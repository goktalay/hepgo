"""Sekreterya → Aramalar ve Aramalarım; kişisel pano ve Yönetim → Sistem Durumu uçları.

Aramayı sekreterya kaydeder ve kullanıcıya bağlar; kullanıcı Aramalarım'da görür, not ekler, tamamlar. Bağlanan ve geri dönüş
istemeyen arama kendiliğinden tamamlanır. Başkasının araması görülemez.

Çalıştırma: .venv/bin/python -m tests.test_calls
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
        mk('sek', ['Sekreter'])
        ali = mk('ali', ['Üretim Yöneticisi'])
        mk('ayse', ['Depo Yöneticisi'])
        rok = ok(a.post('/api/companies', json={'name': 'Roketsan'}))['id']
        kisi = ok(a.post(f'/api/companies/{rok}/people', json={'full_name': 'Mehmet Yılmaz', 'phone': '0532 111 22 33'}))['id']
        # Yönetim → Sistem Durumu ve pano
        sysd = ok(a.get('/api/admin/system'))
        assert {'server', 'services', 'database', 'storage', 'backups', 'security', 'activity', 'growth', 'integrations'} <= set(sysd)
        assert sysd['security']['users_total'] == 4
        keys = {w['key'] for w in ok(a.get('/api/dashboard/widgets'))}
        assert {'clock', 'weather', 'announcements', 'my_calls', 'kpi_admin'} <= keys
        d = ok(a.get('/api/dashboard/data?keys=kpi_admin,my_calls,clock,yok'))
        assert 'kpis' in d['kpi_admin'] and d['my_calls']['items'] == [] and 'yok' not in d
        for w in ('users', 'disk', 'server'):
            ok(a.get(f'/api/system/details?what={w}'))
        assert 'uploads' in ok(a.get('/api/system/details?what=disk'))

    with TestClient(app) as s:
        login(s, 'sek')
        assert s.get('/api/admin/system').status_code == 403
        assert 'uploads' not in ok(s.get('/api/system/details?what=disk'))   # dosya dökümü yalnızca yöneticiye
        assert 'kpi_admin' not in {w['key'] for w in ok(s.get('/api/dashboard/widgets'))}
        assert s.post('/api/secretariat/calls', json={'caller_name': ' '}).status_code == 400
        assert s.post('/api/secretariat/calls', json={'caller_name': 'X', 'result': 'YOK'}).status_code == 400
        c1 = ok(s.post('/api/secretariat/calls', json={'caller_name': 'Mehmet Yılmaz', 'caller_phone': '0532 111 22 33', 'person_id': kisi,
                                                        'subject': 'Teklif', 'note': 'Fiyat listesini istedi', 'result': 'ULASILAMADI',
                                                        'callback': True, 'target_id': ali}))
        assert c1['company_name'] == 'Roketsan' and c1['done_at'] is None and c1['target_name'] == 'Ali'
        c2 = ok(s.post('/api/secretariat/calls', json={'caller_name': 'Veli', 'result': 'BAGLANDI', 'target_id': ali}))
        assert c2['done_at']                                  # bağlandı, geri dönüş istemiyor: tamamlandı
        c3 = ok(s.post('/api/secretariat/calls', json={'caller_name': 'Anket', 'note': 'Yalnızca not'}))
        assert c3['done_at'] and c3['target_id'] is None
        assert len(ok(s.get('/api/secretariat/calls'))) == 3
        assert ok(s.get('/api/secretariat/calls/callers'))[0]['caller_name']
        ok(s.post(f'/api/calls/{c1["id"]}/notes', json={'body': 'Ali Bey toplantıda'}))

    with TestClient(app) as u:
        login(u, 'ali')
        n = {x['key']: x for x in ok(u.get('/api/notifications'))['items']}
        assert n['call-waiting']['count'] == 1 and n['call-waiting']['href'] == '#/my-calls'
        mine = ok(u.get('/api/me/calls'))
        assert [k['caller_name'] for k in mine] == ['Mehmet Yılmaz', 'Veli']   # bekleyen önce
        assert ok(u.get('/api/dashboard/data?keys=my_calls'))['my_calls']['items'][0]['id'] == c1['id']
        d = ok(u.get(f'/api/calls/{c1["id"]}'))
        assert d['seen_at'] and not d['can_edit'] and len(d['notes']) == 1
        assert u.post('/api/secretariat/calls', json={'caller_name': 'X'}).status_code == 403
        d = ok(u.post(f'/api/calls/{c1["id"]}/notes', json={'body': 'Geri aradım, liste gönderildi'}))
        assert len(d['notes']) == 2
        assert u.post(f'/api/calls/{c1["id"]}/notes', json={'body': ' '}).status_code == 400
        d = ok(u.post(f'/api/calls/{c1["id"]}/done', json={'done': True}))
        assert d['done_at'] and d['done_by_name'] == 'Ali'
        assert 'call-waiting' not in {x['key'] for x in ok(u.get('/api/notifications'))['items']}
        ok(u.post(f'/api/calls/{c1["id"]}/done', json={'done': False}))
        assert u.get(f'/api/calls/{c3["id"]}').status_code == 404    # başkasının araması

    with TestClient(app) as y:
        login(y, 'ayse')
        assert ok(y.get('/api/me/calls')) == []
        assert y.get(f'/api/calls/{c1["id"]}').status_code == 404
        assert y.post(f'/api/calls/{c1["id"]}/notes', json={'body': 'x'}).status_code == 404

    with TestClient(app) as s:
        login(s, 'sek')
        e = ok(s.put(f'/api/secretariat/calls/{c2["id"]}', json={'caller_name': 'Veli', 'result': 'MESAJ', 'target_id': ali, 'callback': True}))
        assert e['done_at']                                   # aynı kişi: durum korunur
        ok(s.delete(f'/api/secretariat/calls/{c3["id"]}'))
        assert len(ok(s.get('/api/secretariat/calls'))) == 2
    print('Aramalar, pano ve sistem durumu testleri geçti.')


if __name__ == '__main__':
    main()
