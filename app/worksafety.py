"""İş Güvenliği — yapılandırma, olay / ısı haritası / istatistik kayıtları ve rapor.

Dağıtık kurulumda tespit ve kayıt FABRİKADA (kamera servisi, yerel DB) yapılır; bulut `face.rpc` üzerinden `ws_*`
yöntemleriyle okur (rpc). Yapılandırmanın doğruluk kaynağı buluttur (app_kv['ws_config']); kaydedildiğinde fabrikaya
aktarılır. Kamera görüntüsü dışarı çıkmaz — olay karesi ve klibi fabrikada tutulur, istenince ajandan getirilir."""
import json
import time
from datetime import date, datetime, timedelta

from . import config, db
from . import worksafety_rules as R

CONFIG_KEY, STATUS_KEY = 'ws_config', 'ws_status'
EVENT_DIR = config.UPLOAD_DIR / 'wsevents'
LIVE_DIR = config.DATA_DIR / 'cameras' / 'live'
GRID_W, GRID_H = 32, 18
HEAT_KINDS = ('person', 'vehicle', 'event')
SHIFTS = (('00:00–08:00', 0, 8), ('08:00–16:00', 8, 16), ('16:00–24:00', 16, 24))

class NotFound(Exception):
    pass


# ---------------------------------------------------------------- yapılandırma
def default_config():
    return {'enabled': False, 'all_cameras': True, 'faces_mode': 'auto', 'blur_faces': True, 'clip': True,
            'cooldown': 300, 'interval': 2.0, 'retention_days': 90, 'rules': {}, 'cameras': {}}


def _num(v, lo, hi, default, cast=float):
    try:
        return cast(min(hi, max(lo, cast(v))))
    except (TypeError, ValueError):
        return default


def _clock(v, default):
    try:
        hh, mm = str(v).split(':')[:2]
        return f'{int(hh) % 24:02d}:{int(mm) % 60:02d}'
    except (TypeError, ValueError):
        return default


def _zone(z, i):
    if not isinstance(z, dict) or z.get('type') not in R.ZONE_KEYS:
        return None
    pts = []
    for p in z.get('points') or []:
        try:
            pts.append([round(min(1.0, max(0.0, float(p[0]))), 4), round(min(1.0, max(0.0, float(p[1]))), 4)])
        except (TypeError, ValueError, IndexError):
            return None
    if not 3 <= len(pts) <= 40:
        return None
    src, prm = z.get('params') or {}, {}
    t = z['type']
    if t == 'count':
        for k in ('min', 'max'):
            if src.get(k) not in (None, ''):
                prm[k] = _num(src[k], 0, 500, 0, int)
    elif t == 'confined':
        prm['max'] = _num(src.get('max'), 0, 50, 1, int)
    elif t == 'machine':
        keys = {c[0] for c in R.COLORS}
        prm['auth_colors'] = [c for c in (src.get('auth_colors') or []) if c in keys]
    elif t == 'timed':
        for k in ('from', 'to'):
            if src.get(k):
                prm[k] = _clock(src[k], None)
    elif t == 'vehicle_lane':
        if src.get('dir') not in (None, ''):
            prm['dir'] = _num(src['dir'], -360, 360, 0) % 360
    elif t == 'ppe_zone':
        prm['items'] = [k for k in (src.get('items') or []) if k in R.KKD]
    zid = str(z.get('id') or '')[:24] or f'z{int(time.time() * 1000) % 10 ** 10}{i}'
    return {'id': zid, 'name': (str(z.get('name') or '').strip() or dict((k, n) for k, n, *_ in R.ZONE_TYPES)[t])[:60],
            'type': t, 'points': pts, 'params': {k: v for k, v in prm.items() if v is not None}}


def normalize(cfg):
    """Dışarıdan gelen yapılandırmayı doğrular / sınırlar (bilinmeyen anahtarlar atılır)."""
    src = cfg if isinstance(cfg, dict) else {}
    out = default_config()
    for k in ('enabled', 'all_cameras', 'blur_faces', 'clip'):
        if k in src:
            out[k] = bool(src[k])
    if src.get('faces_mode') in ('auto', 'on', 'off'):
        out['faces_mode'] = src['faces_mode']
    out['cooldown'] = _num(src.get('cooldown'), 30, 86400, 300, int)
    out['interval'] = _num(src.get('interval'), 0.5, 60, 2.0)
    out['retention_days'] = _num(src.get('retention_days'), 1, 3650, 90, int)
    for key, u in (src.get('rules') or {}).items():
        base = R.BY_KEY.get(key)
        if not base or not isinstance(u, dict):
            continue
        e = {}
        if 'enabled' in u:
            e['enabled'] = bool(u['enabled'])
        for k in ('sev', 'lik'):
            if u.get(k) not in (None, ''):
                e[k] = _num(u[k], 1, 5, base[k], int)
        prm = {}
        for pk, pv in (u.get('params') or {}).items():
            if pk not in base['params']:
                continue
            d = base['params'][pk]
            if isinstance(d, bool):
                prm[pk] = bool(pv)
            elif isinstance(d, list):
                prm[pk] = [str(x)[:40] for x in (pv or [])][:40]
            elif isinstance(d, str):
                prm[pk] = _clock(pv, d)
            elif isinstance(d, int):
                prm[pk] = _num(pv, 0, 86400, d, int)
            else:
                prm[pk] = _num(pv, 0, 1000, d)
        if prm:
            e['params'] = prm
        if e:
            out['rules'][key] = e
    for cid, c in (src.get('cameras') or {}).items():
        if not str(cid).isdigit() or not isinstance(c, dict):
            continue
        zones = [z for z in (_zone(z, i) for i, z in enumerate(c.get('zones') or [])) if z][:40]
        only = c.get('rules')
        out['cameras'][str(int(cid))] = {
            'enabled': bool(c.get('enabled', True)), 'ppe': bool(c.get('ppe')),
            'rules': None if only is None else [k for k in only if k in R.BY_KEY], 'zones': zones}
    return out


def get_config(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (CONFIG_KEY,)).fetchone()
    try:
        return normalize(json.loads(row[0])) if row else default_config()
    except (ValueError, TypeError):
        return default_config()


def set_config(conn, cfg):
    cfg = normalize(cfg)
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (CONFIG_KEY, json.dumps(cfg, ensure_ascii=False)))
    return cfg


def camera_config(cfg, cid):
    """Kameranın etkin ayarı ya da None (kapsam dışı)."""
    c = (cfg.get('cameras') or {}).get(str(cid))
    if c is None:
        return {'enabled': True, 'ppe': False, 'rules': None, 'zones': []} if cfg.get('all_cameras') else None
    return c if c.get('enabled') else None


def catalog(caps=None):
    """Arayüz için kural / bölge / KKD kataloğu. caps verilirse kural başına model durumu eklenir."""
    from . import worksafety_detect as D
    rules = []
    for r in R.RULES:
        e = {k: r[k] for k in ('no', 'key', 'name', 'cat', 'sev', 'lik', 'desc', 'zone', 'zone_req', 'params', 'hold', 'confirm', 'on')}
        e['ppe'] = r.get('ppe')
        if caps is not None:
            ok, why = R.model_ok(r, caps)
            e['model_ok'], e['model_missing'] = ok, why
        rules.append(e)
    return {'rules': rules, 'cats': [{'key': k, 'name': n} for k, n in R.CATS],
            'zone_types': [{'key': k, 'name': n, 'color': c, 'rules': rs, 'params': ps} for k, n, c, rs, ps in R.ZONE_TYPES],
            'kkd': [{'key': k, 'name': R.KKD_NAMES[k]} for k in R.KKD], 'colors': [{'key': k, 'name': n} for k, n in R.COLORS],
            'objects': [c for c in D.COCO if c != 'person'], 'levels': [n for _, n in R.LEVELS],
            'grid': [GRID_W, GRID_H], 'shifts': [s[0] for s in SHIFTS]}


# ---------------------------------------------------------------- durum
def set_status(conn, st):
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (STATUS_KEY, json.dumps(st, ensure_ascii=False)))


def status(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (STATUS_KEY,)).fetchone()
    try:
        st = json.loads(row[0]) if row else {}
    except (ValueError, TypeError):
        st = {}
    st['age'] = round(time.time() - st['ts'], 1) if st.get('ts') else None
    st['running'] = st['age'] is not None and st['age'] < 90
    cfg = get_config(conn)
    st['enabled'], st['faces_mode'] = cfg['enabled'], cfg['faces_mode']
    today = date.today().isoformat()
    st['events_today'] = conn.execute('SELECT COUNT(*) FROM ws_events WHERE at >= ?', (today,)).fetchone()[0]
    st['open_events'] = conn.execute('SELECT COUNT(*) FROM ws_events WHERE ack_at IS NULL').fetchone()[0]
    return st


# ---------------------------------------------------------------- olaylar
_EV_COLS = ('id, camera_id, camera_name, rule, rule_name, cat, zone_id, zone_name, severity, likelihood, risk, level, '
            'detail, meta, photo, clip, at, ack_by, ack_name, ack_at, ack_note')


def _ev(r):
    try:
        r['meta'] = json.loads(r['meta']) if r.get('meta') else {}
    except (ValueError, TypeError):
        r['meta'] = {}
    return r


def add_event(conn, camera_id, camera_name, e, photo=None, clip=None, at=None):
    cur = conn.execute(
        '''INSERT INTO ws_events (camera_id, camera_name, rule, rule_name, cat, zone_id, zone_name, severity, likelihood, risk, level,
                                  detail, meta, photo, clip, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (camera_id, camera_name, e['rule'], e['name'], e.get('cat'), e.get('zone'), e.get('zone_name'), e['sev'], e['lik'], e['risk'],
         e['level'], e.get('detail'), json.dumps({**(e.get('meta') or {}), 'boxes': e.get('boxes') or [], 'duration': e.get('duration'),
                                                 'n': e.get('viol')}, ensure_ascii=False), photo, clip, at or db.now()))
    return cur.lastrowid


def _ev_where(a):
    cond, prm = [], []
    if a.get('since'):
        cond.append('at >= ?')
        prm.append(str(a['since']))
    if a.get('until'):
        cond.append('at < ?')
        prm.append((date.fromisoformat(str(a['until'])[:10]) + timedelta(days=1)).isoformat() if len(str(a['until'])) <= 10 else str(a['until']))
    for k, col in (('rule', 'rule'), ('level', 'level'), ('cat', 'cat')):
        if a.get(k):
            cond.append(f'{col} = ?')
            prm.append(str(a[k]))
    if a.get('camera') not in (None, ''):
        cond.append('camera_id = ?')
        prm.append(int(a['camera']))
    if a.get('ack') in ('open', 0, '0'):
        cond.append('ack_at IS NULL')
    elif a.get('ack') in ('done', 1, '1'):
        cond.append('ack_at IS NOT NULL')
    return (' WHERE ' + ' AND '.join(cond)) if cond else '', prm


def events(conn, a):
    where, prm = _ev_where(a)
    limit = _num(a.get('limit'), 1, 2000, 200, int)
    rows = [_ev(r) for r in db.rows(conn.execute(f'SELECT {_EV_COLS} FROM ws_events{where} ORDER BY at DESC, id DESC LIMIT ?', (*prm, limit)))]
    total = conn.execute(f'SELECT COUNT(*) FROM ws_events{where}', prm).fetchone()[0]
    return {'rows': rows, 'total': total}


def event(conn, eid):
    r = db.row(conn.execute(f'SELECT {_EV_COLS} FROM ws_events WHERE id = ?', (int(eid),)))
    if not r:
        raise NotFound('Uyarı bulunamadı')
    return _ev(r)


def ack(conn, ids, by=None, name=None, note=None, undo=False):
    ids = [int(i) for i in (ids or [])][:2000]
    if not ids:
        return {'ok': True, 'n': 0}
    q = ','.join('?' * len(ids))
    if undo:
        cur = conn.execute(f'UPDATE ws_events SET ack_by = NULL, ack_name = NULL, ack_at = NULL, ack_note = NULL WHERE id IN ({q})', ids)
    else:
        cur = conn.execute(f'UPDATE ws_events SET ack_by = ?, ack_name = ?, ack_at = ?, ack_note = ? WHERE id IN ({q}) AND ack_at IS NULL',
                           (by, (name or '')[:80] or None, db.now(), (note or '').strip()[:500] or None, *ids))
    return {'ok': True, 'n': cur.rowcount}


def purge(conn, days):
    """Saklama süresi dolan olayları, medyalarını ve ısı / istatistik satırlarını siler."""
    lim = (date.today() - timedelta(days=int(days))).isoformat()
    n = 0
    for r in conn.execute('SELECT photo, clip FROM ws_events WHERE at < ?', (lim,)).fetchall():
        for f in (r[0], r[1]):
            if f:
                try:
                    (config.UPLOAD_DIR / f).unlink()
                except OSError:
                    pass
        n += 1
    conn.execute('DELETE FROM ws_events WHERE at < ?', (lim,))
    conn.execute('DELETE FROM ws_heat WHERE day < ?', (lim,))
    conn.execute('DELETE FROM ws_stats WHERE day < ?', (lim,))
    return n


# ---------------------------------------------------------------- ısı haritası / istatistik
def heat_add(conn, camera_id, day, kind, cells):
    """cells: {hücre dizini: artış} — günün ızgarasına eklenir."""
    if not cells:
        return
    row = conn.execute('SELECT grid FROM ws_heat WHERE camera_id = ? AND day = ? AND kind = ?', (camera_id, day, kind)).fetchone()
    try:
        grid = json.loads(row[0]) if row else None
    except (ValueError, TypeError):
        grid = None
    if not grid or len(grid) != GRID_W * GRID_H:
        grid = [0] * (GRID_W * GRID_H)
    for i, v in cells.items():
        if 0 <= int(i) < len(grid):
            grid[int(i)] = round(grid[int(i)] + v, 2)
    conn.execute('INSERT OR REPLACE INTO ws_heat (camera_id, day, kind, grid) VALUES (?,?,?,?)',
                 (camera_id, day, kind, json.dumps(grid, separators=(',', ':'))))


def heat(conn, a):
    kind = a.get('kind') if a.get('kind') in HEAT_KINDS else 'person'
    d1 = str(a.get('from') or date.today().isoformat())[:10]
    d2 = str(a.get('to') or d1)[:10]
    cond, prm = 'kind = ? AND day >= ? AND day <= ?', [kind, d1, d2]
    if a.get('camera') not in (None, ''):
        cond += ' AND camera_id = ?'
        prm.append(int(a['camera']))
    out = {}
    for r in conn.execute(f'SELECT camera_id, grid FROM ws_heat WHERE {cond}', prm):
        try:
            g = json.loads(r[1])
        except (ValueError, TypeError):
            continue
        cur = out.setdefault(r[0], [0] * (GRID_W * GRID_H))
        if len(g) == len(cur):
            out[r[0]] = [x + y for x, y in zip(cur, g)]
    return {'kind': kind, 'from': d1, 'to': d2, 'w': GRID_W, 'h': GRID_H,
            'cameras': [{'camera_id': cid, 'grid': [round(v, 1) for v in g], 'max': round(max(g), 1), 'sum': round(sum(g), 1)}
                        for cid, g in sorted(out.items())]}


def stats_add(conn, day, hour, items):
    """items: {(camera_id, rule): [checks, violations]}"""
    for (cid, rule), (c, v) in items.items():
        if c or v:
            conn.execute('''INSERT INTO ws_stats (day, hour, camera_id, rule, checks, violations) VALUES (?,?,?,?,?,?)
                            ON CONFLICT(day, hour, camera_id, rule) DO UPDATE SET checks = checks + excluded.checks,
                                                                                 violations = violations + excluded.violations''',
                         (day, int(hour), int(cid), rule, int(c), int(v)))


def _score(wc, wv):
    """Güvenlik puanı = 100 × (1 − Σ şiddet·ihlal / Σ şiddet·denetim); denetim yoksa None."""
    return round(100.0 * (1 - min(1.0, wv / wc)), 1) if wc > 0 else None


def report(conn, a):
    """Dönem raporu: genel puan + gün / kural / kamera / vardiya / bölge kırılımı. Varsayılan dönem son 7 gün."""
    d2 = str(a.get('to') or date.today().isoformat())[:10]
    d1 = str(a.get('from') or (date.fromisoformat(d2) - timedelta(days=6)).isoformat())[:10]
    days = (date.fromisoformat(d2) - date.fromisoformat(d1)).days + 1
    rules = R.effective(get_config(conn))
    sev = {k: r['sev'] for k, r in rules.items()}
    names = {r[0]: r[1] for r in conn.execute('SELECT id, name FROM cameras')}

    def agg(d_from, d_to):
        tot, by_day, by_rule, by_cam, by_hour = [0, 0, 0, 0], {}, {}, {}, {}
        for day, hour, cid, rule, c, v in conn.execute(
                'SELECT day, hour, camera_id, rule, SUM(checks), SUM(violations) FROM ws_stats WHERE day >= ? AND day <= ? '
                'GROUP BY day, hour, camera_id, rule', (d_from, d_to)):
            s = sev.get(rule, 3)
            v = min(v, c)
            for d, k in ((by_day, day), (by_rule, rule), (by_cam, cid), (by_hour, hour)):
                x = d.setdefault(k, [0, 0, 0, 0])
                x[0] += c
                x[1] += v
                x[2] += s * c
                x[3] += s * v
            tot[0] += c
            tot[1] += v
            tot[2] += s * c
            tot[3] += s * v
        return tot, by_day, by_rule, by_cam, by_hour

    tot, by_day, by_rule, by_cam, by_hour = agg(d1, d2)
    p1 = (date.fromisoformat(d1) - timedelta(days=days)).isoformat()
    p2 = (date.fromisoformat(d1) - timedelta(days=1)).isoformat()
    ptot = agg(p1, p2)[0]
    until = (date.fromisoformat(d2) + timedelta(days=1)).isoformat()
    ev_rule, ev_cam, ev_zone, ev_level, ev_day = {}, {}, {}, {}, {}
    n_ev = n_open = 0
    for rule, cid, cname, zid, zname, lvl, at, ack_at in conn.execute(
            'SELECT rule, camera_id, camera_name, zone_id, zone_name, level, at, ack_at FROM ws_events WHERE at >= ? AND at < ?', (d1, until)):
        n_ev += 1
        n_open += 0 if ack_at else 1
        ev_rule[rule] = ev_rule.get(rule, 0) + 1
        ev_cam[cid] = ev_cam.get(cid, 0) + 1
        ev_level[lvl] = ev_level.get(lvl, 0) + 1
        ev_day[at[:10]] = ev_day.get(at[:10], 0) + 1
        names.setdefault(cid, cname)
        if zid:
            z = ev_zone.setdefault((cid, zid), {'camera_id': cid, 'camera': names.get(cid) or cname, 'zone': zname or zid, 'events': 0})
            z['events'] += 1
    day_list = [(date.fromisoformat(d1) + timedelta(days=i)).isoformat() for i in range(days)]
    shifts = []
    for name, h1, h2 in SHIFTS:
        x = [sum(by_hour.get(h, [0, 0, 0, 0])[i] for h in range(h1, h2)) for i in range(4)]
        shifts.append({'name': name, 'checks': x[0], 'violations': x[1], 'score': _score(x[2], x[3])})
    return {
        'from': d1, 'to': d2, 'days': days, 'score': _score(tot[2], tot[3]), 'prev_score': _score(ptot[2], ptot[3]),
        'checks': tot[0], 'violations': tot[1], 'events': n_ev, 'open_events': n_open,
        'levels': [{'level': n, 'events': ev_level.get(n, 0)} for _, n in R.LEVELS],
        'by_day': [{'day': d, 'checks': by_day.get(d, [0] * 4)[0], 'violations': by_day.get(d, [0] * 4)[1],
                    'score': _score(*by_day.get(d, [0] * 4)[2:]), 'events': ev_day.get(d, 0)} for d in day_list],
        'by_rule': [{'rule': k, 'no': rules[k]['no'], 'name': rules[k]['name'], 'cat': rules[k]['cat'], 'checks': x[0], 'violations': x[1],
                     'rate': round(100.0 * x[1] / x[0], 2) if x[0] else None, 'events': ev_rule.get(k, 0)}
                    for k, x in sorted(by_rule.items(), key=lambda kv: -kv[1][3]) if k in rules],
        'by_camera': [{'camera_id': cid, 'camera': names.get(cid) or f'Kamera {cid}', 'checks': x[0], 'violations': x[1],
                       'score': _score(x[2], x[3]), 'events': ev_cam.get(cid, 0)}
                      for cid, x in sorted(by_cam.items(), key=lambda kv: (_score(kv[1][2], kv[1][3]) or 100, kv[0]))],
        'by_shift': shifts,
        'by_hour': [{'hour': h, 'checks': by_hour.get(h, [0] * 4)[0], 'violations': by_hour.get(h, [0] * 4)[1],
                     'score': _score(*by_hour.get(h, [0] * 4)[2:])} for h in range(24)],
        'by_zone': sorted(ev_zone.values(), key=lambda z: -z['events'])[:50],
    }


# ---------------------------------------------------------------- canlı görünüm
def live(ids):
    """Kamera servisinin son gözlem özetleri (LIVE_DIR/<cid>.ws.json) → {cid: özet}."""
    out = {}
    for cid in (ids or [])[:64]:
        p = LIVE_DIR / f'{int(cid)}.ws.json'
        try:
            if time.time() - p.stat().st_mtime < 30:
                out[str(int(cid))] = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
    return out


def cameras(conn):
    cfg = get_config(conn)
    out = []
    for r in db.rows(conn.execute('SELECT id, name, location, status, last_frame_at, faces, active, stream_url FROM cameras ORDER BY name COLLATE NOCASE, id')):
        live_f = LIVE_DIR / f'{r["id"]}.jpg'
        try:
            age = round(time.time() - live_f.stat().st_mtime, 1)
        except OSError:
            age = None
        out.append({'id': r['id'], 'name': r['name'], 'location': r['location'], 'status': r['status'], 'last_frame_at': r['last_frame_at'],
                    'faces': r['faces'], 'active': r['active'], 'has_stream': bool(r['stream_url']), 'live_age': age,
                    'in_scope': camera_config(cfg, r['id']) is not None})
    return out


# ---------------------------------------------------------------- face.rpc dağıtıcısı (fabrika tarafı)
def rpc(conn, method, a):
    if method == 'ws_status':
        return status(conn)
    if method == 'ws_config_set':
        cfg = set_config(conn, a.get('cfg') or {})
        return {'ok': True, 'enabled': cfg['enabled']}
    if method == 'ws_config_get':
        return get_config(conn)
    if method == 'ws_cameras':
        return cameras(conn)
    if method == 'ws_events':
        return events(conn, a)
    if method == 'ws_event':
        return event(conn, a['id'])
    if method == 'ws_ack':
        return ack(conn, a.get('ids') or [], a.get('by'), a.get('name'), a.get('note'), bool(a.get('undo')))
    if method == 'ws_heat':
        return heat(conn, a)
    if method == 'ws_report':
        return report(conn, a)
    if method == 'ws_live':
        return live(a.get('ids') or [])
    raise ValueError(f'Bilinmeyen iş güvenliği işlemi: {method}')


def local_day_hour(ts=None):
    d = datetime.fromtimestamp(ts) if ts else datetime.now()
    return d.date().isoformat(), d.hour
