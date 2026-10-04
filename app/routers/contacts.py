"""Rehber › Kişilerim — /api/my/contacts: kişisel rehber (mail yazışmaları, Google / Outlook kişileri, elle eklenenler).
Yalnızca sahibi görür; yönetici dahil başka hiç kimse erişemez."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/my/contacts')


@router.get('')
def list_contacts(q: str = '', user=Depends(auth.current_user), conn=db.DB):
    t = f'%{q.strip().lower()}%'
    rows = db.rows(conn.execute('''SELECT * FROM personal_contacts WHERE user_id = ? AND (lower(COALESCE(name, '')) LIKE ? OR lower(COALESCE(email, '')) LIKE ?
                                   OR lower(COALESCE(company, '')) LIKE ? OR COALESCE(phone, '') LIKE ?) ORDER BY COALESCE(name, email) COLLATE NOCASE LIMIT 3000''',
                                (user['id'], t, t, t, t)))
    return {'contacts': rows}


class ContactIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    note: Optional[str] = None


def _vals(b):
    if not (b.name or b.email or b.phone):
        raise HTTPException(400, 'Ad, e-posta ya da telefon girin')
    t = lambda v, n=200: ((v or '').strip()[:n] or None)
    return t(b.name), (t(b.email) or '').lower() or None, t(b.phone, 60), t(b.company), t(b.title), t(b.note, 2000)


@router.post('')
def add(b: ContactIn, user=Depends(auth.current_user), conn=db.DB):
    import secrets
    v = _vals(b)
    now = db.now()
    cur = conn.execute('''INSERT INTO personal_contacts (user_id, source, ext_id, name, email, phone, company, title, note, created_at, updated_at)
                          VALUES (?, 'manual', ?, ?,?,?,?,?,?,?,?)''', (user['id'], secrets.token_hex(8), *v, now, now))
    conn.commit()
    return {'id': cur.lastrowid}


def _own(conn, user, cid):
    r = db.row(conn.execute('SELECT * FROM personal_contacts WHERE id = ? AND user_id = ?', (cid, user['id'])))
    if not r:
        raise HTTPException(404, 'Kişi bulunamadı')
    return r


@router.put('/{cid}')
def update(cid: int, b: ContactIn, user=Depends(auth.current_user), conn=db.DB):
    _own(conn, user, cid)
    conn.execute('UPDATE personal_contacts SET name=?, email=?, phone=?, company=?, title=?, note=?, updated_at=? WHERE id=?', (*_vals(b), db.now(), cid))
    conn.commit()
    return {'ok': True}


@router.delete('/{cid}')
def delete(cid: int, user=Depends(auth.current_user), conn=db.DB):
    _own(conn, user, cid)
    conn.execute('DELETE FROM personal_contacts WHERE id = ?', (cid,))
    conn.commit()
    return {'ok': True}
