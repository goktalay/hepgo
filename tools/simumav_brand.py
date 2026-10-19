#!/opt/hepgo/fabrika-yonetim/.venv/bin/python
"""SIMUMAV marka çıktıları: SVG → PNG (32/64/180/512), og.png 1200×630, favicon.ico, hesap servisi ikonları.
Playwright headless shell (SwiftShader) ile SVG'yi kırparak üretir; favicon Pillow ile PNG'den.
Kullanım: tools/simumav_brand.py  (depo kökünden ya da herhangi yerden)"""
import os, pathlib, shutil
os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
from playwright.sync_api import sync_playwright  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRAND = ROOT / 'static/simumav/brand'
MT_IMG = ROOT / 'central/sshmaster_server/static/mt/img'
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']

OG_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:1200px;height:630px;overflow:hidden;background:#05070f;font-family:Inter,'Segoe UI',Roboto,'DejaVu Sans',Arial,sans-serif}
.bg{position:absolute;inset:0;background:radial-gradient(ellipse 70% 60% at 70% 40%,#13244f 0%,#070b16 55%,#03050a 100%)}
.grid{position:absolute;left:-10%;right:-10%;bottom:0;height:46%;background:
 repeating-linear-gradient(90deg,rgba(25,230,210,.18) 0 1px,transparent 1px 60px),
 repeating-linear-gradient(0deg,rgba(25,230,210,.14) 0 1px,transparent 1px 40px);
 transform:perspective(600px) rotateX(62deg);transform-origin:50% 100%;mask-image:linear-gradient(to top,#000 20%,transparent)}
.hz{position:absolute;left:0;right:0;top:78%;height:2px;background:linear-gradient(90deg,transparent,#19e6d2 40%,#19e6d2 60%,transparent);box-shadow:0 0 24px #19e6d2}
.logo{position:absolute;left:84px;top:150px;width:300px;height:300px;}.logo svg{width:300px;height:300px;filter:drop-shadow(0 20px 50px rgba(25,230,210,.35))}
.t{position:absolute;left:430px;top:176px;color:#fff}
.t h1{margin:0;font-size:108px;letter-spacing:12px;font-weight:800;background:linear-gradient(90deg,#19e6d2,#ffb347);-webkit-background-clip:text;background-clip:text;color:transparent;line-height:1}
.t p{margin:22px 0 0;font-size:34px;color:#cfe3ff;letter-spacing:1px}
.t small{display:block;margin-top:26px;font-size:24px;color:#8fb3d9}
.streak{position:absolute;height:6px;border-radius:3px;background:linear-gradient(90deg,transparent,#ffb347)}
</style></head><body>
<div class="bg"></div><div class="grid"></div><div class="hz"></div>
<div class="streak" style="left:30px;top:220px;width:120px"></div>
<div class="streak" style="left:60px;top:260px;width:80px;height:4px"></div>
<div class="logo">__LOGO__</div>
<div class="t"><h1>SIMUMAV</h1><p>Gerçek dünya, gerçek fizik — dron simülasyonu</p><small>simumav.com · ArduPilot SITL · Google 3B · Mission Planner</small></div>
</body></html>"""


def main():
    svg = (BRAND / 'simumav.svg').read_text(encoding='utf-8')
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=ARGS)
        pg = b.new_page(viewport={'width': 1200, 'height': 630}, device_scale_factor=1)
        # ikon PNG'leri: SVG'yi tam boy gömülü sayfada çiz, saydam arka plan
        for size in (32, 64, 180, 512):
            pg.set_viewport_size({'width': size, 'height': size})
            pg.set_content(f'<!doctype html><html><body style="margin:0;background:transparent">{svg.replace("<svg ", f"<svg width={size} height={size} ", 1)}</body></html>')
            pg.screenshot(path=str(BRAND / f'icon-{size}.png'), omit_background=True, clip={'x': 0, 'y': 0, 'width': size, 'height': size})
        # og görseli
        pg.set_viewport_size({'width': 1200, 'height': 630})
        pg.set_content(OG_HTML.replace('__LOGO__', svg))
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(BRAND / 'og.png'), clip={'x': 0, 'y': 0, 'width': 1200, 'height': 630})
        b.close()
    # favicon.ico: 16/32/48 (Pillow)
    im = Image.open(BRAND / 'icon-512.png').convert('RGBA')
    im.save(BRAND / 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])
    # hesap servisi (mastertool.download › Oyunlar) ikon kalıbı: static/mt/img/<icon>.svg | .png (128) | -512.png
    MT_IMG.mkdir(parents=True, exist_ok=True)
    shutil.copy(BRAND / 'simumav.svg', MT_IMG / 'simumav.svg')
    im.resize((128, 128), Image.LANCZOS).save(MT_IMG / 'simumav.png')
    shutil.copy(BRAND / 'icon-512.png', MT_IMG / 'simumav-512.png')
    for f in sorted(BRAND.glob('*.png')) + [BRAND / 'favicon.ico'] + sorted(MT_IMG.glob('simumav*')):
        print(f.relative_to(ROOT), f.stat().st_size)


if __name__ == '__main__':
    main()
