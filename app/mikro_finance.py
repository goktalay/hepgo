"""Mikro ERP → Finans tek yönlü senkronu: banka hesapları, kasalar, banka/kasa hareketleri ve (eşleşen firmaların)
cari hareketleri. Mikro'ya hiçbir şey yazılmaz. Tekrarlanabilir: her hareket fin_txns.mikro_ref ile eşleşir
('cha:<guid>:d' hareketin kendi hesabı, 'cha:<guid>:c' karşı banka/kasa); değişen güncellenir, Mikro'da silinen /
iptal edilen yerelden de kalkar. Elle girilen Finans hareketlerine dokunulmaz.

Yön: banka/kasa için borç (tip 0) = giriş, alacak = çıkış; karşı tarafta (havale, kredi kartı) tersi.
Cari için borç = 'in' (firmanın bize borcu artar), alacak = 'out' — Finans'ta pozitif cari bakiye = alacağımız.
"""
import json

from . import db, mikro

KV_KEY = 'mikro.fin_sync'
CINS = {2: 'banka', 4: 'kasa'}
EVRAK = {0: 'Fatura', 29: 'Devir / açılış', 33: 'Dekont', 34: 'Gelen havale', 35: 'Giden havale', 56: 'Makbuz',
         61: 'Fatura', 63: 'Mahsup / virman', 64: 'Kredi kartı', 65: 'Kredi kartı ödemesi', 112: 'Kredi ödemesi'}


def _cins(r, key='cins'):
    v = r.get(key)
    return int(v) if v is not None else -1   # 0 (cari) geçerli bir değer: "or -1" kullanılmaz


def _tl(r):
    """Hareketin TL tutarı: dövizli satırda Mikro tutarı döviz cinsindendir (× kur)."""
    amt = float(r.get('tutar') or 0)
    if _cins(r, 'dc') > 0 and float(r.get('kur') or 0) > 0:
        amt *= float(r['kur'])
    return round(amt, 2)


def _due(r):
    """Mikro cha_vade: YYYYMMDD tarih ya da (küçük sayı) gün farkı; 0/boş → vade yok (hareket tarihi)."""
    v = r.get('vade')
    d0 = str(r.get('tarih'))[:10]
    try:
        v = int(v or 0)
    except (TypeError, ValueError):
        return None
    if v >= 19000101:
        s = str(v)
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    if v and -3650 < v < 3650:
        from datetime import date, timedelta
        try:
            return (date.fromisoformat(d0) + timedelta(days=v)).isoformat()
        except ValueError:
            return None
    return None


def sync_ledger(conn):
    """Hesap planı + muhasebe fiş satırları (tek yönlü; Mikro'da silinen/iptal edilen yerelden de kalkar)."""
    coa = mikro.list_coa()
    now = db.now()
    conn.executemany('INSERT INTO fin_coa (code, name, updated_at) VALUES (?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at',
                     [((r['kod'] or '').strip(), (r['ad'] or '').strip() or (r['kod'] or '').strip(), now) for r in coa if (r.get('kod') or '').strip()])
    rows = mikro.list_ledger()
    have = {g for (g,) in conn.execute('SELECT guid FROM fin_ledger')}
    seen, added, data = set(), 0, []
    for r in rows:
        g = r.get('guid')
        if not g:
            continue
        seen.add(g)
        amt = round(float(r.get('tutar') or 0), 2)
        data.append((g, str(r['tarih'])[:10], r.get('yevmiye'), r.get('sira'), r.get('tur'), (r.get('hesap') or '').strip(),
                     (r.get('aciklama') or '').strip()[:300] or None, amt if amt > 0 else 0.0, -amt if amt < 0 else 0.0, (r.get('belge') or '').strip() or None))
        added += g not in have
    conn.executemany('''INSERT INTO fin_ledger (guid, date, journal_no, entry_no, kind, account, description, debit, credit, doc_no)
                        VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(guid) DO UPDATE SET date=excluded.date, journal_no=excluded.journal_no,
                        entry_no=excluded.entry_no, kind=excluded.kind, account=excluded.account, description=excluded.description,
                        debit=excluded.debit, credit=excluded.credit, doc_no=excluded.doc_no''', data)
    gone = have - seen
    if gone:
        conn.executemany('DELETE FROM fin_ledger WHERE guid = ?', [(g,) for g in gone])
    return {'hesap_plani': len(coa), 'yevmiye_satiri': len(rows), 'yeni': added, 'silinen': len(gone)}


def _iban(v):
    return ''.join(ch for ch in (v or '') if ch.isalnum()).upper() or None


def _doc(r):
    belge = (r.get('belge') or '').strip()
    if belge:
        return belge
    seri = (r.get('seri') or '').strip()
    return f'{seri}-{r.get("sira")}' if seri else str(r.get('sira') or '')


def _upsert_account(conn, kind, code, name, *, bank=None, iban=None, note=None, active=True):
    row = conn.execute('SELECT id FROM fin_accounts WHERE kind = ? AND mikro_code = ?', (kind, code)).fetchone()
    if row:
        conn.execute('UPDATE fin_accounts SET name=?, bank=?, iban=?, note=?, active=? WHERE id=?',
                     (name, bank, iban, note, 1 if active else 0, row[0]))
        return row[0], False
    cur = conn.execute('''INSERT INTO fin_accounts (kind, name, currency, iban, bank, opening, mikro_code, note, active, created_at)
                          VALUES (?,?,?,?,?,0,?,?,?,?)''', (kind, name, 'TRY', iban, bank, code, note, 1 if active else 0, db.now()))
    return cur.lastrowid, True


def _cari_account(conn, company_id, cache):
    if company_id in cache:
        return cache[company_id]
    r = conn.execute("SELECT id FROM fin_accounts WHERE kind='cari' AND company_id=? AND active=1", (company_id,)).fetchone()
    if r:
        cache[company_id] = r[0]
        return r[0]
    c = conn.execute('SELECT name FROM companies WHERE id=?', (company_id,)).fetchone()
    if not c:
        cache[company_id] = None
        return None
    cur = conn.execute("INSERT INTO fin_accounts (kind,name,company_id,opening,active,created_at) VALUES ('cari',?,?,0,1,?)",
                       (c[0], company_id, db.now()))
    cache[company_id] = cur.lastrowid
    return cur.lastrowid


def plan(rows, include_cari, links):
    """Mikro hareketlerinden üretilecek Finans hareketleri: [(ref, (hesap türü, kod | firma), yön, satır)]."""
    out = []
    for r in rows:
        amt = _tl(r)
        if not r.get('guid') or amt == 0:
            continue
        tip = int(r.get('tip') or 0)
        cins = _cins(r)
        if cins in CINS:
            out.append((f"cha:{r['guid']}:d", (CINS[cins], r['kod']), 'in' if tip == 0 else 'out', r))
        elif cins == 0 and include_cari and links.get(r['kod']):
            out.append((f"cha:{r['guid']}:d", ('cari', links[r['kod']]), 'in' if tip == 0 else 'out', r))
        kh = _cins(r, 'kh')
        if kh in CINS and (r.get('khkod') or '').strip():
            out.append((f"cha:{r['guid']}:c", (CINS[kh], r['khkod'].strip()), 'out' if tip == 0 else 'in', r))
    return out


def preview(conn):
    """Mikro tarafının özeti (senkron öncesi): bankalar / kasalar Mikro bakiyesiyle, hareket kırılımı, eşleşmeyen cariler."""
    banks, kasas, rows = mikro.list_bankalar(), mikro.list_kasalar(), mikro.list_fin_hareket()
    links = {r[0]: r[1] for r in conn.execute("SELECT mikro_code, local_id FROM mikro_links WHERE kind = 'cari'")}
    bal, cnt = {}, {}
    for _ref, (kind, key), d, r in plan(rows, False, links):
        amt = _tl(r)
        bal[(kind, key)] = bal.get((kind, key), 0) + (amt if d == 'in' else -amt)
        cnt[(kind, key)] = cnt.get((kind, key), 0) + 1
    local = {(r[0], r[1]): (r[2], r[3]) for r in conn.execute(
        "SELECT kind, mikro_code, id, opening FROM fin_accounts WHERE kind IN ('banka','kasa') AND mikro_code IS NOT NULL")}

    orj = {}
    try:
        for o in mikro.query('''SELECT cho_Cinsi AS cins, cho_CariKodu AS kod, SUM(cho_Orj_Borc - cho_Orj_Alacak) AS b
                                FROM CARI_HESAP_HAREKETLERI_OZET WHERE cho_Cinsi IN (2, 4) GROUP BY cho_Cinsi, cho_CariKodu'''):
            orj[(CINS[int(o['cins'])], o['kod'])] = round(float(o['b'] or 0), 2)
    except Exception:   # noqa: BLE001 — özet tablosu yoksa döviz bakiyesi gösterilmez
        pass

    def acc(kind, a):
        loc = local.get((kind, a['kod']))
        lb = None
        if loc:
            s = conn.execute("SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount ELSE -amount END),0) FROM fin_txns WHERE account_id=?", (loc[0],)).fetchone()[0]
            lb = round((loc[1] or 0) + s, 2)
        return {'kod': a['kod'], 'ad': (a.get('ad') or '').strip(), 'sube': (a.get('sube') or '').strip() or None, 'iban': _iban(a.get('iban')),
                'doviz': mikro.DOVIZ.get(int(a.get('doviz') or 0), str(a.get('doviz'))), 'iptal': bool(a.get('iptal')),
                'mikro_bakiye': round(bal.get((kind, a['kod']), 0), 2), 'hareket': cnt.get((kind, a['kod']), 0),
                'doviz_bakiye': orj.get((kind, a['kod'])) if int(a.get('doviz') or 0) else None,
                'linked': bool(loc), 'account_id': loc[0] if loc else None, 'finans_bakiye': lb}

    cats, cari_rows, unmapped = {}, 0, set()
    dates = [str(r['tarih'])[:10] for r in rows if r.get('tarih')]
    for r in rows:
        c = EVRAK.get(int(r.get('ev') or 0), 'Diğer')
        x = cats.setdefault(c, {'kategori': c, 'adet': 0, 'tutar': 0.0})
        x['adet'] += 1; x['tutar'] = round(x['tutar'] + _tl(r), 2)
        if _cins(r) == 0:
            cari_rows += 1
            if not links.get(r['kod']):
                unmapped.add(r['kod'])
    last = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KV_KEY,)).fetchone()
    return {'bankalar': [acc('banka', b) for b in banks], 'kasalar': [acc('kasa', k) for k in kasas],
            'hareket': {'toplam': len(rows), 'ilk': min(dates) if dates else None, 'son': max(dates) if dates else None,
                        'kategoriler': sorted(cats.values(), key=lambda x: -x['adet']),
                        'cari_satir': cari_rows, 'cari_eslesmeyen': len(unmapped)},
            'son_senkron': json.loads(last[0]) if last else None}


def sync(conn, include_cari=True, user_id=None):
    """Banka/kasa hesaplarını ve hareketleri Finans'a işler. Özet sözlük döner (commit edilir)."""
    banks, kasas, rows = mikro.list_bankalar(), mikro.list_kasalar(), mikro.list_fin_hareket()
    accounts, new_acc = {}, 0
    for b in banks:
        cur = mikro.DOVIZ.get(int(b.get('doviz') or 0), 'TRY')
        note = f"Mikro banka {b['kod']}" + (f' · {cur} hesap (tutarlar TL karşılığı)' if cur != 'TRY' else '')
        aid, new = _upsert_account(conn, 'banka', b['kod'], (b.get('ad') or b['kod']).strip(), bank=(b.get('ad') or '').strip() or None,
                                   iban=_iban(b.get('iban')), note=note, active=not b.get('iptal'))
        accounts[('banka', b['kod'])] = aid; new_acc += new
    for k in kasas:
        aid, new = _upsert_account(conn, 'kasa', k['kod'], (k.get('ad') or k['kod']).strip(), note=f"Mikro kasa {k['kod']}", active=not k.get('iptal'))
        accounts[('kasa', k['kod'])] = aid; new_acc += new
    links = {r[0]: r[1] for r in conn.execute("SELECT mikro_code, local_id FROM mikro_links WHERE kind = 'cari'")}
    cari_cache = {}
    want = {}
    for ref, (kind, key), direction, r in plan(rows, include_cari, links):
        aid = _cari_account(conn, key, cari_cache) if kind == 'cari' else accounts.get((kind, key))
        if not aid:
            continue
        cat = EVRAK.get(int(r.get('ev') or 0), 'Mikro hareketi')
        want[ref] = (aid, str(r['tarih'])[:10], direction, _tl(r), cat,
                     ((r.get('aciklama') or '').strip() or cat)[:300], _doc(r)[:60] or None, _due(r) if kind == 'cari' else None)
    existing = {row[0]: row[1:] for row in conn.execute(
        "SELECT mikro_ref, id, account_id, date, direction, amount, category, description, doc_no, due_date FROM fin_txns WHERE mikro_ref LIKE 'cha:%'")}
    present = {r['guid'] for r in rows if r.get('guid')}
    added = updated = deleted = 0
    for ref, v in want.items():
        if ref in existing:
            old = existing[ref]
            if tuple(old[1:]) != v:
                conn.execute('UPDATE fin_txns SET account_id=?, date=?, direction=?, amount=?, category=?, description=?, doc_no=?, due_date=? WHERE id=?', (*v, old[0]))
                updated += 1
        else:
            conn.execute('''INSERT INTO fin_txns (account_id, date, direction, amount, currency, category, description, doc_no, due_date, mikro_ref, created_by, created_at)
                            VALUES (?,?,?,?,'TRY',?,?,?,?,?,?,?)''', (*v[:4], v[4], v[5], v[6], v[7], ref, user_id, db.now()))
            added += 1
    for ref, old in existing.items():
        guid = ref.split(':')[1] if ref.count(':') >= 2 else ''
        stale = guid not in present or (ref not in want and (include_cari or not _is_cari(conn, old[1])))
        if stale:
            conn.execute('DELETE FROM fin_txns WHERE id=?', (old[0],))
            deleted += 1
    try:   # muhasebe (mizan / mali tablolar) — okunamazsa ticari senkron yine tamamlanır
        ledger = sync_ledger(conn)
    except Exception as err:   # noqa: BLE001
        ledger = {'hata': str(err)[:200]}
    unmapped = sorted({r['kod'] for r in rows if _cins(r) == 0 and not links.get(r['kod'])})
    stats = {'at': db.now(), 'banka': len(banks), 'kasa': len(kasas), 'yeni_hesap': new_acc, 'hareket': len(rows),
             'eklenen': added, 'guncellenen': updated, 'silinen': deleted, 'cari': include_cari, 'cari_eslesmeyen': len(unmapped), 'muhasebe': ledger}
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (KV_KEY, json.dumps(stats, ensure_ascii=False)))
    conn.commit()
    stats['eslesmeyen_kodlar'] = unmapped[:20]
    return stats


def _is_cari(conn, account_id):
    r = conn.execute('SELECT kind FROM fin_accounts WHERE id=?', (account_id,)).fetchone()
    return bool(r and r[0] == 'cari')
