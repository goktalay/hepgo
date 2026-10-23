"""Hepgo Dron Köprüsü — Linux / Jetson paketi (bridge/dron_koprusu_linux + paylaşılan kopru_core / goruntu_core) testleri:
1) Python 3.8 uyumu: ast.parse(feature_version=(3, 8)) + 3.9+ API/sözdizimi taraması (python3.8 yoksa yorumlayıcısız denetim; varsa derleme de).
2) goruntu_core: gerçek fMP4 (PyAV libx264, frag_keyframe+empty_moov+default_base_moof) kutu ayırma, anahtar parça tespiti, MSE kodek dizgesi;
   işlem planı (copy / yeniden kodlama), ffmpeg / GStreamer (nvv4l2h264enc) komutları, RTP SDP, RTSP kimlik ekleme ve günlükte gizleme.
3) hepgo_kopru: conf okuma/yazma (eslestir yorumları korur), bağlantı ve yedek kamera ayrıştırma, `durum --json`.
4) Paket: tools/kopru_linux_paket.py tar.gz içeriği, install.sh / uninstall.sh `bash -n`, açılan paketten `--surum`.
5) Uçtan uca: geçici HEPGO sunucusu + `hepgo_kopru.py calistir` (sahte ffmpeg/ffprobe) → telemetri köprüsü 'video' yeteneğiyle bağlanır,
   site kamera ayarı video_cfg ile gelir, izleyici init + parçaları alır, JPEG anlık görüntü, durum dosyası.
Çalıştırma: .venv/bin/python -m tests.test_kopru_linux
"""
import ast
import json
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINUX = ROOT / 'bridge' / 'dron_koprusu_linux'
CORE = ROOT / 'bridge' / 'dron_koprusu'
PY = sys.executable
sys.path[:0] = [str(LINUX), str(CORE)]

import goruntu_core as gc  # noqa: E402
import hepgo_kopru as hk  # noqa: E402

PY38_FILES = [CORE / 'kopru_core.py', CORE / 'goruntu_core.py', LINUX / 'hepgo_kopru.py']
BANNED_ATTRS = {'removeprefix', 'removesuffix', 'to_thread', 'TaskGroup', 'timeout_at', 'is_relative_to', 'with_stem', 'readlink', 'cache',
                'lcm', 'isqrt_', 'bit_count', 'ParamSpec', 'TypeAlias', 'kw_only', 'StrEnum', 'pairwise', 'batched', 'zoneinfo'}
GENERIC_BUILTINS = {'list', 'dict', 'tuple', 'set', 'frozenset', 'type'}


# ---------------- 1) Python 3.8 uyumu ----------------
def py38_tests():
    for p in PY38_FILES:
        src = p.read_text(encoding='utf-8')
        tree = ast.parse(src, filename=str(p), feature_version=(3, 8))   # 3.9+ sözdizimi (match, parantezli with, except*) burada düşer
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in BANNED_ATTRS:
                raise AssertionError(f'{p.name}:{n.lineno} Python 3.9+ API: .{n.attr}')
            if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in GENERIC_BUILTINS:
                raise AssertionError(f'{p.name}:{n.lineno} {n.value.id}[...] (3.9+ genel tür; 3.8\'de çalışma anında hata)')
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) and any(isinstance(x, ast.Constant) and x.value is None for x in (n.left, n.right)):
                raise AssertionError(f'{p.name}:{n.lineno} "X | None" (3.10+)')
            if isinstance(n, ast.keyword) and n.arg == 'strict':
                raise AssertionError(f'{p.name}:{n.lineno} zip(strict=) (3.10+)')
            if isinstance(n, ast.ImportFrom) and n.module in ('zoneinfo', 'graphlib', 'tomllib'):
                raise AssertionError(f'{p.name}: {n.module} (3.9+)')
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'run' and \
                    isinstance(n.func.value, ast.Name) and n.func.value.id == 'asyncio' and p.name != 'hepgo_kopru.py':
                pass
    py38 = shutil.which('python3.8')
    if py38:
        for p in PY38_FILES:
            subprocess.run([py38, '-m', 'py_compile', str(p)], check=True)
        print('  python3.8 ile derlendi')
    req = (LINUX / 'requirements.txt').read_text()
    assert 'websockets==13.1' in req and 'pymavlink==2.4.49' in req, req   # 3.8'i destekleyen son sürümler
    print('  Python 3.8 uyumu (ast feature_version + API taraması) geçti')


# ---------------- 2) goruntu_core ----------------
def make_fmp4(path, frames=75, gop=25, frag_us=200000):
    import av
    import numpy as np
    out = av.open(str(path), 'w', format='mp4', options={'movflags': 'frag_keyframe+empty_moov+default_base_moof', 'frag_duration': str(frag_us)})
    s = out.add_stream('libx264', rate=25)
    s.width, s.height, s.pix_fmt = 320, 240, 'yuv420p'
    s.options = {'g': str(gop), 'keyint_min': str(gop), 'bf': '0', 'preset': 'ultrafast', 'tune': 'zerolatency', 'sc_threshold': '0'}
    for i in range(frames):
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        img[:, (i * 4) % 320:(i * 4) % 320 + 20] = (255, 128, 0)
        for pkt in s.encode(av.VideoFrame.from_ndarray(img, format='rgb24')):
            out.mux(pkt)
    for pkt in s.encode():
        out.mux(pkt)
    out.close()
    return path.read_bytes()


def core_tests(tmp):
    data = make_fmp4(tmp / 'ornek.mp4')
    sp = gc.Fmp4Splitter()
    evs, i = [], 0
    rnd = random.Random(7)
    while i < len(data):   # rastgele parça boyutlarıyla (boru okuması gibi)
        n = rnd.randint(1, 9000)
        evs += sp.feed(data[i:i + n])
        i += n
    inits = [e for e in evs if e[0] == 'init']
    frags = [e for e in evs if e[0] == 'frag']
    assert len(inits) == 1 and inits[0][1][4:8] == b'ftyp', [e[0] for e in evs][:5]
    mime, codec = gc.codec_mime(inits[0][1])
    assert codec == 'h264' and mime.startswith('video/mp4; codecs="avc1.') and len(mime.split('avc1.')[1].rstrip('"')) == 6, mime
    keys = [e[2] for e in frags]
    assert keys[0] is True and sum(e[3] for e in frags) == 75, (keys, [e[3] for e in frags])
    assert keys.count(True) == 3 and keys.count(False) >= 3, keys   # 3 GOP; frag_duration ara parçalar üretir
    joined = b''.join([inits[0][1]] + [e[1] for e in frags])
    assert data.startswith(joined) and data[len(joined) + 4:len(joined) + 8] in (b'mfra', b''), data[len(joined):len(joined) + 8]   # bayt kaybı yok (sonda mfra dizini)
    # sentetik moof: trun ilk-örnek bayrağı non_sync → ara parça
    def box(t, p=b''):
        return struct.pack('>I4s', 8 + len(p), t.encode()) + p
    moof = box('moof', box('traf', box('tfhd', struct.pack('>II', 0x020000, 1)) + box('trun', struct.pack('>IIiI', 0x5, 2, 0, 0x01010000))))
    assert gc.fragment_info(moof) == (False, 2)
    moof = box('moof', box('traf', box('tfhd', struct.pack('>IIIII', 0x000020 | 0x8, 1, 40, 0x02000000, 0)[:16]) + box('trun', struct.pack('>II', 0, 3))))
    assert gc.fragment_info(moof) == (True, 3)   # tfhd varsayılan bayrağı (default_sample_duration ardından default_flags)

    tools = gc.Tools(ffmpeg='ffmpeg', ffprobe='ffprobe', encoder='libx264')
    rtsp = {'id': 1, 'kind': 'rtsp', 'url': 'rtsp://192.168.144.25:8554/main.264', 'username': 'yön@etici', 'password': 'p:ss/w#rd', 'transport': 'tcp', 'fps': 0}
    url = gc.source_url(rtsp)
    assert url == 'rtsp://y%C3%B6n%40etici:p%3Ass%2Fw%23rd@192.168.144.25:8554/main.264', url
    assert 'p%3Ass' not in gc.redact('açılamadı: ' + url) and '***' in gc.redact(url)
    pl = gc.plan(rtsp, tools, {'codec': 'h264', 'fps': 30.0})
    assert pl['copy'] is True and pl['codec'] == 'h264', pl
    cmd = gc.build_commands(rtsp, tools, pl)
    assert len(cmd) == 1 and '-c:v' in cmd[0] and cmd[0][cmd[0].index('-c:v') + 1] == 'copy' and 'frag_keyframe+empty_moov+default_base_moof' in cmd[0], cmd
    assert cmd[0][cmd[0].index('-rtsp_transport') + 1] == 'tcp' and url in cmd[0]
    pl = gc.plan({**rtsp, 'fps': 30}, tools, {'codec': 'h264', 'fps': 29.97})
    assert pl['copy'] is True, pl   # FPS kaynakla aynı (±0,6) → kopyala
    pl = gc.plan({**rtsp, 'fps': 10}, tools, {'codec': 'h264', 'fps': 30.0})
    assert pl['copy'] is False and 'FPS' in pl['reason'], pl
    cmd = gc.build_commands({**rtsp, 'fps': 10, 'bitrate_kbps': 1500}, tools, pl)
    c0 = cmd[0]
    assert 'libx264' in c0 and 'fps=10' in c0[c0.index('-vf') + 1] and '1500k' in c0 and c0[c0.index('-g') + 1] == '20', c0
    pl = gc.plan({**rtsp, 'width': 640, 'height': 360}, tools, {'codec': 'h264', 'fps': 25})
    assert not pl['copy'] and 'scale=640:360' in gc.build_commands({**rtsp, 'width': 640, 'height': 360}, tools, pl)[0][gc.build_commands({**rtsp, 'width': 640, 'height': 360}, tools, pl)[0].index('-vf') + 1]
    # H.265: uyar → kopyala (hvc1 etiketi); yeniden_kodla → H.264
    pl = gc.plan(rtsp, tools, {'codec': 'h265', 'fps': 25})
    assert pl['copy'] and pl['codec'] == 'h265' and 'hvc1' in gc.build_commands(rtsp, tools, pl)[0]
    t2 = gc.Tools(encoder='libx264', h265='yeniden_kodla')
    assert gc.plan(rtsp, t2, {'codec': 'h265', 'fps': 25})['copy'] is False
    # Jetson donanım yolu: gst-launch (rtspsrc → nvv4l2decoder → videorate → nvv4l2h264enc) | ffmpeg (fMP4 sarmalayıcı, yeniden kodlamasız)
    tj = gc.Tools(encoder='nvv4l2h264enc')
    tj.gst = '/usr/bin/gst-launch-1.0'
    pl = gc.plan({**rtsp, 'fps': 15}, tj, {'codec': 'h264', 'fps': 30})
    gst, mux = gc.build_commands({**rtsp, 'fps': 15, 'bitrate_kbps': 3000}, tj, pl)
    gs = ' '.join(gst)
    assert 'rtspsrc' in gs and 'nvv4l2decoder' in gs and 'nvv4l2h264enc' in gs and 'bitrate=3000000' in gs and 'framerate=15/1' in gs, gs
    assert 'user-pw=p:ss/w#rd' in gs and 'insert-sps-pps=true' in gs and gs.endswith('fdsink fd=1'), gs
    assert mux[mux.index('-f') + 1] == 'h264' and mux[mux.index('-framerate') + 1] == '15' and mux[mux.index('-c:v') + 1] == 'copy', mux
    rtp = {'id': 2, 'kind': 'rtp', 'rtp_port': 5600, 'codec': 'h264', 'payload_type': 97, 'fps': 0}
    sdp = gc.sdp_text(rtp)
    assert 'm=video 5600 RTP/AVP 97' in sdp and 'a=rtpmap:97 H264/90000' in sdp, sdp
    assert gc.sdp_text({**rtp, 'sdp': 'v=0\nm=video 1 RTP/AVP 96'}).startswith('v=0\nm=video 1')
    cmd = gc.build_commands(rtp, tools, gc.plan(rtp, tools, {}), '/tmp/x.sdp')
    assert '-protocol_whitelist' in cmd[0] and cmd[0][cmd[0].index('-i') + 1] == '/tmp/x.sdp', cmd
    gs = ' '.join(gc.build_commands({**rtp, 'fps': 10}, tj, gc.plan({**rtp, 'fps': 10}, tj, {}))[0])
    assert 'udpsrc port=5600' in gs and 'payload=97' in gs and 'rtph264depay' in gs, gs
    print('  goruntu_core: fMP4 ayırma, anahtar parça, kodek, plan ve komutlar geçti')
    return data


# ---------------- 3) hepgo_kopru conf / CLI ----------------
def cli_tests(tmp):
    conf = tmp / 'kopru.conf'
    shutil.copy(LINUX / 'kopru.conf.ornek', conf)
    hk.set_conf_code(str(conf), 'ornek.app/ANAHTAR_123')
    txt = conf.read_text(encoding='utf-8')
    assert 'kod = ornek.app/ANAHTAR_123' in txt and '# Jetson Nano / Xavier NX J41' in txt and txt.count('kod =') == 1, txt
    hk.set_conf_code(str(conf), 'ornek.app/YENI')
    c = hk.read_conf(str(conf))
    assert hk.conf_get(c, 'kopru', 'kod') == 'ornek.app/YENI' and oct(conf.stat().st_mode & 0o777) == '0o640'
    assert hk.link_spec(c) == {'type': 'serial', 'serial': '/dev/ttyTHS1', 'baud': 921600}
    c.set('baglanti', 'tur', 'udp')
    assert hk.link_spec(c) == {'type': 'udp', 'host': '0.0.0.0', 'port': 14550}
    c.set('baglanti', 'tur', 'yok')
    assert hk.link_spec(c) is None
    c.read_string('[kamera.7]\nad = Gimbal\ntur = rtsp\nadres = rtsp://10.0.0.5/main\nfps = 15\n')
    lc = hk.local_cameras(c)
    assert lc[0]['id'] == 7 and lc[0]['fps'] == 15 and lc[0]['kind'] == 'rtsp' and lc[0]['url'] == 'rtsp://10.0.0.5/main', lc
    empty = tmp / 'bos.conf'
    hk.set_conf_code(str(empty), 'a.b/c')   # dosya yoksa örnekten
    assert 'kod = a.b/c' in empty.read_text() and '[goruntu]' in empty.read_text()
    env = dict(os.environ, HEPGO_KOPRU_DURUM=str(tmp / 'yok.json'))
    out = subprocess.run([PY, str(LINUX / 'hepgo_kopru.py'), '--conf', str(conf), 'durum', '--json'], env=env, stdout=subprocess.PIPE, check=True, universal_newlines=True).stdout
    d = json.loads(out)
    assert d['kod'] == 'ornek.app/…' and 'YENI' not in out and d['surum'] == hk.LINUX_VERSION and 'encoder' in d['araclar'], d   # anahtar yazdırılmaz
    r = subprocess.run([PY, str(LINUX / 'hepgo_kopru.py'), '--conf', str(tmp / 'kodsuz.conf'), 'calistir'], env=env, stdout=subprocess.PIPE, universal_newlines=True, timeout=30)
    assert r.returncode == hk.EXIT_FATAL and 'eslestir' in r.stdout, (r.returncode, r.stdout)
    print('  hepgo_kopru conf / durum / kodsuz çıkış (3) geçti')


# ---------------- 4) paket ----------------
def package_tests(tmp):
    out = tmp / 'paket'
    r = subprocess.run([PY, str(ROOT / 'tools' / 'kopru_linux_paket.py'), '--cikti', str(out), '--yayinla', str(tmp / 'releases')],
                       stdout=subprocess.PIPE, check=True, universal_newlines=True)
    tgz = next(out.glob('HepgoDronKoprusu-Linux-Jetson-*.tar.gz'))
    ver = hk.LINUX_VERSION
    assert tgz.name == f'HepgoDronKoprusu-Linux-Jetson-{ver}.tar.gz', tgz
    with tarfile.open(tgz) as tf:
        names = sorted(m.name.split('/', 1)[1] for m in tf.getmembers() if '/' in m.name)
        modes = {m.name.split('/', 1)[1]: m.mode for m in tf.getmembers() if '/' in m.name}
        tf.extractall(tmp / 'acik')
    assert names == sorted(['install.sh', 'uninstall.sh', 'hepgo-kopru.service', 'kopru.conf.ornek', 'requirements.txt', 'hepgo_kopru.py',
                            'kopru_core.py', 'goruntu_core.py', 'SURUM', 'KURULUM.txt']), names
    assert modes['install.sh'] == 0o755 and modes['kopru_core.py'] == 0o644
    d = tmp / 'acik' / f'HepgoDronKoprusu-Linux-Jetson-{ver}'
    assert (d / 'kopru_core.py').read_bytes() == (CORE / 'kopru_core.py').read_bytes()   # paylaşılan çekirdek, aynen
    for sh in ('install.sh', 'uninstall.sh'):
        subprocess.run(['bash', '-n', str(d / sh)], check=True)
    v = subprocess.run([PY, str(d / 'hepgo_kopru.py'), '--surum'], stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
    assert ver in v, v
    assert (tmp / 'releases' / ver / tgz.name).is_file() and (tmp / 'releases' / ver / (tgz.name + '.sha256')).is_file()
    r2 = subprocess.run([PY, str(ROOT / 'tools' / 'kopru_linux_paket.py'), '--cikti', str(tmp / 'paket2')], stdout=subprocess.PIPE, check=True, universal_newlines=True)
    assert (tmp / 'paket2' / tgz.name).read_bytes() == tgz.read_bytes(), 'paket tekrarlanabilir değil'
    unit = (LINUX / 'hepgo-kopru.service').read_text()
    assert 'RestartPreventExitStatus=3' in unit and 'SupplementaryGroups=dialout video' in unit and 'calistir' in unit
    print(f'  paket {tgz.name} ({tgz.stat().st_size} bayt) geçti')
    return tmp / 'releases'


# ---------------- 5) uçtan uca ----------------
FAKE_FFMPEG = r'''#!{py}
# Sahte ffmpeg/ffprobe (test): fMP4 örnek dosyasını gerçek zamanlı akıtır; mjpeg istenirse JPEG; ffprobe ise JSON.
import json, struct, sys, time
args = sys.argv[1:]
if sys.argv[0].endswith('ffprobe'):
    print(json.dumps({{'streams': [{{'codec_name': 'h264', 'width': 320, 'height': 240, 'avg_frame_rate': '25/1'}}]}})); sys.exit(0)
if 'mjpeg' in args:
    if '-i' in args and args[args.index('-i') + 1] == 'pipe:0':
        sys.stdin.buffer.read()
    sys.stdout.buffer.write(b'\xff\xd8\xff\xe0' + b'J' * 64 + b'\xff\xd9'); sys.exit(0)
open({log!r}, 'a').write(' '.join(args) + '\n')
data = open({mp4!r}, 'rb').read()
boxes, i = [], 0
while i < len(data):
    n = struct.unpack('>I', data[i:i + 4])[0]; boxes.append(data[i:i + n]); i += n
out = sys.stdout.buffer
out.write(boxes[0] + boxes[1]); out.flush()
frags = [boxes[k] + boxes[k + 1] for k in range(2, len(boxes) - 1, 2)]
while True:
    for f in frags:
        out.write(f); out.flush(); time.sleep(0.2)
'''


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def e2e_tests(tmp, releases):
    import httpx
    from websockets.sync.client import connect
    fake = tmp / 'sahte'
    fake.mkdir()
    for nm in ('ffmpeg', 'ffprobe'):
        p = fake / nm
        p.write_text(FAKE_FFMPEG.format(py=PY, mp4=str(tmp / 'ornek.mp4'), log=str(tmp / 'ffmpeg.log')))
        p.chmod(0o755)
    port = free_port()
    data = tempfile.mkdtemp()
    env = dict(os.environ, CAYMAZ_DATA_DIR=data, CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
               CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_DRONE_PKG='1', HEPGO_SITL='0', HEPGO_KOPRU_DIR=str(releases))
    srv = subprocess.Popen([PY, '-m', 'uvicorn', 'app.main:app', '--port', str(port), '--log-level', 'warning'], cwd=str(ROOT), env=env)
    kopru = None
    try:
        base = f'http://127.0.0.1:{port}'
        for _ in range(120):
            try:
                if httpx.get(base + '/api/meta', timeout=1).status_code < 500:
                    break
            except Exception:   # noqa: BLE001
                time.sleep(0.5)
        c = httpx.Client(base_url=base, timeout=30)
        assert c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}).status_code == 200
        app = c.get('/api/drone/bridge-app').json()
        lf = [f for f in app['files'] if f['os'] == 'linux-arm64']
        assert lf and lf[0]['name'].startswith('HepgoDronKoprusu-Linux-Jetson-') and lf[0]['version'] == hk.LINUX_VERSION, app
        assert c.get(lf[0]['url']).content[:2] == b'\x1f\x8b'
        b = c.post('/api/drone/bridges', json={'name': 'Jetson Nano', 'platform': 'linux'}).json()
        cam = c.post('/api/drone/cameras', json={'name': 'Siyi A8', 'bridge_id': b['id'], 'kind': 'rtsp', 'url': 'rtsp://192.168.144.25:8554/main.264',
                                                 'username': 'admin', 'password': 'gizli-123', 'fps': 0}).json()
        conf = tmp / 'e2e.conf'
        conf.write_text(f"[kopru]\nkod = {b['code']}\n[baglanti]\ntur = yok\n[goruntu]\netkin = evet\nffmpeg = {fake / 'ffmpeg'}\nffprobe = {fake / 'ffprobe'}\n",
                        encoding='utf-8')
        durum = tmp / 'durum.json'
        kenv = dict(os.environ, HEPGO_KOPRU_URL=f'ws://127.0.0.1:{port}/ws/drone/bridge', HEPGO_GORUNTU_URL=f'ws://127.0.0.1:{port}/ws/drone/video',
                    HEPGO_KOPRU_DURUM=str(durum))
        kopru = subprocess.Popen([PY, str(LINUX / 'hepgo_kopru.py'), '--conf', str(conf), 'calistir'], env=kenv, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, universal_newlines=True)
        end = time.time() + 30
        row = {}
        while time.time() < end:
            row = next(x for x in c.get('/api/drone/bridges').json() if x['id'] == b['id'])
            if row['online'] and row['video_online']:
                break
            time.sleep(0.3)
        assert row['online'] and row['video_online'] and 'video' in row['caps'] and row['live']['bridge_ver'] == hk.LINUX_VERSION, row
        cookie = c.cookies.get('caymaz_session')
        with connect(f'ws://127.0.0.1:{port}/ws/drone/video/watch?camera_id={cam["id"]}', additional_headers={'Cookie': f'caymaz_session={cookie}'},
                     max_size=None) as w:
            hello = json.loads(w.recv(timeout=10))
            assert hello['t'] == 'hello' and hello['bridge_online'] is True, hello
            bins, texts = [], []
            end = time.time() + 30
            while time.time() < end and len([x for x in bins if x[0] == 2]) < 2:
                m = w.recv(timeout=15)
                if isinstance(m, bytes):
                    bins.append(m)
                else:
                    texts.append(json.loads(m))
            assert bins and bins[0][0] == 1 and bins[0][5:9] == b'ftyp', [x[:1] for x in bins][:5]
            assert [x[0] for x in bins].count(2) >= 2 and 3 in [x[0] for x in bins], [x[0] for x in bins]
            assert any(t.get('t') == 'init' and 'avc1.' in (t.get('mime') or '') for t in texts), texts
            st = c.get(f'/api/drone/cameras/{cam["id"]}').json()
            assert st['status'] == 'canli', st
            r = c.get(f'/api/drone/cameras/{cam["id"]}/snapshot.jpg')
            assert r.status_code == 200 and r.content.startswith(b'\xff\xd8'), (r.status_code, r.text[:200])
        log = (tmp / 'ffmpeg.log').read_text()
        assert '-c:v copy' in log and 'rtsp://admin:gizli-123@192.168.144.25:8554/main.264' in log, log   # FPS kaynak → yeniden kodlamasız
        time.sleep(5.5)
        ds = json.loads(durum.read_text(encoding='utf-8'))
        assert ds['server']['state'] == 'connected' and ds['video']['server'] == 'bagli', ds
        assert str(cam['id']) in ds['video']['cameras'], ds['video']
        print('  uçtan uca: telemetri + görüntü köprüsü, video_cfg, izleyici, anlık görüntü, durum dosyası geçti')
    finally:
        out = ''
        if kopru:
            kopru.terminate()
            try:
                out = kopru.communicate(timeout=10)[0]
            except subprocess.TimeoutExpired:
                kopru.kill()
                out = kopru.communicate()[0]
            assert 'gizli-123' not in out, 'parola günlükte göründü'
            assert kopru.returncode == 0, (kopru.returncode, out[-2000:])
        srv.terminate()
        srv.wait(10)


def main():
    tmp = Path(tempfile.mkdtemp())
    py38_tests()
    core_tests(tmp)
    cli_tests(tmp)
    releases = package_tests(tmp)
    e2e_tests(tmp, releases)
    print('Linux / Jetson köprüsü testleri geçti.')


if __name__ == '__main__':
    main()
