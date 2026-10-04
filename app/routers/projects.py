"""Proje Yönetimi — /api/projects: projeler (resimli tanım, sorumlu, tarihler, bütçe), hareket / fatura / kalem etiketleme,
proje kâr-zararı, proje kararı bekleyen hareketler, anahtar kelime taraması ve proje adayı keşfi.
Proje bir gruplamadır: silinince yalnız etiketler kalkar, finansal veri silinmez."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import auth, config, db, projects as P
from ..files import FILE_GUARDS, save_upload_stream, take_upload

router = APIRouter(prefix='/api/projects')
proj_user = auth.require_module('projects')


def _any(*mods):
    def dep(user=Depends(auth.current_user)):
        if user.get('master') or set(mods) & set(user.get('modules', [])):
            return user
        raise HTTPException(403, 'Bu işlem için yetkiniz yok')
    return dep


# Proje seçimi / hareket kararı: Finans, Satış, Satın Alma ekranlarından da yapılır ("her harekette proje sorulur")
tag_user = _any('projects', 'finance', 'sales', 'purchasing')
FILE_GUARDS['projects'] = lambda user, name: bool(user.get('master')) or bool({'projects', 'finance', 'boss'} & set(user.get('modules', [])))


def _project(conn, pid):
    p = db.row(conn.execute('''SELECT p.*, u.full_name AS manager_name, c.name AS company_name FROM projects p
                               LEFT JOIN users u ON u.id = p.manager_id LEFT JOIN companies c ON c.id = p.company_id WHERE p.id = ?''', (pid,)))
    if not p:
        raise HTTPException(404, 'Proje bulunamadı')
    return p


def _meta():
    return {'kinds': P.KINDS, 'statuses': P.STATUS, 'natures': P.NATURE}


@router.get('')
def list_projects(user=Depends(proj_user), conn=db.DB):
    rows = db.rows(conn.execute('''SELECT p.*, u.full_name AS manager_name, c.name AS company_name FROM projects p
                                   LEFT JOIN users u ON u.id = p.manager_id LEFT JOIN companies c ON c.id = p.company_id
                                   ORDER BY CASE p.status WHEN 'devam' THEN 0 WHEN 'planlama' THEN 1 WHEN 'fikir' THEN 2 WHEN 'beklemede' THEN 3 ELSE 4 END,
                                   p.start_date DESC, p.id DESC'''))
    ms = P.universe(conn)
    umap = {(m['source'], m['ref']): m for m in ms}
    for p in rows:
        f = P.project_finance(conn, p['id'], umap)
        p['fin'] = {k: f[k] for k in ('gelir', 'gider', 'kar', 'marj')}
        p['tag_count'] = len(f['items'])
    decided = set(P.tags_by_source(conn))
    pending = sum(1 for m in ms if (m['source'], m['ref']) not in decided and m['nature'] != 'odeme')
    return {'rows': rows, 'meta': _meta(), 'pending': pending}


@router.get('/options')
def options(user=Depends(tag_user), conn=db.DB):
    """Proje seçim listesi (Finans / Satış / Satın Alma formlarında)."""
    return db.rows(conn.execute("SELECT id, code, name, status FROM projects WHERE status NOT IN ('iptal') ORDER BY name COLLATE NOCASE"))


@router.get('/people/options')
def people(user=Depends(proj_user), conn=db.DB):
    """Proje formu: sorumlu (aktif kullanıcılar) ve müşteri / destek kurumu (firmalar)."""
    return {'users': db.rows(conn.execute('SELECT id, full_name FROM users WHERE active = 1 AND deleted_at IS NULL ORDER BY full_name COLLATE NOCASE')),
            'companies': db.rows(conn.execute('SELECT id, name FROM companies WHERE active = 1 ORDER BY name COLLATE NOCASE')), **_meta()}


class ProjectIn(BaseModel):
    name: str
    code: Optional[str] = None
    kind: str = 'arge'
    status: str = 'devam'
    manager_id: Optional[int] = None
    company_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget: Optional[float] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[str] = None
    mikro_code: Optional[str] = None


def _vals(conn, b: ProjectIn, pid=None):
    if not b.name.strip():
        raise HTTPException(400, 'Proje adı gerekli')
    if b.kind not in P.KINDS or b.status not in P.STATUS:
        raise HTTPException(400, 'Geçersiz tür / durum')
    code = (b.code or '').strip().upper()[:30] or None
    if code and conn.execute('SELECT 1 FROM projects WHERE code = ? AND id IS NOT ?', (code, pid)).fetchone():
        raise HTTPException(409, 'Bu proje kodu kullanılıyor')
    t = lambda v, n: ((v or '').strip()[:n] or None)
    return {'name': b.name.strip()[:160], 'code': code, 'kind': b.kind, 'status': b.status, 'manager_id': b.manager_id, 'company_id': b.company_id,
            'start_date': (b.start_date or '')[:10] or None, 'end_date': (b.end_date or '')[:10] or None, 'budget': b.budget,
            'summary': t(b.summary, 400), 'description': t(b.description, 20000), 'keywords': t(b.keywords, 500), 'mikro_code': t(b.mikro_code, 40),
            'updated_at': db.now()}


@router.post('')
def create(b: ProjectIn, user=Depends(proj_user), conn=db.DB):
    v = _vals(conn, b)
    if not v['code']:
        n = (conn.execute('SELECT MAX(id) FROM projects').fetchone()[0] or 0) + 1
        v['code'] = f'P-{n:04d}'
        while conn.execute('SELECT 1 FROM projects WHERE code = ?', (v['code'],)).fetchone():
            n += 1
            v['code'] = f'P-{n:04d}'
    v.update(created_by=user['id'], created_at=v['updated_at'])
    cur = conn.execute(f"INSERT INTO projects ({', '.join(v)}) VALUES ({', '.join('?' * len(v))})", list(v.values()))
    db.audit(conn, user['id'], 'Proje oluşturdu', 'project', cur.lastrowid, v['name'][:80])
    conn.commit()
    return {'id': cur.lastrowid}


@router.get('/queue/list')
def queue(status: str = 'open', nature: str = '', since: str = '', until: str = '', user=Depends(tag_user), conn=db.DB):
    """Proje kararı bekleyen / verilmiş hareketler; anahtar kelime önerisiyle."""
    ms = P.universe(conn, since, until)
    tags = P.tags_by_source(conn)
    sugg = P.suggestions(conn, ms, set(tags))
    out = []
    for m in ms:
        t = tags.get((m['source'], m['ref']), [])
        if status == 'open' and t or status == 'done' and not t or (nature and m['nature'] != nature):
            continue
        m['tags'] = [{'project_id': x['project_id'], 'name': x['project_name'], 'code': x['project_code'], 'net': x['net'], 'line_desc': x['line_desc']} for x in t]
        m['suggest'] = sugg.get((m['source'], m['ref']), [])
        out.append(m)
    out.sort(key=lambda m: (m['date'] or '', m['ref']), reverse=True)
    counts = {'open': sum(1 for m in ms if (m['source'], m['ref']) not in tags), 'done': sum(1 for m in ms if (m['source'], m['ref']) in tags)}
    return {'rows': out[:3000], 'total': len(out), 'counts': counts, 'natures': P.NATURE,
            'projects': db.rows(conn.execute("SELECT id, code, name FROM projects WHERE status != 'iptal' ORDER BY name COLLATE NOCASE"))}


@router.get('/movement/one')
def movement(source: str, ref: int, user=Depends(tag_user), conn=db.DB):
    m = P.movement(conn, source, ref)
    if not m:
        raise HTTPException(404, 'Hareket bulunamadı ya da projeye sorulmayan bir hareket (açılış / kendi hesapları arası virman)')
    m['projects'] = db.rows(conn.execute("SELECT id, code, name FROM projects WHERE status != 'iptal' ORDER BY name COLLATE NOCASE"))
    return m


class Alloc(BaseModel):
    project_id: Optional[int] = None
    amount: Optional[float] = None
    line_ref: Optional[str] = None


class DecideIn(BaseModel):
    source: str
    ref: int
    allocations: List[Alloc] = []
    note: Optional[str] = None


@router.put('/decide')
def decide(b: DecideIn, user=Depends(tag_user), conn=db.DB):
    m = P.movement(conn, b.source, b.ref)
    if not m:
        raise HTTPException(404, 'Hareket bulunamadı')
    P.decide(conn, user['id'], m, [a.model_dump() for a in b.allocations], b.note)
    conn.commit()
    return {'ok': True}


class DocDecideIn(BaseModel):
    source: str                                # invoice | mdoc
    ref: int
    project_id: Optional[int] = None
    project_none: bool = False
    lines: Optional[List[Optional[int]]] = None   # Satın Alma kalemleri sırasıyla proje (None: belgedeki karar)


@router.put('/decide-doc')
def decide_doc(b: DocDecideIn, user=Depends(tag_user), conn=db.DB):
    """Satış faturası / Satın Alma belgesi kaydedilirken sorulan proje (kalem bazında olabilir)."""
    m = P.canonical(conn, b.source, b.ref)
    if not m:
        raise HTTPException(404, 'Belge bulunamadı')
    head = None if b.project_none else b.project_id
    mlines = [ln for ln in m.get('lines', []) if ln['line_ref'].startswith(('mline:', 'item:'))]
    if b.lines and any(v for v in b.lines) and mlines:
        mlines.sort(key=lambda ln: int(ln['line_ref'].split(':')[1]))
        alloc = []
        for i, ln in enumerate(mlines):
            pid = (b.lines[i] if i < len(b.lines) else None) or head
            if pid:
                alloc.append({'project_id': pid, 'line_ref': ln['line_ref']})
        allocations = alloc or [{'project_id': None}]
    else:
        allocations = [{'project_id': head}]
    P.decide(conn, user['id'], m, allocations)
    conn.commit()
    return {'ok': True, 'source': m['source'], 'ref': m['ref']}


@router.delete('/decide')
def undecide(source: str, ref: int, user=Depends(tag_user), conn=db.DB):
    conn.execute('DELETE FROM project_tags WHERE source = ? AND ref = ?', (source, ref))
    conn.commit()
    return {'ok': True}


class BulkIn(BaseModel):
    items: List[DecideIn]
    project_id: Optional[int] = None   # None: projesiz


@router.post('/decide/bulk')
def decide_bulk(b: BulkIn, user=Depends(tag_user), conn=db.DB):
    ms = {(m['source'], m['ref']): m for m in P.universe(conn)}
    n = 0
    for it in b.items:
        m = ms.get((it.source, it.ref))
        if m:
            m['lines'] = []
            P.decide(conn, user['id'], m, [{'project_id': b.project_id}])
            n += 1
    db.audit(conn, user['id'], 'Toplu proje kararı', 'project', b.project_id, f'{n} hareket')
    conn.commit()
    return {'ok': True, 'count': n}


@router.post('/scan/apply')
def scan_apply(project_id: int = 0, user=Depends(proj_user), conn=db.DB):
    """Anahtar kelimesi eşleşen, kararı verilmemiş hareketleri projeye bağlar (tek projeyle eşleşenler)."""
    ms = {(m['source'], m['ref']): m for m in P.universe(conn)}
    n = 0
    for key, pids in P.suggestions(conn, list(ms.values())).items():
        if len(pids) != 1 or (project_id and pids[0] != project_id):
            continue
        m = ms[key]
        m['lines'] = []
        P.decide(conn, user['id'], m, [{'project_id': pids[0]}], auto=True)
        n += 1
    conn.commit()
    return {'tagged': n}


@router.get('/scan/mikro')
def scan_mikro(user=Depends(proj_user), conn=db.DB):
    """Mikro proje kartları (Entegrasyonlar › Mikro senkronundan) ve kodlarının geçtiği hareket sayıları."""
    import json as _j
    row = conn.execute("SELECT v FROM app_kv WHERE k = 'mikro_projects_probe'").fetchone()
    probe = _j.loads(row[0]) if row else None
    txn = dict(conn.execute('SELECT mikro_project, COUNT(*) FROM fin_txns WHERE mikro_project IS NOT NULL GROUP BY mikro_project').fetchall())
    led = dict(conn.execute('SELECT mikro_project, COUNT(*) FROM fin_ledger WHERE mikro_project IS NOT NULL GROUP BY mikro_project').fetchall())
    linked = dict(conn.execute('SELECT mikro_code, id FROM projects WHERE mikro_code IS NOT NULL').fetchall())
    codes = {r[0]: r[1] for r in conn.execute('SELECT code, name FROM mikro_projects')}
    for c in set(txn) | set(led):
        codes.setdefault(c, None)
    rows = [{'code': c, 'name': n, 'txns': txn.get(c, 0), 'ledger': led.get(c, 0), 'project_id': linked.get(c)} for c, n in codes.items()]
    rows.sort(key=lambda r: -(r['txns'] + r['ledger']))
    return {'probe': probe, 'rows': rows}


@router.get('/scan/discover')
def discover(user=Depends(proj_user), conn=db.DB):
    return {'candidates': P.discover(conn)}


@router.get('/{pid}')
def detail(pid: int, user=Depends(proj_user), conn=db.DB):
    p = _project(conn, pid)
    p['images'] = db.rows(conn.execute('SELECT * FROM project_images WHERE project_id = ? ORDER BY sort, id', (pid,)))
    p['finance'] = P.project_finance(conn, pid)
    p['suggest_count'] = sum(1 for v in P.suggestions(conn).values() if pid in v)
    p['meta'] = _meta()
    return p


@router.put('/{pid}')
def update(pid: int, b: ProjectIn, user=Depends(proj_user), conn=db.DB):
    _project(conn, pid)
    v = _vals(conn, b, pid)
    if not v['code']:
        v.pop('code')
    conn.execute(f"UPDATE projects SET {', '.join(f'{k} = ?' for k in v)} WHERE id = ?", [*v.values(), pid])
    conn.commit()
    return {'ok': True}


@router.delete('/{pid}')
def delete(pid: int, confirm: str = '', user=Depends(proj_user), conn=db.DB):
    p = _project(conn, pid)
    if confirm.strip() != p['name']:
        raise HTTPException(400, 'Silmek için proje adını aynen yazın')
    n = conn.execute('SELECT COUNT(*) FROM project_tags WHERE project_id = ?', (pid,)).fetchone()[0]
    paths = [r[0] for r in conn.execute('SELECT path FROM project_images WHERE project_id = ?', (pid,))] + ([p['image']] if p['image'] else [])
    # Bu projeye dokunan hareketlerin TÜM kararları kalkar (bölüşümdeki "kalan projesiz" dilimi dahil) → yeniden proje sorulur.
    # Hareketler / faturalar / kalemler silinmez (proje bir gruplamadır).
    for src, ref in conn.execute('SELECT DISTINCT source, ref FROM project_tags WHERE project_id = ?', (pid,)).fetchall():
        conn.execute('DELETE FROM project_tags WHERE source = ? AND ref = ?', (src, ref))
    conn.execute('DELETE FROM projects WHERE id = ?', (pid,))
    db.audit(conn, user['id'], 'Proje sildi', 'project', pid, f"{p['name']} · {n} etiket kaldırıldı")
    conn.commit()
    for x in paths:
        (config.UPLOAD_DIR / x).unlink(missing_ok=True)
    return {'ok': True, 'untagged': n}


@router.post('/{pid}/cover')
async def cover(pid: int, file: UploadFile = File(...), user=Depends(proj_user), conn=db.DB):
    p = _project(conn, pid)
    if not (file.filename or '').lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.gif')):
        raise HTTPException(400, 'Kapak resim olmalı')
    path, _ = await save_upload_stream('projects', file, 30 * 1024 * 1024)
    conn.execute('UPDATE projects SET image = ?, updated_at = ? WHERE id = ?', (path, db.now(), pid))
    conn.commit()
    if p['image']:
        (config.UPLOAD_DIR / p['image']).unlink(missing_ok=True)
    return {'image': path}


class ImageIn(BaseModel):
    upload_id: str
    caption: Optional[str] = None


@router.post('/{pid}/images')
def add_image(pid: int, b: ImageIn, user=Depends(proj_user), conn=db.DB):
    _project(conn, pid)
    path, _size, _name = take_upload(b.upload_id, user, 'projects')
    sort = (conn.execute('SELECT MAX(sort) FROM project_images WHERE project_id = ?', (pid,)).fetchone()[0] or 0) + 1
    cur = conn.execute('INSERT INTO project_images (project_id, path, caption, sort, uploaded_by, created_at) VALUES (?,?,?,?,?,?)',
                       (pid, path, (b.caption or '').strip()[:200] or None, sort, user['id'], db.now()))
    conn.commit()
    return {'id': cur.lastrowid}


@router.delete('/images/{iid}')
def delete_image(iid: int, user=Depends(proj_user), conn=db.DB):
    r = db.row(conn.execute('SELECT * FROM project_images WHERE id = ?', (iid,)))
    if not r:
        raise HTTPException(404, 'Resim bulunamadı')
    conn.execute('DELETE FROM project_images WHERE id = ?', (iid,))
    conn.commit()
    (config.UPLOAD_DIR / r['path']).unlink(missing_ok=True)
    return {'ok': True}
