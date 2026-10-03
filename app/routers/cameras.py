"""Güvenlik → Kameralar (ONVIF) ve Tanımlanamayan Kişiler (kamera yüz grupları). Görüntüyü ve yüzleri kamera servisi
(app/camera_service.py, ayrı süreç) üretir; bu router listeler, ekler, izleme karesini verir ve yüz gruplarını kişiye atar."""
import hashlib
import time
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, cameras as camlib, config, db
from ..document_media import _norm
from ..files import FILE_GUARDS

router = APIRouter(prefix='/api/cameras')
faces_router = APIRouter(prefix='/api/faces')
cam_user = auth.require_sysadmin()   # Kameralar modülü yalnızca sistem yöneticisine açık (Sistem Yönetimi)
LIVE_DIR = config.DATA_DIR / 'cameras' / 'live'

_cam_access = lambda user, name: auth.ADMIN in user['roles'] or bool(user.get('master'))
FILE_GUARDS['camfaces'] = _cam_access
FILE_GUARDS['faces_enroll'] = _cam_access   # yüz tanıma eğitimi kırpıkları
FILE_GUARDS['camclips'] = _cam_access        # görülme anı video klipleri (lokal)


class CameraIn(BaseModel):
    name: str
    ip: Optional[str] = None
    port: Optional[int] = None
    xaddr: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None       # boş bırakılırsa (düzenlemede) değişmez
    stream_url: Optional[str] = None     # boşsa ONVIF'ten alınır
    location: Optional[str] = None
    faces: bool = True
    active: bool = True


class DiscoveredIn(BaseModel):
    items: list[dict]
    username: Optional[str] = None
    password: Optional[str] = None


def _public(r):
    r = dict(r)
    r.pop('password_enc', None)
    r['has_password'] = bool(dict(r).get('username'))
    r['stream_url'] = camlib.mask(r.get('stream_url'))
    live = LIVE_DIR / f'{r["id"]}.jpg'
    r['live_age'] = round(time.time() - live.stat().st_mtime, 1) if live.exists() else None
    return r


def _get(conn, cid):
    r = db.row(conn.execute('SELECT * FROM cameras WHERE id = ?', (cid,)))
    if not r:
        raise HTTPException(404, 'Kamera bulunamadı')
    return r


@router.get('')
def list_cameras(user=Depends(cam_user), conn=db.DB):
    from .. import facebridge
    if facebridge.remote():   # dağıtık: kamera listesi + canlı durum fabrikadan (ID'ler fabrikayla tutarlı)
        return _face(conn, 'cameras_list')
    return [_public(r) for r in db.rows(conn.execute('SELECT * FROM cameras ORDER BY name COLLATE NOCASE, id'))]


def _resolve(body, old=None):
    """ONVIF'ten akış adresi ve cihaz bilgisi (akış adresi elle verilmediyse)."""
    url = (body.stream_url or '').strip().lower()
    if url and '***' not in url and not url.startswith(('rtsp://', 'rtsps://', 'http://', 'https://')):
        raise HTTPException(400, 'Akış adresi rtsp:// ya da http(s):// ile başlamalı')   # sunucudaki dosyalar okunamasın
    password = body.password if body.password else (camlib.decrypt(old['password_enc']) if old else '')
    xaddr = (body.xaddr or '').strip() or (f'http://{body.ip.strip()}{":" + str(body.port) if body.port else ""}/onvif/device_service'
                                          if body.ip else None)
    info = {'manufacturer': old and old['manufacturer'], 'model': old and old['model'], 'stream_url': (body.stream_url or '').strip() or None}
    if not info['stream_url'] or (old and body.stream_url and '***' in body.stream_url):
        if not xaddr:
            raise HTTPException(400, 'IP adresi ya da akış adresi (rtsp://…) girin')
        try:
            info = camlib.probe_camera(xaddr, (body.username or '').strip(), password)
        except PermissionError as e:
            raise HTTPException(400, str(e)) from None
        except Exception as e:
            raise HTTPException(400, f'Kameraya ONVIF ile ulaşılamadı: {e}') from None
    return xaddr, password, info


@router.post('')
def add_camera(body: CameraIn, user=Depends(cam_user), conn=db.DB):
    if not body.name.strip():
        raise HTTPException(400, 'Kamera adı zorunlu')
    xaddr, password, info = _resolve(body)
    cur = conn.execute('''INSERT INTO cameras (name, ip, port, username, password_enc, xaddr, stream_url, manufacturer, model, location,
                          faces, active, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (body.name.strip(), (body.ip or '').strip() or None, body.port, (body.username or '').strip() or None,
                        camlib.encrypt(password), xaddr, info['stream_url'], info['manufacturer'], info['model'],
                        (body.location or '').strip() or None, int(body.faces), int(body.active), db.now()))
    db.audit(conn, user['id'], 'Kamera ekledi', 'camera', cur.lastrowid, body.name.strip())
    return {'id': cur.lastrowid}


@router.put('/{cid}')
def update_camera(cid: int, body: CameraIn, user=Depends(cam_user), conn=db.DB):
    old = _get(conn, cid)
    if not body.name.strip():
        raise HTTPException(400, 'Kamera adı zorunlu')
    same_source = (body.stream_url or '') == camlib.mask(old['stream_url']) and not body.password \
        and (body.ip or None) == old['ip'] and (body.username or None) == old['username']
    if same_source:
        xaddr, password, info = old['xaddr'], camlib.decrypt(old['password_enc']), dict(old)
    else:
        if body.stream_url and '***' in body.stream_url:   # maskeli adres: ONVIF'ten yeniden alınır
            body.stream_url = None
        xaddr, password, info = _resolve(body, old)
    conn.execute('''UPDATE cameras SET name = ?, ip = ?, port = ?, username = ?, password_enc = ?, xaddr = ?, stream_url = ?,
                    manufacturer = ?, model = ?, location = ?, faces = ?, active = ? WHERE id = ?''',
                 (body.name.strip(), (body.ip or '').strip() or None, body.port, (body.username or '').strip() or None,
                  camlib.encrypt(password), xaddr, info['stream_url'], info['manufacturer'], info['model'],
                  (body.location or '').strip() or None, int(body.faces), int(body.active), cid))
    db.audit(conn, user['id'], 'Kamera düzenledi', 'camera', cid, body.name.strip())
    return {'ok': True}


@router.delete('/{cid}')
def delete_camera(cid: int, user=Depends(cam_user), conn=db.DB):
    c = _get(conn, cid)
    conn.execute('DELETE FROM cameras WHERE id = ?', (cid,))
    (LIVE_DIR / f'{cid}.jpg').unlink(missing_ok=True)
    db.audit(conn, user['id'], 'Kamera sildi', 'camera', cid, c['name'])
    return {'ok': True}


@router.post('/discover')
async def discover(user=Depends(cam_user)):
    """Ağdaki ONVIF kameralar (WS-Discovery); kayıtlı olanlar işaretlenir."""
    found = await run_in_threadpool(camlib.discover)
    with db.connect() as conn:
        known = {r[0] for r in conn.execute('SELECT ip FROM cameras WHERE ip IS NOT NULL')}
    for f in found:
        f['added'] = f['ip'] in known
    return found


@router.post('/add-discovered')
async def add_discovered(body: DiscoveredIn, user=Depends(cam_user)):
    """Bulunan kameraları ortak kullanıcı adı / şifreyle ekler; her biri için sonuç (eklendi / hata)."""
    def work():
        out = []
        with db.connect() as conn:
            known = {r[0] for r in conn.execute('SELECT ip FROM cameras WHERE ip IS NOT NULL')}
            n = conn.execute('SELECT COUNT(*) FROM cameras').fetchone()[0]
        for it in body.items:
            ip = it.get('ip')
            if not ip or ip in known:
                out.append({'ip': ip, 'ok': False, 'error': 'Zaten kayıtlı'})
                continue
            try:
                info = camlib.probe_camera(it.get('xaddr') or f'http://{ip}/onvif/device_service', body.username or '', body.password or '')
            except Exception as e:
                out.append({'ip': ip, 'ok': False, 'error': str(e)})
                continue
            n += 1
            name = it.get('name') or info.get('model') or f'Kamera {n}'
            with db.connect() as conn:
                cur = conn.execute('''INSERT INTO cameras (name, ip, username, password_enc, xaddr, stream_url, manufacturer, model,
                                      faces, active, auto_added, created_at) VALUES (?,?,?,?,?,?,?,?,1,1,1,?)''',
                                   (f'{name} ({ip})', ip, body.username or None, camlib.encrypt(body.password or ''),
                                    it.get('xaddr'), info['stream_url'], info['manufacturer'], info['model'], db.now()))
                db.audit(conn, user['id'], 'Kamera otomatik ekledi', 'camera', cur.lastrowid, ip)
            out.append({'ip': ip, 'ok': True})
        return out
    return await run_in_threadpool(work)


@router.get('/{cid}/frame')
def frame(cid: int, request: Request, user=Depends(cam_user)):
    """İzleme ekranı: kameranın son karesi (kamera servisi yazar). Değişmediyse 304."""
    path = LIVE_DIR / f'{cid}.jpg'
    if not path.exists():
        # Dağıtık kurulum: canlı kare fabrikada; talep üzerine ajandan getirilir
        if config.AGENT_MODE == 'remote':
            from .. import facebridge
            try:
                data, ctype = facebridge.media(f'cameras/live/{cid}.jpg')
            except HTTPException:
                raise HTTPException(404, 'Görüntü yok')
            return Response(data, media_type=ctype, headers={'Cache-Control': 'no-store'})
        raise HTTPException(404, 'Görüntü yok')
    st = path.stat()
    etag = hashlib.md5(f'{st.st_mtime_ns}-{st.st_size}'.encode()).hexdigest()
    headers = {'ETag': etag, 'Cache-Control': 'no-store', 'X-Frame-Age': f'{time.time() - st.st_mtime:.1f}'}
    if request.headers.get('if-none-match') == etag:
        return Response(status_code=304, headers=headers)
    return Response(path.read_bytes(), media_type='image/jpeg', headers=headers)


# ---------- Tanımlanamayan kişiler (kamera yüz grupları)

class AssignIn(BaseModel):
    user_id: Optional[int] = None
    person_id: Optional[int] = None


class MergeIn(BaseModel):
    ids: list[int]


# Yüz grupları / görülmeler: dağıtık kurulumda (AGENT_MODE=remote) fabrika yerel DB'sinden (facebridge) çekilir,
# isimler bulut DB'sinde çözülür; yerelde doğrudan facecore. İşlem fonksiyonları app/facecore.py'de.
def _face(conn, method, **args):
    from .. import facebridge, facecore
    if facebridge.remote():
        return facebridge.rpc(method, **args)
    try:
        r = facecore.rpc(conn, method, args)
        conn.commit()
        return r
    except facecore.NotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _resolve_names(conn, rows):
    from .. import facebridge
    if facebridge.remote():
        facebridge.resolve_names(conn, rows)
    return rows


@faces_router.get('/groups')
def groups(state: str = 'unknown', user=Depends(cam_user), conn=db.DB):
    return _resolve_names(conn, _face(conn, 'groups', state=state))


@faces_router.get('/groups/{gid}')
def group(gid: int, user=Depends(cam_user), conn=db.DB):
    return _resolve_names(conn, _face(conn, 'group', gid=gid))


@faces_router.post('/groups/{gid}/assign')
def assign(gid: int, body: AssignIn, user=Depends(cam_user), conn=db.DB):
    """Gruptaki tüm yüzler kişiye (kullanıcı ya da firma kişisi) atanır; o kişinin grubu varsa ikisi birleşir.
    Kullanıcı/kişi varlığı BULUT veritabanında doğrulanır; grup fabrikada olabilir."""
    if bool(body.user_id) == bool(body.person_id):
        raise HTTPException(400, 'Bir kullanıcı ya da firma kişisi seçin')
    if body.user_id and not conn.execute('SELECT 1 FROM users WHERE id = ?', (body.user_id,)).fetchone():
        raise HTTPException(400, 'Kullanıcı bulunamadı')
    if body.person_id and not conn.execute('SELECT 1 FROM company_people WHERE id = ?', (body.person_id,)).fetchone():
        raise HTTPException(400, 'Kişi bulunamadı')
    r = _face(conn, 'assign', gid=gid, user_id=body.user_id, person_id=body.person_id, by=user['id'], validate=False)
    db.audit(conn, user['id'], 'Kamera yüz grubunu kişiye atadı', 'face_group', r.get('id', gid),
             f"{'user' if body.user_id else 'person'}={body.user_id or body.person_id}")
    return r


@faces_router.post('/groups/{gid}/unassign')
def unassign(gid: int, user=Depends(cam_user), conn=db.DB):
    return _face(conn, 'unassign', gid=gid)


@faces_router.post('/merge')
def merge(body: MergeIn, user=Depends(cam_user), conn=db.DB):
    """Aynı kişiye ait olduğu görülen grupları birleştirir (ilk seçilen hedef)."""
    r = _face(conn, 'merge', ids=list(dict.fromkeys(body.ids)))
    db.audit(conn, user['id'], 'Kamera yüz gruplarını birleştirdi', 'face_group', r['id'], f'{len(body.ids)} grup')
    return r


@faces_router.delete('/groups/{gid}')
def delete_group(gid: int, user=Depends(cam_user), conn=db.DB):
    """Yanlış tespit: grup, görülmeleri ve resimleri silinir."""
    r = _face(conn, 'delete_group', gid=gid)
    db.audit(conn, user['id'], 'Kamera yüz grubunu sildi', 'face_group', gid, f"{r.get('files', 0)} resim")
    return r


@faces_router.get('/people')
def people(user=Depends(cam_user), conn=db.DB):
    """Atama seçimi: kullanıcılar ve firma kişileri (Firma modülü olmadan)."""
    return {
        'users': db.rows(conn.execute('SELECT id, full_name, photo FROM users WHERE active = 1 AND deleted_at IS NULL ORDER BY full_name')),
        'people': db.rows(conn.execute('''SELECT p.id, p.full_name, p.title, c.name AS company_name FROM company_people p
                                          JOIN companies c ON c.id = p.company_id ORDER BY p.full_name''')),
    }


@faces_router.get('/recent')
def recent(user=Depends(cam_user), conn=db.DB):
    """Son tanınan kişi görülmeleri (kişiye atanmış gruplar)."""
    return _resolve_names(conn, _face(conn, 'recent'))


@faces_router.get('/events')
def events(date_from: str, date_to: str, kind: str = 'known', limit: int = 500,
           user=Depends(cam_user), conn=db.DB):
    """Belirli tarih aralığındaki görülmeler (Olay görüntüleme). kind='known' yalnız tanınanlar, 'all' hepsi.
    Yüz verisi/videolar fabrikada tutulur; bu liste yalnız seçilen aralık için çekilir."""
    r = _face(conn, 'events', date_from=date_from, date_to=date_to, kind=kind, limit=limit)
    _resolve_names(conn, r["events"])
    return r


@faces_router.get('/enroll')
def enroll_list(subject_type: str, user_id: Optional[int] = None, person_id: Optional[int] = None,
                user=Depends(cam_user), conn=db.DB):
    """Bir kişinin eğitim fotoğrafları (yüz kırpıkları)."""
    from .. import faceenroll
    try:
        return {'faces': faceenroll.list_for(conn, subject_type, user_id, person_id)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@faces_router.post('/enroll')
async def enroll_add(file: UploadFile = File(...), subject_type: str = Form(...),
                     user_id: Optional[int] = Form(None), person_id: Optional[int] = Form(None),
                     user=Depends(cam_user), conn=db.DB):
    """Yüz tanıma eğitimi: bir fotoğraf yükle → kişinin yüzü eğitilsin."""
    from .. import faceenroll
    import os
    import tempfile
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, 'Fotoğraf çok büyük (en çok 15 MB)')
    fd, tmp = tempfile.mkstemp(suffix='.jpg', dir=str(config.UPLOAD_DIR))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        ok, res = await run_in_threadpool(faceenroll.enroll, conn, subject_type, user_id, person_id, tmp, user['id'])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    finally:
        os.unlink(tmp)
    if not ok:
        raise HTTPException(422, res)
    conn.commit()
    _push_enroll(conn)   # eğitim izlerini fabrika yüz-tanıma servisine aktar
    db.audit(conn, user['id'], 'Yüz tanıma eğitimi: fotoğraf eklendi', 'face_enroll', res['id'], subject_type)
    return {'ok': True, 'face': res}


@faces_router.delete('/enroll/{enroll_id}')
def enroll_delete(enroll_id: int, user=Depends(cam_user), conn=db.DB):
    from .. import faceenroll
    if faceenroll.delete(conn, enroll_id):
        conn.commit()
        _push_enroll(conn)
    return {'ok': True}


def _push_enroll(conn):
    """Eğitim izlerini (ve güncel ayarı) fabrika yüz-tanıma servisine aktarır (en iyi çaba)."""
    try:
        from .. import facebridge
        facebridge.push(conn)
    except Exception:   # noqa: BLE001
        pass
