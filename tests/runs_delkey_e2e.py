"""Simülasyon kayıtları listesi: fare üzerindeki kayıt Del ile silinir; onayda "Bir daha sorma"; silindikten sonra sıradaki kayıt seçili.
Çalıştırma: .venv/bin/python -m tests.runs_delkey_e2e   (görüntüler /tmp/delrun)
"""
import os
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/delrun-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', GOOGLE_MAPS_API_KEY='', SIM_UDP_BASE='27850')
PORT = 8873
BASE = f'http://127.0.0.1:{PORT}'
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
SHOTS = '/tmp/delrun'
os.makedirs(SHOTS, exist_ok=True)

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth  # noqa: E402
from app.main import app  # noqa: E402

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
assert s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'}).status_code == 200
s.post(f'{BASE}/api/kvkk/accept-terms', json={})
s.post(f'{BASE}/api/location/consent', json={'granted': False})
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Del Test', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
S_ = f'{BASE}/api/drone/sim/sessions'
for i in range(4):   # 4 kayıt
    sid = s.post(S_, json={'type': 'multirotor', 'center_id': c['id'], 'world': {'mode': 'procedural'}}).json()['id']
    time.sleep(1.2)
    s.delete(f'{S_}/{sid}')
    time.sleep(1.2)
ids = [r['id'] for r in s.get(f'{BASE}/api/drone/sim/runs').json()['items']]
assert len(ids) == 4, ids
hatalar = []
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:300]))
        pg.goto(f'{BASE}/#/drone/sim?tab=runs', wait_until='domcontentloaded')
        pg.wait_for_selector('tr[data-run]', timeout=60000)
        pg.keyboard.press('Escape'); pg.evaluate("document.querySelectorAll('.modal-back').forEach(e => e.remove())")
        sira = lambda: [int(x) for x in pg.eval_on_selector_all('tr[data-run]', 'els => els.map(e => e.dataset.run)')]
        cur = lambda: pg.eval_on_selector_all('tr.fs-runs-cur', 'els => els.map(e => +e.dataset.run)')
        satir = sira(); print('liste', satir)
        hedef = satir[1]
        pg.hover(f'tr[data-run="{hedef}"] td:first-child')
        assert cur() == [hedef], cur()
        pg.keyboard.press('Delete')
        pg.wait_for_selector('.modal-back', timeout=5000)
        assert pg.query_selector('.modal-back input[type=checkbox]'), '"Bir daha sorma" kutusu yok'
        pg.screenshot(path=f'{SHOTS}/01-onay.png')
        pg.check('.modal-back input[type=checkbox]')
        pg.click('.modal-back button.danger')
        pg.wait_for_function(f'!document.querySelector(\'tr[data-run="{hedef}"]\')', timeout=10000)
        pg.wait_for_timeout(400)
        print('silindi', hedef, 'seçili', cur(), 'liste', sira())
        assert cur() == [satir[2]], (cur(), satir)   # aynı sıradaki (bir sonraki) kayıt seçili
        pg.screenshot(path=f'{SHOTS}/02-sonraki-secili.png')
        # ikinci Del: sormadan siler (Bir daha sorma)
        pg.mouse.move(5, 5)
        pg.keyboard.press('Delete')
        pg.wait_for_timeout(300)
        assert not pg.query_selector('.modal-back'), 'bir daha sorulmamalıydı'
        pg.wait_for_function(f'!document.querySelector(\'tr[data-run="{satir[2]}"]\')', timeout=10000)
        pg.wait_for_timeout(400)
        print('sormadan silindi', satir[2], 'seçili', cur(), 'liste', sira())
        assert cur() == [satir[3]], cur()
        # son kayıt silinince bir önceki seçilir
        pg.keyboard.press('Delete')
        pg.wait_for_function(f'!document.querySelector(\'tr[data-run="{satir[3]}"]\')', timeout=10000)
        pg.wait_for_timeout(400)
        assert cur() == [satir[0]] and sira() == [satir[0]], (cur(), sira())
        # giriş alanındayken Del silmez
        odak = pg.evaluate("""(() => { const i = [...document.querySelectorAll('input[type=text], input[type=search], input:not([type])')].find(e => e.offsetParent)
          || document.querySelector('.fs-runs-card').appendChild(Object.assign(document.createElement('input'), { type: 'text' }));
          i.focus(); return document.activeElement === i; })()""")
        assert odak, 'görünür metin kutusu bulunamadı'
        pg.keyboard.press('Delete'); pg.wait_for_timeout(600)
        assert sira() == [satir[0]], sira()
        pg.screenshot(path=f'{SHOTS}/03-son.png')
        b.close()
finally:
    server.should_exit = True
    shutil.rmtree(DATA, ignore_errors=True)
print('hatalar:', hatalar or 'yok')
sys.exit(1 if hatalar else 0)
