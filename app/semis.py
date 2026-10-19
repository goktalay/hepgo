"""Yarı mamuller (ürün tipi YARI_MAMUL) ve parça yedekleri: mamulün (CAYMAZ / CAYMAZ V2) ürün ağacı.

Yarı mamul: montajda birleştirilen dört ana yapı (Sol Kanat, Sağ Kanat, Gövde, Elektronik); içindeki parçalarla
birlikte mamulün şemasından türetilir (montaj bölümü = section, elektronik = elektronik katmanındaki parçalar).
Ayrı sipariş verilmez. Parça yedeği: şemadaki her parça bir yedek parça ürünüdür (şema part-<kod>); iki modelde
ortak olan parça tek üründür (aynı stok). Ağaçta yarı mamulün altındaki parçalar şemadan (üyelik) bulunur.
"""
import copy
import os
import threading

from . import db, spares
from . import plane as caymaz
from . import plane_v2, plane_v3, plane_v4

SEMI = spares.SEMI
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
SCHEMAS.update({f'{PART_PREFIX}{p["id"]}': {'module': PartSchema(p['id']), 'title': f'CAYMAZ parçası {p["id"]}'}
                for p in caymaz.build()})
SCHEMAS.update({f'{PART_PREFIX}{p["id"]}': {'module': PartSchema(p['id'], plane_v2), 'title': f'CAYMAZ V2 parçası {p["id"]}'}
                for p in plane_v2.build() if f'{PART_PREFIX}{p["id"]}' not in SCHEMAS})
SCHEMAS.update({f'semi-v3-{code.lower()}': {'module': SemiSchema(sec, plane_v3), 'title': f'CAYMAZ V3 {name} (yarı mamul)'}
                for code, (sec, name) in SEMIS.items()})
SCHEMAS.update({f'{PART_PREFIX}{p["id"]}': {'module': PartSchema(p['id'], plane_v3), 'title': f'CAYMAZ V3 parçası {p["id"]}'}
                for p in plane_v3.build() if f'{PART_PREFIX}{p["id"]}' not in SCHEMAS})
SCHEMAS.update({f'semi-v4-{code.lower()}': {'module': SemiSchema(sec, plane_v4), 'title': f'CAYMAZ V4 {name} (yarı mamul)'}
                for code, (sec, name) in SEMIS.items()})
SCHEMAS.update({f'{PART_PREFIX}{p["id"]}': {'module': PartSchema(p['id'], plane_v4), 'title': f'CAYMAZ V4 parçası {p["id"]}'}
                for p in plane_v4.build() if f'{PART_PREFIX}{p["id"]}' not in SCHEMAS})
# yarı mamul kodu → montaj bölümü (sürümlü yarı mamuller kod sonunda sürüm: SLK2, SGK3, GVD4, ELK2 …)
SEMI_SECTIONS = {**{c: v[0] for c, v in SEMIS.items()},
                 **{f'{c}{v}': sec for v in ('2', '3', '4') for c, (sec, _) in SEMIS.items()}}


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
    semi_ids = dict(conn.execute("SELECT code, id FROM products WHERE schema LIKE 'semi-%'").fetchall())
    for part in caymaz.build():
        schema = f'{PART_PREFIX}{part["id"]}'
        if conn.execute('SELECT 1 FROM products WHERE schema = ?', (schema,)).fetchone():
            continue
        code = part['id'] if not conn.execute('SELECT 1 FROM products WHERE code = ?', (part['id'],)).fetchone() else f'P-{part["id"]}'
        new_id = conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, per_print, parent_id,
                                      orderable, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,0,?)''',
            (code, part_name(part), f'{part["id"]}-YP', 'CAYMAZ parçası · mamul siparişiyle üretilir', schema,
             'YP', SEMI, 1, semi_ids.get(semi_of(part)), db.now())).lastrowid
        if semi_ids.get(semi_of(part)):   # katalogdan sonradan eklenen parça ağaçta ana yapısının altına girer
            conn.execute('INSERT OR IGNORE INTO product_bom (parent_id, child_id, qty) VALUES (?,?,1)', (semi_ids[semi_of(part)], new_id))
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
        conn.execute('DELETE FROM product_bom WHERE child_id = ? OR parent_id = ?', (pid, pid))
        conn.execute('DELETE FROM product_recipe WHERE item_id = ? OR product_id = ?', (pid, pid))
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
            sp = conn.execute("SELECT id FROM products WHERE code = ? AND schema LIKE 'spare-%'", (code,)).fetchone()
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


V3_DESCRIPTION = ('CAYMAZ V2 ile aynı yapı; L4, R4 kanat parçaları ve gövde 01 parçası yeniden çizildi '
                  '(CAYMAZ - L4V3, CAYMAZ - R4V3, CAYMAZ O1 - V3).')
V4_DESCRIPTION = ('CAYMAZ V2 ile aynı yapı; L2, L3, R2, R3 kanat parçaları ile gövde O8, O9 parçaları ve servo kapağı '
                  'yeniden çizildi (L2 - V3, L3 - V3, R2 - V3, R3 - V3, O8 - V3, O9 - V3 çizimleri; SERVO KAPAK - V2).')
# sürüm: (mamul kodu, ad, seri, açıklama, şema anahtarı, parça şeması modülü, montaj sarfı kopyalanacak önceki sürüm eki)
VERSIONS = {
    '2': ('CYZ2', 'CAYMAZ V2', 'CYZ-S2', V2_DESCRIPTION, 'caymaz-v2', plane_v2, ''),
    '3': ('CYZ3', 'CAYMAZ V3', 'CYZ-S3', V3_DESCRIPTION, 'caymaz-v3', plane_v3, '2'),
    '4': ('CYZ4', 'CAYMAZ V4', 'CYZ-S4', V4_DESCRIPTION, 'caymaz-v4', plane_v4, '2'),
}


def create_version(conn, ver, code=None):
    """CAYMAZ V<ver> ürün ağacı (bir kez, firma bazında): mamul, dört V<ver> yarı mamulü, yalnızca bu sürümde olan
    parçaların yedek parça ürünleri (baskı dosyası/süresi print_files'tan) ve montaj sarfı kullanımları (önceki sürümün
    yarı mamullerinden kopya). Ortak parçalar önceki sürümlerin parça yedekleridir (yeni ürün açılmaz). Mamul id'sini döner."""
    vcode, vname, serial, desc, schema_key, plane_mod, prev = VERSIONS[ver]
    code = code or vcode
    row = conn.execute('SELECT id FROM products WHERE code = ?', (code,)).fetchone()
    if row:
        return row[0]
    from .print_files import PRINT_FILES
    mamul = conn.execute(
        '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, orderable, usage_type, created_at)
           VALUES (?,?,?,?,?,?,?,1,'TEK',?)''', (code, vname, serial, desc, schema_key, code, 'MAMUL', db.now())).lastrowid
    semi_ids = {}
    for c, (sec, name) in SEMIS.items():
        semi_ids[f'{c}{ver}'] = conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, parent_id, orderable, created_at)
               VALUES (?,?,?,?,?,?,?,?,0,?)''', (f'{c}{ver}', f'{name} V{ver}', f'{c}{ver}-YM', f'{vname} yarı mamulü · montajda birleştirilen ana yapı',
                                                   f'semi-v{ver}-{c.lower()}', f'{c}{ver}', SEMI, mamul, db.now())).lastrowid
        conn.execute('INSERT OR IGNORE INTO product_bom (parent_id, child_id, qty) VALUES (?,?,1)', (mamul, semi_ids[f'{c}{ver}']))
    for part in plane_mod.build():
        schema = f'{PART_PREFIX}{part["id"]}'
        if conn.execute('SELECT 1 FROM products WHERE schema = ?', (schema,)).fetchone():
            continue   # önceki sürümle ortak parça
        pcode = part['id'] if not conn.execute('SELECT 1 FROM products WHERE code = ?', (part['id'],)).fetchone() else f'P-{part["id"]}'
        pf = PRINT_FILES.get(part['id'], (None, None))
        # yeniden çizilen parçanın üstten 2B görünüşü önceki sürümdeki karşılığıyla aynıdır: aynı resim dosyası (kopya yok)
        changed = getattr(plane_mod, 'CHANGED', None)   # V3/V4: {eski kod: yeni kod}
        old = next((o for o, n in changed.items() if n == part['id']), None) if isinstance(changed, dict) else None
        image = conn.execute('SELECT image FROM products WHERE schema = ?', (f'{PART_PREFIX}{old}',)).fetchone() if old else None
        conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, per_print, parent_id,
                                      orderable, print_file, print_minutes, image, created_at) VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?)''',
            (pcode, part_name(part), f'{part["id"]}-YP', f'{vname} parçası · mamul siparişiyle üretilir', schema, 'YP',
             SEMI, 1, semi_ids[semi_of(part, ver)], pf[0], pf[1], image[0] if image else None, db.now()))
    for part in plane_mod.build():   # ağaç: V<ver> ana yapısı → parçaları (ortak olanlar dahil)
        child = conn.execute('SELECT id FROM products WHERE schema = ?', (f'{PART_PREFIX}{part["id"]}',)).fetchone()
        conn.execute('INSERT OR IGNORE INTO product_bom (parent_id, child_id, qty) VALUES (?,?,1)', (semi_ids[semi_of(part, ver)], child[0]))
    prev_codes = tuple(f'{c}{prev}' for c in SEMIS)
    prev_ids = dict(conn.execute(f"SELECT code, id FROM products WHERE schema LIKE 'semi-%' AND code IN ({','.join('?' * len(prev_codes))})", prev_codes).fetchall())
    for c in SEMIS:
        if f'{c}{prev}' in prev_ids:   # montaj sarfı kullanımları önceki sürümün ana yapılarından kopyalanır
            conn.execute('''INSERT OR IGNORE INTO product_bom (parent_id, child_id, qty, pos)
                            SELECT ?, b.child_id, b.qty, 1 FROM product_bom b JOIN products p ON p.id = b.child_id
                            WHERE b.parent_id = ? AND p.schema LIKE 'spare-%' ''', (semi_ids[f'{c}{ver}'], prev_ids[f'{c}{prev}']))
    # mamul düzeyinde V<prev>'e eklenmiş diğer yarı mamuller (ör. karbüratör kapağı) aynen bağlanır
    if prev:
        prev_m = conn.execute('SELECT id FROM products WHERE code = ?', (VERSIONS[prev][0],)).fetchone()
        if prev_m:
            conn.execute('''INSERT OR IGNORE INTO product_bom (parent_id, child_id, qty, pos)
                            SELECT ?, b.child_id, b.qty, b.pos FROM product_bom b JOIN products p ON p.id = b.child_id
                            WHERE b.parent_id = ? AND p.schema NOT LIKE 'semi-%' ''', (mamul, prev_m[0]))
    conn.commit()
    return mamul


def create_v2(conn, code='CYZ2'):
    return create_version(conn, '2', code)


def create_v3(conn, code='CYZ3'):
    return create_version(conn, '3', code)


def create_v4(conn, code='CYZ4'):
    return create_version(conn, '4', code)


# başlangıçta kurulan sürümler: (sürüm, yalnız bu sürümde olan parça kodları)
AUTO_VERSIONS = (
    ('3', list(plane_v3.CHANGED.values())),
    ('4', plane_v4.NEW_PARTS),
)


def ensure_versions(conn):
    """Başlangıçta: V2 olan firmada V3 ve V4 yoksa oluşturur (idempotent); sürüme özel parçaların G-code'u
    uploads/gcode altında (print_files adıyla) duruyorsa bağlar (dilimleyici bilgileri, gömülü önizleme, 3B yol, süre).
    Dosya sonradan gelirse bir sonraki başlangıçta bağlanır. V2 yoksa dokunmaz."""
    if not conn.execute('SELECT 1 FROM products WHERE code = ?', (VERSIONS['2'][0],)).fetchone():
        return None
    from . import config, gcode
    folder = config.UPLOAD_DIR / gcode.FOLDER
    mids, bekleyen = [], []
    for ver, part_codes in AUTO_VERSIONS:
        mids.append(create_version(conn, ver))
        schemas = tuple(f'{PART_PREFIX}{k}' for k in part_codes)
        for r in db.rows(conn.execute(f'''SELECT id, print_file FROM products WHERE gcode_file IS NULL AND print_file IS NOT NULL
                                         AND schema IN ({','.join('?' * len(schemas))})''', schemas)):
            src = folder / f'{r["print_file"]}.gcode'
            if src.is_file():
                bekleyen.append((r['id'], src))
    if bekleyen:
        # Büyük G-code'ların (60 MB'a kadar) ayrıştırılması dakikalar sürebilir; açılışı bloklamasın diye arka planda bağlanır.
        # Testler/komut satırı için CAYMAZ_GCODE_SYNC=1 senkron çalıştırır.
        if os.environ.get('CAYMAZ_GCODE_SYNC') == '1':
            _gcode_bagla(bekleyen, conn)
        else:
            threading.Thread(target=_gcode_bagla, args=(bekleyen, None), daemon=True, name='semis-gcode').start()
    return mids[-1]


def _gcode_bagla(bekleyen, conn=None):
    """Sürüme özel parçaların G-code'unu bağlar (ensure_versions'tan; conn verilmezse kendi bağlantısını açar)."""
    from . import gcode
    for pid, src in bekleyen:
        try:
            if conn is not None:
                gcode.attach(conn, pid, src)
                conn.commit()
            else:
                with db.connect() as c:
                    gcode.attach(c, pid, src)
                    c.commit()
        except Exception as e:   # noqa: BLE001 — bir dosya bozuksa diğerleri bağlansın
            print('[semis] gcode bağlanamadı', src.name, e)


def print_info(conn):
    """Parça kodu → baskı dosyası ve süresi (parça yedeği ürünlerinden)."""
    rows = db.rows(conn.execute(
        "SELECT schema, code, print_file, print_minutes, gcode_preview FROM products WHERE schema LIKE ? OR (schema = 'custom' AND printed = 1)",
        (f'{PART_PREFIX}%',)))
    return {(r['schema'][len(PART_PREFIX):] if r['schema'].startswith(PART_PREFIX) else r['code']):   # basılı custom: ürün kodu
            {'print_file': r['print_file'], 'print_minutes': r['print_minutes'], 'gcode_preview': r['gcode_preview']}   # 3B görünüm
            for r in rows}


def tree(conn, root_id):
    """Ürün ağacı (product_bom): mamul → yarı mamuller (iç içe) → parçalar; bkz. app/bom.py."""
    from . import bom
    return bom.tree(conn, root_id)
