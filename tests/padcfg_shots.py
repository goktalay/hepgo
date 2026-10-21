"""Uçuş Simülatörü §37 fiziksel kumanda AYAR PANELİ görsel doğrulaması — HEPGO + SIMUMAV (Playwright headless shell + SwiftShader; sahte kinematik;
sahte Gamepad API — tests/rcpad_shots.py yöntemi):
  • kumanda girdisi hassasiyeti: genel ölçek + eksen ölçeği + expo kaydırıcıları, SVG eğri önizlemesi (kesikli turuncu = ⚙ Hassasiyet ile birlikte),
    canlı nokta / giriş → çıkış; ayar RC kanalına yansır (sahte kinematiğin rc dizisi)
  • panel açıkken basılı düğmenin satırı + rozeti parlar (bırakınca söner); oynatılan eksen satırı hafif parlar; requestAnimationFrame döngüsü yalnız
    panel açıkken
  • Algıla (atama kipi): basılan düğme anında atanır, o sırada eylem (ARM) tetiklenmez
  • masaüstü 1600×900 + mobil 390×844 (☰ menü → kumanda simgesi)
Kareler /tmp/padcfg-shots/*.png. Çalıştırma: RCPAD_TARGET=hepgo|simumav ./.venv/bin/python -m tests.padcfg_shots
"""
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/padcfg-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='40350', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='4',
                  SIMUMAV_DATA_DIR=os.path.join(DATA, 'sm'), SIMUMAV_DEV_LOGIN='1', SIMUMAV_UDP_BASE='26150', SIMUMAV_MAX_FLIGHTS='3',
                  SIMUMAV_MP_PORT_BASE='27100', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', SIMUMAV_MAX_SPEEDUP='8')
os.makedirs(os.path.join(DATA, 'sm'), exist_ok=True)
HEDEF = os.environ.get('RCPAD_TARGET', 'hepgo')
PORT, SPORT = 8917, 8665
BASE, SBASE = f'http://127.0.0.1:{PORT}', f'http://127.0.0.1:{SPORT}'
OUT = pathlib.Path('/tmp/padcfg-shots'); OUT.mkdir(parents=True, exist_ok=True)
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
H = {'Origin': SBASE}
c = d = pid = tr = None
if HEDEF == 'hepgo':
    assert s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'}).status_code == 200
    s.post(f'{BASE}/api/kvkk/accept-terms', json={})
    s.post(f'{BASE}/api/location/consent', json={'granted': False})
    c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Test Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
else:
    assert sm.post(f'{SBASE}/api/session', json={'dev_user': 'ayse'}, headers=H).status_code == 200
    d = sm.post(f'{SBASE}/api/hangar', json={'name': 'Kartal', 'type': 'multirotor', 'model_key': 'builtin:quad', 'color': '#0ea5e9'}, headers=H).json()
    sm.put(f"{SBASE}/api/hangar/{d['id']}", json={'is_default': True}, headers=H)
    pid = sm.get(f'{SBASE}/api/crew').json()['pilots'][0]['id']
    tr = sm.post(f'{SBASE}/api/tracks', json={'name': 'Göl Kıyısı', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural',
                                              'world': {'seed': 21, 'runway': True, 'tree_density': 0.2, 'building_count': 20, 'runway_deg': 30}}, headers=H).json()
WORLD = {'mode': 'procedural', 'seed': 11, 'size_m': 3000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.2, 'building_count': 10}
hatalar = []
# Sahte Gamepad API + rAF sayacı (adı padFrame olan geri çağrılar = kumanda paneli döngüsü)
PAD_JS = """(() => {
  const pad = { id: 'Xbox Wireless Controller (STANDARD GAMEPAD Vendor: 045e Product: 0b13)', index: 0, mapping: 'standard', connected: true, timestamp: 0,
    axes: [0, 0, 0, 0], buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })) };
  window.__pad = pad; window.__padOn = false; window.__padRaf = 0;
  Object.defineProperty(Navigator.prototype, 'getGamepads', { configurable: true, value: () => [window.__padOn ? pad : null, null, null, null] });
  window.__padConnect = () => { window.__padOn = true; const e = new Event('gamepadconnected'); Object.defineProperty(e, 'gamepad', { value: pad }); window.dispatchEvent(e); };
  window.__padBtn = (i, v) => { pad.buttons[i] = { pressed: !!v, touched: !!v, value: v ? 1 : 0 }; };
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = f => { if (f && f.name === 'padFrame') window.__padRaf++; return raf(f); };
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


def bekle_js(pg, ifade, ms=15000):   # SwiftShader altında 3B sahne kareleri (dolayısıyla rAF) yavaş olabilir → koşulu bekle
    try:
        pg.wait_for_function(ifade, timeout=ms, polling=100); return True
    except Exception:   # noqa: BLE001
        return False


def shot(pg, ad, panel=False):
    if panel:
        bb = pg.locator('.fs-pad-pop').bounding_box()
        pg.screenshot(path=str(OUT / ad), clip={'x': max(0, bb['x'] - 8), 'y': max(0, bb['y'] - 8), 'width': bb['width'] + 16, 'height': bb['height'] + 16})
    else:
        pg.screenshot(path=str(OUT / ad))
    print('  kare', ad, flush=True)


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


def panel_kapat(pg):
    if pg.evaluate("document.querySelector('.fs-ops-btn')?.classList.contains('primary')"):
        pg.evaluate("document.querySelector('.fs-ops-btn').click()"); pg.wait_for_timeout(800)


def kaydir(pg, sel, v):   # aralık girişine değer + input olayı (gerçek kullanıcı kaydırması gibi)
    pg.evaluate("([s, v]) => { const i = document.querySelector(s); i.value = String(v); i.dispatchEvent(new Event('input', { bubbles: true })); }", [sel, v])


def ortak_panel(pg, ss, on, disarm):
    """Masaüstü panel senaryosu (HEPGO ve SIMUMAV ortak)."""
    pg.evaluate('window.__padConnect()'); pg.wait_for_timeout(1200)
    kontrol(f'{on}: kumanda simgesi görünür', pg.evaluate("!document.querySelector('.fs-pad').hidden"))
    r0 = pg.evaluate('window.__padRaf')
    pg.wait_for_timeout(600)
    kontrol(f'{on}: panel kapalıyken rAF döngüsü yok ({r0} → {pg.evaluate("window.__padRaf")})', pg.evaluate('window.__padRaf') == r0)
    pg.locator('.fs-pad-btn').click()
    ok = bekle_js(pg, f'window.__padRaf > {r0 + 3}')
    kontrol(f'{on}: panel açık → rAF döngüsü çalışıyor ({pg.evaluate("window.__padRaf")})', ok)
    st = pg.evaluate("""(() => { const p = document.querySelector('.fs-pad-pop'); return { sens: !!p.querySelector('.fs-pad-cv .cur')?.getAttribute('d'),
      feel: !!p.querySelector('.fs-pad-cv .feel')?.getAttribute('d'), tabs: p.querySelectorAll('.fs-pad-seg button').length, chips: p.querySelectorAll('.fs-pad-strip .fs-pad-chip').length,
      learn: p.querySelectorAll('.fs-pad-learn').length }; })()""")
    kontrol(f'{on}: hassasiyet bölümü (eğri + ⚙ birleşik eğri + 4 eksen sekmesi + 17 canlı rozet + Algıla) {st}', st['sens'] and st['feel'] and st['tabs'] == 4 and st['chips'] == 17 and st['learn'] == 11)
    shot(pg, f'{on}-01-panel.png', panel=True)
    shot(pg, f'{on}-01-panel-tam.png')
    # ---- basılı düğme parlaması: 2 (atanmamış) + 13 (ch5−; eylem zararsız)
    pg.evaluate('window.__padBtn(2, 1); window.__padBtn(13, 1)'); bekle_js(pg, "document.querySelector('[data-act=ch5_down]').classList.contains('hit') && document.querySelectorAll('.fs-pad-strip .fs-pad-chip.on').length === 2"); pg.wait_for_timeout(300)
    g = pg.evaluate("""(() => { const p = document.querySelector('.fs-pad-pop'), row = p.querySelector('[data-act=ch5_down]');
      return { row: row.classList.contains('hit'), chip: row.querySelector('.fs-pad-chip').classList.contains('on'), sh: getComputedStyle(row).boxShadow,
        strip: [...p.querySelectorAll('.fs-pad-strip .fs-pad-chip.on')].map(c => c.textContent) }; })()""")
    pg.evaluate("document.querySelector('[data-act=ch5_down]').scrollIntoView({ block: 'center' })"); pg.wait_for_timeout(250)
    kontrol(f'{on}: basılı düğme 13 → ch5− satırı + rozeti parlar, canlı şeritte 2 ve 13 {g}', g['row'] and g['chip'] and g['strip'] == ['2', '13'] and 'rgba' in g['sh'])
    shot(pg, f'{on}-02-dugme-parlama.png', panel=True)
    pg.evaluate('window.__padBtn(2, 0); window.__padBtn(13, 0)'); bekle_js(pg, "!document.querySelector('.fs-pad-strip .fs-pad-chip.on')")
    kontrol(f'{on}: bırakınca söner', not pg.evaluate("document.querySelector('[data-act=ch5_down]').classList.contains('hit') || !!document.querySelector('.fs-pad-strip .fs-pad-chip.on')"))
    # ---- hassasiyet: yatış ekseni yarım; önce varsayılanla RC, sonra genel ölçek %50 + expo %60
    pg.evaluate('window.__pad.axes[2] = 0.6'); pg.wait_for_timeout(900); bekle_js(pg, "document.querySelector('.fs-pad-row[data-axis=roll]').classList.contains('mv')")
    rc_a = list(ss.sahte.rc) if ss.sahte and ss.sahte.rc else None
    pg.evaluate("document.querySelector('.fs-pad-seg button[data-axis=roll]').click()"); pg.wait_for_timeout(150)
    kaydir(pg, '.fs-pad-pop input[aria-label="Genel ölçek"]', 50)
    kaydir(pg, '.fs-pad-pop input[aria-label="Expo"]', 60)
    pg.wait_for_timeout(900); bekle_js(pg, "/0\\.1/.test(document.querySelector('.fs-pad-io').textContent)", 6000)
    rc_b = list(ss.sahte.rc) if ss.sahte and ss.sahte.rc else None
    kontrol(f'{on}: genel ölçek %50 + expo %60 → yatış kanalı merkeze yaklaşır {rc_a} → {rc_b}', rc_a and rc_b and rc_a[0] > 1600 and 1500 < rc_b[0] < rc_a[0] - 60)
    sv = pg.evaluate("""(() => { const p = document.querySelector('.fs-pad-pop'); return { io: p.querySelector('.fs-pad-io').textContent, mv: p.querySelector('[data-axis=roll].fs-pad-row').classList.contains('mv'),
      dot: +p.querySelector('.fs-pad-cv .dot').getAttribute('cx') }; })()""")
    kontrol(f'{on}: canlı giriş → çıkış, nokta sağda, yatış satırı hafif parlar {sv["io"]} {sv["dot"]} {sv["mv"]}', '→' in sv['io'] and sv['dot'] > 70 and sv['mv'])
    pg.evaluate("document.querySelector('.fs-pad-pop').scrollTop = 0"); pg.wait_for_timeout(200)
    shot(pg, f'{on}-03-egri-onizleme.png', panel=True)
    pg.evaluate('window.__pad.axes[2] = 0'); pg.wait_for_timeout(300)
    # ---- Algıla: 'lock' satırı ← Start (9; şu an ARM'a atanmış) — disarm'da basılır: atama anında, ARM satırı boşa düşer, ARM TETİKLENMEZ
    disarm()
    bekle(lambda: not ss.tele.get('armed'), 20, 'disarm')
    pg.evaluate("document.querySelector('[data-act=lock] .fs-pad-learn').click()"); pg.wait_for_timeout(250)
    kontrol(f'{on}: Algıla → "Düğmeye basın…"', 'basın' in pg.evaluate("document.querySelector('[data-act=lock] .fs-pad-learn').textContent"))
    pg.evaluate("document.querySelector('[data-act=lock]').scrollIntoView({ block: 'center' })"); pg.wait_for_timeout(200)
    shot(pg, f'{on}-04-algila-bekliyor.png', panel=True)
    pg.evaluate('window.__padBtn(9, 1)'); bekle_js(pg, "document.querySelector('[data-act=lock] select').value === '9'"); pg.wait_for_timeout(150)
    a = pg.evaluate("""(() => { const r = document.querySelector('[data-act=lock]'); return { sel: r.querySelector('select').value, chip: r.querySelector('.fs-pad-chip').textContent,
      on: r.querySelector('.fs-pad-chip').classList.contains('on'), ok: r.classList.contains('ok'), arm: document.querySelector('[data-act=arm] select').value }; })()""")
    kontrol(f'{on}: Start (9) anında kilit satırına atandı + onay parlaması; ARM satırı boşa düştü {a}', a['sel'] == '9' and a['chip'] == '9' and a['on'] and a['ok'] and a['arm'] == '-1')
    shot(pg, f'{on}-05-algila-atandi.png', panel=True)
    pg.wait_for_timeout(1500)
    kontrol(f'{on}: atama basışı ARM tetiklemedi', not ss.tele.get('armed'))
    pg.evaluate('window.__padBtn(9, 0)'); pg.wait_for_timeout(300)
    # ---- eksen algılama: gaz satırı → eksen 3'ü yukarı it (ham −0,9) → i 3, ters
    pg.evaluate("document.querySelector('.fs-pad-row[data-axis=thr] .fs-pad-learn').click()"); pg.wait_for_timeout(200)
    pg.evaluate('window.__pad.axes[3] = -0.9'); bekle_js(pg, "document.querySelector('.fs-pad-row[data-axis=thr] select').value === '3'")
    t = pg.evaluate("({ v: document.querySelector('.fs-pad-row[data-axis=thr] select').value, inv: document.querySelector('.fs-pad-row[data-axis=thr] input[type=checkbox]').checked, p: document.querySelector('.fs-pad-row[data-axis=pitch] select').value })")
    kontrol(f'{on}: eksen algılama: gaz → Eksen 3 (ters), yunuslama boşa düştü {t}', t['v'] == '3' and t['inv'] and t['p'] == '-1')
    pg.evaluate('window.__pad.axes[3] = 0'); pg.wait_for_timeout(200)
    pg.evaluate("document.querySelector('.fs-pad-reset').click()"); pg.wait_for_timeout(300)
    kontrol(f'{on}: Varsayılana dön → ölçek %100, gaz eksen 1', pg.evaluate("document.querySelector('.fs-pad-pop input[aria-label=\"Genel ölçek\"]').value") == '100' and pg.evaluate("document.querySelector('.fs-pad-row[data-axis=thr] select').value") == '1')
    pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
    pg.wait_for_timeout(800); r1 = pg.evaluate('window.__padRaf'); pg.wait_for_timeout(1500)
    kontrol(f'{on}: panel kapanınca rAF durur', pg.evaluate('window.__padRaf') == r1)
    pg.evaluate('window.__padBtn(9, 1)'); pg.wait_for_timeout(300); pg.evaluate('window.__padBtn(9, 0)')
    kontrol(f'{on}: panel kapalıyken Start → ARM (eylem yolu bozulmadı)', bekle(lambda: bool(ss.tele.get('armed')), 12, 'pad ARM'))


def mobil(pg, on):
    pg.evaluate('window.__padConnect()'); pg.wait_for_timeout(1200)
    pg.locator('.fs-mob-btn').tap(); pg.wait_for_timeout(700)
    pg.locator('.fs-pad-btn').tap(); pg.wait_for_timeout(700)
    bb = pg.evaluate("(() => { const r = document.querySelector('.fs-pad-pop').getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top, b: r.bottom, W: innerWidth, H: innerHeight, hid: document.querySelector('.fs-pad-pop').hidden }; })()")
    kontrol(f'{on}: mobil panel ekrana sığar {bb}', not bb['hid'] and bb['l'] >= 0 and bb['r'] <= bb['W'] + 0.5 and bb['t'] >= 0 and bb['b'] <= bb['H'] + 0.5)
    pg.evaluate('window.__padBtn(5, 1); window.__pad.axes[0] = 0.7'); bekle_js(pg, "document.querySelector('[data-act=mode_next]').classList.contains('hit')"); pg.wait_for_timeout(300)
    kontrol(f'{on}: mobil: RB basılı → sonraki mod satırı parlar', pg.evaluate("document.querySelector('[data-act=mode_next]').classList.contains('hit')"))
    shot(pg, f'{on}-10-mobil-panel.png')
    pg.evaluate("document.querySelector('.fs-pad-pop').scrollTop = 99999"); pg.wait_for_timeout(300)
    shot(pg, f'{on}-11-mobil-panel-alt.png')
    pg.evaluate('window.__padBtn(5, 0); window.__pad.axes[0] = 0')


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        if HEDEF == 'hepgo':
            hc = {'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}
            ctx, pg = sayfa(b, 1600, 900, hc)
            sid, ss = hepgo_oturum(pg)
            s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40}})
            bekle(lambda: (ss.tele.get('alt_rel') or 0) > 25, 90, 'kalkış')
            panel_kapat(pg)
            ortak_panel(pg, ss, 'hepgo', lambda: s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'disarm', 'params': {}}))
            ctx.close()
            ctx, pg = sayfa(b, 390, 844, hc, mobile=True)
            hepgo_oturum(pg); panel_kapat(pg)
            mobil(pg, 'hepgo')
            ctx.close()
        else:
            sc = {'name': 'smsid', 'value': sm.cookies['smsid'], 'url': SBASE}
            ctx, pg = sayfa(b, 1600, 900, sc, sm_=True)
            fid, sid, ss = sm_ucus(pg)
            sm.post(f'{SBASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40}}, headers=H)
            bekle(lambda: (ss.tele.get('alt_rel') or 0) > 25, 90, 'kalkış')
            panel_kapat(pg)
            ortak_panel(pg, ss, 'simumav', lambda: sm.post(f'{SBASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'disarm', 'params': {}}, headers=H))
            sm.post(f'{SBASE}/api/fly/{fid}/stop', json={}, headers=H)
            ctx.close()
            ctx, pg = sayfa(b, 390, 844, sc, mobile=True, sm_=True)
            fid, sid, ss = sm_ucus(pg); panel_kapat(pg)
            mobil(pg, 'simumav')
            sm.post(f'{SBASE}/api/fly/{fid}/stop', json={}, headers=H)
            ctx.close()
        b.close()
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
