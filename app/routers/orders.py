from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, catalogs, db, production
from ..files import save_upload
from ..production import (AFTER_ASSEMBLY, IN_ASSEMBLY, ERROR, EVENT_TEXT, PRINTING, WAITING, WAREHOUSE, assembly_info,
                          complete_calibration, complete_covers, complete_electronics, complete_final, complete_section, create_order,
                          order_summaries, recompute)

router = APIRouter(prefix='/api/orders')


def _order_reader(user=Depends(auth.current_user)):
    if not {'orders', 'production'} & set(user['modules']):
        raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
    return user


orders_user = auth.require_module('orders')
production_user = auth.require_module('production')


def part_operator(user=Depends(production_user)):
    """Parçayı üretime alma, teslim ve hata: üretim rolleri (montaj personeli yalnızca montaj yapar)."""
    if not set(auth.PART_OPERATORS) & set(user['roles']):
        raise HTTPException(403, 'Parça işlemleri için yetkiniz yok')
    return user


class OrderIn(BaseModel):
    product_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    note: Optional[str] = None
    quantity: int = 1
    company_id: Optional[int] = None   # siparişin firması


class CompanyIn(BaseModel):
    company_id: Optional[int] = None


def _check_company(conn, cid):
    if cid is not None and not conn.execute('SELECT 1 FROM companies WHERE id = ? AND active = 1 AND is_supplier = 0', (cid,)).fetchone():
        raise HTTPException(400, 'Geçerli bir firma seçin')


class StartIn(BaseModel):
    printer_id: int
    at: Optional[str] = None


class FinishIn(BaseModel):
    warehouse_user_id: int
    at: Optional[str] = None


class SectionIn(BaseModel):
    staff_ids: list[int] = []
    at: Optional[str] = None


class CalibrationIn(SectionIn):
    checklist: dict = {}


@router.get('')
def list_orders(include_done: bool = True, date_from: str = '', date_to: str = '', user=Depends(_order_reader), conn=db.DB):
    """Siparişler. Tarih aralığı verilirse: açık siparişler her zaman, kapanmışlar (tamamlandı / hurda) yalnızca
    açılışı ya da tamamlanması bu aralıktaysa (listeler varsayılan 'bu hafta' ile hızlı açılsın)."""
    if not include_done:
        return order_summaries(conn, "o.status NOT IN ('TAMAMLANDI', 'HURDA')")
    if date_from or date_to:
        c1, a1 = db.date_cond('o.created_at', date_from, date_to)
        c2, a2 = db.date_cond('o.completed_at', date_from, date_to)
        return order_summaries(conn, f"(o.status NOT IN ('TAMAMLANDI', 'HURDA') OR ({c1}) OR ({c2}))", (*a1, *a2))
    return order_summaries(conn)


@router.get('/companies')
def order_companies(user=Depends(_order_reader), conn=db.DB):
    """Sipariş formundaki firma listesi (Firma Yönetimi modülü olmayanlar için de)."""
    return db.rows(conn.execute('SELECT id, name, logo FROM companies WHERE active = 1 AND is_supplier = 0 ORDER BY name'))


@router.put('/{oid}/company')
def set_company(oid: int, body: CompanyIn, user=Depends(orders_user), conn=db.DB):
    order = _get_order(conn, oid)
    _check_company(conn, body.company_id)
    conn.execute('UPDATE orders SET company_id = ? WHERE id = ?', (body.company_id, oid))
    name = conn.execute('SELECT name FROM companies WHERE id = ?', (body.company_id,)).fetchone() if body.company_id else None
    db.audit(conn, user['id'], 'Siparişin firmasını değiştirdi', 'order', oid, f'{order["code"]} → {name[0] if name else "firma yok"}')
    return {'ok': True}


@router.post('')
def new_orders(body: OrderIn, user=Depends(orders_user), conn=db.DB):
    if body.quantity != 1:   # her sipariş tek üretimdir (tek uçak / tek baskı)
        raise HTTPException(400, 'Her sipariş tek üretimdir; birden fazla için ayrı sipariş açın')
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, 'Bitiş tarihi başlangıçtan önce olamaz')
    if body.product_id is None:
        product = db.row(conn.execute('SELECT * FROM products WHERE active = 1 AND orderable = 1 ORDER BY id LIMIT 1'))
    else:   # ürün ayarı: sipariş verilebilir (yarı mamuller hiçbir zaman; CAYMAZ montajında üretilir)
        product = db.row(conn.execute('SELECT * FROM products WHERE id = ? AND active = 1 AND orderable = 1',
                                      (body.product_id,)))
    if not product:
        raise HTTPException(400, 'Geçerli bir ürün seçin')
    _check_company(conn, body.company_id)
    created = []
    for _ in range(body.quantity):
        oid, code = create_order(conn, user['id'], product, body.start_date, body.end_date, body.note, body.company_id)
        db.audit(conn, user['id'], 'Sipariş oluşturdu', 'order', oid, code)
        created.append({'id': oid, 'code': code})
        try:
            from .. import feed
            img = product['image'] if 'image' in product.keys() and product['image'] else None
            media = [{'type': 'image', 'path': img if '/' in str(img) else f'products/{img}'}] if img else None
            feed.add_event(conn, 'ORDER', f'Yeni sipariş: {code} · {product["name"]}', 'order', oid, f'#/orders/{oid}', media=media)
        except Exception:   # noqa: BLE001
            pass
    return created


def _queue(conn, oid, status):
    """Kalibrasyona geçen uçağın yeni kuyruk numarası (montaj bitti bildirimi için)."""
    return conn.execute('SELECT queue_no FROM orders WHERE id = ?', (oid,)).fetchone()[0] if status == 'KALIBRASYON' else None


def _get_order(conn, oid):
    orders = order_summaries(conn, 'o.id = ?', (oid,))
    if not orders:
        raise HTTPException(404, 'Sipariş bulunamadı')
    return orders[0]


@router.get('/{oid}')
def get_order(oid: int, user=Depends(_order_reader), conn=db.DB):
    order = _get_order(conn, oid)
    order['parts'] = db.rows(conn.execute(
        '''SELECT op.id, op.part_id, op.state, op.started_at, op.finished_at, op.approved_at,
                  op.printer_started_at, op.printer_done_at, op.print_seconds, p.name AS printer_name,
                  EXISTS(SELECT 1 FROM direct_part_requests d WHERE d.order_part_id = op.id AND d.status = 'BEKLIYOR') AS direct_pending
           FROM order_parts op LEFT JOIN printers p ON p.id = op.printer_id
           WHERE op.order_id = ?''', (oid,)))
    order['assembly'] = assembly_info(conn, order)
    order['field_task'] = db.row(conn.execute(   # uçağın bulunduğu açık saha görevi
        '''SELECT t.id, t.code, t.status FROM field_tasks t JOIN field_flights f ON f.task_id = t.id
           WHERE f.order_id = ? AND t.status IN ('BASLANGIC', 'GOREVDE') ORDER BY t.id DESC LIMIT 1''', (oid,)))
    return order


@router.get('/{oid}/timeline')
def order_timeline(oid: int, user=Depends(_order_reader), conn=db.DB):
    """Sipariş detayı: aşamalar (birbirine bağlı kartlar) ve siparişin özeti."""
    order = _get_order(conn, oid)
    return {'order': order, 'stages': production.order_timeline(conn, order)}


@router.delete('/{oid}')
def delete_order(oid: int, user=Depends(orders_user), conn=db.DB):
    order = _get_order(conn, oid)
    if order['status'] != 'SIPARIS':
        raise HTTPException(400, 'Üretimi başlamış sipariş silinemez')
    conn.execute('DELETE FROM orders WHERE id = ?', (oid,))
    db.audit(conn, user['id'], 'Sipariş sildi', 'order', oid, order['code'])
    return {'ok': True}


@router.post('/{oid}/assembly/{section}')
def assembly_section(oid: int, section: str, body: SectionIn, user=Depends(production_user), conn=db.DB):
    """Montaj bölümü (sol kanat, sağ kanat, orta gövde) tamamlandı; üçü bitince uçak kalibrasyona geçer."""
    order = _get_order(conn, oid)
    status = complete_section(conn, order, section, user['id'], body.at, body.staff_ids)
    name = assembly_info(conn, order)['sections'][section]
    db.audit(conn, user['id'], 'Montaj bölümünü tamamladı', 'order', oid, f'{order["code"]} / {name}')
    return {'status': status, 'queue_no': _queue(conn, oid, status)}


@router.post('/{oid}/electronics/{part_id}')
def electronics(oid: int, part_id: str, body: SectionIn, user=Depends(production_user), conn=db.DB):
    """Elektronik parçaya (elektronik kat, K04) komponentler monte edildi; hepsi ve montaj bittiyse uçak kalibrasyona geçer."""
    order = _get_order(conn, oid)
    status = complete_electronics(conn, order, part_id, user['id'], body.at, body.staff_ids)
    db.audit(conn, user['id'], 'Elektronik montajı tamamladı', 'order', oid, f'{order["code"]} / {part_id}')
    return {'status': status, 'queue_no': _queue(conn, oid, status)}


@router.post('/{oid}/final')
def final_assembly(oid: int, body: CalibrationIn, user=Depends(production_user), conn=db.DB):
    """Birleştirme montajı: kanatlar ve elektronik parçalar gövdeye takıldı; uçak kalibrasyona geçer."""
    order = _get_order(conn, oid)
    status = complete_final(conn, order, user['id'], body.at, body.staff_ids, body.checklist)
    db.audit(conn, user['id'], 'Birleştirme montajını tamamladı', 'order', oid, order['code'])
    return {'status': status, 'queue_no': _queue(conn, oid, status)}


@router.post('/{oid}/covers')
def cover_assembly(oid: int, body: SectionIn, user=Depends(production_user), conn=db.DB):
    """Kapak montajı: kapaklar en son (birleştirmeden sonra) takılır; uçak kalibrasyona geçer."""
    order = _get_order(conn, oid)
    status = complete_covers(conn, order, user['id'], body.at, body.staff_ids)
    db.audit(conn, user['id'], 'Kapak montajını tamamladı', 'order', oid, order['code'])
    return {'status': status, 'queue_no': _queue(conn, oid, status)}


@router.post('/{oid}/calibration')
def calibration(oid: int, body: CalibrationIn, user=Depends(production_user), conn=db.DB):
    """Kalibrasyon tamamlandı; uçak saha deposu onayı için depocuya düşer."""
    order = _get_order(conn, oid)
    complete_calibration(conn, order, user['id'], body.at, body.staff_ids, body.checklist)
    db.audit(conn, user['id'], 'Kalibrasyonu tamamladı', 'order', oid, order['code'])
    return {'status': 'SAHA_ONAY'}


# --- Parça işlemleri

def _get_part(conn, oid, part_id):
    op = db.row(conn.execute(
        '''SELECT op.*, o.code AS order_code, o.status AS order_status, p.name AS printer_name,
                  pr.schema AS product_schema
           FROM order_parts op JOIN orders o ON o.id = op.order_id
           LEFT JOIN products pr ON pr.id = o.product_id
           LEFT JOIN printers p ON p.id = op.printer_id
           WHERE op.order_id = ? AND op.part_id = ?''', (oid, part_id)))
    if not op:
        raise HTTPException(404, 'Parça bulunamadı')
    return op


def _check_open(op):
    # Elektronik parçalar, uçak montajdayken de üretilebilir (montaja onlarsız geçmiş eski kayıtlar için)
    if op['order_status'] in IN_ASSEMBLY and op['part_id'] in catalogs.electronics_parts(op['product_schema']):
        return
    if op['order_status'] in IN_ASSEMBLY or op['order_status'] in AFTER_ASSEMBLY:
        raise HTTPException(400, 'Bu uçak montaj aşamasına geçmiş; parça işlemi yapılamaz')


def _release_printer(conn, op, now):
    if op['printer_id']:
        conn.execute('''UPDATE printers SET current_part_id = NULL, last_job_end = ?
                        WHERE id = ? AND current_part_id = ?''', (now, op['printer_id'], op['id']))


@router.get('/{oid}/parts/{part_id}')
def part_detail(oid: int, part_id: str, user=Depends(_order_reader), conn=db.DB):
    op = _get_part(conn, oid, part_id)
    events = db.rows(conn.execute(
        '''SELECT e.*, u.full_name AS user_name, t.full_name AS target_name, p.name AS printer_name
           FROM part_events e
           LEFT JOIN users u ON u.id = e.user_id
           LEFT JOIN users t ON t.id = e.target_user
           LEFT JOIN printers p ON p.id = e.printer_id
           WHERE e.order_part_id = ? ORDER BY e.id''', (op['id'],)))
    for e in events:
        e['text'] = EVENT_TEXT.get(e['event'], e['event'])
    op['events'] = events
    if op['state'] == PRINTING and op['started_at']:
        op['elapsed_seconds'] = int((datetime.now() - datetime.fromisoformat(op['started_at'])).total_seconds())
    if op['state'] == PRINTING and op['printer_id']:   # yazıcının şu anki durumu (bu parçayı basıyorsa)
        op['printer_live'] = db.row(conn.execute(
            '''SELECT live_state AS state, live_progress AS progress, live_file AS file, live_print_s AS print_s, last_seen
               FROM printers WHERE id = ? AND current_part_id = ?''', (op['printer_id'], op['id'])))
    if op['delivered_to']:
        op['delivered_to_name'] = conn.execute('SELECT full_name FROM users WHERE id = ?',
                                               (op['delivered_to'],)).fetchone()[0]
    op['group'] = catalogs.part_meta(op['product_schema'], part_id)['group']
    op['direct_request'] = db.row(conn.execute(
        """SELECT d.*, pr.name AS printer_name, ru.full_name AS requested_by_name, du.full_name AS decided_by_name
           FROM direct_part_requests d LEFT JOIN printers pr ON pr.id = d.printer_id
           LEFT JOIN users ru ON ru.id = d.requested_by LEFT JOIN users du ON du.id = d.decided_by
           WHERE d.order_part_id = ? ORDER BY d.id DESC LIMIT 1""", (op['id'],)))
    op['can_approve_direct'] = auth.ADMIN in user['roles']
    return op


@router.post('/{oid}/parts/{part_id}/start')
def start_part(oid: int, part_id: str, body: StartIn, user=Depends(part_operator), conn=db.DB):
    op = _get_part(conn, oid, part_id)
    _check_open(op)
    if op['state'] not in (WAITING, ERROR):
        raise HTTPException(400, 'Bu parça zaten üretimde veya üretilmiş')
    if conn.execute("SELECT 1 FROM direct_part_requests WHERE order_part_id = ? AND status = 'BEKLIYOR'", (op['id'],)).fetchone():
        raise HTTPException(409, 'Bu parça için doğrudan depo ekleme talebi Sistem Yöneticisi onayında')
    printer = db.row(conn.execute('SELECT * FROM printers WHERE id = ?', (body.printer_id,)))
    if not printer:
        raise HTTPException(404, 'Yazıcı bulunamadı')
    if printer['current_part_id']:
        busy = db.row(conn.execute(
            '''SELECT o.code, op.part_id FROM order_parts op JOIN orders o ON o.id = op.order_id
               WHERE op.id = ?''', (printer['current_part_id'],)))
        if busy:
            raise HTTPException(409, f'{printer["name"]} meşgul: {busy["code"]} / {busy["part_id"]} basılıyor')
    last = conn.execute('SELECT MAX(at) FROM part_events WHERE order_part_id = ?', (op['id'],)).fetchone()[0]
    now = db.pick_time(body.at, last, 'Başlama zamanı', 'parçanın son işlemi')
    conn.execute('''UPDATE order_parts SET state = ?, printer_id = ?, started_at = ?, finished_at = NULL,
                    delivered_to = NULL, approved_by = NULL, approved_at = NULL, printer_started_at = NULL,
                    printer_done_at = NULL, print_seconds = NULL, updated_at = ? WHERE id = ?''',
                 (PRINTING, printer['id'], now, now, op['id']))
    conn.execute('''UPDATE printers SET current_part_id = ?, last_job = ?, last_job_start = ?, last_job_end = NULL
                    WHERE id = ?''', (op['id'], f'{op["order_code"]} / {part_id}', now, printer['id']))
    conn.execute('INSERT INTO part_events (order_part_id, event, user_id, printer_id, at) VALUES (?,?,?,?,?)',
                 (op['id'], 'URETIME_BASLADI', user['id'], printer['id'], now))
    db.audit(conn, user['id'], 'Parça üretimine başladı', 'order_part', op['id'],
             f'{op["order_code"]} / {part_id} → {printer["name"]}')
    recompute(conn, oid)
    return {'ok': True}


@router.post('/{oid}/parts/{part_id}/finish')
def finish_part(oid: int, part_id: str, body: FinishIn, user=Depends(part_operator), conn=db.DB):
    op = _get_part(conn, oid, part_id)
    _check_open(op)
    if op['state'] != PRINTING:
        raise HTTPException(400, 'Parça üretimde değil')
    keeper = conn.execute(
        '''SELECT u.full_name FROM users u JOIN user_roles r ON r.user_id = u.id
           WHERE u.id = ? AND r.role = ? AND u.active = 1''',
        (body.warehouse_user_id, auth.WAREHOUSE_MANAGER)).fetchone()
    if not keeper:
        raise HTTPException(400, 'Seçilen kişi depo yöneticisi değil')
    now = db.pick_time(body.at, op['started_at'], 'Teslim zamanı', 'üretime başlama')
    conn.execute('''UPDATE order_parts SET state = ?, finished_at = ?, delivered_to = ?, updated_at = ?
                    WHERE id = ?''', (WAREHOUSE, now, body.warehouse_user_id, now, op['id']))
    _release_printer(conn, op, now)
    conn.execute('''INSERT INTO part_events (order_part_id, event, user_id, printer_id, target_user, at)
                    VALUES (?,?,?,?,?,?)''',
                 (op['id'], 'URETIM_TAMAMLANDI', user['id'], op['printer_id'], body.warehouse_user_id, now))
    db.audit(conn, user['id'], 'Parça üretimini tamamladı', 'order_part', op['id'],
             f'{op["order_code"]} / {part_id} → {keeper[0]}')
    recompute(conn, oid)
    return {'ok': True}


class DirectIn(BaseModel):
    printer_id: int
    at: Optional[str] = None


class DirectDecideIn(BaseModel):
    note: Optional[str] = None


@router.post('/{oid}/parts/{part_id}/direct-request')
def direct_request(oid: int, part_id: str, body: DirectIn, user=Depends(part_operator), conn=db.DB):
    """Parçayı seçili yazıcıyla basılmış kabul edip doğrudan depoya ekleme talebi; Sistem Yöneticisi onayına gider."""
    op = _get_part(conn, oid, part_id)
    _check_open(op)
    if op['state'] not in (WAITING, ERROR):
        raise HTTPException(400, 'Bu parça zaten üretimde veya üretilmiş')
    if conn.execute("SELECT 1 FROM direct_part_requests WHERE order_part_id = ? AND status = 'BEKLIYOR'", (op['id'],)).fetchone():
        raise HTTPException(409, 'Bu parça için zaten bir onay bekleyen talep var')
    printer = db.row(conn.execute('SELECT id, name FROM printers WHERE id = ?', (body.printer_id,)))
    if not printer:
        raise HTTPException(404, 'Yazıcı bulunamadı')
    last = conn.execute('SELECT MAX(at) FROM part_events WHERE order_part_id = ?', (op['id'],)).fetchone()[0]
    at = db.pick_time(body.at, last, 'Baskı zamanı', 'parçanın son işlemi')
    rid = conn.execute(
        "INSERT INTO direct_part_requests (order_part_id, printer_id, print_at, requested_by, requested_at) VALUES (?,?,?,?,?)",
        (op['id'], printer['id'], at, user['id'], db.now())).lastrowid
    conn.execute('INSERT INTO part_events (order_part_id, event, user_id, printer_id, at) VALUES (?,?,?,?,?)',
                 (op['id'], 'DOGRUDAN_TALEP', user['id'], printer['id'], db.now()))
    db.audit(conn, user['id'], 'Doğrudan depo ekleme talebi açtı', 'order_part', op['id'],
             f'{op["order_code"]} / {part_id} -> {printer["name"]} (onay bekliyor)')
    return {'id': rid}


@router.post('/{oid}/parts/{part_id}/direct-approve')
def direct_approve(oid: int, part_id: str, body: DirectDecideIn, user=Depends(auth.current_user), conn=db.DB):
    """Sistem Yöneticisi onaylar: parça seçili yazıcıdan çıkmış gibi DEPO'ya (depo onayına) düşer."""
    if auth.ADMIN not in user['roles']:
        raise HTTPException(403, 'Doğrudan depo eklemeyi yalnızca Sistem Yöneticisi onaylar')
    op = _get_part(conn, oid, part_id)
    req = db.row(conn.execute("SELECT * FROM direct_part_requests WHERE order_part_id = ? AND status = 'BEKLIYOR' ORDER BY id DESC LIMIT 1", (op['id'],)))
    if not req:
        raise HTTPException(404, 'Onay bekleyen talep yok')
    if op['state'] not in (WAITING, ERROR):
        raise HTTPException(400, 'Parça artık uygun durumda değil')
    at = req['print_at'] or db.now()
    conn.execute("UPDATE order_parts SET state = ?, printer_id = ?, started_at = ?, printer_started_at = ?, printer_done_at = ?, finished_at = ?, delivered_to = NULL, approved_by = NULL, approved_at = NULL, updated_at = ? WHERE id = ?",
                 (WAREHOUSE, req['printer_id'], at, at, at, at, db.now(), op['id']))
    conn.execute("UPDATE direct_part_requests SET status = 'ONAYLANDI', decided_by = ?, decided_at = ?, note = ? WHERE id = ?",
                 (user['id'], db.now(), (body.note or '').strip()[:500] or None, req['id']))
    conn.execute('INSERT INTO part_events (order_part_id, event, user_id, printer_id, at) VALUES (?,?,?,?,?)',
                 (op['id'], 'DOGRUDAN_DEPO', user['id'], req['printer_id'], db.now()))
    db.audit(conn, user['id'], 'Doğrudan depo eklemeyi onayladı', 'order_part', op['id'],
             f'{op["order_code"]} / {part_id} -> depo onayina')
    recompute(conn, oid)
    return {'ok': True}


@router.post('/{oid}/parts/{part_id}/direct-reject')
def direct_reject(oid: int, part_id: str, body: DirectDecideIn, user=Depends(auth.current_user), conn=db.DB):
    if auth.ADMIN not in user['roles']:
        raise HTTPException(403, 'Bunu yalnizca Sistem Yoneticisi yapabilir')
    op = _get_part(conn, oid, part_id)
    req = db.row(conn.execute("SELECT id FROM direct_part_requests WHERE order_part_id = ? AND status = 'BEKLIYOR' ORDER BY id DESC LIMIT 1", (op['id'],)))
    if not req:
        raise HTTPException(404, 'Onay bekleyen talep yok')
    conn.execute("UPDATE direct_part_requests SET status = 'REDDEDILDI', decided_by = ?, decided_at = ?, note = ? WHERE id = ?",
                 (user['id'], db.now(), (body.note or '').strip()[:500] or None, req['id']))
    db.audit(conn, user['id'], 'Doğrudan depo eklemeyi reddetti', 'order_part', op['id'], f'{op["order_code"]} / {part_id}')
    return {'ok': True}


class SendIn(BaseModel):
    printer_id: int
    at: Optional[str] = None


@router.post('/{oid}/parts/{part_id}/send-to-printer')
def send_to_printer(oid: int, part_id: str, body: SendIn, user=Depends(part_operator), conn=db.DB):
    """Parçanın G-code'unu seçili yazıcıya (Moonraker) gönderip baskıyı başlatır; yükleme arka planda, ilerleme izlenir."""
    from .. import printer_send
    op = _get_part(conn, oid, part_id)
    _check_open(op)
    if op['state'] not in (WAITING, ERROR):
        raise HTTPException(400, 'Bu parça zaten üretimde veya üretilmiş')
    if conn.execute("SELECT 1 FROM direct_part_requests WHERE order_part_id = ? AND status = 'BEKLIYOR'", (op['id'],)).fetchone():
        raise HTTPException(409, 'Bu parça için doğrudan depo ekleme talebi onayda')
    printer = db.row(conn.execute('SELECT id, name, ip, current_part_id FROM printers WHERE id = ?', (body.printer_id,)))
    if not printer:
        raise HTTPException(404, 'Yazıcı bulunamadı')
    if not printer['ip']:
        raise HTTPException(400, 'Yazıcının IP adresi tanımlı değil')
    if printer['current_part_id']:
        busy = db.row(conn.execute('SELECT o.code, op.part_id FROM order_parts op JOIN orders o ON o.id = op.order_id WHERE op.id = ?', (printer['current_part_id'],)))
        if busy:
            raise HTTPException(409, f'{printer["name"]} meşgul: {busy["code"]} / {busy["part_id"]}')
    # G-code arama: önce parça yedeği kaydı (CAYMAZ alt-parçaları: schema='part-<part_id>').
    # Böyle bir kayıt YOKSA bu tek-parçalı bir üründür (yarı mamul / sarf / custom) → G-code siparişin
    # kendi ürün satırındadır; oraya düşeriz (G-code ürüne id ile yazılıyor, schema'ya göre değil).
    part_row = db.row(conn.execute('SELECT gcode_file FROM products WHERE schema = ?', (f'part-{part_id}',)))
    if part_row is not None:
        gcode_rel = part_row.get('gcode_file')
    else:
        prow = db.row(conn.execute('SELECT p.gcode_file FROM orders o JOIN products p ON p.id = o.product_id WHERE o.id = ?', (oid,)))
        gcode_rel = prow.get('gcode_file') if prow else None
    if not gcode_rel:
        raise HTTPException(400, 'Bu parçanın G-code dosyası sistemde tanımlı değil')
    last = conn.execute('SELECT MAX(at) FROM part_events WHERE order_part_id = ?', (op['id'],)).fetchone()[0]
    at = db.pick_time(body.at, last, 'Başlama zamanı', 'parçanın son işlemi')
    try:
        started = printer_send.start(op['id'], dict(printer), gcode_rel, at, user['id'], oid, op['order_code'], part_id)
    except FileNotFoundError:
        raise HTTPException(400, 'G-code dosyası sunucuda bulunamadı')
    if not started:
        raise HTTPException(409, 'Bu parça için yükleme zaten sürüyor')
    return {'ok': True}


@router.get('/{oid}/parts/{part_id}/send-progress')
def send_progress(oid: int, part_id: str, user=Depends(_order_reader), conn=db.DB):
    from .. import printer_send
    op = _get_part(conn, oid, part_id)
    st = printer_send.state(op['id'])
    if not st:
        return {'status': 'none'}
    pct = round(st['sent'] * 100 / st['total'], 1) if st['total'] else 0
    return {'status': st['status'], 'sent': st['sent'], 'total': st['total'], 'percent': pct,
            'filename': st['filename'], 'printer': st['printer'], 'error': st['error']}


@router.post('/{oid}/parts/{part_id}/error')
async def error_part(oid: int, part_id: str,
                     error_code: str = Form(...), description: str = Form(''),
                     photo: Optional[UploadFile] = File(None),
                     at: str = Form(''), user=Depends(part_operator), conn=db.DB):
    op = _get_part(conn, oid, part_id)
    _check_open(op)
    if op['state'] != PRINTING:
        raise HTTPException(400, 'Parça üretimde değil')
    if not error_code.strip():
        raise HTTPException(400, 'Hata kodu zorunlu')
    when = db.pick_time(at, op['started_at'], 'Hata zamanı', 'üretime başlama')
    photo_path = await save_upload('errors', photo) if photo and photo.filename else None

    def write():   # veritabanı yazımı olay döngüsünü bloklamasın diye iş parçacığında
        now = when
        conn.execute('UPDATE order_parts SET state = ?, finished_at = ?, updated_at = ? WHERE id = ?',
                     (ERROR, now, now, op['id']))
        _release_printer(conn, op, now)
        conn.execute('''INSERT INTO part_events (order_part_id, event, user_id, printer_id, error_code, note, photo, at)
                        VALUES (?,?,?,?,?,?,?,?)''',
                     (op['id'], 'HATA', user['id'], op['printer_id'], error_code.strip(), description.strip(),
                      photo_path, now))
        db.audit(conn, user['id'], 'Parça hatası bildirdi', 'order_part', op['id'],
                 f'{op["order_code"]} / {part_id}: {error_code.strip()}')
        recompute(conn, oid)
    await run_in_threadpool(write)
    return {'ok': True}
