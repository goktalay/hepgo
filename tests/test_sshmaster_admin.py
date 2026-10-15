"""Merkez › SSH Master vekil uçları: gerçek SSH Master hesap servisi (central/sshmaster_server) geçici portta çalışır,
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


def main():
    env = dict(os.environ, SSHM_DATA_DIR=SD, SSHM_ENV_FILE=os.path.join(SD, 'x'), VEILOX_ENV_FILE=os.path.join(SD, 'y'), SSHM_MAIL_TEST='1',
               SSHM_CENTRAL_SECRET='ic-anahtar', SSHM_SECURE_COOKIE='0')
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
                n = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'Merkez: SSH Master%'").fetchone()[0]
            assert n >= 5, n
    finally:
        srv.terminate()
    print('Merkez › SSH Master testleri geçti.')


if __name__ == '__main__':
    main()
