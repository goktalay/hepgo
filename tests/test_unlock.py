"""Bekleme ekranı kilidi: /api/auth/unlock oturumdaki kullanıcının şifresini doğrular; hatalı denemeler giriş denemesi
sayılır ve sınır aşılınca oturum kapatılır.

Çalıştırma: .venv/bin/python -m tests.test_unlock
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def main():
    with TestClient(app) as a:
        assert a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}).status_code == 200
        assert a.post('/api/users', json={'username': 'ali', 'full_name': 'Ali', 'roles': ['Pilot'], 'password': 'sifre-1234'}).status_code == 200
    with TestClient(app) as u:
        assert u.post('/api/auth/unlock', json={'password': 'x'}).status_code == 401          # oturum yok
        assert u.post('/api/auth/login', json={'username': 'ali', 'password': 'sifre-1234'}).status_code == 200
        assert u.post('/api/auth/unlock', json={'password': 'sifre-1234'}).json()['ok']
        assert u.post('/api/auth/unlock', json={'pin': '4826'}).status_code == 400                   # PIN kapalı
        assert u.put('/api/auth/pin', json={'password': 'sifre-1234', 'pin': '4826'}).status_code == 200
        assert u.post('/api/auth/unlock', json={'pin': '4826'}).json()['ok']                         # PIN ile açılır
        r = u.post('/api/auth/unlock', json={'pin': '1357'})
        assert r.status_code == 400 and r.json()['detail'] == 'PIN hatalı'
        assert u.post('/api/auth/unlock', json={'password': 'sifre-1234'}).json()['ok']             # şifreyle de açılır
        r = u.post('/api/auth/unlock', json={'password': 'yanlis'})
        assert r.status_code == 400 and 'hatalı' in r.json()['detail']
        codes = [u.post('/api/auth/unlock', json={'password': 'yanlis'}).status_code for _ in range(10)]
        assert 401 in codes                                                                    # sınır aşıldı: oturum kapandı
        assert u.get('/api/auth/me').status_code == 401
    print('Bekleme ekranı kilidi testleri geçti.')


if __name__ == '__main__':
    main()
