"""HEPGO Uçuş Simülatörü §41 — karşılaşmada İT DALAŞI: görsel doğrulama (iki tarayıcı bağlamı: kurucu = kovalayan, davetli = kaçan; sahte SITL;
uygulama aynı süreçte). Görüntüler /tmp/dogfight-shots/df-*.png: 01 tür seçimi + kurallar şeması · 02 özet · 03 salon · 04 kovalayan HUD'u (rakip
işaretçisi, angajman halkası, KONİ İÇİNDE) · 05 kaçanda KİLİTLENİYOR! · 06-07 sonuç (iki taraf) · 08 salonda sonuç + Rövanş · 09 Karşılaşmalar (tür).
Pilotlar tests/match_bot.it_pilotu ile sahte kinematikte uçar (görüntü sırasında tutma süresi geçici büyütülür, sonra 5 sn → ANGAJE).
Çalıştırma: ./.venv/bin/python -m tests.dogfight_shots
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/dogfight-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39950', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='2', SIM_MATCH_MAX_SESSIONS='6')
PORT = int(os.environ.get('SHOT_PORT') or 8879)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/dogfight-shots')
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
from tests.match_bot import it_pilotu  # noqa: E402

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
    # ---------- kurucu: Yeni Karşılaşma → Tür ve kurallar: İt dalaşı ----------
    ph.goto(f'{BASE}/#/drone/sim?tab=matches', wait_until='domcontentloaded')
    ph.wait_for_selector('.fs-new-match'); ph.wait_for_timeout(1500)
    ph.click('.fs-new-match')
    ph.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=90000); ph.wait_for_timeout(2500)
    ph.evaluate("window.__fsWz.goto('rings')"); ph.wait_for_timeout(500)
    ph.click('.fs-df-kind[data-kind="dogfight"]'); ph.wait_for_timeout(400)
    ns_yaz(ph, 'Angajman menzili', 150); ns_yaz(ph, 'Gereken kesintisiz süre', 5); ns_yaz(ph, 'Başlangıç irtifası', 30)
    ph.select_option('.fs-mt-kindwrap select', 'host_chaser'); ph.wait_for_timeout(500)
    kontrol('it dalaşı şeması', ph.locator('.fs-df-map svg path').count() >= 1)
    shot(ph, 'df-01-tur-secimi-hepgo.png')
    ph.evaluate("window.__fsWz.goto('invite')"); ph.wait_for_timeout(600)
    ph.locator('.fs-mt-list[data-side="left"] li', has_text='Ayşe Pilot').dblclick()
    ph.locator('.fs-mt-list[data-side="left"] li', has_text='Mehmet Pilot').dblclick(); ph.wait_for_timeout(300)
    sag = ph.locator('.fs-mt-list[data-side="right"] li').all_inner_texts()
    kontrol(f'it dalaşında tek davetli: {sag}', len(sag) == 1)
    ph.click('.fs-wz-next'); ph.wait_for_timeout(1200)
    shot(ph, 'df-02-ozet.png')
    ph.click('.fs-start')
    ph.wait_for_function("() => /#\\/drone\\/sim\\/match\\/\\d+/.test(location.hash)", timeout=60000)
    mid = int(ph.evaluate("location.hash.match(/match\\/(\\d+)/)[1]"))
    ph.wait_for_selector('.fs-mt-players li'); ph.wait_for_timeout(1500)
    shot(ph, 'df-03-salon.png')
    pa.goto(f'{BASE}/#/drone/sim/match/{mid}', wait_until='domcontentloaded')
    ph.wait_for_function("() => /#\\/drone\\/sim\\/\\d+\\?match=/.test(location.hash)", timeout=90000)
    pa.wait_for_function("() => /#\\/drone\\/sim\\/\\d+\\?match=/.test(location.hash)", timeout=90000)
    d = mac_durumu(mid)
    roles = {x['id']: x['role'] for x in d['players']}
    kontrol(f'roller: {roles}', roles.get(ME['host']) == 'chaser' and roles.get(ME['ayse']) == 'evader')
    kontrol('yarış başladı', bekle(lambda: mac_durumu(mid)['state'] == 'YARIS', 600, 0.5))
    rt = flightsim_match.MANAGER.get(mid)
    d = mac_durumu(mid)
    merkez = {'lat': 39.925, 'lon': 32.837, 'alt': 900}
    sid = {x['id']: x['session_id'] for x in d['players']}
    P = core.it_baslangiclari(d['rings_cfg'], d['settings']['type'])
    rt.k.it.a['hold_s'] = 120.0   # görüntü için angajman tamamlanmasın (yalnız test aracı)
    kac = it_pilotu(flightsim.MANAGER.get(sid[ME['ayse']]), merkez, P['evader'][2], P['evader'][:2], hiz=2.0, alt=30.0)
    it_pilotu(flightsim.MANAGER.get(sid[ME['host']]), merkez, P['evader'][2], P['chaser'][:2], gecikme_m=90.0, takip=kac)
    kontrol('koni içinde', bekle(lambda: (rt.k.it_durum() or {}).get('in_cone') and (rt.k.it_durum() or {}).get('hold_s', 0) > 6, 120, 0.5))
    ph.evaluate("window.__fsSim && window.__fsSim.setCamera('pilot')"); pa.evaluate("window.__fsSim && window.__fsSim.setCamera('follow')")
    ph.wait_for_timeout(4000)
    print('  HUD kovalayan:', ph.evaluate("window.__fsDogfight?.state()"), flush=True)
    shot(ph, 'df-04-kovalayan-hud.png')
    print('  HUD kaçan:', pa.evaluate("window.__fsDogfight?.state()"), flush=True)
    kontrol('kaçanda KİLİTLENİYOR', bool(pa.evaluate("window.__fsDogfight?.state()?.alert")))
    shot(pa, 'df-05-kacan-uyari.png')
    rt.k.it.a['hold_s'] = 5.0
    sonuc = bekle(lambda: (lambda m: m if m['state'] == 'BITTI' else None)(mac_durumu(mid)), 120, 0.5)
    kontrol(f"bitti, kovalayan kazandı: {sonuc and sonuc.get('reason')}", bool(sonuc) and sonuc.get('winner') == ME['host'] and sonuc.get('reason') == 'angaje')
    ph.wait_for_selector('.fs-mt-result:not([hidden]) table', timeout=60000)
    pa.wait_for_selector('.fs-mt-result:not([hidden]) table', timeout=60000); pa.wait_for_timeout(800)
    shot(ph, 'df-06-sonuc-kovalayan.png')
    shot(pa, 'df-07-sonuc-kacan.png')
    ph.goto(f'{BASE}/#/drone/sim/match/{mid}', wait_until='domcontentloaded')
    ph.wait_for_selector('.fs-mt-res table', timeout=300000); ph.wait_for_timeout(800)
    kontrol('salonda rövanş düğmesi', ph.locator('button', has_text='Rövanş').count() == 1)
    shot(ph, 'df-08-salon-sonuc-rovans.png')
    ph.goto(f'{BASE}/#/drone/sim?tab=matches', wait_until='domcontentloaded')
    ph.wait_for_selector('.fs-mt-table tbody tr', timeout=300000); ph.wait_for_timeout(1200)
    shot(ph, 'df-09-karsilasmalar.png')
    b.close()

server.should_exit = True
time.sleep(1.5)
print('HATALAR:' if hatalar else 'Hata yok', *hatalar[:30], sep='\n  ')
sys.exit(1 if [x for x in hatalar if not x.startswith('KONSOL')] else 0)
