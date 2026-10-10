"""Hizmetler (esnaf · berber/kuaför): hizmet adı + ücret + ortalama süre + hizmeti verebilen personel(ler)
+ personelin alacağı yüzde. Rezervasyon ve Esnaf Kasa bu hizmetleri kullanır.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/services')


def svc_user(user=Depends(auth.current_user)):
    if 'services' not in user['modules']:
        raise HTTPException(403, 'Hizmetler modülü bu firmada kapalı')
    return user


def _staff(conn, sid):
    return [r['user_id'] for r in db.rows(conn.execute(
        'SELECT user_id FROM shop_service_staff WHERE service_id = ?', (sid,)))]


@router.get('')
def list_services(user=Depends(svc_user), conn=db.DB):
    rows = db.rows(conn.execute('SELECT * FROM shop_services WHERE active = 1 ORDER BY sort, name'))
    # personel adlarını tek sorguda topla
    links = db.rows(conn.execute(
        '''SELECT ss.service_id, ss.user_id, u.full_name FROM shop_service_staff ss
           JOIN users u ON u.id = ss.user_id WHERE u.deleted_at IS NULL'''))
    by_svc = {}
    for lk in links:
        by_svc.setdefault(lk['service_id'], []).append({'id': lk['user_id'], 'name': lk['full_name']})
    for r in rows:
        r['staff'] = by_svc.get(r['id'], [])
        r['staff_ids'] = [s['id'] for s in r['staff']]
    return rows


class ServiceIn(BaseModel):
    name: str
    price: float = 0
    duration_min: int = 30
    staff_pct: float = 0
    staff_ids: list[int] = []


def _set_staff(conn, sid, ids):
    conn.execute('DELETE FROM shop_service_staff WHERE service_id = ?', (sid,))
    for uid in set(ids or []):
        conn.execute('INSERT OR IGNORE INTO shop_service_staff (service_id, user_id) VALUES (?,?)', (sid, uid))


@router.post('')
def add_service(body: ServiceIn, user=Depends(svc_user), conn=db.DB):
    name = (body.name or '').strip()[:120]
    if not name:
        raise HTTPException(400, 'Hizmet adı gerekli')
    srt = conn.execute('SELECT COALESCE(MAX(sort), 0) + 1 FROM shop_services').fetchone()[0]
    sid = conn.execute(
        'INSERT INTO shop_services (name, price, duration_min, staff_pct, sort, created_at) VALUES (?,?,?,?,?,?)',
        (name, round(body.price or 0, 2), max(5, int(body.duration_min or 30)),
         max(0.0, min(100.0, body.staff_pct or 0)), srt, db.now())).lastrowid
    _set_staff(conn, sid, body.staff_ids)
    conn.commit()
    db.audit(conn, user['id'], 'Hizmet ekledi', 'shop_service', sid, name)
    return {'id': sid}


@router.put('/{sid}')
def edit_service(sid: int, body: ServiceIn, user=Depends(svc_user), conn=db.DB):
    name = (body.name or '').strip()[:120]
    if not name:
        raise HTTPException(400, 'Hizmet adı gerekli')
    if not conn.execute(
            'UPDATE shop_services SET name = ?, price = ?, duration_min = ?, staff_pct = ? WHERE id = ?',
            (name, round(body.price or 0, 2), max(5, int(body.duration_min or 30)),
             max(0.0, min(100.0, body.staff_pct or 0)), sid)).rowcount:
        raise HTTPException(404, 'Hizmet bulunamadı')
    _set_staff(conn, sid, body.staff_ids)
    conn.commit()
    return {'ok': True}


@router.delete('/{sid}')
def del_service(sid: int, user=Depends(svc_user), conn=db.DB):
    conn.execute('UPDATE shop_services SET active = 0 WHERE id = ?', (sid,))
    conn.commit()
    return {'ok': True}
