"""Mikro ERP modülü: YALNIZCA MASTER erişebilir + tenant kapısı (config gate). Canlı MSSQL gerektirmez.

- Mikro tanımlı değilse (ör. Türkbey) modül hiç görünmez, master bile.
- Mikro tanımlıysa yalnızca MASTER görür; sıradan Yönetici (ADMIN) bile göremez.

Çalıştırma: .venv/bin/python -m tests.test_mikro
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='master@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
                  CAYMAZ_MASTER_USERNAME='master@test', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as c:
        ok(c.post('/api/auth/login', json={'username': 'master@test', 'password': 'admin-sifre-1'}))
        assert ok(c.get('/api/auth/me'))['master'] is True

        # Normal Yönetici (master değil) oluştur.
        from app import auth
        ok(c.post('/api/users', json={'username': 'yonetici@test', 'full_name': 'Yönetici',
                                      'roles': [auth.ADMIN], 'password': 'sifre-1234'}))

        # 1) Mikro tanımlı DEĞİL: master bile modülü görmez.
        config.MIKRO_DB = config.MIKRO_USER = config.MIKRO_PASSWORD = ''
        assert 'mikro' not in ok(c.get('/api/auth/me'))['modules']
        assert c.get('/api/mikro/status').status_code == 403

        # 2) Mikro tanımlı: MASTER görür, sıradan Yönetici GÖRMEZ.
        config.MIKRO_HOST, config.MIKRO_DB = '192.168.1.100', 'MikroDesktop_001'
        config.MIKRO_USER, config.MIKRO_PASSWORD = 'u', 'p'
        me = ok(c.get('/api/auth/me'))
        assert 'mikro' in me['modules'], me['modules']
        st = ok(c.get('/api/mikro/status'))
        assert st['configured'] is True and st['can_import'] is True, st

        with TestClient(app) as adm:
            ok(adm.post('/api/auth/login', json={'username': 'yonetici@test', 'password': 'sifre-1234'}))
            assert 'mikro' not in ok(adm.get('/api/auth/me'))['modules']
            assert adm.get('/api/mikro/status').status_code == 403   # Yönetici bile erişemez

    print('Mikro testleri geçti.')


if __name__ == '__main__':
    main()
