"""Dış firma personeli (ör. kiralık güvenlik): firmanın Kişiler kaydına sistem kullanıcısı bağlanır, İK'da personel olmaz.
Yabancı uyruklu personel: pasaport ve çalışma izni zorunlu belgelerdir (askerlik istenmez)."""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import hr  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a, TestClient(app) as b:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        g = ok(a.post('/api/users', json={'username': 'guv1', 'full_name': 'Güvenlik Bir', 'roles': ['Güvenlik'], 'password': 'Sifre-1234x'}))['id']
        pilot = ok(a.post('/api/users', json={'username': 'pilot', 'full_name': 'Pilot Kişi', 'roles': ['Pilot'], 'password': 'Sifre-1234x'}))['id']
        emps = ok(a.get('/api/hr/employees'))
        assert any(e.get('user_id') == g for e in emps), 'kullanıcı açılınca personel kaydı otomatik açılır'
        cid = ok(a.post('/api/companies?supplier=true', json={'name': '2 AS ÖZEL GÜVENLİK LTD'}))['id']
        pid = ok(a.post(f'/api/companies/{cid}/people', json={'full_name': 'Güvenlik Bir', 'title': 'Güvenlik görevlisi', 'link_user': True, 'user_id': g}))['id']
        # Personel kaydı kaldırıldı ve yeniden açılmıyor
        with db.connect() as conn:
            assert not conn.execute('SELECT 1 FROM employees WHERE user_id = ?', (g,)).fetchone()
            hr.sync_users(conn)
            assert not conn.execute('SELECT 1 FROM employees WHERE user_id = ?', (g,)).fetchone()
        assert all(e.get('user_id') != g for e in ok(a.get('/api/hr/employees')))
        c = ok(a.get(f'/api/companies/{cid}'))
        assert c['people'][0]['user_id'] == g and c['people'][0]['user_name'] == 'Güvenlik Bir'
        ext = next(u for u in ok(a.get('/api/users')) if u['id'] == g)['external']
        assert ext['company_id'] == cid and ext['href'] == f'#/purchasing/suppliers/{cid}'
        # Aynı kullanıcı ikinci kişiye bağlanamaz; Kullanıcı Yönetimi yetkisi olmayan bağlayamaz
        assert a.post(f'/api/companies/{cid}/people', json={'full_name': 'Başkası', 'link_user': True, 'user_id': g}).status_code == 400
        # Belgesi olan personel dış firmaya bağlanamaz
        with db.connect() as conn:
            eid = conn.execute('SELECT id FROM employees WHERE user_id = ?', (pilot,)).fetchone()[0]
            conn.execute("INSERT INTO employee_files (employee_id, kind, path, file_name, created_at) VALUES (?, 'KIMLIK', 'hr/x.pdf', 'x.pdf', ?)", (eid, db.now()))
        assert a.put(f'/api/companies/people/{pid}', json={'full_name': 'Güvenlik Bir', 'link_user': True, 'user_id': pilot}).status_code == 400
        # Bağ kaldırılınca kullanıcı yeniden personel olabilir
        ok(a.put(f'/api/companies/people/{pid}', json={'full_name': 'Güvenlik Bir', 'link_user': True, 'user_id': None}))
        with db.connect() as conn:
            hr.sync_users(conn)
            assert conn.execute('SELECT 1 FROM employees WHERE user_id = ?', (g,)).fetchone()
        # Yabancı uyruklu: pasaport + çalışma izni zorunlu, askerlik değil
        e = {'is_foreign': 1, 'gender': 'E'}
        need = hr.required_kinds(e)
        assert 'PASAPORT' in need and 'CALISMA_IZNI' in need and 'ASKERLIK' not in need
        assert 'PASAPORT' not in hr.required_kinds({'gender': 'E'})
    print('Dış firma personeli ve yabancı uyruklu testleri geçti.')


if __name__ == '__main__':
    main()
