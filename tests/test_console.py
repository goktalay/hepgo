"""Web terminal (/ws/console): varsayılan KAPALI — MASTER dahil kimse kabuk açamaz; CAYMAZ_CONSOLE=1 iken yalnız MASTER.
Çalıştırma: .venv/bin/python -m tests.test_console
"""
import os
import tempfile

os.environ.pop('CAYMAZ_CONSOLE', None)
os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  CAYMAZ_MASTER_USERNAME='sahip@test')

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def denied(client):
    with client.websocket_connect('/ws/console') as ws:
        return ws.receive_text()


def main():
    assert config.CONSOLE_ENABLED is False
    with TestClient(app) as a, TestClient(app) as m:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ok(a.post('/api/users', json={'username': 'sahip@test', 'full_name': 'Sahip', 'roles': ['Sistem Yöneticisi'],
                                      'password': 'Gizli-Parola-77'}))
        ok(m.post('/api/auth/login', json={'username': 'sahip@test', 'password': 'Gizli-Parola-77'}))
        me = ok(m.get('/api/auth/me'))
        assert me['master'] and me['console'] is False, me
        assert 'kapalı' in denied(m)                     # kapalıyken MASTER de açamaz
        config.CONSOLE_ENABLED = True
        try:
            assert ok(m.get('/api/auth/me'))['console'] is True
            assert ok(a.get('/api/auth/me'))['console'] is False
            assert 'Yetkisiz' in denied(a)               # açıkken MASTER olmayan açamaz
        finally:
            config.CONSOLE_ENABLED = False
    print('Konsol testleri geçti.')


if __name__ == '__main__':
    main()
