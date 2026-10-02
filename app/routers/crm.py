"""Rehber, notlar ve takvim (Firma Yönetimi).

Rehber: firma kişileri ve sistem kullanıcıları tek listede. Kişi / kullanıcı / firma detayında evraklar,
notlar (konu hakkında birden çok not), toplantılar ve takvim (randevu ve hatırlatma) bulunur.
Konu (subject): company | person | user. Notlar ve takvim kayıtları Firma Yönetimi modülüne açık herkes içindir;
not ve kaydı yalnızca yazan (ya da Sistem Yöneticisi) düzenler / siler.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/crm')


def crm_user(user=Depends(auth.current_user)):
    """Firma notları / takvimi: Firma Yönetimi ve (tedarikçiler için) Satın Alma."""
    if not {'companies', 'purchasing'} & set(user['modules']):
        raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
    return user


SUBJECTS = {'company': ('companies', 'name'), 'person': ('company_people', 'full_name'), 'user': ('users', 'full_name')}
KINDS = ('RANDEVU', 'HATIRLATMA')


def _subject(conn, subject, sid):
    if subject not in SUBJECTS:
        raise HTTPException(400, 'Geçersiz konu')
    table, name = SUBJECTS[subject]
    extra = ' AND deleted_at IS NULL' if subject == 'user' else ''
    row = conn.execute(f'SELECT {name} FROM {table} WHERE id = ?{extra}', (sid,)).fetchone()
    if not row:
        raise HTTPException(404, 'Kayıt bulunamadı')
    return row[0]


def _event_access(user, subject, sid):
    """Takvime kayıt: Firma Yönetimi kullanıcıları her konuya; diğer herkes yalnızca kendi kişisel takvimine."""
    if 'companies' not in user['modules'] and not (subject == 'user' and sid == user['id']):
        raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')


def _can_edit(conn, user, owner_id):
    if owner_id != user['id'] and auth.ADMIN not in user['roles']:
        raise HTTPException(403, 'Yalnızca kaydı yazan kişi (ya da Sistem Yöneticisi) değiştirebilir')


# ---------- Rehber

@router.get('/contacts')
def contacts(supplier: bool = False, user=Depends(crm_user), conn=db.DB):
    """Rehber: firma kişileri + sistem kullanıcıları (aktif, silinmemiş). supplier=1: tedarikçi kişileri."""
    if ('purchasing' if supplier else 'companies') not in user['modules']:
        raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
    people = db.rows(conn.execute(
        '''SELECT p.*, c.name AS company_name, c.logo AS company_logo, c.active AS company_active
           FROM company_people p JOIN companies c ON c.id = p.company_id WHERE c.is_supplier = ? ORDER BY p.full_name''', (int(supplier),)))
    users = db.rows(conn.execute(
        '''SELECT id, username AS email, full_name, phone, photo FROM users
           WHERE deleted_at IS NULL AND active = 1 ORDER BY full_name'''))
    for u in users:
        u['roles'] = auth.user_roles(conn, u['id'])
    return {'people': people, 'users': users}


def _person_meetings(conn, where, args):
    rows = db.rows(conn.execute(
        f'''SELECT m.id, m.subject, m.meeting_at, m.location, m.notes, m.other_attendees, m.company_id, c.name AS company_name,
                   CASE WHEN a.id IS NOT NULL THEN a.label || ' — ' || TRIM(COALESCE(a.address, '') || ' ' || COALESCE(a.city, '')) END AS address
            FROM company_meetings m JOIN companies c ON c.id = m.company_id LEFT JOIN company_addresses a ON a.id = m.address_id
            WHERE {where} ORDER BY m.meeting_at DESC''', args))
    for m in rows:
        m['people'] = db.rows(conn.execute(
            '''SELECT p.id, p.full_name, p.title FROM meeting_people mp JOIN company_people p ON p.id = mp.person_id
               WHERE mp.meeting_id = ? ORDER BY p.full_name''', (m['id'],)))
        m['users'] = db.rows(conn.execute(
            '''SELECT u.id, u.full_name FROM meeting_users mu JOIN users u ON u.id = mu.user_id
               WHERE mu.meeting_id = ? ORDER BY u.full_name''', (m['id'],)))
    return rows


@router.get('/person/{pid}')
def person_detail(pid: int, user=Depends(crm_user), conn=db.DB):
    p = db.row(conn.execute(
        '''SELECT p.*, c.name AS company_name, c.logo AS company_logo FROM company_people p
           JOIN companies c ON c.id = p.company_id WHERE p.id = ?''', (pid,)))
    if not p:
        raise HTTPException(404, 'Kişi bulunamadı')
    from .documents import list_for_person
    p['documents'] = list_for_person(conn, user, pid)
    p['meetings'] = _person_meetings(conn, 'm.id IN (SELECT meeting_id FROM meeting_people WHERE person_id = ?)', (pid,))
    return p


@router.get('/user/{uid}')
def user_detail(uid: int, user=Depends(crm_user), conn=db.DB):
    u = db.row(conn.execute(
        'SELECT id, username AS email, full_name, phone, photo, active FROM users WHERE id = ? AND deleted_at IS NULL', (uid,)))
    if not u:
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    u['roles'] = auth.user_roles(conn, uid)
    from .documents import list_for_user
    u['documents'] = list_for_user(conn, user, uid)
    u['meetings'] = _person_meetings(conn, 'm.id IN (SELECT meeting_id FROM meeting_users WHERE user_id = ?)', (uid,))
    return u


# ---------- Notlar

class NoteIn(BaseModel):
    subject: str = ''
    subject_id: int = 0
    body: str


def _notes(conn, subject, sid):
    return db.rows(conn.execute(
        '''SELECT n.*, u.full_name AS created_by_name FROM crm_notes n LEFT JOIN users u ON u.id = n.created_by
           WHERE n.subject_type = ? AND n.subject_id = ? ORDER BY n.created_at DESC, n.id DESC''', (subject, sid)))


@router.get('/notes')
def list_notes(subject: str, subject_id: int, user=Depends(crm_user), conn=db.DB):
    _subject(conn, subject, subject_id)
    return _notes(conn, subject, subject_id)


@router.post('/notes')
def add_note(body: NoteIn, user=Depends(crm_user), conn=db.DB):
    name = _subject(conn, body.subject, body.subject_id)
    text = body.body.strip()
    if not text:
        raise HTTPException(400, 'Not boş olamaz')
    cur = conn.execute('INSERT INTO crm_notes (subject_type, subject_id, body, created_by, created_at) VALUES (?,?,?,?,?)',
                       (body.subject, body.subject_id, text, user['id'], db.now()))
    db.audit(conn, user['id'], 'Not ekledi', body.subject, body.subject_id, name)
    return {'id': cur.lastrowid}


def _note(conn, nid):
    n = db.row(conn.execute('SELECT * FROM crm_notes WHERE id = ?', (nid,)))
    if not n:
        raise HTTPException(404, 'Not bulunamadı')
    return n


@router.put('/notes/{nid}')
def update_note(nid: int, body: NoteIn, user=Depends(crm_user), conn=db.DB):
    n = _note(conn, nid)
    _can_edit(conn, user, n['created_by'])
    text = body.body.strip()
    if not text:
        raise HTTPException(400, 'Not boş olamaz')
    conn.execute('UPDATE crm_notes SET body = ?, updated_at = ? WHERE id = ?', (text, db.now(), nid))
    return {'ok': True}


@router.delete('/notes/{nid}')
def delete_note(nid: int, user=Depends(crm_user), conn=db.DB):
    n = _note(conn, nid)
    _can_edit(conn, user, n['created_by'])
    conn.execute('DELETE FROM crm_notes WHERE id = ?', (nid,))
    db.audit(conn, user['id'], 'Not sildi', n['subject_type'], n['subject_id'])
    return {'ok': True}


# ---------- Takvim

class EventIn(BaseModel):
    subject: str = ''
    subject_id: int = 0
    kind: str = 'RANDEVU'
    title: str
    starts_at: str
    ends_at: Optional[str] = None
    location: Optional[str] = None
    note: Optional[str] = None
    user_ids: list[int] = []


def _event_rows(conn, where, args, limit=500):
    rows = db.rows(conn.execute(
        f'''SELECT e.*, u.full_name AS created_by_name FROM crm_events e LEFT JOIN users u ON u.id = e.created_by
            WHERE {where} ORDER BY e.starts_at, e.id LIMIT {int(limit)}''', args))
    for e in rows:
        e['users'] = db.rows(conn.execute(
            '''SELECT u.id, u.full_name FROM crm_event_users eu JOIN users u ON u.id = eu.user_id
               WHERE eu.event_id = ? ORDER BY u.full_name''', (e['id'],)))
    return rows


def _meeting_events(conn, subject, sid, start, end):
    """Toplantılar takvimde salt okunur görünür (firmanın toplantıları / kişinin ya da kullanıcının katıldıkları);
    detayda görüşme notu, görüşülen kişiler (karşı taraf), bizden katılanlar ve diğer katılımcılar gösterilir."""
    where = {'company': 'm.company_id = ?',
             'person': 'm.id IN (SELECT meeting_id FROM meeting_people WHERE person_id = ?)',
             'user': 'm.id IN (SELECT meeting_id FROM meeting_users WHERE user_id = ?)'}[subject]
    return [{'id': f'm{m["id"]}', 'kind': 'TOPLANTI', 'title': m['subject'], 'starts_at': m['meeting_at'],
             'location': m['location'], 'address': m['address'], 'company_id': m['company_id'], 'company_name': m['company_name'],
             'note': m['notes'], 'people': m['people'], 'users': m['users'], 'other_attendees': m['other_attendees'],
             'readonly': True}
            for m in _person_meetings(conn, f'{where} AND m.meeting_at >= ? AND m.meeting_at < ?', (sid, start, end))]


@router.get('/events')
def list_events(subject: str, subject_id: int, start: str, end: str, user=Depends(crm_user), conn=db.DB):
    """Takvim ayı: konu kayıtları (randevu / hatırlatma) + toplantılar. start/end: YYYY-MM-DD."""
    _subject(conn, subject, subject_id)
    events = _event_rows(conn, 'e.subject_type = ? AND e.subject_id = ? AND e.starts_at >= ? AND e.starts_at < ?',
                         (subject, subject_id, start, end))
    return events + _meeting_events(conn, subject, subject_id, start, end)


@router.get('/events/upcoming')
def upcoming(subject: str, subject_id: int, user=Depends(crm_user), conn=db.DB):
    """Yaklaşan ve tamamlanmamış geçmiş hatırlatmalar (takvimin altındaki liste)."""
    _subject(conn, subject, subject_id)
    now = db.now()
    return _event_rows(conn, '''e.subject_type = ? AND e.subject_id = ? AND
                                (e.starts_at >= ? OR (e.kind = 'HATIRLATMA' AND e.done_at IS NULL))''',
                       (subject, subject_id, now[:10]), limit=30)


def _save_event(conn, body, user_id, eid=None):
    name = _subject(conn, body.subject, body.subject_id)
    if body.kind not in KINDS:
        raise HTTPException(400, 'Tür randevu ya da hatırlatma olmalı')
    title = body.title.strip()
    if not title:
        raise HTTPException(400, 'Başlık zorunlu')
    start = db.pick_time(body.starts_at, None, 'Başlangıç')
    end = None
    if body.kind == 'RANDEVU' and body.ends_at:
        end = db.pick_time(body.ends_at, start, 'Bitiş', 'başlangıç')
    users = sorted(set(body.user_ids))
    for uid in users:
        if not conn.execute('SELECT 1 FROM users WHERE id = ? AND deleted_at IS NULL', (uid,)).fetchone():
            raise HTTPException(400, 'Katılımcı kullanıcı bulunamadı')
    vals = (body.subject, body.subject_id, body.kind, title, start, end, (body.location or '').strip() or None,
            (body.note or '').strip() or None)
    if eid:
        conn.execute('''UPDATE crm_events SET subject_type = ?, subject_id = ?, kind = ?, title = ?, starts_at = ?, ends_at = ?,
                        location = ?, note = ? WHERE id = ?''', (*vals, eid))
        conn.execute('DELETE FROM crm_event_users WHERE event_id = ?', (eid,))
    else:
        eid = conn.execute('''INSERT INTO crm_events (subject_type, subject_id, kind, title, starts_at, ends_at, location, note,
                              created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''', (*vals, user_id, db.now())).lastrowid
    conn.executemany('INSERT INTO crm_event_users (event_id, user_id) VALUES (?,?)', [(eid, u) for u in users])
    return eid, name


@router.post('/events')
def add_event(body: EventIn, user=Depends(auth.current_user), conn=db.DB):
    _event_access(user, body.subject, body.subject_id)
    eid, name = _save_event(conn, body, user['id'])
    db.audit(conn, user['id'], 'Takvime kayıt ekledi', body.subject, body.subject_id, f'{name}: {body.title.strip()}')
    return {'id': eid}


def _event(conn, eid):
    e = db.row(conn.execute('SELECT * FROM crm_events WHERE id = ?', (eid,)))
    if not e:
        raise HTTPException(404, 'Takvim kaydı bulunamadı')
    return e


@router.put('/events/{eid}')
def update_event(eid: int, body: EventIn, user=Depends(auth.current_user), conn=db.DB):
    e = _event(conn, eid)
    _can_edit(conn, user, e['created_by'])
    body.subject, body.subject_id = e['subject_type'], e['subject_id']   # konu değişmez
    _save_event(conn, body, user['id'], eid)
    return {'ok': True}


@router.post('/events/{eid}/done')
def toggle_done(eid: int, user=Depends(auth.current_user), conn=db.DB):
    """Hatırlatmayı tamamlandı / tamamlanmadı yapar (oluşturan, katılımcı ya da yönetici)."""
    e = _event(conn, eid)
    mine = e['created_by'] == user['id'] or conn.execute(
        'SELECT 1 FROM crm_event_users WHERE event_id = ? AND user_id = ?', (eid, user['id'])).fetchone()
    if not mine and auth.ADMIN not in user['roles']:
        raise HTTPException(403, 'Bu kaydın katılımcısı değilsiniz')
    conn.execute('UPDATE crm_events SET done_at = ? WHERE id = ?', (None if e['done_at'] else db.now(), eid))
    return {'done': not e['done_at']}


@router.delete('/events/{eid}')
def delete_event(eid: int, user=Depends(auth.current_user), conn=db.DB):
    e = _event(conn, eid)
    _can_edit(conn, user, e['created_by'])
    conn.execute('DELETE FROM crm_events WHERE id = ?', (eid,))
    db.audit(conn, user['id'], 'Takvim kaydını sildi', e['subject_type'], e['subject_id'], e['title'])
    return {'ok': True}


def subject_href(subject, sid):
    return {'company': f'#/companies/{sid}/calendar', 'person': f'#/companies/rehber/person/{sid}/calendar',
            'user': f'#/companies/rehber/user/{sid}/calendar'}[subject]


def due_for(conn, user_id):
    """Bildirim: bugünkü randevular ve zamanı gelmiş, tamamlanmamış hatırlatmalar (oluşturan ya da katılımcı)."""
    now = datetime.now()
    today_end = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat(timespec='seconds')
    rows = _event_rows(conn, '''(e.created_by = ? OR e.id IN (SELECT event_id FROM crm_event_users WHERE user_id = ?)) AND
        ((e.kind = 'HATIRLATMA' AND e.done_at IS NULL AND e.starts_at <= ?) OR
         (e.kind = 'RANDEVU' AND e.starts_at >= ? AND e.starts_at < ?))''',
                       (user_id, user_id, now.isoformat(timespec='seconds'), now.isoformat(timespec='seconds'), today_end))
    for r in rows:
        r['subject_name'] = _subject(conn, r['subject_type'], r['subject_id']) if r['subject_type'] in SUBJECTS else ''
        r['href'] = '#/calendar'   # kişisel takvim: kullanıcının tüm randevu ve hatırlatmaları
    return rows


# ---------- Kişisel takvim (kullanıcı menüsü → Takvim): herkes, yalnızca kendi kayıtları

def _mine(user_id):
    return ('''(e.created_by = ? OR e.id IN (SELECT event_id FROM crm_event_users WHERE user_id = ?)
               OR (e.subject_type = 'user' AND e.subject_id = ?))''', (user_id, user_id, user_id))


def _label(conn, rows, user):
    """Kişisel takvimde kaydın konusu (firma / kişi / kullanıcı) ve bağlantısı (Firma Yönetimi erişimi varsa)."""
    crm = 'companies' in user['modules']
    for r in rows:
        own = r.get('subject_type') == 'user' and r.get('subject_id') == user['id']
        if r.get('subject_type') in SUBJECTS and not own:
            try:
                r['subject_name'] = _subject(conn, r['subject_type'], r['subject_id'])
            except HTTPException:
                r['subject_name'] = None
            r['subject_href'] = subject_href(r['subject_type'], r['subject_id']) if crm else None
    return rows


@router.get('/my/events')
def my_events(start: str, end: str, user=Depends(auth.current_user), conn=db.DB):
    where, args = _mine(user['id'])
    rows = _label(conn, _event_rows(conn, f'{where} AND e.starts_at >= ? AND e.starts_at < ?', (*args, start, end)), user)
    from .meetings import calendar_items   # şirket içi toplantılar (Kişisel → Toplantılar)
    return rows + _meeting_events(conn, 'user', user['id'], start, end) + calendar_items(conn, user['id'], start, end)


@router.get('/my/upcoming')
def my_upcoming(user=Depends(auth.current_user), conn=db.DB):
    where, args = _mine(user['id'])
    return _label(conn, _event_rows(conn, f'''{where} AND (e.starts_at >= ? OR (e.kind = 'HATIRLATMA' AND e.done_at IS NULL))''',
                                     (*args, db.now()[:10]), limit=30), user)
