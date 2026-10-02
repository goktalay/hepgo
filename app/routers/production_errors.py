"""Araçlar → Üretim Hataları: üretimde parçalara girilen hata kayıtları (hata kodu, açıklama, fotoğraf, yazıcı,
kaydeden) sonradan incelenir. Salt okunur; Üretim, Yazıcı ya da Sipariş modülü olan kullanıcılar görür."""
from fastapi import APIRouter, Depends, HTTPException

from .. import auth, db
from ..production import PART_STATES_TEXT

router = APIRouter(prefix='/api/production-errors')
MODULES = {'production', 'printers', 'orders'}


def errors_user(user=Depends(auth.current_user)):
    if not MODULES & set(user['modules']):
        raise HTTPException(403, 'Bu araca erişim yetkiniz yok')
    return user


@router.get('')
def list_errors(date_from: str = '', date_to: str = '', user=Depends(errors_user), conn=db.DB):
    dc, da = db.date_cond('e.at', date_from, date_to)
    rows = db.rows(conn.execute(
        '''SELECT e.id, e.at, e.error_code, e.note, e.photo,
                  op.part_id, op.state AS part_state, o.id AS order_id, o.code AS order_code, o.queue_no,
                  pr.name AS product_name, c.name AS company_name, c.logo AS company_logo,
                  p.id AS printer_id, p.name AS printer_name, u.id AS user_id, u.full_name AS user_name,
                  (SELECT COUNT(*) FROM part_events x WHERE x.order_part_id = e.order_part_id AND x.event = 'HATA') AS part_errors
           FROM part_events e
           JOIN order_parts op ON op.id = e.order_part_id
           JOIN orders o ON o.id = op.order_id
           LEFT JOIN products pr ON pr.id = o.product_id
           LEFT JOIN companies c ON c.id = o.company_id
           LEFT JOIN printers p ON p.id = e.printer_id
           LEFT JOIN users u ON u.id = e.user_id
           WHERE e.event = 'HATA' AND ''' + dc + '''
           ORDER BY e.at DESC, e.id DESC''', da))
    for r in rows:
        r['part_state_text'] = PART_STATES_TEXT.get(r['part_state'], r['part_state'])
    return rows
