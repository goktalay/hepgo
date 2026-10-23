"""HEPGO bayram temaları (docs/bayram-temalari.md) — uç nokta + görsel doğrulama (Playwright headless shell). Sunucu AYRI süreçte (geçici veri dizini).

  * GET /api/holiday-theme (oturumsuz; TR 2027-05-19 birleşik tema, 422), GET /api/holiday-theme/me (oturumlu; ayar + konum),
    PUT /api/auth/prefs/settings ile holiday {on, country} gidiş-dönüş
  * Pano: 20 tema önizleme kipiyle (/?bayram=<tema>#/), birleşik tema, başka sayfada ve simülatör sahnesinde (.fs-stage) katman gizli,
    Kişisel Ayarlar › Bayram temaları, "Hareketleri azalt" → durağan kare
Görüntüler /tmp/bayram-shots/hepgo-*.png. Çalıştırma: ./.venv/bin/python -m tests.holiday_hepgo_shots [tema …]
"""
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = int(os.environ.get('SHOT_PORT') or 8833)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/bayram-shots')
DATA = pathlib.Path('/tmp/bayram-hepgo-data')
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
LIBS = '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu'
THEMES = ['kurban', 'ramazan', 'hicri', 'noel', 'paskalya', 'hristiyan', 'yilbasi', 'cin_yeni', 'diwali', 'holi', 'hindu', 'yahudi',
          'cocuk_genclik', 'kadin_anne', 'sevgi', 'cadilar', 'bagimsizlik', 'emek', 'bahar', 'genel']
USER, PW = 'demo@firma.com', 'Demo-Sifre-12'


def main():
    only = [a for a in sys.argv[1:] if a in THEMES] or THEMES
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('CAYMAZ_')}
    env.update(CAYMAZ_DATA_DIR=str(DATA), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
               CAYMAZ_ADMIN_USERNAME=USER, CAYMAZ_ADMIN_PASSWORD=PW, CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici', HEPGO_SITL='0', SIM_UDP_BASE='39550',
               SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', CAYMAZ_ENV_FILE=str(DATA / 'yok.env'))
    log = open(OUT / 'hepgo-server.log', 'w')
    srv = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-c', f"import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port={PORT}, log_level='warning')"],
                           cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    errors = []
    try:
        for _ in range(240):
            try:
                socket.create_connection(('127.0.0.1', PORT), 0.3).close()
                break
            except OSError:
                time.sleep(0.5)
        # ---- uç noktalar
        r = requests.get(f'{BASE}/api/holiday-theme', params={'country': 'TR', 'date': '2027-05-19', 'lang': 'tr'}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert [a['theme'] for a in j['active']] == ['kurban', 'cocuk_genclik'] and j['active'][0]['day_index'] == 5, j
        assert 'max-age=3600' in r.headers.get('cache-control', '')
        assert requests.get(f'{BASE}/api/holiday-theme', params={'country': 'TUR'}, timeout=10).status_code == 422
        assert requests.get(f'{BASE}/api/holiday-theme', params={'country': 'TR', 'date': 'x'}, timeout=10).status_code == 422
        assert requests.get(f'{BASE}/api/holiday-theme/me', timeout=10).status_code == 401
        s = requests.Session()
        assert s.post(f'{BASE}/api/auth/login', json={'username': USER, 'password': PW}, timeout=30).status_code == 200
        s.post(f'{BASE}/api/kvkk/accept-terms', json={}, timeout=30)
        me = s.get(f'{BASE}/api/holiday-theme/me', timeout=30).json()
        assert me['enabled'] is True and me['country'] is None and 'TR' in me['countries'] and len(me['themes']) == 20, me
        cur = s.get(f'{BASE}/api/auth/me', timeout=30).json().get('prefs', {}).get('settings', {})
        assert s.put(f'{BASE}/api/auth/prefs/settings', json={**cur, 'holiday': {'on': False, 'country': 'DE'}}, timeout=30).status_code == 200
        me = s.get(f'{BASE}/api/holiday-theme/me', timeout=30).json()
        assert me['enabled'] is False and me['country'] == 'DE', me
        cur = {**cur, 'privacy': {**cur.get('privacy', {}), 'share_location_web': False}}   # konum izni penceresi görüntüyü örtmesin
        assert s.put(f'{BASE}/api/auth/prefs/settings', json={**cur, 'holiday': {'on': True, 'country': ''}}, timeout=30).status_code == 200
        print('  uç noktalar + ayar gidiş-dönüş tamam', flush=True)

        os.environ['LD_LIBRARY_PATH'] = LIBS
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=EXE, args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])

            def page(**kw):
                ctx = br.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR', timezone_id='Europe/Istanbul', **kw)
                ctx.add_cookies([{'name': c.name, 'value': c.value, 'url': BASE} for c in s.cookies])
                pg = ctx.new_page()
                pg.on('pageerror', lambda e: errors.append(f'[pageerror] {str(e)[:300]}'))
                pg.on('console', lambda m: errors.append(f'[console] {m.text[:300]}') if m.type in ('error', 'warning') and ('holiday' in m.text.lower() or 'bayram' in m.text.lower()) else None)
                return ctx, pg

            st = lambda pg: pg.evaluate('window.__holidayFx ? window.__holidayFx() : null')
            ctx, pg = page()
            for th in only:
                pg.goto(f'{BASE}/app?bayram={th}#/', wait_until='domcontentloaded')
                pg.wait_for_function('window.__holidayFx && window.__holidayFx().frames > 20', timeout=60000)
                pg.wait_for_timeout(2400 if th not in ('bagimsizlik', 'noel', 'cin_yeni') else 5000)
                x = st(pg); assert x['themes'][0] == th, x
                pg.screenshot(path=str(OUT / f'hepgo-{th}.png')); print(f'  hepgo-{th}.png  {x["avgMs"]} ms/kare  ülke={x["detected"]["country"]} ({x["detected"]["source"]})', flush=True)
            pg.goto(f'{BASE}/app?bayram=kurban,cocuk_genclik#/', wait_until='domcontentloaded'); pg.wait_for_function('window.__holidayFx && window.__holidayFx().frames > 20', timeout=60000); pg.wait_for_timeout(3000)
            assert st(pg)['themes'] == ['kurban', 'cocuk_genclik']
            pg.screenshot(path=str(OUT / 'hepgo-birlesik-kurban-genclik.png')); print('  hepgo-birlesik-kurban-genclik.png', flush=True)
            # simülatör sahnesi (.fs-stage) ve başka sayfa → gizli
            assert pg.evaluate("document.querySelectorAll('canvas.holiday-fx').length") == 1
            pg.evaluate("document.body.append(Object.assign(document.createElement('div'), { className: 'fs-stage' }))"); pg.wait_for_timeout(1500)
            pg.wait_for_function("document.querySelector('canvas.holiday-fx').style.opacity === '0'", timeout=15000)   # döngü bir sonraki karede gizler
            pg.evaluate("document.querySelector('.fs-stage').remove()")
            pg.wait_for_function("document.querySelector('canvas.holiday-fx').style.opacity === '1'", timeout=15000)
            pg.goto(f'{BASE}/app?bayram=kurban#/settings/holiday', wait_until='domcontentloaded'); pg.wait_for_selector('.set-card h3', timeout=30000); pg.wait_for_timeout(2500)
            assert pg.evaluate("document.querySelector('canvas.holiday-fx')?.style.opacity") in ('0', None)
            pg.screenshot(path=str(OUT / 'hepgo-ayarlar.png')); print('  hepgo-ayarlar.png (katman gizli)', flush=True)
            assert pg.locator('.set-card select').count() >= 2   # ülke + önizleme (yönetici)
            ctx.close()
            ctx, pg = page(reduced_motion='reduce')
            pg.goto(f'{BASE}/app?bayram=noel#/', wait_until='domcontentloaded'); pg.wait_for_function('window.__holidayFx && window.__holidayFx()', timeout=60000); pg.wait_for_timeout(2500)
            x = st(pg); assert x['reduced'] and not x['running'], x
            pg.screenshot(path=str(OUT / 'hepgo-reduced-noel.png')); print('  hepgo-reduced-noel.png (durağan)', flush=True)
            ctx.close()
            br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(20)
        except subprocess.TimeoutExpired:
            srv.kill()
    if errors:
        print('HATALAR:'); [print(' ', e) for e in errors[:20]]
        sys.exit(1)
    print('holiday_hepgo_shots: TAMAM')


if __name__ == '__main__':
    main()
