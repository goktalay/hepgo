"""Güvenlik (fabrika girişi): gelen araçların plakası kaydedilir, çıkışta "çıkış yaptı" denir; giriş / çıkış kayıtları.
Güvenlik rolündeki kullanıcı yalnızca bu modülü görür. Parktaki araçlar Sekreterya'da misafir kaydına bağlanabilir."""
import json
import re
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/security')
security_user = auth.require_module('security')
admin_user = auth.require_module('admin')
BC_KEY = 'building_control'   # app_kv: {'times': ['HH:MM', ...]} günlük bina kontrol saatleri


class VehicleIn(BaseModel):
    plate: str
    note: Optional[str] = None


def norm_plate(p):
    """Plaka büyük harf, tek boşluklu (34 ABC 123); boşluksuz girilirse il kodu / harf / sayı arasına boşluk konur."""
    p = re.sub(r'\s+', ' ', (p or '').strip().upper().replace('İ', 'I').replace('-', ' '))
    compact = p.replace(' ', '')
    m = re.fullmatch(r'(\d{2})([A-Z]{1,3})(\d{2,5})', compact)
    return f'{m[1]} {m[2]} {m[3]}' if m else p


VEHICLE_SELECT = '''SELECT v.*, ue.full_name AS entered_by_name, ux.full_name AS exited_by_name,
       (SELECT g.code FROM guest_visit_vehicles gv JOIN guest_visits g ON g.id = gv.visit_id
        WHERE gv.vehicle_id = v.id ORDER BY g.id DESC LIMIT 1) AS visit_code
FROM vehicle_visits v LEFT JOIN users ue ON ue.id = v.entered_by LEFT JOIN users ux ON ux.id = v.exited_by'''


def parked(conn):
    return db.rows(conn.execute(VEHICLE_SELECT + ' WHERE v.exited_at IS NULL ORDER BY v.entered_at DESC, v.id DESC'))


@router.get('/vehicles')
def vehicles(user=Depends(security_user), conn=db.DB):
    return parked(conn)


@router.post('/vehicles')
def vehicle_in(body: VehicleIn, user=Depends(security_user), conn=db.DB):
    plate = norm_plate(body.plate)
    if len(plate.replace(' ', '')) < 4:
        raise HTTPException(400, 'Plakayı girin')
    if conn.execute('SELECT 1 FROM vehicle_visits WHERE plate = ? AND exited_at IS NULL', (plate,)).fetchone():
        raise HTTPException(400, f'{plate} zaten içeride (çıkış yapmamış)')
    cur = conn.execute('INSERT INTO vehicle_visits (plate, note, entered_at, entered_by) VALUES (?,?,?,?)',
                       (plate, (body.note or '').strip() or None, db.now(), user['id']))
    db.audit(conn, user['id'], 'Araç girişi', 'vehicle', cur.lastrowid, plate)
    return {'id': cur.lastrowid, 'plate': plate}


@router.post('/vehicles/{vid}/exit')
def vehicle_out(vid: int, user=Depends(security_user), conn=db.DB):
    v = db.row(conn.execute('SELECT * FROM vehicle_visits WHERE id = ?', (vid,)))
    if not v:
        raise HTTPException(404, 'Kayıt bulunamadı')
    if v['exited_at']:
        raise HTTPException(400, 'Bu araç zaten çıkış yapmış')
    conn.execute('UPDATE vehicle_visits SET exited_at = ?, exited_by = ? WHERE id = ?', (db.now(), user['id'], vid))
    db.audit(conn, user['id'], 'Araç çıkışı', 'vehicle', vid, v['plate'])
    return {'ok': True}


@router.put('/vehicles/{vid}')
def vehicle_edit(vid: int, body: VehicleIn, user=Depends(security_user), conn=db.DB):
    """Hatalı girilen plakayı/notu çıkış yapmadan düzeltir (yalnızca hâlâ içerideki araç)."""
    v = db.row(conn.execute('SELECT * FROM vehicle_visits WHERE id = ?', (vid,)))
    if not v:
        raise HTTPException(404, 'Kayıt bulunamadı')
    if v['exited_at']:
        raise HTTPException(400, 'Çıkış yapmış araç düzenlenemez')
    plate = norm_plate(body.plate)
    if len(plate.replace(' ', '')) < 4:
        raise HTTPException(400, 'Geçerli bir plaka girin')
    if conn.execute('SELECT 1 FROM vehicle_visits WHERE plate = ? AND exited_at IS NULL AND id != ?', (plate, vid)).fetchone():
        raise HTTPException(400, f'{plate} zaten içeride (çıkış yapmamış)')
    conn.execute('UPDATE vehicle_visits SET plate = ?, note = ? WHERE id = ?',
                 (plate, (body.note or '').strip() or None, vid))
    db.audit(conn, user['id'], 'Araç plakası düzeltildi', 'vehicle', vid, f"{v['plate']} → {plate}")
    return {'id': vid, 'plate': plate}


@router.get('/log')
def log(date_from: str = '', date_to: str = '', q: str = '', user=Depends(security_user), conn=db.DB):
    """Giriş / çıkış kayıtları (en yeni üstte); tarih aralığı giriş tarihine göre, en fazla 1000 kayıt."""
    where, args = ['1=1'], []
    if date_from:
        where.append('substr(v.entered_at, 1, 10) >= ?')
        args.append(date_from)
    if date_to:
        where.append('substr(v.entered_at, 1, 10) <= ?')
        args.append(date_to)
    if q.strip():
        where.append("replace(v.plate, ' ', '') LIKE ?")
        args.append(f"%{norm_plate(q).replace(' ', '')}%")
    return db.rows(conn.execute(VEHICLE_SELECT + f' WHERE {" AND ".join(where)} ORDER BY v.entered_at DESC, v.id DESC LIMIT 1000', args))


# ---------- Bina Kontrol: günlük bina turu (GPS rotası) ----------
def _bc_times(conn):
    r = conn.execute('SELECT v FROM app_kv WHERE k = ?', (BC_KEY,)).fetchone()
    try:
        return sorted(set(json.loads(r[0]).get('times', []))) if r else []
    except ValueError:
        return []


def _valid_day(s):
    try:
        return _date.fromisoformat((s or '')[:10]).isoformat()
    except (TypeError, ValueError):
        return _date.today().isoformat()


class StartIn(BaseModel):
    date: Optional[str] = None
    slot: Optional[str] = None


class PointIn(BaseModel):
    lat: float
    lng: float
    acc: Optional[float] = None


@router.get('/building')
def building_day(date: str = None, user=Depends(security_user), conn=db.DB):
    """Seçili günün bina kontrol turları: ayarlı saatler (bekliyor) + başlatılmış/bitmiş kayıtlar."""
    day = _valid_day(date)
    times = _bc_times(conn)
    rows = db.rows(conn.execute(
        '''SELECT c.*, u.full_name AS started_by_name,
                  (SELECT COUNT(*) FROM building_check_points p WHERE p.check_id = c.id) AS points,
                  (SELECT COUNT(*) FROM building_check_notes n WHERE n.check_id = c.id) AS notes
           FROM building_checks c LEFT JOIN users u ON u.id = c.started_by
           WHERE c.day = ? ORDER BY c.id''', (day,)))
    by_slot = {r['slot']: r for r in rows if r['slot']}
    out = []
    for t in times:   # ayarlı her saat için: kayıt varsa onu, yoksa "bekliyor"
        if t in by_slot:
            out.append(by_slot[t])
        else:
            out.append({'id': None, 'day': day, 'slot': t, 'status': 'BEKLIYOR', 'started_at': None, 'finished_at': None, 'points': 0, 'notes': 0})
    out += [r for r in rows if not r['slot']]   # saatsiz (elle başlatılan) turlar
    out.sort(key=lambda r: (r.get('slot') or '~', r.get('id') or 0))
    return {'date': day, 'times': times, 'checks': out}


@router.post('/building/start')
def building_start(body: StartIn, user=Depends(security_user), conn=db.DB):
    day = _valid_day(body.date)
    slot = (body.slot or '').strip()[:5] or None
    # Aynı anda yalnızca bir süren kontrol olabilir (hangi gün/saat olursa olsun)
    if db.row(conn.execute("SELECT id FROM building_checks WHERE status = 'DEVAM'")):
        raise HTTPException(400, 'Zaten süren bir bina kontrolü var; önce onu bitirin')
    if slot and db.row(conn.execute("SELECT id FROM building_checks WHERE day = ? AND slot = ? AND status != 'IPTAL'", (day, slot))):
        raise HTTPException(400, 'Bu saat için kontrol zaten başlatılmış')
    cur = conn.execute('INSERT INTO building_checks (day, slot, status, started_at, started_by) VALUES (?,?,?,?,?)',
                       (day, slot, 'DEVAM', db.now(), user['id']))
    db.audit(conn, user['id'], 'Bina kontrol turu başlattı', 'building_check', cur.lastrowid, slot or '')
    return {'id': cur.lastrowid}


@router.post('/building/{cid}/point')
def building_point(cid: int, body: PointIn, user=Depends(security_user), conn=db.DB):
    c = db.row(conn.execute('SELECT * FROM building_checks WHERE id = ?', (cid,)))
    if not c or c['status'] != 'DEVAM':
        raise HTTPException(400, 'Tur aktif değil')
    conn.execute('INSERT INTO building_check_points (check_id, lat, lng, acc, at) VALUES (?,?,?,?,?)',
                 (cid, body.lat, body.lng, body.acc, db.now()))
    return {'ok': True}


@router.post('/building/{cid}/finish')
def building_finish(cid: int, user=Depends(security_user), conn=db.DB):
    c = db.row(conn.execute('SELECT * FROM building_checks WHERE id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Tur bulunamadı')
    if c['status'] == 'DEVAM':
        conn.execute("UPDATE building_checks SET status = 'BITTI', finished_at = ? WHERE id = ?", (db.now(), cid))
        db.audit(conn, user['id'], 'Bina kontrol turu bitirdi', 'building_check', cid, c['slot'] or '')
    return {'ok': True}


@router.get('/building/{cid}/track')
def building_track(cid: int, user=Depends(security_user), conn=db.DB):
    c = db.row(conn.execute('SELECT c.*, u.full_name AS started_by_name FROM building_checks c LEFT JOIN users u ON u.id = c.started_by WHERE c.id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Tur bulunamadı')
    c['points'] = db.rows(conn.execute('SELECT lat, lng, acc, at FROM building_check_points WHERE check_id = ? ORDER BY id', (cid,)))
    return c


class BCNoteIn(BaseModel):
    note: str


@router.get('/building/{cid}/notes')
def building_notes(cid: int, user=Depends(security_user), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT n.id, n.note, n.created_at, u.full_name AS by_name FROM building_check_notes n
           LEFT JOIN users u ON u.id = n.created_by WHERE n.check_id = ? ORDER BY n.id DESC''', (cid,)))


@router.post('/building/{cid}/note')
def building_add_note(cid: int, body: BCNoteIn, user=Depends(security_user), conn=db.DB):
    if not db.row(conn.execute('SELECT id FROM building_checks WHERE id = ?', (cid,))):
        raise HTTPException(404, 'Tur bulunamadı')
    note = (body.note or '').strip()[:1000]
    if not note:
        raise HTTPException(400, 'Not girin')
    cur = conn.execute('INSERT INTO building_check_notes (check_id, note, created_by, created_at) VALUES (?,?,?,?)',
                       (cid, note, user['id'], db.now()))
    return {'id': cur.lastrowid}


@router.get('/building/config')
def building_config(user=Depends(security_user), conn=db.DB):
    return {'times': _bc_times(conn)}


class BCConfigIn(BaseModel):
    times: list[str] = []


@router.put('/building/config')
def building_config_set(body: BCConfigIn, user=Depends(admin_user), conn=db.DB):
    """Günlük bina kontrol saatlerini ayarla (yalnızca Sistem Yöneticisi)."""
    clean = []
    for t in body.times:
        t = (t or '').strip()
        if re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', t):
            clean.append(t)
    clean = sorted(set(clean))
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (BC_KEY, json.dumps({'times': clean})))
    return {'times': clean}
