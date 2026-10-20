"""Büyük .BIN izleme (§8.3) + uçuş logu kaynağı (Gerçek / Simülasyon, §19) — görsel doğrulama ve ölçüm (Playwright headless shell + SwiftShader).
Uygulama aynı süreçte (iş parçacığı) açılır; sahte kinematik (SITL yok). Loglar BINPERF_DIR'den (varsayılan /tmp/binperf) bağlanır:
  log6.bin (gerçek, ~754 MB, 4 sa 41 dk — PROD #6 kopyası), sim9.bin / sim37.bin (SITL kayıtları). Satırlar origin NULL yazılır ve
  db.flight_log_origin_doldur (açılış göçü) ile doldurulur.
Görüntüler /tmp/binperf-shots/*.png:
  01 Uçuş Logu Analizi (Kaynak sütunu) · 02 süzgeç Simülasyon · 03 sihirbaz Kayıttan oynat listesi (rozetler) · 04 süzgeç Gerçek + sıralama
  05 ilk açılış: ayrıştırma ilerleme kartı · 06 oynatma (3 sa+ kayıt, kalkış) · 07 ortaya atlama (parça) · 08 ikinci açılış (önbellek)
Çalıştırma: export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
            ./.venv/bin/python -m tests.binperf_shots
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
DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/binperf-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39350', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
SRC = pathlib.Path(os.environ.get('BINPERF_DIR') or '/tmp/binperf')
PORT = int(os.environ.get('SHOT_PORT') or 8817)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/binperf-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth, config, db, flightsim, flightsim_replay as R  # noqa: E402
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
s.post(f'{BASE}/api/drone/centers', json={'name': 'Akyurt Test Sahası', 'lat': 40.184, 'lon': 33.326, 'alt': 1045})
hatalar, olcum = [], {}

# ---- loglar (PROD analiz özetleriyle; origin NULL → göç)
OZET = {
    'log6.bin': ('13.10.26_565km_700m.BIN', 'CYZ-0002', 'HASAN ÇELEBİ', 'Akyurt', {'vehicle': 'ArduPlane', 'firmware': 'ArduPlane V4.7.1 (dbe79216)', 'flight_s': 14120.0,
                 'duration_s': 16874.5, 'start_utc': '2026-10-13T10:39:32+00:00', 'takeoff_utc': '2026-10-13T11:30:31+00:00', 'distance_m': 565000,
                 'home': {'lat': 40.1840098, 'lng': 33.3263108, 'alt': 1045.24}}),
    'sim9.bin': ('SIM-6-20261018-1730.bin', 'Simülatör · Sabit Kanat · D-0005', 'HASAN ÇELEBİ', 'Akyurt', {'vehicle': 'ArduPlane', 'flight_s': 0, 'duration_s': 917.9,
                 'start_utc': '2026-10-18T14:38:10+00:00', 'home': {'lat': 39.3775435, 'lng': 34.2903541, 'alt': 100.1}}),
    'sim37.bin': ('SIM-4-20261020-1933.bin', 'Simülatör · Multikopter', 'MUHAMMED KADEROĞLU', 'Akyurt', {'vehicle': 'ArduCopter', 'flight_s': 15, 'duration_s': 22.1,
                  'start_utc': '2026-10-20T16:33:46+00:00', 'home': {'lat': 39.3775, 'lng': 34.2903, 'alt': 100}}),
    'b1h.bin': ('00000031.BIN', 'CYZ-0003', 'Test Pilot', 'Ankara', {'vehicle': 'ArduPlane', 'flight_s': 3580, 'duration_s': 3600, 'start_utc': '2026-10-15T08:00:00+00:00',
                'home': {'lat': 39.925, 'lng': 32.837, 'alt': 900}}),
}
up = config.UPLOAD_DIR / 'flightlogs'
up.mkdir(parents=True, exist_ok=True)
ids = {}
with db.connect() as conn:
    for f, (ad, ac, pilot, yer, ozet) in OZET.items():
        if not (SRC / f).exists():
            print('  (yok, atlandı)', SRC / f)
            continue
        (up / f).symlink_to(SRC / f)
        ids[f] = conn.execute('''INSERT INTO flight_logs (file, file_name, size, status, analysis, aircraft, pilot, location, uploaded_by, uploaded_at, analyzed_at, origin)
                                  VALUES (?,?,?,'TAMAM',?,?,?,?,1,?,?,NULL)''',
                              (f'flightlogs/{f}', ad, (SRC / f).stat().st_size, json.dumps({'summary': ozet}), ac, pilot, yer, db.now(), db.now())).lastrowid
    conn.commit()
    t = time.time()
    db.flight_log_origin_doldur(conn)
    conn.commit()
    olcum['goc_sn'] = round(time.time() - t, 3)
    olcum['origin'] = {f: conn.execute('SELECT origin FROM flight_logs WHERE id = ?', (i,)).fetchone()[0] for f, i in ids.items()}
print('  göç:', olcum, flush=True)
R.onbellek_sil(ids['log6.bin'])


def shot(pg, ad):
    pg.screenshot(path=str(OUT / ad))
    print('  kare', ad, flush=True)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.on('response', lambda r: hatalar.append(f'HTTP {r.status} {r.url[len(BASE):][:120]}') if r.status >= 400 and '/thumb' not in r.url and '/osm' not in r.url and '/terrain' not in r.url else None)
        # ---- 01/02 Uçuş Logu Analizi
        pg.goto(f'{BASE}/#/tools/flight-log', wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-origin', timeout=60000)
        pg.wait_for_timeout(800)
        red = pg.locator('.modal-foot button', has_text='Reddet')   # konum izni (KVKK) penceresi
        if red.count():
            red.first.click(); pg.wait_for_timeout(500)
        shot(pg, '01-ucus-loglari-kaynak-sutunu.png')
        pg.locator('.filters select').first.select_option('SIM')
        pg.wait_for_timeout(500)
        assert pg.locator('.fs-origin.real').count() == 0 and pg.locator('.fs-origin.sim').count() == 2, 'süzgeç Simülasyon'
        shot(pg, '02-ucus-loglari-suzgec-simulasyon.png')
        pg.locator('.filters select').first.select_option('')
        pg.locator('th.sortable', has_text='Kaynak').click(); pg.wait_for_timeout(300)
        # ---- 03/04 sihirbaz Kayıttan oynat
        pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-wizard .fs-mode-row', timeout=60000)
        pg.locator('.fs-mode-row button', has_text='Kayıttan oynat').click()
        pg.wait_for_selector('.fs-logs .fs-log', timeout=30000)
        pg.wait_for_timeout(1500)
        pg.evaluate("document.querySelector('.fs-log-search').scrollIntoView({block: 'start'})"); pg.wait_for_timeout(500)
        shot(pg, '03-sihirbaz-kayit-listesi-kaynak.png')
        pg.locator('.fs-log-filter button', has_text='Gerçek').click()
        pg.locator('select.fs-log-sort').select_option('big'); pg.wait_for_timeout(500)
        assert pg.locator('.fs-logs .fs-origin.sim').count() == 0 and pg.locator('.fs-logs .fs-log').count() == 2, 'süzgeç Gerçek'
        shot(pg, '04-sihirbaz-suzgec-gercek-siralama.png')
        # ---- 05 ilk açılış: 754 MB gerçek kayıt (önbellek yok)
        pg.locator('.fs-logs .fs-log', has_text='13.10.26_565km_700m.BIN').click(); pg.wait_for_timeout(300)
        t0 = time.time()
        pg.locator('.modal-foot .fs-start').click()
        pg.wait_for_selector('.fs-prep', timeout=30000)
        yuzde_gor = None
        for _ in range(600):
            txt = pg.locator('.fs-prep').inner_text()
            sid = next((x for x in flightsim.MANAGER.sessions), None)
            pr = flightsim.MANAGER.sessions[sid].replay.get('progress') if sid is not None else 0
            if pr and 20 <= pr < 100 and yuzde_gor is None:
                yuzde_gor = pr
                shot(pg, '05-ilk-acilis-ayristirma-ilerleme.png')
            if sid is not None and flightsim.MANAGER.sessions[sid].state in ('HAZIR', 'HATA'):
                break
            time.sleep(0.1)
        olcum['ilk_hazir_sn'] = round(time.time() - t0, 1)
        sid = next(iter(flightsim.MANAGER.sessions))
        pg.wait_for_function('() => location.hash.includes("/drone/sim/")', timeout=180000)
        olcum['ilk_oturum_ekrani_sn'] = round(time.time() - t0, 1)
        pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
        pg.wait_for_function('() => window.__fsPlayer && window.__fsPlayer.lod() && window.__fsPlayer.lod().loaded > 0', timeout=180000)
        olcum['ilk_goruntu_sn'] = round(time.time() - t0, 1)
        pg.wait_for_timeout(6000)
        olcum['lod_1'] = pg.evaluate('window.__fsPlayer.lod()')
        shot(pg, '06-oynatma-kalkis.png')
        # ---- 07 ortaya atlama (2 sa 20 dk): parça yüklenir; o arada genel bakış oynar
        dur = pg.evaluate('window.__fsPlayer.duration()')
        t1 = time.time()
        pg.evaluate(f'window.__fsPlayer.seek({dur / 2})')
        pg.wait_for_function('() => window.__fsPlayer.lod().pending === 0 && window.__fsPlayer.lod().loaded >= 2', timeout=30000)
        olcum['atlama_parca_sn'] = round(time.time() - t1, 2)
        pg.wait_for_timeout(4000)
        olcum['lod_2'] = pg.evaluate('window.__fsPlayer.lod()')
        olcum['oynatma_t'] = round(pg.evaluate('window.__fsPlayer.time()'), 1)
        shot(pg, '07-oynatma-ortaya-atlama.png')
        olcum['js_bellek_mb'] = pg.evaluate('performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null')
        s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        pg.wait_for_timeout(1000)
        # ---- 08 ikinci açılış (önbellekten): oturum + ilk görüntü süresi
        pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(1500)
        t2 = time.time()
        r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': ids['log6.bin'], 'world': {'mode': 'procedural', 'seed': 3, 'size_m': 4000}})
        assert r.status_code == 201, r.text
        sid2 = r.json()['id']
        while flightsim.MANAGER.sessions[sid2].state == 'BASLIYOR':
            time.sleep(0.05)
        olcum['ikinci_hazir_sn'] = round(time.time() - t2, 2)
        pg.evaluate(f"location.hash = '#/drone/sim/{sid2}?netsim=delay0'")
        pg.wait_for_function('() => window.__fsPlayer && window.__fsPlayer.lod() && window.__fsPlayer.lod().loaded > 0 && window.__fsPlayer.playing()', timeout=60000)
        olcum['ikinci_ilk_goruntu_sn'] = round(time.time() - t2, 2)   # SwiftShader (yazılım WebGL) 3B dünya kurulumu dahil
        # veri yolu: sayfa geçişinden itibaren /replay (genel bakış) ve ilk parça yanıtlarının bitişi (ms) — 3B kurulumuyla paralel iner
        olcum["ikinci_veri_ms"] = pg.evaluate(r"""() => { const n = performance.getEntriesByType('resource').filter(e => /\/api\/drone\/sim\/sessions\/\d+\/replay/.test(e.name));
          return n.slice(-3).map(e => ({ u: e.name.replace(/^.*\/sessions\//, ''), bitis_ms: Math.round(e.responseEnd - e.startTime), kb: Math.round((e.transferSize || 0) / 1024) })); }""")
        pg.wait_for_timeout(3000)
        shot(pg, '08-ikinci-acilis-onbellek.png')
        s.delete(f'{BASE}/api/drone/sim/sessions/{sid2}')
        b.close()
finally:
    olcum['onbellek_mb'] = round(R.onbellek_boyutu(ids.get('log6.bin', 0)) / 1e6, 2)
    print('ÖLÇÜM', json.dumps(olcum, ensure_ascii=False), flush=True)
    for hh in hatalar[:30]:
        print('  !', hh)
    server.should_exit = True
    time.sleep(1)
