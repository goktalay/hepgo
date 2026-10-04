"""MASTER (sistem sahibi): yalnızca config.MASTER_USERNAMES; her şeye erişir (admin rolü olmasa da); başkası MASTER olamaz;
diğer yöneticiler sistem sahibini sıradan Sistem Yöneticisi olarak görür; hesabı korunur; Veri & Yedek (özet, yedek
indirme, tam veri paketi; KVKK gereği kişisel veri gösterilmez).

Çalıştırma: .venv/bin/python -m tests.test_master
"""
import io
import os
import tempfile
import zipfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_MASTER_USERNAME='boss@sahibi.com',
                  CAYMAZ_ADMIN_USERNAME='boss@sahibi.com', CAYMAZ_ADMIN_PASSWORD='master-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def main():
    with TestClient(app) as m:
        login(m, 'boss@sahibi.com', 'master-sifre-1')
        me = ok(m.get('/api/auth/me'))
        assert me['master'] is True and 'master' in me['modules'] and 'MASTER' in me['roles']
        # sistem yöneticisi rolü DB'de olmasa bile her modüle erişir
        with __import__('app.db', fromlist=['db']).connect() as conn:
            conn.execute("DELETE FROM user_roles WHERE user_id = ?", (me['id'],))
            conn.commit()
        me2 = ok(m.get('/api/auth/me'))
        assert set(me2['modules']) >= {'admin', 'users', 'master', 'products', 'purchasing'}   # rol yokken bile
        # role bağlı bildirimler gerçek (DB) rollere göre: rol yokken role-özel bildirim gelmez (her modülde "register" olmaz)
        keys = {n['key'] for n in ok(m.get('/api/notifications'))['items']}
        assert 'warehouse-pending' not in keys and 'production-error' not in keys and 'purchase-approval' not in keys
        # normal yöneticiler ve personel oluştur
        ok(m.post('/api/users', json={'username': 'admin2', 'full_name': 'Yönetici İki', 'roles': ['Sistem Yöneticisi'], 'password': 'sifre-1234'}))
        ok(m.post('/api/users', json={'username': 'pilot1', 'full_name': 'Pilot Bir', 'roles': ['Pilot'], 'password': 'sifre-1234'}))
        # MASTER rolü kullanıcıya atanamaz (ROLES'te yok)
        assert m.post('/api/users', json={'username': 'x', 'full_name': 'X', 'roles': ['MASTER'], 'password': 'sifre-1234'}).status_code == 400
        # MASTER modülü "Veri & Yedek" (KVKK: kişisel veri göstermez): özet, yedekler, tam veri paketi
        ov = ok(m.get('/api/master/overview'))
        assert {'db_bytes', 'uploads_bytes', 'backup_count', 'last_backup', 'backup_ok'} <= set(ov) and 'users' not in ov
        assert ov['backup_count'] == 0 and ov['backup_ok'] is False
        nightly = Path(tmp) / 'backups' / 'nightly'
        nightly.mkdir(parents=True)
        (nightly / 'caymaz-20260101.db').write_bytes(b'SQLite format 3\x00')
        ov = ok(m.get('/api/master/overview'))
        assert ov['nightly_count'] == 1 and ov['last_backup']['name'] == 'caymaz-20260101.db' and ov['backup_ok'] is True
        assert [b['name'] for b in ok(m.get('/api/master/backups'))] == ['caymaz-20260101.db']
        r = m.get('/api/master/backups/download', params={'name': 'caymaz-20260101.db'})
        assert r.status_code == 200 and r.content.startswith(b'SQLite format 3')
        for bad in ('../caymaz.db', '../../signing.key', 'caymaz-x.db/../../caymaz.db', 'signing.key'):   # yol kaçışı / ad
            assert m.get('/api/master/backups/download', params={'name': bad}).status_code in (400, 404), bad
        assert m.get('/api/master/backups/download', params={'name': 'caymaz-yok.db'}).status_code == 404
        before = set(Path(tempfile.gettempdir()).glob('caymaz-export-*'))
        r = m.get('/api/master/export')
        assert r.status_code == 200 and r.headers['content-type'] == 'application/zip'
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assert 'caymaz.db' in names and 'BILGI.txt' in names, names
        assert set(Path(tempfile.gettempdir()).glob('caymaz-export-*')) == before   # geçici kopya silindi
    with TestClient(app) as a:   # normal Sistem Yöneticisi
        login(a, 'admin2', 'sifre-1234')
        assert ok(a.get('/api/auth/me'))['master'] is False
        for u in ('/api/master/overview', '/api/master/backups', '/api/master/export'):   # MASTER modülü kapalı
            assert a.get(u).status_code == 403, u
        # sistem sahibini sıradan Sistem Yöneticisi olarak görür (MASTER gizli)
        users = ok(a.get('/api/users'))
        boss = next(u for u in users if u['username'] == 'boss@sahibi.com')
        assert boss['roles'] == ['Sistem Yöneticisi'] and not boss.get('is_master')
        bid = boss['id']
        # sistem sahibinin hesabı pasifleştirilemez / kullanıcı adı değiştirilemez / silinemez
        assert a.put(f'/api/users/{bid}', json={'username': 'boss@sahibi.com', 'full_name': 'Sahibi', 'roles': ['Sistem Yöneticisi'], 'active': False}).status_code == 400
        assert a.put(f'/api/users/{bid}', json={'username': 'baska@x.com', 'full_name': 'Sahibi', 'roles': ['Sistem Yöneticisi'], 'active': True}).status_code == 400
        assert a.delete(f'/api/users/{bid}').status_code == 403
    with TestClient(app) as p:   # pilot: master alanı yok
        login(p, 'pilot1', 'sifre-1234')
        assert ok(p.get('/api/auth/me'))['master'] is False and 'master' not in ok(p.get('/api/auth/me'))['modules']
        assert p.get('/api/master/overview').status_code == 403
    print('MASTER testleri geçti.')


if __name__ == '__main__':
    main()
