"""Sipariş detayı (Sipariş Yönetimi): aşamalar birbirine bağlı kartlar için; her sipariş tek üretim.

Çalıştırma: .venv/bin/python -m tests.test_order_detail
"""
import json
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


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        prods = {p['code']: p for p in ok(a.get('/api/products'))}
        cyz = prods['CYZ']
        r = a.post('/api/orders', json={'product_id': cyz['id'], 'quantity': 2})
        assert r.status_code == 400 and 'tek üretim' in r.json()['detail']
        created = ok(a.post('/api/orders', json={'product_id': cyz['id'], 'note': 'Deneme'}))
        assert len(created) == 1
        oid = created[0]['id']
        t = ok(a.get(f'/api/orders/{oid}/timeline'))
        keys = [s['key'] for s in t['stages']]
        assert keys == ['SIPARIS', 'URETIM', 'DEPO', 'MONTAJ', 'KALIBRASYON', 'SAHA_DEPO', 'SAHA', 'UCUS']
        st = {s['key']: s for s in t['stages']}
        assert st['SIPARIS']['state'] == 'done' and 'Açıklama: Deneme' in st['SIPARIS']['lines']
        assert st['URETIM']['state'] == 'todo' and st['MONTAJ']['state'] == 'todo'
        assert [x['title'] for x in st['MONTAJ']['steps']][-2:] == ['Birleştirme montajı', 'Kapak montajı']
        # Üretim başlar, bir kısım depoda: üretim ve depo sürüyor
        pid = ok(a.post('/api/printers', json={'name': 'P1', 'ip': '10.0.0.1'}))['id']
        ok(a.post(f'/api/orders/{oid}/parts/L1/start', json={'printer_id': pid}))
        with db.connect() as c:
            c.execute("UPDATE order_parts SET state = 'DEPO', finished_at = ?, approved_at = ? WHERE order_id = ? AND part_id = 'L2'",
                      (db.now(), db.now(), oid))
        st = {s['key']: s for s in ok(a.get(f'/api/orders/{oid}/timeline'))['stages']}
        assert st['URETIM']['state'] == 'current' and st['DEPO']['state'] == 'current'
        assert '1 / 64 parça depoya alındı' in st['DEPO']['lines']
        # Uçuş: saha görevindeki uçuşun raporu (uçtu) Uçuş kartında
        with db.connect() as c:
            c.execute("UPDATE order_parts SET state = 'MONTAJ', finished_at = ?, approved_at = ? WHERE order_id = ?", (db.now(), db.now(), oid))
            c.execute("UPDATE orders SET status = 'TAMAMLANDI', queue_no = 'CYZ-0001', completed_at = ? WHERE id = ?", (db.now(), oid))
            tid = c.execute("INSERT INTO field_tasks (code, status, created_at, started_at) VALUES ('GRV-0001', 'GOREVDE', ?, ?)",
                            (db.now(), db.now())).lastrowid
            fid = c.execute('INSERT INTO field_flights (task_id, order_id) VALUES (?, ?)', (tid, oid)).lastrowid
            c.execute('''INSERT INTO flight_logs (task_id, flight_id, file, file_name, size, status, analysis, uploaded_at)
                         VALUES (?,?,?,?,?,?,?,?)''', (tid, fid, 'x.bin', 'x.bin', 1, 'TAMAM',
                                                       json.dumps({'summary': {'flight_s': 1800, 'distance_m': 76000, 'alt_max': 523,
                                                                               'takeoff_utc': '2026-09-21T14:07:40+00:00'}}), db.now()))
        st = {s['key']: s for s in ok(a.get(f'/api/orders/{oid}/timeline'))['stages']}
        assert st['SAHA_DEPO']['state'] == 'done' and 'Kuyruk no: CYZ-0001' in st['SAHA_DEPO']['lines']
        assert st['SAHA']['state'] == 'current' and st['SAHA']['steps'][0]['task_id'] == tid
        assert st['UCUS']['state'] == 'done' and st['UCUS']['steps'][0]['flight_id'] == fid
        assert st['UCUS']['lines'][0] == 'GRV-0001: 30 dk uçtu · 76.0 km · en yüksek 523 m'
        # Yedek parça siparişi: Sipariş → Üretim → Depo → Stok
        sp = ok(a.post('/api/orders', json={'product_id': prods['BBK']['id']}))[0]['id']
        assert [s['key'] for s in ok(a.get(f'/api/orders/{sp}/timeline'))['stages']] == ['SIPARIS', 'URETIM', 'DEPO', 'STOK']
        assert a.get('/api/orders/99999/timeline').status_code == 404
    print('Sipariş detayı testleri geçti.')


if __name__ == '__main__':
    main()
