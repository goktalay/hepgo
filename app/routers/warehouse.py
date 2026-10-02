from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, catalogs, db
from ..production import AFTER_ASSEMBLY, ASSEMBLY, WAREHOUSE, approve_field_depot, order_summaries, recompute

router = APIRouter(prefix='/api')
warehouse_user = auth.require_module('warehouse')
stock_user = auth.require_module('stock')

_PART_SELECT = '''
    SELECT op.id, op.part_id, op.state, op.finished_at, op.approved_at,
           o.id AS order_id, o.code AS order_code,
           d.full_name AS delivered_to_name, a.full_name AS approved_by_name,
           p.name AS printer_name,
           (SELECT u.full_name FROM part_events e JOIN users u ON u.id = e.user_id
            WHERE e.order_part_id = op.id AND e.event = 'URETIM_TAMAMLANDI' ORDER BY e.id DESC LIMIT 1)
             AS delivered_by_name
    FROM order_parts op
    JOIN orders o ON o.id = op.order_id
    LEFT JOIN users d ON d.id = op.delivered_to
    LEFT JOIN users a ON a.id = op.approved_by
    LEFT JOIN printers p ON p.id = op.printer_id
'''


class ApproveIn(BaseModel):
    ids: list[int]
    at: Optional[str] = None


class AtIn(BaseModel):
    at: Optional[str] = None


@router.get('/warehouse/pending')
def pending(user=Depends(warehouse_user), conn=db.DB):
    return db.rows(conn.execute(
        _PART_SELECT + " WHERE op.state = 'DEPO' AND op.approved_at IS NULL ORDER BY op.finished_at", ()))


@router.get('/warehouse/history')
def history(date_from: str = '', date_to: str = '', user=Depends(warehouse_user), conn=db.DB):
    dc, da = db.date_cond('op.approved_at', date_from, date_to)
    return db.rows(conn.execute(
        _PART_SELECT + f' WHERE op.approved_at IS NOT NULL AND {dc} ORDER BY op.approved_at DESC LIMIT 500', tuple(da)))


@router.post('/warehouse/approve')
def approve(body: ApproveIn, user=Depends(warehouse_user), conn=db.DB):
    if not body.ids:
        raise HTTPException(400, 'Onaylanacak parça seçilmedi')
    last = conn.execute(f"SELECT MAX(finished_at) FROM order_parts WHERE id IN ({','.join('?' * len(body.ids))})",
                        body.ids).fetchone()[0]
    now = db.pick_time(body.at, last, 'Onay zamanı', 'depoya teslim')
    orders = set()
    approved = 0
    for pid in body.ids:
        op = db.row(conn.execute(
            'SELECT op.id, op.order_id, op.part_id, op.state, op.approved_at, o.code FROM order_parts op '
            'JOIN orders o ON o.id = op.order_id WHERE op.id = ?', (pid,)))
        if not op or op['state'] != WAREHOUSE or op['approved_at']:
            continue
        conn.execute('UPDATE order_parts SET approved_by = ?, approved_at = ?, updated_at = ? WHERE id = ?',
                     (user['id'], now, now, pid))
        conn.execute('INSERT INTO part_events (order_part_id, event, user_id, at) VALUES (?,?,?,?)',
                     (pid, 'DEPO_ONAY', user['id'], now))
        db.audit(conn, user['id'], 'Depo girişini onayladı', 'order_part', pid, f'{op["code"]} / {op["part_id"]}')
        orders.add(op['order_id'])
        approved += 1
    for oid in orders:
        recompute(conn, oid, now)
    return {'approved': approved}


# ---------- Saha deposu: kalibrasyonu biten uçakların depocu onayı

@router.get('/warehouse/aircraft')
def aircraft(user=Depends(warehouse_user), conn=db.DB):
    """Saha deposu onayı bekleyen uçaklar ve son onaylananlar."""
    def with_steps(orders):
        for o in orders:
            o['steps'] = {r['step']: r for r in db.rows(conn.execute(
                '''SELECT s.step, s.at, u.full_name AS recorded_by_name FROM assembly_steps s
                   LEFT JOIN users u ON u.id = s.recorded_by WHERE s.order_id = ?''', (o['id'],)))}
        return orders
    pending = with_steps(order_summaries(conn, "o.status = 'SAHA_ONAY'"))
    done = with_steps(order_summaries(
        conn, "o.status = 'TAMAMLANDI' AND EXISTS (SELECT 1 FROM assembly_steps s WHERE s.order_id = o.id AND s.step = 'SAHA_DEPO')"))
    return {'pending': pending, 'approved': done[:200]}


@router.post('/warehouse/aircraft/{oid}/approve')
def approve_aircraft(oid: int, body: AtIn, user=Depends(warehouse_user), conn=db.DB):
    orders = order_summaries(conn, 'o.id = ?', (oid,))
    if not orders:
        raise HTTPException(404, 'Sipariş bulunamadı')
    queue_no = approve_field_depot(conn, orders[0], user['id'], body.at)
    db.audit(conn, user['id'], 'Uçağı saha deposuna aldı', 'order', oid, f'{orders[0]["code"]} → {queue_no}')
    return {'queue_no': queue_no}


@router.get('/stock')
def stock(product_id: Optional[int] = None, user=Depends(stock_user), conn=db.DB):
    """Seçilen ürün tipinin stoğu (varsayılan: ilk aktif ürün)."""
    product = db.row(conn.execute(
        'SELECT * FROM products WHERE id = ?' if product_id else 'SELECT * FROM products ORDER BY active DESC, id LIMIT 1',
        (product_id,) if product_id else ()))
    if not product:
        raise HTTPException(404, 'Ürün bulunamadı')
    pid = product['id']
    # saha deposunda bekleyen: tek kullanımlık bir kez sahaya gittiyse sayılmaz; çoklu kullanım görevden dönünce sayılır
    ready = db.rows(conn.execute(
        '''SELECT o.id, o.code, o.queue_no, o.completed_at FROM orders o JOIN products p ON p.id = o.product_id
           WHERE o.product_id = ? AND o.status = 'TAMAMLANDI' AND NOT EXISTS (
               SELECT 1 FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
               WHERE f.order_id = o.id AND t.status != 'IPTAL'
                 AND (COALESCE(p.usage_type, 'TEK') != 'COKLU' OR t.status IN ('BASLANGIC', 'GOREVDE')))
           ORDER BY o.queue_no''', (pid,)))
    # Yarı mamul: üretimi başlamış ama montajı tamamlanmamış uçaklar
    wip = db.rows(conn.execute(
        "SELECT id, code, status FROM orders WHERE product_id = ? AND status NOT IN ('SIPARIS', 'TAMAMLANDI', 'HURDA') ORDER BY id",
        (pid,)))
    ids = catalogs.part_ids(product['schema'])
    counts = {p: 0 for p in ids}
    pending = {p: 0 for p in ids}
    for r in conn.execute(
            f'''SELECT op.part_id, op.approved_at IS NOT NULL, COUNT(*) FROM order_parts op
               JOIN orders o ON o.id = op.order_id
               WHERE o.product_id = ? AND o.status NOT IN ({','.join('?' * len(AFTER_ASSEMBLY))}, 'SAHADA_MONTAJ') AND op.state IN (?, ?)
               GROUP BY op.part_id, op.approved_at IS NOT NULL''', (pid, *AFTER_ASSEMBLY, WAREHOUSE, ASSEMBLY)):
        if r[0] in counts:
            (counts if r[1] else pending)[r[0]] += r[2]
    return {'product': product, 'ready_aircraft': ready, 'wip_aircraft': wip,
            'part_counts': counts, 'pending_counts': pending}
