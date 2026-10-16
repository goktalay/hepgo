"""Sistem yöneticisinin sebepsiz çıkış QR'ı: yalnız Sistem Yöneticisi / sistem sahibi üretir; güvenlik okutunca 'dışarıda'
kaydı düşer (sebep yok), ikinci okutma dönüş kaydeder; güvenlik 'Dışarıdaki yöneticiler' listesinde görür ve elle de
dönüş yazabilir. Kod yalnız üretildiği gün geçerli ve kişiye bağlıdır (imzalı).

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_admin_exit_pass
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from datetime import date, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, exitpass  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p='sifre-1234'):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def main():
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        mk = lambda u, roles: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,   # noqa: E731
                                                            'password': 'sifre-1234'}))['id']
        yon = mk('yonetici', ['Sistem Yöneticisi'])
        mk('guv', ['Güvenlik'])
        mk('montaj', ['Montaj Personeli'])
    with TestClient(app) as yonetici, TestClient(app) as guv, TestClient(app) as montaj:
        login(yonetici, 'yonetici'); login(guv, 'guv'); login(montaj, 'montaj')
        # yalnız sistem yöneticisi üretir
        assert montaj.get('/api/security/my-exit-pass').status_code == 403
        assert guv.get('/api/security/my-exit-pass').status_code == 403
        p = ok(yonetici.get('/api/security/my-exit-pass'))
        assert p['token'] and p['valid_on'] == date.today().isoformat() and p['outside_since'] is None
        # güvenlik okutur → çıkış (sebep yok); listede görünür; yönetici kendi ekranında "dışarıda" görür
        r = ok(guv.post('/api/security/verify-pass', json={'token': p['token']}))
        assert r['allow'] is True and r['type'] == 'admin' and r['name'] == 'Yonetici' and not r.get('returned'), r
        lst = ok(guv.get('/api/security/personnel'))['admins_outside']
        assert len(lst) == 1 and lst[0]['user_id'] == yon and lst[0]['name'] == 'Yonetici'
        assert ok(yonetici.get('/api/security/my-exit-pass'))['outside_since']
        exits = ok(guv.get('/api/security/exits'))
        assert exits[0]['kind'] == 'admin' and exits[0]['person_name'] == 'Yonetici'
        # ikinci okutma → dönüş; liste boşalır
        r = ok(guv.post('/api/security/verify-pass', json={'token': p['token']}))
        assert r['allow'] is True and r.get('returned') is True
        assert ok(guv.get('/api/security/personnel'))['admins_outside'] == []
        assert ok(yonetici.get('/api/security/my-exit-pass'))['outside_since'] is None
        # tekrar çıkış + güvenlik elle "Döndü"
        ok(guv.post('/api/security/verify-pass', json={'token': p['token']}))
        pid = ok(guv.get('/api/security/personnel'))['admins_outside'][0]['id']
        ok(guv.post(f'/api/security/admin-exit/{pid}/return', json={}))
        assert ok(guv.get('/api/security/personnel'))['admins_outside'] == []
        assert guv.post(f'/api/security/admin-exit/{pid}/return', json={}).status_code == 404
        # dünkü kod geçersiz; başka kişinin kodu taklit edilemez (imza)
        with db.connect() as c:
            old = exitpass.make_token(c, 'admin', yon, (date.today() - timedelta(days=1)).isoformat())
        r = ok(guv.post('/api/security/verify-pass', json={'token': old}))
        assert r['allow'] is False and ('gün' in r['reason'].lower() or 'dolmuş' in r['reason'].lower()), r
        fake = p['token'][:-4] + 'AAAA'
        assert ok(guv.post('/api/security/verify-pass', json={'token': fake}))['allow'] is False
        # güvenlik olmayan okutamaz
        assert montaj.post('/api/security/verify-pass', json={'token': p['token']}).status_code == 403
    print('Yönetici çıkış QR testleri geçti.')


if __name__ == '__main__':
    main()
