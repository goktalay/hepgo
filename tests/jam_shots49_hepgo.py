"""HEPGO Uçuş Simülatörü — §49 KARIŞTIRMA EKLERİ görsel doğrulaması (Playwright headless shell + SwiftShader). Uygulama aynı süreçte; sahte kinematik
(HEPGO_SITL=0: göstergeler + kumanda iletmeme + komut reddi + bölge) ya da JAM_REAL=1 + HEPGO_SITL_DIR → gerçek SITL (konum kaybı tepkisi, hayalet).
Kareler /tmp/jam-shots/49-*: panel (bağlantı karıştırma, karıştırıcı bölgesi, konum kaybında otopilot), taslak bölge + küçük harita (tıklayarak merkez),
bölge dışında bekleme bandı, bölge içinde KUMANDA YOK / TELEMETRİ YOK (göstergeler son değerde + rozet), dar ekran, özet raporu;
gerçek SITL'de ayrıca: tam GPS karıştırma → ALT_HOLD (gaz ortada), GPS aldatma → otopilot konumu işaretçisi (3B + küçük harita), kumanda kaybı → aracın kendi tepkisi.
Çalıştırma: ./.venv/bin/python -m tests.jam_shots49_hepgo
"""
import asyncio
import math
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
REAL = os.environ.get('JAM_REAL') == '1'
DATA = '/tmp/jam-shots49-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='1' if REAL else '0', SIM_UDP_BASE='39870', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
PORT = int(os.environ.get('SHOT_PORT') or 8883)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/jam-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

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


OLAY = []
izle_dur = []


def arac(ad):
    t = ss.tele
    print(f"  [araç] {ad}: kip {t.get('mode')} arm {t.get('armed')} irtifa {round(t.get('alt_rel') or 0, 1)} konum {t.get('lat')}, {t.get('lon')} | olaylar: {OLAY[-(60 if os.environ.get('JAM_TESHIS') else 8):]}", flush=True)
    if os.environ.get('JAM_TESHIS'):
        print('\n'.join('      ' + o for o in OLAY), flush=True)
    del OLAY[:]


def shot(pg, ad, clip=None):
    pg.screenshot(path=str(OUT / ad), clip=clip)
    print('  kare', ad, flush=True)


def cmd(sid, name, params=None):
    r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': name, 'params': params or {}})
    if r.status_code != 200:
        hatalar.append(f'cmd {name} {r.status_code} {r.text[:200]}')
    return r


def tasma(pg, sel):
    """Öğe görünüm alanının dışına taşıyor mu (px)."""
    return pg.evaluate("""sel => { const r = document.querySelector(sel).getBoundingClientRect();
      return { l: Math.round(r.left), t: Math.round(r.top), r: Math.round(innerWidth - r.right), b: Math.round(innerHeight - r.bottom), w: Math.round(r.width), h: Math.round(r.height) }; }""", sel)


def doldur(pg, sel, v):
    el = pg.locator(sel)
    el.fill(str(v)); el.dispatch_event('change')

def js(pg, kod):
    return pg.evaluate(kod)


def durum(pg):
    return js(pg, """({st: document.querySelector('.fs-jam').dataset.state, band: document.querySelector('.fs-jam-banner').hidden ? null : document.querySelector('.fs-jam-banner').innerText.replace(/\\n/g, ' | '),
      bcls: document.querySelector('.fs-jam-banner').className, map: !document.querySelector('.fs-jam-map').hidden, pick: document.querySelector('.fs-jam-map').classList.contains('fs-jam-pick'),
      lg: document.querySelector('.fs-jam-map footer').innerText.replace(/\\n/g, ' | '), olc: document.querySelector('.fs-jam-map header span').innerText,
      rozet: !document.querySelector('.fs-jam-tlmb').hidden, lost: document.querySelector('.fs-stage').classList.contains('fs-tlm-lost'), btn: document.querySelector('.fs-jam-btn').innerText})""")


def hud(pg):
    return js(pg, "[...document.querySelectorAll('.fs-hud > *:not(.fs-jam-tlmb)')].map(e => e.innerText).filter(x => !/^net:/.test(x.trim())).join(' # ')")   # ağ istatistiği satırı telemetri değildir


def harita(pg, ad):
    mb = pg.locator('.fs-jam-map').bounding_box()
    shot(pg, ad, {'x': max(0, mb['x'] - 10), 'y': max(0, mb['y'] - 10), 'width': mb['width'] + 20, 'height': mb['height'] + 20})


def panel(pg, ad):
    pb = pg.locator('.fs-jam-pop').bounding_box()
    shot(pg, ad, {'x': max(0, pb['x'] - 16), 'y': max(0, pb['y'] - 16), 'width': pb['width'] + 32, 'height': min(js(pg, 'innerHeight') - max(0, pb['y'] - 16), pb['height'] + 90)})


def ac(pg):
    if js(pg, "document.querySelector('.fs-jam-pop').hidden"):
        pg.locator('.fs-jam-btn').click()
    pg.wait_for_selector('.fs-jam-pop:not([hidden])', timeout=20000); pg.wait_for_timeout(400)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1600, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        if REAL:   # tarayıcının sanal kumandası kapalı: headless tarayıcı saniyelerce takılabiliyor, 20 Hz RC akışı kesilince ArduPilot ~3 sn'de
            # SITL'in iç RC'sine döner (kip anahtarı → STABILIZE, gaz en altta) ve araç düşer. Aynı akışı aşağıda betik kararlı biçimde gönderir.
            ctx.add_init_script("try { localStorage.setItem('caymaz.fs.rc.on', '0'); } catch (e) {}")
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        body = {'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False},
                'world': {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'time': 'day', 'wind_ms': 4 if REAL else 0, 'wind_dir': 270, 'tree_density': 0.3, 'building_count': 20}}
        r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
        assert r.status_code == 201, r.text
        sid = r.json()['id']
        print('  oturum jam:', r.json().get('jam'), flush=True)
        ss = flightsim.MANAGER.sessions[sid]
        olay0, t_olay = ss._olay, time.time()
        def _olay(text, severity=6):   # olay günlüğü: araç tepkilerinin (failsafe, kip değişimi, çarpışma) dökümü
            OLAY.append(f'{time.time() - t_olay:5.0f}s {text}'); return olay0(text, severity)
        ss._olay = _olay
        if REAL:   # varsayılan kullanıcı yolu: sanal kumanda açık, çubuklar ortada, gaz çubuğuna dokunulmamış (gaz kanalı 0 = dokunma)
            def _rc_akis():
                while ss.state != 'KAPANDI' and not izle_dur:
                    if ss.loop is not None:
                        try:
                            asyncio.run_coroutine_threadsafe(ss.rc([1500, 1500, 0, 1500, 1500, 0, 0, 0]), ss.loop)
                        except Exception:   # noqa: BLE001
                            pass
                    time.sleep(0.05)
            threading.Thread(target=_rc_akis, daemon=True).start()
        if os.environ.get('JAM_TESHIS'):   # teşhis: araca giden MAVLink mesajları (kalp atışı dışında) ve komutlar
            gonder0, komut0 = ss._gonder, ss.komut
            def _gonder(msg):
                ad = msg.get_type()
                if ad not in ('HEARTBEAT', 'TIMESYNC', 'SYSTEM_TIME', 'REQUEST_DATA_STREAM', 'PARAM_REQUEST_READ', 'PARAM_REQUEST_LIST'):
                    d = msg.to_dict(); d.pop('mavpackettype', None)
                    OLAY.append(f'{time.time() - t_olay:5.0f}s → {ad} {str(d)[:150]}')
                return gonder0(msg)
            async def _komut(name, params, kaynak=None):
                if name != 'rc':
                    OLAY.append(f'{time.time() - t_olay:5.0f}s cmd {name} {str(params)[:80]} [{kaynak}]')
                return await komut0(name, params, kaynak)
            ss._gonder, ss.komut = _gonder, _komut
            def _izle():
                son = None
                while ss.state != 'KAPANDI' and not izle_dur:
                    t = ss.tele; simdi = (t.get('mode'), t.get('armed'))
                    if simdi != son:
                        OLAY.append(f"{time.time() - t_olay:5.0f}s KİP {simdi} irtifa {round(t.get('alt_rel') or 0, 1)} gaz {t.get('throttle')} rc {(t.get('rc') or [])[:5]}"); son = simdi
                    time.sleep(0.2)
            threading.Thread(target=_izle, daemon=True).start()
        bekle(lambda: ss.state == 'HAZIR' and (ss.sahte is not None or ss._heartbeat_alindi), 180, 'HAZIR')
        pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-bar .fs-jam', timeout=240000)
        pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera', timeout=240000)
        js(pg, "[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
        js(pg, "localStorage.removeItem('fs.jam')")
        pg.wait_for_timeout(6000)   # giriş sekansı
        if REAL:   # gerçek SITL: EKF / GPS hazır olmadan ARM olmaz — hazır olana dek bekle, kalkana dek yinele
            bekle(lambda: ss.tele.get('gps_fix', 0) >= 3 and ss.tele.get('home'), 150, 'GPS / ev')
            time.sleep(12)
            for _ in range(12):
                cmd(sid, 'mode', {'mode': 'GUIDED'}); time.sleep(1)
                cmd(sid, 'arm'); time.sleep(2)
                cmd(sid, 'takeoff', {'alt': 30}); time.sleep(4)
                if (ss.tele.get('alt_rel') or 0) > 2 and ss.tele.get('mode') == 'GUIDED':
                    break
            hatalar[:] = [h for h in hatalar if not h.startswith('cmd ')]   # hazır olmadan reddedilen ARM denemeleri hata değil
        else:
            cmd(sid, 'takeoff', {'alt': 60})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > (45 if not REAL else 26), 150, 'kalkış')
        arac('kalkış sonrası')
        pg.wait_for_timeout(2500)
        # ---- panel: yeni bölümler ----
        ac(pg)
        print('  panel:', tasma(pg, '.fs-jam-pop'), 'gövde kaydırma:', js(pg, "(b => ({sh: b.scrollHeight, ch: b.clientHeight}))(document.querySelector('.fs-jam-body'))"),
              'fs:', js(pg, "!document.querySelector('.fs-jam-fs').closest('.fs-jam-sec').hidden"), 'harita:', durum(pg)['map'], flush=True)
        shot(pg, '49-00-panel.png'); panel(pg, '49-01-panel-zoom.png')
        # ---- taslak bölge + küçük harita ----
        pg.locator('.fs-jam-zone').check(); pg.wait_for_timeout(700)
        d = durum(pg)
        print('  taslak:', d, 'merkez:', js(pg, "document.querySelector('.fs-jam-zc').value"), 'gövde:', js(pg, "(b => ({sh: b.scrollHeight, ch: b.clientHeight}))(document.querySelector('.fs-jam-body'))"), tasma(pg, '.fs-jam-pop'), flush=True)
        if not (d['map'] and d['pick']):
            hatalar.append(f'taslak bölgede küçük harita yok: {d}')
        print('  harita düzeni:', js(pg, "(m => { const c = getComputedStyle(m), h = m.querySelector('header'), k = m.querySelector('canvas'), r = e => { const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]; }; return {disp: c.display, pos: c.position, kutu: r(m), bas: r(h), basDisp: getComputedStyle(h).display, basPos: getComputedStyle(h).position, cv: r(k), cvPos: getComputedStyle(k).position, cvDisp: getComputedStyle(k).display}; })(document.querySelector('.fs-jam-map'))"), flush=True)
        if js(pg, "getComputedStyle(document.querySelector('.fs-jam-map')).display") != 'block':
            hatalar.append('küçük harita blok düzeninde değil (genel bir sınıfla çakışma)')
        shot(pg, '49-02-draft.png'); harita(pg, '49-03-draft-map.png')
        js(pg, "document.querySelector('.fs-jam-body').scrollTop = 9999"); pg.wait_for_timeout(200)
        panel(pg, '49-04-panel-zone.png')
        # tıklayarak merkez: haritanın sol alt çeyreği
        z0 = js(pg, "document.querySelector('.fs-jam-zc').value")
        cb = pg.locator('.fs-jam-map canvas').bounding_box()
        pg.mouse.click(cb['x'] + cb['width'] * 0.3, cb['y'] + cb['height'] * 0.72); pg.wait_for_timeout(500)
        z1 = js(pg, "document.querySelector('.fs-jam-zc').value")
        print('  harita tıklaması:', z0, '→', z1, 'panel açık:', js(pg, "!document.querySelector('.fs-jam-pop').hidden"), flush=True)
        if z0 == z1 or js(pg, "document.querySelector('.fs-jam-pop').hidden"):
            hatalar.append('harita tıklaması merkezi taşımadı / paneli kapattı')
        harita(pg, '49-05-click-map.png')
        # hatalı merkez metni → uyarı, eski değer
        doldur(pg, '.fs-jam-zc', 'abc'); pg.wait_for_timeout(300)
        if js(pg, "document.querySelector('.fs-jam-zc').value") != z1:
            hatalar.append('hatalı merkez metni geri alınmadı')
        # yarıçap 200, aracın önüne; kumanda + telemetri; Başlat → bölge dışında bekleme
        doldur(pg, '.fs-jam-zr', 200)
        pg.locator('.fs-jam-zahead').click(); pg.wait_for_timeout(300)
        print('  aracın önüne:', js(pg, "document.querySelector('.fs-jam-zc').value"), flush=True)
        if not REAL:   # sahte araç lat0/lon0 çevresinde 150 m daire çizer: bölge dairenin doğusunda (merkez 250 m), araç batıda ve yavaş
            k = ss.sahte
            k.HIZ, k.aci = 2.0, -math.pi / 2
            doldur(pg, '.fs-jam-zc', f"{k.lat0:.5f}, {k.lon0 + 250.0 / (111320.0 * math.cos(math.radians(k.lat0))):.5f}"); pg.wait_for_timeout(300)
        if not REAL:   # gerçek SITL'de kumanda kaybı aracı RTL'ye alıp bölgeden çıkarır: orada yalnız telemetri (kumanda ayrı adımda)
            pg.locator('.fs-jam-rc').check()
        pg.locator('.fs-jam-tlm').check()
        if not REAL:
            pg.locator('.fs-jam-seg:not(.fs-jam-fs) button[data-v=off]').click()
        doldur(pg, '.fs-jam-dur', 0)
        pg.wait_for_timeout(300)
        js(pg, "document.querySelector('.fs-jam-body').scrollTop = 0")
        panel(pg, '49-06-panel-filled.png')
        arac('Başlat öncesi')
        if os.environ.get('JAM_TESHIS'):
            raise RuntimeError('teşhis koşusu: Başlat öncesinde duruldu')
        t0 = time.time()
        pg.locator('.fs-jam-start').click()
        bekle(lambda: ss.jam.on, 8, 'karıştırma açılışı')
        t1 = time.time()
        pg.wait_for_function("document.querySelector('.fs-jam').dataset.state !== 'off'", timeout=20000)
        print(f'  Başlat → sunucu {t1 - t0:.1f} sn, arayüz {time.time() - t0:.1f} sn', flush=True)
        pg.wait_for_timeout(1500)
        sd = ss.jam.durum()
        print('  sunucu:', {k: sd.get(k) for k in ('on', 'active', 'gps', 'rc', 'tlm', 'zone', 'fs', 'thr_mid', 'sim')}, flush=True)
        d = durum(pg)
        print('  bekleme:', d, flush=True)
        if d['st'] != 'wait' or 'wait' not in d['bcls'] or d['rozet']:
            hatalar.append(f'bölge dışında bekleme durumu yanlış: {d}')
        shot(pg, '49-07-wait.png'); harita(pg, '49-08-wait-map.png')
        h0 = hud(pg)
        r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'mode', 'params': {'mode': 'GUIDED'}})
        print('  dışarıda kip komutu:', r.status_code, flush=True)
        if r.status_code != 200:
            hatalar.append(f'bölge dışında komut reddedildi: {r.status_code} {r.text[:120]}')
        # ---- bölgeye giriş ----
        z = sd['zone']
        if REAL:
            cmd(sid, 'mode', {'mode': 'GUIDED'})
            pg.wait_for_timeout(1500)   # GUIDED hedefi: bölge merkezi (MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, yalnız konum)
            ss.loop.call_soon_threadsafe(lambda: ss._gonder(ss.mav.set_position_target_global_int_encode(
                0, ss.sysid, ss.comp, 6, 0x0DF8, int(z['lat'] * 1e7), int(z['lon'] * 1e7), 30, 0, 0, 0, 0, 0, 0, 0, 0)))
        else:
            ss.sahte.aci = math.pi / 2 - 0.3   # dairenin doğu ucuna yakın: bölge içinde
        bekle(lambda: ss.jam.durum().get('active'), 90, 'bölgeye giriş')
        arac('giriş beklemesi sonrası')
        pg.wait_for_timeout(2500)
        d = durum(pg)
        print('  içeride:', d, 'tele.jam:', ss.tele.get('jam'), 'kip:', ss.tele.get('mode'), flush=True)
        if d['st'] != 'on' or not d['rozet'] or not d['lost'] or (not REAL and 'KUMANDA YOK' not in (d['band'] or '')) or 'TELEMETRİ YOK' not in (d['band'] or ''):
            hatalar.append(f'bölge içinde durum yanlış: {d}')
        shot(pg, '49-09-inside.png'); harita(pg, '49-10-inside-map.png')
        hb = pg.locator('.fs-hud').bounding_box()
        if not hb:   # varsayılan görünüm harekât paneli: sade HUD'a geç, rozet + soluk göstergeler orada
            js(pg, "[...document.querySelectorAll('.fs-bar button')].find(b => b.innerText.trim() === 'Panel')?.click()"); pg.wait_for_timeout(600)
            hb = pg.locator('.fs-hud').bounding_box(); hud_gecis = True
        else:
            hud_gecis = False
        if hb:
            shot(pg, '49-11-hud-lost.png', {'x': hb['x'] - 8, 'y': hb['y'] - 8, 'width': hb['width'] + 16, 'height': min(900 - hb['y'], hb['height'] + 16)})
        # telemetri kesik: yer istasyonu komutu reddedilir, göstergeler son değerde kalır
        r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'mode', 'params': {'mode': 'RTL'}})
        print('  içeride kip komutu:', r.status_code, r.text[:160], flush=True)
        if r.status_code == 200:
            hatalar.append('telemetri kesikken kip komutu kabul edildi')
        h1 = hud(pg)
        if not REAL:
            ss.sahte.hedef_alt = 90.0
            bekle(lambda: (ss.tele.get('alt_rel') or 0) > 80, 60, 'irtifa değişimi')
        else:
            pg.wait_for_timeout(6000)
        pg.wait_for_timeout(1200)
        h2 = hud(pg)
        print('  HUD donuk mu:', h1 == h2, '| gerçek irtifa', round(ss.tele.get('alt_rel') or 0, 1), flush=True)
        if h1 != h2:
            hatalar.append('telemetri kesikken sağ panel değişti:\n      ' + h1[:300].replace('\n', ' ') + '\n      ' + h2[:300].replace('\n', ' '))
        shot(pg, '49-12-inside-later.png')
        if hud_gecis:
            js(pg, "[...document.querySelectorAll('.fs-bar button')].find(b => b.innerText.trim() === 'Panel')?.click()"); pg.wait_for_timeout(500)
        # etkinken panel
        ac(pg)
        print('  etkin panel:', js(pg, "({start: document.querySelector('.fs-jam-start').innerText, live: document.querySelector('.fs-jam-live').innerText, rc: document.querySelector('.fs-jam-rc').checked, tlm: document.querySelector('.fs-jam-tlm').checked, zone: document.querySelector('.fs-jam-zone').checked, zr: document.querySelector('.fs-jam-zr').value})"), durum(pg)['pick'], flush=True)
        shot(pg, '49-13-panel-active.png')
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
        # dar ekran
        pg.set_viewport_size({'width': 420, 'height': 800}); pg.wait_for_timeout(1500)
        print('  dar: band', tasma(pg, '.fs-jam-banner'), 'harita', tasma(pg, '.fs-jam-map'), flush=True)
        shot(pg, '49-14-narrow.png')
        pg.locator('.fs-mob-btn').click(); pg.wait_for_timeout(700)
        pg.locator('.fs-jam-btn').click(); pg.wait_for_timeout(700)
        dp = tasma(pg, '.fs-jam-pop')
        print('  dar panel:', dp, flush=True)
        if min(dp['l'], dp['r'], dp['t'], dp['b']) < 0 or dp['w'] < 200:
            hatalar.append(f'dar ekranda panel taşıyor: {dp}')
        shot(pg, '49-15-narrow-panel.png')
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
        if js(pg, "document.querySelector('.fs-stage').classList.contains('fs-mob-open')"):
            pg.locator('.fs-mob-btn').click(); pg.wait_for_timeout(400)
        pg.set_viewport_size({'width': 1600, 'height': 900}); pg.wait_for_timeout(1200)
        # ---- bölgeden çıkış ----
        if REAL:
            print('  gerçek SITL: içeride 12 sn bekleniyor (aracın kendi tepkisi)…', flush=True)
            pg.wait_for_timeout(12000)
            print('  kip:', ss.tele.get('mode'), 'irtifa', round(ss.tele.get('alt_rel') or 0, 1), 'durum', {k: ss.jam.durum().get(k) for k in ('active', 'thr_mid', 'fs')}, flush=True)
            shot(pg, '49-16-real-inside.png')
        else:
            ss.sahte.aci = -math.pi / 2
            bekle(lambda: ss.jam.durum().get('active') is False, 15, 'bölgeden çıkış')
            pg.wait_for_timeout(2500)
            d = durum(pg); h3 = hud(pg)
            print('  çıkış:', d, 'HUD yeniden akıyor:', h3 != h2, flush=True)
            if d['st'] != 'wait' or d['rozet'] or d['lost'] or h3 == h2:
                hatalar.append(f'bölgeden çıkış durumu yanlış: {d}')
            shot(pg, '49-16-outside.png'); harita(pg, '49-17-outside-map.png')
        # Durdur
        cmd(sid, 'jam', {'off': True})
        bekle(lambda: not ss.jam.on, 8, 'karıştırma kapanışı')
        t0 = time.time()
        bekle(lambda: durum(pg)['st'] != 'on', 15, 'ön yüzde kapanış')   # headless tarayıcı yük altında telemetrinin gerisinde kalabilir
        print(f'  ön yüz kapanışı {time.time() - t0:.1f} sn sonra gördü', flush=True)
        pg.wait_for_timeout(1500)
        d = durum(pg)
        print('  kapandı:', d, flush=True)
        if d['rozet'] or d['lost'] or (not REAL and d['map']):
            hatalar.append(f'kapanış sonrası kalıntı: {d}')
        if REAL:
            # ---- gerçek SITL: konum kaybı tepkisi + otopilot konumu işaretçisi ----
            bekle(lambda: not ss.jam.durum().get('real'), 60, 'toparlanma')
            cmd(sid, 'mode', {'mode': 'GUIDED'}); pg.wait_for_timeout(3000)
            ac(pg); panel(pg, '49-20-real-panel.png')
            print('  fs seçici:', js(pg, "({gizli: document.querySelector('.fs-jam-fs').closest('.fs-jam-sec').hidden, sec: document.querySelector('.fs-jam-fs button[aria-pressed=true]')?.dataset.v, ipucu: document.querySelector('.fs-jam-fs').nextElementSibling.innerText})"), flush=True)
            pg.keyboard.press('Escape')
            cmd(sid, 'jam', {'gps': 'off', 'spoof': {'on': True, 'dir': 90, 'speed': 5, 'max_m': 120}, 'dur_s': 0})
            bekle(lambda: (ss.tele.get('nav_err') or 0) > 25, 90, 'aldatma: seyrüsefer hatası')
            pg.wait_for_timeout(2500)
            d = durum(pg)
            print('  aldatma:', d, 'nav_err', ss.tele.get('nav_err'), 'off_m', ss.jam.durum().get('off_m'), 'kip', ss.tele.get('mode'), flush=True)
            if 'otopilot konumu' not in d['lg']:
                hatalar.append(f'küçük haritada otopilot konumu yok: {d}')
            shot(pg, '49-21-ghost.png'); harita(pg, '49-22-ghost-map.png')
            pg.wait_for_timeout(8000)
            shot(pg, '49-23-ghost-later.png'); harita(pg, '49-24-ghost-map-later.png')
            cmd(sid, 'jam', {'off': True}); bekle(lambda: not ss.jam.on, 8, 'aldatma kapanışı')
            bekle(lambda: not ss.jam.durum().get('real'), 90, 'aldatma sonrası toparlanma')
            pg.wait_for_timeout(1500)
            print('  toparlandı:', durum(pg), flush=True)
            # tam GPS karıştırma (kopter varsayılanı: irtifa tut) — simülatör kip zorlamaz, ArduPilot'un kendi kararı
            cmd(sid, 'mode', {'mode': 'GUIDED'}); pg.wait_for_timeout(2500)
            a0 = ss.tele.get('alt_rel') or 0
            cmd(sid, 'jam', {'gps': 'full', 'dur_s': 0})
            bekle(lambda: ss.tele.get('mode') not in ('GUIDED', None), 40, 'tam karıştırma: kip değişimi')
            pg.wait_for_timeout(9000)
            sd = ss.jam.durum()
            print('  tam karıştırma: kip', ss.tele.get('mode'), '| irtifa', round(a0, 1), '→', round(ss.tele.get('alt_rel') or 0, 1), '| fs', sd.get('fs'), 'gaz-orta', sd.get('thr_mid'), '|', durum(pg)['band'], flush=True)
            if ss.tele.get('mode') != 'ALT_HOLD':
                hatalar.append(f"tam karıştırmada kip {ss.tele.get('mode')} (beklenen ALT_HOLD)")
            if abs((ss.tele.get('alt_rel') or 0) - a0) > 6:
                hatalar.append(f"ALT_HOLD'da irtifa korunmadı: {a0:.1f} → {ss.tele.get('alt_rel')}")
            shot(pg, '49-25-full-althold.png')
            cmd(sid, 'jam', {'off': True}); bekle(lambda: not ss.jam.on, 8, 'tam karıştırma kapanışı')
            bekle(lambda: not ss.jam.durum().get('real'), 90, 'tam karıştırma sonrası toparlanma')
            cmd(sid, 'mode', {'mode': 'GUIDED'}); pg.wait_for_timeout(2500)
            # yalnız kumanda: aracın kendi kumanda kaybı tepkisi
            cmd(sid, 'jam', {'rc': True, 'dur_s': 0})
            pg.wait_for_timeout(9000)
            print('  kumanda kaybı: kip', ss.tele.get('mode'), '|', durum(pg)['band'], flush=True)
            shot(pg, '49-26-rc-lost.png')
            cmd(sid, 'jam', {'off': True}); bekle(lambda: not ss.jam.on, 8, 'kumanda kapanışı')
            pg.wait_for_timeout(1500)
        # Bitir → rapor
        pg.locator('.fs-bar .btn.danger', has_text='Bitir').first.click()
        pg.wait_for_selector('.modal', timeout=8000); pg.wait_for_timeout(400)
        js(pg, "[...document.querySelectorAll('.modal .btn')].filter(b => /^Bitir$/.test(b.textContent.trim())).pop()?.click()")
        pg.wait_for_selector('.fs-rp-jam', timeout=40000)
        pg.wait_for_timeout(1500)
        js(pg, "document.querySelector('.fs-rp-jam').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(600)
        shot(pg, '49-30-report-jam.png')
        rk = js(pg, "document.querySelector('.fs-rp-jam').innerText").replace('\n', ' | ')
        print('  rapor kartı:', rk[:800], flush=True)
        for ad in ('Kumanda kesintisi süresi', 'Telemetri kesintisi süresi', 'Karıştırıcı bölgesi'):
            if ad not in rk:
                hatalar.append(f'rapor kartında "{ad}" yok')
        b.close()
except Exception as e:   # noqa: BLE001
    import traceback
    traceback.print_exc()
    hatalar.append('İSTİSNA: ' + str(e)[:400])
print('HATALAR:' if hatalar else 'hata yok', flush=True)
for h in hatalar:
    print('  -', h, flush=True)
sys.stdout.flush()
os._exit(1 if hatalar else 0)
