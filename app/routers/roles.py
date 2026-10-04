"""Rol Yönetimi — /api/roles (Program Ayarları; Sistem Yöneticisi ve MASTER). Rol adı "/" içerebildiği için
(ör. "Kalite / Sertifikasyon") rol, adres yolunda değil ?name= parametresinde taşınır.

Roller ağaç şeklindedir (üst rolden miras), her rol için modül / alt modül bazında aç · veri oku · veri yaz izni ya da
yasağı tanımlanır (kayıt yoksa miras). Kişi birden çok role atanabilir; izin ile yasak çakışırsa yasak geçerlidir ve
uyarı gösterilir. Görev ayrılığı için "çakışan roller" tanımlanabilir (aynı kişiye atanınca uyarı)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, rbac

router = APIRouter(prefix='/api/roles')


def role_admin(user=Depends(auth.current_user)):
    if user.get('master') or auth.ADMIN in user['roles']:
        return user
    raise HTTPException(403, 'Rol Yönetimi yalnızca sistem yöneticisine açıktır')


def _role(conn, name):
    r = db.row(conn.execute('SELECT * FROM roles WHERE name = ?', (name,)))
    if not r:
        raise HTTPException(404, 'Rol bulunamadı')
    return r


def _users_of(conn, name):
    rows = db.rows(conn.execute('''SELECT u.id, u.username, u.full_name, u.active FROM users u JOIN user_roles r ON r.user_id = u.id
                                   WHERE r.role = ? AND u.deleted_at IS NULL ORDER BY u.full_name COLLATE NOCASE''', (name,)))
    for u in rows:
        u['roles'] = auth.user_roles(conn, u['id'])
        c = rbac.conflicts(u['roles'])
        u['conflicts'] = len(c['perm']) + len(c['sod'])
    return rows


@router.get('')
def list_roles(user=Depends(role_admin), conn=db.DB):
    counts = {r[0]: r[1] for r in conn.execute('''SELECT r.role, COUNT(*) FROM user_roles r JOIN users u ON u.id = r.user_id
                                                 WHERE u.deleted_at IS NULL AND u.active = 1 GROUP BY r.role''')}
    nperm = {r[0]: r[1] for r in conn.execute('SELECT role, COUNT(*) FROM role_perms GROUP BY role')}
    roles = db.rows(conn.execute('SELECT * FROM roles ORDER BY system DESC, sort, name COLLATE NOCASE'))
    for r in roles:
        r['locked'] = r['name'] == rbac.LOCKED
        r['users'] = counts.get(r['name'], 0)
        r['perm_count'] = nperm.get(r['name'], 0)
    return {'roles': roles, 'catalog': rbac.catalog(), 'caps': rbac.CAP_LABELS, 'locked': rbac.LOCKED}


@router.get('/users/all')
def all_users(user=Depends(role_admin), conn=db.DB):
    rows = db.rows(conn.execute("SELECT id, username, full_name, active FROM users WHERE deleted_at IS NULL ORDER BY full_name COLLATE NOCASE"))
    for u in rows:
        u['roles'] = auth.user_roles(conn, u['id'])
    return [u for u in rows if not auth.is_master(u['username'])]


@router.get('/check')
def check(roles: str = '', user=Depends(role_admin)):
    """Verilen rol birleşiminin çakışmaları (Kullanıcı Yönetimi'nde atama öncesi uyarı)."""
    return rbac.conflicts([r for r in roles.split(',') if r])


@router.get('/one')
def get_role(name: str, user=Depends(role_admin), conn=db.DB):
    r = _role(conn, name)
    r['locked'] = name == rbac.LOCKED
    explicit = {}
    for node, cap, allow in conn.execute('SELECT node, cap, allow FROM role_perms WHERE role = ?', (name,)):
        explicit.setdefault(node, {})[cap] = bool(allow)
    st = rbac.state()
    eff = {}
    for n in rbac.node_keys():
        for cap in rbac.CAPS:
            v, src_role, src_node = rbac.role_value(name, n, cap, st)
            if v is not None:
                eff.setdefault(n, {})[cap] = {'value': v, 'role': src_role, 'node': src_node}
    final = rbac.effective([name])
    r.update(perms=explicit, effective=eff, final=final, chain=rbac.role_chain(name),
             children=[x[0] for x in conn.execute('SELECT name FROM roles WHERE parent = ? ORDER BY name', (name,))],
             conflicts_with=sorted({b if a == name else a for a, b in conn.execute('SELECT a, b FROM role_conflicts WHERE a = ? OR b = ?', (name, name))}),
             users=_users_of(conn, name))
    return r


class RoleIn(BaseModel):
    name: str
    description: Optional[str] = None
    parent: Optional[str] = None
    copy_from: Optional[str] = None
    conflicts_with: Optional[List[str]] = None


def _check_parent(conn, name, parent):
    if not parent:
        return None
    _role(conn, parent)
    if parent == name or name in rbac.role_chain(parent, {r[0]: r[1] for r in conn.execute('SELECT name, parent FROM roles')}):
        raise HTTPException(400, 'Üst rol, rolün kendisi ya da alt rolü olamaz (döngü)')
    return parent


def _clean_name(n):
    n = ' '.join((n or '').split())[:60]
    if not n or n.upper() == auth.MASTER:
        raise HTTPException(400, 'Geçerli bir rol adı girin')
    return n


def _set_conflicts(conn, name, others):
    if others is None:
        return
    conn.execute('DELETE FROM role_conflicts WHERE a = ? OR b = ?', (name, name))
    for o in set(others):
        if o != name and conn.execute('SELECT 1 FROM roles WHERE name = ?', (o,)).fetchone():
            a, b = sorted((name, o))
            conn.execute('INSERT OR IGNORE INTO role_conflicts (a, b) VALUES (?,?)', (a, b))


@router.post('')
def create_role(b: RoleIn, user=Depends(role_admin), conn=db.DB):
    name = _clean_name(b.name)
    if conn.execute('SELECT 1 FROM roles WHERE name = ? COLLATE NOCASE', (name,)).fetchone():
        raise HTTPException(409, 'Bu adla bir rol zaten var')
    parent = _check_parent(conn, name, b.parent)
    sort = (conn.execute('SELECT MAX(sort) FROM roles').fetchone()[0] or 0) + 1
    conn.execute('INSERT INTO roles (name, description, parent, system, sort, created_at, updated_at) VALUES (?,?,?,0,?,?,?)',
                 (name, (b.description or '').strip()[:300] or None, parent, sort, db.now(), db.now()))
    if b.copy_from:
        _role(conn, b.copy_from)
        conn.execute('INSERT INTO role_perms (role, node, cap, allow) SELECT ?, node, cap, allow FROM role_perms WHERE role = ?', (name, b.copy_from))
    _set_conflicts(conn, name, b.conflicts_with)
    db.audit(conn, user['id'], 'Rol oluşturdu', 'role', None, name + (f' (üst: {parent})' if parent else ''))
    conn.commit()
    rbac.bump()
    return {'name': name}


@router.put('/one')
def update_role(name: str, b: RoleIn, user=Depends(role_admin), conn=db.DB):
    r = _role(conn, name)
    new = _clean_name(b.name)
    if new != name:
        if r['system']:
            raise HTTPException(400, 'Sistem rollerinin adı değiştirilemez (programda kullanılıyor); açıklamasını değiştirebilirsiniz')
        if conn.execute('SELECT 1 FROM roles WHERE name = ? COLLATE NOCASE AND name != ?', (new, name)).fetchone():
            raise HTTPException(409, 'Bu adla bir rol zaten var')
    parent = _check_parent(conn, name, b.parent) if name != rbac.LOCKED else None
    conn.execute('UPDATE roles SET description = ?, parent = ?, updated_at = ? WHERE name = ?',
                 ((b.description or '').strip()[:300] or None, parent, db.now(), name))
    _set_conflicts(conn, name, b.conflicts_with)
    if new != name:   # yeniden adlandırma: role bağlı tüm kayıtlar
        for sql in ('UPDATE roles SET name = ? WHERE name = ?', 'UPDATE roles SET parent = ? WHERE parent = ?',
                    'UPDATE role_perms SET role = ? WHERE role = ?', 'UPDATE role_conflicts SET a = ? WHERE a = ?',
                    'UPDATE role_conflicts SET b = ? WHERE b = ?', 'UPDATE user_roles SET role = ? WHERE role = ?',
                    'UPDATE document_roles SET role = ? WHERE role = ?'):
            conn.execute(sql, (new, name))
    db.audit(conn, user['id'], 'Rolü düzenledi', 'role', None, name if new == name else f'{name} → {new}')
    conn.commit()
    rbac.bump()
    return {'name': new}


@router.delete('/one')
def delete_role(name: str, confirm: str = '', user=Depends(role_admin), conn=db.DB):
    r = _role(conn, name)
    if r['system']:
        raise HTTPException(400, 'Sistem rolleri silinemez; izinlerini kısıtlayabilir ya da kullanıcılarını çıkarabilirsiniz')
    if confirm.strip() != name:
        raise HTTPException(400, 'Silmek için rol adını aynen yazın')
    n = conn.execute('SELECT COUNT(*) FROM user_roles WHERE role = ?', (name,)).fetchone()[0]
    conn.execute('UPDATE roles SET parent = ? WHERE parent = ?', (r['parent'], name))   # alt roller bir üste bağlanır
    for sql in ('DELETE FROM role_perms WHERE role = ?', 'DELETE FROM role_conflicts WHERE a = ? OR b = ?',
                'DELETE FROM user_roles WHERE role = ?', 'DELETE FROM document_roles WHERE role = ?', 'DELETE FROM roles WHERE name = ?'):
        conn.execute(sql, (name,) * sql.count('?'))
    db.audit(conn, user['id'], 'Rol sildi', 'role', None, f'{name} · {n} kullanıcıdan kaldırıldı')
    conn.commit()
    rbac.bump()
    return {'ok': True, 'users_removed': n}


class PermChange(BaseModel):
    node: str
    cap: str
    value: Optional[bool] = None   # True izin · False yasak · None miras


class PermsIn(BaseModel):
    changes: List[PermChange]


@router.put('/perms')
def set_perms(name: str, b: PermsIn, user=Depends(role_admin), conn=db.DB):
    _role(conn, name)
    if name == rbac.LOCKED:
        raise HTTPException(400, 'Sistem Yöneticisi tüm yetkilere sahiptir; izinleri değiştirilemez')
    nodes = set(rbac.node_keys())
    for c in b.changes:
        if c.node not in nodes or c.cap not in rbac.CAPS:
            raise HTTPException(400, f'Geçersiz izin: {c.node}/{c.cap}')
        if c.value is None:
            conn.execute('DELETE FROM role_perms WHERE role = ? AND node = ? AND cap = ?', (name, c.node, c.cap))
        else:
            conn.execute('''INSERT INTO role_perms (role, node, cap, allow) VALUES (?,?,?,?)
                            ON CONFLICT(role, node, cap) DO UPDATE SET allow = excluded.allow''', (name, c.node, c.cap, int(c.value)))
    conn.execute('UPDATE roles SET updated_at = ? WHERE name = ?', (db.now(), name))
    db.audit(conn, user['id'], 'Rol izinlerini değiştirdi', 'role', None,
             f"{name}: " + ', '.join(f"{c.node}/{c.cap}={'miras' if c.value is None else 'izin' if c.value else 'yasak'}" for c in b.changes)[:500])
    conn.commit()
    rbac.bump()
    return {'ok': True}


class UsersIn(BaseModel):
    user_ids: List[int]


@router.post('/members')
def add_users(name: str, b: UsersIn, user=Depends(role_admin), conn=db.DB):
    _role(conn, name)
    warnings = []
    for uid in b.user_ids:
        u = db.row(conn.execute('SELECT id, full_name FROM users WHERE id = ? AND deleted_at IS NULL', (uid,)))
        if not u:
            continue
        conn.execute('INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?,?)', (uid, name))
        c = rbac.conflicts(auth.user_roles(conn, uid))
        if c['perm'] or c['sod']:
            warnings.append({'user': u['full_name'], **c})
    db.audit(conn, user['id'], 'Role kullanıcı ekledi', 'role', None, f'{name}: {len(b.user_ids)} kullanıcı')
    conn.commit()
    return {'ok': True, 'warnings': warnings}


@router.delete('/members')
def remove_user(name: str, uid: int, user=Depends(role_admin), conn=db.DB):
    if name == auth.ADMIN:
        if uid == user['id']:
            raise HTTPException(400, 'Kendi yönetici yetkinizi kaldıramazsınız')
        left = conn.execute('''SELECT COUNT(*) FROM user_roles r JOIN users u ON u.id = r.user_id
                               WHERE r.role = ? AND u.active = 1 AND u.deleted_at IS NULL AND u.id != ?''', (auth.ADMIN, uid)).fetchone()[0]
        if not left:
            raise HTTPException(400, 'Son aktif sistem yöneticisi rolden çıkarılamaz')
    conn.execute('DELETE FROM user_roles WHERE user_id = ? AND role = ?', (uid, name))
    db.audit(conn, user['id'], 'Rolden kullanıcı çıkardı', 'role', None, f'{name}: kullanıcı {uid}')
    conn.commit()
    return {'ok': True}
