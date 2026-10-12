"""Ekran bazlı sürüm takibi uçları (bkz. app/ui_updates.py)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, ui_updates as U

router = APIRouter(prefix='/api/ui')


def _admin(user=Depends(auth.current_user)):
    if not (user.get('master') or auth.ADMIN in user.get('roles', [])):
        raise HTTPException(403, 'Yalnız Sistem Yöneticisi')
    return user


class LoadedIn(BaseModel):
    stamp: Optional[str] = None


@router.post('/loaded')
def loaded(body: LoadedIn, user=Depends(auth.current_user), conn=db.DB):
    """İstemci açıldı: hangi derlemeyle yüklendi → sürüm id'si. Yanıt: {release, current, pending}."""
    U.ensure_tables(conn)
    rid = U.set_loaded(conn, user['id'], body.stamp)
    return {'release': rid, 'current': U.current_id(conn), 'pending': U.pending_for(conn, rid)}


@router.get('/updates')
def updates(loaded: int = 0, user=Depends(auth.current_user), conn=db.DB):
    """loaded sürümünden sonra değişen ekranlar: {current, pending:{screen: release}} ('*' = tüm ekranlar)."""
    U.ensure_tables(conn)
    return {'current': U.current_id(conn), 'pending': U.pending_for(conn, loaded)}


class AckIn(BaseModel):
    screen: str
    release: int
    kind: str = 'refresh'


@router.post('/ack')
def ack(body: AckIn, user=Depends(auth.current_user), conn=db.DB):
    U.ensure_tables(conn)
    kind = body.kind if body.kind in ('refresh', 'visit') else 'refresh'
    return {'ok': True, 'n': U.ack(conn, user['id'], body.screen[:60], body.release, kind)}


# ---- Yönetim › Sürüm Takibi
@router.get('/releases')
def releases(user=Depends(_admin), conn=db.DB):
    U.ensure_tables(conn)
    scr, _ = U.screens()
    rows = db.rows(conn.execute('SELECT id, stamp, created_at, screens, files FROM ui_releases ORDER BY id DESC LIMIT 200'))
    import json
    out = []
    for r in rows:
        s = json.loads(r['screens'] or '[]')
        out.append({'id': r['id'], 'stamp': r['stamp'], 'created_at': r['created_at'], 'all': '*' in s,
                    'screens': sorted(scr) if '*' in s else s, 'screen_count': len(scr) if '*' in s else len(s),
                    'files': json.loads(r['files'] or '[]')})
    return {'items': out, 'current': U.current_id(conn), 'screen_titles': {k: v['title'] for k, v in scr.items()}}


@router.get('/releases/{rid}/screens')
def release_screens(rid: int, user=Depends(_admin), conn=db.DB):
    U.ensure_tables(conn)
    d = U.release_screens(conn, rid)
    if not d:
        raise HTTPException(404, 'Sürüm bulunamadı')
    return d


@router.get('/releases/{rid}/screens/{screen}/users')
def release_screen_users(rid: int, screen: str, user=Depends(_admin), conn=db.DB):
    U.ensure_tables(conn)
    return U.screen_users(conn, rid, screen)


@router.post('/rescan')
def rescan(user=Depends(_admin), conn=db.DB):
    """Elle tarama: dosyalar değiştiyse yeni sürüm kaydı (normalde başlangıçta yapılır)."""
    from ..main import asset_version
    return {'release': U.ensure_release(conn, asset_version())}
