"""Merkez › SSH Master: SSH Master (sshmasters.com) kullanıcı ve sürüm yönetimi.

SSH Master hesap servisi (central/sshmaster_server, systemd hepgo-sshmasters) aynı sunucuda 127.0.0.1:8095'te çalışır; Merkez onu
Veilox'taki gibi İÇ anahtarla (X-Central-Secret = CAYMAZ_CENTRAL_API_SECRET, servis tarafında VEILOX_CENTRAL_API_SECRET) çağırır.
Yalnız merkez modunda (CAYMAZ_FEDERATION_CENTRAL=1) ve 'sshmaster' modül yetkisiyle. Kullanıcıların şifreleri/kütüphaneleri Merkez'e
gelmez (sunucu da okuyamaz; uçtan uca şifreli)."""
import os

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from .. import auth, config, db

router = APIRouter(prefix='/api/central/sshm')
sshm_user = auth.require_module('sshmaster')
SSHM_URL = os.environ.get('CAYMAZ_SSHM_URL', 'http://127.0.0.1:8095').rstrip('/')


def _sm(method, path, json_body=None, files=None, data=None, timeout=30):
    if not config.FEDERATION_CENTRAL:
        raise HTTPException(404, 'Bulunamadı')
    if not config.CENTRAL_API_SECRET:
        raise HTTPException(503, 'Merkez iç anahtarı tanımlı değil')
    try:
        with httpx.Client(base_url=SSHM_URL, timeout=timeout) as c:
            r = c.request(method, path, json=json_body, files=files, data=data, headers={'X-Central-Secret': config.CENTRAL_API_SECRET})
    except httpx.HTTPError:
        raise HTTPException(503, 'SSH Master servisine ulaşılamıyor')
    if r.status_code >= 400:
        try:
            msg = r.json().get('message') or r.json().get('detail')
        except ValueError:
            msg = None
        raise HTTPException(r.status_code, msg or 'SSH Master servisi hatası')
    return r.json()


@router.get('/users')
def users(user=Depends(sshm_user)):
    return _sm('GET', '/api/sm/admin/users')


@router.get('/users/{uid}')
def user_detail(uid: int, user=Depends(sshm_user)):
    return _sm('GET', f'/api/sm/admin/users/{uid}')


@router.put('/users/{uid}')
async def user_update(uid: int, request: Request, user=Depends(sshm_user), conn=db.DB):
    b = await request.json()
    body = {k: b[k] for k in ('status', 'name', 'note') if k in b}
    r = _sm('PUT', f'/api/sm/admin/users/{uid}', body)
    db.audit(conn, user['id'], 'Merkez: SSH Master kullanıcısını düzenledi', 'sshm_user', uid, ', '.join(f'{k}={v}' for k, v in body.items())[:300])
    return r


@router.delete('/users/{uid}')
def user_delete(uid: int, user=Depends(sshm_user), conn=db.DB):
    r = _sm('DELETE', f'/api/sm/admin/users/{uid}')
    db.audit(conn, user['id'], 'Merkez: SSH Master kullanıcısını sildi', 'sshm_user', uid)
    return r


@router.post('/users/{uid}/reset-mail')
def user_reset_mail(uid: int, user=Depends(sshm_user), conn=db.DB):
    r = _sm('POST', f'/api/sm/admin/users/{uid}/reset-mail')
    db.audit(conn, user['id'], 'Merkez: SSH Master e-postası gönderdi', 'sshm_user', uid, r.get('sent'))
    return r


@router.get('/releases')
def releases(user=Depends(sshm_user)):
    return _sm('GET', '/api/sm/admin/releases')


@router.post('/releases')
def release_upload(version: str = Form(...), notes: str = Form(''), setup: UploadFile = File(...), portable: UploadFile = File(None),
                   user=Depends(sshm_user), conn=db.DB):
    files = {'setup': (setup.filename or 'setup.exe', setup.file, 'application/octet-stream')}
    if portable is not None and portable.filename:
        files['portable'] = (portable.filename, portable.file, 'application/octet-stream')
    r = _sm('POST', '/api/sm/releases', files=files, data={'version': version, 'notes': notes}, timeout=600)
    db.audit(conn, user['id'], 'Merkez: SSH Master sürümü yükledi', 'sshm_release', r.get('version'), r.get('sha256'))
    return r


@router.delete('/releases/{rid}')
def release_delete(rid: int, user=Depends(sshm_user), conn=db.DB):
    r = _sm('DELETE', f'/api/sm/admin/releases/{rid}')
    db.audit(conn, user['id'], 'Merkez: SSH Master sürümünü sildi', 'sshm_release', rid)
    return r
