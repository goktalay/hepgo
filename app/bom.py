"""Ürün ağacı (product_bom) ve reçete (product_recipe).

Ürün ağacı: mamul / yarı mamul → alt yarı mamuller (iç içe), üst üründe kullanılan adetle. Mevcut CAYMAZ yapısı
(mamul → dört ana yapı → parçalar ve montaj sarfları) bir kez bu tabloya taşınır; sonrası Ürün Yönetimi'nden düzenlenir.
Montaj sarfının (KMH, BBK, KBK) stoktan düşülen adedi bu ağaçtan hesaplanır (spares.per_product).
Reçete: bir üründe doğrudan kullanılan yedek parça ve hammaddeler (miktar, hammaddenin birimiyle).
"""
import json

from . import db, spares

UNITS = ('adet', 'g', 'kg', 'm', 'cm', 'mm', 'lt', 'ml', 'm²', 'paket')


def children(conn):
    kids = {}
    for parent, child, qty, pos in conn.execute('SELECT parent_id, child_id, qty, pos FROM product_bom ORDER BY pos, child_id'):
        kids.setdefault(parent, []).append((child, qty))
    return kids


def creates_cycle(conn, parent_id, child_id):
    """child_id'nin alt ağacında parent_id var mı (ya da aynı ürün mü)?"""
    kids = children(conn)
    stack, seen = [child_id], set()
    while stack:
        n = stack.pop()
        if n == parent_id:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(c for c, _ in kids.get(n, []))
    return False


def tree(conn, root_id):
    """İç içe ürün ağacı. Düğüm: id, code, name, type, active, qty (üstte kullanılan), section (ana yapı),
    stok bilgisi (basılı parçalar), print_minutes (parçada kendi süresi, üst üründe altındaki parçaların toplamı)."""
    from .semis import SEMI_SECTIONS
    rows = {r['id']: r for r in db.rows(conn.execute(
        'SELECT id, code, name, type, schema, active, print_minutes, image, gcode_preview FROM products'))}
    kids = children(conn)
    recipe_n = dict(conn.execute('SELECT product_id, COUNT(*) FROM product_recipe GROUP BY product_id').fetchall())

    def node(pid, qty, seen):
        r = rows[pid]
        n = {k: r[k] for k in ('id', 'code', 'name', 'type', 'active')}
        n['qty'] = qty
        n['role'] = spares.role(r)
        n['has_image'], n['has_3d'] = bool(r['image']), bool(r['gcode_preview'])
        n['recipe_count'] = recipe_n.get(pid, 0)
        if spares.is_section(r) and r['code'] in SEMI_SECTIONS:
            n['section'] = SEMI_SECTIONS[r['code']]
        if spares.is_stocked(r):
            n['stock'] = spares.stock(conn, pid)
            n['part_spare'] = n['role'] == 'part'
        n['children'] = [node(c, q, seen | {c}) for c, q in kids.get(pid, []) if c in rows and c not in seen]
        n['print_minutes'] = r['print_minutes'] if n.get('part_spare') else (
            sum(c['print_minutes'] or 0 for c in n['children'] if c['role'] != 'sarf') if n['children'] else r['print_minutes'])
        return n
    return node(root_id, 1, {root_id}) if root_id in rows else None


def parents(conn, pid):
    return db.rows(conn.execute(
        '''SELECT p.id, p.code, p.name, p.type, b.qty FROM product_bom b JOIN products p ON p.id = b.parent_id
           WHERE b.child_id = ? ORDER BY p.id''', (pid,)))


def recipe(conn, pid):
    return db.rows(conn.execute(
        '''SELECT r.item_id, r.qty, r.note, p.code, p.name, p.type, p.unit, p.active FROM product_recipe r
           JOIN products p ON p.id = r.item_id WHERE r.product_id = ? ORDER BY r.pos, p.code''', (pid,)))


def recipe_total(conn, pid):
    """Ürünün ağacındaki tüm alt ürünlerin reçeteleri, ağaç adetleriyle çarpılarak toplanır (kendisi dahil)."""
    kids = children(conn)
    items = {}
    for r in db.rows(conn.execute('SELECT product_id, item_id, qty FROM product_recipe')):
        items.setdefault(r['product_id'], []).append((r['item_id'], r['qty']))
    total = {}

    def walk(p, mult, seen):
        for item, q in items.get(p, []):
            total[item] = total.get(item, 0) + q * mult
        for c, q in kids.get(p, []):
            if c not in seen:
                walk(c, q * mult, seen | {c})
    walk(pid, 1, {pid})
    if not total:
        return []
    info = {r['id']: r for r in db.rows(conn.execute(
        f"SELECT id, code, name, type, unit FROM products WHERE id IN ({','.join('?' * len(total))})", list(total)))}
    return sorted(({**info[i], 'item_id': i, 'qty': round(q, 3)} for i, q in total.items() if i in info),
                  key=lambda r: (r['type'], r['code']))


def migrate(conn):
    """(Bir kez) mevcut yapıyı yeni sisteme taşır:
    1. basılı yedek parçalar (parça yedekleri ve montaj sarfları) yarı mamul tipine geçer; davranışları aynı kalır,
    2. ürün ağacı: mamul → ana yapılar (parent_id), ana yapı → parçaları (şemadan), montaj sarfı kullanımları,
    3. reçete: G-code'u olan her parça için dilimleyicinin filament ağırlığı (hammadde: <malzeme> Filament, gram)."""
    from . import catalogs
    from .semis import PART_PREFIX
    conn.execute(f"UPDATE products SET type = 'YARI_MAMUL' WHERE {spares.STOCKED_SQL}")
    rows = db.rows(conn.execute('SELECT id, code, schema, type, parent_id, per_print, gcode_meta FROM products ORDER BY id'))
    by_schema = {r['schema']: r['id'] for r in rows}
    add = 'INSERT OR IGNORE INTO product_bom (parent_id, child_id, qty, pos) VALUES (?,?,?,?)'
    for r in rows:
        if spares.is_section(r):
            if r['parent_id']:
                conn.execute(add, (r['parent_id'], r['id'], 1, 0))
            if r['schema'] in catalogs.SCHEMAS:
                for part_id in catalogs.part_ids(r['schema']):
                    child = by_schema.get(f'{PART_PREFIX}{part_id}')
                    if child:
                        conn.execute(add, (r['id'], child, 1, 0))
    for parent, child, qty in conn.execute('SELECT parent_id, spare_id, qty FROM product_spares WHERE qty > 0').fetchall():
        conn.execute(add, (parent, child, qty, 1))
    # Reçete: filament (G-code bilgisinden); bir baskıda birden çok adet çıkıyorsa adet başına
    raw = {}
    for r in rows:
        try:
            meta = json.loads(r['gcode_meta'] or '{}')
        except ValueError:
            continue
        if not meta.get('filament_g'):
            continue
        material = (meta.get('material') or 'PLA').split(';')[0].strip().upper()[:12] or 'PLA'
        if material not in raw:
            code = f'HM-{"".join(ch for ch in material if ch.isalnum())[:8] or "FIL"}'
            row = conn.execute('SELECT id FROM products WHERE code = ?', (code,)).fetchone()
            raw[material] = row[0] if row else create(conn, code, f'{material} Filament', spares.RAW, unit='g',
                                                       description='3B yazıcı filamenti · reçetedeki miktar gramdır')
        conn.execute('INSERT OR IGNORE INTO product_recipe (product_id, item_id, qty, note, pos) VALUES (?,?,?,?,0)',
                     (r['id'], raw[material], round(meta['filament_g'] / (r['per_print'] or 1), 2), 'G-code (dilimleyici)'))


def create(conn, code, name, type_, unit=None, description=None):
    """Ürün Yönetimi'nden açılan ürün (şemasız). Seri no ve kuyruk öneki koddan türetilir; sipariş verilmez."""
    prefix = ''.join(ch for ch in code if ch.isalnum())[:6] or 'URN'
    return conn.execute(
        '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, orderable, usage_type, unit, created_at)
           VALUES (?,?,?,?,?,?,?,0,?,?,?)''',
        (code, name, code, description, spares.CUSTOM, prefix, type_, 'TEK' if type_ == spares.MAMUL else None,
         unit or ('adet' if type_ in (spares.SPARE, spares.RAW, spares.FIXTURE, spares.CONSUMABLE) else None), db.now())).lastrowid
