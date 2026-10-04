"""Bir kişiye birden fazla e-posta adresi; firma kişilerinde her adresin bir FİRMASI vardır (kişi birden çok firmada olabilir).

Birincil adres kişinin kendi `email` alanında, firması `company_people.company_id`; ek adresler `person_emails`'te
(firma kişilerinde `company_id` ile). kind: 'company' → company_people, 'employee' → employees. Adresler küçük harfle.
Firma ataması e-posta adresi üzerinden yapılır: bir adresi bir firmaya atamak o adresin firmasını değiştirir (kişi aynı kalır).
Bir kişinin firmaları = adreslerinin firmaları (+ adressizse birincil firması). Firmasız kişi: hiçbir adresi firmaya bağlı değil.
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


def _extra_rows(conn, kind, ids):
    """{kişi id: [(adres, firma id)]}"""
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        for ref, e, cid in conn.execute(f'SELECT ref_id, email, company_id FROM person_emails WHERE kind = ? AND ref_id IN '
                                        f'({",".join("?" * len(part))}) ORDER BY id', (kind, *part)):
            out.setdefault(ref, []).append((e, cid))
    return out


def extras(conn, kind, ids):
    """{kişi id: [ek adresler]}"""
    return {k: [e for e, _ in v] for k, v in _extra_rows(conn, kind, ids).items()}


def attach(conn, kind, rows, key='id'):
    """Kayıtlara 'emails' ([birincil, *ekler]) ekler; firma kişilerinde ayrıca 'email_list' ([{email, company_id,
    company_name}]) ve 'companies' ([{id, name}] — kişinin bütün firmaları)."""
    ex = _extra_rows(conn, kind, [r[key] for r in rows])
    names = {}
    if kind == 'company':
        cids = {r.get('company_id') for r in rows} | {c for v in ex.values() for _, c in v}
        cids.discard(None)
        if cids:
            names = dict(conn.execute(f'SELECT id, name FROM companies WHERE id IN ({",".join("?" * len(cids))})', tuple(cids)))
    for r in rows:
        prim = norm(r.get('email'))
        lst = ([(prim, r.get('company_id'))] if prim else []) + [(e, c) for e, c in ex.get(r[key], []) if e != prim]
        r['emails'] = [e for e, _ in lst]
        if kind == 'company':
            r['email_list'] = [{'email': e, 'company_id': c, 'company_name': names.get(c)} for e, c in lst]
            seen, comps = set(), []
            for c in ([r.get('company_id')] if not prim else []) + [c for _, c in lst]:
                if c and c not in seen:
                    seen.add(c)
                    comps.append({'id': c, 'name': names.get(c)})
            r['companies'] = comps
    return rows


def set_all(conn, kind, ref_id, emails, now, company_id=None):
    """Kişinin tüm adreslerini yazar: ilki birincil (kişinin email alanı), kalanı ek adresler. Firma kişilerinde zaten var
    olan adresin firması korunur; yeni ek adres `company_id` (formun açıldığı firma) ile eklenir."""
    emails = parse(emails)
    keep = {e: c for e, c in _extra_rows(conn, kind, [ref_id]).get(ref_id, [])}
    conn.execute(f'UPDATE {TABLES[kind]} SET email = ? WHERE id = ?', (emails[0] if emails else None, ref_id))
    conn.execute('DELETE FROM person_emails WHERE kind = ? AND ref_id = ?', (kind, ref_id))
    conn.executemany('INSERT INTO person_emails (kind, ref_id, email, company_id, created_at) VALUES (?,?,?,?,?)',
                     [(kind, ref_id, e, keep.get(e, company_id) if kind == 'company' else None, now) for e in emails[1:]])
    return emails


def add(conn, kind, ref_id, email, now, company_id=None):
    """Kişiye adres ekler (firma kişisinde adresin firmasıyla): birincil boşsa birincil olur (kişinin firması da o firma),
    değilse ek adres. Adres zaten kişideyse yalnız firması güncellenir."""
    e = parse([email])[0]
    prim = conn.execute(f'SELECT email FROM {TABLES[kind]} WHERE id = ?', (ref_id,)).fetchone()
    if prim is None:
        raise ValueError('Kişi bulunamadı')
    if not norm(prim[0]) or norm(prim[0]) == e:
        if kind == 'company':
            conn.execute('UPDATE company_people SET email = ?, company_id = COALESCE(?, company_id) WHERE id = ?', (e, company_id, ref_id))
        else:
            conn.execute(f'UPDATE {TABLES[kind]} SET email = ? WHERE id = ?', (e, ref_id))
    else:
        conn.execute('''INSERT INTO person_emails (kind, ref_id, email, company_id, created_at) VALUES (?,?,?,?,?)
                        ON CONFLICT(kind, ref_id, email) DO UPDATE SET company_id = COALESCE(excluded.company_id, company_id)''',
                     (kind, ref_id, e, company_id if kind == 'company' else None, now))
    return e


def remove(conn, kind, ref_id, email):
    """Adresi kişiden kaldırır; birincil kaldırılırsa ilk ek adres (firmasıyla) birincil olur."""
    e = norm(email)
    prim = conn.execute(f'SELECT email FROM {TABLES[kind]} WHERE id = ?', (ref_id,)).fetchone()
    if prim and norm(prim[0]) == e:
        nxt = conn.execute('SELECT id, email, company_id FROM person_emails WHERE kind = ? AND ref_id = ? ORDER BY id LIMIT 1',
                           (kind, ref_id)).fetchone()
        if kind == 'company':
            conn.execute('UPDATE company_people SET email = ?, company_id = CASE WHEN ? THEN ? ELSE company_id END WHERE id = ?',
                         (nxt[1] if nxt else None, bool(nxt), nxt[2] if nxt else None, ref_id))
        else:
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


# ---------------- firma kişileri: adres → kişi / firma ----------------
def owner(conn, email):
    """Adresin sahibi firma kişisi: (kişi id, adresin firması, birincil mi) ya da None. Birden çoksa en son eklenen."""
    e = norm(email)
    r = conn.execute('SELECT id, company_id FROM company_people WHERE lower(trim(email)) = ? ORDER BY id DESC LIMIT 1', (e,)).fetchone()
    if r:
        return r[0], r[1], True
    r = conn.execute("SELECT ref_id, company_id FROM person_emails WHERE kind = 'company' AND email = ? ORDER BY id DESC LIMIT 1", (e,)).fetchone()
    return (r[0], r[1], False) if r else None


def set_company(conn, person_id, email, company_id):
    """Adresin firmasını değiştirir (None: firmadan ayır). Birincil adresse kişinin birincil firması da değişir."""
    e = norm(email)
    prim = conn.execute('SELECT email FROM company_people WHERE id = ?', (person_id,)).fetchone()
    if prim and norm(prim[0]) == e:
        conn.execute('UPDATE company_people SET company_id = ? WHERE id = ?', (company_id, person_id))
    else:
        conn.execute("UPDATE person_emails SET company_id = ? WHERE kind = 'company' AND ref_id = ? AND email = ?", (company_id, person_id, e))


def member_sql(alias='p'):
    """Firmanın kişileri: birincil firması ya da adreslerinden birinin firması o firma olanlar (parametre: firma id ×2)."""
    return (f"({alias}.company_id = ? OR {alias}.id IN (SELECT ref_id FROM person_emails WHERE kind = 'company' AND company_id = ?))")
