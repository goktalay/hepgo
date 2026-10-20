"""Kişisel → Mail API'si (v2, çok hesaplı). Yalnızca kullanıcının kendi hesapları; yönetici dahil kimse başkasının postalarını
göremez. Şifre / jeton hiçbir yanıtta dönmez. Hız için liste özetleri ve açılan iletiler hesap sahibine özel önbellekte
(mail_cache) tutulur; hesap kaldırılınca önbelleği de silinir. Yalnızca hesap bağlama / ayırma ve gönderim sayısı loglanır. Klasör anahtarı '/' içerebildiği için ?folder= ile taşınır."""
import re
import secrets
import time
from typing import List, Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from .. import auth, config, db, mail, mail_cache, mail_import, person_emails, personal
from ..cameras import decrypt, encrypt

router = APIRouter(prefix='/api/mail')
MAX_ATTACH = 25 * 1024 * 1024
_unread_cache = {}   # user_id → (zaman, sayı)
PUBLIC = ('id', 'email', 'login', 'name', 'provider', 'auth_type', 'imap_host', 'imap_port', 'pop_host', 'pop_port', 'smtp_host', 'smtp_port',
          'smtp_security', 'save_sent', 'signature', 'color', 'sort', 'auto_import', 'sync_calendar', 'sync_contacts', 'last_ok', 'last_error',
          'last_sync', 'sync_error', 'created_at')


def _wrap(fn):
    try:
        return fn()
    except mail.MailError as e:
        raise HTTPException(400, str(e)) from e


def _box(conn, user, box_id):
    b = db.row(conn.execute('SELECT * FROM mail_boxes WHERE id = ? AND user_id = ?', (box_id, user['id'])))
    if not b:
        raise HTTPException(404, 'Mail hesabı bulunamadı')
    return b


def _boxes(conn, user):
    return db.rows(conn.execute('SELECT * FROM mail_boxes WHERE user_id = ? ORDER BY sort, id', (user['id'],)))


def _public(b):
    out = {k: b.get(k) for k in PUBLIC}
    out['needs_reauth'] = mail.needs_reauth(b)   # Ayarlar › Mail Hesaplarım: "Yeniden bağlan" düğmesi
    return out


def oauth_available():
    return {'google': bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET), 'microsoft': bool(config.MS_CLIENT_ID and config.MS_CLIENT_SECRET)}


def unread_count(conn, user):
    """Bildirim / pano / Kişisel sayısı: tüm hesapların gelen kutularındaki okunmamış (60 sn önbellek; hata olursa önceki)."""
    hit = _unread_cache.get(user['id'])
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    n, failed = 0, False
    for b in _boxes(conn, user):
        try:
            n += mail.unread(b)
        except Exception:
            failed = True
    if failed and hit and not n:
        n = hit[1]   # sunucu geçici erişilemezse önceki sayı korunur
    _unread_cache[user['id']] = (time.time(), n)
    return n


_preview_cache = {}   # user_id → (zaman, sayı, son okunmamışlar)


def unread_preview(conn, user):
    """Bildirim için: okunmamış sayısı + en yeni 5 okunmamış e-postanın gönderen / konu / içerik özeti.
    Gövde PEEK ile okunur (okundu işaretlenmez); sayı değişmedikçe 10 dk önbellekten."""
    n = unread_count(conn, user)
    hit = _preview_cache.get(user['id'])
    if hit and hit[1] == n and time.time() - hit[0] < 600:
        return n, hit[2]
    items = []
    if n:
        for b in _boxes(conn, user):
            if b['provider'] == 'pop3':
                continue
            try:
                r = mail.list_messages(b, 'inbox', '', 0, True, limit=5)
            except Exception:
                continue
            items += [dict(it, box_id=b['id'], box_email=b['email']) for it in r['items']]
        items.sort(key=lambda x: x.get('date') or '', reverse=True)
        items = items[:5]
    _preview_cache[user['id']] = (time.time(), n, items)
    return n, items


# ---------------- hesaplar ----------------
@router.get('/providers')
def providers(user=Depends(auth.current_user)):
    return {'providers': {k: {kk: v for kk, v in p.items()} for k, p in mail.PROVIDERS.items()}, 'oauth': oauth_available()}


@router.get('/boxes')
def boxes(user=Depends(auth.current_user), conn=db.DB):
    return {'boxes': [_public(b) for b in _boxes(conn, user)], 'oauth': oauth_available(), 'can_import': 'documents' in user['modules']}


class BoxIn(BaseModel):
    email: str
    password: Optional[str] = None
    provider: str = 'imap'
    name: Optional[str] = None
    login: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    pop_host: Optional[str] = None
    pop_port: Optional[int] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_security: Optional[str] = None


def _host(v):
    return ''.join(ch for ch in (v or '').strip() if ch.isalnum() or ch in '.-') or None


@router.post('/boxes')
def add_box(body: BoxIn, user=Depends(auth.current_user), conn=db.DB):
    addr = body.email.strip().lower()
    prov = body.provider if body.provider in mail.PROVIDERS else 'imap'
    p = mail.PROVIDERS[prov]
    pw = (body.password or '').strip()
    if prov in ('gmail', 'yahoo', 'icloud', 'yandex'):
        pw = pw.replace(' ', '')   # uygulama şifreleri 4'lü gruplar halinde gösterilir
    if '@' not in addr or not pw:
        raise HTTPException(400, 'E-posta adresini ve şifreyi girin')
    if p.get('oauth_only'):
        raise HTTPException(400, f"{p['title']} hesapları şifreyle bağlanamaz; “Microsoft ile bağlan” kullanın")
    if conn.execute('SELECT 1 FROM mail_boxes WHERE user_id = ? AND email = ?', (user['id'], addr)).fetchone():
        raise HTTPException(409, 'Bu adres zaten ekli')
    box = {'id': 0, 'user_id': user['id'], 'email': addr, 'login': (body.login or '').strip() or None, 'provider': prov, 'auth_type': 'password',
           'secret': encrypt(pw), 'imap_host': _host(body.imap_host), 'imap_port': body.imap_port, 'pop_host': _host(body.pop_host), 'pop_port': body.pop_port,
           'smtp_host': _host(body.smtp_host), 'smtp_port': body.smtp_port,
           'smtp_security': body.smtp_security if body.smtp_security in ('ssl', 'starttls') else None}
    if p.get('custom') and not ((box['imap_host'] or box['pop_host']) and box['smtp_host']):
        raise HTTPException(400, 'Gelen (IMAP / POP3) ve giden (SMTP) sunucu adreslerini girin')
    _wrap(lambda: mail.verify(box))
    bid = _insert(conn, user, box, body.name)
    return _public(_box(conn, user, bid))


def _insert(conn, user, box, name=None):
    sort = (conn.execute('SELECT MAX(sort) FROM mail_boxes WHERE user_id = ?', (user['id'],)).fetchone()[0] or 0) + 1
    autosent = mail.PROVIDERS.get(box['provider'], {}).get('autosent')
    cur = conn.execute('''INSERT INTO mail_boxes (user_id, email, login, name, provider, auth_type, secret, imap_host, imap_port, pop_host, pop_port,
                          smtp_host, smtp_port, smtp_security, save_sent, sort, last_ok, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (user['id'], box['email'], box.get('login'), (name or user['full_name']).strip(), box['provider'], box['auth_type'], box['secret'],
                        box.get('imap_host'), box.get('imap_port'), box.get('pop_host'), box.get('pop_port'), box.get('smtp_host'), box.get('smtp_port'),
                        box.get('smtp_security'), 0 if autosent else 1, sort, db.now(), db.now()))
    _unread_cache.pop(user['id'], None)
    db.audit(conn, user['id'], 'Mail hesabı bağladı', 'mail', cur.lastrowid, f"{box['email']} ({box['provider']}, {box['auth_type']})")
    conn.commit()
    return cur.lastrowid


class BoxUpd(BaseModel):
    name: Optional[str] = None
    signature: Optional[str] = None
    color: Optional[str] = None
    save_sent: Optional[bool] = None
    auto_import: Optional[bool] = None
    sync_calendar: Optional[bool] = None
    sync_contacts: Optional[bool] = None
    password: Optional[str] = None


@router.put('/boxes/{box_id}')
def update_box(box_id: int, body: BoxUpd, user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    if body.password:
        if b['auth_type'] != 'password':
            raise HTTPException(400, 'Bu hesap OAuth ile bağlı; şifre değiştirilemez')
        trial = dict(b, secret=encrypt(body.password.strip().replace(' ', '') if b['provider'] in ('gmail', 'yahoo', 'icloud', 'yandex') else body.password.strip()))
        _wrap(lambda: mail.verify(trial))
        conn.execute('UPDATE mail_boxes SET secret = ?, last_error = NULL, last_ok = ? WHERE id = ?', (trial['secret'], db.now(), box_id))
        mail.drop(box_id)
    sets = {'name': (body.name or '').strip() or None if body.name is not None else None, 'signature': (body.signature or '').strip()[:4000] or None if body.signature is not None else None,
            'color': (body.color or '')[:20] or None if body.color is not None else None}
    for k, v in sets.items():
        if getattr(body, k) is not None:
            conn.execute(f'UPDATE mail_boxes SET {k} = ? WHERE id = ?', (v, box_id))
    for k in ('save_sent', 'auto_import', 'sync_calendar', 'sync_contacts'):
        if getattr(body, k) is not None:
            conn.execute(f'UPDATE mail_boxes SET {k} = ? WHERE id = ?', (int(getattr(body, k)), box_id))
    conn.commit()
    return _public(_box(conn, user, box_id))


class OrderIn(BaseModel):
    ids: List[int]


@router.put('/boxes-order')
def order(body: OrderIn, user=Depends(auth.current_user), conn=db.DB):
    for i, bid in enumerate(body.ids):
        conn.execute('UPDATE mail_boxes SET sort = ? WHERE id = ? AND user_id = ?', (i, bid, user['id']))
    conn.commit()
    return {'ok': True}


@router.delete('/boxes/{box_id}')
def delete_box(box_id: int, user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    if b['auth_type'] == 'google':   # Google'daki izni de geri al
        try:
            httpx.post('https://oauth2.googleapis.com/revoke', data={'token': decrypt(b['secret'])}, timeout=10)
        except Exception:
            pass
    conn.execute('DELETE FROM personal_events WHERE box_id = ?', (box_id,))
    conn.execute('DELETE FROM mail_boxes WHERE id = ?', (box_id,))
    # Bu sağlayıcıya bağlı başka hesabı kalmadıysa oradan alınan rehber kişileri de silinir (Google API veri politikası)
    if b['auth_type'] in ('google', 'microsoft') and not conn.execute(
            'SELECT 1 FROM mail_boxes WHERE user_id = ? AND auth_type = ?', (user['id'], b['auth_type'])).fetchone():
        conn.execute('DELETE FROM personal_contacts WHERE user_id = ? AND source = ?', (user['id'], b['auth_type']))
    mail.drop(box_id)
    _unread_cache.pop(user['id'], None)
    db.audit(conn, user['id'], 'Mail hesabını ayırdı', 'mail', box_id, b['email'])
    conn.commit()
    return {'ok': True}


# ---------------- OAuth: Google / Microsoft ile bağlan ----------------
_states = {}   # durum jetonu → (kullanıcı, sağlayıcı, zaman)
G_AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'
G_SCOPES = ('https://mail.google.com/ openid email https://www.googleapis.com/auth/calendar.readonly '
            'https://www.googleapis.com/auth/contacts.readonly https://www.googleapis.com/auth/contacts.other.readonly')


def _base(request):
    """OAuth dönüş adresinin tabanı: kullanıcının girdiği alan adı (oturum çerezi o alan adında). Yerel / IP erişiminde PUBLIC_URL."""
    host = (request.headers.get('x-forwarded-host') or request.headers.get('host') or '').split(',')[0].strip()
    name = host.split(':')[0]
    if not host or name in ('localhost', '127.0.0.1', 'testserver') or name.replace('.', '').isdigit():
        return config.PUBLIC_URL or f"{request.url.scheme}://{host}"
    proto = request.headers.get('x-forwarded-proto', '').split(',')[0].strip() or ('https' if '.' in name else request.url.scheme)
    return f'{proto}://{host}'


def _redirect_uri(request, prov):
    return f'{_base(request)}/api/mail/oauth/{prov}/callback'


@router.get('/oauth/{prov}/start')
def oauth_start(prov: str, request: Request, hint: str = '', user=Depends(auth.current_user)):
    """Yetki adresi. hint: yeniden bağlamada aynı hesabın e-postası (sağlayıcı hesap seçiminde onu önerir)."""
    av = oauth_available()
    if prov not in av:
        raise HTTPException(404, 'Bilinmeyen sağlayıcı')
    if not av[prov]:
        raise HTTPException(400, f"{'Google' if prov == 'google' else 'Microsoft'} ile bağlanma bu sunucuda henüz ayarlanmadı (Program Ayarları › Entegrasyonlar)")
    now = time.time()
    for k in [k for k, v in _states.items() if now - v[2] > 600]:
        _states.pop(k, None)
    state = secrets.token_urlsafe(24)
    _states[state] = (user['id'], prov, now)
    if prov == 'google':
        q = {'client_id': config.GOOGLE_CLIENT_ID, 'redirect_uri': _redirect_uri(request, prov), 'response_type': 'code', 'scope': G_SCOPES,
             'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true', 'state': state}
        if '@' in hint:
            q['login_hint'] = hint.strip()[:200]
        return {'url': f'{G_AUTH}?{urlencode(q)}'}
    q = {'client_id': config.MS_CLIENT_ID, 'redirect_uri': _redirect_uri(request, prov), 'response_type': 'code', 'response_mode': 'query',
         'scope': f'openid email profile offline_access {mail.MS_MAIL_SCOPE} https://graph.microsoft.com/Calendars.Read https://graph.microsoft.com/Contacts.Read',
         'prompt': 'select_account', 'state': state}
    if '@' in hint:
        q['login_hint'] = hint.strip()[:200]
    return {'url': f'https://login.microsoftonline.com/{config.MS_TENANT or "common"}/oauth2/v2.0/authorize?{urlencode(q)}'}


@router.get('/oauth/{prov}/callback')
def oauth_callback(prov: str, request: Request, state: str = '', code: str = '', error: str = '', user=Depends(auth.current_user), conn=db.DB):
    back = lambda msg: RedirectResponse(f'/app#/settings/mailboxes?msg={quote(msg, safe="")}', status_code=303)
    st = _states.pop(state, None)
    if not st or st[0] != user['id'] or st[1] != prov or time.time() - st[2] > 600:
        return back('Bağlantı isteği geçersiz ya da süresi doldu; yeniden deneyin')
    if error or not code:
        return back('İzin verilmedi')
    try:
        if prov == 'google':
            r = httpx.post(mail.GOOGLE_TOKEN_URL, data={'code': code, 'client_id': config.GOOGLE_CLIENT_ID, 'client_secret': config.GOOGLE_CLIENT_SECRET,
                                                        'redirect_uri': _redirect_uri(request, prov), 'grant_type': 'authorization_code'}, timeout=20)
            tok = r.json()
            if r.status_code != 200 or 'refresh_token' not in tok:
                return back('Google jetonu alınamadı; yeniden deneyin')
            info = httpx.get('https://openidconnect.googleapis.com/v1/userinfo', headers={'Authorization': f'Bearer {tok["access_token"]}'}, timeout=20).json()
            addr, provider, name = (info.get('email') or '').lower(), 'gmail', info.get('name')
        else:
            r = httpx.post(mail.ms_token_url(), data={'code': code, 'client_id': config.MS_CLIENT_ID, 'client_secret': config.MS_CLIENT_SECRET,
                                                      'redirect_uri': _redirect_uri(request, prov), 'grant_type': 'authorization_code',
                                                      'scope': mail.MS_MAIL_SCOPE}, timeout=20)
            tok = r.json()
            if r.status_code != 200 or 'refresh_token' not in tok:
                return back('Microsoft jetonu alınamadı; yeniden deneyin')
            import base64
            import json as _j
            idt = tok.get('id_token', '').split('.')
            claims = _j.loads(base64.urlsafe_b64decode(idt[1] + '=' * (-len(idt[1]) % 4))) if len(idt) > 1 else {}
            addr = (claims.get('email') or claims.get('preferred_username') or '').lower()
            provider, name = 'outlook', claims.get('name')
    except (httpx.HTTPError, ValueError):
        return back('Sağlayıcıya bağlanılamadı')
    if not addr:
        return back('Hesabın e-posta adresi alınamadı')
    box = {'id': 0, 'user_id': user['id'], 'email': addr, 'provider': provider, 'auth_type': prov, 'secret': encrypt(tok['refresh_token'])}
    try:
        mail.verify(box)
    except mail.MailError as e:
        return back(str(e))
    old = conn.execute('SELECT id FROM mail_boxes WHERE user_id = ? AND email = ?', (user['id'], addr)).fetchone()
    if old:
        conn.execute('UPDATE mail_boxes SET secret = ?, auth_type = ?, provider = ?, last_error = NULL, last_ok = ? WHERE id = ?',
                     (box['secret'], prov, provider, db.now(), old[0]))
        conn.commit()
        mail.drop(old[0])
        bid = old[0]
    else:
        bid = _insert(conn, user, box, name)
    try:   # takvim / kişiler ilk eşitleme
        personal.sync_box(conn, _box(conn, user, bid))
    except Exception:
        pass
    return back('ok')


# ---------------- klasörler / liste / okuma ----------------
@router.get('/{box_id}/folders')
def folders(box_id: int, user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    try:
        out = mail.folders(b)
        conn.execute('UPDATE mail_boxes SET last_ok = ?, last_error = NULL WHERE id = ?', (db.now(), box_id))
        conn.commit()
        return out
    except mail.MailError as e:
        conn.execute('UPDATE mail_boxes SET last_error = ? WHERE id = ?', (str(e)[:300], box_id))
        conn.commit()
        raise HTTPException(400, str(e)) from e


# ---------------- kişi ↔ firma (Firmalar › kişiler e-postasıyla eşleşir) ----------------
def company_map(conn, emails):
    """E-posta → firma kişisi {person_id, person_name, title, company_id, company_name} (büyük/küçük harf duyarsız)."""
    ems = sorted({(e or '').strip().lower() for e in emails if e and '@' in e})
    out = {}
    for i in range(0, len(ems), 400):
        part = ems[i:i + 400]
        q = ",".join("?" * len(part))
        for r in conn.execute(f'''SELECT e, pid, full_name, title, cid, cname FROM (
                                    SELECT lower(trim(p.email)) AS e, p.id AS pid, p.full_name, p.title, c.id AS cid, c.name AS cname
                                    FROM company_people p JOIN companies c ON c.id = p.company_id WHERE lower(trim(p.email)) IN ({q})
                                    UNION ALL
                                    SELECT x.email, p.id, p.full_name, p.title, c.id, c.name FROM person_emails x
                                    JOIN company_people p ON p.id = x.ref_id JOIN companies c ON c.id = x.company_id
                                    WHERE x.kind = 'company' AND x.email IN ({q}))
                                  ORDER BY pid DESC''', (*part, *part)):   # en son atanan geçerli; ek adresler de tanınır
            out.setdefault(r[0], {'person_id': r[1], 'person_name': r[2], 'title': r[3], 'company_id': r[4], 'company_name': r[5]})
    return out


def _annotate(conn, items):
    cm = company_map(conn, [x for it in items for x in ((it.get('from') or {}).get('email'), (it.get('to') or {}).get('email'))])
    for it in items:
        c = cm.get(((it.get('from') or {}).get('email') or '').lower()) or cm.get(((it.get('to') or {}).get('email') or '').lower())
        it['company'] = c['company_name'] if c else None
    return items


def _co_write(user, supplier):
    """Firmalar'daki kural: tedarikçi → Satın Alma, diğer firmalar → Firma Yönetimi (yazma yetkisi)."""
    return ('purchasing' if supplier else 'companies') in user.get('write_modules', user['modules'])


def _can_assign(user):
    return _co_write(user, False) or _co_write(user, True)


@router.get('/{box_id}/list')
def messages(box_id: int, folder: str = 'inbox', q: str = '', page: int = 0, offset: Optional[int] = None, unread: bool = False,
             filter: str = '', sort: str = 'date', user=Depends(auth.current_user), conn=db.DB):
    """filter: unread | starred | attach; sort: date | date_asc | from | subject | size. Klasör önbellekte tamsa sıralama /
    filtre kayıtlı mailler arasında yapılır (hızlı); değilse sunucudan."""
    b = _box(conn, user, box_id)
    r = _wrap(lambda: mail.list_messages(b, folder, q.strip()[:300], max(0, page), unread, offset=offset,
                                         filt=filter or None, sort=sort))
    _annotate(conn, r['items'])
    return r


@router.post('/{box_id}/cache-sync')
def folder_sync(box_id: int, folder: str = 'inbox', user=Depends(auth.current_user), conn=db.DB):
    """Klasörün bütün iletilerini önbelleğe almayı başlatır (sürüyorsa yenisini başlatmaz) ve ilerlemeyi döner."""
    b = _box(conn, user, box_id)
    if mail.settings(b)['is_pop']:
        return {'total': 0, 'done': 0, 'running': False, 'pop': True}
    if not mail_cache.complete(b['id'], folder):
        mail_cache.start_full_sync(b, folder)
    return _sync_view(b['id'], folder)


@router.get('/{box_id}/cache-sync')
def folder_sync_state(box_id: int, folder: str = 'inbox', user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    return _sync_view(b['id'], folder)


def _sync_view(box_id, folder):
    p = mail_cache.progress(box_id, folder)
    return {'total': p.get('total', 0), 'done': p.get('done', 0), 'running': bool(p.get('running')),
            'complete': mail_cache.complete(box_id, folder), 'error': p.get('error')}


# "Tüm Hesaplar" birleşik görünümde desteklenen temel klasör anahtarları
_UNIFIED_FOLDERS = {'inbox', 'starred', 'important', 'sent', 'drafts', 'archive', 'all', 'spam', 'trash'}


def _unified(conn, user, folder, q, filt, sort):
    """Tüm hesapların AYNI temel klasörünü (folder anahtarı) birleştirir (en yeni PAGE); hatalı/klasörü olmayan hesap atlanır."""
    items, errors = [], []
    for b in _boxes(conn, user):
        try:
            r = mail.list_messages(b, folder, q.strip()[:300], 0, False, filt=filt or None, sort=sort)
            items += [dict(it, box_id=b['id'], box_email=b['email'], box_color=b['color']) for it in r['items']]
        except Exception as e:   # noqa: BLE001 — bu hesapta klasör yoksa / erişilemezse atla, bildir
            errors.append({'box_id': b['id'], 'email': b['email'], 'error': str(e)[:200]})
    items.sort(key=lambda x: x.get('date') or '', reverse=sort != 'date_asc')
    if sort == 'from':
        items.sort(key=lambda x: mail_cache._tr_key((x.get('from') or {}).get('name') or (x.get('from') or {}).get('email')))
    elif sort == 'subject':
        items.sort(key=lambda x: mail_cache._tr_key(mail_cache._PREFIX.sub('', x.get('subject') or '')))
    elif sort == 'size':
        items.sort(key=lambda x: -(x.get('size') or 0))
    return {'items': _annotate(conn, items[:mail.PAGE]), 'errors': errors}


@router.get('/unified/inbox')
def unified(folder: str = 'inbox', q: str = '', filter: str = '', sort: str = 'date', user=Depends(auth.current_user), conn=db.DB):
    """Tüm hesapların AYNI temel klasörü birlikte (folder: inbox/spam/trash/sent/drafts/archive/starred…).
    NOT: yol '/unified/list' KULLANMA — '/{box_id}/list' (box_id:int) ile çakışır ve 422 verir; bu uç folder param'ı alır."""
    if folder not in _UNIFIED_FOLDERS:
        folder = 'inbox'
    return _unified(conn, user, folder, q, filter, sort)


@router.get('/{box_id}/msg')
def read(box_id: int, folder: str, uid: int, user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    _unread_cache.pop(user['id'], None)
    d = _wrap(lambda: mail.read(b, folder, uid))
    addrs = [d['from'], *d['to'], *d['cc'], *d.get('reply_to', [])]
    d['people'] = company_map(conn, [a.get('email') for a in addrs])
    fixed = False
    for a in addrs:   # firmada adı e-posta adresi olarak kaydedilmiş kişi: mailde adı görünüyorsa adı düzeltilir
        e = (a.get('email') or '').lower()
        co = d['people'].get(e)
        nm = (a.get('name') or '').strip()
        if co and nm and '@' not in nm and (co['person_name'] or '').strip().lower() == e:
            conn.execute('UPDATE company_people SET full_name = ? WHERE id = ?', (nm[:200], co['person_id']))
            co['person_name'] = nm[:200]
            fixed = True
    if fixed:
        conn.commit()
    d['can_assign'] = bool(_can_assign(user))
    try:   # yazışılan kişi rehbere; davet takvime (hesapta takvim eşitlemesi açıksa)
        personal.collect(conn, user['id'], [(d['from']['name'], d['from']['email'])], own=[x['email'] for x in _boxes(conn, user)])
        if d.get('invite') and b['sync_calendar']:
            personal.upsert_event(conn, user['id'], box_id, 'ics', d['invite'])
            d['invite']['added'] = True
        conn.commit()
    except Exception:
        pass
    return d


@router.get('/{box_id}/att')
def attachment(box_id: int, folder: str, uid: int, idx: int, inline: bool = False, user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    name, ctype, data = _wrap(lambda: mail.attachment(b, folder, uid, idx))
    safe = ctype if ctype.split('/')[0] in ('image', 'audio', 'video') or ctype == 'application/pdf' else 'application/octet-stream'
    disp = 'inline' if inline and safe != 'application/octet-stream' else 'attachment'
    return Response(data, media_type=safe, headers={
        'Content-Disposition': f"{disp}; filename*=UTF-8''{quote(name)}",
        'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox", 'Cache-Control': 'private, max-age=3600'})


class InviteIn(BaseModel):
    folder: str
    uid: int


@router.post('/{box_id}/invite')
def add_invite(box_id: int, body: InviteIn, user=Depends(auth.current_user), conn=db.DB):
    """Davetteki etkinliği Kişisel Takvim'e ekler."""
    b = _box(conn, user, box_id)
    msg = _wrap(lambda: mail.raw_message(b, body.folder, body.uid))
    ev = mail.parse_invite(msg)
    if not ev:
        raise HTTPException(400, 'Bu e-postada takvim daveti yok')
    personal.upsert_event(conn, user['id'], box_id, 'ics', ev)
    conn.commit()
    return {'ok': True, 'event': ev}


class ImportIn(BaseModel):
    folder: str
    uid: int


@router.post('/{box_id}/import')
def import_attachments(box_id: int, body: ImportIn, user=Depends(auth.current_user), conn=db.DB):
    """E-postanın eklerini "Yalnızca ben" görünürlüğünde evraklara kaydeder (OCR uygulanır)."""
    if 'documents' not in user['modules']:
        raise HTTPException(403, 'Evrak Yönetimi yetkiniz yok')
    b = _box(conn, user, box_id)
    ids = _wrap(lambda: mail_import.import_message(conn, user, b, body.folder, body.uid))
    return {'imported': len(ids), 'ids': ids}


class ActionIn(BaseModel):
    folder: str
    uids: list[int]
    action: str
    target: Optional[str] = None


@router.post('/{box_id}/action')
def act(box_id: int, body: ActionIn, user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    if not body.uids or len(body.uids) > 500:
        raise HTTPException(400, 'E-posta seçin')
    _unread_cache.pop(user['id'], None)
    return _wrap(lambda: mail.action(b, body.folder, body.uids, body.action, body.target))


async def _files(files):
    parts, total = [], 0
    for f in files or []:
        if not f.filename:
            continue
        data = await f.read()
        total += len(data)
        if total > MAX_ATTACH:
            raise HTTPException(400, 'Ekler toplam 25 MB sınırını aşıyor')
        parts.append((f.filename, f.content_type or 'application/octet-stream', data))
    return parts


def _doc_files(conn, user, doc_ids, have=0):
    """Sistemdeki evraklardan ek: yalnız kullanıcının görebildiği evraklar (Evrak Yönetimi görünürlük kuralları).
    doc_ids: '12,15' → [(dosya adı, tür, bayt)]; toplam ek sınırı dosyalarla birlikte uygulanır."""
    ids = [int(x) for x in str(doc_ids or '').replace(' ', '').split(',') if x.isdigit()][:20]
    if not ids:
        return []
    from .documents import visible_ids
    ok = visible_ids(conn, user)
    if any(i not in ok for i in ids):
        raise HTTPException(403, 'Eklemek istediğiniz evraklardan birini görme yetkiniz yok')
    import mimetypes
    out, total = [], have
    for d in db.rows(conn.execute(f'SELECT id, file, file_name FROM documents WHERE id IN ({",".join("?" * len(ids))})', ids)):
        path = (config.UPLOAD_DIR / d['file']).resolve()
        if config.UPLOAD_DIR.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404, f"Evrak dosyası bulunamadı: {d['file_name']}")
        data = path.read_bytes()
        total += len(data)
        if total > MAX_ATTACH:
            raise HTTPException(400, 'Ekler toplam 25 MB sınırını aşıyor')
        out.append((d['file_name'], mimetypes.guess_type(d['file_name'])[0] or 'application/octet-stream', data))
    return out


@router.post('/{box_id}/send')
async def send(box_id: int, to: str = Form(''), cc: str = Form(''), bcc: str = Form(''), subject: str = Form(''), body: str = Form(''),
               html: str = Form(''), reply_id: str = Form(''), references: str = Form(''), fwd_folder: str = Form(''), fwd_uid: int = Form(0),
               draft_uid: int = Form(0), doc_ids: str = Form(''), files: list[UploadFile] = File(default=[]),
               user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    parts = await _files(files)
    parts += _doc_files(conn, user, doc_ids, sum(len(x[2]) for x in parts))

    def go():
        return mail.send(b, to=to, cc=cc, bcc=bcc, subject=subject, body=body, html=html or None, files=parts,
                         reply={'message_id': reply_id, 'references': references} if reply_id else None,
                         forward={'folder': fwd_folder, 'uid': fwd_uid} if fwd_folder and fwd_uid else None, draft_uid=draft_uid or None)
    r = await run_in_threadpool(lambda: _wrap(go))
    from email.utils import getaddresses
    personal.collect(conn, user['id'], getaddresses([x for x in (to, cc, bcc) if x]), own=[x['email'] for x in _boxes(conn, user)])
    db.audit(conn, user['id'], 'E-posta gönderdi', 'mail', box_id,
             f'{r["recipients"]} alıcı' + (f' · evrak eki: {doc_ids}' if doc_ids else ''))   # içerik loglanmaz; eklenen evrak numaraları kayıtlı
    conn.commit()
    r.pop('rcpts', None)
    return r


@router.post('/{box_id}/draft')
async def draft(box_id: int, to: str = Form(''), cc: str = Form(''), bcc: str = Form(''), subject: str = Form(''), body: str = Form(''),
                html: str = Form(''), reply_id: str = Form(''), references: str = Form(''), replace_uid: int = Form(0),
                doc_ids: str = Form(''), files: list[UploadFile] = File(default=[]), user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    parts = await _files(files)
    parts += _doc_files(conn, user, doc_ids, sum(len(x[2]) for x in parts))
    return await run_in_threadpool(lambda: _wrap(lambda: mail.save_draft(b, to=to, cc=cc, bcc=bcc, subject=subject, body=body, html=html or None, files=parts,
                                                                          reply={'message_id': reply_id, 'references': references} if reply_id else None,
                                                                          replace_uid=replace_uid or None)))


@router.post('/{box_id}/sync')
def sync(box_id: int, user=Depends(auth.current_user), conn=db.DB):
    """Google / Outlook takvimi ve kişileri şimdi eşitle."""
    b = _box(conn, user, box_id)
    try:
        r = personal.sync_box(conn, b)
    except mail.MailError as e:
        raise HTTPException(400, str(e)) from e
    if r is None:
        raise HTTPException(400, 'Takvim / kişi eşitlemesi yalnızca “Google ile” ya da “Microsoft ile” bağlanan hesaplarda yapılır; davetler mailden otomatik eklenir')
    return r


@router.get('/companies/{cid}/people')
def company_people(cid: int, user=Depends(auth.current_user), conn=db.DB):
    """Atama penceresi: firmanın kişileri (adres "mevcut kişiye ek adres" olarak eklenebilsin)."""
    if not _can_assign(user):
        raise HTTPException(403, 'Kişiyi firmaya atamak için Firma Yönetimi yetkisi gerekir')
    rows = db.rows(conn.execute(f'SELECT id, full_name, title, email, company_id FROM company_people p WHERE {person_emails.member_sql()} '
                                'ORDER BY full_name', (cid, cid)))
    return person_emails.attach(conn, 'company', rows)


@router.get('/people/pick')
def people_pick(q: str = '', user=Depends(auth.current_user), conn=db.DB):
    """Yeni mail › Kişi ekle: Rehber'de erişilebilen, e-postası olan kişiler (firma kişileri — müşteri / tedarikçi yetkisine
    göre — ve sistem kullanıcıları). Ad, e-posta ya da FİRMA ADIYLA aranır; her adres kendi firmasıyla ayrı satır."""
    from .companies import people_of
    from ..document_ocr import fold
    words = fold(q).split()
    out = []
    for sup, mod in ((False, 'companies'), (True, 'purchasing')):
        if mod not in user['modules']:
            continue
        for p in people_of(conn, sup):
            for e in p.get('email_list') or []:
                out.append({'kind': 'person', 'id': p['id'], 'name': p['full_name'], 'email': e['email'], 'title': p.get('title'),
                            'company': e.get('company_name') or '', 'supplier': sup})
    for u in conn.execute("SELECT id, full_name, username FROM users WHERE deleted_at IS NULL AND active = 1 AND username LIKE '%@%'"):
        out.append({'kind': 'user', 'id': u[0], 'name': u[1], 'email': u[2].lower(), 'title': None, 'company': config.COMPANY_NAME, 'supplier': False})
    seen, res = set(), []
    for r in out:
        key = (r['email'], r['company'])
        if key in seen:
            continue
        hay = fold(f"{r['name']} {r['email']} {r['company']}")
        if all(w in hay for w in words):
            seen.add(key)
            res.append(r)
    res.sort(key=lambda r: (fold(r['name']), r['company']))
    return res[:60]


@router.get('/people/companies')
def recipients_companies(emails: str = '', user=Depends(auth.current_user), conn=db.DB):
    """Yeni mail › Evrak ekle: alıcıların bağlı olduğu firmalar ("seçili firmaya etiketli evraklar" için)."""
    cm = company_map(conn, [e.strip() for e in emails.split(',')][:50])
    seen = {}
    for v in cm.values():
        if v.get('company_id'):
            seen.setdefault(v['company_id'], {'id': v['company_id'], 'name': v['company_name']})
    return sorted(seen.values(), key=lambda c: c['name'] or '')


# ---------------- Kişiler / Cariler görünümü (kayıtlı mailler) ----------------
_stats_cache = {}   # kullanıcı → (zaman, istatistik)


def _view_boxes(conn, user):
    bs = [b for b in _boxes(conn, user) if not mail.settings(b)['is_pop']]
    return [b['id'] for b in bs], [b['email'] for b in _boxes(conn, user)]


def _stats(conn, user):
    hit = _stats_cache.get(user['id'])
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    ids, own = _view_boxes(conn, user)
    st = mail_cache.addr_stats(conn, ids, own)
    _stats_cache[user['id']] = (time.time(), st)
    return st


@router.get('/view/people')
def view_people(user=Depends(auth.current_user), conn=db.DB):
    """Mail › Kişiler: maillerdeki adresler. Rehber'de bilinenler (firma kişisi — firmasız dahil — ya da sistem kullanıcısı; bir
    kişinin bütün adresleri tek satırda) üstte ada göre; bilinmeyen adresler altta, son yazışmaya göre."""
    from ..document_ocr import fold
    st = _stats(conn, user)
    owner = {}   # adres → ('person' | 'user', id)
    if {'companies', 'purchasing'} & set(user['modules']):
        for e, pid in conn.execute("""SELECT lower(trim(email)), id FROM company_people WHERE email LIKE '%@%'
                                      UNION ALL SELECT email, ref_id FROM person_emails WHERE kind = 'company'"""):
            if e in st:
                owner.setdefault(e, ('person', pid))
    for uid, e in conn.execute("SELECT id, lower(username) FROM users WHERE deleted_at IS NULL AND username LIKE '%@%'"):
        if e in st:
            owner.setdefault(e, ('user', uid))
    pids = sorted({i for k, i in owner.values() if k == 'person'})
    people = {r['id']: r for r in person_emails.attach(conn, 'company', db.rows(conn.execute(
        f'SELECT id, full_name, email, company_id FROM company_people WHERE id IN ({",".join("?" * len(pids))})', pids)))} if pids else {}
    users = dict(conn.execute('SELECT id, full_name FROM users'))
    known = {}
    for e, k in owner.items():
        if k not in known:
            if k[0] == 'person':
                p = people.get(k[1])
                if not p:
                    continue
                known[k] = {'kind': 'person', 'id': k[1], 'name': p['full_name'], 'companies': [c['name'] for c in p['companies']],
                            'emails': [], 'count': 0, 'last': ''}
            else:
                known[k] = {'kind': 'user', 'id': k[1], 'name': users.get(k[1]) or e, 'companies': [config.COMPANY_NAME],
                            'emails': [], 'count': 0, 'last': ''}
        n, last, _ = st[e]
        r = known[k]
        r['emails'].append({'email': e, 'count': n})
        r['count'] += n
        r['last'] = max(r['last'], last)
    for r in known.values():
        r['emails'].sort(key=lambda x: -x['count'])
    used = set(owner)
    unknown = [{'kind': 'addr', 'email': e, 'name': v[2] or '', 'count': v[0], 'last': v[1]} for e, v in st.items() if e not in used]
    unknown.sort(key=lambda r: r['last'], reverse=True)
    return {'known': sorted(known.values(), key=lambda r: fold(r['name'])), 'unknown': unknown[:1500], 'unknown_total': len(unknown)}


@router.get('/view/cari')
def view_cari(user=Depends(auth.current_user), conn=db.DB):
    """Mail › Cariler: firmalar (müşteri / tedarikçi yetkisine göre) ve çalışanlarının adresleri; ileti sayıları kayıtlı maillerden."""
    from .companies import people_of
    st = _stats(conn, user)
    cos = {}
    for sup, mod in ((False, 'companies'), (True, 'purchasing')):
        if mod not in user['modules']:
            continue
        for p in people_of(conn, sup):
            for e in p.get('email_list') or []:
                if not e.get('company_id'):
                    continue
                c = cos.setdefault(e['company_id'], {'id': e['company_id'], 'name': e.get('company_name') or '', 'supplier': sup,
                                                      'people': [], 'count': 0, 'last': ''})
                n, last, _ = st.get(e['email'], (0, '', None))
                c['people'].append({'id': p['id'], 'name': p['full_name'], 'email': e['email'], 'count': n})
                c['count'] += n
                c['last'] = max(c['last'], last)
    from ..document_ocr import fold
    out = sorted(cos.values(), key=lambda c: (c['count'] == 0, fold(c['name'])))
    for c in out:
        c['people'].sort(key=lambda x: (-x['count'], fold(x['name'])))
    return out


@router.get('/view/mails')
def view_mails(emails: str = '', user=Depends(auth.current_user), conn=db.DB):
    """Seçilen kişinin / carinin adresleriyle yazışmalar (kayıtlı mailler); her iletide eşleşen adres (match)."""
    ids, _ = _view_boxes(conn, user)
    items = mail_cache.mails_for(conn, ids, [e.strip() for e in emails.split(',')])
    return {'items': _annotate(conn, items), 'total': len(items)}


@router.get('/people/search')
def people_search(q: str = '', user=Depends(auth.current_user), conn=db.DB):
    """Atama penceresi: "bu adres şu kişiye ait" — Rehber'deki tüm kişiler arasında (firmasızlar ve başka firmalardakiler dahil)."""
    if not _can_assign(user):
        raise HTTPException(403, 'Kişiyi firmaya atamak için Firma Yönetimi yetkisi gerekir')
    t = f'%{q.strip().lower()}%'
    rows = db.rows(conn.execute('''SELECT id, full_name, title, email, company_id FROM company_people
                                   WHERE lower(full_name) LIKE ? OR lower(COALESCE(email, '')) LIKE ? OR id IN
                                   (SELECT ref_id FROM person_emails WHERE kind = 'company' AND email LIKE ?) ORDER BY full_name LIMIT 20''', (t, t, t)))
    return person_emails.attach(conn, 'company', rows)


@router.get('/companies')
def companies(q: str = '', user=Depends(auth.current_user), conn=db.DB):
    """Kişiyi firmaya atama için firma arama (Firmalar yetkisi gerekir)."""
    if not _can_assign(user):
        raise HTTPException(403, 'Kişiyi firmaya atamak için Firma Yönetimi yetkisi gerekir')
    t = f'%{q.strip()}%'
    return db.rows(conn.execute('''SELECT id, name, is_supplier, (SELECT COUNT(*) FROM company_people p WHERE p.company_id = c.id) AS people FROM companies c
                                   WHERE active = 1 AND name LIKE ? AND ((is_supplier = 1 AND ?) OR (is_supplier = 0 AND ?))
                                   ORDER BY name COLLATE NOCASE LIMIT 30''', (t, int(_co_write(user, True)), int(_co_write(user, False)))))


class AddrIn(BaseModel):
    email: str
    name: Optional[str] = None


class AssignIn(BaseModel):
    email: str
    full_name: Optional[str] = ''
    company_id: int
    title: Optional[str] = None
    phone: Optional[str] = None
    person_id: Optional[int] = None   # verilirse adres bu firmadaki MEVCUT kişiye ek adres olarak eklenir (yeni kişi açılmaz)
    others: List[AddrIn] = []   # maildeki diğer kişiler: aynı alan adındaki bilinmeyenler aynı firmaya otomatik eklenir


# Kişiye ait olmayan, herkese açık e-posta servisleri: aynı alan adı aynı firma demek değildir
PUBLIC_DOMAINS = {
    'gmail.com', 'googlemail.com', 'hotmail.com', 'hotmail.com.tr', 'outlook.com', 'outlook.com.tr', 'live.com', 'live.com.tr',
    'msn.com', 'windowslive.com', 'yahoo.com', 'yahoo.com.tr', 'ymail.com', 'icloud.com', 'me.com', 'mac.com', 'yandex.com',
    'yandex.com.tr', 'yandex.ru', 'ya.ru', 'mail.ru', 'proton.me', 'protonmail.com', 'aol.com', 'gmx.com', 'gmx.de', 'gmx.net',
    'zoho.com', 'superonline.com', 'ttmail.com', 'mynet.com', 'turk.net', 'e-posta.com', 'web.de', 't-online.de'}


AUTO_NOTE = 'E-postadan eklendi (aynı alan adı)'


def _domain(email):
    return email.rsplit('@', 1)[-1].strip().lower() if '@' in (email or '') else ''


def _own_domains(conn):
    """Kendi şirketimizin alan adları (kullanıcı adları): çalışanlarımız müşteri firmaya eklenmesin."""
    return {_domain(r[0]) for r in conn.execute("SELECT username FROM users WHERE username LIKE '%@%'")} - {''}


def _known_name(conn, user, email, given=None):
    """Ad biliniyorsa ad: verilen ad (adres değilse) → kişisel rehber (önce kullanıcının, sonra herkesin) → yok."""
    g = (given or '').strip()
    if g and g.lower() != email and '@' not in g:
        return g[:200]
    r = conn.execute("SELECT name FROM personal_contacts WHERE lower(email) = ? AND COALESCE(trim(name), '') != '' "
                     "AND name NOT LIKE '%@%' ORDER BY (user_id = ?) DESC, hits DESC LIMIT 1", (email, user['id'])).fetchone()
    return r[0][:200] if r else None


@router.post('/people/assign')
def assign_person(body: AssignIn, user=Depends(auth.current_user), conn=db.DB):
    """E-posta adresini bir firmaya atar. Firma ataması ADRES üzerindendir; kişi firmadan bağımsızdır:
    - adres bir kişiye kayıtlıysa (hangi firmada olursa olsun ya da firmasız) o adresin firması seçilen firma olur — kişi aynı kalır;
    - person_id verilirse adres o kişiye (seçilen firmayla) eklenir — aynı kişinin başka firmadaki adresi (ör. Burak: ASG + Gökkubbe);
    - değilse yeni kişi açılır. Aynı alan adından bilinmeyen kişiler de aynı firmaya otomatik eklenir (genel servisler hariç)."""
    if not _can_assign(user):
        raise HTTPException(403, 'Kişiyi firmaya atamak için Firma Yönetimi yetkisi gerekir')
    em = body.email.strip().lower()
    if '@' not in em:
        raise HTTPException(400, 'E-posta gerekli')
    name = _known_name(conn, user, em, body.full_name) or em
    comp = db.row(conn.execute('SELECT id, name, is_supplier FROM companies WHERE id = ? AND active = 1', (body.company_id,)))
    if not comp:
        raise HTTPException(404, 'Firma bulunamadı')
    if not _co_write(user, comp['is_supplier']):
        raise HTTPException(403, 'Bu firmaya kişi ekleme yetkiniz yok')
    t = lambda v, n: ((v or '').strip()[:n] or None)  # noqa: E731
    own = person_emails.owner(conn, em)
    try:
        if body.person_id:
            tgt = db.row(conn.execute('SELECT id, full_name FROM company_people WHERE id = ?', (body.person_id,)))
            if not tgt:
                raise HTTPException(404, 'Kişi bulunamadı')
            if own and own[0] != tgt['id']:
                raise HTTPException(400, 'Bu adres başka bir kişiye kayıtlı; önce iki kişiyi Rehber’den birleştirin')
            person_emails.add(conn, 'company', tgt['id'], em, db.now(), comp['id'])
            name = tgt['full_name']
        elif own:
            person_emails.set_company(conn, own[0], em, comp['id'])
            conn.execute('UPDATE company_people SET title = COALESCE(title, ?), phone = COALESCE(phone, ?) WHERE id = ?',
                         (t(body.title, 120), t(body.phone, 40), own[0]))
            if body.full_name and body.full_name.strip() and '@' not in body.full_name:
                conn.execute('UPDATE company_people SET full_name = ? WHERE id = ?', (name, own[0]))
        else:
            conn.execute('''INSERT INTO company_people (company_id, full_name, title, phone, email, note, created_at) VALUES (?,?,?,?,?,?,?)''',
                         (comp['id'], name, t(body.title, 120), t(body.phone, 40), em, 'E-postadan eklendi', db.now()))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.audit(conn, user['id'], 'E-posta adresini firmaya atadı', 'company', comp['id'], f"{comp['name']}: {name} <{em}>")
    # Aynı alan adından firması olmayan diğer adresler de bu firmaya (sihirbazsız). Kişisi varsa adresi firmaya bağlanır,
    # yoksa yeni kişi açılır. Herkese açık servisler (gmail, hotmail…) ve kendi alan adlarımız hariç.
    also = []
    dom = _domain(em)
    if dom and dom not in PUBLIC_DOMAINS and dom not in _own_domains(conn):
        cand = {}
        for o in body.others:
            oe = (o.email or '').strip().lower()
            if oe != em and '@' in oe and _domain(oe) == dom:
                cand.setdefault(oe, o.name)
        for oe, on in cand.items():
            o_own = person_emails.owner(conn, oe)
            if o_own and o_own[1]:
                continue   # zaten bir firmada
            if o_own:
                person_emails.set_company(conn, o_own[0], oe, comp['id'])
            else:
                conn.execute('INSERT INTO company_people (company_id, full_name, email, note, created_at) VALUES (?,?,?,?,?)',
                             (comp['id'], _known_name(conn, user, oe, on) or oe, oe, AUTO_NOTE, db.now()))
            also.append(oe)
        if also:
            db.audit(conn, user['id'], 'Aynı alan adındaki e-posta adreslerini firmaya ekledi', 'company', comp['id'],
                     f"{comp['name']}: {', '.join(also)}")
    conn.commit()
    out = dict(company_map(conn, [em]).get(em) or {})
    cm = company_map(conn, also)
    out['also'] = [{'email': oe, **cm[oe]} for oe in also if oe in cm]
    return out


@router.delete('/people/assign')
def unassign_person(person_id: int, email: str, auto: bool = False, user=Depends(auth.current_user), conn=db.DB):
    """Firma bağlantısını kaldır: adres kişide kalır, yalnız firmayla bağı kopar (kişi firmasız kalabilir, başka adresleriyle
    başka firmalarda olabilir). auto=1 ("geri al"): yalnız bu adresle otomatik açılmış kişi tamamen silinir."""
    em = email.strip().lower()
    own = person_emails.owner(conn, em) if '@' in em else None
    if not own or own[0] != person_id:
        raise HTTPException(404, 'Kişi bulunamadı')
    r = db.row(conn.execute('SELECT id, full_name, note, email FROM company_people WHERE id = ?', (person_id,)))
    comp = db.row(conn.execute('SELECT id, name, is_supplier FROM companies WHERE id = ?', (own[1],))) if own[1] else None
    if comp and not _co_write(user, comp['is_supplier']):
        raise HTTPException(403, 'Bu firmanın kişilerini değiştirme yetkiniz yok')
    only = not conn.execute("SELECT 1 FROM person_emails WHERE kind = 'company' AND ref_id = ?", (person_id,)).fetchone()
    if auto and r['note'] == AUTO_NOTE and only:
        person_emails.drop(conn, 'company', [person_id])
        conn.execute('DELETE FROM company_people WHERE id = ?', (person_id,))
        db.audit(conn, user['id'], 'Otomatik eklenen e-posta kişisini geri aldı', 'company', own[1], f"{r['full_name']} <{em}>")
    else:
        person_emails.set_company(conn, person_id, em, None)
        db.audit(conn, user['id'], 'E-posta adresinin firma bağlantısını kaldırdı', 'company', own[1], f"{r['full_name']} <{em}>")
    conn.commit()
    return {'company': company_map(conn, [em]).get(em)}


@router.get('/company/{cid}')
def company_mails(cid: int, offset: int = 0, user=Depends(auth.current_user), conn=db.DB):
    """CRM › firma › Mailler: YALNIZ bu kullanıcının kendi mail hesaplarında, firmanın kişileriyle ya da firmanın alan adıyla
    yazışılan iletiler (önbellekten: gelen kutusu + gönderilenler arka planda eşitlenir; açılan her ileti de eklenir)."""
    c = db.row(conn.execute('SELECT id, name, email, website, is_supplier FROM companies WHERE id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Firma bulunamadı')
    if ('purchasing' if c['is_supplier'] else 'companies') not in user['modules']:
        raise HTTPException(403, 'Bu firmayı görme yetkiniz yok')
    boxes = [b['id'] for b in _boxes(conn, user) if b['provider'] != 'pop3']
    emails = {(r[0] or '').strip().lower() for r in conn.execute(
        '''SELECT email FROM company_people WHERE company_id = ? AND email LIKE '%@%' UNION
           SELECT email FROM person_emails WHERE kind = 'company' AND company_id = ?''',
        (cid, cid))}
    if c['email'] and '@' in c['email']:
        emails.add(c['email'].strip().lower())
    emails.discard('')
    skip = PUBLIC_DOMAINS | _own_domains(conn)
    domains = {_domain(e) for e in emails} - skip - {''}
    web = re.sub(r'^https?://', '', (c['website'] or '').strip().lower()).split('/')[0].removeprefix('www.')
    if web and '.' in web and web not in skip:
        domains.add(web)
    # alan adı ile eşleşen adresler zaten kapsanır; yalnız alan adı dışındaki (ör. gmail'deki) kişiler ayrıca aranır
    emails = {e for e in emails if _domain(e) not in domains}
    items = mail_cache.company_mails(conn, boxes, sorted(emails), sorted(domains), limit=mail.PAGE, offset=max(0, offset))
    bmap = {b['id']: b for b in _boxes(conn, user)}
    for it in items:
        b = bmap.get(it['box_id']) or {}
        it.update(box_email=b.get('email'), box_color=b.get('color'))
    return {'items': _annotate(conn, items), 'boxes': len(boxes), 'domains': sorted(domains),
            'more': len(items) == mail.PAGE}


@router.get('/contacts/suggest')
def suggest(q: str = '', user=Depends(auth.current_user), conn=db.DB):
    """Alıcı otomatik tamamlama: kişisel rehber (en çok yazışılan önce) + şirket kullanıcıları."""
    t = f'%{q.strip().lower()}%'
    rows = db.rows(conn.execute('''SELECT name, email, hits FROM personal_contacts WHERE user_id = ? AND email IS NOT NULL
                                   AND (lower(email) LIKE ? OR lower(COALESCE(name, '')) LIKE ?) ORDER BY hits DESC, name LIMIT 12''', (user['id'], t, t)))
    seen = {r['email'] for r in rows}
    for u in db.rows(conn.execute('''SELECT full_name AS name, username AS email FROM users WHERE active = 1 AND deleted_at IS NULL AND username LIKE '%@%'
                                     AND (lower(username) LIKE ? OR lower(full_name) LIKE ?) LIMIT 8''', (t, t))):
        if u['email'].lower() not in seen:
            rows.append({**u, 'hits': 0, 'company': True})
    return rows[:15]
