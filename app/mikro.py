"""Mikro ERP (MSSQL) tek yönlü veri aktarımı: bağlantı ve okuma yardımcıları.

Bizim sistem yalnızca OKUR (tek yönlü: Mikro → bizim sistem). Bağlantı bilgileri config/.env'dedir; şifre asla
loglanmaz ya da API ile dışarı verilmez. Aktarım kullanıcı seçimiyle yapılır (bkz. app/routers/mikro.py).
"""
from . import config

_TIMEOUT = 8


def configured():
    return bool(config.MIKRO_HOST and config.MIKRO_DB and config.MIKRO_USER and config.MIKRO_PASSWORD)


def connect(db=None):
    import pymssql
    return pymssql.connect(server=config.MIKRO_HOST, port=str(config.MIKRO_PORT), user=config.MIKRO_USER,
                           password=config.MIKRO_PASSWORD, database=db or config.MIKRO_DB or 'master',
                           timeout=_TIMEOUT, login_timeout=_TIMEOUT, charset='UTF-8', as_dict=True)


def _query_direct(sql, params=None, db=None):
    with connect(db) as conn:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchall()


def creds():
    """Bağlantı bilgileri (Program Ayarları › Entegrasyonlar'da merkezde saklanır). Uzak modda her istekle, kimliği
    doğrulanmış şifreli ajan kanalından fabrikadaki ajana iletilir (NVR ile aynı yöntem) — ajanın kendi .env'ine gerek kalmaz."""
    return {k: getattr(config, k) for k in ('MIKRO_HOST', 'MIKRO_PORT', 'MIKRO_DB', 'MIKRO_USER', 'MIKRO_PASSWORD')}


def query(sql, params=None, db=None):
    """Tüm Mikro okumalarının tek geçiş noktası. Uzak modda fabrikadaki ajana iletilir (merkez MSSQL'e bağlanmaz)."""
    if config.AGENT_MODE == 'remote':
        from . import devices
        return devices.call_sync('mikro.query', {'sql': sql, 'params': list(params) if params else None, 'db': db, 'cfg': creds()})
    return _query_direct(sql, params, db)


def ping():
    """Bağlantıyı ve sürüm/DB adını döndürür (bağlanamazsa hata mesajı)."""
    try:
        row = query('SELECT @@VERSION AS v, DB_NAME() AS db')[0]
        return {'ok': True, 'version': (row['v'] or '').split('\\n')[0], 'db': row['db']}
    except Exception as err:
        return {'ok': False, 'error': str(err)}


def databases():
    """MikroDB_* veritabanlarını listeler (firma seçimi için)."""
    rows = query("SELECT name FROM sys.databases WHERE name LIKE 'MikroDB%' OR name LIKE 'Mikro%' ORDER BY name", db='master')
    return [r['name'] for r in rows]


def tables(db=None):
    return [r['name'] for r in query("SELECT name FROM sys.tables ORDER BY name", db=db)]


def columns(table, db=None):
    return query("SELECT COLUMN_NAME AS name, DATA_TYPE AS type FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s ORDER BY ORDINAL_POSITION", (table,), db=db)


# ---------- Cari ve stok okuma (yalnızca okuma; tek yönlü Mikro → sistem)

def cari_type(kod):
    """Cari kod önekine göre: 320 satıcı → tedarikçi, 120 alıcı → müşteri, diğer → diğer (Türk tekdüzen hesap planı)."""
    p = (kod or '')[:3]
    return 'tedarikci' if p == '320' else 'musteri' if p == '120' else 'diger'


def list_cari(q='', limit=1000):
    like = f'%{q}%'
    rows = query(f"""SELECT TOP {int(limit)} c.cari_kod, c.cari_unvan1, c.cari_vdaire_adi, c.cari_vdaire_no,
            c.cari_VergiKimlikNo, c.cari_CepTel, c.cari_EMail, c.cari_wwwadresi,
            (SELECT TOP 1 a.adr_il FROM CARI_HESAP_ADRESLERI a WHERE a.adr_cari_kod = c.cari_kod ORDER BY a.adr_adres_no) AS il,
            (SELECT TOP 1 a.adr_ilce FROM CARI_HESAP_ADRESLERI a WHERE a.adr_cari_kod = c.cari_kod ORDER BY a.adr_adres_no) AS ilce
        FROM CARI_HESAPLAR c
        WHERE c.cari_iptal = 0 AND (c.cari_kod LIKE %s OR c.cari_unvan1 LIKE %s)
        ORDER BY c.cari_unvan1""", (like, like))
    for r in rows:
        r['tip'] = cari_type(r['cari_kod'])
        r['vergi_no'] = (r.get('cari_vdaire_no') or '').strip() or (r.get('cari_VergiKimlikNo') or '').strip() or None
    return rows


def cari_by_codes(codes):
    if not codes:
        return {}
    marks = ','.join(['%s'] * len(codes))
    rows = query(f"""SELECT c.cari_kod, c.cari_unvan1, c.cari_vdaire_adi, c.cari_vdaire_no, c.cari_VergiKimlikNo,
            c.cari_CepTel, c.cari_EMail, c.cari_wwwadresi,
            (SELECT TOP 1 a.adr_il FROM CARI_HESAP_ADRESLERI a WHERE a.adr_cari_kod = c.cari_kod ORDER BY a.adr_adres_no) AS il,
            (SELECT TOP 1 a.adr_ilce FROM CARI_HESAP_ADRESLERI a WHERE a.adr_cari_kod = c.cari_kod ORDER BY a.adr_adres_no) AS ilce,
            (SELECT TOP 1 a.adr_cadde FROM CARI_HESAP_ADRESLERI a WHERE a.adr_cari_kod = c.cari_kod ORDER BY a.adr_adres_no) AS cadde
        FROM CARI_HESAPLAR c WHERE c.cari_kod IN ({marks})""", tuple(codes))
    out = {}
    for r in rows:
        r['tip'] = cari_type(r['cari_kod'])
        r['vergi_no'] = (r.get('cari_vdaire_no') or '').strip() or (r.get('cari_VergiKimlikNo') or '').strip() or None
        out[r['cari_kod']] = r
    return out


_STOK_SELECT = """s.sto_kod, s.sto_isim, s.sto_birim1_ad, s.sto_marka_kodu, s.sto_anagrup_kod,
    (SELECT ISNULL(SUM(o.sho_GirisNormal + o.sho_GirisIade - o.sho_CikisNormal - o.sho_CikisIade), 0)
       FROM STOK_HAREKETLERI_OZET o WHERE o.sho_StokKodu = s.sto_kod) AS miktar,
    (SELECT TOP 1 b.bar_kodu FROM BARKOD_TANIMLARI b WHERE b.bar_stokkodu = s.sto_kod AND b.bar_iptal = 0) AS barkod"""


def list_stok(q='', limit=1000):
    like = f'%{q}%'
    return query(f"""SELECT TOP {int(limit)} {_STOK_SELECT} FROM STOKLAR s
        WHERE s.sto_iptal = 0 AND (s.sto_kod LIKE %s OR s.sto_isim LIKE %s OR s.sto_marka_kodu LIKE %s)
        ORDER BY s.sto_isim""", (like, like, like))


def stok_by_codes(codes):
    if not codes:
        return {}
    marks = ','.join(['%s'] * len(codes))
    rows = query(f"SELECT {_STOK_SELECT} FROM STOKLAR s WHERE s.sto_kod IN ({marks})", tuple(codes))
    return {r['sto_kod']: r for r in rows}


def hareket_tipleri(gun=1095):
    """TEŞHİS (salt-okunur): STOK_HAREKETLERI'ndeki hareketleri tip/evraktip/cins'e göre gruplar — sarf çıkış fişlerinin
    hangi evrak tipinde olduğunu bulmak için. Her grup: satır sayısı, toplam miktar, cari var mı, giriş/çıkış deposu,
    tarih aralığı ve örnek açıklamalar. Son `gun` günle sınırlı (varsayılan ~3 yıl)."""
    rows = query(f"""SELECT h.sth_tip AS tip, h.sth_evraktip AS evraktip, h.sth_cins AS cins, h.sth_normal_iade AS iade,
            CASE WHEN h.sth_cari_kodu IS NULL OR h.sth_cari_kodu = '' THEN 0 ELSE 1 END AS cari_var,
            CASE WHEN h.sth_giris_depo_no > 0 THEN 1 ELSE 0 END AS giris_depo,
            CASE WHEN h.sth_cikis_depo_no > 0 THEN 1 ELSE 0 END AS cikis_depo,
            COUNT(*) AS satir, ROUND(SUM(h.sth_miktar), 2) AS toplam_miktar,
            CONVERT(varchar(10), MIN(h.sth_tarih), 120) AS ilk, CONVERT(varchar(10), MAX(h.sth_tarih), 120) AS son
        FROM STOK_HAREKETLERI h
        WHERE h.sth_tarih >= DATEADD(day, -{int(gun)}, GETDATE())
        GROUP BY h.sth_tip, h.sth_evraktip, h.sth_cins, h.sth_normal_iade,
            CASE WHEN h.sth_cari_kodu IS NULL OR h.sth_cari_kodu = '' THEN 0 ELSE 1 END,
            CASE WHEN h.sth_giris_depo_no > 0 THEN 1 ELSE 0 END,
            CASE WHEN h.sth_cikis_depo_no > 0 THEN 1 ELSE 0 END
        ORDER BY h.sth_tip, h.sth_evraktip, satir DESC""")
    # Her (tip, evraktip) için birkaç örnek açıklama — tipin ne olduğunu adlandırmaya yardımcı
    samples = query(f"""SELECT tip, evraktip, aciklama FROM (
            SELECT h.sth_tip AS tip, h.sth_evraktip AS evraktip, h.sth_aciklama AS aciklama,
                   ROW_NUMBER() OVER (PARTITION BY h.sth_tip, h.sth_evraktip ORDER BY h.sth_tarih DESC) AS rn
            FROM STOK_HAREKETLERI h
            WHERE h.sth_tarih >= DATEADD(day, -{int(gun)}, GETDATE()) AND h.sth_aciklama <> ''
        ) t WHERE rn <= 3 ORDER BY tip, evraktip""")
    ex = {}
    for sr in samples:
        ex.setdefault((sr['tip'], sr['evraktip']), []).append((sr['aciklama'] or '').strip()[:60])
    for r in rows:
        r['ornek'] = ex.get((r['tip'], r['evraktip']), [])
    return rows


# ---------- Stok hareketleri (tüm giriş/çıkış — salt-okunur canlı görüntüleyici) ----------
# Mikro evrak tipi (sth_evraktip) → Türkçe etiket (en iyi çaba; bilinmeyen için "Evrak tipi N").
# Bu etiketler tahminidir; görüntüleyici ham evraktip değerini de gösterir.
EVRAKTIP_AD = {
    0: 'Stok Düzeltme', 2: 'Sayım', 6: 'Devir/Düzeltme', 12: 'Üretim',
    3: 'Alış İrsaliyesi', 13: 'Alış Faturası', 4: 'Satış Faturası', 1: 'Satış İrsaliyesi',
    25: 'Sayım Fazlası', 26: 'Sayım Eksiği', 14: 'Alış İade', 5: 'Satış İade',
    32: 'Depo Transfer (Çıkış)', 33: 'Depo Transfer (Giriş)', 50: 'Üretimden Giriş',
    51: 'Üretime Sarf', 70: 'Fire/Zaiyat',
}


def evraktip_ad(n):
    return EVRAKTIP_AD.get(n, f'Evrak tipi {n}')


def stok_hareketleri(codes, date_from=None, date_to=None, limit=5000):
    """SALT-OKUNUR: verilen Mikro stok kodları ve tarih aralığı için TÜM STOK_HAREKETLERI satırları — giriş ve
    çıkış (sarf, üretim, transfer, fatura, iade, sayım…). Yerele hiçbir şey yazmaz. Giriş/çıkış ayrımı sth_tip ile
    (0=giriş, 1=çıkış); miktar işaretli döner (+giriş, -çıkış). Belge: (seri, sıra, evraktip). STOKLAR ile stok adı
    için birleştirilir. Tarihe göre yeniden eskiye sıralanır, en çok `limit` satır."""
    if not codes:
        return []
    marks = ','.join(['%s'] * len(codes))
    params = list(codes) + [date_from, date_to]
    rows = query(f"""SELECT TOP {int(limit)} h.sth_stok_kod AS code, h.sth_tip AS tip, h.sth_evraktip AS evraktip,
            h.sth_cins AS cins, h.sth_normal_iade AS iade, h.sth_miktar AS miktar, ROUND(h.sth_tutar, 2) AS tutar,
            CONVERT(varchar(19), h.sth_tarih, 120) AS tarih, h.sth_aciklama AS aciklama, h.sth_cari_kodu AS cari,
            h.sth_giris_depo_no AS giris_depo, h.sth_cikis_depo_no AS cikis_depo,
            h.sth_evrakno_seri AS seri, h.sth_evrakno_sira AS sira, s.sto_isim AS name
        FROM STOK_HAREKETLERI h
        LEFT JOIN STOKLAR s ON s.sto_kod = h.sth_stok_kod
        WHERE h.sth_stok_kod IN ({marks}) AND h.sth_tarih >= %s AND h.sth_tarih < DATEADD(day, 1, %s)
        ORDER BY h.sth_tarih DESC""", tuple(params))
    out = []
    for r in rows:
        cari = (r.get('cari') or '').strip()
        giris = (r['tip'] == 0)
        qty = float(r.get('miktar') or 0)
        out.append({
            'code': r['code'], 'name': (r.get('name') or '').strip(),
            'date': r.get('tarih'), 'yon': 'giris' if giris else 'cikis',
            'evraktip': r['evraktip'], 'evraktip_ad': evraktip_ad(r['evraktip']),
            'miktar': qty if giris else -qty, 'tutar': r.get('tutar'),
            'aciklama': (r.get('aciklama') or '').strip(), 'cari': cari,
            'dis': bool(cari),   # cari kodu var → şirket dışı hareket; yok → şirket içi/üretim
            'seri': (r.get('seri') or '').strip(), 'sira': r.get('sira'),
            'giris_depo': r.get('giris_depo'), 'cikis_depo': r.get('cikis_depo'),
        })
    return out


def stok_hareketleri_ledger(codes, date_from, date_to):
    """DEFTER AKTARIMI (salt-okunur): verilen stok kodlarının [date_from, date_to] aralığındaki TÜM STOK_HAREKETLERI
    satırları — Mikro'nun benzersiz satır anahtarı (sth_RECno_RECno → mikro_rec) ile. İşaret uygulanmamış ham miktar
    döner; yönü sth_tip belirler (0 giriş, 1 çıkış, 2 sayım). Çağıran taraf (routers/mikro.import_moves) her satırı
    yerel material_moves'a yazar ve mikro_key='mikro:<mikro_rec>' ile tekilleştirir. Tarihe + satır anahtarına göre
    artan sıralanır (kronolojik işlem için). NOT: sth_RECno_RECno, STOK_HAREKETLERI'nin PK'sıdır; sütun adı farklıysa
    sorgu hata verir (bilinçli emniyet davranışı — aktarım yazmadan durur)."""
    if not codes:
        return []
    marks = ','.join(['%s'] * len(codes))
    params = list(codes) + [date_from, date_to]
    return query(f"""SELECT h.sth_RECno_RECno AS mikro_rec, h.sth_stok_kod AS code, h.sth_tip AS tip,
            h.sth_evraktip AS evraktip, h.sth_normal_iade AS iade, h.sth_miktar AS miktar,
            CONVERT(varchar(19), h.sth_tarih, 120) AS tarih, h.sth_aciklama AS aciklama
        FROM STOK_HAREKETLERI h
        WHERE h.sth_stok_kod IN ({marks}) AND h.sth_tarih >= %s AND h.sth_tarih < DATEADD(day, 1, %s)
        ORDER BY h.sth_tarih, h.sth_RECno_RECno""", tuple(params))


# ---------- Faturalar (alış / satış) ----------
# STOK_HAREKETLERI'nde fatura satırları: cins=0, normal (iade değil).
#   Alış faturası: tip=0 (stok giriş), evraktip IN (3,13) — tedarikçiden.
#   Satış faturası: tip=1 (stok çıkış), evraktip=4 — müşteriye.
# Belge (fatura) = (seri, sıra, evraktip). İade faturaları (normal_iade=1) şimdilik kapsam dışı.
_FAT_WHERE = {
    'alis': 'h.sth_cins = 0 AND h.sth_tip = 0 AND h.sth_normal_iade = 0 AND h.sth_evraktip IN (3, 13)',
    'satis': 'h.sth_cins = 0 AND h.sth_tip = 1 AND h.sth_normal_iade = 0 AND h.sth_evraktip = 4',
}


def evrak_key(seri, sira, ev):
    return f'{(seri or "").strip()}|{sira}|{ev}'


def list_faturalar(kind, q='', limit=1000):
    """Fatura belgelerini (baş bilgi) döner: evrak, belge no, cari, tarih, satır sayısı, tutar."""
    where = _FAT_WHERE[kind]
    like = f'%{q}%'
    rows = query(f"""SELECT TOP {int(limit)} g.seri, g.sira, g.ev, g.belge, g.cari, g.tarih, g.satir, g.tutar,
            c.cari_unvan1 AS cari_ad
        FROM (
            SELECT h.sth_evrakno_seri AS seri, h.sth_evrakno_sira AS sira, h.sth_evraktip AS ev,
                   MAX(h.sth_belge_no) AS belge, MAX(h.sth_cari_kodu) AS cari, MAX(h.sth_tarih) AS tarih,
                   COUNT(*) AS satir, ROUND(SUM(h.sth_tutar), 2) AS tutar
            FROM STOK_HAREKETLERI h
            WHERE {where} AND h.sth_cari_kodu <> ''
            GROUP BY h.sth_evrakno_seri, h.sth_evrakno_sira, h.sth_evraktip
        ) g
        LEFT JOIN CARI_HESAPLAR c ON c.cari_kod = g.cari
        WHERE (g.belge LIKE %s OR g.cari LIKE %s OR c.cari_unvan1 LIKE %s OR g.seri LIKE %s)
        ORDER BY g.tarih DESC""", (like, like, like, like))
    for r in rows:
        r['evrak'] = evrak_key(r['seri'], r['sira'], r['ev'])
        r['kind'] = kind
    return rows


def fatura_lines(kind, evraks):
    """Verilen evrak anahtarları için fatura satırlarını döner. evraks: 'seri|sira|ev' listesi.
    Sonuç: {evrak: {'head': {...}, 'lines': [...]}}"""
    if not evraks:
        return {}
    where = _FAT_WHERE[kind]
    keys = {}
    for e in evraks:
        seri, sira, ev = (e.split('|', 2) + ['', '', ''])[:3]
        keys[(seri, str(sira), str(ev))] = e
    siras = sorted({int(s) for (_, s, _) in keys if s.isdigit()})
    if not siras:
        return {}
    marks = ','.join(['%s'] * len(siras))
    rows = query(f"""SELECT h.sth_evrakno_seri AS seri, h.sth_evrakno_sira AS sira, h.sth_evraktip AS ev,
            h.sth_belge_no AS belge, h.sth_belge_tarih AS belge_tarih, h.sth_tarih AS tarih, h.sth_cari_kodu AS cari,
            h.sth_stok_kod AS stok, h.sth_aciklama AS aciklama, h.sth_miktar AS miktar, h.sth_birimfiyat AS fiyat,
            ROUND(h.sth_tutar, 2) AS tutar, h.sth_giris_depo_no AS giris_depo, h.sth_cikis_depo_no AS cikis_depo,
            (SELECT TOP 1 st.sto_isim FROM STOKLAR st WHERE st.sto_kod = h.sth_stok_kod) AS stok_ad,
            (SELECT TOP 1 st.sto_birim1_ad FROM STOKLAR st WHERE st.sto_kod = h.sth_stok_kod) AS birim
        FROM STOK_HAREKETLERI h
        WHERE {where} AND h.sth_evrakno_sira IN ({marks})
        ORDER BY h.sth_evrakno_sira""", tuple(siras))
    out = {}
    for r in rows:
        k = ((r['seri'] or '').strip(), str(r['sira']), str(r['ev']))
        if k not in keys:
            continue
        e = keys[k]
        d = out.setdefault(e, {'head': {'evrak': e, 'belge': r['belge'], 'belge_tarih': r['belge_tarih'],
                                        'tarih': r['tarih'], 'cari': r['cari']}, 'lines': []})
        d['lines'].append(r)
    return out


# ---------- Finans: banka hesapları, kasalar ve finansal hareketler (yalnızca okuma) ----------
DOVIZ = {0: 'TRY', 1: 'USD', 2: 'EUR', 3: 'GBP'}   # Mikro döviz cinsi (0 = ana döviz TL)


def list_bankalar():
    return query("""SELECT ban_kod AS kod, ban_ismi AS ad, ban_sube AS sube, ban_IBANKodu AS iban, ban_hesapno AS hesapno,
            ban_doviz_cinsi AS doviz, ban_iptal AS iptal FROM BANKALAR ORDER BY ban_kod""")


def list_kasalar():
    return query("SELECT kas_kod AS kod, kas_isim AS ad, kas_doviz_cinsi AS doviz, kas_iptal AS iptal FROM KASALAR ORDER BY kas_kod")


def list_fin_hareket():
    """Banka / kasa / cari hareketleri (iptaller hariç). cins: hareketin kendi hesabı (0 cari, 2 banka, 4 kasa…);
    kh/khkod: karşı hesap (havale ve kredi kartı ödemelerinde banka/kasa karşı taraftadır). tip: 0 borç, 1 alacak.
    Tutar: dc (döviz cinsi) 0 ise TL; dövizli satırda tutar dövizdir, TL karşılığı = tutar × kur (bkz. mikro_finance._tl)."""
    return query("""SELECT CAST(cha_Guid AS varchar(40)) AS guid, cha_tarihi AS tarih, cha_cari_cins AS cins, cha_kod AS kod,
            cha_kasa_hizmet AS kh, cha_kasa_hizkod AS khkod, cha_tip AS tip, cha_meblag AS tutar, cha_evrak_tip AS ev,
            cha_cinsi AS ci, cha_evrakno_seri AS seri, cha_evrakno_sira AS sira, cha_belge_no AS belge, cha_aciklama AS aciklama,
            cha_d_cins AS dc, cha_d_kur AS kur, cha_vade AS vade
        FROM CARI_HESAP_HAREKETLERI
        WHERE cha_iptal = 0 AND (cha_cari_cins IN (0, 2, 4) OR cha_kasa_hizmet IN (2, 4))
        ORDER BY cha_tarihi, cha_evrakno_sira""")


def list_coa():
    """Muhasebe hesap planı (kod → ad)."""
    return query("SELECT muh_hesap_kod AS kod, muh_hesap_isim1 AS ad FROM MUHASEBE_HESAP_PLANI ORDER BY muh_hesap_kod")


def list_ledger():
    """Muhasebe fiş satırları (iptaller hariç). meblag0 işaretli: borç +, alacak − (ana döviz TL)."""
    return query("""SELECT CAST(fis_Guid AS varchar(40)) AS guid, fis_tarih AS tarih, fis_yevmiye_no AS yevmiye, fis_sira_no AS sira,
            fis_tur AS tur, fis_hesap_kod AS hesap, fis_aciklama1 AS aciklama, fis_meblag0 AS tutar, fis_tic_belgeno AS belge
        FROM MUHASEBE_FISLERI WHERE fis_iptal = 0 ORDER BY fis_tarih, fis_sira_no, fis_satir_no""")
