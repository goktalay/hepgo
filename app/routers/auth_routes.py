import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import alerts, auth, catalogs, config, db, notifications
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


LOCK_MINUTES = 15
MAX_USER_FAILS = 5    # aynı kullanıcı adına, son başarılı girişten sonra
MAX_IP_FAILS = 20     # aynı IP'den, tüm kullanıcı adlarına


def _locked(conn, username, ip):
    """Kaba kuvvet koruması: son LOCK_MINUTES dakikadaki başarısız denemeler sınırı aştıysa kalan dakika."""
    since = (datetime.now() - timedelta(minutes=LOCK_MINUTES)).isoformat(timespec='seconds')
    last_ok = conn.execute('SELECT MAX(id) FROM login_logs WHERE username = ? AND success = 1',
                           (username,)).fetchone()[0] or 0
    for where, args, limit in (('username = ? AND id > ?', (username, last_ok), MAX_USER_FAILS),
                               ('ip = ?', (ip,), MAX_IP_FAILS)):
        rows = conn.execute(f'SELECT at FROM login_logs WHERE success = 0 AND at > ? AND {where} '
                            'ORDER BY id DESC LIMIT ?', (since, *args, limit)).fetchall()
        if len(rows) >= limit:
            until = datetime.fromisoformat(rows[-1][0]) + timedelta(minutes=LOCK_MINUTES)
            return max(1, -(-int((until - datetime.now()).total_seconds()) // 60))
    return 0


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
        raise HTTPException(401, 'Kullanıcı adı veya şifre hatalı')
    token = auth.create_session(conn, user['id'])
    conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (db.now(), user['id']))
    db.audit(conn, user['id'], 'Sisteme giriş yaptı', 'session', None, _client_ip(request))
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite='lax',
                        max_age=config.SESSION_HOURS * 3600)
    return {'ok': True, 'device_token': _trust_device(conn, user['id'], request, body.device_token)}


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
    token = auth.create_session(conn, u['id'])
    conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (db.now(), u['id']))
    conn.execute('UPDATE trusted_devices SET last_used = ? WHERE id = ?', (db.now(), u['device_id']))
    db.audit(conn, u['id'], 'Sisteme PIN ile giriş yaptı', 'session', None, ip)
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite='lax', max_age=config.SESSION_HOURS * 3600)
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
    if not re.fullmatch(r'\d{4}', body.pin):
        raise HTTPException(400, 'PIN 4 rakam olmalı')
    if body.pin in ('0000', '1111', '1234', '4321', '2222', '3333', '4444', '5555', '6666', '7777', '8888', '9999', '0123'):
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
    out = {k: user[k] for k in ('id', 'username', 'full_name', 'photo', 'roles', 'modules')}
    out['prefs'] = json.loads(user['prefs']) if user['prefs'] else {}
    out['has_pin'] = bool(conn.execute('SELECT pin_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0])
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


@router.post('/auth/password')
def change_password(body: PasswordIn, user=Depends(auth.current_user), conn=db.DB):
    stored = conn.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0]
    if not auth.verify_password(body.current, stored):
        raise HTTPException(400, 'Mevcut şifre hatalı')
    if len(body.new) < 8:
        raise HTTPException(400, 'Yeni şifre en az 8 karakter olmalı')
    conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (auth.hash_password(body.new), user['id']))
    db.audit(conn, user['id'], 'Şifresini değiştirdi', 'user', user['id'])
    return {'ok': True}


@router.get('/meta')
def meta(request: Request):
    # remote: internetten (caymaz.app) bağlanıldı; video/log yükleme için yerel adres gösterilir
    return {'company': config.COMPANY_NAME, 'roles': auth.ROLES, 'remote': is_remote(request), 'local_url': config.LOCAL_URL}


@router.get('/plane')
def get_plane(user=Depends(auth.current_user)):
    """Geriye uyumluluk: varsayılan ürünün şeması. Yeni kod /api/products/{id}/plane kullanır."""
    return catalogs.plane_json(catalogs.DEFAULT_SCHEMA)


@router.get('/people')
def people(role: str = '', user=Depends(auth.current_user), conn=db.DB):
    """Seçim listeleri için rolüne göre aktif personel (ör. depocular, şoförler); rol verilmezse tüm personel."""
    if not role:
        return db.rows(conn.execute(
            'SELECT id, full_name, username, photo FROM users WHERE active = 1 AND deleted_at IS NULL ORDER BY full_name'))
    return db.rows(conn.execute(
        '''SELECT u.id, u.full_name, u.username, u.photo FROM users u
           JOIN user_roles r ON r.user_id = u.id
           WHERE r.role = ? AND u.active = 1 ORDER BY u.full_name''', (role,)))


@router.get('/alerts')
def list_alerts(user=Depends(auth.current_user), conn=db.DB):
    """Üst çubuktaki uyarılar: tüm kullanıcılara açık (yalnızca Güvenlik modülü olan kullanıcı hariç)."""
    if set(user['modules']) <= {'security', 'announcements'}:   # yalnızca güvenlik (duyurular herkese açık)
        return {'total': 0, 'records': 0, 'alerts': []}
    items = alerts.summary(conn)
    # Rozet uyarı türü sayısını gösterir; her türün içindeki kayıt sayısı listede ayrıca yazar
    return {'total': len(items), 'records': sum(a['count'] for a in items), 'alerts': items}


@router.get('/notifications')
def list_notifications(user=Depends(auth.current_user), conn=db.DB):
    """Üst çubuktaki bildirimler: yalnızca kullanıcıyı ilgilendirenler. Rozet toplam kayıt sayısıdır."""
    items = notifications.for_user(conn, user)
    return {'total': sum(n['count'] for n in items), 'items': items}


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
    d = alerts.detail(conn, key)
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
    return [{k: w[k] for k in ('key', 'title', 'desc', 'module', 'size', 'default')} for w in dashboard.available(user)]


@router.get('/dashboard/data')
def dashboard_data(keys: str = '', user=Depends(auth.current_user), conn=db.DB):
    from .. import dashboard
    return dashboard.data(conn, user, [k for k in keys.split(',') if k][:30])
