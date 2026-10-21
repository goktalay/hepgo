"""HEPGO Uçuş Simülatörü §8.5 — KAYITTAN OYNATMA GİRİŞLERİ: görsel doğrulama + uçtan uca akış (Playwright headless shell; sahte SITL HEPGO_SITL=0).
Kullanıcı isteği: kaydı izlemek sihirbazsız ve kaydın ayarlarıyla; saha görevi logları simülatörde görünmesin; Saha yönetiminde "Simüle et" ile
atmosfer/rampa sorulsun. Uygulama aynı süreçte açılır ve betik bitince kapanır. Görüntüler /tmp/replayfix-shots/:
  01 Kayıtlı Simülasyonlar uçuş kartı (Oynat) → 02 hazırlık kartı → 03 sihirbaz AÇILMADAN izleme (kayıttaki yağmur/alacakaranlık/rampa 22°·135°)
  04 Simülasyon Kayıtları tablosu Oynat → doğrudan izleme · 05 Yeni Simülasyon › Kayıttan oynat listesi (yalnız simülatör kaydı; saha/gerçek log yok)
  06 Saha görevi uçuş tablosu "Simüle et" → 07 sihirbaz log sabit, Dünya adımında (atmosfer) → 08 Kalkış adımı (rampa sorulur) · 09 Uçuş Logu Analizi "Simüle et"
Çalıştırma: ./.venv/bin/python -m tests.replayfix_shots_hepgo
"""
import json
import math
import os
import pathlib
import re
import shutil
import socket
import struct
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/replayfix-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39750', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='4')
PORT = int(os.environ.get('SHOT_PORT') or 8867)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/replayfix-shots')
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth, config, db  # noqa: E402
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
hatalar = []
POSTLAR = []   # tarayıcının POST istekleri (Oynat → /runs/{id}/replay)


def tlog_yaz(yol, plane=True, lat0=39.925, lon0=32.837, alt0=900.0, sure=70.0):
    """Küçük .tlog: 10 sn yerde, ARM, pist yönünde kalkış + 120 m yarıçaplı daire, iniş, DISARM (ArduPlane ya da ArduCopter)."""
    from pymavlink.dialects.v20 import ardupilotmega as D
    mav = D.MAVLink(None, srcSystem=1, srcComponent=1)
    t_abs = 1_760_000_000.0
    with open(yol, 'wb') as f:
        def yaz(msg, t):
            f.write(struct.pack('>Q', int(t * 1e6))); f.write(msg.pack(mav)); mav.seq = (mav.seq + 1) % 256
        t = 0.0
        while t <= sure:
            armed = 10.0 <= t < 62.0
            if 12 <= t < 58 and armed:
                ang = (t - 12) / 46 * 2 * math.pi
                r = 120.0
                lat, lon, z = lat0 + r * math.sin(ang) / 110574, lon0 + r * (1 - math.cos(ang)) / (111320 * math.cos(math.radians(lat0))), 40.0 * min(1, (t - 12) / 6)
                vn, ve = r * 2 * math.pi / 46 * math.cos(ang), r * 2 * math.pi / 46 * math.sin(ang)
            else:
                lat, lon, z, vn, ve = lat0, lon0, 0.0, 0.0, 0.0
            yaw = math.atan2(ve, vn) if (vn or ve) else 0.0
            if abs(t - round(t)) < 1e-6:
                yaz(mav.heartbeat_encode(1 if plane else 2, 3, (128 if armed else 0) | 1, (10 if armed and t >= 12 else 0), 4), t_abs + t)
                yaz(mav.gps_raw_int_encode(int((t_abs + t) * 1e6), 3, int(lat * 1e7), int(lon * 1e7), int((alt0 + z) * 1000), 120, 80, 0, 0, 12), t_abs + t)
                if t == 0:
                    yaz(mav.statustext_encode(6, b'ArduPlane V4.5.7 (test)' if plane else b'ArduCopter V4.5.7 (test)'), t_abs + t)
            yaz(mav.global_position_int_encode(int(t * 1000), int(lat * 1e7), int(lon * 1e7), int((alt0 + z) * 1000), int(z * 1000),
                                               int(vn * 100), int(ve * 100), 0, int((math.degrees(yaw) % 360) * 100)), t_abs + t)
            yaz(mav.attitude_encode(int(t * 1000), 0.25 if 12 <= t < 58 else 0.0, 0.05 if armed else 0.0, yaw, 0, 0, 0), t_abs + t)
            yaz(mav.vfr_hud_encode(math.hypot(vn, ve) + 1, math.hypot(vn, ve), int(math.degrees(yaw) % 360), 60 if armed else 0, alt0 + z, 0.0), t_abs + t)
            t = round(t + 0.2, 3)


def log_ekle(conn, ad, yol, origin, vehicle, aircraft, task_id=None, flight_id=None, pilot=None, location=None):
    ozet = json.dumps({'summary': {'vehicle': vehicle, 'flight_s': 50, 'duration_s': 70, 'home': {'lat': 39.925, 'lng': 32.837, 'alt': 900}}})
    return conn.execute('''INSERT INTO flight_logs (task_id, flight_id, file, file_name, size, status, analysis, aircraft, pilot, location, uploaded_by, uploaded_at, origin)
                           VALUES (?, ?, ?, ?, ?, 'TAMAM', ?, ?, ?, ?, 1, ?, ?)''',
                        (task_id, flight_id, f'flightlogs/{yol.name}', ad, yol.stat().st_size, ozet, aircraft, pilot, location, db.now(), origin)).lastrowid


def oturum(kullanici, sifre):
    r = requests.Session()
    assert r.post(f'{BASE}/api/auth/login', json={'username': kullanici, 'password': sifre}).status_code == 200, kullanici
    r.post(f'{BASE}/api/kvkk/accept-terms', json={})
    r.post(f'{BASE}/api/location/consent', json={'granted': False})
    return r


s = oturum('demo@firma.com', 'Demo-Sifre-12')
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Test Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
S_ = f'{BASE}/api/drone/sim/sessions'
R_ = f'{BASE}/api/drone/sim/runs'
P_ = f'{BASE}/api/drone/sim/presets'

# ---------- 1) bir simülasyon oturumu KAYDET: sabit kanat, yağmur + alacakaranlık + rüzgâr, rampa 22° · 135°, termal kamera ----------
AYAR = {'type': 'sabit_kanat', 'center_id': c['id'], 'camera': 'thermal', 'model': {'id': 'builtin:caymaz'}, 'rec': {'bin': True},
        'world': {'mode': 'procedural', 'seed': 4242, 'size_m': 3000, 'time': 'dusk', 'weather': 'rain', 'wind_ms': 8, 'wind_dir': 220, 'fog': 0.25,
                  'launch': {'method': 'ramp', 'angle_deg': 22, 'azimuth_deg': 135}}}
k1 = s.post(P_, json={'name': 'Yağmurda rampa kalkışı', 'description': 'Alacakaranlık, yağmur, rampa 22° · 135°; termal kamera.', 'pilot_id': None, 'settings': AYAR}).json()
r = s.post(f"{P_}/{k1['id']}/start", json={'rec': {'bin': True}})
assert r.status_code == 201, r.text
sid = r.json()['id']
for _ in range(60):
    if s.get(f'{S_}/{sid}').json().get('state') == 'HAZIR':
        break
    time.sleep(0.2)
s.post(f'{S_}/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40}})
time.sleep(3)
s.delete(f'{S_}/{sid}')
time.sleep(1.5)
run = s.get(R_, params={'preset': k1['id']}).json()['items'][0]
assert run['world'].get('weather') == 'rain' and run['world']['launch']['angle_deg'] == 22, run['world']
# sahte SITL .BIN üretmez: kaydın .bin'i yerine aynı uçuşun MAVLink kaydı (.tlog, kaynak SIM) bağlanır — oynatılabilir log
d = config.UPLOAD_DIR / 'flightlogs'
d.mkdir(parents=True, exist_ok=True)
tlog_yaz(d / 'sim-kayit.tlog', plane=True)
shutil.copy(d / 'sim-kayit.tlog', d / 'saha-ucus.tlog')
shutil.copy(d / 'sim-kayit.tlog', d / 'arac-ucus.tlog')
with db.connect() as conn:
    sim_lid = log_ekle(conn, f"SIM-{sid}-20261021-1000.tlog", d / 'sim-kayit.tlog', 'SIM', 'ArduPlane', 'Simülatör · Sabit Kanat', pilot='Demo Yönetici', location='Ankara Test Sahası')
    conn.execute('UPDATE drone_sim_runs SET bin_log_id = ? WHERE id = ?', (sim_lid, run['id']))
    # saha görevi + uçuşu + gerçek log (simülatör listesinde GÖRÜNMEMELİ; Saha yönetiminde "Simüle et")
    tid = conn.execute("INSERT INTO field_tasks (code, status, created_by, created_at, started_at) VALUES ('SG-2026-031', 'GOREVDE', 1, ?, ?)", (db.now(), db.now())).lastrowid
    fid = conn.execute("INSERT INTO field_flights (task_id, launch, note) VALUES (?, 'RAMPA', 'Rampa kalkışı, kuzey sırtı')", (tid,)).lastrowid
    saha_lid = log_ekle(conn, '00000031.tlog', d / 'saha-ucus.tlog', 'REAL', 'ArduPlane', 'CZ-07', task_id=tid, flight_id=fid, pilot='A. Yılmaz', location='Akyurt')
    # Araçlar › Uçuş Logu Analizi'ne bağımsız yüklenmiş gerçek log (o da simülatör listesinde yok; Uçuş Logu Analizi'nde "Simüle et")
    arac_lid = log_ekle(conn, '00000044.tlog', d / 'arac-ucus.tlog', 'REAL', 'ArduPlane', 'CZ-09', pilot='B. Kaya', location='Bedesten')
    conn.commit()
print('kayıt', run['id'], 'sim log', sim_lid, 'saha log', saha_lid, 'araç log', arac_lid, 'görev', tid, flush=True)
liste = [x['id'] for x in s.get(f'{BASE}/api/drone/sim/logs').json()]
if liste != [sim_lid]:
    hatalar.append(f'simülatör log listesi {liste} (yalnız {sim_lid} beklenirdi)')


def shot(pg, ad, full=False):
    pg.screenshot(path=str(OUT / ad), timeout=240000, full_page=full)
    print('  kare', ad, flush=True)


def baglam(b, ses, w=1440, hh=900):
    ctx = b.new_context(viewport={'width': w, 'height': hh}, locale='tr-TR')
    ctx.add_cookies([{'name': auth.COOKIE, 'value': ses.cookies.get(auth.COOKIE), 'url': BASE}])
    ctx.add_init_script("try { localStorage.setItem('fs.rec.on', '0'); } catch (e) {}")   # ekran kaydı kapalı (başsız tarayıcıda paylaşım izni yok)
    pg = ctx.new_page()
    pg.set_default_timeout(60000)
    pg.on('request', lambda q: POSTLAR.append(q.url) if q.method == 'POST' else None)
    pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
    pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
    return ctx, pg


def izleme_dogrula(pg, etiket):
    """Oynat → sihirbaz açılmadan hazırlık kartı → oturum ekranı; oturum kaydın ayarlarıyla mı."""
    istek = POSTLAR
    pg.wait_for_function("() => /#\\/drone\\/sim\\/\\d+/.test(location.hash) || document.querySelector('.fs-prep')", timeout=60000)
    if pg.locator('.fs-wizard-modal').count():
        hatalar.append(f'{etiket}: sihirbaz açıldı')
    pg.wait_for_function("() => /#\\/drone\\/sim\\/\\d+/.test(location.hash)", timeout=180000)
    if not any(re.search(r'/api/drone/sim/runs/\d+/replay$', u) for u in istek):   # tabloda en yeni satır ilk oynatmanın kaydı da olabilir (aynı ayarlar)
        hatalar.append(f'{etiket}: POST /runs/{{id}}/replay yok ({istek})')
    if any(u.endswith('/api/drone/sim/sessions') for u in istek):
        hatalar.append(f'{etiket}: sihirbaz yolu (POST /sessions) kullanıldı')
    istek.clear()
    sid_ = int(pg.evaluate("location.hash.match(/sim\\/(\\d+)/)[1]"))
    g = s.get(f'{S_}/{sid_}').json()
    w = g.get('world') or {}
    if g.get('mode') != 'replay' or w.get('weather') != 'rain' or w.get('time') != 'dusk' or w.get('wind_ms') != 8 or w.get('launch', {}).get('angle_deg') != 22 \
            or w.get('launch', {}).get('azimuth_deg') != 135 or g.get('camera') != 'thermal' or g.get('launch', {}).get('method') != 'ramp':
        hatalar.append(f"{etiket}: oturum kaydın ayarlarında değil: mode={g.get('mode')} world={w} launch={g.get('launch')} camera={g.get('camera')}")
    return sid_


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        # ---------- 01–03 Kayıtlı Simülasyonlar uçuş kartı → Oynat → doğrudan izleme ----------
        ctx, pg = baglam(b, s)
        pg.goto(f"{BASE}/#/drone/sim?tab=saved&preset={k1['id']}", wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-sv-runs .fs-sv-run', timeout=60000)
        pg.locator('.fs-sv-runs .fs-sv-run').first.click(); pg.wait_for_timeout(2500)
        shot(pg, '01-kayitli-ucus-karti-oynat.png')
        pg.locator('.fs-sv [data-act="play"]').first.click()
        try:
            pg.wait_for_selector('.fs-prep', timeout=8000); pg.wait_for_timeout(200)
            shot(pg, '02-hazirlik-karti.png')
        except Exception:   # noqa: BLE001 — önbellekli/kısa kayıtta kart çok kısa sürebilir
            print('  (hazırlık kartı yakalanamadı — çok hızlı)', flush=True)
        sid1 = izleme_dogrula(pg, 'kayıtlı kart Oynat')
        pg.wait_for_timeout(6000)
        shot(pg, '03-dogrudan-izleme.png')
        s.delete(f'{S_}/{sid1}'); time.sleep(1)
        ctx.close()
        # ---------- 04 Simülasyon Kayıtları tablosu → Oynat ----------
        ctx, pg = baglam(b, s)
        pg.goto(f'{BASE}/#/drone/sim?tab=runs', wait_until='domcontentloaded')
        pg.wait_for_selector(f'.fs-runs-card [data-act="play"]:not([disabled])', timeout=60000); pg.wait_for_timeout(800)
        shot(pg, '04-kayitlar-tablosu.png')
        pg.locator('.fs-runs-card [data-act="play"]:not([disabled])').first.click()
        sid2 = izleme_dogrula(pg, 'tablo Oynat')
        pg.wait_for_timeout(4000)
        shot(pg, '04b-tablodan-izleme.png')
        s.delete(f'{S_}/{sid2}'); time.sleep(1)
        ctx.close()
        # ---------- 05 Yeni Simülasyon › Kayıttan oynat: yalnız simülatör kaydı ----------
        ctx, pg = baglam(b, s)
        pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=60000)
        pg.locator('.fs-mode-row .seg button', has_text='Kayıttan oynat').click()
        pg.wait_for_selector('.fs-logs .fs-log', timeout=60000); pg.wait_for_timeout(1500)
        adlar = pg.locator('.fs-logs .fs-log .fs-log-main > b').all_inner_texts()
        if len(adlar) != 1 or 'SIM-' not in adlar[0] or any(x in ' '.join(adlar) for x in ('00000031', '00000044')):
            hatalar.append(f'sihirbaz log listesi: {adlar}')
        if pg.locator('.fs-log-filter .seg').count():
            hatalar.append('Kaynak (Gerçek/Simülasyon) süzgeci hâlâ var')
        shot(pg, '05-yeni-simulasyon-log-listesi.png')
        ctx.close()
        # ---------- 06–08 Saha görevi → "Simüle et" → sihirbaz (log sabit) Dünya adımında → Kalkış adımı ----------
        ctx, pg = baglam(b, s)
        pg.goto(f'{BASE}/#/field/task/{tid}', wait_until='domcontentloaded')
        pg.wait_for_selector('a.fs-simulate', timeout=60000); pg.wait_for_timeout(800)
        shot(pg, '06-saha-gorevi-simule-et.png')
        pg.locator('a.fs-simulate').first.click()
        pg.wait_for_selector('.fs-wz .fs-pin-note', timeout=60000)
        pg.wait_for_function("() => window.__fsWz && window.__fsWz.step === 'world'", timeout=60000)
        pg.wait_for_timeout(3000)
        st = pg.evaluate('window.__fsWz.steps')
        if st != ['log', 'world', 'launch', 'camera', 'summary']:
            hatalar.append(f'Simüle et adımları: {st}')
        if 'simulate=' in pg.evaluate('location.hash'):
            hatalar.append('?simulate adreste kaldı')
        if pg.locator('.fs-wz-top .seg').count():
            hatalar.append('Simüle et: kip seçimi görünür')
        shot(pg, '07-simule-et-dunya-adimi.png')
        pg.evaluate("window.__fsWz.goto('launch')"); pg.wait_for_timeout(2000)
        if not pg.locator('.fs-launch[data-launch="ramp"]').count():
            hatalar.append('Simüle et: rampa seçeneği yok')
        pg.locator('.fs-launch[data-launch="ramp"]').click(); pg.wait_for_timeout(1500)
        shot(pg, '08-simule-et-kalkis-rampa.png')
        pg.evaluate("window.__fsWz.goto('log')"); pg.wait_for_timeout(1200)
        sabit = pg.locator('.fs-logs .fs-log .fs-log-main > b').all_inner_texts()
        if len(sabit) != 1 or '00000031' not in sabit[0]:
            hatalar.append(f'Simüle et: sabit log {sabit}')
        shot(pg, '08b-simule-et-log-sabit.png')
        ctx.close()
        # ---------- 09 Uçuş Logu Analizi: gerçek loglarda "Simüle et" ----------
        ctx, pg = baglam(b, s)
        pg.goto(f'{BASE}/#/tools/flight-log', wait_until='domcontentloaded')
        pg.wait_for_selector('a.fs-simulate', timeout=60000); pg.wait_for_timeout(800)
        shot(pg, '09-ucus-logu-analizi-simule-et.png')
        ctx.close()
        b.close()
finally:
    server.should_exit = True
    time.sleep(1)

if hatalar:
    print('\nHATALAR:')
    for h_ in hatalar:
        print(' -', h_)
    sys.exit(1)
print(f'\nTamam — görüntüler {OUT}')
