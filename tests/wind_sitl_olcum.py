"""§31 rüzgâr — GERÇEK ArduPilot SITL ölçümü (oturum kodu üzerinden: SimSession._ruzgar_yaz / `wind` / esinti / `launch_aim` + SITL ev yönü).
Uygulama aynı süreçte (uvicorn iş parçacığı), HEPGO_SITL=1, ikililer HEPGO_SITL_DIR (vars. /opt/hepgo/sitl/bin). Kapanışta oturumlar silinir
(SITL süreçleri oturum kodu tarafından kendi PID'leriyle durdurulur). Sonuç tablosu stdout'a; ayrıntı docs/ucus-simulatoru.md §31.3.
Çalıştırma: ./.venv/bin/python -m tests.wind_sitl_olcum            (WSO_ONLY=copter,plane,ramp ile alt küme)
"""
import math
import os
import shutil
import socket
import statistics as st
import sys
import threading
import time

DATA = '/tmp/wind-sitl-olcum-data'
shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo',
                  HEPGO_SITL='1', HEPGO_SITL_DIR=os.environ.get('HEPGO_SITL_DIR') or '/opt/hepgo/sitl/bin', SIM_UDP_BASE='39950', SIM_TERRAIN_SERVE='0')
ONLY = set(filter(None, (os.environ.get('WSO_ONLY') or '').split(',')))
PORT = 8881
BASE = f'http://127.0.0.1:{PORT}'

import requests  # noqa: E402
import uvicorn  # noqa: E402

from app import flightsim  # noqa: E402
from app.main import app  # noqa: E402

server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=PORT, log_level='error'))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(160):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close(); break
    except OSError:
        time.sleep(0.25)
else:
    sys.exit('sunucu açılmadı')
s = requests.Session()
assert s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'}).status_code == 200
s.post(f'{BASE}/api/kvkk/accept-terms', json={})
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Ölçüm', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
S = f'{BASE}/api/drone/sim/sessions'
SONUC = []


def bekle(fn, sn, ad):
    t0 = time.time()
    while time.time() - t0 < sn:
        try:
            if fn():
                return True
        except Exception:   # noqa: BLE001
            pass
        time.sleep(0.2)
    raise RuntimeError(f'{ad}: {sn} sn içinde olmadı')


def cmd(sid, name, params=None):
    r = s.post(f'{S}/{sid}/cmd', json={'name': name, 'params': params or {}})
    if r.status_code != 200:
        raise RuntimeError(f'cmd {name} {r.status_code} {r.text[:200]}')
    return r.json()


OLAYLAR = []


def oturum(body):
    r = s.post(S, json=body); assert r.status_code == 201, r.text
    sid = r.json()['id']; ss = flightsim.MANAGER.sessions[sid]
    eski = ss._yay
    ss._yay = lambda m: (OLAYLAR.append(m.get('text')) if m.get('t') == 'event' else None, eski(m))[1]   # olay şeridi (teşhis)
    bekle(lambda: ss.state == 'HAZIR' and ss._heartbeat_alindi and ss.tele.get('gps_fix', 0) >= 3 and ss.tele.get('home'), 150, 'HAZIR + GPS + HOME')
    time.sleep(12)   # EKF hizalaması
    return sid, ss


def ne(ss):
    t = ss.tele; k = math.cos(math.radians(39.925))
    return ((t['lat'] - 39.925) * 110574, (t['lon'] - 32.837) * 111320 * k)


def ornek(ss, sn, hz=5):
    out = []
    for _ in range(int(sn * hz)):
        t = ss.tele; out.append({k: t.get(k) for k in ('groundspeed', 'airspeed', 'heading', 'roll', 'pitch', 'yaw', 'alt_rel', 'wind_spd', 'vn', 've')} | {'ne': ne(ss)})
        time.sleep(1 / hz)
    return out


def yaz(*a):
    print(*a, flush=True); SONUC.append(' '.join(str(x) for x in a))


try:
    # ---------- 1) kopter: ALT_HOLD'da (konum tutma yok) rüzgârla sürüklenme + LOITER'da rüzgâra karşı eğim ----------
    if not ONLY or 'copter' in ONLY:
        sid, ss = oturum({'mode': 'sitl', 'type': 'multirotor', 'center_id': c['id'], 'rec': {'bin': False}, 'world': {'mode': 'procedural', 'wind_ms': 0, 'wind_dir': 270}})
        for _ in range(12):   # EKF konum kestirimi hazır olana dek GUIDED + ARM + NAV_TAKEOFF yinelenir
            cmd(sid, 'mode', {'mode': 'GUIDED'}); time.sleep(1); cmd(sid, 'arm'); time.sleep(2); cmd(sid, 'takeoff', {'alt': 25}); time.sleep(4)
            if (ss.tele.get('alt_rel') or 0) > 2:
                break
        try:
            bekle(lambda: (ss.tele.get('alt_rel') or 0) > 22, 60, 'kopter kalkış')
        except RuntimeError:
            print('olaylar:', OLAYLAR[-25:], 'tele:', {k: ss.tele.get(k) for k in ('mode', 'armed', 'alt_rel', 'gps_fix')}, flush=True); raise
        time.sleep(4)
        rc_dur = threading.Event()

        def rc_dongu():
            while not rc_dur.is_set():
                try:
                    cmd(sid, 'rc', {'ch': [1500, 1500, 1500, 1500, 0, 0, 0, 0]})
                except Exception:   # noqa: BLE001
                    pass
                time.sleep(0.2)
        th = threading.Thread(target=rc_dongu, daemon=True); th.start()
        for ms in (0, 8):
            cmd(sid, 'mode', {'mode': 'LOITER'}); cmd(sid, 'wind', {'ms': ms, 'dir': 270}); time.sleep(10)   # rüzgâr uçuşta değişti (wind komutu)
            lo = ornek(ss, 10)
            egim = st.mean(math.degrees(math.hypot(o['roll'] or 0, o['pitch'] or 0)) for o in lo)
            p0 = ne(ss); cmd(sid, 'mode', {'mode': 'ALT_HOLD'}); time.sleep(15); p1 = ne(ss)
            dn, de = p1[0] - p0[0], p1[1] - p0[1]
            yaz(f'KOPTER rüzgâr {ms:>2} m/s 270°: LOITER ort. eğim {egim:5.2f}° · ALT_HOLD 15 sn sürüklenme {math.hypot(dn, de):6.1f} m (K {dn:+.1f}, D {de:+.1f}) · tele.wind_spd {ss.tele.get("wind_spd")}')
            cmd(sid, 'mode', {'mode': 'LOITER'}); time.sleep(3)
        # esinti: SIM_WIND_SPD 1 Hz (sunucu), türbülans SIM_WIND_TURB
        cmd(sid, 'wind', {'ms': 5, 'dir': 270, 'gust': 5, 'turb': 0}); ws = [o['wind_spd'] for o in ornek(ss, 15, 2)]
        yaz(f'KOPTER esinti 5+5 m/s: tele.wind_spd {min(ws):.2f}…{max(ws):.2f} m/s (SITL SIM_WIND_SPD = {ss.param_son.get("SIM_WIND_SPD")})')
        rc_dur.set(); th.join(2)
        s.delete(f'{S}/{sid}')
    # ---------- 2) sabit kanat: LOITER dairesinde yer hızı salınımı (rüzgâr), türbülansta hava hızı oynaklığı ----------
    if not ONLY or 'plane' in ONLY:
        sid, ss = oturum({'mode': 'sitl', 'type': 'sabit_kanat', 'center_id': c['id'], 'rec': {'bin': False}, 'world': {'mode': 'procedural', 'wind_ms': 0, 'wind_dir': 270, 'runway_heading': 0, 'launch': {'method': 'wheels'}}})
        cmd(sid, 'takeoff', {'alt': 80}); bekle(lambda: (ss.tele.get('alt_rel') or 0) > 60, 120, 'uçak kalkış')
        cmd(sid, 'mode', {'mode': 'LOITER'}); time.sleep(15)
        for w in ({'ms': 0, 'turb': 0}, {'ms': 8, 'turb': 0}, {'ms': 8, 'turb': 3}):
            cmd(sid, 'wind', {**w, 'dir': 270}); time.sleep(12)
            o = ornek(ss, 45)
            g = [x['groundspeed'] for x in o if x['groundspeed'] is not None]; a = [x['airspeed'] for x in o if x['airspeed'] is not None]
            yaz(f'UÇAK LOITER rüzgâr {w["ms"]} m/s turb {w["turb"]}: yer hızı {min(g):5.1f}…{max(g):5.1f} (aralık {max(g) - min(g):4.1f}) · hava hızı {st.mean(a):5.1f} ± {st.pstdev(a):4.2f} m/s')
        s.delete(f'{S}/{sid}')
    # ---------- 3) rampa yönü = SITL ev/burun yönü; launch_aim ile yön değişince yeniden konuşlandırma ----------
    if not ONLY or 'ramp' in ONLY:
        sid, ss = oturum({'mode': 'sitl', 'type': 'sabit_kanat', 'center_id': c['id'], 'rec': {'bin': False}, 'world': {'mode': 'procedural', 'wind_ms': 0, 'runway_heading': 0, 'launch': {'method': 'ramp', 'angle_deg': 15, 'azimuth_deg': 120}}})
        yaz(f'RAMPA azimut 120°: SITL ilk yön {ss.tele.get("heading")}° (yaw {math.degrees(ss.tele.get("yaw") or 0) % 360:.1f}°)')
        t0 = time.time(); r = cmd(sid, 'launch_aim', {'azimuth_deg': 210, 'angle_deg': 20})
        bekle(lambda: ss.state == 'HAZIR' and ss._heartbeat_alindi and ss.tele.get('gps_fix', 0) >= 3, 120, 'yeniden konuşlandırma')
        yaz(f'RAMPA launch_aim 210°/20°: redeploy={r.get("redeploy")} · {time.time() - t0:.1f} sn sonra HAZIR · SITL yön {ss.tele.get("heading")}° · TKOFF_LVL_PITCH {ss.param_son.get("TKOFF_LVL_PITCH")}')
        time.sleep(8)
        r = cmd(sid, 'launch_aim', {'angle_deg': 25})
        time.sleep(2)
        yaz(f'RAMPA yalnız açı 25°: redeploy={r.get("redeploy")} · TKOFF_LVL_PITCH {ss.param_son.get("TKOFF_LVL_PITCH")}')
        p0 = ne(ss); cmd(sid, 'takeoff', {'alt': 60}); bekle(lambda: (ss.tele.get('alt_rel') or 0) > 15, 90, 'rampa kalkış')
        p1 = ne(ss)
        yaz(f'RAMPA fırlatma: yer izi kerterizi {math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0])) % 360:.1f}° (rampa 210°) · faz {ss.launch_phase}')
        s.delete(f'{S}/{sid}')
finally:
    for sid in list(flightsim.MANAGER.sessions):
        try:
            s.delete(f'{S}/{sid}')
        except Exception:   # noqa: BLE001
            pass
    print('\n=== ÖZET ===\n' + '\n'.join(SONUC), flush=True)
    server.should_exit = True
    time.sleep(5)
