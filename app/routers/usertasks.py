"""Günlük Görevler: Sistem Yöneticisi (master/ADMIN) belirli bir kullanıcıya görev atar; kullanıcı kendi
görevlerini görür ve 'yaptım' işaretler. Zorunlu (mandatory) ve tamamlanmamış görev varsa kullanıcının ana
ekranında kalıcı uyarı şeridi gösterilir. recurring=1 her gün tekrarlar (günlük tamamlama user_task_log);
recurring=0 tek seferlik (done_at user_tasks'ta). Temizlik modülünden bağımsızdır."""
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


def _my_tasks(conn, uid, day):
    """uid kullanıcısının 'day' günündeki görevleri (tek seferlik + tekrarlı) ve tamamlanma durumları."""
    rows = db.rows(conn.execute(
        '''SELECT t.id, t.title, t.note, t.mandatory, t.recurring, t.due_day, t.done_at,
                  l.done_at AS day_done_at
           FROM user_tasks t
           LEFT JOIN user_task_log l ON l.task_id = t.id AND l.day = ?
           WHERE t.user_id = ? AND t.active = 1
           ORDER BY t.mandatory DESC, t.id''', (day, uid)))
    out = []
    for r in rows:
        if r['recurring']:
            if r['due_day'] and r['due_day'] > day:   # tekrarlı görev başlangıç gününden önce görünmez
                continue
            done = bool(r['day_done_at'])
            done_at = r['day_done_at']
        else:
            done = bool(r['done_at'])
            # tek seferlik: tamamlandıysa yalnız tamamlandığı gün görünür; bekliyorsa due_day'den itibaren görünür
            if done and (r['done_at'] or '')[:10] != day:
                continue
            if not done and r['due_day'] and r['due_day'] > day:
                continue
            done_at = r['done_at']
        out.append({'id': r['id'], 'title': r['title'], 'note': r['note'], 'mandatory': bool(r['mandatory']),
                    'recurring': bool(r['recurring']), 'due_day': r['due_day'], 'done': done, 'done_at': done_at})
    return out


# ---------- Kullanıcı: kendi görevleri ----------
@router.get('/my/tasks')
def my_tasks(date: str = None, user=Depends(me_user), conn=db.DB):
    day = _valid_day(date)
    tasks = _my_tasks(conn, user['id'], day)
    pending_mandatory = sum(1 for t in tasks if t['mandatory'] and not t['done'])
    return {'date': day, 'tasks': tasks, 'pending': sum(1 for t in tasks if not t['done']),
            'total': len(tasks), 'pending_mandatory': pending_mandatory}


class DoneIn(BaseModel):
    date: str = None
    done: bool = True
    note: str = None


@router.post('/my/tasks/{task_id}/done')
def mark_done(task_id: int, body: DoneIn, user=Depends(me_user), conn=db.DB):
    """Görevi 'yaptım' işaretler (ya da geri alır). Zorunlu görev tamamlanınca uyarı şeridinden düşer."""
    t = db.row(conn.execute('SELECT * FROM user_tasks WHERE id = ? AND user_id = ? AND active = 1', (task_id, user['id'])))
    if not t:
        raise HTTPException(404, 'Görev bulunamadı')
    day = _valid_day(body.date)
    note = (body.note or '').strip()[:500] or None
    done_at = db.now() if body.done else None
    if t['recurring']:
        ex = db.row(conn.execute('SELECT id FROM user_task_log WHERE task_id = ? AND day = ?', (task_id, day)))
        if ex:
            conn.execute('UPDATE user_task_log SET done_at = ?, note = ? WHERE id = ?', (done_at, note, ex['id']))
        else:
            conn.execute('INSERT INTO user_task_log (task_id, day, done_at, note) VALUES (?,?,?,?)', (task_id, day, done_at, note))
    else:
        conn.execute('UPDATE user_tasks SET done_at = ? WHERE id = ?', (done_at, task_id))
    return {'ok': True, 'done_at': done_at}


# ---------- Sistem Yöneticisi: görev atama / yönetim ----------
class TaskIn(BaseModel):
    user_id: int
    title: str
    note: str = None
    mandatory: bool = False
    recurring: bool = False
    due_day: str = None


@router.get('/tasks')
def list_tasks(user=Depends(_master), conn=db.DB):
    """Atanmış (aktif) tüm günlük görevler — yönetim listesi."""
    return db.rows(conn.execute(
        '''SELECT t.id, t.user_id, u.full_name AS user_name, t.title, t.note, t.mandatory, t.recurring,
                  t.due_day, t.done_at, t.active, t.created_at
           FROM user_tasks t JOIN users u ON u.id = t.user_id
           WHERE t.active = 1 ORDER BY t.id DESC'''))


@router.post('/tasks')
def create_task(body: TaskIn, user=Depends(_master), conn=db.DB):
    title = (body.title or '').strip()[:200]
    if not title:
        raise HTTPException(400, 'Görev başlığı girin')
    if not db.row(conn.execute('SELECT id, full_name FROM users WHERE id = ?', (body.user_id,))):
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    due = None if body.recurring else (_valid_day(body.due_day) if body.due_day else _today())
    cur = conn.execute(
        '''INSERT INTO user_tasks (user_id, title, note, mandatory, recurring, due_day, active, created_by, created_at)
           VALUES (?,?,?,?,?,?,1,?,?)''',
        (body.user_id, title, (body.note or '').strip()[:1000] or None, int(body.mandatory),
         int(body.recurring), due, user['id'], db.now()))
    _notify_assignee(conn, body.user_id, title)
    return {'id': cur.lastrowid}


@router.put('/tasks/{task_id}')
def edit_task(task_id: int, body: TaskIn, user=Depends(_master), conn=db.DB):
    title = (body.title or '').strip()[:200]
    if not title:
        raise HTTPException(400, 'Görev başlığı girin')
    due = None if body.recurring else (_valid_day(body.due_day) if body.due_day else _today())
    if not conn.execute(
            '''UPDATE user_tasks SET title = ?, note = ?, mandatory = ?, recurring = ?, due_day = ? WHERE id = ?''',
            (title, (body.note or '').strip()[:1000] or None, int(body.mandatory), int(body.recurring), due, task_id)).rowcount:
        raise HTTPException(404, 'Görev bulunamadı')
    return {'ok': True}


@router.delete('/tasks/{task_id}')
def delete_task(task_id: int, user=Depends(_master), conn=db.DB):
    """Görevi kaldırır (pasife alır; geçmiş tamamlama kayıtları korunur)."""
    if not conn.execute('UPDATE user_tasks SET active = 0 WHERE id = ?', (task_id,)).rowcount:
        raise HTTPException(404, 'Görev bulunamadı')
    return {'ok': True}


def pending_for(conn, uid, day=None):
    """uid kullanıcısının bugün (ya da verilen gün) BEKLEYEN (tamamlanmamış) görevleri. Rozet + uyarı şeridi için."""
    return [t for t in _my_tasks(conn, uid, day or _today()) if not t['done']]


def _notify_assignee(conn, uid, title):
    """Göreve atanan kullanıcıya ANINDA push (uygulama içi rozet 'task-assigned' notifier'ından 60 sn içinde gelir)."""
    try:
        from .. import push
        push.send([uid], {'type': 'notif', 'title': 'Size yeni görev atandı',
                          'tag': 'notif-task-assigned', 'body': title, 'url': '/app#/my-tasks'})
    except Exception:   # noqa: BLE001 — bildirim başarısızlığı görev atamayı bozmasın
        pass
