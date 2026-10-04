"""Küçük XSS korumaları: firma web sitesinde javascript:/data: kabul edilmez (şemasıza https:// eklenir); SVG logo
doğrudan açılınca betik çalıştıramaz (CSP sandbox), tüm dosyalarda nosniff. (Arayüzdeki h() adres koruması: tests/check_js
dışında tarayıcı testiyle denenir — README.)
Çalıştırma: .venv/bin/python -m tests.test_xss_misc
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(2)</script><rect width="10" height="10"/></svg>'
PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                    '1f15c4890000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082')


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        for bad in ('javascript:alert(1)', ' JavaScript:alert(1)', 'data:text/html,<script>1</script>', 'vbscript:x'):
            r = a.post('/api/companies', json={'name': f'Kötü {bad[:4]}', 'website': bad})
            assert r.status_code == 400, (bad, r.text)
        cid = ok(a.post('/api/companies', json={'name': 'İyi Firma', 'website': 'iyifirma.com'}))['id']
        assert ok(a.get(f'/api/companies/{cid}'))['website'] == 'https://iyifirma.com'
        ok(a.put(f'/api/companies/{cid}', json={'name': 'İyi Firma', 'website': 'http://iyifirma.com/x'}))
        assert ok(a.get(f'/api/companies/{cid}'))['website'] == 'http://iyifirma.com/x'
        assert a.put(f'/api/companies/{cid}', json={'name': 'İyi Firma', 'website': 'javascript:alert(1)'}).status_code == 400

        svg = ok(a.post(f'/api/companies/{cid}/logo', files={'file': ('logo.svg', SVG, 'image/svg+xml')}))['logo']
        r = a.get(f'/api/files/{svg}')
        assert r.status_code == 200 and 'sandbox' in r.headers['content-security-policy'] and r.headers['x-content-type-options'] == 'nosniff'
        assert 'sandbox' in a.get(f'/api/files/{svg}?dl=1').headers['content-security-policy']
        png = ok(a.post(f'/api/companies/{cid}/logo', files={'file': ('logo.png', PNG, 'image/png')}))['logo']
        r = a.get(f'/api/files/{png}')
        assert r.status_code == 200 and r.headers['x-content-type-options'] == 'nosniff' and 'content-security-policy' not in r.headers
    print('Küçük XSS koruma testleri geçti.')


if __name__ == '__main__':
    main()
