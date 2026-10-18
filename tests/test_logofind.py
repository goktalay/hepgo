"""Firma Yönetimi › Logolarını bul: logosu olmayan aktif firmaların logosu web'den aranır (site simgeleri → sabit yollar →
Clearbit → Google; alan adı yoksa DuckDuckGo ile alan adı), küçük görsel reddedilir, bulunan logo data/uploads/logos/ altına
yazılıp companies.logo'ya bağlanır; logosu olan firmaya dokunulmaz; alan adı bulunamayan atlanır; yetkisiz kullanıcı 403.
Ağ yok: logofind.fetch sahte tabloyla değiştirilir.
Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_logofind
"""
import io
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import config, db, logofind  # noqa: E402
from app.main import app  # noqa: E402


def png(size):
    out = io.BytesIO()
    Image.new('RGBA', (size, size), (200, 30, 30, 255)).save(out, format='PNG')
    return out.getvalue()


def ico(sizes):
    out = io.BytesIO()
    Image.new('RGBA', (max(sizes), max(sizes)), (0, 0, 200, 255)).save(out, format='ICO', sizes=[(s, s) for s in sizes])
    return out.getvalue()


# Sahte web: URL → (durum, content-type, gövde); tabloda olmayan adresler 404
WEB = {
    # Acme: site HTML'inde apple-touch-icon → 64 px PNG
    'https://acme.com.tr/': (200, 'text/html', b'<html><head><link rel="icon" href="/fav16.png" sizes="16x16">'
                                                 b'<link rel="apple-touch-icon" href="/img/logo.png"></head></html>'),
    'https://acme.com.tr/img/logo.png': (200, 'image/png', png(64)),
    'https://acme.com.tr/fav16.png': (200, 'image/png', png(16)),
    # Beta: site yok, favicon 16 px (reddedilir) → Clearbit
    'https://beta.com/favicon.ico': (200, 'image/x-icon', ico([16])),
    'https://logo.clearbit.com/beta.com': (200, 'image/png', png(128)),
    # Gamma: alan adı yok → DuckDuckGo → gamma.com → yalnız Google favicon servisi
    'https://html.duckduckgo.com/html/?q=Gamma+Sanayi': (200, 'text/html', b'<div class="result"><a class="result__a" '
        b'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.gamma.com%2Fhakkimizda&amp;rut=abc">Gamma</a></div>'),
    'https://www.google.com/s2/favicons?domain=gamma.com&sz=128': (200, 'image/png', png(128)),
    # Zeta: ICO 48 px → PNG'ye çevrilir
    'https://zeta.net/favicon.ico': (200, 'image/vnd.microsoft.icon', ico([48])),
}
calls = []


def fake_fetch(url, timeout=5.0):
    calls.append(url)
    return WEB.get(url, (404, 'text/html', b'yok'))


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def unit():
    assert logofind.domain_of('https://www.acme.com.tr/tr/anasayfa') == 'acme.com.tr'
    assert logofind.domain_of('acme.com.tr') == 'acme.com.tr'
    assert logofind.domain_of(None, 'Ali <ali@Beta.com>') == 'beta.com'
    assert logofind.domain_of(None, 'x@gmail.com') is None          # genel posta servisi alan adı sayılmaz
    assert logofind.domain_of('', '') is None
    assert logofind.check_image('image/png', png(16)) is None       # küçük
    assert logofind.check_image('image/png', b'') is None            # boş
    assert logofind.check_image('image/png', png(40))[0] == '.png'
    assert logofind.check_image('', png(40))[0] == '.png'            # content-type eksik: imzadan tanınır
    ext, data = logofind.check_image('image/x-icon', ico([16, 48]))
    assert ext == '.png' and Image.open(io.BytesIO(data)).size == (48, 48)   # ICO → en büyük kare, PNG
    assert logofind.check_image('image/svg+xml', b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>' + b' ' * 64)[0] == '.svg'
    assert logofind.check_image('image/svg+xml', b'<html>hata sayfasi</html>' + b' ' * 64) is None
    urls = logofind.icons_from_html('https://x.com/', '<link rel="icon" sizes="32x32" href="/a.png"><link rel="shortcut icon" href="/b.ico">'
                                    '<link rel="apple-touch-icon" href="/t.png"><meta property="og:image" content="https://cdn.x.com/og.jpg">')
    assert urls == ['https://x.com/t.png', 'https://x.com/a.png', 'https://x.com/b.ico', 'https://cdn.x.com/og.jpg']


def main():
    unit()
    logofind.fetch = fake_fetch
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ids = {}
        for name, website, email in (('Acme Makine', 'https://www.acme.com.tr', None), ('Beta Ltd', None, 'info@beta.com'),
                                     ('Gamma Sanayi', None, None), ('Delta', None, 'delta@gmail.com'),
                                     ('Omega', 'https://omega.org', None), ('Zeta', 'zeta.net', None), ('Logolu', 'https://acme.com.tr', None)):
            ids[name] = ok(a.post('/api/companies', json={'name': name, 'website': website, 'email': email}))['id']
        with db.connect() as c:   # Logolu firmanın logosu var: taranmamalı
            c.execute('UPDATE companies SET logo = ? WHERE id = ?', ('logos/var.png', ids['Logolu']))
            c.commit()
        assert ok(a.get('/api/companies/logos/find/status'))['running'] is False
        s = ok(a.post('/api/companies/logos/find', json={'only_missing': True}))
        assert s['started'] is True
        logofind._worker.join(30)
        s = ok(a.get('/api/companies/logos/find/status'))
        assert not s['running'] and s['error'] is None, s
        assert s['total'] == 6 and s['done'] == 6, s                    # Logolu taranmadı
        assert (s['found'], s['skipped'], s['failed']) == (4, 1, 1), s   # Acme, Beta, Gamma, Zeta · Delta atlandı · Omega bulunamadı
        src = {i['name']: i['source'] for i in s['items']}
        assert src == {'Acme Makine': 'site', 'Beta Ltd': 'clearbit', 'Gamma Sanayi': 'google+ddg', 'Zeta': 'site'}, src
        assert 'https://acme.com.tr/fav16.png' not in calls           # apple-touch-icon bulununca küçük simge istenmez
        cos = {c['name']: c for c in ok(a.get('/api/companies'))}
        for name in ('Acme Makine', 'Beta Ltd', 'Gamma Sanayi', 'Zeta'):
            p = cos[name]['logo']
            assert p and p.startswith('logos/') and (config.UPLOAD_DIR / p).exists(), (name, p)
            assert Image.open(config.UPLOAD_DIR / p).size[0] >= 32
        assert cos['Zeta']['logo'].endswith('.png')                      # ICO → PNG
        assert cos['Logolu']['logo'] == 'logos/var.png' and not cos['Omega']['logo'] and not cos['Delta']['logo']
        # Kayıtlı logo /api/files ile sunulur
        assert a.get(f"/api/files/{cos['Acme Makine']['logo']}").status_code == 200
        # İkinci tarama: eksik kalanlar yeniden denenir (Omega, Delta); logolular dokunulmaz
        calls.clear()
        ok(a.post('/api/companies/logos/find', json={'only_missing': True}))
        logofind._worker.join(30)
        s = ok(a.get('/api/companies/logos/find/status'))
        assert s['total'] == 2 and s['found'] == 0, s
        assert not any('acme' in u for u in calls)
        ok(a.post('/api/users', json={'username': 'pilot', 'full_name': 'Pilot', 'roles': ['Pilot'], 'password': 'sifre-1234'}))
    with TestClient(app) as p:   # firma modülü yetkisi olmayan kullanıcı
        ok(p.post('/api/auth/login', json={'username': 'pilot', 'password': 'sifre-1234'}))
        assert p.post('/api/companies/logos/find', json={}).status_code == 403
        assert p.get('/api/companies/logos/find/status').status_code == 403
    print('test_logofind: OK')


if __name__ == '__main__':
    main()
