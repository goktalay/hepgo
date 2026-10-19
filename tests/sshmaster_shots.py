#!/opt/hepgo/fabrika-yonetim/.venv/bin/python
"""Merkez › Mastertool ekranı görsel doğrulama (Playwright headless shell): HEPGO merkez kipinde (CAYMAZ_FEDERATION_CENTRAL=1) ve
Mastertool hesap servisi ayrı portlarda subprocess olarak açılır (PID ile kapatılır), demo kullanıcılar + SIMUMAV/VOLFAI özetleri yazılır,
üst kartlar + Araçlar/Oyunlar sütun sekmeleri + kullanıcı ayrıntı paneli görüntülenir. Çıktı: /tmp/flsim/smcol/*.png

Çalıştırma: ./.venv/bin/python tests/sshmaster_shots.py [hepgo_port=8720] [sshm_port=8096]"""
import base64
import hashlib
import os
import pathlib
import sqlite3
import subprocess
import sys
import time

import httpx

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
HP, SP = int(sys.argv[1]) if len(sys.argv) > 1 else 8720, int(sys.argv[2]) if len(sys.argv) > 2 else 8096
DATA = pathlib.Path(os.environ.get('CAYMAZ_DATA_DIR', '/tmp/flsim/smcol-data'))
SD = DATA / 'sshm'
OUT = pathlib.Path('/tmp/flsim/smcol')
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
B, S = f'http://127.0.0.1:{HP}', f'http://127.0.0.1:{SP}'
K = {'X-Central-Secret': 'ic-anahtar'}


def auth_hash(pw, kdf):
    m = hashlib.pbkdf2_hmac('sha256', pw.encode(), base64.b64decode(kdf['salt']), kdf['iter'], 32)
    return base64.b64encode(hashlib.pbkdf2_hmac('sha256', m, pw.encode(), 1, 32)).decode()


def bekle(url):
    for _ in range(120):
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise SystemExit(f'açılmadı: {url}')


def demo_veri():
    """4 kullanıcı: 2'si SIMUMAV uçmuş (biri VOLFAI de), 1'i yalnız VOLFAI, 1'i hiç oyun oynamamış (e-posta bekliyor)."""
    kisiler = [('Ayşe Yılmaz', 'ayse@ornek.com'), ('Mehmet Kaya', 'mehmet@ornek.com'), ('Elif Demir', 'elif@ornek.com'), ('Can Öz', 'can@ornek.com')]
    ids = {}
    for ad, ep in kisiler:
        kdf = httpx.post(S + '/api/sm/auth/prelogin', json={'email': ep}).json()['kdf']
        httpx.post(S + '/api/sm/auth/register', json={'name': ad, 'email': ep, 'auth_hash': auth_hash('Sifre-123', kdf)})
    for u in httpx.get(S + '/api/sm/admin/users', headers=K).json()['users']:
        ids[u['email']] = u['id']
        if u['email'] != 'can@ornek.com':
            httpx.put(S + f"/api/sm/admin/users/{u['id']}", headers=K, json={'status': 'AKTIF'})
    sv = {'X-Simumav-Secret': 'sv-gizli'}
    httpx.put(S + '/api/sv/profile', headers=sv, json={'user_id': ids['ayse@ornek.com'], 'profile': {
        'pilot': 'Ayşe', 'pilots': 2, 'drones': 3, 'flights': 42, 'hours': 17.4, 'last_flight_at': '2026-10-18T21:12:00', 'version': '1.4.0', 'updated_at': 'x'}})
    httpx.put(S + '/api/sv/profile', headers=sv, json={'user_id': ids['mehmet@ornek.com'], 'profile': {
        'pilot': 'Mehmet', 'pilots': 1, 'drones': 1, 'flights': 3, 'hours': 0.6, 'last_flight_at': '2026-10-02T10:40:00', 'version': '1.3.2', 'updated_at': 'x'}})
    for ep, prof in (('ayse@ornek.com', {'hiScore': 12480, 'coins': 37, 'levels': {'1': {'parkurs': {'1': {}, '2': {}}}, '2': {'parkurs': {'1': {}}}}}),
                     ('elif@ornek.com', {'hiScore': 3200, 'coins': 5, 'levels': {'1': {'parkurs': {'1': {}}}}})):
        kdf = httpx.post(S + '/api/vf/auth/prelogin', json={'email': ep}).json()['kdf']
        tok = httpx.post(S + '/api/vf/auth/login', json={'email': ep, 'auth_hash': auth_hash('Sifre-123', kdf), 'device': 'VOLFAI Web'}).json()['token']
        httpx.put(S + '/api/vf/profile', headers={'Authorization': f'Bearer {tok}', 'X-SSHM': '1'}, json={'profile': prof})
    with sqlite3.connect(SD / 'sshm.db') as conn:   # SIMUMAV web paketi sürümü (üst kart): GitHub Actions'ın yazdığı satırın eşdeğeri
        conn.execute("INSERT OR IGNORE INTO web_releases (app, version, file, size, sha256, notes, created_at, created_by) VALUES ('sv','1.4.0','simumav-1.4.0.tar.gz',1024,'00','',?, 'release-key')",
                     (time.strftime('%Y-%m-%dT%H:%M:%S'),))


def main():
    OUT.mkdir(parents=True, exist_ok=True); SD.mkdir(parents=True, exist_ok=True)
    for p in (DATA / 'caymaz.db', SD / 'sshm.db'):
        if p.exists():
            p.unlink()
    senv = dict(os.environ, SSHM_DATA_DIR=str(SD), SSHM_ENV_FILE=str(SD / 'x'), VEILOX_ENV_FILE=str(SD / 'y'), SSHM_MAIL_TEST='1',
                SSHM_CENTRAL_SECRET='ic-anahtar', SSHM_SECURE_COOKIE='0', SIMUMAV_MT_SHARED_SECRET='sv-gizli')
    henv = dict(os.environ, CAYMAZ_DATA_DIR=str(DATA), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
                CAYMAZ_ADMIN_FULL_NAME='Merkez Yönetici', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_FEDERATION_CENTRAL='1',
                CAYMAZ_CENTRAL_API_SECRET='ic-anahtar', CAYMAZ_SSHM_URL=S, CAYMAZ_COMPANY_NAME='HEPGO Merkez')
    ssrv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'sshm.main:app', '--port', str(SP), '--log-level', 'warning'],
                            cwd=ROOT / 'central' / 'sshmaster_server', env=senv)
    hsrv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(HP), '--log-level', 'warning'], cwd=ROOT, env=henv)
    print('PID hesap servisi', ssrv.pid, '· HEPGO', hsrv.pid)
    hatalar = []
    try:
        bekle(S + '/api/sm/health'); bekle(B + '/api/auth/me')
        demo_veri()
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=EXE)
            ctx = b.new_context(viewport={'width': 1920, 'height': 1080}, locale='tr-TR')
            r = ctx.request.post(B + '/api/auth/login', data={'username': 'admin@test', 'password': 'admin-sifre-1'})
            assert r.ok, r.text()
            pg = ctx.new_page()
            pg.on('console', lambda m: hatalar.append(f'KONSOL {m.type}: {m.text[:300]}') if m.type == 'error' else None)
            pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:400]))
            ctx.request.post(B + '/api/kvkk/accept-terms', data={})   # açılıştaki KVKK aydınlatma onayı
            ctx.request.post(B + '/api/location/consent', data={'granted': False})   # web konum rızası diyaloğu açılmasın
            pg.goto(B + '/app#/sshmaster', wait_until='networkidle')
            try:
                pg.wait_for_selector('.stat-strip .stat', timeout=30000)
            except Exception:
                pg.screenshot(path=str(OUT / 'hata.png')); print('URL:', pg.url, '\nMETİN:', pg.inner_text('body')[:600]); raise
            pg.wait_for_selector('table tbody tr', timeout=30000)
            pg.wait_for_timeout(600)
            pg.screenshot(path=str(OUT / '01-araclar.png'))
            pg.click('.seg button:has-text("Oyunlar")')
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / '02-oyunlar.png'))
            pg.select_option('select:has(option[value="sv"])', 'sv')
            pg.wait_for_timeout(300)
            assert pg.locator('table tbody tr').count() == 2, 'SIMUMAV filtresi 2 kullanıcı vermeli'
            pg.screenshot(path=str(OUT / '03-oyunlar-filtre-simumav.png'))
            pg.select_option('select:has(option[value="sv"])', '')
            pg.wait_for_timeout(200)
            pg.click('table tbody tr:has-text("Ayşe")')
            pg.wait_for_selector('.modal-body h3:has-text("Oyunlar")', timeout=15000)
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / '04-ayrinti.png'), full_page=False)
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
    print('sshmaster_shots: TAMAM')


if __name__ == '__main__':
    main()
