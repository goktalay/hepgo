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
def list_feed(since: str = '', located: int = 0, saved: int = 0, limit: int = 60, before_at: str = '', before_id: int = 0,
              after: int = 0, user=Depends(auth.current_user), conn=db.DB):
    """Akış sayfa sayfa: limit + before_at/before_id (sonraki sayfa), after (canlı: bu id'den yeniler)."""
    before = (before_at, before_id) if before_at and before_id else None
    return {'posts': feed.list_posts(conn, since or None, limit=max(1, min(limit, 300)), located=bool(located), viewer_id=user['id'],
                                     saved=bool(saved), before=before, after=after or None),
            'reactions': list(feed.REACTIONS)}


@router.post('/{post_id}/save')
def save(post_id: int, user=Depends(auth.current_user), conn=db.DB):
    r = feed.toggle_save(conn, post_id, user['id'])
    if r is None:
        raise HTTPException(404, 'Paylaşım bulunamadı')
    conn.commit()
    return {'ok': True, 'saved': r}


class ReactIn(BaseModel):
    emoji: str


@router.post('/{post_id}/react')
def react(post_id: int, body: ReactIn, user=Depends(auth.current_user), conn=db.DB):
    r = feed.react(conn, post_id, user['id'], (body.emoji or '').strip())
    conn.commit()
    return {'ok': True, 'my_reaction': r}


class CommentIn(BaseModel):
    text: str
    parent_id: Optional[int] = None   # yanıt: hangi yoruma


@router.get('/{post_id}/comments')
def comments(post_id: int, user=Depends(auth.current_user), conn=db.DB):
    return {'comments': feed.list_comments(conn, post_id, user['id'])}


@router.post('/comments/{comment_id}/like')
def like_comment(comment_id: int, user=Depends(auth.current_user), conn=db.DB):
    r = feed.like_comment(conn, comment_id, user['id'])
    if r is None:
        raise HTTPException(404, 'Yorum bulunamadı')
    conn.commit()
    return {'ok': True, 'liked': r[0], 'like_count': r[1]}


@router.get('/comments/{comment_id}/likes')
def comment_likes(comment_id: int, user=Depends(auth.current_user), conn=db.DB):
    """Yorumu kimlerin beğendiği — yalnızca yorumun sahibi görür (paylaşım tepkileriyle aynı mantık)."""
    row = conn.execute('SELECT user_id FROM feed_comments WHERE id=? AND deleted_at IS NULL', (comment_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Yorum bulunamadı')
    if row[0] != user['id'] and not user.get('master') and 'admin' not in user.get('modules', []):
        raise HTTPException(403, 'Beğenenleri yalnızca yorum sahibi görebilir')
    return {'likes': feed.comment_likers(conn, comment_id)}


@router.post('/{post_id}/comments')
def add_comment(post_id: int, body: CommentIn, user=Depends(auth.current_user), conn=db.DB):
    cid = feed.add_comment(conn, post_id, user['id'], body.text, body.parent_id)
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
    raise HTTPException(403, 'Yalnızca kendi yorumunuzu silebilirsiniz')


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
    db.audit(conn, user['id'], 'Şirketten Haberler paylaşımı', 'feed', pid, f'{len(media)} medya')
    conn.commit()   # yazma kilidi bırakılmadan await edilmesin (aksi halde eşzamanlı istekler kilide takılır)
    await _announce(conn, pid, user, text, media)
    return {'ok': True, 'id': pid}


async def _announce(conn, pid, user, text, media):
    """Yeni paylaşım: bağlı herkese anlık olay (ana ekrandaysa akışa düşer, değilse zil/kutu bildirimi tetiklenir);
    uygulaması kapalı/arka planda olanlara telefon bildirimi (tıklayınca ana ekran). Hata akışı bozmaz."""
    visible = set()
    try:   # yalnız tetik: içerik (yazar, metin) oturumlu GET /api/feed ile alınır — kapanmış oturumlara veri sızmaz
        from . import voice
        visible = voice.visible_uids()
        await voice.broadcast_users({'t': 'feed', 'id': pid})
    except Exception:   # noqa: BLE001
        pass
    try:   # tek push kaynağı (dakikalık tarama 'feed-new' için push atmaz: notifications push=False)
        from .. import push
        ids = feed.push_recipients(conn, user['id'], exclude=visible)
        push.send(ids, {'type': 'notif', 'title': 'Şirketten Haberler: yeni paylaşım', 'tag': 'notif-feed-new',
                        'body': f"{user['full_name']}: {feed.snippet(text, media)}", 'url': '/app#/home'})
    except Exception:   # noqa: BLE001
        pass


class SeenIn(BaseModel):
    last_id: int


class ViewsIn(BaseModel):
    ids: list


@router.post('/views')
def views(body: ViewsIn, user=Depends(auth.current_user), conn=db.DB):
    """Paylaşımlar ekranda göründü (ilk görünme kaydedilir; tekrarlar yok sayılır)."""
    ids = [int(i) for i in (body.ids or [])[:200] if str(i).isdigit()]
    if ids:
        now = db.now()
        conn.executemany('INSERT OR IGNORE INTO feed_views (post_id, user_id, at) VALUES (?,?,?)', [(i, user['id'], now) for i in ids])
        conn.commit()
    return {'ok': True, 'n': len(ids)}


@router.get('/{post_id}/viewers')
def viewers(post_id: int, user=Depends(auth.current_user), conn=db.DB):
    """Paylaşımı kimler görmüş — yalnız master (sistem sahibi)."""
    if not user.get('master'):
        raise HTTPException(403, 'Yalnız sistem sahibi görebilir')
    rows = db.rows(conn.execute('''SELECT v.user_id, v.at, u.full_name, u.photo FROM feed_views v JOIN users u ON u.id = v.user_id
                                   WHERE v.post_id = ? ORDER BY v.at DESC''', (post_id,)))
    total = conn.execute('SELECT COUNT(*) FROM users WHERE active = 1 AND deleted_at IS NULL').fetchone()[0]
    return {'count': len(rows), 'total_users': total, 'items': rows}


@router.post('/seen')
def seen(body: SeenIn, user=Depends(auth.current_user), conn=db.DB):
    """Kullanıcı akışı ana ekranda gördü: yeni paylaşım bildirimi kalkar."""
    v = feed.mark_seen(conn, user['id'], body.last_id)
    conn.commit()
    return {'ok': True, 'seen': v}


@router.get('/{post_id}/reactions')
def reactions(post_id: int, user=Depends(auth.current_user), conn=db.DB):
    """Paylaşıma kimlerin tepki verdiği — yalnızca paylaşım sahibi ve yönetici/sistem sahibi görür."""
    row = conn.execute('SELECT author_id FROM feed_posts WHERE id=? AND deleted_at IS NULL', (post_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Paylaşım bulunamadı')
    if row[0] != user['id'] and not user.get('master') and 'admin' not in user.get('modules', []):
        raise HTTPException(403, 'Tepki verenleri yalnızca paylaşım sahibi görebilir')
    return {'reactions': feed.reactors(conn, post_id)}


@router.delete('/{post_id}')
def remove(post_id: int, user=Depends(auth.current_user), conn=db.DB):
    if feed.delete(conn, post_id, user):
        conn.commit()
        return {'ok': True}
    raise HTTPException(403, 'Yalnızca kendi paylaşımınızı silebilirsiniz')
