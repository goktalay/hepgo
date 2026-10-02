"""Mail ekleri → Evrak Yönetimi. Gelen kutusuna yeni düşen e-postaların ekleri, kullanıcının "Yalnızca ben" görünürlüğünde
evrakı olarak kaydedilir ve OCR'a alınır (yönetici dahil kimse göremez). Arka planda 2 dakikada bir, yalnızca Evrak
modülüne erişimi olan ve "otomatik kaydet" açık hesaplar taranır; hesap ilk bağlandığında eski postalar aktarılmaz
(okuma ekranındaki "Ekleri Evraklara Kaydet" ile tek tek aktarılabilir). Aynı ek iki kez aktarılmaz.
"""
import re
import secrets
import threading
import time
from pathlib import Path

from . import auth, config, db, document_ocr, mail
from .files import KINDS, MAX_BYTES

INTERVAL = 120
ALLOWED = KINDS['documents']


def _save(conn, user_id, msg, meta, folder_note):
    """msg: email.message; dönen: yeni evrak kimlikleri."""
    mid = (msg['Message-ID'] or f'{meta.get("uid")}@{folder_note}').strip()[:300]
    subject = mail._dec(msg['Subject']) or '(konu yok)'
    frm = mail._addr(msg['From'])
    try:
        date = mail.parsedate_to_datetime(msg['Date']).astimezone().date().isoformat() if msg['Date'] else None
    except Exception:
        date = None
    ids = []
    for part, info in mail._attachments(msg):
        if info['inline']:
            continue
        name = Path(info['name']).name[:200] or 'ek'
        ext = Path(name).suffix.lower()
        if ext not in ALLOWED:
            continue
        if conn.execute('SELECT 1 FROM mail_imports WHERE user_id = ? AND message_id = ? AND att_name = ?', (user_id, mid, name)).fetchone():
            continue
        data = part.get_payload(decode=True) or b''
        if not data or len(data) > MAX_BYTES * 4:
            continue
        folder = config.UPLOAD_DIR / 'documents'
        folder.mkdir(parents=True, exist_ok=True)
        fname = secrets.token_hex(12) + ext
        (folder / fname).write_bytes(data)
        cur = conn.execute(
            '''INSERT INTO documents (title, kind, file, file_name, size, doc_date, note, visibility, uploaded_by, uploaded_at)
               VALUES (?,?,?,?,?,?,?,'PRIVATE',?,?)''',
            (Path(name).stem[:300], document_ocr.kind_of(name), f'documents/{fname}', name, len(data), date,
             f'E-posta eki · {subject} · {frm["name"]} <{frm["email"]}>'[:1000], user_id, db.now()))
        doc_id = cur.lastrowid
        conn.execute('INSERT INTO mail_imports (user_id, message_id, att_name, document_id, at) VALUES (?,?,?,?,?)',
                     (user_id, mid, name, doc_id, db.now()))
        document_ocr.index(conn, doc_id)
        db.audit(conn, user_id, 'Mail ekini evraklara kaydetti', 'document', doc_id, name)
        ids.append(doc_id)
    return ids


def _start_ocr(ids):
    for i in ids:
        document_ocr.start(i)


def import_message(conn, user, account, folder, uid):
    """Tek e-postanın eklerini aktarır (okuma ekranındaki düğme)."""
    c = mail.conn_for(account)
    msg = mail._run(c, lambda m: mail._fetch_raw(c, m, folder, uid)[0])
    ids = _save(conn, user['id'], msg, {'uid': uid}, folder)
    conn.commit()
    _start_ocr(ids)
    return ids


def sync_account(conn, a):
    """Gelen kutusunda son taranan UID'den sonraki postaların eklerini aktarır."""
    c = mail.conn_for(a)

    def scan(m):
        m.select('INBOX', readonly=True)
        c.selected = ('INBOX', True)
        typ, d = m.response('UIDVALIDITY')
        validity = (d[0].decode() if d and d[0] else None)
        typ, d = m.uid('SEARCH', None, 'ALL')
        uids = sorted(int(x) for x in (d[0] or b'').split()) if typ == 'OK' else []
        top = uids[-1] if uids else 0
        if a['last_uid'] is None or a['uid_validity'] != validity:   # ilk tarama: geçmiş aktarılmaz
            return validity, top, []
        new = [u for u in uids if u > a['last_uid']][:50]
        found = []
        if new:
            typ, data = m.uid('FETCH', ','.join(map(str, new)), '(UID BODY.PEEK[HEADER.FIELDS (CONTENT-TYPE)])')
            multi = [int(re.search(r'UID (\d+)', p[0].decode()).group(1)) for p in data or []
                     if isinstance(p, tuple) and b'multipart/mixed' in p[1].lower()]
            for u in multi:
                found.append(mail._fetch_raw(c, m, 'inbox', u)[0])
        return validity, (new[-1] if new else top), found
    validity, last, msgs = mail._run(c, scan)
    ids = []
    for msg in msgs:
        ids += _save(conn, a['user_id'], msg, {}, 'inbox')
    conn.execute('UPDATE mail_accounts SET last_uid = ?, uid_validity = ? WHERE user_id = ?', (last, validity, a['user_id']))
    conn.commit()
    _start_ocr(ids)
    return len(ids)


def _loop():
    time.sleep(30)
    while True:
        try:
            with db.connect() as conn:
                accounts = db.rows(conn.execute('SELECT * FROM mail_accounts WHERE auto_import = 1'))
                for a in accounts:
                    roles = auth.user_roles(conn, a['user_id'])
                    if 'documents' not in auth.allowed_modules(roles):
                        continue
                    try:
                        sync_account(conn, a)
                        conn.execute('UPDATE mail_accounts SET last_error = NULL WHERE user_id = ?', (a['user_id'],))
                    except Exception as e:   # bir hesabın hatası diğerlerini durdurmasın
                        conn.execute('UPDATE mail_accounts SET last_error = ? WHERE user_id = ?', (str(e)[:300], a['user_id']))
                    conn.commit()
        except Exception:
            pass
        time.sleep(INTERVAL)


_started = False


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name='mail-import').start()
