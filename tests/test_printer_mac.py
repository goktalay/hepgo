"""Yazıcı kimliği MAC: normalize, göç (ip UNIQUE kalkar, yinelenen MAC birleşir, UNIQUE MAC dizini), IP çakışmasında hata
olmaması, gönderimde MAC doğrulaması (doğru IP / değişmiş IP / aynı IP'de başka cihaz), tarama önbelleği (tek uçuş),
MAC öğrenme. Ağ gerektirmez: identify / discover taklit edilir.
Çalıştırma: .venv/bin/python -m tests.test_printer_mac
"""
import json
import os
import re
import sqlite3
import tempfile
import threading
import time

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, printer_driver, printer_identity as pi  # noqa: E402
from app.main import app  # noqa: E402

M1, M2, M3 = 'FC:EE:28:0F:36:97', 'FC:EE:28:0F:28:CB', 'FC:EE:28:0E:FA:2F'
OTHER = 'A8:BB:CC:DD:EE:01'   # kalıcı (üretici) MAC
RND = '9E:96:32:06:3B:A1'     # rastgele Wi-Fi MAC'i (PROD ağ taramasında görülen türden)


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def test_normalize():
    assert pi.normalize_mac('fc-ee-28-0f-36-97') == M1
    assert pi.normalize_mac('fcee.280f.3697') == M1
    assert pi.normalize_mac(' FC:EE:28:0F:36:97 ') == M1
    assert pi.normalize_mac('') is None and pi.normalize_mac(None) is None
    for bad in ('FC:EE:28:0E:E5:E', 'GG:EE:28:0F:36:97', '00:00:00:00:00:00', 'FC:EE:28:0F:36:97:01'):
        try:
            pi.normalize_mac(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert pi.hw_from_mac(M1) == 'K2Plus-3697'
    assert pi.hw_matches('K2Plus-3697', M1) is True and pi.hw_matches('k2plus-3697', M1) is True
    assert pi.hw_matches('K2Plus-28CB', M1) is False and pi.hw_matches('21', M1) is None
    # verdict
    assert pi.verdict({'arp_mac': M1.lower()}, M1) == 'mac'
    assert pi.verdict({'macs': [OTHER, M1]}, M1) == 'mac'                  # yazıcının API'si (kablolu + Wi-Fi)
    assert pi.verdict({'arp_mac': OTHER, 'hw': 'K2Plus-3697'}, M1) == 'hw'   # Wi-Fi'den ulaşıldı, ağ adı tutuyor
    assert pi.verdict({'arp_mac': OTHER, 'hw': 'K2Plus-28CB'}, M1) == 'mismatch'
    assert pi.verdict({'arp_mac': OTHER}, M1) == 'mismatch'
    assert pi.verdict({'hw': 'K2Plus-28CB'}, M1) == 'mismatch'
    assert pi.verdict({'hw': '21'}, M1, aliases=('21',)) == 'alias'
    assert pi.verdict({'hw': '21'}, M1) == 'unknown'
    assert pi.verdict({'reachable': False}, M1) == 'unknown' and pi.verdict(None, M1) == 'unknown'
    # Rastgele (Wi-Fi gizlilik) MAC: kanıt sayılmaz — ne doğrular ne reddeder; ağ adı / kayıtlı ad karar verir
    assert pi.is_random(RND) and not pi.is_random(M1)
    assert pi.verdict({'arp_mac': RND}, M1) == 'unknown'
    assert pi.verdict({'arp_mac': RND, 'hw': 'K2Plus-3697'}, M1) == 'hw'
    assert pi.verdict({'arp_mac': RND, 'hw': '21'}, M1, aliases=('21',)) == 'alias'
    assert pi.verdict({'arp_mac': RND, 'macs': [M2, RND], 'hw': '21'}, M1, aliases=('21',)) == 'mismatch'   # cihaz listesi tam
    assert pi.verdict({'arp_mac': RND, 'macs': [M1, RND], 'hw': '21'}, M1) == 'mac'


def _old_schema(conn):
    """Göç öncesi durumu kur: printers.ip NOT NULL UNIQUE, MAC dizini yok."""
    conn.commit()
    conn.execute('DROP INDEX IF EXISTS ux_printers_mac')
    conn.execute('DROP INDEX IF EXISTS ix_printers_ip')
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='printers'").fetchone()[0]
    old = re.sub(r'\bip\s+TEXT,[^\n]*', 'ip TEXT NOT NULL UNIQUE,', sql, count=1).replace('CREATE TABLE printers', 'CREATE TABLE printers_eski', 1)
    assert 'NOT NULL UNIQUE' in old
    conn.execute('PRAGMA foreign_keys = OFF')
    conn.executescript('BEGIN;' + old + ';INSERT INTO printers_eski SELECT * FROM printers;DROP TABLE printers;'
                       'ALTER TABLE printers_eski RENAME TO printers;COMMIT;')
    conn.execute('PRAGMA foreign_keys = ON')


def test_migration(a):
    cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
    oid = ok(a.post('/api/orders', json={'product_id': cyz['id'], 'quantity': 1}))[0]['id']
    with db.connect() as conn:
        ops = [r[0] for r in conn.execute('SELECT id FROM order_parts WHERE order_id = ? ORDER BY id LIMIT 2', (oid,))]
        conn.execute('DELETE FROM printers')
        _old_schema(conn)
        ins = ('INSERT INTO printers (id, name, ip, mac, hw_id, created_at, last_seen, current_part_id, rack_side, rack_level, rack_slot) '
               'VALUES (?,?,?,?,?,?,?,?,?,?,?)')
        now = db.now()
        conn.execute(ins, (1, 'A', '10.1.0.1', 'fc-ee-28-0f-36-97', 'K2Plus-3697', now, '2026-10-01T10:00:00', None, None, None, None))
        conn.execute(ins, (2, 'B', '10.1.0.2', M1, None, now, '2026-10-20T10:00:00', None, 'L', 1, 1))   # aynı MAC, daha yeni
        conn.execute(ins, (3, 'C', '10.1.0.3', 'FC:EE:28:0E:E5:E', None, now, None, None, None, None, None))   # geçersiz MAC
        conn.execute(ins, (4, 'D', '#tasima-4', 'FC:EE:28:00:00:04', None, now, None, None, None, None, None))  # park IP
        conn.execute(ins, (5, 'E', '10.1.0.5', M2, None, now, None, ops[0], None, None, None))   # aynı MAC + ikisinde de iş
        conn.execute(ins, (6, 'F', '10.1.0.6', M2.lower(), None, now, None, ops[1], None, None, None))
        conn.execute("INSERT INTO part_events (order_part_id, event, user_id, printer_id, at) VALUES (?, 'TEST', NULL, 1, ?)", (ops[0], now))
        conn.execute("INSERT INTO printer_incidents (printer_id, kind, started_at, ended_at) VALUES (1, 'KAYITSIZ_IPTAL', ?, ?)", (now, now))
        db.audit(conn, None, 'test', 'printer', 1, 'A')
        conn.commit()
        try:   # eski şemada aynı IP iki kayda yazılamıyordu (UNIQUE) — göçün kaldırdığı kısıt
            conn.execute("UPDATE printers SET ip = '10.1.0.2' WHERE id = 1")
            raise AssertionError('UNIQUE bekleniyordu')
        except sqlite3.IntegrityError:
            conn.rollback()

        rep = pi.migrate(conn)
        assert rep['rebuilt'] is True, rep
        rows = {r['id']: r for r in db.rows(conn.execute('SELECT * FROM printers'))}
        assert 1 not in rows and rows[2]['mac'] == M1 and rows[2]['hw_id'] == 'K2Plus-3697', rows.get(2)   # A → B birleşti
        assert rows[2]['rack_side'] == 'L'
        assert conn.execute('SELECT COUNT(*) FROM part_events WHERE printer_id = 2').fetchone()[0] == 1   # bağlı kayıt taşındı
        assert conn.execute('SELECT COUNT(*) FROM printer_incidents WHERE printer_id = 2').fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE entity = 'printer' AND entity_id = '1'").fetchone()[0] == 0
        assert rows[3]['mac'] is None and rep['invalid'][0]['mac'] == 'FC:EE:28:0E:E5:E'
        assert rows[4]['ip'] is None and rows[4]['mac'] == 'FC:EE:28:00:00:04'
        assert rows[5]['mac'] == M2 and rows[6]['mac'] is None and rep['conflicts'][0]['keep'] == 5   # iş varken birleştirme yok
        assert rows[6]['current_part_id'] == ops[1]
        assert rows[2]['mac_source'] == 'kayit'
        assert [m['removed'] for m in rep['merged']] == [1]
        stored = json.loads(conn.execute("SELECT v FROM app_kv WHERE k = 'printers.mac_migration'").fetchone()[0])
        assert stored['merged'][0]['keep'] == 2
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        # MAC benzersiz (NULL'lar hariç); IP artık benzersiz değil ve boş olabilir
        try:
            conn.execute('UPDATE printers SET mac = ? WHERE id = 3', (M1,))
            raise AssertionError('MAC UNIQUE bekleniyordu')
        except sqlite3.IntegrityError:
            conn.rollback()
        conn.execute("UPDATE printers SET ip = '10.1.0.2' WHERE id = 5")
        conn.execute('UPDATE printers SET mac = NULL WHERE id = 4')   # iki NULL MAC serbest
        conn.rollback()
        # İdempotent: ikinci çalıştırma hiçbir şey yapmaz
        rep2 = pi.migrate(conn)
        assert not any(rep2[k] for k in ('rebuilt', 'ip_cleared', 'normalized', 'invalid', 'merged', 'conflicts')), rep2
        conn.execute('UPDATE printers SET current_part_id = NULL')
        conn.execute('DELETE FROM printers')
        conn.commit()


def add(name, ip, mac=None, hw=None, alias=None):
    with db.connect() as conn:
        cur = conn.execute('INSERT INTO printers (name, ip, mac, hw_id, hw_alias, created_at) VALUES (?,?,?,?,?,?)',
                           (name, ip, mac, hw, alias, db.now()))
        conn.commit()
        return cur.lastrowid


def get(pid):
    with db.connect() as conn:
        return db.row(conn.execute('SELECT * FROM printers WHERE id = ?', (pid,)))


def clear():
    with db.connect() as conn:
        conn.execute('DELETE FROM printers')
        conn.commit()
    pi.invalidate_scan()


def live(mac=None, hw=None, state='HAZIR'):
    d = {'state': state, 'progress': 0.0, 'file': None, 'source': 'moonraker', 'model': 'Creality K2 Plus', 'hostname': hw}
    if mac is not None:
        d['mac'] = mac
    if hw is not None:
        d['hw'] = hw
    return d


def test_ip_conflicts():
    clear()
    # IP takası (MAC ile): hata yok, IP'ler yer değiştirir
    p1, p2 = add('P1', '10.0.0.50', M1), add('P2', '10.0.0.60', M2)
    r = pi.apply_scan([['10.0.0.60', live(M1, 'K2Plus-3697')], ['10.0.0.50', live(M2, 'K2Plus-28CB')]])
    assert get(p1)['ip'] == '10.0.0.60' and get(p2)['ip'] == '10.0.0.50' and len(r['moved']) == 2, r
    # Eski "UNIQUE constraint failed: printers.ip" senaryosu: P1 yeni IP'si, çevrimdışı P3'ün tuttuğu IP
    clear()
    p1, p3 = add('P1', '10.0.0.50', None, 'K2Plus-3697'), add('P3', '10.0.0.51', M3)
    printer_driver.discover = lambda: [['10.0.0.51', live(None, 'K2Plus-3697')]]   # eski ajan: MAC yok, ağ adı var
    assert printer_driver.reconcile_ips() == 1
    assert get(p1)['ip'] == '10.0.0.51' and get(p3)['ip'] is None, (get(p1), get(p3))
    # Wi-Fi'deki yazıcı: ARP rastgele MAC, ad elle '21'; yazıcının API'si kablolu MAC'i bildirir → MAC ile eşleşir
    clear()
    p1 = add('P1', '10.0.0.50', M1, None, '21')
    d = dict(live(RND, '21'), macs=[M1, RND])
    r = pi.apply_scan([['10.0.0.77', d]])
    assert get(p1)['ip'] == '10.0.0.77'
    # MAC'siz kayda taramadaki kablolu MAC öğrenilir
    clear()
    p1 = add('P1', '10.0.0.50', None, 'K2Plus-3697')
    r = pi.apply_scan([['10.0.0.50', live(M1, 'K2Plus-3697')]])
    assert get(p1)['mac'] == M1 and get(p1)['mac_source'] == 'arp' and r['learned'], r
    # Wi-Fi MAC'i (ağ adına uymayan) kalıcı kimlik yapılmaz
    clear()
    p1 = add('P1', '10.0.0.50', None, 'K2Plus-3697')
    pi.apply_scan([['10.0.0.50', live(OTHER, 'K2Plus-3697')]])
    assert get(p1)['mac'] is None
    # Kayıtlı yazıcının IP'sinde başka (MAC'i farklı) cihaz: kayıt o IP'den düşer, yeni yazıcı MAC'iyle eklenir
    clear()
    p1 = add('P1', '10.0.0.50', M1)
    r = pi.apply_scan([['10.0.0.50', live(M2, 'K2Plus-28CB')]], add_new=True)
    assert get(p1)['ip'] is None and r['added'][0]['mac'] == M2, r
    with db.connect() as conn:
        assert conn.execute('SELECT ip FROM printers WHERE mac = ?', (M2,)).fetchone()[0] == '10.0.0.50'


def test_resolve():
    clear()
    calls = {'discover': 0}
    devices = {}   # ip → kimlik

    def fake_identify(ip):
        return devices.get(ip) or {'ip': ip, 'reachable': False, 'arp_mac': None, 'macs': [], 'hw': None}

    def fake_discover():
        calls['discover'] += 1
        return [[ip, live(d.get('arp_mac'), d.get('hw'))] for ip, d in devices.items() if d.get('reachable')]
    pi.identify = fake_identify
    printer_driver.discover = fake_discover

    p1 = add('P1', '10.0.0.10', M1)
    # 1) Doğru IP: MAC ARP'den doğrulanır, tarama yok
    devices['10.0.0.10'] = {'ip': '10.0.0.10', 'reachable': True, 'arp_mac': M1, 'macs': [], 'hw': 'K2Plus-3697'}
    r = pi.resolve_ip(p1)
    assert r == {'ip': '10.0.0.10', 'mac': M1, 'method': 'mac', 'moved_from': None}, r
    assert calls['discover'] == 0 and get(p1)['mac_checked_at']
    # 2) IP değişti (eski IP boş): ağ taranır, yeni IP kaydedilir; yeni IP'yi tutan eski kaydın IP'si boşaltılır
    p9 = add('P9', '10.0.0.20', 'FC:EE:28:00:00:09')
    devices.clear()
    devices['10.0.0.20'] = {'ip': '10.0.0.20', 'reachable': True, 'arp_mac': M1, 'macs': [], 'hw': 'K2Plus-3697'}
    r = pi.resolve_ip(p1)
    assert r['ip'] == '10.0.0.20' and r['method'] == 'scan' and r['moved_from'] == '10.0.0.10', r
    assert get(p1)['ip'] == '10.0.0.20' and get(p9)['ip'] is None
    assert calls['discover'] == 1
    # 3) Aynı IP'de BAŞKA cihaz (P2'nin MAC'i): reddedilir, tarama P1'i yeni yerinde bulur
    p2 = add('P2', '10.0.0.30', M2)
    devices.clear()
    devices['10.0.0.20'] = {'ip': '10.0.0.20', 'reachable': True, 'arp_mac': M2, 'macs': [], 'hw': 'K2Plus-28CB'}
    devices['10.0.0.40'] = {'ip': '10.0.0.40', 'reachable': True, 'arp_mac': M1, 'macs': [], 'hw': 'K2Plus-3697'}
    pi.invalidate_scan()
    r = pi.resolve_ip(p1)
    assert r['ip'] == '10.0.0.40' and r['method'] == 'scan', r
    # 4) Başka cihaz IP'de ve yazıcı ağda yok: açık hata, gönderim yok
    devices.pop('10.0.0.40')
    pi.invalidate_scan()
    try:
        pi.resolve_ip(p1)
        raise AssertionError('hata bekleniyordu')
    except pi.IdentityError as e:
        assert 'Yazıcı ağda bulunamadı — MAC ' + M1 in str(e), e
    assert get(p1)['ip'] == '10.0.0.40'   # yanlış cihaza (P2) taşınmadı
    # 5) Eski ajan: MAC okunamıyor, ağ adı doğrular; ağ adı başka → tarama
    devices.clear()
    devices['10.0.0.40'] = {'ip': '10.0.0.40', 'reachable': True, 'arp_mac': None, 'macs': [], 'hw': 'K2Plus-3697', 'legacy': True}
    assert pi.resolve_ip(p1)['method'] == 'hw'
    # 6) Ağ adı elle sayıya çevrilmiş yazıcı (hw_alias, yalnız bu yazıcıda): MAC okunamadığında ad doğrular
    p5 = add('P5', '10.0.0.55', M3, None, '21')
    devices['10.0.0.55'] = {'ip': '10.0.0.55', 'reachable': True, 'arp_mac': None, 'macs': [], 'hw': '21'}
    assert pi.resolve_ip(p5)['method'] == 'alias'
    devices['10.0.0.55'] = {'ip': '10.0.0.55', 'reachable': True, 'arp_mac': OTHER, 'macs': [], 'hw': '21'}
    pi.invalidate_scan()
    try:   # MAC okundu ve başka: ad tutsa da reddedilir
        pi.resolve_ip(p5)
        raise AssertionError('hata bekleniyordu')
    except pi.IdentityError:
        pass
    # 7) MAC'siz yazıcı: gönderim yok
    p0 = add('P0', '10.0.0.70')
    try:
        pi.resolve_ip(p0)
        raise AssertionError('hata bekleniyordu')
    except pi.IdentityError as e:
        assert 'MAC adresi tanımlı değil' in str(e)
    # 8) Önbellek + tek uçuş: eşzamanlı 5 istek tek tarama; 60 sn içinde ikinci tarama yok
    pi.invalidate_scan()
    calls['discover'] = 0

    def slow():
        time.sleep(0.2)
        calls['discover'] += 1
        return [['10.0.0.99', live(M1, 'K2Plus-3697')]]
    printer_driver.discover = slow
    th = [threading.Thread(target=pi.scan) for _ in range(5)]
    [t.start() for t in th]
    [t.join() for t in th]
    assert calls['discover'] == 1, calls
    _, fresh = pi.scan()
    assert calls['discover'] == 1 and fresh is False
    pi.scan(max_age=0)
    assert calls['discover'] == 2
    printer_driver.discover = fake_discover
    return p2


def test_learn(a):
    clear()
    devices = {}
    pi.identify = lambda ip: devices.get(ip) or {'ip': ip, 'reachable': False, 'arp_mac': None, 'macs': [], 'hw': None}
    printer_driver.discover = lambda: [[ip, live(d.get('arp_mac'), d.get('hw'))] for ip, d in devices.items() if d.get('reachable')]
    p1 = add('P1', '10.0.0.10', None, 'K2Plus-3697')
    devices['10.0.0.10'] = {'ip': '10.0.0.10', 'reachable': True, 'arp_mac': OTHER, 'macs': [OTHER, M1], 'hw': 'K2Plus-3697'}
    r = ok(a.post(f'/api/printers/{p1}/learn-mac'))
    assert r['mac'] == M1 and r['source'] == 'cihaz', r   # Wi-Fi MAC'i değil, ağ adına uyan kablolu MAC
    # O IP'de başka yazıcı (ağ adı farklı) ve yazıcı ağda yok → reddedilir
    p2 = add('P2', '10.0.0.20', None, 'K2Plus-28CB')
    devices['10.0.0.20'] = {'ip': '10.0.0.20', 'reachable': True, 'arp_mac': M3, 'macs': [], 'hw': 'K2Plus-FA2F'}
    assert a.post(f'/api/printers/{p2}/learn-mac').status_code == 409
    assert get(p2)['mac'] is None
    # Başka yazıcının MAC'i: reddedilir
    p3 = add('P3', '10.0.0.30')
    devices['10.0.0.30'] = {'ip': '10.0.0.30', 'reachable': True, 'arp_mac': M1, 'macs': [], 'hw': None}
    r = a.post(f'/api/printers/{p3}/learn-mac')
    assert r.status_code == 409 and 'P1' in r.text, r.text
    # Elle MAC: normalize, yineleneni 409
    p4 = ok(a.post('/api/printers', json={'name': 'P4', 'mac': 'fc:ee:28:0e:fa:2f'}))['id']
    assert get(p4)['mac'] == M3 and get(p4)['mac_source'] == 'elle' and get(p4)['ip'] is None
    assert a.post('/api/printers', json={'name': 'P5', 'mac': M3.replace(':', '-')}).status_code == 409
    assert a.post('/api/printers', json={'name': 'P6', 'mac': 'FC:EE:28'}).status_code == 400
    lst = ok(a.get('/api/printers'))
    assert next(p for p in lst if p['id'] == p4)['mac'] == M3


def main():
    test_normalize()
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        test_migration(a)
        test_ip_conflicts()
        test_resolve()
        test_learn(a)
    print('Yazıcı MAC kimliği (normalize, göç, IP çakışması, gönderimde MAC doğrulama, önbellek, öğrenme) testleri geçti.')


if __name__ == '__main__':
    main()
