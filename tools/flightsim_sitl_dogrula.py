"""Uçuş Simülatörü — GERÇEK ArduPilot SITL ile elle doğrulama (DEV).

Ne yapar: uygulamayı test istemcisiyle (lifespan dâhil) ayağa kaldırır, bir merkez oluşturur, gerçek arduplane oturumu açar,
Mission Planner yerine pymavlink ile UDP'den (udpout:127.0.0.1:<port>) bağlanıp HEARTBEAT alır, SIM_WIND_SPD parametresini
okuyarak rüzgârın yazıldığını doğrular, WebSocket'ten en az 20 telemetri karesi okur, oturumu kapatır ve SITL sürecinin
kalmadığını /proc üzerinden denetler.

Çalıştırma (DEV): HEPGO_SITL_DIR=/opt/hepgo/sitl/bin .venv/bin/python -m tools.flightsim_sitl_dogrula [tip] [udp_taban]
  tip: sabit_kanat (varsayılan) | multirotor | hexarotor | helikopter | vtol      udp_taban: SIM_UDP_BASE (varsayılan 14550)
PROD'da çalıştırılmaz; DEV veri dizini geçicidir.
"""
import json
import os
import sys
import tempfile
import time

tip = sys.argv[1] if len(sys.argv) > 1 else 'sabit_kanat'
udp_taban = sys.argv[2] if len(sys.argv) > 2 else '14550'
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(prefix='hepgo-sim-'), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='1', SIM_UDP_BASE=udp_taban)
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/sitl/bin')

from fastapi.testclient import TestClient  # noqa: E402
from pymavlink import mavutil  # noqa: E402

from app import auth, drone_sitl, flightsim  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json()


def sitl_surecleri():
    """Bu çalışma kökündeki (kiracı) arducopter/arduplane süreçleri."""
    kok = str(drone_sitl.CALISMA_KOKU)
    out = []
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            cmd = open(f'/proc/{pid}/cmdline', 'rb').read().decode('utf-8', 'ignore')
        except OSError:
            continue
        if kok in cmd and ('arducopter' in cmd or 'arduplane' in cmd):
            out.append(int(pid))
    return out


def main():
    t0 = time.time()
    print(f'SITL ikili klasörü: {drone_sitl.SITL_KLASORU} · tip={tip} · ikili var: {drone_sitl.ikili_yolu(tip).is_file()}')
    with TestClient(app, base_url='https://testserver') as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        token = a.cookies.get(auth.COOKIE)
        c = ok(a.post('/api/drone/centers', json={'name': 'Doğrulama Merkezi', 'lat': 39.925, 'lon': 32.837, 'alt': 900}))
        meta = ok(a.get('/api/drone/sim/meta'))
        print('meta.types:', [(t['key'], t['binary']) for t in meta['types']], '· host:', meta['host'])
        s = ok(a.post('/api/drone/sim/sessions', json={'type': tip, 'center_id': c['id'], 'world': {'wind_ms': 3, 'wind_dir': 270}}), 201)
        sid, port = s['id'], s['udp_port']
        print(f'oturum {sid}: state={s["state"]} udp={port}')
        bitis = time.time() + 90
        while time.time() < bitis:
            s = ok(a.get(f'/api/drone/sim/sessions/{sid}'))
            if s['state'] in ('HAZIR', 'HATA'):
                break
            time.sleep(1)
        print(f'state={s["state"]} sitl={s["sitl"]} ({time.time() - t0:.0f} sn)')
        assert s['state'] == 'HAZIR', s
        pids = sitl_surecleri()
        print('SITL süreçleri:', pids)
        assert pids and s['sitl']['pid'] in pids, (pids, s['sitl'])

        # --- "Mission Planner": pymavlink UDP istemcisi ---
        gcs = mavutil.mavlink_connection(f'udpout:127.0.0.1:{port}', source_system=255, source_component=190)
        gcs.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)   # ilk paket → GCS kilidi
        hb = gcs.wait_heartbeat(timeout=30)
        assert hb is not None, 'GCS tarafına HEARTBEAT gelmedi'
        print(f'GCS heartbeat: sysid={hb.get_srcSystem()} type={hb.type} mode={mavutil.mode_mapping_bynumber(hb.type).get(hb.custom_mode)}')
        s = ok(a.get(f'/api/drone/sim/sessions/{sid}'))
        print('oturum gcs:', s['gcs'])
        assert s['gcs']['connected'] and s['gcs']['addr'].startswith('127.0.0.1:'), s['gcs']
        # rüzgâr parametresi SITL'e yazıldı mı (GCS tarafından okunur)
        ruzgar = None
        for _ in range(5):
            gcs.mav.param_request_read_send(hb.get_srcSystem(), hb.get_srcComponent(), b'SIM_WIND_SPD', -1)
            m = gcs.recv_match(type='PARAM_VALUE', condition="PARAM_VALUE.param_id=='SIM_WIND_SPD'", blocking=True, timeout=3)
            if m is not None:
                ruzgar = m.param_value
                break
        print('SIM_WIND_SPD =', ruzgar)
        assert ruzgar is not None and abs(ruzgar - 3.0) < 0.01, ruzgar
        sayac = {}
        bitis = time.time() + 3
        while time.time() < bitis:
            m = gcs.recv_match(blocking=True, timeout=1)
            if m is not None:
                sayac[m.get_type()] = sayac.get(m.get_type(), 0) + 1
        print('GCS 3 sn mesaj türleri:', dict(sorted(sayac.items(), key=lambda x: -x[1])[:10]))
        assert 'GLOBAL_POSITION_INT' in sayac or 'ATTITUDE' in sayac, sayac

        # --- WebSocket: ≥ 20 telemetri karesi ---
        with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
            h = json.loads(ws.receive_text())
            assert h['t'] == 'hello' and h['session']['id'] == sid, h
            teles, olaylar = [], []
            bitis = time.time() + 10
            while time.time() < bitis and len(teles) < 25:
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele':
                    teles.append(m)
                elif m['t'] == 'event':
                    olaylar.append(m['text'])
            print(f'WS tele kareleri: {len(teles)} · olaylar: {olaylar[:5]}')
            assert len(teles) >= 20, len(teles)
            son = teles[-1]
            # SITL'de GPS/EKF kilidi 10–45 sn sürer (dron-kopru-protokolu: bu sürede ARM reddedilir); konum için bekle
            bitis = time.time() + 90
            while time.time() < bitis and not (son['gps_fix'] >= 3 and son['home']):
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele':
                    son = m
                elif m['t'] == 'event':
                    olaylar.append(m['text'])
            print(f'GPS kilidi sonrası ({time.time() - t0:.0f} sn) olaylar: {olaylar[-5:]}')
            print('son tele:', {k: son[k] for k in ('lat', 'lon', 'alt_msl', 'alt_rel', 'mode', 'armed', 'gps_fix', 'sats', 'batt_v', 'heading', 'gcs_connected', 'gcs_addr', 'home')})
            assert son['mode'] is not None and abs(son['lat'] - 39.925) < 0.01 and son['gps_fix'] >= 3 and son['gcs_connected'], son
            # komut yolu: mode (uçakta FBWA) → telemetride görünmeli
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'mode', 'params': {'mode': 'FBWA' if tip in ('sabit_kanat', 'vtol') else 'LOITER'}, 'rid': 'm1'}))
            hedef = 'FBWA' if tip in ('sabit_kanat', 'vtol') else 'LOITER'
            bitis = time.time() + 8
            goruldu = None
            while time.time() < bitis:
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele' and m['mode'] == hedef:
                    goruldu = m
                    break
            print('mod değişimi telemetride:', goruldu['mode'] if goruldu else None)
            assert goruldu, 'mod değişimi telemetriye yansımadı'
        gcs.close()

        # --- kapat ---
        ok(a.delete(f'/api/drone/sim/sessions/{sid}'))
        time.sleep(1)
        assert a.get(f'/api/drone/sim/sessions/{sid}').status_code == 404
        kalan = sitl_surecleri()
        print('kapatma sonrası SITL süreçleri:', kalan)
        assert not kalan, kalan
    print(f'GERÇEK SITL DOĞRULAMASI BAŞARILI ({time.time() - t0:.0f} sn) · MANAGER.sessions={flightsim.MANAGER.sessions}')


if __name__ == '__main__':
    main()
