"""Araçlar → Üretim Planlayıcı: mamul ve adet seçilir; yazıcılara hangi parçaların hangi sırayla yükleneceği
(Gantt şeması ile) hesaplanır. Salt okunur: sipariş açmaz, yazıcıya iş göndermez."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, catalogs, db, planner, semis

router = APIRouter(prefix='/api/planner')
tools_user = auth.require_module('tools')


@router.get('/products')
def products(user=Depends(tools_user), conn=db.DB):
    info = semis.print_info(conn)
    rows = db.rows(conn.execute("SELECT id, code, name, serial, schema FROM products WHERE type = 'MAMUL' AND active = 1 ORDER BY id"))
    for r in rows:
        ids = catalogs.part_ids(r['schema'])
        r['part_count'] = len(ids)
        r['print_minutes'] = sum(info.get(i, {}).get('print_minutes') or 0 for i in ids)
    return rows


class PlanIn(BaseModel):
    product_id: int
    quantity: int = 1
    mode: str = 'aircraft'        # aircraft: uçak uçak | fastest: toplam süre en kısa
    change_minutes: int = 15      # iki baskı arası tabla boşaltma / hazırlık
    assume_idle: bool = False     # True: tüm yazıcılar boşmuş gibi (anlık durum yok sayılır)


@router.post('/plan')
def make_plan(body: PlanIn, user=Depends(tools_user), conn=db.DB):
    product = db.row(conn.execute("SELECT * FROM products WHERE id = ? AND type = 'MAMUL'", (body.product_id,)))
    if not product:
        raise HTTPException(404, 'Mamul bulunamadı')
    if not 1 <= body.quantity <= 50:
        raise HTTPException(400, 'Adet 1–50 arasında olmalı')
    if body.mode not in ('aircraft', 'fastest') or not 0 <= body.change_minutes <= 240:
        raise HTTPException(400, 'Geçersiz plan seçeneği')
    return planner.plan(conn, product, body.quantity, body.mode, body.change_minutes, assume_idle=body.assume_idle)
