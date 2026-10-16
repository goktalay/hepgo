"""Şirketten Haberler: sistem sahibi (MASTER) başkasının paylaşımını sebep yazarak kaldırır; sebep paylaşım sahibine zil bildirimi
olarak gider ve /api/feed/removed açılınca görüldü sayılır. Master olmayan kaldıramaz; sebepsiz kaldırılamaz.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_feed_remove
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  CAYMAZ_MASTER_USERNAME='admin@test')   # yönetici hesabı aynı zamanda sistem sahibi

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p='sifre-1234'):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def notes(c):
    return {n['key']: n for n in ok(c.get('/api/notifications'))['items']}


def main():
    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        mk = lambda u, roles: ok(admin.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,   # noqa: E731
                                                                'password': 'sifre-1234'}))['id']
        mk('yonetici', ['Sistem Yöneticisi'])
        mk('ayse', ['Montaj Personeli'])
    with TestClient(app) as ayse, TestClient(app) as master, TestClient(app) as admin:
        login(ayse, 'ayse'); login(master, 'admin@test', 'admin-sifre-1'); login(admin, 'yonetici')
        assert ok(master.get('/api/auth/me'))['master'] is True and ok(admin.get('/api/auth/me'))['master'] is False
        pid = ok(ayse.post('/api/feed', data={'text': 'Bugün sahada güzel bir gün'}))['id']
        pid2 = ok(ayse.post('/api/feed', data={'text': 'İkinci paylaşım'}))['id']
        # master olmayan (yönetici dahil) kaldıramaz; sebep zorunlu
        assert admin.post(f'/api/feed/{pid}/remove', json={'reason': 'uygunsuz'}).status_code == 403
        assert master.post(f'/api/feed/{pid}/remove', json={'reason': ' '}).status_code == 400
        assert ayse.post(f'/api/feed/{pid}/remove', json={'reason': 'kendim'}).status_code == 403
        # master sebeple kaldırır: akıştan kalkar, sahibine zil bildirimi düşer
        ok(master.post(f'/api/feed/{pid}/remove', json={'reason': 'Şirket politikasına uygun değil'}))
        assert pid not in {p['id'] for p in ok(ayse.get('/api/feed'))['posts']}
        assert master.post(f'/api/feed/{pid}/remove', json={'reason': 'tekrar'}).status_code == 404
        n = notes(ayse)['feed-removed']
        assert n['names'] == ['Şirket politikasına uygun değil — "Bugün sahada güzel bir gün"'] and n['href'] == '#/home?removed=1', n
        assert 'feed-removed' not in notes(master)   # başkasına düşmez
        # sahibi sebebi açar → görüldü; bildirim kalkar; ikinci paylaşım kaldırılmamış
        rows = ok(ayse.get('/api/feed/removed'))
        assert len(rows) == 1 and rows[0]['reason'] == 'Şirket politikasına uygun değil' and rows[0]['removed_by']
        assert 'feed-removed' not in notes(ayse) and ok(ayse.get('/api/feed/removed')) == []
        assert pid2 in {p['id'] for p in ok(ayse.get('/api/feed'))['posts']}
        # sahibinin kendi silmesi bildirim üretmez
        ok(ayse.delete(f'/api/feed/{pid2}'))
        assert 'feed-removed' not in notes(ayse)
    print('Paylaşım kaldırma testleri geçti.')


if __name__ == '__main__':
    main()
