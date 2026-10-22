"""SIMUMAV — HEPGO §42 UÇUŞ UYARI SİSTEMİ görsel doğrulama (sahte kinematik, senaryolu) → /tmp/gpws-shots/sm-*.png:
  01 sihirbaz Pilot adımında "Uçuş uyarıları" seçici · 02 PULL UP (WARNING + MASTER + vinyet) · 03 TOO LOW (CAUTION) · 04 ayar paneli (İngilizce arayüz)
  05 uçuş özetinde "Uçuş uyarıları" kartı + disiplin puanı · 06 mobil BANK ANGLE
Çalıştırma: .venv/bin/python -m tests.gpws_shots_simumav
"""
import math
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/sm-gpws-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='28850', SIMUMAV_MAX_FLIGHTS='4',
                  SIMUMAV_MP_PORT_BASE='29800', SIMUMAV_MP_PORT_COUNT='20', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='')
PORT = 8653
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/gpws-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import app.simumav.main as smain  # noqa: E402
from app import flightsim  # noqa: E402

server = uvicorn.Server(uvicorn.Config(smain.app, host='127.0.0.1', port=PORT, log_level='error'))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(120):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close(); break
    except OSError:
        time.sleep(0.25)
else:
    sys.exit('sunucu açılmadı')

H = {'Origin': BASE}
s = requests.Session()
assert s.post(f'{BASE}/api/session', json={'dev_user': 'ayse'}, headers=H).status_code == 200
tok = s.cookies['smsid']
d = s.post(f'{BASE}/api/hangar', json={'name': 'Kartal', 'type': 'multirotor', 'model_key': 'builtin:quad', 'color': '#0ea5e9'}, headers=H).json()
s.put(f"{BASE}/api/hangar/{d['id']}", json={'is_default': True}, headers=H)
pid = s.get(f'{BASE}/api/crew').json()['pilots'][0]['id']
tr = s.post(f'{BASE}/api/tracks', json={'name': 'Göl Kıyısı', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural',
                                        'world': {'seed': 21, 'runway': True, 'tree_density': 0.2, 'building_count': 20, 'runway_deg': 30}}, headers=H).json()
s.put(f"{BASE}/api/tracks/{tr['id']}", json={'is_default': True}, headers=H)
hatalar = []
ST = "(document.querySelector('.fs-gpws')?.__gpws?.state?.() || null)"


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
    pg.screenshot(path=str(OUT / ad))
    print('  kare', ad, flush=True)


def senaryo(ss):
    k = ss.sahte
    ctrl = {'faz': 'aski'}

    def adim(dt):
        k.sure_ms += dt * 1000
        k.armed, k.mode = True, 'LOITER'
        f = ctrl['faz']
        hedef = math.radians(50) if f == 'yatis' else 0.0
        eski = k.roll
        k.roll += max(-1.5 * dt, min(1.5 * dt, hedef - k.roll)); k.rs = (k.roll - eski) / max(dt, 1e-3)
        k.pitch = k.ps = k.ys = 0.0
        if f == 'dalis':
            k.vd = 12.0; k.alt_rel = max(20.0, k.alt_rel - 12.0 * dt)
        elif f == 'alcak':
            k.vd = 0.0; k.alt_rel = 3.0
        else:
            k.vd = max(-3.0, min(3.0, (k.alt_rel - 60.0) * 0.8)); k.alt_rel -= k.vd * dt
        k.vn = 12.0 if f == 'alcak' else 0.0
        k.ve = 0.0
        k.lat += k.vn * dt / 111320.0
    k.adim = adim
    return ctrl


def ucus(ctx, lang='tr'):
    f = s.post(f'{BASE}/api/fly/start', json={'drone_id': d['id'], 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False}}, headers=H)
    assert f.status_code == 201, f.text
    fid, sid = f.json()['flight_id'], f.json()['sim_id']
    ss = flightsim.MANAGER.sessions[sid]
    bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
    ctrl = senaryo(ss); ss.sahte.alt_rel = 60.0
    pg = ctx.new_page()
    pg.set_default_timeout(150000)
    pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
    pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
    pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
    pg.goto(f'{BASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
    pg.wait_for_function('() => window.__smSim && document.querySelector(".fs-gpws")', timeout=240000)
    pg.wait_for_timeout(12000)   # giriş sekansı + kalkış süresi
    return pg, ctrl, ss, fid


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': 'smsid', 'value': tok, 'url': BASE}])
        ctx.add_init_script("try { localStorage.setItem('sm:lang', 'tr'); localStorage.setItem('simumav.consent', 'denied'); } catch (e) {}")
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        # ---- 01 sihirbaz Pilot adımı
        SADECE_RAPOR = os.environ.get('SM_RAPOR') == '1'   # teşhis: yalnız uçuş + rapor
        if not SADECE_RAPOR:
            pg.goto(f'{BASE}/app/#/fly', wait_until='domcontentloaded')
            pg.wait_for_selector('.sm-mode-card.solo, .sm-wizard .sm-cards-drones', timeout=60000)
            if pg.locator('.sm-mode-card.solo').count():   # kip seçimi: Tek oyunculu
                pg.locator('.sm-mode-card.solo').click()
            pg.wait_for_selector('.sm-wizard .sm-cards-drones', timeout=60000)
            pg.wait_for_timeout(2000)
            for _ in range(10):
                if pg.locator('.sm-cards-pilots').count():
                    break
                pg.click('.sm-nav-btn.primary'); pg.wait_for_timeout(500)
            pg.wait_for_selector('.fs-gpws-wz', timeout=20000)
            pg.evaluate("document.querySelector('.fs-gpws-wz').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(600)
            shot(pg, 'sm-01-wizard.png')
            pg.close()
        else:
            pg.close()
        # ---- 02 / 03 uçuş
        pg, ctrl, ss, fid = ucus(ctx)
        pg.mouse.click(700, 450)
        ctrl['faz'] = 'dalis'
        bekle(lambda: (pg.evaluate(ST) or {}).get('primary') == 'PULL_UP', 30, 'PULL UP')
        pg.wait_for_timeout(700)
        shot(pg, 'sm-02-warning-pullup.png')
        ctrl['faz'] = 'aski'; pg.wait_for_timeout(9000)
        ctrl['faz'] = 'alcak'
        bekle(lambda: (pg.evaluate(ST) or {}).get('primary') == 'TOO_LOW', 30, 'TOO LOW')
        pg.wait_for_timeout(600)
        shot(pg, 'sm-03-caution-toolow.png')
        ctrl['faz'] = 'aski'; pg.wait_for_timeout(6000)
        # ---- 04 ayar paneli (İngilizce arayüz, "arayüz dili" seçili)
        pg.evaluate("localStorage.setItem('sm:lang', 'en')")
        pg.evaluate("document.querySelector('.fs-gpws').__gpws.openSettings()"); pg.wait_for_timeout(500)
        shot(pg, 'sm-04-settings.png')
        pg.locator('.fs-gpws-cfg button.b.p').click()
        # ---- 05 uçuş özeti
        ctrl['faz'] = 'yatis'; pg.wait_for_timeout(4000); ctrl['faz'] = 'aski'; pg.wait_for_timeout(3000)
        pg.evaluate('void window.__smSession.endFlight({auto: true})')   # rapor modalı kapanana dek söz bekler → beklenmez
        pg.wait_for_selector('.sm-gpws-card', timeout=60000)
        pg.wait_for_timeout(2500)   # modal açılış animasyonu + çizim
        pg.evaluate("document.querySelector('.sm-gpws-card')?.scrollIntoView({block: 'center'})"); pg.wait_for_timeout(700)
        shot(pg, 'sm-05-report.png')
        hep = pg.evaluate("[...document.querySelectorAll('.sm-report .fs-rp > .fs-rp-gpws')].map(e => getComputedStyle(e).display)")
        if any(x != 'none' for x in hep):
            hatalar.append(f'HEPGO bölümü SIMUMAV raporunda görünüyor: {hep}')
        ctx.close()
        # ---- 06 mobil
        ctxm = b.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale='tr-TR')
        ctxm.add_cookies([{'name': 'smsid', 'value': tok, 'url': BASE}])
        ctxm.add_init_script("try { localStorage.setItem('sm:lang', 'tr'); localStorage.setItem('simumav.consent', 'denied'); } catch (e) {}")
        pm, ctrl2, ss2, fid2 = ucus(ctxm)
        ctrl2['faz'] = 'yatis'
        bekle(lambda: (pm.evaluate(ST) or {}).get('primary') == 'BANK_ANGLE', 30, 'mobil BANK ANGLE')
        pm.wait_for_timeout(800)
        shot(pm, 'sm-06-mobile-bank.png')
        s.post(f'{BASE}/api/fly/{fid2}/stop', json={}, headers=H)
        ctxm.close()
        b.close()
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(4.0)
