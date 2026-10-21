"""CAYSIM istemci API'si (docs/caysim-api.md): istemci kaydı (kod bir kez, rekey, sil, GET anahtar döndürmez), Bearer kimlik (doğru/yanlış/pasif),
hız sınırı (10 başarısız/dk → 429, WS 4429), hello/logo/centers/types/models/world-defaults, oturum aç/kapat (HEPGO_SITL=0 sahte kinematik),
cmd, WS (sorgu anahtarı ve `auth` çerçevesi; hello/tele/cmd/rc), web listesinde `client` alanı, mavlink bilgisi, OPTIONS 204, hata biçimi.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_caysim
"""
import json
import os
import tempfile
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', SIM_UDP_BASE='25550', SIM_MAX_SESSIONS='2')

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app import auth, caysim, flightsim  # noqa: E402
from app.main import app  # noqa: E402

V1 = '/api/caysim/v1'
TELE_ALANLARI = {'ts', 'tbm', 'lat', 'lon', 'alt_msl', 'alt_rel', 'roll', 'pitch', 'yaw', 'rs', 'ps', 'ys', 'vn', 've', 'vd', 'airspeed', 'groundspeed',
                 'heading', 'climb', 'mode', 'armed', 'gps_fix', 'sats', 'batt_v', 'batt_pct', 'throttle', 'rc', 'home', 'gcs_connected', 'gcs_addr'}


def ok(r, code=200):
    assert r.status_code == code, (r.request.method, r.request.url, r.status_code, r.text)
    return r.json()


def hata(r, code, kod):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    d = r.json()['detail']
    assert d['error'] == kod and d['message'], d
    return d


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
    bitis = time.time() + sn
    while time.time() < bitis:
        m = json.loads(ws.receive_text())
        if kosul(m):
            return m
    return None


def close_code(ws):
    try:
        ws.receive_text()
    except WebSocketDisconnect as e:
        return e.code
    return None


def B(key):
    return {'Authorization': f'Bearer {key}'}


def main():
    with TestClient(app, base_url='https://testserver') as a:
        login(a, 'admin@test', 'admin-sifre-1')
        c1 = ok(a.post('/api/drone/centers', json={'name': 'Test Merkezi', 'lat': 39.925, 'lon': 32.837, 'alt': 900}))
        ok(a.post('/api/users', json={'username': 'pilot', 'full_name': 'Pilot Bey', 'roles': [auth.PILOT], 'password': 'sifre-1234'}))
        pilot_id = next(u['id'] for u in ok(a.get('/api/users')) if u['username'] == 'pilot')
        # salt okuyan rol: listeyi görür, istemci ekleyemez
        ok(a.post('/api/users', json={'username': 'montaj', 'full_name': 'Montaj', 'roles': ['Montaj Personeli'], 'password': 'sifre-1234'}))
        ok(a.put('/api/roles/perms', params={'name': 'Montaj Personeli'},
                 json={'changes': [{'node': 'drone.sim', 'cap': 'open', 'value': True}, {'node': 'drone.sim', 'cap': 'read', 'value': True}]}))

        # ---------------- istemci kayıtları (yönetim) ----------------
        assert ok(a.get('/api/drone/sim/clients')) == {'clients': [], 'can_write': True, 'platforms': ['windows', 'linux', 'macos', 'other']}
        assert a.post('/api/drone/sim/clients', json={'name': '  '}).status_code == 400
        assert a.post('/api/drone/sim/clients', json={'name': 'X', 'platform': 'amiga'}).status_code == 400
        assert a.post('/api/drone/sim/clients', json={'name': 'X', 'owner_id': 99999}).status_code == 400
        r = ok(a.post('/api/drone/sim/clients', json={'name': 'Simülatör PC-1', 'platform': 'windows', 'owner_id': pilot_id, 'note': 'salon'}), 201)
        cid, code = r['id'], r['code']
        domain, key = code.split('/', 1)
        assert domain == 'testserver' and len(key) == 43 and all(ch.isalnum() or ch in '-_' for ch in key), code
        assert a.post('/api/drone/sim/clients', json={'name': 'simülatör pc-1'}).status_code == 400   # ad benzersiz (NOCASE)
        r2 = ok(a.post('/api/drone/sim/clients', json={'name': 'Pasif İstemci', 'active': False}), 201)
        key_pasif = r2['code'].split('/', 1)[1]
        lst = ok(a.get('/api/drone/sim/clients'))['clients']
        assert [c['name'] for c in lst] == ['Simülatör PC-1', 'Pasif İstemci'] and all('key' not in c and 'key_enc' not in c and 'code' not in c for c in lst), lst
        c = lst[0]
        assert c['has_key'] is True and c['online'] is False and c['status'] == 'CEVRIMDISI' and c['owner_name'] == 'Pilot Bey' and c['platform'] == 'windows' and c['sessions'] == 0 and c['last_seen'] is None, c
        mon = TestClient(app, base_url='https://testserver')
        login(mon, 'montaj', 'sifre-1234')
        assert ok(mon.get('/api/drone/sim/clients'))['can_write'] is False
        assert mon.post('/api/drone/sim/clients', json={'name': 'Yetkisiz'}).status_code == 403
        assert mon.post(f'/api/drone/sim/clients/{cid}/rekey').status_code == 403 and mon.delete(f'/api/drone/sim/clients/{cid}').status_code == 403

        # ---------------- kimlik ----------------
        hata(a.get(f'{V1}/hello'), 401, 'auth')                                       # çerez var ama Bearer yok → istemci API'si çerez tanımaz
        hata(a.get(f'{V1}/hello', headers=B('yanlis-anahtar')), 401, 'auth')
        hata(a.get(f'{V1}/hello', headers={'Authorization': 'Basic abc'}), 401, 'auth')
        hata(a.get(f'{V1}/hello', headers=B(key_pasif)), 403, 'client_inactive')
        hata(a.get(f'{V1}/sessions', headers=B('x')), 401, 'auth')
        assert a.options(f'{V1}/hello').status_code == 204 and a.options(f'{V1}/sessions/1/cmd').status_code == 204

        # ---------------- hello ----------------
        h = ok(a.get(f'{V1}/hello', headers={**B(key), 'X-Caysim-Host': 'SIM-PC', 'X-Caysim-Ver': '0.3.1', 'X-Caysim-Platform': 'Windows'}))
        assert h['v'] == 1 and h['client'] == {'id': cid, 'name': 'Simülatör PC-1', 'owner': {'id': pilot_id, 'name': 'Pilot Bey'}}, h
        assert h['company']['name'] and h['company']['logo_url'] == f'{V1}/brand/logo' and 'legal_name' in h['company'] and 'primary_color' in h['company'], h
        assert set(h['caps']) >= set(caysim.CAPS) and ('google3d' in h['caps']) == bool(flightsim.GOOGLE_KEY), h
        assert h['limits'] == {'max_sessions': 2, 'max_minutes': flightsim.MAX_MINUTES, 'rc_hz': 40, 'tele_hz': 50} and h['host'] == 'testserver', h
        assert h['google3d'] == {'enabled': bool(flightsim.GOOGLE_KEY)} and h['sitl'] == {'enabled': False} and h['ws_url'] == '/ws/caysim/v1/sessions/{id}' and h['server_time']
        c = ok(a.get('/api/drone/sim/clients'))['clients'][0]
        assert c['host'] == 'SIM-PC' and c['client_ver'] == '0.3.1' and c['platform'] == 'windows' and c['status'] == 'CEVRIMICI' and c['last_seen'], c
        # sorgu parametresiyle de; aşırı uzun host kırpılır
        ok(a.get(f'{V1}/hello', params={'host': 'q' * 300, 'client_ver': '1.0'}, headers=B(key)))
        c = ok(a.get('/api/drone/sim/clients'))['clients'][0]
        assert len(c['host']) == 120 and c['client_ver'] == '1.0', c

        # ---------------- marka / kataloglar ----------------
        r = a.get(f'{V1}/brand/logo', headers=B(key))
        assert r.status_code == 200 and r.headers['content-type'].startswith('image/') and len(r.content) > 100, (r.status_code, r.headers)
        hata(a.get(f'{V1}/brand/logo'), 401, 'auth')
        assert [x['id'] for x in ok(a.get(f'{V1}/centers', headers=B(key)))['centers']] == [c1['id']]
        assert {t['key'] for t in ok(a.get(f'{V1}/types', headers=B(key)))['types']} == {'multirotor', 'hexarotor', 'helikopter', 'sabit_kanat', 'vtol', 'interceptor', 'rover'}
        m = ok(a.get(f'{V1}/models', params={'type': 'sabit_kanat'}, headers=B(key)))
        cay = next(x for x in m['models'] if x['id'] == 'builtin:caymaz')
        assert cay['glb_url'] == f'{V1}/models/builtin:caymaz/glb' and cay['file_url'] is None and m['defaults']['sabit_kanat'] == 'builtin:caymaz', cay
        assert all((x['thumb_url'] or '').startswith(V1) or x['thumb_url'] is None for x in m['models'])
        hata(a.get(f'{V1}/models', params={'type': 'ucan_hali'}, headers=B(key)), 400, 'invalid')
        r = a.get(f'{V1}/models/builtin:caymaz/glb', headers=B(key))
        assert r.status_code == 200 and r.headers['content-type'] == 'model/gltf-binary' and r.content[:4] == b'glTF', r.status_code
        hata(a.get(f'{V1}/models/builtin:quad/glb', headers=B(key)), 404, 'not_found')      # prosedürel: GLB yok
        hata(a.get(f'{V1}/models/999/glb', headers=B(key)), 404, 'not_found')
        hata(a.get(f'{V1}/models/abc/glb', headers=B(key)), 404, 'not_found')
        w = ok(a.get(f'{V1}/world-defaults', headers=B(key)))
        assert w['world_defaults']['seed'] == 12345 and w['limits']['size_m'] == [500, 20000] and w['modes'] == ['procedural', 'real', 'google3d'] and w['times'] == ['day', 'dusk', 'night'], w
        if not flightsim.GOOGLE_KEY:
            hata(a.get(f'{V1}/g3d-key', headers=B(key)), 404, 'not_found')
        hata(a.get(f'{V1}/terrain', params={'lat': 91, 'lon': 0}, headers=B(key)), 400, 'invalid')
        hata(a.get(f'{V1}/tile/yok/1/1/1', headers=B(key)), 404, 'not_found')
        assert ok(a.get(f'{V1}/logs', headers=B(key))) == {'logs': []}   # pilot: flightlogs yetkisi var ama log yok

        # ---------------- oturumlar ----------------
        assert ok(a.get(f'{V1}/sessions', headers=B(key))) == {'sessions': []}
        hata(a.post(f'{V1}/sessions', json={'type': 'ucan_hali', 'center_id': c1['id']}, headers=B(key)), 400, 'invalid')
        hata(a.post(f'{V1}/sessions', json={'type': 'multirotor', 'center_id': 99999}, headers=B(key)), 400, 'invalid')
        hata(a.post(f'{V1}/sessions', json={'mode': 'replay', 'log_id': 12345}, headers=B(key)), 400, 'invalid')
        hata(a.post(f'{V1}/sessions', json={'mode': 'x'}, headers=B(key)), 400, 'invalid')
        assert a.post(f'{V1}/sessions', json={'world': 'x'}, headers=B(key)).status_code == 422
        s = ok(a.post(f'{V1}/sessions', json={'type': 'sabit_kanat', 'center_id': c1['id'], 'world': {'seed': 7, 'time': 'dusk'}, 'model': 'builtin:caymaz'}, headers=B(key)), 201)
        sid = s['id']
        assert s['client'] == {'id': cid, 'name': 'Simülatör PC-1'} and s['owner'] == {'id': pilot_id, 'name': 'Pilot Bey'} and s['type'] == 'sabit_kanat', s
        assert s['world']['seed'] == 7 and s['world']['time'] == 'dusk' and s['world']['mountain_height'] == 300 and 25550 <= s['udp_port'] <= 25649 and s['host'] == 'testserver', s
        assert s['model']['id'] == 'builtin:caymaz' and s['model']['glb_url'] == f'{V1}/models/builtin:caymaz/glb' and s['airframe'] == 'caymaz', s['model']
        g = bekle(lambda: (lambda r: r if r['state'] == 'HAZIR' else None)(ok(a.get(f'{V1}/sessions/{sid}', headers=B(key)))))
        assert g and g['state'] == 'HAZIR'
        # web tarafı: aynı oturum listede, client alanı dolu (CAYSIM rozeti); web'den açılan oturumda client null
        web = ok(a.get('/api/drone/sim/sessions'))
        assert len(web) == 1 and web[0]['id'] == sid and web[0]['client'] == {'id': cid, 'name': 'Simülatör PC-1'} and web[0]['model']['glb_url'].startswith('/static/'), web
        s_web = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id']}), 201)
        assert s_web['client'] is None
        both = ok(a.get(f'{V1}/sessions', headers=B(key)))['sessions']
        assert [x['id'] for x in both] == [sid, s_web['id']] and both[1]['client'] is None    # istemci şirketin tüm oturumlarını görür
        hata(a.post(f'{V1}/sessions', json={'type': 'vtol', 'center_id': c1['id']}, headers=B(key)), 409, 'limit')
        assert ok(a.get('/api/drone/sim/clients'))['clients'][0]['sessions'] == 1
        # komutlar
        cmd = lambda name, params=None: a.post(f'{V1}/sessions/{sid}/cmd', json={'name': name, 'params': params or {}}, headers=B(key))   # noqa: E731
        hata(cmd('ucur'), 400, 'invalid')
        hata(cmd('rc', {'ch': [1500]}), 400, 'invalid')
        hata(cmd('mode', {'mode': 'UCUS'}), 400, 'invalid')
        ok(cmd('takeoff', {'alt': 60}))
        ok(cmd('mode', {'mode': 'FBWA'}))
        ok(cmd('set_home', {'lat': 39.93, 'lon': 32.84, 'alt': 905}))
        hata(a.post(f'{V1}/sessions/99999/cmd', json={'name': 'arm'}, headers=B(key)), 404, 'not_found')
        # mavlink bilgisi
        mv = ok(a.get(f'{V1}/sessions/{sid}/mavlink', headers=B(key)))
        assert mv == {'host': 'testserver', 'udp_port': s['udp_port'], 'gcs_locked': False, 'gcs_addr': None, 'note': mv['note']} and 'GCS' in mv['note'], mv
        hata(a.get(f'{V1}/sessions/{sid}/replay', headers=B(key)), 400, 'invalid')
        hata(a.get(f'{V1}/sessions/99999', headers=B(key)), 404, 'not_found')

        # ---------------- WS ----------------
        token = a.cookies.get(auth.COOKIE)
        with a.websocket_connect(f'/ws/caysim/v1/sessions/{sid}?key={key}') as ws:
            h = json.loads(ws.receive_text())
            assert h['t'] == 'hello' and h['v'] == 1 and h['can_command'] is True and h['server_time'], h
            assert h['session']['id'] == sid and h['session']['client']['id'] == cid and h['session']['model']['glb_url'].startswith(V1), h['session']
            assert ok(a.get('/api/drone/sim/clients'))['clients'][0]['online'] is True
            teles = []
            bitis = time.time() + 2
            while time.time() < bitis and len(teles) < 5:
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele':
                    teles.append(m)
            assert len(teles) >= 3 and TELE_ALANLARI <= set(teles[-1]), (len(teles), TELE_ALANLARI - set(teles[-1] if teles else {}))
            t0 = teles[-1]
            assert t0['armed'] is True and t0['mode'] == 'FBWA' and t0['home'] == {'lat': 39.93, 'lon': 32.84, 'alt': 905.0} and isinstance(t0['tbm'], int), t0
            # 50 Hz: 1 sn'de ≥ 40 kare
            ts = []
            bitis = time.time() + 1.0
            while time.time() < bitis:
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele':
                    ts.append(m['ts'])
            assert len(ts) >= 40, len(ts)
            ws.send_text(json.dumps({'t': 'ping'}))
            assert ws_bekle(ws, lambda x: x['t'] == 'pong', 2)
            # rc → tele'ye yansır; cmd → res
            ws.send_text(json.dumps({'t': 'rc', 'ch': [1600, 1400, 1900, 1500, 2000, 1500, 1500, 1500]}))
            assert ws_bekle(ws, lambda x: x['t'] == 'tele' and x['rc'][2] == 1900 and x['rc'][4] == 2000, 3), 'rc yansımadı'
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'crash', 'rid': 'k1'}))
            gor = {'res': None, 'event': None}
            bitis = time.time() + 3
            while time.time() < bitis and not all(gor.values()):
                m = json.loads(ws.receive_text())
                if m['t'] == 'res' and m.get('rid') == 'k1':
                    gor['res'] = m
                elif m['t'] == 'event' and 'ÇARPIŞMA' in m['text']:
                    gor['event'] = m
            assert gor['res'] and gor['res']['ok'] is True and gor['res']['name'] == 'crash', gor
            assert gor['event'] and gor['event']['severity'] == 2, gor
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'mode', 'params': {'mode': 'UCUS'}, 'rid': 'k2'}))
            res = ws_bekle(ws, lambda x: x['t'] == 'res' and x.get('rid') == 'k2', 3)
            assert res and res['ok'] is False and res['error'], res
            ws.send_text('bozuk json')   # yok sayılır
            ws.send_text(json.dumps({'t': 'ping'}))
            assert ws_bekle(ws, lambda x: x['t'] == 'pong', 2)
        assert bekle(lambda: ok(a.get('/api/drone/sim/clients'))['clients'][0]['online'] is False, 3)
        # ilk çerçeve `auth` ile kimlik
        with a.websocket_connect(f'/ws/caysim/v1/sessions/{sid}') as ws:
            ws.send_text(json.dumps({'t': 'auth', 'key': key}))
            assert json.loads(ws.receive_text())['t'] == 'hello'
        # yanlış anahtar → 4403; pasif → 4403; olmayan oturum → 4404; auth çerçevesi anahtarsız → 4400; çerez işe yaramaz
        with a.websocket_connect(f'/ws/caysim/v1/sessions/{sid}?key=yanlis') as ws:
            assert json.loads(ws.receive_text()) == {'t': 'error', 'error': 'auth'} and close_code(ws) == 4403
        with a.websocket_connect(f'/ws/caysim/v1/sessions/{sid}?key={key_pasif}') as ws:
            assert json.loads(ws.receive_text()) == {'t': 'error', 'error': 'client_inactive'} and close_code(ws) == 4403
        with a.websocket_connect(f'/ws/caysim/v1/sessions/99999?key={key}') as ws:
            assert json.loads(ws.receive_text()) == {'t': 'error', 'error': 'not_found'} and close_code(ws) == 4404
        with a.websocket_connect(f'/ws/caysim/v1/sessions/{sid}') as ws:
            ws.send_text(json.dumps({'t': 'ping'}))
            assert json.loads(ws.receive_text()) == {'t': 'error', 'error': 'auth'} and close_code(ws) == 4400
        with a.websocket_connect(f'/ws/caysim/v1/sessions/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
            ws.send_text('{bozuk')
            assert json.loads(ws.receive_text()) == {'t': 'error', 'error': 'timeout'} and close_code(ws) == 4400

        # ---------------- rekey: eski anahtar düşer, açık WS 4403 ----------------
        caysim._fails.clear()   # yukarıdaki kasıtlı başarısız denemeler sayaca yazıldı (gerçek davranış); bu bölüm temiz sayaçla
        with a.websocket_connect(f'/ws/caysim/v1/sessions/{sid}?key={key}') as ws:
            assert json.loads(ws.receive_text())['t'] == 'hello'
            r = ok(a.post(f'/api/drone/sim/clients/{cid}/rekey'))
            yeni = r['key']
            assert r['code'] == f'testserver/{yeni}' and yeni != key and len(yeni) == 43
            assert bekle(lambda: not caysim.WS_ACIK.get(cid), 3)
            try:
                kod = None
                bitis = time.time() + 3
                while time.time() < bitis:
                    ws.receive_text()
            except WebSocketDisconnect as e:
                kod = e.code
            assert kod == 4403, kod
        hata(a.get(f'{V1}/hello', headers=B(key)), 401, 'auth')
        ok(a.get(f'{V1}/hello', headers=B(yeni)))
        key = yeni
        # pasife alma → bağlantı reddi; yeniden aktif
        caysim._fails.clear()
        ok(a.put(f'/api/drone/sim/clients/{cid}', json={'active': False}))
        hata(a.get(f'{V1}/hello', headers=B(key)), 403, 'client_inactive')
        ok(a.put(f'/api/drone/sim/clients/{cid}', json={'active': True, 'note': 'yeni not'}))
        ok(a.get(f'{V1}/hello', headers=B(key)))
        assert ok(a.get('/api/drone/sim/clients'))['clients'][0]['note'] == 'yeni not'
        assert a.put(f'/api/drone/sim/clients/{cid}', json={'name': 'Pasif İstemci'}).status_code == 400
        assert a.put('/api/drone/sim/clients/99999', json={'name': 'x'}).status_code == 404

        # ---------------- oturum kapatma (istemciden) ----------------
        ok(a.delete(f'{V1}/sessions/{sid}', headers=B(key)))
        hata(a.delete(f'{V1}/sessions/{sid}', headers=B(key)), 404, 'not_found')
        assert [x['id'] for x in ok(a.get('/api/drone/sim/sessions'))] == [s_web['id']]
        ok(a.delete(f"/api/drone/sim/sessions/{s_web['id']}"))

        # ---------------- hız sınırı: IP başına 10 başarısız/dk → 429; sonra doğru anahtar da 429; WS 4429 ----------------
        caysim._fails.clear()
        for i in range(caysim.RATE_MAX - 1):
            hata(a.get(f'{V1}/hello', headers=B(f'yanlis-{i}')), 401, 'auth')
        ok(a.get(f'{V1}/hello', headers=B(key)))                                    # başarılı deneme sayılmaz
        hata(a.get(f'{V1}/hello', headers=B('yanlis-son')), 401, 'auth')             # 10. başarısız
        hata(a.get(f'{V1}/hello', headers=B('yanlis-11')), 429, 'rate_limited')
        hata(a.get(f'{V1}/hello', headers=B(key)), 429, 'rate_limited')             # doğru anahtar da bekler
        with a.websocket_connect(f'/ws/caysim/v1/sessions/1?key={key}') as ws:
            assert json.loads(ws.receive_text()) == {'t': 'error', 'error': 'rate_limited'} and close_code(ws) == 4429
        caysim._fails.clear()
        ok(a.get(f'{V1}/hello', headers=B(key)))

        # ---------------- sil ----------------
        ok(a.delete(f'/api/drone/sim/clients/{cid}'))
        assert a.delete(f'/api/drone/sim/clients/{cid}').status_code == 404
        hata(a.get(f'{V1}/hello', headers=B(key)), 401, 'auth')
        assert [c['name'] for c in ok(a.get('/api/drone/sim/clients'))['clients']] == ['Pasif İstemci']
        ok(a.delete(f"/api/drone/sim/clients/{r2['id']}"))
    assert flightsim.MANAGER.sessions == {}, flightsim.MANAGER.sessions
    print('CAYSIM istemci API testleri geçti.')


if __name__ == '__main__':
    main()
