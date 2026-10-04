"""Bir kişiye birden çok e-posta: firma kişisi ve İK personeli; ilki birincil; geçersiz adres reddedilir; mail firma eşleşmesi,
"mevcut kişiye ekle" ve bağlantı kaldırma ek adresleri tanır; birincil kaldırılınca ek adres birincil olur; kişi silinince
ek adresleri de silinir. Çalıştırma: .venv/bin/python -m tests.test_person_emails
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.mail import company_map  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as c:
        ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        cid = ok(c.post('/api/companies', json={'name': 'Acme'}))['id']
        pid = ok(c.post(f'/api/companies/{cid}/people', json={'full_name': 'Ayşe', 'emails': ['Ayse@Acme.com', 'ayse.k@gmail.com', 'ayse@acme.com']}))['id']
        p = ok(c.get(f'/api/companies/{cid}'))['people'][0]
        assert p['email'] == 'ayse@acme.com' and p['emails'] == ['ayse@acme.com', 'ayse.k@gmail.com'], p
        assert c.post(f'/api/companies/{cid}/people', json={'full_name': 'X', 'emails': ['gecersiz']}).status_code == 400
        # eski istemci (yalnız email) ek adreslere dokunmaz
        ok(c.put(f'/api/companies/people/{pid}', json={'full_name': 'Ayşe K.', 'email': 'ayse@acme.com'}))
        assert ok(c.get(f'/api/companies/{cid}'))['people'][0]['emails'] == ['ayse@acme.com', 'ayse.k@gmail.com']

        with db.connect() as conn:   # mail eşleşmesi ek adresi de tanır
            cm = company_map(conn, ['ayse.k@gmail.com', 'ayse@acme.com'])
        assert cm['ayse.k@gmail.com']['person_id'] == pid and cm['ayse@acme.com']['person_id'] == pid

        # Mail: "mevcut kişiye ekle" — yeni kişi açılmaz
        assert [x['id'] for x in ok(c.get(f'/api/mail/companies/{cid}/people'))] == [pid]
        r = ok(c.post('/api/mail/people/assign', json={'email': 'ayse@ev.net', 'company_id': cid, 'person_id': pid}))
        assert r['person_id'] == pid
        ppl = ok(c.get(f'/api/companies/{cid}'))['people']
        assert len(ppl) == 1 and ppl[0]['emails'] == ['ayse@acme.com', 'ayse.k@gmail.com', 'ayse@ev.net']
        # aynı firmada ek adresle eşleşen atama yeni kişi açmaz
        ok(c.post('/api/mail/people/assign', json={'email': 'ayse.k@gmail.com', 'full_name': 'Ayşe Kaya', 'company_id': cid}))
        assert len(ok(c.get(f'/api/companies/{cid}'))['people']) == 1

        # Bağlantı kaldırma: ek adres → yalnız o; birincil → ilk ek adres birincil olur
        ok(c.request('DELETE', f'/api/mail/people/assign?person_id={pid}&email=ayse@ev.net'))
        ok(c.request('DELETE', f'/api/mail/people/assign?person_id={pid}&email=ayse@acme.com'))
        p = ok(c.get(f'/api/companies/{cid}'))['people'][0]
        assert p['email'] == 'ayse.k@gmail.com' and p['emails'] == ['ayse.k@gmail.com'], p

        # İK personeli
        eid = ok(c.post('/api/hr/applications', json={'tc_no': '12345678950', 'first_name': 'Mehmet', 'last_name': 'Demir', 'source': ok(c.get('/api/hr/meta'))['sources'][0],
                                                      'emails': ['mehmet@firma.com', 'mehmet.d@gmail.com']}))['id']
        e = ok(c.get(f'/api/hr/employees/{eid}'))
        assert e['email'] == 'mehmet@firma.com' and e['emails'] == ['mehmet@firma.com', 'mehmet.d@gmail.com'], e['emails']
        assert c.post('/api/hr/applications', json={'tc_no': '23456789138', 'first_name': 'A', 'last_name': 'B', 'source': ok(c.get('/api/hr/meta'))['sources'][0], 'emails': ['a@b']}).status_code == 400

        # Kişi silinince ek adresleri de silinir
        ok(c.delete(f'/api/companies/people/{pid}'))
        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM person_emails WHERE kind = 'company' AND ref_id = ?", (pid,)).fetchone()[0] == 0
    print('Çoklu e-posta testleri geçti.')


if __name__ == '__main__':
    main()
