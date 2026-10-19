"""SIMUMAV testleri (docs/simumav.md §4, §7): shim ile çekirdek yüklemesi, oturum (dev login), CSRF reddi, oran sınırı 429, hangar/crew/tracks/missions
CRUD + kota aşımı, parametre beyaz listesi reddi, parkur önizlemesi (ağsız sahte karo), fly/start sahte kipte (HEPGO_SITL=0) → flight kaydı + MP TCP
dinleyici IP kilidi (127.0.0.2'den ikinci bağlantı reddi), WS hello, stop → flights satırı, ops listesi / sahiplik 404, meta.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 ./.venv/bin/python -m tests.test_simumav
"""
import io
import json
import os
import socket
import sys
import tempfile
import time

D = tempfile.mkdtemp(prefix='simumav-test-')
os.environ.update(SIMUMAV_DATA_DIR=D, SIMUMAV_DEV_LOGIN='1', HEPGO_SITL='0', SIMUMAV_UDP_BASE='24750', SIMUMAV_MAX_FLIGHTS='2', SIMUMAV_MP_PORT_BASE='25600',
                  SIMUMAV_MP_PORT_COUNT='40', SIMUMAV_SECURE_COOKIE='0', SIMUMAV_ENV_FILE=os.path.join(D, 'yok.env'), SIMUMAV_MP_IDLE_S='4',
                  SIMUMAV_MT_INTERNAL='http://127.0.0.1:1', GOOGLE_MAPS_API_KEY='')
for k in [k for k in sys.modules if k == 'app' or k.startswith('app.')]:   # temiz başlangıç: çekirdek shim ile yüklenmeli
    del sys.modules[k]

from fastapi.testclient import TestClient  # noqa: E402

import app.simumav.main as smain  # noqa: E402
from app import flightsim, sim_terrain  # noqa: E402
from app.simumav import bridge, config  # noqa: E402

ORIGIN = 'http://127.0.0.1:8600'
H = {'Origin': ORIGIN}


def terrarium_png(taban=900.0):
    from PIL import Image
    im = Image.new('RGB', (256, 256))
    px = im.load()
    for y in range(256):
        for x in range(256):
            v = int(round((taban + x * 0.5 + 32768) * 256))
            px[x, y] = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
    buf = io.BytesIO(); im.save(buf, 'PNG'); return buf.getvalue()


def sahte_jpeg():
    from PIL import Image
    im = Image.new('RGB', (256, 256), (90, 120, 60))
    buf = io.BytesIO(); im.save(buf, 'JPEG'); return buf.getvalue()


class SahteFetch:
    def __init__(self):
        self.n = 0
        self.png, self.jpg = terrarium_png(), sahte_jpeg()

    def __call__(self, url, timeout=10, data=None):
        self.n += 1
        return self.png if 'terrarium' in url else self.jpg


def giris(c, ad):
    r = c.post('/api/session', json={'dev_user': ad}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def oturum(c, ad):
    """Aynı TestClient üzerinden ek kullanıcı: çerez başlığı ile (ayrı TestClient nesnesi her istekte kendi olay döngüsünü kapatır ve
    sunucudaki oturum görevlerini iptal eder — test artefaktı). Dönüş: (okuma başlıkları, yazma başlıkları)."""
    asil = c.cookies.get('smsid')
    r = c.post('/api/session', json={'dev_user': ad}, headers=H)
    assert r.status_code == 200, r.text
    tok = r.cookies.get('smsid')
    c.cookies.clear()
    c.cookies.set('smsid', asil)
    return {'Cookie': f'smsid={tok}'}, {'Cookie': f'smsid={tok}', 'Origin': ORIGIN}


def main():
    # ---- shim: HEPGO'ya özgü modüller SIMUMAV karşılıklarıyla yüklendi
    for k in ('app.config', 'app.db', 'app.drone_hub', 'app.feed', 'app.flightlog', 'app.flight_analysis'):
        assert getattr(sys.modules.get(k), 'SIMUMAV_SHIM', False), f'{k} shim değil'
    assert 'app.main' not in sys.modules and 'app.auth' not in sys.modules
    import app.flightsim_hub as fh
    assert fh.drone_hub.__name__ == 'app.simumav.shim.drone_hub' and fh.db.__name__ == 'app.simumav.shim.db'
    from app import config as core_cfg
    assert str(core_cfg.DATA_DIR).startswith(D) and str(core_cfg.UPLOAD_DIR).startswith(D)
    sim_terrain.FETCH = SahteFetch()
    config.RATE['write'] = (100000, 60)   # CRUD/kota sınamaları 60/dk yazma sınırını aşar; oran sınırı ayrı sınanır (session 10/dk)
    config.RATE['read'] = (100000, 60)

    with TestClient(smain.app, base_url=ORIGIN) as c:
        # ---- meta oturumsuz: 200, maps_key yok; güvenlik başlıkları
        r = c.get('/api/meta')
        assert r.status_code == 200 and r.json()['maps_key'] is None and r.json()['authenticated'] is False
        assert 'frame-ancestors' in r.headers['content-security-policy'] and r.headers['x-content-type-options'] == 'nosniff'
        assert "'unsafe-inline'" not in r.headers['content-security-policy'].split('script-src')[1].split(';')[0]
        # statik yönlendirmeler
        assert c.get('/sim/api.js').status_code == 200 and 'export const api' in c.get('/api.js').text and c.get('/static/js/api.js').status_code == 200
        assert c.get('/sim/flightsim.js').status_code == 200 and c.get('/ui.js').status_code == 200 and c.get('/main.js').status_code == 404
        assert c.get('/').status_code == 200 and c.get('/app/').status_code == 200 and c.get('/brand/simumav.svg').status_code == 200
        # oturumsuz API → 401 {detail:{error}}
        r = c.get('/api/hangar'); assert r.status_code == 401 and r.json()['detail']['error'] == 'unauthorized'

        # ---- oturum (dev login) + varsayılanlar
        s = giris(c, 'ali')
        assert s['user']['display_name'] == 'ali' and s['pilots_count'] == 1 and s['drones_count'] == 1 and s['tracks_count'] == 1
        assert 'smsid' in c.cookies
        s_tok = c.cookies['smsid']
        me = c.get('/api/session').json(); assert me['user']['id'] == s['user']['id'] and me['active_flight'] is None
        tr = c.get('/api/tracks').json()['tracks'][0]
        assert tr['name'] == 'TRTEST' and abs(tr['lat'] - 40.0990) < 1e-6 and tr['is_default'] and tr['world_mode'] == 'google3d' and tr['gates'] == []
        d0 = c.get('/api/hangar').json()['drones'][0]; assert d0['name'] == 'FPV-1' and d0['type'] == 'fpv' and d0['model_key'] == 'proc:quad250' and d0['proc']
        p0 = c.get('/api/crew').json()['pilots'][0]; assert p0['character'] == 'p01' and p0['name'] == 'ali'
        assert c.get('/api/meta').json()['authenticated'] is True
        # dev login kapalıyken token zorunlu; geçersiz token (hesap servisi erişilemez) → 503
        r = c.post('/api/session', json={}, headers=H); assert r.status_code == 422
        r = c.post('/api/session', json={'token': 'A' * 40}, headers=H); assert r.status_code == 503 and r.json()['detail']['error'] == 'account_service'

        # ---- CSRF: Origin yok / yabancı → 403; GET etkilenmez
        assert c.post('/api/crew', json={'name': 'x', 'character': 'p02'}).status_code == 403
        r = c.post('/api/crew', json={'name': 'x', 'character': 'p02'}, headers={'Origin': 'https://kotu.example'}); assert r.status_code == 403 and r.json()['detail']['error'] == 'csrf'
        assert c.post('/api/crew', json={'name': 'x', 'character': 'p02'}, headers={'Sec-Fetch-Site': 'same-origin'}).status_code == 201
        assert c.get('/api/crew').status_code == 200

        # ---- settings
        st = c.put('/api/settings', json={'lang': 'en', 'theme': 'light', 'sound': False}, headers=H).json()
        assert st['lang'] == 'en' and st['theme'] == 'light' and st['sound'] is False
        assert c.put('/api/settings', json={'lang': 'xx'}, headers=H).status_code == 422
        assert c.get('/api/session').json()['user']['lang'] == 'en'

        # ---- hangar: katalog, CRUD, param beyaz listesi, kota
        cat = c.get('/api/hangar/catalog').json()['types']
        keys = {t['key']: [m['key'] for m in t['models']] for t in cat}
        assert 'proc:interceptor' in keys['interceptor'] and 'proc:quad250' in keys['fpv'] and 'builtin:caymaz' in keys['plane'] and 'builtin:quad' in keys['multirotor']
        inter = next(m for t in cat for m in t['models'] if m['key'] == 'proc:interceptor')
        assert inter['proc'] and inter['defaults']['AIRSPEED_MAX'] == 170 and inter['defaults']['THR_MAX'] == 100 and inter['defaults']['TKOFF_THR_MAX'] == 100
        r = c.post('/api/hangar', json={'name': 'Ok', 'type': 'interceptor', 'model_key': 'proc:interceptor', 'params': inter['defaults'], 'color': '#00ff88'}, headers=H)
        assert r.status_code == 201, r.text
        okid = r.json()['id']; assert r.json()['params']['AIRSPEED_MAX'] == 170.0
        for kotu in ({'SERIAL1_BAUD': 57}, {'LOG_BITMASK': 1}, {'SYSID_THISMAV': 2}, {'BRD_SAFETYENABLE': 0}, {'SCR_ENABLE': 1}, {'ARMING_CHECK': 0},
                     {'thr_max': 'yüz'}, {'THR_MAX': 1e9}, {'../x': 1}, {'FS_GCS_ENABLE': 0}, {'RC1_MIN': 1000}):
            r = c.post('/api/hangar', json={'name': 'K', 'type': 'plane', 'model_key': 'builtin:delta', 'params': kotu}, headers=H)
            assert r.status_code == 422 and r.json()['detail']['error'] == 'param_rejected', (kotu, r.text)
        assert c.post('/api/hangar', json={'name': 'K', 'type': 'plane', 'model_key': 'proc:quad250'}, headers=H).status_code == 422   # tip/model uyumsuz
        assert c.post('/api/hangar', json={'name': 'K', 'type': 'uzaygemisi', 'model_key': 'builtin:quad'}, headers=H).status_code == 422
        assert c.post('/api/hangar', json={'name': 'x' * 41, 'type': 'plane', 'model_key': 'builtin:delta'}, headers=H).status_code == 422
        r = c.put(f'/api/hangar/{okid}', json={'name': 'Ok-2', 'is_default': True, 'params': {'THR_MAX': 90}}, headers=H)
        assert r.json()['name'] == 'Ok-2' and r.json()['is_default'] and r.json()['params'] == {'THR_MAX': 90.0}
        for i in range(config.QUOTA['drones']):
            r = c.post('/api/hangar', json={'name': f'Q{i}', 'type': 'multirotor', 'model_key': 'builtin:quad'}, headers=H)
            if r.status_code != 201:
                break
        assert r.status_code == 409 and r.json()['detail']['error'] == 'quota' and len(c.get('/api/hangar').json()['drones']) == config.QUOTA['drones']
        assert c.delete(f'/api/hangar/{okid}', headers=H).json()['ok'] and c.get('/api/hangar/catalog').status_code == 200

        # ---- crew
        chars = c.get('/api/crew/characters').json()['characters']
        assert len(chars) == 10 and chars[0]['key'] == 'p01' and chars[0]['gender'] == 'm' and sum(1 for x in chars if x['gender'] == 'f') >= 4
        assert c.post('/api/crew', json={'name': 'Ayşe', 'character': 'p99'}, headers=H).status_code == 422
        pid = c.post('/api/crew', json={'name': 'Ayşe', 'character': 'p04'}, headers=H).json()['id']
        assert c.put(f'/api/crew/{pid}', json={'is_default': True}, headers=H).json()['is_default']
        assert c.delete(f'/api/crew/{pid}', headers=H).json()['ok'] and c.delete(f'/api/crew/{pid}', headers=H).status_code == 404

        # ---- tracks: doğrulama, gates, world, preview
        tid0 = tr['id']
        r = c.post('/api/tracks', json={'name': 'Göl', 'lat': 40.10, 'lon': 33.40, 'radius_m': 100}, headers=H); assert r.status_code == 422   # yarıçap 200–5000
        r = c.post('/api/tracks', json={'name': 'Göl', 'lat': 40.10, 'lon': 33.40, 'wind': {'speed_ms': 45}}, headers=H); assert r.status_code == 422
        r = c.post('/api/tracks', json={'name': 'Göl', 'lat': 40.10, 'lon': 33.40, 'world_mode': 'mars'}, headers=H); assert r.status_code == 422
        r = c.post('/api/tracks', json={'name': 'Göl', 'lat': 40.10, 'lon': 33.40, 'world': {'size_m': 99999}}, headers=H); assert r.status_code == 422
        gates = [{'i': 0, 'lat': 40.1005, 'lon': 33.4005, 'agl_m': 5, 'yaw_deg': 90, 'radius_m': 3, 'kind': 'ring'}, {'i': 1, 'lat': 40.101, 'lon': 33.401, 'agl_m': 8, 'radius_m': 4, 'kind': 'gate'}]
        r = c.post('/api/tracks', json={'name': 'Göl', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural', 'world': {'seed': 7, 'runway': False, 'tree_density': 0.5},
                                        'gates': gates + [{'i': 2, 'lat': 41.0, 'lon': 33.4, 'radius_m': 3}]}, headers=H)
        assert r.status_code == 422 and 'dışında' in r.json()['detail']['message']
        r = c.post('/api/tracks', json={'name': 'Göl', 'lat': 40.10, 'lon': 33.40, 'radius_m': 1500, 'world_mode': 'procedural', 'world': {'seed': 7, 'runway': False, 'tree_density': 0.5}, 'gates': gates}, headers=H)
        assert r.status_code == 201, r.text
        t2 = r.json(); assert t2['world'] == {'seed': 7, 'runway': False, 'tree_density': 0.5} and len(t2['gates']) == 2 and t2['gates'][1]['kind'] == 'gate' and t2['world_mode'] == 'procedural'
        assert c.put(f"/api/tracks/{t2['id']}", json={'gates': [{'i': 5, 'lat': 40.1, 'lon': 33.4}]}, headers=H).status_code == 422   # sıra 0..n-1
        r = c.get(f'/api/tracks/{tid0}/preview.png'); assert r.status_code == 200 and r.headers['content-type'] == 'image/png' and r.content[:4] == b'\x89PNG', r.text[:200]
        from PIL import Image
        assert Image.open(io.BytesIO(r.content)).size == (512, 512)
        n = sim_terrain.FETCH.n; assert c.get(f'/api/tracks/{tid0}/preview.png').status_code == 200 and sim_terrain.FETCH.n == n   # önbellek
        for i in range(config.QUOTA['tracks']):
            r = c.post('/api/tracks', json={'name': f'T{i}', 'lat': 40.0 + i / 100, 'lon': 33.0}, headers=H)
            if r.status_code != 201:
                break
        assert r.status_code == 409 and r.json()['detail']['error'] == 'quota'

        # ---- missions: plan doğrulama (yarıçap dışı nokta, 500+ nokta), fpv_gates
        items = [{'seq': 1, 'command': 16, 'frame': 3, 'x': int(40.1002e7), 'y': int(33.4003e7), 'z': 60}]
        r = c.post('/api/missions', json={'track_id': t2['id'], 'name': 'Koridor', 'kind': 'corridor', 'plan': {'items': items}}, headers=H); assert r.status_code == 201, r.text
        mid = r.json()['id']
        r = c.post('/api/missions', json={'track_id': t2['id'], 'name': 'Uzak', 'kind': 'free', 'plan': {'items': [{'command': 16, 'x': int(41e7), 'y': int(33.4e7), 'z': 50}]}}, headers=H)
        assert r.status_code == 422 and r.json()['detail']['error'] == 'plan_rejected'
        r = c.post('/api/missions', json={'track_id': t2['id'], 'name': 'Çok', 'kind': 'free', 'plan': {'items': items * 501}}, headers=H); assert r.status_code == 422
        r = c.post('/api/missions', json={'track_id': t2['id'], 'name': 'Tur', 'kind': 'fpv_gates', 'plan': {'order': [0, 1, 0], 'laps': 3}}, headers=H); assert r.status_code == 201
        assert c.post('/api/missions', json={'track_id': t2['id'], 'name': 'Tur', 'kind': 'fpv_gates', 'plan': {'order': [7], 'laps': 3}}, headers=H).status_code == 422
        assert c.post('/api/missions', json={'track_id': t2['id'], 'name': 'Tur', 'kind': 'fpv_gates', 'plan': {'order': [0], 'laps': 11}}, headers=H).status_code == 422
        assert c.post('/api/missions', json={'track_id': t2['id'], 'name': 'x', 'kind': 'yok', 'plan': {}}, headers=H).status_code == 422
        assert len(c.get(f"/api/missions?track_id={t2['id']}").json()['missions']) == 2

        # ---- sahiplik: ikinci kullanıcı başkasının kayıtlarını göremez (404)
        HV, HVW = oturum(c, 'veli')
        assert c.get(f"/api/tracks/{tid0}/preview.png", headers=HV).status_code == 404 and c.put(f'/api/missions/{mid}', json={'name': 'x'}, headers=HVW).status_code == 404
        assert c.delete(f"/api/hangar/{d0['id']}", headers=HVW).status_code == 404

        # ---- fly/start (sahte kip): flight kaydı + MP TCP dinleyici + IP kilidi
        drone_id = d0['id']
        pilot_id = c.get('/api/crew').json()['pilots'][0]['id']
        r = c.post('/api/fly/start', json={'drone_id': drone_id, 'pilot_id': pilot_id, 'track_id': tid0, 'mission_id': mid, 'launch': 'hand'}, headers=H)
        assert r.status_code == 422   # görev başka parkura ait
        r = c.post('/api/fly/start', json={'drone_id': drone_id, 'pilot_id': pilot_id, 'track_id': t2['id'], 'mission_id': mid, 'launch': 'wheels', 'record': {'bin': True}}, headers=H)
        assert r.status_code == 201, r.text
        f = r.json(); fid, sid, port = f['flight_id'], f['sim_id'], f['mp']['port']
        assert f['mp']['proto'] == 'tcp' and 25600 <= port < 25640 and f['ws'] == f'/ws/fly/{sid}'
        # ikinci uçuş → 409 flight_active
        r = c.post('/api/fly/start', json={'drone_id': drone_id, 'pilot_id': pilot_id, 'track_id': t2['id'], 'launch': 'wheels'}, headers=H)
        assert r.status_code == 409 and r.json()['detail']['error'] == 'flight_active'
        # dron silinemez (uçuşta)
        assert c.delete(f'/api/hangar/{drone_id}', headers=H).status_code == 409
        st = c.get(f'/api/fly/{fid}').json()
        assert st['active'] and st['live']['sim_id'] == sid and st['live']['mp']['port'] == port and st['live']['mp']['locked_ip'] is None and st['live']['gates'] and st['mp']['connected'] is False
        assert c.get(f'/api/fly/{fid}', headers=HV).status_code == 404
        # MP TCP: 127.0.0.1'den bağlan, GCS kalp atışı gönder → SITL (sahte kip) kalp atışı TCP'den döner
        from pymavlink.dialects.v20 import ardupilotmega as D20
        enc = D20.MAVLink(None, srcSystem=255, srcComponent=190)
        hb = enc.heartbeat_encode(6, 8, 0, 0, 0).pack(enc)
        for _ in range(100):   # oturum HAZIR olsun
            if (bridge.oturum(sid) or flightsim.MANAGER.sessions[sid]).state == 'HAZIR':
                break
            time.sleep(0.05)
        s1 = socket.create_connection(('127.0.0.1', port), timeout=5)
        s1.sendall(hb)
        s1.settimeout(5)
        gelen = b''
        while len(gelen) < 8:
            gelen += s1.recv(4096)
        assert gelen[0] in (0xFE, 0xFD), gelen[:4]   # MAVLink çerçevesi (sahte kip 1 Hz HEARTBEAT)
        for _ in range(50):
            if c.get(f'/api/fly/{fid}').json()['live']['mp']['locked_ip'] == '127.0.0.1':
                break
            time.sleep(0.05)
        assert c.get(f'/api/fly/{fid}').json()['live']['mp']['locked_ip'] == '127.0.0.1'
        # farklı IP'den ikinci bağlantı reddedilir (127.0.0.2 → kaynak adresi farklı)
        s2 = socket.socket(); s2.bind(('127.0.0.2', 0)); s2.settimeout(5); s2.connect(('127.0.0.1', port))
        try:
            s2.sendall(hb)
            assert s2.recv(1024) == b''   # sunucu kapattı
        except (ConnectionResetError, BrokenPipeError):
            pass
        s2.close()
        # aynı IP'den aynı anda ikinci bağlantı da reddedilir (tek bağlantı)
        s3 = socket.create_connection(('127.0.0.1', port), timeout=5); s3.settimeout(5)
        try:
            assert s3.recv(1024) == b''
        except (ConnectionResetError, BrokenPipeError):
            pass
        s3.close()
        for _ in range(40):
            if c.get(f'/api/fly/{fid}').json()['live']['mp']['rejected'] >= 2:
                break
            time.sleep(0.05)
        assert c.get(f'/api/fly/{fid}').json()['live']['mp']['rejected'] >= 2
        # WS hello (çerezle) + başkası 4403
        CK = {'Cookie': f"smsid={c.cookies['smsid']}"}   # TestClient WS'e çerez eklemez
        with c.websocket_connect(f'/ws/fly/{sid}', headers=CK) as ws:
            hello = ws.receive_json(); assert hello['t'] == 'hello' and hello['session']['id'] == sid and hello['flight_id'] == fid and len(hello['gates']) == 2, json.dumps(hello)[:600]
            ws.send_json({'t': 'ping'});
            m = ws.receive_json()
            while m.get('t') not in ('pong',):
                m = ws.receive_json()
            ws.send_json({'t': 'cmd', 'name': 'arm', 'rid': 'r1'})
            while m.get('t') != 'res':
                m = ws.receive_json()
            assert m['ok'] is True
        # başkası (geçerli oturum, sahibi değil) → {'t':'error','error':'not_found'} + 4404; çerezsiz → auth
        with c.websocket_connect(f'/ws/fly/{sid}', headers=HV) as ws:
            assert ws.receive_json() == {'t': 'error', 'error': 'not_found'}
        with c.websocket_connect(f'/ws/fly/{sid}', headers={'Cookie': 'smsid=yok'}) as ws:
            assert ws.receive_json() == {'t': 'error', 'error': 'auth'}
        # uyumluluk yüzeyi: /api/drone/sim/sessions/{id}, cmd, meta
        assert c.get(f'/api/drone/sim/sessions/{sid}').json()['id'] == sid and c.get(f'/api/drone/sim/sessions/{sid}', headers=HV).status_code == 404
        assert c.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'mode', 'params': {'mode': 'LOITER'}}, headers=H).json()['ok']
        cm = c.get('/api/drone/sim/meta').json(); assert cm['simumav'] and cm['centers'][0]['name'] == 'TRTEST' and cm['limits']['max_minutes'] == 45
        # sunucu genel sınır (2): veli bir uçuş açar, üçüncü kullanıcı 429 bekleme odası
        tv = c.get('/api/tracks', headers=HV).json()['tracks'][0]; dv = c.get('/api/hangar', headers=HV).json()['drones'][0]; pv = c.get('/api/crew', headers=HV).json()['pilots'][0]
        r = c.post('/api/fly/start', json={'drone_id': dv['id'], 'pilot_id': pv['id'], 'track_id': tv['id'], 'launch': 'wheels'}, headers=HVW); assert r.status_code == 201, r.text
        fv = r.json()['flight_id']
        assert bridge.aktif_sayisi() == 2
        HC, HCW = oturum(c, 'can')
        t3 = c.get('/api/tracks', headers=HC).json()['tracks'][0]; d3 = c.get('/api/hangar', headers=HC).json()['drones'][0]; p3 = c.get('/api/crew', headers=HC).json()['pilots'][0]
        r = c.post('/api/fly/start', json={'drone_id': d3['id'], 'pilot_id': p3['id'], 'track_id': t3['id'], 'launch': 'wheels'}, headers=HCW)
        assert r.status_code == 429 and r.json()['detail']['error'] == 'server_full' and 'Retry-After' in r.headers, r.text
        # stop (gates sonucu ile) → flights satırı tamam; MP dinleyici kapandı
        s1.close()
        assert c.post(f'/api/fly/{fid}/stop', json={'gates': {'passed': 3, 'missed': 1, 'laps': 1, 'best_lap_s': 42.5}}, headers=H).json()['ok']
        r = c.post(f'/api/fly/{fid}/stop', json={'gates': {'passed': -1}}, headers=H); assert r.status_code == 422
        fl = c.get(f'/api/ops/{fid}').json()
        assert fl['ended_at'] and fl['result'] == 'ok' and fl['duration_s'] is not None and fl['active'] is False and fl['pilot']['name'] == 'ali' and fl['track']['name'] == 'Göl'
        assert fl['summary']['gates'] == {'passed': 3, 'missed': 1, 'laps': 1, 'best_lap_s': 42.5} and fl['mission']['name'] == 'Koridor'
        assert 'bin_path' not in fl and 'params_path' not in fl
        time.sleep(0.3)
        try:
            socket.create_connection(('127.0.0.1', port), timeout=1).close()
            assert False, 'MP portu kapanmalıydı'
        except OSError:
            pass
        assert c.get('/api/session').json()['active_flight'] is None and c.get('/api/crew').json()['pilots'][0]['flights'] == 1
        assert c.post(f'/api/fly/{fv}/stop', headers=HVW).json()['ok']
        # ops: liste, sahiplik 404, replay yok (sahte kipte .bin yok) → 404 no_bin, silme
        ops = c.get('/api/ops').json(); assert ops['total'] == 1 and ops['flights'][0]['id'] == fid and ops['stats']['flights'] == 1
        assert c.get(f'/api/ops/{fid}', headers=HV).status_code == 404 and c.delete(f'/api/ops/{fid}', headers=HVW).status_code == 404
        r = c.get(f'/api/ops/{fid}/replay'); assert r.status_code == 404 and r.json()['detail']['error'] == 'no_bin'
        assert c.get(f'/api/ops/{fid}/bin').status_code == 404
        assert c.delete(f'/api/ops/{fid}', headers=H).json()['ok'] and c.get('/api/ops').json()['total'] == 0
        # denetim kayıtları
        from app.simumav import db as sdb
        with sdb.connect() as conn:
            olaylar = {r[0] for r in conn.execute('SELECT DISTINCT event FROM audit')}
        assert {'login', 'csrf', 'quota', 'param_reject', 'plan_reject', 'fly_start', 'fly_stop', 'mp_reject'} <= olaylar, olaylar
        # dosya yolu denetimi: kök dışı yollar reddedilir
        assert bridge.dosya_yolu('../simumav.db') is None and bridge.dosya_yolu('/etc/passwd') is None and bridge.dosya_yolu('') is None

        # ---- oran sınırı: /api/session 10/dk/IP → 429 + Retry-After
        from app.simumav import auth as sauth
        sauth.oran_sifirla()
        codes = [c.post('/api/session', json={'dev_user': 'can'}, headers=HCW).status_code for _ in range(11)]
        assert codes[:10] == [200] * 10 and codes[10] == 429, codes
        r = c.post('/api/session', json={'dev_user': 'can'}, headers=HCW); assert r.status_code == 429 and r.headers.get('Retry-After') and r.json()['detail']['error'] == 'rate_limited'
        sauth.oran_sifirla()
        # çıkış
        c.cookies.clear(); c.cookies.set('smsid', s_tok)   # oran sınaması jar'a 'can' çerezi yazdı; ali'ye dön
        r1 = c.delete('/api/session', headers=H); r2 = c.get('/api/session')
        assert r1.json()['ok'] and r2.status_code == 401, (r1.text, r2.status_code, r2.text[:200])
    print('test_simumav: TAMAM')


if __name__ == '__main__':
    main()
