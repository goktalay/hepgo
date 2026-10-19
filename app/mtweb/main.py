"""mtweb — Mastertool hesabıyla giriş yapan kullanıcılara Notepad Master ve Convert Master web sürümleri (docs/mtweb.md).

HEPGO araç router'ları (tools_mt, tools_notepad, tools_convert) KOPYALANMADAN dahil edilir; `tools_common.tools_user`
bağımlılığı `dependency_overrides` ile Mastertool kullanıcısına çevrilir. Veri dizini / veritabanı mtweb'e özeldir (config.py).

Yollar (Cloudflare deseni ^/(web|static/mt|api/tools)(/|$)):
  /web/                      host'a göre yönlendirme          /web/healthz            sağlık
  /web/notepadmaster/        Notepad Master (oturum gerekir)   /web/convertmaster/     Convert Master
  /web/sshmaster|ftpmaster|sqlmaster/  "Web sürümü yakında" bilgi sayfası
  /web/common/, /static/mt/  ortak ön yüz dosyaları            /web/config.js          sayfa yapılandırması (kullanıcı, marka)
  /api/tools/...             yalnız beyaz listedeki araç uçları (uzak bağlantı uçları 403)
"""
import json
import logging
import re
import time
import traceback
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config  # noqa: F401 — ilk: çekirdek yollarını mtweb veri dizinine yönlendirir
from app.routers import tools_common, tools_convert, tools_mt, tools_notepad  # noqa: E402

from . import auth, db, quota  # noqa: E402

log = logging.getLogger('mtweb')

# CSP: inline script yok. Monaco: kendi AMD yükleyicisi (aynı köken), web worker (workerMain.js; blob: yedeği), satır içi stil
# öznitelikleri → style-src 'unsafe-inline'. Convert önizlemeleri blob:/data: görsel + medya. Dış bağlantı yok (connect-src 'self').
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob: data:; "
       "font-src 'self' data:; worker-src 'self' blob:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'self'")
HEADERS = {'Content-Security-Policy': CSP, 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin',
           'X-Frame-Options': 'SAMEORIGIN', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
           'Cross-Origin-Opener-Policy': 'same-origin'}

APP_OF = {'notepad': 'notepadmaster', 'convert': 'convertmaster'}
# Beyaz liste: (desen, uygulama | None)
API_ALLOW = [
    (re.compile(r'^/api/tools/mt/account$'), None),
    (re.compile(r'^/api/tools/mt/(notepadmaster|convertmaster)/fs/(list|mkdir|upload|download|delete|rename|usage)$'), 1),
    (re.compile(r'^/api/tools/(notepad)/[A-Za-z]+(/[A-Za-z]+)?$'), 'map'),
    (re.compile(r'^/api/tools/(convert)/[A-Za-z]+(/[A-Za-z]+)?$'), 'map'),
    (re.compile(r'^/api/tools/(convert)/media/[0-9a-f]{40}/[^/]+$'), 'map'),
]
# Uzak bağlantı / dışarıya ağ açan uçlar: bu serviste kapalı
API_BLOCK = re.compile(r'^/api/tools/notepad/(browse/|keys/)|^/api/tools/convert/(speech|ocr)/download$')
UPLOAD_PATH = re.compile(r'^/api/tools/mt/(notepadmaster|convertmaster)/fs/upload$')
DOWNLOAD_PATH = re.compile(r'/fs/download$|/pj/exportOutputs$|/pj/file$|/pj/exportTranscript$|/proj/cache$')
UNSAFE = ('POST', 'PUT', 'PATCH', 'DELETE')
REMOTE_OFF = 'Bu özellik masaüstü sürümünde'
_users = {}   # mt_id → (bitiş, yerel kullanıcı)


@asynccontextmanager
async def lifespan(app):
    db.init()
    quota.install()
    log.info('mtweb · veri %s · hesap %s', config.DATA_DIR, config.ACCOUNT_URL)
    yield
    await auth.close()


app = FastAPI(title='mtweb', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def _err(status, msg, headers=None):
    return JSONResponse({'detail': msg}, status_code=status, headers=headers)


def _api_app(path):
    """API yolu → (izinli mi, uygulama). Uygulama None → ortak uç (hesap)."""
    for rx, kind in API_ALLOW:
        m = rx.match(path)
        if m:
            if kind is None:
                return True, None
            if kind == 'map':
                return True, APP_OF[m.group(1)]
            return True, m.group(kind)
    return False, None


def _html_app(path):
    m = re.match(r'^/web/([a-z]+)/(?:(index|project)\.html)?$', path)
    return m.group(1) if m and m.group(1) in config.APPS else None


def _login_redirect(request):
    nxt = request.url.path + (f'?{request.url.query}' if request.url.query else '')
    return RedirectResponse('/giris?next=' + quote(nxt, safe='/'), status_code=302)


async def _resolve_user(request):
    """Çerez → (yerel kullanıcı | None, hata yanıtı | None)."""
    tok = request.cookies.get(config.COOKIE)
    if not tok:
        return None, None
    try:
        u = await auth.account_user(tok)
    except auth.AccountUnavailable:
        return None, _err(503, 'Hesap servisine ulaşılamıyor; biraz sonra tekrar deneyin')
    if not u:
        return None, None
    if not u['verified']:
        return None, _err(403, 'E-posta adresinizi doğrulayın')
    t = time.time()
    hit = _users.get(u['id'])
    if hit and hit[0] > t and hit[1]['username'] == u['email']:
        return hit[1], None
    local = db.user_for(u)
    local['name'] = u['name']
    _users[u['id']] = (t + config.ACCOUNT_CACHE_S, local)
    db.audit(local['id'], None, 'session', None, auth.client_ip(request))
    return local, None


def _secure(resp, path):
    for k, v in HEADERS.items():
        resp.headers.setdefault(k, v)
    resp.headers.setdefault('Cache-Control', 'no-store' if path.startswith('/api/') or path.endswith('.html') or path.endswith('/')
                            or path == '/web/config.js' else 'no-cache')
    return resp


@app.middleware('http')
async def _gate(request: Request, call_next):
    path = request.url.path
    resp = await _guard(request, path, call_next)
    return _secure(resp, path)


async def _guard(request, path, call_next):
    ip = auth.client_ip(request)
    if path.startswith('/api/'):
        if not path.startswith('/api/tools/'):
            return _err(404, 'Bulunamadı')
        if API_BLOCK.match(path):
            db.audit(None, None, 'blocked', None, ip, path[:120])
            return _err(403, REMOTE_OFF)
        allowed, app_name = _api_app(path)
        if not allowed:
            return _err(404, 'Bulunamadı')
        if app_name and app_name in config.DISABLED_APPS:
            return _err(403, 'Bu uygulama geçici olarak kapalı')
        unsafe = request.method in UNSAFE
        if unsafe and not auth.origin_ok(request):
            db.audit(None, app_name, 'csrf', None, ip, f'{request.method} {path[:100]}')
            return _err(403, 'İstek kaynağı doğrulanamadı')
        user, bad = await _resolve_user(request)
        if bad is not None:
            return bad
        if not user:
            return _err(401, 'Oturum açın')
        lim = config.RATE_WRITE if unsafe else config.RATE_READ
        wait = auth.rate_ok(f'{"w" if unsafe else "r"}:{user["id"]}', *lim) or auth.rate_ok(f'ip{"w" if unsafe else "r"}:{ip}', lim[0] * 3, lim[1])
        if wait:
            db.audit(user['id'], app_name, 'rate', None, ip)
            return _err(429, 'Çok fazla istek; biraz sonra tekrar deneyin', {'Retry-After': str(wait)})
        size = None
        if unsafe:
            cl = request.headers.get('content-length')
            if cl is None:
                if request.headers.get('transfer-encoding'):
                    return _err(411, 'Uzunluk bilgisi gerekli')
                cl = '0'
            try:
                size = int(cl)
            except ValueError:
                return _err(400, 'Geçersiz istek')
            if UPLOAD_PATH.match(path):
                if size > config.UPLOAD_BYTES + config.MB:
                    db.audit(user['id'], app_name, 'quota', size, ip, 'upload')
                    return _err(413, f'Dosya çok büyük (en çok {config.UPLOAD_BYTES // config.MB} MB)')
                used, _ = quota.usage(user['id'])
                if used + size > config.SPACE_BYTES + 64 * 1024:
                    db.audit(user['id'], app_name, 'quota', size, ip, 'space')
                    return _err(413, quota.space_error().detail)
            elif size > config.BODY_BYTES:
                return _err(413, 'İstek çok büyük')
        request.state.mt_user = user
        resp = await call_next(request)
        if unsafe or DOWNLOAD_PATH.search(path):
            if not unsafe:
                try:
                    size = int(resp.headers.get('content-length') or 0) or None
                except ValueError:
                    size = None
            db.audit(user['id'], app_name, path[len('/api/tools/'):][:80], size, ip, None if resp.status_code < 400 else f'HTTP {resp.status_code}')
        return resp

    if path.startswith('/static/mt/') and path.endswith('.html'):   # çıplak HTML yerine kimlikli sayfa
        m = re.match(r'^/static/mt/([a-z]+)/', path)
        return RedirectResponse(f'/web/{m.group(1)}/' if m else '/web/', status_code=302)
    app_name = _html_app(path)
    if app_name:
        if app_name in config.DISABLED_APPS:
            return HTMLResponse(_info_page(app_name, 'disabled'), status_code=503)
        user, bad = await _resolve_user(request)
        if bad is not None:
            if bad.status_code == 403:
                return HTMLResponse(_info_page(app_name, 'verify'), status_code=403)
            return bad
        if not user:
            return _login_redirect(request)
        request.state.mt_user = user
    elif path == '/web/config.js':
        user, _ = await _resolve_user(request)
        request.state.mt_user = user
    return await call_next(request)


def current_user(request: Request):
    u = getattr(request.state, 'mt_user', None)
    if not u:
        raise HTTPException(401, 'Oturum açın')
    return u


app.dependency_overrides[tools_common.tools_user] = current_user


@app.exception_handler(StarletteHTTPException)
async def _http(request, e):
    d = e.detail if isinstance(e.detail, str) else 'Hata'
    if e.status_code >= 500:
        d = 'Sunucu hatası; lütfen tekrar deneyin'
    return JSONResponse({'detail': d}, status_code=e.status_code, headers=dict(getattr(e, 'headers', None) or {}))


@app.exception_handler(RequestValidationError)
async def _val(request, e):
    return JSONResponse({'detail': 'İstek gövdesi geçersiz'}, status_code=422)


@app.exception_handler(Exception)
async def _genel(request, e):
    log.error('İç hata %s %s: %s', request.method, request.url.path, ''.join(traceback.format_exception(e))[-2000:])
    return JSONResponse({'detail': 'Sunucu hatası; lütfen tekrar deneyin'}, status_code=500, headers=HEADERS)


# --- mtweb'e özgü API uçları (HEPGO karşılıklarından ÖNCE kaydedilir) ----------------------------------------------
@app.get('/api/tools/mt/account')
def account(request: Request):
    u = current_user(request)
    return {'loggedIn': True, 'user': {'id': u['mt_id'], 'email': u['email'], 'name': u.get('name') or u['full_name']}, 'email': u['email'],
            'syncEnabled': False, 'state': 'off', 'lastSyncAt': None, 'error': None, 'hepgo': False, 'web': True, 'notice': None,
            'appVersion': 'Mastertool web'}


def _remote_kind(form):
    return (form or {}).get('kind') not in ('local', 'file')


@app.post('/api/tools/notepad/conn/save')
def np_conn_save(body: tools_notepad.Body, request: Request):
    u = current_user(request)
    form = tools_notepad._b(body).get('form') or {}
    if form.get('id'):
        old = tools_notepad.find_conn(tools_notepad.load_store(u['id']), form['id'])
        if old and old.get('kind') not in ('local', 'file'):
            raise HTTPException(403, REMOTE_OFF)
        if old and not form.get('kind'):
            form['kind'] = old['kind']
    if _remote_kind(form):
        raise HTTPException(403, REMOTE_OFF)
    return tools_notepad.conn_save(tools_notepad.Body(form=form), u)


@app.post('/api/tools/notepad/conn/test')
def np_conn_test(body: tools_notepad.Body, request: Request):
    current_user(request)
    if _remote_kind(tools_notepad._b(body).get('form')):
        raise HTTPException(403, REMOTE_OFF)
    return {'ok': True, 'ms': 0}


for r in (tools_mt.router, tools_notepad.router, tools_convert.router):
    app.include_router(r)


# --- sayfalar ------------------------------------------------------------------------------------------------------
@app.get('/web/healthz')
def healthz():
    return {'ok': True}


@app.get('/web')
@app.get('/web/')
def web_root(request: Request):
    host = (request.headers.get('host') or '').split(':')[0].strip().lower()
    host = host[4:] if host.startswith('www.') else host
    if host in config.HOST_APP:
        return RedirectResponse(config.HOST_APP[host], status_code=302)
    if host in config.HUB_HOSTS:
        return RedirectResponse('/uygulamalar', status_code=302)
    return RedirectResponse('/', status_code=302)


def _js_str(obj):
    return json.dumps(obj, ensure_ascii=False).replace('</', '<\\/').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


@app.get('/web/config.js')
def config_js(request: Request, app: str = ''):
    u = getattr(request.state, 'mt_user', None)
    app_name = app if app in config.APP_NAMES else ''
    cfg = {'app': app_name, 'appName': config.APP_NAMES.get(app_name, 'Mastertool'), 'remote': False,
           'user': {'name': u.get('name') or u['full_name'], 'email': u['email']} if u else None,
           'downloadUrl': config.DOWNLOAD_URL, 'allAppsUrl': config.ALL_APPS_URL, 'logoutUrl': '/api/mt/auth/logout', 'loginUrl': '/giris',
           'apps': list(config.APPS), 'disabled': sorted(config.DISABLED_APPS)}
    return Response(f'window.MTWEB = {_js_str(cfg)};\n', media_type='text/javascript; charset=utf-8')


def _inject(html, app_name):
    html = html.replace('<link rel="stylesheet" href="../common/hepgo.css">',
                        '<link rel="stylesheet" href="../common/hepgo.css">\n  <link rel="stylesheet" href="../common/mtweb.css">', 1)
    html = html.replace('<script src="../common/hepgo.js"></script>',
                        f'<script src="/web/config.js?app={app_name}"></script>\n  <script src="../common/mtweb.js"></script>\n'
                        '  <script src="../common/hepgo.js"></script>', 1)
    return html


@app.get('/web/{app_name}')
def web_app_slash(app_name: str):
    if app_name in config.APPS or app_name in config.SOON_APPS:
        return RedirectResponse(f'/web/{app_name}/', status_code=307)
    return HTMLResponse(_info_page(None, 'notfound'), status_code=404)


@app.get('/web/{app_name}/')
@app.get('/web/{app_name}/{page}.html')
def web_app(app_name: str, page: str = 'index'):
    if app_name in config.SOON_APPS:
        return HTMLResponse(_info_page(app_name, 'soon'))
    if app_name not in config.APPS or page not in ('index', 'project'):
        return HTMLResponse(_info_page(None, 'notfound'), status_code=404)
    html = (config.MT_STATIC / app_name / f'{page}.html').read_text(encoding='utf-8')
    return HTMLResponse(_inject(html, app_name))


def _info_page(app_name, kind):
    """Bilgi sayfası (yakında / kapalı / doğrulama / bulunamadı). Metinler mtweb.js'te dile göre doldurulur; burada İngilizce yedek."""
    name = config.APP_NAMES.get(app_name or '', 'Mastertool')
    fallback = {'soon': 'The web version is coming soon — download the desktop version.', 'disabled': 'This app is temporarily unavailable.',
                'verify': 'Please verify your e-mail address.', 'notfound': 'Page not found.'}[kind]
    icon = f'/static/mt/{app_name}/icon.png' if app_name else ''
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}</title>
  <link rel="stylesheet" href="/static/mt/common/mtweb.css">
</head>
<body class="mtweb-info" data-kind="{kind}" data-app="{app_name or ''}">
  <main class="mtweb-card">
    {f'<img src="{icon}" alt="" width="72" height="72">' if icon else ''}
    <h1>{name}</h1>
    <p data-t="{kind}">{fallback}</p>
    <div class="mtweb-actions">
      <a class="mtweb-btn primary" href="{config.DOWNLOAD_URL}" data-t="download">Download the desktop version</a>
      <a class="mtweb-btn" href="{config.ALL_APPS_URL}" data-t="allApps">All apps</a>
    </div>
  </main>
  <script src="/web/config.js?app={app_name or ''}"></script>
  <script src="/static/mt/common/mtweb.js"></script>
</body>
</html>
"""


def _mount(path, directory):
    app.mount(path, StaticFiles(directory=str(directory)), name=path.strip('/').replace('/', '_'))


_mount('/web/common', config.MT_STATIC / 'common')
for _a in config.APPS:
    _mount(f'/web/{_a}', config.MT_STATIC / _a)
_mount('/static/mt', config.MT_STATIC)
