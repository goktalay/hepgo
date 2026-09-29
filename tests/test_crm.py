"""Rehber, notlar ve takvim testi: firma kişileri + kullanıcılar, kişi / kullanıcı / firma detayı, çoklu not,
randevu ve hatırlatma (bildirim, tamamlandı), toplantıların takvimde görünmesi, yetkiler ve silme.

Çalıştırma: .venv/bin/python -m tests.test_crm
"""
import os
import tempfile
from datetime import datetime, timedelta

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
    now = datetime.now().replace(second=0, microsecond=0)
    iso = lambda d: d.isoformat(timespec='seconds')
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        idari = ok(a.post('/api/users', json={'username': 'idari@test', 'full_name': 'İdari Kişi', 'roles': ['İdari Personel'],
                                              'password': 'sifre-1234', 'phone': '0555 111 22 33'}))['id']
        uretim = ok(a.post('/api/users', json={'username': 'uretim@test', 'full_name': 'Üretim Kişi', 'roles': ['Üretim Yöneticisi'],
                                               'password': 'sifre-1234'}))['id']
        cid = ok(a.post('/api/companies', json={'name': 'MKE A.Ş.'}))['id']
        pid = ok(a.post(f'/api/companies/{cid}/people', json={'full_name': 'Ahmet Yılmaz', 'title': 'Müdür', 'phone': '0532'}))['id']
        mid = ok(a.post(f'/api/companies/{cid}/meetings', json={'subject': 'Tedarik', 'meeting_at': iso(now + timedelta(days=2)),
                                                                 'person_ids': [pid], 'user_ids': [idari], 'notes': 'Fiyat ve teslim konuşuldu',
                                                                 'other_attendees': 'Danışman'}))['id']
        admin_id = ok(a.get('/api/auth/me'))['id']

    with TestClient(app) as c:
        login(c, 'idari@test')
        # Rehber: firma kişileri ve kullanıcılar
        contacts = ok(c.get('/api/crm/contacts'))
        assert [p['full_name'] for p in contacts['people']] == ['Ahmet Yılmaz']
        users = {u['full_name']: u for u in contacts['users']}
        assert 'İdari Kişi' in users and users['İdari Kişi']['roles'] == ['İdari Personel'] and users['İdari Kişi']['email'] == 'idari@test'
        # Kişi detayı: toplantı, evrak; kullanıcı detayı: katıldığı toplantı
        p = ok(c.get(f'/api/crm/person/{pid}'))
        assert p['company_name'] == 'MKE A.Ş.' and [m['subject'] for m in p['meetings']] == ['Tedarik'] and p['documents'] == []
        u = ok(c.get(f'/api/crm/user/{idari}'))
        assert [m['company_name'] for m in u['meetings']] == ['MKE A.Ş.']
        assert c.get('/api/crm/user/9999').status_code == 404

        # Notlar: birden çok; en yeni üstte
        n1 = ok(c.post('/api/crm/notes', json={'subject': 'person', 'subject_id': pid, 'body': 'İlk görüşme olumlu'}))['id']
        ok(c.post('/api/crm/notes', json={'subject': 'person', 'subject_id': pid, 'body': 'Fiyat teklifi bekleniyor'}))
        ok(c.post('/api/crm/notes', json={'subject': 'company', 'subject_id': cid, 'body': 'Firma notu (kişiden bağımsız)'}))
        assert c.post('/api/crm/notes', json={'subject': 'person', 'subject_id': pid, 'body': '  '}).status_code == 400
        assert c.post('/api/crm/notes', json={'subject': 'xyz', 'subject_id': 1, 'body': 'x'}).status_code == 400
        notes = ok(c.get(f'/api/crm/notes?subject=person&subject_id={pid}'))
        assert [n['body'] for n in notes] == ['Fiyat teklifi bekleniyor', 'İlk görüşme olumlu'] and notes[0]['created_by_name'] == 'İdari Kişi'
        assert len(ok(c.get(f'/api/crm/notes?subject=company&subject_id={cid}'))) == 1
        ok(c.put(f'/api/crm/notes/{n1}', json={'body': 'İlk görüşme çok olumlu'}))

        # Takvim: randevu (bugün, 1 saat sonra) ve zamanı geçmiş hatırlatma; üretim kişisi hatırlatılacak
        start = now + timedelta(minutes=5) if (now + timedelta(minutes=5)).date() == now.date() else now
        r1 = ok(c.post('/api/crm/events', json={'subject': 'person', 'subject_id': pid, 'kind': 'RANDEVU', 'title': 'Numune teslimi',
                                                  'starts_at': iso(start), 'ends_at': iso(start + timedelta(hours=1)), 'location': 'Ofis'}))['id']
        r2 = ok(c.post('/api/crm/events', json={'subject': 'company', 'subject_id': cid, 'kind': 'HATIRLATMA', 'title': 'Teklifi ara',
                                                  'starts_at': iso(now - timedelta(hours=1)), 'user_ids': [uretim]}))['id']
        assert c.post('/api/crm/events', json={'subject': 'person', 'subject_id': pid, 'kind': 'RANDEVU', 'title': 'x',
                                                'starts_at': iso(now), 'ends_at': iso(now - timedelta(hours=1))}).status_code == 400
        assert c.post('/api/crm/events', json={'subject': 'person', 'subject_id': pid, 'kind': 'X', 'title': 'x',
                                                'starts_at': iso(now)}).status_code == 400
        month = lambda s, i: ok(c.get(f'/api/crm/events?subject={s}&subject_id={i}&start={(now - timedelta(days=40)).date()}'
                                      f'&end={(now + timedelta(days=40)).date()}'))
        ev = month('person', pid)
        assert {e['kind'] for e in ev} == {'RANDEVU', 'TOPLANTI'}   # kişinin katıldığı toplantı da takvimde
        mt = next(e for e in ev if e['kind'] == 'TOPLANTI')
        assert mt['id'] == f'm{mid}' and mt['note'] == 'Fiyat ve teslim konuşuldu' and mt['other_attendees'] == 'Danışman'
        assert [p['full_name'] for p in mt['people']] == ['Ahmet Yılmaz'] and [u['full_name'] for u in mt['users']] == ['İdari Kişi']
        ev_c = month('company', cid)
        assert {e['title'] for e in ev_c} == {'Teklifi ara', 'Tedarik'}
        assert [e['title'] for e in ok(c.get(f'/api/crm/events/upcoming?subject=company&subject_id={cid}'))] == ['Teklifi ara']
        # Bildirim: oluşturana (idari) ikisi de; hatırlatılacak üretim kişisine yalnızca hatırlatma
        notes_of = lambda cl: {n['key']: n for n in ok(cl.get('/api/notifications'))['items']}
        mine_i = {e['title']: e for e in ok(c.get(f'/api/crm/my/events?start={(now - timedelta(days=40)).date()}'
                                                 f'&end={(now + timedelta(days=40)).date()}'))}
        assert {'Numune teslimi', 'Teklifi ara', 'Tedarik'} <= set(mine_i)   # oluşturduğu kayıtlar + katıldığı toplantı
        assert mine_i['Numune teslimi']['subject_href'] == f'#/companies/rehber/person/{pid}/calendar'
        n = notes_of(c)['calendar-due']
        assert sorted(x.split(' ', 1)[1] for x in n['names']) == ['Numune teslimi (Ahmet Yılmaz)', 'Teklifi ara (MKE A.Ş.)']

    with TestClient(app) as u:
        login(u, 'uretim@test')
        assert notes_of(u)['calendar-due']['names'][0].endswith('Teklifi ara (MKE A.Ş.)')
        assert notes_of(u)['calendar-due']['href'] == '#/calendar'   # kişisel takvim
        # Firma Yönetimi modülü olmayan kullanıcı rehbere / notlara giremez
        assert u.get('/api/crm/contacts').status_code == 403
        assert u.get(f'/api/crm/notes?subject=company&subject_id={cid}').status_code == 403
        # Kişisel takvim: herkes kendi takvimine kayıt ekler; başkasının / firmanın takvimine ekleyemez
        mine = ok(u.post('/api/crm/events', json={'subject': 'user', 'subject_id': uretim, 'kind': 'HATIRLATMA',
                                                   'title': 'Kalibrasyon kontrolü', 'starts_at': iso(now + timedelta(days=1))}))['id']
        assert u.post('/api/crm/events', json={'subject': 'company', 'subject_id': cid, 'kind': 'RANDEVU', 'title': 'x',
                                                'starts_at': iso(now)}).status_code == 403
        assert u.post('/api/crm/events', json={'subject': 'user', 'subject_id': idari, 'kind': 'RANDEVU', 'title': 'x',
                                                'starts_at': iso(now)}).status_code == 403
        rng = f'start={(now - timedelta(days=40)).date()}&end={(now + timedelta(days=40)).date()}'
        my = {e['title']: e for e in ok(u.get(f'/api/crm/my/events?{rng}'))}
        # kendi kaydı + katılımcı olduğu firma hatırlatması (konu adıyla; firma modülü yok → bağlantı yok)
        assert set(my) == {'Kalibrasyon kontrolü', 'Teklifi ara'}
        assert my['Teklifi ara']['subject_name'] == 'MKE A.Ş.' and my['Teklifi ara']['subject_href'] is None
        assert 'subject_name' not in my['Kalibrasyon kontrolü']
        assert [e['title'] for e in ok(u.get('/api/crm/my/upcoming'))][-1] == 'Kalibrasyon kontrolü'
        ok(u.post(f'/api/crm/events/{mine}/done'))
        assert ok(u.delete(f'/api/crm/events/{mine}'))

    with TestClient(app) as c:
        login(c, 'idari@test')
        ok(c.post(f'/api/crm/events/{r2}/done'))
        assert 'calendar-due' not in {k for k in notes_of(c)} or all('Teklifi ara' not in x for x in notes_of(c)['calendar-due']['names'])
        # düzenleme: konu değişmez, katılımcı güncellenir
        ok(c.put(f'/api/crm/events/{r1}', json={'subject': 'company', 'subject_id': cid, 'kind': 'RANDEVU', 'title': 'Numune teslimi 2',
                                                 'starts_at': iso(start), 'user_ids': [uretim]}))
        e = next(x for x in month('person', pid) if x['id'] == r1)
        assert e['title'] == 'Numune teslimi 2' and [x['full_name'] for x in e['users']] == ['Üretim Kişi']

    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        other = ok(a.post('/api/users', json={'username': 'idari2@test', 'full_name': 'İdari İki', 'roles': ['İdari Personel'],
                                              'password': 'sifre-1234'}))['id']
        assert other and admin_id
    with TestClient(app) as o:
        login(o, 'idari2@test')
        assert o.put(f'/api/crm/notes/{n1}', json={'body': 'x'}).status_code == 403   # başkasının notu
        assert o.delete(f'/api/crm/events/{r1}').status_code == 403
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        ok(a.delete(f'/api/crm/notes/{n1}'))   # yönetici silebilir
        # kişi / firma silinince notları ve takvim kayıtları da silinir
        ok(a.delete(f'/api/companies/meetings/{mid}'))
        ok(a.delete(f'/api/companies/people/{pid}'))
        ok(a.delete(f'/api/companies/{cid}'))
        with db.connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM crm_notes').fetchone()[0] == 0
            assert conn.execute('SELECT COUNT(*) FROM crm_events').fetchone()[0] == 0
        # not yazmış kullanıcı silinince arşivlenir (geçmiş korunur); kullanıcı hakkındaki notlar da kalır
        with db.connect() as conn:
            conn.execute("INSERT INTO crm_notes (subject_type, subject_id, body, created_by, created_at) VALUES ('user', ?, 'x', ?, ?)",
                         (uretim, idari, db.now()))
        assert ok(a.delete(f'/api/users/{idari}'))['mode'] == 'archived'
        # hiç kaydı olmayan kullanıcı tamamen silinir; hakkındaki notlar da silinir
        with db.connect() as conn:
            conn.execute("INSERT INTO crm_notes (subject_type, subject_id, body, created_by, created_at) VALUES ('user', ?, 'y', ?, ?)",
                         (other, admin_id, db.now()))
        assert ok(a.delete(f'/api/users/{other}'))['mode'] == 'deleted'
        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM crm_notes WHERE subject_type = 'user' AND subject_id = ?", (other,)).fetchone()[0] == 0
    print('Rehber, notlar ve takvim testleri geçti.')


if __name__ == '__main__':
    main()
