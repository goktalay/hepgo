"""Uçuş Simülatörü (drone.sim) — sözleşme §7: meta, oturum aç/limit/kapat, komut yetkisi (salt okuyan 403), WS hello/tele (50 Hz sahte akış, rc override + serbest bırakma paketi),
UDP köprüsü (sahte "SITL" TCP sunucusu ile ham bayt gidiş-dönüş, GCS kilidi). SITL yok: HEPGO_SITL=0 sahte kinematik.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_flightsim
"""
import json
import os
import socket
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

TELE_ALANLARI = {'rs', 'ps', 'ys', 'tbm', 'ts', 'lat', 'lon', 'alt_msl', 'alt_rel', 'roll', 'pitch', 'yaw', 'vn', 've', 'vd', 'airspeed', 'groundspeed', 'heading', 'climb',
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


def ws_bekle(ws, kosul, sn=3.0):
    """WS'den kosul(msg) doğru olan ilk mesajı döndürür (uykusuz: 50 Hz tele kuyruğunu geriden takip etmez)."""
    bitis = time.time() + sn
    while time.time() < bitis:
        m = json.loads(ws.receive_text())
        if kosul(m):
            return m
    return None


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
                res = ws_bekle(ws, lambda m: m['t'] == 'res', 3)
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
            assert {'rs', 'ps', 'ys', 'tbm'} <= set(t0) and isinstance(t0['tbm'], int) and t0['tbm'] > 0, t0   # açısal hızlar + SITL zaman damgası
            # --- 50 Hz sahte akış: 1 sn'de ≥ 40 tele, ardışık ts farkı ort. ≤ 25 ms, ts sunucu alım zamanı (Unix sn) ---
            ts_liste = []
            bitis = time.time() + 1.0
            while time.time() < bitis:
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele':
                    ts_liste.append(m['ts'])
            farklar = [b - a for a, b in zip(ts_liste, ts_liste[1:])]
            assert len(ts_liste) >= 40, len(ts_liste)
            assert sum(farklar) / len(farklar) <= 0.025, sum(farklar) / len(farklar)
            assert abs(ts_liste[-1] - time.time()) < 2, (ts_liste[-1], time.time())
            ws.send_text(json.dumps({'t': 'ping'}))
            assert ws_bekle(ws, lambda x: x['t'] == 'pong', 2)
            # --- RC override: değer paketi hemen ardından serbest bırakma paketi (8×0) hız sınırına takılmaz, kanallar varsayılana döner ---
            ws.send_text(json.dumps({'t': 'rc', 'ch': [1600, 1400, 1900, 1500, 2000, 1500, 1500, 1500]}))
            assert ws_bekle(ws, lambda x: x['t'] == 'tele' and x['rc'][2] == 1900 and x['rc'][4] == 2000, 3), 'rc override tele\'ye yansımadı'
            ws.send_text(json.dumps({'t': 'rc', 'ch': [1650, 1500, 1950, 1500, 1500, 1500, 1500, 1500]}))   # < 25 ms: hız sınırı atar
            ws.send_text(json.dumps({'t': 'rc', 'ch': [0] * 8}))                                              # serbest: atılmaz
            assert ws_bekle(ws, lambda x: x['t'] == 'tele' and x['rc'] == list(flightsim.SahteKinematik.RC_VARSAYILAN), 3), 'rc serbest bırakma işlenmedi'
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
            m = ws_bekle(ws, lambda x: x['t'] == 'tele' and x['armed'], 3)
            assert m and m['mode'] == 'GUIDED', m
            # geçersiz WS komutu → res ok:false
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'mode', 'params': {'mode': 'UCUS'}, 'rid': 'c3'}))
            m = ws_bekle(ws, lambda x: x['t'] == 'res' and x.get('rid') == 'c3', 3)
            assert m and m['ok'] is False and 'mod' in m['error'].lower(), m
            # reset → state BASLIYOR/HAZIR, kinematik sıfır
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'reset', 'rid': 'c4'}))
            m = ws_bekle(ws, lambda x: x['t'] == 'tele' and not x['armed'] and x['alt_rel'] == 0, 3)
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
            m = ws_bekle(ws, lambda x: x['t'] == 'tele' and x['gcs_connected'], 3)
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
            m = ws_bekle(ws, lambda x: x['t'] == 'end', 3)
            assert m and m['reason'] == 'kapatildi', m
        assert ok(a.get('/api/drone/sim/sessions')) == []
        assert a.get(f'/api/drone/sim/sessions/{sid}').status_code == 404
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.bind(('0.0.0.0', udp_port)); sk.close()   # port serbest
        # yeniden açılabilir (limit sayacı düştü); lifespan kapanışı kalanı temizler
        s3 = ok(a.post('/api/drone/sim/sessions', json={'type': 'hexarotor', 'center_id': c1['id']}), 201)
        assert s3['id'] == sid + 2 and s3['udp_port'] == udp_port   # ilk boş port yeniden verilir
    assert flightsim.MANAGER.sessions == {}, flightsim.MANAGER.sessions   # lifespan: kapat_hepsi
    sitl.kapat()
    print('Uçuş Simülatörü testleri geçti.')


if __name__ == '__main__':
    main()
