"""Fatura ortak mantığı: Satış Yönetimi (elle satış faturası) ve Mikro ERP (alış/satış aktarımı) birlikte kullanır.

Stok yönü: alış = giriş (+), satış = çıkış (−); iade faturası yönü tersine çevirir.
Stok hareketi yalnızca satır yerel bir malzemeye (products) eşleşiyorsa ve bir depo seçiliyse uygulanır.
"""
from . import db

VAT_DEFAULT = 20.0
KINDS = ('alis', 'satis')


def line_totals(qty, unit_price, vat_rate):
    sub = round((qty or 0) * (unit_price or 0), 2)
    vat = round(sub * (vat_rate or 0) / 100, 2)
    return sub, vat


def compute(items):
    """items: qty, unit_price, vat_rate alanlı sözlükler. (subtotal, vat_total, total) döner (KDV hariç / KDV / toplam)."""
    subtotal = vat = 0.0
    for it in items:
        s, v = line_totals(it.get('qty'), it.get('unit_price'), it.get('vat_rate', VAT_DEFAULT))
        subtotal += s
        vat += v
    subtotal = round(subtotal, 2)
    vat = round(vat, 2)
    return subtotal, vat, round(subtotal + vat, 2)


def map_product(conn, stok_code):
    """Mikro stok kodunu yerel malzemeye (products.id) eşler: önce mikro_links (senkronlanmış), sonra kod eşleşmesi."""
    if not stok_code:
        return None
    r = conn.execute("SELECT local_id FROM mikro_links WHERE kind = 'stok' AND mikro_code = ?", (stok_code,)).fetchone()
    if r and conn.execute('SELECT 1 FROM products WHERE id = ?', (r[0],)).fetchone():
        return r[0]
    for c in (stok_code, f'MK-{stok_code}'):
        r = conn.execute('SELECT id FROM products WHERE code = ? COLLATE NOCASE', (c,)).fetchone()
        if r:
            return r[0]
    return None


def stock_sign(kind, is_return):
    """Stok işaret çarpanı: alış +, satış −; iade yönü tersine çevirir."""
    base = 1 if kind == 'alis' else -1
    return base * (-1 if is_return else 1)


def default_warehouse(conn):
    r = conn.execute('SELECT id FROM warehouses WHERE active = 1 ORDER BY id LIMIT 1').fetchone()
    return r[0] if r else None


def apply_stock(conn, invoice_id, user_id):
    """Faturanın satırlarını stoğa işler (yalnızca eşleşen malzeme + depo). Zaten uygulanmışsa dokunmaz."""
    from .routers.mrp import add_move
    inv = db.row(conn.execute('SELECT * FROM invoices WHERE id = ?', (invoice_id,)))
    if not inv or inv['stock_applied']:
        return 0
    wid = inv['warehouse_id']
    if not wid:
        return 0
    sign = stock_sign(inv['kind'], inv['is_return'])
    kind_move = 'GIRIS' if sign > 0 else 'CIKIS'
    label = {'alis': 'alış faturası', 'satis': 'satış faturası'}[inv['kind']] + (' iadesi' if inv['is_return'] else '')
    applied = 0
    for it in db.rows(conn.execute('SELECT * FROM invoice_items WHERE invoice_id = ? AND product_id IS NOT NULL', (invoice_id,))):
        qty = sign * abs(it['qty'] or 0)
        if abs(qty) < 1e-9:
            continue
        mid = add_move(conn, it['product_id'], wid, kind_move, qty, user_id,
                       unit_price=it['unit_price'] or None, reason=f'Mikro {label}: {inv["number"] or inv["id"]}')
        conn.execute('UPDATE invoice_items SET move_id = ? WHERE id = ?', (mid, it['id']))
        applied += 1
    conn.execute('UPDATE invoices SET stock_applied = 1, updated_at = ? WHERE id = ?', (db.now(), invoice_id))
    return applied


def revert_stock(conn, invoice_id):
    """Faturanın uyguladığı stok hareketlerini geri alır (silme / yeniden aktarım öncesi)."""
    ids = [r[0] for r in conn.execute('SELECT move_id FROM invoice_items WHERE invoice_id = ? AND move_id IS NOT NULL', (invoice_id,))]
    for mid in ids:
        conn.execute('DELETE FROM material_moves WHERE id = ?', (mid,))
    conn.execute('UPDATE invoice_items SET move_id = NULL WHERE invoice_id = ?', (invoice_id,))
    conn.execute('UPDATE invoices SET stock_applied = 0, updated_at = ? WHERE id = ?', (db.now(), invoice_id))
    return len(ids)


def save_items(conn, invoice_id, items):
    """Fatura satırlarını (yeniden) yazar ve fatura toplamlarını günceller. items: description, qty, unit, unit_price,
    vat_rate, product_id, mikro_stok alanlı sözlükler."""
    conn.execute('DELETE FROM invoice_items WHERE invoice_id = ?', (invoice_id,))
    now = db.now()
    for it in items:
        sub, _ = line_totals(it.get('qty'), it.get('unit_price'), it.get('vat_rate', VAT_DEFAULT))
        conn.execute('''INSERT INTO invoice_items (invoice_id, product_id, mikro_stok, description, qty, unit, unit_price,
                        vat_rate, line_total, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                     (invoice_id, it.get('product_id'), it.get('mikro_stok'), (it.get('description') or '').strip()[:300] or '—',
                      round(it.get('qty') or 0, 4), (it.get('unit') or '').strip()[:16] or None,
                      round(it.get('unit_price') or 0, 4), round(it.get('vat_rate', VAT_DEFAULT), 2), sub, now))
    subtotal, vat, total = compute(items)
    conn.execute('UPDATE invoices SET subtotal = ?, vat_total = ?, total = ?, updated_at = ? WHERE id = ?',
                 (subtotal, vat, total, now, invoice_id))
    return subtotal, vat, total
