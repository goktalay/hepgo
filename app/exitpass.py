"""QR çıkış kodu imzalama / doğrulama: onaylı izin ve görev formları için güvenlik kapısında okutulacak kod.

QR'ın kendisi tarayıcıda (frontend) üretilir; sunucu yalnızca kodu İMZALAR ve DOĞRULAR. Satır (izin / görev)
durumunu bu modül SORGULAMAZ — çağıran taraf (güvenlik doğrulama uç noktası) satırı yükleyip durumunu denetler.

Gizli anahtar app_kv['exitpass_secret'] içinde bir kez üretilip saklanır ve tekrar kullanılır.
Kod biçimi: base64url(payload) + "." + base64url(hmac_sha256(secret, payload)[:18])  ·  payload = "kind:rid:exp"
"""
import base64
import hashlib
import hmac
import secrets
from datetime import date

SECRET_KEY = 'exitpass_secret'
KINDS = ('leave', 'duty', 'admin')   # admin: sistem yöneticisinin sebepsiz çıkış kodu (rid = kullanıcı id, exp = gün)


def _secret(conn):
    """Kalıcı rastgele gizli anahtar (yoksa bir kez üretilip app_kv'ye yazılır)."""
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (SECRET_KEY,)).fetchone()
    if row and row[0]:
        return row[0]
    sec = secrets.token_hex(32)
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (SECRET_KEY, sec))
    return sec


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _unb64(s: str) -> bytes:
    pad = '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sig(secret: str, payload: str) -> bytes:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()[:18]


def make_token(conn, kind, rid, exp):
    """kind ∈ {'leave','duty'}, rid = satır id, exp = kodun geçerli olduğu son gün/an (ISO metin). Kod metnini döndürür."""
    payload = f'{kind}:{rid}:{exp or ""}'
    secret = _secret(conn)
    return _b64(payload.encode()) + '.' + _b64(_sig(secret, payload))


def verify_token(conn, token):
    """Kodu doğrular → {ok, kind, id, exp} ya da {ok:False, reason}. Satır durumunu DB'den SORGULAMAZ (çağıran yapar)."""
    try:
        p_b64, sig_b64 = (token or '').split('.', 1)
    except ValueError:
        return {'ok': False, 'reason': 'Geçersiz kod'}
    try:
        payload = _unb64(p_b64).decode('utf-8')
        given_sig = _unb64(sig_b64)
    except (ValueError, UnicodeDecodeError):
        return {'ok': False, 'reason': 'Geçersiz kod'}
    secret = _secret(conn)
    if not hmac.compare_digest(given_sig, _sig(secret, payload)):
        return {'ok': False, 'reason': 'Geçersiz kod (imza uyuşmuyor)'}
    parts = payload.split(':', 2)
    if len(parts) != 3:
        return {'ok': False, 'reason': 'Geçersiz kod'}
    kind, rid, exp = parts
    if kind not in KINDS:
        return {'ok': False, 'reason': 'Geçersiz kod'}
    try:
        rid = int(rid)
    except ValueError:
        return {'ok': False, 'reason': 'Geçersiz kod'}
    if exp and exp[:10] < date.today().isoformat():
        return {'ok': False, 'reason': 'Kodun süresi dolmuş'}
    return {'ok': True, 'kind': kind, 'id': rid, 'exp': exp or None}
