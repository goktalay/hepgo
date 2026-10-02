"""Satın Alma: tedarikçiler (yalnızca Satın Alma'da), talep (kalemler, onaya gönderme, Sistem Yöneticisi onayı),
fatura / irsaliye ile depo girişi (varsayılan Ana Depo, talebin tamamlanması), teklif (kalemler, iletme, revizyon), yetki.

Çalıştırma: .venv/bin/python -m tests.test_purchasing
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
        ok(a.post('/api/users', json={'username': 'satin', 'full_name': 'Satın Alma', 'roles': ['Satın Alma'], 'password': 'sifre-1234'}))
        ok(a.post('/api/users', json={'username': 'idari', 'full_name': 'İdari', 'roles': ['İdari Personel'], 'password': 'sifre-1234'}))
        ok(a.post('/api/companies', json={'name': 'Müşteri AŞ'}))
    with TestClient(app) as s:
        login(s, 'satin')
        assert 'purchasing' in ok(s.get('/api/auth/me'))['modules']
        # Tedarikçi: Firma Yönetimi'nin aynısı; yalnızca Satın Alma'da görünür
        sup = ok(s.post('/api/companies?supplier=1', json={'name': 'Hobby Market', 'email': 'satis@hobby.test', 'address': 'İstanbul'}))['id']
        assert [c['name'] for c in ok(s.get('/api/companies?supplier=1'))] == ['Hobby Market']
        assert s.get('/api/companies').status_code == 403            # firmalar Satın Alma'ya kapalı
        assert s.post('/api/companies', json={'name': 'X'}).status_code == 403
        ok(s.post(f'/api/companies/{sup}/people', json={'full_name': 'Ahmet Satış', 'email': 'ahmet@hobby.test'}))
        assert ok(s.get(f'/api/companies/{sup}'))['people'][0]['full_name'] == 'Ahmet Satış'
        assert [p['full_name'] for p in ok(s.get('/api/crm/contacts?supplier=1'))['people']] == ['Ahmet Satış']
        # Malzemeler: demirbaş ve sarf tipleri (MRP Malzeme Yönetimi)
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        mats = {}
        for code, name, typ, unit in (('MT-1', 'Motor', 'YEDEK_PARCA', 'adet'), ('HM-PLA', 'PLA', 'HAMMADDE', 'g'),
                                      ('DB-VIDA', 'Akülü Vidalama', 'DEMIRBAS', 'adet'), ('SF-ELD', 'İş Eldiveni', 'SARF', 'paket')):
            mats[code] = ok(a.post('/api/mrp/materials', json={'code': code, 'name': name, 'type': typ, 'unit': unit}))['id']
        assert {m['type'] for m in ok(a.get('/api/mrp/materials'))} == {'YEDEK_PARCA', 'HAMMADDE', 'DEMIRBAS', 'SARF'}
        assert [c['name'] for c in ok(a.get('/api/companies'))] == ['Müşteri AŞ']   # tedarikçi Firma Yönetimi'nde yok
        assert [c['name'] for c in ok(a.get('/api/orders/companies'))] == ['Müşteri AŞ'] if a.get('/api/orders/companies').status_code == 200 else True
    with TestClient(app) as s:
        login(s, 'satin')
        # Talep: kalemler, onaya gönderme
        rid = ok(s.post('/api/purchasing/requests', json={'title': 'Ekim üretim ihtiyacı', 'needed_by': '2026-10-15'}))['id']
        assert s.post(f'/api/purchasing/requests/{rid}/submit').status_code == 400   # kalem yok
        ok(s.post(f'/api/purchasing/requests/{rid}/items', json={'product_id': mats['MT-1'], 'qty': 8, 'note': '2 uçak için'}))
        ok(s.post(f'/api/purchasing/requests/{rid}/items', json={'product_id': mats['SF-ELD'], 'qty': 5}))
        assert s.post(f'/api/purchasing/requests/{rid}/items', json={'product_id': mats['MT-1'], 'qty': 0}).status_code == 400
        ok(s.post(f'/api/purchasing/requests/{rid}/submit'))
        assert s.post(f'/api/purchasing/requests/{rid}/items', json={'product_id': mats['HM-PLA'], 'qty': 1}).status_code == 400   # kilitli
        assert s.post(f'/api/purchasing/requests/{rid}/approve', json={}).status_code == 403   # onay Sistem Yöneticisinde
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        assert any(n['key'] == 'purchase-approval' for n in ok(a.get('/api/notifications'))['items'])
        ok(a.post(f'/api/purchasing/requests/{rid}/approve', json={'note': 'Uygun'}))
    with TestClient(app) as s:
        login(s, 'satin')
        assert any(n['key'] == 'purchase-decided' for n in ok(s.get('/api/notifications'))['items'])
        r = ok(s.get(f'/api/purchasing/requests/{rid}'))
        assert r['status'] == 'ONAYLANDI' and [i['received'] for i in r['items']] == [0, 0]
        assert not any(n['key'] == 'purchase-decided' for n in ok(s.get('/api/notifications'))['items'])
        # Fatura: depo seçilmezse Ana Depo; talebe bağlı; kısmi teslim
        opts = ok(s.get('/api/purchasing/options'))
        assert opts['warehouses'][0]['name'] == 'Ana Depo' and [x['name'] for x in opts['suppliers']] == ['Hobby Market']
        assert s.post('/api/purchasing/invoices', json={'kind': 'FATURA', 'lines': [{'product_id': mats['MT-1'], 'qty': 1}]}).status_code == 400   # tedarikçi
        d1 = ok(s.post('/api/purchasing/invoices', json={'kind': 'FATURA', 'number': 'F-1', 'company_id': sup, 'request_id': rid,
                                                         'lines': [{'product_id': mats['MT-1'], 'qty': 5, 'unit_price': 650}]}))['id']
        ok(s.post(f'/api/purchasing/invoices/{d1}/file', files={'file': ('f.pdf', b'%PDF-1.4', 'application/pdf')}))
        r = ok(s.get(f'/api/purchasing/requests/{rid}'))
        assert r['status'] == 'ONAYLANDI' and [i['received'] for i in r['items']] == [5, 0]
        ok(s.post('/api/purchasing/invoices', json={'kind': 'IRSALIYE', 'number': 'I-7', 'company_id': sup, 'request_id': rid,
                                                    'lines': [{'product_id': mats['MT-1'], 'qty': 3}, {'product_id': mats['SF-ELD'], 'qty': 5}]}))
        assert ok(s.get(f'/api/purchasing/requests/{rid}'))['status'] == 'TAMAMLANDI'
        inv = ok(s.get('/api/purchasing/invoices'))
        assert [(d['number'], d['warehouse_name'], len(d['lines'])) for d in inv] == [('I-7', 'Ana Depo', 2), ('F-1', 'Ana Depo', 1)]
        assert inv[1]['lines_total'] == 3250
        # Teklif: talepten kalemler, düzenleme, iletme, revizyon
        qid = ok(s.post('/api/purchasing/quotes', json={'company_id': sup, 'title': 'Motor teklifi', 'request_id': rid, 'vat_rate': 20}))['id']
        q = ok(s.get(f'/api/purchasing/quotes/{qid}'))
        assert [i['description'] for i in q['items']] == ['Motor', 'İş Eldiveni']
        ok(s.put(f'/api/purchasing/quotes/{qid}/items/{q["items"][0]["id"]}', json={'product_id': mats['MT-1'], 'qty': 8, 'unit_price': 600}))
        ok(s.post(f'/api/purchasing/quotes/{qid}/items', json={'description': 'Kargo', 'qty': 1, 'unit_price': 150}))
        q = ok(s.get(f'/api/purchasing/quotes/{qid}'))
        assert (q['subtotal'], q['vat'], q['total']) == (4950, 990, 5940)
        assert s.post(f'/api/purchasing/quotes/{qid}/revise', json={}).status_code == 400   # taslak doğrudan düzenlenir
        ok(s.post(f'/api/purchasing/quotes/{qid}/sent', json={'sent_to': 'satis@hobby.test'}))
        assert s.post(f'/api/purchasing/quotes/{qid}/items', json={'description': 'x', 'qty': 1}).status_code == 400   # iletilen kilitli
        assert ok(s.post(f'/api/purchasing/quotes/{qid}/revise', json={'reason': 'Fiyat güncellendi'}))['revision'] == 1
        q = ok(s.get(f'/api/purchasing/quotes/{qid}'))
        assert (q['status'], q['revision'], len(q['revisions'])) == ('TASLAK', 1, 1)
        ok(s.put(f'/api/purchasing/quotes/{qid}/items/{q["items"][0]["id"]}', json={'product_id': mats['MT-1'], 'qty': 8, 'unit_price': 550}))
        old = ok(s.get(f'/api/purchasing/quotes/{qid}/revisions/{q["revisions"][0]["id"]}'))
        assert old['revision'] == 0 and old['items'][0]['unit_price'] == 600 and old['total'] == 5940 and old['revision_reason'] == 'Fiyat güncellendi'
        ok(s.post(f'/api/purchasing/quotes/{qid}/sent', json={}))
        ok(s.post(f'/api/purchasing/quotes/{qid}/status', json={'status': 'KABUL'}))
        assert ok(s.get('/api/purchasing/quotes'))[0]['status'] == 'KABUL'
    with TestClient(app) as x:
        login(x, 'idari')   # Firma Yönetimi var, Satın Alma yok
        assert x.get('/api/purchasing/requests').status_code == 403
        assert x.get(f'/api/companies/{sup}').status_code == 403           # tedarikçi detayı kapalı
        assert x.get('/api/companies?supplier=1').status_code == 403
    print('Satın Alma testleri geçti.')


if __name__ == '__main__':
    main()
