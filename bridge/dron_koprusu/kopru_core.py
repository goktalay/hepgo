"""Hepgo Dron Köprüsü — çekirdek (arayüzden bağımsız).

HEPGO Dron Yönetimi köprü protokolü v1 + v1.1 (docs/dron-kopru-protokolu.md):
- Sunucuya DIŞA DOĞRU WebSocket: wss://<alan-adı>/ws/drone/bridge, ilk çerçeve {v:1,t:'auth',key,host,platform,bridge_ver,caps}.
- Dronun yerel bağlantısından (seri / UDP / TCP; pymavlink) gelen ham MAVLink çerçeveleri ikili WebSocket çerçeveleri olarak iletilir.
- Sunucudan gelen {t:'cmd'} komutları drona MAVLink komutu olarak uygulanır, sonuç {t:'res'} ile döner.
- Bağlantı (link) sunucudan link_open/link_close ile ya da arayüzden elle açılır; durum {t:'link'} çerçevesiyle bildirilir.
- Uçuş sonrası .bin logu log_begin / ikili parçalar / log_end ile gönderilir.
- v1.4 (cap 'mp_relay'): sunucudan gelen İKİLİ çerçeve = 0x01 (raw_up) + ham MAVLink → drona olduğu gibi yazılır (HEPGO Canlı Uçuş ›
  Mission Planner aktarımı; boyut ≤ 4 KB, sihirli bayt 0xFE/0xFD, hız sınırı). Ayrıca YEREL Mission Planner: mp_udp='0.0.0.0:14550'
  (dinle — MP 'UDPCl' ile köprü bilgisayarına bağlanır) ya da '192.168.1.50:14550' (gönder — MP 'UDP' ile dinler); drondan gelen her
  çerçeve yerel MP'ye de gider, MP'den geleni drona yazılır (internet gerekmez). Varsayılan kapalı.

Köprü kodu: '<alan-adı>/<anahtar>' (HEPGO › Dron Yönetimi › Dron Köprüleri'nde köprü eklenince bir kez gösterilir).
"""
import asyncio
import hashlib
import json
import os
import platform
import queue
import socket
import threading
import time
from pathlib import Path

APP_NAME = 'Hepgo Dron Köprüsü'          # ürün adı (mağaza adı değişirse yalnız burası ve paket bildirimi)
VERSION = '1.1.1'
CAPS = ['link', 'set_home', 'param', 'reboot', 'mission_set_current', 'altitude_change', 'arm_force', 'mission_start', 'mission_clear', 'mp_relay',
        'veri_kisiti']
# Uydu / ücretli hat veri kısıtı (link_open rate_pm = dakikada telemetri güncellemesi): otopilottan yalnız bu mesajlar bu
# aralıkla istenir; drondan gelen diğer sürekli akışlar köprüde tutulup aralıkla tek seferde iletilir.
LIMITED_MSGS = (33, 30, 1, 74, 24)   # GLOBAL_POSITION_INT, ATTITUDE, SYS_STATUS, VFR_HUD, GPS_RAW_INT
LIMITED_OFF = (193, 241)             # EKF_STATUS_REPORT, VIBRATION: kısıtlı kipte kapatılır
# Beklemeden iletilen (kullanıcı işleminin yanıtı / olay) mesajlar; HEARTBEAT ayrıca mod ya da kurulum değişince
LIMITED_NOW = ('STATUSTEXT', 'COMMAND_ACK', 'HOME_POSITION', 'AUTOPILOT_VERSION', 'FILE_TRANSFER_PROTOCOL')
LIMITED_NOW_PREFIX = ('MISSION_', 'PARAM_', 'LOG_')
RAW_UP = 0x01                     # v1.4 sunucu → köprü ikili çerçeve türü: 0x01 + ham MAVLink (Mission Planner aktarımı)
RAW_MAX = 4096                    # raw_up / yerel MP datagramı üst sınırı (MAVLink çerçevesi ≤ 280 bayt)
RAW_PPS, RAW_BPS = 400, 256 * 1024   # drona yazılan MP trafiği hız sınırı (paket/sn, bayt/sn; aşan atılır)
MAV_MAGIC = (0xFE, 0xFD)
LOCAL_MP_IDLE_S = 30              # yerel MP (dinle kipi): bu kadar sessizlikte adres kilidi kalkar
PING_S = 20
CHUNK = 256 * 1024
FATAL_CODES = {4400: 'Köprü kodu geçersiz ya da süresi dolmuş (yeni kod alın)',
               4403: 'Köprü kodu geçersiz (HEPGO › Dron Köprüleri › Kodu yenile ile yeni kod alın)',
               4409: 'Bu köprü kodu başka bir cihazda açıldı; bu bağlantı kapatıldı'}


class FatalError(Exception):
    pass


def parse_code(code):
    """'caymaz.app/AbC…' → ('caymaz.app', 'AbC…'). Şema (https://) ve boşluklar ayıklanır."""
    c = (code or '').strip()
    for p in ('https://', 'http://', 'wss://', 'ws://'):
        if c.lower().startswith(p):
            c = c[len(p):]
    if '/' not in c:
        raise ValueError('Köprü kodu "<alan-adı>/<anahtar>" biçiminde olmalı')
    domain, key = c.split('/', 1)
    domain, key = domain.strip().strip('/'), key.strip().strip('/')
    if not domain or not key:
        raise ValueError('Köprü kodu eksik')
    return domain, key


def server_url(domain):
    """Test/geliştirme için HEPGO_KOPRU_URL ortam değişkeni sunucu adresini ezer."""
    return os.environ.get('HEPGO_KOPRU_URL') or f'wss://{domain}/ws/drone/bridge'


def link_text(spec):
    t = spec.get('type')
    if t == 'serial':
        return f"serial:{spec.get('serial')}:{spec.get('baud') or 57600}"
    rate = f" · {spec['rate_pm']}/dk" if spec.get('rate_pm') else ''
    return f"{t}:{spec.get('host') or '0.0.0.0'}:{spec.get('port') or (14550 if t == 'udp' else 5760)}{rate}"


# ======================================================================
# MAVLink tarafı (ayrı iş parçacığı)
# ======================================================================
class _Waiter:
    def __init__(self, types, cond):
        self.types, self.cond, self.q = set(types), cond, queue.Queue()


class MavLink:
    """Drona yerel bağlantı. Okuyucu iş parçacığı her çerçeveyi on_bytes'a verir, bekleyen komutlara dağıtır."""

    def __init__(self, spec, on_bytes, on_state, log=print):
        self.spec = dict(spec)
        self.on_bytes, self.on_state, self.log = on_bytes, on_state, log
        self.m = None
        self.target = int(spec['sysid']) if spec.get('sysid') else None
        self.target_comp = 1
        self.vtype = None
        self.armed = False
        self.last_pos = None
        self.param_types = {}
        self.waiters = []
        self.wlock = threading.Lock()
        self.running = False
        self.rx = 0
        self.last_rx = 0.0
        self.errors = 0
        self.streams = set()   # veri akışı istenmiş sysid'ler
        self._wlock = threading.Lock()   # write_raw (MP baytları) seri yazımı bölünmesin
        # Veri kısıtı (uydu): 0 = sınırsız. Aralık (sn) = 60 / rate_pm
        try:
            self.rate_pm = max(0, min(60, int(spec.get('rate_pm') or 0)))
        except (TypeError, ValueError):
            self.rate_pm = 0
        self.every = 60.0 / self.rate_pm if self.rate_pm else 0.0
        self.fs_gcs = None            # FS_GCS_ENABLE / FS_GCS_ENABL değeri (None = okunamadı → güvenli: sinyal 1 sn)
        self._held = {}               # (src, tür) → son çerçeve (kısıtlı kipte aralıkla iletilir)
        self._held_lock = threading.Lock()
        self._last_mode = {}          # src → (base_mode, custom_mode): değişince HEARTBEAT beklemeden iletilir

    # ---- bağlantı ----
    def open(self):
        from pymavlink import mavutil
        t = self.spec.get('type')
        if t == 'serial':
            dev, baud = self.spec.get('serial'), int(self.spec.get('baud') or 57600)
            if not dev:
                raise ValueError('Seri port seçilmedi')
            self.m = mavutil.mavlink_connection(dev, baud=baud, source_system=255, source_component=190)
        elif t == 'tcp':
            host, port = self.spec.get('host') or '127.0.0.1', int(self.spec.get('port') or 5760)
            self.m = mavutil.mavlink_connection(f'tcp:{host}:{port}', source_system=255, source_component=190)
        elif t == 'udp':
            host, port = (self.spec.get('host') or '0.0.0.0'), int(self.spec.get('port') or 14550)
            mode = 'udpin' if host in ('', '0.0.0.0', '127.0.0.1', 'localhost') else 'udpout'
            self.m = mavutil.mavlink_connection(f'{mode}:{"0.0.0.0" if mode == "udpin" else host}:{port}',
                                                source_system=255, source_component=190)
        else:
            raise ValueError('Bağlantı türü serial / tcp / udp olmalı')
        self.running = True
        threading.Thread(target=self._read, daemon=True, name='mav-okuyucu').start()
        threading.Thread(target=self._gcs_heartbeat, daemon=True, name='mav-kalp').start()
        if self.rate_pm:
            self.log(f'Veri kısıtı: dakikada {self.rate_pm} güncelleme (her {self.every:g} sn)')
            threading.Thread(target=self._flusher, daemon=True, name='mav-kisit').start()

    def close(self):
        self.running = False
        try:
            if self.m:
                self.m.close()
        except Exception:   # noqa: BLE001
            pass

    def write_raw(self, data):
        """v1.4: Mission Planner'dan (sunucu raw_up ya da yerel UDP) gelen ham MAVLink baytlarını drona olduğu gibi yazar."""
        if not self.running or self.m is None:
            return False
        with self._wlock:
            self.m.write(data)
        return True

    def _gcs_heartbeat(self):
        from pymavlink import mavutil
        while self.running:
            try:
                self.m.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            except Exception:   # noqa: BLE001
                pass
            # Kısıtlı kipte sinyal YALNIZ dronda yer istasyonu kopma güvenliği (FS_GCS) açıkça kapalıysa seyrelir; açıksa ya da
            # okunamadıysa 1 sn (aksi hâlde otopilot bağlantı koptu sanıp eve dönüş başlatabilir)
            wait = self.every if (self.rate_pm and self.fs_gcs == 0) else 1.0
            end = time.time() + wait
            while self.running and time.time() < end:
                time.sleep(max(0.0, min(1.0, end - time.time())))

    def _deliver(self, data):
        try:
            self.on_bytes(data)
        except Exception:   # noqa: BLE001
            pass

    def _hold(self, msg, t, src):
        """Kısıtlı kip: True → çerçeve tutuldu (aralıkla iletilecek); False → hemen ilet."""
        if t in LIMITED_NOW or t.startswith(LIMITED_NOW_PREFIX):
            return False
        if t == 'HEARTBEAT':
            key = (msg.base_mode, msg.custom_mode, msg.system_status)
            if self._last_mode.get(src) != key:   # mod / kurulum / durum değişti: beklemeden
                self._last_mode[src] = key
                return False
        with self._held_lock:
            self._held[(src, t)] = bytes(msg.get_msgbuf())
        return True

    def _flusher(self):
        while self.running:
            end = time.time() + self.every
            while self.running and time.time() < end:
                time.sleep(min(0.5, max(0.0, end - time.time())))
            with self._held_lock:
                frames, self._held = list(self._held.values()), {}
            if frames:
                self._deliver(b''.join(frames))   # tek paket: uydu oturum / paket başı ücreti en aza

    def _read(self):
        while self.running:
            try:
                msg = self.m.recv_match(blocking=True, timeout=0.5)
            except Exception as e:   # noqa: BLE001
                self.errors += 1
                if self.errors >= 3 and self.running:
                    self.running = False
                    self.on_state('lost', str(e)[:200])
                    return
                time.sleep(0.3)
                continue
            if msg is None:
                continue
            self.errors = 0
            t = msg.get_type()
            if t == 'BAD_DATA':
                continue
            src = msg.get_srcSystem()
            if t == 'HEARTBEAT' and msg.type != 6 and (self.target is None or src == self.target):
                self.target = src
                self.target_comp = msg.get_srcComponent()
                self.vtype = msg.type
                self.armed = bool(msg.base_mode & 128)
                if src not in self.streams:
                    self._request_streams(src, msg.get_srcComponent())
            elif t == 'GLOBAL_POSITION_INT' and src == self.target:
                self.last_pos = (msg.lat, msg.lon, msg.relative_alt / 1000)
            elif t == 'PARAM_VALUE':
                pid = str(msg.param_id).rstrip('\x00')
                self.param_types[pid] = msg.param_type
                if pid in ('FS_GCS_ENABLE', 'FS_GCS_ENABL'):
                    self.fs_gcs = int(msg.param_value)
            if src == 255:
                continue   # kendi GCS kalp atışımızın yankısı
            self.rx += 1
            self.last_rx = time.time()
            if not (self.rate_pm and self._hold(msg, t, src)):
                self._deliver(bytes(msg.get_msgbuf()))
            with self.wlock:
                ws = list(self.waiters)
            for w in ws:
                if t in w.types and (w.cond is None or w.cond(msg)):
                    w.q.put(msg)

    def _request_streams(self, sysid, comp):
        """GÖKTUNGU dron.py: ilk HEARTBEAT'te tüm veri akışları 4 Hz; EKF_STATUS_REPORT (193) ve VIBRATION (241) 2 Hz,
        HOME_POSITION (242) 5 sn aralıkla (ALL akışında yayılmazlar) + ilk HOME bir kez istenir. SITL ve akış parametresi
        (SRx_*) sıfır olan otopilotlar istek gelmeden telemetri yaymaz."""
        self.streams.add(sysid)
        try:
            if self.rate_pm:   # uydu veri kısıtı: tüm akışlar durdurulur, yalnız temel telemetri seçilen aralıkla
                us = int(self.every * 1e6)
                self.m.mav.request_data_stream_send(sysid, comp, 0, 0, 0)   # MAV_DATA_STREAM_ALL durdur
                for mid in LIMITED_MSGS:
                    self.m.mav.command_long_send(sysid, comp, 511, 0, mid, us, 0, 0, 0, 0, 0)
                for mid in LIMITED_OFF:
                    self.m.mav.command_long_send(sysid, comp, 511, 0, mid, -1, 0, 0, 0, 0, 0)
                for name in (b'FS_GCS_ENABLE', b'FS_GCS_ENABL'):   # Copter / Plane: yer istasyonu kopma güvenliği açık mı
                    self.m.mav.param_request_read_send(sysid, comp, name, -1)
            else:
                self.m.mav.request_data_stream_send(sysid, comp, 0, 4, 1)   # MAV_DATA_STREAM_ALL
                for mid, us in ((193, 500000), (241, 500000), (242, 5000000)):
                    self.m.mav.command_long_send(sysid, comp, 511, 0, mid, us, 0, 0, 0, 0, 0)   # MAV_CMD_SET_MESSAGE_INTERVAL
            self.m.mav.command_long_send(sysid, comp, 512, 0, 242, 0, 0, 0, 0, 0, 0)       # MAV_CMD_REQUEST_MESSAGE (HOME)
        except Exception:   # noqa: BLE001
            self.streams.discard(sysid)

    # ---- yardımcılar ----
    def _waiter(self, types, cond=None):
        w = _Waiter(types, cond)
        with self.wlock:
            self.waiters.append(w)
        return w

    def _drop(self, w):
        with self.wlock:
            if w in self.waiters:
                self.waiters.remove(w)

    def _get(self, w, timeout):
        try:
            return w.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def _tgt(self, sysid=None):
        if sysid:
            return int(sysid)
        if self.target is None:
            raise RuntimeError('Drondan kalp atışı (HEARTBEAT) gelmedi')
        return self.target

    def _cmd_long(self, sysid, cmd, p=(0, 0, 0, 0, 0, 0, 0), timeout=4.0):
        tgt = self._tgt(sysid)
        w = self._waiter(['COMMAND_ACK'], lambda m: m.command == cmd and m.get_srcSystem() == tgt)
        try:
            for _ in range(2):
                self.m.mav.command_long_send(tgt, self.target_comp, cmd, 0, *[float(x) for x in p])
                ack = self._get(w, timeout / 2)
                if ack is not None:
                    if ack.result in (0, 5):   # ACCEPTED / IN_PROGRESS
                        return {'ack': int(ack.result)}
                    raise RuntimeError(f'Dron komutu reddetti (MAV_RESULT {ack.result})')
            raise RuntimeError('Dron komuta yanıt vermedi')
        finally:
            self._drop(w)

    def _modes(self):
        from pymavlink import mavutil
        return mavutil.mode_mapping_byname(self.vtype if self.vtype is not None else 2) or {}

    def _is_plane(self):
        return self.vtype in (1, 19, 20, 21, 22, 23, 24, 25)

    def _set_mode(self, sysid, mode):
        mode = str(mode).upper()
        modes = self._modes()
        if mode not in modes:
            raise RuntimeError(f'Bilinmeyen uçuş modu: {mode}')
        self._cmd_long(sysid, 176, (1, modes[mode], 0, 0, 0, 0, 0))   # MAV_CMD_DO_SET_MODE
        return {'mode': mode}

    # ---- komutlar ----
    def execute(self, name, params, sysid=None):
        p = params or {}
        if name == 'arm':
            return self._cmd_long(sysid, 400, (1, 21196 if p.get('force') else 0, 0, 0, 0, 0, 0), 6)
        if name == 'disarm':
            return self._cmd_long(sysid, 400, (0, 21196 if p.get('force') else 0, 0, 0, 0, 0, 0), 6)
        if name == 'set_mode':
            return self._set_mode(sysid, p.get('mode'))
        if name == 'takeoff':
            alt = float(p.get('alt_rel_m') or 30)
            if not self._is_plane() and 'GUIDED' in self._modes():
                self._set_mode(sysid, 'GUIDED')
            return self._cmd_long(sysid, 22, (0, 0, 0, 0, 0, 0, alt), 6)   # MAV_CMD_NAV_TAKEOFF
        if name == 'land':
            modes = self._modes()
            return self._set_mode(sysid, 'QLAND' if self._is_plane() and 'QLAND' in modes else 'LAND') if ('LAND' in modes or 'QLAND' in modes) \
                else self._cmd_long(sysid, 21)
        if name == 'rtl':
            return self._set_mode(sysid, 'RTL')
        if name == 'goto':
            return self._goto(sysid, float(p['lat']), float(p['lon']), float(p.get('alt_rel_m') or 30), p.get('speed_mps'))
        if name == 'altitude_change':
            alt = float(p['alt_rel_m'])
            if self._is_plane():
                return self._cmd_long(sysid, 186, (alt, 3, 0, 0, 0, 0, 0))   # DO_CHANGE_ALTITUDE, frame GLOBAL_RELATIVE_ALT
            if not self.last_pos:
                raise RuntimeError('Konum bilinmiyor')
            return self._goto(sysid, self.last_pos[0] / 1e7, self.last_pos[1] / 1e7, alt, None)
        if name == 'set_home':
            if p.get('lat') is None:
                return self._cmd_long(sysid, 179, (1, 0, 0, 0, 0, 0, 0))
            return self._cmd_long(sysid, 179, (0, 0, 0, 0, float(p['lat']), float(p['lon']), float(p.get('alt') or 0)))
        if name == 'reboot':
            if self.armed:
                raise RuntimeError('armed')
            return self._cmd_long(sysid, 246, (1, 0, 0, 0, 0, 0, 0))
        if name == 'mission_upload':
            return self._mission_upload(sysid, p.get('items') or [], p.get('cruise_speed'))
        if name == 'mission_download':
            return self._mission_download(sysid)
        if name == 'mission_start':   # MAV_CMD_MISSION_START: AUTO'da yerdeki aracı göreve başlatır (sunucu GUIDED→ARM→AUTO sonrası gönderir)
            return self._cmd_long(sysid, 300, (0, 0, 0, 0, 0, 0, 0), 6)
        if name == 'mission_clear':   # MISSION_CLEAR_ALL (görev iptali: AUTO'ya dönse bile eski görev uçulmaz)
            tgt = self._tgt(sysid)
            w = self._waiter(['MISSION_ACK'], lambda m: m.get_srcSystem() == tgt)
            try:
                self.m.mav.mission_clear_all_send(tgt, self.target_comp, 0)
                ack = self._get(w, 5)
            finally:
                self._drop(w)
            if ack is None:
                raise RuntimeError('Görev listesi temizleme onayı gelmedi')
            if ack.type != 0:
                raise RuntimeError(f'Görev listesi temizlenemedi (MAV_MISSION_RESULT {ack.type})')
            return {'cleared': True}
        if name == 'mission_set_current':
            tgt = self._tgt(sysid)
            # HEPGO sırası → araç sırası: yüklemede başa eklenen ev (+ hız) öğesi kadar kaydır
            self.m.mav.mission_set_current_send(tgt, self.target_comp, int(p['seq']) + getattr(self, 'mis_off', {}).get(tgt, 1))
            return {'seq': int(p['seq'])}
        if name == 'param_list':
            tgt = self._tgt(sysid)
            self.m.mav.param_request_list_send(tgt, self.target_comp)
            return {'requested': True}
        if name == 'param_get':
            return self._param_get(sysid, str(p['name']))
        if name == 'param_set':
            return self._param_set(sysid, str(p['name']), float(p['value']), p.get('type'))
        raise RuntimeError(f'Desteklenmeyen komut: {name}')

    def _goto(self, sysid, lat, lon, alt, speed):
        tgt = self._tgt(sysid)
        if speed:
            try:
                self._cmd_long(sysid, 178, (1, float(speed), -1, 0, 0, 0, 0), 2)   # DO_CHANGE_SPEED (yer hızı)
            except Exception:   # noqa: BLE001
                pass
        if self._is_plane():
            self.m.mav.mission_item_int_send(tgt, self.target_comp, 0, 6, 16, 2, 1, 0, 0, 0, 0,
                                             int(lat * 1e7), int(lon * 1e7), alt)   # current=2: GUIDED hedefi
        else:
            if 'GUIDED' in self._modes():
                self._set_mode(sysid, 'GUIDED')
            self.m.mav.set_position_target_global_int_send(0, tgt, self.target_comp, 6, 0b110111111000,
                                                           int(lat * 1e7), int(lon * 1e7), alt, 0, 0, 0, 0, 0, 0, 0, 0)
        return {'lat': lat, 'lon': lon, 'alt_rel_m': alt}

    def _mission_upload(self, sysid, items, cruise_speed):
        tgt = self._tgt(sysid)
        pos = self.last_pos
        first = items[0] if items else {}
        # ArduPilot 0. öğeyi EV konumu sayar: başa ev öğesi eklenir, HEPGO öğeleri 1'den başlar
        home = {'frame': 0, 'command': 16, 'current': 0, 'autocontinue': 1, 'param1': 0, 'param2': 0, 'param3': 0, 'param4': 0,
                'x': int(pos[0]) if pos else int(first.get('x') or 0), 'y': int(pos[1]) if pos else int(first.get('y') or 0), 'z': 0.0}
        seq_items = [home] + [dict(i) for i in items]
        if cruise_speed:
            seq_items.insert(1, {'frame': 2, 'command': 178, 'current': 0, 'autocontinue': 1, 'param1': 1, 'param2': float(cruise_speed),
                                 'param3': -1, 'param4': 0, 'x': 0, 'y': 0, 'z': 0.0})
        # DO_JUMP (177) hedefi HEPGO öğe sırasıdır: başa eklenen ev (+ hız) öğeleri kadar kaydır
        off = len(seq_items) - len(items)
        if not hasattr(self, 'mis_off'):
            self.mis_off = {}
        self.mis_off[tgt] = off
        for it in seq_items[off:]:
            if int(it.get('command') or 0) == 177:
                it['param1'] = float(it.get('param1') or 0) + off
        n = len(seq_items)
        w = self._waiter(['MISSION_REQUEST_INT', 'MISSION_REQUEST', 'MISSION_ACK'], lambda m: m.get_srcSystem() == tgt)
        try:
            self.m.mav.mission_count_send(tgt, self.target_comp, n, 0)
            sent = set()
            while True:
                msg = self._get(w, 5)
                if msg is None:
                    if not sent:
                        self.m.mav.mission_count_send(tgt, self.target_comp, n, 0)
                        msg = self._get(w, 5)
                    if msg is None:
                        raise RuntimeError(f'Görev yükleme zaman aşımı ({len(sent)}/{n})')
                if msg.get_type() == 'MISSION_ACK':
                    if msg.type == 0:
                        return {'count': len(items), 'uploaded': n, 'offset': off}   # araç sırası = HEPGO sırası + offset
                    raise RuntimeError(f'Dron görevi reddetti (MAV_MISSION_RESULT {msg.type})')
                s = msg.seq
                if s >= n:
                    continue
                it = seq_items[s]
                self.m.mav.mission_item_int_send(tgt, self.target_comp, s, int(it.get('frame', 6)), int(it.get('command', 16)),
                                                 1 if s == 1 else 0, int(it.get('autocontinue', 1)),
                                                 float(it.get('param1', 0)), float(it.get('param2', 0)), float(it.get('param3', 0)),
                                                 float(it.get('param4', 0)), int(it.get('x', 0)), int(it.get('y', 0)), float(it.get('z', 0)), 0)
                sent.add(s)
        finally:
            self._drop(w)

    def _mission_download(self, sysid):
        tgt = self._tgt(sysid)
        w = self._waiter(['MISSION_COUNT', 'MISSION_ITEM_INT'], lambda m: m.get_srcSystem() == tgt)
        try:
            self.m.mav.mission_request_list_send(tgt, self.target_comp, 0)
            cnt = self._get(w, 5)
            while cnt is not None and cnt.get_type() != 'MISSION_COUNT':
                cnt = self._get(w, 5)
            if cnt is None:
                raise RuntimeError('Görev listesi alınamadı')
            out = []
            for s in range(cnt.count):
                for _ in range(3):
                    self.m.mav.mission_request_int_send(tgt, self.target_comp, s, 0)
                    it = self._get(w, 2)
                    while it is not None and (it.get_type() != 'MISSION_ITEM_INT' or it.seq != s):
                        it = self._get(w, 2)
                    if it is not None:
                        break
                else:
                    raise RuntimeError(f'Görev öğesi {s} alınamadı')
                if s == 0:
                    continue   # ev konumu
                out.append({'seq': len(out), 'frame': it.frame, 'command': it.command, 'current': it.current, 'autocontinue': it.autocontinue,
                            'param1': it.param1, 'param2': it.param2, 'param3': it.param3, 'param4': it.param4,
                            'x': it.x, 'y': it.y, 'z': it.z, 'mission_type': 0})
            self.m.mav.mission_ack_send(tgt, self.target_comp, 0, 0)
            return {'items': out}
        finally:
            self._drop(w)

    def _param_get(self, sysid, name):
        tgt = self._tgt(sysid)
        w = self._waiter(['PARAM_VALUE'], lambda m: str(m.param_id).rstrip('\x00') == name)
        try:
            for _ in range(3):
                self.m.mav.param_request_read_send(tgt, self.target_comp, name.encode(), -1)
                v = self._get(w, 2)
                if v is not None:
                    return {'name': name, 'value': v.param_value, 'type': v.param_type}
            raise RuntimeError('Parametre okunamadı')
        finally:
            self._drop(w)

    def _param_set(self, sysid, name, value, ptype):
        tgt = self._tgt(sysid)
        ptype = int(ptype) if ptype else self.param_types.get(name)
        if not ptype:
            raise RuntimeError('type_unknown')
        w = self._waiter(['PARAM_VALUE'], lambda m: str(m.param_id).rstrip('\x00') == name)
        try:
            for _ in range(3):
                self.m.mav.param_set_send(tgt, self.target_comp, name.encode(), value, ptype)
                v = self._get(w, 2)
                if v is not None:
                    return {'name': name, 'value': v.param_value, 'type': v.param_type}
            raise RuntimeError('Parametre yazılamadı')
        finally:
            self._drop(w)


# ======================================================================
# Yerel Mission Planner (UDP; internet gerekmez)
# ======================================================================
def parse_mp_udp(text):
    """'0.0.0.0:14550' → ('dinle', '0.0.0.0', 14550) · '192.168.1.50:14550' → ('gonder', '192.168.1.50', 14550) · ''/kapali → None.
    Önek de verilebilir: 'dinle:0.0.0.0:14550' / 'gonder:10.0.0.5:14550'."""
    t = (text or '').strip()
    if not t or t.lower() in ('kapali', 'kapalı', 'yok', 'off', 'no', 'hayir', 'hayır', '0'):
        return None
    mode = None
    for pre in ('dinle:', 'gonder:', 'gönder:', 'listen:', 'send:'):
        if t.lower().startswith(pre):
            mode = 'dinle' if pre in ('dinle:', 'listen:') else 'gonder'
            t = t[len(pre):]
            break
    if ':' not in t:
        raise ValueError('mp_udp "<adres>:<port>" biçiminde olmalı (ör. 0.0.0.0:14550)')
    host, port = t.rsplit(':', 1)
    host = host.strip() or '0.0.0.0'
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError('mp_udp portu 1…65535 olmalı')
    if mode is None:
        mode = 'dinle' if host in ('0.0.0.0', '::', '*') else 'gonder'
    return mode, ('0.0.0.0' if host == '*' else host), port


class LocalMp:
    """Köprü bilgisayarında yerel UDP: 'dinle' kipinde ilk paket gönderen adres kilitlenir (LOCAL_MP_IDLE_S sessizlikte kalkar);
    'gonder' kipinde sabit adrese gönderilir ve yalnız o IP'den gelen kabul edilir. Okuma ayrı iş parçacığında; on_up(data) çağrılır."""

    def __init__(self, spec, on_up, log=print):
        self.mode, self.host, self.port = spec
        self.on_up, self.log = on_up, log
        self.sock = None
        self.peer = (self.host, self.port) if self.mode == 'gonder' else None
        self.last_rx = 0.0
        self.up = self.down = self.dropped = 0
        self.running = False

    def text(self):
        return f'{self.mode}:{self.host}:{self.port}'

    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port) if self.mode == 'dinle' else ('0.0.0.0', 0))
        s.settimeout(0.5)
        self.sock, self.running = s, True
        threading.Thread(target=self._read, daemon=True, name='yerel-mp').start()

    def stop(self):
        self.running = False
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def _read(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if not self.running:
                    return
                time.sleep(0.2)
                continue
            now = time.time()
            if self.mode == 'dinle':
                if self.peer is None or (addr != self.peer and now - self.last_rx > LOCAL_MP_IDLE_S):
                    if addr != self.peer:
                        self.log(f'Yerel Mission Planner bağlandı: {addr[0]}:{addr[1]}')
                    self.peer = addr
                elif addr[0] != self.peer[0]:
                    self.dropped += 1   # kilit: başka adres
                    continue
                else:
                    self.peer = addr
            elif addr[0] != self.host:
                self.dropped += 1
                continue
            self.last_rx = now
            self.up += 1
            try:
                self.on_up(data)
            except Exception:   # noqa: BLE001
                pass

    def send(self, data):
        p = self.peer
        if p is None or self.sock is None:
            return
        try:
            self.sock.sendto(data, p)
            self.down += 1
        except OSError:
            pass

    def info(self):
        return {'mode': self.mode, 'listen' if self.mode == 'dinle' else 'target': f'{self.host}:{self.port}',
                'peer': f'{self.peer[0]}:{self.peer[1]}' if self.peer else None, 'up': self.up, 'down': self.down, 'dropped': self.dropped,
                'last_rx': self.last_rx or None}


class _Kova:
    """Jeton kovası (paket/sn + bayt/sn); iş parçacığı güvenli."""

    def __init__(self, pps, bps):
        self.pps, self.bps = pps, bps
        self.t, self.p, self.b = time.time(), float(pps), float(bps)
        self.lock = threading.Lock()

    def al(self, n):
        with self.lock:
            now = time.time()
            dt, self.t = now - self.t, now
            self.p = min(self.pps * 2, self.p + dt * self.pps)
            self.b = min(self.bps * 2, self.b + dt * self.bps)
            if self.p < 1 or self.b < n:
                return False
            self.p -= 1
            self.b -= n
            return True


# ======================================================================
# Sunucu tarafı (asyncio)
# ======================================================================
class Bridge:
    """Köprü yaşam döngüsü. ui(event, data) geri çağrısı arayüze olay verir:
    'server' (state, detail), 'link' (state, detail), 'log' (metin), 'stats' (dict)."""

    def __init__(self, code, ui=None, link_spec=None, caps=None, version=None, mp_udp=None):
        self.domain, self.key = parse_code(code)
        self.caps = list(caps) if caps is not None else list(CAPS)   # Linux/Jetson köprüsü görüntü açıksa 'video' ekler (v1.3)
        self.version = version or VERSION
        self.ui = ui or (lambda ev, *a: print(ev, *a))
        self.link_spec = link_spec
        self.mav = None
        self.ws = None
        self.loop = None
        self.out = None           # asyncio.Queue: drona ait ham çerçeveler
        self.stopped = False
        self.log_mode = False     # .bin aktarımı sırasında telemetri iletilmez
        self.log_futs = {}
        self.tx = 0
        self.bridge_name = None
        # v1.4 Mission Planner: sunucu raw_up + yerel UDP (mp_udp: parse_mp_udp metni ya da (kip, adres, port))
        self.mp_spec = parse_mp_udp(mp_udp) if isinstance(mp_udp, str) else mp_udp
        self.local_mp = None
        self.kova = _Kova(RAW_PPS, RAW_BPS)
        self.mp_stats = {'raw_up': 0, 'raw_up_bytes': 0, 'raw_drop': 0, 'raw_nolink': 0, 'last_raw_up': 0.0}

    # ---- iş parçacığından çağrılabilir ----
    def stop(self):
        self.stopped = True
        if self.local_mp:
            self.local_mp.stop()
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._close_ws()))
        if self.mav:
            self.mav.close()

    async def _close_ws(self):
        try:
            if self.ws:
                await self.ws.close()
        except Exception:   # noqa: BLE001
            pass

    def open_link_threadsafe(self, spec):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.open_link(spec), self.loop)

    def close_link_threadsafe(self):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.close_link(), self.loop)

    def send_log_threadsafe(self, path):
        if self.loop:
            return asyncio.run_coroutine_threadsafe(self.send_log(path), self.loop)

    # ---- Mission Planner (v1.4) ----
    def raw_up(self, data, src='sunucu'):
        """Mission Planner baytları → drona. Boyut / sihirli bayt / hız denetimi; bağlantı yoksa atılır. İş parçacığı güvenli."""
        st = self.mp_stats
        if not data or len(data) > RAW_MAX or data[0] not in MAV_MAGIC or not self.kova.al(len(data)):
            st['raw_drop'] += 1
            return False
        mav = self.mav
        if mav is None:
            st['raw_nolink'] += 1
            return False
        try:
            ok = mav.write_raw(data)
        except Exception:   # noqa: BLE001
            ok = False
        if not ok:
            st['raw_nolink'] += 1
            return False
        st['raw_up'] += 1
        st['raw_up_bytes'] += len(data)
        st['last_raw_up'] = time.time()
        return True

    def start_local_mp(self):
        if not self.mp_spec or self.local_mp is not None:
            return
        try:
            lm = LocalMp(self.mp_spec, lambda d: self.raw_up(d, 'yerel'), log=lambda s: self.ui('log', s))
            lm.start()
            self.local_mp = lm
            self.ui('log', f'Yerel Mission Planner UDP açık: {lm.text()}')
        except Exception as e:   # noqa: BLE001
            self.ui('log', f'Yerel Mission Planner UDP açılamadı ({self.mp_spec}): {e}')

    def mp_info(self):
        return {**self.mp_stats, 'local': self.local_mp.info() if self.local_mp else None}

    # ---- bağlantı (drona) ----
    def _on_bytes(self, data):
        lm = self.local_mp
        if lm is not None:   # yerel MP her durumda (log aktarımında da) telemetri alır
            lm.send(data)
        if self.log_mode or self.loop is None or self.out is None:
            return
        self.loop.call_soon_threadsafe(self._enqueue, data)

    def _enqueue(self, data):
        if self.out.qsize() > 2000:   # sunucu yavaşsa en eskisini at (telemetride eski paket değersiz)
            try:
                self.out.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.out.put_nowait(data)

    def _on_link_state(self, state, err=None):
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._link_frame(state, err)))

    async def _link_frame(self, state, err=None):
        txt = link_text(self.link_spec) if self.link_spec else ''
        self.ui('link', state, err or txt)
        await self._send({'t': 'link', 'sysid': (self.link_spec or {}).get('sysid'), 'state': state, 'link': txt, **({'error': err} if err else {})})
        if state in ('open', 'lost'):
            await self._send({'t': 'event', 'text': f"link {state} {txt}" + (f' — {err}' if err else ''), 'severity': 6 if state == 'open' else 4})

    async def open_link(self, spec):
        replaced = False
        if self.mav is not None:
            await self.close_link()
            replaced = True
        self.link_spec = dict(spec)
        mav = MavLink(self.link_spec, self._on_bytes, self._on_link_state, log=lambda s: self.ui('log', s))
        await self.loop.run_in_executor(None, mav.open)
        self.mav = mav
        await self._link_frame('open')
        return {'link': link_text(self.link_spec), **({'replaced': True} if replaced else {})}

    async def close_link(self):
        if self.mav is None:
            return {'closed': False}
        m, self.mav = self.mav, None
        await self.loop.run_in_executor(None, m.close)
        await self._link_frame('closed')
        return {'closed': True}

    # ---- WebSocket ----
    async def _send(self, obj):
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps(obj, ensure_ascii=False))
        except Exception:   # noqa: BLE001
            pass

    async def run(self):
        import websockets
        self.loop = asyncio.get_running_loop()
        self.out = asyncio.Queue()
        self.start_local_mp()
        if self.link_spec:
            try:
                await self.open_link(self.link_spec)
            except Exception as e:   # noqa: BLE001
                self.ui('link', 'error', str(e))
        backoff = 2
        while not self.stopped:
            url = server_url(self.domain)
            self.ui('server', 'connecting', url)
            try:
                async with websockets.connect(url, max_size=None, ping_interval=None, open_timeout=15, close_timeout=3) as ws:
                    await ws.send(json.dumps({'v': 1, 't': 'auth', 'key': self.key, 'host': socket.gethostname()[:120],
                                              'platform': platform.system().lower()[:40], 'bridge_ver': self.version, 'caps': self.caps}))
                    first = json.loads(await asyncio.wait_for(ws.recv(), 15))
                    if first.get('t') != 'auth_ok':
                        raise FatalError(FATAL_CODES[4403])
                    self.ws = ws
                    self.bridge_name = first.get('name')
                    self.ui('server', 'connected', f"{first.get('name')} · oturum #{first.get('session_id')}")
                    backoff = 2
                    if self.mav is not None:
                        await self._link_frame('open')
                    tasks = [asyncio.create_task(self._pinger()), asyncio.create_task(self._forwarder())]
                    try:
                        await self._receiver(ws)
                    finally:
                        for t in tasks:
                            t.cancel()
                        self.ws = None
            except FatalError as e:
                self.ui('server', 'fatal', str(e))
                return
            except Exception as e:   # noqa: BLE001
                code = getattr(getattr(e, 'rcvd', None), 'code', None)
                if code in FATAL_CODES:
                    self.ui('server', 'fatal', FATAL_CODES[code])
                    return
                wait = 60 if code == 4429 else backoff
                self.ui('server', 'retry', f'{type(e).__name__}: {str(e)[:120]} · {wait} sn sonra yeniden')
                if self.stopped:
                    return
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, 30)
        self.ui('server', 'stopped', '')

    async def _pinger(self):
        while True:
            await asyncio.sleep(PING_S)
            await self._send({'t': 'ping'})
            self.ui('stats', {'tx': self.tx, 'rx': self.mav.rx if self.mav else 0,
                              'drone': self.mav.target if self.mav else None,
                              'last_rx': self.mav.last_rx if self.mav else 0, 'mp': self.mp_info()})

    async def _forwarder(self):
        while True:
            data = await self.out.get()
            buf = bytearray(data)
            while not self.out.empty() and len(buf) < 32768:
                buf += self.out.get_nowait()
            if self.log_mode or self.ws is None:
                continue
            try:
                await self.ws.send(bytes(buf))
                self.tx += 1
            except Exception:   # noqa: BLE001
                return

    async def _receiver(self, ws):
        async for raw in ws:
            if isinstance(raw, bytes):
                if raw[:1] == bytes([RAW_UP]):   # v1.4 raw_up: HEPGO Mission Planner aktarımı → drona
                    self.raw_up(raw[1:])
                continue   # diğer ikili türler: yok sayılır (ileri uyum)
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            t = m.get('t')
            if t == 'cmd':
                asyncio.create_task(self._handle_cmd(m))
            elif t in ('log_ready', 'log_ack', 'log_err'):
                fut = self.log_futs.pop('cur', None)
                if fut and not fut.done():
                    fut.set_result(m)
            # pong / diğerleri: yok sayılır

    async def _handle_cmd(self, m):
        rid, name, params, sysid = m.get('rid'), m.get('name'), m.get('params') or {}, m.get('sysid')
        self.ui('log', f'Komut: {name} {json.dumps(params, ensure_ascii=False)[:120]}')
        try:
            if name == 'link_open':
                if sysid and not params.get('sysid'):
                    params['sysid'] = sysid
                result = await self.open_link(params)
            elif name == 'link_close':
                result = await self.close_link()
            else:
                if self.mav is None:
                    raise RuntimeError('Dron bağlantısı açık değil (link_open gerekli)')
                result = await self.loop.run_in_executor(None, self.mav.execute, name, params, sysid)
            await self._send({'t': 'res', 'rid': rid, 'ok': True, 'result': result})
            self.ui('log', f'  ✓ {name}')
        except Exception as e:   # noqa: BLE001
            err = str(e)[:300] or type(e).__name__
            if name == 'link_open':
                err = f'link_open: {err}'
                self.ui('link', 'error', err)
            await self._send({'t': 'res', 'rid': rid, 'ok': False, 'error': err})
            self.ui('log', f'  ✗ {name}: {err}')

    # ---- uçuş logu ----
    async def _wait_log(self, timeout):
        fut = self.loop.create_future()
        self.log_futs['cur'] = fut
        return await asyncio.wait_for(fut, timeout)

    async def send_log(self, path):
        p = Path(path)
        size = p.stat().st_size
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                h.update(b)
        if self.ws is None:
            raise RuntimeError('Sunucuya bağlı değil')
        self.log_mode = True
        try:
            waiter = asyncio.ensure_future(self._wait_log(30))
            await self._send({'t': 'log_begin', 'name': p.name[:120], 'size': size, 'sha256': h.hexdigest()})
            r = await waiter
            if r.get('t') != 'log_ready':
                raise RuntimeError(r.get('error') or 'Sunucu logu kabul etmedi')
            sent = 0
            with open(p, 'rb') as f:
                for b in iter(lambda: f.read(CHUNK), b''):
                    await self.ws.send(b)
                    sent += len(b)
                    self.ui('log', f'Log gönderiliyor %{sent * 100 // size}')
            waiter = asyncio.ensure_future(self._wait_log(120))
            await self._send({'t': 'log_end'})
            r = await waiter
            if r.get('t') != 'log_ack':
                raise RuntimeError(r.get('error') or 'Log doğrulanamadı')
            self.ui('log', f"Uçuş logu gönderildi (#{r.get('flight_log_id')})")
            return r.get('flight_log_id')
        finally:
            self.log_mode = False
