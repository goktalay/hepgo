"""Sekreterya → Aramalar: şirkete dışarıdan gelen telefonlar not edilir ve ilgili kullanıcıya bağlanır.

Sonuç: BAGLANDI (kullanıcıya aktarıldı), ULASILAMADI (kullanıcıya ulaşılamadı), MESAJ (mesaj bırakıldı).
Bağlanan ve geri dönüş istemeyen aramalar kendiliğinden tamamlanmış sayılır; diğerleri kullanıcı "Tamamlandı" diyene kadar
Aramalarım'da bekler ve bildirim düşer (notifications: call-waiting). Notlar: sekreterya ve ilgili kullanıcı ekleyebilir.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/secretariat/calls')
me_router = APIRouter(prefix='/api/me/calls')
any_router = APIRouter(prefix='/api/calls')   # ayrıntı ve notlar: sekreterya ya da aramanın ilgili kişisi
sec_user = auth.require_module('secretariat')
RESULTS = {'BAGLANDI', 'ULASILAMADI', 'MESAJ'}

SELECT = '''SELECT k.*, t.full_name AS target_name, t.photo AS target_photo, c.full_name AS created_by_name, d.full_name AS done_by_name,
       p.full_name AS person_name, co.name AS company_name, co.logo AS company_logo,
       (SELECT COUNT(*) FROM phone_call_notes n WHERE n.call_id = k.id) AS note_count
FROM phone_calls k LEFT JOIN users t ON t.id = k.target_id LEFT JOIN users c ON c.id = k.created_by LEFT JOIN users d ON d.id = k.done_by
LEFT JOIN company_people p ON p.id = k.person_id LEFT JOIN companies co ON co.id = p.company_id'''


class CallIn(BaseModel):
    caller_name: str
    caller_phone: Optional[str] = None
    caller_company: Optional[str] = None
    person_id: Optional[int] = None
    subject: Optional[str] = None
    note: Optional[str] = None
    result: str = 'MESAJ'
    callback: bool = False
    target_id: Optional[int] = None


class NoteIn(BaseModel):
    body: str


class DoneIn(BaseModel):
    done: bool = True


def _clean(body: CallIn, conn):
    name = (body.caller_name or '').strip()
    if not name:
        raise HTTPException(400, 'Arayan kişinin adını yazın')
    if body.result not in RESULTS:
        raise HTTPException(400, 'Geçersiz arama sonucu')
    if body.target_id and not conn.execute('SELECT 1 FROM users WHERE id = ? AND active = 1', (body.target_id,)).fetchone():
        raise HTTPException(400, 'İlgili kişi bulunamadı')
    if body.person_id and not conn.execute('SELECT 1 FROM company_people WHERE id = ?', (body.person_id,)).fetchone():
        body.person_id = None
    strip = lambda v: (v or '').strip() or None
    return (name[:120], strip(body.caller_phone), strip(body.caller_company), body.person_id, strip(body.subject), strip(body.note),
            body.result, int(body.callback), body.target_id)


def _get(conn, cid):
    k = db.row(conn.execute(SELECT + ' WHERE k.id = ?', (cid,)))
    if not k:
        raise HTTPException(404, 'Arama bulunamadı')
    return k


def _allowed(user, k):
    if 'secretariat' not in user['modules'] and k['target_id'] != user['id']:
        raise HTTPException(404, 'Arama bulunamadı')


@router.get('')
def calls(user=Depends(sec_user), conn=db.DB):
    return db.rows(conn.execute(SELECT + ' ORDER BY k.created_at DESC LIMIT 1000'))


@router.get('/callers')
def callers(user=Depends(sec_user), conn=db.DB):
    """Daha önce arayanlar (ad, telefon, firma) — yeni kayıtta hızlı seçim için."""
    return db.rows(conn.execute(
        '''SELECT caller_name, caller_phone, caller_company, person_id, MAX(created_at) AS last_at, COUNT(*) AS n FROM phone_calls
           GROUP BY caller_name, IFNULL(caller_phone, '') ORDER BY last_at DESC LIMIT 500'''))


@router.post('')
def add(body: CallIn, user=Depends(sec_user), conn=db.DB):
    vals = _clean(body, conn)
    auto_done = body.result == 'BAGLANDI' and not body.callback   # konuştu, geri dönüş gerekmiyor
    now = db.now()
    cur = conn.execute('''INSERT INTO phone_calls (caller_name, caller_phone, caller_company, person_id, subject, note, result, callback,
                          target_id, created_by, created_at, done_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (*vals, user['id'], now, now if auto_done or not body.target_id else None))
    db.audit(conn, user['id'], 'Arama kaydetti', 'phone_call', cur.lastrowid, vals[0])
    return _get(conn, cur.lastrowid)


@router.put('/{cid}')
def edit(cid: int, body: CallIn, user=Depends(sec_user), conn=db.DB):
    k = _get(conn, cid)
    vals = _clean(body, conn)
    conn.execute('''UPDATE phone_calls SET caller_name = ?, caller_phone = ?, caller_company = ?, person_id = ?, subject = ?, note = ?,
                    result = ?, callback = ?, target_id = ? WHERE id = ?''', (*vals, cid))
    if body.target_id != k['target_id']:   # başka kişiye yönlendirildi: yeniden bekler
        conn.execute('UPDATE phone_calls SET seen_at = NULL, done_at = ?, done_by = NULL WHERE id = ?',
                     (None if body.target_id else db.now(), cid))
    db.audit(conn, user['id'], 'Aramayı düzenledi', 'phone_call', cid, vals[0])
    return _get(conn, cid)


@router.delete('/{cid}')
def delete(cid: int, user=Depends(sec_user), conn=db.DB):
    k = _get(conn, cid)
    conn.execute('DELETE FROM phone_calls WHERE id = ?', (cid,))
    db.audit(conn, user['id'], 'Aramayı sildi', 'phone_call', cid, k['caller_name'])
    return {'ok': True}


@any_router.get('/{cid}')
def detail(cid: int, user=Depends(auth.current_user), conn=db.DB):
    k = _get(conn, cid)
    _allowed(user, k)
    if k['target_id'] == user['id'] and not k['seen_at']:
        k['seen_at'] = db.now()
        conn.execute('UPDATE phone_calls SET seen_at = ? WHERE id = ?', (k['seen_at'], cid))
    k['notes'] = db.rows(conn.execute('''SELECT n.id, n.body, n.at, n.user_id, u.full_name, u.photo FROM phone_call_notes n
                                         LEFT JOIN users u ON u.id = n.user_id WHERE n.call_id = ? ORDER BY n.at''', (cid,)))
    k['can_edit'] = 'secretariat' in user['modules']
    return k


@any_router.post('/{cid}/notes')
def add_note(cid: int, body: NoteIn, user=Depends(auth.current_user), conn=db.DB):
    k = _get(conn, cid)
    _allowed(user, k)
    text = (body.body or '').strip()
    if not text:
        raise HTTPException(400, 'Not boş olamaz')
    conn.execute('INSERT INTO phone_call_notes (call_id, user_id, body, at) VALUES (?,?,?,?)', (cid, user['id'], text[:4000], db.now()))
    db.audit(conn, user['id'], 'Aramaya not ekledi', 'phone_call', cid, None)
    return detail(cid, user, conn)


@any_router.post('/{cid}/done')
def set_done(cid: int, body: DoneIn, user=Depends(auth.current_user), conn=db.DB):
    k = _get(conn, cid)
    _allowed(user, k)
    if body.done:
        conn.execute('UPDATE phone_calls SET done_at = ?, done_by = ?, seen_at = IFNULL(seen_at, ?) WHERE id = ?',
                     (db.now(), user['id'], db.now(), cid))
    else:
        conn.execute('UPDATE phone_calls SET done_at = NULL, done_by = NULL WHERE id = ?', (cid,))
    db.audit(conn, user['id'], 'Aramayı tamamladı' if body.done else 'Aramayı yeniden açtı', 'phone_call', cid, k['caller_name'])
    return detail(cid, user, conn)


@me_router.get('')
def my_calls(user=Depends(auth.current_user), conn=db.DB):
    return db.rows(conn.execute(SELECT + ' WHERE k.target_id = ? ORDER BY k.done_at IS NOT NULL, k.created_at DESC LIMIT 500', (user['id'],)))
