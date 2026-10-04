"""Yeni mail: Rehber'den kişi seçme (ad / e-posta / FİRMA adıyla; bağlı firma görünür) ve Evrak Yönetimi'nden ek
(yalnız görme yetkisi olan evraklar; yetkisiz evrak numarası verilirse gönderim reddedilir); alıcıların firmaları.
Çalıştırma: .venv/bin/python -m tests.test_mail_compose
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@gokkubbetech.com',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, mail  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_mail import GOOD, FakeIMAP, FakeSMTP  # noqa: E402

mail.imaplib.IMAP4_SSL = FakeIMAP
mail.smtplib.SMTP_SSL = mail.smtplib.SMTP = FakeSMTP


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def doc(conn, title, fname, vis='ALL', company=None):
    (config.UPLOAD_DIR / 'documents').mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / 'documents' / fname).write_bytes(b'%PDF-1.4 ' + title.encode())
    i = conn.execute("""INSERT INTO documents (title, kind, file, file_name, size, visibility, uploaded_by, uploaded_at, ocr_status)
                        VALUES (?, 'pdf', ?, ?, 20, ?, NULL, ?, 'TAMAM')""", (title, f'documents/{fname}', fname, vis, db.now())).lastrowid
    if company:
        conn.execute('INSERT INTO document_companies (document_id, company_id) VALUES (?, ?)', (i, company))
    if vis == 'ROLES':
        conn.execute("INSERT INTO document_roles (document_id, role) VALUES (?, 'Gizli Rol')", (i,))
    return i


def main():
    FakeIMAP.servers['imap.gmail.com'] = {'INBOX': {}}
    with TestClient(app) as c:
        ok(c.post('/api/auth/login', json={'username': 'admin@gokkubbetech.com', 'password': 'admin-sifre-1'}))
        bid = ok(c.post('/api/mail/boxes', json={'email': 'ali@gmail.com', 'password': GOOD, 'provider': 'gmail'}))['id']
        gk = ok(c.post('/api/companies', json={'name': 'Gökkubbe Savunma'}))['id']
        asg = ok(c.post('/api/companies', json={'name': 'ASG Group'}))['id']
        pid = ok(c.post(f'/api/companies/{gk}/people', json={'full_name': 'Burak Türkoğlu', 'email': 'burak@gokkubbe.com'}))['id']
        ok(c.post('/api/mail/people/assign', json={'email': 'burak@asg.com', 'company_id': asg, 'person_id': pid}))   # aynı kişi, iki firma
        ok(c.post(f'/api/companies/{asg}/people', json={'full_name': 'Adressiz Kişi'}))

        # kişi seçme: firma adıyla (Türkçe harf duyarsız), her adres kendi firmasıyla; e-postasız kişi gelmez
        r = ok(c.get('/api/mail/people/pick?q=gokkubbe savunma'))
        assert [(x['name'], x['email'], x['company']) for x in r] == [('Burak Türkoğlu', 'burak@gokkubbe.com', 'Gökkubbe Savunma')], r
        r = ok(c.get('/api/mail/people/pick?q=burak'))
        assert {(x['email'], x['company']) for x in r} == {('burak@gokkubbe.com', 'Gökkubbe Savunma'), ('burak@asg.com', 'ASG Group')}, r
        assert not any(x['name'] == 'Adressiz Kişi' for x in ok(c.get('/api/mail/people/pick?q=asg')))
        assert any(x['kind'] == 'user' for x in ok(c.get('/api/mail/people/pick?q=admin'))), 'sistem kullanıcıları da'

        # alıcıların firmaları
        cs = ok(c.get('/api/mail/people/companies?emails=burak@asg.com,yabanci@x.com'))
        assert cs == [{'id': asg, 'name': 'ASG Group'}], cs

        with db.connect() as conn:
            d1 = doc(conn, 'Teklif', 'teklif.pdf', company=gk)
            d2 = doc(conn, 'Gizli bordro', 'gizli.pdf', 'ROLES')
            conn.commit()
        # firmaya etiketli evraklar / yetkisiz evrak listede yok
        assert [d['id'] for d in ok(c.get(f'/api/documents?company_id={gk}'))['documents']] == [d1]
        assert d2 not in [d['id'] for d in ok(c.get('/api/documents'))['documents']]

        # gönderim: yetkili evrak ek olur, yetkisiz evrak reddedilir (hiçbir şey gönderilmez)
        n = len(FakeSMTP.sent)
        r = c.post(f'/api/mail/{bid}/send', data={'to': 'burak@gokkubbe.com', 'subject': 'x', 'body': 'y', 'doc_ids': f'{d1},{d2}'})
        assert r.status_code == 403 and len(FakeSMTP.sent) == n, r.text
        ok(c.post(f'/api/mail/{bid}/send', data={'to': 'burak@gokkubbe.com', 'subject': 'Teklif', 'body': 'Ekte', 'doc_ids': str(d1)}))
        msg = FakeSMTP.sent[-1][1]
        att = [(p.get_filename(), p.get_content_type(), p.get_payload(decode=True)) for p in msg.iter_attachments()]
        assert att == [('teklif.pdf', 'application/pdf', b'%PDF-1.4 Teklif')], att
    print('Yeni mail kişi / evrak eki testleri geçti.')


if __name__ == '__main__':
    main()
