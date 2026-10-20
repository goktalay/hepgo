"""Merkez › Mastertool (eski adı SSH Master) vekil uçları + Mastertool destek köprüsü: gerçek SSH Master hesap servisi (central/sshmaster_server) geçici portta çalışır,
Merkez kipindeki HEPGO onu iç anahtarla çağırır. Çalıştırma: .venv/bin/python -m tests.test_sshmaster_admin"""
import base64
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
s = socket.socket(); s.bind(('127.0.0.1', 0)); PORT = s.getsockname()[1]; s.close()
SD = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FEDERATION_CENTRAL='1',
                  CAYMAZ_CENTRAL_API_SECRET='ic-anahtar', CAYMAZ_SSHM_URL=f'http://127.0.0.1:{PORT}')
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def auth_hash(pw, kdf):
    m = hashlib.pbkdf2_hmac('sha256', pw.encode(), base64.b64decode(kdf['salt']), kdf['iter'], 32)
    return base64.b64encode(hashlib.pbkdf2_hmac('sha256', m, pw.encode(), 1, 32)).decode()


def mastertool_tickets(a):
    """Mastertool hesap servisinin iç anahtarla çağırdığı destek köprüsü: talepler slug=mastertool ile talep ekranına düşer,
    kullanıcı yalnız kendi e-postasının taleplerini görür, iç not dışarı çıkmaz, destek yanıtı e-posta bildirimini tetikler."""
    from app.routers import sshmaster_admin
    K = {'X-Central-Secret': 'ic-anahtar'}
    plain = TestClient(app, base_url='https://testserver')
    assert plain.get('/api/federation/mastertool/tickets?email=u@test.com').status_code == 403
    assert plain.get('/api/federation/mastertool/tickets?email=u@test.com', headers={'X-Central-Secret': 'yanlis'}).status_code == 403
    r = plain.post('/api/federation/mastertool/tickets', headers=K, json={'email': 'U@Test.com', 'name': 'Kullanıcı Bir', 'app': 'fm',
                   'subject': 'FTPS bağlanmıyor', 'body': 'AUTH TLS hatası', 'category': 'teknik'})
    assert r.status_code == 200, r.text
    tid = r.json()['id']
    assert plain.post('/api/federation/mastertool/tickets', headers=K, json={'email': 'u@test.com', 'subject': '', 'body': ''}).status_code == 400
    lst = plain.get('/api/federation/mastertool/tickets?email=u@test.com', headers=K).json()
    assert lst[0]['id'] == tid and lst[0]['app'] == 'fm' and lst[0]['status'] == 'acik', lst
    assert plain.get('/api/federation/mastertool/tickets?email=baska@test.com', headers=K).json() == []
    assert plain.get(f'/api/federation/mastertool/tickets/{tid}?email=baska@test.com', headers=K).status_code == 404
    # Merkez talep ekranında: Mastertool · FTP Masters, kanal mastertool, etiket uygulama
    row = next(x for x in a.get('/api/central/support/tickets?view=all').json()['tickets'] if x['id'] == tid)
    assert row['company_name'] == 'Mastertool · FTP Masters' and row['channel'] == 'mastertool' and row['tags'] == 'FTP Masters' and row['slug'] == 'mastertool', row
    # SIMUMAV (app sv; docs/simumav.md §9): etiket SIMUMAV, firma adı 'Mastertool · SIMUMAV'; Merkez listesinde source=simumav|mastertool|company filtresi
    sv = plain.post('/api/federation/mastertool/tickets', headers=K, json={'email': 'pilot@test.com', 'name': 'Pilot', 'app': 'sv', 'subject': '[Uçuş / Simülasyon] Düşüyor',
                    'body': 'Kalkışta çakılıyor.\n\n--- SIMUMAV bağlamı ---\nSürüm: 1.2.0', 'category': 'teknik'}).json()
    row2 = next(x for x in a.get('/api/central/support/tickets?view=all').json()['tickets'] if x['id'] == sv['id'])
    assert row2['company_name'] == 'Mastertool · SIMUMAV' and row2['tags'] == 'SIMUMAV' and row2['channel'] == 'mastertool', row2
    ids = lambda src: {x['id'] for x in a.get(f'/api/central/support/tickets?view=all&source={src}').json()['tickets']}   # noqa: E731
    assert sv['id'] in ids('simumav') and tid not in ids('simumav') and tid in ids('mastertool') and sv['id'] not in ids('mastertool')
    assert sv['id'] not in ids('company') and tid not in ids('company') and {tid, sv['id']} <= ids('')
    assert plain.get('/api/federation/mastertool/tickets?email=pilot@test.com', headers=K).json()[0]['app'] == 'sv'
    sent = []
    orig = sshmaster_admin.notify_reply
    sshmaster_admin.notify_reply = lambda t: sent.append(t)
    try:
        assert a.post(f'/api/central/support/tickets/{tid}/messages', json={'body': 'iç not', 'internal': True}).status_code == 200
        assert not sent   # iç not bildirim üretmez
        assert a.post(f'/api/central/support/tickets/{tid}/messages', json={'body': 'Sertifikayı kontrol edin'}).status_code == 200
        assert sent and sent[-1]['opened_by_email'] == 'u@test.com' and sent[-1]['slug'] == 'mastertool'
    finally:
        sshmaster_admin.notify_reply = orig
    t = plain.get(f'/api/federation/mastertool/tickets/{tid}?email=u@test.com', headers=K).json()
    kinds = [m['author_kind'] for m in t['messages']]
    assert 'note' not in kinds and kinds.count('support') == 1 and t['status'] == 'yanit_bekliyor' and 'assignee_id' not in t, t
    assert all('iç not' != m['body'] for m in t['messages'])
    t = plain.post(f'/api/federation/mastertool/tickets/{tid}/messages', headers=K, json={'email': 'u@test.com', 'name': 'Kullanıcı Bir', 'body': 'Düzeldi'}).json()
    assert t['messages'][-1]['author_kind'] == 'company' and t['status'] == 'acik'
    assert plain.post(f'/api/federation/mastertool/tickets/{tid}/close', headers=K, json={'email': 'u@test.com'}).json()['status'] == 'cozuldu'


def masterworld(a):
    """Merkez › Mastertool › MASTERWORLD vekil uçları: Excel içe aktarma (multipart iletimi), CRUD, noktalar; api_key ne yanıtta ne audit'te."""
    from app import db
    xlsx = os.environ.get('MW_XLSX', '/home/gelistirici/mt-work/masterworld-ref/Cesium_Canli_Veri_Kaynaklari.xlsx')
    r = a.post('/api/central/sshm/mw/import', files={'file': ('Kaynaklar.xlsx', open(xlsx, 'rb').read(), 'application/octet-stream')})
    assert r.status_code == 200 and r.json()['added'] >= 51 and r.json()['skipped'] == [], r.text
    assert a.post('/api/central/sshm/mw/import', files={'file': ('x.xlsx', b'degil', 'application/octet-stream')}).status_code == 422
    L = a.get('/api/central/sshm/mw/sources').json()
    assert L['stats']['total'] >= 54 and 'adsb_lol' in L['adapters'] and all('api_key' not in s for s in L['sources'])
    osk = next(s for s in L['sources'] if s['slug'] == 'opensky-network')
    r = a.put(f"/api/central/sshm/mw/sources/{osk['id']}", json={'api_key': 'cok-gizli-anahtar', 'enabled': True, 'zararli': 1})
    assert r.status_code == 200 and r.json()['has_key'] and r.json()['live'] and 'cok-gizli-anahtar' not in r.text, r.text
    r = a.post('/api/central/sshm/mw/sources', json={'slug': 'elle-kamera', 'category': 'camera', 'kind': 'camera', 'name': 'Elle kamera', 'adapter': 'points'})
    assert r.status_code == 200 and r.json()['origin'] == 'manual', r.text
    sid = r.json()['id']
    r = a.post('/api/central/sshm/mw/sources', json={'slug': 'K Ö T Ü', 'category': 'camera', 'kind': 'camera', 'name': 'x'})
    assert r.status_code == 422 and 'slug' in r.json()['detail'], r.text
    p = a.post(f'/api/central/sshm/mw/sources/{sid}/points', json={'name': 'Galata', 'lat': 41.02, 'lon': 28.97, 'media_type': 'image', 'media_url': 'https://k.example/a.jpg'}).json()
    assert a.put(f"/api/central/sshm/mw/points/{p['id']}", json={'name': 'Galata Kulesi'}).json()['name'] == 'Galata Kulesi'
    assert [x['name'] for x in a.get(f'/api/central/sshm/mw/sources/{sid}/points').json()['points']] == ['Galata Kulesi']
    assert a.delete(f"/api/central/sshm/mw/points/{p['id']}").json()['ok']
    assert a.delete(f'/api/central/sshm/mw/sources/{sid}').json()['ok']
    with db.connect() as conn:
        logs = conn.execute("SELECT action, detail FROM audit_logs WHERE action LIKE 'Merkez: MASTERWORLD%'").fetchall()
    assert len(logs) >= 7 and not any('cok-gizli-anahtar' in (x[1] or '') for x in logs), logs
    assert any('api_key=değişti' in (x[1] or '') for x in logs) and any("Excel'den" in x[0] for x in logs)


def main():
    env = dict(os.environ, SSHM_DATA_DIR=SD, SSHM_ENV_FILE=os.path.join(SD, 'x'), VEILOX_ENV_FILE=os.path.join(SD, 'y'), SSHM_MAIL_TEST='1',
               SSHM_CENTRAL_SECRET='ic-anahtar', SSHM_SECURE_COOKIE='0', SIMUMAV_MT_SHARED_SECRET='sv-gizli')
    srv = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'sshm.main:app', '--port', str(PORT), '--log-level', 'warning'],
                           cwd=os.path.join(ROOT, 'central', 'sshmaster_server'), env=env)
    try:
        B = f'http://127.0.0.1:{PORT}'
        for _ in range(60):
            try:
                if httpx.get(B + '/api/sm/health', timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        kdf = httpx.post(B + '/api/sm/auth/prelogin', json={'email': 'u@test.com'}).json()['kdf']
        assert httpx.post(B + '/api/sm/auth/register', json={'name': 'Kullanıcı Bir', 'email': 'u@test.com', 'auth_hash': auth_hash('Sifre-123', kdf)}).status_code == 200
        with TestClient(app, base_url='https://testserver') as a:
            assert a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}).status_code == 200
            assert 'sshmaster' in a.get('/api/auth/me').json()['modules']
            d = a.get('/api/central/sshm/users').json()
            u = d['users'][0]
            assert u['email'] == 'u@test.com' and u['status'] == 'BEKLIYOR' and d['stats']['pending'] == 1, d
            assert a.put(f"/api/central/sshm/users/{u['id']}", json={'status': 'AKTIF', 'note': 'test'}).json()['ok']
            det = a.get(f"/api/central/sshm/users/{u['id']}").json()
            assert det['user']['status'] == 'AKTIF' and det['user']['note'] == 'test', det
            assert a.post(f"/api/central/sshm/users/{u['id']}/reset-mail").json()['sent'] == 'reset'
            # oyun kullanımı (SIMUMAV sunucusunun hesap servisine yazdığı özet) vekil yanıtında games + stats.games
            assert det['games']['sv']['has_profile'] is False and det['games']['vf']['has_profile'] is False
            assert httpx.put(B + '/api/sv/profile', headers={'X-Simumav-Secret': 'sv-gizli'}, json={'user_id': u['id'], 'profile': {
                'pilot': 'Kullanıcı Bir', 'pilots': 1, 'drones': 2, 'flights': 5, 'hours': 1.5, 'last_flight_at': '2026-10-19T09:00:00', 'version': '1.4.0'}}).status_code == 200
            d = a.get('/api/central/sshm/users').json()
            sv = d['users'][0]['games']['sv']
            assert sv['has_profile'] and sv['flights'] == 5 and sv['hours'] == 1.5 and sv['pilots'] == 1 and sv['drones'] == 2 and sv['last_version'] == '1.4.0', sv
            assert d['stats']['games']['sv'] == {'name': 'SIMUMAV', 'users': 1, 'flights': 5, 'hours': 1.5, 'release': None} and d['stats']['games']['vf']['users'] == 0, d['stats']['games']
            assert a.get(f"/api/central/sshm/users/{u['id']}").json()['games']['sv']['flights'] == 5
            # uygulama lisansı (FTP Masters kapat / aç)
            assert a.put(f"/api/central/sshm/users/{u['id']}", json={'apps': {'fm': 'KAPALI'}}).json()['ok']
            det = a.get(f"/api/central/sshm/users/{u['id']}").json()
            assert det['apps']['fm']['license'] == 'KAPALI' and det['apps']['sm']['license'] == 'AKTIF', det
            assert a.put(f"/api/central/sshm/users/{u['id']}", json={'apps': {'fm': 'AKTIF'}}).json()['ok']
            # FTP Masters sürümü (uygulama seçimiyle)
            r = a.post('/api/central/sshm/releases', data={'version': '1.0.0', 'app': 'fm'},
                       files={'setup': ('FTP-Masters-Setup-1.0.0.exe', b'MZ' + b'1' * 300, 'application/octet-stream')})
            assert r.status_code == 200, r.text
            assert [x['app'] for x in a.get('/api/central/sshm/releases?app=fm').json()] == ['fm']
            assert a.post('/api/central/sshm/releases', data={'version': '1.0.1', 'app': 'zz'},
                          files={'setup': ('x.exe', b'MZ', 'application/octet-stream')}).status_code == 400
            mastertool_tickets(a)
            masterworld(a)
            r = a.post('/api/central/sshm/releases', data={'version': '2.0.1', 'notes': 'deneme'},
                       files={'setup': ('SSH Master Setup 2.0.1.exe', b'MZ' + b'0' * 500, 'application/octet-stream')})
            assert r.status_code == 200 and r.json()['version'] == '2.0.1', r.text
            rel = a.get('/api/central/sshm/releases').json()
            assert rel[0]['version'] == '2.0.1' and rel[0]['setup_size'] == 502
            assert a.delete(f"/api/central/sshm/releases/{rel[0]['id']}").json()['ok']
            assert a.delete(f"/api/central/sshm/users/{u['id']}").json()['ok']
            assert a.get('/api/central/sshm/users').json()['stats']['users'] == 0
            from app import db
            with db.connect() as conn:
                n = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'Merkez: Mastertool%' OR action LIKE 'Merkez: SSH Master%'").fetchone()[0]
            assert n >= 7, n
    finally:
        srv.terminate()
    print('Merkez › Mastertool testleri geçti.')


if __name__ == '__main__':
    main()
