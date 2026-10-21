"""HEPGO Uçuş Simülatörü §27 — KAYITLI SİMÜLASYONLAR: görsel doğrulama + uçtan uca akış (Playwright headless shell; sahte SITL HEPGO_SITL=0).
Uygulama aynı süreçte açılır ve betik bitince kapanır. Görüntüler /tmp/saved-shots/:
  01-07 sihirbaz son adımı (Uç nabız + Kaydet + azami süre/menzil + pilot seçimi) → ad sorma (çakışma uyarısı) → kayıt; üç sütunlu ekran
  (Serbest Uçuş + kayıtlılar · uçuş kartları · özet + dönen 3B model) açık/koyu × masaüstü/tablet/mobil; Düzenle (önceden dolu sihirbaz → güncelle);
  pilot olarak giriş → "Size atandı" → Başlat (özet + Uç) → geri sayım → oturum → kapanışta uçuş kaydı kayıtlı simülasyona bağlı; Sil.
Çalıştırma: ./.venv/bin/python -m tests.saved_shots_hepgo        (SV_ONLY=desktop-light,… alt küme)
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/saved-shots-hepgo-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39650', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='4')
PORT = int(os.environ.get('SHOT_PORT') or 8863)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/saved-shots')
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
ONLY = set(filter(None, os.environ.get('SV_ONLY', '').split(',')))

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
hatalar = []


def oturum(kullanici, sifre):
    r = requests.Session()
    assert r.post(f'{BASE}/api/auth/login', json={'username': kullanici, 'password': sifre}).status_code == 200, kullanici
    r.post(f'{BASE}/api/kvkk/accept-terms', json={})
    r.post(f'{BASE}/api/location/consent', json={'granted': False})   # KVKK konum izni penceresi görüntüyü örtmesin
    return r


s = oturum('demo@firma.com', 'Demo-Sifre-12')
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Test Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
s.post(f'{BASE}/api/drone/centers', json={'name': 'Bedesten Pisti', 'lat': 40.01, 'lon': 32.70, 'alt': 742})
for u, ad, rol in (('pilot@firma.com', 'Ayşe Pilot', auth.PILOT), ('pilot2@firma.com', 'Mehmet Pilot', auth.PILOT), ('lider@firma.com', 'Saha Lideri', auth.FIELD_LEAD)):
    r = s.post(f'{BASE}/api/users', json={'username': u, 'full_name': ad, 'roles': [rol], 'password': 'Ucus-Gizli-77'})
    assert r.status_code == 200, r.text
sp = oturum('pilot@firma.com', 'Ucus-Gizli-77')
ME = {'pilot': sp.get(f'{BASE}/api/auth/me').json()['id']}
S_ = f'{BASE}/api/drone/sim/sessions'
P_ = f'{BASE}/api/drone/sim/presets'


def ucus(ses, body=None, url=S_, sure=3.0, crash=False):
    """Sahte kinematikte kısa uçuş: aç → kalkış → bekle → (çarpışma) → kapat; kapanışta drone_sim_runs satırı."""
    r = ses.post(url, json=body or {})
    assert r.status_code == 201, r.text
    sid = r.json()['id']
    for _ in range(60):
        if ses.get(f'{S_}/{sid}').json().get('state') == 'HAZIR':
            break
        time.sleep(0.2)
    ses.post(f'{S_}/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40}})
    time.sleep(sure)
    if crash:
        ses.post(f'{S_}/{sid}/cmd', json={'name': 'crash'})
        time.sleep(0.5)
    ses.delete(f'{S_}/{sid}')
    return sid


ayar = {'type': 'sabit_kanat', 'center_id': c['id'], 'world': {'mode': 'procedural', 'seed': 4242, 'size_m': 3000, 'time': 'dusk', 'launch': {'method': 'ramp', 'angle_deg': 18}},
        'model': {'id': 'builtin:caymaz'}, 'power': {'max_speed_ms': 45, 'fuel_l': 5, 'fuel_km_per_l': 25, 'elec_cells': 4, 'elec_mah': 10000, 'elec_w': 30},
        'layout': 'elevon', 'camera': 'thermal', 'rec': {'bin': False}}
# serbest uçuşlar (biri çarpışmalı) + bir kayıtlı simülasyon (Ayşe Pilot'a atanmış) ve onunla iki uçuş
ucus(s, {'type': 'multirotor', 'center_id': c['id']}, sure=2.5)
ucus(s, {'type': 'sabit_kanat', 'center_id': c['id'], 'power': {'fuel_l': 2}}, sure=3, crash=True)
ucus(s, {'type': 'hexarotor', 'center_id': c['id']}, sure=2)
k1 = s.post(P_, json={'name': 'Termal keşif — rampa', 'description': 'Akşam, rampadan kalkış; termal kamerayla kuzey sırtı taraması.', 'pilot_id': ME['pilot'], 'settings': ayar}).json()
k2 = s.post(P_, json={'name': 'Kopter askı testi', 'description': 'Merkez üstünde 40 m askı, batarya bütçesi.', 'pilot_id': None,
                      'settings': {'type': 'multirotor', 'center_id': c['id'], 'world': {'mode': 'procedural'}, 'power': {'elec_cells': 6, 'elec_mah': 16000, 'elec_w': 55}}}).json()
assert k1.get('id') and k2.get('id'), (k1, k2)
ucus(sp, url=f"{P_}/{k1['id']}/start", sure=3)
ucus(sp, url=f"{P_}/{k1['id']}/start", sure=2, crash=True)
time.sleep(1.5)
VIEWS = {'desktop': (1440, 900), 'tablet': (900, 1100), 'mobile': (390, 844)}


def shot(pg, ad, full=False):
    pg.screenshot(path=str(OUT / ad), timeout=240000, full_page=full)
    print('  kare', ad, flush=True)


def baglam(b, ses, w=1440, hh=900, mobile=False, scale=1):
    ctx = b.new_context(viewport={'width': w, 'height': hh}, locale='tr-TR', device_scale_factor=scale, is_mobile=mobile, has_touch=mobile)
    ctx.add_cookies([{'name': auth.COOKIE, 'value': ses.cookies.get(auth.COOKIE), 'url': BASE}])
    pg = ctx.new_page()
    pg.set_default_timeout(60000)
    pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
    pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
    return ctx, pg


def tema(pg, theme):
    pg.evaluate(f"document.documentElement.dataset.theme = {theme!r} === 'dark' ? 'dark' : ''; if ({theme!r} !== 'dark') delete document.documentElement.dataset.theme")


def kayitli_ekran(pg, theme, sel=None):
    pg.goto(f'{BASE}/#/drone/sim?tab=saved' + (f'&preset={sel}' if sel else ''), wait_until='domcontentloaded')
    pg.wait_for_selector('.fs-sv .fs-sv-card[data-preset="free"]', timeout=60000)
    tema(pg, theme)
    pg.wait_for_selector('.fs-sv-runs .fs-sv-run, .fs-sv-runs .fs-sv-empty', timeout=30000)
    pg.wait_for_timeout(2500)   # dönen model (stüdyo bağlamı) ilk kare


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        # ---------- 1) sihirbaz son adımı: Uç (nabız) + Kaydet + azami süre/menzil + pilot ----------
        if not ONLY or 'wizard' in ONLY:
            for theme in ('light', 'dark'):
                ctx, pg = baglam(b, s)
                pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
                pg.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=60000)
                tema(pg, theme)
                pg.locator('.fs-type', has_text='Sabit Kanat').first.click(); pg.wait_for_timeout(1200)
                pg.evaluate("window.__fsWz.goto('summary')"); pg.wait_for_timeout(1200)
                fly = pg.locator('.fs-start.fs-wz-fly')
                if not fly.is_visible() or 'Uç' not in fly.inner_text():
                    hatalar.append('Uç düğmesi yok')
                anim = pg.evaluate("getComputedStyle(document.querySelector('.fs-wz-fly')).animationName")
                if 'fsFlyPulse' not in anim:
                    hatalar.append(f'Uç nabız animasyonu yok: {anim}')
                if not pg.locator('.fs-wz-save').is_visible():
                    hatalar.append('Kaydet düğmesi yok')
                bud = pg.locator('.fs-bud').inner_text()
                if '2 sa 11 dk' not in bud or '193 km' not in bud or 'Sınırlayan' not in bud:
                    hatalar.append(f'özet bütçe: {bud!r}')
                pg.locator('.fs-wz-assign select').select_option(str(ME['pilot'])); pg.wait_for_timeout(300)
                shot(pg, f'01-{theme}-sihirbaz-son-adim.png')
                pg.evaluate("document.querySelector('.fs-wizard-modal .modal-body').scrollTop = 1e6"); pg.wait_for_timeout(300)
                shot(pg, f'01-{theme}-sihirbaz-son-adim-alt.png')
                # ad sorma: çakışan ad → uyarı + Kaydet pasif
                pg.locator('.fs-wz-save').click()
                pg.wait_for_selector('.fs-name-dlg input[data-f="name"]')
                pg.locator('.fs-name-dlg input[data-f="name"]').fill('  termal KEŞİF — rampa ')
                pg.wait_for_timeout(200)
                if not pg.locator('.fs-name-ok').is_disabled():
                    hatalar.append('çakışan adda Kaydet etkin')
                shot(pg, f'02-{theme}-ad-cakisma.png')
                ad = 'Gece devriyesi' if theme == 'light' else 'Gece devriyesi (koyu)'
                pg.locator('.fs-name-dlg input[data-f="name"]').fill(ad)
                pg.locator('.fs-name-dlg textarea').fill('Pist yönünde 2 km açılıp dönüş; termal.')
                pg.wait_for_timeout(200)
                shot(pg, f'02-{theme}-ad-sorma.png')
                pg.keyboard.press('Escape'); pg.wait_for_timeout(300)   # yalnız ad penceresi kapanır
                if not pg.locator('.fs-wizard-modal').is_visible():
                    hatalar.append('Esc sihirbazı da kapattı')
                pg.locator('.fs-wz-save').click()
                pg.wait_for_selector('.fs-name-dlg input[data-f="name"]')
                pg.locator('.fs-name-dlg input[data-f="name"]').fill(ad)
                pg.locator('.fs-name-ok').click()
                pg.wait_for_selector('.fs-wizard-modal', state='detached', timeout=120000)
                pg.wait_for_timeout(2500)
                on = pg.locator('.fs-sv-card.on[data-preset]').get_attribute('data-preset')
                if on in (None, 'free'):
                    hatalar.append(f'kaydedilen seçili gelmedi ({on})')
                shot(pg, f'03-{theme}-kaydedildi.png')
                ctx.close()
            # mobil: son adım altbilgisi (Uç + Kaydet) ve azami süre/menzil kutusu
            ctx, pg = baglam(b, s, 390, 844, mobile=True, scale=2)
            pg.goto(f'{BASE}/#/drone/sim?new=1', wait_until='domcontentloaded')
            pg.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=60000)
            pg.locator('.fs-type', has_text='Sabit Kanat').first.click(); pg.wait_for_timeout(1200)
            pg.evaluate("window.__fsWz.goto('summary')"); pg.wait_for_timeout(1500)
            shot(pg, '01-light-mobil-son-adim.png')
            ctx.close()
            # zil: atanan pilota "Size bir simülasyon atandı"
            zil = sp.get(f'{BASE}/api/notifications').json()
            zil = zil.get('items', zil) if isinstance(zil, dict) else zil
            if not any(n.get('key') == 'sim-assigned' for n in zil):
                hatalar.append(f"pilot zilinde sim-assigned yok: {[n.get('key') for n in zil]}")
        # ---------- 2) üç sütunlu ekran: açık/koyu × masaüstü/tablet/mobil ----------
        for theme in ('light', 'dark'):
            for vk, (w, hh) in VIEWS.items():
                if ONLY and f'{vk}-{theme}' not in ONLY:
                    continue
                ctx, pg = baglam(b, s, w, hh, mobile=vk == 'mobile', scale=2 if vk == 'mobile' else 1)
                kayitli_ekran(pg, theme, 'free')
                n_run = pg.locator('.fs-sv-runs .fs-sv-run').count()
                if n_run != 3:
                    hatalar.append(f'serbest uçuş kartı {n_run} (3 beklenirdi)')
                shot(pg, f'04-{theme}-{vk}-serbest.png', full=vk != 'desktop')
                pg.locator(f'.fs-sv-card[data-preset="{k1["id"]}"]').click(); pg.wait_for_timeout(2500)
                if pg.locator('.fs-sv-runs .fs-sv-run').count() != 2:
                    hatalar.append(f'kayıtlı uçuş kartı {pg.locator(".fs-sv-runs .fs-sv-run").count()} (2 beklenirdi)')
                shot(pg, f'05-{theme}-{vk}-kayitli.png', full=vk != 'desktop')
                pg.locator('.fs-sv-runs .fs-sv-run').first.click(); pg.wait_for_timeout(2500)
                facts = pg.locator('.fs-sv-facts').inner_text()
                for kel in ('Süre', 'Mesafe', 'Sonuç', 'Çarpışma'):
                    if kel.upper() not in facts.upper():
                        hatalar.append(f'özet karosu yok: {kel}')
                dolu = pg.evaluate("(() => { const c = document.querySelector('.fs-sv-stage canvas'); const g = c.getContext('2d'); const d = g.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4 * 97) if (d[i] + d[i + 1] + d[i + 2] > 60) n++; return n; })()")
                if dolu < 20:
                    hatalar.append(f'{theme}-{vk}: dönen model çizilmedi ({dolu})')
                shot(pg, f'06-{theme}-{vk}-ucus-ozeti.png', full=vk != 'desktop')
                ctx.close()
        # ---------- 3) Düzenle: sihirbaz kayıtlı ayarlarla açılır → Kaydet (güncelle) ----------
        ctx, pg = baglam(b, s)
        kayitli_ekran(pg, 'light', k1['id'])
        pg.locator(f'.fs-sv-card[data-preset="{k1["id"]}"] [data-act="edit"]').click()
        pg.wait_for_selector('.fs-wz .fs-types .fs-type', timeout=60000); pg.wait_for_timeout(2500)
        st = pg.evaluate('window.__fsWz.steps')
        if 'launch' not in st:
            hatalar.append(f'düzenle: sabit kanat adımları yok {st}')
        on_tip = pg.locator('.fs-types .fs-type.on').inner_text()
        if 'Sabit Kanat' not in on_tip:
            hatalar.append(f'düzenle: tip {on_tip!r}')
        pg.evaluate("window.__fsWz.goto('launch')"); pg.wait_for_timeout(800)
        if 'on' not in (pg.locator('.fs-launch[data-launch="ramp"]').get_attribute('class') or ''):
            hatalar.append('düzenle: rampa seçili değil')
        pg.evaluate("window.__fsWz.goto('camera')"); pg.wait_for_timeout(500)
        shot(pg, '07-duzenle-kamera.png')
        pg.evaluate("window.__fsWz.goto('summary')"); pg.wait_for_timeout(1200)
        if pg.locator('.fs-start').is_visible():
            hatalar.append('düzenlemede Uç görünür')
        if pg.locator('.fs-wz-assign select').input_value() != str(ME['pilot']):
            hatalar.append('düzenle: pilot seçili değil')
        shot(pg, '07-duzenle-ozet.png')
        pg.locator('.fs-wz-save').click()
        pg.wait_for_selector('.fs-name-dlg input[data-f="name"]')
        if pg.locator('.fs-name-dlg input[data-f="name"]').input_value() != k1['name'] or pg.locator('.fs-name-ok').is_disabled():
            hatalar.append('düzenle: ad önceden dolu değil ya da kendi adı çakışma sayıldı')
        istekler = []
        pg.on('response', lambda r: istekler.append((r.status, r.url, r.text()[:300])) if '/presets' in r.url and r.request.method in ('PUT', 'POST') else None)
        pg.locator('.fs-name-ok').click()
        try:   # swiftshader altında sihirbaz önizlemesi ana iş parçacığını uzun süre meşgul edebilir
            pg.wait_for_selector('.fs-wizard-modal', state='detached', timeout=120000)
        except Exception:
            shot(pg, 'hata-duzenle.png')
            print('  düzenle istekleri:', istekler, pg.evaluate("[...document.querySelectorAll('.toast')].map(t => t.textContent)"), flush=True)
            raise
        g = s.get(f"{P_}/{k1['id']}").json()
        if g['settings'].get('camera') != 'thermal' or g['settings']['world'].get('launch', {}).get('method') != 'ramp' or g['pilot_id'] != ME['pilot']:
            hatalar.append(f"düzenle sonrası ayarlar bozuldu: {g['settings']} pilot {g['pilot_id']}")
        ctx.close()
        # ---------- 4) pilot olarak: "Size atandı" → Başlat (özet + Uç) → geri sayım → oturum → kayıt bağlı ----------
        ctx, pg = baglam(b, sp)
        kayitli_ekran(pg, 'light', k1['id'])
        if not pg.locator(f'.fs-sv-card[data-preset="{k1["id"]}"] .fs-sv-assigned').is_visible():
            hatalar.append('pilot: "Size atandı" rozeti yok')
        if not pg.locator(f'.fs-sv-card[data-preset="{k2["id"]}"] [data-act="start"]').is_disabled():
            hatalar.append('pilot: başkasının (atanmamış) kaydında Başlat etkin')
        if pg.locator(f'.fs-sv-card[data-preset="{k1["id"]}"] [data-act="edit"]').count():
            hatalar.append('pilot: Düzenle görünür')
        shot(pg, '08-pilot-kayitli.png')
        pg.locator(f'.fs-sv-card[data-preset="{k1["id"]}"] [data-act="start"]').click()
        pg.wait_for_selector('.fs-wz-quick .fs-wz-quick-h', timeout=60000); pg.wait_for_timeout(2000)
        if pg.locator('.fs-wz-top').is_visible() or pg.locator('.fs-wz-save').is_visible() or pg.locator('.fs-wz-edit').count():
            hatalar.append('hızlı başlat: şerit/Kaydet/Düzenle görünür')
        pg.locator('.fs-rec-opts input[type=checkbox]').first.uncheck()   # ekran kaydı kapalı (başsız tarayıcıda paylaşım izni yok)
        shot(pg, '09-pilot-baslat-ozet.png')
        bodies = []
        pg.on('request', lambda r: bodies.append(r.url) if r.method == 'POST' and '/presets/' in r.url and r.url.endswith('/start') else None)
        pg.locator('.fs-start').click()
        pg.wait_for_selector('.fs-cd .fs-cd-n', timeout=10000); pg.wait_for_timeout(300)
        shot(pg, '10-geri-sayim.png')
        pg.wait_for_function("() => /#\\/drone\\/sim\\/\\d+/.test(location.hash)", timeout=120000)
        pg.wait_for_timeout(2500)
        shot(pg, '11-pilot-oturum.png')
        if not bodies:
            hatalar.append('POST /presets/{id}/start yok')
        sid = int(pg.evaluate("location.hash.match(/sim\\/(\\d+)/)[1]"))
        sp.delete(f'{S_}/{sid}'); time.sleep(2.5)
        rs = s.get(f"{BASE}/api/drone/sim/runs", params={'preset': k1['id']}).json()
        if rs['total'] != 3 or rs['items'][0]['session_id'] != sid:
            hatalar.append(f"pilotun uçuşu kayda bağlanmadı: {rs['total']} {[x['session_id'] for x in rs['items']]} ({sid})")
        ctx.close()
        # ---------- 5) Sil (tasarlayan) ----------
        ctx, pg = baglam(b, s)
        kayitli_ekran(pg, 'light', k2['id'])
        pg.locator(f'.fs-sv-card[data-preset="{k2["id"]}"] [data-act="del"]').click()
        pg.locator('.modal-foot .btn.danger').click(); pg.wait_for_timeout(1500)
        if pg.locator(f'.fs-sv-card[data-preset="{k2["id"]}"]').count():
            hatalar.append('silinen kayıt listede')
        shot(pg, '12-silindi.png')
        ctx.close()
        b.close()
finally:
    server.should_exit = True
    time.sleep(1)
print('HATALAR:' if hatalar else 'hata yok', *hatalar, sep='\n  ')
