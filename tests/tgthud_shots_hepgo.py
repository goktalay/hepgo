"""HEPGO Uçuş Simülatörü §24.4 (sihirbaz hedef 3B önizlemesi) + §24.5 (F-16 tarzı hedef sembolojisi) — görsel doğrulama (Playwright headless shell +
SwiftShader). Uygulama aynı süreçte (iş parçacığı) açılır; TGT_REAL=1 + HEPGO_SITL_DIR → gerçek ArduPilot SITL (kapanışta lifespan kapatır), aksi sahte.
Görüntüler /tmp/tgthud-shots/hepgo-*.png:
  01 sihirbaz Hedefler kartları (dönen 3B önizleme, ölçek çubuğu, ad/hız/boyut) · 02 gimbal: prizmalar + TD kutusu + TLL · 03 FPV (balıkgözü) aynısı
  04 arkadaki hedefe kilit: kenar oku + TLL + sapma açısı · 05 termal kamerada semboloji · 06 önleme anı (yanıp sönen kutu + ÖNLEME) · 07 FPV önleme/ok
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            ./.venv/bin/python -m tests.tgthud_shots_hepgo        (gerçek SITL: TGT_REAL=1 HEPGO_SITL_DIR=/opt/hepgo/sitl/bin)
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
REAL = os.environ.get('TGT_REAL') == '1'
DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/tgthud-shots-hepgo-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1' if REAL else '0', SIM_UDP_BASE='39350', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8835)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/tgthud-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth, flightsim  # noqa: E402
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
s = requests.Session()
assert s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'}).status_code == 200
s.post(f'{BASE}/api/kvkk/accept-terms', json={})
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Test Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
hatalar = []


def bekle(pred, sec, ad):
    t0 = time.time()
    while time.time() - t0 < sec:
        if pred():
            return True
        time.sleep(0.2)
    hatalar.append(f'{ad}: {sec} sn içinde olmadı'); return False


def shot(pg, ad):
    pg.screenshot(path=str(OUT / ad))
    print('  kare', ad, flush=True)


def cmd(sid, name, params=None):
    r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': name, 'params': params or {}})
    if r.status_code != 200:
        hatalar.append(f'cmd {name} {r.status_code} {r.text[:200]}')
    return r


HUD = "(document.querySelector('.fs-mhud')?.__hud?.targets?.() || null)"
OSD = "(document.querySelector('.fs-osd')?.__osd?.targets?.() || null)"


def kilit(pg, i):
    """Tab döngüsüyle i'ye kilitlen (en çok 6 adım)."""
    for _ in range(6):
        if pg.evaluate(f"window.__fsSim.targetLock && window.__fsSim.targetLock.auto === false && window.__fsSim.targetLock.i === {i}"):
            return True
        pg.keyboard.press('Tab'); pg.wait_for_timeout(150)
    return False


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.on('response', lambda r: hatalar.append(f'HTTP {r.status} {r.url[len(BASE):][:120]}') if r.status >= 400 and '/thumb' not in r.url else None)
        # ---- 01 sihirbaz: Hedefler kartları + 3B önizleme (dünya önizlemesinin renderer'ı)
        pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-wizard .fs-types', timeout=60000)
        pg.wait_for_timeout(6000)
        pg.evaluate("window.__fsWz.goto('targets')"); pg.wait_for_timeout(300)   # §6 adım adım sihirbaz: Hedefler adımı
        for _ in range(3):
            pg.locator('.fs-tg-add').click(); pg.wait_for_timeout(300)
        pg.locator('.fs-tg-card').nth(1).locator('select.fs-tg-model').select_option('tgt:octopus')
        pg.locator('.fs-tg-card').nth(2).locator('select.fs-tg-model').select_option('tgt:altius')
        pg.evaluate("document.querySelector('.fs-targets').scrollIntoView({block: 'start'})")
        pg.wait_for_function("() => [...document.querySelectorAll('.fs-tgv-size')].filter(e => e.textContent).length >= 3", timeout=120000)
        cv = pg.locator('.fs-tgv-cv').first
        bb = cv.bounding_box()
        pg.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2); pg.mouse.down()
        pg.mouse.move(bb['x'] + bb['width'] / 2 + 60, bb['y'] + bb['height'] / 2 - 25, steps=6); pg.mouse.up()
        pg.wait_for_timeout(2500)
        print('  önizleme:', pg.evaluate("[...document.querySelectorAll('.fs-tgv-cap')].map(e => e.textContent)"), flush=True)
        shot(pg, 'hepgo-01-wizard-preview.png')
        n_ctx = pg.evaluate("performance.getEntriesByType ? document.querySelectorAll('canvas').length : 0")
        print('  tuval sayısı (WebGL tek: .fs3d-canvas):', pg.evaluate("document.querySelectorAll('.fs3d-canvas').length"), '/', n_ctx, flush=True)
        # ---- oturum (API): T1 sahte kipte dronun uçtuğu 150 m'lik dairede daha hızlı uçar (yakalar → önleme), T2 kuzey, T3 doğu, T4 güney (arkada)
        targets = {'items': [{'model': 'tgt:lancet', 'alt_m': 60, 'diameter_m': 300, 'speed_ms': 30, 'dir': 'cw', 'name': 'Lancet-1'},
                             {'model': 'tgt:octopus', 'alt_m': 85, 'diameter_m': 300, 'east_m': 0, 'north_m': 520, 'speed_ms': 40, 'dir': 'ccw', 'name': 'Octopus-1'},
                             {'model': 'tgt:altius', 'alt_m': 70, 'diameter_m': 260, 'east_m': 480, 'north_m': 80, 'dir': 'cw', 'name': 'Altius-1'},
                             {'model': 'tgt:sw300', 'alt_m': 65, 'diameter_m': 200, 'east_m': -60, 'north_m': -450, 'dir': 'cw', 'name': 'SW300-1'}], 'radius_m': 25}
        r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': REAL},
                                                           'world': {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.25, 'building_count': 30},
                                                           'targets': targets})
        assert r.status_code == 201, r.text
        sid = r.json()['id']
        ss = flightsim.MANAGER.sessions[sid]
        bekle(lambda: ss.state == 'HAZIR' and (ss.sahte is not None or ss._heartbeat_alindi), 120, 'HAZIR')
        pg.keyboard.press('Escape'); pg.wait_for_timeout(500)
        pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
        pg.wait_for_function('() => window.__fsSim && window.__fsSim.targetsInfo().length === 4', timeout=240000)
        if REAL:
            time.sleep(20)
        cmd(sid, 'takeoff', {'alt': 60})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 55, 120, 'kalkış 60 m')
        print('  yön:', ss.tele.get('heading'), flush=True)
        # ---- 02 gimbal: ufuk hizası (gimbal 0°), oto kilit = en yakın
        pg.evaluate("window.__fsSim.setCamera('fpv'); window.__fsSim.setGimbal(10)"); pg.wait_for_timeout(3500)
        print('  HUD:', pg.evaluate(HUD), flush=True)
        shot(pg, 'hepgo-02-gimbal-symbology.png')
        # öndeki (ekranda) bir hedefe kilit → TD kutusu + TLL
        on = pg.evaluate(f"({HUD}?.items || []).filter(r => r.on).map(r => r.i)")
        if on:
            kilit(pg, on[0]); pg.wait_for_timeout(1500)
            shot(pg, 'hepgo-02b-gimbal-locked.png')
        else:
            hatalar.append('gimbal: ekranda hedef yok')
        # ---- 03 FPV (pilot; balıkgözü)
        pg.evaluate("window.__fsSim.setCamera('pilot')"); pg.wait_for_timeout(3500)
        print('  OSD:', pg.evaluate(OSD), flush=True)
        shot(pg, 'hepgo-03-fpv-symbology.png')
        # ---- 04 arkadaki hedefe kilit (ekran dışı) → kenar oku + TLL + sapma açısı
        pg.evaluate("window.__fsSim.setCamera('fpv')"); pg.wait_for_timeout(1500)
        off = pg.evaluate(f"({HUD}?.items || []).filter(r => !r.on).map(r => r.i)")
        if off:
            kilit(pg, off[-1]); pg.wait_for_timeout(2000)
            print('  ok:', pg.evaluate(HUD), flush=True)
            shot(pg, 'hepgo-04-offscreen-arrow.png')
        else:
            hatalar.append('ekran dışı hedef yok')
        # ---- 05 termal kamera
        pg.evaluate("window.__fsSim.setCamType('thermal')")
        if on:
            kilit(pg, on[0])
        pg.wait_for_timeout(3000)
        shot(pg, 'hepgo-05-thermal-symbology.png')
        pg.evaluate("window.__fsSim.setCamType('night')"); pg.wait_for_timeout(2500)
        shot(pg, 'hepgo-05b-night-symbology.png')
        pg.evaluate("window.__fsSim.setCamType('day')")
        # ---- 06 önleme: Lancet-1 (i=0) dronu aynı dairede yakalar
        kilit(pg, 0)
        ok = bekle(lambda: pg.evaluate(f"({HUD}?.items || []).some(r => r.i === 0 && r.hot)"), 90, 'önleme (HUD)')
        if ok:
            pg.wait_for_timeout(200)
            print('  önleme HUD:', pg.evaluate(HUD), flush=True)
            shot(pg, 'hepgo-06-intercept-gimbal.png')
        # ---- 07 FPV'de önleme
        pg.evaluate("window.__fsSim.setCamera('pilot')")
        ok = bekle(lambda: pg.evaluate(f"({OSD}?.items || []).some(r => r.i === 0 && r.hot)"), 90, 'önleme (OSD)')
        if ok:
            pg.wait_for_timeout(200)
            shot(pg, 'hepgo-07-intercept-fpv.png')
        print('  önleme özeti:', ss.hedef_iz.ozet()['total'], flush=True)
        hs = pg.evaluate("document.querySelector('.fs-mhud')?.__hud?.stats?.()")
        os_ = pg.evaluate("document.querySelector('.fs-osd')?.__osd?.stats?.()")
        print('  çizim ms/kare HUD:', hs, 'OSD:', os_, flush=True)
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / 'hepgo-hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(8.0)
