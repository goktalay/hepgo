"""Yarı mamuller (ürün tipi YARI_MAMUL) ve parça yedekleri: mamulün (CAYMAZ / CAYMAZ V2) ürün ağacı.

Yarı mamul: montajda birleştirilen dört ana yapı (Sol Kanat, Sağ Kanat, Gövde, Elektronik); içindeki parçalarla
birlikte mamulün şemasından türetilir (montaj bölümü = section, elektronik = elektronik katmanındaki parçalar).
Ayrı sipariş verilmez. Parça yedeği: şemadaki her parça bir yedek parça ürünüdür (şema part-<kod>); iki modelde
ortak olan parça tek üründür (aynı stok). Ağaçta yarı mamulün altındaki parçalar şemadan (üyelik) bulunur.
"""
import copy

from . import db
from . import plane as caymaz
from . import plane_v2

SEMI = 'YARI_MAMUL'
ELECTRONICS = 'ELEKTRONIK'

# kod: (montaj bölümü, ad)
SEMIS = {
    'SLK': ('SOL_KANAT', 'Sol Kanat'),
    'SGK': ('SAG_KANAT', 'Sağ Kanat'),
    'GVD': ('GOVDE', 'Gövde'),
    'ELK': (ELECTRONICS, 'Elektronik'),
}


def members(part, section):
    """Parça bu yarı mamule ait mi? (Elektronik: elektronik katmanı; diğerleri: montaj bölümü)"""
    return part['layer'] == 'electronics' if section == ELECTRONICS else part['section'] == section


class SemiSchema:
    """catalogs.SCHEMAS için mamul şemasının bir alt kümesi (plane.py ile aynı arayüz)."""
    GROUPS = caymaz.GROUPS
    ASSEMBLY_SECTIONS = {}
    ELECTRONICS_PARTS = {}

    def __init__(self, section, base=caymaz):
        self.section, self.base = section, base

    def build(self):
        return [p for p in self.base.build() if members(p, self.section)]

    def part_ids(self):
        return [p['id'] for p in self.build()]

    def plane_json(self):
        parts = self.build()
        if self.section == ELECTRONICS:
            parts = _stack(parts)
        pts = [q for p in parts for s in p['shapes'] for q in s['pts']]
        x0, y0 = min(q[0] for q in pts), min(q[1] for q in pts)
        x1, y1 = max(q[0] for q in pts), max(q[1] for q in pts)
        pad = 30
        return {'viewBox': [x0 - pad, y0 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad], 'groups': self.GROUPS,
                'sections': {}, 'parts': parts}


def _stack(parts):
    """Elektronik: en büyük parça (elektronik kat) yerinde kalır, diğerleri (K04) altına ortalanarak dizilir
    (montaj görünümüyle aynı yerleşim). Çizim için kopya üzerinde çalışır."""
    parts = sorted(copy.deepcopy(parts), key=lambda p: -p['area'])
    box = lambda p: (min(q[0] for s in p['shapes'] for q in s['pts']), min(q[1] for s in p['shapes'] for q in s['pts']),
                     max(q[0] for s in p['shapes'] for q in s['pts']), max(q[1] for s in p['shapes'] for q in s['pts']))
    x0, _, x1, top = box(parts[0])
    top += 40
    for p in parts[1:]:
        b = box(p)
        dx, dy = (x0 + x1) / 2 - (b[0] + b[2]) / 2, top - b[1]
        for s in p['shapes']:
            s['pts'] = [[x + dx, y + dy] for x, y in s['pts']]
            s['holes'] = [[h[0] + dx, h[1] + dy, *h[2:]] for h in s['holes']]
            s['slots'] = [[h[0] + dx, h[1] + dy, *h[2:]] for h in s['slots']]
            s['inner'] = [[[x + dx, y + dy] for x, y in line] for line in s.get('inner', [])]
        if p.get('label_at'):
            p['label_at'] = [p['label_at'][0] + dx, p['label_at'][1] + dy]
        top += b[3] - b[1] + 40
    return parts


class PartSchema:
    """Tek bir parçanın yedek parça şeması (parça ayrıca sipariş edilip stoğa basılabilir)."""
    GROUPS = caymaz.GROUPS
    ASSEMBLY_SECTIONS = {}
    ELECTRONICS_PARTS = {}

    def __init__(self, part_id, base=caymaz):
        self.part_id, self.base = part_id, base

    def build(self):
        return [p for p in self.base.build() if p['id'] == self.part_id]

    def part_ids(self):
        return [self.part_id]

    def plane_json(self):
        parts = copy.deepcopy(self.build())   # caymaz.build() önbellekli: paylaşılan nesneler değiştirilmez
        for p in parts:
            p['layer'] = 'body'   # tek parça: katman seçimi yok
        pts = [q for p in parts for s in p['shapes'] for q in s['pts']]
        x0, y0 = min(q[0] for q in pts), min(q[1] for q in pts)
        x1, y1 = max(q[0] for q in pts), max(q[1] for q in pts)
        pad = max(x1 - x0, y1 - y0) * 0.08 + 10
        return {'viewBox': [x0 - pad, y0 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad], 'groups': self.GROUPS,
                'sections': {}, 'parts': parts}


def semi_of(part, suffix=''):
    """Parçanın ait olduğu yarı mamulün kodu (V2 için suffix='2')."""
    return next(code for code, (sec, _) in SEMIS.items() if members(part, sec)) + suffix


def part_name(part):
    return part.get('name') or f'{caymaz.GROUPS.get(part["group"], part["group"])} {part["id"]}'


# Montaj sarfı yedek parçaların yarı mamul başına kullanımı (CAYMAZ başına toplam: KMH 1, BBK 68, KBK 6)
SPARE_USAGE = {
    'KMH': {'GVD': 1},
    'BBK': {'SLK': 27, 'SGK': 27, 'GVD': 14},
    'KBK': {'SLK': 3, 'SGK': 3},
}

PART_PREFIX = 'part-'
SCHEMAS = {f'semi-{code.lower()}': {'module': SemiSchema(sec), 'title': f'CAYMAZ {name} (yarı mamul)'}
           for code, (sec, name) in SEMIS.items()}
SCHEMAS.update({f'semi-v2-{code.lower()}': {'module': SemiSchema(sec, plane_v2), 'title': f'CAYMAZ V2 {name} (yarı mamul)'}
                for code, (sec, name) in SEMIS.items()})
SCHEMAS.update({f'{PART_PREFIX}{p["id"]}': {'module': PartSchema(p['id']), 'title': f'CAYMAZ parçası {p["id"]} (yedek parça)'}
                for p in caymaz.build()})
SCHEMAS.update({f'{PART_PREFIX}{p["id"]}': {'module': PartSchema(p['id'], plane_v2), 'title': f'CAYMAZ V2 parçası {p["id"]} (yedek parça)'}
                for p in plane_v2.build() if f'{PART_PREFIX}{p["id"]}' not in SCHEMAS})
# yarı mamul kodu → montaj bölümü (V2 yarı mamulleri kod sonunda 2: SLK2, SGK2, GVD2, ELK2)
SEMI_SECTIONS = {**{c: v[0] for c, v in SEMIS.items()}, **{f'{c}2': v[0] for c, v in SEMIS.items()}}


def is_part_spare(product):
    return (product.get('schema') or '').startswith(PART_PREFIX)


def seed(conn):
    """Dört yarı mamulü CAYMAZ'a bağlı olarak ekler (bir kez)."""
    parent = conn.execute("SELECT id FROM products WHERE code = 'CYZ'").fetchone()
    for code, (sec, name) in SEMIS.items():
        if conn.execute('SELECT 1 FROM products WHERE code = ?', (code,)).fetchone():
            continue
        conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, parent_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            (code, name, f'{code}-YM', f'CAYMAZ yarı mamulü · montajda birleştirilen ana yapı', f'semi-{code.lower()}',
             code, SEMI, parent[0] if parent else None, db.now()))
    # Ürün ağacı: CAYMAZ'ın her parçası, ait olduğu yarı mamulün altında bir yedek parça (başlangıç stoğu 0)
    semi_ids = dict(conn.execute("SELECT code, id FROM products WHERE type = ?", (SEMI,)).fetchall())
    for part in caymaz.build():
        schema = f'{PART_PREFIX}{part["id"]}'
        if conn.execute('SELECT 1 FROM products WHERE schema = ?', (schema,)).fetchone():
            continue
        code = part['id'] if not conn.execute('SELECT 1 FROM products WHERE code = ?', (part['id'],)).fetchone() else f'P-{part["id"]}'
        conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, per_print, parent_id,
                                      orderable, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,0,?)''',
            (code, part_name(part), f'{part["id"]}-YP', 'CAYMAZ parçası · mamul siparişiyle üretilir', schema,
             'YP', 'YEDEK_PARCA', 1, semi_ids.get(semi_of(part)), db.now()))
    # Katalogdan çıkarılan parçanın parça yedeği (ör. L15-R15) kaldırılır: siparişi yoksa silinir, varsa pasif
    current = {k for k in SCHEMAS if k.startswith(PART_PREFIX)}   # tüm modellerin parçaları
    for pid, schema in conn.execute("SELECT id, schema FROM products WHERE schema LIKE ?", (f'{PART_PREFIX}%',)).fetchall():
        if schema in current:
            continue
        if conn.execute('SELECT 1 FROM orders WHERE product_id = ?', (pid,)).fetchone():
            conn.execute('UPDATE products SET active = 0, orderable = 0 WHERE id = ?', (pid,))
            continue
        conn.execute('DELETE FROM spare_moves WHERE spare_id = ?', (pid,))
        conn.execute('DELETE FROM product_spares WHERE spare_id = ? OR parent_id = ?', (pid, pid))
        conn.execute('DELETE FROM products WHERE id = ?', (pid,))
    # Baskı dosyası ve süresi (Excel eşleştirmesi): yalnızca boş olanlara yazılır, elle düzenleneni ezmez
    from .print_files import PRINT_FILES
    for part_id, (file_name, minutes) in PRINT_FILES.items():
        conn.execute('''UPDATE products SET print_file = COALESCE(print_file, ?), print_minutes = COALESCE(print_minutes, ?)
                        WHERE schema = ?''', (file_name, minutes, f'{PART_PREFIX}{part_id}'))
    # Montaj sarf parçaları: CAYMAZ başına tutulan kullanım, yarı mamul başına adetlere bölünür (bir kez;
    # sonrası Ürün Yönetimi'nden düzenlenir). Birden çok yarı mamulde kullanıldıkları için parent_id boştur.
    if parent:
        for code, per_semi in SPARE_USAGE.items():
            sp = conn.execute("SELECT id FROM products WHERE code = ? AND type = 'YEDEK_PARCA'", (code,)).fetchone()
            if not sp or not conn.execute('SELECT 1 FROM product_spares WHERE parent_id = ? AND spare_id = ?',
                                          (parent[0], sp[0])).fetchone():
                continue
            conn.execute('DELETE FROM product_spares WHERE parent_id = ? AND spare_id = ?', (parent[0], sp[0]))
            for semi_code, qty in per_semi.items():
                if semi_code in semi_ids:
                    conn.execute('INSERT OR REPLACE INTO product_spares (parent_id, spare_id, qty) VALUES (?,?,?)',
                                 (semi_ids[semi_code], sp[0], qty))
            conn.execute('UPDATE products SET parent_id = NULL WHERE id = ?', (sp[0],))


V2_DESCRIPTION = ('Benzin deposunu rahat yerleştirmek için kapakları büyüttük, ön kısımda ki mukavemet artması için ek karbon '
                  'borular eklendi, kanatların kolay birleştirilmesi için kelepçe sistemi eklendi.')


def create_v2(conn, code='CYZ2'):
    """CAYMAZ V2 ürün ağacı (bir kez, firma bazında elle çalıştırılır): mamul, dört V2 yarı mamulü, yalnızca V2'de
    olan parçaların yedek parça ürünleri ve montaj sarfı kullanımları (V1 yarı mamullerinden kopya).
    Ortak parçalar V1'in parça yedekleridir (yeni ürün açılmaz). Mamulün id'sini döner."""
    row = conn.execute('SELECT id FROM products WHERE code = ?', (code,)).fetchone()
    if row:
        return row[0]
    mamul = conn.execute(
        '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, orderable, usage_type, created_at)
           VALUES (?,?,?,?,?,?,?,1,'TEK',?)''', (code, 'CAYMAZ V2', 'CYZ-S2', V2_DESCRIPTION, 'caymaz-v2', code, 'MAMUL', db.now())).lastrowid
    semi_ids = {}
    for c, (sec, name) in SEMIS.items():
        semi_ids[f'{c}2'] = conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, parent_id, orderable, created_at)
               VALUES (?,?,?,?,?,?,?,?,0,?)''', (f'{c}2', f'{name} V2', f'{c}2-YM', 'CAYMAZ V2 yarı mamulü · montajda birleştirilen ana yapı',
                                                   f'semi-v2-{c.lower()}', f'{c}2', SEMI, mamul, db.now())).lastrowid
    for part in plane_v2.build():
        schema = f'{PART_PREFIX}{part["id"]}'
        if conn.execute('SELECT 1 FROM products WHERE schema = ?', (schema,)).fetchone():
            continue   # V1 ile ortak parça
        pcode = part['id'] if not conn.execute('SELECT 1 FROM products WHERE code = ?', (part['id'],)).fetchone() else f'P-{part["id"]}'
        conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, per_print, parent_id,
                                      orderable, created_at) VALUES (?,?,?,?,?,?,?,?,?,0,?)''',
            (pcode, part_name(part), f'{part["id"]}-YP', 'CAYMAZ V2 parçası · mamul siparişiyle üretilir', schema, 'YP',
             'YEDEK_PARCA', 1, semi_ids[semi_of(part, '2')], db.now()))
    v1 = dict(conn.execute("SELECT code, id FROM products WHERE type = ? AND code IN ('SLK','SGK','GVD','ELK')", (SEMI,)).fetchall())
    for c in SEMIS:
        if c in v1:
            conn.execute('''INSERT OR IGNORE INTO product_spares (parent_id, spare_id, qty)
                            SELECT ?, spare_id, qty FROM product_spares WHERE parent_id = ?''', (semi_ids[f'{c}2'], v1[c]))
    return mamul


def print_info(conn):
    """Parça kodu → baskı dosyası ve süresi (parça yedeği ürünlerinden)."""
    return {r['schema'][len(PART_PREFIX):]: {'print_file': r['print_file'], 'print_minutes': r['print_minutes']}
            for r in db.rows(conn.execute(
                "SELECT schema, print_file, print_minutes FROM products WHERE schema LIKE ?", (f'{PART_PREFIX}%',)))}


def tree(conn, root_id):
    """Ürün ağacı: mamul → yarı mamul → yedek parça (parent_id ilişkisi). qty: üst üründe kullanılan adet."""
    from . import spares
    rows = db.rows(conn.execute('SELECT id, code, name, type, schema, parent_id, active, print_minutes FROM products ORDER BY id'))
    usage = {(a, b): q for a, b, q in conn.execute('SELECT parent_id, spare_id, qty FROM product_spares')}
    by_id = {r['id']: r for r in rows}
    by_schema = {r['schema']: r for r in rows}
    kids = {}
    for r in rows:
        if r['type'] == SEMI:   # yarı mamulün parçaları şemasından (ortak parçalar iki modelin altında da görünür)
            from . import catalogs
            for pid in catalogs.part_ids(r['schema']):
                child = by_schema.get(f'{PART_PREFIX}{pid}')
                if child:
                    kids.setdefault(r['id'], []).append({**child, 'parent_id': r['id']})
            kids.setdefault(r['parent_id'], []).append(r)
        elif not (is_part_spare(r) and r['parent_id'] and by_id.get(r['parent_id'], {}).get('type') == SEMI):
            kids.setdefault(r['parent_id'], []).append(r)
    for (parent_id, spare_id), q in usage.items():   # kullanım bağlantıları (bir parça birden çok yarı mamulde)
        if q > 0 and spare_id in by_id and by_id[spare_id]['parent_id'] != parent_id:
            kids.setdefault(parent_id, []).append({**by_id[spare_id], 'parent_id': parent_id})

    def node(r):
        n = {k: r[k] for k in ('id', 'code', 'name', 'type', 'active')}
        n['qty'] = usage.get((r['parent_id'], r['id']), 1)
        if r['type'] == SEMI and r['code'] in SEMI_SECTIONS:
            n['section'] = SEMI_SECTIONS[r['code']]
        if r['type'] == spares.SPARE:
            n['stock'] = spares.stock(conn, r['id'])
            n['part_spare'] = is_part_spare(r)
        n['children'] = [node(c) for c in sorted(kids.get(r['id'], []), key=lambda c: (c['type'] != SEMI, c['id']))]
        # baskı süresi: parça yedeğinde kendi süresi; yarı mamul ve mamulde altındaki parça yedeklerinin toplamı
        n['print_minutes'] = r['print_minutes'] if n.get('part_spare') else (
            sum(c['print_minutes'] or 0 for c in n['children'] if c['type'] != spares.SPARE or c.get('part_spare'))
            if n['children'] else r['print_minutes'])
        return n
    root = next((r for r in rows if r['id'] == root_id), None)
    return node(root) if root else None
