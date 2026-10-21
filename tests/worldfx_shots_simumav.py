"""SIMUMAV — HEPGO §31 ortak dünya katmanı: parkur hava durumu (yağmur / kar), rüzgâr göstergesi (baş/yan/kuyruk), akış çizgileri, rampa yön/açı
paneli — görsel doğrulama (Playwright headless shell + SwiftShader; sahte SITL). Görüntüler /tmp/worldfx-shots/sm-*.png.
Çalıştırma: ./.venv/bin/python -m tests.worldfx_shots_simumav
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/worldfx-shots-sm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='25750', SIMUMAV_MAX_FLIGHTS='2',
                  SIMUMAV_MP_PORT_BASE='26700', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='', SIMUMAV_MAX_SPEEDUP='8')
PORT = int(os.environ.get('SHOT_PORT') or 8641)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/worldfx-shots'); OUT.mkdir(parents=True, exist_ok=True)
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
cay = s.post(f'{BASE}/api/hangar', json={'name': 'CAYMAZ', 'type': 'plane', 'model_key': 'builtin:caymaz', 'color': '#f97316'}, headers=H).json()
kop = s.post(f'{BASE}/api/hangar', json={'name': 'Kartal', 'type': 'multirotor', 'model_key': 'builtin:quad', 'color': '#0ea5e9'}, headers=H).json()
pid = s.get(f'{BASE}/api/crew').json()['pilots'][0]['id']
hatalar = []


def parkur(ad, hava, gust):
    r = s.post(f'{BASE}/api/tracks', json={'name': ad, 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural', 'weather': hava,
                                          'wind': {'speed_ms': 7, 'dir_deg': 300, 'gust': gust},
                                          'world': {'seed': 21, 'runway': True, 'tree_density': 0.35, 'building_count': 60, 'runway_deg': 30}}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


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


def shot(pg, ad):
    pg.screenshot(path=str(OUT / ad))
    print('  kare', ad, flush=True)


def kareler(pg, n=3):
    pg.evaluate(f'() => new Promise(r => {{ let k = 0; const f = () => {{ if (++k >= {n}) r(); else requestAnimationFrame(f); }}; requestAnimationFrame(f); }})')


def ucus(pg, drone, tr, launch):
    f = s.post(f'{BASE}/api/fly/start', json={'drone_id': drone['id'], 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False}, **({'launch': launch} if launch else {})}, headers=H)
    assert f.status_code == 201, f.text
    fid, sid = f.json()['flight_id'], f.json()['sim_id']
    ss = flightsim.MANAGER.sessions[sid]
    pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
    pg.goto(f'{BASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
    pg.wait_for_function('() => window.__smSim && window.__smSim.getCamera', timeout=240000)
    bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
    pg.wait_for_timeout(9000); kareler(pg, 3)
    return fid, sid, ss


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': 'smsid', 'value': tok, 'url': BASE}])
        ctx.add_init_script("try { localStorage.setItem('sm:lang', 'tr'); localStorage.setItem('simumav.consent', 'denied'); } catch (e) {}")
        pg = ctx.new_page()
        pg.set_default_timeout(240000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        # 1) yağmurlu parkur + rampa: rüzgâr göstergesi, tulum, rampa paneli
        tr1 = parkur('Yağmurlu Vadi', 'rain', 3)
        fid, sid, ss = ucus(pg, cay, tr1, {'method': 'ramp', 'angle_deg': 15})
        print('  dünya:', pg.evaluate('({w: window.__smSim.world.weather, g: window.__smSim.world.wind_gust, fx: window.__smSim.fxInfo()})'), flush=True)
        shot(pg, 'sm-01-rain-ramp-gauge.png')
        pg.evaluate('window.__fsRampUi && window.__fsRampUi.open()'); pg.wait_for_timeout(800)
        if pg.locator('.fs-ramp-wind').count():
            pg.locator('.fs-ramp-wind').click(); pg.wait_for_timeout(1500); kareler(pg, 2)
        shot(pg, 'sm-02-ramp-panel-into-wind.png')
        if pg.locator('.fs-ramp-apply:not([disabled])').count():
            pg.locator('.fs-ramp-apply').click(); pg.wait_for_timeout(2500)
        print('  rampa (çekirdek):', ss.launch, flush=True)
        pg.evaluate("window.__smSim.setCamera('pilot')"); pg.wait_for_timeout(2500); kareler(pg, 3)
        shot(pg, 'sm-03-rain-fpv-lens.png')
        s.post(f'{BASE}/api/fly/{fid}/stop', json={}, headers=H); pg.wait_for_timeout(1500)
        # 2) karlı parkur + kopter: kar parçacıkları, beyaz zemin, akış çizgileri
        tr2 = parkur('Karlı Tepe', 'snow', 0)
        fid, sid, ss = ucus(pg, kop, tr2, None)
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'arm', 'params': {}}, headers=H)
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 30}}, headers=H)
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 20, 90, 'kalkış')
        pg.evaluate("window.__smSim.setCamera('follow')"); pg.wait_for_timeout(3000); kareler(pg, 3)
        shot(pg, 'sm-04-snow-follow-streaks.png')
        r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'wind', 'params': {'ms': 3}}, headers=H)
        print('  SIMUMAV uçuşta rüzgâr komutu (sunucu çekirdeği; oyun WS yolu engeller):', r.status_code, flush=True)
        s.post(f'{BASE}/api/fly/{fid}/stop', json={}, headers=H)
        b.close()
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(4.0)
