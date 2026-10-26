"""Canlı Uçuş › Mission Planner aktarımı (app/drone_mprelay.py; protokol v1.4 raw_up / cap 'mp_relay') — uçtan uca:
sahte köprü WebSocket'i (caps mp_relay) + sahte Mission Planner UDP soketi.
  - yetki: görev üyesi olmayan → 403; komut yetkisi olmayan görev üyesi okur ama açamaz; sanal dron / köprüsüz / eski köprü reddi
  - aç → UDPCl adresi; HEARTBEAT her iki yön (MP → köprü ikili 0x01+ham, dron → MP); kilit yalnız GCS kalp atışıyla
  - IP kilidi: başka IP (127.0.0.2) reddedilir + denetim günlüğü; "IP kilidini sıfırla" sonrası yeni IP kilitlenir
  - isteğe bağlı eşleştirme (pair_sysid): yanlış sysid'li kalp atışı kilitlemez
  - MP komutları HEPGO konsoluna "Mission Planner: …" (ARM, mod), PARAM_SET → yankı PARAM_VALUE ile kalıcı kayıt (kaynak mp)
  - sysid ayıklama (aynı köprüde ikinci dron MP'ye gitmez), boyut/sihirli bayt denetimi
  - kiracı/port ayrımı: aralıktaki dolu port (başka süreç/kiracı) atlanır; başka görevin uçuşu ayrı aktarım
  - kapanma: Kapat (port serbest), hareketsizlik, görev bitince; köprü bilgisi mp_relays
Çalıştırma: .venv/bin/python -m tests.test_drone_mprelay
"""
import faulthandler
import json
import os
import socket
import tempfile
import time

faulthandler.dump_traceback_later(170, exit=True)

os.environ.setdefault('HEPGO_SITL', '0')
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0', LIVE_MP_UDP_BASE='14780', LIVE_MP_UDP_COUNT='10',
                  LIVE_MP_PUBLIC_HOST='mp.ornek.test')

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db, drone_hub, drone_mprelay, flight_analysis  # noqa: E402
from app.main import app  # noqa: E402

flight_analysis.start = lambda lid: None


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json() if r.text else None


def login(c, u, p):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def enc(sysid, comp=1):
    from pymavlink.dialects.v20 import ardupilotmega as d
    return d.MAVLink(None, srcSystem=sysid, srcComponent=comp)


def gcs_hb(sysid=255):
    e = enc(sysid, 190)
    return e.heartbeat_encode(6, 8, 0, 0, 0, 3).pack(e)   # MAV_TYPE_GCS, AUTOPILOT_INVALID


def drone_hb(sysid=7, armed=False):
    e = enc(sysid)
    return e.heartbeat_encode(2, 3, (128 if armed else 0) | 1, 5, 4, 3).pack(e)   # quadrotor, LOITER


def recv_udp(s, timeout=5.0):
    s.settimeout(timeout)
    data, _ = s.recvfrom(65535)
    return data


def recv_raw_up(ws, limit=50):
    """Sahte köprü: sunucudan gelen ilk ikili çerçeve (metin çerçeveleri atlanır)."""
    for _ in range(limit):
        m = ws.receive()
        if m.get('bytes') is not None:
            return m['bytes']
    raise AssertionError('raw_up gelmedi')


def drain_udp(s):
    s.settimeout(0.3)
    try:
        while True:
            s.recvfrom(65535)
    except socket.timeout:
        pass


def wait(pred, timeout=8.0, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def udp_sock(ip='127.0.0.1'):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((ip, 0))
    return s


def audit_count(action):
    with db.connect() as conn:
        return conn.execute('SELECT COUNT(*) FROM audit_logs WHERE action = ?', (action,)).fetchone()[0]


def main():
    drone_mprelay.MAINT_S = 0.3
    drone_mprelay.TASK_CHECK_S = 0.5
    with TestClient(app, base_url='https://testserver') as a:
        login(a, 'admin@test', 'admin-sifre-1')
        b = ok(a.post('/api/drone/bridges', json={'name': 'Jetson MX860', 'platform': 'linux'}))
        key = b['code'].split('/', 1)[1]
        b2 = ok(a.post('/api/drone/bridges', json={'name': 'Eski köprü', 'platform': 'windows'}))
        key2 = b2['code'].split('/', 1)[1]
        d = ok(a.post('/api/drone/drones', json={'name': 'MX860'}))
        d2 = ok(a.post('/api/drone/drones', json={'name': 'İkinci'}))
        sd = ok(a.post('/api/drone/drones', json={'name': 'Sanal', 'protocol': 'sanal'}))
        pilot = ok(a.post('/api/users', json={'username': 'pilot@test', 'full_name': 'Pilot', 'roles': [auth.PILOT, auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
        lead = ok(a.post('/api/users', json={'username': 'saha@test', 'full_name': 'Saha', 'roles': [auth.FIELD_LEAD], 'password': 'Gizli-Parola-77'}))
        staff = ok(a.post('/api/users', json={'username': 'personel@test', 'full_name': 'Personel', 'roles': [auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
        ok(a.post('/api/users', json={'username': 'yabanci@test', 'full_name': 'Yabancı', 'roles': [auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
        t = ok(a.post('/api/field/tasks', json={'drone_ids': [d['id'], sd['id']], 'lead_id': lead['id'], 'pilot_id': pilot['id'],
                                                'staff_ids': [pilot['id'], staff['id']]}))
        fl = {f['drone_id']: f for f in ok(a.get(f"/api/field/tasks/{t['id']}"))['flights']}
        fid, sfid = fl[d['id']]['id'], fl[sd['id']]['id']
        ok(a.put(f'/api/field/flights/{fid}', json={'bridge_id': b['id'], 'sysid': 7, 'link': {'type': 'serial', 'serial': '/dev/ttyACM0', 'baud': 115200}}))
        # ikinci görev (başka dron, eski köprü) — ayrı aktarım bağlamı
        t2 = ok(a.post('/api/field/tasks', json={'drone_ids': [d2['id']], 'lead_id': lead['id'], 'pilot_id': pilot['id'], 'staff_ids': [pilot['id']]}))
        fid2 = ok(a.get(f"/api/field/tasks/{t2['id']}"))['flights'][0]['id']
        ok(a.put(f'/api/field/flights/{fid2}', json={'bridge_id': b2['id'], 'sysid': 1}))

        # --- köprü çevrimdışı: durum okunur, açılamaz ---
        st = ok(a.get(f'/api/field/flights/{fid}/mp-relay'))
        assert st['active'] is False and st['available'] is True and st['bridge_online'] is False and st['host'] == 'mp.ornek.test', st
        assert st['port_range'] == [14780, 14789] and st['can_manage'] is True and st['min_versions'] == {'linux': '1.1.6', 'windows': '1.1.0'}, st
        assert a.post(f'/api/field/flights/{fid}/mp-relay').status_code == 409
        r = a.post(f'/api/field/flights/{sfid}/mp-relay')
        assert r.status_code == 400 and 'Sanal' in r.text, r.text

        # --- yetki: görev üyesi olmayan → 403; komut yetkisi olmayan üye okur, açamaz ---
        with TestClient(app, base_url='https://testserver') as y:
            login(y, 'yabanci@test', 'Gizli-Parola-77')
            assert y.get(f'/api/field/flights/{fid}/mp-relay').status_code == 403
            assert y.post(f'/api/field/flights/{fid}/mp-relay').status_code == 403
        with TestClient(app, base_url='https://testserver') as p:
            login(p, 'personel@test', 'Gizli-Parola-77')
            assert ok(p.get(f'/api/field/flights/{fid}/mp-relay'))['can_manage'] is False
            assert p.post(f'/api/field/flights/{fid}/mp-relay').status_code == 403
            assert p.delete(f'/api/field/flights/{fid}/mp-relay').status_code == 403
        assert a.get('/api/field/flights/999999/mp-relay').status_code == 404

        # --- eski köprü (caps'te mp_relay yok) → güncelleme iletisi ---
        with a.websocket_connect('/ws/drone/bridge') as old:
            old.send_text(json.dumps({'v': 1, 't': 'auth', 'key': key2, 'host': 'eski-pc', 'platform': 'windows', 'bridge_ver': '1.0.0', 'caps': ['link']}))
            assert json.loads(old.receive_text())['t'] == 'auth_ok'
            st2 = ok(a.get(f'/api/field/flights/{fid2}/mp-relay'))
            assert st2['bridge_online'] is True and st2['bridge_supported'] is False, st2
            r = a.post(f'/api/field/flights/{fid2}/mp-relay')
            assert r.status_code == 409 and 'Köprüyü güncelleyin (Linux ≥1.1.6 / Windows ≥1.1.0)' in r.json()['detail'], r.text

        # --- kiracı/port ayrımı: aralığın ilk portu başka süreçte (başka kiracı) dolu → sonraki port ---
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(('0.0.0.0', 14780))
        mp = udp_sock()
        with a.websocket_connect('/ws/drone/bridge') as ws:
            ws.send_text(json.dumps({'v': 1, 't': 'auth', 'key': key, 'host': 'mx860', 'platform': 'linux', 'bridge_ver': '1.1.6',
                                     'caps': ['link', 'param', 'mp_relay']}))
            assert json.loads(ws.receive_text())['t'] == 'auth_ok'
            ws.send_bytes(drone_hb(7))
            assert wait(lambda: 7 in drone_hub.BRIDGES[b['id']].drones)
            r = ok(a.post(f'/api/field/flights/{fid}/mp-relay', json={}))
            assert r['active'] is True and r['port'] == 14781 and r['address'] == 'mp.ornek.test:14781', r
            assert r['locked_ip'] is None and r['connected'] is False and r['opened_by'], r
            assert ok(a.post(f'/api/field/flights/{fid}/mp-relay'))['port'] == 14781   # idempotent
            assert drone_hub.BRIDGES[b['id']].info()['mp_relays'] == [fid]
            assert wait(lambda: audit_count('Mission Planner aktarımı açıldı') == 1)
            port = r['port']

            # kilit yalnız GCS kalp atışıyla: dron kalp atışı / çöp / büyük paket kilitlemez, köprüye gitmez
            mp.sendto(drone_hb(1), ('127.0.0.1', port))
            mp.sendto(b'\x00merhaba', ('127.0.0.1', port))
            mp.sendto(b'\xfd' + b'x' * 3000, ('127.0.0.1', port))
            assert wait(lambda: drone_mprelay.get(fid).dropped_invalid >= 3)
            assert drone_mprelay.get(fid).locked_ip is None

            # MP → köprü: GCS HEARTBEAT kilitler, raw_up = 0x01 + ham çerçeve
            hb = gcs_hb(255)
            mp.sendto(hb, ('127.0.0.1', port))
            up = recv_raw_up(ws)
            assert up == bytes([drone_mprelay.RAW_UP]) + hb, up[:8]
            # dron → MP: köprüden gelen çerçeve MP'ye aynen
            dhb = drone_hb(7)
            ws.send_bytes(dhb)
            assert recv_udp(mp) == dhb
            st = ok(a.get(f'/api/field/flights/{fid}/mp-relay'))
            assert st['locked_ip'] == '127.0.0.1' and st['connected'] is True and st['rx_packets'] == 1 and st['tx_packets'] >= 1, st
            assert st['peer'] == f'127.0.0.1:{mp.getsockname()[1]}' and st['dropped']['invalid'] >= 3, st
            assert wait(lambda: audit_count('Mission Planner aktarımı: MP bağlandı') == 1)

            # IP kilidi: 127.0.0.2'den gelen reddedilir (bir kez denetim kaydı)
            ev = udp_sock('127.0.0.2')
            for _ in range(3):
                ev.sendto(gcs_hb(255), ('127.0.0.1', port))
            assert wait(lambda: drone_mprelay.get(fid).dropped_ip == 3)
            assert wait(lambda: audit_count('Mission Planner aktarımı: kilit dışı IP reddedildi') == 1)
            # aynı IP yeni kaynak portu (MP yeniden bağlandı) kabul edilir
            mp_b = udp_sock()
            mp_b.sendto(gcs_hb(255), ('127.0.0.1', port))
            assert recv_raw_up(ws)[1:] == gcs_hb(255)
            ws.send_bytes(dhb)
            assert recv_udp(mp_b) == dhb

            # MP komutları → HEPGO konsolu; PARAM_SET → yankı PARAM_VALUE ile kalıcı kayıt (kaynak mp)
            e = enc(255, 190)
            arm = e.command_long_encode(7, 1, 400, 0, 1, 0, 0, 0, 0, 0, 0).pack(e)
            mode = e.command_long_encode(7, 1, 176, 0, 1, 6, 0, 0, 0, 0, 0).pack(e)   # RTL (kopter 6)
            pset = e.param_set_encode(7, 1, b'RTL_ALT', 2500.0, 9).pack(e)
            for x in (arm, arm, mode, pset):   # MP ACK gelene dek yineler: tek satır
                mp_b.sendto(x, ('127.0.0.1', port))
                assert recv_raw_up(ws)[1:] == x
            texts = lambda: [c['text'] for c in drone_hub.BRIDGES[b['id']].drones[7].console if c['tag'] == 'MP']   # noqa: E731
            assert wait(lambda: any('Mission Planner: ARM' in x for x in texts()) and any('MOD → RTL' in x for x in texts())), texts()
            assert sum(1 for x in texts() if 'Mission Planner: ARM' in x) == 1, texts()
            assert any('PARAM_SET RTL_ALT = 2500' in x for x in texts()), texts()
            pv = enc(7).param_value_encode(b'RTL_ALT', 2500.0, 9, 900, 12)
            ws.send_bytes(pv.pack(enc(7)))
            assert wait(lambda: any(p['name'] == 'RTL_ALT' for p in ok(a.get(f"/api/drone/drones/{d['id']}/sitl-params"))['items']))
            pr = next(p for p in ok(a.get(f"/api/drone/drones/{d['id']}/sitl-params"))['items'] if p['name'] == 'RTL_ALT')
            assert pr['value'] == 2500.0 and pr['source'] == 'mp', pr
            # niyetsiz PARAM_VALUE (araç kendi değiştirdi) gerçek dronda kaydedilmez
            ws.send_bytes(enc(7).param_value_encode(b'WPNAV_SPEED', 700.0, 9, 900, 13).pack(enc(7)))
            ws.send_bytes(enc(7).param_value_encode(b'WPNAV_SPEED', 800.0, 9, 900, 13).pack(enc(7)))
            time.sleep(0.5)
            assert not any(p['name'] == 'WPNAV_SPEED' for p in ok(a.get(f"/api/drone/drones/{d['id']}/sitl-params"))['items'])
            # HEPGO akışı sürerken MP komutu → çakışma uyarısı (genel konsol)
            drone_hub._FLOWS[(b['id'], 7)] = object()
            try:
                land = e.command_long_encode(7, 1, 21, 0, 0, 0, 0, 0, 0, 0, 0).pack(e)
                mp_b.sendto(land, ('127.0.0.1', port))
                recv_raw_up(ws)
                assert wait(lambda: any('İNİŞ' in x and 'çakışabilir' in x for x in texts())), texts()
            finally:
                drone_hub._FLOWS.pop((b['id'], 7), None)

            # sysid ayıklama: aynı köprüde ikinci dron (sysid 9) MP'ye gitmez, uçuşun dronu (7) gider
            ws.send_bytes(drone_hb(9))
            assert wait(lambda: 9 in drone_hub.BRIDGES[b['id']].drones)
            drain_udp(mp_b)   # önceki dron çerçeveleri (PARAM_VALUE, sysid 9'un ilk kalp atışı — henüz tanınmıyordu)
            ws.send_bytes(drone_hb(9) + drone_hb(7, armed=True))
            assert recv_udp(mp_b) == drone_hb(7, armed=True)

            # IP kilidini sıfırla → yeni IP (127.0.0.2) kilitlenebilir
            assert a.post(f'/api/field/flights/{fid2}/mp-relay/reset-ip').status_code == 404   # o uçuşta aktarım yok
            st = ok(a.post(f'/api/field/flights/{fid}/mp-relay/reset-ip'))
            assert st['locked_ip'] is None and st['peer'] is None, st
            ev.sendto(gcs_hb(255), ('127.0.0.1', port))
            assert recv_raw_up(ws)[1:] == gcs_hb(255)
            assert ok(a.get(f'/api/field/flights/{fid}/mp-relay'))['locked_ip'] == '127.0.0.2'
            assert wait(lambda: audit_count('Mission Planner aktarımı: IP kilidi sıfırlandı') == 1)

            # Kapat: port serbest, durum pasif, denetim kaydı
            st = ok(a.delete(f'/api/field/flights/{fid}/mp-relay'))
            assert st['active'] is False and drone_mprelay.get(fid) is None, st
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.bind(('0.0.0.0', port))   # bağlanabiliyorsa port gerçekten kapandı
            probe.close()
            assert wait(lambda: audit_count('Mission Planner aktarımı kapandı') == 1)
            assert drone_hub.BRIDGES[b['id']].info()['mp_relays'] == []

            # isteğe bağlı eşleştirme: pair_sysid 250 → sysid 255 kalp atışı kilitlemez, 250 kilitler
            assert a.post(f'/api/field/flights/{fid}/mp-relay', json={'pair_sysid': 999}).status_code == 400
            r = ok(a.post(f'/api/field/flights/{fid}/mp-relay', json={'pair_sysid': 250}))
            port = r['port']
            assert r['pair_sysid'] == 250
            mp.sendto(gcs_hb(255), ('127.0.0.1', port))
            assert wait(lambda: drone_mprelay.get(fid).dropped_invalid >= 1) and drone_mprelay.get(fid).locked_ip is None
            mp.sendto(gcs_hb(250), ('127.0.0.1', port))
            assert recv_raw_up(ws)[1:] == gcs_hb(250)
            assert drone_mprelay.get(fid).locked_ip == '127.0.0.1'

            # hareketsizlik: MP paketi gelmezse kapanır
            drone_mprelay.IDLE_S = 1
            try:
                assert wait(lambda: drone_mprelay.get(fid) is None, 6), 'hareketsizlikte kapanmadı'
            finally:
                drone_mprelay.IDLE_S = 1800
            assert ok(a.get(f'/api/field/flights/{fid}/mp-relay'))['active'] is False

            # görev bitince kapanır
            ok(a.post(f'/api/field/flights/{fid}/mp-relay'))
            with db.connect() as conn:
                conn.execute("UPDATE field_tasks SET status = 'IPTAL' WHERE id = ?", (t['id'],))
                conn.commit()
            assert wait(lambda: drone_mprelay.get(fid) is None, 6), 'görev kapanınca aktarım kapanmadı'
            assert a.post(f'/api/field/flights/{fid}/mp-relay').status_code == 400
        blocker.close()
        with db.connect() as conn:
            reasons = [r[0] for r in conn.execute("SELECT detail FROM audit_logs WHERE action = 'Mission Planner aktarımı kapandı' ORDER BY id")]
        assert len(reasons) == 3 and 'kapatıldı' in reasons[0] and 'hareketsizlik' in reasons[1] and 'görev kapandı' in reasons[2], reasons
    print('Mission Planner aktarımı testleri geçti.')


if __name__ == '__main__':
    main()
