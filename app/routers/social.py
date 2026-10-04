"""Kişisel sosyal medya (Kişisel Ayarlar › Sosyal Medya) — /api/social. Hesaplar ve paylaşımlar yalnız sahibine görünür;
Şirketten Haberler akışına (açık olan hesaplar) yalnız sahibinin ekranında karışır."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, db, social

router = APIRouter(prefix='/api/social')


def _acc(conn, user, aid):
    a = db.row(conn.execute('SELECT * FROM social_accounts WHERE id = ? AND user_id = ?', (aid, user['id'])))
    if not a:
        raise HTTPException(404, 'Hesap bulunamadı')
    return a


def _pub(a):
    return {k: a[k] for k in ('id', 'provider', 'handle', 'display_name', 'avatar', 'show_in_feed', 'last_sync', 'last_error', 'created_at')}


@router.get('/accounts')
def accounts(user=Depends(auth.current_user), conn=db.DB):
    rows = db.rows(conn.execute('''SELECT a.*, (SELECT COUNT(*) FROM social_posts p WHERE p.account_id = a.id) AS posts
                                   FROM social_accounts a WHERE a.user_id = ? ORDER BY a.id''', (user['id'],)))
    return {'accounts': [dict(_pub(a), posts=a['posts']) for a in rows], 'providers': social.PROVIDERS, 'available': social.available(),
            'feed_on': _feed_on(conn, user)}


def _feed_on(conn, user):
    r = conn.execute("SELECT value FROM user_prefs WHERE user_id = ? AND key = 'social.feed'", (user['id'],)).fetchone()
    return (r[0] if r else '1') != '0'


class AccIn(BaseModel):
    provider: str
    handle: str


@router.post('/accounts')
async def add(body: AccIn, user=Depends(auth.current_user), conn=db.DB):
    if body.provider not in social.PROVIDERS:
        raise HTTPException(400, 'Bilinmeyen sağlayıcı')
    if not body.handle.strip():
        raise HTTPException(400, 'Hesap / adres girin')
    if conn.execute('SELECT COUNT(*) FROM social_accounts WHERE user_id = ?', (user['id'],)).fetchone()[0] >= 20:
        raise HTTPException(400, 'En fazla 20 hesap bağlanabilir')
    try:
        name, avatar, feed_url, posts = await run_in_threadpool(social.resolve, body.provider, body.handle)
    except social.SocialError as e:
        raise HTTPException(400, str(e)) from e
    cur = conn.execute('''INSERT INTO social_accounts (user_id, provider, handle, feed_url, display_name, avatar, last_sync, created_at)
                          VALUES (?,?,?,?,?,?,?,?)''', (user['id'], body.provider, body.handle.strip()[:300], feed_url, (name or '')[:200], avatar, db.now(), db.now()))
    social.store(conn, cur.lastrowid, posts)
    conn.commit()
    return _pub(_acc(conn, user, cur.lastrowid))


class AccUpd(BaseModel):
    show_in_feed: Optional[bool] = None


@router.put('/accounts/{aid}')
def update(aid: int, body: AccUpd, user=Depends(auth.current_user), conn=db.DB):
    _acc(conn, user, aid)
    if body.show_in_feed is not None:
        conn.execute('UPDATE social_accounts SET show_in_feed = ? WHERE id = ?', (int(body.show_in_feed), aid))
    conn.commit()
    return _pub(_acc(conn, user, aid))


@router.post('/accounts/{aid}/refresh')
async def refresh(aid: int, user=Depends(auth.current_user), conn=db.DB):
    a = _acc(conn, user, aid)
    n = await run_in_threadpool(social.refresh, conn, a)
    return {'new': n, **_pub(_acc(conn, user, aid))}


@router.delete('/accounts/{aid}')
def delete(aid: int, user=Depends(auth.current_user), conn=db.DB):
    _acc(conn, user, aid)
    conn.execute('DELETE FROM social_accounts WHERE id = ?', (aid,))
    conn.commit()
    return {'ok': True}


class FeedOn(BaseModel):
    on: bool


@router.put('/feed-on')
def feed_on(body: FeedOn, user=Depends(auth.current_user), conn=db.DB):
    conn.execute("INSERT INTO user_prefs (user_id, key, value) VALUES (?, 'social.feed', ?) ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
                 (user['id'], '1' if body.on else '0'))
    conn.commit()
    return {'on': body.on}


@router.get('/feed')
def feed(before: str = '', after: str = '', limit: int = 30, user=Depends(auth.current_user), conn=db.DB):
    """Şirketten Haberler'e karışan kişisel paylaşımlar: (after, before] aralığı, yeni → eski. Yalnız sahibinin hesapları."""
    if not _feed_on(conn, user):
        return {'posts': [], 'on': False}
    w, a = ['a.user_id = ?', 'a.show_in_feed = 1'], [user['id']]
    if before:
        w.append('p.posted_at < ?'); a.append(before)
    if after:
        w.append('p.posted_at >= ?'); a.append(after)
    rows = db.rows(conn.execute(f'''SELECT p.*, a.provider, a.display_name, a.handle, a.avatar FROM social_posts p JOIN social_accounts a ON a.id = p.account_id
                                    WHERE {' AND '.join(w)} ORDER BY p.posted_at DESC LIMIT ?''', (*a, max(1, min(limit, 100)))))
    return {'posts': rows, 'on': True}
