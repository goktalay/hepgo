"""Spotify — /api/spotify. Her kullanıcının kendi hesabı: anlık çalan parça, oynatma kontrolü, çalma listeleri, arama.

OAuth bağlanma akışı mail / social ile aynı desendedir: /oauth/start yetki adresini verir, /oauth/callback kodu jetonlarla
değişir ve refresh_token'ı şifreli olarak social_accounts(provider='spotify') içine yazar. Anahtar yoksa / hesap bağlı
değilse anlaşılır Türkçe mesajla 400 / 409 döner; 500 üretilmez.
"""
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .. import auth, db, spotify
from ..cameras import encrypt
from .mail import _base   # OAuth dönüş adresi tabanı (kullanıcının girdiği alan adı) — mail / social ile aynı kural

router = APIRouter(prefix='/api/spotify')

_states = {}   # durum jetonu → (kullanıcı id, zaman)


def _err(e: spotify.SpotifyError):
    return HTTPException(getattr(e, 'status', 400), str(e))


@router.get('/status')
def status(user=Depends(auth.current_user), conn=db.DB):
    """Hafif durum: anahtar tanımlı mı, kullanıcı bağlı mı. Üst bar ve pano bununla karar verir (Spotify'a istek atmaz)."""
    return {'configured': spotify.configured(), 'connected': spotify.connected(conn, user['id'])}


# ---------------- OAuth: “Spotify ile bağlan” ----------------
def _redirect_uri(request):
    return f'{_base(request)}/api/spotify/oauth/callback'


@router.get('/oauth/start')
def oauth_start(request: Request, user=Depends(auth.current_user)):
    if not spotify.configured():
        raise HTTPException(400, 'Spotify bu sunucuda henüz ayarlanmadı (Program Ayarları › Entegrasyonlar › Spotify).')
    now = time.time()
    for k in [k for k, v in _states.items() if now - v[1] > 600]:
        _states.pop(k, None)
    state = secrets.token_urlsafe(24)
    _states[state] = (user['id'], now)
    try:
        url = spotify.auth_url(_redirect_uri(request), state)
    except spotify.SpotifyError as e:
        raise _err(e) from e
    return {'url': url}


@router.get('/oauth/callback')
async def oauth_callback(request: Request, state: str = '', code: str = '', error: str = '',
                         user=Depends(auth.current_user), conn=db.DB):
    back = lambda msg: RedirectResponse(f'/app#/settings/social?msg={quote(msg, safe="")}', status_code=303)  # noqa: E731
    st = _states.pop(state, None)
    if not st or st[0] != user['id'] or time.time() - st[1] > 600:
        return back('Bağlantı isteği geçersiz ya da süresi doldu; yeniden deneyin')
    if error or not code:
        return back('İzin verilmedi')
    try:
        tok = await run_in_threadpool(spotify.exchange, code, _redirect_uri(request))
        refresh = tok.get('refresh_token')
        if not refresh:
            return back('Spotify yenileme jetonu vermedi; yeniden deneyin')
        uid, name, avatar, _email = await run_in_threadpool(spotify.me, tok['access_token'])
    except spotify.SpotifyError as e:
        return back(str(e))
    except Exception:   # noqa: BLE001
        return back('Spotify’a bağlanılamadı; yeniden deneyin')
    import json as _json
    secret = encrypt(_json.dumps({'refresh': refresh, 'uid': uid}))
    handle = f'@{name}' if name and not str(name).startswith('@') else (name or uid or 'spotify')
    old = conn.execute("SELECT id FROM social_accounts WHERE user_id = ? AND provider = 'spotify'", (user['id'],)).fetchone()
    if old:
        conn.execute('UPDATE social_accounts SET token = ?, handle = ?, display_name = ?, avatar = ?, last_error = NULL WHERE id = ?',
                     (secret, str(handle)[:300], str(name or '')[:200], avatar, old[0]))
    else:
        if conn.execute('SELECT COUNT(*) FROM social_accounts WHERE user_id = ?', (user['id'],)).fetchone()[0] >= 20:
            return back('En fazla 20 hesap bağlanabilir')
        # show_in_feed = 0: Spotify bir akış kaynağı değil (Şirketten Haberler'e paylaşım getirmez)
        conn.execute('''INSERT INTO social_accounts (user_id, provider, handle, display_name, avatar, token, show_in_feed, last_sync, created_at)
                        VALUES (?,?,?,?,?,?,0,?,?)''',
                     (user['id'], 'spotify', str(handle)[:300], str(name or '')[:200], avatar, secret, None, db.now()))
    conn.commit()
    return back('ok')


@router.post('/disconnect')
async def disconnect(user=Depends(auth.current_user), conn=db.DB):
    removed = await run_in_threadpool(spotify.disconnect, conn, user['id'])
    return {'ok': True, 'removed': removed}


# ---------------- oynatma / bilgi ----------------
@router.get('/now-playing')
async def now_playing(user=Depends(auth.current_user), conn=db.DB):
    try:
        return await run_in_threadpool(spotify.now_playing, conn, user['id'])
    except spotify.SpotifyError as e:
        raise _err(e) from e


@router.get('/playlists')
async def playlists(user=Depends(auth.current_user), conn=db.DB):
    try:
        return {'items': await run_in_threadpool(spotify.playlists, conn, user['id'])}
    except spotify.SpotifyError as e:
        raise _err(e) from e


@router.get('/search')
async def search(q: str = '', user=Depends(auth.current_user), conn=db.DB):
    try:
        return await run_in_threadpool(spotify.search, conn, user['id'], q)
    except spotify.SpotifyError as e:
        raise _err(e) from e


class PlayIn(BaseModel):
    uri: str = ''


@router.post('/play')
async def play(body: PlayIn = PlayIn(), user=Depends(auth.current_user), conn=db.DB):
    try:
        return await run_in_threadpool(spotify.play, conn, user['id'], body.uri or None)
    except spotify.SpotifyError as e:
        raise _err(e) from e


@router.post('/pause')
async def pause(user=Depends(auth.current_user), conn=db.DB):
    try:
        return await run_in_threadpool(spotify.pause, conn, user['id'])
    except spotify.SpotifyError as e:
        raise _err(e) from e


@router.post('/next')
async def next_track(user=Depends(auth.current_user), conn=db.DB):
    try:
        return await run_in_threadpool(spotify.next_track, conn, user['id'])
    except spotify.SpotifyError as e:
        raise _err(e) from e


@router.post('/previous')
async def previous_track(user=Depends(auth.current_user), conn=db.DB):
    try:
        return await run_in_threadpool(spotify.previous_track, conn, user['id'])
    except spotify.SpotifyError as e:
        raise _err(e) from e
