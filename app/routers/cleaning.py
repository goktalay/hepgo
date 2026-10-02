"""Temizlik modülü: günlük yapılacak işler çeklisti. Temizlik görevlisi (ve Sistem Yöneticisi) listeyi görür;
bir işe tıklayınca o günün kaydına 'yapıldı' saati ve kim yaptığı düşer, açıklama girilebilir. Üstte tarih seçilip
geri / ileri gezilebilir. Çeklist maddelerini Sistem Yöneticisi (Program Ayarları › Modül Ayarları › Temizlik) düzenler.
"""
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/cleaning')
cleaning_user = auth.require_module('cleaning')
admin_user = auth.require_module('admin')


def _valid_day(s):
    try:
        return _date.fromisoformat((s or '')[:10]).isoformat()
    except (TypeError, ValueError):
        return _date.today().isoformat()


class MarkIn(BaseModel):
    date: str = None
    note: str = None
    done: bool = True


class ItemIn(BaseModel):
    label: str


@router.get('')
def day_checklist(date: str = None, user=Depends(cleaning_user), conn=db.DB):
    """Seçili günün çeklisti: aktif maddeler + o günkü yapıldı kaydı."""
    day = _valid_day(date)
    rows = db.rows(conn.execute(
        '''SELECT i.id, i.label, l.done_at, l.note, u.full_name AS done_by_name
           FROM cleaning_items i
           LEFT JOIN cleaning_log l ON l.item_id = i.id AND l.day = ?
           LEFT JOIN users u ON u.id = l.done_by
           WHERE i.active = 1 ORDER BY i.sort, i.id''', (day,)))
    done = sum(1 for r in rows if r['done_at'])
    return {'date': day, 'items': rows, 'done': done, 'total': len(rows)}


# ---------- Çeklist yönetimi (Sistem Yöneticisi) — /items yolları /{item_id}'den ÖNCE tanımlanmalı ----------
@router.get('/items')
def list_items(user=Depends(admin_user), conn=db.DB):
    return db.rows(conn.execute('SELECT id, label, sort, active FROM cleaning_items ORDER BY sort, id'))


@router.post('/items')
def add_item(body: ItemIn, user=Depends(admin_user), conn=db.DB):
    label = (body.label or '').strip()[:200]
    if not label:
        raise HTTPException(400, 'İş adı girin')
    nxt = (conn.execute('SELECT MAX(sort) FROM cleaning_items').fetchone()[0] or 0) + 1
    cur = conn.execute('INSERT INTO cleaning_items (label, sort, active, created_at) VALUES (?,?,1,?)', (label, nxt, db.now()))
    return {'id': cur.lastrowid}


@router.put('/items/{item_id}')
def edit_item(item_id: int, body: ItemIn, user=Depends(admin_user), conn=db.DB):
    label = (body.label or '').strip()[:200]
    if not label:
        raise HTTPException(400, 'İş adı girin')
    if not conn.execute('UPDATE cleaning_items SET label = ? WHERE id = ?', (label, item_id)).rowcount:
        raise HTTPException(404, 'İş bulunamadı')
    return {'ok': True}


@router.post('/items/{item_id}/move')
def move_item(item_id: int, dir: str = 'up', user=Depends(admin_user), conn=db.DB):
    """Maddeyi listede yukarı / aşağı taşır (komşuyla sort değiştirir)."""
    items = db.rows(conn.execute('SELECT id, sort FROM cleaning_items WHERE active = 1 ORDER BY sort, id'))
    idx = next((i for i, r in enumerate(items) if r['id'] == item_id), None)
    if idx is None:
        raise HTTPException(404, 'İş bulunamadı')
    j = idx - 1 if dir == 'up' else idx + 1
    if 0 <= j < len(items):
        a, b = items[idx], items[j]
        conn.execute('UPDATE cleaning_items SET sort = ? WHERE id = ?', (b['sort'], a['id']))
        conn.execute('UPDATE cleaning_items SET sort = ? WHERE id = ?', (a['sort'], b['id']))
    return {'ok': True}


@router.delete('/items/{item_id}')
def delete_item(item_id: int, user=Depends(admin_user), conn=db.DB):
    """Maddeyi listeden kaldırır (geçmiş kayıtlar korunur: pasife alınır)."""
    if not conn.execute('UPDATE cleaning_items SET active = 0 WHERE id = ?', (item_id,)).rowcount:
        raise HTTPException(404, 'İş bulunamadı')
    return {'ok': True}


# /{item_id} en sonda: /items gibi özel yolları gölgelememesi için
@router.post('/{item_id}')
def mark(item_id: int, body: MarkIn, user=Depends(cleaning_user), conn=db.DB):
    """Bir işi 'yapıldı' işaretler (saat + kim) ya da geri alır; açıklama kaydeder."""
    it = db.row(conn.execute('SELECT * FROM cleaning_items WHERE id = ? AND active = 1', (item_id,)))
    if not it:
        raise HTTPException(404, 'İş bulunamadı')
    day = _valid_day(body.date)
    note = (body.note or '').strip()[:500] or None
    ex = db.row(conn.execute('SELECT id FROM cleaning_log WHERE item_id = ? AND day = ?', (item_id, day)))
    done_at = db.now() if body.done else None
    done_by = user['id'] if body.done else None
    if ex:
        conn.execute('UPDATE cleaning_log SET done_at = ?, done_by = ?, note = ? WHERE id = ?', (done_at, done_by, note, ex['id']))
    else:
        conn.execute('INSERT INTO cleaning_log (item_id, day, done_at, done_by, note) VALUES (?,?,?,?,?)',
                     (item_id, day, done_at, done_by, note))
    return {'ok': True, 'done_at': done_at}
