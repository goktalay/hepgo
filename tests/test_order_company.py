"""Siparişin firması: sipariş açarken firma seçilir, sonradan değiştirilebilir; listede firma adı ve logosu gelir.
Firma logosu, Firma Yönetimi modülü olmayan üretim kullanıcılarına da açıktır.

Çalıştırma: .venv/bin/python -m tests.test_order_company
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
       b'\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82')


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        rok = ok(a.post('/api/companies', json={'name': 'Roketsan Anonim Şirketi'}))['id']
        gok = ok(a.post('/api/companies', json={'name': 'Gökkubbe Teknoloji'}))['id']
        logo = ok(a.post(f'/api/companies/{rok}/logo', files={'file': ('logo.png', PNG, 'image/png')}))['logo']
        assert {c['id'] for c in ok(a.get('/api/orders/companies'))} >= {rok, gok}
        cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
        assert a.post('/api/orders', json={'product_id': cyz['id'], 'company_id': 999}).status_code == 400
        oid = ok(a.post('/api/orders', json={'product_id': cyz['id'], 'company_id': rok}))[0]['id']
        o = ok(a.get(f'/api/orders/{oid}'))
        assert o['company_id'] == rok and o['company_name'] == 'Roketsan Anonim Şirketi' and o['company_logo'] == logo
        ok(a.put(f'/api/orders/{oid}/company', json={'company_id': gok}))
        assert next(x for x in ok(a.get('/api/orders')) if x['id'] == oid)['company_name'] == 'Gökkubbe Teknoloji'
        assert a.put(f'/api/orders/{oid}/company', json={'company_id': 12345}).status_code == 400
        ok(a.post('/api/users', json={'username': 'montaj', 'full_name': 'Montaj', 'roles': ['Montaj Personeli'], 'password': 'sifre-1234'}))
        ok(a.post('/api/users', json={'username': 'pilot', 'full_name': 'Pilot', 'roles': ['Pilot'], 'password': 'sifre-1234'}))
    with TestClient(app) as m:   # üretim ekranı kullanıcısı: logoyu görür, firmayı değiştiremez
        ok(m.post('/api/auth/login', json={'username': 'montaj', 'password': 'sifre-1234'}))
        assert m.get(f'/api/files/{logo}').status_code == 200
        assert m.put(f'/api/orders/{oid}/company', json={'company_id': rok}).status_code == 403
    with TestClient(app) as p:   # ilgisiz modül: logo kapalı
        ok(p.post('/api/auth/login', json={'username': 'pilot', 'password': 'sifre-1234'}))
        assert p.get(f'/api/files/{logo}').status_code == 404   # yetkisiz: dosyanın varlığı belli edilmez
    print('Sipariş firması testleri geçti.')


if __name__ == '__main__':
    main()
