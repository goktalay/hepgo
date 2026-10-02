"""Kişisel → Toplantılar: davet, bildirim, notlu yanıt, hatırlatma zamanı, düzenleme (zaman değişince yanıt sıfırlanır),
iptal, yetki (davetli olmayan göremez / yalnızca düzenleyen değiştirir) ve kişisel takvimde görünme.

Çalıştırma: .venv/bin/python -m tests.test_meetings
"""
import os
import tempfile
from datetime import datetime, timedelta

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def iso(dt):
    return dt.replace(microsecond=0).isoformat()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ids = {u: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': ['Pilot'], 'password': 'sifre-1234'}))['id']
               for u in ('ali', 'ayse', 'veli', 'can')}
    login = lambda c, u: ok(c.post('/api/auth/login', json={'username': u, 'password': 'sifre-1234'}))
    with TestClient(app) as al, TestClient(app) as ay, TestClient(app) as ve, TestClient(app) as ca:
        for c, u in ((al, 'ali'), (ay, 'ayse'), (ve, 'veli'), (ca, 'can')):
            login(c, u)
        start = datetime.now() + timedelta(days=2)
        body = {'title': 'Üretim planlama', 'starts_at': iso(start), 'ends_at': iso(start + timedelta(hours=1)), 'location': 'Toplantı odası',
                'note': 'Haftalık üretim raporunu getirin', 'remind_min': 15, 'user_ids': [ids['ayse'], ids['veli'], ids['ali']]}
        assert al.post('/api/meetings', json={**body, 'user_ids': []}).status_code == 400
        assert al.post('/api/meetings', json={**body, 'starts_at': iso(datetime.now() - timedelta(hours=1))}).status_code == 400
        assert al.post('/api/meetings', json={**body, 'remind_min': 7}).status_code == 400
        m = ok(al.post('/api/meetings', json=body))
        assert m['my_status'] == 'DUZENLEYEN' and [i['full_name'] for i in m['invites']] == ['Ayse', 'Veli']   # düzenleyen davetli değil
        mid = m['id']
        # davet bildirimi
        n = {x['key']: x for x in ok(ay.get('/api/notifications'))['items']}
        assert n['meeting-invite']['count'] == 1 and n['meeting-invite']['href'] == f'#/meetings/{mid}'
        assert 'meeting-invite' not in {x['key'] for x in ok(al.get('/api/notifications'))['items']}
        # davetli olmayan göremez; yalnızca düzenleyen değiştirir
        assert ca.get(f'/api/meetings/{mid}').status_code == 404 and ok(ca.get('/api/meetings')) == []
        assert ay.put(f'/api/meetings/{mid}', json=body).status_code == 403
        assert ay.post(f'/api/meetings/{mid}/cancel').status_code == 403
        # yanıt (notlu)
        assert ay.post(f'/api/meetings/{mid}/respond', json={'status': 'EVET'}).status_code == 400
        r = ok(ay.post(f'/api/meetings/{mid}/respond', json={'status': 'KATILIYOR', 'response': 'Sunumu getireceğim'}))
        assert r['my_status'] == 'KATILIYOR' and r['my_response'] == 'Sunumu getireceğim'
        ok(ve.post(f'/api/meetings/{mid}/respond', json={'status': 'KATILMIYOR', 'response': 'İzindeyim'}))
        assert 'meeting-invite' not in {x['key'] for x in ok(ay.get('/api/notifications'))['items']}
        d = ok(al.get(f'/api/meetings/{mid}'))
        assert d['counts'] == {'BEKLIYOR': 0, 'KATILIYOR': 1, 'BELKI': 0, 'KATILMIYOR': 1}
        assert {i['full_name']: i['response'] for i in d['invites']} == {'Ayse': 'Sunumu getireceğim', 'Veli': 'İzindeyim'}
        # kişisel takvim: katılan görür, katılmayan görmez
        rng = f'start={start.date()}&end={(start + timedelta(days=1)).date()}'
        assert [e['link'] for e in ok(ay.get(f'/api/crm/my/events?{rng}')) if e.get('link')] == [f'#/meetings/{mid}']
        assert not [e for e in ok(ve.get(f'/api/crm/my/events?{rng}')) if e.get('link')]
        # düzenleme: zaman değişince yanıtlar sıfırlanır, yeni davetli eklenir
        soon_start = datetime.now() + timedelta(minutes=10)
        e = ok(al.put(f'/api/meetings/{mid}', json={**body, 'starts_at': iso(soon_start), 'ends_at': iso(soon_start + timedelta(hours=1)),
                                                    'user_ids': [ids['ayse'], ids['veli'], ids['can']]}))
        assert {i['full_name']: i['status'] for i in e['invites']} == {'Ayse': 'BEKLIYOR', 'Can': 'BEKLIYOR', 'Veli': 'BEKLIYOR'}
        # hatırlatma: 15 dk kala → düzenleyen ve katılmayacağını söylemeyenler
        ok(ve.post(f'/api/meetings/{mid}/respond', json={'status': 'KATILMIYOR'}))
        for c, expect in ((al, True), (ay, True), (ca, True), (ve, False)):
            keys = {x['key']: x for x in ok(c.get('/api/notifications'))['items']}
            assert ('meeting-soon' in keys) == expect, (c, keys.keys())
        soon_item = next(x for x in ok(ay.get('/api/notifications'))['items'] if x['key'] == 'meeting-soon')
        assert 'Üretim planlama' in soon_item['names'][0] and 'Toplantı odası' in soon_item['names'][0]
        # toplantı bittiyse hatırlatma kalkar
        from app import db as _db
        with _db.connect() as conn:
            conn.execute('UPDATE team_meetings SET started_at = ?, ended_at = ? WHERE id = ?', (_db.now(), _db.now(), mid))
            conn.commit()
        assert 'meeting-soon' not in {x['key'] for x in ok(ay.get('/api/notifications'))['items']}
        with _db.connect() as conn:
            conn.execute('UPDATE team_meetings SET started_at = NULL, ended_at = NULL WHERE id = ?', (mid,))
            conn.commit()
        # uzak toplantıda hatırlatma yok
        far = ok(al.post('/api/meetings', json={**body, 'user_ids': [ids['can']]}))
        assert all(x['key'] != 'meeting-soon' or len(x['names']) == 1 for x in ok(ca.get('/api/notifications'))['items'])
        # iptal: yanıt verilemez, bildirimler düşer
        ok(al.post(f'/api/meetings/{mid}/cancel'))
        assert ca.post(f'/api/meetings/{mid}/respond', json={'status': 'KATILIYOR'}).status_code == 400
        assert 'meeting-soon' not in {x['key'] for x in ok(ca.get('/api/notifications'))['items']}
        assert ok(ca.get(f'/api/meetings/{mid}'))['cancelled_at']
        assert [m['id'] for m in ok(ca.get('/api/meetings'))] == [mid, far['id']]
    print('Toplantı testleri geçti.')


if __name__ == '__main__':
    main()
