"""Yapılacaklar (TODO): Sistem Yöneticisi personele görev verir, sonucunu takip eder.

Akış: atanan kişi görevi önce BAŞLATIR (started_at, süre işler) → yaptığı işleri madde madde ekler (todo_items) →
TAMAMLANDI der (done_at, elapsed_s = geçen süre, sonuç notu). Yönetici "Verdiğim görevler"de durumu, maddeleri,
süreyi görür; sonucu gördüğünü işaretler (seen_at). Üst çubuktaki TODO ikonu /api/todos/pending ile beslenir.
Günlük Görevler'den (usertasks) bağımsızdır."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/todos')

DDL = '''
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    note TEXT,
    assignee_id INTEGER NOT NULL REFERENCES users(id),
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    due_at TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    done_at TEXT,
    elapsed_s INTEGER NOT NULL DEFAULT 0,
    result TEXT,
    seen_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_todos_assignee ON todos(assignee_id, status);
CREATE TABLE IF NOT EXISTS todo_items (
    id INTEGER PRIMARY KEY,
    todo_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    done_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_todo_items_todo ON todo_items(todo_id);
'''
PRIORITIES = ('low', 'normal', 'high')
OPEN = ('pending', 'started')


def _ensure(conn):
    conn.executescript(DDL)


def _is_admin(user):
    return bool(user.get('master')) or auth.ADMIN in user.get('roles', [])


def _admin(user=Depends(auth.current_user)):
    if not _is_admin(user):
        raise HTTPException(403, 'Yalnız Sistem Yöneticisi görev verebilir')
    return user


def _elapsed(t, now=None):
    """Geçen süre (sn): başlatılmışsa şu ana kadar, tamamlanmışsa kaydedilen."""
    if t['status'] == 'started' and t['started_at']:
        try:
            return int((datetime.fromisoformat(now or db.now()) - datetime.fromisoformat(t['started_at'])).total_seconds())
        except ValueError:
            return 0
    return int(t['elapsed_s'] or 0)


SELECT = '''SELECT t.*, a.full_name AS assignee_name, a.username AS assignee_username, a.photo AS assignee_photo,
                   c.full_name AS creator_name,
                   (SELECT COUNT(*) FROM todo_items i WHERE i.todo_id = t.id) AS item_count,
                   (SELECT COUNT(*) FROM todo_items i WHERE i.todo_id = t.id AND i.done = 1) AS item_done
            FROM todos t JOIN users a ON a.id = t.assignee_id LEFT JOIN users c ON c.id = t.created_by'''


def _items(conn, tid):
    return db.rows(conn.execute('SELECT id, text, done, sort, created_at, done_at FROM todo_items WHERE todo_id = ? ORDER BY sort, id', (tid,)))


def _pub(conn, t, with_items=True):
    d = dict(t)
    d['elapsed_s'] = _elapsed(t)
    d['open'] = t['status'] in OPEN
    if with_items:
        d['items'] = [dict(i, done=bool(i['done'])) for i in _items(conn, t['id'])]
    return d


def _get(conn, tid, user):
    _ensure(conn)
    t = db.row(conn.execute(SELECT + ' WHERE t.id = ?', (tid,)))
    if not t:
        raise HTTPException(404, 'Görev bulunamadı')
    if not (t['assignee_id'] == user['id'] or t['created_by'] == user['id'] or _is_admin(user)):
        raise HTTPException(403, 'Bu göreve erişiminiz yok')
    return t


def _push(uid, title, body, url):
    try:
        from .. import push
        push.send([uid], {'type': 'notif', 'title': title, 'tag': 'notif-todo', 'body': body, 'url': url})
    except Exception:   # noqa: BLE001 — bildirim başarısızlığı işlemi bozmasın
        pass


# ---------------------------------------------------------------- listeler
@router.get('')
def list_todos(scope: str = 'mine', status: str = 'open', user=Depends(auth.current_user), conn=db.DB):
    """scope=mine (bana atanan) | given (verdiğim) | all (yönetici: hepsi); status=open | done | all."""
    _ensure(conn)
    where, args = [], []
    if scope == 'given':
        where.append('t.created_by = ?'); args.append(user['id'])
    elif scope == 'all' and _is_admin(user):
        pass
    else:
        where.append('t.assignee_id = ?'); args.append(user['id'])
    if status == 'open':
        where.append("t.status IN ('pending','started')")
    elif status == 'done':
        where.append("t.status IN ('done','cancelled')")
    sql = SELECT + (' WHERE ' + ' AND '.join(where) if where else '')
    sql += " ORDER BY CASE t.status WHEN 'started' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, COALESCE(t.due_at, '9') , t.id DESC LIMIT 500"
    rows = db.rows(conn.execute(sql, args))
    return [_pub(conn, r) for r in rows]


@router.get('/pending')
def pending(user=Depends(auth.current_user), conn=db.DB):
    """Üst çubuk TODO ikonu: bana atanan açık görevler (başlatılmış önce) + yöneticiyse görülmemiş tamamlananlar."""
    _ensure(conn)
    rows = db.rows(conn.execute(SELECT + " WHERE t.assignee_id = ? AND t.status IN ('pending','started') ORDER BY CASE t.status WHEN 'started' THEN 0 ELSE 1 END, COALESCE(t.due_at, '9'), t.id DESC LIMIT 30", (user['id'],)))
    done = db.rows(conn.execute(SELECT + " WHERE t.created_by = ? AND t.status = 'done' AND t.seen_at IS NULL ORDER BY t.done_at DESC LIMIT 20", (user['id'],))) if _is_admin(user) else []
    return {'count': len(rows) + len(done), 'mine': [_pub(conn, r, False) for r in rows], 'done': [_pub(conn, r, False) for r in done], 'admin': _is_admin(user)}


def pending_for(conn, uid):
    """notifications.py: kullanıcıya atanan açık görevler."""
    _ensure(conn)
    return db.rows(conn.execute("SELECT id, title, status FROM todos WHERE assignee_id = ? AND status IN ('pending','started') ORDER BY id DESC", (uid,)))


def done_unseen_for(conn, uid):
    """notifications.py: verdiğim görevlerden tamamlanmış ama henüz görmediklerim."""
    _ensure(conn)
    return db.rows(conn.execute('''SELECT t.id, t.title, a.full_name AS assignee_name FROM todos t JOIN users a ON a.id = t.assignee_id
                                   WHERE t.created_by = ? AND t.status = 'done' AND t.seen_at IS NULL ORDER BY t.done_at DESC''', (uid,)))


@router.get('/{tid}')
def get_todo(tid: int, user=Depends(auth.current_user), conn=db.DB):
    return _pub(conn, _get(conn, tid, user))


# ---------------------------------------------------------------- yönetici: ver / düzenle / sil
class TodoIn(BaseModel):
    title: str
    note: Optional[str] = None
    assignee_id: int
    due_at: Optional[str] = None
    priority: str = 'normal'


def _clean(body):
    title = (body.title or '').strip()[:300]
    if not title:
        raise HTTPException(400, 'Görev başlığı gerekli')
    note = (body.note or '').strip()[:4000] or None
    due = (body.due_at or '').strip()[:16] or None
    pr = body.priority if body.priority in PRIORITIES else 'normal'
    return title, note, due, pr


@router.post('')
def create_todo(body: TodoIn, user=Depends(_admin), conn=db.DB):
    _ensure(conn)
    title, note, due, pr = _clean(body)
    if not db.row(conn.execute('SELECT id FROM users WHERE id = ? AND active = 1', (body.assignee_id,))):
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    cur = conn.execute('INSERT INTO todos (title, note, assignee_id, created_by, created_at, due_at, priority) VALUES (?,?,?,?,?,?,?)',
                       (title, note, body.assignee_id, user['id'], db.now(), due, pr))
    conn.commit()
    _push(body.assignee_id, 'Size yeni görev verildi', title, '/app#/my-todos')
    return _pub(conn, _get(conn, cur.lastrowid, user))


class TodoPatch(BaseModel):
    title: Optional[str] = None
    note: Optional[str] = None
    assignee_id: Optional[int] = None
    due_at: Optional[str] = None
    priority: Optional[str] = None


@router.put('/{tid}')
def update_todo(tid: int, body: TodoPatch, user=Depends(auth.current_user), conn=db.DB):
    t = _get(conn, tid, user)
    if not (t['created_by'] == user['id'] or _is_admin(user)):
        raise HTTPException(403, 'Yalnız görevi veren düzenleyebilir')
    title = t['title'] if body.title is None else (body.title.strip()[:300] or t['title'])
    note = t['note'] if body.note is None else (body.note.strip()[:4000] or None)
    due = t['due_at'] if body.due_at is None else (body.due_at.strip()[:16] or None)
    pr = t['priority'] if body.priority is None else (body.priority if body.priority in PRIORITIES else t['priority'])
    assignee = t['assignee_id']
    if body.assignee_id is not None and body.assignee_id != assignee:
        if not db.row(conn.execute('SELECT id FROM users WHERE id = ? AND active = 1', (body.assignee_id,))):
            raise HTTPException(404, 'Kullanıcı bulunamadı')
        assignee = body.assignee_id
    conn.execute('UPDATE todos SET title = ?, note = ?, due_at = ?, priority = ?, assignee_id = ? WHERE id = ?', (title, note, due, pr, assignee, tid))
    conn.commit()
    if assignee != t['assignee_id']:
        _push(assignee, 'Size yeni görev verildi', title, '/app#/my-todos')
    return _pub(conn, _get(conn, tid, user))


@router.delete('/{tid}')
def delete_todo(tid: int, user=Depends(auth.current_user), conn=db.DB):
    t = _get(conn, tid, user)
    if not (t['created_by'] == user['id'] or _is_admin(user)):
        raise HTTPException(403, 'Yalnız görevi veren silebilir')
    conn.execute('DELETE FROM todo_items WHERE todo_id = ?', (tid,))
    conn.execute('DELETE FROM todos WHERE id = ?', (tid,))
    conn.commit()
    return {'ok': True}


@router.post('/{tid}/seen')
def mark_seen(tid: int, user=Depends(auth.current_user), conn=db.DB):
    t = _get(conn, tid, user)
    if not (t['created_by'] == user['id'] or _is_admin(user)):
        raise HTTPException(403, 'Yalnız görevi veren işaretleyebilir')
    conn.execute('UPDATE todos SET seen_at = ? WHERE id = ?', (db.now(), tid))
    conn.commit()
    return {'ok': True}


@router.post('/{tid}/reopen')
def reopen(tid: int, user=Depends(auth.current_user), conn=db.DB):
    """Yönetici tamamlanmış görevi yeniden açar: süre kaldığı yerden devam eder (started)."""
    t = _get(conn, tid, user)
    if not (t['created_by'] == user['id'] or _is_admin(user)):
        raise HTTPException(403, 'Yalnız görevi veren yeniden açabilir')
    conn.execute("UPDATE todos SET status = 'started', started_at = ?, done_at = NULL, seen_at = NULL WHERE id = ?", (db.now(), tid))
    conn.commit()
    _push(t['assignee_id'], 'Görev yeniden açıldı', t['title'], '/app#/my-todos')
    return _pub(conn, _get(conn, tid, user))


# ---------------------------------------------------------------- atanan kişi: başlat / tamamla
def _assignee(t, user):
    if t['assignee_id'] != user['id'] and not _is_admin(user):
        raise HTTPException(403, 'Bu görev size atanmamış')


@router.post('/{tid}/start')
def start(tid: int, user=Depends(auth.current_user), conn=db.DB):
    t = _get(conn, tid, user)
    _assignee(t, user)
    if t['status'] != 'pending':
        raise HTTPException(400, 'Görev zaten başlatılmış' if t['status'] == 'started' else 'Görev kapalı')
    conn.execute("UPDATE todos SET status = 'started', started_at = ? WHERE id = ?", (db.now(), tid))
    conn.commit()
    if t['created_by'] and t['created_by'] != user['id']:
        _push(t['created_by'], 'Görev başlatıldı', f"{t['assignee_name']} · {t['title']}", '/app#/my-todos/given')
    return _pub(conn, _get(conn, tid, user))


class CompleteIn(BaseModel):
    result: Optional[str] = None


@router.post('/{tid}/complete')
def complete(tid: int, body: CompleteIn, user=Depends(auth.current_user), conn=db.DB):
    t = _get(conn, tid, user)
    _assignee(t, user)
    if t['status'] != 'started':
        raise HTTPException(400, 'Önce görevi başlatın' if t['status'] == 'pending' else 'Görev zaten kapalı')
    now = db.now()
    elapsed = int(t['elapsed_s'] or 0) + _elapsed(t, now)
    conn.execute("UPDATE todos SET status = 'done', done_at = ?, elapsed_s = ?, result = ? WHERE id = ?",
                 (now, elapsed, (body.result or '').strip()[:4000] or None, tid))
    conn.execute('UPDATE todo_items SET done = 1, done_at = COALESCE(done_at, ?) WHERE todo_id = ? AND done = 0', (now, tid))
    conn.commit()
    if t['created_by'] and t['created_by'] != user['id']:
        _push(t['created_by'], 'Görev tamamlandı', f"{t['assignee_name']} · {t['title']}", '/app#/my-todos/given')
    return _pub(conn, _get(conn, tid, user))


# ---------------------------------------------------------------- maddeler (yapılan işler)
class ItemIn(BaseModel):
    text: str


@router.post('/{tid}/items')
def add_item(tid: int, body: ItemIn, user=Depends(auth.current_user), conn=db.DB):
    t = _get(conn, tid, user)
    _assignee(t, user)
    text = (body.text or '').strip()[:1000]
    if not text:
        raise HTTPException(400, 'Madde boş olamaz')
    if t['status'] == 'pending':
        raise HTTPException(400, 'Önce görevi başlatın')
    sort = conn.execute('SELECT COALESCE(MAX(sort), 0) + 1 FROM todo_items WHERE todo_id = ?', (tid,)).fetchone()[0]
    conn.execute('INSERT INTO todo_items (todo_id, text, sort, created_by, created_at) VALUES (?,?,?,?,?)', (tid, text, sort, user['id'], db.now()))
    conn.commit()
    return _pub(conn, _get(conn, tid, user))


class ItemPatch(BaseModel):
    text: Optional[str] = None
    done: Optional[bool] = None


@router.put('/{tid}/items/{iid}')
def update_item(tid: int, iid: int, body: ItemPatch, user=Depends(auth.current_user), conn=db.DB):
    t = _get(conn, tid, user)
    _assignee(t, user)
    it = db.row(conn.execute('SELECT * FROM todo_items WHERE id = ? AND todo_id = ?', (iid, tid)))
    if not it:
        raise HTTPException(404, 'Madde bulunamadı')
    text = it['text'] if body.text is None else (body.text.strip()[:1000] or it['text'])
    done = it['done'] if body.done is None else int(bool(body.done))
    done_at = it['done_at'] if body.done is None else (db.now() if done else None)
    conn.execute('UPDATE todo_items SET text = ?, done = ?, done_at = ? WHERE id = ?', (text, done, done_at, iid))
    conn.commit()
    return _pub(conn, _get(conn, tid, user))


@router.delete('/{tid}/items/{iid}')
def delete_item(tid: int, iid: int, user=Depends(auth.current_user), conn=db.DB):
    t = _get(conn, tid, user)
    _assignee(t, user)
    conn.execute('DELETE FROM todo_items WHERE id = ? AND todo_id = ?', (iid, tid))
    conn.commit()
    return _pub(conn, _get(conn, tid, user))
