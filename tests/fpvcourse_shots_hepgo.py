"""HEPGO Uçuş Simülatörü §47 — HAZIR FPV PARKURLARI görsel doğrulaması (Playwright headless shell + SwiftShader; sahte SITL HEPGO_SITL=0; araç sunucuda
sahte kinematikle parkurun YARIŞ HATTI boyunca uçurulur — `fpv_pilotu`). Görüntüler /tmp/fpvcourse-shots/:
  galeri-yeni-karsilasma.png (Tür ve kurallar: FPV kartı + galeri) · galeri-zaman-denemesi.png (Yeni Simülasyon › Hazır FPV parkurları penceresi) ·
  davet-tek-kisilik.png · <mekan>-fpv.png + <mekan>-takip.png (8 mekan × 2: pilot kamerası / takip kamerası; sıradaki kapı yeşil, sonrakiler pembe/mor,
  kılavuz çizgisi, HUD) · hud-hayalet.png (kişisel rekor hayaleti önde + HUD farkı) · sonuc-tek-kisilik.png (KİŞİSEL REKOR) · karsilasmalar-sekmesi.png.
Ayrıca her mekan için renderer.info (çizim çağrısı / üçgen) ve katman istatistiği yazdırılır.
Çalıştırma: ./.venv/bin/python -m tests.fpvcourse_shots_hepgo [mekan …]   (SHOT_GFX=low|medium|high|ultra, varsayılan high)
"""
import json
import math
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/fpvcourse-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39850', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='3', SIM_MATCH_MAX_SESSIONS='4')
PORT = int(os.environ.get('SHOT_PORT') or 8879)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/fpvcourse-shots')
OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
GFX = os.environ.get('SHOT_GFX') or 'high'

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth, flightsim, flightsim_fpv  # noqa: E402
from app import flightsim_match_core as core  # noqa: E402

core.HAZIRLIK_ZAMAN_ASIMI_S = 900.0
from app.main import app  # noqa: E402

server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=PORT, log_level='error'))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(160):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close(); break
    except OSError:
        time.sleep(0.25)
else:
    sys.exit('sunucu açılmadı')
time.sleep(1)
hatalar = []
MERKEZ = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}


def oturum(kullanici, sifre):
    r = requests.Session()
    assert r.post(f'{BASE}/api/auth/login', json={'username': kullanici, 'password': sifre}).status_code == 200, kullanici
    r.post(f'{BASE}/api/kvkk/accept-terms', json={})
    r.post(f'{BASE}/api/location/consent', json={'granted': False})
    return r


s = oturum('demo@firma.com', 'Demo-Sifre-12')
CEN = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara FPV Sahası', 'lat': MERKEZ['lat'], 'lon': MERKEZ['lon'], 'alt': MERKEZ['alt']}).json()
for u, ad in (('ayse@firma.com', 'Ayşe Pilot'), ('mehmet@firma.com', 'Mehmet Pilot')):
    assert s.post(f'{BASE}/api/users', json={'username': u, 'full_name': ad, 'roles': [auth.PILOT], 'password': 'Ucus-Gizli-77'}).status_code == 200
M_ = f'{BASE}/api/drone/sim/matches'


def shot(pg, ad):
    pg.screenshot(path=str(OUT / ad), timeout=300000)
    print('  kare', ad, flush=True)


def kontrol(ad, kosul):
    print(('  ✓ ' if kosul else '  ✗ ') + ad, flush=True)
    if not kosul:
        hatalar.append(ad)


def bekle(fn, sn=120, adim=0.5):
    t = time.time() + sn
    while time.time() < t:
        v = fn()
        if v:
            return v
        time.sleep(adim)
    return fn()


def mac(mid):
    return s.get(f'{M_}/{mid}').json()


def hat_noktalari(c):
    """Yarış hattı (başlangıç → kapılar → S/F) düz nokta listesi + her kapının giriş noktası sırası."""
    pts, kapi_i = [], {}
    for k, seg in enumerate(c['line']):
        for j, p in enumerate(seg):
            if pts and j == 0:
                continue
            pts.append(tuple(p))
        g = k if k < len(c['gates']) else 0
        kapi_i.setdefault(g if k else 0, len(pts) - 3)   # giriş = parçanın sondan üçüncü noktası (giriş, merkez, çıkış)
    return pts, kapi_i


def fpv_pilotu(oturum_, c, hiz=8.0, tur=1):
    """Sahte kinematiği yarış hattı boyunca (tur kez) uçurur; st['hedef'] nokta sırasına varınca orada askıda kalır (yön sıradaki noktaya)."""
    k = oturum_.sahte
    pts, _ = hat_noktalari(c)
    tur_pts = [tuple(p) for seg in c['line'][1:] for p in seg[1:]]
    pts = pts + tur_pts * (tur - 1)
    bx, by = core.enu(MERKEZ['lat'], MERKEZ['lon'], k.lat0, k.lon0)
    st = {'i': 0, 'p': [bx, by, 0.0], 'hedef': len(pts) - 1, 'hiz': hiz, 'pts': pts, 'yaw': math.radians(c['start']['yaw'])}

    def adim(dt):
        k.sure_ms += dt * 1000
        k.armed, k.mode = True, 'ACRO'
        kalan = st['hiz'] * dt
        dur = st.get('dur')   # (x, y, z, m): kapı merkezine m metre kalınca dur
        while kalan > 0 and st['i'] <= min(st['hedef'], len(pts) - 1):
            if dur and st['i'] > st.get('dur_from', 0) and math.dist(st['p'], dur[:3]) <= dur[3]:
                st['i'] = st['hedef'] + 1; st['durdu'] = True; break
            hx, hy, hz = pts[st['i']]
            dx, dy, dz = hx - st['p'][0], hy - st['p'][1], hz - st['p'][2]
            d = math.sqrt(dx * dx + dy * dy + dz * dz)
            if d > 0.05:
                st['yaw'] = math.atan2(dx, dy) if math.hypot(dx, dy) > 0.2 else st['yaw']
            if d <= kalan:
                st['p'] = [hx, hy, hz]; st['i'] += 1; kalan -= d
            else:
                f = kalan / d
                st['p'] = [st['p'][0] + dx * f, st['p'][1] + dy * f, st['p'][2] + dz * f]; kalan = 0
                k.vn, k.ve = dy / d * st['hiz'], dx / d * st['hiz']
        if st['i'] > st['hedef']:
            k.vn = k.ve = 0.0
            nx = dur[:3] if dur else pts[min(st['i'], len(pts) - 1)]
            if math.hypot(nx[0] - st['p'][0], nx[1] - st['p'][1]) > 0.3:
                st['yaw'] = math.atan2(nx[0] - st['p'][0], nx[1] - st['p'][1])
        lat, lon = core.latlon(MERKEZ['lat'], MERKEZ['lon'], st['p'][0], st['p'][1])
        k.lat, k.lon, k.alt_rel = lat, lon, st['p'][2]
        k.yaw, k.roll, k.pitch = st['yaw'], 0.0, -0.06
    k.adim = adim
    return st


def baglam(b, ses, w=1440, hh=900):
    ctx = b.new_context(viewport={'width': w, 'height': hh}, locale='tr-TR')
    ctx.add_cookies([{'name': auth.COOKIE, 'value': ses.cookies.get(auth.COOKIE), 'url': BASE}])
    ctx.add_init_script(f"try {{ localStorage.setItem('fs.gfx', JSON.stringify({{preset: '{GFX}'}})); localStorage.setItem('fs.cam', 'pilot'); localStorage.setItem('caymaz.fs.rc.on', '0'); localStorage.setItem('fs.cam.pip', JSON.stringify({{on: false}})); }} catch (e) {{}}")
    pg = ctx.new_page()
    pg.set_default_timeout(120000)
    pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
    pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
    return ctx, pg


def yaris_ac(pg, cid, laps=1, rule='continue'):
    r = s.post(M_, json={'settings': {'type': 'multirotor', 'center_id': CEN['id'], 'camera': 'day'}, 'kind': 'fpv',
                         'fpv': {'course_id': cid, 'laps': laps, 'crash_rule': rule, 'time_limit_min': 10}, 'invite': [], 'bots': []})
    assert r.status_code == 201, r.text
    mid = r.json()['id']
    pg.goto(f'{BASE}/#/drone/sim/match/{mid}', wait_until='domcontentloaded')
    pg.wait_for_function("() => /#\\/drone\\/sim\\/\\d+\\?match=/.test(location.hash)", timeout=120000)
    pg.wait_for_function("() => !!(window.__fsFpv && window.__fsFpv.layer)", timeout=600000)
    kontrol(f'{cid}: yarış başladı', bekle(lambda: mac(mid)['state'] == 'YARIS', 600, 0.5))
    d = mac(mid)
    sid = d['players'][0]['session_id']
    return mid, sid


def iptal(mid):
    s.post(f'{M_}/{mid}/cancel')
    time.sleep(1.0)


def kamera(pg, mode):
    pg.evaluate(f"window.__fsMatch?.sim?.setCamera('{mode}')")


# her mekan için durulacak kapı (sıradaki kapı yeşil) — mekânın karakteristik bölümü
DUR = {'hangar': 2, 'forest': 3, 'city': 1, 'stadium': 2, 'refinery': 1, 'canyon': 4, 'woodframe': 1, 'concrete': 4}
MEKANLAR = sys.argv[1:] or list(DUR)


def mekan_karesi(b, cid):
    c = flightsim_fpv.parkur(cid)
    ctx, pg = baglam(b, s)
    t0 = time.time()
    mid, sid = yaris_ac(pg, cid)
    pts, kapi = hat_noktalari(c)
    st = fpv_pilotu(flightsim.MANAGER.get(sid), c, hiz=10.0)
    hedef_kapi = DUR[cid]
    g = c['gates'][hedef_kapi]
    st['hedef'] = max(1, kapi.get(hedef_kapi, 3))   # sıradaki kapının giriş noktasına dek …
    st['dur'] = (g['x'], g['y'], g['z'], 7.5)        # … ama kapı merkezine 7,5 m kalınca durur, yönü kapıya
    st['dur_from'] = kapi.get(hedef_kapi - 1, 0) + 2   # önceki kapı geçildikten sonra
    bekle(lambda: st['i'] > st['hedef'], 120, 0.3)
    hx, hy, _ = st['p']
    try:   # yazılım WebGL'de kare hızı düşük: 3B'deki araç bekleme noktasına varana dek bekle
        pg.wait_for_function(f"() => {{ const p = window.__fsMatch?.sim?.position?.(); return p && Math.hypot(p.x - ({hx}), p.y - ({hy})) < 1.5; }}", timeout=90000)
    except Exception:   # noqa: BLE001
        hatalar.append(f'{cid}: 3B araç bekleme noktasına varmadı')
    kamera(pg, 'pilot'); pg.wait_for_timeout(6000)
    info = pg.evaluate("(() => { const f = window.__fsFpv; const s = window.__fsMatch.sim; return { layer: f.layer.info(), stats: f.layer.stats(), gfx: s.gfxStats ? s.gfxStats() : null, hud: f.hud.state(), g: s.getGraphics ? s.getGraphics().level : null }; })()")
    nexts = [g for g in info['layer']['gates'] if g['state'] == 'next']
    kontrol(f"{cid}: sıradaki kapı yeşil (kapı {nexts[0]['i'] if nexts else '—'}, beklenen {hedef_kapi})", bool(nexts) and nexts[0]['i'] == hedef_kapi)
    print(f"  {cid}: renderer {json.dumps(info['gfx'])} · katman {json.dumps(info['stats'])} · kalite {info['g']} · hud '{info['hud']['bar'][:90]}'", flush=True)
    shot(pg, f'{cid}-fpv.png')
    pg.evaluate("window.__fsMatch?.sim?.setFollowView(5.5, 2.0)"); pg.keyboard.press('p'); pg.wait_for_timeout(6000)
    shot(pg, f'{cid}-takip.png')
    print(f'  {cid}: {time.time() - t0:.0f} sn', flush=True)
    iptal(mid)
    ctx.close()
    return info


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE, args=ARGS)
    olcum = {}
    if os.environ.get('SHOT_SKIP_UI') != '1':
        # 1) Yeni Karşılaşma › Tür ve kurallar: FPV kartı + galeri
        ch, ph = baglam(b, s)
        ph.goto(f'{BASE}/#/drone/sim?tab=matches', wait_until='domcontentloaded')
        ph.wait_for_selector('.fs-new-match'); ph.wait_for_timeout(1200)
        ph.click('.fs-new-match')
        ph.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=120000); ph.wait_for_timeout(1500)
        ph.evaluate("window.__fsWz.goto('rings')"); ph.wait_for_timeout(500)
        ph.click('.fs-df-kind[data-kind="fpv"]')
        ph.wait_for_selector('.fs-fc-card .fs-fc-thumb svg', timeout=60000); ph.wait_for_timeout(1500)
        ph.click('.fs-fc-card[data-course="woodframe"]'); ph.wait_for_timeout(1500)
        kontrol('galeride 8 parkur', ph.locator('.fs-fc-card').count() == 8)
        ph.evaluate("document.querySelector('.fs-df-kinds')?.scrollIntoView({block: 'start'})"); ph.wait_for_timeout(500)
        shot(ph, 'galeri-yeni-karsilasma.png')
        ph.evaluate("window.__fsWz.goto('invite')"); ph.wait_for_timeout(600)
        kontrol('davetsiz: tek kişilik notu', ph.locator('.fs-mt-solo:not([hidden])').count() == 1)
        shot(ph, 'davet-tek-kisilik.png')
        ph.evaluate("window.__fsWz.goto('summary')"); ph.wait_for_timeout(800)
        kontrol('özet: Başlat etkin', not ph.locator('.fs-start').is_disabled())
        kontrol('özet: tek kişilik satırı', 'zaman denemesi' in ph.locator('.fs-wz-sum').inner_text())
        shot(ph, 'ozet-tek-kisilik.png')
        ch.close()
        # 2) Yeni Simülasyon › Hazır FPV parkurları (zaman denemesi penceresi)
        ch, ph = baglam(b, s)
        ph.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded')
        ph.wait_for_selector('.fs-new-sim'); ph.wait_for_timeout(1000)
        ph.click('.fs-new-sim')
        ph.wait_for_selector('.fs-fc-ttbtn', timeout=120000); ph.wait_for_timeout(1500)
        shot(ph, 'yeni-simulasyon-fpv-karti.png')
        ph.click('.fs-fc-ttbtn')
        ph.wait_for_selector('.fs-fc-ttmodal .fs-fc-card .fs-fc-thumb svg', timeout=60000); ph.wait_for_timeout(1200)
        ph.click('.fs-fc-ttmodal .fs-fc-card[data-course="refinery"]'); ph.wait_for_timeout(1500)
        ph.evaluate("document.querySelector('.fs-fc-ttmodal .modal-body').scrollTop = 0"); ph.wait_for_timeout(500)
        shot(ph, 'galeri-zaman-denemesi.png')
        ch.close()
    # 3) mekanlar (FPV + takip)
    for cid in MEKANLAR:
        if cid in DUR:
            try:
                olcum[cid] = mekan_karesi(b, cid)
            except Exception as e:   # noqa: BLE001
                hatalar.append(f'{cid}: {str(e)[:300]}')
    # 4) hayalet + HUD + tek kişilik sonuç (hangar, 3 tur — yazılım WebGL'de ekran görüntüsü yavaş, koşu kare alınırken bitmesin): koşu 1 kayıt (5 m/s) · koşu 2 biraz yavaş (hayalet önde görünür; kare sonra iptal) ·
    #    koşu 3 hızlı → KİŞİSEL REKOR (fanfar + rozet)
    if os.environ.get('SHOT_SKIP_GHOST') != '1':
        c = flightsim_fpv.parkur('hangar')
        pts, kapi = hat_noktalari(c)
        ctx, pg = baglam(b, s)
        mid, sid = yaris_ac(pg, 'hangar', laps=3, rule='penalty')
        st = fpv_pilotu(flightsim.MANAGER.get(sid), c, hiz=5.0, tur=3)
        kontrol('koşu 1 bitti', bekle(lambda: mac(mid)['state'] == 'BITTI', 400, 1.0))
        pg.wait_for_selector('.fs-mt-result:not([hidden])', timeout=120000); pg.wait_for_timeout(2500)
        shot(pg, 'sonuc-ilk-kayit.png')
        ctx.close()
        time.sleep(9)
        ctx, pg = baglam(b, s)
        mid, sid = yaris_ac(pg, 'hangar', laps=3, rule='penalty')
        st = fpv_pilotu(flightsim.MANAGER.get(sid), c, hiz=4.8, tur=3)
        pg.wait_for_function("() => window.__fsFpv && window.__fsFpv.layer && window.__fsFpv.layer.info().ghost !== undefined", timeout=120000)
        bekle(lambda: st['i'] > kapi.get(1, 4), 200, 0.3)
        kamera(pg, 'pilot'); pg.wait_for_timeout(4000)
        try:
            pg.wait_for_function("() => window.__fsFpv.layer.info().ghost", timeout=60000)
        except Exception:   # noqa: BLE001
            pass
        gi = pg.evaluate("window.__fsFpv.layer.info()")
        kontrol(f"hayalet görünür: {gi.get('ghostPos')}", bool(gi.get('ghost')))
        hs = pg.evaluate("window.__fsFpv.hud.state()")
        kontrol(f"HUD hayalet farkı: {hs.get('delta')}", hs.get('delta') is not None)
        shot(pg, 'hud-hayalet.png')
        pg.evaluate("window.__fsMatch?.sim?.setFollowView(5.5, 2.0)"); pg.keyboard.press('p'); pg.wait_for_timeout(5000)
        shot(pg, 'hud-hayalet-takip.png')
        iptal(mid)
        ctx.close()
        time.sleep(9)
        ctx, pg = baglam(b, s)
        mid, sid = yaris_ac(pg, 'hangar', laps=3, rule='penalty')
        st = fpv_pilotu(flightsim.MANAGER.get(sid), c, hiz=12.0, tur=3)
        kontrol('koşu 3 bitti', bekle(lambda: mac(mid)['state'] == 'BITTI', 300, 1.0))
        pg.wait_for_selector('.fs-mt-result:not([hidden]) .fs-fc-res', timeout=120000); pg.wait_for_timeout(4000)
        kontrol('KİŞİSEL REKOR rozeti', pg.locator('.fs-mt-result .fs-fc-res .pb').count() == 1)
        shot(pg, 'sonuc-tek-kisilik.png')
        pg.goto(f'{BASE}/#/drone/sim?tab=matches', wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-mt-table tbody tr', timeout=300000); pg.wait_for_timeout(1500)
        kontrol('Karşılaşmalar: FPV parkur + tek kişilik rozeti', pg.locator('.fs-mt-table .fs-fc-solo').count() >= 1)
        shot(pg, 'karsilasmalar-sekmesi.png')
        ctx.close()
    b.close()

server.should_exit = True
time.sleep(1.5)
print('ÖLÇÜM:', json.dumps({k: {'gfx': v['gfx'], 'stats': v['stats']} for k, v in olcum.items()}, ensure_ascii=False))
print('HATALAR:' if hatalar else 'Hata yok', *hatalar[:40], sep='\n  ')
sys.exit(1 if [x for x in hatalar if not x.startswith('KONSOL')] else 0)
