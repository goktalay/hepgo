"""Yazıcı odası yerleşimi (Yazıcı Yönetimi → 3B görünüm): yeni yazıcı ilk boş rafa konur (sol alt, sol üst, sağ alt,
sağ üst; ad numarasına göre), yer değiştirme, çakışma kontrolü ve yetki.

Çalıştırma: .venv/bin/python -m tests.test_printer_layout
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
        for i in range(1, 18):
            ok(a.post('/api/printers', json={'name': str(i), 'ip': f'10.0.0.{i}'}))
        pos = {p['name']: (p['rack_side'], p['rack_level'], p['rack_slot']) for p in ok(a.get('/api/printers'))}
        assert pos['1'] == ('L', 1, 1) and pos['15'] == ('L', 1, 15) and pos['16'] == ('L', 2, 1) and pos['17'] == ('L', 2, 2)
        ids = {p['name']: p['id'] for p in ok(a.get('/api/printers'))}
        # Yer değiştirme: 1 ↔ 16
        ok(a.put('/api/printers/layout', json={'items': [{'id': ids['1'], 'side': 'L', 'level': 2, 'slot': 1},
                                                         {'id': ids['16'], 'side': 'L', 'level': 1, 'slot': 1}]}))
        pos = {p['name']: (p['rack_side'], p['rack_level'], p['rack_slot']) for p in ok(a.get('/api/printers'))}
        assert pos['1'] == ('L', 2, 1) and pos['16'] == ('L', 1, 1)
        # Boş rafa taşıma: sağ alt 3. sıra
        ok(a.put('/api/printers/layout', json={'items': [{'id': ids['2'], 'side': 'R', 'level': 1, 'slot': 3}]}))
        assert next(p for p in ok(a.get('/api/printers')) if p['name'] == '2')['rack_side'] == 'R'
        # Dolu rafa tek başına taşınamaz; aynı yere iki yazıcı konamaz; geçersiz taraf / kat
        assert a.put('/api/printers/layout', json={'items': [{'id': ids['3'], 'side': 'L', 'level': 1, 'slot': 4}]}).status_code == 400
        assert a.put('/api/printers/layout', json={'items': [{'id': ids['3'], 'side': 'R', 'level': 2, 'slot': 1},
                                                             {'id': ids['4'], 'side': 'R', 'level': 2, 'slot': 1}]}).status_code == 400
        assert a.put('/api/printers/layout', json={'items': [{'id': ids['3'], 'side': 'X', 'level': 1, 'slot': 1}]}).status_code == 400
        assert a.put('/api/printers/layout', json={'items': [{'id': ids['3'], 'side': 'R', 'level': 3, 'slot': 1}]}).status_code == 400
        # Yeni yazıcı ilk boş yere: sol alt 2. sıra (2 numara sağa taşındı)
        ok(a.post('/api/printers', json={'name': '18', 'ip': '10.0.0.18'}))
        assert next(p for p in ok(a.get('/api/printers')) if p['name'] == '18')['rack_slot'] == 2
        ok(a.post('/api/users', json={'username': 'uret', 'full_name': 'Üretim', 'roles': ['Montaj Personeli'], 'password': 'sifre-1234'}))
    with TestClient(app) as u:   # yalnızca üretim modülü olan (montaj personeli) odayı görür, yerleşimi değiştiremez
        ok(u.post('/api/auth/login', json={'username': 'uret', 'password': 'sifre-1234'}))
        assert ok(u.get('/api/printers'))[0]['rack_side']
        assert u.put('/api/printers/layout', json={'items': [{'id': ids['3'], 'side': 'R', 'level': 2, 'slot': 9}]}).status_code == 403
    print('Yazıcı odası yerleşimi testleri geçti.')


if __name__ == '__main__':
    main()
