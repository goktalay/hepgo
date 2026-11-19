"""§49 Karıştırma — GERÇEK SITL ölçümü: sanal kumanda AÇIKKEN (20 Hz override akışı) "gaz ortada" ve kumanda karıştırması geçişleri
(elle çalıştırılır; ArduPilot SITL ikilisi gerekir, ~4 dk).

Kopter GUIDED'da 25 m'de askıdayken: (1) tam GPS karıştırma, gaza dokunulmamış → ALT_HOLD + irtifa korunur; (2) pilot gaz verir → devralır;
(3) kumanda karıştırması eklenir → Radio Failsafe, konum yokken ArduPilot'un kendi kararı (LAND); (4) hepsi kapanır → kip değişmez;
(5) yeniden kalkış, YALNIZ kumanda karıştırma 15 sn → RTL; bitince kip RTL'de kalır. Hiçbir adımda STABILIZE'a sıçrama / havada disarm olmamalı.

    PYTHONPATH=. ./.venv/bin/python tests/jam_sitl_olcum49.py
"""
import asyncio
import math
import os
import sys
import socket
import tempfile
import threading
import time

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_DRONE_PKG='1', CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo',
                  HEPGO_SITL='1', SIM_UDP_BASE='39870', SIM_TERRAIN_SERVE='0')
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/sitl/bin')
PORT = 8873
BASE = f'http://127.0.0.1:{PORT}'

import requests  # noqa: E402
import uvicorn  # noqa: E402

from app import flightsim  # noqa: E402
from app.main import app  # noqa: E402

LAT, LON = 39.925, 32.837
K = math.cos(math.radians(LAT))
OLAY, CERCEVE = [], []


def ne(lat, lon):
    return (lat - LAT) * 110574.0, (lon - LON) * 111320.0 * K


def bekle(fn, sn, ad):
    t0 = time.time()
    while time.time() - t0 < sn:
        try:
            if fn():
                return True
        except Exception:   # noqa: BLE001
            pass
        time.sleep(0.2)
    raise RuntimeError(ad)


def main():
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=PORT, log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(160):
        try:
            socket.create_connection(('127.0.0.1', PORT), 0.3).close()
            break
        except OSError:
            time.sleep(0.25)
    s = requests.Session()
    assert s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'}).status_code == 200
    s.post(f'{BASE}/api/kvkk/accept-terms', json={})
    c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ölçüm', 'lat': LAT, 'lon': LON, 'alt': 900}).json()
    S = f'{BASE}/api/drone/sim/sessions'

    def cmd(sid, name, params=None):
        r = s.post(f'{S}/{sid}/cmd', json={'name': name, 'params': params or {}})
        if r.status_code != 200:
            raise RuntimeError(f'cmd {name} {r.status_code} {r.text[:200]}')
        return r.json()

    r = s.post(S, json={'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False},
                        'world': {'mode': 'procedural', 'wind_ms': 0, 'wind_dir': 270}})
    assert r.status_code == 201, r.text
    sid = r.json()['id']
    ss = flightsim.MANAGER.sessions[sid]
    eski = ss._yay

    def yay(m):
        if m.get('t') == 'event':
            OLAY.append(m.get('text'))
        elif m.get('t') == 'jam':
            CERCEVE.append((round(time.time() - T0, 1), m.get('reason'), m.get('on'), m.get('real')))
        return eski(m)
    ss._yay = yay
    T0 = time.time()
    RC = {'ch': None}

    def rc_akis():
        while True:
            ch = RC['ch']
            if ch is not None and ss.loop is not None:
                try:
                    asyncio.run_coroutine_threadsafe(ss.rc(list(ch)), ss.loop)
                except Exception:   # noqa: BLE001
                    pass
            time.sleep(0.05)
    threading.Thread(target=rc_akis, daemon=True).start()

    def satir(ad):
        t = ss.tele
        j = t.get('jam') or {}
        d = ss.jam.durum()
        print(f"{time.time() - T0:6.1f} {ad:26s} {str(t.get('mode')):9s} arm {int(bool(t.get('armed')))} fix {t.get('gps_fix')} irtifa {t.get('alt_rel'):5.1f} "
              f"rc {(t.get('rc') or [])[:5]} gaz% {t.get('throttle')} thr_mid {d.get('thr_mid')} rc_kesik {d.get('rc')} açık {j.get('on')}", flush=True)

    def izle(ad, sn, aralik=2.0):
        n0 = len(OLAY)
        for _ in range(int(sn / aralik)):
            time.sleep(aralik)
            satir(ad)
        yeni = [o for o in OLAY[n0:] if o]
        if yeni:
            print('        olaylar:', yeni[-12:], flush=True)

    NOTR = [1500, 1500, 0, 1500, 1500, 0, 0, 0]
    try:
        bekle(lambda: ss.state == 'HAZIR' and ss._heartbeat_alindi and ss.tele.get('gps_fix', 0) >= 3 and ss.tele.get('home'), 150, 'HAZIR')
        print('--- sanal kumanda akışı başlar (20 Hz, gaz kanalı 0 = dokunma) — tarayıcının varsayılanı')
        RC['ch'] = NOTR
        time.sleep(12)
        satir('yerde, akış açık')
        for _ in range(12):
            cmd(sid, 'mode', {'mode': 'GUIDED'})
            time.sleep(1)
            cmd(sid, 'arm')
            time.sleep(2)
            cmd(sid, 'takeoff', {'alt': 25})
            time.sleep(4)
            if (ss.tele.get('alt_rel') or 0) > 2 and ss.tele.get('mode') == 'GUIDED':
                break
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 22, 60, 'kalkış')
        time.sleep(4)
        satir('GUIDED askı')
        print('--- 1) tam GPS karıştırma (fs = althold), sanal kumanda açık, gaza dokunulmadı → ALT_HOLD + irtifa korunmalı')
        print('    ', cmd(sid, 'jam', {'gps': 'full'})['jam'].get('fs'))
        izle('tam GPS', 30)
        print('--- 2) pilot gaz verir (ch3 = 1650) → devralır, tırmanır')
        RC['ch'] = [1500, 1500, 1650, 1500, 1500, 0, 0, 0]
        izle('pilot gaz 1650', 8)
        RC['ch'] = [1500, 1500, 1500, 1500, 1500, 0, 0, 0]
        izle('pilot gaz 1500', 6)
        print('--- 3) kumanda karıştırma eklenir (GPS hâlâ yok) → Radio failsafe; GPS yokken ArduPilot kararı')
        cmd(sid, 'jam', {'gps': 'full', 'rc': True})
        izle('GPS + kumanda', 20)
        print('--- 4) hepsi kapanır')
        cmd(sid, 'jam', {'off': True})
        izle('kapandı', 30)
        try:
            bekle(lambda: not ss.tele.get('armed'), 60, 'iniş')
        except RuntimeError:
            print('        (araç hâlâ havada)')
        satir('son')
        try:
            bekle(lambda: not ss.jam._gercek, 60, 'toparlanma')
        except RuntimeError:
            print('        (EKF toparlanmadı)')
        print('--- 5) yeniden kalkış; YALNIZ kumanda karıştırma (GPS sağlam) 15 sn → RTL beklenir; bitince kip?')
        RC['ch'] = NOTR
        time.sleep(3)
        for _ in range(12):
            cmd(sid, 'mode', {'mode': 'GUIDED'})
            time.sleep(1)
            cmd(sid, 'arm')
            time.sleep(2)
            cmd(sid, 'takeoff', {'alt': 25})
            time.sleep(4)
            if (ss.tele.get('alt_rel') or 0) > 2 and ss.tele.get('mode') == 'GUIDED':
                break
        bekle(lambda: (ss.tele.get('alt_rel') or 0) > 22, 60, 'kalkış 2')
        time.sleep(3)
        satir('GUIDED askı 2')
        cmd(sid, 'jam', {'rc': True, 'dur_s': 15})
        izle('kumanda kesik', 14)
        izle('kumanda geri', 14, 1.0)
        print('jam çerçeveleri:', CERCEVE)
    finally:
        for x in list(flightsim.MANAGER.sessions):
            try:
                s.delete(f'{S}/{x}')
            except Exception:   # noqa: BLE001
                pass
        time.sleep(2)
        sys.stdout.flush()
    os._exit(0)


if __name__ == '__main__':
    main()
