"""mtweb dış bağlantı koruması (docs/mtweb.md §Dış bağlantılar): SSRF engeli, oran sınırı, eşzamanlı oturum tavanı, denetim.

HEPGO araç kodu her dış bağlantıdan önce `tools_common.NET_GUARD` kancasını çağırır (quota.install bunu `resolve_target`
yapar). Burada:
  1. Ad DNS ile çözülür; adreslerden BİRİ bile global değilse (loopback, özel, link-local / 169.254.169.254, CGNAT 100.64/10,
     çoklu yayın, ayrılmış, belirsiz, ULA / site-local v6, IPv4-mapped / 6to4 / Teredo / NAT64 içindeki özel adres) ya da
     sunucunun kendi adresiyse (MTWEB_BLOCK_IPS + yerel arabirim adresleri) reddedilir.
  2. Port 25/465/587 + MTWEB_BLOCK_PORTS reddedilir.
  3. Doğrulanan IP döner; çağıran bağlantıyı O IP'ye kurar (DNS yeniden bağlama yok).
  4. kind='connect': kullanıcı ve istemci IP başına deneme oranı + mtweb_audit kaydı (kullanıcı, uygulama, host, IP, port,
     sonuç, istemci IP). kind='data' (FTP veri kanalı, SSH tüneli hedefi): yalnız adres/port denetimi.
`acquire(uid, app)` (CONN_GATE): kullanıcı başına uygulama başına MTWEB_NET_USER_SESSIONS, genel MTWEB_NET_SESSIONS.
MTWEB_ALLOW_PRIVATE=1 YALNIZ testte: özel/yerel adreslere izin verir (MTWEB_BLOCK_IPS ve port engeli yine geçerli).
"""
import fcntl
import ipaddress
import socket
import struct
import threading
import time

from . import config  # noqa: I001 — ilk: çekirdek yollarını mtweb veri dizinine yönlendirir
from app.routers import tools_common  # noqa: E402

from . import auth, db  # noqa: E402

MSG_PRIVATE = ('Bu adrese bağlanılamaz: yerel / özel ağ adresleri web sürümünde kapalı '
               '(local or private network addresses are not allowed in the web version)')
MSG_SELF = 'Bu adrese bağlanılamaz (sunucunun kendi adresi) · This address is not allowed'
MSG_PORT = 'Bu porta bağlantıya izin verilmiyor ({p}) · Port {p} is not allowed'
MSG_HOST = 'Geçersiz sunucu adresi · Invalid host'
MSG_RATE = 'Çok fazla bağlantı denemesi; birkaç dakika sonra tekrar deneyin · Too many connection attempts'
MSG_SESS = 'Aynı anda en çok {n} {name} bağlantısı açabilirsiniz; kullanmadıklarınızı kapatın · Too many open connections'
MSG_BUSY = 'Sunucu şu an çok yoğun; biraz sonra tekrar deneyin · Server busy'
MSG_OFF = 'Bu uygulama geçici olarak kapalı · This app is temporarily unavailable'

CLIENT_IP = {}          # yerel kullanıcı id → son istemci IP (oran sınırı + denetim; HTTP/WS ara katmanı yazar)
_NAT64 = (ipaddress.ip_network('64:ff9b::/96'), ipaddress.ip_network('64:ff9b:1::/48'))
_V4COMPAT = ipaddress.ip_network('::/96')
_local = {'at': 0.0, 'addrs': frozenset()}
_local_lock = threading.Lock()


class Denied(tools_common.NetDenied):
    pass


# --- sunucunun kendi adresleri ------------------------------------------------------------------------------------
def _iface_v4():
    out = set()
    try:
        names = [n for _, n in socket.if_nameindex()]
    except OSError:
        names = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for n in names:
            try:
                r = fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s', n.encode()[:15]))   # SIOCGIFADDR
                out.add(socket.inet_ntoa(r[20:24]))
            except OSError:
                pass
    finally:
        s.close()
    return out


def _iface_v6():
    out = set()
    try:
        with open('/proc/net/if_inet6') as f:
            for line in f:
                h = line.split()[0]
                out.add(str(ipaddress.IPv6Address(bytes.fromhex(h))))
    except OSError:
        pass
    return out


def local_addresses():
    """Yerel arabirim adresleri (5 dk önbellek)."""
    t = time.time()
    with _local_lock:
        if t - _local['at'] < 300 and _local['addrs']:
            return _local['addrs']
    addrs = _iface_v4() | _iface_v6()
    try:
        addrs |= set(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    parsed = set()
    for a in addrs:
        try:
            parsed.add(ipaddress.ip_address(a.split('%')[0]))
        except ValueError:
            pass
    with _local_lock:
        _local.update(at=t, addrs=frozenset(parsed))
    return _local['addrs']


def _blocked_nets():
    out = []
    for x in config.BLOCK_IPS:
        try:
            out.append(ipaddress.ip_network(x, strict=False))
        except ValueError:
            pass
    return out


# --- adres sınıflandırma -------------------------------------------------------------------------------------------
def _embedded(ip):
    """IPv6 içine gömülü IPv4 adresleri (mapped, 6to4, Teredo sunucu/istemci, NAT64, eski ::a.b.c.d)."""
    out = [ip]
    if ip.version == 6:
        if ip.ipv4_mapped:
            out.append(ip.ipv4_mapped)
        if ip.sixtofour:
            out.append(ip.sixtofour)
        if ip.teredo:
            out.extend(ip.teredo)
        if any(ip in n for n in _NAT64):
            out.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip in _V4COMPAT and int(ip) > 0xFFFF:
            out.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return out


def _not_public(a):
    return (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified
            or (a.version == 6 and a.is_site_local) or not a.is_global)


def ip_problem(ip):
    """None (izinli) | 'self' (sunucunun kendisi / engel listesi) | 'private' (global olmayan)."""
    if isinstance(ip, str):
        ip = ipaddress.ip_address(ip.split('%')[0])
    nets = _blocked_nets()
    cands = _embedded(ip)
    for a in cands:
        if any(a.version == n.version and a in n for n in nets):
            return 'self'
    if config.ALLOW_PRIVATE:
        return None
    if any(_not_public(a) for a in cands):
        return 'private'
    local = local_addresses()
    if any(a in local for a in cands):
        return 'self'
    return None


# --- kanca: NET_GUARD ----------------------------------------------------------------------------------------------
def resolve_target(host, port, uid=None, app=None, kind='connect'):
    """host:port → doğrulanmış IP. Reddedilirse Denied; ad çözülemezse socket.gaierror (arayüzde DNS hatası)."""
    raw = str(host or '').strip()
    h = raw[1:-1] if raw.startswith('[') and raw.endswith(']') else raw
    client = CLIENT_IP.get(uid)
    connect = kind == 'connect'

    def deny(msg, result, rip=None):
        if connect:
            db.net_audit(uid, app, raw, rip, port, result, client)
        raise Denied(msg)

    if app and app in config.DISABLED_APPS:
        deny(MSG_OFF, 'denied:disabled')
    try:
        port = int(port)
    except (TypeError, ValueError):
        deny(MSG_HOST, 'denied:port')
    if not (1 <= port <= 65535) or port in config.BLOCK_PORTS:
        deny(MSG_PORT.format(p=port), 'denied:port')
    try:
        ipaddress.ip_address(h.split('%')[0])   # IP sabiti (':' ile başlayan v6 dahil) — sınıflandırmaya gider
    except ValueError:
        try:
            tools_common.check_host(h)
        except ValueError:
            deny(MSG_HOST, 'denied:host')
    if connect:
        wait = auth.rate_ok(f'net:u:{uid}', config.NET_ATTEMPTS_USER, config.NET_WINDOW_S)
        if not wait and client:
            wait = auth.rate_ok(f'net:ip:{client}', config.NET_ATTEMPTS_IP, config.NET_WINDOW_S)
        if wait:
            deny(MSG_RATE, 'denied:rate')
    try:
        infos = socket.getaddrinfo(h, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        if connect:
            db.net_audit(uid, app, raw, None, port, 'dns', client)
        raise
    ips = []
    for fam, _, _, _, sa in infos:
        if fam in (socket.AF_INET, socket.AF_INET6) and sa[0] not in ips:
            ips.append(sa[0])
    if not ips:
        deny(MSG_HOST, 'denied:host')
    for ip in ips:
        prob = ip_problem(ip)
        if prob:
            deny(MSG_SELF if prob == 'self' else MSG_PRIVATE, f'denied:{prob}', ip)
    if connect:
        db.net_audit(uid, app, raw, ips[0], port, 'ok', client)
    return ips[0].split('%')[0]


# --- kanca: CONN_GATE ----------------------------------------------------------------------------------------------
_sessions = {}
_total = [0]
_gate_lock = threading.Lock()


def acquire(uid, app):
    """Eşzamanlı bağlantı oturumu yeri; release() döner (birden çok çağrı güvenli)."""
    with _gate_lock:
        if _total[0] >= config.NET_SESSIONS:
            raise Denied(MSG_BUSY)
        k = (uid, app)
        n = _sessions.get(k, 0)
        if n >= config.NET_USER_SESSIONS:
            raise Denied(MSG_SESS.format(n=config.NET_USER_SESSIONS, name=config.APP_NAMES.get(app, app)))
        _sessions[k] = n + 1
        _total[0] += 1
    done = [False]

    def release():
        with _gate_lock:
            if done[0]:
                return
            done[0] = True
            _sessions[k] = max(0, _sessions.get(k, 1) - 1)
            if not _sessions[k]:
                _sessions.pop(k, None)
            _total[0] = max(0, _total[0] - 1)
    return release


def open_sessions(uid=None, app=None):
    with _gate_lock:
        if uid is None:
            return _total[0]
        return _sessions.get((uid, app), 0)


def reset():
    with _gate_lock:
        _sessions.clear()
        _total[0] = 0
    with _local_lock:
        _local.update(at=0.0, addrs=frozenset())

