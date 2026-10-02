"""Doğrudan depoya ekleme: üretim ekranında parçayı seçili yazıcıyla basılmış kabul edip Sistem Yöneticisi onayına
gönderme; onaylanınca parça DEPO'ya (depo onayına) düşer; reddedilince WAITING kalır; yetki.

Çalıştırma: .venv/bin/python -m tests.test_direct_part
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p='sifre-1234'):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def main():
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        ok(a.post('/api/users', json={'username': 'uret', 'full_name': 'Üretim', 'roles': ['Üretim Yöneticisi'], 'password': 'sifre-1234'}))
        prn = ok(a.post('/api/printers', json={'name': 'K2-09', 'ip': '10.0.0.9'}))['id']
        cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
        oid = ok(a.post('/api/orders', json={'product_id': cyz['id'], 'quantity': 1}))[0]['id']
        parts = [p['part_id'] for p in ok(a.get(f'/api/orders/{oid}'))['parts']]
        pA, pB, pC = parts[0], parts[1], parts[2]
    with TestClient(app) as u:
        login(u, 'uret')
        # Doğrudan depo ekleme talebi
        ok(u.post(f'/api/orders/{oid}/parts/{pA}/direct-request', json={'printer_id': prn, 'at': '2026-09-20T10:00'}))
        d = ok(u.get(f'/api/orders/{oid}/parts/{pA}'))
        assert d['state'] == 'BEKLIYOR' and d['direct_request']['status'] == 'BEKLIYOR' and d['direct_request']['printer_name'] == 'K2-09'
        assert d['can_approve_direct'] is False   # üretim yöneticisi onaylayamaz
        assert next(p for p in ok(u.get(f'/api/orders/{oid}'))['parts'] if p['part_id'] == pA)['direct_pending'] == 1
        # bekleyen talep varken normal start ve ikinci talep engellenir
        assert u.post(f'/api/orders/{oid}/parts/{pA}/start', json={'printer_id': prn}).status_code == 409
        assert u.post(f'/api/orders/{oid}/parts/{pA}/direct-request', json={'printer_id': prn}).status_code == 409
        # üretim yöneticisi onaylayamaz
        assert u.post(f'/api/orders/{oid}/parts/{pA}/direct-approve', json={}).status_code == 403
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        assert any(n['key'] == 'direct-part-pending' for n in ok(a.get('/api/notifications'))['items'])
        # Onay: parça DEPO'ya (depo onayına) düşer, seçili yazıcı ve baskı zamanı kaydedilir
        ok(a.post(f'/api/orders/{oid}/parts/{pA}/direct-approve', json={'note': 'Elde basılmış'}))
        d = ok(a.get(f'/api/orders/{oid}/parts/{pA}'))
        assert d['state'] == 'DEPO' and d['approved_at'] is None and d['printer_name'] == 'K2-09'
        assert d['started_at'].startswith('2026-09-20') and d['direct_request']['status'] == 'ONAYLANDI'
        assert any(e['event'] == 'DOGRUDAN_DEPO' for e in d['events'])
        assert not any(n['key'] == 'direct-part-pending' for n in ok(a.get('/api/notifications'))['items'])
        # Depo onayına düştü mü
        pend = ok(a.get('/api/warehouse/pending'))
        assert any(x['part_id'] == pA for x in pend)
        # Reddetme: parça WAITING kalır
        ok(a.post(f'/api/orders/{oid}/parts/{pB}/direct-request', json={'printer_id': prn}))
        ok(a.post(f'/api/orders/{oid}/parts/{pB}/direct-reject', json={'note': 'Basılmamış'}))
        d = ok(a.get(f'/api/orders/{oid}/parts/{pB}'))
        assert d['state'] == 'BEKLIYOR' and d['direct_request']['status'] == 'REDDEDILDI'
        # reddedilince yeniden talep / normal başlatma açık
        ok(a.post(f'/api/orders/{oid}/parts/{pB}/start', json={'printer_id': prn}))
        # depo yöneticisi onaylar → normal akış
        ok(a.post('/api/users', json={'username': 'depo', 'full_name': 'Depo', 'roles': ['Depo Yöneticisi'], 'password': 'sifre-1234'}))
    with TestClient(app) as d:
        login(d, 'depo')
        pid = next(x['id'] for x in ok(d.get('/api/warehouse/pending')) if x['part_id'] == pA)
        ok(d.post('/api/warehouse/approve', json={'ids': [pid]}))
        assert not any(x['part_id'] == pA for x in ok(d.get('/api/warehouse/pending')))
    print('Doğrudan depo ekleme testleri geçti.')


if __name__ == '__main__':
    main()
