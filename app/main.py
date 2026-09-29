import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config, db, document_ocr, files, flight_analysis, printer_driver, production, sysstat
from .routers import (admin, auth_routes, companies, crm, documents, planner, field, flightlogs, orders, printers, products,
                      announcements, calls, cameras, chat, production_errors, reports, secretariat, security, signatures, system, users, warehouse)


@asynccontextmanager
async def lifespan(app):
    db.init()
    with db.connect() as conn:   # kataloğa sonradan eklenen parçalar (ör. elektronik kat) mevcut siparişlere
        production.sync_catalog_parts(conn)
    auth.seed_admin()
    printer_driver.start_poller()
    sysstat.start()
    flight_analysis.resume_pending()
    document_ocr.resume_pending()
    yield


app = FastAPI(title='Fabrika Yönetim Sistemi', lifespan=lifespan)
for r in (admin.router, auth_routes.router, users.router, orders.router, warehouse.router, field.router, flightlogs.router,
          printers.router, products.router, companies.router, documents.router, signatures.router,
          crm.router, planner.router, production_errors.router, secretariat.router, secretariat.me_router, calls.router, calls.me_router, calls.any_router, chat.router, security.router,
          cameras.router, cameras.faces_router, reports.router, announcements.router, system.router, files.router):
    app.include_router(r)

app.mount('/static', StaticFiles(directory=config.STATIC_DIR), name='static')


@app.middleware('http')
async def brand_files(request, call_next):
    """Firma markası: logo (static/img) ve uygulama simgeleri (static/icons) firmanın brand klasöründe varsa oradan."""
    path = request.url.path
    if config.BRAND_DIR and path.startswith(('/static/img/', '/static/icons/')):
        target = (config.BRAND_DIR / path[len('/static/'):]).resolve()
        if config.BRAND_DIR.resolve() in target.parents and target.is_file():
            return FileResponse(target, headers={'Cache-Control': 'no-cache'})
    return await call_next(request)


@app.middleware('http')
async def revalidate_static(request, call_next):
    """Arayüz dosyaları her açılışta sunucuya sorulsun (değişmediyse 304 döner): güncelleme yapıldığında
    tarayıcı ya da Cloudflare eski JS/CSS'i saatlerce göstermesin."""
    response = await call_next(request)
    if request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache'
    return response


@app.get('/manifest.webmanifest')
def manifest():
    return FileResponse(config.STATIC_DIR / 'manifest.webmanifest', media_type='application/manifest+json')


@app.get('/sw.js')
def service_worker():
    # Kök kapsamlı olması için /sw.js'den sunulur; güncellemeler hemen alınsın diye önbelleğe alınmaz
    return FileResponse(config.STATIC_DIR / 'sw.js', media_type='text/javascript',
                        headers={'Cache-Control': 'no-cache', 'Service-Worker-Allowed': '/'})


# ---------- Sürümlü arayüz dosyaları
# index.html, JS/CSS'i /sv/<sürüm>/... adresinden yükler. Sürüm, arayüz dosyalarının değişiklik zamanlarından
# türetilir; dosya değişince adres de değişir, böylece tarayıcı ve Cloudflare önbelleği eski sürümü gösteremez.
# JS içindeki göreli import'lar da aynı sürümlü adres altında çözülür.
ASSET_DIRS = ('js', 'css', 'vendor')


def asset_version():
    h = hashlib.md5()
    for d in ASSET_DIRS:
        for f in sorted((config.STATIC_DIR / d).rglob('*')):
            if f.is_file():
                st = f.stat()
                h.update(f'{f}:{st.st_mtime_ns}:{st.st_size}'.encode())
    return h.hexdigest()[:10]


@app.get('/sv/{ver}/{path:path}')
def versioned_asset(ver: str, path: str):
    target = (config.STATIC_DIR / path).resolve()
    if not target.is_file() or config.STATIC_DIR.resolve() not in target.parents or path.split('/')[0] not in ASSET_DIRS:
        raise HTTPException(404, 'Dosya bulunamadı')
    # Doğru sürümse uzun süre önbelleğe alınabilir; eski sürüm adresi istenirse güncel dosya verilir ama saklanmaz
    cache = 'public, max-age=31536000, immutable' if ver == asset_version() else 'no-cache'
    return FileResponse(target, headers={'Cache-Control': cache})


@app.get('/')
def index():
    html = (config.STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    ver = asset_version()
    for d in ASSET_DIRS:
        html = html.replace(f'"/static/{d}/', f'"/sv/{ver}/{d}/')
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})
