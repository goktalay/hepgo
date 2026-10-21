"""SIMUMAV KARA ARACI (docs/simumav.md §15; HEPGO §31) — görsel doğrulama (Playwright headless shell + SwiftShader; sahte SITL).
Sunucu aynı süreçte iş parçacığı olarak açılır (arka plan süreci bırakılmaz). Görüntüler /tmp/rover-shots/simumav-*.png:
  01 hangar (Keşif 4×4 seçili, dönen 3B; tekerler döner) · 02 yeni araç: tür seçici "Kara Aracı" · 03 model kartları (sürüş biçimi + azami hız)
  04 Uç sihirbazı dron adımı (sürüş biçimi kartları + önizleme) · 05 güç adımı (sürüş bataryası, yakıt isteğe bağlı) · 06 uçuş: takip kamerası, rover sahnede,
  sanal kumanda (gaz/direksiyon) · 07 mod seçici (ArduRover kipleri) · 08 UGV (paletli) uçuş ekranı
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            ./.venv/bin/python -m tests.rover_shots_simumav
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/rover-shots-sm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='25450', SIMUMAV_MAX_FLIGHTS='2',
                  SIMUMAV_MP_PORT_BASE='27000', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='', SIMUMAV_MAX_SPEEDUP='8')
PORT = int(os.environ.get('SHOT_PORT') or 8627)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/rover-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.environ.get('CHROMIUM_PATH') or os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
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
assert s.post(f'{BASE}/api/session', json={'dev_user': 'surucu'}, headers=H).status_code == 200
tok = s.cookies['smsid']
d4 = s.post(f'{BASE}/api/hangar', json={'name': 'Keşif-1', 'type': 'rover', 'model_key': 'glb:rover_4x4', 'color': '#f59e0b'}, headers=H).json()
s.put(f"{BASE}/api/hangar/{d4['id']}", json={'is_default': True}, headers=H)
dugv = s.post(f'{BASE}/api/hangar', json={'name': 'Palet-1', 'type': 'rover', 'model_key': 'glb:rover_ugv', 'color': '#22c55e'}, headers=H).json()
s.post(f'{BASE}/api/hangar', json={'name': 'Kurye-1', 'type': 'rover', 'model_key': 'glb:rover_bot', 'color': '#38bdf8'}, headers=H)
pid = s.get(f'{BASE}/api/crew').json()['pilots'][0]['id']
tr = s.post(f'{BASE}/api/tracks', json={'name': 'Arazi Sahası', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural',
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


def ucus(pg, drone, ad, drive=None, rc=True, modes=False):
    body = {'drone_id': drone['id'], 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False}}
    if drive:
        body['drive'] = drive
    f = s.post(f'{BASE}/api/fly/start', json=body, headers=H)
    assert f.status_code == 201, f.text
    fid, sid = f.json()['flight_id'], f.json()['sim_id']
    ss = flightsim.MANAGER.sessions[sid]
    pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
    pg.goto(f'{BASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
    pg.wait_for_function('() => window.__smSession && window.__smSession.sim', timeout=240000)
    bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
    try:   # giriş sekansı (3-2-1 + iniş) başlar ve biter
        pg.wait_for_function("() => document.querySelector('.fs-stage.fs-intro-on')", timeout=20000)
        pg.wait_for_function("() => !document.querySelector('.fs-stage.fs-intro-on')", timeout=60000)
    except Exception:   # noqa: BLE001
        hatalar.append('giriş sekansı izlenemedi')
    pg.wait_for_timeout(1500)
    r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'arm', 'params': {}}, headers=H)
    if r.status_code != 200:
        hatalar.append(f'arm: {r.status_code} {r.text[:200]}')
    pg.evaluate("window.__smSession.sim.setCamera('follow')")
    if rc:
        pg.evaluate('window.__smSession.rcToggle()')
        pg.keyboard.down('w'); pg.keyboard.down('d')
        bekle(lambda: (ss.tele.get('groundspeed') or 0) > 1.5, 30, 'rover hızlanma')
        pg.keyboard.up('d')
        pg.wait_for_timeout(900)
    shot(pg, ad)
    if rc:
        pg.keyboard.up('w')
    if modes:
        pg.keyboard.press('f'); pg.wait_for_timeout(800)
        shot(pg, 'simumav-07-modes.png')
        flt = pg.evaluate("[...document.querySelectorAll('.fs-flt-pop button')].map(b => b.textContent.trim())")
        print('  mod seçici:', flt, flush=True)
        if 'HOLD' not in flt or 'MANUAL' not in flt or 'LAND' in flt:
            hatalar.append(f'mod seçici: {flt}')
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
    info = pg.evaluate("(() => { const s = window.__smSession; const m = s.sim.modelInfo || {}; return { type: m.type, drive: s.session.drive, ground: s.session.ground, hold: !!document.querySelector('.fs-hold-btn'), takeoff: !!document.querySelector('.fs-takeoff-btn'), stickL: document.querySelector('.fs-stick[data-side=l] small')?.textContent, gauge: document.querySelector('.fs-speed-gauge')?.dataset.max }; })()")
    print('  oturum:', info, flush=True)
    if info.get('takeoff') or not info.get('hold'):
        hatalar.append(f'alt çubuk: kalkış düğmesi {info.get("takeoff")}, dur {info.get("hold")}')
    s.post(f'{BASE}/api/fly/{fid}/stop', json={}, headers=H)


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
        pg.on('response', lambda r: hatalar.append(f'HTTP {r.status} {r.url[len(BASE):][:120]}') if r.status >= 400 else None)
        # ---- 01 hangar
        pg.goto(f'{BASE}/app/#/hangar', wait_until='domcontentloaded')
        pg.wait_for_selector('.strip .strip-card', timeout=60000)
        pg.wait_for_timeout(7000)
        shot(pg, 'simumav-01-hangar.png')
        # ---- 02 yeni araç: tür seçici → Kara Aracı (fpv'den iki sağ)
        pg.click('.strip .plus-btn')
        pg.wait_for_selector('.hsel-item', timeout=30000)
        pg.wait_for_timeout(1500)
        for _ in range(2):
            pg.click('.hsel-arrow.r'); pg.wait_for_timeout(600)
        pg.wait_for_timeout(4000)
        shot(pg, 'simumav-02-hangar-type.png')
        pg.click('.btn-row .btn.primary'); pg.wait_for_timeout(5000)
        shot(pg, 'simumav-03-hangar-models.png')
        # ---- 04 Uç sihirbazı: dron adımı (varsayılan Keşif-1)
        pg.goto(f'{BASE}/app/#/fly', wait_until='domcontentloaded')
        pg.wait_for_selector('.sm-wizard .sm-cards-drones', timeout=60000)
        pg.wait_for_selector('.sm-cards-drive', timeout=30000)
        pg.wait_for_timeout(9000)
        shot(pg, 'simumav-04-wizard-drone.png')
        steps = pg.evaluate("[...document.querySelectorAll('.sm-steps .sm-step span')].map(e => e.textContent)")
        print('  sihirbaz adımları:', steps)
        if any('Kalkış' in x for x in steps):
            hatalar.append(f'kalkış adımı görünüyor: {steps}')
        # ---- 05 güç adımı (drone → track → power)
        for _ in range(2):
            pg.click('.sm-nav-btn.primary'); pg.wait_for_timeout(600)
        pg.wait_for_selector('.sm-pw', timeout=20000); pg.wait_for_timeout(800)
        shot(pg, 'simumav-05-wizard-power.png')
        # ---- 06/07 uçuş: Keşif 4×4 (Ackermann) · 08 paletli UGV
        ucus(pg, d4, 'simumav-06-fly-4x4.png', modes=True)
        ucus(pg, dugv, 'simumav-08-fly-ugv.png')
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / 'simumav-hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(1.0)
