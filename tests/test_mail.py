"""Kişisel → Mail: Gmail IMAP/SMTP sahte sunucularla sınanır (bağlama, klasörler, liste, arama, okuma, ek, işlemler,
gönderme, okunmamış bildirimi, başkasının hesabına erişilemez, şifre API'den dönmez).

Çalıştırma: .venv/bin/python -m tests.test_mail
"""
import os
import re
import tempfile
from email.message import EmailMessage

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import mail  # noqa: E402
from app.main import app  # noqa: E402

GOOD = 'abcdefghijklmnop'
SEEN = '\\Seen'


def make(i, subj, frm, html=False, att=False):
    m = EmailMessage()
    m['From'] = frm; m['To'] = 'ali@firma.com'; m['Subject'] = subj
    m['Date'] = f'Mon, 28 Sep 2026 1{i}:00:00 +0300'; m['Message-ID'] = f'<m{i}@firma.com>'
    m.set_content(f'Merhaba {i}')
    if html:
        m.add_alternative(f'<p>Merhaba <b>{i}</b></p><img src="https://iz.example/p.gif"><script>alert(1)</script>', subtype='html')
    if att:
        m.add_attachment(b'%PDF-1.4 ek', maintype='application', subtype='pdf', filename='teklif.pdf')
    return m.as_bytes()


class FakeIMAP:
    boxes = {}
    def __init__(self, host, port, timeout=None):
        self.sel = None
    def login(self, u, p):
        if p != GOOD:
            raise mail.imaplib.IMAP4.error('[AUTHENTICATIONFAILED] Invalid credentials')
    oauth_user = None
    def authenticate(self, mech, cb):
        import base64 as _b
        raw = cb(b'').decode()
        assert mech == 'XOAUTH2' and 'auth=Bearer erisim-' in raw
        FakeIMAP.oauth_user = raw.split('user=')[1].split('\x01')[0]
    def logout(self): pass
    def noop(self): return 'OK', [b'']
    def response(self, code): return code, [b'1']
    def list(self):
        return 'OK', [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Sent) "/" "[Gmail]/G&APY-nderilmi&AV8- Postalar"',
                      b'(\\HasNoChildren \\Trash) "/" "[Gmail]/&AMcA9g-p"', b'(\\All \\HasNoChildren) "/" "[Gmail]/T&APw-m Postalar"']
    def status(self, box, what):
        b = self.boxes.get(box.strip('"'), {})
        unseen = sum(1 for m in b.values() if SEEN not in m['flags'])
        return 'OK', [f'{box} (MESSAGES {len(b)} UNSEEN {unseen})'.encode()]
    def select(self, box, readonly=False):
        self.sel = box.strip('"'); return 'OK', [b'1']
    def expunge(self):
        b = self.boxes[self.sel]
        for k in [k for k, m in b.items() if '\\Deleted' in m['flags']]:
            del b[k]
        return 'OK', []
    def uid(self, cmd, *args):
        b = self.boxes.setdefault(self.sel, {})
        if cmd == 'SEARCH':
            if 'X-GM-RAW' in args:
                q = args[-1].decode().strip('"').lower()
                ids = [u for u, m in b.items() if q in m['raw'].decode(errors='replace').lower()]
            elif 'UNSEEN' in args:
                ids = [u for u, m in b.items() if '\\Seen' not in m['flags']]
            else:
                ids = list(b)
            return 'OK', [' '.join(map(str, ids)).encode()]
        ids = [int(x) for x in args[0].split(',')]
        if cmd == 'FETCH':
            out = []
            for u in ids:
                m = b.get(u)
                if not m:
                    continue
                meta = f'{u} (UID {u} FLAGS ({" ".join(m["flags"])}) RFC822.SIZE {len(m["raw"])} BODY[] {{1}}'.encode()
                data = m['raw']
                if 'HEADER.FIELDS' in args[1]:
                    data = m['raw'].split(b'\n\n')[0] + b'\n\n'
                out += [(meta, data), b')']
            return 'OK', out
        if cmd == 'STORE':
            for u in ids:
                f = b[u]['flags']
                flag = re.search(r'\\\w+', args[2]).group(0)
                (f.add if args[1].startswith('+') else f.discard)(flag)
            return 'OK', []
        if cmd == 'MOVE':
            dest = self.boxes.setdefault(args[1].strip('"'), {})
            for u in ids:
                dest[max(dest, default=0) + 1] = b.pop(u)
            return 'OK', []
        return 'NO', []


class FakeSMTP:
    sent = []
    def __init__(self, host, port, timeout=None): pass
    def login(self, u, p):
        if p != GOOD:
            raise mail.smtplib.SMTPAuthenticationError(535, b'Username and Password not accepted')
    def send_message(self, msg, from_addr, to_addrs): FakeSMTP.sent.append((msg, to_addrs))
    oauth_user = None
    def ehlo(self): pass
    def docmd(self, cmd, arg):
        import base64 as _b
        raw = _b.b64decode(arg.split(' ', 1)[1]).decode()
        FakeSMTP.oauth_user = raw.split('user=')[1].split('\x01')[0]
        return 235, b'OK'
    def quit(self): pass


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    mail.imaplib.IMAP4_SSL = FakeIMAP
    mail.smtplib.SMTP_SSL = FakeSMTP
    FakeIMAP.boxes['INBOX'] = {1: {'raw': make(1, 'Teklif', 'Veli Kaya <veli@musteri.com>', att=True), 'flags': set()},
                               2: {'raw': make(2, 'Toplantı', '"Ayşe" <ayse@musteri.com>', html=True), 'flags': {'\\Seen'}},
                               3: {'raw': make(3, '=?utf-8?b?w4dhecSxcg==?=', 'x@y.com'), 'flags': set()}}
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ok(a.post('/api/users', json={'username': 'ali', 'full_name': 'Ali', 'roles': ['İdari Personel'], 'password': 'sifre-1234'}))
        ok(a.post('/api/users', json={'username': 'veli', 'full_name': 'Veli', 'roles': ['İdari Personel'], 'password': 'sifre-1234'}))
    with TestClient(app) as u, TestClient(app) as v:
        ok(u.post('/api/auth/login', json={'username': 'ali', 'password': 'sifre-1234'}))
        ok(v.post('/api/auth/login', json={'username': 'veli', 'password': 'sifre-1234'}))
        assert ok(u.get('/api/mail/account')) == {'connected': False, 'oauth_available': False}
        assert u.get('/api/mail/list').status_code == 404
        assert u.get('/api/mail/oauth/start').status_code == 400   # Google bağlantısı ayarlanmamış
        r = u.post('/api/mail/account', json={'email': 'ali@firma.com', 'password': 'yanlis-sifre'})
        assert r.status_code == 400 and 'uygulama şifresi' in r.json()['detail']
        acc = ok(u.post('/api/mail/account', json={'email': 'Ali@Firma.com', 'password': 'abcd efgh ijkl mnop'}))
        assert acc['connected'] and acc['email'] == 'ali@firma.com' and 'secret' not in acc and 'password' not in acc
        f = {x['key']: x for x in ok(u.get('/api/mail/folders'))}
        assert set(f) == {'inbox', 'sent', 'trash', 'all'} and f['inbox']['unseen'] == 2, f
        lst = ok(u.get('/api/mail/list?folder=inbox'))
        assert [m['uid'] for m in lst['items']] == [3, 2, 1] and lst['total'] == 3
        byuid = {m['uid']: m for m in lst['items']}
        assert byuid[1]['from'] == {'name': 'Veli Kaya', 'email': 'veli@musteri.com'} and byuid[1]['attach'] and not byuid[1]['seen']
        assert byuid[3]['subject'] == 'Çayır' and byuid[2]['seen']
        assert [m['uid'] for m in ok(u.get('/api/mail/list?q=toplant'))['items']] == [2]
        # bildirim: okunmamış
        n = {x['key']: x for x in ok(u.get('/api/notifications'))['items']}
        assert n['mail-unread']['count'] == 2 and n['mail-unread']['href'] == '#/mail'
        # okuma: html temizlenir, okundu olur, ek listelenir
        d = ok(u.get('/api/mail/msg/inbox/2'))
        assert '<script' not in d['html'] and 'https://iz.example' in d['html'] and d['from']['name'] == 'Ayşe'
        d = ok(u.get('/api/mail/msg/inbox/1'))
        assert d['attachments'][0]['name'] == 'teklif.pdf' and '\\Seen' in FakeIMAP.boxes['INBOX'][1]['flags']
        r = u.get('/api/mail/att/inbox/1/0')
        assert r.status_code == 200 and r.content.startswith(b'%PDF') and 'teklif.pdf' in r.headers['content-disposition']
        # işlemler
        ok(u.post('/api/mail/action', json={'folder': 'inbox', 'uids': [1], 'action': 'unread'}))
        assert '\\Seen' not in FakeIMAP.boxes['INBOX'][1]['flags']
        ok(u.post('/api/mail/action', json={'folder': 'inbox', 'uids': [1], 'action': 'star'}))
        ok(u.post('/api/mail/action', json={'folder': 'inbox', 'uids': [3], 'action': 'trash'}))
        assert 3 not in FakeIMAP.boxes['INBOX'] and FakeIMAP.boxes['[Gmail]/&AMcA9g-p']
        ok(u.post('/api/mail/action', json={'folder': 'inbox', 'uids': [2], 'action': 'archive'}))
        assert list(FakeIMAP.boxes['INBOX']) == [1]
        assert u.post('/api/mail/action', json={'folder': 'inbox', 'uids': [1], 'action': 'yok'}).status_code == 400
        # gönderme: yanıt başlıkları, ek, imza, iletmede orijinal ek
        ok(u.put('/api/mail/account', json={'name': 'Ali Yılmaz', 'signature': 'Ali Yılmaz · Gökkubbe'}))
        ok(u.post('/api/mail/send', data={'to': 'veli@musteri.com', 'cc': 'b@x.com', 'bcc': 'gizli@x.com', 'subject': 'Re: Teklif', 'body': 'Teşekkürler',
                                          'reply_id': '<m1@firma.com>'}, files=[('files', ('not.txt', b'selam', 'text/plain'))]))
        msg, rcpts = FakeSMTP.sent[-1]
        assert rcpts == ['veli@musteri.com', 'b@x.com', 'gizli@x.com'] and msg['In-Reply-To'] == '<m1@firma.com>' and 'Bcc' not in msg
        assert 'Ali Yılmaz · Gökkubbe' in msg.get_body(('plain',)).get_content() and 'Ali Y' in msg['From']
        assert [p.get_filename() for p in msg.iter_attachments()] == ['not.txt']
        ok(u.post('/api/mail/send', data={'to': 'c@x.com', 'subject': 'Fwd: Teklif', 'fwd_folder': 'inbox', 'fwd_uid': '1'}))
        assert [p.get_filename() for p in FakeSMTP.sent[-1][0].iter_attachments()] == ['teklif.pdf']
        assert u.post('/api/mail/send', data={'to': ' '}).status_code in (400, 422)
        # Ekler → Evrak Yönetimi: elle kaydet (yalnızca sahibi görür, OCR sırasına girer), ikinci kez aktarılmaz
        acc = ok(u.get('/api/mail/account'))
        assert acc['can_import'] and acc['auto_import']
        r = ok(u.post('/api/mail/import', json={'folder': 'inbox', 'uid': 1}))
        assert r['imported'] == 1
        doc = ok(u.get(f'/api/documents/{r["ids"][0]}'))
        assert doc['visibility'] == 'PRIVATE' and doc['file_name'] == 'teklif.pdf' and 'E-posta eki · Teklif' in doc['note']
        assert ok(u.post('/api/mail/import', json={'folder': 'inbox', 'uid': 1}))['imported'] == 0
        assert v.get(f'/api/documents/{r["ids"][0]}').status_code == 404                       # başka kullanıcı göremez
        assert r['ids'][0] not in [d['id'] for d in ok(v.get('/api/documents'))['documents']]
        with TestClient(app) as a:
            ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
            assert a.get(f'/api/documents/{r["ids"][0]}').status_code == 404                   # yönetici de göremez
        # Otomatik tarama: ilk taramada geçmiş aktarılmaz; sonra gelen ekli e-posta aktarılır
        from app import db, mail_import
        with db.connect() as conn:
            row = db.row(conn.execute('SELECT * FROM mail_accounts WHERE user_id = 2'))
            assert mail_import.sync_account(conn, row) == 0
            FakeIMAP.boxes['INBOX'][9] = {'raw': make(9, 'Sözleşme', 'hukuk@musteri.com', att=True), 'flags': set()}
            row = db.row(conn.execute('SELECT * FROM mail_accounts WHERE user_id = 2'))
            assert mail_import.sync_account(conn, row) == 1
            row = db.row(conn.execute('SELECT * FROM mail_accounts WHERE user_id = 2'))
            assert row['last_uid'] == 9 and mail_import.sync_account(conn, row) == 0
        docs = ok(u.get('/api/documents'))['documents']
        assert sorted(d['note'].split(' · ')[1] for d in docs) == ['Sözleşme', 'Teklif']
        # başkası erişemez
        assert v.get('/api/mail/list').status_code == 404 and v.get('/api/mail/msg/inbox/1').status_code == 404
        # ayır
        ok(u.delete('/api/mail/account'))
        assert not ok(u.get('/api/mail/account'))['connected']

        # Google ile bağlan (OAuth): izin → jeton → XOAUTH2 ile IMAP/SMTP
        from urllib.parse import parse_qs, urlparse
        from app import config
        from app.routers import mail as mail_router
        config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET = 'istemci', 'gizli'
        calls = []

        class R:
            def __init__(self, code, data): self.status_code, self._d = code, data
            def json(self): return self._d

        def fake_post(url, data=None, timeout=None, **kw):
            calls.append((url, data))
            if data.get('grant_type') == 'authorization_code':
                return R(200, {'access_token': 'erisim-1', 'refresh_token': 'yenileme-1', 'expires_in': 3600}) if data['code'] == 'kod' else R(400, {})
            if data.get('grant_type') == 'refresh_token':
                return R(200, {'access_token': 'erisim-2', 'expires_in': 3600})
            return R(200, {})
        mail_router.httpx.post = mail.httpx.post = fake_post
        mail_router.httpx.get = lambda url, headers=None, timeout=None: R(200, {'email': 'Ali@Gokkubbe.com'})
        assert ok(u.get('/api/mail/account'))['oauth_available']
        url = ok(u.get('/api/mail/oauth/start'))['url']
        qs = parse_qs(urlparse(url).query)
        assert qs['access_type'] == ['offline'] and 'https://mail.google.com/' in qs['scope'][0] and qs['redirect_uri'][0].endswith('/api/mail/oauth/callback')
        r = u.get(f'/api/mail/oauth/callback?state={qs["state"][0]}&code=kod', follow_redirects=False)
        assert r.status_code == 303 and r.headers['location'] == '/app#/mail/oauth/ok', r.headers['location']
        acc = ok(u.get('/api/mail/account'))
        assert acc['connected'] and acc['auth_type'] == 'oauth' and acc['email'] == 'ali@gokkubbe.com'
        assert FakeIMAP.oauth_user == 'ali@gokkubbe.com'
        # aynı durum jetonu ikinci kez / başka kullanıcı kullanamaz
        assert 'oauth/ok' not in u.get(f'/api/mail/oauth/callback?state={qs["state"][0]}&code=kod', follow_redirects=False).headers['location']
        st = parse_qs(urlparse(ok(u.get('/api/mail/oauth/start'))['url']).query)['state'][0]
        assert 'oauth/ok' not in v.get(f'/api/mail/oauth/callback?state={st}&code=kod', follow_redirects=False).headers['location']
        assert len(ok(u.get('/api/mail/list'))['items']) >= 1
        ok(u.post('/api/mail/send', data={'to': 'x@y.com', 'subject': 'OAuth', 'body': 'deneme'}))
        assert FakeSMTP.oauth_user == 'ali@gokkubbe.com'
        ok(u.delete('/api/mail/account'))
        assert any('revoke' in c[0] for c in calls)                      # ayırınca Google izni geri alınır
    print('Mail testleri geçti.')


if __name__ == '__main__':
    main()
