"""MAVLink telemetri kaydı (.tlog) uçtan uca görsel doğrulama (Playwright headless shell; docs/ucus-simulatoru.md §8.6).

Araçlar › Uçuş Logu Analizi'nde tarayıcıdan .tlog yüklenir (parça parça yükleme) → analiz TAMAM → rapor (özet + harita + tlog notu,
grafikler, ayrıntılar) → listede TLOG rozeti → 3B oynatma (Cesium, /3d) → Uçuş Simülatörü "Simüle et" (kayıttan oynatma oturumu).
Ayrıca bozuk .tlog yüklemesinde anlaşılır hata iletisi. İsteğe bağlı gerçek kayıt: TLOG_GERCEK=/tmp/flsim/ornek/ornek.tlog (API ile).
Görüntüler /tmp/tlog-shots/*.png.
Çalıştırma: .venv/bin/python -m tests.tlog_e2e
"""
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')

from tests.test_tlog import tlog_yaz  # noqa: E402  (ortamı ayarlar: geçici CAYMAZ_DATA_DIR, admin@test)

os.environ.update(GOOGLE_MAPS_API_KEY='', SIM_UDP_BASE='39550', SIM_TERRAIN_SERVE='0')
PORT = int(os.environ.get('SHOT_PORT') or 8873)
BASE = f'http://127.0.0.1:{PORT}'
OUT = '/tmp/tlog-shots'
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.main import app  # noqa: E402

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
d = tempfile.mkdtemp(prefix='tlog-e2e-')
TLOG = os.path.join(d, 'akyurt-gorev-07.tlog')
tlog_yaz(TLOG)
BOZUK = os.path.join(d, 'bozuk.tlog')
with open(BOZUK, 'w') as f:
    f.write('Bu bir telemetri kaydi degil\n' * 200)

server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=PORT, log_level='error'))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(160):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close()
        break
    except OSError:
        time.sleep(0.25)
else:
    sys.exit('sunucu açılmadı')
time.sleep(1)
s = requests.Session()
assert s.post(f'{BASE}/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}).status_code == 200
s.post(f'{BASE}/api/kvkk/accept-terms', json={})
hatalar = []
gercek = os.environ.get('TLOG_GERCEK')
if gercek:
    with open(gercek, 'rb') as f:
        r = s.post(f'{BASE}/api/tools/flight-logs', files={'file': (os.path.basename(gercek), f, 'application/octet-stream')},
                   data={'aircraft': 'Gerçek kayıt'})
    if r.status_code != 200:
        hatalar.append(f'gerçek tlog yüklenemedi: {r.text[:200]}')


def shot(pg, ad):
    pg.screenshot(path=os.path.join(OUT, ad))
    print('  kare', ad, flush=True)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=['--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': c.name, 'value': c.value, 'url': BASE} for c in s.cookies])
        pg = ctx.new_page()
        pg.set_default_timeout(120000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:300]))
        pg.on('console', lambda m: hatalar.append('KONSOL: ' + m.text[:300])
              if m.type == 'error' and 'Failed to load resource' not in m.text and 'ERR_' not in m.text else None)
        pg.goto(f'{BASE}/#/tools/flight-log', wait_until='domcontentloaded')
        pg.wait_for_selector('.upload-card input[type=file]')
        pg.wait_for_timeout(600)
        red = pg.locator('.modal-foot button', has_text='Reddet')
        if red.count():
            red.first.click()
            pg.wait_for_timeout(400)
        acc = pg.locator('.upload-card input[type=file]').get_attribute('accept')
        if '.tlog' not in (acc or ''):
            hatalar.append(f'accept: {acc}')
        # bozuk .tlog → anlaşılır hata
        pg.locator('.upload-card input[type=file]').set_input_files(BOZUK)
        pg.locator('.upload-card button', has_text='Yükle ve Analiz Et').click()
        try:
            pg.wait_for_selector('.toast', timeout=30000)
            pg.wait_for_timeout(400)
            metin = ' '.join(pg.locator('.toast').all_inner_texts())
            if 'metin' not in metin:
                hatalar.append(f'bozuk tlog iletisi: {metin}')
            shot(pg, '01-bozuk-tlog-hata.png')
        except Exception as e:   # noqa: BLE001
            hatalar.append(f'bozuk tlog iletisi görünmedi: {e}')
        pg.wait_for_timeout(3500)
        # geçerli .tlog
        pg.locator('.upload-card input[type=file]').set_input_files(TLOG)
        pg.locator('.upload-card input').nth(1).fill('CYZ-0007')
        pg.locator('.upload-card input').nth(2).fill('HASAN ÇELEBİ')
        pg.locator('.upload-card input').nth(3).fill('Akyurt')
        pg.locator('.upload-card button', has_text='Yükle ve Analiz Et').click()
        pg.wait_for_function("() => /^#\\/tools\\/flight-log\\/\\d+$/.test(location.hash)", timeout=120000)
        lid = int(pg.evaluate('location.hash').rsplit('/', 1)[1])
        pg.wait_for_selector('.fr-doc', timeout=180000)
        pg.wait_for_timeout(1500)
        if not pg.locator('.module-toolbar .fl-format', has_text='TLOG').count():
            hatalar.append('rapor araç çubuğunda TLOG rozeti yok')
        if not pg.locator('.fr-tlog-note').count():
            hatalar.append('raporda tlog notu yok')
        shot(pg, '02-rapor-ozet-harita.png')
        pg.locator('.fr-page').nth(1).scroll_into_view_if_needed()
        pg.wait_for_timeout(600)
        shot(pg, '03-rapor-grafikler.png')
        pg.locator('.fr-page').nth(2).scroll_into_view_if_needed()
        pg.wait_for_timeout(600)
        shot(pg, '04-rapor-ayrintilar.png')
        # liste: TLOG rozeti
        pg.goto(f'{BASE}/#/tools/flight-log', wait_until='domcontentloaded')
        pg.wait_for_selector('td .fl-format', timeout=60000)
        pg.wait_for_timeout(800)
        rozet = pg.locator('td .fl-format').all_inner_texts()
        if 'TLOG' not in rozet:
            hatalar.append(f'liste rozeti: {rozet}')
        shot(pg, '05-liste-tlog-rozeti.png')
        # 3B oynatma (Cesium)
        pg.goto(f'{BASE}/#/tools/flight-log/{lid}/3d', wait_until='domcontentloaded')
        try:
            pg.wait_for_function("() => document.querySelector('canvas')", timeout=60000)
        except Exception as e:   # noqa: BLE001
            hatalar.append(f'3B: canvas yok ({e})')
        pg.wait_for_timeout(6000)
        shot(pg, '06-3b-oynatma.png')
        r = s.get(f'{BASE}/api/flight-logs/{lid}/replay')
        if r.status_code != 200 or len(r.json().get('samples', [])) < 200:
            hatalar.append(f'/replay: {r.status_code} {r.text[:200]}')
        # Uçuş Simülatörü: "Simüle et" → sihirbaz (log sabit) → Başlat → kayıttan oynatma oturumu
        pg.goto(f'{BASE}/#/tools/flight-log', wait_until='domcontentloaded')
        pg.wait_for_selector('a.fs-simulate', timeout=60000)
        pg.wait_for_timeout(600)
        pg.locator('tr', has_text='akyurt-gorev-07.tlog').locator('a.fs-simulate').click()
        try:
            pg.wait_for_function("() => window.__fsWz && window.__fsWz.step === 'world'", timeout=60000)
            pg.wait_for_timeout(1500)
            pg.evaluate("window.__fsWz.goto('summary', { force: true })")
            pg.wait_for_timeout(1500)
            shot(pg, '07-simule-et-ozet.png')
            pg.locator('.fs-start:visible').first.click()
            bitis = time.time() + 90
            oturum = None
            while time.time() < bitis:
                ss = s.get(f'{BASE}/api/drone/sim/sessions').json()
                ss = ss.get('sessions', ss) if isinstance(ss, dict) else ss
                oturum = next((x for x in ss if x.get('mode') == 'replay' and (x.get('replay') or {}).get('log_id') == lid), None)
                if oturum and oturum.get('state') == 'HAZIR':
                    break
                time.sleep(0.5)
            if not oturum or oturum.get('state') != 'HAZIR':
                hatalar.append(f'simülatör kayıt oturumu HAZIR olmadı: {oturum and oturum.get("state")}')
            else:
                print(f'  simülatör oturumu {oturum["id"]}: HAZIR, {oturum["replay"].get("frames")} kare, modlar {oturum["replay"].get("modes")}')
            pg.wait_for_timeout(8000)
            shot(pg, '08-simulator-kayittan-oynatma.png')
            if oturum:
                s.delete(f'{BASE}/api/drone/sim/sessions/{oturum["id"]}')
        except Exception as e:   # noqa: BLE001
            hatalar.append(f'simülatör: {e}')
            shot(pg, '08-simulator-hata.png')
        b.close()
finally:
    server.should_exit = True
    time.sleep(1)
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(os.environ['CAYMAZ_DATA_DIR'], ignore_errors=True)

if hatalar:
    print('\nHATALAR:')
    for h_ in hatalar:
        print(' -', h_)
    sys.exit(1)
print(f'\nTamam — görüntüler {OUT}')
