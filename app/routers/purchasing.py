"""Satın Alma: Tedarikçi Yönetimi (Firma Yönetimi'nin tedarikçi kapsamı, app/routers/companies.py), Talep Yönetimi,
Fatura İrsaliye ve Teklif Yönetimi.

Talep: kalemleri (yedek parça, hammadde, demirbaş, sarf malzeme; miktar ve satır açıklaması) girilir, Sistem Yöneticisi
onayına gönderilir. Fatura / irsaliye: kalemleri seçilen depoya (varsayılan Ana Depo) stok girişi olarak işlenir
(MRP stok hareketleri); talebe bağlanırsa talebin teslim alınan miktarları görünür, hepsi gelince talep tamamlanır.
Teklif: tedarikçiye birden fazla kalemli teklif; gönderildikten sonra değişiklik revizyonla yapılır, eski revizyonlar saklanır.
"""
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import auth, db, spares
from ..files import save_upload
from .mrp import TYPES as MATERIAL_TYPES, add_move

router = APIRouter(prefix='/api/purchasing')
buyer = auth.require_module('purchasing')
REQ_STATUS = {'TASLAK': 'Taslak', 'ONAY_BEKLIYOR': 'Onay bekliyor', 'ONAYLANDI': 'Onaylandı', 'REDDEDILDI': 'Reddedildi',
              'TAMAMLANDI': 'Tamamlandı', 'IPTAL': 'İptal'}
QUOTE_STATUS = {'TASLAK': 'Taslak', 'GONDERILDI': 'Firmaya iletildi', 'KABUL': 'Kabul edildi', 'RED': 'Reddedildi'}


def _date(v, label):
    v = (v or '').strip()
    if not v:
        return None
    try:
        date.fromisoformat(v)
    except ValueError:
        raise HTTPException(400, f'{label} geçersiz')
    return v


def _material(conn, pid):
    m = db.row(conn.execute('SELECT id, code, name, type, unit FROM products WHERE id = ?', (pid,)))
    if not m or m['type'] not in MATERIAL_TYPES:
        raise HTTPException(400, 'Kalem yedek parça, hammadde, demirbaş ya da sarf malzeme olmalı')
    return m


def _supplier(conn, cid, required=True):
    if not cid:
        if required:
            raise HTTPException(400, 'Tedarikçiyi seçin')
        return None
    c = db.row(conn.execute('SELECT id, name, email FROM companies WHERE id = ? AND is_supplier = 1', (cid,)))
    if not c:
        raise HTTPException(400, 'Tedarikçi bulunamadı')
    return c


@router.get('/options')
def options(user=Depends(buyer), conn=db.DB):
    """Seçim listeleri: malzemeler, tedarikçiler, depolar."""
    return {
        'materials': db.rows(conn.execute(
            f"SELECT id, code, name, type, unit, active FROM products WHERE type IN ({','.join('?' * len(MATERIAL_TYPES))}) ORDER BY code",
            MATERIAL_TYPES)),
        'suppliers': db.rows(conn.execute('SELECT id, name, email, logo FROM companies WHERE is_supplier = 1 AND active = 1 ORDER BY name')),
        'warehouses': db.rows(conn.execute('SELECT id, name, code FROM warehouses WHERE active = 1 ORDER BY id')),
        'types': {k: spares.TYPES[k] for k in MATERIAL_TYPES},
    }


# ---------- Talep Yönetimi

class RequestIn(BaseModel):
    title: str
    note: Optional[str] = None
    needed_by: Optional[str] = None


class RequestItemIn(BaseModel):
    product_id: int
    qty: float
    note: Optional[str] = None


class DecisionIn(BaseModel):
    note: Optional[str] = None


def _received(conn, rid):
    """Talebe bağlı faturalarla depoya giren miktarlar {product_id: miktar}."""
    return dict(conn.execute(
        '''SELECT m.product_id, SUM(m.qty) FROM material_moves m JOIN material_docs d ON d.id = m.doc_id
           WHERE d.request_id = ? AND m.kind = 'GIRIS' GROUP BY m.product_id''', (rid,)).fetchall())


def _request(conn, rid):
    r = db.row(conn.execute(
        '''SELECT r.*, u.full_name AS created_by_name, d.full_name AS decided_by_name FROM purchase_requests r
           LEFT JOIN users u ON u.id = r.created_by LEFT JOIN users d ON d.id = r.decided_by WHERE r.id = ?''', (rid,)))
    if not r:
        raise HTTPException(404, 'Talep bulunamadı')
    got = _received(conn, rid)
    r['items'] = db.rows(conn.execute(
        '''SELECT i.*, p.code, p.name, p.type, p.unit FROM purchase_request_items i JOIN products p ON p.id = i.product_id
           WHERE i.request_id = ? ORDER BY i.pos, i.id''', (rid,)))
    for i in r['items']:
        i['received'] = round(got.get(i['product_id'], 0) or 0, 3)
    r['status_label'] = REQ_STATUS.get(r['status'], r['status'])
    return r


@router.get('/requests')
def requests(date_from: str = '', date_to: str = '', user=Depends(buyer), conn=db.DB):
    # Tarih aralığı: açık talepler (taslak / onay bekliyor / onaylandı) her zaman; kapanmışlar açıldığı ya da karara bağlandığı döneme göre
    c1, a1 = db.date_cond('r.created_at', date_from, date_to)
    c2, a2 = db.date_cond('r.decided_at', date_from, date_to)
    where = f"(r.status IN ('TASLAK', 'ONAY_BEKLIYOR', 'ONAYLANDI') OR ({c1}) OR ({c2}))" if (date_from or date_to) else '1=1'
    rows = db.rows(conn.execute(
        f'''SELECT r.*, u.full_name AS created_by_name, d.full_name AS decided_by_name,
                  (SELECT COUNT(*) FROM purchase_request_items i WHERE i.request_id = r.id) AS item_count
           FROM purchase_requests r LEFT JOIN users u ON u.id = r.created_by LEFT JOIN users d ON d.id = r.decided_by
           WHERE {where} ORDER BY r.id DESC''', (*a1, *a2) if (date_from or date_to) else ()))
    for r in rows:
        r['status_label'] = REQ_STATUS.get(r['status'], r['status'])
    return rows


@router.post('/requests')
def create_request(body: RequestIn, user=Depends(buyer), conn=db.DB):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, 'Talep başlığı zorunlu')
    code = db.next_code(conn, 'purchase_requests', 'code', 'TL')
    rid = conn.execute('INSERT INTO purchase_requests (code, title, note, needed_by, created_by, created_at) VALUES (?,?,?,?,?,?)',
                       (code, title[:200], (body.note or '').strip()[:2000] or None, _date(body.needed_by, 'İhtiyaç tarihi'),
                        user['id'], db.now())).lastrowid
    db.audit(conn, user['id'], 'Satın alma talebi açtı', 'purchase_request', rid, f'{code} {title}')
    return {'id': rid, 'code': code}


@router.get('/requests/{rid}')
def get_request(rid: int, user=Depends(buyer), conn=db.DB):
    r = _request(conn, rid)
    r['invoices'] = db.rows(conn.execute(
        '''SELECT d.id, d.kind, d.number, d.doc_date, c.name AS company_name FROM material_docs d LEFT JOIN companies c ON c.id = d.company_id
           WHERE d.request_id = ? ORDER BY d.id''', (rid,)))
    r['can_approve'] = auth.ADMIN in user['roles']
    if r['created_by'] == user['id'] and r['status'] in ('ONAYLANDI', 'REDDEDILDI') and not r['seen_at']:
        conn.execute('UPDATE purchase_requests SET seen_at = ? WHERE id = ?', (db.now(), rid))
    return r


def _editable(conn, rid):
    r = db.row(conn.execute('SELECT * FROM purchase_requests WHERE id = ?', (rid,)))
    if not r:
        raise HTTPException(404, 'Talep bulunamadı')
    if r['status'] not in ('TASLAK', 'REDDEDILDI'):
        raise HTTPException(400, 'Onaya gönderilmiş talep değiştirilemez')
    return r


@router.put('/requests/{rid}')
def update_request(rid: int, body: RequestIn, user=Depends(buyer), conn=db.DB):
    _editable(conn, rid)
    if not body.title.strip():
        raise HTTPException(400, 'Talep başlığı zorunlu')
    conn.execute('UPDATE purchase_requests SET title = ?, note = ?, needed_by = ? WHERE id = ?',
                 (body.title.strip()[:200], (body.note or '').strip()[:2000] or None, _date(body.needed_by, 'İhtiyaç tarihi'), rid))
    return {'ok': True}


@router.post('/requests/{rid}/items')
def add_request_item(rid: int, body: RequestItemIn, user=Depends(buyer), conn=db.DB):
    _editable(conn, rid)
    _material(conn, body.product_id)
    if not 0 < body.qty <= 1e9:
        raise HTTPException(400, 'Talep miktarı 0’dan büyük olmalı')
    pos = conn.execute('SELECT COALESCE(MAX(pos), 0) + 1 FROM purchase_request_items WHERE request_id = ?', (rid,)).fetchone()[0]
    iid = conn.execute('INSERT INTO purchase_request_items (request_id, product_id, qty, note, pos) VALUES (?,?,?,?,?)',
                       (rid, body.product_id, round(body.qty, 4), (body.note or '').strip()[:500] or None, pos)).lastrowid
    return {'id': iid}


@router.put('/requests/{rid}/items/{iid}')
def update_request_item(rid: int, iid: int, body: RequestItemIn, user=Depends(buyer), conn=db.DB):
    _editable(conn, rid)
    _material(conn, body.product_id)
    if not 0 < body.qty <= 1e9:
        raise HTTPException(400, 'Talep miktarı 0’dan büyük olmalı')
    if not conn.execute('UPDATE purchase_request_items SET product_id = ?, qty = ?, note = ? WHERE id = ? AND request_id = ?',
                        (body.product_id, round(body.qty, 4), (body.note or '').strip()[:500] or None, iid, rid)).rowcount:
        raise HTTPException(404, 'Kalem bulunamadı')
    return {'ok': True}


@router.delete('/requests/{rid}/items/{iid}')
def delete_request_item(rid: int, iid: int, user=Depends(buyer), conn=db.DB):
    _editable(conn, rid)
    conn.execute('DELETE FROM purchase_request_items WHERE id = ? AND request_id = ?', (iid, rid))
    return {'ok': True}


@router.post('/requests/{rid}/submit')
def submit_request(rid: int, user=Depends(buyer), conn=db.DB):
    r = _editable(conn, rid)
    if not conn.execute('SELECT 1 FROM purchase_request_items WHERE request_id = ?', (rid,)).fetchone():
        raise HTTPException(400, 'Talebe en az bir kalem ekleyin')
    conn.execute("""UPDATE purchase_requests SET status = 'ONAY_BEKLIYOR', submitted_at = ?, decided_by = NULL, decided_at = NULL,
                    decision_note = NULL, seen_at = NULL WHERE id = ?""", (db.now(), rid))
    db.audit(conn, user['id'], 'Satın alma talebini onaya gönderdi', 'purchase_request', rid, r['code'])
    return {'ok': True}


def _admin(user=Depends(auth.current_user)):
    if auth.ADMIN not in user['roles']:
        raise HTTPException(403, 'Satın alma talebini Sistem Yöneticisi onaylar')
    return user


@router.post('/requests/{rid}/approve')
def approve_request(rid: int, body: DecisionIn, user=Depends(_admin), conn=db.DB):
    r = db.row(conn.execute('SELECT * FROM purchase_requests WHERE id = ?', (rid,)))
    if not r or r['status'] != 'ONAY_BEKLIYOR':
        raise HTTPException(400, 'Onay bekleyen talep bulunamadı')
    conn.execute("UPDATE purchase_requests SET status = 'ONAYLANDI', decided_by = ?, decided_at = ?, decision_note = ?, seen_at = NULL WHERE id = ?",
                 (user['id'], db.now(), (body.note or '').strip()[:1000] or None, rid))
    db.audit(conn, user['id'], 'Satın alma talebini onayladı', 'purchase_request', rid, r['code'])
    return {'ok': True}


@router.post('/requests/{rid}/reject')
def reject_request(rid: int, body: DecisionIn, user=Depends(_admin), conn=db.DB):
    r = db.row(conn.execute('SELECT * FROM purchase_requests WHERE id = ?', (rid,)))
    if not r or r['status'] != 'ONAY_BEKLIYOR':
        raise HTTPException(400, 'Onay bekleyen talep bulunamadı')
    note = (body.note or '').strip()
    if not note:
        raise HTTPException(400, 'Reddetme sebebini yazın')
    conn.execute("UPDATE purchase_requests SET status = 'REDDEDILDI', decided_by = ?, decided_at = ?, decision_note = ?, seen_at = NULL WHERE id = ?",
                 (user['id'], db.now(), note[:1000], rid))
    db.audit(conn, user['id'], 'Satın alma talebini reddetti', 'purchase_request', rid, note[:200])
    return {'ok': True}


@router.post('/requests/{rid}/cancel')
def cancel_request(rid: int, user=Depends(buyer), conn=db.DB):
    r = db.row(conn.execute('SELECT * FROM purchase_requests WHERE id = ?', (rid,)))
    if not r or r['status'] in ('TAMAMLANDI', 'IPTAL'):
        raise HTTPException(400, 'Bu talep iptal edilemez')
    conn.execute("UPDATE purchase_requests SET status = 'IPTAL' WHERE id = ?", (rid,))
    return {'ok': True}


# ---------- Fatura / irsaliye (depo girişi)

class InvoiceLine(BaseModel):
    product_id: int
    qty: float
    unit_price: Optional[float] = None


class InvoiceIn(BaseModel):
    kind: str                       # FATURA | IRSALIYE
    number: Optional[str] = None
    doc_date: Optional[str] = None
    company_id: Optional[int] = None
    amount: Optional[float] = None
    note: Optional[str] = None
    warehouse_id: Optional[int] = None
    request_id: Optional[int] = None
    lines: list[InvoiceLine]


def _invoice_lines(conn, did):
    return db.rows(conn.execute(
        '''SELECT m.id, m.product_id, m.qty, m.unit_price, p.code, p.name, p.type, p.unit, w.name AS warehouse_name
           FROM material_moves m JOIN products p ON p.id = m.product_id LEFT JOIN warehouses w ON w.id = m.warehouse_id
           WHERE m.doc_id = ? ORDER BY m.id''', (did,)))


@router.get('/invoices')
def invoices(date_from: str = '', date_to: str = '', user=Depends(buyer), conn=db.DB):
    dc, da = db.date_cond('COALESCE(d.doc_date, d.created_at)', date_from, date_to)
    rows = db.rows(conn.execute(
        '''SELECT d.*, c.name AS company_name, c.logo AS company_logo, w.name AS warehouse_name, r.code AS request_code,
                  u.full_name AS user_name FROM material_docs d
           LEFT JOIN companies c ON c.id = d.company_id LEFT JOIN warehouses w ON w.id = d.warehouse_id
           LEFT JOIN purchase_requests r ON r.id = d.request_id LEFT JOIN users u ON u.id = d.user_id
           WHERE ''' + dc + '''
           ORDER BY COALESCE(d.doc_date, substr(d.created_at, 1, 10)) DESC, d.id DESC''', da))
    for d in rows:
        d['lines'] = _invoice_lines(conn, d['id'])
        d['lines_total'] = round(sum((l['qty'] or 0) * (l['unit_price'] or 0) for l in d['lines']), 2)
    return rows


@router.post('/invoices')
def create_invoice(body: InvoiceIn, user=Depends(buyer), conn=db.DB):
    """Fatura / irsaliye ve kalemleri: her kalem seçilen depoya (varsayılan Ana Depo) stok girişi olur."""
    if body.kind not in ('FATURA', 'IRSALIYE'):
        raise HTTPException(400, 'Belge türü fatura ya da irsaliye olmalı')
    if not body.lines:
        raise HTTPException(400, 'En az bir kalem girin')
    supplier = _supplier(conn, body.company_id)
    wid = body.warehouse_id or conn.execute('SELECT id FROM warehouses WHERE active = 1 ORDER BY id LIMIT 1').fetchone()[0]
    if not conn.execute('SELECT 1 FROM warehouses WHERE id = ? AND active = 1', (wid,)).fetchone():
        raise HTTPException(400, 'Depo bulunamadı')
    if body.request_id:
        r = db.row(conn.execute('SELECT status FROM purchase_requests WHERE id = ?', (body.request_id,)))
        if not r or r['status'] not in ('ONAYLANDI', 'TAMAMLANDI'):
            raise HTTPException(400, 'Fatura yalnızca onaylanmış talebe bağlanır')
    for ln in body.lines:
        _material(conn, ln.product_id)
        if not 0 < ln.qty <= 1e9:
            raise HTTPException(400, 'Kalem miktarı 0’dan büyük olmalı')
        if ln.unit_price is not None and ln.unit_price < 0:
            raise HTTPException(400, 'Birim fiyat negatif olamaz')
    did = conn.execute(
        '''INSERT INTO material_docs (kind, number, doc_date, company_id, supplier, amount, note, user_id, created_at, request_id, warehouse_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (body.kind, (body.number or '').strip()[:60] or None, _date(body.doc_date, 'Belge tarihi') or date.today().isoformat(), supplier['id'],
         supplier['name'], body.amount, (body.note or '').strip()[:500] or None, user['id'], db.now(), body.request_id, wid)).lastrowid
    label = f'{"Fatura" if body.kind == "FATURA" else "İrsaliye"} {body.number or ""}'.strip()
    for ln in body.lines:
        add_move(conn, ln.product_id, wid, 'GIRIS', ln.qty, user['id'], unit_price=ln.unit_price, doc_id=did,
                 reason=f'{label} · {supplier["name"]}')
    if body.request_id:   # talebin tüm kalemleri geldiyse tamamlandı
        r = _request(conn, body.request_id)
        if r['items'] and all(i['received'] + 1e-9 >= i['qty'] for i in r['items']):
            conn.execute("UPDATE purchase_requests SET status = 'TAMAMLANDI' WHERE id = ?", (body.request_id,))
    db.audit(conn, user['id'], 'Fatura / irsaliye girdi (depo girişi)', 'material_doc', did, f'{label} · {len(body.lines)} kalem')
    return {'id': did}


@router.post('/invoices/{did}/file')
async def invoice_file(did: int, file: UploadFile = File(...), user=Depends(buyer), conn=db.DB):
    if not conn.execute('SELECT 1 FROM material_docs WHERE id = ?', (did,)).fetchone():
        raise HTTPException(404, 'Belge bulunamadı')
    path = await save_upload('mrp', file)
    conn.execute('UPDATE material_docs SET file = ?, file_name = ? WHERE id = ?', (path, (file.filename or 'belge')[:200], did))
    return {'file': path}


# ---------- Teklif Yönetimi

class QuoteIn(BaseModel):
    company_id: int
    title: str
    currency: str = 'TRY'
    vat_rate: float = 20
    valid_until: Optional[str] = None
    note: Optional[str] = None
    request_id: Optional[int] = None


class QuoteItemIn(BaseModel):
    product_id: Optional[int] = None
    description: Optional[str] = None
    qty: float
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    note: Optional[str] = None


class ReviseIn(BaseModel):
    reason: Optional[str] = None


class SentIn(BaseModel):
    sent_to: Optional[str] = None


class QuoteStatusIn(BaseModel):
    status: str


def _quote(conn, qid):
    q = db.row(conn.execute(
        '''SELECT q.*, c.name AS company_name, c.email AS company_email, c.logo AS company_logo, u.full_name AS created_by_name,
                  r.code AS request_code FROM quotes q LEFT JOIN companies c ON c.id = q.company_id LEFT JOIN users u ON u.id = q.created_by
           LEFT JOIN purchase_requests r ON r.id = q.request_id WHERE q.id = ?''', (qid,)))
    if not q:
        raise HTTPException(404, 'Teklif bulunamadı')
    q['items'] = db.rows(conn.execute(
        '''SELECT i.*, p.code AS product_code FROM quote_items i LEFT JOIN products p ON p.id = i.product_id
           WHERE i.quote_id = ? ORDER BY i.pos, i.id''', (qid,)))
    q['subtotal'] = round(sum((i['qty'] or 0) * (i['unit_price'] or 0) for i in q['items']), 2)
    q['vat'] = round(q['subtotal'] * (q['vat_rate'] or 0) / 100, 2)
    q['total'] = round(q['subtotal'] + q['vat'], 2)
    q['status_label'] = QUOTE_STATUS.get(q['status'], q['status'])
    return q


def _draft(conn, qid):
    q = db.row(conn.execute('SELECT * FROM quotes WHERE id = ?', (qid,)))
    if not q:
        raise HTTPException(404, 'Teklif bulunamadı')
    if q['status'] != 'TASLAK':
        raise HTTPException(400, 'Firmaya iletilmiş teklif değiştirilemez; önce revize edin')
    return q


@router.get('/quotes')
def quotes(date_from: str = '', date_to: str = '', user=Depends(buyer), conn=db.DB):
    # Açık teklifler (taslak / firmaya iletildi) her zaman; sonuçlananlar açıldığı döneme göre
    dc, da = db.date_cond('created_at', date_from, date_to)
    where = f"(status IN ('TASLAK', 'GONDERILDI') OR ({dc}))" if (date_from or date_to) else '1=1'
    rows = [_quote(conn, r[0]) for r in conn.execute(f'SELECT id FROM quotes WHERE {where} ORDER BY id DESC', da if (date_from or date_to) else ()).fetchall()]
    for q in rows:
        q['revision_count'] = conn.execute('SELECT COUNT(*) FROM quote_revisions WHERE quote_id = ?', (q['id'],)).fetchone()[0]
    return rows


def _quote_fields(conn, body):
    _supplier(conn, body.company_id)
    if not body.title.strip():
        raise HTTPException(400, 'Teklif konusu zorunlu')
    if body.currency not in ('TRY', 'USD', 'EUR'):
        raise HTTPException(400, 'Para birimi TRY, USD ya da EUR olmalı')
    if not 0 <= body.vat_rate <= 100:
        raise HTTPException(400, 'KDV oranı 0–100 olmalı')
    if body.request_id and not conn.execute('SELECT 1 FROM purchase_requests WHERE id = ?', (body.request_id,)).fetchone():
        raise HTTPException(400, 'Talep bulunamadı')
    return (body.company_id, body.title.strip()[:200], body.currency, body.vat_rate, _date(body.valid_until, 'Geçerlilik tarihi'),
            (body.note or '').strip()[:4000] or None, body.request_id)


@router.post('/quotes')
def create_quote(body: QuoteIn, user=Depends(buyer), conn=db.DB):
    f = _quote_fields(conn, body)
    code = db.next_code(conn, 'quotes', 'code', 'TK')
    qid = conn.execute('''INSERT INTO quotes (company_id, title, currency, vat_rate, valid_until, note, request_id, code, created_by, created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?)''', (*f, code, user['id'], db.now())).lastrowid
    if body.request_id:   # talepten açılan teklif: talebin kalemleri teklife aktarılır
        for n, i in enumerate(db.rows(conn.execute(
                '''SELECT i.product_id, i.qty, i.note, p.name, p.unit FROM purchase_request_items i JOIN products p ON p.id = i.product_id
                   WHERE i.request_id = ? ORDER BY i.pos, i.id''', (body.request_id,)))):
            conn.execute('INSERT INTO quote_items (quote_id, product_id, description, qty, unit, note, pos) VALUES (?,?,?,?,?,?,?)',
                         (qid, i['product_id'], i['name'], i['qty'], i['unit'], i['note'], n))
    db.audit(conn, user['id'], 'Teklif oluşturdu', 'quote', qid, f'{code} {body.title.strip()}')
    return {'id': qid, 'code': code}


@router.get('/quotes/{qid}')
def get_quote(qid: int, user=Depends(buyer), conn=db.DB):
    q = _quote(conn, qid)
    q['revisions'] = db.rows(conn.execute(
        '''SELECT r.id, r.revision, r.reason, r.created_at, u.full_name AS created_by_name FROM quote_revisions r
           LEFT JOIN users u ON u.id = r.created_by WHERE r.quote_id = ? ORDER BY r.revision DESC''', (qid,)))
    return q


@router.get('/quotes/{qid}/revisions/{rev_id}')
def get_revision(qid: int, rev_id: int, user=Depends(buyer), conn=db.DB):
    r = db.row(conn.execute('SELECT * FROM quote_revisions WHERE id = ? AND quote_id = ?', (rev_id, qid)))
    if not r:
        raise HTTPException(404, 'Revizyon bulunamadı')
    return {**json.loads(r['data']), 'revision_reason': r['reason'], 'revised_at': r['created_at']}


@router.put('/quotes/{qid}')
def update_quote(qid: int, body: QuoteIn, user=Depends(buyer), conn=db.DB):
    _draft(conn, qid)
    f = _quote_fields(conn, body)
    conn.execute('''UPDATE quotes SET company_id = ?, title = ?, currency = ?, vat_rate = ?, valid_until = ?, note = ?, request_id = ?,
                    updated_at = ? WHERE id = ?''', (*f, db.now(), qid))
    return {'ok': True}


def _item_fields(conn, body):
    desc = (body.description or '').strip()
    unit = (body.unit or '').strip()[:20] or None
    if body.product_id:
        m = _material(conn, body.product_id)
        desc = desc or m['name']
        unit = unit or m['unit']
    if not desc:
        raise HTTPException(400, 'Kalem açıklaması ya da malzeme seçin')
    if not 0 < body.qty <= 1e9:
        raise HTTPException(400, 'Miktar 0’dan büyük olmalı')
    if body.unit_price is not None and body.unit_price < 0:
        raise HTTPException(400, 'Birim fiyat negatif olamaz')
    return body.product_id, desc[:300], round(body.qty, 4), unit, body.unit_price, (body.note or '').strip()[:500] or None


@router.post('/quotes/{qid}/items')
def add_quote_item(qid: int, body: QuoteItemIn, user=Depends(buyer), conn=db.DB):
    _draft(conn, qid)
    pos = conn.execute('SELECT COALESCE(MAX(pos), 0) + 1 FROM quote_items WHERE quote_id = ?', (qid,)).fetchone()[0]
    iid = conn.execute('INSERT INTO quote_items (product_id, description, qty, unit, unit_price, note, quote_id, pos) VALUES (?,?,?,?,?,?,?,?)',
                       (*_item_fields(conn, body), qid, pos)).lastrowid
    return {'id': iid}


@router.put('/quotes/{qid}/items/{iid}')
def update_quote_item(qid: int, iid: int, body: QuoteItemIn, user=Depends(buyer), conn=db.DB):
    _draft(conn, qid)
    if not conn.execute('UPDATE quote_items SET product_id = ?, description = ?, qty = ?, unit = ?, unit_price = ?, note = ? WHERE id = ? AND quote_id = ?',
                        (*_item_fields(conn, body), iid, qid)).rowcount:
        raise HTTPException(404, 'Kalem bulunamadı')
    return {'ok': True}


@router.delete('/quotes/{qid}/items/{iid}')
def delete_quote_item(qid: int, iid: int, user=Depends(buyer), conn=db.DB):
    _draft(conn, qid)
    conn.execute('DELETE FROM quote_items WHERE id = ? AND quote_id = ?', (iid, qid))
    return {'ok': True}


@router.post('/quotes/{qid}/sent')
def mark_sent(qid: int, body: SentIn, user=Depends(buyer), conn=db.DB):
    """Firmaya iletildi (e-postayla gönderildi ya da elden / yazdırılarak): teklif kilitlenir."""
    q = _draft(conn, qid)
    if not conn.execute('SELECT 1 FROM quote_items WHERE quote_id = ?', (qid,)).fetchone():
        raise HTTPException(400, 'Teklife en az bir kalem ekleyin')
    conn.execute("UPDATE quotes SET status = 'GONDERILDI', sent_at = ?, sent_to = ? WHERE id = ?",
                 (db.now(), (body.sent_to or '').strip()[:200] or None, qid))
    db.audit(conn, user['id'], 'Teklifi firmaya iletti', 'quote', qid, f'{q["code"]} rev.{q["revision"]} → {body.sent_to or "—"}')
    return {'ok': True}


@router.post('/quotes/{qid}/status')
def set_quote_status(qid: int, body: QuoteStatusIn, user=Depends(buyer), conn=db.DB):
    q = db.row(conn.execute('SELECT * FROM quotes WHERE id = ?', (qid,)))
    if not q:
        raise HTTPException(404, 'Teklif bulunamadı')
    if body.status not in ('KABUL', 'RED') or q['status'] != 'GONDERILDI':
        raise HTTPException(400, 'Yalnızca firmaya iletilmiş teklif kabul / red olarak işaretlenir')
    conn.execute('UPDATE quotes SET status = ?, updated_at = ? WHERE id = ?', (body.status, db.now(), qid))
    return {'ok': True}


@router.post('/quotes/{qid}/revise')
def revise_quote(qid: int, body: ReviseIn, user=Depends(buyer), conn=db.DB):
    """Mevcut hâl revizyon olarak saklanır, revizyon numarası artar ve teklif yeniden düzenlenebilir (taslak) olur."""
    q = _quote(conn, qid)
    if q['status'] == 'TASLAK' and not q['sent_at']:
        raise HTTPException(400, 'Taslak teklif doğrudan düzenlenir; revizyon firmaya iletildikten sonra yapılır')
    snapshot = {k: q[k] for k in ('code', 'title', 'company_name', 'currency', 'vat_rate', 'valid_until', 'note', 'status', 'status_label',
                                  'revision', 'sent_at', 'sent_to', 'subtotal', 'vat', 'total')}
    snapshot['items'] = [{k: i[k] for k in ('product_code', 'description', 'qty', 'unit', 'unit_price', 'note')} for i in q['items']]
    conn.execute('INSERT INTO quote_revisions (quote_id, revision, data, reason, created_by, created_at) VALUES (?,?,?,?,?,?)',
                 (qid, q['revision'], json.dumps(snapshot, ensure_ascii=False), (body.reason or '').strip()[:500] or None, user['id'], db.now()))
    conn.execute("UPDATE quotes SET revision = revision + 1, status = 'TASLAK', sent_at = NULL, sent_to = NULL, updated_at = ? WHERE id = ?",
                 (db.now(), qid))
    db.audit(conn, user['id'], 'Teklifi revize etti', 'quote', qid, f'{q["code"]} rev.{q["revision"]} → rev.{q["revision"] + 1}')
    return {'revision': q['revision'] + 1}


# ---------- Bildirimler

def pending_approvals(conn):
    return db.rows(conn.execute("SELECT id, code, title FROM purchase_requests WHERE status = 'ONAY_BEKLIYOR' ORDER BY submitted_at"))


def decided_unseen(conn, user_id):
    return db.rows(conn.execute(
        "SELECT id, code, title, status FROM purchase_requests WHERE created_by = ? AND status IN ('ONAYLANDI', 'REDDEDILDI') AND seen_at IS NULL",
        (user_id,)))
