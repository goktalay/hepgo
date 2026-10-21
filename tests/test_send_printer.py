"""Yazıcıya Gönder: parçanın G-code'u seçili yazıcıya (Moonraker) yüklenir (arka planda, ilerleme izlenir) ve baskı
başlatılır; yükleme bitince parça o yazıcıda üretime alınır. Ağ olmadan yükleme taklit edilir.

Çalıştırma: .venv/bin/python -m tests.test_send_printer
"""
import os
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, printer_identity, printer_send  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    # Yüklemeyi taklit et: gerçek yazıcıya bağlanmadan baytları ilerlet
    def fake_upload(printer, path, filename, start_print, job):
        total = os.path.getsize(path)
        job['total'] = total
        step = max(1, total // 4)
        sent = 0
        while sent < total:
            sent = min(total, sent + step)
            job['sent'] = sent
            time.sleep(0.05)
        return {'item': {'path': filename}}
    printer_send._upload = fake_upload
    # Ağ yok: 10.0.0.9'daki cihaz K2-09'un MAC'ini bildiriyor (gönderim öncesi MAC doğrulaması)
    printer_identity.identify = lambda ip: {'ip': ip, 'reachable': True, 'arp_mac': {'10.0.0.9': 'FC:EE:28:00:00:09'}.get(ip), 'macs': [], 'hw': None}

    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        prn = ok(a.post('/api/printers', json={'name': 'K2-09', 'ip': '10.0.0.9', 'mac': 'fc-ee-28-00-00-09'}))['id']
        prn2 = ok(a.post('/api/printers', json={'name': 'K2-10', 'ip': '10.0.0.10', 'mac': 'FC:EE:28:00:00:10'}))['id']
        prn3 = ok(a.post('/api/printers', json={'name': 'K2-MACSIZ', 'ip': '10.0.0.11'}))['id']   # MAC'siz: gönderim yok
        cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
        oid = ok(a.post('/api/orders', json={'product_id': cyz['id'], 'quantity': 1}))[0]['id']
        part = ok(a.get(f'/api/orders/{oid}'))['parts'][0]['part_id']
        # G-code'u olmayan parça: 400
        assert a.post(f'/api/orders/{oid}/parts/{part}/send-to-printer', json={'printer_id': prn}).status_code == 400
        # parçanın G-code dosyasını tanımla + diske yaz
        gpath = db.config.UPLOAD_DIR / 'gcode' / 'test.gcode'
        gpath.parent.mkdir(parents=True, exist_ok=True)
        gpath.write_bytes(b'G28\n' * 100000)   # ~400 KB
        with db.connect() as conn:
            conn.execute("UPDATE products SET gcode_file = 'gcode/test.gcode' WHERE schema = ?", (f'part-{part}',))
            conn.commit()
        assert a.post(f'/api/orders/{oid}/parts/{part}/send-to-printer', json={'printer_id': 99999}).status_code == 404
        r = a.post(f'/api/orders/{oid}/parts/{part}/send-to-printer', json={'printer_id': prn3})
        assert r.status_code == 400 and 'MAC' in r.text, r.text
        # Gönder
        ok(a.post(f'/api/orders/{oid}/parts/{part}/send-to-printer', json={'printer_id': prn, 'at': '2026-09-25T09:00'}))
        # ilerleme akışı
        seen = set()
        for _ in range(80):
            st = ok(a.get(f'/api/orders/{oid}/parts/{part}/send-progress'))
            seen.add(st['status'])
            if st['status'] == 'done':
                break
            time.sleep(0.05)
        assert 'uploading' in seen and st['status'] == 'done' and st['percent'] == 100
        assert st['ip'] == '10.0.0.9' and st['mac'] == 'FC:EE:28:00:00:09' and st['verified_by'] == 'mac', st
        # parça o yazıcıda üretimde
        d = ok(a.get(f'/api/orders/{oid}/parts/{part}'))
        assert d['state'] == 'URETIMDE' and d['printer_name'] == 'K2-09' and d['started_at'].startswith('2026-09-25')
        assert any(e['event'] == 'YAZICIYA_GONDERILDI' for e in d['events'])
        # yazıcı meşgul göründü mü (current_part_id)
        pr = next(p for p in ok(a.get('/api/printers')) if p['id'] == prn)
        assert pr['current_part'] == part
        # aynı yazıcı meşgul: başka parça gönderilemez
        part2 = ok(a.get(f'/api/orders/{oid}'))['parts'][1]['part_id']
        with db.connect() as conn:
            conn.execute("UPDATE products SET gcode_file = 'gcode/test.gcode' WHERE schema = ?", (f'part-{part2}',))
            conn.commit()
        assert a.post(f'/api/orders/{oid}/parts/{part2}/send-to-printer', json={'printer_id': prn}).status_code == 409
        # zaten üretimdeki parça tekrar gönderilemez
        assert a.post(f'/api/orders/{oid}/parts/{part}/send-to-printer', json={'printer_id': prn2}).status_code == 400
    print('Yazıcıya gönderme testleri geçti.')


if __name__ == '__main__':
    main()
