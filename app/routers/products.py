"""Ürün Yönetimi: ürün tipleri (ör. CAYMAZ) ve parça şemaları.

Yeni ürün tipi (yeni uçak şeması) yazılım tarafında eklenir (bkz. app/catalogs.py); bu modül ürün
kayıtlarını listeler, bilgilerini düzenler ve şemayı önizletir.
"""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, catalogs, db, semis, spares

router = APIRouter(prefix='/api/products')
products_admin = auth.require_module('products')


class ProductIn(BaseModel):
    name: str
    serial: str
    code: str
    queue_prefix: str
    description: Optional[str] = None
    active: bool = True
    orderable: Optional[bool] = None     # sipariş verilebilir (yarı mamulde her zaman hayır)
    usage_type: Optional[str] = None     # mamul: TEK (tek kullanımlık, uçunca hurda) | COKLU (çoklu kullanım)
    print_file: Optional[str] = None     # yedek parça: yazıcıya verilen baskı dosyası (gcode adı)
    print_minutes: Optional[int] = None  # yedek parça: bir baskının süresi (dakika)
    per_print: Optional[int] = None      # yedek parça: bir baskıda üretilen adet
    usages: Optional[dict[int, int]] = None   # yedek parça: {yarı mamul id: o yarı mamulde kullanılan adet}


class AdjustIn(BaseModel):
    qty: int
    reason: str


def _enrich(conn, p):
    mod = catalogs.schema(p['schema'])
    p['schema_title'] = catalogs.SCHEMAS[p['schema']]['title']
    p['part_count'] = len(mod.part_ids())
    stats = conn.execute(
        '''SELECT COUNT(*), SUM(status IN ('TAMAMLANDI', 'HURDA')), SUM(status NOT IN ('SIPARIS', 'TAMAMLANDI', 'HURDA'))
           FROM orders WHERE product_id = ?''', (p['id'],)).fetchone()
    p['order_count'], p['completed_count'], p['wip_count'] = stats[0], stats[1] or 0, stats[2] or 0
    if p.get('parent_id'):
        p['parent'] = db.row(conn.execute('SELECT id, name, code, type FROM products WHERE id = ?', (p['parent_id'],)))
    if p['type'] == spares.SPARE:
        p['part_spare'] = semis.is_part_spare(p)
        p['stock'] = spares.stock(conn, p['id'])
        if p['part_spare']:   # parçayı içeren yarı mamuller (ortak parça: V1 ve V2)
            part_id = p['schema'][len(semis.PART_PREFIX):]
            p['used_in'] = [s for s in db.rows(conn.execute(
                "SELECT id, code, name, schema FROM products WHERE type = ? ORDER BY id", (semis.SEMI,)))
                if s['schema'] in catalogs.SCHEMAS and part_id in catalogs.part_ids(s['schema'])]
        if not p['part_spare']:   # kullanım adedi girilebilen yarı mamuller
            p['semi_options'] = db.rows(conn.execute(
                'SELECT id, code, name FROM products WHERE type = ? ORDER BY id', (semis.SEMI,)))
        p['usages'] = db.rows(conn.execute(
            '''SELECT ps.parent_id, ps.qty, pr.name AS parent_name FROM product_spares ps JOIN products pr ON pr.id = ps.parent_id
               WHERE ps.spare_id = ?''', (p['id'],)))
    elif p['type'] == semis.SEMI:
        info = semis.print_info(conn)
        p['print_minutes_total'] = sum(info.get(i, {}).get('print_minutes') or 0 for i in mod.part_ids())
        p['groups'] = {}
        for part in mod.build():
            name = mod.GROUPS.get(part['group'], part['group'])
            p['groups'][name] = p['groups'].get(name, 0) + 1
    else:
        p['semis'] = db.rows(conn.execute(
            "SELECT id, code, name, schema FROM products WHERE parent_id = ? AND type = ? ORDER BY id", (p['id'], semis.SEMI)))
        for s in p['semis']:
            s['part_count'] = len(catalogs.part_ids(s['schema']))
        info = semis.print_info(conn)
        p['print_minutes_total'] = sum(info.get(i, {}).get('print_minutes') or 0 for i in mod.part_ids())
        used = spares.per_product(conn, p['id'])   # yarı mamuller üzerinden toplam
        p['spares'] = [{**r, 'qty': used[r['spare_id']]} for r in db.rows(conn.execute(
            f"SELECT id AS spare_id, code, name FROM products WHERE id IN ({','.join('?' * len(used))}) ORDER BY id",
            list(used)))] if used else []
    return p


def _get(conn, pid):
    p = db.row(conn.execute('SELECT * FROM products WHERE id = ?', (pid,)))
    if not p:
        raise HTTPException(404, 'Ürün bulunamadı')
    return p


@router.get('')
def list_products(active_only: bool = False, user=Depends(auth.current_user), conn=db.DB):
    """Seçim listeleri (sipariş, stok) için tüm oturum açmış kullanıcılara açıktır."""
    sql = 'SELECT * FROM products' + (' WHERE active = 1' if active_only else '') + ' ORDER BY id'
    # şeması artık olmayan (katalogdan çıkarılmış) ürün listeyi bozmasın
    return [_enrich(conn, p) for p in db.rows(conn.execute(sql)) if p['schema'] in catalogs.SCHEMAS]


@router.get('/schemas')
def list_schemas(user=Depends(products_admin)):
    return [{'key': k, 'title': v['title'], 'part_count': len(v['module'].part_ids())} for k, v in catalogs.SCHEMAS.items()]


@router.get('/{pid}')
def get_product(pid: int, user=Depends(auth.current_user), conn=db.DB):
    return _enrich(conn, _get(conn, pid))


@router.get('/{pid}/tree')
def product_tree(pid: int, user=Depends(auth.current_user), conn=db.DB):
    """Ürün ağacı: mamul → yarı mamul → yedek parça."""
    _get(conn, pid)
    return semis.tree(conn, pid)


@router.get('/{pid}/plane')
def product_plane(pid: int, user=Depends(auth.current_user), conn=db.DB):
    """Parça çizimi; her parçaya baskı dosyası ve süresi eklenir (ipuçları, yazıcı seçimi, kalan süre)."""
    plane = catalogs.plane_json(_get(conn, pid)['schema'])
    info = semis.print_info(conn)
    plane['parts'] = [{**part, **info.get(part['id'], {})} for part in plane['parts']]
    return plane


@router.put('/{pid}')
def update_product(pid: int, body: ProductIn, user=Depends(products_admin), conn=db.DB):
    p = _enrich(conn, _get(conn, pid))
    name, serial = body.name.strip(), body.serial.strip()
    code, prefix = body.code.strip().upper(), body.queue_prefix.strip().upper()
    if not name or not serial:
        raise HTTPException(400, 'Ürün adı ve seri numarası zorunlu')
    if semis.is_part_spare(p):   # parça yedeği: kodu parça kodudur, değiştirilemez
        code, prefix = p['code'], p['queue_prefix']
    for label, v in (('Ürün kodu', code), ('Kuyruk öneki', prefix)):
        if not semis.is_part_spare(p) and not re.fullmatch(r'[A-Z0-9]{2,6}', v):
            raise HTTPException(400, f'{label} 2–6 harf/rakam olmalı')
    if p['order_count'] and (code != p['code'] or prefix != p['queue_prefix']):
        raise HTTPException(400, 'Siparişi olan ürünün kodu ve kuyruk öneki değiştirilemez')
    if conn.execute('SELECT 1 FROM products WHERE (code = ? OR serial = ?) AND id != ?', (code, serial, pid)).fetchone():
        raise HTTPException(400, 'Bu ürün kodu veya seri numarası başka bir üründe kullanılıyor')
    if not body.active and p['type'] == spares.MAMUL and conn.execute(
            "SELECT COUNT(*) FROM products WHERE active = 1 AND type = 'MAMUL' AND id != ?", (pid,)).fetchone()[0] == 0:
        raise HTTPException(400, 'En az bir aktif mamul kalmalı')
    conn.execute('''UPDATE products SET name = ?, serial = ?, code = ?, queue_prefix = ?, description = ?, active = ?
                    WHERE id = ?''', (name, serial, code, prefix, body.description, int(body.active), pid))
    if body.usage_type is not None and p['type'] == spares.MAMUL:
        if body.usage_type not in ('TEK', 'COKLU'):
            raise HTTPException(400, 'Kullanım durumu tek kullanımlık ya da çoklu kullanım olmalı')
        conn.execute('UPDATE products SET usage_type = ? WHERE id = ?', (body.usage_type, pid))
    if body.orderable is not None:
        if body.orderable and p['type'] == semis.SEMI:
            raise HTTPException(400, 'Yarı mamul için sipariş verilemez; CAYMAZ siparişinin montajında üretilir')
        conn.execute('UPDATE products SET orderable = ? WHERE id = ?', (int(body.orderable), pid))
    if p['type'] == spares.SPARE:
        if body.print_minutes is not None and not 0 <= body.print_minutes <= 14 * 1440:
            raise HTTPException(400, 'Baskı süresi 0–14 gün arasında olmalı')
        conn.execute('UPDATE products SET print_file = ?, print_minutes = ? WHERE id = ?',
                     ((body.print_file or '').strip() or None, body.print_minutes or None, pid))
        if body.per_print is not None:
            if not 1 <= body.per_print <= 1000:
                raise HTTPException(400, 'Bir baskıda üretilen adet 1–1000 olmalı')
            conn.execute('UPDATE products SET per_print = ? WHERE id = ?', (body.per_print, pid))
        if body.usages is not None and not semis.is_part_spare(p):
            semi_ids = {r[0] for r in conn.execute('SELECT id FROM products WHERE type = ?', (semis.SEMI,))}
            for semi_id, qty in body.usages.items():
                if semi_id not in semi_ids:
                    raise HTTPException(400, 'Kullanım yalnızca yarı mamullere (Sol Kanat, Sağ Kanat, Gövde, Elektronik) girilir')
                if not 0 <= qty <= 10000:
                    raise HTTPException(400, 'Kullanım adedi 0–10000 olmalı')
                if qty:
                    conn.execute('''INSERT INTO product_spares (parent_id, spare_id, qty) VALUES (?,?,?)
                                    ON CONFLICT(parent_id, spare_id) DO UPDATE SET qty = excluded.qty''', (semi_id, pid, qty))
                else:
                    conn.execute('DELETE FROM product_spares WHERE parent_id = ? AND spare_id = ?', (semi_id, pid))
    db.audit(conn, user['id'], 'Ürün bilgilerini düzenledi', 'product', pid, f'{name} ({serial})')
    return {'ok': True}


# ---------- Yedek parça stoğu

def _stock_reader(user=Depends(auth.current_user)):
    if not {'stock', 'products', 'orders', 'production', 'warehouse'} & set(user['modules']):
        raise HTTPException(403, 'Bu bilgiye erişim yetkiniz yok')
    return user


@router.get('/spares/summary')
def spare_summary(user=Depends(_stock_reader), conn=db.DB):
    return spares.summary(conn)


@router.get('/{pid}/moves')
def spare_moves(pid: int, user=Depends(_stock_reader), conn=db.DB):
    _get(conn, pid)
    return db.rows(conn.execute(
        """SELECT m.*, u.full_name AS user_name, o.code AS order_code FROM spare_moves m LEFT JOIN users u ON u.id = m.user_id
           LEFT JOIN orders o ON o.id = m.order_id WHERE m.spare_id = ? ORDER BY m.id DESC LIMIT 1000""", (pid,)))


@router.post('/{pid}/adjust')
def adjust_stock(pid: int, body: AdjustIn, user=Depends(auth.current_user), conn=db.DB):
    """Sayım düzeltmesi: depo yöneticileri ve sistem yöneticisi (Ürün Yönetimi) stoğa ekler / düşer."""
    if not {'warehouse', 'products'} & set(user['modules']):
        raise HTTPException(403, 'Stok düzeltmesini yalnızca depo yöneticisi veya sistem yöneticisi yapabilir')
    p = _get(conn, pid)
    if p['type'] != spares.SPARE:
        raise HTTPException(400, 'Yalnızca yedek parça stoğu düzeltilebilir')
    if body.qty == 0 or not body.reason.strip():
        raise HTTPException(400, 'Adet (sıfırdan farklı) ve açıklama zorunlu')
    spares.add_move(conn, pid, body.qty, f'Düzeltme: {body.reason.strip()[:200]}', user['id'])
    db.audit(conn, user['id'], 'Yedek parça stoğunu düzeltti', 'product', pid, f'{p["code"]} {body.qty:+d}: {body.reason.strip()}')
    return {'stock': spares.stock(conn, pid)}
