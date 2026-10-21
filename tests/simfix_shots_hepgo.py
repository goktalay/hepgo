"""HEPGO Uçuş Simülatörü — radar/EO tam görüntü, EO zoom + pan/tilt, alt bant mod seçici + DISARM, çarpışma efekti — görsel doğrulama
(Playwright headless shell + SwiftShader). Uygulama aynı süreçte; sahte kinematik (HEPGO_SITL=0) ya da SIMFIX_REAL=1 + HEPGO_SITL_DIR → gerçek SITL.
Dünya: SIMFIX_WORLD = procedural (vars.) | real | google3d (anahtar DEV .env'den okunur, YAZDIRILMAZ).
Görüntüler /tmp/simfix-shots/hepgo-<dünya>-*.png; her karede radar/EO dikdörtgeninin "boş (çok koyu) piksel" oranı yazılır.
Çalıştırma: ./.venv/bin/python -m tests.simfix_shots_hepgo
"""
import io
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
WORLD = os.environ.get('SIMFIX_WORLD') or 'procedural'
REAL = os.environ.get('SIMFIX_REAL') == '1'
DATA = '/tmp/simfix-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
key = ''
if WORLD == 'google3d':
    for ln in pathlib.Path('/opt/hepgo/fabrika-yonetim/.env').read_text().splitlines():
        if ln.startswith('GOOGLE_MAPS_API_KEY='):
            key = ln.split('=', 1)[1].strip().strip('"\'')
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1' if REAL else '0', SIM_UDP_BASE='39650', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY=key)
PORT = int(os.environ.get('SHOT_PORT') or 8867)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/simfix-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from PIL import Image  # noqa: E402
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
P = f'hepgo-{WORLD}'


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
    pg.screenshot(path=str(OUT / f'{P}-{ad}'))
    print('  kare', f'{P}-{ad}', flush=True)


def bos_oran(pg, sel):
    """Seçilen kutunun (radar/EO gövdesi) çok koyu (boş) piksel oranı."""
    bb = pg.locator(sel).bounding_box()
    if not bb:
        return None
    im = Image.open(io.BytesIO(pg.screenshot(clip=bb))).convert('L')
    px = list(im.getdata())
    return round(sum(1 for v in px if v < 22) / max(1, len(px)), 3)


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
    bekle(lambda: ss.state == 'HAZIR' and (ss.sahte is not None or ss._heartbeat_alindi), 180, 'HAZIR')
    pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
    pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera', timeout=240000)
    pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
    pg.evaluate('window.__fsIntroHold = null')
    pg.wait_for_timeout(6000)   # giriş sekansı + karolar
    return sid, ss


WMODE = {'procedural': {'mode': 'procedural', 'seed': 11, 'size_m': 4000}, 'real': {'mode': 'real', 'size_m': 4000}, 'google3d': {'mode': 'google3d'}}[WORLD]
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(2500)
        # ---- A) INTERCEPTOR + saha + görev: radar / EO
        body = {'mode': 'sitl', 'type': 'interceptor', 'center_id': c['id'], 'rec': {'bin': False},
                'world': {**WMODE, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.25, 'building_count': 20, 'runway_heading': 20},
                'site': {'station': True, 'radar': True, 'radar_km': 20, 'eo': True, 'eo_km': 5},
                'targets': {'items': [{'model': 'tgt:octopus', 'alt_m': 150, 'diameter_m': 1600, 'speed_ms': 30, 'dir': 'cw', 'phase_deg': 0, 'name': 'Av'},
                                      {'model': 'tgt:lancet', 'alt_m': 300, 'diameter_m': 5000, 'speed_ms': 40, 'dir': 'ccw', 'phase_deg': 120, 'name': 'Av2'}], 'radius_m': 25}}
        sid, ss = oturum(pg, body)
        print('  dünya:', pg.evaluate('({g: window.__fsSim.google, st: window.__fsSim.siteStats()})'), flush=True)
        cmd(sid, 'takeoff', {'alt': 70})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 50, 120, 'kalkış')
        pg.wait_for_timeout(9000 if WORLD == 'google3d' else 4000)
        print('  radar boş oranı:', bos_oran(pg, '.fs-site-scr.radar .fs-site-bd'), 'EO boş oranı:', bos_oran(pg, '.fs-site-scr.eo .fs-site-bd'),
              pg.evaluate('window.__fsSim.siteStats()'), flush=True)
        shot(pg, '01-radar-eo-full.png')
        # EO: hedef seç (radar tıklaması) → izler; sonra tekerlek zoom + sürükle pan/tilt → elle (takip bırakılır)
        items = pg.evaluate('(window.__fsSim.radarInfo()?.items || [])')
        if items:
            bb = pg.locator('.fs-site-scr.radar .fs-site-bd').bounding_box()
            pg.mouse.click(bb['x'] + items[0]['x'], bb['y'] + items[0]['y'])
            bekle(lambda: pg.evaluate('window.__fsSim.eoInfo()?.status') in ('track', 'out'), 30, 'EO izleme')
            pg.wait_for_timeout(2500)
            shot(pg, '02-eo-track.png')
        eb = pg.locator('.fs-site-scr.eo .fs-site-bd').bounding_box()
        cx, cy = eb['x'] + eb['width'] / 2, eb['y'] + eb['height'] / 2
        z0 = pg.evaluate('window.__fsSim.eoInfo()')
        pg.mouse.move(cx, cy)
        for _ in range(6):
            pg.mouse.wheel(0, 120); pg.wait_for_timeout(120)   # uzaklaştır (izlemedeyken oto zoom'u elle geçersiz kılar)
        pg.wait_for_timeout(1500)
        z1 = pg.evaluate('window.__fsSim.eoInfo()')
        print('  EO zoom (tekerlek):', round(z0['zoom'], 2), '→', round(z1['zoom'], 2), 'manualZoom', z1['manualZoom'], flush=True)
        if not z1['manualZoom']:
            hatalar.append('EO tekerlek zoom çalışmadı')
        a0 = (z1['az'], z1['el'])
        pg.evaluate("window.__eoPd = 0; document.querySelector('.fs-site-scr.eo .fs-site-bd').addEventListener('pointerdown', () => window.__eoPd++)")
        print('  EO noktasındaki öğe:', pg.evaluate(f"(() => {{ const e = document.elementFromPoint({cx}, {cy}); return e && (e.className || e.tagName); }})()"), flush=True)
        pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx + 80, cy + 30, steps=8); pg.mouse.up()
        print('  pointerdown sayısı:', pg.evaluate('window.__eoPd'), flush=True)
        pg.wait_for_timeout(1500)
        z2 = pg.evaluate('window.__fsSim.eoInfo()')
        print('  EO sürükle: az/el', [round(x, 1) for x in a0], '→', round(z2['az'], 1), round(z2['el'], 1), 'durum', z2['status'], 'takip', z2['follow'], flush=True)
        if z2['follow'] or abs(((z2['az'] - a0[0] + 540) % 360) - 180) < 1:
            hatalar.append('EO sürükleme pan/tilt çalışmadı')
        shot(pg, '03-eo-manual-pan-zoom.png')
        az_h = z2['az']; pg.wait_for_timeout(3000)
        if abs(((pg.evaluate('window.__fsSim.eoInfo().az') - az_h + 540) % 360) - 180) > 0.5:
            hatalar.append('EO elle konumda sabit kalmadı (döndü)')
        # Takip düğmesi → takibe dön
        if pg.locator('.fs-site-fol:not([hidden])').count():
            pg.locator('.fs-site-fol').click(); pg.wait_for_timeout(2500)
            print('  Takip →', pg.evaluate('window.__fsSim.eoInfo().status'), flush=True)
        # hedef bırak → EO son yönde sabit (tarama yok)
        pg.evaluate('window.__fsSim.lockTarget(null)'); pg.wait_for_timeout(800)
        a1 = pg.evaluate('window.__fsSim.eoInfo().az'); pg.wait_for_timeout(4000); a2 = pg.evaluate('window.__fsSim.eoInfo().az')
        print('  hedefsiz EO az:', round(a1, 2), '→', round(a2, 2), flush=True)
        if abs(((a2 - a1 + 540) % 360) - 180) > 0.5:
            hatalar.append('EO hedefsizken dönüyor (tarama)')
        # radar: kule merkezli farklı menziller (altlık + karo)
        for km in (50, 5):
            pg.evaluate(f'window.__fsSim.setRadarRange({km})'); pg.wait_for_timeout(5000 if WORLD == 'google3d' else 2500)
            print(f'  radar {km} km boş oranı:', bos_oran(pg, '.fs-site-scr.radar .fs-site-bd'), flush=True)
            shot(pg, f'04-radar-{km}km.png')
        pg.evaluate('window.__fsSim.setRadarRange(null)')
        # PiP (ikincil kamera) — gimbal görüntüsü
        pg.evaluate("window.__fsSim.setPip(true)"); pg.wait_for_timeout(3000)
        shot(pg, '05-pip.png'); pg.evaluate("window.__fsSim.setPip(false)")
        # çarpışma efekti (sunucu çarpışma kaydı → bant + efekt + ses)
        cmd(sid, 'crash', {'kind': 'building', 'speed': 42.3})
        pg.evaluate('window.__fsCrashHold = 0.02')   # yavaş yazılım WebGL: efekt zamanını sabitle
        pg.wait_for_selector('.fs-crash:not([hidden])', timeout=20000)
        print('  efekt:', pg.evaluate('window.__fsSim.crashFxInfo()'), flush=True)
        pg.wait_for_timeout(1500); shot(pg, '06-crash-fx-flash.png')
        pg.evaluate('window.__fsCrashHold = 0.35'); pg.wait_for_timeout(2500); shot(pg, '07-crash-fx-fireball.png')
        pg.evaluate('window.__fsCrashHold = 2.2'); pg.wait_for_timeout(2500); shot(pg, '07b-crash-fx-dust.png')
        # termal: EO kamerası (termal) elle çarpışma yerine çevrilir (sürükleme API'siyle) — ateş topu / kor sıcak
        pg.evaluate('''(() => { const S = window.__fsSim, tw = S.siteInfo().tower, d = S.position(), i = S.eoInfo(), h = 180;
          const dx = d.x - tw[0], dy = d.y - tw[1], g = Math.hypot(dx, dy), az = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360, el = Math.atan2(d.z + 1 - tw[2] - 18, g) * 180 / Math.PI;
          let da = az - i.az; while (da > 180) da -= 360; while (da < -180) da += 360;
          S.eoDrag(-da * h / i.fov, (el - i.el) * h / i.fov, h); S.eoWheel(-700); S.setEoType('thermal'); })()''')
        pg.evaluate("window.__fsCrashHold = 0.6"); pg.wait_for_timeout(3500)
        shot(pg, '08-crash-fx-thermal-eo.png'); pg.evaluate("window.__fsSim.setEoType('day'); window.__fsCrashHold = null")
        cmd(sid, 'reset'); pg.wait_for_timeout(3000)
        s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        # ---- B) sabit kanat: alt bant mod seçici + DISARM / motor kes (panel açıkken de)
        body = {'mode': 'sitl', 'type': 'sabit_kanat', 'center_id': c['id'], 'rec': {'bin': False},
                'world': {**WMODE, 'time': 'day', 'wind_ms': 0, 'runway_heading': 20}, 'launch': {'method': 'wheels'}}
        sid, ss = oturum(pg, body)
        shot(pg, '09-bar-flight-controls.png')
        pg.keyboard.press('f'); pg.wait_for_timeout(600)
        shot(pg, '10-mode-menu.png')
        pg.locator('.fs-flt-grid button[data-mode="FBWA"]').click(); pg.wait_for_timeout(1500)
        print('  mod:', ss.tele.get('mode'), flush=True)
        cmd(sid, 'takeoff', {'alt': 100})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 80, 180, 'kalkış 100 m')
        pg.wait_for_timeout(1500)
        print('  DISARM düğmesi:', pg.evaluate("document.querySelector('.fs-flt-x').textContent"), '/', pg.evaluate("document.querySelector('.fs-flt-x').title"), flush=True)
        pg.locator('.fs-flt-x').click(); pg.wait_for_timeout(2500)
        t0 = time.time(); a0 = ss.tele.get('alt_rel')
        pg.wait_for_timeout(5000)
        print('  motor kes:', {k: ss.tele.get(k) for k in ('armed', 'motor_cut', 'mode', 'throttle', 'airspeed', 'alt_rel', 'climb')}, 'irtifa', a0, '→', ss.tele.get('alt_rel'), f'{time.time() - t0:.1f} sn', flush=True)
        shot(pg, '11-motor-cut-glide.png')
        pg.keyboard.press('p'); pg.wait_for_timeout(1500)   # harekât paneli açık/kapalı — bant yine görünür
        shot(pg, '12-panel-toggle-bar.png')
        s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / f'{P}-hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(6.0)
