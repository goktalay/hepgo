"""Altbilgi sayfa ölçeri (static/js/pagemeter.js) uçtan uca: değerler görünür, indirme sayılır, sayfa değişince sıfırlanır.
Çalıştırma: .venv/bin/python -m tests.pagemeter_e2e
"""
import os
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/pagemeter-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', GOOGLE_MAPS_API_KEY='')
PORT = 8871
BASE = f'http://127.0.0.1:{PORT}'
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')

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
hatalar = []
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:300]))
        pg.goto(f'{BASE}/#/', wait_until='domcontentloaded')
        pg.wait_for_selector('.pagemeter .pm-v', timeout=60000)
        pg.wait_for_timeout(4000)
        tot = lambda: pg.text_content('.pagemeter .pm-v')
        t1 = tot(); print('altbilgi toplam:', t1)
        assert t1 and t1 != '0 B', t1
        pg.keyboard.press('Escape'); pg.evaluate("document.querySelectorAll('.modal-back').forEach(e => e.remove())")
        pg.hover('.pagemeter'); pg.wait_for_selector('.pm-pop', timeout=5000); pg.wait_for_timeout(1200)
        kv = pg.eval_on_selector_all('.pm-pop .sbp-kv dd', 'els => els.map(e => e.textContent)')
        print('panel:', kv)
        assert len(kv) == 5 and ':' in kv[0] and kv[1] >= '00:04', kv
        assert pg.get_attribute('.pm-pop .pm-line', 'points'), 'grafik çizilmedi'
        pg.evaluate("fetch('/static/js/app.js?pm=' + Date.now()).then(r => r.text())")
        pg.wait_for_timeout(2500)
        t2 = tot(); print('indirme sonrası:', t2)
        assert t2 != t1, (t1, t2)
        pg.screenshot(path='/tmp/pagemeter-pop.png', clip={'x': 900, 'y': 540, 'width': 540, 'height': 360})
        pg.goto(f'{BASE}/#/settings', wait_until='domcontentloaded')
        pg.wait_for_timeout(1300)
        assert not pg.query_selector('.pm-pop'), 'sayfa değişince panel kapanmalı'
        print('yeni sayfa toplam:', tot())
        pg.screenshot(path='/tmp/pagemeter.png', clip={'x': 0, 'y': 840, 'width': 1440, 'height': 60})
        b.close()
finally:
    server.should_exit = True
    shutil.rmtree(DATA, ignore_errors=True)
print('hatalar:', hatalar or 'yok')
sys.exit(1 if hatalar else 0)
