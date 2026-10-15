"""SSH Master hesap ve senkronizasyon servisi (sshmasters.com). Sözleşme: docs/sshmaster-api.md (v2).

- Düz şifre sunucuya HİÇ gelmez: istemci (uygulama ve web/WebCrypto) master = PBKDF2(şifre, kdf_salt, 310000) türetir,
  auth_hash = b64(PBKDF2(master, şifre, 1)) gönderir; sunucu auth_hash'i kendi PBKDF2'siyle (ayrı tuz) saklar.
  Kütüphane anahtarı (HKDF(master)) istemcide kalır; sunucu blob'u okuyamaz.
- Web oturumu çerez (sm_session, HttpOnly/Secure/Lax); çerezli değişiklik istekleri ayrıca X-SSHM: 1 başlığı ister (CSRF).
  Uygulama oturumu Bearer token. Token'lar özet olarak saklanır.
- Kişiye özel indirme /indir/<dl_token>: yalnız AYNI kullanıcı web oturumuyla çalışır.
- Yönetim (HEPGO Merkez): /api/sm/admin/* X-Central-Secret (VEILOX_CENTRAL_API_SECRET) ile.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import shutil
import time
from collections import defaultdict, deque

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from . import db, mailer, settings

VERSION = '1.0.0'
app = FastAPI(title='SSH Master', docs_url=None, redoc_url=None, openapi_url=None)
COOKIE = 'sm_session'
EMAIL_RE = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$')
AUTH_RE = re.compile(r'^[A-Za-z0-9+/]{43}=$')          # base64(32 bayt)
SALT_RE = re.compile(r'^[A-Za-z0-9+/]{22}==$')          # base64(16 bayt)
VERSION_RE = re.compile(r'^\d{1,4}\.\d{1,4}\.\d{1,4}([.-][0-9A-Za-z.-]{1,20})?$')
SERVER_ITER = 240_000


# ---------------- yardımcılar ----------------
class Err(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


@app.exception_handler(Err)
async def _err(request, e: Err):
    return JSONResponse({'code': e.code, 'message': e.message, 'detail': e.message}, status_code=e.status)


@app.exception_handler(HTTPException)
async def _http(request, e: HTTPException):
    msg = e.detail if isinstance(e.detail, str) else 'Hata'
    return JSONResponse({'code': 'error', 'message': msg, 'detail': msg}, status_code=e.status_code)


@app.exception_handler(RequestValidationError)
async def _val(request, e):
    return JSONResponse({'code': 'invalid', 'message': 'İstek gövdesi geçersiz', 'detail': 'İstek gövdesi geçersiz'}, status_code=422)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def b64salt():
    return base64.b64encode(secrets.token_bytes(16)).decode()


def det_salt(email):
    """Kullanıcı yokken / kayıtta: e-postaya bağlı deterministik tuz (prelogin varlık sızdırmasın)."""
    return base64.b64encode(hmac.new(settings.SALT_KEY.encode(), email.lower().encode(), hashlib.sha256).digest()[:16]).decode()


def hash_auth(auth_hash):
    salt = secrets.token_bytes(16)
    d = hashlib.pbkdf2_hmac('sha256', auth_hash.encode(), salt, SERVER_ITER)
    return f'pbkdf2_sha256${SERVER_ITER}${salt.hex()}${d.hex()}'


def check_auth(auth_hash, stored):
    try:
        _, it, salt, d = stored.split('$')
        calc = hashlib.pbkdf2_hmac('sha256', auth_hash.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), d)
    except (ValueError, AttributeError):
        return False


_DUMMY = hash_auth('A' * 43 + '=')   # bilinmeyen e-postada da aynı süre harcansın (zamanlama ile varlık sızmasın)


def kdf(salt):
    return {'alg': 'PBKDF2-SHA256', 'iter': settings.KDF_ITER, 'salt': salt}


def client_ip(request: Request):
    return (request.headers.get('cf-connecting-ip') or (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
            or (request.client.host if request.client else ''))[:64]


_RATE = defaultdict(deque)


def rate(request, key, limit, window=60):
    k = f'{key}:{client_ip(request)}'
    q, t = _RATE[k], time.time()
    while q and q[0] < t - window:
        q.popleft()
    if len(q) >= limit:
        raise Err(429, 'rate_limited', 'Çok fazla deneme; biraz sonra tekrar deneyin')
    q.append(t)


async def body(request):
    try:
        b = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise Err(422, 'invalid', 'İstek gövdesi geçersiz')
    if not isinstance(b, dict):
        raise Err(422, 'invalid', 'İstek gövdesi geçersiz')
    return b


def norm_email(v):
    e = str(v or '').strip().lower()
    if not EMAIL_RE.match(e):
        raise Err(422, 'invalid_email', 'Geçerli bir e-posta adresi girin')
    return e


def need_auth_hash(v, field='auth_hash'):
    v = str(v or '')
    if not AUTH_RE.match(v):
        raise Err(422, 'invalid', f'{field} geçersiz')
    return v


def user_public(u):
    return {'id': u['id'], 'email': u['email'], 'name': u['name']}


def new_session(conn, user_id, kind, device=None, app_version=None, ip=None):
    tok = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO sessions (user_id, token_hash, kind, device, app_version, ip, created_at, last_seen) VALUES (?,?,?,?,?,?,?,?)',
                 (user_id, sha(tok), kind, (device or '')[:120] or None, (app_version or '')[:30] or None, ip, db.now(), time.time()))
    return tok


def current(request, conn, require=True, web_only=False):
    """Oturumdaki kullanıcı: Bearer (uygulama) ya da çerez (web). Dönüş (user_row, session_row) | (None, None)."""
    tok, via_cookie = None, False
    a = request.headers.get('authorization') or ''
    if a.lower().startswith('bearer ') and not web_only:
        tok = a[7:].strip()
    elif request.cookies.get(COOKIE):
        tok, via_cookie = request.cookies.get(COOKIE), True
    if not tok:
        if require:
            raise Err(401, 'unauthorized', 'Oturum açın')
        return None, None
    s = conn.execute('SELECT * FROM sessions WHERE token_hash = ?', (sha(tok),)).fetchone()
    if not s or time.time() - s['last_seen'] > settings.TOKEN_DAYS * 86400:
        if s:
            conn.execute('DELETE FROM sessions WHERE id = ?', (s['id'],))
            conn.commit()
        if require:
            raise Err(401, 'session_expired', 'Oturum süresi doldu; yeniden giriş yapın')
        return None, None
    u = conn.execute('SELECT * FROM users WHERE id = ?', (s['user_id'],)).fetchone()
    if not u or u['status'] != 'AKTIF':
        if require:
            raise Err(403, 'suspended' if u and u['status'] == 'ASKIDA' else 'unauthorized', 'Hesap kullanılamıyor')
        return None, None
    if via_cookie and request.method not in ('GET', 'HEAD') and request.headers.get('x-sshm') != '1':
        raise Err(403, 'csrf', 'Geçersiz istek')
    conn.execute('UPDATE sessions SET last_seen = ? WHERE id = ?', (time.time(), s['id']))
    conn.commit()
    return u, s


def set_cookie(resp, tok):
    resp.set_cookie(COOKIE, tok, max_age=settings.TOKEN_DAYS * 86400, httponly=True, secure=settings.SECURE_COOKIE, samesite='lax', path='/')


def central(request):
    sec = request.headers.get('x-central-secret') or ''
    if not settings.CENTRAL_SECRET or not hmac.compare_digest(sec, settings.CENTRAL_SECRET):
        raise Err(403, 'forbidden', 'Yetkisiz')


def new_token(conn, user_id, kind, seconds, salt=None):
    tok = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO tokens (user_id, kind, token_hash, salt, expires) VALUES (?,?,?,?,?)', (user_id, kind, sha(tok), salt, time.time() + seconds))
    return tok


def take_token(conn, tok, kind):
    t = conn.execute('SELECT * FROM tokens WHERE token_hash = ? AND kind = ?', (sha(tok or ''), kind)).fetchone()
    if not t or t['used_at'] or t['expires'] < time.time():
        return None
    return t


def latest_release(conn):
    return conn.execute('SELECT * FROM releases ORDER BY id DESC LIMIT 1').fetchone()


@app.on_event('startup')
def _startup():
    db.init()
    settings.RELEASE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------- genel ----------------
@app.get('/api/sm/health')
def health():
    return {'ok': True, 'version': VERSION, 'time': db.now()}


@app.post('/api/sm/auth/prelogin')
async def prelogin(request: Request):
    rate(request, 'prelogin', 30)
    email = norm_email((await body(request)).get('email'))
    with db.connect() as conn:
        u = conn.execute('SELECT kdf_salt FROM users WHERE email = ?', (email,)).fetchone()
    return {'kdf': kdf(u['kdf_salt'] if u else det_salt(email))}


@app.post('/api/sm/auth/register')
async def register(request: Request):
    rate(request, 'register', 5)
    b = await body(request)
    email = norm_email(b.get('email'))
    name = re.sub(r'\s+', ' ', str(b.get('name') or '')).strip()[:80]
    if len(name) < 2:
        raise Err(422, 'invalid_name', 'Adınızı girin')
    auth = need_auth_hash(b.get('auth_hash'))
    if not mailer.enabled():
        raise Err(503, 'mail_disabled', 'E-posta gönderimi şu an kullanılamıyor')
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if u and u['status'] != 'BEKLIYOR':
            mailer.send_exists(email, u['name'], f'{settings.PUBLIC_URL}/giris', f'{settings.PUBLIC_URL}/sifremi-unuttum')
            return {'ok': True}
        if u:   # doğrulanmamış kayıt yinelendi: ad/şifre güncellenir, yeni bağlantı gider
            conn.execute('UPDATE users SET name = ?, pw_hash = ?, kdf_salt = ? WHERE id = ?', (name, hash_auth(auth), det_salt(email), u['id']))
            uid = u['id']
        else:
            uid = conn.execute('INSERT INTO users (email, name, pw_hash, kdf_salt, dl_token, created_at) VALUES (?,?,?,?,?,?)',
                               (email, name, hash_auth(auth), det_salt(email), secrets.token_urlsafe(24), db.now())).lastrowid
        conn.execute("UPDATE tokens SET used_at = ? WHERE user_id = ? AND kind = 'verify' AND used_at IS NULL", (db.now(), uid))
        tok = new_token(conn, uid, 'verify', settings.VERIFY_HOURS * 3600)
        conn.commit()
    mailer.send_verify(email, name, f'{settings.PUBLIC_URL}/dogrula/{tok}')
    return {'ok': True}


@app.post('/api/sm/auth/resend-verify')
async def resend_verify(request: Request):
    rate(request, 'resend', 5)
    email = norm_email((await body(request)).get('email'))
    with db.connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE email = ? AND status = 'BEKLIYOR'", (email,)).fetchone()
        if u and mailer.enabled():
            conn.execute("UPDATE tokens SET used_at = ? WHERE user_id = ? AND kind = 'verify' AND used_at IS NULL", (db.now(), u['id']))
            tok = new_token(conn, u['id'], 'verify', settings.VERIFY_HOURS * 3600)
            conn.commit()
            mailer.send_verify(email, u['name'], f'{settings.PUBLIC_URL}/dogrula/{tok}')
    return {'ok': True}


@app.get('/dogrula/{tok}')
def verify(tok: str, request: Request):
    with db.connect() as conn:
        t = take_token(conn, tok, 'verify')
        if not t:
            return RedirectResponse('/giris?durum=dogrulama-gecersiz', status_code=303)
        u = conn.execute('SELECT * FROM users WHERE id = ?', (t['user_id'],)).fetchone()
        conn.execute('UPDATE tokens SET used_at = ? WHERE id = ?', (db.now(), t['id']))
        if u['status'] == 'BEKLIYOR':
            conn.execute("UPDATE users SET status = 'AKTIF', verified_at = ? WHERE id = ?", (db.now(), u['id']))
        conn.commit()
        if u['status'] == 'ASKIDA':
            return RedirectResponse('/giris?durum=askida', status_code=303)
        s = new_session(conn, u['id'], 'web', ip=client_ip(request))
        conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (db.now(), u['id']))
        conn.commit()
    resp = RedirectResponse('/hesabim?durum=dogrulandi', status_code=303)
    set_cookie(resp, s)
    return resp


@app.post('/api/sm/auth/login')
async def login(request: Request):
    rate(request, 'login', 10)
    b = await body(request)
    email = norm_email(b.get('email'))
    auth = need_auth_hash(b.get('auth_hash'))
    web = b.get('client') == 'web'
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if not u:
            check_auth(auth, _DUMMY)
            raise Err(401, 'bad_credentials', 'E-posta veya şifre hatalı')
        if not check_auth(auth, u['pw_hash']):
            raise Err(401, 'bad_credentials', 'E-posta veya şifre hatalı')
        if u['status'] == 'BEKLIYOR':
            raise Err(403, 'unverified', 'E-posta adresiniz henüz doğrulanmadı; gelen kutunuzdaki bağlantıya tıklayın')
        if u['status'] == 'ASKIDA':
            raise Err(403, 'suspended', 'Hesabınız askıya alınmış')
        tok = new_session(conn, u['id'], 'web' if web else 'app', b.get('device'), b.get('app_version'), client_ip(request))
        conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (db.now(), u['id']))
        conn.commit()
    out = {'user': user_public(u), 'sync_enabled': bool(u['sync_enabled']), 'kdf': kdf(u['kdf_salt'])}
    if web:
        resp = JSONResponse(out)
        set_cookie(resp, tok)
        return resp
    return {'token': tok, **out}


@app.post('/api/sm/auth/logout')
def logout(request: Request):
    with db.connect() as conn:
        u, s = current(request, conn, require=False)
        if s:
            conn.execute('DELETE FROM sessions WHERE id = ?', (s['id'],))
            conn.commit()
    resp = JSONResponse({'ok': True})
    resp.delete_cookie(COOKIE, path='/')
    return resp


def library_meta(conn, uid):
    lib = conn.execute('SELECT version, updated_at, size, device FROM libraries WHERE user_id = ?', (uid,)).fetchone()
    return dict(lib) if lib else {'version': 0, 'updated_at': None, 'size': 0, 'device': None}


@app.get('/api/sm/me')
def me(request: Request):
    with db.connect() as conn:
        u, _ = current(request, conn)
        return {'user': user_public(u), 'sync_enabled': bool(u['sync_enabled']), 'kdf': kdf(u['kdf_salt']), 'library': library_meta(conn, u['id'])}


@app.post('/api/sm/auth/forgot')
async def forgot(request: Request):
    rate(request, 'forgot', 5)
    email = norm_email((await body(request)).get('email'))
    with db.connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE email = ? AND status != 'ASKIDA'", (email,)).fetchone()
        if u and mailer.enabled():
            conn.execute("UPDATE tokens SET used_at = ? WHERE user_id = ? AND kind = 'reset' AND used_at IS NULL", (db.now(), u['id']))
            tok = new_token(conn, u['id'], 'reset', settings.RESET_MINUTES * 60, salt=b64salt())
            conn.commit()
            mailer.send_reset(email, u['name'], f'{settings.PUBLIC_URL}/sifre-sifirla/{tok}')
    return {'ok': True}   # e-posta kayıtlı olsun olmasın aynı yanıt


@app.get('/api/sm/auth/reset/{tok}')
def reset_info(tok: str):
    with db.connect() as conn:
        t = take_token(conn, tok, 'reset')
        if not t:
            raise Err(404, 'invalid_token', 'Bağlantı geçersiz ya da süresi dolmuş')
        u = conn.execute('SELECT email FROM users WHERE id = ?', (t['user_id'],)).fetchone()
    return {'email': u['email'], 'kdf': kdf(t['salt'])}


def _apply_new_password(conn, uid, new_auth, new_salt, keep_session=None):
    """Şifre değişti: eski anahtarla şifreli kütüphane okunamaz → silinir; diğer oturumlar düşer (uygulama yeniden giriş ister)."""
    conn.execute('UPDATE users SET pw_hash = ?, kdf_salt = ? WHERE id = ?', (hash_auth(new_auth), new_salt, uid))
    conn.execute('DELETE FROM libraries WHERE user_id = ?', (uid,))
    conn.execute('DELETE FROM sessions WHERE user_id = ? AND id != ?', (uid, keep_session or 0))


@app.post('/api/sm/auth/reset/{tok}')
async def reset_apply(tok: str, request: Request):
    rate(request, 'reset', 10)
    new_auth = need_auth_hash((await body(request)).get('new_auth_hash'), 'new_auth_hash')
    with db.connect() as conn:
        t = take_token(conn, tok, 'reset')
        if not t:
            raise Err(404, 'invalid_token', 'Bağlantı geçersiz ya da süresi dolmuş')
        conn.execute('UPDATE tokens SET used_at = ? WHERE id = ?', (db.now(), t['id']))
        _apply_new_password(conn, t['user_id'], new_auth, t['salt'])
        conn.execute("UPDATE users SET status = 'AKTIF', verified_at = COALESCE(verified_at, ?) WHERE id = ? AND status = 'BEKLIYOR'",
                     (db.now(), t['user_id']))   # sıfırlama bağlantısını açabilen e-postanın sahibidir
        conn.commit()
    return {'ok': True}


@app.post('/api/sm/auth/new-salt')
def new_salt(request: Request):
    with db.connect() as conn:
        u, _ = current(request, conn)
        salt = b64salt()
        conn.execute('INSERT INTO tokens (user_id, kind, token_hash, salt, expires) VALUES (?,?,?,?,?)',
                     (u['id'], 'newsalt', sha(salt + ':' + secrets.token_hex(8)), salt, time.time() + 900))
        conn.commit()
    return {'kdf': kdf(salt)}


@app.post('/api/sm/auth/change-password')
async def change_password(request: Request):
    rate(request, 'chpw', 10)
    b = await body(request)
    old = need_auth_hash(b.get('old_auth_hash'), 'old_auth_hash')
    new = need_auth_hash(b.get('new_auth_hash'), 'new_auth_hash')
    salt = str(b.get('new_salt') or '')
    if not SALT_RE.match(salt):
        raise Err(422, 'invalid', 'new_salt geçersiz')
    with db.connect() as conn:
        u, s = current(request, conn)
        if not check_auth(old, u['pw_hash']):
            raise Err(401, 'bad_credentials', 'Mevcut şifre hatalı')
        t = conn.execute("SELECT * FROM tokens WHERE user_id = ? AND kind = 'newsalt' AND salt = ? AND used_at IS NULL AND expires > ?",
                         (u['id'], salt, time.time())).fetchone()
        if not t:
            raise Err(422, 'invalid_salt', 'Tuz geçersiz ya da süresi dolmuş; yeniden deneyin')
        conn.execute('UPDATE tokens SET used_at = ? WHERE id = ?', (db.now(), t['id']))
        _apply_new_password(conn, u['id'], new, salt, keep_session=s['id'])
        conn.commit()
    return {'ok': True}


# ---------------- kütüphane (uçtan uca şifreli blob) ----------------
@app.get('/api/sm/library')
def library_get(request: Request):
    with db.connect() as conn:
        u, _ = current(request, conn)
        lib = conn.execute('SELECT * FROM libraries WHERE user_id = ?', (u['id'],)).fetchone()
    if not lib:
        return {'version': 0, 'updated_at': None, 'blob': None}
    return {'version': lib['version'], 'updated_at': lib['updated_at'], 'blob': lib['blob']}


@app.put('/api/sm/library')
async def library_put(request: Request):
    raw = await request.body()
    if len(raw) > settings.LIBRARY_MAX * 1.4 + 1024:
        raise Err(413, 'too_large', 'Kütüphane 5 MB sınırını aşıyor')
    try:
        b = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Err(422, 'invalid', 'İstek gövdesi geçersiz')
    blob = b.get('blob') if isinstance(b, dict) else None
    try:
        base = int(b.get('base_version'))
        dec = base64.b64decode(blob, validate=True) if isinstance(blob, str) else None
    except (TypeError, ValueError):
        dec = None
    if dec is None or len(dec) < 29:
        raise Err(422, 'invalid', 'blob ya da base_version geçersiz')
    if len(dec) > settings.LIBRARY_MAX:
        raise Err(413, 'too_large', 'Kütüphane 5 MB sınırını aşıyor')
    with db.connect() as conn:
        u, s = current(request, conn)
        lib = conn.execute('SELECT * FROM libraries WHERE user_id = ?', (u['id'],)).fetchone()
        cur = lib['version'] if lib else 0
        if base != cur:
            return JSONResponse({'code': 'conflict', 'message': 'Sunucudaki kütüphane daha yeni', 'detail': 'conflict',
                                 'version': cur, 'blob': lib['blob'] if lib else None}, status_code=409)
        ver = cur + 1
        conn.execute('INSERT INTO libraries (user_id, version, blob, size, device, updated_at) VALUES (?,?,?,?,?,?) '
                     'ON CONFLICT(user_id) DO UPDATE SET version = excluded.version, blob = excluded.blob, size = excluded.size, '
                     'device = excluded.device, updated_at = excluded.updated_at', (u['id'], ver, blob, len(dec), s['device'], db.now()))
        conn.commit()
    return {'version': ver}


@app.delete('/api/sm/library')
def library_delete(request: Request):
    with db.connect() as conn:
        u, _ = current(request, conn)
        conn.execute('DELETE FROM libraries WHERE user_id = ?', (u['id'],))
        conn.commit()
    return {'ok': True}


@app.put('/api/sm/settings')
async def settings_put(request: Request):
    b = await body(request)
    with db.connect() as conn:
        u, _ = current(request, conn)
        if 'sync_enabled' in b:
            conn.execute('UPDATE users SET sync_enabled = ? WHERE id = ?', (1 if b['sync_enabled'] else 0, u['id']))
            conn.commit()
        u = conn.execute('SELECT sync_enabled FROM users WHERE id = ?', (u['id'],)).fetchone()
    return {'sync_enabled': bool(u['sync_enabled'])}


# ---------------- web hesabım ----------------
def release_public(r):
    if not r:
        return None
    return {'version': r['version'], 'notes': r['notes'], 'size': r['setup_size'], 'sha256': r['setup_sha256'],
            'portable': bool(r['portable_file']), 'portable_size': r['portable_size'], 'date': r['created_at']}


@app.get('/api/sm/account')
def account(request: Request):
    with db.connect() as conn:
        u, s = current(request, conn, web_only=True)
        sessions = [{'id': x['id'], 'kind': x['kind'], 'device': x['device'], 'app_version': x['app_version'], 'created_at': x['created_at'],
                     'last_seen': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(x['last_seen'])), 'current': x['id'] == s['id']}
                    for x in conn.execute('SELECT * FROM sessions WHERE user_id = ? ORDER BY last_seen DESC', (u['id'],))]
        r = latest_release(conn)
        return {'user': user_public(u), 'sync_enabled': bool(u['sync_enabled']), 'library': library_meta(conn, u['id']),
                'release': release_public(r), 'download_url': f"/indir/{u['dl_token']}", 'sessions': sessions,
                'downloads': conn.execute('SELECT COUNT(*) FROM downloads WHERE user_id = ?', (u['id'],)).fetchone()[0]}


@app.delete('/api/sm/sessions/{sid}')
def session_revoke(sid: int, request: Request):
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
        conn.execute('DELETE FROM sessions WHERE id = ? AND user_id = ?', (sid, u['id']))
        conn.commit()
    return {'ok': True}


@app.post('/api/sm/account/rotate-link')
def rotate_link(request: Request):
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
        tok = secrets.token_urlsafe(24)
        conn.execute('UPDATE users SET dl_token = ? WHERE id = ?', (tok, u['id']))
        conn.commit()
    return {'download_url': f'/indir/{tok}'}


@app.get('/indir/{tok}')
def download(tok: str, request: Request, tur: str = 'setup'):
    with db.connect() as conn:
        u, _ = current(request, conn, require=False, web_only=True)
        if not u:
            return RedirectResponse(f'/giris?sonra=/indir/{tok}', status_code=303)
        if not hmac.compare_digest(u['dl_token'], tok):
            return HTMLResponse(_page_msg('Bu indirme bağlantısı size ait değil',
                                          'İndirme bağlantıları kişiye özeldir ve yalnız sahibi oturum açmışken çalışır. '
                                          'Kendi bağlantınıza <a href="/hesabim">Hesabım</a> sayfasından ulaşabilirsiniz.'), status_code=403)
        r = latest_release(conn)
        if not r:
            return HTMLResponse(_page_msg('Henüz indirilebilir sürüm yok', 'Sürüm yayımlanınca bu sayfadan indirebilirsiniz.'), status_code=404)
        port = tur == 'portable' and r['portable_file']
        name = r['portable_file'] if port else r['setup_file']
        path = settings.RELEASE_DIR / r['version'] / name
        if not path.is_file():
            return HTMLResponse(_page_msg('Dosya bulunamadı', 'Lütfen daha sonra tekrar deneyin.'), status_code=404)
        conn.execute('INSERT INTO downloads (user_id, release_id, kind, ip, at) VALUES (?,?,?,?,?)',
                     (u['id'], r['id'], 'portable' if port else 'setup', client_ip(request), db.now()))
        conn.commit()
    return FileResponse(path, filename=name, media_type='application/octet-stream', headers={'Cache-Control': 'private, no-store'})


@app.get('/api/sm/releases/latest')
def release_latest(request: Request):
    with db.connect() as conn:
        current(request, conn)
        r = latest_release(conn)
    return release_public(r) or {'version': None}


# ---------------- sürüm yükleme (CI / Merkez) ----------------
def _release_auth(request):
    key = request.headers.get('x-release-key') or ''
    if settings.RELEASE_KEY and hmac.compare_digest(key, settings.RELEASE_KEY):
        return
    central(request)


def _safe_name(n, fallback):
    n = re.sub(r'[^A-Za-z0-9 ._()-]', '_', (n or '').split('/')[-1].split('\\')[-1]).strip() or fallback
    return n[:120] if n.lower().endswith('.exe') else fallback


@app.post('/api/sm/releases')
async def release_upload(request: Request, version: str = Form(...), setup: UploadFile = File(...),
                         portable: UploadFile = File(None), notes: str = Form('')):
    _release_auth(request)
    version = version.strip().lstrip('vV')
    if not VERSION_RE.match(version):
        raise Err(422, 'invalid_version', 'Sürüm numarası geçersiz (ör. 1.2.0)')
    d = settings.RELEASE_DIR / version
    with db.connect() as conn:
        if conn.execute('SELECT 1 FROM releases WHERE version = ?', (version,)).fetchone():
            raise Err(409, 'exists', 'Bu sürüm zaten yüklü')
    d.mkdir(parents=True, exist_ok=True)

    async def save(up, fallback):
        name = _safe_name(up.filename, fallback)
        h, size = hashlib.sha256(), 0
        with open(d / name, 'wb') as f:
            while chunk := await up.read(1024 * 1024):
                f.write(chunk); h.update(chunk); size += len(chunk)
        with open(d / name, 'rb') as f:
            head = f.read(2)
        if head != b'MZ':
            raise Err(422, 'not_exe', f'{name} bir Windows exe dosyası değil')
        return name, size, h.hexdigest()
    try:
        sname, ssize, ssha = await save(setup, f'SSH Master Setup {version}.exe')
        pname = psize = None
        if portable is not None and portable.filename:
            pname, psize, _ = await save(portable, f'SSH-Master-Portable-{version}.exe')
    except Err:
        shutil.rmtree(d, ignore_errors=True)
        raise
    with db.connect() as conn:
        conn.execute('INSERT INTO releases (version, setup_file, setup_size, setup_sha256, portable_file, portable_size, notes, created_at) '
                     'VALUES (?,?,?,?,?,?,?,?)', (version, sname, ssize, ssha, pname, psize, notes.strip()[:4000] or None, db.now()))
        conn.commit()
    return {'ok': True, 'version': version, 'sha256': ssha}


# ---------------- yönetim (HEPGO Merkez) ----------------
@app.get('/api/sm/admin/users')
def admin_users(request: Request):
    central(request)
    with db.connect() as conn:
        rows = conn.execute("""SELECT u.id, u.email, u.name, u.status, u.verified_at, u.sync_enabled, u.note, u.created_at, u.last_login,
                                      l.version AS lib_version, l.size AS lib_size, l.updated_at AS lib_updated,
                                      (SELECT COUNT(*) FROM sessions s WHERE s.user_id = u.id AND s.kind = 'app') AS app_sessions,
                                      (SELECT COUNT(*) FROM downloads d WHERE d.user_id = u.id) AS downloads
                               FROM users u LEFT JOIN libraries l ON l.user_id = u.id ORDER BY u.id DESC""").fetchall()
        stats = {'users': len(rows), 'active': sum(1 for r in rows if r['status'] == 'AKTIF'),
                 'pending': sum(1 for r in rows if r['status'] == 'BEKLIYOR'), 'suspended': sum(1 for r in rows if r['status'] == 'ASKIDA'),
                 'downloads': conn.execute('SELECT COUNT(*) FROM downloads').fetchone()[0],
                 'release': release_public(latest_release(conn))}
    return {'users': [dict(r) for r in rows], 'stats': stats}


@app.get('/api/sm/admin/users/{uid}')
def admin_user(uid: int, request: Request):
    central(request)
    with db.connect() as conn:
        u = conn.execute('SELECT id, email, name, status, verified_at, sync_enabled, note, created_at, last_login FROM users WHERE id = ?', (uid,)).fetchone()
        if not u:
            raise Err(404, 'not_found', 'Kullanıcı bulunamadı')
        sessions = [dict(x) | {'last_seen': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(x['last_seen']))}
                    for x in conn.execute('SELECT id, kind, device, app_version, ip, created_at, last_seen FROM sessions WHERE user_id = ? ORDER BY last_seen DESC', (uid,))]
        downloads = [dict(x) for x in conn.execute('''SELECT d.at, d.kind, d.ip, r.version FROM downloads d LEFT JOIN releases r ON r.id = d.release_id
                                                       WHERE d.user_id = ? ORDER BY d.id DESC LIMIT 50''', (uid,))]
        return {'user': dict(u), 'library': library_meta(conn, uid), 'sessions': sessions, 'downloads': downloads}


@app.put('/api/sm/admin/users/{uid}')
async def admin_user_update(uid: int, request: Request):
    central(request)
    b = await body(request)
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
        if not u:
            raise Err(404, 'not_found', 'Kullanıcı bulunamadı')
        if 'status' in b:
            st = b['status']
            if st not in ('AKTIF', 'ASKIDA'):
                raise Err(422, 'invalid', 'Durum AKTIF ya da ASKIDA olmalı')
            conn.execute('UPDATE users SET status = ?, verified_at = COALESCE(verified_at, ?) WHERE id = ?', (st, db.now() if st == 'AKTIF' else None, uid))
            if st == 'ASKIDA':
                conn.execute('DELETE FROM sessions WHERE user_id = ?', (uid,))   # askıya alınan hemen düşer
        if 'name' in b:
            name = str(b['name'] or '').strip()[:80]
            if len(name) >= 2:
                conn.execute('UPDATE users SET name = ? WHERE id = ?', (name, uid))
        if 'note' in b:
            conn.execute('UPDATE users SET note = ? WHERE id = ?', (str(b['note'] or '').strip()[:1000] or None, uid))
        conn.commit()
    return {'ok': True}


@app.delete('/api/sm/admin/users/{uid}')
def admin_user_delete(uid: int, request: Request):
    central(request)
    with db.connect() as conn:
        conn.execute('DELETE FROM users WHERE id = ?', (uid,))
        conn.commit()
    return {'ok': True}


@app.post('/api/sm/admin/users/{uid}/reset-mail')
def admin_reset_mail(uid: int, request: Request):
    central(request)
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
        if not u:
            raise Err(404, 'not_found', 'Kullanıcı bulunamadı')
        if not mailer.enabled():
            raise Err(503, 'mail_disabled', 'E-posta gönderimi yapılandırılmamış')
        if u['status'] == 'BEKLIYOR':
            tok = new_token(conn, uid, 'verify', settings.VERIFY_HOURS * 3600)
            conn.commit()
            mailer.send_verify(u['email'], u['name'], f'{settings.PUBLIC_URL}/dogrula/{tok}')
            return {'ok': True, 'sent': 'verify'}
        tok = new_token(conn, uid, 'reset', settings.RESET_MINUTES * 60, salt=b64salt())
        conn.commit()
        mailer.send_reset(u['email'], u['name'], f'{settings.PUBLIC_URL}/sifre-sifirla/{tok}')
    return {'ok': True, 'sent': 'reset'}


@app.get('/api/sm/admin/releases')
def admin_releases(request: Request):
    central(request)
    with db.connect() as conn:
        rows = conn.execute('''SELECT r.*, (SELECT COUNT(*) FROM downloads d WHERE d.release_id = r.id) AS downloads
                               FROM releases r ORDER BY r.id DESC''').fetchall()
    return [dict(r) for r in rows]


@app.delete('/api/sm/admin/releases/{rid}')
def admin_release_delete(rid: int, request: Request):
    central(request)
    with db.connect() as conn:
        r = conn.execute('SELECT * FROM releases WHERE id = ?', (rid,)).fetchone()
        if not r:
            raise Err(404, 'not_found', 'Sürüm bulunamadı')
        conn.execute('DELETE FROM releases WHERE id = ?', (rid,))
        conn.commit()
    shutil.rmtree(settings.RELEASE_DIR / r['version'], ignore_errors=True)
    return {'ok': True}


# ---------------- sayfalar ----------------
def _page_msg(title, html):
    return (f'<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title} — SSH Master</title><link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/site.css"></head>'
            f'<body class="acc"><main class="acc-box"><a class="brand" href="/"><img src="/favicon.svg" alt="" width="30" height="30">SSH Master</a>'
            f'<h1>{title}</h1><p class="muted">{html}</p></main></body></html>')


def _static(name, media=None):
    return FileResponse(settings.STATIC_DIR / name, media_type=media, headers={'Cache-Control': 'no-cache'})


@app.get('/')
def page_index():
    return _static('index.html', 'text/html')


@app.get('/kayit')
@app.get('/giris')
@app.get('/sifremi-unuttum')
@app.get('/hesabim')
def page_account():
    return _static('hesap.html', 'text/html')


@app.get('/sifre-sifirla/{tok}')
def page_reset(tok: str):
    return _static('hesap.html', 'text/html')


@app.get('/{name}')
def page_asset(name: str):
    allowed = {'favicon.svg': 'image/svg+xml', 'logo.png': 'image/png', 'site.css': 'text/css', 'hesap.js': 'text/javascript',
               'robots.txt': 'text/plain'}
    if name not in allowed or not (settings.STATIC_DIR / name).is_file():
        return HTMLResponse(_page_msg('Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    return _static(name, allowed[name])
