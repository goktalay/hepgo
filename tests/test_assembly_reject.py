"""Montajda hatalı bulunan parça (SP-0035 / L12 örneği): depoda onaylı ya da montajdaki parça hataya atanır ve yeniden
üretime girer; parçanın bölümü monte edilmişse bölüm montajı geri alınır (diğer parçalar depoya döner, onayları kalır);
uçak montajdaysa sipariş üretime döner. Montajı geçmiş uçakta ve üretimdeki parçada reddedilir.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_assembly_reject
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
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
    sec = lambda key: [p for p, s in sections.items() if s == key and p not in covers]   # noqa: E731
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        mk = lambda u, roles: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,   # noqa: E731
                                                            'password': 'sifre-1234'}))['id']
        m1, m2 = mk('m1', ['Montaj Personeli']), mk('m2', ['Montaj Personeli'])
        cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
        oid = ok(a.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']
        url = f'/api/orders/{oid}'

        def to_depot(parts):
            with db.connect() as c:
                c.executemany("UPDATE order_parts SET state = 'DEPO', finished_at = ?, approved_at = ? WHERE order_id = ? AND part_id = ?",
                              [(db.now(), db.now(), oid, p) for p in parts])
                recompute(c, oid)

        def states():
            return {p['part_id']: p for p in ok(a.get(url))['parts']}

        left = sec('SOL_KANAT')
        bad = 'L12' if 'L12' in left else left[0]
        # 1) Sol kanat depoda, gövde basılıyor → kanat erken monte edilir
        to_depot(left)
        with db.connect() as c:
            c.execute("UPDATE order_parts SET state = 'URETIMDE' WHERE order_id = ? AND part_id = ?", (oid, sec('GOVDE')[0]))
            recompute(c, oid)
        assert ok(a.post(f'{url}/assembly/SOL_KANAT', json={'staff_ids': [m1, m2]}))['status'] == 'URETIM'
        assert states()[bad]['state'] == 'MONTAJ'
        # üretimdeki parça montaj hatasına atanamaz
        assert a.post(f'{url}/parts/{sec("GOVDE")[0]}/assembly-error', data={'error_code': 'M-1'}).status_code == 400
        # 2) Montajda L12 hatalı bulunur: bölüm geri alınır, L12 hataya, diğer kanat parçaları depoya (onaylı), sipariş üretimde
        r = ok(a.post(f'{url}/parts/{bad}/assembly-error', data={'error_code': 'M-101', 'description': 'Çatlak'}))
        assert r['status'] == 'HATA' and r['undone'] == [names['SOL_KANAT']], r   # hatalı parça varken sipariş HATA (mevcut kural)
        st = states()
        assert st[bad]['state'] == 'HATA' and st[bad]['approved_at'] is None
        others = [p for p in left if p != bad]
        assert all(st[p]['state'] == 'DEPO' and st[p]['approved_at'] for p in others)
        o = ok(a.get(url))
        assert 'SOL_KANAT' not in o['assembly']['steps'] and o['status'] == 'HATA'
        d = ok(a.get(f'{url}/parts/{bad}'))
        assert d['events'][-1]['event'] == 'MONTAJ_HATASI' and d['events'][-1]['error_code'] == 'M-101'
        # hatalı parça yeniden üretime alınabilir
        pid = ok(a.post('/api/printers', json={'name': 'Y1', 'ip': '10.0.0.5'}))['id']
        ok(a.post(f'{url}/parts/{bad}/start', json={'printer_id': pid}))
        assert states()[bad]['state'] == 'URETIMDE' and ok(a.get(url))['status'] == 'URETIM'   # yeniden üretime alınınca ÜRETİM
        # kanat yeniden depoya girince bölüm yeniden monte edilebilir
        to_depot([bad])
        assert ok(a.post(f'{url}/assembly/SOL_KANAT', json={'staff_ids': [m1, m2]}))['status'] == 'URETIM'
        # 3) Uçak montajdayken (tüm parçalar depoda) depoda onaylı parça hataya atanınca sipariş üretime döner
        to_depot([p for p in sections if p not in left] + list(eparts))
        o = ok(a.get(url))
        assert o['status'] == 'MONTAJ', o['status']
        victim = sec('SAG_KANAT')[0]
        assert states()[victim]['state'] == 'MONTAJ'   # montaja alınmış, bölüm adımı yok
        r = ok(a.post(f'{url}/parts/{victim}/assembly-error', data={'error_code': 'M-2'}))
        assert r['status'] == 'HATA' and r['undone'] == []
        assert states()[victim]['state'] == 'HATA' and ok(a.get(url))['status'] == 'HATA'   # montajdan çıktı; yeniden üretimle ÜRETİM olur
        # 4) Montajı geçmiş uçakta reddedilir
        with db.connect() as c:
            c.execute("UPDATE orders SET status = 'KALIBRASYON' WHERE id = ?", (oid,))
        assert a.post(f'{url}/parts/{left[1]}/assembly-error', data={'error_code': 'M-3'}).status_code == 400
    print('Montaj hatası testleri geçti.')


if __name__ == '__main__':
    main()
