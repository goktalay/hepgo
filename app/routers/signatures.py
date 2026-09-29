"""Evrak imza talepleri (şirket içi dijital imza).

Evrağı görebilen bir kullanıcı, sistemdeki herhangi bir kullanıcıya imza talebi gönderir. İmzalayan kişi evrak
modülüne erişimi olmasa ya da evrak kısıtlı olsa bile yalnızca bu evrakı görebilir (talep süresince ve sonrasında).
İmzala: dosyanın SHA-256 özeti alınır; talep no, evrak no, özet, imzalayan ve zaman sunucunun gizli anahtarıyla
HMAC-SHA256 ile mühürlenir. Doğrulama dosyayı yeniden özetler: dosya değiştiyse ya da kayıt oynandıysa geçersizdir.
"""
import hashlib
import hmac
import os
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, config, db
from .documents import _get as get_visible_document

router = APIRouter(prefix='/api')
KEY_FILE = config.DATA_DIR / 'signing.key'
STATUS = ('BEKLIYOR', 'IMZALANDI', 'REDDEDILDI', 'IPTAL')


class RequestIn(BaseModel):
    user_ids: list[int]
    message: Optional[str] = None


class RejectIn(BaseModel):
    reason: str


def _key():
    """İmza anahtarı: ilk kullanımda üretilir, data/signing.key (yalnızca sahibi okuyabilir)."""
    if not KEY_FILE.exists():
        KEY_FILE.write_text(secrets.token_hex(32))
        os.chmod(KEY_FILE, 0o600)
    return bytes.fromhex(KEY_FILE.read_text().strip())


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _mac(s, sha, signed_at):
    msg = f'{s["id"]}|{s["document_id"]}|{sha}|{s["signer_id"]}|{signed_at}'.encode()
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()


_SELECT = '''SELECT s.*, su.full_name AS signer_name, ru.full_name AS requested_by_name,
                    d.title AS document_title, d.file, d.file_name, d.kind, d.thumb, d.size, d.pages
             FROM document_signatures s JOIN documents d ON d.id = s.document_id
             LEFT JOIN users su ON su.id = s.signer_id LEFT JOIN users ru ON ru.id = s.requested_by'''


def signatures_for(conn, doc_id):
    return db.rows(conn.execute(_SELECT + ' WHERE s.document_id = ? ORDER BY s.id', (doc_id,)))


def signer_can_see(conn, user_id, file_path):
    """Dosya erişimi: kullanıcı bu dosyanın evrakına imzacı olarak atanmış mı?"""
    return conn.execute(
        '''SELECT 1 FROM document_signatures s JOIN documents d ON d.id = s.document_id
           WHERE s.signer_id = ? AND (d.file = ? OR d.thumb = ?)''', (user_id, file_path, file_path)).fetchone() is not None


def _get(conn, sid, user):
    s = db.row(conn.execute(_SELECT + ' WHERE s.id = ?', (sid,)))
    if not s:
        raise HTTPException(404, 'İmza talebi bulunamadı')
    if user['id'] not in (s['signer_id'], s['requested_by']):
        get_visible_document(conn, s['document_id'], user)   # evrağı görebilen de talebi görebilir; göremezse 404
    return s


@router.post('/documents/{doc_id}/signatures')
def request_signatures(doc_id: int, body: RequestIn, user=Depends(auth.require_module('documents')), conn=db.DB):
    d = get_visible_document(conn, doc_id, user)
    ids = sorted(set(body.user_ids))
    if not ids:
        raise HTTPException(400, 'İmzalayacak en az bir kişi seçin')
    created, skipped = [], []
    for uid in ids:
        u = conn.execute('SELECT full_name FROM users WHERE id = ? AND active = 1 AND deleted_at IS NULL', (uid,)).fetchone()
        if not u:
            raise HTTPException(400, 'İmzalayacak kullanıcı bulunamadı')
        if conn.execute("SELECT 1 FROM document_signatures WHERE document_id = ? AND signer_id = ? AND status = 'BEKLIYOR'",
                        (doc_id, uid)).fetchone():
            skipped.append(u[0])
            continue
        cur = conn.execute('''INSERT INTO document_signatures (document_id, signer_id, requested_by, requested_at, message)
                              VALUES (?,?,?,?,?)''', (doc_id, uid, user['id'], db.now(), (body.message or '').strip() or None))
        created.append(cur.lastrowid)
        db.audit(conn, user['id'], 'İmza talebi gönderdi', 'document', doc_id, f'{d["title"]} → {u[0]}')
    return {'created': created, 'skipped': skipped}


@router.get('/signatures')
def list_signatures(box: str = 'inbox', user=Depends(auth.current_user), conn=db.DB):
    """inbox: bana gelen talepler; sent: gönderdiğim talepler."""
    col = 'signer_id' if box == 'inbox' else 'requested_by'
    return db.rows(conn.execute(
        _SELECT + f" WHERE s.{col} = ? ORDER BY s.status != 'BEKLIYOR', s.requested_at DESC LIMIT 500", (user['id'],)))


@router.get('/signatures/{sid}')
def get_signature(sid: int, user=Depends(auth.current_user), conn=db.DB):
    s = _get(conn, sid, user)
    s['others'] = [x for x in signatures_for(conn, s['document_id']) if x['id'] != sid]
    s['can_decide'] = s['signer_id'] == user['id'] and s['status'] == 'BEKLIYOR'
    s['can_cancel'] = s['requested_by'] == user['id'] and s['status'] == 'BEKLIYOR'
    return s


def _decide(conn, sid, user):
    s = _get(conn, sid, user)
    if s['signer_id'] != user['id']:
        raise HTTPException(403, 'Bu talebi yalnızca imzalayacak kişi yanıtlayabilir')
    if s['status'] != 'BEKLIYOR':
        raise HTTPException(400, 'Bu talep zaten sonuçlanmış')
    return s


@router.post('/signatures/{sid}/sign')
async def sign(sid: int, user=Depends(auth.current_user), conn=db.DB):
    s = await run_in_threadpool(_decide, conn, sid, user)
    sha = await run_in_threadpool(_sha256, config.UPLOAD_DIR / s['file'])

    def write():
        signed_at = db.now()
        conn.execute("""UPDATE document_signatures SET status = 'IMZALANDI', decided_at = ?, file_sha256 = ?, signature = ?
                        WHERE id = ? AND status = 'BEKLIYOR'""", (signed_at, sha, _mac(s, sha, signed_at), sid))
        db.audit(conn, user['id'], 'Evrakı imzaladı', 'document', s['document_id'], s['document_title'])
    await run_in_threadpool(write)
    return {'ok': True}


@router.post('/signatures/{sid}/reject')
def reject(sid: int, body: RejectIn, user=Depends(auth.current_user), conn=db.DB):
    s = _decide(conn, sid, user)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, 'Red açıklaması zorunlu')
    conn.execute("UPDATE document_signatures SET status = 'REDDEDILDI', decided_at = ?, reason = ? WHERE id = ?",
                 (db.now(), reason[:2000], sid))
    db.audit(conn, user['id'], 'İmza talebini reddetti', 'document', s['document_id'], f'{s["document_title"]}: {reason[:200]}')
    return {'ok': True}


@router.post('/signatures/{sid}/cancel')
def cancel(sid: int, user=Depends(auth.current_user), conn=db.DB):
    s = _get(conn, sid, user)
    if s['requested_by'] != user['id'] or s['status'] != 'BEKLIYOR':
        raise HTTPException(400, 'Yalnızca kendi gönderdiğiniz, bekleyen talebi geri çekebilirsiniz')
    conn.execute("UPDATE document_signatures SET status = 'IPTAL', decided_at = ? WHERE id = ?", (db.now(), sid))
    db.audit(conn, user['id'], 'İmza talebini geri çekti', 'document', s['document_id'], f'{s["document_title"]} → {s["signer_name"]}')
    return {'ok': True}


@router.get('/signatures/{sid}/verify')
async def verify(sid: int, user=Depends(auth.current_user), conn=db.DB):
    s = await run_in_threadpool(_get, conn, sid, user)
    if s['status'] != 'IMZALANDI':
        raise HTTPException(400, 'Evrak bu talepte imzalanmamış')
    path = config.UPLOAD_DIR / s['file']
    sha = await run_in_threadpool(_sha256, path) if path.exists() else None
    unchanged = sha == s['file_sha256']
    sealed = hmac.compare_digest(_mac(s, s['file_sha256'], s['decided_at']), s['signature'] or '')
    return {'valid': unchanged and sealed, 'file_unchanged': unchanged, 'seal_ok': sealed}
