"""CAYMAZ V2 testi: V2 şeması (K02/K03/KAPAK7 yok, K08/K09 var, 15 parça -V2), ürün ağacı (V2 yarı mamulleri, V1 ile
ortak parça yedekleri, yalnızca V2'de olan parçalar), montaj sarfı kullanımı, sipariş ve montaj bölümleri.

Çalıştırma: .venv/bin/python -m tests.test_v2
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, plane, plane_v2, semis, spares  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    v1, v2 = set(plane.part_ids()), set(plane_v2.part_ids())
    assert len(v2) == 63 and not ({'K02', 'K03', 'KAPAK7'} & v2) and {'K08', 'K09'} <= v2
    assert {p for p in v2 - v1} == {f'{p}-V2' for p in plane_v2.CHANGED} | {'K08', 'K09'}
    assert v1 - v2 == set(plane_v2.CHANGED) | {'K02', 'K03', 'KAPAK7'}

    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        before = len(ok(a.get('/api/products')))
        with db.connect() as conn:
            mid = semis.create_v2(conn)
            assert semis.create_v2(conn) == mid   # ikinci çalıştırma yeni kayıt açmaz
        products = {p['code']: p for p in ok(a.get('/api/products'))}
        # yeni ürünler: mamul + 4 yarı mamul + 17 yeni parça yedeği (15 V2 + K08 + K09)
        assert len(products) == before + 1 + 4 + 17
        m = products['CYZ2']
        assert (m['name'], m['serial'], m['type'], m['orderable'], m['part_count']) == ('CAYMAZ V2', 'CYZ-S2', 'MAMUL', 1, 63)
        assert m['description'].startswith('Benzin deposunu rahat yerleştirmek için kapakları büyüttük')
        assert products['K08']['parent']['code'] == 'GVD2' and products['L18-V2']['parent']['code'] == 'SLK2'
        assert not products['K08']['orderable'] and products['K08']['stock'] == 0
        assert [x['code'] for x in products['L17']['used_in']] == ['SLK', 'SLK2']   # ortak parça iki modelde
        assert [x['code'] for x in products['L18']['used_in']] == ['SLK'] and [x['code'] for x in products['L18-V2']['used_in']] == ['SLK2']

        tree = ok(a.get(f'/api/products/{m["id"]}/tree'))
        assert [n['code'] for n in tree['children']] == ['SLK2', 'SGK2', 'GVD2', 'ELK2']
        parts = {n['code']: {c['code'] for c in n['children'] if c['part_spare']} for n in tree['children']}
        assert [len(parts[c]) for c in ('SLK2', 'SGK2', 'GVD2', 'ELK2')] == [22, 22, 17, 2]
        assert 'L17' in parts['SLK2'] and 'L18-V2' in parts['SLK2'] and 'L18' not in parts['SLK2']   # ortak + V2
        assert {'K08', 'K09', '05-V2', 'KAPAK5'} <= parts['GVD2'] and not ({'K02', 'K03', 'KAPAK7', '05'} & parts['GVD2'])
        sarf = {n['code']: {c['code']: c['qty'] for c in n['children'] if not c['part_spare']} for n in tree['children']}
        assert sarf == {'SLK2': {'BBK': 27, 'KBK': 3}, 'SGK2': {'BBK': 27, 'KBK': 3}, 'GVD2': {'KMH': 1, 'BBK': 14}, 'ELK2': {}}
        with db.connect() as conn:
            assert {sid: q for sid, q in spares.per_product(conn, m['id']).items()} == {
                products['KMH']['id']: 1, products['BBK']['id']: 68, products['KBK']['id']: 6}
        # V1 ağacı değişmedi: ortak parça (L17) iki modelin altında da görünür, stok tektir
        t1 = ok(a.get(f'/api/products/{products["CYZ"]["id"]}/tree'))
        v1parts = {n['code']: {c['code'] for c in n['children'] if c['part_spare']} for n in t1['children']}
        assert 'L17' in v1parts['SLK'] and 'L18' in v1parts['SLK'] and [len(v1parts[c]) for c in ('SLK', 'SGK', 'GVD', 'ELK')] == [22, 22, 18, 2]

        # Sipariş: 63 parça; montaj bölümleri ve elektronik montaj V1 ile aynı
        o = ok(a.post('/api/orders', json={'product_id': m['id'], 'note': 'CAYMAZ V2 ilk sipariş'}))[0]
        d = ok(a.get(f'/api/orders/{o["id"]}'))
        assert len(d['parts']) == 63 and d['product_name'] == 'CAYMAZ V2' and d['status'] == 'SIPARIS'
        assert {'K08', 'K09', '05-V2'} <= {p['part_id'] for p in d['parts']}
        assert set(d['assembly']['sections']) == {'SOL_KANAT', 'SAG_KANAT', 'GOVDE'}
        assert [e['part_id'] for e in d['assembly']['electronics']] == ['EK', 'K04']
        plane_json = ok(a.get(f'/api/products/{m["id"]}/plane'))
        k08 = next(p for p in plane_json['parts'] if p['id'] == 'K08')
        assert k08['layer'] == 'cover' and k08['section'] == 'GOVDE' and k08['hosts'] == ['05-V2', '04-V2']
        # Parça yedeği sayfası (V2 parçası) çizimi açılır
        assert [p['id'] for p in ok(a.get(f'/api/products/{products["K09"]["id"]}/plane'))['parts']] == ['K09']
    print('CAYMAZ V2 testleri geçti.')


if __name__ == '__main__':
    main()
