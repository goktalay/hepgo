"""Yazıcı kimliği: benzersiz anahtar MAC adresidir, IP değil.

IP geçici bir özelliktir (DHCP ile değişir, elektrik kesintisinde yazıcılar arasında takas olabilir); kayıtta yalnızca
"son görülen IP" olarak tutulur. Bir yazıcıya dosya gönderilmeden / baskı başlatılmadan önce hedef yazıcı MAC ile
doğrulanır (resolve_ip):

  1. Bilinen (son görülen) IP'deki cihazın kimliği okunur (identify): ARP tablosundaki MAC, yazıcının kendi
     API'sinin (Moonraker /machine/system_info) bildirdiği arayüz MAC'leri ve Moonraker ağ adı (K2Plus-XXXX —
     kablolu MAC'in son iki baytı). Kayıtlı MAC bunlarla uyuşursa o IP'ye gönderilir.
  2. Uyuşmazsa / cihaz yanıt vermezse ağ taranır (printer_driver.discover — uzak modda fabrikadaki ajan) ve
     MAC'i (ya da MAC'ten türeyen ağ adı) eşleşen cihazın güncel IP'si kaydedilip oraya gönderilir.
  3. Bulunamazsa açık hata: "Yazıcı ağda bulunamadı — MAC xx". MAC doğrulanmadan ASLA gönderilmez: aynı IP'ye
     taşınmış başka bir yazıcıya dosya gitmez.

Tarama sonucu kısa süre (SCAN_TTL sn) önbellekte tutulur; eşzamanlı istekler tek taramayı paylaşır.
Aynı IP'yi iki kayıt tutamaz: bir yazıcıya IP atanırken o IP'yi tutan eski kaydın IP'si boşaltılır (set_ip) —
printers.ip artık UNIQUE değildir, bu yüzden eski "UNIQUE constraint failed: printers.ip" hatası oluşmaz.
"""
import ipaddress
import re
import threading
import time

from . import config, db

SCAN_TTL = 60   # sn — tarama önbelleği
MAC_SOURCES = {'elle': 'Elle girildi', 'arp': 'Ağ taraması (ARP)', 'cihaz': 'Yazıcının kendi API’si',
               'kayit': 'Önceki kayıt (kaynak bilinmiyor)'}
_NETNAME = re.compile(r'^[A-Za-z0-9]+-([0-9A-Fa-f]{4})$')   # K2Plus-3697, GS03-E092 … (MAC'in son iki baytı)


class IdentityError(RuntimeError):
    """Kullanıcıya gösterilecek kimlik/çözümleme hatası."""


# ---------------------------------------------------------------- MAC yardımcıları

def normalize_mac(raw):
    """MAC'i büyük harf, iki nokta ayraçlı biçime getirir (FC:EE:28:0F:36:97). Boşsa None; geçersizse ValueError."""
    s = re.sub(r'[^0-9A-Fa-f]', '', str(raw or '')).upper()
    if not s:
        return None
    if len(s) != 12 or not re.fullmatch(r'[0-9A-F]{12}', s):
        raise ValueError(f'Geçersiz MAC adresi: {raw}')
    if s in ('000000000000', 'FFFFFFFFFFFF'):
        raise ValueError(f'Geçersiz MAC adresi: {raw}')
    return ':'.join(s[i:i + 2] for i in range(0, 12, 2))


def safe_mac(raw):
    try:
        return normalize_mac(raw)
    except ValueError:
        return None


def is_random(mac):
    """Yerel yönetilen (rastgele) MAC mi — Wi-Fi gizlilik adresi vb. Kalıcı kimlik sayılmaz, uyuşmazlık kanıtı da değildir.
    (K2 Plus'lar Wi-Fi'de rastgele MAC kullanıyor: PROD ağ taramasında 9E:…, 7A:… gibi adresler görüldü.)"""
    mac = safe_mac(mac)
    return bool(mac) and bool(int(mac[:2], 16) & 2)


def hw_from_mac(mac):
    """Kablolu MAC'ten K2 Plus ağ adı (K2Plus-XXXX)."""
    mac = safe_mac(mac)
    return f'K2Plus-{mac[-5:].replace(":", "")}' if mac else None


def is_netname(hw):
    return bool(hw and _NETNAME.match(str(hw).strip()))


def hw_matches(hw, mac):
    """Cihazın ağ adı (K2Plus-XXXX) MAC'in son iki baytıyla uyuşuyor mu. Ağ adı değilse None (bilinmiyor)."""
    m = _NETNAME.match(str(hw or '').strip())
    mac = safe_mac(mac)
    if not m or not mac:
        return None
    return m.group(1).upper() == mac[-5:].replace(':', '')


def verdict(ident, mac, aliases=()):
    """Bir IP'deki cihazın kimliği (identify çıktısı) kayıtlı MAC'e ait mi:
    'mac' (tam MAC eşleşti) | 'hw' (ağ adı MAC'in son iki baytıyla eşleşti) | 'alias' (cihazın bildirdiği ad bu yazıcıya
    özgü kayıtlı ad — ağ adı elle sayıya çevrilmiş yazıcılar; MAC okunamadığında) | 'mismatch' (BAŞKA cihaz) | 'unknown'."""
    mac = safe_mac(mac)
    if not ident or not mac:
        return 'unknown'
    device = {m for m in (safe_mac(x) for x in (ident.get('macs') or [])) if m}   # cihazın kendi arayüz listesi (tam)
    arp = safe_mac(ident.get('arp_mac') or ident.get('mac'))                      # ulaşılan arayüz (Wi-Fi olabilir)
    if mac in device or mac == arp:
        return 'mac'
    hm = hw_matches(ident.get('hw'), mac)
    if hm is True:
        return 'hw'     # aynı yazıcı, başka arayüzünden (ör. Wi-Fi) ulaşılmış
    if hm is False:
        return 'mismatch'
    if device:
        return 'mismatch'   # cihaz tüm arayüz MAC'lerini bildirdi ve bizimki yok
    if arp and not is_random(arp):
        return 'mismatch'   # ulaşılan arayüzün kalıcı (üretici) MAC'i başka
    hw = str(ident.get('hw') or '').strip().upper()
    if hw and hw in {str(a).strip().upper() for a in aliases if a}:
        return 'alias'
    return 'unknown'        # yalnız rastgele Wi-Fi MAC'i görüldü: kanıt yok → doğrulanmadı (taramaya)


# ---------------------------------------------------------------- cihaz kimliği (yerel / ajan)

def arp_mac(ip):
    """Komşu (ARP) tablosundaki MAC; yoksa None. /proc/net/arp okunur (alt süreç yok)."""
    try:
        with open('/proc/net/arp') as f:
            next(f, None)
            for line in f:
                p = line.split()
                if len(p) >= 4 and p[0] == ip and p[2] != '0x0':
                    return safe_mac(p[3])
    except OSError:
        pass
    return None


def _moonraker_macs(ip):
    """Yazıcının kendi API'si: Moonraker /machine/system_info → ağ arayüzlerinin MAC'leri."""
    import httpx
    from .printer_driver import MOONRAKER_PORT, TIMEOUT
    try:
        r = httpx.get(f'http://{ip}:{MOONRAKER_PORT}/machine/system_info', timeout=TIMEOUT)
        net = (((r.json() or {}).get('result') or {}).get('system_info') or {}).get('network') or {}
    except Exception:   # noqa: BLE001 — Moonraker kapalı / eski sürüm
        return []
    out = []
    for name, itf in sorted(net.items(), key=lambda kv: not str(kv[0]).startswith(('eth', 'en'))):   # kablolu önce
        if str(name).startswith(('lo', 'docker', 'veth', 'br')) or not isinstance(itf, dict):
            continue
        m = safe_mac(itf.get('mac_address'))
        if m and m not in out:
            out.append(m)
    return out


def identify_local(ip):
    """Bu makineden (sunucu ya da fabrikadaki ajan) IP'deki cihazın kimliği."""
    from . import printer_driver as pd
    reachable = pd._port_open(ip, pd.MOONRAKER_PORT) or pd._port_open(ip, pd.CREALITY_WS_PORT)   # ARP girdisini de tazeler
    if not reachable:
        return {'ip': ip, 'reachable': False, 'arp_mac': arp_mac(ip), 'macs': [], 'hw': None}
    return {'ip': ip, 'reachable': True, 'arp_mac': arp_mac(ip), 'macs': _moonraker_macs(ip), 'hw': pd.hardware_id(ip)}


def identify(ip):
    """IP'deki cihazın kimliği. Uzak modda ajanda okunur; ajan eskiyse (printer.identify yok) printer.probe'un
    Moonraker ağ adıyla yetinilir (yalnız ad doğrulaması)."""
    if not ip:
        return None
    if config.AGENT_MODE != 'remote':
        return identify_local(ip)
    from . import devices
    try:
        return devices.call_sync('printer.identify', {'ip': ip}, timeout=20)
    except Exception as e:   # noqa: BLE001
        if 'bilinmeyen' not in str(e).lower():
            raise
    live = devices.call_sync('printer.probe', {'ip': ip}, timeout=15)
    hw = live.get('hostname') if isinstance(live, dict) and live.get('source') == 'moonraker' else None
    return {'ip': ip, 'reachable': bool(live), 'arp_mac': None, 'macs': [], 'hw': hw, 'legacy': True}


# ---------------------------------------------------------------- tarama önbelleği (tek uçuş)

_scan_lock = threading.Lock()
_scan_cache = {'t': 0.0, 'v': None}


def scan(max_age=SCAN_TTL):
    """Ağ taraması (printer_driver.discover); sonuç max_age sn önbellekte. Aynı anda gelen istekler kilitte bekler
    ve biten taramanın sonucunu kullanır (tek tarama). (found, taze_mi) döner."""
    with _scan_lock:
        if _scan_cache['v'] is not None and time.monotonic() - _scan_cache['t'] < max_age:
            return _scan_cache['v'], False
        from . import printer_driver
        found = printer_driver.discover() or []
        _scan_cache.update(t=time.monotonic(), v=found)
        return found, True


def invalidate_scan():
    _scan_cache.update(t=0.0, v=None)


def _entry_keys(live):
    live = live if isinstance(live, dict) else {}
    macs = {m for m in (safe_mac(x) for x in (live.get('macs') or [])) if m}
    if safe_mac(live.get('mac')):
        macs.add(safe_mac(live.get('mac')))
    return macs, (live.get('hw') or None)


def find_in_scan(found, mac, aliases=()):
    """Taramada MAC'i eşleşen cihazın IP'si: önce tam MAC, sonra MAC'ten türeyen ağ adı, en son (cihazın MAC'i
    okunamadıysa) yazıcıya özgü kayıtlı ad. Yoksa None."""
    mac = safe_mac(mac)
    if not mac:
        return None
    al = {str(a).strip().upper() for a in aliases if a}
    strong, weak, alias = [], [], []
    for ip, live in found or []:
        macs, hw = _entry_keys(live)
        if mac in macs:
            strong.append(ip)
        elif hw_matches(hw, mac):
            weak.append(ip)
        elif hw and hw_matches(hw, mac) is None and str(hw).strip().upper() in al \
                and not any(not is_random(m) for m in macs):   # ad tutuyor, kalıcı başka MAC görülmedi
            alias.append(ip)
    for group in (strong, weak, alias):
        if group:
            return sorted(group, key=lambda x: ipaddress.IPv4Address(x))[0]
    return None


# ---------------------------------------------------------------- kayıt güncelleme

def set_ip(conn, pid, ip, now=None):
    """Yazıcının son görülen IP'sini yazar; aynı IP'yi tutan BAŞKA kayıtların IP'si boşaltılır (o IP artık onların
    değil). Boşaltılan kayıtların id listesini döner."""
    cleared = []
    if ip:
        cleared = [r[0] for r in conn.execute('SELECT id FROM printers WHERE ip = ? AND id != ?', (ip, pid))]
        if cleared:
            conn.execute('UPDATE printers SET ip = NULL WHERE ip = ? AND id != ?', (ip, pid))
    conn.execute('UPDATE printers SET ip = ? WHERE id = ?', (ip, pid))
    return cleared


def _unique_aliases(conn, p):
    """Yazıcının ağ adı dışındaki kayıtlı adları (hw_alias / sayısal hw_id) — yalnız başka hiçbir yazıcıda yoksa."""
    out = []
    for a in (p.get('hw_id'), p.get('hw_alias')):
        if not a or is_netname(a):
            continue
        n = conn.execute('SELECT COUNT(*) FROM printers WHERE id != ? AND (upper(hw_id) = upper(?) OR upper(hw_alias) = upper(?))',
                         (p['id'], a, a)).fetchone()[0]
        if not n:
            out.append(a)
    return tuple(out)


def _mark_checked(pid, ip, method):
    with db.connect() as conn:
        set_ip(conn, pid, ip)
        conn.execute('UPDATE printers SET mac_checked_at = ? WHERE id = ?', (db.now(), pid))
        conn.commit()


def resolve_ip(pid, user_id=None):
    """Yazıcıya gönderim öncesi hedef IP'yi MAC ile çözer ve doğrular. {'ip','mac','method','moved_from'} döner;
    doğrulanamazsa IdentityError. method: 'mac' | 'hw' (bilinen IP'de doğrulandı) | 'scan' (ağ taramasıyla bulundu)."""
    with db.connect() as conn:
        p = db.row(conn.execute('SELECT id, name, ip, mac, hw_id, hw_alias FROM printers WHERE id = ?', (pid,)))
        aliases = _unique_aliases(conn, p) if p else ()
    if not p:
        raise IdentityError('Yazıcı bulunamadı')
    mac = safe_mac(p['mac'])
    if not mac:
        raise IdentityError(f'{p["name"]}: MAC adresi tanımlı değil — önce Yazıcı Yönetimi’nde “MAC’i Öğren” ile MAC’i '
                            'kaydedin. MAC doğrulanmadan dosya gönderilmez.')
    if p['ip']:
        try:
            v = verdict(identify(p['ip']), mac, aliases)
        except Exception:   # noqa: BLE001 — ajana/yazıcıya ulaşılamadı: taramayla dene
            v = 'unknown'
        if v in ('mac', 'hw', 'alias'):
            _mark_checked(pid, p['ip'], v)
            return {'ip': p['ip'], 'mac': mac, 'method': v, 'moved_from': None}
    # Bilinen IP'de bu yazıcı yok (ya da IP bilinmiyor): ağı tara. Önbellekteki sonuçta yoksa bir kez taze tarama.
    try:
        found, fresh = scan()
        ip = find_in_scan(found, mac, aliases)
        if not ip and not fresh:
            found, _ = scan(max_age=0)
            ip = find_in_scan(found, mac, aliases)
    except Exception as e:   # noqa: BLE001
        raise IdentityError(f'Yazıcı MAC ile doğrulanamadı ve ağ taraması yapılamadı ({e}) — MAC {mac}. '
                            'Gönderim yapılmadı.') from e
    if not ip:
        raise IdentityError(f'Yazıcı ağda bulunamadı — MAC {mac} ({p["name"]}). Gönderim yapılmadı.')
    with db.connect() as conn:
        cleared = set_ip(conn, pid, ip)
        conn.execute('UPDATE printers SET mac_checked_at = ?, last_seen = COALESCE(last_seen, ?) WHERE id = ?', (db.now(), db.now(), pid))
        if p['ip'] != ip:
            db.audit(conn, user_id, 'Yazıcının IP adresi MAC ile bulundu (ağ taraması)', 'printer', pid,
                     f'{p["name"]} · MAC {mac}: {p["ip"] or "—"} → {ip}' + (f' · IP’si boşaltılan kayıt: {cleared}' if cleared else ''))
        conn.commit()
    return {'ip': ip, 'mac': mac, 'method': 'scan', 'moved_from': p['ip'] if p['ip'] != ip else None}


def _pick_primary_mac(ident, known_hw=None):
    """Cihaz kimliğinden yazıcının birincil (kablolu) MAC'i ve kaynağı. Ağ adı varsa son iki baytı ona uyan MAC seçilir
    (Wi-Fi MAC'i kalıcı kimlik yapılmaz)."""
    cands = [(m, 'cihaz') for m in (safe_mac(x) for x in (ident.get('macs') or [])) if m]
    a = safe_mac(ident.get('arp_mac') or ident.get('mac'))
    if a and a not in [c[0] for c in cands]:
        cands.insert(0, (a, 'arp'))
    else:
        cands = [(m, 'arp' if m == a else s) for m, s in cands]
    hw = ident.get('hw') if is_netname(ident.get('hw')) else (known_hw if is_netname(known_hw) else None)
    if hw:
        for m, s in cands:
            if hw_matches(hw, m):
                return m, s
        return None, None
    # Ağ adı yok (ad elle sayıya çevrilmiş): rastgele (Wi-Fi gizlilik) MAC kalıcı kimlik yapılmaz; cihazın listesindeki
    # ilk kalıcı MAC (kablolu önce sıralı), yoksa ARP'deki kalıcı MAC
    for m, s in cands:
        if s == 'cihaz' and not is_random(m):
            return m, s
    if a and not is_random(a):
        return a, 'arp'
    return None, None


def learn_mac(pid, user_id=None):
    """MAC'i olmayan (ya da doğrulanacak) yazıcının MAC'ini cihazdan öğrenir: son görülen IP'deki cihaz okunur; ağ adı
    kayıtlı ağ adıyla çelişirse reddedilir (o IP'de başka yazıcı var). IP'de ulaşılamazsa kayıtlı ağ adıyla ağ taranır."""
    with db.connect() as conn:
        p = db.row(conn.execute('SELECT id, name, ip, mac, hw_id FROM printers WHERE id = ?', (pid,)))
    if not p:
        raise IdentityError('Yazıcı bulunamadı')
    known_hw = p['hw_id'] if is_netname(p['hw_id']) else None
    ident, ip = None, p['ip']
    if ip:
        ident = identify(ip)
        if ident and ident.get('reachable'):
            hw = ident.get('hw')
            if known_hw and is_netname(hw) and hw.upper() != known_hw.upper():
                ident = None   # bu IP'de başka bir yazıcı var → taramayla asıl cihazı ara
        else:
            ident = None
    if ident is None and known_hw:
        found, _ = scan(max_age=0)
        for sip, live in found or []:
            macs, hw = _entry_keys(live)
            if hw and hw.upper() == known_hw.upper():
                ip = sip
                ident = {'ip': sip, 'arp_mac': safe_mac((live or {}).get('mac')), 'macs': sorted(macs), 'hw': hw}
                if not macs:   # eski ajan taramada MAC vermiyor: cihazın kendisine sor
                    ident = identify(sip) or ident
                break
    if ident is None:
        raise IdentityError(f'{p["name"]}: cihaza ulaşılamadı; MAC okunamadı' + ('' if known_hw else ' (kayıtlı ağ adı da yok)'))
    mac, src = _pick_primary_mac(ident, known_hw)
    if not mac:
        raise IdentityError(f'{p["name"]}: cihazın MAC adresi okunamadı (ağ adı {ident.get("hw") or "—"}). '
                            'Fabrikadaki ajan güncel değilse güncelleyin ya da MAC’i elle girin.')
    if known_hw and hw_matches(known_hw, mac) is False:
        raise IdentityError(f'{p["name"]}: {ip} adresindeki cihazın MAC’i ({mac}) kayıtlı ağ adıyla ({known_hw}) uyuşmuyor — '
                            'bu IP’de başka bir yazıcı var.')
    with db.connect() as conn:
        other = db.row(conn.execute('SELECT id, name FROM printers WHERE mac = ? AND id != ?', (mac, pid)))
        if other:
            raise IdentityError(f'{mac} zaten “{other["name"]}” yazıcısında kayıtlı — {ip} adresindeki cihaz o yazıcı.')
        cleared = set_ip(conn, pid, ip)
        hw = ident.get('hw') if is_netname(ident.get('hw')) else None
        conn.execute('UPDATE printers SET mac = ?, mac_source = ?, mac_checked_at = ?, hw_id = COALESCE(hw_id, ?) WHERE id = ?',
                     (mac, src, db.now(), hw, pid))
        db.audit(conn, user_id, 'Yazıcının MAC adresini cihazdan öğrendi', 'printer', pid,
                 f'{p["name"]}: {mac} ({MAC_SOURCES.get(src, src)}) · IP {ip}' + (f' · IP’si boşaltılan kayıt: {cleared}' if cleared else ''))
        conn.commit()
    return {'mac': mac, 'source': src, 'ip': ip}


# ---------------------------------------------------------------- tarama sonucunu kayıtlara uygulama

def apply_scan(found, user_id=None, add_new=False):
    """Tarama sonuçlarını kayıtlarla MAC MERKEZLİ eşleştirir ve uygular (IP + canlı durum; eksik MAC/ağ adı doldurulur).
    Eşleşme sırası: tam MAC → MAC'ten türeyen ağ adı → kayıtlı ağ adı (hw_id / hw_alias) → IP (yalnız kimlikler
    çelişmiyorsa). Eşleşmeyen cihaz bir kaydın IP'sindeyse o kaydın IP'si boşaltılır (artık o IP'de değil);
    add_new ise yeni yazıcı olarak eklenir. {'found','added','moved','learned','cleared'} döner."""
    from . import printer_layout
    added, moved, learned, cleared_all = [], [], [], []
    # Tarama satırları; aynı cihaz iki IP'de göründüyse (kablolu + Wi-Fi) bir kez — kablolu (MAC'i ağ adına uyan) öncelikli
    rows = []
    for ip, live in (f for f in (found or []) if isinstance(f, (list, tuple)) and len(f) == 2 and isinstance(f[1], dict)):
        macs, hw = _entry_keys(live)
        eth = next((m for m in sorted(macs) if hw_matches(hw, m)), None)
        rows.append({'ip': ip, 'live': live, 'macs': macs, 'hw': hw, 'eth': eth})
    rows.sort(key=lambda s: (s['eth'] is None, ipaddress.IPv4Address(s['ip'])))
    scan, seen = [], set()
    for s in rows:
        ident = s['eth'] or (s['hw'].upper() if s['hw'] else None) or next(iter(sorted(s['macs'])), None)
        if ident:
            if ident in seen:
                continue
            seen.add(ident)
        scan.append(s)

    now = db.now()
    with db.connect() as conn:
        existing = db.rows(conn.execute('SELECT id, name, ip, mac, hw_id, hw_alias FROM printers'))
        by_id = {r['id']: r for r in existing}
        by_mac = {safe_mac(r['mac']): r['id'] for r in existing if safe_mac(r['mac'])}
        by_hw = {}
        for r in existing:
            for k in (r['hw_id'], r['hw_alias']):
                if k:
                    by_hw.setdefault(str(k).upper(), r['id'])
        by_ip = {r['ip']: r['id'] for r in existing if r['ip']}

        def conflicts(pid, s):
            r = by_id[pid]
            pm = safe_mac(r['mac'])
            if pm:
                if pm in s['macs']:
                    return False
                hm = hw_matches(s['hw'], pm)
                if hm is not None:
                    return not hm
                return any(not is_random(m) for m in s['macs'])   # kalıcı başka MAC: başka cihaz; rastgele MAC kanıt değil
            rh = {str(k).upper() for k in (r['hw_id'], r['hw_alias']) if k}
            return bool(s['hw'] and rh and s['hw'].upper() not in rh)

        assign = {}   # pid → tarama satırı
        taken = set()
        for stage in ('mac', 'hwmac', 'hw', 'ip'):
            for i, s in enumerate(scan):
                if i in taken:
                    continue
                pid = None
                if stage == 'mac':
                    pid = next((by_mac[m] for m in s['macs'] if m in by_mac), None)
                elif stage == 'hwmac' and s['hw']:
                    pid = next((p for m, p in by_mac.items() if hw_matches(s['hw'], m)), None)
                elif stage == 'hw' and s['hw']:
                    pid = by_hw.get(s['hw'].upper())
                    if pid is not None and conflicts(pid, s):
                        pid = None
                elif stage == 'ip':
                    pid = by_ip.get(s['ip'])
                    if pid is not None and conflicts(pid, s):
                        pid = None
                if pid is None or pid in assign:
                    continue
                assign[pid] = s
                taken.add(i)

        for pid, s in assign.items():
            r = by_id[pid]
            live = s['live']
            cleared = set_ip(conn, pid, s['ip'])
            cleared_all += cleared
            conn.execute('''UPDATE printers SET live_state = ?, live_progress = ?, live_file = ?, live_source = ?, last_seen = ?,
                            live_since = CASE WHEN live_state IS ? AND live_since IS NOT NULL THEN live_since ELSE ? END,
                            live_print_s = ?, model = COALESCE(model, ?) WHERE id = ?''',
                         (live.get('state'), live.get('progress'), live.get('file'), live.get('source'), now,
                          live.get('state'), now, live.get('print_s'), live.get('model'), pid))
            if r['ip'] != s['ip']:
                moved.append({'id': pid, 'name': r['name'], 'old': r['ip'], 'ip': s['ip']})
                db.audit(conn, user_id, 'Yazıcının IP adresini düzeltti (ağ taraması, MAC eşleşmesi)', 'printer', pid,
                         f"{r['name']}: {r['ip'] or '—'} → {s['ip']}")
            pm = safe_mac(r['mac'])
            if pm and (pm in s['macs'] or hw_matches(s['hw'], pm)):
                conn.execute('UPDATE printers SET mac_checked_at = ? WHERE id = ?', (now, pid))
            if not pm and s['eth'] and s['eth'] not in by_mac:   # MAC'i olmayan kayda cihazın kablolu MAC'i
                conn.execute("UPDATE printers SET mac = ?, mac_source = 'arp', mac_checked_at = ? WHERE id = ?", (s['eth'], now, pid))
                by_mac[s['eth']] = pid
                learned.append({'id': pid, 'name': r['name'], 'mac': s['eth']})
                db.audit(conn, user_id, 'Yazıcının MAC adresini ağ taramasından öğrendi', 'printer', pid, f"{r['name']}: {s['eth']}")
            if s['hw'] and not r['hw_id'] and is_netname(s['hw']):
                conn.execute('UPDATE printers SET hw_id = ? WHERE id = ?', (s['hw'], pid))

        count = conn.execute('SELECT COUNT(*) FROM printers').fetchone()[0]
        for i, s in enumerate(scan):
            if i in taken:
                continue
            holder = conn.execute('SELECT id, name FROM printers WHERE ip = ?', (s['ip'],)).fetchone()
            if holder and not add_new:
                # Bu IP'de artık kayıtlı yazıcı değil başka bir cihaz var: eski kaydın IP'si boşaltılır (yanlış cihaza gönderim olmasın)
                conn.execute('UPDATE printers SET ip = NULL WHERE id = ?', (holder[0],))
                cleared_all.append(holder[0])
                db.audit(conn, user_id, 'Yazıcının IP adresi boşaltıldı (IP’de başka cihaz)', 'printer', holder[0], f'{holder[1]}: {s["ip"]}')
            if not add_new:
                continue
            live = s['live']
            count += 1
            name = live.get('hostname') or f'K2 Plus {count:02d}'
            mac = s['eth'] if s['eth'] and s['eth'] not in by_mac else None
            cur = conn.execute('INSERT INTO printers (name, ip, hw_id, mac, mac_source, mac_checked_at, model, auto_added, created_at, '
                               'live_state, live_progress, live_file, live_source, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               (name, None, s['hw'], mac, 'arp' if mac else None, now if mac else None,
                                live.get('model') or 'Creality K2 Plus', 1, now, live.get('state'), live.get('progress'),
                                live.get('file'), live.get('source'), now))
            pid = cur.lastrowid
            cleared_all += set_ip(conn, pid, s['ip'])
            if mac:
                by_mac[mac] = pid
            db.audit(conn, user_id, 'Yazıcı otomatik ekledi', 'printer', pid, f"{name} ({s['ip']}{', MAC ' + mac if mac else ''})")
            added.append({'name': name, 'ip': s['ip'], 'mac': mac})
        if add_new:
            printer_layout.assign_missing(conn)
        conn.commit()
    return {'found': len(found or []), 'added': added, 'moved': moved, 'learned': learned, 'cleared': sorted(set(cleared_all))}


# ---------------------------------------------------------------- göç (db.init)

def migrate(conn):
    """MAC merkezli kimlik göçü (idempotent): printers.ip UNIQUE/NOT NULL kaldırılır (tablo yeniden kurulur, öncesinde
    tam yedek), park değerli IP'ler (#tasima-…, …#eski) boşaltılır, MAC'ler normalize edilir, aynı MAC'li kayıtlar
    güvenliyse birleştirilir ve printers.mac için UNIQUE (NULL'lar hariç) dizin kurulur. Rapor app_kv
    'printers.mac_migration' anahtarına yazılır (yalnız değişiklik olduysa). Rapor sözlüğü döner."""
    import json
    cols = {r[1] for r in conn.execute('PRAGMA table_info(printers)')}
    if not cols:
        return None
    for c in ('mac_source', 'mac_checked_at'):
        if c not in cols:
            conn.execute(f'ALTER TABLE printers ADD COLUMN {c} TEXT')
    rep = {'at': db.now(), 'rebuilt': False, 'ip_cleared': [], 'normalized': [], 'invalid': [], 'merged': [], 'conflicts': []}
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'printers'").fetchone()[0]
    if re.search(r'\bip\s+TEXT\s+NOT\s+NULL\s+UNIQUE', sql, re.I):
        _rebuild_without_ip_unique(conn, sql)
        rep['rebuilt'] = True
    # Geçici park değerleri (eski iki aşamalı IP yazımından kalan) → IP bilinmiyor
    for pid, ip in conn.execute("SELECT id, ip FROM printers WHERE ip LIKE '#%' OR ip LIKE '%#eski' OR ip = ''").fetchall():
        conn.execute('UPDATE printers SET ip = NULL WHERE id = ?', (pid,))
        rep['ip_cleared'].append({'id': pid, 'old': ip})
    # MAC normalize
    for pid, name, mac, src in conn.execute('SELECT id, name, mac, mac_source FROM printers WHERE mac IS NOT NULL').fetchall():
        try:
            norm = normalize_mac(mac)
        except ValueError:
            norm = None
            rep['invalid'].append({'id': pid, 'name': name, 'mac': mac})
            db.audit(conn, None, 'Geçersiz MAC kaldırıldı (göç; yazıcıda “MAC’i Öğren” ile yeniden alın)', 'printer', pid, f'{name}: {mac!r}')
        if norm != mac:
            conn.execute('UPDATE printers SET mac = ? WHERE id = ?', (norm, pid))
            if norm:
                rep['normalized'].append({'id': pid, 'old': mac, 'new': norm})
        if norm and not src:
            conn.execute("UPDATE printers SET mac_source = 'kayit' WHERE id = ?", (pid,))
    # Aynı MAC'li yinelenen kayıtlar
    for (mac,) in conn.execute('SELECT mac FROM printers WHERE mac IS NOT NULL GROUP BY mac HAVING COUNT(*) > 1').fetchall():
        _merge_group(conn, mac, rep)
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_printers_mac ON printers(mac) WHERE mac IS NOT NULL')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_printers_ip ON printers(ip)')
    if any(rep[k] for k in ('rebuilt', 'ip_cleared', 'normalized', 'invalid', 'merged', 'conflicts')):
        conn.execute("INSERT OR REPLACE INTO app_kv (k, v) VALUES ('printers.mac_migration', ?)", (json.dumps(rep, ensure_ascii=False),))
    conn.commit()
    return rep


def _rebuild_without_ip_unique(conn, sql):
    """SQLite sütun kısıtını değiştiremediği için printers tablosu yeniden kurulur: ip TEXT (boş olabilir, benzersiz değil).
    Veriler, dizinler ve diğer tabloların printers(id) bağları korunur; öncesinde tam veritabanı yedeği alınır."""
    import sqlite3
    from datetime import datetime
    new_sql, n = re.subn(r'\bip\s+TEXT\s+NOT\s+NULL\s+UNIQUE', 'ip              TEXT', sql, count=1, flags=re.I)
    if n != 1:
        raise RuntimeError('printers taşınamadı: beklenmeyen tablo tanımı')
    new_sql = re.sub(r'CREATE TABLE\s+(IF NOT EXISTS\s+)?"?printers"?', 'CREATE TABLE printers_yeni', new_sql, count=1)
    indexes = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'printers' AND sql IS NOT NULL")]
    before = conn.execute('SELECT COUNT(*) FROM printers').fetchone()[0]
    conn.commit()
    bdir = config.DATA_DIR / 'backups' / 'migration'
    bdir.mkdir(parents=True, exist_ok=True)
    dst = sqlite3.connect(bdir / f'before-printers-mac-{datetime.now():%Y%m%d-%H%M%S}.db')
    try:
        conn.backup(dst)
    finally:
        dst.close()
    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.executescript('BEGIN;\n' + new_sql + ';\n'
                           'INSERT INTO printers_yeni SELECT * FROM printers;\n'
                           'DROP TABLE printers;\n'
                           'ALTER TABLE printers_yeni RENAME TO printers;\n'
                           + ''.join(f'{i};\n' for i in indexes) + 'COMMIT;')
    finally:
        conn.execute('PRAGMA foreign_keys = ON')
    after = conn.execute('SELECT COUNT(*) FROM printers').fetchone()[0]
    bad = conn.execute('PRAGMA foreign_key_check').fetchall()
    if after != before or bad:
        raise RuntimeError(f'printers taşıma denetimi başarısız: {before} → {after}, bağ hatası {len(bad)}')


def _fk_refs(conn):
    """printers(id)'ye bağlı (tablo, sütun) çiftleri."""
    out = []
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
        for fk in conn.execute(f'PRAGMA foreign_key_list("{t}")').fetchall():
            if fk[2] == 'printers':
                out.append((t, fk[3]))
    return out


def _merge_group(conn, mac, rep):
    """Aynı MAC'li kayıtları güvenliyse tek kayıtta birleştirir: kalan kayıt = üzerinde iş olan, yoksa en son görülen,
    o da yoksa en eski. Bağlı kayıtlar (parça, olay, talep, olay kaydı, denetim izi) kalan kayda taşınır; boş alanlar
    diğerinden doldurulur. İki kayıtta da sürmekte olan iş varsa birleştirilmez: fazladan kaydın MAC'i boşaltılır ve
    çakışma raporlanır (veri kaybı yok)."""
    rows = db.rows(conn.execute('SELECT * FROM printers WHERE mac = ? ORDER BY id', (mac,)))
    busy = [r for r in rows if r['current_part_id']]
    if len(busy) > 1:
        keep = busy[0]
        for r in rows:
            if r['id'] != keep['id']:
                conn.execute('UPDATE printers SET mac = NULL WHERE id = ?', (r['id'],))
                db.audit(conn, None, 'Yinelenen MAC: birleştirilemedi (iki kayıtta da iş var), MAC boşaltıldı', 'printer', r['id'],
                         f'{r["name"]}: {mac} → asıl kayıt #{keep["id"]} {keep["name"]}')
        rep['conflicts'].append({'mac': mac, 'keep': keep['id'], 'others': [r['id'] for r in rows if r['id'] != keep['id']]})
        return
    keep = busy[0] if busy else max(rows, key=lambda r: (r['last_seen'] or '', -r['id']))
    if not busy and not any(r['last_seen'] for r in rows):
        keep = rows[0]
    refs = _fk_refs(conn)
    fill = [c for c in keep if c not in ('id', 'mac', 'name', 'created_at', 'current_part_id')]
    for r in rows:
        if r['id'] == keep['id']:
            continue
        for t, col in refs:
            conn.execute(f'UPDATE "{t}" SET "{col}" = ? WHERE "{col}" = ?', (keep['id'], r['id']))
        conn.execute("UPDATE audit_logs SET entity_id = ? WHERE entity = 'printer' AND entity_id = ?", (str(keep['id']), str(r['id'])))
        for c in fill:
            if keep[c] is None and r[c] is not None:
                if c == 'ip':
                    conn.execute('UPDATE printers SET ip = NULL WHERE id = ?', (r['id'],))
                conn.execute(f'UPDATE printers SET "{c}" = ? WHERE id = ?', (r[c], keep['id']))
                keep[c] = r[c]
        conn.execute('DELETE FROM printers WHERE id = ?', (r['id'],))
        db.audit(conn, None, 'Yinelenen yazıcı kaydı birleştirildi (aynı MAC)', 'printer', keep['id'],
                 f'#{r["id"]} {r["name"]} ({r["ip"] or "—"}) → #{keep["id"]} {keep["name"]} · MAC {mac}')
        rep['merged'].append({'mac': mac, 'keep': keep['id'], 'removed': r['id'], 'removed_name': r['name']})
