"""Stajer: hiçbir modüle yetkili değil (yalnızca herkese açık Duyurular ve genel yapı), yardımcı personel seçimlerinde
"intern" işaretiyle listelenir ve seçilebilir (tek başına değil), pasifleştirilince listelerden düşer ve giriş yapamaz.

Çalıştırma: .venv/bin/python -m tests.test_intern
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db, production  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        assert 'Stajer' in ok(a.get('/api/meta'))['roles']
        mk = lambda u, roles: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles, 'password': 'sifre-1234'}))['id']
        stj, mon, saha = mk('stajer', ['Stajer']), mk('montajci', ['Montaj Personeli']), mk('saha', ['Saha Personeli'])
        with TestClient(app) as s:
            ok(s.post('/api/auth/login', json={'username': 'stajer', 'password': 'sifre-1234'}))
            me = ok(s.get('/api/auth/me'))
            assert me['modules'] == ['announcements'], me['modules']
            for url in ('/api/orders', '/api/printers', '/api/users', '/api/documents', '/api/secretariat/visits', '/api/reports'):
                assert s.get(url).status_code == 403, url
            ok(s.get('/api/dashboard/widgets')); ok(s.get('/api/meetings')); ok(s.get('/api/chat/summary'))   # genel yapı
        # yardımcı personel seçimleri: stajer de listelenir (en sonda, işaretli); sorumlu rollerinde yok
        lst = ok(a.get('/api/people?role=Montaj Personeli'))
        assert [(p['full_name'], p['intern']) for p in lst] == [('Montajci', False), ('Stajer', True)]
        assert [p['full_name'] for p in ok(a.get('/api/people?role=Saha Personeli'))] == ['Saha', 'Stajer']
        assert 'Stajer' not in [p['full_name'] for p in ok(a.get('/api/people?role=Depo Yöneticisi'))]
        assert next(p for p in ok(a.get('/api/people')) if p['id'] == stj)['intern']
        with db.connect() as conn:
            assert production._staff(conn, [mon, stj], minimum=2) == sorted([mon, stj])
            for bad in ([stj], [stj, saha]):   # tek başına stajer olmaz; rolü uymayan kişi olmaz
                try:
                    production._staff(conn, bad, minimum=1)
                    raise AssertionError(bad)
                except HTTPException:
                    pass
            assert auth.has_role_or_intern(conn, stj, auth.FIELD_STAFF) and not auth.has_role_or_intern(conn, stj, auth.DRIVER)
        # pasifleştirme
        u = ok(a.get(f'/api/users/{stj}'))
        ok(a.put(f'/api/users/{stj}', json={**{k: u[k] for k in ('username', 'full_name')}, 'roles': u['roles'], 'active': False}))
        assert 'Stajer' not in [p['full_name'] for p in ok(a.get('/api/people?role=Montaj Personeli'))]
        with TestClient(app) as s:
            assert s.post('/api/auth/login', json={'username': 'stajer', 'password': 'sifre-1234'}).status_code == 401
    print('Stajer testleri geçti.')


if __name__ == '__main__':
    main()
