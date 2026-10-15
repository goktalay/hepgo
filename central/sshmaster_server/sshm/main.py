"""Mastertool hesap ve senkronizasyon servisi: tek hesapla SSH Master (sm) ve FTP Masters (fm).
Sözleşmeler: docs/sshmaster-api.md (v2, /api/sm — geriye dönük uyumlu), docs/ftpmasters-api.md (/api/fm), portal /api/mt.

- Siteler Host başlığıyla ayrılır: mastertool.download (hesap portalı), sshmasters.com ve ftpmasters.com (ürün / indirme sayfası;
  MT_PORTAL_LIVE=1 iken giriş / kayıt / hesap sayfaları portala yönlenir).
- Kimlik uçları (/auth/*, /me) üç önekte de aynıdır; kütüphane / ayar / sürüm uçları uygulamaya özeldir (/api/sm, /api/fm).
  Uygulama oturumu kendi uygulamasının uçlarını kullanır; yönetici o uygulamanın lisansını KAPALI yaparsa giriş ve indirme kapanır.

- Düz şifre sunucuya HİÇ gelmez: istemci (uygulama ve web/WebCrypto) master = PBKDF2(şifre, kdf_salt, 310000) türetir,
  auth_hash = b64(PBKDF2(master, şifre, 1)) gönderir; sunucu auth_hash'i kendi PBKDF2'siyle (ayrı tuz) saklar.
  Kütüphane anahtarı (HKDF(master)) istemcide kalır; sunucu blob'u okuyamaz.
- Web oturumu çerez (sm_session, HttpOnly/Secure/Lax); çerezli değişiklik istekleri ayrıca X-SSHM: 1 başlığı ister (CSRF).
  Uygulama oturumu Bearer token. Token'lar özet olarak saklanır.
- Kişiye özel indirme /indir/<dl_token>: yalnız AYNI kullanıcı web oturumuyla çalışır.
- Yönetim (HEPGO Merkez): /api/sm/admin/* iç anahtarla (X-Central-Secret). Destek talepleri Merkez'e iç anahtarla iletilir.
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

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from . import db, mailer, merkez, settings

VERSION = '2.0.0'
APPS = {'sm': {'name': 'SSH Master', 'setup': 'SSH Master Setup {v}.exe', 'portable': 'SSH-Master-Portable-{v}.exe'},
        'fm': {'name': 'FTP Masters', 'setup': 'FTP-Masters-Setup-{v}.exe', 'portable': 'FTP-Masters-Portable-{v}.exe'}}
PREFIXES = ('sm', 'fm', 'mt')      # mt = Mastertool portalı (web hesabı); kimlik uçları her önekte aynı
SITES = ('sm', 'fm', 'mt')
app = FastAPI(title='Mastertool', docs_url=None, redoc_url=None, openapi_url=None)
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


def need_prefix(a, apps_only=False):
    if a not in (APPS if apps_only else PREFIXES):
        raise Err(404, 'not_found', 'Bulunamadı')
    return a


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


def lic(conn, uid, a):
    """Kullanıcının uygulama lisansı / senkron tercihi; satır yoksa varsayılanla (AKTIF, senkron açık) oluşturulur."""
    r = conn.execute('SELECT * FROM user_apps WHERE user_id = ? AND app = ?', (uid, a)).fetchone()
    if not r:
        conn.execute('INSERT OR IGNORE INTO user_apps (user_id, app, created_at) VALUES (?,?,?)', (uid, a, db.now()))
        conn.commit()
        r = conn.execute('SELECT * FROM user_apps WHERE user_id = ? AND app = ?', (uid, a)).fetchone()
    return r


def need_license(conn, uid, a):
    if a in APPS and lic(conn, uid, a)['license'] != 'AKTIF':
        raise Err(403, 'app_disabled', f'Bu hesapta {APPS[a]["name"]} kullanımı kapalı')


def new_session(conn, user_id, kind, device=None, app_version=None, ip=None, a=None):
    tok = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO sessions (user_id, token_hash, kind, app, device, app_version, ip, created_at, last_seen) VALUES (?,?,?,?,?,?,?,?,?)',
                 (user_id, sha(tok), kind, a if kind == 'app' else None, (device or '')[:120] or None, (app_version or '')[:30] or None, ip,
                  db.now(), time.time()))
    return tok


def current(request, conn, require=True, web_only=False, a=None):
    """Oturumdaki kullanıcı: Bearer (uygulama) ya da çerez (web). Dönüş (user_row, session_row) | (None, None).
    a (sm|fm) verilirse uygulama oturumu yalnız kendi uygulamasının uçlarını kullanabilir ve lisansı açık olmalıdır."""
    tok, via_cookie = None, False
    hdr = request.headers.get('authorization') or ''
    if hdr.lower().startswith('bearer ') and not web_only:
        tok = hdr[7:].strip()
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
    if s['kind'] == 'app' and a in APPS:
        if (s['app'] or 'sm') != a:
            raise Err(403, 'wrong_app', 'Bu oturum başka bir uygulamaya ait')
        need_license(conn, u['id'], a)
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


def latest_release(conn, a='sm'):
    return conn.execute('SELECT * FROM releases WHERE app = ? ORDER BY id DESC LIMIT 1', (a,)).fetchone()


def rel_dir(a, version):
    return settings.RELEASE_DIR / version if a == 'sm' else settings.RELEASE_DIR / a / version   # sm: v1 yolu korunur


def site_of(request):
    """İsteğin geldiği site: mastertool.download → mt, sshmasters.com → sm, ftpmasters.com → fm (www dahil)."""
    host = (request.headers.get('host') or '').split(':')[0].lower().removeprefix('www.')
    for k, url in settings.SITE_URLS.items():
        if host and host == url.split('://', 1)[-1].split('/')[0].lower().removeprefix('www.'):
            return k
    return settings.DEFAULT_SITE if settings.DEFAULT_SITE in SITES else 'sm'


def acct(path):
    return f'{settings.ACCOUNT_URL}{path}'


@app.on_event('startup')
def _startup():
    db.init()
    settings.RELEASE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------- genel ----------------
@app.get('/api/{a}/health')
def health(a: str):
    need_prefix(a)
    return {'ok': True, 'version': VERSION, 'time': db.now()}


@app.post('/api/{a}/auth/prelogin')
async def prelogin(a: str, request: Request):
    need_prefix(a)
    rate(request, 'prelogin', 30)
    email = norm_email((await body(request)).get('email'))
    with db.connect() as conn:
        u = conn.execute('SELECT kdf_salt FROM users WHERE email = ?', (email,)).fetchone()
    return {'kdf': kdf(u['kdf_salt'] if u else det_salt(email))}


def brand_of(a, b):
    br = str((b or {}).get('brand') or '')
    return br if br in SITES else a


@app.post('/api/{a}/auth/register')
async def register(a: str, request: Request):
    need_prefix(a)
    rate(request, 'register', 5)
    b = await body(request)
    brand = brand_of(a, b)
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
            mailer.send_exists(email, u['name'], acct('/giris'), acct('/sifremi-unuttum'), brand)
            return {'ok': True}
        if u:   # doğrulanmamış kayıt yinelendi: ad/şifre güncellenir, yeni bağlantı gider
            conn.execute('UPDATE users SET name = ?, pw_hash = ?, kdf_salt = ? WHERE id = ?', (name, hash_auth(auth), det_salt(email), u['id']))
            uid = u['id']
        else:
            uid = conn.execute('INSERT INTO users (email, name, pw_hash, kdf_salt, dl_token, created_at) VALUES (?,?,?,?,?,?)',
                               (email, name, hash_auth(auth), det_salt(email), secrets.token_urlsafe(24), db.now())).lastrowid
        if a in APPS:
            lic(conn, uid, a)
        conn.execute("UPDATE tokens SET used_at = ? WHERE user_id = ? AND kind = 'verify' AND used_at IS NULL", (db.now(), uid))
        tok = new_token(conn, uid, 'verify', settings.VERIFY_HOURS * 3600)
        conn.commit()
    mailer.send_verify(email, name, acct(f'/dogrula/{tok}'), brand)
    return {'ok': True}


@app.post('/api/{a}/auth/resend-verify')
async def resend_verify(a: str, request: Request):
    need_prefix(a)
    rate(request, 'resend', 5)
    b = await body(request)
    email, brand = norm_email(b.get('email')), brand_of(a, b)
    with db.connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE email = ? AND status = 'BEKLIYOR'", (email,)).fetchone()
        if u and mailer.enabled():
            conn.execute("UPDATE tokens SET used_at = ? WHERE user_id = ? AND kind = 'verify' AND used_at IS NULL", (db.now(), u['id']))
            tok = new_token(conn, u['id'], 'verify', settings.VERIFY_HOURS * 3600)
            conn.commit()
            mailer.send_verify(email, u['name'], acct(f'/dogrula/{tok}'), brand)
    return {'ok': True}


def to_portal(request):
    """Ürün sitesindeki hesap sayfası isteği → portal (yalnız MT_PORTAL_LIVE=1 iken). Dönüş RedirectResponse | None."""
    site = site_of(request)
    if not settings.PORTAL_LIVE or site == 'mt':
        return None
    q = request.url.query
    q = q + ('&' if q else '') + f'app={site}' if 'app=' not in q else q
    return RedirectResponse(f'{settings.PORTAL_URL}{request.url.path}?{q}', status_code=302)


@app.get('/dogrula/{tok}')
def verify(tok: str, request: Request):
    if (r := to_portal(request)):
        return r
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


@app.post('/api/{a}/auth/login')
async def login(a: str, request: Request):
    need_prefix(a)
    rate(request, 'login', 10)
    b = await body(request)
    email = norm_email(b.get('email'))
    auth = need_auth_hash(b.get('auth_hash'))
    web = b.get('client') == 'web' or a == 'mt'
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
        if not web:
            need_license(conn, u['id'], a)
        tok = new_session(conn, u['id'], 'web' if web else 'app', b.get('device'), b.get('app_version'), client_ip(request), a)
        conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (db.now(), u['id']))
        conn.commit()
        sync = bool(lic(conn, u['id'], a)['sync_enabled']) if a in APPS else True
    out = {'user': user_public(u), 'sync_enabled': sync, 'kdf': kdf(u['kdf_salt'])}
    if web:
        resp = JSONResponse(out)
        set_cookie(resp, tok)
        return resp
    return {'token': tok, **out}


@app.post('/api/{a}/auth/logout')
def logout(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, s = current(request, conn, require=False)
        if s:
            conn.execute('DELETE FROM sessions WHERE id = ?', (s['id'],))
            conn.commit()
    resp = JSONResponse({'ok': True})
    resp.delete_cookie(COOKIE, path='/')
    return resp


def library_meta(conn, uid, a='sm'):
    lib = conn.execute('SELECT version, updated_at, size, device FROM libraries WHERE user_id = ? AND app = ?', (uid, a)).fetchone()
    return dict(lib) if lib else {'version': 0, 'updated_at': None, 'size': 0, 'device': None}


@app.get('/api/{a}/me')
def me(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, a=a)
        out = {'user': user_public(u), 'kdf': kdf(u['kdf_salt'])}
        if a in APPS:
            out |= {'sync_enabled': bool(lic(conn, u['id'], a)['sync_enabled']), 'library': library_meta(conn, u['id'], a)}
        return out


@app.post('/api/{a}/auth/forgot')
async def forgot(a: str, request: Request):
    need_prefix(a)
    rate(request, 'forgot', 5)
    b = await body(request)
    email, brand = norm_email(b.get('email')), brand_of(a, b)
    with db.connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE email = ? AND status != 'ASKIDA'", (email,)).fetchone()
        if u and mailer.enabled():
            conn.execute("UPDATE tokens SET used_at = ? WHERE user_id = ? AND kind = 'reset' AND used_at IS NULL", (db.now(), u['id']))
            tok = new_token(conn, u['id'], 'reset', settings.RESET_MINUTES * 60, salt=b64salt())
            conn.commit()
            mailer.send_reset(email, u['name'], acct(f'/sifre-sifirla/{tok}'), brand)
    return {'ok': True}   # e-posta kayıtlı olsun olmasın aynı yanıt


@app.get('/api/{a}/auth/reset/{tok}')
def reset_info(a: str, tok: str):
    need_prefix(a)
    with db.connect() as conn:
        t = take_token(conn, tok, 'reset')
        if not t:
            raise Err(404, 'invalid_token', 'Bağlantı geçersiz ya da süresi dolmuş')
        u = conn.execute('SELECT email FROM users WHERE id = ?', (t['user_id'],)).fetchone()
    return {'email': u['email'], 'kdf': kdf(t['salt'])}


def _apply_new_password(conn, uid, new_auth, new_salt, keep_session=None):
    """Şifre değişti: eski anahtarla şifreli kütüphaneler (tüm uygulamalar) okunamaz → silinir; diğer oturumlar düşer."""
    conn.execute('UPDATE users SET pw_hash = ?, kdf_salt = ? WHERE id = ?', (hash_auth(new_auth), new_salt, uid))
    conn.execute('DELETE FROM libraries WHERE user_id = ?', (uid,))
    conn.execute('DELETE FROM sessions WHERE user_id = ? AND id != ?', (uid, keep_session or 0))


@app.post('/api/{a}/auth/reset/{tok}')
async def reset_apply(a: str, tok: str, request: Request):
    need_prefix(a)
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


@app.post('/api/{a}/auth/new-salt')
def new_salt(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn)
        salt = b64salt()
        conn.execute('INSERT INTO tokens (user_id, kind, token_hash, salt, expires) VALUES (?,?,?,?,?)',
                     (u['id'], 'newsalt', sha(salt + ':' + secrets.token_hex(8)), salt, time.time() + 900))
        conn.commit()
    return {'kdf': kdf(salt)}


@app.post('/api/{a}/auth/change-password')
async def change_password(a: str, request: Request):
    need_prefix(a)
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
@app.get('/api/{a}/library')
def library_get(a: str, request: Request):
    need_prefix(a, apps_only=True)
    with db.connect() as conn:
        u, _ = current(request, conn, a=a)
        lib = conn.execute('SELECT * FROM libraries WHERE user_id = ? AND app = ?', (u['id'], a)).fetchone()
    if not lib:
        return {'version': 0, 'updated_at': None, 'blob': None}
    return {'version': lib['version'], 'updated_at': lib['updated_at'], 'blob': lib['blob']}


@app.put('/api/{a}/library')
async def library_put(a: str, request: Request):
    need_prefix(a, apps_only=True)
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
        u, s = current(request, conn, a=a)
        lib = conn.execute('SELECT * FROM libraries WHERE user_id = ? AND app = ?', (u['id'], a)).fetchone()
        cur = lib['version'] if lib else 0
        if base != cur:
            return JSONResponse({'code': 'conflict', 'message': 'Sunucudaki kütüphane daha yeni', 'detail': 'conflict',
                                 'version': cur, 'blob': lib['blob'] if lib else None}, status_code=409)
        ver = cur + 1
        conn.execute('INSERT INTO libraries (user_id, app, version, blob, size, device, updated_at) VALUES (?,?,?,?,?,?,?) '
                     'ON CONFLICT(user_id, app) DO UPDATE SET version = excluded.version, blob = excluded.blob, size = excluded.size, '
                     'device = excluded.device, updated_at = excluded.updated_at', (u['id'], a, ver, blob, len(dec), s['device'], db.now()))
        conn.commit()
    return {'version': ver}


@app.delete('/api/{a}/library')
def library_delete(a: str, request: Request):
    need_prefix(a, apps_only=True)
    with db.connect() as conn:
        u, _ = current(request, conn, a=a)
        conn.execute('DELETE FROM libraries WHERE user_id = ? AND app = ?', (u['id'], a))
        conn.commit()
    return {'ok': True}


@app.put('/api/{a}/settings')
async def settings_put(a: str, request: Request):
    need_prefix(a, apps_only=True)
    b = await body(request)
    with db.connect() as conn:
        u, _ = current(request, conn, a=a)
        lic(conn, u['id'], a)
        if 'sync_enabled' in b:
            conn.execute('UPDATE user_apps SET sync_enabled = ? WHERE user_id = ? AND app = ?', (1 if b['sync_enabled'] else 0, u['id'], a))
            if a == 'sm':   # v1 alanı (eski yönetim görünümü) eşit kalsın
                conn.execute('UPDATE users SET sync_enabled = ? WHERE id = ?', (1 if b['sync_enabled'] else 0, u['id']))
            conn.commit()
        return {'sync_enabled': bool(lic(conn, u['id'], a)['sync_enabled'])}


# ---------------- web hesabım (portal) ----------------
def release_public(r):
    if not r:
        return None
    return {'version': r['version'], 'notes': r['notes'], 'size': r['setup_size'], 'sha256': r['setup_sha256'],
            'portable': bool(r['portable_file']), 'portable_size': r['portable_size'], 'date': r['created_at']}


def _dl_url(u, a):
    return f"/indir/{u['dl_token']}" if a == 'sm' else f"/indir/{u['dl_token']}/{a}"


@app.get('/api/{a}/account')
def account(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, s = current(request, conn, web_only=True)
        sessions = [{'id': x['id'], 'kind': x['kind'], 'app': x['app'], 'device': x['device'], 'app_version': x['app_version'],
                     'created_at': x['created_at'], 'last_seen': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(x['last_seen'])),
                     'current': x['id'] == s['id']}
                    for x in conn.execute('SELECT * FROM sessions WHERE user_id = ? ORDER BY last_seen DESC', (u['id'],))]
        apps = []
        for k, meta in APPS.items():
            L = lic(conn, u['id'], k)
            apps.append({'app': k, 'name': meta['name'], 'license': L['license'], 'sync_enabled': bool(L['sync_enabled']),
                         'library': library_meta(conn, u['id'], k), 'release': release_public(latest_release(conn, k)),
                         'download_url': _dl_url(u, k),
                         'downloads': conn.execute('SELECT COUNT(*) FROM downloads WHERE user_id = ? AND app = ?', (u['id'], k)).fetchone()[0]})
        sm = apps[0]
        # sm alanları üst düzeyde de (v1 hesap sayfası önbellekte kalmış tarayıcılar için)
        return {'user': user_public(u), 'apps': apps, 'sessions': sessions, 'sync_enabled': sm['sync_enabled'], 'library': sm['library'],
                'release': sm['release'], 'download_url': sm['download_url'],
                'downloads': conn.execute('SELECT COUNT(*) FROM downloads WHERE user_id = ?', (u['id'],)).fetchone()[0]}


@app.delete('/api/{a}/sessions/{sid}')
def session_revoke(a: str, sid: int, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
        conn.execute('DELETE FROM sessions WHERE id = ? AND user_id = ?', (sid, u['id']))
        conn.commit()
    return {'ok': True}


@app.post('/api/{a}/account/rotate-link')
def rotate_link(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
        tok = secrets.token_urlsafe(24)
        conn.execute('UPDATE users SET dl_token = ? WHERE id = ?', (tok, u['id']))
        conn.commit()
    return {'download_url': f'/indir/{tok}'}


def _download(tok, a, request, tur):
    if (r := to_portal(request)):
        return r
    with db.connect() as conn:
        u, _ = current(request, conn, require=False, web_only=True)
        if not u:
            return RedirectResponse(f'/giris?sonra={request.url.path}', status_code=303)
        if not hmac.compare_digest(u['dl_token'], tok):
            return HTMLResponse(_page_msg(request, 'Bu indirme bağlantısı size ait değil',
                                          'İndirme bağlantıları kişiye özeldir ve yalnız sahibi oturum açmışken çalışır. '
                                          'Kendi bağlantınıza <a href="/hesabim">Hesabım</a> sayfasından ulaşabilirsiniz.'), status_code=403)
        if lic(conn, u['id'], a)['license'] != 'AKTIF':
            return HTMLResponse(_page_msg(request, f'{APPS[a]["name"]} hesabınızda kapalı',
                                          'Bu uygulamanın kullanımı hesabınız için kapatılmış. <a href="/hesabim#destek">Destek</a> talebi açabilirsiniz.'),
                                status_code=403)
        r = latest_release(conn, a)
        if not r:
            return HTMLResponse(_page_msg(request, 'Henüz indirilebilir sürüm yok', 'Sürüm yayımlanınca bu sayfadan indirebilirsiniz.'), status_code=404)
        port = tur == 'portable' and r['portable_file']
        name = r['portable_file'] if port else r['setup_file']
        path = rel_dir(a, r['version']) / name
        if not path.is_file():
            return HTMLResponse(_page_msg(request, 'Dosya bulunamadı', 'Lütfen daha sonra tekrar deneyin.'), status_code=404)
        conn.execute('INSERT INTO downloads (user_id, release_id, app, kind, ip, at) VALUES (?,?,?,?,?,?)',
                     (u['id'], r['id'], a, 'portable' if port else 'setup', client_ip(request), db.now()))
        conn.commit()
    return FileResponse(path, filename=name, media_type='application/octet-stream', headers={'Cache-Control': 'private, no-store'})


@app.get('/indir/{tok}')
def download(tok: str, request: Request, tur: str = 'setup'):
    return _download(tok, 'sm', request, tur)


@app.get('/indir/{tok}/{a}')
def download_app(tok: str, a: str, request: Request, tur: str = 'setup'):
    if a not in APPS:
        return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    return _download(tok, a, request, tur)


@app.get('/api/{a}/releases/latest')
def release_latest(a: str, request: Request):
    need_prefix(a, apps_only=True)
    with db.connect() as conn:
        current(request, conn, a=a)
        r = latest_release(conn, a)
    return release_public(r) or {'version': None}


# ---------------- sürüm yükleme (CI / Merkez) ----------------
def _release_auth(request, a):
    key = request.headers.get('x-release-key') or ''
    rk = settings.RELEASE_KEYS.get(a) or ''
    if rk and hmac.compare_digest(key, rk):
        return
    central(request)


def _safe_name(n, fallback):
    n = re.sub(r'[^A-Za-z0-9 ._()-]', '_', (n or '').split('/')[-1].split('\\')[-1]).strip() or fallback
    return n[:120] if n.lower().endswith('.exe') else fallback


def _version(v):
    v = (v or '').strip().lstrip('vV')
    if not VERSION_RE.match(v):
        raise Err(422, 'invalid_version', 'Sürüm numarası geçersiz (ör. 1.2.0)')
    return v


async def _save_upload(up, path, append=False):
    size = 0
    with open(path, 'ab' if append else 'wb') as f:
        while chunk := await up.read(1024 * 1024):
            f.write(chunk); size += len(chunk)
    return size


def _finish_exe(path):
    """Dosya tamam: exe mi (MZ), boyut ve SHA-256."""
    with open(path, 'rb') as f:
        if f.read(2) != b'MZ':
            raise Err(422, 'not_exe', f'{path.name} bir Windows exe dosyası değil')
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return path.stat().st_size, h.hexdigest()


@app.post('/api/{a}/releases')
async def release_upload(a: str, request: Request, version: str = Form(...), setup: UploadFile = File(...),
                         portable: UploadFile = File(None), notes: str = Form('')):
    """Tek istekte yükleme (setup + isteğe bağlı portable). Cloudflare tek istekte 100 MB sınırı koyar: büyük dosyalar için
    parçalı uç /api/{a}/releases/{version}/{setup|portable} kullanılır."""
    need_prefix(a, apps_only=True)
    _release_auth(request, a)
    version = _version(version)
    d = rel_dir(a, version)
    with db.connect() as conn:
        if conn.execute('SELECT 1 FROM releases WHERE app = ? AND version = ?', (a, version)).fetchone():
            raise Err(409, 'exists', 'Bu sürüm zaten yüklü')
    d.mkdir(parents=True, exist_ok=True)
    try:
        sname = _safe_name(setup.filename, APPS[a]['setup'].format(v=version))
        await _save_upload(setup, d / sname)
        ssize, ssha = _finish_exe(d / sname)
        pname = psize = None
        if portable is not None and portable.filename:
            pname = _safe_name(portable.filename, APPS[a]['portable'].format(v=version))
            await _save_upload(portable, d / pname)
            psize, _ = _finish_exe(d / pname)
    except Err:
        shutil.rmtree(d, ignore_errors=True)
        raise
    with db.connect() as conn:
        conn.execute('INSERT INTO releases (app, version, setup_file, setup_size, setup_sha256, portable_file, portable_size, notes, created_at) '
                     'VALUES (?,?,?,?,?,?,?,?,?)', (a, version, sname, ssize, ssha, pname, psize, notes.strip()[:4000] or None, db.now()))
        conn.commit()
    return {'ok': True, 'version': version, 'sha256': ssha}


@app.post('/api/{a}/releases/{version}/{kind}')
async def release_part(a: str, version: str, kind: str, request: Request, file: UploadFile = File(...), part: int = Form(0),
                       parts: int = Form(1), notes: str = Form(''), filename: str = Form('')):
    """Tek dosya, isteğe bağlı parçalı yükleme (her parça < 100 MB). part 0..parts-1 sırayla gönderilir; son parçada dosya
    doğrulanır (MZ, SHA-256). kind=setup sürümü oluşturur (notes ile); kind=portable var olan sürüme taşınabilir dosyayı ekler.
    Yanıt: ara parçada {ok, received}, son parçada {ok, version, kind, sha256, size}."""
    need_prefix(a, apps_only=True)
    _release_auth(request, a)
    version = _version(version)
    if kind not in ('setup', 'portable'):
        raise Err(404, 'not_found', 'Bulunamadı')
    if not (1 <= parts <= 64 and 0 <= part < parts):
        raise Err(422, 'invalid', 'part / parts geçersiz')
    with db.connect() as conn:
        r = conn.execute('SELECT * FROM releases WHERE app = ? AND version = ?', (a, version)).fetchone()
    if kind == 'setup' and r:
        raise Err(409, 'exists', 'Bu sürüm zaten yüklü')
    if kind == 'portable' and not r:
        raise Err(404, 'no_release', 'Önce kurulum dosyası yüklenmeli')
    if kind == 'portable' and r['portable_file']:
        raise Err(409, 'exists', 'Bu sürümün taşınabilir dosyası zaten yüklü')
    d = rel_dir(a, version)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f'.{kind}.part'
    if part == 0:
        tmp.unlink(missing_ok=True)
    elif not tmp.exists() or int(request.headers.get('x-part-offset', tmp.stat().st_size)) != tmp.stat().st_size:
        raise Err(409, 'part_order', 'Parçalar sırayla gönderilmeli (baştan başlayın: part=0)')
    await _save_upload(file, tmp, append=part > 0)
    if tmp.stat().st_size > 2 * 1024 ** 3:
        tmp.unlink(missing_ok=True)
        raise Err(413, 'too_large', 'Dosya çok büyük')
    if part < parts - 1:
        return {'ok': True, 'received': tmp.stat().st_size}
    name = _safe_name(filename or file.filename, APPS[a][kind].format(v=version))
    try:
        size, sha = _finish_exe(tmp)
    except Err:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(d / name)
    with db.connect() as conn:
        if kind == 'setup':
            conn.execute('INSERT INTO releases (app, version, setup_file, setup_size, setup_sha256, notes, created_at) VALUES (?,?,?,?,?,?,?)',
                         (a, version, name, size, sha, notes.strip()[:4000] or None, db.now()))
        else:
            conn.execute('UPDATE releases SET portable_file = ?, portable_size = ? WHERE id = ?', (name, size, r['id']))
        conn.commit()
    return {'ok': True, 'version': version, 'kind': kind, 'sha256': sha, 'size': size}


# ---------------- destek talepleri (Merkez talep ekranına düşer) ----------------
TICKET_APPS = {'sm': 'SSH Master', 'fm': 'FTP Masters', 'mt': 'Hesap / genel'}


def _mz(fn):
    try:
        return fn()
    except merkez.MerkezError as e:
        raise Err(e.status, 'support_error', e.message)


def _who(u):
    return {'email': u['email'], 'name': u['name']}


@app.get('/api/{a}/tickets')
def tickets(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
    return _mz(lambda: merkez.call('GET', '/api/federation/mastertool/tickets', params={'email': u['email']}))


@app.post('/api/{a}/tickets')
async def ticket_create(a: str, request: Request):
    need_prefix(a)
    rate(request, 'ticket', 10, 600)
    b = await body(request)
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
    ta = str(b.get('app') or 'mt')
    payload = _who(u) | {'app': ta if ta in TICKET_APPS else 'mt', 'subject': str(b.get('subject') or '')[:200],
                         'body': str(b.get('body') or '')[:8000], 'category': str(b.get('category') or 'teknik')[:20]}
    return _mz(lambda: merkez.call('POST', '/api/federation/mastertool/tickets', json=payload))


@app.get('/api/{a}/tickets/{tid}')
def ticket_get(a: str, tid: int, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
    return _mz(lambda: merkez.call('GET', f'/api/federation/mastertool/tickets/{tid}', params={'email': u['email']}))


@app.post('/api/{a}/tickets/{tid}/messages')
async def ticket_reply(a: str, tid: int, request: Request):
    need_prefix(a)
    rate(request, 'ticket-msg', 30, 600)
    b = await body(request)
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
    return _mz(lambda: merkez.call('POST', f'/api/federation/mastertool/tickets/{tid}/messages',
                                   json=_who(u) | {'body': str(b.get('body') or '')[:8000]}))


@app.post('/api/{a}/tickets/{tid}/close')
def ticket_close(a: str, tid: int, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
    return _mz(lambda: merkez.call('POST', f'/api/federation/mastertool/tickets/{tid}/close', json=_who(u)))


@app.post('/api/mt/internal/ticket-reply')
async def ticket_notify(request: Request):
    """Merkez destek ekibi bir Mastertool talebine yanıt yazınca çağırır → kullanıcıya markalı e-posta."""
    central(request)
    b = await body(request)
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE email = ?', (str(b.get('email') or '').lower(),)).fetchone()
    if not u or not mailer.enabled():
        return {'ok': True, 'sent': False}
    brand = b.get('app') if b.get('app') in APPS else 'mt'
    mailer.send_ticket_reply(u['email'], u['name'], str(b.get('code') or '')[:20], str(b.get('subject') or '')[:200],
                             acct(f"/hesabim?talep={int(b.get('id') or 0)}#destek"), brand)
    return {'ok': True, 'sent': True}


# ---------------- yönetim (HEPGO Merkez) ----------------
def _admin_apps(conn, uid):
    out = {}
    for k in APPS:
        L = lic(conn, uid, k)
        lib = library_meta(conn, uid, k)
        out[k] = {'license': L['license'], 'sync_enabled': bool(L['sync_enabled']), 'lib_version': lib['version'], 'lib_size': lib['size'],
                  'lib_updated': lib['updated_at'],
                  'app_sessions': conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND kind = 'app' AND COALESCE(app, 'sm') = ?",
                                               (uid, k)).fetchone()[0],
                  'downloads': conn.execute('SELECT COUNT(*) FROM downloads WHERE user_id = ? AND app = ?', (uid, k)).fetchone()[0]}
    return out


@app.get('/api/sm/admin/users')
def admin_users(request: Request):
    central(request)
    with db.connect() as conn:
        rows = conn.execute('SELECT id, email, name, status, verified_at, sync_enabled, note, created_at, last_login FROM users ORDER BY id DESC').fetchall()
        users = []
        for r in rows:
            apps = _admin_apps(conn, r['id'])
            sm = apps['sm']   # v1 alanları üst düzeyde (eski yönetim ekranı)
            users.append(dict(r) | {'apps': apps, 'sync_enabled': int(sm['sync_enabled']), 'lib_version': sm['lib_version'] or None,
                                    'lib_size': sm['lib_size'] or None, 'lib_updated': sm['lib_updated'],
                                    'app_sessions': sum(x['app_sessions'] for x in apps.values()),
                                    'downloads': sum(x['downloads'] for x in apps.values())})
        stats = {'users': len(rows), 'active': sum(1 for r in rows if r['status'] == 'AKTIF'),
                 'pending': sum(1 for r in rows if r['status'] == 'BEKLIYOR'), 'suspended': sum(1 for r in rows if r['status'] == 'ASKIDA'),
                 'downloads': conn.execute('SELECT COUNT(*) FROM downloads').fetchone()[0],
                 'release': release_public(latest_release(conn, 'sm')),
                 'apps': {k: {'name': m['name'], 'release': release_public(latest_release(conn, k)),
                              'downloads': conn.execute('SELECT COUNT(*) FROM downloads WHERE app = ?', (k,)).fetchone()[0],
                              'users': sum(1 for x in users if x['apps'][k]['app_sessions'] or x['apps'][k]['downloads'])}
                          for k, m in APPS.items()}}
    return {'users': users, 'stats': stats}


@app.get('/api/sm/admin/users/{uid}')
def admin_user(uid: int, request: Request):
    central(request)
    with db.connect() as conn:
        u = conn.execute('SELECT id, email, name, status, verified_at, sync_enabled, note, created_at, last_login FROM users WHERE id = ?', (uid,)).fetchone()
        if not u:
            raise Err(404, 'not_found', 'Kullanıcı bulunamadı')
        sessions = [dict(x) | {'last_seen': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(x['last_seen']))}
                    for x in conn.execute('SELECT id, kind, app, device, app_version, ip, created_at, last_seen FROM sessions WHERE user_id = ? '
                                          'ORDER BY last_seen DESC', (uid,))]
        downloads = [dict(x) for x in conn.execute('''SELECT d.at, d.app, d.kind, d.ip, r.version FROM downloads d LEFT JOIN releases r ON r.id = d.release_id
                                                       WHERE d.user_id = ? ORDER BY d.id DESC LIMIT 50''', (uid,))]
        return {'user': dict(u), 'apps': _admin_apps(conn, uid), 'library': library_meta(conn, uid, 'sm'), 'sessions': sessions, 'downloads': downloads}


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
        if isinstance(b.get('apps'), dict):   # uygulama bazında lisans: {"fm": "KAPALI", "sm": "AKTIF"}
            for k, v in b['apps'].items():
                if k not in APPS or v not in ('AKTIF', 'KAPALI'):
                    raise Err(422, 'invalid', 'Lisans AKTIF ya da KAPALI olmalı')
                lic(conn, uid, k)
                conn.execute('UPDATE user_apps SET license = ? WHERE user_id = ? AND app = ?', (v, uid, k))
                if v == 'KAPALI':
                    conn.execute("DELETE FROM sessions WHERE user_id = ? AND kind = 'app' AND COALESCE(app, 'sm') = ?", (uid, k))
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
            mailer.send_verify(u['email'], u['name'], acct(f'/dogrula/{tok}'))
            return {'ok': True, 'sent': 'verify'}
        tok = new_token(conn, uid, 'reset', settings.RESET_MINUTES * 60, salt=b64salt())
        conn.commit()
        mailer.send_reset(u['email'], u['name'], acct(f'/sifre-sifirla/{tok}'))
    return {'ok': True, 'sent': 'reset'}


@app.get('/api/sm/admin/releases')
def admin_releases(request: Request, app_: str = Query('', alias='app')):
    central(request)
    with db.connect() as conn:
        rows = conn.execute('''SELECT r.*, (SELECT COUNT(*) FROM downloads d WHERE d.release_id = r.id) AS downloads
                               FROM releases r WHERE (? = '' OR r.app = ?) ORDER BY r.id DESC''', (app_, app_)).fetchall()
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
    shutil.rmtree(rel_dir(r['app'], r['version']), ignore_errors=True)
    return {'ok': True}


# ---------------- sayfalar (Host'a göre site) ----------------
SITE_NAMES = {'sm': 'SSH Master', 'fm': 'FTP Masters', 'mt': 'Mastertool'}


def _page_msg(request, title, html):
    site = site_of(request)
    return (f'<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title} — {SITE_NAMES[site]}</title><link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/site.css"></head>'
            f'<body class="acc"><main class="acc-box"><a class="brand" href="/"><img src="/favicon.svg" alt="" width="30" height="30">{SITE_NAMES[site]}</a>'
            f'<h1>{title}</h1><p class="muted">{html}</p></main></body></html>')


def _static(path, media=None):
    return FileResponse(path, media_type=media, headers={'Cache-Control': 'no-cache'})


@app.get('/')
def page_index(request: Request):
    return _static(settings.STATIC_DIR / site_of(request) / 'index.html', 'text/html')


def _account_page(request):
    if (r := to_portal(request)):
        return r
    site = site_of(request)
    brand = request.query_params.get('app') if site == 'mt' and request.query_params.get('app') in APPS else site
    html = (settings.STATIC_DIR / 'hesap.html').read_text(encoding='utf-8')
    html = html.replace('{{SITE}}', site).replace('{{BRAND}}', brand).replace('{{NAME}}', SITE_NAMES[site])
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})


@app.get('/kayit')
@app.get('/giris')
@app.get('/sifremi-unuttum')
@app.get('/hesabim')
def page_account(request: Request):
    return _account_page(request)


@app.get('/sifre-sifirla/{tok}')
def page_reset(tok: str, request: Request):
    return _account_page(request)


BRAND_FILES = {'sm.png': ('sm', 'logo.png', 'image/png'), 'fm.png': ('fm', 'logo.png', 'image/png'), 'mt.png': ('mt', 'logo.png', 'image/png'),
               'sm.svg': ('sm', 'favicon.svg', 'image/svg+xml'), 'fm.svg': ('fm', 'favicon.svg', 'image/svg+xml'),
               'mt.svg': ('mt', 'favicon.svg', 'image/svg+xml'), 'hepgo.png': ('mt', 'hepgo.png', 'image/png')}


@app.get('/brand/{name}')
def page_brand(name: str, request: Request):
    """Marka görselleri (e-posta logoları, portal ürün kartları) — her sitede aynı adreste."""
    if name not in BRAND_FILES:
        return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    d, f, media = BRAND_FILES[name]
    return FileResponse(settings.STATIC_DIR / d / f, media_type=media, headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/{name}')
def page_asset(name: str, request: Request):
    shared = {'site.css': 'text/css', 'hesap.js': 'text/javascript', 'robots.txt': 'text/plain'}
    per_site = {'favicon.svg': 'image/svg+xml', 'logo.png': 'image/png'}
    if name in shared and (settings.STATIC_DIR / name).is_file():
        return _static(settings.STATIC_DIR / name, shared[name])
    if name in per_site:
        return _static(settings.STATIC_DIR / site_of(request) / name, per_site[name])
    return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
