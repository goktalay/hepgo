#!/opt/hepgo/fabrika-yonetim/.venv/bin/python
"""mastertool.download ana sayfası › Oyunlar bölümü görsel doğrulama (Playwright headless shell): hesap servisi ayrı portta subprocess
olarak açılır (PID ile kapatılır), VOLFAI + SIMUMAV kartları tr ve en dilinde görüntülenir. Çıktı: /tmp/flsim/mtsim/*.png

Çalıştırma: ./.venv/bin/python central/sshmaster_server/tests/mt_oyunlar_shots.py [port=8097]"""
import os
import pathlib
import subprocess
import sys
import time

import httpx

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
from playwright.sync_api import sync_playwright  # noqa: E402

SRV = pathlib.Path(__file__).resolve().parents[1]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8097
DATA = pathlib.Path('/tmp/flsim/mtsim-data')
OUT = pathlib.Path('/tmp/flsim/mtsim')
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
S = f'http://127.0.0.1:{PORT}'


def bekle(url):
    for _ in range(120):
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise SystemExit(f'açılmadı: {url}')


def main():
    OUT.mkdir(parents=True, exist_ok=True); DATA.mkdir(parents=True, exist_ok=True)
    if (DATA / 'sshm.db').exists():
        (DATA / 'sshm.db').unlink()
    env = dict(os.environ, SSHM_DATA_DIR=str(DATA), SSHM_ENV_FILE=str(DATA / 'x'), VEILOX_ENV_FILE=str(DATA / 'y'), SSHM_MAIL_TEST='1',
               SSHM_SECURE_COOKIE='0', MT_DEFAULT_SITE='mt', MT_PORTAL_LIVE='1')   # tanınmayan Host (127.0.0.1) → mastertool.download gibi davranır
    srv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'sshm.main:app', '--port', str(PORT), '--log-level', 'warning'], cwd=SRV, env=env)
    print('PID hesap servisi', srv.pid)
    hatalar = []
    try:
        bekle(S + '/api/sm/health')
        r = httpx.get(S + '/oyunlar/simumav/', follow_redirects=False)
        assert r.status_code == 307 and r.headers['location'] == 'https://simumav.com/', (r.status_code, r.headers.get('location'))
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=EXE)
            for lang in ('tr', 'en'):
                ctx = b.new_context(viewport={'width': 1600, 'height': 1000}, locale='tr-TR' if lang == 'tr' else 'en-US')
                pg = ctx.new_page()
                pg.on('console', lambda m: hatalar.append(f'KONSOL {m.type}: {m.text[:300]}') if m.type == 'error' else None)
                pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
                pg.goto(S + '/' + ('' if lang == 'tr' else '?lang=en'), wait_until='networkidle')
                pg.wait_for_selector('a.prod[href="https://simumav.com/"] h3:has-text("SIMUMAV")', timeout=20000)
                pg.wait_for_timeout(600)
                red = pg.locator('button:has-text("Reddet"), button:has-text("Reject")')   # çerez bildirimi kartların üstüne gelmesin
                if red.count():
                    red.first.click(); pg.wait_for_timeout(300)
                sec = pg.locator('#oyunlar')
                sec.scroll_into_view_if_needed()
                pg.wait_for_timeout(300)
                kart = pg.locator('a.prod[href="https://simumav.com/"]')
                metin = kart.inner_text()
                beklenen = 'Oyna → · Tanıtım →' if lang == 'tr' else 'Play → · Overview →'
                assert beklenen in metin and 'SIMUMAV' in metin, (lang, metin)
                box = sec.bounding_box(); kb = kart.bounding_box()
                pg.screenshot(path=str(OUT / f'oyunlar-{lang}.png'),
                              clip={'x': 0, 'y': max(box['y'] - 24, 0), 'width': 1600, 'height': kb['y'] + kb['height'] + 24 - max(box['y'] - 24, 0)})
                ctx.close()
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
    print('görüntüler:', sorted(x.name for x in OUT.glob('*.png')))
    if hatalar:
        print('\n'.join(hatalar)); raise SystemExit(1)
    print('mt_oyunlar_shots: TAMAM')


if __name__ == '__main__':
    main()
