"""Kişi firmadan bağımsız; firma ataması e-posta adresi üzerinden; bir kişi birden çok firmada; firmasız kişi; birleştirme.
Örnek: Burak Türkoğlu — burak@asg-group.com → ASG Group, burak@gokkubbetech.com.tr → Gökkubbe: Rehber'de TEK kişi, iki adres
iki firma; iki firmanın kişi listesinde de görünür. Firma silinince kişi kalır. Birleştirme adresleri, firmaları, evrak / not
bağlarını ve kullanıcı bağını taşır. Çalıştırma: .venv/bin/python -m tests.test_people_model
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def members(c, cid):
    return sorted(p['full_name'] for p in ok(c.get(f'/api/companies/{cid}'))['people'])


def main():
    with TestClient(app) as c:
        ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        asg = ok(c.post('/api/companies', json={'name': 'ASG Group'}))['id']
        gok = ok(c.post('/api/companies', json={'name': 'Gökkubbe'}))['id']
        # Burak mailden ASG'ye atanır; sonra Gökkubbe adresi AYNI kişiye (person_id) Gökkubbe firmasıyla eklenir
        b = ok(c.post('/api/mail/people/assign', json={'email': 'burak@asg-group.com', 'full_name': 'Burak Türkoğlu', 'company_id': asg}))
        bid = b['person_id']
        found = ok(c.get('/api/mail/people/search?q=burak'))
        assert [p['id'] for p in found] == [bid]
        g = ok(c.post('/api/mail/people/assign', json={'email': 'burak@gokkubbetech.com.tr', 'company_id': gok, 'person_id': bid}))
        assert g['person_id'] == bid and g['company_name'] == 'Gökkubbe'
        assert members(c, asg) == ['Burak Türkoğlu'] and members(c, gok) == ['Burak Türkoğlu']
        rehber = [p for p in ok(c.get('/api/crm/contacts'))['people'] if p['full_name'] == 'Burak Türkoğlu']
        assert len(rehber) == 1 and sorted(x['name'] for x in rehber[0]['companies']) == ['ASG Group', 'Gökkubbe']
        d = ok(c.get(f'/api/crm/person/{bid}'))
        assert {(e['email'], e['company_name']) for e in d['email_list']} == {('burak@asg-group.com', 'ASG Group'), ('burak@gokkubbetech.com.tr', 'Gökkubbe')}
        cnt = {x['name']: x['people_count'] for x in ok(c.get('/api/companies'))}
        assert cnt['ASG Group'] == 1 and cnt['Gökkubbe'] == 1

        # Atama adres üzerinden: kayıtlı adres başka firmaya atanınca YENİ kişi açılmaz, adresin firması değişir
        yeni = ok(c.post('/api/companies', json={'name': 'Yeni Firma'}))['id']
        ok(c.post('/api/mail/people/assign', json={'email': 'burak@asg-group.com', 'company_id': yeni}))
        assert members(c, asg) == [] and members(c, yeni) == ['Burak Türkoğlu'] and members(c, gok) == ['Burak Türkoğlu']
        assert len([p for p in ok(c.get('/api/crm/contacts'))['people'] if p['full_name'] == 'Burak Türkoğlu']) == 1
        # Firma bağlantısını kaldır: adres kişide kalır, yalnız firmadan ayrılır
        ok(c.request('DELETE', f'/api/mail/people/assign?person_id={bid}&email=burak@asg-group.com'))
        d = ok(c.get(f'/api/crm/person/{bid}'))
        assert {e['email']: e['company_name'] for e in d['email_list']} == {'burak@asg-group.com': None, 'burak@gokkubbetech.com.tr': 'Gökkubbe'}
        assert members(c, yeni) == []

        # Firmasız kişi (Rehber / Google'dan) ve sonradan adresiyle firmaya bağlanması
        fid = ok(c.post('/api/companies/people', json={'full_name': 'Zeynep Ak', 'emails': ['zeynep@ak.com'], 'phone': '0555'}))['id']
        z = next(p for p in ok(c.get('/api/crm/contacts'))['people'] if p['id'] == fid)
        assert z['companies'] == [] and z['company_id'] is None
        assert ok(c.get(f'/api/crm/person/{fid}'))['companies'] == []
        ok(c.post('/api/mail/people/assign', json={'email': 'zeynep@ak.com', 'company_id': asg}))
        assert members(c, asg) == ['Zeynep Ak']

        # Firma silinince kişi kalır (firmasız olur)
        tmp = ok(c.post('/api/companies', json={'name': 'Silinecek'}))['id']
        kid = ok(c.post(f'/api/companies/{tmp}/people', json={'full_name': 'Kalıcı Kişi', 'emails': ['kalici@sil.com']}))['id']
        ok(c.delete(f'/api/companies/{tmp}'))
        k = ok(c.get(f'/api/crm/person/{kid}'))
        assert k['full_name'] == 'Kalıcı Kişi' and k['companies'] == [] and k['emails'] == ['kalici@sil.com']

        # Birleştirme: eski sistemde aynı kişi iki firmada iki kayıt — adres, firma, not, kullanıcı bağı tek kişide
        b2 = ok(c.post(f'/api/companies/{gok}/people', json={'full_name': 'Burak Türkoğlu', 'phone': '0532', 'emails': ['b.turkoglu@gmail.com'],
                                                         'note': 'Eski kayıt'}))['id']
        ok(c.post('/api/crm/notes', json={'subject': 'person', 'subject_id': b2, 'body': 'Telefonda görüşüldü'}))
        uid = ok(c.post('/api/users', json={'username': 'burak.t', 'full_name': 'Burak T', 'roles': ['Pilot'], 'password': 'Sifre-1234x'}))['id']
        with db.connect() as conn:
            conn.execute('UPDATE company_people SET user_id = ? WHERE id = ?', (uid, b2))
            conn.commit()
        dup = ok(c.get(f'/api/crm/person/{bid}'))['duplicates']
        assert [x['id'] for x in dup] == [b2], dup                                      # aynı ad → öneri
        assert c.post(f'/api/companies/people/{bid}/merge', json={'other_id': bid}).status_code == 400
        ok(c.post(f'/api/companies/people/{bid}/merge', json={'other_id': b2}))
        assert c.get(f'/api/crm/person/{b2}').status_code == 404
        m = ok(c.get(f'/api/crm/person/{bid}'))
        assert set(m['emails']) == {'burak@asg-group.com', 'burak@gokkubbetech.com.tr', 'b.turkoglu@gmail.com'} and m['phone'] == '0532'
        assert m['user_id'] == uid and 'Eski kayıt' in (m['note'] or '')
        notes = ok(c.get(f'/api/crm/notes?subject=person&subject_id={bid}'))
        assert any('Telefonda görüşüldü' in (n.get('body') or '') for n in (notes if isinstance(notes, list) else notes.get('notes', []))), notes
        assert members(c, gok) == ['Burak Türkoğlu']                                   # tek kişi kaldı
        # başka kişiye ait adres person_id ile çalınamaz
        r = c.post('/api/mail/people/assign', json={'email': 'zeynep@ak.com', 'company_id': gok, 'person_id': bid})
        assert r.status_code == 400 and 'birleştirin' in r.json()['detail']
        with db.connect() as conn:
            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    print('Kişi modeli testleri geçti.')


if __name__ == '__main__':
    main()
