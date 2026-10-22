"""SIMUMAV — HEPGO §43 GRAFİK KALİTE AYARLARI: uçuş ekranında "Grafik ▾" menüsü (sm.gfx, gfx.* i18n), aynı sahne Düşük / Yüksek / Ultra,
sihirbaz son adımı seçicisi (bileşen) — görsel doğrulama (Playwright headless shell + SwiftShader; sahte SITL). Görüntüler /tmp/gfx-shots/sm-*.png.
Çalıştırma: ./.venv/bin/python -m tests.gfx_shots_simumav
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
DATA = '/tmp/gfx-shots-sm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='25950', SIMUMAV_MAX_FLIGHTS='2',
                  SIMUMAV_MP_PORT_BASE='26900', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='', SIMUMAV_MAX_SPEEDUP='8')
PORT = int(os.environ.get('SHOT_PORT') or 8661)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/gfx-shots'); OUT.mkdir(parents=True, exist_ok=True)
LANG = os.environ.get('GFX_LANG') or 'tr'
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
cay = s.post(f'{BASE}/api/hangar', json={'name': 'CAYMAZ', 'type': 'plane', 'model_key': 'builtin:caymaz', 'color': '#f97316'}, headers=H).json()
pid = s.get(f'{BASE}/api/crew').json()['pilots'][0]['id']
hatalar = []


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


def shot(pg, ad):
    pg.screenshot(path=str(OUT / ad))
    print('  kare', ad, flush=True)


def kareler(pg, n=3):
    pg.evaluate(f'() => new Promise(r => {{ let k = 0; const off = window.__smSim.addFrameHook(() => {{ if (++k >= {n}) {{ off(); r(); }} }}); }})')


def onayar(pg, k):
    if not pg.locator('.fs-gfx-menu:not([hidden])').count():
        pg.locator('.fs-gfx-btn').click(); pg.wait_for_timeout(300)
    pg.locator(f'.fs-gfx-menu .fs-gfx-seg button[data-gfx="{k}"]').click()
    pg.locator('.fs-gfx-menu .fs-gfx-h button').click()
    pg.wait_for_timeout(1800); kareler(pg, 3)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1280, 'height': 720}, locale='tr-TR')
        ctx.add_cookies([{'name': 'smsid', 'value': tok, 'url': BASE}])
        ctx.add_init_script(f"try {{ localStorage.setItem('sm:lang', '{LANG}'); localStorage.setItem('simumav.consent', 'denied'); localStorage.setItem('sm.gfx', JSON.stringify({{ preset: 'high' }})); localStorage.setItem('fs.rec.on', '0'); }} catch (e) {{}}")
        pg = ctx.new_page()
        pg.set_default_timeout(300000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        tr = s.post(f'{BASE}/api/tracks', json={'name': 'Grafik Vadisi', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural', 'weather': 'clear',
                                                'wind': {'speed_ms': 4, 'dir_deg': 300, 'gust': 0},
                                                'world': {'seed': 21, 'runway': True, 'tree_density': 0.45, 'building_count': 80, 'runway_deg': 30}}, headers=H).json()
        f = s.post(f'{BASE}/api/fly/start', json={'drone_id': cay['id'], 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False, 'video': False}}, headers=H)
        assert f.status_code == 201, f.text
        fid, sid = f.json()['flight_id'], f.json()['sim_id']
        ss = flightsim.MANAGER.sessions[sid]
        pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
        pg.goto(f'{BASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
        pg.wait_for_function('() => window.__smSim && window.__smSim.getCamera && document.querySelector(".fs-gfx-btn")', timeout=300000)
        bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
        pg.wait_for_timeout(9000)
        pg.evaluate("window.__smSim.setCamera('follow')"); pg.wait_for_timeout(1500)
        for k in ('low', 'high', 'ultra'):
            onayar(pg, k)
            g = pg.evaluate("(() => { const g = window.__smSim.getGraphics(), st = window.__smSim.gfxStats(); return { level: g.level, pr: g.pr, buf: g.buffer, post: g.pipe.active && g.post, samples: g.pipe.samples, shadow: g.shadow, calls: st.calls, tris: st.tris }; })()")
            print(f'  [{k}]', json.dumps(g, ensure_ascii=False), flush=True)
            shot(pg, f'sm-follow-{k}.png')
        pg.locator('.fs-gfx-btn').click(); pg.wait_for_timeout(300)
        pg.evaluate("document.querySelector('.fs-gfx-menu details').open = true"); pg.wait_for_timeout(1200)
        print('  tercih sm.gfx:', pg.evaluate("localStorage.getItem('sm.gfx')"), '· fs.gfx:', pg.evaluate("localStorage.getItem('fs.gfx')"), flush=True)
        shot(pg, f'sm-menu-{LANG}.png')
        # sihirbaz son adımı bileşeni (oyun teması; aynı modül /sim/flightsim_gfx_ui.js)
        pg.evaluate("""import('/sim/flightsim_gfx_ui.js').then(M => { const w = document.createElement('div'); w.id = 'gfxpick'; w.style.cssText = 'position:fixed;left:24px;top:90px;z-index:99;width:520px;padding:14px;border-radius:12px;background:#0b1220;color:#e6e9ef';
          w.append(M.createGfxPicker({ tr: k => k, keyed: true, storageKey: 'sm.gfx' }).el); document.body.append(w); })""")
        pg.wait_for_timeout(800)
        pg.locator('#gfxpick').screenshot(path=str(OUT / 'sm-wizard-picker.png')); print('  kare sm-wizard-picker.png', flush=True)
        s.post(f'{BASE}/api/fly/{fid}/stop', json={}, headers=H)
        b.close()
except Exception:
    import traceback
    traceback.print_exc()
    hatalar.append('İSTİSNA')
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(3.0)
