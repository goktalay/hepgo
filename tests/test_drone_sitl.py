"""Sanal dron = gerçek ArduPilot SITL (GÖKTUNGU birebir): görev izlenince hub SITL sürecini başlatır, Hepgo Dron Köprüsü
çekirdeğiyle bağlanır; GÖKTUNGU kalkış akışı (GUIDED → teyit → ARM → teyit → NAV_TAKEOFF) gerçek firmware'e karşı çalışır,
irtifa KADEMELİ artar, goto ile konum kademeli değişir, LAND kademeli iner ve araç kendiliğinden DISARM olur.
Çalıştırma: HEPGO_SITL_DIR=/opt/hepgo/sitl/bin .venv/bin/python -m tests.test_drone_sitl   (ikili yoksa ilk çalıştırmada indirilir)
"""
import faulthandler
import json
import os
import tempfile
import time
faulthandler.dump_traceback_later(400, exit=True)
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0', HEPGO_SITL='1')
from fastapi.testclient import TestClient  # noqa: E402
from app import auth, drone_hub, drone_sitl, flight_analysis  # noqa: E402
from app.main import app  # noqa: E402
flight_analysis.start = lambda lid: None


def ok(r):
    assert r.status_code == 200, (r.request.url, r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app, base_url='https://testserver') as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        token = a.cookies.get(auth.COOKIE)
        sd = ok(a.post('/api/drone/drones', json={'name': 'Sanal-SITL', 'protocol': 'sanal'}))
        pilot = ok(a.post('/api/users', json={'username': 'pilot@test', 'full_name': 'Pilot', 'roles': [auth.PILOT, auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
        lead = ok(a.post('/api/users', json={'username': 'saha@test', 'full_name': 'Saha', 'roles': [auth.FIELD_LEAD], 'password': 'Gizli-Parola-77'}))
        t = ok(a.post('/api/field/tasks', json={'drone_ids': [sd['id']], 'lead_id': lead['id'], 'pilot_id': pilot['id'], 'staff_ids': [pilot['id']]}))
        sim_id = -sd['id']
        with a.websocket_connect('/ws/drone/live', headers={'cookie': f'{auth.COOKIE}={token}'}) as live:
            state, events, cons, res = {}, [], [], {}

            def pump(sec, until=None):
                end = time.time() + sec
                while time.time() < end:
                    m = json.loads(live.receive_text())
                    if m.get('t') == 'status' and m.get('bridge_id') == sim_id:
                        state.update(m['state'])
                    elif m.get('t') == 'event' and m.get('bridge_id') == sim_id:
                        events.append(m['text'])
                    elif m.get('t') == 'console' and m.get('bridge_id') == sim_id:
                        cons.append(m['text'])
                    elif m.get('t') == 'res':
                        res[m['rid']] = m
                    if until and until():
                        return True
                return bool(until and until())

            def cmd(rid, name, params=None):
                live.send_text(json.dumps({'t': 'cmd', 'rid': rid, 'bridge_id': sim_id, 'sysid': 1, 'name': name, 'params': params or {}}))
                assert pump(40, lambda: rid in res), (rid, events[-5:])
                return res[rid]

            live.send_text(json.dumps({'t': 'watch', 'task_id': t['id']}))
            assert pump(60, lambda: state.get('lat') is not None and state.get('type') == 2), (events, cons[-10:])
            assert isinstance(drone_hub.SIMS[sim_id], drone_hub.SitlDrone)
            assert drone_sitl.YONETICI.calisiyor_mu(sd['id'])
            print('SITL telemetri:', state['lat'], state['lon'], state['mode'], 'paket', drone_hub.SIMS[sim_id].packets)
            # Gerçek firmware: EKF GPS kullanmaya başlayıp HOME atanmadan ARM edilemez (~30-45 sn). Pilot HAZIR rozetini bekler;
            # test kalkışı GÖKTUNGU akışıyla dener, "ARM teyidi alınamadı" olursa 5 sn sonra yeniden dener.
            assert pump(120, lambda: any('is using GPS' in e for e in events)), events[-8:]
            for deneme in range(12):
                r = cmd(f't{deneme}', 'takeoff', {'alt_rel_m': 20})
                assert r['ok'] is True, r
                if pump(10, lambda: state.get('armed') is True):
                    break
                assert any('ARM teyidi alınamadı' in c for c in cons[-6:]), cons[-6:]
            print('kalkış denemesi', deneme + 1)
            alts = []
            pump(14, lambda: alts.append(state.get('alt_rel') or 0) and False)
            assert state['armed'] is True and state['mode'] == 'GUIDED', state
            seen = sorted(set(round(x) for x in alts))
            assert max(alts) >= 15 and len([x for x in seen if 2 <= x <= 14]) >= 3, seen   # kademeli tırmanış (ara irtifalar görüldü)
            assert any('TAKEOFF komutu iletildi: 20 m' in c for c in cons), cons[-10:]
            lat0 = state['lat']
            assert cmd('g1', 'goto', {'lat': lat0 + 0.002, 'lon': state['lon'], 'alt_rel_m': 20})['ok'] is True
            lats = []
            pump(8, lambda: lats.append(state['lat']) and False)
            moved = [x - lat0 for x in lats]
            assert 0 < moved[len(moved) // 2] < 0.002 and max(moved) > 0.0003, moved[::10]   # kademeli ilerleme (anlık sıçrama yok)
            # GÖKTUNGU prosedürleri gerçek firmware'e karşı: irtifa değişikliği hedefi hafızaya alır, irtifasız goto onu korur
            assert cmd('a1', 'altitude_change', {'alt_rel_m': 30})['ok'] is True
            assert pump(25, lambda: (state.get('alt_rel') or 0) > 27), state.get('alt_rel')
            assert cmd('g2', 'goto', {'lat': lat0, 'lon': state['lon']})['ok'] is True
            assert any('@ 30m rel (hedef korundu)' in c for c in cons), cons[-6:]
            # Görev: yükle → başlat (havada: AUTO + MISSION_START) → duraklat (BRAKE teyitli) → devam (AUTO) → iptal (BRAKE + liste temizlenir)
            items = [{'seq': 0, 'frame': 6, 'command': 16, 'current': 1, 'autocontinue': 1, 'param1': 0, 'param2': 0, 'param3': 0, 'param4': 0,
                      'x': int((lat0 + 0.003) * 1e7), 'y': int(state['lon'] * 1e7), 'z': 30.0, 'mission_type': 0},
                     {'seq': 1, 'frame': 6, 'command': 16, 'current': 0, 'autocontinue': 1, 'param1': 0, 'param2': 0, 'param3': 0, 'param4': 0,
                      'x': int((lat0 + 0.006) * 1e7), 'y': int(state['lon'] * 1e7), 'z': 30.0, 'mission_type': 0}]
            up = cmd('m1', 'mission_upload', {'items': items})
            assert up['ok'] is True and up['result']['offset'] == 1, up
            assert cmd('m2', 'mission_start', {'rota': 'SITL'})['ok'] is True
            assert pump(10, lambda: state.get('mode') == 'AUTO'), state.get('mode')
            r = cmd('m3', 'mission_pause', {'davranis': 'bekle'})
            assert r['ok'] is True and r['result']['mode'] == 'BRAKE', r
            r = cmd('m4', 'mission_resume')
            assert r['ok'] is True and r['result']['mode'] == 'AUTO', r
            r = cmd('m5', 'mission_cancel', {'rota': 'SITL'})
            assert r['ok'] is True and r['result']['mode'] == 'BRAKE', r
            dl = cmd('m6', 'mission_download')
            assert dl['ok'] is True and dl['result']['items'] == [], dl   # görev listesi temizlendi
            print('görev akışları: AUTO → BRAKE → AUTO → iptal (BRAKE, liste boş)')
            assert cmd('l1', 'land')['ok'] is True
            alts2 = []
            pump(10, lambda: alts2.append(state.get('alt_rel') or 0) and False)
            assert state['mode'] == 'LAND' and alts2[-1] < alts2[0] - 2 and alts2[-1] > 1, (alts2[0], alts2[-1])   # kademeli iniş
            print('tırmanış', seen[:8], '… iniş', round(alts2[0], 1), '→', round(alts2[-1], 1))
            assert pump(90, lambda: state.get('armed') is False), (state.get('alt_rel'), state.get('mode'))   # yere inince DISARM
            print('iniş tamam, DISARM')
        # izleyici gidince SIM_IDLE beklemeden durdur (uygulamanın olay döngüsünde)
        sim = drone_hub.SIMS[sim_id]
        sim.loop.call_soon_threadsafe(drone_hub.stop_sim, sim_id)
        time.sleep(7)
        assert not drone_sitl.YONETICI.calisiyor_mu(sd['id'])
    print('SITL sanal dron testi geçti.')


if __name__ == '__main__':
    main()
