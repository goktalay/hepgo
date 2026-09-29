"""Arayüz JavaScript dosyalarının sözdizimi kontrolü (Chromium ile; Node gerekmez).

Çalıştırma: .venv/bin/python -m tests.check_js   (playwright + chromium kurulu olmalı)
"""
import glob
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
CHECK = """src => { try { new Function(src.replace(/^\\s*import[^;]+;/gm, '').replace(/^export /gm, '')); return null; }
                    catch (e) { return e.message; } }"""


def main():
    files = sorted(glob.glob(str(ROOT / 'static/js/**/*.js'), recursive=True))
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        errors = [(f, e) for f in files if (e := pg.evaluate(CHECK, Path(f).read_text(encoding='utf-8')))]
        br.close()
    for f, e in errors:
        print(f'{Path(f).relative_to(ROOT)}: {e}')
    print(f'{len(files)} dosya kontrol edildi, {len(errors)} hata.')
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
