"""Bölümler (esnaf): berber/kuaför için odalar (Kadın, Erkek, VIP, Ağda…), lokanta için salonlar/katlar + masalar.

Lokanta bölümünde masa yönetimi de buradadır (ad, şekil yuvarlak/kare, kişi kapasitesi, sorumlu garson, yerleşim).
Garson ekranı (waiter) bu masaları yerleşim olarak çizer. config.ESNAF_PKG değeri arayüzü yönlendirir.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/sections')


def sec_user(user=Depends(auth.current_user)):
    if 'sections' not in user['modules']:
        raise HTTPException(403, 'Bölümler modülü bu firmada kapalı')
    return user


@router.get('')
def list_sections(user=Depends(sec_user), conn=db.DB):
    """Bölümler + (varsa) her bölümün masaları."""
    secs = db.rows(conn.execute('SELECT * FROM shop_sections WHERE active = 1 ORDER BY sort, id'))
    tables = db.rows(conn.execute('SELECT * FROM shop_tables WHERE active = 1 ORDER BY sort, id'))
    by_sec = {}
    for t in tables:
        t['smoking'] = None
        by_sec.setdefault(t['section_id'], []).append(t)
    for s in secs:
        s['smoking'] = bool(s['smoking'])
        s['tables'] = by_sec.get(s['id'], [])
    return secs


class SectionIn(BaseModel):
    name: str
    kind: str = 'room'
    smoking: bool = False


@router.post('')
def add_section(body: SectionIn, user=Depends(sec_user), conn=db.DB):
    name = (body.name or '').strip()[:120]
    if not name:
        raise HTTPException(400, 'Bölüm adı gerekli')
    kind = body.kind if body.kind in ('room', 'hall') else 'room'
    srt = conn.execute('SELECT COALESCE(MAX(sort), 0) + 1 FROM shop_sections').fetchone()[0]
    sid = conn.execute('INSERT INTO shop_sections (name, kind, smoking, sort, created_at) VALUES (?,?,?,?,?)',
                       (name, kind, int(body.smoking), srt, db.now())).lastrowid
    conn.commit()
    db.audit(conn, user['id'], 'Bölüm ekledi', 'shop_section', sid, name)
    return {'id': sid}


@router.put('/{sid}')
def edit_section(sid: int, body: SectionIn, user=Depends(sec_user), conn=db.DB):
    name = (body.name or '').strip()[:120]
    if not name:
        raise HTTPException(400, 'Bölüm adı gerekli')
    kind = body.kind if body.kind in ('room', 'hall') else 'room'
    if not conn.execute('UPDATE shop_sections SET name = ?, kind = ?, smoking = ? WHERE id = ?',
                        (name, kind, int(body.smoking), sid)).rowcount:
        raise HTTPException(404, 'Bölüm bulunamadı')
    conn.commit()
    return {'ok': True}


@router.delete('/{sid}')
def del_section(sid: int, user=Depends(sec_user), conn=db.DB):
    conn.execute('UPDATE shop_sections SET active = 0 WHERE id = ?', (sid,))
    conn.commit()
    return {'ok': True}


# ---------- Masalar (lokanta) ----------
class TableIn(BaseModel):
    section_id: Optional[int] = None
    name: str
    shape: str = 'square'
    seats: int = 4
    waiter_id: Optional[int] = None


@router.post('/tables')
def add_table(body: TableIn, user=Depends(sec_user), conn=db.DB):
    name = (body.name or '').strip()[:60]
    if not name:
        raise HTTPException(400, 'Masa adı gerekli')
    shape = body.shape if body.shape in ('square', 'round') else 'square'
    srt = conn.execute('SELECT COALESCE(MAX(sort), 0) + 1 FROM shop_tables').fetchone()[0]
    tid = conn.execute(
        'INSERT INTO shop_tables (section_id, name, shape, seats, waiter_id, sort, created_at) VALUES (?,?,?,?,?,?,?)',
        (body.section_id, name, shape, max(1, int(body.seats or 1)), body.waiter_id, srt, db.now())).lastrowid
    conn.commit()
    db.audit(conn, user['id'], 'Masa ekledi', 'shop_table', tid, name)
    return {'id': tid}


@router.put('/tables/{tid}')
def edit_table(tid: int, body: TableIn, user=Depends(sec_user), conn=db.DB):
    name = (body.name or '').strip()[:60]
    if not name:
        raise HTTPException(400, 'Masa adı gerekli')
    shape = body.shape if body.shape in ('square', 'round') else 'square'
    if not conn.execute(
            'UPDATE shop_tables SET section_id = ?, name = ?, shape = ?, seats = ?, waiter_id = ? WHERE id = ?',
            (body.section_id, name, shape, max(1, int(body.seats or 1)), body.waiter_id, tid)).rowcount:
        raise HTTPException(404, 'Masa bulunamadı')
    conn.commit()
    return {'ok': True}


@router.delete('/tables/{tid}')
def del_table(tid: int, user=Depends(sec_user), conn=db.DB):
    conn.execute('UPDATE shop_tables SET active = 0 WHERE id = ?', (tid,))
    conn.commit()
    return {'ok': True}


class LayoutItem(BaseModel):
    id: int
    pos_x: float
    pos_y: float


@router.post('/tables/layout')
def save_layout(items: list[LayoutItem], user=Depends(sec_user), conn=db.DB):
    """Garson yerleşim ekranında masaların konumunu (oranlı 0–1) kaydet."""
    for it in items:
        conn.execute('UPDATE shop_tables SET pos_x = ?, pos_y = ? WHERE id = ?',
                     (max(0.0, min(1.0, it.pos_x)), max(0.0, min(1.0, it.pos_y)), it.id))
    conn.commit()
    return {'ok': True}
