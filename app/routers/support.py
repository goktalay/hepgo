"""Merkez › Destek Merkezi API'si (yalnız merkez modunda): talepler (SLA, iç not, ek, toplu işlem), canlı destek sohbetleri,
destek ekibi ve durum, hazır yanıtlar, ayarlar, ödeme bildirimleri. Firma tarafı aynı verilere /api/federation/* ile, firma
kimliği (slug) ve paylaşılan federasyon anahtarıyla erişir; firmalar iç notları ve başka firmanın kaydını asla görmez."""
import json
import re
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, config, db, policy, push, support
from .central import _companies, _fed, _fee, _packages, _pay_status, _period

router = APIRouter(prefix='/api/central/support')
fed = APIRouter(prefix='/api/federation')
staff_user = auth.require_module('tickets')
MAX_FILES = 5


def _central():
    if not config.FEDERATION_CENTRAL:
        raise HTTPException(404, 'Bulunamadı')


def _is_manager(user):
    return user.get('master') or auth.ADMIN in user.get('roles', []) or 'members' in user.get('modules', [])


def _manager(user=Depends(staff_user)):
    if not _is_manager(user):
        raise HTTPException(403, 'Bu işlem için destek yöneticisi (Sistem Yöneticisi) yetkisi gerekir')
    return user


def _wrap(fn):
    try:
        return fn()
    except support.SupportError as e:
        raise HTTPException(400, str(e)) from e


async def _payload(request: Request):
    """JSON ya da multipart (dosyalı) gövde → (alanlar, [(ad, tür, veri)])."""
    ctype = request.headers.get('content-type', '')
    if ctype.startswith(('multipart/form-data', 'application/x-www-form-urlencoded')):
        form = await request.form()
        fields, files = {}, []
        for k, v in form.multi_items():
            if hasattr(v, 'filename'):
                if v.filename and len(files) < MAX_FILES:
                    files.append((v.filename, v.content_type, await v.read()))
            else:
                fields[k] = v
        return fields, files
    try:
        return (await request.json()) or {}, []
    except ValueError:
        return {}, []


def _send_file(f):
    p = Path(f['path'])
    if not p.exists():
        raise HTTPException(404, 'Dosya bulunamadı')
    inline = (f['mime'] or '').split('/')[0] in ('image', 'video') or f['mime'] == 'application/pdf'
    return FileResponse(p, media_type=f['mime'] if inline else 'application/octet-stream', filename=f['name'],
                        content_disposition_type='inline' if inline else 'attachment',
                        headers={'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox",
                                 'Cache-Control': 'private, max-age=3600'})


def _ticket(conn, tid):
    t = db.row(conn.execute('''SELECT t.*, u.full_name AS assignee_name FROM tickets t LEFT JOIN users u ON u.id = t.assignee_id
                               WHERE t.id = ?''', (tid,)))
    if not t:
        raise HTTPException(404, 'Talep bulunamadı')
    return t


def _member_ctx(conn, slug):
    """Talebin / sohbetin yan panelinde firma özeti: paket, ücret, bu ay ödeme, açık talepler, askı."""
    try:
        comps, pkgs = _companies(), _packages()
    except HTTPException:
        comps, pkgs = [], []
    c = next((x for x in comps if x.get('slug') == slug), None) or {'slug': slug}
    pkg = next((p for p in pkgs if p.get('id') == c.get('package_id')), None)
    fee = _fee(c, pkgs) if c.get('id') else 0.0
    per = _period()
    paid = conn.execute('SELECT COALESCE(SUM(amount), 0) FROM member_payments WHERE slug = ? AND period = ?', (slug, per)).fetchone()[0]
    flag = db.row(conn.execute('SELECT suspended, reason, phone FROM member_flags WHERE slug = ?', (slug,))) or {}
    return {'name': c.get('name') or slug, 'slug': slug, 'url': c.get('url'), 'status': c.get('status'), 'package': pkg['name'] if pkg else None,
            'fee': fee, 'pay_status': _pay_status(fee, paid, per), 'master': c.get('master_username'), 'phone': flag.get('phone'),
            'suspended': bool(flag.get('suspended')),
            'open_tickets': conn.execute("SELECT COUNT(*) FROM tickets WHERE slug = ? AND status IN ('acik','yanit_bekliyor')", (slug,)).fetchone()[0],
            'recent': db.rows(conn.execute('SELECT id, code, subject, status, updated_at FROM tickets WHERE slug = ? ORDER BY updated_at DESC LIMIT 6', (slug,)))}


# ======================= MERKEZ (destek ekibi) =======================
@router.get('/pulse')
def pulse(user=Depends(staff_user), conn=db.DB):
    """Destek Merkezi açıkken birkaç saniyede bir: çevrimiçi işareti, bekleyen sohbetler, okunmamışlar."""
    _central()
    support.touch(conn, user['id'])
    support.sweep(conn)
    conn.commit()
    me = db.row(conn.execute('SELECT status FROM support_staff WHERE user_id = ?', (user['id'],))) or {}
    return {'status': me.get('status') or 'online',
            'waiting_chats': conn.execute("SELECT COUNT(*) FROM support_chats WHERE status = 'waiting'").fetchone()[0],
            'my_chats_unread': conn.execute("SELECT COALESCE(SUM(support_unread),0) FROM support_chats WHERE status = 'active' AND assignee_id = ?",
                                            (user['id'],)).fetchone()[0],
            'tickets_unread': conn.execute("SELECT COUNT(*) FROM tickets WHERE support_unread > 0 AND status != 'kapali' AND (assignee_id IS NULL OR assignee_id = ?)",
                                           (user['id'],)).fetchone()[0]}


class StatusIn(BaseModel):
    status: str


@router.put('/me/status')
def my_status(body: StatusIn, user=Depends(staff_user), conn=db.DB):
    _central()
    _wrap(lambda: support.set_status(conn, user['id'], body.status))
    conn.commit()
    return {'status': body.status}


@router.get('/overview')
def overview(user=Depends(staff_user), conn=db.DB):
    _central()
    support.touch(conn, user['id'])
    support.sweep(conn)
    conn.commit()
    d = support.overview(conn, user['id'])
    d['manager'] = bool(_is_manager(user))
    return d


VIEWS = {
    'mine': "t.assignee_id = :me AND t.status IN ('acik','yanit_bekliyor')",
    'unassigned': "t.assignee_id IS NULL AND t.status IN ('acik','yanit_bekliyor')",
    'open': "t.status IN ('acik','yanit_bekliyor')",
    'awaiting': "t.status = 'acik'",
    'company': "t.status = 'yanit_bekliyor'",
    'resolved': "t.status IN ('cozuldu','kapali')",
    'all': '1=1',
}


@router.get('/tickets')
def tickets(view: str = 'open', q: str = '', category: str = '', priority: str = '', slug: str = '', source: str = '', user=Depends(staff_user), conn=db.DB):
    """source: '' tümü | 'company' firmalar (federasyon) | 'mastertool' Mastertool araçları (slug mastertool) | 'simumav' SIMUMAV oyunu (etiket SIMUMAV)."""
    _central()
    w, a = [VIEWS.get(view, VIEWS['open']) if view != 'overdue' else VIEWS['open']], {'me': user['id']}
    if q:
        w.append('(t.subject LIKE :q OR t.company_name LIKE :q OR t.code LIKE :q OR t.opened_by_name LIKE :q)'); a['q'] = f'%{q.strip()}%'
    if source == 'company':
        w.append("t.slug != 'mastertool'")
    elif source == 'mastertool':
        w.append("t.slug = 'mastertool' AND COALESCE(t.tags, '') != 'SIMUMAV'")
    elif source == 'simumav':
        w.append("t.slug = 'mastertool' AND t.tags = 'SIMUMAV'")
    if category:
        w.append('t.category = :cat'); a['cat'] = category
    if priority:
        w.append('t.priority = :pr'); a['pr'] = priority
    if slug:
        w.append('t.slug = :slug'); a['slug'] = slug
    rows = db.rows(conn.execute(f'''SELECT t.*, u.full_name AS assignee_name,
                                     (SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id = t.id AND m.author_kind IN ('company','support')) AS msg_count
                                     FROM tickets t LEFT JOIN users u ON u.id = t.assignee_id WHERE {" AND ".join(w)}
                                     ORDER BY CASE t.priority WHEN 'acil' THEN 0 WHEN 'yuksek' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                                              t.support_unread DESC, t.updated_at DESC LIMIT 500''', a))
    for t in rows:
        t['sla'] = support.sla_state(t)
    if view == 'overdue':
        rows = [t for t in rows if t['sla']['overdue']]
    counts = {}
    for k in VIEWS:
        counts[k] = conn.execute(f'SELECT COUNT(*) FROM tickets t WHERE {VIEWS[k]}', {'me': user['id']}).fetchone()[0]
    counts['overdue'] = sum(1 for t in db.rows(conn.execute(f"SELECT * FROM tickets t WHERE {VIEWS['open']}")) if support.sla_state(t)['overdue'])
    return {'tickets': rows, 'counts': counts}


@router.get('/tickets/{tid}')
def ticket(tid: int, user=Depends(staff_user), conn=db.DB):
    _central()
    t = _ticket(conn, tid)
    if t['support_unread']:
        conn.execute('UPDATE tickets SET support_unread = 0 WHERE id = ?', (tid,))
        conn.commit()
    t['messages'] = support.ticket_messages(conn, tid, internal=True)
    t['sla'] = support.sla_state(t)
    t['member'] = _member_ctx(conn, t['slug'])
    if t.get('chat_id'):
        t['chat_code'] = (conn.execute('SELECT code FROM support_chats WHERE id = ?', (t['chat_id'],)).fetchone() or [None])[0]
    return t


@router.post('/tickets/{tid}/messages')
async def ticket_reply(tid: int, request: Request, user=Depends(staff_user), conn=db.DB):
    _central()
    t = _ticket(conn, tid)
    f, files = await _payload(request)
    internal = str(f.get('internal', '')).lower() in ('1', 'true', 'on')
    _wrap(lambda: support.support_reply(conn, tid, user, f.get('body', ''), internal, files, t['slug']))
    if f.get('status') in support.STATUSES:
        support.set_status_ticket(conn, _ticket(conn, tid), f['status'], user['full_name'])
    db.audit(conn, user['id'], 'Destek: iç not ekledi' if internal else 'Destek: talebi yanıtladı', 'ticket', tid)
    conn.commit()
    if not internal:
        from . import sshmaster_admin   # Mastertool talebi: kullanıcıya e-posta (döngüsel içe aktarım olmasın diye burada)
        sshmaster_admin.notify_reply(t)
    return ticket(tid, user, conn)


class TicketUpd(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    assignee_id: Optional[int] = None
    tags: Optional[str] = None


def _apply(conn, t, body, user):
    if body.status:
        support.set_status_ticket(conn, t, body.status, user['full_name'])
    if body.priority in support.PRIORITIES and body.priority != t['priority']:
        cfg = support.settings(conn)
        conn.execute('UPDATE tickets SET priority = ?, due_at = ?, resolve_due_at = ?, updated_at = ? WHERE id = ?',
                     (body.priority, support.due(t['created_at'], body.priority, cfg), support.due(t['created_at'], body.priority, cfg, 'resolve'),
                      db.now(), t['id']))
    if body.category in support.CATEGORIES:
        conn.execute('UPDATE tickets SET category = ? WHERE id = ?', (body.category, t['id']))
    if body.tags is not None:
        conn.execute('UPDATE tickets SET tags = ? WHERE id = ?', (body.tags.strip()[:200] or None, t['id']))
    if body.assignee_id is not None and (body.assignee_id or None) != t['assignee_id']:
        to = body.assignee_id or None
        name = (conn.execute('SELECT full_name FROM users WHERE id = ?', (to,)).fetchone() or ['—'])[0] if to else 'kimseye'
        conn.execute('UPDATE tickets SET assignee_id = ?, updated_at = ? WHERE id = ?', (to, db.now(), t['id']))
        support._sys(conn, t['id'], f'{user["full_name"]}: talep {name} atandı.' if to else f'{user["full_name"]}: atama kaldırıldı.')
        if to and to != user['id']:
            push.send({to}, {'type': 'ticket', 'title': f'Size atanan talep · {t["company_name"]}', 'body': t['subject'],
                             'url': f'/app#/tickets/t/{t["id"]}', 'tag': f'ticket-{t["id"]}'})


@router.put('/tickets/{tid}')
def ticket_update(tid: int, body: TicketUpd, user=Depends(staff_user), conn=db.DB):
    _central()
    _apply(conn, _ticket(conn, tid), body, user)
    conn.commit()
    return ticket(tid, user, conn)


class BulkIn(TicketUpd):
    ids: List[int]


@router.post('/tickets/bulk')
def bulk(body: BulkIn, user=Depends(staff_user), conn=db.DB):
    _central()
    for tid in body.ids[:200]:
        _apply(conn, _ticket(conn, tid), body, user)
    conn.commit()
    return {'ok': True, 'count': len(body.ids[:200])}


@router.get('/files/{token}')
def file(token: str, user=Depends(staff_user), conn=db.DB):
    _central()
    f = support.file_row(conn, token)
    if not f:
        raise HTTPException(404, 'Dosya bulunamadı')
    return _send_file(f)


# ---- canlı destek
@router.get('/live')
def live(user=Depends(staff_user), conn=db.DB):
    _central()
    support.touch(conn, user['id'])
    support.sweep(conn)
    conn.commit()
    rows = db.rows(conn.execute('''SELECT c.*, u.full_name AS assignee_name,
                                     (SELECT body FROM support_chat_messages m WHERE m.chat_id = c.id AND m.author_kind != 'system' ORDER BY m.id DESC LIMIT 1) AS last_body
                                     FROM support_chats c LEFT JOIN users u ON u.id = c.assignee_id
                                     WHERE c.status IN ('waiting','active') ORDER BY c.created_at'''))
    for r in rows:
        r['typing'] = support.is_typing(r['id'], 'company')
    return {'waiting': [r for r in rows if r['status'] == 'waiting'], 'mine': [r for r in rows if r['status'] == 'active' and r['assignee_id'] == user['id']],
            'others': [r for r in rows if r['status'] == 'active' and r['assignee_id'] != user['id']],
            'recent': db.rows(conn.execute('''SELECT c.id, c.code, c.company_name, c.user_name, c.topic, c.status, c.rating, c.ended_at, c.ticket_id,
                                              u.full_name AS assignee_name FROM support_chats c LEFT JOIN users u ON u.id = c.assignee_id
                                              WHERE c.status IN ('ended','missed') ORDER BY COALESCE(c.ended_at, c.created_at) DESC LIMIT 30'''))}


@router.get('/chats/{cid}')
def chat(cid: int, after: int = 0, user=Depends(staff_user), conn=db.DB):
    _central()
    c = support.chat_view(conn, cid, after)
    if not c:
        raise HTTPException(404, 'Sohbet bulunamadı')
    if c['assignee_id'] == user['id'] and c['support_unread']:
        conn.execute('UPDATE support_chats SET support_unread = 0 WHERE id = ?', (cid,))
        conn.commit()
    c['typing'] = support.is_typing(cid, 'company')
    if not after:
        c['member'] = _member_ctx(conn, c['slug'])
    return c


@router.post('/chats/{cid}/accept')
def chat_accept(cid: int, user=Depends(staff_user), conn=db.DB):
    _central()
    _wrap(lambda: support.accept_chat(conn, cid, user))
    db.audit(conn, user['id'], 'Destek: canlı sohbeti aldı', 'chat', cid)
    conn.commit()
    return chat(cid, 0, user, conn)


def _own_chat(conn, cid, user):
    c = db.row(conn.execute('SELECT * FROM support_chats WHERE id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Sohbet bulunamadı')
    if c['status'] != 'active':
        raise HTTPException(409, 'Sohbet aktif değil')
    if c['assignee_id'] != user['id'] and not _is_manager(user):
        raise HTTPException(403, 'Bu sohbet başka bir destek uzmanında')
    return c


@router.post('/chats/{cid}/messages')
async def chat_send(cid: int, request: Request, user=Depends(staff_user), conn=db.DB):
    _central()
    c = _own_chat(conn, cid, user)
    f, files = await _payload(request)
    text = (f.get('body') or '').strip()[:4000]
    if not text and not files:
        raise HTTPException(400, 'Mesaj boş olamaz')
    for fn, mime, data in files:
        meta = _wrap(lambda: support.save_file(conn, c['slug'], fn, mime, data, 'support', chat_id=cid))
        support.chat_msg(conn, cid, 'support', user['full_name'], meta['name'], 'file', meta['id'])
    if text:
        support.chat_msg(conn, cid, 'support', user['full_name'], text)
    conn.commit()
    return {'ok': True}


@router.post('/chats/{cid}/typing')
def chat_typing(cid: int, user=Depends(staff_user)):
    support.typing(cid, 'support')
    return {'ok': True}


class TransferIn(BaseModel):
    to: int


@router.post('/chats/{cid}/transfer')
def chat_transfer(cid: int, body: TransferIn, user=Depends(staff_user), conn=db.DB):
    _central()
    _own_chat(conn, cid, user)
    _wrap(lambda: support.transfer_chat(conn, cid, user, body.to))
    return {'ok': True}


@router.post('/chats/{cid}/end')
def chat_end(cid: int, user=Depends(staff_user), conn=db.DB):
    _central()
    _own_chat(conn, cid, user)
    support.end_chat(conn, cid, 'support', user['full_name'])
    return {'ok': True}


class ToTicketIn(BaseModel):
    subject: str = ''
    priority: str = 'normal'


@router.post('/chats/{cid}/ticket')
def chat_ticket(cid: int, body: ToTicketIn, user=Depends(staff_user), conn=db.DB):
    _central()
    tid = _wrap(lambda: support.chat_to_ticket(conn, cid, body.subject.strip() or None, body.priority, user))
    return {'ticket_id': tid}


# ---- hazır yanıtlar
class CannedIn(BaseModel):
    title: str
    body: str
    shortcut: str = ''


@router.get('/canned')
def canned(user=Depends(staff_user), conn=db.DB):
    _central()
    return db.rows(conn.execute('SELECT * FROM support_canned ORDER BY title COLLATE NOCASE'))


@router.post('/canned')
def canned_add(body: CannedIn, user=Depends(staff_user), conn=db.DB):
    _central()
    if not body.title.strip() or not body.body.strip():
        raise HTTPException(400, 'Başlık ve metin gerekli')
    cur = conn.execute('INSERT INTO support_canned (shortcut, title, body, created_by, created_at) VALUES (?,?,?,?,?)',
                       (re.sub(r'[^a-z0-9ğüşıöç-]', '', body.shortcut.lower())[:30] or None, body.title.strip()[:120], body.body.strip()[:4000], user['id'], db.now()))
    conn.commit()
    return {'id': cur.lastrowid}


@router.put('/canned/{cid}')
def canned_upd(cid: int, body: CannedIn, user=Depends(staff_user), conn=db.DB):
    _central()
    conn.execute('UPDATE support_canned SET shortcut = ?, title = ?, body = ?, updated_at = ? WHERE id = ?',
                 (re.sub(r'[^a-z0-9ğüşıöç-]', '', body.shortcut.lower())[:30] or None, body.title.strip()[:120], body.body.strip()[:4000], db.now(), cid))
    conn.commit()
    return {'ok': True}


@router.delete('/canned/{cid}')
def canned_del(cid: int, user=Depends(staff_user), conn=db.DB):
    _central()
    conn.execute('DELETE FROM support_canned WHERE id = ?', (cid,))
    conn.commit()
    return {'ok': True}


# ---- destek ekibi
@router.get('/staff')
def team(user=Depends(staff_user), conn=db.DB):
    _central()
    since = db.now()[:8] + '01'
    rows = support.staff(conn)
    for s in rows:
        s['resolved_month'] = conn.execute("SELECT COUNT(*) FROM tickets WHERE assignee_id = ? AND resolved_at >= ?", (s['id'], since)).fetchone()[0]
        s['chats_month'] = conn.execute('SELECT COUNT(*) FROM support_chats WHERE assignee_id = ? AND created_at >= ?', (s['id'], since)).fetchone()[0]
        r = conn.execute('''SELECT AVG(rating), COUNT(rating) FROM (SELECT rating FROM tickets WHERE assignee_id = ? AND rating IS NOT NULL
                            UNION ALL SELECT rating FROM support_chats WHERE assignee_id = ? AND rating IS NOT NULL)''', (s['id'], s['id'])).fetchone()
        s['csat'], s['csat_count'] = (round(r[0], 2) if r[0] else None), r[1]
        s['is_support_role'] = bool(conn.execute('SELECT 1 FROM user_roles WHERE user_id = ? AND role = ?', (s['id'], auth.SUPPORT_ROLE)).fetchone())
    cand = db.rows(conn.execute('''SELECT id, full_name, username FROM users WHERE active = 1 AND deleted_at IS NULL ORDER BY full_name'''))
    ids = {s['id'] for s in rows}
    return {'staff': rows, 'candidates': [c for c in cand if c['id'] not in ids], 'categories': support.CATEGORIES,
            'manager': bool(_is_manager(user)), 'me': user['id']}


class StaffUpd(BaseModel):
    skills: Optional[List[str]] = None
    max_chats: Optional[int] = None
    title: Optional[str] = None
    status: Optional[str] = None


@router.put('/staff/{uid}')
def staff_upd(uid: int, body: StaffUpd, user=Depends(_manager), conn=db.DB):
    _central()
    now = db.now()
    conn.execute("INSERT OR IGNORE INTO support_staff (user_id, status, updated_at) VALUES (?, 'online', ?)", (uid, now))
    if body.skills is not None:
        conn.execute('UPDATE support_staff SET skills = ? WHERE user_id = ?', (json.dumps([s for s in body.skills if s in support.CATEGORIES]), uid))
    if body.max_chats is not None:
        conn.execute('UPDATE support_staff SET max_chats = ? WHERE user_id = ?', (max(1, min(10, body.max_chats)), uid))
    if body.title is not None:
        conn.execute('UPDATE support_staff SET title = ? WHERE user_id = ?', (body.title.strip()[:80] or None, uid))
    if body.status in support.STAFF_STATUS:
        conn.execute('UPDATE support_staff SET status = ? WHERE user_id = ?', (body.status, uid))
    conn.commit()
    return {'ok': True}


class StaffIn(BaseModel):
    user_id: Optional[int] = None     # mevcut kullanıcıyı ekibe al
    full_name: str = ''               # ya da yeni destek personeli oluştur
    username: str = ''
    password: str = ''
    phone: str = ''
    title: str = ''
    skills: List[str] = []


@router.post('/staff')
def staff_add(body: StaffIn, user=Depends(_manager), conn=db.DB):
    """Ekibe ekle: mevcut kullanıcıya 'Merkez Destek' rolü verir ya da yeni destek personeli hesabı açar (ilk girişte şifre değişir)."""
    _central()
    now = db.now()
    if body.user_id:
        u = db.row(conn.execute('SELECT id, username FROM users WHERE id = ? AND active = 1 AND deleted_at IS NULL', (body.user_id,)))
        if not u:
            raise HTTPException(404, 'Kullanıcı bulunamadı')
        uid = u['id']
    else:
        uname, name = body.username.strip().lower(), body.full_name.strip()
        if not uname or not name:
            raise HTTPException(400, 'Ad soyad ve kullanıcı adı (e-posta) gerekli')
        if conn.execute('SELECT 1 FROM users WHERE username = ?', (uname,)).fetchone():
            raise HTTPException(400, 'Bu kullanıcı adı zaten kayıtlı')
        try:
            policy.validate_password(policy.get(conn), body.password, uname)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        uid = conn.execute('''INSERT INTO users (username, password_hash, full_name, phone, active, created_at, must_change_password)
                              VALUES (?,?,?,?,1,?,1)''', (uname, auth.hash_password(body.password), name, body.phone.strip() or None, now)).lastrowid
        policy.record_history(conn, uid, conn.execute('SELECT password_hash FROM users WHERE id = ?', (uid,)).fetchone()[0])
        db.audit(conn, user['id'], 'Destek personeli oluşturdu', 'user', uid, uname)
    conn.execute('INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, ?)', (uid, auth.SUPPORT_ROLE))
    conn.execute('''INSERT INTO support_staff (user_id, status, skills, title, updated_at) VALUES (?, 'online', ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET skills = excluded.skills, title = COALESCE(excluded.title, support_staff.title)''',
                 (uid, json.dumps([s for s in body.skills if s in support.CATEGORIES]), body.title.strip()[:80] or None, now))
    conn.commit()
    from .. import rbac
    rbac.bump()
    return {'id': uid}


@router.delete('/staff/{uid}')
def staff_remove(uid: int, user=Depends(_manager), conn=db.DB):
    """Ekipten çıkar: 'Merkez Destek' rolü ve ekip ayarı kalkar; kullanıcı hesabı ve geçmiş kayıtlar silinmez."""
    _central()
    conn.execute('DELETE FROM user_roles WHERE user_id = ? AND role = ?', (uid, auth.SUPPORT_ROLE))
    conn.execute('DELETE FROM support_staff WHERE user_id = ?', (uid,))
    conn.execute("UPDATE support_chats SET assignee_id = NULL, status = 'waiting' WHERE assignee_id = ? AND status = 'active'", (uid,))
    db.audit(conn, user['id'], 'Destek ekibinden çıkardı', 'user', uid)
    conn.commit()
    from .. import rbac
    rbac.bump()
    return {'ok': True}


# ---- ayarlar
@router.get('/settings')
def get_settings(user=Depends(staff_user), conn=db.DB):
    _central()
    return {'settings': support.settings(conn), 'manager': bool(_is_manager(user))}


@router.put('/settings')
async def put_settings(request: Request, user=Depends(_manager), conn=db.DB):
    _central()
    body = await request.json()
    s = support.save_settings(conn, body or {})
    db.audit(conn, user['id'], 'Destek ayarlarını güncelledi', 'support', None)
    conn.commit()
    return {'settings': s}


# ---- ödeme bildirimleri (Üyelik Yönetimi › Ödemeler)
members_user = auth.require_module('members')


@router.get('/payment-notices')
def notices(status: str = 'bekliyor', user=Depends(members_user), conn=db.DB):
    _central()
    w, a = ('WHERE status = ?', (status,)) if status in ('bekliyor', 'onaylandi', 'reddedildi') else ('', ())
    return db.rows(conn.execute(f'SELECT * FROM payment_notices {w} ORDER BY created_at DESC LIMIT 300', a))


class DecideIn(BaseModel):
    approve: bool
    period: str = ''
    amount: Optional[float] = None
    note: str = ''


@router.post('/payment-notices/{nid}/decide')
def notice_decide(nid: int, body: DecideIn, user=Depends(members_user), conn=db.DB):
    _central()
    n = db.row(conn.execute('SELECT * FROM payment_notices WHERE id = ?', (nid,)))
    if not n:
        raise HTTPException(404, 'Bildirim bulunamadı')
    if n['status'] != 'bekliyor':
        raise HTTPException(409, 'Bu bildirim zaten sonuçlandırıldı')
    now = db.now()
    pid = None
    if body.approve:
        per = body.period if re.fullmatch(r'\d{4}-\d{2}', body.period or '') else (n['period'] or _period())
        amt = round(body.amount if body.amount and body.amount > 0 else n['amount'], 2)
        pid = conn.execute('''INSERT INTO member_payments (slug, period, amount, paid_at, method, note, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)''',
                           (n['slug'], per, amt, (n['paid_at'] or now)[:10], n['method'] or 'havale',
                            f'Firma bildirimi #{nid}' + (f' · {n["reference"]}' if n['reference'] else ''), user['id'], now)).lastrowid
    conn.execute('UPDATE payment_notices SET status = ?, payment_id = ?, decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?',
                 ('onaylandi' if body.approve else 'reddedildi', pid, user['id'], now, body.note.strip()[:300] or None, nid))
    db.audit(conn, user['id'], 'Ödeme bildirimini onayladı' if body.approve else 'Ödeme bildirimini reddetti', 'payment_notice', nid, n['slug'])
    conn.commit()
    return {'ok': True, 'payment_id': pid}


# ======================= FİRMA → MERKEZ (federasyon) =======================
@fed.get('/support/status')
def fed_support_status(request: Request, slug: str = '', conn=db.DB):
    _fed(request, slug)
    return support.public_status(conn)


@fed.get('/tickets')
def fed_tickets(request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    rows = db.rows(conn.execute('''SELECT id, code, subject, category, priority, status, company_unread, created_at, updated_at, first_response_at,
                                   resolved_at, due_at, rating, channel,
                                   (SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id = t.id AND m.author_kind IN ('company','support')) AS msg_count
                                   FROM tickets t WHERE slug = ? ORDER BY updated_at DESC LIMIT 300''', (slug,)))
    return rows


@fed.post('/tickets')
async def fed_ticket_create(request: Request, slug: str = '', conn=db.DB):
    slug, c = _fed(request, slug)
    f, files = await _payload(request)
    cname = (c or {}).get('name') or str(f.get('company_name') or '')[:120] or slug
    return _wrap(lambda: support.create_ticket(conn, slug, cname, f.get('subject', ''), f.get('body', ''), f.get('category', 'teknik'),
                                               f.get('priority', 'normal'), str(f.get('name') or ''), str(f.get('email') or ''), files=files))


def _fed_ticket(conn, slug, tid):
    t = db.row(conn.execute('''SELECT t.*, u.full_name AS assignee_name, s.title AS assignee_title FROM tickets t
                               LEFT JOIN users u ON u.id = t.assignee_id LEFT JOIN support_staff s ON s.user_id = t.assignee_id
                               WHERE t.id = ? AND t.slug = ?''', (tid, slug)))
    if not t:
        raise HTTPException(404, 'Talep bulunamadı')
    return t


def _fed_view(conn, t):
    t['messages'] = [{k: m[k] for k in ('id', 'author_kind', 'author_name', 'body', 'created_at', 'files')}
                     for m in support.ticket_messages(conn, t['id'], internal=False)]
    for k in ('assignee_id', 'tags', 'support_unread', 'opened_by_email'):
        t.pop(k, None)
    return t


@fed.get('/tickets/{tid}')
def fed_ticket(tid: int, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    t = _fed_ticket(conn, slug, tid)
    if t['company_unread']:
        conn.execute('UPDATE tickets SET company_unread = 0 WHERE id = ?', (tid,))
        conn.commit()
    return _fed_view(conn, t)


@fed.post('/tickets/{tid}/messages')
async def fed_ticket_reply(tid: int, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    t = _fed_ticket(conn, slug, tid)
    f, files = await _payload(request)
    _wrap(lambda: support.company_reply(conn, t, f.get('body', ''), str(f.get('name') or ''), files))
    return _fed_view(conn, _fed_ticket(conn, slug, tid))


class RateIn(BaseModel):
    rating: int
    note: str = ''


@fed.post('/tickets/{tid}/rate')
def fed_ticket_rate(tid: int, body: RateIn, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    t = _fed_ticket(conn, slug, tid)
    if t['status'] not in ('cozuldu', 'kapali'):
        raise HTTPException(409, 'Talep çözüldükten sonra değerlendirilebilir')
    if not 1 <= body.rating <= 5:
        raise HTTPException(400, 'Puan 1 ile 5 arasında olmalı')
    conn.execute('UPDATE tickets SET rating = ?, rating_note = ? WHERE id = ?', (body.rating, body.note.strip()[:500] or None, tid))
    support._sys(conn, tid, f'Firma desteği {body.rating}/5 puanla değerlendirdi.')
    conn.commit()
    return _fed_view(conn, _fed_ticket(conn, slug, tid))


class CloseIn(BaseModel):
    name: str = ''


@fed.post('/tickets/{tid}/close')
def fed_ticket_close(tid: int, body: CloseIn, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    t = _fed_ticket(conn, slug, tid)
    support.set_status_ticket(conn, t, 'cozuldu', body.name or 'Firma')
    conn.execute('UPDATE tickets SET company_unread = 0 WHERE id = ?', (tid,))
    conn.commit()
    return _fed_view(conn, _fed_ticket(conn, slug, tid))


@fed.get('/files/{token}')
def fed_file(token: str, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    f = support.file_row(conn, token, slug)
    if not f:
        raise HTTPException(404, 'Dosya bulunamadı')
    return _send_file(f)


# ---- canlı destek (firma)
@fed.get('/chats')
def fed_chats(request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    support.sweep(conn)
    conn.commit()
    return db.rows(conn.execute('''SELECT c.id, c.code, c.topic, c.status, c.user_name, c.rating, c.ticket_id, c.created_at, c.ended_at, c.company_unread,
                                   u.full_name AS assignee_name FROM support_chats c LEFT JOIN users u ON u.id = c.assignee_id
                                   WHERE c.slug = ? ORDER BY c.created_at DESC LIMIT 50''', (slug,)))


@fed.post('/chats')
def fed_chat_start(body: dict, request: Request, slug: str = '', conn=db.DB):
    slug, c = _fed(request, slug)
    cname = (c or {}).get('name') or str(body.get('company_name') or '')[:120] or slug
    return _wrap(lambda: support.start_chat(conn, slug, cname, str(body.get('name') or ''), str(body.get('email') or ''),
                                            str(body.get('topic') or ''), str(body.get('category') or 'teknik'), str(body.get('message') or '')))


def _fed_chat(conn, slug, cid):
    c = db.row(conn.execute('SELECT * FROM support_chats WHERE id = ? AND slug = ?', (cid, slug)))
    if not c:
        raise HTTPException(404, 'Sohbet bulunamadı')
    return c


@fed.get('/chats/{cid}')
def fed_chat(cid: int, request: Request, slug: str = '', after: int = 0, conn=db.DB):
    slug, _ = _fed(request, slug)
    _fed_chat(conn, slug, cid)
    support.sweep(conn)
    conn.execute('UPDATE support_chats SET company_unread = 0, company_seen_at = ? WHERE id = ?', (db.now(), cid))
    conn.commit()
    c = support.chat_view(conn, cid, after)
    c['typing'] = support.is_typing(cid, 'support')
    for k in ('assignee_id', 'support_unread', 'user_email'):
        c.pop(k, None)
    return c


@fed.post('/chats/{cid}/messages')
async def fed_chat_send(cid: int, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    c = _fed_chat(conn, slug, cid)
    if c['status'] not in ('waiting', 'active'):
        raise HTTPException(409, 'Sohbet sona erdi; yeni bir sohbet başlatın')
    f, files = await _payload(request)
    name = str(f.get('name') or c['user_name'] or c['company_name'])[:120]
    text = str(f.get('body') or '').strip()[:4000]
    kind = 'screen' if f.get('kind') == 'screen' else 'text'
    if kind == 'screen' and not re.match(r'^https://[\w.-]+/s/[A-Z0-9]{5,10}$', text):
        raise HTTPException(400, 'Geçersiz ekran paylaşım bağlantısı')
    if not text and not files:
        raise HTTPException(400, 'Mesaj boş olamaz')
    for fn, mime, data in files:
        meta = _wrap(lambda: support.save_file(conn, slug, fn, mime, data, 'company', chat_id=cid))
        support.chat_msg(conn, cid, 'company', name, meta['name'], 'file', meta['id'])
    if text:
        support.chat_msg(conn, cid, 'company', name, text, kind)
    conn.commit()
    if c['assignee_id'] and kind == 'screen':
        push.send({c['assignee_id']}, {'type': 'chat', 'title': f'Ekran paylaşımı · {c["company_name"]}', 'body': 'Firma ekranını paylaştı',
                                       'url': f'/app#/tickets/live/{cid}', 'tag': f'chat-{cid}'})
    return {'ok': True}


@fed.post('/chats/{cid}/typing')
def fed_chat_typing(cid: int, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    _fed_chat(conn, slug, cid)
    support.typing(cid, 'company')
    return {'ok': True}


@fed.post('/chats/{cid}/end')
def fed_chat_end(cid: int, body: CloseIn, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    c = _fed_chat(conn, slug, cid)
    waiting = c['status'] == 'waiting'
    support.end_chat(conn, cid, 'company', body.name or c['user_name'] or 'Firma')
    if waiting:   # kimse almadan çıkıldı: yazışma kaybolmasın
        support.chat_to_ticket(conn, cid)
    return {'ok': True}


@fed.post('/chats/{cid}/rate')
def fed_chat_rate(cid: int, body: RateIn, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    _fed_chat(conn, slug, cid)
    if not 1 <= body.rating <= 5:
        raise HTTPException(400, 'Puan 1 ile 5 arasında olmalı')
    conn.execute('UPDATE support_chats SET rating = ?, rating_note = ? WHERE id = ?', (body.rating, body.note.strip()[:500] or None, cid))
    conn.commit()
    return {'ok': True}


# ---- ödeme bildirimi (firma)
@fed.get('/payment-notices')
def fed_notices(request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    return db.rows(conn.execute('''SELECT id, period, amount, paid_at, method, reference, note, by_name, status, decision_note, decided_at, created_at
                                   FROM payment_notices WHERE slug = ? ORDER BY created_at DESC LIMIT 60''', (slug,)))


class NoticeIn(BaseModel):
    period: str = ''
    amount: float
    paid_at: str = ''
    method: str = 'havale'
    reference: str = ''
    note: str = ''
    name: str = ''
    email: str = ''


@fed.post('/payment-notices')
def fed_notice_add(body: NoticeIn, request: Request, slug: str = '', conn=db.DB):
    slug, c = _fed(request, slug)
    if body.amount <= 0:
        raise HTTPException(400, 'Tutar sıfırdan büyük olmalı')
    per = body.period if re.fullmatch(r'\d{4}-\d{2}', body.period or '') else _period()
    if conn.execute("SELECT COUNT(*) FROM payment_notices WHERE slug = ? AND status = 'bekliyor'", (slug,)).fetchone()[0] >= 10:
        raise HTTPException(400, 'Onay bekleyen çok sayıda bildiriminiz var')
    cur = conn.execute('''INSERT INTO payment_notices (slug, company_name, period, amount, paid_at, method, reference, note, by_name, by_email, created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                       (slug, (c or {}).get('name') or slug, per, round(body.amount, 2), (body.paid_at or db.now())[:10],
                        body.method if body.method in ('havale', 'eft', 'kart', 'nakit', 'diger') else 'havale',
                        body.reference.strip()[:80] or None, body.note.strip()[:300] or None, body.name[:120], body.email[:160], db.now()))
    conn.commit()
    ids = {r[0] for r in conn.execute('SELECT user_id FROM user_roles WHERE role = ?', (auth.ADMIN,))}
    push.send(ids, {'type': 'payment', 'title': f'Ödeme bildirimi · {(c or {}).get("name") or slug}', 'body': f'{body.amount:,.2f} ₺ · {per}',
                    'url': '/app#/members/payments', 'tag': f'pay-notice-{cur.lastrowid}'})
    return {'id': cur.lastrowid}
