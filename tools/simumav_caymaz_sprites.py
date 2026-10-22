#!/opt/hepgo/fabrika-yonetim/.venv/bin/python
"""SIMUMAV hareketli arka planları için CAYMAZ hareket karesi atlası (Canvas2D; çalışma anında WebGL YOK).

Kaynak: static/models/caymaz-sim.glb (HEPGO'nun kendi CAYMAZ V3 modeli; dış varlık değil). Headless Chromium + three.js ile
FRAMES yörünge açısından (kamera yükselişi ELEV°) saydam zeminli kareler çizilir, tek atlas (COLS×ROWS) WebP olarak yazılır:
static/simumav/app/ui/backdrop/caymaz_atlas.webp. Kare i: kameranın uçağın etrafındaki açısı = i × 360/FRAMES (0 = önden, saat yönü).
Çalıştır: tools/simumav_caymaz_sprites.py
"""
import base64, functools, http.server, io, os, pathlib, threading

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'static/simumav/app/ui/backdrop/caymaz_atlas.webp'
FRAMES, COLS, FW, FH, ELEV = 32, 8, 320, 200, 14
os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

PAGE = f"""<!doctype html><html><body style="margin:0;background:transparent">
<script type="importmap">{{"imports":{{"three":"/vendor/three/three.module.min.js"}}}}</script>
<script type="module">
import * as T from 'three';
import {{ GLTFLoader }} from '/vendor/three/GLTFLoader.js';
const FW = {FW}, FH = {FH}, N = {FRAMES}, ELEV = {ELEV} * Math.PI / 180;
const r = new T.WebGLRenderer({{ antialias: true, alpha: true, preserveDrawingBuffer: true }});
r.setPixelRatio(2); r.setSize(FW, FH); r.setClearColor(0x000000, 0); r.outputColorSpace = T.SRGBColorSpace; r.toneMapping = T.ACESFilmicToneMapping; r.toneMappingExposure = 1.05;
document.body.append(r.domElement);
const sc = new T.Scene();
sc.add(new T.HemisphereLight(0xcfe3ff, 0x2a3140, 1.5));
const sun = new T.DirectionalLight(0xfff1dc, 2.6); sun.position.set(3, 6, 4); sc.add(sun);
const rim = new T.DirectionalLight(0x8fc8ff, 1.4); rim.position.set(-4, 2, -5); sc.add(rim);
const cam = new T.PerspectiveCamera(26, FW / FH, 0.1, 100);
const g = await new GLTFLoader().loadAsync('/models/caymaz-sim.glb');
const m = g.scene; const p = m.getObjectByName('prop'); if (p) p.visible = false;
m.traverse(o => {{ if (o.isMesh) {{ o.material = o.material.clone(); o.material.envMapIntensity = 0; }} }});
const box = new T.Box3().setFromObject(m), c = box.getCenter(new T.Vector3()); m.position.sub(c); sc.add(m);
const out = document.createElement('canvas'); out.width = FW * 2 * {COLS}; out.height = FH * 2 * Math.ceil(N / {COLS});
const o2 = out.getContext('2d');
const R = 6.4;
for (let i = 0; i < N; i++) {{
  const a = i / N * Math.PI * 2;   // 0: kamera burnun önünde (+Z)
  cam.position.set(Math.sin(a) * Math.cos(ELEV) * R, Math.sin(ELEV) * R, Math.cos(a) * Math.cos(ELEV) * R); cam.lookAt(0, 0, 0);
  r.render(sc, cam);
  o2.drawImage(r.domElement, (i % {COLS}) * FW * 2, Math.floor(i / {COLS}) * FH * 2);
}}
window.__atlas = out.toDataURL('image/png');
</script></body></html>"""


def main():
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Q, directory=str(ROOT / 'static'))
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=EXE, args=ARGS)
            pg = br.new_page()
            pg.route(base + '/__sprites.html', lambda rt: rt.fulfill(status=200, content_type='text/html', body=PAGE))
            pg.on('console', lambda msg: print('[konsol]', msg.text))
            pg.on('pageerror', lambda e: print('[hata]', e))
            pg.goto(base + '/__sprites.html')
            pg.wait_for_function('window.__atlas', timeout=120000)
            data = pg.evaluate('window.__atlas')
            br.close()
    finally:
        srv.shutdown()
    img = Image.open(io.BytesIO(base64.b64decode(data.split(',', 1)[1]))).convert('RGBA')
    img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, 'WEBP', quality=82, method=6)
    print(OUT, img.size, OUT.stat().st_size, 'bayt')


if __name__ == '__main__':
    main()
