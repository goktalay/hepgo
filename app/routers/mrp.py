"""Malzeme İhtiyaç Planlaması (MRP): Malzeme Yönetimi (yedek parça ve hammadde), Depo Yönetimi (depolar ve
sorumluları); Yarı Mamül (eski Stok Yönetimi) ve Onay Yönetimi (eski Depo Yönetimi) alt modülleri kendi uçlarını kullanır.

Malzemeler Ürün Yönetimi'ndeki YEDEK_PARCA / HAMMADDE kayıtlarıdır (aynı tablo; reçetelerde kullanılır). Stok depo
başına hareketlerin toplamıdır (material_moves): giriş (fatura / irsaliyeyle), çıkış, transfer, sayım, kullanım (eritme),
hurda. Uçuş kaynaklı hurda: tek kullanımlık uçak hurdaya ayrılınca içindeki malzemeler (ürün reçetesi) sorulur;
hurda olanlar kayda geçer (depo stoğunu etkilemez), sağlam olanlar seçilen depoya geri kazanım olarak girer.
"""
import re
import secrets
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import auth, bom, db, spares
from ..files import FILE_GUARDS, KINDS, save_upload

router = APIRouter(prefix='/api/mrp')
mrp_user = auth.require_module('mrp')
TYPES = (spares.SPARE, spares.RAW, spares.FIXTURE, spares.CONSUMABLE)   # malzeme tipleri
KINDS_OUT = {'CIKIS': 'Çıkış', 'KULLANIM': 'Kullanım (eritme)', 'HURDA': 'Hurda'}
MOVE_LABELS = {'GIRIS': 'Giriş', 'CIKIS': 'Çıkış', 'TRANSFER': 'Transfer', 'SAYIM': 'Sayım düzeltmesi', 'KULLANIM': 'Kullanım (eritme)',
               'HURDA': 'Hurda', 'GERI_KAZANIM': 'Geri kazanım'}

KINDS['mrp'] = {'.pdf', '.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.xml', '.zip', '.doc', '.docx', '.xls', '.xlsx'}
FILE_GUARDS['mrp'] = lambda user, name: 'mrp' in user['modules'] or 'products' in user['modules']


def manager(user=Depends(mrp_user)):
    if not set(auth.MRP_MANAGERS) & set(user['roles']):
        raise HTTPException(403, 'Bu işlemi yalnızca depo yöneticisi, MRP sorumlusu ve sistem yöneticisi yapabilir')
    return user


# ---------- Depolar

class WarehouseIn(BaseModel):
    name: str
    code: Optional[str] = None
    location: Optional[str] = None
    responsible_id: Optional[int] = None
    note: Optional[str] = None
    active: bool = True


def _stock_by_warehouse(conn, product_id=None):
    where, args = ('WHERE warehouse_id IS NOT NULL' + (' AND product_id = ?' if product_id else '')), ((product_id,) if product_id else ())
    return db.rows(conn.execute(f'SELECT warehouse_id, product_id, SUM(qty) AS qty FROM material_moves {where} GROUP BY warehouse_id, product_id', args))


@router.get('/warehouses')
def warehouses(user=Depends(mrp_user), conn=db.DB):
    rows = db.rows(conn.execute(
        '''SELECT w.*, u.full_name AS responsible_name, u.photo AS responsible_photo FROM warehouses w
           LEFT JOIN users u ON u.id = w.responsible_id ORDER BY w.active DESC, w.id'''))
    stock = _stock_by_warehouse(conn)
    for w in rows:
        mine = [s for s in stock if s['warehouse_id'] == w['id'] and abs(s['qty']) > 1e-9]
        w['material_count'] = len(mine)
        w['move_count'] = conn.execute('SELECT COUNT(*) FROM material_moves WHERE warehouse_id = ?', (w['id'],)).fetchone()[0]
    return rows


def _warehouse_fields(conn, body, wid=None):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, 'Depo adı zorunlu')
    code = (body.code or '').strip().upper()[:12] or None
    if code and conn.execute('SELECT 1 FROM warehouses WHERE code = ? AND id IS NOT ?', (code, wid)).fetchone():
        raise HTTPException(400, 'Bu depo kodu kullanılıyor')
    if body.responsible_id and not conn.execute('SELECT 1 FROM users WHERE id = ? AND deleted_at IS NULL', (body.responsible_id,)).fetchone():
        raise HTTPException(400, 'Sorumlu kullanıcı bulunamadı')
    return (name[:80], code, (body.location or '').strip()[:200] or None, body.responsible_id or None,
            (body.note or '').strip()[:500] or None, int(body.active))


@router.post('/warehouses')
def add_warehouse(body: WarehouseIn, user=Depends(manager), conn=db.DB):
    f = _warehouse_fields(conn, body)
    wid = conn.execute('INSERT INTO warehouses (name, code, location, responsible_id, note, active, created_at) VALUES (?,?,?,?,?,?,?)',
                       (*f, db.now())).lastrowid
    db.audit(conn, user['id'], 'Depo ekledi', 'warehouse', wid, f[0])
    return {'id': wid}


@router.put('/warehouses/{wid}')
def update_warehouse(wid: int, body: WarehouseIn, user=Depends(manager), conn=db.DB):
    f = _warehouse_fields(conn, body, wid)
    if not conn.execute('UPDATE warehouses SET name = ?, code = ?, location = ?, responsible_id = ?, note = ?, active = ? WHERE id = ?',
                        (*f, wid)).rowcount:
        raise HTTPException(404, 'Depo bulunamadı')
    db.audit(conn, user['id'], 'Depoyu düzenledi', 'warehouse', wid, f[0])
    return {'ok': True}


@router.delete('/warehouses/{wid}')
def delete_warehouse(wid: int, user=Depends(manager), conn=db.DB):
    if conn.execute('SELECT 1 FROM material_moves WHERE warehouse_id = ?', (wid,)).fetchone():
        raise HTTPException(400, 'Hareketi olan depo silinemez; pasifleştirin')
    if not conn.execute('DELETE FROM warehouses WHERE id = ?', (wid,)).rowcount:
        raise HTTPException(404, 'Depo bulunamadı')
    return {'ok': True}


# ---------- Malzemeler (yedek parça / hammadde)

class MaterialNew(BaseModel):
    code: str
    name: str
    type: str
    unit: Optional[str] = None


class MaterialIn(BaseModel):
    code: str
    name: str
    type: str
    unit: Optional[str] = None
    barcode: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    min_stock: Optional[float] = None
    active: bool = True


class PhysicalIn(BaseModel):
    color: Optional[str] = None
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    depth_mm: Optional[float] = None
    weight_g: Optional[float] = None


def _material(conn, mid):
    m = db.row(conn.execute('SELECT * FROM products WHERE id = ?', (mid,)))
    if not m or m['type'] not in TYPES:
        raise HTTPException(404, 'Malzeme bulunamadı')
    return m


def _totals(conn):
    return dict(conn.execute('SELECT product_id, SUM(qty) FROM material_moves WHERE warehouse_id IS NOT NULL GROUP BY product_id').fetchall())


def _decorate(conn, m, totals=None, first_images=None):
    total = (totals if totals is not None else _totals(conn)).get(m['id'], 0) or 0
    m['stock'] = round(total, 3)
    m['critical'] = m['min_stock'] is not None and total < m['min_stock']
    m['type_label'] = spares.TYPES.get(m['type'])
    m['cover'] = m['image'] or (first_images or {}).get(m['id']) or (m['gcode_preview'][:-4] + '.png' if m['gcode_preview'] else None)
    return m


@router.get('/materials')
def materials(user=Depends(mrp_user), conn=db.DB):
    rows = db.rows(conn.execute(f"SELECT * FROM products WHERE type IN ({','.join('?' * len(TYPES))}) ORDER BY type DESC, code", TYPES))
    totals = _totals(conn)
    first = dict(conn.execute('SELECT product_id, path FROM material_images WHERE id IN (SELECT MIN(id) FROM material_images GROUP BY product_id)').fetchall())
    return [_decorate(conn, m, totals, first) for m in rows]


@router.post('/materials')
def create_material(body: MaterialNew, user=Depends(manager), conn=db.DB):
    from .products import CODE_RE
    code, name = body.code.strip().upper(), body.name.strip()
    if body.type not in TYPES:
        raise HTTPException(400, 'Malzeme tipi yedek parça, hammadde, demirbaş ya da sarf malzeme olmalı')
    if not CODE_RE.fullmatch(code):
        raise HTTPException(400, 'Stok kodu 1–24 karakter olmalı (harf, rakam, - _ . /)')
    if not name:
        raise HTTPException(400, 'Malzeme adı zorunlu')
    if body.unit and body.unit not in bom.UNITS:
        raise HTTPException(400, 'Geçersiz birim')
    if conn.execute('SELECT 1 FROM products WHERE code = ? OR serial = ?', (code, code)).fetchone():
        raise HTTPException(400, 'Bu stok kodu başka bir kayıtta kullanılıyor')
    mid = bom.create(conn, code, name[:200], body.type, body.unit)
    db.audit(conn, user['id'], 'Malzeme ekledi', 'product', mid, f'{code} — {name}')
    return {'id': mid}


@router.get('/materials/{mid}')
def material(mid: int, user=Depends(mrp_user), conn=db.DB):
    m = _decorate(conn, _material(conn, mid))
    m['images'] = db.rows(conn.execute(
        '''SELECT i.*, u.full_name AS user_name FROM material_images i LEFT JOIN users u ON u.id = i.user_id
           WHERE i.product_id = ? ORDER BY i.id''', (mid,)))
    stock = {s['warehouse_id']: s['qty'] for s in _stock_by_warehouse(conn, mid)}
    m['warehouses'] = [{**w, 'qty': round(stock.get(w['id'], 0) or 0, 3)} for w in db.rows(conn.execute(
        '''SELECT w.id, w.name, w.code, w.location, w.active, u.full_name AS responsible_name FROM warehouses w
           LEFT JOIN users u ON u.id = w.responsible_id ORDER BY w.active DESC, w.id'''))
        if w['active'] or stock.get(w['id'])]
    m['used_in'] = db.rows(conn.execute(
        '''SELECT p.id, p.code, p.name, p.type, r.qty FROM product_recipe r JOIN products p ON p.id = r.product_id
           WHERE r.item_id = ? ORDER BY p.id''', (mid,)))
    m['can_edit'] = bool(set(auth.MRP_MANAGERS) & set(user['roles']))
    return m


@router.put('/materials/{mid}')
def update_material(mid: int, body: MaterialIn, user=Depends(manager), conn=db.DB):
    from .products import CODE_RE
    m = _material(conn, mid)
    code, name = body.code.strip().upper(), body.name.strip()
    if not CODE_RE.fullmatch(code) or not name:
        raise HTTPException(400, 'Stok kodu ve malzeme adı zorunlu')
    if body.type not in TYPES:
        raise HTTPException(400, 'Malzeme tipi yedek parça, hammadde, demirbaş ya da sarf malzeme olmalı')
    if conn.execute('SELECT 1 FROM products WHERE (code = ? OR serial = ?) AND id != ?', (code, code, mid)).fetchone():
        raise HTTPException(400, 'Bu stok kodu başka bir kayıtta kullanılıyor')
    barcode = re.sub(r'\s+', '', body.barcode or '')[:64] or None
    if barcode and conn.execute('SELECT 1 FROM products WHERE barcode = ? AND id != ?', (barcode, mid)).fetchone():
        raise HTTPException(400, 'Bu barkod başka bir malzemede kullanılıyor')
    if body.unit and body.unit not in bom.UNITS:
        raise HTTPException(400, 'Geçersiz birim')
    if body.min_stock is not None and body.min_stock < 0:
        raise HTTPException(400, 'Kritik stok negatif olamaz')
    clean = lambda v, n: (v or '').strip()[:n] or None   # noqa: E731
    serial = code if m['schema'] == spares.CUSTOM else m['serial']
    conn.execute('''UPDATE products SET code = ?, serial = ?, name = ?, type = ?, unit = ?, barcode = ?, brand = ?, model = ?,
                    description = ?, min_stock = ?, active = ? WHERE id = ?''',
                 (code, serial, name[:200], body.type, body.unit or 'adet', barcode, clean(body.brand, 80), clean(body.model, 80),
                  clean(body.description, 2000), body.min_stock, int(body.active), mid))
    db.audit(conn, user['id'], 'Malzeme bilgilerini düzenledi', 'product', mid, f'{code} — {name}')
    return {'ok': True}


@router.put('/materials/{mid}/physical')
def update_physical(mid: int, body: PhysicalIn, user=Depends(manager), conn=db.DB):
    _material(conn, mid)
    for k in ('width_mm', 'height_mm', 'depth_mm', 'weight_g'):
        v = getattr(body, k)
        if v is not None and not 0 <= v <= 1e7:
            raise HTTPException(400, 'Ölçüler 0 ya da daha büyük olmalı')
    conn.execute('UPDATE products SET color = ?, width_mm = ?, height_mm = ?, depth_mm = ?, weight_g = ? WHERE id = ?',
                 ((body.color or '').strip()[:40] or None, body.width_mm, body.height_mm, body.depth_mm, body.weight_g, mid))
    return {'ok': True}


# Tanımlama resmi (products.image) ve resim galerisi
@router.post('/materials/{mid}/image')
async def set_cover(mid: int, file: UploadFile = File(...), user=Depends(manager), conn=db.DB):
    _material(conn, mid)
    path = await save_upload('products', file)
    conn.execute('UPDATE products SET image = ? WHERE id = ?', (path, mid))
    return {'image': path}


@router.delete('/materials/{mid}/image')
def remove_cover(mid: int, user=Depends(manager), conn=db.DB):
    _material(conn, mid)
    conn.execute('UPDATE products SET image = NULL WHERE id = ?', (mid,))
    return {'ok': True}


@router.post('/materials/{mid}/images')
async def add_images(mid: int, files: list[UploadFile] = File(...), user=Depends(manager), conn=db.DB):
    _material(conn, mid)
    if len(files) > 30:
        raise HTTPException(400, 'Bir seferde en fazla 30 resim')
    for f in files:
        path = await save_upload('products', f)
        conn.execute('INSERT INTO material_images (product_id, path, file_name, user_id, created_at) VALUES (?,?,?,?,?)',
                     (mid, path, (f.filename or 'resim')[:200], user['id'], db.now()))
    return {'ok': True, 'count': len(files)}


@router.delete('/materials/{mid}/images/{iid}')
def delete_image(mid: int, iid: int, user=Depends(manager), conn=db.DB):
    if not conn.execute('DELETE FROM material_images WHERE id = ? AND product_id = ?', (iid, mid)).rowcount:
        raise HTTPException(404, 'Resim bulunamadı')
    return {'ok': True}


# 3B: G-code (Ürün Yönetimi ile aynı işlem)
class GcodeIn(BaseModel):
    upload_id: str


@router.post('/materials/{mid}/gcode')
def gcode_upload(mid: int, body: GcodeIn, user=Depends(manager), conn=db.DB):
    from . import products
    _material(conn, mid)
    return products.gcode_upload(mid, products.GcodeIn(upload_id=body.upload_id), user=user, conn=conn)


@router.delete('/materials/{mid}/gcode')
def gcode_remove(mid: int, user=Depends(manager), conn=db.DB):
    from . import products
    _material(conn, mid)
    return products.gcode_remove(mid, user=user, conn=conn)


# ---------- Stok hareketleri

class MoveIn(BaseModel):
    kind: str                       # GIRIS | CIKIS | TRANSFER | SAYIM | KULLANIM | HURDA
    warehouse_id: int
    to_warehouse_id: Optional[int] = None
    qty: float                      # SAYIM'da sayılan adet
    unit_price: Optional[float] = None
    reason: Optional[str] = None
    doc_id: Optional[int] = None


def _moves(conn, where, args=()):
    rows = db.rows(conn.execute(
        f'''SELECT m.*, w.name AS warehouse_name, u.full_name AS user_name, o.code AS order_code, o.queue_no,
                   d.kind AS doc_kind, d.number AS doc_number, d.file AS doc_file, p.code AS product_code, p.name AS product_name, p.unit
            FROM material_moves m LEFT JOIN warehouses w ON w.id = m.warehouse_id LEFT JOIN users u ON u.id = m.user_id
            LEFT JOIN orders o ON o.id = m.order_id LEFT JOIN material_docs d ON d.id = m.doc_id JOIN products p ON p.id = m.product_id
            WHERE {where} ORDER BY m.id DESC LIMIT 2000''', args))
    for r in rows:
        r['kind_label'] = MOVE_LABELS.get(r['kind'], r['kind'])
    return rows


def depot_stock(conn, mid, wid):
    return conn.execute('SELECT COALESCE(SUM(qty), 0) FROM material_moves WHERE product_id = ? AND warehouse_id = ?', (mid, wid)).fetchone()[0]


def add_move(conn, mid, wid, kind, qty, user_id, **kw):
    cols = {'product_id': mid, 'warehouse_id': wid, 'kind': kind, 'qty': round(qty, 4), 'user_id': user_id, 'created_at': db.now(), **kw}
    return conn.execute(f'INSERT INTO material_moves ({", ".join(cols)}) VALUES ({",".join("?" * len(cols))})', tuple(cols.values())).lastrowid


@router.get('/materials/{mid}/moves')
def material_moves(mid: int, user=Depends(mrp_user), conn=db.DB):
    _material(conn, mid)
    return _moves(conn, 'm.product_id = ?', (mid,))


@router.post('/materials/{mid}/moves')
def create_move(mid: int, body: MoveIn, user=Depends(manager), conn=db.DB):
    m = _material(conn, mid)
    w = db.row(conn.execute('SELECT * FROM warehouses WHERE id = ?', (body.warehouse_id,)))
    if not w or not w['active']:
        raise HTTPException(400, 'Depoyu seçin')
    reason = (body.reason or '').strip()[:500] or None
    have = depot_stock(conn, mid, w['id'])
    if body.kind == 'SAYIM':
        if body.qty < 0:
            raise HTTPException(400, 'Sayılan adet negatif olamaz')
        delta = body.qty - have
        if abs(delta) < 1e-9:
            raise HTTPException(400, 'Sayım mevcut stokla aynı; düzeltme gerekmiyor')
        add_move(conn, mid, w['id'], 'SAYIM', delta, user['id'], reason=reason or f'Sayım: {have:g} → {body.qty:g}')
        return {'ok': True}
    if body.qty <= 0:
        raise HTTPException(400, 'Miktar 0’dan büyük olmalı')
    if body.kind == 'GIRIS':
        if body.doc_id and not conn.execute('SELECT 1 FROM material_docs WHERE id = ?', (body.doc_id,)).fetchone():
            raise HTTPException(400, 'Belge bulunamadı')
        add_move(conn, mid, w['id'], 'GIRIS', body.qty, user['id'], reason=reason, unit_price=body.unit_price, doc_id=body.doc_id)
        if body.doc_id:   # belgenin giriş deposu (Satın Alma › Fatura İrsaliye listesinde görünür)
            conn.execute('UPDATE material_docs SET warehouse_id = COALESCE(warehouse_id, ?) WHERE id = ?', (w['id'], body.doc_id))
    elif body.kind in KINDS_OUT or body.kind == 'TRANSFER':
        if body.qty > have + 1e-9:
            raise HTTPException(400, f'{w["name"]} deposunda yeterli stok yok (mevcut {have:g} {m["unit"] or "adet"})')
        if body.kind == 'TRANSFER':
            to = db.row(conn.execute('SELECT * FROM warehouses WHERE id = ? AND active = 1', (body.to_warehouse_id or 0,)))
            if not to or to['id'] == w['id']:
                raise HTTPException(400, 'Hedef depoyu seçin (kaynaktan farklı)')
            g = secrets.token_hex(6)
            add_move(conn, mid, w['id'], 'TRANSFER', -body.qty, user['id'], reason=reason or f'→ {to["name"]}', group_id=g)
            add_move(conn, mid, to['id'], 'TRANSFER', body.qty, user['id'], reason=reason or f'{w["name"]} →', group_id=g)
        else:
            if not reason:
                raise HTTPException(400, 'Açıklama zorunlu')
            add_move(conn, mid, w['id'], body.kind, -body.qty, user['id'], reason=reason)
    else:
        raise HTTPException(400, 'Geçersiz hareket türü')
    db.audit(conn, user['id'], f'Malzeme stok hareketi: {MOVE_LABELS[body.kind]}', 'product', mid, f'{m["code"]} {body.qty:g} · {w["name"]}')
    return {'ok': True, 'stock': depot_stock(conn, mid, w['id'])}


@router.get('/materials/{mid}/scrap')
def scrap_and_usage(mid: int, user=Depends(mrp_user), conn=db.DB):
    _material(conn, mid)
    return _moves(conn, "m.product_id = ? AND m.kind IN ('KULLANIM', 'HURDA', 'GERI_KAZANIM')", (mid,))


# ---------- Fatura / irsaliye

@router.post('/docs')
async def create_doc(kind: str = Form(...), number: str = Form(''), doc_date: str = Form(''), company_id: Optional[int] = Form(None),
                     supplier: str = Form(''), amount: Optional[float] = Form(None), note: str = Form(''),
                     file: Optional[UploadFile] = File(None), user=Depends(manager), conn=db.DB):
    if kind not in ('FATURA', 'IRSALIYE'):
        raise HTTPException(400, 'Belge türü fatura ya da irsaliye olmalı')
    if doc_date:
        try:
            date.fromisoformat(doc_date)
        except ValueError:
            raise HTTPException(400, 'Belge tarihi geçersiz')
    if company_id and not conn.execute('SELECT 1 FROM companies WHERE id = ?', (company_id,)).fetchone():
        raise HTTPException(400, 'Firma bulunamadı')
    path = await save_upload('mrp', file) if file and file.filename else None
    did = conn.execute('''INSERT INTO material_docs (kind, number, doc_date, company_id, supplier, amount, file, file_name, note, user_id, created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                       (kind, number.strip()[:60] or None, doc_date or None, company_id, supplier.strip()[:120] or None, amount, path,
                        (file.filename if path else None), note.strip()[:500] or None, user['id'], db.now())).lastrowid
    return {'id': did}


@router.get('/materials/{mid}/docs')
def material_docs(mid: int, user=Depends(mrp_user), conn=db.DB):
    _material(conn, mid)
    return db.rows(conn.execute(
        '''SELECT d.*, c.name AS company_name, SUM(m.qty) AS qty, MAX(m.unit_price) AS unit_price, w.name AS warehouse_name,
                  u.full_name AS user_name
           FROM material_docs d JOIN material_moves m ON m.doc_id = d.id LEFT JOIN companies c ON c.id = d.company_id
           LEFT JOIN warehouses w ON w.id = m.warehouse_id LEFT JOIN users u ON u.id = d.user_id
           WHERE m.product_id = ? GROUP BY d.id ORDER BY COALESCE(d.doc_date, d.created_at) DESC''', (mid,)))


@router.get('/companies')
def company_options(user=Depends(mrp_user), conn=db.DB):
    return db.rows(conn.execute('SELECT id, name FROM companies WHERE is_supplier = 1 AND active = 1 ORDER BY name'))   # tedarikçiler


# ---------- Uçuş kaynaklı hurda: hurdaya ayrılan uçağın malzemeleri

class ReviewItem(BaseModel):
    item_id: int
    qty: float
    result: str                     # HURDA | SAGLAM
    warehouse_id: Optional[int] = None


class ReviewIn(BaseModel):
    items: list[ReviewItem]


def _review_user(user=Depends(auth.current_user)):
    if not (set(auth.MRP_MANAGERS) | set(auth.FIELD_MANAGERS)) & set(user['roles']):
        raise HTTPException(403, 'Hurda malzeme değerlendirmesini saha sorumlusu, depo yöneticisi ya da sistem yöneticisi yapar')
    return user


def aircraft_materials(conn, order_id):
    o = db.row(conn.execute('SELECT id, code, queue_no, status, product_id, material_review_at FROM orders WHERE id = ?', (order_id,)))
    if not o:
        raise HTTPException(404, 'Uçak bulunamadı')
    o['items'] = [r for r in bom.recipe_total(conn, o['product_id']) if r['type'] in TYPES]
    return o


@router.get('/aircraft/{order_id}/materials')
def aircraft_review_get(order_id: int, user=Depends(_review_user), conn=db.DB):
    o = aircraft_materials(conn, order_id)
    o['warehouses'] = db.rows(conn.execute('SELECT id, name FROM warehouses WHERE active = 1 ORDER BY id'))
    return o


@router.post('/aircraft/{order_id}/review')
def aircraft_review(order_id: int, body: ReviewIn, user=Depends(_review_user), conn=db.DB):
    o = aircraft_materials(conn, order_id)
    if o['status'] != 'HURDA':
        raise HTTPException(400, 'Yalnızca hurdaya ayrılmış uçağın malzemeleri değerlendirilir')
    if o['material_review_at']:
        raise HTTPException(400, 'Bu uçağın malzemeleri zaten değerlendirildi')
    allowed = {i['item_id']: i['qty'] for i in o['items']}
    name = o['queue_no'] or o['code']
    for it in body.items:
        if it.item_id not in allowed:
            raise HTTPException(400, 'Uçağın reçetesinde olmayan malzeme')
        if it.qty <= 0:
            continue
        if it.result == 'HURDA':   # stoktan zaten çıkmış (montajda kullanıldı): yalnızca kayıt
            add_move(conn, it.item_id, None, 'HURDA', -it.qty, user['id'], reason=f'Uçuş kaynaklı hurda: {name}', source='UCUS', order_id=order_id)
        elif it.result == 'SAGLAM':
            if not it.warehouse_id or not conn.execute('SELECT 1 FROM warehouses WHERE id = ? AND active = 1', (it.warehouse_id,)).fetchone():
                raise HTTPException(400, 'Sağlam malzemenin gireceği depoyu seçin')
            add_move(conn, it.item_id, it.warehouse_id, 'GERI_KAZANIM', it.qty, user['id'], reason=f'Hurda uçaktan geri kazanım: {name}',
                     source='UCUS', order_id=order_id)
        else:
            raise HTTPException(400, 'Sonuç hurda ya da sağlam olmalı')
    conn.execute('UPDATE orders SET material_review_at = ? WHERE id = ?', (db.now(), order_id))
    db.audit(conn, user['id'], 'Hurda uçağın malzemelerini değerlendirdi', 'order', order_id, name)
    return {'ok': True}


def pending_reviews(conn):
    """Hurdaya ayrılmış, malzemeleri henüz değerlendirilmemiş uçaklar (reçetesinde malzeme olanlar)."""
    rows = db.rows(conn.execute(
        "SELECT o.id, o.code, o.queue_no, o.product_id FROM orders o WHERE o.status = 'HURDA' AND o.material_review_at IS NULL ORDER BY o.scrapped_at"))
    return [r for r in rows if any(i['type'] in TYPES for i in bom.recipe_total(conn, r['product_id']))]
