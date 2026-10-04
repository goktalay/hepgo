"""Mail önbelleği: IMAP iletilerinin özeti (liste satırı), okunan ileti ve katılımcı adresleri veritabanında tutulur.

- Liste: sunucudan yalnız UID listesi + bayraklar (okundu / yıldız) istenir; başlık ve önizleme yalnız önbellekte OLMAYAN
  iletiler için indirilir (önceden her açılışta baştan çekiliyordu).
- Okuma: bir kez açılan ileti önbellekten anında gelir (2 MB'tan büyük işlenmiş ileti saklanmaz).
- Tutarlılık: klasörün UIDVALIDITY'si değişirse o klasörün önbelleği silinir; silinen / taşınan iletiler önbellekten düşer.
- Katılımcılar (kimden / kime / bilgi) `addrs` alanında: CRM › firma › Mailler bu alandan kullanıcının KENDİ hesaplarında arar.
- Arka planda (EŞİTLEME_ARALIĞI) gelen kutusu ve gönderilenlerin başlıkları önbelleğe alınır (CRM'de kaydırılmamış iletiler de görünsün).
POP3 hesapları önbelleğe alınmaz (kendi kısa süreli önbellekleri var).

Yazmalar (submit) TEK arka plan yazıcısında sırayla yapılır: istek içinde yazılsaydı, isteğin kendi bağlantısındaki açık
yazma işlemine takılıp beklerdi ("database is locked"). İstekler yalnız okur (WAL: okuma kilide takılmaz).
"""
import json
import queue
import sqlite3
import threading
import time

from . import config, db

MAX_BODY = 2_000_000
SYNC_INTERVAL = 600          # sn: arka plan başlık eşitlemesi
SYNC_FOLDERS = ('inbox', 'sent')
SYNC_MAX = 1000              # klasör başına en çok bu kadar yeni ileti önbelleğe alınır (en yeniden geriye)


def addr_text(emails):
    """Arama için katılımcı listesi: ' a@x.com b@y.com ' (küçük harf, boşlukla çevrili)."""
    return ' ' + ' '.join(sorted({(e or '').strip().lower() for e in emails if e and '@' in e})) + ' '


_q = queue.Queue()
_writer = None
_writer_lock = threading.Lock()


def _write_loop():
    while True:
        fn, args = _q.get()
        try:
            for attempt in range(20):   # kilitliyse bekleyip yeniden dene (en çok ~1 dk)
                try:
                    with db.connect() as conn:
                        fn(conn, *args)
                        conn.commit()
                    break
                except sqlite3.OperationalError as e:
                    if 'locked' not in str(e):
                        break
                    time.sleep(min(3, 0.2 * (attempt + 1)))
        except Exception:   # noqa: BLE001 — önbellek yazılamasa da mail çalışır
            pass
        finally:
            _q.task_done()


def submit(fn, *args):
    """Önbelleğe yazma işini arka plan yazıcısına sıraya koyar (FIFO: sıra korunur)."""
    global _writer
    if _writer is None:
        with _writer_lock:
            if _writer is None:
                _writer = threading.Thread(target=_write_loop, daemon=True, name='mail-cache-writer')
                _writer.start()
    _q.put((fn, args))


def flush():
    """Sıradaki yazmalar bitene dek bekler (testler)."""
    _q.join()


def state(conn, box_id, folder, uv):
    """'ok' (önbellek geçerli) | 'new' (henüz kayıt yok) | 'changed' (UIDVALIDITY değişmiş: önbellek geçersiz)."""
    old = uidvalidity(conn, box_id, folder)
    return 'new' if old is None else ('ok' if old == uv else 'changed')


def uidvalidity(conn, box_id, folder):
    r = conn.execute('SELECT uidvalidity FROM mail_cache_state WHERE box_id = ? AND folder = ?', (box_id, folder)).fetchone()
    return r[0] if r else None


def set_state(conn, box_id, folder, uv):
    """Klasörün UIDVALIDITY'si değiştiyse eski önbellek geçersizdir (UID'ler yeniden numaralanmış)."""
    old = uidvalidity(conn, box_id, folder)
    if old == uv:
        return
    if old is not None:
        conn.execute('DELETE FROM mail_cache WHERE box_id = ? AND folder = ?', (box_id, folder))
    conn.execute('INSERT OR REPLACE INTO mail_cache_state (box_id, folder, uidvalidity) VALUES (?,?,?)', (box_id, folder, uv))


def get_many(conn, box_id, folder, uids):
    out = {}
    for i in range(0, len(uids), 400):
        part = uids[i:i + 400]
        for uid, summary, seen, starred in conn.execute(
                f'SELECT uid, summary, seen, starred FROM mail_cache WHERE box_id = ? AND folder = ? AND uid IN ({",".join("?" * len(part))})',
                (box_id, folder, *part)):
            d = json.loads(summary)
            d.update(seen=bool(seen), starred=bool(starred))
            out[uid] = d
    return out


def put_many(conn, box_id, folder, items):
    """items: [(özet sözlüğü, katılımcı e-postaları)]"""
    now = db.now()
    conn.executemany('''INSERT INTO mail_cache (box_id, folder, uid, date, seen, starred, addrs, summary, cached_at) VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(box_id, folder, uid) DO UPDATE SET date = excluded.date, seen = excluded.seen,
                        starred = excluded.starred, addrs = excluded.addrs, summary = excluded.summary''',
                     [(box_id, folder, s['uid'], s.get('date'), int(bool(s.get('seen'))), int(bool(s.get('starred'))),
                       addr_text(emails), json.dumps(s, ensure_ascii=False), now) for s, emails in items])


def set_flags(conn, box_id, folder, flags):
    """flags: {uid: (okundu, yıldızlı)}"""
    conn.executemany('UPDATE mail_cache SET seen = ?, starred = ? WHERE box_id = ? AND folder = ? AND uid = ?',
                     [(int(s), int(st), box_id, folder, u) for u, (s, st) in flags.items()])


def prune(conn, box_id, folder, lo, hi, keep):
    """[lo, hi] UID aralığında sunucuda artık olmayan (silinen / taşınan) iletiler önbellekten düşer."""
    gone = [u for (u,) in conn.execute('SELECT uid FROM mail_cache WHERE box_id = ? AND folder = ? AND uid BETWEEN ? AND ?',
                                       (box_id, folder, lo, hi)) if u not in keep]
    forget(conn, box_id, folder, gone)


def forget(conn, box_id, folder, uids):
    conn.executemany('DELETE FROM mail_cache WHERE box_id = ? AND folder = ? AND uid = ?', [(box_id, folder, int(u)) for u in uids])


def get_body(conn, box_id, folder, uid):
    r = conn.execute('SELECT body, seen, starred FROM mail_cache WHERE box_id = ? AND folder = ? AND uid = ? AND body IS NOT NULL',
                     (box_id, folder, uid)).fetchone()
    if not r:
        return None
    d = json.loads(r[0])
    d['starred'] = bool(r[2])
    return d, bool(r[1])


def put_body(conn, box_id, folder, uid, rendered, emails):
    body = json.dumps(rendered, ensure_ascii=False)
    if len(body) > MAX_BODY:
        return
    s = {k: rendered.get(k) for k in ('uid', 'subject', 'date', 'from', 'starred')}
    s.setdefault('to', (rendered.get('to') or [{}])[0] if rendered.get('to') else {'name': '', 'email': ''})
    conn.execute('''INSERT INTO mail_cache (box_id, folder, uid, date, seen, starred, addrs, summary, body, cached_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(box_id, folder, uid) DO UPDATE SET body = excluded.body, seen = 1, addrs = excluded.addrs''',
                 (box_id, folder, uid, rendered.get('date'), 1, int(bool(rendered.get('starred'))), addr_text(emails),
                  json.dumps(s, ensure_ascii=False), body, db.now()))


# ---------------- CRM: firmanın mailleri (yalnız kullanıcının kendi hesaplarında) ----------------
def company_mails(conn, box_ids, emails, domains, limit=50, offset=0):
    """Katılımcıları arasında firmanın kişilerinden biri ya da firmanın alan adından bir adres olan iletiler (yeni → eski)."""
    if not box_ids or not (emails or domains):
        return []
    conds = ['addrs LIKE ?'] * len(emails) + ['addrs LIKE ?'] * len(domains)
    args = [f'% {e} %' for e in emails] + [f'%@{d} %' for d in domains]
    rows = conn.execute(f'''SELECT box_id, folder, uid, summary, seen, starred FROM mail_cache
                            WHERE box_id IN ({",".join("?" * len(box_ids))}) AND ({" OR ".join(conds)})
                            ORDER BY date DESC LIMIT ? OFFSET ?''', (*box_ids, *args, limit, offset)).fetchall()
    out = []
    for box_id, folder, uid, summary, seen, starred in rows:
        d = json.loads(summary)
        d.update(box_id=box_id, folder=folder, uid=uid, seen=bool(seen), starred=bool(starred))
        out.append(d)
    return out


# ---------------- Arka plan eşitlemesi ----------------
def sync_box(box):
    """Gelen kutusu + gönderilenler: en yeniden geriye, önbellekte olmayan başlıklar indirilir (sayfa tamamen önbellekteyse durur)."""
    from . import mail
    for folder in SYNC_FOLDERS:
        offset = 0
        while offset < SYNC_MAX:
            try:
                r = mail.list_messages(box, folder, offset=offset, cache_stats=True)
            except Exception:   # noqa: BLE001 — klasör yok / hesap hatası: diğer klasöre geç
                break
            if not r['items'] or r.get('fetched', 0) == 0:
                break
            offset += len(r['items'])
            time.sleep(0.5)


def _loop():
    time.sleep(90)
    while True:
        try:
            with db.connect() as conn:
                boxes = db.rows(conn.execute('SELECT * FROM mail_boxes'))
            from . import mail
            for b in boxes:
                if not mail.settings(b)['is_pop']:
                    try:
                        sync_box(b)
                    except Exception:   # noqa: BLE001
                        pass
        except Exception:   # noqa: BLE001
            pass
        time.sleep(SYNC_INTERVAL)


_started = False


def start():
    global _started
    if not _started and config.PRINTER_POLL_ENABLED:   # testlerde arka plan eşitlemesi yok
        _started = True
        threading.Thread(target=_loop, daemon=True, name='mail-cache-sync').start()
