"""Araçlar › Ağ Tarayıcı: yalnızca Sistem Yöneticisi; tarama arka planda (burada sahte tarama), cihaza ad verme,
çevrimdışı kaydı silme, üretici (OUI) ve tür tahmini.

Çalıştırma: .venv/bin/python -m tests.test_netscan
"""
import os
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, netscan  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def fake_scan():
    now = db.now()
    with db.connect() as conn:
        conn.execute('UPDATE network_devices SET online = 0')
        for key, ip, mac, host, kind in (('aa:bb:cc:00:00:01', '192.168.1.10', 'aa:bb:cc:00:00:01', 'MUHASEBE-PC', 'Windows bilgisayar'),
                                         ('ip:192.168.1.20', '192.168.1.20', None, None, 'Bilinmiyor')):
            conn.execute('''INSERT INTO network_devices (key, ip, mac, hostname, kind, ports, online, first_seen, last_seen)
                            VALUES (?,?,?,?,?,'[445, 3389]',1,?,?) ON CONFLICT(key) DO UPDATE SET online = 1, last_seen = excluded.last_seen''',
                         (key, ip, mac, host, kind, now, now))
        conn.execute("INSERT OR REPLACE INTO app_kv (k, v) VALUES ('netscan.last', ?)",
                     ('{"at": "%s", "networks": [{"iface": "eth0", "ip": "192.168.1.2", "cidr": "192.168.1.0/24"}], "gateway": "192.168.1.1", "count": 2}' % now,))
        conn.commit()


def main():
    netscan._scan = fake_scan
    # tür tahmini ve yerel (rastgele) MAC
    base = {'ports': [], 'vendor': None, 'hostname': None, 'is_gateway': False, 'is_server': False, 'known': None}
    assert netscan._kind({**base, 'ports': [22, 80, 7125]}) == '3B yazıcı'
    assert netscan._kind({**base, 'ports': [445, 3389], 'netbios': 'PC1'}) == 'Windows bilgisayar'
    assert netscan._kind({**base, 'hostname': 'Android_X.local'}) == 'Telefon / tablet'
    assert netscan._kind({**base, 'is_gateway': True, 'ports': [80]}) == 'Modem / yönlendirici'
    assert netscan.vendor('9e:96:32:06:3b:a1') == 'Yerel (rastgele) MAC'
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ok(a.post('/api/users', json={'username': 'sek', 'full_name': 'Sekreter', 'roles': ['Sekreter'], 'password': 'sifre-1234'}))
        assert ok(a.get('/api/tools/network'))['devices'] == []
        ok(a.post('/api/tools/network/scan'))
        for _ in range(50):
            if not ok(a.get('/api/tools/network/state'))['running']:
                break
            time.sleep(0.1)
        d = ok(a.get('/api/tools/network'))
        assert [x['ip'] for x in d['devices']] == ['192.168.1.10', '192.168.1.20'] and d['last']['count'] == 2
        assert [p['name'] for p in d['devices'][0]['ports']] == ['SMB', 'RDP']
        pc = d['devices'][0]
        ok(a.put(f'/api/tools/network/{pc["id"]}', json={'label': 'Muhasebe', 'note': 'Kat 2'}))
        assert ok(a.get('/api/tools/network'))['devices'][0]['label'] == 'Muhasebe'
        assert a.delete(f'/api/tools/network/{pc["id"]}').status_code == 400   # çevrimiçi cihaz silinmez
        with db.connect() as conn:
            conn.execute("UPDATE network_devices SET online = 0 WHERE ip = '192.168.1.20'")
            conn.commit()
        other = next(x for x in ok(a.get('/api/tools/network'))['devices'] if x['ip'] == '192.168.1.20')
        ok(a.delete(f'/api/tools/network/{other["id"]}'))
    with TestClient(app) as s:   # yetki: Sekreter göremez
        ok(s.post('/api/auth/login', json={'username': 'sek', 'password': 'sifre-1234'}))
        assert s.get('/api/tools/network').status_code == 403
        assert s.post('/api/tools/network/scan').status_code == 403
    print('Ağ tarayıcı testleri geçti.')


if __name__ == '__main__':
    main()
