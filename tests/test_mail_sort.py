"""Mail listesi: filtre (okunmamış / yıldızlı / ekli) ve sıralama (tarih, gönderen, konu, boyut); klasörün tamamı önbelleğe
alınınca (tam eşitleme, ilerleme) sıralama kayıtlı mailler arasında yapılır."""
import os
import shutil
import tempfile

os.environ['CAYMAZ_DATA_DIR'] = tempfile.mkdtemp(prefix='hepgo-sort-')
os.environ.setdefault('CAYMAZ_PRINTER_POLL', '0')

from tests.test_mail import GOOD, SEEN, FakeIMAP, make  # noqa: E402
from app import db, mail, mail_cache  # noqa: E402
from app.cameras import encrypt  # noqa: E402

mail.imaplib.IMAP4_SSL = FakeIMAP


def run():
    db.init()
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id, username, password_hash, full_name, active, created_at) VALUES (1, 'u@t', 'x', 'U', 1, ?)", (db.now(),))
        bid = conn.execute('''INSERT INTO mail_boxes (user_id, email, provider, auth_type, secret, imap_host, imap_port, smtp_host, smtp_port, created_at)
                              VALUES (1, 'ali@firma.com', 'imap', 'password', ?, 'imap.firma.com', 993, 'smtp.firma.com', 465, ?)''',
                           (encrypt(GOOD), db.now())).lastrowid
        conn.commit()
        box = db.row(conn.execute('SELECT * FROM mail_boxes WHERE id = ?', (bid,)))
    FakeIMAP.servers['imap.firma.com'] = {'INBOX': {
        1: {'raw': make(1, 'Zeytin siparişi', 'Çetin <c@x.com>'), 'flags': {SEEN}},
        2: {'raw': make(2, 'Re: Armut', 'Ahmet <a@x.com>', att=True), 'flags': set()},
        3: {'raw': make(3, 'Bal', 'ılgaz <i@x.com>'), 'flags': {SEEN, '\\Flagged'}},
        4: {'raw': make(4, 'Ceviz', 'Burak <b@x.com>'), 'flags': {SEEN}},
    }}
    subj = lambda r: [m['subject'] for m in r['items']]  # noqa: E731

    # eşitleme yokken sıralama sunucudan (Gmail dışı, SORT desteği yok → başlıklarla)
    r = mail.list_messages(box, 'inbox', sort='from')
    assert not r.get('cached') and [m['from']['name'] for m in r['items']] == ['Ahmet', 'Burak', 'Çetin', 'ılgaz'], r['items']
    r = mail.list_messages(box, 'inbox', filt='unread')
    assert subj(r) == ['Re: Armut'], subj(r)

    # tam eşitleme: ilerleme + önbellek
    assert not mail_cache.complete(bid, 'inbox')
    mail_cache.full_sync(box, 'inbox')
    p = mail_cache.progress(bid, 'inbox')
    assert p['total'] == 4 and p['done'] == 4 and not p['running'] and mail_cache.complete(bid, 'inbox'), p

    # kayıtlı mailler arasında
    r = mail.list_messages(box, 'inbox', sort='subject')
    assert r.get('cached') and subj(r) == ['Re: Armut', 'Bal', 'Ceviz', 'Zeytin siparişi'], subj(r)   # "Re:" yok sayılır
    r = mail.list_messages(box, 'inbox', sort='from')
    assert [m['from']['name'] for m in r['items']] == ['Ahmet', 'Burak', 'Çetin', 'ılgaz'], r['items']   # Türkçe alfabe
    assert subj(mail.list_messages(box, 'inbox', sort='date_asc')) == ['Zeytin siparişi', 'Re: Armut', 'Bal', 'Ceviz']
    assert subj(mail.list_messages(box, 'inbox', filt='starred')) == ['Bal']
    assert subj(mail.list_messages(box, 'inbox', filt='attach')) == ['Re: Armut']
    r = mail.list_messages(box, 'inbox', filt='unread', sort='date')
    assert r.get('cached') and subj(r) == ['Re: Armut']
    big = mail.list_messages(box, 'inbox', sort='size')['items']
    assert big[0]['subject'] == 'Re: Armut', [m['subject'] for m in big]   # ekli ileti en büyük
    r = mail.list_messages(box, 'inbox', sort='subject', offset=2, limit=2)
    assert subj(r) == ['Ceviz', 'Zeytin siparişi'] and r['total'] == 4

    # sunucuda silinen ileti ve değişen bayrak sonraki eşitlemede önbelleğe yansır
    srv = FakeIMAP.servers['imap.firma.com']['INBOX']
    del srv[4]
    srv[1]['flags'].discard(SEEN)
    srv[5] = {'raw': make(5, 'Elma', 'Deniz <d@x.com>'), 'flags': set()}
    mail_cache.full_sync(box, 'inbox')
    assert subj(mail.list_messages(box, 'inbox', sort='subject')) == ['Re: Armut', 'Bal', 'Elma', 'Zeytin siparişi']
    assert sorted(subj(mail.list_messages(box, 'inbox', filt='unread'))) == ['Elma', 'Re: Armut', 'Zeytin siparişi']
    print('Mail sıralama / filtre / tam eşitleme testleri geçti.')


if __name__ == '__main__':
    try:
        run()
    finally:
        shutil.rmtree(os.environ['CAYMAZ_DATA_DIR'], ignore_errors=True)
