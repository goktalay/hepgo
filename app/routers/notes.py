"""Kişisel notlar (yapışkan not) — yalnız sahibi görür.

Panoda "Notlar" kutucuğu ve Kişisel › Notlar modülü bu uçları kullanır. Not ekrana iğnelenebilir (pinned=1,
pin_x/pin_y oranı); hangi modülde olunursa olunsun ekranda kalır (arayüzde global katman).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/notes')
COLORS = ('yellow', 'green', 'blue', 'pink', 'orange', 'purple')
PUBLIC = ('id', 'body', 'color', 'pinned', 'pin_x', 'pin_y', 'sort', 'created_at', 'updated_at')


def _pub(r):
    d = {k: r[k] for k in PUBLIC}
    d['pinned'] = bool(d['pinned'])
    return d


@router.get('')
def list_notes(user=Depends(auth.current_user), conn=db.DB):
    rows = db.rows(conn.execute('SELECT * FROM personal_notes WHERE user_id = ? ORDER BY sort, id DESC', (user['id'],)))
    return [_pub(r) for r in rows]


class NoteIn(BaseModel):
    body: str = ''
    color: str = 'yellow'


@router.post('')
def add_note(body: NoteIn, user=Depends(auth.current_user), conn=db.DB):
    color = body.color if body.color in COLORS else 'yellow'
    sort = conn.execute('SELECT COALESCE(MIN(sort), 0) - 1 FROM personal_notes WHERE user_id = ?', (user['id'],)).fetchone()[0]
    nid = conn.execute('INSERT INTO personal_notes (user_id, body, color, sort, created_at) VALUES (?,?,?,?,?)',
                       (user['id'], body.body.strip()[:4000], color, sort, db.now())).lastrowid
    conn.commit()
    return _pub(db.row(conn.execute('SELECT * FROM personal_notes WHERE id = ?', (nid,))))


class NotePatch(BaseModel):
    body: Optional[str] = None
    color: Optional[str] = None
    pinned: Optional[bool] = None
    pin_x: Optional[float] = None
    pin_y: Optional[float] = None


def _own(conn, nid, user):
    r = db.row(conn.execute('SELECT * FROM personal_notes WHERE id = ? AND user_id = ?', (nid, user['id'])))
    if not r:
        raise HTTPException(404, 'Not bulunamadı')
    return r


@router.put('/{nid}')
def update_note(nid: int, body: NotePatch, user=Depends(auth.current_user), conn=db.DB):
    r = _own(conn, nid, user)
    body_val = r['body'] if body.body is None else body.body.strip()[:4000]
    color = r['color'] if body.color is None else (body.color if body.color in COLORS else r['color'])
    pinned = r['pinned'] if body.pinned is None else int(bool(body.pinned))
    px = r['pin_x'] if body.pin_x is None else max(0.0, min(1.0, body.pin_x))
    py = r['pin_y'] if body.pin_y is None else max(0.0, min(1.0, body.pin_y))
    conn.execute('UPDATE personal_notes SET body = ?, color = ?, pinned = ?, pin_x = ?, pin_y = ?, updated_at = ? WHERE id = ?',
                 (body_val, color, pinned, px, py, db.now(), nid))
    conn.commit()
    return _pub(db.row(conn.execute('SELECT * FROM personal_notes WHERE id = ?', (nid,))))


@router.delete('/{nid}')
def delete_note(nid: int, user=Depends(auth.current_user), conn=db.DB):
    _own(conn, nid, user)
    conn.execute('DELETE FROM personal_notes WHERE id = ?', (nid,))
    conn.commit()
    return {'ok': True}
