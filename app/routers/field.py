"""Saha Yönetimi: görevler ve alt modülleri (uçuşlar, masraflar, yol, görev yerleri).

Bir görev birden fazla uçak (sipariş) götürebilir; her uçak için bir uçuş (field_flights) açılır.
Görev bitip (başarılı/başarısız) tüm uçuşların uçuş raporu hazır olunca görev "Rapor Tamamlandı" olur.
"""
from datetime import datetime
from typing import Optional

import json
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, config, db, drone_hub, drone_mprelay, exitpass, transfers
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
OPEN = ('BASLANGIC', 'GOREVDE')                 # açık görev: uçak eklenir/kaldırılır, canlı uçuş yapılır
LINK_TYPES = ('serial', 'tcp', 'udp')           # uçuşun köprü → dron yerel bağlantı türü (field_flights.link.type)


class TaskIn(BaseModel):
    order_ids: list[int] = []      # üretimden gelen uçaklar (sipariş); order_ids VEYA drone_ids'ten en az biri dolu olmalı
    drone_ids: list[int] = []      # Dron Envanteri'nden dronlar (Dron Yönetimi paketi)
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
    """Uçuş düzenleme (tam değiştirme): fırlatma + not + BAĞLANTI (Dron Yönetimi Faz 1 — bağlantı dron kaydında değil uçuştadır).
    link: {type:'serial'|'tcp'|'udp', host?, port?, serial?, baud?}; serial → serial+baud, tcp/udp → host+port zorunlu."""
    launch: Optional[str] = None
    note: Optional[str] = None
    bridge_id: Optional[int] = None    # Dron Köprüleri'nden köprü
    sysid: Optional[int] = None        # MAVLink sistem kimliği 1..255
    link: Optional[dict] = None


class FlightAddIn(BaseModel):
    """Göreve sonradan uçak ekleme: order_id (üretimden gelen uçak) YA DA drone_id (Dron Envanteri) — tam biri."""
    order_id: Optional[int] = None
    drone_id: Optional[int] = None


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


class ExitGroupIn(BaseModel):
    plate: Optional[str] = None            # araç plakası (serbest metin, isteğe bağlı; boşsa "araçsız / kendi aracı")
    employee_ids: list[int] = []           # bu araçtaki yolcular (aktif personel)


class VehiclesExitIn(BaseModel):
    vehicles: list[ExitGroupIn] = []


class ExitReturnIn(BaseModel):
    at: Optional[str] = None               # şirkete dönüş saati (opsiyonel; verilmezse şu an)


class ExitCompleteIn(BaseModel):
    flew: bool = True                      # uçuş yapıldı mı? (Hayır ise açıklama zorunlu)
    note: Optional[str] = None             # görevi bitirme açıklaması (uçulmadıysa zorunlu)
    at: Optional[str] = None


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
                   d.code AS drone_code, d.name AS drone_name, d.model AS drone_model, d.status AS drone_status, d.protocol AS drone_protocol,
                   b.name AS bridge_name, b.status AS bridge_status,
                   l.id AS log_id, l.status AS log_status, l.file_name AS log_file, l.error AS log_error,
                   json_extract(l.analysis, '$.summary.flight_s') AS flight_s
            FROM field_flights f
            LEFT JOIN orders o ON o.id = f.order_id
            LEFT JOIN products p ON p.id = o.product_id
            LEFT JOIN drone_drones d ON d.id = f.drone_id
            LEFT JOIN drone_bridges b ON b.id = f.bridge_id
            LEFT JOIN flight_logs l ON l.id = (SELECT MAX(id) FROM flight_logs WHERE flight_id = f.id)
            WHERE f.task_id IN ({','.join('?' * len(task_ids))}) ORDER BY o.queue_no, d.code''', task_ids))
    videos = {}
    if rows:
        for v in db.rows(conn.execute(
                f'''SELECT v.id, v.flight_id, v.file, v.file_name, v.size, v.uploaded_at, v.uploaded_by, v.kind,
                           u.full_name AS uploaded_by_name
                    FROM flight_videos v LEFT JOIN users u ON u.id = v.uploaded_by
                    WHERE v.flight_id IN ({','.join('?' * len(rows))}) ORDER BY v.id''', [f['id'] for f in rows])):
            videos.setdefault(v['flight_id'], []).append(v)
    online = drone_hub.online_bridges()
    out = {}
    for f in rows:
        f['launch_text'] = LAUNCH_TEXT.get(f['launch'])
        f['videos'] = videos.get(f['id'], [])
        # Faz 1: bağlantı uçuş düzeyinde — köprü, sysid, link (parse edilmiş); sipariş uçakları MAVLink, dronlar kendi protokolü
        f['protocol'] = (f['drone_protocol'] or 'mavlink') if f['drone_id'] else 'mavlink'
        f['label'] = f['queue_no'] or f['order_code'] or f['drone_code']
        f['link'] = drone_hub.parse_link(f['link'])
        f['bridge_online'] = (f['bridge_id'] in online) if f['bridge_id'] is not None else (f['protocol'] == 'sanal' and -f['drone_id'] in drone_hub.SIMS)
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
        t['aircraft'] = ', '.join(f['queue_no'] or f['order_code'] or f['drone_code'] or '?' for f in t['flights'])
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
def list_tasks(date_from: str = '', date_to: str = '', user=Depends(field_user), conn=db.DB):
    """Görevler. Tarih aralığı: açık görevler (başlangıç / görevde) her zaman; diğerleri açıldığı ya da bittiği döneme göre."""
    if not (date_from or date_to):
        return _tasks(conn)
    c1, a1 = db.date_cond('t.created_at', date_from, date_to)
    c2, a2 = db.date_cond('t.finished_at', date_from, date_to)
    return _tasks(conn, f"(t.status IN ('BASLANGIC', 'GOREVDE') OR ({c1}) OR ({c2}))", (*a1, *a2))


@router.get('/tasks/{tid}')
def task_detail(tid: int, user=Depends(field_user), conn=db.DB):
    t = get_task(conn, tid)
    t['expenses'] = db.rows(conn.execute(
        '''SELECT e.*, u.full_name AS created_by_name, sp.full_name AS spent_by_name FROM field_expenses e
           LEFT JOIN users u ON u.id = e.created_by LEFT JOIN users sp ON sp.id = e.spent_by
           WHERE e.task_id = ? ORDER BY e.spent_on DESC, e.id DESC''', (tid,)))
    t['equipment'] = task_equipment(conn, tid)
    t['can'] = {
        'isg': is_manager(user) or user['id'] == t['lead_id'],   # İSG kontrolünü saha sorumlusu doldurur
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
    # Deposundan düşme kuralı: açık görevdeki (BASLANGIC/GOREVDE) uçak düşer; çoklu kullanım görev bitince döner;
    # tek kullanımlık uçak yalnızca UÇARSA tüketilir (uçunca HURDA olur). Görev bitti ama uçulmadıysa ("görevi bitir"
    # + flew=0, flew=1 yok) uçak deposda KALIR ve yeni göreve devredilir. carry_over: böyle devreden (uçulmamış) uçak.
    return db.rows(conn.execute(
        '''SELECT o.id, o.code, o.queue_no, o.status, o.note, o.completed_at, p.name AS product_name,
                  COALESCE(p.usage_type, 'TEK') AS usage_type,
                  (SELECT COUNT(*) FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                   WHERE f.order_id = o.id AND t.status != 'IPTAL') AS past_tasks,
                  EXISTS (SELECT 1 FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                          WHERE f.order_id = o.id AND t.status != 'IPTAL'
                            AND COALESCE(p.usage_type, 'TEK') != 'COKLU'
                            AND EXISTS (SELECT 1 FROM duty_requests dr WHERE dr.field_task_id = t.id AND dr.source = 'field' AND dr.flew = 0)
                            AND NOT EXISTS (SELECT 1 FROM duty_requests dr WHERE dr.field_task_id = t.id AND dr.source = 'field' AND dr.flew = 1)) AS carry_over
           FROM orders o LEFT JOIN products p ON p.id = o.product_id
           WHERE o.status IN ('TAMAMLANDI', 'MONTAJ') AND p.type = 'MAMUL' AND NOT EXISTS (
               SELECT 1 FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
               WHERE f.order_id = o.id AND t.status != 'IPTAL'
                 AND (t.status IN ('BASLANGIC', 'GOREVDE')
                      OR (COALESCE(p.usage_type, 'TEK') != 'COKLU'
                          AND NOT (EXISTS (SELECT 1 FROM duty_requests dr WHERE dr.field_task_id = t.id AND dr.source = 'field' AND dr.flew = 0)
                                   AND NOT EXISTS (SELECT 1 FROM duty_requests dr WHERE dr.field_task_id = t.id AND dr.source = 'field' AND dr.flew = 1)))))
           ORDER BY o.status = 'MONTAJ', o.queue_no, o.code'''))


def available_drones_rows(conn):
    """Göreve götürülebilecek dronlar (Dron Envanteri): aktif ve açık bir görevde (başlangıç / görevde) olmayanlar.
    protocol: mavlink | sanal | dji (bağlantı bilgisi dron kaydında tutulmaz; uçuşta seçilir)."""
    return db.rows(conn.execute(
        '''SELECT d.id, d.code, d.name, d.model, d.serial, d.status, d.note, d.protocol, pl.full_name AS pilot_name,
                  (SELECT COUNT(*) FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                   WHERE f.drone_id = d.id AND t.status != 'IPTAL') AS past_tasks
           FROM drone_drones d LEFT JOIN users pl ON pl.id = d.pilot_id
           WHERE d.status = 'AKTIF' AND NOT EXISTS (
               SELECT 1 FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
               WHERE f.drone_id = d.id AND t.status IN ('BASLANGIC', 'GOREVDE'))
           ORDER BY d.code'''))


@router.get('/available-drones')
def available_drones(user=Depends(field_manager), conn=db.DB):
    return available_drones_rows(conn)


@router.post('/tasks')
def create_task(body: TaskIn, user=Depends(field_manager), conn=db.DB):
    orders = sorted(set(body.order_ids))
    drones = sorted(set(body.drone_ids))
    if not orders and not drones:
        raise HTTPException(400, 'En az bir uçak ya da dron seçin')
    if orders:
        available = {r['id'] for r in available_aircraft(user, conn)}
        if any(o not in available for o in orders):
            raise HTTPException(400, 'Seçilen uçaklardan biri saha deposunda / montajda değil veya başka bir görevde')
    if drones:
        avail_d = {r['id'] for r in available_drones_rows(conn)}
        if any(d not in avail_d for d in drones):
            raise HTTPException(400, 'Seçilen dronlardan biri aktif değil veya başka bir görevde')
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
        if not auth.has_role_or_intern(conn, sid, auth.FIELD_STAFF):
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
    conn.executemany('INSERT INTO field_flights (task_id, drone_id, updated_at) VALUES (?,?,?)',
                     [(tid, d, db.now()) for d in drones])
    task_equipment(conn, tid)   # standart saha ekipman listesi göreve kopyalanır
    # Montaj aşamasında sahaya götürülen uçaklar görev açılınca "Sahada Montaj" aşamasına geçer
    if orders:
        conn.execute(f"""UPDATE orders SET status = 'SAHADA_MONTAJ' WHERE status = 'MONTAJ'
                         AND id IN ({','.join('?' * len(orders))})""", orders)
    parts = [f'{len(orders)} uçak' if orders else None, f'{len(drones)} dron' if drones else None]
    db.audit(conn, user['id'], 'Saha görevi oluşturdu', 'field_task', tid, f'{code} ({", ".join(p for p in parts if p)})')
    return {'id': tid, 'code': code}


@router.get('/tasks/{tid}/addable')
def task_addable(tid: int, user=Depends(field_manager), conn=db.DB):
    """Göreve SONRADAN eklenebilecekler: uçaklar (available-aircraft kuralı: saha deposu / montaj, başka açık görevde değil) ve
    Dron Envanteri'ndeki uygun dronlar; görevdeki mevcut uçuşlar hariç. Görev açık (başlangıç / görevde) değilse 400."""
    task = get_task(conn, tid)
    if task['status'] not in OPEN:
        raise HTTPException(400, 'Yalnız açık göreve (başlangıç / görevde) uçak eklenebilir')
    in_orders = {f['order_id'] for f in task['flights'] if f['order_id']}
    in_drones = {f['drone_id'] for f in task['flights'] if f['drone_id']}
    return {'orders': [r for r in available_aircraft(user, conn) if r['id'] not in in_orders],
            'drones': [r for r in available_drones_rows(conn) if r['id'] not in in_drones]}


@router.post('/tasks/{tid}/flights')
def add_task_flight(tid: int, body: FlightAddIn, user=Depends(field_manager), conn=db.DB):
    """Açık göreve uçak (order_id) YA DA dron (drone_id) ekler — tam biri; uygunluk listeleriyle doğrulanır.
    Montajdaki uçak göreve girince SAHADA_MONTAJ olur. Harekât ekranı izleyicileri yenilenir (drone_hub.task_changed)."""
    if bool(body.order_id) == bool(body.drone_id):
        raise HTTPException(400, 'Bir uçak YA DA bir dron seçin')
    avail = task_addable(tid, user, conn)
    task = get_task(conn, tid)
    if body.order_id:
        row = next((r for r in avail['orders'] if r['id'] == body.order_id), None)
        if not row:
            raise HTTPException(400, 'Seçilen uçak saha deposunda / montajda değil, bu görevde ya da başka bir görevde')
        cur = conn.execute('INSERT INTO field_flights (task_id, order_id, updated_at) VALUES (?,?,?)', (tid, body.order_id, db.now()))
        conn.execute("UPDATE orders SET status = 'SAHADA_MONTAJ' WHERE status = 'MONTAJ' AND id = ?", (body.order_id,))
        label = row['queue_no'] or row['code']
    else:
        row = next((r for r in avail['drones'] if r['id'] == body.drone_id), None)
        if not row:
            raise HTTPException(400, 'Seçilen dron aktif değil, bu görevde ya da başka bir görevde')
        cur = conn.execute('INSERT INTO field_flights (task_id, drone_id, updated_at) VALUES (?,?,?)', (tid, body.drone_id, db.now()))
        label = row['code']
    db.audit(conn, user['id'], 'Saha görevine uçak ekledi', 'field_flight', cur.lastrowid, f'{task["code"]} / {label}')
    conn.commit()   # canlı izleyici yenilemesi (olay döngüsünde ayrı bağlantıyla okur) yazılmış veriyi görsün
    drone_hub.task_changed(tid)
    return {'id': cur.lastrowid}


@router.delete('/flights/{fid}')
def delete_flight(fid: int, user=Depends(field_manager), conn=db.DB):
    """Açık görevden uçuş kaydını kaldırır: logu / videosu yoksa. Sipariş SAHADA_MONTAJ'a geçmişse geri alınmaz (yalnız kayıt
    silinir; notlar CASCADE). Görevin son uçuşu kaldırılamaz (görev en az bir uçakla açılır)."""
    f = flight_row(conn, fid)
    task = get_task(conn, f['task_id'])
    if task['status'] not in OPEN:
        raise HTTPException(400, 'Yalnız açık görevden (başlangıç / görevde) uçuş kaldırılabilir')
    if conn.execute('SELECT 1 FROM flight_logs WHERE flight_id = ?', (fid,)).fetchone() or \
            conn.execute('SELECT 1 FROM flight_videos WHERE flight_id = ?', (fid,)).fetchone():
        raise HTTPException(400, 'Uçuş logu ya da videosu olan uçuş kaldırılamaz')
    if len(task['flights']) <= 1:
        raise HTTPException(400, 'Görevin son uçuşu kaldırılamaz; görevi iptal edin')
    label = _flight_label(task, fid)
    conn.execute('DELETE FROM field_flights WHERE id = ?', (fid,))
    db.audit(conn, user['id'], 'Saha görevinden uçağı kaldırdı', 'field_flight', fid, f'{task["code"]} / {label}')
    conn.commit()
    drone_mprelay.close_threadsafe(fid, 'uçuş görevden kaldırıldı', user)
    drone_hub.task_changed(f['task_id'])
    return {'ok': True}


@router.get('/tasks/{tid}/live')
def task_live(tid: int, user=Depends(field_user), conn=db.DB):
    """Canlı Uçuş (harekât ekranı) görev bağlamı: görev {id, code, status, location_name, lat, lon (field_locations'ta konum
    sütunu yoksa null)} + uçuşlar {id, order_id, drone_id, label, name, protocol, sysid, bridge_id, bridge_name, bridge_online,
    link, sim_bridge_id} + can_command. Görev üyesi ya da saha yöneticisi; Canlı Uçuş (field.live) okuma izni gerekir."""
    t = get_task(conn, tid)
    if not drone_hub.can_read(user):
        raise HTTPException(403, 'Canlı Uçuş izniniz yok')
    if not (is_manager(user) or _member(t, user)):
        raise HTTPException(403, 'Bu görevin canlı uçuşunu yalnız görev üyeleri ve saha yöneticileri izleyebilir')
    task, flights = drone_hub.task_live(conn, tid)
    # tam ekran üst bandındaki görev tanımı için
    task.update(note=t.get('note'), lead_name=t.get('lead_name'), pilot_name=t.get('pilot_name'), location_name=t.get('location_name'))
    for f in flights:
        if f['sim_bridge_id'] is not None:
            f['bridge_online'] = f['sim_bridge_id'] in drone_hub.SIMS
    return {'task': task, 'flights': flights, 'can_command': drone_hub.can_command(user) if 'write_modules' in user else False}


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


def _flight_label(task, fid):
    f = next((x for x in task['flights'] if x['id'] == fid), None)
    return (f and f['label']) or f'#{fid}'


def _int(v):
    try:
        return int(v) if v is not None and str(v).strip() != '' else None
    except (TypeError, ValueError):
        return None


def _check_link(conn, body):
    """Uçuş bağlantı doğrulaması: köprü var mı, sysid 1..255, link türü ve zorunlu alanları. Saklanacak link JSON metnini
    (ya da None) döndürür."""
    if body.bridge_id is not None and not conn.execute('SELECT 1 FROM drone_bridges WHERE id = ?', (body.bridge_id,)).fetchone():
        raise HTTPException(400, 'Köprü bulunamadı')
    if body.sysid is not None and not 1 <= body.sysid <= 255:
        raise HTTPException(400, 'MAVLink sistem kimliği 1…255 olmalı')
    link = body.link
    if link is None:
        return None
    if not isinstance(link, dict):
        raise HTTPException(400, 'Bağlantı ayarı nesne olmalı')
    kind = str(link.get('type') or '').strip().lower()
    if kind not in LINK_TYPES:
        raise HTTPException(400, 'Bağlantı türü serial, tcp ya da udp olmalı')
    if body.bridge_id is None:
        raise HTTPException(400, 'Bağlantı ayarı için önce köprü seçin')
    out = {'type': kind}
    if kind == 'serial':
        serial, baud = str(link.get('serial') or '').strip()[:120], _int(link.get('baud'))
        if not serial or not baud or baud <= 0:
            raise HTTPException(400, 'Seri bağlantı için port adı ve baud gerekli')
        out.update(serial=serial, baud=baud)
    else:
        host, port = str(link.get('host') or '').strip()[:120], _int(link.get('port'))
        if not host or not port or not 1 <= port <= 65535:
            raise HTTPException(400, 'TCP/UDP bağlantısı için sunucu adresi ve port (1…65535) gerekli')
        out.update(host=host, port=port)
    return json.dumps(out, ensure_ascii=False)


@router.put('/flights/{fid}')
def update_flight(fid: int, body: FlightIn, user=Depends(field_user), conn=db.DB):
    """Uçuş bilgileri: fırlatma, not ve BAĞLANTI (köprü + sysid + link). Bağlantı alanları (bridge_id/sysid/link) gövdede HİÇ
    gönderilmezse mevcut değer korunur (Dron Köprüleri yetkisi olmayan pilot fırlatma/not kaydedince bağlantı silinmesin);
    açıkça null gönderilirse temizlenir."""
    require_flight_editor(user)
    f = flight_row(conn, fid)
    task = get_task(conn, f['task_id'])
    if task['status'] == 'IPTAL':
        raise HTTPException(400, 'İptal edilmiş görevin uçuşu düzenlenemez')
    if body.launch not in (None, *LAUNCH_TEXT):
        raise HTTPException(400, 'Geçersiz fırlatma sistemi')
    sent = body.model_fields_set
    if not ({'bridge_id', 'sysid', 'link'} & sent):
        body.bridge_id, body.sysid = f['bridge_id'], f['sysid']
        body.link = json.loads(f['link']) if f['link'] else None
    link = _check_link(conn, body)
    conn.execute('UPDATE field_flights SET launch = ?, note = ?, bridge_id = ?, sysid = ?, link = ?, updated_at = ? WHERE id = ?',
                 (body.launch, (body.note or '').strip() or None, body.bridge_id, body.sysid, link, db.now(), fid))
    bridge = conn.execute('SELECT name FROM drone_bridges WHERE id = ?', (body.bridge_id,)).fetchone() if body.bridge_id else None
    conn_txt = f' · köprü {bridge[0]}' + (f' · sysid {body.sysid}' if body.sysid else '') + (f' · {json.loads(link)["type"]}' if link else '') if bridge else ''
    db.audit(conn, user['id'], 'Uçuş bilgisini düzenledi', 'field_flight', fid,
             f'{task["code"]} / {_flight_label(task, fid)}: {LAUNCH_TEXT.get(body.launch, "fırlatma seçilmedi")}{conn_txt}')
    conn.commit()
    if (body.bridge_id, body.sysid) != (f['bridge_id'], f['sysid']):   # Mission Planner aktarımı eski köprü/sysid'e bağlıydı
        drone_mprelay.close_threadsafe(fid, 'uçuşun bağlantısı değişti', user)
    drone_hub.task_changed(f['task_id'])
    return {'ok': True}


# ---------- Canlı Uçuş › Mission Planner aktarımı (app/drone_mprelay.py; protokol v1.4 raw_up / cap 'mp_relay') ----------
class MpRelayIn(BaseModel):
    pair_sysid: Optional[int] = None       # isteğe bağlı eşleştirme: IP kilidi yalnız bu sysid'li GCS kalp atışıyla kurulur (MP varsayılanı 255)


def _mp_flight(fid, user, write):
    """Uçuş + görev bağlamı ve yetki: Canlı Uçuş okuma + görev üyesi / saha yöneticisi; açma/kapama/sıfırlama için ayrıca
    drone_mprelay.can_manage (komut yetkisi). Sanal dron ve köprüsüz uçuş için aktarım yok."""
    with db.connect() as conn:
        f = flight_row(conn, fid)
        t = get_task(conn, f['task_id'])
        if not drone_hub.can_read(user):
            raise HTTPException(403, 'Canlı Uçuş izniniz yok')
        if not (is_manager(user) or _member(t, user)):
            raise HTTPException(403, 'Bu görevin canlı uçuşunu yalnız görev üyeleri ve saha yöneticileri izleyebilir')
        if write and not drone_mprelay.can_manage(user):
            raise HTTPException(403, 'Mission Planner aktarımı için Canlı Uçuş komut yetkisi (Pilot) ya da Dron Yönetimi yazma izni gerekir')
        d = db.row(conn.execute('SELECT code, protocol FROM drone_drones WHERE id = ?', (f['drone_id'],))) if f['drone_id'] else None
    f['drone_code'] = (d or {}).get('code')
    f['protocol'] = (d or {}).get('protocol') or 'mavlink'
    f['task_status'] = t['status']
    f['task_code'] = t['code']
    return f


def _mp_status(f, request):
    from .drone import _req_host
    r = drone_mprelay.get(f['id'])
    b = drone_hub.BRIDGES.get(f['bridge_id']) if f['bridge_id'] else None
    base = {'flight_id': f['id'], 'task_id': f['task_id'], 'bridge_id': f['bridge_id'], 'sysid': f['sysid'], 'protocol': f['protocol'],
            'bridge_online': b is not None, 'bridge_ver': b.ver if b else None, 'bridge_platform': b.platform if b else None,
            'bridge_supported': drone_mprelay.bridge_supported(b) if b else None, 'update_hint': drone_mprelay.update_hint(),
            'min_versions': drone_mprelay.MIN_VERSIONS, 'host': drone_mprelay.PUBLIC_HOST or _req_host(request) or None,
            'port_range': [drone_mprelay.UDP_BASE, drone_mprelay.UDP_BASE + drone_mprelay.UDP_COUNT - 1], 'idle_timeout_s': drone_mprelay.IDLE_S,
            'available': f['protocol'] != 'sanal' and bool(f['bridge_id']) and f['task_status'] in drone_mprelay.OPEN_TASK}
    return {**base, **(r.info() if r else {'active': False})}


@router.get('/tasks/{tid}/mp-relays')
def mp_relays_of_task(tid: int, user=Depends(field_user), conn=db.DB):
    """Görevin açık Mission Planner aktarımları (harekât ekranı dron kartı rozeti; 3 sn'de bir sorgulanır)."""
    t = get_task(conn, tid)
    if not drone_hub.can_read(user):
        raise HTTPException(403, 'Canlı Uçuş izniniz yok')
    if not (is_manager(user) or _member(t, user)):
        raise HTTPException(403, 'Bu görevin canlı uçuşunu yalnız görev üyeleri ve saha yöneticileri izleyebilir')
    items = [r.info() for r in list(drone_mprelay.RELAYS.values()) if r.task_id == tid and not r.closed]
    return {'items': items, 'can_manage': drone_mprelay.can_manage(user)}


@router.get('/flights/{fid}/mp-relay')
async def mp_relay_status(fid: int, request: Request, user=Depends(auth.current_user)):
    f = await run_in_threadpool(_mp_flight, fid, user, False)
    return {**_mp_status(f, request), 'can_manage': drone_mprelay.can_manage(user)}


@router.post('/flights/{fid}/mp-relay')
async def mp_relay_open(fid: int, request: Request, body: Optional[MpRelayIn] = None, user=Depends(auth.current_user)):
    f = await run_in_threadpool(_mp_flight, fid, user, True)
    if f['protocol'] == 'sanal':
        raise HTTPException(400, 'Sanal dron için Mission Planner aktarımı yok (Uçuş Simülatörü kendi UDP bağlantısını verir)')
    if not f['bridge_id']:
        raise HTTPException(400, 'Uçuşa köprü atanmadı (Uçuş Yönetimi › Düzenle › Bağlantı)')
    if f['task_status'] not in drone_mprelay.OPEN_TASK:
        raise HTTPException(400, 'Görev açık değil (yalnız Başlangıç / Görevde)')
    st = _mp_status(f, request)
    try:
        await drone_mprelay.open_relay(f, user, body.pair_sysid if body else None, st['host'])
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {**_mp_status(f, request), 'can_manage': True}


@router.delete('/flights/{fid}/mp-relay')
async def mp_relay_close(fid: int, request: Request, user=Depends(auth.current_user)):
    f = await run_in_threadpool(_mp_flight, fid, user, True)
    drone_mprelay.close_relay(fid, f"kapatıldı: {user.get('full_name') or user.get('username')}", user)
    return {**_mp_status(f, request), 'can_manage': True}


@router.post('/flights/{fid}/mp-relay/reset-ip')
async def mp_relay_reset_ip(fid: int, request: Request, user=Depends(auth.current_user)):
    f = await run_in_threadpool(_mp_flight, fid, user, True)
    if drone_mprelay.reset_ip(fid, user) is None:
        raise HTTPException(404, 'Açık Mission Planner aktarımı yok')
    return {**_mp_status(f, request), 'can_manage': True}


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


# ---------- Saha görevi araç çıkışları (QR; ONAYSIZ) ----------
# Saha görevine giden personel de "Görevdeki Personel"de görünsün ve güvenlikte QR okutup çıkabilsin diye,
# araç bazında birer görev formu (duty_requests) satırı oluşturulur. Görev formundan FARKLI olarak onay GEREKMEZ:
# satır doğrudan ONAYLANDI açılır (decided_by = işlemi yapan). on_duty_now() / verify-pass duty_requests üzerinden
# çalıştığından bu gruplar otomatik olarak görevde listesine girer ve QR ile okutulabilir.

def _can_exit(task, user):
    """Saha görevi araç çıkış grubunu yöneten: saha sorumlusu/sistem yöneticisi ya da görevdeki bir kişi."""
    return is_manager(user) or _member(task, user)


def _exit_groups(conn, tid):
    """Bu görevin saha çıkış gruplarını (iptal edilmemiş) personelleri ve QR kodu (pass_token) ile döndürür."""
    from .hr import _duty_reqs
    return _duty_reqs(conn, "d.source = 'field' AND d.field_task_id = ? AND d.status != 'IPTAL'", (tid,))


@router.get('/tasks/{tid}/vehicles-exit')
def list_vehicle_exits(tid: int, user=Depends(field_user), conn=db.DB):
    """Görevin araç bazlı çıkış grupları (QR göstermek/yazdırmak için)."""
    task = get_task(conn, tid)
    if not _can_exit(task, user):
        raise HTTPException(403, 'Bu görevin çıkış gruplarını yalnızca görevdeki kişiler görebilir')
    return {'items': _exit_groups(conn, tid)}


@router.post('/tasks/{tid}/vehicles-exit')
def create_vehicle_exits(tid: int, body: VehiclesExitIn, user=Depends(field_user), conn=db.DB):
    """Araç bazlı çıkış grupları oluşturur: her araç için ONAYLI (onaysız/otomatik) bir görev formu + yolcuları.
    Güvenlikte QR okutulunca personel "şirket dışında" sayılır. Her çağrı yeni grup(lar) ekler."""
    task = get_task(conn, tid)
    if not _can_exit(task, user):
        raise HTTPException(403, 'Saha çıkış grubunu yalnızca görevdeki kişiler oluşturabilir')
    if task['status'] == 'IPTAL':
        raise HTTPException(400, 'İptal edilen göreve çıkış grubu eklenemez')
    groups = [g for g in (body.vehicles or []) if [i for i in g.employee_ids if i]]
    if not groups:
        raise HTTPException(400, 'En az bir araç için yolcu seçin')
    destination = task.get('location_name') or task['code']
    depart_at = task.get('started_at') or db.now()
    created = []
    for g in groups:
        ids = list(dict.fromkeys(i for i in g.employee_ids if i))   # tekrarları at
        emps = db.rows(conn.execute(
            f"SELECT id FROM employees WHERE status = 'AKTIF' AND id IN ({','.join('?' * len(ids))})", ids))
        if not emps:
            raise HTTPException(400, 'Araçta geçerli (aktif) personel yok')
        plate = (g.plate or '').strip().upper()[:40] or None
        did = conn.execute(
            '''INSERT INTO duty_requests (employee_id, requested_by, approver_id, destination, purpose, depart_at,
                                          return_at, vehicle_plate, status, decided_by, decided_at, source, field_task_id,
                                          created_at)
               VALUES (?,?,?,?,?,?,?,?,'ONAYLANDI',?,?,'field',?,?)''',
            (emps[0]['id'], user['id'], None, destination[:300], 'Saha görevi', depart_at, None, plate,
             user['id'], db.now(), tid, db.now())).lastrowid
        for e in emps:
            conn.execute('INSERT OR IGNORE INTO duty_people (duty_id, employee_id) VALUES (?,?)', (did, e['id']))
        created.append(did)
    db.audit(conn, user['id'], 'Saha görevi araç çıkışı oluşturdu', 'field_task', tid,
             f'{task["code"]}: {len(created)} araç')
    return {'items': _exit_groups(conn, tid)}


@router.delete('/vehicles-exit/{did}')
def delete_vehicle_exit(did: int, user=Depends(field_user), conn=db.DB):
    """Bir saha çıkış grubunu iptal eder (QR geçersiz olur). duty_people CASCADE ile silinmez; grup IPTAL olur."""
    r = db.row(conn.execute("SELECT * FROM duty_requests WHERE id = ? AND source = 'field'", (did,)))
    if not r or not r['field_task_id']:
        raise HTTPException(404, 'Çıkış grubu bulunamadı')
    task = get_task(conn, r['field_task_id'])
    if not _can_exit(task, user):
        raise HTTPException(403, 'Bu çıkış grubunu iptal etme yetkiniz yok')
    conn.execute("UPDATE duty_requests SET status = 'IPTAL', decided_at = ? WHERE id = ?", (db.now(), did))
    db.audit(conn, user['id'], 'Saha görevi araç çıkışını iptal etti', 'field_task', r['field_task_id'],
             f'{task["code"]}: {r["vehicle_plate"] or "araçsız"}')
    return {'ok': True}


def _exit_group_open(conn, did, user):
    """Dönüş/bitir işlemleri için aktif (ONAYLANDI, henüz dönmemiş) saha çıkış grubunu yetki denetimiyle getirir."""
    r = db.row(conn.execute("SELECT * FROM duty_requests WHERE id = ? AND source = 'field'", (did,)))
    if not r or not r['field_task_id']:
        raise HTTPException(404, 'Çıkış grubu bulunamadı')
    task = get_task(conn, r['field_task_id'])
    if not _can_exit(task, user):
        raise HTTPException(403, 'Bu grubun dönüşünü işaretleme yetkiniz yok')
    if r['status'] != 'ONAYLANDI':
        raise HTTPException(400, 'Bu grup aktif değil')
    if r['returned_at']:
        raise HTTPException(400, 'Bu grup zaten döndü / bitti')
    return r, task


@router.post('/vehicles-exit/{did}/return')
def return_vehicle_exit(did: int, body: ExitReturnIn, user=Depends(field_user), conn=db.DB):
    """Grup şirkete döndü: grubu "Görevde"den düşürür (returned_at) ve aracını güvenlik kaydında İÇERİ alır."""
    r, task = _exit_group_open(conn, did, user)
    at = (body.at or '').strip() or db.now()
    from .security import vehicle_enter
    plate = vehicle_enter(conn, r['vehicle_plate'], user['id'])
    conn.execute("UPDATE duty_requests SET returned_at = ?, return_kind = 'sirket' WHERE id = ?", (at, did))
    db.audit(conn, user['id'], 'Saha görevi dönüşü (şirkete)', 'field_task', r['field_task_id'],
             f'{task["code"]}: şirkete döndü · {r["vehicle_plate"] or "araçsız"}')
    return {'ok': True, 'kind': 'sirket', 'vehicle_plate': plate, 'vehicle_entered': bool(plate)}


@router.post('/vehicles-exit/{did}/complete')
def complete_vehicle_exit(did: int, body: ExitCompleteIn, user=Depends(field_user), conn=db.DB):
    """Görevi bitir: grubu tamamlar (returned_at) — araç İÇERİ ALINMAZ. "Uçuş yapıldı mı?" (flew) ve açıklama kaydedilir.
    Uçulmadıysa (flew=False) açıklama zorunludur. (Uçuş stoğu devri ileride bu veriyi kullanacak; burada sadece toplanır.)"""
    r, task = _exit_group_open(conn, did, user)
    note = (body.note or '').strip()[:1000]
    if not body.flew and not note:
        raise HTTPException(400, 'Uçuş yapılmadıysa bir açıklama girin')
    at = (body.at or '').strip() or db.now()
    conn.execute("UPDATE duty_requests SET returned_at = ?, return_kind = 'bitir', flew = ?, complete_note = ? WHERE id = ?",
                 (at, 1 if body.flew else 0, note or None, did))
    db.audit(conn, user['id'], 'Saha görevi grubunu bitirdi', 'field_task', r['field_task_id'],
             f'{task["code"]}: {"uçuldu" if body.flew else "uçulmadı"}{" · " + note if note else ""}')
    return {'ok': True, 'kind': 'bitir', 'flew': body.flew}


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
    if conn.execute('''SELECT 1 FROM vehicle_assignments WHERE vehicle_id = :v UNION ALL SELECT 1 FROM vehicle_expenses WHERE vehicle_id = :v
                       UNION ALL SELECT 1 FROM vehicle_docs WHERE vehicle_id = :v''', {'v': vid}).fetchone():
        raise HTTPException(400, 'Aracın Araç Yönetimi kayıtları (zimmet, gider, belge) var; pasife alabilirsiniz')
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
def list_flights(view: str = 'ready', date_from: str = '', date_to: str = '', user=Depends(field_user), conn=db.DB):
    """Uçuş Yönetimi: saha görevlerine eklenmiş uçaklar. ready: uçuşa hazır (saha deposunda, montajı bitmiş; görev
    başlangıç / görevde), flown: uçmuş (logu hazır ya da hurda), all: iptal edilmemiş görevlerdeki tümü."""
    where = {'ready': "(o.status = 'TAMAMLANDI' OR f.drone_id IS NOT NULL) AND t.status IN ('BASLANGIC', 'GOREVDE')",
             'flown': "(o.status = 'HURDA' OR l.status = 'TAMAM')",
             'all': "t.status != 'IPTAL'"}.get(view)
    if not where:
        raise HTTPException(400, 'Geçersiz görünüm')
    dargs = ()
    if view != 'ready' and (date_from or date_to):   # uçuşa hazırlar her zaman; uçmuş / tümü görevin başladığı döneme göre
        dc, dargs = db.date_cond('COALESCE(t.started_at, t.created_at)', date_from, date_to)
        where = f'{where} AND {dc}'
    return db.rows(conn.execute(
        f'''SELECT f.id, f.task_id, f.launch, o.id AS order_id, o.code AS order_code, o.queue_no, o.status AS order_status,
                   o.scrapped_at, p.name AS product_name, COALESCE(p.usage_type, 'TEK') AS usage_type,
                   f.drone_id, d.code AS drone_code, d.name AS drone_name, d.model AS drone_model,
                   t.code AS task_code, t.status AS task_status, t.started_at, loc.name AS location_name, pl.full_name AS pilot_name,
                   l.id AS log_id, l.status AS log_status, json_extract(l.analysis, '$.summary.flight_s') AS flight_s,
                   (SELECT COUNT(*) FROM flight_notes n WHERE n.flight_id = f.id) AS note_count,
                   (SELECT COUNT(*) FROM flight_videos v WHERE v.flight_id = f.id) AS media_count
            FROM field_flights f JOIN field_tasks t ON t.id = f.task_id LEFT JOIN orders o ON o.id = f.order_id
            LEFT JOIN products p ON p.id = o.product_id
            LEFT JOIN drone_drones d ON d.id = f.drone_id
            LEFT JOIN field_locations loc ON loc.id = t.location_id LEFT JOIN users pl ON pl.id = t.pilot_id
            LEFT JOIN flight_logs l ON l.id = (SELECT MAX(id) FROM flight_logs WHERE flight_id = f.id)
            WHERE t.status != 'IPTAL' AND {where}
            ORDER BY t.id DESC, o.queue_no, d.code''', tuple(dargs)))


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
    if order and order['status'] == 'HURDA':   # hurda uçağın malzemeleri değerlendirilmedi mi?
        from .mrp import pending_reviews
        order['material_pending'] = any(r['id'] == order['id'] for r in pending_reviews(conn))
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
    tid = transfers.register('up', user['id'], user.get('full_name'), body.file_name, body.size)   # Transfer İzleme
    _uploads[token] = {'flight_id': fid, 'user_id': user['id'], 'file_name': body.file_name[:200], 'size': body.size,
                       'received': 0, 'name': name, 'tid': tid}
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
    tid = st.get('tid')
    written = 0
    stopped = False
    with open(part, 'ab') as f:
        async for chunk in request.stream():
            if tid and transfers.is_canceled(tid):   # MASTER "Durdur": yarım dosyayı bırak, iptal et
                stopped = True
                break
            written += len(chunk)
            if written > CHUNK_MAX or st['received'] + written > st['size']:
                raise HTTPException(400, 'Parça boyutu hatalı')
            f.write(chunk)
            if tid:
                transfers.update(tid, st['received'] + written)
    if stopped:
        part.unlink(missing_ok=True)
        _uploads.pop(token, None)
        transfers.finish(tid)
        raise HTTPException(409, 'Durduruldu')
    st['received'] += written
    return {'received': st['received']}


@router.delete('/uploads/{token}')
def video_cancel(token: str, user=Depends(field_user)):
    """Video yüklemesi iptal edildi: yarım dosya silinir."""
    st = _upload_state(token, user)
    (config.UPLOAD_DIR / 'videos' / (st['name'] + '.part')).unlink(missing_ok=True)
    if st.get('tid'):
        transfers.finish(st['tid'])
    _uploads.pop(token, None)
    return {'ok': True}


@router.post('/uploads/{token}/complete')
def video_complete(token: str, user=Depends(field_user), conn=db.DB):
    st = _upload_state(token, user)
    if st['received'] != st['size']:
        raise HTTPException(400, f'Yükleme eksik ({st["received"]}/{st["size"]} bayt)')
    folder = config.UPLOAD_DIR / 'videos'
    (folder / (st['name'] + '.part')).rename(folder / st['name'])
    if st.get('tid'):
        transfers.finish(st['tid'])
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


# ---------- Modül Ayarları (Program Ayarları › Modül Ayarları › Saha Yönetimi) ----------
# Standart saha ekipman listesi: her yeni görevde göreve kopyalanır; saha yöneticisi göreve özel çıkarır / ekler / miktarını değiştirir.
# Görev tanımları: görev raporunda her rolün sahada üstlendiği işin açıklaması.
DUTIES_KEY = 'field.duties'
DUTY_DEFAULTS = {
    'lead': 'Görevin planlanması ve sahada yönetimi; ekip koordinasyonu, iş güvenliği, uçuş onayı, test sonucunun ve raporun onaylanması.',
    'pilot': 'Uçuş öncesi kontroller (hava aracı, batarya, kumanda, yer istasyonu), uçuşun icrası, uçuş logunun ve gözlemlerin kaydı.',
    'driver': 'Ekibin ve ekipmanın görev yerine güvenle taşınması, araç kontrolü, başlangıç / bitiş kilometresinin kaydı.',
    'staff': 'Ekipmanın yüklenmesi ve kurulumu, sahada montaj, fırlatma desteği, uçuş sonrası toplama ve kontroller.',
}
DUTY_TITLES = {'lead': 'Saha Sorumlusu', 'pilot': 'Pilot', 'driver': 'Şoför', 'staff': 'Saha Personeli'}


def _sysadmin(user):
    if not (user.get('master') or auth.ADMIN in user['roles']):
        raise HTTPException(403, 'Modül ayarları yalnızca sistem yöneticisine açıktır')


def duties(conn):
    import json
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (DUTIES_KEY,)).fetchone()
    try:
        saved = json.loads(row[0]) if row else {}
    except ValueError:
        saved = {}
    return {k: (saved.get(k) or v) for k, v in DUTY_DEFAULTS.items()}


EQ_PRODUCT = 'p.code AS product_code, p.type AS product_type'


def std_equipment(conn):
    return db.rows(conn.execute(f'''SELECT e.id, e.name, e.qty, e.unit, e.note, e.sort, e.product_id, {EQ_PRODUCT}
                                    FROM field_equipment e LEFT JOIN products p ON p.id = e.product_id ORDER BY e.sort, e.id'''))


def _stock_qty(conn, ids):
    """Ürünlerin toplam stoğu (malzeme hareketleri + yarı mamul / yedek parça hareketleri)."""
    if not ids:
        return {}
    q = ','.join('?' * len(ids))
    out = {}
    for t, col in (('material_moves', 'product_id'), ('spare_moves', 'spare_id')):
        for pid, n in conn.execute(f'SELECT {col}, SUM(qty) FROM {t} WHERE {col} IN ({q}) GROUP BY {col}', list(ids)):
            out[pid] = out.get(pid, 0) + (n or 0)
    return out


@router.get('/equipment-search')
def equipment_search(q: str = '', user=Depends(field_user), conn=db.DB):
    """Ekipman seçimi: stoktaki her şey (yedek parça, sarf, hammadde, yarı mamul, mamul — tip ayırmadan); kod, ad, barkod,
    marka / model, açıklama ve Mikro stok kodunda arar. En az 3 karakter; kısa parça kodları (R2, 09) tam eşleşmeyle 2 karakterde de bulunur."""
    q = q.strip()
    if len(q) < 2:
        return []
    # Türkçe büyük / küçük harf (İ-i, I-ı, Ş-ş…) SQLite LIKE'ta eşleşmediği için süzme Python'da
    tr = str.maketrans('İIŞĞÜÖÇ', 'iışğüöç')
    low = lambda s: (s or '').translate(tr).lower()
    k = low(q)
    hits = []
    mikro = {}
    for pid, mc in conn.execute("SELECT local_id, mikro_code FROM mikro_links WHERE kind = 'stok'"):
        mikro[pid] = mc
    for r in db.rows(conn.execute('SELECT id, code, name, type, unit, brand, model, barcode, description, schema FROM products WHERE active = 1')):
        code = low(r['code'])
        if len(k) < 3 and code != k:   # 2 karakter: yalnızca kod tam eşleşmesi
            continue
        hay = ' '.join(low(r[f]) for f in ('code', 'name', 'barcode', 'brand', 'model', 'description')) + ' ' + low(mikro.get(r['id']))
        if k in hay:
            hits.append((code != k, not code.startswith(k), not low(r['name']).startswith(k), low(r['name']), r))
    rows = [x[4] for x in sorted(hits, key=lambda x: x[:4])[:50]]
    for r in rows:
        sch = r.pop('schema') or ''
        r['kind'] = 'YEDEK_PARCA' if sch.startswith(('part-', 'spare-')) else r['type']
        r['mikro_code'] = mikro.get(r['id'])
        for f in ('barcode', 'description'):
            r.pop(f, None)
    st = _stock_qty(conn, [r['id'] for r in rows])
    for r in rows:
        r['stock'] = st.get(r['id'], 0)
    return rows


def _product(conn, pid):
    if not pid:
        return None
    p = db.row(conn.execute('SELECT id, code, name, unit FROM products WHERE id = ?', (pid,)))
    if not p:
        raise HTTPException(400, 'Seçilen ürün stokta bulunamadı')
    return p


class EquipIn(BaseModel):
    id: Optional[int] = None
    product_id: Optional[int] = None
    name: str
    qty: float = 1
    unit: Optional[str] = None
    note: Optional[str] = None


class FieldSettingsIn(BaseModel):
    equipment: list[EquipIn] = []
    duties: dict = {}


@router.get('/settings')
def get_settings(user=Depends(auth.current_user), conn=db.DB):
    _sysadmin(user)
    return {'equipment': std_equipment(conn), 'duties': duties(conn), 'duty_titles': DUTY_TITLES, 'duty_defaults': DUTY_DEFAULTS}


@router.put('/settings')
def put_settings(body: FieldSettingsIn, user=Depends(auth.current_user), conn=db.DB):
    import json
    _sysadmin(user)
    now = db.now()
    keep = []
    for i, e in enumerate(body.equipment):
        name = (e.name or '').strip()[:120]
        if not name:
            continue
        qty = max(0.0, float(e.qty or 0))
        prod = _product(conn, e.product_id)
        if prod:
            name = prod['name'][:120]
        if e.id and conn.execute('SELECT 1 FROM field_equipment WHERE id = ?', (e.id,)).fetchone():
            conn.execute('UPDATE field_equipment SET name = ?, qty = ?, unit = ?, note = ?, sort = ?, product_id = ? WHERE id = ?',
                         (name, qty, (e.unit or '').strip()[:20] or None, (e.note or '').strip()[:200] or None, i, e.product_id or None, e.id))
            keep.append(e.id)
        else:
            if not prod:
                raise HTTPException(400, f'“{name}”: yeni ekipman stoktaki ürünlerden seçilmeli')
            keep.append(conn.execute('INSERT INTO field_equipment (name, qty, unit, note, sort, created_at, product_id) VALUES (?,?,?,?,?,?,?)',
                                     (name, qty, (e.unit or '').strip()[:20] or None, (e.note or '').strip()[:200] or None, i, now, prod['id'])).lastrowid)
    conn.execute(f"DELETE FROM field_equipment WHERE id NOT IN ({','.join('?' * len(keep)) or 'NULL'})", keep)
    d = {k: (str(body.duties.get(k) or '').strip()[:1000] or DUTY_DEFAULTS[k]) for k in DUTY_DEFAULTS}
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (DUTIES_KEY, json.dumps(d, ensure_ascii=False)))
    db.audit(conn, user['id'], 'Saha modül ayarlarını güncelledi', 'settings', None, f'{len(keep)} standart ekipman')
    return get_settings(user, conn)


# ---------- Göreve özel ekipman listesi ----------
def task_equipment(conn, tid):
    """Görevin ekipman listesi; görev için henüz oluşturulmadıysa standart listeden kopyalanır."""
    if not conn.execute('SELECT equip_init FROM field_tasks WHERE id = ?', (tid,)).fetchone()[0]:
        now = db.now()
        conn.executemany('INSERT INTO field_task_equipment (task_id, name, qty, unit, note, std_id, sort, created_at, product_id) VALUES (?,?,?,?,?,?,?,?,?)',
                         [(tid, e['name'], e['qty'], e['unit'], e['note'], e['id'], e['sort'], now, e['product_id']) for e in std_equipment(conn)])
        conn.execute('UPDATE field_tasks SET equip_init = 1 WHERE id = ?', (tid,))
    return db.rows(conn.execute(f'''SELECT e.id, e.name, e.qty, e.unit, e.note, e.std_id, e.product_id, {EQ_PRODUCT}
                                    FROM field_task_equipment e LEFT JOIN products p ON p.id = e.product_id
                                    WHERE e.task_id = ? ORDER BY e.sort, e.id''', (tid,)))


class TaskEquipIn(BaseModel):
    product_id: Optional[int] = None
    name: Optional[str] = None
    qty: Optional[float] = None
    unit: Optional[str] = None
    note: Optional[str] = None


@router.get('/tasks/{tid}/equipment')
def get_task_equipment(tid: int, user=Depends(field_user), conn=db.DB):
    get_task(conn, tid)
    return task_equipment(conn, tid)


@router.post('/tasks/{tid}/equipment')
def add_task_equipment(tid: int, body: TaskEquipIn, user=Depends(field_manager), conn=db.DB):
    t = get_task(conn, tid)
    task_equipment(conn, tid)
    prod = _product(conn, body.product_id)
    if not prod:
        raise HTTPException(400, 'Ekipmanı stoktaki ürünlerden seçin')
    name = prod['name'][:120]
    top = conn.execute('SELECT COALESCE(MAX(sort), 0) + 1 FROM field_task_equipment WHERE task_id = ?', (tid,)).fetchone()[0]
    conn.execute('INSERT INTO field_task_equipment (task_id, name, qty, unit, note, sort, created_at, product_id) VALUES (?,?,?,?,?,?,?,?)',
                 (tid, name, max(0.0, float(body.qty or 1)), (body.unit or prod['unit'] or '').strip()[:20] or None,
                  (body.note or '').strip()[:200] or None, top, db.now(), prod['id']))
    db.audit(conn, user['id'], 'Görev ekipmanı ekledi', 'field_task', tid, f'{t["code"]}: {name}')
    return task_equipment(conn, tid)


@router.put('/tasks/{tid}/equipment/{eid}')
def edit_task_equipment(tid: int, eid: int, body: TaskEquipIn, user=Depends(field_manager), conn=db.DB):
    r = db.row(conn.execute('SELECT * FROM field_task_equipment WHERE id = ? AND task_id = ?', (eid, tid)))
    if not r:
        raise HTTPException(404, 'Ekipman bulunamadı')
    conn.execute('UPDATE field_task_equipment SET name = ?, qty = ?, unit = ?, note = ? WHERE id = ?',
                 ((body.name or r['name']).strip()[:120], max(0.0, float(body.qty if body.qty is not None else r['qty'])),
                  r['unit'] if body.unit is None else (body.unit.strip()[:20] or None),
                  r['note'] if body.note is None else (body.note.strip()[:200] or None), eid))
    return task_equipment(conn, tid)


@router.delete('/tasks/{tid}/equipment/{eid}')
def delete_task_equipment(tid: int, eid: int, user=Depends(field_manager), conn=db.DB):
    r = db.row(conn.execute('SELECT name FROM field_task_equipment WHERE id = ? AND task_id = ?', (eid, tid)))
    if not r:
        raise HTTPException(404, 'Ekipman bulunamadı')
    conn.execute('DELETE FROM field_task_equipment WHERE id = ?', (eid,))
    db.audit(conn, user['id'], 'Görev ekipmanını çıkardı', 'field_task', tid, r['name'])
    return task_equipment(conn, tid)


@router.post('/tasks/{tid}/equipment/reset')
def reset_task_equipment(tid: int, user=Depends(field_manager), conn=db.DB):
    """Göreve özel değişiklikleri atıp standart listeyi yeniden yükler."""
    get_task(conn, tid)
    conn.execute('DELETE FROM field_task_equipment WHERE task_id = ?', (tid,))
    conn.execute('UPDATE field_tasks SET equip_init = 0 WHERE id = ?', (tid,))
    return task_equipment(conn, tid)


# ---------- Görevin İSG kontrolü: kişilerin KKD maddeleri için Yaptı / Yapmadı (saha sorumlusu doldurur)
def _task_crew(t):
    """Görevdeki kişiler (sırayla, tekrarsız): [(user_id, ad, [roller])]."""
    out = {}
    def add(uid, name, role):
        if uid:
            out.setdefault(uid, [name, []])
            if role not in out[uid][1]:
                out[uid][1].append(role)
    add(t['lead_id'], t['lead_name'], 'Saha Sorumlusu')
    add(t['pilot_id'], t['pilot_name'], 'Pilot')
    if t['driver_id']:
        add(t['driver_id'], t['driver_name'], 'Şoför')
    for v in t['vehicles']:
        add(v['driver_id'], v['driver_name'], 'Şoför')
    for s in t['staff']:
        add(s['id'], s['full_name'], 'Saha Personeli')
    return [(uid, n, roles) for uid, (n, roles) in out.items()]


def task_isg(conn, t):
    """Kişi başına: uçuş ekibi pozisyonu, acil durum görevi, KKD listesi (İK'dan) + bu görevdeki Yaptı / Yapmadı işaretleri,
    süresi dolmuş / alınmamış eğitimler."""
    today = db.now()[:10]
    checks = {(r['user_id'], r['item']): r for r in db.rows(conn.execute(
        'SELECT c.*, u.full_name AS checked_by_name FROM field_task_isg c LEFT JOIN users u ON u.id = c.checked_by WHERE c.task_id = ?', (t['id'],)))}
    out = []
    for uid, name, roles in _task_crew(t):
        e = db.row(conn.execute('SELECT id, flight_position, emergency_duty FROM employees WHERE user_id = ?', (uid,)))
        ppe = db.rows(conn.execute('SELECT name, usage FROM employee_ppe WHERE employee_id = ? ORDER BY sort, id', (e['id'],))) if e else []
        tr = db.rows(conn.execute('SELECT name, done_at, valid_until FROM employee_trainings WHERE employee_id = ? ORDER BY sort, id', (e['id'],))) if e else []
        for p in ppe:
            c = checks.get((uid, p['name'])) or {}
            p.update(status=c.get('status'), note=c.get('note'), checked_by_name=c.get('checked_by_name'), checked_at=c.get('checked_at'))
        out.append({'user_id': uid, 'name': name, 'roles': roles, 'position': e and e['flight_position'], 'emergency': e and e['emergency_duty'],
                    'ppe': ppe, 'trainings_missing': [x['name'] for x in tr if not x['done_at']],
                    'trainings_expired': [x['name'] for x in tr if x['valid_until'] and x['valid_until'] < today]})
    return out


class IsgCheckIn(BaseModel):
    user_id: int
    item: str
    status: Optional[str] = None   # YAPTI | YAPMADI | None (temizle)
    note: Optional[str] = None


@router.get('/tasks/{tid}/isg')
def get_task_isg(tid: int, user=Depends(field_user), conn=db.DB):
    return task_isg(conn, get_task(conn, tid))


@router.put('/tasks/{tid}/isg')
def set_task_isg(tid: int, body: IsgCheckIn, user=Depends(field_user), conn=db.DB):
    t = get_task(conn, tid)
    if not (is_manager(user) or user['id'] == t['lead_id']):
        raise HTTPException(403, 'İSG kontrolünü saha sorumlusu doldurur')
    if body.status not in (None, 'YAPTI', 'YAPMADI'):
        raise HTTPException(400, 'Geçersiz durum')
    if body.user_id not in {u for u, *_ in _task_crew(t)}:
        raise HTTPException(400, 'Kişi bu görevde değil')
    item = (body.item or '').strip()[:200]
    if not item:
        raise HTTPException(400, 'Madde boş')
    if body.status is None and not (body.note or '').strip():
        conn.execute('DELETE FROM field_task_isg WHERE task_id = ? AND user_id = ? AND item = ?', (tid, body.user_id, item))
    else:
        conn.execute('''INSERT INTO field_task_isg (task_id, user_id, item, status, note, checked_by, checked_at) VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(task_id, user_id, item) DO UPDATE SET status = excluded.status, note = excluded.note,
                        checked_by = excluded.checked_by, checked_at = excluded.checked_at''',
                     (tid, body.user_id, item, body.status, (body.note or '').strip()[:300] or None, user['id'], db.now()))
    return task_isg(conn, t)


# ---------- Görev raporu (yazdırılabilir): adım adım akış, görev tanımları, ekipman, uçuş raporları ----------
STEP_TEXT = {
    'Saha görevi oluşturdu': 'Görev oluşturuldu',
    'Saha görevini başlattı': 'Sahaya çıkış — görev başlatıldı',
    'Saha görevini bitirdi': 'Görev tamamlandı',
    'Saha görevini iptal etti': 'Görev iptal edildi',
    'Uçuş bilgisini düzenledi': 'Uçuş bilgisi girildi (fırlatma sistemi / not)',
    'Göreve araç ekledi': 'Göreve araç atandı',
    'Araç yol bilgisini girdi': 'Araç kilometre bilgisi girildi',
    'Yol bilgisini girdi': 'Görev yeri / yol bilgisi girildi',
    'Görevden aracı çıkardı': 'Araç görevden çıkarıldı',
    'Görev masrafı ekledi': 'Masraf girildi',
    'Görev masrafı sildi': 'Masraf silindi',
    'Uçuş notu ekledi': 'Uçuş notu eklendi',
    'Uçuş resmi yükledi': 'Uçuş fotoğrafı yüklendi',
    'Uçuş videosu yükledi': 'Uçuş videosu yüklendi',
    'Uçuş videosu sildi': 'Uçuş videosu silindi',
    'Görev ekipmanı ekledi': 'Göreve ekipman eklendi',
    'Görev ekipmanını çıkardı': 'Görevden ekipman çıkarıldı',
}


@router.get('/tasks/{tid}/report')
def task_report(tid: int, user=Depends(field_user), conn=db.DB):
    import json
    t = task_detail(tid, user, conn)
    fids = [f['id'] for f in t['flights']]
    fmarks = ','.join('?' * len(fids)) or 'NULL'
    audits = db.rows(conn.execute(
        f'''SELECT a.action, a.detail, a.at, a.user_id, u.full_name FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id
            WHERE (a.entity = 'field_task' AND a.entity_id = ?) OR (a.entity = 'field_flight' AND a.entity_id IN ({fmarks}))
            ORDER BY a.at, a.id''', (str(tid), *[str(f) for f in fids])))
    steps = [{'at': a['at'], 'who': a['full_name'], 'user_id': a['user_id'], 'text': STEP_TEXT.get(a['action'], a['action']), 'detail': a['detail']}
             for a in audits]
    have = {s['text'] for s in steps}
    # Eski görevlerde kayıt günlüğü eksik olabilir: görev zamanlarından tamamla
    if 'Görev oluşturuldu' not in have:
        steps.append({'at': t['created_at'], 'who': t['created_by_name'], 'user_id': t['created_by'], 'text': 'Görev oluşturuldu', 'detail': t['code']})
    if t['started_at'] and 'Sahaya çıkış — görev başlatıldı' not in have:
        steps.append({'at': t['started_at'], 'who': t['lead_name'], 'user_id': t['lead_id'], 'text': 'Sahaya çıkış — görev başlatıldı', 'detail': None})
    if t['finished_at'] and 'Görev tamamlandı' not in have:
        steps.append({'at': t['finished_at'], 'who': t['lead_name'], 'user_id': t['lead_id'], 'text': 'Görev tamamlandı',
                      'detail': 'Başarılı' if t['result'] == 'BASARILI' else 'Başarısız'})
    logs = db.rows(conn.execute(
        f'''SELECT l.*, u.full_name AS uploaded_by_name, o.code AS order_code, o.queue_no FROM flight_logs l
            LEFT JOIN users u ON u.id = l.uploaded_by LEFT JOIN field_flights f ON f.id = l.flight_id LEFT JOIN orders o ON o.id = f.order_id
            WHERE l.flight_id IN ({fmarks}) ORDER BY l.id''', fids)) if fids else []
    for l in logs:
        ac = l['queue_no'] or l['order_code'] or ''
        steps.append({'at': l['uploaded_at'], 'who': l['uploaded_by_name'], 'user_id': l['uploaded_by'], 'text': 'Uçuş logu yüklendi', 'detail': f'{ac} · {l["file_name"]}'})
        if l['analyzed_at'] and l['status'] == 'TAMAM':
            steps.append({'at': l['analyzed_at'], 'who': 'Sistem', 'user_id': None, 'text': 'Uçuş raporu hazırlandı (log analizi)', 'detail': ac})
            if l['analysis']:
                try:
                    s = json.loads(l['analysis']).get('summary') or {}
                    for key, label in (('takeoff_utc', 'Kalkış'), ('landing_utc', 'İniş')):
                        if s.get(key):
                            at = datetime.fromisoformat(s[key]).astimezone().replace(tzinfo=None).isoformat(timespec='seconds')
                            steps.append({'at': at, 'who': t['pilot_name'], 'user_id': t['pilot_id'], 'text': f'{label} (test uçuşu)', 'detail': ac})
                except (ValueError, TypeError):
                    pass
    if t['report_at']:
        steps.append({'at': t['report_at'], 'who': 'Sistem', 'user_id': None, 'text': 'Tüm uçuş raporları hazır — rapor tamamlandı', 'detail': None})
    START, FINISH = 'Sahaya çıkış — görev başlatıldı', 'Görev tamamlandı'
    prio = {'Görev oluşturuldu': 0, START: 1, FINISH: 3}   # aynı saniyedeki adımlar mantıklı sırada
    steps.sort(key=lambda s: (s['at'] or '', prio.get(s['text'], 2)))
    # Aşama: sahaya çıkış adımından önce Hazırlık, görev bitişinden sonra Rapor, arası Saha
    i_start = next((i for i, s in enumerate(steps) if s['text'] == START), None)
    i_end = next((i for i, s in enumerate(steps) if s['text'] in (FINISH, 'Görev iptal edildi')), None)
    for i, s in enumerate(steps):
        s['phase'] = ('Hazırlık' if i_start is None or i < i_start else 'Rapor' if i_end is not None and i > i_end else 'Saha')
    # Görev tanımları: kişi → roller + rol açıklaması + yaptığı işlemler
    d = duties(conn)
    people = {}

    def add(uid, name, role, extra=None):
        if not uid:
            return
        p = people.setdefault(uid, {'user_id': uid, 'full_name': name, 'roles': [], 'duties': [], 'actions': 0})
        title = DUTY_TITLES[role] + (f' ({extra})' if extra else '')
        if title not in p['roles']:
            p['roles'].append(title)
            p['duties'].append(d[role])
    add(t['lead_id'], t['lead_name'], 'lead')
    add(t['pilot_id'], t['pilot_name'], 'pilot')
    if t['driver_id']:
        add(t['driver_id'], t['driver_name'], 'driver')
    for v in t['vehicles']:
        add(v['driver_id'], v['driver_name'], 'driver', v['plate'])
    for s in t['staff']:
        add(s['id'], s['full_name'], 'staff')
    for s in steps:
        if s['user_id'] in people:
            people[s['user_id']]['actions'] += 1
    # Görev tanımı: İnsan Kaynakları'ndaki kişisel görev tanımı (yalnızca Genel / Kurum İçi maddeler); yoksa rol açıklaması
    from .hr import shareable_duties
    hr = shareable_duties(conn, list(people))
    for uid, p in people.items():
        if hr.get(uid):
            p['duties'], p['duty_source'] = hr[uid], 'hr'
        else:
            p['duty_source'] = 'role'
    # Uçuş raporları
    reports = []
    for f in t['flights']:
        lg = next((l for l in reversed(logs) if l['flight_id'] == f['id'] and l['status'] == 'TAMAM'), None)
        an = {}
        if lg and lg['analysis']:
            try:
                an = json.loads(lg['analysis'])
            except ValueError:
                an = {}
        reports.append({'flight': {k: f.get(k) for k in ('id', 'order_code', 'queue_no', 'product_name', 'product_serial', 'launch_text', 'note', 'flight_s')},
                        'log': {'file_name': lg['file_name'], 'uploaded_by_name': lg['uploaded_by_name'], 'analyzed_at': lg['analyzed_at']} if lg else None,
                        'summary': an.get('summary') or {}, 'findings': an.get('findings') or [],
                        'notes': _flight_notes(conn, f['id']), 'videos': len(f['videos'])})
    return {'task': t, 'steps': steps, 'people': list(people.values()), 'equipment': task_equipment(conn, tid), 'reports': reports,
            'isg': task_isg(conn, t)}
