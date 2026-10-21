"""HEPGO Uçuş Simülatörü §31 KARA ARACI (rover) arayüzü — görsel doğrulama (Playwright headless shell + SwiftShader; SITL yok).
Sihirbaz: Araç adımında Kara Aracı kartı + sürüş biçimi (Ackermann / paletli-diferansiyel) + rover modelleri, Kalkış adımının olmadığı şerit, Güç adımı
(azami hız satırı yok, yakıt ipucu), özet. Oturum: (a) tarayıcı sahte kipi (?mock=1; sihirbazdan "Uç") — alt bant mod seçici rover kipleri, sanal kumanda
(sol gaz / sağ direksiyon), hassasiyet paneli (iki eksen), harekât paneli; (b) sunucu sahte kinematiği (HEPGO_SITL=0) ile API'den açılan rover oturumu.
Görüntüler /tmp/rover-shots/hepgo-ui-*.png. 3B sahnenin ayrıntısı ayrı betikte (ana ajan).
Çalıştırma: ./.venv/bin/python -m tests.rover_shots_hepgo   (ROVER_ONLY=wiz,mock,api ile parça seçilebilir)
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/rover-shots-hepgo-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39650', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8873)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/rover-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.environ.get('CHROMIUM_PATH') or os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
ONLY = set(filter(None, os.environ.get('ROVER_ONLY', '').split(',')))
def want(k):
    return not ONLY or k in ONLY

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
hatalar, bulgular = [], []


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


def shot(pg, ad, clip=None):
    pg.screenshot(path=str(OUT / ad), clip=clip)
    print('  kare', ad, flush=True)


def kontrol(ad, kosul, ek=''):
    (bulgular if kosul else hatalar).append(f'{"✓" if kosul else "✗"} {ad}{f" ({ek})" if ek else ""}')


def wiz_rover(pg, url):
    pg.goto(url, wait_until='domcontentloaded')
    pg.wait_for_selector('.fs-wizard .fs-types', timeout=90000)
    pg.wait_for_timeout(2500)
    pg.locator('.fs-type', has_text='Kara Aracı').first.click()
    pg.wait_for_timeout(2500)


def hold(pg, keys, ms):
    for k in keys:
        pg.keyboard.down(k)
    pg.wait_for_timeout(ms)
    for k in keys:
        pg.keyboard.up(k)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        # ---- 01–04 sihirbaz (sunucu): Kara Aracı kartı, sürüş biçimi, modeller, güç, özet
        if want('wiz'):
            wiz_rover(pg, f'{BASE}/#/drone/sim?new=1')
            steps = pg.evaluate('window.__fsWz.steps')
            kontrol('sihirbaz adımları: Kalkış yok', 'launch' not in steps, ','.join(steps))
            shot(pg, 'hepgo-ui-01a-wizard-vehicle.png')
            pg.evaluate("document.querySelector('.fs-models-wrap')?.scrollIntoView({block: 'start'})"); pg.wait_for_timeout(2500)
            shot(pg, 'hepgo-ui-01b-wizard-models.png')
            models = pg.evaluate("[...document.querySelectorAll('.fs-model b')].map(e => e.textContent)")
            kontrol('rover modelleri listede', any('4×4' in m for m in models) and any('UGV' in m for m in models), ' · '.join(models))
            pg.evaluate("document.querySelector('.fs-drive-step')?.scrollIntoView({block: 'center'})"); pg.wait_for_timeout(400)
            shot(pg, 'hepgo-ui-01c-wizard-drive.png')
            kontrol('sürüş biçimi bölümü görünür', pg.evaluate("!document.querySelector('.fs-drive-step').hidden"))
            kontrol('varsayılan Ackermann (Keşif 4×4)', pg.evaluate("document.querySelector('.fs-drive.on')?.dataset.drive") == 'ackermann')
            pg.locator('.fs-drive[data-drive="skid"]').click(); pg.wait_for_timeout(300)
            kontrol('skid seçilir', pg.evaluate("document.querySelector('.fs-drive.on')?.dataset.drive") == 'skid')
            kontrol('kontrol düzeni gizli', pg.evaluate("document.querySelector('.fs-layout-step').hidden"))
            pg.evaluate("window.__fsWz.goto('power')"); pg.wait_for_timeout(800)
            kontrol('azami hız satırı gizli', pg.evaluate("document.querySelector('[data-pw=max_speed_ms]').hidden"))
            shot(pg, 'hepgo-ui-02-wizard-power.png')
            pg.evaluate("window.__fsWz.goto('summary')"); pg.wait_for_timeout(1000)
            shot(pg, 'hepgo-ui-03-wizard-summary.png')
            kontrol('özette sürüş biçimi', 'Paletli / diferansiyel' in pg.inner_text('.fs-wz-sum'))
            pg.keyboard.press('Escape'); pg.wait_for_timeout(600)
        # ---- 05–08 tarayıcı sahte kipi: sihirbazdan Uç → oturum ekranı
        if want('mock'):
            pg.goto(f'{BASE}/#/drone/sim?mock=1', wait_until='domcontentloaded'); pg.wait_for_timeout(1500)
            pg.evaluate("localStorage.setItem('fs.ops.on', '0')")
            wiz_rover(pg, f'{BASE}/#/drone/sim?mock=1&new=1')
            pg.evaluate("window.__fsWz.goto('summary')"); pg.wait_for_timeout(800)
            shot(pg, 'hepgo-ui-04-mock-wizard-summary.png')
            pg.locator('.fs-start').click()
            pg.wait_for_selector('.fs-stage', timeout=240000)
            pg.wait_for_function('() => document.querySelector(".fs-msg")?.hidden', timeout=240000)
            pg.wait_for_timeout(9000)   # giriş sekansı + otomatik ARM / AUTO turu
            shot(pg, 'hepgo-ui-05-mock-session.png')
            hud = pg.inner_text('.fs-hud')
            kontrol('HUD: Eğim / Yatış / Hız (km/h), AGL yok', 'Eğim' in hud and 'km/h' in hud and 'AGL' not in hud, hud.replace('\n', ' ')[:160])
            kontrol('Kalkış düğmesi yok', pg.locator('.fs-takeoff-btn').count() == 0)
            kontrol('sürüş biçimi rozeti', pg.locator('.fs-drive-badge').count() == 1)
            tele = pg.evaluate('window.__fsTele && window.__fsTele()')
            kontrol('sahte tele yerde (alt_rel 0) ve hareketli', bool(tele) and tele.get('alt_rel') == 0 and (tele.get('groundspeed') or 0) > 0.5, f"mode {tele and tele.get('mode')} gs {tele and tele.get('groundspeed')}")
            # alt bant mod seçici
            pg.locator('.fs-flt-mode').click(); pg.wait_for_timeout(500)
            ms = pg.evaluate("[...document.querySelectorAll('.fs-flt-grid button')].map(b => b.dataset.mode)")
            kontrol('mod seçici ArduRover kipleri', ms[:4] == ['MANUAL', 'ACRO', 'STEERING', 'HOLD'], ','.join(ms))
            shot(pg, 'hepgo-ui-06-mock-mode-picker.png')
            pg.locator('.fs-flt-grid button[data-mode="MANUAL"]').click(); pg.wait_for_timeout(800)
            # sanal kumanda: W + D ile ileri + sağa
            pg.locator('.fs-bar .btn', has_text='Sanal kumanda').click(); pg.wait_for_timeout(600)
            for k in ('w', 'd'):
                pg.keyboard.down(k)
            pg.wait_for_timeout(1500)
            ch = pg.evaluate("[...document.querySelectorAll('.fs-rc i')].map(i => i.style.height)")
            kn = pg.evaluate("[...document.querySelectorAll('.fs-stick-knob')].map(i => i.style.transform)")
            for k in ('w', 'd'):
                pg.keyboard.up(k)
            kontrol('W+D: gaz (RC3) ve direksiyon (RC1) üstte', ch[0] not in ('50%', '') and ch[2] not in ('50%', ''), f'{ch} {kn}')
            pg.wait_for_timeout(2500)
            tele = pg.evaluate('window.__fsTele && window.__fsTele()')
            kontrol('MANUAL + sanal kumanda ile sürüş', bool(tele) and tele.get('mode') == 'MANUAL', f"gs {tele and tele.get('groundspeed')}")
            for k in ('w',):
                pg.keyboard.down(k)
            pg.wait_for_timeout(700)
            shot(pg, 'hepgo-ui-07-mock-virtual-rc.png')
            pg.keyboard.up('w')
            lbl = pg.evaluate("[...document.querySelectorAll('.fs-stick small')].map(e => e.textContent)")
            kontrol('çubuk etiketleri (Gaz / Fren · Direksiyon)', lbl == ['Gaz / Fren', 'Direksiyon'], ' | '.join(lbl))
            print('  RC çubukları:', ch, flush=True)
            pg.locator('.fs-rcf-btn').click(); pg.wait_for_timeout(400)
            ax = pg.evaluate("[...document.querySelectorAll('.fs-rcf-seg.ax button')].map(b => b.textContent)")
            kontrol('hassasiyet: iki eksen', ax == ['Direksiyon', 'Gaz'], ' | '.join(ax))
            shot(pg, 'hepgo-ui-08-mock-rc-feel.png')
            pg.locator('.fs-rcf-x').click(); pg.wait_for_timeout(200)
            pg.locator('.fs-bar .btn', has_text='Sanal kumanda').click(); pg.wait_for_timeout(300)
            # harekât paneli (P)
            pg.locator('.fs-ops-btn').click(); pg.wait_for_timeout(1500)
            shot(pg, 'hepgo-ui-09-mock-ops-panel.png')
            pnl = pg.inner_text('.fs-pn-tiles')
            kontrol('panel: EĞİM karosu, KOMUT = Dur', 'EĞİM' in pnl and 'Dur' in pnl, pnl.replace('\n', ' ')[:200])
            pg.locator('.fs-ops-btn').click(); pg.wait_for_timeout(300)
            pg.evaluate("location.hash = '#/drone/sim?mock=1'"); pg.wait_for_timeout(1500)
        # ---- 10 sunucu sahte kinematiği: API ile rover oturumu (drive skid) → oturum ekranı
        if want('api'):
            body = {'mode': 'sitl', 'type': 'rover', 'center_id': c['id'], 'drive': 'skid', 'model': {'id': 'builtin:rover_ugv'},
                    'world': {'mode': 'procedural', 'seed': 7, 'size_m': 3000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.2, 'building_count': 10}}
            r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
            kontrol('API rover oturumu 201', r.status_code == 201, r.text[:200])
            if r.status_code == 201:
                js = r.json(); sid = js['id']
                kontrol('to_dict ground + drive', js.get('ground') is True and js.get('drive') == 'skid', f"ground {js.get('ground')} drive {js.get('drive')}")
                ss = flightsim.MANAGER.sessions[sid]
                bekle(lambda: ss.state == 'HAZIR', 120, 'HAZIR')
                rt = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 20}})
                kontrol('takeoff rover 400', rt.status_code == 400, rt.text[:120])
                s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'arm', 'params': {}})
                s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'mode', 'params': {'mode': 'AUTO'}})
                pg.evaluate("window.__fsIntroHold = undefined")
                pg.evaluate(f"location.hash = '#/drone/sim/{sid}'")
                pg.wait_for_selector('.fs-stage', timeout=240000)
                pg.wait_for_function('() => document.querySelector(".fs-msg")?.hidden', timeout=240000)
                pg.wait_for_timeout(10000)
                shot(pg, 'hepgo-ui-10-api-session.png')
                pg.locator('.fs-flt-mode').click(); pg.wait_for_timeout(400)
                shot(pg, 'hepgo-ui-11-api-mode-picker.png')
                pg.keyboard.press('Escape')
                s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / 'hepgo-ui-hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(bulgular))
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
