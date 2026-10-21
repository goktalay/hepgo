"""SIMUMAV uçuş ekranı — ALT BANT kapsülleri görsel doğrulaması (HEPGO ortak modülleri; Playwright headless shell + SwiftShader; sahte SITL; sunucu aynı süreçte).
  • Görünüm + kamera türü TEK kapsül (görünüm açılır listesi; kamera yokken gimbal devre dışı; 1–5 kısayolu metni günceller) · Panel + ses TEK kapsül
  • Servo tetik: tek "Dinle" düğmesi → yukarı açılan panel → "Dinlemeye başla" → panel kapanır, düğme kırmızı "Dinleniyor"; Esc kapatır
  • Kara aracı (rover); dar ekran (1280 / 900) taşma denetimi; İngilizce arayüz (çeviri)
Kareler /tmp/fltbar-shots/simumav-*.png. Çalıştırma: ./.venv/bin/python -m tests.fltbar_shots_simumav  (FLTBAR_ONCE=1: yalnız ilk kare)
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
DATA = '/tmp/fltbar-shots-sm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(SIMUMAV_DATA_DIR=DATA, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='25750', SIMUMAV_MAX_FLIGHTS='2',
                  SIMUMAV_MP_PORT_BASE='26700', SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(DATA, 'yok.env'),
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='', SIMUMAV_MAX_SPEEDUP='8')
PORT = int(os.environ.get('SHOT_PORT') or 8641)
BASE = f'http://127.0.0.1:{PORT}'
PRE = os.environ.get('FLTBAR_PREFIX', 'simumav')
ONCE = os.environ.get('FLTBAR_ONCE') == '1'
OUT = pathlib.Path('/tmp/fltbar-shots'); OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import app.simumav.main as smain  # noqa: E402
from app import flightsim  # noqa: E402

server = uvicorn.Server(uvicorn.Config(smain.app, host='127.0.0.1', port=PORT, log_level='error'))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(120):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close(); break
    except OSError:
        time.sleep(0.25)
else:
    sys.exit('sunucu açılmadı')

H = {'Origin': BASE}
s = requests.Session()
assert s.post(f'{BASE}/api/session', json={'dev_user': 'ayse'}, headers=H).status_code == 200
tok = s.cookies['smsid']
d = s.post(f'{BASE}/api/hangar', json={'name': 'Kartal', 'type': 'multirotor', 'model_key': 'builtin:quad', 'color': '#0ea5e9'}, headers=H).json()
s.put(f"{BASE}/api/hangar/{d['id']}", json={'is_default': True}, headers=H)
dr = s.post(f'{BASE}/api/hangar', json={'name': 'Keşif-1', 'type': 'rover', 'model_key': 'glb:rover_4x4', 'color': '#f59e0b'}, headers=H).json()
pid = s.get(f'{BASE}/api/crew').json()['pilots'][0]['id']
tr = s.post(f'{BASE}/api/tracks', json={'name': 'Göl Kıyısı', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural',
                                        'world': {'seed': 21, 'runway': True, 'tree_density': 0.2, 'building_count': 20, 'runway_deg': 30}}, headers=H).json()
s.put(f"{BASE}/api/tracks/{tr['id']}", json={'is_default': True}, headers=H)
hatalar = []


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


def shot(pg, ad, bar=True, extra=260):
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


TASMA_JS = """() => { const bar = document.querySelector('.fs-bar'); const W = innerWidth; const out = [];
  for (const e of bar.querySelectorAll('button, select, input, .pill-group, .fs-srv-pop:not([hidden]), .fs-audio-menu:not([hidden])')) {
    if (!e.offsetParent) continue; const r = e.getBoundingClientRect(); if (r.width && (r.right > W + 0.5 || r.left < -0.5)) out.push((e.className || e.tagName) + ' ' + Math.round(r.left) + '..' + Math.round(r.right)); }
  return { W, sw: document.documentElement.scrollWidth, barH: bar.offsetHeight, out }; }"""


def tasma(pg, ad):
    t = pg.evaluate(TASMA_JS)
    kontrol(f'{ad}: taşma yok (W {t["W"]}, bant {t["barH"]} px)', not t['out'] and t['sw'] <= t['W'], json.dumps(t, ensure_ascii=False)[:300])


def ucus(pg, drone_id, camera=None):
    body = {'drone_id': drone_id, 'pilot_id': pid, 'track_id': tr['id'], 'record': {'bin': False}}
    if camera:
        body['camera'] = camera
    f = s.post(f'{BASE}/api/fly/start', json=body, headers=H)
    assert f.status_code == 201, f.text
    fid, sid = f.json()['flight_id'], f.json()['sim_id']
    ss = flightsim.MANAGER.sessions[sid]
    pg.goto(f'{BASE}/app/#/menu', wait_until='domcontentloaded'); pg.wait_for_timeout(500)
    pg.goto(f'{BASE}/app/#/fly/{fid}', wait_until='domcontentloaded')
    pg.wait_for_selector('.fs-bar .fs-cam-ctl', timeout=240000)
    pg.wait_for_function('() => window.__smSim && window.__smSim.getCamera', timeout=240000)
    bekle(lambda: ss.state == 'HAZIR', 120, 'HAZIR')
    pg.wait_for_timeout(9000)   # giriş sekansı
    return fid, sid, ss


def view_txt(pg):
    return pg.evaluate("document.querySelector('.fs-view-btn')?.textContent.trim()")


def phase(pg):
    return pg.evaluate("document.querySelector('.fs-srv')?.dataset.phase")


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1600, 'height': 900}, locale='tr-TR')
        ctx.add_cookies([{'name': 'smsid', 'value': tok, 'url': BASE}])
        ctx.add_init_script("try { if (!localStorage.getItem('sm:lang')) localStorage.setItem('sm:lang', 'tr'); localStorage.setItem('simumav.consent', 'denied'); } catch (e) {}")   # dil yeniden yüklemede korunur (İngilizce adımı)
        pg = ctx.new_page()
        pg.set_default_timeout(150000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:300]}') if m.type == 'error' and 'WebGL' not in m.text and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)

        # ================= 1) çok rotorlu, kamera yok =================
        fid, sid, ss = ucus(pg, d['id'], camera='none')
        s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40}}, headers=H)
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 25, 90, 'kalkış')
        if pg.evaluate("document.querySelector('.fs-ops-btn').classList.contains('primary')"):
            pg.locator('.fs-ops-btn').click(); pg.wait_for_timeout(800)
        shot(pg, '01-bar-1600.png', extra=40)
        shot(pg, '01-full-1600.png', bar=False)
        if ONCE:
            raise SystemExit(0)
        tasma(pg, '1600')
        kontrol('görünüm + kamera tek kapsül; ayrı görünüm düğmeleri yok', pg.evaluate("!document.querySelector('.fs-bar > .pill-group > [data-cam]') && !!document.querySelector('.fs-cam-ctl .fs-view-btn')"))
        kontrol('Panel + ses tek kapsül', pg.evaluate("!!document.querySelector('.fs-ops-snd > .fs-ops-btn') && !!document.querySelector('.fs-ops-snd .fs-audio-btn')"))
        kontrol('servo: tek Dinle düğmesi', pg.evaluate("document.querySelectorAll('.fs-bar .fs-srv > select, .fs-bar .fs-srv > label').length === 0 && document.querySelector('.fs-srv-btn').textContent.trim() === 'Dinle'"))
        pg.locator('.fs-view-btn').click(); pg.wait_for_timeout(400)
        kontrol('görünüm listesi; gimbal devre dışı (kamera yok)', pg.evaluate("document.querySelector('.fs-view-item[data-cam=fpv]').disabled"))
        shot(pg, '02-view-menu-nocam.png')
        pg.locator('.fs-view-item[data-cam=free]').click(); pg.wait_for_timeout(500)
        kontrol(f'listeden Serbest ({view_txt(pg)})', pg.evaluate('window.__smSim.getCamera()') == 'free' and 'Serbest' in view_txt(pg))
        pg.mouse.click(800, 300); pg.keyboard.press('5'); pg.wait_for_timeout(500)
        kontrol(f'5 tuşu → Yer ({view_txt(pg)})', pg.evaluate('window.__smSim.getCamera()') == 'ground' and 'Yer' in view_txt(pg))
        pg.keyboard.press('1'); pg.wait_for_timeout(500)
        # ---- servo
        pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(400)
        pg.select_option('.fs-srv-ch', '9')
        pg.locator('.fs-srv-pwm').fill('1900'); pg.locator('.fs-srv-pwm').press('Enter')
        shot(pg, '03-servo-pop-idle.png', extra=330)
        pg.locator('.fs-srv-act').click()
        bekle(lambda: phase(pg) == 'listening', 10, 'dinleme')
        pg.wait_for_timeout(300)
        kontrol('dinleme: panel kapandı, "Dinleniyor"', pg.evaluate("document.querySelector('.fs-srv-pop').hidden && document.querySelector('.fs-srv-btn').textContent.trim() === 'Dinleniyor'"))
        shot(pg, '04-servo-listening.png', extra=40)
        pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(400)
        kontrol('dinlerken panel: Dinlemeyi durdur', pg.evaluate("document.querySelector('.fs-srv-act').textContent") == 'Dinlemeyi durdur')
        shot(pg, '05-servo-pop-listening.png', extra=330)
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
        kontrol('Esc paneli kapatır, uçuştan çıkmaz', pg.evaluate("document.querySelector('.fs-srv-pop').hidden && /#\\/fly\\/\\d+/.test(location.hash)"))
        pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(300); pg.locator('.fs-srv-act').click()
        bekle(lambda: phase(pg) == 'idle', 10, 'durdurma')
        pg.mouse.click(700, 250)
        for w, hh in ((1280, 800), (900, 700)):
            pg.set_viewport_size({'width': w, 'height': hh}); pg.wait_for_timeout(1500)
            tasma(pg, f'{w}')
            shot(pg, f'10-bar-{w}.png', extra=40)
            pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(400)
            tasma(pg, f'{w} servo paneli açık')
            shot(pg, f'11-servo-pop-{w}.png', extra=330)
            pg.keyboard.press('Escape'); pg.wait_for_timeout(200)
        shot(pg, '12-full-900.png', bar=False)
        # ---- İngilizce (çeviri)
        pg.set_viewport_size({'width': 1600, 'height': 900})
        pg.evaluate("localStorage.setItem('sm:lang', 'en')"); pg.reload(wait_until='domcontentloaded')
        pg.wait_for_selector('.fs-bar .fs-cam-ctl', timeout=240000); pg.wait_for_timeout(9000)
        pg.locator('.fs-view-btn').click(); pg.wait_for_timeout(400)
        en = pg.evaluate("[...document.querySelectorAll('.fs-view-item span')].map(x => x.textContent).join('|') + ' / ' + document.querySelector('.fs-srv-btn').textContent.trim()")
        kontrol(f'İngilizce: görünüm adları + Listen ({en})', 'Follow' in en and 'Ground' in en and 'Listen' in en)
        shot(pg, '13-en-view-menu.png')
        pg.keyboard.press('Escape'); pg.locator('.fs-srv-btn').click(); pg.wait_for_timeout(400)
        shot(pg, '14-en-servo-pop.png', extra=330)
        pg.keyboard.press('Escape')
        pg.evaluate("localStorage.setItem('sm:lang', 'tr')")
        s.post(f'{BASE}/api/fly/{fid}/stop', json={}, headers=H)
        pg.wait_for_timeout(1500)

        # ================= 2) kara aracı =================
        fid2, sid2, ss2 = ucus(pg, dr['id'])
        if pg.evaluate("document.querySelector('.fs-ops-btn').classList.contains('primary')"):
            pg.locator('.fs-ops-btn').click(); pg.wait_for_timeout(800)
        tasma(pg, 'rover 1600')
        shot(pg, '20-rover-bar-1600.png', extra=40)
        pg.set_viewport_size({'width': 900, 'height': 700}); pg.wait_for_timeout(1500)
        tasma(pg, 'rover 900')
        shot(pg, '21-rover-bar-900.png', extra=40)
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
