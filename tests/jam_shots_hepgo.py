"""HEPGO Uçuş Simülatörü — §48 KARIŞTIRMA görsel doğrulaması (Playwright headless shell + SwiftShader). Uygulama aynı süreçte; sahte kinematik
(HEPGO_SITL=0: karıştırma yalnız göstergeleri etkiler) ya da JAM_REAL=1 + HEPGO_SITL_DIR → gerçek SITL.
Kareler /tmp/jam-shots: alt bant Karıştırma düğmesi (boşta), ayar paneli (GPS karıştırma seviyesi, GPS aldatma yön / hız / azami sapma, süre),
sahne bandı (etkinken), panel etkinken (Uygula + Durdur, canlı satır), durdurma, dar ekran, Bitir → özet raporu Karıştırma kartı.
Çalıştırma: ./.venv/bin/python -m tests.jam_shots_hepgo
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
REAL = os.environ.get('JAM_REAL') == '1'
DATA = '/tmp/jam-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1' if REAL else '0', SIM_UDP_BASE='39850', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8881)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/jam-shots'); OUT.mkdir(parents=True, exist_ok=True)
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


def tasma(pg, sel):
    """Öğe görünüm alanının dışına taşıyor mu (px)."""
    return pg.evaluate("""sel => { const r = document.querySelector(sel).getBoundingClientRect();
      return { l: Math.round(r.left), t: Math.round(r.top), r: Math.round(innerWidth - r.right), b: Math.round(innerHeight - r.bottom), w: Math.round(r.width), h: Math.round(r.height) }; }""", sel)


def doldur(pg, sel, v):
    el = pg.locator(sel)
    el.fill(str(v)); el.dispatch_event('change')


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
        print('  oturum jam:', r.json().get('jam'), flush=True)
        ss = flightsim.MANAGER.sessions[sid]
        bekle(lambda: ss.state == 'HAZIR' and (ss.sahte is not None or ss._heartbeat_alindi), 180, 'HAZIR')
        pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-bar .fs-jam', timeout=240000)
        pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera', timeout=240000)
        pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
        pg.wait_for_timeout(6000)   # giriş sekansı
        cmd(sid, 'takeoff', {'alt': 60})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 45, 120, 'kalkış')
        pg.wait_for_timeout(1500)
        shot(pg, '00-bar-idle.png')
        bar = pg.locator('.fs-bar').bounding_box()
        jb = pg.locator('.fs-jam').bounding_box()
        print('  düğme:', jb, pg.evaluate("({txt: document.querySelector('.fs-jam-btn').innerText, title: document.querySelector('.fs-jam-btn').title, st: document.querySelector('.fs-jam').dataset.state})"), flush=True)
        shot(pg, '01-bar-zoom.png', {'x': max(0, jb['x'] - 260), 'y': bar['y'] - 6, 'width': min(1600 - max(0, jb['x'] - 260), jb['width'] + 520), 'height': bar['height'] + 12})
        # panel
        pg.locator('.fs-jam-btn').click()
        pg.wait_for_selector('.fs-jam-pop:not([hidden])', timeout=5000)
        pg.wait_for_timeout(400)
        print('  panel:', tasma(pg, '.fs-jam-pop'), flush=True)
        shot(pg, '02-panel-default.png')
        pb = pg.locator('.fs-jam-pop').bounding_box()
        klip = {'x': max(0, pb['x'] - 16), 'y': max(0, pb['y'] - 16), 'width': pb['width'] + 32, 'height': min(900 - max(0, pb['y'] - 16), pb['height'] + 90)}
        shot(pg, '03-panel-zoom.png', klip)
        # boş ayarla Başlat → uyarı olayı
        pg.locator('.fs-jam-start').click(); pg.wait_for_timeout(500)
        if ss.jam.on:
            hatalar.append('boş ayarla karıştırma açıldı')
        # ağır + aldatma (yön 135°, 3 m/s, 150 m), 120 sn
        pg.locator('.fs-jam-seg button[data-v=heavy]').click()
        pg.locator('.fs-jam-spoof').check()
        doldur(pg, '.fs-jam-dir', 135); doldur(pg, '.fs-jam-speed', 3); doldur(pg, '.fs-jam-max', 150); doldur(pg, '.fs-jam-dur', 120)
        pg.wait_for_timeout(300)
        shot(pg, '04-panel-filled.png', klip)
        pg.locator('.fs-jam-start').click()
        bekle(lambda: ss.jam.on, 8, 'karıştırma açılışı')
        pg.wait_for_selector('.fs-jam-banner:not([hidden])', timeout=8000)
        pg.wait_for_timeout(4000)
        print('  durum:', ss.jam.durum(), flush=True)
        print('  tele.jam:', ss.tele.get('jam'), 'fix', ss.tele.get('fix'), 'sat', ss.tele.get('sats'), flush=True)
        print('  band:', pg.evaluate("document.querySelector('.fs-jam-banner').innerText").replace('\n', ' | '), tasma(pg, '.fs-jam-banner'), 'panel açık:', pg.evaluate("!document.querySelector('.fs-jam-pop').hidden"), flush=True)
        shot(pg, '05-active.png')
        jb = pg.locator('.fs-jam').bounding_box()
        shot(pg, '06-bar-active-zoom.png', {'x': max(0, jb['x'] - 260), 'y': bar['y'] - 6, 'width': min(1600 - max(0, jb['x'] - 260), jb['width'] + 520), 'height': bar['height'] + 12})
        # etkinken panel: Uygula + Durdur, canlı satır
        pg.locator('.fs-jam-btn').click()
        pg.wait_for_selector('.fs-jam-pop:not([hidden])', timeout=5000); pg.wait_for_timeout(1200)
        print('  etkin panel:', pg.evaluate("({start: document.querySelector('.fs-jam-start').innerText, stop: !document.querySelector('.fs-jam-stop').hidden, live: document.querySelector('.fs-jam-live').innerText, seg: document.querySelector('.fs-jam-seg button[aria-pressed=true]').dataset.v, dir: document.querySelector('.fs-jam-dir').value})"), flush=True)
        pb = pg.locator('.fs-jam-pop').bounding_box()
        shot(pg, '07-panel-active.png', {'x': max(0, pb['x'] - 16), 'y': max(0, pb['y'] - 16), 'width': pb['width'] + 32, 'height': min(900 - max(0, pb['y'] - 16), pb['height'] + 90)})
        # Esc kapatır
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
        if pg.evaluate("!document.querySelector('.fs-jam-pop').hidden"):
            hatalar.append('Esc paneli kapatmadı')
        # dar ekran
        pg.set_viewport_size({'width': 420, 'height': 800}); pg.wait_for_timeout(1500)
        shot(pg, '08-narrow-active.png')
        print('  dar band:', tasma(pg, '.fs-jam-banner'), flush=True)
        pg.locator('.fs-mob-btn').click(); pg.wait_for_timeout(700)   # mobil menü: alt bant çekmece olarak açılır
        shot(pg, '09-narrow-drawer.png')
        pg.locator('.fs-jam-btn').click(); pg.wait_for_timeout(700)
        dp = tasma(pg, '.fs-jam-pop')
        print('  dar panel:', dp, flush=True)
        if min(dp['l'], dp['r'], dp['t']) < 0 or dp['w'] < 200:
            hatalar.append(f'dar ekranda panel taşıyor: {dp}')
        shot(pg, '09-narrow-panel.png')
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
        if pg.evaluate("document.querySelector('.fs-stage').classList.contains('fs-mob-open')"):
            pg.locator('.fs-mob-btn').click(); pg.wait_for_timeout(400)
        pg.set_viewport_size({'width': 1600, 'height': 900}); pg.wait_for_timeout(1200)
        # Durdur
        pg.locator('.fs-jam-btn').click(); pg.wait_for_selector('.fs-jam-pop:not([hidden])', timeout=5000)
        pg.locator('.fs-jam-stop').click()
        bekle(lambda: not ss.jam.on, 8, 'karıştırma kapanışı')
        pg.wait_for_timeout(1500)
        print('  kapandı:', pg.evaluate("({st: document.querySelector('.fs-jam').dataset.state, band: !document.querySelector('.fs-jam-banner').hidden, txt: document.querySelector('.fs-jam-btn').innerText})"), flush=True)
        shot(pg, '10-stopped.png')
        # olay günlüğü
        print('  olaylar:', pg.evaluate("[...document.querySelectorAll('.fs-ev, .fs-events li, .fs-evlog li')].slice(-8).map(e => e.innerText.slice(0, 90))"), flush=True)
        # hafif, 5 sn süreli → kendiliğinden kapanır
        cmd(sid, 'jam', {'gps': 'light', 'dur_s': 5})
        pg.wait_for_timeout(1500)
        print('  hafif band:', pg.evaluate("document.querySelector('.fs-jam-banner').innerText").replace('\n', ' | '), flush=True)
        shot(pg, '11-light.png')
        bekle(lambda: not ss.jam.on, 15, 'süre dolumu')
        pg.wait_for_timeout(1200)
        print('  süre sonrası:', pg.evaluate("({st: document.querySelector('.fs-jam').dataset.state, band: !document.querySelector('.fs-jam-banner').hidden})"), flush=True)
        # Bitir → rapor
        pg.locator('.fs-bar .btn.danger', has_text='Bitir').first.click()
        pg.wait_for_selector('.modal', timeout=8000); pg.wait_for_timeout(400)
        pg.evaluate("[...document.querySelectorAll('.modal .btn')].filter(b => /^Bitir$/.test(b.textContent.trim())).pop()?.click()")
        pg.wait_for_selector('.fs-rp-jam', timeout=40000)
        pg.wait_for_timeout(1500)
        shot(pg, '12-report.png')
        pg.evaluate("document.querySelector('.fs-rp-jam').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(600)
        shot(pg, '13-report-jam.png')
        print('  rapor kartı:', pg.evaluate("document.querySelector('.fs-rp-jam').innerText").replace('\n', ' | ')[:700], flush=True)
        b.close()
except Exception as e:   # noqa: BLE001
    import traceback
    traceback.print_exc()
    hatalar.append('İSTİSNA: ' + str(e)[:400])
print('HATALAR:' if hatalar else 'hata yok', flush=True)
for h in hatalar:
    print('  -', h, flush=True)
sys.stdout.flush()
os._exit(1 if hatalar else 0)
