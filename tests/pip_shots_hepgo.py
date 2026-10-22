"""HEPGO Uçuş Simülatörü §22.4 — KAMERA PiP REGRESYONU (araç yerdeyken gimbal PiP'inin alt yarısı düz mavi olmamalı).
Playwright headless shell + SwiftShader; sahte kinematik (HEPGO_SITL=0); uygulama aynı süreçte. Araç pistte (yerde, DISARMED); ana görünüm serbest kamera
(kasabaya bakış), PiP = gimbal kamerası. Her (araç tipi × dpr × ön ayar × kamera türü) için PiP dikdörtgeni ekrandan kırpılır; ALT YARININ
alt yarısı (pipProbe: 8×4 ızgara) aynı kameranın 4× çözünürlüklü başvuru çizimiyle karşılaştırılır — eski hata (tek dörtgen su düzleminin derinliği
bozuk → su pistin/arazinin üstüne çiziliyordu) çözünürlüğe bağlıydı; ayrıca pipPose(): yakın düzlem kameranın yerden yüksekliğinden küçük olmalı.
Bilgi olarak kırpılan PiP'in alt yarısının "tek renk" payı da yazılır (eski hatada ≈ 1,00).
PIP_DSF = virgüllü dpr listesi (vars. 1,1.5,2) · PIP_PRESETS (vars. low,medium,high,ultra) · PIP_TYPES (vars. sabit_kanat,multirotor,rover) ·
PIP_CAMS (vars. day,thermal,night) · PIP_TIME dünya saati (day | dusk | night) · PIP_GIMBAL (vars. -10,-45,-90). Kareler /tmp/fixes-shots/pip-*.png (PIP_TAG önek).
Çalıştırma: ./.venv/bin/python -m tests.pip_shots_hepgo
"""
import io
import json
import os
import pathlib
import shutil
import socket
import sys
import threading
import time

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
PORT = int(os.environ.get('SHOT_PORT') or 8931)
DATA = f'/tmp/pip-shots-data-{PORT}'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE=os.environ.get('PIP_UDP') or '39980', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MAX_SESSIONS='6')
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/fixes-shots'); OUT.mkdir(parents=True, exist_ok=True)
TAG = os.environ.get('PIP_TAG', 'sonra')
lst = lambda k, d: [x for x in (os.environ.get(k) or d).split(',') if x]   # noqa: E731
DSFS = [float(x) for x in lst('PIP_DSF', '1,1.5,2')]
PRESETS = lst('PIP_PRESETS', 'low,medium,high,ultra')
TYPES = lst('PIP_TYPES', 'sabit_kanat,multirotor,rover')
CAMS = lst('PIP_CAMS', 'day,thermal,night')
GIMBALS = [float(x) for x in lst('PIP_GIMBAL', '-10,-45,-90')]
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

import requests  # noqa: E402
import uvicorn  # noqa: E402
from PIL import Image  # noqa: E402
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
WORLD = {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'mountain_height': 450, 'building_count': 120, 'tree_density': 0.45, 'water': 0.12,
         'time': os.environ.get('PIP_TIME') or 'day', 'wind_ms': 2, 'wind_dir': 300, 'runway_heading': 20, 'fog': 0.15}


def kontrol(ad, kosul, ek=''):
    print(('  ✓ ' if kosul else '  ✗ ') + ad + (f' — {ek}' if ek else ''), flush=True)
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


def kareler(pg, n=3):
    pg.evaluate(f'() => new Promise(r => {{ let k = 0; const off = window.__fsSim.addFrameHook(() => {{ if (++k >= {n}) {{ off(); r(); }} }}); }})')


def tek_renk(img):
    """Alt yarıda medyan renge (her kanal ±10) yakın piksel payı; 1 → düz renk."""
    w, h = img.size
    im = img.crop((int(w * 0.06), int(h * 0.55), int(w * 0.94), int(h * 0.88))).convert('RGB')
    px = list(getattr(im, 'get_flattened_data', im.getdata)())
    med = [sorted(p[i] for p in px)[len(px) // 2] for i in range(3)]
    return sum(1 for p in px if all(abs(p[i] - med[i]) <= 10 for i in range(3))) / max(1, len(px)), med


def pip_olc(pg, ad):
    kareler(pg, 4)
    r = pg.evaluate("""(() => { const S = window.__fsSim, c = S.canvas.getBoundingClientRect(), p = S.pipRect();
      return { x: c.left + p.x, y: c.top + p.y, w: p.w, h: p.h }; })()""")
    png = pg.screenshot(clip={'x': r['x'] + 3, 'y': r['y'] + 3, 'width': r['w'] - 6, 'height': r['h'] - 6})
    img = Image.open(io.BytesIO(png))
    oran, med = tek_renk(img)
    poz = pg.evaluate('window.__fsSim.pipPose()')
    pr = pg.evaluate('window.__fsSim.pipProbe()')
    img.save(OUT / f"pip-{TAG}-{ad}{'' if WORLD['time'] == 'day' else '-' + WORLD['time']}.png")
    yuk = poz['z'] - poz['ground']
    # PiP hedefi ↔ aynı kameranın 4× başvuru çizimi: alt yarıdaki 8×4 ızgaranın ≥ %75'i aynı yüzey (kanal farkı ≤ 40; ince çizgiler/kenarlar
    # çözünürlükle farklı örneklenebilir — eski hatada alt yarının tamamı su/gök rengiydi)
    n = len(pr['pip']) if pr else 1
    ayni = sum(1 for a, b in zip(pr['pip'], pr['ref']) if max(abs(x - y) for x, y in zip(a, b)) <= 40) if pr else 0
    kontrol(f'{ad}: PiP alt yarısı başvuru çizimiyle aynı ({ayni}/{n}; hedef {pr and pr["size"]}; tek renk payı {oran:.2f})', ayni >= 0.75 * n, json.dumps(pr)[:600])
    kontrol(f'{ad}: yakın düzlem < kamera yüksekliği', yuk >= poz['near'] - 0.01, f"yükseklik {yuk:.2f} m, near {poz['near']}, kaynak {poz['src']}")
    return oran


def oturum(tip):
    w = {**WORLD, 'launch': {'method': 'wheels'}} if tip == 'sabit_kanat' else dict(WORLD)
    r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'sitl', 'type': tip, 'center_id': c['id'], 'rec': {'bin': False}, 'world': w})
    assert r.status_code == 201, r.text
    sid = r.json()['id']
    bekle(lambda: flightsim.MANAGER.sessions[sid].state == 'HAZIR', 120, f'{tip} HAZIR')
    return sid


def ac(ctx, sid):
    pg = ctx.new_page()
    pg.set_default_timeout(300000)
    pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
    pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(2000)
    pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
    pg.wait_for_timeout(6000)
    if not pg.locator('.fs-stage').count():   # liste sayfası geç bitip görünümü ezdiyse yeniden yönlendir
        pg.evaluate("location.hash = '#/drone/sim'"); pg.wait_for_timeout(1500)
        pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
    pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera && window.__fsSim.pipPose && document.querySelector(".fs-stage .fs-pip")', timeout=240000)
    pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
    pg.wait_for_timeout(8000)   # giriş sekansı
    pg.evaluate('window.__fsSim.endIntro?.()')
    return pg


def bak(pg):
    """Ana görünüm: serbest kamera kasabaya (PiP = gimbal)."""
    pg.evaluate("""(() => { const S = window.__fsSim, tw = (S.fxInfo().townsAt || [[600, 300]])[0], d = Math.hypot(tw[0], tw[1]) || 1;
      const x = tw[0] - tw[0] / d * 230, y = tw[1] - tw[1] / d * 230, z = S.terrainHeight(x, y) + 45, tz = S.terrainHeight(tw[0], tw[1]) + 6;
      S.setFreeView(x, y, z, -Math.atan2(tw[0] - x, tw[1] - y) * 180 / Math.PI, Math.atan2(tz - z, 230) * 180 / Math.PI); S.setPip(true); })()""")


try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        for tip in TYPES:
            sid = oturum(tip)
            for dsf in DSFS:
                ctx = b.new_context(viewport={'width': 1280, 'height': 720}, locale='tr-TR', device_scale_factor=dsf)
                ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
                ctx.add_init_script("try { localStorage.setItem('fs.gfx', JSON.stringify({ preset: 'high' })); localStorage.setItem('fs.rec.on', '0'); } catch (e) {}")
                pg = ac(ctx, sid)
                def on_ayar(pre):
                    pg.evaluate(f"(() => {{ const S = window.__fsSim; S.setGraphics(S.resolveGfx({{ preset: '{pre}' }}, S.gfxCaps)); }})()")
                    pg.wait_for_timeout(1500)
                    pg.wait_for_function('() => window.__fsSim && window.__fsSim.pipPose && window.__fsSim.getCamera', timeout=240000)   # ön ayar tuval kenar yumuşatmasını değiştirirse 3B yeniden kurulur
                    pg.wait_for_timeout(2500)
                    pg.evaluate('window.__fsSim.endIntro?.()')
                    bak(pg)
                    for cam in CAMS:
                        pg.evaluate(f"window.__fsSim.setCamType('{cam}')")
                        for gb in GIMBALS:
                            pg.evaluate(f'window.__fsSim.setGimbal({gb} - window.__fsSim.getGimbal())')
                            pip_olc(pg, f'{tip}-dpr{dsf}-{pre}-{cam}-g{int(gb)}')
                    print('  poz:', json.dumps(pg.evaluate('window.__fsSim.pipPose()')), flush=True)
                for pre in PRESETS:
                    try:
                        on_ayar(pre)
                    except Exception as e:   # noqa: BLE001 — yazılım GL (SwiftShader) büyük tamponda bağlamı kaybedip sayfayı yeniden yükleyebilir: bir kez yeniden dene
                        if 'context was destroyed' not in str(e) and 'navigation' not in str(e):
                            raise
                        print('  (sayfa yeniden yüklendi; tekrar)', pre, flush=True)
                        pg.wait_for_timeout(5000)
                        pg.wait_for_function('() => window.__fsSim && window.__fsSim.pipPose && window.__fsSim.getCamera', timeout=240000)
                        pg.wait_for_timeout(8000)
                        on_ayar(pre)
                if dsf == DSFS[0]:
                    pg.screenshot(path=str(OUT / f'pip-{TAG}-{tip}-tam.png'))
                ctx.close()
            s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        b.close()
except Exception:
    import traceback
    traceback.print_exc()
    hatalar.append('İSTİSNA')
finally:
    server.should_exit = True
print('HATALAR:' if hatalar else 'hata yok', *hatalar, sep='\n  ')
sys.exit(1 if hatalar else 0)
