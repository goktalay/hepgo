"""Uçuş Simülatörü §45 — PX4 SIH SITL uçtan uca (HEPGO API + WS + Mission Planner/QGC taklidi UDP):
oturum aç (stack px4, airframe, parametre dosyası) → HAZIR → GCS kalp atışı köprüden PX4 HEARTBEAT (MAV_AUTOPILOT_PX4) alır → ARM + kalkış
→ tele alanları dolu (konum, yönelim, hız, GPS, batarya, PX4 kip adı) → takma ad kipi (LOITER → AUTO.LOITER) → desteklenmeyen komut gerekçeli 400
→ RTL (iniş + disarm) → Sıfırla (aynı ayarlarla yeni süreç) → kapat (süreç sonlanır). Tipler: kopter (10040), sabit kanat (10041, pist kalkışı),
VTOL (10043). PX4_E2E_TIPLER ile daraltılabilir (ör. multirotor).

Çalıştırma: HEPGO_SITL_DIR=/opt/hepgo/sitl/bin .venv/bin/python -m tests.test_flightsim_px4_sitl   (~3–5 dk; PX4 /opt/hepgo/sitl/px4)
"""
import faulthandler
import json
import os
import socket
import tempfile
import time

faulthandler.dump_traceback_later(900, exit=True)
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(prefix='px4-sitl-'), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='1', SIM_UDP_BASE='26250', SIM_MAX_SESSIONS='1', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/sitl/bin')

from fastapi.testclient import TestClient  # noqa: E402
from pymavlink.dialects.v20 import ardupilotmega as D  # noqa: E402

from app import drone_sitl, flightsim  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_flightsim_match import Kullanici, bekle, ok  # noqa: E402

MERKEZ = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}
S = '/api/drone/sim/sessions'
SENARYO = {   # tip → (airframe, kalkış m, başarı eşiği m)
    'multirotor': (10040, 15, 12),
    'sabit_kanat': (10041, 40, 20),
    'vtol': (10043, 20, 15),
}


class Akis:
    def __init__(self, ws):
        self.ws, self.tele, self.olaylar, self.modlar = ws, None, [], set()

    def pump(self, sn, kosul=None):
        son = time.time() + sn
        while time.time() < son:
            m = json.loads(self.ws.receive_text())
            if m.get('t') == 'tele':
                self.tele = m
                if m.get('mode'):
                    self.modlar.add(m['mode'])
            elif m.get('t') == 'event':
                self.olaylar.append(m['text'])
            if kosul and self.tele and kosul(self.tele):
                return True
        return False

    def cmd(self, name, params=None):
        self.ws.send_text(json.dumps({'t': 'cmd', 'rid': f'{name}-{time.time()}', 'name': name, 'params': params or {}}))


class SahteGcs:
    """Mission Planner / QGC taklidi: oturumun UDP köprüsüne 1 Hz GCS HEARTBEAT, araç kalp atışlarını toplar."""

    def __init__(self, port):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(('127.0.0.1', 0))
        self.s.setblocking(False)
        self.hedef = ('127.0.0.1', port)
        self.mav = D.MAVLink(None, srcSystem=254, srcComponent=190)
        self.mav.robust_parsing = True
        self.hb, self.tipler, self._son = [], {}, 0.0

    def tik(self):
        if time.time() - self._son > 1.0:
            self._son = time.time()
            self.s.sendto(self.mav.heartbeat_encode(6, 8, 0, 0, 4).pack(self.mav), self.hedef)
        while True:
            try:
                data = self.s.recv(65535)
            except BlockingIOError:
                return
            for m in self.mav.parse_buffer(data) or []:
                self.tipler[m.get_type()] = self.tipler.get(m.get_type(), 0) + 1
                if m.get_type() == 'HEARTBEAT' and m.get_srcSystem() != 254:
                    self.hb.append((m.get_srcSystem(), m.autopilot, m.type))

    def kapat(self):
        self.s.close()


def senaryo(a, cid, tip):
    af, alt, esik = SENARYO[tip]
    print(f'— {tip}: PX4 airframe {af}')
    body = {'type': tip, 'center_id': cid, 'stack': 'px4', 'world': {'wind_ms': 0},
            'stack_cfg': {'airframe': af, 'params_text': '# test\n1\t1\tCOM_DISARM_LAND\t1.5\t9\nNAV_RCL_ACT 0\n', 'params_name': 'test.params'}}
    s = ok(a.post(S, json=body), 201)
    sid = s['id']
    assert s['stack'] == 'px4' and s['stack_info']['airframe'] == af and 'AUTO.RTL' in s['modes'], s
    gcs = None
    try:
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR', 60), ok(a.get(f'{S}/{sid}'))
        d = ok(a.get(f'{S}/{sid}'))
        assert d['sitl']['stack'] == 'px4' and 70 <= d['sitl']['instance'] < 100, d['sitl']
        pid = d['sitl']['pid']
        gcs = SahteGcs(d['udp_port'])
        with a.websocket_connect(f'/ws/drone/sim/{sid}') as ws:
            A = Akis(ws)
            t0 = time.time()
            while time.time() - t0 < 30 and not gcs.hb:
                gcs.tik()
                A.pump(0.3)
            assert gcs.hb and gcs.hb[-1][0] == 1 and gcs.hb[-1][1] == 12, f'GCS köprüsünden PX4 kalp atışı yok: {gcs.hb[-3:]}'
            assert ok(a.get(f'{S}/{sid}'))['gcs']['connected']
            assert A.pump(20, lambda t: t.get('mode') == 'AUTO.LOITER' and (t.get('lat') or 0) > 39), A.tele
            # takma ad kipi + desteklenmeyen komutlar (gerekçeli 400)
            r = ok(a.post(f'{S}/{sid}/cmd', json={'name': 'mode', 'params': {'mode': 'LOITER'}}))
            assert r.get('mode') == 'AUTO.LOITER', r
            for ad, prm in (('speed', {'factor': 2}), ('motor_cut', {'on': True}), ('servo_set', {'ch': 9, 'pwm': 1900})):
                rr = a.post(f'{S}/{sid}/cmd', json={'name': ad, 'params': prm})
                assert rr.status_code == 400 and 'PX4' in rr.text, (ad, rr.status_code, rr.text)
            w = ok(a.post(f'{S}/{sid}/cmd', json={'name': 'wind', 'params': {'ms': 3, 'dir': 90}}))
            assert w['physics'] is False, w
            # ARM + kalkış (EKF hazır olana dek sunucu ARM'ı yineler)
            A.cmd('takeoff', {'alt': alt})
            assert A.pump(150 if tip == 'sabit_kanat' else 90, lambda t: (t.get('alt_rel') or 0) >= esik), f"kalkış: {A.tele and A.tele.get('alt_rel')} {A.olaylar[-6:]}"
            gcs.tik()
            T = A.tele
            print(f"  kalkış: {T['alt_rel']:.1f} m · kip {T['mode']} · hız {T['groundspeed']:.1f} m/s · gps {T['gps_fix']}/{T['sats']} · batt {T['batt_v']}")
            for k in ('lat', 'lon', 'alt_msl', 'roll', 'pitch', 'yaw', 'heading', 'groundspeed', 'throttle', 'gps_fix', 'batt_v', 'home', 'servo'):
                assert T.get(k) is not None, (k, T)
            assert T['armed'] and T['gps_fix'] >= 3 and T['home'] and abs(T['home']['lat'] - MERKEZ['lat']) < 0.01, T
            # RTL → iniş + disarm (sabit kanat: RTL loiter'da kalır; eve dönüş ve kip yeterli)
            A.cmd('rtl')
            assert A.pump(20, lambda t: t.get('mode') == 'AUTO.RTL'), A.tele.get('mode')
            if tip == 'sabit_kanat':
                A.pump(10)
                print(f"  RTL: kip {A.tele['mode']} · {A.tele['alt_rel']:.1f} m")
            else:
                assert A.pump(150, lambda t: not t.get('armed') and (t.get('alt_rel') or 0) < 2), f"iniş: {A.tele.get('alt_rel')} armed={A.tele.get('armed')}"
                print(f"  RTL iniş tamam: {A.tele['alt_rel']:.1f} m, disarm")
            print(f"  görülen kipler: {sorted(A.modlar)} · GCS'ye giden mesaj türü: {len(gcs.tipler)} · köprü kalp atışı {len(gcs.hb)}")
            evt = ' | '.join(A.olaylar)
            assert 'Arming denied: Resolve system health failures first' in evt or 'Armed by external command' in evt, evt[:600]   # parçalı STATUSTEXT birleşir
            assert 'Komut 400 reddedildi' not in evt, evt[:600]   # kalkış ARM yinelemesinde ret satırı yok
            assert ok(a.get(f'{S}/{sid}'))['stack_info']['params_loaded'] == 2
        # Sıfırla: aynı ayarlarla yeni PX4 süreci (temiz=False), yeniden HAZIR
        ok(a.post(f'{S}/{sid}/cmd', json={'name': 'reset', 'params': {}}))
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR', 60)
        d2 = ok(a.get(f'{S}/{sid}'))
        assert d2['sitl']['pid'] != pid, 'Sıfırla yeni süreç açmadı'
        assert not _canli(pid), 'eski PX4 süreci kapanmadı'
        pid = d2['sitl']['pid']
    finally:
        if gcs:
            gcs.kapat()
        if flightsim.MANAGER.get(sid) is not None:
            a.delete(f'{S}/{sid}')
    assert bekle(lambda: not _canli(pid), 10), 'kapanışta PX4 süreci sonlanmadı'
    assert not drone_sitl.YONETICI.calisiyor_mu(flightsim.KIMLIK_TABANI + sid)
    print(f'  {tip}: TAMAM')


def _canli(pid):
    try:
        with open(f'/proc/{pid}/stat') as f:
            return f.read().split(')')[-1].split()[0] != 'Z'
    except OSError:
        return False


def main():
    tipler = [t for t in os.environ.get('PX4_E2E_TIPLER', 'multirotor,sabit_kanat,vtol').split(',') if t]
    with TestClient(app, base_url='https://testserver') as tc:
        a = Kullanici(tc, 'admin@test', 'admin-sifre-1')
        meta = ok(a.get('/api/drone/sim/meta'))
        px4 = next(x for x in meta['stacks'] if x['key'] == 'px4')
        assert px4['available'] and px4['status'] == 'active', px4
        assert {x['key']: x['status'] for x in meta['stacks']} == {'ardupilot': 'active', 'px4': 'active', 'inav': 'planned', 'paparazzi': 'planned',
                                                                   'betaflight': 'unsuitable', 'rotorflight': 'unsuitable'}
        cid = ok(a.post('/api/drone/centers', json={'name': 'PX4 SITL', **MERKEZ}))['id']
        # doğrulama: PX4'te desteklenmeyen tip, yanlış airframe, planlanan yığın → 400
        for body in ({'type': 'helikopter', 'stack': 'px4'}, {'type': 'multirotor', 'stack': 'px4', 'stack_cfg': {'airframe': 10041}},
                     {'type': 'multirotor', 'stack': 'inav'}, {'type': 'multirotor', 'stack': 'px4', 'stack_cfg': {'speed': 3}}):
            r = a.post(S, json={**body, 'center_id': cid})
            assert r.status_code == 400, (body, r.status_code, r.text)
        for t in tipler:
            senaryo(a, cid, t)
    print('test_flightsim_px4_sitl: TAMAM')


if __name__ == '__main__':
    main()
