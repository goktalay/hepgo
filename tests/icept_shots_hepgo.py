"""HEPGO Uçuş Simülatörü §25 INTERCEPTOR + §24 hedefler — görsel doğrulama (Playwright headless shell + SwiftShader). Uygulama aynı süreçte
(iş parçacığı) açılır; ICEPT_REAL=1 + HEPGO_SITL_DIR → gerçek ArduPilot SITL (kapanışta lifespan oturumları/SITL'leri kapatır), aksi sahte kinematik.
Görüntüler /tmp/icept-shots/hepgo-*.png:
  01 sihirbaz INTERCEPTOR kartı + model kataloğu · 02 Hedefler bölümü · 03 dikey kalkış (takip; burun yukarı, hedefler + radar) · 04 askıda gimbal kamerası
  05 önleme olayı (şerit + halka) · 06 yatay uçuş (takip) · 07 özet rapor (hedefler bölümü)
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            ICEPT_REAL=1 HEPGO_SITL_DIR=/opt/hepgo/sitl/bin ./.venv/bin/python -m tests.icept_shots_hepgo
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
REAL = os.environ.get('ICEPT_REAL') == '1'
DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/icept-shots-hepgo-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1' if REAL else '0', SIM_UDP_BASE='39150', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8815)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/icept-shots'); OUT.mkdir(parents=True, exist_ok=True)
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


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(150000)   # yazılım WebGL: önizleme + hedef modelleri yavaş çizilir
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.on('response', lambda r: hatalar.append(f'HTTP {r.status} {r.url[len(BASE):][:120]}') if r.status >= 400 and '/thumb' not in r.url else None)
        # ---- 01 sihirbaz: INTERCEPTOR kartı + model kataloğu
        pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-wizard .fs-types', timeout=60000)
        pg.locator('.fs-type', has_text='INTERCEPTOR').first.click()
        pg.wait_for_timeout(9000)   # model kartları + önizleme (yazılım WebGL)
        pg.locator('.fs-model-step').first.scroll_into_view_if_needed()
        pg.evaluate("document.querySelector('.fs-types').scrollIntoView({block: 'start'})")
        pg.wait_for_timeout(1500)
        shot(pg, 'hepgo-01-wizard-interceptor.png')
        # ---- 02 Hedefler bölümü: 2 hedef (Lancet + Octopus) — §6 adım adım sihirbaz: Hedefler adımına atla
        pg.evaluate("window.__fsWz.goto('targets')"); pg.wait_for_timeout(300)
        pg.locator('.fs-tg-add').click(); pg.wait_for_timeout(300)
        pg.locator('.fs-tg-add').click(); pg.wait_for_timeout(300)
        pg.locator('.fs-tg-card').nth(1).locator('select.fs-tg-model').select_option('tgt:octopus')
        pg.wait_for_timeout(500)
        pg.evaluate("document.querySelector('.fs-targets').scrollIntoView({block: 'start'})")
        pg.wait_for_timeout(1200)
        shot(pg, 'hepgo-02-wizard-targets.png')
        # ---- oturum (API; hedefler: biri uçuş merkezinin üstünden geçen dar yörünge → askıdayken önleme)
        targets = {'items': [{'model': 'tgt:lancet', 'alt_m': 60, 'diameter_m': 100, 'east_m': 50, 'north_m': 0, 'speed_ms': 18, 'dir': 'cw', 'name': 'Lancet-1'},
                             {'model': 'tgt:octopus', 'alt_m': 90, 'diameter_m': 500, 'east_m': -150, 'north_m': 150, 'speed_ms': 40, 'dir': 'ccw', 'name': 'Octopus-1'},
                             {'model': 'tgt:sw300', 'alt_m': 70, 'diameter_m': 300, 'east_m': 200, 'north_m': -120, 'dir': 'cw', 'name': 'SW300-1'}], 'radius_m': 25}
        r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'sitl', 'type': 'interceptor', 'center_id': c['id'], 'rec': {'bin': REAL},
                                                           'world': {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.25, 'building_count': 30},
                                                           'targets': targets})
        assert r.status_code == 201, r.text
        sid = r.json()['id']
        ss = flightsim.MANAGER.sessions[sid]
        bekle(lambda: ss.state == 'HAZIR' and (ss.sahte is not None or ss._heartbeat_alindi), 120, 'HAZIR')
        pg.keyboard.press('Escape'); pg.wait_for_timeout(500)
        pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
        pg.wait_for_function('() => window.__fsSim && window.__fsSim.targetsInfo().length === 3', timeout=240000)
        if REAL:
            time.sleep(20)   # EKF/GPS otursun
        cmd(sid, 'takeoff', {'alt': 60})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 25, 90, 'dikey tırmanış')
        pg.evaluate("window.__fsSim.setCamera('follow')"); pg.wait_for_timeout(3500)
        print('  gövde:', pg.evaluate('window.__fsSim.getBodyPose()'), 'hedefler:', pg.evaluate('window.__fsSim.targetsInfo()'), flush=True)
        shot(pg, 'hepgo-03-vertical-climb.png')
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 55, 60, 'askı irtifası')
        pg.evaluate("window.__fsSim.setCamera('fpv')"); pg.wait_for_timeout(3500)
        shot(pg, 'hepgo-04-hover-gimbal.png')
        pg.evaluate("window.__fsSim.setCamera('follow')")
        # ---- 05 önleme (Lancet-1 yörüngesi askı noktasının üstünden geçer)
        bekle(lambda: ss.hedef_iz.ozet()['total'] >= 1, 120, 'önleme')
        pg.wait_for_timeout(1800)
        shot(pg, 'hepgo-05-intercept.png')
        # ---- 06 yatay uçuş (CRUISE, gaz %100)
        cmd(sid, 'mode', {'mode': 'CRUISE'})
        t0 = time.time()
        while time.time() - t0 < 25:
            cmd(sid, 'rc', {'ch': [1500, 1500, 2000, 1500, 0, 0, 0, 0]}); time.sleep(1)
        print('  yatay:', {k: ss.tele.get(k) for k in ('groundspeed', 'alt_rel', 'mode', 'att_body')}, flush=True)
        pg.evaluate("window.__fsSim.snapCamera()"); pg.wait_for_timeout(3000)
        shot(pg, 'hepgo-06-level-flight.png')
        cmd(sid, 'rc', {'ch': [0] * 8})
        # ---- 07 rapor (Bitir → onay → özet rapor modalı)
        pg.locator('button.btn.sm.danger', has_text='Bitir').first.click(); pg.wait_for_timeout(600)
        pg.locator('.modal-foot .btn.danger').last.click()
        pg.wait_for_selector('.fs-rp-targets', timeout=120000)
        pg.evaluate("document.querySelector('.fs-rp-targets').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(1200)
        shot(pg, 'hepgo-07-report.png')
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
    time.sleep(8.0)   # lifespan: oturumlar + SITL kapanır
