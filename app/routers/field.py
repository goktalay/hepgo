"""Saha Yönetimi: görevler ve alt modülleri (uçuşlar, masraflar, yol, görev yerleri).

Bir görev birden fazla uçak (sipariş) götürebilir; her uçak için bir uçuş (field_flights) açılır.
Görev bitip (başarılı/başarısız) tüm uçuşların uçuş raporu hazır olunca görev "Rapor Tamamlandı" olur.
"""
from datetime import datetime
from typing import Optional

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, config, db
from ..files import KINDS, local_only, save_upload

router = APIRouter(prefix='/api/field')
field_user = auth.require_module('field')
field_manager = auth.require_roles(*auth.FIELD_MANAGERS)

STATUS_TEXT = {
    'BASLANGIC': 'Başlangıç',
    'GOREVDE': 'Görevde',
    'GOREV_TAMAMLANDI': 'Görev Tamamlandı',
    'BASARISIZ': 'Başarısız',
    'RAPOR_TAMAMLANDI': 'Rapor Tamamlandı',
    'IPTAL': 'İptal',
}
LAUNCH_TEXT = {'ARAC_USTU': 'Araç Üstü', 'RAMPA': 'Fırlatma Rampası'}
EXPENSE_CATEGORIES = ['Yakıt', 'Konaklama', 'Yemek', 'Ulaşım / otoyol', 'Malzeme', 'Diğer']
FINISHED = ('GOREV_TAMAMLANDI', 'BASARISIZ')


class TaskIn(BaseModel):
    order_ids: list[int]
    lead_id: int
    driver_id: Optional[int] = None   # eski alan: şoförler artık görevdeki araçlarla girilir
    pilot_id: Optional[int] = None
    staff_ids: list[int] = []
    location_id: Optional[int] = None
    note: Optional[str] = None


class FinishIn(BaseModel):
    success: bool
    at: Optional[str] = None


class AtIn(BaseModel):
    at: Optional[str] = None


class FlightIn(BaseModel):
    launch: Optional[str] = None
    note: Optional[str] = None


class RoadIn(BaseModel):
    location_id: Optional[int] = None
    road_note: Optional[str] = None


class TaskVehicleIn(BaseModel):
    vehicle_id: Optional[int] = None
    driver_id: Optional[int] = None
    start_km: Optional[float] = None
    end_km: Optional[float] = None
    note: Optional[str] = None


class VehicleIn(BaseModel):
    plate: str
    description: Optional[str] = None
    active: bool = True


class LocationIn(BaseModel):
    name: str
    description: Optional[str] = None
    active: bool = True


def _has_role(conn, uid, role):
    return conn.execute(
        'SELECT 1 FROM users u JOIN user_roles r ON r.user_id = u.id WHERE u.id = ? AND r.role = ? AND u.active = 1',
        (uid, role)).fetchone() is not None


def _flights(conn, task_ids):
    if not task_ids:
        return {}
    rows = db.rows(conn.execute(
        f'''SELECT f.*, o.code AS order_code, o.queue_no, o.status AS order_status, p.name AS product_name, p.serial AS product_serial,
                   l.id AS log_id, l.status AS log_status, l.file_name AS log_file, l.error AS log_error,
                   json_extract(l.analysis, '$.summary.flight_s') AS flight_s
            FROM field_flights f
            JOIN orders o ON o.id = f.order_id
            LEFT JOIN products p ON p.id = o.product_id
            LEFT JOIN flight_logs l ON l.id = (SELECT MAX(id) FROM flight_logs WHERE flight_id = f.id)
            WHERE f.task_id IN ({','.join('?' * len(task_ids))}) ORDER BY o.queue_no''', task_ids))
    videos = {}
    if rows:
        for v in db.rows(conn.execute(
                f'''SELECT v.id, v.flight_id, v.file, v.file_name, v.size, v.uploaded_at, v.uploaded_by, v.kind,
                           u.full_name AS uploaded_by_name
                    FROM flight_videos v LEFT JOIN users u ON u.id = v.uploaded_by
                    WHERE v.flight_id IN ({','.join('?' * len(rows))}) ORDER BY v.id''', [f['id'] for f in rows])):
            videos.setdefault(v['flight_id'], []).append(v)
    out = {}
    for f in rows:
        f['launch_text'] = LAUNCH_TEXT.get(f['launch'])
        f['videos'] = videos.get(f['id'], [])
        out.setdefault(f['task_id'], []).append(f)
    return out


def _task_vehicles(conn, task_ids):
    """Görevlere giden araçlar: {görev id: [araç satırı]} (plaka, şoför, km, gidilen yol)."""
    out = {}
    if not task_ids:
        return out
    marks = ','.join('?' * len(task_ids))
    for r in db.rows(conn.execute(
            'SELECT tv.*, v.plate, v.description AS vehicle_description, u.full_name AS driver_name '
            'FROM field_task_vehicles tv JOIN field_vehicles v ON v.id = tv.vehicle_id '
            f'LEFT JOIN users u ON u.id = tv.driver_id WHERE tv.task_id IN ({marks}) ORDER BY tv.id', task_ids)):
        r['distance_km'] = (r['end_km'] - r['start_km']) if r['start_km'] is not None and r['end_km'] is not None else None
        out.setdefault(r['task_id'], []).append(r)
    return out


def _tasks(conn, where='1=1', args=()):
    tasks = db.rows(conn.execute(
        f'''SELECT t.*, d.full_name AS driver_name, ld.full_name AS lead_name, c.full_name AS created_by_name,
                   pl.full_name AS pilot_name,
                   loc.name AS location_name,
                   (SELECT COALESCE(SUM(amount), 0) FROM field_expenses e WHERE e.task_id = t.id) AS expense_total,
                   (SELECT COUNT(*) FROM field_expenses e WHERE e.task_id = t.id) AS expense_count
            FROM field_tasks t
            LEFT JOIN users d ON d.id = t.driver_id
            LEFT JOIN users pl ON pl.id = t.pilot_id
            LEFT JOIN users ld ON ld.id = t.lead_id
            LEFT JOIN users c ON c.id = t.created_by
            LEFT JOIN field_locations loc ON loc.id = t.location_id
            WHERE {where} ORDER BY t.id DESC''', args))
    flights = _flights(conn, [t['id'] for t in tasks])
    vehicles = _task_vehicles(conn, [t['id'] for t in tasks])
    for t in tasks:
        t['status_text'] = STATUS_TEXT[t['status']]
        t['staff'] = db.rows(conn.execute(
            '''SELECT u.id, u.full_name FROM field_task_staff s JOIN users u ON u.id = s.user_id
               WHERE s.task_id = ? ORDER BY u.full_name''', (t['id'],)))
        t['flights'] = flights.get(t['id'], [])
        t['aircraft'] = ', '.join(f['queue_no'] or f['order_code'] for f in t['flights'])
        t['logs_ready'] = sum(1 for f in t['flights'] if f['log_status'] == 'TAMAM')
        t['vehicles'] = vehicles.get(t['id'], [])
        t['vehicle_plate'] = ', '.join(v['plate'] for v in t['vehicles']) or None
        dists = [v['distance_km'] for v in t['vehicles'] if v['distance_km'] is not None]
        t['distance_km'] = sum(dists) if dists else None
        if t['started_at']:
            end = datetime.fromisoformat(t['finished_at']) if t['finished_at'] else datetime.now()
            t['duration_seconds'] = int((end - datetime.fromisoformat(t['started_at'])).total_seconds())
    return tasks


def get_task(conn, tid):
    tasks = _tasks(conn, 't.id = ?', (tid,))
    if not tasks:
        raise HTTPException(404, 'Görev bulunamadı')
    return tasks[0]


def is_manager(user):
    return bool(set(auth.FIELD_MANAGERS) & set(user['roles']))


def _member(task, user):
    return (user['id'] in (task['lead_id'], task['driver_id'], task['pilot_id'], task['created_by'])
            or any(s['id'] == user['id'] for s in task['staff'])
            or any(v['driver_id'] == user['id'] for v in task['vehicles']))


def complete_if_reported(conn, tid):
    """Görev bitmişse ve tüm uçuşların raporu hazırsa görevi Rapor Tamamlandı yapar."""
    t = get_task(conn, tid)
    if t['status'] in FINISHED and t['flights'] and t['logs_ready'] == len(t['flights']):
        conn.execute("UPDATE field_tasks SET status = 'RAPOR_TAMAMLANDI', report_at = ? WHERE id = ?", (db.now(), tid))


# ---------- Görevler ----------

@router.get('/meta')
def meta(user=Depends(field_user)):
    return {'launch': LAUNCH_TEXT, 'expense_categories': EXPENSE_CATEGORIES, 'statuses': STATUS_TEXT}


@router.get('/tasks')
def list_tasks(user=Depends(field_user), conn=db.DB):
    return _tasks(conn)


@router.get('/tasks/{tid}')
def task_detail(tid: int, user=Depends(field_user), conn=db.DB):
    t = get_task(conn, tid)
    t['expenses'] = db.rows(conn.execute(
        '''SELECT e.*, u.full_name AS created_by_name, sp.full_name AS spent_by_name FROM field_expenses e
           LEFT JOIN users u ON u.id = e.created_by LEFT JOIN users sp ON sp.id = e.spent_by
           WHERE e.task_id = ? ORDER BY e.spent_on DESC, e.id DESC''', (tid,)))
    t['can'] = {
        'manage': is_manager(user),
        'flights': is_manager(user) or auth.PILOT in user['roles'],
        'expenses': is_manager(user) or _member(t, user),
        # Yol: görev yeri ve araç ekleme saha yöneticisi ve görevin şoförü; her şoför kendi aracının km'sini girer
        'road': is_manager(user) or user['id'] == t['driver_id'],
        'road_own': [v['id'] for v in t['vehicles'] if v['driver_id'] == user['id']],
    }
    return t


@router.get('/available-aircraft')
def available_aircraft(user=Depends(field_manager), conn=db.DB):
    """Sahaya götürülebilecek uçaklar: saha deposundakiler ve montaj aşamasındakiler (montaj sahada da yapılabilir).
    Açık bir görevde (başlangıç / görevde) olan uçak seçilemez. Kullanım durumu: tek kullanımlık uçak bir kez saha
    görevine gittiyse (uçtuysa HURDA olur) yeniden seçilemez; çoklu kullanım uçağı görev bitince yeniden seçilebilir."""
    return db.rows(conn.execute(
        '''SELECT o.id, o.code, o.queue_no, o.status, o.note, o.completed_at, p.name AS product_name,
                  COALESCE(p.usage_type, 'TEK') AS usage_type,
                  (SELECT COUNT(*) FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                   WHERE f.order_id = o.id AND t.status != 'IPTAL') AS past_tasks
           FROM orders o LEFT JOIN products p ON p.id = o.product_id
           WHERE o.status IN ('TAMAMLANDI', 'MONTAJ') AND p.type = 'MAMUL' AND NOT EXISTS (
               SELECT 1 FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
               WHERE f.order_id = o.id AND t.status != 'IPTAL'
                 AND (COALESCE(p.usage_type, 'TEK') != 'COKLU' OR t.status IN ('BASLANGIC', 'GOREVDE')))
           ORDER BY o.status = 'MONTAJ', o.queue_no, o.code'''))


@router.post('/tasks')
def create_task(body: TaskIn, user=Depends(field_manager), conn=db.DB):
    orders = sorted(set(body.order_ids))
    if not orders:
        raise HTTPException(400, 'En az bir uçak seçin')
    available = {r['id'] for r in available_aircraft(user, conn)}
    if any(o not in available for o in orders):
        raise HTTPException(400, 'Seçilen uçaklardan biri saha deposunda / montajda değil veya başka bir görevde')
    if not _has_role(conn, body.lead_id, auth.FIELD_LEAD) and not _has_role(conn, body.lead_id, auth.ADMIN):
        raise HTTPException(400, 'Seçilen kişi saha sorumlusu değil')
    if body.driver_id and not _has_role(conn, body.driver_id, auth.DRIVER):
        raise HTTPException(400, 'Seçilen kişi şoför değil')
    if not body.pilot_id:
        raise HTTPException(400, 'Pilot seçin')
    if not _has_role(conn, body.pilot_id, auth.PILOT):
        raise HTTPException(400, 'Seçilen kişi pilot değil')
    staff = sorted(set(body.staff_ids))
    if not staff:
        raise HTTPException(400, 'En az bir saha personeli ekleyin')
    for sid in staff:
        if not _has_role(conn, sid, auth.FIELD_STAFF):
            raise HTTPException(400, 'Personel listesinde saha personeli olmayan biri var')
    code = db.next_code(conn, 'field_tasks', 'code', 'GRV')
    cur = conn.execute(
        '''INSERT INTO field_tasks (code, lead_id, driver_id, pilot_id, location_id, created_by, created_at, note)
           VALUES (?,?,?,?,?,?,?,?)''',
        (code, body.lead_id, body.driver_id, body.pilot_id, body.location_id, user['id'], db.now(), body.note))
    tid = cur.lastrowid
    conn.executemany('INSERT INTO field_task_staff (task_id, user_id) VALUES (?,?)', [(tid, s) for s in staff])
    conn.executemany('INSERT INTO field_flights (task_id, order_id, updated_at) VALUES (?,?,?)',
                     [(tid, o, db.now()) for o in orders])
    # Montaj aşamasında sahaya götürülen uçaklar görev açılınca "Sahada Montaj" aşamasına geçer
    conn.execute(f"""UPDATE orders SET status = 'SAHADA_MONTAJ' WHERE status = 'MONTAJ'
                     AND id IN ({','.join('?' * len(orders))})""", orders)
    db.audit(conn, user['id'], 'Saha görevi oluşturdu', 'field_task', tid, f'{code} ({len(orders)} uçak)')
    return {'id': tid, 'code': code}


def _transition(conn, tid, expected):
    task = get_task(conn, tid)
    if task['status'] not in expected:
        raise HTTPException(400, f'Görev bu işlem için uygun durumda değil ({task["status_text"]})')
    return task


@router.post('/tasks/{tid}/start')
def start_task(tid: int, body: Optional[AtIn] = None, user=Depends(field_manager), conn=db.DB):
    task = _transition(conn, tid, ['BASLANGIC'])
    at = db.pick_time(body and body.at, task['created_at'], 'Başlama zamanı', 'görevin açılış')
    conn.execute("UPDATE field_tasks SET status = 'GOREVDE', started_at = ? WHERE id = ?", (at, tid))
    # Montaj aşamasında sahaya götürülen uçaklar "Sahada Montaj" aşamasına geçer
    conn.execute("""UPDATE orders SET status = 'SAHADA_MONTAJ' WHERE status = 'MONTAJ'
                    AND id IN (SELECT order_id FROM field_flights WHERE task_id = ?)""", (tid,))
    db.audit(conn, user['id'], 'Saha görevini başlattı', 'field_task', tid, task['code'])
    return {'ok': True}


@router.post('/tasks/{tid}/cancel')
def cancel_task(tid: int, user=Depends(field_manager), conn=db.DB):
    task = _transition(conn, tid, ['BASLANGIC'])
    conn.execute("UPDATE field_tasks SET status = 'IPTAL' WHERE id = ?", (tid,))
    # İptal: sahaya götürülmeyen uçaklar fabrikadaki montaj aşamasına döner
    conn.execute("""UPDATE orders SET status = 'MONTAJ' WHERE status = 'SAHADA_MONTAJ'
                    AND id IN (SELECT order_id FROM field_flights WHERE task_id = ?)""", (tid,))
    db.audit(conn, user['id'], 'Saha görevini iptal etti', 'field_task', tid, task['code'])
    return {'ok': True}


@router.post('/tasks/{tid}/finish')
def finish_task(tid: int, body: FinishIn, user=Depends(field_manager), conn=db.DB):
    task = _transition(conn, tid, ['GOREVDE'])
    status, result = ('GOREV_TAMAMLANDI', 'BASARILI') if body.success else ('BASARISIZ', 'BASARISIZ')
    at = db.pick_time(body.at, task['started_at'], 'Bitiş zamanı', 'görevin başlama')
    conn.execute('UPDATE field_tasks SET status = ?, result = ?, finished_at = ? WHERE id = ?',
                 (status, result, at, tid))
    # Görev bitti: montajı sahada tamamlanmamış uçaklar fabrikadaki montaj aşamasına döner
    conn.execute("""UPDATE orders SET status = 'MONTAJ' WHERE status = 'SAHADA_MONTAJ'
                    AND id IN (SELECT order_id FROM field_flights WHERE task_id = ?)""", (tid,))
    db.audit(conn, user['id'], 'Saha görevini bitirdi', 'field_task', tid,
             f'{task["code"]}: {"Başarılı" if body.success else "Başarısız"}')
    complete_if_reported(conn, tid)
    return {'ok': True}


# ---------- Uçuş Yönetimi ----------

def flight_row(conn, fid):
    f = db.row(conn.execute('SELECT * FROM field_flights WHERE id = ?', (fid,)))
    if not f:
        raise HTTPException(404, 'Uçuş bulunamadı')
    return f


def require_flight_editor(user):
    if not (set(auth.FIELD_MANAGERS) | {auth.PILOT}) & set(user['roles']):
        raise HTTPException(403, 'Uçuş bilgisini yalnızca saha sorumlusu veya pilot düzenleyebilir')


@router.put('/flights/{fid}')
def update_flight(fid: int, body: FlightIn, user=Depends(field_user), conn=db.DB):
    require_flight_editor(user)
    f = flight_row(conn, fid)
    task = get_task(conn, f['task_id'])
    if task['status'] == 'IPTAL':
        raise HTTPException(400, 'İptal edilmiş görevin uçuşu düzenlenemez')
    if body.launch not in (None, *LAUNCH_TEXT):
        raise HTTPException(400, 'Geçersiz fırlatma sistemi')
    conn.execute('UPDATE field_flights SET launch = ?, note = ?, updated_at = ? WHERE id = ?',
                 (body.launch, (body.note or '').strip() or None, db.now(), fid))
    order = conn.execute('SELECT COALESCE(queue_no, code) FROM orders WHERE id = ?', (f['order_id'],)).fetchone()[0]
    db.audit(conn, user['id'], 'Uçuş bilgisini düzenledi', 'field_flight', fid,
             f'{task["code"]} / {order}: {LAUNCH_TEXT.get(body.launch, "fırlatma seçilmedi")}')
    return {'ok': True}


# ---------- Masraf Yönetimi ----------

@router.post('/tasks/{tid}/expenses')
async def add_expense(tid: int, spent_on: str = Form(...), category: str = Form(...), amount: float = Form(...),
                      description: str = Form(''), receipt: Optional[UploadFile] = File(None),
                      spent_by: Optional[int] = Form(None), user=Depends(field_user), conn=db.DB):
    task = get_task(conn, tid)
    if not (is_manager(user) or _member(task, user)):
        raise HTTPException(403, 'Masrafı yalnızca görevdeki kişiler girebilir')
    if category not in EXPENSE_CATEGORIES:
        raise HTTPException(400, 'Geçersiz masraf kategorisi')
    if amount <= 0:
        raise HTTPException(400, 'Tutar sıfırdan büyük olmalı')
    try:
        datetime.fromisoformat(spent_on)
    except ValueError:
        raise HTTPException(400, 'Geçersiz tarih')
    spender = spent_by or user['id']   # masrafı yapan: sistemdeki herhangi bir personel (varsayılan: giren kişi)
    if not conn.execute('SELECT 1 FROM users WHERE id = ? AND active = 1 AND deleted_at IS NULL', (spender,)).fetchone():
        raise HTTPException(400, 'Masrafı yapan kişi bulunamadı')
    path = await save_upload('receipts', receipt) if receipt and receipt.filename else None

    def write():
        cur = conn.execute(
            '''INSERT INTO field_expenses (task_id, spent_on, category, description, amount, receipt, spent_by, created_by,
                                           created_at) VALUES (?,?,?,?,?,?,?,?,?)''',
            (tid, spent_on[:10], category, description.strip() or None, round(amount, 2), path, spender, user['id'], db.now()))
        db.audit(conn, user['id'], 'Görev masrafı ekledi', 'field_task', tid,
                 f'{task["code"]}: {category} {amount:.2f} TL')
        return cur.lastrowid
    return {'id': await run_in_threadpool(write)}


@router.delete('/expenses/{eid}')
def delete_expense(eid: int, user=Depends(field_user), conn=db.DB):
    e = db.row(conn.execute('SELECT * FROM field_expenses WHERE id = ?', (eid,)))
    if not e:
        raise HTTPException(404, 'Masraf bulunamadı')
    if not (is_manager(user) or e['created_by'] == user['id']):
        raise HTTPException(403, 'Masrafı yalnızca giren kişi veya saha sorumlusu silebilir')
    conn.execute('DELETE FROM field_expenses WHERE id = ?', (eid,))
    db.audit(conn, user['id'], 'Görev masrafı sildi', 'field_task', e['task_id'], f'{e["category"]} {e["amount"]:.2f} TL')
    return {'ok': True}


# ---------- Yol Yönetimi ----------

def _road_manager(task, user):
    if not (is_manager(user) or user['id'] == task['driver_id']):
        raise HTTPException(403, 'Yol bilgisini yalnızca görevin şoförü veya saha sorumlusu girebilir')


@router.put('/tasks/{tid}/road')
def update_road(tid: int, body: RoadIn, user=Depends(field_user), conn=db.DB):
    """Görev geneli yol bilgisi: görev yeri ve not (araçlar ayrı satırlarda)."""
    task = get_task(conn, tid)
    _road_manager(task, user)
    if body.location_id and not conn.execute('SELECT 1 FROM field_locations WHERE id = ?', (body.location_id,)).fetchone():
        raise HTTPException(400, 'Görev yeri bulunamadı')
    conn.execute('UPDATE field_tasks SET location_id = ?, road_note = ? WHERE id = ?',
                 (body.location_id, (body.road_note or '').strip() or None, tid))
    db.audit(conn, user['id'], 'Yol bilgisini girdi', 'field_task', tid, task['code'])
    return {'ok': True}


def _check_km(start_km, end_km):
    if start_km is not None and start_km < 0 or end_km is not None and end_km < 0:
        raise HTTPException(400, 'Km değeri negatif olamaz')
    if start_km is not None and end_km is not None and end_km < start_km:
        raise HTTPException(400, "Bitiş km, başlangıç km'den küçük olamaz")


def _check_driver(conn, driver_id):
    if driver_id and not _has_role(conn, driver_id, auth.DRIVER):
        raise HTTPException(400, 'Seçilen kişi şoför değil')


@router.post('/tasks/{tid}/vehicles')
def add_task_vehicle(tid: int, body: TaskVehicleIn, user=Depends(field_user), conn=db.DB):
    """Göreve araç ekler (birden fazla araç gidebilir); şoför seçilmezse görevin şoförü."""
    task = get_task(conn, tid)
    _road_manager(task, user)
    if task['status'] == 'IPTAL':
        raise HTTPException(400, 'İptal edilen göreve araç eklenemez')
    v = db.row(conn.execute('SELECT * FROM field_vehicles WHERE id = ?', (body.vehicle_id,))) if body.vehicle_id else None
    if not v or not v['active']:
        raise HTTPException(400, 'Geçerli bir araç seçin')
    if conn.execute('SELECT 1 FROM field_task_vehicles WHERE task_id = ? AND vehicle_id = ?', (tid, v['id'])).fetchone():
        raise HTTPException(400, 'Bu araç görevde zaten var')
    driver = body.driver_id or task['driver_id']
    _check_driver(conn, driver)
    _check_km(body.start_km, body.end_km)
    cur = conn.execute(
        'INSERT INTO field_task_vehicles (task_id, vehicle_id, driver_id, start_km, end_km, note, created_at) '
        'VALUES (?,?,?,?,?,?,?)',
        (tid, v['id'], driver, body.start_km, body.end_km, (body.note or '').strip() or None, db.now()))
    db.audit(conn, user['id'], 'Göreve araç ekledi', 'field_task', tid, f'{task["code"]}: {v["plate"]}')
    return {'id': cur.lastrowid}


def _task_vehicle(conn, rid):
    r = db.row(conn.execute('SELECT tv.*, v.plate FROM field_task_vehicles tv JOIN field_vehicles v ON v.id = tv.vehicle_id '
                            'WHERE tv.id = ?', (rid,)))
    if not r:
        raise HTTPException(404, 'Araç kaydı bulunamadı')
    return r


@router.put('/task-vehicles/{rid}')
def update_task_vehicle(rid: int, body: TaskVehicleIn, user=Depends(field_user), conn=db.DB):
    """Aracın şoförü ve km'leri: saha yöneticisi ya da görevin şoförü; aracın kendi şoförü km'lerini girer."""
    r = _task_vehicle(conn, rid)
    task = get_task(conn, r['task_id'])
    manager = is_manager(user) or user['id'] == task['driver_id']
    if not (manager or user['id'] == r['driver_id']):
        raise HTTPException(403, 'Bu aracın bilgisini yalnızca şoförü veya saha sorumlusu girebilir')
    driver = (body.driver_id or r['driver_id']) if manager else r['driver_id']
    _check_driver(conn, driver)
    _check_km(body.start_km, body.end_km)
    conn.execute('UPDATE field_task_vehicles SET driver_id = ?, start_km = ?, end_km = ?, note = ? WHERE id = ?',
                 (driver, body.start_km, body.end_km, (body.note or '').strip() or None, rid))
    km = lambda v: '—' if v is None else f'{v:g}'
    db.audit(conn, user['id'], 'Araç yol bilgisini girdi', 'field_task', task['id'],
             f'{task["code"]}: {r["plate"]} · {km(body.start_km)} → {km(body.end_km)} km')
    return {'ok': True}


@router.delete('/task-vehicles/{rid}')
def delete_task_vehicle(rid: int, user=Depends(field_user), conn=db.DB):
    r = _task_vehicle(conn, rid)
    task = get_task(conn, r['task_id'])
    _road_manager(task, user)
    conn.execute('DELETE FROM field_task_vehicles WHERE id = ?', (rid,))
    db.audit(conn, user['id'], 'Görevden aracı çıkardı', 'field_task', task['id'], f'{task["code"]}: {r["plate"]}')
    return {'ok': True}


# ---------- Görev yerleri ----------

def require_location_editor(user):
    """Görev yerleri ve araç listesi: saha sorumlusu, sistem yöneticisi ve şoför yönetir."""
    if not (set(auth.FIELD_MANAGERS) | {auth.DRIVER}) & set(user['roles']):
        raise HTTPException(403, 'Görev yerlerini ve araçları yalnızca saha sorumlusu veya şoför düzenleyebilir')


@router.get('/locations')
def list_locations(user=Depends(field_user), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT l.*, (SELECT COUNT(*) FROM field_tasks t WHERE t.location_id = l.id) AS task_count
           FROM field_locations l ORDER BY l.active DESC, l.name'''))


@router.post('/locations')
def add_location(body: LocationIn, user=Depends(field_user), conn=db.DB):
    require_location_editor(user)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, 'Görev yeri adı zorunlu')
    if conn.execute('SELECT 1 FROM field_locations WHERE name = ?', (name,)).fetchone():
        raise HTTPException(400, 'Bu görev yeri zaten kayıtlı')
    cur = conn.execute('INSERT INTO field_locations (name, description, active, created_at) VALUES (?,?,?,?)',
                       (name, (body.description or '').strip() or None, int(body.active), db.now()))
    db.audit(conn, user['id'], 'Görev yeri ekledi', 'field_location', cur.lastrowid, name)
    return {'id': cur.lastrowid}


@router.put('/locations/{lid}')
def update_location(lid: int, body: LocationIn, user=Depends(field_user), conn=db.DB):
    require_location_editor(user)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, 'Görev yeri adı zorunlu')
    if not conn.execute('SELECT 1 FROM field_locations WHERE id = ?', (lid,)).fetchone():
        raise HTTPException(404, 'Görev yeri bulunamadı')
    if conn.execute('SELECT 1 FROM field_locations WHERE name = ? AND id != ?', (name, lid)).fetchone():
        raise HTTPException(400, 'Bu görev yeri zaten kayıtlı')
    conn.execute('UPDATE field_locations SET name = ?, description = ?, active = ? WHERE id = ?',
                 (name, (body.description or '').strip() or None, int(body.active), lid))
    db.audit(conn, user['id'], 'Görev yerini düzenledi', 'field_location', lid, name)
    return {'ok': True}


@router.delete('/locations/{lid}')
def delete_location(lid: int, user=Depends(field_user), conn=db.DB):
    require_location_editor(user)
    loc = db.row(conn.execute('SELECT * FROM field_locations WHERE id = ?', (lid,)))
    if not loc:
        raise HTTPException(404, 'Görev yeri bulunamadı')
    if conn.execute('SELECT 1 FROM field_tasks WHERE location_id = ?', (lid,)).fetchone():
        raise HTTPException(400, 'Görevlerde kullanılan yer silinemez; pasife alabilirsiniz')
    conn.execute('DELETE FROM field_locations WHERE id = ?', (lid,))
    db.audit(conn, user['id'], 'Görev yerini sildi', 'field_location', lid, loc['name'])
    return {'ok': True}


# ---------- Araçlar (plakalar) ----------

def _norm_plate(p):
    return ' '.join(p.upper().split())


@router.get('/vehicles')
def list_vehicles(user=Depends(field_user), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT v.*, (SELECT COUNT(*) FROM field_task_vehicles t WHERE t.vehicle_id = v.id) AS task_count
           FROM field_vehicles v ORDER BY v.active DESC, v.plate'''))


@router.post('/vehicles')
def add_vehicle(body: VehicleIn, user=Depends(field_user), conn=db.DB):
    require_location_editor(user)
    plate = _norm_plate(body.plate)
    if not plate:
        raise HTTPException(400, 'Plaka zorunlu')
    if conn.execute('SELECT 1 FROM field_vehicles WHERE plate = ?', (plate,)).fetchone():
        raise HTTPException(400, 'Bu plaka zaten kayıtlı')
    cur = conn.execute('INSERT INTO field_vehicles (plate, description, active, created_at) VALUES (?,?,?,?)',
                       (plate, (body.description or '').strip() or None, int(body.active), db.now()))
    db.audit(conn, user['id'], 'Araç ekledi', 'field_vehicle', cur.lastrowid, plate)
    return {'id': cur.lastrowid}


@router.put('/vehicles/{vid}')
def update_vehicle(vid: int, body: VehicleIn, user=Depends(field_user), conn=db.DB):
    require_location_editor(user)
    plate = _norm_plate(body.plate)
    if not plate:
        raise HTTPException(400, 'Plaka zorunlu')
    if not conn.execute('SELECT 1 FROM field_vehicles WHERE id = ?', (vid,)).fetchone():
        raise HTTPException(404, 'Araç bulunamadı')
    if conn.execute('SELECT 1 FROM field_vehicles WHERE plate = ? AND id != ?', (plate, vid)).fetchone():
        raise HTTPException(400, 'Bu plaka zaten kayıtlı')
    conn.execute('UPDATE field_vehicles SET plate = ?, description = ?, active = ? WHERE id = ?',
                 (plate, (body.description or '').strip() or None, int(body.active), vid))
    db.audit(conn, user['id'], 'Aracı düzenledi', 'field_vehicle', vid, plate)
    return {'ok': True}


@router.delete('/vehicles/{vid}')
def delete_vehicle(vid: int, user=Depends(field_user), conn=db.DB):
    require_location_editor(user)
    v = db.row(conn.execute('SELECT * FROM field_vehicles WHERE id = ?', (vid,)))
    if not v:
        raise HTTPException(404, 'Araç bulunamadı')
    if conn.execute('SELECT 1 FROM field_task_vehicles WHERE vehicle_id = ?', (vid,)).fetchone():
        raise HTTPException(400, 'Görevlerde kullanılan araç silinemez; pasife alabilirsiniz')
    conn.execute('DELETE FROM field_vehicles WHERE id = ?', (vid,))
    db.audit(conn, user['id'], 'Araç sildi', 'field_vehicle', vid, v['plate'])
    return {'ok': True}


# ---------- Uçuş detayı (görevdeki uçağa tıklayınca): uçak + görev bilgisi, log, notlar, video/resimler ----------
NOTE_KINDS = {'GORUS': 'Görüş', 'IYILESTIRME': 'İyileştirme talebi', 'ARIZA': 'Arıza / sorun', 'GOZLEM': 'Gözlem', 'DIGER': 'Diğer'}


def _flight_notes(conn, fid):
    return db.rows(conn.execute(
        '''SELECT n.*, u.full_name AS created_by_name FROM flight_notes n LEFT JOIN users u ON u.id = n.created_by
           WHERE n.flight_id = ? ORDER BY n.created_at DESC, n.id DESC''', (fid,)))


@router.get('/flights')
def list_flights(view: str = 'ready', user=Depends(field_user), conn=db.DB):
    """Uçuş Yönetimi: saha görevlerine eklenmiş uçaklar. ready: uçuşa hazır (saha deposunda, montajı bitmiş; görev
    başlangıç / görevde), flown: uçmuş (logu hazır ya da hurda), all: iptal edilmemiş görevlerdeki tümü."""
    where = {'ready': "o.status = 'TAMAMLANDI' AND t.status IN ('BASLANGIC', 'GOREVDE')",
             'flown': "(o.status = 'HURDA' OR l.status = 'TAMAM')",
             'all': "t.status != 'IPTAL'"}.get(view)
    if not where:
        raise HTTPException(400, 'Geçersiz görünüm')
    return db.rows(conn.execute(
        f'''SELECT f.id, f.task_id, f.launch, o.id AS order_id, o.code AS order_code, o.queue_no, o.status AS order_status,
                   o.scrapped_at, p.name AS product_name, COALESCE(p.usage_type, 'TEK') AS usage_type,
                   t.code AS task_code, t.status AS task_status, t.started_at, loc.name AS location_name, pl.full_name AS pilot_name,
                   l.id AS log_id, l.status AS log_status, json_extract(l.analysis, '$.summary.flight_s') AS flight_s,
                   (SELECT COUNT(*) FROM flight_notes n WHERE n.flight_id = f.id) AS note_count,
                   (SELECT COUNT(*) FROM flight_videos v WHERE v.flight_id = f.id) AS media_count
            FROM field_flights f JOIN field_tasks t ON t.id = f.task_id JOIN orders o ON o.id = f.order_id
            LEFT JOIN products p ON p.id = o.product_id
            LEFT JOIN field_locations loc ON loc.id = t.location_id LEFT JOIN users pl ON pl.id = t.pilot_id
            LEFT JOIN flight_logs l ON l.id = (SELECT MAX(id) FROM flight_logs WHERE flight_id = f.id)
            WHERE t.status != 'IPTAL' AND {where}
            ORDER BY t.id DESC, o.queue_no'''))


@router.post('/flights/{fid}/scrap')
def scrap_aircraft(fid: int, user=Depends(field_manager), conn=db.DB):
    """Tek kullanımlık uçak uçtu: HURDA (log yüklenmediyse elle)."""
    from ..production import scrap
    flight = flight_row(conn, fid)
    if not scrap(conn, flight['order_id'], user['id'], 'Uçtu (saha sorumlusu işaretledi)'):
        raise HTTPException(400, 'Yalnızca saha deposundaki tek kullanımlık uçak hurdaya ayrılabilir')
    return {'ok': True}


@router.post('/flights/{fid}/unscrap')
def unscrap_aircraft(fid: int, user=Depends(field_manager), conn=db.DB):
    from ..production import unscrap
    if not unscrap(conn, flight_row(conn, fid)['order_id'], user['id']):
        raise HTTPException(400, 'Uçak hurdada değil')
    return {'ok': True}


@router.get('/flights/{fid}')
def flight_detail(fid: int, user=Depends(field_user), conn=db.DB):
    flight = flight_row(conn, fid)
    t = get_task(conn, flight['task_id'])
    f = next(x for x in t['flights'] if x['id'] == fid)
    order = db.row(conn.execute(
        '''SELECT o.id, o.code, o.queue_no, o.status, o.note, o.created_at, o.completed_at, o.scrapped_at, o.scrap_reason,
                  p.name AS product_name, p.serial AS product_serial, p.code AS product_code, COALESCE(p.usage_type, 'TEK') AS usage_type
           FROM orders o LEFT JOIN products p ON p.id = o.product_id WHERE o.id = ?''', (flight['order_id'],)))
    log = None
    if f['log_id']:
        log = db.row(conn.execute(
            '''SELECT id, file_name, size, status, error, uploaded_at, json_extract(analysis, '$.summary') AS summary
               FROM flight_logs WHERE id = ?''', (f['log_id'],)))
    task = {k: t.get(k) for k in ('id', 'code', 'status', 'lead_name', 'pilot_name', 'location_name', 'created_at',
                                  'started_at', 'finished_at', 'note', 'aircraft')}
    task['staff'] = [s['full_name'] for s in t.get('staff', [])]
    task['vehicles'] = [v['plate'] for v in t.get('vehicles', [])]
    can_edit = is_manager(user) or auth.PILOT in user['roles']
    return {'flight': f, 'order': order, 'task': task, 'log': log, 'notes': _flight_notes(conn, fid),
            'media': f['videos'], 'note_kinds': NOTE_KINDS,
            'can': {'edit': can_edit, 'upload': can_edit and t['status'] not in ('BASLANGIC', 'IPTAL'),
                    'manage': is_manager(user), 'notes': True}}


class FlightNoteIn(BaseModel):
    kind: str
    body: str


def _note_in(body):
    if body.kind not in NOTE_KINDS:
        raise HTTPException(400, 'Not türü seçin')
    text = body.body.strip()
    if not text:
        raise HTTPException(400, 'Not boş olamaz')
    return text


@router.post('/flights/{fid}/notes')
def add_flight_note(fid: int, body: FlightNoteIn, user=Depends(field_user), conn=db.DB):
    """Uçuş notu: Saha Yönetimi'ne girebilen herkes (pilot, saha ekibi) ekleyebilir."""
    flight = flight_row(conn, fid)
    text = _note_in(body)
    cur = conn.execute('INSERT INTO flight_notes (flight_id, kind, body, created_by, created_at) VALUES (?,?,?,?,?)',
                       (fid, body.kind, text, user['id'], db.now()))
    db.audit(conn, user['id'], 'Uçuş notu ekledi', 'field_task', flight['task_id'], NOTE_KINDS[body.kind])
    return {'id': cur.lastrowid, 'notes': _flight_notes(conn, fid)}


def _flight_note(conn, nid, user):
    n = db.row(conn.execute('SELECT * FROM flight_notes WHERE id = ?', (nid,)))
    if not n:
        raise HTTPException(404, 'Not bulunamadı')
    if n['created_by'] != user['id'] and not is_manager(user):
        raise HTTPException(403, 'Notu yalnızca yazan kişi ya da saha sorumlusu değiştirebilir')
    return n


@router.put('/flight-notes/{nid}')
def update_flight_note(nid: int, body: FlightNoteIn, user=Depends(field_user), conn=db.DB):
    n = _flight_note(conn, nid, user)
    text = _note_in(body)
    conn.execute('UPDATE flight_notes SET kind = ?, body = ?, updated_at = ? WHERE id = ?', (body.kind, text, db.now(), nid))
    return {'notes': _flight_notes(conn, n['flight_id'])}


@router.delete('/flight-notes/{nid}')
def delete_flight_note(nid: int, user=Depends(field_user), conn=db.DB):
    n = _flight_note(conn, nid, user)
    conn.execute('DELETE FROM flight_notes WHERE id = ?', (nid,))
    return {'notes': _flight_notes(conn, n['flight_id'])}


# ---------- Uçuş videoları ve resimleri (parça parça yükleme, boyut sınırı yok) ----------
# Cloudflare tüneli tek istekte ~100 MB'tan büyük gövdeyi kabul etmediğinden videolar istemcide
# parçalara bölünüp sırayla gönderilir; sunucu dosyanın sonuna ekler.
CHUNK_MAX = 64 * 1024 * 1024
_uploads = {}   # jeton → yükleme durumu (sunucu yeniden başlarsa yarım yüklemeler baştan alınır)


class VideoInit(BaseModel):
    file_name: str
    size: int


IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif'}


@router.post('/flights/{fid}/videos')
def video_init(fid: int, body: VideoInit, request: Request, user=Depends(field_user), conn=db.DB):
    """Uçuş videosu ya da resmi (parça parça yükleme). Video yalnızca yerel ağdan; resim her yerden."""
    require_flight_editor(user)
    flight = flight_row(conn, fid)
    if get_task(conn, flight['task_id'])['status'] in ('BASLANGIC', 'IPTAL'):
        raise HTTPException(400, 'Video ve resim, görev başladıktan sonra yüklenebilir')
    ext = Path(body.file_name).suffix.lower()
    if ext not in KINDS['videos'] | IMAGE_EXT:
        raise HTTPException(400, f'Desteklenmeyen dosya türü: {ext or "?"} (video ya da resim yükleyin)')
    if ext in KINDS['videos']:
        local_only(request)
    if body.size <= 0:
        raise HTTPException(400, 'Dosya boş')
    token = secrets.token_hex(16)
    folder = config.UPLOAD_DIR / 'videos'
    folder.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(12) + ext
    (folder / (name + '.part')).touch()
    _uploads[token] = {'flight_id': fid, 'user_id': user['id'], 'file_name': body.file_name[:200], 'size': body.size,
                       'received': 0, 'name': name}
    return {'upload_id': token, 'chunk_size': 16 * 1024 * 1024}


def _upload_state(token, user):
    st = _uploads.get(token)
    if not st or st['user_id'] != user['id']:
        raise HTTPException(404, 'Yükleme bulunamadı; baştan başlatın')
    return st


@router.put('/uploads/{token}')
async def video_chunk(token: str, offset: int, request: Request, user=Depends(field_user)):
    st = _upload_state(token, user)
    if offset != st['received']:
        raise HTTPException(409, f'Beklenen konum {st["received"]}')
    part = config.UPLOAD_DIR / 'videos' / (st['name'] + '.part')
    written = 0
    with open(part, 'ab') as f:
        async for chunk in request.stream():
            written += len(chunk)
            if written > CHUNK_MAX or st['received'] + written > st['size']:
                raise HTTPException(400, 'Parça boyutu hatalı')
            f.write(chunk)
    st['received'] += written
    return {'received': st['received']}


@router.delete('/uploads/{token}')
def video_cancel(token: str, user=Depends(field_user)):
    """Video yüklemesi iptal edildi: yarım dosya silinir."""
    st = _upload_state(token, user)
    (config.UPLOAD_DIR / 'videos' / (st['name'] + '.part')).unlink(missing_ok=True)
    _uploads.pop(token, None)
    return {'ok': True}


@router.post('/uploads/{token}/complete')
def video_complete(token: str, user=Depends(field_user), conn=db.DB):
    st = _upload_state(token, user)
    if st['received'] != st['size']:
        raise HTTPException(400, f'Yükleme eksik ({st["received"]}/{st["size"]} bayt)')
    folder = config.UPLOAD_DIR / 'videos'
    (folder / (st['name'] + '.part')).rename(folder / st['name'])
    _uploads.pop(token, None)
    cur = conn.execute(
        'INSERT INTO flight_videos (flight_id, file, file_name, size, uploaded_by, uploaded_at, kind) VALUES (?,?,?,?,?,?,?)',
        (st['flight_id'], f'videos/{st["name"]}', st['file_name'], st['size'], user['id'], db.now(),
         'RESIM' if Path(st['name']).suffix.lower() in IMAGE_EXT else 'VIDEO'))
    flight = flight_row(conn, st['flight_id'])
    db.audit(conn, user['id'], 'Uçuş resmi yükledi' if Path(st['name']).suffix.lower() in IMAGE_EXT else 'Uçuş videosu yükledi',
             'field_task', flight['task_id'],
             f'{st["file_name"]} ({st["size"] / 1048576:.0f} MB)')
    return {'id': cur.lastrowid}


@router.delete('/videos/{vid}')
def delete_video(vid: int, user=Depends(field_user), conn=db.DB):
    v = db.row(conn.execute('SELECT * FROM flight_videos WHERE id = ?', (vid,)))
    if not v:
        raise HTTPException(404, 'Video bulunamadı')
    if not (is_manager(user) or v['uploaded_by'] == user['id']):
        raise HTTPException(403, 'Videoyu yalnızca yükleyen kişi veya saha sorumlusu silebilir')
    (config.UPLOAD_DIR / v['file']).unlink(missing_ok=True)
    flight = flight_row(conn, v['flight_id'])
    conn.execute('DELETE FROM flight_videos WHERE id = ?', (vid,))
    db.audit(conn, user['id'], 'Uçuş videosu sildi', 'field_task', flight['task_id'], v['file_name'])
    return {'ok': True}
