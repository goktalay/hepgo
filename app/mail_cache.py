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
import re
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


# ---------------- Kişiler / Cariler görünümü: kayıtlı mailler adrese göre ----------------
def addr_stats(conn, box_ids, own=()):
    """Kayıtlı maillerdeki her katılımcı adresi → [ileti sayısı, son tarih, mailde görünen ad]. Kendi adreslerimiz hariç.
    Aynı ileti birden çok klasörde (ör. Gmail Tüm Postalar) olsa da bir kez sayılır."""
    own = {e.lower() for e in own}
    out, seen = {}, set()
    if not box_ids:
        return out
    for addrs, date, fe, fn, subj in conn.execute(
            f"""SELECT addrs, date, json_extract(summary, '$.from.email'), json_extract(summary, '$.from.name'),
                       json_extract(summary, '$.subject') FROM mail_cache WHERE box_id IN ({",".join("?" * len(box_ids))})""", box_ids):
        k = (date, subj, fe)
        if k in seen:
            continue
        seen.add(k)
        fe = (fe or '').lower()
        for e in (addrs or '').split():
            if e in own or '@' not in e:
                continue
            st = out.setdefault(e, [0, '', None])
            st[0] += 1
            if (date or '') > st[1]:
                st[1] = date or ''
            if e == fe and fn and fn.lower() != fe and '@' not in fn:
                st[2] = fn
    return out


def mails_for(conn, box_ids, emails, limit=300):
    """Verilen adreslerden birinin katıldığı iletiler (yeni → eski); her iletiye eşleşen adres ('match', verilen sırayla ilki).
    Aynı ileti birden çok klasördeyse bir kez (gelen / gönderilen klasörü tercih edilir)."""
    emails = [e.lower() for e in emails if e and '@' in e][:200]
    if not box_ids or not emails:
        return []
    rows = conn.execute(f"""SELECT box_id, folder, uid, summary, seen, starred, addrs FROM mail_cache
                            WHERE box_id IN ({",".join("?" * len(box_ids))}) AND ({" OR ".join(["addrs LIKE ?"] * len(emails))})
                            ORDER BY date DESC LIMIT ?""", (*box_ids, *[f'% {e} %' for e in emails], limit * 2)).fetchall()
    rank = {'inbox': 0, 'sent': 1}
    best = {}
    for box_id, folder, uid, summary, seen, starred, addrs in rows:
        d = json.loads(summary)
        k = (d.get('date'), d.get('subject'), (d.get('from') or {}).get('email'))
        have = best.get(k)
        if have and rank.get(have['folder'], 5) <= rank.get(folder, 5):
            continue
        parts = set((addrs or '').split())
        d.update(box_id=box_id, folder=folder, uid=uid, seen=bool(seen), starred=bool(starred),
                 match=next((e for e in emails if e in parts), emails[0]))
        best[k] = d
    return sorted(best.values(), key=lambda d: d.get('date') or '', reverse=True)[:limit]


# ---------------- Arka plan eşitlemesi ----------------
def sync_box(box):
    """Gelen kutusu + gönderilenler: klasörün tamamı önbelleğe (yalnız eksikler indirilir; bayraklar tazelenir)."""
    for folder in SYNC_FOLDERS:
        try:
            full_sync(box, folder)
        except Exception:   # noqa: BLE001 — klasör yok / hesap hatası: diğer klasöre geç
            pass


# ---------------- Tam eşitleme: klasördeki bütün iletiler önbelleğe (sıralama / filtre kayıtlı mailler arasında) ----------------
FULL_MAX = 20000      # klasör başına en çok bu kadar ileti (en yeniden geriye)
FULL_BATCH = 200      # sunucudan tek seferde alınan özet sayısı
COMPLETE_TTL = 3 * 3600   # tamamlanan eşitleme bu süre "tam" sayılır (arka plan eşitlemesi yeniler)
_progress = {}        # (hesap, klasör) → {total, done, running, error, finished}
_plock = threading.Lock()


def progress(box_id, folder):
    with _plock:
        return dict(_progress.get((box_id, folder)) or {'total': 0, 'done': 0, 'running': False, 'finished': None})


def complete(box_id, folder):
    p = progress(box_id, folder)
    return bool(p.get('finished')) and not p.get('error') and time.time() - p['finished'] < COMPLETE_TTL


def _set(box_id, folder, **kw):
    with _plock:
        _progress.setdefault((box_id, folder), {'total': 0, 'done': 0, 'running': False, 'finished': None}).update(kw)


def full_sync(box, folder):
    """Klasörün tamamını önbelleğe alır: sunucudaki UID listesi + bayraklar; önbellekte olmayanlar FULL_BATCH'lik paketlerle
    (en yeniden geriye), sunucuda artık olmayanlar önbellekten düşer. İlerleme progress() ile izlenir."""
    from . import mail
    key = (box['id'], folder)
    with _plock:
        if (_progress.get(key) or {}).get('running'):
            return
        _progress[key] = {'total': 0, 'done': 0, 'running': True, 'finished': None, 'error': None}
    try:
        flags, uv = mail.folder_index(box, folder)
        with db.connect() as conn:
            if uv is not None and state(conn, box['id'], folder, uv) != 'ok':
                set_state(conn, box['id'], folder, uv)
                conn.commit()
            have = {u for (u,) in conn.execute('SELECT uid FROM mail_cache WHERE box_id = ? AND folder = ?', (box['id'], folder))}
        want = sorted(flags, reverse=True)[:FULL_MAX]
        gone = [u for u in have if u not in flags]
        if gone:
            submit(forget, box['id'], folder, gone)
        submit(set_flags, box['id'], folder, {u: flags[u] for u in want if u in have})
        missing = [u for u in want if u not in have]
        _set(*key, total=len(want), done=len(want) - len(missing))
        for i in range(0, len(missing), FULL_BATCH):
            part = missing[i:i + FULL_BATCH]
            mail.fetch_into_cache(box, folder, part)
            _set(*key, done=len(want) - len(missing) + i + len(part))
        flush()
        _set(*key, running=False, finished=time.time(), done=len(want))
    except Exception as e:   # noqa: BLE001 — hata ilerlemede görünür; liste IMAP'tan devam eder
        _set(*key, running=False, error=str(e)[:200])
        raise


def start_full_sync(box, folder):
    """Arka planda tam eşitleme (zaten sürüyorsa yeni başlatmaz)."""
    if progress(box['id'], folder).get('running'):
        return
    threading.Thread(target=lambda: _quiet(full_sync, box, folder), daemon=True, name=f'mail-full-{box["id"]}').start()


def _quiet(fn, *a):
    try:
        fn(*a)
    except Exception:   # noqa: BLE001
        pass


_TR = str.maketrans({'ç': 'c~', 'ğ': 'g~', 'ı': 'h~', 'i': 'i', 'ö': 'o~', 'ş': 's~', 'ü': 'u~'})
_PREFIX = re.compile(r'^\s*((re|fw|fwd|ynt|ilt|aw|wg|tr)\s*(\[\d+\])?\s*:\s*)+', re.I)


def _tr_key(v):
    """Türkçe alfabe sırası (ç c'den, ı h'den sonra…); boş değerler sonda."""
    v = (v or '').strip().strip('"\'').replace('I', 'ı').replace('İ', 'i').lower()
    return v.translate(_TR) if v else '\uffff'


def list_cached(conn, box_id, folder, filt, sort, start, limit):
    """Kayıtlı (önbellekteki) iletiler arasında filtre + sıralama → list_messages ile aynı biçim."""
    where = ['box_id = ?', 'folder = ?']
    if filt == 'unread':
        where.append('seen = 0')
    elif filt == 'starred':
        where.append('starred = 1')
    elif filt == 'attach':
        where.append("json_extract(summary, '$.attach') = 1")
    rows = conn.execute(f"""SELECT uid, date, json_extract(summary, '$.from.name'), json_extract(summary, '$.from.email'),
                                   json_extract(summary, '$.subject'), json_extract(summary, '$.size')
                            FROM mail_cache WHERE {' AND '.join(where)}""", (box_id, folder)).fetchall()
    rows.sort(key=lambda r: (r[1] or '', r[0]), reverse=sort != 'date_asc')   # tarih (eşitse UID); diğer sıralamalarda ikincil
    if sort == 'from':
        rows.sort(key=lambda r: _tr_key(r[2] if r[2] and r[2] != r[3] else r[3]))
    elif sort == 'subject':
        rows.sort(key=lambda r: _tr_key(_PREFIX.sub('', r[4] or '')))
    elif sort == 'size':
        rows.sort(key=lambda r: -(r[5] or 0))
    chunk = [r[0] for r in rows[start:start + limit]]
    got = get_many(conn, box_id, folder, chunk)
    total = len(rows)
    return {'items': [got[u] for u in chunk if u in got], 'total': total, 'page': start // max(1, limit),
            'pages': max(1, -(-total // limit)), 'cached': True}


CONTACTS_INTERVAL = 6 * 3600   # Google / Microsoft takvim ve kişileri bu aralıkla kendiliğinden eşitlenir


def _contacts_due(b):
    if b.get('auth_type') not in ('google', 'microsoft') or not (b.get('sync_contacts') or b.get('sync_calendar')):
        return
    try:
        from datetime import datetime
        last = datetime.fromisoformat(b['last_sync']).timestamp() if b.get('last_sync') else 0
    except ValueError:
        last = 0
    if time.time() - last < CONTACTS_INTERVAL:
        return
    from . import personal
    try:
        with db.connect() as conn:
            personal.sync_box(conn, b)
    except Exception as e:   # noqa: BLE001 — erişim jetonu vb.: hata hesapta görünsün
        try:
            with db.connect() as conn:
                conn.execute('UPDATE mail_boxes SET sync_error = ?, last_sync = ? WHERE id = ?', (str(e)[:500], db.now(), b['id']))
                conn.commit()
        except Exception:   # noqa: BLE001
            pass


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
                _contacts_due(b)
        except Exception:   # noqa: BLE001
            pass
        time.sleep(SYNC_INTERVAL)


_started = False


def start():
    global _started
    if not _started and config.PRINTER_POLL_ENABLED:   # testlerde arka plan eşitlemesi yok
        _started = True
        threading.Thread(target=_loop, daemon=True, name='mail-cache-sync').start()
