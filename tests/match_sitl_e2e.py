"""§33 çok oyunculu karşılaşma — GERÇEK SITL ile uçtan uca (iki ArduCopter SITL süreci): oluştur → katıl → HAZIRLIK (iki SITL, farklı ev
konumu) → WS ready → geri sayım (ARM kapalı) → YARIS → A: kalkış + GUIDED goto ile halkaların önünden içinden geçiş (sunucu tele kancası
doğrular), B: yalnız kalkış → A birinci → sonuç (WS) → SITL'ler kapanır. Kendi başlattığı SITL süreçleri PID ile denetlenir/kapatılır.
SITL ikilileri: HEPGO_SITL_DIR (varsayılan /opt/hepgo/fabrika-yonetim/data/sitl — yalnız okunur/çalıştırılır).
Çalıştırma: .venv/bin/python -m tests.match_sitl_e2e
"""
import json
import math
import os
import signal
import tempfile
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(prefix='match-sitl-'), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='1', SIM_UDP_BASE='41550', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MATCH_MAX_SESSIONS='4', SIM_PARAM_DUMP_S='0')
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/fabrika-yonetim/data/sitl')

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, flightsim  # noqa: E402
from app import flightsim_match_core as core  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_flightsim_match import Kullanici, ok  # noqa: E402

M = '/api/drone/sim/matches'
MERKEZ = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}
pids = set()


def bekle(fn, sn, adim=0.25):
    t = time.time() + sn
    while time.time() < t:
        v = fn()
        if v:
            return v
        time.sleep(adim)
    return fn()


def main():
    t0 = time.time()
    with TestClient(app, base_url='https://testserver') as tc:
        a = Kullanici(tc, 'admin@test', 'admin-sifre-1')
        c1 = ok(a.post('/api/drone/centers', json={'name': 'SITL Yarış', 'lat': MERKEZ['lat'], 'lon': MERKEZ['lon'], 'alt': 900}))
        ok(a.post('/api/users', json={'username': 'ayse', 'full_name': 'Ayşe Pilot', 'roles': [auth.PILOT], 'password': 'sifre-1234'}))
        p1 = Kullanici(tc, 'ayse', 'sifre-1234')
        me = {'admin': ok(a.get('/api/auth/me'))['id'], 'ayse': ok(p1.get('/api/auth/me'))['id']}
        ayar = {'type': 'multirotor', 'center_id': c1['id'], 'world': {'mode': 'procedural', 'seed': 3}}
        halka = {'count': 2, 'min_alt_m': 15, 'max_alt_m': 25, 'diameter_m': 14, 'radius_m': 90, 'seed': 21, 'time_limit_min': 10}
        mt = ok(a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [me['ayse']]}), 201)
        mid, rings = mt['id'], mt['rings']
        print('  karşılaşma', mid, 'halkalar:', [(r['i'], r['x'], r['y'], r['agl_m']) for r in rings], flush=True)
        try:
            with a.websocket_connect(f'/ws/drone/match/{mid}') as wa, p1.websocket_connect(f'/ws/drone/match/{mid}') as w1:
                json.loads(wa.receive_text()); json.loads(w1.receive_text())
                assert ok(p1.post(f'{M}/{mid}/join'))['state'] == 'HAZIRLIK'
                d = bekle(lambda: (lambda x: x if all(p['session_id'] for p in x['players']) else None)(ok(a.get(f'{M}/{mid}'))), 30)
                sids = {p['id']: p['session_id'] for p in d['players']}
                ss = {u: flightsim.MANAGER.get(s) for u, s in sids.items()}
                for s in ss.values():
                    assert bekle(lambda s=s: s.state in ('HAZIR', 'HATA'), 120), s.state
                    assert s.state == 'HAZIR', s.sitl
                    if s.sitl.get('pid'):
                        pids.add(int(s.sitl['pid']))
                    assert bekle(lambda s=s: s._heartbeat_alindi, 120), ('SITL kalp atışı yok', s.sitl)
                print(f'  iki SITL hazır ({time.time() - t0:.0f} sn), pid {sorted(pids)}', flush=True)
                evler = [(s.tele['lat'], s.tele['lon']) for s in ss.values()]
                ayrik = math.dist(core.enu(MERKEZ['lat'], MERKEZ['lon'], *evler[0]), core.enu(MERKEZ['lat'], MERKEZ['lon'], *evler[1]))
                assert ayrik >= core.AYRIK_M - 3, ayrik   # SITL ev konumları gerçekten farklı
                print(f'  SITL ev konumları arası {ayrik:.1f} m', flush=True)
                sa = sids[me['ayse']]
                r = p1.post(f'/api/drone/sim/sessions/{sa}/cmd', json={'name': 'arm'})
                assert r.status_code == 400 and 'başlamadı' in r.text, r.text   # komut kapısı (gerçek SITL)
                for w in (wa, w1):
                    w.send_text(json.dumps({'t': 'ready'}))
                gorulen = []

                def ws_bekle(ws, kosul, sn):
                    bitis = time.time() + sn
                    while time.time() < bitis:
                        m = json.loads(ws.receive_text())
                        gorulen.append(m)
                        if kosul(m):
                            return m
                    return None
                assert ws_bekle(w1, lambda m: m['t'] == 'countdown', 30)
                assert ws_bekle(w1, lambda m: m['t'] == 'state' and m['state'] == 'YARIS', 20)
                print(f'  YARIS ({time.time() - t0:.0f} sn)', flush=True)
                # B (kurucu) yalnız kalkar; A parkuru uçar
                s = ss[me['ayse']]
                sb = ss[me['admin']]

                def kalk(kim, sess, sid, alt):   # EKF/GPS hazır olana dek ArduCopter ARM'ı reddeder → yinele
                    for _ in range(40):
                        kim.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'mode', 'params': {'mode': 'GUIDED'}})
                        kim.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'arm'})
                        if not bekle(lambda: sess.tele.get('armed'), 4):
                            continue
                        kim.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': alt}})
                        if bekle(lambda: (sess.tele.get('alt_rel') or 0) > 2, 8):
                            return True
                    return False
                assert kalk(a, sb, sids[me['admin']], 10), sb.tele
                assert kalk(p1, s, sa, 20), s.tele
                assert bekle(lambda: s.tele.get('alt_rel', 0) > 15, 60), s.tele.get('alt_rel')
                loop = tc.portal

                def git(x, y, alt):
                    lat, lon = core.latlon(MERKEZ['lat'], MERKEZ['lon'], x, y)
                    res = loop.call(s.hub_komut, 'goto', {'lat': lat, 'lon': lon, 'alt_rel_m': alt, 'speed_mps': 8})
                    assert res.get('ok'), res
                    return bekle(lambda: math.dist(core.enu(MERKEZ['lat'], MERKEZ['lon'], s.tele['lat'], s.tele['lon']), (x, y)) < 3.5 and abs(s.tele['alt_rel'] - alt) < 2.5, 90)
                for h in rings:
                    agl = h['agl_m']
                    assert git(h['x'] - h['nx'] * 22, h['y'] - h['ny'] * 22, agl), ('yaklaşma', h['i'], s.tele)
                    assert git(h['x'] + h['nx'] * 18, h['y'] + h['ny'] * 18, agl), ('geçiş', h['i'], s.tele)
                    print(f"  halka {h['i']} ardından ({time.time() - t0:.0f} sn)", flush=True)
                res = ws_bekle(w1, lambda m: m['t'] == 'result', 30) or next((m for m in gorulen if m['t'] == 'result'), None)
                assert res, [m['t'] for m in gorulen[-30:]]
                ringev = [m['i'] for m in gorulen if m['t'] == 'ring' and m['id'] == me['ayse']]
                rs = res['result']
                assert ringev == [1, 2] and rs['winner'] == me['ayse'] and rs['standings'][0]['rings'] == 2, (ringev, rs)
                print(f"  SONUÇ: birinci Ayşe {rs['standings'][0]['time_s']} sn · azami {rs['standings'][0]['max_speed_ms']} m/s; kurucu halka {rs['standings'][1]['rings']}", flush=True)
                assert bekle(lambda: all(flightsim.MANAGER.get(x) is None for x in sids.values()), 60)
        finally:
            pass
    # kendi SITL süreçlerimiz kapandı mı (lifespan kapanışı da kapatır); açık kalan → PID ile kapat
    acik = [p for p in pids if _yasiyor(p)]
    for p in acik:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass
    assert not acik, f'kapanmayan SITL: {acik}'
    print(f'match_sitl_e2e: TAMAM ({time.time() - t0:.0f} sn)')


def _yasiyor(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f'/proc/{pid}/stat') as f:
            return f.read().split()[2] != 'Z'
    except OSError:
        return False


if __name__ == '__main__':
    main()
