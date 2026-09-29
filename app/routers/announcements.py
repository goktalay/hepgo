"""Duyurular: Sistem Yöneticisi yazar, herkes okur. Kullanıcı duyuruyu açınca okundu sayılır ve okunmamışlar listesinden
düşer; yönetici her duyuruyu kimin okuduğunu (ve okumayanları) görür. Okunmamış duyurular bildirim ve panoda görünür."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/announcements')
reader = auth.require_module('announcements')
LEVELS = ('BILGI', 'ONEMLI', 'KRITIK')


def is_admin(user):
    return auth.ADMIN in user['roles']


def admin_only(user=Depends(reader)):
    if not is_admin(user):
        raise HTTPException(403, 'Duyuruyu yalnızca Sistem Yöneticisi yazabilir')
    return user


class AnnIn(BaseModel):
    title: str
    body: str
    level: str = 'BILGI'
    pinned: bool = False
    expires_at: Optional[str] = None


ACTIVE = "(a.expires_at IS NULL OR a.expires_at >= substr(?, 1, 10))"


def unread_for(conn, user_id):
    return db.rows(conn.execute(
        f'''SELECT a.id, a.title, a.level, a.created_at FROM announcements a
            WHERE {ACTIVE} AND NOT EXISTS (SELECT 1 FROM announcement_reads r WHERE r.announcement_id = a.id AND r.user_id = ?)
            ORDER BY a.pinned DESC, a.created_at DESC''', (db.now(), user_id)))


@router.get('')
def list_announcements(user=Depends(reader), conn=db.DB):
    admin = is_admin(user)
    rows = db.rows(conn.execute(
        f'''SELECT a.*, u.full_name AS created_by_name,
                   (SELECT read_at FROM announcement_reads r WHERE r.announcement_id = a.id AND r.user_id = ?) AS read_at,
                   (SELECT COUNT(*) FROM announcement_reads r WHERE r.announcement_id = a.id) AS read_count
            FROM announcements a LEFT JOIN users u ON u.id = a.created_by
            WHERE {'1=1' if admin else ACTIVE} ORDER BY a.pinned DESC, a.created_at DESC''', (user['id'],) if admin else (user['id'], db.now())))
    total = conn.execute('SELECT COUNT(*) FROM users WHERE active = 1 AND deleted_at IS NULL').fetchone()[0]
    for r in rows:
        r['expired'] = bool(r['expires_at'] and r['expires_at'] < db.now()[:10])
        if admin:
            r['user_total'] = total
        else:
            r.pop('read_count', None)
    return {'items': rows, 'can_edit': admin}


@router.get('/{aid}')
def get_announcement(aid: int, user=Depends(reader), conn=db.DB):
    """Duyuruyu açmak onu okundu yapar. Yönetici okuyanları ve okumayanları da görür."""
    a = db.row(conn.execute('SELECT a.*, u.full_name AS created_by_name FROM announcements a LEFT JOIN users u ON u.id = a.created_by WHERE a.id = ?', (aid,)))
    if not a:
        raise HTTPException(404, 'Duyuru bulunamadı')
    conn.execute('INSERT OR IGNORE INTO announcement_reads (announcement_id, user_id, read_at) VALUES (?,?,?)', (aid, user['id'], db.now()))
    if is_admin(user):
        a['readers'] = db.rows(conn.execute(
            '''SELECT u.id, u.full_name, u.photo, r.read_at FROM announcement_reads r JOIN users u ON u.id = r.user_id
               WHERE r.announcement_id = ? ORDER BY r.read_at''', (aid,)))
        a['unread'] = db.rows(conn.execute(
            '''SELECT u.id, u.full_name, u.photo FROM users u WHERE u.active = 1 AND u.deleted_at IS NULL
               AND u.id NOT IN (SELECT user_id FROM announcement_reads WHERE announcement_id = ?) ORDER BY u.full_name''', (aid,)))
    return a


def _check(body):
    if not body.title.strip() or not body.body.strip():
        raise HTTPException(400, 'Başlık ve metin zorunlu')
    if body.level not in LEVELS:
        raise HTTPException(400, 'Geçersiz önem düzeyi')


@router.post('')
def create(body: AnnIn, user=Depends(admin_only), conn=db.DB):
    _check(body)
    cur = conn.execute('''INSERT INTO announcements (title, body, level, pinned, expires_at, created_by, created_at) VALUES (?,?,?,?,?,?,?)''',
                       (body.title.strip(), body.body.strip(), body.level, int(body.pinned), body.expires_at or None, user['id'], db.now()))
    conn.execute('INSERT INTO announcement_reads (announcement_id, user_id, read_at) VALUES (?,?,?)', (cur.lastrowid, user['id'], db.now()))
    db.audit(conn, user['id'], 'Duyuru yayımladı', 'announcement', cur.lastrowid, body.title.strip())
    return {'id': cur.lastrowid}


@router.put('/{aid}')
def update(aid: int, body: AnnIn, user=Depends(admin_only), conn=db.DB):
    _check(body)
    if not conn.execute('SELECT 1 FROM announcements WHERE id = ?', (aid,)).fetchone():
        raise HTTPException(404, 'Duyuru bulunamadı')
    conn.execute('UPDATE announcements SET title = ?, body = ?, level = ?, pinned = ?, expires_at = ?, updated_at = ? WHERE id = ?',
                 (body.title.strip(), body.body.strip(), body.level, int(body.pinned), body.expires_at or None, db.now(), aid))
    db.audit(conn, user['id'], 'Duyuru düzenledi', 'announcement', aid, body.title.strip())
    return {'ok': True}


@router.delete('/{aid}')
def delete(aid: int, user=Depends(admin_only), conn=db.DB):
    conn.execute('DELETE FROM announcements WHERE id = ?', (aid,))
    db.audit(conn, user['id'], 'Duyuru sildi', 'announcement', aid, None)
    return {'ok': True}
