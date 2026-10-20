"""Mastertool (SSH Master + FTP Masters tek hesap) testleri: v1 şemasından geçiş, uygulama bazında oturum / lisans / kütüphane,
/api/fm, parçalı sürüm yükleme, Host'a göre site + portal yönlendirmesi, marka bazlı e-posta, destek köprüsü.
Çalıştırma (central/sshmaster_server içinde): ../../.venv/bin/python -m tests.test_mastertool"""
import base64
import hashlib
import os
import re
import sqlite3
import tempfile

D = tempfile.mkdtemp()
os.environ.update(SSHM_DATA_DIR=D, SSHM_ENV_FILE=os.path.join(D, 'yok.env'), VEILOX_ENV_FILE=os.path.join(D, 'yok2.env'),
                  SSHM_MAIL_TEST='1', SSHM_CENTRAL_SECRET='merkez-gizli', SSHM_RELEASE_KEY='sm-anahtar', FTPM_RELEASE_KEY='fm-anahtar',
                  SQLM_RELEASE_KEY='sq-anahtar', NOTEPADM_RELEASE_KEY='np-anahtar', CONVERTM_RELEASE_KEY='cv-anahtar', MASTERTOOL_RELEASE_KEY='mt-anahtar', IPTOOLS_RELEASE_KEY='ip-anahtar', SIMUMAV_RELEASE_KEY='sv-anahtar', SIMUMAV_MT_SHARED_SECRET='sv-gizli', SSHM_SECURE_COOKIE='0', SSHM_SALT_KEY='test-tuz', SSHM_PUBLIC_URL='https://sshmasters.com', MT_PORTAL_LIVE='0')

# ---- v1 (SSH Master) şemasıyla dolu bir veritabanı: geçiş verileri korumalı
V1 = """
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL, pw_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'BEKLIYOR', verified_at TEXT, kdf_salt TEXT NOT NULL, sync_enabled INTEGER NOT NULL DEFAULT 1,
  dl_token TEXT NOT NULL UNIQUE, note TEXT, created_at TEXT NOT NULL, last_login TEXT);
CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL, device TEXT, app_version TEXT, ip TEXT, created_at TEXT NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE tokens (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE, salt TEXT, expires REAL NOT NULL, used_at TEXT);
CREATE TABLE libraries (user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, version INTEGER NOT NULL, blob TEXT NOT NULL,
  size INTEGER NOT NULL, device TEXT, updated_at TEXT NOT NULL);
CREATE TABLE releases (id INTEGER PRIMARY KEY, version TEXT NOT NULL UNIQUE, setup_file TEXT NOT NULL, setup_size INTEGER NOT NULL,
  setup_sha256 TEXT NOT NULL, portable_file TEXT, portable_size INTEGER, notes TEXT, created_at TEXT NOT NULL);
CREATE TABLE downloads (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  release_id INTEGER REFERENCES releases(id) ON DELETE SET NULL, kind TEXT NOT NULL, ip TEXT, at TEXT NOT NULL);
"""


def auth_hash(password, kdf):
    pw = password.encode()
    master = hashlib.pbkdf2_hmac('sha256', pw, base64.b64decode(kdf['salt']), kdf['iter'], 32)
    return base64.b64encode(hashlib.pbkdf2_hmac('sha256', master, pw, 1, 32)).decode()


def seed_v1():
    from sshm.main import SERVER_ITER  # noqa: F401 (yalnız hash biçimi için)
    from sshm.main import hash_auth, sha
    salt = 'AAECAwQFBgcICQoLDA0ODw=='
    conn = sqlite3.connect(os.path.join(D, 'sshm.db'))
    conn.executescript(V1)
    conn.execute("INSERT INTO users VALUES (1,'eski@test.com','Eski Kullanıcı',?, 'AKTIF','2026-10-01T10:00:00',?,0,'dl-eski',NULL,'2026-10-01T10:00:00',NULL)",
                 (hash_auth(auth_hash('Eski-1234', {'salt': salt, 'iter': 310000})), salt))
    conn.execute("INSERT INTO sessions VALUES (1,1,?,'app','ESKI-PC','1.1.0','1.1.1.1','2026-10-01T10:00:00',strftime('%s','now'))", (sha('eski-token'),))
    conn.execute("INSERT INTO libraries VALUES (1,7,?,40,'ESKI-PC','2026-10-02T10:00:00')", (base64.b64encode(b'x' * 40).decode(),))
    conn.execute("INSERT INTO releases VALUES (5,'1.1.0','SSH Master Setup 1.1.0.exe',4,'abc',NULL,NULL,'v1 notu','2026-10-01T10:00:00')")
    conn.execute("INSERT INTO downloads VALUES (1,1,5,'setup','1.1.1.1','2026-10-01T11:00:00')")
    conn.commit()
    conn.close()
    os.makedirs(os.path.join(D, 'releases', '1.1.0'), exist_ok=True)
    with open(os.path.join(D, 'releases', '1.1.0', 'SSH Master Setup 1.1.0.exe'), 'wb') as f:
        f.write(b'MZv1')
    return salt


def main():
    salt_v1 = seed_v1()
    from fastapi.testclient import TestClient
    from sshm import mailer, merkez, settings
    from sshm.main import app
    W = {'X-SSHM': '1'}
    ADMIN = {'X-Central-Secret': 'merkez-gizli'}

    with TestClient(app, base_url='https://testserver') as c:
        # ---- geçiş: v1 verileri sm'e bağlandı, FK'ler sağlam, eski token çalışıyor
        conn = sqlite3.connect(os.path.join(D, 'sshm.db'))
        conn.row_factory = sqlite3.Row
        assert dict(conn.execute('SELECT app, version, size FROM libraries').fetchone()) == {'app': 'sm', 'version': 7, 'size': 40}
        assert dict(conn.execute('SELECT id, app, version FROM releases').fetchone()) == {'id': 5, 'app': 'sm', 'version': '1.1.0'}
        assert dict(conn.execute('SELECT app, release_id FROM downloads').fetchone()) == {'app': 'sm', 'release_id': 5}
        assert conn.execute('SELECT app FROM sessions').fetchone()[0] == 'sm'
        assert dict(conn.execute('SELECT license, sync_enabled FROM user_apps WHERE user_id = 1').fetchone()) == {'license': 'AKTIF', 'sync_enabled': 0}
        fk = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'downloads'").fetchone()[0]
        assert 'REFERENCES releases(id)' in fk and 'releases_v1' not in fk, fk
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        conn.close()
        OLD = {'Authorization': 'Bearer eski-token'}
        me = c.get('/api/sm/me', headers=OLD).json()
        assert me['user']['email'] == 'eski@test.com' and me['library']['version'] == 7 and me['sync_enabled'] is False, me
        # aynı e-posta + şifreyle /api/fm girişi (yeniden kayıt yok)
        k = c.post('/api/fm/auth/prelogin', json={'email': 'eski@test.com'}).json()['kdf']
        assert k['salt'] == salt_v1
        r = c.post('/api/fm/auth/login', json={'email': 'eski@test.com', 'auth_hash': auth_hash('Eski-1234', k), 'device': 'FTP-PC', 'app_version': '1.0.0'})
        assert r.status_code == 200 and r.json()['token'] and r.json()['sync_enabled'] is True, r.text   # fm senkronu ayrı, varsayılan açık
        FM = {'Authorization': 'Bearer ' + r.json()['token']}
        # oturum yalnız kendi uygulamasının uçlarında
        _r = c.get('/api/sm/library', headers=FM); assert _r.json().get('code') == 'wrong_app', _r.text
        assert c.get('/api/fm/library', headers=OLD).json()['code'] == 'wrong_app'
        assert c.get('/api/fm/me', headers=FM).json()['library']['version'] == 0
        # kütüphaneler ayrı
        blob = base64.b64encode(os.urandom(64)).decode()
        assert c.put('/api/fm/library', headers=FM, json={'base_version': 0, 'blob': blob}).json() == {'version': 1}
        assert c.get('/api/sm/library', headers=OLD).json()['version'] == 7
        assert c.get('/api/fm/library', headers=FM).json()['blob'] == blob
        assert c.put('/api/fm/settings', headers=FM, json={'sync_enabled': False}).json() == {'sync_enabled': False}
        assert c.get('/api/sm/me', headers=OLD).json()['sync_enabled'] is False and c.get('/api/fm/me', headers=FM).json()['sync_enabled'] is False
        assert c.get('/api/xx/health').status_code == 404 and c.get('/api/mt/library').status_code == 404

        # ---- sürümler: fm anahtarı yalnız fm; tek istek + parçalı + taşınabilir ekleme
        exe = b'MZ' + os.urandom(3000)
        f = {'setup': ('x.exe', exe, 'application/octet-stream')}
        assert c.post('/api/fm/releases', data={'version': '1.0.0'}, files=f, headers={'X-Release-Key': 'sm-anahtar'}).status_code == 403
        r = c.post('/api/fm/releases', data={'version': '1.0.0', 'notes': 'İlk FTP Masters'}, files=f, headers={'X-Release-Key': 'fm-anahtar'})
        assert r.status_code == 200 and r.json()['sha256'] == hashlib.sha256(exe).hexdigest(), r.text
        assert os.path.isfile(os.path.join(D, 'releases', 'fm', '1.0.0', 'x.exe'))
        big = b'MZ' + os.urandom(5000)
        K = {'X-Release-Key': 'fm-anahtar'}
        r = c.post('/api/fm/releases/1.1.0/setup', data={'part': '0', 'parts': '2'}, files={'file': ('blob', big[:2500])}, headers=K)
        assert r.json() == {'ok': True, 'received': 2500}, r.text
        assert c.post('/api/fm/releases/1.1.0/setup', data={'part': '1', 'parts': '2'}, files={'file': ('blob', big[2500:])},
                      headers=K | {'X-Part-Offset': '999'}).json()['code'] == 'part_order'
        r = c.post('/api/fm/releases/1.1.0/setup', data={'part': '1', 'parts': '2', 'notes': 'parçalı', 'filename': 'FTP-Masters-Setup-1.1.0.exe'},
                   files={'file': ('blob', big[2500:])}, headers=K)
        assert r.status_code == 200 and r.json()['sha256'] == hashlib.sha256(big).hexdigest() and r.json()['size'] == len(big), r.text
        assert c.post('/api/fm/releases/1.1.0/setup', data={}, files={'file': ('b', big)}, headers=K).json()['code'] == 'exists'
        assert c.post('/api/fm/releases/9.9.9/portable', data={}, files={'file': ('b', big)}, headers=K).json()['code'] == 'no_release'
        assert c.post('/api/fm/releases/1.1.0/portable', data={}, files={'file': ('p.exe', b'XXnotexe')}, headers=K).json()['code'] == 'not_exe'
        port = b'MZ' + b'p' * 100
        r = c.post('/api/fm/releases/1.1.0/portable', data={}, files={'file': ('FTP-Masters-Portable-1.1.0.exe', port)}, headers=K)
        assert r.status_code == 200 and r.json()['kind'] == 'portable', r.text
        # SSH Master: var olan sürüme taşınabilir dosya eklenebilir (Cloudflare 100 MB sınırı için ayrı istek)
        r = c.post('/api/sm/releases/1.1.0/portable', data={}, files={'file': ('SSH-Master-Portable-1.1.0.exe', b'MZport')}, headers={'X-Release-Key': 'sm-anahtar'})
        assert r.status_code == 200, r.text
        assert c.get('/api/fm/releases/latest', headers=FM).json()['version'] == '1.1.0'
        assert c.get('/api/sm/releases/latest', headers=OLD).json() | {} and c.get('/api/sm/releases/latest', headers=OLD).json()['portable'] is True

        # ---- web: portal hesabı (her iki uygulama), indirme bağlantıları uygulama bazında
        r = c.post('/api/mt/auth/login', json={'email': 'eski@test.com', 'auth_hash': auth_hash('Eski-1234', k)})
        assert r.status_code == 200 and 'token' not in r.json() and 'sm_session' in r.cookies, r.text   # /api/mt her zaman web oturumu
        acc = c.get('/api/mt/account').json()
        apps = {a['app']: a for a in acc['apps']}
        assert apps['sm']['release']['version'] == '1.1.0' and apps['fm']['release']['version'] == '1.1.0' and apps['fm']['library']['version'] == 1
        assert apps['sm']['download_url'] == '/indir/dl-eski' and apps['fm']['download_url'] == '/indir/dl-eski/fm'
        assert {s['app'] for s in acc['sessions'] if s['kind'] == 'app'} == {'sm', 'fm'}
        assert acc['download_url'] == '/indir/dl-eski' and acc['release']['version'] == '1.1.0'   # v1 alanları
        r = c.get('/indir/dl-eski/fm')
        assert r.status_code == 200 and r.content == big and 'FTP-Masters-Setup-1.1.0.exe' in r.headers['content-disposition']
        assert c.get('/indir/dl-eski/fm?tur=portable').content == port
        assert c.get('/indir/dl-eski').content == b'MZv1'   # v1 yolundaki SSH Master dosyası
        assert c.get('/indir/dl-eski/xx').status_code == 404

        # ---- uygulama lisansı: fm KAPALI → fm girişi/oturumu/indirme kapanır, sm etkilenmez
        uid = next(u['id'] for u in c.get('/api/sm/admin/users', headers=ADMIN).json()['users'] if u['email'] == 'eski@test.com')
        assert c.put(f'/api/sm/admin/users/{uid}', headers=ADMIN, json={'apps': {'fm': 'YOK'}}).status_code == 422
        assert c.put(f'/api/sm/admin/users/{uid}', headers=ADMIN, json={'apps': {'fm': 'KAPALI'}}).json()['ok']
        assert c.get('/api/fm/me', headers=FM).json()['code'] in ('session_expired', 'unauthorized')   # fm oturumu düştü
        r = c.post('/api/fm/auth/login', json={'email': 'eski@test.com', 'auth_hash': auth_hash('Eski-1234', k)})
        assert r.status_code == 403 and r.json()['code'] == 'app_disabled' and 'FTP Masters' in r.json()['message'], r.text
        assert c.get('/api/sm/me', headers=OLD).status_code == 200
        assert c.get('/indir/dl-eski/fm').status_code == 403 and c.get('/indir/dl-eski').status_code == 200
        au = c.get('/api/sm/admin/users', headers=ADMIN).json()
        row = next(u for u in au['users'] if u['id'] == uid)
        assert row['apps']['fm']['license'] == 'KAPALI' and row['apps']['sm']['lib_version'] == 7 and au['stats']['apps']['fm']['release']['version'] == '1.1.0'
        det = c.get(f'/api/sm/admin/users/{uid}', headers=ADMIN).json()
        assert det['apps']['fm']['downloads'] == 2 and {x['app'] for x in det['downloads']} == {'sm', 'fm'}
        c.put(f'/api/sm/admin/users/{uid}', headers=ADMIN, json={'apps': {'fm': 'AKTIF'}})
        assert c.post('/api/fm/auth/login', json={'email': 'eski@test.com', 'auth_hash': auth_hash('Eski-1234', k)}).status_code == 200
        assert [r['version'] for r in c.get('/api/sm/admin/releases?app=fm', headers=ADMIN).json()] == ['1.1.0', '1.0.0']
        assert [r['app'] for r in c.get('/api/sm/admin/releases', headers=ADMIN).json()].count('sm') == 1

        # ---- şifre değişince TÜM uygulama kütüphaneleri silinir
        me = c.get('/api/mt/me').json()
        fresh = c.post('/api/mt/auth/new-salt', headers=W).json()['kdf']
        assert c.post('/api/mt/auth/change-password', headers=W, json={'old_auth_hash': auth_hash('Eski-1234', me['kdf']),
                      'new_auth_hash': auth_hash('Yeni-5678', fresh), 'new_salt': fresh['salt']}).json() == {'ok': True}
        conn = sqlite3.connect(os.path.join(D, 'sshm.db'))
        assert conn.execute('SELECT COUNT(*) FROM libraries').fetchone()[0] == 0
        conn.close()

        # ---- marka bazlı e-posta (kayıt FTP Masters sitesinden)
        k2 = c.post('/api/mt/auth/prelogin', json={'email': 'yeni@test.com'}).json()['kdf']
        c2 = TestClient(app, base_url='https://testserver')
        assert c2.post('/api/mt/auth/register', json={'name': 'Yeni', 'email': 'yeni@test.com', 'auth_hash': auth_hash('Yeni-1111', k2), 'brand': 'fm'}).json()['ok']
        m = mailer.OUTBOX[-1]
        assert m['subject'].startswith('FTP Masters') and m['from_name'] == 'FTP Masters' and '/brand/fm.png' in m['html'] and 'Mastertool' in m['text'], m
        assert 'veilox' not in (m['html'] + m['text']).lower()
        c2.post('/api/mt/auth/forgot', json={'email': 'yeni@test.com', 'brand': 'xx'})
        assert mailer.OUTBOX[-1]['subject'] == 'Mastertool: e-posta adresinizi doğrulayın' or mailer.OUTBOX[-1]['from_name'] == 'Mastertool'
        c2.get(re.search(r'https://sshmasters\.com(/dogrula/\S+)', m['text']).group(1))
        assert c2.get('/api/mt/account').json()['user']['email'] == 'yeni@test.com'
        # yeni kullanıcı: iki uygulamada da lisans açık
        assert {a['license'] for a in c2.get('/api/mt/account').json()['apps']} == {'AKTIF'}

        # ---- destek köprüsü (Merkez sahte): kullanıcı yalnız kendi e-postasıyla, hata ayrıntısı sızmaz
        calls = []

        def fake(method, path, json=None, params=None):
            calls.append((method, path, json, params))
            if path.endswith('/tickets') and method == 'GET':
                return [{'id': 3, 'code': 'T-0003', 'subject': 'S', 'status': 'acik', 'app': 'fm', 'unread': 1, 'updated_at': '2026-10-15T10:00:00'}]
            if path.endswith('/tickets/99'):
                raise merkez.MerkezError(404, 'Talep bulunamadı')
            return {'id': 3, 'code': 'T-0003'}
        orig = merkez.call
        merkez.call = fake
        try:
            assert c2.get('/api/mt/tickets').json()[0]['code'] == 'T-0003'
            assert calls[-1][3] == {'email': 'yeni@test.com'}
            r = c2.post('/api/mt/tickets', headers=W, json={'app': 'fm', 'subject': 'Bağlanamıyorum', 'body': 'FTPS hatası', 'email': 'baskasi@test.com'})
            assert r.json()['id'] == 3 and calls[-1][2]['email'] == 'yeni@test.com' and calls[-1][2]['app'] == 'fm', calls[-1]   # e-posta oturumdan
            assert c2.post('/api/mt/tickets', json={'subject': 'x', 'body': 'y'}).status_code == 403   # CSRF
            r = c2.get('/api/mt/tickets/99')
            assert r.status_code == 404 and r.json() == {'code': 'support_error', 'message': 'Talep bulunamadı', 'detail': 'Talep bulunamadı'}
            assert TestClient(app, base_url='https://testserver').get('/api/mt/tickets').status_code == 401
        finally:
            merkez.call = orig
        settings.CENTRAL_SECRET, saved = 'merkez-gizli', settings.CENTRAL_SECRET
        settings.MERKEZ_UDS, settings.MERKEZ_URL = '', 'http://127.0.0.1:9'   # kapalı port: tek tip ileti, adres sızmaz
        r = c2.get('/api/mt/tickets')
        assert r.status_code == 503 and '127.0.0.1' not in r.text and 'ulaşılamıyor' in r.json()['message'], r.text
        settings.CENTRAL_SECRET = saved
        # Merkez → yanıt bildirimi e-postası
        assert c.post('/api/mt/internal/ticket-reply', json={'email': 'yeni@test.com'}).status_code == 403
        r = c.post('/api/mt/internal/ticket-reply', headers=ADMIN, json={'id': 3, 'code': 'T-0003', 'subject': 'Bağlanamıyorum', 'email': 'yeni@test.com', 'app': 'fm'})
        assert r.json()['sent'] is True
        m = mailer.OUTBOX[-1]
        assert m['subject'] == 'FTP Masters: destek talebinize yanıt (T-0003)' and '/hesabim?talep=3#destek' in m['text'], m

        # ---- SQL Master (sq): aynı hesap, ayrı oturum / kütüphane / sürüm, kendi anahtarı
        assert c.get('/api/sq/health').json()['ok']
        r = c.post('/api/sq/auth/login', json={'email': 'yeni@test.com', 'auth_hash': auth_hash('Yeni-1111', k2), 'device': 'SQL-PC'})
        assert r.status_code == 200, r.text
        SQ = {'Authorization': 'Bearer ' + r.json()['token']}
        assert c.get('/api/fm/library', headers=SQ).json()['code'] == 'wrong_app'
        assert c.put('/api/sq/library', headers=SQ, json={'base_version': 0, 'blob': blob}).json() == {'version': 1}
        exe_sq = b'MZ' + b'q' * 400
        assert c.post('/api/sq/releases/1.0.0/setup', data={}, files={'file': ('x', exe_sq)}, headers={'X-Release-Key': 'fm-anahtar'}).status_code == 403
        r = c.post('/api/sq/releases/1.0.0/setup', data={'filename': 'SQL-Master-Setup-1.0.0.exe'}, files={'file': ('x', exe_sq)}, headers={'X-Release-Key': 'sq-anahtar'})
        assert r.status_code == 200 and os.path.isfile(os.path.join(D, 'releases', 'sq', '1.0.0', 'SQL-Master-Setup-1.0.0.exe')), r.text
        assert c.get('/api/sq/releases/latest', headers=SQ).json()['version'] == '1.0.0'
        assert {a['app'] for a in c2.get('/api/mt/account').json()['apps']} == {'sm', 'fm', 'sq', 'np', 'cv', 'ip', 'fs', 'qp', 'm3'}
        assert c2.get('/indir/' + c2.get('/api/mt/account').json()['apps'][2]['download_url'].split('/indir/')[1]).content == exe_sq
        sid = next(u['id'] for u in c.get('/api/sm/admin/users', headers=ADMIN).json()['users'] if u['email'] == 'yeni@test.com')
        c.put(f'/api/sm/admin/users/{sid}', headers=ADMIN, json={'apps': {'sq': 'KAPALI'}})
        r = c.post('/api/sq/auth/login', json={'email': 'yeni@test.com', 'auth_hash': auth_hash('Yeni-1111', k2)})
        assert r.json()['code'] == 'app_disabled' and 'SQL Master' in r.json()['message']
        assert c.get('/', headers={'Host': 'sqlmaster.app'}).text.count('<title>SQL Master') == 1
        assert c.get('/brand/sq.png').headers['content-type'] == 'image/png'
        assert c.get('/i18n/sq.de.json').status_code == 200
        # ---- Notepad Master (np)
        r = c.post('/api/np/auth/login', json={'email': 'yeni@test.com', 'auth_hash': auth_hash('Yeni-1111', k2), 'device': 'NP-PC'})
        assert r.status_code == 200, r.text
        NP = {'Authorization': 'Bearer ' + r.json()['token']}
        assert c.get('/api/sq/library', headers=NP).json()['code'] == 'wrong_app'
        assert c.put('/api/np/library', headers=NP, json={'base_version': 0, 'blob': blob}).json() == {'version': 1}
        r = c.post('/api/np/releases/1.0.0/setup', data={'filename': 'Notepad-Master-Setup-1.0.0.exe'}, files={'file': ('x', b'MZ' + b'n' * 99)},
                   headers={'X-Release-Key': 'np-anahtar'})
        assert r.status_code == 200, r.text
        assert c.post('/api/np/releases/1.0.1/setup', data={}, files={'file': ('x', b'MZ')}, headers={'X-Release-Key': 'sq-anahtar'}).status_code == 403
        assert c.get('/', headers={'Host': 'www.notepadmaster.com'}).text.count('<title>Notepad Master') == 1
        assert c.get('/brand/np.png').headers['content-type'] == 'image/png'
        # ---- Convert Master (cv)
        r = c.post('/api/cv/auth/login', json={'email': 'yeni@test.com', 'auth_hash': auth_hash('Yeni-1111', k2)})
        assert r.status_code == 200, r.text
        CV = {'Authorization': 'Bearer ' + r.json()['token']}
        assert c.get('/api/np/library', headers=CV).json()['code'] == 'wrong_app'
        assert c.put('/api/cv/library', headers=CV, json={'base_version': 0, 'blob': blob}).json() == {'version': 1}
        assert c.post('/api/cv/releases/1.0.0/setup', data={}, files={'file': ('x', b'MZ' + b'c' * 9)}, headers={'X-Release-Key': 'cv-anahtar'}).status_code == 200
        assert c.get('/', headers={'Host': 'convertmaster.app'}).text.count('<title>Convert Master') == 1
        assert c.get('/brand/cv.png').headers['content-type'] == 'image/png'
        r = c.get('/giris', headers={'Host': 'notepadmaster.com'})
        assert 'data-site="np"' in r.text or r.status_code == 302

        # ---- Host'a göre site
        for host, title in (('ftpmasters.com', 'FTP Masters —'), ('www.ftpmasters.com', 'FTP Masters —'), ('mastertool.download', 'Mastertool —'),
                            ('sshmasters.com', 'SSH Master —'), ('testserver', 'SSH Master —')):
            r = c.get('/', headers={'Host': host})
            assert r.status_code == 200 and f'<title>{title}' in r.text, (host, r.text[:200])
        r = c.get('/giris', headers={'Host': 'ftpmasters.com'})
        assert 'data-site="fm"' in r.text and '<title>FTP Masters — Hesap' in r.text
        assert c.get('/favicon.svg', headers={'Host': 'ftpmasters.com'}).content == open(os.path.join(settings.STATIC_DIR, 'fm', 'favicon.svg'), 'rb').read()
        for b in ('sm', 'fm', 'mt', 'hepgo'):
            assert c.get(f'/brand/{b}.png').headers['content-type'] == 'image/png'
        assert c.get('/brand/../main.py').status_code == 404 and c.get('/brand/x.png').status_code == 404
        # portal yayında: ürün sitelerinin hesap sayfaları portala yönlenir (marka korunur), portal kendi sayfasını verir
        settings.PORTAL_LIVE = True
        try:
            r = c.get('/hesabim?sonra=/indir/x', headers={'Host': 'www.sshmasters.com'}, follow_redirects=False)
            assert r.status_code == 302 and r.headers['location'] == 'https://mastertool.download/hesabim?sonra=/indir/x&app=sm', r.headers
            assert c.get('/sifre-sifirla/abc', headers={'Host': 'sqlmaster.app'}, follow_redirects=False).headers['location'].startswith('https://mastertool.download/sifre-sifirla/abc')
            r = c.get('/dogrula/abc', headers={'Host': 'ftpmasters.com'}, follow_redirects=False)
            assert r.headers['location'] == 'https://mastertool.download/dogrula/abc?app=fm'
            assert c.get('/indir/dl/fm', headers={'Host': 'ftpmasters.com'}, follow_redirects=False).headers['location'].startswith('https://mastertool.download/indir/dl/fm')
            r = c.get('/kayit?app=fm', headers={'Host': 'mastertool.download'})
            assert r.status_code == 200 and 'data-site="mt" data-brand="fm"' in r.text
            assert c.get('/', headers={'Host': 'sshmasters.com'}).status_code == 200   # ürün sayfası yönlenmez
        finally:
            settings.PORTAL_LIVE = False

        # ---- site içi giriş / kayıt (ürün sitelerinde yerinde, MT_PORTAL_LIVE=1 iken de), next doğrulaması, oturum durumu
        settings.PORTAL_LIVE = True
        try:
            anon = TestClient(app, base_url='https://testserver')
            HOSTS = (('sshmasters.com', 'sm', 'sshmaster'), ('www.ftpmasters.com', 'fm', 'ftpmaster'), ('sqlmaster.app', 'sq', 'sqlmaster'),
                     ('notepadmaster.com', 'np', 'notepadmaster'), ('convertmaster.app', 'cv', 'convertmaster'))
            for host, site, slug in HOSTS:
                for path in ('/giris', '/kayit', '/sifremi-unuttum'):
                    r = anon.get(path, headers={'Host': host}, follow_redirects=False)
                    assert r.status_code == 200 and f'data-site="{site}"' in r.text and f'data-next="/web/{slug}/"' in r.text, (host, path, r.status_code)
                    csp = r.headers['content-security-policy']
                    assert "script-src 'self';" in csp and "frame-ancestors 'self'" in csp and '<script>' not in r.text
                assert anon.get('/hesabim', headers={'Host': host}, follow_redirects=False).status_code == 302   # Hesabım portalda kalır
                home = anon.get('/', headers={'Host': host}).text   # ana sayfa: Web'de aç (birincil) + İndir (.exe) + bölüm + başlıkta oturum
                assert f'<a class="store web" href="/web/{slug}/">' in home and '<b>İndir (.exe)</b>' in home and 'id="web"' in home, host
                assert f'data-mt-auth="{site}" data-web="/web/{slug}/"' in home and '/mtsite.js' in home and '/mtsite.css' in home and 'Kayıt ol' in home
            r = anon.get('/giris', headers={'Host': 'sshmasters.com'})
            assert 'data-portal="https://mastertool.download"' in r.text and 'data-brand="sm"' in r.text
            for bad in ('//evil.com', 'https://evil.com', '/\\evil.com', '/\\/evil.com', '\\/evil.com', 'javascript:alert(1)', '/a b', '/x\r\nLocation: //evil.com',
                        '///evil.com', ' /x', 'evil.com', '/' + 'a' * 600):
                r = anon.get('/giris', params={'next': bad}, headers={'Host': 'ftpmasters.com'})
                assert r.status_code == 200 and 'data-next="/web/ftpmaster/"' in r.text, (bad, re.search(r'data-next="[^"]*"', r.text))
                r = anon.get('/giris', params={'next': bad}, headers={'Host': 'mastertool.download'})
                assert 'data-next=""' in r.text, bad   # portalda varsayılan dönüş hesap.js'te (Hesabım / oyun)
            from sshm.main import safe_next
            assert safe_next('/web/sqlmaster/?a=1#x') == '/web/sqlmaster/?a=1#x' and safe_next('/\\evil.com') == '' and safe_next(None) == ''
            r = anon.get('/giris?next=/web/sqlmaster/', headers={'Host': 'sshmasters.com'})
            assert 'data-next="/web/sqlmaster/"' in r.text
            r = anon.get('/giris?next=/web/sshmaster/%22%3E%3Cscript%3E', headers={'Host': 'mastertool.download'})
            assert '<script>' not in r.text and 'data-next="/web/sshmaster/&quot;&gt;&lt;script&gt;"' in r.text   # öznitelik kaçışlı
            # oturum durumu (başlık için): oturumsuz da 200
            assert anon.get('/api/sm/session').json() == {'user': None}
            st = c2.get('/api/fm/session')
            assert st.status_code == 200 and st.json()['user']['email'] == 'yeni@test.com' and st.headers['cache-control'] == 'private, no-store'
            # kayıt ürün sitesinden: doğrulama bağlantısı (ACCOUNT_URL) ?app=<site> ile; doğrulama sonrası Hesabım "web'de aç" gösterir
            k3 = anon.post('/api/sm/auth/prelogin', json={'email': 'web@test.com'}).json()['kdf']
            assert anon.post('/api/mt/auth/register', json={'name': 'Web Kişi', 'email': 'web@test.com', 'auth_hash': auth_hash('Web-12345', k3), 'brand': 'sm'}).json()['ok']
            link = re.search(r'https://[a-z.]+(/dogrula/[A-Za-z0-9_-]+\?app=sm)\b', mailer.OUTBOX[-1]['text']).group(1)
            r = anon.get(link, headers={'Host': 'mastertool.download'}, follow_redirects=False)
            assert r.status_code == 303 and r.headers['location'] == '/hesabim?durum=dogrulandi&app=sm', r.headers
            r = anon.get('/hesabim?durum=dogrulandi&app=sm', headers={'Host': 'mastertool.download'})
            assert 'data-brand="sm"' in r.text and 'data-web="https://sshmasters.com/web/sshmaster/"' in r.text
            assert 'data-web=""' in anon.get('/hesabim?app=xx', headers={'Host': 'mastertool.download'}).text
            anon.post('/api/mt/auth/resend-verify', json={'email': 'zzz@test.com', 'brand': 'https://evil.com'})   # bilinmeyen marka: ?app eklenmez
        finally:
            settings.PORTAL_LIVE = False

        # ---- mastertool.download/uygulamalar (Master Tool web başlatıcısı) ve katalog ?web=1
        MT = {'Host': 'mastertool.download'}
        r = c2.get('/uygulamalar', headers=MT)
        csp = r.headers['content-security-policy']
        assert r.status_code == 200 and '/uygulamalar.js' in r.text and '<script>' not in r.text and "frame-src 'self'" in csp and "script-src 'self';" in csp
        assert 'data-portal="https://mastertool.download"' in r.text and 'data-dicts="hesap"' in r.text
        assert c2.get('/uygulamalar', headers={'Host': 'sshmasters.com'}).status_code == 404
        assert c2.get('/uygulamalar.js').headers['content-type'].startswith('text/javascript') and c2.get('/uygulamalar.css').headers['content-type'].startswith('text/css')
        assert c2.get('/mtsite.js').status_code == 200 and c2.get('/mtsite.css').status_code == 200
        cat = c2.get('/api/mt/apps?web=1').json()
        ca = {a['app']: a for a in cat['apps']}
        assert ca['sm']['web'] == '/web/sshmaster/' and ca['cv']['web'] == '/web/convertmaster/' and ca['ip']['web'] is None and ca['fs']['web'] is None
        assert ca['fm']['download_url'].startswith('/indir/') and ca['fm']['download_url'].endswith('/fm') and 'vf' in ca and 'sv' in ca and ca['vf']['kind'] == 'web'
        assert cat['launcher']['download_url'].endswith('/mt')
        plain = c2.get('/api/mt/apps').json()['apps']   # masaüstü / eski istemci yanıtı değişmedi
        assert all('web' not in a and 'download_url' not in a for a in plain) and not any(a.get('kind') == 'web' for a in plain)
        anon = TestClient(app, base_url='https://testserver')   # yukarıdaki doğrulama oturum açtı; yeni, oturumsuz istemci
        assert anon.get('/api/mt/apps?web=1').status_code == 401
        acc = {a['app']: a for a in c2.get('/api/mt/account').json()['apps']}
        assert acc['np']['web'] == '/web/notepadmaster/' and acc['qp']['web'] is None
        # /web yedeği (üretimde tünel /web'i mtweb'e verir): oturumsuz → giriş akışı, portalda /web/ → /uygulamalar
        r = anon.get('/web/sshmaster/', headers={'Host': 'sshmasters.com'}, follow_redirects=False)
        assert r.status_code == 302 and r.headers['location'] == '/giris?next=/web/sshmaster/'
        assert anon.get('/web/', headers=MT, follow_redirects=False).headers['location'] == '/uygulamalar'
        assert anon.get('/web', headers={'Host': 'ftpmasters.com'}, follow_redirects=False).headers['location'] == '/giris?next=/web/ftpmaster/'
        assert anon.get('/web/iptools/', follow_redirects=False).status_code == 404
        assert c2.get('/web/ftpmaster/', headers={'Host': 'ftpmasters.com'}).status_code == 503
        # robots: /web/ dizine girmez; site haritasında yok
        for host in ('sshmasters.com', 'mastertool.download', 'convertmaster.app'):
            assert 'Disallow: /web/' in c.get('/robots.txt', headers={'Host': host}).text and '/web/' not in c.get('/sitemap.xml', headers={'Host': host}).text
        assert 'Disallow: /uygulamalar' in c.get('/robots.txt', headers=MT).text
        mh = c.get('/', headers=MT).text
        assert 'href="/uygulamalar"' in mh and 'data-mt-auth="mt"' in mh
        # çeviriler: başlatıcı (mt + hesap sözlüğü) ve ürün sayfalarının yeni metinleri 7 dilde
        ujs = open(os.path.join(settings.STATIC_DIR, 'uygulamalar.js'), encoding='utf-8').read()
        ukeys = {k.replace("\\'", "'") for k in re.findall(r"\bt\('((?:[^'\\]|\\.)*)'", ujs)}
        assert len(ukeys) > 40, len(ukeys)
        for lang in ('en', 'fr', 'de', 'es', 'ar', 'zh', 'ru'):
            d = c.get(f'/i18n/mt.{lang}.json').json() | c.get(f'/i18n/hesap.{lang}.json').json()
            assert not [k for k in ukeys if k not in d], (lang, [k for k in ukeys if k not in d][:5])
            for site in ('sm', 'fm', 'sq', 'np', 'cv'):
                d = c.get(f'/i18n/{site}.{lang}.json').json()
                assert all(k in d for k in ("Web'de aç", 'Kayıt ol', 'İndir (.exe)', 'Tarayıcıda ya da masaüstünde', 'Masaüstü (Windows)', 'Çıkış')), (site, lang)

        # ---- site kiti ve çeviri sözlükleri (8 dil; Türkçe kaynak sayfanın kendisi)
        for a in ('/kit.js', '/kit.css'):
            assert c.get(a, headers={'Host': 'ftpmasters.com'}).status_code == 200, a
        for site in ('sm', 'fm', 'sq', 'np', 'cv', 'mt', 'hesap'):
            for lang in ('en', 'fr', 'de', 'es', 'ar', 'zh', 'ru'):
                r = c.get(f'/i18n/{site}.{lang}.json')
                assert r.status_code == 200 and isinstance(r.json(), dict) and len(r.json()) > 20, (site, lang)
        assert c.get('/i18n/sm.tr.json').status_code == 404 and c.get('/i18n/..%2fmain.py').status_code == 404 and c.get('/i18n/x.en.json').status_code == 404
        hjs = open(os.path.join(settings.STATIC_DIR, 'hesap.js'), encoding='utf-8').read()
        keys = {k.replace("\\'", "'") for k in re.findall(r"\bt\('((?:[^'\\]|\\.)*)'", hjs)}
        for lang in ('en', 'ar', 'zh'):
            d = c.get(f'/i18n/hesap.{lang}.json').json()
            assert not [k for k in keys if k not in d], (lang, [k for k in keys if k not in d][:3])   # hesap.js'deki her metin çevrilmiş
        for site in ('sm', 'fm', 'sq', 'np', 'cv', 'mt'):
            assert '/kit.js' in c.get('/', headers={'Host': {'sm': 'sshmasters.com', 'fm': 'ftpmasters.com', 'sq': 'www.sqlmaster.app', 'np': 'notepadmaster.com', 'cv': 'www.convertmaster.app', 'mt': 'mastertool.download'}[site]}).text
        assert 'data-site="hesap"' in c.get('/giris').text

        # ---- SEO: dile göre başlık, canonical/hreflang, sosyal etiketler, yapılandırılmış veri, robots, sitemap
        r = c.get('/?lang=de', headers={'Host': 'sshmasters.com'})
        assert '<html lang="de" dir="ltr"' in r.text and '<link rel="canonical" href="https://sshmasters.com/?lang=de">' in r.text, r.text[:300]
        assert r.text.count('hreflang=') == 9 and 'application/ld+json' in r.text and '"SoftwareApplication"' in r.text
        assert '<title>SSH Master — Windows' not in r.text and 'og:image' in r.text and 'twitter:card' in r.text
        r = c.get('/?lang=ar', headers={'Host': 'ftpmasters.com'})
        assert 'dir="rtl"' in r.text and 'canonical" href="https://ftpmasters.com/?lang=ar"' in r.text
        r = c.get('/', headers={'Host': 'mastertool.download'})
        assert '"ItemList"' in r.text and 'canonical" href="https://mastertool.download/"' in r.text
        assert c.get('/?lang=xx', headers={'Host': 'sqlmaster.app'}).text.count('<html lang="tr"') == 1
        rb = c.get('/robots.txt', headers={'Host': 'notepadmaster.com'}).text
        assert 'Sitemap: https://notepadmaster.com/sitemap.xml' in rb and 'Disallow: /api/' in rb
        sm = c.get('/sitemap.xml', headers={'Host': 'convertmaster.app'})
        assert sm.headers['content-type'].startswith('application/xml') and sm.text.count('<url>') == 9 and 'convertmaster.app/?lang=zh' in sm.text
        assert 'convertmaster.app/gizlilik' in sm.text and '<image:loc>https://convertmaster.app/shots/' in sm.text
        # Google Analytics: yalnız tanıtım sayfasında ölçüm kimliği; hesap sayfalarında yok; gizlilik sayfası her sitede
        r = c.get('/', headers={'Host': 'ftpmasters.com'})
        assert '<meta name="mt-ga" content="G-0SW2PWQ7L6">' in r.text and '"price": "0"' in r.text and '"softwareVersion"' in r.text
        assert 'mt-ga' not in c.get('/giris', headers={'Host': 'ftpmasters.com'}).text
        g = c.get('/gizlilik', headers={'Host': 'sqlmaster.app'})
        assert g.status_code == 200 and 'SKYREX HAVACILIK TEKNOLOJİ A.Ş.' in g.text and 'G-B86095ZLQB' in g.text and '{{' not in g.text
        assert c.get('/i18n/legal.en.json').status_code in (200, 404)
        og = c.get('/og.png', headers={'Host': 'www.convertmaster.app'})
        assert og.status_code == 200 and og.headers['content-type'] == 'image/png'
        # ekran görüntüleri: galeri, kahraman görseli, yapılandırılmış veride screenshot, /shots/ yalnız sitenin kendi WebP'leri
        r = c.get('/?lang=en', headers={'Host': 'notepadmaster.com'})
        assert 'id="ekranlar"' in r.text and 'class="hero-shot"' in r.text and '"screenshot"' in r.text
        assert 'https://notepadmaster.com/shots/05-proje-penceresi-gece-en.webp' in r.text
        assert '/shots/05-proje-penceresi-gece-en.webp' in r.text and '/shots/05-proje-penceresi-gece.webp' not in r.text   # İngilizce arayüz görüntüsü
        assert '/shots/05-proje-penceresi-gece.webp' in c.get('/', headers={'Host': 'notepadmaster.com'}).text
        sh = c.get('/shots/05-proje-penceresi-gece-800.webp', headers={'Host': 'notepadmaster.com'})
        assert sh.status_code == 200 and sh.headers['content-type'] == 'image/webp'
        assert c.get('/shots/05-proje-penceresi-gece.webp', headers={'Host': 'sshmasters.com'}).status_code == 404
        assert c.get('/shots/..%2Fog.png', headers={'Host': 'notepadmaster.com'}).status_code == 404
        assert c.get('/shots/shots.json', headers={'Host': 'notepadmaster.com'}).status_code == 404
        assert 'noindex' in c.get('/giris').text   # hesap sayfaları dizine girmez
        assert c.get('/hesabim?app=sshmaster', headers={'Host': 'mastertool.download'}).text.count('data-brand="sm"') == 1

        # ---- Master Tool ortak oturumu (SSO): bir kez giriş → diğer uygulamalar şifresiz; birinde çıkış → hepsi düşer
        from sshm.main import _RATE
        _RATE.clear()   # önceki bölümlerin giriş denemeleri hız sınırına takılmasın
        k = c.post('/api/mt/auth/prelogin', json={'email': 'eski@test.com'}).json()['kdf']
        AH = auth_hash('Yeni-5678', k)   # şifre yukarıda değiştirildi
        r = c.post('/api/mt/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'client': 'desktop', 'device': 'MT-PC', 'app_version': '1.0.0'})
        assert r.status_code == 200 and r.json()['sso_token'] and 'token' not in r.json() and 'set-cookie' not in r.headers, r.text
        SSO = r.json()['sso_token']
        MT = {'Authorization': 'Bearer ' + SSO}
        cat = c.get('/api/mt/apps', headers=MT).json()
        assert [x['app'] for x in cat['apps']] == ['sm', 'fm', 'sq', 'np', 'cv', 'ip', 'fs', 'qp', 'm3'] and cat['apps'][1]['exe'] == 'FTP Masters.exe', cat
        ipc = cat['apps'][5]
        assert ipc['description']['en'].startswith('Scans') and len(ipc['description']) == 8 and cat['apps'][0]['description'] is None
        assert ipc['group'] == 'tools' and ipc['name'] == 'IP Tools' and ipc['site'].endswith('/araclar/ip-tools') and cat['apps'][0]['group'] == 'apps'
        assert c.get('/brand/ip.png').headers['content-type'] == 'image/png' and c.get('/brand/qp.svg').headers['content-type'] == 'image/svg+xml'
        assert c.get('/brand/fs-512.png').status_code == 200
        assert cat['apps'][1]['release']['version'] and cat['apps'][1]['icon_png'] == '/brand/fm.png'
        assert c.get('/api/sm/library', headers=MT).json()['code'] == 'wrong_app'          # ortak token uygulama uçlarında geçmez
        d = c.get('/api/mt/apps/fm/download', headers=MT)
        assert d.status_code == 200 and d.headers['x-sha256'] == hashlib.sha256(d.content).hexdigest() and d.content[:2] == b'MZ', d.text[:200]
        assert c.get('/api/mt/apps/xx/download', headers=MT).status_code == 404
        assert c.get('/api/mt/apps/fm/download', headers={'Authorization': 'Bearer yanlis'}).status_code == 401
        r1 = c.post('/api/fm/auth/sso', json={'sso_token': SSO, 'device': 'MT-PC', 'app_version': '1.3.0'})
        r2 = c.post('/api/sm/auth/sso', json={'sso_token': SSO, 'app_version': '1.2.0'})
        assert r1.status_code == 200 and r2.status_code == 200 and r1.json()['kdf'] == k and r1.json()['user']['email'] == 'eski@test.com', r1.text
        F1, S2 = {'Authorization': 'Bearer ' + r1.json()['token']}, {'Authorization': 'Bearer ' + r2.json()['token']}
        assert c.get('/api/fm/me', headers=F1).status_code == 200 and c.get('/api/sm/me', headers=S2).status_code == 200
        assert c.post('/api/fm/auth/sso', json={'sso_token': 'yanlis'}).json()['code'] == 'session_expired'
        assert c.post('/api/mt/auth/sso', json={'sso_token': SSO}).status_code == 404
        r = c.post('/api/fm/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH}); assert r.status_code == 200, r.text; FM = {'Authorization': 'Bearer ' + r.json()['token']}
        assert 'sso_token' not in r.json()
        r = c.post('/api/fm/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH}); assert r.status_code == 200, r.text; FM = {'Authorization': 'Bearer ' + r.json()['token']}
        assert 'sso_token' not in r.json()
        # sm'de çıkış → ortak oturum + fm oturumu da düşer; bağımsız (sso'suz) fm oturumu etkilenmez
        assert c.post('/api/sm/auth/logout', headers=S2).json() == {'ok': True, 'sso_ended': True}
        assert c.get('/api/fm/me', headers=F1).json()['code'] == 'session_expired'
        assert c.get('/api/mt/apps', headers=MT).status_code == 401
        assert c.post('/api/fm/auth/sso', json={'sso_token': SSO}).status_code == 401
        assert c.get('/api/fm/me', headers=FM).status_code == 200
        # uygulamada şifreyle giriş + sso:true → ortak oturum da açılır; Master Tool'dan çıkış hepsini kapatır
        r = c.post('/api/np/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'sso': True, 'device': 'NP-PC'})
        assert r.json()['sso_token'] and r.json()['token'], r.text
        NP, SSO2 = {'Authorization': 'Bearer ' + r.json()['token']}, r.json()['sso_token']
        r = c.post('/api/cv/auth/sso', json={'sso_token': SSO2}); CV = {'Authorization': 'Bearer ' + r.json()['token']}
        assert c.post('/api/mt/auth/logout', headers={'Authorization': 'Bearer ' + SSO2}).json()['sso_ended'] is True
        assert c.get('/api/np/me', headers=NP).status_code == 401 and c.get('/api/cv/me', headers=CV).status_code == 401
        # lisans kapalı uygulama sso ile de açılmaz; Master Tool'un kendi sürümü mt anahtarıyla
        r = c.post('/api/mt/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'client': 'desktop'}); MT3 = {'Authorization': 'Bearer ' + r.json()['sso_token']}
        assert c.post('/api/mt/releases', data={'version': '1.0.0'}, files={'setup': ('m.exe', b'MZmt', 'application/octet-stream')},
                      headers={'X-Release-Key': 'fm-anahtar'}).status_code == 403
        r = c.post('/api/mt/releases/1.0.0/setup', data={'part': '0', 'parts': '1'}, files={'file': ('b', b'MZmaster')}, headers={'X-Release-Key': 'mt-anahtar'})
        assert r.status_code == 200 and r.json()['size'] == 8, r.text
        assert c.get('/api/mt/apps', headers=MT3).json()['launcher']['release']['version'] == '1.0.0'
        assert c.get('/api/mt/releases/latest', headers=MT3).json()['version'] == '1.0.0'
        assert c.get('/api/mt/apps/mt/download', headers=MT3).content == b'MZmaster'
        # Araçlar: aynı lisans/oturum/sürüm düzeni; kendi anahtarıyla yükleme, Master Tool'dan indirme, sso ile şifresiz giriş
        r = c.post('/api/ip/releases/0.1.0/setup', data={'part': '0', 'parts': '1'}, files={'file': ('b', b'MZiptools')}, headers={'X-Release-Key': 'ip-anahtar'})
        assert r.status_code == 200 and r.json()['size'] == 9, r.text
        assert c.post('/api/ip/releases/0.2.0/setup', data={'part': '0', 'parts': '1'}, files={'file': ('b', b'MZx')},
                      headers={'X-Release-Key': 'mt-anahtar'}).status_code == 403
        assert c.get('/api/mt/apps/ip/download', headers=MT3).content == b'MZiptools'
        r = c.post('/api/ip/auth/sso', json={'sso_token': MT3['Authorization'][7:]}); assert r.status_code == 200 and r.json()['token'], r.text
        assert c.get('/api/ip/me', headers={'Authorization': 'Bearer ' + r.json()['token']}).status_code == 200
        tp = c.get('/araclar/ip-tools?lang=en', headers={'Host': 'mastertool.download'})   # araç tanıtım sayfası
        assert tp.status_code == 200 and '<html lang="en"' in tp.text and '"IP Tools"' in tp.text and '/shots/ip-01-kayitlar-gece-en.webp' in tp.text, tp.text[:200]
        assert 'canonical" href="https://mastertool.download/araclar/ip-tools?lang=en"' in tp.text and '"isPartOf"' in tp.text
        assert c.get('/araclar/ip-tools', headers={'Host': 'sshmasters.com'}).status_code == 404
        assert c.get('/araclar/yok', headers={'Host': 'mastertool.download'}).status_code == 404
        sm2 = c.get('/sitemap.xml', headers={'Host': 'mastertool.download'}).text; assert sm2.count('<loc>https://mastertool.download/araclar/quick-preview') == 8 and sm2.count('/araclar/ip-tools') >= 8, sm2.count('/araclar/')
        # web oturumunda (Hesabım) sso oturumu kapatılınca ailesi düşer; web 'Oturumlar' listesinde görünür
        c.post('/api/mt/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'client': 'web'})
        acc = c.get('/api/mt/account').json()
        assert acc['launcher']['name'] == 'Master Tool' and acc['launcher']['release']['version'] == '1.0.0'
        assert {x['app']: x['group'] for x in acc['apps']}['fs'] == 'tools' and acc['apps'][0]['group'] == 'apps'
        sid = next(x['id'] for x in acc['sessions'] if x['kind'] == 'sso')
        r = c.post('/api/sq/auth/sso', json={'sso_token': MT3['Authorization'][7:]}); SQ = {'Authorization': 'Bearer ' + r.json()['token']}
        assert c.delete(f'/api/mt/sessions/{sid}', headers=W).json() == {'ok': True}
        assert c.get('/api/sq/me', headers=SQ).status_code == 401
        c.post('/api/mt/auth/logout', headers=W)

        # ---- VOLFAI (vf, web oyunu): çerezli web oturumu, profil JSON'u, katalog sürüm kapısı, statik sunum, tanıtım sayfası
        _RATE.clear()
        MTH = {'Host': 'mastertool.download'}
        g = TestClient(app, base_url='https://testserver')
        assert g.get('/api/vf/health').json()['ok'] and g.get('/api/vf/library').status_code == 404   # kütüphane / lisans / sürüm yok
        k = g.post('/api/vf/auth/prelogin', json={'email': 'eski@test.com'}).json()['kdf']
        assert k['alg'] == 'PBKDF2-SHA256' and k['salt'] and k['iter'] == settings.KDF_ITER
        r = g.post('/api/vf/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'device': 'VOLFAI Web (Android)', 'app_version': '0.2.3', 'client': 'web'})
        assert r.status_code == 200 and 'sm_session' in r.cookies and 'token' not in r.json(), r.text
        assert r.json()['user']['id'] and r.json()['user']['name'] == 'Eski Kullanıcı' and r.json()['sync_enabled'] is True
        assert g.get('/api/vf/profile').json() == {'user': {'id': r.json()['user']['id'], 'name': 'Eski Kullanıcı'}, 'profile': None, 'updated_at': None}
        prof = {'v': 1, 'coins': 37, 'hiScore': 12480, 'upgrades': {'engine': 1}, 'levels': {'1': {'parkurs': {'1': {'honor': 25, 'best': 79230}}}}, 'updatedAt': 1760724000000}
        assert g.put('/api/vf/profile', json={'profile': prof}).status_code == 403                     # çerezli PUT'ta x-sshm zorunlu (CSRF)
        assert g.put('/api/vf/profile', headers=W, json={'profile': prof}).json() == {'ok': True}
        got = g.get('/api/vf/profile').json()
        assert got['profile'] == prof and got['updated_at'], got
        assert g.put('/api/vf/profile', headers=W, json={'profile': prof | {'coins': 38}}).json()['ok'] and g.get('/api/vf/profile').json()['profile']['coins'] == 38
        r = g.put('/api/vf/profile', headers=W | {'Content-Type': 'application/json'}, content=b'{"profile": {bozuk')
        assert r.status_code == 400 and r.json()['code'] == 'invalid', r.text
        assert g.put('/api/vf/profile', headers=W, json={'profile': 'metin'}).status_code == 400 and g.put('/api/vf/profile', headers=W, json=[1]).status_code == 400
        r = g.put('/api/vf/profile', headers=W, json={'profile': {'big': 'x' * (64 * 1024)}})
        assert r.status_code == 413 and r.json()['code'] == 'too_large', r.text
        assert g.put('/api/vf/profile', headers=W, json={'profile': {'big': 'x' * (60 * 1024)}}).json()['ok']
        assert g.get('/api/vf/me').json()['user']['email'] == 'eski@test.com' and 'library' not in g.get('/api/vf/me').json()
        assert TestClient(app, base_url='https://testserver').get('/api/vf/profile').status_code == 401     # yetkisiz
        assert TestClient(app, base_url='https://testserver').put('/api/vf/profile', headers=W, json={'profile': {}}).status_code == 401
        assert g.post('/api/vf/auth/logout', headers=W).json()['ok'] and g.get('/api/vf/profile').status_code == 401
        # client verilmezse uygulama (Bearer) oturumu; profil Bearer ile de okunur, başka uygulamanın uçlarında geçmez
        r = g.post('/api/vf/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'device': 'VOLFAI'})
        VF = {'Authorization': 'Bearer ' + r.json()['token']}
        assert 'big' in g.get('/api/vf/profile', headers=VF).json()['profile']   # son PUT'taki içerik, Bearer ile
        assert g.get('/api/sm/library', headers=VF).json()['code'] == 'wrong_app'
        assert g.get('/api/xx/profile', headers=VF).status_code == 404 and g.get('/api/sm/profile', headers=VF).status_code == 404
        # katalog: kind:'web' kaydı yalnız ?v=1.2.0 ve üstü isteyen Master Tool'a
        r = c.post('/api/mt/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'client': 'desktop'}); MT4 = {'Authorization': 'Bearer ' + r.json()['sso_token']}
        base_apps = ['sm', 'fm', 'sq', 'np', 'cv', 'ip', 'fs', 'qp', 'm3']
        assert [x['app'] for x in c.get('/api/mt/apps', headers=MT4).json()['apps']] == base_apps
        assert [x['app'] for x in c.get('/api/mt/apps?v=1.1.0', headers=MT4).json()['apps']] == base_apps
        assert [x['app'] for x in c.get('/api/mt/apps?v=bozuk', headers=MT4).json()['apps']] == base_apps
        cat = c.get('/api/mt/apps?v=1.2.0', headers=MT4).json()['apps']
        assert [x['app'] for x in cat] == base_apps + ['vf', 'sv', 'mw'] and [x['app'] for x in c.get('/api/mt/apps?v=v1.10.0-beta', headers=MT4).json()['apps']][-3:] == ['vf', 'sv', 'mw']
        vf = cat[-3]
        assert vf == {'app': 'vf', 'code': 'vf', 'name': 'VOLFAI', 'group': 'games', 'kind': 'web', 'url': 'https://mastertool.download/oyunlar/volfai/',
                      'site': 'https://mastertool.download/oyunlar/volfai/tanitim/', 'icon_svg': '/brand/vf.svg', 'icon_png': '/brand/vf.png', 'description': vf['description']}, vf
        assert len(vf['description']) == 8 and vf['description']['en'].startswith('A touch') and all(k not in vf for k in ('release', 'license', 'exe', 'install_dir'))
        assert c.get('/brand/vf.svg').headers['content-type'] == 'image/svg+xml' and c.get('/brand/vf.png').headers['content-type'] == 'image/png'
        assert c.get('/brand/vf-512.png').status_code == 200
        # SIMUMAV (sv): kendi sitesinde çalışan oyun — url/site simumav.com, ikonlar, açıklama 8 dil
        sv = cat[-2]
        assert sv['app'] == 'sv' and sv['name'] == 'SIMUMAV' and sv['kind'] == 'web' and sv['group'] == 'games' and sv['url'] == 'https://simumav.com/' and sv['site'] == 'https://simumav.com/', sv
        assert set(sv['description']) == {'tr', 'en', 'fr', 'de', 'es', 'ar', 'zh', 'ru'} and sv['description']['en'].startswith('A drone simulation game') and 'SITL' in sv['description']['tr']
        assert {'app', 'name', 'group', 'kind', 'url', 'site', 'icon_svg', 'icon_png', 'description'} <= set(sv) and sv['icon_svg'] == '/brand/sv.svg' and sv['icon_png'] == '/brand/sv.png'
        assert c.get('/brand/sv.svg').headers['content-type'] == 'image/svg+xml' and c.get('/brand/sv.png').status_code == 200 and c.get('/brand/sv-512.png').status_code == 200
        assert 'sv' not in [x['app'] for x in c.get('/api/mt/apps?v=1.1.0', headers=MT4).json()['apps']]   # sürüm kapısı oyunların tümünü kapsar
        # portal yolları kendi sitesine 307: /oyunlar/simumav, /oyunlar/simumav/, /oyunlar/simumav/tanitim/ (yalnız mastertool.download)
        for pth in ('/oyunlar/simumav', '/oyunlar/simumav/', '/oyunlar/simumav/tanitim', '/oyunlar/simumav/tanitim/', '/oyunlar/simumav/index.html'):
            r = c.get(pth, headers=MTH, follow_redirects=False); assert r.status_code == 307 and r.headers['location'] == 'https://simumav.com/', (pth, r.status_code)
        assert c.get('/oyunlar/simumav/', headers={'Host': 'sshmasters.com'}, follow_redirects=False).status_code == 404
        # Hesabım: oyunlar ayrı listede (apps bozulmaz), profil durumu
        c.post('/api/mt/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'client': 'web'})
        acc = c.get('/api/mt/account').json()
        assert {a['app'] for a in acc['apps']} == set(base_apps) and acc['games'][0]['app'] == 'vf' and acc['games'][0]['has_profile'] is True
        assert [g['app'] for g in acc['games']] == ['vf', 'sv', 'mw'] and acc['games'][1]['has_profile'] is False and acc['games'][1]['url'] == 'https://simumav.com/'   # SIMUMAV kartı (sv_profiles henüz yok)
        acc2 = c2.get('/api/mt/account').json(); assert acc2['games'][0]['has_profile'] is False
        c.post('/api/mt/auth/logout', headers=W)
        # ---- SIMUMAV hesap servisi tarafı: Bearer /api/sv/me (verified), sv_profiles (kullanıcı Bearer + sunucu X-Simumav-Secret), CORS yalnız sv
        r = g.post('/api/sv/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'device': 'SIMUMAV Web'}); assert r.status_code == 200, r.text
        SV = {'Authorization': 'Bearer ' + r.json()['token']}
        me = g.get('/api/sv/me', headers=SV).json(); assert me['user']['verified'] is True and me['user']['email'] == 'eski@test.com'
        assert g.get('/api/sv/profile', headers=SV).json()['profile'] is None
        assert g.put('/api/sv/profile', headers=SV, json={'profile': {'pilot': 'Eski'}}).json()['ok'] and g.get('/api/sv/profile', headers=SV).json()['profile'] == {'pilot': 'Eski'}
        assert g.get('/api/vf/profile', headers=VF).json()['profile'].get('pilot') is None   # tablolar ayrı (vf_profiles / sv_profiles)
        uid = me['user']['id']
        assert g.put('/api/sv/profile', headers={'X-Simumav-Secret': 'yanlis'}, json={'user_id': uid, 'profile': {'flights': 3}}).status_code == 403
        assert g.put('/api/sv/profile', headers={'X-Simumav-Secret': 'sv-gizli'}, json={'user_id': uid, 'profile': {'flights': 3, 'hours': 1.5}}).json()['ok']
        assert g.put('/api/sv/profile', headers={'X-Simumav-Secret': 'sv-gizli'}, json={'user_id': 999999, 'profile': {}}).status_code == 404
        assert g.put('/api/vf/profile', headers={'X-Simumav-Secret': 'sv-gizli'}, json={'user_id': uid, 'profile': {}}).status_code == 401   # yalnız sv
        assert g.get('/api/sv/profile', headers=SV).json()['profile'] == {'flights': 3, 'hours': 1.5}
        # ---- SIMUMAV destek köprüsü (docs/simumav.md §9): /api/sv/tickets* X-Simumav-Secret + user_id (sunucu-sunucu) → Merkez mastertool federasyonu,
        # e-posta oturumdaki kullanıcıdan; yanlış gizli 403, user_id yok 422, başka önek 401 (çerez yok); IP oran sınırı sunucu yolunda uygulanmaz
        calls = []

        def fake2(method, path, json=None, params=None):
            calls.append((method, path, json, params))
            return [{'id': 5, 'code': 'T-0005', 'app': 'sv', 'status': 'acik'}] if method == 'GET' and path.endswith('/tickets') else {'id': 5, 'code': 'T-0005', 'messages': []}
        merkez.call, orig2 = fake2, merkez.call
        try:
            SVS = {'X-Simumav-Secret': 'sv-gizli'}
            assert g.get(f'/api/sv/tickets?user_id={uid}', headers=SVS).json()[0]['code'] == 'T-0005' and calls[-1][3] == {'email': 'eski@test.com'}
            r = g.post('/api/sv/tickets', headers=SVS, json={'user_id': uid, 'app': 'sv', 'subject': '[Uçuş] Düşüyor', 'body': 'x', 'category': 'teknik'})
            assert r.status_code == 200 and r.json()['code'] == 'T-0005' and calls[-1][2] == {'email': 'eski@test.com', 'name': 'Eski Kullanıcı', 'app': 'sv', 'subject': '[Uçuş] Düşüyor', 'body': 'x', 'category': 'teknik'}, (r.text, calls[-1])
            assert g.get(f'/api/sv/tickets/5?user_id={uid}', headers=SVS).json()['id'] == 5 and calls[-1][3] == {'email': 'eski@test.com'}
            assert g.post('/api/sv/tickets/5/messages', headers=SVS, json={'user_id': uid, 'body': 'teşekkürler'}).json()['id'] == 5 and calls[-1][2]['body'] == 'teşekkürler'
            assert g.post('/api/sv/tickets/5/close', headers=SVS, json={'user_id': uid}).json()['id'] == 5
            assert g.get(f'/api/sv/tickets?user_id={uid}', headers={'X-Simumav-Secret': 'yanlis'}).status_code == 403
            assert g.get('/api/sv/tickets', headers=SVS).status_code == 422 and g.get('/api/sv/tickets?user_id=999999', headers=SVS).status_code == 404
            assert g.get(f'/api/vf/tickets?user_id={uid}', headers=SVS).status_code == 401 and g.get('/api/sv/tickets', headers=SV).status_code == 401   # Bearer web_only'de geçmez
            assert all(g.post('/api/sv/tickets', headers=SVS, json={'user_id': uid, 'app': 'sv', 'subject': 's', 'body': 'b'}).status_code == 200 for _ in range(12))   # IP oranı yok
        finally:
            merkez.call = orig2
        # Merkez yanıt bildirimi: sv talebinde e-posta bağlantısı SIMUMAV "Taleplerim" ayrıntısına
        r = c.post('/api/mt/internal/ticket-reply', headers=ADMIN, json={'id': 5, 'code': 'T-0005', 'subject': 'Düşüyor', 'email': 'eski@test.com', 'app': 'sv'})
        assert r.json()['sent'] is True and 'https://simumav.com/app/#/support/5' in mailer.OUTBOX[-1]['text'], mailer.OUTBOX[-1]['text']
        c.post('/api/mt/auth/login', json={'email': 'eski@test.com', 'auth_hash': AH, 'client': 'web'})   # Hesabım › Oyunlar: SIMUMAV profili artık kayıtlı
        assert [(x['app'], x['has_profile']) for x in c.get('/api/mt/account').json()['games']] == [('vf', True), ('sv', True), ('mw', False)]
        c.post('/api/mt/auth/logout', headers=W)
        # Merkez › Mastertool: SIMUMAV sunucusunun yazdığı özet admin yanıtında games.sv; VOLFAI profili (hiScore/levels.parkurs) games.vf
        g.put('/api/sv/profile', headers={'X-Simumav-Secret': 'sv-gizli'}, json={'user_id': uid, 'profile': {
            'pilot': 'Eski', 'pilots': 2, 'drones': 3, 'flights': 7, 'hours': 2.25, 'last_flight_at': '2026-10-18T10:00:00', 'version': '1.4.0', 'updated_at': 'x'}})
        assert g.put('/api/vf/profile', headers=VF | W, json={'profile': prof | {'coins': 38}}).json()['ok']   # son vf PUT'u 'big' idi; oyun profili geri
        au = c.get('/api/sm/admin/users', headers=ADMIN).json()
        eski = next(u for u in au['users'] if u['id'] == uid)
        sv_g = eski['games']['sv']
        assert sv_g['has_profile'] and sv_g['flights'] == 7 and sv_g['hours'] == 2.25 and sv_g['pilots'] == 2 and sv_g['drones'] == 3 and sv_g['pilot'] == 'Eski' \
            and sv_g['last_flight_at'] == '2026-10-18T10:00:00' and sv_g['last_version'] == '1.4.0' and sv_g['last_at'], sv_g
        vf_g = eski['games']['vf']
        assert vf_g['has_profile'] and vf_g['hi_score'] == 12480 and vf_g['levels'] == 1 and vf_g['parkurs'] == 1 and vf_g['coins'] == 38, vf_g
        gs = au['stats']['games']
        assert gs['sv']['users'] == 1 and gs['sv']['flights'] == 7 and gs['sv']['hours'] == 2.2 and gs['vf']['users'] == 1, gs
        assert c.get(f'/api/sm/admin/users/{uid}', headers=ADMIN).json()['games']['sv']['flights'] == 7
        assert all(not u['games']['sv']['has_profile'] for u in au['users'] if u['id'] != uid)
        acc3 = c.get('/api/mt/account', headers={'Authorization': SV['Authorization']})
        assert acc3.status_code == 401   # account yalnız web çerezi (Bearer ile değil); SIMUMAV /me kullanır
        r = g.options('/api/sv/me', headers={'Origin': 'https://simumav.com', 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'authorization'})
        assert r.status_code == 204 and r.headers['access-control-allow-origin'] == 'https://simumav.com' and 'Authorization' in r.headers['access-control-allow-headers']
        r = g.get('/api/sv/me', headers=SV | {'Origin': 'https://simumav.com'}); assert r.headers.get('access-control-allow-origin') == 'https://simumav.com' and r.headers.get('vary') == 'Origin'
        assert 'access-control-allow-origin' not in g.get('/api/sv/me', headers=SV | {'Origin': 'https://kotu.example'}).headers
        assert 'access-control-allow-origin' not in g.get('/api/vf/me', headers=VF | {'Origin': 'https://simumav.com'}).headers   # yalnız /api/sv/
        assert g.options('/api/vf/me', headers={'Origin': 'https://simumav.com', 'Access-Control-Request-Method': 'GET'}).status_code != 204
        # ---- web paketleri: /api/sv/web-releases (X-Release-Key), tar güvenliği, sha, 409, latest atomik
        import hashlib as _hl, io as _io, tarfile as _tf
        def paket(version, ver_icerik=None, kotu_yol=None, symlink=False, eksik=False, kok=''):
            buf = _io.BytesIO()
            on = f'{kok}/' if kok else ''
            with _tf.open(fileobj=buf, mode='w:gz') as tf:
                def ekle(ad, data):
                    ti = _tf.TarInfo(on + ad); ti.size = len(data); tf.addfile(ti, _io.BytesIO(data))
                ekle('VERSION', (ver_icerik if ver_icerik is not None else version).encode() + b'\n')
                if not eksik:
                    ekle('run-simumav.sh', b'#!/bin/sh\n'); ekle('requirements.txt', b'fastapi\n')
                ekle('app/simumav/main.py', b'# x\n')
                if kotu_yol:
                    ekle(kotu_yol, b'x')
                if symlink:
                    ti = _tf.TarInfo('link'); ti.type = _tf.SYMTYPE; ti.linkname = '/etc/passwd'; tf.addfile(ti)
            data = buf.getvalue()
            return data, _hl.sha256(data).hexdigest()
        data, sha = paket('0.1.0')
        gonder = lambda d, s, v='0.1.0', key='sv-anahtar': c.post(f'/api/sv/web-releases', headers={'X-Release-Key': key}, data={'version': v, 'sha256': s, 'notes': 'ilk'}, files={'package': (f'simumav-{v}.tar.gz', d, 'application/gzip')})   # noqa: E731
        assert gonder(data, sha, key='yanlis').status_code == 403
        assert c.post('/api/sv/web-releases', data={'version': '0.1.0', 'sha256': sha}, files={'package': ('x.tar.gz', data)}).status_code == 403
        r = gonder(data, 'ab' * 32); assert r.status_code == 422 and r.json()['code'] == 'bad_sha256', r.text
        assert gonder(data, 'kısa').json()['code'] == 'bad_sha256'
        d2, s2 = paket('0.1.0', kotu_yol='../../etc/cron.d/x'); r = gonder(d2, s2); assert r.status_code == 422 and r.json()['code'] == 'unsafe_archive', r.text
        d3, s3 = paket('0.1.0', kotu_yol='/etc/x'); assert gonder(d3, s3).json()['code'] == 'unsafe_archive'
        d4, s4 = paket('0.1.0', symlink=True); assert gonder(d4, s4).json()['code'] == 'unsafe_archive'
        assert not (settings.RELEASE_DIR / 'sv' / '0.1.0').exists()   # hata: sürüm klasörü silinir
        d5, s5 = paket('0.1.0', ver_icerik='0.0.9'); assert gonder(d5, s5).json()['code'] == 'version_mismatch'
        d6, s6 = paket('0.1.0'); assert gonder(b'degil' + d6[5:], _hl.sha256(b'degil' + d6[5:]).hexdigest()).json()['code'] == 'not_gzip'
        assert gonder(data, sha, v='sürüm').status_code == 422
        assert gonder(data, sha).status_code == 429   # anahtarlı uçta oran sınırı 10/dk/IP
        _RATE.clear()
        d8, s8 = paket('0.1.0', eksik=True); assert gonder(d8, s8).json()['code'] == 'incomplete'
        assert c.get('/api/sv/web-releases/latest').status_code == 404
        r = gonder(data, sha); assert r.status_code == 201 and r.json()['version'] == '0.1.0' and r.json()['file'] == 'sv/0.1.0/simumav-0.1.0.tar.gz', r.text
        assert (settings.RELEASE_DIR / 'sv' / '0.1.0' / 'simumav-0.1.0.tar.gz.sha256').read_text() == f'{sha}  simumav-0.1.0.tar.gz\n'
        assert (settings.RELEASE_DIR / 'sv' / '0.1.0' / 'simumav-0.1.0.tar.gz').read_bytes() == data
        assert (settings.RELEASE_DIR / 'sv' / 'latest').read_text() == '0.1.0\n' and not (settings.RELEASE_DIR / 'sv' / 'latest.tmp').exists()
        assert gonder(data, sha).status_code == 409
        d7, s7 = paket('0.2.0', kok='simumav-0.2.0'); assert gonder(d7, s7, v='v0.2.0').status_code == 201 and (settings.RELEASE_DIR / 'sv' / 'latest').read_text().strip() == '0.2.0'   # tek kök klasör + v öneki
        lt = c.get('/api/sv/web-releases/latest').json(); assert lt['version'] == '0.2.0' and lt['sha256'] == s7 and lt['size'] == len(d7)
        assert c.get('/api/sv/web-releases').status_code == 403
        lst = c.get('/api/sv/web-releases', headers=ADMIN).json(); assert lst['latest'] == '0.2.0' and [x['version'] for x in lst['releases']] == ['0.2.0', '0.1.0']
        assert c.get('/api/vf/web-releases', headers=ADMIN).status_code == 404 and not (settings.RELEASE_DIR / 'sv' / 'sürüm').exists()
        # kayıt / giriş sayfası ?app=vf, doğrulama bağlantısı oyuna işaret eder
        assert c.get('/kayit?app=vf', headers=MTH).text.count('data-site="mt" data-brand="vf"') == 1
        k3 = c.post('/api/mt/auth/prelogin', json={'email': 'oyuncu@test.com'}).json()['kdf']
        c3 = TestClient(app, base_url='https://testserver')
        assert c3.post('/api/mt/auth/register', json={'name': 'Oyuncu', 'email': 'oyuncu@test.com', 'auth_hash': auth_hash('Oyun-1234', k3), 'brand': 'vf'}).json()['ok']
        m = mailer.OUTBOX[-1]
        assert m['from_name'] == 'Mastertool', m['from_name']
        link = re.search(r'https://sshmasters\.com(/dogrula/[A-Za-z0-9_-]+\?app=vf)', m['text']).group(1)
        r = c3.get(link, follow_redirects=False)
        assert r.status_code == 303 and r.headers['location'] == '/hesabim?durum=dogrulandi&app=vf' and 'sm_session' in r.cookies, r.headers
        assert c3.get('/api/vf/profile').json()['profile'] is None
        # oyun dizini: dosya yokken 404 (tanıtım bağlantısıyla), geçici dosyalarla doğru MIME, önbellek yok, CSP, yol güvenliği
        assert c.get('/oyunlar/volfai', headers=MTH, follow_redirects=False).headers['location'] == '/oyunlar/volfai/'
        assert c.get('/oyunlar/volfai', headers={'Host': 'sshmasters.com'}, follow_redirects=False).status_code == 404
        assert c.get('/oyunlar/yok/', headers=MTH).status_code == 404
        r = c.get('/oyunlar/volfai/', headers=MTH); assert r.status_code == 404 and '/oyunlar/volfai/tanitim/' in r.text
        gdir = os.path.join(settings.STATIC_DIR, 'mt', 'oyunlar', 'volfai')
        tmpf = {'index.html': '<!doctype html><title>VOLFAI</title><script type="module" src="js/main.js"></script>', 'sw.js': "const CACHE='volfai-test';",
                'manifest.webmanifest': '{"name":"VOLFAI"}', 'js/main.js': 'export const x = 1;', 'css/style.css': 'body{}', 'icons/icon.svg': '<svg/>'}
        try:
            for name, body in tmpf.items():
                os.makedirs(os.path.dirname(os.path.join(gdir, name)), exist_ok=True)
                with open(os.path.join(gdir, name), 'w', encoding='utf-8') as f:
                    f.write(body)
            r = c.get('/oyunlar/volfai/', headers=MTH)
            assert r.status_code == 200 and r.text == tmpf['index.html'] and r.headers['content-type'].startswith('text/html'), r.text[:100]
            assert r.headers['cache-control'] == 'no-cache' and "script-src 'self'" in r.headers['content-security-policy'] and 'unsafe-inline' not in r.headers['content-security-policy'].split('style-src')[0]
            assert c.get('/oyunlar/volfai/index.html', headers=MTH).text == tmpf['index.html']
            r = c.get('/oyunlar/volfai/sw.js', headers=MTH); assert r.headers['content-type'].startswith('text/javascript') and r.headers['cache-control'] == 'no-cache' and 'content-security-policy' not in r.headers
            assert c.get('/oyunlar/volfai/manifest.webmanifest', headers=MTH).headers['content-type'] == 'application/manifest+json'
            assert c.get('/oyunlar/volfai/js/main.js', headers=MTH).headers['content-type'].startswith('text/javascript')
            assert c.get('/oyunlar/volfai/css/style.css', headers=MTH).headers['content-type'].startswith('text/css')
            assert c.get('/oyunlar/volfai/icons/icon.svg', headers=MTH).headers['content-type'] == 'image/svg+xml'
            assert c.get('/oyunlar/volfai/js/', headers=MTH).status_code == 404 and c.get('/oyunlar/volfai/yok.js', headers=MTH).status_code == 404
            assert c.get('/oyunlar/volfai/..%2F..%2Findex.html', headers=MTH).status_code == 404 and c.get('/oyunlar/volfai/js/..%2F..%2F..%2Fhesap.js', headers=MTH).status_code == 404
            assert c.get('/oyunlar/volfai/.gitignore', headers=MTH).status_code == 404
            assert c.get('/oyunlar/volfai/', headers={'Host': 'sshmasters.com'}).status_code == 404
        finally:
            for name in tmpf:
                os.remove(os.path.join(gdir, name))
            for sub in ('js', 'css', 'icons'):
                os.rmdir(os.path.join(gdir, sub))
        # tanıtım sayfası: site kiti, SEO (8 dil), VideoGame yapılandırılmış verisi, CSP, oynama bağlantısı; depodan gelir
        assert c.get('/oyunlar/volfai/tanitim', headers=MTH, follow_redirects=False).headers['location'] == '/oyunlar/volfai/tanitim/'
        tp = c.get('/oyunlar/volfai/tanitim/', headers=MTH)
        assert tp.status_code == 200 and '<html lang="tr"' in tp.text and 'href="/oyunlar/volfai/"' in tp.text and '/kit.js' in tp.text, tp.text[:300]
        assert 'canonical" href="https://mastertool.download/oyunlar/volfai/tanitim/"' in tp.text and tp.text.count('hreflang=') == 9
        assert '"VideoGame"' in tp.text and '"isAccessibleForFree": true' in tp.text and '<meta name="mt-ga" content="G-7SLLGSBLGD">' in tp.text
        csp = tp.headers['content-security-policy']
        assert "script-src 'self' https://www.googletagmanager.com" in csp and "frame-ancestors 'self'" in csp and tp.headers['cache-control'] == 'no-cache'
        assert '<script>' not in tp.text.split('application/ld+json')[0] and 'style="' not in tp.text   # satır içi betik / stil yok (CSP)
        tpe = c.get('/oyunlar/volfai/tanitim/?lang=en', headers=MTH)
        assert '<html lang="en"' in tpe.text and 'canonical" href="https://mastertool.download/oyunlar/volfai/tanitim/?lang=en"' in tpe.text and 'claim the field' in tpe.text
        assert 'dir="rtl"' in c.get('/oyunlar/volfai/tanitim/?lang=ar', headers=MTH).text
        assert c.get('/oyunlar/volfai/tanitim/volfai.css', headers=MTH).headers['content-type'].startswith('text/css')
        assert c.get('/oyunlar/volfai/tanitim/volfai.js', headers=MTH).headers['content-type'].startswith('text/javascript')
        assert c.get('/oyunlar/volfai/tanitim/', headers={'Host': 'ftpmasters.com'}).status_code == 404
        sm3 = c.get('/sitemap.xml', headers=MTH).text
        assert sm3.count('<loc>https://mastertool.download/oyunlar/volfai/tanitim/') == 8, sm3.count('/oyunlar/')
        home = c.get('/', headers=MTH).text
        assert 'id="oyunlar"' in home and 'href="/oyunlar/volfai/tanitim/"' in home and '/brand/vf.svg' in home
        assert 'href="https://simumav.com/"' in home and '/brand/sv.svg' in home and '<h3>SIMUMAV</h3>' in home and 'Oyna → · Tanıtım →' in home   # SIMUMAV kartı
        sv_p = re.search(r'/brand/sv\.svg" alt=""><h3>SIMUMAV</h3>\s*<p>([^<]+)</p>', home).group(1)
        for lang in ('en', 'fr', 'de', 'es', 'ar', 'zh', 'ru'):   # tanıtım sayfasının ve ana sayfa oyun kartlarının metinleri sözlükte (8 dil)
            d = c.get(f'/i18n/mt.{lang}.json').json()
            assert all(x in d for x in ('Neden VOLFAI', 'HEMEN OYNA', 'Oyunlar', 'Koruma halkası', 'Oyna → · Tanıtım →', sv_p)), lang
        assert c.get('/sitemap.xml', headers=MTH).text.count('simumav') == 0   # dış site; site haritasında yalnız portalın kendi sayfaları

        # ---- son kullanıcı hiçbir yerde iç adres görmez
        for root, _, files in os.walk(settings.STATIC_DIR):
            for fn in files:
                if fn.endswith(('.html', '.js', '.css', '.svg', '.json')):
                    txt = open(os.path.join(root, fn), encoding='utf-8').read().lower()
                    assert 'veilox' not in txt and 'merkez' not in txt, fn
    print('Mastertool testleri geçti.')


if __name__ == '__main__':
    main()
