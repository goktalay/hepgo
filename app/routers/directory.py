"""Rehber (birleşik kişi rehberi) — /api/directory. Kişi listesi + kaynaktan bağımsız kişi detayı (evrak, yüz tanıma,
görüşme, toplantı). Bölümler bakanın modül yetkisine göre süzülür (app/directory.py)."""
from fastapi import APIRouter, Depends, HTTPException

from .. import auth, db, directory

router = APIRouter(prefix='/api/directory')
dir_user = auth.require_module('rehber')


@router.get('')
def list_people(q: str = '', kind: str = 'all', user=Depends(dir_user), conn=db.DB):
    return {'people': directory.people(conn, q, kind if kind in ('all', 'user', 'person', 'family') else 'all')}


@router.get('/{ptype}/{pid}')
def person(ptype: str, pid: int, user=Depends(dir_user), conn=db.DB):
    try:
        return directory.detail(conn, user, ptype, pid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
