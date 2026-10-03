"""Finans hareketlerini ilgili kayda bağlama: belge no → fatura, açıklamadaki isim / elle bağlantı → personel.

- Fatura: fin_txns.doc_no ve fin_ledger.doc_no, faturanın numarasıyla (invoices.number / material_docs.number) eşleşir
  (Mikro cari hareketinin belge no'su e-fatura numarasıdır).
- Personel: kasa / banka / cari hareket açıklamasında ad soyad geçiyorsa (ör. "OCAK 2026 MAAŞ AD SOYAD … Havale") otomatik;
  ayrıca personel bir cariye, kasa / banka hesabına ya da muhasebe hesabına elle bağlanabilir (employee_fin_links).
"""
from . import db
from .fleet import fold, squash

LINK_KINDS = {'company': 'Cari (firma)', 'account': 'Kasa / banka hesabı', 'ledger': 'Muhasebe hesabı'}


def person_keys(first, last):
    """Ad soyad eşleşme anahtarları (boşluksuz, Türkçe harf sade): 'ad soyad' ve 'soyad ad'. Çok kısa adlar yanlış eşleşmesin diye alınmaz."""
    a, b = squash(first), squash(last)
    if not a or not b:
        return set()
    return {k for k in (a + b, b + a) if len(k) >= 6}


def employees_index(conn):
    return [(r['id'], f"{r['first_name']} {r['last_name']}", person_keys(r['first_name'], r['last_name']))
            for r in db.rows(conn.execute("SELECT id, first_name, last_name FROM employees WHERE status IN ('AKTIF','AYRILDI')"))]


def match_person(text, idx):
    s = squash(text)
    if not s:
        return None
    for eid, name, keys in idx:
        if any(k in s for k in keys):
            return {'id': eid, 'name': name}
    return None


def invoice_map(conn, docs):
    """{belge no: {id, kind, source}} — satış/alış faturaları (invoices) ve Satın Alma belgeleri (material_docs)."""
    docs = sorted({d for d in docs if d})
    out = {}
    for i in range(0, len(docs), 400):
        part = docs[i:i + 400]
        ph = ','.join('?' * len(part))
        for r in conn.execute(f'SELECT id, number, kind FROM invoices WHERE number IN ({ph})', part):
            out.setdefault(r['number'], {'id': r['id'], 'kind': r['kind'], 'source': 'invoice'})
        for r in conn.execute(f'SELECT id, number, kind FROM material_docs WHERE number IN ({ph})', part):
            out.setdefault(r['number'], {'id': r['id'], 'kind': r['kind'], 'source': 'material_doc'})
    return out


def annotate(conn, rows, people=True):
    """Hareket satırlarına fatura (belge no) ve personel (açıklamadaki ad) bağlantısı ekler."""
    inv = invoice_map(conn, [r.get('doc_no') for r in rows])
    idx = employees_index(conn) if people else []
    for r in rows:
        r['invoice'] = inv.get(r.get('doc_no'))
        r['person'] = match_person(r.get('description'), idx) if idx else None
    return rows


def doc_moves(conn, number):
    """Belge numarasına bağlı cari / kasa / banka hareketleri ve muhasebe fişi satırları."""
    if not number:
        return {'txns': [], 'ledger': []}
    txns = db.rows(conn.execute('''SELECT t.*, a.name AS account_name, a.kind AS account_kind, a.company_id FROM fin_txns t
                                   JOIN fin_accounts a ON a.id = t.account_id WHERE t.doc_no = ? ORDER BY t.date, t.id''', (number,)))
    ledger = db.rows(conn.execute('''SELECT l.date, l.journal_no, l.account, c.name AS account_name, l.description, l.debit, l.credit
                                     FROM fin_ledger l LEFT JOIN fin_coa c ON c.code = l.account WHERE l.doc_no = ? ORDER BY l.date, l.journal_no, l.entry_no''',
                                  (number,)))
    return {'txns': txns, 'ledger': ledger}


def _bal(conn, aid, opening):
    r = conn.execute("SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount ELSE -amount END),0) FROM fin_txns WHERE account_id=?", (aid,)).fetchone()
    return round((opening or 0) + (r[0] or 0), 2)


def person_moves(conn, emp):
    """Personelin hesap hareketleri: açıklamasında adı geçen kasa / banka / cari hareketleri + elle bağlanan cari, hesap ve
    muhasebe hesaplarının hareketleri. Adı geçen ama bağlanmamış hesaplar öneri olarak döner."""
    keys = person_keys(emp['first_name'], emp['last_name'])
    links = db.rows(conn.execute('SELECT * FROM employee_fin_links WHERE employee_id = ? ORDER BY id', (emp['id'],)))
    acc_ids, ledger_codes = set(), set()
    for ln in links:
        if ln['kind'] == 'account' and ln['ref'].isdigit():
            acc_ids.add(int(ln['ref']))
            a = db.row(conn.execute('SELECT name, kind, opening FROM fin_accounts WHERE id = ?', (int(ln['ref']),)))
            ln['label'], ln['sub'] = (a['name'], a['kind']) if a else ('(silinmiş hesap)', '')
            ln['balance'] = _bal(conn, int(ln['ref']), a['opening']) if a else None
        elif ln['kind'] == 'company' and ln['ref'].isdigit():
            c = db.row(conn.execute('SELECT name FROM companies WHERE id = ?', (int(ln['ref']),)))
            ln['label'], ln['sub'] = (c['name'] if c else '(silinmiş firma)'), 'cari'
            for (aid, opening) in conn.execute("SELECT id, opening FROM fin_accounts WHERE kind='cari' AND company_id = ?", (int(ln['ref']),)):
                acc_ids.add(aid)
                ln['balance'] = _bal(conn, aid, opening)
        elif ln['kind'] == 'ledger':
            ledger_codes.add(ln['ref'])
            c = conn.execute('SELECT name FROM fin_coa WHERE code = ?', (ln['ref'],)).fetchone()
            ln['label'], ln['sub'] = f"{ln['ref']} {c[0] if c else ''}".strip(), 'muhasebe'
            r = conn.execute("SELECT COALESCE(SUM(debit - credit), 0) FROM fin_ledger WHERE account = ? OR account LIKE ?", (ln['ref'], ln['ref'] + '.%')).fetchone()
            ln['balance'] = round(r[0] or 0, 2)
    rows = []
    for r in db.rows(conn.execute('''SELECT t.*, a.name AS account_name, a.kind AS account_kind, a.company_id FROM fin_txns t
                                     JOIN fin_accounts a ON a.id = t.account_id ORDER BY t.date DESC, t.id DESC''')):
        linked = r['account_id'] in acc_ids
        named = bool(keys) and any(k in squash(r['description']) for k in keys)
        if linked or named:
            r['via'] = 'link' if linked else 'name'
            rows.append(r)
    annotate(conn, rows, people=False)
    ledger = []
    for code in ledger_codes:
        ledger += db.rows(conn.execute('''SELECT l.date, l.journal_no, l.account, c.name AS account_name, l.description, l.debit, l.credit, l.doc_no
                                          FROM fin_ledger l LEFT JOIN fin_coa c ON c.code = l.account
                                          WHERE l.account = ? OR l.account LIKE ? ''', (code, code + '.%')))
    ledger.sort(key=lambda x: (x['date'], x['journal_no'] or 0), reverse=True)
    # Öneri: adı taşıyan ama bağlanmamış cari / kasa / banka hesapları ve muhasebe hesapları
    sugg = []
    if keys:
        linked_companies = {ln['ref'] for ln in links if ln['kind'] == 'company'}
        for a in db.rows(conn.execute('SELECT id, kind, name, company_id FROM fin_accounts WHERE active = 1')):
            if a['id'] in acc_ids or (a['company_id'] and str(a['company_id']) in linked_companies):
                continue
            if any(k in squash(a['name']) for k in keys):
                if a['kind'] == 'cari' and a['company_id']:
                    sugg.append({'kind': 'company', 'ref': str(a['company_id']), 'label': a['name'], 'sub': 'cari'})
                else:
                    sugg.append({'kind': 'account', 'ref': str(a['id']), 'label': a['name'], 'sub': a['kind']})
        for code, name in conn.execute('SELECT code, name FROM fin_coa'):
            if code not in ledger_codes and any(k in squash(name) for k in keys) and conn.execute('SELECT 1 FROM fin_ledger WHERE account = ? LIMIT 1', (code,)).fetchone():
                sugg.append({'kind': 'ledger', 'ref': code, 'label': f'{code} {name}', 'sub': 'muhasebe'})
    paid = sum(r['amount'] for r in rows if r['account_kind'] in ('kasa', 'banka') and r['direction'] == 'out')
    maas = [r for r in rows if r['account_kind'] in ('kasa', 'banka') and r['direction'] == 'out' and 'maas' in fold(r['description'] or '')]
    return {'links': links, 'suggestions': sugg[:12], 'rows': rows, 'ledger': ledger[:1000],
            'totals': {'paid': round(paid, 2), 'salary': round(sum(r['amount'] for r in maas), 2), 'salary_count': len(maas),
                       'last_salary': maas[0]['date'] if maas else None},
            'name_keys': bool(keys)}


def link_options(conn, q):
    """Bağlanacak cari / hesap / muhasebe hesabı araması."""
    s = squash(q)
    out = []
    if len(s) < 2:
        return out
    for c in conn.execute('SELECT id, name, is_supplier FROM companies WHERE active = 1'):
        if s in squash(c['name']):
            out.append({'kind': 'company', 'ref': str(c['id']), 'label': c['name'], 'sub': 'tedarikçi cari' if c['is_supplier'] else 'cari'})
    for a in conn.execute("SELECT id, name, kind FROM fin_accounts WHERE active = 1 AND kind IN ('kasa','banka')"):
        if s in squash(a['name']):
            out.append({'kind': 'account', 'ref': str(a['id']), 'label': a['name'], 'sub': a['kind']})
    for code, name in conn.execute('SELECT code, name FROM fin_coa'):
        if s in squash(name) or code.startswith(q.strip()):
            out.append({'kind': 'ledger', 'ref': code, 'label': f'{code} {name}', 'sub': 'muhasebe'})
    return out[:40]
