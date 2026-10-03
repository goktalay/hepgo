"""Finans v2 raporları: mizan, hesap ekstresi, mali tablolar (bilanço özeti + gelir tablosu), açık kalemler (FIFO),
yaşlandırma ve nakit akışı takvimi.

Muhasebe verisi Mikro'dan (fin_ledger / fin_coa, Program Ayarları › Entegrasyonlar › Mikro senkronu) gelir; ön muhasebe
(kasa / banka / cari hareketleri, çek-senet, planlı ödemeler) Finans modülünün kendi tablolarındadır.
Hesap hiyerarşisi Tekdüzen Hesap Planı'na göre: 1 (sınıf) → 10 (grup) → 100 (ana hesap) → 100.01 → 100.01.0001 …
"""
from collections import defaultdict
from datetime import date, timedelta

from . import db

# Tekdüzen Hesap Planı sınıf / grup adları (hesap planında yoksa yedek)
TDHP = {'1': 'DÖNEN VARLIKLAR', '2': 'DURAN VARLIKLAR', '3': 'KISA VADELİ YABANCI KAYNAKLAR', '4': 'UZUN VADELİ YABANCI KAYNAKLAR',
        '5': 'ÖZKAYNAKLAR', '6': 'GELİR TABLOSU HESAPLARI', '7': 'MALİYET HESAPLARI', '8': 'SERBEST', '9': 'NAZIM HESAPLAR'}


def ancestors(code):
    """'100.01.0001' → ['1', '10', '100', '100.01', '100.01.0001']"""
    code = (code or '').strip()
    if not code:
        return []
    head, *rest = code.split('.')
    out = [head[:i] for i in range(1, min(3, len(head)) + 1)]
    if len(head) > 3:
        out.append(head)
    cur = head
    for seg in rest:
        cur = f'{cur}.{seg}'
        out.append(cur)
    return out


def depth(code):
    return len(ancestors(code))


def _names(conn):
    n = dict(TDHP)
    n.update({r[0]: r[1] for r in conn.execute('SELECT code, name FROM fin_coa')})
    return n


def has_ledger(conn):
    return bool(conn.execute('SELECT 1 FROM fin_ledger LIMIT 1').fetchone())


def _range(date_from, date_to):
    today = date.today()
    return date_from or f'{today.year}-01-01', date_to or today.isoformat()


def trial_balance(conn, date_from='', date_to='', level=3):
    """Mizan: seçilen dönemde her hesabın borç / alacak toplamı ve bakiyesi; üst hesaplara toplanır.
    level: 1 sınıf · 2 grup · 3 ana hesap · 4 alt hesap · 9 tüm detay."""
    d0, d1 = _range(date_from, date_to)
    agg = defaultdict(lambda: [0.0, 0.0])
    for acc, deb, cre in conn.execute('SELECT account, SUM(debit), SUM(credit) FROM fin_ledger WHERE date BETWEEN ? AND ? GROUP BY account', (d0, d1)):
        for a in ancestors(acc):
            agg[a][0] += deb or 0
            agg[a][1] += cre or 0
    names = _names(conn)
    shown = sorted(c for c in agg if depth(c) <= level)   # Tekdüzen kodlarında düz sıralama = hiyerarşik sıra
    parents = {a for c in shown for a in ancestors(c)[:-1]}
    rows = []
    for code in shown:
        deb, cre = agg[code]
        bal = deb - cre
        rows.append({'code': code, 'name': names.get(code, ''), 'depth': depth(code), 'debit': round(deb, 2), 'credit': round(cre, 2),
                     'bal_debit': round(bal, 2) if bal > 0 else 0.0, 'bal_credit': round(-bal, 2) if bal < 0 else 0.0,
                     'has_children': code in parents})
    tops = [r for r in rows if r['depth'] == 1]
    tot = {k: round(sum(r[k] for r in tops), 2) for k in ('debit', 'credit', 'bal_debit', 'bal_credit')}
    return {'date_from': d0, 'date_to': d1, 'level': level, 'rows': rows, 'total': tot,
            'balanced': abs(tot['debit'] - tot['credit']) < 0.05}


def account_ledger(conn, account, date_from='', date_to=''):
    """Hesap ekstresi (ön ek eşleşmesi: üst hesap seçilirse alt hesapların satırları da gelir), yürüyen bakiye."""
    d0, d1 = _range(date_from, date_to)
    like = account + ('.%' if '.' in account or len(account) >= 3 else '%')
    opening = conn.execute('SELECT COALESCE(SUM(debit - credit), 0) FROM fin_ledger WHERE (account = ? OR account LIKE ?) AND date < ?',
                           (account, like, d0)).fetchone()[0]
    rows = db.rows(conn.execute('''SELECT date, journal_no, entry_no, account, description, debit, credit, doc_no FROM fin_ledger
                                   WHERE (account = ? OR account LIKE ?) AND date BETWEEN ? AND ? ORDER BY date, entry_no, id''',
                                (account, like, d0, d1)))
    bal = opening
    for r in rows:
        bal += (r['debit'] or 0) - (r['credit'] or 0)
        r['balance'] = round(bal, 2)
    return {'account': account, 'name': _names(conn).get(account, ''), 'opening': round(opening, 2), 'rows': rows, 'closing': round(bal, 2)}


def statements(conn, date_from='', date_to=''):
    """Bilanço özeti (sınıf 1–5) + gelir tablosu (sınıf 6; yansıtılmamış 7/A giderleri dahil)."""
    d0, d1 = _range(date_from, date_to)
    g = defaultdict(float)   # 3 haneli ana hesap → borç − alacak
    for acc, bal in conn.execute('SELECT account, SUM(debit - credit) FROM fin_ledger WHERE date BETWEEN ? AND ? GROUP BY account', (d0, d1)):
        g[(acc or '')[:3]] += bal or 0
    bs_all = defaultdict(float)   # bilanço: başlangıçtan bitişe kümülatif
    for acc, bal in conn.execute('SELECT account, SUM(debit - credit) FROM fin_ledger WHERE date <= ? GROUP BY account', (d1,)):
        bs_all[(acc or '')[:3]] += bal or 0
    names = _names(conn)

    def s(prefixes, src=g):
        return sum(v for k, v in src.items() if any(k.startswith(p) for p in prefixes))
    # Gelir tablosu (gelirler alacak bakiyeli → işaret çevrilir)
    brut = -s(['60'])
    indirim = s(['61'])
    net_satis = brut - indirim
    smm = s(['62'])
    brut_kar = net_satis - smm
    # 7/A: yansıtılmamış faaliyet giderleri (75 Ar-Ge, 76 Pazarlama, 77 Genel Yönetim → 63; 78 Finansman → 66)
    y_faal = s(['75', '76', '77'])
    y_fin = s(['78'])
    faal = s(['63']) + y_faal
    faal_kar = brut_kar - faal
    diger_gelir = -s(['64'])
    diger_gider = s(['65'])
    finansman = s(['66']) + y_fin
    olagan = faal_kar + diger_gelir - diger_gider - finansman
    olagandisi_gelir = -s(['67'])
    olagandisi_gider = s(['68'])
    donem = olagan + olagandisi_gelir - olagandisi_gider
    vergi = s(['691'])
    uretim = s(['71', '72', '73', '74'])   # stoğa / satılan mamul maliyetine yansıtılır (doğrudan kâr kalemi değil)
    income = [
        ('A', 'Brüt satışlar (60)', brut), ('B', 'Satış indirimleri (−) (61)', -indirim), ('C', 'Net satışlar', net_satis, True),
        ('D', 'Satışların maliyeti (−) (62)', -smm), ('', 'Brüt satış kârı / zararı', brut_kar, True),
        ('E', 'Faaliyet giderleri (−) (63' + (' + yansıtılmamış 75–77' if y_faal else '') + ')', -faal), ('', 'Faaliyet kârı / zararı', faal_kar, True),
        ('F', 'Diğer faaliyetlerden olağan gelir ve kârlar (64)', diger_gelir), ('G', 'Diğer faaliyetlerden olağan gider ve zararlar (−) (65)', -diger_gider),
        ('H', 'Finansman giderleri (−) (66' + (' + yansıtılmamış 78' if y_fin else '') + ')', -finansman), ('', 'Olağan kâr / zarar', olagan, True),
        ('I', 'Olağan dışı gelir ve kârlar (67)', olagandisi_gelir), ('J', 'Olağan dışı gider ve zararlar (−) (68)', -olagandisi_gider),
        ('', 'Dönem kârı / zararı', donem, True), ('K', 'Dönem kârı vergi ve diğer yasal yükümlülük karşılıkları (−) (691)', -vergi),
        ('', 'Dönem net kârı / zararı', donem - vergi, True),
    ]
    balance = {
        'aktif': [(c, names.get(c, TDHP[c]), round(s([c], bs_all), 2)) for c in ('1', '2')],
        'pasif': [(c, names.get(c, TDHP[c]), round(-s([c], bs_all), 2)) for c in ('3', '4', '5')],
    }
    # Bilançodaki ana hesap kırılımı (sıfır olmayanlar)
    detail = [{'code': k, 'name': names.get(k, ''), 'amount': round(v if k[0] in '12' else -v, 2)} for k, v in sorted(bs_all.items())
              if k and k[0] in '12345' and abs(v) >= 0.005]
    # Kapanmamış dönem: 6/7. sınıf net bakiye pasife "dönem sonucu" olarak eklenir. Stoğa henüz yansıtılmamış üretim
    # maliyetleri (71–74) gider değil varlıktır → aktifte ayrı satır; böylece dönem sonucu gelir tablosuyla aynı olur.
    uretim_bs = round(s(['71', '72', '73', '74'], bs_all), 2)
    if abs(uretim_bs) >= 0.005:
        balance['aktif'].append(('71–74', 'Stoğa yansıtılmamış üretim maliyetleri', uretim_bs))
    kar = round(-s(['6', '7'], bs_all) + uretim_bs, 2)
    ta = round(sum(x[2] for x in balance['aktif']), 2)
    tp = round(sum(x[2] for x in balance['pasif']) + kar, 2)
    return {'date_from': d0, 'date_to': d1,
            'income': [{'code': x[0], 'label': x[1], 'amount': round(x[2], 2), 'total': len(x) > 3} for x in income],
            'kpi': {'net_satis': round(net_satis, 2), 'brut_kar': round(brut_kar, 2), 'faaliyet_kar': round(faal_kar, 2),
                    'net_kar': round(donem - vergi, 2), 'brut_marj': round(brut_kar / net_satis * 100, 1) if net_satis else None,
                    'net_marj': round((donem - vergi) / net_satis * 100, 1) if net_satis else None},
            'uretim_maliyeti': round(uretim, 2), 'yansitilmamis': round(y_faal + y_fin, 2),
            'balance': {'aktif': [{'code': c, 'name': n, 'amount': a} for c, n, a in balance['aktif']],
                        'pasif': [{'code': c, 'name': n, 'amount': a} for c, n, a in balance['pasif']],
                        'donem_sonucu': kar, 'toplam_aktif': ta, 'toplam_pasif': tp, 'detail': detail}}


# ---------------- Açık kalemler (FIFO) · yaşlandırma · nakit akışı ----------------
def open_items(conn):
    """Cari hesaplarda kapanmamış kalemler (FIFO): borçlandırmalar (alacağımız) ve alacaklandırmalar (borcumuz),
    vadesiyle. Ödemeler en eski kaleme sayılır."""
    out_rec, out_pay = [], []
    accs = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, name, company_id FROM fin_accounts WHERE kind='cari' AND active=1")}
    rows = conn.execute(f'''SELECT account_id, date, COALESCE(due_date, date), direction, amount, description, doc_no FROM fin_txns
                           WHERE account_id IN ({",".join("?" * len(accs)) or "NULL"}) ORDER BY account_id, date, id''', tuple(accs)).fetchall()
    cur, deb, cre = None, [], []

    def flush(aid):
        name, cid = accs.get(aid, ('', None))
        for d, due, amt, desc, doc in deb:
            if amt > 0.005:
                out_rec.append({'account_id': aid, 'company_id': cid, 'name': name, 'date': d, 'due': due, 'amount': round(amt, 2), 'description': desc, 'doc_no': doc})
        for d, due, amt, desc, doc in cre:
            if amt > 0.005:
                out_pay.append({'account_id': aid, 'company_id': cid, 'name': name, 'date': d, 'due': due, 'amount': round(amt, 2), 'description': desc, 'doc_no': doc})
    for aid, d, due, direction, amt, desc, doc in rows:
        if aid != cur:
            if cur is not None:
                flush(cur)
            cur, deb, cre = aid, [], []
        amt = float(amt or 0)
        same, other = (deb, cre) if direction == 'in' else (cre, deb)
        while amt > 0.005 and other:   # karşı yöndeki en eski açık kalemi kapat
            take = min(amt, other[0][2])
            other[0][2] -= take
            amt -= take
            if other[0][2] <= 0.005:
                other.pop(0)
        if amt > 0.005:
            same.append([d, due, amt, desc, doc])
    if cur is not None:
        flush(cur)
    return out_rec, out_pay


BUCKETS = [('Vadesi gelmemiş', None, -1), ('0–30 gün', 0, 30), ('31–60 gün', 31, 60), ('61–90 gün', 61, 90), ('90+ gün', 91, 10 ** 6)]


def aging(items, today=None):
    today = today or date.today()
    tot = [0.0] * len(BUCKETS)
    by = defaultdict(lambda: [0.0] * len(BUCKETS))
    names = {}
    for it in items:
        try:
            late = (today - date.fromisoformat(it['due'][:10])).days
        except ValueError:
            late = 0
        i = 0 if late < 0 else next(k for k, b in enumerate(BUCKETS) if k and b[1] <= late <= b[2])
        tot[i] += it['amount']
        by[it['account_id']][i] += it['amount']
        names[it['account_id']] = it['name']
    top = sorted(({'account_id': a, 'name': names[a], 'buckets': [round(x, 2) for x in v], 'total': round(sum(v), 2)} for a, v in by.items()),
                 key=lambda x: -x['total'])[:15]
    return {'labels': [b[0] for b in BUCKETS], 'totals': [round(x, 2) for x in tot], 'total': round(sum(tot), 2), 'top': top}


def _cash_now(conn):
    total = 0.0
    for aid, opening in conn.execute("SELECT id, opening FROM fin_accounts WHERE kind IN ('kasa','banka') AND active=1"):
        s = conn.execute("SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount ELSE -amount END),0) FROM fin_txns WHERE account_id=?", (aid,)).fetchone()[0]
        total += (opening or 0) + (s or 0)
    return round(total, 2)


def _add_month(d, n=1):
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    import calendar
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def cashflow(conn, weeks=12, payday=None, salaries=True):
    """Önümüzdeki N hafta: açık alacak/borç (vadeye göre), çek-senet, planlı ödemeler, maaş günü; yürüyen nakit."""
    today = date.today()
    start = today - timedelta(days=today.weekday())   # bu haftanın pazartesisi
    end = start + timedelta(weeks=weeks)
    rec, pay = open_items(conn)
    items = []
    for it in rec:
        items.append({'date': it['due'][:10], 'dir': 'in', 'amount': it['amount'], 'kind': 'Alacak', 'label': it['name'], 'detail': it['description'] or it['doc_no'] or ''})
    for it in pay:
        items.append({'date': it['due'][:10], 'dir': 'out', 'amount': it['amount'], 'kind': 'Borç', 'label': it['name'], 'detail': it['description'] or it['doc_no'] or ''})
    for r in db.rows(conn.execute("""SELECT i.*, c.name AS company FROM fin_instruments i LEFT JOIN companies c ON c.id=i.company_id
                                     WHERE i.status IN ('portfoy','tahsilde','teminatta','ciro')""")):
        if r['direction'] == 'verilen' and r['status'] != 'ciro':
            items.append({'date': r['due_date'], 'dir': 'out', 'amount': r['amount'], 'kind': 'Verilen ' + ('çek' if r['kind'] == 'cek' else 'senet'),
                          'label': r['company'] or r['drawer'] or '', 'detail': r['number'] or ''})
        elif r['direction'] == 'alinan' and r['status'] in ('portfoy', 'tahsilde', 'teminatta'):
            items.append({'date': r['due_date'], 'dir': 'in', 'amount': r['amount'], 'kind': 'Alınan ' + ('çek' if r['kind'] == 'cek' else 'senet'),
                          'label': r['company'] or r['drawer'] or '', 'detail': r['number'] or ''})
    for p in db.rows(conn.execute('SELECT * FROM fin_plans')):
        try:
            d = date.fromisoformat(p['date'][:10])
        except ValueError:
            continue
        until = date.fromisoformat(p['until'][:10]) if p.get('until') else end
        n = 0
        while d <= min(end, until) and n < 60:
            if d >= today - timedelta(days=0) or p['repeat'] == 'none':
                items.append({'date': d.isoformat(), 'dir': p['direction'], 'amount': p['amount'], 'kind': 'Planlı', 'label': p['description'], 'detail': p.get('category') or ''})
            if p['repeat'] != 'monthly':
                break
            d = _add_month(d)
            n += 1
    if salaries and payday:
        total = conn.execute("SELECT COALESCE(SUM(salary),0), COUNT(*) FROM employees WHERE status='AKTIF' AND salary > 0").fetchone()
        if total[0]:
            d = today.replace(day=min(payday, 28))
            if d < today:
                d = _add_month(d)
            while d < end:
                items.append({'date': d.isoformat(), 'dir': 'out', 'amount': round(total[0], 2), 'kind': 'Maaş', 'label': f'{total[1]} personel maaşı', 'detail': ''})
                d = _add_month(d)
    overdue = {'in': round(sum(i['amount'] for i in items if i['date'] < today.isoformat() and i['dir'] == 'in'), 2),
               'out': round(sum(i['amount'] for i in items if i['date'] < today.isoformat() and i['dir'] == 'out'), 2)}
    cash = _cash_now(conn)
    bal = cash
    wk = []
    for w in range(weeks):
        a, b = start + timedelta(weeks=w), start + timedelta(weeks=w, days=6)
        ins = sum(i['amount'] for i in items if a.isoformat() <= i['date'] <= b.isoformat() and i['dir'] == 'in' and i['date'] >= today.isoformat())
        outs = sum(i['amount'] for i in items if a.isoformat() <= i['date'] <= b.isoformat() and i['dir'] == 'out' and i['date'] >= today.isoformat())
        bal += ins - outs
        wk.append({'start': a.isoformat(), 'end': b.isoformat(), 'in': round(ins, 2), 'out': round(outs, 2), 'balance': round(bal, 2)})
    upcoming = sorted((i for i in items if today.isoformat() <= i['date'] < end.isoformat()), key=lambda i: i['date'])
    return {'cash': cash, 'weeks': wk, 'overdue': overdue, 'items': upcoming[:400], 'items_total': len(upcoming),
            'aging_rec': aging(rec, today), 'aging_pay': aging(pay, today), 'end_balance': round(bal, 2)}
