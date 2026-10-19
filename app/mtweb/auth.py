"""mtweb kimlik ve istek güvenliği (docs/mtweb.md §Kimlik, §Güvenlik).

- Hesap servisi: tarayıcının `sm_session` çerezi SUNUCU-SUNUCU `GET {MTWEB_ACCOUNT_URL}/api/mt/me` ile doğrulanır (yalnız bu çerez
  iletilir). 401/403 → oturum yok. Sonuç ~60 sn önbellekte (anahtar: belirtecin SHA-256 özeti; belirteç saklanmaz).
- Yalnız doğrulanmış (verified) hesaplar.
- Köken (CSRF): durum değiştiren her istekte Origin (yoksa Referer) host'u isteğin Host'u ile aynı olmalı.
- Oran sınırı: kullanıcı (yoksa IP) başına kayan pencere; okuma / yazma ayrı.
"""
import hashlib
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

import httpx

from . import config

_CACHE = {}          # özet → (bitiş, kullanıcı | None)
_CACHE_LOCK = threading.Lock()
_RATE = defaultdict(deque)
_RATE_LOCK = threading.Lock()
_client = [None]


class AccountUnavailable(Exception):
    pass


def client_ip(request):
    h = request.headers
    return (h.get('cf-connecting-ip') or (h.get('x-forwarded-for') or '').split(',')[0].strip()
            or (request.client.host if request.client else ''))[:64]


def _http():
    if _client[0] is None:
        _client[0] = httpx.AsyncClient(timeout=6.0)
    return _client[0]


async def close():
    if _client[0] is not None:
        await _client[0].aclose()
        _client[0] = None


def _key(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


async def account_user(token):
    """sm_session → {'id','email','name','verified'} | None. Hesap servisine ulaşılamazsa AccountUnavailable."""
    tok = str(token or '').strip()
    if not (16 <= len(tok) <= 256) or any(c.isspace() or c in ';,' for c in tok):
        return None
    k = _key(tok)
    t = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(k)
        if hit and hit[0] > t:
            return hit[1]
    try:
        r = await _http().get(f'{config.ACCOUNT_URL}/api/mt/me', headers={'Cookie': f'{config.COOKIE}={tok}'})
    except httpx.HTTPError:
        raise AccountUnavailable() from None
    if r.status_code in (401, 403):
        u = None
    elif r.status_code != 200:
        raise AccountUnavailable()
    else:
        try:
            d = (r.json() or {}).get('user') or {}
            u = {'id': int(d['id']), 'email': str(d.get('email') or '')[:200], 'name': str(d.get('name') or '')[:200], 'verified': bool(d.get('verified'))}
        except (ValueError, KeyError, TypeError):
            u = None
    with _CACHE_LOCK:
        _CACHE[k] = (t + config.ACCOUNT_CACHE_S, u)
        if len(_CACHE) > 20000:
            for kk in [kk for kk, v in _CACHE.items() if v[0] <= t][:10000]:
                _CACHE.pop(kk, None)
    return u


def forget(token):
    with _CACHE_LOCK:
        _CACHE.pop(_key(str(token or '').strip()), None)


def reset():
    with _CACHE_LOCK:
        _CACHE.clear()
    with _RATE_LOCK:
        _RATE.clear()


def origin_ok(request):
    """Origin (yoksa Referer) host:port'u isteğin Host'u ile aynı mı?"""
    host = (request.headers.get('host') or '').strip().lower()
    src = request.headers.get('origin') or request.headers.get('referer') or ''
    if not host or not src or src == 'null':
        return False
    try:
        netloc = urlsplit(src).netloc.lower()
    except ValueError:
        return False
    return bool(netloc) and netloc == host


def rate_ok(key, limit, window):
    """Kayan pencere; aşılmışsa bekleme süresi (sn), değilse 0."""
    t = time.time()
    with _RATE_LOCK:
        q = _RATE[key]
        while q and q[0] < t - window:
            q.popleft()
        if len(q) >= limit:
            return max(1, int(q[0] + window - t) + 1)
        q.append(t)
        if len(_RATE) > 50000:
            for kk in [kk for kk, qq in _RATE.items() if not qq or qq[-1] < t - 600][:10000]:
                _RATE.pop(kk, None)
    return 0
