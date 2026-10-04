"""Merkez Destek Merkezi (yalnız merkez modunda kullanılır): destek talepleri için SLA, destek ekibi ve çevrimiçi durumu,
otomatik atama, dosya ekleri, canlı destek sohbetleri ve ayarlar. Uçlar app/routers/support.py'de; firma tarafı federasyonla
(app/routers/membership.py → central_client) gelir.

- SLA: önceliğe göre ilk yanıt ve çözüm hedefi (takvim saatiyle). İlk destek yanıtında first_response_at, çözülünce resolved_at.
- Ekip: 'Merkez Destek' rolündeki kullanıcılar + support_staff satırı olan yöneticiler. Durum (müsait / meşgul / molada /
  çevrimdışı) kullanıcı seçer; 2 dakikadır ekranı açık olmayan çevrimdışı sayılır.
- Canlı destek: firma sohbet başlatır → (otomatik atama açıksa) müsait ve kapasitesi olan, kategoriye uygun kişiye; değilse
  kuyrukta bekler. Belirli süre kimse almazsa sohbet kaçırılmış sayılır ve yazışma talebe dönüşür (hiçbir istek kaybolmaz).
"""
import json
import mimetypes
import secrets
import time
from datetime import datetime, timedelta

from . import auth, config, db, push

SETTINGS_KEY = 'support_settings'
DEFAULTS = {
    'sla_first': {'acil': 1, 'yuksek': 4, 'normal': 8, 'dusuk': 24},       # ilk yanıt hedefi (saat)
    'sla_resolve': {'acil': 8, 'yuksek': 24, 'normal': 72, 'dusuk': 120},  # çözüm hedefi (saat)
    'hours': {'days': [1, 2, 3, 4, 5], 'start': '09:00', 'end': '18:00'},  # canlı destek çalışma saatleri (1 = Pazartesi)
    'auto_assign': True,           # yeni talep / sohbeti uygun kişiye otomatik ata
    'chat_wait_minutes': 10,       # canlı sohbet bu kadar beklerse talebe dönüşür
    'welcome': 'Merhaba! HEPGO destek ekibine bağlandınız. Size nasıl yardımcı olabiliriz?',
    'offline_msg': 'Destek ekibimiz şu an çevrimdışı. Mesajınızı bırakın; talep olarak kaydedip en kısa sürede dönelim.',
    'contact_email': '', 'contact_phone': '',
    'bank_name': '', 'iban': '', 'account_name': '', 'payment_note': '',
}
STATUSES = ('acik', 'yanit_bekliyor', 'cozuldu', 'kapali')
PRIORITIES = ('dusuk', 'normal', 'yuksek', 'acil')
CATEGORIES = ('teknik', 'fatura', 'oneri', 'egitim', 'diger')
STAFF_STATUS = ('online', 'busy', 'away', 'offline')
ONLINE_WINDOW = 120   # sn: bu süre içinde Destek Merkezi açık olan kişi çevrimiçi sayılır
MAX_FILE = 10 * 1024 * 1024
FILE_DIR = config.DATA_DIR / 'support'
ALLOWED_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.txt', '.log', '.csv', '.zip', '.xlsx', '.xls', '.docx', '.doc',
               '.pptx', '.json', '.mp4', '.webm', '.mov', '.heic'}


class SupportError(Exception):
    pass


# ---------------- ayarlar ----------------
def settings(conn):
    r = conn.execute('SELECT v FROM app_kv WHERE k = ?', (SETTINGS_KEY,)).fetchone()
    try:
        saved = json.loads(r[0]) if r else {}
    except ValueError:
        saved = {}
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in saved.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k].update({kk: vv for kk, vv in v.items() if kk in out[k]})
        elif k in out:
            out[k] = v
    return out


def save_settings(conn, patch):
    cur = settings(conn)
    for k, v in patch.items():
        if k not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[k], dict) and isinstance(v, dict):
            cur[k].update({kk: vv for kk, vv in v.items() if kk in DEFAULTS[k]})
        elif isinstance(DEFAULTS[k], bool):
            cur[k] = bool(v)
        elif isinstance(DEFAULTS[k], int):
            cur[k] = max(1, min(240, int(v or DEFAULTS[k])))
        else:
            cur[k] = str(v or '')[:2000]
    for key in ('sla_first', 'sla_resolve'):
        cur[key] = {p: max(0.25, min(720.0, float(cur[key].get(p) or DEFAULTS[key][p]))) for p in PRIORITIES}
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (SETTINGS_KEY, json.dumps(cur, ensure_ascii=False)))
    return cur


def in_hours(cfg, at=None):
    at = at or datetime.now()
    h = cfg['hours']
    if at.isoweekday() not in (h.get('days') or []):
        return False
    hm = at.strftime('%H:%M')
    return (h.get('start') or '00:00') <= hm < (h.get('end') or '23:59')


def due(created, priority, cfg, kind='first'):
    hours = cfg['sla_first' if kind == 'first' else 'sla_resolve'].get(priority) or 8
    return (datetime.fromisoformat(created) + timedelta(hours=float(hours))).isoformat(timespec='seconds')


# ---------------- ekip ----------------
def team_ids(conn):
    """Destek ekibi: 'Merkez Destek' rolündekiler + ekibe eklenmiş (support_staff satırı olan) yöneticiler."""
    ids = {r[0] for r in conn.execute('SELECT user_id FROM user_roles WHERE role = ?', (auth.SUPPORT_ROLE,))}
    ids |= {r[0] for r in conn.execute('SELECT user_id FROM support_staff')}
    return {i for i in ids if conn.execute('SELECT 1 FROM users WHERE id = ? AND active = 1 AND deleted_at IS NULL', (i,)).fetchone()}


def notify_ids(conn):
    """Bildirim alacaklar: ekip + yöneticiler (+ master)."""
    ids = team_ids(conn)
    ids |= {r[0] for r in conn.execute('SELECT user_id FROM user_roles WHERE role = ?', (auth.ADMIN,))}
    ids |= {r[0] for r in conn.execute('SELECT id, username FROM users WHERE active = 1') if auth.is_master(r[1])}
    return ids


def _alive(last_seen):
    if not last_seen:
        return False
    try:
        return (datetime.now() - datetime.fromisoformat(last_seen)).total_seconds() < ONLINE_WINDOW
    except ValueError:
        return False


def staff(conn):
    ids = team_ids(conn)
    if not ids:
        return []
    rows = db.rows(conn.execute(f'''SELECT u.id, u.full_name, u.username, u.photo, s.status, s.skills, s.max_chats, s.title, s.last_seen
                                    FROM users u LEFT JOIN support_staff s ON s.user_id = u.id
                                    WHERE u.id IN ({",".join("?" * len(ids))}) ORDER BY u.full_name''', tuple(ids)))
    for r in rows:
        try:
            r['skills'] = json.loads(r['skills'] or '[]')
        except ValueError:
            r['skills'] = []
        r['max_chats'] = r['max_chats'] or 3
        chosen = r['status'] or 'offline'
        r['presence'] = chosen if chosen != 'offline' and _alive(r['last_seen']) else 'offline'
        r['active_chats'] = conn.execute("SELECT COUNT(*) FROM support_chats WHERE assignee_id = ? AND status = 'active'", (r['id'],)).fetchone()[0]
        r['open_tickets'] = conn.execute("SELECT COUNT(*) FROM tickets WHERE assignee_id = ? AND status IN ('acik','yanit_bekliyor')", (r['id'],)).fetchone()[0]
    return rows


def touch(conn, uid):
    """Destek Merkezi açık: ekip üyesine çevrimiçi işareti (ilk kez açan destek personelinin durumu 'müsait' başlar).
    Ekipte olmayan yöneticiler izler ama atama almaz."""
    now = db.now()
    if conn.execute('UPDATE support_staff SET last_seen = ? WHERE user_id = ?', (now, uid)).rowcount:
        return
    if conn.execute('SELECT 1 FROM user_roles WHERE user_id = ? AND role = ?', (uid, auth.SUPPORT_ROLE)).fetchone():
        conn.execute("INSERT INTO support_staff (user_id, status, last_seen, updated_at) VALUES (?, 'online', ?, ?)", (uid, now, now))


def set_status(conn, uid, status):
    if status not in STAFF_STATUS:
        raise SupportError('Geçersiz durum')
    now = db.now()
    conn.execute('''INSERT INTO support_staff (user_id, status, last_seen, updated_at) VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET status = excluded.status, last_seen = excluded.last_seen, updated_at = excluded.updated_at''',
                 (uid, status, now, now))


def online(conn):
    return [s for s in staff(conn) if s['presence'] == 'online']


def pick(conn, category=None, kind='ticket'):
    """Otomatik atama: müsait (online) kişiler arasından kategoriye uygun ve en az yüklü olan. Yoksa None."""
    cands = online(conn)
    if kind == 'chat':
        cands = [s for s in cands if s['active_chats'] < s['max_chats']]
    if not cands:
        return None
    skilled = [s for s in cands if not s['skills'] or (category and category in s['skills'])]
    pool = skilled or cands
    key = (lambda s: (s['active_chats'], s['open_tickets'])) if kind == 'chat' else (lambda s: (s['open_tickets'], s['active_chats']))
    return min(pool, key=key)['id']


def public_status(conn):
    """Firmaya gösterilen destek durumu: çevrimiçi kişi sayısı, çalışma saati, ortalama ilk yanıt, iletişim ve ödeme bilgisi."""
    cfg = settings(conn)
    on = online(conn)
    since = (datetime.now() - timedelta(days=30)).isoformat(timespec='seconds')
    fr = [r for r in conn.execute('SELECT created_at, first_response_at FROM tickets WHERE first_response_at IS NOT NULL AND created_at >= ?', (since,))]
    mins = [(datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60 for a, b in fr]
    waiting = conn.execute("SELECT COUNT(*) FROM support_chats WHERE status = 'waiting'").fetchone()[0]
    return {'online': len(on), 'in_hours': in_hours(cfg), 'hours': cfg['hours'], 'avg_first_response_min': round(sum(mins) / len(mins)) if mins else None,
            'waiting_chats': waiting, 'welcome': cfg['welcome'], 'offline_msg': cfg['offline_msg'],
            'contact': {'email': cfg['contact_email'], 'phone': cfg['contact_phone']},
            'payment_info': {'bank_name': cfg['bank_name'], 'iban': cfg['iban'], 'account_name': cfg['account_name'], 'note': cfg['payment_note']},
            'sla_first': cfg['sla_first']}


# ---------------- dosyalar ----------------
def save_file(conn, slug, name, mime, data, by, ticket_id=None, message_id=None, chat_id=None):
    name = (name or 'dosya').replace('/', '_').replace('\\', '_')[-120:]
    ext = ('.' + name.rsplit('.', 1)[-1].lower()) if '.' in name else ''
    if ext not in ALLOWED_EXT:
        raise SupportError(f'Bu dosya türü eklenemez ({ext or "uzantısız"})')
    if not data:
        raise SupportError('Dosya boş')
    if len(data) > MAX_FILE:
        raise SupportError('Dosya 10 MB sınırını aşıyor')
    token = secrets.token_urlsafe(18)
    path = FILE_DIR / token[:2] / token
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    mime = (mime or mimetypes.guess_type(name)[0] or 'application/octet-stream')[:100]
    cur = conn.execute('''INSERT INTO support_files (token, slug, ticket_id, message_id, chat_id, name, mime, size, path, uploaded_by, created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (token, slug, ticket_id, message_id, chat_id, name, mime, len(data), str(path), by, db.now()))
    return {'id': cur.lastrowid, 'token': token, 'name': name, 'mime': mime, 'size': len(data)}


def file_row(conn, token, slug=None):
    f = db.row(conn.execute('SELECT * FROM support_files WHERE token = ?', (token,)))
    if not f or (slug is not None and f['slug'] != slug):
        return None
    return f


def _files_by_msg(conn, ticket_id):
    out = {}
    for f in db.rows(conn.execute('SELECT id, token, name, mime, size, message_id FROM support_files WHERE ticket_id = ? ORDER BY id', (ticket_id,))):
        out.setdefault(f['message_id'], []).append({k: f[k] for k in ('token', 'name', 'mime', 'size')})
    return out


def ticket_messages(conn, ticket_id, internal=True):
    rows = db.rows(conn.execute('SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY id', (ticket_id,)))
    files = _files_by_msg(conn, ticket_id)
    out = []
    for m in rows:
        if m['author_kind'] == 'note' and not internal:
            continue
        m['files'] = files.get(m['id'], [])
        out.append(m)
    return out


# ---------------- talepler ----------------
def sla_state(t, now=None):
    """Talebin SLA durumu: first = ilk yanıt (ok | due | late | met), resolve = çözüm."""
    now = (now or datetime.now()).isoformat(timespec='seconds')
    closed = t['status'] in ('cozuldu', 'kapali')
    if t.get('first_response_at'):
        first = 'met' if not t.get('due_at') or t['first_response_at'] <= t['due_at'] else 'late_met'
    elif closed or not t.get('due_at'):
        first = 'na'
    else:
        first = 'late' if now > t['due_at'] else 'due'
    if closed:
        res = 'met' if not t.get('resolve_due_at') or (t.get('resolved_at') or now) <= t['resolve_due_at'] else 'late_met'
    elif not t.get('resolve_due_at'):
        res = 'na'
    else:
        res = 'late' if now > t['resolve_due_at'] else 'due'
    return {'first': first, 'resolve': res, 'overdue': first == 'late' or res == 'late'}


def create_ticket(conn, slug, company_name, subject, body, category='teknik', priority='normal', name='', email='', channel='ticket',
                  chat_id=None, files=()):
    cfg = settings(conn)
    subject, body = (subject or '').strip()[:200], (body or '').strip()[:8000]
    if not subject or not body:
        raise SupportError('Konu ve açıklama gerekli')
    pr = priority if priority in PRIORITIES else 'normal'
    cat = category if category in CATEGORIES else 'diger'
    now = db.now()
    assignee = pick(conn, cat) if cfg['auto_assign'] else None
    cur = conn.execute('''INSERT INTO tickets (slug, company_name, subject, category, priority, status, opened_by_name, opened_by_email, assignee_id,
                          company_unread, support_unread, created_at, updated_at, due_at, resolve_due_at, channel, chat_id)
                          VALUES (?,?,?,?,?,'acik',?,?,?,0,1,?,?,?,?,?,?)''',
                       (slug, company_name, subject, cat, pr, (name or '')[:120], (email or '')[:160], assignee, now, now,
                        due(now, pr, cfg), due(now, pr, cfg, 'resolve'), channel, chat_id))
    tid = cur.lastrowid
    code = f'T-{tid:04d}'
    conn.execute('UPDATE tickets SET code = ? WHERE id = ?', (code, tid))
    mid = conn.execute('INSERT INTO ticket_messages (ticket_id, author_kind, author_name, body, created_at) VALUES (?,?,?,?,?)',
                       (tid, 'company', (name or company_name or slug)[:120], body, now)).lastrowid
    for fn, mime, data in files:
        save_file(conn, slug, fn, mime, data, 'company', ticket_id=tid, message_id=mid)
    if assignee:
        _sys(conn, tid, 'Talep otomatik olarak atandı.', now)
    conn.commit()
    targets = {assignee} if assignee else notify_ids(conn)
    push.send(targets, {'type': 'ticket', 'title': f'Yeni destek talebi · {company_name or slug}', 'body': subject,
                        'url': f'/app#/tickets/t/{tid}', 'tag': f'ticket-{tid}'})
    return {'id': tid, 'code': code}


def _sys(conn, tid, text, now=None):
    conn.execute('INSERT INTO ticket_messages (ticket_id, author_kind, author_name, body, created_at) VALUES (?,?,?,?,?)',
                 (tid, 'system', 'Sistem', text, now or db.now()))


def support_reply(conn, tid, user, text, internal=False, files=(), slug=None):
    text = (text or '').strip()[:8000]
    if not text and not files:
        raise SupportError('Mesaj boş olamaz')
    now = db.now()
    mid = conn.execute('INSERT INTO ticket_messages (ticket_id, author_kind, author_name, body, created_at) VALUES (?,?,?,?,?)',
                       (tid, 'note' if internal else 'support', user['full_name'], text, now)).lastrowid
    for fn, mime, data in files:
        save_file(conn, slug, fn, mime, data, 'support', ticket_id=tid, message_id=mid)
    if internal:
        conn.execute('UPDATE tickets SET updated_at = ? WHERE id = ?', (now, tid))
    else:
        conn.execute("""UPDATE tickets SET status = CASE WHEN status IN ('acik','yanit_bekliyor') THEN 'yanit_bekliyor' ELSE status END,
                        company_unread = company_unread + 1, support_unread = 0, updated_at = ?,
                        first_response_at = COALESCE(first_response_at, ?), assignee_id = COALESCE(assignee_id, ?) WHERE id = ?""",
                     (now, now, user['id'], tid))


def company_reply(conn, t, text, name, files=()):
    text = (text or '').strip()[:8000]
    if not text and not files:
        raise SupportError('Mesaj boş olamaz')
    now = db.now()
    mid = conn.execute('INSERT INTO ticket_messages (ticket_id, author_kind, author_name, body, created_at) VALUES (?,?,?,?,?)',
                       (t['id'], 'company', (name or t['company_name'])[:120], text, now)).lastrowid
    for fn, mime, data in files:
        save_file(conn, t['slug'], fn, mime, data, 'company', ticket_id=t['id'], message_id=mid)
    reopened = t['status'] in ('cozuldu', 'kapali')
    conn.execute("""UPDATE tickets SET status = 'acik', support_unread = support_unread + 1, company_unread = 0, updated_at = ?,
                    resolved_at = CASE WHEN ? THEN NULL ELSE resolved_at END WHERE id = ?""", (now, int(reopened), t['id']))
    if reopened:
        _sys(conn, t['id'], 'Firma talebi yeniden açtı.', now)
    conn.commit()
    target = {t['assignee_id']} if t.get('assignee_id') else notify_ids(conn)
    push.send(target, {'type': 'ticket', 'title': f'Destek talebine yanıt · {t["company_name"]}', 'body': t['subject'],
                       'url': f'/app#/tickets/t/{t["id"]}', 'tag': f'ticket-{t["id"]}'})


def set_status_ticket(conn, t, status, who):
    if status not in STATUSES or status == t['status']:
        return
    now = db.now()
    label = {'acik': 'açık', 'yanit_bekliyor': 'firma yanıtı bekleniyor', 'cozuldu': 'çözüldü', 'kapali': 'kapalı'}[status]
    conn.execute('''UPDATE tickets SET status = ?, updated_at = ?,
                    resolved_at = CASE WHEN ? IN ('cozuldu','kapali') THEN COALESCE(resolved_at, ?) ELSE NULL END WHERE id = ?''',
                 (status, now, status, now, t['id']))
    _sys(conn, t['id'], f'{who}: durum “{label}” olarak değiştirildi.', now)
    if status in ('cozuldu', 'kapali'):
        conn.execute('UPDATE tickets SET company_unread = company_unread + 1 WHERE id = ?', (t['id'],))


# ---------------- canlı destek ----------------
_typing = {}   # chat_id → {'company': zaman, 'support': zaman}


def typing(chat_id, side):
    _typing.setdefault(chat_id, {})[side] = time.time()


def is_typing(chat_id, side):
    return time.time() - _typing.get(chat_id, {}).get(side, 0) < 6


def chat_msg(conn, chat_id, kind, name, body, mkind='text', file_id=None):
    now = db.now()
    mid = conn.execute('''INSERT INTO support_chat_messages (chat_id, author_kind, author_name, body, kind, file_id, created_at)
                          VALUES (?,?,?,?,?,?,?)''', (chat_id, kind, name, body, mkind, file_id, now)).lastrowid
    conn.execute('UPDATE support_chats SET last_msg_at = ? WHERE id = ?', (now, chat_id))
    if kind == 'company':
        conn.execute('UPDATE support_chats SET support_unread = support_unread + 1 WHERE id = ?', (chat_id,))
    elif kind == 'support':
        conn.execute('UPDATE support_chats SET company_unread = company_unread + 1 WHERE id = ?', (chat_id,))
    _typing.get(chat_id, {}).pop(kind, None)
    return mid


def start_chat(conn, slug, company_name, user_name, user_email, topic, category, first_message):
    cfg = settings(conn)
    text = (first_message or '').strip()[:4000]
    if not text:
        raise SupportError('Mesajınızı yazın')
    if conn.execute("SELECT COUNT(*) FROM support_chats WHERE slug = ? AND status IN ('waiting','active')", (slug,)).fetchone()[0] >= 5:
        raise SupportError('Firmanızın açık canlı destek sohbetleri var; lütfen onlardan devam edin')
    cat = category if category in CATEGORIES else 'teknik'
    if not online(conn):   # kimse çevrimiçi değil → doğrudan talep (mesaj bırak)
        r = create_ticket(conn, slug, company_name, (topic or text[:80]).strip() or 'Canlı destek mesajı', text, cat, 'normal', user_name, user_email, 'chat')
        return {'offline': True, 'ticket': r}
    now = db.now()
    cur = conn.execute('''INSERT INTO support_chats (slug, company_name, user_name, user_email, topic, category, status, created_at, last_msg_at)
                          VALUES (?,?,?,?,?,?,'waiting',?,?)''', (slug, company_name, user_name[:120], user_email[:160], (topic or '')[:160], cat, now, now))
    cid = cur.lastrowid
    conn.execute('UPDATE support_chats SET code = ? WHERE id = ?', (f'C-{cid:04d}', cid))
    chat_msg(conn, cid, 'company', user_name or company_name, text)
    assignee = pick(conn, cat, 'chat') if cfg['auto_assign'] else None
    if assignee:
        _accept(conn, cid, assignee)
    conn.commit()
    push.send({assignee} if assignee else {s['id'] for s in online(conn)} or notify_ids(conn),
              {'type': 'chat', 'title': f'Canlı destek · {company_name or slug}', 'body': (topic or text)[:120],
               'url': f'/app#/tickets/live/{cid}', 'tag': f'chat-{cid}'})
    return {'id': cid, 'code': f'C-{cid:04d}'}


def _accept(conn, cid, uid):
    u = db.row(conn.execute('SELECT full_name FROM users WHERE id = ?', (uid,)))
    now = db.now()
    conn.execute("UPDATE support_chats SET status = 'active', assignee_id = ?, accepted_at = COALESCE(accepted_at, ?) WHERE id = ?", (uid, now, cid))
    welcome = settings(conn)['welcome']
    chat_msg(conn, cid, 'system', 'Sistem', f'{u["full_name"] if u else "Destek"} sohbete katıldı.')
    if welcome:
        chat_msg(conn, cid, 'support', u['full_name'] if u else 'Destek', welcome)


def accept_chat(conn, cid, user):
    c = db.row(conn.execute('SELECT * FROM support_chats WHERE id = ?', (cid,)))
    if not c:
        raise SupportError('Sohbet bulunamadı')
    if c['status'] != 'waiting':
        raise SupportError('Bu sohbet başka bir kişi tarafından alındı ya da sona erdi')
    _accept(conn, cid, user['id'])
    conn.commit()


def transfer_chat(conn, cid, user, to_id):
    c = db.row(conn.execute('SELECT * FROM support_chats WHERE id = ?', (cid,)))
    if not c or c['status'] != 'active':
        raise SupportError('Yalnız aktif sohbet aktarılabilir')
    to = db.row(conn.execute('SELECT id, full_name FROM users WHERE id = ? AND active = 1', (to_id,)))
    if not to or to['id'] not in team_ids(conn) | notify_ids(conn):
        raise SupportError('Aktarılacak kişi destek ekibinde değil')
    conn.execute('UPDATE support_chats SET assignee_id = ? WHERE id = ?', (to['id'], cid))
    chat_msg(conn, cid, 'system', 'Sistem', f'Sohbet {user["full_name"]} tarafından {to["full_name"]} kişisine aktarıldı.')
    conn.commit()
    push.send({to['id']}, {'type': 'chat', 'title': f'Size aktarılan sohbet · {c["company_name"]}', 'body': c['topic'] or '',
                           'url': f'/app#/tickets/live/{cid}', 'tag': f'chat-{cid}'})


def end_chat(conn, cid, by, name):
    c = db.row(conn.execute('SELECT * FROM support_chats WHERE id = ?', (cid,)))
    if not c or c['status'] in ('ended', 'missed'):
        return c
    now = db.now()
    conn.execute("UPDATE support_chats SET status = 'ended', ended_at = ?, ended_by = ? WHERE id = ?", (now, by, cid))
    chat_msg(conn, cid, 'system', 'Sistem', f'Sohbet {name} tarafından sonlandırıldı.')
    conn.commit()
    return c


def chat_to_ticket(conn, cid, subject=None, priority='normal', by_user=None):
    """Sohbeti (yazışmasıyla) destek talebine dönüştürür; zaten dönüştürülmüşse mevcut talebi döner."""
    c = db.row(conn.execute('SELECT * FROM support_chats WHERE id = ?', (cid,)))
    if not c:
        raise SupportError('Sohbet bulunamadı')
    if c['ticket_id']:
        return c['ticket_id']
    msgs = db.rows(conn.execute("SELECT * FROM support_chat_messages WHERE chat_id = ? AND author_kind != 'system' ORDER BY id", (cid,)))
    transcript = '\n'.join(f'[{m["created_at"][11:16]}] {m["author_name"]}: {m["body"] or ""}' for m in msgs)
    r = create_ticket(conn, c['slug'], c['company_name'], subject or c['topic'] or f'Canlı destek {c["code"]}',
                      f'Canlı destek yazışması ({c["code"]}):\n\n{transcript}', c['category'] or 'teknik', priority,
                      c['user_name'], c['user_email'], 'chat', chat_id=cid)
    conn.execute('UPDATE support_chats SET ticket_id = ? WHERE id = ?', (r['id'], cid))
    if by_user:
        conn.execute('UPDATE tickets SET assignee_id = COALESCE(assignee_id, ?), first_response_at = COALESCE(first_response_at, ?) WHERE id = ?',
                     (by_user['id'], db.now() if c['accepted_at'] else None, r['id']))
    chat_msg(conn, cid, 'system', 'Sistem', f'Bu yazışma {r["code"]} numaralı destek talebi olarak kaydedildi; takibini Destek Taleplerim’den yapabilirsiniz.')
    conn.commit()
    return r['id']


def sweep(conn):
    """Kimsenin almadığı bekleyen sohbetler talebe dönüşür (kaçırılan sohbet)."""
    cfg = settings(conn)
    limit = (datetime.now() - timedelta(minutes=cfg['chat_wait_minutes'])).isoformat(timespec='seconds')
    for (cid,) in conn.execute("SELECT id FROM support_chats WHERE status = 'waiting' AND created_at < ?", (limit,)).fetchall():
        conn.execute("UPDATE support_chats SET status = 'missed', ended_at = ?, ended_by = 'system' WHERE id = ?", (db.now(), cid))
        chat_to_ticket(conn, cid)


def chat_view(conn, cid, after=0, internal=True):
    c = db.row(conn.execute('''SELECT c.*, u.full_name AS assignee_name, s.title AS assignee_title FROM support_chats c
                               LEFT JOIN users u ON u.id = c.assignee_id LEFT JOIN support_staff s ON s.user_id = c.assignee_id WHERE c.id = ?''', (cid,)))
    if not c:
        return None
    msgs = db.rows(conn.execute('SELECT * FROM support_chat_messages WHERE chat_id = ? AND id > ? ORDER BY id', (cid, after)))
    fids = [m['file_id'] for m in msgs if m['file_id']]
    if fids:
        fmap = {f['id']: f for f in db.rows(conn.execute(f'SELECT id, token, name, mime, size FROM support_files WHERE id IN ({",".join("?" * len(fids))})', fids))}
        for m in msgs:
            if m['file_id'] in fmap:
                m['file'] = {k: fmap[m['file_id']][k] for k in ('token', 'name', 'mime', 'size')}
    if c['status'] == 'waiting':
        c['queue_position'] = conn.execute("SELECT COUNT(*) FROM support_chats WHERE status = 'waiting' AND id <= ?", (cid,)).fetchone()[0]
    c['messages'] = msgs
    if c['ticket_id']:
        c['ticket_code'] = (conn.execute('SELECT code FROM tickets WHERE id = ?', (c['ticket_id'],)).fetchone() or [None])[0]
    return c


# ---------------- pano ----------------
def overview(conn, uid):
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    since = (now - timedelta(days=30)).isoformat(timespec='seconds')
    tickets = db.rows(conn.execute("SELECT * FROM tickets WHERE status IN ('acik','yanit_bekliyor')"))
    overdue = [t for t in tickets if sla_state(t, now)['overdue']]
    fr = conn.execute('SELECT created_at, first_response_at FROM tickets WHERE first_response_at IS NOT NULL AND created_at >= ?', (since,)).fetchall()
    mins = [(datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60 for a, b in fr]
    res = conn.execute('SELECT created_at, resolved_at FROM tickets WHERE resolved_at IS NOT NULL AND created_at >= ?', (since,)).fetchall()
    rh = [(datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600 for a, b in res]
    rated = [r[0] for r in conn.execute('SELECT rating FROM tickets WHERE rating IS NOT NULL AND updated_at >= ? UNION ALL '
                                        'SELECT rating FROM support_chats WHERE rating IS NOT NULL AND created_at >= ?', (since, since))]
    met = sum(1 for t in db.rows(conn.execute('SELECT * FROM tickets WHERE created_at >= ? AND due_at IS NOT NULL', (since,)))
              if sla_state(t, now)['first'] in ('met', 'due'))
    total_sla = conn.execute('SELECT COUNT(*) FROM tickets WHERE created_at >= ? AND due_at IS NOT NULL', (since,)).fetchone()[0]
    days = [(now - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(13, -1, -1)]
    created = dict(conn.execute('SELECT substr(created_at,1,10), COUNT(*) FROM tickets WHERE created_at >= ? GROUP BY 1', (days[0],)).fetchall())
    resolved = dict(conn.execute('SELECT substr(resolved_at,1,10), COUNT(*) FROM tickets WHERE resolved_at >= ? GROUP BY 1', (days[0],)).fetchall())
    chats = dict(conn.execute('SELECT substr(created_at,1,10), COUNT(*) FROM support_chats WHERE created_at >= ? GROUP BY 1', (days[0],)).fetchall())
    top = db.rows(conn.execute('''SELECT slug, company_name, COUNT(*) AS n FROM tickets WHERE status IN ('acik','yanit_bekliyor')
                                  GROUP BY slug ORDER BY n DESC LIMIT 6'''))
    cats = db.rows(conn.execute('SELECT category, COUNT(*) AS n FROM tickets WHERE created_at >= ? GROUP BY category ORDER BY n DESC', (since,)))
    return {
        'waiting_chats': conn.execute("SELECT COUNT(*) FROM support_chats WHERE status = 'waiting'").fetchone()[0],
        'active_chats': conn.execute("SELECT COUNT(*) FROM support_chats WHERE status = 'active'").fetchone()[0],
        'my_chats': conn.execute("SELECT COUNT(*) FROM support_chats WHERE status = 'active' AND assignee_id = ?", (uid,)).fetchone()[0],
        'open': len(tickets), 'overdue': len(overdue),
        'unassigned': sum(1 for t in tickets if not t['assignee_id']),
        'mine': sum(1 for t in tickets if t['assignee_id'] == uid),
        'awaiting_support': sum(1 for t in tickets if t['status'] == 'acik'),
        'awaiting_company': sum(1 for t in tickets if t['status'] == 'yanit_bekliyor'),
        'new_today': conn.execute('SELECT COUNT(*) FROM tickets WHERE substr(created_at,1,10) = ?', (today,)).fetchone()[0],
        'resolved_today': conn.execute('SELECT COUNT(*) FROM tickets WHERE substr(resolved_at,1,10) = ?', (today,)).fetchone()[0],
        'avg_first_response_min': round(sum(mins) / len(mins)) if mins else None,
        'avg_resolve_hours': round(sum(rh) / len(rh), 1) if rh else None,
        'csat': round(sum(rated) / len(rated), 2) if rated else None, 'csat_count': len(rated),
        'sla_rate': round(met / total_sla * 100) if total_sla else None,
        'trend': [{'day': d, 'created': created.get(d, 0), 'resolved': resolved.get(d, 0), 'chats': chats.get(d, 0)} for d in days],
        'top_companies': top, 'categories': cats, 'staff': staff(conn),
    }
