"""Dron Yönetimi › Veri Paketleri API'si (RBAC 'drone.packages': okuma = liste / tüketim, yazma = ekle / düzenle / sil).
Uçuş bağlantısı formu için kısa liste (/options) Saha Yönetimi ya da Canlı Uçuş yetkisiyle de okunur. İş mantığı app/data_packages.py."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, data_packages as dp, db

router = APIRouter(prefix='/api/drone/packages')
packages_user = auth.require_module('drone.packages')


class PackageIn(BaseModel):
    name: str
    provider: Optional[str] = None
    period: str = 'AYLIK'
    quota_mb: float
    price: Optional[float] = None
    currency: str = 'USD'
    overage_per_mb: Optional[float] = None
    start_date: str
    auto_renew: bool = True
    sim_count: Optional[int] = None
    note: Optional[str] = None
    active: bool = True


def _can_write(user):
    return 'drone.packages' in (user.get('write_modules') or [])


def _check(body):
    name = (body.name or '').strip()
    if not name:
        raise HTTPException(400, 'Paket adı gerekli')
    if body.period not in dp.PERIODS:
        raise HTTPException(400, 'Dönem aylık, 3 aylık, 6 aylık ya da yıllık olmalı')
    if not body.quota_mb or body.quota_mb <= 0 or body.quota_mb > 10_000_000:
        raise HTTPException(400, 'Dahil veri (MB) sıfırdan büyük olmalı')
    for v, label in ((body.price, 'Fiyat'), (body.overage_per_mb, 'Aşım ücreti')):
        if v is not None and v < 0:
            raise HTTPException(400, f'{label} negatif olamaz')
    if body.sim_count is not None and not 0 <= body.sim_count <= 10000:
        raise HTTPException(400, 'SIM sayısı geçersiz')
    try:
        date.fromisoformat(body.start_date[:10])
    except (TypeError, ValueError):
        raise HTTPException(400, 'Başlangıç tarihi geçersiz') from None
    cur = (body.currency or 'USD').strip().upper()[:3]
    return {'name': name[:120], 'provider': (body.provider or '').strip()[:120] or None, 'period': body.period, 'quota_mb': float(body.quota_mb),
            'price': body.price, 'currency': cur or 'USD', 'overage_per_mb': body.overage_per_mb, 'start_date': body.start_date[:10],
            'auto_renew': int(bool(body.auto_renew)), 'sim_count': body.sim_count, 'note': (body.note or '').strip()[:2000] or None,
            'active': int(bool(body.active))}


def _row(conn, pid):
    r = db.row(conn.execute('SELECT * FROM data_packages WHERE id = ?', (pid,)))
    if not r:
        raise HTTPException(404, 'Paket bulunamadı')
    return r


@router.get('')
def list_packages(user=Depends(packages_user), conn=db.DB):
    rows = db.rows(conn.execute('SELECT * FROM data_packages ORDER BY active DESC, name COLLATE NOCASE'))
    return {'items': [dp.summary(conn, r) for r in rows], 'can_write': _can_write(user),
            'periods': dp.PERIOD_TEXT, 'lines': dp.LINES}


@router.get('/options')
def package_options(user=Depends(auth.current_user), conn=db.DB):
    """Uçuş bağlantısı formu: etkin paketler + kalan (Saha / Canlı Uçuş / Veri Paketleri yetkisi)."""
    mods = user.get('modules') or []
    if not any(m in mods for m in ('drone.packages', 'field', 'field.live')):
        raise HTTPException(403, 'Yetkiniz yok')
    rows = db.rows(conn.execute('SELECT * FROM data_packages WHERE active = 1 ORDER BY name COLLATE NOCASE'))
    keep = ('id', 'name', 'provider', 'period_text', 'quota_mb', 'used_mb', 'remaining_mb', 'pct', 'days_left', 'status', 'period_end')
    return {'items': [{k: s[k] for k in keep} for s in (dp.summary(conn, r) for r in rows)], 'lines': dp.LINES}


@router.get('/{pid}')
def get_package(pid: int, user=Depends(packages_user), conn=db.DB):
    r = _row(conn, pid)
    return {**dp.summary(conn, r), 'usage': dp.usage_detail(conn, r), 'can_write': _can_write(user)}


@router.post('')
def add_package(body: PackageIn, user=Depends(packages_user), conn=db.DB):
    if not _can_write(user):
        raise HTTPException(403, 'Veri Paketleri için yazma yetkiniz yok')
    v = _check(body)
    cur = conn.execute(f'INSERT INTO data_packages ({", ".join(v)}, created_by, created_at) VALUES ({", ".join("?" * len(v))}, ?, ?)',
                       (*v.values(), user['id'], db.now()))
    db.audit(conn, user['id'], 'Veri paketi ekledi', 'data_package', cur.lastrowid, f"{v['name']} · {v['quota_mb']:g} MB · {dp.PERIOD_TEXT[v['period']]}")
    return {'id': cur.lastrowid}


@router.put('/{pid}')
def update_package(pid: int, body: PackageIn, user=Depends(packages_user), conn=db.DB):
    if not _can_write(user):
        raise HTTPException(403, 'Veri Paketleri için yazma yetkiniz yok')
    _row(conn, pid)
    v = _check(body)
    conn.execute(f'UPDATE data_packages SET {", ".join(f"{k} = ?" for k in v)}, updated_at = ? WHERE id = ?', (*v.values(), db.now(), pid))
    db.audit(conn, user['id'], 'Veri paketini düzenledi', 'data_package', pid, f"{v['name']} · {v['quota_mb']:g} MB")
    return {'ok': True}


@router.delete('/{pid}')
def delete_package(pid: int, user=Depends(packages_user), conn=db.DB):
    if not _can_write(user):
        raise HTTPException(403, 'Veri Paketleri için yazma yetkiniz yok')
    r = _row(conn, pid)
    used = conn.execute('SELECT COUNT(*) FROM data_usage WHERE package_id = ?', (pid,)).fetchone()[0]
    if used:
        raise HTTPException(400, 'Tüketim kaydı olan paket silinemez; pasife alın')
    conn.execute('DELETE FROM data_packages WHERE id = ?', (pid,))
    db.audit(conn, user['id'], 'Veri paketini sildi', 'data_package', pid, r['name'])
    return {'ok': True}
