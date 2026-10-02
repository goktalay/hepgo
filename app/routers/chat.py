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
from pydantic import BaseModel

from .. import auth, config, db, push
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
    pr = conn.execute('SELECT prefs FROM users WHERE id = ?', (uid,)).fetchone()
    dnd = auth.dnd_state(pr[0] if pr else None)   # rahatsız etmeyin (mesaj)
    u['no_messages'] = bool(p.get('no_messages')) or dnd['messages']
    u['dnd_messages'] = dnd['messages']
    u['hide_read'] = bool(p.get('hide_read'))
    u['absence'] = auth.absence(conn, uid)   # izinli / raporlu: sohbet başlığında gösterilir
    u['hide_delivered'] = bool(p.get('hide_delivered'))
    return u


# "Yazıyor…" göstergesi: bellekte son yazma zamanı (kalıcı değil). (gönderen, alıcı) ve (gönderen, 'g', grup)
TYPING = {}
TYPING_TTL = 4.5


def _typing_now(key):
    import time
    t = TYPING.get(key)
    return bool(t and time.time() - t < TYPING_TTL)


def _mark_delivered(conn, me):
    """Uygulaması açık olan alıcıya ulaşan mesajlar "iletildi" (✓✓) sayılır."""
    conn.execute('UPDATE chat_messages SET delivered_at = ? WHERE to_id = ? AND delivered_at IS NULL', (db.now(), me))


@router.get('/summary')
def summary(user=Depends(auth.current_user), conn=db.DB):
    """Başlık düğmesi: son sohbetler (kişi başına bir satır), okunmamış sayısı gönderene göre."""
    me = user['id']
    _mark_delivered(conn, me)
    rows = db.rows(conn.execute(
        '''WITH last AS (
               SELECT CASE WHEN from_id = ? THEN to_id ELSE from_id END AS peer, MAX(id) AS mid
               FROM chat_messages WHERE from_id = ? OR to_id = ? GROUP BY peer)
           SELECT u.id, u.full_name, u.photo, CASE WHEN {hide} THEN NULL ELSE u.last_seen END AS last_seen, m.body, m.file_kind, m.file_name, m.from_id, m.created_at, m.deleted_at,
                  (SELECT COUNT(*) FROM chat_messages x WHERE x.from_id = u.id AND x.to_id = ? AND x.read_at IS NULL) AS unread
           FROM last JOIN chat_messages m ON m.id = last.mid JOIN users u ON u.id = last.peer
           ORDER BY unread > 0 DESC, m.id DESC LIMIT 30'''.replace('{hide}', PRIV('hide_online')), (me, me, me, me)))
    cut = (datetime.now() - ONLINE_WINDOW).isoformat(timespec='seconds')
    absent = auth.absent_map(conn)
    for r in rows:
        r['online'] = bool(r['last_seen'] and r['last_seen'] >= cut)
        r['mine'] = r.pop('from_id') == me
        r['kind'] = 'user'
        r['absence'] = absent.get(r['id'])
    items = rows + my_groups(conn, user)   # kişiler + gruplar (Tüm Şirket dahil); okunmamışlar ve en yeni önce
    items.sort(key=lambda r: r['created_at'] or '', reverse=True)
    items.sort(key=lambda r: not r['unread'])
    return {'people': sum(1 for r in items if r['unread']), 'unread': sum(r['unread'] for r in items), 'items': items}


# ---------- Gruplar ve "Tüm Şirket" kanalı
# Tüm Şirket: herkes üyedir (ayrı üyelik kaydı yok), yalnızca Sistem Yöneticisi yazar; şirket logosuyla görünür.
# Diğer gruplar: kuran kişi grup yöneticisidir; üyeleri ve adı o (ya da Sistem Yöneticisi) değiştirir; üye gruptan ayrılabilir.

class GroupIn(BaseModel):
    name: str
    user_ids: list[int] = []


def company_group(conn):
    r = conn.execute('SELECT id FROM chat_groups WHERE is_company = 1').fetchone()
    if r:
        return r[0]
    return conn.execute('INSERT INTO chat_groups (name, is_company, created_at) VALUES (?,1,?)', ('Tüm Şirket', db.now())).lastrowid


def _group(conn, gid, user):
    g = db.row(conn.execute('SELECT * FROM chat_groups WHERE id = ?', (gid,)))
    if not g:
        raise HTTPException(404, 'Grup bulunamadı')
    member = conn.execute('SELECT 1 FROM chat_group_members WHERE group_id = ? AND user_id = ?', (gid, user['id'])).fetchone()
    if not g['is_company'] and not member:
        raise HTTPException(404, 'Grup bulunamadı')
    g['members'] = [] if g['is_company'] else db.rows(conn.execute(
        'SELECT u.id, u.full_name, u.photo, m.is_admin FROM chat_group_members m JOIN users u ON u.id = m.user_id '
        'WHERE m.group_id = ? ORDER BY m.is_admin DESC, u.full_name', (gid,)))
    g['member_count'] = (conn.execute('SELECT COUNT(*) FROM users WHERE active = 1 AND deleted_at IS NULL').fetchone()[0]
                         if g['is_company'] else len(g['members']))
    g['can_post'] = not g['is_company'] or auth.ADMIN in user['roles']
    g['can_edit'] = not g['is_company'] and (auth.ADMIN in user['roles'] or any(m['id'] == user['id'] and m['is_admin'] for m in g['members']))
    return g


def my_groups(conn, user):
    """Kullanıcının grupları (Tüm Şirket dahil): son ileti ve okunmamış sayısı."""
    cid = company_group(conn)
    rows = db.rows(conn.execute(
        'SELECT g.id, g.name, g.is_company, (SELECT MAX(id) FROM chat_group_messages WHERE group_id = g.id) AS mid, '
        'IFNULL((SELECT last_read_id FROM chat_group_reads WHERE group_id = g.id AND user_id = ?), 0) AS read_id '
        'FROM chat_groups g WHERE g.id = ? OR g.id IN (SELECT group_id FROM chat_group_members WHERE user_id = ?)',
        (user['id'], cid, user['id'])))
    for r in rows:
        last = db.row(conn.execute(
            'SELECT m.body, m.file_kind, m.file_name, m.from_id, m.created_at, m.deleted_at, u.full_name AS from_name '
            'FROM chat_group_messages m JOIN users u ON u.id = m.from_id WHERE m.id = ?', (r['mid'],))) if r['mid'] else None
        r.update(last or {'body': None, 'file_kind': None, 'file_name': None, 'from_id': None, 'created_at': None, 'from_name': None})
        r['unread'] = conn.execute('SELECT COUNT(*) FROM chat_group_messages WHERE group_id = ? AND id > ? AND from_id != ?',
                                   (r['id'], r['read_id'], user['id'])).fetchone()[0]
        r['mine'] = r.pop('from_id') == user['id']
        r['kind'] = 'group'
    return rows


def _active_ids(conn, ids):
    for uid in ids:
        if not conn.execute('SELECT 1 FROM users WHERE id = ? AND active = 1 AND deleted_at IS NULL', (uid,)).fetchone():
            raise HTTPException(400, 'Eklenen kişi bulunamadı')


@router.post('/groups')
def create_group(body: GroupIn, user=Depends(auth.current_user), conn=db.DB):
    name = body.name.strip()[:80]
    if not name:
        raise HTTPException(400, 'Grup adı yazın')
    members = sorted({u for u in body.user_ids if u != user['id']})
    if not members:
        raise HTTPException(400, 'En az bir kişi ekleyin')
    _active_ids(conn, members)
    gid = conn.execute('INSERT INTO chat_groups (name, created_by, created_at) VALUES (?,?,?)', (name, user['id'], db.now())).lastrowid
    conn.execute('INSERT INTO chat_group_members (group_id, user_id, is_admin, joined_at) VALUES (?,?,1,?)', (gid, user['id'], db.now()))
    conn.executemany('INSERT INTO chat_group_members (group_id, user_id, joined_at) VALUES (?,?,?)', [(gid, u, db.now()) for u in members])
    db.audit(conn, user['id'], 'Mesaj grubu kurdu', 'chat_group', gid, f'{name} · {len(members) + 1} kişi')
    return _group(conn, gid, user)


@router.get('/groups/{gid}')
def group_info(gid: int, user=Depends(auth.current_user), conn=db.DB):
    return _group(conn, gid, user)


@router.put('/groups/{gid}')
def edit_group(gid: int, body: GroupIn, user=Depends(auth.current_user), conn=db.DB):
    g = _group(conn, gid, user)
    if not g['can_edit']:
        raise HTTPException(403, 'Grubu yalnızca grup yöneticisi değiştirebilir')
    name = body.name.strip()[:80] or g['name']
    keep = {m['id'] for m in g['members'] if m['is_admin']}
    want = set(body.user_ids) | keep
    old = {m['id'] for m in g['members']}
    _active_ids(conn, want - old)
    conn.execute('UPDATE chat_groups SET name = ? WHERE id = ?', (name, gid))
    conn.executemany('DELETE FROM chat_group_members WHERE group_id = ? AND user_id = ?', [(gid, u) for u in old - want])
    conn.executemany('INSERT INTO chat_group_members (group_id, user_id, joined_at) VALUES (?,?,?)', [(gid, u, db.now()) for u in want - old])
    return _group(conn, gid, user)


@router.delete('/groups/{gid}/me')
def leave_group(gid: int, user=Depends(auth.current_user), conn=db.DB):
    g = _group(conn, gid, user)
    if g['is_company']:
        raise HTTPException(400, 'Tüm Şirket kanalından ayrılınamaz')
    conn.execute('DELETE FROM chat_group_members WHERE group_id = ? AND user_id = ?', (gid, user['id']))
    left = db.rows(conn.execute('SELECT user_id, is_admin FROM chat_group_members WHERE group_id = ? ORDER BY joined_at', (gid,)))
    if not left:
        conn.execute('DELETE FROM chat_groups WHERE id = ?', (gid,))
    elif not any(m['is_admin'] for m in left):   # yönetici ayrıldıysa en eski üye yönetici olur
        conn.execute('UPDATE chat_group_members SET is_admin = 1 WHERE group_id = ? AND user_id = ?', (gid, left[0]['user_id']))
    return {'ok': True}


GROUP_SELECT = ('SELECT m.*, u.full_name AS from_name, u.photo AS from_photo FROM chat_group_messages m '
                'JOIN users u ON u.id = m.from_id WHERE m.group_id = ?')


def _mark_read(conn, gid, uid, top):
    conn.execute('INSERT INTO chat_group_reads (group_id, user_id, last_read_id) VALUES (?,?,?) '
                 'ON CONFLICT(group_id, user_id) DO UPDATE SET last_read_id = MAX(last_read_id, excluded.last_read_id)', (gid, uid, top))


# ---------- Mesaj menüsü (WhatsApp tarzı): yanıtla, tepki, ilet, kopyala, yıldızla, düzenle, bilgi, sil
# kind: 'd' birebir (chat_messages) | 'g' grup (chat_group_messages)
TABLE = {'d': 'chat_messages', 'g': 'chat_group_messages'}
EDIT_MINUTES = 15          # kendi metin mesajını bu süre içinde düzenleyebilir
DELETE_ALL_HOURS = 48      # "herkesten sil" bu süre içinde


def _snippet(m):
    if m.get('deleted_at'):
        return 'Bu mesaj silindi'
    if m.get('body'):
        return m['body'][:140]
    return {'image': '📷 Fotoğraf', 'audio': '🎤 Sesli mesaj'}.get(m.get('file_kind'), f"📎 {m.get('file_name') or 'Dosya'}")


def _decorate(conn, kind, rows, me):
    """Mesaj satırlarına yanıt özeti, tepkiler, yıldız, silinmiş bilgisi ekler; 'benden sil'inenleri çıkarır."""
    if not rows:
        return rows
    ids = [r['id'] for r in rows]
    q = ','.join('?' * len(ids))
    hidden = {r[0] for r in conn.execute(f'SELECT msg_id FROM chat_hidden WHERE kind = ? AND user_id = ? AND msg_id IN ({q})', (kind, me, *ids))}
    stars = {r[0] for r in conn.execute(f'SELECT msg_id FROM chat_stars WHERE kind = ? AND user_id = ? AND msg_id IN ({q})', (kind, me, *ids))}
    reacts = {}
    for mid, emoji, uid, name in conn.execute(
            f'SELECT r.msg_id, r.emoji, r.user_id, u.full_name FROM chat_reactions r JOIN users u ON u.id = r.user_id '
            f'WHERE r.kind = ? AND r.msg_id IN ({q}) ORDER BY r.at', (kind, *ids)):
        reacts.setdefault(mid, []).append({'emoji': emoji, 'user_id': uid, 'name': name})
    rids = {r['reply_to'] for r in rows if r.get('reply_to')}
    replies = {}
    if rids:
        rq = ','.join('?' * len(rids))
        for x in db.rows(conn.execute(f'SELECT t.id, t.body, t.file_kind, t.file_name, t.deleted_at, u.full_name AS from_name, t.from_id '
                                      f'FROM {TABLE[kind]} t JOIN users u ON u.id = t.from_id WHERE t.id IN ({rq})', tuple(rids))):
            replies[x['id']] = {'id': x['id'], 'from_name': x['from_name'], 'from_id': x['from_id'], 'text': _snippet(x)}
    out = []
    for r in rows:
        if r['id'] in hidden:
            continue
        if r.get('deleted_at'):
            r.update(body=None, file=None, file_name=None, file_kind=None, file_size=None, duration=None)
        r['deleted'] = bool(r.get('deleted_at'))
        r['starred'] = r['id'] in stars
        r['reactions'] = reacts.get(r['id'], [])
        r['reply'] = replies.get(r.get('reply_to'))
        out.append(r)
    return out


def _msg(conn, kind, mid, user):
    """Kullanıcının görebildiği mesaj (birebirde tarafı, grupta üyesi olmalı) → satır; yoksa 404."""
    if kind not in TABLE:
        raise HTTPException(404, 'Mesaj bulunamadı')
    m = db.row(conn.execute(f'SELECT * FROM {TABLE[kind]} WHERE id = ?', (mid,)))
    if not m:
        raise HTTPException(404, 'Mesaj bulunamadı')
    if kind == 'd':
        if user['id'] not in (m['from_id'], m['to_id']):
            raise HTTPException(404, 'Mesaj bulunamadı')
    else:
        _group(conn, m['group_id'], user)   # üyelik kontrolü
    return m


def _touch(conn, kind, mid):
    conn.execute(f'UPDATE {TABLE[kind]} SET updated_at = ? WHERE id = ?', (db.now(), mid))


class ReactIn(BaseModel):
    emoji: str = ''


@router.post('/msg/{kind}/{mid}/react')
def react(kind: str, mid: int, body: ReactIn, user=Depends(auth.current_user), conn=db.DB):
    m = _msg(conn, kind, mid, user)
    if m.get('deleted_at'):
        raise HTTPException(400, 'Silinmiş mesaja tepki verilemez')
    emoji = (body.emoji or '').strip()[:16]
    cur = conn.execute('SELECT emoji FROM chat_reactions WHERE kind = ? AND msg_id = ? AND user_id = ?', (kind, mid, user['id'])).fetchone()
    if not emoji or (cur and cur[0] == emoji):   # aynı emojiye tekrar basmak tepkiyi kaldırır
        conn.execute('DELETE FROM chat_reactions WHERE kind = ? AND msg_id = ? AND user_id = ?', (kind, mid, user['id']))
    else:
        conn.execute('INSERT OR REPLACE INTO chat_reactions (kind, msg_id, user_id, emoji, at) VALUES (?,?,?,?,?)',
                     (kind, mid, user['id'], emoji, db.now()))
    _touch(conn, kind, mid)
    return _decorate(conn, kind, [_with_names(conn, kind, mid)], user['id'])[0]


@router.post('/msg/{kind}/{mid}/star')
def star(kind: str, mid: int, user=Depends(auth.current_user), conn=db.DB):
    _msg(conn, kind, mid, user)
    if conn.execute('DELETE FROM chat_stars WHERE kind = ? AND msg_id = ? AND user_id = ?', (kind, mid, user['id'])).rowcount:
        return {'starred': False}
    conn.execute('INSERT INTO chat_stars (kind, msg_id, user_id, at) VALUES (?,?,?,?)', (kind, mid, user['id'], db.now()))
    return {'starred': True}


class EditIn(BaseModel):
    body: str


@router.put('/msg/{kind}/{mid}')
def edit_message(kind: str, mid: int, body: EditIn, user=Depends(auth.current_user), conn=db.DB):
    m = _msg(conn, kind, mid, user)
    if m['from_id'] != user['id']:
        raise HTTPException(403, 'Yalnızca kendi mesajınızı düzenleyebilirsiniz')
    if m.get('deleted_at') or not m.get('body') or m.get('forwarded'):
        raise HTTPException(400, 'Bu mesaj düzenlenemez')
    if (datetime.now() - datetime.fromisoformat(m['created_at'])).total_seconds() > EDIT_MINUTES * 60:
        raise HTTPException(400, f'Mesajlar yalnızca gönderildikten sonraki {EDIT_MINUTES} dakika içinde düzenlenebilir')
    text = (body.body or '').strip()[:5000]
    if not text:
        raise HTTPException(400, 'Mesaj boş olamaz')
    now = db.now()
    conn.execute(f'UPDATE {TABLE[kind]} SET body = ?, edited_at = ?, updated_at = ? WHERE id = ?', (text, now, now, mid))
    return _decorate(conn, kind, [_with_names(conn, kind, mid)], user['id'])[0]


@router.delete('/msg/{kind}/{mid}')
def delete_message(kind: str, mid: int, scope: str = 'me', user=Depends(auth.current_user), conn=db.DB):
    m = _msg(conn, kind, mid, user)
    if scope == 'all':
        if m['from_id'] != user['id']:
            raise HTTPException(403, 'Yalnızca kendi mesajınızı herkesten silebilirsiniz')
        if (datetime.now() - datetime.fromisoformat(m['created_at'])).total_seconds() > DELETE_ALL_HOURS * 3600:
            raise HTTPException(400, f'Mesajlar yalnızca {DELETE_ALL_HOURS} saat içinde herkesten silinebilir; “Benden sil”i kullanın')
        now = db.now()
        conn.execute(f'UPDATE {TABLE[kind]} SET body = NULL, file = NULL, file_name = NULL, file_kind = NULL, file_size = NULL, '
                     f'duration = NULL, deleted_at = ?, updated_at = ? WHERE id = ?', (now, now, mid))
        conn.execute('DELETE FROM chat_reactions WHERE kind = ? AND msg_id = ?', (kind, mid))
        return {'ok': True, 'scope': 'all'}
    conn.execute('INSERT OR IGNORE INTO chat_hidden (kind, msg_id, user_id) VALUES (?,?,?)', (kind, mid, user['id']))
    return {'ok': True, 'scope': 'me'}


@router.get('/msg/{kind}/{mid}/info')
def message_info(kind: str, mid: int, user=Depends(auth.current_user), conn=db.DB):
    """Mesaj bilgisi (kendi mesajı): birebirde iletildi / okundu zamanı, grupta okuyanlar ve henüz okumayanlar."""
    m = _msg(conn, kind, mid, user)
    out = {'created_at': m['created_at'], 'edited_at': m.get('edited_at'), 'mine': m['from_id'] == user['id']}
    if not out['mine']:
        return out
    if kind == 'd':
        peer = _peer(conn, m['to_id'], user)
        mine = privacy(conn, user['id'])
        out['delivered_at'] = None if (peer['hide_delivered'] or mine.get('hide_delivered')) else m.get('delivered_at')
        out['read_at'] = None if (peer['hide_read'] or mine.get('hide_read')) else m.get('read_at')
        out['hidden_receipts'] = bool(peer['hide_read'] or mine.get('hide_read'))
        return out
    g = _group(conn, m['group_id'], user)
    members = g['members'] if not g['is_company'] else db.rows(conn.execute(
        'SELECT id, full_name, photo FROM users WHERE active = 1 AND deleted_at IS NULL'))
    read = {r[0] for r in conn.execute('SELECT user_id FROM chat_group_reads WHERE group_id = ? AND last_read_id >= ?', (m['group_id'], mid))}
    others = [x for x in members if x['id'] != user['id']]
    out['read'] = [{'id': x['id'], 'full_name': x['full_name'], 'photo': x.get('photo')} for x in others if x['id'] in read]
    out['unread'] = [{'id': x['id'], 'full_name': x['full_name'], 'photo': x.get('photo')} for x in others if x['id'] not in read]
    return out


class ForwardIn(BaseModel):
    items: list[dict]          # [{kind: 'd'|'g', id}]
    users: list[int] = []
    groups: list[int] = []


@router.post('/forward')
def forward(body: ForwardIn, user=Depends(auth.current_user), conn=db.DB):
    """Mesajları başka kişilere / gruplara iletir (kopyası “İletildi” etiketiyle gönderilir; dosyalar aynı dosyayı paylaşır)."""
    if not body.items or (not body.users and not body.groups):
        raise HTTPException(400, 'İletilecek mesaj ve alıcı seçin')
    if len(body.items) > 30 or len(body.users) + len(body.groups) > 30:
        raise HTTPException(400, 'Tek seferde en fazla 30 mesaj ve 30 alıcı')
    msgs = []
    for it in body.items:
        m = _msg(conn, str(it.get('kind')), int(it.get('id') or 0), user)
        if m.get('deleted_at'):
            continue
        msgs.append(m)
    if not msgs:
        raise HTTPException(400, 'İletilecek mesaj yok')
    now = db.now()
    sent, skipped = 0, []
    cols = 'body, file, file_name, file_kind, file_size, duration'
    for uid in dict.fromkeys(body.users):
        try:
            peer = _peer(conn, uid, user)
        except HTTPException:
            continue
        if not peer['active'] or peer['no_messages']:
            skipped.append(peer['full_name'])
            continue
        for m in msgs:
            conn.execute(f'INSERT INTO chat_messages (from_id, to_id, {cols}, forwarded, created_at) VALUES (?,?,?,?,?,?,?,?,1,?)',
                         (user['id'], uid, m['body'], m['file'], m['file_name'], m['file_kind'], m['file_size'], m['duration'], now))
        sent += 1
    for gid in dict.fromkeys(body.groups):
        try:
            g = _group(conn, gid, user)
        except HTTPException:
            continue
        if not g['can_post']:
            skipped.append(g['name'])
            continue
        last = None
        for m in msgs:
            last = conn.execute(f'INSERT INTO chat_group_messages (group_id, from_id, {cols}, forwarded, created_at) VALUES (?,?,?,?,?,?,?,?,1,?)',
                                (gid, user['id'], m['body'], m['file'], m['file_name'], m['file_kind'], m['file_size'], m['duration'], now)).lastrowid
        if last:
            _mark_read(conn, gid, user['id'], last)
        sent += 1
    return {'sent': sent, 'skipped': skipped}


def _sync_mark():
    """Değişiklik akışı işareti: zaman damgaları saniye hassasiyetinde olduğundan 2 sn geriden (örtüşmeli) verilir;
    aynı saniyedeki düzenleme / silme / tepki kaçmaz (istemci aynı mesajı tekrar alırsa üzerine yazar)."""
    from datetime import timedelta
    return (datetime.now() - timedelta(seconds=2)).isoformat(timespec='seconds')


def _with_names(conn, kind, mid):
    if kind == 'g':
        return db.row(conn.execute('SELECT m.*, u.full_name AS from_name, u.photo AS from_photo FROM chat_group_messages m '
                                   'JOIN users u ON u.id = m.from_id WHERE m.id = ?', (mid,)))
    return db.row(conn.execute('SELECT * FROM chat_messages WHERE id = ?', (mid,)))


def _reply_ok(conn, kind, reply_to, where, args):
    """Yanıtlanan mesaj aynı sohbette olmalı; değilse yok sayılır."""
    if not reply_to:
        return None
    return reply_to if conn.execute(f'SELECT 1 FROM {TABLE[kind]} WHERE id = ? AND {where}', (reply_to, *args)).fetchone() else None


@router.get('/g/{gid}')
def group_messages(gid: int, after: int = 0, before: int = 0, since: str = '', user=Depends(auth.current_user), conn=db.DB):
    g = _group(conn, gid, user)
    if after:
        rows = db.rows(conn.execute(f'{GROUP_SELECT} AND m.id > ? ORDER BY m.id LIMIT 500', (gid, after)))
    else:
        cond = 'AND m.id < ?' if before else ''
        rows = db.rows(conn.execute(f'{GROUP_SELECT} {cond} ORDER BY m.id DESC LIMIT {PAGE}', (gid, before) if before else (gid,)))[::-1]
    _mark_read(conn, gid, user['id'], conn.execute('SELECT MAX(id) FROM chat_group_messages WHERE group_id = ?', (gid,)).fetchone()[0] or 0)
    typers = [k[0] for k in list(TYPING) if len(k) == 3 and k[2] == gid and k[0] != user['id'] and _typing_now(k)]
    names = [r[0] for r in conn.execute(f"SELECT full_name FROM users WHERE id IN ({','.join('?' * len(typers))})", typers)] if typers else []
    # Açık sohbette değişenler (düzenleme / silme / tepki): since'ten sonra güncellenen eski mesajlar
    upd = db.rows(conn.execute(f'{GROUP_SELECT} AND m.updated_at > ? AND m.id <= ?', (gid, since, after))) if since and after else []
    return {'group': g, 'items': _decorate(conn, 'g', rows, user['id']), 'updates': _decorate(conn, 'g', upd, user['id']),
            'sync': _sync_mark(), 'typing': names, 'more': not after and len(rows) == PAGE}


@router.post('/g/{gid}')
async def group_send(gid: int, body: str = Form(''), duration: Optional[float] = Form(None), file: Optional[UploadFile] = File(None),
                     reply_to: Optional[int] = Form(None), user=Depends(auth.current_user), conn=db.DB):
    text = (body or '').strip()[:5000]
    has_file = file is not None and file.filename
    if not text and not has_file:
        raise HTTPException(400, 'Mesaj boş')
    g = _group(conn, gid, user)
    if not g['can_post']:
        raise HTTPException(403, 'Tüm Şirket kanalına yalnızca Sistem Yöneticisi yazabilir')
    path = await save_upload('chat', file) if has_file else None

    def write():
        kind = size = name = None
        if path:
            ext = Path(path).suffix.lower()
            kind = 'image' if ext in IMAGE else 'audio' if ext in AUDIO or (ext == '.webm' and duration) else 'file'
            name = Path(file.filename).name[:200]
            size = (config.UPLOAD_DIR / path).stat().st_size
        rt = _reply_ok(conn, 'g', reply_to, 'group_id = ?', (gid,))
        mid = conn.execute('INSERT INTO chat_group_messages (group_id, from_id, body, file, file_name, file_kind, file_size, duration, created_at, reply_to) '
                           'VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (gid, user['id'], text or None, path, name, kind, size, round(duration, 1) if duration else None, db.now(), rt)).lastrowid
        _mark_read(conn, gid, user['id'], mid)
        TYPING.pop((user['id'], 'g', gid), None)
        members = [r[0] for r in conn.execute('SELECT user_id FROM chat_group_members WHERE group_id = ? AND user_id != ?', (gid, user['id']))]
        push.send(members, {'type': 'chat', 'title': f"{g.get('name') or 'Grup'} — {user['full_name']}", 'body': _push_text(text, kind),
                            'tag': f'chat-g{gid}', 'url': f'/app#/messages/g{gid}'})
        return _decorate(conn, 'g', [db.row(conn.execute(f'{GROUP_SELECT} AND m.id = ?', (gid, mid)))], user['id'])[0]
    return await run_in_threadpool(write)


@router.get('/{uid}')
def messages(uid: int, after: int = 0, before: int = 0, since: str = '', user=Depends(auth.current_user), conn=db.DB):
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
    now = db.now()
    conn.execute('UPDATE chat_messages SET read_at = ?, delivered_at = COALESCE(delivered_at, ?) WHERE from_id = ? AND to_id = ? AND read_at IS NULL',
                 (now, now, uid, me))
    _mark_delivered(conn, me)
    mine = privacy(conn, me)
    # Gönderdiklerimin okundu / iletildi bilgisi (pencere açıkken tikler güncellensin). WhatsApp gibi karşılıklı:
    # kendi bilgisini kapatan, başkalarınınkini de göremez.
    seen = conn.execute('SELECT MAX(id) FROM chat_messages WHERE from_id = ? AND to_id = ? AND read_at IS NOT NULL', (me, uid)).fetchone()[0]
    if peer['hide_read'] or mine.get('hide_read'):
        seen = 0
    delivered = conn.execute('SELECT MAX(id) FROM chat_messages WHERE from_id = ? AND to_id = ? AND delivered_at IS NOT NULL', (me, uid)).fetchone()[0]
    if peer['hide_delivered'] or mine.get('hide_delivered'):
        delivered = 0
    upd = db.rows(conn.execute(f'SELECT * FROM chat_messages WHERE {pair} AND updated_at > ? AND id <= ?', (*args, since, after))) if since and after else []
    return {'peer': peer, 'items': _decorate(conn, 'd', rows, me), 'updates': _decorate(conn, 'd', upd, me), 'sync': _sync_mark(),
            'seen_upto': seen or 0, 'delivered_upto': delivered or 0,
            'typing': _typing_now((uid, me)), 'more': not after and len(rows) == PAGE}


@router.post('/{uid}/typing')
def typing(uid: int, user=Depends(auth.current_user)):
    import time
    TYPING[(user['id'], uid)] = time.time()
    return {'ok': True}


@router.post('/g/{gid}/typing')
def group_typing(gid: int, user=Depends(auth.current_user), conn=db.DB):
    import time
    _group(conn, gid, user)
    TYPING[(user['id'], 'g', gid)] = time.time()
    return {'ok': True}


@router.post('/{uid}')
async def send(uid: int, body: str = Form(''), duration: Optional[float] = Form(None), file: Optional[UploadFile] = File(None),
               reply_to: Optional[int] = Form(None), user=Depends(auth.current_user), conn=db.DB):
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
        TYPING.pop((user['id'], uid), None)
        kind = size = name = None
        if path:
            ext = Path(path).suffix.lower()
            kind = 'image' if ext in IMAGE else 'audio' if ext in AUDIO or (ext == '.webm' and duration) else 'file'
            name = Path(file.filename).name[:200]
            size = (config.UPLOAD_DIR / path).stat().st_size
        rt = _reply_ok(conn, 'd', reply_to, '((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))', (user['id'], uid, uid, user['id']))
        cur = conn.execute('''INSERT INTO chat_messages (from_id, to_id, body, file, file_name, file_kind, file_size, duration, created_at, reply_to)
                              VALUES (?,?,?,?,?,?,?,?,?,?)''',
                           (user['id'], uid, text or None, path, name, kind, size, round(duration, 1) if duration else None, db.now(), rt))
        push.send([uid], {'type': 'chat', 'title': user['full_name'], 'body': _push_text(text, kind),   # rahatsız etmeyin açıksa mesaj zaten gönderilemez
                          'tag': f"chat-d{user['id']}", 'url': f"/app#/messages/u{user['id']}"})
        return _decorate(conn, 'd', [db.row(conn.execute('SELECT * FROM chat_messages WHERE id = ?', (cur.lastrowid,)))], user['id'])[0]
    return await run_in_threadpool(write)


def _push_text(text, kind):
    if text:
        return text[:140]
    return {'image': '📷 Fotoğraf', 'audio': '🎤 Sesli mesaj'}.get(kind, '📎 Dosya')


def _chat_guard(user, name):
    with db.connect() as conn:
        if conn.execute('SELECT 1 FROM chat_messages WHERE file = ? AND (from_id = ? OR to_id = ?)',
                        (f'chat/{name}', user['id'], user['id'])).fetchone():
            return True
        # Dosya birden çok gruba iletilmiş olabilir: üyesi olduğu (ya da Tüm Şirket) herhangi birinde varsa erişir
        return bool(conn.execute(
            '''SELECT 1 FROM chat_group_messages m JOIN chat_groups g ON g.id = m.group_id
               WHERE m.file = ? AND (g.is_company = 1 OR EXISTS (SELECT 1 FROM chat_group_members x WHERE x.group_id = m.group_id AND x.user_id = ?))
               LIMIT 1''', (f'chat/{name}', user['id'])).fetchone())


FILE_GUARDS['chat'] = _chat_guard
