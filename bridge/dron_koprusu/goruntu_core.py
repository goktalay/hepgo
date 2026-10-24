"""Hepgo Dron Köprüsü — GÖRÜNTÜ çekirdeği (arayüzden bağımsız; Linux/Jetson başsız servisi kullanır, Windows'ta da ffmpeg ile çalışır).

Protokol v1.3 (docs/dron-kopru-protokolu.md): köprü sunucuya telemetriden AYRI ikinci bir WebSocket açar (DIŞA DOĞRU; NAT/4G arkası):
wss://<alan>/ws/drone/video, ilk çerçeve {v:1,t:'auth',key,host,platform,bridge_ver,caps}. Sunucu {t:'auth_ok',cameras:[…]} ile
kamera yapılandırmasını gönderir (Dron Yönetimi › Kameralar; SİTEDEN gelir, kayıt değişince {t:'video_cfg',cameras}); yerel conf
yalnız yedektir (sunucu 'cameras' göndermezse). Köprü izleyici olduğunda ({t:'want',camera_id,on}) kaynağı açar:
  - RTSP (gimbal kamera, ör. Siyi rtsp://192.168.144.25:8554/main.264) ya da RTP (köprüde UDP port dinler; SDP verilmezse üretilir).
  - FPS 'kaynak' (0) ya da kaynakla aynıysa ve ölçek yoksa YENİDEN KODLAMADAN (ffmpeg -c copy) — Jetson'da CPU harcanmaz.
  - Aksi hâlde yeniden kodlama: Jetson'da GStreamer donanım kodlayıcı (nvv4l2decoder + nvv4l2h264enc), yoksa x264enc / ffmpeg libx264.
  - H.265 kaynak: uyarı (tarayıcı oynatamayabilir) ya da `h265 = yeniden_kodla` ile H.264'e çevrilir.
ffmpeg çıktısı parçalı MP4'tür (frag_keyframe+empty_moov+default_base_moof); bu modül kutuları ayırır (init = ftyp+moov, parça =
moof+mdat), parçanın anahtar kareyle başlayıp başlamadığını trun/tfhd bayraklarından çözer ve ikili çerçeve olarak iter:
  [tür:1][kamera_id:4 big-endian][yük]  tür 1 init · 2 anahtar parça · 3 ara parça · 4 JPEG anlık görüntü.
Gönderim kuyruğu bayt sınırlıdır: ağ yavaşsa parçalar atlanır ve sonraki anahtar parçadan devam edilir (gecikme birikmez).
Kare gelmezse (NOFRAME_S) {t:'vstate',state:'kare_yok'} + süreç yeniden başlatılır (artan bekleme).
Python 3.8 uyumlu (Jetson Nano JetPack 4.6 → python3.8); yalnız standart kütüphane + websockets.
"""
import asyncio
import json
import os
import platform
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import time
from urllib.parse import quote, urlsplit, urlunsplit

T_INIT, T_KEY, T_DELTA, T_JPEG = 1, 2, 3, 4
NOFRAME_S = 10          # bu kadar sn parça gelmezse "kare yok" + yeniden başlat
SEND_MAX = 4 * 1024 * 1024   # kamera başına gönderim kuyruğu (bayt); aşılınca parça atlanır
PROBE_S = 10
SNAP_S = 12
PING_S = 20
FRAG_MS = 500           # ffmpeg -frag_duration (ms): anahtar kare dışında da parça kes → düşük gecikme
FATAL_CODES = {4400: 'Köprü kodu geçersiz ya da süresi dolmuş', 4403: 'Köprü kodu geçersiz (Dron Köprüleri › Kodu yenile)',
               4409: 'Bu köprü kodu başka bir cihazda açıldı; görüntü bağlantısı kapatıldı'}


def video_url(domain):
    """Test/geliştirme için HEPGO_GORUNTU_URL sunucu adresini ezer."""
    return os.environ.get('HEPGO_GORUNTU_URL') or 'wss://{}/ws/drone/video'.format(domain)


# ======================================================================
# Parçalı MP4 (ISO BMFF) çözümleme
# ======================================================================
def _boxes(buf, start=0, end=None):
    """(tür, kutu_başı, içerik_başı, kutu_sonu) üretir; yarım kutuda durur."""
    end = len(buf) if end is None else end
    i = start
    while i + 8 <= end:
        size, typ = struct.unpack('>I4s', bytes(buf[i:i + 8]))
        hdr = 8
        if size == 1:
            if i + 16 > end:
                return
            size = struct.unpack('>Q', bytes(buf[i + 8:i + 16]))[0]
            hdr = 16
        elif size == 0:
            size = end - i
        if size < hdr or i + size > end:
            return
        yield typ.decode('latin-1'), i, i + hdr, i + size
        i += size


def _child(buf, s, e, name):
    for typ, _b, cs, ce in _boxes(buf, s, e):
        if typ == name:
            return cs, ce
    return None


def fragment_info(moof):
    """moof kutusundan (anahtar_mı, örnek_sayısı). sample_is_non_sync_sample (0x10000) bayrağı: trun ilk örnek bayrağı >
    trun örnek bayrağı > tfhd varsayılan bayrağı. Bayrak bulunamazsa anahtar sayılır (ffmpeg frag_keyframe parçası)."""
    key, samples = True, 0
    top = _child(moof, 0, len(moof), 'moof')
    s, e = top if top else (0, len(moof))
    first_traf = True
    for typ, _b, cs, ce in _boxes(moof, s, e):
        if typ != 'traf':
            continue
        default_flags = None
        tf = _child(moof, cs, ce, 'tfhd')
        if tf:
            fl = struct.unpack('>I', bytes(moof[tf[0]:tf[0] + 4]))[0] & 0xFFFFFF
            off = tf[0] + 8   # version/flags + track_ID
            for bit, n in ((0x1, 8), (0x2, 4), (0x8, 4), (0x10, 4)):
                if fl & bit:
                    off += n
            if fl & 0x20 and off + 4 <= tf[1]:
                default_flags = struct.unpack('>I', bytes(moof[off:off + 4]))[0]
        tr = _child(moof, cs, ce, 'trun')
        if not tr:
            continue
        fl = struct.unpack('>I', bytes(moof[tr[0]:tr[0] + 4]))[0] & 0xFFFFFF
        count = struct.unpack('>I', bytes(moof[tr[0] + 4:tr[0] + 8]))[0]
        samples += count
        if not first_traf:
            continue
        first_traf = False
        off = tr[0] + 8
        if fl & 0x1:
            off += 4
        flags = None
        if fl & 0x4:
            flags = struct.unpack('>I', bytes(moof[off:off + 4]))[0]
            off += 4
        elif fl & 0x400 and count:
            o = off + (4 if fl & 0x100 else 0) + (4 if fl & 0x200 else 0)
            flags = struct.unpack('>I', bytes(moof[o:o + 4]))[0]
        if flags is None:
            flags = default_flags
        if flags is not None:
            key = not (flags & 0x10000)
    return key, samples


def codec_mime(init):
    """init segmentinden MSE tipi: 'video/mp4; codecs="avc1.PPCCLL"' ya da hvc1/hev1 (yaklaşık dizge)."""
    b = bytes(init)
    i = b.find(b'avcC')
    if i >= 0 and i + 8 <= len(b):
        p, c, l = b[i + 5], b[i + 6], b[i + 7]
        return 'video/mp4; codecs="avc1.{:02x}{:02x}{:02x}"'.format(p, c, l), 'h264'
    for tag in (b'hvc1', b'hev1'):
        if b.find(tag) >= 0:
            j = b.find(b'hvcC')
            if j >= 0 and j + 8 + 13 <= len(b):
                x = b[j + 4:]
                prof_space, tier, prof = x[1] >> 6, (x[1] >> 5) & 1, x[1] & 0x1F
                compat = struct.unpack('>I', x[2:6])[0]
                rev = int('{:032b}'.format(compat)[::-1], 2)
                level = x[12]
                ps = ['', 'A', 'B', 'C'][prof_space]
                return 'video/mp4; codecs="{}.{}{}.{:x}.{}{}.B0"'.format(tag.decode(), ps, prof, rev, 'H' if tier else 'L', level), 'h265'
            return 'video/mp4; codecs="{}.1.6.L93.B0"'.format(tag.decode()), 'h265'
    return 'video/mp4', None


class Fmp4Splitter:
    """ffmpeg'in stdout akışını kutulara böler: ('init', bayt) ve ('frag', bayt, anahtar_mı, örnek_sayısı)."""

    def __init__(self):
        self.buf = bytearray()
        self.head = bytearray()   # init biriktirme (ftyp + moov) / parça öncesi kutular (styp, sidx, prft)
        self.moof = None
        self.have_init = False

    def feed(self, data):
        self.buf += data
        out = []
        consumed = 0
        for typ, b, _cs, e in _boxes(self.buf):
            box = bytes(self.buf[b:e])
            consumed = e
            if typ == 'ftyp':
                self.head = bytearray(box)
                self.have_init = False
            elif typ == 'moov':
                out.append(('init', bytes(self.head) + box))
                self.head = bytearray()
                self.have_init = True
            elif typ == 'moof':
                self.moof = box
            elif typ == 'mdat':
                if self.moof is not None and self.have_init:
                    key, n = fragment_info(self.moof)
                    out.append(('frag', bytes(self.head) + self.moof + box, key, n))
                self.moof = None
                self.head = bytearray()
            elif typ in ('styp', 'sidx', 'prft') and self.have_init:
                self.head += box
            # diğer üst düzey kutular (free, mfra…) atlanır
        if consumed:
            del self.buf[:consumed]
        if len(self.buf) > 64 * 1024 * 1024:   # bozuk akış: sınırsız büyümesin
            self.buf = bytearray()
        return out


# ======================================================================
# Araç bulma ve komut üretimi
# ======================================================================
class Tools:
    """ffmpeg / ffprobe / GStreamer yolları ve Jetson donanım kodlayıcı varlığı (bir kez denetlenir)."""

    def __init__(self, ffmpeg='ffmpeg', ffprobe=None, encoder='otomatik', h265='uyar'):
        self.ffmpeg = shutil.which(ffmpeg) or ffmpeg
        self.ffprobe = shutil.which(ffprobe or 'ffprobe') or (ffprobe or '')
        self.gst = shutil.which('gst-launch-1.0')
        self.encoder = (encoder or 'otomatik').strip().lower()
        self.h265 = (h265 or 'uyar').strip().lower()
        self._elems = {}
        self._demux = None

    def gst_has(self, elem):
        if elem not in self._elems:
            ins = shutil.which('gst-inspect-1.0')
            ok = False
            if ins and self.gst:
                try:
                    ok = subprocess.run([ins, elem], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode == 0
                except Exception:   # noqa: BLE001
                    ok = False
            self._elems[elem] = ok
        return self._elems[elem]

    def ff_demux(self, name):
        """ffmpeg bu girişi (demuxer) okuyabiliyor mu? Bazı Jetson/statik ffmpeg derlemelerinde ağ girişleri (rtsp, sdp/rtp) yoktur
        ("Unrecognized option 'rtsp_transport'") — o zaman kaynak GStreamer (rtspsrc/udpsrc) ile alınır, ffmpeg yalnız fMP4'e sarar."""
        if self._demux is None:
            names = set()
            try:
                out = subprocess.run([self.ffmpeg, '-hide_banner', '-demuxers'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     timeout=10).stdout.decode('utf-8', 'replace')
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and 'D' in parts[0]:
                        names.update(parts[1].split(','))
            except Exception:   # noqa: BLE001
                names = set()
            self._demux = names
        return name in self._demux if self._demux else True   # liste alınamazsa engelleme (eski davranış)

    def ff_reads(self, cfg):
        """ffmpeg bu kamerayı doğrudan açabilir mi (rtsp → 'rtsp' demuxer, rtp → 'sdp' demuxer)?"""
        kind = cfg.get('kind')
        if kind == 'rtsp':
            return self.ff_demux('rtsp')
        if kind == 'rtp':
            return self.ff_demux('sdp')
        return True

    def pick_encoder(self):
        """'nvv4l2h264enc' (Jetson donanım) | 'x264enc' (GStreamer yazılım) | 'libx264' (ffmpeg yazılım)."""
        if self.encoder in ('nvv4l2h264enc', 'x264enc', 'libx264'):
            return self.encoder
        if self.gst and self.gst_has('nvv4l2h264enc') and self.gst_has('nvv4l2decoder'):
            return 'nvv4l2h264enc'
        return 'libx264'

    def info(self):
        return {'ffmpeg': bool(shutil.which(self.ffmpeg) or os.path.isfile(self.ffmpeg)), 'ffprobe': bool(self.ffprobe and shutil.which(self.ffprobe)),
                'gstreamer': bool(self.gst), 'encoder': self.pick_encoder(), 'ffmpeg_rtsp': self.ff_demux('rtsp')}


def source_url(cfg):
    """RTSP adresine kullanıcı adı/parola eklenir (yalnız köprü sürecinde; sunucu kaydında URL kimliksizdir)."""
    url = cfg.get('url') or ''
    user, pw = cfg.get('username') or '', cfg.get('password') or ''
    if not user:
        return url
    p = urlsplit(url)
    netloc = quote(user, safe='') + (':' + quote(pw, safe='') if pw else '') + '@' + p.netloc.split('@')[-1]
    return urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))


def redact(text):
    """Günlüklerde parola görünmesin: rtsp://kullanıcı:parola@ → rtsp://kullanıcı:***@"""
    import re
    return re.sub(r'(rtsps?://[^:/@\s]+):[^@\s]*@', r'\1:***@', str(text))


def sdp_text(cfg):
    if (cfg.get('sdp') or '').strip():
        return cfg['sdp'].strip() + '\n'
    pt = int(cfg.get('payload_type') or 96)
    enc = 'H265' if cfg.get('codec') == 'h265' else 'H264'
    return ('v=0\no=- 0 0 IN IP4 127.0.0.1\ns=HEPGO\nc=IN IP4 0.0.0.0\nt=0 0\n'
            'm=video {} RTP/AVP {}\na=rtpmap:{} {}/90000\n').format(int(cfg.get('rtp_port') or 5600), pt, pt, enc)


def ffmpeg_input(cfg, sdp_path=None):
    """ffmpeg giriş seçenekleri (düşük gecikme)."""
    common = ['-hide_banner', '-loglevel', 'warning', '-fflags', '+genpts+nobuffer', '-flags', 'low_delay']
    if cfg.get('kind') == 'rtp':
        return common + ['-protocol_whitelist', 'file,udp,rtp', '-reorder_queue_size', '64', '-i', sdp_path]
    if cfg.get('kind') == 'test':   # geliştirme: ffmpeg'in iç test görüntüsü
        return common + ['-re', '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate={}'.format(int(cfg.get('fps') or 25))]
    return common + ['-rtsp_transport', cfg.get('transport') or 'tcp', '-i', source_url(cfg)]


def fmp4_out():
    return ['-an', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov+default_base_moof', '-frag_duration', str(FRAG_MS * 1000),
            '-flush_packets', '1', 'pipe:1']


def plan(cfg, tools, probe=None):
    """Kaynak + hedefe göre işlem planı: {'copy': bool, 'codec': 'h264'|'h265', 'fps': hedef, 'src_fps', 'reason'}.
    copy: H.264 (ya da uyarılı H.265) kaynak, FPS kaynak/aynı, ölçek yok."""
    probe = probe or {}
    codec = probe.get('codec') or ('h265' if cfg.get('codec') == 'h265' else 'h264')
    if cfg.get('kind') == 'test':
        codec = 'raw'
    src_fps = probe.get('fps')
    fps = int(cfg.get('fps') or 0)
    same_fps = fps == 0 or (src_fps is not None and abs(src_fps - fps) < 0.6)
    scale = bool(cfg.get('width') and cfg.get('height'))
    reason = []
    if codec == 'raw':
        reason.append('ham kaynak')
    if not same_fps:
        reason.append('FPS {} → {}'.format(src_fps if src_fps else '?', fps))
    if scale:
        reason.append('ölçek {}×{}'.format(cfg['width'], cfg['height']))
    if codec == 'h265' and tools.h265 == 'yeniden_kodla':
        reason.append('H.265 → H.264')
    if codec not in ('h264', 'h265', 'raw'):
        reason.append('{} → H.264'.format(codec))
    return {'copy': not reason, 'codec': codec if not reason else 'h264', 'fps': fps or src_fps or 25, 'src_fps': src_fps,
            'reason': ', '.join(reason)}


def gst_source(cfg, src_codec):
    """GStreamer kaynak + RTP çözme (rtspsrc / udpsrc → depay → parse): ['rtspsrc', …, '!', 'rtph264depay', '!', 'h264parse']."""
    depay, parse = ('rtph265depay', 'h265parse') if src_codec == 'h265' else ('rtph264depay', 'h264parse')
    if cfg['kind'] == 'rtsp':
        src = ['rtspsrc', 'location=' + cfg.get('url', ''), 'latency=150', 'protocols=' + ('tcp' if (cfg.get('transport') or 'tcp') == 'tcp' else 'udp')]
        if cfg.get('username'):
            src += ['user-id=' + cfg['username'], 'user-pw=' + (cfg.get('password') or '')]
        src += ['!', 'application/x-rtp,media=video,encoding-name={}'.format('H265' if src_codec == 'h265' else 'H264')]   # yalnız bu kodekli video pedi
    else:
        caps = 'application/x-rtp,media=video,clock-rate=90000,encoding-name={},payload={}'.format(
            'H265' if src_codec == 'h265' else 'H264', int(cfg.get('payload_type') or 96))
        src = ['udpsrc', 'port={}'.format(int(cfg.get('rtp_port') or 5600)), 'caps=' + caps, '!', 'rtpjitterbuffer', 'latency=100']
    return src + ['!', depay, '!', parse]


async def gst_probe(cfg, tools, timeout=8):
    """ffprobe yoksa/okuyamıyorsa RTSP kodeğini GStreamer ile öğren: rtspsrc pedinin RTP başlığı (encoding-name=H264|H265)."""
    if not tools.gst or cfg.get('kind') != 'rtsp':
        return {}
    args = [tools.gst, '-v', 'rtspsrc', 'location=' + cfg.get('url', ''), 'latency=150',
            'protocols=' + ('tcp' if (cfg.get('transport') or 'tcp') == 'tcp' else 'udp')]
    if cfg.get('username'):
        args += ['user-id=' + cfg['username'], 'user-pw=' + (cfg.get('password') or '')]
    args += ['!', 'fakesink']
    p = None
    try:
        p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        end = time.time() + timeout
        while time.time() < end:
            try:
                line = await asyncio.wait_for(p.stdout.readline(), max(0.1, end - time.time()))
            except asyncio.TimeoutError:
                break
            if not line:
                break
            t = line.decode('utf-8', 'replace')
            if 'media=(string)video' in t and 'encoding-name=(string)' in t:
                enc = t.split('encoding-name=(string)', 1)[1].split(',', 1)[0].strip().upper()
                return {'codec': {'H264': 'h264', 'H265': 'h265', 'HEVC': 'h265'}.get(enc, enc.lower())}
    except Exception:   # noqa: BLE001
        return {}
    finally:
        _kill(p)
    return {}


def gst_copy_commands(cfg, tools, codec, tail):
    """Yeniden kodlamadan: GStreamer kaynaktan H.264/H.265 bayt akışı → ffmpeg (-f h264|hevc, duvar saati zaman damgası) + tail."""
    caps = 'video/x-h265' if codec == 'h265' else 'video/x-h264'
    gst = [tools.gst, '-q', '-e'] + gst_source(cfg, codec) + ['config-interval=-1', '!', caps + ',stream-format=byte-stream,alignment=au', '!', 'fdsink', 'fd=1']
    mux = [tools.ffmpeg, '-hide_banner', '-loglevel', 'warning', '-fflags', '+genpts+nobuffer', '-use_wallclock_as_timestamps', '1',
           '-f', 'hevc' if codec == 'h265' else 'h264', '-i', 'pipe:0'] + tail
    return [gst, mux]


def build_commands(cfg, tools, pl, sdp_path=None):
    """Çalıştırılacak süreçler: [ffmpeg] ya da [gst-launch, ffmpeg] (gst H.264 bayt akışı → ffmpeg fMP4 sarmalayıcı)."""
    ff = tools.ffmpeg
    via_gst = cfg.get('kind') in ('rtsp', 'rtp') and not tools.ff_reads(cfg)   # ffmpeg ağ girişi yok → kaynak GStreamer'dan
    if via_gst and not tools.gst:
        raise RuntimeError("Bu ffmpeg {} girişini desteklemiyor ve GStreamer yok: sudo apt install --reinstall ffmpeg gstreamer1.0-tools "
                           "gstreamer1.0-plugins-good gstreamer1.0-plugins-bad".format(cfg.get('kind', '').upper()))
    if via_gst:
        src_codec = 'h265' if (pl.get('src_codec') or cfg.get('codec')) == 'h265' else 'h264'
        need = ['rtspsrc' if cfg.get('kind') == 'rtsp' else 'udpsrc', 'rtp{}depay'.format(src_codec), '{}parse'.format(src_codec)]
        missing = [e for e in need if not tools.gst_has(e)]
        if missing:
            raise RuntimeError('GStreamer eklentisi eksik: {} — sudo apt install gstreamer1.0-plugins-good gstreamer1.0-plugins-bad '
                               'gstreamer1.0-libav'.format(', '.join(missing)))
    if pl['copy']:
        tag = ['-tag:v', 'hvc1'] if pl['codec'] == 'h265' else []
        if via_gst:
            return gst_copy_commands(cfg, tools, pl['codec'], ['-c:v', 'copy'] + tag + fmp4_out())
        return [[ff] + ffmpeg_input(cfg, sdp_path) + ['-map', '0:v:0', '-c:v', 'copy'] + tag + fmp4_out()]
    fps = int(pl['fps'] or 25)
    kbps = int(cfg.get('bitrate_kbps') or 2000)
    w, h = cfg.get('width'), cfg.get('height')
    enc = tools.pick_encoder()
    if via_gst and enc == 'libx264':
        enc = 'x264enc'   # kaynak GStreamer'dan geliyorsa kodlama da GStreamer'da
    if enc in ('nvv4l2h264enc', 'x264enc') and tools.gst and cfg.get('kind') in ('rtsp', 'rtp'):
        gst = [tools.gst, '-q', '-e']
        src_codec = 'h265' if (pl.get('src_codec') or cfg.get('codec')) == 'h265' else 'h264'
        size = ',width={},height={}'.format(w, h) if w and h else ''
        if enc == 'nvv4l2h264enc':
            chain = ['nvv4l2decoder', '!', 'nvvidconv', '!', 'video/x-raw,format=I420', '!', 'videorate', 'drop-only=true', '!',
                     'video/x-raw,framerate={}/1'.format(fps), '!', 'nvvidconv', '!', 'video/x-raw(memory:NVMM),format=NV12' + size, '!',
                     'nvv4l2h264enc', 'bitrate={}'.format(kbps * 1000), 'insert-sps-pps=true', 'iframeinterval={}'.format(fps * 2),
                     'idrinterval={}'.format(fps * 2), 'maxperf-enable=true']
        else:
            chain = ['avdec_' + ('h265' if src_codec == 'h265' else 'h264'), '!', 'videoconvert', '!', 'videoscale', '!', 'videorate', 'drop-only=true', '!',
                     'video/x-raw,format=I420,framerate={}/1'.format(fps) + size, '!',
                     'x264enc', 'tune=zerolatency', 'speed-preset=ultrafast', 'bitrate={}'.format(kbps), 'key-int-max={}'.format(fps * 2)]
        gst += gst_source(cfg, src_codec) + ['!'] + chain + ['!', 'h264parse', 'config-interval=-1', '!',
                                                              'video/x-h264,stream-format=byte-stream,alignment=au', '!', 'fdsink', 'fd=1']
        mux = [ff, '-hide_banner', '-loglevel', 'warning', '-fflags', '+genpts+nobuffer', '-f', 'h264', '-framerate', str(fps), '-i', 'pipe:0',
               '-c:v', 'copy'] + fmp4_out()
        return [gst, mux]
    vf = ['fps={}'.format(fps)]
    if w and h:
        vf.append('scale={}:{}'.format(w, h))
    return [[ff] + ffmpeg_input(cfg, sdp_path) + ['-map', '0:v:0', '-vf', ','.join(vf), '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
                                                  '-pix_fmt', 'yuv420p', '-bf', '0', '-g', str(fps * 2), '-b:v', '{}k'.format(kbps),
                                                  '-maxrate', '{}k'.format(kbps), '-bufsize', '{}k'.format(kbps)] + fmp4_out()]


async def probe(cfg, tools, sdp_path=None):
    """ffprobe ile kaynak kodeki/FPS/çözünürlük (yoksa {}). Zaman aşımı PROBE_S."""
    if cfg.get('kind') in ('rtsp', 'rtp') and not tools.ff_reads(cfg):
        return await gst_probe(cfg, tools)   # ffmpeg/ffprobe bu girişi okuyamıyor: kodek GStreamer'dan (RTP: kamera kaydından)
    if not tools.ffprobe or cfg.get('kind') == 'test':
        return {}
    args = [tools.ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name,width,height,avg_frame_rate,r_frame_rate',
            '-of', 'json']
    if cfg.get('kind') == 'rtp':
        args += ['-protocol_whitelist', 'file,udp,rtp', sdp_path]
    else:
        args += ['-rtsp_transport', cfg.get('transport') or 'tcp', source_url(cfg)]
    try:
        p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await asyncio.wait_for(p.communicate(), PROBE_S)
        except asyncio.TimeoutError:
            _kill(p)
            return {}
        s = (json.loads(out.decode() or '{}').get('streams') or [{}])[0]
    except Exception:   # noqa: BLE001
        return {}

    def rate(v):
        try:
            a, b = str(v).split('/')
            return round(float(a) / float(b), 2) if float(b) else None
        except (ValueError, ZeroDivisionError):
            return None
    codec = {'h264': 'h264', 'hevc': 'h265'}.get(s.get('codec_name'), s.get('codec_name'))
    fps = rate(s.get('avg_frame_rate')) or rate(s.get('r_frame_rate'))
    if fps and fps > 240:
        fps = None
    return {'codec': codec, 'fps': fps, 'w': s.get('width'), 'h': s.get('height')}


def _kill(p):
    if p is None or p.returncode is not None:
        return
    try:
        if hasattr(os, 'killpg'):
            os.killpg(p.pid, signal.SIGKILL)
        else:
            p.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            p.kill()
        except Exception:   # noqa: BLE001
            pass


# ======================================================================
# Kamera işçisi: süreçleri çalıştırır, kutuları ayırır, köprüye verir
# ======================================================================
class CameraWorker:
    def __init__(self, cfg, tools, emit, state, log):
        self.cfg, self.tools = dict(cfg), tools
        self.emit, self.state_cb, self.log = emit, state, log   # emit(tür, bayt) · state(durum, ayrıntı, ek) · log(metin)
        self.id = int(cfg['id'])
        self.task = None
        self.procs = []
        self.init = None
        self.last_key = None      # son anahtar parça (anlık görüntü önbellekten)
        self.last_frag = 0.0
        self.stats = {'bytes': 0, 'samples': 0, 't': time.time()}
        self.stat = {}
        self.state = 'bekliyor'
        self.plan = None
        self.err_tail = []

    def running(self):
        return self.task is not None and not self.task.done()

    def start(self):
        if not self.running():
            self.task = asyncio.ensure_future(self._run())

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):   # noqa: BLE001
                pass
        self.task = None
        self._kill_all()
        self.init, self.last_key = None, None
        self._set('bekliyor', 'Yayın durdu (izleyen yok)')

    def _kill_all(self):
        for p in self.procs:
            _kill(p)
        self.procs = []

    def _set(self, state, detail='', **extra):
        self.state = state
        try:
            self.state_cb(self.id, state, detail, extra)
        except Exception:   # noqa: BLE001
            pass

    async def _run(self):
        backoff = 2
        while True:
            sdp_path = None
            try:
                if self.cfg.get('kind') == 'rtp':
                    fd, sdp_path = tempfile.mkstemp(prefix='hepgo-rtp-', suffix='.sdp')
                    with os.fdopen(fd, 'w') as f:
                        f.write(sdp_text(self.cfg))
                self._set('basliyor', 'Kaynak açılıyor')
                pr = await probe(self.cfg, self.tools, sdp_path)
                pl = plan(self.cfg, self.tools, pr)
                pl['src_codec'] = pr.get('codec')
                self.plan = pl
                if pr.get('codec') == 'h265' and pl['copy']:
                    self._set('h265', 'Kaynak H.265: tarayıcı oynatamayabilir (kamerada H.264 seçin ya da köprü ayarında h265 = yeniden_kodla)')
                cmds = build_commands(self.cfg, self.tools, pl, sdp_path)
                self.log('kamera #{} {}: {}'.format(self.id, 'kopyala (-c copy)' if pl['copy'] else 'yeniden kodla ({})'.format(pl['reason']),
                                                    redact(' | '.join(c[0] for c in cmds))))
                got = await self._spawn_and_read(cmds)
                if got:
                    backoff = 2
            except asyncio.CancelledError:
                self._kill_all()
                raise
            except FileNotFoundError as e:
                self._set('hata', 'Araç bulunamadı: {} (sudo apt install ffmpeg)'.format(e.filename or e))
            except Exception as e:   # noqa: BLE001
                self._set('hata', redact('{}: {}'.format(type(e).__name__, e))[:280])
            finally:
                self._kill_all()
                if sdp_path:
                    try:
                        os.unlink(sdp_path)
                    except OSError:
                        pass
            gst_err = [e for e in self.err_tail if e.startswith('gst: ')]   # GStreamer kaynağı düştüyse asıl neden odur (ffmpeg yalnız "akış yok" der)
            tail = redact(' / '.join((gst_err[-2:] + [e for e in self.err_tail if not e.startswith('gst: ')][-1:]) if gst_err else self.err_tail[-3:]))[:280]
            if self.state not in ('hata',):
                self._set('kare_yok', 'Kaynaktan görüntü gelmiyor; {} sn sonra yeniden denenecek{}'.format(backoff, (' — ' + tail) if tail else ''))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _spawn_and_read(self, cmds):
        self.err_tail = []
        kw = {'start_new_session': True} if hasattr(os, 'setsid') else {}
        if len(cmds) == 1:
            p = await asyncio.create_subprocess_exec(*cmds[0], stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.PIPE, **kw)
            self.procs = [p]
            reader = p.stdout
            errs = [p.stderr]
        else:
            r, w = os.pipe()
            try:
                p1 = await asyncio.create_subprocess_exec(*cmds[0], stdin=asyncio.subprocess.DEVNULL, stdout=w, stderr=asyncio.subprocess.PIPE, **kw)
                p2 = await asyncio.create_subprocess_exec(*cmds[1], stdin=r, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **kw)
            finally:
                os.close(r)
                os.close(w)
            self.procs = [p1, p2]
            reader = p2.stdout
            errs = [p1.stderr, p2.stderr]
        tags = ['gst', 'ffmpeg'] if len(errs) == 2 else ['']
        err_tasks = [asyncio.ensure_future(self._stderr(s, t)) for s, t in zip(errs, tags)]
        sp = Fmp4Splitter()
        got = False
        try:
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(65536), NOFRAME_S)
                except asyncio.TimeoutError:
                    self.log('kamera #{}: {} sn parça yok'.format(self.id, NOFRAME_S))
                    return got
                if not data:
                    return got
                for ev in sp.feed(data):
                    if ev[0] == 'init':
                        self.init = ev[1]
                        mime, codec = codec_mime(ev[1])
                        self.mime = mime
                        self._set('h265' if codec == 'h265' and self.state == 'h265' else 'basliyor', 'Akış başladı', mime=mime)
                        self.emit(T_INIT, ev[1])
                    else:
                        _t, frag, key, n = ev
                        got = True
                        self.last_frag = time.time()
                        if key:
                            self.last_key = frag
                        self.emit(T_KEY if key else T_DELTA, frag)
                        if self.state not in ('canli', 'h265'):
                            self._set('canli', 'Yayında', mime=getattr(self, 'mime', None))
                        self._count(len(frag), n)
        finally:
            for t in err_tasks:
                t.cancel()

    async def _stderr(self, stream, tag=''):
        try:
            while True:
                line = await stream.readline()
                if not line:
                    return
                txt = line.decode('utf-8', 'replace').strip()
                if txt:
                    txt = (tag + ': ' + txt) if tag else txt
                    self.err_tail = (self.err_tail + [txt])[-12:]
                    self.log('kamera #{} süreç: {}'.format(self.id, redact(txt)[:200]))
        except (asyncio.CancelledError, Exception):   # noqa: BLE001
            return

    def _count(self, nbytes, samples):
        s = self.stats
        s['bytes'] += nbytes
        s['samples'] += samples
        dt = time.time() - s['t']
        if dt >= 2:
            pl = self.plan or {}
            self.stat = {'kbps': round(s['bytes'] * 8 / 1000 / dt), 'fps': round(s['samples'] / dt, 1), 'copy': bool(pl.get('copy')),
                         'src_fps': pl.get('src_fps'), 'codec': pl.get('codec'), 'mime': getattr(self, 'mime', None)}
            self.stats = {'bytes': 0, 'samples': 0, 't': time.time()}
            try:
                self.state_cb(self.id, None, None, {'stat': self.stat})
            except Exception:   # noqa: BLE001
                pass

    async def _snapshot_gst(self, out):
        """ffmpeg ağ girişi yoksa: GStreamer kaynaktan H.264/H.265 bayt akışı → ffmpeg tek JPEG kare."""
        codec = 'h265' if (self.plan or {}).get('src_codec') == 'h265' or self.cfg.get('codec') == 'h265' else 'h264'
        gst, ff = gst_copy_commands(self.cfg, self.tools, codec, out)
        r, w = os.pipe()
        p1 = p2 = None
        try:
            p1 = await asyncio.create_subprocess_exec(*gst, stdin=asyncio.subprocess.DEVNULL, stdout=w, stderr=asyncio.subprocess.DEVNULL)
            p2 = await asyncio.create_subprocess_exec(*ff, stdin=r, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        finally:
            os.close(r)
            os.close(w)
        try:
            jpg, err = await asyncio.wait_for(p2.communicate(), SNAP_S)
        except asyncio.TimeoutError:
            _kill(p2)
            raise RuntimeError('Kaynaktan kare alınamadı (zaman aşımı, GStreamer)')
        finally:
            _kill(p1)
        if not jpg.startswith(b'\xff\xd8'):
            raise RuntimeError(redact(err.decode('utf-8', 'replace').strip().splitlines()[-1] if err.strip() else 'JPEG üretilemedi')[:200])
        return jpg

    async def snapshot(self):
        """JPEG: yayın açıksa önbellekteki init + son anahtar parçadan (kaynağa ikinci bağlantı yok — RTP portu meşgul olsa da çalışır),
        değilse kaynaktan tek kare."""
        ff = self.tools.ffmpeg
        out = ['-frames:v', '1', '-vf', "scale='min(1280,iw)':-2", '-q:v', '5', '-f', 'image2', '-c:v', 'mjpeg', 'pipe:1']
        sdp_path = None
        try:
            if self.running() and self.init and self.last_key:
                args = [ff, '-hide_banner', '-loglevel', 'error', '-f', 'mp4', '-i', 'pipe:0'] + out
                data_in = self.init + self.last_key
            else:
                if self.cfg.get('kind') == 'rtp':
                    fd, sdp_path = tempfile.mkstemp(prefix='hepgo-rtp-', suffix='.sdp')
                    with os.fdopen(fd, 'w') as f:
                        f.write(sdp_text(self.cfg))
                if self.cfg.get('kind') in ('rtsp', 'rtp') and not self.tools.ff_reads(self.cfg) and self.tools.gst:
                    return await self._snapshot_gst(out)
                args = [ff] + ffmpeg_input(self.cfg, sdp_path) + out
                data_in = None
            p = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE if data_in else asyncio.subprocess.DEVNULL,
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                jpg, err = await asyncio.wait_for(p.communicate(data_in), SNAP_S)
            except asyncio.TimeoutError:
                _kill(p)
                raise RuntimeError('Kaynaktan kare alınamadı (zaman aşımı)')
            if not jpg.startswith(b'\xff\xd8'):
                raise RuntimeError(redact(err.decode('utf-8', 'replace').strip().splitlines()[-1] if err.strip() else 'JPEG üretilemedi')[:200])
            return jpg
        finally:
            if sdp_path:
                try:
                    os.unlink(sdp_path)
                except OSError:
                    pass


# ======================================================================
# Sunucu tarafı: görüntü WebSocket'i
# ======================================================================
class VideoBridge:
    """Görüntü bağlantısı yaşam döngüsü. ui(olay, *veri): 'video' (durum, ayrıntı), 'log' (metin).
    local_cameras: sunucu kamera listesi göndermezse (eski sunucu) kullanılacak yerel conf kameraları."""

    def __init__(self, domain, key, tools, ui=None, local_cameras=None, always=False, version='', caps=None):
        self.domain, self.key, self.tools = domain, key, tools
        self.ui = ui or (lambda ev, *a: print(ev, *a))
        self.local = list(local_cameras or [])
        self.always = always          # izleyici olmasa da yayınla (yerel conf 'surekli')
        self.version, self.caps = version, list(caps or ['video'])
        self.workers = {}             # kamera_id → CameraWorker
        self.cfgs = {}
        self.wanted = set()
        self.ws = None
        self.stopped = False
        self.loop = None
        self.q = None                 # gönderim kuyruğu (çerçeveler)
        self.qbytes = {}              # kamera_id → kuyruktaki bayt
        self.skip = set()             # kuyruk taşınca anahtar parçaya dek atlanan kameralar
        self.cam_state = {}           # kamera_id → {state, detail, stat}
        self.server_state = ('bekliyor', '')
        self.sent = 0
        self.clk_off = None           # sunucu saati − yerel saat (ms; ping/pong yarı-RTT ile) → parça zaman damgası (gerçek gecikme)
        self.clk_rtt = None
        self.clk_n = 0

    def status(self):
        return {'server': self.server_state[0], 'detail': self.server_state[1], 'sent': self.sent,
                'cameras': {str(k): {'name': (self.cfgs.get(k) or {}).get('name'), 'wanted': k in self.wanted, **v} for k, v in self.cam_state.items()},
                'tools': self.tools.info()}

    def stop(self):
        self.stopped = True
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._shutdown()))

    async def _shutdown(self):
        for w in list(self.workers.values()):
            await w.stop()
        try:
            if self.ws:
                await self.ws.close()
        except Exception:   # noqa: BLE001
            pass

    # ---- işçiden gelen ----
    def _emit(self, cam_id, typ, payload):
        if self.q is None or self.ws is None:
            return
        n = len(payload) + 5
        if typ == T_INIT:
            self.skip.add(cam_id)
        elif cam_id in self.skip:
            if typ != T_KEY:
                return
        if typ != T_INIT and self.qbytes.get(cam_id, 0) + n > SEND_MAX:
            self.skip.add(cam_id)   # ağ yavaş: anahtar parçaya dek atla (gecikme birikmesin)
            return
        if typ == T_KEY:
            self.skip.discard(cam_id)
        if self.clk_off is not None:   # parçanın köprüden çıkış anı, SUNUCU saatiyle (aynı kuyruk → sıra korunur)
            self.q.put_nowait((cam_id, 0, json.dumps({'t': 'fts', 'camera_id': cam_id, 'ms': round(time.time() * 1000 + self.clk_off)})))
        self.qbytes[cam_id] = self.qbytes.get(cam_id, 0) + n
        self.q.put_nowait((cam_id, n, bytes([typ]) + struct.pack('>I', cam_id) + payload))

    def _state(self, cam_id, state, detail, extra):
        cs = self.cam_state.setdefault(cam_id, {})
        if extra.get('stat'):
            cs['stat'] = extra['stat']
            asyncio.ensure_future(self._send_json(dict({'t': 'stat', 'camera_id': cam_id}, **extra['stat'])))
            return
        cs['state'], cs['detail'] = state, detail
        msg = {'t': 'vstate', 'camera_id': cam_id, 'state': state, 'detail': detail}
        if extra.get('mime'):
            msg['mime'] = extra['mime']
        self.ui('video', '#{} {}'.format(cam_id, state), detail)
        asyncio.ensure_future(self._send_json(msg))

    async def _send_json(self, obj):
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps(obj, ensure_ascii=False))
        except Exception:   # noqa: BLE001
            pass

    # ---- yapılandırma ----
    async def apply_cfg(self, cams):
        new = {int(c['id']): c for c in cams if c.get('id') is not None}
        for cid in list(self.workers):
            if cid not in new or new[cid] != self.cfgs.get(cid):
                await self.workers.pop(cid).stop()
        self.cfgs = new
        for cid in list(self.cam_state):
            if cid not in new:
                self.cam_state.pop(cid, None)
        for cid, c in new.items():
            self.cam_state.setdefault(cid, {'state': 'bekliyor', 'detail': ''})
            if cid not in self.workers:
                self.workers[cid] = CameraWorker(c, self.tools, lambda t, p, _c=cid: self._emit(_c, t, p), self._state,
                                                 lambda s: self.ui('log', s))
            if self.always or cid in self.wanted:
                self.workers[cid].start()
        self.ui('log', 'Kamera yapılandırması: ' + (', '.join('#{} {} ({})'.format(k, v.get('name'), v.get('kind')) for k, v in new.items()) or 'kamera yok'))

    async def want(self, cid, on):
        if on:
            self.wanted.add(cid)
            w = self.workers.get(cid)
            if w:
                w.start()
        else:
            self.wanted.discard(cid)
            w = self.workers.get(cid)
            if w and not self.always:
                await w.stop()

    async def snap(self, cid, rid=None):
        w = self.workers.get(cid)
        try:
            if w is None:
                raise RuntimeError('Kamera bu köprüde tanımlı değil')
            jpg = await w.snapshot()
            if self.ws is not None:
                await self.ws.send(bytes([T_JPEG]) + struct.pack('>I', cid) + jpg)
        except Exception as e:   # noqa: BLE001
            await self._send_json({'t': 'snap_err', 'camera_id': cid, 'rid': rid, 'error': redact(str(e))[:300] or type(e).__name__})

    # ---- WebSocket ----
    async def run(self):
        import websockets
        self.loop = asyncio.get_event_loop()
        backoff = 2
        while not self.stopped:
            url = video_url(self.domain)
            self.server_state = ('baglaniyor', url)
            self.ui('video', 'baglaniyor', url)
            self.q = asyncio.Queue()
            self.qbytes, self.skip = {}, set()
            try:
                async with websockets.connect(url, max_size=8 * 1024 * 1024, ping_interval=None, open_timeout=15, close_timeout=3) as ws:
                    await ws.send(json.dumps({'v': 1, 't': 'auth', 'key': self.key, 'host': socket.gethostname()[:120],
                                              'platform': platform.system().lower()[:40], 'bridge_ver': self.version, 'caps': self.caps}))
                    first = json.loads(await asyncio.wait_for(ws.recv(), 15))
                    if first.get('t') != 'auth_ok':
                        raise _Fatal(FATAL_CODES[4403])
                    self.ws = ws
                    self.server_state = ('bagli', str(first.get('name') or ''))
                    self.ui('video', 'bagli', '{} · {} kamera'.format(first.get('name'), len(first.get('cameras') or [])))
                    backoff = 2
                    await self.apply_cfg(first['cameras'] if 'cameras' in first else self.local)
                    tasks = [asyncio.ensure_future(self._sender(ws)), asyncio.ensure_future(self._pinger())]
                    try:
                        await self._receiver(ws)
                    finally:
                        for t in tasks:
                            t.cancel()
                        self.ws = None
                        for w in list(self.workers.values()):   # bağlantı yokken kaynak açık kalmasın (bant/CPU)
                            await w.stop()
                        self.wanted.clear()
            except _Fatal as e:
                self.server_state = ('hata', str(e))
                self.ui('video', 'hata', str(e))
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:   # noqa: BLE001
                code = getattr(getattr(e, 'rcvd', None), 'code', None)
                if code in FATAL_CODES and code != 4409:
                    self.server_state = ('hata', FATAL_CODES[code])
                    self.ui('video', 'hata', FATAL_CODES[code])
                    return
                wait = 60 if code in (4429, 4409) else backoff
                self.server_state = ('yeniden', '{}: {}'.format(type(e).__name__, str(e)[:120]))
                self.ui('video', 'yeniden', '{}: {} · {} sn sonra yeniden'.format(type(e).__name__, str(e)[:120], wait))
                if self.stopped:
                    break
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, 30)
        await self._shutdown()

    async def _sender(self, ws):
        while True:
            cid, n, frame = await self.q.get()
            self.qbytes[cid] = max(0, self.qbytes.get(cid, 0) - n)
            try:
                await ws.send(frame)
                self.sent += 1
            except Exception:   # noqa: BLE001
                return

    async def _pinger(self):
        while True:
            await self._send_json({'t': 'ping', 'c': round(time.time() * 1000)})   # c: saat eşitleme (sunucu ms + c ile döner)
            await asyncio.sleep(3 if self.clk_n < 6 else PING_S)

    def _on_pong(self, m):
        try:
            c, ms = float(m['c']), float(m['ms'])
        except (KeyError, TypeError, ValueError):
            return
        now = time.time() * 1000
        rtt = now - c
        if rtt < 0 or rtt > 10000:
            return
        off = ms + rtt / 2 - now
        if self.clk_off is None or rtt <= (self.clk_rtt or rtt) * 1.5:   # düşük RTT örnekleri güvenilir
            self.clk_off = off if self.clk_off is None else self.clk_off * 0.7 + off * 0.3
            self.clk_rtt = rtt if self.clk_rtt is None else min(rtt, self.clk_rtt * 1.05)
        self.clk_n += 1

    async def _receiver(self, ws):
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            t = m.get('t')
            try:
                cid = int(m.get('camera_id') or 0)
            except (TypeError, ValueError):
                cid = 0
            if t == 'pong':
                self._on_pong(m)
            elif t == 'video_cfg':
                await self.apply_cfg(m.get('cameras') or [])
            elif t == 'want':
                await self.want(cid, bool(m.get('on')))
            elif t == 'snap':
                asyncio.ensure_future(self.snap(cid, m.get('rid')))


class _Fatal(Exception):
    pass
