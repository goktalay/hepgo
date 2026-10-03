"""Araç Yönetimi — iş mantığı: gider kategorisi, muhasebe (Mikro yevmiye) ve finans hareketlerinden araç gideri adayları,
plaka / anahtar kelime / kiralayan firma ile eşleştirme önerisi, km ve hatırlatmalar.

Modül yalnızca yerel tabloları okur: Mikro verisi Program Ayarları › Entegrasyonlar'daki senkronla fin_ledger / fin_coa /
fin_txns'e gelir. Aday hareket = 7'li gider hesaplarından adı araç / taşıt / yakıt / HGS / MTV… içerenlere yazılan borç
satırları (virman ve açılış fişleri hariç); aynı fişin aynı kategorideki satırları (ör. KKEG + normal kısım) tek harekettir."""
import json
import re
from datetime import date

from . import db

CATEGORIES = {'yakit': 'Yakıt', 'bakim': 'Bakım / onarım', 'lastik': 'Lastik', 'sigorta': 'Sigorta / kasko', 'vergi': 'MTV / vergi',
              'otoyol': 'HGS / OGS / otoyol', 'otopark': 'Otopark', 'kira': 'Kira', 'ceza': 'Trafik cezası', 'yikama': 'Yıkama / temizlik',
              'diger': 'Diğer'}
BODY_TYPES = {'otomobil': 'Otomobil', 'suv': 'SUV / arazi', 'pickup': 'Pick-up', 'hafif_ticari': 'Hafif ticari', 'panelvan': 'Panelvan',
              'minibus': 'Minibüs / midibüs', 'kamyonet': 'Kamyonet', 'kamyon': 'Kamyon / çekici', 'motosiklet': 'Motosiklet',
              'is_makinesi': 'İş makinesi / forklift', 'diger': 'Diğer'}
FUEL_TYPES = {'dizel': 'Dizel', 'benzin': 'Benzin', 'lpg': 'Benzin + LPG', 'hibrit': 'Hibrit', 'elektrik': 'Elektrik'}
FUEL_LEVELS = {'bos': 'Boş', '1/4': '1/4', '1/2': '1/2', '3/4': '3/4', 'dolu': 'Dolu'}
OWNERSHIP = {'owned': 'Şirket malı (satın alındı)', 'leased': 'Kiralık'}
LEASE_INCLUDES = {'bakim': 'Periyodik bakım', 'lastik': 'Lastik', 'trafik': 'Trafik sigortası', 'kasko': 'Kasko', 'mtv': 'MTV',
                  'ikame': 'İkame araç'}
EXIT_REASONS = {'satildi': 'Satıldı', 'iade': 'Kiralayana iade edildi', 'hurda': 'Hurdaya ayrıldı', 'diger': 'Diğer'}
DOC_KINDS = {'ruhsat': 'Ruhsat', 'kira': 'Kira sözleşmesi', 'zimmet': 'İmzalı zimmet formu', 'trafik': 'Trafik sigortası poliçesi',
             'kasko': 'Kasko poliçesi', 'muayene': 'Muayene raporu', 'fatura': 'Fatura', 'servis': 'Servis / bakım formu',
             'hasar': 'Hasar / kaza tutanağı', 'diger': 'Diğer'}
EQUIPMENT = ['Ruhsat', 'Trafik sigortası poliçesi', 'Kasko poliçesi', 'Yedek anahtar', 'Stepne', 'Kriko ve bijon anahtarı',
             'Yangın söndürücü', 'İlk yardım çantası', 'Reflektör', 'Çekme halatı', 'HGS / OGS etiketi', 'Taşıt tanıma (yakıt) kartı']
# Zimmet formu maddeleri: firmaya göre düzenlenir (Araç Yönetimi › Ayarlar). Hukuk danışmanına kontrol ettirilmesi önerilir.
CLAUSES = '\n'.join([
    'Araç yalnızca şirket işleri için ve şirketin izin verdiği kapsamda kullanılır.',
    'Aracın özenli kullanımından, temiz tutulmasından ve belgelerinin araçta bulundurulmasından teslim alan personel sorumludur.',
    'Arıza, hasar, kaza ve hırsızlık durumları gecikmeden yöneticiye bildirilir.',
    'Kullanım süresince oluşan trafik cezaları ve kullanıcı kusurundan doğan zararlar için şirket iç düzenlemeleri uygulanır.',
    'Araç ve belgeleri şirketin izni olmadan üçüncü kişilere kullandırılamaz.',
    'Araç; istendiğinde, görev değişikliğinde ya da iş akdinin sona ermesinde ekipmanlarıyla birlikte eksiksiz teslim edilir.',
])
DUE_FIELDS = [('inspection_date', 'Muayene'), ('traffic_ins_date', 'Trafik sigortası'), ('kasko_date', 'Kasko'),
              ('lease_end', 'Kira sözleşmesi bitişi'), ('next_service_date', 'Periyodik bakım')]

_TR = str.maketrans('İIıŞşĞğÜüÖöÇçÂâÎîÛû', 'iiissgguuoocc' + 'aaiiuu')


def fold(s):
    return (s or '').translate(_TR).lower()


def squash(s):
    """Karşılaştırma anahtarı: Türkçe harfler sadeleşir, boşluk / noktalama atılır ('06 FNR 830' → '06fnr830')."""
    return re.sub(r'[^0-9a-z]', '', fold(s))


_CAT_RULES = [('yakit', ('akaryakit', 'yakit', 'benzin', 'motorin', 'mazot', 'dizel', 'lpg')),
              ('lastik', ('lastik',)),
              ('bakim', ('tamir', 'bakim', 'onarim', 'servis', 'yedek parca')),
              ('kira', ('kira',)),
              ('sigorta', ('sigorta', 'kasko')),
              ('vergi', ('mtv', 'motorlu tasit vergi')),
              ('otoyol', ('hgs', 'ogs', 'otoyol', 'kopru')),
              ('otopark', ('otopark',)),
              ('ceza', ('ceza',)),
              ('yikama', ('yikama',))]
# 7'li gider hesabının adı bunlardan birini (tam kelime) içeriyorsa araç gider hesabıdır. KKEG_ARAÇ gibi alt çizgili adlar da tutsun
# diye kelime sınırı harf olmayan karakterle bakılır ("ARACILIK" eşleşmez).
_VEH_RE = re.compile(r'(?<![a-z])(arac|araclar|tasit|tasitlar|akaryakit|yakit|otopark|hgs|ogs|mtv|kasko|otoyol)(?![a-z])')
# Finans (kasa / banka) çıkışlarında araçla ilgili sayılacak kelimeler
_TXN_RE = re.compile(r'(?<![a-z])(arac|tasit|akaryakit|yakit|benzin|motorin|hgs|ogs|otopark|kasko|mtv|otoyol)')
PLATE_RE = re.compile(r'(?<![0-9A-ZÇĞİÖŞÜ])(0[1-9]|[1-7][0-9]|8[01])\s?([A-ZÇĞİÖŞÜ]{1,3})\s?([0-9]{2,5})(?![0-9])')


def category_of(text):
    f = fold(text)
    for k, words in _CAT_RULES:
        if any(w in f for w in words):
            return k
    return 'diger'


def norm_plate(p):
    """'06fnr 830' → '06 FNR 830' (biçim tanınmazsa yalnızca büyük harf + tek boşluk)."""
    s = ' '.join((p or '').upper().split())
    m = PLATE_RE.fullmatch(s.replace(' ', '')) or PLATE_RE.fullmatch(s)
    return f'{m.group(1)} {m.group(2)} {m.group(3)}' if m else s


def days_left(d):
    try:
        return (date.fromisoformat((d or '')[:10]) - date.today()).days
    except ValueError:
        return None


def settings(conn):
    row = conn.execute("SELECT v FROM app_kv WHERE k='fleet_settings'").fetchone()
    try:
        s = json.loads(row[0]) if row else {}
    except ValueError:
        s = {}
    return {'clauses': s.get('clauses') or CLAUSES, 'equipment': s.get('equipment') or EQUIPMENT, 'custom': bool(s)}


# ---------------- km / hatırlatmalar ----------------
def km_now(conn, vid):
    r = conn.execute('''SELECT MAX(x) FROM (
        SELECT start_km x FROM field_vehicles WHERE id=:v
        UNION ALL SELECT start_km FROM vehicle_assignments WHERE vehicle_id=:v UNION ALL SELECT end_km FROM vehicle_assignments WHERE vehicle_id=:v
        UNION ALL SELECT km FROM vehicle_expenses WHERE vehicle_id=:v
        UNION ALL SELECT start_km FROM field_task_vehicles WHERE vehicle_id=:v UNION ALL SELECT end_km FROM field_task_vehicles WHERE vehicle_id=:v)''',
                     {'v': vid}).fetchone()[0]
    return r


def dues(v, km=None, within=30):
    """Yaklaşan / geçmiş muayene, sigorta, kasko, kira bitişi, bakım (tarih ya da km)."""
    if not v.get('active'):
        return []
    out = []
    for f, label in DUE_FIELDS:
        if f == 'lease_end' and v.get('ownership') != 'leased':
            continue
        left = days_left(v.get(f))
        if left is not None and left <= within:
            out.append({'key': f, 'label': label, 'date': v[f][:10], 'days': left})
    if v.get('next_service_km') and km is not None and km >= v['next_service_km'] - 1000:
        out.append({'key': 'next_service_km', 'label': 'Periyodik bakım', 'km': v['next_service_km'], 'left_km': round(v['next_service_km'] - km)})
    return out


# ---------------- Muhasebe / finans hareketleri ----------------
def expense_accounts(conn):
    """Araç gider hesapları: 7'li hesaplardan adı araç / taşıt / yakıt / HGS / MTV… içerenler (yansıtma hesapları hariç)."""
    out = {}
    for code, name in conn.execute("SELECT code, name FROM fin_coa WHERE code LIKE '7%'"):
        f = fold(name)
        if _VEH_RE.search(f) and 'yansitma' not in f:
            out[code] = name
    return out


def _parse_desc(desc):
    """Mikro alış faturası açıklaması 'Al.fat. : BELGE/TARİH/AÇIKLAMA/CARİ KOD/CARİ AD/MASRAF MRK/HESAP' → (belge, açıklama, cari)."""
    d = (desc or '').strip()
    m = re.match(r'^(?:al|sat)\.?\s*fat\.?\s*:\s*(.*)$', d, re.I)
    if not m:
        return None, d, None
    p = [x.strip() for x in m.group(1).split('/')]
    return (p[0] or None), (p[2] if len(p) > 2 else '') or None, (p[4] if len(p) > 4 else '') or None


def _ledger_moves(conn, since, only_guid_group=None):
    accs = expense_accounts(conn)
    if not accs:
        return []
    ph = ','.join('?' * len(accs))
    where, args = f'account IN ({ph}) AND debit > 0 AND COALESCE(kind, 0) != 3', list(accs)
    if only_guid_group:   # tek hareket: aynı fiş (tarih + yevmiye no + belge no)
        where += ' AND date=? AND COALESCE(journal_no, -1)=? AND COALESCE(doc_no, \'\')=?'
        args += list(only_guid_group)
    else:
        where += ' AND date >= ?'
        args.append(since)
    groups = {}
    for r in conn.execute(f'SELECT guid, date, journal_no, account, description, debit, doc_no FROM fin_ledger WHERE {where}', args):
        if 'virman' in fold(r['description']):
            continue
        cat = category_of(accs[r['account']])
        key = (r['date'], r['journal_no'], r['doc_no'] or '', cat)
        g = groups.get(key)
        if not g:
            belge, note, vendor = _parse_desc(r['description'])
            g = groups[key] = {'source': 'mikro', 'date': r['date'], 'category': cat, 'amount': 0.0, 'doc_no': r['doc_no'] or belge,
                               'vendor': vendor, 'note': note, 'text': r['description'] or '', 'accounts': [], 'guids': [],
                               'jkey': [r['date'], r['journal_no'] if r['journal_no'] is not None else -1, r['doc_no'] or '']}
        g['guids'].append(r['guid'])
        g['amount'] += r['debit']
        name = f"{r['account']} {accs[r['account']]}"
        if name not in g['accounts']:
            g['accounts'].append(name)
    out = []
    for g in groups.values():
        g['ref'] = 'led:' + min(g['guids'])
        g['amount'] = round(g['amount'], 2)
        g.pop('guids')
        out.append(g)
    return out


def _txn_moves(conn, since, txn_id=None):
    where, args = "t.direction='out' AND t.mikro_ref IS NULL AND t.counter_id IS NULL AND a.kind IN ('kasa','banka')", []
    if txn_id:
        where += ' AND t.id=?'
        args.append(txn_id)
    else:
        where += ' AND t.date >= ?'
        args.append(since)
    out = []
    for r in conn.execute(f'''SELECT t.id, t.date, t.amount, t.currency, t.category, t.description, t.doc_no, a.name AS account_name
                              FROM fin_txns t JOIN fin_accounts a ON a.id=t.account_id WHERE {where}''', args):
        text = ' '.join(x for x in (r['category'], r['description']) if x)
        out.append({'source': 'finans', 'ref': f"txn:{r['id']}", 'date': r['date'], 'category': category_of(text), 'amount': round(r['amount'], 2),
                    'doc_no': r['doc_no'], 'vendor': None, 'note': r['description'], 'text': text, 'accounts': [r['account_name']],
                    'vehicle_words': bool(_TXN_RE.search(fold(text)))})
    return out


def _vehicle_keys(conn):
    out = []
    for v in db.rows(conn.execute('''SELECT v.id, v.plate, v.match_keys, v.ownership, v.active, c.name AS lessor_name
                                     FROM field_vehicles v LEFT JOIN companies c ON c.id=v.lessor_id''')):
        keys = {squash(v['plate'])}
        for k in (v['match_keys'] or '').split(','):
            k = squash(k)
            if len(k) >= 3:
                keys.add(k)
        lessor = squash(' '.join(fold(v['lessor_name'] or '').split()[:2])) if v['ownership'] == 'leased' and v['lessor_name'] else ''
        out.append({'id': v['id'], 'keys': {k for k in keys if k}, 'lessor': lessor if len(lessor) >= 4 else '', 'active': v['active']})
    return out


def _suggest(m, vkeys):
    """Plaka / anahtar kelime eşleşmesi (kesin öneri) ya da kiralayan firma (kira, HGS, yakıt faturası) eşleşmesi (aday)."""
    s = squash(m['text'])
    hits = [v['id'] for v in vkeys if any(k in s for k in v['keys'])]
    if hits:
        return hits, 'plaka' if len(hits) == 1 else 'çoklu'
    vend = squash(m.get('vendor') or '')
    if vend:
        lh = [v['id'] for v in vkeys if v['lessor'] and v['active'] and v['lessor'] in vend]
        if lh:
            return lh, 'kiralayan'
    return [], None


def _tags(conn, refs=None):
    tags = {}
    for r in conn.execute('''SELECT e.id, e.ref, e.vehicle_id, e.amount, e.category, v.plate FROM vehicle_expenses e
                             JOIN field_vehicles v ON v.id=e.vehicle_id WHERE e.ref IS NOT NULL'''):
        if refs is None or r['ref'] in refs:
            tags.setdefault(r['ref'], []).append({'expense_id': r['id'], 'vehicle_id': r['vehicle_id'], 'plate': r['plate'],
                                                  'amount': r['amount'], 'category': r['category']})
    return tags


def _decorate(conn, moves, vkeys=None):
    vkeys = vkeys if vkeys is not None else _vehicle_keys(conn)
    tags = _tags(conn)
    ignored = {r[0] for r in conn.execute('SELECT ref FROM vehicle_ignored')}
    out = []
    for m in moves:
        m['suggest'], m['match'] = _suggest(m, vkeys)
        if m['source'] == 'finans' and not (m.pop('vehicle_words', False) or m['suggest']):
            continue   # finans çıkışı ancak araç kelimesi ya da plaka içeriyorsa aday
        m['tags'] = tags.get(m['ref'], [])
        m['tagged'] = round(sum(t['amount'] for t in m['tags']), 2)
        m['remaining'] = round(m['amount'] - m['tagged'], 2)
        m['ignored'] = m['ref'] in ignored
        out.append(m)
    return out


def moves(conn, since):
    ms = _decorate(conn, _ledger_moves(conn, since) + _txn_moves(conn, since))
    ms.sort(key=lambda m: (m['date'], m['ref']), reverse=True)
    return ms


def move_by_ref(conn, ref):
    """Tek hareket (etiketleme anında tutarı sunucuda yeniden hesaplamak için)."""
    if ref.startswith('led:'):
        r = conn.execute('SELECT date, journal_no, doc_no, account FROM fin_ledger WHERE guid=?', (ref[4:],)).fetchone()
        if not r:
            return None
        for m in _ledger_moves(conn, None, (r['date'], r['journal_no'] if r['journal_no'] is not None else -1, r['doc_no'] or '')):
            if m['ref'] == ref:
                return _decorate(conn, [m])[0]
        return None
    if ref.startswith('txn:') and ref[4:].isdigit():
        ms = _txn_moves(conn, None, int(ref[4:]))
        if ms:
            ms[0]['vehicle_words'] = True   # tek hareket istenince filtre uygulanmaz
            return _decorate(conn, ms)[0]
    return None


# ---------------- Muhasebedeki taşıtlar (254) ----------------
def asset_accounts(conn):
    """254 Taşıtlar alt hesapları (hareketi olan): ad, maliyet (borç toplamı), ilk tarih, ad içinden plaka / marka / tarih önerisi."""
    rows = db.rows(conn.execute('''SELECT c.code, c.name, ROUND(SUM(l.debit), 2) AS cost, MIN(l.date) AS first_date FROM fin_coa c
                                   JOIN fin_ledger l ON l.account = c.code WHERE c.code LIKE '254%' AND l.debit > 0 GROUP BY c.code ORDER BY c.code'''))
    linked = {r[0]: r[1] for r in conn.execute("SELECT asset_account, id FROM field_vehicles WHERE asset_account IS NOT NULL AND asset_account != ''")}
    plates = {squash(r[0]): r[1] for r in conn.execute('SELECT plate, id FROM field_vehicles')}
    out = []
    for r in rows:
        name = r['name'] or ''
        m = PLATE_RE.search(name.upper())
        plate = f'{m.group(1)} {m.group(2)} {m.group(3)}' if m else None
        d = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', name)
        rest = name
        if m:
            rest = (name[:m.start()] + name[m.end():])
        rest = re.sub(r'\(?\d{2}\.\d{2}\.\d{4}\)?', '', rest).strip(' -()')
        parts = rest.split()
        r.update(plate=plate, brand=parts[0].title() if parts else None, model=' '.join(parts[1:]) or None,
                 date=f'{d.group(3)}-{d.group(2)}-{d.group(1)}' if d else r['first_date'],
                 vehicle_id=linked.get(r['code']), plate_vehicle_id=plates.get(squash(plate)) if plate else None)
        out.append(r)
    return out
