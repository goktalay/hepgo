"""Kişisel pano (ana sayfa): herkesin kendine göre düzenlediği küçük kutucuklar (widget).

Her kutucuk: anahtar, başlık, açıklama, gerektirdiği modül (None: herkes), varsayılan genişlik (1–3) ve veri fonksiyonu.
Kullanıcı yalnızca girebildiği modüllerin kutucuklarını ekleyebilir. Düzen user_prefs['dashboard'] içinde saklanır
(arayüz yazar); varsayılan düzen kullanıcının modüllerine göre kurulur.
"""
from collections import Counter
from datetime import date, datetime, timedelta

from . import db

WIDGETS = []

# Kutucuk Ekle penceresinde KONUYA GÖRE gruplama (sıralı, açılır/kapanır). group verilmezse anahtara göre eşlenir, yoksa 'Genel'.
GROUP_ORDER = ['Kişisel', 'Genel', 'Üretim', 'Depo & Stok', 'Saha', 'Ofis & Güvenlik', 'Sistem']
WIDGET_GROUP = {
    'calendar': 'Kişisel', 'notifications': 'Kişisel', 'my_cargo': 'Kişisel', 'my_guests': 'Kişisel', 'my_calls': 'Kişisel',
    'birthdays': 'Kişisel', 'announcements': 'Kişisel',
    'modules': 'Genel', 'clock': 'Genel', 'weather': 'Genel', 'company_news': 'Genel',
    'alerts': 'Üretim', 'kpi_production': 'Üretim', 'chart_production': 'Üretim', 'forecast': 'Üretim',
    'recent_orders': 'Üretim', 'kpi_printers': 'Üretim',
    'kpi_warehouse': 'Depo & Stok', 'kpi_stock': 'Depo & Stok',
    'kpi_field': 'Saha',
    'kpi_security': 'Ofis & Güvenlik', 'kpi_secretariat': 'Ofis & Güvenlik', 'kpi_documents': 'Ofis & Güvenlik',
    'kpi_admin': 'Sistem',
}


def widget(key, title, desc, module=None, size=1, default=False, modules=None, fixed=False, group=None):
    def deco(fn):
        WIDGETS.append({'key': key, 'title': title, 'desc': desc, 'module': module, 'modules': modules, 'size': size,
                        'default': default, 'fixed': fixed, 'group': group or WIDGET_GROUP.get(key, 'Genel'), 'fn': fn})
        return fn
    return deco


# Yeni kullanıcının panosu (sırasıyla); yetkisi olmayan kutucuk atlanır. Değer: sıra (1'den başlar), yoksa 0.
DEFAULT_LAYOUT = ['company_news', 'clock', 'calendar', 'birthdays', 'announcements', 'kpi_production', 'chart_production']


def available(user):
    mods = set(user['modules'])
    order = {k: i + 1 for i, k in enumerate(DEFAULT_LAYOUT)}
    return [{**w, 'default': order.get(w['key'], 0)} for w in WIDGETS
            if (w['module'] is None or w['module'] in mods) and (not w.get('modules') or set(w['modules']) & mods)]


def data(conn, user, keys):
    by = {w['key']: w for w in available(user)}
    out = {}
    for k in keys:
        if k in by:
            try:
                out[k] = by[k]['fn'](conn, user)
            except Exception as e:   # tek kutucuğun hatası panoyu bozmasın
                out[k] = {'error': str(e)}
    return out


count = lambda conn, sql, args=(): conn.execute(sql, args).fetchone()[0]
today = lambda: date.today().isoformat()


# ---------- herkes

@widget('modules', 'Modüller', 'Girebildiğiniz modüllere kısayollar', size=3)
def w_modules(conn, user):
    return {}


@widget('company_news', 'Şirketten Haberler', 'Günün olayları ve paylaşımlar (akış + harita)', size=1, default=True, fixed=True)
def w_company_news(conn, user):
    return {}   # içerik istemcide /api/feed'den gelir (akış + harita + paylaşım)


@widget('birthdays', 'Doğum Günleri', 'Yaklaşan personel doğum günleri', size=1)
def w_birthdays(conn, user):
    from .routers.hr import upcoming_birthdays
    return {'items': upcoming_birthdays(conn, days=45, limit=12)}


@widget('calendar', 'Takvimim', 'Bugünkü ve yaklaşan randevular, hatırlatmalar ve toplantılar', size=1)
def w_calendar(conn, user):
    from .routers.crm import _event_rows, _mine
    where, args = _mine(user['id'])
    rows = _event_rows(conn, f"{where} AND (e.starts_at >= ? OR (e.kind = 'HATIRLATMA' AND e.done_at IS NULL))", (*args, today()), limit=8)
    items = [{'title': r['title'], 'at': r['starts_at'], 'kind': r['kind'], 'done': bool(r['done_at']), 'href': '#/calendar'} for r in rows]
    # Yaklaşan (ve süren) toplantılar: düzenlediğim ya da davet edildiğim, katılmayacağım demediklerim
    since = (datetime.now() - timedelta(minutes=30)).isoformat(timespec='seconds')   # başlamayan toplantı 30 dk sonra düşer
    for m in db.rows(conn.execute(
            '''SELECT m.id, m.title, m.starts_at, m.ends_at, m.location, m.started_at, m.ended_at,
                      (SELECT status FROM team_meeting_invites WHERE meeting_id = m.id AND user_id = ?) AS my_status
               FROM team_meetings m WHERE m.cancelled_at IS NULL AND m.ended_at IS NULL AND (m.started_at IS NOT NULL OR m.starts_at >= ?)
                 AND (m.created_by = ? OR m.id IN (SELECT meeting_id FROM team_meeting_invites WHERE user_id = ? AND status != 'KATILMIYOR'))
               ORDER BY m.starts_at LIMIT 8''', (user['id'], since, user['id'], user['id']))):
        items.append({'title': m['title'], 'at': m['starts_at'], 'kind': 'TOPLANTI', 'location': m['location'],
                      'live': bool(m['started_at']), 'pending': m['my_status'] == 'BEKLIYOR', 'href': f'#/meetings/{m["id"]}'})
    items.sort(key=lambda i: i['at'] or '')
    return {'items': items[:16]}   # liste kutucukta kaydırılır


@widget('notifications', 'Bildirimlerim', 'Sizi ilgilendiren bekleyen işler', size=1)
def w_notifications(conn, user):
    from . import notifications
    return {'items': notifications.for_user(conn, user)}


@widget('alerts', 'Uyarılar', 'Sistem uyarıları (yazıcı, üretim)', size=1, modules=('production', 'printers'))
def w_alerts(conn, user):
    from . import alerts
    return {'items': alerts.summary(conn, user)}


@widget('my_cargo', 'Kargolarım', 'Sekreteryada bekleyen kargolarınız', size=1)
def w_my_cargo(conn, user):
    return {'items': db.rows(conn.execute('SELECT id, carrier, description, created_at FROM cargo WHERE recipient_id = ? AND delivered_at IS NULL ORDER BY created_at',
                                          (user['id'],)))}


@widget('my_guests', 'Misafirlerim', 'Bugün size gelen misafirler', size=1)
def w_my_guests(conn, user):
    rows = db.rows(conn.execute(
        '''SELECT g.id, g.code, g.purpose, g.arrived_at, g.left_at,
                  (SELECT group_concat(full_name, ', ') FROM guest_visit_people WHERE visit_id = g.id) AS names
           FROM guest_visits g JOIN guest_visit_hosts h ON h.visit_id = g.id WHERE h.user_id = ? AND substr(g.arrived_at, 1, 10) = ?
           ORDER BY g.arrived_at DESC''', (user['id'], today())))
    return {'items': rows}


@widget('my_calls', 'Aramalarım', 'Sizi arayan, geri dönmediğiniz telefonlar', size=1)
def w_my_calls(conn, user):
    return {'items': db.rows(conn.execute(
        '''SELECT id, caller_name, caller_company, caller_phone, subject, result, callback, created_at FROM phone_calls
           WHERE target_id = ? AND done_at IS NULL ORDER BY created_at DESC LIMIT 10''', (user['id'],)))}


@widget('announcements', 'Duyurular', 'Okunmamış duyurular (yönetimden)', size=1)
def w_announcements(conn, user):
    from .routers.announcements import unread_for
    return {'items': unread_for(conn, user['id'])}


@widget('email', 'E-posta', 'Bağlı hesaplarınızdaki okunmamış e-postaların tümü', size=1, group='Kişisel')
def w_email(conn, user):
    """Kişisel › Mail hesaplarındaki okunmamış iletiler (önbellekten, hızlı). Yalnız kullanıcının kendi hesapları."""
    import json as _json
    boxes = [r[0] for r in conn.execute('SELECT id FROM mail_boxes WHERE user_id = ?', (user['id'],))]
    if not boxes:
        return {'boxes': 0, 'count': 0, 'items': []}
    q = ','.join('?' * len(boxes))
    rows = conn.execute(f"SELECT box_id, uid, summary FROM mail_cache WHERE folder = 'inbox' AND seen = 0 AND box_id IN ({q}) "
                        'ORDER BY date DESC LIMIT 100', boxes).fetchall()
    items = []
    for box_id, uid, summary in rows:
        d = _json.loads(summary)
        fr = d.get('from') or {}
        items.append({'box_id': box_id, 'uid': uid, 'folder': 'inbox',
                      'from': (fr.get('name') or fr.get('email') or '').strip(), 'subject': d.get('subject'), 'date': d.get('date')})
    return {'boxes': len(boxes), 'count': len(items), 'items': items}


@widget('active_users', 'Kullanıcılar', 'Çevrimiçi kullanıcılar; tıklayınca hızlı mesajlaşma', size=1, group='Genel')
def w_active_users(conn, user):
    from datetime import datetime as _dt
    from .routers.admin import ONLINE_WINDOW
    cut = (_dt.now() - ONLINE_WINDOW).isoformat(timespec='seconds')
    admin = 'Sistem Yöneticisi' in (user.get('roles') or [])
    rows = db.rows(conn.execute(
        '''SELECT id, full_name, photo FROM users u WHERE active = 1 AND deleted_at IS NULL AND id != ? AND last_seen >= ?
             AND EXISTS (SELECT 1 FROM sessions s WHERE s.user_id = u.id AND s.expires_at > ?)
             AND (? OR IFNULL(json_extract(u.prefs, '$.settings.privacy.hide_online'), 0) = 0)
           ORDER BY full_name''',
        (user['id'], cut, db.now(), admin)))
    return {'items': rows, 'count': len(rows)}


@widget('world_clock', 'Dünya Saati', 'Eklediğiniz şehirlerin saatlerini yan yana gösterir', size=1, group='Genel')
def w_world_clock(conn, user):
    return {}   # şehirler istemcide (kutucuk ayarı): ad + zaman dilimi


@widget('alarm', 'Alarm', 'Saat ve haftanın günlerine alarm; zamanı gelince sesle uyarır', size=1, group='Kişisel')
def w_alarm(conn, user):
    return {}   # alarmlar cihazda (localStorage)


@widget('notes', 'Notlar', 'Yapışkan notlarınız; ekrana iğneleyebilirsiniz', size=1, group='Kişisel')
def w_notes(conn, user):
    rows = db.rows(conn.execute('SELECT id, body, color, pinned FROM personal_notes WHERE user_id = ? ORDER BY sort, id DESC LIMIT 40', (user['id'],)))
    return {'count': len(rows)}


@widget('quick_directory', 'Hızlı Rehber', 'Sık ulaştığınız kişiler; mesaj ve e-posta kısayolu', size=1, group='Kişisel')
def w_quick_directory(conn, user):
    return {}   # kişiler istemcide (kutucuk ayarı)


@widget('my_messages', 'Mesajlarım', 'Size gelen son mesajlar', size=1, group='Kişisel')
def w_my_messages(conn, user):
    """Sistemdeki (uygulama içi) sohbette her kişiyle son ileti; okunmamışlar önce."""
    me = user['id']
    rows = db.rows(conn.execute(
        """WITH last AS (SELECT CASE WHEN from_id = ? THEN to_id ELSE from_id END AS peer, MAX(id) AS mid
                         FROM chat_messages WHERE from_id = ? OR to_id = ? GROUP BY peer)
           SELECT u.id AS peer_id, u.full_name, u.photo, m.body, m.file_kind, m.from_id, m.created_at,
                  (SELECT COUNT(*) FROM chat_messages x WHERE x.from_id = u.id AND x.to_id = ? AND x.read_at IS NULL) AS unread
           FROM last JOIN chat_messages m ON m.id = last.mid JOIN users u ON u.id = last.peer
           WHERE u.active = 1 AND u.deleted_at IS NULL
           ORDER BY unread > 0 DESC, m.id DESC LIMIT 8""", (me, me, me, me)))
    kinds = {'image': '📷 Fotoğraf', 'video': '🎬 Video', 'audio': '🎤 Ses', 'file': '📎 Dosya'}
    items = []
    for r in rows:
        prev = r['body'] or (kinds.get(r['file_kind'], '📎 Dosya') if r['file_kind'] else '')
        items.append({'peer_id': r['peer_id'], 'name': r['full_name'], 'photo': r['photo'],
                      'preview': (('Siz: ' if r['from_id'] == me else '') + (prev or '')).strip()[:90],
                      'at': r['created_at'], 'unread': r['unread']})
    return {'items': items, 'unread': sum(i['unread'] for i in items)}


@widget('my_meetings', 'Toplantılarım', 'Aktif ve bekleyen görüntülü toplantılarınız', size=1, group='Kişisel')
def w_my_meetings(conn, user):
    """Görüntülü toplantılar (meet): devam eden (DEVAM) ve bekleyen (PLANLANDI); tıklayınca toplantıya girilir."""
    rows = db.rows(conn.execute(
        """SELECT m.id, m.title, m.status, m.scheduled_at, hu.full_name AS host_name,
                  (SELECT COUNT(*) FROM online_meeting_participants p WHERE p.meeting_id = m.id) AS participants
           FROM online_meetings m LEFT JOIN users hu ON hu.id = m.host_id
           WHERE m.status != 'BITTI' AND (m.host_id = ? OR m.id IN
                 (SELECT meeting_id FROM online_meeting_participants WHERE user_id = ?))
           ORDER BY (m.status = 'DEVAM') DESC, COALESCE(m.scheduled_at, m.created_at) LIMIT 10""",
        (user['id'], user['id'])))
    return {'items': rows}


@widget('weather', 'Hava durumu', 'Bulunduğunuz konuma ya da seçtiğiniz şehre göre hava durumu', size=1)
def w_weather(conn, user):
    return {}


@widget('clock', 'Saat', 'Dijital ya da analog saat, tarih', size=1)
def w_clock(conn, user):
    return {}


# ---------- modüllere göre özetler

@widget('kpi_production', 'Üretim özeti', 'Açık sipariş, yazıcıdaki parça, bugün biten ve hata', 'production')
def w_kpi_production(conn, user):
    d = today()
    return {'kpis': [
        {'label': 'Açık sipariş', 'value': count(conn, "SELECT COUNT(*) FROM orders WHERE status NOT IN ('TAMAMLANDI','HURDA')"), 'href': '#/production'},
        {'label': 'Yazıcıdaki parça', 'value': count(conn, "SELECT COUNT(*) FROM order_parts WHERE state = 'URETIMDE'")},
        {'label': 'Bugün teslim', 'value': count(conn, "SELECT COUNT(*) FROM part_events WHERE event = 'URETIM_TAMAMLANDI' AND at >= ?", (d,)), 'tone': 'ok'},
        {'label': 'Bugün hata', 'value': count(conn, "SELECT COUNT(*) FROM part_events WHERE event = 'HATA' AND at >= ?", (d,)), 'tone': 'alert'},
    ]}


@widget('chart_production', 'Son 14 gün üretim', 'Günlük depoya teslim ve hata grafiği', 'production', size=2)
def w_chart_production(conn, user):
    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    done = Counter(r[0] for r in conn.execute("SELECT substr(at,1,10) FROM part_events WHERE event = 'URETIM_TAMAMLANDI' AND at >= ?", (days[0],)))
    err = Counter(r[0] for r in conn.execute("SELECT substr(at,1,10) FROM part_events WHERE event = 'HATA' AND at >= ?", (days[0],)))
    return {'labels': [f'{d[8:10]}.{d[5:7]}' for d in days], 'done': [done.get(d, 0) for d in days], 'err': [err.get(d, 0) for d in days]}


@widget('forecast', 'Teslim tahmini', 'Son 7 günün hızıyla açık siparişlerin tahmini bitişi', 'production')
def w_forecast(conn, user):
    from .reports import REPORTS
    fn = next(r['fn'] for r in REPORTS if r['key'] == 'kapasite-tahmin')
    d = fn(conn, {'from': (date.today() - timedelta(days=6)).isoformat(), 'to': today()})
    return {'kpis': d['kpis'][:3], 'rows': d['tables'][0]['rows'][:4]}


@widget('recent_orders', 'Son siparişler', 'Son açılan siparişler ve ilerlemeleri', 'orders', size=2)
def w_recent_orders(conn, user):
    from .production import order_summaries
    return {'items': [{k: o[k] for k in ('id', 'code', 'status', 'progress', 'product_name', 'company_name', 'company_logo', 'queue_no')}
                      for o in order_summaries(conn)[:6]]}


@widget('kpi_printers', 'Yazıcılar', 'Yazdıran, boştaki, sorunlu ve çevrimdışı yazıcılar', 'printers')
def w_kpi_printers(conn, user):
    st = Counter(('BAKIM' if r[1] else (r[0] or 'CEVRIMDISI')) for r in conn.execute('SELECT live_state, maint_since FROM printers'))
    return {'states': st, 'total': sum(st.values())}


@widget('kpi_warehouse', 'Depo', 'Onay bekleyen parçalar ve saha deposu onayı bekleyen uçaklar', 'warehouse')
def w_kpi_warehouse(conn, user):
    return {'kpis': [
        {'label': 'Onay bekleyen parça', 'value': count(conn, "SELECT COUNT(*) FROM order_parts WHERE state = 'DEPO' AND approved_at IS NULL"), 'href': '#/mrp/approvals', 'tone': 'alert'},
        {'label': 'Saha deposu onayı', 'value': count(conn, "SELECT COUNT(*) FROM orders WHERE status = 'SAHA_ONAY'")},
        {'label': 'Saha deposundaki uçak', 'value': count(conn, "SELECT COUNT(*) FROM orders o JOIN products p ON p.id = o.product_id WHERE o.status = 'TAMAMLANDI' AND p.type = 'MAMUL'"), 'tone': 'ok'},
    ]}


@widget('kpi_stock', 'Yedek parça stoğu', 'Stoğun kaç uçağa yettiği ve kısıtlayan parça', 'stock')
def w_kpi_stock(conn, user):
    from . import spares
    rows = [r for r in spares.summary(conn) if r['per_aircraft']]
    lim = min(rows, key=lambda r: r['enough_for'] if r['enough_for'] is not None else 1e9) if rows else None
    return {'kpis': [{'label': 'Stok yeter (uçak)', 'value': lim['enough_for'] if lim else '—', 'tone': 'alert' if lim and not lim['enough_for'] else 'ok', 'href': '#/mrp/semi'},
                     {'label': 'Kısıtlayan parça', 'value': lim['code'] if lim else '—'}]}


@widget('kpi_field', 'Saha', 'Aktif görevler, uçuşa hazır uçaklar ve bu ayki uçuşlar', 'field')
def w_kpi_field(conn, user):
    month = date.today().isoformat()[:7]
    return {'kpis': [
        {'label': 'Görevde', 'value': count(conn, "SELECT COUNT(*) FROM field_tasks WHERE status = 'GOREVDE'"), 'href': '#/field', 'tone': 'ok'},
        {'label': 'Başlangıçta', 'value': count(conn, "SELECT COUNT(*) FROM field_tasks WHERE status = 'BASLANGIC'")},
        {'label': 'Bu ay uçuş raporu', 'value': count(conn, "SELECT COUNT(*) FROM flight_logs WHERE status = 'TAMAM' AND substr(uploaded_at,1,7) = ?", (month,))},
    ]}


@widget('kpi_security', 'Güvenlik', 'İçerideki araç, bugün giren araç, tanımsız yüzler', 'security')
def w_kpi_security(conn, user):
    return {'kpis': [
        {'label': 'İçerideki araç', 'value': count(conn, 'SELECT COUNT(*) FROM vehicle_visits WHERE exited_at IS NULL'), 'href': '#/security', 'tone': 'ok'},
        {'label': 'Bugün giren', 'value': count(conn, 'SELECT COUNT(*) FROM vehicle_visits WHERE entered_at >= ?', (today(),))},
        {'label': 'Tanımsız kişi grubu', 'value': count(conn, 'SELECT COUNT(*) FROM face_groups WHERE person_id IS NULL AND user_id IS NULL'),
         'href': '#/security/faces', 'tone': 'alert'},
    ]}


@widget('kpi_secretariat', 'Sekreterya', 'İçerideki misafir ve bekleyen kargolar', 'secretariat')
def w_kpi_secretariat(conn, user):
    return {'kpis': [
        {'label': 'İçerideki misafir grubu', 'value': count(conn, 'SELECT COUNT(*) FROM guest_visits WHERE left_at IS NULL'), 'href': '#/secretariat', 'tone': 'ok'},
        {'label': 'İçerideki kişi', 'value': count(conn, 'SELECT COUNT(*) FROM guest_visit_people gp JOIN guest_visits g ON g.id = gp.visit_id WHERE g.left_at IS NULL')},
        {'label': 'Bekleyen kargo', 'value': count(conn, 'SELECT COUNT(*) FROM cargo WHERE delivered_at IS NULL'), 'href': '#/secretariat/cargo', 'tone': 'alert'},
    ]}


@widget('kpi_documents', 'Evrak', 'Bu ay yüklenen evrak ve bekleyen imzalar', 'documents')
def w_kpi_documents(conn, user):
    month = date.today().isoformat()[:7]
    return {'kpis': [
        {'label': 'Bu ay evrak', 'value': count(conn, 'SELECT COUNT(*) FROM documents WHERE substr(uploaded_at,1,7) = ?', (month,)), 'href': '#/documents'},
        {'label': 'Bekleyen imza', 'value': count(conn, "SELECT COUNT(*) FROM document_signatures WHERE status = 'BEKLIYOR'"), 'tone': 'alert'},
    ]}


@widget('kpi_admin', 'Sistem', 'Çevrimiçi kullanıcı, bugün giriş, başarısız giriş, yedek yaşı', 'admin')
def w_kpi_admin(conn, user):
    from .routers.admin import _backups
    now = datetime.now()
    b = _backups()
    return {'kpis': [
        {'label': 'Çevrimiçi', 'value': count(conn, 'SELECT COUNT(*) FROM users WHERE last_seen >= ?', ((now - timedelta(minutes=2)).isoformat(timespec='seconds'),)), 'href': '#/admin', 'tone': 'ok'},
        {'label': 'Başarısız giriş (24 sa)', 'value': count(conn, 'SELECT COUNT(*) FROM login_logs WHERE success = 0 AND at >= ?', ((now - timedelta(hours=24)).isoformat(timespec='seconds'),)), 'tone': 'alert'},
        {'label': 'Son yedek', 'value': f'{round(b["nightly_age_h"])} sa önce' if b['nightly_age_h'] is not None else 'yok', 'tone': '' if b['ok'] else 'alert'},
    ]}
