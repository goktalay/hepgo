"""Ürün şemaları (parça katalogları) kaydı.

Her ürün tipi bir şemaya bağlıdır; şema, uçağın parçalarını ve çizimini üreten bir modüldür
(build(), plane_json(), part_ids(), GROUPS). Yeni ürün tipi eklemek için:
  1. app/plane.py'ye benzer yeni bir şema modülü yazılır (ör. app/schemas/<ad>.py),
  2. aşağıdaki SCHEMAS sözlüğüne kaydedilir,
  3. Ürün Yönetimi'nde bu şemaya bağlı ürün kaydı açılır (db.seed_products ya da yönetici eliyle).
"""
from fastapi import HTTPException

from . import plane as caymaz
from . import plane_v2, plane_v3, plane_v4, semis, spares

class CustomSchema:
    """Ürün Yönetimi'nden açılan ürün: çizim şeması yok (yapısı ürün ağacı ve reçeteyle tanımlanır)."""
    GROUPS = {}
    ASSEMBLY_SECTIONS = {}
    ELECTRONICS_PARTS = {}

    def build(self):
        return []

    def part_ids(self):
        return []

    def plane_json(self):
        return {'viewBox': [0, 0, 100, 100], 'groups': {}, 'sections': {}, 'parts': []}


SCHEMAS = {
    spares.CUSTOM: {'module': CustomSchema(), 'title': 'Ürün ağacı ve reçeteyle tanımlı'},
    'caymaz': {'module': caymaz, 'title': 'CAYMAZ delta kanat'},
    'caymaz-v2': {'module': plane_v2, 'title': 'CAYMAZ V2 delta kanat (büyük kapaklar, karbon takviye, kelepçeli kanat)'},
    'caymaz-v3': {'module': plane_v3, 'title': 'CAYMAZ V3 delta kanat (V2 + yeniden çizilen L4, R4 ve gövde 01)'},
    'caymaz-v4': {'module': plane_v4, 'title': 'CAYMAZ V4 delta kanat (V2 + yeniden çizilen L2, L3, R2, R3, burun 08, 09 ve servo kapağı)'},
    # dondurulmuş revizyon: servo kapağı V3'e geçmeden önce verilen CAYMAZ V4 siparişleri (orders.schema_rev)
    'caymaz-v4-r1': {'module': plane_v4.R1, 'frozen': True, 'layout': 'caymaz-v4',
                     'title': 'CAYMAZ V4 delta kanat (Servo Kapak V2 revizyonu)'},
    **spares.SCHEMAS,   # yedek parçalar: tek parçalı şemalar (kamera tutucu, klipsler)
    **semis.SCHEMAS,    # yarı mamuller: CAYMAZ'ın dört ana yapısı (sol/sağ kanat, gövde, elektronik)
}
DEFAULT_SCHEMA = 'caymaz'

# Şeması sonradan değişen ürünler: ürünün şema anahtarı → [(dondurulmuş revizyon anahtarı, o revizyona özgü parça)].
# Değişiklikten önce verilen sipariş (parça listesinde revizyona özgü parça olan) o revizyona sabitlenir
# (orders.schema_rev): parça listesi, montaj adımları ve çizimi değişmez. Yeni sipariş ürünün güncel şemasıyla açılır.
REVISIONS = {
    'caymaz-v4': [('caymaz-v4-r1', plane_v4.SERVO_COVER_R1)],
    'semi-v4-gvd': [('semi-v4r1-gvd', plane_v4.SERVO_COVER_R1)],
}
# SQL: siparişin şeması (o = orders, p = products)
ORDER_SCHEMA = 'COALESCE(o.schema_rev, p.schema)'


def layout_key(key):
    """Elle yapılan 3B yerleşimlerin anahtarı: dondurulmuş revizyon güncel şemanın yerleşimini kullanır."""
    return SCHEMAS.get(key, {}).get('layout', key)


def schema(key):
    entry = SCHEMAS.get(key)
    if not entry:
        raise HTTPException(500, f'Ürün şeması bulunamadı: {key}')
    return entry['module']


def part_ids(key):
    return schema(key).part_ids()


def part_meta(key, part_id):
    mod = schema(key)
    meta = next((p for p in mod.build() if p['id'] == part_id), {})
    return {'group': mod.GROUPS.get(meta.get('group'))}


def plane_json(key):
    return schema(key).plane_json()


def is_printed_custom(p):
    """Ürün Yönetimi'nden açılıp 'Basılıp stokta tutulur' işaretlenen ürün: çizim şeması yok, kendisi tek baskı parçasıdır."""
    return (p.get('schema') or '') == spares.CUSTOM and bool(p.get('printed'))


def product_part_ids(p):
    """Ürünün üretim parçaları: şemadan; basılı custom üründe ürünün kendi kodu (tek parça, ürünün G-code'uyla basılır)."""
    ids = part_ids(p['schema'])
    return ids if ids or not is_printed_custom(p) else [p['code']]


def printed_plane(p):
    """Basılı custom ürünün üretim çizimi: tek parça; zeminde ürünün 2B üstten görünüm resmi (varsa)."""
    pts = [[10, 10], [390, 10], [390, 290], [10, 290]]
    part = {'id': p['code'], 'name': p['name'], 'group': 'printed', 'side': 'M', 'section': None, 'layer': 'body', 'area': 380 * 280,
            'shapes': [{'pts': pts, 'holes': [], 'slots': [], 'inner': []}], 'label_at': [200, 150]}
    if p.get('image'):
        part['image'] = p['image']
    return {'viewBox': [0, 0, 400, 300], 'groups': {'printed': 'Basılı ürün'}, 'sections': {}, 'parts': [part]}


def sections(key):
    """Montaj bölümleri {anahtar: ad} ve parça → bölüm eşlemesi."""
    mod = schema(key)
    return mod.ASSEMBLY_SECTIONS, {p['id']: p['section'] for p in mod.build()}


def electronics_parts(key):
    """Elektronik montaj yapılan parçalar {kod: ad} (şemada yoksa boş)."""
    return dict(getattr(schema(key), 'ELECTRONICS_PARTS', {}))


def cover_parts(key):
    """Kapaklar (elektronik kapak K04 hariç): montajın en sonunda, birleştirmeden sonra takılır; gövde bölümüne sayılmaz."""
    return [p['id'] for p in schema(key).build() if p['group'] == 'cover' and p.get('layer') != 'electronics']


def electronics_step(part_id):
    return f'ELEKTRONIK_{part_id}'
