"""Patron ekranı — /api/boss: üst yönetim özeti (yalnızca okunur) ve kart ayrıntıları."""
from fastapi import APIRouter, Depends, HTTPException

from .. import auth, boss, db

router = APIRouter(prefix='/api/boss')
boss_user = auth.require_module('boss')


@router.get('')
def summary(fresh: int = 0, user=Depends(boss_user), conn=db.DB):
    s = dict(boss.summary(conn, bool(fresh)))
    s['user'] = user['full_name']
    return s


@router.get('/detail/{key}')
def detail(key: str, user=Depends(boss_user), conn=db.DB):
    d = boss.detail(conn, key)
    if d is None:
        raise HTTPException(404, 'Ayrıntı bulunamadı')
    return d
