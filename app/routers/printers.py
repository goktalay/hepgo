import ipaddress

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, db, printer_driver, printer_layout

router = APIRouter(prefix='/api/printers')
printer_admin = auth.require_module('printers')


def _printer_reader(user=Depends(auth.current_user)):
    # Üretim ekranı yazıcı seçtirdiği için üretim kullanıcıları da listeyi okuyabilir.
    if not {'printers', 'production'} & set(user['modules']):
        raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
    return user


class PrinterIn(BaseModel):
    name: str
    ip: str


class SlotIn(BaseModel):
    id: int
    side: str
    level: int
    slot: int


class LayoutIn(BaseModel):
    items: list[SlotIn]


def _validate(conn, body, pid=None):
    if not body.name.strip():
        raise HTTPException(400, 'Yazıcı adı zorunlu')
    try:
        ipaddress.IPv4Address(body.ip.strip())
    except ValueError:
        raise HTTPException(400, 'Geçersiz IP adresi')
    if conn.execute('SELECT 1 FROM printers WHERE ip = ? AND id IS NOT ?', (body.ip.strip(), pid)).fetchone():
        raise HTTPException(400, 'Bu IP adresi zaten kayıtlı')


@router.get('')
def list_printers(user=Depends(_printer_reader), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT p.*, o.code AS current_order, op.part_id AS current_part, op.order_id AS current_order_id
           FROM printers p
           LEFT JOIN order_parts op ON op.id = p.current_part_id
           LEFT JOIN orders o ON o.id = op.order_id
           ORDER BY p.name'''))


@router.put('/layout')
def save_layout(body: LayoutIn, user=Depends(printer_admin), conn=db.DB):
    """Yazıcı odası yerleşimi (3B görünüm): verilen yazıcıların taraf / kat / sıra bilgisi; bir yerde tek yazıcı olur."""
    ids = {r[0] for r in conn.execute('SELECT id FROM printers')}
    per_row = printer_layout.slots_per_row(len(ids)) + 10
    seen = set()
    for it in body.items:
        key = (it.side, it.level, it.slot)
        if it.id not in ids or it.side not in ('L', 'R') or it.level not in (1, 2) or not 1 <= it.slot <= per_row:
            raise HTTPException(400, 'Geçersiz yerleşim')
        if key in seen:
            raise HTTPException(400, 'Aynı rafa iki yazıcı konamaz')
        seen.add(key)
    moved = {it.id for it in body.items}
    others = {tuple(r[1:]) for r in conn.execute('SELECT id, rack_side, rack_level, rack_slot FROM printers') if r[0] not in moved}
    if seen & others:
        raise HTTPException(400, 'Seçilen raf dolu')
    conn.executemany('UPDATE printers SET rack_side = NULL, rack_level = NULL, rack_slot = NULL WHERE id = ?', [(i,) for i in moved])
    conn.executemany('UPDATE printers SET rack_side = ?, rack_level = ?, rack_slot = ? WHERE id = ?',
                     [(it.side, it.level, it.slot, it.id) for it in body.items])
    db.audit(conn, user['id'], 'Yazıcı yerleşimini değiştirdi', 'printer', None, f'{len(body.items)} yazıcı')
    return {'ok': True}


@router.post('')
def add_printer(body: PrinterIn, user=Depends(printer_admin), conn=db.DB):
    _validate(conn, body)
    cur = conn.execute('INSERT INTO printers (name, ip, created_at) VALUES (?,?,?)',
                       (body.name.strip(), body.ip.strip(), db.now()))
    db.audit(conn, user['id'], 'Yazıcı ekledi', 'printer', cur.lastrowid, f'{body.name} ({body.ip})')
    printer_layout.assign_missing(conn)   # odada ilk boş rafa
    return {'id': cur.lastrowid}


@router.put('/{pid}')
def update_printer(pid: int, body: PrinterIn, user=Depends(printer_admin), conn=db.DB):
    if not conn.execute('SELECT 1 FROM printers WHERE id = ?', (pid,)).fetchone():
        raise HTTPException(404, 'Yazıcı bulunamadı')
    _validate(conn, body, pid)
    conn.execute('UPDATE printers SET name = ?, ip = ? WHERE id = ?', (body.name.strip(), body.ip.strip(), pid))
    db.audit(conn, user['id'], 'Yazıcı düzenledi', 'printer', pid, f'{body.name} ({body.ip})')
    return {'ok': True}


@router.delete('/{pid}')
def delete_printer(pid: int, user=Depends(printer_admin), conn=db.DB):
    p = db.row(conn.execute('SELECT * FROM printers WHERE id = ?', (pid,)))
    if not p:
        raise HTTPException(404, 'Yazıcı bulunamadı')
    if p['current_part_id']:
        raise HTTPException(400, 'Üzerinde üretim olan yazıcı silinemez')
    conn.execute('DELETE FROM printers WHERE id = ?', (pid,))
    db.audit(conn, user['id'], 'Yazıcı sildi', 'printer', pid, f'{p["name"]} ({p["ip"]})')
    return {'ok': True}


@router.post('/refresh')
async def refresh(user=Depends(printer_admin)):
    await run_in_threadpool(printer_driver.poll_all)

    def write():
        with db.connect() as conn:
            db.audit(conn, user['id'], 'Yazıcı durumlarını elle yeniledi', 'printer')
    await run_in_threadpool(write)
    return {'ok': True}


@router.post('/discover')
async def discover(user=Depends(printer_admin)):
    found = await run_in_threadpool(printer_driver.discover)
    return await run_in_threadpool(_add_discovered, found, user)


def _add_discovered(found, user):
    added = []
    with db.connect() as conn:
        existing = {r[0] for r in conn.execute('SELECT ip FROM printers')}
        count = conn.execute('SELECT COUNT(*) FROM printers').fetchone()[0]
        for ip, live in sorted(found, key=lambda f: ipaddress.IPv4Address(f[0])):
            if ip in existing:
                continue
            count += 1
            # Yazıcının ağdaki adı (ör. K2Plus-3697) varsa o kullanılır; fiziksel cihazla eşleştirmesi kolay olur.
            name = live.get('hostname') or f'K2 Plus {count:02d}'
            now = db.now()
            cur = conn.execute(
                '''INSERT INTO printers (name, ip, model, auto_added, created_at, live_state, live_progress,
                   live_file, live_source, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (name, ip, live['model'] or 'Creality K2 Plus', 1, now, live['state'], live['progress'], live['file'],
                 live['source'], now))
            db.audit(conn, user['id'], 'Yazıcı otomatik ekledi', 'printer', cur.lastrowid, f'{name} ({ip})')
            added.append({'name': name, 'ip': ip})
        printer_layout.assign_missing(conn)
    return {'found': len(found), 'added': added}
