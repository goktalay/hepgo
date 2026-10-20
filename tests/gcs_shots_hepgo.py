"""HEPGO Uçuş Simülatörü §26 (yer kontrol sahası + EO/radar kulesi + "Yer kontrolünü koru") — görsel doğrulama (Playwright headless shell + SwiftShader).
Uygulama aynı süreçte açılır; GCS_REAL=1 + HEPGO_SITL_DIR → gerçek ArduPilot SITL (INTERCEPTOR tailsitter), aksi sahte kinematik.
Görüntüler /tmp/gcs-shots/hepgo-*.png:
  01 sihirbaz: Radar / İstasyon / EO kartları + menziller + şematik + "Yer kontrolünü koru" parametreleri
  02 sahne: istasyon, kule (radar anteni + EO başlığı), interceptor rafı (serbest kamera)  · 02b termal kamerada saha (ılık)
  03 uçuş: sol altta radar + EO ekranları, görev şeridi, tehditler  · 04 radar tıklamasıyla hedef seçimi → EO izler
  05 EO termal  · 06 görev olayı (önleme/sızma bandı)  · 07 görev sonu raporu  · 08 Bitir → özet raporda görev bölümü  · 09 kayıttan oynatma (rapor kartı)
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            ./.venv/bin/python -m tests.gcs_shots_hepgo        (gerçek SITL: GCS_REAL=1 HEPGO_SITL_DIR=/opt/hepgo/sitl/bin)
"""
import math
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
REAL = os.environ.get('GCS_REAL') == '1'
DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/gcs-shots-hepgo-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1' if REAL else '0', SIM_UDP_BASE='39450', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8847)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/gcs-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
ONLY = set(filter(None, os.environ.get('GCS_ONLY', '').split(',')))

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
        time.sleep(0.25)
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
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.on('response', lambda r: hatalar.append(f'HTTP {r.status} {r.url[len(BASE):][:120]}') if r.status >= 400 and '/thumb' not in r.url else None)
        # ---- 01 sihirbaz
        if not ONLY or '01' in ONLY:
            pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
            pg.wait_for_selector('.fs-wizard .fs-types', timeout=60000)
            pg.wait_for_timeout(3000)
            pg.locator('.fs-type', has_text='INTERCEPTOR').first.click(); pg.wait_for_timeout(600)
            pg.evaluate("window.__fsWz.goto('site')"); pg.wait_for_timeout(300)   # §6 adım adım sihirbaz: Yer kontrol adımı
            for k in ('radar', 'station', 'eo'):
                card = pg.locator(f'.fs-site-card[data-key="{k}"]')
                if 'on' not in (card.get_attribute('class') or ''):
                    card.click(); pg.wait_for_timeout(150)
            pg.locator('.fs-site-scn .fs-site-card').nth(1).click(); pg.wait_for_timeout(300)
            pg.evaluate("document.querySelector('.fs-site-step').scrollIntoView({block: 'start'})")
            pg.wait_for_timeout(1200)
            shot(pg, 'hepgo-01-wizard-site.png')
            pg.keyboard.press('Escape'); pg.wait_for_timeout(500)
        # ---- oturum (API): INTERCEPTOR + saha + görev
        body = {'mode': 'sitl', 'type': 'interceptor', 'center_id': c['id'], 'rec': {'bin': REAL},
                'world': {'mode': 'procedural', 'seed': 11, 'size_m': 6000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.25, 'building_count': 30, 'runway_heading': 20},
                'site': {'station': True, 'radar': True, 'radar_km': 20, 'eo': True, 'eo_km': 5},
                'defend': {'seed': 4242, 'waves': 2, 'prep_s': 20, 'radius_m': 100, 'difficulty': 'easy', 'interceptors': 10}}
        r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
        assert r.status_code == 201, r.text
        sid = r.json()['id']
        ss = flightsim.MANAGER.sessions[sid]
        bekle(lambda: ss.state == 'HAZIR' and (ss.sahte is not None or ss._heartbeat_alindi), 120, 'HAZIR')
        pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
        pg.wait_for_function('() => window.__fsSim && window.__fsSim.siteInfo && window.__fsSim.siteInfo() && window.__fsSim.siteInfo().rackN === 10', timeout=240000)
        pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")   # KVKK konum izni penceresi
        pg.wait_for_timeout(2500)
        print('  saha:', pg.evaluate('window.__fsSim.siteInfo()'), flush=True)
        # ---- 02 sahne: serbest kamera sahaya bakar (istasyon + kule + raf)
        st = pg.evaluate('window.__fsSim.siteInfo().station')
        tw = pg.evaluate('window.__fsSim.siteInfo().tower')

        def bak(cam, hedef):
            dx, dy, dz = hedef[0] - cam[0], hedef[1] - cam[1], hedef[2] - cam[2]
            yaw = math.degrees(math.atan2(-dx, dy)); pitch = math.degrees(math.asin(dz / math.sqrt(dx * dx + dy * dy + dz * dz)))
            pg.evaluate(f"window.__fsSim.setFreeView({cam[0]}, {cam[1]}, {cam[2]}, {yaw}, {pitch})")
        hx, hy = (st[0] + tw[0]) / 2, (st[1] + tw[1]) / 2
        bak((hx - 22, hy - 58, st[2] + 34), (hx - 2, hy + 4, st[2] + 2))
        pg.wait_for_timeout(4000)
        shot(pg, 'hepgo-02-scene-site.png')
        pg.evaluate("window.__fsSim.setCamType('thermal')")
        pg.evaluate("window.__fsSim.setCamera('fpv')"); pg.wait_for_timeout(300)
        pg.evaluate("window.__fsSim.setCamera('free')")
        bak((hx - 22, hy - 58, st[2] + 34), (hx - 2, hy + 4, st[2] + 2))
        pg.wait_for_timeout(1500)
        pg.evaluate("window.__fsSim.setCamType('day')")
        # ---- uçuş: kalkış + hızlandırma
        cmd(sid, 'takeoff', {'alt': 70})
        cmd(sid, 'speed', {'factor': 2})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 60, 120, 'kalkış 70 m')
        pg.evaluate("window.__fsSim.setCamera('follow')")
        bekle(lambda: ss.savunma.durum()['spawned'] >= 1, 120, 'tehdit doğuşu')
        pg.wait_for_timeout(2500)
        print('  radar:', pg.evaluate('JSON.stringify(window.__fsSim.radarInfo() && {r: window.__fsSim.radarInfo().range_m, n: window.__fsSim.radarInfo().items.length})'), flush=True)
        shot(pg, 'hepgo-03-flight-radar-eo.png')
        # ---- 04 radar tıklaması → seçim → EO izler
        items = pg.evaluate('(window.__fsSim.radarInfo()?.items || [])')
        if items:
            it = items[0]
            bb = pg.locator('.fs-site-scr.radar .fs-site-bd').bounding_box()
            pg.mouse.click(bb['x'] + it['x'], bb['y'] + it['y'])
            pg.wait_for_timeout(300)
            print('  kilit:', pg.evaluate('window.__fsSim.targetLock'), flush=True)
            bekle(lambda: (pg.evaluate('window.__fsSim.eoInfo()?.status') in ('track', 'out')) and not pg.evaluate('window.__fsSim.eoInfo()?.slewing'), 40, 'EO izleme')
            pg.wait_for_timeout(1500)
            print('  eo:', pg.evaluate('window.__fsSim.eoInfo()'), flush=True)
            shot(pg, 'hepgo-04-radar-select-eo-track.png')
            pg.evaluate("window.__fsSim.setEoType('thermal')"); pg.wait_for_timeout(2000)
            shot(pg, 'hepgo-05-eo-thermal.png')
            pg.evaluate("window.__fsSim.setEoType('day')")
        else:
            hatalar.append('radar: kapsamada hedef yok')
        # gimbal kamerasında HUD + dok
        pg.evaluate("window.__fsSim.setCamera('fpv'); window.__fsSim.setGimbal(-5)"); pg.wait_for_timeout(2500)
        shot(pg, 'hepgo-05b-gimbal-dock.png')
        pg.evaluate("window.__fsSim.setCamera('follow')")
        # ---- 06 görev olayı (önleme ya da sızma)
        n0 = len(ss.savunma.kills) + len(ss.savunma.leaks)
        if bekle(lambda: len(ss.savunma.kills) + len(ss.savunma.leaks) > n0, 240, 'görev olayı'):
            pg.wait_for_timeout(500)
            shot(pg, 'hepgo-06-event-banner.png')
        # ---- 07 görev sonu raporu
        cmd(sid, 'speed', {'factor': 4})
        if bekle(lambda: ss.savunma.bitti is not None, 400, 'görev sonu'):
            pg.wait_for_selector('.fs-def-rp', timeout=30000)
            pg.wait_for_timeout(1200)
            shot(pg, 'hepgo-07-mission-report.png')
            print('  sonuç:', {k: ss.savunma.ozet()[k] for k in ('score', 'rank', 'accuracy', 'health', 'spawned')}, flush=True)
            pg.locator('.modal .btn', has_text='Devam').first.click(); pg.wait_for_timeout(500)
        # ---- 08 Bitir → özet raporu (görev bölümü)
        pg.locator('.fs-bar .btn.danger', has_text='Bitir').click()
        pg.wait_for_timeout(400)
        pg.locator('.modal .btn', has_text='Bitir').last.click()
        pg.wait_for_selector('.fs-rp-defend', timeout=60000)
        pg.wait_for_timeout(1000)
        pg.evaluate("document.querySelector('.fs-rp-defend').scrollIntoView({block: 'start'})")
        pg.wait_for_timeout(600)
        shot(pg, 'hepgo-08-summary-defend.png')
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
    time.sleep(6.0)
