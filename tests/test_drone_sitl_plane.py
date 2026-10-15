"""Sabit kanat kalkışı (tüm sabit kanatlar; burada gerçek ArduPlane SITL): karttaki Takeoff akışı TKOFF_ALT'ı yazar, TAKEOFF moduna
geçer, ARM eder; uçak seçilen irtifaya kendisi tırmanır. (Çok rotorlu akıştaki GUIDED + NAV_TAKEOFF ArduPlane'de reddedilir.)
Çalıştırma: HEPGO_SITL_DIR=/opt/hepgo/sitl/bin .venv/bin/python -m tests.test_drone_sitl_plane
"""
import faulthandler
import json
import os
import tempfile
import time
faulthandler.dump_traceback_later(400, exit=True)
os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0', HEPGO_SITL='1')
from fastapi.testclient import TestClient  # noqa: E402
from app import auth, drone_hub, flight_analysis  # noqa: E402
from app.main import app  # noqa: E402
flight_analysis.start = lambda lid: None


def ok(r):
    assert r.status_code == 200, (r.request.url, r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app, base_url='https://testserver') as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        token = a.cookies.get(auth.COOKIE)
        sd = ok(a.post('/api/drone/drones', json={'name': 'Sanal-Kanat', 'protocol': 'sanal', 'model': 'Sabit kanat'}))
        pilot = ok(a.post('/api/users', json={'username': 'pilot@test', 'full_name': 'Pilot', 'roles': [auth.PILOT, auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
        lead = ok(a.post('/api/users', json={'username': 'saha@test', 'full_name': 'Saha', 'roles': [auth.FIELD_LEAD], 'password': 'Gizli-Parola-77'}))
        t = ok(a.post('/api/field/tasks', json={'drone_ids': [sd['id']], 'lead_id': lead['id'], 'pilot_id': pilot['id'], 'staff_ids': [pilot['id']]}))
        sim_id = -sd['id']
        with a.websocket_connect('/ws/drone/live', headers={'cookie': f'{auth.COOKIE}={token}'}) as live:
            state, cons, res = {}, [], {}

            def pump(sec, until=None):
                end = time.time() + sec
                while time.time() < end:
                    m = json.loads(live.receive_text())
                    if m.get('t') == 'status' and m.get('bridge_id') == sim_id:
                        state.update(m['state'])
                    elif m.get('t') == 'console' and m.get('bridge_id') == sim_id:
                        cons.append(m['text'])
                    elif m.get('t') == 'res':
                        res[m['rid']] = m
                    if until and until():
                        return True
                return bool(until and until())

            def cmd(rid, name, params=None):
                live.send_text(json.dumps({'t': 'cmd', 'rid': rid, 'bridge_id': sim_id, 'sysid': 1, 'name': name, 'params': params or {}}))
                assert pump(40, lambda: rid in res), rid
                return res[rid]

            live.send_text(json.dumps({'t': 'watch', 'task_id': t['id']}))
            assert pump(90, lambda: state.get('type') == 1 and state.get('lat')), (state.get('type'), cons[-8:])   # ArduPlane (MAV_TYPE 1)
            assert drone_hub.SIMS[sim_id].tip == 'sabit_kanat'
            for deneme in range(15):
                time.sleep(0 if deneme == 0 else 4)
                bas = len(cons)
                assert cmd(f't{deneme}', 'takeoff', {'alt_rel_m': 40})['ok'] is True
                if pump(30, lambda: state.get('armed') is True):
                    break
                assert any('ARM teyidi alınamadı' in c or 'TAKEOFF modu teyit edilmedi' in c for c in cons[bas:]), cons[bas:]   # GPS/HOME oturmadan ARM yok
            print('kalkış denemesi', deneme + 1)
            assert state['mode'] == 'TAKEOFF', state['mode']
            assert 'TKOFF_ALT = 40' in cons and any('sabit kanat kalkışı başladı (40 m)' in c for c in cons), cons[-10:]
            assert not any('NAV_TAKEOFF' in c or 'KALKIŞ (TAKEOFF) BAŞARISIZ' in c for c in cons), cons
            alts = []
            pump(25, lambda: alts.append(state.get('alt_rel') or 0) and False)
            assert max(alts) > 30 and state['groundspeed'] > 10, (max(alts), state.get('groundspeed'))
            print('sabit kanat tırmanışı: en yüksek', round(max(alts), 1), 'm, yer hızı', round(state['groundspeed'], 1), 'm/s')
        sim = drone_hub.SIMS[sim_id]
        sim.loop.call_soon_threadsafe(drone_hub.stop_sim, sim_id)
        time.sleep(7)
    print('Sabit kanat kalkış testi geçti.')


if __name__ == '__main__':
    main()
