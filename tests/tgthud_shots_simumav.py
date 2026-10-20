"""SIMUMAV — HEPGO §24.4 hedef 3B önizlemesi + §24.5 F-16 tarzı hedef sembolojisi (docs/simumav.md §11) — görsel doğrulama (Playwright headless shell +
SwiftShader; sahte SITL). Sunucu aynı süreçte iş parçacığı olarak açılır (arka plan süreci bırakılmaz). Görüntüler /tmp/tgthud-shots/sm-*.png:
  01 HEDEFLER adımı: kartlarda dönen 3B model (tek stüdyo bağlamı) · 02 gimbal HUD: prizmalar + TD kutusu + TLL · 03 FPV OSD · 04 ekran dışı kilit (ok + açı)
  05 termal · 06 önleme anı (ÖNLEME yanıp söner)
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            ./.venv/bin/python -m tests.tgthud_shots_simumav
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/tgthud-shots-sm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='25350', SIMUMAV_MAX_FLIGHTS='2',
                  SIMUMAV_MP_PORT_BASE='26400', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='', SIMUMAV_MAX_SPEEDUP='8')
PORT = int(os.environ.get('SHOT_PORT') or 8637)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/tgthud-shots'); OUT.mkdir(parents=True, exist_ok=True)
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


HUD = "(document.querySelector('.fs-mhud')?.__hud?.targets?.() || null)"
OSD = "(document.querySelector('.fs-osd')?.__osd?.targets?.() || null)"
SIMJ = 'window.__smSession.sim'


def kilit(pg, i):
    for _ in range(6):
        if pg.evaluate(f"{SIMJ}.targetLock && {SIMJ}.targetLock.auto === false && {SIMJ}.targetLock.i === {i}"):
            return True
        pg.keyboard.press('Tab'); pg.wait_for_timeout(150)
    return False


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
        # ---- 01 HEDEFLER adımı (drone → track → power → mission → targets) + 3B önizleme
        pg.goto(f'{BASE}/app/#/fly', wait_until='domcontentloaded')
        pg.wait_for_selector('.sm-wizard .sm-cards-drones', timeout=60000)
        pg.wait_for_timeout(4000)
        for _ in range(4):
            pg.click('.sm-nav-btn.primary'); pg.wait_for_timeout(500)
        pg.wait_for_selector('.sm-targets', timeout=20000)
        pg.click('.sm-tg-add'); pg.wait_for_timeout(300); pg.click('.sm-tg-add'); pg.wait_for_timeout(300)
        pg.locator('.sm-tg-card').nth(1).locator('select.sm-tg-model').select_option('tgt:octopus')
        pg.wait_for_function("() => [...document.querySelectorAll('.fs-tgv-size')].filter(e => e.textContent).length >= 2", timeout=120000)
        pg.wait_for_timeout(1500)
        print('  önizleme:', pg.evaluate("[...document.querySelectorAll('.fs-tgv-cap')].map(e => e.textContent)"), '· WebGL tuvali (gizli stüdyo):', pg.evaluate("document.querySelectorAll('canvas.fs3d-canvas').length"), flush=True)
        shot(pg, 'sm-01-wizard-preview.png')
        pg.click('.sm-nav-btn.primary'); pg.wait_for_timeout(800)   # adımdan çık → stüdyo kapanır
        # ---- uçuş (sahte): dron 150 m yarıçaplı daire; Lancet aynı dairede 30 m/s → yakalar
        targets = {'items': [{'model': 'tgt:lancet', 'alt_m': 40, 'diameter_m': 300, 'speed_ms': 30, 'dir': 'cw', 'name': 'Lancet-1'},
                             {'model': 'tgt:octopus', 'alt_m': 70, 'diameter_m': 600, 'east_m': 200, 'north_m': 150, 'speed_ms': 50, 'dir': 'ccw', 'name': 'Octopus-1'},
                             {'model': 'tgt:altius', 'alt_m': 55, 'diameter_m': 400, 'east_m': -250, 'north_m': -100, 'dir': 'cw', 'name': 'Altius-1'}], 'radius_m': 25}
        f = s.post(f'{BASE}/api/fly/start', json={'drone_id': d['id'], 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False}, 'targets': targets}, headers=H)
        assert f.status_code == 201, f.text
        fid, sid = f.json()['flight_id'], f.json()['sim_id']
        ss = flightsim.MANAGER.sessions[sid]
        pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
        pg.goto(f'{BASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
        pg.wait_for_function('() => window.__smSession && window.__smSession.sim && window.__smSession.sim.targetsInfo().length === 3', timeout=240000)
        bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40}}, headers=H)
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 39 and (ss.tele.get('groundspeed') or 0) > 5, 60, 'kalkış + daire')
        # ---- 02 gimbal HUD
        pg.evaluate(f"{SIMJ}.setCamera('fpv'); {SIMJ}.setGimbal(8)"); pg.wait_for_timeout(3500)
        print('  HUD:', pg.evaluate(HUD), flush=True)
        on = pg.evaluate(f"({HUD}?.items || []).filter(r => r.on).map(r => r.i)")
        if on:
            kilit(pg, on[0]); pg.wait_for_timeout(1200)
        shot(pg, 'sm-02-gimbal-symbology.png')
        # ---- 03 FPV OSD
        pg.evaluate(f"{SIMJ}.setCamera('pilot')"); pg.wait_for_timeout(3500)
        print('  OSD:', pg.evaluate(OSD), flush=True)
        shot(pg, 'sm-03-fpv-symbology.png')
        # ---- 04 ekran dışı kilit
        pg.evaluate(f"{SIMJ}.setCamera('fpv')"); pg.wait_for_timeout(1500)
        off = pg.evaluate(f"({HUD}?.items || []).filter(r => !r.on).map(r => r.i)")
        if off:
            kilit(pg, off[-1]); pg.wait_for_timeout(1500)
            shot(pg, 'sm-04-offscreen-arrow.png')
        else:
            hatalar.append('ekran dışı hedef yok')
        # ---- 05 termal
        pg.evaluate(f"{SIMJ}.setCamType('thermal')"); pg.wait_for_timeout(3000)
        shot(pg, 'sm-05-thermal-symbology.png')
        pg.evaluate(f"{SIMJ}.setCamType('day')")
        # ---- 06 önleme (Lancet-1 dronu yakalar; hız ×4)
        kilit(pg, 0)
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'speed', 'params': {'factor': 4}}, headers=H)
        if bekle(lambda: pg.evaluate(f"({HUD}?.items || []).some(r => r.i === 0 && r.hot)"), 120, 'önleme (HUD)'):
            pg.wait_for_timeout(150)
            print('  önleme HUD:', pg.evaluate(HUD), flush=True)
            shot(pg, 'sm-06-intercept-gimbal.png')
        print('  önleme özeti:', ss.hedef_iz.ozet()['total'], flush=True)
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
