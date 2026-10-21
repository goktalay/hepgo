"""SIMUMAV uçuş arayüzü (HEPGO §27.1 / §27.2 / §27.3 / §27.4 ortak modülleri) — görsel doğrulama (Playwright headless shell + SwiftShader; sahte SITL).
Görüntüler /tmp/flyui-shots/sm-*.png: 01 sihirbaz Pilot adımında gösterge tasarımı kartları · 02 giriş sekansı (100 m + 3-2-1) · 03 hassasiyet paneli ·
04 radar/EO taşınmış + büyütülmüş · 05 gösterge temaları (oyun teması koyu + açık).
Çalıştırma: ./.venv/bin/python -m tests.flyui_shots_simumav
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/flyui-shots-sm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='25450', SIMUMAV_MAX_FLIGHTS='2',
                  SIMUMAV_MP_PORT_BASE='26400', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='', SIMUMAV_MAX_SPEEDUP='8')
PORT = int(os.environ.get('SHOT_PORT') or 8637)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/flyui-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import app.simumav.main as smain  # noqa: E402
from app import flightsim  # noqa: E402

server = uvicorn.Server(uvicorn.Config(smain.app, host='127.0.0.1', port=PORT, log_level='error'))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(120):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close(); break
    except OSError:
        time.sleep(0.25)
else:
    sys.exit('sunucu açılmadı')

H = {'Origin': BASE}
s = requests.Session()
assert s.post(f'{BASE}/api/session', json={'dev_user': 'ayse'}, headers=H).status_code == 200
tok = s.cookies['smsid']
d = s.post(f'{BASE}/api/hangar', json={'name': 'Kartal', 'type': 'multirotor', 'model_key': 'builtin:quad', 'color': '#0ea5e9'}, headers=H).json()
s.put(f"{BASE}/api/hangar/{d['id']}", json={'is_default': True}, headers=H)
pid = s.get(f'{BASE}/api/crew').json()['pilots'][0]['id']
tr = s.post(f'{BASE}/api/tracks', json={'name': 'Göl Kıyısı', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural',
                                        'world': {'seed': 21, 'runway': True, 'tree_density': 0.2, 'building_count': 20, 'runway_deg': 30}}, headers=H).json()
s.put(f"{BASE}/api/tracks/{tr['id']}", json={'is_default': True}, headers=H)
hatalar = []


def bekle(pred, sec, ad):
    t0 = time.time()
    while time.time() - t0 < sec:
        try:
            if pred():
                return True
        except Exception:   # noqa: BLE001
            pass
        time.sleep(0.25)
    hatalar.append(f'{ad}: {sec} sn içinde olmadı'); return False


def shot(pg, ad, clip=None):
    pg.screenshot(path=str(OUT / ad), clip=clip)
    print('  kare', ad, flush=True)


def drag(pg, sel, dx, dy, steps=12):
    bb = pg.locator(sel).first.bounding_box()
    x, y = bb['x'] + min(60, bb['width'] / 3), bb['y'] + bb['height'] / 2
    pg.mouse.move(x, y); pg.mouse.down()
    for i in range(1, steps + 1):
        pg.mouse.move(x + dx * i / steps, y + dy * i / steps); pg.wait_for_timeout(16)
    pg.mouse.up()


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': 'smsid', 'value': tok, 'url': BASE}])
        ctx.add_init_script("try { localStorage.setItem('sm:lang', 'tr'); localStorage.setItem('simumav.consent', 'denied'); } catch (e) {}")
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        # ---- 01 sihirbaz: Pilot adımı (kamera türü + gösterge tasarımı)
        pg.goto(f'{BASE}/app/#/fly', wait_until='domcontentloaded')
        pg.wait_for_selector('.sm-wizard .sm-cards-drones', timeout=60000)
        pg.wait_for_timeout(2500)
        for _ in range(10):
            if pg.locator('.sm-cards-pilots').count():
                break
            pg.click('.sm-nav-btn.primary'); pg.wait_for_timeout(500)
        pg.wait_for_selector('.fs-gt-card', timeout=20000)
        pg.locator('.fs-gt-card[data-gtheme="military"]').click(); pg.wait_for_timeout(300)
        pg.evaluate("document.querySelector('.sm-gt-holder').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(600)
        shot(pg, 'sm-01-wizard-gauge-theme.png')
        print('  tema:', pg.evaluate("localStorage.getItem('fs.gauge.theme')"), flush=True)
        # ---- uçuş (API) + giriş sekansı
        f = s.post(f'{BASE}/api/fly/start', json={'drone_id': d['id'], 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False},
                                                  'site': {'station': True, 'radar': True, 'radar_km': 10, 'eo': True, 'eo_km': 5}}, headers=H)
        assert f.status_code == 201, f.text
        fid, sid = f.json()['flight_id'], f.json()['sim_id']
        ss = flightsim.MANAGER.sessions[sid]
        pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
        pg.evaluate("window.__fsIntroHold = 0.15; localStorage.removeItem('fs.site.win')")
        pg.goto(f'{BASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
        pg.evaluate("window.__fsIntroHold = 0.15")
        pg.wait_for_selector('.fs-cd:not([hidden])', timeout=240000)
        pg.wait_for_timeout(6000)
        for at, ad in ((0.15, 'a-3'), (1.3, 'b-2'), (2.35, 'c-1'), (3.3, 'd-go'), (4.4, 'e-blend')):
            pg.evaluate(f'window.__fsIntroHold = {at}'); pg.wait_for_timeout(2500)
            shot(pg, f'sm-02-intro-{ad}.png')
        pg.evaluate('delete window.__fsIntroHold'); pg.wait_for_timeout(2500)
        shot(pg, 'sm-02-intro-f-normal.png')
        bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40}}, headers=H)
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 30, 90, 'kalkış')
        # ---- 03 hassasiyet paneli
        pg.evaluate('window.__smSession.rcToggle()'); pg.wait_for_timeout(500)
        pg.locator('.fs-rcf-btn').click(); pg.wait_for_timeout(300)
        pg.locator('.fs-rcf-seg button[data-p="sport"]').click(); pg.wait_for_timeout(500)
        shot(pg, 'sm-03-rc-feel-panel.png')
        pg.locator('.fs-rcf-x').click(); pg.evaluate('window.__smSession.rcToggle()'); pg.wait_for_timeout(300)
        # ---- 04 radar / EO taşı + büyüt
        bekle(lambda: pg.locator('.fs-site-scr.radar').is_visible(), 60, 'radar ekranı')
        drag(pg, '.fs-site-scr.radar .fs-site-hd', 300, -360); pg.wait_for_timeout(300)
        gb = pg.locator('.fs-site-scr.radar .fs-site-grip').bounding_box()
        pg.mouse.move(gb['x'] + 8, gb['y'] + 8); pg.mouse.down()
        for i in range(1, 13):
            pg.mouse.move(gb['x'] + 8 + 120 * i / 12, gb['y'] + 8 + 80 * i / 12); pg.wait_for_timeout(16)
        pg.mouse.up(); pg.wait_for_timeout(2500)
        shot(pg, 'sm-04-site-moved-resized.png')
        # ---- 05 gösterge temaları
        pg.wait_for_selector('.fs-gauges:not([hidden])', timeout=60000)
        for t in ('dark', 'light'):
            pg.evaluate(f"document.documentElement.setAttribute('data-theme', '{t}')")
            for k in ('classic', 'cockpit', 'glass', 'minimal', 'military'):
                pg.evaluate(f"document.querySelector('.fs-gauges').dataset.gtheme = '{k}'"); pg.wait_for_timeout(700)
                bb = pg.locator('.fs-gauges').bounding_box()
                clip = {'x': max(0, bb['x'] - 40), 'y': max(0, bb['y'] - 40), 'width': min(1440, bb['width'] + 80), 'height': min(900 - max(0, bb['y'] - 40), bb['height'] + 70)}
                shot(pg, f'sm-05-gauges-{k}-{t}.png', clip)
        shot(pg, 'sm-05-full.png')
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / 'sm-hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
