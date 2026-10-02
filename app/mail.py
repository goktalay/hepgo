"""Kişisel → Mail: kullanıcının Gmail hesabına IMAP (okuma) ve SMTP (gönderme) ile bağlanır.

Kimlik iki türlüdür: (1) "Google ile bağlan" (OAuth, kurumsal Google Workspace hesapları için): Google'ın izin ekranından
alınan yenileme jetonu saklanır, IMAP/SMTP'ye XOAUTH2 ile girilir; (2) kişisel Gmail için 16 haneli "Uygulama şifresi".
Jeton / şifre cameras.encrypt ile şifrelenmiş saklanır. Her kullanıcı için bir IMAP bağlantısı açık tutulur (5 dk boşta kalınca kapanır);
aynı kullanıcının istekleri sırayla işlenir. Klasörler Gmail'in özel kullanım işaretlerinden (\\Sent, \\Trash…) bulunur,
böylece Türkçe arayüzlü hesaplarda da çalışır. Arama Gmail sözdizimiyle yapılır (X-GM-RAW; ör. from:ali has:attachment).
"""
import base64
import email
import imaplib
import re
import smtplib
import threading
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import formataddr, getaddresses, make_msgid, parseaddr, parsedate_to_datetime

import httpx

from . import config
from .cameras import decrypt

TOKEN_URL = 'https://oauth2.googleapis.com/token'
_tokens = {}   # yenileme jetonu özeti → (erişim jetonu, bitiş)


def access_token(refresh):
    """OAuth yenileme jetonundan erişim jetonu (süresi dolmadan önbellekten)."""
    import hashlib
    key = hashlib.sha256(refresh.encode()).hexdigest()
    hit = _tokens.get(key)
    if hit and hit[1] - time.time() > 120:
        return hit[0]
    try:
        r = httpx.post(TOKEN_URL, data={'client_id': config.GOOGLE_CLIENT_ID, 'client_secret': config.GOOGLE_CLIENT_SECRET,
                                        'refresh_token': refresh, 'grant_type': 'refresh_token'}, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise MailError(f'Google\'a bağlanılamadı: {e}') from e
    if r.status_code != 200:
        raise MailError('Google bağlantısının süresi doldu ya da izin geri alındı; Mail ayarlarından yeniden "Google ile bağlan" yapın.')
    d = r.json()
    _tokens[key] = (d['access_token'], time.time() + int(d.get('expires_in', 3600)))
    return d['access_token']


def _xoauth(addr, token):
    return f'user={addr}\x01auth=Bearer {token}\x01\x01'


class Creds:
    """Hesabın giriş bilgisi: uygulama şifresi ya da OAuth yenileme jetonu."""
    def __init__(self, account):
        self.addr = account['email']
        self.kind = account.get('auth_type') or 'password'
        self.secret = decrypt(account['secret'])

    def imap_login(self, m):
        if self.kind == 'oauth':
            tok = access_token(self.secret)
            m.authenticate('XOAUTH2', lambda _: _xoauth(self.addr, tok).encode())
        else:
            m.login(self.addr, self.secret)

    def smtp_login(self, s):
        if self.kind == 'oauth':
            s.ehlo()
            code, resp = s.docmd('AUTH', 'XOAUTH2 ' + base64.b64encode(_xoauth(self.addr, access_token(self.secret)).encode()).decode())
            if code != 235:
                raise smtplib.SMTPAuthenticationError(code, resp)
        else:
            s.login(self.addr, self.secret)

    def __eq__(self, other):
        return isinstance(other, Creds) and (self.addr, self.kind, self.secret) == (other.addr, other.kind, other.secret)

IMAP_HOST, SMTP_HOST = 'imap.gmail.com', 'smtp.gmail.com'
TIMEOUT = 20
IDLE_CLOSE = 300
PAGE = 50
FOLDERS = [   # anahtar, başlık, özel kullanım işareti
    ('inbox', 'Gelen Kutusu', None), ('starred', 'Yıldızlı', '\\Flagged'), ('important', 'Önemli', '\\Important'),
    ('sent', 'Gönderilenler', '\\Sent'), ('drafts', 'Taslaklar', '\\Drafts'), ('all', 'Tüm Postalar', '\\All'),
    ('spam', 'Spam', '\\Junk'), ('trash', 'Çöp Kutusu', '\\Trash'),
]
imaplib._MAXLINE = 10_000_000   # büyük klasör listeleri


class MailError(Exception):
    pass


def friendly(exc):
    s = str(exc)
    if 'AUTHENTICATIONFAILED' in s or 'Invalid credentials' in s or 'Username and Password not accepted' in s or '535' in s:
        return ('Gmail girişi reddedildi. Adresi ve 16 haneli uygulama şifresini kontrol edin (normal Gmail şifresi çalışmaz; '
                'Google hesabında 2 adımlı doğrulama açık olmalı).')
    if 'IMAP access is disabled' in s or 'Web login required' in s:
        return 'Gmail ayarlarında IMAP erişimi kapalı; Gmail → Ayarlar → Yönlendirme ve POP/IMAP bölümünden açın.'
    return f'Gmail bağlantı hatası: {s[:200]}'


def _dec(v):
    try:
        return str(make_header(decode_header(v or '')))
    except Exception:
        return v or ''


# ---------- IMAP bağlantı havuzu
class _Conn:
    def __init__(self, creds):
        self.creds = creds
        self.lock = threading.RLock()
        self.imap = None
        self.used = 0
        self.folders = None
        self.selected = None

    def get(self):
        now = time.time()
        if self.imap and now - self.used > 60:
            try:
                self.imap.noop()
            except Exception:
                self.imap = None
        if not self.imap:
            try:
                m = imaplib.IMAP4_SSL(IMAP_HOST, 993, timeout=TIMEOUT)
                self.creds.imap_login(m)
            except imaplib.IMAP4.error as e:
                raise MailError(friendly(e)) from e
            except OSError as e:
                raise MailError(f'Gmail sunucusuna bağlanılamadı: {e}') from e
            self.imap, self.selected = m, None
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
            for uid, c in list(_pool.items()):
                if time.time() - c.used > IDLE_CLOSE and c.lock.acquire(blocking=False):
                    try:
                        c.close()
                        del _pool[uid]
                    finally:
                        c.lock.release()


threading.Thread(target=_reaper, daemon=True, name='mail-reaper').start()


def conn_for(account):
    with _pool_lock:
        c = _pool.get(account['user_id'])
        creds = Creds(account)
        if not c or c.creds != creds:
            if c:
                c.close()
            c = _pool[account['user_id']] = _Conn(creds)
        return c


def drop(user_id):
    with _pool_lock:
        c = _pool.pop(user_id, None)
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
                    raise MailError('Gmail bağlantısı koptu; tekrar deneyin')


# ---------- test (hesap bağlama)
def verify(account):
    """account: {'email', 'secret' (şifreli), 'auth_type'} — IMAP ve SMTP girişini dener."""
    creds = Creds(account)
    try:
        m = imaplib.IMAP4_SSL(IMAP_HOST, 993, timeout=TIMEOUT)
        creds.imap_login(m)
        m.logout()
        s = smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=TIMEOUT)
        creds.smtp_login(s)
        s.quit()
    except (imaplib.IMAP4.error, smtplib.SMTPException) as e:
        raise MailError(friendly(e)) from e
    except OSError as e:
        raise MailError(f'Gmail sunucusuna bağlanılamadı: {e}') from e


# ---------- klasörler
_LIST_RE = re.compile(r'\((?P<flags>[^)]*)\) "(?P<sep>[^"]*)" (?P<name>.+)')


def _mailbox_map(c, m):
    if c.folders:
        return c.folders
    typ, data = m.list()
    out = {'inbox': 'INBOX'}
    for raw in data or []:
        line = raw.decode(errors='replace') if isinstance(raw, bytes) else str(raw)
        mt = _LIST_RE.match(line)
        if not mt:
            continue
        flags, name = mt['flags'], mt['name'].strip()
        for key, _, flag in FOLDERS:
            if flag and flag in flags.split():
                out[key] = name
    c.folders = out
    return out


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
    return box


def folders(account):
    c = conn_for(account)

    def fn(m):
        mp = _mailbox_map(c, m)
        out = []
        for key, title, _ in FOLDERS:
            if key not in mp:
                continue
            unseen = None
            if key in ('inbox', 'spam', 'drafts'):
                typ, d = m.status(_q(mp[key]), '(UNSEEN MESSAGES)')
                mt = re.search(rb'UNSEEN (\d+)', d[0] or b'') if typ == 'OK' else None
                unseen = int(mt.group(1)) if mt else None
            out.append({'key': key, 'title': title, 'unseen': unseen})
        return out
    return _run(c, fn)


def unread(account):
    c = conn_for(account)

    def fn(m):
        typ, d = m.status('INBOX', '(UNSEEN)')
        mt = re.search(rb'UNSEEN (\d+)', d[0] or b'') if typ == 'OK' else None
        return int(mt.group(1)) if mt else 0
    return _run(c, fn)


# ---------- liste
def _addr(v):
    name, a = parseaddr(_dec(v))
    return {'name': name or a.split('@')[0], 'email': a}


def list_messages(account, folder='inbox', q='', page=0, unread_only=False):
    c = conn_for(account)

    def fn(m):
        _select(c, m, folder)
        if q:
            typ, d = m.uid('SEARCH', 'CHARSET', 'UTF-8', 'X-GM-RAW', f'"{q.replace(chr(34), " ")}"'.encode())
        else:
            typ, d = m.uid('SEARCH', None, 'UNSEEN' if unread_only else 'ALL')
        uids = [int(x) for x in (d[0] or b'').split()] if typ == 'OK' else []
        uids.sort(reverse=True)
        total = len(uids)
        chunk = uids[page * PAGE:(page + 1) * PAGE]
        if not chunk:
            return {'items': [], 'total': total, 'page': page, 'pages': max(1, -(-total // PAGE))}
        typ, data = m.uid('FETCH', ','.join(map(str, chunk)),
                          '(UID FLAGS RFC822.SIZE X-GM-THRID BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE CONTENT-TYPE)])')
        items = {}
        for part in data or []:
            if not isinstance(part, tuple):
                continue
            meta, hdr = part[0].decode(errors='replace'), part[1]
            uid = int(re.search(r'UID (\d+)', meta).group(1))
            flags = re.search(r'FLAGS \(([^)]*)\)', meta)
            flags = flags.group(1).split() if flags else []
            size = re.search(r'RFC822\.SIZE (\d+)', meta)
            h = email.message_from_bytes(hdr, policy=default_policy)
            try:
                dt = parsedate_to_datetime(h['Date']).astimezone().isoformat(timespec='seconds') if h['Date'] else None
            except Exception:
                dt = None
            ctype = (h.get('Content-Type') or '').lower()
            items[uid] = {'uid': uid, 'from': _addr(h['From']), 'to': [_addr(x) for x in [h['To'] or '']][0],
                          'subject': _dec(h['Subject']) or '(konu yok)', 'date': dt,
                          'seen': '\\Seen' in flags, 'starred': '\\Flagged' in flags,
                          'attach': 'multipart/mixed' in ctype, 'size': int(size.group(1)) if size else 0}
        return {'items': [items[u] for u in chunk if u in items], 'total': total, 'page': page, 'pages': max(1, -(-total // PAGE))}
    return _run(c, fn)


# ---------- okuma
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


def read(account, folder, uid):
    import base64
    c = conn_for(account)

    def fn(m):
        msg, flags = _fetch_raw(c, m, folder, uid)
        html = text = None
        body = msg.get_body(preferencelist=('html', 'plain'))
        if body is not None:
            content = body.get_content()
            if body.get_content_type() == 'text/html':
                html = content
                plain = msg.get_body(preferencelist=('plain',))
                text = plain.get_content() if plain is not None else None
            else:
                text = content
        atts = _attachments(msg)
        files = []
        for i, (part, info) in enumerate(atts):
            payload = part.get_payload(decode=True) or b''
            info = {**info, 'idx': i, 'size': len(payload)}
            if html and info['cid'] and len(payload) < 3_000_000:   # satır içi resim: veri adresi olarak gömülür
                html = html.replace(f'cid:{info["cid"]}', f'data:{info["type"]};base64,{base64.b64encode(payload).decode()}')
            if not info['inline']:
                files.append(info)
        if html:
            html = re.sub(r'(?is)<script.*?</script>', '', html)
        if '\\Seen' not in flags and folder != 'drafts':   # açınca okundu
            try:
                _select(c, m, folder, readonly=False)
                m.uid('STORE', str(uid), '+FLAGS', '(\\Seen)')
            except Exception:
                pass
        try:
            dt = parsedate_to_datetime(msg['Date']).astimezone().isoformat(timespec='seconds') if msg['Date'] else None
        except Exception:
            dt = None
        addrs = lambda k: [{'name': n or a, 'email': a} for n, a in getaddresses([_dec(x) for x in msg.get_all(k, [])]) if a]
        return {'uid': uid, 'folder': folder, 'subject': _dec(msg['Subject']) or '(konu yok)', 'date': dt,
                'from': _addr(msg['From']), 'to': addrs('To'), 'cc': addrs('Cc'), 'reply_to': addrs('Reply-To'),
                'message_id': msg['Message-ID'], 'references': msg['References'],
                'html': html, 'text': text, 'attachments': files, 'starred': '\\Flagged' in flags}
    return _run(c, fn)


def attachment(account, folder, uid, idx):
    c = conn_for(account)

    def fn(m):
        msg, _ = _fetch_raw(c, m, folder, uid)
        atts = _attachments(msg)
        if not 0 <= idx < len(atts):
            raise MailError('Ek bulunamadı')
        part, info = atts[idx]
        return info['name'], info['type'], part.get_payload(decode=True) or b''
    return _run(c, fn)


# ---------- işlemler
def action(account, folder, uids, act):
    c = conn_for(account)
    ids = ','.join(str(int(u)) for u in uids)

    def fn(m):
        mp = _mailbox_map(c, m)
        _select(c, m, folder, readonly=False)
        if act in ('read', 'unread'):
            m.uid('STORE', ids, '+FLAGS' if act == 'read' else '-FLAGS', '(\\Seen)')
        elif act in ('star', 'unstar'):
            m.uid('STORE', ids, '+FLAGS' if act == 'star' else '-FLAGS', '(\\Flagged)')
        elif act == 'trash':
            if folder == 'trash':   # çöpteyse kalıcı sil
                m.uid('STORE', ids, '+FLAGS', '(\\Deleted)')
                m.expunge()
            else:
                typ, _ = m.uid('MOVE', ids, _q(mp['trash']))
                if typ != 'OK':
                    m.uid('COPY', ids, _q(mp['trash']))
                    m.uid('STORE', ids, '+FLAGS', '(\\Deleted)')
                    m.expunge()
        elif act == 'archive':   # Gmail: gelen kutusundan kaldırmak = arşivlemek
            if folder != 'inbox':
                raise MailError('Yalnızca gelen kutusundaki e-posta arşivlenir')
            m.uid('STORE', ids, '+FLAGS', '(\\Deleted)')
            m.expunge()
        elif act == 'spam':
            m.uid('MOVE', ids, _q(mp['spam']))
        elif act == 'inbox':   # spam / çöpten gelen kutusuna geri al
            m.uid('MOVE', ids, 'INBOX')
        else:
            raise MailError('Geçersiz işlem')
        return {'ok': True}
    return _run(c, fn)


# ---------- gönderme
def send(account, *, to, cc='', bcc='', subject='', body='', files=(), reply=None, forward=None):
    """files: [(ad, tür, bayt)]; reply: {message_id, references}; forward: {folder, uid} → orijinal ekler eklenir."""
    addr = account['email']
    msg = EmailMessage()
    msg['From'] = formataddr((account.get('name') or '', addr))
    creds = Creds(account)
    msg['To'] = to
    if cc:
        msg['Cc'] = cc
    msg['Subject'] = subject
    msg['Message-ID'] = make_msgid(domain=addr.split('@')[-1])
    if reply and reply.get('message_id'):
        msg['In-Reply-To'] = reply['message_id']
        msg['References'] = f"{reply.get('references') or ''} {reply['message_id']}".strip()
    text = body or ''
    if account.get('signature'):
        text = f'{text}\n\n-- \n{account["signature"]}'
    msg.set_content(text)
    esc = lambda s: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    msg.add_alternative(f'<div style="font-family:Arial,sans-serif;font-size:14px;white-space:pre-wrap">{esc(text)}</div>', subtype='html')
    extra = list(files)
    if forward:
        c = conn_for(account)

        def fwd(m):
            orig, _ = _fetch_raw(c, m, forward['folder'], int(forward['uid']))
            return [(info['name'], info['type'], part.get_payload(decode=True) or b'') for part, info in _attachments(orig) if not info['inline']]
        extra += _run(c, fwd)
    for name, ctype, data in extra:
        maintype, _, subtype = (ctype or 'application/octet-stream').partition('/')
        msg.add_attachment(data, maintype=maintype, subtype=subtype or 'octet-stream', filename=name)
    rcpts = [a for _, a in getaddresses([x for x in (to, cc, bcc) if x and x.strip()]) if a]   # boş alan ayrıştırmayı bozar
    if not rcpts:
        raise MailError('Alıcı adresi girin')
    try:
        s = smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=TIMEOUT)
        creds.smtp_login(s)
        s.send_message(msg, from_addr=addr, to_addrs=rcpts)
        s.quit()
    except smtplib.SMTPException as e:
        raise MailError(friendly(e)) from e
    except OSError as e:
        raise MailError(f'Gmail sunucusuna bağlanılamadı: {e}') from e
    return {'ok': True, 'recipients': len(rcpts)}
