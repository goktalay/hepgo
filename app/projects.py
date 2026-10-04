"""Proje Yönetimi — iş mantığı.

Proje bir GRUPLAMADIR: finansal hareketler (fin_txns), satış / alış faturaları (invoices) ve Satın Alma belgeleri
(material_docs) projeye etiketlenir (project_tags). Proje silinince yalnızca etiketler kalkar; finansal veri silinmez.

- Her hareket için karar sorulur: "Projesiz" (project_id NULL etiket), tek proje, tutar bölüşümü ya da kalem bazında
  (alış faturasındaki malzemeler / muhasebe satırları). Kalemlerden seçilmeyen kalan kısım otomatik "projesiz" olur.
- Nitelik (nature): gelir | gider (kâr-zarara girer) | odeme (tahsilat / ödeme: nakit akışı, kâr-zarar dışı — aynı tutar
  fatura ve ödeme olarak iki kez sayılmasın).
- Net (KDV hariç) tutar faturanın muhasebe fişinden (fin_ledger.doc_no) hesaplanır; fiş yoksa brüt tutar kullanılır.
"""
import re
from collections import Counter, defaultdict
from datetime import date

from . import db
from .fleet import fold, squash

KINDS = {'arge': 'Ar-Ge projesi', 'musteri': 'Müşteri projesi', 'ic': 'İç proje', 'destek': 'Destekli proje (TÜBİTAK / KOSGEB…)'}
STATUS = {'fikir': 'Fikir', 'planlama': 'Planlama', 'devam': 'Devam ediyor', 'beklemede': 'Beklemede', 'tamamlandi': 'Tamamlandı', 'iptal': 'İptal'}
NATURE = {'gelir': 'Gelir', 'gider': 'Gider', 'odeme': 'Tahsilat / ödeme'}
SKIP_CATS = {'Devir / açılış', 'Virman'}
COST_PREFIX = ('15', '25', '26', '62', '63', '64', '65', '66', '68', '7')
REV_PREFIX = ('6',)


# ---------------- Hareket evreni ----------------
def _txn_rows(conn, where='1=1', args=()):
    return db.rows(conn.execute(f'''SELECT t.id, t.date, t.direction, t.amount, t.category, t.description, t.doc_no, t.counter_id, t.mikro_ref, t.mikro_project,
                                    a.id AS account_id, a.name AS account_name, a.kind AS account_kind, a.company_id
                                    FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id WHERE {where}''', args))


def _cari_docs(conn):
    """Cari hareketlerinin belge noları (kasa / banka hareketi bunlardan biriyle eşleşirse ödeme / tahsilattır)."""
    return {(r[0], r[1]) for r in conn.execute("SELECT t.doc_no, t.date FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id WHERE a.kind = 'cari' AND t.doc_no IS NOT NULL")}


def _invoice_numbers(conn):
    return {r[0] for r in conn.execute('SELECT number FROM invoices WHERE number IS NOT NULL')}


def txn_nature(t, cari_docs, inv_numbers):
    if t['category'] in SKIP_CATS or t['counter_id']:
        return None   # açılış / kendi hesapları arası virman: projeye sorulmaz
    if t['account_kind'] == 'cari':
        if t['category'] == 'Fatura' or (t['doc_no'] and t['doc_no'] in inv_numbers):
            return 'gelir' if t['direction'] == 'in' else 'gider'
        return 'odeme'
    if t['doc_no'] and (t['doc_no'], t['date']) in cari_docs:
        return 'odeme'   # carinin ödemesi / tahsilatı (karşılığı cari hareketi)
    return 'gelir' if t['direction'] == 'in' else 'gider'


def _ledger_by_doc(conn, docs):
    out = defaultdict(list)
    docs = [d for d in set(docs) if d]
    for i in range(0, len(docs), 400):
        part = docs[i:i + 400]
        for r in conn.execute(f'''SELECT l.guid, l.doc_no, l.account, c.name, l.description, l.debit, l.credit, l.mikro_project FROM fin_ledger l
                                  LEFT JOIN fin_coa c ON c.code = l.account WHERE l.doc_no IN ({",".join("?" * len(part))})''', part):
            out[r[1]].append({'guid': r[0], 'account': r[2], 'account_name': r[3], 'description': r[4], 'debit': r[5] or 0, 'credit': r[6] or 0,
                              'mikro_project': r[7]})
    return out


def net_of(lines, nature, gross):
    """KDV hariç tutar: gelirde 6'lı hesap alacakları, giderde stok / gider / duran varlık borçları."""
    if lines and nature == 'gelir':
        n = sum(l['credit'] for l in lines if l['account'].startswith(REV_PREFIX))
        if n > 0:
            return round(n, 2), True
    if lines and nature == 'gider':
        n = sum(l['debit'] for l in lines if l['account'].startswith(COST_PREFIX))
        if n > 0:
            return round(n, 2), True
    return round(gross, 2), False


def universe(conn, since='', until=''):
    """Projeye sorulacak tüm hareketler (txn + eşleşmeyen fatura / belge), nitelik ve brüt / net tutarla."""
    cari_docs, inv_numbers = _cari_docs(conn), _invoice_numbers(conn)
    w, a = ['1=1'], []
    if since:
        w.append('t.date >= ?'); a.append(since)
    if until:
        w.append('t.date <= ?'); a.append(until)
    out = []
    txns = _txn_rows(conn, ' AND '.join(w), a)
    txn_docs = {t['doc_no'] for t in txns if t['doc_no']}
    ledger = _ledger_by_doc(conn, [t['doc_no'] for t in txns])
    for t in txns:
        nat = txn_nature(t, cari_docs, inv_numbers)
        if not nat:
            continue
        net, exact = net_of(ledger.get(t['doc_no']) if nat != 'odeme' else None, nat, t['amount'])
        out.append({'source': 'txn', 'ref': t['id'], 'date': t['date'], 'nature': nat, 'amount': round(t['amount'], 2), 'net': net, 'net_exact': exact,
                    'title': t['description'] or t['category'] or '—', 'account': t['account_name'], 'account_kind': t['account_kind'],
                    'company_id': t['company_id'], 'account_id': t['account_id'], 'doc_no': t['doc_no'], 'category': t['category'], 'mikro': bool(t['mikro_ref']),
                    'direction': t['direction'], 'mikro_project': t['mikro_project']})
    dw, da = ['number IS NOT NULL'], []
    if since:
        dw.append('invoice_date >= ?'); da.append(since)
    for r in db.rows(conn.execute(f'SELECT id, kind, number, company_name, invoice_date, subtotal, total FROM invoices WHERE {" AND ".join(dw)}', da)):
        if r['number'] in txn_docs:
            continue   # aynı belge cari hareketi olarak zaten var
        out.append({'source': 'invoice', 'ref': r['id'], 'date': r['invoice_date'] or '', 'nature': 'gelir' if r['kind'] == 'satis' else 'gider',
                    'amount': round(r['total'] or 0, 2), 'net': round(r['subtotal'] or r['total'] or 0, 2), 'net_exact': True,
                    'title': f"{'Satış' if r['kind'] == 'satis' else 'Alış'} faturası", 'account': r['company_name'], 'account_kind': 'fatura',
                    'company_id': None, 'account_id': None, 'doc_no': r['number'], 'category': 'Fatura', 'mikro': False, 'mikro_project': None})
    for r in db.rows(conn.execute('''SELECT d.id, d.number, COALESCE(d.doc_date, substr(d.created_at, 1, 10)) AS date, d.amount, c.name AS company,
                                     (SELECT SUM(qty * COALESCE(unit_price, 0)) FROM material_moves m WHERE m.doc_id = d.id) AS lines_total
                                     FROM material_docs d LEFT JOIN companies c ON c.id = d.company_id WHERE d.kind = 'FATURA' ''')):
        if (r['number'] and r['number'] in txn_docs) or (since and r['date'] < since):
            continue
        gross = r['amount'] or r['lines_total'] or 0
        out.append({'source': 'mdoc', 'ref': r['id'], 'date': r['date'], 'nature': 'gider', 'amount': round(gross, 2), 'net': round(r['lines_total'] or gross, 2),
                    'net_exact': bool(r['lines_total']), 'title': 'Satın Alma faturası', 'account': r['company'], 'account_kind': 'fatura',
                    'company_id': None, 'account_id': None, 'doc_no': r['number'], 'category': 'Fatura', 'mikro': False, 'mikro_project': None})
    return out


def tags_by_source(conn):
    out = defaultdict(list)
    for r in db.rows(conn.execute('SELECT t.*, p.name AS project_name, p.code AS project_code FROM project_tags t LEFT JOIN projects p ON p.id = t.project_id')):
        out[(r['source'], r['ref'])].append(r)
    return out


def movement(conn, source, ref):
    """Tek hareket + kalem seçenekleri (fatura kalemleri / Satın Alma satırları / muhasebe satırları) + mevcut etiketler."""
    m = None
    if source == 'txn':
        t = conn.execute('SELECT date FROM fin_txns WHERE id = ?', (ref,)).fetchone()
        pool = universe(conn, t[0], t[0]) if t else []
    else:
        pool = universe(conn)
    m = next((x for x in pool if x['source'] == source and x['ref'] == ref), None)
    if not m:
        return None   # yok ya da projeye sorulmayan hareket (açılış, kendi hesapları arası virman)
    lines = []
    if m['nature'] != 'odeme':
        inv = {'id': ref} if source == 'invoice' else db.row(conn.execute('SELECT id FROM invoices WHERE number = ?', (m['doc_no'],))) if m['doc_no'] else None
        if inv:
            for it in db.rows(conn.execute('SELECT id, description, qty, unit, unit_price, line_total FROM invoice_items WHERE invoice_id = ?', (inv['id'],))):
                lines.append({'line_ref': f"item:{it['id']}", 'desc': f"{it['description']} · {it['qty']:g} {it['unit'] or ''}".strip(), 'net': round(it['line_total'] or (it['qty'] or 0) * (it['unit_price'] or 0), 2)})
        mdoc = {'id': ref} if source == 'mdoc' else db.row(conn.execute("SELECT id FROM material_docs WHERE number = ? AND kind = 'FATURA'", (m['doc_no'],))) if m['doc_no'] else None
        if mdoc and not lines:
            for ln in db.rows(conn.execute('''SELECT m.id, m.qty, m.unit_price, p.code, p.name, p.unit FROM material_moves m JOIN products p ON p.id = m.product_id
                                              WHERE m.doc_id = ?''', (mdoc['id'],))):
                lines.append({'line_ref': f"mline:{ln['id']}", 'desc': f"{ln['code']} {ln['name']} · {ln['qty']:g} {ln['unit'] or ''}".strip(),
                              'net': round((ln['qty'] or 0) * (ln['unit_price'] or 0), 2)})
        if not lines and m['doc_no']:
            for l in _ledger_by_doc(conn, [m['doc_no']]).get(m['doc_no'], []):
                v = l['credit'] if m['nature'] == 'gelir' else l['debit']
                if v > 0 and l['account'].startswith(REV_PREFIX if m['nature'] == 'gelir' else COST_PREFIX):
                    lines.append({'line_ref': f"ledger:{l['guid']}", 'desc': f"{l['account']} {l['account_name'] or ''}".strip(), 'net': round(v, 2)})
    m['lines'] = lines
    m['tags'] = tags_by_source(conn).get((source, ref), [])
    return m


def decide(conn, user_id, m, allocations, note=None, auto=False):
    """Hareketin proje kararını yazar (öncekiler silinir). allocations: [{project_id|None, amount?, line_ref?}]
    - kalem bazında: seçilen kalemler projeye, kalan tutar "projesiz";
    - tutar bölüşümü: net oransal; boş / tek eleman: tamamı."""
    from fastapi import HTTPException
    pids = {a.get('project_id') for a in allocations if a.get('project_id')}
    for pid in pids:
        if not conn.execute('SELECT 1 FROM projects WHERE id = ?', (pid,)).fetchone():
            raise HTTPException(400, 'Proje bulunamadı')
    rows = []
    lines = {ln['line_ref']: ln for ln in m.get('lines', [])}
    by_line = [a for a in allocations if a.get('line_ref')]
    if by_line:
        used = 0.0
        for a in by_line:
            ln = lines.get(a['line_ref'])
            if not ln:
                raise HTTPException(400, 'Kalem bulunamadı')
            used += ln['net']
            rows.append((a.get('project_id'), ln['net'], ln['net'], a['line_ref'], ln['desc'][:200]))
        rest_net = round(m['net'] - used, 2)
        if rest_net > 0.009:
            ratio = rest_net / m['net'] if m['net'] else 0
            rows.append((None, round(m['amount'] * ratio, 2), rest_net, None, 'Kalan (projesiz)'))
    else:
        total = sum(a.get('amount') or 0 for a in allocations)
        if not total:   # tutar verilmedi: tamamı tek karara (proje ya da projesiz)
            a = allocations[0] if allocations else {'project_id': None}
            rows.append((a.get('project_id'), m['amount'], m['net'], None, None))
        else:
            if total > m['amount'] + 0.01:
                raise HTTPException(400, f"Dağıtılan tutar hareket tutarını ({m['amount']:.2f}) aşıyor")
            for a in allocations:
                if (a.get('amount') or 0) <= 0:
                    continue
                r = a['amount'] / m['amount'] if m['amount'] else 0
                rows.append((a.get('project_id'), round(a['amount'], 2), round(m['net'] * r, 2), None, None))
            rest = round(m['amount'] - total, 2)
            if rest > 0.009:
                rows.append((None, rest, round(m['net'] * rest / m['amount'], 2), None, 'Kalan (projesiz)'))
    conn.execute('DELETE FROM project_tags WHERE source = ? AND ref = ?', (m['source'], m['ref']))
    now = db.now()
    for pid, amount, net, line_ref, line_desc in rows:
        conn.execute('''INSERT INTO project_tags (source, ref, project_id, nature, amount, net, line_ref, line_desc, note, auto, created_by, created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (m['source'], m['ref'], pid, m['nature'], amount, net, line_ref, line_desc,
                                                              (note or '').strip()[:300] or None, int(auto), user_id, now))


def canonical(conn, source, ref):
    """Fatura / Satın Alma belgesinin proje kararının yazılacağı hareket: aynı belge no'lu cari hareketi varsa o (Mikro),
    yoksa belgenin kendisi — böylece aynı belge iki kez sayılmaz."""
    tbl = {'invoice': 'invoices', 'mdoc': 'material_docs'}.get(source)
    if tbl:
        num = conn.execute(f'SELECT number FROM {tbl} WHERE id = ?', (ref,)).fetchone()
        if num and num[0]:
            t = conn.execute("SELECT t.id FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id WHERE t.doc_no = ? AND a.kind = 'cari' ORDER BY t.id LIMIT 1", (num[0],)).fetchone()
            if t:
                return movement(conn, 'txn', t[0])
    return movement(conn, source, ref)


# ---------------- Proje finansı ----------------
def _category(tag, m):
    if tag['line_ref'] and (tag['line_ref'].startswith(('item:', 'mline:')) or (tag['line_desc'] or '').startswith('15')):
        return 'Malzeme'
    if tag['nature'] == 'gelir':
        return 'Satış / gelir'
    text = fold((m or {}).get('title', '') + ' ' + (tag['line_desc'] or ''))
    if any(w in text for w in ('maas', 'ucret', 'bordro', 'sgk', 'avans')):
        return 'Personel'
    if m and m.get('account_kind') in ('kasa', 'banka'):
        return 'Doğrudan gider'
    return 'Hizmet / fatura'


def project_finance(conn, pid, umap=None):
    tags = db.rows(conn.execute('SELECT * FROM project_tags WHERE project_id = ?', (pid,)))
    umap = umap if umap is not None else {(x['source'], x['ref']): x for x in universe(conn)}
    items, cats, months = [], defaultdict(float), defaultdict(lambda: {'gelir': 0.0, 'gider': 0.0})
    tot = {'gelir': 0.0, 'gider': 0.0, 'tahsilat': 0.0, 'odeme': 0.0}
    for t in tags:
        m = umap.get((t['source'], t['ref']))
        if m is None:
            continue   # hareket silinmiş (Mikro'dan kalkan) — öksüz etiket sayılmaz
        d = (m or {}).get('date') or ''
        if t['nature'] in ('gelir', 'gider'):
            tot[t['nature']] += t['net']
            if t['nature'] == 'gider':
                cats[_category(t, m)] += t['net']
            if d:
                months[d[:7]][t['nature']] += t['net']
        else:   # tahsilat: carinin alacak kaydı (müşteri ödedi) ya da kasa / banka girişi
            d_ = (m or {}).get('direction')
            inflow = m and ((m['account_kind'] == 'cari' and d_ == 'out') or (m['account_kind'] in ('kasa', 'banka') and d_ == 'in'))
            tot['tahsilat' if inflow else 'odeme'] += t['amount']
        items.append({**t, 'date': d, 'title': (m or {}).get('title'), 'account': (m or {}).get('account'), 'doc_no': (m or {}).get('doc_no'),
                      'account_kind': (m or {}).get('account_kind'), 'company_id': (m or {}).get('company_id'), 'account_id': (m or {}).get('account_id'),
                      'category': _category(t, m) if t['nature'] == 'gider' else None})
    items.sort(key=lambda x: x['date'], reverse=True)
    kar = tot['gelir'] - tot['gider']
    return {'gelir': round(tot['gelir'], 2), 'gider': round(tot['gider'], 2), 'kar': round(kar, 2),
            'marj': round(kar / tot['gelir'] * 100, 1) if tot['gelir'] else None, 'tahsilat': round(tot['tahsilat'], 2), 'odeme': round(tot['odeme'], 2),
            'categories': {k: round(v, 2) for k, v in sorted(cats.items(), key=lambda x: -x[1])},
            'months': [{'month': k, **{kk: round(vv, 2) for kk, vv in v.items()}} for k, v in sorted(months.items())], 'items': items}


# ---------------- Tarama ----------------
def _keys(p):
    ks = [k.strip() for k in (p.get('keywords') or '').split(',') if k.strip()]
    if p.get('code'):
        ks.append(p['code'])
    return [squash(k) for k in ks if len(squash(k)) >= 3]


def _text(m, ledger):
    return squash(' '.join(filter(None, [m['title'], m['doc_no'], m.get('account') or ''] + [l['description'] or '' for l in ledger.get(m['doc_no'], [])])))


def suggestions(conn, ms=None, decided=None):
    """Kararı verilmemiş hareketlerden proje anahtar kelimeleriyle eşleşenler: {(source, ref): [project_id…]}."""
    projects = [p for p in db.rows(conn.execute("SELECT id, code, keywords, mikro_code FROM projects WHERE status NOT IN ('iptal')")) if _keys(p) or p['mikro_code']]
    if not projects:
        return {}
    ms = ms if ms is not None else universe(conn)
    decided = decided if decided is not None else set(tags_by_source(conn))
    open_ms = [m for m in ms if (m['source'], m['ref']) not in decided]
    ledger = _ledger_by_doc(conn, [m['doc_no'] for m in open_ms])
    out = {}
    for m in open_ms:
        s = _text(m, ledger)
        codes = {m.get('mikro_project')} | {l['mikro_project'] for l in ledger.get(m['doc_no'], [])}   # Mikro proje kodu eşleşmesi kesindir
        hits = [p['id'] for p in projects if (p['mikro_code'] and p['mikro_code'] in codes) or any(k in s for k in _keys(p))]
        if hits:
            out[(m['source'], m['ref'])] = hits
    return out


STOP = set('''fatura faturasi fat al sat dekont havale eft giden gelen odeme odemesi tahsilat hizmet hizmeti bedeli bedel gideri giderleri gider
kdv tevkifat ait icin ve ile the of a s ltd sti ltdsti as a.s anonim sirketi sirket san tic sanayi ticaret limited pos alisveris kart no
mutabakat isyeri yurtici yurtdisi aylik ay ocak subat mart nisan mayis haziran temmuz agustos eylul ekim kasim aralik maas maasi
virman mahsup acilis devir kredi karti nakit kasa banka hesap hesabi hesaba tl usd eur fis fisi belge no tarih mal malzeme operasyon merkezi
arac yakit kira bina elektrik su dogalgaz telefon internet kargo noter vergi sgk prim personel ucret bordro
bankasi ziraat halk halkbank vakif vakiflar vakifbank garanti akbank isbank yapi kredi denizbank qnb teb kuveyt albaraka enpara ing hsbc finansbank
hav gond gonderilen gonderim gelen giden borc borcu alacak iade iadesi avans avansi sanal teknoloji hamili hesaptan cari satis
mobil merkezi sube eft fast swift dekontu tutar toplam fark kur alimi alim satin yansitma ft ftr
siyah beyaz mavi sari kirmizi yesil gri turuncu mor pembe kahverengi lacivert renkli renk toner kartus kalem tahta kagit'''.split())


def discover(conn, limit=30):
    """Proje adayları: fatura açıklamalarında / notlarında farklı aylarda ve belgelerde tekrar eden, firma / hesap / kişi /
    banka adı ya da kod olmayan ayırt edici ifadeler (banka ve POS hareketleri gürültü olduğu için taranmaz)."""
    ms = [m for m in universe(conn) if m['nature'] in ('gelir', 'gider') and m['account_kind'] in ('cari', 'fatura')]
    ledger = _ledger_by_doc(conn, [m['doc_no'] for m in ms])
    names = {squash(r[0]) for r in conn.execute('SELECT name FROM companies')} | {squash(r[0]) for r in conn.execute('SELECT name FROM fin_accounts')}
    coa = {squash(r[0]) for r in conn.execute('SELECT name FROM fin_coa')}
    # Firma / hesap / kişi adlarını oluşturan kelimeler: yalnız bunlardan oluşan ifade aday olmaz
    name_words = set()
    for (n,) in conn.execute('SELECT name FROM companies UNION ALL SELECT name FROM fin_accounts UNION ALL SELECT full_name FROM users UNION ALL '
                             "SELECT first_name || ' ' || last_name FROM employees"):
        name_words |= {fold(w) for w in re.findall(r'[0-9A-Za-zÇĞİÖŞÜçğıöşü]{2,}', n or '')}
    stats = defaultdict(lambda: {'docs': set(), 'months': set(), 'amount': 0.0, 'samples': [], 'vendors': set(), 'paren': False})
    for m in ms:
        texts = ([m['title']] if m['source'] == 'txn' else []) + [_ledger_note(l['description']) for l in ledger.get(m['doc_no'], [])]
        parens = {squash(x) for t_ in texts if t_ for x in re.findall(r'\(([^()]{3,60})\)', t_)}   # "(FIRLATMA RAMPASI)" gibi etiketler
        words = re.findall(r'[0-9A-Za-zÇĞİÖŞÜçğıöşü\-]{3,}', ' '.join(t for t in texts if t))
        toks = [fold(w) for w in words]
        seen = set()
        for n in (1, 2, 3):
            for i in range(len(toks) - n + 1):
                g = toks[i:i + n]
                if any(x in STOP or re.search(r'[0-9]', x) for x in g) or all(x in name_words for x in g):
                    continue   # kod (rakam içerir), durak kelime ya da tamamen firma / kişi adı
                phrase = ' '.join(g)
                key = squash(phrase)
                if len(key) < 4 or key in seen or key in names or key in coa or any(key in nm for nm in names if len(nm) < 40 and len(key) > 6):
                    continue
                seen.add(key)
                st = stats[key]
                st['phrase'] = phrase
                st['docs'].add((m['source'], m['ref']))
                st['months'].add(m['date'][:7])
                st['amount'] += m['net']
                st['vendors'].add(m.get('account') or '')
                st['paren'] = st['paren'] or key in parens
                sample = next((t_ for t_ in texts if t_ and key in squash(t_)), m['title'])
                if len(st['samples']) < 3 and sample[:120] not in st['samples']:
                    st['samples'].append(sample[:120])
    cands = [{'phrase': v['phrase'].upper(), 'key': k, 'count': len(v['docs']), 'months': len(v['months']), 'amount': round(v['amount'], 2), 'samples': v['samples'],
              'vendors': len(v['vendors']), 'paren': v['paren'], 'docs': frozenset(v['docs'])}
             for k, v in stats.items() if len(v['docs']) >= 3 and len(v['months']) >= 2 and (len(v['vendors']) >= 2 or v['paren'])]
    # Aynı belge kümesini kapsayan ifadelerden (ör. "MOTOR PERVANE SETİ" / "PERVANE SETİ VTOL") yalnız biri kalır
    cands.sort(key=lambda c: (-c['count'], -len(c['phrase'].split()), -len(c['key'])))
    out, seen_docs = [], set()
    for c in cands:
        if c['docs'] in seen_docs:
            continue
        seen_docs.add(c['docs'])
        out.append(c)
    for c in out:
        c.pop('docs')
    # Öncelik: parantez içi etiket, proje / ar-ge sözcükleri, farklı tedarikçi sayısı, tutar
    out.sort(key=lambda c: (-c['paren'], -('proje' in c['key'] or 'arge' in c['key'] or 'prototip' in c['key']), -c['vendors'], -c['amount']))
    return out[:limit]


def _ledger_note(desc):
    from .fleet import _parse_desc
    _, note, _ = _parse_desc(desc)
    return note or ''
