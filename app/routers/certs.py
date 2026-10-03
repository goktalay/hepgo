"""Sertifikasyon — /api/certs: şirketin sahip olduğu ve almaya çalıştığı sertifikalar (ISO 9001, tesis güvenlik,
üretim izni…). Her sertifikanın taranmış görseli (A4 dikey), tarihleri, yüzlerce dokümanı ve birden çok denetimi olur.
Dokümanlar parça parça yüklenir (POST /api/uploads kind=certs → jeton → POST /api/certs/{id}/docs)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import auth, config, db
from ..files import FILE_GUARDS, save_upload_stream, take_upload

router = APIRouter(prefix='/api/certs')
cert_user = auth.require_module('certs')
FILE_GUARDS['certs'] = lambda user, name: bool(user.get('master')) or 'certs' in user.get('modules', [])

STATUS = {'hazirlik': 'Hazırlık', 'basvuru': 'Başvuru yapıldı', 'gecerli': 'Geçerli', 'askida': 'Askıda',
          'suresi_doldu': 'Süresi doldu', 'iptal': 'İptal'}
AUDIT_KINDS = {'ilk': 'İlk belgelendirme', 'gozetim': 'Gözetim', 'yeniden': 'Yeniden belgelendirme', 'ic': 'İç denetim',
               'musteri': 'Müşteri denetimi', 'ozel': 'Özel / habersiz'}
AUDIT_RESULTS = {'planlandi': 'Planlandı', 'basarili': 'Başarılı', 'sartli': 'Şartlı (düzeltici faaliyet)', 'basarisiz': 'Başarısız', 'iptal': 'İptal'}


def _days_left(d):
    try:
        return (date.fromisoformat((d or '')[:10]) - date.today()).days
    except ValueError:
        return None


def _cert(conn, cid):
    c = db.row(conn.execute('SELECT * FROM certs WHERE id=?', (cid,)))
    if not c:
        raise HTTPException(404, 'Sertifika bulunamadı')
    return c


def _decorate(conn, c):
    c['days_left'] = _days_left(c.get('expiry_date'))
    c['doc_count'] = conn.execute('SELECT COUNT(*) FROM cert_docs WHERE cert_id=?', (c['id'],)).fetchone()[0]
    c['audit_count'] = conn.execute('SELECT COUNT(*) FROM cert_audits WHERE cert_id=?', (c['id'],)).fetchone()[0]
    nxt = conn.execute("SELECT MIN(date) FROM cert_audits WHERE cert_id=? AND result='planlandi' AND date >= ?",
                       (c['id'], date.today().isoformat())).fetchone()[0]
    c['next_audit'] = nxt
    return c


@router.get('')
def list_certs(user=Depends(cert_user), conn=db.DB):
    rows = [_decorate(conn, c) for c in db.rows(conn.execute('SELECT * FROM certs ORDER BY name COLLATE NOCASE'))]
    return {'rows': rows, 'statuses': STATUS, 'audit_kinds': AUDIT_KINDS, 'audit_results': AUDIT_RESULTS}


class CertIn(BaseModel):
    name: str
    standard: Optional[str] = None
    issuer: Optional[str] = None
    cert_no: Optional[str] = None
    status: str = 'gecerli'
    apply_date: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    scope: Optional[str] = None
    note: Optional[str] = None


def _vals(b: CertIn):
    if not b.name.strip():
        raise HTTPException(400, 'Sertifika adı gerekli')
    if b.status not in STATUS:
        raise HTTPException(400, 'Geçersiz durum')
    t = lambda v, n=300: ((v or '').strip()[:n] or None)
    d = lambda v: ((v or '')[:10] or None)
    return (b.name.strip()[:160], t(b.standard, 120), t(b.issuer, 160), t(b.cert_no, 80), b.status, d(b.apply_date), d(b.issue_date),
            d(b.expiry_date), t(b.scope, 2000), t(b.note, 4000))


@router.post('')
def create(b: CertIn, user=Depends(cert_user), conn=db.DB):
    now = db.now()
    cur = conn.execute('''INSERT INTO certs (name, standard, issuer, cert_no, status, apply_date, issue_date, expiry_date, scope, note,
                          created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (*_vals(b), user['id'], now, now))
    db.audit(conn, user['id'], 'Sertifika ekledi', 'cert', cur.lastrowid, b.name[:80])
    conn.commit()
    return {'id': cur.lastrowid}


@router.get('/{cid}')
def detail(cid: int, user=Depends(cert_user), conn=db.DB):
    c = _decorate(conn, _cert(conn, cid))
    c['audits'] = db.rows(conn.execute('''SELECT a.*, (SELECT COUNT(*) FROM cert_docs d WHERE d.audit_id=a.id) AS doc_count
                                          FROM cert_audits a WHERE a.cert_id=? ORDER BY a.date DESC, a.id DESC''', (cid,)))
    c['folders'] = [r[0] for r in conn.execute("SELECT DISTINCT folder FROM cert_docs WHERE cert_id=? AND folder IS NOT NULL AND folder != '' ORDER BY folder", (cid,))]
    return c


@router.put('/{cid}')
def update(cid: int, b: CertIn, user=Depends(cert_user), conn=db.DB):
    _cert(conn, cid)
    conn.execute('''UPDATE certs SET name=?, standard=?, issuer=?, cert_no=?, status=?, apply_date=?, issue_date=?, expiry_date=?, scope=?, note=?,
                    updated_at=? WHERE id=?''', (*_vals(b), db.now(), cid))
    conn.commit()
    return {'ok': True}


@router.delete('/{cid}')
def delete(cid: int, confirm: str = '', user=Depends(cert_user), conn=db.DB):
    c = _cert(conn, cid)
    if confirm.strip().casefold() != c['name'].strip().casefold():
        raise HTTPException(400, 'Silmek için sertifika adını aynen yazın')
    paths = [r[0] for r in conn.execute('SELECT path FROM cert_docs WHERE cert_id=?', (cid,))] + ([c['image']] if c['image'] else [])
    conn.execute('DELETE FROM certs WHERE id=?', (cid,))
    db.audit(conn, user['id'], 'Sertifika sildi', 'cert', cid, f"{c['name']} · {len(paths)} dosya")
    conn.commit()
    for p in paths:
        (config.UPLOAD_DIR / p).unlink(missing_ok=True)
    return {'ok': True}


@router.post('/{cid}/image')
async def set_image(cid: int, file: UploadFile = File(...), user=Depends(cert_user), conn=db.DB):
    """Taranmış sertifika görseli (A4 dikey gösterilir). Eski görsel silinir."""
    c = _cert(conn, cid)
    if not (file.filename or '').lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.tif', '.tiff', '.bmp')):
        raise HTTPException(400, 'Sertifika görseli resim olmalı (JPG / PNG / WEBP / HEIC)')
    path, _size = await save_upload_stream('certs', file, 40 * 1024 * 1024)
    conn.execute('UPDATE certs SET image=?, updated_at=? WHERE id=?', (path, db.now(), cid))
    conn.commit()
    if c['image']:
        (config.UPLOAD_DIR / c['image']).unlink(missing_ok=True)
    return {'image': path}


# ---- Dokümanlar
@router.get('/{cid}/docs')
def docs(cid: int, audit_id: int = 0, user=Depends(cert_user), conn=db.DB):
    _cert(conn, cid)
    where, args = 'd.cert_id=?', [cid]
    if audit_id:
        where += ' AND d.audit_id=?'
        args.append(audit_id)
    return db.rows(conn.execute(f'''SELECT d.*, u.full_name AS uploaded_by_name, a.date AS audit_date, a.kind AS audit_kind
                                   FROM cert_docs d LEFT JOIN users u ON u.id=d.uploaded_by LEFT JOIN cert_audits a ON a.id=d.audit_id
                                   WHERE {where} ORDER BY d.created_at DESC, d.id DESC''', args))


class DocIn(BaseModel):
    upload_id: str
    folder: Optional[str] = None
    audit_id: Optional[int] = None


@router.post('/{cid}/docs')
def add_doc(cid: int, body: DocIn, user=Depends(cert_user), conn=db.DB):
    _cert(conn, cid)
    if body.audit_id and not conn.execute('SELECT 1 FROM cert_audits WHERE id=? AND cert_id=?', (body.audit_id, cid)).fetchone():
        raise HTTPException(404, 'Denetim bulunamadı')
    path, size, name = take_upload(body.upload_id, user, 'certs')
    cur = conn.execute('INSERT INTO cert_docs (cert_id, audit_id, folder, name, path, size, uploaded_by, created_at) VALUES (?,?,?,?,?,?,?,?)',
                       (cid, body.audit_id or None, (body.folder or '').strip()[:80] or None, name[:200], path, size, user['id'], db.now()))
    conn.commit()
    return {'id': cur.lastrowid}


class DocUpd(BaseModel):
    name: Optional[str] = None
    folder: Optional[str] = None


@router.put('/docs/{did}')
def update_doc(did: int, body: DocUpd, user=Depends(cert_user), conn=db.DB):
    d = db.row(conn.execute('SELECT * FROM cert_docs WHERE id=?', (did,)))
    if not d:
        raise HTTPException(404, 'Doküman bulunamadı')
    conn.execute('UPDATE cert_docs SET name=?, folder=? WHERE id=?', ((body.name or d['name']).strip()[:200], (body.folder or '').strip()[:80] or None, did))
    conn.commit()
    return {'ok': True}


@router.delete('/docs/{did}')
def delete_doc(did: int, user=Depends(cert_user), conn=db.DB):
    d = db.row(conn.execute('SELECT * FROM cert_docs WHERE id=?', (did,)))
    if not d:
        raise HTTPException(404, 'Doküman bulunamadı')
    if d['uploaded_by'] != user['id'] and not user.get('master') and 'admin' not in user.get('modules', []):
        raise HTTPException(403, 'Dokümanı yalnızca yükleyen ya da yönetici silebilir')
    conn.execute('DELETE FROM cert_docs WHERE id=?', (did,))
    db.audit(conn, user['id'], 'Sertifika dokümanı sildi', 'cert', d['cert_id'], d['name'][:80])
    conn.commit()
    (config.UPLOAD_DIR / d['path']).unlink(missing_ok=True)
    return {'ok': True}


# ---- Denetimler
class AuditIn(BaseModel):
    date: str
    kind: str = 'gozetim'
    body: Optional[str] = None
    auditor: Optional[str] = None
    result: str = 'planlandi'
    major: int = 0
    minor: int = 0
    observations: int = 0
    capa_due: Optional[str] = None
    next_date: Optional[str] = None
    notes: Optional[str] = None


def _avals(b: AuditIn):
    if not b.date or b.kind not in AUDIT_KINDS or b.result not in AUDIT_RESULTS:
        raise HTTPException(400, 'Tarih, denetim türü ve sonuç gerekli')
    t = lambda v, n=200: ((v or '').strip()[:n] or None)
    return (b.date[:10], b.kind, t(b.body), t(b.auditor), b.result, max(0, b.major), max(0, b.minor), max(0, b.observations),
            (b.capa_due or '')[:10] or None, (b.next_date or '')[:10] or None, t(b.notes, 4000))


@router.get('/audits/all')
def all_audits(user=Depends(cert_user), conn=db.DB):
    """Tüm sertifikaların denetimleri (yaklaşanlar önce)."""
    rows = db.rows(conn.execute('''SELECT a.*, c.name AS cert_name, c.standard,
                                   (SELECT COUNT(*) FROM cert_docs d WHERE d.audit_id=a.id) AS doc_count
                                   FROM cert_audits a JOIN certs c ON c.id=a.cert_id ORDER BY a.date DESC, a.id DESC'''))
    for r in rows:
        r['days_left'] = _days_left(r['date'])
    return {'rows': rows, 'audit_kinds': AUDIT_KINDS, 'audit_results': AUDIT_RESULTS}


@router.post('/{cid}/audits')
def add_audit(cid: int, b: AuditIn, user=Depends(cert_user), conn=db.DB):
    _cert(conn, cid)
    now = db.now()
    cur = conn.execute('''INSERT INTO cert_audits (cert_id, date, kind, body, auditor, result, major, minor, observations, capa_due, next_date, notes,
                          created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (cid, *_avals(b), user['id'], now, now))
    _plan_next(conn, cid, b)
    db.audit(conn, user['id'], 'Denetim kaydı', 'cert', cid, f'{b.date} {AUDIT_KINDS.get(b.kind)}')
    conn.commit()
    return {'id': cur.lastrowid}


def _plan_next(conn, cid, b):
    """Sonraki denetim tarihi girildiyse, o tarihte henüz kayıt yoksa 'planlandı' denetimi otomatik açılır."""
    if b.next_date and b.result != 'planlandi' and not conn.execute(
            'SELECT 1 FROM cert_audits WHERE cert_id=? AND date=?', (cid, b.next_date[:10])).fetchone():
        now = db.now()
        conn.execute('''INSERT INTO cert_audits (cert_id, date, kind, body, result, created_at, updated_at)
                        VALUES (?,?,?,?, 'planlandi', ?, ?)''', (cid, b.next_date[:10], 'gozetim', (b.body or '').strip()[:200] or None, now, now))


@router.put('/audits/{aid}')
def update_audit(aid: int, b: AuditIn, user=Depends(cert_user), conn=db.DB):
    a = db.row(conn.execute('SELECT * FROM cert_audits WHERE id=?', (aid,)))
    if not a:
        raise HTTPException(404, 'Denetim bulunamadı')
    conn.execute('''UPDATE cert_audits SET date=?, kind=?, body=?, auditor=?, result=?, major=?, minor=?, observations=?, capa_due=?, next_date=?,
                    notes=?, updated_at=? WHERE id=?''', (*_avals(b), db.now(), aid))
    _plan_next(conn, a['cert_id'], b)
    conn.commit()
    return {'ok': True}


@router.delete('/audits/{aid}')
def delete_audit(aid: int, user=Depends(cert_user), conn=db.DB):
    a = db.row(conn.execute('SELECT * FROM cert_audits WHERE id=?', (aid,)))
    if not a:
        raise HTTPException(404, 'Denetim bulunamadı')
    paths = [r[0] for r in conn.execute('SELECT path FROM cert_docs WHERE audit_id=?', (aid,))]
    conn.execute('DELETE FROM cert_audits WHERE id=?', (aid,))
    conn.commit()
    for p in paths:
        (config.UPLOAD_DIR / p).unlink(missing_ok=True)
    return {'ok': True}
