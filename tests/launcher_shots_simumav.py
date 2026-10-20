"""SIMUMAV — HEPGO §27 INTERCEPTOR fırlatıcıları görsel doğrulama (Playwright headless shell + SwiftShader; sahte SITL). Sunucu aynı süreçte iş parçacığı.
Görüntüler /tmp/launcher-shots/sm-*.png: 01 sihirbaz fırlatıcı adımı (4 kart + 4'lü önizleme) · 02 el fırlatıcısı kartı (nişan kaydırıcıları)
  03 uçuş: NİŞANGÂH penceresi göğe bakarken hedeflerle · 04 fırlatma anı (İngilizce arayüz: launcher.* çevirileri)
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            ./.venv/bin/python -m tests.launcher_shots_simumav
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/launcher-shots-sm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='25350', SIMUMAV_MAX_FLIGHTS='2',
                  SIMUMAV_MP_PORT_BASE='26200', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='', SIMUMAV_MAX_SPEEDUP='8')
PORT = int(os.environ.get('SHOT_PORT') or 8619)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/launcher-shots'); OUT.mkdir(parents=True, exist_ok=True)
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
d = s.post(f'{BASE}/api/hangar', json={'name': 'Önleyici X4', 'type': 'interceptor', 'model_key': 'glb:icept_x4', 'color': '#ef4444'}, headers=H).json()
s.put(f"{BASE}/api/hangar/{d['id']}", json={'is_default': True}, headers=H)
pid = s.get(f'{BASE}/api/crew').json()['pilots'][0]['id']
tr = s.post(f'{BASE}/api/tracks', json={'name': 'Önleme Sahası', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural',
                                        'world': {'seed': 21, 'runway': True, 'tree_density': 0.2, 'building_count': 20}}, headers=H).json()
s.put(f"{BASE}/api/tracks/{tr['id']}", json={'is_default': True}, headers=H)
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


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': 'smsid', 'value': tok, 'url': BASE}])
        ctx.add_init_script("try { localStorage.setItem('sm:lang', 'tr'); localStorage.setItem('simumav.consent', 'denied'); localStorage.setItem('fs.cam.pip', JSON.stringify({ on: false })); } catch (e) {}")
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.on('response', lambda r: hatalar.append(f'HTTP {r.status} {r.url[len(BASE):][:120]}') if r.status >= 400 else None)
        # ---- 01–02 sihirbaz: drone → track → FIRLATICI
        pg.goto(f'{BASE}/app/#/fly', wait_until='domcontentloaded')
        pg.wait_for_selector('.sm-wizard .sm-cards-drones', timeout=60000)
        pg.wait_for_timeout(6000)
        for _ in range(2):
            pg.click('.sm-nav-btn.primary'); pg.wait_for_timeout(600)
        pg.wait_for_selector('.sm-icept-pod4', timeout=20000)
        pg.wait_for_timeout(9000)
        print('  kartlar:', pg.evaluate("[...document.querySelectorAll('.sm-cards-launch .sm-card b')].map(b => b.textContent)"), flush=True)
        shot(pg, 'sm-01-wizard-launcher.png')
        pg.locator('.sm-cards-launch .sm-card').nth(3).click(); pg.wait_for_timeout(7000)
        shot(pg, 'sm-02-wizard-handheld.png')
        # ---- 03–04 uçuş: el fırlatıcısı + hedefler (İngilizce arayüz)
        targets = {'items': [{'model': 'tgt:lancet', 'alt_m': 120, 'diameter_m': 400, 'east_m': 250, 'north_m': 350, 'speed_ms': 25, 'dir': 'cw', 'name': 'Lancet-1'},
                             {'model': 'tgt:octopus', 'alt_m': 180, 'diameter_m': 600, 'east_m': 400, 'north_m': 500, 'speed_ms': 40, 'dir': 'ccw', 'name': 'Octopus-1'}], 'radius_m': 25}
        f = s.post(f'{BASE}/api/fly/start', json={'drone_id': d['id'], 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False}, 'targets': targets,
                                                'launch': {'method': 'handheld', 'aim_az_deg': 30, 'aim_el_deg': 25}}, headers=H)
        assert f.status_code == 201, f.text
        fid, sid = f.json()['flight_id'], f.json()['sim_id']
        ss = flightsim.MANAGER.sessions[sid]
        pg.evaluate("localStorage.setItem('sm:lang', 'en')")
        pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
        pg.goto(f'{BASE}/app/?lang=en#/fly/{fid}', wait_until='domcontentloaded')
        pg.wait_for_function('() => window.__smSession && window.__smSession.sim && window.__smSession.sim.targetsInfo().length === 2 && window.__smSession.sim.launcherInfo()', timeout=240000)
        bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
        pg.wait_for_timeout(2000)
        a = pg.evaluate('window.__smSession.sim.aimAtTarget()')
        print('  hedefe nişan:', a, flush=True)
        pg.evaluate("window.__smSession.sim.setScopeZoom(2)")
        pg.evaluate("window.__smSession.sim.setCamera('follow')"); pg.wait_for_timeout(4000)
        print('  pencere:', pg.evaluate("(() => { const e = document.querySelector('.fs-scope'); return e && { hidden: e.hidden, title: e.querySelector('.fs-scope-hd .t').textContent, btn: document.querySelector('.fs-scope-btn')?.textContent }; })()"), flush=True)
        shot(pg, 'sm-03-fly-scope.png')
        aim = pg.evaluate('window.__smSession.sim.getAim()')
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40, 'aim': {'az_deg': round(aim['az'], 1), 'el_deg': round(aim['el'], 1)}}}, headers=H)
        bekle(lambda: ss.launch_phase in ('launch', 'released'), 30, 'fırlatma')
        pg.wait_for_timeout(1000)
        shot(pg, 'sm-04-fly-launch.png')
        print('  aşama:', ss.launch_phase, ss.launch.get('aim_az_deg'), flush=True)
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
    time.sleep(1.0)
