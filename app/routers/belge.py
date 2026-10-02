"""Evrak › Belge Yönetim: uygulama içi ofis belgeleri (Excel/Word/Sunum).

Her belge bir sahibe aittir. Varsayılan erişim: Evrak modülü olan herkes GÖRÜNTÜLER (salt-okunur).
Sahip, bir kullanıcıya 'write' izni verirse o kişi düzenleyebilir. Her kaydetmede önceki içerik sürüm
geçmişine alınır; eski sürümler görülebilir ve geri yüklenebilir. Silme/paylaşım yalnız sahip (veya MASTER).
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/belge')
belge_user = auth.require_module('documents')

KINDS = {'excel', 'word', 'sunum'}
DEFAULT = {
    'excel': {'rows': 40, 'cols': 12, 'cells': {}},
    'word': {'html': ''},
    'sunum': {'slides': [{'html': ''}]},
}


def _doc(conn, did):
    d = db.row(conn.execute('SELECT * FROM office_docs WHERE id=? AND deleted_at IS NULL', (did,)))
    if not d:
        raise HTTPException(404, 'Belge bulunamadı')
    return d


def _perm(conn, d, user):
    if user.get('master') or d['owner_id'] == user['id']:
        return 'owner'
    s = db.row(conn.execute('SELECT perm FROM office_shares WHERE doc_id=? AND user_id=?', (d['id'], user['id'])))
    if s and s['perm'] == 'write':
        return 'write'
    return 'read'


def _can_write(perm):
    return perm in ('owner', 'write')


def _public(conn, d, user):
    perm = _perm(conn, d, user)
    owner = db.row(conn.execute('SELECT full_name FROM users WHERE id=?', (d['owner_id'],)))
    out = {'id': d['id'], 'kind': d['kind'], 'title': d['title'], 'owner_id': d['owner_id'],
           'owner_name': owner['full_name'] if owner else '—', 'updated_at': d['updated_at'],
           'created_at': d['created_at'], 'my_perm': perm, 'can_write': _can_write(perm)}
    return out


@router.get('')
def list_docs(kind: str = '', user=Depends(belge_user), conn=db.DB):
    where = 'WHERE deleted_at IS NULL'
    args = []
    if kind in KINDS:
        where += ' AND kind=?'
        args.append(kind)
    rows = db.rows(conn.execute(f'SELECT * FROM office_docs {where} ORDER BY updated_at DESC', args))
    return [_public(conn, d, user) for d in rows]


class CreateIn(BaseModel):
    kind: str
    title: str = ''


@router.post('')
def create_doc(body: CreateIn, user=Depends(belge_user), conn=db.DB):
    if body.kind not in KINDS:
        raise HTTPException(400, 'Geçersiz belge türü')
    title = (body.title or '').strip() or {'excel': 'Yeni Çalışma Sayfası', 'word': 'Yeni Belge', 'sunum': 'Yeni Sunum'}[body.kind]
    now = db.now()
    cur = conn.execute('INSERT INTO office_docs(kind,title,owner_id,content,created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,?)',
                       (body.kind, title[:200], user['id'], json.dumps(DEFAULT[body.kind]), now, now, user['id']))
    db.audit(conn, user['id'], 'Belge oluşturdu', 'office', cur.lastrowid, f'{body.kind}: {title}')
    conn.commit()
    d = _doc(conn, cur.lastrowid)
    out = _public(conn, d, user)
    out['content'] = json.loads(d['content'] or '{}')
    return out


@router.get('/{did}')
def get_doc(did: int, user=Depends(belge_user), conn=db.DB):
    d = _doc(conn, did)
    out = _public(conn, d, user)
    try:
        out['content'] = json.loads(d['content'] or '{}')
    except ValueError:
        out['content'] = DEFAULT.get(d['kind'], {})
    if out['my_perm'] == 'owner':
        out['shares'] = db.rows(conn.execute(
            '''SELECT s.user_id, s.perm, u.full_name FROM office_shares s JOIN users u ON u.id=s.user_id
               WHERE s.doc_id=? ORDER BY u.full_name''', (did,)))
    return out


class SaveIn(BaseModel):
    title: str | None = None
    content: dict | list | None = None


@router.put('/{did}')
def save_doc(did: int, body: SaveIn, user=Depends(belge_user), conn=db.DB):
    d = _doc(conn, did)
    if not _can_write(_perm(conn, d, user)):
        raise HTTPException(403, 'Bu belgeyi düzenleme izniniz yok')
    now = db.now()
    if body.content is not None:
        # önceki içeriği sürüm geçmişine al (boş değilse)
        if d['content'] and d['content'] not in ('', '{}'):
            conn.execute('INSERT INTO office_versions(doc_id,content,saved_at,saved_by) VALUES(?,?,?,?)',
                         (did, d['content'], d['updated_at'], d['updated_by']))
            # en çok 50 sürüm sakla
            conn.execute('''DELETE FROM office_versions WHERE doc_id=? AND id NOT IN
                            (SELECT id FROM office_versions WHERE doc_id=? ORDER BY id DESC LIMIT 50)''', (did, did))
        conn.execute('UPDATE office_docs SET content=?, updated_at=?, updated_by=? WHERE id=?',
                     (json.dumps(body.content), now, user['id'], did))
    if body.title is not None and body.title.strip():
        conn.execute('UPDATE office_docs SET title=?, updated_at=? WHERE id=?', (body.title.strip()[:200], now, did))
    conn.commit()
    return {'ok': True, 'updated_at': now}


@router.delete('/{did}')
def delete_doc(did: int, user=Depends(belge_user), conn=db.DB):
    d = _doc(conn, did)
    if _perm(conn, d, user) != 'owner':
        raise HTTPException(403, 'Yalnızca belge sahibi silebilir')
    conn.execute('UPDATE office_docs SET deleted_at=? WHERE id=?', (db.now(), did))
    db.audit(conn, user['id'], 'Belge sildi', 'office', did, d['title'])
    conn.commit()
    return {'ok': True}


# ---------- Sürüm geçmişi
@router.get('/{did}/versions')
def versions(did: int, user=Depends(belge_user), conn=db.DB):
    _doc(conn, did)
    return db.rows(conn.execute(
        '''SELECT v.id, v.saved_at, u.full_name AS saved_by_name FROM office_versions v
           LEFT JOIN users u ON u.id=v.saved_by WHERE v.doc_id=? ORDER BY v.id DESC''', (did,)))


@router.get('/{did}/versions/{vid}')
def version_content(did: int, vid: int, user=Depends(belge_user), conn=db.DB):
    _doc(conn, did)
    v = db.row(conn.execute('SELECT * FROM office_versions WHERE id=? AND doc_id=?', (vid, did)))
    if not v:
        raise HTTPException(404, 'Sürüm bulunamadı')
    try:
        content = json.loads(v['content'] or '{}')
    except ValueError:
        content = {}
    return {'id': v['id'], 'saved_at': v['saved_at'], 'content': content}


@router.post('/{did}/versions/{vid}/restore')
def restore_version(did: int, vid: int, user=Depends(belge_user), conn=db.DB):
    d = _doc(conn, did)
    if not _can_write(_perm(conn, d, user)):
        raise HTTPException(403, 'Düzenleme izniniz yok')
    v = db.row(conn.execute('SELECT content FROM office_versions WHERE id=? AND doc_id=?', (vid, did)))
    if not v:
        raise HTTPException(404, 'Sürüm bulunamadı')
    now = db.now()
    # mevcut içeriği de geçmişe al, sonra eski sürümü geri yükle
    conn.execute('INSERT INTO office_versions(doc_id,content,saved_at,saved_by) VALUES(?,?,?,?)',
                 (did, d['content'], d['updated_at'], d['updated_by']))
    conn.execute('UPDATE office_docs SET content=?, updated_at=?, updated_by=? WHERE id=?', (v['content'], now, user['id'], did))
    db.audit(conn, user['id'], 'Belge sürümü geri yükledi', 'office', did, f'v{vid}')
    conn.commit()
    return {'ok': True}


# ---------- Paylaşım (yalnız sahip)
class ShareIn(BaseModel):
    user_id: int
    perm: str = 'write'


def _owner_only(conn, did, user):
    d = _doc(conn, did)
    if _perm(conn, d, user) != 'owner':
        raise HTTPException(403, 'Yalnızca belge sahibi paylaşımı yönetebilir')
    return d


@router.get('/{did}/shares')
def list_shares(did: int, user=Depends(belge_user), conn=db.DB):
    _owner_only(conn, did, user)
    return db.rows(conn.execute(
        '''SELECT s.user_id, s.perm, u.full_name FROM office_shares s JOIN users u ON u.id=s.user_id
           WHERE s.doc_id=? ORDER BY u.full_name''', (did,)))


@router.post('/{did}/shares')
def add_share(did: int, body: ShareIn, user=Depends(belge_user), conn=db.DB):
    d = _owner_only(conn, did, user)
    if body.user_id == d['owner_id']:
        raise HTTPException(400, 'Sahip zaten tam yetkilidir')
    if not db.row(conn.execute('SELECT 1 FROM users WHERE id=?', (body.user_id,))):
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    perm = 'write' if body.perm == 'write' else 'read'
    conn.execute('INSERT INTO office_shares(doc_id,user_id,perm) VALUES(?,?,?) '
                 'ON CONFLICT(doc_id,user_id) DO UPDATE SET perm=excluded.perm', (did, body.user_id, perm))
    conn.commit()
    return {'ok': True}


@router.delete('/{did}/shares/{uid}')
def remove_share(did: int, uid: int, user=Depends(belge_user), conn=db.DB):
    _owner_only(conn, did, user)
    conn.execute('DELETE FROM office_shares WHERE doc_id=? AND user_id=?', (did, uid))
    conn.commit()
    return {'ok': True}
