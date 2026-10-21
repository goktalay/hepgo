"""HEPGO Uçuş Simülatörü §31 KARA ARACI — 3B görsel doğrulama (Playwright headless shell + SwiftShader). Uygulama aynı süreçte (iş parçacığı) açılır;
ROVER_REAL=1 + HEPGO_SITL_DIR → gerçek ArduRover SITL (kapanışta lifespan oturumları/SITL'leri kapatır), aksi sahte kinematik.
Görüntüler /tmp/rover-shots/3d-*.png:
  01 prosedürel dünya, takip (kovalama) kamerası · 02 kokpit (pilot) + kara aracı göstergesi · 03 sensör (gimbal) kamerası · 04 yer kamerası
  05 dönüşte direksiyon (yakın takip) · 06 paletli UGV · 07 teslimat robotu · 08 gerçek arazi (Kapadokya eğimli arazi; zemine oturma, eğim)
  09 Google 3B (anahtar varsa)
Her karede window.__fsSim.roverState() teşhisi yazdırılır (gösterilen z ↔ yüzey, eğim/yatış, teker/direksiyon, kaba örnek sayısı).
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            [ROVER_REAL=1 HEPGO_SITL_DIR=/opt/hepgo/sitl/bin] ./.venv/bin/python -m tests.rover_shots_3d [yalnız=01,02,...]
"""
import json
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
REAL = os.environ.get('ROVER_REAL') == '1'
GKEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/rover-shots-3d-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1' if REAL else '0', SIM_UDP_BASE='39350', SIM_TERRAIN_SERVE='1' if REAL else '0', SIM_MAX_SESSIONS='3')
PORT = int(os.environ.get('SHOT_PORT') or 8847)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/rover-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
SECIM = set(sys.argv[1].split(',')) if len(sys.argv) > 1 else None

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
s.post(f'{BASE}/api/location/consent', json={'granted': False})   # konum izni penceresi kareleri örtmesin
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Test Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
# Erciyes eteği (Kayseri) — binasız eğimli arazi: gerçek arazide zemine oturma ve eğim
c2 = s.post(f'{BASE}/api/drone/centers', json={'name': 'Erciyes eteği', 'lat': 38.5560, 'lon': 35.4600, 'alt': 2100}).json()
hatalar = []


def ister(k):
    return SECIM is None or k in SECIM


def bekle(pred, sec, ad):
    t0 = time.time()
    while time.time() - t0 < sec:
        if pred():
            return True
        time.sleep(0.2)
    hatalar.append(f'{ad}: {sec} sn içinde olmadı'); return False


def cmd(sid, name, params=None):
    r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': name, 'params': params or {}})
    if r.status_code != 200:
        hatalar.append(f'cmd {name} {r.status_code} {r.text[:200]}')
    return r


def surus(sid, steer, thr, sn):
    t0 = time.time()
    while time.time() - t0 < sn:
        cmd(sid, 'rc', {'ch': [int(1500 + steer * 500), 0, int(1500 + thr * 500), 0, 0, 0, 0, 0]}); time.sleep(0.25)


def ac(model, world, center=None, drive=None):
    body = {'mode': 'sitl', 'type': 'rover', 'center_id': (center or c)['id'], 'model': {'id': model}, 'world': world}
    if drive:
        body['drive'] = drive
    r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
    assert r.status_code == 201, r.text
    sid = r.json()['id']
    ss = flightsim.MANAGER.sessions[sid]
    bekle(lambda: ss.state == 'HAZIR' and (ss.sahte is not None or ss._heartbeat_alindi), 150, 'HAZIR')
    return sid, ss


def kapat(sid):
    s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')


def git(pg, sid):
    pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')   # tam yükleme: liste sayfasının geç gelen çizimi oturumu ezmesin
    pg.wait_for_function('() => window.__fsSim && window.__fsSim.roverState && window.__fsSim.roverState()', timeout=240000)
    pg.wait_for_timeout(1500)
    rd = pg.locator('.modal-back button', has_text='Reddet')   # KVKK konum izni penceresi (tam yüklemede) kareyi örtmesin
    if rd.count():
        rd.first.click(); pg.wait_for_timeout(400)


def shot(pg, ad):
    pg.screenshot(path=str(OUT / ad))
    if not pg.evaluate("!!document.querySelector('.fs-stage')"):
        hatalar.append(f'{ad}: oturum sahnesi yok ({pg.url})')
    st = pg.evaluate('window.__fsSim && window.__fsSim.roverState()')
    kisa = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in (st or {}).items() if k in ('shownZ', 'fitZ', 'pitchDeg', 'rollDeg', 'steerDeg', 'speed', 'wheels', 'steers', 'drive', 'samples', 'coarse', 'dust', 'scale')}
    print('  kare', ad, json.dumps(kisa, ensure_ascii=False), flush=True)
    return st


PROC = {'mode': 'procedural', 'seed': 7, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.3, 'building_count': 30, 'mountain_height': 120, 'water': 0}
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        ctx.add_init_script("localStorage.setItem('fs.cam.pip', JSON.stringify({on: false}))")   # kamera PiP'i aracı örtmesin
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('framenavigated', lambda f: print('  gezinme:', f.url[len(BASE):], flush=True) if f == pg.main_frame else None)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300].split("?")[0]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.on('response', lambda r: hatalar.append(f'HTTP {r.status} {r.url[len(BASE):].split("?")[0][:120]}') if r.status >= 400 and '/thumb' not in r.url else None)   # sorgu (anahtar) yazılmaz
        # ---- 4×4 prosedürel dünya
        if any(ister(k) for k in ('01', '02', '03', '04', '05')):
            sid, ss = ac('builtin:rover_4x4', PROC)
            git(pg, sid)
            if REAL:
                time.sleep(15)
            cmd(sid, 'mode', {'mode': 'MANUAL'}); cmd(sid, 'arm'); time.sleep(1.5)
            surus(sid, 0.0, 0.45, 6)
            pg.evaluate("window.__fsSim.setCamera('follow')"); pg.wait_for_timeout(2500)
            if ister('01'):
                shot(pg, '3d-01-follow.png')
            if ister('02'):
                pg.evaluate("window.__fsSim.setCamera('pilot')"); surus(sid, 0.0, 0.4, 3); shot(pg, '3d-02-cockpit.png')
            if ister('03'):
                pg.evaluate("window.__fsSim.setCamera('fpv')"); surus(sid, 0.0, 0.4, 3); shot(pg, '3d-03-gimbal.png')
            if ister('04'):
                pg.evaluate("window.__fsSim.setCamera('ground')"); surus(sid, 0.0, 0.4, 3); shot(pg, '3d-04-ground.png')
            if ister('05'):
                pg.evaluate("window.__fsSim.setPip(false)")
                pg.evaluate("window.__fsSim.setCamera('follow')"); surus(sid, 0.8, 0.35, 4)
                pg.evaluate("window.__fsSim.snapCamera()"); surus(sid, 0.8, 0.35, 1.5); shot(pg, '3d-05-steer.png')
            cmd(sid, 'rc', {'ch': [0] * 8}); kapat(sid); time.sleep(2)
        # ---- paletli UGV + teslimat robotu
        for k, model, ad in (('06', 'builtin:rover_ugv', '3d-06-ugv.png'), ('07', 'builtin:rover_bot', '3d-07-bot.png')):
            if not ister(k):
                continue
            sid, ss = ac(model, PROC)
            git(pg, sid)
            if REAL:
                time.sleep(15)
            cmd(sid, 'mode', {'mode': 'MANUAL'}); cmd(sid, 'arm'); time.sleep(1.5)
            surus(sid, 0.35, 0.6, 5)
            pg.evaluate("window.__fsSim.setCamera('follow')"); pg.evaluate("window.__fsSim.snapCamera()"); surus(sid, 0.35, 0.6, 2.5)
            shot(pg, ad)
            cmd(sid, 'rc', {'ch': [0] * 8}); kapat(sid); time.sleep(2)
        # ---- gerçek arazi (eğim)
        if ister('08'):
            sid, ss = ac('builtin:rover_4x4', {'mode': 'real', 'size_m': 3000, 'time': 'day', 'wind_ms': 0, 'runway': False}, center=c2)
            git(pg, sid)
            pg.wait_for_function('() => window.__fsSim.terrainInfo && window.__fsSim.terrainInfo.real', timeout=240000)
            if REAL:
                time.sleep(15)
            cmd(sid, 'mode', {'mode': 'MANUAL'}); cmd(sid, 'arm'); time.sleep(1.5)
            surus(sid, 0.0, 0.6, 22)
            pg.evaluate("window.__fsSim.setPip(false)")
            pg.evaluate("window.__fsSim.setCamera('follow')"); pg.evaluate("window.__fsSim.snapCamera()"); surus(sid, 0.05, 0.6, 3)
            shot(pg, '3d-08-real-terrain.png')
            pg.evaluate("window.__fsSim.setCamera('pilot')"); surus(sid, 0.1, 0.5, 3); shot(pg, '3d-08b-real-cockpit.png')
            cmd(sid, 'rc', {'ch': [0] * 8}); kapat(sid); time.sleep(2)
        if ister('09') and GKEY:
            sid, ss = ac('builtin:rover_4x4', {'mode': 'google3d', 'time': 'day', 'wind_ms': 0})
            git(pg, sid)
            pg.wait_for_timeout(25000)   # karolar
            cmd(sid, 'mode', {'mode': 'MANUAL'}); cmd(sid, 'arm'); time.sleep(1.5)
            surus(sid, 0.1, 0.35, 6)
            pg.evaluate("window.__fsSim.setCamera('follow')"); pg.evaluate("window.__fsSim.snapCamera()"); surus(sid, 0.1, 0.35, 4)
            shot(pg, '3d-09-google.png')
            cmd(sid, 'rc', {'ch': [0] * 8}); kapat(sid); time.sleep(2)
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / '3d-hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(8.0)   # lifespan: oturumlar + SITL kapanır
