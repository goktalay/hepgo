"""Uçtan uca akış testi: sipariş → üretim → hata → depo onayı → montaj → saha görevi.

Çalıştırma: .venv/bin/python -m tests.test_flow
"""
import os
import tempfile
import time
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
                  # Mikro ERP bu testte devre dışı (yerel .env'den sızmasın): modül seti deterministik kalsın.
                  CAYMAZ_MIKRO_DB='', CAYMAZ_MIKRO_USER='', CAYMAZ_MIKRO_PASSWORD='')

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, plane  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


SAMPLE_LOG = (Path(__file__).parent / 'data' / 'arduplane-sample.bin').read_bytes()


def wait_log(client, lid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        log = ok(client.get(f'/api/flight-logs/{lid}'))
        if log['status'] != 'ISLENIYOR':
            return log
        time.sleep(0.2)
    raise AssertionError('analiz zaman aşımı')


def admin_get_order(oid):
    with TestClient(app) as c:
        login(c, 'admin@test', 'admin-sifre-1')
        return c.get(f'/api/orders/{oid}')


def ok_users():
    with db.connect() as c:
        return db.rows(c.execute('SELECT id, username FROM users'))


def notes(client):
    """Kullanıcının bildirimleri, türe göre."""
    return {n['key']: n for n in ok(client.get('/api/notifications'))['items'] if n['key'] != 'docs-missing'}   # eksik evrak (tests/test_my_docs)


def main():
    with TestClient(app) as admin:
        assert admin.get('/api/auth/me').status_code == 401
        assert admin.post('/api/auth/login', json={'username': 'admin@test', 'password': 'x'}).status_code == 401
        login(admin, 'admin@test', 'admin-sifre-1')
        me = ok(admin.get('/api/auth/me'))
        assert set(me['modules']) == {'admin', 'production', 'orders', 'warehouse', 'stock', 'field', 'printers',
                                      'products', 'tools', 'users', 'companies', 'documents', 'secretariat', 'security', 'reports', 'announcements', 'hr', 'mrp', 'purchasing', 'sales', 'cleaning', 'design'}
        assert admin.get('/api/printers').status_code == 200

        def mk(name, roles):
            return ok(admin.post('/api/users', json={'username': name, 'full_name': name.title(),
                                                     'roles': roles, 'password': 'sifre-1234'}))['id']
        depocu = mk('depocu', ['Depo Yöneticisi'])
        mk('uretici', ['Üretim Sorumlusu'])
        sofor = mk('sofor', ['Şoför'])
        saha1, saha2 = mk('saha1', ['Saha Personeli']), mk('saha2', ['Saha Personeli'])
        mk('sahasef', ['Saha Sorumlusu'])
        m1, m2 = mk('montaj1', ['Montaj Personeli']), mk('montaj2', ['Montaj Personeli'])
        el = mk('elektro', ['Elektronik Personeli'])
        pil = mk('ucucu', ['Pilot'])

        mk('yazici', ['Yazıcı Bakım Sorumlusu'])
        with TestClient(app) as yc:
            login(yc, 'yazici', 'sifre-1234')
            p1 = ok(yc.post('/api/printers', json={'name': 'K2-01', 'ip': '10.0.0.11'}))['id']
            p2 = ok(yc.post('/api/printers', json={'name': 'K2-02', 'ip': '10.0.0.12'}))['id']
            assert yc.post('/api/printers', json={'name': 'dup', 'ip': '10.0.0.11'}).status_code == 400
            assert notes(yc) == {}
            with db.connect() as c:
                c.execute("UPDATE printers SET live_state = 'CEVRIMDISI' WHERE id = ?", (p2,))
            n = notes(yc)['printers-down']   # bakım sorumlusu: ulaşılamayan yazıcı
            assert n['names'] == ['K2-02'] and n['detail'] == '1 çevrimdışı'
            with db.connect() as c:
                c.execute('UPDATE printers SET live_state = NULL WHERE id = ?', (p2,))

        products = ok(admin.get('/api/products'))
        assert [(p['name'], p['serial'], p['part_count']) for p in products if p['type'] == 'MAMUL'] == [('CAYMAZ', 'CYZ-S1', 64)]
        prod = products[0]
        assert admin.post('/api/orders', json={'product_id': 999}).status_code == 400
        order = ok(admin.post('/api/orders', json={'product_id': prod['id'], 'quantity': 1,
                                                   'start_date': '2026-09-24', 'end_date': '2026-10-01'}))[0]
        assert ok(admin.get(f'/api/orders/{order["id"]}'))['product_serial'] == 'CYZ-S1'
        edit = {'name': 'CAYMAZ', 'serial': 'CYZ-S1', 'code': 'XYZ', 'queue_prefix': 'CYZ', 'active': True}
        assert admin.put(f'/api/products/{prod["id"]}', json=edit).status_code == 400   # siparişi var
        ok(admin.put(f'/api/products/{prod["id"]}', json={**edit, 'code': 'CYZ', 'description': 'test'}))
        assert admin.put(f'/api/products/{prod["id"]}', json={**edit, 'code': 'CYZ', 'active': False}).status_code == 400
        assert len(ok(admin.get(f'/api/products/{prod["id"]}/plane'))['parts']) == 64
        oid = order['id']
        detail = ok(admin.get(f'/api/orders/{oid}'))
        assert len(detail['parts']) == len(plane.part_ids()) == 64
        assert detail['status'] == 'SIPARIS'

    # Yetki: üretim sorumlusu sipariş açamaz, kullanıcı listeleyemez
    with TestClient(app) as prod:
        login(prod, 'uretici', 'sifre-1234')
        assert prod.post('/api/orders', json={'quantity': 1}).status_code == 403
        assert prod.get('/api/users').status_code == 403
        assert prod.put('/api/products/1', json={}).status_code in (403, 422)
        assert len(ok(prod.get('/api/products'))) == 72   # CAYMAZ + 4 yarı mamul + 3 yedek parça + 64 parça yedeği
        assert len(ok(prod.get('/api/printers'))) == 2

        ok(prod.post(f'/api/orders/{oid}/parts/09/start', json={'printer_id': p1}))
        assert prod.post(f'/api/orders/{oid}/parts/08/start', json={'printer_id': p1}).status_code == 409
        assert prod.get('/api/admin/dashboard').status_code == 403
        with TestClient(app) as adm:
            login(adm, 'admin@test', 'admin-sifre-1')
            dash = ok(adm.get('/api/admin/dashboard'))
            assert {u['username'] for u in dash['online']} >= {'uretici', 'admin@test'}
            assert dash['summary']['parts_printing'] == 1 and dash['summary']['orders_open'] == 1
            job = dash['products'][0]['printing'][0]
            assert job['part_id'] == '09' and job['printer'] == 'K2-01' and job['remaining'] is None
            # Yazıcı kendi durumunu "hazır" bildiriyor: K2-01 sistemde üretimde (uyumsuz), K2-02 gerçekten boşta
            with db.connect() as c:
                c.execute("UPDATE printers SET live_state = 'HAZIR'")
            s = ok(adm.get('/api/admin/dashboard'))['summary']
            assert s['printers_stale'] == 1 and s['stale_printers'][0]['name'] == 'K2-01'
            assert s['printers_really_idle'] == 1 and s['printing_outside'] == 0
            with db.connect() as c:
                c.execute("UPDATE printers SET live_state = 'YAZDIRIYOR' WHERE name = 'K2-02'")
            s = ok(adm.get('/api/admin/dashboard'))['summary']
            assert s['printing_outside'] == 1 and s['outside_printers'][0]['name'] == 'K2-02'
            # Üst çubuk uyarıları: herkese açık (üretim sorumlusu da görür)
            al = ok(prod.get('/api/alerts'))
            assert al['total'] == 2 and {a['key'] for a in al['alerts']} == {'printer-stale', 'printer-outside'}
            d = ok(prod.get('/api/alerts/printer-stale'))
            assert d['items'][0]['name'] == 'K2-01' and d['items'][0]['part_id'] == '09'
            with db.connect() as c:   # iki yazıcı aynı türde → rozet yine tür sayısı
                c.execute("UPDATE printers SET live_state = 'YAZDIRIYOR', current_part_id = NULL WHERE name = 'K2-01'")
            al = ok(prod.get('/api/alerts'))
            assert al['total'] == 1 and al['records'] == 2 and al['alerts'][0]['count'] == 2
            with db.connect() as c:
                c.execute("UPDATE printers SET live_state = 'HAZIR', current_part_id = "
                          "(SELECT id FROM order_parts WHERE part_id = '09') WHERE name = 'K2-01'")
                c.execute("UPDATE printers SET live_state = 'HATA' WHERE name = 'K2-02'")
            al = ok(prod.get('/api/alerts'))
            assert [a['key'] for a in al['alerts']] == ['printer-error', 'printer-stale']
            assert prod.get('/api/alerts/yok').status_code == 404
            with db.connect() as c:
                c.execute('UPDATE printers SET live_state = NULL')
            ok(adm.put('/api/auth/prefs/adminTiles', json=['online_users', 'printers_stale']))
            assert ok(adm.get('/api/auth/me'))['prefs']['adminTiles'] == ['online_users', 'printers_stale']
            with TestClient(app) as tmp:
                login(tmp, 'depocu', 'sifre-1234')
                assert 'depocu' in {u['username'] for u in ok(adm.get('/api/admin/dashboard'))['online']}
                ok(tmp.post('/api/auth/logout'))
            assert 'depocu' not in {u['username'] for u in ok(adm.get('/api/admin/dashboard'))['online']}
        assert ok(prod.get(f'/api/orders/{oid}'))['status'] == 'URETIM'
        d = ok(prod.get(f'/api/orders/{oid}/parts/09'))
        assert d['state'] == 'URETIMDE' and 'elapsed_seconds' in d

        # Hata → sipariş HATA, yazıcı boşalır, parça yeniden başlatılabilir
        ok(prod.post(f'/api/orders/{oid}/parts/09/error',
                     data={'error_code': 'E-12', 'description': 'Katman kayması'},
                     files={'photo': ('hata.jpg', b'\xff\xd8\xff fake', 'image/jpeg')}))
        assert ok(prod.get(f'/api/orders/{oid}'))['status'] == 'HATA'
        ev = ok(prod.get(f'/api/orders/{oid}/parts/09'))['events'][-1]
        assert ev['error_code'] == 'E-12' and ev['photo'].startswith('errors/')
        assert prod.get(f'/api/files/{ev["photo"]}').status_code == 200
        n = notes(prod)   # üretim sorumlusu: hata veren parça bildirimi
        assert n['production-error']['names'] == ['SP-0001 / 09 (E-12)'] and n['production-error']['href'] == f'#/production/{oid}'

        # Tüm parçaları üret ve depoya teslim et
        assert prod.post(f'/api/orders/{oid}/parts/08/start', json={'printer_id': p1}).status_code == 200
        # Saat dilimli zaman sunucunun yerel saatine çevrilir; ileri tarih serbest
        from datetime import datetime as _dt, timezone as _tz
        utc = _dt(2031, 5, 1, 9, 0, tzinfo=_tz.utc)
        assert db.pick_time('2031-05-01T12:00+03:00') == utc.astimezone().replace(tzinfo=None).isoformat(timespec='seconds')
        r = prod.post(f'/api/orders/{oid}/parts/08/finish', json={'warehouse_user_id': depocu, 'at': '2020-01-01T08:00'})
        assert r.status_code == 400 and 'önce olamaz' in r.json()['detail']   # başlamadan önce teslim olmaz
        assert prod.post(f'/api/orders/{oid}/parts/08/finish',
                         json={'warehouse_user_id': depocu, 'at': 'dun'}).status_code == 400
        from datetime import datetime, timedelta
        chosen = (datetime.now() - timedelta(minutes=0)).replace(second=0, microsecond=0).isoformat(timespec='minutes')
        ok(prod.post(f'/api/orders/{oid}/parts/08/finish', json={'warehouse_user_id': depocu, 'at': chosen}))
        assert ok(prod.get(f'/api/orders/{oid}/parts/08'))['finished_at'] == chosen + ':00'
        assert prod.post(f'/api/orders/{oid}/parts/08/finish',
                         json={'warehouse_user_id': depocu}).status_code == 400
        for pid in plane.part_ids():
            if pid == '08':
                continue
            ok(prod.post(f'/api/orders/{oid}/parts/{pid}/start', json={'printer_id': p2}))
            if pid != '09':
                assert prod.post(f'/api/orders/{oid}/parts/{pid}/finish',
                                 json={'warehouse_user_id': sofor}).status_code == 400
            ok(prod.post(f'/api/orders/{oid}/parts/{pid}/finish', json={'warehouse_user_id': depocu}))
        o = ok(prod.get(f'/api/orders/{oid}'))
        assert o['status'] == 'DEPO' and o['progress'] == 100, o['status']
        assert prod.post(f'/api/orders/{oid}/assembly/GOVDE', json={'staff_ids': [m1, m2]}).status_code == 400
        assert notes(prod) == {}   # depo yöneticisi olmayan depo bildirimini görmez

    with TestClient(app) as depo:
        login(depo, 'depocu', 'sifre-1234')
        pending = ok(depo.get('/api/warehouse/pending'))
        assert len(pending) == 64
        nt = notes(depo)   # depocu: onay bekleyen parça bildirimi
        assert set(nt) == {'warehouse-pending'} and nt['warehouse-pending']['count'] == 64
        assert nt['warehouse-pending']['detail'] == '64 tanesi size teslim edildi'
        stock = ok(depo.get('/api/stock'))
        assert stock['pending_counts']['09'] == 1 and stock['part_counts']['09'] == 0
        ok(depo.post('/api/warehouse/approve', json={'ids': [p['id'] for p in pending[:-1]]}))
        assert ok(depo.get('/api/stock'))['part_counts']['09'] == 1
        assert len(ok(depo.get('/api/warehouse/pending'))) == 1
        ok(depo.post('/api/warehouse/approve', json={'ids': [pending[-1]['id']]}))
        assert notes(depo) == {}

    with TestClient(app) as prod:
        login(prod, 'uretici', 'sifre-1234')
        o = ok(prod.get(f'/api/orders/{oid}'))
        # Elektronik parçalar (elektronik kat, K04) depoda kalır, diğer parçalar montaja alınır
        assert o['status'] == 'MONTAJ' and all(p['state'] == ('DEPO' if p['part_id'] in ('EK', 'K04') else 'MONTAJ') for p in o['parts'])
        assert [(e['part_id'], e['step'], e['state']) for e in o['assembly']['electronics']] == [
            ('EK', 'ELEKTRONIK_EK', 'DEPO'), ('K04', 'ELEKTRONIK_K04', 'DEPO')]
        assert set(notes(prod)) == {'assembly-waiting'}   # hata kapandı, montaj bekliyor
        assert prod.post(f'/api/orders/{oid}/parts/09/start', json={'printer_id': p1}).status_code == 400
        asm = o['assembly']
        assert list(asm['sections']) == ['SOL_KANAT', 'SAG_KANAT', 'GOVDE'] and asm['steps'] == {}
        url = f'/api/orders/{oid}/assembly'
        assert prod.post(f'{url}/GOVDE', json={'staff_ids': [m1]}).status_code == 400            # en az 2 personel
        assert prod.post(f'{url}/GOVDE', json={'staff_ids': [m1, depocu]}).status_code == 400    # montaj personeli değil
        assert prod.post(f'{url}/GOVDE', json={'staff_ids': [m1, m2], 'at': '2020-01-01T10:00'}).status_code == 400
        assert prod.post(f'{url}/KANAT', json={'staff_ids': [m1, m2]}).status_code == 404
        assert ok(prod.post(f'{url}/GOVDE', json={'staff_ids': [m1, m2, m2]}))['status'] == 'MONTAJ'
        assert prod.post(f'{url}/GOVDE', json={'staff_ids': [m1, m2]}).status_code == 400        # tekrar
        assert notes(prod)['assembly-waiting']['names'] == ['SP-0001 (Sol Kanat, Sağ Kanat, Elektronik: EK, Elektronik: K04, Birleştirme, Kapak)']
        assert prod.post(f'/api/orders/{oid}/calibration', json={'staff_ids': [m1, m2]}).status_code == 400   # montaj bitmedi
        ok(prod.post(f'{url}/SOL_KANAT', json={'staff_ids': [m1, m2]}))
        # Üç bölüm bitti ama elektronik kat monte edilmedi: kalibrasyona geçmez
        assert ok(prod.post(f'{url}/SAG_KANAT', json={'staff_ids': [m1, m2]}))['status'] == 'MONTAJ'
        assert notes(prod)['assembly-waiting']['names'] == ['SP-0001 (Elektronik: EK, Elektronik: K04, Birleştirme, Kapak)']
        assert prod.post(f'/api/orders/{oid}/calibration', json={'staff_ids': [m1, m2]}).status_code == 400
        assert prod.post(f'/api/orders/{oid}/electronics/EK', json={'staff_ids': []}).status_code == 400
        assert prod.post(f'/api/orders/{oid}/electronics/EK', json={'staff_ids': [m1]}).status_code == 400   # elektronikçi değil
        assert prod.post(f'/api/orders/{oid}/electronics/K01', json={'staff_ids': [el]}).status_code == 404
        fin = {'wings': True, 'electronics': True}
        assert prod.post(f'/api/orders/{oid}/final', json={'staff_ids': [m1, m2], 'checklist': fin}).status_code == 400   # elektronik bitmedi
        with TestClient(app) as ec:   # elektronik personeli: bildirimi görür, montajı kaydeder
            login(ec, 'elektro', 'sifre-1234')
            assert notes(ec)['electronics-waiting']['names'] == ['SP-0001 / EK', 'SP-0001 / K04']
            assert ok(ec.post(f'/api/orders/{oid}/electronics/EK', json={'staff_ids': [el]}))['status'] == 'MONTAJ'
            assert ec.post(f'/api/orders/{oid}/electronics/EK', json={'staff_ids': [el]}).status_code == 400
            assert notes(ec)['electronics-waiting']['names'] == ['SP-0001 / K04']
            assert ok(ec.post(f'/api/orders/{oid}/electronics/K04', json={'staff_ids': [el]}))['status'] == 'MONTAJ'
            assert notes(ec) == {}
        # Birleştirme montajı: kanatlar ve elektronik parçalar gövdeye takılır; ardından kapaklar, sonra kalibrasyon
        assert notes(prod)['assembly-waiting']['names'] == ['SP-0001 (Birleştirme, Kapak)']
        assert prod.post(f'/api/orders/{oid}/covers', json={'staff_ids': [m1]}).status_code == 400   # önce birleştirme
        assert ok(prod.get(f'/api/orders/{oid}'))['assembly']['final']['ready'] is True
        assert prod.post(f'/api/orders/{oid}/final', json={'staff_ids': [m1, m2], 'checklist': {'wings': True}}).status_code == 400
        assert prod.post(f'/api/orders/{oid}/final', json={'staff_ids': [m1], 'checklist': fin}).status_code == 400
        assert ok(prod.post(f'/api/orders/{oid}/final', json={'staff_ids': [m1, m2], 'checklist': fin}))['status'] == 'MONTAJ'
        assert prod.post(f'/api/orders/{oid}/final', json={'staff_ids': [m1, m2], 'checklist': fin}).status_code == 400
        assert notes(prod)['assembly-waiting']['names'] == ['SP-0001 (Kapak)']
        assert prod.post(f'/api/orders/{oid}/calibration', json={'staff_ids': [m1, m2]}).status_code == 400   # kapaklar takılmadı
        assert prod.post(f'/api/orders/{oid}/covers', json={'staff_ids': []}).status_code == 400
        r = ok(prod.post(f'/api/orders/{oid}/covers', json={'staff_ids': [m1]}))
        assert r['status'] == 'KALIBRASYON' and r['queue_no'] == 'CYZ-0001'   # montaj bitti: kuyruk no (metal etiket)
        assert ok(prod.get(f'/api/orders/{oid}'))['queue_no'] == 'CYZ-0001'
        assert prod.post(f'/api/orders/{oid}/covers', json={'staff_ids': [m1]}).status_code == 400
        ev = ok(prod.get(f'/api/orders/{oid}/parts/K01'))['events'][-1]
        assert ev['event'] == 'MONTAJ_TAMAMLANDI' and ev['note'] == 'Kapak montajı'
        o = ok(prod.get(f'/api/orders/{oid}'))
        assert o['status'] == 'KALIBRASYON' and [s['full_name'] for s in o['assembly']['steps']['GOVDE']['staff']] == ['Montaj1', 'Montaj2']
        assert ok(prod.get(f'/api/orders/{oid}/parts/EK'))['events'][-1]['event'] == 'ELEKTRONIK_MONTAJ'
        assert o['assembly']['steps']['ELEKTRONIK_EK']['staff'][0]['full_name'] == 'Elektro'
        assert ok(prod.get(f'/api/orders/{oid}/parts/K04'))['state'] == 'MONTAJ'
        ev = ok(prod.get(f'/api/orders/{oid}/parts/L18'))['events'][-1]
        assert ev['event'] == 'MONTAJ_TAMAMLANDI' and ev['note'] == 'Sol Kanat'
        assert set(notes(prod)) == {'calibration-waiting'}
        checks = {k: True for k in o['assembly']['checks']}
        cal = f'/api/orders/{oid}/calibration'
        r = prod.post(cal, json={'staff_ids': [m1, m2], 'checklist': {**checks, 'cg': False}})
        assert r.status_code == 400 and 'CG' in r.json()['detail']
        assert prod.post(cal, json={'staff_ids': [m1], 'checklist': checks}).status_code == 400
        ok(prod.post(cal, json={'staff_ids': [m1, m2], 'checklist': checks}))
        o = ok(prod.get(f'/api/orders/{oid}'))
        assert o['status'] == 'SAHA_ONAY' and o['assembly']['steps']['KALIBRASYON']['checklist'] == checks
        assert notes(prod) == {}
        assert prod.post(f'/api/warehouse/aircraft/{oid}/approve', json={}).status_code == 403   # depo modülü yok

    with TestClient(app) as mc:   # montaj personeli: üretime girer, parça işlemi yapamaz
        login(mc, 'montaj1', 'sifre-1234')
        assert mc.get(f'/api/orders/{oid}').status_code == 200
        assert mc.post(f'/api/orders/{oid}/parts/09/start', json={'printer_id': p1}).status_code == 403

    with TestClient(app) as depo:   # saha deposu onayı: kuyruk numarası verilir, uçak sahaya gidebilir
        login(depo, 'depocu', 'sifre-1234')
        assert notes(depo)['field-depot-pending']['names'] == ['SP-0001']
        ac = ok(depo.get('/api/warehouse/aircraft'))
        assert [a['code'] for a in ac['pending']] == ['SP-0001'] and ac['approved'] == []
        assert depo.post(f'/api/warehouse/aircraft/{oid}/approve', json={'at': '2020-01-01T00:00'}).status_code == 400
        assert ok(depo.post(f'/api/warehouse/aircraft/{oid}/approve', json={}))['queue_no'] == 'CYZ-0001'
        assert depo.post(f'/api/warehouse/aircraft/{oid}/approve', json={}).status_code == 400
        ac = ok(depo.get('/api/warehouse/aircraft'))
        assert ac['pending'] == [] and ac['approved'][0]['steps']['SAHA_DEPO']['recorded_by_name'] == 'Depocu'
        assert set(notes(depo)) <= {'spares-low'}, notes(depo)   # montajla kamera tutucu stoğu bitti
        o = ok(depo.get(f'/api/stock'))
        assert [a['queue_no'] for a in o['ready_aircraft']] == ['CYZ-0001']

    # İkinci bir tamamlanmış uçak (hızlı kurulum): çok uçaklı saha görevi için
    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        oid2 = ok(admin.post('/api/orders', json={'quantity': 1}))[0]['id']
    with db.connect() as c:
        c.execute("UPDATE orders SET status = 'TAMAMLANDI', queue_no = 'CYZ-0002' WHERE id = ?", (oid2,))

    with TestClient(app) as saha:
        login(saha, 'sahasef', 'sifre-1234')
        me = ok(saha.get('/api/auth/me'))['id']
        av = ok(saha.get('/api/field/available-aircraft'))
        assert [a['queue_no'] for a in av if a['status'] == 'TAMAMLANDI'] == ['CYZ-0001', 'CYZ-0002']
        base = {'order_ids': [oid, oid2], 'lead_id': me, 'pilot_id': pil, 'staff_ids': [saha1, saha2]}   # şoför görevde değil
        assert saha.post('/api/field/tasks', json={**base, 'pilot_id': None}).status_code == 400    # pilot zorunlu
        assert saha.post('/api/field/tasks', json={**base, 'pilot_id': sofor}).status_code == 400   # pilot değil
        assert saha.post('/api/field/tasks', json={**base, 'driver_id': saha1}).status_code == 400   # şoför değil
        assert saha.post('/api/field/tasks', json={**base, 'lead_id': saha1}).status_code == 400     # sorumlu değil
        assert saha.post('/api/field/tasks', json={**base, 'order_ids': []}).status_code == 400
        # Görev yerleri ve araçlar
        loc = ok(saha.post('/api/field/locations', json={'name': 'Test Sahası'}))['id']
        assert saha.post('/api/field/locations', json={'name': 'test sahası'}).status_code == 400
        car = ok(saha.post('/api/field/vehicles', json={'plate': '06 abc 123', 'description': 'Pikap'}))['id']
        assert ok(saha.get('/api/field/vehicles'))[0]['plate'] == '06 ABC 123'
        t = ok(saha.post('/api/field/tasks', json={**base, 'location_id': loc}))
        assert t['code'] == 'GRV-0001'
        assert notes(saha) == {}   # görevi kendisi açtı: atama bildirimi yok
        # Araçlar ve şoförleri görevin içinden eklenir (birden fazla araç)
        rid = ok(saha.post(f'/api/field/tasks/{t["id"]}/vehicles', json={'vehicle_id': car, 'driver_id': sofor}))['id']
        assert saha.post(f'/api/field/tasks/{t["id"]}/vehicles', json={'vehicle_id': car}).status_code == 400   # aynı araç
        assert saha.post(f'/api/field/tasks/{t["id"]}/vehicles', json={'vehicle_id': car, 'driver_id': saha1}).status_code == 400
        car2 = ok(saha.post('/api/field/vehicles', json={'plate': '34 xy 99'}))['id']
        rid2 = ok(saha.post(f'/api/field/tasks/{t["id"]}/vehicles', json={'vehicle_id': car2, 'driver_id': sofor, 'start_km': 500}))['id']
        for who in ('sofor', 'saha1'):
            with TestClient(app) as c:
                login(c, who, 'sifre-1234')
                n = notes(c)
                assert list(n) == ['field-assigned'] and n['field-assigned']['href'] == f'#/field/task/{t["id"]}'
        assert ok(saha.get('/api/field/available-aircraft')) == []
        tid = t['id']
        task = ok(saha.get(f'/api/field/tasks/{tid}'))
        assert task['lead_name'] == 'Sahasef' and len(task['flights']) == 2 and task['location_name'] == 'Test Sahası'
        assert task['pilot_name'] == 'Ucucu'
        f1, f2 = task['flights']
        assert saha.post(f'/api/field/flights/{f1["id"]}/flight-log', files={'file': ('u.bin', SAMPLE_LOG)}).status_code == 400
        assert saha.post(f'/api/field/tasks/{tid}/finish', json={'success': True}).status_code == 400
        assert saha.post(f'/api/field/tasks/{tid}/start', json={'at': '2020-05-01T09:00'}).status_code == 400
        ok(saha.post(f'/api/field/tasks/{tid}/start'))
        # Uçuş Yönetimi: fırlatma sistemi + log (uçuş başına)
        ok(saha.put(f'/api/field/flights/{f1["id"]}', json={'launch': 'ARAC_USTU'}))
        ok(saha.put(f'/api/field/flights/{f2["id"]}', json={'launch': 'RAMPA', 'note': 'rüzgârlı'}))
        assert saha.put(f'/api/field/flights/{f1["id"]}', json={'launch': 'UCAK'}).status_code == 400
        # Uçuş videosu: parça parça yükleme, izleme (Range), silme
        video = bytes(range(256)) * 400                       # 100 KB
        assert saha.post(f'/api/field/flights/{f1["id"]}/videos', json={'file_name': 'a.exe', 'size': 10}).status_code == 400
        up = ok(saha.post(f'/api/field/flights/{f1["id"]}/videos', json={'file_name': 'ucus.mp4', 'size': len(video)}))['upload_id']
        assert saha.put(f'/api/field/uploads/{up}?offset=5', content=video[:10]).status_code == 409
        ok(saha.put(f'/api/field/uploads/{up}?offset=0', content=video[:60000]))
        assert saha.post(f'/api/field/uploads/{up}/complete').status_code == 400   # eksik
        ok(saha.put(f'/api/field/uploads/{up}?offset=60000', content=video[60000:]))
        vid = ok(saha.post(f'/api/field/uploads/{up}/complete'))['id']
        v = ok(saha.get(f'/api/field/tasks/{tid}'))['flights'][0]['videos'][0]
        assert v['id'] == vid and v['size'] == len(video) and v['file_name'] == 'ucus.mp4'
        r = saha.get(f'/api/files/{v["file"]}', headers={'Range': 'bytes=100-199'})
        assert r.status_code == 206 and r.content == video[100:200]
        up2 = ok(saha.post(f'/api/field/flights/{f1["id"]}/videos', json={'file_name': 'b.mov', 'size': 3}))['upload_id']
        ok(saha.put(f'/api/field/uploads/{up2}?offset=0', content=b'abc'))
        ok(saha.post(f'/api/field/uploads/{up2}/complete'))
        assert len(ok(saha.get(f'/api/field/tasks/{tid}'))['flights'][0]['videos']) == 2
        ok(saha.delete(f'/api/field/videos/{vid}'))
        assert saha.get(f'/api/files/{v["file"]}').status_code == 404
        assert saha.post(f'/api/field/flights/{f1["id"]}/flight-log',
                         files={'file': ('rapor.pdf', b'%PDF', 'application/pdf')}).status_code == 400
        lid = ok(saha.post(f'/api/field/flights/{f1["id"]}/flight-log', files={'file': ('ucus.bin', SAMPLE_LOG)}))['id']
        log = wait_log(saha, lid)
        assert log['status'] == 'TAMAM', log.get('error')
        assert log['analysis']['summary']['firmware'].startswith('ArduPlane')
        assert log['task']['code'] == 'GRV-0001' and log['aircraft'] == 'CYZ-0001'
        assert log['flight']['launch_text'] == 'Araç Üstü' and log['location'] == 'Test Sahası'
        # Masraf Yönetimi
        ok(saha.post(f'/api/field/tasks/{tid}/expenses', data={'spent_on': '2026-09-25', 'category': 'Yakıt',
                                                               'amount': '1250.50', 'description': 'Mazot'},
                     files={'receipt': ('fis.jpg', b'\xff\xd8\xff', 'image/jpeg')}))
        ok(saha.post(f'/api/field/tasks/{tid}/expenses', data={'spent_on': '2026-09-25', 'category': 'Yemek', 'amount': '300',
                                                               'spent_by': str(pil)}))   # masrafı pilot yaptı
        assert saha.post(f'/api/field/tasks/{tid}/expenses', data={'spent_on': '2026-09-25', 'category': 'Yemek', 'amount': '5',
                                                                  'spent_by': '99999'}).status_code == 400
        ex = ok(saha.get(f'/api/field/tasks/{tid}'))['expenses']
        assert {e['category']: e['spent_by_name'] for e in ex} == {'Yemek': 'Ucucu', 'Yakıt': 'Sahasef'}
        assert saha.post(f'/api/field/tasks/{tid}/expenses', data={'spent_on': '2026-09-25', 'category': 'Kumar',
                                                                  'amount': '5'}).status_code == 400
        assert saha.post(f'/api/field/tasks/{tid}/expenses', data={'spent_on': '2026-09-25', 'category': 'Yemek',
                                                                  'amount': '-5'}).status_code == 400
        # Görev bitti ama ikinci uçuşun raporu yok → Rapor Tamamlandı olmamalı
        ok(saha.post(f'/api/field/tasks/{tid}/finish', json={'success': True}))
        task = ok(saha.get(f'/api/field/tasks/{tid}'))
        assert task['status'] == 'GOREV_TAMAMLANDI' and task['logs_ready'] == 1
        n = notes(saha)['field-report-lead']   # saha sorumlusu: raporu eksik uçuş
        assert n['count'] == 1 and n['names'] == ['GRV-0001 / CYZ-0002'] and n['href'] == f'#/field/task/{tid}'
        with TestClient(app) as c:   # şoför: bitmiş görevde yol bilgisi eksik; artık atama bildirimi yok
            login(c, 'sofor', 'sifre-1234')
            assert notes(c)['field-road']['names'] == ['GRV-0001: 06 ABC 123 başlangıç km, bitiş km; 34 XY 99 bitiş km']
            assert 'field-assigned' not in notes(c)
        assert task['expense_total'] == 1550.5
        assert next(e for e in task['expenses'] if e['category'] == 'Yakıt')['receipt'].startswith('receipts/')
        lid2 = ok(saha.post(f'/api/field/flights/{f2["id"]}/flight-log', files={'file': ('ucus2.bin', SAMPLE_LOG)}))['id']
        assert wait_log(saha, lid2)['status'] == 'TAMAM'
        task = ok(saha.get(f'/api/field/tasks/{tid}'))
        assert task['status'] == 'RAPOR_TAMAMLANDI' and task['logs_ready'] == 2
        assert notes(saha) == {}
        assert saha.delete(f'/api/field/locations/{loc}').status_code == 400   # görevde kullanılıyor

    # Yol Yönetimi: her şoför kendi aracının km'sini girer; araç ekleme/çıkarma saha yöneticisinde
    with TestClient(app) as sc:
        login(sc, 'sofor', 'sifre-1234')
        assert sc.put(f'/api/field/task-vehicles/{rid}', json={'start_km': 100, 'end_km': 50}).status_code == 400
        ok(sc.put(f'/api/field/task-vehicles/{rid}', json={'start_km': 12000, 'end_km': 12240}))
        ok(sc.put(f'/api/field/task-vehicles/{rid2}', json={'start_km': 500, 'end_km': 560}))
        assert sc.put(f'/api/field/tasks/{tid}/road', json={'location_id': loc}).status_code == 403
        assert sc.post(f'/api/field/tasks/{tid}/vehicles', json={'vehicle_id': car2}).status_code == 403
        assert sc.delete(f'/api/field/task-vehicles/{rid2}').status_code == 403
        task = ok(sc.get(f'/api/field/tasks/{tid}'))
        assert task['distance_km'] == 300 and task['vehicle_plate'] == '06 ABC 123, 34 XY 99'
        assert [v['distance_km'] for v in task['vehicles']] == [240, 60]
        assert notes(sc) == {}
        assert task['can'] == {'manage': False, 'flights': False, 'expenses': True, 'road': False, 'road_own': [rid, rid2], 'isg': False}
        assert sc.put(f'/api/field/flights/{f1["id"]}', json={'launch': 'RAMPA'}).status_code == 403
        assert sc.delete(f'/api/field/vehicles/{car}').status_code == 400   # görevde kullanılıyor
        ok(sc.put(f'/api/field/vehicles/{car}', json={'plate': '06 ABC 123', 'active': False}))
    with TestClient(app) as outsider:
        login(outsider, 'uretici', 'sifre-1234')
        assert outsider.get(f'/api/field/tasks/{tid}').status_code == 403

    # Araçlar → Uçuş Logu Analizi (göreve bağlı olmayan)
    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        pilot = ok(admin.post('/api/users', json={'username': 'pilot', 'full_name': 'Pilot', 'roles': ['Pilot'],
                                                  'password': 'sifre-1234'}))['id']
        assert pilot
    with TestClient(app) as pc:
        login(pc, 'pilot', 'sifre-1234')
        lid = ok(pc.post('/api/tools/flight-logs', files={'file': ('bagimsiz.BIN', SAMPLE_LOG)},
                         data={'aircraft': 'Deneme', 'location': 'Saha'}))['id']
        log = wait_log(pc, lid)
        assert log['status'] == 'TAMAM' and log['task'] is None and log['location'] == 'Saha'
        bad = ok(pc.post('/api/tools/flight-logs', files={'file': ('bozuk.bin', b'bu bir log degil' * 100)}))['id']
        assert wait_log(pc, bad)['status'] == 'HATA'
        listed = ok(pc.get('/api/tools/flight-logs'))
        assert {x['id'] for x in listed} >= {lid, bad}
        task_log = next(x for x in listed if x['task_code'] == 'GRV-0001')
        assert pc.delete(f'/api/tools/flight-logs/{task_log["id"]}').status_code == 400
        ok(pc.delete(f'/api/tools/flight-logs/{bad}'))

    with TestClient(app) as sofor_c:
        login(sofor_c, 'sofor', 'sifre-1234')
        assert len(ok(sofor_c.get('/api/field/tasks'))) == 1
        assert sofor_c.post('/api/field/tasks/1/start').status_code == 403
        assert sofor_c.get('/api/tools/flight-logs').status_code == 200             # Araçlar herkese açık (M9)
        assert sofor_c.get(f'/api/flight-logs/{task_log["id"]}').status_code == 200
        assert sofor_c.get(f'/api/flight-logs/{lid}').status_code == 200
        assert sofor_c.get('/api/stock').status_code == 403                         # Şoför stok göremez

    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        logs = ok(admin.get('/api/users/2/logins'))
        assert logs and logs[0]['success'] == 1
        assert any(l['action'] == 'Depo girişini onayladı' for l in ok(admin.get('/api/users/2/logs'))['rows'])
        # Sayfa hareketleri: normal istek ve sekme kapanırken gelen sendBeacon (text/plain) gövdesi
        ok(admin.post('/api/activity', json=[{'event': 'enter', 'path': '#/stock', 'title': 'Stok Yönetimi'}]))
        ok(admin.post('/api/activity', content='[{"event":"leave","path":"#/stock","title":"Stok Yönetimi","seconds":42}]',
                      headers={'Content-Type': 'text/plain'}))
        me_id = ok(admin.get('/api/auth/me'))['id']
        logs = ok(admin.get(f'/api/users/{me_id}/logs?kind=page'))
        assert [r['action'] for r in logs['rows'][:2]] == ['Sayfadan çıktı', 'Sayfaya girdi']
        assert '42 sn' in logs['rows'][0]['detail'] and logs['summary']['page_views'] >= 1
        assert all(r['entity'] != 'page' for r in ok(admin.get(f'/api/users/{me_id}/logs?kind=action'))['rows'])
        assert ok(admin.get(f'/api/users/{me_id}/logs?q=Stok'))['total'] == 2
        assert any(r['action'] == 'Sisteme giriş yaptı' for r in ok(admin.get(f'/api/users/{me_id}/logs'))['rows'])
        assert admin.post('/api/activity', content='bozuk', headers={'Content-Type': 'text/plain'}).status_code == 400
        assert admin.get('/api/stock').status_code == 200
    with TestClient(app) as depo2:
        login(depo2, 'depocu', 'sifre-1234')
        stock = ok(depo2.get('/api/stock'))
        assert stock['ready_aircraft'] == [] and stock['wip_aircraft'] == []

    with TestClient(app) as bf:   # kaba kuvvet: 5 hatalı denemeden sonra doğru şifre de 15 dk reddedilir
        for _ in range(5):
            assert bf.post('/api/auth/login', json={'username': 'depocu', 'password': 'yanlis'}).status_code == 401
        r = bf.post('/api/auth/login', json={'username': 'depocu', 'password': 'sifre-1234'})
        assert r.status_code == 429 and 'dakika' in r.json()['detail']
        login(bf, 'uretici', 'sifre-1234')   # başka kullanıcı etkilenmez

    # Gecikmiş sipariş (üretim yöneticisi) ve raporu eksik uçuş (görevli pilot)
    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        late = ok(admin.post('/api/orders', json={'start_date': '2026-01-01', 'end_date': '2026-01-31'}))[0]
        ok(admin.post('/api/users', json={'username': 'uyon', 'full_name': 'Üretim Yön', 'roles': ['Üretim Yöneticisi'],
                                          'password': 'sifre-1234'}))
        pid = ok(admin.get('/api/auth/me'))['id']
        admin_notes = notes(admin)
    assert admin_notes == {}   # rolü olmayan türleri yönetici de görmez
    pilot_id = next(u['id'] for u in ok_users() if u['username'] == 'pilot')
    with db.connect() as c:
        t3 = c.execute("INSERT INTO field_tasks (code, status, created_by, created_at) VALUES ('GRV-0099', 'BASARISIZ', ?, ?)",
                       (pid, db.now())).lastrowid
        c.execute('INSERT INTO field_task_staff (task_id, user_id) VALUES (?, ?)', (t3, pilot_id))
        c.execute('INSERT INTO field_flights (task_id, order_id) VALUES (?, ?)', (t3, oid2))
    with TestClient(app) as c:
        login(c, 'uyon', 'sifre-1234')
        assert notes(c)['orders-overdue']['names'] == [f'{late["code"]} (bitiş 2026-01-31)']
    with TestClient(app) as c:
        login(c, 'pilot', 'sifre-1234')
        n = notes(c)['field-report-pilot']
        assert n['names'] == ['GRV-0099 / CYZ-0002'] and n['href'] == f'#/field/task/{t3}'

    # Elektronik kat montajdaki uçakta da üretilebilir; kataloğa eklenen parça mevcut siparişlere eklenir
    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        o4 = ok(admin.post('/api/orders', json={}))[0]['id']
        with db.connect() as c:
            c.execute("UPDATE order_parts SET state = 'MONTAJ', approved_at = ? WHERE order_id = ? AND part_id != 'EK'", (db.now(), o4))
            c.execute("UPDATE orders SET status = 'MONTAJ' WHERE id = ?", (o4,))
            c.execute("DELETE FROM order_parts WHERE order_id = ? AND part_id = 'EK'", (o4,))
            from app.production import sync_catalog_parts
            assert sync_catalog_parts(c) == 1
        assert admin.post(f'/api/orders/{o4}/parts/L18/start', json={'printer_id': p1}).status_code == 400
        # Elektronik kat basılmadan sipariş Depo'ya geçmez
        o5 = ok(admin.post('/api/orders', json={}))[0]['id']
        with db.connect() as c:
            c.execute("UPDATE order_parts SET state = 'DEPO', approved_at = ? WHERE order_id = ? AND part_id != 'EK'", (db.now(), o5))
            c.execute("UPDATE order_parts SET approved_at = NULL WHERE order_id = ? AND part_id = 'EK'", (o5,))
            from app.production import recompute
            assert recompute(c, o5) == 'URETIM'
            c.execute("UPDATE order_parts SET state = 'DEPO' WHERE order_id = ? AND part_id = 'EK'", (o5,))
            assert recompute(c, o5) == 'DEPO'   # elektronik kat depo onayı bekliyor
            c.execute("UPDATE order_parts SET approved_at = ? WHERE order_id = ? AND part_id = 'EK'", (db.now(), o5))
            assert recompute(c, o5) == 'MONTAJ'
            assert c.execute("SELECT state FROM order_parts WHERE order_id = ? AND part_id = 'EK'", (o5,)).fetchone()[0] == 'DEPO'
        ok(admin.post(f'/api/orders/{o4}/parts/EK/start', json={'printer_id': p1}))
        assert ok(admin.get(f'/api/orders/{o4}'))['status'] == 'MONTAJ'

    # Montajdaki uçak da sahaya götürülebilir (montaj sahada yapılır)
    with TestClient(app) as saha:
        login(saha, 'sahasef', 'sifre-1234')
        av = {a['id']: a for a in ok(saha.get('/api/field/available-aircraft'))}
        assert av[o5]['status'] == 'MONTAJ' and av[o5]['queue_no'] is None
        me = ok(saha.get('/api/auth/me'))['id']
        t5 = ok(saha.post('/api/field/tasks', json={'order_ids': [o5], 'lead_id': me, 'pilot_id': pil, 'staff_ids': [saha2]}))
        assert ok(admin_get_order(o5))['status'] == 'SAHADA_MONTAJ'   # görev açılınca Sahada Montaj
        # İptal edilen görevdeki uçak fabrikadaki montaja döner
        t6 = ok(saha.post('/api/field/tasks', json={'order_ids': [o4], 'lead_id': me, 'pilot_id': pil, 'staff_ids': [saha2]}))
        assert ok(admin_get_order(o4))['status'] == 'SAHADA_MONTAJ'
        ok(saha.post(f'/api/field/tasks/{t6["id"]}/cancel'))
        assert ok(admin_get_order(o4))['status'] == 'MONTAJ'
        assert ok(saha.get(f'/api/field/tasks/{t5["id"]}'))['flights'][0]['order_code'] == ok(admin_get_order(o5))['code']
        assert o5 not in {a['id'] for a in ok(saha.get('/api/field/available-aircraft'))}
        # Montaj adımları sahada da yapılır; görev bitince montajı bitmemiş uçak fabrikadaki montaja döner
        ok(saha.post(f'/api/field/tasks/{t5["id"]}/start'))
        o = ok(admin_get_order(o5))
        assert o['status'] == 'SAHADA_MONTAJ' and o['field_task']['code'] == t5['code']
    with TestClient(app) as prod:
        login(prod, 'uretici', 'sifre-1234')
        assert ok(prod.post(f'/api/orders/{o5}/assembly/GOVDE', json={'staff_ids': [m1, m2]}))['status'] == 'SAHADA_MONTAJ'
        assert 'SP-' in notes(prod)['assembly-waiting']['names'][-1]
    with TestClient(app) as saha:
        login(saha, 'sahasef', 'sifre-1234')
        ok(saha.post(f'/api/field/tasks/{t5["id"]}/finish', json={'success': True}))
        o = ok(admin_get_order(o5))
        assert o['status'] == 'MONTAJ' and o['field_task'] is None and 'GOVDE' in o['assembly']['steps']

    # Büyük uçuş logu: parça parça yükleme (Cloudflare 100 MB tek istek sınırı)
    with TestClient(app) as c:
        login(c, 'admin@test', 'admin-sifre-1')
        assert c.post('/api/uploads', json={'kind': 'videos', 'file_name': 'a.mp4', 'size': 10}).status_code == 400
        assert c.post('/api/uploads', json={'kind': 'flightlogs', 'file_name': 'a.txt', 'size': 10}).status_code == 400
        assert c.post('/api/uploads', json={'kind': 'flightlogs', 'file_name': 'a.bin', 'size': 3 * 1024 ** 3}).status_code == 400
        up = ok(c.post('/api/uploads', json={'kind': 'flightlogs', 'file_name': 'buyuk.BIN', 'size': len(SAMPLE_LOG)}))['upload_id']
        half = len(SAMPLE_LOG) // 2
        ok(c.put(f'/api/uploads/{up}?offset=0', content=SAMPLE_LOG[:half]))
        assert c.post('/api/tools/flight-logs/chunked', json={'upload_id': up}).status_code == 400   # eksik
        assert c.put(f'/api/uploads/{up}?offset=0', content=SAMPLE_LOG[half:]).status_code == 409    # yanlış konum
        ok(c.put(f'/api/uploads/{up}?offset={half}', content=SAMPLE_LOG[half:]))
        lid = ok(c.post('/api/tools/flight-logs/chunked', json={'upload_id': up, 'aircraft': 'CYZ-T', 'note': ' '}))['id']
        log = wait_log(c, lid)
        assert log['status'] == 'TAMAM' and log['file_name'] == 'buyuk.BIN' and log['size'] == len(SAMPLE_LOG)
        assert log['aircraft'] == 'CYZ-T' and log['note'] is None
        # 3B oynatma verisi: .bin'den üretilir, saklanır; log silinince o da silinir
        rp = ok(c.get(f'/api/flight-logs/{lid}/replay'))
        assert rp['fields'][:4] == ['t', 'lat', 'lng', 'alt'] and len(rp['samples']) >= 2
        cache = config.UPLOAD_DIR / (log['file'] + '.replay.json')
        assert cache.exists() and ok(c.get(f'/api/flight-logs/{lid}/replay')) == rp
        ok(c.delete(f'/api/tools/flight-logs/{lid}'))
        assert not cache.exists()
        assert c.post('/api/tools/flight-logs/chunked', json={'upload_id': up}).status_code == 404   # jeton kullanıldı
    # Video ve log yalnızca yerel ağdan (Cloudflare tüneli üzerinden gelen istek reddedilir); iptal yarım dosyayı siler
    with TestClient(app) as c:
        login(c, 'admin@test', 'admin-sifre-1')
        cf = {'cf-ray': 'abc123-IST', 'cf-connecting-ip': '85.100.1.1'}
        r = c.post('/api/uploads', json={'kind': 'flightlogs', 'file_name': 'a.bin', 'size': 10}, headers=cf)
        assert r.status_code == 403 and 'yerel ağ' in r.json()['detail']
        assert c.post('/api/tools/flight-logs', files={'file': ('u.bin', SAMPLE_LOG)}, headers=cf).status_code == 403
        assert c.post(f'/api/field/flights/{f1["id"]}/videos', json={'file_name': 'v.mp4', 'size': 10}, headers=cf).status_code == 403
        m = ok(c.get('/api/meta', headers=cf))
        assert m['remote'] is True and m['local_url'].startswith('http://')
        assert ok(c.get('/api/meta'))['remote'] is False
        up = ok(c.post('/api/uploads', json={'kind': 'flightlogs', 'file_name': 'iptal.bin', 'size': 100}))['upload_id']
        ok(c.put(f'/api/uploads/{up}?offset=0', content=b'x' * 40))
        parts_before = list((config.UPLOAD_DIR / 'flightlogs').glob('*.part'))
        assert parts_before
        ok(c.delete(f'/api/uploads/{up}'))
        assert not list((config.UPLOAD_DIR / 'flightlogs').glob('*.part'))
        assert c.put(f'/api/uploads/{up}?offset=40', content=b'x').status_code == 404
    with TestClient(app) as c:   # başka kullanıcı başkasının yüklemesine parça ekleyemez
        login(c, 'admin@test', 'admin-sifre-1')
        up = ok(c.post('/api/uploads', json={'kind': 'flightlogs', 'file_name': 'x.bin', 'size': 5}))['upload_id']
    with TestClient(app) as c:
        login(c, 'uretici', 'sifre-1234')
        assert c.put(f'/api/uploads/{up}?offset=0', content=b'12345').status_code == 404

    # Kullanıcı silme: kaydı olmayan tamamen silinir; iş kayıtlarında adı geçen arşivlenir (geçmiş korunur)
    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        me = ok(admin.get('/api/auth/me'))['id']
        assert admin.delete(f'/api/users/{me}').status_code == 400
        tmp_id = ok(admin.post('/api/users', json={'username': 'gecici', 'full_name': 'Geçici', 'roles': ['Şoför'],
                                                   'password': 'sifre-1234'}))['id']
        assert ok(admin.delete(f'/api/users/{tmp_id}'))['mode'] == 'deleted'
        assert admin.get(f'/api/users/{tmp_id}').status_code == 404
        saha1_id = next(u['id'] for u in ok(admin.get('/api/users')) if u['username'] == 'saha1')
        assert ok(admin.delete(f'/api/users/{saha1_id}'))['mode'] == 'archived'
        assert 'saha1' not in [u['username'] for u in ok(admin.get('/api/users'))]
        assert admin.delete(f'/api/users/{saha1_id}').status_code == 404
        ok(admin.post('/api/users', json={'username': 'saha1', 'full_name': 'Yeni Saha', 'password': 'sifre-1234'}))
        task = ok(admin.get(f'/api/field/tasks/{tid}'))
        assert 'Saha1' in [s['full_name'] for s in task['staff']]   # geçmiş kayıtta adı duruyor
    with TestClient(app) as c:
        assert c.post('/api/auth/login', json={'username': 'saha1#silindi-%d' % saha1_id, 'password': 'sifre-1234'}).status_code == 401

    # Sürümlü arayüz dosyaları: index.html sürümlü adresleri kullanır; yanlış yol ve dizin dışı istek reddedilir
    with TestClient(app) as c:
        import re
        html = c.get('/app').text
        ver = re.search(r'/sv/([0-9a-f]+)/js/app.js', html).group(1)
        r = c.get(f'/sv/{ver}/js/app.js')
        assert r.status_code == 200 and 'immutable' in r.headers['cache-control']
        assert 'no-cache' in c.get('/sv/eski/js/app.js').headers['cache-control']
        assert c.get(f'/sv/{ver}/../app/config.py').status_code == 404
        assert c.get(f'/sv/{ver}/icons/icon-192.png').status_code == 404
        assert c.get('/static/js/app.js').headers['cache-control'] == 'no-cache'

    print('Tüm akış testleri geçti.')


if __name__ == '__main__':
    main()
