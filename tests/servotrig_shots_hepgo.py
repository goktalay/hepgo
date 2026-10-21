"""HEPGO Uçuş Simülatörü — §34 SERVO TETİK görsel doğrulaması (Playwright headless shell + SwiftShader). Uygulama aynı süreçte; sahte kinematik
(HEPGO_SITL=0; `servo_set` sanal servo çıkışı = Mission Planner DO_SET_SERVO karşılığı) ya da SERVOTRIG_REAL=1 + HEPGO_SITL_DIR → gerçek SITL.
Kareler /tmp/servotrig-shots: alt bant Servo tetik bölümü (boşta / dinlerken canlı PWM + yanıp sönen nokta), tetik bandı (gecikme sürüyor), çarpma
efekti, otomatik Bitir → özet raporu (Servo tetik kartı + harita işaretleri), Simülasyon Kayıtları rozeti.
Çalıştırma: ./.venv/bin/python -m tests.servotrig_shots_hepgo
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
REAL = os.environ.get('SERVOTRIG_REAL') == '1'
DATA = '/tmp/servotrig-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1' if REAL else '0', SIM_UDP_BASE='39750', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8879)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/servotrig-shots'); OUT.mkdir(parents=True, exist_ok=True)
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


def cmd(sid, name, params=None):
    r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': name, 'params': params or {}})
    if r.status_code != 200:
        hatalar.append(f'cmd {name} {r.status_code} {r.text[:200]}')
    return r


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1600, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        body = {'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False},
                'world': {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.3, 'building_count': 20}}
        r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
        assert r.status_code == 201, r.text
        sid = r.json()['id']
        ss = flightsim.MANAGER.sessions[sid]
        bekle(lambda: ss.state == 'HAZIR' and (ss.sahte is not None or ss._heartbeat_alindi), 180, 'HAZIR')
        pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')   # doğrudan yükleme (liste sayfasının 3B önizlemesi de __fsSim kurar)
        pg.wait_for_selector('.fs-bar .fs-srv', timeout=240000)
        pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera', timeout=240000)
        pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
        pg.wait_for_timeout(6000)   # giriş sekansı
        cmd(sid, 'takeoff', {'alt': 60})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 45, 120, 'kalkış')
        cmd(sid, 'servo_set', {'ch': 9, 'pwm': 1500})   # kanal 9 çıkışı 1500 µs (canlı değer görünsün)
        pg.wait_for_timeout(1500)
        shot(pg, '00-start.png')
        print('  DOM:', pg.evaluate("({hash: location.hash, bar: document.querySelectorAll('.fs-bar').length, srv: document.querySelectorAll('.fs-srv').length, modal: [...document.querySelectorAll('.modal')].map(m => m.innerText.slice(0, 120))})"), flush=True)
        bar = pg.locator('.fs-bar').bounding_box()
        srv = pg.locator('.fs-srv').bounding_box()
        print('  servo bölümü:', srv, flush=True)
        shot(pg, '01-bar-idle.png')
        # UI ile ayar: kanal 9, ≥ 1900 µs, 4000 ms (bant görünsün diye uzun) → Dinle
        pg.select_option('.fs-srv-ch', '9')
        pg.select_option('.fs-srv-cmp', 'ge')
        pwm, dly = pg.locator('.fs-srv label input').nth(0), pg.locator('.fs-srv label input').nth(2)
        pwm.fill('1900'); pwm.dispatch_event('change')
        dly.fill('4000'); dly.dispatch_event('change')
        pg.locator('.fs-srv-btn').click()
        bekle(lambda: ss.servo_tetik.phase == 'listening', 10, 'dinleme')
        pg.wait_for_timeout(1200)
        print('  dinleme:', pg.evaluate("({p: document.querySelector('.fs-srv').dataset.phase, live: document.querySelector('.fs-srv-live').textContent, btn: document.querySelector('.fs-srv-btn').textContent, ch: document.querySelector('.fs-srv-ch').selectedOptions[0].textContent})"), flush=True)
        shot(pg, '02-listening.png')
        clip = {'x': max(0, srv['x'] - 20), 'y': bar['y'] - 6, 'width': min(1600 - max(0, srv['x'] - 20), srv['width'] + 40), 'height': bar['height'] + 12}
        shot(pg, '03-bar-servo-zoom.png', clip)
        # canlı PWM: 1700 → bant 1700 µs gösterir (koşul sağlanmadı)
        cmd(sid, 'servo_set', {'ch': 9, 'pwm': 1700}); pg.wait_for_timeout(800)
        live = pg.evaluate("document.querySelector('.fs-srv-live').textContent")
        print('  canlı PWM:', live, flush=True)
        if '1700' not in live:
            hatalar.append(f'canlı PWM güncellenmedi: {live}')
        # Mission Planner DO_SET_SERVO karşılığı → tetik (gecikme sürüyor bandı)
        pg.evaluate('window.__fsCrashHold = 0.35')   # yavaş yazılım WebGL: efekt zamanını sabitle (ateş topu)
        cmd(sid, 'servo_set', {'ch': 9, 'pwm': 1900})
        pg.wait_for_selector('.fs-srv-banner:not([hidden])', timeout=8000)
        pg.wait_for_timeout(500)
        shot(pg, '04-trigger-pending.png')
        pg.wait_for_selector('.fs-crash:not([hidden])', timeout=20000)
        pg.wait_for_timeout(900)
        shot(pg, '05-crash-fx.png')
        print('  tetik:', {k: ss.servo_tetik.trigger.get(k) for k in ('agl', 'dist_home_m', 'tbm')}, 'çarpma:', {k: ss.servo_tetik.hit.get(k) for k in ('agl', 'dist_home_m', 'delay_sim_ms', 'delay_wall_ms')}, flush=True)
        # otomatik Bitir → özet raporu
        pg.wait_for_selector('.fs-rp-servo', timeout=30000)
        pg.evaluate('window.__fsCrashHold = null')
        pg.wait_for_timeout(1500)
        shot(pg, '06-report.png')
        pg.evaluate("document.querySelector('.fs-rp-servo').scrollIntoView({block: 'start'})"); pg.wait_for_timeout(600)
        shot(pg, '07-report-servo-card.png')
        rb = pg.locator('.fs-rp-map').bounding_box()
        pg.evaluate("document.querySelector('.fs-rp-map').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(400)
        rb = pg.locator('.fs-rp-map').bounding_box()
        shot(pg, '08-report-map.png', {'x': rb['x'] - 10, 'y': rb['y'] - 10, 'width': rb['width'] + 20, 'height': rb['height'] + 60})
        txt = pg.evaluate("document.querySelector('.fs-rp-servo').innerText")
        print('  rapor kartı:', txt.replace('\n', ' | ')[:600], flush=True)
        pg.locator('.modal .btn.primary', has_text='Devam').click()
        bekle(lambda: sid not in flightsim.MANAGER.sessions, 40, 'oturum kapanışı')
        pg.wait_for_timeout(3000)
        pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(4000)   # Kayıtlı Simülasyonlar: Serbest uçuş kartı
        kart = pg.locator('.fs-sv-srv')
        print('  uçuş kartı rozeti:', kart.count() and kart.first.text_content(), flush=True)
        if kart.count():
            shot(pg, '09-saved-card-badge.png')
        else:
            hatalar.append('Kayıtlı Simülasyonlar uçuş kartı rozeti yok')
        pg.goto(f'{BASE}/#/drone/sim?tab=runs', wait_until='domcontentloaded'); pg.wait_for_timeout(4000)
        rozet = pg.locator('.fs-runs-srv')
        print('  kayıt rozeti:', rozet.count() and rozet.first.text_content(), flush=True)
        if not rozet.count():
            hatalar.append('Simülasyon Kayıtları rozeti yok')
        else:
            rozet.first.scroll_into_view_if_needed()
            shot(pg, '10-runs-badge.png')
        r = s.get(f'{BASE}/api/drone/sim/runs').json()['items'][0]
        print('  run:', {k: r.get(k) for k in ('result', 'end_reason', 'servo_trig')}, flush=True)
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / 'hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(6.0)
