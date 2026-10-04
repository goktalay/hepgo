"""Mail › Kişiler ve Cariler görünümleri (kayıtlı mailler): Rehber'de bilinen kişiler (bütün adresleri tek satırda, firmasız
kişi ve sistem kullanıcısı dahil) üstte, bilinmeyen adresler altta; carinin çalışanlarının adresleriyle yazışmalar; her iletide
eşleşen adres; kendi adresimiz listede yok; aynı ileti iki klasörde olsa bile bir kez.
Çalıştırma: .venv/bin/python -m tests.test_mail_views
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@gokkubbetech.com',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, mail, mail_cache  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_mail import GOOD, FakeIMAP, FakeSMTP, make  # noqa: E402

mail.imaplib.IMAP4_SSL = FakeIMAP
mail.smtplib.SMTP_SSL = mail.smtplib.SMTP = FakeSMTP


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    inbox = {1: {'raw': make(1, 'Teklif', 'Burak T <burak@gokkubbe.com>'), 'flags': set()},
             2: {'raw': make(2, 'Fatura', 'Burak <burak@asg.com>'), 'flags': set()},
             3: {'raw': make(3, 'Selam', 'Yabancı Biri <yabanci@x.com>'), 'flags': set()},
             4: {'raw': make(4, 'Bilgi', 'Firmasız <serbest@y.com>'), 'flags': set()},
             5: {'raw': make(5, 'İç yazışma', 'Admin <admin@gokkubbetech.com>'), 'flags': set()}}
    FakeIMAP.servers['imap.gmail.com'] = {'INBOX': inbox, '[Gmail]/&AMcA9g-p': {9: dict(inbox[1])}}   # aynı ileti Çöp'te de
    with TestClient(app) as c:
        ok(c.post('/api/auth/login', json={'username': 'admin@gokkubbetech.com', 'password': 'admin-sifre-1'}))
        bid = ok(c.post('/api/mail/boxes', json={'email': 'ali@firma.com', 'password': GOOD, 'provider': 'gmail'}))['id']
        gk = ok(c.post('/api/companies', json={'name': 'Gökkubbe Savunma'}))['id']
        asg = ok(c.post('/api/companies', json={'name': 'ASG Group'}))['id']
        pid = ok(c.post(f'/api/companies/{gk}/people', json={'full_name': 'Burak Türkoğlu', 'email': 'burak@gokkubbe.com'}))['id']
        ok(c.post('/api/mail/people/assign', json={'email': 'burak@asg.com', 'company_id': asg, 'person_id': pid}))
        ok(c.post('/api/companies/people', json={'full_name': 'Serbest Kişi', 'email': 'serbest@y.com'}))
        with db.connect() as conn:
            box = db.row(conn.execute('SELECT * FROM mail_boxes WHERE id = ?', (bid,)))
        mail_cache.full_sync(box, 'inbox')
        mail_cache.full_sync(box, 'trash')

        v = ok(c.get('/api/mail/view/people'))
        known = {r['name']: r for r in v['known']}
        assert set(known) >= {'Burak Türkoğlu', 'Serbest Kişi'} and any(r['kind'] == 'user' for r in v['known']), known
        b = known['Burak Türkoğlu']
        assert sorted(e['email'] for e in b['emails']) == ['burak@asg.com', 'burak@gokkubbe.com'] and sorted(b['companies']) == ['ASG Group', 'Gökkubbe Savunma'], b
        assert b['count'] == 2, b   # "Teklif" iki klasörde ama bir kez sayılır
        assert [u['email'] for u in v['unknown']] == ['yabanci@x.com'] and v['unknown'][0]['name'] == 'Yabancı Biri', v['unknown']
        assert not any(e['email'] == 'ali@firma.com' for r in v['known'] for e in r['emails']), 'kendi adresimiz listelenmez'

        cari = {x['name']: x for x in ok(c.get('/api/mail/view/cari'))}
        assert cari['Gökkubbe Savunma']['count'] == 1 and cari['ASG Group']['count'] == 1, cari
        assert [p['email'] for p in cari['ASG Group']['people']] == ['burak@asg.com']

        r = ok(c.get('/api/mail/view/mails?emails=burak@gokkubbe.com,burak@asg.com'))
        got = sorted((m['subject'], m['match'], m['folder']) for m in r['items'])
        assert got == [('Fatura', 'burak@asg.com', 'inbox'), ('Teklif', 'burak@gokkubbe.com', 'inbox')], got
        assert all(m['box_id'] == bid for m in r['items'])
    print('Mail Kişiler / Cariler görünümü testleri geçti.')


if __name__ == '__main__':
    main()
