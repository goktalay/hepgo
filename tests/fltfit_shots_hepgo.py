"""HEPGO Uçuş Simülatörü — ALT BANT SIĞDIRMA (docs/ucus-simulatoru.md §29.6 / §43 sonrası düzeltme; Playwright headless shell + SwiftShader; sahte kinematik).
Alt bant (.fs-bar) ≥ 1280 px genişlikte TEK SATIR, 1024–1279 px'te en çok İKİ satır olmalı; hiçbir öğe ekran dışına taşmamalı. Bant genişliğe göre
kademeli sıkışır (flightsim_barfit.js: fs-bar-c1 … c3 — boşluk/iç boşluk, ikincil etiketler simgeye iner; title/aria-label korunur).
Araç tipleri: çok rotorlu (gimbal kamerası), sabit kanat (tekerlekli kalkış), kara aracı, kayıttan oynatma; harekât paneli açık/kapalı; dar ekran;
mobil (☰ menü, §39) düzeni bozulmamalı. Kareler /tmp/fixes-shots/fltfit-<önek>-*.png (FLTFIT_TAG: 'once' | 'sonra').
Çalıştırma: ./.venv/bin/python -m tests.fltfit_shots_hepgo
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
PORT = int(os.environ.get('SHOT_PORT') or 8933)
DATA = f'/tmp/fltfit-shots-data-{PORT}'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE=os.environ.get('FLTFIT_UDP') or '39990', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='6')
BASE = f'http://127.0.0.1:{PORT}'
TAG = os.environ.get('FLTFIT_TAG', 'sonra') + ('' if os.environ.get('FLTFIT_LANG', 'tr') == 'tr' else '-' + os.environ['FLTFIT_LANG'])
OUT = pathlib.Path('/tmp/fixes-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
SAMPLE_BIN = pathlib.Path(__file__).with_name('data') / 'arduplane-sample.bin'
WIDTHS = [int(x) for x in (os.environ.get('FLTFIT_W') or '1600,1440,1366,1280,1180,1024').split(',')]
CASES = [x for x in (os.environ.get('FLTFIT_CASES') or 'multi,plane,rover,replay,mobile').split(',') if x]
DUMP = os.environ.get('FLTFIT_DUMP') == '1'
LANG = os.environ.get('FLTFIT_LANG', 'tr')   # HEPGO arayüz dili (caymaz.lang): tr | en | de …

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth, config, db, flightsim  # noqa: E402
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
s.post(f'{BASE}/api/location/consent', json={'granted': False})
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Test Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
hatalar = []
WORLD = {'mode': 'procedural', 'seed': 11, 'size_m': 3000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.2, 'building_count': 10}


def kontrol(ad, kosul, ek=''):
    print(('  ✓ ' if kosul else '  ✗ ') + ad + (f' — {ek}' if ek and not kosul else ''), flush=True)
    if not kosul:
        hatalar.append(f'{ad} {ek}')


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


# Bant ölçümü: görünür doğrudan çocukların satırları (üst kenar kümeleri), taşma, sıkıştırma kademesi, alt satırın sola/sağa hizası
OLC_JS = """() => { const bar = document.querySelector('.fs-bar'); const W = innerWidth; const kids = [...bar.children].filter(e => e.offsetParent && e.getBoundingClientRect().width > 0);
  const tops = []; for (const e of kids) { const t = Math.round(e.getBoundingClientRect().top + e.getBoundingClientRect().height / 2); if (!tops.some(x => Math.abs(x - t) < 12)) tops.push(t); }
  const out = []; for (const e of bar.querySelectorAll('button, select, input, .pill-group')) { if (!e.offsetParent) continue; const r = e.getBoundingClientRect(); if (r.width && (r.right > W + 0.5 || r.left < -0.5)) out.push((e.className || e.tagName) + ' ' + Math.round(r.left) + '..' + Math.round(r.right)); }
  const noLabel = [...bar.querySelectorAll('button')].filter(b => b.offsetParent && !b.textContent.trim() && !b.getAttribute('aria-label') && !b.title).map(b => b.className);
  return { W, rows: tops.length, barH: bar.offsetHeight, lvl: bar.dataset.fit || '0', sw: document.documentElement.scrollWidth, out, noLabel,
    kids: kids.map(e => [e.className.split(' ').slice(0, 2).join('.'), Math.round(e.getBoundingClientRect().left), Math.round(e.getBoundingClientRect().width), e.textContent.trim().replace(/\\s+/g, ' ').slice(0, 40)]) }; }"""


def olc(pg, ad, maxrows):
    pg.wait_for_timeout(700)
    pg.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r))))')   # sığdırma (RO → rAF) otursun
    m = pg.evaluate(OLC_JS)
    if DUMP:
        print('   ', ad, json.dumps(m, ensure_ascii=False), flush=True)
    kontrol(f'{ad}: {m["rows"]} satır (≤ {maxrows}), kademe {m["lvl"]}, bant {m["barH"]} px', m['rows'] <= maxrows and not m['out'] and m['sw'] <= m['W'] and not m['noLabel'],
            json.dumps({k: m[k] for k in ('rows', 'out', 'sw', 'noLabel', 'kids')}, ensure_ascii=False)[:900])
    return m


def shot(pg, ad):
    vw = pg.viewport_size
    bb = pg.locator('.fs-bar').bounding_box()
    y = max(0, min(bb['y'], vw['height'] - 60) - 30)
    pg.screenshot(path=str(OUT / f'fltfit-{TAG}-{ad}.png'), clip={'x': 0, 'y': y, 'width': vw['width'], 'height': vw['height'] - y})


def oturum_ac(pg, body, sec='.fs-bar'):
    r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
    assert r.status_code == 201, r.text
    sid = r.json()['id']
    if body.get('mode') != 'replay':
        bekle(lambda: flightsim.MANAGER.sessions[sid].state == 'HAZIR', 180, 'HAZIR')
    pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')
    pg.wait_for_timeout(5000)
    if not pg.locator('.fs-stage').count():
        pg.evaluate("location.hash = '#/drone/sim'"); pg.wait_for_timeout(1500)
        pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
    pg.wait_for_selector(sec, timeout=240000)
    pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera', timeout=240000)
    pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
    pg.wait_for_timeout(5000)
    return sid


def panel(pg, on):
    if pg.evaluate("document.querySelector('.fs-ops-btn').classList.contains('primary')") != on:
        pg.locator('.fs-ops-btn').click(); pg.wait_for_timeout(900)


def genislikler(pg, ad, panel_durumlari=(False, True)):
    for w in WIDTHS:
        pg.set_viewport_size({'width': w, 'height': 760 if w < 1300 else 820}); pg.wait_for_timeout(900)
        for pn in panel_durumlari:
            panel(pg, pn)
            olc(pg, f'{ad} {w}{" panel" if pn else ""}', 1 if w >= 1280 else 2)
            if w in (1600, 1440, 1366, 1280, 1024):
                shot(pg, f'{ad}-{w}{"-panel" if pn else ""}')
    pg.set_viewport_size({'width': 1600, 'height': 900})


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1600, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        ctx.add_init_script("try { localStorage.setItem('fs.gfx', JSON.stringify({ preset: 'low' })); localStorage.setItem('caymaz.lang', '%s'); } catch (e) {}" % LANG)
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        if 'multi' in CASES:
            sid = oturum_ac(pg, {'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False}, 'camera': 'day', 'world': WORLD}, sec='.fs-bar .fs-srv')
            pg.mouse.click(700, 300); pg.keyboard.press('3'); pg.wait_for_timeout(500)   # gimbal → "GMB" etiketi de bantta
            genislikler(pg, 'multi')
            s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        if 'plane' in CASES:
            sid = oturum_ac(pg, {'mode': 'sitl', 'type': 'sabit_kanat', 'center_id': c['id'], 'rec': {'bin': False}, 'world': {**WORLD, 'launch': {'method': 'wheels'}}}, sec='.fs-bar .fs-srv')
            pg.evaluate("window.__fsSim.setFreeView(-30, -60, 20, 0, -5)"); pg.wait_for_timeout(400)
            genislikler(pg, 'plane')
            s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        if 'rover' in CASES:
            sid = oturum_ac(pg, {'mode': 'sitl', 'type': 'rover', 'center_id': c['id'], 'drive': 'skid', 'model': {'id': 'builtin:rover_ugv'}, 'rec': {'bin': False}, 'world': WORLD})
            genislikler(pg, 'rover')
            s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        if 'replay' in CASES:
            hedef = config.UPLOAD_DIR / 'flightlogs'; hedef.mkdir(parents=True, exist_ok=True)
            shutil.copy(SAMPLE_BIN, hedef / 'ornek.bin')
            with db.connect() as conn:
                lid = conn.execute('''INSERT INTO flight_logs (file, file_name, size, status, analysis, aircraft, uploaded_by, uploaded_at, origin)
                                      VALUES (?, 'ornek.BIN', ?, 'TAMAM', ?, 'CZ-T', 1, ?, 'REAL')''',
                                   ('flightlogs/ornek.bin', SAMPLE_BIN.stat().st_size, json.dumps({'summary': {'vehicle': 'ArduPlane', 'home': {'lat': 39.925, 'lng': 32.837}}}), db.now())).lastrowid
                conn.commit()
            oturum_ac(pg, {'mode': 'replay', 'log_id': lid, 'world': {'mode': 'procedural', 'seed': 3, 'size_m': 4000}}, sec='.fs-bar .fs-playbar')
            genislikler(pg, 'replay')
        if 'mobile' in CASES:
            mctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='tr-TR', is_mobile=True, has_touch=True, device_scale_factor=2)
            mctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
            mctx.add_init_script("try { localStorage.setItem('fs.gfx', JSON.stringify({ preset: 'low' })); } catch (e) {}")
            mp = mctx.new_page(); mp.set_default_timeout(150000)
            mp.on('pageerror', lambda e: hatalar.append('MOBİL SAYFA: ' + str(e)[:400]))
            sid = oturum_ac(mp, {'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False}, 'camera': 'day', 'world': WORLD}, sec='.fs-stage')
            kontrol('mobil: ☰ kipinde', mp.evaluate("document.querySelector('.fs-stage').classList.contains('fs-mob')"))
            mp.locator('.fs-mob-btn').click(); mp.wait_for_timeout(800)
            m = mp.evaluate(OLC_JS)
            kontrol(f"mobil: menü açık, bant sıkıştırılmadı (kademe {m['lvl']}), taşma yok", m['lvl'] == '0' and not m['out'] and m['sw'] <= m['W'], json.dumps(m, ensure_ascii=False)[:600])
            mp.screenshot(path=str(OUT / f'fltfit-{TAG}-mobile-390.png'))
            mctx.close()
            s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        b.close()
except Exception:
    import traceback
    traceback.print_exc()
    hatalar.append('İSTİSNA')
finally:
    server.should_exit = True
print('HATALAR:' if hatalar else 'hata yok', *hatalar, sep='\n  ')
sys.exit(1 if hatalar else 0)
