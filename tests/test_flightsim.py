"""Uçuş Simülatörü (drone.sim) — sözleşme §7: meta, oturum aç/limit/kapat, komut yetkisi (salt okuyan 403), WS hello/tele,
UDP köprüsü (sahte "SITL" TCP sunucusu ile ham bayt gidiş-dönüş, GCS kilidi). SITL yok: HEPGO_SITL=0 sahte kinematik.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_flightsim
"""
import json
import math
import os
import socket
import struct
import tempfile
import threading
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', SIM_UDP_BASE='24550', SIM_MAX_SESSIONS='2')

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app import auth, flightsim  # noqa: E402
from app.main import app  # noqa: E402

TELE_ALANLARI = {'ts', 'lat', 'lon', 'alt_msl', 'alt_rel', 'roll', 'pitch', 'yaw', 'vn', 've', 'vd', 'airspeed', 'groundspeed', 'heading', 'climb',
                 'mode', 'armed', 'gps_fix', 'sats', 'batt_v', 'batt_pct', 'throttle', 'rc', 'home', 'gcs_connected', 'gcs_addr'}


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json()


def login(c, u, p):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))
    return c.cookies.get(auth.COOKIE)


def bekle(fn, sn=5.0, adim=0.05):
    bitis = time.time() + sn
    while time.time() < bitis:
        v = fn()
        if v:
            return v
        time.sleep(adim)
    return fn()


def udp_al(sk, beklenen, port):
    """GCS soketinden beklenen ham baytı alır; sahte otopilotun 1 Hz MAVLink HEARTBEAT paketlerini (msgid 0) atlar."""
    bitis = time.time() + 3
    hb = 0
    while time.time() < bitis:
        data, addr = sk.recvfrom(4096)
        assert addr[1] == port, addr
        if data[:1] == b'\xfd' and len(data) == 21 and data[7:10] == b'\x00\x00\x00':
            hb += 1
            continue
        return data, hb
    raise AssertionError(f'{beklenen!r} gelmedi')


def close_code(ws):
    try:
        ws.receive_text()
    except WebSocketDisconnect as e:
        return e.code
    return None


class SahteSitl:
    """Sahte "SITL" SERIAL0: TCP dinler, gelen baytları biriktirir, istenirse istemciye bayt yazar."""

    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(2)
        self.port = self.srv.getsockname()[1]
        self.baglar = []          # açık istemci bağlantıları (kapanan oturumunki listeden düşer)
        self.alinan = bytearray()
        self.kilit = threading.Lock()
        threading.Thread(target=self._kabul, daemon=True).start()

    def _kabul(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            with self.kilit:
                self.baglar.append(c)
            threading.Thread(target=self._oku, args=(c,), daemon=True).start()

    def _oku(self, c):
        while True:
            try:
                d = c.recv(4096)
            except OSError:
                d = b''
            if not d:
                with self.kilit:
                    if c in self.baglar:
                        self.baglar.remove(c)
                return
            with self.kilit:
                self.alinan += d

    def yaz(self, data):
        with self.kilit:
            baglar = list(self.baglar)
        assert len(baglar) == 1, f'tek canlı SITL bağlantısı beklenir: {len(baglar)}'
        baglar[0].sendall(data)

    def kapat(self):
        try:
            self.srv.close()
        except OSError:
            pass


def tlog_yaz(yol, lat0=39.925, lon0=32.837, alt0=900.0, sure=60.0):
    """pymavlink ile küçük bir .tlog (8 bayt big-endian µs zaman damgası + MAVLink2 çerçevesi): 10 sn yerde (disarmed), ARM, 40 sn daire
    uçuşu (STABILIZE → LOITER), iniş, DISARM. Döner: (ilk ARM zamanı, ARM anındaki konum)."""
    from pymavlink.dialects.v20 import ardupilotmega as D
    mav = D.MAVLink(None, srcSystem=1, srcComponent=1)
    t_abs = 1_700_000_000.0
    arm_t, arm_pos = None, None
    with open(yol, 'wb') as f:
        def yaz(msg, t):
            f.write(struct.pack('>Q', int(t * 1e6)))
            f.write(msg.pack(mav))
            mav.seq = (mav.seq + 1) % 256
        t = 0.0
        while t <= sure:
            armed = 10.0 <= t < 55.0
            if armed and arm_t is None:
                arm_t = t
            mode = 5 if (armed and t >= 20) else 0   # ArduCopter LOITER=5 · STABILIZE=0
            if 15 <= t < 50 and armed:   # 10–15 dikey tırmanış (yerinde), sonra 100 m yarıçaplı daire
                ang = (t - 15) / 35 * 2 * math.pi
                r = 100.0
                lat, lon, z = lat0 + r * math.cos(ang) / 110574, lon0 + r * math.sin(ang) / (111320 * math.cos(math.radians(lat0))), 30.0
                vn, ve = -r * 2 * math.pi / 35 * math.sin(ang), r * 2 * math.pi / 35 * math.cos(ang)
            else:
                lat, lon, z, vn, ve = lat0, lon0, (30.0 * min(1, (t - 10) / 5) if armed and t < 50 else 0.0), 0.0, 0.0
            if armed and arm_pos is None:
                arm_pos = (lat, lon)
            yaw = math.atan2(ve, vn) if (vn or ve) else 0.0
            if abs(t - round(t)) < 1e-6:   # 1 Hz
                yaz(mav.heartbeat_encode(2, 3, (128 if armed else 0) | 1, mode, 4), t_abs + t)   # MAV_TYPE_QUADROTOR, ARDUPILOTMEGA; CUSTOM_MODE bayrağı
                yaz(mav.sys_status_encode(0, 0, 0, 500, 16200 - int(t * 10), 1200, 95 - int(t // 10), 0, 0, 0, 0, 0, 0), t_abs + t)
                yaz(mav.gps_raw_int_encode(int((t_abs + t) * 1e6), 3, int(lat * 1e7), int(lon * 1e7), int((alt0 + z) * 1000), 120, 80, 0, 0, 12), t_abs + t)
                if t == 0:
                    yaz(mav.statustext_encode(6, b'ArduCopter V4.5.7 (test)'), t_abs + t)
                if t == 10:
                    yaz(mav.statustext_encode(6, b'Arming motors'), t_abs + t)
                if t == 30:
                    yaz(mav.statustext_encode(4, b'Low battery warning (test)'), t_abs + t)
            yaz(mav.global_position_int_encode(int(t * 1000), int(lat * 1e7), int(lon * 1e7), int((alt0 + z) * 1000), int(z * 1000),
                                               int(vn * 100), int(ve * 100), 0, int((math.degrees(yaw) % 360) * 100)), t_abs + t)
            yaz(mav.attitude_encode(int(t * 1000), 0.1 if armed else 0.0, -0.05 if armed else 0.0, yaw, 0, 0, 0), t_abs + t)
            yaz(mav.rc_channels_encode(int(t * 1000), 8, 1500, 1500, 1600 if armed else 1000, 1500, 1800, 1000, 1000, 1500, *([0] * 10), 200), t_abs + t)
            yaz(mav.vfr_hud_encode(math.hypot(vn, ve) + 1, math.hypot(vn, ve), int(math.degrees(yaw) % 360), 55 if armed else 0, alt0 + z, 0.0), t_abs + t)
            t = round(t + 0.2, 3)   # 5 Hz
    return arm_t, arm_pos


def replay_testleri(a, c1, mon_token_login):
    """§8: ayrıştırıcı birim testi (.tlog) + /logs yetki kesişimi + replay oturumu + gzip kare ucu + WS (tele yok, cmd yalnız reset)."""
    import gzip
    from app import config, flightsim_replay as R
    yol = config.UPLOAD_DIR / 'flightlogs'
    yol.mkdir(parents=True, exist_ok=True)
    tl = yol / 'test-kayit.tlog'
    arm_t, arm_pos = tlog_yaz(tl)
    # --- ayrıştırıcı ---
    d = R.ayristir(tl)
    assert d['hz'] == R.REPLAY_HZ and d['fields'] == R.FIELDS and d['source'] == 'tlog' and d['type'] == 'multirotor' and d['vehicle'] == 'ArduCopter', (d['hz'], d['type'], d['vehicle'])
    assert 55 <= d['duration_s'] <= 60.5 and 5 * 55 <= d['n'] <= R.REPLAY_HZ * 61, (d['duration_s'], d['n'])   # 5 Hz kaynak → en çok 5 kare/sn tutulur
    assert abs(d['takeoff_t'] - arm_t) < 0.3 and abs(d['home']['lat'] - arm_pos[0]) < 1e-6 and abs(d['home']['lon'] - arm_pos[1]) < 1e-6 and abs(d['home']['alt'] - 900) < 0.01, (d['takeoff_t'], d['home'])
    assert d['modes'] == ['STABILIZE', 'LOITER'], d['modes']
    metinler = [e['text'] for e in d['events']]
    assert 'Mod: STABILIZE' in metinler and 'Mod: LOITER' in metinler and 'ARM — motorlar kuruldu' in metinler and 'DISARM — motorlar devre dışı' in metinler and 'Arming motors' in metinler, metinler
    uyari = next(e for e in d['events'] if 'Low battery' in e['text'])
    assert uyari['sev'] == 4 and 29.9 <= uyari['t'] <= 30.1, uyari
    FI = {k: i for i, k in enumerate(d['fields'])}
    assert d['frames'][0][FI['rc']] is None   # ilk konum karesi RC'den önce (sample-and-hold: henüz bilinmeyen alan None)
    k0, k30 = next(f for f in d['frames'] if f[FI['rc']]), next(f for f in d['frames'] if f[FI['t']] >= 30)
    assert k0[FI['armed']] == 0 and k0[FI['alt_rel']] == 0 and k0[FI['rc']][2] == 1000 and k0[FI['sats']] == 12 and k0[FI['fix']] == 3, k0
    assert k30[FI['armed']] == 1 and 29 <= k30[FI['alt_rel']] <= 31 and k30[FI['mode']] == 1 and k30[FI['rc']][2] == 1600 and 17 <= k30[FI['gs']] <= 18.5 and k30[FI['thr']] == 55, k30
    assert d['start_utc'].startswith('2023-11-14T22:13:20'), d['start_utc']
    # --- flight_logs kaydı (analiz TAMAM) ---
    from app import db
    with db.connect() as conn:
        cur = conn.execute('''INSERT INTO flight_logs (task_id, file, file_name, size, status, analysis, aircraft, pilot, location, uploaded_by, uploaded_at)
                              VALUES (NULL, ?, ?, ?, 'TAMAM', ?, 'CZ-TEST', 'Test Pilot', 'Akyurt', 1, ?)''',
                           ('flightlogs/test-kayit.tlog', 'test-kayit.tlog', tl.stat().st_size,
                            json.dumps({'summary': {'vehicle': 'ArduCopter', 'flight_s': 40, 'duration_s': 60, 'home': {'lat': 39.925, 'lng': 32.837}}}), db.now()))
        lid = cur.lastrowid
        conn.execute('''INSERT INTO flight_logs (task_id, file, file_name, size, status, uploaded_by, uploaded_at) VALUES (NULL, 'flightlogs/yarim.bin', 'yarim.bin', 10, 'ISLENIYOR', 1, ?)''', (db.now(),))
        conn.commit()
    # --- /logs: admin (tools) görür; analizi bitmemiş listelenmez; arama ---
    m = ok(a.get('/api/drone/sim/meta'))
    assert m['replay']['logs_allowed'] is True and m['replay']['hz'] == R.REPLAY_HZ and '.tlog' in m['replay']['formats'], m['replay']
    logs = ok(a.get('/api/drone/sim/logs'))
    assert [l['id'] for l in logs] == [lid] and logs[0]['ext'] == 'tlog' and logs[0]['type'] == 'multirotor' and logs[0]['cached'] is False and logs[0]['aircraft'] == 'CZ-TEST', logs
    assert ok(a.get('/api/drone/sim/logs?q=cz-test')) and ok(a.get('/api/drone/sim/logs?q=yokboyle')) == []
    # montaj: drone.sim var; Araçlar (tools) rolden kapatılır, Saha (field) zaten yok → log listesi boş, oturum açamaz (yazma yok → 403)
    ok(a.put('/api/roles/perms', params={'name': 'Montaj Personeli'}, json={'changes': [{'node': 'tools', 'cap': 'open', 'value': False}]}))
    mon = TestClient(app, base_url='https://testserver')
    login(mon, 'montaj', 'sifre-1234')
    assert not ({'tools', 'field'} & set(ok(mon.get('/api/auth/me'))['modules'])), ok(mon.get('/api/auth/me'))['modules']
    assert ok(mon.get('/api/drone/sim/meta'))['replay']['logs_allowed'] is False and ok(mon.get('/api/drone/sim/logs')) == []
    assert mon.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid}).status_code == 403
    # --- oturum: doğrulama ---
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay'}).status_code == 400
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': 99999}).status_code == 400
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid + 1}).status_code == 400   # ISLENIYOR
    assert a.post('/api/drone/sim/sessions', json={'mode': 'ucur', 'log_id': lid}).status_code == 400
    assert a.post('/api/drone/sim/sessions', json={'mode': 'sitl'}).status_code == 400   # type/center_id yok
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid, 'world': {'time': 'gece'}}).status_code == 400
    s = ok(a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid, 'world': {'seed': 3, 'time': 'night'}}), 201)
    assert s['mode'] == 'replay' and s['udp_port'] is None and s['type'] == 'multirotor' and s['replay']['log_id'] == lid and s['replay']['file_name'] == 'test-kayit.tlog', s
    assert s['world']['time'] == 'night' and s['gcs'] == {'connected': False, 'addr': None, 'since': None} and s['state'] in ('BASLIYOR', 'HAZIR'), s
    sid = s['id']
    g = bekle(lambda: (lambda r: r if r['state'] == 'HAZIR' else None)(ok(a.get(f'/api/drone/sim/sessions/{sid}'))), 10)
    assert g and g['replay']['frames'] == d['n'] and g['replay']['duration_s'] == d['duration_s'] and g['replay']['home'] == d['home'] and g['replay']['progress'] == 100, g and g['replay']
    assert g['center']['lat'] == d['home']['lat'] and g['center']['alt'] == d['home']['alt'] and g['replay']['modes'] == ['STABILIZE', 'LOITER'] and g['replay']['takeoff_t'] == d['takeoff_t'], g['center']
    assert R.onbellek_yolu(lid).exists() and ok(a.get('/api/drone/sim/logs'))[0]['cached'] is True
    # --- kareler (gzip JSON) ---
    r = a.get(f'/api/drone/sim/sessions/{sid}/replay')
    assert r.status_code == 200 and r.headers.get('content-type', '').startswith('application/json'), (r.status_code, r.headers)
    body = r.json()   # httpx Content-Encoding: gzip açar
    assert body['v'] == R.ONBELLEK_SURUM and body['n'] == d['n'] and len(body['frames']) == d['n'] and body['fields'] == R.FIELDS and body['home'] == d['home'] and len(body['events']) == len(d['events']), (body['n'], len(body['frames']))
    with gzip.open(R.onbellek_yolu(lid), 'rt', encoding='utf-8') as f:
        assert json.load(f)['n'] == d['n']
    # --- komutlar: yalnız reset; SITL komutları 400 ---
    assert a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'arm'}).status_code == 400
    assert a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'rc', 'params': {'ch': [1500] * 8}}).status_code == 400
    ok(a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'reset'}))
    # --- WS: hello (mode replay) · tele gelmez · cmd reset → res ok + replay reset yayını · cmd arm → ok:false ---
    token = a.cookies.get(auth.COOKIE)
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        hh = json.loads(ws.receive_text())
        assert hh['t'] == 'hello' and hh['session']['mode'] == 'replay' and hh['session']['state'] == 'HAZIR' and hh['session']['replay']['frames'] == d['n'], hh
        ws.send_text(json.dumps({'t': 'rc', 'ch': [1500] * 8}))
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'reset', 'rid': 'r1'}))
        gor = {}
        bitis = time.time() + 3
        while time.time() < bitis and not ({'res', 'replay'} <= set(gor)):
            mm = json.loads(ws.receive_text())
            assert mm['t'] != 'tele', 'kayıt oturumunda tele yayını olmamalı'
            gor[mm['t']] = mm
        assert gor['res']['ok'] is True and gor['res']['rid'] == 'r1' and gor['replay']['action'] == 'reset', gor
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'arm', 'rid': 'r2'}))
        mm = bekle(lambda: (lambda x: x if x['t'] == 'res' and x.get('rid') == 'r2' else None)(json.loads(ws.receive_text())), 3)
        assert mm and mm['ok'] is False and 'reset' in mm['error'], mm
        # kapat → end
        ok(a.delete(f'/api/drone/sim/sessions/{sid}'))
        mm = bekle(lambda: (lambda x: x if x['t'] == 'end' else None)(json.loads(ws.receive_text())), 3)
        assert mm and mm['reason'] == 'kapatildi', mm
    assert a.get(f'/api/drone/sim/sessions/{sid}/replay').status_code == 404
    # SITL oturumunda /replay 400; önbellekli ikinci açılış anında HAZIR
    s2 = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    assert s2['mode'] == 'sitl' and a.get(f"/api/drone/sim/sessions/{s2['id']}/replay").status_code == 400
    s3 = ok(a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid}), 201)
    g = bekle(lambda: (lambda r: r if r['state'] == 'HAZIR' else None)(ok(a.get(f"/api/drone/sim/sessions/{s3['id']}"))), 5)
    assert g and g['replay']['frames'] == d['n']
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid}).status_code == 409   # limit sayımına dahil
    ok(a.delete(f"/api/drone/sim/sessions/{s2['id']}")); ok(a.delete(f"/api/drone/sim/sessions/{s3['id']}"))
    # bozuk dosya → HATA (sitl.error), /replay 409
    bozuk = yol / 'bozuk.bin'
    bozuk.write_bytes(b'\x00' * 64)
    with db.connect() as conn:
        cur = conn.execute('''INSERT INTO flight_logs (task_id, file, file_name, size, status, analysis, uploaded_by, uploaded_at) VALUES (NULL, 'flightlogs/bozuk.bin', 'bozuk.bin', 64, 'TAMAM', '{}', 1, ?)''', (db.now(),))
        bid = cur.lastrowid
        conn.commit()
    s4 = ok(a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': bid}), 201)
    g = bekle(lambda: (lambda r: r if r['state'] in ('HATA', 'HAZIR') else None)(ok(a.get(f"/api/drone/sim/sessions/{s4['id']}"))), 10)
    assert g and g['state'] == 'HATA' and g['sitl']['error'], g
    assert a.get(f"/api/drone/sim/sessions/{s4['id']}/replay").status_code == 409
    ok(a.delete(f"/api/drone/sim/sessions/{s4['id']}"))
    # log silinince önbellek de silinir
    ok(a.delete(f'/api/tools/flight-logs/{lid}'))
    assert not R.onbellek_yolu(lid).exists()
    print('Kayıttan oynatma testleri geçti.')


def main():
    sitl = SahteSitl()
    flightsim.MANAGER.sahte_tcp_port = sitl.port
    with TestClient(app, base_url='https://testserver') as a:
        login(a, 'admin@test', 'admin-sifre-1')
        c1 = ok(a.post('/api/drone/centers', json={'name': 'Test Merkezi', 'lat': 39.925, 'lon': 32.837, 'alt': 900}))
        ok(a.post('/api/drone/centers', json={'name': 'Pasif Merkez', 'lat': 40.0, 'lon': 33.0, 'active': False}))
        # salt okuyan rol: Montaj Personeli'ne drone.sim yalnız aç + oku
        ok(a.post('/api/users', json={'username': 'montaj', 'full_name': 'Montaj', 'roles': ['Montaj Personeli'], 'password': 'sifre-1234'}))
        ok(a.put('/api/roles/perms', params={'name': 'Montaj Personeli'},
                 json={'changes': [{'node': 'drone.sim', 'cap': 'open', 'value': True}, {'node': 'drone.sim', 'cap': 'read', 'value': True}]}))
        ok(a.post('/api/users', json={'username': 'pilot', 'full_name': 'Pilot', 'roles': [auth.PILOT], 'password': 'sifre-1234'}))

        # --- meta ---
        m = ok(a.get('/api/drone/sim/meta'))
        assert {t['key'] for t in m['types']} == {'multirotor', 'hexarotor', 'helikopter', 'sabit_kanat', 'vtol'} and all(t['binary'] for t in m['types']), m
        assert [c['id'] for c in m['centers']] == [c1['id']] and m['centers'][0]['alt'] == 900, m   # pasif merkez listelenmez
        assert m['limits'] == {'max_sessions': 2, 'max_minutes': flightsim.MAX_MINUTES} and m['host'] == 'testserver' and m['can_command'] is True, m
        assert m['world_defaults']['seed'] == 12345

        # --- oturum aç: doğrulama ---
        assert a.post('/api/drone/sim/sessions', json={'type': 'ucan_hali', 'center_id': c1['id']}).status_code == 400
        assert a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': 99999}).status_code == 400
        assert a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id'], 'world': {'tree_density': 5}}).status_code == 400
        assert a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id'], 'world': {'time': 'gece'}}).status_code == 400
        world = {'seed': 7, 'size_m': 3000, 'tree_density': 0.5, 'wind_ms': 4, 'wind_dir': 90, 'time': 'dusk', 'runway': True}
        s = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id'], 'world': world}), 201)
        assert s['type'] == 'multirotor' and s['center']['id'] == c1['id'] and s['center']['lat'] == 39.925 and s['world']['seed'] == 7
        assert s['world']['mountain_height'] == 300 and s['world']['time'] == 'dusk', s   # eksikler varsayılanla dolar
        assert 24550 <= s['udp_port'] <= 24649 and s['host'] == 'testserver' and s['owner']['name'] == 'Sistem Yöneticisi' or s['owner']['id'], s
        assert s['state'] in ('BASLIYOR', 'HAZIR') and s['gcs'] == {'connected': False, 'addr': None, 'since': None}, s
        sid = s['id']
        g = bekle(lambda: (lambda r: r if r['state'] == 'HAZIR' else None)(ok(a.get(f'/api/drone/sim/sessions/{sid}'))))
        assert g and g['state'] == 'HAZIR' and g['sitl']['port'] == sitl.port, g
        # --- limit ---
        s2 = ok(a.post('/api/drone/sim/sessions', json={'type': 'sabit_kanat', 'center_id': c1['id']}), 201)
        assert s2['udp_port'] != s['udp_port']
        r = a.post('/api/drone/sim/sessions', json={'type': 'vtol', 'center_id': c1['id']})
        assert r.status_code == 409, (r.status_code, r.text)
        assert [x['id'] for x in ok(a.get('/api/drone/sim/sessions'))] == [sid, s2['id']]
        ok(a.delete(f"/api/drone/sim/sessions/{s2['id']}"))
        assert a.get(f"/api/drone/sim/sessions/{s2['id']}").status_code == 404
        assert a.delete(f"/api/drone/sim/sessions/{s2['id']}").status_code == 404
        assert [x['id'] for x in ok(a.get('/api/drone/sim/sessions'))] == [sid]

        # --- komutlar (REST) ---
        cmd = lambda name, params=None: a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': name, 'params': params or {}})   # noqa: E731
        assert cmd('ucur').status_code == 400
        assert cmd('rc', {'ch': [1500, 1500, 1500]}).status_code == 400
        assert cmd('rc', {'ch': [1500, 1500, 2500, 1500, 1500, 1500, 1500, 1500]}).status_code == 400
        assert cmd('takeoff', {'alt': 'yüksek'}).status_code == 400
        assert cmd('mode', {'mode': 'UCUS'}).status_code == 400
        ok(cmd('takeoff'))   # varsayılan irtifa (kopter 10 m)
        ok(cmd('mode', {'mode': 'LOITER'}))
        ok(cmd('rc', {'ch': [1500, 1500, 1800, 1500, 1500, 1500, 1500, 1500]}))
        ok(cmd('set_home', {'lat': 39.93, 'lon': 32.84, 'alt': 905}))

        # --- salt okuyan rol: görür ama komut veremez / oturum açamaz ---
        if True:   # yardımcı istemciler with'siz: `with TestClient` çıkışı lifespan kapanışını (kapat_hepsi) tetikler
            mon = TestClient(app, base_url='https://testserver')
            mtoken = login(mon, 'montaj', 'sifre-1234')
            mm = ok(mon.get('/api/drone/sim/meta'))
            assert mm['can_command'] is False
            assert [x['id'] for x in ok(mon.get('/api/drone/sim/sessions'))] == [sid]
            assert mon.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'arm'}).status_code == 403
            assert mon.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id']}).status_code == 403
            assert mon.delete(f'/api/drone/sim/sessions/{sid}').status_code == 403
            # WS: izler, komut reddedilir
            with mon.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={mtoken}'}) as ws:
                h = json.loads(ws.receive_text())
                assert h['t'] == 'hello' and h['session']['id'] == sid and h['can_command'] is False, h
                ws.send_text(json.dumps({'t': 'cmd', 'name': 'arm', 'rid': 'r1'}))
                res = bekle(lambda: (lambda m: m if m['t'] == 'res' else None)(json.loads(ws.receive_text())), 3)
                assert res and res['ok'] is False and res['rid'] == 'r1', res
        # drone paketine erişimi olmayan rol (Pilot var ama bu kullanıcı 'drone' modülünde değil?) → Pilot drone'a sahiptir; yetkisiz rol: Güvenlik
        ok(a.post('/api/users', json={'username': 'guv', 'full_name': 'Guv', 'roles': ['Güvenlik'], 'password': 'sifre-1234'}))
        if True:
            guv = TestClient(app, base_url='https://testserver')
            gtoken = login(guv, 'guv', 'sifre-1234')
            assert guv.get('/api/drone/sim/meta').status_code == 403
            with guv.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={gtoken}'}) as ws:
                assert json.loads(ws.receive_text()) == {'t': 'error', 'error': 'auth'}
                assert close_code(ws) == 4403
        # çerezsiz → 4403; olmayan oturum → 4404
        with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': 'yok=1'}) as ws:
            assert json.loads(ws.receive_text())['error'] == 'auth' and close_code(ws) == 4403
        token = a.cookies.get(auth.COOKIE)
        with a.websocket_connect('/ws/drone/sim/99999', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
            assert json.loads(ws.receive_text())['error'] == 'not_found' and close_code(ws) == 4404

        # --- WS: hello + telemetri (sahte kinematik komutlara tepki verir) ---
        with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
            h = json.loads(ws.receive_text())
            assert h['t'] == 'hello' and h['session']['state'] == 'HAZIR' and h['can_command'] is True, h
            teles = []
            bitis = time.time() + 3
            while time.time() < bitis and len(teles) < 5:
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele':
                    teles.append(m)
            assert len(teles) >= 2, len(teles)
            t0 = teles[-1]
            assert TELE_ALANLARI <= set(t0), TELE_ALANLARI - set(t0)
            assert t0['armed'] is True and t0['mode'] == 'LOITER' and t0['alt_rel'] > 0 and len(t0['rc']) == 8 and t0['rc'][2] == 1800, t0
            assert t0['home'] == {'lat': 39.93, 'lon': 32.84, 'alt': 905.0} and t0['gcs_connected'] is False and t0['gcs_addr'] is None, t0
            assert abs(t0['lat'] - 39.925) < 0.01 and abs(t0['lon'] - 32.837) < 0.01 and t0['alt_msl'] > 900, t0
            ws.send_text(json.dumps({'t': 'ping'}))
            assert bekle(lambda: json.loads(ws.receive_text())['t'] == 'pong', 2)
            # WS komutu: crash → disarm + olay; rc akışı
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'crash', 'rid': 'c1'}))
            gor = {'res': None, 'event': None, 'tele': None}
            bitis = time.time() + 3
            while time.time() < bitis and not all(gor.values()):
                m = json.loads(ws.receive_text())
                if m['t'] == 'res':
                    gor['res'] = m
                elif m['t'] == 'event' and 'ÇARPIŞMA' in m['text']:
                    gor['event'] = m
                elif m['t'] == 'tele' and m['armed'] is False:
                    gor['tele'] = m
            assert gor['res'] and gor['res']['ok'] is True and gor['res']['rid'] == 'c1', gor['res']
            assert gor['event'] and gor['event']['severity'] == 2 and gor['tele'] and gor['tele']['alt_rel'] == 0, gor
            ws.send_text(json.dumps({'t': 'rc', 'ch': [1500, 1500, 1200, 1500, 1500, 1500, 1500, 1500]}))
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'takeoff', 'params': {'alt': 30}, 'rid': 'c2'}))
            m = bekle(lambda: (lambda x: x if x['t'] == 'tele' and x['armed'] else None)(json.loads(ws.receive_text())), 3)
            assert m and m['mode'] == 'GUIDED', m
            # geçersiz WS komutu → res ok:false
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'mode', 'params': {'mode': 'UCUS'}, 'rid': 'c3'}))
            m = bekle(lambda: (lambda x: x if x['t'] == 'res' and x.get('rid') == 'c3' else None)(json.loads(ws.receive_text())), 3)
            assert m and m['ok'] is False and 'mod' in m['error'].lower(), m
            # reset → state BASLIYOR/HAZIR, kinematik sıfır
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'reset', 'rid': 'c4'}))
            m = bekle(lambda: (lambda x: x if x['t'] == 'tele' and not x['armed'] and x['alt_rel'] == 0 else None)(json.loads(ws.receive_text())), 3)
            assert m, 'reset sonrası sıfır telemetri gelmedi'

            # --- UDP köprüsü: GCS (UDP) ↔ sahte SITL (TCP) ham bayt; GCS kilidi ---
            udp_port = h['session']['udp_port']
            gcs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            gcs.bind(('127.0.0.1', 0))
            gcs.settimeout(3)
            gcs.sendto(b'\xfd\x09GCS-PAKET-1', ('127.0.0.1', udp_port))
            assert bekle(lambda: bytes(sitl.alinan).endswith(b'GCS-PAKET-1'), 3), bytes(sitl.alinan)
            sitl.yaz(b'\xfd\x05SITL-TELE-1')
            data, hb = udp_al(gcs, b'\xfd\x05SITL-TELE-1', udp_port)
            assert data == b'\xfd\x05SITL-TELE-1', data
            # GCS bağlanınca sahte otopilot 1 Hz MAVLink HEARTBEAT da gönderir (Mission Planner 'bağlı' görsün)
            if not hb:
                d2, _ = gcs.recvfrom(4096)
                assert d2[:1] == b'\xfd' and len(d2) == 21 and d2[7:10] == b'\x00\x00\x00', d2
            # oturumda GCS görünür (REST + tele)
            g = ok(a.get(f'/api/drone/sim/sessions/{sid}'))
            assert g['gcs']['connected'] is True and g['gcs']['addr'] == f'127.0.0.1:{gcs.getsockname()[1]}' and g['gcs']['since'], g
            m = bekle(lambda: (lambda x: x if x['t'] == 'tele' and x['gcs_connected'] else None)(json.loads(ws.receive_text())), 3)
            assert m and m['gcs_addr'] == g['gcs']['addr'], m
            # ikinci adres: iletilmez (kilit); ilk GCS'nin paketi iletilir
            sahtekar = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sahtekar.bind(('127.0.0.1', 0))
            sahtekar.settimeout(0.5)
            once = len(sitl.alinan)
            sahtekar.sendto(b'SAHTEKAR', ('127.0.0.1', udp_port))
            time.sleep(0.5)
            assert len(sitl.alinan) == once and b'SAHTEKAR' not in bytes(sitl.alinan)
            gcs.sendto(b'GCS-PAKET-2', ('127.0.0.1', udp_port))
            assert bekle(lambda: bytes(sitl.alinan).endswith(b'GCS-PAKET-2'), 3)
            sitl.yaz(b'SITL-TELE-2')
            assert udp_al(gcs, b'SITL-TELE-2', udp_port)[0] == b'SITL-TELE-2'
            try:
                sahtekar.recvfrom(4096)
                raise AssertionError('kilit dışı adres SITL verisi almamalı')
            except socket.timeout:
                pass
            ses = flightsim.MANAGER.get(sid)
            assert ses.gcs_rx == 2 and ses.gcs_atilan == 1 and ses.sitl_rx == len(b'\xfd\x05SITL-TELE-1') + len(b'SITL-TELE-2'), (ses.gcs_rx, ses.gcs_atilan, ses.sitl_rx)
            # kilit sessizlikte kalkar (süreyi kısaltarak): yeni adres GCS olur
            ses.gcs_last -= flightsim.GCS_SESSIZLIK + 1
            sahtekar.sendto(b'YENI-GCS', ('127.0.0.1', udp_port))
            assert bekle(lambda: bytes(sitl.alinan).endswith(b'YENI-GCS'), 3)
            g = ok(a.get(f'/api/drone/sim/sessions/{sid}'))
            assert g['gcs']['addr'] == f'127.0.0.1:{sahtekar.getsockname()[1]}', g
            gcs.close(); sahtekar.close()

            # --- kapat: WS 'end' alır, UDP portu boşalır, oturum listeden düşer ---
            ok(a.delete(f'/api/drone/sim/sessions/{sid}'))
            m = bekle(lambda: (lambda x: x if x['t'] == 'end' else None)(json.loads(ws.receive_text())), 3)
            assert m and m['reason'] == 'kapatildi', m
        assert ok(a.get('/api/drone/sim/sessions')) == []
        assert a.get(f'/api/drone/sim/sessions/{sid}').status_code == 404
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.bind(('0.0.0.0', udp_port)); sk.close()   # port serbest
        # yeniden açılabilir (limit sayacı düştü); lifespan kapanışı kalanı temizler
        s3 = ok(a.post('/api/drone/sim/sessions', json={'type': 'hexarotor', 'center_id': c1['id']}), 201)
        assert s3['id'] == sid + 2 and s3['udp_port'] == udp_port   # ilk boş port yeniden verilir
        ok(a.delete(f"/api/drone/sim/sessions/{s3['id']}"))
        # --- kayıttan oynatma (§8) ---
        replay_testleri(a, c1, None)
    assert flightsim.MANAGER.sessions == {}, flightsim.MANAGER.sessions   # lifespan: kapat_hepsi
    sitl.kapat()
    print('Uçuş Simülatörü testleri geçti.')


if __name__ == '__main__':
    main()
