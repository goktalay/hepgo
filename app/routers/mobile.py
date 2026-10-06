"""Mobil uygulama (Capacitor) uçları: native bildirim jetonu kaydı + konum sinyali.

Arayüz canlı web; bu uçlar yalnız native kabuktan (iOS/Android) çağrılır. static/js/native.js bunları kullanır.
Native bildirim gönderimi app/push_native.py; konumlar location_pings tablosunda.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, push_native

router = APIRouter(prefix='/api')


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
    rows = db.rows(conn.execute('''SELECT lp.user_id, u.full_name, u.photo, lp.lat, lp.lng, lp.accuracy, lp.at, lp.platform
        FROM location_pings lp
        JOIN (SELECT user_id, MAX(id) AS mid FROM location_pings GROUP BY user_id) m ON m.mid = lp.id
        JOIN users u ON u.id = lp.user_id
        ORDER BY lp.at DESC'''))
    return {'people': rows}
