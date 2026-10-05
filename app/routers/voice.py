"""Kişiler arası sesli görüşme (WebRTC): WebSocket sinyalleşme + görüşme geçmişi/transkript REST'i.

Sinyalleşme: tarayıcılar /ws/voice'a bağlanır (oturum çereziyle kimlik). Sunucu yalnızca haberleşmeyi (davet/zil,
kabul/ret, WebRTC offer/answer/ICE, bitiş, kayıt onayı) ilgili kullanıcılara iletir; ses AKIŞI tarayıcılar arasında
uçtan uca (peer-to-peer) gider, sunucudan geçmez. Grup görüşmesi mesh (her çift kendi arasında) kurar.

Kayıt: yalnızca TÜM katılımcılar onaylayınca başlar; karışık sesi görüşmeyi başlatan taraf kaydeder, bitince yükler.
Yüklenen kayıt voice_audio ile metne çevrilir, konuşmacılar ses profilleriyle tanınır, özet çıkarılır.
"""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, db, voice_audio, push
from ..files import save_upload

router = APIRouter(prefix='/api/voice')
ws_router = APIRouter()

PEERS = {}      # user_id -> set[WebSocket]  (aynı kullanıcının birden çok sekmesi olabilir)
VISIBLE = {}    # WebSocket -> bool  (sekme şu an ekranda görünür mü; görünürse OS bildirimi gereksiz)
CALL_MEMBERS = {}   # call_id -> set[user_id]  (o an bağlı katılımcılar)


def _online():
    return set(PEERS)


async def _send(user_id, msg):
    """Kullanıcının tüm bağlı sekmelerine JSON mesaj gönderir."""
    dead = []
    for ws in list(PEERS.get(user_id, ())):
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            dead.append(ws)
    for ws in dead:
        PEERS.get(user_id, set()).discard(ws)


def visible_uids():
    """Uygulaması şu an ekranda görünür olan kullanıcılar (uygulama içi bildirim yeter, telefon bildirimi gerekmez)."""
    return {uid for uid, socks in list(PEERS.items()) if any(VISIBLE.get(w) for w in list(socks))}


async def broadcast_users(msg, exclude=None):
    """Bağlı (oturum açmış) tüm kullanıcılara olay — ör. Şirketten Haberler'e yeni paylaşım."""
    for uid in list(PEERS):
        if uid != exclude:
            await _send(uid, msg)


async def _broadcast(call_id, msg, exclude=None):
    for uid in list(CALL_MEMBERS.get(call_id, ())):
        if uid != exclude:
            await _send(uid, msg)


_touched = {}   # uid -> son yazma (monotonic)


def _touch_db(uid):
    conn = None
    try:
        conn = db.connect()
        conn.execute('PRAGMA busy_timeout = 3000')
        conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (db.now(), uid))
        conn.commit()
    except Exception:
        pass
    finally:
        if conn is not None:
            conn.close()


def _touch(uid):
    """Kullanıcının son görülme zamanını tazeler (WS bağlantısı çevrimiçi göstergesidir).
    ÖNEMLİ: olay döngüsünde veritabanına YAZILMAZ — veritabanı meşgulken tüm sunucu donuyordu (kilitlenme kaydı:
    voice._touch). En fazla 20 sn'de bir, ayrı iş parçacığında yazılır."""
    import time as _t
    now = _t.monotonic()
    if now - _touched.get(uid, 0) < 20:
        return
    _touched[uid] = now
    try:
        asyncio.get_running_loop().run_in_executor(None, _touch_db, uid)
    except RuntimeError:   # döngü dışında çağrıldıysa doğrudan
        _touch_db(uid)


def _participant_ids(conn, call_id):
    return [r[0] for r in conn.execute('SELECT user_id FROM voice_call_participants WHERE call_id = ?', (call_id,))]


def _uinfo(conn, ids):
    """{id: {'full_name','photo'}} — arama ekranında kişilerin fotoğrafını göstermek için."""
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {r['id']: {'full_name': r['full_name'], 'photo': r['photo']} for r in db.rows(conn.execute(
        f"SELECT id, full_name, photo FROM users WHERE id IN ({','.join('?' * len(ids))})", ids))}


# ---------- WebSocket sinyalleşme ----------
# Veritabanı işleri ana döngüde değil iş parçacığında yapılır (_db): veritabanı meşgulken (kilit beklemesi 15 sn'ye kadar)
# tüm sunucu donmasın.
async def _db(fn, *args):
    return await asyncio.to_thread(fn, *args)


def _sql(sql, args=()):
    with db.connect() as conn:
        conn.execute(sql, args)


@ws_router.websocket('/ws/voice')
async def ws_voice(ws: WebSocket):
    await ws.accept()
    def who():
        with db.connect() as conn:
            return auth.user_by_token(conn, ws.cookies.get(auth.COOKIE))
    user = await _db(who)
    if not user:
        await ws.send_text(json.dumps({'t': 'error', 'error': 'Oturum açılmamış'}))
        await ws.close()
        return
    uid = user['id']
    PEERS.setdefault(uid, set()).add(ws)
    _touch(uid)   # WS bağlıyken çevrimiçi say (uygulama arka planda olsa da, HTTP yoklaması dursa da)
    try:
        await ws.send_text(json.dumps({'t': 'ready', 'user_id': uid}))
        while True:
            raw = await ws.receive_text()
            try:
                m = json.loads(raw)
            except Exception:
                continue
            if m.get('t') == 'ping':   # istemci ~25 sn'de bir yollar → çevrimiçi kal
                _touch(uid)
                continue
            if m.get('t') == 'presence':   # sekme görünürlüğü (görünürken yeni paylaşım için OS bildirimi atılmaz)
                VISIBLE[ws] = bool(m.get('visible'))
                continue
            await _handle(conn_none=None, user=user, m=m, ws=ws)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        VISIBLE.pop(ws, None)
        PEERS.get(uid, set()).discard(ws)
        if not PEERS.get(uid):
            PEERS.pop(uid, None)
            # bağlı olduğu görüşmelerden düş
            for cid, members in list(CALL_MEMBERS.items()):
                if uid in members:
                    members.discard(uid)
                    await _broadcast(cid, {'t': 'peer_left', 'call_id': cid, 'user_id': uid})
                    if len(members) <= 1:
                        await _end_call(cid)


async def _handle(conn_none, user, m, ws):
    t = m.get('t')
    uid = user['id']
    if t == 'invite':
        await _invite(user, m)
    elif t == 'accept':
        await _accept(user, m)
    elif t == 'reject':
        await _reject(user, m)
    elif t == 'signal':   # WebRTC offer/answer/ice — hedef kullanıcıya ilet
        to = m.get('to')
        if to and m.get('call_id') in CALL_MEMBERS and uid in CALL_MEMBERS[m['call_id']]:
            await _send(to, {'t': 'signal', 'call_id': m['call_id'], 'from': uid, 'data': m.get('data')})
    elif t == 'add':
        await _add(user, m)
    elif t == 'end':
        await _leave(user, m.get('call_id'))
    elif t == 'rec_request':
        await _rec_request(user, m.get('call_id'))
    elif t == 'rec_consent':
        await _rec_consent(user, m.get('call_id'), bool(m.get('ok')))
    elif t == 'rec_stop':
        await _rec_stop(user, m.get('call_id'))


async def _invite(user, m):
    uid = user['id']
    targets = [t for t in (m.get('to') or []) if isinstance(t, int) and t != uid]
    if not targets:
        await _send(uid, {'t': 'error', 'error': 'Aranacak kişi seçin'})
        return
    now = db.now()

    def load():
        with db.connect() as conn:
            return conn.execute(
                f"SELECT id, full_name, prefs FROM users WHERE id IN ({','.join('?' * len(targets + [uid]))})", targets + [uid]).fetchall()
    rows = await _db(load)
    names = {r[0]: r[1] for r in rows}
    prefs = {r[0]: r[2] for r in rows}
    # Rahatsız etmeyin (arama): kapalı kişiler aranmaz
    blocked = [t for t in targets if auth.dnd_state(prefs.get(t))['calls']]
    targets = [t for t in targets if t not in blocked]
    if not targets:
        who = ', '.join(names.get(t, '') for t in blocked) or 'Kişi'
        await _send(uid, {'t': 'error', 'error': f'{who} şu an aramalara kapalı (rahatsız etmeyin)'})
        return
    kind = 'grup' if len(targets) > 1 else 'bire_bir'
    video = bool(m.get('video')) and kind == 'bire_bir'   # görüntülü arama yalnızca bire bir

    def create():
        with db.connect() as conn:
            title = kind == 'grup' and (', '.join(names.get(t, '') for t in targets)[:120]) or None
            cid = conn.execute('INSERT INTO voice_calls (kind, initiator_id, title, status, started_at) VALUES (?,?,?,?,?)',
                               (kind, uid, title, 'ARANIYOR', now)).lastrowid
            conn.execute('INSERT INTO voice_call_participants (call_id, user_id, role, invited_at, joined_at) VALUES (?,?,?,?,?)',
                         (cid, uid, 'initiator', now, now))
            for t in targets:
                conn.execute('INSERT INTO voice_call_participants (call_id, user_id, role, invited_at) VALUES (?,?,?,?)',
                             (cid, t, 'callee', now))
            db.audit(conn, uid, 'Sesli görüşme başlattı', 'voice_call', cid, f'{kind} · {len(targets)} kişi')
            return cid, _uinfo(conn, targets + [uid])
    cid, info = await _db(create)
    CALL_MEMBERS[cid] = {uid}
    push.send(targets, {'type': 'call', 'title': 'Gelen arama', 'body': f"{user['full_name']} sizi arıyor" + (' (görüntülü)' if video else ' (grup görüşmesi)' if kind == 'grup' else ''),
                        'tag': f'call-{cid}', 'url': '/app#/messages'}, ttl=45)   # uygulama kapalı / ekran kilitli olsa da çalsın
    caller = {'id': uid, 'full_name': user['full_name'], 'photo': info.get(uid, {}).get('photo')}
    for t in targets:
        await _send(t, {'t': 'ring', 'call_id': cid, 'kind': kind, 'video': video, 'caller': caller,
                        'members': [names.get(x) for x in targets if x != t]})
    # arayana bilgi: kimlere ulaşıldı (fotoğrafla)
    await _send(uid, {'t': 'calling', 'call_id': cid, 'kind': kind,
                      'targets': [{'id': t, 'name': names.get(t), 'photo': info.get(t, {}).get('photo'), 'online': t in PEERS} for t in targets]})


async def _add(user, m):
    """Süren görüşmeye kişi ekler: davetliyi ekler/yeniden davet eder ve zil çalar (kabul edince mesh'e katılır)."""
    cid = m.get('call_id')
    uid = user['id']
    if cid not in CALL_MEMBERS or uid not in CALL_MEMBERS[cid]:
        return
    targets = [t for t in (m.get('to') or []) if isinstance(t, int) and t != uid]
    if not targets:
        return
    now = db.now()

    def add():
        with db.connect() as conn:
            already = set(_participant_ids(conn, cid))
            for t in targets:
                if t in already:
                    conn.execute("UPDATE voice_call_participants SET outcome = NULL, left_at = NULL, invited_at = ? WHERE call_id = ? AND user_id = ?", (now, cid, t))
                else:
                    conn.execute('INSERT INTO voice_call_participants (call_id, user_id, role, invited_at) VALUES (?,?,?,?)', (cid, t, 'callee', now))
            conn.execute("UPDATE voice_calls SET kind = 'grup' WHERE id = ?", (cid,))
            names = {r[0]: r[1] for r in conn.execute(
                f"SELECT id, full_name FROM users WHERE id IN ({','.join('?' * len(targets))})", targets)}
            db.audit(conn, uid, 'Görüşmeye kişi ekledi', 'voice_call', cid, ', '.join(names.values()))
            return names, _uinfo(conn, targets + [uid])
    names, info = await _db(add)
    push.send(targets, {'type': 'call', 'title': 'Gelen arama', 'body': f"{user['full_name']} sizi görüşmeye ekliyor",
                        'tag': f'call-{cid}', 'url': '/app#/messages'}, ttl=45)
    caller = {'id': uid, 'full_name': user['full_name'], 'photo': info.get(uid, {}).get('photo')}
    for t in targets:
        await _send(t, {'t': 'ring', 'call_id': cid, 'kind': 'grup', 'caller': caller,
                        'members': [names.get(x) for x in targets if x != t]})
    await _send(uid, {'t': 'calling', 'call_id': cid, 'kind': 'grup',
                      'targets': [{'id': t, 'name': names.get(t), 'photo': info.get(t, {}).get('photo'), 'online': t in PEERS} for t in targets]})


async def _accept(user, m):
    cid = m.get('call_id')
    uid = user['id']
    def accept():
        with db.connect() as conn:
            row = db.row(conn.execute('SELECT * FROM voice_calls WHERE id = ?', (cid,)))
            if not row or row['status'] in ('BITTI', 'IPTAL'):
                return False
            now = db.now()
            conn.execute("UPDATE voice_call_participants SET joined_at = ?, outcome = 'ANSWERED' WHERE call_id = ? AND user_id = ?", (now, cid, uid))
            if row['status'] == 'ARANIYOR':
                conn.execute("UPDATE voice_calls SET status = 'DEVAM', answered_at = ? WHERE id = ?", (now, cid))
            return True
    if not await _db(accept):
        await _send(uid, {'t': 'ended', 'call_id': cid})
        return
    existing = sorted(CALL_MEMBERS.setdefault(cid, set()))
    CALL_MEMBERS[cid].add(uid)

    def peers():
        with db.connect() as conn:
            return _uinfo(conn, existing + [uid])
    info = await _db(peers)
    # yeni katılan mevcut üyelerle mesh kurar: mevcut üyelere "peer_join" (onlar offer başlatır), fotoğrafla
    await _broadcast(cid, {'t': 'peer_join', 'call_id': cid, 'user_id': uid, 'name': user['full_name'],
                           'photo': info.get(uid, {}).get('photo')}, exclude=uid)
    await _send(uid, {'t': 'joined', 'call_id': cid,
                      'peers': [{'id': p, 'name': info.get(p, {}).get('full_name'), 'photo': info.get(p, {}).get('photo')} for p in existing]})


async def _reject(user, m):
    cid = m.get('call_id')
    uid = user['id']
    def reject():
        with db.connect() as conn:
            conn.execute("UPDATE voice_call_participants SET outcome = 'REJECTED', left_at = ? WHERE call_id = ? AND user_id = ?", (db.now(), cid, uid))
            return conn.execute("SELECT COUNT(*) FROM voice_call_participants WHERE call_id = ? AND role = 'callee' AND outcome IS NULL", (cid,)).fetchone()[0]
    pending = await _db(reject)
    await _broadcast(cid, {'t': 'rejected', 'call_id': cid, 'user_id': uid})
    if pending == 0 and len(CALL_MEMBERS.get(cid, set())) <= 1:   # kimse kalmadıysa görüşmeyi kapat
        await _end_call(cid, status='KACIRILDI')


async def _leave(user, cid):
    uid = user['id']
    members = CALL_MEMBERS.get(cid)
    if members and uid in members:
        members.discard(uid)
        await _db(_sql, "UPDATE voice_call_participants SET left_at = ?, outcome = COALESCE(outcome, 'LEFT') WHERE call_id = ? AND user_id = ?", (db.now(), cid, uid))
        await _broadcast(cid, {'t': 'peer_left', 'call_id': cid, 'user_id': uid})
        if len(members) <= 1:
            await _end_call(cid)


async def _end_call(cid, status='BITTI'):
    members = CALL_MEMBERS.pop(cid, set())

    def end():
        with db.connect() as conn:
            row = db.row(conn.execute('SELECT started_at, answered_at, status FROM voice_calls WHERE id = ?', (cid,)))
            if not row or row['status'] in ('BITTI', 'IPTAL', 'KACIRILDI'):
                return
            now = db.now()
            base = row['answered_at'] or row['started_at']
            from datetime import datetime
            secs = max(0, int((datetime.fromisoformat(now) - datetime.fromisoformat(base)).total_seconds())) if row['answered_at'] else 0
            st = status if status != 'BITTI' else ('BITTI' if row['answered_at'] else 'KACIRILDI')
            conn.execute('UPDATE voice_calls SET status = ?, ended_at = ?, seconds = ? WHERE id = ?', (st, now, secs, cid))
            conn.execute("UPDATE voice_call_participants SET left_at = COALESCE(left_at, ?), outcome = COALESCE(outcome, 'MISSED') WHERE call_id = ?", (now, cid))
    try:
        await _db(end)
    except Exception:
        pass
    for uid in members:
        await _send(uid, {'t': 'ended', 'call_id': cid})


async def _rec_request(user, cid):
    uid = user['id']
    members = CALL_MEMBERS.get(cid, set())
    if uid not in members:
        return
    await _db(_sql, 'UPDATE voice_call_participants SET rec_consent = 1 WHERE call_id = ? AND user_id = ?', (cid, uid))   # isteyen otomatik onaylı
    # diğer katılımcılara anlık onay isteği (aynı ekranda)
    await _broadcast(cid, {'t': 'rec_request', 'call_id': cid, 'by': uid, 'by_name': user['full_name']}, exclude=uid)
    await _check_rec(cid)


async def _rec_consent(user, cid, ok):
    uid = user['id']
    await _db(_sql, 'UPDATE voice_call_participants SET rec_consent = ? WHERE call_id = ? AND user_id = ?', (1 if ok else 0, cid, uid))
    await _broadcast(cid, {'t': 'rec_consent', 'call_id': cid, 'user_id': uid, 'ok': ok})
    if not ok:
        await _broadcast(cid, {'t': 'rec_denied', 'call_id': cid, 'by': uid})
        return
    await _check_rec(cid)


async def _rec_stop(user, cid):
    """Kaydı başlatan durdurdu: tüm katılımcılara 'kaydı durdur' yayınla (herkes kendi kaydını kapatıp yükler)."""
    if cid not in CALL_MEMBERS or user['id'] not in CALL_MEMBERS[cid]:
        return
    await _broadcast(cid, {'t': 'rec_stopped', 'call_id': cid, 'by': user['id']})


async def _check_rec(cid):
    """Bağlı tüm katılımcılar onayladıysa kaydı başlat (karışık sesi görüşmeyi başlatan kaydeder)."""
    members = CALL_MEMBERS.get(cid, set())
    if not members:
        return
    def load():
        with db.connect() as conn:
            return ({r[0]: r[1] for r in conn.execute('SELECT user_id, rec_consent FROM voice_call_participants WHERE call_id = ?', (cid,))},
                    conn.execute('SELECT initiator_id FROM voice_calls WHERE id = ?', (cid,)).fetchone())
    consents, init = await _db(load)
    if init and all(consents.get(u) == 1 for u in members):
        await _db(_sql, 'UPDATE voice_calls SET recorded = 1 WHERE id = ?', (cid,))
        recorder = init[0] if init[0] in members else sorted(members)[0]
        await _broadcast(cid, {'t': 'rec_start', 'call_id': cid, 'recorder': recorder})


_ID_CLIP_EXT = {'.webm', '.ogg', '.oga', '.opus', '.mp4', '.m4a', '.mp3', '.wav', '.aac'}
_ID_CLIP_MAX = 12 * 1024 * 1024   # kısa klip; ~1-2 dk fazlasıyla yeter


@router.post('/identify-clip')
async def identify_clip(file: UploadFile, user=Depends(auth.current_user), conn=db.DB):
    """Konuşmacı tanıma CANLI TEST: kısa ses klibinden konuşanın ses-izini (WeSpeaker) çıkarıp kayıtlı ses
    profilleriyle (voice_profiles) eşleştirir. Dönüş {matched, user_id, name, photo, score}. Eşleşme yoksa
    matched False → arayüz 'Tanımsız Kişi' gösterir. Model + ffmpeg sunucuda; voice_profiles bulut DB'sinde."""
    from pathlib import Path
    from .. import meeting_audio
    # available() Toplantılar modül anahtarına bağlıdır; canlı test için yalnız modelin varlığı yeterli.
    if not meeting_audio.MODEL.exists():
        raise HTTPException(503, 'Konuşmacı tanıma modeli bulunamadı (wespeaker)')
    ext = Path(file.filename or 'a.webm').suffix.lower() or '.webm'
    if ext not in _ID_CLIP_EXT:
        raise HTTPException(400, 'Desteklenmeyen ses biçimi')
    data = await file.read(_ID_CLIP_MAX + 1)
    if len(data) > _ID_CLIP_MAX:
        raise HTTPException(400, 'Klip çok uzun')
    if not data:
        raise HTTPException(400, 'Klip boş')
    profs = meeting_audio.profiles(conn)
    if not profs:
        return {'matched': False, 'user_id': None, 'name': None, 'photo': None, 'score': None, 'no_profiles': True}

    def run():
        import tempfile
        from .. import document_media
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / f'clip{ext}'
            src.write_bytes(data)
            wav = Path(tmp) / 'clip.wav'
            document_media._to_wav(src, wav)
            sig = meeting_audio.read_wav(wav)
            if sig is None or len(sig) < meeting_audio.SR // 2:   # < 0.5 sn konuşma
                return 'short'
            return meeting_audio.best_profile(meeting_audio.embed(sig), profs)

    res = await run_in_threadpool(run)
    if res == 'short':
        return {'matched': False, 'user_id': None, 'name': None, 'photo': None, 'score': None, 'short': True}
    uid, score = (res if res else (None, 0.0))
    if not uid:
        return {'matched': False, 'user_id': None, 'name': None, 'photo': None, 'score': round(float(score), 3)}
    row = db.row(conn.execute('SELECT full_name, photo FROM users WHERE id = ?', (uid,)))
    return {'matched': True, 'user_id': uid, 'name': row['full_name'] if row else None,
            'photo': row['photo'] if row else None, 'score': round(float(score), 3)}


# ---------- REST: kişiler, geçmiş, transkript ----------
@router.get('/users')
def callable_users(user=Depends(auth.current_user), conn=db.DB):
    """Aranabilecek kişiler (aktif kullanıcılar) + çevrimiçi bilgisi."""
    online = _online()
    rows = db.rows(conn.execute(
        'SELECT id, full_name, photo FROM users WHERE active = 1 AND deleted_at IS NULL AND id != ? ORDER BY full_name', (user['id'],)))
    absent = auth.absent_map(conn)
    for r in rows:
        r['online'] = r['id'] in online
        r['absence'] = absent.get(r['id'])   # izinli / raporlu (aranabilir ama bilgi olarak gösterilir)
    return rows


@router.get('/online')
def online_ids(user=Depends(auth.current_user)):
    return {'online': sorted(_online())}


@router.get('/calls')
def my_calls(user=Depends(auth.current_user), conn=db.DB):
    rows = db.rows(conn.execute(
        '''SELECT c.*, iu.full_name AS initiator_name FROM voice_calls c
           LEFT JOIN users iu ON iu.id = c.initiator_id
           WHERE c.id IN (SELECT call_id FROM voice_call_participants WHERE user_id = ?)
           ORDER BY c.started_at DESC LIMIT 300''', (user['id'],)))
    for c in rows:
        c['participants'] = db.rows(conn.execute(
            '''SELECT p.user_id, p.role, p.outcome, u.full_name, u.photo FROM voice_call_participants p
               JOIN users u ON u.id = p.user_id WHERE p.call_id = ? ORDER BY p.role DESC, u.full_name''', (c['id'],)))
    return rows


@router.get('/with/{uid}')
def calls_with(uid: int, user=Depends(auth.current_user), conn=db.DB):
    """Bir kişiyle olan bire-bir görüşmeler (sohbet dizisine karışması için) — kayıtlıysa transkript segmentleriyle."""
    me = user['id']
    rows = db.rows(conn.execute(
        '''SELECT c.* FROM voice_calls c
           WHERE c.kind = 'bire_bir'
             AND c.id IN (SELECT call_id FROM voice_call_participants WHERE user_id = ?)
             AND c.id IN (SELECT call_id FROM voice_call_participants WHERE user_id = ?)
           ORDER BY c.started_at''', (me, uid)))
    for c in rows:
        c['has_audio'] = bool(conn.execute('SELECT 1 FROM voice_call_audio WHERE call_id = ? LIMIT 1', (c['id'],)).fetchone())
        c['segments'] = db.rows(conn.execute(
            '''SELECT s.audio_id, s.t0, s.text, sp.label AS speaker_label, sp.user_id AS speaker_user
               FROM voice_call_segments s LEFT JOIN voice_call_speakers sp ON sp.id = s.speaker_id
               WHERE s.call_id = ? ORDER BY s.t0''', (c['id'],))) if c['recorded'] else []
    return rows


@router.get('/calls/{cid}')
def call_detail(cid: int, user=Depends(auth.current_user), conn=db.DB):
    c = db.row(conn.execute('SELECT c.*, iu.full_name AS initiator_name FROM voice_calls c LEFT JOIN users iu ON iu.id = c.initiator_id WHERE c.id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Görüşme bulunamadı')
    if not conn.execute('SELECT 1 FROM voice_call_participants WHERE call_id = ? AND user_id = ?', (cid, user['id'])).fetchone():
        raise HTTPException(403, 'Bu görüşmeye katılmadınız')
    c['participants'] = db.rows(conn.execute(
        '''SELECT p.user_id, p.role, p.outcome, u.full_name, u.photo FROM voice_call_participants p
           JOIN users u ON u.id = p.user_id WHERE p.call_id = ? ORDER BY p.role DESC, u.full_name''', (cid,)))
    c['speakers'] = db.rows(conn.execute(
        'SELECT id, label, user_id, auto, score, seconds FROM voice_call_speakers WHERE call_id = ? ORDER BY seconds DESC', (cid,)))
    c['segments'] = db.rows(conn.execute(
        '''SELECT s.id, s.audio_id, s.speaker_id, s.t0, s.t1, s.at, s.text, sp.label AS speaker_label, sp.user_id AS speaker_user
           FROM voice_call_segments s LEFT JOIN voice_call_speakers sp ON sp.id = s.speaker_id
           WHERE s.call_id = ? ORDER BY s.audio_id, s.t0''', (cid,)))
    c['has_audio'] = bool(conn.execute('SELECT 1 FROM voice_call_audio WHERE call_id = ? LIMIT 1', (cid,)).fetchone())
    # atama için: görüşme katılımcıları (öncelikli) + aktif kullanıcılar
    c['assignable'] = db.rows(conn.execute(
        'SELECT id, full_name, photo FROM users WHERE active = 1 AND deleted_at IS NULL ORDER BY full_name'))
    return c


@router.get('/calls/{cid}/audio')
def call_audio(cid: int, aid: int | None = None, user=Depends(auth.current_user), conn=db.DB):
    """Görüşme kaydını oynatmak için ses dosyasını akışlar (yalnızca katılımcı).

    Her katılımcının kendi mikrofon kaydı ayrı dosyadır; transkriptteki bir satır o segmentin ait olduğu
    dosyayı (aid = audio_id) çalar; aid verilmezse ilk kayıt döner (geriye dönük uyum)."""
    from fastapi.responses import FileResponse

    from .. import config
    if not conn.execute('SELECT 1 FROM voice_call_participants WHERE call_id = ? AND user_id = ?', (cid, user['id'])).fetchone():
        raise HTTPException(403, 'Bu görüşmeye katılmadınız')
    a = (db.row(conn.execute('SELECT file, wav FROM voice_call_audio WHERE call_id = ? AND id = ?', (cid, aid))) if aid
         else db.row(conn.execute('SELECT file, wav FROM voice_call_audio WHERE call_id = ? ORDER BY id LIMIT 1', (cid,))))
    if not a:
        raise HTTPException(404, 'Kayıt yok')
    # Oynatmada WAV'ı tercih et: tarayıcı MediaRecorder webm'inde süre/seek bilgisi olmadığından o ana gidemiyor;
    # işleme sırasında üretilen WAV tam seek edilebilir. WAV yoksa özgün kayda düş.
    rel = a['wav'] if a['wav'] and (config.UPLOAD_DIR / a['wav']).is_file() else a['file']
    path = config.UPLOAD_DIR / rel
    if not path.is_file():
        raise HTTPException(404, 'Ses dosyası bulunamadı')
    ext = path.suffix.lower()
    mt = {'.webm': 'audio/webm', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4', '.mp4': 'audio/mp4', '.wav': 'audio/wav'}.get(ext, 'application/octet-stream')
    return FileResponse(path, media_type=mt, filename=f'gorusme-{cid}{ext}')


@router.post('/calls/{cid}/recording')
async def upload_recording(cid: int, file: UploadFile = File(...), user=Depends(auth.current_user), conn=db.DB):
    c = db.row(conn.execute('SELECT * FROM voice_calls WHERE id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Görüşme bulunamadı')
    if not conn.execute('SELECT 1 FROM voice_call_participants WHERE call_id = ? AND user_id = ?', (cid, user['id'])).fetchone():
        raise HTTPException(403, 'Bu görüşmeye katılmadınız')
    if not c['recorded']:
        raise HTTPException(400, 'Bu görüşme için kayıt onayı yok')
    path = await save_upload('calls', file)
    started = c['answered_at'] or c['started_at']
    # her katılımcı KENDİ mikrofonunu yükler (user_id ile); kişi başına net ses → kesin konuşmacı ataması
    conn.execute('INSERT INTO voice_call_audio (call_id, user_id, file, started_at, ended_at) VALUES (?,?,?,?,?)',
                 (cid, user['id'], path, started, db.now()))
    if voice_audio.available():
        conn.execute("UPDATE voice_calls SET process_status = 'ISLENIYOR' WHERE id = ?", (cid,))
        conn.commit()
        voice_audio.schedule(cid)   # kısa gecikme: diğer katılımcının kaydı da gelsin, tek işlemede toplansın
    else:   # konuşma tanıma kapalı / kurulu değil: kayıt saklanır, metne çevrilmez
        conn.execute("UPDATE voice_calls SET process_status = 'TAMAM', process_error = NULL WHERE id = ?", (cid,))
    db.audit(conn, user['id'], 'Görüşme kaydı yükledi', 'voice_call', cid)
    return {'ok': True, 'processing': voice_audio.available()}


class AssignIn(BaseModel):
    user_id: Optional[int] = None


@router.post('/calls/{cid}/speakers/{sid}/assign')
def assign_speaker(cid: int, sid: int, body: AssignIn, user=Depends(auth.current_user), conn=db.DB):
    """Bir konuşmacıyı kişiye atar; o kişinin ses profilini günceller (sonraki görüşmelerde otomatik tanınır)."""
    import json as _json

    from ..meeting_audio import learn
    sp = db.row(conn.execute('SELECT * FROM voice_call_speakers WHERE id = ? AND call_id = ?', (sid, cid)))
    if not sp:
        raise HTTPException(404, 'Konuşmacı bulunamadı')
    if not conn.execute('SELECT 1 FROM voice_call_participants WHERE call_id = ? AND user_id = ?', (cid, user['id'])).fetchone():
        raise HTTPException(403, 'Bu görüşmeye katılmadınız')
    if body.user_id:
        name = conn.execute('SELECT full_name FROM users WHERE id = ?', (body.user_id,)).fetchone()
        if not name:
            raise HTTPException(400, 'Kullanıcı bulunamadı')
        conn.execute('UPDATE voice_call_speakers SET user_id = ?, auto = 0, label = ? WHERE id = ?', (body.user_id, name[0], sid))
        if sp['embedding']:
            learn(conn, body.user_id, _json.loads(sp['embedding']), max(1, int(sp['seconds'] or 1)))
        _rematch(conn, cid)   # güncel profillerle kalan bilinmeyenleri yeniden dener
    else:
        conn.execute('UPDATE voice_call_speakers SET user_id = NULL, auto = 0, label = ? WHERE id = ?',
                     (f'Kişi {sid}', sid))
    return {'ok': True}


def _rematch(conn, cid):
    """Atanmamış konuşmacıları güncel ses profilleriyle yeniden tanımaya çalışır (bir kişi atanınca)."""
    import json as _json

    from ..meeting_audio import _unit, best_profile, profiles
    profs = profiles(conn)
    taken = {r[0] for r in conn.execute('SELECT user_id FROM voice_call_speakers WHERE call_id = ? AND user_id IS NOT NULL', (cid,))}
    for row in db.rows(conn.execute("SELECT id, embedding FROM voice_call_speakers WHERE call_id = ? AND user_id IS NULL AND embedding IS NOT NULL", (cid,))):
        uid, score = best_profile(_unit(_json.loads(row['embedding'])), profs, exclude=taken)
        if uid:
            nm = conn.execute('SELECT full_name FROM users WHERE id = ?', (uid,)).fetchone()[0]
            conn.execute('UPDATE voice_call_speakers SET user_id = ?, auto = 1, score = ?, label = ? WHERE id = ?', (uid, round(score, 3), nm, row['id']))
            taken.add(uid)


@router.post('/calls/{cid}/reprocess')
def reprocess(cid: int, user=Depends(auth.current_user), conn=db.DB):
    c = db.row(conn.execute('SELECT initiator_id, recorded FROM voice_calls WHERE id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Görüşme bulunamadı')
    if not c['recorded'] or not voice_audio.available():
        raise HTTPException(400, 'İşlenecek kayıt yok')
    conn.execute("UPDATE voice_calls SET process_status = 'ISLENIYOR' WHERE id = ?", (cid,))
    conn.commit()
    voice_audio.start(cid)
    return {'ok': True}
