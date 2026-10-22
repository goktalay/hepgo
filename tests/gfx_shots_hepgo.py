"""HEPGO Uçuş Simülatörü §43 — GRAFİK KALİTE AYARLARI: görsel karşılaştırma + göreli ölçüm (Playwright headless shell + SwiftShader; sahte kinematik).
Aynı sahne (prosedürel dünya, sabit serbest kamera) Düşük / Orta / Yüksek / Ultra ön ayarlarıyla; her ön ayarda yazılım WebGL kare hızı (render edilen kare /
sn, frame hook ile), karenin çizim çağrısı / üçgen sayısı, tampon çözünürlüğü, son işlem hattı bilgisi yazılır. Ayrıca "Grafik ▾" menüsü (ön ayar + canlı FPS +
Özel kaydırıcıları) ve köşe FPS sayacı görüntüsü. Görüntüler /tmp/gfx-shots/hepgo-*.png. SwiftShader yavaştır: FPS'ler yalnız GÖRELİ yorumlanmalı.
GFX_ONLY = virgüllü ön ayar listesi (ör. 'low,ultra'); GFX_VIEW = virgüllü bakış listesi: drone (vars.), town (vars.), valley, overview, ground; GFX_VARIANTS teşhis.
Çalıştırma: ./.venv/bin/python -m tests.gfx_shots_hepgo
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
PORT = int(os.environ.get('SHOT_PORT') or 8893)
DATA = f'/tmp/gfx-shots-data-{PORT}'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  HEPGO_SITL='0', SIM_UDP_BASE=os.environ.get('GFX_UDP') or '39950', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/gfx-shots'); OUT.mkdir(parents=True, exist_ok=True)
ONLY = [x for x in (os.environ.get('GFX_ONLY') or 'low,medium,high,ultra').split(',') if x]
VIEWS_ON = (os.environ.get('GFX_VIEW') or 'drone,town').split(',')
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
        time.sleep(0.25)
    hatalar.append(f'{ad}: {sec} sn içinde olmadı'); return False


def shot(pg, ad):
    pg.screenshot(path=str(OUT / f'hepgo-{ad}.png'))
    print('  kare', f'hepgo-{ad}.png', flush=True)


def kareler(pg, n=3):
    """n kare RENDER edilene dek bekle (frame hook; kare sınırı atlanan rAF'leri saymaz)."""
    pg.evaluate(f'() => new Promise(r => {{ let k = 0; const off = window.__fsSim.addFrameHook(() => {{ if (++k >= {n}) {{ off(); r(); }} }}); }})')


def olc(pg, ms=6000):
    """Render edilen kare/sn (frame hook) + karenin çizim çağrısı/üçgen + uygulanan ayar."""
    r = pg.evaluate(f'''() => new Promise(res => {{ const S = window.__fsSim; let n = 0; const t0 = performance.now();
      const off = S.addFrameHook(() => {{ n++; }});
      setTimeout(() => {{ off(); const st = S.gfxStats(), g = S.getGraphics(); res({{ fps: +(n * 1000 / (performance.now() - t0)).toFixed(2), calls: st.calls, tris: st.tris,
        buf: g.buffer, pr: g.pr, samples: g.pipe.samples, post: g.pipe.active && g.post, ao: g.pipe.ao, bloom: g.pipe.bloom, shadow: g.shadow, nativeAA: g.nativeAA, level: g.level, preset: g.preset,
        fog: S.fxInfo().fog, trees: S.fxInfo().treeChunks, treeHi: S.fxInfo().treeHi }}); }}, {ms}); }})''')
    return r


def bak(pg, x, y, dz, tx, ty, tdz=0):
    pg.evaluate(f"""(() => {{ const S = window.__fsSim, h = (a, b) => S.terrainHeight(a, b);
      const z = Math.max(h({x}, {y}), S.waterZ > -1e9 ? S.waterZ : -1e9) + {dz}, tz = h({tx}, {ty}) + {tdz}, dx = {tx} - ({x}), dy = {ty} - ({y});
      S.setFreeView({x}, {y}, z, -Math.atan2(dx, dy) * 180 / Math.PI, Math.atan2(tz - z, Math.hypot(dx, dy)) * 180 / Math.PI); }})()""")


def menu_ac(pg):
    if not pg.locator('.fs-gfx-menu:not([hidden])').count():
        pg.locator('.fs-gfx-btn').click(); pg.wait_for_timeout(300)


def onayar(pg, k):
    menu_ac(pg)
    pg.locator(f'.fs-gfx-menu .fs-gfx-seg button[data-gfx="{k}"]').click()
    pg.locator('.fs-gfx-menu .fs-gfx-h button').click()   # menüyü kapat (kareyi örtmesin)
    pg.wait_for_timeout(1800 if k in ('low', 'medium') else 1200)   # arazi/bitki ayrıntısı değişince dünya 700 ms sonra yeniden kurulur
    kareler(pg, 3)


WORLD = {'mode': 'procedural', 'seed': 11, 'size_m': 4000, 'mountain_height': 450, 'building_count': 120, 'tree_density': 0.45}
tablo = []
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = b.new_context(viewport={'width': 1280, 'height': 720}, locale='tr-TR', device_scale_factor=float(os.environ.get('GFX_DSF') or 1))
        ctx.add_cookies([{'name': auth.COOKIE, 'value': s.cookies.get(auth.COOKIE), 'url': BASE}])
        # karşılaştırma elle ön ayarla (uyarlamalı kip kapalı); ekran kaydı kapalı (kayıt tabanı piksel oranını ≥ 1 tutar — ayrı denetlenir)
        ctx.add_init_script("try { localStorage.setItem('fs.gfx', JSON.stringify({ preset: 'high' })); localStorage.setItem('fs.rec.on', '0'); } catch (e) {}")
        pg = ctx.new_page()
        pg.set_default_timeout(300000)
        pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
        pg.on('console', lambda m: hatalar.append(f'KONSOL: {m.text[:600]}') if m.type == 'error' and 'GPU stall' not in m.text and 'Failed to load resource' not in m.text else None)
        pg.goto(f'{BASE}/#/drone/sim', wait_until='domcontentloaded'); pg.wait_for_timeout(2500)
        body = {'mode': 'sitl', 'type': 'sabit_kanat', 'center_id': c['id'], 'rec': {'bin': False},
                'world': {**WORLD, 'time': 'day', 'wind_ms': 4, 'wind_dir': 300, 'runway_heading': 20, 'fog': 0.15, 'launch': {'method': 'wheels'}}}
        r = s.post(f'{BASE}/api/drone/sim/sessions', json=body)
        assert r.status_code == 201, r.text
        sid = r.json()['id']
        ss = flightsim.MANAGER.sessions[sid]
        bekle(lambda: ss.state == 'HAZIR', 120, 'HAZIR')
        pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
        pg.wait_for_timeout(6000)
        if not pg.locator('.fs-stage').count():   # liste sayfası geç bitip görünümü ezdiyse yeniden yönlendir
            pg.evaluate("location.hash = '#/drone/sim'"); pg.wait_for_timeout(1500)
            pg.evaluate(f"location.hash = '#/drone/sim/{sid}?netsim=delay0'")
        pg.wait_for_function('() => window.__fsSim && window.__fsSim.getCamera && document.querySelector(".fs-gfx-btn")', timeout=240000)
        pg.evaluate("[...document.querySelectorAll('.modal .btn')].find(b => /Reddet/.test(b.textContent))?.click()")
        pg.wait_for_timeout(8000)   # giriş sekansı
        print('  yetenekler:', pg.evaluate('window.__fsSim.gfxCaps'), flush=True)
        print('  otomatik algılama:', pg.evaluate("JSON.parse(localStorage.getItem('fs.gfx'))"), flush=True)
        print('  alt bant yüksekliği (Grafik düğmesiyle / düğmesiz):', pg.evaluate("(() => { const b = document.querySelector('.fs-bar'), g = document.querySelector('.fs-gfx'); const h1 = b.offsetHeight; g.style.display = 'none'; const h2 = b.offsetHeight; g.style.display = ''; return [h1, h2]; })()"), flush=True)
        tw = (pg.evaluate('window.__fsSim.fxInfo().townsAt') or [[600, 300]])[0]
        ax, ay = tw[0] * 0.55, tw[1] * 0.55
        import math
        d = math.hypot(*tw) or 1
        VIEWS = {'overview': (-300, -700, 160, 400, 1200, 0), 'valley': (ax - 140, ay - 140, 55, tw[0], tw[1], 10), 'ground': (-30, -80, 6, 120, 500, 2),
                 'town': (tw[0] - tw[0] / d * 230, tw[1] - tw[1] / d * 230, 45, tw[0], tw[1], 6),   # kasabaya 230 m'den
                 'drone': (-14, -26, 5, 0, 0, 1.2)}   # pistteki uçak (gölge, kenar yumuşatma)
        for v in json.loads(os.environ.get('GFX_VARIANTS') or '[]'):   # teşhis: [{name, base, custom}] özel ince ayarlar
            pg.evaluate(f"(() => {{ const S = window.__fsSim; S.setGraphics(S.resolveGfx({{ preset: 'custom', base: {json.dumps(v['base'])}, custom: {json.dumps(v.get('custom') or {})} }}, S.gfxCaps)); }})()")
            pg.wait_for_timeout(1500)
            for vw in VIEWS_ON:
                bak(pg, *VIEWS[vw]); kareler(pg, 3); shot(pg, f"{vw}-{v['name']}")
        for k in ONLY:
            onayar(pg, k)
            for vw in VIEWS_ON:
                bak(pg, *VIEWS[vw]); kareler(pg, 3)
                shot(pg, f'{vw}-{k}')
            m = olc(pg)
            m['preset'] = k
            tablo.append(m)
            print(f'  [{k}]', json.dumps(m, ensure_ascii=False), flush=True)
        # menü: Ultra'da ayar paneli + Özel bölümü açık
        menu_ac(pg)
        pg.evaluate("document.querySelector('.fs-gfx-menu details').open = true")
        pg.wait_for_timeout(1500)
        shot(pg, 'menu')
        # Özel: gölge kapalı + görüş 0,5 (canlı uygulama, yeniden başlatma yok)
        pg.locator('.fs-gfx-menu select[data-k="shadow"]').select_option('0'); pg.wait_for_timeout(600)
        pg.evaluate("(() => { const i = document.querySelector('.fs-gfx-menu input[data-k=fog]'); i.value = '0.5'; i.dispatchEvent(new Event('change')); })()")
        pg.wait_for_timeout(800)
        print('  özel:', pg.evaluate("(() => { const g = window.__fsSim.getGraphics(); return { preset: g.preset, level: g.level, shadow: g.shadow, fog: g.fog, sceneFog: window.__fsSim.fxInfo().fog, pref: JSON.parse(localStorage.getItem('fs.gfx')) }; })()"), flush=True)
        shot(pg, 'menu-custom')
        # köşe FPS sayacı + Otomatik
        pg.locator('.fs-gfx-menu .fs-gfx-chk').nth(1).locator('input').check()
        pg.locator('.fs-gfx-menu .fs-gfx-seg button[data-gfx="auto"]').click(); pg.wait_for_timeout(2500)
        pg.locator('.fs-gfx-menu .fs-gfx-h button').click(); pg.wait_for_timeout(1500); kareler(pg, 2)
        print('  otomatik:', pg.evaluate("(() => { const g = window.__fsSim.getGraphics(); return { preset: g.preset, level: g.level, pr: g.pr }; })()"), flush=True)
        shot(pg, 'auto-counter')
        s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
        b.close()
except Exception:
    try:
        pg.screenshot(path=str(OUT / 'hepgo-hata.png')); print('  hash:', pg.evaluate('location.hash'), 'sim:', pg.evaluate('!!window.__fsSim'), 'stage:', pg.locator('.fs-stage').count(), flush=True)
    except Exception:   # noqa: BLE001
        pass
    import traceback
    traceback.print_exc()
    hatalar.append('İSTİSNA')
finally:
    server.should_exit = True
print('\n| Ön ayar | yazılım GL kare/sn | çizim çağrısı | üçgen | tampon | MSAA | son işlem | gölge |')
print('|---|---|---|---|---|---|---|---|')
for m in tablo:
    print(f"| {m['preset']} | {m['fps']} | {m['calls']} | {m['tris']} | {m['buf'][0]}×{m['buf'][1]} @{m['pr']} | {m['samples']}{' (tuval)' if m['nativeAA'] and not m['post'] else ''} | {'AO ' + str(m['ao']) + ' · bloom ' + str(m['bloom']) if m['post'] else '—'} | {m['shadow'] or 'yok'} |")
print('HATALAR:' if hatalar else 'hata yok', *hatalar, sep='\n  ')
