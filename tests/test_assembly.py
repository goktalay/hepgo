"""3B Montaj: montaj meta verisi (G-code önizlemesi olmayan ortamda da çalışır) ve elle düzeltmelerin kaydı / yetkisi."""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a, TestClient(app) as b:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ok(a.post('/api/users', json={'username': 'pilot', 'full_name': 'Pilot', 'roles': ['Pilot'], 'password': 'Sifre-1234x'}))
        ok(b.post('/api/auth/login', json={'username': 'pilot', 'password': 'Sifre-1234x'}))
        m = ok(a.get('/api/products/assembly3d/caymaz'))
        assert m['overrides'] == {} and 'file' in m and isinstance(m['parts'], list)
        assert a.get('/api/products/assembly3d/yok').status_code == 404
        # Elle düzeltme: kaydet, oku, otomatiğe dön (null)
        r = ok(a.put('/api/products/assembly3d/caymaz/overrides', json={'parts': {'L17': {'p': [-100, 0, 12.345], 'r': [0, 450, -90]}, 'R1': {'p': [1, 2, 3], 'r': [0, 0, 0]}}}))
        assert r['overrides']['L17'] == {'p': [-100.0, 0.0, 12.3], 'r': [0.0, 90.0, 270.0]}, r
        assert ok(a.get('/api/products/assembly3d/caymaz'))['overrides']['R1']['p'] == [1.0, 2.0, 3.0]
        r = ok(a.put('/api/products/assembly3d/caymaz/overrides', json={'parts': {'R1': None}}))
        assert set(r['overrides']) == {'L17'}
        assert ok(a.get('/api/products/assembly3d/caymaz-v2'))['overrides'] == {}   # şema başına ayrı
        # Ürün yönetimi yetkisi olmayan düzenleyemez (görüntüleyebilir)
        assert b.put('/api/products/assembly3d/caymaz/overrides', json={'parts': {'L17': None}}).status_code == 403
        assert ok(b.get('/api/products/assembly3d/caymaz'))['overrides']['L17']
    print('3B montaj testleri geçti.')


if __name__ == '__main__':
    main()
