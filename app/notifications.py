"""Kişiye özel bildirim sistemi (üst çubuktaki zil simgesi).

Uyarılardan farkı: her kullanıcı yalnızca kendisini ilgilendiren bildirimleri görür.
Her bildirim türü bir kayıttır: `roles` türü hangi rollerin göreceğini verir (None: rolden bağımsız,
kayıtlar kişiye göre süzülür), `fn(conn, user)` ise o kullanıcı için bekleyen kayıtları döndürür.
Yeni tür eklemek için NOTIFICATIONS'a kayıt eklenir. Bildirimler yalnızca okur; veri değiştirmez.
"""
from datetime import date

from . import auth, catalogs, db


def _result(rows, names, href, detail=None):
    return {'rows': rows, 'names': names, 'href': href, 'detail': detail}


def _field_tasks(conn, where, args=()):
    from .routers.field import _tasks   # döngüsel içe aktarmayı önlemek için burada
    return _tasks(conn, where, args)


# ---------- Depo

def warehouse_pending(conn, user):
    """Üretimi tamamlanıp depoya teslim edilmiş, depo onayı bekleyen parçalar."""
    rows = db.rows(conn.execute(
        '''SELECT op.id, op.part_id, op.delivered_to, o.code AS order_code
           FROM order_parts op JOIN orders o ON o.id = op.order_id
           WHERE op.state = 'DEPO' AND op.approved_at IS NULL ORDER BY op.finished_at'''))
    mine = sum(r['delivered_to'] == user['id'] for r in rows)
    return _result(rows, [f'{r["order_code"]} / {r["part_id"]}' for r in rows], '#/warehouse',
                   f'{mine} tanesi size teslim edildi' if mine else None)


# ---------- Üretim

def production_errors(conn, user):
    """Hata verip yeniden üretime alınmayı bekleyen parçalar."""
    rows = db.rows(conn.execute(
        '''SELECT op.id, op.part_id, o.id AS order_id, o.code AS order_code,
                  (SELECT e.error_code FROM part_events e WHERE e.order_part_id = op.id AND e.event = 'HATA'
                   ORDER BY e.id DESC LIMIT 1) AS error_code
           FROM order_parts op JOIN orders o ON o.id = op.order_id
           WHERE op.state = 'HATA' AND o.status NOT IN ('TAMAMLANDI', 'HURDA') ORDER BY op.finished_at'''))
    orders = {r['order_id'] for r in rows}
    return _result(rows, [f'{r["order_code"]} / {r["part_id"]}' + (f' ({r["error_code"]})' if r['error_code'] else '')
                          for r in rows],
                   f'#/production/{rows[0]["order_id"]}' if len(orders) == 1 else '#/production',
                   'Yeniden üretime alınmalı')


def assembly_waiting(conn, user):
    """Montaj aşamasındaki uçaklar ve tamamlanmamış bölümleri."""
    rows = db.rows(conn.execute(
        """SELECT o.id, o.code, p.schema FROM orders o JOIN products p ON p.id = o.product_id
           WHERE o.status IN ('MONTAJ', 'SAHADA_MONTAJ') ORDER BY o.id"""))
    names = []
    for r in rows:
        sections, _ = catalogs.sections(r['schema'])
        sections = {**sections, **{catalogs.electronics_step(p): f'Elektronik: {p}'
                                   for p in catalogs.electronics_parts(r['schema'])}, 'BIRLESTIRME': 'Birleştirme',
                    **({'KAPAK': 'Kapak'} if catalogs.cover_parts(r['schema']) else {})}
        done = {x[0] for x in conn.execute('SELECT step FROM assembly_steps WHERE order_id = ?', (r['id'],))}
        names.append(f'{r["code"]} ({", ".join(v for k, v in sections.items() if k not in done)})')
    return _result(rows, names, f'#/production/{rows[0]["id"]}' if len(rows) == 1 else '#/production',
                   'Bölüm çerçevesine tıklayıp montajı tamamlayın')


def electronics_waiting(conn, user):
    """Depoya alınmış, elektronik komponentleri henüz monte edilmemiş elektronik parçalar (elektronik kat, K04)."""
    rows = []
    for o in db.rows(conn.execute(
            """SELECT o.id, o.code, p.schema FROM orders o JOIN products p ON p.id = o.product_id
               WHERE o.status NOT IN ('KALIBRASYON', 'SAHA_ONAY', 'TAMAMLANDI', 'HURDA') ORDER BY o.id""")):
        for pid in catalogs.electronics_parts(o['schema']):
            if conn.execute("SELECT 1 FROM order_parts WHERE order_id = ? AND part_id = ? AND state = 'DEPO' "
                            'AND approved_at IS NOT NULL', (o['id'], pid)).fetchone():
                rows.append({**o, 'part': pid})
    ids = {r['id'] for r in rows}
    return _result(rows, [f'{r["code"]} / {r["part"]}' for r in rows],
                   f'#/production/{rows[0]["id"]}' if len(ids) == 1 else '#/production',
                   'ELEKTRONİK görünümünde parçaya tıklayıp komponent montajını onaylayın')


def calibration_waiting(conn, user):
    """Montajı bitmiş, kalibrasyonu bekleyen uçaklar."""
    rows = db.rows(conn.execute("SELECT id, code FROM orders WHERE status = 'KALIBRASYON' ORDER BY id"))
    return _result(rows, [r['code'] for r in rows],
                   f'#/production/{rows[0]["id"]}' if len(rows) == 1 else '#/production',
                   'Uçağa tıklayıp kalibrasyon kontrol listesini doldurun')


def field_depot_pending(conn, user):
    """Kalibrasyonu bitmiş, saha deposuna alınmak için depocu onayı bekleyen uçaklar."""
    rows = db.rows(conn.execute("SELECT id, code FROM orders WHERE status = 'SAHA_ONAY' ORDER BY id"))
    return _result(rows, [r['code'] for r in rows], '#/warehouse/aircraft', 'Onaylanınca uçak sahaya gidebilir')


def orders_overdue(conn, user):
    """Bitiş tarihi geçtiği hâlde montajı tamamlanmamış siparişler."""
    rows = db.rows(conn.execute(
        "SELECT id, code, end_date FROM orders WHERE status NOT IN ('TAMAMLANDI', 'HURDA') AND end_date IS NOT NULL "
        "AND end_date < ? ORDER BY end_date", (date.today().isoformat(),)))
    return _result(rows, [f'{r["code"]} (bitiş {r["end_date"]})' for r in rows], '#/orders')


# ---------- Yazıcı

def printers_down(conn, user):
    """Hata bildiren ya da ağdan ulaşılamayan yazıcılar."""
    rows = db.rows(conn.execute(
        "SELECT id, name, live_state FROM printers WHERE live_state IN ('HATA', 'CEVRIMDISI') ORDER BY name"))
    errors = sum(r['live_state'] == 'HATA' for r in rows)
    offline = len(rows) - errors
    parts = [f'{errors} hata veriyor' if errors else '', f'{offline} çevrimdışı' if offline else '']
    return _result(rows, [r['name'] for r in rows], '#/printers', ', '.join(p for p in parts if p))


# ---------- Saha

def _missing_reports(tasks):
    rows = [(t, f) for t in tasks for f in t['flights'] if f['log_status'] != 'TAMAM']
    failed = sum(f['log_status'] == 'HATA' for _, f in rows)
    names = [f'{t["code"]} / {f["queue_no"] or f["order_code"]}' for t, f in rows]
    ids = {t['id'] for t, _ in rows}
    href = f'#/field/task/{next(iter(ids))}' if len(ids) == 1 else '#/field'
    return _result(rows, names, href, f'{failed} logun çözümlemesi hatalı' if failed else 'Uçuş logu yüklenmeli')


def field_reports_lead(conn, user):
    """Saha sorumlusu olduğu, bitmiş görevlerde raporu (analizi tamamlanmış logu) olmayan uçuşlar."""
    return _missing_reports(_field_tasks(conn, "t.lead_id = ? AND t.status IN ('GOREV_TAMAMLANDI', 'BASARISIZ')",
                                         (user['id'],)))


def field_reports_pilot(conn, user):
    """Pilot olarak görevli olduğu bitmiş görevlerde raporu olmayan uçuşlar (saha sorumlusu bildirimiyle çakışmaz)."""
    return _missing_reports(_field_tasks(
        conn, "t.status IN ('GOREV_TAMAMLANDI', 'BASARISIZ') AND COALESCE(t.lead_id, 0) != ? "
              "AND (t.pilot_id = ? OR t.id IN (SELECT task_id FROM field_task_staff WHERE user_id = ?))",
        (user['id'], user['id'], user['id'])))


def field_road_missing(conn, user):
    """Şoförü olduğu görevlerde eksik yol bilgisi. Görevin şoförü: araç girilmemişse ve (görev bittiyse) görev yeri;
    her aracın şoförü: kendi aracının başlangıç km'si, görev bittiyse bitiş km'si."""
    tasks = _field_tasks(conn, "t.status NOT IN ('BASLANGIC', 'IPTAL') AND (t.driver_id = ? OR "
                               "t.id IN (SELECT task_id FROM field_task_vehicles WHERE driver_id = ?))", (user['id'], user['id']))
    rows = []
    for t in tasks:
        finished = t['status'] != 'GOREVDE'
        missing = []
        if t['driver_id'] == user['id']:
            if not t['vehicles']:
                missing.append('araç')
            if finished and not t['location_id']:
                missing.append('görev yeri')
        for v in t['vehicles']:
            if v['driver_id'] != user['id'] and t['driver_id'] != user['id']:
                continue
            need = ['başlangıç km'] + (['bitiş km'] if finished else [])
            gaps = [k for k in need if v['start_km' if k == 'başlangıç km' else 'end_km'] is None]
            if gaps:
                missing.append(f'{v["plate"]} {", ".join(gaps)}')
        if missing:
            rows.append((t, missing))
    ids = [t['id'] for t, _ in rows]
    return _result(rows, [f'{t["code"]}: {"; ".join(m)}' for t, m in rows],
                   f'#/field/task/{ids[0]}' if len(ids) == 1 else '#/field', "Yol Yönetimi'nden girilmeli")


def field_assigned(conn, user):
    """Kullanıcının görevli (personel, şoför ya da saha sorumlusu) olduğu, henüz başlamamış görevler."""
    tasks = _field_tasks(
        conn, "t.status = 'BASLANGIC' AND (t.driver_id = ? OR t.lead_id = ? OR t.pilot_id = ? OR "
              "t.id IN (SELECT task_id FROM field_task_staff WHERE user_id = ?) OR "
              "t.id IN (SELECT task_id FROM field_task_vehicles WHERE driver_id = ?)) AND COALESCE(t.created_by, 0) != ?",
        (user['id'],) * 6)
    return _result(tasks, [f'{t["code"]}' + (f' – {t["location_name"]}' if t['location_name'] else '') for t in tasks],
                   f'#/field/task/{tasks[0]["id"]}' if len(tasks) == 1 else '#/field', 'Görev henüz başlamadı')


def signatures_pending(conn, user):
    """Kullanıcının imzasını bekleyen evraklar (herkes; tıklayınca evrak ve İmzala / Reddet / Vazgeç)."""
    rows = db.rows(conn.execute(
        '''SELECT s.id, d.title, u.full_name AS requested_by_name FROM document_signatures s
           JOIN documents d ON d.id = s.document_id LEFT JOIN users u ON u.id = s.requested_by
           WHERE s.signer_id = ? AND s.status = 'BEKLIYOR' ORDER BY s.requested_at''', (user['id'],)))
    return _result(rows, [f'{r["title"]} ({r["requested_by_name"] or "—"})' for r in rows],
                   f'#/sign/{rows[0]["id"]}' if len(rows) == 1 else '#/sign', 'Evrakı görüp imzalayın ya da reddedin')


def spares_low(conn, user):
    """Stoğu bir mamulün (CAYMAZ) montajına yetmeyen yedek parçalar."""
    from . import spares
    rows = [r for r in spares.summary(conn) if r['per_aircraft'] and r['stock'] < r['per_aircraft']]
    return _result(rows, [f'{r["code"]}: stok {r["stock"]}, gereken {r["per_aircraft"]}' for r in rows], '#/stock',
                   'Yedek parça siparişi açın (Sipariş Yönetimi)')


def calendar_due(conn, user):
    """Takvim: bugünkü randevular ve zamanı gelmiş, tamamlanmamış hatırlatmalar (oluşturan ya da katılımcı)."""
    from .routers.crm import due_for
    rows = due_for(conn, user['id'])
    names = [f'{r["starts_at"][11:16]} {r["title"]}' + (f' ({r["subject_name"]})' if r['subject_name'] else '') for r in rows]
    return _result(rows, names, rows[0]['href'] if rows else '#/companies', 'Randevu ve hatırlatmalarınız')


# ---------- Sekreterya

def guest_visit(conn, user):
    """Görüşülecek kişi olarak ilişkilendirildiğiniz, bugün gelmiş ve henüz çıkmamış misafirler."""
    rows = db.rows(conn.execute(
        '''SELECT g.id, g.code, g.purpose, g.arrived_at,
                  (SELECT group_concat(full_name, ', ') FROM guest_visit_people WHERE visit_id = g.id) AS names
           FROM guest_visits g JOIN guest_visit_hosts h ON h.visit_id = g.id
           WHERE h.user_id = ? AND g.left_at IS NULL AND substr(g.arrived_at, 1, 10) = ? ORDER BY g.arrived_at''',
        (user['id'], date.today().isoformat())))
    return _result(rows, [f'{r["arrived_at"][11:16]} {r["names"] or r["code"]}' + (f' ({r["purpose"]})' if r['purpose'] else '')
                          for r in rows], '#/my-guests', 'Sekreterya misafirinizi kaydetti')


def cargo_waiting(conn, user):
    """Size gelen, teslim almadığınız kargolar."""
    rows = db.rows(conn.execute(
        'SELECT id, carrier, description, created_at FROM cargo WHERE recipient_id = ? AND delivered_at IS NULL ORDER BY created_at',
        (user['id'],)))
    return _result(rows, [r['carrier'] or r['description'] or 'Kargo' for r in rows], '#/my-cargo', 'Sekreteryadan teslim alın')


def call_waiting(conn, user):
    """Sizi arayan, henüz tamamlamadığınız (geri dönmediğiniz) telefonlar."""
    rows = db.rows(conn.execute(
        'SELECT id, caller_name, caller_company, created_at FROM phone_calls WHERE target_id = ? AND done_at IS NULL ORDER BY created_at',
        (user['id'],)))
    return _result(rows, [r['caller_name'] + (f' ({r["caller_company"]})' if r['caller_company'] else '') for r in rows], '#/my-calls',
                   'Geri dönüp tamamlayın')


def announcements_unread(conn, user):
    """Okunmamış duyurular (açınca okundu sayılır)."""
    from .routers.announcements import unread_for
    rows = unread_for(conn, user['id'])
    return _result(rows, [r['title'] for r in rows], '#/announcements', 'Okumak için açın')


NOTIFICATIONS = [
    {'key': 'announcements', 'roles': None, 'fn': announcements_unread, 'title': 'Yeni duyuru'},
    {'key': 'guest-visit', 'roles': None, 'fn': guest_visit, 'title': 'Misafiriniz geldi'},
    {'key': 'cargo-waiting', 'roles': None, 'fn': cargo_waiting, 'title': 'Kargonuz var'},
    {'key': 'call-waiting', 'roles': None, 'fn': call_waiting, 'title': 'Sizi arayanlar var'},
    {'key': 'calendar-due', 'roles': None, 'fn': calendar_due, 'title': 'Takvim: bugün ve zamanı gelen'},
    {'key': 'spares-low', 'roles': [auth.PRODUCTION_MANAGER, auth.WAREHOUSE_MANAGER], 'fn': spares_low,
     'title': 'Stoğu yetmeyen yedek parça'},
    {'key': 'signature-pending', 'roles': None, 'fn': signatures_pending, 'title': 'İmzanızı bekleyen evrak'},
    {'key': 'warehouse-pending', 'roles': [auth.WAREHOUSE_MANAGER], 'fn': warehouse_pending,
     'title': 'Depo onayı bekleyen parça'},
    {'key': 'production-error', 'roles': [auth.PRODUCTION_MANAGER, auth.PRODUCTION_LEAD], 'fn': production_errors,
     'title': 'Hata veren parça'},
    {'key': 'field-depot-pending', 'roles': [auth.WAREHOUSE_MANAGER], 'fn': field_depot_pending,
     'title': 'Saha deposu onayı bekleyen uçak'},
    {'key': 'assembly-waiting', 'roles': [auth.PRODUCTION_MANAGER, auth.PRODUCTION_LEAD, auth.ASSEMBLER],
     'fn': assembly_waiting, 'title': 'Montajı bekleyen uçak'},
    {'key': 'electronics-waiting', 'roles': [auth.ELECTRONICS], 'fn': electronics_waiting,
     'title': 'Elektronik montajı bekleyen kat'},
    {'key': 'calibration-waiting', 'roles': [auth.PRODUCTION_MANAGER, auth.PRODUCTION_LEAD, auth.ASSEMBLER],
     'fn': calibration_waiting, 'title': 'Kalibrasyonu bekleyen uçak'},
    {'key': 'orders-overdue', 'roles': [auth.PRODUCTION_MANAGER], 'fn': orders_overdue,
     'title': 'Bitiş tarihi geçmiş sipariş'},
    {'key': 'printers-down', 'roles': [auth.PRINTER_MAINTAINER], 'fn': printers_down,
     'title': 'Bakım gerektiren yazıcı'},
    {'key': 'field-report-lead', 'roles': [auth.FIELD_LEAD], 'fn': field_reports_lead,
     'title': 'Raporu eksik uçuş'},
    {'key': 'field-report-pilot', 'roles': [auth.PILOT], 'fn': field_reports_pilot,
     'title': 'Raporu eksik uçuş'},
    {'key': 'field-road', 'roles': [auth.DRIVER], 'fn': field_road_missing,
     'title': 'Yol bilgisi girilmemiş görev'},
    {'key': 'field-assigned', 'roles': None, 'fn': field_assigned,
     'title': 'Size atanan saha görevi'},
]


def for_user(conn, user):
    out = []
    for n in NOTIFICATIONS:
        if n['roles'] is not None and not set(n['roles']) & set(user['roles']):
            continue
        r = n['fn'](conn, user)
        if r['rows']:
            out.append({'key': n['key'], 'title': n['title'], 'href': r['href'], 'count': len(r['rows']),
                        'names': r['names'][:5], 'detail': r['detail']})
    return out
