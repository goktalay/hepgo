"""Yazıcı BAKIM modu: personel yazıcıyı bakıma alır/hatta geri verir; bakımdaki yazıcı maint_since taşır, KPI'da BAKIM
sayılır (arıza/çevrimdışı değil). Çalıştırma: .venv/bin/python -m tests.test_printer_maint
"""
import os, tempfile
os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')
from fastapi.testclient import TestClient  # noqa: E402
from app import dashboard, db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, c=200):
    assert r.status_code == c, (r.status_code, r.text); return r.json()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        pid = ok(a.post('/api/printers', json={'name': 'K2-01', 'ip': '10.0.0.1'}))['id']
        # başta bakımda değil
        assert ok(a.get('/api/printers'))[0]['maint_since'] is None
        # bakıma al
        ok(a.post(f'/api/printers/{pid}/maintenance', json={'on': True}))
        p = next(x for x in ok(a.get('/api/printers')) if x['id'] == pid)
        assert p['maint_since'], 'maint_since dolmalı'
        # KPI: BAKIM sayılır (CEVRIMDISI değil)
        with db.connect() as conn:
            st = dashboard.data(conn, {'id': 1, 'roles': [], 'modules': ['printers']}, ['kpi_printers'])['kpi_printers']['states']
        assert st.get('BAKIM') == 1 and st.get('CEVRIMDISI', 0) == 0, st
        # hatta geri ver
        ok(a.post(f'/api/printers/{pid}/maintenance', json={'on': False}))
        assert next(x for x in ok(a.get('/api/printers')) if x['id'] == pid)['maint_since'] is None
        with db.connect() as conn:
            st = dashboard.data(conn, {'id': 1, 'roles': [], 'modules': ['printers']}, ['kpi_printers'])['kpi_printers']['states']
        assert st.get('BAKIM', 0) == 0 and st.get('CEVRIMDISI') == 1, st
    print('Yazıcı BAKIM modu testleri geçti.')


if __name__ == '__main__':
    main()
