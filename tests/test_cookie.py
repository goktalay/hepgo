"""Oturum çerezi: HTTPS'ten (doğrudan ya da Cloudflare tüneli: X-Forwarded-Proto / CF-Visitor) gelindiyse Secure;
yerel ağdan düz HTTP ile girişte Secure yok (yoksa tarayıcı saklamaz). Her durumda HttpOnly + SameSite=Lax.
Çalıştırma: .venv/bin/python -m tests.test_cookie
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

LOGIN = {'username': 'admin@test', 'password': 'admin-sifre-1'}


def cookie(client, headers=None):
    r = client.post('/api/auth/login', json=LOGIN, headers=headers or {})
    assert r.status_code == 200, r.text
    sc = r.headers['set-cookie'].lower()
    assert sc.startswith('caymaz_session=') and 'httponly' in sc and 'samesite=lax' in sc, sc
    return sc


def main():
    with TestClient(app) as c:
        assert 'secure' not in cookie(c)                                         # yerel ağ, düz HTTP
        assert 'secure' in cookie(c, {'x-forwarded-proto': 'https'})             # Cloudflare tüneli
        assert 'secure' in cookie(c, {'cf-visitor': '{"scheme":"https"}'})
        assert 'secure' not in cookie(c, {'x-forwarded-proto': 'http'})
    with TestClient(app, base_url='https://firma.veilox.app') as c:
        assert 'secure' in cookie(c)                                             # doğrudan HTTPS
        assert c.get('/api/auth/me').status_code == 200                          # Secure çerez HTTPS'te gönderilir
    print('Oturum çerezi testleri geçti.')


if __name__ == '__main__':
    main()
