"""Uçuş logu analizi (alt süreç + kuyruk, §8.4) — ölçüm + görsel doğrulama (Playwright headless shell).

Sunucu AYRI süreçte (uvicorn, kendi PID'iyle kapatılır) açılır; böylece sunucu belleği ile analiz alt sürecinin belleği ayrı ölçülür.
Büyük log tarayıcıdan parça parça yüklenir (Araçlar › Uçuş Logu Analizi) → rapor sayfasında ilerleme çubuğu → listede ilerleme +
ikinci log "Sırada" → analiz biter → rapor. Analiz sürerken ayrı iş parçacığı API gecikmesini ölçer (arayüz donuyor mu).
  BINANALYZE_LOG   : büyük log (vars. /tmp/binanalyze/big754.bin — PROD #6 kopyası)
  BINANALYZE_LOG2  : kuyrukta bekletilecek ikinci log (vars. /tmp/binanalyze/mid275.bin)
  BINANALYZE_KOD   : sunucunun çalıştırılacağı kod dizini (vars. bu depo; "önce" ölçümü için eski sürümün worktree'si)
  BINANALYZE_GORSEL: 0 → yalnız ölçüm (API ile yükleme; eski sürüm için)
Görüntüler /tmp/binanalyze-shots/*.png. Ölçüm özeti stdout'a JSON.
Çalıştırma: LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu ./.venv/bin/python -m tests.binanalyze_shots
"""
import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
KOD = pathlib.Path(os.environ.get('BINANALYZE_KOD') or ROOT)
LOG = pathlib.Path(os.environ.get('BINANALYZE_LOG') or '/tmp/binanalyze/big754.bin')
LOG2 = pathlib.Path(os.environ.get('BINANALYZE_LOG2') or '/tmp/binanalyze/mid275.bin')
GORSEL = os.environ.get('BINANALYZE_GORSEL', '1') != '0'
PORT = int(os.environ.get('SHOT_PORT') or 8831)
BASE = f'http://127.0.0.1:{PORT}'
OUT = pathlib.Path('/tmp/binanalyze-shots')
DATA = pathlib.Path(os.environ.get('BINANALYZE_DATA') or '/tmp/binanalyze-shots-data')
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
LIBS = '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu'


def proc_kb(pid, alan):
    try:
        with open(f'/proc/{pid}/status') as f:
            for sat in f:
                if sat.startswith(alan + ':'):
                    return int(sat.split()[1])
    except OSError:
        pass
    return 0


def cocuklar(pid):
    out = []
    try:
        for tid in os.listdir(f'/proc/{pid}/task'):
            with open(f'/proc/{pid}/task/{tid}/children') as f:
                out += [int(x) for x in f.read().split()]
    except OSError:
        pass
    return out


def main():
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('CAYMAZ_')}
    env.update(CAYMAZ_DATA_DIR=str(DATA), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
               CAYMAZ_DRONE_PKG='1', CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12',
               CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici', HEPGO_SITL='0', SIM_UDP_BASE='39450', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='',
               CAYMAZ_ENV_FILE=str(DATA / 'yok.env'))
    sunucu = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-c',
                               f"import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port={PORT}, log_level='error')"],
                              cwd=str(KOD), env=env)
    olcum = {'kod': str(KOD), 'log_mb': round(LOG.stat().st_size / 1e6)}
    hatalar = []
    try:
        for _ in range(200):
            try:
                socket.create_connection(('127.0.0.1', PORT), 0.3).close()
                break
            except OSError:
                time.sleep(0.25)
        else:
            sys.exit('sunucu açılmadı')
        time.sleep(1)
        s = requests.Session()
        assert s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'}).status_code == 200
        s.post(f'{BASE}/api/kvkk/accept-terms', json={})
        olcum['sunucu_rss_bos_mb'] = proc_kb(sunucu.pid, 'VmRSS') // 1024

        # ---- analiz sürerken API gecikmesi + bellek örnekleyici
        dur = threading.Event()
        gec, rss_s, hwm_c = [], [0], [0]

        def ornekle():
            api = requests.Session()
            api.cookies.update(s.cookies)
            while not dur.is_set():
                t = time.time()
                try:
                    api.get(f'{BASE}/api/tools/flight-logs', timeout=120)
                    api.get(f'{BASE}/api/auth/me', timeout=120)
                except requests.RequestException:
                    pass
                gec.append((time.time() - t) / 2)
                rss_s[0] = max(rss_s[0], proc_kb(sunucu.pid, 'VmRSS'))
                for c in cocuklar(sunucu.pid):
                    hwm_c[0] = max(hwm_c[0], proc_kb(c, 'VmHWM'))
                time.sleep(0.2)

        def analiz_bekle(lid, sn=900):
            bitis = time.time() + sn
            while time.time() < bitis:
                r = s.get(f'{BASE}/api/flight-logs/{lid}').json()
                if r['status'] != 'ISLENIYOR':
                    return r
                time.sleep(0.25)
            raise TimeoutError(lid)

        if not GORSEL:   # yalnız ölçüm (eski sürüm): tek istekle yükle, analizi bekle
            with open(LOG, 'rb') as f:
                t = time.time()
                lid = s.post(f'{BASE}/api/tools/flight-logs', files={'file': (LOG.name, f, 'application/octet-stream')}).json()['id']
            olcum['yukleme_ucu_sn'] = round(time.time() - t, 2)
            th = threading.Thread(target=ornekle, daemon=True)
            t = time.time()
            th.start()
            r = analiz_bekle(lid)
            olcum['analiz_sn'] = round(time.time() - t, 1)
        else:
            from playwright.sync_api import sync_playwright
            os.environ['LD_LIBRARY_PATH'] = LIBS
            with sync_playwright() as p:
                b = p.chromium.launch(executable_path=EXE)
                ctx = b.new_context(viewport={'width': 1440, 'height': 900}, locale='tr-TR')
                ctx.add_cookies([{'name': c.name, 'value': c.value, 'url': BASE} for c in s.cookies])
                pg = ctx.new_page()
                pg.set_default_timeout(300000)
                pg.on('pageerror', lambda e: hatalar.append('SAYFA: ' + str(e)[:300]))
                pg.on('console', lambda m: hatalar.append('KONSOL: ' + m.text[:300]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

                def shot(ad):
                    pg.screenshot(path=str(OUT / ad))
                    print('  kare', ad, flush=True)
                pg.goto(f'{BASE}/#/tools/flight-log', wait_until='domcontentloaded')
                pg.wait_for_selector('.upload-card input[type=file]')
                pg.wait_for_timeout(600)
                red = pg.locator('.modal-foot button', has_text='Reddet')
                if red.count():
                    red.first.click()
                    pg.wait_for_timeout(400)
                pg.locator('.upload-card input[type=file]').set_input_files(str(LOG))
                pg.locator('.upload-card input').nth(1).fill('CYZ-0002')
                pg.locator('.upload-card input').nth(2).fill('HASAN ÇELEBİ')
                pg.locator('.upload-card input').nth(3).fill('Akyurt')
                t_yukle = time.time()
                pg.locator('.upload-card button', has_text='Yükle ve Analiz Et').click()
                pg.wait_for_selector('.upload-card .progress-line', timeout=60000)
                pg.wait_for_function("() => { const b = document.querySelector('.upload-card .progress-line b'); return b && parseInt(b.textContent.slice(1)) >= 30; }", timeout=300000)
                shot('01-buyuk-log-yukleniyor.png')
                pg.wait_for_function("() => /^#\\/tools\\/flight-log\\/\\d+$/.test(location.hash)", timeout=600000)   # hash gezinmesi (load olayı yok)
                olcum['yukleme_sn'] = round(time.time() - t_yukle, 1)
                lid = int(pg.evaluate('location.hash').rsplit('/', 1)[1])
                t_analiz = time.time()
                th = threading.Thread(target=ornekle, daemon=True)
                th.start()
                # ikinci log kuyruğa (API, tek istek; ayrı iş parçacığında): ilk analiz sürerken "Sırada (1.)"
                ikinci = {}

                def yukle2():
                    with open(LOG2, 'rb') as f:
                        ikinci['id'] = s.post(f'{BASE}/api/tools/flight-logs', files={'file': (LOG2.name, f, 'application/octet-stream')},
                                              data={'aircraft': 'CYZ-0001', 'pilot': 'Test Pilot', 'location': 'Ankara'}).json()['id']
                y2 = threading.Thread(target=yukle2, daemon=True)
                y2.start()
                liste = ctx.new_page()
                liste.goto(f'{BASE}/#/tools/flight-log', wait_until='domcontentloaded')
                pg.wait_for_function("() => { const b = document.querySelector('.fl-analyzing .progress-line b'); return b && parseInt(b.textContent.slice(1)) >= 15; }", timeout=300000)
                shot('02-rapor-sayfasi-analiz-ilerlemesi.png')
                try:   # ilk analiz sürerken ikinci log sıraya girdiyse: ilerleme çubuğu + "Sırada (1.)" aynı karede
                    liste.wait_for_function("() => document.querySelector('.fl-queue') && document.querySelector('td .fl-progress')", timeout=30000)
                    liste.wait_for_timeout(200)
                except Exception:   # noqa: BLE001 — analiz çok hızlı bittiyse (sıra görülmeden)
                    hatalar.append('UYARI: liste karesinde sıra + ilerleme birlikte yakalanamadı')
                liste.screenshot(path=str(OUT / '03-liste-ilerleme-ve-sira.png'))
                print('  kare 03-liste-ilerleme-ve-sira.png', flush=True)
                pg.wait_for_selector('.fr-doc', timeout=900000)
                olcum['analiz_sn'] = round(time.time() - t_analiz, 1)
                pg.wait_for_timeout(1500)
                shot('04-analiz-sonucu-rapor.png')
                pg.evaluate('window.scrollTo(0, 900)')
                pg.wait_for_timeout(600)
                shot('05-analiz-sonucu-rapor-grafikler.png')
                y2.join(300)
                analiz_bekle(ikinci['id'])
                liste.wait_for_timeout(2500)
                liste.screenshot(path=str(OUT / '06-liste-ikisi-de-hazir.png'))
                print('  kare 06-liste-ikisi-de-hazir.png', flush=True)
                r = s.get(f'{BASE}/api/flight-logs/{lid}').json()
                b.close()
        dur.set()
        th.join(5)
        olcum['durum'] = r['status']
        olcum['ozet'] = {k: (r.get('analysis') or {}).get('summary', {}).get(k) for k in ('flight_s', 'distance_m', 'duration_s')}
        olcum['api_gecikme_ms'] = {'ornek': len(gec), 'ort': round(1000 * sum(gec) / max(1, len(gec))),
                                  'en_cok': round(1000 * max(gec or [0]))}
        olcum['sunucu_rss_tepe_mb'] = rss_s[0] // 1024
        olcum['analiz_sureci_tepe_mb'] = hwm_c[0] // 1024
        olcum['sunucu_hwm_mb'] = proc_kb(sunucu.pid, 'VmHWM') // 1024
        olcum['hatalar'] = hatalar
        print(json.dumps(olcum, ensure_ascii=False, indent=1), flush=True)
    finally:
        sunucu.send_signal(signal.SIGTERM)
        try:
            sunucu.wait(15)
        except subprocess.TimeoutExpired:
            sunucu.kill()
            sunucu.wait()
        shutil.rmtree(DATA, ignore_errors=True)


if __name__ == '__main__':
    main()
