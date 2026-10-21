# §31 KARA ARACI doğrulaması — GERÇEK ArduRover 4.7.2 SITL, HEPGO sunucusu (aynı süreçte, iş parçacığı) üzerinden. Kapanışta lifespan oturumları ve
# SITL süreçlerini kapatır (pkill yok). Kullanım:
#   HEPGO_SITL_DIR=/opt/hepgo/sitl/bin .venv/bin/python -m tools.sitl.dogrula_rover [ackermann|skid|ikisi]
# Senaryo (her sürüş biçimi için): rover oturumu → kalp atışı (MAV_TYPE_GROUND_ROVER, kip listesi) → `takeoff` 400 denetimi → MANUAL + ARM → RC override
# (RC3 gaz %60, RC1 direksiyon) 8 sn düz + 6 sn dönüş: hız / yön hızı / konum → HOLD (durma) → Mission Planner yerine pymavlink (UDP, GCS kilidi) ile
# 3 noktalı kısa görev (≈ 60 m üçgen) yüklenir → AUTO: her WP'ye varış süresi ve en yakın mesafe → RTL: eve dönüş mesafesi → DISARM.
# Çıktı: /tmp/rover-sitl/sonuc.json + stdout ÖZET.
import json
import math
import os
import shutil
import socket
import sys
import threading
import time

SECIM = sys.argv[1] if len(sys.argv) > 1 else 'ikisi'
OUT = os.environ.get('DOGRULA_OUT', '/tmp/rover-sitl')
DATA = f'{OUT}/data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/sitl/bin')
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', HEPGO_SITL='1', SIM_UDP_BASE=os.environ.get('DOGRULA_UDP', '39450'),
                  SIM_TERRAIN_SERVE='0')
PORT = int(os.environ.get('DOGRULA_PORT', '8849'))
BASE = f'http://127.0.0.1:{PORT}'

import requests  # noqa: E402
import uvicorn  # noqa: E402
from pymavlink import mavutil  # noqa: E402

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
assert s.post(f'{BASE}/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}).status_code == 200
c = s.post(f'{BASE}/api/drone/centers', json={'name': 'Rover Sahası', 'lat': 39.925, 'lon': 32.837, 'alt': 900}).json()
SONUC = {}


def cmd(sid, name, params=None):
    r = s.post(f'{BASE}/api/drone/sim/sessions/{sid}/cmd', json={'name': name, 'params': params or {}})
    return r.status_code, (r.json() if r.headers.get('content-type', '').startswith('application/json') else r.text)


def bekle(pred, sn, adim=0.2):
    t0 = time.time()
    while time.time() - t0 < sn:
        if pred():
            return time.time() - t0
        time.sleep(adim)
    return None


def yerel(lat0, lon0, lat, lon):
    return ((lon - lon0) * 111320 * math.cos(math.radians(lat0)), (lat - lat0) * 110574)


def nokta(lat0, lon0, e, n):
    return lat0 + n / 110574, lon0 + e / (111320 * math.cos(math.radians(lat0)))


def gorev_yukle(udp_port, wps):
    """Mission Planner taklidi: UDP'den GCS olarak bağlan, MISSION_COUNT → istenen MISSION_ITEM_INT'ler → MISSION_ACK."""
    m = mavutil.mavlink_connection(f'udpout:127.0.0.1:{udp_port}', source_system=254, source_component=190)
    m.mav.heartbeat_send(6, 8, 0, 0, 0)
    hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=10)
    while hb is not None and hb.type in (6, 18):
        hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=10)
    assert hb is not None, 'GCS: araç kalp atışı yok'
    sysid, comp = hb.get_srcSystem(), hb.get_srcComponent()
    items = [(0, 16, 0, 0, 0)] + [(3, 16, la, lo, 0) for la, lo in wps]   # 0: ev (yok sayılır), sonra NAV_WAYPOINT (frame 3 GLOBAL_RELATIVE_ALT)
    m.mav.mission_count_send(sysid, comp, len(items), 0)
    t0 = time.time()
    while time.time() - t0 < 20:
        r = m.recv_match(type=['MISSION_REQUEST_INT', 'MISSION_REQUEST', 'MISSION_ACK'], blocking=True, timeout=3)
        if r is None:
            m.mav.heartbeat_send(6, 8, 0, 0, 0)
            continue
        if r.get_type() == 'MISSION_ACK':
            m.close()
            return r.type, hb.type
        fr, cm, la, lo, z = items[r.seq]
        m.mav.mission_item_int_send(sysid, comp, r.seq, fr, cm, 0, 1, 0, 0, 0, 0, int(la * 1e7), int(lo * 1e7), z, 0)
    m.close()
    return None, hb.type


def senaryo(drive):
    out = {'drive': drive}
    r = s.post(f'{BASE}/api/drone/sim/sessions', json={'mode': 'sitl', 'type': 'rover', 'center_id': c['id'], 'drive': drive,
                                                        'world': {'mode': 'procedural', 'wind_ms': 0}})
    assert r.status_code == 201, r.text
    d = r.json()
    sid = d['id']
    ss = flightsim.MANAGER.sessions[sid]
    olaylar = []
    _olay0 = ss._olay
    ss._olay = lambda text, severity=6: (olaylar.append(f'{severity} {text}'), _olay0(text, severity))[1]   # STATUSTEXT / oturum olayları (özet)
    out['session'] = {k: d.get(k) for k in ('type', 'drive', 'ground')} | {'model': (d.get('model') or {}).get('id')}
    t = bekle(lambda: ss._heartbeat_alindi, 90)
    out['heartbeat_s'] = round(t, 1) if t is not None else None
    out['vtype'] = ss.vtype
    out['sitl_model'] = ss._sitl_modeli()
    out['modes'] = sorted(flightsim._modlar(ss.vtype or 10))
    out['takeoff'] = cmd(sid, 'takeoff', {'alt': 10})[0]
    out['motor_cut'] = cmd(sid, 'motor_cut', {'on': True})[0]
    te = ss.tele
    bekle(lambda: (te.get('gps_fix') or 0) >= 3 and te.get('home'), 60)
    out['ekf_gps_s'] = bekle(lambda: any('is using GPS' in e for e in olaylar), 60)   # konum gerektiren kipler (AUTO/RTL/GUIDED) EKF GPS'i kullanmadan reddedilir
    time.sleep(2)
    home = dict(te.get('home') or {'lat': te['lat'], 'lon': te['lon']})
    out['home'] = home
    # MANUAL + ARM
    cmd(sid, 'mode', {'mode': 'MANUAL'}); time.sleep(1)
    arm_t0 = time.time()
    for _ in range(6):
        cmd(sid, 'arm')
        if bekle(lambda: te.get('armed'), 3):
            break
    out['arm_s'] = round(time.time() - arm_t0, 1) if te.get('armed') else None
    out['mode_after_arm'] = te.get('mode')
    # düz sürüş (RC3 %60 ileri) 8 sn
    hiz = []
    t0 = time.time()
    while time.time() - t0 < 8:
        cmd(sid, 'rc', {'ch': [1500, 0, 1800, 0, 0, 0, 0, 0]}); time.sleep(0.25)
        hiz.append(te.get('groundspeed') or 0)
    e, n = yerel(home['lat'], home['lon'], te['lat'], te['lon'])
    out['manual_straight'] = {'max_ms': round(max(hiz), 2), 'end_ms': round(hiz[-1], 2), 'dist_m': round(math.hypot(e, n), 1), 'heading': te.get('heading'),
                              'alt_rel': te.get('alt_rel'), 'throttle': te.get('throttle'), 'servo': te.get('servo')}
    # dönüş: direksiyon tam sağ 6 sn
    h0 = te.get('heading') or 0
    yr = []
    t0 = time.time()
    while time.time() - t0 < 6:
        cmd(sid, 'rc', {'ch': [2000, 0, 1700, 0, 0, 0, 0, 0]}); time.sleep(0.25)
        yr.append(te.get('ys') or 0)
    out['manual_turn'] = {'heading_change': round(((te.get('heading') or 0) - h0) % 360, 1), 'max_yaw_rate_dps': round(math.degrees(max(yr, key=abs)), 1),
                          'servo': te.get('servo'), 'speed': te.get('groundspeed')}
    cmd(sid, 'rc', {'ch': [0] * 8})
    cmd(sid, 'mode', {'mode': 'HOLD'})
    out['hold_stop_s'] = bekle(lambda: (te.get('groundspeed') or 0) < 0.3, 15)
    # görev: evden ~60 m üçgen (kuzeydoğu)
    la0, lo0 = te['lat'], te['lon']
    wps = [nokta(la0, lo0, 30, 30), nokta(la0, lo0, 60, -10), nokta(la0, lo0, 15, -40)]
    ack, hbt = gorev_yukle(ss.udp_port, wps)
    out['mission_ack'] = ack
    out['gcs_heartbeat_type'] = hbt
    time.sleep(1)
    out['auto_cmd'] = cmd(sid, 'mode', {'mode': 'AUTO'})[0]
    bekle(lambda: te.get('mode') == 'AUTO', 5)
    yakin = [1e9] * len(wps)
    varis = [None] * len(wps)
    t0 = time.time()
    hizlar = []
    while time.time() - t0 < 90:
        for i, (la, lo) in enumerate(wps):
            dd = math.hypot(*yerel(la, lo, te['lat'], te['lon']))
            if dd < yakin[i]:
                yakin[i] = dd
            if dd < 4 and varis[i] is None:
                varis[i] = round(time.time() - t0, 1)
        hizlar.append(te.get('groundspeed') or 0)
        if varis[-1] is not None or te.get('mode') != 'AUTO':
            break
        time.sleep(0.2)
    out['auto'] = {'arrive_s': varis, 'closest_m': [round(x, 1) for x in yakin], 'mode_end': te.get('mode'), 'mean_ms': round(sum(hizlar) / max(1, len(hizlar)), 2),
                   'route_points': len(ss.route)}
    # RTL
    out['rtl_cmd'] = cmd(sid, 'rtl')[0]
    t = bekle(lambda: math.hypot(*yerel(home['lat'], home['lon'], te['lat'], te['lon'])) < 3, 90)
    out['rtl'] = {'arrive_s': round(t, 1) if t is not None else None, 'home_dist_m': round(math.hypot(*yerel(home['lat'], home['lon'], te['lat'], te['lon'])), 1),
                  'mode': te.get('mode')}
    time.sleep(3)
    out['rtl']['mode_after'] = te.get('mode')
    out['rtl']['speed_after'] = te.get('groundspeed')
    cmd(sid, 'disarm')
    out['disarmed'] = bekle(lambda: not te.get('armed'), 10) is not None
    out['events_tail'] = [e for e in olaylar if not e.startswith('6 Komut')][-25:]
    s.delete(f'{BASE}/api/drone/sim/sessions/{sid}')
    time.sleep(3)
    return out


try:
    for dr in (['ackermann', 'skid'] if SECIM == 'ikisi' else [SECIM]):
        print(f'== {dr}', flush=True)
        SONUC[dr] = senaryo(dr)
        print(json.dumps(SONUC[dr], ensure_ascii=False, indent=1), flush=True)
finally:
    os.makedirs(OUT, exist_ok=True)
    with open(f'{OUT}/sonuc.json', 'w', encoding='utf-8') as f:
        json.dump(SONUC, f, ensure_ascii=False, indent=1)
    server.should_exit = True
    time.sleep(8)
