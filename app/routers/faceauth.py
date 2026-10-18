"""Yüz ile giriş uçları (`/api/auth/face/*`). Çekirdek: app/facelogin.py; akış ve güvenlik modeli: docs/yuz-tanima.md.

Oturumlu (kişisel ayarlar): status, enroll/start (şifre ile), enroll/frame, enroll/finish, enroll/cancel, mode, delete (şifre ile).
Oturumsuz (giriş ekranı; yalnız güvenilir cihaz jetonu): challenge, verify, pin. Politika: Sistem Ayarları › Güvenlik ›
"Yüz ile giriş" (policy.face_enabled, face_threshold, face_liveness)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth, db, facelogin, policy
from .auth_routes import _absent_check, _client_ip, _device_user, _expire_check, _locked

router = APIRouter(prefix='/api/auth/face')


def _policy_on(conn):
    pol = policy.get(conn)
    if not pol['face_enabled']:
        raise HTTPException(403, 'Yüz ile giriş sistem yöneticisi tarafından kapatıldı')
    return pol


def _engine():
    if not facelogin.engine_available():
        raise HTTPException(503, 'Yüz tanıma motoru bu sunucuda kurulu değil')


@router.get('/status')
def face_status(user=Depends(auth.current_user), conn=db.DB):
    pol = policy.get(conn)
    st = facelogin.status(conn, user['id'])
    st.update(policy_enabled=bool(pol['face_enabled']), engine=facelogin.engine_available(), liveness=bool(pol['face_liveness']),
              has_pin=bool(conn.execute('SELECT pin_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0]),
              slots=facelogin.SLOTS, min_slots=facelogin.MIN_SLOTS)
    return st


class EnrollStartIn(BaseModel):
    password: str
    append: bool = False


@router.post('/enroll/start')
def enroll_start(body: EnrollStartIn, user=Depends(auth.current_user), conn=db.DB):
    """Eğitim oturumu açar (mevcut şifre ile — PIN ayarıyla aynı kural). append: ikinci tarama (mevcut kayda eklenir)."""
    _policy_on(conn)
    _engine()
    stored = conn.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0]
    if not auth.verify_password(body.password, stored):
        raise HTTPException(400, 'Şifre hatalı')
    if body.append and not facelogin.has_face(conn, user['id']):
        body.append = False
    eid = facelogin.enroll_start(user['id'], append=body.append)
    return {'enroll_id': eid, 'slots': facelogin.SLOTS, 'min_slots': facelogin.MIN_SLOTS, 'ttl': facelogin.ENROLL_TTL}


class EnrollFrameIn(BaseModel):
    enroll_id: str
    jpg: str   # base64 JPEG (data: öneki olmadan)


@router.post('/enroll/frame')
def enroll_frame(body: EnrollFrameIn, user=Depends(auth.current_user), conn=db.DB):
    e = facelogin.enroll_get(body.enroll_id, user['id'])
    if not e:
        raise HTTPException(410, 'Eğitim oturumu bulunamadı ya da süresi doldu; yeniden başlatın')
    if len(body.jpg) > 1_500_000:
        raise HTTPException(413, 'Kare çok büyük')
    return facelogin.enroll_frame(e, body.jpg)


class EnrollFinishIn(BaseModel):
    enroll_id: str
    mode: Optional[str] = None   # face | face_pin


@router.post('/enroll/finish')
def enroll_finish(body: EnrollFinishIn, request: Request, user=Depends(auth.current_user), conn=db.DB):
    e = facelogin.enroll_get(body.enroll_id, user['id'])
    if not e:
        raise HTTPException(410, 'Eğitim oturumu bulunamadı ya da süresi doldu; yeniden başlatın')
    if body.mode is not None and body.mode not in ('face', 'face_pin'):
        raise HTTPException(400, 'Geçersiz kip')
    try:
        n, slots = facelogin.enroll_finish(conn, e, body.enroll_id, mode=body.mode)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    db.audit(conn, user['id'], 'Yüz tanıtma kaydı oluşturdu' if not e['append'] else 'Yüz tanıtma kaydına ikinci tarama ekledi',
             'user', user['id'], f'{n} gömme · {",".join(slots)} · {_client_ip(request)}')
    return {'ok': True, 'count': n, 'slots': slots, **facelogin.status(conn, user['id'])}


class EnrollCancelIn(BaseModel):
    enroll_id: str


@router.post('/enroll/cancel')
def enroll_cancel(body: EnrollCancelIn, user=Depends(auth.current_user)):
    facelogin.enroll_cancel(body.enroll_id)
    return {'ok': True}


class ModeIn(BaseModel):
    mode: str


@router.put('/mode')
def set_mode(body: ModeIn, user=Depends(auth.current_user), conn=db.DB):
    if not facelogin.record(conn, user['id']):
        raise HTTPException(404, 'Yüz tanıtılmamış')
    try:
        facelogin.set_mode(conn, user['id'], body.mode)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    db.audit(conn, user['id'], 'Yüz ile giriş kipini değiştirdi', 'user', user['id'], body.mode)
    return {'ok': True, 'mode': body.mode}


class DeleteIn(BaseModel):
    password: str


@router.post('/delete')
def delete_face(body: DeleteIn, request: Request, user=Depends(auth.current_user), conn=db.DB):
    stored = conn.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0]
    if not auth.verify_password(body.password, stored):
        raise HTTPException(400, 'Şifre hatalı')
    facelogin.delete(conn, user['id'])
    db.audit(conn, user['id'], 'Yüz verisini sildi', 'user', user['id'], _client_ip(request))
    return {'ok': True, 'enrolled': False}


# ---------- giriş ekranı (oturumsuz; güvenilir cihaz jetonu zorunlu)

class ChallengeIn(BaseModel):
    token: str   # güvenilir cihaz jetonu (trusted_devices)


def _face_user(conn, token):
    u = _device_user(conn, token)
    if not u or not u['active']:
        raise HTTPException(401, 'Bu cihazda yüz ile giriş yok; şifreyle giriş yapın')
    r = facelogin.record(conn, u['id'])
    if not r or not r['enabled'] or not r['count']:
        raise HTTPException(401, 'Bu hesapta yüz tanıtılmamış; şifre ya da PIN ile giriş yapın')
    return u, r


@router.post('/challenge')
def challenge(body: ChallengeIn, request: Request, conn=db.DB):
    pol = _policy_on(conn)
    _engine()
    u, r = _face_user(conn, body.token)
    ip = _client_ip(request)
    wait = _locked(conn, u['username'], ip)
    if wait:
        raise HTTPException(429, f'Çok fazla hatalı deneme. {wait} dakika sonra tekrar deneyin.')
    if not facelogin.rate_ok(f'u:{u["id"]}') or (ip and not facelogin.rate_ok(f'ip:{ip}')):
        raise HTTPException(429, 'Çok sık yüz ile giriş denemesi; biraz bekleyin')
    nonce, ch = facelogin.challenge_new(u['id'], u['device_id'], ip, r['mode'], liveness=bool(pol['face_liveness']))
    return {'challenge': nonce, 'pose': ch['pose'], 'mode': r['mode'], 'expires_in': facelogin.CHALLENGE_TTL,
            'max_frames': facelogin.MAX_FRAMES}


class VerifyIn(BaseModel):
    challenge: str
    jpg: str


def _fail(conn, request, u, ch, nonce, reason):
    """Meydan okuma başarısız kapanır: login_logs'a başarısız deneme (kaba kuvvet kilidi PIN ile aynı) + audit."""
    facelogin.challenge_drop(nonce)
    ip = _client_ip(request)
    conn.execute('INSERT INTO login_logs (user_id, username, success, ip, user_agent, at) VALUES (?,?,0,?,?,?)',
                 (u['id'], u['username'], ip, request.headers.get('user-agent'), db.now()))
    db.audit(conn, u['id'], 'Yüz ile giriş başarısız', 'session', None, f'{reason} · en iyi benzerlik {ch.get("best", 0):.2f} · {ip}')
    conn.commit()
    raise HTTPException(401, reason)


def _finish_login(conn, request, response, u, nonce, how):
    facelogin.challenge_drop(nonce)
    _absent_check(conn, u)
    pol = policy.get(conn)
    _expire_check(conn, u['id'], pol)
    ip = _client_ip(request)
    conn.execute('INSERT INTO login_logs (user_id, username, success, ip, user_agent, at) VALUES (?,?,1,?,?,?)',
                 (u['id'], u['username'], ip, request.headers.get('user-agent'), db.now()))
    token = auth.create_session(conn, u['id'], pol['session_hours'], *auth.request_device(request))
    conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (db.now(), u['id']))
    conn.execute('UPDATE trusted_devices SET last_used = ? WHERE id = ?', (db.now(), u['device_id']))
    db.audit(conn, u['id'], how, 'session', None, ip)
    auth.set_session_cookie(response, request, token, pol['session_hours'])


@router.post('/verify')
def verify(body: VerifyIn, request: Request, response: Response, conn=db.DB):
    """Bir kare: eşleme → canlılık (baş çevirme) → oturum (kip 'face') ya da PIN adımı (kip 'face_pin')."""
    pol = _policy_on(conn)
    ch = facelogin.challenge_get(body.challenge)
    if not ch:
        raise HTTPException(410, 'Doğrulama süresi doldu; yeniden deneyin')
    u = db.row(conn.execute('SELECT id, username, full_name, active, pin_hash FROM users WHERE id = ? AND deleted_at IS NULL', (ch['uid'],)))
    if not u or not u['active']:
        facelogin.challenge_drop(body.challenge)
        raise HTTPException(401, 'Hesap pasif')
    u = dict(u, device_id=ch['device_id'])
    if len(body.jpg) > 1_500_000:
        raise HTTPException(413, 'Kare çok büyük')
    embs = facelogin.embeddings_of(conn, u['id'])
    if not embs:
        facelogin.challenge_drop(body.challenge)
        raise HTTPException(401, 'Bu hesapta yüz tanıtılmamış')
    out = facelogin.verify_frame(ch, embs, body.jpg, facelogin.threshold(pol))
    if out.get('fail'):
        _fail(conn, request, u, ch, body.challenge, out.get('reason') or 'Yüz eşleşmedi')
    out.pop('sim', None)   # benzerlik skoru istemciye sızdırılmaz (eşik kestirimi yapılmasın)
    if out.get('done'):
        if ch['mode'] == 'face_pin':   # savunma: kip face_pin ise done yalnız /pin ile olur
            ch['stage'] = 'pin'
            out.update(done=False, need_pin=True, stage='pin')
        else:
            _finish_login(conn, request, response, u, body.challenge, 'Sisteme yüz ile giriş yaptı')
            out['ok'] = True
    out['frames_left'] = max(0, facelogin.MAX_FRAMES - ch['frames'])
    return out


class FacePinIn(BaseModel):
    challenge: str
    pin: str


@router.post('/pin')
def face_pin(body: FacePinIn, request: Request, response: Response, conn=db.DB):
    """Yüz + PIN kipi: yüz doğrulandıktan sonra PIN ile oturum."""
    _policy_on(conn)
    ch = facelogin.challenge_get(body.challenge)
    if not ch or ch['stage'] != 'pin':
        raise HTTPException(410, 'Önce yüz doğrulaması gerekir')
    u = db.row(conn.execute('SELECT id, username, full_name, active, pin_hash FROM users WHERE id = ? AND deleted_at IS NULL', (ch['uid'],)))
    if not u or not u['active']:
        facelogin.challenge_drop(body.challenge)
        raise HTTPException(401, 'Hesap pasif')
    u = dict(u, device_id=ch['device_id'])
    if not u['pin_hash']:
        facelogin.challenge_drop(body.challenge)
        raise HTTPException(400, 'Bu hesapta PIN tanımlı değil; şifreyle giriş yapın')
    ip = _client_ip(request)
    if _locked(conn, u['username'], ip):
        facelogin.challenge_drop(body.challenge)
        raise HTTPException(429, 'Çok fazla hatalı deneme')
    if not auth.verify_password(body.pin, u['pin_hash']):
        conn.execute('INSERT INTO login_logs (user_id, username, success, ip, user_agent, at) VALUES (?,?,0,?,?,?)',
                     (u['id'], u['username'], ip, request.headers.get('user-agent'), db.now()))
        conn.commit()
        if _locked(conn, u['username'], ip):
            facelogin.challenge_drop(body.challenge)
            raise HTTPException(401, 'PIN çok kez hatalı girildi; şifreyle giriş yapın')
        raise HTTPException(400, 'PIN hatalı')
    _finish_login(conn, request, response, u, body.challenge, 'Sisteme yüz + PIN ile giriş yaptı')
    return {'ok': True}
