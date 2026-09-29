"""Bölüm bölüm montaj testi: bir bölümün (sol kanat, sağ kanat, orta gövde) tüm parçaları depoya girince, siparişin
diğer parçaları üretimdeyken de o bölüm monte edilebilir. Kapaklar gövdeye sayılmaz: birleştirme kapaklar basılırken
yapılabilir, kapak montajı en son (tüm kapaklar depoda) yapılır ve uçak kalibrasyona geçer.

Çalıştırma: .venv/bin/python -m tests.test_early_assembly
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import catalogs, db  # noqa: E402
from app.main import app  # noqa: E402
from app.production import recompute  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    names, sections = catalogs.sections('caymaz')
    covers = set(catalogs.cover_parts('caymaz'))
    eparts = set(catalogs.electronics_parts('caymaz'))
    sec = lambda key: [p for p, s in sections.items() if s == key and p not in covers]
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        mk = lambda u, roles: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,
                                                            'password': 'sifre-1234'}))['id']
        m1, m2, el = mk('m1', ['Montaj Personeli']), mk('m2', ['Montaj Personeli']), mk('el', ['Elektronik Personeli'])
        cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
        oid = ok(a.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']

        def to_depot(parts):
            with db.connect() as c:
                c.executemany("UPDATE order_parts SET state = 'DEPO', finished_at = ?, approved_at = ? WHERE order_id = ? AND part_id = ?",
                              [(db.now(), db.now(), oid, p) for p in parts])
                recompute(c, oid)

        # Sol kanadın parçaları depoda, gerisi basılıyor / bekliyor
        to_depot(sec('SOL_KANAT'))
        with db.connect() as c:
            c.execute("UPDATE order_parts SET state = 'URETIMDE' WHERE order_id = ? AND part_id = ?", (oid, sec('GOVDE')[0]))
            recompute(c, oid)
        o = ok(a.get(f'/api/orders/{oid}'))
        sp = o['assembly']['section_parts']
        assert o['status'] == 'URETIM' and sp['SOL_KANAT']['all_ready'] and not sp['GOVDE']['all_ready']
        assert sp['GOVDE']['total'] == len(sec('GOVDE')) and sp['GOVDE']['ready'] == 0   # kapaklar gövdeye sayılmaz
        url = f'/api/orders/{oid}/assembly'
        r = a.post(f'{url}/SAG_KANAT', json={'staff_ids': [m1, m2]})
        assert r.status_code == 400 and '0/' in r.json()['detail']
        assert ok(a.post(f'{url}/SOL_KANAT', json={'staff_ids': [m1, m2]}))['status'] == 'URETIM'   # gövde basılırken kanat
        o = ok(a.get(f'/api/orders/{oid}'))
        assert all(p['state'] == 'MONTAJ' for p in o['parts'] if p['part_id'] in sec('SOL_KANAT'))
        assert 'SOL_KANAT' in o['assembly']['steps'] and o['status'] == 'URETIM'
        assert a.post(f'{url}/SOL_KANAT', json={'staff_ids': [m1, m2]}).status_code == 400

        # Kapaklar hariç her şey depoda: kalan bölümler, elektronik ve birleştirme kapaklar basılırken yapılır
        to_depot(sec('SAG_KANAT') + sec('GOVDE') + list(eparts))
        o = ok(a.get(f'/api/orders/{oid}'))
        assert o['status'] == 'URETIM' and o['assembly']['covers']['ready'] == 0 and o['assembly']['covers']['total'] == len(covers)
        for key in ('SAG_KANAT', 'GOVDE'):
            assert ok(a.post(f'{url}/{key}', json={'staff_ids': [m1, m2]}))['status'] == 'URETIM'
        for part in eparts:
            ok(a.post(f'/api/orders/{oid}/electronics/{part}', json={'staff_ids': [el]}))
        fin = {'wings': True, 'electronics': True}
        assert ok(a.post(f'/api/orders/{oid}/final', json={'staff_ids': [m1, m2], 'checklist': fin}))['status'] == 'URETIM'
        assert a.post(f'/api/orders/{oid}/covers', json={'staff_ids': [m1]}).status_code == 400   # kapaklar depoda değil
        cover_state = {p['part_id']: p['state'] for p in ok(a.get(f'/api/orders/{oid}'))['parts'] if p['part_id'] in covers}
        assert set(cover_state.values()) == {'BEKLIYOR'}   # gövde montajı kapaklara dokunmaz

        # Kapaklar depoya girince uçak montaj aşamasına geçer; kapak montajı ile kalibrasyona
        to_depot(covers)
        o = ok(a.get(f'/api/orders/{oid}'))
        assert o['status'] == 'MONTAJ' and o['assembly']['covers']['all_ready']
        assert ok(a.post(f'/api/orders/{oid}/covers', json={'staff_ids': [m1]}))['status'] == 'KALIBRASYON'
        o = ok(a.get(f'/api/orders/{oid}'))
        assert all(p['state'] == 'MONTAJ' for p in o['parts'])
        assert a.post(f'{url}/GOVDE', json={'staff_ids': [m1, m2]}).status_code == 400   # kalibrasyondan sonra yok
    print('Bölüm bölüm montaj ve kapak montajı testleri geçti.')


if __name__ == '__main__':
    main()
