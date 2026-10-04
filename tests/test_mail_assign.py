"""Mail › kişiyi firmaya atama: ad biliniyorsa (mail başlığı ya da rehber) ad da kaydedilir; aynı maildeki aynı alan adından
bilinmeyen kişiler sihirbazsız aynı firmaya eklenir (herkese açık servisler — gmail vb. — ve kendi alan adlarımız hariç,
başka firmada kayıtlı olana dokunulmaz); "geri al" otomatik eklenenleri siler.
Çalıştırma: .venv/bin/python -m tests.test_mail_assign
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@gokkubbetech.com',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def people(c, cid):
    return {p['email']: p['full_name'] for p in ok(c.get(f'/api/companies/{cid}'))['people'] if p.get('email')}


def main():
    with TestClient(app) as c:
        me = ok(c.post('/api/auth/login', json={'username': 'admin@gokkubbetech.com', 'password': 'admin-sifre-1'}))
        uid = ok(c.get('/api/auth/me'))['id']
        acme = ok(c.post('/api/companies', json={'name': 'Acme Makina'}))['id']
        diger = ok(c.post('/api/companies', json={'name': 'Diğer Firma'}))['id']
        # ayse@acme.com.tr başka firmada zaten kayıtlı
        ok(c.post('/api/mail/people/assign', json={'email': 'ayse@acme.com.tr', 'full_name': 'Ayşe Yıldız', 'company_id': diger}))
        with db.connect() as conn:   # rehberde adı bilinen ama mailde adı görünmeyen kişi
            conn.execute("INSERT INTO personal_contacts (user_id, source, ext_id, name, email, created_at) VALUES (?, 'google', 'x1', 'Cem Kaya', 'cem@acme.com.tr', ?)",
                         (uid, db.now()))
            conn.commit()
        others = [{'email': 'Mehmet@Acme.com.tr', 'name': 'Mehmet Demir'}, {'email': 'cem@acme.com.tr', 'name': None},
                  {'email': 'satis@acme.com.tr', 'name': 'satis@acme.com.tr'}, {'email': 'ayse@acme.com.tr', 'name': 'Ayşe'},
                  {'email': 'birisi@gmail.com', 'name': 'Birisi'}, {'email': 'ben@gokkubbetech.com', 'name': 'Ben'},
                  {'email': 'ali@acme.com.tr', 'name': 'Ali'}]
        r = ok(c.post('/api/mail/people/assign', json={'email': 'ali@acme.com.tr', 'full_name': 'Ali Can', 'company_id': acme, 'others': others}))
        assert r['company_id'] == acme and r['person_name'] == 'Ali Can'
        also = {x['email']: x['person_name'] for x in r['also']}
        assert also == {'mehmet@acme.com.tr': 'Mehmet Demir', 'cem@acme.com.tr': 'Cem Kaya', 'satis@acme.com.tr': 'satis@acme.com.tr'}, also
        assert people(c, acme) == {'ali@acme.com.tr': 'Ali Can', **also}
        assert people(c, diger) == {'ayse@acme.com.tr': 'Ayşe Yıldız'}              # başka firmadakine dokunulmadı

        # Ad verilmezse rehberden; rehberde de yoksa adres
        with db.connect() as conn:
            conn.execute("INSERT INTO personal_contacts (user_id, source, ext_id, name, email, created_at) VALUES (?, 'mail', 'x2', 'Zeynep Ak', 'zeynep@beta.com', ?)",
                         (uid, db.now()))
            conn.commit()
        beta = ok(c.post('/api/companies', json={'name': 'Beta'}))['id']
        assert ok(c.post('/api/mail/people/assign', json={'email': 'zeynep@beta.com', 'full_name': '', 'company_id': beta}))['person_name'] == 'Zeynep Ak'
        assert ok(c.post('/api/mail/people/assign', json={'email': 'x@beta.com', 'company_id': beta}))['person_name'] == 'x@beta.com'

        # Herkese açık servis: aynı alan adı aynı firma değildir
        g = ok(c.post('/api/mail/people/assign', json={'email': 'patron@gmail.com', 'full_name': 'Patron', 'company_id': beta,
                                                       'others': [{'email': 'baska@gmail.com', 'name': 'Başka'}]}))
        assert g['also'] == []

        # Geri al: otomatik eklenenler silinir; elle eklenen (ali) kalır
        for x in r['also']:
            u = ok(c.request('DELETE', f"/api/mail/people/assign?person_id={x['person_id']}&email={x['email']}&auto=1"))
            assert u['company'] is None
        assert people(c, acme) == {'ali@acme.com.tr': 'Ali Can'}
        names = [p['full_name'] for p in ok(c.get(f'/api/companies/{acme}'))['people']]
        assert names == ['Ali Can'], names                                           # kayıt tamamen silindi
        # auto=1 elle eklenen kişiyi silmez, yalnız bağlantıyı kaldırır
        ali = r['person_id']
        ok(c.request('DELETE', f'/api/mail/people/assign?person_id={ali}&email=ali@acme.com.tr&auto=1'))
        assert [p['full_name'] for p in ok(c.get(f'/api/companies/{acme}'))['people']] == ['Ali Can']
    print('Mail kişi atama testleri geçti.')


if __name__ == '__main__':
    main()
