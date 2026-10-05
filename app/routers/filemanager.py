"""Dosya Yöneticisi (kişisel dosya gezgini).

Her kullanıcının iç içe klasörleri ve dosyaları vardır (fm_nodes). Bir düğüm (dosya / klasör) bir kullanıcı ya da
rol ile paylaşılabilir (fm_shares); klasör paylaşımı alt ağacın tamamını paylaşır. Paylaşımda hedeflere bildirim düşer
(app/notifications.py file_shared). Yetki modeli:
  - Düğümün SAHİBİ tam yetkilidir (view + edit).
  - Bir düğüm, kullanıcıya (ya da rolüne) yönelik bir fm_shares satırı düğümün KENDİSİNDE ya da herhangi bir ÜST klasöründe
    varsa görüntülenebilir. perm 'edit' o düğüm/alt ağaçta düzenleme verir.
Yüklenen dosyalar UPLOAD_DIR/fm/ altına akışlı yazılır (büyük / her tür dosya); file_path UPLOAD_DIR'e görelidir.
"""
import html as _html
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from .. import auth, config, db, files

router = APIRouter(prefix='/api/fm')
public = APIRouter()   # /p/{token}: oturumsuz (herkese açık) dış paylaşım bağlantıları — current_user YOK

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


# ---------- dış (herkese açık) paylaşım bağlantıları (yetkili uçlar) ----------

def _client_ip(request: Request):
    return (request.headers.get('cf-connecting-ip')
            or (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
            or (request.client.host if request.client else '')) or '?'


def _link_expired(link):
    return bool(link['expires_at']) and link['expires_at'] < db.now()


def _link_remaining(link):
    """Kalan süre (saniye); süresiz ise None, süresi dolduysa 0."""
    if not link['expires_at']:
        return None
    delta = (datetime.fromisoformat(link['expires_at']) - datetime.now()).total_seconds()
    return max(0, int(delta))


class PublicLinkIn(BaseModel):
    password: str
    hours: Optional[int] = None   # geçerlilik süresi (saat); 0 / None = süresiz


@router.post('/node/{nid}/public-link')
def create_public_link(nid: int, body: PublicLinkIn, request: Request, user=Depends(auth.current_user), conn=db.DB):
    _node(conn, nid)
    if _access(conn, nid, user) != 'edit':
        raise HTTPException(403, 'Bu öğe için dış bağlantı oluşturma yetkiniz yok')
    pw = (body.password or '').strip()
    if len(pw) < 4:
        raise HTTPException(400, 'Şifre en az 4 karakter olmalı')
    hours = body.hours or 0
    if hours < 0 or hours > 720:
        raise HTTPException(400, 'Süre 1–720 saat arası olmalı')
    token = secrets.token_urlsafe(16)
    expires_at = (datetime.now() + timedelta(hours=hours)).isoformat(timespec='seconds') if hours else None
    conn.execute(
        'INSERT INTO fm_public_links (token, node_id, password_hash, expires_at, created_by, created_at) '
        'VALUES (?,?,?,?,?,?)',
        (token, nid, auth.hash_password(pw), expires_at, user['id'], db.now()))
    conn.commit()
    return {'token': token, 'url': f'/p/{token}'}


@router.get('/node/{nid}/public-links')
def list_public_links(nid: int, user=Depends(auth.current_user), conn=db.DB):
    _node(conn, nid)
    if _access(conn, nid, user) != 'edit':
        raise HTTPException(403, 'Bu öğenin dış bağlantılarını görme yetkiniz yok')
    out = []
    for r in db.rows(conn.execute(
            'SELECT * FROM fm_public_links WHERE node_id = ? ORDER BY id DESC', (nid,))):
        out.append({'id': r['id'], 'token': r['token'], 'url': f"/p/{r['token']}",
                    'created_at': r['created_at'], 'expires_at': r['expires_at'],
                    'claimed_at': r['claimed_at'], 'revoked': bool(r['revoked']),
                    'expired': _link_expired(r), 'remaining': _link_remaining(r)})
    return {'links': out}


@router.delete('/public-link/{lid}')
def revoke_public_link(lid: int, user=Depends(auth.current_user), conn=db.DB):
    link = db.row(conn.execute('SELECT * FROM fm_public_links WHERE id = ?', (lid,)))
    if not link:
        raise HTTPException(404, 'Bağlantı bulunamadı')
    is_admin = auth.ADMIN in user['roles'] or auth.BOSS in user['roles'] or user.get('master')
    if link['created_by'] != user['id'] and not is_admin:
        raise HTTPException(403, 'Bu bağlantıyı yalnızca oluşturan ya da yönetim kaldırabilir')
    conn.execute('UPDATE fm_public_links SET revoked = 1 WHERE id = ?', (lid,))
    conn.commit()
    return {'ok': True}


# ---------- dış paylaşım: oturumsuz (herkese açık) uçlar — /p/{token} ----------

def _pub_link(conn, token):
    """Geçerli (iptal edilmemiş, süresi dolmamış) bağlantı satırı; yoksa None."""
    link = db.row(conn.execute('SELECT * FROM fm_public_links WHERE token = ?', (token,)))
    if not link or link['revoked'] or _link_expired(link):
        return None
    return link


def _pub_cookie(token):
    return f'fmp_{token}'


def _pub_gate(request: Request, conn, token):
    """Her oturumsuz uçta zorunlu denetim: geçerli bağlantı + sahiplenilmiş + istek çerezi sahipleyen oturumla eşleşir.
    Döner: (link). Aksi halde HTTPException."""
    link = _pub_link(conn, token)
    if not link:
        raise HTTPException(404, 'Bağlantı geçersiz veya süresi dolmuş')
    claim = request.cookies.get(_pub_cookie(token))
    if not link['claimed_session'] or not claim or not secrets.compare_digest(claim, link['claimed_session']):
        raise HTTPException(403, 'Bu bağlantı için önce şifre girmeniz gerekiyor')
    return link


def _pub_items(conn, link, parent):
    """Paylaşılan düğümün (alt ağacın) içeriğini verir. parent=None → paylaşılan düğümün kendisi (dosya ise dosya,
    klasör ise doğrudan çocukları). parent verilirse alt ağaç içinde kısıtlanır."""
    root = _node(conn, link['node_id'])
    if root['kind'] == 'file':
        return {'is_file': True, 'node_name': root['name'], 'current': None, 'up_parent': None,
                'items': [{'id': root['id'], 'name': root['name'], 'is_dir': False,
                           'mime': root['mime'], 'size': root['size']}]}
    # klasör: gezinme hedefi alt ağaç (kök ya da altındaki bir klasör) ile sınırlı
    cur = link['node_id'] if parent is None else parent
    if cur != link['node_id'] and not _is_descendant(conn, cur, link['node_id']):
        raise HTTPException(403, 'Bu bağlantının kapsamı dışında')
    cur_node = _node(conn, cur)
    if cur_node['kind'] != 'folder':
        raise HTTPException(400, 'Klasör değil')
    up = None if cur == link['node_id'] else cur_node['parent_id']
    kids = db.rows(conn.execute(
        "SELECT id, name, kind, mime, size FROM fm_nodes WHERE parent_id = ? ORDER BY kind DESC, name COLLATE NOCASE", (cur,)))
    items = [{'id': k['id'], 'name': k['name'], 'is_dir': k['kind'] == 'folder',
              'mime': k['mime'], 'size': k['size']} for k in kids]
    return {'is_file': False, 'node_name': root['name'], 'current': cur, 'up_parent': up, 'items': items}


def _pub_payload(conn, link, parent=None):
    data = _pub_items(conn, link, parent)
    data.update({'ok': True, 'expires_at': link['expires_at'], 'remaining': _link_remaining(link)})
    return data


@public.get('/p/{token}')
def public_page(token: str, request: Request, conn=db.DB):
    link = _pub_link(conn, token)
    if not link:
        return HTMLResponse(_public_html(token, invalid=True), status_code=404,
                            headers={'Cache-Control': 'no-store'})
    return HTMLResponse(_public_html(token, invalid=False), headers={'Cache-Control': 'no-store'})


async def _unlock_password(request: Request):
    """Şifreyi JSON gövdesinden ya da form verisinden okur (ikisi de desteklenir)."""
    ctype = (request.headers.get('content-type') or '').lower()
    try:
        if 'application/json' in ctype:
            data = await request.json()
            return (data or {}).get('password') or ''
        form = await request.form()
        return form.get('password') or ''
    except Exception:
        return ''


@public.post('/p/{token}/unlock')
async def public_unlock(token: str, request: Request, response: Response, conn=db.DB):
    link = _pub_link(conn, token)
    if not link:
        raise HTTPException(404, 'Bağlantı geçersiz veya süresi dolmuş')
    pw = await _unlock_password(request)
    if not auth.verify_password(pw, link['password_hash']):
        raise HTTPException(401, 'Şifre hatalı')
    cookie = request.cookies.get(_pub_cookie(token))
    if link['claimed_session']:
        # Zaten sahiplenilmiş: yalnızca sahipleyen oturum (çerezi eşleşen) devam edebilir
        if not cookie or not secrets.compare_digest(cookie, link['claimed_session']):
            raise HTTPException(403, 'Başka biri bu şifre ile giriş yapmıştır.')
    else:
        # İlk doğru şifre: bağlantıyı bu oturuma kilitle
        claim = secrets.token_urlsafe(24)
        conn.execute(
            'UPDATE fm_public_links SET claimed_session = ?, claimed_at = ?, claimed_ua = ?, claimed_ip = ? '
            'WHERE id = ? AND claimed_session IS NULL',
            (claim, db.now(), (request.headers.get('user-agent') or '')[:300], _client_ip(request), link['id']))
        conn.commit()
        link = db.row(conn.execute('SELECT * FROM fm_public_links WHERE id = ?', (link['id'],)))
        # Yarış durumu: araya başka oturum girip sahiplendiyse ve bizim çerez eşleşmiyorsa reddet
        if not secrets.compare_digest(link['claimed_session'], claim):
            raise HTTPException(403, 'Başka biri bu şifre ile giriş yapmıştır.')
        response.set_cookie(_pub_cookie(token), claim, httponly=True, samesite='lax',
                            secure=auth.is_https(request),
                            max_age=_link_remaining(link) or 7 * 24 * 3600, path=f'/p/{token}')
    return _pub_payload(conn, link)


@public.get('/p/{token}/list')
def public_list(token: str, request: Request, parent: str = '', conn=db.DB):
    link = _pub_gate(request, conn, token)
    return _pub_payload(conn, link, parent=_opt_id(parent))


@public.get('/p/{token}/download/{nid}')
def public_download(token: str, nid: int, request: Request, conn=db.DB):
    link = _pub_gate(request, conn, token)
    node = _node(conn, nid)
    # yalnız paylaşılan düğüm ya da alt ağacındaki bir dosya
    if nid != link['node_id'] and not _is_descendant(conn, nid, link['node_id']):
        raise HTTPException(403, 'Bu bağlantının kapsamı dışında')
    if node['kind'] != 'file' or not node['file_path']:
        raise HTTPException(404, 'Dosya bulunamadı')
    path = config.UPLOAD_DIR / node['file_path']
    if not path.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return FileResponse(path, filename=node['name'], headers=files._headers(path))


def _public_html(token, invalid):
    """Oturumsuz, bağımsız (SPA'sız) dış paylaşım sayfası. Tüm CSS/JS satır içi ve bağımsızdır."""
    tok = _html.escape(token, quote=True)
    if invalid:
        return _PUBLIC_INVALID
    return _PUBLIC_PAGE.replace('__TOKEN__', tok)


_PUBLIC_INVALID = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Bağlantı geçersiz</title>
<style>:root{color-scheme:light dark}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#e2e8f0}
.box{max-width:420px;padding:32px;text-align:center}.ic{font-size:48px}h1{font-size:20px;margin:16px 0 8px}
p{color:#94a3b8;line-height:1.5}</style></head><body><div class="box"><div class="ic">🔒</div>
<h1>Bağlantı geçersiz veya süresi dolmuş</h1>
<p>Bu paylaşım bağlantısı kaldırılmış, süresi dolmuş ya da hiç var olmamış. Lütfen bağlantıyı paylaşan kişiyle iletişime geçin.</p>
</div></body></html>"""


_PUBLIC_PAGE = r"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Paylaşılan dosyalar</title>
<style>
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:#0f172a;color:#e2e8f0;display:flex;flex-direction:column;align-items:center}
.wrap{width:100%;max-width:720px;padding:24px 16px}
.card{background:#1e293b;border:1px solid #334155;border-radius:14px;padding:24px;box-shadow:0 10px 30px rgba(0,0,0,.3)}
h1{font-size:19px;margin:0 0 4px}.muted{color:#94a3b8;font-size:13px}
form{margin-top:18px;display:flex;flex-direction:column;gap:12px}
input[type=password]{width:100%;padding:12px 14px;border-radius:10px;border:1px solid #475569;background:#0f172a;
color:#e2e8f0;font-size:15px}
button{cursor:pointer;border:0;border-radius:10px;padding:12px 16px;font-size:15px;font-weight:600;
background:#3b82f6;color:#fff}button:disabled{opacity:.6;cursor:default}
.err{color:#f87171;font-size:13px;min-height:16px}
.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.count{font-variant-numeric:tabular-nums;font-weight:700;background:#0f172a;border:1px solid #334155;
padding:6px 12px;border-radius:999px;font-size:14px}
.count.warn{color:#fbbf24;border-color:#78350f}.count.over{color:#f87171}
.crumbs{font-size:13px;color:#94a3b8;margin-bottom:10px}
.up{background:#334155;color:#e2e8f0;padding:8px 12px;font-size:13px;margin-bottom:10px}
ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
li{display:flex;align-items:center;gap:12px;background:#0f172a;border:1px solid #334155;border-radius:10px;padding:10px 14px}
li .ic{font-size:22px;flex:0 0 auto}li .nm{flex:1 1 auto;word-break:break-word}
li .sz{color:#94a3b8;font-size:12px;flex:0 0 auto}
li.dir{cursor:pointer}li.dir:hover{border-color:#3b82f6}
a.dl{color:#60a5fa;text-decoration:none;font-size:13px;font-weight:600;flex:0 0 auto}
.hidden{display:none}
.foot{text-align:center;color:#64748b;font-size:12px;margin-top:18px}
</style></head><body><div class="wrap">
<div class="card">
  <div id="auth">
    <h1>Paylaşılan içerik</h1>
    <p class="muted">Bu içerik şifre korumalıdır. Görüntülemek için size verilen şifreyi girin.</p>
    <form id="f">
      <input id="pw" type="password" placeholder="Şifre" autocomplete="off" autofocus>
      <div class="err" id="e"></div>
      <button id="b" type="submit">Aç</button>
    </form>
    <p class="muted">Bu bağlantı ilk giren kişiye kilitlenir ve süresi dolduğunda kapanır.</p>
  </div>
  <div id="view" class="hidden">
    <div class="bar">
      <h1 id="title" style="margin:0">Dosyalar</h1>
      <span class="count" id="count">—</span>
    </div>
    <div class="crumbs" id="crumbs"></div>
    <div id="list"></div>
  </div>
</div>
<div class="foot">Güvenli dış paylaşım bağlantısı</div>
</div>
<script>
var TOKEN = "__TOKEN__";
var BASE = "/p/" + TOKEN;
var timer = null, deadline = null;
function esc(s){var d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML;}
function fmtSize(b){if(b==null)return '';var u=['B','KB','MB','GB','TB'],i=0,n=b;while(n>=1024&&i<u.length-1){n/=1024;i++;}return (i?n.toFixed(1):n)+' '+u[i];}
function render(d){
  document.getElementById('auth').classList.add('hidden');
  document.getElementById('view').classList.remove('hidden');
  document.getElementById('title').textContent = d.node_name || 'Dosyalar';
  setCountdown(d.remaining);
  var crumbs = document.getElementById('crumbs');
  crumbs.innerHTML = '';
  if(!d.is_file && d.up_parent != null){
    var up = document.createElement('button');
    up.className='up'; up.textContent='⬆ Üst klasör';
    up.onclick=function(){load(d.up_parent);};
    crumbs.appendChild(up);
  }
  var list = document.getElementById('list');
  var ul = document.createElement('ul');
  if(!d.items.length){ list.innerHTML = '<p class="muted">Bu klasör boş.</p>'; return; }
  d.items.forEach(function(it){
    var li = document.createElement('li');
    if(it.is_dir){
      li.className='dir';
      li.innerHTML = '<span class="ic">📁</span><span class="nm">'+esc(it.name)+'</span>';
      li.onclick=function(){load(it.id);};
    } else {
      li.innerHTML = '<span class="ic">📄</span><span class="nm">'+esc(it.name)+'</span>'+
        '<span class="sz">'+esc(fmtSize(it.size))+'</span>'+
        '<a class="dl" href="'+BASE+'/download/'+it.id+'">İndir</a>';
    }
    ul.appendChild(li);
  });
  list.innerHTML=''; list.appendChild(ul);
}
function setCountdown(remaining){
  if(timer){clearInterval(timer);timer=null;}
  var el=document.getElementById('count');
  if(remaining==null){ el.textContent='Süresiz'; return; }
  deadline = Date.now() + remaining*1000;
  function tick(){
    var s = Math.max(0, Math.round((deadline-Date.now())/1000));
    var h=Math.floor(s/3600),m=Math.floor((s%3600)/60),ss=s%60;
    el.textContent = (h>0?h+':':'') + String(m).padStart(2,'0')+':'+String(ss).padStart(2,'0');
    el.className='count'+(s<=0?' over':(s<300?' warn':''));
    if(s<=0){clearInterval(timer);timer=null;el.textContent='Süre doldu';setTimeout(function(){location.reload();},1500);}
  }
  tick(); timer=setInterval(tick,1000);
}
function load(parent){
  var u = BASE + '/list' + (parent!=null ? '?parent='+encodeURIComponent(parent) : '');
  fetch(u,{credentials:'same-origin'}).then(function(r){
    if(r.status===403||r.status===404){showAuth();return null;}
    return r.json();
  }).then(function(d){ if(d&&d.ok) render(d); });
}
function showAuth(){
  document.getElementById('view').classList.add('hidden');
  document.getElementById('auth').classList.remove('hidden');
}
document.getElementById('f').addEventListener('submit',function(ev){
  ev.preventDefault();
  var b=document.getElementById('b'), e=document.getElementById('e');
  e.textContent=''; b.disabled=true;
  fetch(BASE+'/unlock',{method:'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.getElementById('pw').value})})
  .then(function(r){return r.text().then(function(t){var d=null;try{d=JSON.parse(t);}catch(x){}return {ok:r.ok,status:r.status,d:d};});})
  .then(function(res){
    b.disabled=false;
    if(res.ok&&res.d&&res.d.ok){ render(res.d); }
    else { e.textContent=(res.d&&res.d.detail)||'Şifre hatalı'; }
  }).catch(function(){ b.disabled=false; e.textContent='Bağlantı hatası'; });
});
// Çerez varsa doğrudan listeyi dene (şifre tekrar istenmesin)
load(null);
</script></body></html>"""
