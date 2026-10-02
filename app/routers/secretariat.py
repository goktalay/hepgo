"""Sekreterya: misafir kaydı (bir grup = bir kayıt; gelen kişiler, gelen araçlar, görüşülecek kişiler) ve kargolar.
Görüşülecek kişiye ve kargonun ilgili kişisine bildirim düşer (notifications: guest-visit, cargo-waiting).
Kargolarım (kullanıcı menüsü) herkese açıktır: kişi yalnızca kendi kargolarını görür ve teslim alır."""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, db
from ..files import FILE_GUARDS, save_upload
from .security import parked

router = APIRouter(prefix='/api/secretariat')
me_router = APIRouter(prefix='/api/me')   # kişiye özel: Kargolarım, Misafirlerim (modül gerekmez)
sec_user = auth.require_module('secretariat')


# ---------- Seçim listeleri (Firma modülü olmadan)

@router.get('/people')
def people(q: str = '', user=Depends(sec_user), conn=db.DB):
    """Firmalarda kayıtlı kişiler (gelen kişi araması)."""
    return db.rows(conn.execute(
        '''SELECT p.id, p.full_name, p.title, p.phone, p.company_id, c.name AS company_name, c.logo AS company_logo
           FROM company_people p JOIN companies c ON c.id = p.company_id ORDER BY p.full_name'''))


@router.get('/companies')
def companies(user=Depends(sec_user), conn=db.DB):
    return db.rows(conn.execute('SELECT id, name, logo FROM companies WHERE active = 1 ORDER BY name'))


@router.get('/parked')
def parked_vehicles(user=Depends(sec_user), conn=db.DB):
    """Güvenliğin kaydettiği, şu an parktaki araçlar (misafir kaydına bağlamak için)."""
    return parked(conn)


# ---------- Misafir kayıtları

class VisitIn(BaseModel):
    purpose: Optional[str] = None
    note: Optional[str] = None


class GuestIn(BaseModel):
    person_id: Optional[int] = None          # firmada kayıtlı kişi
    company_id: Optional[int] = None         # yeni kişi bu firmaya eklenir
    full_name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    company_text: Optional[str] = None       # serbest giriş: firma adı (sistemde yok)


class IdsIn(BaseModel):
    ids: list[int]


def _visit(conn, vid):
    v = db.row(conn.execute(
        '''SELECT g.*, u.full_name AS created_by_name FROM guest_visits g LEFT JOIN users u ON u.id = g.created_by
           WHERE g.id = ?''', (vid,)))
    if not v:
        raise HTTPException(404, 'Misafir kaydı bulunamadı')
    v['people'] = db.rows(conn.execute(
        '''SELECT gp.*, c.id AS company_id, c.name AS company_name, c.logo AS company_logo
           FROM guest_visit_people gp LEFT JOIN company_people p ON p.id = gp.person_id
           LEFT JOIN companies c ON c.id = p.company_id WHERE gp.visit_id = ? ORDER BY gp.id''', (vid,)))
    v['vehicles'] = db.rows(conn.execute(
        '''SELECT v.* FROM guest_visit_vehicles gv JOIN vehicle_visits v ON v.id = gv.vehicle_id
           WHERE gv.visit_id = ? ORDER BY v.entered_at''', (vid,)))
    v['hosts'] = db.rows(conn.execute(
        '''SELECT u.id, u.full_name, u.photo, h.added_at FROM guest_visit_hosts h JOIN users u ON u.id = h.user_id
           WHERE h.visit_id = ? ORDER BY u.full_name''', (vid,)))
    return v


def _summary(conn, where='1=1', args=()):
    rows = db.rows(conn.execute(
        f'''SELECT g.*, u.full_name AS created_by_name,
                   (SELECT COUNT(*) FROM guest_visit_people WHERE visit_id = g.id) AS people_count,
                   (SELECT group_concat(full_name, ', ') FROM guest_visit_people WHERE visit_id = g.id) AS people_names,
                   (SELECT group_concat(v.plate, ', ') FROM guest_visit_vehicles gv JOIN vehicle_visits v ON v.id = gv.vehicle_id
                    WHERE gv.visit_id = g.id) AS plates,
                   (SELECT group_concat(x.full_name, ', ') FROM guest_visit_hosts h JOIN users x ON x.id = h.user_id
                    WHERE h.visit_id = g.id) AS host_names
            FROM guest_visits g LEFT JOIN users u ON u.id = g.created_by WHERE {where} ORDER BY g.arrived_at DESC LIMIT 500''', args))
    return rows


@router.get('/visits')
def visits(scope: str = '', date_from: str = '', date_to: str = '', user=Depends(sec_user), conn=db.DB):
    """scope=inside: içerideki misafirler; scope=history: çıkış yapmışlar (tarih aralığıyla, geliş tarihine göre)."""
    if scope == 'inside':
        return _summary(conn, 'g.left_at IS NULL')
    if scope == 'history':
        dc, da = db.date_cond('g.arrived_at', date_from, date_to)
        return _summary(conn, f'g.left_at IS NOT NULL AND {dc}', tuple(da))
    return _summary(conn)


@router.post('/visits')
def new_visit(body: VisitIn, user=Depends(sec_user), conn=db.DB):
    code = db.next_code(conn, 'guest_visits', 'code', 'MS')
    now = db.now()
    cur = conn.execute('INSERT INTO guest_visits (code, purpose, note, arrived_at, created_by, created_at) VALUES (?,?,?,?,?,?)',
                       (code, (body.purpose or '').strip() or None, (body.note or '').strip() or None, now, user['id'], now))
    db.audit(conn, user['id'], 'Misafir kaydı açtı', 'guest_visit', cur.lastrowid, code)
    return {'id': cur.lastrowid, 'code': code}


@router.get('/visits/{vid}')
def get_visit(vid: int, user=Depends(sec_user), conn=db.DB):
    return _visit(conn, vid)


@router.put('/visits/{vid}')
def update_visit(vid: int, body: VisitIn, user=Depends(sec_user), conn=db.DB):
    _visit(conn, vid)
    conn.execute('UPDATE guest_visits SET purpose = ?, note = ? WHERE id = ?',
                 ((body.purpose or '').strip() or None, (body.note or '').strip() or None, vid))
    return _visit(conn, vid)


@router.post('/visits/{vid}/leave')
def leave(vid: int, user=Depends(sec_user), conn=db.DB):
    v = _visit(conn, vid)
    if v['left_at']:
        raise HTTPException(400, 'Misafir çıkışı zaten yapılmış')
    conn.execute('UPDATE guest_visits SET left_at = ? WHERE id = ?', (db.now(), vid))
    db.audit(conn, user['id'], 'Misafir çıkışı', 'guest_visit', vid, v['code'])
    return _visit(conn, vid)


@router.post('/visits/{vid}/people')
def add_guest(vid: int, body: GuestIn, user=Depends(sec_user), conn=db.DB):
    """Gelen kişi: kayıtlı kişi (person_id), bir firmaya yeni kişi (company_id + ad) ya da serbest giriş (ad + firma adı)."""
    v = _visit(conn, vid)
    if body.person_id:
        p = db.row(conn.execute('SELECT p.*, c.name AS company_name FROM company_people p JOIN companies c ON c.id = p.company_id '
                                'WHERE p.id = ?', (body.person_id,)))
        if not p:
            raise HTTPException(404, 'Kişi bulunamadı')
        if any(g['person_id'] == p['id'] for g in v['people']):
            raise HTTPException(400, f'{p["full_name"]} zaten ekli')
        pid, name, company_text, title, phone = p['id'], p['full_name'], None, p['title'], p['phone']
    else:
        name = (body.full_name or '').strip()
        if not name:
            raise HTTPException(400, 'Ad soyad zorunlu')
        title, phone = (body.title or '').strip() or None, (body.phone or '').strip() or None
        if body.company_id:   # firmaya yeni kişi olarak da kaydedilir (Rehber'de görünür)
            c = db.row(conn.execute('SELECT id, name FROM companies WHERE id = ?', (body.company_id,)))
            if not c:
                raise HTTPException(400, 'Firma bulunamadı')
            pid = conn.execute('INSERT INTO company_people (company_id, full_name, title, phone, created_at) VALUES (?,?,?,?,?)',
                               (c['id'], name, title, phone, db.now())).lastrowid
            db.audit(conn, user['id'], 'Firmaya kişi ekledi (misafir)', 'company', c['id'], f'{c["name"]}: {name}')
            company_text = None
        else:
            pid, company_text = None, (body.company_text or '').strip() or None
    conn.execute('INSERT INTO guest_visit_people (visit_id, person_id, full_name, company_text, title, phone) VALUES (?,?,?,?,?,?)',
                 (vid, pid, name, company_text, title, phone))
    return _visit(conn, vid)


@router.delete('/visits/{vid}/people/{gid}')
def remove_guest(vid: int, gid: int, user=Depends(sec_user), conn=db.DB):
    conn.execute('DELETE FROM guest_visit_people WHERE id = ? AND visit_id = ?', (gid, vid))
    return _visit(conn, vid)


@router.post('/visits/{vid}/vehicles')
def add_vehicles(vid: int, body: IdsIn, user=Depends(sec_user), conn=db.DB):
    _visit(conn, vid)
    ok = {v['id'] for v in parked(conn)}
    bad = [i for i in body.ids if i not in ok]
    if bad:
        raise HTTPException(400, 'Yalnızca parktaki (çıkış yapmamış) araçlar seçilebilir')
    conn.executemany('INSERT OR IGNORE INTO guest_visit_vehicles (visit_id, vehicle_id) VALUES (?,?)', [(vid, i) for i in body.ids])
    return _visit(conn, vid)


@router.delete('/visits/{vid}/vehicles/{vehicle_id}')
def remove_vehicle(vid: int, vehicle_id: int, user=Depends(sec_user), conn=db.DB):
    conn.execute('DELETE FROM guest_visit_vehicles WHERE visit_id = ? AND vehicle_id = ?', (vid, vehicle_id))
    return _visit(conn, vid)


@router.post('/visits/{vid}/hosts')
def add_hosts(vid: int, body: IdsIn, user=Depends(sec_user), conn=db.DB):
    """Görüşülecek kişiler (firma kullanıcıları): her birine bildirim düşer."""
    v = _visit(conn, vid)
    active = {r[0] for r in conn.execute('SELECT id FROM users WHERE active = 1 AND deleted_at IS NULL')}
    if any(i not in active for i in body.ids):
        raise HTTPException(400, 'Geçersiz kullanıcı')
    now = db.now()
    conn.executemany('INSERT OR IGNORE INTO guest_visit_hosts (visit_id, user_id, added_at) VALUES (?,?,?)', [(vid, i, now) for i in body.ids])
    db.audit(conn, user['id'], 'Misafiri kişiyle ilişkilendirdi', 'guest_visit', vid, f'{v["code"]}: {len(body.ids)} kişi')
    return _visit(conn, vid)


@router.delete('/visits/{vid}/hosts/{uid}')
def remove_host(vid: int, uid: int, user=Depends(sec_user), conn=db.DB):
    conn.execute('DELETE FROM guest_visit_hosts WHERE visit_id = ? AND user_id = ?', (vid, uid))
    return _visit(conn, vid)


# ---------- Kargolar

CARGO_SELECT = '''SELECT k.*, r.full_name AS recipient_name, r.photo AS recipient_photo, c.full_name AS created_by_name,
       d.full_name AS delivered_by_name
FROM cargo k JOIN users r ON r.id = k.recipient_id LEFT JOIN users c ON c.id = k.created_by LEFT JOIN users d ON d.id = k.delivered_by'''


@router.get('/cargo')
def cargo_list(date_from: str = '', date_to: str = '', user=Depends(sec_user), conn=db.DB):
    # Bekleyen kargolar her zaman; teslim edilenler teslim tarihine göre (tarih aralığı verilirse)
    dc, da = db.date_cond('k.delivered_at', date_from, date_to)
    where = f'(k.delivered_at IS NULL OR ({dc}))' if (date_from or date_to) else '1=1'
    return db.rows(conn.execute(CARGO_SELECT + f' WHERE {where} ORDER BY k.delivered_at IS NOT NULL, k.created_at DESC LIMIT 500', tuple(da)))


@router.post('/cargo')
async def cargo_add(recipient_id: int = Form(...), carrier: str = Form(''), tracking_no: str = Form(''),
                    description: str = Form(''), photo: Optional[UploadFile] = File(None),
                    user=Depends(sec_user), conn=db.DB):
    """Gelen kargo: ilgili kişiye bağlanır, resmi çekilebilir; kişiye bildirim düşer (Kargolarım)."""
    path = await save_upload('cargo', photo) if photo and photo.filename else None

    def write():
        r = db.row(conn.execute('SELECT id, full_name FROM users WHERE id = ? AND active = 1', (recipient_id,)))
        if not r:
            raise HTTPException(400, 'İlgili kişiyi seçin')
        cur = conn.execute('''INSERT INTO cargo (carrier, tracking_no, description, photo, recipient_id, created_by, created_at)
                              VALUES (?,?,?,?,?,?,?)''',
                           (carrier.strip() or None, tracking_no.strip() or None, description.strip() or None, path,
                            recipient_id, user['id'], db.now()))
        db.audit(conn, user['id'], 'Kargo kaydetti', 'cargo', cur.lastrowid, f'{r["full_name"]}: {carrier.strip() or "kargo"}')
        return {'id': cur.lastrowid}
    return await run_in_threadpool(write)


@router.post('/cargo/{cid}/deliver')
def cargo_deliver_by_secretary(cid: int, user=Depends(sec_user), conn=db.DB):
    """Sekreterya teslim etti (kişi ekrandan onaylamadan elden teslim)."""
    return _deliver(conn, cid, user, by_recipient=False)


def _deliver(conn, cid, user, by_recipient):
    k = db.row(conn.execute('SELECT * FROM cargo WHERE id = ?', (cid,)))
    if not k or (by_recipient and k['recipient_id'] != user['id']):
        raise HTTPException(404, 'Kargo bulunamadı')
    if k['delivered_at']:
        raise HTTPException(400, 'Bu kargo zaten teslim alınmış')
    conn.execute('UPDATE cargo SET delivered_at = ?, delivered_by = ? WHERE id = ?', (db.now(), user['id'], cid))
    db.audit(conn, user['id'], 'Kargoyu teslim aldı' if by_recipient else 'Kargoyu teslim etti', 'cargo', cid, None)
    return {'ok': True}


@me_router.get('/cargo')
def my_cargo(user=Depends(auth.current_user), conn=db.DB):
    return db.rows(conn.execute(CARGO_SELECT + ' WHERE k.recipient_id = ? ORDER BY k.delivered_at IS NOT NULL, k.created_at DESC LIMIT 200',
                                (user['id'],)))


@me_router.post('/cargo/{cid}/receive')
def receive(cid: int, user=Depends(auth.current_user), conn=db.DB):
    return _deliver(conn, cid, user, by_recipient=True)


@me_router.get('/guests')
def my_guests(user=Depends(auth.current_user), conn=db.DB):
    """Görüşülecek kişi olarak ilişkilendirildiğim misafir kayıtları (son 60)."""
    rows = _summary(conn, 'g.id IN (SELECT visit_id FROM guest_visit_hosts WHERE user_id = ?)', (user['id'],))[:60]
    conn.execute('UPDATE guest_visit_hosts SET seen_at = ? WHERE user_id = ? AND seen_at IS NULL', (db.now(), user['id']))   # bildirim kalkar
    for r in rows:
        r['people'] = db.rows(conn.execute(
            '''SELECT gp.full_name, gp.title, gp.company_text, c.name AS company_name, c.logo AS company_logo
               FROM guest_visit_people gp LEFT JOIN company_people p ON p.id = gp.person_id
               LEFT JOIN companies c ON c.id = p.company_id WHERE gp.visit_id = ? ORDER BY gp.id''', (r['id'],)))
    return rows


def _cargo_guard(user, name):
    if 'secretariat' in user['modules']:
        return True
    with db.connect() as conn:
        return conn.execute('SELECT 1 FROM cargo WHERE photo = ? AND recipient_id = ?', (f'cargo/{name}', user['id'])).fetchone() is not None


FILE_GUARDS['cargo'] = _cargo_guard
