"""Creality K2 Plus yazıcılarından canlı durum okuma ve ağ taraması.

K2 Plus (Creality OS, Klipper tabanlı) iki yoldan konuşabilir:
  1. Creality'nin yerel WebSocket'i (ws://IP:9999) — Creality Print'in kullandığı kanal,
     bağlanınca JSON durum mesajları gönderir (state, printProgress, printFileName ...).
  2. Moonraker HTTP API (http://IP:7125) — açık olan cihazlarda.
Önce Moonraker, olmazsa WebSocket denenir. Alan adları firmware sürümüne göre
değişebildiğinden eşleme toleranslı yazıldı.
"""
import ipaddress
import json
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from websockets.sync.client import connect as ws_connect

from . import config, db

CREALITY_WS_PORT = 9999
MOONRAKER_PORT = 7125
TIMEOUT = 3

# Birleşik durum kodları → arayüz etiketleri frontend'dedir.
IDLE, PRINTING, PAUSED, DONE, ERROR, OFFLINE = 'HAZIR', 'YAZDIRIYOR', 'DURAKLADI', 'TAMAMLANDI', 'HATA', 'CEVRIMDISI'

_MOONRAKER_STATES = {'standby': IDLE, 'printing': PRINTING, 'paused': PAUSED,
                     'complete': DONE, 'cancelled': IDLE, 'error': ERROR}
# Creality K serisi 'state' alanı
_CREALITY_STATES = {0: IDLE, 1: PRINTING, 2: DONE, 3: ERROR, 4: IDLE, 5: PAUSED}


def _moonraker(ip):
    url = f'http://{ip}:{MOONRAKER_PORT}'
    r = httpx.get(f'{url}/printer/objects/query',
                  params={'print_stats': '', 'virtual_sdcard': ''}, timeout=TIMEOUT)
    r.raise_for_status()
    status = r.json()['result']['status']
    ps, sd = status.get('print_stats', {}), status.get('virtual_sdcard', {})
    info = {}
    try:
        info = httpx.get(f'{url}/printer/info', timeout=TIMEOUT).json()['result']
    except Exception:
        pass
    return {
        'state': _MOONRAKER_STATES.get(ps.get('state'), IDLE),
        'progress': round((sd.get('progress') or 0) * 100, 1),
        'file': ps.get('filename') or None,
        'print_s': ps.get('print_duration'),   # işin net baskı süresi (duraklamalar hariç), sn
        'hostname': info.get('hostname'),
        'model': None,
        'source': 'moonraker',
    }


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _creality_ws(ip):
    merged = {}
    with ws_connect(f'ws://{ip}:{CREALITY_WS_PORT}', open_timeout=TIMEOUT, close_timeout=1) as ws:
        # Tam durum isteği; firmware bunu yok sayarsa periyodik mesajlar yine gelir.
        try:
            ws.send(json.dumps({'method': 'get', 'params': {'reqPrinterPara': 1}}))
        except Exception:
            pass
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            try:
                msg = ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            except TimeoutError:
                break
            try:
                data = json.loads(msg)
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict):
                merged.update(data)
            if 'state' in merged and ('printProgress' in merged or 'model' in merged):
                break
    if not merged:
        raise ConnectionError('Yazıcıdan veri gelmedi')
    try:
        state = _CREALITY_STATES.get(int(merged.get('state')), IDLE)
    except (TypeError, ValueError):
        state = IDLE
    file = merged.get('printFileName') or None
    if file:
        file = str(file).rsplit('/', 1)[-1]
    return {
        'state': state,
        'progress': float(merged.get('printProgress') or 0),
        'file': file,
        'print_s': _num(merged.get('printJobTime')),   # işin baskı süresi, sn (firmware veriyorsa)
        'hostname': merged.get('hostname'),
        'model': merged.get('model'),
        'source': 'creality-ws',
    }


def hardware_id(ip):
    """Yazıcının kalıcı donanım kimliği: Moonraker'ın seri numarasından türeyen ağ adı (ör. K2Plus-3697).
    IP değişse de sabittir. Yalnızca Moonraker'dan okunur (Creality WS'in sayısal hostname'i güvenilmez)."""
    try:
        hn = (_moonraker(ip).get('hostname') or '').strip()
        return hn or None
    except Exception:
        return None


def device_name(ip):
    """Yazıcının ekranından girilen kullanıcı adı (Creality 'deviceName'). Boşsa None döner.
    Ağ hostname'i (K2Plus-XXXX) KULLANILMAZ — o kullanıcı adı değildir."""
    try:
        merged = {}
        with ws_connect(f'ws://{ip}:{CREALITY_WS_PORT}', open_timeout=TIMEOUT, close_timeout=1) as ws:
            try:
                ws.send(json.dumps({'method': 'get', 'params': {'reqPrinterPara': 1}}))
            except Exception:
                pass
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline:
                try:
                    msg = ws.recv(timeout=max(0.1, deadline - time.monotonic()))
                except TimeoutError:
                    break
                try:
                    data = json.loads(msg)
                except (TypeError, ValueError):
                    continue
                if isinstance(data, dict):
                    merged.update(data)
                if 'deviceName' in merged:
                    break
        # Kullanıcının cihaz ekranından verdiği ad: bazı firmware'lerde deviceName, çoğunda WS 'hostname' alanında (ör. '25', '31').
        # Ağ/seri adı (K2Plus-XXXX) yalnızca Moonraker'dan gelir; WS hostname kullanıcı adıdır.
        name = str(merged.get('deviceName') or '').strip() or str(merged.get('hostname') or '').strip()
        if not name or name.upper().startswith('K2PLUS-'):   # ağ adıysa kullanıcı adı sayılmaz
            return None
        return name
    except Exception:
        return None


def _probe_direct(ip):
    for fn in (_moonraker, _creality_ws):
        try:
            return fn(ip)
        except Exception:
            continue
    return None


def probe(ip):
    """Yazıcının canlı durumunu döner; ulaşılamazsa None. Uzak modda fabrikadaki ajan yoklar."""
    if config.AGENT_MODE == 'remote':
        try:
            from . import devices
            return devices.call_sync('printer.probe', {'ip': ip}, timeout=15)
        except Exception:
            return None
    return _probe_direct(ip)


def poll_all():
    """Kayıtlı yazıcıların canlı durumu, SON GÖRÜLEN IP'lerinden okunur. Kimlik denetimi: Moonraker'ın bildirdiği ağ adı
    (K2Plus-XXXX) yazıcının MAC'iyle uyuşmazsa o IP'de BAŞKA bir yazıcı vardır — durum bu kayda yazılmaz (çevrimdışı
    sayılır) ve bir sonraki tazelemede ağ taramasıyla doğru IP bulunur. IP'si bilinmeyen kayıt çevrimdışıdır."""
    from .printer_identity import hw_matches
    with db.connect() as conn:
        printers = db.rows(conn.execute(
            'SELECT id, ip, mac, hw_id, model, live_state, live_file, live_progress, live_since, current_part_id, maint_since, arge_since FROM printers'))
    if not printers:
        return
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda p: (p, probe(p['ip']) if p['ip'] else None), printers))
    now = db.now()
    with db.connect() as conn:
        for p, live in results:
            if live and _other_device(p, live.get('hostname') if live.get('source') == 'moonraker' else None, hw_matches):
                live = None   # bu IP'de başka yazıcı: durumu bu kayda yazma
            if live:
                since = p['live_since'] if p['live_state'] == live['state'] and p['live_since'] else now
                conn.execute(
                    '''UPDATE printers SET live_state = ?, live_progress = ?, live_file = ?, live_source = ?,
                       last_seen = ?, live_since = ?, model = COALESCE(model, ?), live_print_s = ? WHERE id = ?''',
                    (live['state'], live['progress'], live['file'], live['source'], now, since, live['model'],
                     live.get('print_s'), p['id']))
                detect_unrecorded_abort(conn, p, live['state'], now)
            else:
                conn.execute('UPDATE printers SET live_state = ? WHERE id = ?', (OFFLINE, p['id']))
        track_jobs(conn, now)


def _other_device(p, hostname, hw_matches):
    """Yoklanan IP'deki cihazın ağ adı bu kaydın MAC'ine / kayıtlı ağ adına ait değilse True (başka yazıcı)."""
    if not hostname:
        return False
    from .printer_identity import is_netname
    if p.get('mac'):
        return hw_matches(hostname, p['mac']) is False
    hw = p.get('hw_id') or ''
    return is_netname(hw) and is_netname(hostname) and hostname.upper() != hw.upper()


def detect_unrecorded_abort(conn, before, state, now):
    """Sistemde üretime başlatılmamış (kayıtsız) bir baskı bitmeden durdu: yazdırıyor / duraklatılmış iken yazıcı
    boşa geçti (iptal) ya da hata verdi. Kritik uyarı için olay kaydı açılır. Bağlantı kopması (çevrimdışı) sayılmaz;
    baskı tamamlandıysa (TAMAMLANDI) olay yoktur."""
    # Bakım / Ar-Ge modundaki yazıcıda deneme baskıları kayıtsız iptal/hata sayılmaz (alarm üretmez)
    if before['live_state'] not in (PRINTING, PAUSED) or state not in (IDLE, ERROR) or before['current_part_id'] \
            or before['maint_since'] or before['arge_since']:
        return
    started = before['live_since'] if before['live_state'] == PRINTING else None
    conn.execute('''INSERT INTO printer_incidents (printer_id, kind, file, progress, end_state, started_at, ended_at)
                    VALUES (?, 'KAYITSIZ_IPTAL', ?, ?, ?, ?, ?)''',
                 (before['id'], before['live_file'], before['live_progress'], state, started, now))


def track_jobs(conn, now):
    """Üretimdeki parçanın yazıcıdaki gerçek başlangıç ve bitiş anı (yazıcının kendi bildirimine göre).

    Başlangıç: yazıcı bu parçanın dosyasını basarken ilk görüldüğü an. Bitiş: ardından yazıcı "tamamlandı"
    dediği an. Böylece personelin parçayı yazıcıda ne kadar beklettiği (bitiş → "Üretim Tamamlandı") ölçülür.
    Dosya adı parçanın baskı dosyasıyla uyuşmuyorsa (başka bir iş) kaydedilmez; baskı dosyası tanımsız
    parçalarda dosya adı kontrol edilmez."""
    from .alerts import expected_files, norm_file
    files = expected_files(conn)
    rows = db.rows(conn.execute(
        '''SELECT op.id, op.part_id, op.printer_started_at, op.printer_done_at, p.live_state, p.live_file, p.live_print_s
           FROM printers p JOIN order_parts op ON op.id = p.current_part_id
           WHERE op.state = 'URETIMDE' AND p.live_state IN (?, ?, ?)''', (PRINTING, PAUSED, DONE)))
    for r in rows:
        expected = files.get(r['part_id'])
        if expected and norm_file(expected) != norm_file(r['live_file']):
            continue
        if r['live_print_s'] is not None and not r['printer_done_at']:   # parçanın net baskı süresi (yazıcının bildirdiği)
            conn.execute('UPDATE order_parts SET print_seconds = ? WHERE id = ?', (int(r['live_print_s']), r['id']))
        if r['live_state'] in (PRINTING, PAUSED) and not r['printer_started_at']:
            conn.execute('UPDATE order_parts SET printer_started_at = ? WHERE id = ?', (now, r['id']))
        elif r['live_state'] == DONE and r['printer_started_at'] and not r['printer_done_at']:
            conn.execute('UPDATE order_parts SET printer_done_at = ? WHERE id = ?', (now, r['id']))


_recon_lock = threading.Lock()
_recon_last = 0.0


def reconcile_ips():
    """Ağı tarayıp yazıcıların IP'lerini MAC'e (yoksa MAC'ten türeyen / kayıtlı ağ adına) göre günceller: IP değişen
    yazıcının kaydı silinmez, yalnızca son görülen IP'si güncellenir; aynı IP'yi tutan eski kaydın IP'si boşaltılır
    (printer_identity.apply_scan). Değişen IP sayısını döner."""
    from . import printer_identity
    found, _ = printer_identity.scan()
    if not found:
        return 0
    return len(printer_identity.apply_scan(found)['moved'])


def reconcile_if_offline(min_interval=25):
    """Çevrimdışı yazıcı varsa (IP değişmiş olabilir) ve son taramadan beri min_interval sn geçtiyse IP'leri tazeler.
    Aynı anda tek tarama; kilit meşgulse hemen döner. Değişen IP'ler bir sonraki yoklama/tazelemede yansır."""
    global _recon_last
    if not config.PRINTER_POLL_ENABLED:   # yazıcı ağı kapalıysa (ör. testler) tarama yapılmaz
        return 0
    with db.connect() as conn:
        offline = conn.execute("SELECT COUNT(*) FROM printers WHERE live_state IS NULL OR live_state = 'CEVRIMDISI'").fetchone()[0]
    if not offline:
        return 0
    if not _recon_lock.acquire(blocking=False):
        return 0
    try:
        if time.monotonic() - _recon_last < min_interval:
            return 0
        _recon_last = time.monotonic()
        return reconcile_ips()   # canli durumu da tazeler
    finally:
        _recon_lock.release()


def trigger_reconcile():
    """Yazıcı listesi istendiğinde çağrılır: IP tazelemeyi ARKA PLANDA başlatır (liste anında döner, bekletmez).
    Çevrimdışı yazıcı yoksa, yakında tarandıysa ya da yazıcı ağı kapalıysa hiçbir şey yapmaz."""
    if not config.PRINTER_POLL_ENABLED:
        return
    threading.Thread(target=lambda: reconcile_if_offline(), name='reconcile', daemon=True).start()


def _local_networks():
    """Makinenin fiziksel ağ arayüzlerindeki IPv4 /24 ağları (docker köprüleri hariç)."""
    nets = set()
    try:
        out = subprocess.run(['ip', '-4', '-o', 'addr', 'show'], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            parts = line.split()
            iface, cidr = parts[1], parts[3]
            if iface == 'lo' or iface.startswith(('docker', 'br-', 'veth', 'virbr', 'tailscale', 'zt')):
                continue
            nets.add(ipaddress.ip_interface(cidr.split('/')[0] + '/24').network)
    except Exception:
        pass
    if not nets:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('10.255.255.255', 1))
            nets.add(ipaddress.ip_interface(s.getsockname()[0] + '/24').network)
    return [n for n in nets if n.is_private]


def _port_open(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=0.5):
            return True
    except OSError:
        return False


def _discover_local():
    """Bu makinenin ağ bloğunda (/24) 9999/7125 portu açık cihazları bulur, yazıcı olduğunu doğrular ve her biri için
    MAC'ini (ARP, live['mac']) ve ağ adını (live['hw'], K2Plus-XXXX) da okur. [[ip, live], …] döner."""
    hosts = [str(h) for net in _local_networks() for h in net.hosts()]

    from .printer_identity import _moonraker_macs, arp_mac

    def check(ip):
        if _port_open(ip, MOONRAKER_PORT) or _port_open(ip, CREALITY_WS_PORT):
            live = _probe_direct(ip)
            if live:
                # mac: ARP (ulaşılan arayüz; Wi-Fi'de rastgele olabilir) · macs: yazıcının kendi API'sinin bildirdiği tüm
                # arayüz MAC'leri (kablolu dahil) — yazıcının benzersiz kimliği bunlardan biridir
                macs = _moonraker_macs(ip) if live.get('source') == 'moonraker' else []
                return [ip, dict(live, hw=hardware_id(ip), mac=arp_mac(ip), macs=macs)]
        return None

    with ThreadPoolExecutor(max_workers=64) as pool:
        return [r for r in pool.map(check, hosts) if r]


def discover():
    """Yazıcıları bulur (tüm ağ bloğu). Uzak modda tarama fabrikadaki ajanda yapılır — fabrika LAN'ı yalnız oradan görünür."""
    if config.AGENT_MODE == 'remote':
        from . import devices
        return devices.call_sync('printer.discover', {}, timeout=90)
    return _discover_local()


_started = False


def start_poller():
    global _started
    if _started or not config.PRINTER_POLL_ENABLED:
        return
    _started = True

    def loop():
        cycle = 0
        while True:
            try:
                poll_all()
                cycle += 1
                if cycle % 12 == 0:   # ~2 dakikada bir: çevrimdışı yazıcı varsa IP'leri kendiliğinden tazele (DHCP değişimi)
                    reconcile_if_offline(min_interval=0)
            except Exception:
                pass
            time.sleep(config.PRINTER_POLL_SECONDS)

    threading.Thread(target=loop, daemon=True, name='printer-poller').start()
