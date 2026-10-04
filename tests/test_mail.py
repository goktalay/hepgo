"""Kişisel → Mail v2 (çok hesaplı, Outlook gibi): sahte IMAP / POP3 / SMTP sunucularıyla — hesap ekleme (Gmail uygulama
şifresi, özel IMAP + STARTTLS SMTP, POP3), klasörler (özel kullanım + Türkçe adlar + özel klasör), liste, arama, okuma,
davet (ICS) → kişisel takvim, ek, işlemler, gönderme (Gönderilenler'e kayıt), taslak, birleşik gelen kutusu, kişi önerisi,
kişisel rehber gizliliği, başkasının hesabına erişilemez, şifre API'den dönmez; sosyal medya RSS akışı yalnız sahibine.

Çalıştırma: .venv/bin/python -m tests.test_mail
"""
import os
import re
import tempfile
from email.message import EmailMessage

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import mail, social  # noqa: E402
from app.main import app  # noqa: E402

GOOD = 'abcdefghijklmnop'
SEEN = '\\Seen'
ICS = '''BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\nUID:davet-1@firma.com\r\nSUMMARY:Proje toplantısı\r\nDTSTART:20261015T070000Z\r\nDTEND:20261015T080000Z\r\nLOCATION:Toplantı Odası\r\nORGANIZER:mailto:veli@musteri.com\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'''


def make(i, subj, frm, html=False, att=False, ics=False):
    m = EmailMessage()
    m['From'] = frm; m['To'] = 'ali@firma.com'; m['Subject'] = subj
    m['Date'] = f'Mon, 28 Sep 2026 1{i}:00:00 +0300'; m['Message-ID'] = f'<m{i}@firma.com>'
    m.set_content(f'Merhaba {i}')
    if html:
        m.add_alternative(f'<p>Merhaba <b>{i}</b></p><script>alert(1)</script>', subtype='html')
    if att:
        m.add_attachment(b'%PDF-1.4 ek', maintype='application', subtype='pdf', filename='teklif.pdf')
    if ics:
        m.add_attachment(ICS.encode(), maintype='text', subtype='calendar', filename='invite.ics')
    return m.as_bytes()


class FakeIMAP:
    servers = {}   # host → {klasör: {uid: {...}}}
    def __init__(self, host, port, timeout=None):
        self.boxes = FakeIMAP.servers.setdefault(host, {})
        self.host, self.sel, self.literal = host, None, None
    def login(self, u, p):
        if p != GOOD:
            raise mail.imaplib.IMAP4.error('[AUTHENTICATIONFAILED] Invalid credentials')
    def logout(self): pass
    def noop(self): return 'OK', [b'']
    def response(self, code): return code, [b'1']
    def list(self):
        if 'gmail' in self.host:
            return 'OK', [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Sent) "/" "[Gmail]/G&APY-nderilmi&AV8- Postalar"',
                          b'(\\HasNoChildren \\Trash) "/" "[Gmail]/&AMcA9g-p"', b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Taslaklar"']
        return 'OK', [b'(\\HasNoChildren) "." "INBOX"', b'(\\HasNoChildren) "." "G&APY-nderilmi&AV8- &ANYBHw-eler"',
                      b'(\\HasNoChildren) "." "Silinmi&AV8- &ANYBHw-eler"', b'(\\HasNoChildren) "." "Taslaklar"', b'(\\HasNoChildren) "." "Projeler"',
                      b'(\\Noselect \\HasChildren) "." "Arsiv"']
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
    def append(self, box, flags, date, raw):
        b = self.boxes.setdefault(box.strip('"'), {})
        b[max(b, default=0) + 1] = {'raw': raw, 'flags': set(re.findall(r'\\\w+', flags))}
        return 'OK', []
    def uid(self, cmd, *args):
        b = self.boxes.setdefault(self.sel, {})
        if cmd == 'SEARCH':
            if 'X-GM-RAW' in args:
                q = args[-1].decode().strip('"').lower()
            elif 'TEXT' in args and self.literal:
                q = self.literal.decode().lower(); self.literal = None
            else:
                q = None
            if q is not None:   # gerçek sunucular gibi: kodlanmış konu başlığı da çözülerek aranır
                txt = lambda raw: (raw.decode(errors='replace') + ' ' + mail._dec(mail.email.message_from_bytes(raw)['Subject'])).lower()
                ids = [u for u, m in b.items() if q in txt(m['raw'])]
            elif 'UNSEEN' in args:
                ids = [u for u, m in b.items() if SEEN not in m['flags']]
            else:
                ids = list(b)
            return 'OK', [' '.join(map(str, ids)).encode()]
        ids = [int(x) for x in args[0].split(',')]
        if cmd == 'FETCH':   # gerçek sunucu gibi: liste isteğinde başlık ve kısmi gövde ayrı literal olarak döner
            out = []
            for u in ids:
                m = b.get(u)
                if not m:
                    continue
                head = f'{u} (UID {u} FLAGS ({" ".join(m["flags"])}) RFC822.SIZE {len(m["raw"])}'
                if 'HEADER.FIELDS' in args[1]:
                    hdr, _, body = m['raw'].partition(b'\n\n')
                    lim = re.search(r'TEXT\]<0\.(\d+)>', args[1])
                    out.append((f'{head} BODY[HEADER.FIELDS (FROM TO SUBJECT DATE CONTENT-TYPE)] {{{len(hdr) + 2}}}'.encode(), hdr + b'\n\n'))
                    if lim:
                        out.append((f' BODY[TEXT]<0> {{{min(len(body), int(lim.group(1)))}}}'.encode(), body[:int(lim.group(1))]))
                else:
                    out.append((f'{head} BODY[] {{{len(m["raw"])}}}'.encode(), m['raw']))
                out.append(b')')
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
    def __init__(self, host, port, timeout=None): self.host = host
    def ehlo(self): pass
    def starttls(self): self.tls = True
    def login(self, u, p):
        if p != GOOD:
            raise mail.smtplib.SMTPAuthenticationError(535, b'Username and Password not accepted')
    def send_message(self, msg, from_addr, to_addrs):
        assert msg['Bcc'] is None, 'Bcc başlığı alıcılara gitmemeli'
        FakeSMTP.sent.append((self.host, msg, to_addrs))
    def quit(self): pass


class FakePOP:
    msgs = []
    def __init__(self, host, port, timeout=None): pass
    def user(self, u): pass
    def pass_(self, p):
        if p != GOOD:
            raise mail.poplib.error_proto(b'-ERR authentication failed')
    def uidl(self): return b'+OK', [f'{i + 1} pop-{i}'.encode() for i in range(len(self.msgs))], 0
    def top(self, no, n):
        hdr, _, body = self.msgs[no - 1].partition(b'\n\n')
        return b'+OK', hdr.split(b'\n') + [b''] + body.split(b'\n')[:n], 0
    def retr(self, no): return b'+OK', self.msgs[no - 1].split(b'\n'), 0
    def dele(self, no): self.msgs[no - 1] = None
    def quit(self): FakePOP.msgs = [m for m in self.msgs if m]


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


RSS = '''<?xml version="1.0"?><rss version="2.0"><channel><title>Ali'nin Blogu</title>
<item><title>Yeni prototip</title><link>https://blog.example/1</link><guid>g1</guid><pubDate>Mon, 28 Sep 2026 10:00:00 +0300</pubDate><description>&lt;p&gt;Uçuş testi&lt;/p&gt;</description></item>
<item><title>Fuar</title><link>https://blog.example/2</link><guid>g2</guid><pubDate>Sun, 27 Sep 2026 10:00:00 +0300</pubDate><description>IDEF</description></item>
</channel></rss>'''.encode()


class FakeResp:
    def __init__(self, content, status=200): self.content, self.status_code, self.text = content, status, content.decode()


def main():
    mail.imaplib.IMAP4_SSL = FakeIMAP
    mail.smtplib.SMTP_SSL = FakeSMTP
    mail.smtplib.SMTP = FakeSMTP
    mail.poplib.POP3_SSL = FakePOP
    social.httpx.get = lambda url, **kw: FakeResp(RSS)
    FakeIMAP.servers['imap.gmail.com'] = {'INBOX': {
        1: {'raw': make(1, 'Teklif', 'Veli Kaya <veli@musteri.com>', att=True), 'flags': set()},
        2: {'raw': make(2, 'Toplantı daveti', '"Ayşe" <ayse@musteri.com>', html=True, ics=True), 'flags': {SEEN}},
        3: {'raw': make(3, '=?utf-8?b?w4dhecSxcg==?=', 'x@y.com'), 'flags': set()}}}
    FakeIMAP.servers['mail.firma.com'] = {'INBOX': {1: {'raw': make(4, 'Sipariş', 'Tedarikçi <satis@tedarik.com>'), 'flags': set()}}}
    FakePOP.msgs = [make(5, 'POP iletisi', 'pop@ornek.com'), make(6, 'İkinci', 'pop2@ornek.com')]
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ok(a.post('/api/users', json={'username': 'ali', 'full_name': 'Ali', 'roles': ['İdari Personel'], 'password': 'Gizli-Parola-71x'}))
        ok(a.post('/api/users', json={'username': 'veli', 'full_name': 'Veli', 'roles': ['İdari Personel'], 'password': 'Gizli-Parola-71x'}))
    with TestClient(app) as u, TestClient(app) as v:
        ok(u.post('/api/auth/login', json={'username': 'ali', 'password': 'Gizli-Parola-71x'}))
        ok(v.post('/api/auth/login', json={'username': 'veli', 'password': 'Gizli-Parola-71x'}))
        assert ok(u.get('/api/mail/boxes'))['boxes'] == []
        assert 'outlook' in ok(u.get('/api/mail/providers'))['providers']
        # Gmail: yanlış şifre → anlaşılır hata; doğru uygulama şifresi (boşluklu) → bağlanır
        r = u.post('/api/mail/boxes', json={'email': 'ali@gmail.com', 'password': 'yanlis-sifre', 'provider': 'gmail'})
        assert r.status_code == 400 and 'uygulama şifresi' in r.json()['detail'], r.text
        g = ok(u.post('/api/mail/boxes', json={'email': 'Ali@gmail.com', 'password': 'abcd efgh ijkl mnop', 'provider': 'gmail', 'name': 'Ali K.'}))
        assert g['email'] == 'ali@gmail.com' and 'secret' not in g and g['save_sent'] == 0
        assert u.post('/api/mail/boxes', json={'email': 'x@outlook.com', 'password': GOOD, 'provider': 'outlook'}).status_code == 400   # yalnız OAuth
        # Özel IMAP + STARTTLS SMTP
        c = ok(u.post('/api/mail/boxes', json={'email': 'ali@firma.com', 'password': GOOD, 'provider': 'imap', 'imap_host': 'mail.firma.com', 'imap_port': 993,
                                                'smtp_host': 'mail.firma.com', 'smtp_port': 587, 'smtp_security': 'starttls'}))
        assert c['save_sent'] == 1
        p = ok(u.post('/api/mail/boxes', json={'email': 'ali@pop.com', 'password': GOOD, 'provider': 'pop3', 'pop_host': 'pop.ornek.com', 'pop_port': 995,
                                                'smtp_host': 'smtp.ornek.com', 'smtp_port': 465, 'smtp_security': 'ssl'}))
        assert u.post('/api/mail/boxes', json={'email': 'ali@firma.com', 'password': GOOD, 'provider': 'imap', 'imap_host': 'h', 'smtp_host': 'h'}).status_code == 409
        # Klasörler: Türkçe adlar ve özel klasör
        f = ok(u.get(f"/api/mail/{c['id']}/folders"))
        keys = {x['key']: x for x in f}
        assert {'inbox', 'sent', 'drafts', 'trash'} <= set(keys) and 'x:Projeler' in keys and keys['x:Projeler']['title'] == 'Projeler', f
        fg = {x['key'] for x in ok(u.get(f"/api/mail/{g['id']}/folders"))}
        assert {'inbox', 'sent', 'trash', 'drafts'} <= fg
        # Liste önizlemesi (snippet): düz metin / HTML (betik ve stil atılır) / POP3
        lst = ok(u.get(f"/api/mail/{g['id']}/list?folder=inbox"))['items']
        snip = {x['subject']: x['snippet'] for x in lst}
        assert snip['Teklif'].startswith('Merhaba 1'), snip
        assert all('alert' not in v and '<' not in v for v in snip.values()), snip
        assert ok(u.get(f"/api/mail/{p['id']}/list?folder=inbox"))['items'][0]['snippet'].startswith('Merhaba'), 'POP3 önizleme'
        # Bildirim: okunmamış e-postalar gönderen + konu + içerik özetiyle; okundu işaretlenmez
        nt = next(x for x in ok(u.get('/api/notifications'))['items'] if x['key'] == 'mail-unread')
        assert nt['count'] >= 2 and any('Teklif — Merhaba 1' in x for x in nt['names']), nt
        assert nt['push']['title'].startswith('✉️') and nt['push']['body'], nt
        assert SEEN not in FakeIMAP.servers['imap.gmail.com']['INBOX'][1]['flags'], 'önizleme okundu işaretlememeli'
        # Kişi → firma: gönderen bir firmaya personel olarak atanır; sonraki listede / okumada firma adı görünür
        from app import db as _db
        with _db.connect() as cc_:
            comp_id = cc_.execute("INSERT INTO companies (name, active, created_at) VALUES ('Müşteri A.Ş.', 1, '2026-01-01T00:00:00')").lastrowid
            cc_.commit()
        assert any(c['id'] == comp_id for c in ok(u.get('/api/mail/companies?q=Müşteri')))
        r = ok(u.post('/api/mail/people/assign', json={'email': 'Veli@Musteri.com', 'full_name': 'Veli Kaya', 'company_id': comp_id, 'title': 'Satın Alma'}))
        assert r['company_name'] == 'Müşteri A.Ş.' and r['title'] == 'Satın Alma', r
        row_ = next(x for x in ok(u.get(f"/api/mail/{g['id']}/list?folder=inbox"))['items'] if x['subject'] == 'Teklif')
        assert row_['company'] == 'Müşteri A.Ş.', row_
        assert v.post('/api/mail/people/assign', json={'email': 'x@y.com', 'full_name': 'X', 'company_id': comp_id}).status_code in (403, 200)
        # Adres başka firmada kayıtlıysa oradaki kişiye dokunulmaz; seçilen firmaya yeni kişi eklenir, en son atanan görünür
        with _db.connect() as cc_:
            b_id = cc_.execute("INSERT INTO companies (name, active, created_at) VALUES ('Bayi B', 1, '2026-01-01T00:00:00')").lastrowid
            rana = cc_.execute("INSERT INTO company_people (company_id, full_name, email, created_at) VALUES (?, 'Rana', 'rana@b.com', '2026-01-01')", (b_id,)).lastrowid
            sup_id = cc_.execute("INSERT INTO companies (name, active, is_supplier, created_at) VALUES ('Tedarikçi T', 1, 1, '2026-01-01T00:00:00')").lastrowid
            cc_.commit()
        r = ok(u.post('/api/mail/people/assign', json={'email': 'rana@b.com', 'full_name': 'Rana Yılmaz', 'company_id': comp_id}))
        assert r['company_id'] == comp_id and r['person_id'] != rana, r
        with _db.connect() as cc_:
            assert tuple(cc_.execute('SELECT company_id, full_name, email FROM company_people WHERE id = ?', (rana,)).fetchone()) == (b_id, 'Rana', 'rana@b.com')
        r = ok(u.delete(f"/api/mail/people/assign?person_id={r['person_id']}&email=rana@b.com"))
        assert r['company']['company_id'] == b_id, r   # yalnız o kişiden kaldırıldı; B'deki kayıt yerinde
        assert u.delete(f'/api/mail/people/assign?person_id={rana}&email=baska@b.com').status_code == 404
        # Tedarikçi firmalar Satın Alma yetkisi ister (Firmalar'daki kural)
        from app.routers.mail import _co_write
        only_co = {'modules': ['companies'], 'write_modules': ['companies']}
        assert _co_write(only_co, False) and not _co_write(only_co, True)
        assert not _co_write({'modules': ['companies'], 'write_modules': []}, False), 'salt okunur Firmalar yetkisi atayamaz'
        assert not any(c['id'] == sup_id for c in ok(u.get('/api/mail/companies?q=Tedarik'))), 'İdari Personel tedarikçiyi görmez'
        assert u.post('/api/mail/people/assign', json={'email': 'z@t.com', 'full_name': 'Z', 'company_id': sup_id}).status_code == 403
        # Sonsuz kaydırma: sıra konumuyla (offset) sonraki parça
        assert [x['uid'] for x in ok(u.get(f"/api/mail/{g['id']}/list?folder=inbox&offset=1"))['items']] == [2, 1]
        # Liste, arama, okuma + davet takvime, kişi rehbere
        lst = ok(u.get(f"/api/mail/{g['id']}/list?folder=inbox"))
        assert [x['uid'] for x in lst['items']] == [3, 2, 1] and lst['items'][2]['attach']
        assert [x['uid'] for x in ok(u.get(f"/api/mail/{g['id']}/list?folder=inbox&q=teklif"))['items']] == [1]
        assert [x['uid'] for x in ok(u.get(f"/api/mail/{c['id']}/list?folder=inbox&q=sipariş"))['items']] == [1]
        d = ok(u.get(f"/api/mail/{g['id']}/msg?folder=inbox&uid=2"))
        assert '<script' not in d['html'] and d['invite']['title'] == 'Proje toplantısı' and d['invite']['added']
        ev = ok(u.get('/api/crm/my/events?start=2026-10-01T00:00:00&end=2026-11-01T00:00:00'))
        assert any(e.get('kind') == 'KISISEL' and 'Proje toplantısı' in e['title'] for e in ev), ev
        assert not any(e.get('kind') == 'KISISEL' for e in ok(v.get('/api/crm/my/events?start=2026-10-01T00:00:00&end=2026-11-01T00:00:00')))
        att = u.get(f"/api/mail/{g['id']}/att?folder=inbox&uid=1&idx=0")
        assert att.status_code == 200 and att.content.startswith(b'%PDF')
        # Birleşik gelen kutusu
        uni = ok(u.get('/api/mail/unified/inbox'))
        assert {x['box_id'] for x in uni['items']} == {g['id'], c['id'], p['id']} and not uni['errors'], uni['errors']
        # POP3: okuma / okundu / silme
        pl = ok(u.get(f"/api/mail/{p['id']}/list"))
        assert len(pl['items']) == 2 and not pl['items'][0]['seen']
        pu = pl['items'][0]['uid']
        assert ok(u.get(f"/api/mail/{p['id']}/msg?folder=inbox&uid={pu}"))['subject'] in ('İkinci', 'POP iletisi')
        assert ok(u.get(f"/api/mail/{p['id']}/folders"))[0]['unseen'] == 1
        # İşlemler
        ok(u.post(f"/api/mail/{c['id']}/action", json={'folder': 'inbox', 'uids': [1], 'action': 'move', 'target': 'x:Projeler'}))
        assert len(FakeIMAP.servers['mail.firma.com']['Projeler']) == 1
        ok(u.post(f"/api/mail/{g['id']}/action", json={'folder': 'inbox', 'uids': [3], 'action': 'trash'}))
        # Gönderme: özel sunucuda Gönderilenler'e kaydedilir, Gmail'de kaydedilmez; Bcc başlığı gitmez; alıcılar rehbere
        r = ok(u.post(f"/api/mail/{c['id']}/send", data={'to': 'Müşteri <musteri@firma2.com>', 'bcc': 'gizli@firma2.com', 'subject': 'Teklif',
                                                          'html': '<p>Merhaba <b>dünya</b></p><script>x</script>'}))
        assert r['recipients'] == 2 and r['saved_to_sent'] and FakeSMTP.sent[-1][0] == 'mail.firma.com'
        sent_box = next(k for k in FakeIMAP.servers['mail.firma.com'] if 'nderilmi' in k)
        assert len(FakeIMAP.servers['mail.firma.com'][sent_box]) == 1 and b'Bcc' not in FakeIMAP.servers['mail.firma.com'][sent_box][1]['raw']
        assert not ok(u.post(f"/api/mail/{g['id']}/send", data={'to': 'veli@musteri.com', 'subject': 'Yanıt', 'body': 'Tamam'}))['saved_to_sent']
        # Taslak
        ok(u.post(f"/api/mail/{c['id']}/draft", data={'to': 'a@b.com', 'subject': 'Taslak', 'body': 'yarım'}))
        assert len(FakeIMAP.servers['mail.firma.com']['Taslaklar']) == 1
        # Kişi önerisi ve kişisel rehber gizliliği
        sug = ok(u.get('/api/mail/contacts/suggest?q=musteri'))
        assert any(x['email'] == 'musteri@firma2.com' for x in sug) and any(x['email'] == 'ayse@musteri.com' for x in sug), sug
        assert not ok(v.get('/api/mail/contacts/suggest?q=musteri'))
        mine = ok(u.get('/api/my/contacts'))['contacts']
        assert mine and not ok(v.get('/api/my/contacts'))['contacts']
        cid = ok(u.post('/api/my/contacts', json={'name': 'Elle Kişi', 'phone': '0555'}))['id']
        assert v.put(f'/api/my/contacts/{cid}', json={'name': 'X'}).status_code == 404 and v.delete(f'/api/my/contacts/{cid}').status_code == 404
        # Başkasının hesabına erişilemez
        assert v.get(f"/api/mail/{g['id']}/list").status_code == 404 and v.get(f"/api/mail/{g['id']}/folders").status_code == 404
        assert v.delete(f"/api/mail/boxes/{g['id']}").status_code == 404
        # Ayarlar: imza / renk; şifre değiştirme doğrulanır
        ok(u.put(f"/api/mail/boxes/{c['id']}", json={'signature': 'Saygılarımla\nAli', 'color': '#e11d48'}))
        assert u.put(f"/api/mail/boxes/{c['id']}", json={'password': 'yanlis'}).status_code == 400
        # Sosyal medya: RSS yalnız sahibinin akışına
        acc = ok(u.post('/api/social/accounts', json={'provider': 'rss', 'handle': 'blog.example/feed'}))
        assert acc['display_name'] == "Ali'nin Blogu"
        fd = ok(u.get('/api/social/feed'))
        assert [x['text'].split('\n')[0] for x in fd['posts']] == ['Yeni prototip', 'Fuar'] and 'Uçuş testi' in fd['posts'][0]['text']
        assert ok(v.get('/api/social/feed'))['posts'] == [] and v.delete(f"/api/social/accounts/{acc['id']}").status_code == 404
        ok(u.put(f"/api/social/accounts/{acc['id']}", json={'show_in_feed': False}))
        assert ok(u.get('/api/social/feed'))['posts'] == []
        ok(u.put(f"/api/social/accounts/{acc['id']}", json={'show_in_feed': True}))
        ok(u.put('/api/social/feed-on', json={'on': False}))
        assert ok(u.get('/api/social/feed')) == {'posts': [], 'on': False}
        assert u.post('/api/social/accounts', json={'provider': 'instagram', 'handle': 'ali'}).status_code == 400   # anahtar yok
        # Hesap silme
        ok(u.delete(f"/api/mail/boxes/{p['id']}"))
        assert len(ok(u.get('/api/mail/boxes'))['boxes']) == 2
    print('Mail testleri geçti.')


if __name__ == '__main__':
    main()
