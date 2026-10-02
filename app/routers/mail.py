"""Kişisel → Mail API'si. Yalnızca kullanıcının kendi hesabı; yönetici dahil kimse başkasının postalarını göremez.
Uygulama şifresi hiçbir yanıtta dönmez. İçerik sunucuda saklanmaz (Gmail'den anlık okunur); yalnızca bağlama / ayırma loglanır."""
import secrets
import time
from typing import Optional
from urllib.parse import quote, urlencode

import httpx

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from .. import auth, config, db, mail, mail_import
from ..cameras import encrypt

router = APIRouter(prefix='/api/mail')
MAX_ATTACH = 25 * 1024 * 1024
_unread_cache = {}   # user_id → (zaman, sayı)


def _account(conn, uid, required=True):
    a = db.row(conn.execute('SELECT * FROM mail_accounts WHERE user_id = ?', (uid,)))
    if not a and required:
        raise HTTPException(404, 'Gmail hesabı bağlı değil')
    return a


def _wrap(fn):
    try:
        return fn()
    except mail.MailError as e:
        raise HTTPException(400, str(e)) from e


def unread_count(conn, user):
    """Bildirim / pano / Kişisel sayısı: gelen kutusundaki okunmamış (60 sn önbellek; hata olursa 0)."""
    hit = _unread_cache.get(user['id'])
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    a = _account(conn, user['id'], required=False)
    n = 0
    if a:
        try:
            n = mail.unread(a)
        except Exception:
            n = hit[1] if hit else 0
    _unread_cache[user['id']] = (time.time(), n)
    return n


class AccountIn(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class ProfileIn(BaseModel):
    name: Optional[str] = None
    signature: Optional[str] = None
    auto_import: Optional[bool] = None


@router.get('/account')
def account(user=Depends(auth.current_user), conn=db.DB):
    a = _account(conn, user['id'], required=False)
    oauth = bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)
    if not a:
        return {'connected': False, 'oauth_available': oauth}
    return {'connected': True, 'auth_type': a['auth_type'], 'oauth_available': oauth, 'email': a['email'], 'name': a['name'], 'signature': a['signature'], 'since': a['created_at'],
            'auto_import': bool(a['auto_import']), 'can_import': 'documents' in user['modules'], 'last_error': a['last_error']}


@router.post('/account')
def connect(body: AccountIn, user=Depends(auth.current_user), conn=db.DB):
    addr = body.email.strip().lower()
    pw = body.password.replace(' ', '')   # Google şifreyi 4'lü gruplar halinde gösterir
    if '@' not in addr or len(pw) < 8:
        raise HTTPException(400, 'Gmail adresini ve uygulama şifresini girin')
    secret = encrypt(pw)
    _wrap(lambda: mail.verify({'email': addr, 'secret': secret, 'auth_type': 'password'}))
    _save_account(conn, user, addr, secret, 'password', body.name)
    return account(user, conn)


def _save_account(conn, user, addr, secret, kind, name=None):
    conn.execute('''INSERT INTO mail_accounts (user_id, email, secret, name, created_at, last_ok, auth_type) VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET email = excluded.email, secret = excluded.secret, name = excluded.name,
                    created_at = excluded.created_at, last_ok = excluded.last_ok, last_error = NULL, last_uid = NULL, uid_validity = NULL,
                    auth_type = excluded.auth_type''',
                 (user['id'], addr, secret, (name or user['full_name']).strip(), db.now(), db.now(), kind))
    mail.drop(user['id'])
    _unread_cache.pop(user['id'], None)
    db.audit(conn, user['id'], 'Gmail hesabını bağladı', 'mail', user['id'], f'{addr} ({"Google ile" if kind == "oauth" else "uygulama şifresi"})')


# ---------- Google ile bağlan (OAuth; kurumsal Google Workspace hesapları)
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
SCOPES = 'https://mail.google.com/ openid email'
_states = {}   # durum jetonu → (kullanıcı, zaman)


def _redirect_uri(request):
    base = config.PUBLIC_URL or f"{request.headers.get('x-forwarded-proto', request.url.scheme)}://{request.headers.get('host')}"
    return f'{base}/api/mail/oauth/callback'


@router.get('/oauth/start')
def oauth_start(request: Request, user=Depends(auth.current_user)):
    if not (config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET):
        raise HTTPException(400, 'Google ile bağlanma bu sunucuda henüz ayarlanmadı (sistem yöneticisi)')
    now = time.time()
    for k in [k for k, v in _states.items() if now - v[1] > 600]:
        _states.pop(k, None)
    state = secrets.token_urlsafe(24)
    _states[state] = (user['id'], now)
    q = {'client_id': config.GOOGLE_CLIENT_ID, 'redirect_uri': _redirect_uri(request), 'response_type': 'code', 'scope': SCOPES,
         'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true', 'state': state}
    return {'url': f'{AUTH_URL}?{urlencode(q)}'}


@router.get('/oauth/callback')
def oauth_callback(request: Request, state: str = '', code: str = '', error: str = '', user=Depends(auth.current_user), conn=db.DB):
    back = lambda msg: RedirectResponse(f'/app#/mail/oauth/{quote(msg, safe="")}', status_code=303)
    st = _states.pop(state, None)
    if not st or st[0] != user['id'] or time.time() - st[1] > 600:
        return back('Bağlantı isteği geçersiz ya da süresi doldu; yeniden deneyin')
    if error or not code:
        return back('Google izni verilmedi')
    try:
        r = httpx.post(mail.TOKEN_URL, data={'code': code, 'client_id': config.GOOGLE_CLIENT_ID, 'client_secret': config.GOOGLE_CLIENT_SECRET,
                                             'redirect_uri': _redirect_uri(request), 'grant_type': 'authorization_code'}, timeout=20)
        tok = r.json()
        if r.status_code != 200 or 'refresh_token' not in tok:
            return back('Google jetonu alınamadı; yeniden deneyin')
        info = httpx.get('https://openidconnect.googleapis.com/v1/userinfo', headers={'Authorization': f'Bearer {tok["access_token"]}'}, timeout=20).json()
    except (httpx.HTTPError, ValueError):
        return back('Google\'a bağlanılamadı')
    addr = (info.get('email') or '').lower()
    if not addr:
        return back('Google hesabının e-posta adresi alınamadı')
    secret = encrypt(tok['refresh_token'])
    try:
        mail.verify({'email': addr, 'secret': secret, 'auth_type': 'oauth'})
    except mail.MailError as e:
        return back(str(e))
    _save_account(conn, user, addr, secret, 'oauth')
    return back('ok')


@router.put('/account')
def profile(body: ProfileIn, user=Depends(auth.current_user), conn=db.DB):
    _account(conn, user['id'])
    conn.execute('UPDATE mail_accounts SET name = ?, signature = ? WHERE user_id = ?',
                 ((body.name or '').strip() or None, (body.signature or '').strip()[:2000] or None, user['id']))
    if body.auto_import is not None:
        conn.execute('UPDATE mail_accounts SET auto_import = ? WHERE user_id = ?', (int(body.auto_import), user['id']))
    return account(user, conn)


@router.delete('/account')
def disconnect(user=Depends(auth.current_user), conn=db.DB):
    a = _account(conn, user['id'])
    if a['auth_type'] == 'oauth':   # Google'daki izni de geri al
        try:
            from ..cameras import decrypt
            httpx.post('https://oauth2.googleapis.com/revoke', data={'token': decrypt(a['secret'])}, timeout=10)
        except Exception:
            pass
    conn.execute('DELETE FROM mail_accounts WHERE user_id = ?', (user['id'],))
    mail.drop(user['id'])
    _unread_cache.pop(user['id'], None)
    db.audit(conn, user['id'], 'Gmail hesabını ayırdı', 'mail', user['id'], a['email'])
    return {'connected': False, 'oauth_available': bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)}


@router.get('/folders')
def folders(user=Depends(auth.current_user), conn=db.DB):
    a = _account(conn, user['id'])
    out = _wrap(lambda: mail.folders(a))
    inbox = next((f for f in out if f['key'] == 'inbox'), None)
    if inbox and inbox['unseen'] is not None:
        _unread_cache[user['id']] = (time.time(), inbox['unseen'])
    return out


@router.get('/list')
def messages(folder: str = 'inbox', q: str = '', page: int = 0, unread: bool = False, user=Depends(auth.current_user), conn=db.DB):
    a = _account(conn, user['id'])
    return _wrap(lambda: mail.list_messages(a, folder, q.strip()[:300], max(0, page), unread))


@router.get('/msg/{folder}/{uid}')
def read(folder: str, uid: int, user=Depends(auth.current_user), conn=db.DB):
    a = _account(conn, user['id'])
    _unread_cache.pop(user['id'], None)
    return _wrap(lambda: mail.read(a, folder, uid))


@router.get('/att/{folder}/{uid}/{idx}')
def attachment(folder: str, uid: int, idx: int, inline: bool = False, user=Depends(auth.current_user), conn=db.DB):
    a = _account(conn, user['id'])
    name, ctype, data = _wrap(lambda: mail.attachment(a, folder, uid, idx))
    safe = ctype if ctype.split('/')[0] in ('image', 'audio', 'video') or ctype == 'application/pdf' else 'application/octet-stream'
    disp = 'inline' if inline and safe != 'application/octet-stream' else 'attachment'
    return Response(data, media_type=safe, headers={
        'Content-Disposition': f"{disp}; filename*=UTF-8''{quote(name)}",
        'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox", 'Cache-Control': 'private, max-age=3600'})


class ImportIn(BaseModel):
    folder: str
    uid: int


@router.post('/import')
def import_attachments(body: ImportIn, user=Depends(auth.current_user), conn=db.DB):
    """E-postanın eklerini "Yalnızca ben" görünürlüğünde evraklara kaydeder (OCR uygulanır)."""
    if 'documents' not in user['modules']:
        raise HTTPException(403, 'Evrak Yönetimi yetkiniz yok')
    a = _account(conn, user['id'])
    ids = _wrap(lambda: mail_import.import_message(conn, user, a, body.folder, body.uid))
    return {'imported': len(ids), 'ids': ids}


class ActionIn(BaseModel):
    folder: str
    uids: list[int]
    action: str


@router.post('/action')
def act(body: ActionIn, user=Depends(auth.current_user), conn=db.DB):
    a = _account(conn, user['id'])
    if not body.uids or len(body.uids) > 500:
        raise HTTPException(400, 'E-posta seçin')
    _unread_cache.pop(user['id'], None)
    return _wrap(lambda: mail.action(a, body.folder, body.uids, body.action))


@router.post('/send')
async def send(to: str = Form(...), cc: str = Form(''), bcc: str = Form(''), subject: str = Form(''), body: str = Form(''),
               reply_id: str = Form(''), references: str = Form(''), fwd_folder: str = Form(''), fwd_uid: int = Form(0),
               files: list[UploadFile] = File(default=[]), user=Depends(auth.current_user), conn=db.DB):
    a = _account(conn, user['id'])
    parts, total = [], 0
    for f in files or []:
        if not f.filename:
            continue
        data = await f.read()
        total += len(data)
        if total > MAX_ATTACH:
            raise HTTPException(400, 'Ekler toplam 25 MB sınırını aşıyor')
        parts.append((f.filename, f.content_type or 'application/octet-stream', data))

    def go():
        return mail.send(a, to=to, cc=cc, bcc=bcc, subject=subject, body=body, files=parts,
                         reply={'message_id': reply_id, 'references': references} if reply_id else None,
                         forward={'folder': fwd_folder, 'uid': fwd_uid} if fwd_folder and fwd_uid else None)
    r = await run_in_threadpool(lambda: _wrap(go))
    db.audit(conn, user['id'], 'E-posta gönderdi', 'mail', user['id'], f'{r["recipients"]} alıcı')   # içerik loglanmaz
    return r
