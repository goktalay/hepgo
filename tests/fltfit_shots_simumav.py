"""SIMUMAV uçuş ekranı — ALT BANT SIĞDIRMA (HEPGO flightsim_fltbar.fitFlightBar; Playwright headless shell + SwiftShader; sahte SITL; sunucu aynı süreçte).
≥ 1280 px tek satır, 1024–1279 px en çok iki satır, taşma yok; çok rotorlu (gimbal görünümü) TR/EN/DE + kara aracı; harekât paneli açık/kapalı.
Kareler /tmp/fixes-shots/fltfit-sm-<önek>-*.png. Çalıştırma: ./.venv/bin/python -m tests.fltfit_shots_simumav  (FLTFIT_LANGS, FLTFIT_W, FLTFIT_TAG)
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
DATA = '/tmp/fltfit-shots-sm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='25850', SIMUMAV_MAX_FLIGHTS='2',
                  SIMUMAV_MP_PORT_BASE='26800', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='', SIMUMAV_MAX_SPEEDUP='8')
PORT = int(os.environ.get('SHOT_PORT') or 8643)
BASE = f'http://127.0.0.1:{PORT}'
TAG = os.environ.get('FLTFIT_TAG', 'sonra')
OUT = pathlib.Path('/tmp/fixes-shots'); OUT.mkdir(parents=True, exist_ok=True)
LANGS = [x for x in (os.environ.get('FLTFIT_LANGS') or 'tr,en,de').split(',') if x]
WIDTHS = [int(x) for x in (os.environ.get('FLTFIT_W') or '1440,1366,1280,1024').split(',')]
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
d = s.post(f'{BASE}/api/hangar', json={'name': 'Kartal', 'type': 'multirotor', 'model_key': 'builtin:quad', 'color': '#0ea5e9'}, headers=H).json()
s.put(f"{BASE}/api/hangar/{d['id']}", json={'is_default': True}, headers=H)
dr = s.post(f'{BASE}/api/hangar', json={'name': 'Keşif-1', 'type': 'rover', 'model_key': 'glb:rover_4x4', 'color': '#f59e0b'}, headers=H).json()
pid = s.get(f'{BASE}/api/crew').json()['pilots'][0]['id']
tr = s.post(f'{BASE}/api/tracks', json={'name': 'Göl Kıyısı', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural',
                                        'world': {'seed': 21, 'runway': True, 'tree_density': 0.2, 'building_count': 20, 'runway_deg': 30}}, headers=H).json()
s.put(f"{BASE}/api/tracks/{tr['id']}", json={'is_default': True}, headers=H)
hatalar = []


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
        time.sleep(0.25)
    hatalar.append(f'{ad}: {sec} sn içinde olmadı'); return False


OLC_JS = """() => { const bar = document.querySelector('.fs-bar'); const W = innerWidth; const kids = [...bar.children].filter(e => e.offsetParent && e.getBoundingClientRect().width > 0);
  const tops = []; for (const e of kids) { const t = Math.round(e.getBoundingClientRect().top + e.getBoundingClientRect().height / 2); if (!tops.some(x => Math.abs(x - t) < 12)) tops.push(t); }
  const out = []; for (const e of bar.querySelectorAll('button, select, input, .pill-group')) { if (!e.offsetParent) continue; const r = e.getBoundingClientRect(); if (r.width && (r.right > W + 0.5 || r.left < -0.5)) out.push((e.className || e.tagName) + ' ' + Math.round(r.left) + '..' + Math.round(r.right)); }
  return { W, rows: tops.length, barH: bar.offsetHeight, lvl: bar.dataset.fit || '0', sw: document.documentElement.scrollWidth, out,
    kids: kids.map(e => [e.className.split(' ').slice(0, 2).join('.'), Math.round(e.getBoundingClientRect().width), e.textContent.trim().replace(/\\s+/g, ' ').slice(0, 30)]) }; }"""


def shot(pg, ad):
    vw = pg.viewport_size
    bb = pg.locator('.fs-bar').bounding_box()
    y = max(0, min(bb['y'], vw['height'] - 60) - 30)
    pg.screenshot(path=str(OUT / f'fltfit-sm-{TAG}-{ad}.png'), clip={'x': 0, 'y': y, 'width': vw['width'], 'height': vw['height'] - y})


def olc(pg, ad, maxrows):
    pg.wait_for_timeout(700)
    pg.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r))))')   # sığdırma (RO → rAF) otursun
    m = pg.evaluate(OLC_JS)
    kontrol(f'{ad}: {m["rows"]} satır (≤ {maxrows}), kademe {m["lvl"]}, bant {m["barH"]} px', m['rows'] <= maxrows and not m['out'] and m['sw'] <= m['W'],
            json.dumps(m, ensure_ascii=False)[:900])


def ucus(pg, drone_id, camera=None):
    body = {'drone_id': drone_id, 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False}}
    if camera:
        body['camera'] = camera
    f = s.post(f'{BASE}/api/fly/start', json=body, headers=H)
    assert f.status_code == 201, f.text
    fid, sid = f.json()['flight_id'], f.json()['sim_id']
    ss = flightsim.MANAGER.sessions[sid]
    pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
    pg.goto(f'{BASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
    pg.wait_for_selector('.fs-bar .fs-cam-ctl', timeout=240000)
    pg.wait_for_function('() => window.__smSim && window.__smSim.getCamera', timeout=240000)
    bekle(lambda: ss.state == 'HAZIR', 120, 'HAZIR')
    pg.wait_for_timeout(9000)   # giriş sekansı
    return fid


def panel(pg, on):
    if pg.evaluate("document.querySelector('.fs-ops-btn').classList.contains('primary')") != on:
        pg.locator('.fs-ops-btn').click(); pg.wait_for_timeout(900)


def genislikler(pg, ad):
    for w in WIDTHS:
        pg.set_viewport_size({'width': w, 'height': 760 if w < 1300 else 820}); pg.wait_for_timeout(900)
        for pn in (False, True):
            panel(pg, pn)
            olc(pg, f'{ad} {w}{" panel" if pn else ""}', 1 if w >= 1280 else 2)
            if w in (1366, 1280, 1024):
                shot(pg, f'{ad}-{w}{"-panel" if pn else ""}')
    pg.set_viewport_size({'width': 1600, 'height': 900})


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        for lang in LANGS:
            ctx = b.new_context(viewport={'width': 1600, 'height': 900}, locale='tr-TR')
            ctx.add_cookies([{'name': 'smsid', 'value': tok, 'url': BASE}])
            ctx.add_init_script("try { localStorage.setItem('sm:lang', '%s'); localStorage.setItem('simumav.consent', 'denied'); localStorage.setItem('sm.gfx', JSON.stringify({ preset: 'low' })); } catch (e) {}" % lang)
            pg = ctx.new_page()
            pg.set_default_timeout(150000)
            pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
            fid = ucus(pg, d['id'], camera='day')
            pg.mouse.click(700, 300); pg.keyboard.press('3'); pg.wait_for_timeout(600)   # gimbal: açı etiketi + HUD düğmesi de bantta
            genislikler(pg, f'{lang}-multi')
            s.post(f'{BASE}/api/fly/{fid}/stop', json={}, headers=H); pg.wait_for_timeout(1500)
            if lang == LANGS[0]:
                fid = ucus(pg, dr['id'])
                genislikler(pg, f'{lang}-rover')
                s.post(f'{BASE}/api/fly/{fid}/stop', json={}, headers=H); pg.wait_for_timeout(1500)
            ctx.close()
        b.close()
except Exception:
    import traceback
    traceback.print_exc()
    hatalar.append('İSTİSNA')
finally:
    server.should_exit = True
print('HATALAR:' if hatalar else 'hata yok', *hatalar, sep='\n  ')
sys.exit(1 if hatalar else 0)
