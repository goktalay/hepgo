"""HEPGO Uçuş Simülatörü §6 — "Yeni Simülasyon Başlat" adım adım sihirbazı: görsel doğrulama + uçtan uca başlatma (Playwright headless shell).
Uygulama aynı süreçte açılır (sahte SITL: HEPGO_SITL=0). Görüntüler /tmp/wizard-shots/:
  <tema>-<genişlik>-<nn>-<adım>.png — açık/koyu tema × masaüstü (1440) / tablet (900) / mobil (390); sabit kanat (kalkış adımı dahil) tüm adımlar
  + kopterde kalkış adımının atlandığı şerit, doğrulama (merkezsiz İleri pasif), Enter ile ilerleme, kayıttan oynat kipi şeridi.
Son olarak sihirbazdan GERÇEKTEN oturum başlatılır (Başlat → POST /sessions → oturum ekranı) ve gövde denetlenir (tip, merkez, launch, power).
Çalıştırma: ./.venv/bin/python -m tests.wizard_shots_hepgo        (WZ_ONLY=desktop-light,… alt küme)
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/wizard-shots-hepgo-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39550', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8861)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/wizard-shots')
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
ONLY = set(filter(None, os.environ.get('WZ_ONLY', '').split(',')))

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
s.post(f'{BASE}/api/drone/centers', json={'name': 'Bedesten Pisti', 'lat': 40.01, 'lon': 32.70, 'alt': 742})
hatalar = []
VIEWS = {'desktop': (1440, 900), 'tablet': (900, 1100), 'mobile': (390, 844)}


def shot(pg, ad):
    pg.screenshot(path=str(OUT / ad), timeout=240000)
    print('  kare', ad, flush=True)


def ac(pg, theme):
    pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
    pg.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=60000)
    pg.evaluate(f"document.documentElement.dataset.theme = {theme!r} === 'dark' ? 'dark' : ''; if ({theme!r} !== 'dark') delete document.documentElement.dataset.theme")
    pg.wait_for_timeout(1500)


def adim(pg):
    return pg.evaluate('window.__fsWz && window.__fsWz.step')


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        for theme in ('light', 'dark'):
            for vk, (w, hh) in VIEWS.items():
                if ONLY and f'{vk}-{theme}' not in ONLY:
                    continue
                ctx = b.new_context(viewport={'width': w, 'height': hh}, locale='tr-TR', device_scale_factor=2 if vk == 'mobile' else 1, is_mobile=vk == 'mobile', has_touch=vk != 'desktop')
                ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
                pg = ctx.new_page()
                pg.set_default_timeout(60000)
                pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
                pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
                ac(pg, theme)
                pg.locator('.fs-type', has_text='Sabit Kanat').first.click(); pg.wait_for_timeout(1200)
                steps = pg.evaluate('window.__fsWz.steps')
                assert steps == ['vehicle', 'world', 'launch', 'power', 'camera', 'targets', 'site', 'summary'], steps
                for i, k in enumerate(steps):
                    assert adim(pg) == k, (adim(pg), k)
                    if k == 'launch':
                        pg.locator('.fs-launch[data-launch="ramp"]').click(); pg.wait_for_timeout(300)
                    if k == 'targets':
                        pg.locator('.fs-tg-add').click(); pg.wait_for_timeout(1500)
                    if k == 'site':
                        card = pg.locator('.fs-site-card[data-key="radar"]')
                        if 'on' not in (card.get_attribute('class') or ''):
                            card.click(); pg.wait_for_timeout(200)
                    pg.wait_for_timeout(900 if k in ('vehicle', 'world', 'launch') else 400)
                    shot(pg, f'{theme}-{vk}-{i + 1:02d}-{k}.png')
                    if vk == 'mobile' and k in ('world', 'power', 'targets'):   # mobil: uzun adımın alt kısmı
                        pg.evaluate("document.querySelector('.fs-wizard-modal .modal-body').scrollTop = 1e6"); pg.wait_for_timeout(300)
                        shot(pg, f'{theme}-{vk}-{i + 1:02d}-{k}-alt.png')
                    if k != 'summary':
                        nb = pg.locator('.fs-wz-next')
                        assert nb.is_enabled(), f'{k}: İleri pasif ({pg.locator(".fs-wz-why").text_content()})'
                        nb.click(); pg.wait_for_timeout(300)
                ctx.close()
        # ---- davranış: kopterde Kalkış yok; merkezsiz doğrulama; Enter ile ilerleme; şerit tıklaması; kayıttan oynat kipi; gerçek Başlat
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(60000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        ac(pg, 'light')
        pg.locator('.fs-type', has_text='Multikopter').first.click(); pg.wait_for_timeout(500)
        steps = pg.evaluate('window.__fsWz.steps')
        if 'launch' in steps:
            hatalar.append(f'kopterde kalkış adımı var: {steps}')
        shot(pg, 'davranis-01-kopter-serit.png')
        # Enter = İleri (odak gövdede)
        pg.locator('.fs-wz-ph-t').click()
        pg.keyboard.press('Enter'); pg.wait_for_timeout(400)
        if adim(pg) != 'world':
            hatalar.append(f'Enter ilerletmedi: {adim(pg)}')
        # şerit: Özet'e atlama (aradaki adımlar geçerli) → kartlar + Düzenle → Dünya
        pg.locator('.fs-wz-chip[data-step="summary"] button').click(); pg.wait_for_timeout(500)
        if adim(pg) != 'summary':
            hatalar.append(f'şerit atlaması olmadı: {adim(pg)}')
        n_card = pg.locator('.fs-wz-sum-card').count()
        if n_card != len(pg.evaluate('window.__fsWz.steps')) - 1:
            hatalar.append(f'özet kart sayısı {n_card}')
        shot(pg, 'davranis-02-ozet.png')
        pg.locator('.fs-wz-sum-card[data-step="world"] .fs-wz-edit').click(); pg.wait_for_timeout(400)
        if adim(pg) != 'world':
            hatalar.append(f'Düzenle dönmedi: {adim(pg)}')
        # hedef doğrulaması: geçersiz hedef → Hedefler adımında İleri pasif
        pg.evaluate("window.__fsWz.goto('targets')"); pg.wait_for_timeout(300)
        pg.locator('.fs-tg-add').click(); pg.wait_for_timeout(500)
        shot(pg, 'davranis-03-hedef.png')
        # kalkış ayarı kaydırıcısı + değer kutusu (sabit kanat)
        pg.evaluate("window.__fsWz.goto('vehicle')"); pg.wait_for_timeout(300)
        pg.locator('.fs-type', has_text='Sabit Kanat').first.click(); pg.wait_for_timeout(500)
        pg.evaluate("window.__fsWz.goto('launch')"); pg.wait_for_timeout(300)
        pg.locator('.fs-launch[data-launch="vehicle"]').click(); pg.wait_for_timeout(200)
        box = pg.locator('.fs-launch-param:not([hidden]) .fs-ns-in').first
        box.fill('85'); box.press('Enter'); pg.wait_for_timeout(200)
        if adim(pg) != 'launch':
            hatalar.append('değer kutusunda Enter adımı ilerletti')
        # güç: mAh kutusuna 12000 → kaydırıcı log ölçekte; değer gövdeye
        pg.evaluate("window.__fsWz.goto('power')"); pg.wait_for_timeout(300)
        mah = pg.locator('[data-pw="elec_mah"] .fs-ns-in')
        mah.fill('12000'); mah.press('Tab'); pg.wait_for_timeout(200)
        pg.evaluate("window.__fsWz.goto('summary')"); pg.wait_for_timeout(400)
        pg.locator('.fs-rec-opts input[type=checkbox]').first.uncheck()   # ekran kaydı kapalı: Başlat'ta ekran paylaşımı izni istenmez (başsız tarayıcı)
        shot(pg, 'davranis-04-ozet-ucak.png')
        # Gerçek başlatma: istek gövdesi yakalanır
        bodies = []
        pg.on('request', lambda r: bodies.append(r.post_data_json) if r.method == 'POST' and r.url.endswith('/api/drone/sim/sessions') else None)
        pg.locator('.fs-start').click()
        pg.wait_for_function("() => /#\\/drone\\/sim\\/\\d+/.test(location.hash)", timeout=120000)
        pg.wait_for_timeout(2500)
        shot(pg, 'davranis-05-oturum.png')
        print('  başlatma gövdesi:', bodies[:1], flush=True)
        if not bodies:
            hatalar.append('POST /sessions yok')
        else:
            bd = bodies[0]
            for k, v in (('mode', 'sitl'), ('type', 'sabit_kanat'), ('layout', 'elevon')):
                if bd.get(k) != v:
                    hatalar.append(f'gövde {k}={bd.get(k)!r}')
            if bd.get('center_id') not in (c['id'],) and not isinstance(bd.get('center_id'), int):
                hatalar.append(f'center_id {bd.get("center_id")}')
            if (bd.get('world') or {}).get('launch', {}).get('method') != 'vehicle' or bd['world']['launch'].get('release_kmh') != 85:
                hatalar.append(f'launch {bd.get("world", {}).get("launch")}')
            if (bd.get('power') or {}).get('elec_mah') != 12000:
                hatalar.append(f'power {bd.get("power")}')
            if not bd.get('targets') or len(bd['targets']['items']) != 1:
                hatalar.append(f'targets {bd.get("targets")}')
        sid = pg.evaluate("location.hash.match(/sim\\/(\\d+)/)[1]")
        r = s.get(f'{BASE}/api/drone/sim/sessions/{sid}')
        print('  oturum:', r.status_code, r.json().get('type'), r.json().get('state'), flush=True)
        s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        # kayıttan oynat kipi şeridi (log yoksa İleri pasif + gerekçe)
        ac(pg, 'light')
        pg.locator('.fs-wz-top .seg button', has_text='Kayıttan oynat').click(); pg.wait_for_timeout(1200)
        rsteps = pg.evaluate('window.__fsWz.steps')
        print('  kayıt adımları:', rsteps, flush=True)
        if rsteps[0] != 'log' or 'power' in rsteps:
            hatalar.append(f'kayıt adımları {rsteps}')
        if pg.locator('.fs-wz-next').is_enabled():
            hatalar.append('log yokken İleri etkin')
        shot(pg, 'davranis-06-kayit-kipi.png')
        ctx.close()
        b.close()
finally:
    server.should_exit = True
print('HATALAR:' if hatalar else 'hata yok', *hatalar, sep='\n  ')
sys.exit(1 if hatalar else 0)
