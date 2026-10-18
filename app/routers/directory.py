"""Rehber (birleşik kişi rehberi) — /api/directory. Kişi listesi + kaynaktan bağımsız kişi detayı (evrak, yüz tanıma,
görüşme, toplantı). Bölümler bakanın modül yetkisine göre süzülür (app/directory.py)."""
from fastapi import APIRouter, Depends, HTTPException, Response

from .. import auth, db, directory

router = APIRouter(prefix='/api/directory')
dir_user = auth.require_module('rehber')


@router.get('')
def list_people(q: str = '', kind: str = 'all', user=Depends(dir_user), conn=db.DB):
    return {'people': directory.people(conn, q, kind if kind in ('all', 'user', 'person', 'family') else 'all')}


@router.get('/face-avatar/{ptype}/{pid}')
def face_avatar(ptype: str, pid: int, user=Depends(dir_user), conn=db.DB):
    """Fotoğrafı olmayan kişi için yüz tanımada EN SON tanınan yüzün kırpığı (JPEG). Rehberi gören herkes görür;
    kamera medyasının geneli (tam kare, klip) bu uçtan açılmaz."""
    r = directory.face_avatar_bytes(conn, ptype, pid)
    if not r:
        raise HTTPException(404, 'Yüz kaydı yok')
    data, ctype = r
    return Response(data, media_type=ctype or 'image/jpeg', headers={'Cache-Control': 'private, max-age=300'})


@router.get('/{ptype}/{pid}')
def person(ptype: str, pid: int, user=Depends(dir_user), conn=db.DB):
    try:
        return directory.detail(conn, user, ptype, pid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
