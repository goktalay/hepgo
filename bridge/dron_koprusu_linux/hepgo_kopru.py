#!/usr/bin/env python3
"""Hepgo Dron Köprüsü — Linux / NVIDIA Jetson başsız servisi (telemetri + görüntü köprüsü).

Telemetri çekirdeği bridge/dron_koprusu/kopru_core.py, görüntü çekirdeği goruntu_core.py ile PAYLAŞILIR (kopyalanmaz; paket üretici
tools/kopru_linux_paket.py ikisini pakete koyar). Servis: systemd hepgo-kopru.service → `hepgo-kopru calistir`; günlük journald'a.
Yapılandırma: /etc/hepgo-kopru/kopru.conf (INI; kopru.conf.ornek). Kamera ayarları SİTEDEN gelir (Dron Yönetimi › Kameralar);
conf'taki [kamera.N] bölümleri yalnız yedektir (sunucu kamera listesi göndermezse) ve `kamera-dene` içindir.

Komutlar:
  hepgo-kopru eslestir <köprü kodu>            köprü kodunu (<alan>/<anahtar>) doğrular, conf'a yazar, servisi yeniden başlatır
  hepgo-kopru eslestir --alan <alan> <6 hane>  6 haneli eşleştirme kodu ile kalıcı anahtar alır
  hepgo-kopru durum [--json]                   servis + sunucu + dron bağlantısı + kameralar + araçlar (ffmpeg / GStreamer / kodlayıcı)
  hepgo-kopru log [-f] [-n 200]                journalctl -u hepgo-kopru
  hepgo-kopru kamera-dene [--kamera N] [--sure 10] [--cikti dosya.mp4]   yerel conf kamerasını dener (sunucuya göndermez)
  hepgo-kopru mp-ac <ip:port>                  YEREL Mission Planner UDP'yi açar ([baglanti] mp_udp; 0.0.0.0:14550 = dinle, MP 'UDPCl'
                                               ile bu cihaza bağlanır · 192.168.1.50:14550 = o bilgisayardaki MP'ye gönder) + servis yeniden başlar
  hepgo-kopru mp-kapat                         yerel Mission Planner UDP'yi kapatır (HEPGO üzerinden aktarım ayrıca siteden açılır)
  hepgo-kopru calistir                         servis (ön planda; systemd çağırır)
Python 3.8+ (Jetson Nano JetPack 4.6 / Ubuntu 18.04: install.sh python3.8 kurar).
"""
import argparse
import asyncio
import configparser
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / 'dron_koprusu'):   # kurulu pakette aynı klasör; depoda kardeş klasör (kopru_core paylaşılır)
    if (_p / 'kopru_core.py').is_file() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import kopru_core  # noqa: E402
import goruntu_core  # noqa: E402

LINUX_VERSION = '1.1.6'   # Linux/Jetson paketi sürümü (paket adı ve bridge_ver)
CONF = os.environ.get('HEPGO_KOPRU_CONF') or '/etc/hepgo-kopru/kopru.conf'
DURUM = os.environ.get('HEPGO_KOPRU_DURUM') or '/run/hepgo-kopru/durum.json'
SERVICE = 'hepgo-kopru'
EXIT_FATAL = 3            # köprü kodu geçersiz: systemd RestartPreventExitStatus=3 (eşleştirme sonrası `eslestir` yeniden başlatır)
LINK_RETRY_S = 5
EVET = ('1', 'evet', 'e', 'true', 'yes', 'on', 'acik', 'açık')


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ---------------- yapılandırma ----------------
def read_conf(path=CONF):
    c = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(';', '#'))
    c.read(path, encoding='utf-8')
    return c


def conf_get(c, sec, key, default=''):
    try:
        v = c.get(sec, key, fallback=default)
    except (configparser.Error, ValueError):
        v = default
    return (v or '').strip() if isinstance(v, str) else v


def link_spec(c):
    """[baglanti] → kopru_core link spec ya da None (tur = yok / boş: bağlantı sunucudan link_open ile açılır)."""
    t = conf_get(c, 'baglanti', 'tur', 'serial').lower()
    sysid = conf_get(c, 'baglanti', 'sysid')
    if t in ('', 'yok', 'none'):
        return None
    if t == 'serial':
        spec = {'type': 'serial', 'serial': conf_get(c, 'baglanti', 'cihaz', '/dev/ttyTHS1'), 'baud': int(conf_get(c, 'baglanti', 'baud', '921600') or 921600)}
    elif t in ('udp', 'tcp'):
        spec = {'type': t, 'host': conf_get(c, 'baglanti', 'adres', '0.0.0.0' if t == 'udp' else '127.0.0.1'),
                'port': int(conf_get(c, 'baglanti', 'port', '14550' if t == 'udp' else '5760') or 0)}
    else:
        raise ValueError('[baglanti] tur serial / udp / tcp / yok olmalı')
    if sysid:
        spec['sysid'] = int(sysid)
    return spec


def local_cameras(c):
    """[kamera.<id>] bölümleri → goruntu_core kamera yapılandırması (YEDEK: sunucu 'cameras' göndermezse; kamera-dene)."""
    out = []
    for sec in c.sections():
        if not sec.lower().startswith('kamera.'):
            continue
        try:
            cid = int(sec.split('.', 1)[1])
        except ValueError:
            continue
        g = lambda k, d='': conf_get(c, sec, k, d)   # noqa: E731
        out.append({'id': cid, 'name': g('ad', sec), 'kind': g('tur', 'rtsp').lower(), 'url': g('adres'), 'username': g('kullanici'),
                    'password': g('parola'), 'transport': g('tasima', 'tcp').lower(), 'rtp_port': int(g('rtp_port', '5600') or 5600),
                    'codec': g('kodek', 'h264').lower(), 'payload_type': int(g('yuk_turu', '96') or 96), 'sdp': '', 'fps': int(g('fps', '0') or 0),
                    'width': int(g('genislik')) if g('genislik') else None, 'height': int(g('yukseklik')) if g('yukseklik') else None,
                    'bitrate_kbps': int(g('bitrate_kbps')) if g('bitrate_kbps') else None})
    return out


def tools_from(c):
    return goruntu_core.Tools(ffmpeg=conf_get(c, 'goruntu', 'ffmpeg', 'ffmpeg') or 'ffmpeg', ffprobe=conf_get(c, 'goruntu', 'ffprobe', 'ffprobe') or 'ffprobe',
                              encoder=conf_get(c, 'goruntu', 'kodlayici', 'otomatik'), h265=conf_get(c, 'goruntu', 'h265', 'uyar'))


def set_conf_code(path, code):
    """conf'taki [kopru] kod satırını değiştirir (diğer satırlar/yorumlar korunur); dosya yoksa örnekten oluşturulur. İzin 0640."""
    set_conf_value(path, 'kopru', 'kod', code)


def set_conf_value(path, section, key, value):
    """conf'ta [section] key satırını değiştirir/ekler (diğer satırlar/yorumlar korunur); dosya yoksa örnekten oluşturulur. İzin 0640."""
    p = Path(path)
    if p.is_file():
        lines = p.read_text(encoding='utf-8').splitlines()
    else:
        ornek = HERE / 'kopru.conf.ornek'
        lines = ornek.read_text(encoding='utf-8').splitlines() if ornek.is_file() else ['[kopru]', 'kod =']
    satir = '{} = {}'.format(key, value)
    out, sec, done = [], None, False
    for ln in lines:
        s = ln.strip()
        if s.startswith('[') and s.endswith(']'):
            if sec == section and not done:
                while out and not out[-1].strip():   # bölüm sonundaki boş satırların önüne ekle
                    out.pop()
                out += [satir, '']
                done = True
            sec = s[1:-1].strip().lower()
        elif sec == section and not done and '=' in s and not s.startswith(('#', ';')) and s.split('=', 1)[0].strip().lower() == key:
            out.append(satir)
            done = True
            continue
        out.append(ln)
    if not done:
        if sec != section:
            out += ['', '[{}]'.format(section)]
        out.append(satir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text('\n'.join(out) + '\n', encoding='utf-8')
    os.chmod(str(tmp), 0o640)
    try:
        st = p.stat()
        os.chown(str(tmp), st.st_uid, st.st_gid)
    except (OSError, AttributeError):
        pass
    os.replace(str(tmp), str(p))


# ---------------- servis (calistir) ----------------
class Daemon:
    def __init__(self, conf_path):
        self.conf_path = conf_path
        self.c = read_conf(conf_path)
        self.code = conf_get(self.c, 'kopru', 'kod')
        self.status = {'pid': os.getpid(), 'version': LINUX_VERSION, 'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'host': socket.gethostname(),
                       'server': {'state': 'bekliyor', 'detail': ''}, 'link': {'state': 'kapali', 'detail': ''}, 'stats': {}}
        self.bridge = None
        self.video = None
        self.fatal = None
        self.link_conf = None
        self.manual_close = False

    def ui(self, ev, *a):
        if ev == 'stats':
            self.status['stats'] = a[0] if a else {}
            return
        log(ev, *[goruntu_core.redact(x) for x in a])
        if ev == 'server':
            self.status['server'] = {'state': a[0], 'detail': a[1] if len(a) > 1 else ''}
            if a[0] == 'fatal':
                self.fatal = a[1] if len(a) > 1 else 'fatal'
        elif ev == 'link':
            self.status['link'] = {'state': a[0], 'detail': a[1] if len(a) > 1 else ''}
            if a[0] == 'closed':
                self.manual_close = True
            elif a[0] == 'open':
                self.manual_close = False
            elif a[0] in ('lost', 'error') and self.link_conf and not self.manual_close:
                asyncio.get_event_loop().call_later(LINK_RETRY_S, self._reopen)

    def _reopen(self):
        """Otomatik yeniden bağlanma: seri port çıkarıldı / dron kapandı → conf bağlantısı LINK_RETRY_S sn'de bir yeniden denenir."""
        b = self.bridge
        if b is None or b.stopped or self.manual_close or (b.mav is not None and b.mav.running):
            return
        spec = dict(b.link_spec or self.link_conf)
        log('link', 'yeniden deneniyor', kopru_core.link_text(spec))
        asyncio.ensure_future(self._try_open(spec))

    async def _try_open(self, spec):
        try:
            await self.bridge.open_link(spec)
        except Exception as e:   # noqa: BLE001
            self.ui('link', 'error', str(e)[:200])

    async def _status_writer(self):
        p = Path(DURUM)
        while True:
            if self.video is not None:
                self.status['video'] = self.video.status()
            self.status['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix('.tmp')
                tmp.write_text(json.dumps(self.status, ensure_ascii=False, indent=1), encoding='utf-8')
                os.replace(str(tmp), str(p))
            except OSError:
                pass
            await asyncio.sleep(5)

    async def run(self):
        if not self.code:
            log('server', 'fatal', 'Köprü kodu yok: sudo hepgo-kopru eslestir <köprü kodu>')
            return EXIT_FATAL
        try:
            domain, key = kopru_core.parse_code(self.code)
            self.link_conf = link_spec(self.c)
        except ValueError as e:
            log('server', 'fatal', str(e))
            return EXIT_FATAL
        video_on = conf_get(self.c, 'goruntu', 'etkin', 'evet').lower() in EVET
        caps = list(kopru_core.CAPS) + (['video'] if video_on else [])
        try:
            mp_udp = kopru_core.parse_mp_udp(conf_get(self.c, 'baglanti', 'mp_udp'))
        except ValueError as e:
            log('mp', 'uyarı', '[baglanti] mp_udp yok sayıldı: {}'.format(e))
            mp_udp = None
        self.bridge = kopru_core.Bridge(self.code, ui=self.ui, link_spec=self.link_conf, caps=caps, version=LINUX_VERSION, mp_udp=mp_udp)
        loop = asyncio.get_event_loop()
        tasks = [asyncio.ensure_future(self.bridge.run()), asyncio.ensure_future(self._status_writer())]
        if video_on:
            tools = tools_from(self.c)
            log('video', 'araçlar', json.dumps(tools.info(), ensure_ascii=False))
            self.video = goruntu_core.VideoBridge(domain, key, tools, ui=self.ui, local_cameras=local_cameras(self.c),
                                                  always=conf_get(self.c, 'goruntu', 'surekli', 'hayir').lower() in EVET, version=LINUX_VERSION)
            tasks.append(asyncio.ensure_future(self.video.run()))
        stop = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):
                pass
        if self.link_conf and self.link_conf.get('type') == 'serial' and not os.path.exists(self.link_conf['serial']):
            log('link', 'uyarı', '{} yok — bağlanınca otomatik açılacak'.format(self.link_conf['serial']))
        # telemetri görevi biterse (kod geçersiz) servis çıkar
        waiter = asyncio.ensure_future(stop.wait())
        done, _ = await asyncio.wait([waiter, tasks[0]], return_when=asyncio.FIRST_COMPLETED)
        self.bridge.stop()
        if self.video:
            self.video.stop()
        await asyncio.sleep(0.5)
        for t in tasks + [waiter]:
            t.cancel()
        try:
            Path(DURUM).unlink()
        except OSError:
            pass
        if self.fatal:
            log('server', 'fatal', self.fatal, '— yeni kod: sudo hepgo-kopru eslestir <köprü kodu>')
            return EXIT_FATAL
        return 0


def cmd_calistir(args):
    rc = asyncio.run(Daemon(args.conf).run())
    sys.exit(rc)


# ---------------- eslestir ----------------
async def _verify(domain, key=None, pair=None, timeout=15):
    """Telemetri ucuna bağlanıp kodu doğrular → (anahtar, köprü adı). Hata: RuntimeError."""
    import websockets
    url = kopru_core.server_url(domain)
    async with websockets.connect(url, open_timeout=timeout, close_timeout=3, ping_interval=None) as ws:
        first = {'v': 1, 't': 'pair', 'code': pair} if pair else {'v': 1, 't': 'auth', 'key': key}
        first.update(host=socket.gethostname()[:120], platform='linux', bridge_ver=LINUX_VERSION, caps=[])
        await ws.send(json.dumps(first))
        try:
            r = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        except Exception:   # noqa: BLE001
            r = {}
        if r.get('t') != 'auth_ok':
            raise RuntimeError('Kod geçersiz ya da süresi dolmuş (HEPGO › Dron Köprüleri › Kodu yenile / Eşleştir)')
        return r.get('key') or key, r.get('name') or ''


def cmd_eslestir(args):
    raw = args.kod.strip()
    try:
        if args.alan:
            domain = kopru_core.parse_code(args.alan.strip().rstrip('/') + '/x')[0]
            key, name = asyncio.run(_verify(domain, pair=raw.upper()))
        else:
            domain, key = kopru_core.parse_code(raw)
            key, name = (key, '') if args.dogrulama_yok else asyncio.run(_verify(domain, key=key))
    except ValueError as e:
        sys.exit('Hata: {} (örnek: sudo hepgo-kopru eslestir caymaz.app/AbC…  ya da  --alan caymaz.app 7KX2QD)'.format(e))
    except Exception as e:   # noqa: BLE001
        sys.exit('Sunucuya bağlanılamadı / kod reddedildi: {}'.format(e))
    code = '{}/{}'.format(domain, key)
    try:
        set_conf_code(args.conf, code)
    except PermissionError:
        sys.exit('Yapılandırma yazılamadı ({}): sudo ile çalıştırın'.format(args.conf))
    print('Köprü eşleşti{}: {}/… → {}'.format(' (' + name + ')' if name else '', domain, args.conf))
    if not args.yeniden_baslatma_yok and _systemctl('is-enabled') is not None:
        r = subprocess.run(['systemctl', 'restart', SERVICE])
        print('Servis yeniden başlatıldı.' if r.returncode == 0 else 'Servis yeniden başlatılamadı: sudo systemctl restart ' + SERVICE)


# ---------------- durum / log ----------------
def _systemctl(what):
    try:
        r = subprocess.run(['systemctl', what, SERVICE], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=10)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def cmd_durum(args):
    st = {}
    try:
        st = json.loads(Path(DURUM).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    c = read_conf(args.conf)
    code = conf_get(c, 'kopru', 'kod')
    out = {'servis': _systemctl('is-active') or 'bilinmiyor', 'surum': LINUX_VERSION, 'conf': args.conf,
           'kod': (code.split('/', 1)[0] + '/…') if code else None, 'canli': st}
    try:
        spec = link_spec(c)
        out['baglanti_ayari'] = kopru_core.link_text(spec) if spec else 'yok (sunucudan link_open)'
    except ValueError as e:
        out['baglanti_ayari'] = 'HATALI: {}'.format(e)
    try:
        mp = kopru_core.parse_mp_udp(conf_get(c, 'baglanti', 'mp_udp'))
        out['mp_udp'] = '{}:{}:{}'.format(*mp) if mp else 'kapalı'
    except ValueError as e:
        out['mp_udp'] = 'HATALI: {}'.format(e)
    out['araclar'] = tools_from(c).info()
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print('Hepgo Dron Köprüsü (Linux) {}'.format(LINUX_VERSION))
    print('  servis      : {}'.format(out['servis']))
    print('  köprü kodu  : {}'.format(out['kod'] or 'YOK — sudo hepgo-kopru eslestir <kod>'))
    print('  dron ayarı  : {}'.format(out['baglanti_ayari']))
    print('  yerel MP    : {}'.format(out['mp_udp']))
    if st:
        print('  sunucu      : {} {}'.format(st.get('server', {}).get('state'), st.get('server', {}).get('detail') or ''))
        print('  dron bağl.  : {} {}'.format(st.get('link', {}).get('state'), st.get('link', {}).get('detail') or ''))
        s = st.get('stats') or {}
        if s:
            print('  telemetri   : gönderilen {} · alınan {} · sysid {}'.format(s.get('tx'), s.get('rx'), s.get('drone')))
        mp = s.get('mp') or {}
        if mp:
            loc = mp.get('local') or {}
            print('  MP (HEPGO)  : drona yazılan {} paket · atılan {} · bağlantısız {}'.format(mp.get('raw_up'), mp.get('raw_drop'), mp.get('raw_nolink')))
            if loc:
                print('  MP (yerel)  : {} · eş {} · MP→dron {} · dron→MP {}'.format(loc.get('listen') or loc.get('target'), loc.get('peer') or 'bekleniyor',
                                                                                 loc.get('up'), loc.get('down')))
        v = st.get('video')
        if v:
            print('  görüntü     : {} {}'.format(v.get('server'), v.get('detail') or ''))
            for cid, cs in (v.get('cameras') or {}).items():
                stt = cs.get('stat') or {}
                print('    kamera #{} {}: {} {}{}'.format(cid, cs.get('name') or '', cs.get('state'), cs.get('detail') or '',
                                                     ' · {} kbit/sn {} fps'.format(stt.get('kbps'), stt.get('fps')) if stt else ''))
    else:
        print('  (canlı durum yok: servis çalışmıyor olabilir — sudo systemctl status {})'.format(SERVICE))
    a = out['araclar']
    print('  araçlar     : ffmpeg {} · ffprobe {} · GStreamer {} · kodlayıcı {}'.format(*('var' if a[k] else 'YOK' for k in ('ffmpeg', 'ffprobe', 'gstreamer')), a['encoder']))


def cmd_log(args):
    cmd = ['journalctl', '-u', SERVICE, '-n', str(args.n), '--no-pager'] + (['-f'] if args.f else [])
    try:
        os.execvp(cmd[0], cmd)
    except OSError as e:
        sys.exit('journalctl çalıştırılamadı: {}'.format(e))


# ---------------- yerel Mission Planner ----------------
def _yeniden_baslat(args):
    if not getattr(args, 'yeniden_baslatma_yok', False) and _systemctl('is-enabled') is not None:
        r = subprocess.run(['systemctl', 'restart', SERVICE])
        print('Servis yeniden başlatıldı.' if r.returncode == 0 else 'Servis yeniden başlatılamadı: sudo systemctl restart ' + SERVICE)


def cmd_mp_ac(args):
    try:
        mp = kopru_core.parse_mp_udp(args.adres)
    except ValueError as e:
        sys.exit(str(e))
    if not mp:
        sys.exit('Adres gerekli (ör. 0.0.0.0:14550 ya da 192.168.1.50:14550)')
    c = read_conf(args.conf)
    try:
        spec = link_spec(c)
    except ValueError:
        spec = None
    if mp[0] == 'dinle' and spec and spec.get('type') == 'udp' and int(spec.get('port') or 0) == mp[2]:
        sys.exit('Port {} dron bağlantısında ([baglanti] port) kullanılıyor; başka port seçin (ör. 0.0.0.0:14551)'.format(mp[2]))
    try:
        set_conf_value(args.conf, 'baglanti', 'mp_udp', '{}:{}'.format(mp[1], mp[2]) if (mp[0] == 'dinle') == (mp[1] in ('0.0.0.0', '::'))
                       else '{}:{}:{}'.format(*mp))
    except OSError:
        sys.exit('Yapılandırma yazılamadı ({}): sudo ile çalıştırın'.format(args.conf))
    if mp[0] == 'dinle':
        print('Yerel Mission Planner: {}:{} dinleniyor → MP › UDPCl › <bu cihazın IP adresi>:{}'.format(mp[1], mp[2], mp[2]))
    else:
        print('Yerel Mission Planner: telemetri {}:{} adresine gönderilecek → o bilgisayarda MP › UDP › port {}'.format(mp[1], mp[2], mp[2]))
    _yeniden_baslat(args)


def cmd_mp_kapat(args):
    try:
        set_conf_value(args.conf, 'baglanti', 'mp_udp', '')
    except OSError:
        sys.exit('Yapılandırma yazılamadı ({}): sudo ile çalıştırın'.format(args.conf))
    print('Yerel Mission Planner UDP kapatıldı.')
    _yeniden_baslat(args)


# ---------------- kamera-dene ----------------
def cmd_kamera_dene(args):
    c = read_conf(args.conf)
    cams = local_cameras(c)
    if args.adres:
        cams = [{'id': 1, 'name': 'komut satırı', 'kind': 'test' if args.adres == 'test' else 'rtsp', 'url': args.adres, 'transport': args.tasima,
                 'fps': args.fps, 'width': None, 'height': None, 'bitrate_kbps': None, 'codec': 'h264'}]
    if args.kamera is not None:
        cams = [x for x in cams if x['id'] == args.kamera]
    if not cams:
        sys.exit('Denenecek kamera yok: conf\'a [kamera.<id>] ekleyin ya da --adres rtsp://… verin (asıl kamera ayarları siteden gelir)')
    cam = cams[0]
    tools = tools_from(c)
    print('Araçlar:', json.dumps(tools.info(), ensure_ascii=False))
    out = open(args.cikti, 'wb') if args.cikti else None
    seen = {'init': 0, 'key': 0, 'delta': 0, 'bytes': 0, 'mime': None}

    def emit(typ, payload):
        seen['bytes'] += len(payload)
        if typ == goruntu_core.T_INIT:
            seen['init'] += 1
            seen['mime'] = goruntu_core.codec_mime(payload)[0]
        elif typ == goruntu_core.T_KEY:
            seen['key'] += 1
        else:
            seen['delta'] += 1
        if out:
            out.write(payload)

    def state(cid, s, d, extra):
        if s:
            print('  durum:', s, goruntu_core.redact(d or ''))
        elif extra.get('stat'):
            print('  ölçüm:', json.dumps(extra['stat'], ensure_ascii=False))

    async def run():
        w = goruntu_core.CameraWorker(cam, tools, emit, state, lambda s: print(' ', goruntu_core.redact(s)))
        w.start()
        await asyncio.sleep(args.sure)
        await w.stop()
    print('Kamera #{} {} deneniyor ({} sn)…'.format(cam['id'], cam.get('name'), args.sure))
    asyncio.run(run())
    if out:
        out.close()
    print('Sonuç: init {init} · anahtar parça {key} · ara parça {delta} · {bytes} bayt · {mime}'.format(**seen))
    sys.exit(0 if seen['init'] and seen['key'] else 1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='hepgo-kopru', description='Hepgo Dron Köprüsü — Linux / Jetson (telemetri + görüntü)')
    ap.add_argument('--conf', default=CONF, help='yapılandırma dosyası (varsayılan {})'.format(CONF))
    ap.add_argument('--surum', action='version', version='hepgo-kopru {} (çekirdek {})'.format(LINUX_VERSION, kopru_core.VERSION))
    sub = ap.add_subparsers(dest='komut')
    sub.add_parser('calistir', help='servis (ön planda)').set_defaults(fn=cmd_calistir)
    p = sub.add_parser('eslestir', help='köprü kodunu kaydet (doğrular, servisi yeniden başlatır)')
    p.add_argument('kod', help='köprü kodu <alan>/<anahtar> ya da --alan ile 6 haneli eşleştirme kodu')
    p.add_argument('--alan', help='6 haneli eşleştirme kodu için sunucu alan adı (ör. caymaz.app)')
    p.add_argument('--dogrulama-yok', action='store_true', help='sunucuya bağlanmadan yaz (çevrim dışı kurulum)')
    p.add_argument('--yeniden-baslatma-yok', action='store_true')
    p.set_defaults(fn=cmd_eslestir)
    p = sub.add_parser('durum', help='servis / bağlantı / kamera durumu')
    p.add_argument('--json', action='store_true')
    p.set_defaults(fn=cmd_durum)
    p = sub.add_parser('log', help='servis günlüğü (journald)')
    p.add_argument('-f', action='store_true', help='izle')
    p.add_argument('-n', type=int, default=200)
    p.set_defaults(fn=cmd_log)
    p = sub.add_parser('kamera-dene', help='yerel conf kamerasını dener (sunucuya göndermez)')
    p.add_argument('--kamera', type=int)
    p.add_argument('--adres', help='rtsp://… ya da "test" (ffmpeg test görüntüsü)')
    p.add_argument('--tasima', default='tcp', choices=('tcp', 'udp'))
    p.add_argument('--fps', type=int, default=0)
    p.add_argument('--sure', type=float, default=10)
    p.add_argument('--cikti', help='alınan fMP4 akışını dosyaya yaz')
    p.set_defaults(fn=cmd_kamera_dene)
    p = sub.add_parser('mp-ac', help='yerel Mission Planner UDP (0.0.0.0:14550 dinle · <ip>:<port> gönder)')
    p.add_argument('adres', help='0.0.0.0:14550 (MP UDPCl ile bağlanır) ya da 192.168.1.50:14550 (o bilgisayardaki MP UDP dinler)')
    p.add_argument('--yeniden-baslatma-yok', action='store_true')
    p.set_defaults(fn=cmd_mp_ac)
    p = sub.add_parser('mp-kapat', help='yerel Mission Planner UDP\'yi kapat')
    p.add_argument('--yeniden-baslatma-yok', action='store_true')
    p.set_defaults(fn=cmd_mp_kapat)
    args = ap.parse_args(argv)
    if not getattr(args, 'fn', None):
        ap.print_help()
        return 2
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
