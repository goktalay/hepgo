"""Uçuş Simülatörü §37–§39 görsel doğrulaması — HEPGO + SIMUMAV (Playwright headless shell + SwiftShader; sahte kinematik; sunucular aynı süreçte):
  §37 sanal kumanda varsayılan açık + fiziksel kumanda (sahte Gamepad API: navigator.getGamepads + gamepadconnected) → tost, alt bant simgesi, eşleme
      paneli, kol → RC kanalları (sunucu sahte kinematiğinin rc dizisi), düğme → ARM
  §38 kumanda açıkken kadranlar yerine ince yatay ilerleme çubukları (temalar; Göstergesiz → yok; kumanda kapanınca kadranlar)
  §39 mobil: 390×844 / 412×915 / 844×390 (Chromium mobil emülasyonu: isMobile + hasTouch) üst şerit + alt bant gizli, ☰ menü açık / kapalı
Kareler /tmp/fltbar-shots/rcpad-*.png. Çalıştırma: ./.venv/bin/python -m tests.rcpad_shots
FLTBAR_BEFORE=1 (+ PYTHONPATH eski ağaç): yalnız "önce" kareleri (sanal kumanda elle açık kadranlar + mobil) → rcpad-once-*.png
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/rcpad-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='40150', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='4',
                  SIMUMAV_DATA_DIR=os.path.join(DATA, 'sm'), SIMUMAV_DEV_LOGIN='1', SIMUMAV_UDP_BASE='25950', SIMUMAV_MAX_FLIGHTS='3',
                  SIMUMAV_MP_PORT_BASE='26900', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', SIMUMAV_MAX_SPEEDUP='8')
os.makedirs(os.path.join(DATA, 'sm'), exist_ok=True)
BEFORE = os.environ.get('FLTBAR_BEFORE') == '1'
HEDEF = os.environ.get('RCPAD_TARGET', 'hepgo')   # hepgo | simumav (iki uygulama aynı süreçte açılmaz: çekirdek modüller ortak)
PRE = 'rcpad-once' if BEFORE else 'rcpad'
PORT, SPORT = 8897, 8645
BASE, SBASE = f'http://127.0.0.1:{PORT}', f'http://127.0.0.1:{SPORT}'
OUT = pathlib.Path('/tmp/fltbar-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

if HEDEF == 'hepgo':
    from app import auth  # noqa: E402
    from app.main import app  # noqa: E402
    SUNUCU = ((app, PORT),)
else:
    import app.simumav.main as smain  # noqa: E402  (SIMUMAV shim'i HEPGO modüllerinden ÖNCE)
    SUNUCU = ((smain.app, SPORT),)
from app import flightsim  # noqa: E402

for a, p in SUNUCU:
    srv = uvicorn.Server(uvicorn.Config(a, host='127.0.0.1', port=p, log_level='error'))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(160):
        try:
            socket.create_connection(('127.0.0.1', p), 0.3).close(); break
        except OSError:
            time.sleep(0.25)
    else:
        sys.exit('sunucu açılmadı')
time.sleep(1)
s = requests.Session()
sm = requests.Session()
c = d = pid = tr = None


def hepgo_hazirla():
    global c
    assert s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'}).status_code == 200
    s.post(f'{BASE}/api/kvkk/accept-terms', json={})
    s.post(f'{BASE}/api/location/consent', json={'granted': False})
    c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Test Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()


H = {'Origin': SBASE}


def sm_hazirla():
    global d, pid, tr
    assert sm.post(f'{SBASE}/api/session', json={'dev_user': 'ayse'}, headers=H).status_code == 200
    d = sm.post(f'{SBASE}/api/hangar', json={'name': 'Kartal', 'type': 'multirotor', 'model_key': 'builtin:quad', 'color': '#0ea5e9'}, headers=H).json()
    sm.put(f"{SBASE}/api/hangar/{d['id']}", json={'is_default': True}, headers=H)
    pid = sm.get(f'{SBASE}/api/crew').json()['pilots'][0]['id']
    tr = sm.post(f'{SBASE}/api/tracks', json={'name': 'Göl Kıyısı', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural',
                                              'world': {'seed': 21, 'runway': True, 'tree_density': 0.2, 'building_count': 20, 'runway_deg': 30}}, headers=H).json()


if HEDEF == 'hepgo':
    hepgo_hazirla()
else:
    sm_hazirla()
WORLD = {'mode': 'procedural', 'seed': 11, 'size_m': 3000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.2, 'building_count': 10}
hatalar = []
PAD_JS = """(() => {
  const pad = { id: 'Xbox Wireless Controller (STANDARD GAMEPAD Vendor: 045e Product: 0b13)', index: 0, mapping: 'standard', connected: true, timestamp: 0,
    axes: [0, 0, 0, 0], buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })) };
  window.__pad = pad; window.__padOn = false;
  Object.defineProperty(Navigator.prototype, 'getGamepads', { configurable: true, value: () => [window.__padOn ? pad : null, null, null, null] });
  window.__padConnect = () => { window.__padOn = true; const e = new Event('gamepadconnected'); Object.defineProperty(e, 'gamepad', { value: pad }); window.dispatchEvent(e); };
  window.__padBtn = (i, v) => { pad.buttons[i] = { pressed: !!v, touched: !!v, value: v ? 1 : 0 }; };
})()"""


def kontrol(ad, kosul, ek=''):
    print(('  ✓ ' if kosul else '  ✗ ') + ad + (f' — {ek}' if ek and not kosul else ''), flush=True)
    if not kosul:
        hatalar.append(f'{ad} {ek}')


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
    pg.screenshot(path=str(OUT / f'{PRE}-{ad}'))
    print('  kare', f'{PRE}-{ad}', flush=True)


def sayfa(b, w, hh, cookie, mobile=False, sm_=False):
    kw = dict(viewport={'width': w, 'height': hh}, locale='tr-TR')
    if mobile:
        kw.update(is_mobile=True, has_touch=True, device_scale_factor=2,
                  user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1')
    ctx = b.new_context(**kw)
    ctx.add_cookies([cookie])
    ctx.add_init_script(PAD_JS)
    if sm_:
        ctx.add_init_script("try { if (!localStorage.getItem('sm:lang')) localStorage.setItem('sm:lang', 'tr'); localStorage.setItem('simumav.consent', 'denied'); } catch (e) {}")
    pg = ctx.new_page()
    pg.set_default_timeout(150000)
    pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
    pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
    return ctx, pg


def hepgo_oturum(pg):
    r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False}, 'world': WORLD})
    assert r.status_code == 201, r.text
    sid = r.json()['id']; ss = flightsim.MANAGER.sessions[sid]
    bekle(lambda: ss.state == 'HAZIR', 180, 'HAZIR')
    pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')
    pg.wait_for_selector('.fs-stage', timeout=240000)
    pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera', timeout=240000)
    pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
    pg.wait_for_timeout(6000)
    return sid, ss


def sm_ucus(pg):
    f = sm.post(f'{SBASE}/api/fly/start', json={'drone_id': d['id'], 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False}}, headers=H)
    assert f.status_code == 201, f.text
    fid, sid = f.json()['flight_id'], f.json()['sim_id']
    ss = flightsim.MANAGER.sessions[sid]
    pg.goto(f'{SBASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
    pg.goto(f'{SBASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
    pg.wait_for_selector('.fs-stage .fs-bar', state='attached', timeout=240000)
    pg.wait_for_function('() => window.__smSim && window.__smSim.getCamera', timeout=240000)
    bekle(lambda: ss.state == 'HAZIR', 120, 'HAZIR')
    pg.wait_for_timeout(9000)
    return fid, sid, ss


def rc_ac(pg):   # önce kipi: eski kodda kumanda elle açılır
    if not pg.evaluate("document.querySelector('.fs-stage').classList.contains('rc-on')"):
        pg.evaluate("[...document.querySelectorAll('.fs-bar button')].find(b => /Sanal kumanda/.test(b.textContent))?.click()"); pg.wait_for_timeout(800)


def panel_kapat(pg):
    if pg.evaluate("document.querySelector('.fs-ops-btn')?.classList.contains('primary')"):
        pg.evaluate("document.querySelector('.fs-ops-btn').click()"); pg.wait_for_timeout(800)


def hepgo_calis(b, hc):
    # ================= HEPGO masaüstü =================
    ctx, pg = sayfa(b, 1600, 900, hc)
    sid, ss = hepgo_oturum(pg)
    s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40}})
    bekle(lambda: (ss.tele.get('alt_rel') or 0) > 25, 90, 'kalkış')
    panel_kapat(pg)
    if BEFORE:
        rc_ac(pg); pg.wait_for_timeout(1500)
        shot(pg, 'hepgo-rc-1600.png')
    else:
        kontrol('sanal kumanda varsayılan açık (rc-on, çubuklar görünür)', pg.evaluate("document.querySelector('.fs-stage').classList.contains('rc-on') && !document.querySelector('.fs-sticks').hidden"))
        g = pg.evaluate("(() => { const g = document.querySelector('.fs-gauges'), r = g.getBoundingClientRect(), L = document.querySelector('.fs-stick[data-side=l]').getBoundingClientRect(), R = document.querySelector('.fs-stick[data-side=r]').getBoundingClientRect(); return { disp: getComputedStyle(g).display, svg: getComputedStyle(g.querySelector('.fs-gauge-dial svg')).display, bar: getComputedStyle(g.querySelector('.fs-gauge-bar')).display, l: r.left, r: r.right, h: r.height, sl: L.right, sr: R.left }; })()")
        kontrol(f'kumanda açık: kadranlar yerine ilerleme çubukları, çubukların arasında {g}', g['svg'] == 'none' and g['bar'] == 'block' and g['l'] > g['sl'] and g['r'] < g['sr'])
        shot(pg, 'hepgo-50-rc-bars-1600.png')
        for t in ('glass', 'military', 'cockpit', 'minimal'):
            pg.evaluate(f"document.querySelector('.fs-gauges').dataset.gtheme = '{t}'"); pg.wait_for_timeout(500)
            bb = pg.locator('.fs-gauges').bounding_box()
            pg.screenshot(path=str(OUT / f'{PRE}-hepgo-51-bars-{t}.png'), clip={'x': bb['x'] - 260, 'y': bb['y'] - 60, 'width': bb['width'] + 520, 'height': bb['height'] + 160})
        pg.evaluate("document.querySelector('.fs-gauges').dataset.gtheme = 'none'"); pg.wait_for_timeout(400)
        kontrol('Göstergesiz tema: çubuklar da yok', pg.evaluate("getComputedStyle(document.querySelector('.fs-gauges')).display") == 'none')
        pg.evaluate("document.querySelector('.fs-gauges').dataset.gtheme = 'classic'")
        # ---- fiziksel kumanda
        pg.evaluate('window.__padConnect()'); pg.wait_for_timeout(1200)
        kontrol('kumanda bağlandı: alt bant simgesi + tost', pg.evaluate("!document.querySelector('.fs-pad').hidden") and 'Kumanda bağlandı' in pg.evaluate("document.body.innerText"))
        shot(pg, 'hepgo-52-pad-connected.png')
        pg.evaluate('window.__pad.axes[1] = -1; window.__pad.axes[2] = 0.6'); pg.wait_for_timeout(800)
        rc = ss.sahte.rc if ss.sahte else None
        kontrol(f'kol → RC kanalları (gaz 2000, yatış > 1650 — ölü bölge + §27.1 eğrisi): {rc}', rc is not None and rc[2] == 2000 and rc[0] > 1650)
        kontrol('sanal çubuk düğmesi kumandayı izler', 'translate' in pg.evaluate("document.querySelector('.fs-stick[data-side=l] .fs-stick-knob').style.transform"))
        pg.locator('.fs-pad-btn').click(); pg.wait_for_timeout(600)
        shot(pg, 'hepgo-53-pad-panel.png')
        pg.keyboard.press('Escape'); pg.wait_for_timeout(200)
        pg.evaluate('window.__pad.axes[1] = 0; window.__pad.axes[2] = 0'); pg.wait_for_timeout(2200)
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'disarm', 'params': {}})
        bekle(lambda: not ss.tele.get('armed'), 15, 'disarm')
        pg.evaluate('window.__padBtn(9, 1)'); pg.wait_for_timeout(300); pg.evaluate('window.__padBtn(9, 0)')
        kontrol('Start düğmesi → ARM', bekle(lambda: bool(ss.tele.get('armed')), 10, 'pad ARM'))
        # ---- kumanda kapalı → kadranlar
        pg.evaluate("[...document.querySelectorAll('.fs-bar button')].find(b => /Sanal kumanda/.test(b.textContent)).click()"); pg.wait_for_timeout(1200)
        kontrol('kumanda kapalı: kadranlar geri', pg.evaluate("getComputedStyle(document.querySelector('.fs-gauge-dial svg')).display") != 'none')
        kontrol('kapatma tercihi hatırlanır (caymaz.fs.rc.on=0)', pg.evaluate("localStorage.getItem('caymaz.fs.rc.on')") == '0')
        shot(pg, 'hepgo-54-rc-off-dials.png')
        pg.evaluate("[...document.querySelectorAll('.fs-bar button')].find(b => /Sanal kumanda/.test(b.textContent)).click()"); pg.wait_for_timeout(600)
        for w, hh in ((1280, 800), (900, 700)):
            pg.set_viewport_size({'width': w, 'height': hh}); pg.wait_for_timeout(1500)
            g = pg.evaluate("(() => { const r = document.querySelector('.fs-gauges').getBoundingClientRect(), L = document.querySelector('.fs-stick[data-side=l]').getBoundingClientRect(), R = document.querySelector('.fs-stick[data-side=r]').getBoundingClientRect(); return { l: r.left, r: r.right, sl: L.right, sr: R.left }; })()")
            kontrol(f'{w}: çubuklar arasına sığar {g}', g['l'] >= g['sl'] - 0.5 and g['r'] <= g['sr'] + 0.5)
            shot(pg, f'hepgo-55-rc-bars-{w}.png')
    ctx.close()
    # ================= HEPGO mobil =================
    for w, hh, ad in ((390, 844, 'iphone'), (412, 915, 'android'), (844, 390, 'yatay')):
        ctx, pg = sayfa(b, w, hh, hc, mobile=True)
        sid, ss = hepgo_oturum(pg)
        panel_kapat(pg)
        if BEFORE:
            rc_ac(pg); shot(pg, f'hepgo-60-mobile-{ad}.png'); ctx.close(); continue
        st = pg.evaluate("({mob: document.body.classList.contains('fs-mob'), nav: getComputedStyle(document.querySelector('.fs-nav')).display, bar: getComputedStyle(document.querySelector('.fs-bar')).display, hdr: document.querySelector('.app-header') ? getComputedStyle(document.querySelector('.app-header')).display : 'none', btn: getComputedStyle(document.querySelector('.fs-mob-btn')).display})")
        kontrol(f'{ad}: üst şerit + alt bant + uygulama başlığı gizli, ☰ görünür {st}', st['mob'] and st['nav'] == 'none' and st['bar'] == 'none' and st['hdr'] == 'none' and st['btn'] != 'none')
        shot(pg, f'hepgo-60-mobile-{ad}.png')
        pg.locator('.fs-mob-btn').tap(); pg.wait_for_timeout(700)
        st = pg.evaluate("({nav: getComputedStyle(document.querySelector('.fs-nav')).display, bar: getComputedStyle(document.querySelector('.fs-bar')).display, sw: document.documentElement.scrollWidth, W: innerWidth, bb: document.querySelector('.fs-bar').getBoundingClientRect().bottom, H: innerHeight})")
        kontrol(f'{ad}: ☰ → menü açık, taşma yok {st}', st['nav'] != 'none' and st['bar'] != 'none' and st['sw'] <= st['W'] and st['bb'] <= st['H'] + 0.5)
        shot(pg, f'hepgo-61-mobile-{ad}-open.png')
        pg.mouse.click(w // 2, hh // 2 - 40 if hh > 500 else hh // 2 - 60); pg.wait_for_timeout(500)
        kontrol(f'{ad}: dışına dokununca kapanır', not pg.evaluate("document.querySelector('.fs-stage').classList.contains('fs-mob-open')"))
        ctx.close()


def sm_calis(b, sc):
    # ================= SIMUMAV =================
    ctx, pg = sayfa(b, 1600, 900, sc, sm_=True)
    fid, sid, ss = sm_ucus(pg)
    sm.post(f'{SBASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40}}, headers=H)
    bekle(lambda: (ss.tele.get('alt_rel') or 0) > 25, 90, 'kalkış')
    panel_kapat(pg)
    if BEFORE:
        rc_ac(pg); pg.wait_for_timeout(1500); shot(pg, 'simumav-rc-1600.png')
    else:
        kontrol('SIMUMAV: sanal kumanda varsayılan açık + çubuk göstergeler', pg.evaluate("document.querySelector('.fs-stage').classList.contains('rc-on') && getComputedStyle(document.querySelector('.fs-gauge-dial svg')).display === 'none'"))
        shot(pg, 'simumav-50-rc-bars-1600.png')
        pg.evaluate('window.__padConnect()'); pg.wait_for_timeout(1000)
        pg.evaluate('window.__pad.axes[1] = -0.5'); pg.wait_for_timeout(800)
        rc = ss.sahte.rc if ss.sahte else None
        kontrol(f'SIMUMAV kol → RC (gaz ≈ 1730): {rc}', rc is not None and 1700 <= rc[2] <= 1760)
        pg.locator('.fs-pad-btn').click(); pg.wait_for_timeout(500)
        shot(pg, 'simumav-53-pad-panel.png')
        pg.keyboard.press('Escape')
    sm.post(f'{SBASE}/api/fly/{fid}/stop', json={}, headers=H)
    ctx.close()
    for w, hh, ad in ((390, 844, 'iphone'), (844, 390, 'yatay')):
        ctx, pg = sayfa(b, w, hh, sc, mobile=True, sm_=True)
        fid, sid, ss = sm_ucus(pg)
        panel_kapat(pg)
        if BEFORE:
            rc_ac(pg); shot(pg, f'simumav-60-mobile-{ad}.png')
        else:
            kontrol(f'SIMUMAV {ad}: üst şerit + alt bant gizli', pg.evaluate("getComputedStyle(document.querySelector('.fs-bar')).display === 'none' && getComputedStyle(document.querySelector('.fs-nav')).display === 'none'"))
            shot(pg, f'simumav-60-mobile-{ad}.png')
            pg.locator('.fs-mob-btn').tap(); pg.wait_for_timeout(700)
            shot(pg, f'simumav-61-mobile-{ad}-open.png')
        sm.post(f'{SBASE}/api/fly/{fid}/stop', json={}, headers=H)
        ctx.close()


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        if HEDEF == 'hepgo':
            hepgo_calis(b, {'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE})
        else:
            sm_calis(b, {'name': 'smsid', 'value': sm.cookies['smsid'], 'url': SBASE})
        b.close()
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
