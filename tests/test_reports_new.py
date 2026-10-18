"""Yeni modül raporları (Uçuş Simülatörü, Kamera Olayları, Tasarım Sürümleri, Firma Veri Doluluğu, Şirketten Haberler,
Duyuru Okunma, Canlı Konum Sinyalleri) ve Üyelik › Paketinizdeki Modüller uç noktası: yapı, yetki, tarih filtresi, boş veri.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_reports_new
"""
import os
import tempfile
from datetime import date, datetime, timedelta

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_DRONE_PKG='1', CAYMAZ_MASTER_USERNAME='admin@test', CAYMAZ_FEDERATION_URL='https://merkez.test',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, reports  # noqa: E402
from app.main import app  # noqa: E402

NEW = ['sim-ucus', 'kamera-olay', 'tasarim-surum', 'firma-veri-doluluk', 'haber-etkilesim', 'duyuru-okunma', 'konum-sinyal']
MODULE_OF = {'sim-ucus': 'drone', 'kamera-olay': 'cameras', 'tasarim-surum': 'design', 'firma-veri-doluluk': 'companies',
             'haber-etkilesim': 'announcements', 'duyuru-okunma': 'announcements', 'konum-sinyal': 'konum'}


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def check(d):
    assert set(d) >= {'kpis', 'insights', 'charts', 'tables', 'params', 'title', 'module'}
    for k in d['kpis']:
        assert 'label' in k and 'value' in k
    for c in d['charts']:
        if c['type'] == 'heat':
            assert len(c['heat']['values']) == 7 and all(len(r) == 24 for r in c['heat']['values'])
        else:
            assert all(len(ds['data']) == len(c['labels']) for ds in c['datasets']), (d['key'], c['title'])
    for t in d['tables']:
        keys = {c['key'] for c in t['columns']}
        assert all(keys <= set(r) for r in t['rows']), (d['key'], t['title'])


def kpi(d, label):
    return next(k['value'] for k in d['kpis'] if k['label'] == label)


def ts(days_ago, hour=10):
    return (datetime.now() - timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0, microsecond=0).isoformat(timespec='seconds')


def seed(conn, admin_id):
    """Dönem içinde (bugün / 2 gün önce) ve dönem dışında (40 gün önce) birer kayıt: tarih filtresi ayrımı görünsün."""
    now = db.now()
    # Simülatör koşuları
    for i, (ago, res, cc, dur) in enumerate([(0, 'tamam', 0, 600), (2, 'carpisma', 2, 120), (40, 'tamam', 0, 900)]):
        conn.execute('''INSERT INTO drone_sim_runs (session_id, owner_id, owner_name, type, center_name, started_at, ended_at, duration_s, mode, result, crash_count, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sitl', ?, ?, ?)''', (i + 1, admin_id, 'Pilot A' if i else 'Pilot B', 'multirotor' if i != 1 else 'sabit_kanat', 'Ankara', ts(ago), ts(ago), dur, res, cc, now))
    # Kamera: iki kamera, tanınan + tanımsız görülme, İSG alarmı
    cam = conn.execute("INSERT INTO cameras (name, created_at) VALUES ('Giriş', ?)", (now,)).lastrowid
    g_known = conn.execute("INSERT INTO face_groups (user_id, centroid, first_seen, last_seen) VALUES (?, X'00', ?, ?)", (admin_id, now, now)).lastrowid
    g_unknown = conn.execute("INSERT INTO face_groups (centroid, first_seen, last_seen) VALUES (X'00', ?, ?)", (now, now)).lastrowid
    for g, ago in ((g_known, 0), (g_known, 1), (g_unknown, 2), (g_known, 40)):
        conn.execute("INSERT INTO face_sightings (group_id, camera_id, at, crop, frame, embedding) VALUES (?, ?, ?, 'c', 'f', X'00')", (g, cam, ts(ago)))
    conn.execute("INSERT INTO isg_alarms (camera_id, camera_name, missing, at, created_at) VALUES (?, 'Giriş', 'kask', ?, ?)", (cam, ts(1), now))
    # Tasarım: proje, çizim, 2 sürüm (biri dönem dışı), not
    pid = conn.execute("INSERT INTO design_projects (name, created_by, created_at) VALUES ('Kanat', ?, ?)", (admin_id, ts(2))).lastrowid
    did = conn.execute("INSERT INTO design_drawings (project_id, name, kind, created_by, created_at) VALUES (?, 'Kanat v1', 'drawing', ?, ?)", (pid, admin_id, ts(2))).lastrowid
    conn.execute("INSERT INTO design_drawing_versions (drawing_id, version, file_name, size, uploaded_by, created_at) VALUES (?, 1, 'k.step', 2048, ?, ?)", (did, admin_id, ts(1)))
    conn.execute("INSERT INTO design_drawing_versions (drawing_id, version, file_name, size, uploaded_by, created_at) VALUES (?, 0, 'k0.step', 1024, ?, ?)", (did, admin_id, ts(40)))
    conn.execute("INSERT INTO design_drawing_notes (drawing_id, note, created_by, created_at) VALUES (?, 'ilk not', ?, ?)", (did, admin_id, ts(0)))
    # Şirketten Haberler: 2 paylaşım, tepki, yorum, görüntüleme
    p1 = conn.execute("INSERT INTO feed_posts (kind, author_id, text, created_at) VALUES ('USER', ?, 'Merhaba', ?)", (admin_id, ts(0))).lastrowid
    p2 = conn.execute("INSERT INTO feed_posts (kind, author_id, text, created_at) VALUES ('FLIGHT', ?, 'Uçuş', ?)", (admin_id, ts(40))).lastrowid
    conn.execute("INSERT INTO feed_reactions (post_id, user_id, emoji, created_at) VALUES (?, ?, '👍', ?)", (p1, admin_id, ts(0)))
    conn.execute("INSERT INTO feed_comments (post_id, user_id, text, created_at) VALUES (?, ?, 'süper', ?)", (p1, admin_id, ts(0)))
    conn.execute("INSERT INTO feed_views (post_id, user_id, at) VALUES (?, ?, ?)", (p1, admin_id, ts(0)))
    conn.execute("INSERT INTO feed_views (post_id, user_id, at) VALUES (?, ?, ?)", (p2, admin_id, ts(40)))
    # Duyuru + okuma
    aid = conn.execute("INSERT INTO announcements (title, body, level, created_by, created_at) VALUES ('Kritik duyuru', 'x', 'KRITIK', ?, ?)", (admin_id, ts(1))).lastrowid
    conn.execute('INSERT INTO announcement_reads (announcement_id, user_id, read_at) VALUES (?, ?, ?)', (aid, admin_id, ts(1)))
    # Canlı konum sinyalleri
    for ago, acc in ((0, 12.0), (0, 80.0), (1, 30.0), (40, 5.0)):
        conn.execute('INSERT INTO location_pings (user_id, lat, lng, accuracy, at, platform, created_at) VALUES (?, 39.9, 32.8, ?, ?, ?, ?)', (admin_id, acc, ts(ago), 'android', ts(ago)))
    conn.commit()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        allr = ok(a.get('/api/reports'))
        keys = {r['key'] for r in allr}
        assert set(NEW) <= keys, set(NEW) - keys
        assert len(allr) == len(reports.REPORTS) >= 29
        for k in NEW:   # boş veri: yapı doğru, hata yok
            d = ok(a.get(f'/api/reports/{k}'))
            check(d)
            assert d['module'] == MODULE_OF[k]
        d = ok(a.get('/api/reports/sim-ucus'))
        assert kpi(d, 'Koşu') == 0 and d['insights'] == []
        # Veri ekle
        with db.connect() as c:
            admin_id = c.execute("SELECT id FROM users WHERE username = 'admin@test'").fetchone()[0]
            seed(c, admin_id)
        ok(a.post('/api/companies', json={'name': 'Logosuz AŞ', 'phone': '0312'}))
        ok(a.post('/api/companies', json={'name': 'Tam Firma', 'phone': '0312', 'email': 'a@b.c', 'website': 'https://x.y', 'address': 'Ankara'}))
        today = date.today()
        q30 = f'date_from={(today - timedelta(29)).isoformat()}&date_to={today.isoformat()}'
        q1 = f'date_from={(today - timedelta(1)).isoformat()}&date_to={today.isoformat()}'
        # Simülatör: 30 günde 2 koşu (40 gün önceki dışarıda), 2 çarpışma; son 2 günde 1 koşu
        d = ok(a.get(f'/api/reports/sim-ucus?{q30}'))
        check(d)
        assert kpi(d, 'Koşu') == 2 and kpi(d, 'Çarpışma') == 2 and kpi(d, 'Pilot') == 2, d['kpis']
        assert len(d['charts'][0]['labels']) == 30 and sum(d['charts'][0]['datasets'][0]['data']) == 2
        assert d['tables'][2]['rows'][0]['sonuc'] == 'Tamam' and d['tables'][2]['rows'][1]['sonuc'] == 'Çarpışma'
        assert kpi(ok(a.get(f'/api/reports/sim-ucus?{q1}')), 'Koşu') == 1
        # Kamera: 3 görülme (2 tanınan, 1 tanımsız), 1 alarm onaysız
        d = ok(a.get(f'/api/reports/kamera-olay?{q30}'))
        check(d)
        assert kpi(d, 'Yüz görülme') == 3 and kpi(d, 'Tanınan') == 2 and kpi(d, 'Tanımsız') == 1 and kpi(d, 'İSG alarmı') == 1
        assert d['tables'][0]['rows'][0] == {'cam': 'Giriş', 'n': 3, 'alarm': 1}
        assert d['tables'][1]['rows'][0]['durum'] == 'Onaysız'
        # Tasarım: 1 yeni proje, 1 çizim, 1 sürüm (eski sürüm dışarıda), 1 not
        d = ok(a.get(f'/api/reports/tasarim-surum?{q30}'))
        check(d)
        assert kpi(d, 'Yeni proje') == 1 and kpi(d, 'Yeni çizim / montaj') == 1 and kpi(d, 'Yüklenen sürüm') == 1 and kpi(d, 'Not') == 1
        assert d['tables'][0]['rows'][0]['proje'] == 'Kanat' and d['tables'][0]['rows'][0]['ver'] == 1
        # Firma doluluğu: 2 aktif firma (+ varsayılan kayıtlar olabilir); logolu 0; eksik listesinde Logosuz AŞ
        d = ok(a.get(f'/api/reports/firma-veri-doluluk?{q30}'))
        check(d)
        n = kpi(d, 'Aktif firma')
        assert n >= 2 and kpi(d, 'Logolu') == 0 and kpi(d, 'Dönemde eklenen') >= 2
        miss = {r['firma']: r for r in d['tables'][1]['rows']}
        assert 'Logosuz AŞ' in miss and 'E-posta' in miss['Logosuz AŞ']['eksik'] and 'Logo' in miss['Tam Firma']['eksik']
        assert miss['Logosuz AŞ']['n'] > miss['Tam Firma']['n']
        assert d['charts'][0]['max'] == 100 and len(d['charts'][0]['labels']) == 7
        # Haberler: 1 paylaşım dönemde (40 günlük dışarıda), 1 tepki, 1 yorum, 1 görüntüleme
        d = ok(a.get(f'/api/reports/haber-etkilesim?{q30}'))
        check(d)
        assert kpi(d, 'Paylaşım') == 1 and kpi(d, 'Tepki') == 1 and kpi(d, 'Yorum') == 1 and kpi(d, 'Görüntüleme') == 1
        assert d['tables'][0]['rows'][0]['text'] == 'Merhaba' and d['charts'][1]['labels'] == ['Kullanıcı paylaşımı']
        # Duyuru: 1 kritik duyuru, 1 okuma
        d = ok(a.get(f'/api/reports/duyuru-okunma?{q30}'))
        check(d)
        assert kpi(d, 'Duyuru') == 1 and kpi(d, 'Toplam okuma') == 1 and kpi(d, 'Kritik') == 1
        assert d['tables'][0]['rows'][0]['level'] == 'Kritik'
        # Konum: 3 sinyal dönemde, 1 kişi, 2 sinyalli gün; ortanca doğruluk 30 m
        d = ok(a.get(f'/api/reports/konum-sinyal?{q30}'))
        check(d)
        assert kpi(d, 'Sinyal') == 3 and kpi(d, 'Kişi') == 1 and kpi(d, 'Sinyalli gün') == '2 / 30' and kpi(d, 'Ortanca doğruluk') == '30 m'
        assert len(d['tables'][1]['rows']) == 2 and d['charts'][0]['datasets'][1]['axis'] == 'y2'
        # Tarih doğrulama (mevcut kural)
        assert a.get('/api/reports/sim-ucus?date_from=2026-02-30').status_code == 400
        assert a.get('/api/reports/konum-sinyal?date_from=2024-01-01&date_to=2026-01-01').status_code == 400
        # Üyelik › Paketinizdeki Modüller: master için her şey açık; CAYMAZ_MODULES kısıtı → 'missing'
        m = ok(a.get('/api/membership/modules'))
        states = {x['key']: x['state'] for x in m['modules']}
        assert states['reports'] == 'open' and states['drone'] == 'open' and states['companies'] == 'open', states
        assert 'uyelik' not in states and 'users' not in states and 'orders' not in states
        assert states['pos'] == 'missing'   # esnaf paketi yok
        assert m['in_package'] == sum(1 for s in states.values() if s != 'missing')
        old = config.MODULES
        config.MODULES = ['admin', 'reports', 'companies', 'uyelik']
        try:
            states2 = {x['key']: x['state'] for x in ok(a.get('/api/membership/modules'))['modules']}
        finally:
            config.MODULES = old
        assert states2['reports'] == 'missing' or states2['reports'] == 'open'   # 'reports' kullanıcı modüllerinde (master) → open
        assert states2['design'] == 'missing' and states2['hr'] == 'missing' and states2['companies'] == 'open', states2
        ok(a.post('/api/users', json={'username': 'sek', 'full_name': 'Sekreter', 'roles': ['Sekreter'], 'password': 'sifre-1234'}))
    with TestClient(app) as s:   # Sekreter: yalnız sekreterya raporları; yeni raporlar 404 (yetkisi olmayan modül)
        ok(s.post('/api/auth/login', json={'username': 'sek', 'password': 'sifre-1234'}))
        mods = {r['module'] for r in ok(s.get('/api/reports'))}
        assert mods == {'secretariat', 'announcements'}, mods   # Sekreter rolünde Duyurular açık → haber / duyuru raporları görünür
        for k in NEW:
            code = 200 if MODULE_OF[k] == 'announcements' else 404
            assert s.get(f'/api/reports/{k}').status_code == code, (k, code)
        check(ok(s.get('/api/reports/haber-etkilesim')))
    print(f'Yeni rapor testleri geçti ({len(NEW)} yeni rapor, toplam {len(reports.REPORTS)}).')


if __name__ == '__main__':
    main()
