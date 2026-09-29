"""Kullanıcılar arası canlı mesajlaşma (birebir).

Durum çubuğundaki çevrimiçi kişilere ya da başlıktaki mesaj düğmesine tıklanınca sohbet penceresi açılır. Mesaj metin, dosya,
resim ya da bas-konuş ses kaydı olabilir. Pencere açıkken yeni mesajlar ~2 sn'de bir çekilir (after=son id); karşı tarafın
mesajları pencere açılınca okundu sayılır. Başlıktaki düğme okunmamış mesajları gönderene göre gruplar.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import auth, config, db
from ..files import FILE_GUARDS, save_upload
from .admin import ONLINE_WINDOW

router = APIRouter(prefix='/api/chat')
IMAGE = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif'}
AUDIO = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.weba'}
PAGE = 60


# Gizlilik (Ayarlar → Gizlilik; users.prefs.settings.privacy): çevrimiçi durumu gizle, okundu bilgisi gönderme, mesaj alma
PRIV = lambda col: f"IFNULL(json_extract(u.prefs, '$.settings.privacy.{col}'), 0)"


def privacy(conn, uid):
    r = conn.execute('SELECT prefs FROM users WHERE id = ?', (uid,)).fetchone()
    try:
        return (json.loads(r[0]) if r and r[0] else {}).get('settings', {}).get('privacy', {}) or {}
    except ValueError:
        return {}


def _peer(conn, uid, me):
    if uid == me['id']:
        raise HTTPException(400, 'Kendinize mesaj gönderemezsiniz')
    u = db.row(conn.execute('SELECT id, full_name, photo, last_seen, active FROM users WHERE id = ? AND deleted_at IS NULL', (uid,)))
    if not u:
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    p = privacy(conn, uid)
    if p.get('hide_online'):
        u['last_seen'] = None
    u['online'] = bool(u['last_seen'] and u['last_seen'] >= (datetime.now() - ONLINE_WINDOW).isoformat(timespec='seconds'))
    u['no_messages'] = bool(p.get('no_messages'))
    u['hide_read'] = bool(p.get('hide_read'))
    return u


@router.get('/summary')
def summary(user=Depends(auth.current_user), conn=db.DB):
    """Başlık düğmesi: son sohbetler (kişi başına bir satır), okunmamış sayısı gönderene göre."""
    me = user['id']
    rows = db.rows(conn.execute(
        '''WITH last AS (
               SELECT CASE WHEN from_id = ? THEN to_id ELSE from_id END AS peer, MAX(id) AS mid
               FROM chat_messages WHERE from_id = ? OR to_id = ? GROUP BY peer)
           SELECT u.id, u.full_name, u.photo, CASE WHEN {hide} THEN NULL ELSE u.last_seen END AS last_seen, m.body, m.file_kind, m.file_name, m.from_id, m.created_at,
                  (SELECT COUNT(*) FROM chat_messages x WHERE x.from_id = u.id AND x.to_id = ? AND x.read_at IS NULL) AS unread
           FROM last JOIN chat_messages m ON m.id = last.mid JOIN users u ON u.id = last.peer
           ORDER BY unread > 0 DESC, m.id DESC LIMIT 30'''.replace('{hide}', PRIV('hide_online')), (me, me, me, me)))
    cut = (datetime.now() - ONLINE_WINDOW).isoformat(timespec='seconds')
    for r in rows:
        r['online'] = bool(r['last_seen'] and r['last_seen'] >= cut)
        r['mine'] = r.pop('from_id') == me
    return {'people': sum(1 for r in rows if r['unread']), 'unread': sum(r['unread'] for r in rows), 'items': rows}


@router.get('/{uid}')
def messages(uid: int, after: int = 0, before: int = 0, user=Depends(auth.current_user), conn=db.DB):
    """Sohbet: after verilirse yalnızca yeniler, before verilirse daha eskiler; yoksa son 60 mesaj. Gelenler okundu olur."""
    peer = _peer(conn, uid, user)
    me = user['id']
    pair = '((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))'
    args = (me, uid, uid, me)
    if after:
        rows = db.rows(conn.execute(f'SELECT * FROM chat_messages WHERE {pair} AND id > ? ORDER BY id LIMIT 500', (*args, after)))
    else:
        cond = 'AND id < ?' if before else ''
        rows = db.rows(conn.execute(f'SELECT * FROM chat_messages WHERE {pair} {cond} ORDER BY id DESC LIMIT {PAGE}',
                                    (*args, before) if before else args))[::-1]
    conn.execute('UPDATE chat_messages SET read_at = ? WHERE from_id = ? AND to_id = ? AND read_at IS NULL', (db.now(), uid, me))
    # Gönderdiklerimin okundu bilgisi (pencere açıkken çift tik güncellensin)
    seen = conn.execute('SELECT MAX(id) FROM chat_messages WHERE from_id = ? AND to_id = ? AND read_at IS NOT NULL', (me, uid)).fetchone()[0]
    if peer['hide_read'] or privacy(conn, me).get('hide_read'):   # okundu bilgisi karşılıklı kapanır
        seen = 0
    return {'peer': peer, 'items': rows, 'seen_upto': seen or 0, 'more': not after and len(rows) == PAGE}


@router.post('/{uid}')
async def send(uid: int, body: str = Form(''), duration: Optional[float] = Form(None), file: Optional[UploadFile] = File(None),
               user=Depends(auth.current_user), conn=db.DB):
    text = (body or '').strip()[:5000]
    has_file = file is not None and file.filename
    if not text and not has_file:
        raise HTTPException(400, 'Mesaj boş')
    path = await save_upload('chat', file) if has_file else None

    def write():
        peer = _peer(conn, uid, user)
        if not peer['active']:
            raise HTTPException(400, 'Bu kullanıcı pasif')
        if peer['no_messages']:
            raise HTTPException(400, f'{peer["full_name"]} mesaj almayı kapatmış')
        kind = size = name = None
        if path:
            ext = Path(path).suffix.lower()
            kind = 'image' if ext in IMAGE else 'audio' if ext in AUDIO or (ext == '.webm' and duration) else 'file'
            name = Path(file.filename).name[:200]
            size = (config.UPLOAD_DIR / path).stat().st_size
        cur = conn.execute('''INSERT INTO chat_messages (from_id, to_id, body, file, file_name, file_kind, file_size, duration, created_at)
                              VALUES (?,?,?,?,?,?,?,?,?)''',
                           (user['id'], uid, text or None, path, name, kind, size, round(duration, 1) if duration else None, db.now()))
        return db.row(conn.execute('SELECT * FROM chat_messages WHERE id = ?', (cur.lastrowid,)))
    return await run_in_threadpool(write)


def _chat_guard(user, name):
    with db.connect() as conn:
        return conn.execute('SELECT 1 FROM chat_messages WHERE file = ? AND (from_id = ? OR to_id = ?)',
                            (f'chat/{name}', user['id'], user['id'])).fetchone() is not None


FILE_GUARDS['chat'] = _chat_guard
