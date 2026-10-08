"""Mesai ayarları (Program Ayarları) + fazla mesai (İK). Bkz. app/worktime.py."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, worktime

router = APIRouter(prefix='/api/worktime')


def _can_edit(user):
    return bool(user.get('master')) or auth.ADMIN in (user.get('roles') or [])


def _can_hr(user):
    return bool(user.get('master')) or any(r in (user.get('roles') or []) for r in (auth.ADMIN, auth.HR))


def _monthly_std_hours(sch):
    weekly = 0.0
    for d in range(1, 8):
        day = sch['days'][str(d)]
        if day['on']:
            weekly += worktime.shift_hours(day['from'], day['to'])
    return round(weekly * 4.33, 2)


@router.get('/schedule')
def get_schedule(user=Depends(auth.current_user), conn=db.DB):
    sch = worktime.get_schedule(conn)
    sch['monthly_std_hours'] = _monthly_std_hours(sch)
    sch['can_edit'] = _can_edit(user)
    sch['all_roles'] = auth.all_roles()   # "konumu her zaman açık roller" seçimi için tüm roller
    return sch


class ScheduleIn(BaseModel):
    days: dict
    holidays: list = []
    overtime_multiplier: float = 1.5
    always_track_roles: Optional[list] = None


@router.put('/schedule')
def put_schedule(body: ScheduleIn, user=Depends(auth.current_user), conn=db.DB):
    if not _can_edit(user):
        raise HTTPException(403, 'Yetki yok')
    sch = worktime.set_schedule(conn, body.model_dump())
    db.audit(conn, user['id'], 'Mesai ayarları güncellendi', 'settings', None, f"çarpan {sch['overtime_multiplier']}")
    conn.commit()
    sch['monthly_std_hours'] = _monthly_std_hours(sch)
    return sch


@router.get('/overtime')
def list_overtime(user_id: Optional[int] = None, month: Optional[str] = None, user=Depends(auth.current_user), conn=db.DB):
    if not _can_hr(user):
        raise HTTPException(403, 'Yetki yok')
    sch = worktime.get_schedule(conn)
    std = _monthly_std_hours(sch) or 1
    where, args = [], []
    if user_id:
        where.append('o.user_id = ?'); args.append(user_id)
    if month:
        where.append("substr(o.date,1,7) = ?"); args.append(month[:7])
    sql = '''SELECT o.id, o.user_id, u.full_name, e.salary, o.date, o.start_time, o.end_time, o.multiplier, o.note, o.created_at
             FROM overtime_shifts o JOIN users u ON u.id = o.user_id LEFT JOIN employees e ON e.user_id = o.user_id'''
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY o.date DESC, o.id DESC'
    rows = db.rows(conn.execute(sql, args))
    for r in rows:
        hrs = worktime.shift_hours(r['start_time'], r['end_time'])
        r['hours'] = hrs
        hourly = (r['salary'] / std) if r.get('salary') else None
        r['amount'] = round(hrs * hourly * (r['multiplier'] or 1), 2) if hourly else None
    return {'items': rows, 'monthly_std_hours': std, 'default_multiplier': sch['overtime_multiplier']}


class OvertimeIn(BaseModel):
    user_id: int
    date: str
    start: str
    end: str
    multiplier: Optional[float] = None
    note: Optional[str] = None


@router.post('/overtime')
def add_overtime(body: OvertimeIn, user=Depends(auth.current_user), conn=db.DB):
    if not _can_hr(user):
        raise HTTPException(403, 'Yetki yok')
    if not (body.date and body.start and body.end) or worktime._hm(body.end) <= worktime._hm(body.start):
        raise HTTPException(400, 'Geçerli tarih ve saat aralığı girin (bitiş > başlangıç)')
    mult = body.multiplier if body.multiplier else worktime.get_schedule(conn)['overtime_multiplier']
    mult = max(1.0, min(10.0, float(mult)))
    conn.execute('''INSERT INTO overtime_shifts (user_id, date, start_time, end_time, multiplier, note, created_by, created_at)
                    VALUES (?,?,?,?,?,?,?,?)''',
                 (body.user_id, body.date[:10], body.start[:5], body.end[:5], mult, (body.note or '').strip()[:300] or None, user['id'], db.now()))
    db.audit(conn, user['id'], 'Fazla mesai girildi', 'user', body.user_id, f'{body.date} {body.start}-{body.end} ×{mult}')
    conn.commit()
    return {'ok': True}


@router.delete('/overtime/{oid}')
def del_overtime(oid: int, user=Depends(auth.current_user), conn=db.DB):
    if not _can_hr(user):
        raise HTTPException(403, 'Yetki yok')
    conn.execute('DELETE FROM overtime_shifts WHERE id = ?', (oid,))
    conn.commit()
    return {'ok': True}
