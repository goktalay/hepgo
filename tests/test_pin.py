"""PIN ile giriş ve bu cihazdaki hesaplar: şifreyle girişte cihaz jetonu verilir; jetonla hesap listelenir; PIN açılır /
değiştirilir / kapanır (şifre ile); PIN ile giriş; hatalı PIN sınırı aşılınca cihaz jetonu silinir.

Çalıştırma: .venv/bin/python -m tests.test_pin
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
        ok(a.post('/api/users', json={'username': 'ali', 'full_name': 'Ali', 'roles': ['Pilot'], 'password': 'sifre-1234'}))
    with TestClient(app) as u:
        tok = ok(u.post('/api/auth/login', json={'username': 'ali', 'password': 'sifre-1234'}))['device_token']
        assert tok and not ok(u.get('/api/auth/me'))['has_pin']
        assert ok(u.post('/api/auth/devices', json={'tokens': [tok, 'sahte']})) == [
            {'token': tok, 'id': 2, 'username': 'ali', 'full_name': 'Ali', 'has_pin': False}]
        assert u.put('/api/auth/pin', json={'password': 'yanlis', 'pin': '4826'}).status_code == 400
        assert u.put('/api/auth/pin', json={'password': 'sifre-1234', 'pin': '12a4'}).status_code == 400
        assert u.put('/api/auth/pin', json={'password': 'sifre-1234', 'pin': '1234'}).status_code == 400   # kolay PIN
        assert ok(u.put('/api/auth/pin', json={'password': 'sifre-1234', 'pin': '4826'}))['has_pin']
        assert ok(u.get('/api/auth/me'))['has_pin']
        ok(u.post('/api/auth/logout'))
        assert ok(u.post('/api/auth/devices', json={'tokens': [tok]}))[0]['has_pin']
        assert u.post('/api/auth/login-pin', json={'token': 'sahte', 'pin': '4826'}).status_code == 401
        assert u.post('/api/auth/login-pin', json={'token': tok, 'pin': '0000'}).status_code == 400
        ok(u.post('/api/auth/login-pin', json={'token': tok, 'pin': '4826'}))
        assert ok(u.get('/api/auth/me'))['username'] == 'ali'
        # PIN kapatma
        ok(u.put('/api/auth/pin', json={'password': 'sifre-1234'}))
        assert u.post('/api/auth/login-pin', json={'token': tok, 'pin': '4826'}).status_code == 401
        ok(u.put('/api/auth/pin', json={'password': 'sifre-1234', 'pin': '4826'}))
        ok(u.post('/api/auth/logout'))
        # hatalı PIN sınırı: cihaz jetonu silinir, şifre gerekir
        codes = [u.post('/api/auth/login-pin', json={'token': tok, 'pin': '9990'}).status_code for _ in range(8)]
        assert 401 in codes or 429 in codes, codes
        assert ok(u.post('/api/auth/devices', json={'tokens': [tok]})) == []
    print('PIN ve cihaz hesapları testleri geçti.')


if __name__ == '__main__':
    main()
