"""Malzeme İhtiyaç Planlaması: depolar, malzeme (yedek parça / hammadde) kaydı ve bilgileri, stok hareketleri
(giriş + fatura, çıkış, transfer, sayım, kullanım, hurda), resimler, uçuş kaynaklı hurda değerlendirmesi, yetki.

Çalıştırma: .venv/bin/python -m tests.test_mrp
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                    '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082')


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p='sifre-1234'):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def main():
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        for u, role in (('mrp', 'MRP Sorumlusu'), ('depo', 'Depo Yöneticisi'), ('uret', 'Üretim Sorumlusu'), ('saha', 'Saha Sorumlusu'), ('sek', 'Sekreter')):
            ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': [role], 'password': 'sifre-1234'}))
    with TestClient(app) as d:
        login(d, 'depo')
        me = ok(d.get('/api/auth/me'))
        assert {'mrp', 'stock', 'warehouse'} <= set(me['modules'])
        # Depolar: varsayılan Ana Depo; yeni depo ve sorumlusu
        ws = ok(d.get('/api/mrp/warehouses'))
        assert [w['name'] for w in ws] == ['Ana Depo']
        ana = ws[0]['id']
        w2 = ok(d.post('/api/mrp/warehouses', json={'name': 'Saha Deposu', 'code': 'saha', 'responsible_id': me['id'], 'location': 'Polatlı'}))['id']
        assert d.post('/api/mrp/warehouses', json={'name': 'X', 'code': 'SAHA'}).status_code == 400
        assert next(w for w in ok(d.get('/api/mrp/warehouses')) if w['id'] == w2)['responsible_name'] == 'Depo'
        # Malzeme: yedek parça / hammadde
        assert d.post('/api/mrp/materials', json={'code': 'M1', 'name': 'X', 'type': 'MAMUL'}).status_code == 400
        mot = ok(d.post('/api/mrp/materials', json={'code': 'mt-2212', 'name': 'Fırçasız Motor 2212', 'type': 'YEDEK_PARCA'}))['id']
        pla = ok(d.post('/api/mrp/materials', json={'code': 'HM-PLA', 'name': 'PLA Filament', 'type': 'HAMMADDE', 'unit': 'g'}))['id']
        ok(d.put(f'/api/mrp/materials/{mot}', json={'code': 'MT-2212', 'name': 'Fırçasız Motor 2212', 'type': 'YEDEK_PARCA', 'unit': 'adet',
                                                   'barcode': '8690000000011', 'brand': 'T-Motor', 'model': 'MN2212', 'min_stock': 4}))
        assert d.put(f'/api/mrp/materials/{pla}', json={'code': 'HM-PLA', 'name': 'PLA', 'type': 'HAMMADDE', 'barcode': '8690000000011'}).status_code == 400
        ok(d.put(f'/api/mrp/materials/{mot}/physical', json={'color': 'Siyah', 'width_mm': 28, 'height_mm': 28, 'depth_mm': 32, 'weight_g': 56}))
        m = ok(d.get(f'/api/mrp/materials/{mot}'))
        assert (m['brand'], m['model'], m['color'], m['weight_g'], m['stock'], m['critical']) == ('T-Motor', 'MN2212', 'Siyah', 56, 0, True)
        # Giriş (faturayla), çıkış, transfer, sayım, kullanım, hurda
        doc = ok(d.post('/api/mrp/docs', data={'kind': 'FATURA', 'number': 'ABC-2026-1', 'doc_date': '2026-09-20', 'supplier': 'Hobby Ltd', 'amount': '12000'},
                        files={'file': ('fatura.pdf', b'%PDF-1.4 x', 'application/pdf')}))['id']
        ok(d.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'GIRIS', 'warehouse_id': ana, 'qty': 20, 'unit_price': 600, 'doc_id': doc}))
        assert d.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'CIKIS', 'warehouse_id': ana, 'qty': 50, 'reason': 'x'}).status_code == 400
        assert d.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'CIKIS', 'warehouse_id': ana, 'qty': 1}).status_code == 400   # açıklama
        ok(d.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'CIKIS', 'warehouse_id': ana, 'qty': 2, 'reason': 'Montaj'}))
        ok(d.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'TRANSFER', 'warehouse_id': ana, 'to_warehouse_id': w2, 'qty': 5}))
        ok(d.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'SAYIM', 'warehouse_id': w2, 'qty': 4}))
        ok(d.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'KULLANIM', 'warehouse_id': ana, 'qty': 1, 'reason': 'Test tezgâhı'}))
        ok(d.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'HURDA', 'warehouse_id': ana, 'qty': 1, 'reason': 'Sargı yanık'}))
        m = ok(d.get(f'/api/mrp/materials/{mot}'))
        assert {w['name']: w['qty'] for w in m['warehouses']} == {'Ana Depo': 11, 'Saha Deposu': 4} and m['stock'] == 15 and not m['critical']
        moves = ok(d.get(f'/api/mrp/materials/{mot}/moves'))
        assert [x['kind'] for x in moves] == ['HURDA', 'KULLANIM', 'SAYIM', 'TRANSFER', 'TRANSFER', 'CIKIS', 'GIRIS']
        docs = ok(d.get(f'/api/mrp/materials/{mot}/docs'))
        assert (docs[0]['number'], docs[0]['qty'], docs[0]['unit_price']) == ('ABC-2026-1', 20, 600) and d.get(f'/api/files/{docs[0]["file"]}').status_code == 200
        assert [x['kind'] for x in ok(d.get(f'/api/mrp/materials/{mot}/scrap'))] == ['HURDA', 'KULLANIM']
        # Resimler: tanımlama resmi ve galeri
        ok(d.post(f'/api/mrp/materials/{mot}/image', files={'file': ('on.png', PNG, 'image/png')}))
        ok(d.post(f'/api/mrp/materials/{mot}/images', files=[('files', ('a.png', PNG, 'image/png')), ('files', ('b.png', PNG, 'image/png'))]))
        m = ok(d.get(f'/api/mrp/materials/{mot}'))
        assert len(m['images']) == 2 and m['image'] and m['cover'] == m['image']
        ok(d.delete(f'/api/mrp/materials/{mot}/images/{m["images"][0]["id"]}'))
        lst = {x['code']: x for x in ok(d.get('/api/mrp/materials'))}
        assert lst['MT-2212']['stock'] == 15 and lst['HM-PLA']['type'] == 'HAMMADDE'
        assert d.delete(f'/api/mrp/warehouses/{w2}').status_code == 400   # hareketi var
    # Uçuş kaynaklı hurda: uçağın reçetesindeki malzemeler sorulur
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        cyz = next(p for p in ok(a.get('/api/products/options')) if p['code'] == 'CYZ')['id']
        ok(a.post(f'/api/products/{cyz}/recipe', json={'item_id': mot, 'qty': 4}))
        ok(a.post(f'/api/products/{cyz}/recipe', json={'item_id': pla, 'qty': 500}))
    with db.connect() as conn:
        oid = conn.execute("INSERT INTO orders (code, product_id, status, created_at, scrapped_at) VALUES ('S-1', ?, 'HURDA', ?, ?)",
                           (cyz, db.now(), db.now())).lastrowid
        conn.commit()
    with TestClient(app) as s:
        login(s, 'saha')
        assert any(n['key'] == 'material-review' for n in ok(s.get('/api/notifications'))['items'])
        r = ok(s.get(f'/api/mrp/aircraft/{oid}/materials'))
        assert {i['code']: i['qty'] for i in r['items']} == {'MT-2212': 4, 'HM-PLA': 500}
        assert s.post(f'/api/mrp/aircraft/{oid}/review', json={'items': [{'item_id': mot, 'qty': 1, 'result': 'SAGLAM'}]}).status_code == 400   # depo
        ok(s.post(f'/api/mrp/aircraft/{oid}/review', json={'items': [
            {'item_id': mot, 'qty': 3, 'result': 'HURDA'}, {'item_id': mot, 'qty': 1, 'result': 'SAGLAM', 'warehouse_id': ana},
            {'item_id': pla, 'qty': 500, 'result': 'HURDA'}]}))
        assert s.post(f'/api/mrp/aircraft/{oid}/review', json={'items': []}).status_code == 400   # bir kez
        assert not any(n['key'] == 'material-review' for n in ok(s.get('/api/notifications'))['items'])
        assert s.get('/api/mrp/materials').status_code == 200   # saha sorumlusu MRP'yi görür (stok yetkisi)
        assert s.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'GIRIS', 'warehouse_id': ana, 'qty': 1}).status_code == 403
    with TestClient(app) as d:
        login(d, 'depo')
        m = ok(d.get(f'/api/mrp/materials/{mot}'))
        assert m['stock'] == 16   # geri kazanılan 1 motor Ana Depo'ya girdi; hurda stoğu etkilemez
        sc = ok(d.get(f'/api/mrp/materials/{mot}/scrap'))
        assert [(x['kind'], x['source'], x['order_code']) for x in sc[:2]] == [('GERI_KAZANIM', 'UCUS', 'S-1'), ('HURDA', 'UCUS', 'S-1')]
    with TestClient(app) as r:   # MRP Sorumlusu: malzeme, depo, stok hareketi, yarı mamul; parça onayı (Onay Yönetimi) yok
        login(r, 'mrp')
        mods = set(ok(r.get('/api/auth/me'))['modules'])
        assert {'mrp', 'stock'} <= mods and 'warehouse' not in mods
        ok(r.post('/api/mrp/warehouses', json={'name': 'Yedek Depo'}))
        ok(r.post(f'/api/mrp/materials/{mot}/moves', json={'kind': 'GIRIS', 'warehouse_id': ana, 'qty': 2}))
        assert r.get('/api/warehouse/pending').status_code == 403
    with TestClient(app) as x:
        login(x, 'sek')
        assert x.get('/api/mrp/materials').status_code == 403
    print('Malzeme İhtiyaç Planlaması testleri geçti.')


if __name__ == '__main__':
    main()
