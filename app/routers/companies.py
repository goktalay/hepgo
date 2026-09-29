"""Firma Yönetimi: firmalar, logoları ve firmada çalışan / ilişkili kişiler. Firmanın evrakları Evrak Yönetimi'nden
(görünürlük kurallarıyla) gelir."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, db
from ..document_ocr import fold
from ..files import save_upload

router = APIRouter(prefix='/api/companies')
company_user = auth.require_module('companies')


def company_reader(user=Depends(auth.current_user)):
    """Firma ve kişi listeleri Evrak Yönetimi'nde evrak ilişkilendirmek için de okunur."""
    if not {'companies', 'documents'} & set(user['modules']):
        raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
    return user


class CompanyIn(BaseModel):
    name: str
    tax_office: Optional[str] = None
    tax_no: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None
    active: bool = True


class AddressIn(BaseModel):
    label: str
    address: str
    city: Optional[str] = None
    note: Optional[str] = None


class MeetingIn(BaseModel):
    subject: str
    meeting_at: str
    address_id: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    other_attendees: Optional[str] = None
    person_ids: list[int] = []
    user_ids: list[int] = []


class PersonIn(BaseModel):
    full_name: str
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    note: Optional[str] = None


def _clean(v):
    return (v or '').strip() or None


def _duplicate(conn, name, exclude=None):
    """Aynı ad (Türkçe harf ve büyük/küçük harf farkı yok sayılarak) başka firmada var mı?"""
    return any(fold(r[1]) == fold(name) for r in conn.execute('SELECT id, name FROM companies') if r[0] != exclude)


def _get(conn, cid):
    c = db.row(conn.execute('SELECT * FROM companies WHERE id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Firma bulunamadı')
    return c


@router.get('')
def list_companies(user=Depends(company_reader), conn=db.DB):
    rows = db.rows(conn.execute(
        '''SELECT c.*, (SELECT COUNT(*) FROM company_people p WHERE p.company_id = c.id) AS people_count,
                  (SELECT COUNT(*) FROM company_addresses a WHERE a.company_id = c.id) AS address_count,
                  (SELECT a.city FROM company_addresses a WHERE a.company_id = c.id ORDER BY a.id LIMIT 1) AS city
           FROM companies c ORDER BY c.active DESC, c.name'''))
    from .documents import visible_ids   # döngüsel içe aktarmayı önlemek için burada
    seen = visible_ids(conn, user)
    for c in rows:   # evrak sayısı yalnızca kullanıcının görebildiği evraklardan
        ids = {r[0] for r in conn.execute(
            '''SELECT document_id FROM document_companies WHERE company_id = ?
               UNION SELECT dp.document_id FROM document_people dp JOIN company_people p ON p.id = dp.person_id
               WHERE p.company_id = ?''', (c['id'], c['id']))}
        c['document_count'] = len(ids & seen)
    return rows


@router.get('/people')
def list_people(user=Depends(company_reader), conn=db.DB):
    """Tüm firmaların kişileri (Rehber görünümü ve evrak ilişkilendirme seçimi için)."""
    return db.rows(conn.execute(
        '''SELECT p.*, c.name AS company_name, c.logo AS company_logo, c.active AS company_active
           FROM company_people p JOIN companies c ON c.id = p.company_id
           ORDER BY c.name, p.full_name'''))


@router.post('')
def add_company(body: CompanyIn, user=Depends(company_user), conn=db.DB):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, 'Firma adı zorunlu')
    if _duplicate(conn, name):
        raise HTTPException(400, 'Bu firma zaten kayıtlı')
    cur = conn.execute(
        '''INSERT INTO companies (name, tax_office, tax_no, phone, email, website, note, active, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (name, _clean(body.tax_office), _clean(body.tax_no), _clean(body.phone), _clean(body.email), _clean(body.website),
         _clean(body.note), int(body.active), user['id'], db.now()))
    if _clean(body.address):   # yeni firmada girilen adres "Merkez" olarak kaydedilir
        conn.execute('INSERT INTO company_addresses (company_id, label, address, created_at) VALUES (?,?,?,?)',
                     (cur.lastrowid, 'Merkez', _clean(body.address), db.now()))
    db.audit(conn, user['id'], 'Firma ekledi', 'company', cur.lastrowid, name)
    return {'id': cur.lastrowid}


@router.get('/{cid}')
def get_company(cid: int, user=Depends(company_user), conn=db.DB):
    c = _get(conn, cid)
    c['people'] = db.rows(conn.execute('SELECT * FROM company_people WHERE company_id = ? ORDER BY full_name', (cid,)))
    c['addresses'] = db.rows(conn.execute('SELECT * FROM company_addresses WHERE company_id = ? ORDER BY id', (cid,)))
    from .documents import list_for_company
    c['documents'] = list_for_company(conn, user, cid)
    c['meetings'] = _meetings(conn, cid)
    return c


@router.put('/{cid}')
def update_company(cid: int, body: CompanyIn, user=Depends(company_user), conn=db.DB):
    _get(conn, cid)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, 'Firma adı zorunlu')
    if _duplicate(conn, name, cid):
        raise HTTPException(400, 'Bu firma adı başka bir kayıtta var')
    conn.execute('''UPDATE companies SET name = ?, tax_office = ?, tax_no = ?, phone = ?, email = ?, website = ?,
                    note = ?, active = ? WHERE id = ?''',
                 (name, _clean(body.tax_office), _clean(body.tax_no), _clean(body.phone), _clean(body.email),
                  _clean(body.website), _clean(body.note), int(body.active), cid))
    db.audit(conn, user['id'], 'Firma bilgilerini düzenledi', 'company', cid, name)
    return {'ok': True}


@router.delete('/{cid}')
def delete_company(cid: int, user=Depends(company_user), conn=db.DB):
    c = _get(conn, cid)
    linked = conn.execute(
        '''SELECT COUNT(*) FROM document_companies WHERE company_id = ?''', (cid,)).fetchone()[0] + conn.execute(
        '''SELECT COUNT(*) FROM document_people dp JOIN company_people p ON p.id = dp.person_id WHERE p.company_id = ?''',
        (cid,)).fetchone()[0]
    if linked:
        raise HTTPException(400, 'Firmaya bağlı evrak var; silmek yerine pasife alın')
    person_ids = [r[0] for r in conn.execute('SELECT id FROM company_people WHERE company_id = ?', (cid,))]
    _drop_crm(conn, 'company', [cid])
    _drop_crm(conn, 'person', person_ids)
    conn.execute('DELETE FROM companies WHERE id = ?', (cid,))
    db.audit(conn, user['id'], 'Firma sildi', 'company', cid, c['name'])
    return {'ok': True}


@router.post('/{cid}/logo')
async def upload_logo(cid: int, file: UploadFile, user=Depends(company_user), conn=db.DB):
    c = await run_in_threadpool(_get, conn, cid)
    path = await save_upload('logos', file)

    def write():
        conn.execute('UPDATE companies SET logo = ? WHERE id = ?', (path, cid))
        db.audit(conn, user['id'], 'Firma logosunu güncelledi', 'company', cid, c['name'])
    await run_in_threadpool(write)
    return {'logo': path}


# ---------- Kişiler

@router.post('/{cid}/people')
def add_person(cid: int, body: PersonIn, user=Depends(company_user), conn=db.DB):
    c = _get(conn, cid)
    if not body.full_name.strip():
        raise HTTPException(400, 'Ad soyad zorunlu')
    cur = conn.execute('''INSERT INTO company_people (company_id, full_name, title, phone, email, note, created_at)
                          VALUES (?,?,?,?,?,?,?)''',
                       (cid, body.full_name.strip(), _clean(body.title), _clean(body.phone), _clean(body.email),
                        _clean(body.note), db.now()))
    db.audit(conn, user['id'], 'Firmaya kişi ekledi', 'company', cid, f'{c["name"]}: {body.full_name.strip()}')
    return {'id': cur.lastrowid}


def _person(conn, pid):
    p = db.row(conn.execute('SELECT p.*, c.name AS company_name FROM company_people p JOIN companies c ON c.id = p.company_id '
                            'WHERE p.id = ?', (pid,)))
    if not p:
        raise HTTPException(404, 'Kişi bulunamadı')
    return p


@router.put('/people/{pid}')
def update_person(pid: int, body: PersonIn, user=Depends(company_user), conn=db.DB):
    p = _person(conn, pid)
    if not body.full_name.strip():
        raise HTTPException(400, 'Ad soyad zorunlu')
    conn.execute('UPDATE company_people SET full_name = ?, title = ?, phone = ?, email = ?, note = ? WHERE id = ?',
                 (body.full_name.strip(), _clean(body.title), _clean(body.phone), _clean(body.email), _clean(body.note), pid))
    db.audit(conn, user['id'], 'Firma kişisini düzenledi', 'company', p['company_id'], f'{p["company_name"]}: {body.full_name.strip()}')
    return {'ok': True}


@router.delete('/people/{pid}')
def delete_person(pid: int, user=Depends(company_user), conn=db.DB):
    p = _person(conn, pid)
    if conn.execute('SELECT 1 FROM document_people WHERE person_id = ?', (pid,)).fetchone():
        raise HTTPException(400, 'Bu kişiye bağlı evrak var; önce evraktaki ilişkiyi kaldırın')
    _drop_crm(conn, 'person', [pid])
    conn.execute('DELETE FROM company_people WHERE id = ?', (pid,))
    db.audit(conn, user['id'], 'Firma kişisini sildi', 'company', p['company_id'], f'{p["company_name"]}: {p["full_name"]}')
    return {'ok': True}


def _drop_crm(conn, subject, ids):
    """Silinen firma / kişinin notları ve takvim kayıtları da silinir."""
    for i in ids:
        conn.execute('DELETE FROM crm_notes WHERE subject_type = ? AND subject_id = ?', (subject, i))
        conn.execute('DELETE FROM crm_events WHERE subject_type = ? AND subject_id = ?', (subject, i))


# ---------- Toplantılar

def _meetings(conn, cid):
    rows = db.rows(conn.execute(
        """SELECT m.*, u.full_name AS created_by_name, a.label AS address_label, a.address AS address_text,
                  a.city AS address_city
           FROM company_meetings m LEFT JOIN users u ON u.id = m.created_by
           LEFT JOIN company_addresses a ON a.id = m.address_id
           WHERE m.company_id = ? ORDER BY m.meeting_at DESC, m.id DESC""", (cid,)))
    for m in rows:
        m['people'] = db.rows(conn.execute(
            """SELECT p.id, p.full_name, p.title FROM meeting_people mp JOIN company_people p ON p.id = mp.person_id
               WHERE mp.meeting_id = ? ORDER BY p.full_name""", (m['id'],)))
        m['users'] = db.rows(conn.execute(
            """SELECT u.id, u.full_name FROM meeting_users mu JOIN users u ON u.id = mu.user_id
               WHERE mu.meeting_id = ? ORDER BY u.full_name""", (m['id'],)))
    return rows


def _meeting(conn, mid):
    m = db.row(conn.execute('SELECT * FROM company_meetings WHERE id = ?', (mid,)))
    if not m:
        raise HTTPException(404, 'Toplantı bulunamadı')
    return m


def _save_meeting(conn, cid, body, user_id, mid=None):
    subject = body.subject.strip()
    if not subject:
        raise HTTPException(400, 'Toplantı konusu zorunlu')
    at = db.pick_time(body.meeting_at, None, 'Toplantı zamanı')   # ileri tarih (planlanan toplantı) serbest
    people = sorted(set(body.person_ids))
    for pid in people:
        if not conn.execute('SELECT 1 FROM company_people WHERE id = ? AND company_id = ?', (pid, cid)).fetchone():
            raise HTTPException(400, 'Karşı taraf katılımcısı bu firmanın kişisi değil')
    users = sorted(set(body.user_ids))
    for uid in users:
        if not conn.execute('SELECT 1 FROM users WHERE id = ? AND deleted_at IS NULL', (uid,)).fetchone():
            raise HTTPException(400, 'Katılımcı kullanıcı bulunamadı')
    if body.address_id and not conn.execute('SELECT 1 FROM company_addresses WHERE id = ? AND company_id = ?',
                                            (body.address_id, cid)).fetchone():
        raise HTTPException(400, 'Seçilen adres bu firmanın değil')
    values = (subject[:300], at, body.address_id or None, _clean(body.location), _clean(body.notes), _clean(body.other_attendees))
    if mid:
        conn.execute("""UPDATE company_meetings SET subject = ?, meeting_at = ?, address_id = ?, location = ?, notes = ?,
                        other_attendees = ?, updated_at = ? WHERE id = ?""", (*values, db.now(), mid))
    else:
        mid = conn.execute("""INSERT INTO company_meetings (subject, meeting_at, address_id, location, notes, other_attendees,
                              company_id, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                           (*values, cid, user_id, db.now())).lastrowid
    conn.execute('DELETE FROM meeting_people WHERE meeting_id = ?', (mid,))
    conn.execute('DELETE FROM meeting_users WHERE meeting_id = ?', (mid,))
    conn.executemany('INSERT INTO meeting_people (meeting_id, person_id) VALUES (?,?)', [(mid, p) for p in people])
    conn.executemany('INSERT INTO meeting_users (meeting_id, user_id) VALUES (?,?)', [(mid, u) for u in users])
    return mid


@router.post('/{cid}/meetings')
def add_meeting(cid: int, body: MeetingIn, user=Depends(company_user), conn=db.DB):
    c = _get(conn, cid)
    mid = _save_meeting(conn, cid, body, user['id'])
    db.audit(conn, user['id'], 'Firma toplantısı ekledi', 'company', cid, f'{c["name"]}: {body.subject.strip()}')
    return {'id': mid}


@router.put('/meetings/{mid}')
def update_meeting(mid: int, body: MeetingIn, user=Depends(company_user), conn=db.DB):
    m = _meeting(conn, mid)
    _save_meeting(conn, m['company_id'], body, user['id'], mid)
    db.audit(conn, user['id'], 'Firma toplantısını düzenledi', 'company', m['company_id'], body.subject.strip())
    return {'ok': True}


@router.delete('/meetings/{mid}')
def delete_meeting(mid: int, user=Depends(company_user), conn=db.DB):
    m = _meeting(conn, mid)
    conn.execute('DELETE FROM company_meetings WHERE id = ?', (mid,))
    db.audit(conn, user['id'], 'Firma toplantısını sildi', 'company', m['company_id'], m['subject'])
    return {'ok': True}


# ---------- Adresler

def _address(conn, aid):
    a = db.row(conn.execute('SELECT a.*, c.name AS company_name FROM company_addresses a JOIN companies c ON c.id = a.company_id '
                            'WHERE a.id = ?', (aid,)))
    if not a:
        raise HTTPException(404, 'Adres bulunamadı')
    return a


def _check_address(body):
    if not body.label.strip() or not body.address.strip():
        raise HTTPException(400, 'Adres adı ve açık adres zorunlu')


@router.post('/{cid}/addresses')
def add_address(cid: int, body: AddressIn, user=Depends(company_user), conn=db.DB):
    c = _get(conn, cid)
    _check_address(body)
    cur = conn.execute('INSERT INTO company_addresses (company_id, label, address, city, note, created_at) VALUES (?,?,?,?,?,?)',
                       (cid, body.label.strip()[:100], body.address.strip(), _clean(body.city), _clean(body.note), db.now()))
    db.audit(conn, user['id'], 'Firmaya adres ekledi', 'company', cid, f'{c["name"]}: {body.label.strip()}')
    return {'id': cur.lastrowid}


@router.put('/addresses/{aid}')
def update_address(aid: int, body: AddressIn, user=Depends(company_user), conn=db.DB):
    a = _address(conn, aid)
    _check_address(body)
    conn.execute('UPDATE company_addresses SET label = ?, address = ?, city = ?, note = ? WHERE id = ?',
                 (body.label.strip()[:100], body.address.strip(), _clean(body.city), _clean(body.note), aid))
    db.audit(conn, user['id'], 'Firma adresini düzenledi', 'company', a['company_id'], f'{a["company_name"]}: {body.label.strip()}')
    return {'ok': True}


@router.delete('/addresses/{aid}')
def delete_address(aid: int, user=Depends(company_user), conn=db.DB):
    a = _address(conn, aid)
    used = conn.execute('SELECT COUNT(*) FROM company_meetings WHERE address_id = ?', (aid,)).fetchone()[0]
    if used:
        raise HTTPException(400, f'Bu adres {used} toplantıda kullanılıyor; önce toplantılardaki adresi değiştirin')
    conn.execute('DELETE FROM company_addresses WHERE id = ?', (aid,))
    db.audit(conn, user['id'], 'Firma adresini sildi', 'company', a['company_id'], f'{a["company_name"]}: {a["label"]}')
    return {'ok': True}
