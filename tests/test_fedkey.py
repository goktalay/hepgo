"""Federasyon: her firmaya ayrı (türetilmiş) anahtar. Firma A'nın anahtarı yalnız A'nın slug'ıyla geçer; B'nin verisine
erişemez. Ortak (ana) anahtar yalnız geçiş ayarı açıkken geçer. Doğrulama ucu (/federation/verify) da aynı kural.
Çalıştırma: .venv/bin/python -m tests.test_fedkey
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  CAYMAZ_FEDERATION_CENTRAL='1', CAYMAZ_FEDERATION_SECRET='ana-anahtar-xyz', CAYMAZ_FEDERATION_URL='',
                  CAYMAZ_TENANT_SLUG='', CAYMAZ_VEILOX_SOCKET='/nonexistent/veilox.sock')

from fastapi.testclient import TestClient  # noqa: E402

from app import config, fedauth  # noqa: E402
from app.main import app  # noqa: E402


def main():
    ka, kb = fedauth.tenant_key('acme'), fedauth.tenant_key('beta')
    assert ka != kb and len(ka) == 64 and ka != config.FEDERATION_SECRET
    with TestClient(app) as c:
        st = lambda key, slug: c.get('/api/federation/status', params={'slug': slug}, headers={'X-Fed-Secret': key}).status_code  # noqa: E731
        vf = lambda key, slug: c.post('/api/federation/verify', params={'slug': slug}, headers={'X-Fed-Secret': key},  # noqa: E731
                                      json={'username': 'yok', 'password': 'yok'}).status_code
        assert st(ka, 'acme') == 200 and st(kb, 'beta') == 200
        assert st(ka, 'beta') == 403 and st(kb, 'acme') == 403          # başka firmanın verisine erişemez
        assert st('yanlis', 'acme') == 403 and st('', 'acme') == 403
        assert vf(ka, 'acme') == 200 and vf(ka, 'beta') == 403 and vf(ka, '') == 403
        # Geçiş: ortak anahtar açıkken geçer, kapatılınca geçmez (türetilmiş anahtar her zaman geçer)
        assert config.FEDERATION_ALLOW_SHARED and st(config.FEDERATION_SECRET, 'beta') == 200 and vf(config.FEDERATION_SECRET, '') == 200
        config.FEDERATION_ALLOW_SHARED = False
        try:
            assert st(config.FEDERATION_SECRET, 'beta') == 403 and vf(config.FEDERATION_SECRET, '') == 403
            assert st(ka, 'acme') == 200 and vf(ka, 'acme') == 200
        finally:
            config.FEDERATION_ALLOW_SHARED = True
    print('Federasyon anahtarı testleri geçti.')


if __name__ == '__main__':
    main()
