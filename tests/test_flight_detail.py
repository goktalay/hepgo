"""Uçuş detayı testi: görevdeki uçağın detayı (uçak + görev bilgisi), sahada montajdaki uçağın sipariş durumu,
uçuş notları (türlü, birden çok; yetki), uçuş video ve resimleri (resim her yerden, video yalnızca yerel ağdan).

Çalıştırma: .venv/bin/python -m tests.test_flight_detail
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


def upload(c, fid, name, data, headers=None):
    init = c.post(f'/api/field/flights/{fid}/videos', json={'file_name': name, 'size': len(data)}, headers=headers or {})
    if init.status_code != 200:
        return init
    up = init.json()['upload_id']
    ok(c.put(f'/api/field/uploads/{up}?offset=0', content=data))
    return c.post(f'/api/field/uploads/{up}/complete')


def main():
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        mk = lambda u, roles: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,
                                                            'password': 'sifre-1234'}))['id']
        lead, pilot, staff = mk('lead', ['Saha Sorumlusu']), mk('pilot', ['Pilot']), mk('saha', ['Saha Personeli'])
        cyz = next(p for p in ok(a.get('/api/products')) if p['code'] == 'CYZ')
        o1 = ok(a.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']
        o2 = ok(a.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']
        with db.connect() as conn:   # biri saha deposunda (montajı bitmiş), diğeri montajda
            conn.execute("UPDATE orders SET status = 'TAMAMLANDI', queue_no = 'CYZ-0001', completed_at = ? WHERE id = ?", (db.now(), o1))
            conn.execute("UPDATE orders SET status = 'MONTAJ' WHERE id = ?", (o2,))
    with TestClient(app) as s:
        login(s, 'lead')
        tid = ok(s.post('/api/field/tasks', json={'order_ids': [o1, o2], 'lead_id': lead, 'pilot_id': pilot,
                                                   'staff_ids': [staff]}))['id']
        t = ok(s.get(f'/api/field/tasks/{tid}'))
        fl = {f['order_id']: f for f in t['flights']}
        assert fl[o1]['order_status'] == 'TAMAMLANDI' and fl[o2]['order_status'] == 'SAHADA_MONTAJ'   # sahaya giden montaj uçağı
        fid = fl[o1]['id']
        d = ok(s.get(f'/api/field/flights/{fid}'))
        assert d['order']['queue_no'] == 'CYZ-0001' and d['order']['product_name'] == 'CAYMAZ'
        assert d['task']['code'] == t['code'] and d['task']['pilot_name'] == 'Pilot' and d['task']['staff'] == ['Saha']
        assert d['log'] is None and d['notes'] == [] and d['media'] == []
        assert d['can']['edit'] and not d['can']['upload']   # görev başlamadan yükleme yok
        assert set(d['note_kinds']) == {'GORUS', 'IYILESTIRME', 'ARIZA', 'GOZLEM', 'DIGER'}
        assert s.get('/api/field/flights/9999').status_code == 404

        # Uçuş notları: türlü, birden çok; en yeni üstte
        ok(s.post(f'/api/field/flights/{fid}/notes', json={'kind': 'GORUS', 'body': 'Kalkış sorunsuz'}))
        r = ok(s.post(f'/api/field/flights/{fid}/notes', json={'kind': 'IYILESTIRME', 'body': 'Rampa açısı artırılmalı'}))
        assert [(n['kind'], n['body']) for n in r['notes']] == [('IYILESTIRME', 'Rampa açısı artırılmalı'), ('GORUS', 'Kalkış sorunsuz')]
        assert s.post(f'/api/field/flights/{fid}/notes', json={'kind': 'XX', 'body': 'x'}).status_code == 400
        assert s.post(f'/api/field/flights/{fid}/notes', json={'kind': 'GORUS', 'body': ' '}).status_code == 400
        nid = r['notes'][0]['id']

        # Video / resim: görev başlamadan yüklenemez
        assert upload(s, fid, 'kalkis.jpg', b'\xff\xd8x' * 10).status_code == 400
        ok(s.post(f'/api/field/tasks/{tid}/start', json={}))
        assert ok(s.get(f'/api/field/flights/{fid}'))['can']['upload']
        ok(upload(s, fid, 'kalkis.jpg', b'\xff\xd8x' * 10))
        ok(upload(s, fid, 'ucus.mp4', b'\0' * 100))                     # yerel ağdan video
        remote = {'cf-connecting-ip': '1.2.3.4'}
        assert upload(s, fid, 'uzak.mp4', b'\0' * 100, remote).status_code == 403   # internetten video yok
        ok(upload(s, fid, 'uzak.png', b'\x89PNG' * 10, remote))           # internetten resim olur
        assert upload(s, fid, 'x.exe', b'abc').status_code == 400
        media = ok(s.get(f'/api/field/flights/{fid}'))['media']
        assert [(m['file_name'], m['kind']) for m in media] == [('kalkis.jpg', 'RESIM'), ('ucus.mp4', 'VIDEO'), ('uzak.png', 'RESIM')]
        assert s.get(f'/api/files/{media[0]["file"]}').status_code == 200

    with TestClient(app) as p:
        login(p, 'saha')   # saha personeli not ekler; başkasının notunu değiştiremez; yükleme yapamaz
        ok(p.post(f'/api/field/flights/{fid}/notes', json={'kind': 'GOZLEM', 'body': 'Rüzgar arttı'}))
        assert p.put(f'/api/field/flight-notes/{nid}', json={'kind': 'GORUS', 'body': 'x'}).status_code == 403
        assert p.delete(f'/api/field/flight-notes/{nid}').status_code == 403
        assert upload(p, fid, 'a.jpg', b'\xff\xd8x').status_code == 403
        assert not ok(p.get(f'/api/field/flights/{fid}'))['can']['edit']
    with TestClient(app) as s:
        login(s, 'lead')   # saha sorumlusu herkesin notunu düzenler / siler
        r = ok(s.put(f'/api/field/flight-notes/{nid}', json={'kind': 'ARIZA', 'body': 'Rampa açısı yetersiz'}))
        assert r['notes'][1]['kind'] == 'ARIZA' and r['notes'][1]['updated_at']
        r = ok(s.delete(f'/api/field/flight-notes/{nid}'))
        assert len(r['notes']) == 2
        # ---- Kullanım durumu ve HURDA
        assert ok(s.get(f'/api/field/flights/{fid}'))['order']['usage_type'] == 'TEK'
        ready = ok(s.get('/api/field/flights?view=ready'))
        assert [f['id'] for f in ready] == [fid]   # montajdaki uçak (o2) uçuşa hazır değil
        assert o1 not in {a['id'] for a in ok(s.get('/api/field/available-aircraft'))}   # açık görevde
        ok(s.post(f'/api/field/flights/{fid}/scrap'))                   # log yok: saha sorumlusu "uçtu" der
        d = ok(s.get(f'/api/field/flights/{fid}'))
        assert d['order']['status'] == 'HURDA' and d['order']['scrapped_at']
        assert s.post(f'/api/field/flights/{fid}/scrap').status_code == 400
        assert ok(s.get('/api/field/flights?view=ready')) == [] and [f['id'] for f in ok(s.get('/api/field/flights?view=flown'))] == [fid]
        ok(s.post(f'/api/field/flights/{fid}/unscrap'))
        assert ok(s.get(f'/api/field/flights/{fid}'))['order']['status'] == 'TAMAMLANDI'
        # log uçtuğunu gösterince otomatik hurda
        from app.production import scrap
        with db.connect() as conn:
            assert scrap(conn, o1, None, 'Uçtu (test)')
        # görev bitince: tek kullanımlık (uçtu → hurda) seçilemez; çoklu kullanım yeniden seçilebilir
        with db.connect() as conn:
            conn.execute("UPDATE orders SET status = 'TAMAMLANDI', scrapped_at = NULL WHERE id = ?", (o1,))
            conn.execute("UPDATE field_tasks SET status = 'GOREV_TAMAMLANDI' WHERE id = ?", (tid,))
        assert o1 not in {a['id'] for a in ok(s.get('/api/field/available-aircraft'))}   # tek kullanımlık: bir kez gitti
        with db.connect() as conn:
            conn.execute("UPDATE products SET usage_type = 'COKLU' WHERE code = 'CYZ'")
        av = {a['id']: a for a in ok(s.get('/api/field/available-aircraft'))}
        assert av[o1]['usage_type'] == 'COKLU' and av[o1]['past_tasks'] == 1
    # ---- Sahada montajı biten (kalibrasyona geçen) uçak: görev başlangıçtaysa göreve başlanmış sayılır
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        mk = lambda u, roles: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,
                                                            'password': 'sifre-1234'}))['id']
        m1, m2 = mk('m1', ['Montaj Personeli']), mk('m2', ['Montaj Personeli'])
        o3 = ok(a.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']
        with db.connect() as conn:
            conn.execute("UPDATE order_parts SET state = 'MONTAJ', approved_at = ? WHERE order_id = ?", (db.now(), o3))
            conn.execute("UPDATE orders SET status = 'MONTAJ' WHERE id = ?", (o3,))
            for step in ('SOL_KANAT', 'SAG_KANAT', 'GOVDE', 'ELEKTRONIK_EK', 'ELEKTRONIK_K04'):
                conn.execute('INSERT INTO assembly_steps (order_id, step, at, recorded_at) VALUES (?,?,?,?)',
                             (o3, step, db.now(), db.now()))
    with TestClient(app) as s:
        login(s, 'lead')
        t2 = ok(s.post('/api/field/tasks', json={'order_ids': [o3], 'lead_id': lead, 'pilot_id': pilot, 'staff_ids': [staff]}))['id']
        assert ok(s.get(f'/api/field/tasks/{t2}'))['status'] == 'BASLANGIC'
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        assert ok(a.get(f'/api/orders/{o3}'))['status'] == 'SAHADA_MONTAJ'
        r = ok(a.post(f'/api/orders/{o3}/final', json={'staff_ids': [m1, m2], 'checklist': {'wings': True, 'electronics': True},
                                                        'at': '2026-12-01T09:00:00'}))
        assert r['status'] == 'SAHADA_MONTAJ'   # kapaklar takılmadı
        r = ok(a.post(f'/api/orders/{o3}/covers', json={'staff_ids': [m1], 'at': '2026-12-01T10:00:00'}))
        assert r['status'] == 'KALIBRASYON'
        t = ok(a.get(f'/api/field/tasks/{t2}'))
        assert t['status'] == 'GOREVDE' and t['started_at'].startswith('2026-12-01T10:00'), (t['status'], t['started_at'])
    with TestClient(app) as p:
        login(p, 'saha')
        assert p.post(f'/api/field/flights/{fid}/scrap').status_code == 403   # yalnızca saha sorumlusu
    print('Uçuş detayı (notlar, video ve resimler) testleri geçti.')


if __name__ == '__main__':
    main()
