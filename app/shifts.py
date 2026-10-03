"""Fabrika vardiya ayarı (Program Ayarları › Genel Ayarlar). 24 saat biçiminde gündüz/gece mesaisi.

NVR kanallarında "sadece gündüz" / "sadece akşam" zamanlaması bu aralıkları kullanır (yüz tanıma yalnız
ilgili vardiyada çalışır). Varsayılan: gündüz 08:30–17:30, gece 17:30–08:30. app_kv['shift_config']'te saklanır.
"""
import json
import re

KV_KEY = 'shift_config'
DEFAULT = {'day': ['08:30', '17:30'], 'night': ['17:30', '08:30']}
_HHMM = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def get(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KV_KEY,)).fetchone()
    try:
        data = json.loads(row[0]) if row else {}
    except ValueError:
        data = {}
    out = {k: list(v) for k, v in DEFAULT.items()}
    for key in ('day', 'night'):
        v = data.get(key)
        if isinstance(v, (list, tuple)) and len(v) == 2 and all(_HHMM.match(str(x)) for x in v):
            out[key] = [str(v[0]), str(v[1])]
    return out


def save(conn, day=None, night=None):
    cur = get(conn)
    for key, val in (('day', day), ('night', night)):
        if val is None:
            continue
        if not (isinstance(val, (list, tuple)) and len(val) == 2 and all(_HHMM.match(str(x)) for x in val)):
            raise ValueError(f'{key}: saat SS:DD biçiminde olmalı (24 saat)')
        cur[key] = [str(val[0]), str(val[1])]
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (KV_KEY, json.dumps(cur)))
    return cur


def _to_min(hhmm):
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def in_window(hhmm, start, end):
    """SS:DD verilen an [start,end) aralığında mı? Gece yarısını geçen aralıkları (ör. 17:30–08:30) destekler."""
    t, s, e = _to_min(hhmm), _to_min(start), _to_min(end)
    return (s <= t < e) if s < e else (t >= s or t < e)


def active_now(conn, hhmm, schedule):
    """schedule: all | day | night | custom(aralıklar dışarıdan). Verilen an yüz tanıma çalışmalı mı?"""
    if schedule == 'all':
        return True
    cfg = get(conn)
    if schedule == 'day':
        return in_window(hhmm, *cfg['day'])
    if schedule == 'night':
        return in_window(hhmm, *cfg['night'])
    return False
