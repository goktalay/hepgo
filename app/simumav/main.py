"""SIMUMAV ASGI uygulaması (docs/simumav.md §1–§2, §7 başlıklar/CSP).

Yollar: `/api/*` router'lar; `/ws/fly/{sim_id}` (+ HEPGO `/ws/drone/sim/{id}`, `/ws/drone/live`); statik:
  `/`            → static/simumav/site (tanıtım; index.html)      `/app` → static/simumav/app (oyun kabuğu; index.html)
  `/brand`       → static/simumav/brand                            `/vendor`, `/static/vendor` → static/vendor (three.js, xterm …)
  `/static/models` → static/models (dahili GLB)                    `/sim` → static/js/modules (HEPGO simülatör ön yüz modülleri)
  `/sim/api.js`, `/api.js` → static/simumav/app/simapi.js          `/<ad>.js` (ui.js, i18n.js, icons.js, …) → static/js/<ad>.js (modüllerin ../ içe aktarımları)
Güvenlik başlıkları her yanıtta; CSP inline script'siz; hata yanıtları iç ayrıntı sızdırmaz (500 → genel mesaj, ayrıntı günlüğe).
"""
import logging
import re
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config  # noqa: F401 — ilk: çekirdek yollarını yönlendirir
from . import bridge, db
from .routers import crew, fly, hangar, meta, missions, ops, session, settings, tracks

log = logging.getLogger('simumav')
CSP = ("default-src 'self'; script-src 'self' https://maps.googleapis.com https://*.cesium.com; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self' https://mastertool.download https://maps.googleapis.com https://*.googleapis.com https://*.cesium.com "
       "https://*.arcgisonline.com https://*.amazonaws.com https://tile.googleapis.com wss://simumav.com wss://www.simumav.com ws://127.0.0.1:8600 ws://localhost:8600; "
       "img-src 'self' data: blob: https:; media-src 'self' blob: data:; font-src 'self' data:; worker-src 'self' blob:; frame-ancestors 'none'; object-src 'none'; "
       "base-uri 'self'; form-action 'self'")
HEADERS = {'Content-Security-Policy': CSP, 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin',
           'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), fullscreen=(self), gamepad=(self), display-capture=(self)',
           'X-Frame-Options': 'DENY', 'Cross-Origin-Opener-Policy': 'same-origin'}
JS_KOK = re.compile(r'^(ui|i18n|icons|segicons|fa-icons|imgopt|step3d|gcode3d|engine3d)\.js$')


@asynccontextmanager
async def lifespan(app):
    db.init()
    bridge.cekirdek_baslat()
    log.info('SIMUMAV %s · veri %s · SITL %s · dev login %s', config.VERSION, config.DATA_DIR, 'açık' if config.SITL_ENABLED else 'SAHTE', config.DEV_LOGIN)
    yield
    await bridge.hepsini_kapat()


app = FastAPI(title='SIMUMAV', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware('http')
async def _guvenlik(request: Request, call_next):
    resp = await call_next(request)
    for k, v in HEADERS.items():
        resp.headers.setdefault(k, v)
    if request.url.path.startswith('/api/'):
        resp.headers.setdefault('Cache-Control', 'no-store')
    return resp


@app.exception_handler(HTTPException)
async def _http(request, e: HTTPException):
    d = e.detail if isinstance(e.detail, dict) and 'error' in e.detail else {'error': 'error' if e.status_code < 500 else 'server_error', 'message': str(e.detail or 'Hata')}
    return JSONResponse({'detail': d}, status_code=e.status_code, headers=dict(e.headers or {}))


@app.exception_handler(RequestValidationError)
async def _val(request, e):
    alanlar = sorted({str(x['loc'][-1]) for x in e.errors() if x.get('loc')})[:10]
    return JSONResponse({'detail': {'error': 'invalid', 'message': 'Eksik ya da hatalı alan: ' + ', '.join(alanlar) if alanlar else 'İstek gövdesi geçersiz', 'fields': alanlar}},
                        status_code=422)


@app.exception_handler(Exception)
async def _genel(request, e):
    log.error('İç hata %s %s: %s', request.method, request.url.path, ''.join(traceback.format_exception(e))[-2000:])
    return JSONResponse({'detail': {'error': 'server_error', 'message': 'Sunucu hatası; lütfen tekrar deneyin'}}, status_code=500, headers=HEADERS)


for r in (session.router, settings.router, hangar.router, crew.router, tracks.router, missions.router, fly.router, fly.compat, ops.router, meta.router, fly.ws_router):
    app.include_router(r)


def _js(path):
    return FileResponse(path, media_type='text/javascript; charset=utf-8', headers={'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff'})


@app.get('/sim/api.js')
@app.get('/static/js/api.js')
@app.get('/api.js')
def simapi():
    """HEPGO modüllerinin `../api.js` / `./api.js` içe aktarımı → SIMUMAV API sarmalayıcısı."""
    return _js(config.SM_STATIC / 'app' / 'simapi.js')


@app.get('/{name}.js')
def kok_js(name: str):
    """Modüllerin kök seviye bağımlılıkları (ui.js, i18n.js, step3d.js …) — yalnız beyaz liste."""
    f = f'{name}.js'
    p = config.STATIC_DIR / 'js' / f
    if not JS_KOK.match(f) or not p.is_file():
        return JSONResponse({'detail': {'error': 'not_found', 'message': 'Bulunamadı'}}, status_code=404)
    return _js(p)


@app.get('/healthz')
def healthz():
    return {'ok': True, 'version': config.VERSION}


def _mount(path, directory, html=False):
    directory.mkdir(parents=True, exist_ok=True)
    app.mount(path, StaticFiles(directory=str(directory), html=html), name=path.strip('/') or 'site')


_mount('/static/vendor', config.STATIC_DIR / 'vendor')
_mount('/static/models', config.STATIC_DIR / 'models')
_mount('/vendor', config.STATIC_DIR / 'vendor')
_mount('/sim', config.STATIC_DIR / 'js' / 'modules')
_mount('/brand', config.SM_STATIC / 'brand')
_mount('/app', config.SM_STATIC / 'app', html=True)
_mount('/', config.SM_STATIC / 'site', html=True)


@app.head('/')
def head_root():
    return Response(status_code=200)
