"""Günlük Görevler: Sistem Yöneticisi (master) kullanıcılara görev atar; kullanıcı kendi görevlerini görür,
'yaptım' ya da 'reddet' işaretler. Zorunlu (mandatory) + bekleyen görev varsa ana ekranda uyarı şeridi.
recurring=1 → haftanın seçili günlerinde tekrarlar (günlük işlem user_task_log'da); recurring=0 → tek seferlik
(işlem user_tasks'ta: status/done_at/reason). Her görevin görev_saati (task_time) vardır. Temizlikten bağımsız."""
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api')
me_user = auth.current_user


def _master(user=Depends(auth.current_user)):
    if not (user.get('master') or auth.ADMIN in user.get('roles', [])):
        raise HTTPException(403, 'Yalnız Sistem Yöneticisi görev atayabilir')
    return user


def _today():
    return _date.today().isoformat()


def _valid_day(s):
    try:
        return _date.fromisoformat((s or '')[:10]).isoformat()
    except (TypeError, ValueError):
        return _today()


def _valid_time(s):
    s = (s or '').strip()[:5]
    try:
        hh, mm = s.split(':')
        if 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59:
            return f'{int(hh):02d}:{int(mm):02d}'
    except (ValueError, AttributeError):
        pass
    return None


def _norm_weekdays(lst):
    """[1..7] (Pzt=1..Paz=7) → '1,2,3' (benzersiz, sıralı). Boş → None (her gün)."""
    try:
        days = sorted({int(x) for x in (lst or []) if 1 <= int(x) <= 7})
    except (ValueError, TypeError):
        days = []
    return ','.join(str(d) for d in days) or None


def _applies_today(task, day, wd):
    """Görev 'day' gününde geçerli mi? (tekrarlı: haftanın günü; tek seferlik: due_day geçmiş ve beklemede)."""
    if task['recurring']:
        if task['weekdays']:
            days = [int(x) for x in task['weekdays'].split(',') if x.strip().isdigit()]
            if days and wd not in days:
                return False
        return True
    # tek seferlik
    if task['status']:   # işlenmiş (done/rejected): yalnız işlem gününde görünür
        return (task['done_at'] or '')[:10] == day
    return not (task['due_day'] and task['due_day'] > day)   # beklemede: due_day'den itibaren


def _my_tasks(conn, uid, day):
    """uid kullanıcısının 'day' günündeki görevleri + o günkü durum (done/rejected/bekliyor)."""
    wd = _date.fromisoformat(day).isoweekday()   # 1=Pzt..7=Paz
    rows = db.rows(conn.execute(
        '''SELECT t.*, l.status AS day_status, l.done_at AS day_at, l.reason AS day_reason
           FROM user_tasks t
           LEFT JOIN user_task_log l ON l.task_id = t.id AND l.day = ?
           WHERE t.user_id = ? AND t.active = 1
           ORDER BY (t.task_time IS NULL), t.task_time, t.mandatory DESC, t.id''', (day, uid)))
    out = []
    for r in rows:
        if not _applies_today(r, day, wd):
            continue
        if r['recurring']:
            status, at, reason = r['day_status'], r['day_at'], r['day_reason']
        else:
            status, at, reason = r['status'], r['done_at'], r['reason']
        out.append({
            'id': r['id'], 'title': r['title'], 'note': r['note'], 'mandatory': bool(r['mandatory']),
            'recurring': bool(r['recurring']), 'weekdays': r['weekdays'], 'task_time': r['task_time'],
            'due_day': r['due_day'], 'status': status, 'done': status == 'done', 'rejected': status == 'rejected',
            'at': at, 'reason': reason,
        })
    return out


def pending_for(conn, uid, day=None):
    """uid kullanıcısının bugün BEKLEYEN (ne yapılmış ne reddedilmiş) görevleri. Rozet + uyarı şeridi için."""
    return [t for t in _my_tasks(conn, uid, day or _today()) if not t['status']]


# ---------- Kullanıcı: kendi görevleri ----------
@router.get('/my/tasks')
def my_tasks(date: str = None, user=Depends(me_user), conn=db.DB):
    day = _valid_day(date)
    tasks = _my_tasks(conn, user['id'], day)
    return {'date': day, 'tasks': tasks,
            'pending': sum(1 for t in tasks if not t['status']),
            'done': sum(1 for t in tasks if t['done']),
            'total': len(tasks),
            'pending_mandatory': sum(1 for t in tasks if t['mandatory'] and not t['status'])}


class ActionIn(BaseModel):
    date: str = None
    action: str = 'done'   # 'done' | 'reject' | 'undo'
    reason: str = None


@router.post('/my/tasks/{task_id}/action')
def task_action(task_id: int, body: ActionIn, user=Depends(me_user), conn=db.DB):
    """Görevi 'yaptım' (done) / 'reddet' (reject, neden) / geri al (undo) işaretler."""
    t = db.row(conn.execute('SELECT * FROM user_tasks WHERE id = ? AND user_id = ? AND active = 1', (task_id, user['id'])))
    if not t:
        raise HTTPException(404, 'Görev bulunamadı')
    day = _valid_day(body.date)
    act = body.action if body.action in ('done', 'reject', 'undo') else 'done'
    status = None if act == 'undo' else ('rejected' if act == 'reject' else 'done')
    at = None if act == 'undo' else db.now()
    reason = (body.reason or '').strip()[:500] or None if act == 'reject' else None
    if t['recurring']:
        if status is None:
            conn.execute('DELETE FROM user_task_log WHERE task_id = ? AND day = ?', (task_id, day))
        else:
            ex = db.row(conn.execute('SELECT id FROM user_task_log WHERE task_id = ? AND day = ?', (task_id, day)))
            if ex:
                conn.execute('UPDATE user_task_log SET status = ?, done_at = ?, reason = ? WHERE id = ?', (status, at, reason, ex['id']))
            else:
                conn.execute('INSERT INTO user_task_log (task_id, day, status, done_at, reason) VALUES (?,?,?,?,?)', (task_id, day, status, at, reason))
    else:
        conn.execute('UPDATE user_tasks SET status = ?, done_at = ?, reason = ? WHERE id = ?', (status, at, reason, task_id))
    return {'ok': True, 'status': status, 'at': at}


# ---------- Sistem Yöneticisi: görev atama / yönetim ----------
class TaskIn(BaseModel):
    user_id: int = None
    title: str
    note: str = None
    mandatory: bool = False
    recurring: bool = False
    due_day: str = None
    weekdays: list = None
    task_time: str = None


def _validate(body, require_user=True):
    title = (body.title or '').strip()[:200]
    note = (body.note or '').strip()[:1000]
    tm = _valid_time(body.task_time)
    if require_user and not body.user_id:
        raise HTTPException(400, 'Kişi seçin')
    if not title:
        raise HTTPException(400, 'Görev başlığı zorunlu')
    if not note:
        raise HTTPException(400, 'Görev detayı zorunlu')
    if not tm:
        raise HTTPException(400, 'Görev saati zorunlu (ör. 09:00)')
    return title, note, tm


@router.get('/tasks')
def list_tasks(user_id: int = None, user=Depends(_master), conn=db.DB):
    """Atanmış (aktif) görevler; user_id verilirse yalnız o kişininkiler. Her görevin bugünkü/son durumu özetlenir."""
    args, where = [], 't.active = 1'
    if user_id:
        where += ' AND t.user_id = ?'
        args.append(user_id)
    rows = db.rows(conn.execute(
        f'''SELECT t.id, t.user_id, u.full_name AS user_name, t.title, t.note, t.mandatory, t.recurring,
                   t.due_day, t.weekdays, t.task_time, t.status, t.done_at, t.reason, t.created_at
            FROM user_tasks t JOIN users u ON u.id = t.user_id
            WHERE {where} ORDER BY t.id DESC''', tuple(args)))
    return rows


@router.post('/tasks')
def create_task(body: TaskIn, user=Depends(_master), conn=db.DB):
    title, note, tm = _validate(body)
    if not db.row(conn.execute('SELECT id FROM users WHERE id = ?', (body.user_id,))):
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    due = None if body.recurring else (_valid_day(body.due_day) if body.due_day else _today())
    wd = _norm_weekdays(body.weekdays) if body.recurring else None
    cur = conn.execute(
        '''INSERT INTO user_tasks (user_id, title, note, mandatory, recurring, due_day, weekdays, task_time,
           active, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,1,?,?)''',
        (body.user_id, title, note, int(body.mandatory), int(body.recurring), due, wd, tm, user['id'], db.now()))
    _notify_assignee(conn, body.user_id, title)
    return {'id': cur.lastrowid}


@router.put('/tasks/{task_id}')
def edit_task(task_id: int, body: TaskIn, user=Depends(_master), conn=db.DB):
    title, note, tm = _validate(body, require_user=False)
    due = None if body.recurring else (_valid_day(body.due_day) if body.due_day else _today())
    wd = _norm_weekdays(body.weekdays) if body.recurring else None
    if not conn.execute(
            '''UPDATE user_tasks SET title = ?, note = ?, mandatory = ?, recurring = ?, due_day = ?,
               weekdays = ?, task_time = ? WHERE id = ?''',
            (title, note, int(body.mandatory), int(body.recurring), due, wd, tm, task_id)).rowcount:
        raise HTTPException(404, 'Görev bulunamadı')
    return {'ok': True}


@router.delete('/tasks/{task_id}')
def delete_task(task_id: int, user=Depends(_master), conn=db.DB):
    if not conn.execute('UPDATE user_tasks SET active = 0 WHERE id = ?', (task_id,)).rowcount:
        raise HTTPException(404, 'Görev bulunamadı')
    return {'ok': True}


@router.get('/tasks/{task_id}/log')
def task_log(task_id: int, user=Depends(_master), conn=db.DB):
    """Görevin tamamlama/red geçmişi: hangi gün, saat kaçta yaptı ya da reddetti."""
    t = db.row(conn.execute('SELECT id, recurring, status, done_at, reason, due_day FROM user_tasks WHERE id = ?', (task_id,)))
    if not t:
        raise HTTPException(404, 'Görev bulunamadı')
    if t['recurring']:
        return db.rows(conn.execute(
            '''SELECT day, status, done_at, reason FROM user_task_log
               WHERE task_id = ? AND status IS NOT NULL ORDER BY day DESC''', (task_id,)))
    if t['status']:
        return [{'day': (t['done_at'] or '')[:10] or t['due_day'], 'status': t['status'], 'done_at': t['done_at'], 'reason': t['reason']}]
    return []


def _notify_assignee(conn, uid, title):
    """Göreve atanan kullanıcıya ANINDA push (uygulama içi rozet 'task-assigned' notifier'ından da gelir)."""
    try:
        from .. import push
        push.send([uid], {'type': 'notif', 'title': 'Size yeni görev atandı',
                          'tag': 'notif-task-assigned', 'body': title, 'url': '/app#/my-tasks'})
    except Exception:   # noqa: BLE001 — bildirim başarısızlığı görev atamayı bozmasın
        pass
