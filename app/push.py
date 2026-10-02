"""Arka plan bildirimleri (Web Push): uygulama kapalıyken / ekran kilitliyken arama, mesaj, telsiz ve bildirimler cihaza düşer.

Sunucu VAPID anahtarı ilk kullanımda data/vapid.pem olarak üretilir (chmod 600). Tarayıcı aboneliği push_subs tablosunda tutulur.
Gönderim ana döngüyü hiç bekletmez: send() işi küçük bir iş parçacığı havuzuna bırakır; geçersiz (404/410) abonelikler silinir.
Bildirimler (üst çubuktaki zil) zaten sorgu ile hesaplandığı için arka planda dakikada bir sayılır; bir türün sayısı artınca push gider.
"""
import asyncio
import base64
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from . import auth, config, db

log = logging.getLogger('caymaz.push')
KEY_FILE = config.DATA_DIR / 'vapid.pem'
SUBJECT = 'mailto:destek@gokkubbetech.com'
_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='push')
_vapid = None


def _key():
    global _vapid
    if _vapid is None:
        from py_vapid import Vapid02 as Vapid
        if KEY_FILE.exists():
            _vapid = Vapid.from_file(str(KEY_FILE))
        else:
            v = Vapid()
            v.generate_keys()
            v.save_key(str(KEY_FILE))
            os.chmod(KEY_FILE, 0o600)
            _vapid = v
    return _vapid


def public_key():
    """Tarayıcının applicationServerKey'i (base64url, sıkıştırılmamış P-256 noktası)."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    raw = _key().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def available():
    try:
        import pywebpush  # noqa: F401
        return True
    except ImportError:
        return False


def subscribe(conn, user_id, sub, ua=None):
    keys = sub.get('keys') or {}
    if not sub.get('endpoint') or not keys.get('p256dh') or not keys.get('auth'):
        raise ValueError('Geçersiz abonelik')
    conn.execute('''INSERT INTO push_subs (user_id, endpoint, p256dh, auth, ua, created_at) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh, auth = excluded.auth,
                    ua = excluded.ua''', (user_id, sub['endpoint'], keys['p256dh'], keys['auth'], (ua or '')[:200], db.now()))


def unsubscribe(conn, user_id, endpoint):
    conn.execute('DELETE FROM push_subs WHERE user_id = ? AND endpoint = ?', (user_id, endpoint))


def _deliver(user_ids, payload, ttl):
    from pywebpush import WebPushException, webpush
    with db.connect() as conn:
        subs = db.rows(conn.execute(
            f"SELECT id, endpoint, p256dh, auth FROM push_subs WHERE user_id IN ({','.join('?' * len(user_ids))})", list(user_ids)))
    if not subs:
        return 0
    data = json.dumps(payload, ensure_ascii=False)
    dead, sent = [], 0
    for s in subs:
        try:
            webpush({'endpoint': s['endpoint'], 'keys': {'p256dh': s['p256dh'], 'auth': s['auth']}}, data,
                    vapid_private_key=_key(), vapid_claims={'sub': SUBJECT}, ttl=ttl, timeout=10,
                    headers={'Urgency': 'high' if payload.get('type') in ('call', 'radio') else 'normal'})
            sent += 1
        except WebPushException as e:
            code = getattr(e.response, 'status_code', None)
            if code in (404, 410):
                dead.append(s['id'])
            else:
                log.warning('push gönderilemedi (%s): %s', code, str(e)[:200])
        except Exception as e:   # ağ hatası vb. — sistemi etkilemesin
            log.warning('push hatası: %s', str(e)[:200])
    if dead:
        with db.connect() as conn:
            conn.executemany('DELETE FROM push_subs WHERE id = ?', [(i,) for i in dead])
    return sent


def send(user_ids, payload, ttl=300):
    """Engellemeden gönder (senkron ya da async koddan çağrılabilir). payload: {type, title, body, url, tag}."""
    ids = {int(u) for u in (user_ids or []) if u}
    if not ids or not available():
        return
    _pool.submit(_deliver, ids, payload, ttl)


def send_lazy(fn):
    """Yük, iş parçacığında hesaplanacaksa (isim sorgusu vb.): fn() → (user_ids, payload) | None."""
    if not available():
        return

    def run():
        r = fn()
        if r and r[0]:
            _deliver({int(u) for u in r[0]}, r[1], 120)
    _pool.submit(run)


# ---------- Bildirimler (zil): dakikada bir; bir türün sayısı artınca push
def _user(conn, uid):
    u = db.row(conn.execute('SELECT id, username, full_name, prefs FROM users WHERE id = ? AND active = 1 AND deleted_at IS NULL', (uid,)))
    if not u:
        return None
    real = auth.user_roles(conn, uid)
    u['master'] = auth.is_master(u['username'])
    u['real_roles'] = real
    u['roles'] = [*auth.ROLES, auth.MASTER] if u['master'] else real
    u['modules'] = [*auth.MODULE_ROLES.keys(), 'master'] if u['master'] else auth.allowed_modules(real)
    return u


_last = {}   # uid → {key: count}


def _scan():
    from . import notifications
    out = []
    with db.connect() as conn:
        uids = [r[0] for r in conn.execute('SELECT DISTINCT user_id FROM push_subs')]
        absent = auth.absent_map(conn)
        for uid in uids:
            u = _user(conn, uid)
            if not u or (uid in absent and not u['master']):
                continue
            try:
                items = notifications.for_user(conn, u)
            except Exception as e:
                log.warning('bildirim taraması (%s): %s', uid, e)
                continue
            now = {n['key']: n['count'] for n in items}
            prev = _last.get(uid)
            _last[uid] = now
            if prev is None:
                continue   # ilk tarama: yalnızca durum al
            new = [n for n in items if n['count'] > prev.get(n['key'], 0)]
            if new:
                n = new[0]
                more = f' (+{len(new) - 1} bildirim daha)' if len(new) > 1 else ''
                out.append((uid, {'type': 'notif', 'title': n['title'], 'tag': f'notif-{n["key"]}',
                                  'body': (', '.join(n['names'][:3]) or n.get('detail') or '') + more,
                                  'url': '/app' + (n['href'] or '#/')}))
    return out


async def notify_loop(interval=60):
    await asyncio.sleep(20)
    while True:
        try:
            if available():
                for uid, payload in await asyncio.to_thread(_scan):
                    send([uid], payload, ttl=3600)
        except Exception as e:
            log.warning('bildirim döngüsü: %s', e)
        await asyncio.sleep(interval)


# Telsiz: aynı kişiye aynı kanal için en fazla 2 dakikada bir
_radio_seen = {}


def radio_talk(ch, speaker, targets, online):
    now = time.monotonic()
    to = [u for u in targets if u != speaker and u not in online and now - _radio_seen.get((u, ch), 0) > 120]
    if not to:
        return
    for u in to:
        _radio_seen[(u, ch)] = now

    def build():
        with db.connect() as conn:
            r = conn.execute('SELECT full_name FROM users WHERE id = ?', (speaker,)).fetchone()
            c = conn.execute('SELECT name FROM radio_channels WHERE id = ?', (ch,)).fetchone() if isinstance(ch, int) else None
        who = r[0] if r else 'Bir kullanıcı'
        return to, {'type': 'radio', 'title': f'Telsiz: {c[0]}' if c else 'Telsiz', 'body': f'{who} konuşuyor — dinlemek için açın',
                    'tag': f'radio-{ch}', 'url': '/app#/'}
    send_lazy(build)
