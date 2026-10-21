"""HEPGO Uçuş Simülatörü uçuş arayüzü — görsel doğrulama (Playwright headless shell + SwiftShader; sahte kinematik, SITL yok).
§27.2 giriş sekansı (100 m bakış + 3-2-1), §27.1 kumanda hassasiyeti paneli, §27.4 radar/EO pencereleri taşınmış + büyütülmüş, §27.3 gösterge tasarımları
(5 tema × açık/koyu), sihirbazda gösterge seçimi. Görüntüler /tmp/flyui-shots/hepgo-*.png.
Çalıştırma: ./.venv/bin/python -m tests.flyui_shots_hepgo
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/flyui-shots-hepgo-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39550', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8857)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/flyui-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
ONLY = set(filter(None, os.environ.get('FLYUI_ONLY', '').split(',')))

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
        try:
            if pred():
                return True
        except Exception:   # noqa: BLE001
            pass
        time.sleep(0.2)
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


def grip(pg, sel, dx, dy, steps=12):
    bb = pg.locator(sel).first.bounding_box()
    x, y = bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2
    pg.mouse.move(x, y); pg.mouse.down()
    for i in range(1, steps + 1):
        pg.mouse.move(x + dx * i / steps, y + dy * i / steps); pg.wait_for_timeout(16)
    pg.mouse.up()


def theme(pg, t):
    pg.evaluate(f"document.documentElement.setAttribute('data-theme', '{t}')")


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        # ---- 01 sihirbaz: Kamera adımında gösterge tasarımı kartları (açık + koyu)
        if not ONLY or '01' in ONLY:
            pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
            pg.wait_for_selector('.fs-wizard .fs-types', timeout=60000)
            pg.wait_for_timeout(2500)
            pg.locator('.fs-type', has_text='Sabit kanat').first.click(); pg.wait_for_timeout(500)
            pg.evaluate("window.__fsWz.goto('camera')"); pg.wait_for_timeout(500)
            pg.locator('.fs-gt-card[data-gtheme="cockpit"]').click(); pg.wait_for_timeout(300)
            pg.evaluate("document.querySelector('.fs-gt-wiz').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(600)
            for t in ('light', 'dark'):
                theme(pg, t); pg.evaluate("document.querySelector('.fs-gt-wiz') && window.__fsWz && window.__fsWz.goto('camera')"); pg.wait_for_timeout(500)
                pg.evaluate("document.querySelector('.fs-gt-wiz').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(400)
                shot(pg, f'hepgo-01-wizard-gauge-theme-{t}.png')
            theme(pg, 'light')
            pg.keyboard.press('Escape'); pg.wait_for_timeout(500)
            pg.evaluate("localStorage.setItem('fs.gauge.theme', 'classic')")
        # ---- oturum (API): sabit kanat + saha (radar + EO) + güç
        if ONLY and '01' not in ONLY:
            pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(2000)
        body = {'mode': 'sitl', 'type': 'sabit_kanat', 'center_id': c['id'],
                'world': {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.25, 'building_count': 20, 'runway_heading': 20},
                'site': {'station': True, 'radar': True, 'radar_km': 10, 'eo': True, 'eo_km': 5},
                'power': {'max_speed_ms': 45, 'fuel_l': 5, 'fuel_km_per_l': 25, 'elec_cells': 4, 'elec_mah': 10000, 'elec_w': 30}}
        r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
        assert r.status_code == 201, r.text
        sid = r.json()['id']
        ss = flightsim.MANAGER.sessions[sid]
        bekle(lambda: ss.state == 'HAZIR', 120, 'HAZIR')
        pg.evaluate("localStorage.removeItem('fs.site.win'); localStorage.setItem('fs.site', JSON.stringify({radar: true, eo: true})); window.__fsIntroHold = 0.15")
        pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
        # ---- 02 giriş sekansı: 100 m bakış + 3-2-1 (kareler)
        pg.wait_for_selector('.fs-cd:not([hidden])', timeout=240000)
        pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
        pg.wait_for_timeout(6000)   # karolar / model yerleşsin (sekans 0,15 sn'de tutuluyor)
        for at, ad in ((0.15, 'a-3'), (1.3, 'b-2'), (2.35, 'c-1'), (3.3, 'd-go'), (4.4, 'e-blend')):
            pg.evaluate(f'window.__fsIntroHold = {at}'); pg.wait_for_timeout(2500)
            shot(pg, f'hepgo-02-intro-{ad}.png')
        pg.evaluate('delete window.__fsIntroHold'); pg.wait_for_timeout(3000)
        shot(pg, 'hepgo-02-intro-f-normal.png')
        print('  intro aktif mi:', pg.evaluate('window.__fsSim?.introActive?.()'), flush=True)
        # ---- 03 sanal kumanda + hassasiyet paneli
        cmd = lambda n, pr=None: s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': n, 'params': pr or {}})
        cmd('takeoff', {'alt': 60})
        pg.locator('.fs-bar .btn', has_text='Sanal kumanda').click(); pg.wait_for_timeout(600)
        pg.locator('.fs-rcf-btn').click(); pg.wait_for_timeout(300)
        pg.locator('.fs-rcf-seg button[data-p="soft"]').click(); pg.wait_for_timeout(200)
        pg.locator('.fs-rcf-seg.ax button[data-a="yaw"]').click(); pg.wait_for_timeout(200)
        pg.locator('.fs-rcf-row input').nth(1).fill('55'); pg.locator('.fs-rcf-row input').nth(1).dispatch_event('input'); pg.wait_for_timeout(400)
        shot(pg, 'hepgo-03-rc-feel-panel.png')
        print('  rc feel:', pg.evaluate("localStorage.getItem('fs.rc.feel')")[:120], flush=True)
        pg.locator('.fs-rcf-x').click(); pg.wait_for_timeout(200)
        pg.locator('.fs-bar .btn', has_text='Sanal kumanda').click(); pg.wait_for_timeout(400)
        # ---- 04 radar / EO: taşı + büyüt + köşeye yapış
        bekle(lambda: pg.locator('.fs-site-scr.radar').is_visible(), 30, 'radar ekranı')
        shot(pg, 'hepgo-04a-site-default.png')
        drag(pg, '.fs-site-scr.radar .fs-site-hd', 380, -330)
        pg.wait_for_timeout(400)
        grip(pg, '.fs-site-scr.radar .fs-site-grip', 160, 110)
        pg.wait_for_timeout(400)
        drag(pg, '.fs-site-scr.eo .fs-site-hd', 1300, -40)   # sağ kenara → yapışma + PiP/kadran kaçınma
        pg.wait_for_timeout(1200)
        print('  pencereler:', pg.evaluate("localStorage.getItem('fs.site.win')"), flush=True)
        shot(pg, 'hepgo-04b-site-moved-resized.png')
        # kalıcılık: yeniden yükle
        pg.reload(wait_until='domcontentloaded')
        pg.wait_for_function('() => window.__fsSim && document.querySelector(".fs-site-scr.radar.fs-float")', timeout=240000)
        pg.wait_for_timeout(7000)
        shot(pg, 'hepgo-04c-site-after-reload.png')
        pg.locator('.fs-site-scr.radar .fs-site-rst').click(); pg.wait_for_timeout(800)
        shot(pg, 'hepgo-04d-site-reset.png')
        # ---- 05 gösterge temaları (açık + koyu): kadran bölgesi kırpılmış + tam kare
        pg.wait_for_selector('.fs-gauges:not([hidden])', timeout=60000)
        for t in ('light', 'dark'):
            theme(pg, t)
            for k in ('classic', 'cockpit', 'glass', 'minimal', 'military'):
                pg.evaluate(f"document.querySelector('.fs-gauges').dataset.gtheme = '{k}'"); pg.wait_for_timeout(700)
                bb = pg.locator('.fs-gauges').bounding_box()
                clip = {'x': max(0, bb['x'] - 40), 'y': max(0, bb['y'] - 40), 'width': min(1440, bb['width'] + 80), 'height': min(900 - max(0, bb['y'] - 40), bb['height'] + 70)}
                shot(pg, f'hepgo-05-gauges-{k}-{t}.png', clip)
            shot(pg, f'hepgo-05-full-{t}.png')
        theme(pg, 'light')
        # uçuş içi seçici (kadran kutusu)
        pg.locator('.fs-gauge[data-g="speed"]').click(); pg.wait_for_timeout(400)
        pg.locator('.fs-gt-row button[data-gtheme="glass"]').click(); pg.wait_for_timeout(500)
        shot(pg, 'hepgo-06-gauge-pop-theme-row.png')
        print('  tema:', pg.evaluate("localStorage.getItem('fs.gauge.theme')"), flush=True)
        pg.keyboard.press('g'); pg.wait_for_timeout(200)
        print('  G sonrası:', pg.evaluate("document.querySelector('.fs-gauges').dataset.gtheme"), flush=True)
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
