"""İş Güvenliği — kamera tabanlı kural denetimi (KKD, bölge, araç, davranış, ergonomi): kurallar ve bölgeler, uyarılar
(kare + klip), canlı izleme, ısı haritası, güvenlik puanı / raporlar.

Tespiti kamera servisi içindeki işleyici (app/worksafety_worker.py) yapar; bu yönlendirici yapılandırmayı saklar ve
sonuçları listeler. Dağıtık kurulumda (AGENT_MODE=remote) yapılandırmanın doğruluk kaynağı buluttur (app_kv), olaylar /
ısı / istatistik fabrikanın yerel veritabanındadır ve `face.rpc` (ws_*) ile okunur; görüntü fabrikadan çıkmaz."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import auth, db, facebridge
from .. import worksafety as W
from ..files import FILE_GUARDS
from . import cameras as cameras_router

router = APIRouter(prefix='/api/worksafety')
ws_user = auth.require_module('worksafety')
FILE_GUARDS['wsevents'] = lambda user, name: 'worksafety' in user['modules'] or bool(user.get('master'))   # uyarı karesi / klibi
OUTDATED = 'Fabrika ajanı güncel değil: İş Güvenliği için fabrika bilgisayarındaki yazılımın güncellenmesi gerekir'


def _ws(conn, method, _timeout=25, **args):
    """Fabrika tarafı işlemi: dağıtık kurulumda ajandan, tek makinede doğrudan."""
    if facebridge.remote():
        try:
            return facebridge.rpc(method, _timeout=_timeout, **args)
        except HTTPException as e:
            if 'Bilinmeyen' in str(e.detail):   # eski ajan ws_* işlemlerini tanımaz
                raise HTTPException(409, OUTDATED)
            raise
        except (RuntimeError, TimeoutError) as e:
            raise HTTPException(503, str(e) or 'Fabrika ajanına ulaşılamadı')
    try:
        r = W.rpc(conn, method, args)
        conn.commit()
        return r
    except W.NotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _status(conn):
    """İşleyici durumu; fabrikaya ulaşılamıyorsa nedenini taşıyan boş durum (arayüz açıklasın)."""
    try:
        st = _ws(conn, 'ws_status', _timeout=8)
        st['reachable'] = True
    except HTTPException as e:
        st = {'reachable': False, 'running': False, 'problem': e.detail, 'outdated': e.status_code == 409}
    cfg = W.get_config(conn)
    st['enabled'], st['faces_mode'], st['remote'] = cfg['enabled'], cfg['faces_mode'], facebridge.remote()
    return st


def _caps(st):
    if not st.get('running') or 'objects' not in st:
        return None
    classes = list(st.get('classes_extra') or [])
    return {'objects': st.get('objects'), 'pose': st.get('pose'), 'ppe': st.get('ppe') or [], 'classes': classes,
            'backend': st.get('backend')}


@router.get('/catalog')
def catalog(user=Depends(ws_user)):
    """Kural, bölge türü ve KKD kataloğu + (işleyici çalışıyorsa) kural başına model durumu."""
    with db.connect() as conn:
        st = _status(conn)
    caps = _caps(st)
    if caps is not None:   # COCO sınıfları işleyicide hep vardır; durumda yalnız ek sınıflar taşınır
        from .. import worksafety_detect as D
        caps['classes'] = list(D.COCO) + caps['classes']
    return {**W.catalog(caps), 'status': st}


@router.get('/status')
def status(user=Depends(ws_user)):
    with db.connect() as conn:
        return _status(conn)


@router.get('/config')
def get_config(user=Depends(ws_user)):
    with db.connect() as conn:
        return W.get_config(conn)


@router.put('/config')
def put_config(body: dict, user=Depends(ws_user)):
    """Kurallar, KKD senaryo grupları, bölgeler, kamera kapsamı ve genel ayarlar tek belgede saklanır; fabrikaya hemen aktarılır."""
    with db.connect() as conn:
        old = W.get_config(conn)
        cfg = W.set_config(conn, body)
        conn.commit()
        diff = [k for k in cfg if cfg[k] != old.get(k)]
        db.audit(conn, user['id'], 'İş Güvenliği ayarı', 'worksafety', None,
                 ('etkin' if cfg['enabled'] else 'kapalı') + (f' · değişen: {", ".join(diff)}' if diff else ''))
        conn.commit()
        warn = None
        if facebridge.remote():
            try:
                _ws(conn, 'ws_config_set', _timeout=12, cfg=cfg)
            except HTTPException as e:
                warn = f'Ayar kaydedildi ancak fabrikaya aktarılamadı ({e.detail}). Fabrika bağlandığında kendiliğinden aktarılır.'
    return {'ok': True, 'config': cfg, 'warning': warn}


@router.get('/cameras')
def cameras(user=Depends(ws_user)):
    with db.connect() as conn:
        cfg = W.get_config(conn)
        try:
            rows = _ws(conn, 'ws_cameras', _timeout=12)
        except HTTPException as e:
            if e.status_code != 409:
                raise
            rows = [{k: c.get(k) for k in ('id', 'name', 'location', 'status', 'last_frame_at', 'faces', 'active', 'live_age')}
                    for c in facebridge.rpc('cameras_list')]
    for c in rows:
        cc = W.camera_config(cfg, c['id'])
        c['in_scope'] = cc is not None
        grp = (cc.get('ppe_groups') or {}).get(cc.get('ppe_group')) if cc else None
        c['ppe'] = bool(cc and (cc.get('ppe') or grp))
        c['ppe_group'], c['ppe_group_name'] = (grp['id'], grp['name']) if grp else (None, None)
        c['zones'] = len(cc['zones']) if cc else 0
    return rows


@router.get('/cameras/{cid}/frame')
def frame(cid: int, request: Request, w: int = 0, user=Depends(ws_user)):
    """Bölge çizimi ve canlı izleme için kameranın son karesi (Kameralar modülündeki uçla aynı kaynak)."""
    return cameras_router.frame(cid, request, w, user)


@router.get('/live')
def live(ids: str = '', user=Depends(ws_user)):
    """Canlı izleme kaplaması: kamera başına kişi / araç kutuları ve o andaki ihlaller."""
    want = [int(x) for x in ids.split(',') if x.strip().isdigit()][:64]
    if not want:
        return {}
    with db.connect() as conn:
        return _ws(conn, 'ws_live', _timeout=8, ids=want)


@router.get('/events')
def events(since: Optional[str] = None, until: Optional[str] = None, rule: Optional[str] = None, level: Optional[str] = None,
           cat: Optional[str] = None, camera: Optional[int] = None, ack: Optional[str] = None, limit: int = 300,
           user=Depends(ws_user)):
    args = {k: v for k, v in {'since': since, 'until': until, 'rule': rule, 'level': level, 'cat': cat, 'camera': camera,
                              'ack': ack, 'limit': limit}.items() if v not in (None, '')}
    with db.connect() as conn:
        return _ws(conn, 'ws_events', **args)


@router.get('/events/{eid}')
def event(eid: int, user=Depends(ws_user)):
    with db.connect() as conn:
        return _ws(conn, 'ws_event', id=eid)


class AckIn(BaseModel):
    ids: list[int]
    note: Optional[str] = None
    undo: bool = False


@router.post('/events/ack')
def ack(body: AckIn, user=Depends(ws_user)):
    """Uyarıları 'görüldü / kapatıldı' işaretler (ya da geri alır)."""
    with db.connect() as conn:
        r = _ws(conn, 'ws_ack', ids=body.ids[:2000], by=user['id'], name=user.get('full_name') or user.get('username'),
                note=body.note, undo=body.undo)
        db.audit(conn, user['id'], 'İş Güvenliği uyarısı ' + ('yeniden açıldı' if body.undo else 'kapatıldı'), 'worksafety', None,
                 f'{r.get("n", 0)} uyarı' + (f' · {body.note.strip()[:120]}' if body.note and body.note.strip() else ''))
        conn.commit()
        return r


@router.get('/heatmap')
def heatmap(request: Request, kind: str = 'person', camera: Optional[int] = None, to: Optional[str] = None, user=Depends(ws_user)):
    """Kamera başına 32×18 yoğunluk ızgarası (kişi / araç / ihlal) — tarih aralığı `from` / `to`."""
    args = {k: v for k, v in {'kind': kind, 'camera': camera, 'from': request.query_params.get('from'), 'to': to}.items()
            if v not in (None, '')}
    with db.connect() as conn:
        return _ws(conn, 'ws_heat', **args)


@router.get('/report')
def report(request: Request, to: Optional[str] = None, user=Depends(ws_user)):
    """Dönem raporu: güvenlik puanı + gün / kural / kamera / vardiya / bölge kırılımı (varsayılan son 7 gün)."""
    args = {k: v for k, v in {'from': request.query_params.get('from'), 'to': to}.items() if v not in (None, '')}
    with db.connect() as conn:
        return _ws(conn, 'ws_report', **args)
