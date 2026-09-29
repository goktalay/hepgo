"""Baskı dosyası / süresi ve yazıcı takibi testi: Excel'den gelen dosya-süre eşleştirmesi, dosya adı karşılaştırmalı
uyarılar (yanlış dosya, sistemde boş ama yazıcıda baskı) ve yazıcının "tamamlandı" dediği anın kaydı (bekleme süresi).

Çalıştırma: .venv/bin/python -m tests.test_print_tracking
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.alerts import norm_file  # noqa: E402
from app.main import app  # noqa: E402
from app.printer_driver import track_jobs  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def live(pid, state, file, print_s=None):
    with db.connect() as c:
        c.execute('UPDATE printers SET live_state = ?, live_file = ?, live_print_s = ? WHERE id = ?', (state, file, print_s, pid))
        track_jobs(c, db.now())


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        products = ok(a.get('/api/products'))
        by_code = {p['code']: p for p in products}
        # Excel eşleştirmesi: dosya ve süre (dakika) parça yedeklerinde
        assert (by_code['L1']['print_file'], by_code['L1']['print_minutes']) == ('c5- sol - part 1_ABS_9h16m', 556)
        assert by_code['05']['print_minutes'] == 1640 and by_code['EK']['print_file'] == 'c5 - elektronik katman_ABS_8h14m'
        assert by_code['ARABA-KAPAK']['print_minutes'] == 93 and by_code['FLAP-KAPAK']['print_minutes'] == 223
        cyz = by_code['CYZ']
        assert cyz['print_minutes_total'] == 35683 and by_code['SLK']['print_minutes_total'] > 0
        # Sipariş: yalnızca mamul ve montaj sarfı yedek parçalar
        assert [p['code'] for p in products if p['orderable']] == ['CYZ', 'KMH', 'BBK', 'KBK']
        plane = ok(a.get(f'/api/products/{cyz["id"]}/plane'))
        l1 = next(p for p in plane['parts'] if p['id'] == 'L1')
        assert l1['print_file'] == 'c5- sol - part 1_ABS_9h16m' and l1['print_minutes'] == 556
        tree = ok(a.get(f'/api/products/{cyz["id"]}/tree'))
        assert tree['print_minutes'] == 35683 and sum(n['print_minutes'] for n in tree['children']) == 35683
        # baskı süresi düzenleme (KMH için dosya ve süre girilebilir)
        ok(a.put(f'/api/products/{by_code["KMH"]["id"]}', json={'name': 'Kamera Holder', 'serial': 'KMH-YP', 'code': 'KMH',
                                                                 'queue_prefix': 'KMH', 'print_file': 'kmh_ABS_1h0m', 'print_minutes': 60}))
        assert ok(a.get(f'/api/products/{by_code["KMH"]["id"]}'))['print_minutes'] == 60

        assert norm_file('/gcodes/C5- SOL - part 1_ABS_9h16m.gcode') == norm_file('c5- sol - part 1_ABS_9h16m')

        p1 = ok(a.post('/api/printers', json={'name': 'P1', 'ip': '10.0.0.1'}))['id']
        p2 = ok(a.post('/api/printers', json={'name': 'P2', 'ip': '10.0.0.2'}))['id']
        oid = ok(a.post('/api/orders', json={'product_id': cyz['id']}))[0]['id']
        ok(a.post(f'/api/orders/{oid}/parts/L1/start', json={'printer_id': p1}))
        alerts = lambda: {x['key']: x for x in ok(a.get('/api/alerts'))['alerts']}

        # Yazıcı başka bir parçanın dosyasını basıyor → yanlış dosya uyarısı; başlangıç kaydedilmez
        live(p1, 'YAZDIRIYOR', 'c5- sol - part 2_ABS_7h9m.gcode')
        d = ok(a.get('/api/alerts/printer-wrong-file'))
        assert [(r['name'], r['part_id'], r['file_parts']) for r in d['items']] == [('P1', 'L1', ['L2'])]
        assert d['items'][0]['expected_file'] == 'c5- sol - part 1_ABS_9h16m'
        op = lambda: next(x for x in ok(a.get(f'/api/orders/{oid}'))['parts'] if x['part_id'] == 'L1')
        assert op()['printer_started_at'] is None
        # Yazıcının önceki işten kalan "tamamlandı" durumu bitiş sayılmaz (başlangıç görülmedi)
        live(p1, 'TAMAMLANDI', 'c5- sol - part 1_ABS_9h16m.gcode')
        assert op()['printer_done_at'] is None
        # Doğru dosya basılıyor → uyarı yok, yazıcıdaki başlangıç kaydedilir
        live(p1, 'YAZDIRIYOR', 'c5- sol - part 1_ABS_9h16m.gcode', 1200.7)
        assert 'printer-wrong-file' not in alerts() and op()['printer_started_at']
        # Yazdırma süresi: yazıcının bildirdiği net baskı süresi (duraklamalar hariç) parçaya işlenir
        d = ok(a.get(f'/api/orders/{oid}/parts/L1'))
        assert d['print_seconds'] == 1200 and d['printer_live']['state'] == 'YAZDIRIYOR' and d['printer_live']['print_s'] == 1200.7
        live(p1, 'DURAKLADI', 'c5- sol - part 1_ABS_9h16m.gcode', 1500)
        assert ok(a.get(f'/api/orders/{oid}/parts/L1'))['print_seconds'] == 1500
        # Yazıcı "tamamlandı" dedi → bitiş anı ve son baskı süresi kaydedilir; parça hâlâ üretimde: bekleme süresi görünür
        live(p1, 'TAMAMLANDI', 'c5- sol - part 1_ABS_9h16m.gcode', 33360)
        done_at = op()['printer_done_at']
        assert done_at and ok(a.get(f'/api/orders/{oid}/parts/L1'))['print_seconds'] == 33360
        live(p1, 'TAMAMLANDI', 'c5- sol - part 1_ABS_9h16m.gcode', 5)   # bittikten sonraki değer baskı süresini değiştirmez
        assert ok(a.get(f'/api/orders/{oid}/parts/L1'))['print_seconds'] == 33360
        stale = ok(a.get('/api/alerts/printer-stale'))['items']
        assert stale[0]['part_id'] == 'L1' and stale[0]['waiting_seconds'] is not None
        live(p1, 'TAMAMLANDI', 'c5- sol - part 1_ABS_9h16m.gcode')
        assert op()['printer_done_at'] == done_at   # ilk "tamamlandı" anı korunur
        depocu = ok(a.post('/api/users', json={'username': 'depo', 'full_name': 'Depo', 'roles': ['Depo Yöneticisi'],
                                               'password': 'sifre-1234'}))['id']
        ok(a.post(f'/api/orders/{oid}/parts/L1/finish', json={'warehouse_user_id': depocu}))
        detail = ok(a.get(f'/api/orders/{oid}/parts/L1'))
        assert detail['printer_done_at'] == done_at and detail['finished_at'] >= done_at

        # Sistemde boş yazıcıda baskı: dosya adından parça bulunur; tanımsız dosya boş liste
        live(p2, 'YAZDIRIYOR', 'c5-ortakapak-part3_ABS_4h3m.gcode')
        out = ok(a.get('/api/alerts/printer-outside'))['items']
        assert [(r['name'], r['file_parts']) for r in out] == [('P2', ['K03'])]
        live(p2, 'DURAKLADI', 'Parca9_ABS_8h38m.gcode')
        assert ok(a.get('/api/alerts/printer-outside'))['items'][0]['file_parts'] == []

        # Yeniden başlatma: önceki yazıcı kayıtları temizlenir
        ok(a.post(f'/api/orders/{oid}/parts/L2/start', json={'printer_id': p1}))
        assert next(x for x in ok(a.get(f'/api/orders/{oid}'))['parts'] if x['part_id'] == 'L2')['printer_done_at'] is None
        # ---- KRİTİK: kayıtsız baskı yarıda kesildi (sistemde parça atanmamış yazıcı yazdırırken boşa / hataya geçti)
        from app.printer_driver import detect_unrecorded_abort
        p3 = ok(a.post('/api/printers', json={'name': 'P3', 'ip': '10.0.0.3'}))['id']
        before = lambda state, part=None: {'id': p3, 'live_state': state, 'live_file': 'c5-orta-part2_ABS_18h0m.gcode',
                                           'live_progress': 37.5, 'live_since': '2026-09-28T10:00:00', 'current_part_id': part}
        with db.connect() as c:
            detect_unrecorded_abort(c, before('YAZDIRIYOR'), 'TAMAMLANDI', db.now())   # bitti: olay yok
            detect_unrecorded_abort(c, before('YAZDIRIYOR'), 'CEVRIMDISI', db.now())   # bağlantı koptu: olay yok
            detect_unrecorded_abort(c, before('YAZDIRIYOR', part=1), 'HAZIR', db.now())   # sistemde kayıtlı iş: olay yok
            detect_unrecorded_abort(c, before('HAZIR'), 'HAZIR', db.now())
            assert c.execute('SELECT COUNT(*) FROM printer_incidents').fetchone()[0] == 0
            detect_unrecorded_abort(c, before('YAZDIRIYOR'), 'HAZIR', db.now())         # iptal edildi → olay
            detect_unrecorded_abort(c, before('DURAKLADI'), 'HATA', db.now())            # duraklatılmışken hata → olay
        s = {x['key']: x for x in ok(a.get('/api/alerts'))['alerts']}
        crit = s['printer-unrecorded-abort']
        assert crit['critical'] and crit['level'] == 'danger' and crit['count'] == 2
        assert list(s)[0] == 'printer-unrecorded-abort'   # kritik uyarı en üstte
        det = ok(a.get('/api/alerts/printer-unrecorded-abort'))
        assert det['items'][0]['file_parts'] == ['02'] and det['items'][0]['live_progress'] == 37.5
        assert {i['end_state'] for i in det['items']} == {'HAZIR', 'HATA'}
        ok(a.post(f'/api/alerts/incidents/{det["items"][0]["incident_id"]}/ack'))
        assert a.post(f'/api/alerts/incidents/{det["items"][0]["incident_id"]}/ack').status_code == 404   # zaten görüldü
        assert ok(a.get('/api/alerts/printer-unrecorded-abort'))['items'].__len__() == 1
        pilot = ok(a.post('/api/users', json={'username': 'pilot@t', 'full_name': 'Pilot', 'roles': ['Pilot'], 'password': 'sifre-1234'}))
        assert pilot
    with TestClient(app) as pl:
        ok(pl.post('/api/auth/login', json={'username': 'pilot@t', 'password': 'sifre-1234'}))
        iid = ok(pl.get('/api/alerts/printer-unrecorded-abort'))['items'][0]['incident_id']   # herkes görür
        assert pl.post(f'/api/alerts/incidents/{iid}/ack').status_code == 403   # yalnızca yazıcı / üretim sorumluları kapatır
    print('Baskı dosyası ve yazıcı takibi testleri geçti.')


if __name__ == '__main__':
    main()
