"""İzinli / raporlu personel: sağlık raporu ya da onaylı izin bugünü kapsıyorsa personel sistemde izinli görünür,
giriş yapamaz ve açık oturumu kapanır; ileri tarihli rapor etkilemez; sistem sahibi (MASTER) asla kilitlenmez.

Çalıştırma: .venv/bin/python -m tests.test_absence
"""
import os
import tempfile
from datetime import date, timedelta

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_MASTER_USERNAME='boss@test',
                  CAYMAZ_ADMIN_USERNAME='boss@test', CAYMAZ_ADMIN_PASSWORD='master-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'boss@test', 'password': 'master-sifre-1'}))
        uid = ok(a.post('/api/users', json={'username': 'p@test', 'full_name': 'Personel Bir', 'roles': ['Saha Personeli'], 'password': 'sifre-1234'}))['id']
        eid = next(e['id'] for e in ok(a.get('/api/hr/employees')) if e.get('username') == 'p@test')
        with db.connect() as c:
            c.execute("UPDATE employees SET status = 'AKTIF' WHERE id = ?", (eid,)); c.commit()
        p = TestClient(app)
        ok(p.post('/api/auth/login', json={'username': 'p@test', 'password': 'sifre-1234'}))
        ok(p.get('/api/auth/me'))
        # İleri tarihli rapor: etkilemez
        ok(a.post(f'/api/hr/employees/{eid}/health-reports', data={'start_date': d(3), 'end_date': d(5)}))
        auth._absence_cache.clear()
        ok(p.get('/api/auth/me'))
        # Bugünü kapsayan rapor: açık oturum kapanır, giriş engellenir; listelerde raporlu
        r = ok(a.post(f'/api/hr/employees/{eid}/health-reports', data={'start_date': d(-1), 'end_date': d(1), 'note': 'grip'}))
        assert len(r) == 2
        assert a.post(f'/api/hr/employees/{eid}/health-reports', data={'start_date': d(2), 'end_date': d(1)}).status_code == 400
        x = p.get('/api/auth/me')
        assert x.status_code == 401 and 'raporlu' in x.json()['detail'], x.text
        x = p.post('/api/auth/login', json={'username': 'p@test', 'password': 'sifre-1234'})
        assert x.status_code == 403 and 'raporlu' in x.json()['detail']
        assert next(e for e in ok(a.get('/api/hr/employees')) if e['id'] == eid)['on_report']
        assert next(u for u in ok(a.get('/api/users')) if u['id'] == uid)['absence']['kind'] == 'RAPOR'
        assert ok(a.get(f'/api/hr/employees/{eid}'))['absence']['label'] == 'Raporlu'
        # Rapor silinince giriş yeniden açılır
        rid = next(h['id'] for h in r if h['start_date'] == d(-1))
        ok(a.delete(f'/api/hr/employees/{eid}/health-reports/{rid}'))
        ok(p.post('/api/auth/login', json={'username': 'p@test', 'password': 'sifre-1234'}))
        # Onaylı izin de aynı kuralı uygular
        lv = ok(a.post(f'/api/hr/employees/{eid}/leaves', json={'kind': 'UCRETLI', 'start': d(0), 'end': d(2), 'reason': 'tatil', 'location': 'Ankara'}))
        auth._absence_cache.clear()
        with db.connect() as c:
            st = c.execute('SELECT status FROM leave_requests WHERE employee_id = ?', (eid,)).fetchone()[0]
        assert st == 'ONAYLANDI', st
        x = p.get('/api/auth/me')
        assert x.status_code == 401 and 'izinli' in x.json()['detail'], x.text
        # Sistem sahibi kendi izni / raporu olsa da kilitlenmez
        boss_eid = next(e['id'] for e in ok(a.get('/api/hr/employees')) if e.get('username') == 'boss@test')
        ok(a.post(f'/api/hr/employees/{boss_eid}/health-reports', data={'start_date': d(0), 'end_date': d(0)}))
        auth._absence_cache.clear()
        ok(a.get('/api/auth/me'))
    print('İzinli / raporlu testleri geçti.')


if __name__ == '__main__':
    main()
