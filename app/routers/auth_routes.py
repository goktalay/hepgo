import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import alerts, auth, catalogs, config, db, integrations, notifications, policy, push, speech
from ..files import is_remote

router = APIRouter(prefix='/api')


class LoginIn(BaseModel):
    username: str
    password: str
    device_token: Optional[str] = None   # bu cihazın eski jetonu (yenilenir)


class PasswordIn(BaseModel):
    current: str
    new: str


def _client_ip(request):
    # Cloudflare tüneli yerel makineden bağlanır; gerçek istemci IP'si o durumda başlıktan okunur.
    ip = request.client.host if request.client else None
    if ip in ('127.0.0.1', '::1'):
        return request.headers.get('cf-connecting-ip') or ip
    return ip


def _locked(conn, username, ip):
    """Kaba kuvvet koruması: son (kilit süresi) dakikadaki başarısız denemeler sınırı aştıysa kalan dakika.

    Sınırlar Program Ayarları → Güvenlik'ten (policy) okunur."""
    pol = policy.get(conn)
    lock_min, user_fails, ip_fails = pol['lockout_minutes'], pol['lockout_fails'], pol['ip_fails']
    since = (datetime.now() - timedelta(minutes=lock_min)).isoformat(timespec='seconds')
    # 1) Kullanıcı bazlı: aynı kullanıcıya SON BAŞARILI girişten sonra art arda hatalı deneme sınırı aşıldıysa.
    last_ok = conn.execute('SELECT MAX(id) FROM login_logs WHERE username = ? AND success = 1',
                           (username,)).fetchone()[0] or 0
    rows = conn.execute('SELECT at FROM login_logs WHERE success = 0 AND at > ? AND username = ? AND id > ? '
                        'ORDER BY id DESC LIMIT ?', (since, username, last_ok, user_fails)).fetchall()
    if len(rows) >= user_fails:
        until = datetime.fromisoformat(rows[-1][0]) + timedelta(minutes=lock_min)
        return max(1, -(-int((until - datetime.now()).total_seconds()) // 60))
    # 2) IP bazlı (hesap taraması): aynı IP, BAŞKA hesaplara deniyorsa. Kullanıcının kendi hataları (1) kapsamında.
    #    Not: Tek işyeri/fabrika tek genel IP (Cloudflare cf-connecting-ip) arkasında olabilir; bu yüzden sabah toplu
    #    girişlerde herkesin kilitlenmemesi için farklı HESAP sayısına bakılır (ip_fails=0 ise IP kuralı kapalı).
    if ip and ip_fails > 0:
        n = conn.execute('SELECT COUNT(DISTINCT username) FROM login_logs WHERE success = 0 AND at > ? AND ip = ? AND username <> ?',
                         (since, ip, username)).fetchone()[0] or 0
        if n >= ip_fails:
            return lock_min
    return 0


def _absent_check(conn, user):
    """İzinli / sağlık raporlu personel giriş yapamaz (sistem sahibi hariç)."""
    if auth.is_master(user['username']):
        return
    a = auth.absence(conn, user['id'])
    if a:
        conn.commit()   # giriş kaydı yazılsın
        raise HTTPException(403, auth.absence_message(a))


@router.post('/auth/login')
def login(body: LoginIn, request: Request, response: Response, conn=db.DB):
    wait = _locked(conn, body.username.strip(), _client_ip(request))
    if wait:
        raise HTTPException(429, f'Çok fazla hatalı deneme. {wait} dakika sonra tekrar deneyin.')
    user = db.row(conn.execute('SELECT * FROM users WHERE username = ?', (body.username.strip(),)))
    ok = bool(user and user['active'] and auth.verify_password(body.password, user['password_hash']))
    conn.execute(
        'INSERT INTO login_logs (user_id, username, success, ip, user_agent, at) VALUES (?,?,?,?,?,?)',
        (user['id'] if user else None, body.username.strip(), int(ok),
         _client_ip(request), request.headers.get('user-agent'), db.now()))
    if not ok:
        # Başarısız deneme kaydı yine de yazılsın diye hata öncesi commit edilir.
        conn.commit()
        # Merkez (Veilox) destek girişi: yerel kullanıcı yoksa ya da destek temsil kaydıysa merkeze sor (onaylı çapraz giriş)
        from . import federation
        if federation.enabled() and (user is None or federation.is_support_account(user)):
            fed = federation.try_login(conn, body.username.strip(), body.password, request)
            if fed:
                conn.commit()
                return fed
        raise HTTPException(401, 'Kullanıcı adı veya şifre hatalı')
    _absent_check(conn, user)
    if not auth.is_master(user['username']):   # merkez firmayı pasife aldıysa (yumuşak askı)
        from .. import central_client
        s = central_client.suspension()
        if s.get('suspended'):
            conn.commit()
            raise HTTPException(403, central_client.suspended_message(s))
    pol = policy.get(conn)
    _expire_check(conn, user['id'], pol)
    token = auth.create_session(conn, user['id'], pol['session_hours'])
    conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (db.now(), user['id']))
    db.audit(conn, user['id'], 'Sisteme giriş yaptı', 'session', None, _client_ip(request))
    auth.set_session_cookie(response, request, token, pol['session_hours'])
    return {'ok': True, 'device_token': _trust_device(conn, user['id'], request, body.device_token)}


def _expire_check(conn, uid, pol):
    """Şifre geçerlilik süresi dolduysa kullanıcıyı ilk fırsatta şifre değiştirmeye zorlar."""
    if pol['expire_days'] <= 0:
        return
    row = conn.execute('SELECT password_changed_at FROM users WHERE id = ?', (uid,)).fetchone()
    changed = row[0] if row else None
    if not changed:   # hiç kaydı yoksa şimdiden başlat (bir sonraki dolumda uyarır)
        conn.execute('UPDATE users SET password_changed_at = ? WHERE id = ?', (db.now(), uid))
        return
    try:
        age = (datetime.now() - datetime.fromisoformat(changed)).days
    except ValueError:
        return
    if age >= pol['expire_days']:
        conn.execute('UPDATE users SET must_change_password = 1 WHERE id = ?', (uid,))


# ---------- Bu cihazdaki hesaplar ve PIN ile giriş
# Şifreyle giriş yapılan cihaza bir jeton verilir (tarayıcıda saklanır). Giriş ekranı bu jetonlarla cihazda daha önce giriş
# yapmış hesapları (ad, fotoğraf) listeler; PIN'i olan hesap 4 haneli PIN'le, olmayan yalnızca şifreyle (kullanıcı adı
# yazmadan) girer. PIN hatası şifre hatası gibi sayılır; sınır aşılınca o cihazın jetonu silinir (yeniden şifre gerekir).
DEVICE_DAYS = 90
_sha = lambda t: hashlib.sha256(t.encode()).hexdigest()


def _trust_device(conn, uid, request, old=None):
    if old:   # aynı cihazın eski jetonu yenilenir
        conn.execute('DELETE FROM trusted_devices WHERE token_hash = ? AND user_id = ?', (_sha(old), uid))
    tok = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO trusted_devices (user_id, token_hash, user_agent, created_at, last_used) VALUES (?,?,?,?,?)',
                 (uid, _sha(tok), (request.headers.get('user-agent') or '')[:300], db.now(), db.now()))
    cut = (datetime.now() - timedelta(days=DEVICE_DAYS)).isoformat(timespec='seconds')
    conn.execute('DELETE FROM trusted_devices WHERE IFNULL(last_used, created_at) < ?', (cut,))
    return tok


def _device_user(conn, token):
    if not token or len(token) > 200:
        return None
    return db.row(conn.execute(
        '''SELECT u.id, u.username, u.full_name, u.photo, u.active, u.pin_hash, d.id AS device_id FROM trusted_devices d
           JOIN users u ON u.id = d.user_id WHERE d.token_hash = ? AND u.deleted_at IS NULL''', (_sha(token),)))


class DevicesIn(BaseModel):
    tokens: list[str]


@router.post('/auth/devices')
def devices(body: DevicesIn, conn=db.DB):
    """Giriş ekranı: bu cihazda kayıtlı hesaplar (geçersiz / pasif olanlar dönmez)."""
    out = []
    for t in body.tokens[:10]:
        u = _device_user(conn, t)
        if u and u['active']:
            out.append({'token': t, 'id': u['id'], 'username': u['username'], 'full_name': u['full_name'], 'has_pin': bool(u['pin_hash'])})
    return out


class PinLoginIn(BaseModel):
    token: str
    pin: str


@router.post('/auth/login-pin')
def login_pin(body: PinLoginIn, request: Request, response: Response, conn=db.DB):
    if not policy.get(conn)['pin_enabled']:
        raise HTTPException(403, 'PIN ile giriş sistem yöneticisi tarafından kapatıldı; şifreyle giriş yapın')
    u = _device_user(conn, body.token)
    if not u or not u['active'] or not u['pin_hash']:
        raise HTTPException(401, 'Bu cihazda PIN ile giriş yok; şifreyle giriş yapın')
    ip = _client_ip(request)
    wait = _locked(conn, u['username'], ip)
    if wait:
        raise HTTPException(429, f'Çok fazla hatalı deneme. {wait} dakika sonra tekrar deneyin.')
    ok = auth.verify_password(body.pin, u['pin_hash'])
    conn.execute('INSERT INTO login_logs (user_id, username, success, ip, user_agent, at) VALUES (?,?,?,?,?,?)',
                 (u['id'], u['username'], int(ok), ip, request.headers.get('user-agent'), db.now()))
    if not ok:
        if _locked(conn, u['username'], ip):   # sınır aşıldı: bu cihazda PIN kapanır, şifre gerekir
            conn.execute('DELETE FROM trusted_devices WHERE id = ?', (u['device_id'],))
            conn.commit()
            raise HTTPException(401, 'PIN çok kez hatalı girildi; şifreyle giriş yapın')
        conn.commit()
        raise HTTPException(400, 'PIN hatalı')
    _absent_check(conn, u)
    pol = policy.get(conn)
    _expire_check(conn, u['id'], pol)
    token = auth.create_session(conn, u['id'], pol['session_hours'])
    conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (db.now(), u['id']))
    conn.execute('UPDATE trusted_devices SET last_used = ? WHERE id = ?', (db.now(), u['device_id']))
    db.audit(conn, u['id'], 'Sisteme PIN ile giriş yaptı', 'session', None, ip)
    auth.set_session_cookie(response, request, token, pol['session_hours'])
    return {'ok': True}


class PinIn(BaseModel):
    password: str
    pin: Optional[str] = None


@router.put('/auth/pin')
def set_pin(body: PinIn, user=Depends(auth.current_user), conn=db.DB):
    """PIN'i açar / değiştirir (mevcut şifre ile). pin boşsa PIN kapanır."""
    stored = conn.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0]
    if not auth.verify_password(body.password, stored):
        raise HTTPException(400, 'Şifre hatalı')
    if body.pin is None:
        conn.execute('UPDATE users SET pin_hash = NULL WHERE id = ?', (user['id'],))
        db.audit(conn, user['id'], 'Giriş PIN\'ini kapattı', 'user', user['id'], None)
        return {'has_pin': False}
    pol = policy.get(conn)
    if not pol['pin_enabled']:
        raise HTTPException(403, 'PIN ile giriş sistem yöneticisi tarafından kapatıldı')
    n = pol['pin_length']
    if not re.fullmatch(rf'\d{{{n}}}', body.pin):
        raise HTTPException(400, f'PIN {n} rakam olmalı')
    if len(set(body.pin)) == 1 or body.pin in ('1234', '4321', '0123', '12345', '123456', '654321', '1234567', '12345678'):
        raise HTTPException(400, 'Bu PIN çok kolay tahmin edilir; başka bir PIN seçin')
    conn.execute('UPDATE users SET pin_hash = ? WHERE id = ?', (auth.hash_password(body.pin), user['id']))
    db.audit(conn, user['id'], 'Giriş PIN\'ini ayarladı', 'user', user['id'], None)
    return {'has_pin': True}


class UnlockIn(BaseModel):
    password: Optional[str] = None
    pin: Optional[str] = None   # PIN açıksa bekleme ekranı PIN ile de açılır


@router.post('/auth/unlock')
def unlock(body: UnlockIn, request: Request, response: Response, user=Depends(auth.current_user), conn=db.DB):
    """Bekleme ekranının kilidi: oturumdaki kullanıcının şifresi doğrulanır. Hatalı denemeler giriş denemesi sayılır;
    sınır aşılınca oturum kapatılır (yeniden giriş gerekir)."""
    ip = _client_ip(request)
    if _locked(conn, user['username'], ip):
        _end_session(conn, request, response)
        raise HTTPException(401, 'Çok fazla hatalı deneme; oturum kapatıldı')
    pw_hash, pin_hash = conn.execute('SELECT password_hash, pin_hash FROM users WHERE id = ?', (user['id'],)).fetchone()
    ok = (body.pin is not None and pin_hash and auth.verify_password(body.pin, pin_hash)) or \
         (body.password is not None and auth.verify_password(body.password, pw_hash))
    if ok:
        db.audit(conn, user['id'], 'Bekleme ekranı kilidini açtı', 'session', None, ip)
        return {'ok': True}
    conn.execute('INSERT INTO login_logs (user_id, username, success, ip, user_agent, at) VALUES (?,?,0,?,?,?)',
                 (user['id'], user['username'], ip, request.headers.get('user-agent'), db.now()))
    if _locked(conn, user['username'], ip):
        _end_session(conn, request, response)
        conn.commit()
        raise HTTPException(401, 'Çok fazla hatalı deneme; oturum kapatıldı')
    conn.commit()
    raise HTTPException(400, 'PIN hatalı' if body.pin is not None else 'Şifre hatalı')


def _end_session(conn, request, response):
    token = request.cookies.get(auth.COOKIE)
    if token:
        conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
    response.delete_cookie(auth.COOKIE)


@router.post('/auth/logout')
def logout(request: Request, response: Response, conn=db.DB):
    token = request.cookies.get(auth.COOKIE)
    if token:
        row = conn.execute('SELECT user_id FROM sessions WHERE token = ?', (token,)).fetchone()
        if row:   # çıkış yapan kullanıcı hemen çevrimdışı görünsün
            conn.execute('UPDATE users SET last_seen = NULL WHERE id = ?', (row[0],))
            db.audit(conn, row[0], 'Sistemden çıkış yaptı', 'session', None, _client_ip(request))
        conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
    response.delete_cookie(auth.COOKIE)
    return {'ok': True}


@router.get('/auth/me')
def me(user=Depends(auth.current_user), conn=db.DB):
    out = {k: user[k] for k in ('id', 'username', 'full_name', 'photo', 'roles', 'modules', 'master')}
    out['write_modules'] = user.get('write_modules', user['modules'])   # Rol Yönetimi: yazma yetkisi olan modüller
    out['console'] = config.CONSOLE_ENABLED and bool(user['master'])   # web terminal açık mı (Araçlar › Terminal)
    out['support'] = bool(user.get('support'))   # merkez destek oturumu mu (arayüzde uyarı şeridi için)
    out['ai'] = bool(config.AI_API_KEY)   # yapay zeka asistanı tanımlı mı (anahtar yoksa maskot ve YZ ayarları gizlenir)
    out['speech'] = speech.enabled('dictation', conn)   # sesle yazdırma: Konuşma Tanıma entegrasyonu + modül anahtarı
    out['nvr'] = bool(config.NVR_HOST and config.NVR_USER)   # NVR entegrasyonu aktif mi (Kameralar modülü yalnızca o zaman görünür)
    out['printer'] = integrations.is_added(conn, 'printer') and integrations.is_enabled(conn, 'printer')   # Yazıcı entegrasyonu eklenmiş + açık mı (Yazıcı Yönetimi yalnız o zaman görünür)
    from .usertasks import pending_for   # günlük görevler: bekleyen ZORUNLU görev → ana ekranda uyarı şeridi
    _pend = pending_for(conn, user['id'])
    out['pending_tasks'] = sum(1 for t in _pend if t['mandatory'])
    from .surveys import pending_for as _survey_pending   # zorunlu + cevaplanmamış anket → ana ekranda uyarı şeridi
    out['pending_surveys'] = len(_survey_pending(conn, user['id']))
    out['real_roles'] = user.get('real_roles', user['roles'])   # MASTER: ekranda gösterilen gerçek (atanmış) roller
    out['prefs'] = json.loads(user['prefs']) if user['prefs'] else {}
    out['has_pin'] = bool(conn.execute('SELECT pin_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0])
    out['must_change_password'] = bool(user['must_change_password']) and config.FORCE_PASSWORD_CHANGE and policy.get(conn)['force_first_change']
    from .. import kvkk
    out['kvkk_pending'] = (not user.get('support')) and (not kvkk.user_terms_ok(conn, user['id']))   # girişte zorunlu KVKK onayı (destek oturumu hariç)
    if config.FEDERATION_CENTRAL:   # Merkez (Veilox) instance: özlük evrak geri sayımı YOK (destek ekibi, fabrika personeli değil)
        out['docs_due'] = None
    else:
        from .hr import my_docs
        d = my_docs(conn, user['id'])   # eksik özlük evrakı → başlıkta geri sayım
        out['docs_due'] = {'missing': len(d['missing']), 'deadline': d['deadline']} if d and d['missing'] else None
    return out


@router.put('/auth/prefs/{key}')
def set_pref(key: str, value=Body(...), user=Depends(auth.current_user), conn=db.DB):
    """Kullanıcıya özel arayüz tercihi (ör. Yönetim panelinde gösterilen rakamlar); tüm cihazlarda aynı kalır."""
    if len(key) > 40 or len(json.dumps(value)) > 4000:
        raise HTTPException(400, 'Tercih çok büyük')
    prefs = json.loads(user['prefs']) if user['prefs'] else {}
    prefs[key] = value
    conn.execute('UPDATE users SET prefs = ? WHERE id = ?', (json.dumps(prefs, ensure_ascii=False), user['id']))
    db.audit(conn, user['id'], 'Görünüm tercihini değiştirdi', 'pref', key, json.dumps(value, ensure_ascii=False)[:200])
    return {'ok': True}


# Arayüz hareketleri: sayfaya giriş/çıkış, yazdırma vb. Tarayıcı kapanırken sendBeacon ile de gelebilir
# (text/plain gövde), bu yüzden gövde elle çözülür.
ACTIVITY = {'enter': 'Sayfaya girdi', 'leave': 'Sayfadan çıktı', 'print': 'Yazdırdı', 'open': 'Açtı'}


def _write_activity(user_id, events):
    with db.connect() as conn:
        for e in events[:20]:
            action = ACTIVITY.get(e.get('event')) if isinstance(e, dict) else None
            if not action:
                continue
            title = str(e.get('title') or '')[:200]
            secs = e.get('seconds')
            detail = title + (f' · {int(secs)} sn kaldı' if isinstance(secs, (int, float)) and e.get('event') == 'leave' else '')
            db.audit(conn, user_id, action, 'page', str(e.get('path') or '')[:200], detail)


@router.post('/activity')
async def activity(request: Request, user=Depends(auth.current_user)):
    try:
        body = json.loads((await request.body()) or b'{}')
    except ValueError:
        raise HTTPException(400, 'Geçersiz kayıt')
    # Veritabanı yazımı iş parçacığında: olay döngüsü kilit beklerken bloklanmasın
    await run_in_threadpool(_write_activity, user['id'], body if isinstance(body, list) else [body])
    return {'ok': True}


# ---------- Şifremi unuttum: e-posta ile 6 haneli kod → yeni şifre (oturum gerektirmez) ----------
class ForgotIn(BaseModel):
    username: str


class ResetIn(BaseModel):
    username: str
    code: str
    password: str


_forgot_hits = {}   # ip → [zamanlar]
FORGOT_LIMIT, FORGOT_WINDOW = 8, 3600


def _find_user_by_ident(conn, ident):
    return db.row(conn.execute(
        'SELECT id, username, email, active FROM users WHERE username = ? OR (email IS NOT NULL AND lower(email) = lower(?))',
        (ident, ident)))


@router.post('/auth/forgot')
def forgot_password(body: ForgotIn, request: Request, conn=db.DB):
    """Kullanıcı adı / e-posta ile şifre sıfırlama kodu ister; kayıtlı e-postaya 6 haneli kod gönderilir."""
    from .. import sysmail
    ident = (body.username or '').strip()
    if not ident:
        raise HTTPException(400, 'Kullanıcı adı veya e-posta girin')
    if not sysmail.enabled():
        raise HTTPException(503, 'E-posta ile sıfırlama bu an kullanılamıyor. Lütfen yöneticinize başvurun.')
    ip = _client_ip(request)
    now = time.time()
    _forgot_hits[ip] = [t for t in _forgot_hits.get(ip, []) if now - t < FORGOT_WINDOW]
    if len(_forgot_hits[ip]) >= FORGOT_LIMIT:
        raise HTTPException(429, 'Çok fazla istek. Daha sonra tekrar deneyin.')
    _forgot_hits[ip].append(now)
    user = _find_user_by_ident(conn, ident)
    if not (user and user['active'] and (user['email'] or '').strip()):
        # Kullanıcı yok ya da e-posta kayıtlı değil → kodu üretmeyiz; kullanıcıyı yönlendiririz
        return {'ok': True, 'has_email': False}
    code = f'{secrets.randbelow(1000000):06d}'
    exp = (datetime.now() + timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%S')
    conn.execute('DELETE FROM password_resets WHERE user_id = ?', (user['id'],))
    conn.execute('INSERT INTO password_resets (user_id, code_hash, expires_at, attempts, used, created_at) VALUES (?,?,?,?,?,?)',
                 (user['id'], auth.hash_password(code), exp, 0, 0, db.now()))
    conn.commit()
    try:
        sysmail.send_reset_code(user['email'].strip(), code, user['username'])
    except Exception:   # noqa: BLE001
        raise HTTPException(502, 'E-posta gönderilemedi. Biraz sonra tekrar deneyin.')
    m = user['email'].strip().split('@')
    masked = (m[0][:2] + '***@' + m[1]) if len(m) == 2 else user['email'].strip()
    return {'ok': True, 'has_email': True, 'sent_to': masked}


@router.post('/auth/reset')
def reset_password(body: ResetIn, request: Request, conn=db.DB):
    """Sıfırlama kodu + yeni şifre ile şifreyi değiştirir; tüm oturumları kapatır."""
    ident = (body.username or '').strip()
    user = _find_user_by_ident(conn, ident)
    if not user:
        raise HTTPException(400, 'Geçersiz istek')
    r = db.row(conn.execute('SELECT id, code_hash, expires_at, attempts, used FROM password_resets WHERE user_id = ? ORDER BY id DESC LIMIT 1', (user['id'],)))
    if not r or r['used']:
        raise HTTPException(400, 'Sıfırlama kodu bulunamadı. Yeni kod isteyin.')
    try:
        if datetime.now() > datetime.fromisoformat(r['expires_at']):
            raise HTTPException(400, 'Kodun süresi doldu. Yeni kod isteyin.')
    except ValueError:
        pass
    if (r['attempts'] or 0) >= 5:
        raise HTTPException(429, 'Çok fazla hatalı deneme. Yeni kod isteyin.')
    if not auth.verify_password((body.code or '').strip(), r['code_hash']):
        conn.execute('UPDATE password_resets SET attempts = attempts + 1 WHERE id = ?', (r['id'],))
        conn.commit()
        raise HTTPException(400, 'Kod hatalı')
    pol = policy.get(conn)
    try:
        policy.validate_password(pol, body.password, user['username'])
    except ValueError as e:
        raise HTTPException(400, str(e))
    if pol['reuse_block'] and any(auth.verify_password(body.password, h) for h in policy.recent_hashes(conn, user['id'], pol['reuse_block'])):
        raise HTTPException(400, f"Son {pol['reuse_block']} şifrenizden birini yeniden kullanamazsınız")
    new_hash = auth.hash_password(body.password)
    conn.execute('UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?', (new_hash, user['id']))
    policy.record_history(conn, user['id'], new_hash)
    conn.execute('UPDATE password_resets SET used = 1 WHERE id = ?', (r['id'],))
    conn.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))   # güvenlik: tüm oturumları kapat
    db.audit(conn, user['id'], 'Şifresini sıfırladı (e-posta kodu)', 'user', user['id'], _client_ip(request))
    conn.commit()
    return {'ok': True}


@router.post('/auth/password')
def change_password(body: PasswordIn, request: Request, user=Depends(auth.current_user), conn=db.DB):
    stored = conn.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0]
    if not auth.verify_password(body.current, stored):
        raise HTTPException(400, 'Mevcut şifre hatalı')
    pol = policy.get(conn)
    try:
        policy.validate_password(pol, body.new, user['username'])
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.new == body.current:
        raise HTTPException(400, 'Yeni şifre mevcut şifreyle aynı olamaz')
    # Son N şifrenin yeniden kullanımını engelle (Güvenlik kuralı)
    if pol['reuse_block'] and any(auth.verify_password(body.new, h) for h in policy.recent_hashes(conn, user['id'], pol['reuse_block'])):
        raise HTTPException(400, f"Son {pol['reuse_block']} şifrenizden birini yeniden kullanamazsınız")
    new_hash = auth.hash_password(body.new)
    conn.execute('UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?', (new_hash, user['id']))
    policy.record_history(conn, user['id'], new_hash)
    # Şifre değişince diğer oturumlar iptal (ele geçirilmiş olası saldırgan oturumu kalmasın); mevcut oturum korunur
    cur_token = request.cookies.get(auth.COOKIE)
    conn.execute('DELETE FROM sessions WHERE user_id = ? AND token IS NOT ?', (user['id'], cur_token))
    db.audit(conn, user['id'], 'Şifresini değiştirdi', 'user', user['id'])
    return {'ok': True}


@router.get('/meta')
def meta(request: Request, conn=db.DB):
    # remote: internetten (caymaz.app) bağlanıldı; video/log yükleme için yerel adres gösterilir
    # remote: büyük dosya yükleme engeli için. Yerel-yükleme zorunluluğu kapalıysa (bulut kurulum) her yerden
    # yüklemeye izin verilir → remote=false raporlanır (arayüzdeki "yalnızca yerel ağ" engelleri kalkar).
    remote = is_remote(request) and config.LOCAL_UPLOAD_REQUIRED
    from .system import brand_logo_url   # firma kimliği: yüklenmiş logo (tenant'a özel), yoksa None
    return {'company': config.COMPANY_NAME, 'company_legal': config.COMPANY_LEGAL_NAME,
            'logo_url': brand_logo_url(conn), 'roles': auth.all_roles(), 'remote': remote, 'local_url': config.LOCAL_URL,
            'white_label': config.WHITE_LABEL, 'local_upload_required': config.LOCAL_UPLOAD_REQUIRED,
            'maps_key': config.GOOGLE_MAPS_API_KEY}   # Google Haritalar (istemci tarafı; yoksa harita OSM'e düşer


@router.get('/plane')
def get_plane(user=Depends(auth.current_user)):
    """Geriye uyumluluk: varsayılan ürünün şeması. Yeni kod /api/products/{id}/plane kullanır."""
    return {**catalogs.plane_json(catalogs.DEFAULT_SCHEMA), 'schema': catalogs.DEFAULT_SCHEMA}


@router.get('/people')
def people(role: str = '', user=Depends(auth.current_user), conn=db.DB):
    """Seçim listeleri için rolüne göre aktif personel (ör. depocular, şoförler); rol verilmezse tüm personel."""
    interns = auth.interns(conn)
    if not role:
        rows = db.rows(conn.execute(
            'SELECT id, full_name, username, photo FROM users WHERE active = 1 AND deleted_at IS NULL ORDER BY full_name'))
    else:   # yardımcı personel rollerinde stajerler de listelenir (en sonda)
        roles = (role, auth.INTERN) if role in auth.HELPER_ROLES else (role,)
        rows = db.rows(conn.execute(
            f'''SELECT DISTINCT u.id, u.full_name, u.username, u.photo FROM users u JOIN user_roles r ON r.user_id = u.id
                WHERE r.role IN ({','.join('?' * len(roles))}) AND u.active = 1 AND u.deleted_at IS NULL ORDER BY u.full_name''', roles))
    for r in rows:
        r['intern'] = r['id'] in interns
    if role in auth.HELPER_ROLES:
        rows.sort(key=lambda r: (r['intern'], r['full_name']))
    return rows


@router.get('/alerts')
def list_alerts(user=Depends(auth.current_user), conn=db.DB):
    """Üst çubuktaki uyarılar: tüm kullanıcılara açık (yalnızca Güvenlik modülü olan kullanıcı hariç)."""
    items = alerts.summary(conn, user)   # yalnızca üretim / yazıcı modülü olanlar görür
    # Rozet uyarı türü sayısını gösterir; her türün içindeki kayıt sayısı listede ayrıca yazar
    return {'total': len(items), 'records': sum(a['count'] for a in items), 'alerts': items}


@router.get('/notifications')
def list_notifications(user=Depends(auth.current_user), conn=db.DB):
    """Üst çubuktaki bildirimler: yalnızca kullanıcıyı ilgilendirenler. Rozet toplam kayıt sayısıdır."""
    items = notifications.for_user(conn, user)
    return {'total': sum(n['count'] for n in items), 'items': items}


@router.get('/notifications/types')
def notification_types(user=Depends(auth.current_user)):
    """Ayarlar → Bildirimler: kullanıcının açıp kapatabileceği bildirim ve uyarı türleri."""
    return {'notifications': notifications.types_for(user), 'alerts': alerts.types_for(user)}


@router.post('/alerts/incidents/{iid}/ack')
def acknowledge_incident(iid: int, user=Depends(auth.current_user), conn=db.DB):
    """Kritik yazıcı olayını "Gördüm": yazıcı / üretim sorumluları ve yönetici."""
    if not {'printers', 'production', 'admin'} & set(user['modules']):
        raise HTTPException(403, 'Bu olayı kapatma yetkiniz yok')
    if not alerts.acknowledge(conn, iid, user['id']):
        raise HTTPException(404, 'Olay bulunamadı ya da zaten görüldü')
    db.audit(conn, user['id'], 'Kritik yazıcı uyarısını gördü', 'printer_incident', iid)
    return {'ok': True}


@router.get('/alerts/{key}')
def alert_detail(key: str, user=Depends(auth.current_user), conn=db.DB):
    d = alerts.detail(conn, key, user)
    if not d:
        raise HTTPException(404, 'Uyarı türü bulunamadı')
    return d


# ---------- Kullanıcı tercihleri (sunucuda; ör. kamera izleme düzeni)

class PrefIn(BaseModel):
    value: Optional[str] = None


@router.get('/me/prefs/{key}')
def get_pref(key: str, user=Depends(auth.current_user), conn=db.DB):
    r = conn.execute('SELECT value FROM user_prefs WHERE user_id = ? AND key = ?', (user['id'], key)).fetchone()
    return {'value': r[0] if r else None}


@router.put('/me/prefs/{key}')
def set_pref(key: str, body: PrefIn, user=Depends(auth.current_user), conn=db.DB):
    if len(key) > 60 or len(body.value or '') > 20000:
        raise HTTPException(400, 'Tercih çok uzun')
    conn.execute('INSERT INTO user_prefs (user_id, key, value) VALUES (?,?,?) ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value',
                 (user['id'], key, body.value))
    return {'ok': True}


# ---------- Kişisel pano (ana sayfa): kutucuklar ve verileri

@router.get('/dashboard/widgets')
def dashboard_widgets(user=Depends(auth.current_user)):
    from .. import dashboard
    return [{k: w[k] for k in ('key', 'title', 'desc', 'module', 'size', 'default', 'fixed', 'group')} for w in dashboard.available(user)]


@router.get('/dashboard/data')
def dashboard_data(keys: str = '', user=Depends(auth.current_user), conn=db.DB):
    from .. import dashboard
    return dashboard.data(conn, user, [k for k in keys.split(',') if k][:30])


# ---------- Arka plan bildirimleri (Web Push): bu cihaza abone ol / aboneliği kaldır
class PushSubIn(BaseModel):
    endpoint: str
    keys: dict = {}


@router.get('/push/key')
def push_key(user=Depends(auth.current_user)):
    if not push.available():
        raise HTTPException(503, 'Arka plan bildirimleri sunucuda kurulu değil')
    return {'key': push.public_key()}


@router.post('/push/subscribe')
def push_subscribe(body: PushSubIn, request: Request, user=Depends(auth.current_user), conn=db.DB):
    try:
        push.subscribe(conn, user['id'], body.model_dump(), request.headers.get('user-agent'))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {'ok': True}


@router.post('/push/unsubscribe')
def push_unsubscribe(body: PushSubIn, user=Depends(auth.current_user), conn=db.DB):
    push.unsubscribe(conn, user['id'], body.endpoint)
    return {'ok': True}


@router.post('/push/test')
def push_test(user=Depends(auth.current_user), conn=db.DB):
    n = conn.execute('SELECT COUNT(*) FROM push_subs WHERE user_id = ?', (user['id'],)).fetchone()[0]
    if not n:
        raise HTTPException(400, 'Bu hesapta arka plan bildirimine abone cihaz yok')
    push.send([user['id']], {'type': 'notif', 'title': 'Deneme bildirimi', 'body': 'Arka plan bildirimleri bu cihazda çalışıyor.', 'tag': 'test', 'url': '/app#/settings'})
    return {'ok': True, 'devices': n}
