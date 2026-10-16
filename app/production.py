"""Sipariş ve parça durum kuralları."""
import json

from fastapi import HTTPException

from . import auth, catalogs, db, spares

# Parça durumları
WAITING, PRINTING, WAREHOUSE, ASSEMBLY, ERROR = 'BEKLIYOR', 'URETIMDE', 'DEPO', 'MONTAJ', 'HATA'
PART_STATES_TEXT = {WAITING: 'Üretilmedi', PRINTING: 'Üretimde', WAREHOUSE: 'Depoda', ASSEMBLY: 'Montajda', ERROR: 'Hata'}
# Sipariş durumları. Montajdan sonra: MONTAJ (3 bölüm) → KALIBRASYON → SAHA_ONAY (depocu onayı bekler)
# → TAMAMLANDI (saha deposunda, kuyruk numarası almış; sahaya yalnızca bu durumdaki uçaklar gider).
# → HURDA: tek kullanımlık ürün (products.usage_type = 'TEK') uçtuktan sonra; yeniden sahaya gidemez.
ORDER_STATUSES = ['SIPARIS', 'URETIM', 'HATA', 'DEPO', 'MONTAJ', 'SAHADA_MONTAJ', 'KALIBRASYON', 'SAHA_ONAY', 'TAMAMLANDI', 'HURDA']
AFTER_ASSEMBLY = ('KALIBRASYON', 'SAHA_ONAY', 'TAMAMLANDI', 'HURDA')   # parçalar artık uçağın içinde
CLOSED = ('TAMAMLANDI', 'HURDA')   # kapanmış sipariş (üretim bitti)
# Montaj aşamaları: fabrikada (MONTAJ) ya da sahaya götürülüp sahada (SAHADA_MONTAJ); adımlar ikisinde de aynıdır
IN_ASSEMBLY = ('MONTAJ', 'SAHADA_MONTAJ')

CALIBRATION_CHECKS = {
    'electronics': 'Elektronik kat takıldı mı?',
    'caliper': 'Kumpas kalibrasyonu yapıldı mı?',
    'cg': "CG'si alındı mı?",
    'motor': 'Motor test edildi mi?',
    'ready': 'Uçuşa hazır mı?',
}
# Birleştirme montajı: bölümler ve elektronik montajlar bittikten sonra kanatların gövdeye, elektronik kat ve
# K04'ün gövdeye takılması. Bu adım bitince uçak kalibrasyona geçer.
FINAL_STEP = 'BIRLESTIRME'
FINAL_CHECKS = {
    'wings': 'Sol ve sağ kanat gövdeye monte edildi mi?',
    'electronics': 'Elektronik kat ve K04 gövdeye monte edildi mi?',
}
# Kapak montajı: kapaklar en son, birleştirmeden sonra takılır; bitince uçak kalibrasyona geçer
COVER_STEP = 'KAPAK'
MIN_COVER_STAFF = 1
STEP_TEXT = {'BIRLESTIRME': 'Birleştirme montajı', 'KAPAK': 'Kapak montajı', 'KALIBRASYON': 'Kalibrasyon', 'SAHA_DEPO': 'Saha deposu onayı'}
MIN_ASSEMBLY_STAFF = 2
MIN_ELECTRONICS_STAFF = 1

EVENT_TEXT = {
    'URETIME_BASLADI': 'Üretime başladı',
    'YAZICIYA_GONDERILDI': 'G-code yazıcıya gönderildi, baskı başlatıldı',
    'DOGRUDAN_DEPO': 'Doğrudan depoya eklendi (Sistem Yöneticisi onayıyla, basılmış)',
    'DOGRUDAN_TALEP': 'Doğrudan depoya ekleme talebi (onay bekliyor)',
    'URETIM_TAMAMLANDI': 'Üretim tamamlandı, depoya teslim edildi',
    'HATA': 'Hata verdi',
    'DEPO_ONAY': 'Depo teslim aldı (onay)',
    'MONTAJA_ALINDI': 'Montaja alındı',
    'MONTAJ_TAMAMLANDI': 'Montaj tamamlandı',
    'ELEKTRONIK_MONTAJ': 'Elektronik komponentler monte edildi',
    'AKTARILDI': 'Siparişler arası aktarıldı',
}


def create_order(conn, user_id, product, start_date, end_date, note, company_id=None):
    code = db.next_code(conn, 'orders', 'code', 'SP')
    now = db.now()
    cur = conn.execute(
        '''INSERT INTO orders (code, created_by, created_at, start_date, end_date, note, product_id, company_id)
           VALUES (?,?,?,?,?,?,?,?)''',
        (code, user_id, now, start_date, end_date, note, product['id'], company_id))
    oid = cur.lastrowid
    conn.executemany(
        'INSERT INTO order_parts (order_id, part_id, updated_at) VALUES (?,?,?)',
        [(oid, pid, now) for pid in catalogs.product_part_ids(product)])
    return oid, code


def _schema(conn, order_id):
    return conn.execute('SELECT p.schema FROM orders o JOIN products p ON p.id = o.product_id WHERE o.id = ?',
                        (order_id,)).fetchone()[0]


def recompute(conn, order_id, at=None):
    """Parça durumlarından sipariş durumunu türetir. Tüm parçalar depoya girip
    onaylandığında hepsi otomatik olarak montaja alınır (at: montaja alınma zamanı)."""
    status = conn.execute('SELECT status FROM orders WHERE id = ?', (order_id,)).fetchone()[0]
    if status in IN_ASSEMBLY or status in AFTER_ASSEMBLY:
        return status
    # Elektronik parçalar (elektronik kat, K04) da diğer parçalar gibi sayılır: depoya girmeden sipariş Depo/Montaj
    # olmaz. Montaja alınırken depoda kalırlar; elektronik komponentleri takılınca montaja geçerler.
    eparts = catalogs.electronics_parts(_schema(conn, order_id))
    parts = db.rows(conn.execute('SELECT id, part_id, state, approved_at FROM order_parts WHERE order_id = ?', (order_id,)))
    states = [p['state'] for p in parts]
    in_depot = all(s in (WAREHOUSE, ASSEMBLY) for s in states)

    product = db.row(conn.execute('SELECT p.schema, o.id, o.code, o.product_id FROM orders o JOIN products p ON p.id = o.product_id '
                                  'WHERE o.id = ?', (order_id,)))
    if spares.is_stocked(product) and in_depot and all(p['approved_at'] for p in parts):
        # Yedek parça: montaj yok; depo onayıyla sipariş tamamlanır, bir baskıda üretilen adet stoğa girer
        now = at or db.now()
        conn.execute("UPDATE orders SET status = 'TAMAMLANDI', completed_at = ? WHERE id = ?", (now, order_id))
        spares.produced(conn, product, now)
        return 'TAMAMLANDI'
    if in_depot and all(p['approved_at'] for p in parts):
        to_move = [p['id'] for p in parts if p['state'] == WAREHOUSE and p['part_id'] not in eparts]
        now = at or db.now()
        for pid in to_move:
            conn.execute('UPDATE order_parts SET state = ?, updated_at = ? WHERE id = ?', (ASSEMBLY, now, pid))
            conn.execute('INSERT INTO part_events (order_part_id, event, at) VALUES (?,?,?)',
                         (pid, 'MONTAJA_ALINDI', now))
        new = 'MONTAJ'
    elif ERROR in states:
        new = 'HATA'
    elif in_depot:
        new = 'DEPO'
    elif any(s != WAITING for s in states):
        new = 'URETIM'
    else:
        new = 'SIPARIS'
    if new != status:
        conn.execute('UPDATE orders SET status = ? WHERE id = ?', (new, order_id))
    return new


def order_summaries(conn, where='1=1', args=()):
    orders = db.rows(conn.execute(
        f'''SELECT o.*, u.full_name AS created_by_name, p.name AS product_name, p.serial AS product_serial,
                   p.code AS product_code, p.schema AS product_schema, p.queue_prefix, p.type AS product_type,
                   (p.schema LIKE 'part-%' OR p.schema LIKE 'spare-%' OR (p.schema = 'custom' AND p.printed = 1)) AS product_stocked,
                   p.per_print, c.name AS company_name, c.logo AS company_logo
            FROM orders o LEFT JOIN users u ON u.id = o.created_by
            LEFT JOIN products p ON p.id = o.product_id
            LEFT JOIN companies c ON c.id = o.company_id
            WHERE {where} ORDER BY o.id DESC''', args))
    counts = {}
    for r in conn.execute('SELECT order_id, state, COUNT(*) FROM order_parts GROUP BY order_id, state'):
        counts.setdefault(r[0], {})[r[1]] = r[2]
    for o in orders:
        c = counts.get(o['id'], {})
        total = sum(c.values()) or 1
        done = c.get(WAREHOUSE, 0) + c.get(ASSEMBLY, 0)
        o['counts'] = c
        o['total_parts'] = total
        o['progress'] = 100 if o['status'] in CLOSED else round(done * 100 / total)
    return orders


# ---------- Montaj, kalibrasyon, saha deposu

def sync_catalog_parts(conn):
    """Kataloğa sonradan eklenen parçaları (ör. elektronik kat) mevcut siparişlere ekler. Montajı bitmiş
    uçaklarda parça takılı kabul edilir; diğerlerinde üretilmemiş olarak başlar."""
    added = 0
    for o in db.rows(conn.execute(
            'SELECT o.id, o.status, p.schema, p.code, p.printed FROM orders o JOIN products p ON p.id = o.product_id')):
        have = {r[0] for r in conn.execute('SELECT part_id FROM order_parts WHERE order_id = ?', (o['id'],))}
        missing = [pid for pid in catalogs.product_part_ids(o) if pid not in have]
        state = ASSEMBLY if o['status'] in AFTER_ASSEMBLY else WAITING
        conn.executemany('INSERT INTO order_parts (order_id, part_id, state, updated_at) VALUES (?,?,?,?)',
                         [(o['id'], pid, state, db.now()) for pid in missing])
        added += len(missing)
    return added


def assembly_info(conn, order):
    """Siparişin montaj adımları: {adım: {at, staff, recorded_by_name, checklist}} ve bölüm adları."""
    names, _ = catalogs.sections(order['product_schema'])
    steps = {}
    for r in db.rows(conn.execute(
            '''SELECT s.*, u.full_name AS recorded_by_name FROM assembly_steps s
               LEFT JOIN users u ON u.id = s.recorded_by WHERE s.order_id = ?''', (order['id'],))):
        r['staff'] = db.rows(conn.execute(
            '''SELECT u.id, u.full_name FROM assembly_staff a JOIN users u ON u.id = a.user_id
               WHERE a.step_id = ? ORDER BY u.full_name''', (r['id'],)))
        r['checklist'] = json.loads(r['checklist']) if r['checklist'] else None
        steps[r['step']] = r
    electronics = []
    for pid, name in catalogs.electronics_parts(order['product_schema']).items():
        row = db.row(conn.execute('SELECT state, approved_at FROM order_parts WHERE order_id = ? AND part_id = ?',
                                  (order['id'], pid))) or {}
        electronics.append({'part_id': pid, 'name': name, 'step': catalogs.electronics_step(pid), **row})
    ready = all(k in steps for k in names) and all(e['step'] in steps for e in electronics)
    covers = catalogs.cover_parts(order['product_schema'])
    cover_info = None
    if covers:
        rows = db.rows(conn.execute(f"SELECT state, approved_at FROM order_parts WHERE order_id = ? AND part_id IN ({','.join('?' * len(covers))})",
                                    (order['id'], *covers)))
        n = sum(1 for r in rows if r['state'] in (WAREHOUSE, ASSEMBLY) and r['approved_at'])
        cover_info = {'step': COVER_STEP, 'parts': covers, 'total': len(rows), 'ready': n, 'all_ready': n == len(rows),
                      'min_staff': MIN_COVER_STAFF}
    return {'sections': names, 'section_parts': section_parts(conn, order), 'covers': cover_info, 'steps': steps, 'checks': CALIBRATION_CHECKS, 'min_staff': MIN_ASSEMBLY_STAFF,
            'electronics': electronics, 'min_electronics_staff': MIN_ELECTRONICS_STAFF,
            'final': {'step': FINAL_STEP, 'checks': FINAL_CHECKS, 'ready': ready}}


def section_parts(conn, order):
    """Bölüm başına parça hazırlığı {bölüm: {total, ready, all_ready, last_approved}}. Bir bölümün tüm parçaları depoya
    girip onaylanınca (siparişin diğer parçaları üretimde olsa da) o bölümün montajı yapılabilir."""
    names, part_sections = catalogs.sections(order['product_schema'])
    covers = set(catalogs.cover_parts(order['product_schema']))   # kapaklar bölüme sayılmaz; en son takılır
    parts = db.rows(conn.execute('SELECT part_id, state, approved_at FROM order_parts WHERE order_id = ?', (order['id'],)))
    parts = [p for p in parts if p['part_id'] not in covers]
    out = {}
    for key in names:
        mine = [p for p in parts if part_sections.get(p['part_id']) == key]
        ok = [p for p in mine if p['state'] in (WAREHOUSE, ASSEMBLY) and p['approved_at']]
        out[key] = {'total': len(mine), 'ready': len(ok), 'all_ready': bool(mine) and len(ok) == len(mine),
                    'last_approved': max((p['approved_at'] for p in ok), default=None)}
    return out


def _staff(conn, staff_ids, role=auth.ASSEMBLER, minimum=MIN_ASSEMBLY_STAFF):
    ids = sorted(set(staff_ids or []))
    if len(ids) < minimum:
        raise HTTPException(400, f'En az {minimum} {role.lower()} seçin')
    ok = {u for u in ids if auth.has_role_or_intern(conn, u, role)}   # yardımcı personelde stajer de olur
    if ok != set(ids):
        raise HTTPException(400, f'Seçilen kişilerden biri {role.lower()} değil')
    if not set(ids) - auth.interns(conn):
        raise HTTPException(400, f'Stajerlerin yanında en az 1 {role.lower()} seçin')
    return ids


def _last_time(conn, oid, steps=()):
    """Bir sonraki adım bu zamandan önce olamaz: parçaların son depo onayı ve verilen adımların en geç zamanı."""
    eparts = list(catalogs.electronics_parts(_schema(conn, oid)))
    times = [conn.execute(f"SELECT MAX(approved_at) FROM order_parts WHERE order_id = ? "
                          f"AND part_id NOT IN ({','.join('?' * len(eparts)) or "''"})", (oid, *eparts)).fetchone()[0]]
    if steps:
        times.append(conn.execute(
            f"SELECT MAX(at) FROM assembly_steps WHERE order_id = ? AND step IN ({','.join('?' * len(steps))})",
            (oid, *steps)).fetchone()[0])
    return max((t for t in times if t), default=None)


def record_step(conn, order, step, user_id, at, staff_ids=(), checklist=None, note=None):
    cur = conn.execute(
        '''INSERT INTO assembly_steps (order_id, step, at, checklist, note, recorded_by, recorded_at)
           VALUES (?,?,?,?,?,?,?)''',
        (order['id'], step, at, json.dumps(checklist, ensure_ascii=False) if checklist else None, note, user_id, db.now()))
    conn.executemany('INSERT INTO assembly_staff (step_id, user_id) VALUES (?,?)', [(cur.lastrowid, u) for u in staff_ids])


def complete_section(conn, order, section, user_id, at_value, staff_ids):
    """Montaj bölümü (sol kanat, sağ kanat, orta gövde) tamamlandı. Uçak montajdayken ya da — sipariş henüz
    üretimdeyken — bölümün tüm parçaları depoya girip onaylandıysa yapılabilir (örn. gövde basılırken kanat montajı).
    Bölümün parçaları montaja geçer."""
    names, part_sections = catalogs.sections(order['product_schema'])
    if section not in names:
        raise HTTPException(404, 'Montaj bölümü bulunamadı')
    if order['status'] in AFTER_ASSEMBLY:
        raise HTTPException(400, 'Uçak montaj aşamasını geçmiş')
    if conn.execute('SELECT 1 FROM assembly_steps WHERE order_id = ? AND step = ?', (order['id'], section)).fetchone():
        raise HTTPException(400, f'{names[section]} montajı zaten tamamlanmış')
    early = order['status'] not in IN_ASSEMBLY
    info = section_parts(conn, order)[section]
    if early and not info['all_ready']:
        raise HTTPException(400, f'{names[section]} montajı için bölümün tüm parçaları depoya girip onaylanmalı '
                                 f'({info["ready"]}/{info["total"]} hazır)')
    staff = _staff(conn, staff_ids)
    last = info['last_approved'] if early else _last_time(conn, order['id'])
    at = db.pick_time(at_value, last, 'Montaj zamanı', 'depo onayı' if early else 'montaja alınma')
    record_step(conn, order, section, user_id, at, staff)
    part_rows = [(r[0], r[1], r[2]) for r in conn.execute('SELECT id, part_id, state FROM order_parts WHERE order_id = ?', (order['id'],))]
    covers = set(catalogs.cover_parts(order['product_schema']))
    mine = [(pid, state) for pid, part, state in part_rows if part_sections.get(part) == section and part not in covers]
    conn.executemany('UPDATE order_parts SET state = ?, updated_at = ? WHERE id = ?',
                     [(ASSEMBLY, at, pid) for pid, state in mine if state == WAREHOUSE])
    conn.executemany('INSERT INTO part_events (order_part_id, event, user_id, note, at) VALUES (?,?,?,?,?)',
                     [(pid, 'MONTAJ_TAMAMLANDI', user_id, names[section], at) for pid, _ in mine])
    if early:
        return recompute(conn, order['id'])
    return advance_to_calibration(conn, order)


def advance_to_calibration(conn, order):
    """Üç montaj bölümü, her elektronik parçanın (elektronik kat, K04) montajı, birleştirme ve kapak montajı bitince
    uçak kalibrasyona geçer."""
    need = _pre_final_steps(order) | {FINAL_STEP} | ({COVER_STEP} if catalogs.cover_parts(order['product_schema']) else set())
    done = {r[0] for r in conn.execute('SELECT step FROM assembly_steps WHERE order_id = ?', (order['id'],))}
    status = conn.execute('SELECT status FROM orders WHERE id = ?', (order['id'],)).fetchone()[0]
    if status in IN_ASSEMBLY and need <= done:
        conn.execute("UPDATE orders SET status = 'KALIBRASYON' WHERE id = ?", (order['id'],))
        assign_queue_no(conn, order['id'])   # montaj bitti: uçağın metal etiketine yazılacak kuyruk numarası
        spares.consume(conn, order)   # montaj tamamlandı: kullanılan yedek parçalar stoktan düşer
        if status == 'SAHADA_MONTAJ':
            start_field_task_for(conn, order)
        return 'KALIBRASYON'
    return status


def assign_queue_no(conn, order_id):
    """Uçağa kuyruk numarası (ör. CYZ-0001, CYZ2-0001): ürün öneki + 4 hane, ürün başına sıralı. Montaj bitip kalibrasyona
    geçerken atanır (metal etikete yazılır); bir kez atanan numara değişmez. Numarayı döndürür."""
    row = conn.execute('''SELECT o.queue_no, p.queue_prefix, p.code FROM orders o JOIN products p ON p.id = o.product_id
                          WHERE o.id = ?''', (order_id,)).fetchone()
    if not row or row[0]:
        return row[0] if row else None
    q = db.next_code(conn, 'orders', 'queue_no', row[1] or row[2])
    conn.execute('UPDATE orders SET queue_no = ? WHERE id = ?', (q, order_id))
    return q


def start_field_task_for(conn, order):
    """Sahada montajı biten (kalibrasyona geçen) uçak: bulunduğu saha görevi hâlâ başlangıçtaysa göreve başlanmış
    sayılır — görev "Görevde" olur; başlama zamanı son montaj adımının (kapak / birleştirme) zamanıdır. Görevdeki diğer montaj
    aşamasındaki uçaklar da "Sahada Montaj" olur (göreve elle başlamakla aynı)."""
    at = conn.execute('SELECT MAX(at) FROM assembly_steps WHERE order_id = ? AND step IN (?, ?)',
                      (order['id'], FINAL_STEP, COVER_STEP)).fetchone()[0] or db.now()
    for tid, code, created_at in conn.execute(
            """SELECT t.id, t.code, t.created_at FROM field_tasks t JOIN field_flights f ON f.task_id = t.id
               WHERE f.order_id = ? AND t.status = 'BASLANGIC'""", (order['id'],)).fetchall():
        conn.execute("UPDATE field_tasks SET status = 'GOREVDE', started_at = ? WHERE id = ?", (max(at, created_at), tid))
        conn.execute("""UPDATE orders SET status = 'SAHADA_MONTAJ' WHERE status = 'MONTAJ'
                        AND id IN (SELECT order_id FROM field_flights WHERE task_id = ?)""", (tid,))
        db.audit(conn, None, 'Saha görevi kendiliğinden başladı', 'field_task', tid,
                 f'{code}: {order["code"]} sahada montajı bitti, kalibrasyona geçti')


def _pre_final_steps(order):
    names, _ = catalogs.sections(order['product_schema'])
    return set(names) | {catalogs.electronics_step(p) for p in catalogs.electronics_parts(order['product_schema'])}


def complete_final(conn, order, user_id, at_value, staff_ids, checklist):
    """Birleştirme montajı: bölümler ve elektronik montajlar bittikten sonra, en az 2 montaj personeli. Kapaklar
    sonra takıldığı için, kapaklar henüz basılırken (sipariş üretimdeyken) de yapılabilir."""
    if order['status'] in AFTER_ASSEMBLY:
        raise HTTPException(400, 'Uçak montaj aşamasını geçmiş')
    done = {r[0] for r in conn.execute('SELECT step FROM assembly_steps WHERE order_id = ?', (order['id'],))}
    if FINAL_STEP in done:
        raise HTTPException(400, 'Birleştirme montajı zaten tamamlanmış')
    pre = _pre_final_steps(order)
    if not pre <= done:
        raise HTTPException(400, 'Önce üç montaj bölümü ve elektronik montajlar tamamlanmalı')
    checklist = {k: bool((checklist or {}).get(k)) for k in FINAL_CHECKS}
    missing = [FINAL_CHECKS[k] for k, v in checklist.items() if not v]
    if missing:
        raise HTTPException(400, 'Tamamlamak için tüm maddeler onaylanmalı: ' + ' '.join(missing))
    staff = _staff(conn, staff_ids)
    last = _steps_time(conn, order['id'], pre) if order['status'] not in IN_ASSEMBLY else _last_time(conn, order['id'], list(pre))
    at = db.pick_time(at_value, last, 'Birleştirme zamanı', 'montaj')
    record_step(conn, order, FINAL_STEP, user_id, at, staff, checklist)
    return advance_to_calibration(conn, order)


def _steps_time(conn, oid, steps):
    return conn.execute(f"SELECT MAX(at) FROM assembly_steps WHERE order_id = ? AND step IN ({','.join('?' * len(steps))})",
                        (oid, *steps)).fetchone()[0]


def complete_covers(conn, order, user_id, at_value, staff_ids):
    """Kapak montajı: birleştirmeden sonra, tüm kapaklar depoda (onaylı) iken; bitince uçak kalibrasyona geçer."""
    covers = catalogs.cover_parts(order['product_schema'])
    if not covers:
        raise HTTPException(404, 'Bu üründe kapak montajı yok')
    if order['status'] not in IN_ASSEMBLY:
        raise HTTPException(400, 'Kapak montajı için tüm parçalar depoya girmiş olmalı (uçak montaj aşamasında değil)')
    done = {r[0] for r in conn.execute('SELECT step FROM assembly_steps WHERE order_id = ?', (order['id'],))}
    if COVER_STEP in done:
        raise HTTPException(400, 'Kapak montajı zaten tamamlanmış')
    if FINAL_STEP not in done:
        raise HTTPException(400, 'Kapaklar en son takılır: önce birleştirme montajı tamamlanmalı')
    rows = db.rows(conn.execute(f"SELECT id, state, approved_at FROM order_parts WHERE order_id = ? AND part_id IN ({','.join('?' * len(covers))})",
                                (order['id'], *covers)))
    if not all(r['state'] in (WAREHOUSE, ASSEMBLY) and r['approved_at'] for r in rows):
        raise HTTPException(400, 'Tüm kapaklar depoda (onaylı) olmalı')
    staff = _staff(conn, staff_ids, minimum=MIN_COVER_STAFF)
    last = max(t for t in (_steps_time(conn, order['id'], [FINAL_STEP]), *(r['approved_at'] for r in rows)) if t)
    at = db.pick_time(at_value, last, 'Kapak montajı zamanı', 'birleştirme')
    record_step(conn, order, COVER_STEP, user_id, at, staff)
    conn.executemany('UPDATE order_parts SET state = ?, updated_at = ? WHERE id = ?', [(ASSEMBLY, at, r['id']) for r in rows])
    conn.executemany('INSERT INTO part_events (order_part_id, event, user_id, note, at) VALUES (?,?,?,?,?)',
                     [(r['id'], 'MONTAJ_TAMAMLANDI', user_id, 'Kapak montajı', at) for r in rows])
    return advance_to_calibration(conn, order)


def complete_electronics(conn, order, part_id, user_id, at_value, staff_ids):
    """Depodaki elektronik parçaya (elektronik kat ya da K04) elektronik komponentler monte edildi (en az 1 personel)."""
    eparts = catalogs.electronics_parts(order['product_schema'])
    if part_id not in eparts:
        raise HTTPException(404, 'Bu parçaya elektronik montaj yapılmaz')
    op = db.row(conn.execute('SELECT * FROM order_parts WHERE order_id = ? AND part_id = ?', (order['id'], part_id)))
    if not op:
        raise HTTPException(404, 'Parça bulunamadı')
    if order['status'] in AFTER_ASSEMBLY:
        raise HTTPException(400, 'Uçak kalibrasyona geçmiş')
    step = catalogs.electronics_step(part_id)
    if conn.execute('SELECT 1 FROM assembly_steps WHERE order_id = ? AND step = ?', (order['id'], step)).fetchone():
        raise HTTPException(400, f'{eparts[part_id]} elektronik montajı zaten yapılmış')
    if op['state'] != WAREHOUSE or not op['approved_at']:
        raise HTTPException(400, f'{eparts[part_id]} depoda (onaylı) değil')
    staff = _staff(conn, staff_ids, auth.ELECTRONICS, MIN_ELECTRONICS_STAFF)
    at = db.pick_time(at_value, op['approved_at'], 'Montaj zamanı', 'depo onayı')
    record_step(conn, order, step, user_id, at, staff)
    conn.execute('UPDATE order_parts SET state = ?, updated_at = ? WHERE id = ?', (ASSEMBLY, at, op['id']))
    conn.execute('INSERT INTO part_events (order_part_id, event, user_id, at) VALUES (?,?,?,?)',
                 (op['id'], 'ELEKTRONIK_MONTAJ', user_id, at))
    return advance_to_calibration(conn, order)


def complete_calibration(conn, order, user_id, at_value, staff_ids, checklist):
    if order['status'] != 'KALIBRASYON':
        raise HTTPException(400, 'Uçak kalibrasyon aşamasında değil')
    checklist = {k: bool((checklist or {}).get(k)) for k in CALIBRATION_CHECKS}
    missing = [CALIBRATION_CHECKS[k] for k, v in checklist.items() if not v]
    if missing:
        raise HTTPException(400, 'Tamamlamak için tüm maddeler onaylanmalı: ' + ' '.join(missing))
    staff = _staff(conn, staff_ids)
    names, _ = catalogs.sections(order['product_schema'])
    esteps = [catalogs.electronics_step(p) for p in catalogs.electronics_parts(order['product_schema'])]
    at = db.pick_time(at_value, _last_time(conn, order['id'], [*names, *esteps, FINAL_STEP, COVER_STEP]), 'Kalibrasyon zamanı', 'montaj')
    record_step(conn, order, 'KALIBRASYON', user_id, at, staff, checklist)
    conn.execute("UPDATE orders SET status = 'SAHA_ONAY' WHERE id = ?", (order['id'],))


def approve_field_depot(conn, order, user_id, at_value):
    """Depocu kalibrasyonu biten uçağı saha deposuna alır: kuyruk numarası verilir, uçak sahaya gidebilir."""
    if order['status'] != 'SAHA_ONAY':
        raise HTTPException(400, 'Uçak saha deposu onayı beklemiyor')
    at = db.pick_time(at_value, _last_time(conn, order['id'], ['KALIBRASYON']), 'Onay zamanı', 'kalibrasyon')
    record_step(conn, order, 'SAHA_DEPO', user_id, at)
    queue_no = assign_queue_no(conn, order['id'])   # kalibrasyona geçerken atanmıştır; eski kayıtlarda şimdi
    conn.execute('''UPDATE orders SET status = 'TAMAMLANDI', completed_at = ?, completed_by = ? WHERE id = ?''',
                 (at, user_id, order['id']))
    return queue_no


# ---------- Hurda (tek kullanımlık uçak uçtu)

def scrap(conn, order_id, user_id, reason, at=None):
    """Saha deposundaki tek kullanımlık uçağı HURDA yapar (uçtu). Değiştiyse True."""
    o = db.row(conn.execute('''SELECT o.id, o.code, o.status, p.usage_type FROM orders o JOIN products p ON p.id = o.product_id
                               WHERE o.id = ?''', (order_id,)))
    if not o or o['status'] != 'TAMAMLANDI' or o['usage_type'] != 'TEK':
        return False
    conn.execute("UPDATE orders SET status = 'HURDA', scrapped_at = ?, scrap_reason = ? WHERE id = ?",
                 (at or db.now(), reason, order_id))
    db.audit(conn, user_id, 'Uçağı hurdaya ayırdı', 'order', order_id, f'{o["code"]} · {reason}')
    return True


def unscrap(conn, order_id, user_id):
    """Yanlışlıkla hurdaya ayrılan uçağı saha deposuna geri alır."""
    o = db.row(conn.execute('SELECT id, code, status FROM orders WHERE id = ?', (order_id,)))
    if not o or o['status'] != 'HURDA':
        return False
    conn.execute("UPDATE orders SET status = 'TAMAMLANDI', scrapped_at = NULL, scrap_reason = NULL, material_review_at = NULL WHERE id = ?", (order_id,))
    conn.execute("DELETE FROM material_moves WHERE order_id = ? AND source = 'UCUS'", (order_id,))   # malzeme değerlendirmesi geri alınır
    db.audit(conn, user_id, 'Uçağı hurdadan geri aldı', 'order', order_id, o['code'])
    return True


# ---------- Sipariş detayı: aşamalar (Sipariş Yönetimi → sipariş detayı)

def order_timeline(conn, order):
    """Siparişin aşamaları, birbirine bağlı kartlar için: [{key, title, state: done|current|todo, at, by, lines: [..], steps: [..]}].
    Mamul: Sipariş → Üretim → Depo → Montaj → Kalibrasyon → Saha deposu → Saha (→ Hurda).
    Yedek parça: Sipariş → Üretim → Depo → Stok."""
    oid = order['id']
    parts = db.rows(conn.execute('SELECT part_id, state, started_at, finished_at, approved_at FROM order_parts WHERE order_id = ?', (oid,)))
    total = len(parts) or 1
    n = {s: sum(p['state'] == s for p in parts) for s in (WAITING, PRINTING, WAREHOUSE, ASSEMBLY, ERROR)}
    first_start = conn.execute('''SELECT MIN(e.at) FROM part_events e JOIN order_parts op ON op.id = e.order_part_id
                                  WHERE op.order_id = ? AND e.event = 'URETIME_BASLADI' ''', (oid,)).fetchone()[0]
    errors = conn.execute('''SELECT COUNT(*) FROM part_events e JOIN order_parts op ON op.id = e.order_part_id
                             WHERE op.order_id = ? AND e.event = 'HATA' ''', (oid,)).fetchone()[0]
    produced = [p for p in parts if p['state'] in (WAREHOUSE, ASSEMBLY)]
    approved = [p for p in parts if p['approved_at']]
    all_made = len(produced) == len(parts) and parts
    all_approved = len(approved) == len(parts) and parts
    status = order['status']
    spare = bool(order.get('product_stocked'))   # basılı stok parçası: montaj yok
    after = status in AFTER_ASSEMBLY or status in IN_ASSEMBLY

    def stage(key, title, state, at=None, by=None, lines=(), steps=()):
        return {'key': key, 'title': title, 'state': state, 'at': at, 'by': by, 'lines': [x for x in lines if x], 'steps': list(steps)}

    out = [stage('SIPARIS', 'Sipariş verildi', 'done', order['created_at'], order.get('created_by_name'), [
        f'Firma: {order["company_name"]}' if order.get('company_name') else None,
        f'Ürün: {order.get("product_name")} ({order.get("product_serial")})' if order.get('product_serial') else f'Ürün: {order.get("product_name")}',
        f'Planlanan: {order["start_date"] or "—"} – {order["end_date"] or "—"}' if order['start_date'] or order['end_date'] else None,
        f'Açıklama: {order["note"]}' if order['note'] else None])]

    prod_state = 'done' if all_made or after else 'current' if first_start else 'todo'
    out.append(stage('URETIM', 'Üretim', prod_state,
                     max((p['finished_at'] for p in parts if p['finished_at']), default=None) if prod_state == 'done' else first_start, None, [
        f'Başladı: {first_start[:16].replace("T", " ")}' if first_start and prod_state == 'done' else None,
        f'{len(produced)} / {len(parts)} parça üretildi' if parts else None,
        f'{n[PRINTING]} parça yazıcıda' if n[PRINTING] and not after else None,
        f'{n[ERROR]} parça hatalı, yeniden basılacak' if n[ERROR] else None,
        f'Toplam {errors} hata kaydı' if errors else None]))

    depot_state = 'done' if all_approved or after else 'current' if approved or produced else 'todo'
    out.append(stage('DEPO', 'Depo onayı', depot_state, max((p['approved_at'] for p in approved), default=None) if depot_state == 'done' else None, None, [
        f'{len(approved)} / {len(parts)} parça depoya alındı' if parts else None,
        f'{len(produced) - len(approved)} parça onay bekliyor' if len(produced) > len(approved) else None]))

    if spare:
        stock_at = conn.execute("SELECT MIN(created_at) FROM spare_moves WHERE order_id = ? AND qty > 0", (oid,)).fetchone()[0]
        out.append(stage('STOK', 'Stoğa girdi', 'done' if status == 'TAMAMLANDI' else 'todo', stock_at or order['completed_at'], None,
                         [f'{order.get("per_print") or 1} adet {order.get("product_name")} stoğa eklendi' if status == 'TAMAMLANDI' else None]))
        return out

    asm = assembly_info(conn, order)
    steps = asm['steps']
    asm_done = status in AFTER_ASSEMBLY
    rows = [(k, f'{name} montajı') for k, name in asm['sections'].items()]
    rows += [(e['step'], f'Elektronik: {e["name"]}') for e in asm['electronics']]
    rows += [(FINAL_STEP, 'Birleştirme montajı')]
    if asm.get('covers') and (status not in AFTER_ASSEMBLY or asm['covers']['step'] in steps):   # kapak adımı öncesi bitmiş eski siparişler hariç
        rows += [(asm['covers']['step'], 'Kapak montajı')]
    sub = [{'title': t, 'done': k in steps, 'at': steps[k]['at'] if k in steps else None,
            'by': ', '.join(s['full_name'] for s in steps[k]['staff']) or steps[k].get('recorded_by_name') if k in steps else None}
           for k, t in rows]
    done_steps = [s for s in sub if s['done']]
    out.append(stage('MONTAJ', 'Montaj', 'done' if asm_done else 'current' if done_steps or status in IN_ASSEMBLY else 'todo',
                     max((s['at'] for s in done_steps), default=None) if asm_done else None, None,
                     [f'{len(done_steps)} / {len(sub)} montaj adımı tamamlandı',
                      'Sahada montaj' if status == 'SAHADA_MONTAJ' else None], sub))

    cal = steps.get('KALIBRASYON')
    out.append(stage('KALIBRASYON', 'Kalibrasyon', 'done' if cal else 'current' if status == 'KALIBRASYON' else 'todo',
                     cal and cal['at'], cal and (', '.join(s['full_name'] for s in cal['staff']) or cal.get('recorded_by_name')),
                     [f'Kuyruk no: {order["queue_no"]} (metal etiket)' if order['queue_no'] and asm_done else None,
                      'Kontrol listesi tamamlandı' if cal else None]))

    dep = steps.get('SAHA_DEPO')
    out.append(stage('SAHA_DEPO', 'Saha deposu', 'done' if dep or status in CLOSED else 'current' if status == 'SAHA_ONAY' else 'todo',
                     (dep and dep['at']) or order['completed_at'], dep and dep.get('recorded_by_name'),
                     [f'Kuyruk no: {order["queue_no"]}' if order['queue_no'] else None,
                      'Depocu onayı bekliyor' if status == 'SAHA_ONAY' else None]))

    tasks = db.rows(conn.execute(
        '''SELECT t.id, t.code, t.status, t.result, t.started_at, t.finished_at, f.id AS flight_id, l.name AS location
           FROM field_flights f JOIN field_tasks t ON t.id = f.task_id LEFT JOIN field_locations l ON l.id = t.location_id
           WHERE f.order_id = ? ORDER BY t.id''', (oid,)))
    task_text = {'BASLANGIC': 'Başlangıç', 'GOREVDE': 'Görevde', 'GOREV_TAMAMLANDI': 'Görev tamamlandı', 'BASARISIZ': 'Başarısız',
                 'RAPOR_TAMAMLANDI': 'Rapor tamamlandı', 'IPTAL': 'İptal'}
    active = [t for t in tasks if t['status'] in ('BASLANGIC', 'GOREVDE')]
    out.append(stage('SAHA', 'Saha görevi', 'current' if active else 'done' if tasks else 'todo',
                     (tasks[-1]['started_at'] if tasks else None), None,
                     [f'{t["code"]}: {task_text.get(t["status"], t["status"])}' + (f' · {t["location"]}' if t['location'] else '') for t in tasks],
                     [{'title': t['code'], 'task_id': t['id'], 'flight_id': t['flight_id']} for t in tasks]))
    # Uçuş: siparişin uçağının saha görevlerindeki uçuşları (uçuş raporu, notlar, video / resim)
    flights = db.rows(conn.execute(
        '''SELECT f.id, t.code AS task_code, t.status AS task_status, l.status AS log_status,
                  json_extract(l.analysis, '$.summary') AS summary,
                  (SELECT COUNT(*) FROM flight_notes n WHERE n.flight_id = f.id) AS notes,
                  (SELECT COUNT(*) FROM flight_videos v WHERE v.flight_id = f.id) AS media
           FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
           LEFT JOIN flight_logs l ON l.id = (SELECT MAX(id) FROM flight_logs WHERE flight_id = f.id)
           WHERE f.order_id = ? ORDER BY f.id''', (oid,)))
    lines, links, flown_at, flown = [], [], None, False
    for fl in flights:
        sm = json.loads(fl['summary']) if fl['summary'] else {}
        if sm.get('flight_s'):
            flown = True
            flown_at = flown_at or sm.get('takeoff_utc')
            lines.append(f'{fl["task_code"]}: {round(sm["flight_s"] / 60)} dk uçtu · {round((sm.get("distance_m") or 0) / 1000, 1)} km'
                         f' · en yüksek {round(sm.get("alt_max") or 0)} m')
        elif fl['log_status'] == 'ISLENIYOR':
            lines.append(f'{fl["task_code"]}: uçuş raporu işleniyor')
        else:
            lines.append(f'{fl["task_code"]}: uçuş raporu yüklenmedi')
        extra = [f'{fl["notes"]} uçuş notu' if fl['notes'] else None, f'{fl["media"]} video / resim' if fl['media'] else None]
        if any(extra):
            lines.append(' · '.join(x for x in extra if x))
        links.append({'title': fl['task_code'], 'flight_id': fl['id']})
    out.append(stage('UCUS', 'Uçuş', 'done' if flown or status == 'HURDA' else 'current' if active else 'todo', flown_at, None,
                     lines, links))
    if order.get('scrapped_at') or status == 'HURDA':
        out.append(stage('HURDA', 'Hurda (uçtu)', 'done', order.get('scrapped_at'), None, [order.get('scrap_reason')]))
    return out   # birden çok aşama aynı anda sürebilir (ör. depo onayı sürerken bölüm montajı)
