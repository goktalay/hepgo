"""HEPGO Uçuş Simülatörü §42 — UÇUŞ UYARI SİSTEMİ görsel doğrulama (Playwright headless shell + SwiftShader; sahte kinematik, senaryolu).
Görüntüler /tmp/gpws-shots/hep-*.png:
  01 PULL UP (kırmızı WARNING kutusu, MASTER WARNING yanıp söner, kenar vinyeti) · 02 B ile onaylandı (sabit, ses susar) · 03 TOO LOW (sarı CAUTION)
  04 gimbal HUD'unda BANK ANGLE (kutu yerine HUD yazısı) · 05 FPV OSD'de · 06 ses kapsülü menüsü satırı · 07 ayar paneli · 08 özet raporda bölüm
  09 sihirbaz özet adımında seçici · 10 mobil (390×844) WARNING · 11 kayıttan oynatmada yeniden hesap (sahte kayıt kipi)
Çalıştırma: ./.venv/bin/python -m tests.gpws_shots_hepgo
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
DATA = '/tmp/gpws-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39750', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8861)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/gpws-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--autoplay-policy=no-user-gesture-required']

import requests  # noqa: E402
import uvicorn  # noqa: E402
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
ST = "(document.querySelector('.fs-gpws')?.__gpws?.state?.() || null)"


def bekle(pred, sec, ad):
    t0 = time.time()
    while time.time() - t0 < sec:
        try:
            if pred():
                return True
        except Exception:   # noqa: BLE001
            pass
        time.sleep(0.2)
    hatalar.append(f'{ad}: {sec} sn içinde olmadı'); return False


def shot(pg, ad):
    pg.screenshot(path=str(OUT / ad))
    print('  kare', ad, flush=True)


def senaryo(ss):
    """Sahte kinematiği senaryoyla sür: ctrl['faz'] → aski (60 m) · dalis (12 m/s alçalma) · yatis (50°) · alcak (3 m, 12 m/s)."""
    k = ss.sahte
    ctrl = {'faz': 'aski', 'alt': 60.0, 'roll': 0.0}

    def adim(dt):
        k.sure_ms += dt * 1000
        k.armed, k.mode = True, 'LOITER'
        f = ctrl['faz']
        hedef_roll = math.radians(50) if f == 'yatis' else 0.0
        eski = k.roll
        k.roll += max(-1.5 * dt, min(1.5 * dt, hedef_roll - k.roll))
        k.rs = (k.roll - eski) / max(dt, 1e-3)
        k.pitch, k.ps, k.ys = 0.0, 0.0, 0.0
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


def oturum(pg, ss, sid):
    pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')
    pg.wait_for_function('() => window.__fsSim && document.querySelector(".fs-gpws")', timeout=240000)
    pg.wait_for_timeout(1500)
    if pg.locator('.modal button:has-text("Reddet")').count():
        pg.locator('.modal button:has-text("Reddet")').first.click(); pg.wait_for_timeout(400)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        ctx.add_init_script("try { localStorage.removeItem('fs.gpws'); } catch (e) {}")
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        # ---- 09 sihirbaz: özet adımında "Uçuş uyarıları"
        pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=60000)
        pg.evaluate("window.__fsWz.goto('summary')"); pg.wait_for_timeout(1200)
        pg.evaluate("document.querySelector('.fs-gpws-wz')?.scrollIntoView({block: 'center'})"); pg.wait_for_timeout(500)
        if not pg.locator('.fs-gpws-wz').count():
            hatalar.append('sihirbazda uyarı seçici yok')
        shot(pg, 'hep-09-wizard.png')
        # ---- canlı oturum (sahte kinematik)
        r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False},
                                                           'world': {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.25, 'building_count': 30}})
        assert r.status_code == 201, r.text
        sid = r.json()['id']
        ss = flightsim.MANAGER.sessions[sid]
        bekle(lambda: ss.state == 'HAZIR', 60, 'HAZIR')
        ctrl = senaryo(ss)
        ss.sahte.alt_rel = 60.0
        oturum(pg, ss, sid)
        pg.mouse.click(700, 450)   # ses kilidi (ilk etkileşim)
        pg.wait_for_timeout(9000)   # kalkış süresi (havalanma + 3 sn) geçsin
        # ---- 01 PULL UP
        ctrl['faz'] = 'dalis'
        bekle(lambda: (pg.evaluate(ST) or {}).get('primary') == 'PULL_UP', 20, 'PULL UP')
        pg.wait_for_timeout(700)
        print('  durum:', pg.evaluate(ST), flush=True)
        shot(pg, 'hep-01-warning-pullup.png')
        # ---- 02 onay (B): ses susar, kutu sabit, MASTER lambası sabit
        pg.evaluate('document.activeElement && document.activeElement.blur && document.activeElement.blur()')
        pg.keyboard.press('b'); pg.wait_for_timeout(600)
        st = pg.evaluate(ST)
        if not st or not all(a['acked'] for a in st['active']):
            hatalar.append(f'onay işlemedi: {st}')
        shot(pg, 'hep-02-warning-acked.png')
        ctrl['faz'] = 'aski'; pg.wait_for_timeout(9000)
        # ---- 03 TOO LOW (sarı)
        ctrl['faz'] = 'alcak'
        bekle(lambda: (pg.evaluate(ST) or {}).get('primary') == 'TOO_LOW', 20, 'TOO LOW')
        pg.wait_for_timeout(600)
        shot(pg, 'hep-03-caution-toolow.png')
        ctrl['faz'] = 'aski'; pg.wait_for_timeout(8000)
        # ---- 04 gimbal HUD + BANK ANGLE
        pg.evaluate("window.__fsSim.setCamera('fpv'); window.__fsSim.setGimbal(0)")
        ctrl['faz'] = 'yatis'
        bekle(lambda: (pg.evaluate(ST) or {}).get('primary') == 'BANK_ANGLE', 20, 'BANK ANGLE')
        pg.wait_for_timeout(1200)
        st = pg.evaluate(ST)
        if not st.get('hud'):
            hatalar.append(f'gimbal kipinde kutu HUD\'a devredilmedi: {st}')
        shot(pg, 'hep-04-gimbal-hud-bank.png')
        # ---- 05 FPV OSD
        pg.evaluate("window.__fsSim.setCamera('pilot')"); pg.wait_for_timeout(1500)
        shot(pg, 'hep-05-fpv-osd-bank.png')
        ctrl['faz'] = 'aski'
        pg.evaluate("window.__fsSim.setCamera('follow')"); pg.wait_for_timeout(5000)
        # ---- 06 ses kapsülü menüsü satırı + 07 ayar paneli
        pg.locator('.fs-audio-more').first.click(); pg.wait_for_timeout(400)
        shot(pg, 'hep-06-audio-menu.png')
        pg.locator('.fs-gpws-gear').first.click(); pg.wait_for_timeout(500)
        shot(pg, 'hep-07-settings.png')
        pg.locator('.fs-gpws-cfg button.b.p').click(); pg.wait_for_timeout(300)
        # ---- 08 özet rapor
        ctrl['faz'] = 'yatis'; pg.wait_for_timeout(4000); ctrl['faz'] = 'aski'; pg.wait_for_timeout(2000)
        pg.locator('button.danger:has-text("Bitir")').first.click(); pg.wait_for_timeout(800)
        pg.locator('.modal button:has-text("Bitir")').last.click()
        pg.wait_for_selector('.fs-rp-gpws', timeout=30000)
        pg.evaluate("document.querySelector('.fs-rp-gpws')?.scrollIntoView({block: 'center'})"); pg.wait_for_timeout(600)
        shot(pg, 'hep-08-report.png')
        print('  sunucu özeti:', ss.uyarilar.ozet() and {k: ss.uyarilar.ozet()[k] for k in ('warnings', 'cautions', 'score', 'grade')}, flush=True)
        ctx.close()
        # ---- 10 mobil
        ctxm = b.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale='tr-TR')
        ctxm.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pm = ctxm.new_page()
        pm.on('pageerror', lambda e: hatalar.append('MOBİL SAYFA: ' + str(e)[:400]))
        r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False},
                                                           'world': {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'time': 'day', 'wind_ms': 0}})
        sid2 = r.json()['id']
        ss2 = flightsim.MANAGER.sessions[sid2]
        bekle(lambda: ss2.state == 'HAZIR', 60, 'HAZIR 2')
        ctrl2 = senaryo(ss2); ss2.sahte.alt_rel = 60.0
        oturum(pm, ss2, sid2)
        pm.wait_for_timeout(9000)
        ctrl2['faz'] = 'yatis'
        bekle(lambda: (pm.evaluate(ST) or {}).get('primary') == 'BANK_ANGLE', 20, 'mobil BANK ANGLE')
        pm.wait_for_timeout(800)
        shot(pm, 'hep-10-mobile-bank.png')
        ctrl2['faz'] = 'dalis'
        bekle(lambda: (pm.evaluate(ST) or {}).get('primary') == 'PULL_UP', 20, 'mobil PULL UP')
        pm.wait_for_timeout(600)
        shot(pm, 'hep-10b-mobile-pullup.png')
        ctxm.close()
        s.delete(f'{BASE}/api/drone/sim/sessions/{sid2}')
        # ---- 11 kayıttan oynatma (sahte kayıt kipi): değerlendirici karelerle ilerler, sunucuya göndermez (kuyruk 0)
        ctx3 = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx3.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        p3 = ctx3.new_page()
        p3.on('pageerror', lambda e: hatalar.append('KAYIT SAYFA: ' + str(e)[:400]))
        p3.goto(f'{BASE}/#/drone/sim/mock-1r?mock=1', wait_until='domcontentloaded')
        if bekle(lambda: p3.evaluate("!!document.querySelector('.fs-gpws')"), 120, 'kayıt sahnesi'):
            p3.wait_for_timeout(3000)
            p3.evaluate("document.querySelector('.fs-play-btn')?.click()")
            ok = bekle(lambda: ((p3.evaluate(ST) or {}).get('evalT') or 0) > 5, 60, 'kayıtta değerlendirme')
            print('  kayıt durumu:', p3.evaluate(ST), flush=True)
            if ok and (p3.evaluate(ST) or {}).get('queue'):
                hatalar.append('kayıttan oynatmada sunucu kuyruğu dolu')
        ctx3.close()
        b.close()
except Exception:
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
    time.sleep(4.0)
