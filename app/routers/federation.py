"""Merkez (Veilox) destek girişi — federasyon.

Akış (müşteri firma instance'ında):
  1. Giriş ekranında yerel kullanıcı bulunamaz / şifre tutmazsa, kullanıcı adı+şifre merkeze (Veilox) sorulur.
  2. Merkez, kullanıcıyı doğrular ve "Merkez Destek" rolünde olduğunu teyit ederse, bekleyen bir çapraz-giriş kaydı açılır.
  3. Firma MASTER'ına onay düşer; onaylarsa bu instance'ta süreli, master-benzeri (işlevsel modüller) bir oturum açılır ve
     giriş ekranı otomatik giriş yapar. Onaylanmazsa / 2 dk içinde onay gelmezse iptal olur. Her şey iz kaydına yazılır.

Merkez (Veilox) instance'ı (FEDERATION_CENTRAL=1) yalnızca /api/federation/verify ucunu açar; paylaşılan gizli anahtarla korunur.
"""
import hmac
import secrets
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth, config, db

router = APIRouter(prefix='/api')

PENDING_MINUTES = 2          # onay bekleme süresi
FED_SENTINEL = '*FEDERATED*'   # destek (merkez) kullanıcısının yerel kaydında şifre yerine; normal girişi engeller


# ---------------- Merkez (Veilox) tarafı: doğrulama ucu ----------------
class VerifyIn(BaseModel):
    username: str
    password: str


@router.post('/federation/verify')
def verify(body: VerifyIn, request: Request, conn=db.DB):
    """Merkez doğrulama: kullanıcı+şifre geçerli ve 'Merkez Destek' rolündeyse kimliğini döner. Paylaşılan anahtarla korunur."""
    if not config.FEDERATION_CENTRAL:
        raise HTTPException(404, 'Bulunamadı')
    secret = request.headers.get('x-fed-secret', '')
    if not config.FEDERATION_SECRET or not hmac.compare_digest(secret, config.FEDERATION_SECRET):
        raise HTTPException(403, 'Yetkisiz')
    user = db.row(conn.execute('SELECT * FROM users WHERE username = ? AND deleted_at IS NULL', (body.username.strip(),)))
    ok = bool(user and user['active'] and auth.verify_password(body.password, user['password_hash']))
    if not ok:
        return {'ok': False}
    is_support = conn.execute('SELECT 1 FROM user_roles WHERE user_id = ? AND role = ?',
                              (user['id'], auth.SUPPORT_ROLE)).fetchone() is not None
    if not is_support:
        return {'ok': False, 'reason': 'not_support'}
    return {'ok': True, 'username': user['username'], 'full_name': user['full_name']}


# ---------------- Müşteri tarafı: çapraz giriş ----------------
def enabled():
    return bool(config.FEDERATION_URL and config.FEDERATION_SECRET)


def is_support_account(user):
    """Yerel kayıt bir merkez-destek temsil kaydı mı (normal şifresi yok)?"""
    return bool(user) and user['password_hash'] == FED_SENTINEL


def _client_ip(request):
    return (request.headers.get('x-forwarded-for', '').split(',')[0].strip()
            or (request.client.host if request.client else '')) or '?'


def try_login(conn, username, password, request):
    """Yerel giriş başarısızsa merkeze sor. Destek kullanıcısıysa bekleyen kayıt açıp {pending, token} döner; değilse None."""
    if not enabled():
        return None
    try:
        r = httpx.post(f'{config.FEDERATION_URL}/api/federation/verify',
                       json={'username': username, 'password': password},
                       headers={'X-Fed-Secret': config.FEDERATION_SECRET}, timeout=12)
        data = r.json() if r.status_code == 200 else {}
    except Exception:   # noqa: BLE001 — merkeze ulaşılamazsa normal "hatalı giriş"e düş
        return None
    if not data.get('ok'):
        return None
    token = secrets.token_urlsafe(24)
    now = db.now()
    exp = (datetime.now() + timedelta(minutes=PENDING_MINUTES)).isoformat(timespec='seconds')
    conn.execute('''INSERT INTO crosslogin_requests (token, username, full_name, ip, user_agent, status, created_at, expires_at)
                    VALUES (?,?,?,?,?,'pending',?,?)''',
                 (token, data['username'], data.get('full_name') or data['username'], _client_ip(request),
                  (request.headers.get('user-agent') or '')[:300], now, exp))
    db.audit(conn, None, 'Merkez destek girişi talebi', 'crosslogin', None, f"{data['username']} · {_client_ip(request)}")
    return {'pending': True, 'token': token, 'full_name': data.get('full_name') or data['username'],
            'expires_in': PENDING_MINUTES * 60}


def _expire_old(conn):
    conn.execute("UPDATE crosslogin_requests SET status = 'expired' WHERE status = 'pending' AND expires_at < ?", (db.now(),))


@router.get('/auth/crosslogin/status/{token}')
def poll(token: str, response: Response, conn=db.DB):
    """Giriş ekranı yoklaması. Onaylandıysa oturum çerezi kurulur ve otomatik giriş sağlanır."""
    _expire_old(conn)
    conn.commit()
    row = db.row(conn.execute('SELECT * FROM crosslogin_requests WHERE token = ?', (token,)))
    if not row:
        raise HTTPException(404, 'Talep bulunamadı')
    out = {'status': row['status'], 'full_name': row['full_name']}
    if row['status'] == 'approved' and row['session_token']:
        response.set_cookie(auth.COOKIE, row['session_token'], httponly=True, samesite='lax',
                            max_age=config.FEDERATION_SESSION_HOURS * 3600)
    return out


def _require_master(user):
    if not user.get('master'):
        raise HTTPException(403, 'Yalnızca sistem sahibi (MASTER) onaylayabilir')


@router.get('/auth/crosslogin/pending')
def pending(user=Depends(auth.current_user), conn=db.DB):
    """Firma MASTER'ı için bekleyen çapraz-giriş onayları (+ aktif destek oturumları)."""
    _require_master(user)
    _expire_old(conn)
    conn.commit()
    pend = db.rows(conn.execute(
        "SELECT id, username, full_name, ip, created_at, expires_at FROM crosslogin_requests WHERE status = 'pending' ORDER BY id DESC"))
    active = db.rows(conn.execute(
        '''SELECT u.id AS user_id, u.username, u.full_name, u.support_until FROM users u
           WHERE u.support_until IS NOT NULL AND u.support_until > ? ORDER BY u.support_until DESC''', (db.now(),)))
    return {'pending': pend, 'active': active}


class DecisionIn(BaseModel):
    approve: bool


@router.post('/auth/crosslogin/{req_id}/decision')
def decide(req_id: int, body: DecisionIn, user=Depends(auth.current_user), conn=db.DB):
    """MASTER onayı/reddi. Onayda bu instance'ta süreli master-benzeri oturum açılır."""
    _require_master(user)
    _expire_old(conn)
    row = db.row(conn.execute("SELECT * FROM crosslogin_requests WHERE id = ?", (req_id,)))
    if not row or row['status'] != 'pending':
        raise HTTPException(409, 'Talep artık geçerli değil (zaman aşımı ya da yanıtlanmış olabilir)')
    if not body.approve:
        conn.execute("UPDATE crosslogin_requests SET status = 'rejected', approved_by = ?, decided_at = ? WHERE id = ?",
                     (user['id'], db.now(), req_id))
        db.audit(conn, user['id'], 'Merkez destek girişini reddetti', 'crosslogin', req_id, row['username'])
        conn.commit()
        return {'ok': True, 'status': 'rejected'}
    uid = _ensure_support_user(conn, row['username'], row['full_name'])
    until = (datetime.now() + timedelta(hours=config.FEDERATION_SESSION_HOURS)).isoformat(timespec='seconds')
    conn.execute('UPDATE users SET support_until = ?, active = 1 WHERE id = ?', (until, uid))
    sess = auth.create_session(conn, uid, config.FEDERATION_SESSION_HOURS)
    conn.execute("UPDATE crosslogin_requests SET status = 'approved', session_token = ?, local_user_id = ?, approved_by = ?, decided_at = ? WHERE id = ?",
                 (sess, uid, user['id'], db.now(), req_id))
    db.audit(conn, user['id'], 'Merkez destek girişini onayladı', 'crosslogin', req_id, f"{row['username']} · {row['ip']}")
    conn.commit()
    return {'ok': True, 'status': 'approved'}


@router.post('/auth/crosslogin/end/{support_user_id}')
def end_session(support_user_id: int, user=Depends(auth.current_user), conn=db.DB):
    """MASTER: aktif bir destek oturumunu sonlandırır (yetki biter, oturumları silinir)."""
    _require_master(user)
    row = db.row(conn.execute('SELECT username, support_until FROM users WHERE id = ? AND password_hash = ?',
                              (support_user_id, FED_SENTINEL)))
    if not row:
        raise HTTPException(404, 'Destek oturumu bulunamadı')
    conn.execute('UPDATE users SET support_until = NULL WHERE id = ?', (support_user_id,))
    conn.execute('DELETE FROM sessions WHERE user_id = ?', (support_user_id,))
    db.audit(conn, user['id'], 'Merkez destek oturumunu sonlandırdı', 'crosslogin', support_user_id, row['username'])
    conn.commit()
    return {'ok': True}


def _ensure_support_user(conn, username, full_name):
    """Merkez destek kullanıcısını bu instance'ta temsil eden yerel kaydı döndürür (yoksa oluşturur). Normal şifresi yoktur."""
    row = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute('''INSERT INTO users (username, full_name, password_hash, active, created_at, must_change_password)
                          VALUES (?,?,?,1,?,0)''', (username, full_name or username, FED_SENTINEL, db.now()))
    return cur.lastrowid
