"""Raporlar modülü: tüm modüllerin raporları.

Her rapor bir modüle bağlıdır; kullanıcı yalnızca girebildiği modüllerin raporlarını görür. Rapor fonksiyonu tarih
aralığını (p['from'], p['to'] — YYYY-MM-DD) alır ve şunu döndürür:
  kpis:     [{label, value, sub?, tone?}]                         özet göstergeler
  insights: [metin]                                               otomatik çıkarımlar
  charts:   [{title, type, labels, datasets, unit?, wide?, stacked?, sub?}]
            type: bar | hbar | line | area | doughnut | combo (çubuk + çizgi, ikinci eksen) | heat (hafta günü × saat)
  tables:   [{title, columns: [{key, label, align?}], rows: [...], sub?}]
Arayüz grafik (göstergeler, çıkarımlar, grafikler) ya da baskı (göstergeler, tablolar) olarak gösterir; ikisi de antetli yazdırılır.
"""
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from . import db

DAYS_TR = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']
ORDER_TEXT = {'SIPARIS': 'Sipariş', 'URETIM': 'Üretim', 'HATA': 'Hata', 'DEPO': 'Depo', 'MONTAJ': 'Montaj', 'SAHADA_MONTAJ': 'Sahada Montaj',
              'KALIBRASYON': 'Kalibrasyon', 'SAHA_ONAY': 'Saha deposu onayı', 'TAMAMLANDI': 'Saha Deposunda', 'HURDA': 'Hurda (uçtu)'}
REPORTS = []


def report(key, module, title, desc):
    def deco(fn):
        REPORTS.append({'key': key, 'module': module, 'title': title, 'desc': desc, 'fn': fn})
        return fn
    return deco


# ---------- yardımcılar

def rng(p):
    return f'{p["from"]}T00:00:00', f'{p["to"]}T23:59:59'


def days(p):
    d0, d1 = date.fromisoformat(p['from']), date.fromisoformat(p['to'])
    return [(d0 + timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]


def day_labels(ds):
    return [f'{d[8:10]}.{d[5:7]}' for d in ds]


def series(ds, counter):
    return [counter.get(d, 0) for d in ds]


def mins(a, b):
    try:
        return (datetime.fromisoformat(b[:19]) - datetime.fromisoformat(a[:19])).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def dur(m):
    """Dakika → '2 sa 15 dk' / '3 g 4 sa'."""
    if m is None:
        return '—'
    m = int(round(m))
    if m < 60:
        return f'{m} dk'
    h, mm = divmod(m, 60)
    if h < 48:
        return f'{h} sa {mm} dk' if mm else f'{h} sa'
    d, hh = divmod(h, 24)
    return f'{d} g {hh} sa'


def pct(a, b):
    return round(100 * a / b, 1) if b else 0


def median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def quantile(v, q):
    v = sorted(x for x in v if x is not None)
    return v[min(len(v) - 1, int(math.ceil(q * len(v))) - 1)] if v else None


def fmt_dt(s):
    return f'{s[8:10]}.{s[5:7]}.{s[:4]} {s[11:16]}' if s else '—'


def top(counter, n=12):
    return counter.most_common(n)


def pareto(counter, share=0.8):
    """Toplamın %80'ini oluşturan en az sayıda kalem."""
    total = sum(counter.values())
    acc, out = 0, []
    for k, v in counter.most_common():
        out.append(k)
        acc += v
        if acc >= share * total:
            break
    return out


def heat(rows_at):
    """Hafta günü × saat ısı haritası: 7 × 24 sayım."""
    grid = [[0] * 24 for _ in range(7)]
    for at in rows_at:
        try:
            t = datetime.fromisoformat(at[:19])
        except (TypeError, ValueError):
            continue
        grid[t.weekday()][t.hour] += 1
    return {'rows': DAYS_TR, 'cols': [f'{h:02d}' for h in range(24)], 'values': grid}


def peak_of(grid):
    best = max(((grid['values'][d][h], d, h) for d in range(7) for h in range(24)), default=(0, 0, 0))
    return best


def col(key, label, align=None):
    return {'key': key, 'label': label, **({'align': align} if align else {})}


# ================================================================ ÜRETİM

@report('uretim-performans', 'production', 'Üretim Performansı',
        'Günlük depoya giren parça ve hata, vardiya (saat) dağılımı, parça durumları')
def uretim_performans(conn, p):
    a, b = rng(p)
    ev = db.rows(conn.execute("SELECT event, at FROM part_events WHERE at BETWEEN ? AND ? AND event IN ('URETIME_BASLADI','URETIM_TAMAMLANDI','HATA','DEPO_ONAY')", (a, b)))
    ds = days(p)
    by = defaultdict(Counter)
    for e in ev:
        by[e['event']][e['at'][:10]] += 1
    started, done, errs = sum(by['URETIME_BASLADI'].values()), sum(by['URETIM_TAMAMLANDI'].values()), sum(by['HATA'].values())
    parts = db.rows(conn.execute('''SELECT op.state, op.print_seconds, op.printer_done_at, op.finished_at FROM order_parts op
                                    WHERE op.finished_at BETWEEN ? AND ?''', (a, b)))
    net = [x['print_seconds'] / 60 for x in parts if x['print_seconds']]
    waits = [mins(x['printer_done_at'], x['finished_at']) for x in parts if x['printer_done_at'] and x['finished_at']]
    hours = Counter(int(e['at'][11:13]) for e in ev if e['event'] == 'URETIME_BASLADI')
    state = Counter(r[0] for r in conn.execute(
        "SELECT op.state FROM order_parts op JOIN orders o ON o.id = op.order_id WHERE o.status NOT IN ('TAMAMLANDI','HURDA')"))
    names = {'BEKLIYOR': 'Üretilmedi', 'URETIMDE': 'Üretimde', 'DEPO': 'Depoda', 'MONTAJ': 'Montajda', 'HATA': 'Hata'}
    busiest = max(ds, key=lambda d: by['URETIM_TAMAMLANDI'].get(d, 0)) if ds else None
    night = sum(v for h, v in hours.items() if h >= 20 or h < 7)
    ins = [f'Dönemde {started} baskı başlatıldı, {done} parça depoya teslim edildi; hata oranı %{pct(errs, started)}.']
    if busiest and by['URETIM_TAMAMLANDI'].get(busiest):
        ins.append(f'En verimli gün {busiest[8:10]}.{busiest[5:7]}: {by["URETIM_TAMAMLANDI"][busiest]} parça teslim.')
    if started:
        ins.append(f'Baskıların %{pct(night, started)} kadarı akşam 20:00 – sabah 07:00 arasında başlatıldı (gece kullanımı).')
    if waits:
        ins.append(f'Biten parça yazıcıda ortalama {dur(sum(waits) / len(waits))} bekledi; bu süre yazıcı kapasitesinden kayıp demektir.')
    return {
        'kpis': [{'icon': 'production', 'label': 'Başlatılan baskı', 'value': started}, {'icon': 'warehouse', 'label': 'Depoya teslim', 'value': done, 'tone': 'ok'},
                 {'icon': 'warning', 'label': 'Hata', 'value': errs, 'tone': 'alert' if errs else ''},
                 {'icon': 'warning', 'label': 'Hata oranı', 'value': f'%{pct(errs, started)}'}],
        'insights': ins,
        'charts': [
            {'title': 'Günlük üretim ve hata', 'type': 'combo', 'wide': True, 'labels': day_labels(ds),
             'datasets': [{'label': 'Depoya teslim', 'data': series(ds, by['URETIM_TAMAMLANDI'])},
                          {'label': 'Başlatılan', 'data': series(ds, by['URETIME_BASLADI'])},
                          {'label': 'Hata', 'data': series(ds, by['HATA']), 'line': True}]},
            {'title': 'Baskı başlatma saatleri (vardiya)', 'type': 'bar', 'labels': [f'{h:02d}' for h in range(24)],
             'datasets': [{'label': 'Başlatılan baskı', 'data': [hours.get(h, 0) for h in range(24)]}]},
            {'title': 'Açık siparişlerde parça durumu', 'type': 'doughnut', 'labels': [names.get(k, k) for k in state],
             'datasets': [{'label': 'Parça', 'data': list(state.values())}]},
        ],
        'tables': [{'title': 'Günlük özet', 'columns': [col('day', 'Gün'), col('start', 'Başlatılan', 'num'), col('done', 'Depoya teslim', 'num'),
                                                         col('err', 'Hata', 'num'), col('rate', 'Hata oranı', 'num')],
                    'rows': [{'day': f'{d[8:10]}.{d[5:7]}.{d[:4]}', 'start': by['URETIME_BASLADI'].get(d, 0), 'done': by['URETIM_TAMAMLANDI'].get(d, 0),
                              'err': by['HATA'].get(d, 0), 'rate': f'%{pct(by["HATA"].get(d, 0), by["URETIME_BASLADI"].get(d, 0))}'}
                             for d in ds if by['URETIME_BASLADI'].get(d) or by['URETIM_TAMAMLANDI'].get(d) or by['HATA'].get(d)]}],
    }


def _code(c):
    k = (c or '').strip().upper()
    return 'KODSUZ' if not k or k.strip('.-0') == '' or k.startswith(('KOD YOK', 'HATA KODU YOK')) else k


@report('hata-analizi', 'production', 'Üretim Hataları Analizi (Pareto)',
        'Hata kodu Pareto analizi; yazıcı, parça ve saat bazında hatalar')
def hata_analizi(conn, p):
    a, b = rng(p)
    rows = db.rows(conn.execute(
        '''SELECT e.at, e.error_code, e.note, op.part_id, o.code AS order_code, pr.name AS printer, u.full_name AS user
           FROM part_events e JOIN order_parts op ON op.id = e.order_part_id JOIN orders o ON o.id = op.order_id
           LEFT JOIN printers pr ON pr.id = e.printer_id LEFT JOIN users u ON u.id = e.user_id
           WHERE e.event = 'HATA' AND e.at BETWEEN ? AND ? ORDER BY e.at DESC''', (a, b)))
    starts = conn.execute("SELECT COUNT(*) FROM part_events WHERE event = 'URETIME_BASLADI' AND at BETWEEN ? AND ?", (a, b)).fetchone()[0]
    codes = Counter(_code(r['error_code']) for r in rows)
    printers = Counter(r['printer'] or '—' for r in rows)
    parts = Counter(r['part_id'] for r in rows)
    total = len(rows)
    pk = [k for k, _ in codes.most_common(12)]
    cum, acc = [], 0
    for k in pk:
        acc += codes[k]
        cum.append(round(100 * acc / total, 1) if total else 0)
    vital = pareto(codes)
    ins = []
    if total:
        ins.append(f'Hataların %80\'i {len(vital)} hata kodundan geliyor: {", ".join(vital[:5])}. Önce bunlara odaklanmak en büyük iyileşmeyi sağlar.')
        pt = printers.most_common(1)[0]
        ins.append(f'En çok hata veren yazıcı {pt[0]}: {pt[1]} hata (tümünün %{pct(pt[1], total)}). Bakım önceliği bu yazıcı olmalı.')
        pp = parts.most_common(1)[0]
        ins.append(f'En çok hata veren parça {pp[0]} ({pp[1]} hata); dosya / dilimleme ayarlarının gözden geçirilmesi önerilir.')
        repeat = sum(1 for v in Counter((r['order_code'], r['part_id']) for r in rows).values() if v > 1)
        if repeat:
            ins.append(f'{repeat} parça aynı siparişte birden çok kez hata verdi (tekrarlayan hata).')
    else:
        ins.append('Bu dönemde hata kaydı yok.')
    return {
        'kpis': [{'icon': 'warning', 'label': 'Hata', 'value': total, 'tone': 'alert' if total else ''}, {'icon': 'warning', 'label': 'Hata oranı', 'value': f'%{pct(total, starts)}', 'sub': f'{starts} baskıda'},
                 {'icon': 'tag', 'label': 'Farklı hata kodu', 'value': len(codes)}, {'icon': 'printers', 'label': 'Hata veren yazıcı', 'value': len(printers)}],
        'insights': ins,
        'charts': [
            {'title': 'Hata kodları — Pareto', 'type': 'combo', 'wide': True, 'labels': pk, 'pareto': True,
             'datasets': [{'label': 'Hata sayısı', 'data': [codes[k] for k in pk]}, {'label': 'Kümülatif %', 'data': cum, 'line': True, 'axis': 'pct'}]},
            {'title': 'Yazıcılara göre hata', 'type': 'hbar', 'labels': [k for k, _ in top(printers)], 'datasets': [{'label': 'Hata', 'data': [v for _, v in top(printers)]}]},
            {'title': 'Parçalara göre hata', 'type': 'hbar', 'labels': [k for k, _ in top(parts)], 'datasets': [{'label': 'Hata', 'data': [v for _, v in top(parts)]}]},
            {'title': 'Hataların zamanı (gün × saat)', 'type': 'heat', 'wide': True, 'heat': heat([r['at'] for r in rows])},
        ],
        'tables': [{'title': 'Hata kayıtları', 'columns': [col('at', 'Zaman'), col('order_code', 'Sipariş'), col('part_id', 'Parça'), col('printer', 'Yazıcı'),
                                                          col('code', 'Hata kodu'), col('note', 'Açıklama'), col('user', 'Kaydeden')],
                    'rows': [{**r, 'at': fmt_dt(r['at']), 'code': r['error_code'] or '—', 'note': r['note'] or '', 'printer': r['printer'] or '—'} for r in rows]}],
    }


@report('baski-sapma', 'production', 'Baskı Süresi Sapması',
        'Planlanan dosya süresi ile yazıcının bildirdiği gerçek net baskı süresinin parça bazında karşılaştırması')
def baski_sapma(conn, p):
    from .semis import print_info
    a, b = rng(p)
    info = print_info(conn)
    rows = db.rows(conn.execute('SELECT part_id, print_seconds FROM order_parts WHERE print_seconds > 0 AND finished_at BETWEEN ? AND ?', (a, b)))
    acc = defaultdict(list)
    for r in rows:
        acc[r['part_id']].append(r['print_seconds'] / 60)
    out = []
    for pid, v in acc.items():
        plan = (info.get(pid) or {}).get('print_minutes')
        real = sum(v) / len(v)
        out.append({'part': pid, 'n': len(v), 'plan': plan, 'real': real, 'dev': pct(real - plan, plan) if plan else None})
    out.sort(key=lambda r: -(abs(r['dev']) if r['dev'] is not None else -1))
    with_plan = [r for r in out if r['plan']]
    tp = sum(r['plan'] * r['n'] for r in with_plan)
    tr = sum(r['real'] * r['n'] for r in with_plan)
    ins = []
    if with_plan:
        ins.append(f'Toplamda gerçek net baskı süresi planın %{pct(tr - tp, tp):+} kadar {"üstünde" if tr > tp else "altında"}.')
        w = with_plan[0]
        ins.append(f'En büyük sapma {w["part"]}: plan {dur(w["plan"])}, gerçek ortalama {dur(w["real"])} (%{w["dev"]:+}).')
        slow = [r['part'] for r in with_plan if r['dev'] and r['dev'] > 10]
        if slow:
            ins.append(f'{len(slow)} parça planlanandan %10\'dan fazla uzun basılıyor; Üretim Planlayıcı süreleri bunlarda iyimser kalır: {", ".join(slow[:8])}.')
    else:
        ins.append('Bu dönemde yazıcının net baskı süresi bildirdiği tamamlanmış parça yok.')
    ins.append('Net baskı süresi (duraklamalar hariç) 28.09.2026\'dan itibaren yazıcıdan ölçülüyor; veri biriktikçe rapor güçlenir.')
    top_rows = with_plan[:15]
    return {
        'kpis': [{'icon': 'production', 'label': 'Ölçülen baskı', 'value': len(rows)}, {'icon': 'products', 'label': 'Parça türü', 'value': len(out)},
                 {'icon': 'calendar', 'label': 'Toplam gerçek', 'value': dur(tr)},
                 {'icon': 'warning', 'label': 'Genel sapma', 'value': f'%{pct(tr - tp, tp):+}' if tp else '—', 'tone': 'alert' if tp and tr > tp * 1.1 else ''}],
        'insights': ins,
        'charts': [{'title': 'Plan ve gerçek net baskı (en çok sapan 15 parça, dakika)', 'type': 'bar', 'wide': True, 'labels': [r['part'] for r in top_rows],
                    'datasets': [{'label': 'Plan', 'data': [r['plan'] for r in top_rows]}, {'label': 'Gerçek ort.', 'data': [round(r['real']) for r in top_rows]}]}],
        'tables': [{'title': 'Parça bazında sapma', 'columns': [col('part', 'Parça'), col('n', 'Baskı', 'num'), col('plan_t', 'Plan', 'num'),
                                                                col('real_t', 'Gerçek ort.', 'num'), col('dev_t', 'Sapma', 'num')],
                    'rows': [{**r, 'plan_t': dur(r['plan']), 'real_t': dur(r['real']), 'dev_t': f'%{r["dev"]:+}' if r['dev'] is not None else '—'} for r in out]}],
    }


@report('yazicida-bekleme', 'production', 'Yazıcıda Bekleme (Tabla Boşaltma)',
        'Baskısı biten parçanın yazıcıda ne kadar beklediği; saat, yazıcı ve teslim eden bazında')
def yazicida_bekleme(conn, p):
    a, b = rng(p)
    rows = db.rows(conn.execute(
        '''SELECT op.part_id, op.printer_done_at, op.finished_at, pr.name AS printer, o.code AS order_code,
                  (SELECT u.full_name FROM part_events e JOIN users u ON u.id = e.user_id WHERE e.order_part_id = op.id AND e.event = 'URETIM_TAMAMLANDI'
                   ORDER BY e.id DESC LIMIT 1) AS user
           FROM order_parts op JOIN orders o ON o.id = op.order_id LEFT JOIN printers pr ON pr.id = op.printer_id
           WHERE op.printer_done_at IS NOT NULL AND op.finished_at BETWEEN ? AND ?''', (a, b)))
    for r in rows:
        r['wait'] = max(0, mins(r['printer_done_at'], r['finished_at']) or 0)
    w = [r['wait'] for r in rows]
    buckets = [('0–15 dk', 0, 15), ('15–30 dk', 15, 30), ('30–60 dk', 30, 60), ('1–2 sa', 60, 120), ('2–4 sa', 120, 240), ('4–8 sa', 240, 480), ('8 sa+', 480, 1e9)]
    hist = [sum(1 for x in w if lo <= x < hi) for _, lo, hi in buckets]
    by_hour = defaultdict(list)
    for r in rows:
        by_hour[int(r['printer_done_at'][11:13])].append(r['wait'])
    by_printer = defaultdict(list)
    for r in rows:
        by_printer[r['printer'] or '—'].append(r['wait'])
    pr_avg = sorted(((k, sum(v) / len(v)) for k, v in by_printer.items()), key=lambda x: -x[1])[:15]
    lost = sum(w)
    ins = []
    if w:
        ins.append(f'Biten parçalar yazıcıda toplam {dur(lost)} bekledi; bu kadar süre yeni baskı başlatılamadı.')
        night = [x for h, v in by_hour.items() if h >= 20 or h < 7 for x in v]
        day = [x for h, v in by_hour.items() if 7 <= h < 20 for x in v]
        if night and day:
            ins.append(f'Gece biten parçalar ortalama {dur(sum(night) / len(night))}, gündüz bitenler {dur(sum(day) / len(day))} bekliyor.'
                       + (' Gece vardiyası / otomatik tabla boşaltma planı düşünülebilir.' if sum(night) / len(night) > 2 * sum(day) / len(day) else ''))
        ins.append(f'Parçaların %{pct(sum(1 for x in w if x > 60), len(w))} kadarı 1 saatten uzun bekledi.')
    else:
        ins.append('Bu dönemde yazıcının "bitti" bildirdiği ve teslim edilen parça yok.')
    return {
        'kpis': [{'icon': 'products', 'label': 'Ölçülen parça', 'value': len(w)}, {'icon': 'calendar', 'label': 'Ortalama', 'value': dur(sum(w) / len(w)) if w else '—'},
                 {'icon': 'calendar', 'label': 'Medyan', 'value': dur(median(w))},
                 {'icon': 'warning', 'label': 'Toplam kayıp', 'value': dur(lost), 'tone': 'alert' if lost > 600 else ''}],
        'insights': ins,
        'charts': [
            {'title': 'Bekleme süresi dağılımı', 'type': 'bar', 'labels': [x[0] for x in buckets], 'datasets': [{'label': 'Parça', 'data': hist}]},
            {'title': 'Bittiği saate göre ortalama bekleme (dk)', 'type': 'bar', 'labels': [f'{h:02d}' for h in range(24)],
             'datasets': [{'label': 'Ort. bekleme', 'data': [round(sum(by_hour[h]) / len(by_hour[h])) if by_hour.get(h) else 0 for h in range(24)]}]},
            {'title': 'Yazıcılara göre ortalama bekleme (dk)', 'type': 'hbar', 'wide': True, 'labels': [k for k, _ in pr_avg],
             'datasets': [{'label': 'Ort. bekleme', 'data': [round(v) for _, v in pr_avg]}]},
        ],
        'tables': [{'title': 'Parçalar', 'columns': [col('order_code', 'Sipariş'), col('part_id', 'Parça'), col('printer', 'Yazıcı'), col('done', 'Yazıcıda bitti'),
                                                     col('fin', 'Teslim'), col('wait_t', 'Bekleme', 'num'), col('user', 'Teslim eden')],
                    'rows': [{**r, 'done': fmt_dt(r['printer_done_at']), 'fin': fmt_dt(r['finished_at']), 'wait_t': dur(r['wait']), 'user': r['user'] or '—'}
                             for r in sorted(rows, key=lambda r: -r['wait'])]}],
    }


@report('montaj-performans', 'production', 'Montaj Performansı',
        'Montaj adımları, personel katkısı ve sipariş başına montaj süresi')
def montaj_performans(conn, p):
    a, b = rng(p)
    steps = db.rows(conn.execute(
        '''SELECT s.id, s.step, s.at, o.code FROM assembly_steps s JOIN orders o ON o.id = s.order_id WHERE s.at BETWEEN ? AND ?''', (a, b)))
    kind = lambda st: ('Bölüm' if st in ('SOL_KANAT', 'SAG_KANAT', 'GOVDE') else 'Elektronik' if st.startswith('ELEKTRONIK') else
                       'Birleştirme' if st == 'BIRLESTIRME' else 'Kapak' if st == 'KAPAK' else 'Kalibrasyon' if st == 'KALIBRASYON' else 'Saha deposu')
    staff = defaultdict(Counter)
    for r in conn.execute(f'''SELECT u.full_name, s.step FROM assembly_staff a JOIN users u ON u.id = a.user_id JOIN assembly_steps s ON s.id = a.step_id
                              WHERE s.at BETWEEN ? AND ?''', (a, b)):
        staff[r[0]][kind(r[1])] += 1
    kinds = ['Bölüm', 'Elektronik', 'Birleştirme', 'Kapak', 'Kalibrasyon']
    people = sorted(staff, key=lambda k: -sum(staff[k].values()))[:15]
    per_order = defaultdict(list)
    for s in steps:
        per_order[s['code']].append(s)
    orders = []
    for code, ss in per_order.items():
        ats = sorted(x['at'] for x in ss)
        cal = next((x['at'] for x in ss if x['step'] == 'KALIBRASYON'), None)
        orders.append({'code': code, 'steps': len(ss), 'first': fmt_dt(ats[0]), 'last': fmt_dt(ats[-1]),
                       'span': dur(mins(ats[0], ats[-1])), 'cal': fmt_dt(cal) if cal else '—'})
    daily = Counter(s['at'][:10] for s in steps)
    ds = days(p)
    ins = []
    if steps:
        ins.append(f'Dönemde {len(steps)} montaj adımı tamamlandı ({len(per_order)} uçakta).')
        if people:
            ins.append(f'En çok montaj adımında görev alan: {people[0]} ({sum(staff[people[0]].values())} adım).')
    else:
        ins.append('Bu dönemde montaj adımı yok.')
    return {
        'kpis': [{'icon': 'tools', 'label': 'Montaj adımı', 'value': len(steps)}, {'icon': 'flightlog', 'label': 'Uçak', 'value': len(per_order)},
                 {'icon': 'settings', 'label': 'Kalibrasyonu biten', 'value': sum(1 for s in steps if s['step'] == 'KALIBRASYON'), 'tone': 'ok'},
                 {'icon': 'users', 'label': 'Görev alan personel', 'value': len(staff)}],
        'insights': ins,
        'charts': [
            {'title': 'Personel katkısı (adım türüne göre)', 'type': 'hbar', 'stacked': True, 'wide': True, 'labels': people,
             'datasets': [{'label': k, 'data': [staff[pp].get(k, 0) for pp in people]} for k in kinds]},
            {'title': 'Günlük montaj adımı', 'type': 'bar', 'labels': day_labels(ds), 'datasets': [{'label': 'Adım', 'data': series(ds, daily)}]},
        ],
        'tables': [{'title': 'Uçak bazında montaj', 'columns': [col('code', 'Sipariş'), col('steps', 'Adım', 'num'), col('first', 'İlk adım'), col('last', 'Son adım'),
                                                                col('span', 'Montaj süresi', 'num'), col('cal', 'Kalibrasyon')], 'rows': orders}],
    }


@report('kapasite-tahmin', 'production', 'Üretim Kapasite ve Teslim Tahmini',
        'Kalan parçaların tükenme grafiği, son 7 günün üretim hızına göre tahmini bitiş ve açık siparişlerin teslim tahmini')
def kapasite_tahmin(conn, p):
    parts = db.rows(conn.execute(
        """SELECT op.finished_at, o.id AS oid, o.code, o.created_at, o.end_date FROM order_parts op JOIN orders o ON o.id = op.order_id
           WHERE o.status NOT IN ('HURDA') AND o.product_id IN (SELECT id FROM products WHERE type = 'MAMUL')"""))
    ds = days(p)
    remaining = []
    for d in ds:
        end = f'{d}T23:59:59'
        remaining.append(sum(1 for x in parts if x['created_at'] <= end and (not x['finished_at'] or x['finished_at'] > end)))
    today = date.today()
    wk = (today - timedelta(6)).isoformat()
    # hız: gerçek "üretim tamamlandı" kayıtları (sistem başlangıcında depoya toplu aktarılan parçalar sayılmaz)
    made7 = conn.execute("SELECT COUNT(*) FROM part_events WHERE event = 'URETIM_TAMAMLANDI' AND at >= ?", (f'{wk}T00:00:00',)).fetchone()[0]
    rate = made7 / 7
    left = sum(1 for x in parts if not x['finished_at'])
    eta_days = math.ceil(left / rate) if rate else None
    proj_labels, proj = [], []
    if rate and left:
        steps = min(eta_days, 60)
        for i in range(1, steps + 1):
            proj_labels.append((today + timedelta(i)).isoformat())
            proj.append(max(0, round(left - rate * i)))
    labels = day_labels(ds + proj_labels)
    # Açık siparişler: sıra ile (önce açılan önce) aynı hızla tamamlanırsa tahmini bitiş
    opens = defaultdict(lambda: {'left': 0, 'total': 0})
    meta = {}
    for x in parts:
        o = opens[x['oid']]
        o['total'] += 1
        o['left'] += 0 if x['finished_at'] else 1
        meta[x['oid']] = (x['code'], x['created_at'], x['end_date'])
    acc, forecast = 0, []
    for oid in sorted(opens, key=lambda k: meta[k][1]):
        o = opens[oid]
        if not o['left']:
            continue
        acc += o['left']
        eta = (today + timedelta(math.ceil(acc / rate))).isoformat() if rate else None
        code, _, end = meta[oid]
        forecast.append({'code': code, 'left': o['left'], 'total': o['total'], 'eta': eta, 'end': end,
                         'late': (date.fromisoformat(eta) - date.fromisoformat(end)).days if eta and end else None})
    late = [f for f in forecast if f['late'] and f['late'] > 0]
    fmt = lambda s: f'{s[8:10]}.{s[5:7]}.{s[:4]}' if s else '—'
    ins = [f'Son 7 günde günde ortalama {round(rate, 1)} parça üretildi; açık siparişlerde {left} parça kaldı.']
    if eta_days:
        ins.append(f'Bu hızla kalan tüm parçalar yaklaşık {eta_days} günde, {fmt((today + timedelta(eta_days)).isoformat())} civarında biter.')
    elif left:
        ins.append('Son 7 günde üretim olmadığı için bitiş tahmini yapılamıyor.')
    if late:
        ins.append(f'{len(late)} siparişin tahmini bitişi planlanan bitiş tarihini aşıyor (en çok {max(f["late"] for f in late)} gün). Yazıcı sayısı ya da vardiya artırılmalı.')
    return {
        'kpis': [{'icon': 'stock', 'label': 'Kalan parça', 'value': left}, {'icon': 'production', 'label': 'Günlük hız (7 gün)', 'value': round(rate, 1)},
                 {'icon': 'calendar', 'label': 'Tahmini bitiş', 'value': (today + timedelta(eta_days)).strftime('%d.%m') if eta_days else '—',
                  'sub': str((today + timedelta(eta_days)).year) if eta_days else None, 'tone': 'ok'},
                 {'icon': 'warning', 'label': 'Gecikecek sipariş', 'value': len(late), 'tone': 'alert' if late else ''}],
        'insights': ins,
        'charts': [{'title': 'Kalan parça — gerçekleşen ve tahmin', 'type': 'line', 'wide': True, 'labels': labels,
                    'datasets': [{'label': 'Kalan (gerçekleşen)', 'data': remaining + [None] * len(proj)},
                                 {'label': 'Tahmin', 'data': [None] * (len(remaining) - 1) + [left] + proj, 'dash': True}]},
                   {'title': 'Açık siparişlerde kalan parça', 'type': 'hbar', 'stacked': True, 'labels': [f['code'] for f in forecast],
                    'datasets': [{'label': 'Üretilen', 'data': [f['total'] - f['left'] for f in forecast]}, {'label': 'Kalan', 'data': [f['left'] for f in forecast]}]}],
        'tables': [{'title': 'Sipariş teslim tahmini', 'sub': 'Siparişler açılış sırasına göre, son 7 günün üretim hızıyla üretilirse',
                    'columns': [col('code', 'Sipariş'), col('prog', 'Üretilen', 'num'), col('left', 'Kalan', 'num'), col('eta_t', 'Tahmini üretim bitişi'),
                                col('end_t', 'Planlanan bitiş'), col('late_t', 'Fark', 'num')],
                    'rows': [{**f, 'prog': f'{f["total"] - f["left"]} / {f["total"]}', 'eta_t': fmt(f['eta']), 'end_t': fmt(f['end']),
                              'late_t': '—' if f['late'] is None else f'{f["late"]:+} gün'} for f in forecast]}],
    }


# ================================================================ SİPARİŞ

@report('siparis-durum', 'orders', 'Sipariş Durum Raporu', 'Tüm siparişlerin anlık durumu, ilerlemesi, firması ve gecikmeleri (dönemden bağımsız)')
def siparis_durum(conn, p):
    from .production import order_summaries
    orders = order_summaries(conn)
    today = date.today().isoformat()
    for o in orders:
        o['late'] = (date.fromisoformat(today) - date.fromisoformat(o['end_date'])).days if o['end_date'] and o['end_date'] < today and o['status'] not in ('TAMAMLANDI', 'HURDA', 'SAHA_ONAY') else 0
    open_ = [o for o in orders if o['status'] not in ('TAMAMLANDI', 'HURDA')]
    st = Counter(ORDER_TEXT.get(o['status'], o['status']) for o in orders)
    comp = Counter(o['company_name'] or 'Firma yok' for o in orders)
    late = [o for o in open_ if o['late'] > 0]
    ins = [f'{len(open_)} açık siparişin ortalama ilerlemesi %{round(sum(o["progress"] for o in open_) / len(open_)) if open_ else 0}.']
    if late:
        ins.append(f'{len(late)} sipariş bitiş tarihini geçti; en çok geciken {max(late, key=lambda o: o["late"])["code"]} ({max(o["late"] for o in late)} gün).')
    if comp:
        c = comp.most_common(1)[0]
        ins.append(f'Siparişlerin %{pct(c[1], len(orders))} kadarı {c[0]} için.')
    return {
        'kpis': [{'icon': 'orders', 'label': 'Sipariş', 'value': len(orders)}, {'icon': 'orders', 'label': 'Açık', 'value': len(open_)},
                 {'icon': 'production', 'label': 'Tamamlanan', 'value': sum(o['status'] == 'TAMAMLANDI' for o in orders), 'tone': 'ok'},
                 {'icon': 'warning', 'label': 'Geciken', 'value': len(late), 'tone': 'alert' if late else ''}],
        'insights': ins,
        'charts': [
            {'title': 'Durumlara göre', 'type': 'doughnut', 'labels': list(st), 'datasets': [{'label': 'Sipariş', 'data': list(st.values())}]},
            {'title': 'Firmalara göre', 'type': 'doughnut', 'labels': list(comp), 'datasets': [{'label': 'Sipariş', 'data': list(comp.values())}]},
            {'title': 'Açık siparişlerin ilerlemesi (%)', 'type': 'hbar', 'wide': True, 'labels': [o['code'] for o in open_],
             'datasets': [{'label': 'İlerleme', 'data': [o['progress'] for o in open_]}], 'max': 100},
        ],
        'tables': [{'title': 'Siparişler', 'columns': [col('code', 'Sipariş'), col('company_name', 'Firma'), col('product_name', 'Ürün'), col('status_t', 'Durum'),
                                                       col('progress_t', 'İlerleme', 'num'), col('created', 'Sipariş tarihi'), col('end_date', 'Bitiş'),
                                                       col('late_t', 'Gecikme', 'num'), col('queue_no', 'Kuyruk no')],
                    'rows': [{**o, 'status_t': ORDER_TEXT.get(o['status'], o['status']), 'progress_t': f'%{o["progress"]}', 'created': fmt_dt(o['created_at']),
                              'late_t': f'{o["late"]} gün' if o['late'] else '—', 'company_name': o['company_name'] or '—', 'end_date': o['end_date'] or '—',
                              'queue_no': o['queue_no'] or '—'} for o in orders]}],
    }


@report('cevrim-suresi', 'orders', 'Sipariş Çevrim Süreleri', 'Dönemde açılan her uçağın aşama aşama süresi: nerede zaman kaybediliyor?')
def cevrim_suresi(conn, p):
    a, b = rng(p)
    rows = db.rows(conn.execute('''SELECT id, code, created_at, status FROM orders WHERE product_id IN (SELECT id FROM products WHERE type = 'MAMUL')
                                   AND created_at BETWEEN ? AND ? ORDER BY id''', (a, b)))
    stages = ['Sipariş → üretim', 'Üretim', 'Depo onayı', 'Montaj', 'Kalibrasyon', 'Saha deposu']
    out = []
    for o in rows:
        first = conn.execute('''SELECT MIN(e.at) FROM part_events e JOIN order_parts op ON op.id = e.order_part_id
                                WHERE op.order_id = ? AND e.event = 'URETIME_BASLADI' ''', (o['id'],)).fetchone()[0]
        made = conn.execute("SELECT MAX(finished_at), SUM(state IN ('DEPO','MONTAJ')), COUNT(*) FROM order_parts WHERE order_id = ?", (o['id'],)).fetchone()
        appr = conn.execute('SELECT MAX(approved_at), SUM(approved_at IS NOT NULL) FROM order_parts WHERE order_id = ?', (o['id'],)).fetchone()
        st = {r[0]: r[1] for r in conn.execute('SELECT step, at FROM assembly_steps WHERE order_id = ?', (o['id'],))}
        asm_end = max((v for k, v in st.items() if k not in ('KALIBRASYON', 'SAHA_DEPO')), default=None)
        points = [o['created_at'], first, made[0] if made[1] == made[2] else None, appr[0] if appr[1] == made[2] else None,
                  asm_end, st.get('KALIBRASYON'), st.get('SAHA_DEPO')]
        seg = []
        for i in range(6):
            x, y = points[i], points[i + 1]
            seg.append(round(max(0, mins(x, y)) / 60, 1) if x and y else None)
        if any(v is not None for v in seg[1:]):
            out.append({'code': o['code'], 'seg': seg, 'total': round(sum(v for v in seg if v), 1)})
    avg = [round(sum(r['seg'][i] for r in out if r['seg'][i] is not None) / max(1, sum(1 for r in out if r['seg'][i] is not None)), 1) for i in range(6)]
    bott = stages[max(range(6), key=lambda i: avg[i])] if out and max(avg) > 0 else None
    done = [r for r in out if r['seg'][5] is not None]
    ins = []
    if out and bott:
        ins.append(f'Ortalamada en uzun aşama "{bott}" ({dur(max(avg) * 60)}); çevrim süresini kısaltmak için darboğaz burası.')
        if done:
            ins.append(f'Saha deposuna ulaşan {len(done)} uçağın ortalama toplam çevrim süresi {dur(sum(r["total"] for r in done) / len(done) * 60)}.')
    elif out:
        ins.append('Aşama zamanları henüz ayrışmıyor (kayıtlar aynı anda girilmiş); gerçek üretim ilerledikçe darboğaz görünür.')
    else:
        ins.append('Bu dönemde açılmış ve üretimi başlamış mamul siparişi yok.')
    return {
        'kpis': [{'icon': 'flightlog', 'label': 'Uçak', 'value': len(out)}, {'icon': 'warehouse', 'label': 'Saha deposuna ulaşan', 'value': len(done), 'tone': 'ok'},
                 {'icon': 'warning', 'label': 'Darboğaz', 'value': bott or '—'}, {'icon': 'production', 'label': 'Ort. üretim', 'value': dur(avg[1] * 60) if out else '—'}],
        'insights': ins,
        'charts': [
            {'title': 'Uçak bazında aşama süreleri (saat)', 'type': 'hbar', 'stacked': True, 'wide': True, 'labels': [r['code'] for r in out],
             'datasets': [{'label': s, 'data': [r['seg'][i] or 0 for r in out]} for i, s in enumerate(stages)]},
            {'title': 'Ortalama aşama süresi (saat)', 'type': 'bar', 'labels': stages, 'datasets': [{'label': 'Ortalama', 'data': avg}]},
        ],
        'tables': [{'title': 'Aşama süreleri', 'columns': [col('code', 'Sipariş')] + [col(f's{i}', s, 'num') for i, s in enumerate(stages)] + [col('tot', 'Toplam', 'num')],
                    'rows': [{'code': r['code'], **{f's{i}': dur(v * 60) if v is not None else '—' for i, v in enumerate(r['seg'])}, 'tot': dur(r['total'] * 60)} for r in out]}],
    }


# ================================================================ DEPO / STOK

@report('depo-onay', 'warehouse', 'Depo Onay Performansı', 'Günlük depo onayları, teslimden onaya geçen süre ve onaylayan kişiler')
def depo_onay(conn, p):
    a, b = rng(p)
    rows = db.rows(conn.execute('''SELECT op.finished_at, op.approved_at, u.full_name AS user FROM order_parts op LEFT JOIN users u ON u.id = op.approved_by
                                   WHERE op.approved_at BETWEEN ? AND ?''', (a, b)))
    lag = [mins(r['finished_at'], r['approved_at']) for r in rows if r['finished_at']]
    lag = [x for x in lag if x is not None and x >= 0]
    ds = days(p)
    daily = Counter(r['approved_at'][:10] for r in rows)
    by_day_lag = defaultdict(list)
    for r in rows:
        m = mins(r['finished_at'], r['approved_at']) if r['finished_at'] else None
        if m is not None and m >= 0:
            by_day_lag[r['approved_at'][:10]].append(m)
    users = Counter(r['user'] or '—' for r in rows)
    pending = conn.execute("SELECT COUNT(*) FROM order_parts WHERE state = 'DEPO' AND approved_at IS NULL").fetchone()[0]
    return {
        'kpis': [{'icon': 'warehouse', 'label': 'Onaylanan parça', 'value': len(rows), 'tone': 'ok'}, {'icon': 'calendar', 'label': 'Ort. onay süresi', 'value': dur(sum(lag) / len(lag)) if lag else '—'},
                 {'icon': 'calendar', 'label': 'Medyan', 'value': dur(median(lag))}, {'icon': 'warning', 'label': 'Şu an onay bekleyen', 'value': pending, 'tone': 'alert' if pending else ''}],
        'insights': [f'Teslim edilen parça ortalama {dur(sum(lag) / len(lag))} sonra depoda onaylandı.' if lag else 'Bu dönemde depo onayı yok.']
        + ([f'Şu an {pending} parça depo onayı bekliyor.'] if pending else []),
        'charts': [
            {'title': 'Günlük onay ve ortalama onay süresi', 'type': 'combo', 'wide': True, 'labels': day_labels(ds),
             'datasets': [{'label': 'Onaylanan parça', 'data': series(ds, daily)},
                          {'label': 'Ort. onay süresi (dk)', 'data': [round(sum(by_day_lag[d]) / len(by_day_lag[d])) if by_day_lag.get(d) else None for d in ds], 'line': True, 'axis': 'y2'}]},
            {'title': 'Onaylayan kişiler', 'type': 'doughnut', 'labels': list(users), 'datasets': [{'label': 'Parça', 'data': list(users.values())}]},
        ],
        'tables': [{'title': 'Onaylayanlar', 'columns': [col('user', 'Kişi'), col('n', 'Parça', 'num')], 'rows': [{'user': k, 'n': v} for k, v in users.most_common()]}],
    }


@report('stok-durum', 'stock', 'Yedek Parça Stok ve Kapasite', 'Stok, uçak başına ihtiyaç, stoğun kaç uçağa yettiği ve stok hareketleri')
def stok_durum(conn, p):
    from . import spares
    a, b = rng(p)
    rows = [r for r in spares.summary(conn) if r['per_aircraft']]
    # Uçak başına ihtiyaç: yarı mamullerin ait olduğu mamul başına toplam; birden çok mamulde (CAYMAZ, V2) en büyüğü
    parent = dict(conn.execute('SELECT id, parent_id FROM products'))
    for r in rows:
        per = Counter()
        for u in r['usages']:
            per[parent.get(u['parent_id']) or u['parent_id']] += u['qty']
        r['per_aircraft'] = max(per.values()) if per else r['per_aircraft']
        r['enough_for'] = r['stock'] // r['per_aircraft'] if r['per_aircraft'] else None
    cap = min((r['enough_for'] for r in rows if r['enough_for'] is not None), default=None)
    limit = min(rows, key=lambda r: r['enough_for'] if r['enough_for'] is not None else 1e9) if rows else None
    moves = db.rows(conn.execute('''SELECT m.created_at, m.qty, m.reason, p.code FROM spare_moves m JOIN products p ON p.id = m.spare_id
                                    WHERE m.created_at BETWEEN ? AND ? ORDER BY m.created_at DESC''', (a, b)))
    ds = days(p)
    used = Counter(m['created_at'][:10] for m in moves for _ in range(max(0, -m['qty'])))
    made = Counter(m['created_at'][:10] for m in moves for _ in range(max(0, m['qty'])))
    return {
        'kpis': [{'icon': 'stock', 'label': 'Sarf yedek parça', 'value': len(rows)}, {'icon': 'warehouse', 'label': 'Stok yeter (uçak)', 'value': cap if cap is not None else '—', 'tone': 'alert' if cap == 0 else 'ok'},
                 {'icon': 'warning', 'label': 'Kısıtlayan parça', 'value': limit['code'] if limit else '—'}, {'icon': 'refresh', 'label': 'Hareket', 'value': len(moves)}],
        'insights': [f'Mevcut stokla {cap} uçak daha monte edilebilir; kısıtlayan parça {limit["code"]} ({limit["stock"]} adet, uçak başına {limit["per_aircraft"]}).'
                     if limit else 'Uçak başına kullanımı tanımlı yedek parça yok.'],
        'charts': [
            {'title': 'Stok ve uçak başına ihtiyaç', 'type': 'bar', 'labels': [r['code'] for r in rows],
             'datasets': [{'label': 'Stok', 'data': [r['stock'] for r in rows]}, {'label': 'Uçak başına', 'data': [r['per_aircraft'] for r in rows]}]},
            {'title': 'Stoğun yettiği uçak sayısı', 'type': 'hbar', 'labels': [r['code'] for r in rows], 'datasets': [{'label': 'Uçak', 'data': [r['enough_for'] or 0 for r in rows]}]},
            {'title': 'Günlük stok girişi ve kullanım (adet)', 'type': 'bar', 'wide': True, 'labels': day_labels(ds),
             'datasets': [{'label': 'Giriş', 'data': series(ds, made)}, {'label': 'Kullanım', 'data': series(ds, used)}]},
        ],
        'tables': [{'title': 'Stok', 'columns': [col('code', 'Kod'), col('name', 'Ad'), col('stock', 'Stok', 'num'), col('per_aircraft', 'Uçak başına', 'num'),
                                                 col('enough', 'Yeter (uçak)', 'num'), col('open_orders', 'Açık sipariş', 'num')],
                    'rows': [{**r, 'enough': r['enough_for'] if r['enough_for'] is not None else '—'} for r in rows]},
                   {'title': 'Stok hareketleri', 'columns': [col('at', 'Zaman'), col('code', 'Parça'), col('qty', 'Adet', 'num'), col('reason', 'Açıklama')],
                    'rows': [{**m, 'at': fmt_dt(m['created_at']), 'qty': f'{m["qty"]:+}'} for m in moves]}],
    }


# ================================================================ YAZICI

@report('yazici-verim', 'printers', 'Yazıcı Kullanım ve Verimlilik', 'Yazıcı başına basılan parça, net baskı saati, doluluk ve hata oranı')
def yazici_verim(conn, p):
    a, b = rng(p)
    period_h = len(days(p)) * 24
    prs = {r[0]: r[1] for r in conn.execute('SELECT id, name FROM printers')}
    starts = Counter(r[0] for r in conn.execute("SELECT printer_id FROM part_events WHERE event = 'URETIME_BASLADI' AND at BETWEEN ? AND ?", (a, b)))
    errs = Counter(r[0] for r in conn.execute("SELECT printer_id FROM part_events WHERE event = 'HATA' AND at BETWEEN ? AND ?", (a, b)))
    done = Counter(r[0] for r in conn.execute("SELECT printer_id FROM part_events WHERE event = 'URETIM_TAMAMLANDI' AND at BETWEEN ? AND ?", (a, b)))
    # Baskı süresi: yazıcının bildirdiği net süre; yoksa yazıcıdaki başlangıç–bitiş; o da yoksa dosyanın planlanan süresi
    from .semis import print_info
    plan = {k: v.get('print_minutes') for k, v in print_info(conn).items()}
    net = defaultdict(float)
    measured = estimated = 0
    for pid, part, secs, ps, pd in conn.execute(
            '''SELECT printer_id, part_id, print_seconds, printer_started_at, printer_done_at FROM order_parts
               WHERE printer_id IS NOT NULL AND finished_at BETWEEN ? AND ?''', (a, b)):
        if secs:
            h, measured = secs / 3600, measured + 1
        elif ps and pd:
            h, measured = max(0, mins(ps, pd) or 0) / 60, measured + 1
        elif plan.get(part):
            h, estimated = plan[part] / 60, estimated + 1
        else:
            continue
        net[pid] += h
    rows = []
    for pid, name in prs.items():
        rows.append({'name': name, 'start': starts.get(pid, 0), 'done': done.get(pid, 0), 'err': errs.get(pid, 0),
                     'rate': pct(errs.get(pid, 0), starts.get(pid, 0)), 'hours': round(net.get(pid, 0), 1),
                     'util': min(100.0, pct(net.get(pid, 0), period_h))})   # çakışan kayıtlarda %100'ü aşmasın
    rows.sort(key=lambda r: -r['util'])
    used = [r for r in rows if r['start']]
    idle = [r['name'] for r in rows if not r['start']]
    fleet = pct(sum(r['hours'] for r in rows), period_h * max(1, len(rows)))
    worst = max(used, key=lambda r: (r['rate'], r['err'])) if used else None
    ins = [f'Filo ortalama doluluğu %{fleet}. Baskı süreleri: {measured} parçada yazıcıdan ölçülen, {estimated} parçada dosyanın planlanan süresi.']
    if used:
        ins.append(f'En yoğun yazıcı {rows[0]["name"]}: {rows[0]["hours"]} saat baskı (%{rows[0]["util"]}).')
        if worst and worst['err']:
            ins.append(f'En yüksek hata oranı {worst["name"]}: %{worst["rate"]} ({worst["err"]} hata / {worst["start"]} baskı).')
    if idle:
        ins.append(f'{len(idle)} yazıcı dönem boyunca hiç kullanılmadı: {", ".join(idle[:10])}{"…" if len(idle) > 10 else ""}.')
    top_rows = rows[:20]
    return {
        'kpis': [{'icon': 'printers', 'label': 'Yazıcı', 'value': len(rows)}, {'icon': 'production', 'label': 'Kullanılan', 'value': len(used), 'tone': 'ok'},
                 {'icon': 'fleet', 'label': 'Filo doluluğu', 'value': f'%{fleet}'},
                 {'icon': 'warning', 'label': 'Hiç kullanılmayan', 'value': len(idle), 'tone': 'alert' if idle else ''}],
        'insights': ins,
        'charts': [
            {'title': 'Doluluk oranı (%, en yoğun 20)', 'type': 'hbar', 'wide': True, 'labels': [r['name'] for r in top_rows],
             'datasets': [{'label': 'Doluluk %', 'data': [r['util'] for r in top_rows]}]},
            {'title': 'Baskı ve hata (en yoğun 20)', 'type': 'bar', 'stacked': True, 'wide': True, 'labels': [r['name'] for r in top_rows],
             'datasets': [{'label': 'Başarılı', 'data': [max(0, r['start'] - r['err']) for r in top_rows]}, {'label': 'Hata', 'data': [r['err'] for r in top_rows]}]},
        ],
        'tables': [{'title': 'Yazıcılar', 'columns': [col('name', 'Yazıcı'), col('start', 'Baskı', 'num'), col('done', 'Teslim', 'num'), col('err', 'Hata', 'num'),
                                                      col('rate_t', 'Hata oranı', 'num'), col('hours', 'Baskı (sa)', 'num'), col('util_t', 'Doluluk', 'num')],
                    'rows': [{**r, 'rate_t': f'%{r["rate"]}', 'util_t': f'%{r["util"]}'} for r in rows]}],
    }


# ================================================================ SAHA

def _summary(an):
    try:
        return (json.loads(an) or {}).get('summary') or {}
    except (TypeError, ValueError):
        return {}


@report('ucus-performans', 'field', 'Uçuş Performansı', 'Uçuş süreleri, mesafe, irtifa, hız ve batarya; uçuş bazında karşılaştırma')
def ucus_performans(conn, p):
    a, b = rng(p)
    rows = []
    for r in db.rows(conn.execute('''SELECT l.id, l.analysis, l.uploaded_at, l.aircraft, t.code AS task, o.code AS order_code, o.queue_no
                                     FROM flight_logs l LEFT JOIN field_tasks t ON t.id = l.task_id LEFT JOIN field_flights f ON f.id = l.flight_id
                                     LEFT JOIN orders o ON o.id = f.order_id WHERE l.status = 'TAMAM' ''')):
        s = _summary(r['analysis'])
        when = (s.get('takeoff_utc') or s.get('start_utc') or r['uploaded_at'] or '')[:10]
        if not s.get('flight_s') or not (p['from'] <= when <= p['to']):
            continue
        rows.append({'name': r['queue_no'] or r['order_code'] or r['aircraft'] or f'Log {r["id"]}', 'task': r['task'] or '—', 'date': when,
                     'min': round(s['flight_s'] / 60, 1), 'km': round((s.get('distance_m') or 0) / 1000, 1), 'alt': round(s.get('alt_max') or 0),
                     'gs': round(s.get('gs_max') or 0, 1), 'as_avg': round(s.get('as_avg') or 0, 1),
                     'bat': f'{s.get("bat_start_v", "—")} → {s.get("bat_end_v", "—")} V' if s.get('bat_start_v') else '—',
                     'range': round((s.get('max_home_m') or 0) / 1000, 1)})
    rows.sort(key=lambda r: r['date'])
    tot_min, tot_km = sum(r['min'] for r in rows), sum(r['km'] for r in rows)
    longest = max(rows, key=lambda r: r['min']) if rows else None
    return {
        'kpis': [{'icon': 'flightlog', 'label': 'Uçuş', 'value': len(rows)}, {'icon': 'calendar', 'label': 'Toplam uçuş', 'value': dur(tot_min)}, {'icon': 'radar', 'label': 'Toplam mesafe', 'value': f'{round(tot_km, 1)} km'},
                 {'icon': 'flightlog', 'label': 'En uzun', 'value': dur(longest['min']) if longest else '—'}],
        'insights': ([f'{len(rows)} uçuşta toplam {dur(tot_min)} havada kalındı ve {round(tot_km, 1)} km yol alındı; uçuş başına ortalama {dur(tot_min / len(rows))}.',
                      f'En uzun uçuş {longest["name"]} ({dur(longest["min"])}, {longest["km"]} km).'] if rows else ['Bu dönemde analiz edilmiş uçuş yok.']),
        'charts': [
            {'title': 'Uçuş süresi (dk) ve mesafe (km)', 'type': 'combo', 'wide': True, 'labels': [f'{r["name"]} {r["date"][8:10]}.{r["date"][5:7]}' for r in rows],
             'datasets': [{'label': 'Süre (dk)', 'data': [r['min'] for r in rows]}, {'label': 'Mesafe (km)', 'data': [r['km'] for r in rows], 'line': True, 'axis': 'y2'}]},
            {'title': 'En yüksek irtifa (m)', 'type': 'bar', 'labels': [r['name'] for r in rows], 'datasets': [{'label': 'İrtifa', 'data': [r['alt'] for r in rows]}]},
            {'title': 'Eve en uzak mesafe (km)', 'type': 'bar', 'labels': [r['name'] for r in rows], 'datasets': [{'label': 'Menzil', 'data': [r['range'] for r in rows]}]},
        ],
        'tables': [{'title': 'Uçuşlar', 'columns': [col('date', 'Tarih'), col('name', 'Uçak'), col('task', 'Görev'), col('min_t', 'Süre', 'num'), col('km', 'Mesafe (km)', 'num'),
                                                    col('alt', 'Maks. irtifa (m)', 'num'), col('range', 'Menzil (km)', 'num'), col('gs', 'Maks. yer hızı (m/s)', 'num'), col('bat', 'Batarya')],
                    'rows': [{**r, 'min_t': dur(r['min'])} for r in rows]}],
    }


@report('saha-masraf', 'field', 'Saha Görevleri ve Masraflar', 'Görevler, gidilen yol, uçuş sayısı; masrafların kategori ve görev dağılımı')
def saha_masraf(conn, p):
    a, b = rng(p)
    tasks = db.rows(conn.execute('''SELECT t.id, t.code, t.status, t.created_at, l.name AS location,
                                           (SELECT COUNT(*) FROM field_flights f WHERE f.task_id = t.id) AS flights,
                                           (SELECT SUM(end_km - start_km) FROM field_task_vehicles v WHERE v.task_id = t.id AND end_km >= start_km) AS km,
                                           (SELECT SUM(amount) FROM field_expenses e WHERE e.task_id = t.id) AS cost
                                    FROM field_tasks t LEFT JOIN field_locations l ON l.id = t.location_id WHERE t.created_at BETWEEN ? AND ? ORDER BY t.id''', (a, b)))
    exp = db.rows(conn.execute('SELECT category, amount, spent_on FROM field_expenses WHERE spent_on BETWEEN ? AND ?', (p['from'], p['to'])))
    cat = Counter()
    for e in exp:
        cat[e['category'] or 'Diğer'] += e['amount'] or 0
    total = sum(cat.values())
    km = sum(t['km'] or 0 for t in tasks)
    money = lambda v: f'{v:,.2f} ₺'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return {
        'kpis': [{'icon': 'field', 'label': 'Görev', 'value': len(tasks)}, {'icon': 'flightlog', 'label': 'Uçuş', 'value': sum(t['flights'] for t in tasks)},
                 {'icon': 'fleet', 'label': 'Gidilen yol', 'value': f'{round(km)} km'}, {'icon': 'finance', 'label': 'Toplam masraf', 'value': money(total)}],
        'insights': ([f'Masrafların %{pct(cat.most_common(1)[0][1], total)} kadarı "{cat.most_common(1)[0][0]}".'] if total else ['Bu dönemde masraf yok.'])
        + ([f'Kilometre başına masraf {money(total / km)}.'] if km and total else []),
        'charts': [
            {'title': 'Masraf kategorileri', 'type': 'doughnut', 'labels': list(cat), 'datasets': [{'label': '₺', 'data': [round(v, 2) for v in cat.values()]}]},
            {'title': 'Görev başına masraf (₺) ve yol (km)', 'type': 'combo', 'labels': [t['code'] for t in tasks],
             'datasets': [{'label': 'Masraf (₺)', 'data': [round(t['cost'] or 0, 2) for t in tasks]}, {'label': 'Yol (km)', 'data': [round(t['km'] or 0) for t in tasks], 'line': True, 'axis': 'y2'}]},
        ],
        'tables': [{'title': 'Görevler', 'columns': [col('code', 'Görev'), col('created', 'Tarih'), col('location', 'Yer'), col('status', 'Durum'), col('flights', 'Uçuş', 'num'),
                                                     col('km_t', 'Yol', 'num'), col('cost_t', 'Masraf', 'num')],
                    'rows': [{**t, 'created': fmt_dt(t['created_at']), 'location': t['location'] or '—', 'km_t': f'{round(t["km"] or 0)} km', 'cost_t': money(t['cost'] or 0)} for t in tasks]},
                   {'title': 'Masraf kategorileri', 'columns': [col('cat', 'Kategori'), col('amount', 'Tutar', 'num'), col('share', 'Pay', 'num')],
                    'rows': [{'cat': k, 'amount': money(v), 'share': f'%{pct(v, total)}'} for k, v in cat.most_common()]}],
    }


# ================================================================ FİRMA / EVRAK

@report('firma-iliski', 'companies', 'Firma İlişki Karnesi', 'Firma başına kişi, toplantı, not, evrak, sipariş ve misafir ziyareti; ilişki puanı')
def firma_iliski(conn, p):
    a, b = rng(p)
    q = lambda sql, args=(): dict(conn.execute(sql, args).fetchall())
    people = q('SELECT company_id, COUNT(*) FROM company_people GROUP BY company_id')
    meet = q('SELECT company_id, COUNT(*) FROM company_meetings WHERE meeting_at BETWEEN ? AND ? GROUP BY company_id', (a, b))
    notes = q("SELECT subject_id, COUNT(*) FROM crm_notes WHERE subject_type = 'company' AND created_at BETWEEN ? AND ? GROUP BY subject_id", (a, b))
    docs = q('SELECT dc.company_id, COUNT(*) FROM document_companies dc JOIN documents d ON d.id = dc.document_id WHERE d.uploaded_at BETWEEN ? AND ? GROUP BY dc.company_id', (a, b))
    orders = q('SELECT company_id, COUNT(*) FROM orders WHERE created_at BETWEEN ? AND ? GROUP BY company_id', (a, b))
    visits = q('''SELECT cp.company_id, COUNT(DISTINCT gp.visit_id) FROM guest_visit_people gp JOIN company_people cp ON cp.id = gp.person_id
                  JOIN guest_visits g ON g.id = gp.visit_id WHERE g.arrived_at BETWEEN ? AND ? GROUP BY cp.company_id''', (a, b))
    rows = []
    for cid, name in conn.execute('SELECT id, name FROM companies WHERE active = 1 AND is_supplier = 0'):
        r = {'name': name, 'people': people.get(cid, 0), 'meet': meet.get(cid, 0), 'notes': notes.get(cid, 0), 'docs': docs.get(cid, 0),
             'orders': orders.get(cid, 0), 'visits': visits.get(cid, 0)}
        r['score'] = r['meet'] * 3 + r['orders'] * 4 + r['visits'] * 2 + r['docs'] + r['notes']
        rows.append(r)
    rows.sort(key=lambda r: -r['score'])
    active = [r for r in rows if r['score']]
    cold = [r['name'] for r in rows if not r['score'] and r['people']]
    t10 = active[:10]
    return {
        'kpis': [{'icon': 'companies', 'label': 'Firma', 'value': len(rows)}, {'icon': 'crm', 'label': 'Dönemde etkileşim', 'value': len(active), 'tone': 'ok'},
                 {'icon': 'calendar', 'label': 'Toplantı', 'value': sum(r['meet'] for r in rows)},
                 {'icon': 'orders', 'label': 'Sipariş', 'value': sum(r['orders'] for r in rows)}],
        'insights': ([f'En yoğun ilişki {active[0]["name"]} (puan {active[0]["score"]}).'] if active else ['Bu dönemde firma etkileşimi yok.'])
        + ([f'Rehberde kişisi olup bu dönemde hiç etkileşim olmayan {len(cold)} firma var: {", ".join(cold[:6])}{"…" if len(cold) > 6 else ""}.'] if cold else []),
        'charts': [{'title': 'İlişki puanı (en yüksek 10)', 'type': 'hbar', 'stacked': True, 'wide': True, 'labels': [r['name'] for r in t10],
                    'datasets': [{'label': 'Toplantı ×3', 'data': [r['meet'] * 3 for r in t10]}, {'label': 'Sipariş ×4', 'data': [r['orders'] * 4 for r in t10]},
                                 {'label': 'Ziyaret ×2', 'data': [r['visits'] * 2 for r in t10]}, {'label': 'Evrak', 'data': [r['docs'] for r in t10]},
                                 {'label': 'Not', 'data': [r['notes'] for r in t10]}]}],
        'tables': [{'title': 'Firmalar', 'sub': 'Puan: toplantı ×3 + sipariş ×4 + misafir ziyareti ×2 + evrak + not',
                    'columns': [col('name', 'Firma'), col('people', 'Kişi', 'num'), col('meet', 'Toplantı', 'num'), col('notes', 'Not', 'num'), col('docs', 'Evrak', 'num'),
                                col('orders', 'Sipariş', 'num'), col('visits', 'Ziyaret', 'num'), col('score', 'Puan', 'num')], 'rows': rows}],
    }


@report('evrak', 'documents', 'Evrak ve İmza Raporu', 'Yüklenen evrak türleri, aylık dağılım ve bekleyen imzalar')
def evrak(conn, p):
    a, b = rng(p)
    docs = db.rows(conn.execute('SELECT kind, uploaded_at, size FROM documents WHERE uploaded_at BETWEEN ? AND ?', (a, b)))
    kinds = Counter(d['kind'] for d in docs)
    ds = days(p)
    daily = Counter(d['uploaded_at'][:10] for d in docs)
    sig = db.rows(conn.execute('''SELECT d.title, s.status, s.requested_at, s.decided_at, u.full_name AS signer FROM document_signatures s
                                  JOIN documents d ON d.id = s.document_id LEFT JOIN users u ON u.id = s.signer_id ORDER BY s.requested_at DESC LIMIT 300'''))
    pend = [s for s in sig if s['status'] == 'BEKLIYOR']
    lags = [mins(s['requested_at'], s['decided_at']) for s in sig if s['decided_at']]
    st_text = {'BEKLIYOR': 'Bekliyor', 'IMZALANDI': 'İmzalandı', 'REDDEDILDI': 'Reddedildi'}
    return {
        'kpis': [{'icon': 'documents', 'label': 'Yüklenen evrak', 'value': len(docs)}, {'icon': 'upload', 'label': 'Toplam boyut', 'value': f'{round(sum(d["size"] or 0 for d in docs) / 1024 ** 2)} MB'},
                 {'icon': 'warning', 'label': 'Bekleyen imza', 'value': len(pend), 'tone': 'alert' if pend else ''},
                 {'icon': 'calendar', 'label': 'Ort. imza süresi', 'value': dur(sum(lags) / len(lags)) if lags else '—'}],
        'insights': [f'En çok yüklenen tür: {kinds.most_common(1)[0][0]} ({kinds.most_common(1)[0][1]}).' if kinds else 'Bu dönemde evrak yüklenmedi.']
        + ([f'{len(pend)} imza talebi bekliyor; en eskisi {fmt_dt(min(s["requested_at"] for s in pend))}.'] if pend else []),
        'charts': [{'title': 'Evrak türleri', 'type': 'doughnut', 'labels': list(kinds), 'datasets': [{'label': 'Evrak', 'data': list(kinds.values())}]},
                   {'title': 'Günlük yükleme', 'type': 'bar', 'labels': day_labels(ds), 'datasets': [{'label': 'Evrak', 'data': series(ds, daily)}]}],
        'tables': [{'title': 'İmza talepleri', 'columns': [col('title', 'Evrak'), col('signer', 'İmzalayacak'), col('st', 'Durum'), col('req', 'İstendi'), col('dec', 'Karar')],
                    'rows': [{**s, 'st': st_text.get(s['status'], s['status']), 'req': fmt_dt(s['requested_at']), 'dec': fmt_dt(s['decided_at'])} for s in sig]}],
    }


# ================================================================ SEKRETERYA / GÜVENLİK

@report('misafir', 'secretariat', 'Misafir Raporu', 'Günlük misafir sayısı, geliş saatleri, ziyaret süreleri, firmalar ve görüşülen kişiler')
def misafir(conn, p):
    a, b = rng(p)
    visits = db.rows(conn.execute('''SELECT g.id, g.code, g.arrived_at, g.left_at, g.purpose,
                                            (SELECT COUNT(*) FROM guest_visit_people WHERE visit_id = g.id) AS n FROM guest_visits g
                                     WHERE g.arrived_at BETWEEN ? AND ? ORDER BY g.arrived_at''', (a, b)))
    comp = Counter()
    for r in conn.execute('''SELECT COALESCE(c.name, gp.company_text, 'Belirtilmemiş') FROM guest_visit_people gp JOIN guest_visits g ON g.id = gp.visit_id
                             LEFT JOIN company_people cp ON cp.id = gp.person_id LEFT JOIN companies c ON c.id = cp.company_id WHERE g.arrived_at BETWEEN ? AND ?''', (a, b)):
        comp[r[0]] += 1
    hosts = Counter(r[0] for r in conn.execute('''SELECT u.full_name FROM guest_visit_hosts h JOIN users u ON u.id = h.user_id
                                                  JOIN guest_visits g ON g.id = h.visit_id WHERE g.arrived_at BETWEEN ? AND ?''', (a, b)))
    ds = days(p)
    ppl = Counter()
    for v in visits:
        ppl[v['arrived_at'][:10]] += v['n']
    stays = [mins(v['arrived_at'], v['left_at']) for v in visits if v['left_at']]
    hours = Counter(int(v['arrived_at'][11:13]) for v in visits)
    return {
        'kpis': [{'icon': 'guest', 'label': 'Ziyaret (grup)', 'value': len(visits)}, {'icon': 'person', 'label': 'Misafir kişi', 'value': sum(v['n'] for v in visits)},
                 {'icon': 'calendar', 'label': 'Ort. ziyaret süresi', 'value': dur(sum(stays) / len(stays)) if stays else '—'},
                 {'icon': 'companies', 'label': 'Farklı firma', 'value': len(comp)}],
        'insights': ([f'En yoğun geliş saati {hours.most_common(1)[0][0]:02d}:00; en çok gelen firma {comp.most_common(1)[0][0]}.'] if visits and comp else
                     ['Bu dönemde misafir kaydı yok.']),
        'charts': [{'title': 'Günlük misafir (kişi)', 'type': 'bar', 'wide': True, 'labels': day_labels(ds), 'datasets': [{'label': 'Kişi', 'data': series(ds, ppl)}]},
                   {'title': 'Firmalar', 'type': 'hbar', 'labels': [k for k, _ in top(comp, 10)], 'datasets': [{'label': 'Kişi', 'data': [v for _, v in top(comp, 10)]}]},
                   {'title': 'Görüşülen kişiler', 'type': 'hbar', 'labels': [k for k, _ in top(hosts, 10)], 'datasets': [{'label': 'Ziyaret', 'data': [v for _, v in top(hosts, 10)]}]},
                   {'title': 'Geliş saatleri', 'type': 'bar', 'labels': [f'{h:02d}' for h in range(24)], 'datasets': [{'label': 'Ziyaret', 'data': [hours.get(h, 0) for h in range(24)]}]}],
        'tables': [{'title': 'Ziyaretler', 'columns': [col('code', 'Kod'), col('arr', 'Geliş'), col('left', 'Çıkış'), col('n', 'Kişi', 'num'), col('stay', 'Süre', 'num'), col('purpose', 'Amaç')],
                    'rows': [{**v, 'arr': fmt_dt(v['arrived_at']), 'left': fmt_dt(v['left_at']), 'stay': dur(mins(v['arrived_at'], v['left_at'])) if v['left_at'] else 'İçeride',
                              'purpose': v['purpose'] or '—'} for v in visits]}],
    }


@report('kargo', 'secretariat', 'Kargo Raporu', 'Kargo firmaları, kişi başına kargo ve teslim alma süreleri')
def kargo(conn, p):
    a, b = rng(p)
    rows = db.rows(conn.execute('''SELECT k.carrier, k.created_at, k.delivered_at, u.full_name AS who FROM cargo k JOIN users u ON u.id = k.recipient_id
                                   WHERE k.created_at BETWEEN ? AND ?''', (a, b)))
    car = Counter(r['carrier'] or 'Belirtilmemiş' for r in rows)
    who = Counter(r['who'] for r in rows)
    lag = [mins(r['created_at'], r['delivered_at']) for r in rows if r['delivered_at']]
    ds = days(p)
    daily = Counter(r['created_at'][:10] for r in rows)
    waiting = sum(1 for r in rows if not r['delivered_at'])
    return {
        'kpis': [{'icon': 'cargo', 'label': 'Kargo', 'value': len(rows)}, {'icon': 'warning', 'label': 'Bekleyen', 'value': waiting, 'tone': 'alert' if waiting else ''},
                 {'icon': 'calendar', 'label': 'Ort. teslim alma', 'value': dur(sum(lag) / len(lag)) if lag else '—'}, {'icon': 'companies', 'label': 'Kargo firması', 'value': len(car)}],
        'insights': [f'En çok kargo {car.most_common(1)[0][0]} ile geldi; en çok kargosu olan {who.most_common(1)[0][0]}.'] if rows else ['Bu dönemde kargo yok.'],
        'charts': [{'title': 'Kargo firmaları', 'type': 'doughnut', 'labels': list(car), 'datasets': [{'label': 'Kargo', 'data': list(car.values())}]},
                   {'title': 'Kişiler', 'type': 'hbar', 'labels': [k for k, _ in top(who, 10)], 'datasets': [{'label': 'Kargo', 'data': [v for _, v in top(who, 10)]}]},
                   {'title': 'Günlük kargo', 'type': 'bar', 'wide': True, 'labels': day_labels(ds), 'datasets': [{'label': 'Kargo', 'data': series(ds, daily)}]}],
        'tables': [{'title': 'Kişi bazında', 'columns': [col('who', 'Kişi'), col('n', 'Kargo', 'num')], 'rows': [{'who': k, 'n': v} for k, v in who.most_common()]}],
    }


@report('arac-giris', 'security', 'Araç Giriş / Çıkış Analizi', 'Gün × saat yoğunluk haritası, kalış süreleri, sık gelen plakalar')
def arac_giris(conn, p):
    a, b = rng(p)
    rows = db.rows(conn.execute('SELECT plate, entered_at, exited_at FROM vehicle_visits WHERE entered_at BETWEEN ? AND ?', (a, b)))
    stays = [mins(r['entered_at'], r['exited_at']) for r in rows if r['exited_at']]
    plates = Counter(r['plate'] for r in rows)
    ds = days(p)
    daily = Counter(r['entered_at'][:10] for r in rows)
    hm = heat([r['entered_at'] for r in rows])
    pk = peak_of(hm)
    long_ = [r for r in rows if r['exited_at'] and (mins(r['entered_at'], r['exited_at']) or 0) > 8 * 60]
    return {
        'kpis': [{'icon': 'fleet', 'label': 'Giriş', 'value': len(rows)}, {'icon': 'fleet', 'label': 'Farklı araç', 'value': len(plates)},
                 {'icon': 'calendar', 'label': 'Ort. kalış', 'value': dur(sum(stays) / len(stays)) if stays else '—'},
                 {'icon': 'warning', 'label': 'Hâlâ içeride', 'value': sum(1 for r in rows if not r['exited_at'])}],
        'insights': ([f'En yoğun zaman {DAYS_TR[pk[1]]} {pk[2]:02d}:00 ({pk[0]} giriş).',
                      f'En sık gelen araç {plates.most_common(1)[0][0]} ({plates.most_common(1)[0][1]} kez).']
                     + ([f'{len(long_)} araç 8 saatten uzun içeride kaldı.'] if long_ else [])) if rows else ['Bu dönemde araç kaydı yok.'],
        'charts': [{'title': 'Giriş yoğunluğu (gün × saat)', 'type': 'heat', 'wide': True, 'heat': hm},
                   {'title': 'Günlük giriş', 'type': 'bar', 'labels': day_labels(ds), 'datasets': [{'label': 'Araç', 'data': series(ds, daily)}]},
                   {'title': 'Sık gelen plakalar', 'type': 'hbar', 'labels': [k for k, _ in top(plates, 10)], 'datasets': [{'label': 'Giriş', 'data': [v for _, v in top(plates, 10)]}]}],
        'tables': [{'title': 'Plakalar', 'columns': [col('plate', 'Plaka'), col('n', 'Giriş', 'num'), col('avg', 'Ort. kalış', 'num'), col('last', 'Son giriş')],
                    'rows': [{'plate': k, 'n': v, 'avg': dur(median([mins(r['entered_at'], r['exited_at']) for r in rows if r['plate'] == k and r['exited_at']])),
                              'last': fmt_dt(max(r['entered_at'] for r in rows if r['plate'] == k))} for k, v in plates.most_common()]}],
    }


@report('kamera-yoklama', 'security', 'Kamera Yüz Tanıma ve Yoklama', 'Kişi bazında kameralarda ilk / son görülme (günlük yoklama), tanınan / tanımsız yüzler')
def kamera_yoklama(conn, p):
    a, b = rng(p)
    rows = db.rows(conn.execute('''SELECT s.at, c.name AS camera, g.id AS gid, COALESCE(u.full_name, pp.full_name) AS who
                                   FROM face_sightings s JOIN face_groups g ON g.id = s.group_id LEFT JOIN cameras c ON c.id = s.camera_id
                                   LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people pp ON pp.id = g.person_id
                                   WHERE s.at BETWEEN ? AND ? ORDER BY s.at''', (a, b)))
    ds = days(p)
    known = Counter(r['at'][:10] for r in rows if r['who'])
    unknown = Counter(r['at'][:10] for r in rows if not r['who'])
    cams = Counter(r['camera'] or '—' for r in rows)
    att = {}
    for r in rows:
        if not r['who']:
            continue
        k = (r['who'], r['at'][:10])
        f, l_, n = att.get(k, (r['at'], r['at'], 0))
        att[k] = (min(f, r['at']), max(l_, r['at']), n + 1)
    table = [{'who': k[0], 'day': f'{k[1][8:10]}.{k[1][5:7]}.{k[1][:4]}', 'first': v[0][11:16], 'last': v[1][11:16], 'span': dur(mins(v[0], v[1])), 'n': v[2]}
             for k, v in sorted(att.items(), key=lambda kv: (kv[0][1], kv[0][0]))]
    unknown_groups = len({r['gid'] for r in rows if not r['who']})
    return {
        'kpis': [{'icon': 'camera', 'label': 'Görülme', 'value': len(rows)}, {'icon': 'person', 'label': 'Tanınan kişi', 'value': len({r['who'] for r in rows if r['who']}), 'tone': 'ok'},
                 {'icon': 'warning', 'label': 'Tanımsız kişi grubu', 'value': unknown_groups, 'tone': 'alert' if unknown_groups else ''}, {'icon': 'cameras', 'label': 'Kamera', 'value': len(cams)}],
        'insights': [f'{unknown_groups} tanımsız kişi grubu var; Güvenlik → Tanımlanamayan Kişiler\'den kişiye atanırsa yoklama tablosuna girer.'] if rows else
        ['Bu dönemde kamera yüz kaydı yok (kamera eklenmemiş ya da yüz tanıma kapalı).'],
        'charts': [{'title': 'Günlük görülme', 'type': 'bar', 'stacked': True, 'wide': True, 'labels': day_labels(ds),
                    'datasets': [{'label': 'Tanınan', 'data': series(ds, known)}, {'label': 'Tanımsız', 'data': series(ds, unknown)}]},
                   {'title': 'Kameralar', 'type': 'doughnut', 'labels': list(cams), 'datasets': [{'label': 'Görülme', 'data': list(cams.values())}]},
                   {'title': 'Görülme yoğunluğu (gün × saat)', 'type': 'heat', 'wide': True, 'heat': heat([r['at'] for r in rows])}],
        'tables': [{'title': 'Günlük yoklama (kameralara göre ilk / son görülme)', 'columns': [col('day', 'Gün'), col('who', 'Kişi'), col('first', 'İlk', 'num'),
                                                                                              col('last', 'Son', 'num'), col('span', 'Aralık', 'num'), col('n', 'Görülme', 'num')], 'rows': table}],
    }


# ================================================================ YÖNETİM / ÜRÜN

@report('kullanici-aktivite', 'admin', 'Kullanıcı Aktivitesi', 'Girişler, başarısız girişler, kullanıcı bazında işlem sayısı ve saatlik kullanım')
def kullanici_aktivite(conn, p):
    a, b = rng(p)
    logins = db.rows(conn.execute('SELECT username, success, ip, at FROM login_logs WHERE at BETWEEN ? AND ?', (a, b)))
    acts = db.rows(conn.execute('SELECT u.full_name AS who, a.action, a.at FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id WHERE a.at BETWEEN ? AND ?', (a, b)))
    ds = days(p)
    ok = Counter(l['at'][:10] for l in logins if l['success'])
    bad = Counter(l['at'][:10] for l in logins if not l['success'])
    who = Counter(x['who'] or 'Sistem' for x in acts)
    action = Counter(x['action'] for x in acts)
    fails = Counter(l['username'] for l in logins if not l['success'])
    return {
        'kpis': [{'icon': 'security', 'label': 'Başarılı giriş', 'value': sum(ok.values()), 'tone': 'ok'}, {'icon': 'warning', 'label': 'Başarısız giriş', 'value': sum(bad.values()), 'tone': 'alert' if bad else ''},
                 {'icon': 'terminal', 'label': 'İşlem', 'value': len(acts)}, {'icon': 'users', 'label': 'Aktif kullanıcı', 'value': len({x['who'] for x in acts if x['who']})}],
        'insights': ([f'En çok işlem yapan {who.most_common(1)[0][0]} ({who.most_common(1)[0][1]} işlem).'] if acts else [])
        + ([f'Başarısız girişlerin çoğu "{fails.most_common(1)[0][0]}" kullanıcı adıyla ({fails.most_common(1)[0][1]}); şifre unutulmuş ya da deneme olabilir.'] if fails else []),
        'charts': [{'title': 'Günlük giriş', 'type': 'bar', 'stacked': True, 'wide': True, 'labels': day_labels(ds),
                    'datasets': [{'label': 'Başarılı', 'data': series(ds, ok)}, {'label': 'Başarısız', 'data': series(ds, bad)}]},
                   {'title': 'Kullanıcı bazında işlem', 'type': 'hbar', 'labels': [k for k, _ in top(who)], 'datasets': [{'label': 'İşlem', 'data': [v for _, v in top(who)]}]},
                   {'title': 'İşlem saatleri', 'type': 'heat', 'wide': True, 'heat': heat([x['at'] for x in acts])}],
        'tables': [{'title': 'En sık işlemler', 'columns': [col('action', 'İşlem'), col('n', 'Sayı', 'num')], 'rows': [{'action': k, 'n': v} for k, v in action.most_common(40)]}],
    }


@report('personel-karne', 'admin', 'Personel Performans Karnesi',
        'Kişi başına modüller arası katkı: üretim, teslim, hata kaydı, depo onayı, montaj, araç ve misafir kayıtları')
def personel_karne(conn, p):
    a, b = rng(p)
    q = lambda sql: Counter({r[0]: r[1] for r in conn.execute(sql, (a, b)) if r[0]})
    cols = [
        ('start', 'Üretime başlatma', q("SELECT user_id, COUNT(*) FROM part_events WHERE event = 'URETIME_BASLADI' AND at BETWEEN ? AND ? GROUP BY user_id")),
        ('done', 'Depoya teslim', q("SELECT user_id, COUNT(*) FROM part_events WHERE event = 'URETIM_TAMAMLANDI' AND at BETWEEN ? AND ? GROUP BY user_id")),
        ('err', 'Hata kaydı', q("SELECT user_id, COUNT(*) FROM part_events WHERE event = 'HATA' AND at BETWEEN ? AND ? GROUP BY user_id")),
        ('appr', 'Depo onayı', q("SELECT user_id, COUNT(*) FROM part_events WHERE event = 'DEPO_ONAY' AND at BETWEEN ? AND ? GROUP BY user_id")),
        ('asm', 'Montaj adımı', q('SELECT a.user_id, COUNT(*) FROM assembly_staff a JOIN assembly_steps s ON s.id = a.step_id WHERE s.at BETWEEN ? AND ? GROUP BY a.user_id')),
        ('veh', 'Araç kaydı', q('SELECT entered_by, COUNT(*) FROM vehicle_visits WHERE entered_at BETWEEN ? AND ? GROUP BY entered_by')),
        ('vis', 'Misafir kaydı', q('SELECT created_by, COUNT(*) FROM guest_visits WHERE created_at BETWEEN ? AND ? GROUP BY created_by')),
    ]
    names = dict(conn.execute('SELECT id, full_name FROM users'))
    uids = sorted({u for _, _, c in cols for u in c}, key=lambda u: -sum(c.get(u, 0) for _, _, c in cols))
    rows = [{'name': names.get(u, '—'), **{k: c.get(u, 0) for k, _, c in cols}, 'total': sum(c.get(u, 0) for _, _, c in cols)} for u in uids]
    t15 = rows[:15]
    ins = []
    if rows:
        ins.append(f'Dönemin en yüksek katkısı {rows[0]["name"]}: toplam {rows[0]["total"]} kayıt.')
        for k, label, c in cols:
            if c:
                u, n = c.most_common(1)[0]
                ins.append(f'{label}: en çok {names.get(u, "—")} ({n}).')
    else:
        ins.append('Bu dönemde kayıt yok.')
    return {
        'kpis': [{'icon': 'users', 'label': 'Katkı veren kişi', 'value': len(rows)}] + [{'icon': 'production', 'label': label, 'value': sum(c.values())} for _, label, c in cols[:3]],
        'insights': ins[:6],
        'charts': [{'title': 'Kişi başına katkı (en yüksek 15)', 'type': 'hbar', 'stacked': True, 'wide': True, 'labels': [r['name'] for r in t15],
                    'datasets': [{'label': label, 'data': [r[k] for r in t15]} for k, label, _ in cols]}],
        'tables': [{'title': 'Personel karnesi', 'columns': [col('name', 'Kişi')] + [col(k, label, 'num') for k, label, _ in cols] + [col('total', 'Toplam', 'num')],
                    'rows': rows}],
    }


@report('urun-baski-listesi', 'products', 'Ürün Parça ve Baskı Listesi', 'Mamul başına parçalar, yazıcı dosyaları, baskı süreleri ve yedek stok (baskı referansı)')
def urun_baski_listesi(conn, p):
    from . import catalogs
    from .semis import print_info
    info = print_info(conn)
    stock = {r[0][len('part-'):]: r[1] for r in conn.execute("SELECT schema, id FROM products WHERE schema LIKE 'part-%'")}
    from .spares import stock as stock_of
    tables, labels, data = [], [], []
    for pid, name, schema in conn.execute("SELECT id, name, schema FROM products WHERE type = 'MAMUL' AND schema != 'custom' AND active = 1 ORDER BY id").fetchall():
        rows = []
        for part in catalogs.part_ids(schema):
            i = info.get(part, {})
            rows.append({'part': part, 'file': i.get('print_file') or '—', 'min': i.get('print_minutes'), 'min_t': dur(i.get('print_minutes')),
                         'stock': stock_of(conn, stock[part]) if part in stock else '—'})
        rows.sort(key=lambda r: -(r['min'] or 0))
        longest = rows[0] if rows else None
        labels.append(name)
        data.append(round(max((r['min'] or 0) for r in rows) / 60, 1) if rows else 0)
        tables.append({'title': f'{name} — {len(rows)} parça', 'sub': f'En uzun parça {longest["part"]} ({longest["min_t"]}); tek uçağın en kısa baskı süresi bu parçayla sınırlıdır.' if longest else None,
                       'columns': [col('part', 'Parça'), col('file', 'Yazıcı dosyası'), col('min_t', 'Baskı süresi', 'num'), col('stock', 'Yedek stok', 'num')], 'rows': rows})
    return {'kpis': [{'icon': 'products', 'label': 'Mamul', 'value': len(tables)}], 'insights': ['Paralel yazıcılarla bir uçağın en kısa baskı süresi, en uzun parçanın süresidir.'],
            'charts': [{'title': 'En uzun parça baskı süresi (saat)', 'type': 'bar', 'labels': labels, 'datasets': [{'label': 'Saat', 'data': data}]}], 'tables': tables}


def visible(user):
    return [r for r in REPORTS if r['module'] in user['modules']]
