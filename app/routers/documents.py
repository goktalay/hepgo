"""Evrak Yönetimi: taranmış evrak, resim, video ve diğer dosyalar; OCR metni üzerinde arama; firma ve firma
kişileriyle ilişkilendirme.

Görünürlük (yükleyen seçer): ALL (Evrak modülüne girebilen herkes), ROLES (yalnızca seçilen rollerdeki kişiler),
PRIVATE (yalnızca yükleyen). Yükleyen kendi evrakını her zaman görür; sistem yöneticisi de rolü seçilmemişse
kısıtlı evrakı göremez. Kural; liste, arama, firma detayı, dosya ve küçük resim indirmede aynı şekilde uygulanır.
"""
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, config, db, document_ocr
from ..document_ocr import IMAGE_EXT, fold, kind_of
from ..files import FILE_GUARDS, take_upload

router = APIRouter(prefix='/api/documents')
doc_user = auth.require_module('documents')
VISIBILITY = ('ALL', 'ROLES', 'PRIVATE')


class DocumentIn(BaseModel):
    upload_ids: list[str] = []
    merge_images: bool = False
    title: Optional[str] = None
    doc_date: Optional[str] = None
    note: Optional[str] = None
    company_ids: list[int] = []
    person_ids: list[int] = []
    visibility: str = 'ALL'
    roles: list[str] = []


# ---------- Görünürlük

def _visible_sql(user, alias='d'):
    roles = list(user['roles']) or ['']
    return (f"""({alias}.uploaded_by = ? OR {alias}.visibility = 'ALL' OR ({alias}.visibility = 'ROLES' AND {alias}.id IN
               (SELECT document_id FROM document_roles WHERE role IN ({','.join('?' * len(roles))}))))""",
            [user['id'], *roles])


def visible_ids(conn, user):
    if 'documents' not in user['modules'] and 'companies' not in user['modules']:
        return set()
    sql, args = _visible_sql(user)
    return {r[0] for r in conn.execute(f'SELECT d.id FROM documents d WHERE {sql}', args)}


def _file_guard(user, name):
    path = f'documents/{name}'
    with db.connect() as conn:
        from .signatures import signer_can_see   # imzacı, evrağı modül/görünürlük dışında da görebilir
        if signer_can_see(conn, user['id'], path):
            return True
        if 'documents' not in user['modules'] and 'companies' not in user['modules']:
            return False
        sql, args = _visible_sql(user)
        return conn.execute(f'''SELECT 1 FROM documents d WHERE (d.file = ? OR d.thumb = ? OR d.id IN
                                (SELECT document_id FROM document_faces WHERE crop = ?)) AND {sql}''',
                            (path, path, path, *args)).fetchone() is not None


FILE_GUARDS['documents'] = _file_guard
# Firma logoları siparişlerde (üretim, sipariş, depo ekranları) da gösterilir
FILE_GUARDS['logos'] = lambda user, name: bool({'companies', 'documents', 'orders', 'production', 'warehouse'} & set(user['modules']))


# ---------- Liste ve arama

def _decorate(conn, docs):
    for d in docs:
        d['companies'] = db.rows(conn.execute(
            'SELECT c.id, c.name FROM document_companies dc JOIN companies c ON c.id = dc.company_id WHERE dc.document_id = ? '
            'ORDER BY c.name', (d['id'],)))
        d['people'] = db.rows(conn.execute(
            '''SELECT p.id, p.full_name, p.company_id, c.name AS company_name FROM document_people dp
               JOIN company_people p ON p.id = dp.person_id JOIN companies c ON c.id = p.company_id
               WHERE dp.document_id = ? ORDER BY p.full_name''', (d['id'],)))
        d['roles'] = [r[0] for r in conn.execute('SELECT role FROM document_roles WHERE document_id = ? ORDER BY role', (d['id'],))]
    return docs


_LIST = '''SELECT d.id, d.title, d.kind, d.file, d.file_name, d.size, d.thumb, d.pages, d.doc_date, d.note, d.ocr_status,
                  d.ocr_error, d.visibility, d.uploaded_by, d.uploaded_at, u.full_name AS uploaded_by_name,
                  length(d.ocr_text) AS text_length
           FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by'''


def _tokens(q):
    return re.findall(r'\w+', fold(q))


def _match_query(tokens, phrase):
    if phrase and len(tokens) > 1:
        return '"' + ' '.join(tokens) + '"'
    return ' '.join(f'"{t}"*' for t in tokens)


def _snippet(tokens, *texts, width=90):
    """Aranan ifadenin geçtiği yerden özgün metinle kısa alıntı: {before, match, after}."""
    pattern = re.compile(r'\W+'.join(re.escape(t) for t in tokens))
    single = re.compile(re.escape(tokens[0])) if tokens else None
    for text in texts:
        if not text:
            continue
        folded = fold(text)   # fold harf sayısını korur: konumlar özgün metinde de geçerli
        m = pattern.search(folded) or (single.search(folded) if single else None)
        if m:
            a, b = m.span()
            s, e = max(0, a - width), min(len(text), b + width)
            clean = lambda x: re.sub(r'\s+', ' ', x)
            return {'before': ('…' if s else '') + clean(text[s:a]), 'match': clean(text[a:b]),
                    'after': clean(text[b:e]) + ('…' if e < len(text) else '')}
    return None


@router.get('')
def list_documents(q: str = '', company_id: Optional[int] = None, person_id: Optional[int] = None, kind: str = '',
                   status: str = '', date_from: str = '', date_to: str = '', limit: int = 500,
                   user=Depends(doc_user), conn=db.DB):
    vis, args = _visible_sql(user)
    where = [vis]
    if company_id:
        where.append('''(d.id IN (SELECT document_id FROM document_companies WHERE company_id = ?) OR d.id IN
                        (SELECT dp.document_id FROM document_people dp JOIN company_people p ON p.id = dp.person_id
                         WHERE p.company_id = ?))''')
        args += [company_id, company_id]
    if person_id:
        where.append('d.id IN (SELECT document_id FROM document_people WHERE person_id = ?)')
        args.append(person_id)
    if kind:
        where.append('d.kind = ?')
        args.append(kind)
    if status:
        where.append('d.ocr_status = ?')
        args.append(status)
    if date_from:
        where.append('COALESCE(d.doc_date, substr(d.uploaded_at, 1, 10)) >= ?')
        args.append(date_from)
    if date_to:
        where.append('COALESCE(d.doc_date, substr(d.uploaded_at, 1, 10)) <= ?')
        args.append(date_to)
    tokens = _tokens(q)
    order = 'd.uploaded_at DESC, d.id DESC'
    rows = []
    if tokens:
        # Önce ifadenin kendisi (cümle), bulunmazsa kelimelerin hepsi (sıra fark etmeden) aranır
        for phrase in (True, False):
            sql = (f'{_LIST} JOIN documents_fts f ON f.rowid = d.id WHERE {" AND ".join(where)} '
                   f'AND documents_fts MATCH ? ORDER BY bm25(documents_fts, 5.0, 1.0) LIMIT ?')
            rows = db.rows(conn.execute(sql, (*args, _match_query(tokens, phrase), limit)))
            if rows or len(tokens) == 1:
                break
        for d in rows:
            full = conn.execute('SELECT title, note, ocr_text FROM documents WHERE id = ?', (d['id'],)).fetchone()
            d['snippet'] = _snippet(tokens, full['ocr_text'], full['note'], full['title'])
    else:
        rows = db.rows(conn.execute(f'{_LIST} WHERE {" AND ".join(where)} ORDER BY {order} LIMIT ?', (*args, limit)))
    return {'documents': _decorate(conn, rows), 'ocr_available': document_ocr.available()}


def list_for_company(conn, user, cid):
    """Firma detayı: firmaya ya da firmanın kişilerine bağlı, kullanıcının görebildiği evraklar."""
    vis, args = _visible_sql(user)
    return _decorate(conn, db.rows(conn.execute(
        f'''{_LIST} WHERE {vis} AND (d.id IN (SELECT document_id FROM document_companies WHERE company_id = ?) OR d.id IN
            (SELECT dp.document_id FROM document_people dp JOIN company_people p ON p.id = dp.person_id WHERE p.company_id = ?))
            ORDER BY COALESCE(d.doc_date, d.uploaded_at) DESC''', (*args, cid, cid))))


def list_for_person(conn, user, pid):
    """Rehber kişi detayı: kişiye bağlı, kullanıcının görebildiği evraklar."""
    vis, args = _visible_sql(user)
    return _decorate(conn, db.rows(conn.execute(
        f'''{_LIST} WHERE {vis} AND d.id IN (SELECT document_id FROM document_people WHERE person_id = ?)
            ORDER BY COALESCE(d.doc_date, d.uploaded_at) DESC''', (*args, pid))))


def list_for_user(conn, user, uid):
    """Rehber kullanıcı detayı: kullanıcının yüklediği ya da imzasına gönderilen, görülebilen evraklar."""
    vis, args = _visible_sql(user)
    return _decorate(conn, db.rows(conn.execute(
        f'''{_LIST} WHERE {vis} AND (d.uploaded_by = ? OR d.id IN (SELECT document_id FROM document_signatures WHERE signer_id = ?)
            OR d.id IN (SELECT document_id FROM document_faces WHERE user_id = ?))
            ORDER BY COALESCE(d.doc_date, d.uploaded_at) DESC''', (*args, uid, uid, uid))))


# ---------- Evrak

def _get(conn, doc_id, user):
    vis, args = _visible_sql(user)
    d = db.row(conn.execute(f'SELECT d.*, u.full_name AS uploaded_by_name FROM documents d '
                            f'LEFT JOIN users u ON u.id = d.uploaded_by WHERE d.id = ? AND {vis}', (doc_id, *args)))
    if not d:
        raise HTTPException(404, 'Evrak bulunamadı')
    return d


def _can_edit(d, user):
    return d['uploaded_by'] == user['id'] or auth.ADMIN in user['roles']


def _check_links(conn, body):
    if body.visibility not in VISIBILITY:
        raise HTTPException(400, 'Geçersiz görünürlük')
    roles = sorted(set(body.roles)) if body.visibility == 'ROLES' else []
    if body.visibility == 'ROLES' and not roles:
        raise HTTPException(400, 'Görebilecek en az bir rol seçin')
    if any(r not in auth.all_roles() for r in roles):
        raise HTTPException(400, 'Geçersiz rol')
    for cid in set(body.company_ids):
        if not conn.execute('SELECT 1 FROM companies WHERE id = ?', (cid,)).fetchone():
            raise HTTPException(400, 'Firma bulunamadı')
    for pid in set(body.person_ids):
        if not conn.execute('SELECT 1 FROM company_people WHERE id = ?', (pid,)).fetchone():
            raise HTTPException(400, 'Kişi bulunamadı')
    if body.doc_date:
        try:
            from datetime import date
            date.fromisoformat(body.doc_date[:10])
        except ValueError:
            raise HTTPException(400, 'Evrak tarihi geçersiz') from None
    return roles


def _save_links(conn, doc_id, body, roles):
    conn.execute('DELETE FROM document_companies WHERE document_id = ?', (doc_id,))
    conn.execute('DELETE FROM document_people WHERE document_id = ?', (doc_id,))
    conn.execute('DELETE FROM document_roles WHERE document_id = ?', (doc_id,))
    conn.executemany('INSERT INTO document_companies (document_id, company_id) VALUES (?,?)',
                     [(doc_id, c) for c in sorted(set(body.company_ids))])
    conn.executemany('INSERT INTO document_people (document_id, person_id) VALUES (?,?)',
                     [(doc_id, p) for p in sorted(set(body.person_ids))])
    conn.executemany('INSERT INTO document_roles (document_id, role) VALUES (?,?)', [(doc_id, r) for r in roles])


def _merge_images(stored, title):
    """Taranmış sayfa resimlerini tek PDF evrakta birleştirir (sayfa sırası seçim sırası)."""
    from PIL import Image, ImageOps
    pages = []
    for path, _, _ in stored:
        with Image.open(config.UPLOAD_DIR / path) as im:
            pages.append(ImageOps.exif_transpose(im).convert('RGB'))
    name = f'{Path(stored[0][0]).stem}.pdf'
    out = config.UPLOAD_DIR / 'documents' / name
    pages[0].save(out, 'PDF', save_all=True, append_images=pages[1:], resolution=200)
    for path, _, _ in stored:
        (config.UPLOAD_DIR / path).unlink(missing_ok=True)
    safe = re.sub(r'[^\w\s.-]', '', title or 'Taranan evrak').strip() or 'Taranan evrak'
    return [(f'documents/{name}', out.stat().st_size, f'{safe}.pdf')]


@router.post('')
async def create_documents(body: DocumentIn, user=Depends(doc_user), conn=db.DB):
    """Parça parça yüklenmiş dosyalardan evrak oluşturur (her dosya bir evrak; istenirse resimler tek PDF)."""
    if not body.upload_ids:
        raise HTTPException(400, 'Dosya seçin')
    roles = await run_in_threadpool(_check_links, conn, body)
    stored = [await run_in_threadpool(take_upload, u, user, 'documents') for u in body.upload_ids]
    if body.merge_images and len(stored) > 1:
        if any(Path(fn).suffix.lower() not in IMAGE_EXT for _, _, fn in stored):
            raise HTTPException(400, 'Yalnızca resimler tek evrakta birleştirilebilir')
        stored = await run_in_threadpool(_merge_images, stored, body.title)

    def write():
        ids = []
        for i, (path, size, file_name) in enumerate(stored):
            title = (body.title or '').strip()
            title = (f'{title} ({i + 1})' if len(stored) > 1 else title) if title else Path(file_name).stem
            cur = conn.execute(
                '''INSERT INTO documents (title, kind, file, file_name, size, doc_date, note, visibility, uploaded_by, uploaded_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (title[:300], kind_of(file_name), path, file_name[:300], size, (body.doc_date or '')[:10] or None,
                 (body.note or '').strip() or None, body.visibility, user['id'], db.now()))
            _save_links(conn, cur.lastrowid, body, roles)
            document_ocr.index(conn, cur.lastrowid)
            db.audit(conn, user['id'], 'Evrak yükledi', 'document', cur.lastrowid, f'{title} ({file_name})')
            ids.append(cur.lastrowid)
        conn.commit()   # OCR iş parçacığı kaydı görebilsin
        return ids
    ids = await run_in_threadpool(write)
    for doc_id in ids:
        document_ocr.start(doc_id)
    return {'ids': ids}


@router.get('/{doc_id}')
def get_document(doc_id: int, user=Depends(doc_user), conn=db.DB):
    d = _decorate(conn, [_get(conn, doc_id, user)])[0]
    d['can_edit'] = _can_edit(d, user)
    from .signatures import signatures_for
    d['signatures'] = signatures_for(conn, doc_id)
    d['faces'] = _faces(conn, doc_id)
    return d


# ---------- Videodaki kişiler (yüz tanıma)

def _faces(conn, doc_id):
    return db.rows(conn.execute(
        '''SELECT f.id, f.crop, f.samples, f.first_at, f.person_id, f.user_id, f.auto, f.assigned_at,
                  p.full_name AS person_name, p.title AS person_title, c.id AS company_id, c.name AS company_name,
                  u.full_name AS user_name, a.full_name AS assigned_by_name
           FROM document_faces f
           LEFT JOIN company_people p ON p.id = f.person_id LEFT JOIN companies c ON c.id = p.company_id
           LEFT JOIN users u ON u.id = f.user_id LEFT JOIN users a ON a.id = f.assigned_by
           WHERE f.document_id = ? ORDER BY f.samples DESC, f.id''', (doc_id,)))


class FaceIn(BaseModel):
    person_id: Optional[int] = None   # firma kişisi
    user_id: Optional[int] = None     # personel (sistem kullanıcısı)


def _face(conn, doc_id, fid, user):
    _get(conn, doc_id, user)   # evrağı görebiliyor mu
    f = db.row(conn.execute('SELECT * FROM document_faces WHERE id = ? AND document_id = ?', (fid, doc_id)))
    if not f:
        raise HTTPException(404, 'Yüz bulunamadı')
    return f


def _unlink_face(conn, f):
    """Yüzün eklediği kişi bağlantısı, evrakta aynı kişiye ait başka yüz yoksa kaldırılır."""
    if f['added_link'] and f['person_id'] and not conn.execute(
            'SELECT 1 FROM document_faces WHERE document_id = ? AND person_id = ? AND id != ?',
            (f['document_id'], f['person_id'], f['id'])).fetchone():
        conn.execute('DELETE FROM document_people WHERE document_id = ? AND person_id = ?', (f['document_id'], f['person_id']))


@router.put('/{doc_id}/faces/{fid}')
def assign_face(doc_id: int, fid: int, body: FaceIn, user=Depends(doc_user), conn=db.DB):
    """Yüzü bir firma kişisine ya da personele bağlar (ikisi de boşsa tanımsız yapar). Firma kişisi evrağın kişilerine eklenir."""
    f = _face(conn, doc_id, fid, user)
    if body.person_id and body.user_id:
        raise HTTPException(400, 'Yüz ya firma kişisine ya da personele bağlanır')
    if body.person_id and not conn.execute('SELECT 1 FROM company_people WHERE id = ?', (body.person_id,)).fetchone():
        raise HTTPException(400, 'Firma kişisi bulunamadı')
    if body.user_id and not conn.execute('SELECT 1 FROM users WHERE id = ? AND deleted_at IS NULL', (body.user_id,)).fetchone():
        raise HTTPException(400, 'Personel bulunamadı')
    _unlink_face(conn, f)
    added = 0
    if body.person_id and not conn.execute('SELECT 1 FROM document_people WHERE document_id = ? AND person_id = ?',
                                           (doc_id, body.person_id)).fetchone():
        conn.execute('INSERT INTO document_people (document_id, person_id) VALUES (?, ?)', (doc_id, body.person_id))
        added = 1
    elif body.person_id and f['person_id'] == body.person_id:
        added = f['added_link']
    conn.execute('''UPDATE document_faces SET person_id = ?, user_id = ?, auto = 0, added_link = ?, assigned_by = ?, assigned_at = ?
                    WHERE id = ?''', (body.person_id, body.user_id, added, user['id'], db.now(), fid))
    document_ocr.index(conn, doc_id)
    who = (conn.execute('SELECT full_name FROM company_people WHERE id = ?', (body.person_id,)).fetchone() if body.person_id else
           conn.execute('SELECT full_name FROM users WHERE id = ?', (body.user_id,)).fetchone() if body.user_id else None)
    db.audit(conn, user['id'], 'Videodaki kişiyi tanımladı' if who else 'Videodaki kişiyi tanımsız yaptı', 'document', doc_id,
             who[0] if who else None)
    return {'faces': _faces(conn, doc_id)}


@router.delete('/{doc_id}/faces/{fid}')
def delete_face(doc_id: int, fid: int, user=Depends(doc_user), conn=db.DB):
    """Yanlış tespit (kişi değil) ya da gereksiz yüz: kaldırılır."""
    f = _face(conn, doc_id, fid, user)
    _unlink_face(conn, f)
    conn.execute('DELETE FROM document_faces WHERE id = ?', (fid,))
    (config.UPLOAD_DIR / f['crop']).unlink(missing_ok=True)
    document_ocr.index(conn, doc_id)
    db.audit(conn, user['id'], 'Videodaki yüzü kaldırdı', 'document', doc_id)
    return {'faces': _faces(conn, doc_id)}


@router.put('/{doc_id}')
def update_document(doc_id: int, body: DocumentIn, user=Depends(doc_user), conn=db.DB):
    d = _get(conn, doc_id, user)
    if not _can_edit(d, user):
        raise HTTPException(403, 'Evrakı yalnızca yükleyen kişi veya sistem yöneticisi düzenleyebilir')
    if d['uploaded_by'] != user['id'] and body.visibility != d['visibility']:
        raise HTTPException(403, 'Görünürlüğü yalnızca evrakı yükleyen kişi değiştirebilir')
    roles = _check_links(conn, body)
    if d['uploaded_by'] != user['id'] and roles != sorted(r[0] for r in conn.execute(
            'SELECT role FROM document_roles WHERE document_id = ?', (doc_id,))):
        raise HTTPException(403, 'Görünürlüğü yalnızca evrakı yükleyen kişi değiştirebilir')
    title = (body.title or '').strip()
    if not title:
        raise HTTPException(400, 'Evrak adı zorunlu')
    conn.execute('UPDATE documents SET title = ?, doc_date = ?, note = ?, visibility = ?, updated_at = ? WHERE id = ?',
                 (title[:300], (body.doc_date or '')[:10] or None, (body.note or '').strip() or None, body.visibility,
                  db.now(), doc_id))
    _save_links(conn, doc_id, body, roles)
    document_ocr.index(conn, doc_id)
    db.audit(conn, user['id'], 'Evrakı düzenledi', 'document', doc_id, title)
    return {'ok': True}


@router.delete('/{doc_id}')
def delete_document(doc_id: int, user=Depends(doc_user), conn=db.DB):
    d = _get(conn, doc_id, user)
    if not _can_edit(d, user):
        raise HTTPException(403, 'Evrakı yalnızca yükleyen kişi veya sistem yöneticisi silebilir')
    crops = [r[0] for r in conn.execute('SELECT crop FROM document_faces WHERE document_id = ?', (doc_id,))]
    for f in (d['file'], d['thumb'], *crops):
        if f:
            (config.UPLOAD_DIR / f).unlink(missing_ok=True)
    conn.execute('DELETE FROM documents_fts WHERE rowid = ?', (doc_id,))
    conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
    db.audit(conn, user['id'], 'Evrak sildi', 'document', doc_id, f'{d["title"]} ({d["file_name"]})')
    return {'ok': True}


@router.post('/{doc_id}/ocr')
def rerun_ocr(doc_id: int, user=Depends(doc_user), conn=db.DB):
    d = _get(conn, doc_id, user)
    if not _can_edit(d, user):
        raise HTTPException(403, 'Yetkiniz yok')
    conn.execute("UPDATE documents SET ocr_status = 'BEKLIYOR', ocr_error = NULL WHERE id = ?", (doc_id,))
    conn.commit()
    document_ocr.start(doc_id)
    return {'ok': True}
