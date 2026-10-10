"""Garson (esnaf · lokanta/fastfood): masa yerleşim ekranı + kişi bazlı adisyon + masa birleştirme + hesap.

Masalar bölümlerden (shop_tables) gelir. Bir masaya adisyon açılır (shop_orders), kişi (seat) bazlı
kalemler eklenir (shop_order_items). İki masa geçici birleştirilebilir. Hesap alınca adisyon bir POS
satışına dönüşür (invoices source='pos' + stok düşümü + kasa tahsilatı); program ayarındaki zorunlu
bahşiş (tip) yüzdesi uygulanabilir.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, invoices

router = APIRouter(prefix='/api/waiter')


def waiter_user(user=Depends(auth.current_user)):
    if 'waiter' not in user['modules']:
        raise HTTPException(403, 'Garson modülü bu firmada kapalı')
    return user


def _order_total(conn, oid):
    r = conn.execute('SELECT COALESCE(SUM(qty * price), 0) FROM shop_order_items WHERE order_id = ?', (oid,)).fetchone()
    return round(r[0] or 0, 2)


@router.get('/floor')
def floor(user=Depends(waiter_user), conn=db.DB):
    """Bölümler + masalar + her masanın açık adisyon durumu (boş/dolu, kişi, tutar)."""
    secs = db.rows(conn.execute("SELECT * FROM shop_sections WHERE active = 1 AND kind = 'hall' ORDER BY sort, id"))
    tables = db.rows(conn.execute('SELECT * FROM shop_tables WHERE active = 1 ORDER BY sort, id'))
    orders = {o['table_id']: o for o in db.rows(conn.execute(
        "SELECT * FROM shop_orders WHERE status = 'OPEN' ORDER BY id"))}
    names = {u['id']: u['full_name'] for u in db.rows(conn.execute('SELECT id, full_name FROM users'))}
    for t in tables:
        o = orders.get(t['id'])
        t['waiter_name'] = names.get(t['waiter_id'])
        t['order'] = ({'id': o['id'], 'party': o['party'], 'total': _order_total(conn, o['id']),
                       'opened_at': o['opened_at'], 'merged_with': o['merged_with']} if o else None)
    by_sec = {}
    for t in tables:
        by_sec.setdefault(t['section_id'], []).append(t)
    for s in secs:
        s['tables'] = by_sec.get(s['id'], [])
    # bölümsüz masalar da görünsün
    loose = by_sec.get(None, [])
    return {'sections': secs, 'loose': loose}


@router.get('/menu')
def menu(user=Depends(waiter_user), conn=db.DB):
    """Satılık ürünler (lokanta menüsü): ad, fiyat, barkod."""
    return db.rows(conn.execute(
        '''SELECT id, name, barcode, unit, COALESCE(sale_price, 0) AS price
           FROM products WHERE is_retail = 1 AND COALESCE(active, 1) = 1 ORDER BY name LIMIT 500'''))


@router.get('/accounts')
def accounts(user=Depends(waiter_user), conn=db.DB):
    return db.rows(conn.execute("SELECT id, name FROM fin_accounts WHERE kind = 'kasa' ORDER BY name"))


class OpenIn(BaseModel):
    party: int = 1


@router.post('/table/{tid}/open')
def open_table(tid: int, body: OpenIn, user=Depends(waiter_user), conn=db.DB):
    t = db.row(conn.execute('SELECT * FROM shop_tables WHERE id = ? AND active = 1', (tid,)))
    if not t:
        raise HTTPException(404, 'Masa bulunamadı')
    ex = db.row(conn.execute("SELECT id FROM shop_orders WHERE table_id = ? AND status = 'OPEN'", (tid,)))
    if ex:
        return {'id': ex['id']}   # zaten açık
    oid = conn.execute(
        "INSERT INTO shop_orders (table_id, party, status, opened_by, opened_at) VALUES (?,?,'OPEN',?,?)",
        (tid, max(1, int(body.party or 1)), user['id'], db.now())).lastrowid
    conn.commit()
    return {'id': oid}


@router.get('/order/{oid}')
def get_order(oid: int, user=Depends(waiter_user), conn=db.DB):
    o = db.row(conn.execute('SELECT * FROM shop_orders WHERE id = ?', (oid,)))
    if not o:
        raise HTTPException(404, 'Adisyon bulunamadı')
    o['items'] = db.rows(conn.execute('SELECT * FROM shop_order_items WHERE order_id = ? ORDER BY seat, id', (oid,)))
    o['total'] = _order_total(conn, oid)
    # birleştirilmiş masalar
    merged = db.rows(conn.execute('SELECT id, table_id FROM shop_orders WHERE merged_with = ?', (oid,)))
    o['merged_orders'] = [m['id'] for m in merged]
    return o


class ItemIn(BaseModel):
    seat: int = 1
    product_id: Optional[int] = None
    name: str = ''
    qty: float = 1
    price: float = 0
    note: str = ''


@router.post('/order/{oid}/item')
def add_item(oid: int, body: ItemIn, user=Depends(waiter_user), conn=db.DB):
    o = db.row(conn.execute("SELECT * FROM shop_orders WHERE id = ? AND status = 'OPEN'", (oid,)))
    if not o:
        raise HTTPException(404, 'Açık adisyon bulunamadı')
    name, price = (body.name or '').strip()[:160], round(body.price or 0, 2)
    if body.product_id:
        p = db.row(conn.execute('SELECT name, COALESCE(sale_price,0) AS price FROM products WHERE id = ?', (body.product_id,)))
        if p:
            name = name or p['name']
            if not price:
                price = round(p['price'], 2)
    if not name:
        raise HTTPException(400, 'Ürün/kalem adı gerekli')
    iid = conn.execute(
        '''INSERT INTO shop_order_items (order_id, seat, product_id, name, qty, price, note, created_at)
           VALUES (?,?,?,?,?,?,?,?)''',
        (oid, max(1, int(body.seat or 1)), body.product_id, name, float(body.qty or 1), price,
         (body.note or '').strip()[:200], db.now())).lastrowid
    conn.commit()
    return {'id': iid}


@router.delete('/order/{oid}/item/{iid}')
def del_item(oid: int, iid: int, user=Depends(waiter_user), conn=db.DB):
    conn.execute('DELETE FROM shop_order_items WHERE id = ? AND order_id = ?', (iid, oid))
    conn.commit()
    return {'ok': True}


class MergeIn(BaseModel):
    other_table_id: int


@router.post('/order/{oid}/merge')
def merge_table(oid: int, body: MergeIn, user=Depends(waiter_user), conn=db.DB):
    """Başka bir masanın açık adisyonunu bu adisyona taşı (geçici birleşik masa)."""
    o = db.row(conn.execute("SELECT * FROM shop_orders WHERE id = ? AND status = 'OPEN'", (oid,)))
    if not o:
        raise HTTPException(404, 'Açık adisyon bulunamadı')
    other = db.row(conn.execute("SELECT * FROM shop_orders WHERE table_id = ? AND status = 'OPEN'", (body.other_table_id,)))
    if not other:
        # diğer masada adisyon yoksa sadece boş birleşim: aç ve işaretle
        conn.execute("INSERT INTO shop_orders (table_id, party, status, merged_with, opened_by, opened_at) VALUES (?,0,'OPEN',?,?,?)",
                     (body.other_table_id, oid, user['id'], db.now()))
        conn.commit()
        return {'ok': True}
    conn.execute('UPDATE shop_order_items SET order_id = ? WHERE order_id = ?', (oid, other['id']))
    conn.execute("UPDATE shop_orders SET status = 'MERGED', merged_with = ?, closed_at = ? WHERE id = ?",
                 (oid, db.now(), other['id']))
    conn.execute('UPDATE shop_orders SET party = party + ? WHERE id = ?', (other['party'] or 0, oid))
    conn.commit()
    db.audit(conn, user['id'], 'Masa birleştirdi', 'shop_order', oid, f'masa {body.other_table_id}')
    return {'ok': True}


def _tip_pct(conn):
    r = conn.execute("SELECT v FROM app_kv WHERE k = 'shop.tip_pct'").fetchone()
    try:
        return float(r[0]) if r and r[0] else 0.0
    except (TypeError, ValueError):
        return 0.0


class PayIn(BaseModel):
    account_id: Optional[int] = None
    payment: str = 'Nakit'        # Nakit | Kart | Veresiye
    tip_pct: Optional[float] = None


def _pos_number(conn):
    y = date.today().year
    n = conn.execute("SELECT COUNT(*) FROM invoices WHERE source = 'pos' AND number LIKE ?", (f'POS-{y}-%',)).fetchone()[0]
    return f'POS-{y}-{n + 1:05d}'


@router.post('/order/{oid}/pay')
def pay(oid: int, body: PayIn, user=Depends(waiter_user), conn=db.DB):
    """Hesabı al: adisyonu POS satışına çevir (fatura + stok + kasa tahsilatı), bahşiş uygula, masayı boşalt."""
    o = db.row(conn.execute("SELECT * FROM shop_orders WHERE id = ? AND status = 'OPEN'", (oid,)))
    if not o:
        raise HTTPException(404, 'Açık adisyon bulunamadı')
    rows = db.rows(conn.execute('SELECT * FROM shop_order_items WHERE order_id = ? ORDER BY seat, id', (oid,)))
    if not rows:
        raise HTTPException(400, 'Adisyon boş')
    items = [{'product_id': r['product_id'], 'description': r['name'], 'qty': float(r['qty']),
              'unit': 'Adet', 'unit_price': float(r['price']), 'vat_rate': 10} for r in rows]
    pay_m = body.payment if body.payment in ('Nakit', 'Kart', 'Veresiye') else 'Nakit'
    tip_pct = body.tip_pct if body.tip_pct is not None else _tip_pct(conn)
    number = _pos_number(conn)
    wid = invoices.default_warehouse(conn)
    iid = conn.execute(
        '''INSERT INTO invoices (kind, source, number, company_name, invoice_date, warehouse_id, currency, stock_applied, created_by, created_at)
           VALUES ('satis','pos',?,?,?,?,'TRY',0,?,?)''',
        (number, 'Lokanta Adisyon', db.now()[:10], wid, user['id'], db.now())).lastrowid
    sub, vat, total = invoices.save_items(conn, iid, items)
    if wid:
        try:
            invoices.apply_stock(conn, iid, user['id'])
        except Exception:   # noqa: BLE001 — stok izlenmiyorsa satış yine geçsin
            pass
    tip = round(total * (tip_pct or 0) / 100.0, 2)
    grand = round(total + tip, 2)
    if pay_m != 'Veresiye' and body.account_id:
        conn.execute(
            '''INSERT INTO fin_txns (account_id,date,direction,amount,currency,category,description,doc_no,created_by,created_at)
               VALUES (?,?,?,?,'TRY',?,?,?,?,?)''',
            (body.account_id, db.now()[:10], 'in', grand, f'POS {pay_m}',
             f'Lokanta adisyon {number}' + (f' (bahşiş {tip} ₺)' if tip else ''), number, user['id'], db.now()))
    # adisyonu ve birleşik masaları kapat
    conn.execute("UPDATE shop_orders SET status = 'PAID', closed_at = ? WHERE id = ? OR merged_with = ?",
                 (db.now(), oid, oid))
    conn.commit()
    db.audit(conn, user['id'], 'Lokanta adisyon ödendi', 'invoice', iid, f'{number} · {grand} ₺ · {pay_m}')
    return {'id': iid, 'number': number, 'subtotal': round(sub, 2), 'vat': round(vat, 2),
            'total': round(total, 2), 'tip': tip, 'grand': grand, 'payment': pay_m}
