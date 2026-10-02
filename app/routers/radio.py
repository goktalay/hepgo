"""Telsiz (bas-konuş): sistem yöneticisinin tanımladığı kanallar; üyeler kendi resmine basılı tutarak konuşur.

Ses canlı olarak WebSocket (/ws/radio) üzerinden sunucuya gelir ve kanalın o an çevrimiçi olan diğer üyelerine anında
iletilir (onay gerekmez, ses SAKLANMAZ). Aynı anda birden çok kişi konuşursa her birinin sesi ayrı ayrı iletilir ve
alıcıda canlı karışır.

İkili ses çerçevesi:  istemci → sunucu  [0x01][kanal u32 BE][μ-law 16 kHz mono]
                      sunucu → istemci  [0x01][kanal u32 BE][konuşan u32 BE][μ-law 16 kHz mono]
Metin mesajları: {t:'talk', ch, on} (konuşma başladı/bitti), {t:'ping'}.

Birim hatları (Sekreterya / Güvenlik): herkes birime seslenebilir; ses birimin rolündeki çevrimiçi görevlilere gider
ve görevlinin ekranındaki bekleme odasında seslenenin resmi belirir (birden çok kişi aynı anda bekleyebilir).
Görevli o resme basılı tutunca YALNIZCA o kişiyle konuşur.
  birime seslenme kanalı : 0xF0000000 | birim                (birim: 1 Sekreterya, 2 Güvenlik)
  görevliden kişiye özel : 0x80000000 | birim << 24 | kişi_id
"""
import json
import struct
import time
import asyncio
from contextlib import closing
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import auth, db, push

router = APIRouter(prefix='/api/radio')
ws_router = APIRouter()

PEERS = {}       # user_id -> set[WebSocket]
TALKING = {}     # kanal -> set[user_id]
_members = {}    # kanal -> set[user_id] (önbellek; yönetim değişikliğinde temizlenir)
MAX_FRAME = 16384
COLORS = ['#2f6fed', '#16a34a', '#e8590c', '#9333ea', '#dc2626', '#0ea5a4', '#db2777', '#ca8a04']


_company = {'id': None, 'members': set(), 't': 0.0}
COMPANY_NAME = 'Tüm Şirket'
# "Tüm Şirket" kanalı KAPALI: tüm şirkete yapılan çağrılar sunucuyu kilitliyordu (yönetim kararı, 01.10.2026).
# Kanal kaydı silinmez; listede görünmez ve bu kanala ses gönderilmez.
COMPANY_ENABLED = False


def company_id(conn=None):
    """Sabit "Tüm Şirket" kanalı: yoksa oluşturulur. Herkes üyedir, silinemez, listede en üsttedir."""
    if _company['id']:
        return _company['id']
    own = conn is None
    conn = conn or db.connect()
    try:
        r = conn.execute('SELECT id FROM radio_channels WHERE is_company = 1 ORDER BY id LIMIT 1').fetchone()
        if r:
            _company['id'] = r[0]
        else:
            _company['id'] = conn.execute("INSERT INTO radio_channels (name, color, is_company, created_at) VALUES (?, '#16407e', 1, ?)",
                                          (COMPANY_NAME, db.now())).lastrowid
            conn.commit()
    finally:
        if own:
            conn.close()
    return _company['id']


def members_of(ch):
    if ch == company_id() and not COMPANY_ENABLED:
        return set()
    if ch == company_id():
        if time.time() - _company['t'] > 30:   # tüm aktif kullanıcılar (30 sn önbellek)
            with closing(db.connect()) as conn:   # closing: bağlantı açık kalmasın
                _company['members'] = {r[0] for r in conn.execute('SELECT id FROM users WHERE active = 1 AND deleted_at IS NULL')}
            _company['t'] = time.time()
        return _company['members']
    m = _members.get(ch)
    if m is None:
        with closing(db.connect()) as conn:
            m = {r[0] for r in conn.execute("SELECT user_id FROM radio_members WHERE channel_id = ? AND status = 'UYE'", (ch,))}
        _members[ch] = m
    return m


# ---------- Birim hatları (Sekreterya / Güvenlik) ----------
DESK_BASE = 0xF0000000
DESKS = {1: {'name': 'Sekreterya', 'role': auth.SECRETARY, 'color': '#9333ea'},
         2: {'name': 'Güvenlik', 'role': auth.SECURITY, 'color': '#dc2626'}}
_desk_cache = {}   # birim -> (zaman, set[uid])


def desk_of(ch):
    """Birime seslenme kanalıysa birim no."""
    return ch & 0xFF if ch & 0xF0000000 == DESK_BASE and (ch & 0xFF) in DESKS else None


def private_of(ch):
    """Görevliden kişiye özel kanalsa (birim, kişi)."""
    if ch & 0x80000000 and ch & 0xF0000000 != DESK_BASE:
        d = (ch >> 24) & 0x7F
        if d in DESKS:
            return d, ch & 0xFFFFFF
    return None


def desk_staff(d):
    t, m = _desk_cache.get(d, (0, set()))
    if time.time() - t > 30:
        with closing(db.connect()) as conn:
            m = {r[0] for r in conn.execute(
                'SELECT r.user_id FROM user_roles r JOIN users u ON u.id = r.user_id '
                'WHERE r.role = ? AND u.active = 1 AND u.deleted_at IS NULL', (DESKS[d]['role'],))}
        _desk_cache[d] = (time.time(), m)
    return m


def recipients(ch, sender):
    """Bu kanala `sender`'ın gönderdiği ses/konuşma bilgisi kimlere gider? Yetkisizse None."""
    d = desk_of(ch)
    if d:
        return desk_staff(d)                 # herkes birime seslenebilir
    p = private_of(ch)
    if p:
        d, target = p
        return {target} if sender in desk_staff(d) else None   # yalnızca görevli kişiye özel cevap verir
    members = members_of(ch)
    return members if sender in members else None


def _uinfo(conn, ids):
    ids = list(ids)
    if not ids:
        return {}
    return {r['id']: r for r in db.rows(conn.execute(
        f"SELECT id, full_name, photo FROM users WHERE active = 1 AND deleted_at IS NULL AND id IN ({','.join('?' * len(ids))})", ids))}


def _channel_rows(conn, where='', args=()):
    company_id(conn)
    chans = db.rows(conn.execute(
        f'''SELECT c.id, c.name, c.color, c.is_company, c.created_by, u.full_name AS owner_name
            FROM radio_channels c LEFT JOIN users u ON u.id = c.created_by {where}
            ORDER BY c.is_company DESC, c.name''', args))
    for c in chans:
        c['is_company'] = bool(c['is_company'])
        uids = list(members_of(c['id']))
        info = _uinfo(conn, uids)
        c['members'] = sorted(({'id': u, 'full_name': info[u]['full_name'], 'photo': info[u]['photo'], 'online': u in PEERS}
                               for u in uids if u in info), key=lambda x: (not x['online'], x['full_name']))
        c['online'] = sum(1 for x in c['members'] if x['online'])
        c['talking'] = sorted(TALKING.get(c['id'], ()))
    return chans


# ---------- REST ----------
@router.get('/channels')
def my_channels(user=Depends(auth.current_user), conn=db.DB):
    """Telsiz menüsü: sabit "Tüm Şirket" + ÜYESİ olduğum kanallar (davet onaylanmadan görünmez)."""
    company = 'c.is_company = 1 OR ' if COMPANY_ENABLED else ''
    return _channel_rows(conn, f"WHERE {company}c.id IN (SELECT channel_id FROM radio_members WHERE user_id = ? AND status = 'UYE')",
                         (user['id'],))


@router.get('/desks')
def desks(user=Depends(auth.current_user), conn=db.DB):
    """Sekreterya / Güvenlik birim hatları ve kullanıcının görevli olduğu birimler (bekleme odası)."""
    out = []
    for d, cfg in DESKS.items():
        staff = desk_staff(d)
        info = _uinfo(conn, staff)
        members = sorted(({'id': u, 'full_name': info[u]['full_name'], 'photo': info[u]['photo'], 'online': u in PEERS}
                          for u in staff if u in info), key=lambda x: (not x['online'], x['full_name']))
        out.append({'id': DESK_BASE | d, 'desk': d, 'name': cfg['name'], 'color': cfg['color'], 'is_desk': True,
                    'members': members, 'online': sum(1 for x in members if x['online'])})
    return {'desks': out, 'staff_of': [DESK_BASE | d for d in DESKS if user['id'] in desk_staff(d)]}


# ---------- Kullanıcının kendi kanalları (Ayarlar › Telsiz Kanallarım) ----------
# Kanalı herkes oluşturabilir; oluşturan sahibidir. Eklenen kişilere davet (onay bildirimi) gider, onaylayan üye olur.
@router.get('/mine')
def mine(user=Depends(auth.current_user), conn=db.DB):
    me = user['id']
    owned = db.rows(conn.execute('SELECT id, name, color FROM radio_channels WHERE created_by = ? AND is_company = 0 ORDER BY name', (me,)))
    for c in owned:
        c['people'] = db.rows(conn.execute(
            '''SELECT u.id, u.full_name, u.photo, m.status FROM radio_members m JOIN users u ON u.id = m.user_id
               WHERE m.channel_id = ? AND m.user_id != ? ORDER BY m.status DESC, u.full_name''', (c['id'], me)))
    member = db.rows(conn.execute(
        '''SELECT c.id, c.name, c.color, u.full_name AS owner_name,
                  (SELECT COUNT(*) FROM radio_members x WHERE x.channel_id = c.id AND x.status = 'UYE') AS member_count
           FROM radio_members m JOIN radio_channels c ON c.id = m.channel_id LEFT JOIN users u ON u.id = c.created_by
           WHERE m.user_id = ? AND m.status = 'UYE' AND c.is_company = 0 AND c.created_by IS NOT ? ORDER BY c.name''', (me, me)))
    invites = db.rows(conn.execute(
        '''SELECT c.id, c.name, c.color, u.full_name AS invited_by_name, u.photo AS invited_by_photo, m.invited_at
           FROM radio_members m JOIN radio_channels c ON c.id = m.channel_id LEFT JOIN users u ON u.id = m.invited_by
           WHERE m.user_id = ? AND m.status = 'DAVET' ORDER BY m.invited_at DESC''', (me,)))
    users = db.rows(conn.execute('SELECT id, full_name, photo FROM users WHERE active = 1 AND deleted_at IS NULL AND id != ? ORDER BY full_name', (me,)))
    return {'owned': owned, 'member': member, 'invites': invites, 'users': users, 'colors': COLORS}


class ChannelIn(BaseModel):
    name: str
    color: Optional[str] = None
    user_ids: list[int] = []


async def _notify_channels_changed(uids):
    for u in uids:
        await _send_json(u, {'t': 'channels'})


def _owned(conn, ch, user):
    c = db.row(conn.execute('SELECT * FROM radio_channels WHERE id = ?', (ch,)))
    if not c:
        raise HTTPException(404, 'Kanal bulunamadı')
    if c['is_company'] or c['created_by'] != user['id']:
        raise HTTPException(403, 'Bu kanalı yalnızca oluşturan kişi düzenleyebilir')
    return c


def _sync_people(conn, ch, me, user_ids):
    """Seçilen kişiler: yeni olanlar DAVET olarak eklenir, çıkarılanlar silinir; sahibi her zaman üye."""
    valid = {r[0] for r in conn.execute('SELECT id FROM users WHERE active = 1 AND deleted_at IS NULL')}
    want = {u for u in user_ids if u in valid and u != me}
    have = {r[0] for r in conn.execute('SELECT user_id FROM radio_members WHERE channel_id = ? AND user_id != ?', (ch, me))}
    for u in have - want:
        conn.execute('DELETE FROM radio_members WHERE channel_id = ? AND user_id = ?', (ch, u))
    now = db.now()
    conn.executemany("INSERT OR IGNORE INTO radio_members (channel_id, user_id, status, invited_by, invited_at) VALUES (?,?,'DAVET',?,?)",
                     [(ch, u, me, now) for u in want - have])
    conn.execute("INSERT OR IGNORE INTO radio_members (channel_id, user_id, status) VALUES (?,?,'UYE')", (ch, me))
    _members.pop(ch, None)
    return have | want


@router.post('/channels')
async def create_channel(body: ChannelIn, user=Depends(auth.current_user), conn=db.DB):
    name = body.name.strip()[:60]
    if not name:
        raise HTTPException(400, 'Kanal adı zorunlu')
    ch = conn.execute('INSERT INTO radio_channels (name, color, created_by, created_at) VALUES (?,?,?,?)',
                      (name, body.color if body.color in COLORS else COLORS[0], user['id'], db.now())).lastrowid
    _sync_people(conn, ch, user['id'], body.user_ids)
    db.audit(conn, user['id'], 'Telsiz kanalı oluşturdu', 'radio', ch, name)
    conn.commit()
    await _notify_channels_changed({user['id']})
    return {'id': ch}


@router.put('/channels/{ch}')
async def update_channel(ch: int, body: ChannelIn, user=Depends(auth.current_user), conn=db.DB):
    _owned(conn, ch, user)
    name = body.name.strip()[:60]
    if not name:
        raise HTTPException(400, 'Kanal adı zorunlu')
    before = members_of(ch).copy()
    conn.execute('UPDATE radio_channels SET name = ?, color = ? WHERE id = ?', (name, body.color if body.color in COLORS else COLORS[0], ch))
    _sync_people(conn, ch, user['id'], body.user_ids)
    conn.commit()
    await _notify_channels_changed(before | members_of(ch))
    return {'ok': True}


@router.delete('/channels/{ch}')
async def delete_channel(ch: int, user=Depends(auth.current_user), conn=db.DB):
    _owned(conn, ch, user)
    before = members_of(ch).copy()
    conn.execute('DELETE FROM radio_channels WHERE id = ?', (ch,))
    _members.pop(ch, None); TALKING.pop(ch, None)
    db.audit(conn, user['id'], 'Telsiz kanalını sildi', 'radio', ch)
    conn.commit()
    await _notify_channels_changed(before)
    return {'ok': True}


@router.post('/channels/{ch}/accept')
async def accept_invite(ch: int, user=Depends(auth.current_user), conn=db.DB):
    if not conn.execute("UPDATE radio_members SET status = 'UYE' WHERE channel_id = ? AND user_id = ? AND status = 'DAVET'",
                        (ch, user['id'])).rowcount:
        raise HTTPException(404, 'Bekleyen davet bulunamadı')
    _members.pop(ch, None)
    conn.commit()
    await _notify_channels_changed(members_of(ch))
    return {'ok': True}


@router.post('/channels/{ch}/decline')
async def decline_invite(ch: int, user=Depends(auth.current_user), conn=db.DB):
    conn.execute("DELETE FROM radio_members WHERE channel_id = ? AND user_id = ? AND status = 'DAVET'", (ch, user['id']))
    return {'ok': True}


@router.post('/channels/{ch}/leave')
async def leave_channel(ch: int, user=Depends(auth.current_user), conn=db.DB):
    c = db.row(conn.execute('SELECT created_by, is_company FROM radio_channels WHERE id = ?', (ch,)))
    if not c or c['is_company']:
        raise HTTPException(400, 'Bu kanaldan ayrılamazsınız')
    if c['created_by'] == user['id']:
        raise HTTPException(400, 'Kendi kanalınızdan ayrılamazsınız; isterseniz silebilirsiniz')
    before = members_of(ch).copy()
    conn.execute('DELETE FROM radio_members WHERE channel_id = ? AND user_id = ?', (ch, user['id']))
    _members.pop(ch, None)
    conn.commit()
    await _notify_channels_changed(before)
    return {'ok': True}


# ---------- WebSocket ----------
async def _send_json(uid, msg):
    data = json.dumps(msg)
    for ws in list(PEERS.get(uid, ())):
        try:
            await ws.send_text(data)
        except Exception:
            PEERS.get(uid, set()).discard(ws)


async def _broadcast_channel(ch, msg):
    for u in members_of(ch):
        if u in PEERS:
            await _send_json(u, msg)


async def _presence(uid, online):
    """Kanal arkadaşlarına çevrimiçi/çevrimdışı bilgisi (üye listesindeki avatarlar)."""
    def load():   # iş parçacığında: veritabanı meşgulken ana döngü donmasın
        with db.connect() as conn:
            return [r[0] for r in conn.execute('SELECT channel_id FROM radio_members WHERE user_id = ?', (uid,))] + [company_id(conn)]
    chans = await asyncio.to_thread(load)
    peers = set()
    for ch in chans:
        peers |= members_of(ch)
    peers.discard(uid)
    for u in peers:
        if u in PEERS:
            await _send_json(u, {'t': 'presence', 'uid': uid, 'online': online})


async def _set_talk(ch, uid, on):
    s = TALKING.setdefault(ch, set())
    if on:
        s.add(uid)
    else:
        s.discard(uid)
    to = (recipients(ch, uid) or set()) | {uid}
    msg = {'t': 'talk', 'ch': ch, 'uid': uid, 'on': bool(on)}
    if on:   # bağlı olmayanlara (uygulama kapalı / ekran kilitli) arka plan bildirimi
        push.radio_talk(ch, uid, to, set(PEERS))
    for u in to:
        if u in PEERS:
            await _send_json(u, msg)


@ws_router.websocket('/ws/radio')
async def ws_radio(ws: WebSocket):
    await ws.accept()
    def who():
        with db.connect() as conn:
            return auth.user_by_token(conn, ws.cookies.get(auth.COOKIE))
    user = await asyncio.to_thread(who)
    if not user:
        await ws.close()
        return
    uid = user['id']
    first = uid not in PEERS
    PEERS.setdefault(uid, set()).add(ws)
    if first:
        await _presence(uid, True)
    try:
        while True:
            msg = await ws.receive()
            if msg.get('type') == 'websocket.disconnect':
                break
            data = msg.get('bytes')
            if data:
                if len(data) < 6 or len(data) > MAX_FRAME or data[0] != 1:
                    continue
                ch = struct.unpack('>I', data[1:5])[0]
                members = recipients(ch, uid)
                if members is None:
                    continue
                out = b'\x01' + data[1:5] + struct.pack('>I', uid) + data[5:]
                for u in members:
                    if u == uid:
                        continue
                    for peer in list(PEERS.get(u, ())):
                        try:
                            await peer.send_bytes(out)
                        except Exception:
                            PEERS.get(u, set()).discard(peer)
                continue
            try:
                m = json.loads(msg.get('text') or '{}')
            except Exception:
                continue
            if m.get('t') == 'talk':
                ch = m.get('ch')
                if isinstance(ch, int) and 0 <= ch < 2 ** 32 and recipients(ch, uid) is not None:
                    await _set_talk(ch, uid, m.get('on'))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        PEERS.get(uid, set()).discard(ws)
        if not PEERS.get(uid):
            PEERS.pop(uid, None)
            for ch, s in list(TALKING.items()):
                if uid in s:
                    await _set_talk(ch, uid, False)
            await _presence(uid, False)
