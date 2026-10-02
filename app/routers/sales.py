"""Satış Yönetimi (M21): firmalar için satış faturası oluşturma / düzenleme / yazdırma.

Faturalar ortak `invoices` tablosunda tutulur (kind='satis'). Elle oluşturulanlar source='manual' (düzenlenebilir);
Mikro ERP'den çekilen satış faturaları da listede görünür ama kilitlidir (source='mikro', yalnızca Mikro modülünden yönetilir).
"İstersen stoktan düş" seçeneği (reduce_stock) açıksa fatura satırları eşleşen malzemelerden stok çıkışı yapar.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, invoices

router = APIRouter(prefix='/api/sales')
sales_user = auth.require_module('sales')


class ItemIn(BaseModel):
    product_id: Optional[int] = None
    description: str = ''
    qty: float = 0
    unit: Optional[str] = None
    unit_price: float = 0
    vat_rate: float = invoices.VAT_DEFAULT


class InvoiceIn(BaseModel):
    company_id: int
    number: Optional[str] = None
    invoice_date: Optional[str] = None
    note: Optional[str] = None
    warehouse_id: Optional[int] = None
    reduce_stock: bool = False
    items: list[ItemIn]


def _next_number(conn):
    from datetime import date
    yr = date.today().year
    n = conn.execute("SELECT COUNT(*) FROM invoices WHERE kind = 'satis' AND source = 'manual' AND number LIKE ?",
                     (f'SF-{yr}-%',)).fetchone()[0]
    return f'SF-{yr}-{n + 1:04d}'


def _clean_items(items):
    out = []
    for it in items:
        desc = (it.description or '').strip()
        if not desc and not it.product_id:
            continue
        if (it.qty or 0) <= 0:
            raise HTTPException(400, 'Her satırda miktar 0’dan büyük olmalı')
        out.append({'product_id': it.product_id, 'description': desc, 'qty': it.qty, 'unit': it.unit,
                    'unit_price': it.unit_price, 'vat_rate': it.vat_rate})
    if not out:
        raise HTTPException(400, 'En az bir fatura satırı ekleyin')
    return out


@router.get('/warehouses')
def warehouses(user=Depends(sales_user), conn=db.DB):
    """Stoktan düşme seçeneği için etkin depolar (Satış kullanıcısı MRP'ye erişmeden görebilsin diye)."""
    return db.rows(conn.execute('SELECT id, name, code FROM warehouses WHERE active = 1 ORDER BY id'))


@router.get('/products')
def products(q: str = '', user=Depends(sales_user), conn=db.DB):
    """Fatura satırı için ürün/malzeme seçici."""
    like = f'%{q.strip()}%'
    return db.rows(conn.execute(
        '''SELECT id, code, name, unit, type, barcode, brand FROM products
           WHERE active = 1 AND (code LIKE ? OR name LIKE ? OR barcode LIKE ?)
           ORDER BY name LIMIT 300''', (like, like, like)))


@router.get('')
def list_invoices(q: str = '', date_from: str = '', date_to: str = '', user=Depends(sales_user), conn=db.DB):
    dc, da = db.date_cond('COALESCE(i.invoice_date, i.created_at)', date_from, date_to)
    rows = db.rows(conn.execute(
        '''SELECT i.id, i.number, i.invoice_date, i.company_id, i.company_name, i.source, i.total, i.subtotal,
                  i.vat_total, i.stock_applied, i.created_at, c.name AS company_current,
                  (SELECT COUNT(*) FROM invoice_items it WHERE it.invoice_id = i.id) AS line_count
           FROM invoices i LEFT JOIN companies c ON c.id = i.company_id
           WHERE i.kind = 'satis' AND ''' + dc + ''' ORDER BY COALESCE(i.invoice_date, i.created_at) DESC, i.id DESC''', da))
    ql = q.strip().lower()
    if ql:
        rows = [r for r in rows if ql in ((r['number'] or '') + ' ' + (r['company_name'] or '') + ' ' + (r['company_current'] or '')).lower()]
    return rows


@router.get('/{iid}')
def get_invoice(iid: int, user=Depends(sales_user), conn=db.DB):
    inv = db.row(conn.execute("SELECT * FROM invoices WHERE id = ? AND kind = 'satis'", (iid,)))
    if not inv:
        raise HTTPException(404, 'Fatura bulunamadı')
    inv['items'] = db.rows(conn.execute(
        '''SELECT it.*, p.code AS product_code FROM invoice_items it
           LEFT JOIN products p ON p.id = it.product_id WHERE it.invoice_id = ? ORDER BY it.id''', (iid,)))
    if inv['company_id']:
        inv['company'] = db.row(conn.execute('SELECT id, name, tax_office, tax_no, phone, email, address FROM companies WHERE id = ?', (inv['company_id'],)))
    return inv


@router.post('')
def create_invoice(body: InvoiceIn, user=Depends(sales_user), conn=db.DB):
    company = db.row(conn.execute('SELECT id, name FROM companies WHERE id = ?', (body.company_id,)))
    if not company:
        raise HTTPException(400, 'Firma bulunamadı')
    items = _clean_items(body.items)
    wid = None
    if body.reduce_stock:
        wid = body.warehouse_id or invoices.default_warehouse(conn)
        if not wid:
            raise HTTPException(400, 'Stoktan düşmek için bir depo gerekli; önce MRP’de depo tanımlayın')
    number = (body.number or '').strip() or _next_number(conn)
    iid = conn.execute('''INSERT INTO invoices (kind, source, is_return, number, company_id, company_name, invoice_date,
         warehouse_id, currency, stock_applied, created_by, created_at)
         VALUES ('satis','manual',0,?,?,?,?,?,'TRY',0,?,?)''',
         (number[:64], company['id'], company['name'][:200], (body.invoice_date or '').strip()[:10] or None, wid,
          user['id'], db.now())).lastrowid
    conn.execute('UPDATE invoices SET note = ? WHERE id = ?', ((body.note or '').strip()[:1000] or None, iid))
    invoices.save_items(conn, iid, items)
    if body.reduce_stock:
        invoices.apply_stock(conn, iid, user['id'])
    db.audit(conn, user['id'], 'Satış faturası oluşturdu', 'invoice', iid, f'{number} · {company["name"]}')
    return {'id': iid}


@router.put('/{iid}')
def update_invoice(iid: int, body: InvoiceIn, user=Depends(sales_user), conn=db.DB):
    inv = db.row(conn.execute("SELECT * FROM invoices WHERE id = ? AND kind = 'satis'", (iid,)))
    if not inv:
        raise HTTPException(404, 'Fatura bulunamadı')
    if inv['source'] != 'manual':
        raise HTTPException(400, 'Mikro’dan gelen fatura buradan düzenlenemez')
    company = db.row(conn.execute('SELECT id, name FROM companies WHERE id = ?', (body.company_id,)))
    if not company:
        raise HTTPException(400, 'Firma bulunamadı')
    items = _clean_items(body.items)
    invoices.revert_stock(conn, iid)   # önce eski stok etkisini geri al
    wid = None
    if body.reduce_stock:
        wid = body.warehouse_id or inv['warehouse_id'] or invoices.default_warehouse(conn)
        if not wid:
            raise HTTPException(400, 'Stoktan düşmek için bir depo gerekli')
    conn.execute('''UPDATE invoices SET number = ?, company_id = ?, company_name = ?, invoice_date = ?, warehouse_id = ?,
                    note = ?, updated_at = ? WHERE id = ?''',
                 ((body.number or '').strip()[:64] or inv['number'], company['id'], company['name'][:200],
                  (body.invoice_date or '').strip()[:10] or None, wid, (body.note or '').strip()[:1000] or None, db.now(), iid))
    invoices.save_items(conn, iid, items)
    if body.reduce_stock:
        invoices.apply_stock(conn, iid, user['id'])
    db.audit(conn, user['id'], 'Satış faturası düzenledi', 'invoice', iid, inv['number'] or str(iid))
    return {'ok': True}


@router.delete('/{iid}')
def delete_invoice(iid: int, user=Depends(sales_user), conn=db.DB):
    inv = db.row(conn.execute("SELECT * FROM invoices WHERE id = ? AND kind = 'satis'", (iid,)))
    if not inv:
        raise HTTPException(404, 'Fatura bulunamadı')
    if inv['source'] != 'manual':
        raise HTTPException(400, 'Mikro’dan gelen fatura buradan silinemez')
    invoices.revert_stock(conn, iid)
    conn.execute('DELETE FROM invoices WHERE id = ?', (iid,))
    db.audit(conn, user['id'], 'Satış faturası sildi', 'invoice', iid, inv['number'] or str(iid))
    return {'ok': True}
