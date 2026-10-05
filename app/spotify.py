"""Spotify entegrasyonu: her kullanıcı kendi Spotify hesabını bağlar (OAuth 2.0 Authorization Code).

Program Ayarları › Entegrasyonlar › Spotify'a Client ID / Secret girilince, kullanıcı Kişisel Ayarlar › Sosyal Medya'dan
“Spotify ile bağlan” der. Dönüşte yenileme jetonu (refresh_token) şifreli olarak social_accounts.token içinde saklanır
(provider='spotify'). Erişim jetonu (access_token) kısa ömürlüdür; bellekte kullanıcı başına önbelleğe alınır ve süresi
dolunca yenileme jetonuyla tazelenir. Anlık çalan parça ve oynatma kontrolü Spotify Web API üzerinden yapılır.

Anahtar yoksa / hesap bağlı değilse hiçbir yerde 500 üretilmez: anlaşılır Türkçe mesajla 400 (anahtar yok) ya da
409 (bağlı değil) döner; üst bar ve pano kutucuğu bu durumda yalnızca “bağlan” önerisi gösterir ya da gizli kalır.
"""
import json
import threading
import time
from urllib.parse import urlencode

import httpx

from . import config, db
from .cameras import decrypt, encrypt

AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
API = 'https://api.spotify.com/v1'
# Gerekli izinler: anlık çalan + oynatma durumu + oynatma kontrolü + web oynatıcı + hesap bilgisi + çalma listeleri
SCOPES = ('user-read-currently-playing user-read-playback-state user-modify-playback-state '
          'streaming user-read-email playlist-read-private')
TIMEOUT = 12

_cache = {}        # user_id → (access_token, expiry_epoch)   (bellek içi; erişim jetonu kısa ömürlü)
_lock = threading.Lock()


class SpotifyError(Exception):
    """Kullanıcıya gösterilecek anlaşılır hata; status: HTTP kodu (400 anahtar yok / 409 bağlı değil / 502 Spotify)."""
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def configured():
    return bool(config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET)


def _need_config():
    if not configured():
        raise SpotifyError('Spotify bu sunucuda henüz ayarlanmadı (Program Ayarları › Entegrasyonlar › Spotify).', 400)


# ---------------- OAuth ----------------
def auth_url(redirect_uri, state):
    _need_config()
    q = {'client_id': config.SPOTIFY_CLIENT_ID, 'response_type': 'code', 'redirect_uri': redirect_uri,
         'scope': SCOPES, 'state': state, 'show_dialog': 'false'}
    return f'{AUTH_URL}?{urlencode(q)}'


def _token_request(data):
    _need_config()
    try:
        r = httpx.post(TOKEN_URL, data=data, auth=(config.SPOTIFY_CLIENT_ID, config.SPOTIFY_CLIENT_SECRET), timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise SpotifyError('Spotify’a ulaşılamadı; yeniden deneyin.', 502) from e
    tok = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
    if r.status_code != 200 or 'access_token' not in tok:
        raise SpotifyError(f"Spotify jetonu alınamadı: {tok.get('error_description') or tok.get('error') or r.status_code}", 502)
    return tok


def exchange(code, redirect_uri):
    """Yetki kodu → jetonlar (ilk bağlanma). refresh_token döner."""
    return _token_request({'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri})


def me(access):
    """/v1/me → (spotify_id, görünen ad, avatar, e-posta)."""
    data = _api_raw('GET', '/me', access)
    imgs = data.get('images') or []
    return data.get('id'), data.get('display_name') or data.get('id'), (imgs[0].get('url') if imgs else None), data.get('email')


# ---------------- jeton (erişim) yönetimi ----------------
def _account(conn, user_id):
    return db.row(conn.execute("SELECT * FROM social_accounts WHERE user_id = ? AND provider = 'spotify' ORDER BY id LIMIT 1",
                               (user_id,)))


def connected(conn, user_id):
    return _account(conn, user_id) is not None


def _refresh_access(conn, acc):
    """Saklı refresh_token ile yeni erişim jetonu al; Spotify yeni refresh_token verirse DB'de güncelle."""
    try:
        stored = json.loads(decrypt(acc['token']))
    except Exception as e:   # noqa: BLE001 — bozuk / eski kayıt
        raise SpotifyError('Spotify oturumu okunamadı; hesabı yeniden bağlayın.', 409) from e
    refresh = stored.get('refresh')
    if not refresh:
        raise SpotifyError('Spotify oturumu sona erdi; hesabı yeniden bağlayın.', 409)
    tok = _token_request({'grant_type': 'refresh_token', 'refresh_token': refresh})
    access = tok['access_token']
    exp = time.time() + int(tok.get('expires_in') or 3600) - 60
    with _lock:
        _cache[acc['user_id']] = (access, exp)
    if tok.get('refresh_token') and tok['refresh_token'] != refresh:   # Spotify bazen yeni refresh verir
        stored['refresh'] = tok['refresh_token']
        conn.execute('UPDATE social_accounts SET token = ? WHERE id = ?', (encrypt(json.dumps(stored)), acc['id']))
        conn.commit()
    return access


def access_token_for(conn, user_id):
    """Kullanıcının geçerli erişim jetonu; yoksa/eskiyse yenilenir. Bağlı değilse 409."""
    acc = _account(conn, user_id)
    if not acc:
        raise SpotifyError('Spotify hesabınız bağlı değil (Kişisel Ayarlar › Sosyal Medya).', 409)
    with _lock:
        cached = _cache.get(user_id)
    if cached and time.time() < cached[1]:
        return cached[0]
    return _refresh_access(conn, acc)


def disconnect(conn, user_id):
    """Hesabı ayır: social_accounts kaydını sil ve bellekteki jetonu düşür."""
    acc = _account(conn, user_id)
    with _lock:
        _cache.pop(user_id, None)
    if acc:
        conn.execute('DELETE FROM social_accounts WHERE id = ?', (acc['id'],))
        conn.commit()
    return bool(acc)


# ---------------- Web API çağrıları ----------------
def _request(method, path, access, **kw):
    try:
        r = httpx.request(method, f'{API}{path}', headers={'Authorization': f'Bearer {access}'}, timeout=TIMEOUT, **kw)
    except httpx.HTTPError as e:
        raise SpotifyError('Spotify’a ulaşılamadı; yeniden deneyin.', 502) from e
    return r


def _api_raw(method, path, access, **kw):
    """Tek deneme (jeton zaten geçerli): 200/JSON döner, 204 → None. Hata → SpotifyError."""
    r = _request(method, path, access, **kw)
    return _handle(r)


def _handle(r):
    if r.status_code == 204 or not r.content:
        return None
    if r.status_code == 404:
        raise SpotifyError('Etkin bir Spotify cihazı yok. Spotify uygulamasını (telefon / bilgisayar / web) açıp bir şey çalın.', 409)
    if r.status_code == 403:
        raise SpotifyError('Spotify bu işleme izin vermedi (Premium hesap gerekebilir ya da yetki verilmedi).', 403)
    if r.status_code == 429:
        raise SpotifyError('Spotify istek sınırı doldu; biraz sonra deneyin.', 429)
    if r.status_code >= 400:
        try:
            msg = (r.json().get('error') or {}).get('message')
        except Exception:   # noqa: BLE001
            msg = None
        raise SpotifyError(f'Spotify isteği başarısız ({r.status_code}){": " + msg if msg else ""}', 502)
    try:
        return r.json()
    except ValueError:
        return None


def call(conn, user_id, method, path, **kw):
    """Kullanıcı adına Spotify Web API çağrısı; 401 olursa jetonu bir kez yenileyip tekrar dener."""
    access = access_token_for(conn, user_id)
    r = _request(method, path, access, **kw)
    if r.status_code == 401:   # jeton eskidi: bir kez yenile ve tekrar dene
        acc = _account(conn, user_id)
        if acc:
            access = _refresh_access(conn, acc)
            r = _request(method, path, access, **kw)
    return _handle(r)


# ---------------- üst seviye yardımcılar ----------------
def _artists(item):
    return ', '.join(a.get('name') for a in (item.get('artists') or []) if a.get('name'))


def _track_brief(item):
    if not item:
        return None
    album = item.get('album') or {}
    imgs = album.get('images') or []
    return {
        'id': item.get('id'),
        'uri': item.get('uri'),
        'title': item.get('name'),
        'artists': _artists(item),
        'album': album.get('name'),
        'art': (imgs[0].get('url') if imgs else None),
        'url': (item.get('external_urls') or {}).get('spotify'),
        'duration_ms': item.get('duration_ms'),
    }


def now_playing(conn, user_id):
    """Anlık çalan parça. Çalan yoksa / 204 → {'playing': False}."""
    data = call(conn, user_id, 'GET', '/me/player/currently-playing')
    if not data or not data.get('item'):
        return {'playing': False}
    item = data['item']
    device = (data.get('device') or {}).get('name') if isinstance(data.get('device'), dict) else None
    out = _track_brief(item)
    out.update({
        'playing': True,
        'is_playing': bool(data.get('is_playing')),
        'progress_ms': data.get('progress_ms') or 0,
        'device': device,
    })
    return out


def playback_state(conn, user_id):
    """Cihaz + oynatma durumu (/me/player). Etkin cihaz yoksa {'active': False}."""
    data = call(conn, user_id, 'GET', '/me/player')
    if not data:
        return {'active': False}
    return {'active': True, 'is_playing': bool(data.get('is_playing')),
            'device': (data.get('device') or {}).get('name'), 'progress_ms': data.get('progress_ms') or 0,
            'item': _track_brief(data.get('item'))}


def play(conn, user_id, uri=None):
    """Oynat / sürdür. uri verilirse: track → tek parça, playlist/album/artist → bağlam (context) olarak çalınır."""
    body = None
    if uri:
        body = {'uris': [uri]} if uri.startswith('spotify:track:') else {'context_uri': uri}
    call(conn, user_id, 'PUT', '/me/player/play', json=body)
    return {'ok': True}


def pause(conn, user_id):
    call(conn, user_id, 'PUT', '/me/player/pause')
    return {'ok': True}


def next_track(conn, user_id):
    call(conn, user_id, 'POST', '/me/player/next')
    return {'ok': True}


def previous_track(conn, user_id):
    call(conn, user_id, 'POST', '/me/player/previous')
    return {'ok': True}


def playlists(conn, user_id, limit=20):
    data = call(conn, user_id, 'GET', '/me/playlists', params={'limit': max(1, min(limit, 50))})
    out = []
    for p in (data or {}).get('items', []):
        if not p:
            continue
        imgs = p.get('images') or []
        out.append({'name': p.get('name'), 'uri': p.get('uri'),
                    'art': (imgs[0].get('url') if imgs else None),
                    'tracks': (p.get('tracks') or {}).get('total'),
                    'owner': (p.get('owner') or {}).get('display_name')})
    return out


def search(conn, user_id, q, limit=8):
    q = (q or '').strip()
    if not q:
        return {'tracks': [], 'playlists': []}
    data = call(conn, user_id, 'GET', '/search', params={'q': q, 'type': 'track,playlist', 'limit': max(1, min(limit, 20))})
    tracks = [_track_brief(it) for it in ((data or {}).get('tracks') or {}).get('items', []) if it]
    pls = []
    for p in ((data or {}).get('playlists') or {}).get('items', []):
        if not p:
            continue
        imgs = p.get('images') or []
        pls.append({'name': p.get('name'), 'uri': p.get('uri'), 'art': (imgs[0].get('url') if imgs else None),
                    'owner': (p.get('owner') or {}).get('display_name')})
    return {'tracks': tracks, 'playlists': pls}
