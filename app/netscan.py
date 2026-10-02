"""Ağ tarayıcı (Araçlar › Ağ Tarayıcı): sunucunun bulunduğu yerel ağdaki cihazlar.

Tarama: fping ile ICMP taraması, ardından komşu (ARP) tablosu (ICMP'ye yanıt vermeyen ama ARP'ye yanıt veren
cihazlar da bulunur). Her cihaz için MAC ve üretici (IEEE OUI), bilgisayar adı (ters DNS, NetBIOS, mDNS), açık
yaygın portlar ve tahmini cihaz türü. Yazıcı ve kamera kayıtlarıyla IP eşleştirilir. Sonuçlar network_devices
tablosunda tutulur (ilk / son görülme, elle verilen ad). Tarama arka planda çalışır; aynı anda tek tarama.
"""
import ipaddress
import json
import re
import socket
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from . import db

PORTS = {22: 'SSH', 80: 'HTTP', 443: 'HTTPS', 445: 'SMB', 3389: 'RDP', 554: 'RTSP', 7125: 'Moonraker', 9100: 'Yazıcı (RAW)',
         631: 'IPP', 8080: 'HTTP-alt', 5900: 'VNC', 53: 'DNS'}
SKIP_IFACES = ('lo', 'docker', 'br-', 'veth', 'virbr', 'tailscale', 'wg', 'tun', 'zt')
MAX_HOSTS = 1024   # /22'den büyük ağlar sunucunun bulunduğu /24 ile sınırlanır
OUI_FILES = ('/usr/share/ieee-data/oui.txt', '/var/lib/ieee-data/oui.txt')

_lock = threading.Lock()
_state = {'running': False, 'phase': None, 'done': 0, 'total': 0, 'error': None, 'started_at': None, 'finished_at': None}
_oui = None


def state():
    return dict(_state)


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ''


def networks():
    """Sunucunun yerel IPv4 ağları: [{iface, ip, cidr}] (docker / sanal arayüzler hariç)."""
    out = []
    try:
        data = json.loads(_run(['ip', '-j', '-4', 'addr', 'show']) or '[]')
    except ValueError:
        data = []
    for itf in data:
        name = itf.get('ifname', '')
        if name.startswith(SKIP_IFACES) or 'UP' not in itf.get('flags', []):
            continue
        for a in itf.get('addr_info', []):
            ip = ipaddress.ip_address(a['local'])
            if not ip.is_private or ip.is_loopback:
                continue
            net = ipaddress.ip_network(f'{a["local"]}/{a["prefixlen"]}', strict=False)
            if net.num_addresses > MAX_HOSTS:
                net = ipaddress.ip_network(f'{a["local"]}/24', strict=False)
            out.append({'iface': name, 'ip': a['local'], 'cidr': str(net)})
    return out


def gateway():
    try:
        routes = json.loads(_run(['ip', '-j', '-4', 'route', 'show', 'default']) or '[]')
        return routes[0].get('gateway') if routes else None
    except ValueError:
        return None


MANUF_URL = 'https://www.wireshark.org/download/automated/data/manuf'   # IEEE OUI listesi (24 / 28 / 36 bitlik bloklar)


def _manuf_path():
    from . import config
    return config.DATA_DIR / 'oui' / 'manuf'


def refresh_vendors():
    """Üretici listesi yoksa ya da 30 günden eskiyse indirilir (internet yoksa eldeki kullanılır)."""
    global _oui
    import time
    import urllib.request
    p = _manuf_path()
    if p.is_file() and time.time() - p.stat().st_mtime < 30 * 86400:
        return
    try:
        with urllib.request.urlopen(MANUF_URL, timeout=30) as r:
            data = r.read()
        if len(data) > 500_000:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            _oui = None
    except OSError:
        pass


def _load_vendors():
    table = {}   # onaltılık önek (6, 7 ya da 9 hane) → üretici
    p = _manuf_path()
    if p.is_file():
        for line in p.read_text(encoding='utf-8', errors='replace').splitlines():
            if not line or line[0] == '#':
                continue
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            prefix, bits = (parts[0].strip().split('/') + ['24'])[:2]
            hexs = prefix.replace(':', '').replace('-', '').upper()[:int(bits) // 4]
            name = (parts[2] if len(parts) > 2 and parts[2].strip() else parts[1]).strip()
            table[hexs] = name
        return table
    for f in OUI_FILES:   # yedek: sistemdeki IEEE listesi
        if Path(f).is_file():
            for line in Path(f).read_text(encoding='utf-8', errors='replace').splitlines():
                m = re.match(r'^([0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2})\s+\(hex\)\s+(.+)$', line.strip())
                if m:
                    table[m.group(1).replace('-', '')] = m.group(2).strip()
            break
    return table


def vendor(mac):
    global _oui
    if not mac:
        return None
    if _oui is None:
        _oui = _load_vendors()
    hexs = mac.replace(':', '').upper()
    if int(hexs[1], 16) & 2:   # yerel yönetilen MAC: telefonların gizlilik adresi ya da cihazın rastgele ürettiği adres
        return 'Yerel (rastgele) MAC'
    return next((_oui[hexs[:n]] for n in (9, 7, 6) if hexs[:n] in _oui), None)


def _names(ip):
    """Bilgisayar adı: NetBIOS (Windows), mDNS (Mac, Linux, telefon), ters DNS (modem / DHCP)."""
    names = {}
    nb = _run(['nmblookup', '-A', ip], timeout=4)
    m = next((re.match(r'\s*(\S+)\s+<00>', l) for l in nb.splitlines() if '<00>' in l and 'GROUP' not in l), None)
    if m:
        names['netbios'] = m.group(1)
    grp = next((re.match(r'\s*(\S+)\s+<00>', l) for l in nb.splitlines() if '<00>' in l and 'GROUP' in l), None)
    if grp:
        names['workgroup'] = grp.group(1)
    md = _run(['avahi-resolve', '-a', ip], timeout=4).split()
    if len(md) >= 2:
        names['mdns'] = md[1]
    try:
        socket.setdefaulttimeout(2)
        dns = socket.gethostbyaddr(ip)[0]
        if dns and dns != ip:
            names['dns'] = dns
    except (OSError, socket.herror):
        pass
    finally:
        socket.setdefaulttimeout(None)
    return names


def _ports(ip):
    open_ = []
    for port in PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.35)
        try:
            if s.connect_ex((ip, port)) == 0:
                open_.append(port)
        except OSError:
            pass
        finally:
            s.close()
    return open_


def _kind(d):
    """Tahmini cihaz türü."""
    ports, v, n = set(d['ports']), (d['vendor'] or '').lower(), (d['hostname'] or '').lower()
    if d.get('known') and d['known'].startswith('3B yazıcı'):
        return '3B yazıcı'
    if d.get('known') and d['known'].startswith('Kamera'):
        return 'Kamera'
    if d['is_gateway']:
        return 'Modem / yönlendirici'
    if d['is_server']:
        return 'Bu sunucu'
    if 7125 in ports:
        return '3B yazıcı'
    if 554 in ports or any(k in v for k in ('hikvision', 'dahua', 'uniview', 'axis')):
        return 'Kamera'
    if 'android' in n or 'iphone' in n or 'ipad' in n or v.startswith('yerel (rastgele)') and not ports:
        return 'Telefon / tablet'
    if 'macbook' in n or 'imac' in n or 'mac-mini' in n:
        return 'Mac'
    if 3389 in ports or (445 in ports and d.get('netbios')):
        return 'Windows bilgisayar'
    if 9100 in ports or 631 in ports or any(k in v for k in ('hewlett', 'brother', 'canon', 'epson', 'kyocera', 'xerox', 'ricoh')):
        return 'Yazıcı'
    if d.get('netbios') or 445 in ports:
        return 'Bilgisayar'
    if 22 in ports:
        return 'Linux / sunucu'
    if ports & {80, 443, 8080}:
        return 'Web arayüzlü cihaz'
    return 'Bilinmiyor'


def _known(conn):
    """Sistemde kayıtlı cihazlar: IP → açıklama (yazıcılar, kameralar)."""
    out = {}
    for name, ip in conn.execute('SELECT name, ip FROM printers WHERE ip IS NOT NULL'):
        out[ip] = f'3B yazıcı: {name}'
    for name, ip, url in conn.execute('SELECT name, ip, stream_url FROM cameras'):
        host = ip or (urlparse(url).hostname if url else None)
        if host:
            out.setdefault(host, f'Kamera: {name}')
    return out


def _scan():
    nets = networks()
    if not nets:
        raise RuntimeError('Taranacak yerel ağ bulunamadı')
    gw = gateway()
    _state.update(phase='Üretici listesi denetleniyor')
    refresh_vendors()
    alive = set()
    _state.update(phase='Cihazlar aranıyor (ping ve ARP)', done=0, total=0)
    for n in nets:
        out = _run(['fping', '-a', '-q', '-g', n['cidr'], '-r', '1', '-t', '300'], timeout=120)
        alive |= {l.strip() for l in out.splitlines() if l.strip()}
    macs = {}
    for n in nets:   # ARP tablosu: ICMP'ye yanıt vermeyen cihazlar da burada
        try:
            neigh = json.loads(_run(['ip', '-j', 'neigh', 'show', 'dev', n['iface']]) or '[]')
        except ValueError:
            neigh = []
        net = ipaddress.ip_network(n['cidr'])
        for e in neigh:
            if e.get('lladdr') and not set(e.get('state', [])) & {'FAILED', 'INCOMPLETE'} and ipaddress.ip_address(e['dst']) in net:
                macs[e['dst']] = e['lladdr'].lower()
                alive.add(e['dst'])
    server_ips = {n['ip'] for n in nets}
    alive |= server_ips
    ips = sorted(alive, key=lambda x: tuple(int(p) for p in x.split('.')))
    _state.update(phase='Bilgisayar adları ve portlar okunuyor', total=len(ips))

    def probe(ip):
        names = _names(ip)
        ports = _ports(ip)
        _state['done'] += 1
        return ip, names, ports
    with ThreadPoolExecutor(max_workers=32) as ex:
        results = list(ex.map(probe, ips))
    now = db.now()
    with db.connect() as conn:
        known = _known(conn)
        conn.execute('UPDATE network_devices SET online = 0')
        for ip, names, ports in results:
            mac = macs.get(ip)
            hostname = names.get('netbios') or names.get('mdns', '').removesuffix('.local') or names.get('dns') or None
            d = {'ip': ip, 'mac': mac, 'vendor': vendor(mac), 'hostname': hostname, 'netbios': names.get('netbios'),
                 'mdns': names.get('mdns'), 'dns': names.get('dns'), 'workgroup': names.get('workgroup'), 'ports': ports,
                 'is_gateway': ip == gw, 'is_server': ip in server_ips, 'known': known.get(ip)}
            d['kind'] = _kind(d)
            key = mac or f'ip:{ip}'   # cihaz MAC ile izlenir (IP değişse de aynı kayıt)
            row = conn.execute('SELECT id FROM network_devices WHERE key = ?', (key,)).fetchone()
            vals = (ip, mac, d['vendor'], hostname, d['netbios'], d['mdns'], d['dns'], d['workgroup'], json.dumps(ports), d['kind'],
                    d['known'], int(d['is_gateway']), int(d['is_server']), now)
            if row:
                conn.execute('''UPDATE network_devices SET ip = ?, mac = ?, vendor = ?, hostname = COALESCE(?, hostname), netbios = ?, mdns = ?,
                                dns = ?, workgroup = ?, ports = ?, kind = ?, known = ?, is_gateway = ?, is_server = ?, last_seen = ?, online = 1
                                WHERE id = ?''', (*vals, row[0]))
            else:
                conn.execute('''INSERT INTO network_devices (ip, mac, vendor, hostname, netbios, mdns, dns, workgroup, ports, kind, known,
                                is_gateway, is_server, last_seen, online, key, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)''',
                             (*vals, key, now))
        conn.execute("INSERT OR REPLACE INTO app_kv (k, v) VALUES ('netscan.last', ?)",
                     (json.dumps({'at': now, 'networks': nets, 'gateway': gw, 'count': len(results)}),))
        conn.commit()


def start():
    with _lock:
        if _state['running']:
            return False
        _state.update(running=True, error=None, started_at=db.now(), finished_at=None, phase='Başlıyor', done=0, total=0)

    def job():
        try:
            _scan()
        except Exception as err:   # arayüzde gösterilir
            _state['error'] = str(err)
        finally:
            _state.update(running=False, phase=None, finished_at=db.now())
    threading.Thread(target=job, daemon=True, name='netscan').start()
    return True
