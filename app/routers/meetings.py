"""Kişisel → Toplantılar: şirket içi toplantı daveti.

Düzenleyen başlık, zaman, yer, talep notu ve hatırlatma süresiyle toplantı oluşturup kullanıcıları davet eder. Davet,
davetlinin bildirimine düşer (meeting-invite); davetli notuyla Katılıyorum / Belki / Katılmıyorum der. Toplantıdan
remind_min dakika önce katılan / yanıt vermemiş davetlilere ve düzenleyene hatırlatma bildirimi (meeting-soon) çıkar.
Toplantıyı yalnızca düzenleyen (ya da Sistem Yöneticisi) değiştirir / iptal eder; zaman değişirse yanıtlar sıfırlanır.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/meetings')
STATUSES = ('KATILIYOR', 'BELKI', 'KATILMIYOR')
REMIND = (0, 5, 10, 15, 30, 60, 120, 1440)


class MeetingIn(BaseModel):
    title: str
    starts_at: str
    ends_at: Optional[str] = None
    location: Optional[str] = None
    note: Optional[str] = None
    remind_min: int = 15
    user_ids: list[int] = []


class RespondIn(BaseModel):
    status: str
    response: Optional[str] = None


def _invites(conn, mid):
    return db.rows(conn.execute(
        '''SELECT i.user_id, i.status, i.response, i.responded_at, u.full_name, u.photo FROM team_meeting_invites i
           JOIN users u ON u.id = i.user_id WHERE i.meeting_id = ? ORDER BY u.full_name''', (mid,)))


def _decorate(conn, m, user):
    m['organizer'] = conn.execute('SELECT full_name FROM users WHERE id = ?', (m['created_by'],)).fetchone()[0]
    m['invites'] = _invites(conn, m['id'])
    mine = next((i for i in m['invites'] if i['user_id'] == user['id']), None)
    m['my_status'] = 'DUZENLEYEN' if m['created_by'] == user['id'] else (mine['status'] if mine else None)
    m['my_response'] = mine['response'] if mine else None
    m['counts'] = {s: sum(1 for i in m['invites'] if i['status'] == s) for s in ('BEKLIYOR', *STATUSES)}
    m['can_edit'] = m['created_by'] == user['id'] or auth.ADMIN in user['roles']
    return m


def _get(conn, mid, user):
    m = db.row(conn.execute('SELECT * FROM team_meetings WHERE id = ?', (mid,)))
    if not m:
        raise HTTPException(404, 'Toplantı bulunamadı')
    invited = conn.execute('SELECT 1 FROM team_meeting_invites WHERE meeting_id = ? AND user_id = ?', (mid, user['id'])).fetchone()
    if m['created_by'] != user['id'] and not invited and auth.ADMIN not in user['roles']:
        raise HTTPException(404, 'Toplantı bulunamadı')
    return _decorate(conn, m, user)


def _validate(conn, body, user):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, 'Toplantı konusu zorunlu')
    start = db.pick_time(body.starts_at, None, 'Başlangıç')
    end = db.pick_time(body.ends_at, start, 'Bitiş', 'başlangıç') if body.ends_at else None
    if body.remind_min not in REMIND:
        raise HTTPException(400, 'Geçersiz hatırlatma süresi')
    users = sorted({u for u in body.user_ids if u != user['id']})
    if not users:
        raise HTTPException(400, 'En az bir katılımcı davet edin')
    for uid in users:
        if not conn.execute('SELECT 1 FROM users WHERE id = ? AND active = 1 AND deleted_at IS NULL', (uid,)).fetchone():
            raise HTTPException(400, 'Davet edilen kullanıcı bulunamadı')
    return title[:200], start, end, (body.location or '').strip()[:200] or None, (body.note or '').strip()[:4000] or None, users


@router.get('')
def my_meetings(scope: str = 'upcoming', user=Depends(auth.current_user), conn=db.DB):
    """upcoming: bugün ve sonrası · past: geçmiş · all. Düzenlediğim ya da davet edildiğim toplantılar."""
    today = datetime.now().replace(hour=0, minute=0, second=0).isoformat(timespec='seconds')
    cond = {'upcoming': 'AND m.starts_at >= ?', 'past': 'AND m.starts_at < ?', 'all': 'AND ? IS NOT NULL'}.get(scope, 'AND m.starts_at >= ?')
    rows = db.rows(conn.execute(
        f'''SELECT m.* FROM team_meetings m WHERE (m.created_by = ? OR m.id IN (SELECT meeting_id FROM team_meeting_invites WHERE user_id = ?))
            {cond} ORDER BY m.starts_at {'DESC' if scope == 'past' else ''} LIMIT 300''', (user['id'], user['id'], today)))
    return [_decorate(conn, m, user) for m in rows]


@router.post('')
def create(body: MeetingIn, user=Depends(auth.current_user), conn=db.DB):
    title, start, end, loc, note, users = _validate(conn, body, user)
    if start < datetime.now().isoformat(timespec='seconds'):
        raise HTTPException(400, 'Toplantı zamanı geçmiş olamaz')
    now = db.now()
    mid = conn.execute('''INSERT INTO team_meetings (title, starts_at, ends_at, location, note, remind_min, created_by, created_at)
                          VALUES (?,?,?,?,?,?,?,?)''', (title, start, end, loc, note, body.remind_min, user['id'], now)).lastrowid
    conn.executemany('INSERT INTO team_meeting_invites (meeting_id, user_id, invited_at) VALUES (?,?,?)', [(mid, u, now) for u in users])
    db.audit(conn, user['id'], 'Toplantı oluşturdu', 'meeting', mid, f'{title} · {len(users)} davetli')
    try:
        from .. import feed
        feed.add_event(conn, 'MEETING', f'Toplantı planlandı: {title}', 'meeting', mid, f'#/meetings/{mid}')
    except Exception:   # noqa: BLE001
        pass
    return _get(conn, mid, user)


@router.get('/{mid}')
def detail(mid: int, user=Depends(auth.current_user), conn=db.DB):
    return _get(conn, mid, user)


@router.put('/{mid}')
def update(mid: int, body: MeetingIn, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    if not m['can_edit']:
        raise HTTPException(403, 'Toplantıyı yalnızca düzenleyen değiştirebilir')
    if m['cancelled_at']:
        raise HTTPException(400, 'İptal edilen toplantı değiştirilemez')
    title, start, end, loc, note, users = _validate(conn, body, user)
    users = [u for u in users if u != m['created_by']]
    conn.execute('''UPDATE team_meetings SET title = ?, starts_at = ?, ends_at = ?, location = ?, note = ?, remind_min = ?, updated_at = ?
                    WHERE id = ?''', (title, start, end, loc, note, body.remind_min, db.now(), mid))
    old = {i['user_id'] for i in m['invites']}
    conn.executemany('DELETE FROM team_meeting_invites WHERE meeting_id = ? AND user_id = ?', [(mid, u) for u in old - set(users)])
    conn.executemany('INSERT INTO team_meeting_invites (meeting_id, user_id, invited_at) VALUES (?,?,?)',
                     [(mid, u, db.now()) for u in set(users) - old])
    if start != m['starts_at']:   # zaman değişti: herkesin yeniden yanıt vermesi istenir
        conn.execute("UPDATE team_meeting_invites SET status = 'BEKLIYOR', responded_at = NULL WHERE meeting_id = ?", (mid,))
    db.audit(conn, user['id'], 'Toplantıyı değiştirdi', 'meeting', mid, title)
    return _get(conn, mid, user)


@router.post('/{mid}/cancel')
def cancel(mid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    if not m['can_edit']:
        raise HTTPException(403, 'Toplantıyı yalnızca düzenleyen iptal edebilir')
    conn.execute('UPDATE team_meetings SET cancelled_at = ? WHERE id = ?', (db.now(), mid))
    db.audit(conn, user['id'], 'Toplantıyı iptal etti', 'meeting', mid, m['title'])
    return _get(conn, mid, user)


@router.post('/{mid}/respond')
def respond(mid: int, body: RespondIn, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    if body.status not in STATUSES:
        raise HTTPException(400, 'Geçersiz yanıt')
    if m['cancelled_at']:
        raise HTTPException(400, 'Toplantı iptal edildi')
    cur = conn.execute('''UPDATE team_meeting_invites SET status = ?, response = ?, responded_at = ? WHERE meeting_id = ? AND user_id = ?''',
                       (body.status, (body.response or '').strip()[:1000] or None, db.now(), mid, user['id']))
    if not cur.rowcount:
        raise HTTPException(400, 'Bu toplantıya davetli değilsiniz')
    return _get(conn, mid, user)


# ---------- Bildirimler (app/notifications.py) ve takvim

def pending_invites(conn, user_id):
    """Yanıt bekleyen davetler (iptal edilmemiş, başlamamış)."""
    return db.rows(conn.execute(
        '''SELECT m.id, m.title, m.starts_at, u.full_name AS organizer FROM team_meeting_invites i JOIN team_meetings m ON m.id = i.meeting_id
           JOIN users u ON u.id = m.created_by
           WHERE i.user_id = ? AND i.status = 'BEKLIYOR' AND m.cancelled_at IS NULL AND m.starts_at > ? ORDER BY m.starts_at''',
        (user_id, db.now())))


def soon(conn, user_id):
    """Hatırlatma zamanı gelmiş, henüz başlamamış (ya da yeni başlamış) toplantılar: düzenleyen ve katılmayacağını söylemeyenler."""
    now = datetime.now()
    rows = db.rows(conn.execute(
        '''SELECT m.id, m.title, m.starts_at, m.location, m.remind_min FROM team_meetings m
           WHERE m.cancelled_at IS NULL AND m.ended_at IS NULL AND m.remind_min > 0 AND m.starts_at >= ? AND m.starts_at <= ?
             AND (m.created_by = ? OR m.id IN (SELECT meeting_id FROM team_meeting_invites WHERE user_id = ? AND status != 'KATILMIYOR'))
           ORDER BY m.starts_at''',
        ((now - timedelta(minutes=5)).isoformat(timespec='seconds'), (now + timedelta(days=1)).isoformat(timespec='seconds'),
         user_id, user_id)))
    return [r for r in rows if datetime.fromisoformat(r['starts_at']) - timedelta(minutes=r['remind_min']) <= now]


def calendar_items(conn, user_id, start, end):
    """Kişisel takvimde görünecek toplantılar (katılmayacağım dediklerim hariç)."""
    rows = db.rows(conn.execute(
        '''SELECT m.*, (SELECT status FROM team_meeting_invites WHERE meeting_id = m.id AND user_id = ?) AS my_status
           FROM team_meetings m WHERE m.starts_at >= ? AND m.starts_at < ? AND m.cancelled_at IS NULL
             AND (m.created_by = ? OR m.id IN (SELECT meeting_id FROM team_meeting_invites WHERE user_id = ? AND status != 'KATILMIYOR'))''',
        (user_id, start, end, user_id, user_id)))
    return [{'id': f't{m["id"]}', 'kind': 'TOPLANTI', 'title': m['title'] + (' (yanıt bekliyor)' if m['my_status'] == 'BEKLIYOR' else ''),
             'starts_at': m['starts_at'], 'ends_at': m['ends_at'], 'location': m['location'], 'users': [], 'readonly': True,
             'link': f'#/meetings/{m["id"]}'} for m in rows]
