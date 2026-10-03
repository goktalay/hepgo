"""Canlı yayın — /api/live (başlat / bitir / etkin yayınlar) ve /ws/live/{id} (yayıncı görüntüsü + izleyici etkileşimi).

Yayıncı kamerayı tarayıcıda MediaRecorder ile ~1 sn'lik parçalı MP4 olarak gönderir; sunucu yeniden kodlamadan
izleyicilere dağıtır (Instagram / TikTok Live gibi birkaç saniyelik gecikme; Cloudflare arkasında standart HTTPS
WebSocket — operatör / NAT engeli yok) ve aynı anda kaydeder. Geç katılan izleyici son anahtar kareden başlar
(app/live.py). Yavaş izleyicinin kuyruğu dolarsa onun görüntüsü bir sonraki anahtar kareye atlar; yayın durmaz.

Yayın başlayınca herkese anlık olay + telefon bildirimi gider; zil bildirimi ('live-now') yayın bitene kadar kalır,
tıklayan yayına katılır. Yayın bitince kayıt Şirketten Haberler'e (tür LIVE) video olarak düşer.
"""
import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import auth, config, db, feed
from .. import live as media

router = APIRouter(prefix='/api/live')
ws_router = APIRouter()

KEEP_SEC = 35          # yayıncının bağlantısı koparsa yayının bekleyeceği süre (yeniden bağlanabilir)
MAX_QUEUE = 48         # izleyici başına bekleyen mesaj / parça
MAX_GOP = 90           # son anahtar kareden bu yana tutulan en çok parça
STREAMS = {}           # yayın id → Stream


class Viewer:
    def __init__(self, ws, user):
        self.ws, self.user = ws, user
        self.q = asyncio.Queue(maxsize=MAX_QUEUE)
        self.ready = False          # görüntü başladı mı (init + anahtar kare gönderildi)
        self.last_chat = self.last_like = 0.0

    def put(self, item, media_item=False):
        try:
            self.q.put_nowait(item)
            return True
        except asyncio.QueueFull:
            if media_item:   # yetişemiyor: kuyruğu boşalt, bir sonraki anahtar karede yeniden başlasın
                while not self.q.empty():
                    self.q.get_nowait()
                self.ready = False
            return False


class Stream:
    def __init__(self, sid, owner):
        self.id, self.owner = sid, owner
        self.pub = None
        self.parser = media.Fmp4()
        self.gop = []
        self.viewers = {}           # ws → Viewer
        self.likes = self.comments = self.peak = 0
        self.dropped_at = None
        self.file = None
        self.part = 0
        self.parts = []             # (yol, bayt)
        self.ended = False

    # --- kayıt (her yeniden başlatma ayrı parça; yayın sonunda en uzun parça paylaşılır)
    def _rec_open(self, init):
        if self.file:
            self.file.close()
        while True:   # sunucu yeniden başlasa da önceki parçanın üzerine yazılmaz
            self.part += 1
            rel = f'feed/live_{self.id}' + ('' if self.part == 1 else f'_p{self.part}') + '.mp4'
            path = config.UPLOAD_DIR / rel
            if not path.exists():
                break
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, 'wb')
        self.file.write(init)
        self.parts.append([rel, len(init)])

    def _rec(self, data):
        if self.file:
            self.file.write(data)
            self.parts[-1][1] += len(data)

    def close_file(self):
        if self.file:
            try:
                self.file.close()
            except OSError:
                pass
            self.file = None

    # --- dağıtım
    def users(self):
        seen, out = set(), []
        for v in self.viewers.values():
            if v.user['id'] not in seen:
                seen.add(v.user['id'])
                out.append({'id': v.user['id'], 'name': v.user['full_name'], 'photo': v.user.get('photo')})
        return out

    def broadcast(self, msg, include_pub=True):
        txt = json.dumps(msg, ensure_ascii=False)
        for v in list(self.viewers.values()):
            v.put(txt)
        if include_pub and self.pub is not None:
            asyncio.ensure_future(_safe_text(self.pub, txt))

    def on_media(self, data):
        for ev in self.parser.feed(data):
            if ev[0] == 'init':
                self._rec_open(ev[1])
                self.gop = []
                self.broadcast({'t': 'mime', 'mime': self.parser.mime}, include_pub=False)
                for v in self.viewers.values():
                    if v.ready:
                        v.put(ev[1], True)
                continue
            frag, key = ev[1], ev[2]
            self._rec(frag)
            if key:
                self.gop = [frag]
            elif self.gop and len(self.gop) < MAX_GOP:
                self.gop.append(frag)
            for v in list(self.viewers.values()):
                if v.ready:
                    v.put(frag, True)
                elif key and self.parser.init:
                    if v.put(self.parser.init, True) and v.put(frag, True):
                        v.ready = True

    def start_viewer(self, v):
        """Yeni izleyici: init + son anahtar kareden bu yana parçalar (yoksa bir sonraki anahtar kareyi bekler)."""
        if self.parser.init and self.gop:
            ok = v.put(self.parser.init, True)
            for f in self.gop:
                ok = ok and v.put(f, True)
            v.ready = ok


async def _safe_text(ws, txt):
    try:
        await ws.send_text(txt)
    except Exception:   # noqa: BLE001
        pass


async def _sender(v: Viewer):
    try:
        while True:
            item = await v.q.get()
            if isinstance(item, (bytes, bytearray)):
                await v.ws.send_bytes(item)
            else:
                await v.ws.send_text(item)
    except Exception:   # noqa: BLE001 — bağlantı koptu
        pass


def _db(fn, *a):
    return asyncio.to_thread(fn, *a)


def _row(sid):
    with db.connect() as conn:
        return db.row(conn.execute('''SELECT s.*, u.full_name, u.photo FROM live_streams s JOIN users u ON u.id = s.user_id
                                      WHERE s.id = ?''', (sid,)))


def _user_pub(u):
    return {'id': u['id'], 'name': u['full_name'], 'photo': u.get('photo')}


async def _announce_start(sid, user, title):
    try:
        from . import voice
        await voice.broadcast_users({'t': 'live', 'state': 'start', 'id': sid, 'user': _user_pub(user), 'title': title})
    except Exception:   # noqa: BLE001
        pass
    try:
        from .. import push

        def recips():
            with db.connect() as conn:
                return feed.push_recipients(conn, user['id'], mute_key='live-now')
        ids = await _db(recips)
        push.send(ids, {'type': 'notif', 'title': f"🔴 {user['full_name']} canlı yayında", 'tag': f'live-{sid}',
                        'body': title or 'İzlemek için dokunun', 'url': f'/app#/live/{sid}'}, ttl=3600)
    except Exception:   # noqa: BLE001
        pass


def _fmt_dur(sec):
    sec = int(sec)
    return f'{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}' if sec >= 3600 else f'{sec // 60}:{sec % 60:02d}'


async def end_stream(sid, reason='end'):
    """Yayını bitirir (tekrar çağrılabilir): kaydı kapatır, Şirketten Haberler'e paylaşır, herkese bildirir."""
    st = STREAMS.pop(sid, None)
    if st:
        if st.ended:
            return
        st.ended = True
        st.close_file()

    def finish():
        with db.connect() as conn:
            r = db.row(conn.execute('SELECT * FROM live_streams WHERE id = ?', (sid,)))
            if not r or r['status'] != 'live':
                return None
            now = db.now()
            total = conn.execute('SELECT COUNT(*) FROM live_viewers WHERE stream_id = ?', (sid,)).fetchone()[0]
            comments = conn.execute('SELECT COUNT(*) FROM live_comments WHERE stream_id = ?', (sid,)).fetchone()[0]
            peak = max(r['viewers_peak'] or 0, st.peak if st else 0)
            likes = max(r['likes'] or 0, st.likes if st else 0)
            # en uzun kayıt parçası (yayıncı yeniden bağlandıysa birden çok parça olabilir; diskteki hepsine bakılır)
            files = sorted((config.UPLOAD_DIR / 'feed').glob(f'live_{sid}.mp4')) + sorted((config.UPLOAD_DIR / 'feed').glob(f'live_{sid}_p*.mp4'))
            best = max(files, key=lambda f: f.stat().st_size, default=None)
            rec = f'feed/{best.name}' if best and best.stat().st_size > 60_000 else None
            from datetime import datetime
            try:
                dur = (datetime.fromisoformat(now) - datetime.fromisoformat(r['started_at'])).total_seconds()
            except ValueError:
                dur = 0
            stats = [_fmt_dur(dur), f'{total} izleyici' if total else None, f'{likes} beğeni' if likes else None,
                     f'{comments} yorum' if comments else None]
            text = '🔴 Canlı yayın' + (f": {r['title']}" if r['title'] else '') + '\n' + ' · '.join(s for s in stats if s)
            mediaj = json.dumps([{'type': 'video', 'path': rec}]) if rec else None
            cur = conn.execute('''INSERT INTO feed_posts (kind, author_id, text, media, lat, lng, ref_type, ref_id, created_at)
                                  VALUES ('LIVE',?,?,?,?,?,'live',?,?)''', (r['user_id'], text, mediaj, r['lat'], r['lng'], sid, now))
            conn.execute('''UPDATE live_streams SET status='ended', ended_at=?, viewers_peak=?, viewers_total=?, likes=?, comments=?,
                            recording=?, post_id=? WHERE id=?''', (now, peak, total, likes, comments, rec, cur.lastrowid, sid))
            conn.commit()
            return {'post_id': cur.lastrowid, 'recording': rec, 'user_id': r['user_id'], 'title': r['title'], 'name': None}
    res = await _db(finish)
    if st:
        st.broadcast({'t': 'end', 'post_id': res['post_id'] if res else None, 'reason': reason})
        await asyncio.sleep(0.3)
        for v in list(st.viewers.values()):
            try:
                await v.ws.close()
            except Exception:   # noqa: BLE001
                pass
    try:
        from . import voice
        await voice.broadcast_users({'t': 'live', 'state': 'end', 'id': sid})
        if res:
            await voice.broadcast_users({'t': 'feed', 'id': res['post_id']})
    except Exception:   # noqa: BLE001
        pass
    if res:
        try:   # telefon bildirimi aynı etiketle güncellenir (bildirim yayın bitene kadar kalır)
            from .. import push

            def recips():
                with db.connect() as conn:
                    return feed.push_recipients(conn, res['user_id'], mute_key='live-now')
            ids = await _db(recips)
            push.send(ids, {'type': 'notif', 'title': 'Canlı yayın sona erdi', 'tag': f'live-{sid}',
                            'body': 'Kaydı Şirketten Haberler’de izleyebilirsiniz', 'url': '/app#/home'}, ttl=600)
        except Exception:   # noqa: BLE001
            pass
    return res


_reaper_started = False


async def _reaper():
    """Yayıncısı dönmeyen ya da sunucu yeniden başlarken yarım kalan yayınları kapatır."""
    t0 = time.time()
    while True:
        await asyncio.sleep(10)
        try:
            for sid, st in list(STREAMS.items()):
                if st.pub is None and st.dropped_at and time.time() - st.dropped_at > KEEP_SEC:
                    await end_stream(sid, 'timeout')
            if time.time() - t0 > 90:   # yeniden başlatmadan kalan, yayıncısı hiç bağlanmayan yayınlar
                def stale():
                    with db.connect() as conn:
                        return [r[0] for r in conn.execute("SELECT id FROM live_streams WHERE status='live'")]
                for sid in await _db(stale):
                    st = STREAMS.get(sid)
                    if st is None:
                        STREAMS[sid] = Stream(sid, None)
                        STREAMS[sid].dropped_at = time.time() - KEEP_SEC + 20
        except Exception:   # noqa: BLE001
            pass


async def start_reaper():
    """Uygulama açılışında (main.lifespan) bir kez."""
    global _reaper_started
    if not _reaper_started:
        _reaper_started = True
        await _reaper()


def _ensure_reaper():
    if not _reaper_started:
        asyncio.get_running_loop().create_task(start_reaper())


# ---------------- REST ----------------
class StartIn(BaseModel):
    title: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


@router.post('/start')
async def start(body: StartIn, user=Depends(auth.current_user)):
    _ensure_reaper()
    title = (body.title or '').strip()[:120] or None

    def create():
        with db.connect() as conn:
            r = conn.execute("SELECT id FROM live_streams WHERE user_id = ? AND status = 'live'", (user['id'],)).fetchone()
            if r:
                return r[0], False
            cur = conn.execute('INSERT INTO live_streams (user_id, title, status, started_at, lat, lng) VALUES (?,?,?,?,?,?)',
                               (user['id'], title, 'live', db.now(), body.lat, body.lng))
            db.audit(conn, user['id'], 'Canlı yayın başlattı', 'live', cur.lastrowid, title)
            conn.commit()
            return cur.lastrowid, True
    sid, new = await _db(create)
    STREAMS.setdefault(sid, Stream(sid, user))
    if new:
        await _announce_start(sid, user, title)
    return {'id': sid, 'resumed': not new}


@router.post('/{sid}/end')
async def end(sid: int, user=Depends(auth.current_user)):
    r = await _db(_row, sid)
    if not r:
        raise HTTPException(404, 'Yayın bulunamadı')
    if r['user_id'] != user['id'] and not user.get('master'):
        raise HTTPException(403, 'Yayını yalnızca yayıncı bitirebilir')
    res = await end_stream(sid)
    return {'ok': True, 'post_id': (res or {}).get('post_id') or r.get('post_id')}


@router.get('/active')
def active(user=Depends(auth.current_user), conn=db.DB):
    rows = db.rows(conn.execute('''SELECT s.id, s.user_id, s.title, s.started_at, u.full_name AS name, u.photo
                                   FROM live_streams s JOIN users u ON u.id = s.user_id WHERE s.status = 'live' ORDER BY s.started_at DESC'''))
    for r in rows:
        st = STREAMS.get(r['id'])
        r['viewers'] = len(st.users()) if st else 0
        r['on_air'] = bool(st and st.pub is not None)
    return rows


@router.get('/{sid}')
def info(sid: int, user=Depends(auth.current_user), conn=db.DB):
    r = db.row(conn.execute('''SELECT s.*, u.full_name AS name, u.photo FROM live_streams s JOIN users u ON u.id = s.user_id
                               WHERE s.id = ?''', (sid,)))
    if not r:
        raise HTTPException(404, 'Yayın bulunamadı')
    return r


# ---------------- WebSocket ----------------
@ws_router.websocket('/ws/live/{sid}')
async def ws_live(ws: WebSocket, sid: int):
    await ws.accept()

    def who():
        with db.connect() as conn:
            return auth.user_by_token(conn, ws.cookies.get(auth.COOKIE))
    user = await _db(who)
    r = await _db(_row, sid) if user else None
    if not user or not r or r['status'] != 'live':
        await ws.send_text(json.dumps({'t': 'end', 'post_id': (r or {}).get('post_id'), 'reason': 'not-live' if user else 'auth'}))
        await ws.close()
        return
    _ensure_reaper()
    owner = {'id': r['user_id'], 'full_name': r['full_name'], 'photo': r['photo']}
    st = STREAMS.get(sid)
    if st is None or st.ended:
        st = STREAMS[sid] = Stream(sid, owner)
    if st.owner is None:
        st.owner = owner
    is_pub = ws.query_params.get('role') == 'pub' and user['id'] == r['user_id']

    def recent():
        with db.connect() as conn:
            return list(reversed(db.rows(conn.execute(
                '''SELECT c.text, c.created_at AS at, u.id AS uid, u.full_name AS name, u.photo FROM live_comments c
                   LEFT JOIN users u ON u.id = c.user_id WHERE c.stream_id = ? ORDER BY c.id DESC LIMIT 30''', (sid,)))))
    hello = {'t': 'hello', 'id': sid, 'title': r['title'], 'started_at': r['started_at'], 'owner': _user_pub(owner),
             'mime': st.parser.mime if st.parser.init else None, 'likes': max(st.likes, r['likes'] or 0),
             'viewers': st.users(), 'comments': await _db(recent), 'me': _user_pub(user)}

    if is_pub:
        old = st.pub
        st.pub, st.dropped_at = ws, None
        st.parser = media.Fmp4()   # yayıncı (yeniden) bağlandı: kaydedici baştan başlar (yeni init)
        if old is not None:
            asyncio.ensure_future(old.close())
        await ws.send_text(json.dumps(hello, ensure_ascii=False))
        st.broadcast({'t': 'status', 'on_air': True}, include_pub=False)
        try:
            while True:
                m = await ws.receive()
                if m.get('type') == 'websocket.disconnect':
                    break
                if m.get('bytes'):
                    st.on_media(m['bytes'])
                elif m.get('text'):
                    try:
                        msg = json.loads(m['text'])
                    except ValueError:
                        continue
                    if msg.get('t') == 'end':
                        await end_stream(sid)
                        return
                    if msg.get('t') == 'chat':
                        await _chat(st, user, msg.get('text'))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if st.pub is ws:
                st.pub, st.dropped_at = None, time.time()
                if not st.ended:
                    st.broadcast({'t': 'status', 'on_air': False}, include_pub=False)
        return

    # izleyici
    v = Viewer(ws, user)
    st.viewers[ws] = v
    sender = asyncio.ensure_future(_sender(v))
    v.put(json.dumps(hello, ensure_ascii=False))
    st.start_viewer(v)
    users = st.users()
    st.peak = max(st.peak, len(users))

    def joined():
        with db.connect() as conn:
            conn.execute('INSERT OR IGNORE INTO live_viewers (stream_id, user_id, joined_at) VALUES (?,?,?)', (sid, user['id'], db.now()))
            conn.execute('UPDATE live_streams SET viewers_peak = MAX(viewers_peak, ?) WHERE id = ?', (st.peak, sid))
            conn.commit()
    await _db(joined)
    st.broadcast({'t': 'viewers', 'list': users, 'join': _user_pub(user)})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get('t') == 'chat':
                await _chat(st, user, msg.get('text'), v)
            elif msg.get('t') == 'like':
                now = time.time()
                if now - v.last_like < 0.12:
                    continue
                v.last_like = now
                st.likes += 1
                st.broadcast({'t': 'like', 'n': st.likes, 'uid': user['id']})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        st.viewers.pop(ws, None)
        sender.cancel()
        if not st.ended:
            st.broadcast({'t': 'viewers', 'list': st.users()})
        if st.likes:
            def save_likes():
                with db.connect() as conn:
                    conn.execute('UPDATE live_streams SET likes = MAX(likes, ?) WHERE id = ?', (st.likes, sid))
                    conn.commit()
            await _db(save_likes)


async def _chat(st, user, text, v=None):
    text = (text or '').strip()[:300]
    if not text:
        return
    now = time.time()
    if v is not None:
        if now - v.last_chat < 0.6:
            return
        v.last_chat = now
    st.comments += 1

    def save():
        with db.connect() as conn:
            conn.execute('INSERT INTO live_comments (stream_id, user_id, text, created_at) VALUES (?,?,?,?)', (st.id, user['id'], text, db.now()))
            conn.commit()
    await _db(save)
    st.broadcast({'t': 'chat', 'uid': user['id'], 'name': user['full_name'], 'photo': user.get('photo'), 'text': text, 'at': db.now()})
