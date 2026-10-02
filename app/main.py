import hashlib
from contextlib import asynccontextmanager

import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import agent_hub, auth, config, db, document_ocr, files, flight_analysis, printer_driver, production, push, sync, sysstat
from .routers import (admin, assistant, auth_routes, belge, cleaning, companies, console, crm, design, documents, hr, master, meet, mikro, radio, mrp, netscan, purchasing, sales, voice, planner, field, flightlogs, orders, printers, products,
                      announcements, calls, cameras, chat, mail, meeting_room, meetings, production_errors, reports, secretariat, security, signatures, system, users, warehouse)


@asynccontextmanager
async def lifespan(app):
    db.init()
    from . import integrations
    with db.connect() as conn:   # Program Ayarları › Entegrasyonlar: panelden girilen anahtar / bağlantı bilgileri
        integrations.apply(conn)
    with db.connect() as conn:   # kataloğa sonradan eklenen parçalar (ör. elektronik kat) mevcut siparişlere
        production.sync_catalog_parts(conn)
    auth.seed_admin()
    printer_driver.start_poller()
    sysstat.start()
    flight_analysis.resume_pending()
    document_ocr.resume_pending()
    from . import mail_import
    mail_import.start()   # mail ekleri → Evrak Yönetimi
    from . import meeting_audio
    meeting_audio.resume_pending()   # yarım kalan toplantı ses işlemleri
    from . import voice_audio
    voice_audio.resume_pending()   # yarım kalan görüşme ses işlemleri
    from . import meet_audio
    meet_audio.resume_pending()    # yarım kalan online toplantı ses işlemleri
    import asyncio
    from . import agent_hub
    agent_hub.set_loop(asyncio.get_running_loop())   # dağıtık mod: senkron cihaz kodundan ajana köprü
    from . import watchdog
    watchdog.start()   # olay döngüsü donarsa yığın izini kaydeder
    from .routers import meet as meet_router
    asyncio.get_running_loop().create_task(push.notify_loop())   # arka plan bildirimleri (Web Push)
    asyncio.get_running_loop().create_task(sync.loop())   # entegrasyon otomatik senkronizasyonu (Mikro / PDKS)
    asyncio.get_running_loop().create_task(meet_router.end_stale_on_startup())   # yeniden başlamada asılı kalan 'canlı' toplantılar
    yield


app = FastAPI(title='Fabrika Yönetim Sistemi', lifespan=lifespan)


class _AssetGZip:
    """Yalnızca arayüz dosyalarını (/sv/… JS/CSS) ve uygulama sayfasını gzip'ler (mobilde açılış hızı).
    Ses / video / dosya indirmeleri sıkıştırılmaz: Range (ileri sarma) istekleri bozulmasın."""
    def __init__(self, app):
        self.app = app
        self.gz = GZipMiddleware(app, minimum_size=1024, compresslevel=5)   # 9 yerine 5: neredeyse aynı boyut, çok daha az işlemci

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '') if scope['type'] == 'http' else ''
        if path.startswith('/sv/') or path in ('/', '/app', '/app/') or path.startswith('/m/'):
            return await self.gz(scope, receive, send)
        return await self.app(scope, receive, send)


app.add_middleware(_AssetGZip)
for r in (admin.router, auth_routes.router, users.router, orders.router, warehouse.router, field.router, flightlogs.router,
          printers.router, products.router, companies.router, documents.router, belge.router, signatures.router,
          crm.router, planner.router, production_errors.router, secretariat.router, secretariat.me_router, calls.router, calls.me_router, calls.any_router, chat.router, mail.router, meeting_room.router, meetings.router, hr.router, hr.me_router, hr.docs_router, master.router, mikro.router, mrp.router, netscan.router, purchasing.router, sales.router, voice.router, voice.ws_router, security.router,
          cameras.router, cameras.faces_router, reports.router, announcements.router, system.router, assistant.router, meet.router, meet.ws_router, radio.router, radio.ws_router, cleaning.router, design.router, console.ws_router, agent_hub.ws_router, files.router):
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


_IMPORT_RE = re.compile(r'''^\s*(?:import|export)\s+(?:[^'";]*?\s+from\s+)?['"](\.{1,2}/[^'"]+\.js)['"]''', re.M)
_preload_cache = {}


def _module_graph(ver):
    """app.js'nin statik import ağacındaki tüm modüller. index.html'e modulepreload olarak eklenir: tarayıcı
    ~70 modülü zincirleme keşfetmek (her seviye bir gidiş-dönüş) yerine hepsini baştan paralel indirir."""
    if ver in _preload_cache:
        return _preload_cache[ver]
    root = config.STATIC_DIR / 'js'
    seen, stack = [], [root / 'app.js']
    while stack:
        f = stack.pop()
        if f in seen or not f.is_file():
            continue
        seen.append(f)
        for rel in _IMPORT_RE.findall(f.read_text(encoding='utf-8', errors='ignore')):
            stack.append((f.parent / rel).resolve())
    out = [p.relative_to(config.STATIC_DIR.resolve()).as_posix() for p in (x.resolve() for x in seen)]
    _preload_cache.clear()
    _preload_cache[ver] = out
    return out


_splash_cache = {}


def _splash_logo():
    """Açılış ekranı logosu: firmanın logosundan küçültülmüş WebP, sayfaya gömülü (data URI) → ağ beklemeden ilk anda görünür."""
    src = config.STATIC_DIR / 'img' / 'logo.png'
    if config.BRAND_DIR and (config.BRAND_DIR / 'img' / 'logo.png').is_file():
        src = config.BRAND_DIR / 'img' / 'logo.png'
    key = (str(src), src.stat().st_mtime_ns)
    if key not in _splash_cache:
        import base64
        import io
        from PIL import Image
        im = Image.open(src)
        if im.width > 360:
            im = im.resize((360, round(im.height * 360 / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, 'WEBP', quality=80, method=6)
        _splash_cache.clear()
        _splash_cache[key] = 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()
    return _splash_cache[key]


def _spa():
    html = (config.STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    try:
        html = html.replace('class="sp-logo" src="/static/img/logo.png"', f'class="sp-logo" src="{_splash_logo()}"')
    except Exception:   # noqa: BLE001 — logo işlenemezse normal adresten yüklenir
        pass
    ver = asset_version()
    links = '\n'.join(f'<link rel="modulepreload" href="/sv/{ver}/{p}">' for p in _module_graph(ver))
    html = html.replace('<!--MODULEPRELOAD-->', links)
    for d in ASSET_DIRS:
        html = html.replace(f'"/static/{d}/', f'"/sv/{ver}/{d}/')
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})


@app.get('/')
def index():
    """Kök adres doğrudan uygulamaya (Gökkubbe/firma girişi) yönlenir. Ürün tanıtımı artık veilox.app'te."""
    return RedirectResponse('/app', status_code=307)


@app.get('/app')
@app.get('/app/')
def app_shell():
    return _spa()


@app.get('/m/{code}')
def meeting_join_page(code: str):
    """Dış katılımcı toplantı giriş sayfası: aynı uygulama kabuğu; app.js guest moduna geçer."""
    return _spa()
