"""Yedek parça testi: başlangıç stokları, yedek parça siparişi (baskı) → depo onayı → stoğa giriş (baskı adedi),
CAYMAZ montajı tamamlanınca stoktan düşüm, düşük stok bildirimi, sayım düzeltmesi ve sahaya giden uçak listesi.

Çalıştırma: .venv/bin/python -m tests.test_spares
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p='sifre-1234'):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def notes(c):
    return {n['key']: n for n in ok(c.get('/api/notifications'))['items']}


def main():
    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        mk = lambda u, roles: ok(admin.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,
                                                                'password': 'sifre-1234'}))['id']
        mk('uyon', ['Üretim Yöneticisi'])
        depocu = mk('depocu', ['Depo Yöneticisi'])
        m1, m2 = mk('m1', ['Montaj Personeli']), mk('m2', ['Montaj Personeli'])
        el = mk('el', ['Elektronik Personeli'])
        mk('saha', ['Saha Sorumlusu'])
        printer = ok(admin.post('/api/printers', json={'name': 'K2-01', 'ip': '10.0.0.1'}))['id']

        # ---- Başlangıç: üç yedek parça, stokları ve CAYMAZ başına kullanımları
        products = ok(admin.get('/api/products'))
        sp = {p['code']: p for p in products if p['type'] == 'YEDEK_PARCA' and not p['part_spare']}
        assert {c: (p['stock'], p['per_print'], sum(u['qty'] for u in p['usages']), p['part_count']) for c, p in sp.items()} == {
            'KMH': (1, 1, 1, 1), 'BBK': (183, 12, 68, 1), 'KBK': (38, 12, 6, 1)}
        cyz = next(p for p in products if p['code'] == 'CYZ')
        assert cyz['type'] == 'MAMUL' and {x['code']: x['qty'] for x in cyz['spares']} == {'KMH': 1, 'BBK': 68, 'KBK': 6}
        # Yarı mamuller: CAYMAZ'ın dört ana yapısı, parçaları CAYMAZ'ın parçalarını tam olarak böler; sipariş verilemez
        semi = {p['code']: p for p in products if p['type'] == 'YARI_MAMUL'}
        assert {c: (p['name'], p['part_count'], p['parent']['code']) for c, p in semi.items()} == {
            'SLK': ('Sol Kanat', 22, 'CYZ'), 'SGK': ('Sağ Kanat', 22, 'CYZ'), 'GVD': ('Gövde', 18, 'CYZ'), 'ELK': ('Elektronik', 2, 'CYZ')}
        assert [s['code'] for s in cyz['semis']] == ['SLK', 'SGK', 'GVD', 'ELK']
        ids = [set(x['id'] for x in ok(admin.get(f'/api/products/{p["id"]}/plane'))['parts']) for p in semi.values()]
        assert sum(len(i) for i in ids) == len(set().union(*ids)) == cyz['part_count']
        assert ids[3] == {'EK', 'K04'}
        assert admin.post('/api/orders', json={'product_id': semi['SLK']['id']}).status_code == 400
        assert all(not p['orderable'] for p in semi.values())
        # yarı mamul sipariş verilebilir yapılamaz
        assert admin.put(f'/api/products/{semi["SLK"]["id"]}', json={
            'name': 'Sol Kanat', 'serial': 'SLK-YM', 'code': 'SLK', 'queue_prefix': 'SLK', 'orderable': True}).status_code == 400
        # Ürün ağacı: her CAYMAZ parçası, ait olduğu yarı mamulün altında bir yedek parça
        parts = {p['code']: p for p in products if p.get('part_spare')}
        assert len(parts) == 64 and parts['L18']['parent']['code'] == 'SLK' and parts['EK']['parent']['code'] == 'ELK'
        assert parts['L18']['stock'] == 0 and not parts['L18']['orderable']   # parça yedekleri mamul siparişiyle üretilir
        assert all(not p['orderable'] for p in parts.values()) and all(p['orderable'] for p in sp.values())
        assert admin.post('/api/orders', json={'product_id': parts['L18']['id']}).status_code == 400
        ok(admin.get(f'/api/products/{parts["EK"]["id"]}/plane'))   # parça şeması ortak kataloğu değiştirmemeli
        assert {x['id'] for x in ok(admin.get(f'/api/products/{semi["ELK"]["id"]}/plane'))['parts']} == {'EK', 'K04'}
        tree = ok(admin.get(f'/api/products/{cyz["id"]}/tree'))
        assert [n['code'] for n in tree['children']] == ['SLK', 'SGK', 'GVD', 'ELK']
        assert [len([c for c in n['children'] if c['part_spare']]) for n in tree['children']] == [22, 22, 18, 2]
        assert tree['children'][0]['section'] == 'SOL_KANAT'
        assert {c['code'] for c in tree['children'][3]['children']} == {'EK', 'K04'}
        # Montaj sarfı: yarı mamul başına adet (BBK: Sol 27, Sağ 27, Gövde 14; KBK: Sol 3, Sağ 3; KMH: Gövde 1)
        sarf = {n['code']: {c['code']: c['qty'] for c in n['children'] if not c['part_spare']} for n in tree['children']}
        assert sarf == {'SLK': {'BBK': 27, 'KBK': 3}, 'SGK': {'BBK': 27, 'KBK': 3}, 'GVD': {'KMH': 1, 'BBK': 14}, 'ELK': {}}
        # kullanım düzenleme: yarı mamul başına; yarı mamul olmayan ürüne kullanım girilemez
        kbk_edit = {'name': 'Küçük Bağlantı Klipsi', 'serial': 'KBK-YP', 'code': 'KBK', 'queue_prefix': 'KBK', 'per_print': 12}
        assert admin.put(f'/api/products/{sp["KBK"]["id"]}', json={**kbk_edit, 'usages': {str(cyz['id']): 5}}).status_code == 400
        ok(admin.put(f'/api/products/{sp["KBK"]["id"]}', json={**kbk_edit, 'usages': {str(semi['GVD']['id']): 2}}))
        assert {u['parent_name']: u['qty'] for u in ok(admin.get(f'/api/products/{sp["KBK"]["id"]}'))['usages']} == {
            'Sol Kanat': 3, 'Sağ Kanat': 3, 'Gövde': 2}
        ok(admin.put(f'/api/products/{sp["KBK"]["id"]}', json={**kbk_edit, 'usages': {str(semi['GVD']['id']): 0}}))
        assert sum(u['qty'] for u in ok(admin.get(f'/api/products/{sp["KBK"]["id"]}'))['usages']) == 6
        # parça yedeğinin kodu kilitli
        ok(admin.put(f'/api/products/{parts["L18"]["id"]}', json={'name': 'Kanat L18', 'serial': 'L18-YP', 'code': 'ZZZ',
                                                                   'queue_prefix': 'ZZ', 'per_print': 1}))
        assert ok(admin.get(f'/api/products/{parts["L18"]["id"]}'))['code'] == 'L18'
        # Sipariş verilebilir ayarı: kapatılan üründen sipariş açılamaz
        kmh_edit = {'name': 'Kamera Holder', 'serial': 'KMH-YP', 'code': 'KMH', 'queue_prefix': 'KMH'}
        ok(admin.put(f'/api/products/{sp["KMH"]["id"]}', json={**kmh_edit, 'orderable': False}))
        assert admin.post('/api/orders', json={'product_id': sp['KMH']['id']}).status_code == 400
        ok(admin.put(f'/api/products/{sp["KMH"]["id"]}', json={**kmh_edit, 'orderable': True}))
        # Parça yedeği siparişi (yönetici sipariş verilebilir yaparsa): tek parça basılır, depo onayında stoğa 1 girer
        ok(admin.put(f'/api/products/{parts["L18"]["id"]}', json={'name': 'Kanat L18', 'serial': 'L18-YP', 'code': 'L18',
                                                                   'queue_prefix': 'YP', 'per_print': 1, 'orderable': True}))
        po = ok(admin.post('/api/orders', json={'product_id': parts['L18']['id']}))[0]
        assert [x['part_id'] for x in ok(admin.get(f'/api/orders/{po["id"]}'))['parts']] == ['L18']
        with db.connect() as conn:
            conn.execute("UPDATE order_parts SET state = 'DEPO', approved_at = ?, finished_at = ? WHERE order_id = ?",
                         (db.now(), db.now(), po['id']))
            from app.production import recompute
            assert recompute(conn, po['id']) == 'TAMAMLANDI'
        assert ok(admin.get(f'/api/products/{parts["L18"]["id"]}'))['stock'] == 1
        plane = ok(admin.get(f'/api/products/{sp["BBK"]["id"]}/plane'))
        assert [p['id'] for p in plane['parts']] == ['BBK'] and len(plane['parts'][0]['shapes']) == 12   # 12'li baskı

    # ---- Yedek parça siparişi: 1 baskı → depo onayı → 12 adet stoğa girer
    with TestClient(app) as c:
        login(c, 'uyon')
        o = ok(c.post('/api/orders', json={'product_id': sp['BBK']['id'], 'quantity': 1}))[0]
        order = ok(c.get(f'/api/orders/{o["id"]}'))
        assert [p['part_id'] for p in order['parts']] == ['BBK'] and order['product_type'] == 'YEDEK_PARCA'
        ok(c.post(f'/api/orders/{o["id"]}/parts/BBK/start', json={'printer_id': printer}))
        ok(c.post(f'/api/orders/{o["id"]}/parts/BBK/finish', json={'warehouse_user_id': depocu}))
        assert ok(c.get(f'/api/orders/{o["id"]}'))['status'] == 'DEPO'
    with TestClient(app) as d:
        login(d, 'depocu')
        pid = ok(d.get('/api/warehouse/pending'))[0]['id']
        ok(d.post('/api/warehouse/approve', json={'ids': [pid]}))
        order = ok(d.get(f'/api/stock'))   # depocu stok ekranı
        summary = {x['code']: x for x in ok(d.get('/api/products/spares/summary'))}
        assert summary['BBK']['stock'] == 195 and summary['BBK']['enough_for'] == 2
        moves = ok(d.get(f'/api/products/{sp["BBK"]["id"]}/moves'))
        assert moves[0]['qty'] == 12 and moves[0]['order_code'] == o['code'] and moves[0]['reason'].startswith('Üretim')
        # Sayım düzeltmesi: depo yöneticisi yapabilir
        assert d.post(f'/api/products/{sp["KBK"]["id"]}/adjust', json={'qty': 0, 'reason': 'x'}).status_code == 400
        assert ok(d.post(f'/api/products/{sp["KBK"]["id"]}/adjust', json={'qty': -2, 'reason': 'Sayım farkı'}))['stock'] == 36
    with TestClient(app) as c:
        login(c, 'uyon')
        assert ok(c.get(f'/api/orders/{o["id"]}'))['status'] == 'TAMAMLANDI'
        assert c.post(f'/api/products/{sp["KBK"]["id"]}/adjust', json={'qty': 5, 'reason': 'x'}).status_code == 403
        assert notes(c).get('spares-low') is None

    # ---- CAYMAZ montajı tamamlanınca (birleştirme → kalibrasyon) yedek parçalar stoktan düşer
    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        oid = ok(admin.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']
        with db.connect() as conn:
            conn.execute("UPDATE order_parts SET state = 'DEPO', approved_at = ?, finished_at = ? WHERE order_id = ?",
                         (db.now(), db.now(), oid))
            from app.production import recompute
            assert recompute(conn, oid) == 'MONTAJ'
        for sec in ('SOL_KANAT', 'SAG_KANAT', 'GOVDE'):
            ok(admin.post(f'/api/orders/{oid}/assembly/{sec}', json={'staff_ids': [m1, m2]}))
        for part in ('EK', 'K04'):
            ok(admin.post(f'/api/orders/{oid}/electronics/{part}', json={'staff_ids': [el]}))
        before = {x['code']: x['stock'] for x in ok(admin.get('/api/products/spares/summary')) if x['per_aircraft']}
        assert before == {'KMH': 1, 'BBK': 195, 'KBK': 36}
        ok(admin.post(f'/api/orders/{oid}/final', json={'staff_ids': [m1, m2], 'checklist': {'wings': True, 'electronics': True}}))
        r = ok(admin.post(f'/api/orders/{oid}/covers', json={'staff_ids': [m1]}))
        assert r['status'] == 'KALIBRASYON'
        after = {x['code']: x['stock'] for x in ok(admin.get('/api/products/spares/summary')) if x['per_aircraft']}
        assert after == {'KMH': 0, 'BBK': 127, 'KBK': 30}
        assert ok(admin.get(f'/api/products/{parts["L18"]["id"]}'))['stock'] == 1   # parça yedekleri montajda düşmez
        mv = ok(admin.get(f'/api/products/{sp["BBK"]["id"]}/moves'))[0]
        assert mv['qty'] == -68 and mv['reason'].startswith('Montaj')
    with TestClient(app) as c:
        login(c, 'uyon')   # kamera tutucu bitti: bir uçağa yetmiyor
        n = notes(c)['spares-low']
        assert n['names'] == ['KMH: stok 0, gereken 1'] and n['href'] == '#/stock'
    with TestClient(app) as s:
        login(s, 'saha')   # yedek parça siparişi sahaya götürülebilecek uçak listesinde yok
        assert o['id'] not in {a['id'] for a in ok(s.get('/api/field/available-aircraft'))}
    print('Yedek parça testleri geçti.')


if __name__ == '__main__':
    main()
