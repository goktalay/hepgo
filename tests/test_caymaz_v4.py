"""CAYMAZ V4 testi: V4 şeması (V2 kopyası; L2, L3, R2, R3, 08, 09 → -V4 ve servo kapağı), başlangıçta idempotent kurulum
(ensure_versions: V3 + V4; iki çalıştırmada çift kayıt yok), ürün ağacı (V2 ile aynı yapı + servo kapağı), yalnızca
V4'te olan 7 parçanın yedek parça kayıtları (baskı dosyası / süresi), montaj sarfı kullanımı, G-code bağlama
(gcode_file / gcode_preview / gcode_thumb; 2B resim ÜRETİLMEZ, V2 karşılığının resmi aynen kullanılır), sipariş.
Servo kapağı revizyonu: güncel kapak SERVO-KAPAK-V3 (bir baskıda 4 adet); kapak değişmeden önce verilen sipariş
Servo Kapak V2 ile sürer (orders.schema_rev = 'caymaz-v4-r1'), yeni sipariş V3 ile açılır.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_caymaz_v4
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_GCODE_SYNC='1',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import catalogs, db, plane_v2, plane_v4, production, semis, spares  # noqa: E402
from app.print_files import PER_PRINT, PRINT_FILES  # noqa: E402
from app.main import app  # noqa: E402

GCODE_SRC = Path(os.environ.get('CAYMAZ_V4_GCODE', '/opt/hepgo/incoming/caymazv4_parcalar'))
# servo kapağının güncel G-code'u (bir baskıda 4 adet) ayrı klasörden gelir
SERVO_SRC = Path(os.environ.get('CAYMAZ_V4_SERVO_GCODE', '/opt/hepgo/incoming/caymazv4_servo_v3'))
V2K, V3K = 'SERVO-KAPAK-V2', 'SERVO-KAPAK-V3'
NEW = ['L2-V4', 'L3-V4', 'R2-V4', 'R3-V4', '08-V4', '09-V4', V3K]


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    v2, v4 = set(plane_v2.part_ids()), set(plane_v4.part_ids())
    assert len(v4) == len(v2) + 1 == 64 and plane_v4.NEW_PARTS == NEW
    assert v4 - v2 == set(NEW) and v2 - v4 == set(plane_v4.CHANGED)
    servo = next(p for p in plane_v4.build() if p['id'] == V3K)
    assert servo['group'] == 'cover' and servo['layer'] == 'cover' and servo['section'] == 'GOVDE' and servo['hosts'] == ['02']
    assert servo['name'] == 'Servo Kapak V3' and plane_v4.REPLACED == {V2K: V3K}
    # dondurulmuş ilk revizyon: yalnız servo kapağı farklı (aynı yer, aynı şekil, aynı sıra)
    r1 = plane_v4.R1.build()
    assert [p['id'] for p in r1] == [V2K if i == V3K else i for i in plane_v4.part_ids()]
    old = next(p for p in r1 if p['id'] == V2K)
    assert old['name'] == 'Servo Kapak V2' and old['shapes'] == servo['shapes'] and old['hosts'] == servo['hosts']
    assert catalogs.part_ids('caymaz-v4-r1') == plane_v4.R1.part_ids() and catalogs.cover_parts('caymaz-v4-r1').count(V2K) == 1
    assert V3K in catalogs.cover_parts('caymaz-v4') and V2K not in catalogs.cover_parts('caymaz-v4')
    assert catalogs.part_ids('part-' + V2K) == [V2K] and catalogs.part_ids('part-' + V3K) == [V3K]
    assert V2K in catalogs.part_ids('semi-v4r1-gvd') and V3K in catalogs.part_ids('semi-v4-gvd')
    assert catalogs.layout_key('caymaz-v4-r1') == 'caymaz-v4' and catalogs.layout_key('caymaz-v4') == 'caymaz-v4'
    for p in plane_v4.build():   # yeni parçalar V2 parçasıyla aynı yer / aynı yarı mamul
        if p['id'] in plane_v4.CHANGED.values():
            old = next(k for k, v in plane_v4.CHANGED.items() if v == p['id'])
            o = next(q for q in plane_v2.build() if q['id'] == old)
            assert p['shapes'] == o['shapes'] and p['section'] == o['section'], p['id']
    assert all(k in PRINT_FILES for k in NEW) and PRINT_FILES['L2-V4'] == ('L2 - V3 _ABS_7h33m', 453)
    assert PRINT_FILES['08-V4'][1] == 16 * 60 + 46 and PRINT_FILES[V2K][1] == 420
    assert PRINT_FILES[V3K] == ('SERVO KAPAK - V3_ABS_7h32m', 452) and PER_PRINT == {V3K: 4}

    # G-code dosyaları veri klasörüne (uploads/gcode): başlangıçta bağlanır
    folder = Path(tmp) / 'uploads' / 'gcode'
    folder.mkdir(parents=True)
    have_gcode = GCODE_SRC.is_dir() and SERVO_SRC.is_dir()
    if have_gcode:
        for f in [*GCODE_SRC.glob('*.gcode'), *SERVO_SRC.glob('*.gcode')]:
            try:
                os.link(f, folder / f.name)
            except OSError:
                shutil.copy2(f, folder / f.name)

    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        with db.connect() as conn:
            assert semis.ensure_versions(conn) is None   # V2 yokken dokunmaz
            semis.create_v2(conn)
        before = len(ok(a.get('/api/products')))
        with db.connect() as conn:
            mid = semis.ensure_versions(conn)
            conn.commit()
        with db.connect() as conn:
            assert semis.ensure_versions(conn) == mid   # ikinci başlangıç: yeni kayıt yok
            conn.commit()
        products = {p['code']: p for p in ok(a.get('/api/products'))}
        # V3: mamul + 4 yarı mamul + 3 parça; V4: mamul + 4 yarı mamul + 7 parça
        assert len(products) == before + (1 + 4 + 3) + (1 + 4 + 7)
        assert len([c for c in products if c.endswith('-V4')]) == 6 and V3K in products and V2K not in products
        m = products['CYZ4']
        assert (m['name'], m['serial'], m['type'], m['orderable'], m['schema'], m['queue_prefix'], m['part_count']) == \
            ('CAYMAZ V4', 'CYZ-S4', 'MAMUL', 1, 'caymaz-v4', 'CYZ4', 64)
        assert m['description'].startswith('CAYMAZ V2 ile aynı yapı; L2, L3, R2, R3')
        for code in NEW:   # yedek parça kayıtları
            p = products[code]
            assert p['schema'] == f'part-{code}' and p['parent']['code'] in ('SLK4', 'SGK4', 'GVD4') and not p['orderable']
            assert (p['print_file'], p['print_minutes']) == PRINT_FILES[code], code
        assert products['L2-V4']['parent']['code'] == 'SLK4' and products['R3-V4']['parent']['code'] == 'SGK4'
        assert products['08-V4']['parent']['code'] == 'GVD4' and products[V3K]['parent']['code'] == 'GVD4'
        k3 = products[V3K]
        assert (k3['name'], k3['serial'], k3['queue_prefix'], k3['type'], k3['per_print']) == ('Servo Kapak V3', f'{V3K}-YP', 'YP', 'YARI_MAMUL', 4)
        assert all(products[c]['per_print'] == 1 for c in NEW if c != V3K)
        assert 'SERVO KAPAK - V3' in m['description'] and 'SERVO KAPAK - V2' not in m['description']
        # dondurulmuş revizyon yeni ürüne şema olarak seçilemez
        keys = {x['key'] for x in ok(a.get('/api/products/schemas'))}
        assert 'caymaz-v4' in keys and not ({'caymaz-v4-r1', 'semi-v4r1-gvd'} & keys)
        assert [x['code'] for x in products['L2']['used_in']] == ['SLK', 'SLK2', 'SLK3']   # eski L2 V4'te yok
        assert [x['code'] for x in products['L2-V4']['used_in']] == ['SLK4']
        assert [x['code'] for x in products['L17']['used_in']] == ['SLK', 'SLK2', 'SLK3', 'SLK4']   # ortak parça

        tree = ok(a.get(f'/api/products/{m["id"]}/tree'))
        assert [n['code'] for n in tree['children']] == ['SLK4', 'SGK4', 'GVD4', 'ELK4']
        parts = {n['code']: {c['code'] for c in n['children'] if c['part_spare']} for n in tree['children']}
        assert [len(parts[c]) for c in ('SLK4', 'SGK4', 'GVD4', 'ELK4')] == [22, 22, 18, 2]   # V2: 22, 22, 17, 2 + servo kapağı
        assert {'L2-V4', 'L3-V4', 'L4-V2', 'L17'} <= parts['SLK4'] and not ({'L2', 'L3', 'L4-V3'} & parts['SLK4'])
        assert {'08-V4', '09-V4', V3K, '01-V2', 'K08'} <= parts['GVD4'] and not ({'08-V2', '09', '01-V3'} & parts['GVD4'])
        sarf = {n['code']: {c['code']: c['qty'] for c in n['children'] if not c['part_spare']} for n in tree['children']}
        assert sarf == {'SLK4': {'BBK': 27, 'KBK': 3}, 'SGK4': {'BBK': 27, 'KBK': 3}, 'GVD4': {'KMH': 1, 'BBK': 14}, 'ELK4': {}}
        with db.connect() as conn:
            assert spares.per_product(conn, m['id']) == {products['KMH']['id']: 1, products['BBK']['id']: 68, products['KBK']['id']: 6}
            # V2 ağacı değişmedi (düğüm sayısı)
            n2 = conn.execute('SELECT COUNT(*) FROM product_bom WHERE parent_id IN (SELECT id FROM products WHERE code IN (?,?,?,?))',
                              ('SLK2', 'SGK2', 'GVD2', 'ELK2')).fetchone()[0]
            n4 = conn.execute('SELECT COUNT(*) FROM product_bom WHERE parent_id IN (SELECT id FROM products WHERE code IN (?,?,?,?))',
                              ('SLK4', 'SGK4', 'GVD4', 'ELK4')).fetchone()[0]
            assert n4 == n2 + 1 == 63 + 6 + 1

        plane_json = ok(a.get(f'/api/products/{m["id"]}/plane'))
        pj = {p['id']: p for p in plane_json['parts']}
        assert pj[V3K]['hosts'] == ['02'] and V2K not in pj and pj['L2-V4']['print_file'] == 'L2 - V3 _ABS_7h33m'
        # üstten 2B görünüş: yeni parça V2 karşılığının resmini aynen kullanır (aynı dosya yolu; şekil zaten aynı)
        for old, new in plane_v4.CHANGED.items():
            assert products[new]['image'] == products[old]['image'], (old, new)
        assert [p['id'] for p in ok(a.get(f'/api/products/{products["09-V4"]["id"]}/plane'))['parts']] == ['09-V4']

        if have_gcode:   # G-code bağlandı: 3B önizleme, gömülü 300x300 thumbnail, süre; 2B resim üretilmez
            up = Path(tmp) / 'uploads'
            for code in NEW:
                p = products[code]
                assert p['gcode_file'] == f'gcode/{PRINT_FILES[code][0]}.gcode', code
                assert p['gcode_preview'] and (up / p['gcode_preview']).is_file(), code
                assert p['gcode_thumb'] and (up / p['gcode_thumb']).is_file(), code
                assert pj[code]['gcode_preview'] == p['gcode_preview']
            assert not (up / 'products').exists() or not list((up / 'products').glob('gcode-top-*'))
            # servo kapağı: görünen resim G-code'dan (izometrik kart + gömülü önizleme); süre dilimleyiciden (7 sa 32 dk)
            assert k3['image'] is None and (up / k3['gcode_preview'].replace('.bin', '.png')).is_file()
            gm = json.loads(k3['gcode_meta'])
            assert k3['print_minutes'] == 452 and gm['layers'] == 498 and gm['material'] == 'ABS'
            with db.connect() as conn:   # üçüncü başlangıç: G-code bağlı, yeniden işlenmez
                meta = dict(conn.execute("SELECT code, gcode_meta FROM products WHERE code IN ('L2-V4', '09-V4')").fetchall())
                semis.ensure_versions(conn)
                assert dict(conn.execute("SELECT code, gcode_meta FROM products WHERE code IN ('L2-V4', '09-V4')").fetchall()) == meta
        else:
            print('UYARI: G-code klasörü yok, bağlama testi atlandı:', GCODE_SRC)

        # Sipariş: 64 parça; montaj bölümleri V2 ile aynı; kuyruk öneki CYZ4
        o = ok(a.post('/api/orders', json={'product_id': m['id'], 'note': 'CAYMAZ V4 ilk sipariş'}))[0]
        d = ok(a.get(f'/api/orders/{o["id"]}'))
        assert len(d['parts']) == 64 and d['product_name'] == 'CAYMAZ V4' and d['status'] == 'SIPARIS' and o['code']
        with db.connect() as conn:   # üretim kuyruğu öneki (üretim izleme) CYZ4
            assert conn.execute('SELECT p.queue_prefix FROM orders o JOIN products p ON p.id = o.product_id WHERE o.id = ?',
                                (o['id'],)).fetchone()[0] == 'CYZ4'
        assert set(NEW) <= {p['part_id'] for p in d['parts']} and not ({'L2', '09', '08-V2'} & {p['part_id'] for p in d['parts']})
        assert set(d['assembly']['sections']) == {'SOL_KANAT', 'SAG_KANAT', 'GOVDE'}
        assert V2K not in {p['part_id'] for p in d['parts']}

        servo_revision(a, m, o, products)
    print('CAYMAZ V4 testleri geçti.')


def servo_revision(a, m, o, products):
    """Servo kapağı değişmeden önceki kurulum (V2 kapaklı ağaç, V2 kapaklı sipariş) yeniden kurulur ve başlangıç adımları
    çalıştırılır: eski sipariş V2 ile kalır (parça listesi, montaj, çizim), ağaç ve yeni sipariş V3'e geçer."""
    gvd, k3 = products['GVD4']['id'], products[V3K]['id']
    with db.connect() as conn:
        bom0 = conn.execute('SELECT COUNT(*) FROM product_bom').fetchone()[0]
        # kapak değişmeden önceki durum: V3 ürünü yok, ağaçta ve siparişte V2 (ağaçta adet 2, sıra 5: korunmalı)
        conn.execute('DELETE FROM products WHERE id = ?', (k3,))
        conn.execute('DELETE FROM product_bom WHERE child_id = ?', (k3,))
        k2 = conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, type, per_print, parent_id, orderable,
                                      print_file, print_minutes, created_at) VALUES (?,?,?,?,?,?,?,1,?,0,?,?,?)''',
            (V2K, 'Servo Kapak V2', f'{V2K}-YP', 'CAYMAZ V4 parçası · mamul siparişiyle üretilir', f'part-{V2K}', 'YP', 'YARI_MAMUL',
             gvd, *PRINT_FILES[V2K], db.now())).lastrowid
        conn.execute('INSERT INTO product_bom (parent_id, child_id, qty, pos) VALUES (?,?,2,5)', (gvd, k2))
        conn.execute('UPDATE products SET description = ? WHERE id = ?', (semis.V4_DESCRIPTION_R1, m['id']))
        conn.execute('UPDATE order_parts SET part_id = ?, state = ? WHERE order_id = ? AND part_id = ?', (V2K, 'DEPO', o['id'], V3K))
        assert conn.execute('SELECT schema_rev FROM orders WHERE id = ?', (o['id'],)).fetchone()[0] is None
        parts0 = [tuple(r) for r in conn.execute('SELECT part_id, state FROM order_parts WHERE order_id = ? ORDER BY id', (o['id'],)).fetchall()]
        conn.commit()

    for tur in (1, 2):   # başlangıç adımları (main.py sırası); ikinci tur: idempotent
        with db.connect() as conn:
            db_init_seed(conn)
            assert production.sync_catalog_parts(conn) == 0, tur   # eski siparişe V3 parçası eklenmez
            semis.ensure_versions(conn)
            conn.commit()
            assert conn.execute('SELECT schema_rev FROM orders WHERE id = ?', (o['id'],)).fetchone()[0] == 'caymaz-v4-r1'
            assert [tuple(r) for r in conn.execute('SELECT part_id, state FROM order_parts WHERE order_id = ? ORDER BY id', (o['id'],)).fetchall()] == parts0
            assert conn.execute('SELECT COUNT(*) FROM product_bom').fetchone()[0] == bom0
            assert conn.execute('SELECT COUNT(*) FROM products WHERE schema IN (?, ?)', (f'part-{V2K}', f'part-{V3K}')).fetchone()[0] == 2

    products = {p['code']: p for p in ok(a.get('/api/products'))}
    k2, k3 = products[V2K], products[V3K]
    # eski kapak durur (eski siparişler onunla basılır); ağaçta yerini V3 alır (adet ve sıra korunur)
    assert k2['active'] and k2['print_file'] == 'SERVO KAPAK - V2_ABS_7h0m' and k2['used_in'] == [] and 'Servo Kapak V3 ile değiştirildi' in k2['description']
    assert (k3['per_print'], k3['parent']['code'], [x['code'] for x in k3['used_in']]) == (4, 'GVD4', ['GVD4'])
    assert (k3['print_file'], k3['print_minutes'], k3['orderable']) == ('SERVO KAPAK - V3_ABS_7h32m', 452, 0)
    assert 'SERVO KAPAK - V3' in products['CYZ4']['description']
    with db.connect() as conn:
        assert tuple(conn.execute('SELECT qty, pos FROM product_bom WHERE parent_id = ? AND child_id = ?', (gvd, k3['id'])).fetchone()) == (2, 5)
    if SERVO_SRC.is_dir():
        assert k3['gcode_file'] == 'gcode/SERVO KAPAK - V3_ABS_7h32m.gcode' and k3['gcode_preview'] and k3['gcode_thumb']

    # eski sipariş: parça listesi, montaj kapakları ve çizimi V2 ile; yeni sipariş V3 ile
    eski = ok(a.get(f'/api/orders/{o["id"]}'))
    ids = {p['part_id'] for p in eski['parts']}
    assert len(eski['parts']) == 64 and V2K in ids and V3K not in ids and eski['schema_rev'] == 'caymaz-v4-r1'
    assert next(p for p in eski['parts'] if p['part_id'] == V2K)['state'] == 'DEPO'
    ok(a.get(f'/api/orders/{o["id"]}/parts/{V2K}'))   # parça ayrıntısı eski revizyonun kataloğundan
    cizim = lambda oid: {p['id'] for p in ok(a.get(f'/api/products/{m["id"]}/plane', params={'order': oid} if oid else None))['parts']}
    assert V2K in cizim(o['id']) and V3K not in cizim(o['id'])
    assert ok(a.get(f'/api/products/{m["id"]}/plane', params={'order': o['id']}))['schema'] == 'caymaz-v4-r1'
    yeni = ok(a.post('/api/orders', json={'product_id': m['id'], 'note': 'kapak değişiminden sonra'}))[0]
    yd = ok(a.get(f'/api/orders/{yeni["id"]}'))
    yids = {p['part_id'] for p in yd['parts']}
    assert len(yd['parts']) == 64 and V3K in yids and V2K not in yids and yd['schema_rev'] is None
    assert V3K in cizim(yeni['id']) and V2K not in cizim(yeni['id']) and V3K in cizim(None)
    assert ok(a.get(f'/api/products/{m["id"]}/plane', params={'order': 999999}))['schema'] == 'caymaz-v4'   # olmayan sipariş: güncel şema
    with db.connect() as conn:
        o_eski = production.order_summaries(conn, 'o.id = ?', (o['id'],))[0]
        o_yeni = production.order_summaries(conn, 'o.id = ?', (yeni['id'],))[0]
        assert (o_eski['product_schema'], o_yeni['product_schema']) == ('caymaz-v4-r1', 'caymaz-v4')
        assert catalogs.cover_parts(o_eski['product_schema']).count(V2K) == 1 and V3K in catalogs.cover_parts(o_yeni['product_schema'])
        assert production.freeze_revisions(conn) == 0
    # 3B montaj: her revizyon kendi kapağıyla; V4'e özgü parçalar da yerleşir (türediği V2 şemasının listesine düşmez)
    for key, var, yok in (('caymaz-v4', V3K, V2K), ('caymaz-v4-r1', V2K, V3K)):
        a3 = ok(a.get(f'/api/products/assembly3d/{key}'))
        ids3 = {p['id'] for p in a3['parts']} | set(a3['missing'])
        assert set(NEW[:-1]) | {var} <= ids3 and yok not in ids3, key
        if SERVO_SRC.is_dir() and GCODE_SRC.is_dir():
            # (eski kapak ürünü bu testte G-code'suz yeniden kurulduğundan yalnız güncel kapak aranır)
            assert set(NEW[:-1]) | ({V3K} & {var}) <= {p['id'] for p in a3['parts']}, key


def db_init_seed(conn):
    """Başlangıçtaki yarı mamul tohumlaması (db.init içindeki semis.seed): katalogdan çıkan parçayı temizler —
    eski revizyonun parçası (Servo Kapak V2) katalogda sayılır, silinmez / pasifleşmez."""
    semis.seed(conn)
    conn.commit()


if __name__ == '__main__':
    main()
