"""Dosya Yöneticisi (kişisel dosya gezgini).

Her kullanıcının iç içe klasörleri ve dosyaları vardır (fm_nodes). Bir düğüm (dosya / klasör) bir kullanıcı ya da
rol ile paylaşılabilir (fm_shares); klasör paylaşımı alt ağacın tamamını paylaşır. Paylaşımda hedeflere bildirim düşer
(app/notifications.py file_shared). Yetki modeli:
  - Düğümün SAHİBİ tam yetkilidir (view + edit).
  - Bir düğüm, kullanıcıya (ya da rolüne) yönelik bir fm_shares satırı düğümün KENDİSİNDE ya da herhangi bir ÜST klasöründe
    varsa görüntülenebilir. perm 'edit' o düğüm/alt ağaçta düzenleme verir.
Yüklenen dosyalar UPLOAD_DIR/fm/ altına akışlı yazılır (büyük / her tür dosya); file_path UPLOAD_DIR'e görelidir.
"""
import secrets
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, config, db, files

router = APIRouter(prefix='/api/fm')

FM_MAX_BYTES = 2 * 1024 ** 3   # 2 GB: her tür dosyaya elverişli üst sınır


# ---------- yardımcılar

def _roles(user):
    return user.get('roles') or []


def _opt_id(v):
    """Sorgu / form alanını isteğe bağlı düğüm kimliğine çevirir: boş / 'null' → None (kök)."""
    if v is None:
        return None
    v = str(v).strip()
    if v == '' or v.lower() == 'null':
        return None
    try:
        return int(v)
    except ValueError:
        raise HTTPException(400, 'Geçersiz klasör')


def _node(conn, nid):
    r = db.row(conn.execute('SELECT * FROM fm_nodes WHERE id = ?', (nid,)))
    if not r:
        raise HTTPException(404, 'Öğe bulunamadı')
    return r


def _access(conn, node_id, user):
    """Kullanıcının bir düğümdeki etkin yetkisi: None | 'view' | 'edit'. Sahip → 'edit'; paylaşımlar düğüm ve üst
    klasörler boyunca taranır (en geniş yetki kazanır)."""
    roles = _roles(user)
    best = None
    nid = node_id
    seen = set()
    while nid is not None and nid not in seen:
        seen.add(nid)
        r = db.row(conn.execute('SELECT owner_id, parent_id FROM fm_nodes WHERE id = ?', (nid,)))
        if not r:
            return best
        if r['owner_id'] == user['id']:
            return 'edit'
        for s in db.rows(conn.execute(
                'SELECT target_type, target_user_id, target_role, perm FROM fm_shares WHERE node_id = ?', (nid,))):
            if (s['target_type'] == 'user' and s['target_user_id'] == user['id']) or \
               (s['target_type'] == 'role' and s['target_role'] in roles):
                if s['perm'] == 'edit':
                    best = 'edit'
                elif best is None:
                    best = 'view'
        nid = r['parent_id']
    return best


def _require_edit_parent(conn, parent_id, user):
    """parent_id (None = kendi kök) üzerinde 'edit' şartı; yeni düğümün sahibini (kök → kullanıcı, yoksa klasör sahibi) döndürür."""
    if parent_id is None:
        return user['id']
    node = _node(conn, parent_id)
    if node['kind'] != 'folder':
        raise HTTPException(400, 'Hedef bir klasör değil')
    if _access(conn, parent_id, user) != 'edit':
        raise HTTPException(403, 'Bu klasöre ekleme yetkiniz yok')
    return node['owner_id']


def _check_dup(conn, parent_id, owner_id, name, exclude_id=None):
    """Aynı klasörde (büyük/küçük harf duyarsız) aynı adlı öğe varsa 400."""
    if parent_id is None:
        sql = 'SELECT 1 FROM fm_nodes WHERE owner_id = ? AND parent_id IS NULL AND name = ? COLLATE NOCASE'
        args = [owner_id, name]
    else:
        sql = 'SELECT 1 FROM fm_nodes WHERE parent_id = ? AND name = ? COLLATE NOCASE'
        args = [parent_id, name]
    if exclude_id is not None:
        sql += ' AND id != ?'
        args.append(exclude_id)
    if conn.execute(sql, args).fetchone():
        raise HTTPException(400, 'Bu adda bir öğe zaten var')


def _is_descendant(conn, cand_id, ancestor_id):
    """cand_id, ancestor_id'nin kendisi ya da alt ağacındaki bir düğüm mü? (klasör kendi içine taşınamaz denetimi)"""
    nid = cand_id
    seen = set()
    while nid is not None and nid not in seen:
        seen.add(nid)
        if nid == ancestor_id:
            return True
        r = db.row(conn.execute('SELECT parent_id FROM fm_nodes WHERE id = ?', (nid,)))
        if not r:
            break
        nid = r['parent_id']
    return False


def _shared_flag(conn, nid):
    return bool(conn.execute('SELECT 1 FROM fm_shares WHERE node_id = ? LIMIT 1', (nid,)).fetchone())


def _breadcrumb(conn, folder_id, user):
    """Kökten geçerli klasöre kadar yol (erişilemeyen üst düğümlerde durur). Kök için boş."""
    chain = []
    nid = folder_id
    seen = set()
    while nid is not None and nid not in seen:
        seen.add(nid)
        r = db.row(conn.execute('SELECT id, name, parent_id FROM fm_nodes WHERE id = ?', (nid,)))
        if not r or _access(conn, r['id'], user) is None:
            break
        chain.append({'id': r['id'], 'name': r['name']})
        nid = r['parent_id']
    chain.reverse()
    return chain


async def _save_fm(upload: UploadFile):
    """Yüklenen dosyayı UPLOAD_DIR/fm/ altına belleğe almadan akışlı yazar; (göreli yol, boyut). Her tür / uzantı kabul edilir."""
    ext = Path(upload.filename or '').suffix.lower()[:20]
    folder = config.UPLOAD_DIR / 'fm'
    folder.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(16) + ext
    path = folder / name
    size = 0
    try:
        with open(path, 'wb') as f:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > FM_MAX_BYTES:
                    raise HTTPException(400, f'Dosya {FM_MAX_BYTES // 1024 ** 3} GB sınırını aşıyor')
                f.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(400, 'Dosya boş')
    return f'fm/{name}', size


def _subtree_files(conn, nid):
    """Düğüm ve tüm alt ağacındaki dosya düğümlerinin file_path'leri (silmeden önce fiziksel dosyaları kaldırmak için)."""
    out = []
    stack = [nid]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        r = db.row(conn.execute('SELECT kind, file_path FROM fm_nodes WHERE id = ?', (cur,)))
        if r and r['kind'] == 'file' and r['file_path']:
            out.append(r['file_path'])
        for c in conn.execute('SELECT id FROM fm_nodes WHERE parent_id = ?', (cur,)):
            stack.append(c[0])
    return out


# ---------- listeleme

@router.get('/list')
def fm_list(parent: str = '', user=Depends(auth.current_user), conn=db.DB):
    pid = _opt_id(parent)
    if pid is None:
        can_edit = True
        path = []
        kids = db.rows(conn.execute(
            "SELECT * FROM fm_nodes WHERE owner_id = ? AND parent_id IS NULL ORDER BY kind DESC, name COLLATE NOCASE",
            (user['id'],)))
    else:
        node = _node(conn, pid)
        perm = _access(conn, pid, user)
        if perm is None:
            raise HTTPException(404, 'Öğe bulunamadı')
        if node['kind'] != 'folder':
            raise HTTPException(400, 'Klasör değil')
        can_edit = perm == 'edit'
        path = _breadcrumb(conn, pid, user)
        kids = db.rows(conn.execute(
            "SELECT * FROM fm_nodes WHERE parent_id = ? ORDER BY kind DESC, name COLLATE NOCASE", (pid,)))
    folders, filelist = [], []
    for k in kids:
        sh = _shared_flag(conn, k['id'])
        if k['kind'] == 'folder':
            folders.append({'id': k['id'], 'name': k['name'], 'shared': sh})
        else:
            filelist.append({'id': k['id'], 'name': k['name'], 'size': k['size'], 'mime': k['mime'],
                             'updated_at': k['updated_at'], 'shared': sh})
    return {'path': path, 'folders': folders, 'files': filelist, 'can_edit': can_edit}


@router.get('/tree')
def fm_tree(user=Depends(auth.current_user), conn=db.DB):
    rows = db.rows(conn.execute(
        "SELECT id, name, parent_id FROM fm_nodes WHERE owner_id = ? AND kind = 'folder' ORDER BY name COLLATE NOCASE",
        (user['id'],)))
    return {'nodes': rows}


# ---------- klasör / yükleme

class FolderIn(BaseModel):
    parent_id: Optional[int] = None
    name: str


@router.post('/folder')
def create_folder(body: FolderIn, user=Depends(auth.current_user), conn=db.DB):
    name = (body.name or '').strip()[:255]
    if not name:
        raise HTTPException(400, 'Klasör adı gerekli')
    owner_id = _require_edit_parent(conn, body.parent_id, user)
    _check_dup(conn, body.parent_id, owner_id, name)
    ts = db.now()
    nid = conn.execute(
        'INSERT INTO fm_nodes (owner_id, parent_id, kind, name, created_at, updated_at) VALUES (?,?,?,?,?,?)',
        (owner_id, body.parent_id, 'folder', name, ts, ts)).lastrowid
    conn.commit()
    return {'id': nid}


@router.post('/upload')
async def upload(parent_id: str = Form(''), file: UploadFile = File(...),
                 user=Depends(auth.current_user), conn=db.DB):
    pid = _opt_id(parent_id)
    owner_id = _require_edit_parent(conn, pid, user)
    name = (file.filename or 'dosya').replace('/', '_').replace('\\', '_').strip()[:255] or 'dosya'
    _check_dup(conn, pid, owner_id, name)
    rel, size = await _save_fm(file)
    ts = db.now()
    try:
        nid = conn.execute(
            'INSERT INTO fm_nodes (owner_id, parent_id, kind, name, file_path, size, mime, created_at, updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?)',
            (owner_id, pid, 'file', name, rel, size, file.content_type, ts, ts)).lastrowid
        conn.commit()
    except BaseException:
        (config.UPLOAD_DIR / rel).unlink(missing_ok=True)
        raise
    return {'id': nid, 'name': name, 'size': size, 'mime': file.content_type}


# ---------- yeniden adlandır / taşı / sil

class NodePatch(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None


@router.patch('/node/{nid}')
def patch_node(nid: int, body: NodePatch, user=Depends(auth.current_user), conn=db.DB):
    node = _node(conn, nid)
    if _access(conn, nid, user) != 'edit':
        raise HTTPException(403, 'Bu öğeyi değiştirme yetkiniz yok')
    moving = 'parent_id' in body.model_fields_set
    new_parent = body.parent_id if moving else node['parent_id']
    if moving and body.parent_id is not None:
        _require_edit_parent(conn, body.parent_id, user)
        if node['kind'] == 'folder' and _is_descendant(conn, body.parent_id, nid):
            raise HTTPException(400, 'Klasör kendi içine ya da alt klasörüne taşınamaz')
    new_name = node['name'] if body.name is None else (body.name or '').strip()[:255]
    if not new_name:
        raise HTTPException(400, 'Ad gerekli')
    _check_dup(conn, new_parent, node['owner_id'], new_name, exclude_id=nid)
    conn.execute('UPDATE fm_nodes SET name = ?, parent_id = ?, updated_at = ? WHERE id = ?',
                 (new_name, new_parent, db.now(), nid))
    conn.commit()
    return {'ok': True}


@router.delete('/node/{nid}')
def delete_node(nid: int, user=Depends(auth.current_user), conn=db.DB):
    _node(conn, nid)
    if _access(conn, nid, user) != 'edit':
        raise HTTPException(403, 'Bu öğeyi silme yetkiniz yok')
    paths = _subtree_files(conn, nid)
    conn.execute('DELETE FROM fm_nodes WHERE id = ?', (nid,))   # alt ağaç + paylaşımlar ON DELETE CASCADE ile silinir
    conn.commit()
    for rel in paths:
        try:
            (config.UPLOAD_DIR / rel).unlink(missing_ok=True)
        except Exception:
            pass
    return {'ok': True}


@router.get('/download/{nid}')
def download(nid: int, user=Depends(auth.current_user), conn=db.DB):
    node = _node(conn, nid)
    if _access(conn, nid, user) is None:
        raise HTTPException(404, 'Öğe bulunamadı')
    if node['kind'] != 'file' or not node['file_path']:
        raise HTTPException(404, 'Dosya bulunamadı')
    path = config.UPLOAD_DIR / node['file_path']
    if not path.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return FileResponse(path, filename=node['name'], headers=files._headers(path))


# ---------- paylaşım

@router.get('/node/{nid}/shares')
def node_shares(nid: int, user=Depends(auth.current_user), conn=db.DB):
    node = _node(conn, nid)
    if node['owner_id'] != user['id']:
        raise HTTPException(403, 'Yalnızca sahibi paylaşımları görebilir')
    out = []
    for s in db.rows(conn.execute('SELECT * FROM fm_shares WHERE node_id = ? ORDER BY id', (nid,))):
        if s['target_type'] == 'user':
            u = db.row(conn.execute('SELECT full_name FROM users WHERE id = ?', (s['target_user_id'],)))
            target_name = u['full_name'] if u else '—'
        else:
            target_name = s['target_role']
        out.append({'id': s['id'], 'target_type': s['target_type'], 'target_user_id': s['target_user_id'],
                    'target_role': s['target_role'], 'target_name': target_name, 'perm': s['perm']})
    return {'shares': out}


class ShareTarget(BaseModel):
    type: str
    id: Optional[int] = None
    role: Optional[str] = None
    perm: str = 'view'


class ShareIn(BaseModel):
    targets: List[ShareTarget]


@router.post('/node/{nid}/share')
def share_node(nid: int, body: ShareIn, user=Depends(auth.current_user), conn=db.DB):
    node = _node(conn, nid)
    if node['owner_id'] != user['id']:
        raise HTTPException(403, 'Yalnızca sahibi paylaşabilir')
    valid_roles = set(auth.all_roles())
    added = []   # yeni eklenen paylaşımlar (bildirim için)
    for t in body.targets:
        perm = 'edit' if t.perm == 'edit' else 'view'
        if t.type == 'user':
            if not t.id or not conn.execute('SELECT 1 FROM users WHERE id = ?', (t.id,)).fetchone():
                raise HTTPException(400, 'Kullanıcı bulunamadı')
            if t.id == user['id']:
                continue   # sahibinin kendine paylaşması anlamsız
            if conn.execute('SELECT 1 FROM fm_shares WHERE node_id = ? AND target_type = ? AND target_user_id = ?',
                            (nid, 'user', t.id)).fetchone():
                continue
            sid = conn.execute(
                'INSERT INTO fm_shares (node_id, target_type, target_user_id, perm, shared_by, created_at) VALUES (?,?,?,?,?,?)',
                (nid, 'user', t.id, perm, user['id'], db.now())).lastrowid
            added.append(sid)
        elif t.type == 'role':
            if not t.role or t.role not in valid_roles:
                raise HTTPException(400, 'Rol bulunamadı')
            if conn.execute('SELECT 1 FROM fm_shares WHERE node_id = ? AND target_type = ? AND target_role = ?',
                            (nid, 'role', t.role)).fetchone():
                continue
            sid = conn.execute(
                'INSERT INTO fm_shares (node_id, target_type, target_role, perm, shared_by, created_at) VALUES (?,?,?,?,?,?)',
                (nid, 'role', t.role, perm, user['id'], db.now())).lastrowid
            added.append(sid)
        else:
            raise HTTPException(400, 'Geçersiz hedef türü')
    conn.commit()
    # Bildirim: yeni eklenen hedefler fm_share_seen kaydı olmadığından file_shared ile hedeflere düşer (çevrimiçi
    # tarama ayrıca telefon push'u atar). Burada ek kayıt gerekmez; paylaşım satırlarının kendisi bildirimdir.
    return {'ok': True, 'shared': len(added)}


@router.delete('/share/{sid}')
def delete_share(sid: int, user=Depends(auth.current_user), conn=db.DB):
    s = db.row(conn.execute(
        'SELECT fs.id, n.owner_id AS node_owner FROM fm_shares fs JOIN fm_nodes n ON n.id = fs.node_id WHERE fs.id = ?',
        (sid,)))
    if not s:
        raise HTTPException(404, 'Paylaşım bulunamadı')
    if s['node_owner'] != user['id']:
        raise HTTPException(403, 'Yalnızca sahibi paylaşımı kaldırabilir')
    conn.execute('DELETE FROM fm_shares WHERE id = ?', (sid,))
    conn.commit()
    return {'ok': True}


@router.get('/shared')
def shared_with_me(user=Depends(auth.current_user), conn=db.DB):
    """Benimle paylaşılanlar (doğrudan + rol). En üstteki paylaşılan düğüme tekilleştirilir (üstü zaten paylaşılan alt
    düğümler tekrar listelenmez). YAN ETKİ: bu kullanıcıya yönelik tüm paylaşımlar görüldü işaretlenir (bildirim temizlenir)."""
    roles = _roles(user)
    conds = ['(fs.target_type = ? AND fs.target_user_id = ?)']
    args = ['user', user['id']]
    if roles:
        ph = ','.join('?' * len(roles))
        conds.append(f'(fs.target_type = ? AND fs.target_role IN ({ph}))')
        args += ['role', *roles]
    where = ' OR '.join(conds)
    rows = db.rows(conn.execute(
        f'''SELECT fs.id AS share_id, fs.node_id, fs.perm, fs.created_at, n.name, n.kind, n.parent_id,
                   u.full_name AS shared_by_name
            FROM fm_shares fs JOIN fm_nodes n ON n.id = fs.node_id LEFT JOIN users u ON u.id = fs.shared_by
            WHERE n.owner_id != ? AND ({where})
            ORDER BY fs.created_at DESC''',
        (user['id'], *args)))
    shared_ids = {r['node_id'] for r in rows}
    best, meta = {}, {}
    for r in rows:
        conn.execute('INSERT OR IGNORE INTO fm_share_seen (share_id, user_id, seen_at) VALUES (?,?,?)',
                     (r['share_id'], user['id'], db.now()))
        nid = r['node_id']
        if nid not in best or r['perm'] == 'edit':
            best[nid] = r['perm']
        meta.setdefault(nid, r)
    conn.commit()

    def _ancestor_shared(parent_id):
        nid = parent_id
        guard = set()
        while nid is not None and nid not in guard:
            guard.add(nid)
            if nid in shared_ids:
                return True
            r = db.row(conn.execute('SELECT parent_id FROM fm_nodes WHERE id = ?', (nid,)))
            if not r:
                break
            nid = r['parent_id']
        return False

    items = []
    for nid, r in meta.items():
        if _ancestor_shared(r['parent_id']):
            continue   # üstü zaten paylaşılan: tekrar listeleme
        items.append({'node_id': nid, 'name': r['name'], 'kind': r['kind'],
                      'shared_by_name': r['shared_by_name'], 'created_at': r['created_at'], 'perm': best[nid]})
    return {'items': items}
