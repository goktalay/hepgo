"""Uygulama ikonu (kopru.ico) ve MSIX görselleri (Assets/*.png) üretir. Kaynak: static/img/hepgo-mark.png.
Çalıştırma: python packaging/make_assets.py (bridge/dron_koprusu dizininden)."""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
APP = HERE.parent
SRC = APP.parent.parent / 'static' / 'img' / 'hepgo-mark.png'
src = Image.open(SRC).convert('RGBA')


def square(size, pad=0.12):
    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    inner = int(size * (1 - 2 * pad))
    im = src.copy()
    im.thumbnail((inner, inner), Image.LANCZOS)
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
    return canvas


def wide(w, h):
    canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    im = src.copy()
    im.thumbnail((int(h * 0.8), int(h * 0.8)), Image.LANCZOS)
    canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
    return canvas


square(256, 0.02).save(APP / 'kopru.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
assets = HERE / 'layout' / 'Assets'
assets.mkdir(parents=True, exist_ok=True)
for name, size in [('Square44x44Logo.png', 44), ('Square44x44Logo.targetsize-256_altform-unplated.png', 256),
                   ('Square150x150Logo.png', 150), ('StoreLogo.png', 50), ('Square310x310Logo.png', 310)]:
    square(size, 0.0 if 'unplated' in name else 0.12).save(assets / name)
wide(310, 150).save(assets / 'Wide310x150Logo.png')
wide(620, 300).save(assets / 'SplashScreen.png')
print('ikon ve görseller üretildi:', sorted(p.name for p in assets.iterdir()))
