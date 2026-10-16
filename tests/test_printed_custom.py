"""Basılı custom ürün (Ürün Yönetimi'nden açılıp 'Basılıp stokta tutulur' işaretlenen, ör. KARBÜRATÖR KAPAĞI): üretim
çiziminde ürünün kendisi tek parçadır (2B üstten görünüm resmi zeminde), sipariş bu parçayla açılır, parçasız açılmış eski
siparişlere başlangıç eşitlemesiyle parça eklenir, baskı dosyası ürünün kendisinden gelir.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_printed_custom
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, production  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        pid = ok(a.post('/api/products', json={'code': 'KRB-KPK', 'name': 'KARBÜRATÖR KAPAĞI', 'type': 'YARI_MAMUL'}))['id']
        # basılı işaretlenmeden önce açılmış (parçasız) eski sipariş durumu: doğrudan oluşturulur
        with db.connect() as conn:
            conn.execute("UPDATE products SET orderable = 1, image = 'products/ornek.png', print_file = 'karbur_ABS_3h33m', "
                         "print_minutes = 213, gcode_file = 'gcode/karbur.gcode' WHERE id = ?", (pid,))
            conn.commit()
            p = db.row(conn.execute('SELECT * FROM products WHERE id = ?', (pid,)))
            old, _ = production.create_order(conn, 1, p, None, None, 'eski')
            conn.commit()
            assert conn.execute('SELECT COUNT(*) FROM order_parts WHERE order_id = ?', (old,)).fetchone()[0] == 0
        ok(a.put(f'/api/products/{pid}', json={'name': 'KARBÜRATÖR KAPAĞI', 'serial': 'KRB-KPK', 'code': 'KRB-KPK',
                                               'queue_prefix': 'KRBKPK', 'printed': True, 'active': True}))
        with db.connect() as conn:   # baskı alanları ürün sayfasından/G-code yüklemesinden gelir; testte doğrudan
            conn.execute("UPDATE products SET image = 'products/ornek.png', print_file = 'karbur_ABS_3h33m', print_minutes = 213 WHERE id = ?", (pid,))
            conn.commit()
        # üretim çizimi: tek parça (ürün kodu), resim, baskı dosyası ve süresi
        plane = ok(a.get(f'/api/products/{pid}/plane'))
        assert [x['id'] for x in plane['parts']] == ['KRB-KPK'], plane
        part = plane['parts'][0]
        assert part['image'] == 'products/ornek.png' and part['print_file'] == 'karbur_ABS_3h33m' and part['print_minutes'] == 213, part
        # yeni sipariş parçasıyla açılır
        o = ok(a.post('/api/orders', json={'product_id': pid}))[0]
        with db.connect() as conn:
            assert [r[0] for r in conn.execute('SELECT part_id FROM order_parts WHERE order_id = ?', (o['id'],))] == ['KRB-KPK']
            # başlangıç eşitlemesi eski siparişe parçayı ekler (yeniden çalıştırmak güvenli)
            assert production.sync_catalog_parts(conn) >= 1
            assert production.sync_catalog_parts(conn) == 0
            conn.commit()
            assert [r[0] for r in conn.execute('SELECT part_id FROM order_parts WHERE order_id = ?', (old,))] == ['KRB-KPK']
        d = ok(a.get(f"/api/orders/{o['id']}/parts/KRB-KPK"))
        assert d['state'] == 'BEKLIYOR' or d['state'], d
        # basılı değilse (salt custom) çizim boş kalır
        q = ok(a.post('/api/products', json={'code': 'DUZ-1', 'name': 'Düz custom', 'type': 'YARI_MAMUL'}))['id']
        assert ok(a.get(f'/api/products/{q}/plane'))['parts'] == []
    print('Basılı custom ürün testleri geçti.')


if __name__ == '__main__':
    main()
