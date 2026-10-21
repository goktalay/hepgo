"""HEPGO Uçuş Simülatörü §31 — gerçekçi dünya, hava durumu, rüzgâr göstergeleri, rampa yön/açı arayüzü: görsel doğrulama
(Playwright headless shell + SwiftShader; sahte kinematik HEPGO_SITL=0). Dünya: WFX_WORLD = procedural (vars.) | real.
Görüntüler /tmp/worldfx-shots/<önek>-*.png; her sahnede fxInfo (çizim çağrısı, üçgen, sis) ve yazılım WebGL kare hızı yazılır.
WFX_ONLY = virgüllü sahne listesi (ör. 'day,rain'); WFX_PREFIX dosya öneki (önce/sonra karşılaştırması için).
Çalıştırma: ./.venv/bin/python -m tests.worldfx_shots_hepgo
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
WORLD = os.environ.get('WFX_WORLD') or 'procedural'
ONLY = set(filter(None, (os.environ.get('WFX_ONLY') or '').split(',')))
PREFIX = os.environ.get('WFX_PREFIX') or f'hepgo-{WORLD}'
DATA = f"/tmp/worldfx-shots-data-{WORLD}-{os.environ.get('SHOT_PORT') or 8871}"
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE=os.environ.get('WFX_UDP') or '39750', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8871)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/worldfx-shots'); OUT.mkdir(parents=True, exist_ok=True)
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
NEW = pathlib.Path('static/js/modules/flightsim_worldfx.js').exists()   # "önce" kopyasında §31 yok


def want(k):
    return not ONLY or k in ONLY


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
    pg.screenshot(path=str(OUT / f'{PREFIX}-{ad}.png'))
    print('  kare', f'{PREFIX}-{ad}.png', flush=True)


def fps(pg, ms=3000):
    return pg.evaluate(f'''() => new Promise(res => {{ let n = 0; const t0 = performance.now(); const f = () => {{ n++; if (performance.now() - t0 < {ms}) requestAnimationFrame(f); else res(+(n * 1000 / (performance.now() - t0)).toFixed(1)); }}; requestAnimationFrame(f); }})''')


def info(pg, ad):
    fi = pg.evaluate('window.__fsSim.fxInfo ? window.__fsSim.fxInfo() : null')
    print(f'  [{ad}] fps(yazılım GL)={fps(pg)} fx={fi}', flush=True)


def cmd(sid, name, params=None):
    r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': name, 'params': params or {}})
    if r.status_code != 200:
        hatalar.append(f'cmd {name} {r.status_code} {r.text[:200]}')
    return r


def oturum(pg, body):
    r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
    assert r.status_code == 201, r.text
    sid = r.json()['id']
    ss = flightsim.MANAGER.sessions[sid]
    bekle(lambda: ss.state == 'HAZIR', 120, 'HAZIR')
    pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
    pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera', timeout=240000)
    pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
    pg.wait_for_timeout(7000)   # giriş sekansı
    if not pg.locator('.fs-stage').count():   # liste sayfası geç bitip görünümü ezdiyse yeniden yönlendir
        pg.evaluate("location.hash = '#/drone/sim'"); pg.wait_for_timeout(1500)
        pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'"); pg.wait_for_selector('.fs-stage', timeout=120000); pg.wait_for_timeout(7000)
    if os.environ.get('WFX_DEBUG'):
        print('  hash:', pg.evaluate('location.hash'), 'fps', fps(pg), 'stage', pg.locator('.fs-stage').count(), flush=True); shot(pg, '00-debug')
    return sid, ss


def dunya(pg, **kw):
    """Aynı oturumda dünyayı değiştir (hava/saat) — 3B yeniden kurulur."""
    pg.evaluate(f'window.__fsSim.setWorld({{ ...window.__fsSim.world, ...{kw!r} }})'.replace('True', 'true').replace('False', 'false'))
    pg.wait_for_timeout(2500 if WORLD == 'procedural' else 9000)
    kareler(pg, 2)


def kareler(pg, n=3):
    """n kare çizilene dek bekle (yazılım WebGL saniyede < 1 kare; değişiklikten sonra eski kare yakalanmasın)."""
    pg.evaluate(f'() => new Promise(r => {{ let k = 0; const f = () => {{ if (++k >= {n}) r(); else requestAnimationFrame(f); }}; requestAnimationFrame(f); }})')


def bak(pg, x, y, dz, tx, ty, tdz=0, n=3):
    """Kamera (x, y, arazi + dz) → hedef (tx, ty, arazi + tdz) — serbest kamera (yaw: 0 kuzey, + batı)."""
    pg.evaluate(f"""(() => {{ const S = window.__fsSim, h = (a, b) => S.terrainHeight(a, b);
      const z = Math.max(h({x}, {y}), S.waterZ > -1e9 ? S.waterZ : -1e9) + {dz}, tz = h({tx}, {ty}) + {tdz}, dx = {tx} - ({x}), dy = {ty} - ({y});
      S.setFreeView({x}, {y}, z, -Math.atan2(dx, dy) * 180 / Math.PI, Math.atan2(tz - z, Math.hypot(dx, dy)) * 180 / Math.PI); }})()""")
    kareler(pg, n)


WMODE = {'procedural': {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'mountain_height': 450, 'building_count': 120, 'tree_density': 0.4},
         'real': {'mode': 'real', 'size_m': 4000, 'building_count': 0, 'tree_density': 0.4}}[WORLD]
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(240000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:600]}') if m.type in (('error', 'warning') if os.environ.get('WFX_DEBUG') else ('error',)) and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(2500)
        body = {'mode': 'sitl', 'type': 'sabit_kanat', 'center_id': c['id'], 'rec': {'bin': False},
                'world': {**WMODE, 'time': 'day', 'wind_ms': 6, 'wind_dir': 300, 'runway_heading': 20, 'fog': 0.2, 'launch': {'method': 'ramp', 'angle_deg': 15}}}
        sid, ss = oturum(pg, body)
        # 1) genel bakış (gündüz, açık) — dağlar, kasaba, orman
        tw = (pg.evaluate('window.__fsSim.fxInfo ? window.__fsSim.fxInfo().townsAt : null') or [[600, 300]])[0]
        ax, ay = tw[0] * 0.55, tw[1] * 0.55   # kasabaya bakış noktası (merkezle kasaba arası)
        V = [(-300, -700, 160, 400, 1200, 0), (ax - 120, ay - 120, 70, tw[0], tw[1], 10), (-30, -80, 6, 120, 500, 2)]
        if want('day'):
            bak(pg, *V[0]); shot(pg, '01-day-overview'); info(pg, 'day')
            bak(pg, *V[1]); shot(pg, '02-day-town')
            bak(pg, *V[2]); shot(pg, '03-day-ground')
        if want('dusk'):
            dunya(pg, time='dusk'); bak(pg, *V[0]); shot(pg, '04-dusk')
        if want('night'):
            dunya(pg, time='night'); bak(pg, *V[1]); shot(pg, '05-night-town'); info(pg, 'night')
        for w, ad in (('rain', '06-rain'), ('snow', '07-snow'), ('fog', '08-fog'), ('storm', '09-storm'), ('cloudy', '10-cloudy')):
            if want(w) and NEW:
                dunya(pg, time='day', weather=w); bak(pg, *V[2]); shot(pg, ad); info(pg, w)
                if w in ('rain', 'snow'):
                    bak(pg, *V[0]); shot(pg, ad + '-far')
        if NEW and (want('wind') or want('ramp')):
            dunya(pg, time='day', weather='clear')
            pg.evaluate("window.__fsSim.setCamera('follow')"); pg.wait_for_timeout(2500)
            if want('wind'):
                cmd(sid, 'wind', {'ms': 9, 'dir': 250, 'gust': 4})
                pg.wait_for_timeout(2500); kareler(pg, 3)
                print('  rüzgâr:', pg.evaluate('window.__fsSim.windInfo()'), flush=True)
                shot(pg, '11-follow-windsock-gauge-streaks')
                rw = pg.evaluate('window.__fsSim.world.runway_heading') * 3.14159 / 180   # tulum: pist yerel (44, 60) → dünya
                sx, sy = 44 * __import__('math').cos(-rw) - 60 * __import__('math').sin(-rw), 44 * __import__('math').sin(-rw) + 60 * __import__('math').cos(-rw)
                bak(pg, sx - 18, sy - 22, 6, sx, sy, 7); shot(pg, '12-windsock-close')
            if want('ramp'):
                pg.evaluate("window.__fsSim.setCamera('follow')"); pg.wait_for_timeout(2500)
                cv = pg.locator('canvas.fs3d-canvas').bounding_box()
                pg.mouse.click(cv['x'] + cv['width'] / 2, cv['y'] + cv['height'] / 2); pg.wait_for_timeout(1500)
                print('  rampaya tıklama paneli açtı:', bool(pg.locator('.fs-ramp-ui:not([hidden])').count()), flush=True)
                if not pg.locator('.fs-ramp-ui:not([hidden])').count():
                    pg.evaluate("window.__fsRampUi && window.__fsRampUi.open()"); pg.wait_for_timeout(800)
                shot(pg, '13-ramp-ui')
                if pg.locator('.fs-ramp-wind').count():
                    pg.locator('.fs-ramp-wind').click(); pg.wait_for_timeout(1500); kareler(pg, 3); shot(pg, '14-ramp-into-wind-preview')
                    pg.locator('.fs-ramp-apply').click(); pg.wait_for_timeout(2500)
                    print('  rampa (sunucu):', ss.launch, 'sahte yön°', round(__import__('math').degrees(ss.sahte.heading), 1), flush=True)
                    shot(pg, '15-ramp-applied')
            if want('fly'):
                cmd(sid, 'takeoff', {'alt': 80})
                bekle(lambda: (ss.tele.get('alt_rel') or 0) > 60, 120, 'kalkış')
                pg.wait_for_timeout(3000)
                shot(pg, '16-flight-streaks'); info(pg, 'flight')
                pg.evaluate("window.__fsSim.setCamera('pilot')"); dunya(pg, weather='rain'); pg.wait_for_timeout(2500); kareler(pg, 3)
                shot(pg, '17-fpv-rain-lens')
                pg.evaluate("window.__fsSim.setCamera('follow')"); dunya(pg, weather='snow', time='dusk'); kareler(pg, 3)
                shot(pg, '18-follow-snow-dusk')
        s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / f'{PREFIX}-hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(4.0)
