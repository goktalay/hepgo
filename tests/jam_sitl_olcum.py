"""§48 Karıştırma — GERÇEK SITL ölçümü (elle çalıştırılır; ArduPilot SITL ikilisi gerekir, ~4 dk).

Kopter GUIDED'da 25 m'de askıdayken `cmd jam` ile sırayla: GPS aldatma (2 m/s, 60 m, doğu) → kapat → hafif → ağır → tam. Her adımda gerçek konum
(tele.lat/lon = SIMSTATE), otopilotun konumu (tele.nav_lat/nav_lon = EKF), nav_err, GPS kilidi / uydu, kip ve otopilot iletileri yazdırılır.
Beklenen: aldatmada EKF sürüklenmeyi izler (nav_err ≈ sapma), araç gerçekte TERS yöne kayar; kapanınca EKF birkaç saniyede gerçek konuma döner
('settled' çerçevesi); hafifte uçuş sürer; ağır / tamda "EKF variance" / "GPS Glitch" ve EKF failsafe (LAND).

Çalıştırma: PYTHONPATH=. timeout 420 .venv/bin/python tests/jam_sitl_olcum.py   (SITL dizini: HEPGO_SITL_DIR, varsayılan /opt/hepgo/sitl/bin)
"""
import math
import os
import sys
import socket
import tempfile
import threading
import time

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_DRONE_PKG='1', CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo',
                  HEPGO_SITL='1', SIM_UDP_BASE='39850', SIM_TERRAIN_SERVE='0')
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/sitl/bin')
PORT = 8871
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

    def satir(ad):
        t = ss.tele
        g = ne(t['lat'], t['lon'])
        e = ne(t['nav_lat'], t['nav_lon']) if 'nav_lat' in t else (None, None)
        ekf = f'EKF(K {e[0]:+7.1f} D {e[1]:+7.1f}) hata {t.get("nav_err"):6.1f}' if e[0] is not None else 'EKF = konum'
        j = t.get('jam') or {}
        print(f"{time.time() - T0:6.1f} {ad:22s} {str(t.get('mode')):9s} arm {int(bool(t.get('armed')))} fix {t.get('gps_fix')} uydu {t.get('sats'):2d} "
              f"irtifa {t.get('alt_rel'):5.1f}  GERÇEK(K {g[0]:+7.1f} D {g[1]:+7.1f})  {ekf}  sapma {j.get('off_m')} kalan {j.get('left_s')}", flush=True)

    def izle(ad, sn, aralik=3.0):
        n0 = len(OLAY)
        for _ in range(int(sn / aralik)):
            time.sleep(aralik)
            satir(ad)
        yeni = [o for o in OLAY[n0:] if o]
        if yeni:
            print('        olaylar:', yeni[-10:], flush=True)

    def kalk():
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

    def hazirla():
        """Bir önceki adım failsafe ile indirdiyse yeniden kalk; EKF toparlanmasını ('settled') bekle."""
        try:
            bekle(lambda: not ss.jam._gercek, 100, 'toparlanma')
        except RuntimeError:
            print('        (EKF toparlanmadı — süre aşımı)')
        if not ss.tele.get('armed') or (ss.tele.get('alt_rel') or 0) < 15 or ss.tele.get('mode') != 'GUIDED':
            bekle(lambda: not ss.tele.get('armed'), 60, 'iniş')
            time.sleep(3)
            kalk()

    try:
        bekle(lambda: ss.state == 'HAZIR' and ss._heartbeat_alindi and ss.tele.get('gps_fix', 0) >= 3 and ss.tele.get('home'), 150, 'HAZIR')
        time.sleep(12)
        kalk()
        satir('GUIDED askı')
        print('--- GPS aldatma: doğu (90°), 2 m/s, 60 m')
        print('    ', cmd(sid, 'jam', {'spoof': {'on': True, 'dir': 90, 'speed': 2, 'max_m': 60}})['jam'])
        izle('aldatma', 45)
        print('--- kapat')
        cmd(sid, 'jam', {'off': True})
        izle('aldatma kapandı', 24)
        hazirla()
        print('--- hafif karıştırma, 30 sn')
        cmd(sid, 'jam', {'gps': 'light', 'dur_s': 30})
        izle('hafif', 36)
        hazirla()
        print('--- ağır karıştırma')
        cmd(sid, 'jam', {'gps': 'heavy', 'dur_s': 0})
        izle('ağır', 24)
        cmd(sid, 'jam', {'off': True})
        izle('ağır kapandı', 15)
        hazirla()
        print('--- tam karıştırma')
        cmd(sid, 'jam', {'gps': 'full'})
        izle('tam', 15)
        cmd(sid, 'jam', {'off': True})
        izle('tam kapandı', 15)
        print('jam çerçeveleri (sn, neden, açık, gerçek kip):', CERCEVE)
        print('özet:', s.get(f'{S}/{sid}/summary').json().get('jam'))
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
