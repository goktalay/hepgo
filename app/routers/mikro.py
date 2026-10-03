"""Mikro ERP → sistem tek yönlü veri aktarımı (Mikro ERP modülü).

Kullanıcı Mikro'daki cari ve stok kayıtlarını görür, seçtiklerini "Aktar" der. Daha önce aktarılanlar (mikro_links)
işaretli gelir; tekrar aktarılınca eşleşen yerel kayıt güncellenir. Sistem Mikro'ya HİÇBİR ŞEY yazmaz (yalnızca okur).
Cari → firmalar/tedarikçiler (companies), stok → MRP malzemeleri (products) + Ana Depo stoğu.
"""
from typing import Optional

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, auth, bom, db, invoices, mikro, spares

router = APIRouter(prefix='/api/mikro')
mikro_user = auth.require_module('mikro')
UNITS = set(bom.UNITS)
STOK_TYPES = (spares.SPARE, spares.RAW, spares.FIXTURE, spares.CONSUMABLE)


_log = logging.getLogger('caymaz.mikro')


def _read_error(err):
    """Mikro okuma hatası: günlüğe yazılır, kullanıcıya açıklamasıyla döner. 502 yerine 424: Cloudflare 502 yanıtının
    gövdesini kendi hata sayfasıyla değiştirdiği için gerçek mesaj ekrana ulaşmıyordu."""
    _log.warning('Mikro ERP okunamadı: %s', err)
    msg = str(err)
    if config.MIKRO_PASSWORD:
        msg = msg.replace(config.MIKRO_PASSWORD, '***')
    return HTTPException(424, f'Mikro ERP okunamadı: {msg[:300]}')


def _norm_unit(u):
    u = (u or '').strip().lower()
    return u if u in UNITS else 'adet'


def _links(conn, kind):
    return {r['mikro_code']: r for r in db.rows(conn.execute(
        'SELECT mikro_code, local_id, updated_at, imported_at FROM mikro_links WHERE kind = ?', (kind,)))}


@router.get('/status')
def status(user=Depends(mikro_user), conn=db.DB):
    if not mikro.configured():
        return {'configured': False}
    p = mikro.ping()
    counts = {k: conn.execute('SELECT COUNT(*) FROM mikro_links WHERE kind = ?', (k,)).fetchone()[0] for k in ('cari', 'stok')}
    return {'configured': True, 'ok': p['ok'], 'db': p.get('db'), 'error': p.get('error'), 'imported': counts,
            'can_import': bool(user.get('master'))}


@router.get('/cari')
def cari(q: str = '', show_imported: bool = False, user=Depends(mikro_user), conn=db.DB):
    if not mikro.configured():
        raise HTTPException(400, 'Mikro ERP bağlantısı tanımlı değil')
    try:
        rows = mikro.list_cari(q, 1000)
    except Exception as err:
        raise _read_error(err)
    links = _links(conn, 'cari')
    for r in rows:
        lk = links.get(r['cari_kod'])
        r['imported'] = bool(lk)
        r['local_id'] = lk['local_id'] if lk else None
        r['imported_at'] = lk['updated_at'] or lk['imported_at'] if lk else None
    # Daha önce senkronize edilenler varsayılan gelmez; "Aktarılanları da göster" ile açılır
    return _hide_imported(rows, show_imported)


@router.get('/stok')
def stok(q: str = '', show_imported: bool = False, user=Depends(mikro_user), conn=db.DB):
    if not mikro.configured():
        raise HTTPException(400, 'Mikro ERP bağlantısı tanımlı değil')
    try:
        rows = mikro.list_stok(q, 1000)
    except Exception as err:
        raise _read_error(err)
    links = _links(conn, 'stok')
    for r in rows:
        lk = links.get(r['sto_kod'])
        r['imported'] = bool(lk)
        r['local_id'] = lk['local_id'] if lk else None
        r['imported_at'] = lk['updated_at'] or lk['imported_at'] if lk else None
    return _hide_imported(rows, show_imported)


def _hide_imported(rows, show_imported):
    """Aktarılanları (imported) gizler; toplam ve gizlenen sayısını da döndürür ki arayüz bilgilendirsin."""
    hidden = sum(1 for r in rows if r.get('imported'))
    shown = rows if show_imported else [r for r in rows if not r.get('imported')]
    return {'rows': shown, 'total': len(rows), 'hidden': 0 if show_imported else hidden}


def _manager(user):
    if not user.get('master'):
        raise HTTPException(403, 'Mikro ERP yalnızca sistem sahibine (MASTER) açıktır')


class CariImportIn(BaseModel):
    codes: list[str]


class StokImportIn(BaseModel):
    codes: list[str]
    type: str = spares.CONSUMABLE
    warehouse_id: Optional[int] = None
    set_stock: bool = True


def _link(conn, kind, code, local_id, label, new=None):
    """mikro_links kaydını güvenle yazar (UPSERT): kayıt yoksa ekler, varsa günceller. `new` argümanı yok sayılır
    (geriye dönük uyumluluk için tutuldu); UNIQUE(kind, mikro_code) çakışmalarına karşı dayanıklıdır."""
    now = db.now()
    conn.execute('''INSERT INTO mikro_links (kind, mikro_code, local_id, label, imported_at) VALUES (?,?,?,?,?)
                    ON CONFLICT(kind, mikro_code) DO UPDATE SET local_id = excluded.local_id, label = excluded.label,
                    updated_at = ?''', (kind, code, local_id, label, now, now))


@router.post('/import/cari')
def import_cari(body: CariImportIn, user=Depends(mikro_user), conn=db.DB):
    """Seçilen carileri firmalara/tedarikçilere aktarır (mükerrer olanları günceller)."""
    _manager(user)
    if not body.codes:
        raise HTTPException(400, 'Aktarılacak cari seçin')
    added, updated = _import_cari_codes(conn, body.codes[:2000], user['id'])
    db.audit(conn, user['id'], 'Mikro ERP cari aktardı', 'company', None, f'{added} yeni, {updated} güncel')
    return {'added': added, 'updated': updated}


def _import_cari_codes(conn, codes, user_id):
    """Verilen cari kodlarını firma/tedarikçi olarak ekler/günceller. (added, updated). Elle içe aktarma ve
    otomatik senkronizasyon aynı çekirdeği kullanır."""
    data = mikro.cari_by_codes(codes)
    links = _links(conn, 'cari')
    added = updated = 0
    for code in codes:
        c = data.get(code)
        if not c:
            continue
        name = (c['cari_unvan1'] or code).strip()[:200]
        supplier = 1 if c['tip'] == 'tedarikci' else 0
        vals = dict(name=name, tax_office=(c.get('cari_vdaire_adi') or '').strip() or None, tax_no=c.get('vergi_no'),
                    phone=(c.get('cari_CepTel') or '').strip() or None, email=(c.get('cari_EMail') or '').strip() or None,
                    website=(c.get('cari_wwwadresi') or '').strip() or None)
        lk = links.get(code)
        cid = lk['local_id'] if lk and conn.execute('SELECT 1 FROM companies WHERE id = ?', (lk['local_id'],)).fetchone() else None
        # Aynı ada sahip firma zaten varsa (ör. elle eklenmiş) onu eşle — companies.name UNIQUE (NOCASE) olduğu için
        # yeni INSERT çakışır; mevcut kaydı güncelleyip bağlarız (mükerrer firma oluşturmadan).
        if cid is None:
            existing = conn.execute('SELECT id FROM companies WHERE name = ? COLLATE NOCASE', (name,)).fetchone()
            cid = existing[0] if existing else None
        if cid is not None:
            conn.execute('''UPDATE companies SET name = ?, tax_office = ?, tax_no = ?, phone = ?, email = ?, website = ?,
                            is_supplier = ? WHERE id = ?''',
                         (*vals.values(), supplier, cid))
            _link(conn, 'cari', code, cid, name, new=not (lk and lk['local_id'] == cid))
            updated += 1
        else:
            cid = conn.execute('''INSERT INTO companies (name, tax_office, tax_no, phone, email, website, note, active,
                                  created_by, created_at, is_supplier) VALUES (?,?,?,?,?,?,?,1,?,?,?)''',
                               (*vals.values(), f'Mikro ERP: {code}', user_id, db.now(), supplier)).lastrowid
            _link(conn, 'cari', code, cid, name, new=True)
            added += 1
        city = (c.get('il') or '').strip() or None
        addr = ', '.join(x for x in ((c.get('cadde') or '').strip(), (c.get('ilce') or '').strip()) if x) or None
        if (addr or city) and not conn.execute('SELECT 1 FROM company_addresses WHERE company_id = ?', (cid,)).fetchone():
            conn.execute('INSERT INTO company_addresses (company_id, label, address, city, created_at) VALUES (?,?,?,?,?)',
                         (cid, 'Merkez', addr or city, city, db.now()))
    return added, updated


@router.post('/import/stok')
def import_stok(body: StokImportIn, user=Depends(mikro_user), conn=db.DB):
    """Seçilen stokları MRP malzemelerine aktarır; Mikro'daki güncel miktarı Ana Depo'ya sayım olarak yazar."""
    _manager(user)
    if body.type not in STOK_TYPES:
        raise HTTPException(400, 'Geçersiz malzeme tipi')
    if not body.codes:
        raise HTTPException(400, 'Aktarılacak stok seçin')
    wid = body.warehouse_id
    if not wid:
        row = conn.execute('SELECT id FROM warehouses WHERE active = 1 ORDER BY id LIMIT 1').fetchone()
        wid = row[0] if row else None
    if body.set_stock and not wid:
        raise HTTPException(400, 'Depo bulunamadı; önce MRP’de bir depo tanımlayın')
    data = mikro.stok_by_codes(body.codes[:2000])
    links = _links(conn, 'stok')
    used_codes = {r[0] for r in conn.execute('SELECT code FROM products')}
    added = updated = 0
    from .mrp import add_move, depot_stock
    for code in body.codes:
        s = data.get(code)
        if not s:
            continue
        name = (s['sto_isim'] or code).strip()[:200]
        unit = _norm_unit(s['sto_birim1_ad'])
        barcode = (s.get('barkod') or '').strip()[:64] or None
        brand = (s.get('sto_marka_kodu') or '').strip()[:80] or None
        lk = links.get(code)
        pid = lk['local_id'] if lk and conn.execute('SELECT 1 FROM products WHERE id = ?', (lk['local_id'],)).fetchone() else None
        if pid:
            conn.execute('UPDATE products SET name = ?, type = ?, unit = ?, barcode = COALESCE(?, barcode), brand = COALESCE(?, brand) WHERE id = ?',
                         (name, body.type, unit, barcode, brand, pid))
            _link(conn, 'stok', code, pid, name, new=False)
            updated += 1
        else:
            pcode = code if code not in used_codes else f'MK-{code}'
            pcode = pcode[:24]
            pid = bom.create(conn, pcode, name, body.type, unit, description=f'Mikro ERP: {code}')
            if barcode:
                conn.execute('UPDATE products SET barcode = ? WHERE id = ?', (barcode, pid))
            if brand:
                conn.execute('UPDATE products SET brand = ? WHERE id = ?', (brand, pid))
            used_codes.add(pcode)
            _link(conn, 'stok', code, pid, name, new=True)
            added += 1
        if body.set_stock and wid:   # Mikro'daki güncel miktara eşitle (tek yönlü): fark kadar sayım hareketi
            target = round(float(s.get('miktar') or 0), 3)
            have = depot_stock(conn, pid, wid)
            delta = round(target - have, 4)
            if abs(delta) > 1e-9:
                add_move(conn, pid, wid, 'SAYIM', delta, user['id'], reason=f'Mikro ERP senkron: {code} → {target:g}')
    db.audit(conn, user['id'], 'Mikro ERP stok aktardı', 'product', None, f'{added} yeni, {updated} güncel ({spares.TYPES.get(body.type)})')
    return {'added': added, 'updated': updated}


# ---------- Faturalar (alış / satış) ----------
class FatImportIn(BaseModel):
    evraks: list[str]
    warehouse_id: Optional[int] = None


def _fat_list(kind, q, conn, show_imported=False):
    docs = mikro.list_faturalar(kind, q, 1000)
    if kind == 'alis':   # alış faturaları Satın Alma › Fatura İrsaliye (material_docs) altında tutulur
        links = {r['mikro_code']: r for r in db.rows(conn.execute(
            "SELECT mikro_code, local_id AS lid, imported_at, updated_at FROM mikro_links WHERE kind = 'alis_fat'"))}
    else:                # satış faturaları Satış Yönetimi (invoices) altında
        links = {r['mikro_code']: r for r in db.rows(conn.execute(
            "SELECT mikro_evrak AS mikro_code, id AS lid, imported_at, updated_at FROM "
            "(SELECT mikro_evrak, id, created_at AS imported_at, updated_at FROM invoices WHERE source = 'mikro' AND kind = 'satis')"))}
    for d in docs:
        lk = links.get(d['evrak'])
        d['imported'] = bool(lk)
        d['local_id'] = lk['lid'] if lk else None
        d['imported_at'] = (lk['updated_at'] or lk['imported_at']) if lk else None
    return _hide_imported(docs, show_imported)


@router.get('/alis')
def alis(q: str = '', show_imported: bool = False, user=Depends(mikro_user), conn=db.DB):
    if not mikro.configured():
        raise HTTPException(400, 'Mikro ERP bağlantısı tanımlı değil')
    try:
        return _fat_list('alis', q, conn, show_imported)
    except Exception as err:
        raise _read_error(err)


@router.get('/satis')
def satis(q: str = '', show_imported: bool = False, user=Depends(mikro_user), conn=db.DB):
    if not mikro.configured():
        raise HTTPException(400, 'Mikro ERP bağlantısı tanımlı değil')
    try:
        return _fat_list('satis', q, conn, show_imported)
    except Exception as err:
        raise _read_error(err)


def _resolve_company(conn, cari, names):
    """Mikro cari → yerel firma (varsa) ve anlık ünvan."""
    company_id = None
    if cari:
        r = conn.execute("SELECT local_id FROM mikro_links WHERE kind = 'cari' AND mikro_code = ?", (cari,)).fetchone()
        if r and conn.execute('SELECT 1 FROM companies WHERE id = ?', (r[0],)).fetchone():
            company_id = r[0]
    cari_ad = (names.get(cari, {}).get('cari_unvan1') if cari else None) or cari or '—'
    return company_id, cari_ad[:200]


def _import_faturalar(kind, body, user, conn):
    _manager(user)
    if not body.evraks:
        raise HTTPException(400, 'Aktarılacak fatura seçin')
    wid = body.warehouse_id or invoices.default_warehouse(conn)
    if not wid:
        raise HTTPException(400, 'Depo bulunamadı; önce MRP’de bir depo tanımlayın')
    data = mikro.fatura_lines(kind, body.evraks[:2000])
    caris = {v['head']['cari'] for v in data.values() if v['head'].get('cari')}
    names = mikro.cari_by_codes(list(caris)) if caris else {}
    return (_import_alis if kind == 'alis' else _import_satis)(body, data, names, wid, user, conn)


def _import_alis(body, data, names, wid, user, conn):
    """Alış faturaları → Satın Alma › Fatura İrsaliye (material_docs) + Ana Depo'ya stok GİRİŞİ.
    Böylece Satın Alma modülünde görünür. Mükerrer/yeniden aktarımda eski kayıt (belge + hareketler) geri alınıp yenilenir."""
    from datetime import date
    from .mrp import add_move
    linked = {r['mikro_code']: r['local_id'] for r in db.rows(conn.execute("SELECT mikro_code, local_id FROM mikro_links WHERE kind = 'alis_fat'"))}
    added = updated = unmapped = 0
    for e in body.evraks:
        pack = data.get(e)
        if not pack:
            continue
        head, lines = pack['head'], pack['lines']
        company_id, cari_ad = _resolve_company(conn, head.get('cari'), names)
        # Eski (invoices tabanlı) alış kaydı varsa migre et: stok hareketlerini geri al ve sil.
        old = conn.execute("SELECT id FROM invoices WHERE source = 'mikro' AND kind = 'alis' AND mikro_evrak = ?", (e,)).fetchone()
        if old:
            invoices.revert_stock(conn, old[0])
            conn.execute('DELETE FROM invoices WHERE id = ?', (old[0],))
        is_upd = e in linked
        if is_upd:   # mevcut belge + hareketlerini sil (yeniden yaz)
            conn.execute('DELETE FROM material_moves WHERE doc_id = ?', (linked[e],))
            conn.execute('DELETE FROM material_docs WHERE id = ?', (linked[e],))
        number = (head.get('belge') or e)[:60]
        idate = str(head.get('belge_tarih') or head.get('tarih') or '')[:10] or date.today().isoformat()
        amount = round(sum((ln.get('tutar') or 0) for ln in lines), 2)
        did = conn.execute('''INSERT INTO material_docs (kind, number, doc_date, company_id, supplier, amount, note, user_id, created_at, warehouse_id)
             VALUES ('FATURA',?,?,?,?,?,?,?,?,?)''',
             (number, idate, company_id, cari_ad, amount, f'Mikro ERP alış faturası: {e}', user['id'], db.now(), wid)).lastrowid
        for ln in lines:
            pid = invoices.map_product(conn, ln.get('stok'))
            qty = ln.get('miktar') or 0
            if not pid or qty <= 0:
                unmapped += int(not pid)
                continue
            add_move(conn, pid, wid, 'GIRIS', qty, user['id'], unit_price=ln.get('fiyat') or None, doc_id=did,
                     reason=f'Mikro alış faturası: {number} · {cari_ad}')
        _link(conn, 'alis_fat', e, did, number)
        linked[e] = did
        updated += int(is_upd)
        added += int(not is_upd)
    db.audit(conn, user['id'], 'Mikro ERP alış faturası aktardı (Satın Alma)', 'material_doc', None,
             f'{added} yeni, {updated} güncel; {unmapped} eşleşmeyen satır')
    return {'added': added, 'updated': updated, 'unmapped': unmapped}


def _import_satis(body, data, names, wid, user, conn):
    """Satış faturaları → Satış Yönetimi (invoices) + Ana Depo'dan stok ÇIKIŞI."""
    added = updated = unmapped = 0
    for e in body.evraks:
        pack = data.get(e)
        if not pack:
            continue
        head, lines = pack['head'], pack['lines']
        company_id, cari_ad = _resolve_company(conn, head.get('cari'), names)
        ex = conn.execute("SELECT id FROM invoices WHERE source = 'mikro' AND kind = 'satis' AND mikro_evrak = ?", (e,)).fetchone()
        is_upd = bool(ex)
        if ex:
            invoices.revert_stock(conn, ex[0])
            conn.execute('DELETE FROM invoices WHERE id = ?', (ex[0],))
        number = (head.get('belge') or e)[:64]
        idate = str(head.get('belge_tarih') or head.get('tarih') or '')[:10] or None
        iid = conn.execute('''INSERT INTO invoices (kind, source, is_return, number, company_id, company_name, invoice_date,
             warehouse_id, currency, stock_applied, mikro_evrak, created_by, created_at)
             VALUES ('satis','mikro',0,?,?,?,?,?,'TRY',0,?,?,?)''',
             (number, company_id, cari_ad, idate, wid, e, user['id'], db.now())).lastrowid
        items = []
        for ln in lines:
            pid = invoices.map_product(conn, ln.get('stok'))
            if not pid:
                unmapped += 1
            items.append({'product_id': pid, 'mikro_stok': ln.get('stok'),
                          'description': (ln.get('stok_ad') or ln.get('aciklama') or ln.get('stok') or '—'),
                          'qty': ln.get('miktar') or 0, 'unit': ln.get('birim'), 'unit_price': ln.get('fiyat') or 0,
                          'vat_rate': 0})   # Mikro tutarı KDV hariç; içe aktarımda toplam = net
        invoices.save_items(conn, iid, items)
        invoices.apply_stock(conn, iid, user['id'])
        updated += int(is_upd)
        added += int(not is_upd)
    db.audit(conn, user['id'], 'Mikro ERP satış faturası aktardı', 'invoice', None,
             f'{added} yeni, {updated} güncel; {unmapped} eşleşmeyen satır')
    return {'added': added, 'updated': updated, 'unmapped': unmapped}


@router.post('/import/alis')
def import_alis(body: FatImportIn, user=Depends(mikro_user), conn=db.DB):
    return _import_faturalar('alis', body, user, conn)


@router.post('/import/satis')
def import_satis(body: FatImportIn, user=Depends(mikro_user), conn=db.DB):
    return _import_faturalar('satis', body, user, conn)


# ---------- Finans: banka hesapları, kasalar, finansal hareketler (Mikro → Finans, tek yönlü) ----------
class FinSyncIn(BaseModel):
    cari: bool = True   # eşleşen firmaların cari hareketleri de Finans'a işlensin


@router.get('/finans')
def finans(user=Depends(mikro_user), conn=db.DB):
    """Mikro'daki banka / kasa hesapları (Mikro ve Finans bakiyesiyle) ve hareket özeti."""
    if not mikro.configured():
        raise HTTPException(400, 'Mikro ERP bağlantısı tanımlı değil')
    from .. import mikro_finance
    try:
        return mikro_finance.preview(conn)
    except Exception as err:   # noqa: BLE001
        raise _read_error(err)


@router.post('/sync/finans')
def sync_finans(body: FinSyncIn, user=Depends(mikro_user), conn=db.DB):
    """Banka/kasa hesaplarını ve finansal hareketleri Finans modülüne senkronize eder (tekrar çalıştırılabilir)."""
    _manager(user)
    if not mikro.configured():
        raise HTTPException(400, 'Mikro ERP bağlantısı tanımlı değil')
    from .. import mikro_finance
    try:
        st = mikro_finance.sync(conn, include_cari=body.cari, user_id=user['id'])
    except Exception as err:   # noqa: BLE001
        raise _read_error(err)
    db.audit(conn, user['id'], 'Mikro ERP finans senkronu', 'finance', None,
             f"{st['eklenen']} yeni, {st['guncellenen']} güncel, {st['silinen']} silinen hareket")
    conn.commit()
    return st


@router.post('/reset-stock')
def reset_stock(user=Depends(mikro_user), conn=db.DB):
    """Daha önce 'Stok Aktarımı'nda sayım olarak yazılan Mikro senkron stok hareketlerini siler (stok sıfırlanır),
    böylece stok artık yalnızca alış/satış faturalarından oluşur. Fatura kaynaklı hareketlere DOKUNMAZ."""
    _manager(user)
    n = conn.execute("SELECT COUNT(*) FROM material_moves WHERE kind = 'SAYIM' AND reason LIKE 'Mikro ERP senkron%'").fetchone()[0]
    conn.execute("DELETE FROM material_moves WHERE kind = 'SAYIM' AND reason LIKE 'Mikro ERP senkron%'")
    db.audit(conn, user['id'], 'Mikro ERP senkron stoğunu sıfırladı', 'product', None, f'{n} sayım hareketi silindi')
    return {'deleted': n}


def auto_import_new(conn, kind):
    """Zamanlanmış senkronizasyon: Mikro’da olup henüz bağlanmamış YENİ kayıtları aktarır (ek niteliğinde, tek yönlü).
    kind='cari': yeni cariler. Stok ve faturalar malzeme tipi / depo / finansal seçim gerektirdiğinden elle aktarılır."""
    if kind != 'cari':
        return 0
    linked = set(_links(conn, 'cari').keys())
    codes = [c['cari_kod'] for c in mikro.list_cari('', limit=5000) if c['cari_kod'] not in linked]
    if not codes:
        return 0
    sys_uid = conn.execute('SELECT id FROM users WHERE deleted_at IS NULL ORDER BY id LIMIT 1').fetchone()[0]
    added, _ = _import_cari_codes(conn, codes, sys_uid)
    db.audit(conn, sys_uid, 'Mikro ERP otomatik senkron: yeni cari', 'company', None, f'{added} yeni cari')
    return added
