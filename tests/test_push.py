"""Arka plan bildirimleri (Web Push): abonelik, şifreli yük (gerçek ECE şifreleme / çözme), arama / mesaj tetikleyicileri, bildirim taraması."""
import base64
import json
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

import http_ece
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from app import db, push
from app.main import app

b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
SENT = []


class FakeResp:
    status_code = 201
    text = ''
    reason = 'Created'
    headers = {}


def fake_post(url, data=None, headers=None, timeout=None, **kw):
    SENT.append((url, data, headers))
    r = FakeResp()
    if 'gone' in url:
        r.status_code = 410
    return r


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    import requests
    requests.post = fake_post
    import pywebpush
    pywebpush.requests.post = fake_post
    push._pool.submit = lambda fn, *a: fn(*a)   # testte eşzamanlı çalıştır

    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    secret = os.urandom(16)
    with TestClient(app) as a, TestClient(app) as b:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        uid = ok(a.post('/api/users', json={'username': 'u2', 'full_name': 'Ayşe Test', 'roles': ['Pilot'], 'password': 'Sifre-1234x'}))['id']
        ok(b.post('/api/auth/login', json={'username': 'u2', 'password': 'Sifre-1234x'}))
        key = ok(b.get('/api/push/key'))['key']
        assert len(base64.urlsafe_b64decode(key + '==')) == 65   # sıkıştırılmamış P-256
        assert (push.config.DATA_DIR / 'vapid.pem').stat().st_mode & 0o077 == 0   # anahtar yalnızca sahibine açık
        assert b.post('/api/push/subscribe', json={'endpoint': 'https://push.example/x', 'keys': {}}).status_code == 400
        ok(b.post('/api/push/subscribe', json={'endpoint': 'https://push.example/u2', 'keys': {'p256dh': b64(pub), 'auth': b64(secret)}}))
        ok(b.post('/api/push/subscribe', json={'endpoint': 'https://push.example/gone', 'keys': {'p256dh': b64(pub), 'auth': b64(secret)}}))
        # Deneme: şifreli yük çözülünce başlık / gövde doğru
        ok(b.post('/api/push/test', json={}))
        url, data, headers = next(x for x in SENT if x[0].endswith('/u2'))
        assert headers['content-encoding'] == 'aes128gcm' and headers['authorization'].startswith('vapid ')
        msg = json.loads(http_ece.decrypt(data, private_key=priv, auth_secret=secret, version='aes128gcm'))
        assert msg['title'] == 'Deneme bildirimi' and msg['type'] == 'notif'
        with db.connect() as conn:   # 410 dönen abonelik silinir
            eps = [r[0] for r in conn.execute('SELECT endpoint FROM push_subs WHERE user_id = ?', (uid,))]
        assert eps == ['https://push.example/u2'], eps
        assert a.post('/api/push/test', json={}).status_code == 400   # admin'in abone cihazı yok
        # Mesaj → alıcıya push
        SENT.clear()
        ok(a.post(f'/api/chat/{uid}', data={'body': 'Merhaba, rampa hazır mı?'}))
        msg = json.loads(http_ece.decrypt(SENT[-1][1], private_key=priv, auth_secret=secret, version='aes128gcm'))
        assert msg['type'] == 'chat' and msg['body'] == 'Merhaba, rampa hazır mı?' and msg['url'].endswith(f'#/messages/u1'), msg
        # Arama → zil push (uygulama kapalı olsa da)
        SENT.clear()
        with a.websocket_connect('/ws/voice') as wa:
            assert json.loads(wa.receive_text())['t'] == 'ready'
            wa.send_text(json.dumps({'t': 'invite', 'to': [uid]}))
            assert json.loads(wa.receive_text())['t'] == 'calling'
        msg = json.loads(http_ece.decrypt(SENT[-1][1], private_key=priv, auth_secret=secret, version='aes128gcm'))
        assert msg['type'] == 'call' and 'arıyor' in msg['body'] and SENT[-1][2].get('urgency') == 'high', (msg, SENT[-1][2])
        # Bildirim taraması: ilk taramada yalnızca durum alınır, sayı artınca push
        push._last.clear()
        assert push._scan() == []
        push._last[uid] = {}
        with db.connect() as conn:
            u = push._user(conn, uid)
            from app import notifications
            items = notifications.for_user(conn, u)
        out = push._scan()
        assert len(out) == (1 if items else 0)
        ok(b.post('/api/push/unsubscribe', json={'endpoint': 'https://push.example/u2', 'keys': {}}))
        with db.connect() as conn:
            assert not conn.execute('SELECT 1 FROM push_subs WHERE user_id = ?', (uid,)).fetchone()
    print('Arka plan bildirimi testleri geçti.')


if __name__ == '__main__':
    main()
