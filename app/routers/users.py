from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, db
from ..files import save_upload

router = APIRouter(prefix='/api/users')
admin_only = auth.require_module('users')


class UserIn(BaseModel):
    username: str
    full_name: str
    phone: Optional[str] = None
    roles: list[str] = []
    active: bool = True
    password: Optional[str] = None


def _validate(conn, body, user_id=None):
    if not body.username.strip() or not body.full_name.strip():
        raise HTTPException(400, 'Kullanıcı adı ve ad soyad zorunlu')
    bad = [r for r in body.roles if r not in auth.ROLES]
    if bad:
        raise HTTPException(400, f'Geçersiz rol: {", ".join(bad)}')
    dup = conn.execute('SELECT id FROM users WHERE username = ? AND id IS NOT ?',
                       (body.username.strip(), user_id)).fetchone()
    if dup:
        raise HTTPException(400, 'Bu kullanıcı adı zaten kayıtlı')
    if body.password is not None and body.password != '' and len(body.password) < 8:
        raise HTTPException(400, 'Şifre en az 8 karakter olmalı')


def _with_roles(conn, users):
    for u in users:
        u['roles'] = auth.user_roles(conn, u['id'])
    return users


@router.get('')
def list_users(q: str = '', role: str = '', user=Depends(admin_only), conn=db.DB):
    sql = '''SELECT id, username, full_name, phone, photo, active, created_at, last_seen,
                    (SELECT MAX(at) FROM login_logs l WHERE l.user_id = users.id AND success = 1) AS last_login
             FROM users WHERE deleted_at IS NULL'''
    args = []
    if q:
        sql += ' AND (username LIKE ? OR full_name LIKE ?)'
        args += [f'%{q}%', f'%{q}%']
    if role:
        sql += ' AND id IN (SELECT user_id FROM user_roles WHERE role = ?)'
        args.append(role)
    return _with_roles(conn, db.rows(conn.execute(sql + ' ORDER BY full_name', args)))


@router.post('')
def create_user(body: UserIn, user=Depends(admin_only), conn=db.DB):
    _validate(conn, body)
    if not body.password:
        raise HTTPException(400, 'Yeni kullanıcı için şifre zorunlu')
    cur = conn.execute(
        'INSERT INTO users (username, password_hash, full_name, phone, active, created_at) VALUES (?,?,?,?,?,?)',
        (body.username.strip(), auth.hash_password(body.password), body.full_name.strip(),
         body.phone, int(body.active), db.now()))
    uid = cur.lastrowid
    conn.executemany('INSERT INTO user_roles (user_id, role) VALUES (?,?)', [(uid, r) for r in set(body.roles)])
    db.audit(conn, user['id'], 'Kullanıcı oluşturdu', 'user', uid, body.username)
    return {'id': uid}


@router.get('/{uid}')
def get_user(uid: int, user=Depends(admin_only), conn=db.DB):
    u = db.row(conn.execute('SELECT id, username, full_name, phone, photo, active, created_at FROM users '
                            'WHERE id = ? AND deleted_at IS NULL', (uid,)))
    if not u:
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    return _with_roles(conn, [u])[0]


@router.put('/{uid}')
def update_user(uid: int, body: UserIn, user=Depends(admin_only), conn=db.DB):
    if not conn.execute('SELECT 1 FROM users WHERE id = ?', (uid,)).fetchone():
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    _validate(conn, body, uid)
    if uid == user['id'] and (auth.ADMIN not in body.roles or not body.active):
        raise HTTPException(400, 'Kendi yönetici yetkinizi veya hesabınızı kapatamazsınız')
    conn.execute('UPDATE users SET username = ?, full_name = ?, phone = ?, active = ? WHERE id = ?',
                 (body.username.strip(), body.full_name.strip(), body.phone, int(body.active), uid))
    conn.execute('DELETE FROM user_roles WHERE user_id = ?', (uid,))
    conn.executemany('INSERT INTO user_roles (user_id, role) VALUES (?,?)', [(uid, r) for r in set(body.roles)])
    if body.password:
        conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (auth.hash_password(body.password), uid))
        conn.execute('DELETE FROM sessions WHERE user_id = ?', (uid,))
    if not body.active:
        conn.execute('DELETE FROM sessions WHERE user_id = ?', (uid,))
    db.audit(conn, user['id'], 'Kullanıcı bilgilerini düzenledi', 'user', uid,
             body.username + (' (şifre sıfırlandı)' if body.password else ''))
    return {'ok': True}


# Kullanıcının adının geçtiği iş kayıtları: varsa kullanıcı tamamen silinmez, geçmiş bozulmasın diye arşivlenir
_REFERENCES = [
    ('orders', 'created_by'), ('orders', 'completed_by'), ('order_parts', 'delivered_to'), ('order_parts', 'approved_by'),
    ('part_events', 'user_id'), ('part_events', 'target_user'), ('field_tasks', 'lead_id'), ('field_tasks', 'driver_id'), ('field_tasks', 'pilot_id'), ('field_task_vehicles', 'driver_id'),
    ('field_tasks', 'created_by'), ('field_task_staff', 'user_id'), ('flight_logs', 'uploaded_by'),
    ('flight_videos', 'uploaded_by'), ('field_expenses', 'created_by'), ('field_expenses', 'spent_by'), ('assembly_steps', 'recorded_by'),
    ('assembly_staff', 'user_id'), ('companies', 'created_by'), ('documents', 'uploaded_by'),
    ('company_meetings', 'created_by'), ('meeting_users', 'user_id'), ('document_signatures', 'signer_id'),
    ('document_signatures', 'requested_by'), ('spare_moves', 'user_id'),
    ('crm_notes', 'created_by'), ('crm_events', 'created_by'), ('crm_event_users', 'user_id'),
    ('document_faces', 'user_id'), ('document_faces', 'assigned_by'), ('flight_notes', 'created_by'),
]


@router.delete('/{uid}')
def delete_user(uid: int, user=Depends(admin_only), conn=db.DB):
    u = db.row(conn.execute('SELECT * FROM users WHERE id = ? AND deleted_at IS NULL', (uid,)))
    if not u:
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    if uid == user['id']:
        raise HTTPException(400, 'Kendi hesabınızı silemezsiniz')
    if auth.ADMIN in auth.user_roles(conn, uid) and conn.execute(
            '''SELECT COUNT(*) FROM users x JOIN user_roles r ON r.user_id = x.id
               WHERE r.role = ? AND x.active = 1 AND x.deleted_at IS NULL AND x.id != ?''', (auth.ADMIN, uid)).fetchone()[0] == 0:
        raise HTTPException(400, 'Son sistem yöneticisi silinemez')
    used = any(conn.execute(f'SELECT 1 FROM {t} WHERE {c} = ? LIMIT 1', (uid,)).fetchone() for t, c in _REFERENCES)
    if used:
        # Arşivle: listeden ve seçim listelerinden kalkar, giriş yapamaz, kullanıcı adı yeniden kullanılabilir
        conn.execute('''UPDATE users SET active = 0, deleted_at = ?, username = ?, last_seen = NULL WHERE id = ?''',
                     (db.now(), f'{u["username"]}#silindi-{uid}', uid))
        conn.execute('DELETE FROM user_roles WHERE user_id = ?', (uid,))
        conn.execute('DELETE FROM sessions WHERE user_id = ?', (uid,))
        mode = 'archived'
    else:
        conn.execute("DELETE FROM crm_notes WHERE subject_type = 'user' AND subject_id = ?", (uid,))
        conn.execute("DELETE FROM crm_events WHERE subject_type = 'user' AND subject_id = ?", (uid,))
        conn.execute('DELETE FROM users WHERE id = ?', (uid,))   # roller ve oturumlar da silinir
        mode = 'deleted'
    db.audit(conn, user['id'], 'Kullanıcıyı sildi', 'user', uid,
             f'{u["full_name"]} ({u["username"]})' + (' – geçmiş kayıtları korundu' if used else ''))
    return {'mode': mode}


@router.post('/{uid}/photo')
async def upload_photo(uid: int, file: UploadFile, user=Depends(admin_only), conn=db.DB):
    if not conn.execute('SELECT 1 FROM users WHERE id = ?', (uid,)).fetchone():
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    path = await save_upload('users', file)

    def write():
        conn.execute('UPDATE users SET photo = ? WHERE id = ?', (path, uid))
        db.audit(conn, user['id'], 'Kullanıcı resmini güncelledi', 'user', uid)
    await run_in_threadpool(write)
    return {'photo': path}


@router.get('/{uid}/logs')
def user_logs(uid: int, kind: str = '', q: str = '', date_from: str = '', date_to: str = '', limit: int = 1000,
              user=Depends(admin_only), conn=db.DB):
    """Kullanıcının tüm hareketleri. kind: 'page' (sayfa hareketleri) | 'action' (işlemler) | '' (tümü)."""
    where, args = ['user_id = ?'], [uid]
    if kind == 'page':
        where.append("entity = 'page'")
    elif kind == 'action':
        where.append("(entity IS NULL OR entity != 'page')")
    if q:
        where.append('(action LIKE ? OR detail LIKE ? OR entity_id LIKE ?)')
        args += [f'%{q}%'] * 3
    if date_from:
        where.append('at >= ?')
        args.append(date_from)
    if date_to:
        where.append('at < ?')
        args.append(date_to + 'T99')
    cond = ' AND '.join(where)
    rows = db.rows(conn.execute(
        f'SELECT id, action, entity, entity_id, detail, at FROM audit_logs WHERE {cond} ORDER BY id DESC LIMIT ?',
        (*args, max(1, min(limit, 5000)))))
    total = conn.execute(f'SELECT COUNT(*) FROM audit_logs WHERE {cond}', args).fetchone()[0]
    today = db.now()[:10]
    stats = conn.execute(
        '''SELECT COUNT(*), SUM(entity = 'page' AND action = 'Sayfaya girdi'), SUM(entity IS NULL OR entity != 'page'),
                  SUM(at >= ?), MIN(at), MAX(at) FROM audit_logs WHERE user_id = ?''', (today, uid)).fetchone()
    top = db.rows(conn.execute(
        '''SELECT detail AS page, COUNT(*) AS n FROM audit_logs WHERE user_id = ? AND entity = 'page'
           AND action = 'Sayfaya girdi' GROUP BY detail ORDER BY n DESC LIMIT 3''', (uid,)))
    return {'rows': rows, 'total': total, 'summary': {
        'all': stats[0], 'page_views': stats[1] or 0, 'actions': stats[2] or 0, 'today': stats[3] or 0,
        'first': stats[4], 'last': stats[5], 'top_pages': top}}


@router.get('/{uid}/logins')
def user_logins(uid: int, user=Depends(admin_only), conn=db.DB):
    return db.rows(conn.execute(
        'SELECT id, success, ip, user_agent, at FROM login_logs WHERE user_id = ? ORDER BY id DESC LIMIT 500',
        (uid,)))
