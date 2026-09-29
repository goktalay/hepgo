"""Araçlar → Üretim Hataları: "Hata verdi" ile kapatılan parçaların hata kodu, açıklaması, resmi, yazıcısı ve
kaydedeni listelenir; yetki (Üretim / Yazıcı / Sipariş modülü).

Çalıştırma: .venv/bin/python -m tests.test_production_errors
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


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        pid = ok(a.post('/api/printers', json={'name': '12', 'ip': '10.0.0.12'}))['id']
        cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
        oid = ok(a.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']
        for i, (part, code, desc, photo) in enumerate([('09', 'E-12', 'Katman kayması', True), ('09', 'Havaya baskı', '', False),
                                                       ('L4', '', 'Filament sıkıştı', True)]):
            ok(a.post(f'/api/orders/{oid}/parts/{part}/start', json={'printer_id': pid}))
            files = {'photo': ('hata.jpg', b'\xff\xd8\xff fake', 'image/jpeg')} if photo else None
            ok(a.post(f'/api/orders/{oid}/parts/{part}/error', data={'error_code': code or '-', 'description': desc}, files=files))
        rows = ok(a.get('/api/production-errors'))
        assert len(rows) == 3
        last = rows[0]   # en yeni üstte
        assert last['part_id'] == 'L4' and last['note'] == 'Filament sıkıştı' and last['photo'] and last['printer_name'] == '12'
        assert last['user_name'] and last['order_code'] == 'SP-0001' and last['part_state'] == 'HATA' and last['part_state_text'] == 'Hata'
        p09 = [r for r in rows if r['part_id'] == '09']
        assert [r['error_code'] for r in p09] == ['Havaya baskı', 'E-12'] and all(r['part_errors'] == 2 for r in p09)
        assert p09[0]['photo'] is None and p09[1]['photo']
        assert a.get(f'/api/files/{last["photo"]}').status_code == 200
        for u, role in (('yazici', 'Yazıcı Bakım Sorumlusu'), ('pilot', 'Pilot')):
            ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': [role], 'password': 'sifre-1234'}))
    with TestClient(app) as y:   # yazıcı bakım sorumlusu görür
        ok(y.post('/api/auth/login', json={'username': 'yazici', 'password': 'sifre-1234'}))
        assert len(ok(y.get('/api/production-errors'))) == 3
    with TestClient(app) as p:   # ilgisiz rol göremez
        ok(p.post('/api/auth/login', json={'username': 'pilot', 'password': 'sifre-1234'}))
        assert p.get('/api/production-errors').status_code == 403
    print('Üretim hataları testleri geçti.')


if __name__ == '__main__':
    main()
