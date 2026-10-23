"""Uçuş Simülatörü — multikopter gimbal kamerası TİTREME regresyonu (HEPGO + SIMUMAV ortak 3B: static/js/modules/flightsim3d.js), gerçek tarayıcı.

Kök neden: gerçek ArduCopter SITL askıda gövde yönelimi ~16 Hz'de ±1,5–2° salınır (tests/data/sitl_copter_hover_att.json); gimbal kamerası gövdeye
sabitti → görüntü her 1–2 karede iki poz arasında gidip geliyordu. Düzeltme: araç kamerası yönelimi gövdenin alçak geçiren süzgeci (stabStep).
Bu test kaydı 50 Hz tele olarak gerçek createFlightSim3D'ye verir (gimbal −49°, PiP açık — kullanıcı videosundaki düzen), her render karesinde
kameranın dünya pozunu (cameraPose) ve gövde pozunu (getBodyPose) toplar: asılı dronda kamera kare→kare açı değişimi gövdeninkinden çok küçük olmalı.
Sanal saat (rAF + performance.now) ile 60 fps belirlenimci. Sunucu gerekmez (statik dosya + Playwright yolu). Çalıştırma: .venv/bin/python -m tests.flightsim_camstab_e2e  [kök dizin (ör. eski sürüm dışa aktarımı)]
"""
import functools
import http.server
import json
import math
import os
import socketserver
import sys
import threading

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
from playwright.sync_api import sync_playwright  # noqa: E402

KOK = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'sitl_copter_hover_att.json')
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']


class _Sessiz(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Sunucu(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


srv = _Sunucu(('127.0.0.1', 0), functools.partial(_Sessiz, directory=KOK))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{srv.server_address[1]}'

SAYFA = """<!doctype html><html><body style="margin:0;background:#000"><div id="m" style="position:absolute;inset:0"></div>
<script type="module">
// Belirlenimci saat: yazılım WebGL'de (swiftshader) kare saniyeler sürer → rAF ve performance.now sanal saate bağlanır; her adımda o ana dek
// gelmiş 20 ms'lik ATTITUDE kareleri verilir ve kare 1000/FPS ms sanal süreyle çizilir (gerçek tarayıcıdaki 60 fps akışın aynısı).
const realNow = performance.now.bind(performance);
let fake = null;
performance.now = () => (fake ?? realNow());
let rafQ = [], manual = false;   // kurulum gerçek saatle (kurulum rAF bekler); ölçüm başlayınca kareler yalnız step() ile
window.requestAnimationFrame = cb => { if (manual) { rafQ.push(cb); return 0; } return setTimeout(() => (manual ? rafQ.push(cb) : cb(realNow())), 16); };
window.cancelAnimationFrame = () => {};
const M = await import('/static/js/modules/flightsim3d.js');
const F = (await (await fetch('/fixture.json')).json()).f;
const sim = await M.createFlightSim3D(document.getElementById('m'), { mode: 'procedural', seed: 3, tree_density: 0, building_count: 0, runway: true },
  { type: 'multirotor', camera: 'fpv' });
window.sim = sim;
let k = 0, t0 = null;
const b0 = F[0][0];
window.step = (n, fps) => {
  if (t0 == null) { manual = true; t0 = realNow() + 50; }
  const out = [];
  for (let i = 0; i < n; i++) {
    fake = (fake ?? t0) + 1000 / fps;
    const el = fake - t0;
    while (k * 20 <= el) {   // kayıt döngüsel (tbm sürekli artar)
      const f = F[k % F.length], tbm = b0 + k * 20; k++;
      sim.setTelemetry({ x: 0, y: 0, alt_rel: 137, roll: f[1], pitch: f[2], yaw: f[3], rs: f[4], ps: f[5], ys: f[6], tbm, tbm_pos: tbm, ve: 0, vn: 0, vd: 0, armed: true, throttle: 36, mode: 'ALT_HOLD' });
    }
    const q = rafQ; rafQ = [];
    q.forEach(cb => { try { cb(fake); } catch (e) { console.error(e); } });
    out.push({ t: fake, c: sim.cameraPose(), b: sim.getBodyPose() });
  }
  return out;
};
window.ready = true;
</script></body></html>"""


def aci(a, b):
    d = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (math.hypot(*a) * math.hypot(*b))))
    return math.degrees(math.acos(d))


def govde_ileri(b):   # ENU gövde burnu (+Y): Euler 'ZXY' (pitch, roll, −yaw) → ileri vektör (roll'dan bağımsız) + sağ kanat
    p, r, y = b['pitch'], b['roll'], b['yaw']
    fwd = (math.sin(y) * math.cos(p), math.cos(y) * math.cos(p), math.sin(p))
    return fwd, (math.cos(r), 0.0, math.sin(r))


hatalar = []
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=ARGS)
    pg = br.new_page(viewport={'width': 400, 'height': 225})
    pg.on('pageerror', lambda e: hatalar.append(str(e)[:300]))
    pg.on('console', lambda m: hatalar.append(m.text[:300]) if m.type == 'error' else None)
    pg.route(BASE + '/harness.html', lambda r: r.fulfill(status=200, content_type='text/html', body=SAYFA))
    pg.route(BASE + '/fixture.json', lambda r: r.fulfill(status=200, content_type='application/json', body=open(FIX).read()))
    pg.goto(BASE + '/harness.html')
    pg.wait_for_function('window.ready === true', timeout=180000)
    pg.evaluate("() => { sim.setCamera('fpv'); sim.setGimbal(-49); sim.setPip(true); }")
    pg.evaluate('() => step(90, 60)')   # 1,5 sn: enterpolasyon tamponu oturur
    K = pg.evaluate('() => step(120, 60)')
    br.close()

cam = [((k['c']['fx'], k['c']['fy'], k['c']['fz']), (k['c']['ux'], k['c']['uy'], k['c']['uz'])) for k in K]
gov = [govde_ileri(k['b']) for k in K]
dts = [K[i]['t'] - K[i - 1]['t'] for i in range(1, len(K))]
c_step = [max(aci(cam[i][0], cam[i - 1][0]), aci(cam[i][1], cam[i - 1][1])) for i in range(1, len(cam))]
g_step = [max(aci(gov[i][0], gov[i - 1][0]), aci(gov[i][1], gov[i - 1][1])) for i in range(1, len(gov))]
ort = lambda x: sum(x) / len(x)  # noqa: E731
fps = 1000 / ort(dts)
print(f'kök: {KOK}\nkare: {len(K)} · sanal {fps:.0f} fps')
print(f'gövde (SITL) kare→kare: ort {ort(g_step):.3f}° · en çok {max(g_step):.3f}°')
print(f'gimbal kamera kare→kare: ort {ort(c_step):.3f}° · en çok {max(c_step):.3f}°')
oran = ort(g_step) / max(1e-6, ort(c_step))
print(f'sönüm: {oran:.1f}×')
esik = 8.0   # 60 fps sanal saat: birim testteki (tests/test_flightsim_camstab.mjs) ≥ 8× ile aynı
if hatalar:
    print('sayfa hataları:', hatalar)
ok = not hatalar and ort(g_step) > 0.5 and oran >= esik and ort(c_step) < 0.15
print('SONUÇ:', 'GEÇTİ' if ok else 'KALDI')
sys.exit(0 if ok else 1)
