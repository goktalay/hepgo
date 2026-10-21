"""HEPGO Uçuş Simülatörü — ALT BANT kapsülleri görsel doğrulaması (Playwright headless shell + SwiftShader; sahte kinematik HEPGO_SITL=0; uygulama aynı süreçte).
  • Görünüm + kamera türü TEK kapsül ("Takip ▾" | "📷 Kamera yok ▾"; görünüm açılır listesi, kamera yokken gimbal devre dışı, 1–5 kısayolu metni günceller)
  • "Panel" + ses (🔊 ▾) TEK kapsül
  • Servo tetik: tek "Dinle" düğmesi → yukarı açılan panel → "Dinlemeye başla" → panel kapanır, düğme kırmızı "Dinleniyor"; tekrar basınca durdur;
    Esc / dışarı tıklama kapatır (oturumdan çıkmaz); tetik → "Tetiklendi" → çarpma → özet (§34 akışı)
  • Kara aracı (rover) ve kayıttan oynatma (replay; servo yok); dar ekran (1280 / 900 genişlik) taşma denetimi
Kareler /tmp/fltbar-shots/hepgo-*.png. Çalıştırma: ./.venv/bin/python -m tests.fltbar_shots_hepgo  (FLTBAR_ONCE=1: önceki düzen için yalnız ilk kare)
"""
import json
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
DATA = '/tmp/fltbar-shots-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE='39950', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='4')
PORT = int(os.environ.get('SHOT_PORT') or 8893)
BASE = f'http://127.0.0.1:{PORT}'
PRE = os.environ.get('FLTBAR_PREFIX', 'hepgo')
ONCE = os.environ.get('FLTBAR_ONCE') == '1'
OUT = pathlib.Path('/tmp/fltbar-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
SAMPLE_BIN = pathlib.Path(__file__).with_name('data') / 'arduplane-sample.bin'

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app import auth, config, db, flightsim  # noqa: E402
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
s.post(f'{BASE}/api/location/consent', json={'granted': False})
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ankara Test Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
hatalar = []
WORLD = {'mode': 'procedural', 'seed': 11, 'size_m': 3000, 'time': 'day', 'wind_ms': 0, 'tree_density': 0.2, 'building_count': 10}


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
        time.sleep(0.2)
    hatalar.append(f'{ad}: {sec} sn içinde olmadı'); return False


def shot(pg, ad, bar=True, extra=260):
    """bar=True: alt bandın üstündeki açılır panelleri de içeren alt şerit; False: tam ekran."""
    vw = pg.viewport_size
    if bar:
        bb = None
        for _ in range(20):   # yeniden boyutlandırmadan hemen sonra yerleşim oturana dek
            bb = pg.locator('.fs-bar').bounding_box()
            if bb and bb['y'] < vw['height'] - 10:
                break
            pg.wait_for_timeout(250)
        y = max(0, min(bb['y'], vw['height'] - 60) - extra)
        pg.screenshot(path=str(OUT / f'{PRE}-{ad}'), clip={'x': 0, 'y': y, 'width': vw['width'], 'height': vw['height'] - y})
    else:
        pg.screenshot(path=str(OUT / f'{PRE}-{ad}'))
    print('  kare', f'{PRE}-{ad}', flush=True)


def cmd(sid, name, params=None):
    r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': name, 'params': params or {}})
    if r.status_code != 200:
        hatalar.append(f'cmd {name} {r.status_code} {r.text[:200]}')
    return r


TASMA_JS = """() => { const bar = document.querySelector('.fs-bar'); const W = innerWidth; const out = [];
  for (const e of bar.querySelectorAll('button, select, input, .pill-group, .fs-srv-pop:not([hidden]), .fs-audio-menu:not([hidden])')) {
    if (!e.offsetParent && getComputedStyle(e).position !== 'fixed') continue; const r = e.getBoundingClientRect(); if (r.width && (r.right > W + 0.5 || r.left < -0.5)) out.push((e.className || e.tagName) + ' ' + Math.round(r.left) + '..' + Math.round(r.right)); }
  return { W, sw: document.documentElement.scrollWidth, barH: bar.offsetHeight, out }; }"""


def tasma(pg, ad):
    t = pg.evaluate(TASMA_JS)
    kontrol(f'{ad}: taşma yok (W {t["W"]}, bant {t["barH"]} px)', not t['out'] and t['sw'] <= t['W'], json.dumps(t, ensure_ascii=False)[:300])


def oturum_ac(pg, body, sec='.fs-bar'):
    r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
    assert r.status_code == 201, r.text
    sid = r.json()['id']
    ss = flightsim.MANAGER.sessions[sid]
    bekle(lambda: ss.state == 'HAZIR', 180, 'HAZIR')
    pg.goto(f'{BASE}/#/drone/sim/{sid}?netsim=delay0', wait_until='domcontentloaded')   # netsim: teşhis adı window.__fsSim
    pg.wait_for_selector(sec, timeout=240000)
    pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera', timeout=240000)
    pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
    pg.wait_for_timeout(5000)   # giriş sekansı
    return sid, ss


def view_txt(pg):
    return pg.evaluate("document.querySelector('.fs-view-btn')?.textContent.trim()")


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1600, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)

        # ================= 1) çok rotorlu, kamera yok (kullanıcının ekran görüntüsündeki durum) =================
        sid, ss = oturum_ac(pg, {'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False}, 'camera': 'none', 'world': WORLD},
                            sec='.fs-bar .fs-srv' if not ONCE else '.fs-bar')
        cmd(sid, 'takeoff', {'alt': 40})
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 25, 90, 'kalkış')
        pg.wait_for_timeout(1500)
        shot(pg, '01-bar-1600.png', extra=40)
        shot(pg, '01-full-1600.png', bar=False)
        if ONCE:
            raise SystemExit(0)
        tasma(pg, '1600')
        kontrol('ayrı görünüm düğmeleri yok; görünüm + kamera tek kapsülde', pg.evaluate("!document.querySelector('.fs-bar > .pill-group > [data-cam]') && !!document.querySelector('.fs-cam-ctl .fs-view-btn') && !!document.querySelector('.fs-cam-ctl .fs-cam-btn')"))
        kontrol('Panel + ses tek kapsülde', pg.evaluate("!!document.querySelector('.fs-ops-snd > .fs-ops-btn') && !!document.querySelector('.fs-ops-snd .fs-audio-btn') && !!document.querySelector('.fs-ops-snd .fs-audio-more')"))
        kontrol('servo: satır içi giriş yok, tek Dinle düğmesi', pg.evaluate("document.querySelectorAll('.fs-bar .fs-srv > select, .fs-bar .fs-srv > label').length === 0 && document.querySelector('.fs-srv-btn').textContent.trim() === 'Dinle' && document.querySelector('.fs-srv-pop').hidden"))
        kontrol(f'görünüm düğmesi "Takip": {view_txt(pg)}', 'Takip' in (view_txt(pg) or ''))
        # ---- görünüm listesi (kamera yok → gimbal devre dışı)
        pg.locator('.fs-view-btn').click(); pg.wait_for_timeout(400)
        kontrol('görünüm listesi açık; gimbal devre dışı (kamera yok)', pg.evaluate("!document.querySelector('.fs-view-menu').hidden && document.querySelector('.fs-view-item[data-cam=fpv]').disabled && document.querySelectorAll('.fs-view-item').length === 5"))
        shot(pg, '02-view-menu-nocam.png')
        pg.locator('.fs-view-item[data-cam=fpv]').click(force=True); pg.wait_for_timeout(300)
        kontrol('devre dışı gimbal seçilemez', pg.evaluate('window.__fsSim.getCamera()') == 'follow')
        pg.locator('.fs-view-item[data-cam=free]').click(); pg.wait_for_timeout(600)
        kontrol(f'listeden Serbest: menü kapandı, düğme "Serbest" ({view_txt(pg)})', pg.evaluate("document.querySelector('.fs-view-menu').hidden && window.__fsSim.getCamera() === 'free'") and 'Serbest' in view_txt(pg))
        pg.mouse.click(800, 300); pg.keyboard.press('5'); pg.wait_for_timeout(600)
        kontrol(f'5 tuşu → Yer, düğme metni güncel ({view_txt(pg)})', pg.evaluate('window.__fsSim.getCamera()') == 'ground' and 'Yer' in view_txt(pg))
        pg.keyboard.press('2'); pg.wait_for_timeout(600)
        kontrol(f'2 tuşu → FPV ({view_txt(pg)})', pg.evaluate('window.__fsSim.getCamera()') == 'pilot' and 'FPV' in view_txt(pg))
        shot(pg, '03-view-fpv-key2.png', extra=40)
        pg.keyboard.press('1'); pg.wait_for_timeout(600)
        # ---- kamera türü Gündüz → gimbal etkin, 3 tuşu
        pg.locator('.fs-cam-btn').click(); pg.wait_for_timeout(300)
        shot(pg, '04-camera-menu.png', extra=330)
        pg.locator('.fs-cam-types [data-camtype=day]').click(); pg.wait_for_timeout(400)
        pg.mouse.click(800, 300); pg.keyboard.press('3'); pg.wait_for_timeout(800)
        kontrol(f'Gündüz: 3 tuşu → gimbal ({view_txt(pg)})', pg.evaluate('window.__fsSim.getCamera()') == 'fpv' and 'Gimbal' in view_txt(pg))
        pg.locator('.fs-view-btn').click(); pg.wait_for_timeout(400)
        kontrol('gimbal etkin (kamera var)', pg.evaluate("!document.querySelector('.fs-view-item[data-cam=fpv]').disabled"))
        shot(pg, '05-view-menu-gimbal.png')
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
        kontrol('Esc görünüm listesini kapatır, oturumdan çıkmaz', pg.evaluate("document.querySelector('.fs-view-menu').hidden && /#\\/drone\\/sim\\/\\d+/.test(location.hash)"))
        pg.keyboard.press('1'); pg.wait_for_timeout(600)
        # ---- ses menüsü (Panel ile aynı kapsülde)
        pg.locator('.fs-ops-snd .fs-audio-more').click(); pg.wait_for_timeout(300)
        shot(pg, '06-panel-sound-menu.png', extra=150)
        pg.mouse.click(800, 300); pg.wait_for_timeout(300)
        # ---- servo tetik: panel → dinle → kırmızı düğme
        cmd(sid, 'servo_set', {'ch': 9, 'pwm': 1500})
        pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(400)
        kontrol('servo paneli açıldı (düğmenin üstünde)', pg.evaluate("(() => { const p = document.querySelector('.fs-srv-pop'), b = document.querySelector('.fs-srv-btn'); return !p.hidden && p.getBoundingClientRect().bottom <= b.getBoundingClientRect().top; })()"))
        pg.select_option('.fs-srv-ch', '9'); pg.select_option('.fs-srv-cmp', 'ge')
        pg.locator('.fs-srv-pwm').fill('1900'); pg.locator('.fs-srv-pwm').press('Enter')
        pg.locator('.fs-srv-delay').fill('1500'); pg.locator('.fs-srv-delay').press('Enter')
        pg.wait_for_timeout(1200)
        kontrol('canlı PWM görünür (1500 µs)', '1500' in pg.evaluate("document.querySelector('.fs-srv-live').textContent"), pg.evaluate("document.querySelector('.fs-srv-live').textContent"))
        shot(pg, '07-servo-pop-idle.png', extra=330)
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
        kontrol('Esc servo panelini kapatır, oturumdan çıkmaz', pg.evaluate("document.querySelector('.fs-srv-pop').hidden && /#\\/drone\\/sim\\/\\d+/.test(location.hash)"))
        pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(300)
        pg.mouse.click(700, 250); pg.wait_for_timeout(300)
        kontrol('dışarı tıklama servo panelini kapatır', pg.evaluate("document.querySelector('.fs-srv-pop').hidden"))
        pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(300)
        pg.locator('.fs-srv-act').click()
        bekle(lambda: pg.evaluate("document.querySelector('.fs-srv').dataset.phase") == 'listening', 10, 'dinleme')
        pg.wait_for_timeout(300)
        st = pg.evaluate("({p: document.querySelector('.fs-srv').dataset.phase, open: !document.querySelector('.fs-srv-pop').hidden, t: document.querySelector('.fs-srv-btn').textContent.trim(), bg: getComputedStyle(document.querySelector('.fs-srv-btn')).animationName})")
        kontrol(f'dinleme: panel kapandı, düğme kırmızı yanıp sönen "Dinleniyor" {st}', st['p'] == 'listening' and not st['open'] and st['t'] == 'Dinleniyor' and st['bg'] == 'fs-srv-pulse')
        kontrol('sunucu dinliyor', ss.servo_tetik.durum().get('on') is True, json.dumps(ss.servo_tetik.durum(), ensure_ascii=False)[:200])
        shot(pg, '08-servo-listening.png', extra=40)
        pg.wait_for_timeout(500)
        shot(pg, '08b-servo-listening-blink.png', extra=40)
        pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(500)
        st = pg.evaluate("({open: !document.querySelector('.fs-srv-pop').hidden, act: document.querySelector('.fs-srv-act').textContent, dis: document.querySelector('.fs-srv-ch').disabled, live: document.querySelector('.fs-srv-live').textContent})")
        kontrol(f'dinlerken panel: değerler kilitli + canlı PWM + "Dinlemeyi durdur" {st}', st['open'] and st['act'] == 'Dinlemeyi durdur' and st['dis'] and '1500' in st['live'])
        shot(pg, '09-servo-pop-listening.png', extra=330)
        pg.locator('.fs-srv-act').click()
        bekle(lambda: pg.evaluate("document.querySelector('.fs-srv').dataset.phase") == 'idle', 10, 'durdurma')
        kontrol('durdur → boşta, düğme "Dinle"', pg.evaluate("document.querySelector('.fs-srv-btn').textContent.trim()") == 'Dinle' and ss.servo_tetik.durum().get('on') is not True)
        pg.mouse.click(700, 250); pg.wait_for_timeout(200)
        # ---- dar ekran
        for w, hh in ((1280, 800), (900, 700)):
            pg.set_viewport_size({'width': w, 'height': hh}); pg.wait_for_timeout(1500)
            tasma(pg, f'{w}')
            shot(pg, f'10-bar-{w}.png', extra=40)
            pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(400)
            tasma(pg, f'{w} servo paneli açık')
            shot(pg, f'11-servo-pop-{w}.png', extra=330)
            pg.keyboard.press('Escape')
            pg.locator('.fs-view-btn').click(); pg.wait_for_timeout(300)
            tasma(pg, f'{w} görünüm listesi açık')
            shot(pg, f'12-view-menu-{w}.png')
            pg.keyboard.press('Escape'); pg.wait_for_timeout(200)
        shot(pg, '13-full-900.png', bar=False)
        pg.set_viewport_size({'width': 1600, 'height': 900}); pg.wait_for_timeout(1200)
        # ---- harekât paneli açık
        if not pg.evaluate("document.querySelector('.fs-ops-btn').classList.contains('primary')"):
            pg.locator('.fs-ops-btn').click(); pg.wait_for_timeout(1200)
        shot(pg, '14-panel-open.png', bar=False)
        # ---- tetik: dinle → servo 2000 → Tetiklendi → çarpma → özet (§34 akışı aynen)
        pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(300); pg.locator('.fs-srv-act').click()
        bekle(lambda: pg.evaluate("document.querySelector('.fs-srv').dataset.phase") == 'listening', 10, 'dinleme 2')
        cmd(sid, 'servo_set', {'ch': 9, 'pwm': 2000})
        if bekle(lambda: pg.evaluate("document.querySelector('.fs-srv').dataset.phase") in ('pending', 'fired'), 10, 'tetik'):
            shot(pg, '15-servo-triggered.png', bar=False)
            kontrol('tetik: düğme "Tetiklendi" / "ÇARPMA"', pg.evaluate("document.querySelector('.fs-srv-btn').textContent.trim()") in ('Tetiklendi', 'ÇARPMA'))
        bekle(lambda: pg.evaluate("!!document.querySelector('.fs-rp-servo')"), 60, 'özet raporu (Servo tetik)')
        pg.wait_for_timeout(1500)
        shot(pg, '16-summary.png', bar=False)

        # ================= 2) kara aracı (rover) =================
        pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(1500)
        sid2, ss2 = oturum_ac(pg, {'mode': 'sitl', 'type': 'rover', 'center_id': c['id'], 'drive': 'skid', 'model': {'id': 'builtin:rover_ugv'}, 'rec': {'bin': False}, 'world': WORLD})
        if pg.evaluate("document.querySelector('.fs-ops-btn').classList.contains('primary')"):
            pg.locator('.fs-ops-btn').click(); pg.wait_for_timeout(800)
        tasma(pg, 'rover 1600')
        shot(pg, '20-rover-bar-1600.png', extra=40)
        pg.locator('.fs-view-btn').click(); pg.wait_for_timeout(300)
        shot(pg, '21-rover-view-menu.png')
        pg.keyboard.press('Escape')
        pg.set_viewport_size({'width': 900, 'height': 700}); pg.wait_for_timeout(1500)
        tasma(pg, 'rover 900')
        shot(pg, '22-rover-bar-900.png', extra=40)
        pg.set_viewport_size({'width': 1600, 'height': 900}); pg.wait_for_timeout(500)

        # ================= 3) kayıttan oynatma (replay): servo / komut yok =================
        hedef = config.UPLOAD_DIR / 'flightlogs'; hedef.mkdir(parents=True, exist_ok=True)
        shutil.copy(SAMPLE_BIN, hedef / 'ornek.bin')
        with db.connect() as conn:
            lid = conn.execute('''INSERT INTO flight_logs (file, file_name, size, status, analysis, aircraft, uploaded_by, uploaded_at, origin)
                                  VALUES (?, 'ornek.BIN', ?, 'TAMAM', ?, 'CZ-T', 1, ?, 'REAL')''',
                               ('flightlogs/ornek.bin', SAMPLE_BIN.stat().st_size, json.dumps({'summary': {'vehicle': 'ArduPlane', 'home': {'lat': 39.925, 'lng': 32.837}}}), db.now())).lastrowid
            conn.commit()
        pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(1500)
        oturum_ac(pg, {'mode': 'replay', 'log_id': lid, 'world': {'mode': 'procedural', 'seed': 3, 'size_m': 4000}}, sec='.fs-bar .fs-playbar')
        kontrol('replay: servo tetik yok, görünüm + kamera ve Panel + ses kapsülleri var', pg.evaluate("!document.querySelector('.fs-srv') && !!document.querySelector('.fs-cam-ctl .fs-view-btn') && !!document.querySelector('.fs-ops-snd .fs-ops-btn')"))
        if pg.evaluate("document.querySelector('.fs-ops-btn').classList.contains('primary')"):
            pg.locator('.fs-ops-btn').click(); pg.wait_for_timeout(800)
        tasma(pg, 'replay 1600')
        shot(pg, '30-replay-bar-1600.png', extra=40)
        for w, hh in ((1280, 800), (900, 700)):
            pg.set_viewport_size({'width': w, 'height': hh}); pg.wait_for_timeout(1500)
            tasma(pg, f'replay {w}')
            shot(pg, f'31-replay-bar-{w}.png', extra=40)
        shot(pg, '32-replay-full-900.png', bar=False)
        b.close()
except SystemExit:
    pass
except Exception:
    try:
        pg.screenshot(path=str(OUT / f'{PRE}-hata.png'))
    except Exception:   # noqa: BLE001
        pass
    raise
finally:
    print('\n'.join(hatalar) if hatalar else 'hata yok')
    server.should_exit = True
