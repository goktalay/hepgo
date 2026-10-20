#!/opt/hepgo/fabrika-yonetim/.venv/bin/python
"""MASTERWORLD görsel doğrulama (Playwright headless shell): hesap servisi (MT_DEFAULT_SITE=mt → 127.0.0.1 mastertool.download gibi) ve HEPGO
merkez kipi ayrı portlarda subprocess olarak açılır (PID ile kapatılır). Gerçek Excel içe aktarılır, örnek 'points' kaynağı + noktalar eklenir.
Çıktı: /tmp/masterworld/merkez-*.png (Merkez › Mastertool › MASTERWORLD) ve /tmp/masterworld/mt-*.png (ana sayfa kartı, /uygulamalar, simge).

Çalıştırma: ./.venv/bin/python tests/masterworld_shots.py [xlsx]"""
import base64
import hashlib
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time

import httpx

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
XLSX = sys.argv[1] if len(sys.argv) > 1 else '/home/gelistirici/mt-work/masterworld-ref/Cesium_Canli_Veri_Kaynaklari.xlsx'
OUT = pathlib.Path('/tmp/masterworld')
EXE = os.environ.get('CHROMIUM_PATH') or os.path.expanduser(
    '~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
K = {'X-Central-Secret': 'ic-anahtar'}


def bos_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close()
    return p


def auth_hash(pw, kdf):
    m = hashlib.pbkdf2_hmac('sha256', pw.encode(), base64.b64decode(kdf['salt']), kdf['iter'], 32)
    return base64.b64encode(hashlib.pbkdf2_hmac('sha256', m, pw.encode(), 1, 32)).decode()


def bekle(url):
    for _ in range(160):
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise SystemExit(f'açılmadı: {url}')


def demo(S):
    r = httpx.post(S + '/api/sm/admin/mw/import', headers=K, files={'file': ('Kaynaklar.xlsx', open(XLSX, 'rb').read())}, timeout=60)
    assert r.status_code == 200, r.text
    src = {s['slug']: s for s in httpx.get(S + '/api/sm/admin/mw/sources', headers=K).json()['sources']}
    httpx.put(S + f"/api/sm/admin/mw/sources/{src['windy-webcams-api-v3']['id']}", headers=K, json={'api_key': 'demo-anahtar', 'enabled': True})
    r = httpx.post(S + '/api/sm/admin/mw/sources', headers=K, json={'slug': 'istanbul-kameralari', 'category': 'camera', 'kind': 'camera', 'name': 'İstanbul kameraları',
                                                                   'adapter': 'points', 'enabled': True, 'license': 'Kurum izniyle', 'attribution': 'Kamera: İBB',
                                                                   'attribution_required': True, 'sort': 380})
    sid = r.json()['id']
    for n, la, lo in (('Galata Kulesi', 41.0256, 28.9741), ('Kız Kulesi', 41.0211, 29.0041), ('Taksim Meydanı', 41.0369, 28.9850)):
        httpx.post(S + f'/api/sm/admin/mw/sources/{sid}/points', headers=K, json={'name': n, 'lat': la, 'lon': lo, 'media_type': 'image',
                                                                                 'media_url': f'https://kamera.example/{n.split()[0].lower()}.jpg'})
    kdf = httpx.post(S + '/api/mt/auth/prelogin', json={'email': 'demo@ornek.com'}).json()['kdf']
    httpx.post(S + '/api/mt/auth/register', json={'name': 'Demo Kullanıcı', 'email': 'demo@ornek.com', 'auth_hash': auth_hash('Sifre-123', kdf)})
    uid = next(u['id'] for u in httpx.get(S + '/api/sm/admin/users', headers=K).json()['users'])
    httpx.put(S + f'/api/sm/admin/users/{uid}', headers=K, json={'status': 'AKTIF'})
    return kdf


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    DATA = pathlib.Path(tempfile.mkdtemp(prefix='mwshots-'))
    SD = DATA / 'sshm'; SD.mkdir()
    HP, SP = bos_port(), bos_port()
    B, S = f'http://127.0.0.1:{HP}', f'http://127.0.0.1:{SP}'
    senv = dict(os.environ, SSHM_DATA_DIR=str(SD), SSHM_ENV_FILE=str(SD / 'x'), VEILOX_ENV_FILE=str(SD / 'y'), SSHM_MAIL_TEST='1', SSHM_CENTRAL_SECRET='ic-anahtar',
                SSHM_SECURE_COOKIE='0', MT_DEFAULT_SITE='mt', MT_PORTAL_LIVE='1', MASTERWORLD_MT_SHARED_SECRET='mw-gizli')
    henv = dict(os.environ, CAYMAZ_DATA_DIR=str(DATA), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
                CAYMAZ_ADMIN_FULL_NAME='Merkez Yönetici', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_FEDERATION_CENTRAL='1',
                CAYMAZ_CENTRAL_API_SECRET='ic-anahtar', CAYMAZ_SSHM_URL=S, CAYMAZ_COMPANY_NAME='HEPGO Merkez')
    ssrv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'sshm.main:app', '--port', str(SP), '--log-level', 'warning'], cwd=ROOT / 'central' / 'sshmaster_server', env=senv)
    hsrv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(HP), '--log-level', 'warning'], cwd=ROOT, env=henv)
    print('PID hesap servisi', ssrv.pid, '· HEPGO', hsrv.pid)
    hatalar = []
    try:
        bekle(S + '/api/sm/health'); bekle(B + '/api/auth/me')
        kdf = demo(S)
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=EXE)
            # ---------------- Merkez
            ctx = b.new_context(viewport={'width': 1920, 'height': 1080}, locale='tr-TR')
            assert ctx.request.post(B + '/api/auth/login', data={'username': 'admin@test', 'password': 'admin-sifre-1'}).ok
            ctx.request.post(B + '/api/kvkk/accept-terms', data={})
            ctx.request.post(B + '/api/location/consent', data={'granted': False})
            pg = ctx.new_page()
            pg.on('console', lambda m: hatalar.append(f'KONSOL {m.type}: {m.text[:300]}') if m.type == 'error' else None)
            pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
            pg.goto(B + '/app#/sshmaster/masterworld', wait_until='networkidle')
            pg.wait_for_selector('[data-stat="mw-total"]', timeout=30000)
            pg.wait_for_selector('table tbody tr[data-slug="adsb-lol"]', timeout=30000)
            pg.wait_for_timeout(600)
            pg.screenshot(path=str(OUT / 'merkez-01-liste.png'))
            pg.select_option('select:has(option[value="keymiss"])', 'keymiss'); pg.wait_for_timeout(300)
            n = pg.locator('table tbody tr').count()
            assert n == 3, f'anahtar eksik filtresi 3 kaynak vermeli (opensky, aisstream, firms), {n}'
            pg.screenshot(path=str(OUT / 'merkez-02-anahtar-eksik.png'))
            pg.select_option('select:has(option[value="keymiss"])', ''); pg.select_option('select:has(option[value="nc"])', 'nc'); pg.wait_for_timeout(300)
            pg.screenshot(path=str(OUT / 'merkez-03-ticari-kisitli.png'))
            pg.select_option('select:has(option[value="nc"])', '')
            # tek tık aç/kapa: celestrak kapat → aç
            row = pg.locator('tr[data-slug="celestrak"]')
            row.locator('button').click(); pg.wait_for_timeout(500)
            assert 'Kapalı' in row.inner_text()
            row.locator('button').click(); pg.wait_for_timeout(500)
            assert 'Etkin' in row.inner_text()
            pg.click('tr[data-slug="opensky-network"]')
            pg.wait_for_selector('.modal-body input[type=password]', timeout=15000); pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / 'merkez-04-duzenle.png'))
            pg.click('.modal-head .x-btn'); pg.wait_for_timeout(300)
            pg.click('tr[data-slug="istanbul-kameralari"]')
            pg.wait_for_selector('.modal-body h3:has-text("Noktalar (3)")', timeout=15000)
            pg.locator('.modal-body h3:has-text("Noktalar")').scroll_into_view_if_needed(); pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / 'merkez-05-noktalar.png'))
            pg.click('.modal-body button:has-text("Nokta ekle")'); pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / 'merkez-06-nokta-ekle.png'))
            pg.keyboard.press('Escape'); pg.wait_for_timeout(200); pg.keyboard.press('Escape'); pg.wait_for_timeout(200)
            pg.locator('input[type=file][accept*=".xlsx"]').set_input_files(XLSX)
            pg.wait_for_selector('.modal-head h2:has-text("içe aktarma sonucu")', timeout=30000); pg.wait_for_timeout(500)
            pg.screenshot(path=str(OUT / 'merkez-07-ice-aktarma.png'))
            pg.keyboard.press('Escape')
            ctx.close()
            # ---------------- mastertool.download
            for lang in ('tr', 'en'):
                ctx = b.new_context(viewport={'width': 1600, 'height': 1000}, locale='tr-TR' if lang == 'tr' else 'en-US')
                pg = ctx.new_page()
                pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
                pg.goto(S + '/' + ('' if lang == 'tr' else '?lang=en'), wait_until='networkidle')
                kart = pg.locator('a.prod[href="https://masterworld.app/"]')
                kart.wait_for(timeout=20000); pg.wait_for_timeout(600)
                red = pg.locator('button:has-text("Reddet"), button:has-text("Reject")')
                if red.count():
                    red.first.click(); pg.wait_for_timeout(300)
                kart.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
                metin = kart.inner_text()
                assert 'MASTERWORLD' in metin and ('Canlı dünya küresi' in metin if lang == 'tr' else 'Live world globe' in metin), (lang, metin)
                sec = pg.locator('#urunler .prods').first.bounding_box()
                pg.screenshot(path=str(OUT / f'mt-01-anasayfa-{lang}.png'), clip={'x': 0, 'y': max(sec['y'] - 90, 0), 'width': 1600, 'height': sec['height'] + 120})
                ctx.close()
            ctx = b.new_context(viewport={'width': 1600, 'height': 1000}, locale='tr-TR')
            assert ctx.request.post(S + '/api/mt/auth/login', data={'email': 'demo@ornek.com', 'auth_hash': auth_hash('Sifre-123', kdf), 'client': 'web'}).ok
            pg = ctx.new_page()
            pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
            pg.goto(S + '/uygulamalar', wait_until='networkidle')
            pg.wait_for_selector('[data-group="apps"] .tile[data-app="mw"]', timeout=20000); pg.wait_for_timeout(500)
            t = pg.locator('.tile[data-app="mw"]').inner_text()
            assert 'MASTERWORLD' in t and 'Aç' in t and 'Oyna' not in t, t
            pg.screenshot(path=str(OUT / 'mt-02-uygulamalar.png'))
            pg.goto(S + '/hesabim', wait_until='networkidle'); pg.wait_for_timeout(800)
            ob = pg.locator('button[data-tab]:has-text("Uygulamalar"), button[data-tab="apps"]')
            if ob.count():
                ob.first.click(); pg.wait_for_timeout(400)
            h3 = pg.locator('h3:has-text("Web uygulamaları")')
            if h3.count():
                h3.first.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
                pg.screenshot(path=str(OUT / 'mt-03-hesabim.png'))
            else:
                hatalar.append('Hesabım: "Web uygulamaları" başlığı bulunamadı')
            ctx.close()
            ctx = b.new_context(viewport={'width': 760, 'height': 300})
            pg = ctx.new_page()
            pg.set_content(f'<body style="margin:0;background:#0f1522;display:flex;gap:28px;align-items:center;justify-content:center;height:300px">'
                           f'<img src="{S}/brand/mw-512.png" width="200"><img src="{S}/brand/mw.png" width="128"><img src="{S}/brand/mw.svg" width="64">'
                           f'<div style="background:#f4f6fa;padding:18px;border-radius:16px"><img src="{S}/brand/mw.svg" width="96"></div></body>')
            pg.wait_for_timeout(500)
            pg.screenshot(path=str(OUT / 'mt-04-simge.png'))
            b.close()
    finally:
        for s in (hsrv, ssrv):
            s.terminate()
        for s in (hsrv, ssrv):
            try:
                s.wait(10)
            except subprocess.TimeoutExpired:
                s.kill()
    print('görüntüler:', sorted(x.name for x in OUT.glob('*.png')))
    if hatalar:
        print('\n'.join(hatalar)); raise SystemExit(1)
    print('masterworld_shots: TAMAM')


if __name__ == '__main__':
    main()
