"""Şirketten Haberler akışı — /api/feed. Tüm giriş yapmış kullanıcılar görür ve paylaşım ekleyebilir
(resim/video/ses + konum). Sistem olayları app/feed.py üzerinden eklenir."""
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import auth, config, db, feed
from ..files import FILE_GUARDS

router = APIRouter(prefix='/api/feed')
FILE_GUARDS['feed'] = lambda user, name: True   # akış medyası tüm kullanıcılara görünür (giriş zorunlu)

MEDIA_EXT = {'image': {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic'}, 'video': {'.mp4', '.webm', '.mov', '.m4v'},
             'audio': {'.webm', '.ogg', '.oga', '.opus', '.m4a', '.mp3', '.wav', '.weba'}}


def _media_type(ext):
    for t, exts in MEDIA_EXT.items():
        if ext in exts:
            return t
    return None


@router.get('')
def list_feed(since: str = '', located: int = 0, user=Depends(auth.current_user), conn=db.DB):
    return {'posts': feed.list_posts(conn, since or None, located=bool(located), viewer_id=user['id']),
            'reactions': list(feed.REACTIONS)}


class ReactIn(BaseModel):
    emoji: str


@router.post('/{post_id}/react')
def react(post_id: int, body: ReactIn, user=Depends(auth.current_user), conn=db.DB):
    r = feed.react(conn, post_id, user['id'], (body.emoji or '').strip())
    conn.commit()
    return {'ok': True, 'my_reaction': r}


class CommentIn(BaseModel):
    text: str


@router.get('/{post_id}/comments')
def comments(post_id: int, user=Depends(auth.current_user), conn=db.DB):
    return {'comments': feed.list_comments(conn, post_id)}


@router.post('/{post_id}/comments')
def add_comment(post_id: int, body: CommentIn, user=Depends(auth.current_user), conn=db.DB):
    cid = feed.add_comment(conn, post_id, user['id'], body.text)
    if not cid:
        raise HTTPException(400, 'Yorum eklenemedi')
    conn.commit()
    db.audit(conn, user['id'], 'Şirketten Haberler yorumu', 'feed', post_id, body.text[:80])
    return {'ok': True, 'id': cid}


@router.delete('/comments/{comment_id}')
def delete_comment(comment_id: int, user=Depends(auth.current_user), conn=db.DB):
    if feed.delete_comment(conn, comment_id, user):
        conn.commit()
        return {'ok': True}
    raise HTTPException(404, 'Yorum bulunamadı ya da silme yetkiniz yok')


@router.post('')
async def add(text: str = Form(''), lat: Optional[float] = Form(None), lng: Optional[float] = Form(None),
              files: List[UploadFile] = File(default=[]), user=Depends(auth.current_user), conn=db.DB):
    text = (text or '').strip()[:2000]
    if not text and not files:
        raise HTTPException(400, 'Metin ya da en az bir medya ekleyin')
    media = []
    feed_dir = config.UPLOAD_DIR / 'feed'
    feed_dir.mkdir(parents=True, exist_ok=True)
    for f in files[:8]:
        data = await f.read()
        if len(data) > 60 * 1024 * 1024:
            raise HTTPException(413, f'{f.filename}: dosya çok büyük (en çok 60 MB)')
        ext = os.path.splitext(f.filename or '')[1].lower()
        mtype = _media_type(ext)
        if not mtype:
            raise HTTPException(415, f'Desteklenmeyen dosya türü: {ext or f.filename}')
        import secrets
        name = f'{secrets.token_hex(8)}{ext}'
        (feed_dir / name).write_bytes(data)
        media.append({'type': mtype, 'path': f'feed/{name}'})
    pid = feed.add_post(conn, user['id'], text, media, lat, lng)
    conn.commit()
    db.audit(conn, user['id'], 'Şirketten Haberler paylaşımı', 'feed', pid, f'{len(media)} medya')
    return {'ok': True, 'id': pid}


@router.delete('/{post_id}')
def remove(post_id: int, user=Depends(auth.current_user), conn=db.DB):
    if feed.delete(conn, post_id, user):
        conn.commit()
        return {'ok': True}
    raise HTTPException(404, 'Paylaşım bulunamadı ya da silme yetkiniz yok')
