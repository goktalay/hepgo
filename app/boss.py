"""Patron ekranı — üst yönetimin tek bakışta görmesi gerekenler: nakit, alacak / borç, kârlılık (muhasebe), nakit projeksiyonu,
satış, üretim, insan kaynakları, operasyon ve dikkat gerektiren konular. Her kartın ayrıntısı detail(key) ile gelir.

Patron diğer modüllere yetkili olmayabilir; bu yüzden ayrıntılar da yalnızca okunur özetler olarak buradan verilir.
Bölümler birbirinden bağımsız hesaplanır: bir veri kaynağı yoksa / hata verirse o bölüm boş gelir, ekran yine açılır."""
import logging
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from . import db
from . import finance_reports as fr

log = logging.getLogger(__name__)
_CACHE = {}
TTL = 120


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:   # bölüm hesaplanamadıysa ekranın geri kalanı açılsın
        log.exception('patron ekranı bölümü: %s', getattr(fn, '__name__', fn))
        return None


def _one(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return (r[0] if r else 0) or 0


def _month_add(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _cari_balances(conn):
    return db.rows(conn.execute('''SELECT a.id, a.name, a.company_id, ROUND(COALESCE(a.opening, 0) + COALESCE(SUM(CASE WHEN t.direction = 'in' THEN t.amount ELSE -t.amount END), 0), 2) AS bal,
                                   MAX(t.date) AS last_date
                                   FROM fin_accounts a LEFT JOIN fin_txns t ON t.account_id = a.id WHERE a.kind = 'cari' AND a.active = 1 GROUP BY a.id'''))


# ---------------- Bölümler ----------------
def finance(conn):
    today = date.today()
    caris = _cari_balances(conn)
    rec = sum(c['bal'] for c in caris if c['bal'] > 0)
    pay = -sum(c['bal'] for c in caris if c['bal'] < 0)
    o_rec, o_pay = fr.open_items(conn)
    t = today.isoformat()
    month = t[:7]
    m_in = _one(conn, "SELECT SUM(t.amount) FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id WHERE a.kind IN ('kasa','banka') AND t.direction = 'in' AND substr(t.date, 1, 7) = ?", (month,))
    m_out = _one(conn, "SELECT SUM(t.amount) FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id WHERE a.kind IN ('kasa','banka') AND t.direction = 'out' AND substr(t.date, 1, 7) = ?", (month,))
    return {'cash': fr._cash_now(conn), 'receivable': round(rec, 2), 'payable': round(pay, 2),
            'overdue_rec': round(sum(i['amount'] for i in o_rec if i['due'][:10] < t), 2),
            'overdue_pay': round(sum(i['amount'] for i in o_pay if i['due'][:10] < t), 2),
            'overdue_rec_n': len({i['account_id'] for i in o_rec if i['due'][:10] < t}),
            'month_in': round(m_in, 2), 'month_out': round(m_out, 2),
            'aging_rec': fr.aging(o_rec, today)}


def profit(conn):
    """Muhasebeden yılbaşından bugüne kârlılık + geçen yılın aynı dönemi + son 12 ay ciro / net kâr."""
    if not _one(conn, 'SELECT COUNT(*) FROM fin_ledger'):
        return None
    today = date.today()
    ytd = fr.statements(conn, f'{today.year}-01-01', today.isoformat())
    try:
        ly_end = today.replace(year=today.year - 1)
    except ValueError:   # 29 Şubat
        ly_end = today.replace(year=today.year - 1, day=28)
    ly = fr.statements(conn, f'{today.year - 1}-01-01', ly_end.isoformat())
    months = []
    start = _month_add(today.replace(day=1), -11)
    for i in range(12):
        a = _month_add(start, i)
        b = _month_add(start, i + 1) - timedelta(days=1)
        k = fr.statements(conn, a.isoformat(), min(b, today).isoformat())['kpi']
        months.append({'month': a.isoformat()[:7], 'sales': k['net_satis'], 'net': k['net_kar'], 'gross': k['brut_kar']})
    return {'ytd': ytd['kpi'], 'ly': ly['kpi'], 'months': months, 'income': ytd['income']}


def cash_projection(conn):
    s = conn.execute("SELECT v FROM app_kv WHERE k = 'fin.settings'").fetchone()
    import json
    try:
        st = json.loads(s[0]) if s else {}
    except ValueError:
        st = {}
    cf = fr.cashflow(conn, 12, int(st.get('payday') or 0) or None, st.get('salaries', True))
    low = min(cf['weeks'], key=lambda w: w['balance']) if cf['weeks'] else None
    return {'weeks': cf['weeks'], 'cash': cf['cash'], 'end': cf['end_balance'], 'low': low}


def sales(conn):
    today = date.today()
    y0, m0 = f'{today.year}-01-01', today.isoformat()[:7]
    ly0, ly1 = f'{today.year - 1}-01-01', today.replace(year=today.year - 1, day=min(today.day, 28)).isoformat()
    q = '''SELECT SUM(t.amount) FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id
           WHERE a.kind = 'cari' AND t.direction = 'in' AND t.category = 'Fatura' AND t.date BETWEEN ? AND ?'''
    ytd = _one(conn, q, (y0, today.isoformat()))
    ly = _one(conn, q, (ly0, ly1))
    month = _one(conn, q, (m0 + '-01', today.isoformat()))
    top = db.rows(conn.execute('''SELECT a.company_id, a.name, ROUND(SUM(t.amount), 2) AS amount, COUNT(*) AS n FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id
                                  WHERE a.kind = 'cari' AND t.direction = 'in' AND t.category = 'Fatura' AND t.date >= ? GROUP BY a.id ORDER BY amount DESC LIMIT 6''', (y0,)))
    return {'ytd': round(ytd, 2), 'ly': round(ly, 2), 'month': round(month, 2), 'top': top}


def production(conn):
    today = date.today().isoformat()
    m0 = today[:7]
    st = Counter(r[0] or 'CEVRIMDISI' for r in conn.execute('SELECT live_state FROM printers'))
    total = sum(st.values())
    done_m = _one(conn, "SELECT COUNT(*) FROM part_events WHERE event = 'URETIM_TAMAMLANDI' AND substr(at, 1, 7) = ?", (m0,))
    err_m = _one(conn, "SELECT COUNT(*) FROM part_events WHERE event = 'HATA' AND substr(at, 1, 7) = ?", (m0,))
    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    done = Counter(r[0] for r in conn.execute("SELECT substr(at, 1, 10) FROM part_events WHERE event = 'URETIM_TAMAMLANDI' AND at >= ?", (days[0],)))
    return {'open_orders': _one(conn, "SELECT COUNT(*) FROM orders WHERE status NOT IN ('TAMAMLANDI','HURDA','IPTAL')"),
            'in_print': _one(conn, "SELECT COUNT(*) FROM order_parts WHERE state = 'URETIMDE'"),
            'done_today': _one(conn, "SELECT COUNT(*) FROM part_events WHERE event = 'URETIM_TAMAMLANDI' AND at >= ?", (today,)),
            'done_month': done_m, 'err_month': err_m, 'err_rate': round(err_m / (done_m + err_m) * 100, 1) if done_m + err_m else None,
            'printers': {'total': total, 'printing': st.get('YAZDIRIYOR', 0), 'error': st.get('HATA', 0), 'offline': st.get('CEVRIMDISI', 0),
                         'paused': st.get('DURAKLADI', 0), 'idle': st.get('HAZIR', 0) + st.get('TAMAMLANDI', 0)},
            'trend': [{'day': d, 'done': done.get(d, 0)} for d in days]}


def people(conn):
    from . import auth
    y0 = f'{date.today().year}-01-01'
    absent = auth.absent_map(conn)
    active_users = {r[0] for r in conn.execute("SELECT user_id FROM employees WHERE status = 'AKTIF' AND user_id IS NOT NULL")}
    away = [a for uid, a in absent.items() if uid in active_users]
    return {'active': _one(conn, "SELECT COUNT(*) FROM employees WHERE status = 'AKTIF'"),
            'on_leave': sum(1 for a in away if a['kind'] == 'IZIN'), 'on_report': sum(1 for a in away if a['kind'] == 'RAPOR'),
            'payroll': round(_one(conn, "SELECT SUM(salary) FROM employees WHERE status = 'AKTIF'"), 2),
            'hired': _one(conn, "SELECT COUNT(*) FROM employees WHERE start_date >= ?", (y0,)),
            'left': _one(conn, "SELECT COUNT(*) FROM employees WHERE status = 'AYRILDI' AND end_date >= ?", (y0,)),
            'applications': _one(conn, "SELECT COUNT(*) FROM employees WHERE status = 'BASVURU'"),
            'pending_leaves': _one(conn, "SELECT COUNT(*) FROM leave_requests WHERE status = 'BEKLIYOR'")}


def operations(conn):
    today = date.today()
    t, m0 = today.isoformat(), today.isoformat()[:7]
    out = {'purchase_pending': _one(conn, "SELECT COUNT(*) FROM purchase_requests WHERE status = 'ONAY_BEKLIYOR'"),
           'parts_pending': _one(conn, "SELECT COUNT(*) FROM order_parts WHERE state = 'DEPO' AND approved_at IS NULL"),
           'field_active': _one(conn, "SELECT COUNT(*) FROM field_tasks WHERE status IN ('BASLANGIC','GOREVDE')")}
    out['vehicles'] = _one(conn, 'SELECT COUNT(*) FROM field_vehicles WHERE active = 1')
    out['fleet_month'] = round(_one(conn, 'SELECT SUM(amount) FROM vehicle_expenses WHERE substr(date, 1, 7) = ?', (m0,)), 2)
    out['fleet_year'] = round(_one(conn, 'SELECT SUM(amount) FROM vehicle_expenses WHERE date >= ?', (f'{today.year}-01-01',)), 2)
    lim = (today + timedelta(days=60)).isoformat()
    out['certs_valid'] = _one(conn, "SELECT COUNT(*) FROM certs WHERE status = 'gecerli'")
    out['certs_expiring'] = _one(conn, "SELECT COUNT(*) FROM certs WHERE status IN ('gecerli','askida') AND expiry_date IS NOT NULL AND expiry_date != '' AND expiry_date <= ?", (lim,))
    out['audits_upcoming'] = _one(conn, "SELECT COUNT(*) FROM cert_audits WHERE result = 'planlandi' AND date BETWEEN ? AND ?", (t, (today + timedelta(days=30)).isoformat()))
    return out


def attention(conn, s):
    """Patronun bakması gerekenler (önem sırasıyla)."""
    items = []
    f, cp, pr, op = s.get('finance') or {}, s.get('cash') or {}, s.get('production') or {}, s.get('operations') or {}
    if cp.get('low') and cp['low']['balance'] < 0:
        items.append({'level': 'red', 'key': 'cash', 'title': 'Nakit projeksiyonu eksiye düşüyor',
                      'text': f"{cp['low']['start'][8:10]}.{cp['low']['start'][5:7]} haftasında öngörülen nakit {cp['low']['balance']:,.0f} ₺".replace(',', '.')})
    if f.get('overdue_rec'):
        items.append({'level': 'red' if f['overdue_rec'] > (f.get('receivable') or 1) * 0.25 else 'yellow', 'key': 'overdue',
                      'title': 'Vadesi geçmiş alacak', 'text': f"{f['overdue_rec']:,.0f} ₺ · {f['overdue_rec_n']} cari".replace(',', '.')})
    if f.get('overdue_pay'):
        items.append({'level': 'yellow', 'key': 'payables', 'title': 'Vadesi geçmiş borç', 'text': f"{f['overdue_pay']:,.0f} ₺".replace(',', '.')})
    if (pr.get('printers') or {}).get('error'):
        items.append({'level': 'red', 'key': 'production', 'title': 'Hatadaki yazıcı', 'text': f"{pr['printers']['error']} yazıcı hata durumunda"})
    if pr.get('err_rate') and pr['err_rate'] >= 10:
        items.append({'level': 'yellow', 'key': 'production', 'title': 'Üretim hata oranı yüksek', 'text': f"Bu ay %{pr['err_rate']}"})
    if op.get('certs_expiring'):
        items.append({'level': 'yellow', 'key': 'operations', 'title': 'Süresi dolmak üzere sertifika', 'text': f"{op['certs_expiring']} sertifika (60 gün)"})
    if op.get('audits_upcoming'):
        items.append({'level': 'blue', 'key': 'operations', 'title': 'Yaklaşan denetim', 'text': f"{op['audits_upcoming']} denetim (30 gün)"})
    if op.get('purchase_pending'):
        items.append({'level': 'blue', 'key': 'operations', 'title': 'Onay bekleyen satın alma talebi', 'text': f"{op['purchase_pending']} talep"})
    if op.get('parts_pending'):
        items.append({'level': 'blue', 'key': 'production', 'title': 'Depo onayı bekleyen parça', 'text': f"{op['parts_pending']} parça"})
    try:
        from .notifications import fleet_due
        fd = fleet_due(conn, {'modules': ['fleet']})
        if fd['rows']:
            items.append({'level': 'yellow', 'key': 'operations', 'title': 'Araç: muayene / sigorta / bakım', 'text': ' · '.join(fd['names'][:2]) + (' …' if len(fd['names']) > 2 else '')})
    except Exception:
        pass
    order = {'red': 0, 'yellow': 1, 'blue': 2}
    return sorted(items, key=lambda i: order[i['level']])


def summary(conn, fresh=False):
    c = _CACHE.get('summary')
    if c and not fresh and time.time() - c[0] < TTL:
        return c[1]
    s = {'finance': _safe(finance, conn), 'profit': _safe(profit, conn), 'cash': _safe(cash_projection, conn), 'sales': _safe(sales, conn),
         'production': _safe(production, conn), 'people': _safe(people, conn), 'operations': _safe(operations, conn)}
    s['attention'] = _safe(attention, conn, s) or []
    s['generated_at'] = datetime.now().isoformat(timespec='seconds')
    _CACHE['summary'] = (time.time(), s)
    return s


# ---------------- Ayrıntılar (karta tıklanınca) ----------------
def detail(conn, key):
    today = date.today()
    if key == 'cash':
        accs = db.rows(conn.execute("SELECT id, kind, name, bank, opening FROM fin_accounts WHERE kind IN ('kasa','banka') AND active = 1"))
        for a in accs:
            a['balance'] = round((a['opening'] or 0) + _one(conn, "SELECT SUM(CASE WHEN direction = 'in' THEN amount ELSE -amount END) FROM fin_txns WHERE account_id = ?", (a['id'],)), 2)
        accs.sort(key=lambda a: -abs(a['balance']))
        return {'accounts': accs, 'projection': _safe(cash_projection, conn)}
    if key in ('receivables', 'payables', 'overdue'):
        rec, pay = fr.open_items(conn)
        items = rec if key != 'payables' else pay
        t = today.isoformat()
        by = defaultdict(lambda: {'amount': 0.0, 'overdue': 0.0, 'oldest': None})
        names = {}
        for i in items:
            b = by[i['account_id']]
            names[i['account_id']] = i['name']
            b['amount'] += i['amount']
            if i['due'][:10] < t:
                b['overdue'] += i['amount']
                b['oldest'] = min(b['oldest'] or i['due'][:10], i['due'][:10])
        rows = [{'name': names[k], 'amount': round(v['amount'], 2), 'overdue': round(v['overdue'], 2),
                 'late_days': (today - date.fromisoformat(v['oldest'])).days if v['oldest'] else 0} for k, v in by.items()]
        rows.sort(key=lambda r: -(r['overdue'] if key == 'overdue' else r['amount']))
        return {'rows': rows[:40], 'aging': fr.aging(items, today), 'total': round(sum(r['amount'] for r in rows), 2)}
    if key == 'profit':
        p = _safe(profit, conn)
        return p
    if key == 'sales':
        y0 = f'{today.year}-01-01'
        months = db.rows(conn.execute('''SELECT substr(t.date, 1, 7) AS month, ROUND(SUM(t.amount), 2) AS amount FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id
                                         WHERE a.kind = 'cari' AND t.direction = 'in' AND t.category = 'Fatura' AND t.date >= ? GROUP BY month ORDER BY month''',
                                      (_month_add(today.replace(day=1), -11).isoformat(),)))
        top = db.rows(conn.execute('''SELECT a.name, ROUND(SUM(t.amount), 2) AS amount, COUNT(*) AS n, MAX(t.date) AS last FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id
                                      WHERE a.kind = 'cari' AND t.direction = 'in' AND t.category = 'Fatura' AND t.date >= ? GROUP BY a.id ORDER BY amount DESC LIMIT 25''', (y0,)))
        sup = db.rows(conn.execute('''SELECT a.name, ROUND(SUM(t.amount), 2) AS amount, COUNT(*) AS n FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id
                                      WHERE a.kind = 'cari' AND t.direction = 'out' AND t.category = 'Fatura' AND t.date >= ? GROUP BY a.id ORDER BY amount DESC LIMIT 15''', (y0,)))
        return {'months': months, 'top': top, 'suppliers': sup}
    if key == 'production':
        from .production import order_summaries
        orders = [{k: o.get(k) for k in ('code', 'status', 'progress', 'product_name', 'company_name', 'queue_no')}
                  for o in order_summaries(conn) if o.get('status') not in ('TAMAMLANDI', 'HURDA', 'IPTAL')][:30]
        printers = db.rows(conn.execute('SELECT name, live_state, live_progress, live_file FROM printers ORDER BY name'))
        return {'orders': orders, 'printers': printers, 'summary': _safe(production, conn)}
    if key == 'people':
        from . import auth
        absent = auth.absent_map(conn)
        away = db.rows(conn.execute("SELECT id, first_name || ' ' || last_name AS name, title, user_id FROM employees WHERE status = 'AKTIF' AND user_id IS NOT NULL"))
        away = [dict(e, **absent[e['user_id']]) for e in away if e['user_id'] in absent]
        titles = db.rows(conn.execute("SELECT COALESCE(NULLIF(title, ''), 'Belirtilmemiş') AS title, COUNT(*) AS n, ROUND(SUM(COALESCE(salary, 0)), 2) AS payroll FROM employees WHERE status = 'AKTIF' GROUP BY 1 ORDER BY n DESC"))
        recent = db.rows(conn.execute("SELECT first_name || ' ' || last_name AS name, title, start_date FROM employees WHERE status = 'AKTIF' AND start_date IS NOT NULL ORDER BY start_date DESC LIMIT 8"))
        return {'away': away, 'titles': titles, 'recent': recent, 'summary': _safe(people, conn)}
    if key == 'operations':
        fleet = db.rows(conn.execute('''SELECT v.plate, v.brand, v.model, ROUND(SUM(e.amount), 2) AS amount FROM field_vehicles v LEFT JOIN vehicle_expenses e
                                        ON e.vehicle_id = v.id AND e.date >= ? WHERE v.active = 1 GROUP BY v.id ORDER BY amount DESC''', (f'{today.year}-01-01',)))
        certs = db.rows(conn.execute("SELECT name, standard, status, expiry_date FROM certs ORDER BY CASE WHEN expiry_date IS NULL OR expiry_date = '' THEN 1 ELSE 0 END, expiry_date"))
        reqs = db.rows(conn.execute("SELECT code, title, needed_by, submitted_at FROM purchase_requests WHERE status = 'ONAY_BEKLIYOR' ORDER BY submitted_at"))
        return {'fleet': fleet, 'certs': certs, 'requests': reqs, 'summary': _safe(operations, conn)}
    return None
