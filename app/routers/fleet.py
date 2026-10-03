"""Araç Yönetimi — /api/fleet: şirket araçları (satın alınan / kiralanan), personele zimmet + zimmet formu + elektronik teslim
onayı, belgeler (ruhsat, kira sözleşmesi, poliçeler…), giderler (elle ya da muhasebe / finans hareketlerinden etiketlenen) ve
araç başına toplam harcama. Araçlar Saha modülüyle ortak field_vehicles tablosundadır."""
import json
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .. import auth, config, db, fleet
from ..files import FILE_GUARDS, save_upload_stream, take_upload

router = APIRouter(prefix='/api/fleet')
fleet_user = auth.require_module('fleet')


def _file_guard(user, name):
    if user.get('master') or 'fleet' in user.get('modules', []):
        return True
    conn = db.connect()   # zimmetli personel kendi aracının fotoğrafını görür
    try:
        return conn.execute('''SELECT 1 FROM field_vehicles v JOIN vehicle_assignments a ON a.vehicle_id = v.id
                               WHERE a.user_id = ? AND v.photo = ?''', (user['id'], f'fleet/{name}')).fetchone() is not None
    finally:
        conn.close()


FILE_GUARDS['fleet'] = _file_guard


def _vehicle(conn, vid):
    v = db.row(conn.execute('''SELECT v.*, s.name AS seller_name, l.name AS lessor_name FROM field_vehicles v
                               LEFT JOIN companies s ON s.id = v.seller_id LEFT JOIN companies l ON l.id = v.lessor_id WHERE v.id = ?''', (vid,)))
    if not v:
        raise HTTPException(404, 'Araç bulunamadı')
    return v


def _active_assign(conn, vid):
    return db.row(conn.execute('''SELECT a.*, u.full_name FROM vehicle_assignments a JOIN users u ON u.id = a.user_id
                                  WHERE a.vehicle_id = ? AND a.end_date IS NULL ORDER BY a.start_date DESC, a.id DESC LIMIT 1''', (vid,)))


def _meta(conn):
    return {'categories': fleet.CATEGORIES, 'body_types': fleet.BODY_TYPES, 'fuel_types': fleet.FUEL_TYPES, 'fuel_levels': fleet.FUEL_LEVELS,
            'ownership': fleet.OWNERSHIP, 'lease_includes': fleet.LEASE_INCLUDES, 'exit_reasons': fleet.EXIT_REASONS, 'doc_kinds': fleet.DOC_KINDS,
            'equipment': fleet.settings(conn)['equipment']}


@router.get('')
def list_vehicles(user=Depends(fleet_user), conn=db.DB):
    y0 = f'{date.today().year}-01-01'
    spend = {r[0]: (r[1] or 0, r[2] or 0) for r in conn.execute(
        'SELECT vehicle_id, SUM(amount), SUM(CASE WHEN date >= ? THEN amount END) FROM vehicle_expenses GROUP BY vehicle_id', (y0,))}
    assigns = {r['vehicle_id']: r for r in db.rows(conn.execute(
        '''SELECT a.vehicle_id, a.id, a.user_id, a.start_date, a.accepted_at, u.full_name FROM vehicle_assignments a JOIN users u ON u.id = a.user_id
           WHERE a.end_date IS NULL ORDER BY a.start_date, a.id'''))}
    rows = db.rows(conn.execute('''SELECT v.*, l.name AS lessor_name,
                                   (SELECT COUNT(*) FROM field_task_vehicles t WHERE t.vehicle_id = v.id) AS task_count,
                                   (SELECT COUNT(*) FROM vehicle_docs d WHERE d.vehicle_id = v.id) AS doc_count
                                   FROM field_vehicles v LEFT JOIN companies l ON l.id = v.lessor_id ORDER BY v.active DESC, v.plate'''))
    for v in rows:
        v['spend_total'], v['spend_year'] = (round(x, 2) for x in spend.get(v['id'], (0, 0)))
        v['assignee'] = assigns.get(v['id'])
        v['km_now'] = fleet.km_now(conn, v['id'])
        v['dues'] = fleet.dues(v, v['km_now'])
    open_moves = sum(1 for m in fleet.moves(conn, _since(365)) if m['remaining'] > 0.009 and not m['ignored'])
    assets = [a for a in fleet.asset_accounts(conn) if not a['vehicle_id']]
    return {'rows': rows, 'meta': _meta(conn), 'open_moves': open_moves, 'unlinked_assets': assets, 'year': date.today().year}


@router.get('/options')
def options(user=Depends(fleet_user), conn=db.DB):
    """Form seçim listeleri: personel (aktif kullanıcılar), firmalar (satıcı / kiralayan), muhasebedeki taşıt hesapları."""
    users = db.rows(conn.execute('''SELECT u.id, u.full_name, e.title, e.department FROM users u LEFT JOIN employees e ON e.user_id = u.id
                                    WHERE u.active = 1 AND u.deleted_at IS NULL ORDER BY u.full_name COLLATE NOCASE'''))
    companies = db.rows(conn.execute('SELECT id, name, is_supplier FROM companies WHERE active = 1 ORDER BY name COLLATE NOCASE'))
    return {'users': users, 'companies': companies, 'assets': fleet.asset_accounts(conn), 'meta': _meta(conn)}


class VehicleIn(BaseModel):
    plate: str
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    body_type: Optional[str] = None
    fuel_type: Optional[str] = None
    color: Optional[str] = None
    vin: Optional[str] = None
    engine_no: Optional[str] = None
    description: Optional[str] = None
    ownership: str = 'owned'
    purchase_date: Optional[str] = None
    purchase_price: Optional[float] = None
    seller_id: Optional[int] = None
    purchase_doc: Optional[str] = None
    asset_account: Optional[str] = None
    lessor_id: Optional[int] = None
    lease_no: Optional[str] = None
    lease_start: Optional[str] = None
    lease_end: Optional[str] = None
    lease_monthly: Optional[float] = None
    lease_currency: Optional[str] = 'TRY'
    lease_km_limit: Optional[float] = None
    lease_includes: List[str] = []
    start_km: Optional[float] = None
    inspection_date: Optional[str] = None
    traffic_ins_date: Optional[str] = None
    kasko_date: Optional[str] = None
    next_service_date: Optional[str] = None
    next_service_km: Optional[float] = None
    match_keys: Optional[str] = None
    active: bool = True
    exit_date: Optional[str] = None
    exit_reason: Optional[str] = None
    note: Optional[str] = None


def _vvals(conn, b: VehicleIn, vid=None):
    plate = fleet.norm_plate(b.plate)
    if not plate:
        raise HTTPException(400, 'Plaka zorunlu')
    key = fleet.squash(plate)
    for oid, op in conn.execute('SELECT id, plate FROM field_vehicles'):
        if oid != vid and fleet.squash(op) == key:
            raise HTTPException(409, f'Bu plaka zaten kayıtlı ({op})')
    if b.ownership not in fleet.OWNERSHIP:
        raise HTTPException(400, 'Geçersiz sahiplik türü')
    for cid in (b.seller_id, b.lessor_id):
        if cid and not conn.execute('SELECT 1 FROM companies WHERE id = ?', (cid,)).fetchone():
            raise HTTPException(400, 'Firma bulunamadı')
    t = lambda v, n=200: ((v or '').strip()[:n] or None)
    d = lambda v: ((v or '')[:10] or None)
    leased = b.ownership == 'leased'
    return {
        'plate': plate, 'description': t(b.description, 300), 'brand': t(b.brand, 60), 'model': t(b.model, 120),
        'year': b.year if b.year and 1950 <= b.year <= 2100 else None, 'body_type': b.body_type if b.body_type in fleet.BODY_TYPES else None,
        'fuel_type': b.fuel_type if b.fuel_type in fleet.FUEL_TYPES else None, 'color': t(b.color, 40), 'vin': t(b.vin, 40), 'engine_no': t(b.engine_no, 40),
        'ownership': b.ownership,
        'purchase_date': None if leased else d(b.purchase_date), 'purchase_price': None if leased else b.purchase_price,
        'seller_id': None if leased else b.seller_id, 'purchase_doc': None if leased else t(b.purchase_doc, 80),
        'asset_account': None if leased else t(b.asset_account, 40),
        'lessor_id': b.lessor_id if leased else None, 'lease_no': t(b.lease_no, 80) if leased else None,
        'lease_start': d(b.lease_start) if leased else None, 'lease_end': d(b.lease_end) if leased else None,
        'lease_monthly': b.lease_monthly if leased else None, 'lease_currency': (b.lease_currency or 'TRY')[:3].upper() if leased else None,
        'lease_km_limit': b.lease_km_limit if leased else None,
        'lease_includes': ','.join(k for k in b.lease_includes if k in fleet.LEASE_INCLUDES) or None if leased else None,
        'start_km': b.start_km, 'inspection_date': d(b.inspection_date), 'traffic_ins_date': d(b.traffic_ins_date), 'kasko_date': d(b.kasko_date),
        'next_service_date': d(b.next_service_date), 'next_service_km': b.next_service_km, 'match_keys': t(b.match_keys, 300),
        'active': int(b.active), 'exit_date': None if b.active else d(b.exit_date),
        'exit_reason': None if b.active else (b.exit_reason if b.exit_reason in fleet.EXIT_REASONS else None),
        'note': t(b.note, 4000), 'updated_at': db.now(),
    }


@router.post('')
def create(b: VehicleIn, user=Depends(fleet_user), conn=db.DB):
    vals = _vvals(conn, b)
    vals['created_at'] = vals['updated_at']
    cols = ', '.join(vals)
    cur = conn.execute(f"INSERT INTO field_vehicles ({cols}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
    db.audit(conn, user['id'], 'Araç ekledi', 'field_vehicle', cur.lastrowid, vals['plate'])
    conn.commit()
    return {'id': cur.lastrowid}


@router.get('/{vid}')
def detail(vid: int, user=Depends(fleet_user), conn=db.DB):
    v = _vehicle(conn, vid)
    v['km_now'] = fleet.km_now(conn, vid)
    v['dues'] = fleet.dues(v, v['km_now'])
    v['assignments'] = db.rows(conn.execute('''SELECT a.*, u.full_name, c.full_name AS created_by_name,
                                               (SELECT COUNT(*) FROM vehicle_docs d WHERE d.assignment_id = a.id) AS doc_count
                                               FROM vehicle_assignments a JOIN users u ON u.id = a.user_id LEFT JOIN users c ON c.id = a.created_by
                                               WHERE a.vehicle_id = ? ORDER BY a.start_date DESC, a.id DESC''', (vid,)))
    for a in v['assignments']:
        a['equipment'] = json.loads(a['equipment'] or '[]')
    v['expenses'] = db.rows(conn.execute('''SELECT e.*, u.full_name AS created_by_name FROM vehicle_expenses e LEFT JOIN users u ON u.id = e.created_by
                                            WHERE e.vehicle_id = ? ORDER BY e.date DESC, e.id DESC''', (vid,)))
    v['docs'] = db.rows(conn.execute('''SELECT d.*, u.full_name AS uploaded_by_name FROM vehicle_docs d LEFT JOIN users u ON u.id = d.uploaded_by
                                        WHERE d.vehicle_id = ? ORDER BY d.created_at DESC, d.id DESC''', (vid,)))
    t = conn.execute('''SELECT COUNT(*), SUM(CASE WHEN end_km > start_km THEN end_km - start_km END) FROM field_task_vehicles
                        WHERE vehicle_id = ?''', (vid,)).fetchone()
    v['field'] = {'tasks': t[0], 'km': t[1]}
    kms = [x for x in [v['start_km']] + [e['km'] for e in v['expenses']] + [a['start_km'] for a in v['assignments']] if x]
    first_km = min(kms) if kms else None
    total = sum(e['amount'] for e in v['expenses'])
    v['spend_total'] = round(total, 2)
    v['cost_per_km'] = round(total / (v['km_now'] - first_km), 2) if total and first_km is not None and v['km_now'] and v['km_now'] - first_km > 100 else None
    v['meta'] = _meta(conn)
    return v


@router.put('/{vid}')
def update(vid: int, b: VehicleIn, user=Depends(fleet_user), conn=db.DB):
    _vehicle(conn, vid)
    vals = _vvals(conn, b, vid)
    if not b.active and _active_assign(conn, vid):
        raise HTTPException(409, 'Zimmeti süren araç pasife alınamaz; önce aracı iade alın')
    conn.execute(f"UPDATE field_vehicles SET {', '.join(f'{k} = ?' for k in vals)} WHERE id = ?", [*vals.values(), vid])
    db.audit(conn, user['id'], 'Aracı düzenledi', 'field_vehicle', vid, vals['plate'])
    conn.commit()
    return {'ok': True}


@router.delete('/{vid}')
def delete(vid: int, confirm: str = '', user=Depends(fleet_user), conn=db.DB):
    v = _vehicle(conn, vid)
    if fleet.squash(confirm) != fleet.squash(v['plate']):
        raise HTTPException(400, 'Silmek için plakayı aynen yazın')
    if conn.execute('SELECT 1 FROM field_task_vehicles WHERE vehicle_id = ?', (vid,)).fetchone():
        raise HTTPException(409, 'Saha görevlerinde kullanılan araç silinemez; pasife alabilirsiniz')
    paths = [r[0] for r in conn.execute('SELECT path FROM vehicle_docs WHERE vehicle_id = ?', (vid,))]
    paths += [r[0] for r in conn.execute('SELECT receipt FROM vehicle_expenses WHERE vehicle_id = ? AND receipt IS NOT NULL', (vid,))]
    paths += [v['photo']] if v['photo'] else []
    conn.execute('DELETE FROM field_vehicles WHERE id = ?', (vid,))
    db.audit(conn, user['id'], 'Araç sildi', 'field_vehicle', vid, f"{v['plate']} · {len(paths)} dosya")
    conn.commit()
    for p in paths:
        (config.UPLOAD_DIR / p).unlink(missing_ok=True)
    return {'ok': True}


@router.post('/{vid}/photo')
async def set_photo(vid: int, file: UploadFile = File(...), user=Depends(fleet_user), conn=db.DB):
    v = _vehicle(conn, vid)
    if not (file.filename or '').lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif')):
        raise HTTPException(400, 'Araç fotoğrafı resim olmalı (JPG / PNG / WEBP / HEIC)')
    path, _size = await save_upload_stream('fleet', file, 25 * 1024 * 1024)
    conn.execute('UPDATE field_vehicles SET photo = ?, updated_at = ? WHERE id = ?', (path, db.now(), vid))
    conn.commit()
    if v['photo']:
        (config.UPLOAD_DIR / v['photo']).unlink(missing_ok=True)
    return {'photo': path}


# ---------------- Zimmet ----------------
class AssignIn(BaseModel):
    user_id: int
    start_date: str
    start_km: Optional[float] = None
    start_fuel: Optional[str] = None
    equipment: List[str] = []
    condition: Optional[str] = None
    note: Optional[str] = None


class ReturnIn(BaseModel):
    end_date: str
    end_km: Optional[float] = None
    end_fuel: Optional[str] = None
    end_note: Optional[str] = None


def _assignment(conn, aid):
    a = db.row(conn.execute('SELECT * FROM vehicle_assignments WHERE id = ?', (aid,)))
    if not a:
        raise HTTPException(404, 'Zimmet kaydı bulunamadı')
    return a


@router.post('/{vid}/assign')
def assign(vid: int, b: AssignIn, user=Depends(fleet_user), conn=db.DB):
    v = _vehicle(conn, vid)
    if not v['active']:
        raise HTTPException(409, 'Pasif araç zimmetlenemez')
    p = db.row(conn.execute('SELECT id, full_name FROM users WHERE id = ? AND active = 1 AND deleted_at IS NULL', (b.user_id,)))
    if not p:
        raise HTTPException(400, 'Personel bulunamadı')
    if not b.start_date:
        raise HTTPException(400, 'Teslim tarihi gerekli')
    cur_a = _active_assign(conn, vid)
    if cur_a:   # devir: önceki zimmet aynı tarih / km ile kapanır
        if cur_a['user_id'] == b.user_id:
            raise HTTPException(409, 'Araç zaten bu personele zimmetli')
        if b.start_date[:10] < cur_a['start_date']:
            raise HTTPException(400, 'Devir tarihi önceki zimmetin başlangıcından önce olamaz')
        conn.execute('UPDATE vehicle_assignments SET end_date = ?, end_km = ?, end_fuel = ?, end_note = ? WHERE id = ?',
                     (b.start_date[:10], b.start_km, b.start_fuel, f"Devredildi → {p['full_name']}", cur_a['id']))
    eq = [x.strip()[:80] for x in b.equipment if x and x.strip()][:40]
    cur = conn.execute('''INSERT INTO vehicle_assignments (vehicle_id, user_id, start_date, start_km, start_fuel, equipment, condition, note,
                          created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                       (vid, b.user_id, b.start_date[:10], b.start_km, b.start_fuel if b.start_fuel in fleet.FUEL_LEVELS else None,
                        json.dumps(eq, ensure_ascii=False), (b.condition or '').strip()[:2000] or None, (b.note or '').strip()[:2000] or None,
                        user['id'], db.now()))
    db.audit(conn, user['id'], 'Araç zimmetledi', 'field_vehicle', vid, f"{v['plate']} → {p['full_name']}")
    conn.commit()
    return {'id': cur.lastrowid}


@router.post('/assignments/{aid}/return')
def return_vehicle(aid: int, b: ReturnIn, user=Depends(fleet_user), conn=db.DB):
    a = _assignment(conn, aid)
    if a['end_date']:
        raise HTTPException(409, 'Bu zimmet zaten kapanmış')
    if not b.end_date or b.end_date[:10] < a['start_date']:
        raise HTTPException(400, 'İade tarihi teslim tarihinden önce olamaz')
    if b.end_km is not None and a['start_km'] is not None and b.end_km < a['start_km']:
        raise HTTPException(400, 'İade km teslim km’sinden küçük olamaz')
    conn.execute('UPDATE vehicle_assignments SET end_date = ?, end_km = ?, end_fuel = ?, end_note = ? WHERE id = ?',
                 (b.end_date[:10], b.end_km, b.end_fuel if b.end_fuel in fleet.FUEL_LEVELS else None, (b.end_note or '').strip()[:2000] or None, aid))
    db.audit(conn, user['id'], 'Aracı iade aldı', 'field_vehicle', a['vehicle_id'], f'zimmet {aid}')
    conn.commit()
    return {'ok': True}


@router.put('/assignments/{aid}')
def update_assignment(aid: int, b: AssignIn, user=Depends(fleet_user), conn=db.DB):
    """Düzeltme. Teslim bilgileri onaydan sonra değişirse personelin onayı sıfırlanır (yeniden onaylar)."""
    a = _assignment(conn, aid)
    eq = json.dumps([x.strip()[:80] for x in b.equipment if x and x.strip()][:40], ensure_ascii=False)
    new = (b.start_date[:10], b.start_km, b.start_fuel if b.start_fuel in fleet.FUEL_LEVELS else None, eq, (b.condition or '').strip()[:2000] or None)
    changed = new != (a['start_date'], a['start_km'], a['start_fuel'], a['equipment'], a['condition'])
    reset = bool(a['accepted_at'] and changed)
    conn.execute(f'''UPDATE vehicle_assignments SET start_date = ?, start_km = ?, start_fuel = ?, equipment = ?, condition = ?, note = ?
                     {', accepted_at = NULL, accepted_ip = NULL' if reset else ''} WHERE id = ?''', (*new, (b.note or '').strip()[:2000] or None, aid))
    conn.commit()
    return {'ok': True, 'acceptance_reset': reset}


@router.delete('/assignments/{aid}')
def delete_assignment(aid: int, user=Depends(fleet_user), conn=db.DB):
    a = _assignment(conn, aid)
    if a['accepted_at']:
        raise HTTPException(409, 'Personelin onayladığı zimmet silinemez; iade alın')
    conn.execute('DELETE FROM vehicle_assignments WHERE id = ?', (aid,))
    db.audit(conn, user['id'], 'Zimmet kaydını sildi', 'field_vehicle', a['vehicle_id'], f'zimmet {aid}')
    conn.commit()
    return {'ok': True}


@router.get('/assignments/{aid}/form')
def assignment_form(aid: int, user=Depends(auth.current_user), conn=db.DB):
    """Zimmet formu verisi (yazdırma / onay ekranı): araç modülü yetkilisi ya da zimmetli personelin kendisi görür."""
    a = _assignment(conn, aid)
    if a['user_id'] != user['id'] and 'fleet' not in user.get('modules', []) and not user.get('master'):
        raise HTTPException(404, 'Zimmet kaydı bulunamadı')
    a['equipment'] = json.loads(a['equipment'] or '[]')
    v = _vehicle(conn, a['vehicle_id'])
    p = db.row(conn.execute('''SELECT u.full_name, u.phone, e.tc_no, e.title, e.department FROM users u LEFT JOIN employees e ON e.user_id = u.id
                               WHERE u.id = ?''', (a['user_id'],)))
    by = conn.execute('SELECT full_name FROM users WHERE id = ?', (a['created_by'],)).fetchone() if a['created_by'] else None
    s = fleet.settings(conn)
    return {'assignment': a, 'vehicle': {k: v[k] for k in ('plate', 'brand', 'model', 'year', 'color', 'vin', 'engine_no', 'fuel_type', 'body_type',
                                                            'ownership', 'lessor_name', 'photo')},
            'person': p, 'delivered_by': by[0] if by else None, 'company': config.COMPANY_NAME, 'clauses': s['clauses'],
            'mine': a['user_id'] == user['id'], 'meta': _meta(conn)}


@router.post('/assignments/{aid}/accept')
def accept(aid: int, request: Request, user=Depends(auth.current_user), conn=db.DB):
    a = _assignment(conn, aid)
    if a['user_id'] != user['id']:
        raise HTTPException(403, 'Zimmeti yalnızca teslim alan personel onaylayabilir')
    if a['end_date']:
        raise HTTPException(409, 'Kapanmış zimmet onaylanamaz')
    if a['accepted_at']:
        return {'ok': True, 'accepted_at': a['accepted_at']}
    ip = request.headers.get('cf-connecting-ip') or (request.client.host if request.client else None)
    now = db.now()
    conn.execute('UPDATE vehicle_assignments SET accepted_at = ?, accepted_ip = ? WHERE id = ?', (now, ip, aid))
    db.audit(conn, user['id'], 'Araç zimmetini onayladı', 'field_vehicle', a['vehicle_id'], f'zimmet {aid}')
    conn.commit()
    return {'ok': True, 'accepted_at': now}


@router.get('/mine/list')
def mine(user=Depends(auth.current_user), conn=db.DB):
    """Kişisel › Araç Zimmetim: bana zimmetli (ve geçmişte zimmetlenmiş) araçlar."""
    rows = db.rows(conn.execute('''SELECT a.id, a.vehicle_id, a.start_date, a.start_km, a.end_date, a.end_km, a.accepted_at,
                                   v.plate, v.brand, v.model, v.year, v.color, v.photo, v.ownership
                                   FROM vehicle_assignments a JOIN field_vehicles v ON v.id = a.vehicle_id
                                   WHERE a.user_id = ? ORDER BY a.end_date IS NOT NULL, a.start_date DESC''', (user['id'],)))
    for r in rows:
        if not r['end_date']:
            v = _vehicle(conn, r['vehicle_id'])
            r['dues'] = fleet.dues(v, fleet.km_now(conn, r['vehicle_id']), within=15)
    return rows


# ---------------- Belgeler ----------------
class DocIn(BaseModel):
    upload_id: str
    kind: str = 'diger'
    expires: Optional[str] = None
    assignment_id: Optional[int] = None


@router.post('/{vid}/docs')
def add_doc(vid: int, b: DocIn, user=Depends(fleet_user), conn=db.DB):
    _vehicle(conn, vid)
    if b.assignment_id and not conn.execute('SELECT 1 FROM vehicle_assignments WHERE id = ? AND vehicle_id = ?', (b.assignment_id, vid)).fetchone():
        raise HTTPException(404, 'Zimmet kaydı bulunamadı')
    path, size, name = take_upload(b.upload_id, user, 'fleet')
    cur = conn.execute('''INSERT INTO vehicle_docs (vehicle_id, assignment_id, kind, name, path, size, expires, uploaded_by, created_at)
                          VALUES (?,?,?,?,?,?,?,?,?)''', (vid, b.assignment_id or None, b.kind if b.kind in fleet.DOC_KINDS else 'diger', name[:200], path, size,
                                                          (b.expires or '')[:10] or None, user['id'], db.now()))
    conn.commit()
    return {'id': cur.lastrowid}


class DocUpd(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    expires: Optional[str] = None


@router.put('/docs/{did}')
def update_doc(did: int, b: DocUpd, user=Depends(fleet_user), conn=db.DB):
    d = db.row(conn.execute('SELECT * FROM vehicle_docs WHERE id = ?', (did,)))
    if not d:
        raise HTTPException(404, 'Belge bulunamadı')
    conn.execute('UPDATE vehicle_docs SET name = ?, kind = ?, expires = ? WHERE id = ?',
                 ((b.name or d['name']).strip()[:200], b.kind if b.kind in fleet.DOC_KINDS else d['kind'], (b.expires or '')[:10] or None, did))
    conn.commit()
    return {'ok': True}


@router.delete('/docs/{did}')
def delete_doc(did: int, user=Depends(fleet_user), conn=db.DB):
    d = db.row(conn.execute('SELECT * FROM vehicle_docs WHERE id = ?', (did,)))
    if not d:
        raise HTTPException(404, 'Belge bulunamadı')
    if d['uploaded_by'] != user['id'] and not user.get('master') and 'admin' not in user.get('modules', []):
        raise HTTPException(403, 'Belgeyi yalnızca yükleyen ya da yönetici silebilir')
    conn.execute('DELETE FROM vehicle_docs WHERE id = ?', (did,))
    db.audit(conn, user['id'], 'Araç belgesi sildi', 'field_vehicle', d['vehicle_id'], d['name'][:80])
    conn.commit()
    (config.UPLOAD_DIR / d['path']).unlink(missing_ok=True)
    return {'ok': True}


# ---------------- Giderler (elle) ----------------
class ExpenseIn(BaseModel):
    date: str
    category: str
    amount: float
    liters: Optional[float] = None
    km: Optional[float] = None
    vendor: Optional[str] = None
    description: Optional[str] = None
    upload_id: Optional[str] = None


def _evals(b: ExpenseIn):
    if not b.date or b.category not in fleet.CATEGORIES or not b.amount or b.amount <= 0:
        raise HTTPException(400, 'Tarih, kategori ve tutar gerekli')
    return (b.date[:10], b.category, round(b.amount, 2), b.liters if b.liters and b.liters > 0 else None, b.km if b.km and b.km > 0 else None,
            (b.vendor or '').strip()[:160] or None, (b.description or '').strip()[:1000] or None)


@router.post('/{vid}/expenses')
def add_expense(vid: int, b: ExpenseIn, user=Depends(fleet_user), conn=db.DB):
    _vehicle(conn, vid)
    vals = _evals(b)
    receipt = take_upload(b.upload_id, user, 'fleet')[0] if b.upload_id else None
    cur = conn.execute('''INSERT INTO vehicle_expenses (vehicle_id, date, category, amount, liters, km, vendor, description, source, receipt,
                          created_by, created_at) VALUES (?,?,?,?,?,?,?,?, 'manual', ?,?,?)''', (vid, *vals, receipt, user['id'], db.now()))
    conn.commit()
    return {'id': cur.lastrowid}


@router.put('/expenses/{eid}')
def update_expense(eid: int, b: ExpenseIn, user=Depends(fleet_user), conn=db.DB):
    e = db.row(conn.execute('SELECT * FROM vehicle_expenses WHERE id = ?', (eid,)))
    if not e:
        raise HTTPException(404, 'Gider bulunamadı')
    d, cat, amount, liters, km, vendor, desc = _evals(b)
    if e['source'] != 'manual':   # muhasebeden gelen: tarih / tutar kaynağa bağlı; kategori, litre, km, not düzenlenir
        d, amount, vendor = e['date'], e['amount'], e['vendor']
    conn.execute('UPDATE vehicle_expenses SET date = ?, category = ?, amount = ?, liters = ?, km = ?, vendor = ?, description = ? WHERE id = ?',
                 (d, cat, amount, liters, km, vendor, desc, eid))
    conn.commit()
    return {'ok': True}


@router.delete('/expenses/{eid}')
def delete_expense(eid: int, user=Depends(fleet_user), conn=db.DB):
    e = db.row(conn.execute('SELECT * FROM vehicle_expenses WHERE id = ?', (eid,)))
    if not e:
        raise HTTPException(404, 'Gider bulunamadı')
    conn.execute('DELETE FROM vehicle_expenses WHERE id = ?', (eid,))
    conn.commit()
    if e['receipt']:
        (config.UPLOAD_DIR / e['receipt']).unlink(missing_ok=True)
    return {'ok': True}


# ---------------- Muhasebe / finans hareketlerini etiketleme ----------------
def _since(days):
    from datetime import timedelta
    return (date.today() - timedelta(days=max(1, min(days, 3660)))).isoformat()


@router.get('/movements/list')
def movements(days: int = 365, user=Depends(fleet_user), conn=db.DB):
    vs = db.rows(conn.execute('SELECT id, plate, brand, model, active, ownership FROM field_vehicles ORDER BY active DESC, plate'))
    return {'rows': fleet.moves(conn, _since(days)), 'vehicles': vs, 'categories': fleet.CATEGORIES,
            'accounts': len(fleet.expense_accounts(conn))}


class Alloc(BaseModel):
    vehicle_id: int
    amount: float


class TagIn(BaseModel):
    ref: str
    allocations: List[Alloc]
    category: Optional[str] = None
    liters: Optional[float] = None
    km: Optional[float] = None
    note: Optional[str] = None


def _tag(conn, user, m, allocs, category=None, liters=None, km=None, note=None):
    allocs = [a for a in allocs if a.amount and a.amount > 0]
    if not allocs:
        raise HTTPException(400, 'En az bir araç ve tutar gerekli')
    if len({a.vehicle_id for a in allocs}) != len(allocs):
        raise HTTPException(400, 'Aynı araç iki kez seçilmiş')
    if sum(a.amount for a in allocs) > m['amount'] + 0.01:
        raise HTTPException(400, f"Dağıtılan tutar hareket tutarını ({m['amount']:.2f}) aşıyor")
    for a in allocs:
        if not conn.execute('SELECT 1 FROM field_vehicles WHERE id = ?', (a.vehicle_id,)).fetchone():
            raise HTTPException(400, 'Araç bulunamadı')
    cat = category if category in fleet.CATEGORIES else m['category']
    desc = (note or '').strip()[:1000] or m.get('note') or ', '.join(m.get('accounts') or [])[:1000] or None
    conn.execute('DELETE FROM vehicle_expenses WHERE ref = ?', (m['ref'],))
    conn.execute('DELETE FROM vehicle_ignored WHERE ref = ?', (m['ref'],))
    one = len(allocs) == 1
    now = db.now()
    for a in allocs:
        conn.execute('''INSERT INTO vehicle_expenses (vehicle_id, date, category, amount, liters, km, vendor, description, source, ref, ref_total,
                        created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (a.vehicle_id, m['date'], cat, round(a.amount, 2), liters if one and liters else None, km if one and km else None,
                      (m.get('vendor') or '')[:160] or None, desc, m['source'], m['ref'], m['amount'], user['id'], now))


@router.post('/movements/tag')
def tag(b: TagIn, user=Depends(fleet_user), conn=db.DB):
    m = fleet.move_by_ref(conn, b.ref)
    if not m:
        raise HTTPException(404, 'Hareket bulunamadı (muhasebe verisi yeniden aktarılmış olabilir; listeyi yenileyin)')
    _tag(conn, user, m, b.allocations, b.category, b.liters, b.km, b.note)
    conn.commit()
    return {'ok': True}


@router.delete('/movements/tag')
def untag(ref: str, user=Depends(fleet_user), conn=db.DB):
    n = conn.execute('DELETE FROM vehicle_expenses WHERE ref = ?', (ref,)).rowcount
    conn.commit()
    return {'ok': True, 'removed': n}


class IgnoreIn(BaseModel):
    ref: str
    ignore: bool = True


@router.post('/movements/ignore')
def ignore(b: IgnoreIn, user=Depends(fleet_user), conn=db.DB):
    if b.ignore:
        conn.execute('INSERT OR IGNORE INTO vehicle_ignored (ref, user_id, created_at) VALUES (?,?,?)', (b.ref[:120], user['id'], db.now()))
    else:
        conn.execute('DELETE FROM vehicle_ignored WHERE ref = ?', (b.ref,))
    conn.commit()
    return {'ok': True}


class AutoIn(BaseModel):
    refs: List[str] = []
    days: int = 365


@router.post('/movements/auto')
def auto_tag(b: AutoIn, user=Depends(fleet_user), conn=db.DB):
    """Plaka / anahtar kelimeyle tek araca eşleşen etiketsiz hareketlerin tamamını o araca yazar."""
    want = set(b.refs)
    n = 0
    for m in fleet.moves(conn, _since(b.days)):
        if m['tags'] or m['ignored'] or m['match'] != 'plaka' or len(m['suggest']) != 1 or (want and m['ref'] not in want):
            continue
        _tag(conn, user, m, [Alloc(vehicle_id=m['suggest'][0], amount=m['amount'])])
        n += 1
    conn.commit()
    return {'tagged': n}


# ---------------- Rapor / ayarlar ----------------
@router.get('/report/summary')
def report(year: int = 0, user=Depends(fleet_user), conn=db.DB):
    year = year or date.today().year
    y0, y1 = f'{year}-01-01', f'{year}-12-31'
    rows = db.rows(conn.execute('''SELECT e.vehicle_id, v.plate, v.brand, v.model, v.active, e.category, SUBSTR(e.date, 6, 2) AS month,
                                   SUM(e.amount) AS amount, SUM(e.liters) AS liters FROM vehicle_expenses e JOIN field_vehicles v ON v.id = e.vehicle_id
                                   WHERE e.date BETWEEN ? AND ? GROUP BY e.vehicle_id, e.category, month''', (y0, y1)))
    years = [r[0] for r in conn.execute("SELECT DISTINCT SUBSTR(date, 1, 4) FROM vehicle_expenses ORDER BY 1 DESC")]
    return {'year': year, 'rows': rows, 'years': years or [str(year)], 'categories': fleet.CATEGORIES}


@router.get('/settings/form')
def get_settings(user=Depends(fleet_user), conn=db.DB):
    s = fleet.settings(conn)
    s['default_clauses'], s['default_equipment'] = fleet.CLAUSES, fleet.EQUIPMENT
    return s


class SettingsIn(BaseModel):
    clauses: str = ''
    equipment: List[str] = []


@router.put('/settings/form')
def put_settings(b: SettingsIn, user=Depends(fleet_user), conn=db.DB):
    eq = [x.strip()[:80] for x in b.equipment if x and x.strip()][:40]
    v = json.dumps({'clauses': b.clauses.strip()[:8000], 'equipment': eq}, ensure_ascii=False)
    conn.execute("INSERT INTO app_kv (k, v) VALUES ('fleet_settings', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (v,))
    conn.commit()
    return {'ok': True}
