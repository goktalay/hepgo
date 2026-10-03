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


GROUP_SELECT = '''SELECT g.id, g.person_id, g.user_id, g.samples, g.best_crop, g.first_seen, g.last_seen, g.assigned_at,
       u.full_name AS user_name, p.full_name AS person_name, pc.name AS person_company, c.name AS last_camera_name,
       (SELECT COUNT(*) FROM face_sightings s WHERE s.group_id = g.id) AS sightings,
       (SELECT group_concat(DISTINCT cc.name) FROM face_sightings s JOIN cameras cc ON cc.id = s.camera_id WHERE s.group_id = g.id) AS cameras
FROM face_groups g LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people p ON p.id = g.person_id
LEFT JOIN companies pc ON pc.id = p.company_id LEFT JOIN cameras c ON c.id = g.last_camera'''


@faces_router.get('/groups')
def groups(state: str = 'unknown', user=Depends(cam_user), conn=db.DB):
    where = 'g.person_id IS NULL AND g.user_id IS NULL' if state == 'unknown' else 'g.person_id IS NOT NULL OR g.user_id IS NOT NULL'
    return db.rows(conn.execute(GROUP_SELECT + f' WHERE {where} ORDER BY g.last_seen DESC LIMIT 500'))


@faces_router.get('/groups/{gid}')
def group(gid: int, user=Depends(cam_user), conn=db.DB):
    g = db.row(conn.execute(GROUP_SELECT + ' WHERE g.id = ?', (gid,)))
    if not g:
        raise HTTPException(404, 'Yüz grubu bulunamadı')
    g['items'] = db.rows(conn.execute(
        '''SELECT s.id, s.at, s.crop, s.frame, s.score, c.name AS camera_name FROM face_sightings s
           LEFT JOIN cameras c ON c.id = s.camera_id WHERE s.group_id = ? ORDER BY s.at DESC LIMIT 400''', (gid,)))
    return g


def _merge(conn, target, sources):
    """Kaynak grupları hedefe taşır: görülmeler, ağırlık merkezi (örnek sayısıyla), sayılar, ilk / son görülme."""
    rows = {r['id']: r for r in db.rows(conn.execute(
        f'SELECT * FROM face_groups WHERE id IN ({",".join("?" * (len(sources) + 1))})', (target, *sources)))}
    if target not in rows or any(s not in rows for s in sources):
        raise HTTPException(404, 'Yüz grubu bulunamadı')
    acc = np.zeros(128, np.float32)
    for r in rows.values():
        acc += np.frombuffer(r['centroid'], dtype=np.float32) * max(1, r['samples'])
    best = max(rows.values(), key=lambda r: r['best_score'])
    conn.execute(f'UPDATE face_sightings SET group_id = ? WHERE group_id IN ({",".join("?" * len(sources))})', (target, *sources))
    conn.execute('''UPDATE face_groups SET centroid = ?, samples = ?, best_crop = ?, best_score = ?, first_seen = ?, last_seen = ?
                    WHERE id = ?''',
                 (_norm(acc).astype(np.float32).tobytes(), sum(r['samples'] for r in rows.values()), best['best_crop'], best['best_score'],
                  min(r['first_seen'] for r in rows.values()), max(r['last_seen'] for r in rows.values()), target))
    conn.execute(f'DELETE FROM face_groups WHERE id IN ({",".join("?" * len(sources))})', sources)


@faces_router.post('/groups/{gid}/assign')
def assign(gid: int, body: AssignIn, user=Depends(cam_user), conn=db.DB):
    """Gruptaki tüm yüzler kişiye (kullanıcı ya da firma kişisi) atanır; o kişinin grubu varsa ikisi birleşir."""
    if bool(body.user_id) == bool(body.person_id):
        raise HTTPException(400, 'Bir kullanıcı ya da firma kişisi seçin')
    if body.user_id and not conn.execute('SELECT 1 FROM users WHERE id = ?', (body.user_id,)).fetchone():
        raise HTTPException(400, 'Kullanıcı bulunamadı')
    if body.person_id and not conn.execute('SELECT 1 FROM company_people WHERE id = ?', (body.person_id,)).fetchone():
        raise HTTPException(400, 'Kişi bulunamadı')
    if not conn.execute('SELECT 1 FROM face_groups WHERE id = ?', (gid,)).fetchone():
        raise HTTPException(404, 'Yüz grubu bulunamadı')
    col, val = ('user_id', body.user_id) if body.user_id else ('person_id', body.person_id)
    existing = conn.execute(f'SELECT id FROM face_groups WHERE {col} = ? AND id != ? ORDER BY samples DESC LIMIT 1', (val, gid)).fetchone()
    target = existing[0] if existing else gid
    if existing:
        _merge(conn, target, [gid])
    conn.execute('UPDATE face_groups SET person_id = ?, user_id = ?, assigned_by = ?, assigned_at = ? WHERE id = ?',
                 (body.person_id, body.user_id, user['id'], db.now(), target))
    db.audit(conn, user['id'], 'Kamera yüz grubunu kişiye atadı', 'face_group', target, f'{col}={val}')
    return {'id': target}


@faces_router.post('/groups/{gid}/unassign')
def unassign(gid: int, user=Depends(cam_user), conn=db.DB):
    conn.execute('UPDATE face_groups SET person_id = NULL, user_id = NULL, assigned_by = NULL, assigned_at = NULL WHERE id = ?', (gid,))
    return {'ok': True}


@faces_router.post('/merge')
def merge(body: MergeIn, user=Depends(cam_user), conn=db.DB):
    """Aynı kişiye ait olduğu görülen grupları birleştirir (ilk seçilen hedef)."""
    ids = list(dict.fromkeys(body.ids))
    if len(ids) < 2:
        raise HTTPException(400, 'En az iki grup seçin')
    _merge(conn, ids[0], ids[1:])
    db.audit(conn, user['id'], 'Kamera yüz gruplarını birleştirdi', 'face_group', ids[0], f'{len(ids)} grup')
    return {'id': ids[0]}


@faces_router.delete('/groups/{gid}')
def delete_group(gid: int, user=Depends(cam_user), conn=db.DB):
    """Yanlış tespit: grup, görülmeleri ve resimleri silinir."""
    files = [r[0] for r in conn.execute('SELECT crop FROM face_sightings WHERE group_id = ? UNION SELECT frame FROM face_sightings WHERE group_id = ? '
                                        'UNION SELECT best_crop FROM face_groups WHERE id = ?', (gid, gid, gid)) if r[0]]
    conn.execute('DELETE FROM face_groups WHERE id = ?', (gid,))
    for f in files:
        (config.UPLOAD_DIR / f).unlink(missing_ok=True)
    db.audit(conn, user['id'], 'Kamera yüz grubunu sildi', 'face_group', gid, f'{len(files)} resim')
    return {'ok': True}


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
    return db.rows(conn.execute(
        '''SELECT s.id, s.at, s.crop, s.frame, c.name AS camera_name, g.id AS group_id, u.full_name AS user_name,
                  p.full_name AS person_name, pc.name AS person_company
           FROM face_sightings s JOIN face_groups g ON g.id = s.group_id LEFT JOIN cameras c ON c.id = s.camera_id
           LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people p ON p.id = g.person_id LEFT JOIN companies pc ON pc.id = p.company_id
           WHERE g.user_id IS NOT NULL OR g.person_id IS NOT NULL ORDER BY s.at DESC LIMIT 200'''))


@faces_router.get('/events')
def events(date_from: str, date_to: str, kind: str = 'known', limit: int = 500,
           user=Depends(cam_user), conn=db.DB):
    """Belirli tarih aralığındaki görülmeler (Olay görüntüleme). kind='known' yalnız tanınanlar, 'all' hepsi.
    Yüz verisi/videolar fabrikada tutulur; bu liste yalnız seçilen aralık için çekilir."""
    where = "s.at >= ? AND s.at < ?"
    args = [date_from, date_to + '~']   # 'YYYY-MM-DD' → o günün sonuna kadar (ISO karşılaştırma)
    if kind == 'known':
        where += " AND (g.user_id IS NOT NULL OR g.person_id IS NOT NULL)"
    return {'events': db.rows(conn.execute(
        f'''SELECT s.id, s.at, s.crop, s.frame, s.clip, s.score, c.name AS camera_name, g.id AS group_id,
                   u.full_name AS user_name, p.full_name AS person_name, pc.name AS person_company
            FROM face_sightings s JOIN face_groups g ON g.id = s.group_id LEFT JOIN cameras c ON c.id = s.camera_id
            LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people p ON p.id = g.person_id
            LEFT JOIN companies pc ON pc.id = p.company_id
            WHERE {where} ORDER BY s.at DESC LIMIT ?''', (*args, min(limit, 2000))))}


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
    db.audit(conn, user['id'], 'Yüz tanıma eğitimi: fotoğraf eklendi', 'face_enroll', res['id'], subject_type)
    return {'ok': True, 'face': res}


@faces_router.delete('/enroll/{enroll_id}')
def enroll_delete(enroll_id: int, user=Depends(cam_user), conn=db.DB):
    from .. import faceenroll
    if faceenroll.delete(conn, enroll_id):
        conn.commit()
    return {'ok': True}
