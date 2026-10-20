"""HEPGO Uçuş Simülatörü §27 INTERCEPTOR fırlatıcıları — görsel doğrulama (Playwright headless shell + SwiftShader). Uygulama aynı süreçte açılır;
LAUNCHER_REAL=1 + HEPGO_SITL_DIR → gerçek ArduPilot SITL (kapanışta lifespan oturumları/SITL'leri kapatır), aksi sahte kinematik.
Görüntüler /tmp/launcher-shots/hepgo-*.png:
  01 sihirbaz Kalkış adımı (4 fırlatıcı kartı + 4'lü önizleme) · 02–04 sihirbaz önizlemesi 8'li / tüp / el fırlatıcısı
  05 4'lü fırlatıcı sahnede (hücreler, LED, sayaç) · 06 4'lü fırlatma anı (kapak, duman) · 07 tüp sahnede · 08 el fırlatıcısı + pilot + ekran (yakın)
  09 nişangâh penceresi göğe bakarken hedeflerle · 10 el fırlatma anı (geri tepme dumanı) · 11 görev: 8'li ×2 kutu (raf yok) · 12 8'li sıradaki hücre
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            [LAUNCHER_REAL=1 HEPGO_SITL_DIR=/opt/hepgo/sitl/bin] ./.venv/bin/python -m tests.launcher_shots_hepgo
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
REAL = os.environ.get('LAUNCHER_REAL') == '1'
DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/launcher-shots-hepgo-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1' if REAL else '0', SIM_UDP_BASE='39250', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8817)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/launcher-shots'); OUT.mkdir(parents=True, exist_ok=True)
ONLY = set(filter(None, os.environ.get('SHOTS', '').split(',')))   # ör. SHOTS=wizard,pod4,hand,defend
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
WORLD = {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.25, 'building_count': 30, 'runway_heading': 30}
TARGETS = {'items': [{'model': 'tgt:lancet', 'alt_m': 120, 'diameter_m': 400, 'east_m': 250, 'north_m': 350, 'speed_ms': 25, 'dir': 'cw', 'name': 'Lancet-1'},
                     {'model': 'tgt:octopus', 'alt_m': 180, 'diameter_m': 600, 'east_m': 400, 'north_m': 500, 'speed_ms': 40, 'dir': 'ccw', 'name': 'Octopus-1'},
                     {'model': 'tgt:sw300', 'alt_m': 90, 'diameter_m': 300, 'east_m': -300, 'north_m': 200, 'dir': 'cw', 'name': 'SW300-1'}], 'radius_m': 25}


def want(k):
    return not ONLY or k in ONLY


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


def oturum(pg, launch, targets=True, site=None, defend=None):
    body = {'mode': 'sitl', 'type': 'interceptor', 'center_id': c['id'], 'rec': {'bin': False}, 'world': {**WORLD, 'launch': launch}}
    if targets:
        body['targets'] = TARGETS
    if site:
        body['site'] = site
    if defend:
        body['defend'] = defend
    r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
    assert r.status_code == 201, r.text
    sid = r.json()['id']
    ss = flightsim.MANAGER.sessions[sid]
    bekle(lambda: ss.state == 'HAZIR' and (ss.sahte is not None or ss._heartbeat_alindi), 120, 'HAZIR')
    pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')
    pg.wait_for_function('() => window.__fsSim && window.__fsSim.launcherInfo && window.__fsSim.launcherInfo()', timeout=240000)
    pg.wait_for_timeout(2500)
    izin_kapat(pg)
    return sid, ss


def izin_kapat(pg):
    """Sayfa yeniden yüklenince çıkan "Konum takibine izin" penceresini kapat (Reddet)."""
    try:
        b = pg.locator('.modal button', has_text='Reddet')
        if b.count() and b.first.is_visible():
            b.first.click(); pg.wait_for_timeout(400)
    except Exception:   # noqa: BLE001
        pass


def bitir(pg, sid):
    s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
    pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded')
    pg.wait_for_timeout(1500)


def yakin(pg, ang=200, k=1.0, hk=0.6, look=0.5):
    """Serbest kamera düzeneğe (sim.rigFocus: merkez + bakış yarıçapı): ang (0 kuzeyden bakış, + batıya) yönünde k × yarıçap geride."""
    pg.evaluate(f"""(() => {{ const s = window.__fsSim, f = s.rigFocus; const a = {ang} * Math.PI / 180, d = f.r * {k};
      const z = f.z + f.h * {hk} + d * 0.22, tz = f.z + f.h * {look};
      s.setFreeView(f.x + Math.sin(a) * d, f.y - Math.cos(a) * d, z, {ang}, Math.atan2(tz - z, d) * 180 / Math.PI); }})()""")


def sade(pg, on=True, scope=True):
    """3B yakın çekim: kadranlar / olay şeridi / (isteğe bağlı) nişangâh penceresi gizli (nişangâh görüntüsü 3B tuvaline kopyalanmaz)."""
    css = '.fs-pip,.fs-gauges,.fs-events{visibility:hidden!important}' + ('.fs-scope{visibility:hidden!important}' if scope else '')
    pg.evaluate("""(([on, css, scope]) => { let e = document.getElementById('shot-sade'); const s = window.__fsSim;
      const rect = () => { const b = document.querySelector('.fs-scope-bd'), m = document.querySelector('.fs-canvas'); if (!b || !m || b.closest('.fs-scope').hidden) return null; const r = b.getBoundingClientRect(), q = m.getBoundingClientRect(); return { x: r.left - q.left, y: r.top - q.top, w: r.width, h: r.height }; };
      if (!on) { e?.remove(); s?.setScopeRect?.(rect()); return; }
      if (!e) { e = document.createElement('style'); e.id = 'shot-sade'; document.head.append(e); } e.textContent = css;
      if (scope) s?.setScopeRect?.(null); else s?.setScopeRect?.(rect()); })""", [on, css, scope])


def ekran_yakin(pg, d=1.0, up=0.25):
    """El fırlatıcısının ekranına bak: ekran merkezinden normal yönünde d m geride (biraz yukarıda)."""
    pg.evaluate(f"""(() => {{ const s = window.__fsSim, e = s.launcherInfo().screen; if (!e) return;
      const x = e.x + e.nx * {d}, y = e.y + e.ny * {d}, z = e.z + e.nz * {d} + {up};
      const dx = e.x - x, dy = e.y - y, dz = e.z - z, L = Math.hypot(dx, dy, dz);
      s.setFreeView(x, y, z, Math.atan2(-dx, dy) * 180 / Math.PI, Math.asin(dz / L) * 180 / Math.PI); }})()""")


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
        pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(2500)
        pg.evaluate("localStorage.setItem('fs.cam.pip', JSON.stringify({ on: false }))")   # kamera PiP'i kapalı (fırlatıcı görüntüleri sade)
        # ---- 01–04 sihirbaz Kalkış adımı
        if want('wizard'):
            pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
            pg.wait_for_selector('.fs-wizard .fs-types', timeout=60000)
            pg.locator('.fs-type', has_text='INTERCEPTOR').first.click()
            pg.wait_for_timeout(4000)
            pg.evaluate("window.__fsWz.goto('launch')"); pg.wait_for_timeout(9000)
            print('  kartlar:', pg.evaluate("[...document.querySelectorAll('.fs-launch')].map(b => b.dataset.launch)"), flush=True)
            shot(pg, 'hepgo-01-wizard-launch.png')
            for i, (k, ad) in enumerate((('pod8', '02-wizard-pod8'), ('tube', '03-wizard-tube'), ('handheld', '04-wizard-handheld'))):
                pg.locator(f'.fs-launch[data-launch="{k}"]').click(); pg.wait_for_timeout(7000)
                shot(pg, f'hepgo-{ad}.png')
            pg.keyboard.press('Escape'); pg.wait_for_timeout(500)
        # ---- 05–06 4'lü fırlatıcı (3 dolu)
        if want('pod4'):
            sid, ss = oturum(pg, {'method': 'pod4', 'loaded': 3})
            print('  pod4:', pg.evaluate('window.__fsSim.launcherInfo()'), flush=True)
            sade(pg); yakin(pg, ang=215, k=2.0, hk=1.6); pg.wait_for_timeout(3500)
            shot(pg, 'hepgo-05-pod4.png')
            if REAL:
                time.sleep(20)
            cmd(sid, 'takeoff', {'alt': 60})
            bekle(lambda: ss.launch_phase in ('launch', 'released'), 30, 'pod4 launch')
            yakin(pg, ang=215, k=2.6, hk=2.4, look=3.2)
            pg.wait_for_timeout(700 if not REAL else 1500)
            shot(pg, 'hepgo-06-pod4-launch.png')
            sade(pg, False)
            bekle(lambda: (ss.tele.get('alt_rel') or 0) > 8, 60, 'pod4 tırmanış')
            pg.wait_for_timeout(1500)
            print('  pod4 sonrası:', pg.evaluate('window.__fsSim.launcherInfo()'), flush=True)
            bitir(pg, sid)
        # ---- 07 tüp
        if want('tube'):
            sid, ss = oturum(pg, {'method': 'tube'}, targets=False)
            sade(pg); yakin(pg, ang=210, k=2.2, hk=1.4); pg.wait_for_timeout(3500)
            shot(pg, 'hepgo-07-tube.png'); sade(pg, False)
            bitir(pg, sid)
        # ---- 08–10 el fırlatıcısı + nişangâh
        if want('hand'):
            sid, ss = oturum(pg, {'method': 'handheld', 'aim_az_deg': 40, 'aim_el_deg': 30})
            pg.wait_for_function('() => window.__fsSim.targetsInfo().length === 3', timeout=120000)
            a = pg.evaluate('window.__fsSim.aimAtTarget()')
            print('  hedefe nişan:', a, flush=True)
            sade(pg); yakin(pg, ang=(180 - a['az'] - 40) % 360 if a else 190, k=0.85, hk=0.55, look=0.7)   # önden-sağdan (pilot nişan azimutuna bakar); pg.wait_for_timeout(4000)
            shot(pg, 'hepgo-08-handheld.png')
            ekran_yakin(pg, d=1.1, up=0.35); pg.wait_for_timeout(3500)
            shot(pg, 'hepgo-08b-handheld-screen.png')
            sade(pg, False); sade(pg, True, scope=False)
            yakin(pg, ang=(a['az'] + 200) % 360 if a else 190, k=1.1, hk=0.8, look=0.8)
            pg.wait_for_timeout(2500)
            pg.evaluate("window.__fsSim.setScopeZoom(2)"); pg.wait_for_timeout(2500)
            print('  nişangâh:', pg.evaluate('(() => { const h = window.__fsSim.scopeHud(); return h && { n: h.items.length, aim: h.aim, fov: h.fov }; })()'), flush=True)
            shot(pg, 'hepgo-09-scope.png'); sade(pg, False)
            if REAL:
                time.sleep(20)
            pg.evaluate("window.__fsSim.setScopeZoom(1)")
            sade(pg); yakin(pg, ang=(a['az'] + 110) % 360 if a else 190, k=1.3, hk=0.7, look=0.9)
            aim = pg.evaluate('window.__fsSim.getAim()')
            cmd(sid, 'takeoff', {'alt': 60, 'aim': {'az_deg': round(aim['az'], 1), 'el_deg': round(aim['el'], 1)}})
            bekle(lambda: ss.launch_phase in ('launch', 'released'), 30, 'el launch')
            pg.wait_for_timeout(1000 if not REAL else 1600)
            shot(pg, 'hepgo-10-hand-launch.png'); sade(pg, False)
            bitir(pg, sid)
        # ---- 11–12 görev: 8'li kutular (12 interceptor → 2 kutu; raf yok)
        if want('defend'):
            sid, ss = oturum(pg, {'method': 'pod8'}, targets=False, site={'station': True, 'radar': True, 'radar_km': 20, 'eo': True, 'eo_km': 5},
                             defend={'seed': 7, 'waves': 2, 'interceptors': 12, 'difficulty': 'easy', 'prep_s': 300})
            info = pg.evaluate('window.__fsSim.launcherInfo()')
            print('  görev pod8:', info['inventory'], 'raf:', pg.evaluate('window.__fsSim.siteInfo()')['rackN'], flush=True)
            sade(pg); yakin(pg, ang=200, k=1.5, hk=2.2); pg.wait_for_timeout(3500)
            shot(pg, 'hepgo-11-defend-pod8.png'); sade(pg, False)
            bitir(pg, sid)
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
    time.sleep(8.0)
