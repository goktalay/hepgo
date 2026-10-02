"""İlk girişte şifre değişikliği: yöneticinin oluşturduğu / şifresini sıfırladığı kullanıcı, şifresini değiştirene kadar
yalnızca oturum ve şifre uçlarını kullanabilir (428); değiştirince serbest kalır. Yönetici kendi şifresini sıfırlarsa zorunluluk yok.

Çalıştırma: .venv/bin/python -m tests.test_force_password
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='1',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        assert ok(a.get('/api/auth/me'))['must_change_password']          # .env'deki ilk yönetici de değiştirir
        assert a.get('/api/users').status_code == 428
        ok(a.post('/api/auth/password', json={'current': 'admin-sifre-1', 'new': 'yeni-yonetici-1'}))
        assert not ok(a.get('/api/auth/me'))['must_change_password']
        uid = ok(a.post('/api/users', json={'username': 'ali', 'full_name': 'Ali', 'roles': ['Pilot'], 'password': 'verilen-1234'}))['id']
    with TestClient(app) as u:
        ok(u.post('/api/auth/login', json={'username': 'ali', 'password': 'verilen-1234'}))
        assert ok(u.get('/api/auth/me'))['must_change_password']
        for url in ('/api/notifications', '/api/dashboard/widgets', '/api/meetings', '/api/people'):
            assert u.get(url).status_code == 428, url
        assert u.post('/api/auth/password', json={'current': 'verilen-1234', 'new': 'verilen-1234'}).status_code == 400   # aynı şifre
        assert u.post('/api/auth/password', json={'current': 'yanlis', 'new': 'kendi-sifrem-1'}).status_code == 400
        ok(u.post('/api/auth/password', json={'current': 'verilen-1234', 'new': 'kendi-sifrem-1'}))
        ok(u.get('/api/notifications'))
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'yeni-yonetici-1'}))
        me = ok(a.get('/api/auth/me'))
        ok(a.put(f'/api/users/{uid}', json={'username': 'ali', 'full_name': 'Ali', 'roles': ['Pilot'], 'active': True, 'password': 'sifirla-5678'}))
        ok(a.put(f'/api/users/{me["id"]}', json={'username': 'admin@test', 'full_name': me['full_name'], 'roles': me['roles'], 'active': True, 'password': 'yonetici-yeni-2'}))
    with TestClient(app) as a:   # şifre sıfırlanınca oturumlar kapanır; yeniden girilir
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'yonetici-yeni-2'}))
        assert not ok(a.get('/api/auth/me'))['must_change_password']       # kendi şifresini sıfırlayan yönetici serbest
    with TestClient(app) as u:
        ok(u.post('/api/auth/login', json={'username': 'ali', 'password': 'sifirla-5678'}))
        assert ok(u.get('/api/auth/me'))['must_change_password'] and u.get('/api/notifications').status_code == 428
    print('İlk girişte şifre değişikliği testleri geçti.')


if __name__ == '__main__':
    main()
