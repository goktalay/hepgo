"""CAYMAZ V4 testi: V4 şeması (V2 kopyası; L2, L3, R2, R3, 08, 09 → -V4 ve servo kapağı), başlangıçta idempotent kurulum
(ensure_versions: V3 + V4; iki çalıştırmada çift kayıt yok), ürün ağacı (V2 ile aynı yapı + servo kapağı), yalnızca
V4'te olan 7 parçanın yedek parça kayıtları (baskı dosyası / süresi), montaj sarfı kullanımı, G-code bağlama
(gcode_file / gcode_preview / gcode_thumb; 2B resim ÜRETİLMEZ, V2 karşılığının resmi aynen kullanılır), sipariş.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_caymaz_v4
"""
import os
import shutil
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, plane_v2, plane_v4, semis, spares  # noqa: E402
from app.print_files import PRINT_FILES  # noqa: E402
from app.main import app  # noqa: E402

GCODE_SRC = Path(os.environ.get('CAYMAZ_V4_GCODE', '/opt/hepgo/incoming/caymazv4_parcalar'))
NEW = ['L2-V4', 'L3-V4', 'R2-V4', 'R3-V4', '08-V4', '09-V4', 'SERVO-KAPAK-V2']


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    v2, v4 = set(plane_v2.part_ids()), set(plane_v4.part_ids())
    assert len(v4) == len(v2) + 1 == 64 and plane_v4.NEW_PARTS == NEW
    assert v4 - v2 == set(NEW) and v2 - v4 == set(plane_v4.CHANGED)
    servo = next(p for p in plane_v4.build() if p['id'] == 'SERVO-KAPAK-V2')
    assert servo['group'] == 'cover' and servo['layer'] == 'cover' and servo['section'] == 'GOVDE' and servo['hosts'] == ['02']
    for p in plane_v4.build():   # yeni parçalar V2 parçasıyla aynı yer / aynı yarı mamul
        if p['id'] in plane_v4.CHANGED.values():
            old = next(k for k, v in plane_v4.CHANGED.items() if v == p['id'])
            o = next(q for q in plane_v2.build() if q['id'] == old)
            assert p['shapes'] == o['shapes'] and p['section'] == o['section'], p['id']
    assert all(k in PRINT_FILES for k in NEW) and PRINT_FILES['L2-V4'] == ('L2 - V3 _ABS_7h33m', 453)
    assert PRINT_FILES['08-V4'][1] == 16 * 60 + 46 and PRINT_FILES['SERVO-KAPAK-V2'][1] == 420

    # G-code dosyaları veri klasörüne (uploads/gcode): başlangıçta bağlanır
    folder = Path(tmp) / 'uploads' / 'gcode'
    folder.mkdir(parents=True)
    have_gcode = GCODE_SRC.is_dir()
    if have_gcode:
        for f in GCODE_SRC.glob('*.gcode'):
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
        assert len([c for c in products if c.endswith('-V4')]) == 6 and 'SERVO-KAPAK-V2' in products
        m = products['CYZ4']
        assert (m['name'], m['serial'], m['type'], m['orderable'], m['schema'], m['queue_prefix'], m['part_count']) == \
            ('CAYMAZ V4', 'CYZ-S4', 'MAMUL', 1, 'caymaz-v4', 'CYZ4', 64)
        assert m['description'].startswith('CAYMAZ V2 ile aynı yapı; L2, L3, R2, R3')
        for code in NEW:   # yedek parça kayıtları
            p = products[code]
            assert p['schema'] == f'part-{code}' and p['parent']['code'] in ('SLK4', 'SGK4', 'GVD4') and not p['orderable']
            assert (p['print_file'], p['print_minutes']) == PRINT_FILES[code], code
        assert products['L2-V4']['parent']['code'] == 'SLK4' and products['R3-V4']['parent']['code'] == 'SGK4'
        assert products['08-V4']['parent']['code'] == 'GVD4' and products['SERVO-KAPAK-V2']['parent']['code'] == 'GVD4'
        assert products['SERVO-KAPAK-V2']['name'] == 'Servo Kapak V2'
        assert [x['code'] for x in products['L2']['used_in']] == ['SLK', 'SLK2', 'SLK3']   # eski L2 V4'te yok
        assert [x['code'] for x in products['L2-V4']['used_in']] == ['SLK4']
        assert [x['code'] for x in products['L17']['used_in']] == ['SLK', 'SLK2', 'SLK3', 'SLK4']   # ortak parça

        tree = ok(a.get(f'/api/products/{m["id"]}/tree'))
        assert [n['code'] for n in tree['children']] == ['SLK4', 'SGK4', 'GVD4', 'ELK4']
        parts = {n['code']: {c['code'] for c in n['children'] if c['part_spare']} for n in tree['children']}
        assert [len(parts[c]) for c in ('SLK4', 'SGK4', 'GVD4', 'ELK4')] == [22, 22, 18, 2]   # V2: 22, 22, 17, 2 + servo kapağı
        assert {'L2-V4', 'L3-V4', 'L4-V2', 'L17'} <= parts['SLK4'] and not ({'L2', 'L3', 'L4-V3'} & parts['SLK4'])
        assert {'08-V4', '09-V4', 'SERVO-KAPAK-V2', '01-V2', 'K08'} <= parts['GVD4'] and not ({'08-V2', '09', '01-V3'} & parts['GVD4'])
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
        assert pj['SERVO-KAPAK-V2']['hosts'] == ['02'] and pj['L2-V4']['print_file'] == 'L2 - V3 _ABS_7h33m'
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
    print('CAYMAZ V4 testleri geçti.')


if __name__ == '__main__':
    main()
