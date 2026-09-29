"""Raporlar modülü API'si: kullanıcının girebildiği modüllerin raporları ve rapor verisi (app/reports.py)."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException

from .. import auth, db, reports

router = APIRouter(prefix='/api/reports')
reports_user = auth.require_module('reports')


@router.get('')
def list_reports(user=Depends(reports_user)):
    return [{k: r[k] for k in ('key', 'module', 'title', 'desc')} for r in reports.visible(user)]


@router.get('/{key}')
def run_report(key: str, date_from: str = '', date_to: str = '', user=Depends(reports_user), conn=db.DB):
    r = next((x for x in reports.visible(user) if x['key'] == key), None)
    if not r:
        raise HTTPException(404, 'Rapor bulunamadı ya da yetkiniz yok')
    try:
        d1 = date.fromisoformat(date_to) if date_to else date.today()
        d0 = date.fromisoformat(date_from) if date_from else d1 - timedelta(days=29)
    except ValueError:
        raise HTTPException(400, 'Tarih geçersiz') from None
    if d0 > d1:
        raise HTTPException(400, 'Başlangıç tarihi bitişten sonra olamaz')
    if (d1 - d0).days > 366:
        raise HTTPException(400, 'Tarih aralığı en fazla bir yıl olabilir')
    p = {'from': d0.isoformat(), 'to': d1.isoformat()}
    data = r['fn'](conn, p)
    db.audit(conn, user['id'], 'Rapor görüntüledi', 'report', None, f'{r["title"]} ({p["from"]} – {p["to"]})')
    return {'key': key, 'module': r['module'], 'title': r['title'], 'desc': r['desc'], 'params': p, **data}
