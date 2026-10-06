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
cam_user = auth.require_module('cameras')   # Kameralar modülü: Sistem Yöneticisi + "Kamera Yetkilisi" rolü
LIVE_DIR = config.DATA_DIR / 'cameras' / 'live'

# Kamera yüz medyası: Kameralar modülü (admin/kamera yetkilisi) + İK (aile üyelerinin tanınan yüzleri personel detayında)
_cam_access = lambda user, name: bool({'cameras', 'hr'} & set(user['modules'])) or bool(user.get('master'))
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


_last_watch: dict[int, float] = {}   # cid → son "izleniyor" sinyali zamanı (fabrikaya throttle'lı gönderilir)
WATCH_PING = 6                       # sn: izleme sinyalini en çok bu sıklıkta gönder


def _ping_watch(cid: int):
    """Canlı izleme: fabrikaya 'bu kamerayı izliyorum' de ki yüz tanıma kapalı olsa bile canlı yakalasın."""
    from .. import facebridge
    now = time.time()
    if now - _last_watch.get(cid, 0) < WATCH_PING:
        return
    _last_watch[cid] = now
    try:
        facebridge.rpc('watch', _timeout=8, cid=cid, ttl=25)
    except Exception:
        _last_watch[cid] = 0   # başarısızsa bir sonraki karede tekrar dene


@router.get('/{cid}/frame')
def frame(cid: int, request: Request, user=Depends(cam_user)):
    """İzleme ekranı: kameranın son karesi (kamera servisi yazar). Değişmediyse 304."""
    path = LIVE_DIR / f'{cid}.jpg'
    if not path.exists():
        # Dağıtık kurulum: canlı kare fabrikada; talep üzerine ajandan getirilir (+ izleme sinyali)
        if config.AGENT_MODE == 'remote':
            from .. import facebridge
            _ping_watch(cid)
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


class NameIn(BaseModel):
    name: str


_CHAN_RE = None


def _chan_of(stream_url):
    """RTSP adresinden NVR kanal numarası (…/unicast/c28/…) → 28; NVR dışıysa None."""
    import re
    m = re.search(r'/unicast/c(\d+)/', stream_url or '')
    return int(m.group(1)) if m else None


@router.put('/{cid}/name')
def rename_camera(cid: int, body: NameIn, user=Depends(cam_user), conn=db.DB):
    """Kamerayı yeniden adlandır. NVR kanalıysa ad kanal ayarına yazılır (kalıcı; sync ezmez) ve fabrikaya aktarılır;
    NVR dışıysa doğrudan kamera tablosunda güncellenir. Dağıtık kurulumda da ad fabrikadaki listeye yansır."""
    from .. import facebridge, nvr
    name = (body.name or '').strip()[:60]
    if not name:
        raise HTTPException(400, 'Ad boş olamaz')
    ch = None
    if facebridge.remote():
        for c in _face(conn, 'cameras_list'):
            if c['id'] == cid:
                ch = _chan_of(c.get('stream_url'))
                break
    else:
        ch = _chan_of(_get(conn, cid)['stream_url'])
    if ch:
        import json
        store = nvr._ch_store(conn)
        rec = store.get(str(ch), {})
        rec['name'] = name
        store[str(ch)] = rec
        conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (nvr.CH_KEY, json.dumps(store)))
        conn.commit()
        from .system import _push_face_config
        _push_face_config(conn)   # fabrikaya aktar → sync_cameras adı kamera tablosuna yazar
    else:
        conn.execute('UPDATE cameras SET name = ? WHERE id = ?', (name, cid))
        conn.commit()
    return {'ok': True, 'name': name}


@router.get('/overlays')
def overlays(ids: str = '', user=Depends(cam_user), conn=db.DB):
    """Canlı izleme çerçeveleri: verilen kamera id'leri için yüz kutuları + kimlik (bilinen=ad, bilinmeyen=boş)."""
    id_list = [int(x) for x in ids.split(',') if x.strip().isdigit()][:40]
    if not id_list:
        return {'overlays': {}}
    r = _face(conn, 'overlays', ids=id_list)
    ov = r.get('overlays', {})
    uids = {b['id'] for bs in ov.values() for b in bs if b.get('kind') == 'user' and b.get('id')}
    pids = {b['id'] for bs in ov.values() for b in bs if b.get('kind') == 'person' and b.get('id')}
    fids = {b['id'] for bs in ov.values() for b in bs if b.get('kind') == 'family' and b.get('id')}
    vids = {b['id'] for bs in ov.values() for b in bs if b.get('kind') == 'visitor' and b.get('id')}
    users = {x[0]: x[1] for x in conn.execute(
        f'SELECT id, full_name FROM users WHERE id IN ({",".join("?" * len(uids))})', tuple(uids))} if uids else {}
    people = {x[0]: x[1] for x in conn.execute(
        f'SELECT id, full_name FROM company_people WHERE id IN ({",".join("?" * len(pids))})', tuple(pids))} if pids else {}
    family = {x[0]: x[1] for x in conn.execute(
        f'SELECT id, full_name FROM family_members WHERE id IN ({",".join("?" * len(fids))})', tuple(fids))} if fids else {}
    visitors = {x[0]: x[1] for x in conn.execute(
        f'SELECT id, full_name FROM visitors WHERE id IN ({",".join("?" * len(vids))})', tuple(vids))} if vids else {}
    for bs in ov.values():
        for b in bs:
            b['known'] = bool(b.get('kind'))
            b['label'] = (users.get(b['id']) if b.get('kind') == 'user' else people.get(b['id']) if b.get('kind') == 'person'
                          else family.get(b['id']) if b.get('kind') == 'family'
                          else visitors.get(b['id']) if b.get('kind') == 'visitor' else None)
    return {'overlays': ov}


# ---------- Tanımlanamayan kişiler (kamera yüz grupları)

class AssignIn(BaseModel):
    user_id: Optional[int] = None
    person_id: Optional[int] = None
    family_id: Optional[int] = None
    visitor_id: Optional[int] = None


class MergeIn(BaseModel):
    ids: list[int]


class SightingIdsIn(BaseModel):
    ids: list[int]


class SightingAssignIn(BaseModel):
    ids: list[int]
    user_id: Optional[int] = None
    person_id: Optional[int] = None
    family_id: Optional[int] = None
    visitor_id: Optional[int] = None


class VisitorIn(BaseModel):
    full_name: str
    company: Optional[str] = None
    phone: Optional[str] = None
    note: Optional[str] = None


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


class FrameIn(BaseModel):
    jpg: str                            # base64 JPEG (data: öneki olmadan)
    min_face: Optional[int] = None      # bu pikselden küçük yüzleri atla (öntanımlı 44)
    thr: Optional[float] = None         # eşleştirme kosinüs eşiği (öntanımlı KNOWN_PERSON=0.42)


@faces_router.post('/recognize-frame')
def recognize_frame(body: FrameIn, user=Depends(cam_user), conn=db.DB):
    """CANLI TEST: tarayıcı kamerasından gelen tek kareyi fabrika yüz ajanında EĞİTİLMİŞ izlerle eşleştirir.
    Dönüş {w,h,faces:[{box:[x,y,w,h], score, *_id, *_name}]}; isimler bulut DB'sinden (resolve_names) çözülür.
    Eşleşmeyen yüzler de çerçeveyle döner (score None) → arayüz 'Tanımsız Kişi' gösterir."""
    res = _face(conn, 'recognize_frame', jpg=body.jpg, min_face=body.min_face, thr=body.thr)
    if isinstance(res, dict):
        _resolve_names(conn, res.get('faces') or [])
    return res


@faces_router.get('/isg-alarms')
def isg_alarms(limit: int = 200, user=Depends(cam_user), conn=db.DB):
    """İSG/KKD alarm listesi (Görüntü İşleme). Zorunlu KKD eksik yakalanınca üretilir; isimler bulutta çözülür."""
    return _resolve_names(conn, _face(conn, 'isg_alarms', limit=limit))


@faces_router.post('/isg-alarms/{aid}/ack')
def isg_ack(aid: int, user=Depends(cam_user), conn=db.DB):
    """Alarmı 'görüldü' işaretler."""
    return _face(conn, 'isg_ack', aid=aid, by=user['id'])


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
    if sum(bool(x) for x in (body.user_id, body.person_id, body.family_id, body.visitor_id)) != 1:
        raise HTTPException(400, 'Bir kullanıcı, firma kişisi, aile üyesi ya da ziyaretçi seçin')
    if body.user_id and not conn.execute('SELECT 1 FROM users WHERE id = ?', (body.user_id,)).fetchone():
        raise HTTPException(400, 'Kullanıcı bulunamadı')
    if body.person_id and not conn.execute('SELECT 1 FROM company_people WHERE id = ?', (body.person_id,)).fetchone():
        raise HTTPException(400, 'Kişi bulunamadı')
    if body.family_id and not conn.execute('SELECT 1 FROM family_members WHERE id = ?', (body.family_id,)).fetchone():
        raise HTTPException(400, 'Aile üyesi bulunamadı')
    if body.visitor_id and not conn.execute('SELECT 1 FROM visitors WHERE id = ?', (body.visitor_id,)).fetchone():
        raise HTTPException(400, 'Ziyaretçi bulunamadı')
    r = _face(conn, 'assign', gid=gid, user_id=body.user_id, person_id=body.person_id, family_id=body.family_id,
              visitor_id=body.visitor_id, by=user['id'], validate=False)
    kind = 'user' if body.user_id else 'person' if body.person_id else 'family' if body.family_id else 'visitor'
    db.audit(conn, user['id'], 'Kamera yüz grubunu kişiye atadı', 'face_group', r.get('id', gid),
             f"{kind}={body.user_id or body.person_id or body.family_id or body.visitor_id}")
    try:   # atanan yüzleri eğitime de ekle (en iyi çaba — atama yine başarılı sayılır)
        n = _enroll_assigned(conn, r, kind, body.user_id, body.person_id, body.family_id, user['id'], body.visitor_id)
        if n:
            db.audit(conn, user['id'], f'Atanan yüzler eğitime eklendi: {n}', 'face_enroll', r.get('id', gid), kind)
    except Exception:   # noqa: BLE001
        pass
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


@faces_router.delete('/sightings/{sid}')
def delete_sighting(sid: int, user=Depends(cam_user), conn=db.DB):
    """Bir gruptan tek görülme (resim) çıkarır. Grup/kişi atanmış olabilir; kalanlar kalır."""
    r = _face(conn, 'delete_sighting', sid=sid)
    db.audit(conn, user['id'], 'Kamera yüz görülmesini kaldırdı', 'face_sighting', sid, None)
    return r


@faces_router.post('/sightings/delete')
def delete_sightings(body: SightingIdsIn, user=Depends(cam_user), conn=db.DB):
    """Birden çok görülmeyi (resmi) toplu kaldırır. Kalanlar kalır; boşalan grup silinir."""
    r = _face(conn, 'delete_sightings', ids=list(dict.fromkeys(body.ids)))
    db.audit(conn, user['id'], 'Kamera yüz görülmelerini kaldırdı', 'face_sighting', None, f"{r.get('deleted', 0)} görülme")
    return r


@faces_router.post('/sightings/assign')
def assign_sightings(body: SightingAssignIn, user=Depends(cam_user), conn=db.DB):
    """Seçili görülmeleri mevcut gruptan çıkarıp yalnız onları bir kişiye (kullanıcı / firma kişisi / aile üyesi) atar.
    Kişinin grubu varsa birleşir. Varlık BULUT veritabanında doğrulanır; görülme fabrikada olabilir."""
    if sum(bool(x) for x in (body.user_id, body.person_id, body.family_id, body.visitor_id)) != 1:
        raise HTTPException(400, 'Bir kullanıcı, firma kişisi, aile üyesi ya da ziyaretçi seçin')
    if body.user_id and not conn.execute('SELECT 1 FROM users WHERE id = ?', (body.user_id,)).fetchone():
        raise HTTPException(400, 'Kullanıcı bulunamadı')
    if body.person_id and not conn.execute('SELECT 1 FROM company_people WHERE id = ?', (body.person_id,)).fetchone():
        raise HTTPException(400, 'Kişi bulunamadı')
    if body.family_id and not conn.execute('SELECT 1 FROM family_members WHERE id = ?', (body.family_id,)).fetchone():
        raise HTTPException(400, 'Aile üyesi bulunamadı')
    if body.visitor_id and not conn.execute('SELECT 1 FROM visitors WHERE id = ?', (body.visitor_id,)).fetchone():
        raise HTTPException(400, 'Ziyaretçi bulunamadı')
    r = _face(conn, 'assign_sightings', ids=list(dict.fromkeys(body.ids)), user_id=body.user_id,
              person_id=body.person_id, family_id=body.family_id, visitor_id=body.visitor_id, by=user['id'], validate=False)
    kind = 'user' if body.user_id else 'person' if body.person_id else 'family' if body.family_id else 'visitor'
    db.audit(conn, user['id'], 'Kamera yüz görülmelerini kişiye atadı', 'face_group', r.get('id'),
             f"{kind}={body.user_id or body.person_id or body.family_id or body.visitor_id} · {len(body.ids)} görülme")
    try:   # atanan görülmeleri eğitime de ekle (en iyi çaba — atama yine başarılı sayılır)
        n = _enroll_assigned(conn, r, kind, body.user_id, body.person_id, body.family_id, user['id'], body.visitor_id)
        if n:
            db.audit(conn, user['id'], f'Atanan yüzler eğitime eklendi: {n}', 'face_enroll', r.get('id'), kind)
    except Exception:   # noqa: BLE001
        pass
    return r


@faces_router.delete('/groups/{gid}')
def delete_group(gid: int, user=Depends(cam_user), conn=db.DB):
    """Yanlış tespit: grup, görülmeleri ve resimleri silinir."""
    r = _face(conn, 'delete_group', gid=gid)
    db.audit(conn, user['id'], 'Kamera yüz grubunu sildi', 'face_group', gid, f"{r.get('files', 0)} resim")
    return r


@faces_router.get('/people')
def people(user=Depends(cam_user), conn=db.DB):
    """Atama seçimi: kullanıcılar, firma kişileri, personel aile üyeleri ve ziyaretçiler (Firma modülü olmadan)."""
    return {
        'users': db.rows(conn.execute('SELECT id, full_name, photo FROM users WHERE active = 1 AND deleted_at IS NULL ORDER BY full_name')),
        'people': db.rows(conn.execute('''SELECT p.id, p.full_name, p.title, c.name AS company_name FROM company_people p
                                          LEFT JOIN companies c ON c.id = p.company_id ORDER BY p.full_name''')),
        'family': db.rows(conn.execute('''SELECT fm.id, fm.full_name, fm.relation, (e.first_name || ' ' || e.last_name) AS employee_name
                                          FROM family_members fm JOIN employees e ON e.id = fm.employee_id ORDER BY fm.full_name''')),
        'visitors': db.rows(conn.execute('SELECT id, full_name, company, phone FROM visitors ORDER BY full_name')),
    }


@faces_router.get('/visitors')
def visitors_list(q: str = '', user=Depends(cam_user), conn=db.DB):
    """Ziyaretçi arama (atama seçici için): ad ya da firmaya göre."""
    q = (q or '').strip()
    if q:
        like = f'%{q}%'
        rows = db.rows(conn.execute(
            '''SELECT id, full_name, company, phone, note FROM visitors
               WHERE full_name LIKE ? OR company LIKE ? ORDER BY full_name LIMIT 60''', (like, like)))
    else:
        rows = db.rows(conn.execute('SELECT id, full_name, company, phone, note FROM visitors ORDER BY full_name LIMIT 60'))
    return {'visitors': rows}


@faces_router.post('/visitors')
def visitor_create(body: VisitorIn, user=Depends(cam_user), conn=db.DB):
    """Yeni ziyaretçi oluştur (atama seçicideki satır içi 'Yeni ziyaretçi'). id + ad döner."""
    name = (body.full_name or '').strip()
    if not name:
        raise HTTPException(400, 'Ziyaretçi adı gerekli')
    cur = conn.execute('INSERT INTO visitors (full_name, company, phone, note, created_by, created_at) VALUES (?,?,?,?,?,?)',
                       (name, (body.company or '').strip() or None, (body.phone or '').strip() or None,
                        (body.note or '').strip() or None, user['id'], db.now()))
    conn.commit()
    db.audit(conn, user['id'], 'Ziyaretçi eklendi', 'visitor', cur.lastrowid, name)
    return {'id': cur.lastrowid, 'full_name': name, 'company': (body.company or '').strip() or None}


@faces_router.delete('/visitors/{visitor_id}')
def visitor_delete(visitor_id: int, user=Depends(cam_user), conn=db.DB):
    """Ziyaretçiyi sil (bağlı eğitim izleri ON DELETE CASCADE, atanmış gruplar ON DELETE SET NULL)."""
    if conn.execute('SELECT 1 FROM visitors WHERE id = ?', (visitor_id,)).fetchone():
        conn.execute('DELETE FROM visitors WHERE id = ?', (visitor_id,))
        conn.commit()
        db.audit(conn, user['id'], 'Ziyaretçi silindi', 'visitor', visitor_id, None)
    return {'ok': True}


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
                family_id: Optional[int] = None, visitor_id: Optional[int] = None, user=Depends(cam_user), conn=db.DB):
    """Bir kişinin eğitim fotoğrafları (yüz kırpıkları)."""
    from .. import faceenroll
    try:
        return {'faces': faceenroll.list_for(conn, subject_type, user_id, person_id, family_id, visitor_id)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@faces_router.post('/enroll')
async def enroll_add(file: UploadFile = File(...), subject_type: str = Form(...),
                     user_id: Optional[int] = Form(None), person_id: Optional[int] = Form(None),
                     family_id: Optional[int] = Form(None), visitor_id: Optional[int] = Form(None),
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
        ok, res = await run_in_threadpool(faceenroll.enroll, conn, subject_type, user_id, person_id, tmp, user['id'], family_id, visitor_id)
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


class EnrollIdsIn(BaseModel):
    ids: list = []


@faces_router.post('/enroll/delete')
def enroll_delete_bulk(body: EnrollIdsIn, user=Depends(cam_user), conn=db.DB):
    """Birden çok eğitim izini toplu siler (Yapay Zeka alt modülü)."""
    from .. import faceenroll
    n = 0
    for i in (body.ids or []):
        try:
            if faceenroll.delete(conn, int(i)):
                n += 1
        except Exception:   # noqa: BLE001
            continue
    if n:
        conn.commit()
        _push_enroll(conn)
    return {'ok': True, 'deleted': n}


class EnrollFrameIn(BaseModel):
    jpg: str                            # base64 JPEG (data: öneki olmadan)
    subject_type: str
    user_id: Optional[int] = None
    person_id: Optional[int] = None
    family_id: Optional[int] = None
    visitor_id: Optional[int] = None


@faces_router.post('/enroll-frame')
def enroll_frame(body: EnrollFrameIn, user=Depends(cam_user), conn=db.DB):
    """iPhone tarzı yüz eğitimi: tarayıcıdan gelen tek kareyi fabrika yüz ajanında işler (en büyük yüz → embedding +
    kırpık + kafa açısı) ve kişiye eğitim izi olarak kaydeder (source='manual', dedupe). Dönüş {found, added, yaw, pitch, box, score}."""
    import base64
    from .. import faceenroll
    res = _face(conn, 'embed_frame', jpg=body.jpg)
    if not isinstance(res, dict) or not res.get('found'):
        return {'found': False}
    try:
        added = faceenroll.enroll_precomputed(conn, body.subject_type, body.user_id, body.person_id, body.family_id,
                                              base64.b64decode(res['crop']), base64.b64decode(res['embedding']),
                                              user['id'], body.visitor_id, source='manual')
    except ValueError as e:
        raise HTTPException(400, str(e))
    if added:
        conn.commit()
        _push_enroll(conn)
    return {'found': True, 'added': bool(added), 'enroll_id': added,
            'yaw': res.get('yaw'), 'pitch': res.get('pitch'), 'box': res.get('box'), 'score': res.get('score')}


def _push_enroll(conn):
    """Eğitim izlerini (ve güncel ayarı) fabrika yüz-tanıma servisine aktarır (en iyi çaba)."""
    try:
        from .. import facebridge
        facebridge.push(conn)
    except Exception:   # noqa: BLE001
        pass


def _enroll_assigned(conn, r, subject_type, user_id, person_id, family_id, by, visitor_id=None):
    """Atama sonucunda gelen `enroll_faces` yükünü (facecore'dan) YENİDEN TESPİT olmadan eğitim verisine ekler:
    her yüz için kırpık görüntüsü getirilir (dağıtık: facebridge.media; yerel: UPLOAD_DIR'den okunur) ve
    faceenroll.enroll_precomputed ile kaydedilir (dedupe'lu). Eklenen yüz varsa eğitim izleri fabrika servisine
    aktarılır (_push_enroll). En iyi çaba: atama başarılı olduktan sonra çalışır, hata atmaz. Eklenen yüz sayısını döner."""
    import base64
    from .. import facebridge, faceenroll
    faces = (r or {}).get('enroll_faces') or []
    added = 0
    for f in faces:
        try:
            crop_path, emb_b64 = f.get('crop'), f.get('embedding')
            if not crop_path or not emb_b64:
                continue
            if facebridge.remote():
                crop_bytes, _ = facebridge.media(crop_path)
            else:
                crop_bytes = (config.UPLOAD_DIR / crop_path).read_bytes()
            if faceenroll.enroll_precomputed(conn, subject_type, user_id, person_id, family_id,
                                             crop_bytes, base64.b64decode(emb_b64), by, visitor_id):
                added += 1
        except Exception:   # noqa: BLE001
            continue
    if added:
        conn.commit()
        _push_enroll(conn)   # yeni eğitim izleri gerçek zamanlı tanımaya ulaşsın
    return added
