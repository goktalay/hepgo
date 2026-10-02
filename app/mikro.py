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


def query(sql, params=None, db=None):
    with connect(db) as conn:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchall()


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
