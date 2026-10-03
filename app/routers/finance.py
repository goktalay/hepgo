"""Finans / Ön-Muhasebe: kasa & banka hesapları, cariler, hareketler, cari ekstre, nakit pozisyonu özeti.
Cariler = Firma Yönetimi'ndeki firmalar ve Satın Alma'daki tedarikçiler (ayrı cari listesi yok); firmanın finans hesabı
ilk hareket/ekstrede otomatik açılır. Mikro ERP aktarımı modülde değil, Program Ayarları › Entegrasyonlar'dadır.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/finance')
fin_user = auth.require_module('finance')
KINDS = ('kasa', 'banka', 'cari')


def _balance_row(conn, acc_id, opening):
    r = conn.execute("SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount ELSE -amount END),0) FROM fin_txns WHERE account_id=?", (acc_id,)).fetchone()
    return round((opening or 0) + (r[0] or 0), 2)


class AccountIn(BaseModel):
    kind: str
    name: str
    currency: str = 'TRY'
    iban: Optional[str] = None
    bank: Optional[str] = None
    company_id: Optional[int] = None
    opening: float = 0
    mikro_code: Optional[str] = None
    note: Optional[str] = None


@router.get('/accounts')
def accounts(kind: str = '', user=Depends(fin_user), conn=db.DB):
    where, args = ['a.active=1'], []
    if kind in KINDS:
        where.append('a.kind=?'); args.append(kind)
    rows = db.rows(conn.execute(
        f'''SELECT a.*, c.name AS company_name FROM fin_accounts a
            LEFT JOIN companies c ON c.id=a.company_id
            WHERE {" AND ".join(where)} ORDER BY a.kind, a.name COLLATE NOCASE''', args))
    for r in rows:
        r['balance'] = _balance_row(conn, r['id'], r['opening'])
    return rows


@router.post('/accounts')
def add_account(body: AccountIn, user=Depends(fin_user), conn=db.DB):
    if body.kind not in ('kasa', 'banka'):
        raise HTTPException(400, 'Buradan yalnızca kasa / banka hesabı açılır; cariler Firma Yönetimi’ndeki firmalardır')
    cur = conn.execute('''INSERT INTO fin_accounts (kind,name,currency,iban,bank,company_id,opening,mikro_code,note,active,created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,1,?)''',
                       (body.kind, body.name.strip()[:120], body.currency[:3].upper(), body.iban, body.bank,
                        body.company_id, body.opening or 0, body.mikro_code, body.note, db.now()))
    conn.commit()
    db.audit(conn, user['id'], 'Finans hesabı ekledi', 'fin_account', cur.lastrowid, f'{body.kind} · {body.name}')
    return {'id': cur.lastrowid}


@router.put('/accounts/{aid}')
def edit_account(aid: int, body: AccountIn, user=Depends(fin_user), conn=db.DB):
    if not conn.execute('SELECT 1 FROM fin_accounts WHERE id=?', (aid,)).fetchone():
        raise HTTPException(404, 'Hesap yok')
    conn.execute('''UPDATE fin_accounts SET name=?,currency=?,iban=?,bank=?,company_id=?,opening=?,mikro_code=?,note=? WHERE id=?''',
                 (body.name.strip()[:120], body.currency[:3].upper(), body.iban, body.bank, body.company_id,
                  body.opening or 0, body.mikro_code, body.note, aid))
    conn.commit()
    return {'ok': True}


@router.delete('/accounts/{aid}')
def del_account(aid: int, user=Depends(fin_user), conn=db.DB):
    conn.execute('UPDATE fin_accounts SET active=0 WHERE id=?', (aid,))
    conn.commit()
    return {'ok': True}


class TxnIn(BaseModel):
    account_id: int
    date: str
    direction: str
    amount: float
    currency: str = 'TRY'
    category: Optional[str] = None
    counter_id: Optional[int] = None
    description: Optional[str] = None
    doc_no: Optional[str] = None


@router.get('/txns')
def txns(account_id: int = 0, date_from: str = '', date_to: str = '', limit: int = 500, user=Depends(fin_user), conn=db.DB):
    where, args = ['1=1'], []
    if account_id:
        where.append('t.account_id=?'); args.append(account_id)
    if date_from:
        where.append('t.date>=?'); args.append(date_from)
    if date_to:
        where.append('t.date<=?'); args.append(date_to)
    rows = db.rows(conn.execute(
        f'''SELECT t.*, a.name AS account_name, a.kind AS account_kind FROM fin_txns t
            JOIN fin_accounts a ON a.id=t.account_id
            WHERE {" AND ".join(where)} ORDER BY t.date DESC, t.id DESC LIMIT ?''', (*args, min(limit, 2000))))
    return rows


@router.post('/txns')
def add_txn(body: TxnIn, user=Depends(fin_user), conn=db.DB):
    if body.direction not in ('in', 'out'):
        raise HTTPException(400, 'Yön in/out olmalı')
    if body.amount <= 0:
        raise HTTPException(400, 'Tutar sıfırdan büyük olmalı')
    cur = conn.execute('''INSERT INTO fin_txns (account_id,date,direction,amount,currency,category,counter_id,description,doc_no,created_by,created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                       (body.account_id, body.date[:10], body.direction, abs(body.amount), body.currency[:3].upper(),
                        body.category, body.counter_id, body.description, body.doc_no, user['id'], db.now()))
    # Virman: karşı hesaba ters yönde otomatik hareket
    if body.counter_id:
        conn.execute('''INSERT INTO fin_txns (account_id,date,direction,amount,currency,category,counter_id,description,doc_no,created_by,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                     (body.counter_id, body.date[:10], 'in' if body.direction == 'out' else 'out', abs(body.amount),
                      body.currency[:3].upper(), 'Virman', body.account_id, body.description or 'Virman', body.doc_no, user['id'], db.now()))
    conn.commit()
    db.audit(conn, user['id'], 'Finans hareketi ekledi', 'fin_txn', cur.lastrowid, f'{body.direction} {body.amount}')
    return {'id': cur.lastrowid}


@router.delete('/txns/{tid}')
def del_txn(tid: int, user=Depends(fin_user), conn=db.DB):
    r = conn.execute('SELECT mikro_ref FROM fin_txns WHERE id=?', (tid,)).fetchone()
    if r and r[0]:   # Mikro'dan yansıyan hareket: bir sonraki senkronda geri gelirdi — kaynağında düzeltilmeli
        raise HTTPException(409, 'Bu hareket Mikro ERP’den senkronize edildi; düzeltmeyi Mikro’da yapın (sonraki senkronda yansır).')
    conn.execute('DELETE FROM fin_txns WHERE id=?', (tid,))
    conn.commit()
    return {'ok': True}


@router.get('/accounts/{aid}/statement')
def statement(aid: int, date_from: str = '', date_to: str = '', user=Depends(fin_user), conn=db.DB):
    """Cari / hesap ekstresi: hareketler + yürüyen bakiye."""
    acc = db.row(conn.execute('''SELECT a.*, c.name AS company_name FROM fin_accounts a
                                 LEFT JOIN companies c ON c.id=a.company_id WHERE a.id=?''', (aid,)))
    if not acc:
        raise HTTPException(404, 'Hesap yok')
    rows = db.rows(conn.execute('SELECT * FROM fin_txns WHERE account_id=? ORDER BY date, id', (aid,)))
    bal = acc['opening'] or 0
    out = []
    for r in rows:
        bal += r['amount'] if r['direction'] == 'in' else -r['amount']
        r['balance'] = round(bal, 2)
        if (not date_from or r['date'] >= date_from) and (not date_to or r['date'] <= date_to):
            out.append(r)
    acc['balance'] = round(bal, 2)
    return {'account': acc, 'rows': out, 'opening': acc['opening'] or 0}


@router.get('/summary')
def summary(user=Depends(fin_user), conn=db.DB):
    """Finans özeti: nakit pozisyonu (kasa+banka), cari borç/alacak, bu ay giriş/çıkış, son hareketler."""
    accs = db.rows(conn.execute("SELECT * FROM fin_accounts WHERE active=1"))
    cash = 0.0
    receivable = 0.0   # bizden alacaklı (cari bakiye +)
    payable = 0.0
    for a in accs:
        b = _balance_row(conn, a['id'], a['opening'])
        if a['kind'] in ('kasa', 'banka'):
            cash += b
        elif a['kind'] == 'cari':
            if b >= 0:
                receivable += b
            else:
                payable += -b
    month = db.now()[:7]
    mi = conn.execute("SELECT COALESCE(SUM(amount),0) FROM fin_txns WHERE direction='in' AND substr(date,1,7)=?", (month,)).fetchone()[0]
    mo = conn.execute("SELECT COALESCE(SUM(amount),0) FROM fin_txns WHERE direction='out' AND substr(date,1,7)=?", (month,)).fetchone()[0]
    recent = db.rows(conn.execute('''SELECT t.*, a.name AS account_name, a.kind AS account_kind, a.company_id FROM fin_txns t JOIN fin_accounts a ON a.id=t.account_id
                                     ORDER BY t.date DESC, t.id DESC LIMIT 12'''))
    # son 6 ay giriş/çıkış (grafik)
    series = db.rows(conn.execute('''SELECT substr(date,1,7) AS ay,
                                     SUM(CASE WHEN direction='in' THEN amount ELSE 0 END) AS giris,
                                     SUM(CASE WHEN direction='out' THEN amount ELSE 0 END) AS cikis
                                     FROM fin_txns GROUP BY ay ORDER BY ay DESC LIMIT 6'''))
    return {'cash': round(cash, 2), 'receivable': round(receivable, 2), 'payable': round(payable, 2),
            'month_in': round(mi, 2), 'month_out': round(mo, 2), 'recent': recent, 'series': list(reversed(series)),
            'accounts': len(accs)}


# ---------------- Cariler = firmalar / tedarikçiler ----------------
def _cari_account(conn, company_id):
    """Firmanın cari finans hesabı (yoksa oluşturulur)."""
    r = conn.execute("SELECT id FROM fin_accounts WHERE kind='cari' AND company_id=? AND active=1", (company_id,)).fetchone()
    if r:
        return r[0]
    c = conn.execute('SELECT name FROM companies WHERE id=?', (company_id,)).fetchone()
    if not c:
        raise HTTPException(404, 'Firma bulunamadı')
    cur = conn.execute("INSERT INTO fin_accounts (kind,name,company_id,opening,active,created_at) VALUES ('cari',?,?,0,1,?)",
                       (c[0], company_id, db.now()))
    conn.commit()
    return cur.lastrowid


@router.get('/cari')
def cari_list(supplier: int = -1, user=Depends(fin_user), conn=db.DB):
    """Firmalar (müşteri) ve tedarikçiler, cari bakiyeleriyle. supplier: 1 tedarikçi, 0 müşteri, -1 hepsi."""
    cols = {r[1] for r in conn.execute('PRAGMA table_info(companies)')}
    sup = 'c.is_supplier' if 'is_supplier' in cols else '0'
    where = ['c.active=1']
    if supplier in (0, 1):
        where.append(f'COALESCE({sup},0)=?')
    rows = db.rows(conn.execute(
        f'''SELECT c.id, c.name, c.phone, c.tax_no, COALESCE({sup},0) AS is_supplier, a.id AS account_id, a.opening,
                   (SELECT MAX(t.date) FROM fin_txns t WHERE t.account_id=a.id) AS last_date
            FROM companies c LEFT JOIN fin_accounts a ON a.kind='cari' AND a.company_id=c.id AND a.active=1
            WHERE {" AND ".join(where)} ORDER BY c.name COLLATE NOCASE''', (supplier,) if supplier in (0, 1) else ()))
    for r in rows:
        r['balance'] = _balance_row(conn, r['account_id'], r['opening']) if r['account_id'] else 0.0
    return rows


@router.get('/cari/{company_id}')
def cari_statement(company_id: int, date_from: str = '', date_to: str = '', user=Depends(fin_user), conn=db.DB):
    """Firmanın cari ekstresi (hesap yoksa açılır)."""
    return statement(_cari_account(conn, company_id), date_from, date_to, user, conn)


# ================= Finans v2: mizan, mali tablolar, nakit akışı, çek / senet, planlı ödemeler =================
import json as _json   # noqa: E402

from .. import finance_reports as fr   # noqa: E402

SET_KEY = 'fin.settings'


def _settings(conn):
    r = conn.execute('SELECT v FROM app_kv WHERE k=?', (SET_KEY,)).fetchone()
    try:
        s = _json.loads(r[0]) if r else {}
    except ValueError:
        s = {}
    return {'payday': int(s.get('payday') or 0), 'salaries': s.get('salaries', True)}


@router.get('/trial')
def trial(date_from: str = '', date_to: str = '', level: int = 3, user=Depends(fin_user), conn=db.DB):
    """Mizan (Mikro muhasebe fişlerinden)."""
    return {**fr.trial_balance(conn, date_from, date_to, max(1, min(level, 9))), 'has_ledger': fr.has_ledger(conn)}


@router.get('/ledger')
def ledger(account: str, date_from: str = '', date_to: str = '', user=Depends(fin_user), conn=db.DB):
    return fr.account_ledger(conn, account.strip(), date_from, date_to)


@router.get('/statements')
def fin_statements(date_from: str = '', date_to: str = '', user=Depends(fin_user), conn=db.DB):
    return {**fr.statements(conn, date_from, date_to), 'has_ledger': fr.has_ledger(conn)}


@router.get('/cashflow')
def fin_cashflow(weeks: int = 12, user=Depends(fin_user), conn=db.DB):
    st = _settings(conn)
    return {**fr.cashflow(conn, max(4, min(weeks, 52)), st['payday'], st['salaries']), 'settings': st}


class FinSettingsIn(BaseModel):
    payday: int = 0
    salaries: bool = True


@router.put('/settings')
def fin_settings(body: FinSettingsIn, user=Depends(fin_user), conn=db.DB):
    v = {'payday': max(0, min(body.payday, 28)), 'salaries': body.salaries}
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (SET_KEY, _json.dumps(v)))
    conn.commit()
    return v


# ---- Çek / senet
INSTR_STATUS = {'portfoy': 'Portföyde', 'tahsilde': 'Bankada tahsilde', 'teminatta': 'Teminatta', 'ciro': 'Ciro edildi',
                'tahsil': 'Tahsil edildi', 'odendi': 'Ödendi', 'karsiliksiz': 'Karşılıksız / protestolu', 'iade': 'İade edildi'}


class InstrIn(BaseModel):
    kind: str = 'cek'
    direction: str = 'alinan'
    number: Optional[str] = None
    bank: Optional[str] = None
    drawer: Optional[str] = None
    company_id: Optional[int] = None
    amount: float
    issue_date: Optional[str] = None
    due_date: str
    status: str = 'portfoy'
    note: Optional[str] = None


def _instr_clean(b: InstrIn):
    if b.kind not in ('cek', 'senet') or b.direction not in ('alinan', 'verilen') or b.status not in INSTR_STATUS:
        raise HTTPException(400, 'Geçersiz tür / yön / durum')
    if not b.amount or b.amount <= 0 or not b.due_date:
        raise HTTPException(400, 'Tutar ve vade tarihi gerekli')
    return (b.kind, b.direction, (b.number or '').strip() or None, (b.bank or '').strip() or None, (b.drawer or '').strip() or None,
            b.company_id, round(b.amount, 2), b.issue_date or None, b.due_date[:10], b.status, (b.note or '').strip() or None)


@router.get('/instruments')
def instruments(status: str = '', user=Depends(fin_user), conn=db.DB):
    rows = db.rows(conn.execute('''SELECT i.*, c.name AS company FROM fin_instruments i LEFT JOIN companies c ON c.id=i.company_id
                                   ORDER BY CASE WHEN i.status IN ('portfoy','tahsilde','teminatta') THEN 0 ELSE 1 END, i.due_date'''))
    return {'rows': rows, 'statuses': INSTR_STATUS}


@router.post('/instruments')
def instrument_add(body: InstrIn, user=Depends(fin_user), conn=db.DB):
    now = db.now()
    cur = conn.execute('''INSERT INTO fin_instruments (kind, direction, number, bank, drawer, company_id, amount, issue_date, due_date, status, note,
                          created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (*_instr_clean(body), user['id'], now, now))
    db.audit(conn, user['id'], 'Çek/senet kaydı', 'fin_instrument', cur.lastrowid, f'{body.kind} {body.amount}')
    conn.commit()
    return {'id': cur.lastrowid}


@router.put('/instruments/{iid}')
def instrument_edit(iid: int, body: InstrIn, user=Depends(fin_user), conn=db.DB):
    conn.execute('''UPDATE fin_instruments SET kind=?, direction=?, number=?, bank=?, drawer=?, company_id=?, amount=?, issue_date=?, due_date=?,
                    status=?, note=?, updated_at=? WHERE id=?''', (*_instr_clean(body), db.now(), iid))
    conn.commit()
    return {'ok': True}


@router.delete('/instruments/{iid}')
def instrument_del(iid: int, user=Depends(fin_user), conn=db.DB):
    conn.execute('DELETE FROM fin_instruments WHERE id=?', (iid,))
    conn.commit()
    return {'ok': True}


# ---- Planlı ödeme / tahsilat
class PlanIn(BaseModel):
    date: str
    direction: str = 'out'
    amount: float
    description: str
    category: Optional[str] = None
    repeat: str = 'none'
    until: Optional[str] = None


@router.get('/plans')
def plans(user=Depends(fin_user), conn=db.DB):
    return db.rows(conn.execute('SELECT * FROM fin_plans ORDER BY date'))


@router.post('/plans')
def plan_add(body: PlanIn, user=Depends(fin_user), conn=db.DB):
    if body.direction not in ('in', 'out') or body.amount <= 0 or not body.description.strip() or not body.date:
        raise HTTPException(400, 'Tarih, yön, tutar ve açıklama gerekli')
    cur = conn.execute('INSERT INTO fin_plans (date, direction, amount, description, category, repeat, until, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                       (body.date[:10], body.direction, round(body.amount, 2), body.description.strip()[:200], (body.category or '').strip() or None,
                        body.repeat if body.repeat in ('none', 'monthly') else 'none', (body.until or '')[:10] or None, user['id'], db.now()))
    conn.commit()
    return {'id': cur.lastrowid}


@router.delete('/plans/{pid}')
def plan_del(pid: int, user=Depends(fin_user), conn=db.DB):
    conn.execute('DELETE FROM fin_plans WHERE id=?', (pid,))
    conn.commit()
    return {'ok': True}


# ================= Hareketler ilgili kaydın detayında: hesap / cari detayı, fatura ve personel hareketleri =================
from datetime import date as _date   # noqa: E402

from .. import fin_links   # noqa: E402


def _any_module(*mods):
    def dep(user=Depends(auth.current_user)):
        if user.get('master') or set(mods) & set(user.get('modules', [])):
            return user
        raise HTTPException(403, 'Bu işlem için yetkiniz yok')
    return dep


doc_user = _any_module('finance', 'sales', 'purchasing')     # fatura detayındaki "Hareketler"
person_user = _any_module('finance', 'hr')                    # personel detayındaki "Hesap Hareketleri"


def _sums(rows):
    t_in = sum(r['amount'] for r in rows if r['direction'] == 'in')
    t_out = sum(r['amount'] for r in rows if r['direction'] == 'out')
    return round(t_in, 2), round(t_out, 2)


@router.get('/accounts/{aid}/detail')
def account_detail(aid: int, date_from: str = '', date_to: str = '', user=Depends(fin_user), conn=db.DB):
    """Kasa / banka hesabı detayı: hesap bilgisi, özet ve hareketler (yeni → eski, yürüyen bakiyeli, fatura / personel bağlantılı)."""
    st = statement(aid, date_from, date_to, user, conn)
    st['rows'] = fin_links.annotate(conn, st['rows'][::-1])
    month = db.now()[:7]
    t_in, t_out = _sums(st['rows'])
    m_in, m_out = _sums([r for r in st['rows'] if r['date'][:7] == month])
    st['kpi'] = {'in': t_in, 'out': t_out, 'month_in': m_in, 'month_out': m_out, 'count': len(st['rows'])}
    return st


@router.get('/cari/{company_id}/detail')
def cari_detail(company_id: int, date_from: str = '', date_to: str = '', user=Depends(fin_user), conn=db.DB):
    """Cari detayı: firma, bakiye, hareketler (ekstre), faturalar, açık kalemler (FIFO, vadeli) ve çek / senetler."""
    c = db.row(conn.execute('SELECT id, name, phone, email, tax_office, tax_no, COALESCE(is_supplier, 0) AS is_supplier FROM companies WHERE id = ?', (company_id,)))
    if not c:
        raise HTTPException(404, 'Firma bulunamadı')
    aid = _cari_account(conn, company_id)
    st = statement(aid, date_from, date_to, user, conn)
    st['rows'] = fin_links.annotate(conn, st['rows'][::-1])
    rec, pay = fr.open_items(conn)
    today = _date.today().isoformat()
    items = [dict(i, side='rec') for i in rec if i['account_id'] == aid] + [dict(i, side='pay') for i in pay if i['account_id'] == aid]
    for i in items:
        try:
            i['late'] = (_date.today() - _date.fromisoformat(i['due'][:10])).days
        except ValueError:
            i['late'] = 0
    items.sort(key=lambda i: i['due'])
    invoices = db.rows(conn.execute('''SELECT id, kind, source, number, invoice_date AS date, total, currency, 'invoice' AS src FROM invoices
                                       WHERE company_id = ? OR (company_id IS NULL AND company_name = ?)''', (company_id, c['name'])))
    invoices += db.rows(conn.execute('''SELECT id, kind, 'manual' AS source, number, COALESCE(doc_date, substr(created_at, 1, 10)) AS date, amount AS total,
                                        'TRY' AS currency, 'material_doc' AS src FROM material_docs WHERE company_id = ?''', (company_id,)))
    invoices.sort(key=lambda r: r['date'] or '', reverse=True)
    docs_with_moves = {r[0] for r in conn.execute('SELECT DISTINCT doc_no FROM fin_txns WHERE account_id = ? AND doc_no IS NOT NULL', (aid,))}
    for r in invoices:
        r['has_moves'] = r['number'] in docs_with_moves   # bu carideki hareketi olan faturalar işaretlenir
    instruments = db.rows(conn.execute('SELECT * FROM fin_instruments WHERE company_id = ? ORDER BY due_date DESC', (company_id,)))
    t_in, t_out = _sums(st['rows'])
    st.update(company=c, open_items=items, invoices=invoices, instruments=instruments, instr_status=INSTR_STATUS,
              kpi={'in': t_in, 'out': t_out, 'count': len(st['rows']), 'open_rec': round(sum(i['amount'] for i in items if i['side'] == 'rec'), 2),
                   'open_pay': round(sum(i['amount'] for i in items if i['side'] == 'pay'), 2),
                   'overdue': round(sum(i['amount'] for i in items if i['due'][:10] < today), 2)})
    return st


@router.get('/docs/moves')
def doc_moves(number: str, user=Depends(doc_user), conn=db.DB):
    """Fatura / belge numarasına bağlı cari-kasa-banka hareketleri ve muhasebe fişi satırları (fatura detayındaki Hareketler)."""
    return fin_links.doc_moves(conn, number.strip())


@router.get('/invoices/{iid}')
def invoice_detail(iid: int, src: str = 'invoice', user=Depends(fin_user), conn=db.DB):
    """Cari detayından açılan fatura: başlık, kalemler ve hareketler."""
    if src == 'material_doc':
        inv = db.row(conn.execute('''SELECT d.id, d.kind, d.number, COALESCE(d.doc_date, substr(d.created_at, 1, 10)) AS invoice_date, d.amount AS total,
                                     c.name AS company_name, d.note FROM material_docs d LEFT JOIN companies c ON c.id = d.company_id WHERE d.id = ?''', (iid,)))
        items = db.rows(conn.execute('''SELECT m.qty, m.unit_price, p.name AS description, p.unit FROM material_moves m LEFT JOIN products p ON p.id = m.product_id
                                        WHERE m.doc_id = ? ORDER BY m.id''', (iid,))) if inv else []
    else:
        inv = db.row(conn.execute('SELECT * FROM invoices WHERE id = ?', (iid,)))
        items = db.rows(conn.execute('SELECT description, qty, unit, unit_price, vat_rate, line_total FROM invoice_items WHERE invoice_id = ? ORDER BY id', (iid,))) if inv else []
    if not inv:
        raise HTTPException(404, 'Fatura bulunamadı')
    inv['items'] = items
    inv['moves'] = fin_links.doc_moves(conn, inv['number'])
    return inv


@router.get('/person/{eid}')
def person(eid: int, user=Depends(person_user), conn=db.DB):
    emp = db.row(conn.execute('SELECT id, first_name, last_name FROM employees WHERE id = ?', (eid,)))
    if not emp:
        raise HTTPException(404, 'Personel bulunamadı')
    d = fin_links.person_moves(conn, emp)
    d['kinds'] = fin_links.LINK_KINDS
    d['can_finance'] = bool(user.get('master') or 'finance' in user.get('modules', []))
    return d


class LinkIn(BaseModel):
    kind: str
    ref: str


@router.post('/person/{eid}/links')
def person_link(eid: int, body: LinkIn, user=Depends(person_user), conn=db.DB):
    if not conn.execute('SELECT 1 FROM employees WHERE id = ?', (eid,)).fetchone():
        raise HTTPException(404, 'Personel bulunamadı')
    ok = {'company': 'SELECT 1 FROM companies WHERE id = ?', 'account': 'SELECT 1 FROM fin_accounts WHERE id = ?',
          'ledger': 'SELECT 1 FROM fin_coa WHERE code = ?'}.get(body.kind)
    if not ok or not conn.execute(ok, (body.ref,)).fetchone():
        raise HTTPException(400, 'Bağlanacak kayıt bulunamadı')
    conn.execute('INSERT OR IGNORE INTO employee_fin_links (employee_id, kind, ref, created_by, created_at) VALUES (?,?,?,?,?)',
                 (eid, body.kind, body.ref, user['id'], db.now()))
    db.audit(conn, user['id'], 'Personeli finans hesabına bağladı', 'employee', eid, f'{body.kind}:{body.ref}')
    conn.commit()
    return {'ok': True}


@router.delete('/person/{eid}/links/{lid}')
def person_unlink(eid: int, lid: int, user=Depends(person_user), conn=db.DB):
    conn.execute('DELETE FROM employee_fin_links WHERE id = ? AND employee_id = ?', (lid, eid))
    conn.commit()
    return {'ok': True}


@router.get('/person-link-options')
def person_link_options(q: str = '', user=Depends(person_user), conn=db.DB):
    return fin_links.link_options(conn, q)
