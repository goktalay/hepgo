"""Araçlar › Notepad Master (web) — kullanıcı başına sunucu dosyaları: DATA_DIR/tools/notes/<uid>/.

Dosya adı güvenli (dizin ayracı yok); en çok 2 MB metin. Tarayıcı tarafında otomatik kayıt localStorage'da.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .tools_common import safe_name, tools_user, user_dir

router = APIRouter(prefix='/api/tools/notepad')
MAX_LEN = 2 * 1024 * 1024


def _p(user, name):
    n = safe_name(name, '')
    if not n:
        raise HTTPException(400, 'Dosya adı gerekli')
    return user_dir('notes', user['id']) / n


@router.get('/files')
def list_files(user=Depends(tools_user)):
    d = user_dir('notes', user['id'])
    out = []
    for p in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            st = p.stat()
            out.append({'name': p.name, 'size': st.st_size, 'mtime': int(st.st_mtime)})
    return out


@router.get('/file')
def read_file(name: str, user=Depends(tools_user)):
    p = _p(user, name)
    if not p.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return {'name': p.name, 'content': p.read_text('utf-8', errors='replace')}


class FileIn(BaseModel):
    name: str
    content: str = ''


@router.put('/file')
def write_file(body: FileIn, user=Depends(tools_user)):
    if len(body.content.encode('utf-8')) > MAX_LEN:
        raise HTTPException(413, 'Dosya 2 MB sınırını aşıyor')
    p = _p(user, body.name)
    p.write_text(body.content, 'utf-8')
    return {'name': p.name, 'size': p.stat().st_size}


@router.delete('/file')
def delete_file(name: str, user=Depends(tools_user)):
    p = _p(user, name)
    if p.is_file():
        p.unlink()
    return {'ok': True}
