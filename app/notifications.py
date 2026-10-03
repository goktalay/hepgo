"""Kişiye özel bildirim sistemi (üst çubuktaki zil simgesi).

Uyarılardan farkı: her kullanıcı yalnızca kendisini ilgilendiren bildirimleri görür.
Her bildirim türü bir kayıttır: `roles` türü hangi rollerin göreceğini verir (None: rolden bağımsız,
kayıtlar kişiye göre süzülür), `fn(conn, user)` ise o kullanıcı için bekleyen kayıtları döndürür.
Yeni tür eklemek için NOTIFICATIONS'a kayıt eklenir. Bildirimler yalnızca okur; veri değiştirmez.
"""
import json
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
    return _result(rows, [f'{r["order_code"]} / {r["part_id"]}' for r in rows], '#/mrp/approvals',
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
    return _result(rows, [r['code'] for r in rows], '#/mrp/approvals/aircraft', 'Onaylanınca uçak sahaya gidebilir')


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
        "SELECT id, name, live_state FROM printers WHERE live_state IN ('HATA', 'CEVRIMDISI')"))
    from . import printer_layout
    rows.sort(key=lambda r: printer_layout.name_key(r['name']))
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
    return _result(rows, [f'{r["code"]}: stok {r["stock"]}, gereken {r["per_aircraft"]}' for r in rows], '#/mrp/semi',
                   'Yedek parça siparişi açın (Sipariş Yönetimi)')


def calendar_due(conn, user):
    """Takvim: bugünkü randevular ve zamanı gelmiş, tamamlanmamış hatırlatmalar (oluşturan ya da katılımcı)."""
    from .routers.crm import due_for
    rows = due_for(conn, user['id'])
    names = [f'{r["starts_at"][11:16]} {r["title"]}' + (f' ({r["subject_name"]})' if r['subject_name'] else '') for r in rows]
    return _result(rows, names, rows[0]['href'] if rows else '#/companies', 'Randevu ve hatırlatmalarınız')


# ---------- Sekreterya

def guest_visit(conn, user):
    """Görüşülecek kişi olarak ilişkilendirildiğiniz, bugün gelmiş, henüz çıkmamış ve Misafirlerim'de görmediğiniz misafirler."""
    rows = db.rows(conn.execute(
        '''SELECT g.id, g.code, g.purpose, g.arrived_at,
                  (SELECT group_concat(full_name, ', ') FROM guest_visit_people WHERE visit_id = g.id) AS names
           FROM guest_visits g JOIN guest_visit_hosts h ON h.visit_id = g.id
           WHERE h.user_id = ? AND h.seen_at IS NULL AND g.left_at IS NULL AND substr(g.arrived_at, 1, 10) = ? ORDER BY g.arrived_at''',
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


def meeting_invites(conn, user):
    """Yanıt bekleyen toplantı davetleri."""
    from .routers.meetings import pending_invites
    rows = pending_invites(conn, user['id'])
    return _result(rows, [f'{r["title"]} ({r["starts_at"][8:10]}.{r["starts_at"][5:7]} {r["starts_at"][11:16]})' for r in rows],
                   f'#/meetings/{rows[0]["id"]}' if len(rows) == 1 else '#/meetings', 'Katılım durumunuzu bildirin')


def meeting_soon(conn, user):
    """Hatırlatma zamanı gelen toplantılar (toplantıdan önce seçilen süre kadar)."""
    from .routers.meetings import soon
    rows = soon(conn, user['id'])
    return _result(rows, [f'{r["starts_at"][11:16]} · {r["title"]}' + (f' · {r["location"]}' if r['location'] else '') for r in rows],
                   f'#/meetings/{rows[0]["id"]}' if len(rows) == 1 else '#/meetings', 'Toplantı yaklaşıyor')


def mail_unread(conn, user):
    """Gmail gelen kutusundaki okunmamış e-postalar (hesap bağlıysa)."""
    from .routers.mail import unread_count
    n = unread_count(conn, user)
    rows = [{'id': i} for i in range(n)]
    return _result(rows, [f'{n} okunmamış e-posta'] if n else [], '#/mail', 'Gelen kutusunu açın')


def announcements_unread(conn, user):
    """Okunmamış duyurular (açınca okundu sayılır)."""
    from .routers.announcements import unread_for
    rows = unread_for(conn, user['id'])
    return _result(rows, [r['title'] for r in rows], '#/announcements', 'Okumak için açın')


def hr_leave_pending(conn, user):
    """İnsan Kaynakları: onay bekleyen izin talepleri."""
    from .routers.hr import pending_leaves
    rows = pending_leaves(conn)
    return _result(rows, [f'{r["employee_name"]} · {r["req_start"][8:10]}.{r["req_start"][5:7]}–{r["req_end"][8:10]}.{r["req_end"][5:7]}'
                          for r in rows], '#/hr/leaves', 'Tarihleri kontrol edip onaylayın ya da reddedin')


def leave_decided(conn, user):
    """İzin talebim sonuçlandı (İzinlerim açılınca görüldü sayılır)."""
    from .routers.hr import decided_unseen
    rows = decided_unseen(conn, user['id'])
    return _result(rows, [f'{"Onaylandı" if r["status"] == "ONAYLANDI" else "Reddedildi"} · '
                          f'{(r["start_date"] or r["req_start"])[8:10]}.{(r["start_date"] or r["req_start"])[5:7]}' for r in rows],
                   '#/my-leaves', 'İzin talebinizin sonucunu görün')


def material_review(conn, user):
    """Hurdaya ayrılan uçağın içindeki malzemeler değerlendirilmedi (hurda / sağlam)."""
    from .routers.mrp import pending_reviews
    rows = pending_reviews(conn)
    if not rows:
        return _result([], [], '#/field/flights')
    fid = conn.execute('SELECT id FROM field_flights WHERE order_id = ? ORDER BY id DESC LIMIT 1', (rows[0]['id'],)).fetchone()
    return _result(rows, [r['queue_no'] or r['code'] for r in rows], f'#/field/flight/{fid[0]}' if fid and len(rows) == 1 else '#/field/flights',
                   'Uçağın içindeki malzemeler hurda mı, sağlam mı?')


def purchase_approval(conn, user):
    """Sistem Yöneticisi: onay bekleyen satın alma talepleri."""
    from .routers.purchasing import pending_approvals
    rows = pending_approvals(conn)
    return _result(rows, [f'{r["code"]} {r["title"]}' for r in rows],
                   f'#/purchasing/requests/{rows[0]["id"]}' if len(rows) == 1 else '#/purchasing/requests', 'Kalemleri inceleyip onaylayın ya da reddedin')


def purchase_decided(conn, user):
    """Açtığım satın alma talebi onaylandı / reddedildi (talep açılınca görüldü sayılır)."""
    from .routers.purchasing import decided_unseen
    rows = decided_unseen(conn, user['id'])
    return _result(rows, [f'{r["code"]} {"onaylandı" if r["status"] == "ONAYLANDI" else "reddedildi"}' for r in rows],
                   f'#/purchasing/requests/{rows[0]["id"]}' if len(rows) == 1 else '#/purchasing/requests', 'Talebinizin sonucunu görün')


def direct_part_pending(conn, user):
    """Sistem Yöneticisi: doğrudan depoya ekleme (basılmış) onayı bekleyen parçalar."""
    rows = db.rows(conn.execute(
        """SELECT d.id, o.id AS order_id, o.code, op.part_id, pr.name AS printer_name
           FROM direct_part_requests d JOIN order_parts op ON op.id = d.order_part_id JOIN orders o ON o.id = op.order_id
           LEFT JOIN printers pr ON pr.id = d.printer_id WHERE d.status = 'BEKLIYOR' ORDER BY d.requested_at"""))
    return _result(rows, [f'{r["code"]} / {r["part_id"]} → {r["printer_name"] or "?"}' for r in rows],
                   f'#/production/{rows[0]["order_id"]}' if rows else '#/production',
                   'Parçayı basılmış kabul edip depo onayına gönderin ya da reddedin')


def radio_invites(conn, user):
    rows = db.rows(conn.execute(
        '''SELECT c.id, c.name, u.full_name FROM radio_members m JOIN radio_channels c ON c.id = m.channel_id
           LEFT JOIN users u ON u.id = m.invited_by WHERE m.user_id = ? AND m.status = 'DAVET' ORDER BY m.invited_at DESC''', (user['id'],)))
    return _result(rows, [f'{r["full_name"] or "Bir kullanıcı"}: {r["name"]}' for r in rows], '#/settings/radio', 'Onaylamak için açın')


def ai_change_pending(conn, user):
    rows = db.rows(conn.execute(
        '''SELECT r.id, r.summary, u.full_name FROM ai_change_requests r JOIN users u ON u.id = r.user_id
           WHERE r.status = 'BEKLIYOR' ORDER BY r.id DESC'''))
    return _result(rows, [f'{r["full_name"]}: {r["summary"]}' for r in rows], '#/sysconfig/ai-changes', 'Onaylamak için açın')


def ai_change_decided(conn, user):
    rows = db.rows(conn.execute(
        '''SELECT id, summary, status FROM ai_change_requests
           WHERE user_id = ? AND status != 'BEKLIYOR' AND seen_at IS NULL ORDER BY id DESC''', (user['id'],)))
    lbl = {'ONAYLANDI': 'onaylandı ve uygulandı', 'RED': 'reddedildi', 'HATA': 'onaylandı ama uygulanamadı'}
    return _result(rows, [f'{r["summary"]} — {lbl.get(r["status"], r["status"])}' for r in rows], '#/', None)


def tickets_waiting(conn, user):
    """Merkez: firmalardan gelen, yanıt bekleyen destek talepleri (yalnızca merkez modunda, talep yetkilisine)."""
    from . import config
    if not config.FEDERATION_CENTRAL or 'tickets' not in user.get('modules', []):
        return _result([], [], '#/tickets')
    rows = db.rows(conn.execute(
        "SELECT id, code, company_name, subject FROM tickets WHERE support_unread > 0 AND status NOT IN ('kapali') ORDER BY updated_at DESC"))
    return _result(rows, [f'{r["company_name"] or ""}: {r["subject"]}' for r in rows], '#/tickets', 'Yanıtlamak için açın')


def live_now(conn, user):
    """Şu an canlı yayın yapanlar (kendi yayını hariç) — yayın bitene kadar kalır; tıklayan yayına katılır."""
    from . import feed
    if not feed.can_see_home(user.get('modules', [])):
        return _result([], [], '#/home')
    rows = db.rows(conn.execute('''SELECT s.id, s.title, u.full_name FROM live_streams s JOIN users u ON u.id = s.user_id
                                   WHERE s.status = 'live' AND s.user_id != ? ORDER BY s.started_at DESC''', (user['id'],)))
    names = [f"🔴 {r['full_name']}" + (f": {r['title']}" if r['title'] else ' canlı yayında') for r in rows]
    return _result(rows, names, f"#/live/{rows[0]['id']}" if rows else '#/home', 'Katılmak için dokunun')


def feed_new(conn, user):
    """Şirketten Haberler: görmediğiniz yeni paylaşımlar (tıklayınca ana ekran; ana ekranda görünce kalkar)."""
    from . import feed
    if not feed.can_see_home(user.get('modules', [])):   # yalnız-Güvenlik / rolsüz: ana ekranı göremez → temizlenemeyen bildirim olmasın
        return _result([], [], '#/home')
    rows = feed.unseen_posts(conn, user['id'])
    return _result(rows, [f'{r["author_name"]}: {feed.snippet(r["text"], r["media"])}' for r in rows], '#/home', 'Ana ekranda görmek için açın')


NOTIFICATIONS = [
    {'key': 'tickets-waiting', 'roles': None, 'fn': tickets_waiting, 'title': 'Yanıt bekleyen destek talebi'},
    {'key': 'radio-invite', 'roles': None, 'fn': radio_invites, 'title': 'Telsiz kanalı daveti'},
    {'key': 'ai-change-pending', 'roles': [auth.ADMIN], 'fn': ai_change_pending, 'title': 'Yapay zeka değişiklik talebi onay bekliyor'},
    {'key': 'ai-change-decided', 'roles': None, 'fn': ai_change_decided, 'title': 'Yapay zeka değişiklik talebin sonuçlandı'},
    {'key': 'direct-part-pending', 'roles': [auth.ADMIN], 'fn': direct_part_pending, 'title': 'Doğrudan depo ekleme onayı bekliyor'},
    {'key': 'purchase-approval', 'roles': [auth.ADMIN], 'fn': purchase_approval, 'title': 'Onay bekleyen satın alma talebi'},
    {'key': 'purchase-decided', 'roles': [auth.PURCHASING, auth.ADMIN], 'fn': purchase_decided, 'title': 'Satın alma talebiniz sonuçlandı'},
    {'key': 'material-review', 'roles': [auth.FIELD_LEAD, auth.WAREHOUSE_MANAGER, auth.MRP_LEAD], 'fn': material_review,
     'title': 'Hurda uçağın malzemeleri değerlendirilmedi'},
    {'key': 'hr-leave-pending', 'roles': [auth.HR], 'fn': hr_leave_pending, 'title': 'Onay bekleyen izin talebi'},
    {'key': 'leave-decided', 'roles': None, 'fn': leave_decided, 'title': 'İzin talebiniz sonuçlandı'},
    {'key': 'announcements', 'roles': None, 'fn': announcements_unread, 'title': 'Yeni duyuru'},
    {'key': 'guest-visit', 'roles': None, 'fn': guest_visit, 'title': 'Misafiriniz geldi'},
    {'key': 'cargo-waiting', 'roles': None, 'fn': cargo_waiting, 'title': 'Kargonuz var'},
    {'key': 'call-waiting', 'roles': None, 'fn': call_waiting, 'title': 'Sizi arayanlar var'},
    {'key': 'meeting-soon', 'roles': None, 'fn': meeting_soon, 'title': 'Toplantı yaklaşıyor'},
    {'key': 'meeting-invite', 'roles': None, 'fn': meeting_invites, 'title': 'Toplantı daveti'},
    {'key': 'mail-unread', 'roles': None, 'fn': mail_unread, 'title': 'Okunmamış e-posta'},
    {'key': 'calendar-due', 'roles': None, 'fn': calendar_due, 'title': 'Takvim: bugün ve zamanı gelen'},
    {'key': 'spares-low', 'roles': [auth.PRODUCTION_MANAGER, auth.WAREHOUSE_MANAGER, auth.MRP_LEAD], 'fn': spares_low,
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
    # Sonda: dakikalık push taramasında önemli bildirimlerin önüne geçmesin. push=False: telefon bildirimini paylaşım
    # anında routers/feed._announce atar; tarama aynı artış için ikinci kez atmasın (çift bildirim olmasın).
    {'key': 'feed-new', 'roles': None, 'fn': feed_new, 'title': 'Şirketten Haberler: yeni paylaşım', 'push': False},
    # Telefon bildirimini yayın başlarken routers/live atar (aynı etiketle bitince günceller); tarama ikinci kez atmasın
    {'key': 'live-now', 'roles': None, 'fn': live_now, 'title': 'Canlı yayın', 'push': False},
]


def _applies(n, user):
    return n['roles'] is None or bool(set(n['roles']) & set(user.get('real_roles', user['roles'])))


def _muted(user):
    """Kullanıcının kapattığı bildirim türleri (Ayarlar → Bildirimler → Bildirim türleri)."""
    try:
        p = json.loads(user['prefs']) if user.get('prefs') else {}
        return set(p.get('settings', {}).get('muteNotif') or [])
    except Exception:
        return set()


def docs_missing(conn, user):
    """Kendi eksik özlük evrakı (kapatılamaz, kırmızı): Evraklarım'a yönlendirir."""
    from .routers.hr import my_docs
    d = my_docs(conn, user['id'])
    if not d or not d['missing']:
        return None
    return {'key': 'docs-missing', 'title': f'{len(d["missing"])} adet eksik evrakınız var', 'href': '#/my-documents',
            'count': len(d['missing']), 'names': [x[1] for x in d['missing']][:5], 'critical': True,
            'detail': f'Son gün: {d["deadline"][8:10]}.{d["deadline"][5:7]}.{d["deadline"][:4]} {d["deadline"][11:16]} — yüklemek için dokunun'}


def for_user(conn, user):
    out = []
    dm = docs_missing(conn, user)
    if dm:
        out.append(dm)
    muted = _muted(user)
    for n in NOTIFICATIONS:
        if not _applies(n, user) or n['key'] in muted:
            continue
        r = n['fn'](conn, user)
        if r['rows']:
            out.append({'key': n['key'], 'title': n['title'], 'href': r['href'], 'count': len(r['rows']),
                        'names': r['names'][:5], 'detail': r['detail']})
    return out


def types_for(user):
    """Kullanıcının rollerine uyan bildirim türleri + o an kapalı olup olmadığı (ayar ekranı için)."""
    muted = _muted(user)
    return [{'key': n['key'], 'title': n['title'], 'on': n['key'] not in muted}
            for n in NOTIFICATIONS if _applies(n, user)]
