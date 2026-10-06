"""Native mobil bildirim (Capacitor uygulaması): Android=FCM (HTTP v1), iOS=APNs.

Cihaz jetonları push_native tablosunda tutulur (web push'tan AYRI). push.send() hem web push'a hem buraya dağıtır.
Kimlik bilgileri DOSYADAN/ENV'DEN okunur; YOKSA sessizce devre dışıdır (token toplanır, gönderim yapılmaz):

  FCM (Android):  data/fcm-service-account.json   (Firebase › Proje ayarları › Hizmet hesapları › Yeni özel anahtar)
  APNs (iOS):     data/apns/AuthKey.p8  +  env:  CAYMAZ_APNS_KEY_ID, CAYMAZ_APNS_TEAM_ID, CAYMAZ_APNS_BUNDLE_ID
                  (env: CAYMAZ_APNS_ENV=prod|sandbox — öntanımlı prod)

NOT: APNs HTTP/2 gerektirir → sunucuda `pip install h2` (httpx[http2]). FCM yalnız httpx+cryptography ile çalışır.
JWT'ler PyJWT'siz, doğrudan cryptography ile imzalanır.
"""
import base64
import json
import threading
import time

from . import config, db

FCM_SA = config.DATA_DIR / 'fcm-service-account.json'
APNS_KEY = config.DATA_DIR / 'apns' / 'AuthKey.p8'
import os  # noqa: E402
APNS_KEY_ID = os.environ.get('CAYMAZ_APNS_KEY_ID', '')
APNS_TEAM_ID = os.environ.get('CAYMAZ_APNS_TEAM_ID', '')
APNS_BUNDLE_ID = os.environ.get('CAYMAZ_APNS_BUNDLE_ID', 'com.gokkubbe.hepgo')
APNS_HOST = 'api.sandbox.push.apple.com' if os.environ.get('CAYMAZ_APNS_ENV', 'prod') == 'sandbox' else 'api.push.apple.com'

_lock = threading.Lock()
_fcm_tok = {'v': None, 'exp': 0}
_apns_tok = {'v': None, 'exp': 0}


def available():
    return FCM_SA.exists() or (APNS_KEY.exists() and APNS_KEY_ID and APNS_TEAM_ID)


# ---------------------------------------------------------------- jeton kaydı
def register(conn, user_id, platform, token):
    platform = (platform or '').strip().lower()
    if platform not in ('ios', 'android') or not token:
        return False
    now = db.now()
    conn.execute('''INSERT INTO push_native (user_id, platform, token, created_at, updated_at) VALUES (?,?,?,?,?)
                    ON CONFLICT(token) DO UPDATE SET user_id = excluded.user_id, platform = excluded.platform, updated_at = excluded.updated_at''',
                 (int(user_id), platform, token, now, now))
    return True


def _tokens(conn, user_ids):
    ids = [int(u) for u in user_ids if u]
    if not ids:
        return []
    q = f"SELECT platform, token FROM push_native WHERE user_id IN ({','.join('?' * len(ids))})"
    return [(r[0], r[1]) for r in conn.execute(q, ids)]


def _drop(token):
    try:
        with db.connect() as conn:
            conn.execute('DELETE FROM push_native WHERE token = ?', (token,))
            conn.commit()
    except Exception:   # noqa: BLE001
        pass


# ---------------------------------------------------------------- JWT (cryptography ile; PyJWT yok)
def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def _jwt_rs256(claims, private_key_pem):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_private_key(private_key_pem.encode() if isinstance(private_key_pem, str) else private_key_pem, password=None)
    head = _b64u(json.dumps({'alg': 'RS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    body = _b64u(json.dumps(claims, separators=(',', ':')).encode())
    sig = key.sign(f'{head}.{body}'.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f'{head}.{body}.{_b64u(sig)}'


def _jwt_es256(claims, p8_pem, kid):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    key = serialization.load_pem_private_key(p8_pem.encode() if isinstance(p8_pem, str) else p8_pem, password=None)
    head = _b64u(json.dumps({'alg': 'ES256', 'kid': kid, 'typ': 'JWT'}, separators=(',', ':')).encode())
    body = _b64u(json.dumps(claims, separators=(',', ':')).encode())
    der = key.sign(f'{head}.{body}'.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    raw = r.to_bytes(32, 'big') + s.to_bytes(32, 'big')   # JWS için ham r||s
    return f'{head}.{body}.{_b64u(raw)}'


# ---------------------------------------------------------------- FCM (Android, HTTP v1)
def _fcm_access_token(sa):
    if _fcm_tok['v'] and _fcm_tok['exp'] > time.time() + 60:
        return _fcm_tok['v']
    now = int(time.time())
    claims = {'iss': sa['client_email'], 'scope': 'https://www.googleapis.com/auth/firebase.messaging',
              'aud': sa.get('token_uri', 'https://oauth2.googleapis.com/token'), 'iat': now, 'exp': now + 3600}
    assertion = _jwt_rs256(claims, sa['private_key'])
    import httpx
    r = httpx.post(sa.get('token_uri', 'https://oauth2.googleapis.com/token'),
                   data={'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': assertion}, timeout=15)
    r.raise_for_status()
    tok = r.json()['access_token']
    _fcm_tok['v'] = tok
    _fcm_tok['exp'] = time.time() + 3300
    return tok


def _fcm_send(tokens, payload):
    if not tokens or not FCM_SA.exists():
        return
    try:
        sa = json.loads(FCM_SA.read_text())
        at = _fcm_access_token(sa)
        import httpx
        url = f"https://fcm.googleapis.com/v1/projects/{sa['project_id']}/messages:send"
        data = {k: str(v) for k, v in (payload or {}).items() if v is not None}
        with httpx.Client(timeout=15, headers={'Authorization': f'Bearer {at}'}) as cli:
            for tk in tokens:
                msg = {'message': {'token': tk, 'notification': {'title': payload.get('title') or 'HEPGO', 'body': payload.get('body') or ''},
                                   'data': data, 'android': {'priority': 'high', 'notification': {'click_action': 'OPEN_URL'}}}}
                try:
                    resp = cli.post(url, json=msg)
                    if resp.status_code in (400, 404) and 'UNREGISTERED' in resp.text.upper() or resp.status_code == 404:
                        _drop(tk)
                except Exception:   # noqa: BLE001
                    pass
    except Exception:   # noqa: BLE001
        pass


# ---------------------------------------------------------------- APNs (iOS, HTTP/2)
def _apns_jwt():
    if _apns_tok['v'] and _apns_tok['exp'] > time.time() + 60:
        return _apns_tok['v']
    pem = APNS_KEY.read_text()
    tok = _jwt_es256({'iss': APNS_TEAM_ID, 'iat': int(time.time())}, pem, APNS_KEY_ID)
    _apns_tok['v'] = tok
    _apns_tok['exp'] = time.time() + 2400   # <1 saat (Apple en çok 1 saat)
    return tok


def _apns_send(tokens, payload):
    if not tokens or not (APNS_KEY.exists() and APNS_KEY_ID and APNS_TEAM_ID):
        return
    try:
        import httpx
        jwt_tok = _apns_jwt()
        body = {'aps': {'alert': {'title': payload.get('title') or 'HEPGO', 'body': payload.get('body') or ''}, 'sound': 'default'}}
        for k, v in (payload or {}).items():
            if k not in ('title', 'body') and v is not None:
                body[k] = v
        try:
            cli = httpx.Client(http2=True, timeout=15)   # h2 paketi gerekir (pip install h2)
        except Exception:   # noqa: BLE001 — h2 yoksa APNs atlanır
            return
        with cli:
            for tk in tokens:
                try:
                    resp = cli.post(f'https://{APNS_HOST}/3/device/{tk}',
                                    headers={'authorization': f'bearer {jwt_tok}', 'apns-topic': APNS_BUNDLE_ID, 'apns-push-type': 'alert', 'apns-priority': '10'},
                                    content=json.dumps(body))
                    if resp.status_code == 410 or (resp.status_code == 400 and 'BadDeviceToken' in resp.text):
                        _drop(tk)
                except Exception:   # noqa: BLE001
                    pass
    except Exception:   # noqa: BLE001
        pass


# ---------------------------------------------------------------- toplu gönderim (push.send'den çağrılır)
def send(conn, user_ids, payload):
    """Verilen kullanıcıların native cihazlarına bildirim gönderir (Android→FCM, iOS→APNs). Engelleyebilir; çağıran thread'de çalıştır."""
    if not available():
        return
    rows = _tokens(conn, user_ids)
    if not rows:
        return
    android = [t for p, t in rows if p == 'android']
    ios = [t for p, t in rows if p == 'ios']
    if android:
        _fcm_send(android, payload or {})
    if ios:
        _apns_send(ios, payload or {})
