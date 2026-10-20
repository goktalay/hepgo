"""SIMUMAV yer kontrol sahası + "Yer kontrolünü koru" (HEPGO §26; docs/simumav.md §12) — görsel doğrulama (Playwright headless shell + SwiftShader; sahte SITL).
Sunucu aynı süreçte iş parçacığı olarak açılır (arka plan süreci bırakılmaz). Görüntüler /tmp/gcs-shots/sm-*.png:
  01 sihirbaz "Yer kontrol" adımı · 02 Görevler: "Yer kontrolünü koru" kartı · 02b görev editörü (savunma parametreleri)
  03 uçuş: sol altta radar + EO, görev şeridi · 04 radar tıklaması → EO takibi · 05 görev sonu raporu · 06 uçuş sonu raporu (görev kartı) · 07 Operasyon replay
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            ./.venv/bin/python -m tests.gcs_shots_simumav            (dil: GCS_LANG=en)
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/gcs-shots-sm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='25350', SIMUMAV_MAX_FLIGHTS='2',
                  SIMUMAV_MP_PORT_BASE='26300', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='', SIMUMAV_MAX_SPEEDUP='8')
PORT = int(os.environ.get('SHOT_PORT') or 8627)
BASE = f'http://127.0.0.1:{PORT}'
LANG = os.environ.get('GCS_LANG', 'tr')
OUT = pathlib.Path('/tmp/gcs-shots'); OUT.mkdir(parents=True, exist_ok=True)
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
tr = s.post(f'{BASE}/api/tracks', json={'name': 'Savunma Sahası', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural',
                                        'world': {'seed': 21, 'runway': True, 'tree_density': 0.2, 'building_count': 20, 'runway_deg': 30}}, headers=H).json()
s.put(f"{BASE}/api/tracks/{tr['id']}", json={'is_default': True}, headers=H)
mis = s.post(f'{BASE}/api/missions', json={'track_id': tr['id'], 'name': 'Üs savunması', 'kind': 'defend',
                                           'plan': {'kind': 'defend', 'defend': {'seed': 4242, 'waves': 2, 'difficulty': 'easy', 'prep_s': 20, 'radius_m': 100, 'interceptors': 10}}}, headers=H).json()
hatalar = []


def bekle(pred, sec, ad):
    t0 = time.time()
    while time.time() - t0 < sec:
        if pred():
            return True
        time.sleep(0.25)
    hatalar.append(f'{ad}: {sec} sn içinde olmadı'); return False


def shot(pg, ad, **kw):
    pg.screenshot(path=str(OUT / ad), **kw)
    print('  kare', ad, flush=True)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': 'smsid', 'value': tok, 'url': BASE}])
        ctx.add_init_script(f"try {{ localStorage.setItem('sm:lang', '{LANG}'); localStorage.setItem('simumav.consent', 'denied'); }} catch (e) {{}}")
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.on('response', lambda r: hatalar.append(f'HTTP {r.status} {r.url[len(BASE):][:120]}') if r.status >= 400 else None)
        # ---- 01 sihirbaz: drone → track → power → mission → site
        pg.goto(f'{BASE}/app/#/fly', wait_until='domcontentloaded')
        pg.wait_for_selector('.sm-wizard .sm-cards-drones', timeout=60000)
        pg.wait_for_timeout(3000)
        for _ in range(4):
            pg.click('.sm-nav-btn.primary'); pg.wait_for_timeout(500)
        pg.wait_for_selector('.fs-site-wiz', timeout=20000)
        for k in ('radar', 'station', 'eo'):
            card = pg.locator(f'.fs-site-card[data-key="{k}"]')
            if 'on' not in (card.get_attribute('class') or ''):
                card.click(); pg.wait_for_timeout(150)
        pg.locator('.fs-site-scn .fs-site-card').nth(1).click(); pg.wait_for_timeout(500)
        shot(pg, 'sm-01-wizard-site.png')
        # ---- 02 Görevler: savunma kartı + editör
        pg.goto(f'{BASE}/app/#/missions', wait_until='domcontentloaded')
        pg.wait_for_selector('.mission-card', timeout=30000); pg.wait_for_timeout(1500)
        shot(pg, 'sm-02-missions-defend.png')
        pg.locator('.mission-card').first.click()
        pg.wait_for_selector('.mission-editor .side-panel', timeout=60000); pg.wait_for_timeout(4000)
        shot(pg, 'sm-02b-mission-editor.png')
        # ---- uçuş: savunma görevi + saha
        f = s.post(f'{BASE}/api/fly/start', json={'drone_id': d['id'], 'pilot_id': pid, 'track_id': tr['id'], 'mission_id': mis['id'], 'record': {'bin': False},
                                                  'site': {'station': True, 'radar': True, 'radar_km': 20, 'eo': True, 'eo_km': 5}}, headers=H)
        assert f.status_code == 201, f.text
        fid, sid = f.json()['flight_id'], f.json()['sim_id']
        ss = flightsim.MANAGER.sessions[sid]
        pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
        pg.goto(f'{BASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
        pg.wait_for_function('() => window.__smSession && window.__smSession.sim && window.__smSession.sim.siteInfo() && window.__smSession.sim.siteInfo().rackN === 10', timeout=240000)
        bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 70}}, headers=H)
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'speed', 'params': {'factor': 2}}, headers=H)
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 60, 90, 'kalkış')
        pg.evaluate("window.__smSession.sim.setCamera('follow')")
        bekle(lambda: ss.savunma.durum()['spawned'] >= 1, 120, 'tehdit doğuşu')
        pg.wait_for_timeout(3000)
        shot(pg, 'sm-03-fly-radar-eo.png')
        items = pg.evaluate('(window.__smSession.sim.radarInfo()?.items || [])')
        if items:
            it = items[0]
            bb = pg.locator('.fs-site-scr.radar .fs-site-bd').bounding_box()
            pg.mouse.click(bb['x'] + it['x'], bb['y'] + it['y'])
            bekle(lambda: pg.evaluate('window.__smSession.sim.eoInfo()?.status') in ('track', 'out') and not pg.evaluate('window.__smSession.sim.eoInfo()?.slewing'), 40, 'EO izleme')
            pg.wait_for_timeout(1500)
            print('  eo:', pg.evaluate('window.__smSession.sim.eoInfo()'), flush=True)
            shot(pg, 'sm-04-eo-track.png')
        else:
            hatalar.append('radar: hedef yok')
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'speed', 'params': {'factor': 8}}, headers=H)
        if bekle(lambda: ss.savunma.bitti is not None, 400, 'görev sonu'):
            pg.wait_for_selector('.fs-def-rp', timeout=40000); pg.wait_for_timeout(2500)
            shot(pg, 'sm-05-mission-report.png', animations='disabled')
            pg.locator('.modal-foot .btn').first.click(); pg.wait_for_timeout(600)
        pg.click('.fs-end-btn'); pg.wait_for_timeout(500)
        pg.click('.modal-foot .btn.danger, .modal-foot .btn.primary')
        pg.wait_for_selector('.sm-def-card', timeout=90000)
        pg.wait_for_timeout(3500)
        pg.evaluate("document.querySelector('.sm-def-card').scrollIntoView({block: 'start'})"); pg.wait_for_timeout(600)
        shot(pg, 'sm-06-flight-report.png', animations='disabled')
        pg.goto(f'{BASE}/app/#/ops/{fid}', wait_until='domcontentloaded')
        pg.wait_for_selector('.replay-defend-card', timeout=60000); pg.wait_for_timeout(4000)
        shot(pg, 'sm-07-ops-replay.png')
        print('  __smGl:', pg.evaluate('window.__smGl ?? null'), flush=True)
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
