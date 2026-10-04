"""Mail önbelleği + CRM › firma › Mailler (sahte IMAP): liste ikinci kez sunucudan başlık indirmeden gelir, bayraklar tazelenir,
sunucuda silinen ileti önbellekten düşer, açılan ileti ikinci kez indirilmez, UIDVALIDITY değişince önbellek yenilenir;
arka plan eşitlemesi gönderilenleri de alır; firma sekmesi yalnız kullanıcının kendi hesaplarından, firmanın kişileri /
alan adıyla yazışmaları gösterir (genel servis alan adı eşleşmez); yetkisiz kullanıcı göremez.
Çalıştırma: .venv/bin/python -m tests.test_mail_cache
"""
from email.message import EmailMessage

from tests.test_mail import GOOD, FakeIMAP, FakeSMTP  # noqa: E402  (ortam ve sahte sunucular)

from fastapi.testclient import TestClient  # noqa: E402

from app import db, mail, mail_cache  # noqa: E402
from app.main import app  # noqa: E402

HOST = 'mail.cache-test.com'
stats = {'hdr': 0, 'body': 0, 'uv': b'1'}


class CountingIMAP(FakeIMAP):
    def response(self, code):
        return code, [stats['uv']]

    def uid(self, cmd, *args):
        if cmd == 'FETCH' and 'HEADER.FIELDS' in args[1]:
            stats['hdr'] += 1
        elif cmd == 'FETCH' and 'FLAGS' not in args[1].replace('UID FLAGS)', ''):   # tam ileti (okuma)
            stats['body'] += 1
        return super().uid(cmd, *args)


def msg(i, frm, to='ali@firma.com', cc=None, subj=None):
    m = EmailMessage()
    m['From'], m['To'], m['Subject'] = frm, to, subj or f'Konu {i}'
    if cc:
        m['Cc'] = cc
    m['Date'] = f'Mon, 28 Sep 2026 1{i}:00:00 +0300'
    m['Message-ID'] = f'<c{i}@x>'
    m.set_content(f'Gövde {i}')
    return {'raw': m.as_bytes(), 'flags': set()}


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    mail.imaplib.IMAP4_SSL = CountingIMAP
    mail.smtplib.SMTP_SSL = mail.smtplib.SMTP = FakeSMTP
    FakeIMAP.servers[HOST] = {
        'INBOX': {1: msg(1, 'Müşteri <ayse@musteri.com.tr>'), 2: msg(2, 'Biri <biri@gmail.com>', cc='mehmet@musteri.com.tr'),
                  3: msg(3, 'Alakasız <x@baska.com>'), 4: msg(4, 'Gmail kişisi <kisi@gmail.com>')},
    }
    sent_name = 'G&APY-nderilmi&AV8- &ANYBHw-eler'
    FakeIMAP.servers[HOST][sent_name] = {1: msg(5, 'Ali <ali@firma.com>', to='Ayşe <ayse@musteri.com.tr>', subj='Teklifimiz')}
    with TestClient(app) as u:
        ok(u.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        b = ok(u.post('/api/mail/boxes', json={'email': 'ali@firma.com', 'password': GOOD, 'provider': 'imap', 'imap_host': HOST,
                                               'imap_port': 993, 'smtp_host': HOST, 'smtp_port': 465, 'smtp_security': 'ssl'}))['id']
        L = lambda: ok(u.get(f'/api/mail/{b}/list?folder=inbox'))['items']  # noqa: E731
        first = L()
        mail_cache.flush()
        assert [x['uid'] for x in first] == [4, 3, 2, 1] and stats['hdr'] == 1
        again = L()
        assert stats['hdr'] == 1, 'ikinci liste başlık indirmemeli'
        assert [(x['uid'], x['subject']) for x in again] == [(x['uid'], x['subject']) for x in first]
        FakeIMAP.servers[HOST]['INBOX'][1]['flags'].add('\\Seen')          # başka cihazda okundu
        assert next(x for x in L() if x['uid'] == 1)['seen'] is True
        del FakeIMAP.servers[HOST]['INBOX'][3]                              # başka cihazda silindi
        assert [x['uid'] for x in L()] == [4, 2, 1]
        mail_cache.flush()
        with db.connect() as conn:
            assert sorted(r[0] for r in conn.execute('SELECT uid FROM mail_cache WHERE box_id = ? AND folder = ?', (b, 'inbox'))) == [1, 2, 4]

        # Okuma: ikinci açılış sunucudan indirmez
        r1 = ok(u.get(f'/api/mail/{b}/msg?folder=inbox&uid=2'))
        mail_cache.flush()
        n = stats['body']
        r2 = ok(u.get(f'/api/mail/{b}/msg?folder=inbox&uid=2'))
        assert stats['body'] == n and r2['subject'] == r1['subject'] and r2['text'].strip() == 'Gövde 2'

        # UIDVALIDITY değişti → önbellek geçersiz, başlıklar yeniden
        stats['uv'] = b'2'
        mail.drop(b)
        L()
        assert stats['hdr'] == 2

        # Arka plan eşitlemesi gönderilenleri de alır
        with db.connect() as conn:
            box = db.row(conn.execute('SELECT * FROM mail_boxes WHERE id = ?', (b,)))
        mail_cache.sync_box(box)
        mail_cache.flush()

        # CRM › firma › Mailler
        cid = ok(u.post('/api/companies', json={'name': 'Müşteri A.Ş.'}))['id']
        ok(u.post('/api/mail/people/assign', json={'email': 'ayse@musteri.com.tr', 'full_name': 'Ayşe', 'company_id': cid}))
        cm = ok(u.get(f'/api/mail/company/{cid}'))
        subj = sorted(x['subject'] for x in cm['items'])
        assert subj == ['Konu 1', 'Konu 2', 'Teklifimiz'], subj               # gelen (ayşe), bilgi (mehmet: aynı alan adı), gönderilen
        assert cm['domains'] == ['musteri.com.tr'] and cm['boxes'] == 1
        assert {x['folder'] for x in cm['items']} == {'inbox', 'sent'}
        # gmail kişisi firmaya eklense de gmail.com alan adı eşleşmez: yalnız o adres
        ok(u.post('/api/mail/people/assign', json={'email': 'kisi@gmail.com', 'full_name': 'Kişi', 'company_id': cid}))
        subj = sorted(x['subject'] for x in ok(u.get(f'/api/mail/company/{cid}'))['items'])
        assert subj == ['Konu 1', 'Konu 2', 'Konu 4', 'Teklifimiz'], subj      # biri@gmail.com (Konu 2) yalnız mehmet cc'de olduğu için
        assert u.get('/api/mail/company/99999').status_code == 404

        # Başka kullanıcı: kendi hesabı yok → boş; Firma Yönetimi yetkisi yoksa → 403
        ok(u.post('/api/users', json={'username': 'crm1', 'full_name': 'CRM Bir', 'roles': ['Satış'], 'password': 'Sifre-1234x'}))
        ok(u.post('/api/users', json={'username': 'pilot1', 'full_name': 'Pilot Bir', 'roles': ['Pilot'], 'password': 'Sifre-1234x'}))
    for name, code in (('crm1', 200), ('pilot1', 403)):
        with TestClient(app) as o:
            ok(o.post('/api/auth/login', json={'username': name, 'password': 'Sifre-1234x'}))
            me = ok(o.get('/api/auth/me'))
            r = o.get(f'/api/mail/company/{cid}')
            if 'companies' in me['modules']:
                assert r.status_code == 200 and r.json()['items'] == [] and r.json()['boxes'] == 0, r.text
            else:
                assert r.status_code == 403, (name, r.status_code)
    print('Mail önbelleği ve CRM mail sekmesi testleri geçti.')


if __name__ == '__main__':
    main()
