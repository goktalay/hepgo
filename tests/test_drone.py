"""Dron Yönetimi (Faz 0): köprü WebSocket'i (kimlik, eşleştirme, MAVLink → canlı durum, komut RPC, log aktarımı), REST ve RBAC.
Çalıştırma: .venv/bin/python -m tests.test_drone
"""
import faulthandler
import hashlib
import json
import os
import tempfile
import time

faulthandler.dump_traceback_later(120, exit=True)   # WebSocket beklemesi takılırsa yığın izini bas ve çık

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app import auth, config, db, drone_hub, flight_analysis  # noqa: E402
from app.main import app  # noqa: E402

flight_analysis.start = lambda lid: None   # testte gerçek .bin analizi başlamasın


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
    return hb, gp, hud, st


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
    raise AssertionError(f'{want} mesajı gelmedi; gelenler: {[x.get("t") for x in box]}')


def main():
    with TestClient(app, base_url='https://testserver') as a:
        login(a, 'admin@test', 'admin-sifre-1')
        # --- şema: field_flights.drone_id, flight_logs.source, drone_* tabloları (idempotent init) ---
        db.init()
        with db.connect() as conn:
            cols = {r[1] for r in conn.execute('PRAGMA table_info(field_flights)')}
            assert {'order_id', 'drone_id'} <= cols, cols
            assert 'source' in {r[1] for r in conn.execute('PRAGMA table_info(flight_logs)')}
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'drone_%'")}
            assert {'drone_bridges', 'drone_drones', 'drone_bridge_sessions', 'drone_route_centers', 'drone_routes', 'drone_waypoints'} <= tables, tables
            fk = conn.execute('PRAGMA foreign_key_check').fetchall()
            assert not fk, fk

        # --- REST: köprü + dron ---
        b = ok(a.post('/api/drone/bridges', json={'name': 'Test köprüsü', 'platform': 'linux'}))
        d = ok(a.post('/api/drone/drones', json={'name': 'Göktungu-1', 'sysid': 7, 'bridge_id': b['id']}))
        assert d['code'] == 'D-0001', d

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

        # --- eşleştirme kodu → auth_ok + kalıcı anahtar (tek kullanımlık) ---
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
            assert hello['t'] == 'hello' and hello['me']['can_command'] is True, hello
            with a.websocket_connect('/ws/drone/bridge') as ws:
                ws.send_text(json.dumps({'v': 1, 't': 'auth', 'key': key, 'host': 'pilot-pc', 'platform': 'linux', 'bridge_ver': '0.1'}))
                m = json.loads(ws.receive_text())
                assert m['t'] == 'auth_ok' and 'key' not in m, m
                br = drain(live, 'bridge')
                assert br['online'] is True and br['bridge_id'] == b['id']
                hb, gp, hud, st = mav_frames()
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
                live.send_text(json.dumps({'t': 'cmd', 'rid': 'ac', 'bridge_id': b['id'], 'sysid': 7, 'name': 'arm_check'}))
                ac = drain(live, 'res', pred=lambda m: m.get('rid') == 'ac')
                assert ac['ok'] is True and ac['result']['bulundu'] is True and ac['result']['armed'] is True, ac
                assert any(x['grup'] == 'konum' for x in ac['result']['maddeler']) and ac['result']['mesajlar'][0]['sev'] == 4, ac['result']
                assert s1['state']['ready'] and 'hazir' in s1['state']['ready'], s1['state'].get('ready')
                # ping/pong
                ws.send_text(json.dumps({'t': 'ping'}))
                assert json.loads(ws.receive_text())['t'] == 'pong'
                # komut: izleyici → sunucu → köprü → res → izleyici
                live.send_text(json.dumps({'t': 'cmd', 'rid': 'r1', 'bridge_id': b['id'], 'sysid': 7, 'name': 'set_mode', 'params': {'mode': 'RTL'}}))
                cmd = json.loads(ws.receive_text())
                assert cmd['t'] == 'cmd' and cmd['rid'] == 'r1' and cmd['name'] == 'set_mode' and cmd['params'] == {'mode': 'RTL'}, cmd
                ws.send_text(json.dumps({'t': 'res', 'rid': 'r1', 'ok': True, 'result': {'mode': 'RTL'}}))
                res = drain(live, 'res')
                assert res['rid'] == 'r1' and res['ok'] is True, res
                # bilinmeyen komut reddedilir (köprüye gitmez)
                live.send_text(json.dumps({'t': 'cmd', 'rid': 'r2', 'bridge_id': b['id'], 'sysid': 7, 'name': 'selfdestruct'}))
                res = drain(live, 'res')
                assert res['rid'] == 'r2' and res['ok'] is False and 'Bilinmeyen' in res['error'], res
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
                # REST canlı durum: köprü çevrimiçi, dron envanteriyle eşleşti
                live_state = ok(a.get('/api/drone/live'))
                assert live_state['bridges'][0]['bridge_id'] == b['id'] and '7' in live_state['bridges'][0]['drones']
                dr = ok(a.get(f"/api/drone/drones/{d['id']}"))
                assert dr['online'] is True and dr['live']['mode'] == 'AUTO', dr
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
        assert [x['code'] for x in ok(a.get('/api/field/available-drones'))] == ['D-0001']
        r = a.post('/api/field/tasks', json={'order_ids': [], 'drone_ids': [], 'lead_id': lead['id'], 'pilot_id': pilot['id'], 'staff_ids': [pilot['id']]})
        assert r.status_code == 400 and 'dron' in r.text.lower(), r.text
        t = ok(a.post('/api/field/tasks', json={'drone_ids': [d['id']], 'lead_id': lead['id'], 'pilot_id': pilot['id'], 'staff_ids': [pilot['id']]}))
        task = ok(a.get(f"/api/field/tasks/{t['id']}"))
        assert task['aircraft'] == 'D-0001' and task['flights'][0]['drone_code'] == 'D-0001' and task['flights'][0]['order_id'] is None, task['flights']
        assert ok(a.get('/api/field/available-drones')) == []   # açık görevde
        fl = ok(a.get('/api/field/flights?view=ready'))
        assert any(f['drone_code'] == 'D-0001' for f in fl), fl
        r = a.delete(f"/api/drone/drones/{d['id']}")
        assert ok(r)['deactivated'] is True   # uçuş kaydı var → pasife alınır

        # --- RBAC: field modülü olmayan kullanıcı → 403 / WS 4403 ---
        other_role = next(r for r in auth.ROLES if r not in auth.MODULE_ROLES['field'] and r != auth.ADMIN)
        ok(a.post('/api/users', json={'username': 'disari@test', 'full_name': 'Dışarı', 'roles': [other_role], 'password': 'Gizli-Parola-77'}))
        with TestClient(app, base_url='https://testserver') as o:
            tok = login(o, 'disari@test', 'Gizli-Parola-77')
            assert o.get('/api/drone/drones').status_code == 403
            assert o.get('/api/drone/bridges').status_code == 403
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
