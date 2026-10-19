"""SSH Master hesap servisi testleri. Çalıştırma (central/sshmaster_server içinde): ../../.venv/bin/python -m tests.test_sshm"""
import base64
import hashlib
import hmac
import os
import re
import tempfile

D = tempfile.mkdtemp()
os.environ.update(SSHM_DATA_DIR=D, SSHM_ENV_FILE=os.path.join(D, 'yok.env'), VEILOX_ENV_FILE=os.path.join(D, 'yok2.env'),
                  SSHM_MAIL_TEST='1', SSHM_CENTRAL_SECRET='merkez-gizli', SSHM_RELEASE_KEY='surum-anahtari', SSHM_SECURE_COOKIE='0',
                  SSHM_SALT_KEY='test-tuz', SSHM_PUBLIC_URL='https://sshmasters.com')
from fastapi.testclient import TestClient  # noqa: E402
from sshm import mailer  # noqa: E402
from sshm.main import app  # noqa: E402

W = {'X-SSHM': '1'}
ADMIN = {'X-Central-Secret': 'merkez-gizli'}


def auth_hash(password, kdf):
    pw = password.encode()
    master = hashlib.pbkdf2_hmac('sha256', pw, base64.b64decode(kdf['salt']), kdf['iter'], 32)
    return base64.b64encode(hashlib.pbkdf2_hmac('sha256', master, pw, 1, 32)).decode()


def last_link(kind):
    m = mailer.OUTBOX[-1]
    return re.search(rf'https://sshmasters\.com(/{kind}/[A-Za-z0-9_-]+)', m['text']).group(1)


def main():
    # test vektörü (istemciyle ortak): Test1234! / AAECAwQFBgcICQoLDA0ODw== / 310000
    assert auth_hash('Test1234!', {'salt': 'AAECAwQFBgcICQoLDA0ODw==', 'iter': 310000}) == 'mLBQ6HQqD19kX/VavErWYq+7tM4mCmGfic7GuQQlBMY='
    with TestClient(app, base_url='https://testserver') as c:
        assert c.get('/api/sm/health').json()['ok'] is True
        # prelogin: kullanıcı yokken deterministik tuz, varlık sızmaz
        k1 = c.post('/api/sm/auth/prelogin', json={'email': 'Ali@Test.com'}).json()['kdf']
        assert k1 == c.post('/api/sm/auth/prelogin', json={'email': 'ali@test.com'}).json()['kdf'] and k1['iter'] == 310000
        # kayıt → doğrulama e-postası (SSH Master markalı)
        r = c.post('/api/sm/auth/register', json={'name': 'Ali Veli', 'email': 'ali@test.com', 'auth_hash': auth_hash('Gizli-123', k1)})
        assert r.status_code == 200, r.text
        m = mailer.OUTBOX[-1]
        assert m['to'] == 'ali@test.com' and m['subject'].startswith('SSH Master') and 'https://sshmasters.com/brand/sm.png' in m['html'], m['subject']
        assert c.post('/api/sm/auth/register', json={'name': 'X', 'email': 'ali@test.com', 'auth_hash': 'kısa'}).status_code == 422
        # doğrulanmadan uygulama girişi 403 unverified
        r = c.post('/api/sm/auth/login', json={'email': 'ali@test.com', 'auth_hash': auth_hash('Gizli-123', k1)})
        assert r.status_code == 403 and r.json()['code'] == 'unverified', r.text
        # doğrula → web oturumu + /hesabim
        link = last_link('dogrula')
        r = c.get(link, follow_redirects=False)
        assert r.status_code == 303 and r.headers['location'].startswith('/hesabim') and 'sm_session' in r.cookies, r.headers
        assert c.get(link, follow_redirects=False).headers['location'].startswith('/giris')   # tek kullanımlık
        acc = c.get('/api/sm/account').json()
        assert acc['user']['email'] == 'ali@test.com' and acc['release'] is None and acc['download_url'].startswith('/indir/'), acc
        # çerezli değişiklik isteği X-SSHM başlığı olmadan reddedilir (CSRF)
        assert c.post('/api/sm/account/rotate-link').status_code == 403
        # uygulama girişi: yanlış / doğru
        assert c.post('/api/sm/auth/login', json={'email': 'ali@test.com', 'auth_hash': auth_hash('yanlis-sifre', k1)}).json()['code'] == 'bad_credentials'
        assert c.post('/api/sm/auth/login', json={'email': 'yok@test.com', 'auth_hash': auth_hash('x' * 8, k1)}).json()['code'] == 'bad_credentials'
        r = c.post('/api/sm/auth/login', json={'email': 'ali@test.com', 'auth_hash': auth_hash('Gizli-123', k1), 'device': 'PC-1', 'app_version': '1.2.0'})
        lg = r.json()
        assert r.status_code == 200 and lg['token'] and lg['kdf'] == k1 and lg['sync_enabled'] is True, lg
        A = {'Authorization': 'Bearer ' + lg['token']}
        app_client = TestClient(app, base_url='https://testserver')   # çerezsiz (uygulama)
        assert app_client.get('/api/sm/me', headers=A).json()['library']['version'] == 0
        # kütüphane: boş → PUT v1 → eski base 409 (sunucudaki blob döner) → doğru base v2
        blob = base64.b64encode(os.urandom(64)).decode()
        assert app_client.get('/api/sm/library', headers=A).json() == {'version': 0, 'updated_at': None, 'blob': None}
        assert app_client.put('/api/sm/library', headers=A, json={'base_version': 0, 'blob': blob}).json() == {'version': 1}
        r = app_client.put('/api/sm/library', headers=A, json={'base_version': 0, 'blob': blob})
        assert r.status_code == 409 and r.json()['code'] == 'conflict' and r.json()['version'] == 1 and r.json()['blob'] == blob, r.text
        assert app_client.put('/api/sm/library', headers=A, json={'base_version': 1, 'blob': blob}).json() == {'version': 2}
        assert app_client.put('/api/sm/library', headers=A, json={'base_version': 2, 'blob': 'bozuk!!'}).status_code == 422
        assert app_client.put('/api/sm/settings', headers=A, json={'sync_enabled': False}).json() == {'sync_enabled': False}
        # kişiye özel indirme: sürüm yok → 404; sürüm yükle (anahtar şart, MZ başlığı şart)
        dl = acc['download_url']
        assert c.get(dl).status_code == 404
        exe = b'MZ' + os.urandom(2000)
        files = {'setup': ('SSH Master Setup 1.2.0.exe', exe, 'application/octet-stream')}
        assert app_client.post('/api/sm/releases', data={'version': '1.2.0'}, files=files).status_code == 403
        assert app_client.post('/api/sm/releases', data={'version': '1.2.0'}, files={'setup': ('a.exe', b'XX' * 10)}, headers={'X-Release-Key': 'surum-anahtari'}).status_code == 422
        r = app_client.post('/api/sm/releases', data={'version': 'v1.2.0', 'notes': 'İlk sürüm'}, files=files, headers={'X-Release-Key': 'surum-anahtari'})
        assert r.status_code == 200 and r.json()['sha256'] == hashlib.sha256(exe).hexdigest(), r.text
        assert app_client.get('/api/sm/releases/latest', headers=A).json()['version'] == '1.2.0'
        r = c.get(dl)
        assert r.status_code == 200 and r.content == exe and 'SSH%20Master%20Setup%201.2.0.exe' in r.headers['content-disposition'], r.headers
        # başka kullanıcı ya da oturumsuz aynı bağlantıyı kullanamaz
        assert TestClient(app, base_url='https://testserver').get(dl, follow_redirects=False).headers['location'] == f'/giris?sonra={dl}'
        k2 = c.post('/api/sm/auth/prelogin', json={'email': 'veli@test.com'}).json()['kdf']
        c2 = TestClient(app, base_url='https://testserver')
        c2.post('/api/sm/auth/register', json={'name': 'Veli', 'email': 'veli@test.com', 'auth_hash': auth_hash('Baska-456', k2)})
        c2.get(last_link('dogrula'))
        assert c2.get(dl).status_code == 403
        # bağlantı yenilenince eskisi çalışmaz
        new_dl = c.post('/api/sm/account/rotate-link', headers=W).json()['download_url']
        assert new_dl != dl and c.get(dl).status_code == 403 and c.get(new_dl).status_code == 200
        # şifre değiştir: yeni tuz + eski/yeni auth → kütüphane silinir, uygulama oturumu düşer
        me = c.get('/api/sm/me').json()
        fresh = c.post('/api/sm/auth/new-salt', headers=W).json()['kdf']
        assert fresh['salt'] != me['kdf']['salt']
        assert c.post('/api/sm/auth/change-password', headers=W, json={'old_auth_hash': auth_hash('yanlis', me['kdf']),
                      'new_auth_hash': auth_hash('Yeni-789', fresh), 'new_salt': fresh['salt']}).json()['code'] == 'bad_credentials'
        r = c.post('/api/sm/auth/change-password', headers=W, json={'old_auth_hash': auth_hash('Gizli-123', me['kdf']),
                   'new_auth_hash': auth_hash('Yeni-789', fresh), 'new_salt': fresh['salt']})
        assert r.status_code == 200, r.text
        assert app_client.get('/api/sm/me', headers=A).json()['code'] == 'session_expired'
        assert c.get('/api/sm/me').json()['library']['version'] == 0   # web oturumu korunur, kütüphane silindi
        k_new = c.post('/api/sm/auth/prelogin', json={'email': 'ali@test.com'}).json()['kdf']
        assert k_new == fresh and c.post('/api/sm/auth/login', json={'email': 'ali@test.com', 'auth_hash': auth_hash('Yeni-789', k_new)}).status_code == 200
        # şifremi unuttum: kayıtlı olmayan e-posta da aynı yanıt; bağlantı yeni tuz verir
        n = len(mailer.OUTBOX)
        assert c.post('/api/sm/auth/forgot', json={'email': 'kimse@test.com'}).json() == {'ok': True} and len(mailer.OUTBOX) == n
        c.post('/api/sm/auth/forgot', json={'email': 'ali@test.com'})
        rl = last_link('sifre-sifirla').split('/')[-1]
        info = c.get(f'/api/sm/auth/reset/{rl}').json()
        assert info['email'] == 'ali@test.com' and info['kdf']['salt'] != k_new['salt']
        assert c.post(f'/api/sm/auth/reset/{rl}', json={'new_auth_hash': auth_hash('Sifir-000', info['kdf'])}).json() == {'ok': True}
        assert c.get(f'/api/sm/auth/reset/{rl}').status_code == 404   # tek kullanımlık
        assert c.post('/api/sm/auth/login', json={'email': 'ali@test.com', 'auth_hash': auth_hash('Sifir-000', info['kdf'])}).status_code == 200
        # zaten kayıtlı e-postayla yeniden kayıt: "zaten hesabınız var" e-postası, hesap değişmez
        c.post('/api/sm/auth/register', json={'name': 'Saldırgan', 'email': 'ali@test.com', 'auth_hash': auth_hash('Kotu-111', k1)})
        assert 'zaten' in mailer.OUTBOX[-1]['subject']
        # yönetim (Merkez iç anahtarı)
        assert c.get('/api/sm/admin/users').status_code == 403
        au = c.get('/api/sm/admin/users', headers=ADMIN).json()
        ali = next(u for u in au['users'] if u['email'] == 'ali@test.com')
        assert au['stats']['users'] == 2 and au['stats']['downloads'] == 2 and ali['downloads'] == 2 and ali['sync_enabled'] == 0, au
        det = c.get(f"/api/sm/admin/users/{ali['id']}", headers=ADMIN).json()
        assert det['user']['name'] == 'Ali Veli' and len(det['downloads']) == 2, det
        # oyun özetleri (Merkez › Mastertool): profil yok → has_profile False, sayaçlar 0; üst kart özeti
        assert ali['games']['sv'] == {'has_profile': False, 'last_at': None, 'flights': 0, 'hours': 0, 'pilots': 0, 'drones': 0, 'pilot': None,
                                      'last_flight_at': None, 'last_version': None}, ali['games']
        assert ali['games']['vf'] == {'has_profile': False, 'last_at': None, 'hi_score': 0, 'levels': 0, 'parkurs': 0, 'coins': 0}
        assert au['stats']['games'] == {'sv': {'name': 'SIMUMAV', 'users': 0, 'flights': 0, 'hours': 0, 'release': None},
                                        'vf': {'name': 'VOLFAI', 'users': 0, 'release': None}}, au['stats']['games']
        assert det['games'] == ali['games']
        assert c.put(f"/api/sm/admin/users/{ali['id']}", headers=ADMIN, json={'status': 'ASKIDA'}).json()['ok']
        assert c.get('/api/sm/me').status_code == 401   # askıya alınan oturumları düştü
        r = c.post('/api/sm/auth/login', json={'email': 'ali@test.com', 'auth_hash': auth_hash('Sifir-000', info['kdf'])})
        assert r.json()['code'] == 'suspended'
        c.put(f"/api/sm/admin/users/{ali['id']}", headers=ADMIN, json={'status': 'AKTIF'})
        assert c.post(f"/api/sm/admin/users/{ali['id']}/reset-mail", headers=ADMIN).json()['sent'] == 'reset'
        rels = c.get('/api/sm/admin/releases', headers=ADMIN).json()
        assert rels[0]['version'] == '1.2.0' and rels[0]['downloads'] == 2
        # sayfalar
        for path in ('/', '/kayit', '/giris', '/sifremi-unuttum', '/hesabim', '/sifre-sifirla/x', '/site.css', '/hesap.js', '/logo.png', '/favicon.svg'):
            assert c.get(path).status_code == 200, path
        assert c.get('/main.py').status_code == 404 and c.get('/../sshm/main.py').status_code == 404
        assert c.delete(f"/api/sm/admin/users/{ali['id']}", headers=ADMIN).json()['ok']
    print('SSH Master hesap servisi testleri geçti.')


if __name__ == '__main__':
    main()
