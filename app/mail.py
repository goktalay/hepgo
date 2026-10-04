"""Kişisel → Mail (v2, Outlook gibi): kullanıcı başına birden çok hesap — Gmail / Google Workspace, Outlook / Microsoft 365,
Yandex, iCloud, Yahoo, şirket içi Exchange ve diğer IMAP sunucuları, ayrıca POP3. Okuma IMAP (ya da POP3), gönderme SMTP.

Kimlik: uygulama şifresi (password) ya da OAuth yenileme jetonu (google | microsoft) — XOAUTH2 ile girilir. Şifre / jeton
cameras.encrypt ile şifreli saklanır, hiçbir yanıtta dönmez. Her hesap için bir IMAP bağlantısı açık tutulur (5 dk boşta
kalınca kapanır); aynı hesabın istekleri sırayla işlenir. Klasörler özel kullanım işaretlerinden (\\Sent, \\Trash…) ya da
yaygın adlardan (Sent Items, Gönderilmiş Öğeler…) bulunur; diğer klasörler de listelenir. İçerik sunucuda saklanmaz.
"""
import base64
import email
import hashlib
import html as _html
import imaplib
import poplib
import re
import smtplib
import threading
import time
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import formataddr, format_datetime, getaddresses, make_msgid, parseaddr, parsedate_to_datetime

import httpx

from . import config, db, mail_cache
from .cameras import decrypt

TIMEOUT = 20
IDLE_CLOSE = 300
PAGE = 50
imaplib._MAXLINE = 10_000_000   # büyük klasör listeleri
poplib._MAXLINE = 200_000        # HTML gövdelerde tek satır uzun olabilir (önizleme için TOP n 30)

PROVIDERS = {   # anahtar: (başlık, imap, smtp(host, port, güvenlik), oauth, gönderileni sunucu kendisi kaydeder mi, not)
    'gmail': {'title': 'Gmail / Google Workspace', 'imap': ('imap.gmail.com', 993), 'smtp': ('smtp.gmail.com', 465, 'ssl'), 'oauth': 'google',
              'autosent': True, 'help': 'Google hesabında 2 adımlı doğrulama açıkken alınan 16 haneli uygulama şifresi ya da “Google ile bağlan”.'},
    'outlook': {'title': 'Outlook / Microsoft 365', 'imap': ('outlook.office365.com', 993), 'smtp': ('smtp.office365.com', 587, 'starttls'),
                'oauth': 'microsoft', 'autosent': True, 'oauth_only': True,
                'help': 'Microsoft şifreyle IMAP girişini kapattı; “Microsoft ile bağlan” kullanılır.'},
    'yandex': {'title': 'Yandex Mail', 'imap': ('imap.yandex.com', 993), 'smtp': ('smtp.yandex.com', 465, 'ssl'), 'autosent': False,
               'help': 'Yandex ID › Güvenlik › Uygulama şifreleri bölümünden “Mail” için şifre oluşturun.'},
    'icloud': {'title': 'iCloud Mail', 'imap': ('imap.mail.me.com', 993), 'smtp': ('smtp.mail.me.com', 587, 'starttls'), 'autosent': False,
               'help': 'appleid.apple.com › Uygulamaya özel parola.'},
    'yahoo': {'title': 'Yahoo Mail', 'imap': ('imap.mail.yahoo.com', 993), 'smtp': ('smtp.mail.yahoo.com', 465, 'ssl'), 'autosent': True,
              'help': 'Yahoo hesap güvenliği › Uygulama şifresi oluştur.'},
    'imap': {'title': 'Diğer IMAP / Exchange', 'custom': True, 'autosent': False,
             'help': 'Şirket ya da hosting sunucunuzun IMAP ve SMTP bilgileri (Exchange sunucularında IMAP açık olmalı).'},
    'pop3': {'title': 'POP3', 'custom': True, 'pop': True, 'autosent': False,
             'help': 'POP3 yalnızca gelen kutusunu indirir; klasör ve okundu bilgisi sunucuda tutulmaz.'},
}
FOLDERS = [   # anahtar, başlık, özel kullanım işareti, yaygın adlar
    ('inbox', 'Gelen Kutusu', None, ()),
    ('starred', 'Yıldızlı', '\\Flagged', ()),
    ('important', 'Önemli', '\\Important', ()),
    ('drafts', 'Taslaklar', '\\Drafts', ('drafts', 'draft', 'taslaklar', 'inbox.drafts')),
    ('sent', 'Gönderilenler', '\\Sent', ('sent', 'sent items', 'sent mail', 'sent messages', 'gönderilmiş öğeler', 'gönderilenler', 'giden', 'inbox.sent')),
    ('archive', 'Arşiv', '\\Archive', ('archive', 'arşiv', 'arsiv', 'inbox.archive')),
    ('all', 'Tüm Postalar', '\\All', ()),
    ('spam', 'Gereksiz', '\\Junk', ('junk', 'junk e-mail', 'junk email', 'spam', 'gereksiz e-posta', 'istenmeyen', 'inbox.spam', 'inbox.junk')),
    ('trash', 'Çöp Kutusu', '\\Trash', ('trash', 'deleted items', 'deleted messages', 'silinmiş öğeler', 'çöp kutusu', 'cop kutusu', 'inbox.trash', 'bin')),
]
FOLDER_TITLE = {k: t for k, t, _, _ in FOLDERS}


class MailError(Exception):
    pass


# ---------------- OAuth erişim jetonları ----------------
_tokens = {}   # (sağlayıcı, kaynak, jeton özeti) → (erişim jetonu, bitiş)
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
TOKEN_URL = GOOGLE_TOKEN_URL   # geriye uyum


def ms_token_url():
    return f'https://login.microsoftonline.com/{config.MS_TENANT or "common"}/oauth2/v2.0/token'


MS_MAIL_SCOPE = 'https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access'
MS_GRAPH_SCOPE = 'https://graph.microsoft.com/Calendars.Read https://graph.microsoft.com/Contacts.Read offline_access'


def access_token(refresh, kind='google', scope=None):
    """Yenileme jetonundan erişim jetonu (süresi dolmadan önbellekten). Microsoft'ta kaynak (Outlook / Graph) kapsamla seçilir."""
    key = (kind, scope or '', hashlib.sha256(refresh.encode()).hexdigest())
    hit = _tokens.get(key)
    if hit and hit[1] - time.time() > 120:
        return hit[0]
    if kind == 'microsoft':
        url, data = ms_token_url(), {'client_id': config.MS_CLIENT_ID, 'client_secret': config.MS_CLIENT_SECRET, 'refresh_token': refresh,
                                     'grant_type': 'refresh_token', 'scope': scope or MS_MAIL_SCOPE}
        who = 'Microsoft'
    else:
        url, data = GOOGLE_TOKEN_URL, {'client_id': config.GOOGLE_CLIENT_ID, 'client_secret': config.GOOGLE_CLIENT_SECRET,
                                       'refresh_token': refresh, 'grant_type': 'refresh_token'}
        who = 'Google'
    try:
        r = httpx.post(url, data=data, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise MailError(f'{who}\'a bağlanılamadı: {e}') from e
    if r.status_code != 200:
        raise MailError(f'{who} bağlantısının süresi doldu ya da izin geri alındı; Mail Hesaplarım’dan yeniden bağlayın.')
    d = r.json()
    _tokens[key] = (d['access_token'], time.time() + int(d.get('expires_in', 3600)))
    return d['access_token']


def _xoauth(addr, token):
    return f'user={addr}\x01auth=Bearer {token}\x01\x01'


# ---------------- Hesap / bağlantı ----------------
def settings(box):
    """Hesabın sunucu ayarları (hazır sağlayıcı ya da özel)."""
    p = PROVIDERS.get(box.get('provider') or 'imap', PROVIDERS['imap'])
    imap = (box.get('imap_host') or (p.get('imap') or (None, None))[0], int(box.get('imap_port') or (p.get('imap') or (None, 993))[1] or 993))
    smtp = (box.get('smtp_host') or (p.get('smtp') or (None,))[0], int(box.get('smtp_port') or (p.get('smtp') or (None, 465))[1] or 465),
            box.get('smtp_security') or (p.get('smtp') or (None, None, 'ssl'))[2] or 'ssl')
    return {'imap': imap, 'smtp': smtp, 'pop': (box.get('pop_host'), int(box.get('pop_port') or 995)), 'is_pop': (box.get('provider') == 'pop3'),
            'gmail': (box.get('provider') == 'gmail') or (imap[0] or '').endswith('gmail.com')}


class Creds:
    """Hesabın giriş bilgisi: uygulama şifresi ya da OAuth yenileme jetonu."""
    def __init__(self, box):
        self.addr = box['email']
        self.login = (box.get('login') or '').strip() or box['email']
        self.kind = box.get('auth_type') or 'password'
        if self.kind == 'oauth':
            self.kind = 'google'
        self.secret = decrypt(box['secret'])

    def token(self):
        return access_token(self.secret, self.kind)

    def imap_login(self, m):
        if self.kind in ('google', 'microsoft'):
            tok = self.token()
            m.authenticate('XOAUTH2', lambda _: _xoauth(self.addr, tok).encode())
        else:
            m.login(self.login, self.secret)

    def smtp_login(self, s):
        if self.kind in ('google', 'microsoft'):
            s.ehlo()
            code, resp = s.docmd('AUTH', 'XOAUTH2 ' + base64.b64encode(_xoauth(self.addr, self.token()).encode()).decode())
            if code != 235:
                raise smtplib.SMTPAuthenticationError(code, resp)
        else:
            s.login(self.login, self.secret)

    def __eq__(self, other):
        return isinstance(other, Creds) and (self.addr, self.login, self.kind, self.secret) == (other.addr, other.login, other.kind, other.secret)


def friendly(exc, box=None):
    s = str(exc)
    if 'AUTHENTICATIONFAILED' in s or 'Invalid credentials' in s or 'not accepted' in s or '535' in s or 'LOGIN failed' in s or 'authentication failed' in s.lower():
        hint = PROVIDERS.get((box or {}).get('provider') or 'imap', {}).get('help', '')
        return f'Giriş reddedildi. Adresi ve şifreyi kontrol edin. {hint}'.strip()
    if 'IMAP access is disabled' in s or 'Web login required' in s:
        return 'Hesapta IMAP erişimi kapalı; posta ayarlarından IMAP’i açın.'
    return f'Posta sunucusu hatası: {s[:200]}'


def imap_connect(box):
    st = settings(box)
    host, port = st['imap']
    if not host:
        raise MailError('IMAP sunucusu girilmemiş')
    try:
        m = imaplib.IMAP4_SSL(host, port, timeout=TIMEOUT) if port != 143 else imaplib.IMAP4(host, port, timeout=TIMEOUT)
        if port == 143:
            m.starttls()
        Creds(box).imap_login(m)
        return m
    except imaplib.IMAP4.error as e:
        raise MailError(friendly(e, box)) from e
    except OSError as e:
        raise MailError(f'Posta sunucusuna bağlanılamadı ({host}): {e}') from e


def smtp_connect(box):
    st = settings(box)
    host, port, sec = st['smtp']
    if not host:
        raise MailError('SMTP sunucusu girilmemiş')
    try:
        if sec == 'ssl':
            s = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT)
        else:
            s = smtplib.SMTP(host, port, timeout=TIMEOUT)
            s.ehlo()
            s.starttls()
        Creds(box).smtp_login(s)
        return s
    except smtplib.SMTPException as e:
        raise MailError(friendly(e, box)) from e
    except OSError as e:
        raise MailError(f'Gönderim sunucusuna bağlanılamadı ({host}): {e}') from e


class _Conn:
    def __init__(self, box):
        self.box = box
        self.creds = Creds(box)
        self.lock = threading.RLock()
        self.imap = None
        self.used = 0
        self.folders = None
        self.selected = None
        self.uidv = {}   # klasör anahtarı → UIDVALIDITY (önbellek geçerliliği)

    def get(self):
        now = time.time()
        if self.imap and now - self.used > 60:
            try:
                self.imap.noop()
            except Exception:
                self.imap = None
        if not self.imap:
            self.imap, self.selected, self.folders = imap_connect(self.box), None, None
        self.used = now
        return self.imap

    def close(self):
        try:
            self.imap and self.imap.logout()
        except Exception:
            pass
        self.imap = None


_pool, _pool_lock = {}, threading.Lock()


def _reaper():
    while True:
        time.sleep(60)
        with _pool_lock:
            for k, c in list(_pool.items()):
                if time.time() - c.used > IDLE_CLOSE and c.lock.acquire(blocking=False):
                    try:
                        c.close()
                        del _pool[k]
                    finally:
                        c.lock.release()


threading.Thread(target=_reaper, daemon=True, name='mail-reaper').start()


def conn_for(box):
    with _pool_lock:
        c = _pool.get(box['id'])
        creds = Creds(box)
        if not c or c.creds != creds or settings(c.box) != settings(box):
            if c:
                c.close()
            c = _pool[box['id']] = _Conn(box)
        c.box = box
        return c


def drop(box_id):
    with _pool_lock:
        c = _pool.pop(box_id, None)
    if c:
        c.close()


def _run(c, fn):
    """Bağlantı koparsa bir kez yeniden bağlanıp dener."""
    with c.lock:
        for attempt in (0, 1):
            m = c.get()
            try:
                return fn(m)
            except (imaplib.IMAP4.abort, OSError, ConnectionError):
                c.imap = None
                if attempt:
                    raise MailError('Posta sunucusu bağlantısı koptu; tekrar deneyin')


def verify(box):
    """Hesap eklenirken giriş denemesi: IMAP (ya da POP3) + SMTP."""
    if settings(box)['is_pop']:
        p = pop_connect(box)
        p.quit()
    else:
        imap_connect(box).logout()
    smtp_connect(box).quit()


# ---------------- IMAP: klasörler ----------------
_LIST_RE = re.compile(r'\((?P<flags>[^)]*)\) (?:"(?P<sep>[^"]*)"|NIL) (?P<name>.+)')


def utf7_decode(s):
    """IMAP değiştirilmiş UTF-7 klasör adı → okunur metin (ör. G&APY-nderilmi&AV8- → Gönderilmiş)."""
    def dec(mt):
        x = mt.group(1)
        if not x:
            return '&'
        b = x.replace(',', '/')
        b += '=' * (-len(b) % 4)
        try:
            return base64.b64decode(b).decode('utf-16-be')
        except Exception:
            return mt.group(0)
    return re.sub(r'&([^-]*)-', dec, s)


def _mailbox_map(c, m):
    """{anahtar: sunucudaki ad}; özel klasörler 'x:<ad>' anahtarıyla (görünen ad çözülmüş)."""
    if c.folders:
        return c.folders
    typ, data = m.list()
    out, extra = {'inbox': 'INBOX'}, {}
    for raw in data or []:
        line = raw.decode(errors='replace') if isinstance(raw, bytes) else str(raw)
        mt = _LIST_RE.match(line)
        if not mt:
            continue
        flags, name = mt['flags'], mt['name'].strip()
        bare = name.strip('"')
        if '\\Noselect' in flags or '\\NonExistent' in flags or bare.upper() == 'INBOX':
            continue
        key = next((k for k, _, flag, _ in FOLDERS if flag and flag in flags.split()), None)
        if not key:
            low = utf7_decode(bare).lower().rsplit(mt['sep'] or '/', 1)[-1] if mt['sep'] else utf7_decode(bare).lower()
            key = next((k for k, _, _, names in FOLDERS if low in names or utf7_decode(bare).lower() in names), None)
        if key and key not in out:
            out[key] = name
        elif not key:
            extra[f'x:{bare}'] = (name, utf7_decode(bare), mt['sep'] or '')
    c.folders = {**out, **{k: v[0] for k, v in extra.items()}}
    c.extra_titles = {k: v[1] for k, v in extra.items()}
    c.extra_seps = {k: v[2] for k, v in extra.items()}   # hiyerarşi ayırıcısı (Gmail '/', çoğu sunucu '.'): arayüzde ağaç
    return c.folders


def _q(name):
    return name if name.startswith('"') else f'"{name}"'


def _select(c, m, folder, readonly=True):
    box = _mailbox_map(c, m).get(folder)
    if not box:
        raise MailError('Klasör bulunamadı')
    if c.selected != (box, readonly):
        typ, _ = m.select(_q(box), readonly=readonly)
        if typ != 'OK':
            raise MailError('Klasör açılamadı')
        c.selected = (box, readonly)
        try:
            _, uv = m.response('UIDVALIDITY')
            if uv and uv[0]:
                c.uidv[folder] = int(uv[0])
        except (ValueError, TypeError, imaplib.IMAP4.error):
            pass
    return box


def folders(box):
    if settings(box)['is_pop']:
        return pop_folders(box)
    c = conn_for(box)

    def fn(m):
        mp = _mailbox_map(c, m)
        out = []
        for key, title, _, _ in FOLDERS:
            if key not in mp:
                continue
            unseen = None
            if key in ('inbox', 'spam', 'drafts'):
                try:
                    typ, d = m.status(_q(mp[key]), '(UNSEEN MESSAGES)')
                    mt = re.search(rb'UNSEEN (\d+)', d[0] or b'') if typ == 'OK' else None
                    unseen = int(mt.group(1)) if mt else None
                except Exception:
                    unseen = None
            out.append({'key': key, 'title': title, 'unseen': unseen})
        seps = getattr(c, 'extra_seps', {})
        for key, title in sorted(getattr(c, 'extra_titles', {}).items(), key=lambda x: x[1].lower()):
            out.append({'key': key, 'title': title, 'unseen': None, 'custom': True, 'sep': seps.get(key, '')})
        return out
    return _run(c, fn)


def unread(box):
    if settings(box)['is_pop']:
        return 0
    c = conn_for(box)

    def fn(m):
        typ, d = m.status('INBOX', '(UNSEEN)')
        mt = re.search(rb'UNSEEN (\d+)', d[0] or b'') if typ == 'OK' else None
        return int(mt.group(1)) if mt else 0
    return _run(c, fn)


# ---------------- ortak yardımcılar ----------------
def _dec(v):
    try:
        return str(make_header(decode_header(v or '')))
    except Exception:
        return v or ''


def _addr(v):
    name, a = parseaddr(_dec(v))
    return {'name': name or a.split('@')[0], 'email': a}


def _date(v):
    try:
        return parsedate_to_datetime(v).astimezone().isoformat(timespec='seconds') if v else None
    except Exception:
        return None


SNIPPET_BYTES = 6000   # liste önizlemesi için gövdenin yalnız başı okunur (Gmail'deki tek satırlık özet)


def _snippet(hdr_bytes, text, n=180):
    """Kısmi gövdeden (ilk birkaç KB) okunabilir tek satırlık önizleme: ilk düz metin (yoksa HTML) bölüm, alıntılar atılır."""
    if not text:
        return ''
    try:
        msg = email.message_from_bytes(hdr_bytes.rstrip(b'\r\n') + b'\r\n\r\n' + text)
        target = None
        for part in msg.walk():
            if part.is_multipart() or part.get_filename():
                continue
            ct = part.get_content_type()
            if ct == 'text/plain':
                target = part
                break
            if ct == 'text/html' and target is None:
                target = part
        if target is None:
            return ''
        cte = (target.get('Content-Transfer-Encoding') or '').strip().lower()
        if cte == 'base64':   # kesilmiş base64: 4'ün katına indirip çöz
            b = re.sub(r'[^A-Za-z0-9+/=]', '', target.get_payload(decode=False) or '').rstrip('=')
            b = b[:len(b) // 4 * 4]
            data = base64.b64decode(b + '=' * (-len(b) % 4)) if b else b''
        else:
            data = target.get_payload(decode=True) or b''
        cs = target.get_content_charset() or 'utf-8'
        try:
            txt = data.decode(cs, 'replace')
        except LookupError:
            txt = data.decode('utf-8', 'replace')
        if target.get_content_type() == 'text/html':
            txt = re.sub(r'(?is)<(style|script|head|title)[^>]*>.*?(</\1>|$)', ' ', txt)
            txt = re.sub(r'(?s)<!--.*?(-->|$)', ' ', txt)
            txt = re.sub(r'(?s)<[^>]*>?', ' ', txt)
            txt = _html.unescape(txt)
        lines = [ln for ln in txt.splitlines() if not ln.lstrip().startswith('>')]
        txt = re.sub(r'\s+', ' ', ' '.join(lines)).strip()
        txt = re.sub(r'[\u200b-\u200f\u034f\u00ad\ufeff]+', '', txt)
        return txt[:n]
    except Exception:
        return ''


def _summary(uid, hdr_bytes, flags=(), size=0, text=None):
    h = email.message_from_bytes(hdr_bytes, policy=default_policy)
    ctype = (h.get('Content-Type') or '').lower()
    return {'uid': uid, 'from': _addr(h['From']), 'to': _addr(h['To'] or ''), 'subject': _dec(h['Subject']) or '(konu yok)',
            'date': _date(h['Date']), 'seen': '\\Seen' in flags, 'starred': '\\Flagged' in flags,
            'attach': 'multipart/mixed' in ctype, 'invite': 'text/calendar' in ctype, 'size': size,
            'snippet': _snippet(hdr_bytes, text)}


# ---------------- IMAP: liste / okuma / işlemler ----------------
# Liste filtresi ve sıralaması (bütün klasöre uygulanır, yalnız ekrandaki sayfaya değil)
FILTERS = ('unread', 'starred', 'attach')
SORTS = ('date', 'date_asc', 'from', 'subject', 'size')
SORT_MAX = 5000   # sunucu SORT desteklemezse (Gmail) en yeni bu kadar iletinin başlığıyla sıralanır; eskiler tarih sırasıyla sonda
_GM_FILTER = {'unread': 'is:unread', 'starred': 'is:starred', 'attach': 'has:attachment'}
_IMAP_FILTER = {'unread': ['UNSEEN'], 'starred': ['FLAGGED'], 'attach': ['HEADER', 'Content-Type', '"multipart/mixed"']}
_sortkeys = {}   # (hesap, klasör, UIDVALIDITY) → {uid: (gönderen, konu, boyut)} — aynı klasör yeniden sıralanınca tekrar çekilmez
_RE_PREFIX = re.compile(r'^\s*((re|fw|fwd|ynt|ilt|aw|wg|tr)\s*(\[\d+\])?\s*:\s*)+', re.I)


def _search(m, q, gm, filt):
    """Arama + filtre → UID listesi. Gmail: X-GM-RAW (Gmail arama dili); diğerleri: standart IMAP ölçütleri."""
    if gm and (q or filt == 'attach'):   # Gmail arama dili yalnız metin araması / ek için; bayraklar standart IMAP ile
        raw = ' '.join(x for x in (q.replace('"', ' ').strip(), _GM_FILTER.get(filt, '')) if x)
        typ, d = m.uid('SEARCH', 'CHARSET', 'UTF-8', 'X-GM-RAW', f'"{raw}"'.encode())
    else:
        crit = _IMAP_FILTER.get(filt, [])
        if q:   # konu / gönderen / içerik
            try:
                m.literal = q.encode('utf-8')
                typ, d = m.uid('SEARCH', 'CHARSET', 'UTF-8', *crit, 'TEXT')
            except imaplib.IMAP4.error:
                typ, d = m.uid('SEARCH', None, *crit, 'TEXT', f'"{q.encode("ascii", "ignore").decode()}"')
        else:
            typ, d = m.uid('SEARCH', None, *(crit or ['ALL']))
    return [int(x) for x in (d[0] or b'').split()] if typ == 'OK' else []


def _sort_key_from(v):
    name, a = parseaddr(_dec(v))
    return (name.strip(' "\'') or a).casefold()


def _keys_for(c, m, box, folder, uids):
    """Gönderen / konu / boyut sıralama anahtarları; eksikler 500'erli tek FETCH ile (yalnız iki başlık alanı)."""
    ck = (box['id'], folder, c.uidv.get(folder))
    if len(_sortkeys) > 64:
        _sortkeys.clear()
    have = _sortkeys.setdefault(ck, {})
    need = [u for u in uids if u not in have]
    for i in range(0, len(need), 500):
        typ, data = m.uid('FETCH', ','.join(map(str, need[i:i + 500])), '(UID RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])')
        for part in data or []:
            if not isinstance(part, tuple):
                continue
            meta = part[0].decode(errors='replace')
            mu, sz = re.search(r'UID (\d+)', meta), re.search(r'RFC822\.SIZE (\d+)', meta)
            if not mu:
                continue
            h = email.message_from_bytes(part[1] or b'', policy=default_policy)
            subj = _RE_PREFIX.sub('', _dec(h['Subject'])).strip().casefold()
            have[int(mu.group(1))] = (_sort_key_from(h['From']), subj, int(sz.group(1)) if sz else 0)
    return have


def _order(c, m, box, folder, uids, sort, q, gm, filt):
    """UID'leri istenen sıraya koyar → (sıralı UID'ler, yalnız en yeni SORT_MAX içinde mi sıralandı)."""
    if sort == 'date_asc':
        return sorted(uids), False
    newest = sorted(uids, reverse=True)
    if sort not in ('from', 'subject', 'size'):
        return newest, False
    if not gm and not q and 'SORT' in getattr(m, 'capabilities', ()):   # sunucu sıralar (RFC 5256): bütün klasör
        try:
            typ, d = m.uid('SORT', {'from': '(FROM)', 'subject': '(SUBJECT)', 'size': '(REVERSE SIZE)'}[sort], 'UTF-8',
                           *(_IMAP_FILTER.get(filt) or ['ALL']))
            if typ == 'OK':
                ok = set(uids)
                got = [u for u in (int(x) for x in (d[0] or b'').split()) if u in ok]
                if len(got) == len(ok):
                    return got, False
        except imaplib.IMAP4.error:
            pass
    head, rest = newest[:SORT_MAX], newest[SORT_MAX:]
    keys = _keys_for(c, m, box, folder, head)
    if sort == 'size':
        head.sort(key=lambda u: -(keys.get(u) or ('', '', 0))[2])   # kararlı sıralama: eşitlerde yeni önce
    else:
        i = 0 if sort == 'from' else 1
        head.sort(key=lambda u: (keys.get(u) or ('\uffff', '\uffff', 0))[i] or '\uffff')   # boş ad / konu sonda
    return head + rest, bool(rest)


def _fetch_summaries(m, uids):
    """Seçili klasörde UID'lerin liste özetleri → ({uid: özet}, {uid: katılımcı adresleri})."""
    typ, data = m.uid('FETCH', ','.join(map(str, uids)),
                      f'(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE CONTENT-TYPE CONTENT-TRANSFER-ENCODING)] BODY.PEEK[TEXT]<0.{SNIPPET_BYTES}>)')
    got, cur = {}, None   # uid → {hdr, text, flags, size}; gövde parçası UID taşımayabilir → son görülen UID'ye aittir
    for part in data or []:
        if not isinstance(part, tuple):
            continue
        meta, payload = part[0].decode(errors='replace'), part[1]
        mu = re.search(r'UID (\d+)', meta)
        if mu:
            cur = int(mu.group(1))
            d = got.setdefault(cur, {'hdr': b'', 'text': None, 'flags': [], 'size': 0})
            fl = re.search(r'FLAGS \(([^)]*)\)', meta)
            size = re.search(r'RFC822\.SIZE (\d+)', meta)
            d['flags'] = fl.group(1).split() if fl else d['flags']
            d['size'] = int(size.group(1)) if size else d['size']
        if cur is None:
            continue
        if 'BODY[TEXT]' in meta.upper():
            got[cur]['text'] = payload
        else:
            got[cur]['hdr'] = payload
    items = {u: _summary(u, d['hdr'], d['flags'], d['size'], d['text']) for u, d in got.items() if d['hdr']}
    return items, {u: _participants(got[u]['hdr']) for u in items}


def folder_index(box, folder):
    """Klasördeki bütün UID'ler ve bayrakları (tam eşitleme için) → ({uid: (okundu, yıldızlı)}, UIDVALIDITY)."""
    c = conn_for(box)

    def fn(m):
        _select(c, m, folder)
        typ, d = m.uid('SEARCH', None, 'ALL')
        uids = [int(x) for x in (d[0] or b'').split()] if typ == 'OK' else []
        flags = {}
        for i in range(0, len(uids), 1000):
            typ, fl = m.uid('FETCH', ','.join(map(str, uids[i:i + 1000])), '(UID FLAGS)')
            for line in fl or []:
                line = (line[0] if isinstance(line, tuple) else line or b'').decode(errors='replace')
                mu, mf = re.search(r'UID (\d+)', line), re.search(r'FLAGS \(([^)]*)\)', line)
                if mu and mf:
                    f = mf.group(1).split()
                    flags[int(mu.group(1))] = ('\\Seen' in f, '\\Flagged' in f)
        return {u: flags.get(u, (False, False)) for u in uids}, c.uidv.get(folder)
    return _run(c, fn)


def fetch_into_cache(box, folder, uids):
    """Verilen UID'lerin özetlerini sunucudan alıp önbelleğe yazar (tam eşitleme). Yazılan özet sayısı döner."""
    c = conn_for(box)

    def fn(m):
        _select(c, m, folder)
        items, parts = _fetch_summaries(m, uids)
        mail_cache.submit(mail_cache.put_many, box['id'], folder, [(items[u], parts[u]) for u in items])
        return len(items)
    return _run(c, fn)


def list_messages(box, folder='inbox', q='', page=0, unread_only=False, limit=PAGE, offset=None, cache_stats=False, filt=None, sort='date'):
    """offset verilirse sayfa yerine o sıradan başlar (sonsuz kaydırma: arşivle / sil sonrası ileti atlanmasın).
    Önbellekli (mail_cache): sunucudan UID listesi + bayraklar; başlık / önizleme yalnız önbellekte olmayanlar için.
    filt: unread | starred | attach; sort: date | date_asc | from | subject | size (bütün klasöre uygulanır)."""
    start = max(0, offset) if offset is not None else page * limit
    filt = filt if filt in FILTERS else ('unread' if unread_only else None)
    sort = sort if sort in SORTS else 'date'
    if settings(box)['is_pop']:
        return pop_list(box, q, page, filt == 'unread', offset=start)
    if (filt or sort != 'date') and not q and mail_cache.complete(box['id'], folder):   # kayıtlı mailler arasında
        with db.connect() as conn:
            return mail_cache.list_cached(conn, box['id'], folder, filt, sort, start, limit)
    c = conn_for(box)
    gm = settings(box)['gmail']

    def fn(m):
        _select(c, m, folder)
        uids, limited = _order(c, m, box, folder, _search(m, q, gm, filt), sort, q, gm, filt)
        total = len(uids)
        chunk = uids[start:start + limit]
        if not chunk:
            return {'items': [], 'total': total, 'page': page, 'pages': max(1, -(-total // PAGE)), 'fetched': 0}
        uv = c.uidv.get(folder)   # None: sunucu bildirmedi → önbellek durumuna dokunulmaz
        with db.connect() as conn:   # istek içinde yalnız OKUMA; yazmalar mail_cache.submit ile arka planda
            st = mail_cache.state(conn, box['id'], folder, uv) if uv is not None else 'ok'
            cached = mail_cache.get_many(conn, box['id'], folder, chunk) if st != 'changed' else {}
        if st != 'ok':
            mail_cache.submit(mail_cache.set_state, box['id'], folder, uv)
        if cached:   # önbellektekilerin yalnız bayrakları tazelenir (okundu / yıldız başka cihazda değişmiş olabilir)
            typ, fl = m.uid('FETCH', ','.join(map(str, cached)), '(UID FLAGS)')
            flags = {}
            for part in fl or []:
                line = (part[0] if isinstance(part, tuple) else part or b'').decode(errors='replace')
                mu, mf = re.search(r'UID (\d+)', line), re.search(r'FLAGS \(([^)]*)\)', line)
                if mu and mf and int(mu.group(1)) in cached:
                    f = mf.group(1).split()
                    flags[int(mu.group(1))] = ('\\Seen' in f, '\\Flagged' in f)
            for u, (seen, star) in flags.items():
                cached[u].update(seen=seen, starred=star)
            mail_cache.submit(mail_cache.set_flags, box['id'], folder, flags)
        if not q and not filt and sort == 'date':   # sayfa aralığında sunucuda olmayanlar (silinen / taşınan) önbellekten düşer
            mail_cache.submit(mail_cache.prune, box['id'], folder, chunk[-1], chunk[0], set(chunk))
        missing = [u for u in chunk if u not in cached]
        if not missing:
            out = {'items': [cached[u] for u in chunk], 'total': total, 'page': page, 'pages': max(1, -(-total // PAGE)), 'sort_limited': limited}
            return dict(out, fetched=0) if cache_stats else out
        items, parts = _fetch_summaries(m, missing)
        mail_cache.submit(mail_cache.put_many, box['id'], folder, [(items[u], parts[u]) for u in items])
        items.update(cached)
        out = {'items': [items[u] for u in chunk if u in items], 'total': total, 'page': page, 'pages': max(1, -(-total // PAGE)),
               'sort_limited': limited}
        return dict(out, fetched=len(missing)) if cache_stats else out
    return _run(c, fn)


def _participants(hdr_bytes):
    """Başlıktaki tüm e-posta adresleri (kimden / kime / bilgi) — CRM araması için."""
    h = email.message_from_bytes(hdr_bytes, policy=default_policy)
    return [a for _, a in getaddresses([_dec(x) for k in ('From', 'To', 'Cc') for x in h.get_all(k, [])]) if a]


def _fetch_raw(c, m, folder, uid):
    _select(c, m, folder)
    typ, data = m.uid('FETCH', str(uid), '(FLAGS BODY.PEEK[])')
    raw = next((p[1] for p in data or [] if isinstance(p, tuple)), None)
    if typ != 'OK' or not raw:
        raise MailError('E-posta bulunamadı')
    flags = next((p[0].decode(errors='replace') for p in data if isinstance(p, tuple)), '')
    return email.message_from_bytes(raw, policy=default_policy), flags


def _attachments(msg):
    out = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = part.get_content_disposition()
        name = part.get_filename()
        cid = (part.get('Content-ID') or '').strip('<> ')
        if disp == 'attachment' or name or (cid and part.get_content_maintype() == 'image'):
            out.append((part, {'name': _dec(name) if name else (f'resim.{part.get_content_subtype()}' if cid else 'ek'),
                               'type': part.get_content_type(), 'cid': cid or None, 'inline': disp != 'attachment' and bool(cid)}))
    return out


def _render(msg, uid, folder, flags=''):
    html = text = None
    body = msg.get_body(preferencelist=('html', 'plain'))
    if body is not None:
        try:
            content = body.get_content()
        except Exception:
            content = (body.get_payload(decode=True) or b'').decode('utf-8', 'replace')
        if body.get_content_type() == 'text/html':
            html = content
            plain = msg.get_body(preferencelist=('plain',))
            try:
                text = plain.get_content() if plain is not None else None
            except Exception:
                text = None
        else:
            text = content
    files = []
    for i, (part, info) in enumerate(_attachments(msg)):
        payload = part.get_payload(decode=True) or b''
        info = {**info, 'idx': i, 'size': len(payload)}
        if html and info['cid'] and len(payload) < 3_000_000:   # satır içi resim: veri adresi olarak gömülür
            html = html.replace(f'cid:{info["cid"]}', f'data:{info["type"]};base64,{base64.b64encode(payload).decode()}')
        if not info['inline']:
            files.append(info)
    if html:
        html = re.sub(r'(?is)<script.*?</script>', '', html)
    addrs = lambda k: [{'name': n or a, 'email': a} for n, a in getaddresses([_dec(x) for x in msg.get_all(k, [])]) if a]
    return {'uid': uid, 'folder': folder, 'subject': _dec(msg['Subject']) or '(konu yok)', 'date': _date(msg['Date']),
            'from': _addr(msg['From']), 'to': addrs('To'), 'cc': addrs('Cc'), 'reply_to': addrs('Reply-To'),
            'message_id': msg['Message-ID'], 'references': msg['References'],
            'html': html, 'text': text, 'attachments': files, 'starred': '\\Flagged' in flags, 'invite': parse_invite(msg)}


def read(box, folder, uid):
    if settings(box)['is_pop']:
        return pop_read(box, uid)
    c = conn_for(box)
    with db.connect() as conn:
        hit = mail_cache.get_body(conn, box['id'], folder, uid)
    if hit:   # önbellekten anında; okunmadıysa sunucuda okundu işareti arka planda
        rendered, seen = hit
        if not seen and folder != 'drafts':
            threading.Thread(target=_mark_seen, args=(box, folder, uid), daemon=True).start()
        return rendered

    def fn(m):
        msg, flags = _fetch_raw(c, m, folder, uid)
        if '\\Seen' not in flags and folder != 'drafts':   # açınca okundu
            try:
                _select(c, m, folder, readonly=False)
                m.uid('STORE', str(uid), '+FLAGS', '(\\Seen)')
            except Exception:
                pass
        out = _render(msg, uid, folder, flags)
        if folder != 'drafts':   # taslak düzenlenebilir: önbelleğe alınmaz
            if c.uidv.get(folder) is not None:
                mail_cache.submit(mail_cache.set_state, box['id'], folder, c.uidv[folder])
            mail_cache.submit(mail_cache.put_body, box['id'], folder, uid, out,
                              [out['from'].get('email'), *[a['email'] for a in out['to'] + out['cc']]])
        return out
    return _run(c, fn)


def _mark_seen(box, folder, uid):
    try:
        action(box, folder, [uid], 'read')
    except Exception:
        pass


def raw_message(box, folder, uid):
    if settings(box)['is_pop']:
        return pop_raw(box, uid)
    c = conn_for(box)
    return _run(c, lambda m: _fetch_raw(c, m, folder, uid)[0])


def attachment(box, folder, uid, idx):
    msg = raw_message(box, folder, uid)
    atts = _attachments(msg)
    if not 0 <= idx < len(atts):
        raise MailError('Ek bulunamadı')
    part, info = atts[idx]
    return info['name'], info['type'], part.get_payload(decode=True) or b''


def action(box, folder, uids, act, target=None):
    if settings(box)['is_pop']:
        return pop_action(box, uids, act)
    c = conn_for(box)
    ids = ','.join(str(int(u)) for u in uids)
    gm = settings(box)['gmail']

    def move(m, dest):
        typ, _ = m.uid('MOVE', ids, _q(dest))
        if typ != 'OK':   # MOVE desteklemeyen sunucu: kopyala + sil
            m.uid('COPY', ids, _q(dest))
            m.uid('STORE', ids, '+FLAGS', '(\\Deleted)')
            m.expunge()

    def fn(m):
        mp = _mailbox_map(c, m)
        _select(c, m, folder, readonly=False)
        if act in ('read', 'unread'):
            m.uid('STORE', ids, '+FLAGS' if act == 'read' else '-FLAGS', '(\\Seen)')
        elif act in ('star', 'unstar'):
            m.uid('STORE', ids, '+FLAGS' if act == 'star' else '-FLAGS', '(\\Flagged)')
        elif act == 'trash':
            if folder == 'trash' or 'trash' not in mp:   # çöpteyse (ya da çöp klasörü yoksa) kalıcı sil
                m.uid('STORE', ids, '+FLAGS', '(\\Deleted)')
                m.expunge()
            else:
                move(m, mp['trash'])
        elif act == 'archive':
            if gm and folder == 'inbox':   # Gmail: gelen kutusundan kaldırmak = arşivlemek
                m.uid('STORE', ids, '+FLAGS', '(\\Deleted)')
                m.expunge()
            elif 'archive' in mp:
                move(m, mp['archive'])
            else:
                raise MailError('Bu hesapta arşiv klasörü yok')
        elif act == 'spam':
            if 'spam' not in mp:
                raise MailError('Bu hesapta gereksiz klasörü yok')
            move(m, mp['spam'])
        elif act == 'inbox':
            move(m, 'INBOX')
        elif act == 'move':
            if target not in mp:
                raise MailError('Hedef klasör bulunamadı')
            move(m, mp[target])
        else:
            raise MailError('Geçersiz işlem')
        _cache_after(box, folder, uids, act)
        return {'ok': True}
    return _run(c, fn)


def _cache_after(box, folder, uids, act):
    """Sunucudaki işlemi önbelleğe yansıtır: bayrak değişimi güncellenir, taşınan / silinen ileti klasörün önbelleğinden düşer."""
    if act in ('read', 'unread', 'star', 'unstar'):
        col, val = ('seen', act == 'read') if act in ('read', 'unread') else ('starred', act == 'star')
        mail_cache.submit(lambda conn, rows: conn.executemany(f'UPDATE mail_cache SET {col} = ? WHERE box_id = ? AND folder = ? AND uid = ?', rows),
                          [(int(val), box['id'], folder, int(u)) for u in uids])
    else:
        mail_cache.submit(mail_cache.forget, box['id'], folder, list(uids))


# ---------------- Gönderme / taslak ----------------
def build(box, *, to, cc='', bcc='', subject='', body='', html=None, files=(), reply=None):
    addr = box['email']
    msg = EmailMessage()
    msg['From'] = formataddr((box.get('name') or '', addr))
    if to:
        msg['To'] = to
    if cc:
        msg['Cc'] = cc
    if bcc:
        msg['Bcc'] = bcc
    msg['Subject'] = subject
    msg['Date'] = format_datetime(datetime.now(timezone.utc).astimezone())
    msg['Message-ID'] = make_msgid(domain=addr.split('@')[-1])
    if reply and reply.get('message_id'):
        msg['In-Reply-To'] = reply['message_id']
        msg['References'] = f"{reply.get('references') or ''} {reply['message_id']}".strip()
    sig = (box.get('signature') or '').strip()
    text = body or (re.sub(r'<[^>]+>', '', re.sub(r'(?i)<br\s*/?>|</p>|</div>', '\n', html or '')) if html else '')
    if sig:
        text = f'{text}\n\n-- \n{sig}'
    msg.set_content(text)
    esc = lambda s: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    if html:
        safe = re.sub(r'(?is)<script.*?</script>', '', html)
        if sig:
            safe += f'<br><div style="color:#555;white-space:pre-wrap">-- <br>{esc(sig)}</div>'
        msg.add_alternative(f'<div style="font-family:Arial,sans-serif;font-size:14px">{safe}</div>', subtype='html')
    else:
        msg.add_alternative(f'<div style="font-family:Arial,sans-serif;font-size:14px;white-space:pre-wrap">{esc(text)}</div>', subtype='html')
    for name, ctype, data in files:
        maintype, _, subtype = (ctype or 'application/octet-stream').partition('/')
        msg.add_attachment(data, maintype=maintype, subtype=subtype or 'octet-stream', filename=name)
    return msg


def _append(box, folder_key, msg, flags='(\\Seen)'):
    """IMAP klasörüne ileti ekler (Gönderilenler / Taslaklar). Klasör yoksa sessizce geçer."""
    if settings(box)['is_pop']:
        return False
    c = conn_for(box)

    def fn(m):
        mp = _mailbox_map(c, m)
        if folder_key not in mp:
            return False
        bcc = msg['Bcc']
        raw = msg.as_bytes() if not bcc else _without_bcc(msg)
        typ, _ = m.append(_q(mp[folder_key]), flags, imaplib.Time2Internaldate(time.time()), raw)
        c.selected = None
        return typ == 'OK'
    try:
        return _run(c, fn)
    except Exception:
        return False


def _without_bcc(msg):
    import copy
    m2 = copy.deepcopy(msg)
    del m2['Bcc']
    return m2.as_bytes()


def send(box, *, to, cc='', bcc='', subject='', body='', html=None, files=(), reply=None, forward=None, draft_uid=None):
    """files: [(ad, tür, bayt)]; reply: {message_id, references}; forward: {folder, uid} → orijinal ekler eklenir."""
    extra = list(files)
    if forward:
        orig = raw_message(box, forward['folder'], int(forward['uid']))
        extra += [(info['name'], info['type'], part.get_payload(decode=True) or b'') for part, info in _attachments(orig) if not info['inline']]
    msg = build(box, to=to, cc=cc, bcc=bcc, subject=subject, body=body, html=html, files=extra, reply=reply)
    rcpts = [a for _, a in getaddresses([x for x in (to, cc, bcc) if x and x.strip()]) if a]   # boş alan ayrıştırmayı bozar
    if not rcpts:
        raise MailError('Alıcı adresi girin')
    s = smtp_connect(box)
    try:
        sendable = email.message_from_bytes(_without_bcc(msg), policy=default_policy)
        s.send_message(sendable, from_addr=box['email'], to_addrs=rcpts)
        s.quit()
    except smtplib.SMTPException as e:
        raise MailError(friendly(e, box)) from e
    except OSError as e:
        raise MailError(f'Gönderim sunucusuna bağlanılamadı: {e}') from e
    saved = False
    if box.get('save_sent') and not PROVIDERS.get(box.get('provider') or 'imap', {}).get('autosent'):
        saved = _append(box, 'sent', msg)
    if draft_uid:
        try:
            action(box, 'drafts', [draft_uid], 'trash')
        except Exception:
            pass
    return {'ok': True, 'recipients': len(rcpts), 'saved_to_sent': saved, 'rcpts': rcpts}


def save_draft(box, *, to='', cc='', bcc='', subject='', body='', html=None, files=(), reply=None, replace_uid=None):
    msg = build(box, to=to, cc=cc, bcc=bcc, subject=subject, body=body, html=html, files=files, reply=reply)
    ok = _append(box, 'drafts', msg, '(\\Draft \\Seen)')
    if not ok:
        raise MailError('Bu hesapta taslak klasörü bulunamadı')
    if replace_uid:
        try:
            action(box, 'drafts', [replace_uid], 'trash')
        except Exception:
            pass
    return {'ok': True}


# ---------------- POP3 ----------------
_pop_cache = {}   # box id → (zaman, [(uidl, no, başlık özeti)])
_pop_locks = {}


def pop_connect(box):
    host, port = settings(box)['pop']
    if not host:
        raise MailError('POP3 sunucusu girilmemiş')
    try:
        p = poplib.POP3_SSL(host, port, timeout=TIMEOUT) if port != 110 else poplib.POP3(host, port, timeout=TIMEOUT)
        if port == 110:
            p.stls()
        cr = Creds(box)
        p.user(cr.login)
        p.pass_(cr.secret)
        return p
    except poplib.error_proto as e:
        raise MailError(friendly(e, box)) from e
    except OSError as e:
        raise MailError(f'POP3 sunucusuna bağlanılamadı ({host}): {e}') from e


def _pop_index(box, fresh=False):
    """Son 300 ileti: (uidl, no, başlık + gövdenin ilk 30 satırı). Önceki dizindeki iletiler yeniden indirilmez (UIDL değişmez);
    aynı hesap için eşzamanlı istekler tek dizini paylaşır."""
    def cached():
        hit = _pop_cache.get(box['id'])
        return hit[1] if hit and not fresh and time.time() - hit[0] < 60 else None
    if (out := cached()) is not None:
        return out
    with _pop_locks.setdefault(box['id'], threading.Lock()):
        if (out := cached()) is not None:   # başka istek az önce tazeledi
            return out
        old = {u: top for u, _, top in (_pop_cache.get(box['id']) or (0, []))[1]}
        p = pop_connect(box)
        try:
            resp, lines, _ = p.uidl()
            idx = []
            for ln in lines:
                no, uidl = ln.decode(errors='replace').split(' ', 1)
                idx.append((uidl.strip(), int(no)))
            out = []
            for uidl, no in idx[-300:]:
                top = old.get(uidl)
                if top is None:
                    try:
                        _, hl, _ = p.top(no, 30)
                    except poplib.error_proto:   # aşırı uzun satır: bağlantı yanıtın ortasında kalır → yeniden bağlan, yalnız başlık
                        p.close()
                        p = pop_connect(box)
                        _, hl, _ = p.top(no, 0)
                    top = b'\r\n'.join(hl) + b'\r\n'
                out.append((uidl, no, top))
        except (poplib.error_proto, OSError) as e:
            raise MailError(f'POP3 sunucusu yanıtı okunamadı: {e}') from e
        finally:
            try:
                p.quit()
            except Exception:
                pass
        _pop_cache[box['id']] = (time.time(), out)
        return out


def _pop_seen(box):
    from . import db
    conn = db.connect()
    try:
        return {r[0] for r in conn.execute('SELECT uidl FROM mail_pop_seen WHERE box_id = ?', (box['id'],))}
    finally:
        conn.close()


def _pop_uid(uidl):
    return int(hashlib.sha1(uidl.encode()).hexdigest()[:12], 16)   # istemciye sayısal kimlik


def pop_folders(box):
    seen = _pop_seen(box)
    return [{'key': 'inbox', 'title': 'Gelen Kutusu', 'unseen': sum(1 for u, _, _ in _pop_index(box) if u not in seen)}]


def pop_list(box, q='', page=0, unread_only=False, offset=None):
    seen = _pop_seen(box)
    items = []
    for uidl, no, top in reversed(_pop_index(box)):
        hdr, _, text = top.partition(b'\r\n\r\n')
        s = _summary(_pop_uid(uidl), hdr + b'\r\n\r\n', ['\\Seen'] if uidl in seen else [], text=text)
        if q and q.lower() not in f"{s['subject']} {s['from']['name']} {s['from']['email']}".lower():
            continue
        if unread_only and s['seen']:
            continue
        items.append(s)
    total, start = len(items), (page * PAGE if offset is None else offset)
    return {'items': items[start:start + PAGE], 'total': total, 'page': page, 'pages': max(1, -(-total // PAGE))}


def _pop_find(box, uid):
    for uidl, no, _ in _pop_index(box):
        if _pop_uid(uidl) == uid:
            return uidl, no
    raise MailError('E-posta bulunamadı')


def pop_raw(box, uid):
    uidl, no = _pop_find(box, uid)
    p = pop_connect(box)
    try:
        _, lines, _ = p.retr(no)
    finally:
        try:
            p.quit()
        except Exception:
            pass
    return email.message_from_bytes(b'\r\n'.join(lines), policy=default_policy)


def pop_read(box, uid):
    from . import db
    msg = pop_raw(box, uid)
    uidl, _ = _pop_find(box, uid)
    conn = db.connect()
    try:
        conn.execute('INSERT OR IGNORE INTO mail_pop_seen (box_id, uidl) VALUES (?,?)', (box['id'], uidl))
        conn.commit()
    finally:
        conn.close()
    return _render(msg, uid, 'inbox', '\\Seen')


def pop_action(box, uids, act):
    from . import db
    found = [_pop_find(box, u) for u in uids]
    if act in ('read', 'unread'):
        conn = db.connect()
        try:
            for uidl, _ in found:
                if act == 'read':
                    conn.execute('INSERT OR IGNORE INTO mail_pop_seen (box_id, uidl) VALUES (?,?)', (box['id'], uidl))
                else:
                    conn.execute('DELETE FROM mail_pop_seen WHERE box_id = ? AND uidl = ?', (box['id'], uidl))
            conn.commit()
        finally:
            conn.close()
        return {'ok': True}
    if act == 'trash':   # POP3: sunucudan kalıcı silinir
        p = pop_connect(box)
        try:
            for _, no in found:
                p.dele(no)
        finally:
            p.quit()
        _pop_cache.pop(box['id'], None)
        return {'ok': True}
    raise MailError('POP3 hesabında bu işlem yapılamaz')


# ---------------- Takvim daveti (ICS) ----------------
def _ics_unfold(text):
    return re.sub(r'\r?\n[ \t]', '', text)


def _ics_dt(v, params=''):
    """ICS tarih → (ISO yerel, tüm gün mü)."""
    v = v.strip()
    try:
        if 'VALUE=DATE' in params or re.fullmatch(r'\d{8}', v):
            return f'{v[:4]}-{v[4:6]}-{v[6:8]}T00:00:00', True
        if v.endswith('Z'):
            dt = datetime.strptime(v, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).astimezone()
            return dt.replace(tzinfo=None).isoformat(timespec='seconds'), False
        dt = datetime.strptime(v[:15], '%Y%m%dT%H%M%S')
        return dt.isoformat(timespec='seconds'), False
    except ValueError:
        return None, False


def parse_ics(text):
    """İlk VEVENT: {uid, title, starts_at, ends_at, all_day, location, description, organizer, method, status}."""
    t = _ics_unfold(text)
    method = (re.search(r'(?m)^METHOD:(.+)$', t) or [None, ''])[1].strip().upper()
    ev = re.search(r'(?s)BEGIN:VEVENT(.*?)END:VEVENT', t)
    if not ev:
        return None
    props = {}
    for line in ev.group(1).splitlines():
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        name, _, params = k.partition(';')
        props.setdefault(name.upper(), (params, v))
    get = lambda n: props.get(n, ('', ''))[1].replace('\\n', '\n').replace('\\,', ',').replace('\\;', ';').strip()
    start, all_day = _ics_dt(*reversed(props.get('DTSTART', ('', '')))) if 'DTSTART' in props else (None, False)
    end, _ = _ics_dt(*reversed(props.get('DTEND', ('', '')))) if 'DTEND' in props else (None, False)
    if not start:
        return None
    org = get('ORGANIZER')
    return {'uid': get('UID') or hashlib.sha1(t.encode()).hexdigest(), 'title': get('SUMMARY') or '(başlıksız etkinlik)', 'starts_at': start,
            'ends_at': end, 'all_day': all_day, 'location': get('LOCATION') or None, 'description': get('DESCRIPTION')[:2000] or None,
            'organizer': org.replace('mailto:', '').replace('MAILTO:', '') or None, 'method': method or 'PUBLISH',
            'status': 'cancelled' if method == 'CANCEL' or get('STATUS').upper() == 'CANCELLED' else ('tentative' if method == 'REQUEST' else 'confirmed')}


def parse_invite(msg):
    for part in msg.walk():
        if part.get_content_type() == 'text/calendar' or (part.get_filename() or '').lower().endswith('.ics'):
            try:
                raw = part.get_payload(decode=True) or b''
                return parse_ics(raw.decode('utf-8', 'replace'))
            except Exception:
                return None
    return None
