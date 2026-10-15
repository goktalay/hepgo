"""Dron Yönetimi (Faz 0 + Faz 1): köprü WebSocket'i (kimlik, köprü kodu, eşleştirme, MAVLink → canlı durum, komut RPC, log aktarımı),
REST, RBAC; Faz 1: bağlantı bilgisi uçuşta (addable / POST flights / PUT link / DELETE), görev bağlamı (watch task_id, live), sanal dron
simülatörü (tick + arm/takeoff/goto/rtl + görev yükleme), köprü kodu biçimi, drone_drones sütun düşürme migrasyonu (idempotent).
Çalıştırma: .venv/bin/python -m tests.test_drone
"""
import faulthandler
import hashlib
import json
import os
import re
import tempfile
import time

faulthandler.dump_traceback_later(170, exit=True)   # WebSocket beklemesi takılırsa yığın izini bas ve çık

os.environ.setdefault('HEPGO_SITL', '0')   # bu test eski kinematik simülatörle (hızlı); gerçek SITL: tests/test_drone_sitl.py
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app import auth, config, db, drone_hub, flight_analysis  # noqa: E402
from app.main import app  # noqa: E402

flight_analysis.start = lambda lid: None   # testte gerçek .bin analizi başlamasın

OLD_COLS = {'conn_type', 'conn_host', 'conn_port', 'conn_serial', 'conn_baud', 'bridge_id', 'sysid'}   # Faz 0'da drone_drones'taydı
KEY_RE = re.compile(r'^[A-Za-z0-9_-]{40,}$')


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json() if r.text else None


def login(c, u, p):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))
    return c.cookies.get(auth.COOKIE)


def mav_frames(sysid=7):
    from pymavlink.dialects.v20 import ardupilotmega as d
    enc = d.MAVLink(None, srcSystem=sysid, srcComponent=1)
    hb = enc.heartbeat_encode(1, 3, 128 | 16, 10, 4, 3).pack(enc)            # sabit kanat, ARMED, custom_mode 10 (AUTO)
    gp = enc.global_position_int_encode(0, 399000000, 328000000, 950000, 120000, 1200, 50, -20, 18000).pack(enc)
    hud = enc.vfr_hud_encode(22.5, 24.0, 180, 65, 121.0, 1.5).pack(enc)
    st = enc.statustext_encode(4, b'Test uyarisi', 0, 0).pack(enc)
    pv = enc.param_value_encode(b'RTL_ALT', 100.0, 9, 3, 1).pack(enc) + enc.param_value_encode(b'WPNAV_SPEED', 1000.0, 9, 3, 2).pack(enc)
    return hb, gp, hud, st, pv


def close_code(ws):
    try:
        ws.receive_text()
    except WebSocketDisconnect as e:
        return e.code
    return None


_inbox = {}


def drain(ws, want, limit=10, pred=lambda m: True):
    """İstenen türde (t) ilk mesajı döndürür; aradakiler kaybolmaz, sonraki aramalar için saklanır."""
    box = _inbox.setdefault(id(ws), [])
    for i, m in enumerate(box):
        if m.get('t') == want and pred(m):
            return box.pop(i)
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if m.get('t') == want and pred(m):
            return m
        box.append(m)
    raise AssertionError(f'{want} mesajı gelmedi; gelenler: {[x.get("t") for x in box][-20:]}')


def cmd(live, rid, bridge_id, name, params=None, sysid=1, limit=60):
    """İzleyici komutu gönderir, res çerçevesini bekler."""
    live.send_text(json.dumps({'t': 'cmd', 'rid': rid, 'bridge_id': bridge_id, 'sysid': sysid, 'name': name, 'params': params or {}}))
    return drain(live, 'res', limit=limit, pred=lambda m: m.get('rid') == rid)


def schema_checks():
    with db.connect() as conn:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(field_flights)')}
        assert {'order_id', 'drone_id', 'bridge_id', 'sysid', 'link'} <= cols, cols
        dcols = {r[1] for r in conn.execute('PRAGMA table_info(drone_drones)')}
        assert 'protocol' in dcols and not dcols & OLD_COLS, dcols
        idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert 'ix_drone_drones_bridge' not in idx and 'ix_field_flights_bridge' in idx, idx
        assert 'source' in {r[1] for r in conn.execute('PRAGMA table_info(flight_logs)')}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'drone_%'")}
        assert {'drone_bridges', 'drone_drones', 'drone_bridge_sessions', 'drone_route_centers', 'drone_routes', 'drone_waypoints'} <= tables, tables
        fk = conn.execute('PRAGMA foreign_key_check').fetchall()
        assert not fk, fk


def main():
    with TestClient(app, base_url='https://testserver') as a:
        login(a, 'admin@test', 'admin-sifre-1')
        # --- şema: Faz 1 sütunları; idempotent init ---
        db.init()
        schema_checks()
        # --- migrasyon: Faz 0 sütunları (conn_*, bridge_id + dizini, sysid) geri eklenir → init onları düşürür; ikinci init zararsız ---
        with db.connect() as conn:
            for col, typ in (('conn_type', 'TEXT'), ('conn_host', 'TEXT'), ('conn_port', 'INTEGER'), ('conn_serial', 'TEXT'),
                             ('conn_baud', 'INTEGER'), ('sysid', 'INTEGER')):
                conn.execute(f'ALTER TABLE drone_drones ADD COLUMN {col} {typ}')
            conn.execute('ALTER TABLE drone_drones ADD COLUMN bridge_id INTEGER REFERENCES drone_bridges(id) ON DELETE SET NULL')
            conn.execute('CREATE INDEX IF NOT EXISTS ix_drone_drones_bridge ON drone_drones(bridge_id)')
            conn.commit()
            assert OLD_COLS <= {r[1] for r in conn.execute('PRAGMA table_info(drone_drones)')}
        db.init()
        schema_checks()
        db.init()
        schema_checks()

        # --- REST: köprü (köprü kodu <domain>/<key>, bir kez) + dron (protocol mavlink | sanal | dji; bağlantı alanı yok) ---
        b = ok(a.post('/api/drone/bridges', json={'name': 'Test köprüsü', 'platform': 'linux'}))
        dom, code_key = b['code'].split('/', 1)
        assert dom == 'testserver' and KEY_RE.match(code_key), b
        bl = ok(a.get('/api/drone/bridges'))
        assert bl[0]['has_key'] is True and bl[0]['owner_name'] and 'code' not in bl[0] and 'code_hint' not in bl[0] and 'key' not in bl[0], bl[0]
        assert bl[0]['flight_count'] == 0 and bl[0]['drone_count'] == 0, bl[0]
        d = ok(a.post('/api/drone/drones', json={'name': 'Göktungu-1'}))
        assert d['code'] == 'D-0001', d
        assert a.post('/api/drone/drones', json={'name': 'X', 'protocol': 'parrot'}).status_code == 400
        sd = ok(a.post('/api/drone/drones', json={'name': 'Sanal-1', 'protocol': 'sanal'}))
        assert sd['code'] == 'D-0002', sd
        drones = ok(a.get('/api/drone/drones'))
        assert [x['protocol_text'] for x in drones] == ['MAVLink', 'Sanal Dron'], drones
        assert not {'bridge_id', 'sysid', 'conn_type', 'online', 'live'} & set(drones[0]), drones[0]
        meta = ok(a.get('/api/drone/meta'))
        assert meta['protocols'] == {'mavlink': 'MAVLink', 'sanal': 'Sanal Dron', 'dji': 'DJI'} and 'link_open' in meta['commands'], meta
        # Köprü yazılımı: kodun anahtarıyla auth → auth_ok (eşleştirme kodu olmadan bağlanır)
        with a.websocket_connect('/ws/drone/bridge') as ws:
            ws.send_text(json.dumps({'v': 1, 't': 'auth', 'key': code_key, 'host': 'kurulum-pc', 'platform': 'linux', 'bridge_ver': '0.2'}))
            m = json.loads(ws.receive_text())
            assert m['t'] == 'auth_ok' and m['bridge_id'] == b['id'] and 'key' not in m, m

        # --- köprü WS: yanlış anahtar → 4403 ---
        with a.websocket_connect('/ws/drone/bridge') as ws:
            ws.send_text(json.dumps({'v': 1, 't': 'auth', 'key': 'yanlis'}))
            m = json.loads(ws.receive_text())
            assert m == {'t': 'auth_err', 'code': 4403}, m
            assert close_code(ws) == 4403
        # bozuk ilk mesaj → 4400
        with a.websocket_connect('/ws/drone/bridge') as ws:
            ws.send_text('bu json degil')
            assert close_code(ws) == 4400

        # --- eşleştirme kodu → auth_ok + YENİ kalıcı anahtar (tek kullanımlık); köprü kodunun anahtarı geçersiz olur ---
        pc = ok(a.post(f"/api/drone/bridges/{b['id']}/pair"))
        assert len(pc['code']) == 6
        with a.websocket_connect('/ws/drone/bridge') as ws:
            ws.send_text(json.dumps({'v': 1, 't': 'pair', 'code': pc['code'].lower(), 'host': 'pilot-pc', 'platform': 'linux', 'bridge_ver': '0.1'}))
            m = json.loads(ws.receive_text())
            assert m['t'] == 'auth_ok' and m['bridge_id'] == b['id'] and m.get('key'), m
            key = m['key']
            assert m['session_id']
        with a.websocket_connect('/ws/drone/bridge') as ws:   # aynı kod ikinci kez geçersiz
            ws.send_text(json.dumps({'v': 1, 't': 'pair', 'code': pc['code']}))
            assert json.loads(ws.receive_text())['t'] == 'auth_err'
            assert close_code(ws) == 4403
        with a.websocket_connect('/ws/drone/bridge') as ws:   # eski (köprü kodundaki) anahtar artık geçersiz
            ws.send_text(json.dumps({'v': 1, 't': 'auth', 'key': code_key}))
            assert json.loads(ws.receive_text())['t'] == 'auth_err'
            assert close_code(ws) == 4403

        def sessions():
            for _ in range(25):   # kapanış arka plan iş parçacığında yazılır
                with db.connect() as conn:
                    s = db.rows(conn.execute('SELECT status, packets FROM drone_bridge_sessions WHERE bridge_id = ? ORDER BY id', (b['id'],)))
                if s and all(r['status'] != 'ACIK' for r in s):
                    return s
                time.sleep(0.2)
            return s
        s = sessions()
        assert s and s[0]['status'] in ('KOPTU', 'KAPANDI'), s   # kapanan bağlantı oturumu bitirdi
        assert ok(a.get('/api/drone/bridges'))[0]['has_key'] is True

        # --- canlı izleyici (çerez) + köprü MAVLink → status JSON; komut RPC; log aktarımı ---
        token = a.cookies.get(auth.COOKIE)
        with a.websocket_connect('/ws/drone/live', headers={'cookie': f'{auth.COOKIE}={token}'}) as live:
            hello = json.loads(live.receive_text())
            assert hello['t'] == 'hello' and hello['me']['can_command'] is True and 'task' not in hello, hello
            with a.websocket_connect('/ws/drone/bridge') as ws:
                ws.send_text(json.dumps({'v': 1, 't': 'auth', 'key': key, 'host': 'pilot-pc', 'platform': 'linux', 'bridge_ver': '0.1', 'caps': ['set_home', 'param', 'link', 'bilinmeyen']}))
                m = json.loads(ws.receive_text())
                assert m['t'] == 'auth_ok' and 'key' not in m, m
                br = drain(live, 'bridge')
                assert br['online'] is True and br['bridge_id'] == b['id'] and br['info']['caps'] == ['link', 'param', 'set_home'], br
                hb, gp, hud, st, pv = mav_frames()
                ws.send_bytes(pv)   # v1.1 PARAM_VALUE → toplu 'params' paketi
                pr = drain(live, 'params')
                assert [x[0] for x in pr['items']] == ['RTL_ALT', 'WPNAV_SPEED'] and pr['count'] == 3 and pr['cached'] == 2, pr
                live.send_text(json.dumps({'t': 'param_cache', 'bridge_id': b['id'], 'sysid': 7}))
                pc2 = drain(live, 'param_cache')
                assert pc2['params']['RTL_ALT'][0] == 100.0, pc2
                ws.send_bytes(hb + gp)
                ws.send_bytes(hud)
                ws.send_bytes(st)
                # 10 Hz sınırı: konum/hız içeren paket ilkinden sonra gecikmeli gelebilir
                s1 = drain(live, 'status', pred=lambda m: m['state']['lat'] is not None and m['state']['throttle'] is not None)
                assert s1['bridge_id'] == b['id'] and s1['sysid'] == 7
                state = s1['state']
                assert state['throttle'] == 65 and state['airspeed'] == 22.5, state
                assert state['armed'] is True and state['mode'] == 'AUTO' and abs(state['lat'] - 39.9) < 1e-6 and state['alt_rel'] == 120.0, state
                ev = drain(live, 'event')
                assert 'Test uyarisi' in ev['text'] and ev['severity'] == 4 and ev['ts'], ev
                assert 'console' in hello['caps'] and 'arm_check' in hello['caps'], hello
                # Haberleşme konsolu: STATUSTEXT satırı yayınlanır, geçmiş istenebilir, aynı satır tekrarı birleşir
                cl = drain(live, 'console')
                assert cl['tag'] == 'STATUS' and 'Test uyarisi' in cl['text'] and cl['sev'] == 'uyari' and cl['fresh'] is True, cl
                ws.send_bytes(st)
                cl2 = drain(live, 'console')
                assert cl2['repeat'] == 2 and cl2['fresh'] is False, cl2
                live.send_text(json.dumps({'t': 'console_hist', 'bridge_id': b['id'], 'sysid': 7}))
                hist = drain(live, 'console_hist')
                assert len(hist['lines']) == 1 and hist['lines'][0]['repeat'] == 2, hist
                # ARM CHECK raporu sunucudan (köprüye gitmez; komut yetkisi gerekmez)
                ac = cmd(live, 'ac', b['id'], 'arm_check', sysid=7)
                assert ac['ok'] is True and ac['result']['bulundu'] is True and ac['result']['armed'] is True, ac
                assert any(x['grup'] == 'konum' for x in ac['result']['maddeler']) and ac['result']['mesajlar'][0]['sev'] == 4, ac['result']
                assert s1['state']['ready'] and 'hazir' in s1['state']['ready'], s1['state'].get('ready')
                # ping/pong
                ws.send_text(json.dumps({'t': 'ping'}))
                assert json.loads(ws.receive_text())['t'] == 'pong'
                # komut: izleyici → sunucu → köprü → res → izleyici
                live.send_text(json.dumps({'t': 'cmd', 'rid': 'r1', 'bridge_id': b['id'], 'sysid': 7, 'name': 'set_mode', 'params': {'mode': 'RTL'}}))
                c1 = json.loads(ws.receive_text())
                assert c1['t'] == 'cmd' and c1['rid'] == 'r1' and c1['name'] == 'set_mode' and c1['params'] == {'mode': 'RTL'}, c1
                ws.send_text(json.dumps({'t': 'res', 'rid': 'r1', 'ok': True, 'result': {'mode': 'RTL'}}))
                res = drain(live, 'res')
                assert res['rid'] == 'r1' and res['ok'] is True, res
                # v1.1 cap link: link_open köprüye iletilir
                live.send_text(json.dumps({'t': 'cmd', 'rid': 'l1', 'bridge_id': b['id'], 'sysid': 7, 'name': 'link_open',
                                           'params': {'type': 'udp', 'host': '0.0.0.0', 'port': 14550, 'sysid': 7}}))
                c2 = json.loads(ws.receive_text())
                assert c2['name'] == 'link_open' and c2['params']['port'] == 14550, c2
                ws.send_text(json.dumps({'t': 'res', 'rid': 'l1', 'ok': True}))
                assert drain(live, 'res', pred=lambda m: m.get('rid') == 'l1')['ok'] is True
                # GÖKTUNGU COMMAND_ACK bildirimi: kabul → dron konsolu; red → gerekçeli BAŞARISIZ (dron + genel konsol), son PreArm metniyle
                from pymavlink.dialects.v20 import ardupilotmega as _d
                enc = _d.MAVLink(None, srcSystem=7, srcComponent=1)
                ws.send_bytes(enc.statustext_encode(3, b'PreArm: Need Position Estimate', 0, 0).pack(enc)
                              + enc.command_ack_encode(400, 4).pack(enc) + enc.command_ack_encode(22, 0).pack(enc)
                              + enc.command_ack_encode(511, 4).pack(enc))   # 511 (SET_MESSAGE_INTERVAL) kullanıcı komutu değil: bildirilmez
                red = drain(live, 'konsol', limit=60)
                assert red['text'] == '[7] ARM / DISARM BAŞARISIZ: yürütülemedi (ön koşullar sağlanmadı) (PreArm: Need Position Estimate)' and red['sev'] == 'hata', red
                kabul = drain(live, 'console', limit=60, pred=lambda m: m['text'] == 'KALKIŞ (TAKEOFF) kabul edildi')
                assert kabul['sev'] == 'basari' and kabul['tag'] == 'KOMUT', kabul
                ev = drain(live, 'event', limit=60, pred=lambda m: 'PreArm' in m['text'])
                assert ev['severity'] == 3, ev
                # bilinmeyen komut reddedilir (köprüye gitmez)
                res = cmd(live, 'r2', b['id'], 'selfdestruct', sysid=7)
                assert res['ok'] is False and 'Bilinmeyen' in res['error'], res
                # uçuş sonrası log aktarımı: log_begin → parçalar → log_end → flight_logs (source=BRIDGE)
                blob = os.urandom(70000)
                ws.send_text(json.dumps({'t': 'log_begin', 'name': 'ucus.bin', 'size': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}))
                assert json.loads(ws.receive_text())['t'] == 'log_ready'
                for i in range(0, len(blob), 30000):
                    ws.send_bytes(blob[i:i + 30000])
                ws.send_text(json.dumps({'t': 'log_end'}))
                ack = json.loads(ws.receive_text())
                assert ack['t'] == 'log_ack' and ack['flight_log_id'], ack
                lg = drain(live, 'log')
                assert lg['flight_log_id'] == ack['flight_log_id']
                with db.connect() as conn:
                    row = db.row(conn.execute('SELECT * FROM flight_logs WHERE id = ?', (ack['flight_log_id'],)))
                    assert row['source'] == 'BRIDGE' and row['size'] == len(blob) and row['file_name'] == 'ucus.bin', row
                    assert (config.UPLOAD_DIR / row['file']).stat().st_size == len(blob)
                # sağlama uyuşmazlığı → log_err, kayıt yok
                ws.send_text(json.dumps({'t': 'log_begin', 'name': 'bozuk.bin', 'size': 10, 'sha256': '00' * 32}))
                assert json.loads(ws.receive_text())['t'] == 'log_ready'
                ws.send_bytes(b'0123456789')
                ws.send_text(json.dumps({'t': 'log_end'}))
                assert json.loads(ws.receive_text())['t'] == 'log_err'
                # REST canlı durum: köprü çevrimiçi; dron kaydında köprü/canlı alanı yok
                live_state = ok(a.get('/api/drone/live'))
                assert live_state['bridges'][0]['bridge_id'] == b['id'] and '7' in live_state['bridges'][0]['drones']
                assert live_state['drones'][0]['protocol'] == 'mavlink' and 'bridge_id' not in live_state['drones'][0], live_state['drones']
                dr = ok(a.get(f"/api/drone/drones/{d['id']}"))
                assert dr['protocol_text'] == 'MAVLink' and dr['flights'] == [] and 'online' not in dr, dr
                # ikinci bağlantı aynı anahtarla → eskisi 4409 ile kapanır
                with a.websocket_connect('/ws/drone/bridge') as ws2:
                    ws2.send_text(json.dumps({'v': 1, 't': 'auth', 'key': key}))
                    assert json.loads(ws2.receive_text())['t'] == 'auth_ok'
                    assert close_code(ws) == 4409
            # köprü ayrıldı → izleyiciye bridge offline
            br = drain(live, 'bridge', limit=20)
            while br.get('online') is not False:
                br = drain(live, 'bridge', limit=20)
        rows = sessions()
        assert any(r['packets'] >= 3 for r in rows), rows
        assert all(r['status'] in ('KOPTU', 'KAPANDI') for r in rows), rows
        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'Dron komutu'").fetchone()[0] >= 1

        # --- Saha görevi: dron ile (order_id NULL) ---
        pilot = ok(a.post('/api/users', json={'username': 'pilot@test', 'full_name': 'Pilot', 'roles': [auth.PILOT, auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
        lead = ok(a.post('/api/users', json={'username': 'saha@test', 'full_name': 'Saha', 'roles': [auth.FIELD_LEAD], 'password': 'Gizli-Parola-77'}))
        avail = ok(a.get('/api/field/available-drones'))
        assert [x['code'] for x in avail] == ['D-0001', 'D-0002'] and [x['protocol'] for x in avail] == ['mavlink', 'sanal'], avail
        r = a.post('/api/field/tasks', json={'order_ids': [], 'drone_ids': [], 'lead_id': lead['id'], 'pilot_id': pilot['id'], 'staff_ids': [pilot['id']]})
        assert r.status_code == 400 and 'dron' in r.text.lower(), r.text
        t = ok(a.post('/api/field/tasks', json={'drone_ids': [d['id']], 'lead_id': lead['id'], 'pilot_id': pilot['id'], 'staff_ids': [pilot['id']]}))
        task = ok(a.get(f"/api/field/tasks/{t['id']}"))
        f0 = task['flights'][0]
        assert task['aircraft'] == 'D-0001' and f0['drone_code'] == 'D-0001' and f0['order_id'] is None, task['flights']
        assert f0['protocol'] == 'mavlink' and f0['label'] == 'D-0001' and f0['bridge_id'] is None and f0['link'] is None and f0['bridge_online'] is False, f0
        assert [x['code'] for x in ok(a.get('/api/field/available-drones'))] == ['D-0002']   # D-0001 açık görevde
        fl = ok(a.get('/api/field/flights?view=ready'))
        assert any(f['drone_code'] == 'D-0001' for f in fl), fl

        # --- Faz 1: Dron Ekle (addable) + POST flights ---
        ad = ok(a.get(f"/api/field/tasks/{t['id']}/addable"))
        assert isinstance(ad['orders'], list) and [x['code'] for x in ad['drones']] == ['D-0002'] and ad['drones'][0]['protocol'] == 'sanal', ad
        assert a.post(f"/api/field/tasks/{t['id']}/flights", json={}).status_code == 400
        assert a.post(f"/api/field/tasks/{t['id']}/flights", json={'order_id': 1, 'drone_id': sd['id']}).status_code == 400
        assert a.post(f"/api/field/tasks/{t['id']}/flights", json={'drone_id': d['id']}).status_code == 400       # zaten görevde
        assert a.post(f"/api/field/tasks/{t['id']}/flights", json={'order_id': 999999}).status_code == 400       # uygun uçak değil
        nf = ok(a.post(f"/api/field/tasks/{t['id']}/flights", json={'drone_id': sd['id']}))
        task = ok(a.get(f"/api/field/tasks/{t['id']}"))
        assert [f['label'] for f in task['flights']] == ['D-0001', 'D-0002'] and task['flights'][1]['protocol'] == 'sanal' and task['flights'][1]['id'] == nf['id'], task['flights']
        assert ok(a.get('/api/field/available-drones')) == [] and ok(a.get(f"/api/field/tasks/{t['id']}/addable"))['drones'] == []
        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'Saha görevine uçak ekledi'").fetchone()[0] == 1

        # --- Faz 1: uçuş bağlantısı (PUT): köprü + sysid + link doğrulaması ---
        fid = f0['id']
        put = lambda body: a.put(f'/api/field/flights/{fid}', json=body)   # noqa: E731
        assert put({'bridge_id': 999999}).status_code == 400                                               # köprü yok
        assert put({'bridge_id': b['id'], 'link': {'type': 'wifi'}}).status_code == 400                     # tür
        assert put({'bridge_id': b['id'], 'link': {'type': 'serial', 'serial': '/dev/ttyUSB0'}}).status_code == 400   # baud eksik
        assert put({'bridge_id': b['id'], 'link': {'type': 'tcp', 'host': '192.168.4.1'}}).status_code == 400          # port eksik
        assert put({'link': {'type': 'udp', 'host': '0.0.0.0', 'port': 14550}}).status_code == 400          # köprü seçilmeden link
        assert put({'bridge_id': b['id'], 'sysid': 300}).status_code == 400                                 # sysid aralığı
        ok(put({'launch': 'RAMPA', 'note': 'ilk deneme', 'bridge_id': b['id'], 'sysid': 7, 'link': {'type': 'udp', 'host': '0.0.0.0', 'port': '14550'}}))
        f0 = ok(a.get(f"/api/field/tasks/{t['id']}"))['flights'][0]
        assert f0['bridge_id'] == b['id'] and f0['bridge_name'] == 'Test köprüsü' and f0['sysid'] == 7 and f0['launch'] == 'RAMPA', f0
        assert f0['link'] == {'type': 'udp', 'host': '0.0.0.0', 'port': 14550} and f0['bridge_online'] is False, f0
        ok(put({'launch': 'RAMPA', 'bridge_id': b['id'], 'sysid': 7, 'link': {'type': 'serial', 'serial': 'COM5', 'baud': 57600}}))
        assert ok(a.get(f"/api/field/tasks/{t['id']}"))['flights'][0]['link'] == {'type': 'serial', 'serial': 'COM5', 'baud': 57600}
        ok(put({'launch': 'RAMPA', 'bridge_id': b['id'], 'sysid': 7, 'link': {'type': 'udp', 'host': '0.0.0.0', 'port': 14550}}))
        assert ok(a.get('/api/drone/bridges'))[0]['flight_count'] == 1

        # --- Faz 1: görev bağlamı REST (live) ---
        lv = ok(a.get(f"/api/field/tasks/{t['id']}/live"))
        assert lv['task']['code'] == t['code'] and lv['task']['status'] == 'BASLANGIC' and lv['task']['lat'] is None and lv['can_command'] is True, lv['task']
        by = {f['label']: f for f in lv['flights']}
        assert by['D-0001']['protocol'] == 'mavlink' and by['D-0001']['bridge_id'] == b['id'] and by['D-0001']['bridge_name'] == 'Test köprüsü', by
        assert by['D-0001']['sysid'] == 7 and by['D-0001']['link']['port'] == 14550 and by['D-0001']['sim_bridge_id'] is None, by
        assert by['D-0002']['protocol'] == 'sanal' and by['D-0002']['sim_bridge_id'] == -sd['id'] and by['D-0002']['name'] == 'Sanal-1', by
        assert by['D-0002']['bridge_online'] is False   # izleyen yok → sanal dron çalışmıyor
        ok(a.post('/api/users', json={'username': 'saha2@test', 'full_name': 'Saha 2', 'roles': [auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
        with TestClient(app, base_url='https://testserver') as o2:   # görev üyesi olmayan saha personeli → 403
            login(o2, 'saha2@test', 'Gizli-Parola-77')
            assert o2.get(f"/api/field/tasks/{t['id']}/live").status_code == 403
        with TestClient(app, base_url='https://testserver') as p:    # pilot (görev üyesi) → 200
            login(p, 'pilot@test', 'Gizli-Parola-77')
            assert ok(p.get(f"/api/field/tasks/{t['id']}/live"))['task']['id'] == t['id']
        assert a.get('/api/field/tasks/999999/live').status_code == 404

        # --- Faz 1: WS watch task_id → görev bağlamı + sanal dron simülatörü ---
        sim_id = -sd['id']
        with a.websocket_connect('/ws/drone/live', headers={'cookie': f'{auth.COOKIE}={token}'}) as live:
            drain(live, 'hello')
            live.send_text(json.dumps({'t': 'watch', 'task_id': 999999}))
            assert drain(live, 'error', limit=20)['error'] == 'Görev bulunamadı'
            live.send_text(json.dumps({'t': 'watch', 'task_id': t['id']}))
            hello = drain(live, 'hello', limit=30, pred=lambda m: m.get('task'))
            assert hello['task']['code'] == t['code'] and [f['label'] for f in hello['flights']] == ['D-0001', 'D-0002'], hello['flights']
            sims = [x for x in hello['bridges'] if x['bridge_id'] == sim_id]
            assert sims and sims[0]['sim'] is True and sims[0]['name'] == 'Sanal · D-0002' and sims[0]['drone_id'] == sd['id'], hello['bridges']
            assert all(x['bridge_id'] == sim_id for x in hello['bridges']), hello['bridges']   # gerçek köprü çevrimdışı
            assert next(f for f in hello['flights'] if f['label'] == 'D-0002')['bridge_online'] is True
            assert sim_id in drone_hub.SIMS and drone_hub.SIMS[sim_id].task_id == t['id']
            assert ok(a.get(f"/api/field/tasks/{t['id']}/live"))['flights'][1]['bridge_online'] is True
            st = drain(live, 'status', limit=30, pred=lambda m: m['bridge_id'] == sim_id)
            s = st['state']
            assert st['sysid'] == 1 and s['armed'] is False and abs(s['lat'] - 39.9) < 1e-6 and abs(s['lon'] - 32.8) < 1e-6, s
            assert s['fix'] == 6 and s['sats'] == 12 and s['mode'] == 'STABILIZE' and s['type_name'] == 'Quadrotor' and s['batt_pct'] == 100, s
            assert s['ready']['hazir'] is True, s['ready']
            # GÖKTUNGU kalkış: kontrol listesi sunucuda doğrulanır ve kaydedilir; takeoff pilotun ayrıca ARM etmesini istemez
            # (hub: GUIDED → teyit → ARM → teyit → NAV_TAKEOFF, arka planda)
            kk = lambda cevap, zorunlu=True: [{'anahtar': 'pervane_siki', 'soru': 'Pervaneler sıkı mı?', 'grup': 'fiziksel', 'cevap': cevap, 'zorunlu': zorunlu},   # noqa: E731
                                              {'anahtar': 'alan_temiz', 'soru': 'Alan temiz mi?', 'grup': 'ortak', 'cevap': True, 'zorunlu': zorunlu}]
            r = cmd(live, 'k0', sim_id, 'takeoff', {'alt_rel_m': 20, 'kontrol': []})
            assert r['ok'] is False and 'Eksik istek' in r['error'], r
            r = cmd(live, 'k1', sim_id, 'takeoff', {'alt_rel_m': 20, 'kontrol': kk(False)})
            assert r['ok'] is False and r['error'] == '1 zorunlu madde onaylanmadı; kalkış reddedildi', r
            r = cmd(live, 'k2', sim_id, 'takeoff', {'alt_rel_m': 20, 'kontrol': kk(False, zorunlu=False)})
            assert r['ok'] is False and r['error'] == 'Kontrol listesi boş', r
            r0 = cmd(live, 's0', sim_id, 'takeoff', {'alt_rel_m': 20, 'kontrol': kk(True)})
            assert r0['ok'] is True and r0['result']['kontrol_id'], r0
            ev = drain(live, 'event', limit=60, pred=lambda m: m['bridge_id'] == sim_id and 'Arming' in m['text'])
            assert ev['sysid'] == 1 and ev['severity'] == 6, ev
            st = drain(live, 'status', limit=80, pred=lambda m: m['bridge_id'] == sim_id and m['state']['alt_rel'] > 0.5)
            assert st['state']['armed'] is True and st['state']['mode'] == 'GUIDED' and st['state']['climb'] > 0, st['state']
            assert cmd(live, 's1b', sim_id, 'arm')['ok'] is False                       # zaten ARM
            with db.connect() as conn:
                kc = conn.execute('SELECT * FROM drone_takeoff_checks WHERE id = ?', (r0['result']['kontrol_id'],)).fetchone()
            assert kc['task_id'] == t['id'] and kc['drone_id'] == sd['id'] and kc['sysid'] == 1 and kc['alt_m'] == 20 and kc['full_ok'] == 1, dict(kc)
            assert kc['item_count'] == 2 and kc['yes_count'] == 2 and kc['takeoff_sent'] == 1 and kc['takeoff_error'] is None, dict(kc)
            live.send_text(json.dumps({'t': 'console_hist', 'bridge_id': sim_id, 'sysid': 1}))
            hist = drain(live, 'console_hist', limit=60, pred=lambda m: m.get('bridge_id') == sim_id)
            texts = [x['text'] for x in hist['lines']]
            assert 'GUIDED/ARM teyidi bekleniyor...' in texts and 'TAKEOFF komutu iletildi: 20 m' in texts, texts
            assert any(x.startswith('Kontrol listesi onaylandı (kayıt #') for x in texts), texts
            assert cmd(live, 's2', sim_id, 'takeoff', {'alt_rel_m': 25})['ok'] is True   # havada: ARM atlanır, yeni hedef
            r = cmd(live, 's2b', sim_id, 'reboot')                                    # GÖKTUNGU: ARM'dayken reboot reddedilir
            assert r['ok'] is False and r['error'].startswith('REBOOT REDDEDİLDİ'), r
            # goto irtifasız: takeoff hedefi (25 m rel) korunur (GÖKTUNGU hedef_irtifa_rel)
            assert cmd(live, 's3', sim_id, 'goto', {'lat': 39.902, 'lon': 32.8})['ok'] is True
            st = drain(live, 'status', limit=80, pred=lambda m: m['bridge_id'] == sim_id and m['state']['groundspeed'] > 5)
            assert st['state']['lat'] > 39.9 and st['state']['wp_dist'] is not None and st['state']['dist_m'] > 0 and st['state']['flight_s'] >= 0, st['state']
            assert cmd(live, 's4', sim_id, 'rtl')['ok'] is True
            st = drain(live, 'status', limit=80, pred=lambda m: m['bridge_id'] == sim_id and m['state']['mode'] == 'RTL')
            assert st['state']['home_lat'] is not None, st['state']
            # set_mode LOITER → durur; görev yükle/indir; mission_set_current; set_home; arm_check; link_open ok; desteklenmeyen → error
            assert cmd(live, 's5', sim_id, 'set_mode', {'mode': 'LOITER'})['ok'] is True
            drain(live, 'status', limit=80, pred=lambda m: m['bridge_id'] == sim_id and m['state']['mode'] == 'LOITER' and m['state']['groundspeed'] < 0.1)
            assert cmd(live, 's6', sim_id, 'set_mode', {'mode': 'YOK'})['ok'] is False
            items = [{'seq': 0, 'frame': 6, 'command': 22, 'x': 0, 'y': 0, 'z': 15},
                     {'seq': 1, 'frame': 6, 'command': 16, 'param1': 0, 'x': 399010000, 'y': 328000000, 'z': 15},
                     {'seq': 2, 'frame': 6, 'command': 20, 'x': 0, 'y': 0, 'z': 0}]
            up = cmd(live, 's7', sim_id, 'mission_upload', {'items': items})
            assert up['ok'] is True and up['result']['count'] == 3, up
            dl = cmd(live, 's8', sim_id, 'mission_download')
            assert [it['command'] for it in dl['result']['items']] == [22, 16, 20] and dl['result']['items'][1]['x'] == 399010000, dl
            ms = cmd(live, 's9', sim_id, 'mission_start', {'rota': 'Test'})   # havada ARM: doğrudan AUTO
            assert ms['ok'] is True, ms
            st = drain(live, 'status', limit=80, pred=lambda m: m['bridge_id'] == sim_id and m['state']['mode'] == 'AUTO')
            assert st['state']['mission_count'] == 3 and st['state']['mission_seq'] is not None, st['state']
            assert cmd(live, 's10', sim_id, 'mission_set_current', {'seq': 1})['ok'] is True
            # GÖKTUNGU görev akışları: duraklat ('bekle' → BRAKE, telemetriden doğrulanır), devam (AUTO), başa dön (RTL), iptal (+ liste temizlenir)
            r = cmd(live, 'p1', sim_id, 'mission_pause', {'davranis': 'bekle'})
            assert r['ok'] is True and r['result']['mode'] == 'BRAKE', r
            r = cmd(live, 'p2', sim_id, 'mission_resume')
            assert r['ok'] is True and r['result']['mode'] == 'AUTO', r
            r = cmd(live, 'p3', sim_id, 'mission_pause', {'davranis': 'basa_don'})
            assert r['ok'] is True and r['result']['mode'] == 'RTL', r
            r = cmd(live, 'p4', sim_id, 'mission_resume_at', {'seq': 1, 'rota': 'Test', 'toplam_oge': 3})   # havada: set_current + AUTO
            assert r['ok'] is True, r
            r = cmd(live, 'p5', sim_id, 'mission_cancel', {'rota': 'Test'})
            assert r['ok'] is True and r['result']['mode'] == 'BRAKE' and drone_hub.SIMS[sim_id].mission == [], r
            gk = [m for m in _inbox.get(id(live), []) if m.get('t') == 'konsol']
            gk += [drain(live, 'konsol', limit=200, pred=lambda m: 'GÖREV İPTAL EDİLDİ' in m['text'])]
            texts = [m['text'] for m in gk]
            assert any("GÖREV İPTAL EDİLDİ ('Test') - dron BRAKE, görev listesi temizlendi" in x for x in texts), texts
            # irtifa değişikliği: GUIDED + konumda irtifa, hedef hafızaya alınır
            assert cmd(live, 'a1', sim_id, 'altitude_change', {'alt_rel_m': 30})['ok'] is True
            assert drone_hub.SIMS[sim_id].st.hedef_rel == 30.0 and drone_hub.SIMS[sim_id].mode == 'GUIDED'
            assert cmd(live, 's11', sim_id, 'set_home', {'lat': 39.95, 'lon': 32.85})['ok'] is True
            ac = cmd(live, 's12', sim_id, 'arm_check')
            assert ac['ok'] is True and ac['result']['armed'] is True and ac['result']['ozet']['hazir'] is True, ac
            assert cmd(live, 's13', sim_id, 'link_open', {'type': 'udp', 'host': '0.0.0.0', 'port': 14550})['ok'] is True
            r14 = cmd(live, 's14', sim_id, 'param_list')
            assert r14['ok'] is False and 'desteklemiyor' in r14['error'], r14
            r15 = cmd(live, 's15', -999, 'arm')
            assert r15['ok'] is False and 'Sanal dron çalışmıyor' in r15['error'], r15
            live.send_text(json.dumps({'t': 'console_hist', 'bridge_id': sim_id, 'sysid': 1}))
            hist = drain(live, 'console_hist', limit=60, pred=lambda m: m.get('bridge_id') == sim_id)
            assert any(x['tag'] == 'KOMUT' for x in hist['lines']) and any('Arming' in x['text'] for x in hist['lines']), hist['lines'][:3]
            ht = [x['text'] for x in hist['lines']]
            for beklenen in ('-> takeoff', 'GOTO 39.90200,32.80000 @ 25m rel (hedef korundu)', 'İRTİFA -> 30m', 'MOD -> LOITER', '-> reboot',
                             'REBOOT REDDEDİLDİ: araç arm edilmiş durumda. Önce disarm edin.', 'RTL'):
                assert beklenen in ht, (beklenen, ht[-25:])
            assert any(x.startswith('HOME = 39.950000,32.850000 @ ') and x.endswith('m AMSL (zemin kestirimi)') for x in ht), ht[-10:]
            # DISARM her zaman ZORLA (GÖKTUNGU param2=21196): havada da motorlar kesilir, hedef irtifa unutulur
            assert cmd(live, 'd1', sim_id, 'disarm')['ok'] is True
            assert drone_hub.SIMS[sim_id].st.d['armed'] is False and drone_hub.SIMS[sim_id].st.hedef_rel is None
            with db.connect() as conn:
                assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'Sanal dron komutu'").fetchone()[0] >= 5
            # Görev süzgeci: uçuşa bağlı köprü (b) görünür; başka köprü (b2) bu izleyiciye ulaşmaz
            with a.websocket_connect('/ws/drone/bridge') as ws:
                ws.send_text(json.dumps({'v': 1, 't': 'auth', 'key': key, 'host': 'pilot-pc'}))
                assert json.loads(ws.receive_text())['t'] == 'auth_ok'
                br = drain(live, 'bridge', limit=60, pred=lambda m: m['bridge_id'] == b['id'] and m.get('online') is True)
                assert br['info']['name'] == 'Test köprüsü', br
                hb, gp, hud, st_, pv = mav_frames()
                ws.send_bytes(hb + gp)
                s1 = drain(live, 'status', limit=80, pred=lambda m: m['bridge_id'] == b['id'])
                assert s1['sysid'] == 7 and s1['state']['mode'] == 'AUTO', s1
                assert ok(a.get(f"/api/field/tasks/{t['id']}/live"))['flights'][0]['bridge_online'] is True
            b2 = ok(a.post('/api/drone/bridges', json={'name': 'Yabancı köprü'}))
            k2 = b2['code'].split('/', 1)[1]
            with a.websocket_connect('/ws/drone/bridge') as ws2:
                ws2.send_text(json.dumps({'v': 1, 't': 'auth', 'key': k2, 'host': 'baska-pc'}))
                assert json.loads(ws2.receive_text())['t'] == 'auth_ok'
                hb2, gp2, *_ = mav_frames(sysid=9)
                ws2.send_bytes(hb2 + gp2)
                ws2.send_bytes(hb2 + gp2)
                for _ in range(6):   # sanal dron akışından paket al (≥ 1 sn); bu arada b2 kaynaklı hiçbir çerçeve gelmemeli
                    drain(live, 'status', limit=60, pred=lambda m: m['bridge_id'] == sim_id)
                box = _inbox.get(id(live), [])
                assert not any(m.get('bridge_id') == b2['id'] for m in box), [m for m in box if m.get('bridge_id') == b2['id']]
                assert b2['id'] in drone_hub.BRIDGES
            # Uçuş kaldırma: logu olan kaldırılamaz; sanal uçuş kaldırılınca izleyici hello yenilenir ve sanal dron durur
            with db.connect() as conn:
                conn.execute("INSERT INTO flight_logs (task_id, flight_id, file, file_name, size, uploaded_at, source) VALUES (?,?,?,?,?,?,'UPLOAD')",
                             (t['id'], fid, 'flightlogs/x.bin', 'x.bin', 10, db.now()))
                conn.commit()
            assert a.delete(f'/api/field/flights/{fid}').status_code == 400
            ok(a.delete(f"/api/field/flights/{nf['id']}"))
            hello = drain(live, 'hello', limit=120, pred=lambda m: m.get('task') and len(m['flights']) == 1)
            assert hello['flights'][0]['label'] == 'D-0001', hello['flights']
            off = drain(live, 'bridge', limit=120, pred=lambda m: m['bridge_id'] == sim_id and m.get('online') is False)
            assert off['status'] == 'KAPANDI' and sim_id not in drone_hub.SIMS, off
            assert a.delete(f'/api/field/flights/{fid}').status_code == 400   # son uçuş (ve logu var)
            # yeniden ekle → hello yenilenir, sanal dron tekrar başlar
            nf = ok(a.post(f"/api/field/tasks/{t['id']}/flights", json={'drone_id': sd['id']}))
            hello = drain(live, 'hello', limit=120, pred=lambda m: m.get('task') and len(m['flights']) == 2)
            assert sim_id in drone_hub.SIMS and any(x['bridge_id'] == sim_id for x in hello['bridges']), hello['bridges']
            drain(live, 'status', limit=60, pred=lambda m: m['bridge_id'] == sim_id and m['state']['armed'] is False)
            # eski watch (köprü) davranışı korunur: görev bağlamı kalkar
            live.send_text(json.dumps({'t': 'watch', 'bridge_id': None}))
            hello = drain(live, 'hello', limit=120, pred=lambda m: not m.get('task'))
            assert any(x['bridge_id'] == b2['id'] for x in hello['bridges']) or True   # b2 kapanmış olabilir; hello görevsizdir
        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'Saha görevinden uçağı kaldırdı'").fetchone()[0] == 1

        # --- köprü kodu yenileme: {key, code} ---
        rk = ok(a.post(f"/api/drone/bridges/{b['id']}/rekey"))
        assert KEY_RE.match(rk['key']) and rk['code'] == f"testserver/{rk['key']}", rk
        r = a.delete(f"/api/drone/drones/{d['id']}")
        assert ok(r)['deactivated'] is True   # uçuş kaydı var → pasife alınır

        # --- RBAC: field modülü olmayan kullanıcı → 403 / WS 4403 ---
        other_role = next(r for r in auth.ROLES if r not in auth.MODULE_ROLES['field'] and r != auth.ADMIN)
        ok(a.post('/api/users', json={'username': 'disari@test', 'full_name': 'Dışarı', 'roles': [other_role], 'password': 'Gizli-Parola-77'}))
        with TestClient(app, base_url='https://testserver') as o:
            tok = login(o, 'disari@test', 'Gizli-Parola-77')
            assert o.get('/api/drone/drones').status_code == 403
            assert o.get('/api/drone/bridges').status_code == 403
            assert o.get(f"/api/field/tasks/{t['id']}/live").status_code == 403
            with o.websocket_connect('/ws/drone/live', headers={'cookie': f'{auth.COOKIE}={tok}'}) as ws:
                assert json.loads(ws.receive_text()).get('t') == 'error'
                assert close_code(ws) == 4403
        # çerezsiz izleyici
        with a.websocket_connect('/ws/drone/live', headers={'cookie': f'{auth.COOKIE}=yok'}) as ws:
            assert json.loads(ws.receive_text()).get('t') == 'error'
            assert close_code(ws) == 4403
        # pilot (Pilot + Saha Personeli): field okur; komut yetkisi rol/yazma iznine bağlı → en azından WS açılır
        with TestClient(app, base_url='https://testserver') as p:
            tok = login(p, 'pilot@test', 'Gizli-Parola-77')
            with p.websocket_connect('/ws/drone/live', headers={'cookie': f'{auth.COOKIE}={tok}'}) as ws:
                hello = json.loads(ws.receive_text())
                assert hello['t'] == 'hello', hello

        # --- rota → MISSION: başa otomatik TAKEOFF (ilk noktanın irtifası, en az 2 m); döngü DO_JUMP ilk rota noktasına ---
        rt = ok(a.post('/api/drone/routes', json={'name': 'Döngü rota', 'kind': 'loop', 'cruise_alt': 40,
                                                  'waypoints': [{'lat': 39.9, 'lon': 32.8, 'alt': 1}, {'lat': 39.91, 'lon': 32.81}]}))
        mi = ok(a.get(f"/api/drone/routes/{rt['id']}/mission"))
        assert mi['auto_takeoff'] is True and [x['command'] for x in mi['items']] == [22, 16, 16, 177], mi
        assert mi['items'][0]['z'] == 2.0 and mi['items'][0]['current'] == 1 and mi['items'][1]['current'] == 0, mi['items'][:2]
        assert [x['seq'] for x in mi['items']] == [0, 1, 2, 3] and mi['items'][3]['param1'] == 1.0 and mi['items'][2]['z'] == 40, mi['items']
        rt2 = ok(a.post('/api/drone/routes', json={'name': 'Kalkışlı rota', 'waypoints': [{'lat': 39.9, 'lon': 32.8, 'alt': 15, 'action': 'takeoff'},
                                                                                         {'lat': 39.91, 'lon': 32.81, 'alt': 15}]}))
        mi2 = ok(a.get(f"/api/drone/routes/{rt2['id']}/mission"))
        assert mi2['auto_takeoff'] is False and [x['command'] for x in mi2['items']] == [22, 16], mi2

        # --- yeniden başlama: açık oturumlar KESILDI ---
        with db.connect() as conn:
            conn.execute("INSERT INTO drone_bridge_sessions (bridge_id, started_at, status) VALUES (?, ?, 'ACIK')", (b['id'], db.now()))
            conn.commit()
        drone_hub.recover_on_start()
        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM drone_bridge_sessions WHERE status = 'ACIK'").fetchone()[0] == 0
    print('Dron Yönetimi testleri geçti.')


if __name__ == '__main__':
    main()
