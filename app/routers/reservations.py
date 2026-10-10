"""Rezervasyon (esnaf): berberde personel+hizmet randevusu, lokantada masa rezervasyonu.

Takvim: başlangıç/bitiş ISO; çakışma (overlap) kontrolü aynı personel VEYA aynı masa için yapılır.
Berberde hizmet seçilince süre hizmetten alınır (frontend ends_at hesaplar); çakışma yine sunucuda doğrulanır.
Dışarıdan (public) rezervasyon için /api/public/... uçları ayrı (giriş gerektirmez); burası personel tarafıdır.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/reservations')
STATUS = ('ONAYLI', 'GELMEDI', 'TAMAM', 'IPTAL')


def rsv_user(user=Depends(auth.current_user)):
    if 'reservations' not in user['modules']:
        raise HTTPException(403, 'Rezervasyon modülü bu firmada kapalı')
    return user


def overlap(conn, kind, ref_id, starts_at, ends_at, exclude_id=None):
    """Aynı personel (staff) veya masa (table) için zaman çakışması var mı? İptal/gelmedi sayılmaz."""
    col = 'staff_id' if kind == 'staff' else 'table_id'
    if not ref_id:
        return False
    q = f'''SELECT COUNT(*) FROM shop_reservations
            WHERE {col} = ? AND status IN ('ONAYLI','TAMAM')
              AND starts_at < ? AND ends_at > ?'''
    args = [ref_id, ends_at, starts_at]
    if exclude_id:
        q += ' AND id != ?'
        args.append(exclude_id)
    return conn.execute(q, args).fetchone()[0] > 0


def _row(r, names):
    r['staff_name'] = names.get(r['staff_id'])
    return r


@router.get('')
def list_reservations(start: str = '', end: str = '', user=Depends(rsv_user), conn=db.DB):
    """Aralıktaki rezervasyonlar (takvim). start/end ISO tarih (YYYY-MM-DD)."""
    q = 'SELECT r.*, s.name AS service_name, t.name AS table_name FROM shop_reservations r ' \
        'LEFT JOIN shop_services s ON s.id = r.service_id LEFT JOIN shop_tables t ON t.id = r.table_id WHERE 1=1'
    args = []
    if start:
        q += ' AND r.starts_at >= ?'; args.append(start)
    if end:
        q += ' AND r.starts_at <= ?'; args.append(end + 'T23:59:59')
    q += ' ORDER BY r.starts_at'
    rows = db.rows(conn.execute(q, args))
    names = {u['id']: u['full_name'] for u in db.rows(conn.execute('SELECT id, full_name FROM users'))}
    return [_row(r, names) for r in rows]


class ReservationIn(BaseModel):
    kind: str = 'staff'                  # staff (berber) | table (lokanta)
    staff_id: Optional[int] = None
    table_id: Optional[int] = None
    service_id: Optional[int] = None
    customer: str = ''
    phone: str = ''
    party: Optional[int] = None
    starts_at: str
    ends_at: str
    note: str = ''


def _validate(body):
    if not body.starts_at or not body.ends_at:
        raise HTTPException(400, 'Başlangıç ve bitiş zamanı gerekli')
    if body.ends_at <= body.starts_at:
        raise HTTPException(400, 'Bitiş, başlangıçtan sonra olmalı')
    kind = body.kind if body.kind in ('staff', 'table') else 'staff'
    ref = body.staff_id if kind == 'staff' else body.table_id
    if not ref:
        raise HTTPException(400, ('Personel' if kind == 'staff' else 'Masa') + ' seçin')
    return kind, ref


@router.post('')
def add_reservation(body: ReservationIn, user=Depends(rsv_user), conn=db.DB):
    kind, ref = _validate(body)
    if overlap(conn, kind, ref, body.starts_at, body.ends_at):
        raise HTTPException(409, 'Bu zaman aralığı dolu (çakışma var)')
    rid = conn.execute(
        '''INSERT INTO shop_reservations (kind, staff_id, table_id, service_id, customer, phone, party,
               starts_at, ends_at, status, note, source, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,'ONAYLI',?,'staff',?,?)''',
        (kind, body.staff_id, body.table_id, body.service_id, (body.customer or '').strip()[:120],
         (body.phone or '').strip()[:32], body.party, body.starts_at, body.ends_at,
         (body.note or '').strip()[:500], user['id'], db.now())).lastrowid
    conn.commit()
    db.audit(conn, user['id'], 'Rezervasyon ekledi', 'shop_reservation', rid, body.customer)
    return {'id': rid}


@router.put('/{rid}')
def edit_reservation(rid: int, body: ReservationIn, user=Depends(rsv_user), conn=db.DB):
    cur = db.row(conn.execute('SELECT * FROM shop_reservations WHERE id = ?', (rid,)))
    if not cur:
        raise HTTPException(404, 'Rezervasyon bulunamadı')
    kind, ref = _validate(body)
    if overlap(conn, kind, ref, body.starts_at, body.ends_at, exclude_id=rid):
        raise HTTPException(409, 'Bu zaman aralığı dolu (çakışma var)')
    conn.execute(
        '''UPDATE shop_reservations SET kind=?, staff_id=?, table_id=?, service_id=?, customer=?, phone=?,
               party=?, starts_at=?, ends_at=?, note=? WHERE id = ?''',
        (kind, body.staff_id, body.table_id, body.service_id, (body.customer or '').strip()[:120],
         (body.phone or '').strip()[:32], body.party, body.starts_at, body.ends_at,
         (body.note or '').strip()[:500], rid))
    conn.commit()
    return {'ok': True}


class StatusIn(BaseModel):
    status: str


@router.post('/{rid}/status')
def set_status(rid: int, body: StatusIn, user=Depends(rsv_user), conn=db.DB):
    st = body.status if body.status in STATUS else None
    if not st:
        raise HTTPException(400, 'Geçersiz durum')
    if not conn.execute('UPDATE shop_reservations SET status = ? WHERE id = ?', (st, rid)).rowcount:
        raise HTTPException(404, 'Rezervasyon bulunamadı')
    conn.commit()
    return {'ok': True}


@router.delete('/{rid}')
def del_reservation(rid: int, user=Depends(rsv_user), conn=db.DB):
    conn.execute('DELETE FROM shop_reservations WHERE id = ?', (rid,))
    conn.commit()
    return {'ok': True}
