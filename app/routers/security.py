"""Güvenlik (fabrika girişi): gelen araçların plakası kaydedilir, çıkışta "çıkış yaptı" denir; giriş / çıkış kayıtları.
Güvenlik rolündeki kullanıcı yalnızca bu modülü görür. Parktaki araçlar Sekreterya'da misafir kaydına bağlanabilir."""
import json
import re
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, exitpass

router = APIRouter(prefix='/api/security')
security_user = auth.require_module('security')
admin_user = auth.require_module('admin')
BC_KEY = 'building_control'   # app_kv: {'times': ['HH:MM', ...]} günlük bina kontrol saatleri
# Onaylı olmayan kaydın çıkış kapısında gösterilecek gerekçesi
_NOT_APPROVED = {'BEKLIYOR': 'Onay bekliyor', 'REDDEDILDI': 'Reddedilmiş', 'IPTAL': 'İptal edilmiş'}


class VehicleIn(BaseModel):
    plate: str
    note: Optional[str] = None


def norm_plate(p):
    """Plaka büyük harf, tek boşluklu (34 ABC 123); boşluksuz girilirse il kodu / harf / sayı arasına boşluk konur."""
    p = re.sub(r'\s+', ' ', (p or '').strip().upper().replace('İ', 'I').replace('-', ' '))
    compact = p.replace(' ', '')
    m = re.fullmatch(r'(\d{2})([A-Z]{1,3})(\d{2,5})', compact)
    return f'{m[1]} {m[2]} {m[3]}' if m else p


VEHICLE_SELECT = '''SELECT v.*, ue.full_name AS entered_by_name, ux.full_name AS exited_by_name,
       (SELECT g.code FROM guest_visit_vehicles gv JOIN guest_visits g ON g.id = gv.visit_id
        WHERE gv.vehicle_id = v.id ORDER BY g.id DESC LIMIT 1) AS visit_code
FROM vehicle_visits v LEFT JOIN users ue ON ue.id = v.entered_by LEFT JOIN users ux ON ux.id = v.exited_by'''


def parked(conn):
    return db.rows(conn.execute(VEHICLE_SELECT + ' WHERE v.exited_at IS NULL ORDER BY v.entered_at DESC, v.id DESC'))


@router.get('/vehicles')
def vehicles(user=Depends(security_user), conn=db.DB):
    return parked(conn)


@router.post('/vehicles')
def vehicle_in(body: VehicleIn, user=Depends(security_user), conn=db.DB):
    plate = norm_plate(body.plate)
    if len(plate.replace(' ', '')) < 4:
        raise HTTPException(400, 'Plakayı girin')
    if conn.execute('SELECT 1 FROM vehicle_visits WHERE plate = ? AND exited_at IS NULL', (plate,)).fetchone():
        raise HTTPException(400, f'{plate} zaten içeride (çıkış yapmamış)')
    cur = conn.execute('INSERT INTO vehicle_visits (plate, note, entered_at, entered_by) VALUES (?,?,?,?)',
                       (plate, (body.note or '').strip() or None, db.now(), user['id']))
    db.audit(conn, user['id'], 'Araç girişi', 'vehicle', cur.lastrowid, plate)
    return {'id': cur.lastrowid, 'plate': plate}


@router.post('/vehicles/{vid}/exit')
def vehicle_out(vid: int, user=Depends(security_user), conn=db.DB):
    v = db.row(conn.execute('SELECT * FROM vehicle_visits WHERE id = ?', (vid,)))
    if not v:
        raise HTTPException(404, 'Kayıt bulunamadı')
    if v['exited_at']:
        raise HTTPException(400, 'Bu araç zaten çıkış yapmış')
    conn.execute('UPDATE vehicle_visits SET exited_at = ?, exited_by = ? WHERE id = ?', (db.now(), user['id'], vid))
    db.audit(conn, user['id'], 'Araç çıkışı', 'vehicle', vid, v['plate'])
    return {'ok': True}


@router.put('/vehicles/{vid}')
def vehicle_edit(vid: int, body: VehicleIn, user=Depends(security_user), conn=db.DB):
    """Hatalı girilen plakayı/notu çıkış yapmadan düzeltir (yalnızca hâlâ içerideki araç)."""
    v = db.row(conn.execute('SELECT * FROM vehicle_visits WHERE id = ?', (vid,)))
    if not v:
        raise HTTPException(404, 'Kayıt bulunamadı')
    if v['exited_at']:
        raise HTTPException(400, 'Çıkış yapmış araç düzenlenemez')
    plate = norm_plate(body.plate)
    if len(plate.replace(' ', '')) < 4:
        raise HTTPException(400, 'Geçerli bir plaka girin')
    if conn.execute('SELECT 1 FROM vehicle_visits WHERE plate = ? AND exited_at IS NULL AND id != ?', (plate, vid)).fetchone():
        raise HTTPException(400, f'{plate} zaten içeride (çıkış yapmamış)')
    conn.execute('UPDATE vehicle_visits SET plate = ?, note = ? WHERE id = ?',
                 (plate, (body.note or '').strip() or None, vid))
    db.audit(conn, user['id'], 'Araç plakası düzeltildi', 'vehicle', vid, f"{v['plate']} → {plate}")
    return {'id': vid, 'plate': plate}


# ---------- QR çıkış kodu doğrulama: onaylı izin / görev formunun kodu okutulur, personel çıkışı kaydedilir

class PassIn(BaseModel):
    token: str


def _record_exit(conn, name, kind, ref_id, scanned_by):
    conn.execute('INSERT INTO person_exits (person_name, kind, ref_id, scanned_by, at) VALUES (?,?,?,?,?)',
                 (name, kind, ref_id, scanned_by, db.now()))
    db.audit(conn, scanned_by, 'Personel çıkışı (QR)', 'person_exit', ref_id, f'{name} · {kind}')


def vehicle_enter(conn, plate, user_id, note='Görev dönüşü'):
    """Görev grubunun aracını güvenlik araç kaydında İÇERİ girmiş olarak işaretler.
    Açık (içeride) bir kayıt varsa kapatılıp yeni giriş açılır; yoksa doğrudan yeni giriş açılır."""
    if not plate:
        return None
    p = norm_plate(plate)
    open_v = db.row(conn.execute(
        'SELECT id FROM vehicle_visits WHERE plate = ? AND exited_at IS NULL ORDER BY id DESC LIMIT 1', (p,)))
    if open_v:
        conn.execute('UPDATE vehicle_visits SET exited_at = ?, exited_by = ? WHERE id = ?', (db.now(), user_id, open_v['id']))
    conn.execute('INSERT INTO vehicle_visits (plate, note, entered_at, entered_by) VALUES (?,?,?,?)',
                 (p, note, db.now(), user_id))
    return p


def vehicle_exit(conn, plate, user_id, note='Görev çıkışı'):
    """Görev grubunun aracını güvenlik araç kaydında DIŞARI çıkmış olarak işaretler (QR çıkışında).
    Açık bir giriş kaydı varsa çıkışı işlenir; yoksa (güvenlik girişini yapmadıysa) giriş açılıp hemen çıkış işaretlenir."""
    if not plate:
        return None
    p = norm_plate(plate)
    open_v = db.row(conn.execute(
        'SELECT id FROM vehicle_visits WHERE plate = ? AND exited_at IS NULL ORDER BY id DESC LIMIT 1', (p,)))
    if open_v:
        conn.execute('UPDATE vehicle_visits SET exited_at = ?, exited_by = ? WHERE id = ?', (db.now(), user_id, open_v['id']))
    else:
        conn.execute('INSERT INTO vehicle_visits (plate, note, entered_at, entered_by, exited_at, exited_by) VALUES (?,?,?,?,?,?)',
                     (p, note, db.now(), user_id, db.now(), user_id))
    return p


@router.post('/verify-pass')
def verify_pass(body: PassIn, user=Depends(security_user), conn=db.DB):
    """QR çıkış kodunu doğrular ve izin verilirse personel çıkışını kaydeder."""
    v = exitpass.verify_token(conn, body.token)
    if not v['ok']:
        return {'allow': False, 'reason': v.get('reason') or 'Geçersiz veya süresi dolmuş kod'}
    today = _date.today().isoformat()
    if v['kind'] == 'leave':
        r = db.row(conn.execute(
            '''SELECT l.*, e.first_name || ' ' || e.last_name AS name, e.title AS title
               FROM leave_requests l JOIN employees e ON e.id = l.employee_id WHERE l.id = ?''', (v['id'],)))
        if not r:
            return {'allow': False, 'reason': 'Kayıt bulunamadı'}
        if r['status'] != 'ONAYLANDI':
            return {'allow': False, 'type': 'leave', 'name': r['name'], 'reason': _NOT_APPROVED.get(r['status'], 'Onaylı değil')}
        start = (r['start_date'] or r['req_start'])[:10]
        end = (r['end_date'] or r['req_end'])[:10]
        info = {'type': 'leave', 'name': r['name'], 'title': r['title'], 'dates': {'start': start, 'end': end}}
        if today < start:
            return {'allow': False, 'reason': f'İzin {start} tarihinde başlıyor', **info}
        if today > end:
            return {'allow': False, 'reason': 'İzin süresi geçmiş', **info}
        _record_exit(conn, r['name'], 'leave', r['id'], user['id'])
        return {'allow': True, **info}
    # görev formu (araca/göreve özel; birden çok personel)
    r = db.row(conn.execute('SELECT * FROM duty_requests d WHERE d.id = ?', (v['id'],)))
    if not r:
        return {'allow': False, 'reason': 'Kayıt bulunamadı'}
    people = [row[0] for row in conn.execute(
        """SELECT e.first_name || ' ' || e.last_name FROM duty_people dp JOIN employees e ON e.id = dp.employee_id
           WHERE dp.duty_id = ? ORDER BY 1""", (v['id'],)).fetchall()]
    if not people:   # eski kayıt (duty_people yok) → employee_id'ye düş
        one = db.row(conn.execute("SELECT first_name || ' ' || last_name AS name FROM employees WHERE id = ?", (r['employee_id'],)))
        people = [one['name']] if one else []
    names = ', '.join(people) or '—'
    is_field = r.get('source') == 'field'   # saha görevi araç çıkışı (onaysız/otomatik aktif) → "şirket dışında"
    if r['status'] != 'ONAYLANDI':
        return {'allow': False, 'type': 'duty', 'name': names, 'people': people, 'source': r.get('source'),
                'reason': _NOT_APPROVED.get(r['status'], 'Onaylı değil')}
    depart = (r['depart_at'] or '')[:10]
    ret = (r['return_at'] or '')[:10] or None
    info = {'type': 'duty', 'name': names, 'people': people, 'destination': r['destination'], 'source': r.get('source'),
            'dates': {'depart': r['depart_at'], 'return': r['return_at']},
            **({'note': 'Saha görevi — şirket dışında'} if is_field else {})}
    if depart and today < depart:
        return {'allow': False, 'reason': f'Görev {depart} tarihinde başlıyor', **info}
    warn = 'Dikkat: tahmini dönüş tarihi geçmiş' if ret and today > ret else None
    if not r['exited_at']:   # ilk okutma → "Görevde"ye geç (manuel + saha görevleri)
        conn.execute('UPDATE duty_requests SET exited_at = ? WHERE id = ?', (db.now(), r['id']))
    for nm in people:   # her personel için çıkış kaydı
        _record_exit(conn, nm, 'duty', r['id'], user['id'])
    plate = vehicle_exit(conn, r['vehicle_plate'], user['id'])   # grubun aracını güvenlik araç kaydında dışarı çıkar
    veh = {'vehicle_plate': plate, 'vehicle_exited': bool(plate)} if plate else {}
    return {'allow': True, **info, **veh, **({'reason': warn} if warn else {})}


@router.get('/exits')
def person_exits(user=Depends(security_user), conn=db.DB):
    """Son personel çıkışları (QR ile okutulan izin / görev çıkışları)."""
    return db.rows(conn.execute(
        '''SELECT p.*, u.full_name AS scanned_by_name FROM person_exits p
           LEFT JOIN users u ON u.id = p.scanned_by ORDER BY p.id DESC LIMIT 100'''))


@router.get('/personnel')
def personnel(user=Depends(security_user), conn=db.DB):
    """Güvenlik için: şu an görevde olan araç/görev grupları (kart: plaka + personel + çıkış) ve bugün izinli personel."""
    from .hr import on_duty_groups, on_leave_today
    return {'on_duty': on_duty_groups(conn), 'on_leave': on_leave_today(conn)}


@router.post('/duty/{did}/return')
def duty_return(did: int, user=Depends(security_user), conn=db.DB):
    """Görev grubu fabrikaya döndü (güvenlik "Giriş Yaptı"): grubu "Görevde"den düşürür ve aracını İÇERİ girmiş işaretler."""
    r = db.row(conn.execute("SELECT * FROM duty_requests WHERE id = ? AND status = 'ONAYLANDI'", (did,)))
    if not r:
        raise HTTPException(404, 'Görev grubu bulunamadı')
    if r['returned_at']:
        raise HTTPException(400, 'Bu grup zaten giriş yaptı')
    conn.execute("UPDATE duty_requests SET returned_at = ?, return_kind = 'sirket' WHERE id = ?", (db.now(), did))
    plate = vehicle_enter(conn, r['vehicle_plate'], user['id'])
    db.audit(conn, user['id'], 'Görev dönüşü (şirkete giriş)', 'duty', did, plate or '—')
    return {'ok': True, 'vehicle_plate': plate, 'vehicle_entered': bool(plate)}


@router.get('/log')
def log(date_from: str = '', date_to: str = '', q: str = '', user=Depends(security_user), conn=db.DB):
    """Giriş / çıkış kayıtları (en yeni üstte); tarih aralığı giriş tarihine göre, en fazla 1000 kayıt."""
    where, args = ['1=1'], []
    if date_from:
        where.append('substr(v.entered_at, 1, 10) >= ?')
        args.append(date_from)
    if date_to:
        where.append('substr(v.entered_at, 1, 10) <= ?')
        args.append(date_to)
    if q.strip():
        where.append("replace(v.plate, ' ', '') LIKE ?")
        args.append(f"%{norm_plate(q).replace(' ', '')}%")
    return db.rows(conn.execute(VEHICLE_SELECT + f' WHERE {" AND ".join(where)} ORDER BY v.entered_at DESC, v.id DESC LIMIT 1000', args))


# ---------- Bina Kontrol: günlük bina turu (GPS rotası) ----------
def _bc_times(conn):
    r = conn.execute('SELECT v FROM app_kv WHERE k = ?', (BC_KEY,)).fetchone()
    try:
        return sorted(set(json.loads(r[0]).get('times', []))) if r else []
    except ValueError:
        return []


def _valid_day(s):
    try:
        return _date.fromisoformat((s or '')[:10]).isoformat()
    except (TypeError, ValueError):
        return _date.today().isoformat()


class StartIn(BaseModel):
    date: Optional[str] = None
    slot: Optional[str] = None


class PointIn(BaseModel):
    lat: float
    lng: float
    acc: Optional[float] = None


@router.get('/building')
def building_day(date: str = None, user=Depends(security_user), conn=db.DB):
    """Seçili günün bina kontrol turları: ayarlı saatler (bekliyor) + başlatılmış/bitmiş kayıtlar."""
    day = _valid_day(date)
    times = _bc_times(conn)
    rows = db.rows(conn.execute(
        '''SELECT c.*, u.full_name AS started_by_name,
                  (SELECT COUNT(*) FROM building_check_points p WHERE p.check_id = c.id) AS points,
                  (SELECT COUNT(*) FROM building_check_notes n WHERE n.check_id = c.id) AS notes
           FROM building_checks c LEFT JOIN users u ON u.id = c.started_by
           WHERE c.day = ? ORDER BY c.id''', (day,)))
    by_slot = {r['slot']: r for r in rows if r['slot']}
    out = []
    for t in times:   # ayarlı her saat için: kayıt varsa onu, yoksa "bekliyor"
        if t in by_slot:
            out.append(by_slot[t])
        else:
            out.append({'id': None, 'day': day, 'slot': t, 'status': 'BEKLIYOR', 'started_at': None, 'finished_at': None, 'points': 0, 'notes': 0})
    out += [r for r in rows if not r['slot']]   # saatsiz (elle başlatılan) turlar
    out.sort(key=lambda r: (r.get('slot') or '~', r.get('id') or 0))
    return {'date': day, 'times': times, 'checks': out}


@router.get('/building/active')
def building_active(user=Depends(security_user), conn=db.DB):
    """Süren (DEVAM) bina kontrolü — HANGİ GÜN/OTURUM olursa olsun (tek). Yoksa null.
    Sistem kapansa / tarih değişse bile kullanıcı bu turu görüp bitirebilsin diye tarihten bağımsızdır."""
    c = db.row(conn.execute(
        '''SELECT c.*, u.full_name AS started_by_name,
                  (SELECT COUNT(*) FROM building_check_points p WHERE p.check_id = c.id) AS points
           FROM building_checks c LEFT JOIN users u ON u.id = c.started_by
           WHERE c.status = 'DEVAM' ORDER BY c.id DESC LIMIT 1'''))
    return {'check': c}


@router.post('/building/start')
def building_start(body: StartIn, user=Depends(security_user), conn=db.DB):
    day = _valid_day(body.date)
    slot = (body.slot or '').strip()[:5] or None
    # Aynı anda yalnızca bir süren kontrol olabilir (hangi gün/saat olursa olsun)
    if db.row(conn.execute("SELECT id FROM building_checks WHERE status = 'DEVAM'")):
        raise HTTPException(400, 'Zaten süren bir bina kontrolü var; önce onu bitirin')
    if slot and db.row(conn.execute("SELECT id FROM building_checks WHERE day = ? AND slot = ? AND status != 'IPTAL'", (day, slot))):
        raise HTTPException(400, 'Bu saat için kontrol zaten başlatılmış')
    cur = conn.execute('INSERT INTO building_checks (day, slot, status, started_at, started_by) VALUES (?,?,?,?,?)',
                       (day, slot, 'DEVAM', db.now(), user['id']))
    db.audit(conn, user['id'], 'Bina kontrol turu başlattı', 'building_check', cur.lastrowid, slot or '')
    return {'id': cur.lastrowid}


@router.post('/building/{cid}/point')
def building_point(cid: int, body: PointIn, user=Depends(security_user), conn=db.DB):
    c = db.row(conn.execute('SELECT * FROM building_checks WHERE id = ?', (cid,)))
    if not c or c['status'] != 'DEVAM':
        raise HTTPException(400, 'Tur aktif değil')
    conn.execute('INSERT INTO building_check_points (check_id, lat, lng, acc, at) VALUES (?,?,?,?,?)',
                 (cid, body.lat, body.lng, body.acc, db.now()))
    return {'ok': True}


@router.post('/building/{cid}/finish')
def building_finish(cid: int, user=Depends(security_user), conn=db.DB):
    c = db.row(conn.execute('SELECT * FROM building_checks WHERE id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Tur bulunamadı')
    if c['status'] == 'DEVAM':
        conn.execute("UPDATE building_checks SET status = 'BITTI', finished_at = ? WHERE id = ?", (db.now(), cid))
        db.audit(conn, user['id'], 'Bina kontrol turu bitirdi', 'building_check', cid, c['slot'] or '')
    return {'ok': True}


@router.get('/building/{cid}/track')
def building_track(cid: int, user=Depends(security_user), conn=db.DB):
    c = db.row(conn.execute('SELECT c.*, u.full_name AS started_by_name FROM building_checks c LEFT JOIN users u ON u.id = c.started_by WHERE c.id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Tur bulunamadı')
    c['points'] = db.rows(conn.execute('SELECT lat, lng, acc, at FROM building_check_points WHERE check_id = ? ORDER BY id', (cid,)))
    return c


class BCNoteIn(BaseModel):
    note: str


@router.get('/building/{cid}/notes')
def building_notes(cid: int, user=Depends(security_user), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT n.id, n.note, n.created_at, u.full_name AS by_name FROM building_check_notes n
           LEFT JOIN users u ON u.id = n.created_by WHERE n.check_id = ? ORDER BY n.id DESC''', (cid,)))


@router.post('/building/{cid}/note')
def building_add_note(cid: int, body: BCNoteIn, user=Depends(security_user), conn=db.DB):
    if not db.row(conn.execute('SELECT id FROM building_checks WHERE id = ?', (cid,))):
        raise HTTPException(404, 'Tur bulunamadı')
    note = (body.note or '').strip()[:1000]
    if not note:
        raise HTTPException(400, 'Not girin')
    cur = conn.execute('INSERT INTO building_check_notes (check_id, note, created_by, created_at) VALUES (?,?,?,?)',
                       (cid, note, user['id'], db.now()))
    return {'id': cur.lastrowid}


@router.get('/building/config')
def building_config(user=Depends(security_user), conn=db.DB):
    return {'times': _bc_times(conn)}


class BCConfigIn(BaseModel):
    times: list[str] = []


@router.put('/building/config')
def building_config_set(body: BCConfigIn, user=Depends(admin_user), conn=db.DB):
    """Günlük bina kontrol saatlerini ayarla (yalnızca Sistem Yöneticisi)."""
    clean = []
    for t in body.times:
        t = (t or '').strip()
        if re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', t):
            clean.append(t)
    clean = sorted(set(clean))
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (BC_KEY, json.dumps({'times': clean})))
    return {'times': clean}
