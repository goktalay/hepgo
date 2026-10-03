"""NVR (ağ kayıt cihazı) erişimi — kameralar NVR arkasındayken ONVIF ile bilgi/kanal, RTSP ile akış.

Bulut (AGENT_MODE=remote) NVR'ın LAN'ına erişemez; bu yüzden probe op'u fabrika ajanı üzerinden çalışır
(devices.call_sync → agent_ops 'nvr.probe'). RTSP akışı yalnız fabrika-tarafı yüz-tanıma servisinde kullanılır
(akış buluta taşınmaz). ONVIF PasswordDigest 'Created' damgası CİHAZ saatine göre üretilir — makine saati kaymışsa
doğru şifre reddedilmesin diye (UNIVIEW NVR'da gözlendi)."""
import base64
import hashlib
import os
import re
import secrets
import threading
import time
import urllib.parse
from datetime import datetime, timezone

import httpx

from . import config, db, devices

TIMEOUT = 12
_NS = ('xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
       'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
       'xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
       'xmlns:tt="http://www.onvif.org/ver10/schema"')


def configured():
    return bool(config.NVR_HOST and config.NVR_USER)


def _creds():
    """Bulut tarafı: NVR kimlik bilgilerini (panelde girilen) köprü op'una argüman olarak geçmek için.
    Op'lar FABRİKA ajanında çalışır; ajanın kendi config'inde bu bilgiler yoktur, bu yüzden argümanla taşınır."""
    return {'host': config.NVR_HOST, 'port': config.NVR_PORT, 'user': config.NVR_USER, 'password': config.NVR_PASSWORD}


def _resolve(args):
    """Fabrika tarafı: op argümanındaki kimlik bilgileri (bulutta girilen) öncelikli; yoksa yerel config."""
    a = args or {}
    return {
        'host': a.get('host') or config.NVR_HOST,
        'port': int(a.get('port') or config.NVR_PORT or 80),
        'user': a.get('user') or config.NVR_USER,
        'password': a.get('password') if a.get('password') is not None else config.NVR_PASSWORD,
    }


def _onvif_url(host, port):
    hp = host if (':' in host or port == 80) else f'{host}:{port}'
    return f'http://{hp}/onvif/device_service'


def _tag(text, name):
    m = re.search(rf'<(?:\w+:)?{name}[^>]*>([^<]*)<', text)
    return m.group(1).strip() if m else None


def _device_created(url):
    """Cihazın UTC saatini alıp ONVIF 'Created' damgası üretir (makine saati kaymasına dayanıklı)."""
    try:
        body = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
                '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/></s:Body></s:Envelope>')
        t = httpx.post(url, content=body.encode(), headers={'Content-Type': 'application/soap+xml'}, timeout=TIMEOUT).text
        u = re.search(r'UTCDateTime>.*?Hour>(\d+).*?Minute>(\d+).*?Second>(\d+).*?Year>(\d+).*?Month>(\d+).*?Day>(\d+)', t, re.S)
        if u:
            h, mi, s, y, mo, d = (int(x) for x in u.groups())
            return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    except Exception:   # noqa: BLE001 — saat alınamazsa yerel saate düş
        pass
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def _security(user, password, created):
    nonce = secrets.token_bytes(16)
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + (password or '').encode()).digest()).decode()
    return (f'<s:Header><Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
            f'<UsernameToken><Username>{user}</Username>'
            f'<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</Password>'
            f'<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>'
            f'<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>'
            f'</UsernameToken></Security></s:Header>')


def _soap(url, body, user, password, created):
    env = f'<?xml version="1.0"?><s:Envelope {_NS}>{_security(user, password, created)}<s:Body>{body}</s:Body></s:Envelope>'
    r = httpx.post(url, content=env.encode(), headers={'Content-Type': 'application/soap+xml; charset=utf-8'}, timeout=TIMEOUT)
    text = r.text
    if 'NotAuthorized' in text or r.status_code in (401, 403):
        raise PermissionError('NVR kullanıcı adı / şifre kabul etmedi')
    if r.status_code >= 400 or re.search(r'<(?:\w+:)?Fault[ >]', text):
        raise RuntimeError(f'NVR ONVIF hatası ({r.status_code})')
    return text


def _probe_direct(args=None):
    """Fabrika-yerel: NVR ONVIF'e bağlanır, cihaz bilgisi + kanal sayısı döner. (agent op: 'nvr.probe')"""
    cr = _resolve(args)
    if not (cr['host'] and cr['user']):
        return {'ok': False, 'error': 'NVR bilgileri eksik'}
    url = _onvif_url(cr['host'], cr['port'])
    u, p = cr['user'], cr['password']
    created = _device_created(url)
    info = _soap(url, '<tds:GetDeviceInformation/>', u, p, created)
    channels = 0
    try:
        caps = _soap(url, '<tds:GetCapabilities><tds:Category>Media</tds:Category></tds:GetCapabilities>', u, p, created)
        m = re.search(r'Media>\s*<(?:\w+:)?XAddr>([^<]+)', caps)
        media = m.group(1).strip() if m else url
        vs = _soap(media, '<trt:GetVideoSources/>', u, p, created)
        channels = len(re.findall(r'<(?:\w+:)?VideoSources[ >]', vs))
    except Exception:   # noqa: BLE001 — kanal sayısı opsiyonel
        pass
    return {'ok': True, 'manufacturer': _tag(info, 'Manufacturer'), 'model': _tag(info, 'Model'),
            'firmware': _tag(info, 'FirmwareVersion'), 'channels': channels}


def _channels_direct(args=None):
    """Fabrika-yerel: NVR kanal listesi. (agent op: 'nvr.channels')

    UNIVIEW ONVIF profil token'ları kanal numarasını güvenilir vermiyor; bunun yerine probe'un bildirdiği kanal
    sayısı (GetVideoSources) kullanılıp 1..N 'Kanal N' üretilir. RTSP /unicast/c<N>/ bu numarayla çalışır
    (snapshot/akış doğrulandı). Kanal adı panelden düzenlenebilir ve kayıtlı adlar ayrıca gösterilir."""
    cr = _resolve(args)
    if not (cr['host'] and cr['user']):
        return {'ok': False, 'error': 'NVR bilgileri eksik', 'channels': []}
    n = _probe_direct(args).get('channels') or 0
    channels = [{'ch': i, 'name': None} for i in range(1, n + 1)]
    return {'ok': True, 'count': len(channels), 'channels': channels}


def probe():
    """Uzak modda fabrika ajanı üzerinden; yerelde doğrudan."""
    return devices.call_sync('nvr.probe', _creds())


def channels():
    """Uzak modda fabrika ajanı üzerinden; yerelde doğrudan. NVR'daki kanal listesi."""
    return devices.call_sync('nvr.channels', _creds())


# --- Canlı tek kamera izleme (talep üzerine) — fabrika-yerel RTSP → JPEG kare ---
# Kameralar NVR arkasında (fabrika LAN'ı) olduğu için buluttan doğrudan izlenemez; fabrika ajanı kareyi çeker.
# Akan izleme için kanal başına VideoCapture kısa süre açık tutulur; boşta kalan ~15 sn sonra kapatılır (reaper).
_caps = {}                      # channel -> {'cap', 'sub', 'last'}
_caps_lock = threading.Lock()
_reaper_on = False


def _reaper():
    while True:
        time.sleep(5)
        now = time.time()
        with _caps_lock:
            for ch, ent in list(_caps.items()):
                if now - ent['last'] > 15:
                    try:
                        ent['cap'].release()
                    except Exception:   # noqa: BLE001
                        pass
                    _caps.pop(ch, None)


def _snapshot_direct(args):
    """Fabrika-yerel: bir kanaldan tek JPEG kare (base64). (agent op: 'nvr.snapshot')"""
    global _reaper_on
    cr = _resolve(args)
    if not (cr['host'] and cr['user']):
        return {'ok': False, 'error': 'NVR bilgileri eksik'}
    channel = int(args['channel'])
    sub = bool(args.get('sub', True))          # alt akış: daha hafif
    width = int(args.get('width', 960))
    try:
        import cv2
    except ImportError:
        return {'ok': False, 'error': 'Bu makinede görüntü kütüphanesi (OpenCV) yok'}
    os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS', 'rtsp_transport;tcp|stimeout;5000000')
    with _caps_lock:
        if not _reaper_on:
            _reaper_on = True
            threading.Thread(target=_reaper, daemon=True).start()
        ent = _caps.get(channel)
        if ent is None or ent['sub'] != sub or not ent['cap'].isOpened():
            if ent:
                try:
                    ent['cap'].release()
                except Exception:   # noqa: BLE001
                    pass
            cap = cv2.VideoCapture(rtsp_url(channel, sub=sub, creds=cr), cv2.CAP_FFMPEG)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:   # noqa: BLE001
                pass
            ent = _caps[channel] = {'cap': cap, 'sub': sub, 'last': time.time()}
        cap = ent['cap']
        ent['last'] = time.time()
    ok, frame = cap.read()
    if not ok or frame is None:
        with _caps_lock:
            try:
                cap.release()
            except Exception:   # noqa: BLE001
                pass
            _caps.pop(channel, None)
        return {'ok': False, 'error': 'kare alınamadı (kanal yayında değil olabilir)'}
    hh, ww = frame.shape[:2]
    if ww > width:
        frame = cv2.resize(frame, (width, int(hh * width / ww)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
    if not ok:
        return {'ok': False, 'error': 'kare kodlanamadı'}
    return {'ok': True, 'jpg': base64.b64encode(buf.tobytes()).decode(), 'ts': time.time()}


def snapshot(channel, sub=True, width=960):
    """Uzak modda fabrika ajanı üzerinden; yerelde doğrudan. Tek kare (base64 JPEG)."""
    return devices.call_sync('nvr.snapshot', {'channel': channel, 'sub': sub, 'width': width, **_creds()}, timeout=12)


def rtsp_url(channel, sub=False, with_credentials=True, creds=None):
    """UNIVIEW biçimi RTSP adresi. channel: 1..N; sub=True alt akış (hafif). Yalnız fabrika-tarafı kullanır."""
    cr = creds or {'host': config.NVR_HOST, 'user': config.NVR_USER, 'password': config.NVR_PASSWORD}
    s = 1 if sub else 0
    auth = ''
    if with_credentials:
        auth = f'{urllib.parse.quote(cr["user"] or "")}:{urllib.parse.quote(cr["password"] or "", safe="")}@'
    return f'rtsp://{auth}{cr["host"]}:554/unicast/c{int(channel)}/s{s}/live'


# --- Kanal ayarı (yüz tanıma aç/kapa + zamanlama) — app_kv['nvr_channels'] ---
# Varsayılan: tüm kameralar KAPALI, yalnızca 1. kanal açık (GPU yükünü kademeli artırmak için).
CH_KEY = 'nvr_channels'
SCHEDULES = ('all', 'day', 'night', 'custom')   # tüm gün / sadece gündüz / sadece akşam / özel


def _ch_store(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (CH_KEY,)).fetchone()
    try:
        import json
        return json.loads(row[0]) if row else {}
    except ValueError:
        return {}


def channel_config(conn):
    """NVR kanal listesi + her kanalın kayıtlı yüz-tanıma ayarı (yoksa varsayılan). Panelde gösterilir."""
    store = _ch_store(conn)
    try:
        info = channels()
    except Exception as e:   # noqa: BLE001 — NVR'a ulaşılamazsa kayıtlı ayarları göster
        info = {'ok': False, 'error': str(e), 'channels': [{'ch': int(k), 'name': None} for k in sorted(store, key=int)]}
    out = []
    for c in info.get('channels', []):
        ch = c['ch']
        saved = store.get(str(ch), {})
        out.append({
            'ch': ch,
            'name': saved.get('name') or c.get('name') or f'Kanal {ch}',
            'face': bool(saved.get('face', ch == 1)),          # varsayılan: yalnız kanal 1 açık
            'schedule': saved.get('schedule', 'all') if saved.get('schedule') in SCHEDULES else 'all',
            'custom': saved.get('custom') or [],               # [["HH:MM","HH:MM"], ...]
        })
    return {'ok': info.get('ok', False), 'error': info.get('error'), 'channels': out}


def save_channel_config(conn, channels_in):
    """channels_in: [{ch, face, schedule, custom, name?}]. Tümünü yazar."""
    import json
    store = {}
    for c in channels_in or []:
        ch = int(c['ch'])
        sched = c.get('schedule')
        rec = {'face': bool(c.get('face')), 'schedule': sched if sched in SCHEDULES else 'all'}
        if c.get('name'):
            rec['name'] = str(c['name']).strip()[:60]
        if rec['schedule'] == 'custom':
            rec['custom'] = [[str(a)[:5], str(b)[:5]] for a, b in (c.get('custom') or []) if a and b]
        store[str(ch)] = rec
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (CH_KEY, json.dumps(store)))
    return len(store)


def active_channels(conn):
    """Yüz tanıma AÇIK kanalların listesi (fabrika servisi bu kanalların RTSP akışını çeker)."""
    return [c for c in channel_config(conn)['channels'] if c['face']]


def sync_cameras(conn):
    """Yüz tanıma açık NVR kanallarını `cameras` tablosuna köprüler (mevcut yüz-tanıma servisi bunları işler).
    Kapatılan kanal pasifleştirilir (görülme geçmişi silinmez). NVR kameraları stream_url ile tanınır."""
    from . import cameras as camlib
    if not configured():
        return 0
    base = f'rtsp://{config.NVR_HOST}:554/unicast/'   # NVR kanallarının ortak öneki
    pw = camlib.encrypt(config.NVR_PASSWORD) if config.NVR_PASSWORD else None
    want = {}
    for c in active_channels(conn):
        want[rtsp_url(c['ch'], with_credentials=False)] = c
    # Mevcut NVR kameraları
    existing = {r[1]: r[0] for r in conn.execute(
        "SELECT id, stream_url FROM cameras WHERE stream_url LIKE ?", (base + '%',)).fetchall()}
    for url, c in want.items():
        if url in existing:
            conn.execute('UPDATE cameras SET name = ?, username = ?, password_enc = ?, faces = 1, active = 1 WHERE id = ?',
                         (c['name'], config.NVR_USER, pw, existing[url]))
        else:
            conn.execute('''INSERT INTO cameras (name, ip, port, username, password_enc, stream_url, location, faces, active, auto_added, created_at)
                            VALUES (?,?,?,?,?,?,?,1,1,1,?)''',
                         (c['name'], config.NVR_HOST, 554, config.NVR_USER, pw, url, f'NVR kanal {c["ch"]}', db.now()))
    for url, cid in existing.items():        # artık yüz tanıma açık olmayanları pasifleştir
        if url not in want:
            conn.execute('UPDATE cameras SET active = 0 WHERE id = ?', (cid,))
    return len(want)


# --- GPU kapasite ölçümü — kaç kameraya aynı anda yüz tanıma yapılabilir ---
# NVR'ın çalıştığı FABRİKA makinesinin GPU'su ölçülür (uzak modda ajan üzerinden). Tahmin modeli:
# yüz hattı = tespit (RetinaFace-mobilenet) + gömme (ArcFace), ~10 FPS/akış, HEVC çözme (NVDEC).
# Bilinen NVIDIA ailelerine göre eşzamanlı akış tablosu; bilinmeyende VRAM'den tahmin. Yönetici elle ezebilir.
CAP_KEY = 'nvr_capacity'
# ad parçası (küçük harf) → ~eşzamanlı yüz-tanıma akışı (@~10 FPS, giriş-yüzü yakalama hattı).
# Gerçek sınır genelde NVDEC çözücü sayısına yakındır; muhafazakâr tutuldu.
_GPU_STREAMS = {
    # Jetson / gömülü (birleşik bellek)
    'agx orin': 24, 'orin nx': 12, 'orin nano': 6, 'orin': 12,
    'agx xavier': 10, 'xavier nx': 5, 'xavier': 8, 'tx2': 3, 'jetson': 4, 'tegra': 4, 'nano': 2,
    'thor': 30,
    # Grace-Blackwell / masaüstü AI (GB10 = DGX Spark sınıfı, birleşik bellek)
    'gb10': 40, 'gb200': 80, 'gh200': 60, 'grace': 40,
    # Veri merkezi
    'b200': 80, 'b100': 80, 'h200': 64, 'h100': 60, 'a100': 60, 'a40': 40, 'a30': 30, 'a10': 24,
    'l40': 48, 'l4': 24, 't4': 20, 'v100': 36,
    # Masaüstü / iş istasyonu
    'rtx 5090': 56, 'rtx 5080': 44, 'rtx 4090': 40, 'rtx 4080': 32, 'rtx 4070': 22,
    'rtx 3090': 34, 'rtx 3080': 28, 'rtx 3060': 16, 'rtx 2080': 20, 'rtx 2060': 12,
    'rtx a6000': 48, 'rtx a5000': 34, 'rtx a4000': 22, 'rtx pro': 48,
    'quadro': 12, 'gtx 1660': 8, 'gtx 1050': 3,
}
# Birleşik bellekli (GPU belleği = sistem RAM'i) aileler: VRAM okunamazsa /proc/meminfo'ya düş
_UNIFIED = ('orin', 'xavier', 'tegra', 'jetson', 'tx2', 'nano', 'thor', 'gb10', 'gb200', 'gh200', 'grace')


def _jetson_model():
    try:
        with open('/proc/device-tree/model', 'rb') as f:
            return f.read().decode('utf-8', 'ignore').strip('\x00').strip()
    except Exception:   # noqa: BLE001
        return None


def _nvml_device():
    """(ad, toplam_VRAM_MB) veya (None, None). sysstat ile aynı NVML yolu."""
    import ctypes
    for so in ('libnvidia-ml.so.1', 'libnvidia-ml.so'):
        try:
            lib = ctypes.CDLL(so)
        except OSError:
            continue
        try:
            if lib.nvmlInit_v2() != 0 and lib.nvmlInit() != 0:
                continue
            h = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) != 0:
                lib.nvmlShutdown(); continue
            name = ctypes.create_string_buffer(96)
            lib.nvmlDeviceGetName(h, name, 96)

            class _Mem(ctypes.Structure):
                _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]
            mem = _Mem()
            total_mb = int(mem.total / (1024 * 1024)) if lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(mem)) == 0 else None
            lib.nvmlShutdown()
            return name.value.decode('utf-8', 'ignore') or None, total_mb
        except Exception:   # noqa: BLE001
            try:
                lib.nvmlShutdown()
            except Exception:   # noqa: BLE001
                pass
    return None, None


def _estimate_streams(name, vram_mb, jetson):
    key = (name or '').lower()
    for part, n in _GPU_STREAMS.items():
        if part in key:
            return n, f'bilinen cihaz: {name}'
    if jetson:
        g = (vram_mb or 0) / 1024
        return max(2, int(g * 1.0)), f'Jetson (paylaşımlı {g:.0f} GB bellek) tahmini'
    if vram_mb:
        g = vram_mb / 1024
        return max(2, int(g * 1.6)), f'{g:.0f} GB VRAM tahmini'
    return 0, 'GPU bulunamadı — yüz tanıma için NVIDIA GPU gerekir'


def _sys_ram_mb():
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    return int(int(line.split()[1]) / 1024)
    except Exception:   # noqa: BLE001
        pass
    return None


def _gpu_capacity_direct(args=None):
    """Fabrika-yerel: GPU'yu ölç, önerilen max kamera sayısını hesapla. (agent op: 'nvr.gpu')"""
    jetson = _jetson_model()
    name, vram_mb = _nvml_device()
    if not name and jetson:
        name = jetson
    unified = bool(jetson) or any(p in (name or '').lower() for p in _UNIFIED)
    if not vram_mb and unified:   # birleşik bellek: GPU belleği sistem RAM'iyle paylaşımlı
        vram_mb = _sys_ram_mb()
    est, basis = _estimate_streams(name, vram_mb, unified)
    return {'ok': bool(name), 'gpu_name': name, 'vram_mb': vram_mb, 'jetson': unified,
            'est_max': est, 'basis': basis}


def gpu_capacity(conn):
    """GPU ölçümü + yönetici elle ayarı → etkin max. Panelde gösterilir."""
    import json
    try:
        cap = devices.call_sync('nvr.gpu', {})
    except Exception as e:   # noqa: BLE001
        cap = {'ok': False, 'gpu_name': None, 'vram_mb': None, 'est_max': 0, 'basis': f'ölçülemedi: {e}'}
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (CAP_KEY,)).fetchone()
    try:
        manual = json.loads(row[0]).get('manual_max') if row else None
    except ValueError:
        manual = None
    cap['manual_max'] = manual
    cap['effective_max'] = int(manual) if isinstance(manual, int) and manual > 0 else cap.get('est_max') or 0
    return cap


def save_capacity(conn, manual_max):
    """manual_max: pozitif int (elle sınır) ya da None/0 (otomatik tahmine dön)."""
    import json
    val = int(manual_max) if manual_max else None
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)',
                 (CAP_KEY, json.dumps({'manual_max': val if val and val > 0 else None})))
    return gpu_capacity(conn)


def test():
    if not configured():
        return False, 'NVR IP, kullanıcı ve şifre girilmeli.'
    try:
        r = probe()
    except PermissionError:
        return False, 'NVR kullanıcı adı veya şifre hatalı.'
    except Exception as e:   # noqa: BLE001
        return False, f'NVR’a ulaşılamadı: {type(e).__name__}'
    if not r.get('ok'):
        return False, r.get('error') or 'NVR bağlantısı başarısız.'
    man, mod = (r.get('manufacturer') or '').strip(), (r.get('model') or '').strip()
    ch = r.get('channels') or 0
    extra = f' · {ch} kanal' if ch else ''
    return True, f'Bağlantı başarılı · {man} {mod}{extra}'.replace('  ', ' ').strip()
