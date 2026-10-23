"""Dron Kameraları + görüntü köprüsü (app/drone_video.py, routers/drone.py; protokol v1.3): kamera CRUD ve doğrulama (RTSP/RTP, FPS,
çözünürlük, bit hızı), parolanın yanıtlara/izleyiciye sızmaması, köprüye video_cfg iletimi (auth_ok + kayıt değişince), /ws/drone/video
kimlik (yanlış anahtar 4403), izleyici WS (çerezsiz/yetkisiz 4403), init önbelleği + GOP dağıtımı + yeni izleyicinin anahtar parçadan
başlaması, yavaş izleyicide parça atlama, want on/off, JPEG anlık görüntü, Canlı Uçuş › Kameralar (görev seçimi, etkin köprü, HUD dronu, yetki).
Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_drone_video
"""
import asyncio
import faulthandler
import json
import os
import struct
import tempfile
import threading
import time

faulthandler.dump_traceback_later(170, exit=True)

os.environ.setdefault('HEPGO_SITL', '0')
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app import auth, db, drone_video  # noqa: E402
from app.main import app  # noqa: E402

PAROLA = 'Gizli-Kamera-Parolasi-9'


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json() if r.text else None


def login(c, u, p):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))
    return c.cookies.get(auth.COOKIE)


def box(typ, payload=b''):
    return struct.pack('>I4s', 8 + len(payload), typ.encode()) + payload


def fake_init():
    avcc = box('avcC', bytes([1, 0x64, 0x00, 0x28, 0xFF, 0xE1]))
    return box('ftyp', b'isom\x00\x00\x02\x00isomiso6avc1mp41') + box('moov', box('trak', box('mdia', avcc)))


def fake_frag(key, seq):
    flags = 0x02000000 if key else 0x01010000   # depends_on=2 (I) | depends_on=1 + non_sync
    trun = box('trun', struct.pack('>II', 0x000005, 3) + struct.pack('>i', 0) + struct.pack('>I', flags))
    tfhd = box('tfhd', struct.pack('>II', 0x020000, 1))
    moof = box('moof', box('mfhd', struct.pack('>II', 0, seq)) + box('traf', tfhd + trun))
    return moof + box('mdat', bytes([seq % 256]) * 200)


def frame(typ, cam_id, payload):
    return bytes([typ]) + struct.pack('>I', cam_id) + payload


def close_code(ws):
    try:
        for _ in range(50):
            m = ws.receive()
            if m.get('type') == 'websocket.close':
                return m.get('code')
    except WebSocketDisconnect as e:
        return e.code
    except Exception:   # noqa: BLE001
        return None


def recv_json(ws, want, limit=20):
    for _ in range(limit):
        m = ws.receive()
        if m.get('text'):
            j = json.loads(m['text'])
            if j.get('t') == want:
                return j
    raise AssertionError(f'{want} gelmedi')


def recv_any(ws):
    m = ws.receive()
    if m.get('text') is not None:
        return 'text', json.loads(m['text'])
    return 'bytes', m.get('bytes')


def crud_tests(a, bid, did):
    base = {'name': 'Gimbal', 'bridge_id': bid, 'drone_id': did, 'kind': 'rtsp', 'url': 'rtsp://192.168.144.25:8554/main.264', 'transport': 'tcp', 'fps': 0}
    bad = [
        ({**base, 'name': ' '}, 'ad'),
        ({**base, 'kind': 'http'}, 'tür'),
        ({**base, 'url': 'http://x/y'}, 'rtsp biçim'),
        ({**base, 'url': 'rtsp://admin:1234@192.168.1.10/stream'}, 'URL içinde kimlik'),
        ({**base, 'url': 'rtsp://host:70000/a'}, 'port aralığı'),
        ({**base, 'transport': 'sctp'}, 'taşıma'),
        ({**base, 'fps': 7}, 'FPS'),
        ({**base, 'width': 1280}, 'yalnız genişlik'),
        ({**base, 'width': 1281, 'height': 720}, 'tek sayı genişlik'),
        ({**base, 'bitrate_kbps': 50}, 'bit hızı'),
        ({**base, 'bridge_id': 99999}, 'köprü yok'),
        ({**base, 'drone_id': 99999}, 'dron yok'),
        ({**base, 'kind': 'rtp', 'url': None, 'rtp_port': 80}, 'RTP port'),
        ({**base, 'kind': 'rtp', 'rtp_port': 5600, 'codec': 'vp8'}, 'RTP kodek'),
        ({**base, 'kind': 'rtp', 'rtp_port': 5600, 'payload_type': 33}, 'yük türü'),
        ({**base, 'kind': 'rtp', 'rtp_port': 5600, 'sdp': 'm=audio 1 RTP/AVP 0'}, 'SDP'),
    ]
    for body, why in bad:
        r = a.post('/api/drone/cameras', json=body)
        assert r.status_code == 400, (why, r.status_code, r.text)
    for fps in drone_video.FPS_CHOICES:
        assert fps in (0, 5, 10, 15, 20, 25, 30)
    c1 = ok(a.post('/api/drone/cameras', json={**base, 'username': 'admin', 'password': PAROLA, 'fps': 15, 'width': 1280, 'height': 720, 'bitrate_kbps': 2500}))
    assert a.post('/api/drone/cameras', json={**base, 'name': 'gimbal'}).status_code == 400   # ad benzersiz (büyük/küçük harf)
    sdp = 'v=0\no=- 0 0 IN IP4 0.0.0.0\ns=x\nc=IN IP4 0.0.0.0\nt=0 0\nm=video 5600 RTP/AVP 96\na=rtpmap:96 H264/90000'
    c2 = ok(a.post('/api/drone/cameras', json={'name': 'RTP kamera', 'bridge_id': bid, 'kind': 'rtp', 'rtp_port': 5600, 'codec': 'h265', 'sdp': sdp,
                                               'password': 'yok-sayilir', 'fps': 10}))
    r = a.post('/api/drone/cameras', json={'name': 'RTP ikinci', 'bridge_id': bid, 'kind': 'rtp', 'rtp_port': 5600})
    assert r.status_code == 400 and 'RTP portu' in r.text, r.text   # aynı köprüde aynı port
    lst = ok(a.get('/api/drone/cameras'))
    raw = json.dumps(lst, ensure_ascii=False)
    assert PAROLA not in raw and 'password' not in raw.replace('has_password', '') and 'yok-sayilir' not in raw, raw
    g = {c['id']: c for c in lst}
    assert g[c1['id']]['has_password'] is True and g[c2['id']]['has_password'] is False, lst   # RTP'de parola tutulmaz
    assert g[c1['id']]['status'] == 'kopru_cevrimdisi' and g[c1['id']]['status_text'] == 'Köprü çevrim dışı', g[c1['id']]
    assert g[c2['id']]['payload_type'] == 96 and g[c2['id']]['codec'] == 'h265' and g[c2['id']]['url'] is None
    one = ok(a.get(f"/api/drone/cameras/{c1['id']}"))
    assert PAROLA not in json.dumps(one) and one['fps'] == 15 and one['width'] == 1280
    with db.connect() as conn:
        enc = conn.execute('SELECT password_enc FROM drone_cameras WHERE id = ?', (c1['id'],)).fetchone()[0]
    assert enc and PAROLA not in enc
    # parola None → korunur; password_clear → silinir; yeni parola → değişir
    upd = {**base, 'username': 'admin', 'fps': 15, 'width': 1280, 'height': 720, 'bitrate_kbps': 2500}
    ok(a.put(f"/api/drone/cameras/{c1['id']}", json=upd))
    assert ok(a.get(f"/api/drone/cameras/{c1['id']}"))['has_password'] is True
    d = ok(a.get(f'/api/drone/drones/{did}'))
    assert [c['name'] for c in d['cameras']] == ['Gimbal'] and PAROLA not in json.dumps(d)
    meta = ok(a.get('/api/drone/meta'))
    assert meta['can']['cameras'] and meta['write']['cameras'] and meta['camera_fps'] == [0, 5, 10, 15, 20, 25, 30] and meta['camera_kinds']['rtp'] == 'RTP'
    return c1['id'], c2['id'], upd


def frame_logic_tests():
    """Yavaş izleyici: bayt sınırı aşılınca parça atlanır, sonraki anahtar parçadan devam (doğrudan _on_frame)."""
    class FakeV(drone_video.VViewer):
        def __init__(self):
            self.q, self.pending, self.need_key, self.dropped, self.items = None, 0, True, 0, []

        def put(self, item, size=0):
            self.pending += size
            self.items.append(item)

    vb = drone_video.VBridge(None, {'id': 9001, 'name': 'x'}, 'h', '1')
    vb.cams = {777}
    st = drone_video.stream(777)
    fast, slow = FakeV(), FakeV()
    st.viewers |= {fast, slow}
    old = drone_video.VIEWER_MAX_BYTES
    drone_video.VIEWER_MAX_BYTES = 600
    try:
        drone_video._on_frame(vb, frame(1, 777, fake_init()))
        drone_video._on_frame(vb, frame(3, 777, fake_frag(False, 1)))   # init sonrası ilk ara parça: anahtar beklenir → atlanır
        assert not any(isinstance(x, bytes) and x[0] == 3 for x in fast.items)
        drone_video._on_frame(vb, frame(2, 777, fake_frag(True, 2)))
        fast.pending = 0
        for i in range(3):
            drone_video._on_frame(vb, frame(3, 777, fake_frag(False, 3 + i)))
            fast.pending = 0   # hızlı izleyici kuyruğunu boşaltıyor
        kinds = [x[0] for x in fast.items if isinstance(x, bytes)]
        assert kinds == [1, 2, 3, 3, 3], kinds
        sk = [x[0] for x in slow.items if isinstance(x, bytes)]
        assert sk[:2] == [1, 2] and slow.dropped >= 1 and slow.need_key is True, (sk, slow.dropped)
        n = len(sk)
        drone_video._on_frame(vb, frame(3, 777, fake_frag(False, 9)))   # hâlâ anahtar bekliyor
        assert len([x for x in slow.items if isinstance(x, bytes)]) == n
        slow.pending = 0
        drone_video._on_frame(vb, frame(2, 777, fake_frag(True, 10)))
        assert [x for x in slow.items if isinstance(x, bytes)][-1][0] == 2 and slow.need_key is False
        assert st.gop and st.gop[0][0] == 2 and len(st.gop) == 1
        drone_video._on_frame(vb, frame(2, 778, fake_frag(True, 11)))   # bu köprüde olmayan kamera: yok sayılır
        assert 778 not in drone_video.STREAMS
    finally:
        drone_video.VIEWER_MAX_BYTES = old
        drone_video.STREAMS.pop(777, None)
    print('  yavaş izleyici / parça atlama testleri geçti')


def main():
    frame_logic_tests()
    with TestClient(app, base_url='https://testserver') as a:
        token = login(a, 'admin@test', 'admin-sifre-1')
        with db.connect() as conn:
            assert 'caps' in {r[1] for r in conn.execute('PRAGMA table_info(drone_bridges)')}
            assert {'drone_cameras', 'field_task_cameras'} <= {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        b = ok(a.post('/api/drone/bridges', json={'name': 'Jetson-1', 'platform': 'linux'}))
        key = b['code'].split('/', 1)[1]
        b2 = ok(a.post('/api/drone/bridges', json={'name': 'Yedek köprü', 'platform': 'linux'}))
        key2 = b2['code'].split('/', 1)[1]
        d = ok(a.post('/api/drone/drones', json={'name': 'Göktungu-1'}))
        cam1, cam2, upd = crud_tests(a, b['id'], d['id'])
        print('  kamera CRUD / doğrulama / parola testleri geçti')

        # --- görüntü köprüsü kimliği ---
        with a.websocket_connect('/ws/drone/video') as ws:
            ws.send_text(json.dumps({'v': 1, 't': 'auth', 'key': 'yanlis-anahtar', 'host': 'x'}))
            assert json.loads(ws.receive_text())['code'] == 4403
            assert close_code(ws) == 4403
        # --- izleyici yetkisi: çerezsiz ---
        with a.websocket_connect(f'/ws/drone/video/watch?camera_id={cam1}', headers={'cookie': f'{auth.COOKIE}=yok'}) as w:
            assert json.loads(w.receive_text())['t'] == 'error'
            assert close_code(w) == 4403
        # yetkisiz kullanıcı (dron/saha modülü yok)
        other_role = next(r for r in auth.ROLES if r not in auth.MODULE_ROLES.get('field', []) and r not in auth.MODULE_ROLES.get('drone', []) and r != auth.ADMIN)
        ok(a.post('/api/users', json={'username': 'disari@test', 'full_name': 'Dışarı', 'roles': [other_role], 'password': 'Gizli-Parola-77'}))
        with TestClient(app, base_url='https://testserver') as o:
            tok = login(o, 'disari@test', 'Gizli-Parola-77')
            assert o.get('/api/drone/cameras').status_code == 403
            assert o.get(f'/api/drone/cameras/{cam1}/snapshot.jpg').status_code == 403
            with o.websocket_connect(f'/ws/drone/video/watch?camera_id={cam1}', headers={'cookie': f'{auth.COOKIE}={tok}'}) as w:
                assert json.loads(w.receive_text())['t'] == 'error'
                assert close_code(w) == 4403
        # köprü çevrim dışıyken anlık görüntü → 503
        assert a.get(f'/api/drone/cameras/{cam1}/snapshot.jpg').status_code == 503

        with a.websocket_connect('/ws/drone/video') as br:
            br.send_text(json.dumps({'v': 1, 't': 'auth', 'key': key, 'host': 'jetson-nano', 'platform': 'linux', 'bridge_ver': '1.1.0', 'caps': ['video']}))
            ao = json.loads(br.receive_text())
            assert ao['t'] == 'auth_ok' and ao['bridge_id'] == b['id'], ao
            cams = {c['id']: c for c in ao['cameras']}
            assert set(cams) == {cam1, cam2}, cams
            assert cams[cam1]['password'] == PAROLA and cams[cam1]['username'] == 'admin' and cams[cam1]['fps'] == 15   # parola YALNIZ köprüye
            assert cams[cam1]['url'] == 'rtsp://192.168.144.25:8554/main.264' and cams[cam2]['rtp_port'] == 5600 and cams[cam2]['sdp'].startswith('v=0')
            bl = {x['id']: x for x in ok(a.get('/api/drone/bridges'))}
            assert bl[b['id']]['video_online'] is True and bl[b['id']]['video'] is True and bl[b['id']]['camera_count'] == 2, bl[b['id']]
            assert ok(a.get(f'/api/drone/cameras/{cam1}'))['status'] == 'hazir'
            # kayıt değişince köprüye video_cfg
            ok(a.put(f'/api/drone/cameras/{cam1}', json={**upd, 'fps': 25}))
            vc = recv_json(br, 'video_cfg')
            assert {c['id']: c for c in vc['cameras']}[cam1]['fps'] == 25, vc
            ok(a.post(f'/api/drone/cameras/{cam2}/active', json={'active': False}))
            vc = recv_json(br, 'video_cfg')
            assert [c['id'] for c in vc['cameras']] == [cam1], vc
            # izleyici → want on
            with a.websocket_connect(f'/ws/drone/video/watch?camera_id={cam1}', headers={'cookie': f'{auth.COOKIE}={token}'}) as w1:
                hello = json.loads(w1.receive_text())
                assert hello['t'] == 'hello' and hello['bridge_online'] is True and hello['camera']['name'] == 'Gimbal', hello
                assert PAROLA not in json.dumps(hello)
                want = recv_json(br, 'want')
                assert want == {'t': 'want', 'camera_id': cam1, 'on': True}, want
                mime = 'video/mp4; codecs="avc1.640028"'
                br.send_text(json.dumps({'t': 'vstate', 'camera_id': cam1, 'state': 'canli', 'detail': 'Yayında', 'mime': mime}))
                assert recv_json(w1, 'state')['state'] == 'canli'
                init = fake_init()
                br.send_bytes(frame(1, cam1, init))
                br.send_bytes(frame(2, cam1, fake_frag(True, 1)))
                br.send_bytes(frame(3, cam1, fake_frag(False, 2)))
                got = []
                while len([g for g in got if g[0] == 'bytes']) < 3:
                    got.append(recv_any(w1))
                bins = [g[1] for g in got if g[0] == 'bytes']
                assert [x[0] for x in bins] == [1, 2, 3] and bins[0][1:] == init, [x[:1] for x in bins]
                assert any(g[0] == 'text' and g[1]['t'] == 'init' and g[1]['mime'] == mime for g in got), got
                br.send_text(json.dumps({'t': 'stat', 'camera_id': cam1, 'kbps': 1800, 'fps': 25.0, 'codec': 'h264', 'copy': True}))
                stt = recv_json(w1, 'stat')
                assert stt['kbps'] == 1800 and stt['age'] is not None and stt['age'] < 5, stt
                assert ok(a.get(f'/api/drone/cameras/{cam1}'))['status'] == 'canli'
                # ikinci izleyici: init + GOP (anahtar parçadan itibaren) hemen gelir; want yeniden gönderilmez
                with a.websocket_connect(f'/ws/drone/video/watch?camera_id={cam1}', headers={'cookie': f'{auth.COOKIE}={token}'}) as w2:
                    got2 = []
                    while len([g for g in got2 if g[0] == 'bytes']) < 3:
                        got2.append(recv_any(w2))
                    assert [g[1][0] for g in got2 if g[0] == 'bytes'] == [1, 2, 3], got2
                # JPEG anlık görüntü: REST isteği köprüye {t:'snap'} gönderir, köprü tür 4 ile yanıtlar
                res = {}
                th = threading.Thread(target=lambda: res.update(r=a.get(f'/api/drone/cameras/{cam1}/snapshot.jpg')))
                th.start()
                sn = recv_json(br, 'snap')
                assert sn['camera_id'] == cam1
                jpg = b'\xff\xd8\xff\xe0' + b'\x00' * 50 + b'\xff\xd9'
                br.send_bytes(frame(4, cam1, jpg))
                th.join(10)
                assert res['r'].status_code == 200 and res['r'].content == jpg and res['r'].headers['content-type'] == 'image/jpeg', res
                # anlık görüntü hatası
                th = threading.Thread(target=lambda: res.update(r=a.get(f'/api/drone/cameras/{cam1}/snapshot.jpg')))
                th.start()
                recv_json(br, 'snap')
                br.send_text(json.dumps({'t': 'snap_err', 'camera_id': cam1, 'error': 'Kaynaktan kare alınamadı'}))
                th.join(10)
                assert res['r'].status_code == 503 and 'kare' in res['r'].text, res['r'].text
            # son izleyici gidince LINGER sonra want off
            old = drone_video.LINGER
            print('  video WS uçtan uca (init, dağıtım, ikinci izleyici, anlık görüntü) geçti')

            # --- Canlı Uçuş › Kameralar: görev seçimi + etkin köprü + HUD dronu ---
            pilot = ok(a.post('/api/users', json={'username': 'pilot@test', 'full_name': 'Pilot', 'roles': [auth.PILOT, auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
            lead = ok(a.post('/api/users', json={'username': 'saha@test', 'full_name': 'Saha', 'roles': [auth.FIELD_LEAD], 'password': 'Gizli-Parola-77'}))
            t = ok(a.post('/api/field/tasks', json={'drone_ids': [d['id']], 'lead_id': lead['id'], 'pilot_id': pilot['id'], 'staff_ids': [pilot['id']]}))
            tc = ok(a.get(f"/api/drone/tasks/{t['id']}/cameras"))
            assert tc['assigned'] == [] and tc['can_edit'] is True and [x['drone_id'] for x in tc['drones']] == [d['id']], tc
            assert {x['id'] for x in tc['available']} == {cam1} and 'url' not in tc['available'][0] and PAROLA not in json.dumps(tc)
            assert a.put(f"/api/drone/tasks/{t['id']}/cameras/{cam1}", json={'drone_id': 99999}).status_code == 400   # görevde olmayan dron
            assert a.put(f"/api/drone/tasks/{t['id']}/cameras/{cam1}", json={'bridge_id': 99999}).status_code == 400
            assert a.put(f"/api/drone/tasks/{t['id']}/cameras/{cam2}", json={}).status_code == 400   # pasif kamera
            ok(a.put(f"/api/drone/tasks/{t['id']}/cameras/{cam1}", json={}))
            tc = ok(a.get(f"/api/drone/tasks/{t['id']}/cameras"))
            assert len(tc['assigned']) == 1 and tc['assigned'][0]['hud_drone_id'] == d['id'] and tc['assigned'][0]['task_bridge_id'] is None, tc['assigned']
            # köprüyü bu görev için değiştir → kamera eski köprünün listesinden çıkar, yenisinin listesine girer
            ok(a.put(f"/api/drone/tasks/{t['id']}/cameras/{cam1}", json={'bridge_id': b2['id'], 'drone_id': d['id']}))
            vc = recv_json(br, 'video_cfg')
            assert vc['cameras'] == [], vc
            ok(a.put(f"/api/drone/tasks/{t['id']}/cameras/{cam1}", json={'drone_id': None}))   # yalnız dron: köprü seçimi korunur
            ta = ok(a.get(f"/api/drone/tasks/{t['id']}/cameras"))['assigned'][0]
            assert ta['task_bridge_id'] == b2['id'] and ta['hud_drone_id'] == d['id'], ta   # dron boş → kamera kaydının dronu (görevde)
            with a.websocket_connect('/ws/drone/video') as br2:
                br2.send_text(json.dumps({'v': 1, 't': 'auth', 'key': key2, 'host': 'jetson-2', 'caps': ['video']}))
                ao2 = json.loads(br2.receive_text())
                assert [c['id'] for c in ao2['cameras']] == [cam1], ao2
                assert ok(a.get(f'/api/drone/cameras/{cam1}'))['eff_bridge_id'] == b2['id']
            # görev kapanınca etkin köprü kayıtlı köprüye döner
            with db.connect() as conn:
                conn.execute("UPDATE field_tasks SET status = 'TAMAMLANDI' WHERE id = ?", (t['id'],))
                conn.commit()
            assert ok(a.get(f'/api/drone/cameras/{cam1}'))['eff_bridge_id'] == b['id']
            with db.connect() as conn:
                conn.execute("UPDATE field_tasks SET status = 'BASLANGIC' WHERE id = ?", (t['id'],))
                conn.commit()
            # yetki: görev üyesi olmayan saha personeli → 403; pilot (üye) okur
            ok(a.post('/api/users', json={'username': 'saha2@test', 'full_name': 'Saha 2', 'roles': [auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
            with TestClient(app, base_url='https://testserver') as o2:
                login(o2, 'saha2@test', 'Gizli-Parola-77')
                assert o2.get(f"/api/drone/tasks/{t['id']}/cameras").status_code == 403
            with TestClient(app, base_url='https://testserver') as p:
                login(p, 'pilot@test', 'Gizli-Parola-77')
                pc = ok(p.get(f"/api/drone/tasks/{t['id']}/cameras"))
                assert [x['id'] for x in pc['assigned']] == [cam1]
                assert ok(p.get(f"/api/drone/camera-list?task_id={t['id']}"))[0]['id'] == cam1
            ok(a.delete(f"/api/drone/tasks/{t['id']}/cameras/{cam1}"))
            assert a.delete(f"/api/drone/tasks/{t['id']}/cameras/{cam1}").status_code == 404
            vc = recv_json(br, 'video_cfg')
            assert [c['id'] for c in vc['cameras']] == [cam1], vc
            print('  Canlı Uçuş › Kameralar (görev seçimi, etkin köprü, yetki) geçti')

            # bağlı köprü silinemez; bağlantıyı kes
            assert a.delete(f"/api/drone/bridges/{b['id']}").status_code == 400
            ok(a.delete(f'/api/drone/cameras/{cam2}'))
            ok(a.post(f"/api/drone/bridges/{b['id']}/disconnect"))
            assert close_code(br) in (1000, None)
        assert drone_video.LINGER == old
        time.sleep(0.2)
        assert b['id'] not in drone_video.VBRIDGES
        assert ok(a.get(f'/api/drone/cameras/{cam1}'))['status'] == 'kopru_cevrimdisi'
        with db.connect() as conn:
            acts = {r[0] for r in conn.execute("SELECT action FROM audit_logs WHERE entity = 'drone_camera'")}
        assert {'Dron kamerası ekledi', 'Dron kamerası güncelledi', 'Dron kamerası sildi'} <= acts, acts
    print('Dron kameraları / görüntü köprüsü testleri geçti.')


if __name__ == '__main__':
    main()
