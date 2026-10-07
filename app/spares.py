"""Yedek parçalar (ürün tipi YEDEK_PARCA): çoklu basılan küçük parçalar ve stokları.

Her yedek parça bir üründür: tek parçalı bir şeması (çizimi) vardır, siparişle yazıcıda basılır. Bir sipariş
(bir baskı) depo onayından geçince stoğa "bir baskıda üretilen adet" (per_print) kadar girer. Bir mamulün (CAYMAZ)
montajı tamamlanınca (birleştirme montajı → kalibrasyon) mamul başına kullanılan adet stoktan düşer. Kullanım,
yarı mamul başına tutulur (product_spares: ör. BBK Sol Kanat 27, Sağ Kanat 27, Gövde 14); mamul başına = toplam.
Stok, hareketlerin toplamıdır (spare_moves): üretim +, montaj −, başlangıç ve sayım düzeltmesi ±.
"""
import math

from . import config, db

# Ürün tipleri (etiket): MAMUL, YARI_MAMUL, YEDEK_PARCA (satın alınan / reçetede kullanılan parça), HAMMADDE.
# Davranış tipten değil şemadan gelir: basılıp stokta tutulan parçalar (şema part-* ve spare-*) yarı mamul tipindedir.
MAMUL, SEMI, SPARE, RAW = 'MAMUL', 'YARI_MAMUL', 'YEDEK_PARCA', 'HAMMADDE'
FIXTURE, CONSUMABLE = 'DEMIRBAS', 'SARF'   # MRP malzemeleri: demirbaş ve sarf malzeme (reçetede kullanılmaz)
TYPES = {MAMUL: 'Mamul', SEMI: 'Yarı mamul', SPARE: 'Yedek parça', RAW: 'Hammadde', FIXTURE: 'Demirbaş', CONSUMABLE: 'Sarf malzeme'}
CUSTOM = 'custom'   # Ürün Yönetimi'nden açılan ürün: çizim şeması yok (ağaç, reçete, resim, G-code ile tanımlanır)
STOCKED_SQL = "(schema LIKE 'part-%' OR schema LIKE 'spare-%')"   # basılıp stokta tutulan (sipariş = baskı)


def is_stocked(p):
    """Basılıp stokta tutulan parça: parça yedeği (part-*), montaj sarfı (spare-*) ya da Ürün Yönetimi'nden açılıp
    'Basılıp stokta tutulur' işaretlenen custom ürün (printed=1)."""
    schema = p.get('schema') or ''
    return schema.startswith(('part-', 'spare-')) or (schema == CUSTOM and bool(p.get('printed')))


def is_sarf(p):
    """Montaj sarfı (KMH, BBK, KBK): mamulün montajında stoktan düşülür."""
    return (p.get('schema') or '').startswith('spare-')


def is_section(p):
    """Mamul şemasından türeyen yarı mamul (Sol Kanat, Sağ Kanat, Gövde, Elektronik)."""
    return (p.get('schema') or '').startswith('semi-')


def role(p):
    schema = p.get('schema') or ''
    return ('part' if schema.startswith('part-') else 'sarf' if schema.startswith('spare-') else 'section'
            if schema.startswith('semi-') else 'custom' if schema == CUSTOM else 'mamul')


# ---------- Çizimler (her yedek parça tek parçalı bir şema; koordinatlar kendi çizim uzayında)

def _h_vertical(x0, y0, w=78, h=230, leg=24, bar0=105, bar1=128):
    """Dikey H klips (büyük bağlantı klipsi)."""
    return [[x0, y0], [x0 + leg, y0], [x0 + leg, y0 + bar0], [x0 + w - leg, y0 + bar0], [x0 + w - leg, y0], [x0 + w, y0],
            [x0 + w, y0 + h], [x0 + w - leg, y0 + h], [x0 + w - leg, y0 + bar1], [x0 + leg, y0 + bar1], [x0 + leg, y0 + h],
            [x0, y0 + h]]


def _h_horizontal(x0, y0, w=232, h=80, bar=22, stem=24):
    """Yatay H klips (küçük bağlantı klipsi)."""
    xc = x0 + w * 0.5
    return [[x0, y0], [x0 + w, y0], [x0 + w, y0 + bar], [xc + stem / 2, y0 + bar], [xc + stem / 2, y0 + h - bar],
            [x0 + w, y0 + h - bar], [x0 + w, y0 + h], [x0, y0 + h], [x0, y0 + h - bar], [xc - stem / 2, y0 + h - bar],
            [xc - stem / 2, y0 + bar], [x0, y0 + bar]]


def _ring(x, y, r, n=20):
    return [[x + r * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)] for i in range(n)]


def _kmh():
    """Kamera tutucu: taban plakası, yukarı daralan gövde, üstte çatal; 4 vida deliği, oval kanal."""
    outline = [[112, 290], [142, 290], [200, 112], [200, 68], [208, 68], [208, 95], [238, 95], [238, 68], [246, 68],
               [246, 112], [303, 290], [330, 290], [330, 302], [112, 302]]
    inner = [[[200, 95], [246, 95], [246, 112], [200, 112]],          # çatal altı köprü
             [[142, 290], [303, 290], [303, 294], [142, 294]]]        # taban birleşimi
    inner += [_ring(x, y, 9) for x, y in ((205, 176), (238, 176), (205, 210), (238, 210))]
    inner += [_ring(x, y, 5) for x, y in ((205, 176), (238, 176), (205, 210), (238, 210))]
    shape = {'pts': outline, 'holes': [], 'slots': [[193, 231, 59, 22]], 'inner': inner}
    return {'viewBox': [95, 50, 250, 270], 'shapes': [shape], 'label_at': [222, 140]}


def _bbk():
    """Büyük bağlantı klipsi: bir baskıda 2 sıra × 6 dikey H = 12 adet."""
    shapes = [{'pts': _h_vertical(78 + c * 93, 70 + r * 243), 'holes': [], 'slots': [], 'inner': []}
              for r in range(2) for c in range(6)]
    return {'viewBox': [60, 50, 590, 520], 'shapes': shapes, 'label_at': None}


def _kbk():
    """Küçük bağlantı klipsi: bir baskıda 6 sıra × 2 yatay H = 12 adet."""
    shapes = [{'pts': _h_horizontal(75 + c * 243, 75 + r * 93), 'holes': [], 'slots': [], 'inner': []}
              for r in range(6) for c in range(2)]
    return {'viewBox': [55, 55, 520, 580], 'shapes': shapes, 'label_at': None}


class SpareSchema:
    """catalogs.SCHEMAS için tek parçalı şema (plane.py ile aynı arayüz)."""
    GROUPS = {'spare': 'Yedek parça'}
    ASSEMBLY_SECTIONS = {}
    ELECTRONICS_PARTS = {}

    def __init__(self, code, name, drawing):
        self.code, self.name, self._drawing = code, name, drawing

    def build(self):
        d = self._drawing()
        area = sum(abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(s['pts'], s['pts'][1:] + s['pts'][:1]))) / 2
                   for s in d['shapes'])
        part = {'id': self.code, 'name': self.name, 'group': 'spare', 'side': 'M', 'shapes': d['shapes'], 'area': round(area),
                'section': None, 'layer': 'body'}
        if d.get('label_at'):
            part['label_at'] = d['label_at']
        return [part]

    def part_ids(self):
        return [self.code]

    def plane_json(self):
        return {'viewBox': self._drawing()['viewBox'], 'groups': self.GROUPS, 'sections': {}, 'parts': self.build()}


# kod: (ad, çizim, bir baskıda üretilen, CAYMAZ başına kullanılan, başlangıç stoğu)
SPARES = {
    'KMH': ('Kamera Holder', _kmh, 1, 1, 1),
    'BBK': ('Büyük Bağlantı Klipsi', _bbk, 12, 68, 183),
    'KBK': ('Küçük Bağlantı Klipsi', _kbk, 12, 6, 38),
}
SCHEMAS = {f'spare-{code.lower()}': {'module': SpareSchema(code, v[0], v[1]), 'title': f'{v[0]} (montaj sarfı)'}
           for code, v in SPARES.items()}


def seed(conn):
    """İlk kurulumda üç yedek parçayı, başlangıç stoklarını ve CAYMAZ başına kullanımlarını ekler."""
    parent = conn.execute("SELECT id FROM products WHERE code = 'CYZ'").fetchone()
    for code, (name, _, per_print, usage, initial) in SPARES.items():
        if conn.execute('SELECT 1 FROM products WHERE code = ?', (code,)).fetchone():
            continue
        pid = conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, per_print, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            (code, name, f'{code}-YP', f'Yedek parça · bir baskıda {per_print} adet', f'spare-{code.lower()}', code, SEMI,
             per_print, db.now())).lastrowid
        if initial and config.SEED_SPARE_STOCK:   # yeni firmada (ör. Türkbey) stok sıfırdan başlar
            conn.execute('INSERT INTO spare_moves (spare_id, qty, reason, created_at) VALUES (?,?,?,?)',
                         (pid, initial, 'Başlangıç stoğu', db.now()))
        if parent:
            conn.execute('INSERT INTO product_spares (parent_id, spare_id, qty) VALUES (?,?,?)', (parent[0], pid, usage))


# ---------- Stok

def stock(conn, spare_id):
    return conn.execute('SELECT COALESCE(SUM(qty), 0) FROM spare_moves WHERE spare_id = ?', (spare_id,)).fetchone()[0]


def add_move(conn, spare_id, qty, reason, user_id=None, order_id=None, at=None):
    conn.execute('INSERT INTO spare_moves (spare_id, qty, reason, order_id, user_id, created_at) VALUES (?,?,?,?,?,?)',
                 (spare_id, qty, reason, order_id, user_id, at or db.now()))


def produced(conn, order, at=None):
    """Yedek parça siparişi depoya alındı: bir baskıda üretilen adet stoğa girer (sipariş başına bir kez)."""
    if conn.execute("SELECT 1 FROM spare_moves WHERE order_id = ? AND qty > 0", (order['id'],)).fetchone():
        return
    per = conn.execute('SELECT per_print FROM products WHERE id = ?', (order['product_id'],)).fetchone()[0] or 1
    add_move(conn, order['product_id'], per, f'Üretim: {order["code"]}', order_id=order['id'], at=at)


def per_product(conn, product_id):
    """Bir mamulde kullanılan montaj sarfı adetleri {spare_id: adet}: ürün ağacında (product_bom) mamulün altındaki
    tüm dallardan, üst adetlerle çarpılarak toplanır (ör. BBK: Sol Kanat 27 + Sağ Kanat 27 + Gövde 14)."""
    kids = {}
    for parent, child, qty, schema in conn.execute(
            'SELECT b.parent_id, b.child_id, b.qty, p.schema FROM product_bom b JOIN products p ON p.id = b.child_id WHERE b.qty > 0'):
        kids.setdefault(parent, []).append((child, qty, schema))
    out = {}

    def walk(pid, mult, seen):
        for child, qty, schema in kids.get(pid, []):
            if child in seen:
                continue
            if schema.startswith('spare-'):
                out[child] = out.get(child, 0) + qty * mult
            walk(child, qty * mult, seen | {child})
    walk(product_id, 1, {product_id})
    return {k: int(math.ceil(v - 1e-9)) for k, v in out.items()}


def usages(conn, spare_id):
    """Montaj sarfının kullanıldığı ürünler ve adetleri (ürün ağacındaki doğrudan üstleri)."""
    return db.rows(conn.execute(
        """SELECT b.parent_id, b.qty, p.name AS parent_name FROM product_bom b JOIN products p ON p.id = b.parent_id
           WHERE b.child_id = ? AND b.qty > 0 ORDER BY p.id""", (spare_id,)))


def consume(conn, order, at=None):
    """Mamulün montajı tamamlandı: kullanılan yedek parçalar stoktan düşer (sipariş başına bir kez)."""
    if conn.execute('SELECT 1 FROM spare_moves WHERE order_id = ? AND qty < 0', (order['id'],)).fetchone():
        return
    for spare_id, qty in per_product(conn, order['product_id']).items():
        add_move(conn, spare_id, -qty, f'Montaj: {order["code"]}', order_id=order['id'], at=at)


def summary(conn):
    """Yedek parçalar: stok, bir baskıda üretilen, mamul başına kullanılan ve stoğun kaç mamule yettiği."""
    rows = db.rows(conn.execute(f"SELECT id, code, name, schema, per_print, active FROM products WHERE {STOCKED_SQL} ORDER BY id"))
    for r in rows:
        r['stock'] = stock(conn, r['id'])
        r['usages'] = usages(conn, r['id']) if is_sarf(r) else []   # parça yedekleri siparişle basılır, montajda düşülmez
        need = int(math.ceil(sum(u['qty'] for u in r['usages']) - 1e-9))
        r['per_aircraft'] = need
        r['enough_for'] = r['stock'] // need if need else None
        r['open_orders'] = conn.execute("SELECT COUNT(*) FROM orders WHERE product_id = ? AND status NOT IN ('TAMAMLANDI', 'HURDA')",
                                        (r['id'],)).fetchone()[0]
    return rows
