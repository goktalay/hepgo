"""Bir kişiye birden fazla e-posta adresi (firma kişisi ve İK personeli).

Birincil adres kişinin kendi `email` alanında kalır (mevcut her yer çalışmaya devam eder); ek adresler `person_emails`
tablosunda. kind: 'company' → company_people, 'employee' → employees. Adresler küçük harfle saklanır.
Mail modülü (firma eşleşmesi, CRM › Mailler, firmaya ata) birincil + ek adreslerin hepsini tanır.
"""
import re

TABLES = {'company': 'company_people', 'employee': 'employees'}
_EMAIL = re.compile(r'^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$')
MAX = 10


def norm(e):
    return (e or '').strip().lower()


def parse(values):
    """Liste → geçerli, tekrarsız adresler (sıra korunur). Geçersiz adres varsa ValueError."""
    out = []
    for v in values or []:
        e = norm(v)
        if not e:
            continue
        if not _EMAIL.match(e) or len(e) > 120:
            raise ValueError(f'Geçersiz e-posta adresi: {v}')
        if e not in out:
            out.append(e)
    if len(out) > MAX:
        raise ValueError(f'Bir kişiye en çok {MAX} e-posta adresi eklenebilir')
    return out


def extras(conn, kind, ids):
    """{kişi id: [ek adresler]}"""
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        for ref, e in conn.execute(f'SELECT ref_id, email FROM person_emails WHERE kind = ? AND ref_id IN ({",".join("?" * len(part))}) '
                                   'ORDER BY id', (kind, *part)):
            out.setdefault(ref, []).append(e)
    return out


def attach(conn, kind, rows, key='id'):
    """Kayıtlara 'emails' alanı ekler: [birincil, *ekler]."""
    ex = extras(conn, kind, [r[key] for r in rows])
    for r in rows:
        prim = norm(r.get('email'))
        r['emails'] = ([prim] if prim else []) + [e for e in ex.get(r[key], []) if e != prim]
    return rows


def set_all(conn, kind, ref_id, emails, now):
    """Kişinin tüm adreslerini yazar: ilki birincil (kişinin email alanı), kalanı ek adresler."""
    emails = parse(emails)
    conn.execute(f'UPDATE {TABLES[kind]} SET email = ? WHERE id = ?', (emails[0] if emails else None, ref_id))
    conn.execute('DELETE FROM person_emails WHERE kind = ? AND ref_id = ?', (kind, ref_id))
    conn.executemany('INSERT INTO person_emails (kind, ref_id, email, created_at) VALUES (?,?,?,?)',
                     [(kind, ref_id, e, now) for e in emails[1:]])
    return emails


def add(conn, kind, ref_id, email, now):
    """Kişiye adres ekler: birincil boşsa birincil olur, değilse ek adres (zaten varsa değişmez)."""
    e = parse([email])[0]
    prim = conn.execute(f'SELECT email FROM {TABLES[kind]} WHERE id = ?', (ref_id,)).fetchone()
    if prim is None:
        raise ValueError('Kişi bulunamadı')
    if not norm(prim[0]):
        conn.execute(f'UPDATE {TABLES[kind]} SET email = ? WHERE id = ?', (e, ref_id))
    elif norm(prim[0]) != e:
        conn.execute('INSERT OR IGNORE INTO person_emails (kind, ref_id, email, created_at) VALUES (?,?,?,?)', (kind, ref_id, e, now))
    return e


def remove(conn, kind, ref_id, email):
    """Adresi kişiden kaldırır; birincil kaldırılırsa ilk ek adres birincil olur."""
    e = norm(email)
    prim = conn.execute(f'SELECT email FROM {TABLES[kind]} WHERE id = ?', (ref_id,)).fetchone()
    if prim and norm(prim[0]) == e:
        nxt = conn.execute('SELECT id, email FROM person_emails WHERE kind = ? AND ref_id = ? ORDER BY id LIMIT 1', (kind, ref_id)).fetchone()
        conn.execute(f'UPDATE {TABLES[kind]} SET email = ? WHERE id = ?', (nxt[1] if nxt else None, ref_id))
        if nxt:
            conn.execute('DELETE FROM person_emails WHERE id = ?', (nxt[0],))
    else:
        conn.execute('DELETE FROM person_emails WHERE kind = ? AND ref_id = ? AND email = ?', (kind, ref_id, e))


def drop(conn, kind, ids):
    """Silinen kişilerin ek adresleri."""
    conn.executemany('DELETE FROM person_emails WHERE kind = ? AND ref_id = ?', [(kind, i) for i in ids])


def has(conn, kind, ref_id, email):
    e = norm(email)
    prim = conn.execute(f'SELECT email FROM {TABLES[kind]} WHERE id = ?', (ref_id,)).fetchone()
    return bool(prim and norm(prim[0]) == e) or conn.execute(
        'SELECT 1 FROM person_emails WHERE kind = ? AND ref_id = ? AND email = ?', (kind, ref_id, e)).fetchone() is not None
