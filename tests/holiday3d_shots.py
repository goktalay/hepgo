"""Bayram süsleri — UÇUŞ SAHNESİ görselleri (docs/bayram-temalari.md › Uçuş sahnesi) → /tmp/bayram3d-shots/<uygulama>-*.png
Sahte SITL (HEPGO_SITL=0) + yazılım WebGL (SwiftShader). Uçuş adresi ?bayram=kurban önizlemesiyle açılır (ayar yolu: holidayDecorSpec), diğer temalar
sim.setHoliday ile değiştirilir. Denetimler: 3B süs kuruldu (üçgen ≤ 20 000), uçuşta 2B bayram katmanı / kutlama şeridi YOK, koyunlar çayırda.
  kurban: Takip (dron çayırın yanında asılı) + Yer kamerası · ramazan (gündüz + gece) · noel · cadilar · bagimsizlik
Çalıştırma: ./.venv/bin/python -m tests.holiday3d_shots hepgo   |   ./.venv/bin/python -m tests.holiday3d_shots simumav
"""
import math
import os
import shutil
import socket
import sys
import threading
import time

APP = (sys.argv[1] if len(sys.argv) > 1 else 'hepgo').lower()
assert APP in ('hepgo', 'simumav'), APP
os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
PORT = int(os.environ.get('SHOT_PORT') or (8935 if APP == 'hepgo' else 8936))
DATA = f'/tmp/bayram3d-data-{APP}'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
OUT = '/tmp/bayram3d-shots'
os.makedirs(OUT, exist_ok=True)
if APP == 'hepgo':
    os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                      CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                      HEPGO_SITL='0', SIM_UDP_BASE='39750', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', CAYMAZ_ENV_FILE=os.path.join(DATA, 'yok.env'))
else:
    os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='29750', SIMUMAV_MAX_FLIGHTS='4',
                      SIMUMAV_MP_PORT_BASE='30700', SIMUMAV_MP_PORT_COUNT='20', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                      SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='')
BASE = f'http://127.0.0.1:{PORT}'
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import flightsim  # noqa: E402
from app import flightsim_match_core as core  # noqa: E402

if APP == 'hepgo':
    from app import auth  # noqa: E402
    from app.main import app as APPOBJ  # noqa: E402
else:
    import app.simumav.main as smain  # noqa: E402
    from app.simumav import config as SC  # noqa: E402
    APPOBJ = smain.app
    for _k in ('session', 'write', 'read'):
        SC.RATE[_k] = (100000, 60)
server = uvicorn.Server(uvicorn.Config(APPOBJ, host='127.0.0.1', port=PORT, log_level='error'))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(200):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close()
        break
    except OSError:
        time.sleep(0.25)
else:
    sys.exit('sunucu açılmadı')
time.sleep(1)
SIMV = '__fsSim' if APP == 'hepgo' else '__smSim'
sonuc, hatalar = [], []


def kontrol(ad, kosul):
    print(('  ✓ ' if kosul else '  ✗ ') + ad, flush=True)
    if not kosul:
        hatalar.append(ad)


def bekle(fn, sn=120, adim=0.5):
    t = time.time() + sn
    while time.time() < t:
        try:
            v = fn()
        except Exception:   # noqa: BLE001
            v = None
        if v:
            return v
        time.sleep(adim)
    return None


def shot(pg, ad):
    pg.screenshot(path=f'{OUT}/{APP}-{ad}.png')
    sonuc.append(f'{OUT}/{APP}-{ad}.png')
    print('  ·', f'{APP}-{ad}.png', flush=True)


def asili(ss, x, y, z, yaw_deg):
    """Sahte kinematik: evden (x doğu, y kuzey) noktada z m'de asılı (LOITER)."""
    k = ss.sahte

    def adim(dt):
        k.sure_ms += dt * 1000
        k.armed, k.mode = True, 'LOITER'
        k.lat, k.lon = core.latlon(k.lat0, k.lon0, x, y)
        k.alt_rel = z
        k.yaw = math.radians(yaw_deg)
        k.vn = k.ve = 0.0
        k.throttle = 55.0
    k.adim = adim


def katman_yok(pg):
    """Uçuşta 2B bayram katmanı / kutlama şeridi görünmüyor mu"""
    r = pg.evaluate("""(() => { const c = [...document.querySelectorAll('canvas.holiday-fx')].map(e => getComputedStyle(e).opacity);
      const b = [...document.querySelectorAll('.hfx-banner')].filter(e => e.classList.contains('on')).length; return { canvases: c, banners: b }; })()""")
    return r, all(float(o) == 0 for o in r['canvases']) and r['banners'] == 0


def sahne(pg, ss, th, kip='follow', isim=None, gece=False):
    info = pg.evaluate(f"window.{SIMV}.holidayInfo()")
    sp = [s for s in info['spots'] if s['kind'] not in ('fireworks', 'roof_flags', 'snow', 'gifts', 'butterflies')]
    hedef = sp[0] if sp else {'x': 60, 'y': 60, 'r': 5}
    x, y = hedef['x'], hedef['y']
    d = math.hypot(x, y) or 1
    if kip == 'follow':   # takip kamerası dronun güneybatısından kuzeydoğuya bakar → dron süsün güneybatısında, alçakta
        r = hedef['r'] + 6
        asili(ss, x - r * 0.75, y - r * 0.75, 7 if hedef['r'] > 10 else 5, 45)
    else:   # Yer kamerası (45, −70) → dron, kamera ile süs arasında
        cx, cy = 45, -70
        asili(ss, cx + (x - cx) * 0.55, cy + (y - cy) * 0.55, 5, 45)
    pg.evaluate(f"window.{SIMV}.setCamera('{kip}')")
    pg.wait_for_timeout(6000)
    shot(pg, isim or f'{th}-{kip}' + ('-gece' if gece else ''))


THEMES = ['kurban', 'ramazan', 'noel', 'cadilar', 'bagimsizlik']
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        if APP == 'hepgo':
            s = requests.Session()
            assert s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'}).status_code == 200
            s.post(f'{BASE}/api/kvkk/accept-terms', json={})
            c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Test Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
            WORLD = {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'mountain_height': 250, 'building_count': 30, 'tree_density': 0.2, 'time': 'day', 'wind_ms': 5, 'wind_dir': 300,
                     'runway_heading': 20, 'fog': 0.15}
            ctx = b.new_context(viewport={'width': 1280, 'height': 720}, locale='tr-TR')
            ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
            ctx.add_init_script("try { localStorage.setItem('fs.gfx', JSON.stringify({ preset: 'high' })); localStorage.setItem('fs.rec.on', '0'); } catch (e) {}")
            pg = ctx.new_page()
            pg.set_default_timeout(300000)
            pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
            pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:400]}') if m.type == 'error' and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text and 'WebGL' not in m.text else None)
            pg.goto(f'{BASE}/app?bayram=kurban#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(2500)
            r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False}, 'world': WORLD})
            assert r.status_code == 201, r.text
            sid = r.json()['id']
            ss = flightsim.MANAGER.sessions[sid]
            bekle(lambda: ss.state == 'HAZIR' and ss.sahte is not None, 120)
            pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
            pg.wait_for_timeout(6000)
            if not pg.locator('.fs-stage').count():
                pg.evaluate("location.hash = '#/drone/sim'"); pg.wait_for_timeout(1500)
                pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
            pg.wait_for_function('() => window.__fsSim && window.__fsSim.holidayInfo', timeout=240000)
            for _ in range(60):
                if pg.evaluate('window.__fsSim.holidayInfo()'):
                    break
                pg.wait_for_timeout(1000)
            else:
                print('  teşhis:', pg.evaluate("({ href: location.href, hi: window.__fsSim.holidayInfo() })"), hatalar, flush=True)
            pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
            pg.wait_for_timeout(8000)   # giriş sekansı
            pg.keyboard.press('p'); pg.wait_for_timeout(300)
        else:
            H = {'Origin': BASE}
            ali = requests.Session()
            assert ali.post(f'{BASE}/api/session', json={'dev_user': 'ali'}, headers=H).status_code == 200
            pid = ali.get(f'{BASE}/api/crew').json()['pilots'][0]['id']
            dr = ali.post(f'{BASE}/api/hangar', json={'name': 'IRIS', 'type': 'multirotor', 'model_key': 'glb:iris', 'color': '#f97316'}, headers=H).json()
            trk = ali.post(f'{BASE}/api/tracks', json={'name': 'Bayram Sahası', 'lat': 40.10, 'lon': 33.40, 'radius_m': 800, 'world_mode': 'procedural', 'weather': 'clear',
                                                       'world': {'seed': 9, 'runway': True, 'tree_density': 0.12, 'building_count': 12, 'runway_deg': 20}}, headers=H).json()
            st = ali.get(f'{BASE}/api/settings').json()
            kontrol(f"SIMUMAV ayarı holiday_3d varsayılan açık ({st.get('holiday_3d')})", st.get('holiday_3d') is True)
            assert ali.put(f'{BASE}/api/settings', json={'holiday_3d': False}, headers=H).status_code == 200
            kontrol('holiday_3d kapat → GET false', ali.get(f'{BASE}/api/settings').json().get('holiday_3d') is False)
            ali.put(f'{BASE}/api/settings', json={'holiday_3d': True}, headers=H)
            f = ali.post(f'{BASE}/api/fly/start', json={'drone_id': dr['id'], 'pilot_id': pid, 'track_id': trk['id'], 'record': {'bin': False, 'video': False}}, headers=H)
            assert f.status_code == 201, f.text
            fid, sid = f.json()['flight_id'], f.json()['sim_id']
            ss = flightsim.MANAGER.sessions[sid]
            ctx = b.new_context(viewport={'width': 1280, 'height': 720}, locale='tr-TR')
            ctx.add_cookies([{'name': 'smsid', 'value': ali.cookies['smsid'], 'url': BASE}])
            ctx.add_init_script("try { localStorage.setItem('sm:lang', 'tr'); localStorage.setItem('simumav.lang', 'tr'); localStorage.setItem('simumav.consent', 'denied'); localStorage.setItem('fs.rec.on', '0'); localStorage.setItem('sm.gfx', JSON.stringify({ preset: 'high' })); localStorage.setItem('sm.rcOn', 'false'); } catch (e) {}")
            pg = ctx.new_page()
            pg.set_default_timeout(300000)
            pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
            pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:400]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
            pg.goto(f'{BASE}/app/?bayram=kurban#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(1500)
            pg.goto(f'{BASE}/app/?bayram=kurban#/fly/{fid}', wait_until='domcontentloaded')
            pg.wait_for_function('() => window.__smSim && window.__smSim.holidayInfo && window.__smSim.holidayInfo()', timeout=300000)
            pg.wait_for_timeout(9000)
            pg.keyboard.press('p'); pg.wait_for_timeout(300)
        info = pg.evaluate(f'window.{SIMV}.holidayInfo()')
        print('  süs:', {k: info[k] for k in ('themes', 'level', 'counts', 'tris', 'draws', 'avgMs')}, flush=True)
        kontrol(f"?bayram=kurban → 3B koyunlar ({info['counts'].get('sheep')}), üçgen {info['tris']} ≤ 20000", info['themes'] == ['kurban'] and 6 <= info['counts'].get('sheep', 0) <= 12 and info['tris'] <= 20000)
        r, ok = katman_yok(pg)
        kontrol(f'uçuşta 2B bayram katmanı yok (tuval saydamlıkları {r["canvases"]}, şerit {r["banners"]})', ok)
        sahne(pg, ss, 'kurban', 'follow', 'kurban-takip')
        sh = pg.evaluate(f'window.{SIMV}.holidaySheep()')
        pg.wait_for_timeout(10000)   # yazılım WebGL düşük kare hızında (dt ≤ 0,1 sn/kare) yürüme yavaş ilerler
        sh2 = pg.evaluate(f'window.{SIMV}.holidaySheep()')
        moved = sum(1 for a, c in zip(sh, sh2) if math.hypot(a['x'] - c['x'], a['y'] - c['y']) > 0.02)
        kontrol(f'koyunlar geziniyor ({moved}/{len(sh)} hareket etti; durumlar {sorted({x["st"] for x in sh2})})', moved >= 1)
        sahne(pg, ss, 'kurban', 'ground', 'kurban-yer')
        st = pg.evaluate(f'window.{SIMV}.collisionState()')
        kontrol(f"süs çarpışma üretmez (kind {st.get('kind')})", not st.get('kind'))
        for th in THEMES[1:]:
            i2 = pg.evaluate(f"window.{SIMV}.setHoliday({{ themes: ['{th}'], country: 'TR' }})")
            pg.wait_for_timeout(1500)
            kontrol(f"{th}: {i2['counts']} · üçgen {i2['tris']}", i2['tris'] <= 20000 and i2['items'] > 0)
            sahne(pg, ss, th, 'follow')
        # ramazan gece (fenerler ışıklı) — dünya gece kipine
        pg.evaluate(f"window.{SIMV}.setHoliday({{ themes: ['ramazan'], country: 'TR' }})")
        if APP == 'hepgo':
            pg.evaluate(f"window.{SIMV}.setWorld({{ ...{__import__('json').dumps(WORLD)}, time: 'dusk' }})")
        else:
            pg.evaluate(f"(() => {{ const S = window.{SIMV}; return S.setWorld({{ mode: 'procedural', seed: 9, runway: true, tree_density: 0.12, building_count: 12, runway_heading: 20, time: 'dusk' }}); }})()")
        pg.wait_for_timeout(4000)
        sahne(pg, ss, 'ramazan', 'follow', 'ramazan-aksam', gece=True)
        r, ok = katman_yok(pg)
        kontrol('sonda da uçuşta 2B katman yok', ok)
        print('  kare süresi (ms):', pg.evaluate(f'window.{SIMV}.holidayInfo().avgMs'), flush=True)
        b.close()
except Exception:
    import traceback
    traceback.print_exc()
    hatalar.append('İSTİSNA')
    try:
        print('  teşhis:', pg.evaluate(f"(() => ({{ hash: location.hash, search: location.search, sim: !!window.{SIMV}, hi: window.{SIMV}?.holidayInfo?.() ?? 'yok', stage: !!document.querySelector('.fs-stage') }}))()"), flush=True)
        pg.screenshot(path=f'{OUT}/{APP}-hata.png', timeout=60000)
    except Exception as e:   # noqa: BLE001
        print('  teşhis alınamadı', e)
finally:
    server.should_exit = True
print('\nGÖRÜNTÜLER:', *sonuc, sep='\n  ')
print('HATALAR:' if hatalar else 'hata yok', *hatalar, sep='\n  ')
sys.exit(1 if hatalar else 0)
