"""HEPGO Uçuş Simülatörü §45 — UÇUŞ YIĞINI görsel doğrulama (Playwright headless shell + SwiftShader; GERÇEK PX4 SIH SITL).
Görüntüler /tmp/stacks-shots/*.png:
  01 sihirbaz Araç adımı: yığın kartları (ArduPilot varsayılan; INAV / Paparazzi "Yakında", Betaflight / Rotorflight "Uygun değil" gri + gerekçe)
  02 PX4 seçili (kopter): airframe 10040, simülasyon hızı, çalışan / çalışmayan özellikler, parametre dosyası
  03 PX4 + Helikopter: tip uyarısı, İleri pasif · 04 PX4 + VTOL: airframe seçenekleri · 05 özet adımında "Uçuş yığını"
  06 PX4 ile uçuş (kalkış sonrası 3B + harekât paneli, PX4 kipi, QGROUNDCONTROL / MP bölümü) · 07 kip açılır listesi (PX4 kipleri)
Çalıştırma: HEPGO_SITL_DIR=/opt/hepgo/sitl/bin ./.venv/bin/python -m tests.stacks_shots_hepgo
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/stacks-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1', SIM_UDP_BASE='39850', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/sitl/bin')
PORT = int(os.environ.get('SHOT_PORT') or 8871)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/stacks-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth  # noqa: E402
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


def shot(pg, ad, el=None):
    (pg.locator(el).last if el else pg).screenshot(path=str(OUT / ad))
    print('  ✓', ad)


def tikla_tip(pg, ad):
    pg.locator('.fs-type', has_text=ad).first.click(); pg.wait_for_timeout(500)


def main():
    sid = None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=EXE, args=ARGS)
            ctx = b.new_context(viewport={'width': 1440, 'height': 1000}, locale='tr-TR')
            ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
            pg = ctx.new_page()
            pg.on('pageerror', lambda e: hatalar.append(str(e)))
            pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
            pg.wait_for_selector('.yy-card', timeout=30000)
            pg.wait_for_timeout(1500)
            tikla_tip(pg, 'Multikopter')
            shot(pg, '01-yigin-kartlari.png', 'div.modal[role=dialog]')
            pg.locator('.yy-card[data-stack="px4"]').click(); pg.wait_for_timeout(400)
            pg.locator('.yy-stack input[type=file]').set_input_files(files=[{'name': 'quad.params', 'mimeType': 'text/plain',
                                                                            'buffer': b'# QGC\n1\t1\tMPC_XY_VEL_MAX\t8\t9\n1\t1\tMIS_TAKEOFF_ALT\t15\t9\n'}])
            pg.wait_for_timeout(500)
            pg.locator('.yy-stack').scroll_into_view_if_needed()
            shot(pg, '02-px4-kopter.png', 'div.modal[role=dialog]')
            tikla_tip(pg, 'Helikopter')
            pg.locator('.yy-stack').scroll_into_view_if_needed()
            shot(pg, '03-px4-helikopter-uyari.png', 'div.modal[role=dialog]')
            tikla_tip(pg, 'VTOL')
            pg.locator('.yy-stack').scroll_into_view_if_needed()
            shot(pg, '04-px4-vtol-airframe.png', 'div.modal[role=dialog]')
            tikla_tip(pg, 'Multikopter')
            pg.evaluate("window.__fsWz.goto('summary')"); pg.wait_for_timeout(1200)
            shot(pg, '05-ozet.png', 'div.modal[role=dialog]')
            pg.keyboard.press('Escape')
            # PX4 oturumu (API) + kalkış → oturum ekranı
            r = s.post(f'{BASE}/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c['id'], 'stack': 'px4', 'world': {'mode': 'procedural', 'wind_ms': 0},
                                                              'stack_cfg': {'airframe': 10040}})
            assert r.status_code == 201, r.text
            sid = r.json()['id']
            t0 = time.time()
            while time.time() - t0 < 60 and s.get(f'{BASE}/api/drone/sim/sessions/{sid}').json()['state'] != 'HAZIR':
                time.sleep(0.5)
            pg.goto(f'{BASE}/#/drone/sim/{sid}', wait_until='domcontentloaded')
            pg.wait_for_timeout(8000)
            t0 = time.time()
            while time.time() - t0 < 60:
                rr = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 25}})
                if rr.status_code == 200:
                    break
                time.sleep(2)
            t0 = time.time()
            while time.time() - t0 < 90:
                tele = pg.evaluate('window.__fsTele && window.__fsTele()') or {}
                if (tele.get('alt_rel') or 0) > 20:
                    break
                time.sleep(1)
            print('  irtifa', tele.get('alt_rel'), 'kip', tele.get('mode'))
            pg.wait_for_timeout(2500)
            shot(pg, '06-px4-ucus.png')
            sel = pg.locator('.fs-flt-mode, .fs-modesel').first
            try:
                sel.click(timeout=5000, force=True); pg.wait_for_timeout(600)
                shot(pg, '07-px4-kipler.png')
            except Exception as e:   # noqa: BLE001
                print('  kip listesi açılamadı:', e)
            b.close()
    finally:
        if sid is not None:
            s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
            time.sleep(2)
        server.should_exit = True
        time.sleep(1)
    if hatalar:
        print('SAYFA HATALARI:', hatalar[:5])
    print('stacks_shots_hepgo: TAMAM' if not hatalar else 'stacks_shots_hepgo: SAYFA HATASI VAR')


if __name__ == '__main__':
    main()
