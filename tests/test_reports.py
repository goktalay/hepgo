"""Raporlar modülü: her rapor doğru yapıda döner (göstergeler, çıkarımlar, grafikler, tablolar); kullanıcı yalnızca
girebildiği modüllerin raporlarını görür; tarih doğrulaması.

Çalıştırma: .venv/bin/python -m tests.test_reports
"""
import os
import tempfile
from datetime import date, timedelta

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, reports  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def check(d):
    assert set(d) >= {'kpis', 'insights', 'charts', 'tables', 'params', 'title', 'module'}
    for c in d['charts']:
        if c['type'] == 'heat':
            assert len(c['heat']['values']) == 7 and all(len(r) == 24 for r in c['heat']['values'])
        else:
            assert all(len(ds['data']) == len(c['labels']) for ds in c['datasets']), (d['key'], c['title'])
    for t in d['tables']:
        keys = {c['key'] for c in t['columns']}
        assert all(keys <= set(r) for r in t['rows']), (d['key'], t['title'])


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        allr = ok(a.get('/api/reports'))
        # Dron raporu yalnız dron paketinde, Canlı Konum raporu yalnız sistem sahibinde görünür (bu testte ikisi de yok)
        assert {r['key'] for r in allr} == {r['key'] for r in reports.REPORTS if r['module'] not in ('drone', 'konum')} and len(allr) >= 20
        for r in allr:   # boş veriyle
            check(ok(a.get(f'/api/reports/{r["key"]}')))
        # Biraz veri: sipariş, üretim, hata, araç girişi, misafir
        cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
        oid = ok(a.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']
        pid = ok(a.post('/api/printers', json={'name': '7', 'ip': '10.0.0.7'}))['id']
        ok(a.post(f'/api/orders/{oid}/parts/L1/start', json={'printer_id': pid}))
        ok(a.post(f'/api/orders/{oid}/parts/L1/error', data={'error_code': 'E-1', 'description': 'x'}))
        ok(a.post(f'/api/orders/{oid}/parts/L2/start', json={'printer_id': pid}))
        ok(a.post('/api/security/vehicles', json={'plate': '34 AB 123'}))
        ok(a.post('/api/secretariat/visits', json={'purpose': 'Toplantı'}))
        for r in allr:
            check(ok(a.get(f'/api/reports/{r["key"]}')))
        d = ok(a.get('/api/reports/hata-analizi'))
        assert d['kpis'][0]['value'] == 1 and d['charts'][0]['labels'] == ['E-1']
        d = ok(a.get('/api/reports/uretim-performans'))
        assert d['kpis'][0]['value'] == 2 and len(d['charts'][0]['labels']) == 30   # varsayılan son 30 gün
        today = date.today()
        d = ok(a.get(f'/api/reports/arac-giris?date_from={(today - timedelta(6)).isoformat()}&date_to={today.isoformat()}'))
        assert d['kpis'][0]['value'] == 1 and d['params']['from'] == (today - timedelta(6)).isoformat()
        assert a.get('/api/reports/arac-giris?date_from=2026-02-30').status_code == 400
        assert a.get('/api/reports/arac-giris?date_from=2026-09-10&date_to=2026-09-01').status_code == 400
        assert a.get('/api/reports/arac-giris?date_from=2024-01-01&date_to=2026-01-01').status_code == 400
        assert a.get('/api/reports/yok').status_code == 404
        with db.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'Rapor görüntüledi'").fetchone()[0] > 0
        for u, role in (('pilot', 'Pilot'), ('guv', 'Güvenlik'), ('sek', 'Sekreter')):
            ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': [role], 'password': 'sifre-1234'}))
    with TestClient(app) as p:   # Pilot: saha ve stok raporları
        ok(p.post('/api/auth/login', json={'username': 'pilot', 'password': 'sifre-1234'}))
        mods = {r['module'] for r in ok(p.get('/api/reports'))}
        assert mods == {'field', 'stock', 'announcements'}, mods   # Duyurular herkese açık → haber / duyuru raporları da görünür
        assert p.get('/api/reports/hata-analizi').status_code == 404   # yetkisi olmayan modülün raporu
        check(ok(p.get('/api/reports/ucus-performans')))
    with TestClient(app) as s:
        ok(s.post('/api/auth/login', json={'username': 'sek', 'password': 'sifre-1234'}))
        assert {r['module'] for r in ok(s.get('/api/reports'))} == {'secretariat', 'announcements'}
    with TestClient(app) as g:   # Güvenlik rolü Raporlar modülünü görmez
        ok(g.post('/api/auth/login', json={'username': 'guv', 'password': 'sifre-1234'}))
        assert g.get('/api/reports').status_code == 403
    print(f'Rapor testleri geçti ({len(reports.REPORTS)} rapor).')


if __name__ == '__main__':
    main()
