#!/opt/hepgo/fabrika-yonetim/.venv/bin/python
"""MASTERWORLD hesap servisi simgeleri: static/mt/img/masterworld.svg → masterworld.png (128) + masterworld-512.png (saydam).
Playwright headless shell ile SVG tam boy çizilir (tools/simumav_brand.py kalıbı); 128 px Pillow ile 512'den küçültülür.
Kullanım: tools/masterworld_brand.py"""
import os
import pathlib
os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
from playwright.sync_api import sync_playwright  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
MT_IMG = ROOT / 'central/sshmaster_server/static/mt/img'
EXE = os.environ.get('CHROMIUM_PATH') or os.path.expanduser(
    '~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')


def main():
    svg = (MT_IMG / 'masterworld.svg').read_text(encoding='utf-8')
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE)
        pg = b.new_page(viewport={'width': 512, 'height': 512}, device_scale_factor=1)
        pg.set_content(f'<!doctype html><html><body style="margin:0;background:transparent">{svg.replace("<svg ", "<svg width=512 height=512 ", 1)}</body></html>')
        pg.screenshot(path=str(MT_IMG / 'masterworld-512.png'), omit_background=True, clip={'x': 0, 'y': 0, 'width': 512, 'height': 512})
        b.close()
    Image.open(MT_IMG / 'masterworld-512.png').convert('RGBA').resize((128, 128), Image.LANCZOS).save(MT_IMG / 'masterworld.png', optimize=True)
    for f in sorted(MT_IMG.glob('masterworld*')):
        print(f.relative_to(ROOT), f.stat().st_size)


if __name__ == '__main__':
    main()
