"""Kişisel pano (ana sayfa): herkesin kendine göre düzenlediği küçük kutucuklar (widget).

Her kutucuk: anahtar, başlık, açıklama, gerektirdiği modül (None: herkes), varsayılan genişlik (1–3) ve veri fonksiyonu.
Kullanıcı yalnızca girebildiği modüllerin kutucuklarını ekleyebilir. Düzen user_prefs['dashboard'] içinde saklanır
(arayüz yazar); varsayılan düzen kullanıcının modüllerine göre kurulur.
"""
from collections import Counter
from datetime import date, datetime, timedelta

from . import db

WIDGETS = []


def widget(key, title, desc, module=None, size=1, default=False):
    def deco(fn):
        WIDGETS.append({'key': key, 'title': title, 'desc': desc, 'module': module, 'size': size, 'default': default, 'fn': fn})
        return fn
    return deco


# Yeni kullanıcının panosu (sırasıyla); yetkisi olmayan kutucuk atlanır. Değer: sıra (1'den başlar), yoksa 0.
DEFAULT_LAYOUT = ['clock', 'calendar', 'announcements', 'kpi_production', 'chart_production']


def available(user):
    mods = set(user['modules'])
    order = {k: i + 1 for i, k in enumerate(DEFAULT_LAYOUT)}
    return [{**w, 'default': order.get(w['key'], 0)} for w in WIDGETS if w['module'] is None or w['module'] in mods]


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


@widget('calendar', 'Takvimim', 'Bugünkü ve yaklaşan randevular, hatırlatmalar', size=1)
def w_calendar(conn, user):
    from .routers.crm import _event_rows, _mine
    where, args = _mine(user['id'])
    rows = _event_rows(conn, f"{where} AND (e.starts_at >= ? OR (e.kind = 'HATIRLATMA' AND e.done_at IS NULL))", (*args, today()), limit=8)
    return {'items': [{'title': r['title'], 'at': r['starts_at'], 'kind': r['kind'], 'done': bool(r['done_at'])} for r in rows]}


@widget('notifications', 'Bildirimlerim', 'Sizi ilgilendiren bekleyen işler', size=1)
def w_notifications(conn, user):
    from . import notifications
    return {'items': notifications.for_user(conn, user)}


@widget('alerts', 'Uyarılar', 'Sistem uyarıları (yazıcı, üretim)', size=1)
def w_alerts(conn, user):
    from . import alerts
    if set(user['modules']) <= {'security', 'announcements'}:
        return {'items': []}
    return {'items': alerts.summary(conn)}


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
    st = Counter(r[0] or 'CEVRIMDISI' for r in conn.execute('SELECT live_state FROM printers'))
    return {'states': st, 'total': sum(st.values())}


@widget('kpi_warehouse', 'Depo', 'Onay bekleyen parçalar ve saha deposu onayı bekleyen uçaklar', 'warehouse')
def w_kpi_warehouse(conn, user):
    return {'kpis': [
        {'label': 'Onay bekleyen parça', 'value': count(conn, "SELECT COUNT(*) FROM order_parts WHERE state = 'DEPO' AND approved_at IS NULL"), 'href': '#/warehouse', 'tone': 'alert'},
        {'label': 'Saha deposu onayı', 'value': count(conn, "SELECT COUNT(*) FROM orders WHERE status = 'SAHA_ONAY'")},
        {'label': 'Saha deposundaki uçak', 'value': count(conn, "SELECT COUNT(*) FROM orders o JOIN products p ON p.id = o.product_id WHERE o.status = 'TAMAMLANDI' AND p.type = 'MAMUL'"), 'tone': 'ok'},
    ]}


@widget('kpi_stock', 'Yedek parça stoğu', 'Stoğun kaç uçağa yettiği ve kısıtlayan parça', 'stock')
def w_kpi_stock(conn, user):
    from . import spares
    rows = [r for r in spares.summary(conn) if r['per_aircraft']]
    lim = min(rows, key=lambda r: r['enough_for'] if r['enough_for'] is not None else 1e9) if rows else None
    return {'kpis': [{'label': 'Stok yeter (uçak)', 'value': lim['enough_for'] if lim else '—', 'tone': 'alert' if lim and not lim['enough_for'] else 'ok', 'href': '#/stock'},
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
