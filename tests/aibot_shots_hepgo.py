"""HEPGO Uçuş Simülatörü §44 — YAPAY ZEKÂ PİLOT + OYUN EFEKTLERİ görsel doğrulaması (Playwright headless shell; sahte SITL HEPGO_SITL=0; bot
sürücüleri sunucuda sahte kinematikte uçar). Görüntüler /tmp/aibot-shots/hepgo-*.png:
  01 davet adımı: yapay zekâ pilot ekle (seviye + çipler) · 02 özet · 03 salon: botlar (AI · seviye rozeti, 🤖, kaldır ✕, ekle satırı) ·
  04 yarış: 3B'de bot oyuncular + sıralama · 05 sonuç: AI rozeti + puan sayacı · 06 ses kapsülü menüsünde "Oyun efektleri" · 07 Karşılaşmalar sekmesi.
Davetli (Ayşe) tarayıcısızdır (3B "hazır" sayılır); kurucu rota pilotuyla yavaş uçar.
Çalıştırma: ./.venv/bin/python -m tests.aibot_shots_hepgo
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/aibot-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39950', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='2', SIM_MATCH_MAX_SESSIONS='6')
PORT = int(os.environ.get('SHOT_PORT') or 8873)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/aibot-shots')
OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth, flightsim, flightsim_match  # noqa: E402
from app import flightsim_match_core as core  # noqa: E402

core.HAZIRLIK_ZAMAN_ASIMI_S = 900.0   # yazılım WebGL'de iki 3B dünya yavaş kurulur
from app.main import app  # noqa: E402
from tests.match_bot import rota_pilotu  # noqa: E402

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
hatalar = []


def oturum(kullanici, sifre):
    r = requests.Session()
    assert r.post(f'{BASE}/api/auth/login', json={'username': kullanici, 'password': sifre}).status_code == 200, kullanici
    r.post(f'{BASE}/api/kvkk/accept-terms', json={})
    r.post(f'{BASE}/api/location/consent', json={'granted': False})
    return r


s = oturum('demo@firma.com', 'Demo-Sifre-12')
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Yarış Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
for u, ad in (('ayse@firma.com', 'Ayşe Pilot'), ('mehmet@firma.com', 'Mehmet Pilot'), ('zeynep@firma.com', 'Zeynep Uçar'), ('can@firma.com', 'Can Demir')):
    r = s.post(f'{BASE}/api/users', json={'username': u, 'full_name': ad, 'roles': [auth.PILOT], 'password': 'Ucus-Gizli-77'})
    assert r.status_code == 200, r.text
sa = oturum('ayse@firma.com', 'Ucus-Gizli-77')
sm = oturum('mehmet@firma.com', 'Ucus-Gizli-77')
ME = {'host': s.get(f'{BASE}/api/auth/me').json()['id'], 'ayse': sa.get(f'{BASE}/api/auth/me').json()['id'], 'mehmet': sm.get(f'{BASE}/api/auth/me').json()['id']}
M_ = f'{BASE}/api/drone/sim/matches'


def shot(pg, ad):
    pg.screenshot(path=str(OUT / ad), timeout=240000)
    print('  kare', ad, flush=True)


def kontrol(ad, kosul):
    print(('  ✓ ' if kosul else '  ✗ ') + ad, flush=True)
    if not kosul:
        hatalar.append(ad)


def baglam(b, ses, w=1440, hh=900):
    ctx = b.new_context(viewport={'width': w, 'height': hh}, locale='tr-TR')
    ctx.add_cookies([{'name': auth.COOKIE, 'value': ses.cookies.get(auth.COOKIE), 'url': BASE}])
    pg = ctx.new_page()
    pg.set_default_timeout(90000)
    pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
    pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
    return ctx, pg


def mac_durumu(mid):
    return s.get(f'{M_}/{mid}').json()


def bekle(fn, sn=120, adim=0.5):
    t = time.time() + sn
    while time.time() < t:
        v = fn()
        if v:
            return v
        time.sleep(adim)
    return fn()


def ns_yaz(pg, etiket, deger):
    inp = pg.locator('.fs-ns', has_text=etiket).locator('.fs-ns-in').first
    inp.fill(str(deger)); inp.press('Enter'); pg.wait_for_timeout(150)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE, args=ARGS)
    ch, ph = baglam(b, s)
    ph.goto(f'{BASE}/#/drone/sim?tab=matches', wait_until='domcontentloaded')
    ph.wait_for_selector('.fs-new-match'); ph.wait_for_timeout(1500)
    ph.click('.fs-new-match')
    ph.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=90000); ph.wait_for_timeout(2000)
    ph.evaluate("window.__fsWz.goto('rings')"); ph.wait_for_timeout(500)
    ns_yaz(ph, 'Halka sayısı', 3); ns_yaz(ph, 'Minimum yükseklik', 12); ns_yaz(ph, 'Maksimum yükseklik', 24); ns_yaz(ph, 'Halka çapı', 16); ns_yaz(ph, 'Parkur yarıçapı', 110)
    ph.wait_for_timeout(800)
    ph.evaluate("window.__fsWz.goto('invite')"); ph.wait_for_timeout(600)
    ph.locator('.fs-mt-list[data-side="left"] li', has_text='Ayşe Pilot').dblclick()
    ph.click('.fs-mt-lv button[data-level="hard"]'); ph.click('.fs-mt-bots .btn.primary')
    ph.click('.fs-mt-lv button[data-level="easy"]'); ph.click('.fs-mt-bots .btn.primary')
    ph.wait_for_timeout(400)
    chips = ph.locator('.fs-mt-chip').all_inner_texts()
    kontrol(f'iki bot çipi: {chips}', len(chips) == 2 and 'AI-Şahin (Zor)' in chips[0] and 'AI-Kartal (Kolay)' in chips[1])
    kontrol('sayaç 3 / 7', '3 / 7' in ph.locator('.fs-mt-col[data-side="right"] .badge').inner_text())
    ph.locator('.fs-mt-bots').scroll_into_view_if_needed(); ph.wait_for_timeout(300)
    shot(ph, 'hepgo-01-davet-yapay-zeka-ekle.png')
    ph.click('.fs-wz-next'); ph.wait_for_timeout(1200)
    shot(ph, 'hepgo-02-ozet.png')
    ph.click('.fs-start')
    ph.wait_for_function("() => /#\\/drone\\/sim\\/match\\/\\d+/.test(location.hash)", timeout=60000)
    mid = int(ph.evaluate("location.hash.match(/match\\/(\\d+)/)[1]"))
    ph.wait_for_selector('.fs-mt-players li[data-bot="1"]'); ph.wait_for_timeout(1200)
    rozet = ph.locator('.fs-mt-players .fs-ai-badge').all_inner_texts()
    kontrol(f'salonda AI rozetleri: {rozet}', rozet == ['AI · Zor', 'AI · Kolay'])
    kontrol('salonda bot ekle satırı', ph.locator('.fs-mt-addbot').count() == 1)
    shot(ph, 'hepgo-03-salon-botlar.png')
    # davetli gelir → HAZIRLIK (insan + 2 bot + kurucu)
    assert sa.post(f'{M_}/{mid}/join').status_code == 200
    ph.wait_for_function("() => /#\\/drone\\/sim\\/\\d+\\?match=/.test(location.hash)", timeout=60000)
    rt = flightsim_match.MANAGER.get(mid)
    rt.ready.add(ME['ayse'])
    kontrol('geri sayım başladı', bekle(lambda: mac_durumu(mid)['state'] in ('GERI_SAYIM', 'YARIS'), 300, 0.25))
    kontrol('yarış başladı', bekle(lambda: mac_durumu(mid)['state'] == 'YARIS', 30, 0.25))
    d = mac_durumu(mid)
    merkez = {'lat': 39.925, 'lon': 32.837, 'alt': 900}
    for p_ in d['players']:
        if p_['id'] > 0:
            rota_pilotu(flightsim.MANAGER.get(p_['session_id']), d['rings'], merkez, hiz=3.0 if p_['id'] == ME['host'] else 2.5)
    kontrol('botlar kalktı', bekle(lambda: sum(1 for p_ in mac_durumu(mid)['players'] if p_['id'] < 0 and (flightsim.MANAGER.get(p_['session_id']).tele.get('alt_rel') or 0) > 5) == 2, 60, 0.5))
    ph.wait_for_timeout(14000)
    ghost = ph.evaluate("window.__fsMatch?.layer?.ghostInfo?.() || []")
    kontrol(f'kurucu ekranında 3 diğer oyuncu (2 bot): {ghost}', len(ghost) == 3)
    shot(ph, 'hepgo-04-yarista-botlar.png')
    sonuc = bekle(lambda: (lambda m: m if m['state'] == 'BITTI' else None)(mac_durumu(mid)), 400, 1.0)
    kontrol(f"bot kazandı: {sonuc and sonuc.get('winner')}", bool(sonuc) and (sonuc.get('winner') or 0) < 0)
    ph.wait_for_selector('.fs-mt-result:not([hidden]) table', timeout=30000); ph.wait_for_timeout(4500)
    kontrol('sonuçta AI rozetleri', ph.locator('.fs-mt-result .fs-ai-badge').count() == 2)
    kontrol(f"puan sayacı: {ph.locator('.fs-mt-score b').inner_text()}", ph.locator('.fs-mt-score b').inner_text() == ph.locator('.fs-mt-score b').get_attribute('data-score'))
    shot(ph, 'hepgo-05-sonuc-ai-rozeti-puan.png')
    ph.click('.fs-mt-result .acts .btn'); ph.wait_for_timeout(300)
    ph.evaluate("document.querySelector('.fs-audio-more')?.click()"); ph.wait_for_timeout(500)
    kontrol('ses menüsünde Oyun efektleri', ph.locator('.fs-audio-menu .fs-sfx-row').count() == 1)
    try:
        ph.locator('.fs-audio-menu:has(.fs-sfx-row)').first.screenshot(path=str(OUT / 'hepgo-06-ses-menusu-oyun-efektleri.png')); print('  kare hepgo-06-ses-menusu-oyun-efektleri.png', flush=True)
    except Exception as e:   # noqa: BLE001
        hatalar.append(f'ses menüsü: {str(e)[:120]}')
    ph.goto(f'{BASE}/#/drone/sim?tab=matches', wait_until='domcontentloaded')
    ph.wait_for_selector('.fs-mt-table tbody tr', timeout=300000); ph.wait_for_timeout(1200)
    shot(ph, 'hepgo-07-karsilasmalar-sekmesi.png')
    b.close()

server.should_exit = True
time.sleep(1.5)
print('HATALAR:' if hatalar else 'Hata yok', *hatalar[:30], sep='\n  ')
sys.exit(1 if [x for x in hatalar if not x.startswith('KONSOL')] else 0)
