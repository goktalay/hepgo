"""Kişisel sosyal medya (Kişisel Ayarlar › Sosyal Medya) — /api/social. Hesaplar ve paylaşımlar yalnız sahibine görünür;
Şirketten Haberler akışına (açık olan hesaplar) yalnız sahibinin ekranında karışır."""
import json
import secrets
import time
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .. import auth, db, social
from ..cameras import encrypt
from .mail import _base   # OAuth dönüş adresi: kullanıcının girdiği alan adı (mail ile aynı kural)

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
    if social.PROVIDERS[body.provider].get('oauth'):
        raise HTTPException(400, f"{social.PROVIDERS[body.provider]['title']} hesabı “ile bağlan” düğmesiyle eklenir")
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
    a = _acc(conn, user, aid)
    if a['provider'] == 'x' and a['token']:
        social.x_revoke(a)   # X'teki izni de geri al
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


# ---------------- OAuth: “X ile bağlan” ----------------
_states = {}   # durum jetonu → (kullanıcı, sağlayıcı, code_verifier, zaman)


def _redirect_uri(request, prov):
    return f'{_base(request)}/api/social/oauth/{prov}/callback'


@router.get('/oauth/{prov}/start')
def oauth_start(prov: str, request: Request, user=Depends(auth.current_user)):
    if prov not in social.IMPLEMENTED:
        raise HTTPException(404, 'Bu sağlayıcıyla bağlanma desteklenmiyor')
    if not social.available()[prov]:
        raise HTTPException(400, f"{social.PROVIDERS[prov]['title']} bağlantısı bu sunucuda henüz ayarlanmadı (Program Ayarları › Entegrasyonlar)")
    now = time.time()
    for k in [k for k, v in _states.items() if now - v[3] > 600]:
        _states.pop(k, None)
    state = secrets.token_urlsafe(24)
    url, verifier = social.x_auth_url(_redirect_uri(request, prov), state)
    _states[state] = (user['id'], prov, verifier, now)
    return {'url': url}


@router.get('/oauth/{prov}/callback')
def oauth_callback(prov: str, request: Request, state: str = '', code: str = '', error: str = '', error_description: str = '',
                   user=Depends(auth.current_user), conn=db.DB):
    back = lambda msg: RedirectResponse(f'/app#/settings/social?msg={quote(msg, safe="")}', status_code=303)  # noqa: E731
    st = _states.pop(state, None)
    if not st or st[0] != user['id'] or st[1] != prov or time.time() - st[3] > 600:
        return back('Bağlantı isteği geçersiz ya da süresi doldu; yeniden deneyin')
    if error or not code:   # X'in verdiği açıklama gösterilir (ör. access_denied, invalid_request: redirect_uri…)
        return back(f"X izin vermedi: {error_description or error}"[:200] if error and error != 'access_denied' else 'İzin verilmedi')
    try:
        tok = social.x_exchange(code, st[2], _redirect_uri(request, prov))
        uid, username, name, avatar = social.x_me(tok['access'])
    except social.SocialError as e:
        return back(str(e))
    except Exception:   # noqa: BLE001
        return back('X’e bağlanılamadı; yeniden deneyin')
    tok['uid'] = uid
    secret = encrypt(json.dumps(tok))
    old = conn.execute("SELECT id FROM social_accounts WHERE user_id = ? AND provider = 'x' AND lower(handle) = ?",
                       (user['id'], f'@{username}'.lower())).fetchone()
    if old:
        aid = old[0]
        conn.execute('UPDATE social_accounts SET token = ?, display_name = ?, avatar = ?, last_error = NULL WHERE id = ?',
                     (secret, name[:200], avatar, aid))
    else:
        if conn.execute('SELECT COUNT(*) FROM social_accounts WHERE user_id = ?', (user['id'],)).fetchone()[0] >= 20:
            return back('En fazla 20 hesap bağlanabilir')
        aid = conn.execute('''INSERT INTO social_accounts (user_id, provider, handle, display_name, avatar, token, last_sync, created_at)
                              VALUES (?,?,?,?,?,?,?,?)''', (user['id'], 'x', f'@{username}', name[:200], avatar, secret, None, db.now())).lastrowid
    conn.commit()
    social.refresh(conn, _acc(conn, user, aid))   # ilk paylaşımlar (hata olursa hesapta gösterilir)
    return back('ok')
