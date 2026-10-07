"""Mesai (çalışma saati) sistemi: haftalık program + tatiller + fazla mesai çarpanı.

Ayar app_kv['work_schedule'] içinde JSON:
  { "days": {"1":{"on":true,"from":"08:30","to":"17:30"}, ... "7":{...}},   # 1=Pazartesi .. 7=Pazar
    "holidays": ["2026-01-01", ...],                                        # mesai OLMAYAN günler
    "overtime_multiplier": 1.5 }
Fazla mesai kayıtları overtime_shifts tablosunda (İK girer).
"""
import json
from datetime import datetime

KV = 'work_schedule'


def _default():
    return {
        'days': {str(d): {'on': d <= 5, 'from': '08:30', 'to': '17:30'} for d in range(1, 8)},
        'holidays': [],
        'overtime_multiplier': 1.5,
    }


def _hm(s):
    try:
        h, m = str(s).split(':')[:2]
        return int(h) * 60 + int(m)
    except Exception:   # noqa: BLE001
        return 0


def get_schedule(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KV,)).fetchone()
    try:
        data = json.loads(row[0]) if row and row[0] else {}
    except Exception:   # noqa: BLE001
        data = {}
    d0 = _default()
    days = data.get('days') or {}
    out = {'days': {}, 'holidays': [h for h in (data.get('holidays') or []) if h],
           'overtime_multiplier': float(data.get('overtime_multiplier') or 1.5)}
    for d in range(1, 8):
        dd = days.get(str(d)) or {}
        base = d0['days'][str(d)]
        out['days'][str(d)] = {'on': bool(dd.get('on', base['on'])),
                               'from': str(dd.get('from', base['from']))[:5],
                               'to': str(dd.get('to', base['to']))[:5]}
    return out


def set_schedule(conn, data):
    sch = {'days': {}, 'holidays': [], 'overtime_multiplier': 1.5}
    days = (data or {}).get('days') or {}
    d0 = _default()
    for d in range(1, 8):
        dd = days.get(str(d)) or {}
        base = d0['days'][str(d)]
        sch['days'][str(d)] = {'on': bool(dd.get('on', False)),
                               'from': str(dd.get('from', base['from']))[:5],
                               'to': str(dd.get('to', base['to']))[:5]}
    hol = (data or {}).get('holidays') or []
    sch['holidays'] = sorted({str(h)[:10] for h in hol if h})[:400]
    try:
        m = float((data or {}).get('overtime_multiplier') or 1.5)
    except Exception:   # noqa: BLE001
        m = 1.5
    sch['overtime_multiplier'] = max(1.0, min(10.0, m))
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (KV, json.dumps(sch)))
    return sch


def is_work_time(conn, dt=None):
    """Genel mesai saati mi? (haftalık program + tatiller; sunucu saati Europe/Istanbul)."""
    dt = dt or datetime.now()
    sch = get_schedule(conn)
    if dt.date().isoformat() in sch['holidays']:
        return False
    day = sch['days'][str(dt.isoweekday())]
    if not day['on']:
        return False
    cur = dt.hour * 60 + dt.minute
    return _hm(day['from']) <= cur <= _hm(day['to'])


def is_work_time_for(conn, user_id, dt=None):
    """Kullanıcı için mesai zamanı mı? Genel mesai VEYA o kişinin o güne girilmiş fazla mesaisi."""
    dt = dt or datetime.now()
    if is_work_time(conn, dt):
        return True
    ds = dt.date().isoformat()
    cur = dt.hour * 60 + dt.minute
    for st, en in conn.execute('SELECT start_time, end_time FROM overtime_shifts WHERE user_id = ? AND date = ?', (user_id, ds)).fetchall():
        if _hm(st) <= cur <= _hm(en):
            return True
    return False


def shift_hours(start_time, end_time):
    mins = max(0, _hm(end_time) - _hm(start_time))
    return round(mins / 60.0, 2)


def is_on_duty(conn, user_id):
    """Kullanıcı şu an GÖREVDE / SAHADA mı? (onaylı görev; çıkmış/saha, dönmemiş, bugünü kapsıyor).
    Görevde olan personel konumunu kapatamaz → konum her zaman takip edilir."""
    today = datetime.now().date().isoformat()
    return conn.execute(
        """SELECT 1 FROM duty_requests d
             JOIN duty_people dp ON dp.duty_id = d.id
             JOIN employees e ON e.id = dp.employee_id
            WHERE e.user_id = ? AND d.status = 'ONAYLANDI' AND d.returned_at IS NULL
              AND (d.exited_at IS NOT NULL OR d.source = 'field')
              AND substr(d.depart_at, 1, 10) <= ?
              AND (d.return_at IS NULL OR substr(d.return_at, 1, 10) >= ?)
            LIMIT 1""", (user_id, today, today)).fetchone() is not None
