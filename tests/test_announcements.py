"""Duyurular: yalnızca Sistem Yöneticisi yazar; herkes görür; açınca okundu olur ve okunmamış listeden (bildirim, pano) düşer;
yönetici okuyanları ve okumayanları görür; süresi geçen duyuru kullanıcılara görünmez.

Çalıştırma: .venv/bin/python -m tests.test_announcements
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        for u, role in (('pilot', 'Pilot'), ('guv', 'Güvenlik')):
            ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': [role], 'password': 'sifre-1234'}))
        assert a.post('/api/announcements', json={'title': ' ', 'body': 'x'}).status_code == 400
        assert a.post('/api/announcements', json={'title': 'X', 'body': 'x', 'level': 'YOK'}).status_code == 400
        a1 = ok(a.post('/api/announcements', json={'title': 'Bayram tatili', 'body': 'Fabrika 3 gün kapalı.', 'level': 'ONEMLI', 'pinned': True}))['id']
        a2 = ok(a.post('/api/announcements', json={'title': 'Eski duyuru', 'body': 'x', 'expires_at': '2020-01-01'}))['id']
        lst = ok(a.get('/api/announcements'))
        assert lst['can_edit'] and len(lst['items']) == 2 and lst['items'][0]['read_at']   # yazan okumuş sayılır
    with TestClient(app) as p:
        ok(p.post('/api/auth/login', json={'username': 'pilot', 'password': 'sifre-1234'}))
        lst = ok(p.get('/api/announcements'))
        assert not lst['can_edit'] and [x['title'] for x in lst['items']] == ['Bayram tatili']   # süresi geçen görünmez
        assert lst['items'][0]['read_at'] is None and 'read_count' not in lst['items'][0]
        n = {x['key']: x for x in ok(p.get('/api/notifications'))['items']}
        assert n['announcements']['count'] == 1
        assert ok(p.get('/api/dashboard/data?keys=announcements'))['announcements']['items'][0]['title'] == 'Bayram tatili'
        d = ok(p.get(f'/api/announcements/{a1}'))   # açınca okundu
        assert d['body'] == 'Fabrika 3 gün kapalı.' and 'readers' not in d
        assert ok(p.get('/api/announcements'))['items'][0]['read_at']
        assert 'announcements' not in {x['key'] for x in ok(p.get('/api/notifications'))['items']}
        assert ok(p.get('/api/dashboard/data?keys=announcements'))['announcements']['items'] == []
        assert p.post('/api/announcements', json={'title': 'X', 'body': 'y'}).status_code == 403
        assert p.put(f'/api/announcements/{a1}', json={'title': 'X', 'body': 'y'}).status_code == 403
        assert p.delete(f'/api/announcements/{a1}').status_code == 403
    with TestClient(app) as g:   # Güvenlik rolü de duyuruları görür; üretim uyarıları gizli kalır
        ok(g.post('/api/auth/login', json={'username': 'guv', 'password': 'sifre-1234'}))
        assert len(ok(g.get('/api/announcements'))['items']) == 1
        assert ok(g.get('/api/alerts'))['total'] == 0
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        d = ok(a.get(f'/api/announcements/{a1}'))
        assert {r['full_name'] for r in d['readers']} >= {'Pilot'} and 'Guv' in {u['full_name'] for u in d['unread']}
        assert ok(a.get('/api/announcements'))['items'][0]['read_count'] == 2
        ok(a.put(f'/api/announcements/{a1}', json={'title': 'Bayram tatili (güncel)', 'body': 'Fabrika 4 gün kapalı.', 'level': 'KRITIK'}))
        ok(a.delete(f'/api/announcements/{a2}'))
        assert [x['title'] for x in ok(a.get('/api/announcements'))['items']] == ['Bayram tatili (güncel)']
    print('Duyuru testleri geçti.')


if __name__ == '__main__':
    main()
