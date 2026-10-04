"""Kişisel → Mail API'si (v2, çok hesaplı). Yalnızca kullanıcının kendi hesapları; yönetici dahil kimse başkasının postalarını
göremez. Şifre / jeton hiçbir yanıtta dönmez. İçerik sunucuda saklanmaz (posta sunucusundan anlık okunur); yalnızca hesap
bağlama / ayırma ve gönderim sayısı loglanır. Klasör anahtarı '/' içerebildiği için ?folder= ile taşınır."""
import secrets
import time
from typing import List, Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from .. import auth, config, db, mail, mail_import, personal
from ..cameras import decrypt, encrypt

router = APIRouter(prefix='/api/mail')
MAX_ATTACH = 25 * 1024 * 1024
_unread_cache = {}   # user_id → (zaman, sayı)
PUBLIC = ('id', 'email', 'login', 'name', 'provider', 'auth_type', 'imap_host', 'imap_port', 'pop_host', 'pop_port', 'smtp_host', 'smtp_port',
          'smtp_security', 'save_sent', 'signature', 'color', 'sort', 'auto_import', 'sync_calendar', 'sync_contacts', 'last_ok', 'last_error',
          'last_sync', 'created_at')


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
    return {k: b.get(k) for k in PUBLIC}


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
    mail.drop(box_id)
    _unread_cache.pop(user['id'], None)
    db.audit(conn, user['id'], 'Mail hesabını ayırdı', 'mail', box_id, b['email'])
    conn.commit()
    return {'ok': True}


# ---------------- OAuth: Google / Microsoft ile bağlan ----------------
_states = {}   # durum jetonu → (kullanıcı, sağlayıcı, zaman)
G_AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'
G_SCOPES = ('https://mail.google.com/ openid email https://www.googleapis.com/auth/calendar.readonly '
            'https://www.googleapis.com/auth/contacts.readonly')


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
def oauth_start(prov: str, request: Request, user=Depends(auth.current_user)):
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
        return {'url': f'{G_AUTH}?{urlencode(q)}'}
    q = {'client_id': config.MS_CLIENT_ID, 'redirect_uri': _redirect_uri(request, prov), 'response_type': 'code', 'response_mode': 'query',
         'scope': f'openid email profile offline_access {mail.MS_MAIL_SCOPE} https://graph.microsoft.com/Calendars.Read https://graph.microsoft.com/Contacts.Read',
         'prompt': 'select_account', 'state': state}
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


@router.get('/{box_id}/list')
def messages(box_id: int, folder: str = 'inbox', q: str = '', page: int = 0, unread: bool = False, user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    return _wrap(lambda: mail.list_messages(b, folder, q.strip()[:300], max(0, page), unread))


@router.get('/unified/inbox')
def unified(q: str = '', user=Depends(auth.current_user), conn=db.DB):
    """Tüm hesapların gelen kutuları birlikte (en yeni 50); hatalı hesap atlanır ve bildirilir."""
    items, errors = [], []
    for b in _boxes(conn, user):
        try:
            r = mail.list_messages(b, 'inbox', q.strip()[:300], 0, False)
            items += [dict(it, box_id=b['id'], box_email=b['email'], box_color=b['color']) for it in r['items']]
        except Exception as e:
            errors.append({'box_id': b['id'], 'email': b['email'], 'error': str(e)[:200]})
    items.sort(key=lambda x: x.get('date') or '', reverse=True)
    return {'items': items[:mail.PAGE], 'errors': errors}


@router.get('/{box_id}/msg')
def read(box_id: int, folder: str, uid: int, user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    _unread_cache.pop(user['id'], None)
    d = _wrap(lambda: mail.read(b, folder, uid))
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


@router.post('/{box_id}/send')
async def send(box_id: int, to: str = Form(''), cc: str = Form(''), bcc: str = Form(''), subject: str = Form(''), body: str = Form(''),
               html: str = Form(''), reply_id: str = Form(''), references: str = Form(''), fwd_folder: str = Form(''), fwd_uid: int = Form(0),
               draft_uid: int = Form(0), files: list[UploadFile] = File(default=[]), user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    parts = await _files(files)

    def go():
        return mail.send(b, to=to, cc=cc, bcc=bcc, subject=subject, body=body, html=html or None, files=parts,
                         reply={'message_id': reply_id, 'references': references} if reply_id else None,
                         forward={'folder': fwd_folder, 'uid': fwd_uid} if fwd_folder and fwd_uid else None, draft_uid=draft_uid or None)
    r = await run_in_threadpool(lambda: _wrap(go))
    from email.utils import getaddresses
    personal.collect(conn, user['id'], getaddresses([x for x in (to, cc, bcc) if x]), own=[x['email'] for x in _boxes(conn, user)])
    db.audit(conn, user['id'], 'E-posta gönderdi', 'mail', box_id, f'{r["recipients"]} alıcı')   # içerik loglanmaz
    conn.commit()
    r.pop('rcpts', None)
    return r


@router.post('/{box_id}/draft')
async def draft(box_id: int, to: str = Form(''), cc: str = Form(''), bcc: str = Form(''), subject: str = Form(''), body: str = Form(''),
                html: str = Form(''), reply_id: str = Form(''), references: str = Form(''), replace_uid: int = Form(0),
                files: list[UploadFile] = File(default=[]), user=Depends(auth.current_user), conn=db.DB):
    b = _box(conn, user, box_id)
    parts = await _files(files)
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
