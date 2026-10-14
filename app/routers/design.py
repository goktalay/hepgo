"""Endüstriyel Tasarım: projeler → çizim / montaj çizimi ağacı (parent_id ile alt çizimler) → her çizimin sürüm
geçmişi. Her yeni dosya yüklemesi yeni bir sürümdür; eski sürümler (dosya + açıklama) geçmişte kalır ve görüntülenebilir.
"""
import json
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
    product_id: Optional[int] = None   # None → parçanın tüm eşleşmelerini kaldır
    mode: str = 'replace'              # replace: parçanın eşleşmesi bu ürün olur · add: ek ürün (L15 → L15A + L15B) · remove: yalnız bu ürünü çıkar


class StepTreeIn(BaseModel):
    """STEP parça ağacı düzenlemesi: groups [{key, name, parent}], parents {key: parentKey|null}, names {key: ad}; None/boş → sıfırla."""
    tree: Optional[dict] = None


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
        vid = conn.execute('SELECT id FROM design_drawing_versions WHERE drawing_id = ? AND version = ?', (did, nxt)).fetchone()[0]
        db.audit(conn, user['id'], f'Çizim sürümü yüklendi (v{nxt})', 'design_drawing', did, (file.filename or ''))
    return {'ok': True, 'version': nxt, 'id': vid}


@router.post('/versions/{vid}/thumb')
async def set_version_thumb(vid: int, file: UploadFile = File(...), user=Depends(design_user)):
    """STEP sürümünün 3B önizleme resmi (PNG; tarayıcıda WebGL ile çekilir, montaj kartında gösterilir)."""
    with db.connect() as conn:
        v = db.row(conn.execute('SELECT id, drawing_id FROM design_drawing_versions WHERE id = ?', (vid,)))
        if not v:
            raise HTTPException(404, 'Sürüm bulunamadı')
    path = await save_upload('design', file)
    with db.connect() as conn:
        conn.execute('UPDATE design_drawing_versions SET thumb_path = ? WHERE id = ?', (path, vid))
    return {'ok': True, 'thumb': f'/api/design/file?t={vid}'}


class SpecsIn(BaseModel):
    specs: Optional[dict] = None


SPEC_KEYS = ('mtow_g', 'payload_g', 'empty_g', 'wingspan_mm', 'length_mm', 'cruise_kmh', 'endurance_min', 'battery', 'notes')


@router.put('/drawings/{did}/specs')
def set_specs(did: int, body: SpecsIn, user=Depends(design_user), conn=db.DB):
    """Montaj genel bilgileri (kalkış ağırlığı, faydalı yük, kanat açıklığı…) — detay sayfasının üst kartı."""
    d = _drawing(conn, did)
    sp = {}
    for k in SPEC_KEYS:
        v = (body.specs or {}).get(k)
        if v is None or v == '':
            continue
        if k in ('battery', 'notes'):
            sp[k] = str(v).strip()[:500]
        else:
            try:
                sp[k] = float(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f'{k}: sayı girin')
    conn.execute('UPDATE design_drawings SET specs = ? WHERE id = ?', (json.dumps(sp, ensure_ascii=False) if sp else None, did))
    db.audit(conn, user['id'], 'Montaj bilgilerini güncelledi', 'design_drawing', did, d['name'])
    return {'ok': True, 'specs': sp}


@router.get('/drawings/{did}')
def drawing_detail(did: int, user=Depends(design_user), conn=db.DB):
    """Montaj detay sayfası: çizim, güncel sürüm, proje, mamul, bilgiler, eşleşme istatistikleri (basılan parça ağırlığı, süre)."""
    d = dict(_drawing(conn, did))
    proj = db.row(conn.execute('SELECT id, name FROM design_projects WHERE id = ?', (d['project_id'],)))
    cur = db.row(conn.execute('SELECT id, version, file_name, size, note, created_at, thumb_path FROM design_drawing_versions WHERE drawing_id = ? ORDER BY version DESC LIMIT 1', (did,)))
    mamul = db.row(conn.execute('SELECT id, code, name, weight_g FROM products WHERE id = ?', (d['product_id'],))) if d['product_id'] else None
    links = db.rows(conn.execute('''SELECT l.mesh_key, l.mesh_name, p.id, p.code, p.name, p.weight_g, p.gcode_meta, p.print_minutes
                                    FROM design_step_links l JOIN products p ON p.id = l.product_id WHERE l.drawing_id = ?''', (did,)))
    weight = 0.0; minutes = 0.0; weighed = 0
    for l in links:
        w = l['weight_g']
        if not w and l['gcode_meta']:
            try:
                w = (json.loads(l['gcode_meta']) or {}).get('filament_g')
            except (TypeError, ValueError):
                w = None
        if w:
            weight += float(w); weighed += 1
        if l['print_minutes']:
            minutes += float(l['print_minutes'])
    try:
        specs = json.loads(d['specs']) if d['specs'] else {}
    except (TypeError, ValueError):
        specs = {}
    counts = db.row(conn.execute('''SELECT (SELECT COUNT(*) FROM design_drawing_versions WHERE drawing_id = ?) AS versions,
                                       (SELECT COUNT(*) FROM design_drawing_notes WHERE drawing_id = ?) AS notes,
                                       (SELECT COUNT(*) FROM design_production_parts WHERE drawing_id = ?) AS parts''', (did, did, did)))
    return {'id': d['id'], 'name': d['name'], 'kind': d['kind'], 'project': proj, 'current': cur, 'product': mamul, 'specs': specs,
            'version_count': counts['versions'], 'note_count': counts['notes'], 'prod_count': counts['parts'],
            'stats': {'linked': len(links), 'weighed': weighed, 'printed_weight_g': round(weight, 1), 'print_minutes': round(minutes)},
            'mamuls': db.rows(conn.execute("SELECT id, code, name FROM products WHERE active = 1 AND type = 'MAMUL' ORDER BY name"))}


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
    links = db.rows(conn.execute('''SELECT l.mesh_key, l.mesh_name, l.product_id, p.code AS product_code, p.name AS product_name, p.gcode_preview
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
    if not cands and not d['product_id']:   # mamul seçiliyse yalnız onun ağacı (boşsa boş); seçili değilse tüm yarı mamuller
        cands = db.rows(conn.execute("SELECT id, code, name, type, NULL AS section FROM products WHERE active = 1 AND type IN ('YARI_MAMUL','YEDEK_PARCA') ORDER BY code"))
    seen, uniq = set(), []
    for c in cands:
        if c['id'] not in seen:
            seen.add(c['id']); uniq.append(dict(c))
    if uniq:   # adayların G-code 3B önizleme yolu (karşılaştırma penceresi: seçili STEP parçası ↔ ürünün basılan geometrisi)
        ids = [c['id'] for c in uniq]
        prev = {r['id']: r for r in db.rows(conn.execute(f"SELECT id, gcode_preview, orderable FROM products WHERE id IN ({','.join('?' * len(ids))})", ids))}
        for c in uniq:   # orderable: sipariş verilebilir yarı mamul → birden çok STEP parçasıyla eşleşebilir (ör. aynı vida/klips)
            c['gcode_preview'] = (prev.get(c['id']) or {}).get('gcode_preview')
            c['orderable'] = bool((prev.get(c['id']) or {}).get('orderable'))
    mamul = db.row(conn.execute('SELECT id, code, name FROM products WHERE id = ?', (d['product_id'],))) if d['product_id'] else None
    try:
        tree = json.loads(d['step_tree']) if d['step_tree'] else None
    except (TypeError, ValueError):
        tree = None
    cur = db.row(conn.execute('SELECT id, version, file_name FROM design_drawing_versions WHERE drawing_id = ? ORDER BY version DESC LIMIT 1', (did,)))
    return {'links': links, 'candidates': uniq, 'product': mamul, 'tree': tree,
            'drawing': {'id': d['id'], 'name': d['name'], 'project_id': d['project_id'], 'kind': d['kind'], 'current': cur},
            'mamuls': db.rows(conn.execute("SELECT id, code, name FROM products WHERE active = 1 AND type = 'MAMUL' ORDER BY name"))}


ENGINE_TYPES = ('DLE-222', 'HE-280')   # static/js/engine3d.js ile aynı


def tree_in_engine(e):
    """Motor yerleşimi: {type, node, nose, up, offset[3], prop} — bilinmeyen tür → yok."""
    if not isinstance(e, dict) or e.get('type') not in ENGINE_TYPES:
        return None
    try:
        off = [float(x) for x in (e.get('offset') or [0, 0, 0])][:3]
    except (TypeError, ValueError):
        off = [0, 0, 0]
    ax = lambda v, d: v if isinstance(v, str) and len(v) == 2 and v[0] in '+-' and v[1] in 'xyz' else d
    try:
        yaw = float(e.get('yaw') or 0)
    except (TypeError, ValueError):
        yaw = 0.0
    return {'type': e['type'], 'node': (str(e['node'])[:120] if e.get('node') else None), 'nose': ax(e.get('nose'), '+x'), 'up': ax(e.get('up'), '+z'),
            'yaw': yaw, 'offset': (off + [0, 0, 0])[:3], 'prop': bool(e.get('prop'))}


@router.put('/drawings/{did}/step-tree')
def set_step_tree(did: int, body: StepTreeIn, user=Depends(design_user), conn=db.DB):
    """STEP ağacı düzenlemelerini (alt kırılımlar, taşımalar, adlar) tek seferde kaydet; dosya değişmez, düzen her açılışta uygulanır."""
    d = _drawing(conn, did)
    tree = body.tree or None
    if tree:
        groups = [g for g in (tree.get('groups') or []) if isinstance(g, dict) and g.get('key') and str(g.get('name') or '').strip()]
        tree = {'groups': [{'key': str(g['key'])[:120], 'name': str(g['name']).strip()[:200], 'parent': (str(g['parent'])[:120] if g.get('parent') else None)} for g in groups][:500],
                'parents': {str(k)[:120]: (str(v)[:120] if v else None) for k, v in (tree.get('parents') or {}).items()},
                'names': {str(k)[:120]: str(v).strip()[:200] for k, v in (tree.get('names') or {}).items() if str(v or '').strip()},
                'hidden': [str(k)[:120] for k in (tree.get('hidden') or []) if k][:2000]}   # ağaçtan/modelden gizlenen parça ve kırılımlar
        eng = tree_in_engine(body.tree.get('engine'))
        if eng:
            tree['engine'] = eng
        if not tree['groups'] and not tree['parents'] and not tree['names'] and not tree['hidden'] and not eng:
            tree = None
    conn.execute('UPDATE design_drawings SET step_tree = ? WHERE id = ?', (json.dumps(tree, ensure_ascii=False) if tree else None, did))
    db.audit(conn, user['id'], 'STEP parça ağacını düzenledi', 'design_drawing', did,
             f"{d['name']} · {len(tree['groups'])} kırılım, {len(tree['parents'])} taşıma, {len(tree['names'])} ad, {len(tree['hidden'])} gizli" if tree else f"{d['name']} · sıfırlandı")
    return {'ok': True, 'tree': tree}


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
    if body.mode == 'remove':
        conn.execute('DELETE FROM design_step_links WHERE drawing_id = ? AND mesh_key = ? AND product_id = ?', (did, key, p['id']))
        db.audit(conn, user['id'], 'STEP parça eşleşmesini kaldırdı', 'design_drawing', did, f"{body.mesh_name or key} ✕ {p['code']}")
        return {'ok': True, 'linked': bool(conn.execute('SELECT 1 FROM design_step_links WHERE drawing_id = ? AND mesh_key = ?', (did, key)).fetchone())}
    if body.mode != 'add':   # replace: parçanın önceki eşleşmeleri gider
        conn.execute('DELETE FROM design_step_links WHERE drawing_id = ? AND mesh_key = ?', (did, key))
    conn.execute('''INSERT INTO design_step_links (drawing_id, mesh_key, mesh_name, product_id, created_by, created_at) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(drawing_id, mesh_key, product_id) DO UPDATE SET mesh_name = excluded.mesh_name,
                    created_by = excluded.created_by, created_at = excluded.created_at''',
                 (did, key, (body.mesh_name or '')[:200] or None, p['id'], user['id'], db.now()))
    db.audit(conn, user['id'], 'STEP parçasını ürünle eşleştirdi', 'design_drawing', did, f"{body.mesh_name or key} → {p['code']}")
    return {'ok': True, 'linked': True, 'product_code': p['code'], 'product_name': p['name']}


# ---------- 3B CFD (OpenFOAM) ----------
@router.get('/cfd/status')
def cfd_status(user=Depends(design_user)):
    from .. import cfd
    return {'available': cfd.available(), 'openfoam_dir': str(cfd.OPENFOAM_DIR), 'cores': cfd.cores(), 'resolutions': {k: v['label'] for k, v in cfd.RES.items()},
            'iters': {k: v['iters'] for k, v in cfd.RES.items()}}


@router.get('/drawings/{did}/cfd')
def cfd_list(did: int, user=Depends(design_user), conn=db.DB):
    _drawing(conn, did)
    rows = db.rows(conn.execute('''SELECT r.id, r.name, r.status, r.phase, r.iters, r.cells, r.params, r.geometry, r.result, r.error, r.created_at, r.started_at, r.finished_at,
                                          r.version_id, u.full_name AS created_by_name
                                   FROM design_cfd_runs r LEFT JOIN users u ON u.id = r.created_by WHERE r.drawing_id = ? ORDER BY r.id DESC LIMIT 50''', (did,)))
    for r in rows:
        for k in ('params', 'geometry', 'result'):
            try:
                r[k] = json.loads(r[k]) if r[k] else None
            except (TypeError, ValueError):
                r[k] = None
    return rows


@router.post('/drawings/{did}/cfd')
async def cfd_create(did: int, file: UploadFile = File(...), params: str = Form('{}'), user=Depends(design_user)):
    """Yeni analiz: STL (akış +x, yukarı +z, metre) + parametreler → durum dizini üretilir, kuyruğa alınır."""
    from .. import cfd, config as cfg
    if not cfd.available():
        raise HTTPException(503, 'OpenFOAM bu sunucuda kurulu değil (CAYMAZ_OPENFOAM_DIR)')
    try:
        p = json.loads(params or '{}')
    except ValueError:
        raise HTTPException(400, 'Parametreler okunamadı')
    with db.connect() as conn:
        d = _drawing(conn, did)
        active = conn.execute("SELECT COUNT(*) FROM design_cfd_runs WHERE status IN ('queued','running','cancelling')").fetchone()[0]
    if active >= 3:
        raise HTTPException(429, 'Kuyrukta zaten 3 analiz var; biri bitince yenisini başlatın')
    U = float(p.get('U') or 0)
    if not (0.5 <= U <= 200):
        raise HTTPException(400, 'Akış hızı 0,5–200 m/s olmalı')
    res = p.get('res') if p.get('res') in cfd.RES else 'coarse'
    cores = int(p.get('cores') or cfd.cores()); cores = max(1, min(cores, cfd.cores()))
    iters = int(p.get('iters') or cfd.RES[res]['iters']); iters = max(20, min(iters, 3000))
    prm = {'U': U, 'rho': float(p.get('rho') or 1.225), 'nu': float(p.get('nu') or 1.5e-5), 'res': res, 'cores': cores, 'iters': iters,
           'turb_intensity': float(p.get('turb_intensity') or 0.01), 'aoa': float(p.get('aoa') or 0), 'yaw': float(p.get('yaw') or 0), 'nose': p.get('nose') or '+x', 'up': p.get('up') or '+z',
           'scope': p.get('scope') or 'all', 'scope_name': (p.get('scope_name') or '')[:200]}
    with db.connect() as conn:
        cur = conn.execute('INSERT INTO design_cfd_runs (drawing_id, version_id, name, params, status, created_by, created_at) VALUES (?,?,?,?,?,?,?)',
                           (did, p.get('version_id'), (p.get('name') or f"{d['name']} · {U:g} m/s · {cfd.RES[res]['label']}")[:200], json.dumps(prm), 'preparing', user['id'], db.now()))
        run_id = cur.lastrowid
    case = cfd.CFD_DIR / str(run_id)
    try:
        (case / 'constant' / 'triSurface').mkdir(parents=True, exist_ok=True)
        stl = case / 'constant' / 'triSurface' / 'body.stl'
        with open(stl, 'wb') as f:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        tris = cfd.read_stl(stl)
        if len(tris) < 4:
            raise ValueError('STL boş')
        geo = cfd.geometry(tris)
        if max(geo['size']) > 50 or max(geo['size']) < 0.005:
            raise ValueError(f"Gövde boyutu {max(geo['size']):.3f} m — birim/ölçek hatalı görünüyor (metre bekleniyor)")
        info = cfd.write_case(case, geo, prm)
        with db.connect() as conn:
            conn.execute("UPDATE design_cfd_runs SET status = 'queued', geometry = ?, dir = ?, params = ? WHERE id = ?",
                         (json.dumps({**geo, **info}), str(case), json.dumps({**prm, **info}), run_id))
            db.audit(conn, user['id'], 'CFD analizi başlattı', 'design_drawing', did, f"{d['name']} · {U:g} m/s · {res}")
    except Exception as e:   # noqa: BLE001
        with db.connect() as conn:
            conn.execute("UPDATE design_cfd_runs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?", (str(e)[:2000], db.now(), run_id))
        raise HTTPException(400, f'Analiz hazırlanamadı: {e}')
    cfd.enqueue(run_id)
    return {'id': run_id, 'geometry': geo, 'case': info}


def _cfd_run(conn, rid):
    r = db.row(conn.execute('SELECT * FROM design_cfd_runs WHERE id = ?', (rid,)))
    if not r:
        raise HTTPException(404, 'Analiz bulunamadı')
    return r


@router.get('/cfd/{rid}')
def cfd_get(rid: int, user=Depends(design_user), conn=db.DB):
    from .. import cfd
    r = dict(_cfd_run(conn, rid))
    for k in ('params', 'geometry', 'result'):
        try:
            r[k] = json.loads(r[k]) if r[k] else None
        except (TypeError, ValueError):
            r[k] = None
    r['log'] = cfd.log_tail(rid, 40)
    if r['status'] in ('running', 'done') and r.get('dir'):
        from pathlib import Path
        case = Path(r['dir'])
        try:
            r['coeffs_live'] = cfd.parse_coeffs(case) if r['status'] == 'running' else None
            r['residuals'] = cfd.parse_residuals(case)
        except Exception:   # noqa: BLE001
            r['coeffs_live'] = None; r['residuals'] = None
    r.pop('dir', None)
    return r


@router.post('/cfd/{rid}/cancel')
def cfd_cancel(rid: int, user=Depends(design_user), conn=db.DB):
    r = _cfd_run(conn, rid)
    if r['status'] == 'queued':
        conn.execute("UPDATE design_cfd_runs SET status = 'cancelled', phase = 'cancelled', finished_at = ? WHERE id = ?", (db.now(), rid))
    elif r['status'] == 'running':
        conn.execute("UPDATE design_cfd_runs SET status = 'cancelling' WHERE id = ?", (rid,))
    return {'ok': True}


@router.delete('/cfd/{rid}')
def cfd_delete(rid: int, user=Depends(design_user), conn=db.DB):
    import shutil
    r = _cfd_run(conn, rid)
    if r['status'] in ('running', 'cancelling'):
        raise HTTPException(400, 'Önce analizi durdurun')
    conn.execute('DELETE FROM design_cfd_runs WHERE id = ?', (rid,))
    if r['dir']:
        shutil.rmtree(r['dir'], ignore_errors=True)
    return {'ok': True}


@router.get('/cfd/{rid}/file')
def cfd_file(rid: int, name: str, user=Depends(design_user), conn=db.DB):
    from fastapi.responses import FileResponse
    from pathlib import Path
    r = _cfd_run(conn, rid)
    if name not in ('body.bin', 'slice_side.bin', 'slice_top.bin', 'lines.bin', 'meta.json') or not r['dir']:
        raise HTTPException(404, 'Dosya yok')
    path = Path(r['dir']) / 'results' / name
    if not path.is_file():
        raise HTTPException(404, 'Sonuç dosyası yok')
    return FileResponse(path, media_type='application/json' if name.endswith('.json') else 'application/octet-stream')


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
def design_file(v: int = None, p: int = None, t: int = None, dl: int = 0, user=Depends(design_user), conn=db.DB):
    from fastapi.responses import FileResponse
    from .. import config
    row = None
    if t:   # sürümün 3B önizleme resmi
        row = db.row(conn.execute("SELECT thumb_path AS file_path, 'onizleme.png' AS file_name FROM design_drawing_versions WHERE id = ?", (t,)))
    elif v:
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
