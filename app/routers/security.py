"""Güvenlik (fabrika girişi): gelen araçların plakası kaydedilir, çıkışta "çıkış yaptı" denir; giriş / çıkış kayıtları.
Güvenlik rolündeki kullanıcı yalnızca bu modülü görür. Parktaki araçlar Sekreterya'da misafir kaydına bağlanabilir."""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/security')
security_user = auth.require_module('security')


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
