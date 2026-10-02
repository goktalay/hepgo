"""Saha görev raporu ve ekipman listesi testi: Modül Ayarları'ndaki standart ekipman listesi yeni göreve kopyalanır,
göreve özel çıkarma / ekleme / miktar değişikliği standart listeyi etkilemez; görev raporu adım adım akışı, görev
tanımlarını (kişi + rol), ekipmanı ve uçuşları döner. Ayarları yalnızca sistem yöneticisi değiştirir.

Çalıştırma: .venv/bin/python -m tests.test_field_report
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p='sifre-1234'):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def main():
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        mk = lambda u, roles: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,
                                                            'password': 'sifre-1234'}))['id']
        lead, pilot, staff = mk('lead', ['Saha Sorumlusu']), mk('pilot', ['Pilot']), mk('saha', ['Saha Personeli'])
        cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
        o1 = ok(a.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']
        with db.connect() as conn:
            conn.execute("UPDATE orders SET status = 'TAMAMLANDI', queue_no = 'CYZ-0001', completed_at = ? WHERE id = ?", (db.now(), o1))
        # Modül ayarları: standart ekipman + görev tanımı
        # Ekipman stoktaki ürünlerden seçilir: test için sarf ürünleri
        from app import spares
        with db.connect() as conn:
            prod = {}
            for i, (nm, un) in enumerate((('Yer istasyonu (laptop)', 'adet'), ('Batarya 6S', 'adet'), ('Fırlatma rampası', 'adet'), ('Jeneratör', 'adet'))):
                prod[nm] = conn.execute("INSERT INTO products (code, name, serial, schema, queue_prefix, created_at, type, unit, orderable) VALUES (?,?,?,?,?,?,'SARF',?,0)",
                                        (f'EQ{i}', nm, f'EQ{i}', spares.CUSTOM, f'EQ{i}', db.now(), un)).lastrowid
            conn.execute("INSERT INTO spare_moves (spare_id, qty, reason, created_at) VALUES (?, 3, 'test', ?)", (prod['Batarya 6S'], db.now()))
        found = ok(a.get('/api/field/equipment-search?q=bat'))
        assert found and found[0]['name'] == 'Batarya 6S' and found[0]['stock'] == 3 and found[0]['type'] == 'SARF'
        assert ok(a.get('/api/field/equipment-search?q=ba')) == []   # en az 3 karakter
        assert a.put('/api/field/settings', json={'equipment': [{'name': 'Serbest yazı', 'qty': 1}]}).status_code == 400   # stoktan seçilmeli
        st = ok(a.put('/api/field/settings', json={'equipment': [
            {'product_id': prod['Yer istasyonu (laptop)'], 'name': 'Yer istasyonu (laptop)', 'qty': 1, 'unit': 'adet'},
            {'product_id': prod['Batarya 6S'], 'name': 'x', 'qty': 4, 'unit': 'adet'},
            {'product_id': prod['Fırlatma rampası'], 'name': 'Fırlatma rampası', 'qty': 1},
        ], 'duties': {'pilot': 'Uçuşu yapar ve logu yükler.'}}))
        # İK görev tanımı (Saha Personeli için): Genel + Gizli madde; raporda yalnızca Genel / Kurum İçi görünür
        with db.connect() as conn:
            emp = conn.execute('SELECT id FROM employees WHERE user_id = ?', (staff,)).fetchone()
            if not emp:
                emp = (conn.execute("INSERT INTO employees (user_id, first_name, last_name, status, created_at) VALUES (?, 'Saha', 'Personel', 'AKTIF', ?)",
                                    (staff, db.now())).lastrowid,)
        eid = emp[0]
        ok(a.post(f'/api/hr/employees/{eid}/duties', json={'text': 'Rampayı kurar ve fırlatmaya hazırlar.', 'level': 'GENEL'}))
        ok(a.post(f'/api/hr/employees/{eid}/duties', json={'text': 'Kripto anahtarlarını taşır.', 'level': 'GIZLI'}))
        d = ok(a.post(f'/api/hr/employees/{eid}/duties', json={'text': 'Sahayı toplar.', 'level': 'KURUM_ICI'}))
        assert [x['level'] for x in d] == ['GENEL', 'GIZLI', 'KURUM_ICI']
        assert a.post(f'/api/hr/employees/{eid}/duties', json={'text': 'x', 'level': 'YOK'}).status_code == 400
        d = ok(a.put(f'/api/hr/employees/{eid}/duties-order', json={'ids': [d[2]['id'], d[0]['id'], d[1]['id']]}))
        assert [x['text'] for x in d][0] == 'Sahayı toplar.'
        ok(a.post(f'/api/hr/employees/{eid}/isg/ppe', json={'name': 'Baret / kask', 'usage': 'Saha boyunca'}))   # İSG: KKD
        ok(a.post(f'/api/hr/employees/{eid}/isg/ppe', json={'name': 'Reflektif yelek'}))
        assert [e['name'] for e in st['equipment']] == ['Yer istasyonu (laptop)', 'Batarya 6S', 'Fırlatma rampası']
        assert st['duties']['pilot'] == 'Uçuşu yapar ve logu yükler.' and st['duties']['lead']   # boş kalan varsayılana döner
    with TestClient(app) as s:
        login(s, 'lead')
        assert s.get('/api/field/settings').status_code == 403   # ayarlar yalnızca sistem yöneticisi
        tid = ok(s.post('/api/field/tasks', json={'order_ids': [o1], 'lead_id': lead, 'pilot_id': pilot, 'staff_ids': [staff]}))['id']
        t = ok(s.get(f'/api/field/tasks/{tid}'))
        assert [(e['name'], e['qty']) for e in t['equipment']] == [('Yer istasyonu (laptop)', 1), ('Batarya 6S', 4), ('Fırlatma rampası', 1)]
        bat = next(e for e in t['equipment'] if e['name'] == 'Batarya 6S')
        ramp = next(e for e in t['equipment'] if e['name'] == 'Fırlatma rampası')
        ok(s.put(f'/api/field/tasks/{tid}/equipment/{bat["id"]}', json={'qty': 6}))           # göreve özel miktar
        ok(s.delete(f'/api/field/tasks/{tid}/equipment/{ramp["id"]}'))                        # göreve özel çıkar
        assert s.post(f'/api/field/tasks/{tid}/equipment', json={'name': 'Jeneratör', 'qty': 1}).status_code == 400   # stoktan seçilmeli
        eq = ok(s.post(f'/api/field/tasks/{tid}/equipment', json={'product_id': prod['Jeneratör'], 'qty': 1}))  # göreve özel ekle
        assert eq[-1]['product_code'] == 'EQ3' and eq[-1]['unit'] == 'adet'
        assert [(e['name'], e['qty']) for e in eq] == [('Yer istasyonu (laptop)', 1), ('Batarya 6S', 6), ('Jeneratör', 1)]
        # İSG kontrolü: saha sorumlusu KKD için Yaptı / Yapmadı işaretler
        isg = ok(s.get(f'/api/field/tasks/{tid}/isg'))
        sp = next(p for p in isg if p['user_id'] == staff)
        assert [p['name'] for p in sp['ppe']] == ['Baret / kask', 'Reflektif yelek'] and sp['ppe'][0]['status'] is None
        ok(s.put(f'/api/field/tasks/{tid}/isg', json={'user_id': staff, 'item': 'Baret / kask', 'status': 'YAPTI'}))
        ok(s.put(f'/api/field/tasks/{tid}/isg', json={'user_id': staff, 'item': 'Reflektif yelek', 'status': 'YAPMADI', 'note': 'yelek unutuldu'}))
        assert s.put(f'/api/field/tasks/{tid}/isg', json={'user_id': staff, 'item': 'Baret / kask', 'status': 'BELKI'}).status_code in (400, 422)
        assert ok(s.get(f'/api/field/tasks/{tid}'))['can']['isg'] is True
        ok(s.post(f'/api/field/tasks/{tid}/start', json={}))
        ok(s.post(f'/api/field/tasks/{tid}/finish', json={'success': True}))
        r = ok(s.get(f'/api/field/tasks/{tid}/report'))
        texts = [x['text'] for x in r['steps']]
        assert texts[0] == 'Görev oluşturuldu' and 'Sahaya çıkış — görev başlatıldı' in texts and 'Görev tamamlandı' in texts
        assert {x['phase'] for x in r['steps']} >= {'Hazırlık', 'Saha'}
        roles = {p['full_name']: p['roles'] for p in r['people']}
        assert roles == {'Lead': ['Saha Sorumlusu'], 'Pilot': ['Pilot'], 'Saha': ['Saha Personeli']}
        assert next(p for p in r['people'] if p['full_name'] == 'Pilot')['duties'] == ['Uçuşu yapar ve logu yükler.']   # İK tanımı yok → rol
        sp = next(p for p in r['people'] if p['full_name'] == 'Saha')
        assert sp['duty_source'] == 'hr' and sp['duties'] == ['Sahayı toplar.', 'Rampayı kurar ve fırlatmaya hazırlar.']   # Gizli madde yok
        assert [e['name'] for e in r['equipment']] == ['Yer istasyonu (laptop)', 'Batarya 6S', 'Jeneratör']
        kkd = {p['name']: (p['status'], p['note']) for p in next(x for x in r['isg'] if x['user_id'] == staff)['ppe']}
        assert kkd == {'Baret / kask': ('YAPTI', None), 'Reflektif yelek': ('YAPMADI', 'yelek unutuldu')}
        assert len(r['reports']) == 1 and r['reports'][0]['flight']['queue_no'] == 'CYZ-0001' and r['reports'][0]['log'] is None
    with TestClient(app) as p:
        login(p, 'pilot')
        assert p.put(f'/api/field/tasks/{tid}/isg', json={'user_id': staff, 'item': 'Baret / kask', 'status': 'YAPMADI'}).status_code == 403   # yalnız saha sorumlusu / yönetici
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        assert len(ok(a.get('/api/field/settings'))['equipment']) == 3   # standart liste göreve özel değişikliklerden etkilenmez
    print('Saha görev raporu ve ekipman testleri geçti.')


if __name__ == '__main__':
    main()
