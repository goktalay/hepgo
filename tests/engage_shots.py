"""HEPGO Uçuş Simülatörü §40 — Boşluk ile KİLİT + ANGAJMAN görsel doğrulama (Playwright headless shell + SwiftShader; sahte kinematik).
Görüntüler /tmp/dogfight-shots/engage-*.png:
  01 takip kamerası: aday hedefin TD kutusu + "Boşluk: kilit" · 02 Boşluk → KİLİT (çift çerçeve) + angajman paneli (süre, mesafe, Vc, açı, ΔH)
  03 gimbal HUD'unda kilit sembolü · 04 ANGAJMAN BAŞARILI (kilitli hedef önlendi) · 05 özet raporda angajman listesi · 06 kutu yokken ipucu
Çalıştırma: ./.venv/bin/python -m tests.engage_shots
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/engage-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39550', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8857)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/dogfight-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth, flightsim  # noqa: E402
from app import flightsim_targets as FT  # noqa: E402
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
ENG = "(document.querySelector('.fs-eng-cv')?.__eng?.state?.() || null)"


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


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        # Hedefler: T1 dronun dairesinde ters yönde (sahte kinematik R=150 m saat yönü; kafa kafaya) — önlenir; T2 kuzeyde önde; T3 güneyde arkada
        targets = {'items': [{'model': 'tgt:lancet', 'alt_m': 60, 'diameter_m': 300, 'speed_ms': 20, 'dir': 'ccw', 'name': 'Lancet-1'},
                             {'model': 'tgt:octopus', 'alt_m': 85, 'diameter_m': 300, 'north_m': 520, 'speed_ms': 40, 'dir': 'ccw', 'name': 'Octopus-1'},
                             {'model': 'tgt:sw300', 'alt_m': 65, 'diameter_m': 200, 'east_m': -60, 'north_m': -450, 'dir': 'cw', 'name': 'SW300-1'}], 'radius_m': 25}
        r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False},
                                                           'world': {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.25, 'building_count': 30},
                                                           'targets': targets})
        assert r.status_code == 201, r.text
        sid = r.json()['id']
        ss = flightsim.MANAGER.sessions[sid]
        bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
        pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')
        pg.wait_for_function('() => window.__fsSim && window.__fsSim.targetsInfo().length === 3', timeout=240000)
        pg.wait_for_timeout(1500)
        if pg.locator('.modal button:has-text("Reddet")').count():   # KVKK konum izni penceresi
            pg.locator('.modal button:has-text("Reddet")').first.click(); pg.wait_for_timeout(400)
        # sanal kumandayı kapat (Boşluk ipucu yolu da görülsün)
        pg.evaluate("document.querySelector('.fs-rc-btn, .fs-bar button[title^=\"Sanal kumanda\"]')?.classList.contains('primary') && document.querySelector('.fs-bar button[title^=\"Sanal kumanda\"]').click()")
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 60}})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 55, 120, 'kalkış 60 m')
        # ---- 06 önce: kutu yokken (kamera yere bakıyor) Boşluk → ipucu
        pg.evaluate("window.__fsSim.setCamera('fpv'); window.__fsSim.setGimbal(-90)"); pg.wait_for_timeout(1500)
        st = pg.evaluate(ENG)
        print('  yere bakış:', st, flush=True)
        if st and st['candidate'] is None:
            (pg.evaluate('document.activeElement && document.activeElement.blur && document.activeElement.blur()'), pg.keyboard.press('Space')); pg.wait_for_timeout(300)
            shot(pg, 'engage-06-no-box-hint.png')
        # ---- 01 takip kamerası: aday kutusu + ipucu
        pg.evaluate("window.__fsSim.setCamera('follow')")
        bekle(lambda: (pg.evaluate(ENG) or {}).get('candidate') is not None, 60, 'takipte aday')
        pg.wait_for_timeout(500)
        print('  aday:', pg.evaluate(ENG), flush=True)
        shot(pg, 'engage-01-follow-candidate.png')
        # ---- 02 Boşluk → kilit (aday ekrandan çıkmış olabilir: kilitlenene dek yeniden dene)
        t_end = time.time() + 60
        while time.time() < t_end and not (pg.evaluate(ENG) or {}).get('engaged'):
            if (pg.evaluate(ENG) or {}).get('candidate') is not None:
                (pg.evaluate('document.activeElement && document.activeElement.blur && document.activeElement.blur()'), pg.keyboard.press('Space'))
            time.sleep(0.6)
        bekle(lambda: (pg.evaluate(ENG) or {}).get('engaged') is not None, 10, 'kilit')
        pg.wait_for_timeout(1800)
        st = pg.evaluate(ENG)
        print('  kilit:', st, ss.hedef_iz.angajman_durumu(), flush=True)
        shot(pg, 'engage-02-follow-locked.png')
        # ---- 04 ANGAJMAN BAŞARILI: takipte Lancet-1'e (i=0) kilitli kal; önlenince yeşil panel
        pg.evaluate("window.__fsSim.setCamera('follow')"); pg.wait_for_timeout(500)
        t_end = time.time() + 150
        while time.time() < t_end:
            st = pg.evaluate(ENG) or {}
            if st.get('ok'):
                shot(pg, 'engage-04-success.png'); break
            eng = st.get('engaged')
            if eng and eng.get('i') != 0:
                (pg.evaluate('document.activeElement && document.activeElement.blur && document.activeElement.blur()'), pg.keyboard.press('Space'))
            elif not eng and st.get('candidate') == 0:
                (pg.evaluate('document.activeElement && document.activeElement.blur && document.activeElement.blur()'), pg.keyboard.press('Space'))
            time.sleep(0.3)
        else:
            hatalar.append('angajman başarılı karesi alınamadı')
        print('  angajmanlar:', ss.hedef_iz.ozet()['engagements'], flush=True)
        # ---- 03 gimbal HUD (ufuk) — kilit sembolü
        pg.evaluate("window.__fsSim.setCamera('fpv'); window.__fsSim.setGimbal(-window.__fsSim.getGimbal())"); pg.wait_for_timeout(2000)
        t_end = time.time() + 90   # gimbal HUD'unda yeniden kilit (TD kutusundaki aday)
        while time.time() < t_end and not (pg.evaluate(ENG) or {}).get('engaged'):
            if (pg.evaluate(ENG) or {}).get('candidate') is not None:
                (pg.evaluate('document.activeElement && document.activeElement.blur && document.activeElement.blur()'), pg.keyboard.press('Space'))
            time.sleep(0.6)
        pg.wait_for_timeout(1500)
        shot(pg, 'engage-03-gimbal-locked.png')
        print('  gimbal kaplama:', pg.evaluate(ENG), flush=True)
        # ---- 05 özet rapor (Bitir)
        pg.locator('button.danger:has-text("Bitir")').first.click(); pg.wait_for_timeout(800)
        pg.locator('.modal button:has-text("Bitir")').last.click()
        if pg.locator('.fs-rp-eng').count() == 0:
            pg.wait_for_selector('.fs-rp-eng', timeout=30000)
        pg.evaluate("document.querySelector('.fs-rp-eng')?.scrollIntoView({block: 'center'})"); pg.wait_for_timeout(600)
        shot(pg, 'engage-05-report.png')
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / 'engage-hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(6.0)
