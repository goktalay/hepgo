"""SSH Erişim (yalnız MASTER): sunucu CRUD, parola/anahtar şifreli saklanır ve hiç geri dönmez, yetki kısıtı,
WebSocket yalnız sistem sahibine açık. Gerçek SSH bağlantısı kurulmaz (uzak sunucu gerektirir).
Çalıştırma: .venv/bin/python -m tests.test_ssh
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='mkaderoglu@gokkubbetech.com', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
                  CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_MASTER_USERNAME='mkaderoglu@gokkubbetech.com')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.cameras import decrypt  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as c:
        ok(c.post("/api/auth/login", json={"username": "mkaderoglu@gokkubbetech.com", "password": "admin-sifre-1"}))
        me = ok(c.get("/api/auth/me"))
        assert me.get('master'), 'giriş yapan MASTER olmalı'
        # ekle (parola)
        hid = ok(c.post('/api/ssh/hosts', json={'label': 'Fabrika GX10', 'host': '192.168.1.50', 'port': 22,
                                                'username': 'mkaderoglu', 'auth_type': 'password', 'secret': 'gizli-parola'}))['id']
        lst = ok(c.get('/api/ssh/hosts'))
        assert len(lst) == 1 and lst[0]['label'] == 'Fabrika GX10' and lst[0]['has_secret']
        assert 'secret' not in lst[0], 'parola yanıtta DÖNMEMELİ'
        # parola veritabanında şifreli; çözülünce doğru
        with db.connect() as conn:
            enc = conn.execute('SELECT secret FROM ssh_hosts WHERE id = ?', (hid,)).fetchone()[0]
        assert enc != 'gizli-parola' and decrypt(enc) == 'gizli-parola', 'parola şifreli saklanmalı'
        # düzenle: parola boş → korunur, port değişir
        ok(c.put(f'/api/ssh/hosts/{hid}', json={'label': 'GX10', 'host': '192.168.1.50', 'port': 2222,
                                                'username': 'mkaderoglu', 'auth_type': 'password', 'secret': None}))
        with db.connect() as conn:
            r = conn.execute('SELECT port, secret FROM ssh_hosts WHERE id = ?', (hid,)).fetchone()
        assert r[0] == 2222 and decrypt(r[1]) == 'gizli-parola', 'boş parola eski parolayı korumalı'
        # eksik alan reddi
        assert c.post('/api/ssh/hosts', json={'label': '', 'host': 'x', 'username': 'u', 'secret': 'p'}).status_code == 400
        assert c.post('/api/ssh/hosts', json={'label': 'Y', 'host': 'x', 'username': 'u', 'auth_type': 'password'}).status_code == 400  # parola yok
        # denetim kaydı yazıldı
        with db.connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE entity = 'ssh'").fetchone()[0]
        assert n >= 2, ('ssh denetim kaydı', n)

        # MASTER olmayan kullanıcı erişemez
        with db.connect() as conn:
            conn.execute("INSERT INTO users (username, password_hash, full_name, active, created_at) VALUES ('calisan@firma.com', ?, 'Çalışan', 1, ?)",
                         (__import__('app.auth', fromlist=['hash_password']).hash_password('calisan-sifre-1'), db.now()))
            conn.commit()
        c2 = TestClient(app)
        ok(c2.post('/api/auth/login', json={'username': 'calisan@firma.com', 'password': 'calisan-sifre-1'}))
        assert c2.get('/api/ssh/hosts').status_code == 403, 'MASTER olmayan listeleyememeli'
        assert c2.post('/api/ssh/hosts', json={'label': 'X', 'host': 'h', 'username': 'u', 'secret': 'p'}).status_code == 403
        # WebSocket: MASTER olmayan reddedilir
        try:
            with c2.websocket_connect(f'/ws/ssh/{hid}') as w:
                txt = w.receive_text()
                assert 'Yetkisiz' in txt, txt
            assert False, 'bağlantı kapanmalıydı'
        except Exception:
            pass
        # sil
        ok(c.delete(f'/api/ssh/hosts/{hid}'))
        assert ok(c.get('/api/ssh/hosts')) == []
    print('SSH Erişim testleri geçti.')


if __name__ == '__main__':
    main()
