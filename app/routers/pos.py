"""Esnaf Kasa (POS): dokunmatik perakende satış. Satılık ürünleri (products.is_retail, sale_price) listeler;
peşin satışı kendi fatura kaydı (invoices source='pos') + stok düşümü (material_moves) + kasa tahsilatı (fin_txns)
olarak işler. Carisiz (perakende) satış; ödeme Nakit / Kart / Veresiye. Barkodla arama destekli."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, invoices

router = APIRouter(prefix='/api/pos')


def pos_user(user=Depends(auth.current_user)):
    if 'pos' not in user['modules']:
        raise HTTPException(403, 'Esnaf Kasa modülü bu firmada kapalı')
    return user


@router.get('/products')
def products(q: str = '', user=Depends(pos_user), conn=db.DB):
    """Satılık ürünler + fiyat + barkod + (varsa) stok. q: ad / kod / barkod araması."""
    qq = (q or '').strip()
    like = f'%{qq}%'
    return db.rows(conn.execute(
        '''SELECT p.id, p.code, p.name, p.barcode, p.unit, p.image, COALESCE(p.sale_price, 0) AS sale_price,
                  COALESCE((SELECT SUM(qty) FROM material_moves WHERE product_id = p.id), 0) AS stock
           FROM products p
           WHERE p.is_retail = 1 AND COALESCE(p.active, 1) = 1
             AND (? = '' OR p.name LIKE ? OR p.code LIKE ? OR COALESCE(p.barcode,'') LIKE ?)
           ORDER BY p.name LIMIT 300''', (qq, like, like, like)))


@router.get('/accounts')
def accounts(user=Depends(pos_user), conn=db.DB):
    """Tahsilatın yazılacağı kasa hesapları."""
    return db.rows(conn.execute("SELECT id, name FROM fin_accounts WHERE kind = 'kasa' ORDER BY name"))


class SaleItem(BaseModel):
    product_id: int
    qty: float = 1


class SaleIn(BaseModel):
    items: list[SaleItem] = []
    payment: str = 'Nakit'          # Nakit | Kart | Veresiye
    account_id: int | None = None   # Nakit/Kart tahsilatının yazılacağı kasa


def _pos_number(conn):
    y = date.today().year
    n = conn.execute("SELECT COUNT(*) FROM invoices WHERE source = 'pos' AND number LIKE ?", (f'POS-{y}-%',)).fetchone()[0]
    return f'POS-{y}-{n + 1:05d}'


@router.post('/sale')
def sale(body: SaleIn, user=Depends(pos_user), conn=db.DB):
    """Peşin satış: fatura (source='pos') + stok düşümü + (Veresiye değilse) kasa tahsilatı. Fiş verisi döner."""
    if not body.items:
        raise HTTPException(400, 'Sepet boş')
    items = []
    for it in body.items:
        p = db.row(conn.execute('SELECT id, name, unit, sale_price FROM products WHERE id = ? AND is_retail = 1', (it.product_id,)))
        if not p:
            raise HTTPException(400, 'Satılık ürün bulunamadı')
        if (it.qty or 0) <= 0:
            continue
        items.append({'product_id': p['id'], 'description': p['name'], 'qty': float(it.qty),
                      'unit': p['unit'] or 'Adet', 'unit_price': float(p['sale_price'] or 0), 'vat_rate': 20})
    if not items:
        raise HTTPException(400, 'Geçerli ürün yok')
    pay = body.payment if body.payment in ('Nakit', 'Kart', 'Veresiye') else 'Nakit'
    number = _pos_number(conn)
    wid = invoices.default_warehouse(conn)
    iid = conn.execute(
        '''INSERT INTO invoices (kind, source, number, company_name, invoice_date, warehouse_id, currency, stock_applied, created_by, created_at)
           VALUES ('satis','pos',?,?,?,?,'TRY',0,?,?)''',
        (number, 'Perakende Satış', db.now()[:10], wid, user['id'], db.now())).lastrowid
    sub, vat, total = invoices.save_items(conn, iid, items)
    if wid:
        try:
            invoices.apply_stock(conn, iid, user['id'])   # stoktan düş (ürün stoğu takip ediliyorsa)
        except Exception:   # noqa: BLE001 — stok yoksa/izlenmiyorsa satış yine de geçsin
            pass
    if pay != 'Veresiye' and body.account_id:
        conn.execute(
            '''INSERT INTO fin_txns (account_id,date,direction,amount,currency,category,description,doc_no,created_by,created_at)
               VALUES (?,?,?,?,'TRY',?,?,?,?,?)''',
            (body.account_id, db.now()[:10], 'in', round(total, 2), f'POS {pay}',
             f'Yazarkasa satışı {number}', number, user['id'], db.now()))
    conn.commit()
    db.audit(conn, user['id'], 'Yazarkasa satışı', 'invoice', iid, f'{number} · {round(total, 2)} ₺ · {pay}')
    return {'id': iid, 'number': number, 'subtotal': round(sub, 2), 'vat': round(vat, 2), 'total': round(total, 2), 'payment': pay}


# ---------- Satılık ürün yönetimi (POS'a özel; basit perakende ürün) ----------
class ProductIn(BaseModel):
    name: str
    barcode: str = ''
    sale_price: float = 0
    unit: str = 'Adet'
    stock: float = 0   # yeni üründe açılış stoğu


@router.get('/catalog')
def catalog(user=Depends(pos_user), conn=db.DB):
    """Satılık ürünler (düzenleme listesi): ad, barkod, fiyat, birim, stok."""
    return db.rows(conn.execute(
        '''SELECT p.id, p.name, p.barcode, p.unit, COALESCE(p.sale_price, 0) AS sale_price,
                  COALESCE((SELECT SUM(qty) FROM material_moves WHERE product_id = p.id), 0) AS stock
           FROM products p WHERE p.is_retail = 1 AND COALESCE(p.active, 1) = 1 ORDER BY p.name'''))


@router.post('/product')
def add_product(body: ProductIn, user=Depends(pos_user), conn=db.DB):
    name = (body.name or '').strip()[:200]
    if not name:
        raise HTTPException(400, 'Ürün adı gerekli')
    import time as _t
    code = f'PRK{int(_t.time() * 1000)}'
    conn.execute(
        '''INSERT INTO products (code, name, serial, schema, queue_prefix, type, active, created_at, is_retail, sale_price, barcode, unit)
           VALUES (?,?,?,'','','MAMUL',1,?,1,?,?,?)''',
        (code, name, code, db.now(), round(body.sale_price or 0, 2),
         (body.barcode or '').strip()[:64] or None, (body.unit or 'Adet').strip()[:16] or 'Adet'))
    pid = conn.execute('SELECT id FROM products WHERE code = ?', (code,)).fetchone()[0]
    if (body.stock or 0) > 0:
        from .mrp import add_move
        wid = invoices.default_warehouse(conn)
        if wid:
            add_move(conn, pid, wid, 'GIRIS', float(body.stock), user['id'], reason='POS açılış stoğu')
    conn.commit()
    db.audit(conn, user['id'], 'POS ürünü ekledi', 'product', pid, name)
    return {'id': pid}


@router.put('/product/{pid}')
def edit_product(pid: int, body: ProductIn, user=Depends(pos_user), conn=db.DB):
    name = (body.name or '').strip()[:200]
    if not name:
        raise HTTPException(400, 'Ürün adı gerekli')
    if not conn.execute(
            'UPDATE products SET name = ?, sale_price = ?, barcode = ?, unit = ? WHERE id = ? AND is_retail = 1',
            (name, round(body.sale_price or 0, 2), (body.barcode or '').strip()[:64] or None,
             (body.unit or 'Adet').strip()[:16] or 'Adet', pid)).rowcount:
        raise HTTPException(404, 'Ürün bulunamadı')
    conn.commit()
    return {'ok': True}


class StockIn(BaseModel):
    qty: float = 0
    mode: str = 'set'   # 'set' (bu değere getir) | 'add' (ekle)


@router.post('/product/{pid}/stock')
def set_stock(pid: int, body: StockIn, user=Depends(pos_user), conn=db.DB):
    if not db.row(conn.execute('SELECT id FROM products WHERE id = ? AND is_retail = 1', (pid,))):
        raise HTTPException(404, 'Ürün bulunamadı')
    cur = conn.execute('SELECT COALESCE(SUM(qty), 0) FROM material_moves WHERE product_id = ?', (pid,)).fetchone()[0]
    delta = body.qty if body.mode == 'add' else (body.qty - cur)
    if abs(delta) > 1e-9:
        from .mrp import add_move
        wid = invoices.default_warehouse(conn)
        if not wid:
            raise HTTPException(400, 'Depo tanımsız')
        add_move(conn, pid, wid, 'GIRIS' if delta > 0 else 'CIKIS', delta, user['id'], reason='POS stok düzeltme')
    conn.commit()
    return {'ok': True, 'stock': cur + delta}


@router.delete('/product/{pid}')
def del_product(pid: int, user=Depends(pos_user), conn=db.DB):
    conn.execute('UPDATE products SET is_retail = 0 WHERE id = ?', (pid,))
    conn.commit()
    return {'ok': True}


@router.get('/sales')
def recent_sales(limit: int = 30, user=Depends(pos_user), conn=db.DB):
    """Son yazarkasa satışları (gün sonu / iade için)."""
    return db.rows(conn.execute(
        '''SELECT id, number, total, invoice_date, created_at FROM invoices
           WHERE source = 'pos' ORDER BY id DESC LIMIT ?''', (max(1, min(limit, 100)),)))
