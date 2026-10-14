"""Endüstriyel Tasarım: projeler → çizim / montaj çizimi ağacı (parent_id ile alt çizimler) → her çizimin sürüm
geçmişi. Her yeni dosya yüklemesi yeni bir sürümdür; eski sürümler (dosya + açıklama) geçmişte kalır ve görüntülenebilir.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import auth, db
from ..files import save_upload

router = APIRouter(prefix='/api/design')
design_user = auth.require_module('design')


class ProjectIn(BaseModel):
    name: str
    description: Optional[str] = None


class DrawingIn(BaseModel):
    name: str
    kind: str = 'drawing'          # 'assembly' (montaj) | 'drawing' | 'part'
    parent_id: Optional[int] = None


class RenameIn(BaseModel):
    name: str


class ProductLinkIn(BaseModel):
    product_id: Optional[int] = None


class StepLinkIn(BaseModel):
    mesh_key: str
    mesh_name: Optional[str] = None
    product_id: Optional[int] = None   # None → eşleşmeyi kaldır


class CopyIn(BaseModel):
    target_project_id: Optional[int] = None
    target_parent_id: Optional[int] = None


@router.get('/projects')
def projects(user=Depends(design_user), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT p.*, u.full_name AS created_by_name,
                  (SELECT COUNT(*) FROM design_drawings d WHERE d.project_id = p.id) AS drawing_count,
                  (SELECT v.id FROM design_drawing_versions v JOIN design_drawings d2 ON d2.id = v.drawing_id
                    WHERE d2.project_id = p.id AND (lower(v.file_name) LIKE '%.png' OR lower(v.file_name) LIKE '%.jpg'
                      OR lower(v.file_name) LIKE '%.jpeg' OR lower(v.file_name) LIKE '%.webp')
                    ORDER BY v.created_at DESC LIMIT 1) AS thumb_vid
           FROM design_projects p LEFT JOIN users u ON u.id = p.created_by
           WHERE p.archived = 0 ORDER BY p.id DESC'''))


@router.post('/projects')
def create_project(body: ProjectIn, user=Depends(design_user), conn=db.DB):
    name = (body.name or '').strip()[:200]
    if not name:
        raise HTTPException(400, 'Proje adı girin')
    cur = conn.execute('INSERT INTO design_projects (name, description, created_by, created_at) VALUES (?,?,?,?)',
                       (name, (body.description or '').strip() or None, user['id'], db.now()))
    db.audit(conn, user['id'], 'Tasarım projesi oluşturdu', 'design_project', cur.lastrowid, name)
    return {'id': cur.lastrowid}


def _tree(conn, pid):
    """Projenin çizim ağacı: her düğümde güncel sürüm + sürüm sayısı; parent_id ile iç içe."""
    drawings = db.rows(conn.execute(
        '''SELECT d.*, u.full_name AS created_by_name, pr.code AS product_code, pr.name AS product_name,
                  (SELECT COUNT(*) FROM design_step_links l WHERE l.drawing_id = d.id) AS link_count,
                  (SELECT COUNT(*) FROM design_drawing_versions v WHERE v.drawing_id = d.id) AS version_count,
                  (SELECT COUNT(*) FROM design_drawing_notes n WHERE n.drawing_id = d.id) AS note_count,
                  (SELECT COUNT(*) FROM design_production_parts pp WHERE pp.drawing_id = d.id) AS prod_count
           FROM design_drawings d LEFT JOIN users u ON u.id = d.created_by LEFT JOIN products pr ON pr.id = d.product_id
           WHERE d.project_id = ? ORDER BY d.sort, d.id''', (pid,)))
    cur = {}
    for v in db.rows(conn.execute(
            '''SELECT v.*, u.full_name AS uploaded_by_name FROM design_drawing_versions v
               LEFT JOIN users u ON u.id = v.uploaded_by
               WHERE v.drawing_id IN (SELECT id FROM design_drawings WHERE project_id = ?)
               ORDER BY v.drawing_id, v.version''', (pid,))):
        cur[v['drawing_id']] = v   # son sürüm (version'a göre artan sırada; sonuncusu kalır)
    by_parent = {}
    for d in drawings:
        d['current'] = cur.get(d['id'])
        d['children'] = []
        by_parent.setdefault(d['parent_id'], []).append(d)
    def build(pid_):
        out = by_parent.get(pid_, [])
        for d in out:
            d['children'] = build(d['id'])
        return out
    return build(None)


@router.get('/projects/{pid}')
def project_detail(pid: int, user=Depends(design_user), conn=db.DB):
    p = db.row(conn.execute('SELECT p.*, u.full_name AS created_by_name FROM design_projects p LEFT JOIN users u ON u.id = p.created_by WHERE p.id = ?', (pid,)))
    if not p:
        raise HTTPException(404, 'Proje bulunamadı')
    p['tree'] = _tree(conn, pid)
    return p


@router.put('/projects/{pid}')
def edit_project(pid: int, body: ProjectIn, user=Depends(design_user), conn=db.DB):
    if not conn.execute('UPDATE design_projects SET name = ?, description = ? WHERE id = ?',
                        ((body.name or '').strip()[:200], (body.description or '').strip() or None, pid)).rowcount:
        raise HTTPException(404, 'Proje bulunamadı')
    return {'ok': True}


@router.delete('/projects/{pid}')
def delete_project(pid: int, user=Depends(design_user), conn=db.DB):
    conn.execute('UPDATE design_projects SET archived = 1 WHERE id = ?', (pid,))
    db.audit(conn, user['id'], 'Tasarım projesi arşivledi', 'design_project', pid, '')
    return {'ok': True}


@router.post('/projects/{pid}/drawings')
def add_drawing(pid: int, body: DrawingIn, user=Depends(design_user), conn=db.DB):
    if not db.row(conn.execute('SELECT id FROM design_projects WHERE id = ?', (pid,))):
        raise HTTPException(404, 'Proje bulunamadı')
    name = (body.name or '').strip()[:200]
    if not name:
        raise HTTPException(400, 'Çizim adı girin')
    parent = body.parent_id
    if parent and not db.row(conn.execute('SELECT id FROM design_drawings WHERE id = ? AND project_id = ?', (parent, pid))):
        raise HTTPException(400, 'Üst çizim bulunamadı')
    kind = body.kind if body.kind in ('assembly', 'drawing', 'part') else 'drawing'
    nxt = (conn.execute('SELECT MAX(sort) FROM design_drawings WHERE project_id = ? AND parent_id IS ?', (pid, parent)).fetchone()[0] or 0) + 1
    cur = conn.execute('INSERT INTO design_drawings (project_id, parent_id, name, kind, sort, created_by, created_at) VALUES (?,?,?,?,?,?,?)',
                       (pid, parent, name, kind, nxt, user['id'], db.now()))
    return {'id': cur.lastrowid}


@router.put('/drawings/{did}')
def rename_drawing(did: int, body: RenameIn, user=Depends(design_user), conn=db.DB):
    if not conn.execute('UPDATE design_drawings SET name = ? WHERE id = ?', ((body.name or '').strip()[:200], did)).rowcount:
        raise HTTPException(404, 'Çizim bulunamadı')
    return {'ok': True}


def _request_or_delete(conn, user, kind, target_id, label, project_id, do_delete):
    """Master doğrudan siler; diğerleri silme talebi oluşturur (Master onayına)."""
    if user.get('master'):
        do_delete()
        db.audit(conn, user['id'], f'{kind} silindi (master)', 'design', target_id, label or '')
        return {'ok': True, 'deleted': True}
    if not conn.execute("SELECT 1 FROM design_delete_requests WHERE kind=? AND target_id=? AND status='BEKLIYOR'", (kind, target_id)).fetchone():
        conn.execute('INSERT INTO design_delete_requests (kind, target_id, label, project_id, requested_by, created_at) VALUES (?,?,?,?,?,?)',
                     (kind, target_id, label, project_id, user['id'], db.now()))
    return {'ok': True, 'requested': True}


@router.delete('/drawings/{did}')
def delete_drawing(did: int, user=Depends(design_user), conn=db.DB):
    d = db.row(conn.execute('SELECT * FROM design_drawings WHERE id = ?', (did,)))
    if not d:
        raise HTTPException(404, 'Çizim bulunamadı')
    return _request_or_delete(conn, user, 'drawing', did, d['name'], d['project_id'],
                              lambda: conn.execute('DELETE FROM design_drawings WHERE id = ?', (did,)))


@router.get('/drawings/{did}/versions')
def versions(did: int, user=Depends(design_user), conn=db.DB):
    if not db.row(conn.execute('SELECT id FROM design_drawings WHERE id = ?', (did,))):
        raise HTTPException(404, 'Çizim bulunamadı')
    return db.rows(conn.execute(
        '''SELECT v.id, v.version, v.file_name, v.file_path, v.note, v.created_at, u.full_name AS uploaded_by_name
           FROM design_drawing_versions v LEFT JOIN users u ON u.id = v.uploaded_by
           WHERE v.drawing_id = ? ORDER BY v.version DESC''', (did,)))


@router.post('/drawings/{did}/version')
async def add_version(did: int, file: UploadFile = File(...), note: str = Form(None), user=Depends(design_user)):
    with db.connect() as conn:
        d = db.row(conn.execute('SELECT * FROM design_drawings WHERE id = ?', (did,)))
        if not d:
            raise HTTPException(404, 'Çizim bulunamadı')
    path = await save_upload('design', file)
    with db.connect() as conn:
        nxt = (conn.execute('SELECT MAX(version) FROM design_drawing_versions WHERE drawing_id = ?', (did,)).fetchone()[0] or 0) + 1
        conn.execute('''INSERT INTO design_drawing_versions (drawing_id, version, file_path, file_name, note, uploaded_by, created_at)
                        VALUES (?,?,?,?,?,?,?)''', (did, nxt, path, (file.filename or 'çizim')[:200], (note or '').strip() or None, user['id'], db.now()))
        db.audit(conn, user['id'], f'Çizim sürümü yüklendi (v{nxt})', 'design_drawing', did, (file.filename or ''))
    return {'ok': True, 'version': nxt}


# ---------- Kopyalama: bir çizimi / montajı (tüm alt parçaları ve sürüm geçmişiyle) başka yere kopyala ----------
def _descendants(conn, did):
    seen, stack = set(), [did]
    while stack:
        cur = stack.pop(); seen.add(cur)
        stack += [r[0] for r in conn.execute('SELECT id FROM design_drawings WHERE parent_id = ?', (cur,))]
    return seen


def _clone(conn, src_id, tproj, nparent, uid, now):
    s = db.row(conn.execute('SELECT * FROM design_drawings WHERE id = ?', (src_id,)))
    nxt = (conn.execute('SELECT MAX(sort) FROM design_drawings WHERE project_id = ? AND parent_id IS ?', (tproj, nparent)).fetchone()[0] or 0) + 1
    nid = conn.execute('INSERT INTO design_drawings (project_id, parent_id, name, kind, sort, created_by, created_at) VALUES (?,?,?,?,?,?,?)',
                       (tproj, nparent, s['name'], s['kind'], nxt, uid, now)).lastrowid
    for v in db.rows(conn.execute('SELECT * FROM design_drawing_versions WHERE drawing_id = ? ORDER BY version', (src_id,))):
        conn.execute('''INSERT INTO design_drawing_versions (drawing_id, version, file_path, file_name, size, note, uploaded_by, created_at)
                        VALUES (?,?,?,?,?,?,?,?)''', (nid, v['version'], v['file_path'], v['file_name'], v['size'], v['note'], v['uploaded_by'], v['created_at']))
    for ch in conn.execute('SELECT id FROM design_drawings WHERE parent_id = ? ORDER BY sort, id', (src_id,)).fetchall():
        _clone(conn, ch[0], tproj, nid, uid, now)
    return nid


@router.post('/drawings/{did}/copy')
def copy_drawing(did: int, body: CopyIn, user=Depends(design_user), conn=db.DB):
    """Çizimi/montajı alt parçaları ve tüm sürüm geçmişiyle hedef projeye/montaja kopyalar."""
    src = db.row(conn.execute('SELECT * FROM design_drawings WHERE id = ?', (did,)))
    if not src:
        raise HTTPException(404, 'Çizim bulunamadı')
    tproj = body.target_project_id or src['project_id']
    if not db.row(conn.execute('SELECT id FROM design_projects WHERE id = ?', (tproj,))):
        raise HTTPException(400, 'Hedef proje bulunamadı')
    tparent = body.target_parent_id
    if tparent is not None:
        if not db.row(conn.execute('SELECT id FROM design_drawings WHERE id = ? AND project_id = ?', (tparent, tproj))):
            raise HTTPException(400, 'Hedef montaj bulunamadı')
        if tparent in _descendants(conn, did):
            raise HTTPException(400, 'Bir çizim kendi içine kopyalanamaz')
    nid = _clone(conn, did, tproj, tparent, user['id'], db.now())
    db.audit(conn, user['id'], 'Çizim kopyalandı', 'design_drawing', nid, src['name'])
    return {'id': nid}


# ---------- Notlar: her çizime/montaja farklı zamanlarda not ----------
class NoteIn(BaseModel):
    note: str


@router.get('/drawings/{did}/notes')
def list_notes(did: int, user=Depends(design_user), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT n.id, n.note, n.created_at, u.full_name AS by_name FROM design_drawing_notes n
           LEFT JOIN users u ON u.id = n.created_by WHERE n.drawing_id = ? ORDER BY n.id DESC''', (did,)))


@router.post('/drawings/{did}/notes')
def add_note(did: int, body: NoteIn, user=Depends(design_user), conn=db.DB):
    if not db.row(conn.execute('SELECT id FROM design_drawings WHERE id = ?', (did,))):
        raise HTTPException(404, 'Çizim bulunamadı')
    note = (body.note or '').strip()[:2000]
    if not note:
        raise HTTPException(400, 'Not girin')
    cur = conn.execute('INSERT INTO design_drawing_notes (drawing_id, note, created_by, created_at) VALUES (?,?,?,?)',
                       (did, note, user['id'], db.now()))
    return {'id': cur.lastrowid}


@router.delete('/notes/{nid}')
def delete_note(nid: int, user=Depends(design_user), conn=db.DB):
    conn.execute('DELETE FROM design_drawing_notes WHERE id = ?', (nid,))
    return {'ok': True}


# ---------- Üretim parçaları: montaja üretim aşaması için G-code dosyaları ----------
class ProdPartIn(BaseModel):
    name: str
    qty: Optional[float] = None
    note: Optional[str] = None


# ---------- Eşleştirme: montaj/çizim ↔ mamul; STEP parçası ↔ yarı mamul (3B önizlemede seçilen parça)
def _drawing(conn, did):
    d = db.row(conn.execute('SELECT * FROM design_drawings WHERE id = ?', (did,)))
    if not d:
        raise HTTPException(404, 'Çizim bulunamadı')
    return d


@router.put('/drawings/{did}/product')
def set_drawing_product(did: int, body: ProductLinkIn, user=Depends(design_user), conn=db.DB):
    """Montaj/çizimi Ürün Yönetimi'ndeki mamul (ya da yarı mamul) ile eşleştir; None → kaldır."""
    d = _drawing(conn, did)
    name = None
    if body.product_id is not None:
        p = db.row(conn.execute('SELECT id, code, name, type FROM products WHERE id = ?', (body.product_id,)))
        if not p:
            raise HTTPException(404, 'Ürün bulunamadı')
        name = f"{p['code']} — {p['name']}"
    conn.execute('UPDATE design_drawings SET product_id = ? WHERE id = ?', (body.product_id, did))
    db.audit(conn, user['id'], 'Çizimi ürünle eşleştirdi' if body.product_id else 'Çizim–ürün eşleşmesini kaldırdı', 'design_drawing', did, name or d['name'])
    return {'ok': True, 'product_id': body.product_id, 'product_label': name}


@router.get('/drawings/{did}/step-links')
def step_links(did: int, user=Depends(design_user), conn=db.DB):
    """STEP parça eşleşmeleri + seçim adayları (çizim bir mamule bağlıysa onun ağacındaki yarı mamuller, değilse tüm yarı mamuller)."""
    from .. import bom
    d = _drawing(conn, did)
    links = db.rows(conn.execute('''SELECT l.mesh_key, l.mesh_name, l.product_id, p.code AS product_code, p.name AS product_name
                                    FROM design_step_links l JOIN products p ON p.id = l.product_id WHERE l.drawing_id = ? ORDER BY l.id''', (did,)))
    cands = []
    if d['product_id']:
        def walk(n):
            if n['id'] != d['product_id']:
                cands.append({'id': n['id'], 'code': n['code'], 'name': n['name'], 'type': n['type'], 'section': n.get('section')})
            for c in n.get('children', []):
                walk(c)
        try:
            walk(bom.tree(conn, d['product_id']))
        except Exception:   # noqa: BLE001
            pass
    if not cands:
        cands = db.rows(conn.execute("SELECT id, code, name, type, NULL AS section FROM products WHERE active = 1 AND type IN ('YARI_MAMUL','YEDEK_PARCA') ORDER BY code"))
    seen, uniq = set(), []
    for c in cands:
        if c['id'] not in seen:
            seen.add(c['id']); uniq.append(c)
    mamul = db.row(conn.execute('SELECT id, code, name FROM products WHERE id = ?', (d['product_id'],))) if d['product_id'] else None
    return {'links': links, 'candidates': uniq, 'product': mamul,
            'mamuls': db.rows(conn.execute("SELECT id, code, name FROM products WHERE active = 1 AND type = 'MAMUL' ORDER BY name"))}


@router.put('/drawings/{did}/step-links')
def set_step_link(did: int, body: StepLinkIn, user=Depends(design_user), conn=db.DB):
    d = _drawing(conn, did)
    key = (body.mesh_key or '').strip()[:200]
    if not key:
        raise HTTPException(400, 'Parça anahtarı gerekli')
    if body.product_id is None:
        conn.execute('DELETE FROM design_step_links WHERE drawing_id = ? AND mesh_key = ?', (did, key))
        db.audit(conn, user['id'], 'STEP parça eşleşmesini kaldırdı', 'design_drawing', did, f"{d['name']} · {body.mesh_name or key}")
        return {'ok': True, 'linked': False}
    p = db.row(conn.execute('SELECT id, code, name FROM products WHERE id = ?', (body.product_id,)))
    if not p:
        raise HTTPException(404, 'Ürün bulunamadı')
    conn.execute('''INSERT INTO design_step_links (drawing_id, mesh_key, mesh_name, product_id, created_by, created_at) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(drawing_id, mesh_key) DO UPDATE SET mesh_name = excluded.mesh_name, product_id = excluded.product_id,
                    created_by = excluded.created_by, created_at = excluded.created_at''',
                 (did, key, (body.mesh_name or '')[:200] or None, p['id'], user['id'], db.now()))
    db.audit(conn, user['id'], 'STEP parçasını ürünle eşleştirdi', 'design_drawing', did, f"{body.mesh_name or key} → {p['code']}")
    return {'ok': True, 'linked': True, 'product_code': p['code'], 'product_name': p['name']}


@router.get('/drawings/{did}/parts')
def list_parts(did: int, user=Depends(design_user), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT p.id, p.name, p.qty, p.note, p.file_path, p.file_name, p.created_at, u.full_name AS by_name FROM design_production_parts p
           LEFT JOIN users u ON u.id = p.created_by WHERE p.drawing_id = ? ORDER BY p.sort, p.id''', (did,)))


@router.post('/drawings/{did}/parts')
async def add_part(did: int, file: UploadFile = File(...), name: str = Form(None), qty: str = Form(None), note: str = Form(None), user=Depends(design_user)):
    with db.connect() as conn:
        if not db.row(conn.execute('SELECT id FROM design_drawings WHERE id = ?', (did,))):
            raise HTTPException(404, 'Çizim bulunamadı')
    path = await save_upload('design', file)
    nm = (name or file.filename or 'parça').strip()[:200]
    try:
        q = float(qty) if qty not in (None, '') else None
    except (TypeError, ValueError):
        q = None
    with db.connect() as conn:
        nxt = (conn.execute('SELECT MAX(sort) FROM design_production_parts WHERE drawing_id = ?', (did,)).fetchone()[0] or 0) + 1
        cur = conn.execute('''INSERT INTO design_production_parts (drawing_id, name, qty, note, file_path, file_name, sort, created_by, created_at)
                              VALUES (?,?,?,?,?,?,?,?,?)''',
                           (did, nm, q, (note or '').strip() or None, path, (file.filename or nm)[:200], nxt, user['id'], db.now()))
        db.audit(conn, user['id'], 'Üretim parçası (G-code) eklendi', 'design_drawing', did, nm)
    return {'id': cur.lastrowid}


@router.put('/parts/{part_id}')
def edit_part(part_id: int, body: ProdPartIn, user=Depends(design_user), conn=db.DB):
    name = (body.name or '').strip()[:200]
    if not name:
        raise HTTPException(400, 'Parça adı girin')
    if not conn.execute('UPDATE design_production_parts SET name = ?, qty = ?, note = ? WHERE id = ?',
                        (name, body.qty, (body.note or '').strip() or None, part_id)).rowcount:
        raise HTTPException(404, 'Parça bulunamadı')
    return {'ok': True}


@router.delete('/parts/{part_id}')
def delete_part(part_id: int, user=Depends(design_user), conn=db.DB):
    pp = db.row(conn.execute('SELECT p.*, d.project_id FROM design_production_parts p JOIN design_drawings d ON d.id = p.drawing_id WHERE p.id = ?', (part_id,)))
    if not pp:
        raise HTTPException(404, 'Parça bulunamadı')
    return _request_or_delete(conn, user, 'part', part_id, pp['name'], pp['project_id'],
                              lambda: conn.execute('DELETE FROM design_production_parts WHERE id = ?', (part_id,)))


# ---------- Dosya servisi: önizleme tüm tasarımcılara, indirme (dl=1) yalnızca Master ----------
@router.get('/file')
def design_file(v: int = None, p: int = None, dl: int = 0, user=Depends(design_user), conn=db.DB):
    from fastapi.responses import FileResponse
    from .. import config
    row = None
    if v:
        row = db.row(conn.execute('SELECT file_path, file_name FROM design_drawing_versions WHERE id = ?', (v,)))
    elif p:
        row = db.row(conn.execute('SELECT file_path, file_name FROM design_production_parts WHERE id = ?', (p,)))
    if not row or not row['file_path']:
        raise HTTPException(404, 'Dosya yok')
    if dl and not user.get('master'):
        raise HTTPException(403, 'İndirme yalnızca Master kullanıcısına açıktır')
    path = config.UPLOAD_DIR / row['file_path']
    if not path.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return FileResponse(path, filename=row['file_name'], content_disposition_type='attachment' if dl else 'inline')


# ---------- Silme talepleri (yalnızca Master görür/karara bağlar) ----------
def _master_only(user=Depends(design_user)):
    if not user.get('master'):
        raise HTTPException(403, 'Yalnızca Master')
    return user


@router.get('/delete-requests')
def delete_requests(user=Depends(_master_only), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT r.*, u.full_name AS requested_by_name, p.name AS project_name
           FROM design_delete_requests r LEFT JOIN users u ON u.id = r.requested_by
           LEFT JOIN design_projects p ON p.id = r.project_id
           WHERE r.status = 'BEKLIYOR' ORDER BY r.id DESC'''))


@router.post('/delete-requests/{rid}/approve')
def approve_delete(rid: int, user=Depends(_master_only), conn=db.DB):
    r = db.row(conn.execute("SELECT * FROM design_delete_requests WHERE id = ? AND status = 'BEKLIYOR'", (rid,)))
    if not r:
        raise HTTPException(404, 'Talep bulunamadı')
    if r['kind'] == 'drawing':
        conn.execute('DELETE FROM design_drawings WHERE id = ?', (r['target_id'],))
    elif r['kind'] == 'part':
        conn.execute('DELETE FROM design_production_parts WHERE id = ?', (r['target_id'],))
    conn.execute("UPDATE design_delete_requests SET status = 'ONAYLANDI' WHERE id = ?", (rid,))
    db.audit(conn, user['id'], 'Silme talebi onayladı', 'design', r['target_id'], r['label'] or '')
    return {'ok': True}


@router.post('/delete-requests/{rid}/reject')
def reject_delete(rid: int, user=Depends(_master_only), conn=db.DB):
    conn.execute("UPDATE design_delete_requests SET status = 'REDDEDILDI' WHERE id = ? AND status = 'BEKLIYOR'", (rid,))
    return {'ok': True}
