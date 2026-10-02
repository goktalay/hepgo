"""PDKS (personel devam kontrol) entegrasyonu: Firebird veritabanından giriş-çıkış hareketleri — YALNIZCA OKUMA.

Bağlantı Firebird ağ protokolüyledir (varsayılan 3050). Yerli istemci kütüphanesi (libfbclient) sunucuya kurulmadan,
proje içinde vendor/firebird/lib altından yüklenir (OCR'daki gibi). Veritabanına / cihaza hiçbir şey yazılmaz.

Şema cihaz yazılımına (ör. Fixap) göre değişebildiğinden tablo ve kolon adları çalışma anında RDB$ sistem
tablolarından bulunur ve bilinen Türkçe adlarla eşlenir. Böylece kolon adları birebir tutmasa da çalışır.
"""
import threading

from . import config

_LIB = str((config.BASE_DIR / 'vendor' / 'firebird' / 'lib').resolve())
_lock = threading.Lock()
_configured_driver = False


def available():
    """firebird-driver ve yerli istemci kütüphanesi yüklenebiliyor mu?"""
    try:
        import os
        _ensure_driver()
        return os.path.exists(f'{_LIB}/libfbclient.so')
    except Exception:
        return False


def _ensure_driver():
    """firebird-driver'a vendor'daki libfbclient yolunu bir kez tanıtır."""
    global _configured_driver
    if _configured_driver:
        return
    import ctypes, os
    # Bağımlılıkları (libtommath, libtomcrypt) önce global sembol tablosuna yükle ki libfbclient onları bulsun
    # (systemd altında LD_LIBRARY_PATH'e güvenmeden). Ardından firebird-driver'a tam yolu ver.
    os.environ.setdefault('LD_LIBRARY_PATH', _LIB)
    for dep in ('libtommath.so.1', 'libtomcrypt.so.1'):
        try:
            ctypes.CDLL(f'{_LIB}/{dep}', mode=ctypes.RTLD_GLOBAL)
        except OSError:
            pass
    from firebird.driver import driver_config
    driver_config.fb_client_library.value = f'{_LIB}/libfbclient.so'
    _configured_driver = True


def configured():
    return bool(config.PDKS_HOST and config.PDKS_DB and config.PDKS_USER and config.PDKS_PASSWORD)


def connect(timeout=8):
    """Salt okunur Firebird bağlantısı (bağlamsal; `with pdks.connect() as con:`). Ulaşılamayan adreste `timeout` sn sonra hata verir.
    firebird-driver'ın bağlantı zaman aşımı sürümlere göre değiştiğinden bağlanma ayrı iş parçacığında yapılır."""
    import threading
    _ensure_driver()
    from firebird.driver import connect as fb_connect
    dsn = f'{config.PDKS_HOST}/{config.PDKS_PORT}:{config.PDKS_DB}'
    box = {}

    def _run():
        try:
            box['con'] = fb_connect(dsn, user=config.PDKS_USER, password=config.PDKS_PASSWORD, charset='WIN1254')
        except BaseException as e:   # noqa: BLE001
            box['err'] = e
    th = threading.Thread(target=_run, daemon=True)   # daemon: ulaşılamayan adreste asılı kalsa da süreç beklemez
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f'{config.PDKS_HOST}:{config.PDKS_PORT} içinde {timeout} sn’de yanıt alınamadı')
    if 'err' in box:
        raise box['err']
    return box['con']


def _tables(cur):
    cur.execute("SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE RDB$VIEW_BLR IS NULL AND (RDB$SYSTEM_FLAG IS NULL OR RDB$SYSTEM_FLAG = 0)")
    return [r[0] for r in cur.fetchall()]


def _columns(cur, table):
    cur.execute("SELECT TRIM(RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME = ? ORDER BY RDB$FIELD_POSITION", (table,))
    return [r[0] for r in cur.fetchall()]


def test():
    """(ok, mesaj) — bağlantı ve okunabilen tablo sayısı. Şifre mesajda yer almaz."""
    if not configured():
        return False, 'Sunucu, veritabanı yolu, kullanıcı ve şifre girilmeli.'
    try:
        with _lock, connect() as con:
            cur = con.cursor()
            tables = _tables(cur)
        key = [t for t in tables if any(w in t.upper() for w in ('PERSONEL', 'GIRISCIKIS', 'GIRIS_CIKIS', 'CIHAZGECIS'))]
        return True, f'Bağlantı başarılı · {len(tables)} tablo' + (f' (ör. {", ".join(key[:4])})' if key else '')
    except Exception as e:   # noqa: BLE001 — kullanıcıya anlaşılır mesaj
        return False, _friendly(e)


def _friendly(e):
    msg = str(e)
    if config.PDKS_PASSWORD:
        msg = msg.replace(config.PDKS_PASSWORD, '***')
    low = msg.lower()
    if 'libfbclient' in low or 'client library' in low or 'cannot load' in low:
        return 'Firebird istemci kütüphanesi yüklenemedi (vendor/firebird/lib).'
    if 'login' in low or 'password' in low or 'user name' in low or '335544472' in msg:
        return 'Kullanıcı adı veya şifre hatalı.'
    if 'no such file' in low or 'not found' in low or 'cannot attach' in low or '335544344' in msg:
        return f'Veritabanı bulunamadı ya da yol yanlış: {config.PDKS_DB}'
    if 'yanıt alınamadı' in msg or 'network' in low or 'connection' in low or 'refused' in low or 'timed out' in low or 'host unknown' in low:
        return f'Sunucuya ulaşılamadı ({config.PDKS_HOST}:{config.PDKS_PORT}). IP / port, ağ ve güvenlik duvarını kontrol edin.'
    return f'Bağlanılamadı: {type(e).__name__} · {msg[:150]}'


# ---------- Şema keşfi: tablo / kolon adlarını bilinen alanlara eşle
def _pick(cols, *names):
    up = {c.upper(): c for c in cols}
    for n in names:
        if n in up:
            return up[n]
    for n in names:   # içeren
        for c in cols:
            if n in c.upper():
                return c
    return None


def schema(cur):
    """Keşfedilen şema: {'personnel': {table, cols...}, 'moves': {table, cols...}} | eksikse ilgili anahtar None."""
    tables = {t.upper(): t for t in _tables(cur)}
    out = {}
    # Personel tablosu (Fixap: PER_TANIM, P_* kolonları). Farklı kurulumlar için esnek seçim.
    pt = tables.get('PER_TANIM') or tables.get('PERSONEL') or next((v for k, v in tables.items() if ('PERSONEL' in k or k == 'PER_TANIM') and 'GRUP' not in k), None)
    if pt:
        c = _columns(cur, pt)
        out['personnel'] = {'table': pt, 'id': _pick(c, 'P_ID', 'PERSONEL_ID', 'ID', 'SICIL_ID'),
                            'name': _pick(c, 'P_AD', 'PERSONELADI', 'ADSOYAD', 'ADI'), 'surname': _pick(c, 'P_SOYAD', 'SOYADI', 'SOYAD'),
                            'card': _pick(c, 'P_KARTID', 'P_KARTNO', 'KARTID', 'KARTNO', 'KART_NO'), 'sicil': _pick(c, 'P_SICILNO', 'SICILNO', 'SICIL'),
                            'tc': _pick(c, 'P_TCNO', 'TCKIMLIKNO', 'TCNO'), 'dept': _pick(c, 'P_DEPARTMAN', 'DEPARTMAN_ID', 'DEPARTMAN'),
                            'title': _pick(c, 'P_UNVAN', 'UNVAN'), 'active': _pick(c, 'P_AKTIF', 'AKTIF', 'DURUM'),
                            'start': _pick(c, 'P_IS_BAS_TAR', 'ISEBASLAMA')}
    # Giriş-çıkış hareketleri (Fixap: PER_GIRISCIKIS → P_KART_ID, TARIH, SAAT; yön tutulmaz, sıradan türetilir)
    mt = (tables.get('PER_GIRISCIKIS') or tables.get('GIRISCIKIS') or tables.get('GIRIS_CIKIS')
          or next((v for k, v in tables.items() if 'GIRISCIKIS' in k and 'WC' not in k and 'YETKISIZ' not in k and 'VIEW' not in k), None))
    if mt:
        c = _columns(cur, mt)
        out['moves'] = {'table': mt, 'card': _pick(c, 'P_KART_ID', 'KARTID', 'KARTNO', 'KART_ID'),
                        'date': _pick(c, 'TARIH', 'GIRISTARIHI'), 'time': _pick(c, 'SAAT', 'SAATI'),
                        'direction': _pick(c, 'GIRIS_CIKIS', 'GECISTIPI', 'YON'), 'device': _pick(c, 'CIHAZ_ID', 'CIHAZID')}
    out['tables'] = sorted(tables.values())
    return out


# ---------- Yüksek seviye okuma: personel ve günlük giriş-çıkış (yön sıradan türetilir)
def fetch_personnel():
    """PDKS'deki personeller: [{kart_id, ad, soyad, sicil, tc, unvan, aktif, ise_baslama}]."""
    with _lock, connect() as con:
        cur = con.cursor()
        s = schema(cur)['personnel']
        if not s:
            return []
        cols = {k: s[k] for k in ('id', 'name', 'surname', 'card', 'sicil', 'tc', 'title', 'active', 'start') if s.get(k)}
        cur.execute(f'SELECT {", ".join(cols.values())} FROM {s["table"]}')
        keys = list(cols)
        out = []
        for row in cur.fetchall():
            d = dict(zip(keys, row))
            out.append({'kart_id': str(d.get('card')) if d.get('card') is not None else None,
                        'ad': (d.get('name') or '').strip(), 'soyad': (d.get('surname') or '').strip(),
                        'sicil': d.get('sicil'), 'tc': (str(d['tc']).strip() if d.get('tc') else None),
                        'unvan': d.get('title'), 'aktif': d.get('active') in (1, '1', True),
                        'ise_baslama': str(d['start'])[:10] if d.get('start') else None})
        return out


def fetch_scans(date_from, date_to):
    """Ham okumalar: {kart_id: [(tarih, 'HH:MM'), ...]} — tarih aralığı dahil (YYYY-MM-DD)."""
    with _lock, connect() as con:
        cur = con.cursor()
        s = schema(cur)['moves']
        if not s:
            return {}
        cur.execute(f'SELECT {s["card"]}, {s["date"]}, {s["time"]} FROM {s["table"]} '
                    f'WHERE {s["date"]} BETWEEN ? AND ? ORDER BY {s["card"]}, {s["date"]}, {s["time"]}',
                    (date_from, date_to))
        out = {}
        for card, d, t in cur.fetchall():
            out.setdefault(str(card), []).append((str(d)[:10], str(t)[:5] if t else ''))
        return out


def daily_attendance(date_from, date_to):
    """Kart başına gün başına: ilk okuma = giriş, son okuma = çıkış, okuma sayısı ve kabaca içeride süre (dk).
    {kart_id: {tarih: {giris, cikis, okuma, dakika}}}. Cihaz yön tutmadığından ilk/son okuma esas alınır."""
    scans = fetch_scans(date_from, date_to)
    out = {}
    for card, items in scans.items():
        byday = {}
        for d, t in items:
            byday.setdefault(d, []).append(t)
        days = {}
        for d, times in byday.items():
            times = sorted(x for x in times if x)
            if not times:
                continue
            giris, cikis = times[0], times[-1]
            mins = None
            if giris != cikis:
                gh, gm = int(giris[:2]), int(giris[3:5])
                ch, cm = int(cikis[:2]), int(cikis[3:5])
                mins = (ch * 60 + cm) - (gh * 60 + gm)
            days[d] = {'giris': giris, 'cikis': cikis if cikis != giris else None, 'okuma': len(times), 'dakika': mins}
        out[card] = days
    return out


def discover():
    """Test / kurulum ekranı için: bağlan, şemayı keşfet, birkaç örnek satır döndür (salt okuma)."""
    with _lock, connect() as con:
        cur = con.cursor()
        sc = schema(cur)
        sample = {}
        p = sc.get('personnel')
        if p and p['name']:
            cols = [p[k] for k in ('name', 'surname', 'card', 'sicil', 'dept') if p.get(k)]
            cur.execute(f'SELECT FIRST 5 {", ".join(cols)} FROM {p["table"]}')
            sample['personnel'] = {'columns': cols, 'rows': [list(r) for r in cur.fetchall()]}
        m = sc.get('moves')
        if m and (m['ts'] or m['date']):
            cols = [m[k] for k in ('person', 'card', 'ts', 'date', 'time', 'direction', 'device') if m.get(k)]
            order = m['ts'] or m['date']
            cur.execute(f'SELECT FIRST 5 {", ".join(cols)} FROM {m["table"]} ORDER BY {order} DESC')
            sample['moves'] = {'columns': cols, 'rows': [[str(v) for v in r] for r in cur.fetchall()]}
        return {'schema': sc, 'sample': sample}
