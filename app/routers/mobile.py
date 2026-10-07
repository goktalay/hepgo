"""Mobil uygulama (Capacitor) uçları: native bildirim jetonu kaydı + konum sinyali.

Arayüz canlı web; bu uçlar yalnız native kabuktan (iOS/Android) çağrılır. static/js/native.js bunları kullanır.
Native bildirim gönderimi app/push_native.py; konumlar location_pings tablosunda.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, push_native

router = APIRouter(prefix='/api')


def _location_consent(conn, uid):
    r = conn.execute('SELECT prefs FROM users WHERE id = ?', (uid,)).fetchone()
    try:
        return ((json.loads(r[0]) if r and r[0] else {}).get('settings', {}) or {}).get('location_consent') or None
    except Exception:   # noqa: BLE001
        return None


class ConsentIn(BaseModel):
    granted: bool


@router.get('/location/consent')
def get_location_consent(user=Depends(auth.current_user), conn=db.DB):
    """Kişinin KVKK konum takibi açık rızası durumu (null=henüz sorulmadı)."""
    return {'consent': _location_consent(conn, user['id'])}


@router.post('/location/consent')
def set_location_consent(body: ConsentIn, user=Depends(auth.current_user), conn=db.DB):
    """KVKK açık rıza kaydı: mobil uygulamada konum takibine onay/ret. Denetlenebilir (audit)."""
    r = conn.execute('SELECT prefs FROM users WHERE id = ?', (user['id'],)).fetchone()
    try:
        prefs = json.loads(r[0]) if r and r[0] else {}
    except Exception:   # noqa: BLE001
        prefs = {}
    prefs.setdefault('settings', {})['location_consent'] = {'granted': bool(body.granted), 'at': db.now()}
    conn.execute('UPDATE users SET prefs = ? WHERE id = ?', (json.dumps(prefs), user['id']))
    db.audit(conn, user['id'], 'Konum takibi açık rızası', 'user', user['id'], 'onay' if body.granted else 'ret')
    conn.commit()
    return {'ok': True, 'granted': bool(body.granted)}


class NativeTokenIn(BaseModel):
    platform: str          # 'ios' | 'android'
    token: str


@router.post('/push/native-register')
def native_register(body: NativeTokenIn, user=Depends(auth.current_user), conn=db.DB):
    """Capacitor uygulamasının FCM/APNs cihaz jetonunu kaydeder (bildirimler bu cihaza da gider)."""
    ok = push_native.register(conn, user['id'], body.platform, (body.token or '').strip())
    if ok:
        conn.commit()
    return {'ok': ok}


class LocationIn(BaseModel):
    lat: float
    lng: float
    acc: Optional[float] = None
    at: Optional[str] = None
    platform: Optional[str] = None


@router.post('/location/ping')
def location_ping(body: LocationIn, user=Depends(auth.current_user), conn=db.DB):
    """Mobil uygulamadan (arkaplan) gelen konum. Kişi başına en son ~500 kayıt tutulur."""
    if not (-90 <= body.lat <= 90 and -180 <= body.lng <= 180):
        raise HTTPException(400, 'Geçersiz koordinat')
    c = _location_consent(conn, user['id'])   # KVKK: açık rıza yoksa konum SAKLANMAZ
    if not (c and c.get('granted')):
        return {'ok': False, 'consent': False}
    conn.execute('INSERT INTO location_pings (user_id, lat, lng, accuracy, at, platform, created_at) VALUES (?,?,?,?,?,?,?)',
                 (user['id'], body.lat, body.lng, body.acc, body.at, (body.platform or '')[:20] or None, db.now()))
    conn.execute('''DELETE FROM location_pings WHERE user_id = ? AND id NOT IN
                    (SELECT id FROM location_pings WHERE user_id = ? ORDER BY id DESC LIMIT 500)''', (user['id'], user['id']))
    conn.commit()
    return {'ok': True}


@router.get('/location/latest')
def location_latest(user=Depends(auth.current_user), conn=db.DB):
    """Her kullanıcının EN SON konumu (yönetici/güvenlik için canlı takip haritası). Yalnız yetkili roller."""
    allowed = user.get('master') or any(r in user.get('roles', []) for r in (auth.ADMIN, auth.SECURITY, auth.HR))
    if not allowed:
        raise HTTPException(403, 'Yetki yok')
    rows = db.rows(conn.execute('''SELECT lp.user_id, u.full_name, u.photo, u.last_seen, lp.lat, lp.lng, lp.accuracy, lp.at, lp.platform
        FROM location_pings lp
        JOIN (SELECT user_id, MAX(id) AS mid FROM location_pings GROUP BY user_id) m ON m.mid = lp.id
        JOIN users u ON u.id = lp.user_id
        ORDER BY lp.at DESC'''))
    return {'people': rows}


class DeviceInfoIn(BaseModel):
    device_id: Optional[str] = None
    platform: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    app_build: Optional[str] = None
    webview: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    screen: Optional[str] = None
    ua: Optional[str] = None


@router.post('/device-info')
def device_info(body: DeviceInfoIn, user=Depends(auth.current_user), conn=db.DB):
    """Giriş sonrası mobil uygulamadan gelen cihaz künyesi (yasal/teknik bilgiler). Kişi+cihaz bazında güncellenir."""
    def cut(v, n=120):
        return (v or '')[:n] or None
    now = db.now()
    did = cut(body.device_id, 80)
    row = conn.execute('SELECT id FROM mobile_devices WHERE user_id = ? AND device_id IS ?', (user['id'], did)).fetchone()
    vals = (body.platform and body.platform[:20], cut(body.model), cut(body.manufacturer), cut(body.os_version, 40),
            cut(body.app_version, 40), cut(body.app_build, 40), cut(body.webview, 80), cut(body.language, 20),
            cut(body.timezone, 60), cut(body.screen, 40), cut(body.ua, 400))
    if row:
        conn.execute('''UPDATE mobile_devices SET platform=?, model=?, manufacturer=?, os_version=?, app_version=?,
            app_build=?, webview=?, language=?, timezone=?, screen=?, ua=?, last_seen=? WHERE id=?''', (*vals, now, row[0]))
    else:
        conn.execute('''INSERT INTO mobile_devices (user_id, device_id, platform, model, manufacturer, os_version,
            app_version, app_build, webview, language, timezone, screen, ua, first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (user['id'], did, *vals, now, now))
    conn.commit()
    return {'ok': True}


@router.get('/devices')
def list_devices(user=Depends(auth.current_user), conn=db.DB):
    """Kayıtlı mobil cihaz künyeleri (yönetici görünümü). Yalnız master/admin/İK."""
    allowed = user.get('master') or any(r in user.get('roles', []) for r in (auth.ADMIN, auth.HR))
    if not allowed:
        raise HTTPException(403, 'Yetki yok')
    rows = db.rows(conn.execute('''SELECT md.*, u.full_name FROM mobile_devices md JOIN users u ON u.id = md.user_id
        ORDER BY md.last_seen DESC'''))
    return {'devices': rows}
