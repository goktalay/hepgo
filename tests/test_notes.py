"""Kişisel notlar: yalnız sahibi; oluştur / düzenle / renk / ekrana iğnele (pin_x,pin_y) / sil; başkasının notuna erişilemez.
Çalıştırma: .venv/bin/python -m tests.test_notes
"""
import os, tempfile
os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')
from fastapi.testclient import TestClient  # noqa: E402
from app import auth, db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, c=200):
    assert r.status_code == c, (r.status_code, r.text); return r.json()


def main():
    with TestClient(app) as c:
        ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        n = ok(c.post('/api/notes', json={'body': 'Alışveriş', 'color': 'green'}))
        assert n['body'] == 'Alışveriş' and n['color'] == 'green' and not n['pinned']
        n2 = ok(c.put(f"/api/notes/{n['id']}", json={'body': 'Güncellendi', 'pinned': True, 'pin_x': 0.5, 'pin_y': 0.3}))
        assert n2['body'] == 'Güncellendi' and n2['pinned'] and abs(n2['pin_x'] - 0.5) < 1e-6
        # geçersiz renk korunur, sınır dışı pin kırpılır
        n3 = ok(c.put(f"/api/notes/{n['id']}", json={'color': 'xxx', 'pin_x': 5}))
        assert n3['color'] == 'green' and n3['pin_x'] == 1.0
        lst = ok(c.get('/api/notes'))
        assert len(lst) == 1 and lst[0]['pinned']
        # başka kullanıcı erişemez
        with db.connect() as conn:
            conn.execute("INSERT INTO users (username, password_hash, full_name, active, created_at) VALUES ('baska@test', ?, 'B', 1, ?)",
                         (auth.hash_password('baska-sifre-1'), db.now())); conn.commit()
        c2 = TestClient(app); ok(c2.post('/api/auth/login', json={'username': 'baska@test', 'password': 'baska-sifre-1'}))
        assert c2.get('/api/notes').json() == []
        assert c2.put(f"/api/notes/{n['id']}", json={'body': 'çalındı'}).status_code == 404
        assert c2.delete(f"/api/notes/{n['id']}").status_code == 404
        # sil
        ok(c.delete(f"/api/notes/{n['id']}"))
        assert ok(c.get('/api/notes')) == []
    print('Kişisel notlar testleri geçti.')


if __name__ == '__main__':
    main()
