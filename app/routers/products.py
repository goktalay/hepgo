"""Ürün Yönetimi: mamul, yarı mamul, yedek parça ve hammadde kayıtları.

Tip (MAMUL / YARI_MAMUL / YEDEK_PARCA / HAMMADDE) etikettir; üretim davranışı şemadan gelir (CAYMAZ şemaları,
ana yapılar, basılı parçalar). Ürün Yönetimi'nden açılan ürünlerin şeması yoktur ('custom'); yapıları ürün ağacı
(iç içe yarı mamuller), reçete (yedek parça / hammadde miktarları), 2B üstten görünüm resmi ve G-code ile tanımlanır.
"""
import re
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import assembly3d, auth, bom, catalogs, config, db, files, semis, spares

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
    printed: Optional[bool] = None       # custom ürün: basılıp stokta tutulur (yerleşik sarf gibi) → baskı alanları + stok
    usage_type: Optional[str] = None     # mamul: TEK (tek kullanımlık, uçunca hurda) | COKLU (çoklu kullanım)
    print_file: Optional[str] = None     # yedek parça: yazıcıya verilen baskı dosyası (gcode adı)
    print_minutes: Optional[int] = None  # yedek parça: bir baskının süresi (dakika)
    per_print: Optional[int] = None      # yedek parça: bir baskıda üretilen adet
    usages: Optional[dict[int, int]] = None   # montaj sarfı: {yarı mamul id: o yarı mamulde kullanılan adet}
    type: Optional[str] = None           # yalnızca Ürün Yönetimi'nden açılan ürünlerde değiştirilebilir
    unit: Optional[str] = None           # yedek parça / hammadde birimi


class NewProductIn(BaseModel):
    code: str
    name: str
    type: str
    unit: Optional[str] = None


class BomIn(BaseModel):
    child_id: Optional[int] = None
    qty: float = 1


class RecipeIn(BaseModel):
    item_id: Optional[int] = None
    qty: float
    note: Optional[str] = None


class GcodeIn(BaseModel):
    upload_id: str


class AdjustIn(BaseModel):
    qty: int
    reason: str


def _enrich(conn, p):
    mod = catalogs.schema(p['schema'])
    p['schema_title'] = catalogs.SCHEMAS[p['schema']]['title']
    p['type_label'] = spares.TYPES.get(p['type'], p['type'])
    p['role'] = spares.role(p)
    p['stocked'] = spares.is_stocked(p)
    p['part_count'] = len(mod.part_ids())
    stats = conn.execute(
        '''SELECT COUNT(*), SUM(status IN ('TAMAMLANDI', 'HURDA')), SUM(status NOT IN ('SIPARIS', 'TAMAMLANDI', 'HURDA'))
           FROM orders WHERE product_id = ?''', (p['id'],)).fetchone()
    p['order_count'], p['completed_count'], p['wip_count'] = stats[0], stats[1] or 0, stats[2] or 0
    p['bom_count'] = conn.execute('SELECT COUNT(*) FROM product_bom WHERE parent_id = ?', (p['id'],)).fetchone()[0]
    p['recipe_count'] = conn.execute('SELECT COUNT(*) FROM product_recipe WHERE product_id = ?', (p['id'],)).fetchone()[0]
    p['used_in'] = bom.parents(conn, p['id'])   # ürün ağacında üstleri
    if p['type'] in (spares.SPARE, spares.RAW):   # reçetelerde kullanıldığı ürünler
        p['used_in_recipes'] = db.rows(conn.execute(
            '''SELECT p.id, p.code, p.name, p.type, r.qty FROM product_recipe r JOIN products p ON p.id = r.product_id
               WHERE r.item_id = ? ORDER BY p.id''', (p['id'],)))
    if p.get('parent_id'):
        p['parent'] = db.row(conn.execute('SELECT id, name, code, type FROM products WHERE id = ?', (p['parent_id'],)))
    if p['stocked']:
        p['part_spare'] = semis.is_part_spare(p)
        p['stock'] = spares.stock(conn, p['id'])
        if not p['part_spare']:   # montaj sarfı: kullanım adedi girilebilen ana yapılar
            p['semi_options'] = db.rows(conn.execute(
                "SELECT id, code, name FROM products WHERE schema LIKE 'semi-%' ORDER BY id"))
        p['usages'] = spares.usages(conn, p['id']) if not p['part_spare'] else []
    elif spares.is_section(p):
        info = semis.print_info(conn)
        p['print_minutes_total'] = sum(info.get(i, {}).get('print_minutes') or 0 for i in mod.part_ids())
        p['groups'] = {}
        for part in mod.build():
            name = mod.GROUPS.get(part['group'], part['group'])
            p['groups'][name] = p['groups'].get(name, 0) + 1
    elif p['role'] == 'mamul':
        p['semis'] = db.rows(conn.execute(
            "SELECT id, code, name, schema FROM products WHERE parent_id = ? AND schema LIKE 'semi-%' ORDER BY id", (p['id'],)))
        for s in p['semis']:
            s['part_count'] = len(catalogs.part_ids(s['schema']))
        info = semis.print_info(conn)
        p['print_minutes_total'] = sum(info.get(i, {}).get('print_minutes') or 0 for i in mod.part_ids())
        used = spares.per_product(conn, p['id'])   # ürün ağacı üzerinden toplam
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


GCODE_MODULES = {'products', 'production', 'printers', 'stock', 'warehouse'}


def _gcode_guard(user, name):
    return bool(GCODE_MODULES & set(user['modules']))


from ..files import FILE_GUARDS  # noqa: E402
FILE_GUARDS['gcode'] = _gcode_guard
FILE_GUARDS['products'] = _gcode_guard   # ürün resimleri (2B üstten görünüm)


@router.get('/previews')
def previews(user=Depends(auth.current_user), conn=db.DB):
    """Parça kodu → 3B görünüm yolu, önizleme resmi ve baskı bilgisi (Üretim, Yazıcı, Stok, Depo, Ürün kullanıcıları)."""
    if not _gcode_guard(user, ''):
        raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
    out = {}
    for r in db.rows(conn.execute('SELECT code, schema, gcode_preview, gcode_thumb, gcode_file, print_minutes FROM products WHERE gcode_preview IS NOT NULL')):
        item = {'preview': r['gcode_preview'], 'thumb': r['gcode_thumb'], 'file': r['gcode_file'], 'minutes': r['print_minutes']}
        out[r['code']] = item
        if r['schema'].startswith(semis.PART_PREFIX):
            out[r['schema'][len(semis.PART_PREFIX):]] = item
    return out


@router.get('/options')
def product_options(user=Depends(auth.current_user), conn=db.DB):
    """Ürün ağacı ve reçete seçimleri için hafif liste."""
    return db.rows(conn.execute('SELECT id, code, name, type, unit, active, schema FROM products ORDER BY type, code'))


CODE_RE = re.compile(r'[A-Z0-9ÇĞİÖŞÜ][A-Z0-9ÇĞİÖŞÜ._/-]{0,23}')


@router.post('')
def create_product(body: NewProductIn, user=Depends(products_admin), conn=db.DB):
    """Yeni mamul / yarı mamul / yedek parça / hammadde (kod, ad, tip); ayrıntısı ürün sayfasında girilir."""
    code, name = body.code.strip().upper(), body.name.strip()
    if not CODE_RE.fullmatch(code):
        raise HTTPException(400, 'Kod 1–24 karakter olmalı (harf, rakam, - _ . /)')
    if not name:
        raise HTTPException(400, 'Ad zorunlu')
    if body.type not in spares.TYPES:
        raise HTTPException(400, 'Geçersiz tip')
    if body.unit and body.unit not in bom.UNITS:
        raise HTTPException(400, 'Geçersiz birim')
    if conn.execute('SELECT 1 FROM products WHERE code = ? OR serial = ?', (code, code)).fetchone():
        raise HTTPException(400, 'Bu kod başka bir üründe kullanılıyor')
    pid = bom.create(conn, code, name[:200], body.type, body.unit)
    db.audit(conn, user['id'], 'Ürün ekledi', 'product', pid, f'{code} — {name} ({spares.TYPES[body.type]})')
    return {'id': pid}


@router.delete('/{pid}')
def delete_product(pid: int, user=Depends(products_admin), conn=db.DB):
    """Yalnızca Ürün Yönetimi'nden açılmış, siparişi olmayan ürün silinir (ağaç ve reçete bağlantılarıyla)."""
    p = _get(conn, pid)
    if p['schema'] != spares.CUSTOM:
        raise HTTPException(400, 'Şemadan türeyen ürün silinemez; pasifleştirin')
    if conn.execute('SELECT 1 FROM orders WHERE product_id = ?', (pid,)).fetchone():
        raise HTTPException(400, 'Siparişi olan ürün silinemez; pasifleştirin')
    conn.execute('DELETE FROM product_bom WHERE parent_id = ? OR child_id = ?', (pid, pid))
    conn.execute('DELETE FROM product_recipe WHERE product_id = ? OR item_id = ?', (pid, pid))
    conn.execute('DELETE FROM products WHERE id = ?', (pid,))
    db.audit(conn, user['id'], 'Ürünü sildi', 'product', pid, f'{p["code"]} — {p["name"]}')
    return {'ok': True}


@router.get('/{pid}')
def get_product(pid: int, user=Depends(auth.current_user), conn=db.DB):
    return _enrich(conn, _get(conn, pid))


@router.get('/{pid}/tree')
def product_tree(pid: int, user=Depends(auth.current_user), conn=db.DB):
    """Ürün ağacı: iç içe yarı mamuller ve adetleri."""
    _get(conn, pid)
    return semis.tree(conn, pid)


@router.get('/assembly3d/{schema_key}')
async def assembly(schema_key: str, user=Depends(auth.current_user)):
    """3B Montaj: parçaların G-code takım yolları uçaktaki yerlerine oturtulmuş tek dosya (ilk istekte hesaplanır, sonra önbellek)."""
    if schema_key not in catalogs.SCHEMAS:
        raise HTTPException(404, 'Şema bulunamadı')

    def run():
        with db.connect() as conn:
            meta = dict(assembly3d.build(conn, schema_key))
            meta['overrides'] = assembly3d.overrides(conn, schema_key)
            return meta
    return await run_in_threadpool(run)


class AssemblyOverridesIn(BaseModel):
    parts: dict = {}   # parça id → {'p': [x, y, z] mm, 'r': [x, y, z] derece} | None (otomatiğe dön)


@router.put('/assembly3d/{schema_key}/overrides')
def save_assembly_overrides(schema_key: str, body: AssemblyOverridesIn, user=Depends(products_admin), conn=db.DB):
    """3B Montaj düzenleyicisi: parçaların elle verilen konum / dönüş düzeltmeleri (otomatik yerleşimin üstüne)."""
    if schema_key not in catalogs.SCHEMAS:
        raise HTTPException(404, 'Şema bulunamadı')
    cur = assembly3d.save_overrides(conn, schema_key, body.parts)
    db.audit(conn, user['id'], '3B montaj yerleşimini düzenledi', 'product', None, f'{schema_key}: {len(body.parts)} parça')
    return {'overrides': cur}


@router.get('/{pid}/plane')
def product_plane(pid: int, user=Depends(auth.current_user), conn=db.DB):
    """Parça çizimi; her parçaya baskı dosyası ve süresi eklenir (ipuçları, yazıcı seçimi, kalan süre)."""
    key = _get(conn, pid)['schema']
    plane = catalogs.plane_json(key)
    plane['schema'] = key
    info = semis.print_info(conn)
    plane['parts'] = [{**part, **info.get(part['id'], {})} for part in plane['parts']]
    return plane


@router.put('/{pid}')
def update_product(pid: int, body: ProductIn, user=Depends(products_admin), conn=db.DB):
    p = _enrich(conn, _get(conn, pid))
    custom = p['schema'] == spares.CUSTOM
    name, serial = body.name.strip(), body.serial.strip()
    code, prefix = body.code.strip().upper(), body.queue_prefix.strip().upper()
    if not name or not serial:
        raise HTTPException(400, 'Ürün adı ve seri numarası zorunlu')
    # Basılıp stokta tutulur bayrağı (yalnız custom MAMUL/YARI_MAMUL) — işaretli custom ürün yerleşik sarf gibi davranır
    new_printed = bool(body.printed) if (custom and body.printed is not None) else bool(p.get('printed'))
    if custom and body.printed is not None and new_printed and (body.type or p['type']) not in (spares.MAMUL, spares.SEMI):
        raise HTTPException(400, 'Yalnız mamul ve yarı mamul basılıp stokta tutulabilir')
    stocked_eff = p['stocked'] or (custom and new_printed)
    if semis.is_part_spare(p):   # parça yedeği: kodu parça kodudur, değiştirilemez
        code, prefix = p['code'], p['queue_prefix']
    if custom:
        if not CODE_RE.fullmatch(code):
            raise HTTPException(400, 'Kod 1–24 karakter olmalı (harf, rakam, - _ . /)')
        if new_printed:   # basılı custom: yazdırma kuyruğu için kısa kuyruk öneki gerekir
            if not re.fullmatch(r'[A-Z0-9]{2,6}', prefix):
                raise HTTPException(400, 'Basılı ürün için kuyruk öneki 2–6 harf/rakam olmalı')
        else:
            prefix = p['queue_prefix']
    else:
        for label, v in (('Ürün kodu', code), ('Kuyruk öneki', prefix)):
            if not semis.is_part_spare(p) and not re.fullmatch(r'[A-Z0-9]{2,6}', v):
                raise HTTPException(400, f'{label} 2–6 harf/rakam olmalı')
    if p['order_count'] and (code != p['code'] or prefix != p['queue_prefix']):
        raise HTTPException(400, 'Siparişi olan ürünün kodu ve kuyruk öneki değiştirilemez')
    if conn.execute('SELECT 1 FROM products WHERE (code = ? OR serial = ?) AND id != ?', (code, serial, pid)).fetchone():
        raise HTTPException(400, 'Bu ürün kodu veya seri numarası başka bir üründe kullanılıyor')
    if not body.active and p['role'] == 'mamul' and conn.execute(
            "SELECT COUNT(*) FROM products WHERE active = 1 AND type = 'MAMUL' AND schema != 'custom' AND id != ?", (pid,)).fetchone()[0] == 0:
        raise HTTPException(400, 'En az bir aktif mamul kalmalı')
    conn.execute('''UPDATE products SET name = ?, serial = ?, code = ?, queue_prefix = ?, description = ?, active = ?
                    WHERE id = ?''', (name, serial, code, prefix, body.description, int(body.active), pid))
    if custom and body.type and body.type != p['type']:
        if body.type not in spares.TYPES:
            raise HTTPException(400, 'Geçersiz tip')
        conn.execute('UPDATE products SET type = ? WHERE id = ?', (body.type, pid))
    if body.unit is not None:
        if body.unit and body.unit not in bom.UNITS:
            raise HTTPException(400, 'Geçersiz birim')
        conn.execute('UPDATE products SET unit = ? WHERE id = ?', (body.unit or None, pid))
    if body.usage_type is not None and (body.type or p['type']) == spares.MAMUL:
        if body.usage_type not in ('TEK', 'COKLU'):
            raise HTTPException(400, 'Kullanım durumu tek kullanımlık ya da çoklu kullanım olmalı')
        conn.execute('UPDATE products SET usage_type = ? WHERE id = ?', (body.usage_type, pid))
    if body.orderable is not None:
        if body.orderable and spares.is_section(p):
            raise HTTPException(400, 'Bu yarı mamul CAYMAZ siparişinin montajında üretilir; ayrı iş emri açılmaz')
        # Ürün Yönetimi'nden açılan (custom) MAMUL ve YARI_MAMUL için iş emri açılabilir (ürün ağacı/reçeteyle üretilir).
        # Diğer custom türler (hammadde/yedek parça/sarf/demirbaş) satın alınır; iş emri açılmaz.
        if body.orderable and custom and (body.type or p['type']) not in (spares.MAMUL, spares.SEMI):
            raise HTTPException(400, 'Bu tür için iş emri açılamaz (yalnız mamul ve yarı mamul)')
        conn.execute('UPDATE products SET orderable = ? WHERE id = ?', (int(body.orderable), pid))
    if custom and body.printed is not None:
        conn.execute('UPDATE products SET printed = ? WHERE id = ?', (int(new_printed), pid))
    if stocked_eff:
        if body.print_minutes is not None and not 0 <= body.print_minutes <= 14 * 1440:
            raise HTTPException(400, 'Baskı süresi 0–14 gün arasında olmalı')
        conn.execute('UPDATE products SET print_file = ?, print_minutes = ? WHERE id = ?',
                     ((body.print_file or '').strip() or None, body.print_minutes or None, pid))
        if body.per_print is not None:
            if not 1 <= body.per_print <= 1000:
                raise HTTPException(400, 'Bir baskıda üretilen adet 1–1000 olmalı')
            conn.execute('UPDATE products SET per_print = ? WHERE id = ?', (body.per_print, pid))
        if body.usages is not None and not semis.is_part_spare(p):
            semi_ids = {r[0] for r in conn.execute("SELECT id FROM products WHERE schema LIKE 'semi-%'")}
            for semi_id, qty in body.usages.items():
                if semi_id not in semi_ids:
                    raise HTTPException(400, 'Kullanım yalnızca yarı mamullere (Sol Kanat, Sağ Kanat, Gövde, Elektronik) girilir')
                if not 0 <= qty <= 10000:
                    raise HTTPException(400, 'Kullanım adedi 0–10000 olmalı')
                if qty:
                    conn.execute('''INSERT INTO product_bom (parent_id, child_id, qty, pos) VALUES (?,?,?,1)
                                    ON CONFLICT(parent_id, child_id) DO UPDATE SET qty = excluded.qty''', (semi_id, pid, qty))
                else:
                    conn.execute('DELETE FROM product_bom WHERE parent_id = ? AND child_id = ?', (semi_id, pid))
    db.audit(conn, user['id'], 'Ürün bilgilerini düzenledi', 'product', pid, f'{name} ({serial})')
    return {'ok': True}


# ---------- Ürün ağacı (iç içe yarı mamuller)

def _qty(v):
    if not 0 < v <= 100000:
        raise HTTPException(400, 'Miktar 0’dan büyük olmalı')
    return round(v, 4)


@router.post('/{pid}/bom')
def bom_add(pid: int, body: BomIn, user=Depends(products_admin), conn=db.DB):
    parent, child = _get(conn, pid), _get(conn, body.child_id or 0)
    if parent['type'] not in (spares.MAMUL, spares.SEMI):
        raise HTTPException(400, 'Ürün ağacı yalnızca mamul ve yarı mamulde tutulur')
    if child['type'] != spares.SEMI:
        raise HTTPException(400, 'Ürün ağacına yarı mamul eklenir; yedek parça ve hammadde reçeteye eklenir')
    if bom.creates_cycle(conn, pid, child['id']):
        raise HTTPException(400, 'Bu ürün kendi alt ağacına eklenemez')
    if conn.execute('SELECT 1 FROM product_bom WHERE parent_id = ? AND child_id = ?', (pid, child['id'])).fetchone():
        raise HTTPException(400, 'Bu yarı mamul zaten ekli; adedini değiştirin')
    pos = conn.execute('SELECT COALESCE(MAX(pos), 0) + 1 FROM product_bom WHERE parent_id = ?', (pid,)).fetchone()[0]
    conn.execute('INSERT INTO product_bom (parent_id, child_id, qty, pos) VALUES (?,?,?,?)', (pid, child['id'], _qty(body.qty), pos))
    db.audit(conn, user['id'], 'Ürün ağacına ekledi', 'product', pid, f'{parent["code"]} ← {child["code"]} × {body.qty:g}')
    return {'ok': True}


@router.put('/{pid}/bom/{child_id}')
def bom_update(pid: int, child_id: int, body: BomIn, user=Depends(products_admin), conn=db.DB):
    if not conn.execute('UPDATE product_bom SET qty = ? WHERE parent_id = ? AND child_id = ?', (_qty(body.qty), pid, child_id)).rowcount:
        raise HTTPException(404, 'Ağaçta böyle bir bağlantı yok')
    db.audit(conn, user['id'], 'Ürün ağacı adedini değiştirdi', 'product', pid, f'{child_id} × {body.qty:g}')
    return {'ok': True}


@router.delete('/{pid}/bom/{child_id}')
def bom_remove(pid: int, child_id: int, user=Depends(products_admin), conn=db.DB):
    if not conn.execute('DELETE FROM product_bom WHERE parent_id = ? AND child_id = ?', (pid, child_id)).rowcount:
        raise HTTPException(404, 'Ağaçta böyle bir bağlantı yok')
    db.audit(conn, user['id'], 'Ürün ağacından çıkardı', 'product', pid, str(child_id))
    return {'ok': True}


# ---------- Reçete (yedek parça ve hammadde miktarları)

@router.get('/{pid}/recipe')
def recipe_get(pid: int, user=Depends(auth.current_user), conn=db.DB):
    _get(conn, pid)
    return {'items': bom.recipe(conn, pid), 'total': bom.recipe_total(conn, pid)}


@router.post('/{pid}/recipe')
def recipe_set(pid: int, body: RecipeIn, user=Depends(products_admin), conn=db.DB):
    """Reçeteye ekler ya da miktarını günceller."""
    p, item = _get(conn, pid), _get(conn, body.item_id or 0)
    if p['type'] not in (spares.MAMUL, spares.SEMI):
        raise HTTPException(400, 'Reçete yalnızca mamul ve yarı mamulde tutulur')
    if item['type'] not in (spares.SPARE, spares.RAW, spares.CONSUMABLE):
        raise HTTPException(400, 'Reçeteye yedek parça, hammadde veya sarf malzeme eklenir')
    pos = conn.execute('SELECT COALESCE(MAX(pos), 0) + 1 FROM product_recipe WHERE product_id = ?', (pid,)).fetchone()[0]
    conn.execute('''INSERT INTO product_recipe (product_id, item_id, qty, note, pos) VALUES (?,?,?,?,?)
                    ON CONFLICT(product_id, item_id) DO UPDATE SET qty = excluded.qty, note = excluded.note''',
                 (pid, item['id'], _qty(body.qty), (body.note or '').strip()[:200] or None, pos))
    db.audit(conn, user['id'], 'Reçeteyi düzenledi', 'product', pid, f'{item["code"]} = {body.qty:g} {item["unit"] or ""}')
    return {'ok': True}


@router.delete('/{pid}/recipe/{item_id}')
def recipe_remove(pid: int, item_id: int, user=Depends(products_admin), conn=db.DB):
    if not conn.execute('DELETE FROM product_recipe WHERE product_id = ? AND item_id = ?', (pid, item_id)).rowcount:
        raise HTTPException(404, 'Reçetede böyle bir kalem yok')
    db.audit(conn, user['id'], 'Reçeteden çıkardı', 'product', pid, str(item_id))
    return {'ok': True}


# ---------- Resim (2B üstten görünüm) ve G-code (3B)

@router.post('/{pid}/image')
async def image_upload(pid: int, file: UploadFile, user=Depends(products_admin), conn=db.DB):
    p = _get(conn, pid)
    path = await files.save_upload('products', file)
    conn.execute('UPDATE products SET image = ? WHERE id = ?', (path, pid))
    db.audit(conn, user['id'], 'Ürün resmini yükledi', 'product', pid, p['code'])
    return {'image': path}


@router.delete('/{pid}/image')
def image_remove(pid: int, user=Depends(products_admin), conn=db.DB):
    p = _get(conn, pid)
    conn.execute('UPDATE products SET image = NULL WHERE id = ?', (pid,))
    db.audit(conn, user['id'], 'Ürün resmini kaldırdı', 'product', pid, p['code'])
    return {'ok': True}


@router.post('/{pid}/gcode')
def gcode_upload(pid: int, body: GcodeIn, user=Depends(products_admin), conn=db.DB):
    """Parça parça yüklenen G-code ürüne bağlanır: dilimleyici bilgileri, önizleme ve 3B yol çıkarılır."""
    from .. import gcode
    p = _get(conn, pid)
    rel, _, original = files.take_upload(body.upload_id, user, 'gcode')
    src = config.UPLOAD_DIR / rel
    safe = re.sub(r'[\\/:*?"<>|]+', '_', Path(original).name).strip() or f'{p["code"]}.gcode'
    if not safe.lower().endswith('.gcode'):
        safe += '.gcode'
    dest = src.parent / safe
    other = conn.execute('SELECT 1 FROM products WHERE gcode_file = ? AND id != ?', (f'{gcode.FOLDER}/{safe}', pid)).fetchone()
    if other:   # aynı adlı dosya başka ürünün: üzerine yazılmaz
        dest = src.parent / f'{re.sub(r"[^A-Za-z0-9_-]+", "_", p["code"])}_{safe}'
    if dest.exists():
        dest.unlink()
    shutil.move(src, dest)
    try:
        meta = gcode.attach(conn, pid, dest)
    except Exception as err:   # bozuk / okunamayan dosya
        raise HTTPException(400, f'G-code okunamadı: {err}')
    db.audit(conn, user['id'], 'G-code yükledi', 'product', pid, f'{p["code"]}: {dest.name}')
    return {'ok': True, 'seconds': meta.get('seconds'), 'filament_g': meta.get('filament_g')}


@router.delete('/{pid}/gcode')
def gcode_remove(pid: int, user=Depends(products_admin), conn=db.DB):
    p = _get(conn, pid)
    conn.execute('UPDATE products SET gcode_file = NULL, gcode_meta = NULL, gcode_thumb = NULL, gcode_preview = NULL WHERE id = ?', (pid,))
    db.audit(conn, user['id'], 'G-code kaldırdı', 'product', pid, p['code'])
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
    """Sayım düzeltmesi: depo yöneticileri, MRP sorumlusu ve sistem yöneticisi (Ürün Yönetimi) stoğa ekler / düşer."""
    if not {'warehouse', 'products'} & set(user['modules']) and auth.MRP_LEAD not in user['roles']:
        raise HTTPException(403, 'Stok düzeltmesini yalnızca depo yöneticisi, MRP sorumlusu veya sistem yöneticisi yapabilir')
    p = _get(conn, pid)
    if not spares.is_stocked(p):
        raise HTTPException(400, 'Yalnızca stokta tutulan basılı parçaların stoğu düzeltilebilir')
    if body.qty == 0 or not body.reason.strip():
        raise HTTPException(400, 'Adet (sıfırdan farklı) ve açıklama zorunlu')
    spares.add_move(conn, pid, body.qty, f'Düzeltme: {body.reason.strip()[:200]}', user['id'])
    db.audit(conn, user['id'], 'Yedek parça stoğunu düzeltti', 'product', pid, f'{p["code"]} {body.qty:+d}: {body.reason.strip()}')
    return {'stock': spares.stock(conn, pid)}
