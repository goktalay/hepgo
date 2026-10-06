"""KVKK uçları: veri sahibi başvuruları (herkes kendi adına), rıza kaydı/raporu ve saklama ayarları (yönetici/MASTER)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, kvkk

router = APIRouter(prefix='/api/kvkk')
admin_only = auth.require_module('users')   # Kullanıcı Yönetimi yetkisi = yönetici


class RequestIn(BaseModel):
    kind: str                 # export | delete | object
    note: Optional[str] = None


class ConsentIn(BaseModel):
    kind: str                 # biometric | voice
    subject_type: str         # user | employee | person | family | visitor
    subject_id: int
    granted: bool = True
    note: Optional[str] = None


class HandleIn(BaseModel):
    resolution: Optional[str] = None


class SettingsIn(BaseModel):
    biometric_enforce: Optional[int] = None
    retention_sightings_days: Optional[int] = None
    retention_audio_days: Optional[int] = None
    retention_audit_days: Optional[int] = None


# ---- girişte zorunlu KVKK onayı ----
@router.get('/terms')
def terms(user=Depends(auth.current_user), conn=db.DB):
    """Girişte gösterilen KVKK aydınlatma/açık rıza metni + bu kullanıcının onay durumu."""
    return {'version': kvkk.terms_version(conn), 'pending': not kvkk.user_terms_ok(conn, user['id']), 'html': kvkk.TERMS_HTML}


@router.post('/accept-terms')
def accept_terms(user=Depends(auth.current_user), conn=db.DB):
    kvkk.accept_terms(conn, user['id'])
    conn.commit()
    return {'ok': True, 'version': kvkk.terms_version(conn)}


# ---- veri sahibi (her kullanıcı kendi adına) ----
@router.post('/request')
def create_request(body: RequestIn, user=Depends(auth.current_user), conn=db.DB):
    if body.kind not in kvkk.REQUEST_KINDS:
        raise HTTPException(400, 'Geçersiz başvuru türü')
    rid = kvkk.create_request(conn, user['id'], body.kind, body.note)
    conn.commit()
    return {'id': rid, 'ok': True}


@router.get('/my-requests')
def my_requests(user=Depends(auth.current_user), conn=db.DB):
    return db.rows(conn.execute('SELECT id, kind, note, status, created_at, handled_at, resolution FROM kvkk_requests '
                                'WHERE user_id = ? ORDER BY created_at DESC', (user['id'],)))


# ---- yönetici ----
@router.get('/requests')
def requests(status: str = '', user=Depends(admin_only), conn=db.DB):
    return kvkk.list_requests(conn, status or None)


@router.post('/requests/{rid}/handle')
def handle(rid: int, body: HandleIn, user=Depends(admin_only), conn=db.DB):
    if not conn.execute('SELECT 1 FROM kvkk_requests WHERE id = ?', (rid,)).fetchone():
        raise HTTPException(404, 'Başvuru bulunamadı')
    kvkk.handle_request(conn, rid, user['id'], body.resolution)
    conn.commit()
    return {'ok': True}


@router.get('/settings')
def get_settings(user=Depends(admin_only), conn=db.DB):
    return kvkk.settings(conn)


@router.put('/settings')
def put_settings(body: SettingsIn, user=Depends(admin_only), conn=db.DB):
    cur = kvkk.save_settings(conn, body.model_dump(exclude_none=True))
    db.audit(conn, user['id'], 'KVKK ayarlarını güncelledi', 'kvkk', None, str(cur))
    conn.commit()
    return cur


@router.get('/biometric-status')
def biometric_status(user=Depends(admin_only), conn=db.DB):
    return kvkk.biometric_status(conn)


@router.post('/consent')
def set_consent(body: ConsentIn, user=Depends(admin_only), conn=db.DB):
    if body.kind not in kvkk.CONSENT_KINDS:
        raise HTTPException(400, 'Geçersiz rıza türü')
    kvkk.set_consent(conn, body.kind, body.subject_type, body.subject_id, body.granted, user['id'], body.note)
    db.audit(conn, user['id'], 'KVKK açık rıza kaydı', 'kvkk_consent', body.subject_id,
             f'{body.kind}/{body.subject_type}={int(body.granted)}')
    conn.commit()
    return {'ok': True}


@router.get('/consent')
def get_consent(kind: str, subject_type: str, subject_id: int, user=Depends(admin_only), conn=db.DB):
    return {'granted': kvkk.has_consent(conn, kind, subject_type, subject_id)}
