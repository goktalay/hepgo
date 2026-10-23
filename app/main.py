import hashlib
import html as htmlmod
import os
import secrets
from contextlib import asynccontextmanager

import re
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import agent_hub, auth, config, db, document_ocr, files, flight_analysis, integration_health, kvkk, mail_cache, printer_driver, production, push, sync, sysstat
from .routers import directory, feed, federation, screenshare, finance, central, sshmaster_admin, membership, live as live_router, certs as certs_router, fleet as fleet_router, boss as boss_router, roles as roles_router, projects as projects_router, social as social_router, contacts as contacts_router, support as support_router, spotify as spotify_router, search as search_router
from .routers import (admin, assistant, auth_routes, belge, cleaning, companies, console, crm, design, documents, hr, master, meet, mikro, radio, mrp, netscan, purchasing, sales, voice, planner, field, flightlogs, orders, printers, products,
                      announcements, calls, cameras, chat, mail, meeting_room, meetings, production_errors, reports, secretariat, security, signatures, notes, filemanager, ssh_hosts, system, users, warehouse, factory, mobile, worktime as worktime_router, kvkk as kvkk_router, usertasks, todos, ui_updates as ui_updates_router, surveys, pos, sections, services, reservations, waiter, beta)


@asynccontextmanager
async def lifespan(app):
    db.init()
    from . import ui_updates
    with db.connect() as conn:   # ekran bazlı sürüm takibi: arayüz dosyaları değiştiyse yeni sürüm kaydı (etkilenen ekranlarla)
        try:
            ui_updates.ensure_release(conn, asset_version())
        except Exception as e:   # noqa: BLE001 — takip başlangıcı uygulamayı durdurmasın
            print('[ui_updates] tarama hatası:', e)
    from . import integrations
    with db.connect() as conn:   # Program Ayarları › Entegrasyonlar: panelden girilen anahtar / bağlantı bilgileri
        integrations.apply(conn)
    with db.connect() as conn:   # kataloğa sonradan eklenen parçalar (ör. elektronik kat) mevcut siparişlere
        production.sync_catalog_parts(conn)
    from . import cfd
    cfd.recover_on_start()   # yarım kalan CFD koşuları 'failed', kuyruktakiler sürer
    from . import semis
    with db.connect() as conn:   # CAYMAZ V3 / V4: V2 olan firmada ürün ağaçları + yeni parçaların G-code'u (bir kez; idempotent)
        try:
            semis.ensure_versions(conn)
        except Exception as e:   # noqa: BLE001
            print('[semis] sürüm kurulumu hatası:', e)
    auth.seed_admin()
    from . import rbac
    with db.connect() as conn:   # Rol Yönetimi: koddaki roller / varsayılan modül izinleri (bir kez) veritabanına
        rbac.sync(conn)
    printer_driver.start_poller()
    sysstat.start()
    flight_analysis.resume_pending()
    document_ocr.resume_pending()
    from . import mail_import
    mail_import.start()   # mail ekleri → Evrak Yönetimi
    mail_cache.start()    # mail önbelleği: gelen kutusu + gönderilenler başlıkları (CRM › firma › Mailler)
    from . import social
    social.start()   # kişisel sosyal medya akışları (RSS / YouTube / Bluesky / Mastodon)
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
    integration_health.start()   # entegrasyonlar düzenli denenir; çevrimdışıysa sistem yöneticisine bildirim
    kvkk.start()                 # KVKK saklama süresi temizliği (günlük): eski görülme/ses/audit kayıtları silinir
    watchdog.start()   # olay döngüsü donarsa yığın izini kaydeder
    from .routers import meet as meet_router
    asyncio.get_running_loop().create_task(push.notify_loop())   # arka plan bildirimleri (Web Push)
    asyncio.get_running_loop().create_task(sync.loop())   # entegrasyon otomatik senkronizasyonu (Mikro / PDKS)
    asyncio.get_running_loop().create_task(meet_router.end_stale_on_startup())   # yeniden başlamada asılı kalan 'canlı' toplantılar
    asyncio.get_running_loop().create_task(live_router.start_reaper())   # yarım kalan canlı yayınlar (yayıncı dönmezse kapanır)
    from . import drone_hub
    drone_hub.start()   # Dron Yönetimi: önceki süreçten açık kalan köprü oturumları KESILDI; bakım döngüsü
    yield
    from . import flightsim, flightsim_match
    await flightsim_match.MANAGER.kapat_hepsi()   # §33 çok oyunculu karşılaşmalar (bitmemişler IPTAL; oyuncu oturumları kapanır)
    await flightsim.MANAGER.kapat_hepsi()   # Uçuş Simülatörü: açık oturumlar (SITL süreçleri, UDP portları) kapanır


app = FastAPI(title='HEPGO ERP', lifespan=lifespan)


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


class _WsOriginGuard:
    """WebSocket'lerde siteler arası ele geçirmeye (CSWSH) karşı: tarayıcı Origin gönderir; Origin, bağlanılan adresle
    (Host) ya da tanımlı adreslerle (CAYMAZ_PUBLIC_URL, CAYMAZ_LOCAL_URL, CAYMAZ_WS_ORIGINS) eşleşmiyorsa el sıkışma
    reddedilir. Firmalar aynı üst alan adını paylaştığından (SameSite çerez) başka firmanın sayfası bağlanamaz.
    Origin göndermeyen tarayıcı dışı istemciler (fabrika ajanı) etkilenmez; onlar kendi anahtarıyla doğrulanır."""
    def __init__(self, app):
        self.app = app

    @staticmethod
    def _allowed(scope):
        h = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope.get('headers') or []}
        origin = h.get('origin')
        if origin is None:
            return True
        host = urlsplit(origin).netloc.lower()
        extra = {urlsplit(u.strip()).netloc.lower() for u in
                 (config.PUBLIC_URL, config.LOCAL_URL, *os.environ.get('CAYMAZ_WS_ORIGINS', '').split(',')) if u.strip()}
        return bool(host) and (host == h.get('host', '').lower() or host in extra)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket' and not self._allowed(scope):
            await receive()   # websocket.connect
            return await send({'type': 'websocket.close', 'code': 4403})   # kabul edilmeden → HTTP 403
        return await self.app(scope, receive, send)


app.add_middleware(_WsOriginGuard)


# Transfer İzleme (MASTER panosu): GET /api/files/* indirmelerini KABA biçimde izler. FileResponse gövdesine
# DOKUNULMAZ (Range/sendfile ve video ileri-sarma korunur); yalnızca ASGI send olayları gözlenir: yanıt
# başlarken kayıt açılır (boyut = Content-Length), gövde bitince tamamlanır. Küçültülmüş resim (?w=) istekleri
# gürültü yapmasın diye izlenmez. Kullanıcı adı oturum çerezinden en iyi çabayla (kısa önbellekli) çözülür.
_dl_user_cache = {}   # token -> (monotonic, ad)


def _down_user(scope):
    try:
        raw = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope.get('headers') or []}.get('cookie')
        if not raw:
            return '—'
        from http.cookies import SimpleCookie
        ck = SimpleCookie()
        ck.load(raw)
        m = ck.get(auth.COOKIE)
        token = m.value if m else None
        if not token:
            return '—'
        import time as _t
        now = _t.monotonic()
        hit = _dl_user_cache.get(token)
        if hit and now - hit[0] < 60:
            return hit[1]
        with db.connect() as conn:
            u = auth.user_by_token(conn, token)
        name = (u['full_name'] if u else None) or '—'
        if len(_dl_user_cache) > 500:
            _dl_user_cache.clear()
        _dl_user_cache[token] = (now, name)
        return name
    except Exception:   # noqa: BLE001 — izleme hiçbir koşulda indirmeyi bozmamalı
        return '—'


class _DownloadTracker:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '') if scope['type'] == 'http' else ''
        if (scope.get('method') != 'GET' or not path.startswith('/api/files/')
                or b'w=' in scope.get('query_string', b'')):   # küçük resim (thumbnail) istekleri izlenmez
            return await self.app(scope, receive, send)
        from . import transfers
        state = {'tid': None}
        name = path.rsplit('/', 1)[-1]

        async def send_wrap(event):
            et = event['type']
            if et == 'http.response.start':
                if 200 <= event['status'] < 300:
                    headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in event.get('headers') or []}
                    try:
                        size = int(headers.get('content-length') or 0)
                    except ValueError:
                        size = 0
                    state['tid'] = transfers.register('down', None, _down_user(scope), name, size, cancelable=False)
            elif et == 'http.response.body' and not event.get('more_body', False) and state['tid']:
                transfers.finish(state['tid'])
            await send(event)

        try:
            return await self.app(scope, receive, send_wrap)
        except BaseException:
            if state['tid']:
                transfers.finish(state['tid'])
            raise


app.add_middleware(_DownloadTracker)
from . import drone_hub  # noqa: E402 — Dron Yönetimi: köprü + canlı uçuş WebSocket'leri
from .routers import drone as drone_router  # noqa: E402
from .routers import flightsim as flightsim_router  # noqa: E402 — Uçuş Simülatörü (SITL + Mission Planner köprüsü)
from .routers import caysim as caysim_router  # noqa: E402 — CAYSIM masaüstü istemci API'si (docs/caysim-api.md)
from .routers import faceauth as faceauth_router  # noqa: E402 — Yüz ile giriş (docs/yuz-tanima.md)
from .routers import tools_convert, tools_ftp, tools_mt, tools_notepad, tools_sql, tools_ssh, tools_volfai  # noqa: E402 — Araçlar › Master Tool web sürümleri
for r in (admin.router, auth_routes.router, faceauth_router.router, users.router, orders.router, warehouse.router, field.router, flightlogs.router, drone_router.router, drone_hub.ws_router,
          flightsim_router.router, flightsim_router.ws_router, caysim_router.router, caysim_router.admin_router, caysim_router.ws_router,
          printers.router, products.router, companies.router, documents.router, belge.router, signatures.router,
          crm.router, planner.router, production_errors.router, secretariat.router, secretariat.me_router, calls.router, calls.me_router, calls.any_router, chat.router, mail.router, meeting_room.router, meetings.router, hr.router, hr.me_router, hr.duties_me_router, hr.duties_router, hr.docs_router, master.router, mikro.router, mrp.router, netscan.router, purchasing.router, sales.router, voice.router, voice.ws_router, security.router,
          cameras.router, cameras.faces_router, reports.router, announcements.router, system.router, assistant.router, meet.router, meet.ws_router, radio.router, radio.ws_router, cleaning.router, usertasks.router, todos.router, ui_updates_router.router, surveys.router, pos.router, sections.router, services.router, reservations.router, waiter.router, beta.router, design.router, console.ws_router, ssh_hosts.router, ssh_hosts.ws_router, notes.router, filemanager.router, filemanager.public, agent_hub.ws_router, files.router, directory.router, feed.router, federation.router, screenshare.router, screenshare.ws_router, finance.router, live_router.router, live_router.ws_router, certs_router.router, fleet_router.router, boss_router.router, roles_router.router, projects_router.router, social_router.router, contacts_router.router, spotify_router.router,
          tools_mt.router, tools_ssh.router, tools_ssh.ws_router, tools_ftp.router, tools_ftp.ws_router, tools_sql.router, tools_notepad.router, tools_convert.router, tools_volfai.router,
          central.router, central.fed_router, sshmaster_admin.router, sshmaster_admin.fed, support_router.router, support_router.fed, membership.router, factory.router, mobile.router, worktime_router.router, kvkk_router.router, search_router.router):
    app.include_router(r)
from .routers import flightsim_presets as flightsim_presets_router  # noqa: E402 — Uçuş Simülatörü §27 Kayıtlı Simülasyonlar
app.include_router(flightsim_presets_router.router)
from .routers import flightsim_match as flightsim_match_router  # noqa: E402 — Uçuş Simülatörü §33 çok oyunculu karşılaşma
app.include_router(flightsim_match_router.router)
app.include_router(flightsim_match_router.ws_router)
app.include_router(flightsim_match_router.fpv_router)   # §47 hazır FPV parkurları (katalog, skor, hayalet)
from .routers import holiday as holiday_router  # noqa: E402 — Bayram temaları (docs/bayram-temalari.md; SIMUMAV ile ortak app/holiday_themes.py)
app.include_router(holiday_router.router)

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


# --- Güvenlik başlıkları ---------------------------------------------------
# Satır içi iki CSS-önyükleme onload işleyicisinin CSP karması (index.html'deki rel-swap).
_CSP_HASHES = ("'sha256-1jAmyYXcRq6zFldLe/GCgIDJBiOONdXjTLgEFMDnDSM=' "
               "'sha256-mVP3PTvMv9AYGWNbDo0gms1jqWyGhlU/Iog4lTy7y2I='")
# Her yanıtta uygulanan güvenli taban: çerçeveleme (clickjacking), object ve base-uri sınırlanır;
# script/style/img KISITLANMAZ (yardımcı sayfalar — ekran paylaşımı, yasal — kırılmasın). Ana uygulama (_spa)
# kendi tam/nonce'lu CSP'sini set eder; dosya/mail sandbox yanıtları kendi katı CSP'sini korur.
_SAFE_CSP = "frame-ancestors 'self'; object-src 'none'; base-uri 'self'"


def _is_https(request):
    xf = (request.headers.get('x-forwarded-proto') or '').lower()
    if xf:
        return 'https' in xf
    cf = (request.headers.get('cf-visitor') or '')
    if '"scheme":"https"' in cf.replace(' ', ''):
        return True
    return request.url.scheme == 'https'


def _app_csp(nonce):
    """Ana uygulama (kimlik doğrulamalı arayüz) için katı CSP. Satır içi script yalnız nonce/karma ile çalışır
    (enjekte edilen script engellenir). Google Haritalar (caymaz'da anahtar var) ve Google Fonts'a izin verilir;
    img/connect/media https: ile pragmatik (harita döşemeleri, avatar, radyo akışı, hava durumu, OAuth)."""
    return ("default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; frame-ancestors 'self'; "
            f"script-src 'self' 'nonce-{nonce}' 'unsafe-eval' 'unsafe-hashes' {_CSP_HASHES} "
            "https://maps.googleapis.com https://maps.gstatic.com https://cdn.jsdelivr.net; "   # jsdelivr: Cesium (3B uçuş izleme)
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob: https:; font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "connect-src 'self' https: wss: blob:; media-src 'self' blob: data: https:; "   # blob: GLTFLoader (ImageBitmapLoader) glb içi dokuları fetch(blob:) ile okur (Google 3D Tiles, Uçuş Simülatörü §10)
            "worker-src 'self' blob: https://cdn.jsdelivr.net; child-src 'self' blob: data:; frame-src 'self' blob: data:;")


@app.middleware('http')
async def security_headers(request, call_next):
    """Tüm yanıtlara güvenlik başlıkları: MIME-sniff kapalı, referrer sızıntısı sınırlı, aynı-köken çerçeveleme
    (native offline iframe'i için SAMEORIGIN), HTTPS'te HSTS, kullanılmayan güçlü özellikler kapalı. CSP tabanı
    setdefault ile — yanıt kendi CSP'sini vermişse (ana uygulama / sandbox) dokunulmaz."""
    response = await call_next(request)
    h = response.headers
    h.setdefault('X-Content-Type-Options', 'nosniff')
    h.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    h.setdefault('X-Frame-Options', 'SAMEORIGIN')
    # camera/microphone=(self): yüz ile giriş, görüşme, sesle yazdırma yalnız kendi kökenimizde (gömülü üçüncü taraf çerçeve alamaz)
    h.setdefault('Permissions-Policy', 'payment=(), usb=(), serial=(), bluetooth=(), hid=(), midi=(), camera=(self), microphone=(self)')
    if _is_https(request):
        h.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    h.setdefault('Content-Security-Policy', _SAFE_CSP)
    return response


@app.get('/manifest.webmanifest')
def manifest():
    # Beyaz etikette uygulama adı firmanın adı olur (HEPGO görünmez); ikonlar BRAND_DIR'den gelir (ayrı middleware).
    if config.WHITE_LABEL:
        import json as _json
        data = _json.loads((config.STATIC_DIR / 'manifest.webmanifest').read_text(encoding='utf-8'))
        name = config.COMPANY_NAME or data.get('name')
        data['name'] = name
        data['short_name'] = (name or '')[:12]
        return Response(_json.dumps(data, ensure_ascii=False), media_type='application/manifest+json')
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
    src = config.STATIC_DIR / 'img' / 'hepgo-logo.png'
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


def _brand_head(html, request, page_title=None, description=None):
    """Bağlantı önizlemesi (WhatsApp, iMessage, Slack…) ve uygulama adları: beyaz etikette yalnızca firmanın adı (HEPGO
    görünmez). Tarayıcılar JS çalıştırmadığı için başlık / Open Graph etiketleri sunucuda firmaya göre yazılır."""
    import html as _h
    wl = config.WHITE_LABEL
    company = (config.COMPANY_NAME or '').strip()
    brand = company if (wl and company) else 'HEPGO ERP'
    title = f'{page_title} · {brand}' if page_title else brand
    desc = description or (f'{company} yönetim sistemi' if wl and company else 'Fabrikanızı tek platformdan yönetin.')
    host = request.headers.get('x-forwarded-host') or request.headers.get('host') or ''
    local = host.startswith(('127.', 'localhost', '192.168.', '10.')) or not host
    base = (os.environ.get('CAYMAZ_PUBLIC_URL') or (f"{'http' if local else 'https'}://{host}" if host else '')).rstrip('/')
    e = lambda v: _h.escape(v, quote=True)
    html = re.sub(r'<title>[^<]*</title>', f'<title>{e(title)}</title>', html, count=1)
    html = html.replace('<meta name="apple-mobile-web-app-title" content="HEPGO">', f'<meta name="apple-mobile-web-app-title" content="{e(brand[:30])}">')
    html = html.replace('<meta name="application-name" content="HEPGO ERP">', f'<meta name="application-name" content="{e(brand)}">')
    og = (f'<meta name="description" content="{e(desc)}">\n'
          f'<meta property="og:type" content="website">\n<meta property="og:site_name" content="{e(brand)}">\n'
          f'<meta property="og:title" content="{e(title)}">\n<meta property="og:description" content="{e(desc)}">\n'
          + (f'<meta property="og:url" content="{e(base + request.url.path)}">\n'
             f'<meta property="og:image" content="{e(base)}/api/system/brand/og.png">\n'   # firma logosu (PNG, kare) — WhatsApp/iMessage SVG göstermez
             f'<meta property="og:image:type" content="image/png">\n<meta property="og:image:width" content="640">\n<meta property="og:image:height" content="640">\n' if base else '')
          + f'<meta name="twitter:card" content="summary">\n<meta name="twitter:title" content="{e(title)}">\n'
          f'<meta name="twitter:description" content="{e(desc)}">\n')
    return html.replace('</head>', og + '</head>', 1)


def _spa(request, page_title=None, description=None):
    html = (config.STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    try:
        html = html.replace('class="sp-logo" src="/static/img/hepgo-logo.png"', f'class="sp-logo" src="{_splash_logo()}"')
    except Exception:   # noqa: BLE001 — logo işlenemezse normal adresten yüklenir
        pass
    html = _brand_head(html, request, page_title, description)
    ver = asset_version()
    links = '\n'.join(f'<link rel="modulepreload" href="/sv/{ver}/{p}">' for p in _module_graph(ver))
    html = html.replace('<!--MODULEPRELOAD-->', links)
    for d in ASSET_DIRS:
        html = html.replace(f'"/static/{d}/', f'"/sv/{ver}/{d}/')
    # CSP nonce: satır içi script'lere (tema + açılış ekranı) ekle; enjekte edilen script'ler engellenir
    nonce = secrets.token_urlsafe(16)
    html = html.replace('<script>', f'<script nonce="{nonce}">')
    html = html.replace('</head>', f'<script nonce="{nonce}">window.__VER="{ver}";</script>\n</head>', 1)   # açık uygulamada sürüm karşılaştırması
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache', 'Content-Security-Policy': _app_csp(nonce)})


@app.get('/api/version')
def app_version_api():
    """Arayüz sürümü (statik dosya damgası). Açık uygulama bunu yoklar; değişince kendini yeniler."""
    return {'ver': asset_version()}


@app.get('/')
def index():
    """Kök adres doğrudan uygulamaya (Gökkubbe/firma girişi) yönlenir. Ürün tanıtımı artık veilox.app'te."""
    return RedirectResponse('/app', status_code=307)


@app.get('/app')
@app.get('/app/')
def app_shell(request: Request):
    return _spa(request)


@app.get('/m/{code}')
def meeting_join_page(code: str, request: Request):
    """Dış katılımcı toplantı giriş sayfası: aynı uygulama kabuğu; app.js guest moduna geçer.
    Bağlantı önizlemesi (WhatsApp vb.) için başlıkta toplantı adı, açıklamada firma + tarih-saat."""
    title, desc = 'Görüntülü toplantı daveti', 'Toplantıya katılmak için bağlantıya dokunun.'
    try:
        from .routers.meet import when_lines
        with db.connect() as conn:
            m = db.row(conn.execute("SELECT title, scheduled_at, duration_min FROM online_meetings WHERE code = ? AND status != 'BITTI'", (code,)))
        if m:
            title = m['title']
            when = when_lines(m['scheduled_at'], m['duration_min'])
            desc = f"{config.COMPANY_NAME} görüntülü toplantı daveti" + (f" · {when[0]}" if when else '') + ' · Katılmak için bağlantıya dokunun.'
    except Exception:   # noqa: BLE001 — önizleme metni için; sayfa yine açılır
        pass
    return _spa(request, title, desc)


# Herkese açık yasal sayfalar (Google / Microsoft OAuth onay ekranı bunlara bağlantı ister): oturum gerektirmez.
LEGAL_UPDATED = '4 Ekim 2026'
LEGAL_PROVIDER = 'GÖKKUBBE Teknoloji'
LEGAL_EMAIL = os.environ.get('CAYMAZ_LEGAL_EMAIL', 'destek@gokkubbetech.com')


def _legal(request, name):
    host = (request.headers.get('x-forwarded-host') or request.headers.get('host') or '').split(',')[0].strip()
    html = (config.STATIC_DIR / 'legal' / f'{name}.html').read_text(encoding='utf-8')
    for k, v in (('DATE', LEGAL_UPDATED), ('PROVIDER', LEGAL_PROVIDER), ('EMAIL', LEGAL_EMAIL), ('HOST', host or 'HEPGO')):
        html = html.replace('{{' + k + '}}', htmlmod.escape(v))
    return HTMLResponse(html, headers={'Cache-Control': 'public, max-age=3600'})


@app.get('/gizlilik')
@app.get('/privacy')
def privacy_page(request: Request):
    return _legal(request, 'privacy')


@app.get('/kullanim-sartlari')
@app.get('/terms')
def terms_page(request: Request):
    return _legal(request, 'terms')


@app.get('/beta-sozlesmesi')
@app.get('/beta-agreement')
def beta_agreement_page(request: Request):
    return _legal(request, 'beta')


@app.get('/s/{code}')
def screen_view_page(code: str, request: Request):
    """Ekran paylaşımı izleyici sayfası (bağımsız, hafif): rrweb replay + imleç/kontrol + sesli-görüntülü."""
    html = (config.STATIC_DIR / 'screen.html').read_text(encoding='utf-8')
    return HTMLResponse(_brand_head(html, request, 'Ekran paylaşımı', 'Ekranı izlemek ve destek olmak için bağlantıya dokunun.'),
                        headers={'Cache-Control': 'no-cache'})
