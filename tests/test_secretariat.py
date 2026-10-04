"""Güvenlik (araç giriş / çıkış) ve Sekreterya (misafir kaydı, kargolar) testleri; bildirimler ve yetkiler.

Çalıştırma: .venv/bin/python -m tests.test_secretariat
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p='sifre-1234'):
    return ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def main():
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        mk = lambda u, roles: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles, 'password': 'sifre-1234'}))['id']
        mk('guv', ['Güvenlik'])
        mk('sek', ['Sekreter'])
        ali = mk('ali', ['Üretim Yöneticisi'])
        ayse = mk('ayse', ['Depo Yöneticisi'])
        rok = ok(a.post('/api/companies', json={'name': 'Roketsan Anonim Şirketi'}))['id']
        kisi = ok(a.post(f'/api/companies/{rok}/people', json={'full_name': 'Mehmet Yılmaz', 'title': 'Mühendis'}))['id']

    with TestClient(app) as g:   # Güvenlik: yalnızca güvenlik modülü; araç giriş / çıkış
        me = login(g, 'guv')
        assert ok(g.get('/api/auth/me'))['modules'] == ['security', 'announcements']
        assert ok(g.get('/api/alerts'))['total'] == 0          # üretim uyarıları gösterilmez
        assert g.get('/api/printers').status_code == 403 and g.get('/api/secretariat/visits').status_code == 403
        v1 = ok(g.post('/api/security/vehicles', json={'plate': '34abc123'}))
        assert v1['plate'] == '34 ABC 123'
        assert g.post('/api/security/vehicles', json={'plate': '34 ABC 123'}).status_code == 400   # zaten içeride
        assert g.post('/api/security/vehicles', json={'plate': ' '}).status_code == 400
        v2 = ok(g.post('/api/security/vehicles', json={'plate': '06 xy 4567', 'note': 'Kargo aracı'}))
        v3 = ok(g.post('/api/security/vehicles', json={'plate': '35 K 99'}))
        ok(g.post(f'/api/security/vehicles/{v3["id"]}/exit'))
        assert g.post(f'/api/security/vehicles/{v3["id"]}/exit').status_code == 400
        assert [v['plate'] for v in ok(g.get('/api/security/vehicles'))] == ['06 XY 4567', '34 ABC 123']
        log = ok(g.get('/api/security/log'))
        assert len(log) == 3 and next(x for x in log if x['plate'] == '35 K 99')['exited_by_name'] == 'Guv'
        assert [x['plate'] for x in ok(g.get('/api/security/log?q=06xy'))] == ['06 XY 4567']

    with TestClient(app) as s:   # Sekreterya: misafir kaydı ve kargo
        login(s, 'sek')
        assert set(ok(s.get('/api/auth/me'))['modules']) == {'secretariat', 'tools', 'reports', 'announcements', 'rehber'}
        assert s.get('/api/security/vehicles').status_code == 403
        visit = ok(s.post('/api/secretariat/visits', json={'purpose': 'Proje toplantısı'}))
        assert visit['code'] == 'MS-0001'
        vid = visit['id']
        d = ok(s.post(f'/api/secretariat/visits/{vid}/people', json={'person_id': kisi}))                 # kayıtlı kişi
        assert s.post(f'/api/secretariat/visits/{vid}/people', json={'person_id': kisi}).status_code == 400
        d = ok(s.post(f'/api/secretariat/visits/{vid}/people', json={'full_name': 'Zeynep Kaya', 'company_id': rok}))   # firmaya yeni
        d = ok(s.post(f'/api/secretariat/visits/{vid}/people', json={'full_name': 'Can Demir', 'company_text': 'Serbest Ltd.'}))
        assert [(p['full_name'], p['company_name'] or p['company_text']) for p in d['people']] == [
            ('Mehmet Yılmaz', 'Roketsan Anonim Şirketi'), ('Zeynep Kaya', 'Roketsan Anonim Şirketi'), ('Can Demir', 'Serbest Ltd.')]
        assert any(p['full_name'] == 'Zeynep Kaya' for p in ok(s.get('/api/secretariat/people')))   # Rehber'e eklendi
        assert s.post(f'/api/secretariat/visits/{vid}/people', json={'full_name': ' '}).status_code == 400
        parked = ok(s.get('/api/secretariat/parked'))
        assert len(parked) == 2
        assert s.post(f'/api/secretariat/visits/{vid}/vehicles', json={'ids': [v3['id']]}).status_code == 400   # çıkmış araç
        d = ok(s.post(f'/api/secretariat/visits/{vid}/vehicles', json={'ids': [v1['id'], v2['id']]}))
        assert sorted(v['plate'] for v in d['vehicles']) == ['06 XY 4567', '34 ABC 123']
        d = ok(s.post(f'/api/secretariat/visits/{vid}/hosts', json={'ids': [ali]}))
        assert [h['full_name'] for h in d['hosts']] == ['Ali']
        summ = ok(s.get('/api/secretariat/visits'))[0]
        assert summ['people_count'] == 3 and summ['host_names'] == 'Ali' and '34 ABC 123' in summ['plates']
        # Kargo: resimli; ilgili kişiye bildirim
        c1 = ok(s.post('/api/secretariat/cargo', data={'recipient_id': str(ayse), 'carrier': 'Aras', 'description': 'Numune'},
                       files={'photo': ('k.jpg', b'\xff\xd8\xff fake', 'image/jpeg')}))['id']
        ok(s.post('/api/secretariat/cargo', data={'recipient_id': str(ayse), 'carrier': 'Yurtiçi'}))
        assert s.post('/api/secretariat/cargo', data={'recipient_id': '9999'}).status_code == 400
        cargo = ok(s.get('/api/secretariat/cargo'))
        photo = next(k for k in cargo if k['id'] == c1)['photo']
        assert photo and s.get(f'/api/files/{photo}').status_code == 200
    with TestClient(app) as u:   # görüşülecek kişi: bildirim + Misafirlerim
        login(u, 'ali')
        n = {x['key']: x for x in ok(u.get('/api/notifications'))['items']}
        assert n['guest-visit']['count'] == 1 and 'Mehmet Yılmaz' in n['guest-visit']['names'][0]
        g = ok(u.get('/api/me/guests'))
        assert g[0]['code'] == 'MS-0001' and len(g[0]['people']) == 3
        # Misafirlerim açıldı: bildirim görüldü sayılır ve kalkar
        assert 'guest-visit' not in {x['key'] for x in ok(u.get('/api/notifications'))['items']}
        assert u.get(f'/api/files/{photo}').status_code == 404   # başkasının kargo resmi
    with TestClient(app) as u:   # kargo sahibi: bildirim, Kargolarım, teslim aldım
        login(u, 'ayse')
        n = {x['key']: x for x in ok(u.get('/api/notifications'))['items']}
        assert n['cargo-waiting']['count'] == 2 and n['cargo-waiting']['href'] == '#/my-cargo'
        mine = ok(u.get('/api/me/cargo'))
        assert len(mine) == 2 and u.get(f'/api/files/{photo}').status_code == 200
        ok(u.post(f'/api/me/cargo/{c1}/receive'))
        assert u.post(f'/api/me/cargo/{c1}/receive').status_code == 400
        assert {x['key']: x for x in ok(u.get('/api/notifications'))['items']}['cargo-waiting']['count'] == 1
    with TestClient(app) as u:   # başkasının kargosunu teslim alamaz
        login(u, 'ali')
        other = next(k for k in mine if k['id'] != c1)['id']
        assert u.post(f'/api/me/cargo/{other}/receive').status_code == 404
    with TestClient(app) as s:
        login(s, 'sek')
        ok(s.post(f'/api/secretariat/cargo/{other}/deliver'))   # sekreterya elden teslim etti
        d = ok(s.post(f'/api/secretariat/visits/{vid}/leave'))
        assert d['left_at']
        assert s.post(f'/api/secretariat/visits/{vid}/leave').status_code == 400
    with TestClient(app) as u:   # misafir çıktı: bildirim kalkar
        login(u, 'ali')
        assert 'guest-visit' not in {x['key'] for x in ok(u.get('/api/notifications'))['items']}
    print('Güvenlik ve Sekreterya testleri geçti.')


if __name__ == '__main__':
    main()
