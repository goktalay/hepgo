"""HEPGO Uçuş Simülatörü §33 — ÇOK OYUNCULU KARŞILAŞMA: görsel doğrulama + uçtan uca akış, İKİ ayrı tarayıcı bağlamı (kurucu + davetli) ve
tarayıcısız üçüncü oyuncu (Playwright headless shell; sahte SITL HEPGO_SITL=0; uygulama aynı süreçte). Görüntüler /tmp/match-shots/:
  01 ana ekran (Yeni Karşılaşma düğmesi) · 02 sihirbaz Halkalar · 03-04 Davet et (iki liste: boş → davet edildi) · 05 özet (yalnız Başlat)
  06 kurucu bekleme salonu (bekleniyor) · 07 davetlinin zil bildirimi · 08-09 salonlar (geldi / bekleniyor) · 10 hazırlık bekleme katmanı ·
  11 geri sayım · 12-13 yarış (halkalar + diğer oyuncular, iki taraf) · 14-15 sonuç ekranı (iki taraf) · 16 Karşılaşmalar sekmesi.
Rota pilotu (tests/match_bot.py) sunucu tarafında sahte kinematiği halkalardan geçirir.
Çalıştırma: ./.venv/bin/python -m tests.match_shots_hepgo
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/match-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39850', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='2', SIM_MATCH_MAX_SESSIONS='6')
PORT = int(os.environ.get('SHOT_PORT') or 8871)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/match-shots')
shutil.rmtree(OUT, ignore_errors=True)
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
    ca, pa = baglam(b, sa)
    # ---------- kurucu: ana ekran → Yeni Karşılaşma sihirbazı ----------
    ph.goto(f'{BASE}/#/drone/sim?tab=matches', wait_until='domcontentloaded')
    ph.wait_for_selector('.fs-new-match'); ph.wait_for_timeout(1500)
    shot(ph, '01-ana-ekran-yeni-karsilasma.png')
    ph.click('.fs-new-match')
    ph.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=90000); ph.wait_for_timeout(2500)
    tipler = ph.locator('.fs-wz .fs-types .fs-type').all_inner_texts()
    kontrol('karşılaşmada kara aracı yok', not any('Kara Aracı' in t for t in tipler))
    st = ph.evaluate('window.__fsWz.steps')
    kontrol(f'adımlar Halkalar + Davet et, Hedefler/Yer kontrol yok: {st}', 'rings' in st and 'invite' in st and 'site' not in st and 'targets' not in st)
    kontrol('dron kaydı bölümü yok', ph.locator('.fs-drone-step').count() == 0 or not ph.locator('.fs-drone-step').is_visible())
    ph.evaluate("window.__fsWz.goto('rings')"); ph.wait_for_timeout(500)
    ns_yaz(ph, 'Halka sayısı', 5); ns_yaz(ph, 'Minimum yükseklik', 12); ns_yaz(ph, 'Maksimum yükseklik', 45); ns_yaz(ph, 'Halka çapı', 14); ns_yaz(ph, 'Parkur yarıçapı', 160)
    ph.wait_for_selector('.fs-mt-map svg circle'); ph.wait_for_timeout(800)
    kontrol('önizlemede 5 halka', ph.locator('.fs-mt-map svg circle').count() >= 5)
    shot(ph, '02-sihirbaz-halkalar.png')
    ph.evaluate("window.__fsWz.goto('invite')"); ph.wait_for_timeout(600)
    kontrol('davet: sağ liste boş, İleri pasif', ph.locator('.fs-mt-list[data-side="right"] li.empty').count() == 1 and ph.locator('.fs-wz-next').is_disabled())
    shot(ph, '03-davet-bos.png')
    ph.locator('.fs-mt-list[data-side="left"] li', has_text='Ayşe Pilot').dblclick()
    ph.locator('.fs-mt-list[data-side="left"] li', has_text='Mehmet Pilot').click()
    ph.locator('.fs-mt-mid button').first.click(); ph.wait_for_timeout(400)
    sag = ph.locator('.fs-mt-list[data-side="right"] li').all_inner_texts()
    kontrol(f'sağda Ayşe + Mehmet: {sag}', any('Ayşe' in t for t in sag) and any('Mehmet' in t for t in sag) and len(sag) == 2)
    shot(ph, '04-davet-edildi.png')
    ph.click('.fs-wz-next'); ph.wait_for_timeout(1200)
    kontrol('son adım: Başlat var, Kaydet / Uç yok', ph.locator('.fs-start').is_visible() and not ph.locator('.fs-wz-save').is_visible() and ph.locator('.fs-wz-fly').count() == 0)
    shot(ph, '05-ozet-baslat.png')
    ph.click('.fs-start')
    ph.wait_for_function("() => /#\\/drone\\/sim\\/match\\/\\d+/.test(location.hash)", timeout=60000)
    mid = int(ph.evaluate("location.hash.match(/match\\/(\\d+)/)[1]"))
    ph.wait_for_selector('.fs-mt-players li[data-status="davetli"]'); ph.wait_for_timeout(1200)
    shot(ph, '06-salon-kurucu-bekleniyor.png')
    # ---------- davetli (Ayşe): zil → salon ----------
    pa.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded')
    pa.wait_for_selector('.inbox-btn'); pa.wait_for_timeout(6000)
    pa.click('.inbox-btn'); pa.wait_for_timeout(800)
    it = pa.locator(f'.alerts-panel a[href="#/drone/sim/match/{mid}"]')
    kontrol('zilde karşılaşma daveti', it.count() == 1)
    shot(pa, '07-davetli-bildirim.png')
    it.first.click()
    pa.wait_for_selector('.fs-mt-players li'); pa.wait_for_timeout(1500)
    kontrol('Ayşe salona geldi', bekle(lambda: next(x for x in mac_durumu(mid)['players'] if x['id'] == ME['ayse'])['status'] == 'geldi', 15))
    ph.wait_for_selector(f'.fs-mt-players li[data-id="{ME["ayse"]}"][data-status="geldi"]', timeout=20000); ph.wait_for_timeout(800)
    shot(pa, '08-salon-davetli.png')
    shot(ph, '09-salon-kurucu-geldi.png')
    # ---------- Mehmet (tarayıcısız) gelir → HAZIRLIK → iki tarayıcı oturum ekranına geçer ----------
    assert sm.post(f'{M_}/{mid}/join').status_code == 200
    ph.wait_for_function("() => /#\\/drone\\/sim\\/\\d+\\?match=/.test(location.hash)", timeout=60000)
    pa.wait_for_function("() => /#\\/drone\\/sim\\/\\d+\\?match=/.test(location.hash)", timeout=60000)
    rt = flightsim_match.MANAGER.get(mid)
    try:
        ph.wait_for_function("() => { const w = document.querySelector('.fs-mt-wait'); return w && !w.hidden; }", timeout=180000, polling=500)
    except Exception as e:   # noqa: BLE001
        hatalar.append(f'hazırlık katmanı görünmedi: {str(e)[:120]}')
    ph.wait_for_timeout(1500)
    shot(ph, '10-hazirlik-bekleme.png')
    rt.ready.add(ME['mehmet'])   # tarayıcısız oyuncu: 3B "hazır" sayılır
    kontrol('geri sayım başladı', bekle(lambda: mac_durumu(mid)['state'] in ('GERI_SAYIM', 'YARIS'), 240, 0.25))
    try:
        ph.wait_for_selector('.fs-mt-wait:not([hidden]) .big, .fs-cd:not([hidden])', timeout=15000); ph.wait_for_timeout(200)
    except Exception:   # noqa: BLE001
        pass
    shot(ph, '11-geri-sayim.png')
    kontrol('yarış başladı', bekle(lambda: mac_durumu(mid)['state'] == 'YARIS', 30, 0.25))
    # ---------- rota pilotları: Ayşe hızlı (kazanır), kurucu yavaş, Mehmet yalnız 2 halka ----------
    d = mac_durumu(mid)
    merkez = {'lat': 39.925, 'lon': 32.837, 'alt': 900}
    for p_ in d['players']:
        ss = flightsim.MANAGER.get(p_['session_id'])
        hiz, kadar = {ME['ayse']: (9.0, None), ME['host']: (7.5, None), ME['mehmet']: (7.0, 2)}[p_['id']]
        rota_pilotu(ss, d['rings'], merkez, hiz=hiz, kadar=kadar)
    ph.wait_for_timeout(9000)
    ghost = ph.evaluate("window.__fsMatch?.layer?.ghostInfo?.() || []")
    kontrol(f'kurucu ekranında 5 halka + 2 diğer oyuncu: {ghost}', ph.evaluate("window.__fsMatch?.layer?.ringCount") == 5 and len(ghost) == 2 and all(g['visible'] for g in ghost))
    print('  halkalar:', ph.evaluate("window.__fsMatch?.layer?.ringInfo?.()"), ph.evaluate("window.__fsMatch?.sim?.cameraState?.()"), flush=True)
    shot(ph, '12-yaris-kurucu.png')
    shot(pa, '13-yaris-davetli.png')
    sonuc = bekle(lambda: (lambda m: m if m['state'] == 'BITTI' else None)(mac_durumu(mid)), 300, 1.0)
    kontrol('karşılaşma bitti, kazanan Ayşe', bool(sonuc) and sonuc.get('winner') == ME['ayse'])
    ph.wait_for_selector('.fs-mt-result:not([hidden]) table', timeout=30000)
    pa.wait_for_selector('.fs-mt-result:not([hidden]) table', timeout=30000); pa.wait_for_timeout(800)
    kontrol('sonuç iki tarafta da', ph.locator('.fs-mt-result tbody tr').count() == 3 and pa.locator('.fs-mt-result tbody tr').count() == 3)
    shot(ph, '14-sonuc-kurucu.png')
    shot(pa, '15-sonuc-davetli.png')
    ph.goto(f'{BASE}/#/drone/sim?tab=matches', wait_until='domcontentloaded')
    ph.wait_for_selector('.fs-mt-table tbody tr', timeout=300000); ph.wait_for_timeout(1200)
    shot(ph, '16-karsilasmalar-sekmesi.png')
    ph.goto(f'{BASE}/#/drone/sim/match/{mid}', wait_until='domcontentloaded')
    ph.wait_for_selector('.fs-mt-res table', timeout=300000); ph.wait_for_timeout(800)
    kontrol('salonda sonuç sırası 1-2-3', ph.locator('.fs-mt-res tbody .rk').all_inner_texts() == ['1', '2', '3'])
    shot(ph, '17-salon-sonuc.png')
    b.close()

server.should_exit = True
time.sleep(1.5)
print('HATALAR:' if hatalar else 'Hata yok', *hatalar[:30], sep='\n  ')
sys.exit(1 if [x for x in hatalar if not x.startswith('KONSOL')] else 0)
