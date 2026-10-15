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
                  SSHM_SECURE_COOKIE='0', SSHM_SALT_KEY='test-tuz', SSHM_PUBLIC_URL='https://sshmasters.com', MT_PORTAL_LIVE='0')

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

        # ---- Host'a göre site
        for host, title in (('ftpmasters.com', 'FTP Masters —'), ('www.ftpmasters.com', 'FTP Masters —'), ('mastertool.download', 'Mastertool —'),
                            ('sshmasters.com', 'SSH Master —'), ('testserver', 'SSH Master —')):
            r = c.get('/', headers={'Host': host})
            assert r.status_code == 200 and f'<title>{title}' in r.text, (host, r.text[:200])
        r = c.get('/giris', headers={'Host': 'ftpmasters.com'})
        assert 'data-site="fm"' in r.text and '<title>FTP Masters — Hesap' in r.text
        assert c.get('/favicon.svg', headers={'Host': 'ftpmasters.com'}).content == open(os.path.join(settings.STATIC_DIR, 'fm', 'favicon.svg'), 'rb').read()
        for b in ('sm', 'fm', 'mt'):
            assert c.get(f'/brand/{b}.png').headers['content-type'] == 'image/png'
        assert c.get('/brand/../main.py').status_code == 404 and c.get('/brand/x.png').status_code == 404
        # portal yayında: ürün sitelerinin hesap sayfaları portala yönlenir (marka korunur), portal kendi sayfasını verir
        settings.PORTAL_LIVE = True
        try:
            r = c.get('/giris?sonra=/hesabim', headers={'Host': 'www.sshmasters.com'}, follow_redirects=False)
            assert r.status_code == 302 and r.headers['location'] == 'https://mastertool.download/giris?sonra=/hesabim&app=sm', r.headers
            r = c.get('/dogrula/abc', headers={'Host': 'ftpmasters.com'}, follow_redirects=False)
            assert r.headers['location'] == 'https://mastertool.download/dogrula/abc?app=fm'
            assert c.get('/indir/dl/fm', headers={'Host': 'ftpmasters.com'}, follow_redirects=False).headers['location'].startswith('https://mastertool.download/indir/dl/fm')
            r = c.get('/kayit?app=fm', headers={'Host': 'mastertool.download'})
            assert r.status_code == 200 and 'data-site="mt" data-brand="fm"' in r.text
            assert c.get('/', headers={'Host': 'sshmasters.com'}).status_code == 200   # ürün sayfası yönlenmez
        finally:
            settings.PORTAL_LIVE = False

        # ---- son kullanıcı hiçbir yerde iç adres görmez
        for root, _, files in os.walk(settings.STATIC_DIR):
            for fn in files:
                if fn.endswith(('.html', '.js', '.css', '.svg')):
                    txt = open(os.path.join(root, fn), encoding='utf-8').read().lower()
                    assert 'veilox' not in txt and 'merkez' not in txt, fn
    print('Mastertool testleri geçti.')


if __name__ == '__main__':
    main()
