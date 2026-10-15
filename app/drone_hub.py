"""Dron köprüsü hub'ı (Dron Yönetimi paketi, Faz 0): pilotun cihazındaki köprü yazılımı sunucuya DIŞA DOĞRU WebSocket ile
bağlanır (port açılmaz; Cloudflare tüneli + Unix soket mimarisiyle uyumlu), drondan gelen ham MAVLink baytlarını ikili çerçeve
olarak iletir; sunucu pymavlink ile çözümleyip tarayıcılara (Canlı Uçuş) 5–10 Hz JSON durum paketi dağıtır; tarayıcıdan gelen
komutlar (arm, set_mode, rtl, …) req/res RPC ile köprüye iletilir. Uçuş sonrası .bin logu köprü kanalından parça parça gelir ve
flight_logs'a (source=BRIDGE) düşer. Canlı telemetri DOSYAYA (.tlog) yazılır; veritabanında yalnız oturum meta tutulur.

Protokol v1 (GÖKTUNGU köprüleriyle ortak sözleşme):
  köprü → sunucu (metin JSON): {v:1,t:'auth',key,host,platform,bridge_ver} | {v:1,t:'pair',code,host,platform,bridge_ver}
      | {t:'ping'} | {t:'res',rid,ok,result|error} | {t:'log_begin',name,size,sha256,flight_id?,task_id?} | {t:'log_end'}
  köprü → sunucu (ikili): ham MAVLink v1/v2 çerçeveleri; log aktarımı sırasında (.bin parçaları, ≤ 1 MB)
  sunucu → köprü: {t:'auth_ok',bridge_id,server_time,key?} | {t:'auth_err',code} | {t:'pong'} | {t:'cmd',rid,sysid,name,params}
      | {t:'log_ack',flight_log_id} | {t:'log_err',error}
  tarayıcı ↔ sunucu (/ws/drone/live, oturum çerezi): ← {t:'hello',bridges,task?,flights?} {t:'status',bridge_id,sysid,state}
      {t:'bridge',bridge_id,online} {t:'event',bridge_id,sysid,text,severity} {t:'res',rid,ok,…} {t:'pong'}
      → {t:'ping'} {t:'cmd',rid,bridge_id,sysid,name,params} {t:'watch',task_id} | {t:'watch',bridge_id|null}
  Kapanış kodları: 4400 kimlik yok/zaman aşımı · 4403 anahtar/kod yanlış · 4409 aynı köprü ikinci bağlantı (eski kapatılır)
      · 4429 hız sınırı (IP başına 10 başarısız deneme / dk).
Komut adları v1: arm, disarm, set_mode{mode}, takeoff{alt_rel_m}, land, rtl, goto{lat,lon,alt_rel_m,speed_mps?},
  mission_upload{items}, mission_download, disconnect (sunucu tarafı: köprü oturumunu KAPANDI ile kapatır).
Faz 1 — GÖREV BAĞLAMI: harekât ekranı {t:'watch',task_id} gönderir; izleyici yalnız o saha görevinin uçuşlarına bağlı köprüleri
  (field_flights.bridge_id) ve görevin SANAL dronlarını görür. Sanal dron (protocol='sanal'): sunucu içi simülatör SimDrone,
  köprü gibi davranır, bridge_id = -drone_id (negatif). Bağlantı bilgisi (köprü/sysid/link) dron kaydında değil uçuştadır.
Tek uvicorn süreci varsayılır (tenant başına bir süreç; --workers>1 ile hub paylaşılamaz).
"""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth, cameras, config, db, drone_sitl

ws_router = APIRouter()

PROTO = 1
CAPS = ['console', 'arm_check']   # tarayıcıya bildirilen sunucu yetenekleri (harekât arayüzü HEPGO_OZ bayrakları); set_home/param köprü desteğiyle gelir
CONSOLE_MAX = 200         # Haberleşme konsolu: dron (sysid) başına saklanan satır
PAIR_TTL = 600            # eşleştirme kodu ömrü (sn)
AUTH_TIMEOUT = 15         # ilk mesaj için bekleme
STATUS_HZ = 10            # tarayıcıya en çok durum paketi/sn (sysid başına)
VIEWER_QUEUE = 32         # izleyici kuyruğu (dolunca en eskisi atılır; parametre akışı toplu 'params' paketleriyle gider)
LOG_MAX = 2 * 1024 ** 3   # köprüden gelen .bin üst sınırı
RATE_WINDOW, RATE_MAX = 60, 10
CMD_TIMEOUT = 10
CMD_TIMEOUTS = {'mission_upload': 60, 'mission_download': 60, 'log_list': 60}
# Sunucu-içi bileşik komutlar (GÖKTUNGU dron.py / gorev.py akışı birebir; köprüye v1 set_mode/arm/takeoff olarak gider):
#  takeoff       → set_mode GUIDED → mod teyidi (4 sn) → (ARM değilse) ARM (zorlamasız) → ARM teyidi (6 sn) → NAV_TAKEOFF.
#                  Pilot ayrıca ARM etmez. Akış arka planda yürür; yanıt akış başlayınca döner, adımlar dron konsoluna düşer.
#  mission_start → (ARM değilse) GUIDED → 0,3 sn → ARM → teyit (5 sn) → AUTO → 0,3 sn → MISSION_START (köprü 'mission_start'
#                  yeteneği bildirdiyse). NAV_TAKEOFF gönderilmez: rotanın ilk öğesi TAKEOFF'tur (routes/{id}/mission ekler).
TAKEOFF_ALT = 10.0
GUIDED_CONFIRM_S = 4.0
ARM_CONFIRM_S = 6.0
MISSION_ARM_CONFIRM_S = 5.0
SEQ_CMDS = {'takeoff', 'mission_start'}
_FLOWS = {}         # (bridge_id, sysid) → sürmekte olan kalkış/görev akışı   # öğe başına MISSION_REQUEST_INT turu (telsizde 0,2–1 sn) → uzun rotalar
CMD_NAMES = {'arm', 'disarm', 'set_mode', 'takeoff', 'land', 'rtl', 'goto', 'mission_upload', 'mission_download', 'disconnect', 'arm_check',
             # protokol v1.1 (isteğe bağlı; köprü auth çerçevesinde caps ile bildirir, desteklemiyorsa res.error döner)
             'set_home', 'param_list', 'param_get', 'param_set', 'reboot', 'mission_set_current', 'altitude_change',
             # v1.1 cap 'link': köprünün drona yerel bağlantısını (uçuşun link ayarı) açma/kapama
             'link_open', 'link_close',
             # protokol v1.2 taslağı (docs/dron-kopru-protokolu.md; caps 'bakim' / 'log' bildiren köprüler)
             'kalib_gyro', 'kalib_baro', 'kalib_ivme', 'kalib_level', 'kalib_esc', 'kalib_radyo',
             'kalib_pusula_baslat', 'kalib_pusula_kabul', 'kalib_pusula_iptal', 'motor_test', 'motor_test_dur', 'log_list', 'log_fetch', 'log_erase',
             # sunucu-içi bileşik komut (bkz. SEQ_CMDS); köprü 'mission_start' yeteneği bildirirse MAV_CMD_MISSION_START olarak da gider
             'mission_start'}
BRIDGE_CAPS = {'set_home', 'param', 'arm_force', 'reboot', 'mission_set_current', 'altitude_change', 'log', 'bakim', 'link', 'mission_start'}   # köprünün bildirebileceği yetenekler
OPEN_TASK = ('BASLANGIC', 'GOREVDE')   # sanal dron yalnız açık görevde uçar
# Sanal dron = gerçek ArduPilot SITL süreci (GÖKTUNGU). HEPGO_SITL=0 → eski sunucu içi kinematik simülatör (yalnız testler).
SITL_ENABLED = os.environ.get('HEPGO_SITL', '1') != '0'
SITL_CONNECT_S = 40                     # SITL ayağa kalkıp SERIAL0'ı dinleyene dek bağlanma denemesi (GÖKTUNGU Tuzak D)
SIM_IDLE = 600                          # izleyici kalmayınca sanal dronun durma süresi (sn)

BRIDGES = {}        # bridge_id → Bridge (yalnız canlı bağlantılar)
SIMS = {}           # -drone_id → SimDrone (çalışan sanal dronlar)
VIEWERS = {}        # ws → Viewer
PAIR_CODES = {}     # kod → {'bridge_id', 'exp'}
_fails = {}         # ip → [zaman damgası…]
_pending = {}       # rid → (Future, viewer_ws | None, bridge_id)
_loop_task = None


def _db(fn, *a):
    return asyncio.to_thread(fn, *a)


# ---------------- MAVLink çözümleme ----------------
def _mav():
    from pymavlink.dialects.v20 import ardupilotmega as dialect
    p = dialect.MAVLink(None)
    p.robust_parsing = True
    return p


def _mode_name(mav_type, num):
    try:
        from pymavlink import mavutil
        mp = mavutil.mode_mapping_bynumber(mav_type) or {}
        return mp.get(num) or str(num)
    except Exception:   # noqa: BLE001
        return str(num)


MAV_TYPES = {1: 'Sabit kanat', 2: 'Quadrotor', 3: 'Koaksiyel', 4: 'Helikopter', 10: 'Kara aracı', 11: 'Deniz aracı', 12: 'Denizaltı', 13: 'Hexarotor',
             14: 'Octorotor', 15: 'Tricopter', 19: 'VTOL tailsitter', 20: 'VTOL tiltrotor', 21: 'VTOL', 22: 'VTOL tailsitter', 23: 'VTOL tiltwing',
             24: 'VTOL', 29: 'Dodecarotor', 35: 'Decarotor'}
# MAV_SYS_STATUS_SENSOR bit maskesi (SYS_STATUS.onboard_control_sensors_*): panelde sensör sağlığı rozetleri için
SENSOR_BITS = {'gyro': 1, 'accel': 2, 'mag': 4, 'baro': 8, 'diff_press': 16, 'gps': 32, 'optflow': 64, 'vision': 128, 'laser': 256, 'ext_gnd_truth': 512,
               'rate_ctrl': 1024, 'att_stab': 2048, 'yaw_pos': 4096, 'z_alt_ctrl': 8192, 'xy_pos_ctrl': 16384, 'motor': 32768, 'rc': 65536,
               'ahrs': 2097152, 'terrain': 4194304, 'battery': 33554432, 'prearm': 268435456, 'logging': 1073741824, 'geofence': 1048576}


def _dist_m(lat1, lon1, lat2, lon2):
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


class DroneState:
    """Bir sysid'nin son bilinen durumu (JSON'a çevrilebilir sözlük). Alanlar GÖKTUNGU harekât paneliyle uyumlu (README eşlemesi)."""
    __slots__ = ('d', 'emitted', 'dirty', 'timer', 'armed_at', 'last_pos', 'console', 'rc_at', 'texts', 'params', 'param_buf', 'param_timer')

    def __init__(self, sysid):
        self.timer = None   # hız sınırına takılan güncellemeyi sonradan yayınlayan zamanlayıcı
        self.params = {}    # PARAM_VALUE önbelleği: ad → [değer, index, count, type] (status paketine GİRMEZ; param_cache ile istenir)
        self.param_buf = []   # yayın bekleyen PARAM_VALUE'lar (200 ms'de bir toplu 'params' paketi)
        self.param_timer = None
        self.armed_at = None   # ARM anı (uçuş süresi)
        self.last_pos = None   # kat edilen mesafe için son konum
        self.console = []      # Haberleşme konsolu satırları (son CONSOLE_MAX): {ts, tag, text, sev, repeat}
        self.rc_at = None      # son RC_CHANNELS zamanı (ARM CHECK: kumanda bağlı mı)
        self.texts = []        # son STATUSTEXT'ler (ARM CHECK mesajlar sekmesi): {ts, text, severity}
        self.d = {'sysid': sysid, 'type': None, 'type_name': None, 'autopilot': None, 'armed': False, 'mode': None, 'mode_num': None,
                  'lat': None, 'lon': None, 'alt': None, 'alt_rel': None, 'hdg': None, 'vx': None, 'vy': None, 'vz': None,
                  'airspeed': None, 'groundspeed': None, 'throttle': None, 'climb': None, 'roll': None, 'pitch': None, 'yaw': None,
                  'volt': None, 'curr': None, 'batt_pct': None, 'fix': None, 'sats': None, 'hdop': None, 'rpm': None,
                  'wp_dist': None, 'mission_seq': None, 'mission_count': None, 'home_lat': None, 'home_lon': None, 'home_alt': None,
                  'sensors': None, 'ekf_flags': None, 'prearm': [], 'last_text': None, 'flight_s': 0, 'dist_m': 0.0,
                  'magkal_pct': None, 'magkal_durum': None, 'magkal_rapor': None, 'kalib': None,   # v1.2 pusula kalibrasyonu / kalibrasyon oturumu
                  'last_hb': None, 'updated': None, 'msgs': 0}
        self.emitted = 0.0
        self.dirty = False

    def feed(self, m):
        t = m.get_type(); d = self.d
        d['msgs'] += 1
        if t == 'HEARTBEAT':
            if getattr(m, 'type', None) in (6,):   # GCS kalp atışı — dron değil
                return False
            d['type'] = m.type; d['type_name'] = MAV_TYPES.get(m.type, f'Tip {m.type}'); d['autopilot'] = m.autopilot
            armed = bool(m.base_mode & 128)
            now = time.time()
            if armed and not d['armed']:
                self.armed_at = now; d['dist_m'] = 0.0; d['prearm'] = []
            elif not armed and d['armed']:
                self.armed_at = None
            d['armed'] = armed
            if self.armed_at:
                d['flight_s'] = int(now - self.armed_at)
            d['mode_num'] = m.custom_mode; d['mode'] = _mode_name(m.type, m.custom_mode)
            d['last_hb'] = now
        elif t == 'GLOBAL_POSITION_INT':
            lat, lon = m.lat / 1e7, m.lon / 1e7
            if d['armed'] and self.last_pos and lat and lon:
                d['dist_m'] = round(d['dist_m'] + _dist_m(self.last_pos[0], self.last_pos[1], lat, lon), 1)
            if lat or lon:
                self.last_pos = (lat, lon)
            d['lat'] = lat; d['lon'] = lon; d['alt'] = m.alt / 1000; d['alt_rel'] = m.relative_alt / 1000
            d['vx'] = m.vx / 100; d['vy'] = m.vy / 100; d['vz'] = m.vz / 100; d['hdg'] = (m.hdg / 100) if m.hdg != 65535 else None
        elif t == 'NAV_CONTROLLER_OUTPUT':
            d['wp_dist'] = m.wp_dist
        elif t == 'MISSION_CURRENT':
            d['mission_seq'] = m.seq
            if getattr(m, 'total', 65535) not in (65535, None):
                d['mission_count'] = m.total
        elif t == 'HOME_POSITION':
            d['home_lat'] = m.latitude / 1e7; d['home_lon'] = m.longitude / 1e7; d['home_alt'] = m.altitude / 1000
        elif t == 'EKF_STATUS_REPORT':
            d['ekf_flags'] = m.flags
        elif t in ('RC_CHANNELS', 'RC_CHANNELS_RAW'):
            self.rc_at = time.time()
            return False
        elif t == 'MAG_CAL_PROGRESS':   # v1.2 pusula kalibrasyonu ilerlemesi
            d['magkal_pct'] = m.completion_pct; d['magkal_durum'] = m.cal_status
        elif t == 'MAG_CAL_REPORT':
            d['magkal_durum'] = m.cal_status
            d['magkal_rapor'] = {'compass_id': m.compass_id, 'fitness': m.fitness, 'cal_status': m.cal_status, 'autosaved': m.autosaved,
                                 'ofs': [m.ofs_x, m.ofs_y, m.ofs_z], 'diag': [m.diag_x, m.diag_y, m.diag_z], 'offdiag': [m.offdiag_x, m.offdiag_y, m.offdiag_z]}
        elif t == 'PARAM_VALUE':   # v1.1 param_list/param_get/param_set yankısı: önbelleğe + toplu yayın kuyruğuna
            name = str(m.param_id).rstrip('\x00')
            self.params[name] = [m.param_value, m.param_index, m.param_count, m.param_type]
            self.param_buf.append([name, m.param_value, m.param_index, m.param_count, m.param_type])
            return False
        elif t == 'VFR_HUD':
            d['airspeed'] = m.airspeed; d['groundspeed'] = m.groundspeed; d['throttle'] = m.throttle; d['climb'] = m.climb
            if d['hdg'] is None:
                d['hdg'] = m.heading
        elif t == 'ATTITUDE':
            import math
            d['roll'] = round(math.degrees(m.roll), 1); d['pitch'] = round(math.degrees(m.pitch), 1); d['yaw'] = round(math.degrees(m.yaw) % 360, 1)
        elif t == 'SYS_STATUS':
            d['volt'] = m.voltage_battery / 1000 if m.voltage_battery != 65535 else None
            d['curr'] = m.current_battery / 100 if m.current_battery != -1 else None
            d['batt_pct'] = m.battery_remaining if m.battery_remaining != -1 else None
            pres, en, ok = m.onboard_control_sensors_present, m.onboard_control_sensors_enabled, m.onboard_control_sensors_health
            d['sensors'] = {k: ('ok' if ok & b else 'fail') for k, b in SENSOR_BITS.items() if (pres & b) and (en & b)}
        elif t == 'GPS_RAW_INT':
            d['fix'] = m.fix_type; d['sats'] = m.satellites_visible; d['hdop'] = m.eph / 100 if m.eph != 65535 else None
        elif t == 'RPM':
            d['rpm'] = getattr(m, 'rpm1', None)
        else:
            return False
        d['updated'] = time.time()
        self.dirty = True
        return True


class Viewer:
    def __init__(self, ws, user):
        self.ws, self.user = ws, user
        self.q = asyncio.Queue(maxsize=VIEWER_QUEUE)
        self.watch = None     # bridge_id ya da None (hepsi) — eski davranış
        self.loop = asyncio.get_running_loop()   # izleyicinin olay döngüsü (task_changed istek iş parçacığından buraya aktarır)
        self.task_id = None   # Faz 1: görev bağlamı ({t:'watch',task_id}); doluysa yalnız görevin köprüleri/sanal dronları geçer
        self.allowed = set()  # görevin uçuşlarına bağlı köprü kimlikleri (+ sanal dron -drone_id)
        self.task = None      # hello.task {id, code, status, location_name, lat, lon}
        self.flights = []     # hello.flights (task_live ile aynı satırlar)

    def passes(self, bridge_id):
        """Bu izleyiciye bridge_id kaynaklı bir mesaj gider mi? (None: kaynaksız mesaj, herkese)"""
        if bridge_id is None:
            return True
        if self.task_id is not None:
            return bridge_id in self.allowed
        return self.watch is None or self.watch == bridge_id

    def put(self, txt):
        try:
            self.q.put_nowait(txt)
        except asyncio.QueueFull:   # yetişemiyor: en eskisini at (telemetride eski paket değersiz)
            try:
                self.q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.q.put_nowait(txt)
            except asyncio.QueueFull:
                pass


class Bridge:
    def __init__(self, ws, row, host, platform, ver, caps=()):
        self.ws, self.id, self.name = ws, row['id'], row['name']
        self.host, self.platform, self.ver = host, platform, ver
        self.caps = sorted(set(caps) & BRIDGE_CAPS)   # v1.1: köprünün desteklediği isteğe bağlı komutlar
        self.session_id = None
        self.parser = _mav()
        self.drones = {}        # sysid → DroneState
        self.packets = 0
        self.last_seen = time.time()
        self.connected_at = db.now()
        self.closing = None     # None | 'KAPANDI' (sunucu/pilot kapattı)
        self.log = None         # aktif .bin aktarımı: {'f', 'h', 'size', 'got', 'name', 'sha', 'path', 'flight_id', 'task_id'}
        self.tlog = None        # canlı telemetri dosyası
        self.tlog_path = None

    def info(self):
        return {'bridge_id': self.id, 'name': self.name, 'host': self.host, 'platform': self.platform, 'bridge_ver': self.ver, 'caps': self.caps,
                'connected_at': self.connected_at, 'packets': self.packets, 'session_id': self.session_id,
                'drones': {str(s): st.d for s, st in self.drones.items()}}


# ---------------- Yardımcılar ----------------
def _broadcast(msg, bridge_id=None):
    """İzleyicilere yayın. Kaynak köprü: bridge_id parametresi, yoksa mesajın bridge_id alanı (köprü çevrimiçi/çevrimdışı
    bildirimleri) — görev bağlamındaki izleyiciler yalnız kendi görevlerinin köprülerini görür."""
    txt = json.dumps(msg, ensure_ascii=False)
    src = bridge_id if bridge_id is not None else msg.get('bridge_id')
    for v in list(VIEWERS.values()):
        if v.passes(src):
            v.put(txt)


def _bridge_or_sim(bridge_id):
    """Gerçek köprü (pozitif) ya da sanal dron (negatif, -drone_id); yoksa None."""
    try:
        bid = int(bridge_id or 0)
    except (TypeError, ValueError):
        return None
    return SIMS.get(bid) if bid < 0 else BRIDGES.get(bid)


async def _safe_send(ws, msg):
    try:
        await ws.send_text(json.dumps(msg, ensure_ascii=False))
    except Exception:   # noqa: BLE001
        pass


def _rate_limited(ip):
    now = time.time()
    lst = [t for t in _fails.get(ip, []) if now - t < RATE_WINDOW]
    _fails[ip] = lst
    return len(lst) >= RATE_MAX


def _note_fail(ip):
    _fails.setdefault(ip, []).append(time.time())


def _resolve_key(key):
    """Düz anahtar → drone_bridges satırı (sabit-zamanlı karşılaştırma, yalnız aktif köprüler)."""
    if not key:
        return None
    with db.connect() as conn:
        rows = db.rows(conn.execute('SELECT id, name, key_enc FROM drone_bridges WHERE active = 1 AND key_enc IS NOT NULL'))
    for r in rows:
        try:
            if hmac.compare_digest(cameras.decrypt(r['key_enc']), key):
                return r
        except Exception:   # noqa: BLE001
            continue
    return None


def make_pair_code(bridge_id):
    """Panelden 'Eşleştir': 6 karakterli tek kullanımlık kod (10 dk). Aynı köprünün eski kodu iptal olur."""
    for c, v in list(PAIR_CODES.items()):
        if v['bridge_id'] == bridge_id or v['exp'] < time.time():
            PAIR_CODES.pop(c, None)
    code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
    PAIR_CODES[code] = {'bridge_id': bridge_id, 'exp': time.time() + PAIR_TTL}
    return {'code': code, 'expires_in': PAIR_TTL}


def issue_key(conn, bridge_id):
    """Yeni kalıcı anahtar üretir, şifreli saklar, DÜZ metni döndürür (yalnız bir kez gösterilir); eski anahtar geçersiz olur."""
    key = secrets.token_urlsafe(32)
    conn.execute('UPDATE drone_bridges SET key_enc = ?, updated_at = ? WHERE id = ?', (cameras.encrypt(key), db.now(), bridge_id))
    return key


def online_bridges():
    return {b.id: b.info() for b in BRIDGES.values()}


def snapshot():
    """Bağlı gerçek köprüler + çalışan sanal dronlar (köprü gibi; bridge_id negatif, info.sim = True)."""
    return {'bridges': [b.info() for b in BRIDGES.values()] + [s.info() for s in SIMS.values()]}


def all_caps(bridges=None):
    """Tarayıcıya bildirilen yetenekler: sunucu yetenekleri + bağlı köprülerin bildirdikleri (köprü bazlı ayrım hello.bridges[].caps'te).
    bridges verilirse (görev bağlamı) yalnız o köprülerin yetenekleri eklenir."""
    caps = set(CAPS)
    for b in (bridges if bridges is not None else [*BRIDGES.values(), *SIMS.values()]):
        caps |= set(b.caps)
    return sorted(caps)


async def disconnect_bridge(bridge_id, reason='KAPANDI'):
    b = BRIDGES.get(bridge_id)
    if not b:
        return False
    b.closing = reason
    try:
        await b.ws.close(code=1000)
    except Exception:   # noqa: BLE001
        pass
    return True


def _open_session(bridge, started_by=None):
    def work():
        tdir = config.UPLOAD_DIR / 'drone'
        tdir.mkdir(parents=True, exist_ok=True)
        rel = f"drone/{db.now().replace(':', '').replace('-', '')[:15]}-{bridge.id}-{secrets.token_hex(4)}.tlog"
        with db.connect() as conn:
            cur = conn.execute('''INSERT INTO drone_bridge_sessions (bridge_id, started_by, started_at, status, tlog_path, last_seen)
                                  VALUES (?,?,?,'ACIK',?,?)''', (bridge.id, started_by, db.now(), rel, db.now()))
            conn.execute("UPDATE drone_bridges SET status = 'CEVRIMICI', last_seen = ?, host = ?, platform = ?, bridge_ver = ? WHERE id = ?",
                         (db.now(), bridge.host, bridge.platform, bridge.ver, bridge.id))
            db.audit(conn, None, 'Dron köprüsü bağlandı', 'drone_bridge', bridge.id, f'{bridge.name} · {bridge.host or ""}')
            conn.commit()
            return cur.lastrowid, rel
    return _db(work)


def _close_session(bridge, status, error=None, mark_offline=True):
    """Oturum kapanışını arka plan iş parçacığında yazar (await edilmez): bağlantı görevi iptal edilmiş olsa bile tamamlanır."""
    def work():
        try:
            with db.connect() as conn:
                conn.execute('UPDATE drone_bridge_sessions SET ended_at = ?, status = ?, packets = ?, last_seen = ?, error = ? WHERE id = ?',
                             (db.now(), status, bridge.packets, db.now(), error, bridge.session_id))
                if mark_offline:
                    conn.execute("UPDATE drone_bridges SET status = 'CEVRIMDISI', last_seen = ? WHERE id = ?", (db.now(), bridge.id))
                db.audit(conn, None, 'Dron köprüsü ayrıldı', 'drone_bridge', bridge.id, f'{bridge.name} · {status} · {bridge.packets} paket')
                conn.commit()
        except Exception:   # noqa: BLE001
            pass
    try:
        asyncio.get_running_loop().run_in_executor(None, work)
    except RuntimeError:
        threading.Thread(target=work, daemon=True).start()


def _tlog_write(bridge, data):
    """Mission Planner uyumlu .tlog: her MAVLink çerçevesi önünde 8 bayt big-endian mikrosaniye zaman damgası."""
    if bridge.tlog is None:
        try:
            p = config.UPLOAD_DIR / bridge.tlog_path
            bridge.tlog = open(p, 'ab')
        except OSError:
            return
    try:
        bridge.tlog.write(int(time.time() * 1e6).to_bytes(8, 'big') + data)
    except OSError:
        pass


# ---------------- Köprü: /ws/drone/bridge ----------------
@ws_router.websocket('/ws/drone/bridge')
async def ws_bridge(ws: WebSocket):
    await ws.accept()
    ip = (ws.client.host if ws.client else '') or ''
    if _rate_limited(ip):
        await ws.close(code=4429)
        return
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT))
    except Exception:   # noqa: BLE001
        await ws.close(code=4400)
        return
    row, issued = None, None
    if first.get('t') == 'auth':
        row = await _db(_resolve_key, str(first.get('key') or ''))
    elif first.get('t') == 'pair':
        code = str(first.get('code') or '').strip().upper()
        pc = PAIR_CODES.pop(code, None)
        if pc and pc['exp'] >= time.time():
            def pair():
                with db.connect() as conn:
                    r = db.row(conn.execute('SELECT id, name FROM drone_bridges WHERE id = ? AND active = 1', (pc['bridge_id'],)))
                    if not r:
                        return None, None
                    k = issue_key(conn, r['id'])
                    db.audit(conn, None, 'Dron köprüsü eşleştirildi', 'drone_bridge', r['id'], f"{r['name']} · {first.get('host') or ''}")
                    conn.commit()
                    return r, k
            row, issued = await _db(pair)
    if row is None:
        _note_fail(ip)
        def rej():
            with db.connect() as conn:
                db.audit(conn, None, 'Dron köprüsü kimlik reddi', 'drone_bridge', None, f"{ip} · {first.get('host') or ''}")
                conn.commit()
        await _db(rej)
        await _safe_send(ws, {'t': 'auth_err', 'code': 4403})
        await ws.close(code=4403)
        return
    caps = [str(c)[:30] for c in (first.get('caps') or []) if isinstance(c, str)][:32] if isinstance(first.get('caps'), list) else []
    bridge = Bridge(ws, row, str(first.get('host') or '')[:120], str(first.get('platform') or '')[:40], str(first.get('bridge_ver') or '')[:40], caps)
    prev = BRIDGES.get(bridge.id)
    BRIDGES[bridge.id] = bridge
    if prev is not None and prev.ws is not ws:   # aynı köprü ikinci kez: eski bağlantı kapatılır
        prev.closing = 'KAPANDI'
        try:
            await prev.ws.close(code=4409)
        except Exception:   # noqa: BLE001
            pass
    bridge.session_id, bridge.tlog_path = await _open_session(bridge)
    hello = {'t': 'auth_ok', 'v': PROTO, 'bridge_id': bridge.id, 'name': bridge.name, 'server_time': db.now(), 'session_id': bridge.session_id}
    if issued:
        hello['key'] = issued   # yalnız eşleştirmede, bir kez
    await _safe_send(ws, hello)
    _broadcast({'t': 'bridge', 'bridge_id': bridge.id, 'online': True, 'info': bridge.info()})
    status = 'KOPTU'
    error = None
    try:
        while True:
            m = await ws.receive()
            if m.get('type') == 'websocket.disconnect':
                break
            bridge.last_seen = time.time()
            if m.get('bytes') is not None:
                data = m['bytes']
                if bridge.log:
                    await _log_chunk(bridge, data)
                else:
                    bridge.packets += 1
                    _tlog_write(bridge, data)
                    _feed_mavlink(bridge, data)
            elif m.get('text'):
                try:
                    msg = json.loads(m['text'])
                except ValueError:
                    continue
                t = msg.get('t')
                if t == 'ping':
                    await _safe_send(ws, {'t': 'pong', 'server_time': db.now()})
                elif t == 'res':
                    ent = _pending.get(msg.get('rid'))
                    if ent and not ent[0].done():
                        ent[0].set_result(msg)
                elif t == 'log_begin':
                    await _log_begin(bridge, msg)
                elif t == 'log_end':
                    await _log_end(bridge)
                elif t == 'status':   # cihazda çözümlenmiş durum (isteğe bağlı): doğrudan dağıt
                    sysid = int(msg.get('sysid') or 1)
                    st = bridge.drones.setdefault(sysid, DroneState(sysid))
                    st.d.update({k: v for k, v in (msg.get('state') or {}).items() if k in st.d})
                    st.d['updated'] = time.time(); st.dirty = True
                    _emit(bridge, st, force=True)
                elif t == 'event':
                    _broadcast({'t': 'event', 'bridge_id': bridge.id, 'sysid': msg.get('sysid'), 'text': str(msg.get('text') or '')[:300],
                                'severity': msg.get('severity')}, bridge.id)
    except (WebSocketDisconnect, Exception) as e:   # noqa: BLE001
        error = str(e)[:200] if not isinstance(e, WebSocketDisconnect) else None
    finally:
        if bridge.closing:
            status = bridge.closing
        current = BRIDGES.get(bridge.id) is bridge   # aynı köprü yeni bağlantıyla devam ediyorsa (4409) çevrimdışı sayılmaz
        if current:
            BRIDGES.pop(bridge.id, None)
            for rid, (fut, _vw, bid) in list(_pending.items()):
                if not fut.done() and bid == bridge.id:
                    fut.set_exception(RuntimeError('Köprü bağlantısı koptu'))
        if bridge.log:
            try:
                bridge.log['f'].close(); Path(bridge.log['path']).unlink(missing_ok=True)
            except OSError:
                pass
        if bridge.tlog:
            try:
                bridge.tlog.close()
            except OSError:
                pass
        if current:   # izleyicilere senkron (görev iptal edilmişse bile ulaşır)
            _broadcast({'t': 'bridge', 'bridge_id': bridge.id, 'online': False, 'status': status})
        _close_session(bridge, status, error, mark_offline=current)


def _feed_mavlink(bridge, data):
    try:
        msgs = bridge.parser.parse_buffer(data) or []
    except Exception:   # noqa: BLE001 — bozuk çerçeve: atla
        return
    for m in msgs:
        try:
            sysid = m.get_srcSystem()
        except Exception:   # noqa: BLE001
            continue
        if m.get_type() == 'BAD_DATA':
            continue
        if m.get_type() == 'STATUSTEXT':
            text = str(m.text).rstrip('\x00')[:200]
            st = bridge.drones.setdefault(sysid, DroneState(sysid))
            st.d['last_text'] = text
            if text.startswith(('PreArm', 'Arm:')):   # ARM CHECK rozetleri: son 8 ön-kol uyarısı
                st.d['prearm'] = (st.d['prearm'] + [text])[-8:]
            last = st.texts[-1] if st.texts else None   # ARM CHECK mesajlar sekmesi biçimi (arm_check.js acMesajCiz): ts, metin, sev, tekrar
            if last and last['metin'] == text and last['sev'] == m.severity:
                last['tekrar'] += 1; last['ts'] = time.time()
            else:
                st.texts = (st.texts + [{'ts': time.time(), 'metin': text, 'sev': m.severity, 'tekrar': 1}])[-50:]
            _broadcast({'t': 'event', 'bridge_id': bridge.id, 'sysid': sysid, 'text': text, 'severity': m.severity, 'ts': time.time()}, bridge.id)
            console_line(bridge, sysid, 'STATUS', text, 'hata' if m.severity <= 3 else 'uyari' if m.severity == 4 else 'basari' if m.severity == 5 else 'bilgi')
            continue
        st = bridge.drones.setdefault(sysid, DroneState(sysid))
        if st.feed(m):
            _emit(bridge, st)
        elif st.param_buf and st.param_timer is None:   # PARAM_VALUE'lar 200 ms'de bir toplu gider (binlerce parametre kuyruğu boğmasın)
            st.param_timer = asyncio.get_running_loop().call_later(0.2, _flush_params, bridge, st)


def _flush_params(bridge, st):
    st.param_timer = None
    if not st.param_buf:
        return
    items, st.param_buf = st.param_buf, []
    _broadcast({'t': 'params', 'bridge_id': bridge.id, 'sysid': st.d['sysid'], 'items': items, 'count': items[-1][3], 'cached': len(st.params)}, bridge.id)


def _emit(bridge, st, force=False):
    """En çok STATUS_HZ paket/sn; sınıra takılan güncelleme kaybolmaz, süre dolunca son durum yayınlanır."""
    wait = 1.0 / STATUS_HZ - (time.time() - st.emitted)
    if not force and wait > 0:
        if st.timer is None:
            st.timer = asyncio.get_running_loop().call_later(wait, _flush, bridge, st)
        return
    _flush(bridge, st)


def _flush(bridge, st):
    if st.timer is not None:
        st.timer.cancel(); st.timer = None
    st.emitted = time.time(); st.dirty = False
    st.d['ready'] = ready_summary(st)
    _broadcast({'t': 'status', 'bridge_id': bridge.id, 'sysid': st.d['sysid'], 'state': st.d}, bridge.id)


# ---------------- Haberleşme konsolu ve ARM CHECK (sunucu-yalnız; köprüye gitmez) ----------------
def console_line(bridge, sysid, tag, text, sev='bilgi'):
    """Dron (sysid) başına halka tampon + izleyicilere yayın. Ardışık aynı satır birleştirilir (repeat ×N, fresh False)."""
    st = bridge.drones.setdefault(int(sysid or 0), DroneState(int(sysid or 0)))
    now = time.time()
    last = st.console[-1] if st.console else None
    if last and last['tag'] == tag and last['text'] == text:
        last['repeat'] += 1; last['ts'] = now
        line, fresh = last, False
    else:
        line = {'ts': now, 'tag': tag, 'text': text, 'sev': sev, 'repeat': 1}
        st.console = (st.console + [line])[-CONSOLE_MAX:]
        fresh = True
    _broadcast({'t': 'console', 'bridge_id': bridge.id, 'sysid': st.d['sysid'], 'fresh': fresh, **line}, bridge.id)


def ready_summary(st):
    """Kart rozeti / PFD köşe kutusu için uçuşa hazırlık özeti: {hazir, uyari, sebep}."""
    d = st.d
    if d['armed']:
        return {'hazir': None, 'uyari': 0, 'sebep': 'ARM · uçuşta'}
    fails = [k for k, v in (d['sensors'] or {}).items() if v == 'fail']
    sebep = d['prearm'][-1] if d['prearm'] else (f'Sensör: {fails[0]}' if fails else None)
    if sebep is None and (d['fix'] is None or d['fix'] < 3):
        sebep = 'GPS fix yok'
    return {'hazir': sebep is None, 'uyari': len(fails), 'sebep': sebep}


def arm_check_report(st):
    """ARM CHECK penceresi (GÖKTUNGU arm_check.js) için rapor: PreArm mesajları, sensör sağlığı, konum, güç, kumanda."""
    d = st.d; now = time.time()
    maddeler = []
    for t in d['prearm']:
        maddeler.append({'grup': 'prearm', 'ad': t, 'durum': 'hata', 'aciklama': 'Otopilot ön-kol denetimi', 'oncelik': 1})
    for k, v in (d['sensors'] or {}).items():
        maddeler.append({'grup': 'sensor', 'ad': k, 'durum': 'tamam' if v == 'ok' else 'hata', 'aciklama': 'SYS_STATUS sensör sağlığı', 'oncelik': 2})
    fix = d['fix']
    maddeler.append({'grup': 'konum', 'ad': 'GPS fix', 'durum': 'bilinmiyor' if fix is None else 'tamam' if fix >= 3 else 'uyari' if fix == 2 else 'hata',
                     'aciklama': f"fix {fix} · {d['sats'] if d['sats'] is not None else '?'} uydu · HDOP {d['hdop'] if d['hdop'] is not None else '?'}", 'oncelik': 1})
    if d['hdop'] is not None and d['hdop'] > 2:
        maddeler.append({'grup': 'konum', 'ad': 'HDOP', 'durum': 'uyari', 'aciklama': f"HDOP {d['hdop']} > 2", 'oncelik': 3})
    maddeler.append({'grup': 'konum', 'ad': 'HOME', 'durum': 'tamam' if d['home_lat'] else 'uyari', 'aciklama': 'Ev konumu alındı' if d['home_lat'] else 'HOME_POSITION gelmedi', 'oncelik': 0})
    pct = d['batt_pct']
    maddeler.append({'grup': 'guc', 'ad': 'Batarya', 'durum': 'bilinmiyor' if d['volt'] is None else 'hata' if (pct is not None and pct < 20) else 'uyari' if (pct is not None and pct < 40) else 'tamam',
                     'aciklama': f"{d['volt']} V" + (f" · %{pct}" if pct is not None else ''), 'oncelik': 1})
    rc_ok = st.rc_at is not None and now - st.rc_at < 3
    maddeler.append({'grup': 'rc', 'ad': 'Kumanda', 'durum': 'tamam' if rc_ok else 'bilinmiyor', 'aciklama': 'RC_CHANNELS alınıyor' if rc_ok else 'Kumanda verisi gelmiyor', 'oncelik': 2})
    hb_ok = d['last_hb'] is not None and now - d['last_hb'] < 5
    maddeler.append({'grup': 'sensor', 'ad': 'Kalp atışı', 'durum': 'tamam' if hb_ok else 'hata', 'aciklama': 'Telemetri canlı' if hb_ok else 'Kalp atışı yok', 'oncelik': 0})
    for x in maddeler:   # GÖKTUNGU arm_check.js acDenetimCiz 'deger' alanını gösterir
        x['deger'] = x['aciklama']
    kritik = sum(1 for x in maddeler if x['durum'] == 'hata'); uyari = sum(1 for x in maddeler if x['durum'] == 'uyari')
    sebep = next((x['ad'] for x in maddeler if x['durum'] == 'hata'), None) or next((x['ad'] for x in maddeler if x['durum'] == 'uyari'), None)
    return {'bulundu': True, 'sysid': d['sysid'], 'armed': d['armed'], 'mod': d['mode'],
            'ozet': {'hazir': kritik == 0, 'uyari': uyari, 'kritik': kritik, 'sebep': sebep},
            'maddeler': maddeler, 'parametreler': [], 'mesajlar': list(st.texts), 'ts': now}


# ---------------- Uçuş sonrası .bin aktarımı ----------------
async def _log_begin(bridge, msg):
    size = int(msg.get('size') or 0)
    name = str(msg.get('name') or 'flight.bin')[:120]
    if bridge.log or size <= 0 or size > LOG_MAX or not name.lower().endswith(('.bin', '.log')):
        await _safe_send(bridge.ws, {'t': 'log_err', 'error': 'Geçersiz log başlangıcı (boyut/ad) ya da aktarım sürüyor'})
        return
    d = config.UPLOAD_DIR / 'flightlogs'
    d.mkdir(parents=True, exist_ok=True)
    rel = f"flightlogs/{secrets.token_hex(12)}{Path(name).suffix.lower()}"
    bridge.log = {'f': open(config.UPLOAD_DIR / rel, 'wb'), 'h': hashlib.sha256(), 'size': size, 'got': 0, 'name': name,
                  'sha': str(msg.get('sha256') or '').lower(), 'path': str(config.UPLOAD_DIR / rel), 'rel': rel,
                  'flight_id': msg.get('flight_id'), 'task_id': msg.get('task_id')}
    await _safe_send(bridge.ws, {'t': 'log_ready', 'name': name})


async def _log_chunk(bridge, data):
    lg = bridge.log
    lg['f'].write(data); lg['h'].update(data); lg['got'] += len(data)
    if lg['got'] > lg['size']:
        lg['f'].close(); Path(lg['path']).unlink(missing_ok=True); bridge.log = None
        await _safe_send(bridge.ws, {'t': 'log_err', 'error': 'Bildirilen boyut aşıldı'})


async def _log_end(bridge):
    lg = bridge.log
    if not lg:
        return
    bridge.log = None
    lg['f'].close()
    digest = lg['h'].hexdigest()
    if lg['got'] != lg['size'] or (lg['sha'] and lg['sha'] != digest):
        Path(lg['path']).unlink(missing_ok=True)
        await _safe_send(bridge.ws, {'t': 'log_err', 'error': 'Boyut ya da sağlama (sha256) uyuşmuyor'})
        return

    def store():
        from . import flight_analysis
        with db.connect() as conn:
            s = db.row(conn.execute('SELECT started_by, task_id, flight_id FROM drone_bridge_sessions WHERE id = ?', (bridge.session_id,))) or {}
            flight_id = lg.get('flight_id') or s.get('flight_id')
            task_id = lg.get('task_id') or s.get('task_id')
            if flight_id and not task_id:
                r = conn.execute('SELECT task_id FROM field_flights WHERE id = ?', (flight_id,)).fetchone()
                task_id = r[0] if r else None
            cur = conn.execute('''INSERT INTO flight_logs (task_id, flight_id, file, file_name, size, uploaded_by, uploaded_at, source, note)
                                  VALUES (?,?,?,?,?,?,?,'BRIDGE',?)''',
                               (task_id, flight_id, lg['rel'], lg['name'], lg['got'], s.get('started_by'), db.now(), f'Köprü: {bridge.name}'))
            db.audit(conn, s.get('started_by'), 'Dron köprüsünden uçuş logu alındı', 'flight_log', cur.lastrowid, f"{lg['name']} · {lg['got']} bayt")
            conn.commit()
            lid = cur.lastrowid
        flight_analysis.start(lid)
        return lid
    lid = await _db(store)
    await _safe_send(bridge.ws, {'t': 'log_ack', 'flight_log_id': lid})
    _broadcast({'t': 'log', 'bridge_id': bridge.id, 'flight_log_id': lid, 'name': lg['name']}, bridge.id)
    for sysid in list(bridge.drones) or [0]:
        console_line(bridge, sysid, 'LOG', f"Uçuş logu alındı: {lg['name']} (#{lid})", 'basari')


# ---------------- Görev bağlamı (Faz 1): görevin uçuşları, köprüleri ve sanal dronları ----------------
_loc_geo = None   # field_locations.lat/lon sütunları var mı (None: henüz bakılmadı)


def _location_geo_cols(conn):
    """field_locations tablosunda konum sütunu (lat + lon|lng) varsa adlarını döndürür; yoksa None (live.task.lat/lon null)."""
    global _loc_geo
    if _loc_geo is None:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(field_locations)')}
        lon = 'lon' if 'lon' in cols else 'lng' if 'lng' in cols else None
        _loc_geo = ('lat', lon) if 'lat' in cols and lon else ()
    return _loc_geo or None


def parse_link(txt):
    """field_flights.link JSON metni → sözlük (bozuksa None)."""
    if not txt:
        return None
    try:
        v = json.loads(txt) if isinstance(txt, str) else txt
    except ValueError:
        return None
    return v if isinstance(v, dict) and v.get('type') else None


def task_live(conn, task_id):
    """Görev + uçuş satırları (REST /api/field/tasks/{id}/live ve WS hello.task/flights aynı biçim).
    flights[]: id, order_id, drone_id, label (kuyruk no | dron kodu), name (ürün adı | dron adı), protocol (sipariş uçakları
    'mavlink'), sysid, bridge_id, bridge_name, bridge_online, link (parse edilmiş), sim_bridge_id (sanal ise -drone_id)."""
    geo = _location_geo_cols(conn)
    geo_sql = f', loc.{geo[0]} AS lat, loc.{geo[1]} AS lon' if geo else ', NULL AS lat, NULL AS lon'
    task = db.row(conn.execute(f'''SELECT t.id, t.code, t.status, loc.name AS location_name{geo_sql}
                                   FROM field_tasks t LEFT JOIN field_locations loc ON loc.id = t.location_id WHERE t.id = ?''', (task_id,)))
    if not task:
        return None, []
    rows = db.rows(conn.execute(
        '''SELECT f.id, f.order_id, f.drone_id, f.bridge_id, f.sysid, f.link, o.queue_no, o.code AS order_code, p.name AS product_name,
                  d.code AS drone_code, d.name AS drone_name, d.protocol AS drone_protocol, d.model AS drone_model, b.name AS bridge_name
           FROM field_flights f
           LEFT JOIN orders o ON o.id = f.order_id LEFT JOIN products p ON p.id = o.product_id
           LEFT JOIN drone_drones d ON d.id = f.drone_id LEFT JOIN drone_bridges b ON b.id = f.bridge_id
           WHERE f.task_id = ? ORDER BY o.queue_no, d.code, f.id''', (task_id,)))
    flights = []
    for r in rows:
        protocol = (r['drone_protocol'] or 'mavlink') if r['drone_id'] else 'mavlink'
        flights.append({'id': r['id'], 'order_id': r['order_id'], 'drone_id': r['drone_id'],
                        'label': r['queue_no'] or r['order_code'] or r['drone_code'] or f"#{r['id']}",
                        'name': r['product_name'] or r['drone_name'], 'protocol': protocol, 'sysid': r['sysid'],
                        'bridge_id': r['bridge_id'], 'bridge_name': r['bridge_name'], 'bridge_online': r['bridge_id'] in BRIDGES,
                        'drone_model': r['drone_model'], 'link': parse_link(r['link']), 'sim_bridge_id': -r['drone_id'] if protocol == 'sanal' and r['drone_id'] else None})
    return task, flights


def _task_allowed(flights):
    out = set()
    for f in flights:
        if f['bridge_id'] is not None:
            out.add(int(f['bridge_id']))
        if f['sim_bridge_id'] is not None:
            out.add(int(f['sim_bridge_id']))
    return out


def _sim_home(conn, task):
    """Sanal dronun ev konumu: görev yeri lat/lon → ilk aktif rota merkezi → Ankara (39.9, 32.8)."""
    if task and task.get('lat') is not None and task.get('lon') is not None:
        return float(task['lat']), float(task['lon'])
    c = conn.execute('SELECT lat, lon FROM drone_route_centers WHERE active = 1 ORDER BY id LIMIT 1').fetchone()
    return (float(c[0]), float(c[1])) if c else (39.9, 32.8)


def _task_status(task_id):
    with db.connect() as conn:
        r = conn.execute('SELECT status FROM field_tasks WHERE id = ?', (task_id,)).fetchone()
    return r[0] if r else None


COPTER_MODES = {'STABILIZE': 0, 'ALT_HOLD': 2, 'AUTO': 3, 'GUIDED': 4, 'LOITER': 5, 'RTL': 6, 'LAND': 9, 'POSHOLD': 16}
NAV_TAKEOFF, NAV_WAYPOINT, NAV_LOITER_TIME, NAV_RTL, NAV_LAND, DO_JUMP = 22, 16, 19, 20, 21, 177


class SimDrone:
    """SANAL DRON: görevin protocol='sanal' uçuşu için sunucu içi sahte köprü. Bridge ile aynı yüzeyi taşır (id, name, drones,
    caps, info) — _emit / console_line / arm_check_report değişmeden çalışır; bridge_id = -drone_id (negatif), sysid = uçuş
    sysid || 1. 5 Hz tick (asyncio görevi) DroneState alanlarını üretir; komutlar send_command'dan (bridge_id < 0) gelir.
    Kinematik: tırmanma 3 m/s, iniş 2 m/s, yatay 12 m/s (goto/rtl/auto). Batarya uçarken 0,03 %/sn düşer.
    İzleyici kalmayınca SIM_IDLE sonra, görev açık (BASLANGIC/GOREVDE) değilse hemen durur."""
    TICK, CLIMB, DESCENT, SPEED = 0.2, 3.0, 2.0, 12.0

    def __init__(self, task_id, flight, home):
        self.task_id, self.drone_id, self.flight_id = task_id, int(flight['drone_id']), flight['id']
        self.id = -self.drone_id
        self.name = f"Sanal · {flight['label']}"
        self.sysid = int(flight.get('sysid') or 1)
        self.host, self.platform, self.ver = 'sunucu', 'sanal', f'sim-{PROTO}'
        self.caps = ['set_home', 'mission_set_current', 'altitude_change', 'arm_force']
        self.session_id, self.packets, self.connected_at, self.last_seen = None, 0, db.now(), time.time()
        self.closing, self.log, self.tlog, self.tlog_path = None, None, None, None
        self.st = DroneState(self.sysid)
        self.drones = {self.sysid: self.st}
        self.home = (float(home[0]), float(home[1]))
        self.lat, self.lon, self.alt = self.home[0], self.home[1], 0.0
        self.hdg, self.gs, self.vz = 0.0, 0.0, 0.0
        self.mode, self.phase = 'STABILIZE', 'idle'   # phase: idle | takeoff | goto | auto | loiter | rtl | land
        self.target = None          # (lat, lon, alt_rel)
        self.hold_until = None      # LOITER_TIME / WAYPOINT bekleme bitişi
        self.mission, self.seq = [], 0
        self.batt = 100.0
        self.last_viewer = time.time()
        self.task = None
        d = self.st.d
        d.update({'type': 2, 'type_name': MAV_TYPES[2], 'autopilot': 3, 'armed': False, 'fix': 6, 'sats': 12, 'hdop': 0.7,
                  'home_lat': self.home[0], 'home_lon': self.home[1], 'home_alt': 900.0, 'ekf_flags': 831, 'mission_count': 0,
                  'sensors': {k: 'ok' for k in ('gyro', 'accel', 'mag', 'baro', 'gps', 'rc', 'ahrs', 'battery', 'prearm', 'logging')}})
        self.st.rc_at = time.time()
        self._state()

    # --- Bridge yüzeyi ---
    def info(self):
        return {'bridge_id': self.id, 'name': self.name, 'host': self.host, 'platform': self.platform, 'bridge_ver': self.ver, 'caps': self.caps,
                'connected_at': self.connected_at, 'packets': self.packets, 'session_id': None, 'sim': True, 'drone_id': self.drone_id,
                'task_id': self.task_id, 'flight_id': self.flight_id, 'drones': {str(s): st.d for s, st in self.drones.items()}}

    # --- yardımcılar ---
    def _event(self, text, severity=6):
        """STATUSTEXT benzeri olay: event + console + ARM CHECK mesaj listesi."""
        now = time.time()
        self.st.d['last_text'] = text
        self.st.texts = (self.st.texts + [{'ts': now, 'metin': text, 'sev': severity, 'tekrar': 1}])[-50:]
        _broadcast({'t': 'event', 'bridge_id': self.id, 'sysid': self.sysid, 'text': text, 'severity': severity, 'ts': now}, self.id)
        console_line(self, self.sysid, 'STATUS', text, 'hata' if severity <= 3 else 'uyari' if severity == 4 else 'basari' if severity == 5 else 'bilgi')

    def _set_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            self._event(f'Mode {mode}', 6)

    def _dist_to(self, lat, lon):
        return _dist_m(self.lat, self.lon, lat, lon)

    def _move_toward(self, lat, lon, dt):
        """Hedefe doğru SPEED ile ilerler; hedefe kalan mesafeyi döndürür."""
        import math
        dist = self._dist_to(lat, lon)
        if dist < 0.05:
            self.gs = 0.0
            return 0.0
        p1, p2 = math.radians(self.lat), math.radians(lat)
        dl = math.radians(lon - self.lon)
        brg = math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360
        step = min(dist, self.SPEED * dt)
        self.hdg = brg
        self.gs = step / dt
        self.lat += step * math.cos(math.radians(brg)) / 111320.0
        self.lon += step * math.sin(math.radians(brg)) / (111320.0 * max(0.05, math.cos(math.radians(self.lat))))
        self.st.d['dist_m'] = round(self.st.d['dist_m'] + step, 1)
        return dist - step

    def _alt_toward(self, alt, dt):
        """İrtifayı hedefe götürür (tırmanma CLIMB, alçalma DESCENT); kalan farkı döndürür."""
        diff = alt - self.alt
        if abs(diff) < 0.05:
            self.vz = 0.0; self.alt = alt
            return 0.0
        rate = self.CLIMB if diff > 0 else self.DESCENT
        step = min(abs(diff), rate * dt)
        self.alt += step if diff > 0 else -step
        self.vz = step / dt if diff > 0 else -step / dt
        return alt - self.alt

    def _disarm(self, text='Disarming motors'):
        self.st.d['armed'] = False; self.st.armed_at = None
        self.gs = self.vz = 0.0; self.alt = 0.0
        self.phase, self.target, self.hold_until = 'idle', None, None
        self._event(text, 6)

    def _mission_next(self):
        """AUTO: sıradaki görev öğesini hedef yapar; bitince LOITER."""
        while True:
            if self.seq >= len(self.mission):
                self.phase = 'loiter'; self.target = None
                self._set_mode('LOITER')
                self._event('Mission complete', 6)
                return
            it = self.mission[self.seq]
            cmd = it['command']
            self.st.d['mission_seq'] = self.seq
            if cmd == DO_JUMP:
                tgt = int(it.get('param1') or 0)
                rep = it.get('param2')
                if rep is None or rep < 0 or it.setdefault('_done', 0) < rep:
                    it['_done'] = it.get('_done', 0) + 1
                    self.seq = tgt if 0 <= tgt < len(self.mission) else len(self.mission)
                else:
                    self.seq += 1
                continue
            if cmd == NAV_TAKEOFF:
                self.target = (self.lat, self.lon, float(it.get('z') or 10))
                self.phase = 'auto'
                return
            if cmd in (NAV_WAYPOINT, NAV_LOITER_TIME):
                lat, lon = (it['lat'], it['lon']) if (it['lat'] or it['lon']) else (self.lat, self.lon)   # x/y 0: yerinde (ör. yalnız irtifa)
                self.target = (lat, lon, float(it.get('z') or self.alt or 10))
                self.phase = 'auto'
                return
            if cmd == NAV_RTL:
                self._rtl(auto=True)
                return
            if cmd == NAV_LAND:
                if it.get('lat') and it.get('lon'):
                    self.target = (it['lat'], it['lon'], self.alt)
                    self.phase = 'auto'
                else:
                    self.phase = 'land'; self.target = None
                    self._set_mode('LAND')
                return
            self.seq += 1   # bilinmeyen öğe: atla

    def _rtl(self, auto=False):
        self.target = (self.home[0], self.home[1], max(self.alt, 15.0))
        self.phase = 'rtl'
        if not auto:
            self._set_mode('RTL')
        self._event('RTL: returning home', 6)

    # --- tick ---
    def _step(self, dt):
        d = self.st.d
        now = time.time()
        if not d['armed']:
            self.gs = self.vz = 0.0
        elif self.phase == 'takeoff':
            if self._alt_toward(self.target[2], dt) <= 0.05:
                self.phase = 'loiter'; self.target = None
                self._event('Takeoff complete', 6)
        elif self.phase in ('goto', 'rtl', 'auto'):
            rem = self._move_toward(self.target[0], self.target[1], dt)
            vrem = self._alt_toward(self.target[2], dt)
            d['wp_dist'] = int(rem)
            if rem <= 0.05 and abs(vrem) <= 0.05:
                if self.phase == 'goto':
                    self.phase = 'loiter'; self.target = None
                    self._event('Reached destination', 6)
                elif self.phase == 'rtl':
                    self.phase = 'land'; self.target = None
                    if self.mode != 'RTL':
                        self._set_mode('LAND')
                    self._event('RTL: landing', 6)
                else:   # auto: öğe tamamlandı
                    it = self.mission[self.seq] if self.seq < len(self.mission) else {}
                    hold = float(it.get('param1') or 0) if it.get('command') in (NAV_WAYPOINT, NAV_LOITER_TIME) else 0.0
                    if it.get('command') == NAV_LAND:
                        self.phase = 'land'; self.target = None
                        self._set_mode('LAND')
                    elif hold > 0 and self.hold_until is None:
                        self.hold_until = now + hold
                    elif self.hold_until is None or now >= self.hold_until:
                        self.hold_until = None
                        self.seq += 1
                        self._mission_next()
        elif self.phase == 'land':
            if self._alt_toward(0.0, dt) <= 0.05:
                self._disarm()
        else:   # loiter / idle (havada bekleme)
            self.gs = 0.0; self.vz = 0.0
        if d['armed']:
            self.batt = max(0.0, self.batt - 0.03 * dt)
            d['flight_s'] = int(now - self.st.armed_at) if self.st.armed_at else 0
        self._state()

    def _state(self):
        import math
        d = self.st.d; now = time.time()
        moving = self.gs > 0.1
        d.update({'lat': round(self.lat, 7), 'lon': round(self.lon, 7), 'alt': round(900.0 + self.alt, 1), 'alt_rel': round(self.alt, 1),
                  'hdg': round(self.hdg, 1), 'groundspeed': round(self.gs, 1), 'airspeed': round(self.gs, 1), 'climb': round(self.vz, 1),
                  'vx': round(self.gs * math.cos(math.radians(self.hdg)), 1), 'vy': round(self.gs * math.sin(math.radians(self.hdg)), 1), 'vz': round(-self.vz, 1),
                  'throttle': 0 if not d['armed'] else 60 if moving or abs(self.vz) > 0.1 else 45,
                  'roll': round(2.0 * math.sin(now), 1) if d['armed'] and self.alt > 0.1 else 0.0,
                  'pitch': -8.0 if moving else 0.0, 'yaw': round(self.hdg, 1),
                  'volt': round(21.0 + 4.2 * self.batt / 100, 2), 'curr': 18.0 if (d['armed'] and self.alt > 0.1) else 1.5 if d['armed'] else 0.4,
                  'batt_pct': int(self.batt), 'mode': self.mode, 'mode_num': COPTER_MODES.get(self.mode, 0),
                  'last_hb': now, 'updated': now, 'msgs': d['msgs'] + 1})
        if self.phase not in ('goto', 'rtl', 'auto'):
            d['wp_dist'] = None
        self.packets += 1

    def _publish(self):
        self.st.dirty = True
        _emit(self, self.st)

    # --- komutlar (send_command → bridge_id < 0) ---
    def command(self, name, params):
        """Senkron komut işleyici; {'ok', 'result'?, 'error'?} döndürür (köprü res çerçevesiyle aynı)."""
        p = params or {}
        d = self.st.d
        try:
            if name == 'arm':
                if d['armed']:
                    return {'ok': False, 'error': 'Zaten ARM'}
                d['armed'] = True; self.st.armed_at = time.time(); d['dist_m'] = 0.0; d['prearm'] = []
                self.home = (self.lat, self.lon); d['home_lat'], d['home_lon'] = self.home
                self._event('Arming motors', 6)
                return {'ok': True}
            if name == 'disarm':
                if not d['armed']:
                    return {'ok': False, 'error': 'Zaten DISARM'}
                if self.alt > 0.5:
                    return {'ok': False, 'error': 'Havada disarm edilemez (önce LAND)'}
                self._disarm()
                return {'ok': True}
            if name == 'takeoff':
                if not d['armed']:
                    return {'ok': False, 'error': 'Önce ARM edin'}
                alt = float(p.get('alt_rel_m') or 30)
                if not 1 <= alt <= 1000:
                    return {'ok': False, 'error': 'Kalkış irtifası 1…1000 m'}
                self._set_mode('GUIDED')
                self.target = (self.lat, self.lon, alt); self.phase = 'takeoff'; self.hold_until = None
                self._event(f'Takeoff to {alt:g} m', 6)
                return {'ok': True}
            if name == 'land':
                if not d['armed']:
                    return {'ok': False, 'error': 'Dron yerde'}
                self._set_mode('LAND'); self.phase = 'land'; self.target = None
                return {'ok': True}
            if name == 'rtl':
                if not d['armed']:
                    return {'ok': False, 'error': 'Dron yerde'}
                self._rtl()
                return {'ok': True}
            if name == 'goto':
                if not d['armed'] or self.alt < 0.5:
                    return {'ok': False, 'error': 'Önce kalkış yapın'}
                lat, lon = float(p['lat']), float(p['lon'])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    return {'ok': False, 'error': 'Geçersiz konum'}
                alt = float(p.get('alt_rel_m') or self.alt)
                self._set_mode('GUIDED')
                self.target = (lat, lon, alt); self.phase = 'goto'; self.hold_until = None
                return {'ok': True}
            if name == 'altitude_change':
                if not d['armed'] or self.alt < 0.5:
                    return {'ok': False, 'error': 'Önce kalkış yapın'}
                alt = float(p.get('alt_rel_m') or self.alt)
                self._set_mode('GUIDED')
                self.target = (self.lat, self.lon, alt); self.phase = 'goto'
                return {'ok': True}
            if name == 'set_mode':
                mode = str(p.get('mode') or '').upper()
                if mode not in COPTER_MODES:
                    return {'ok': False, 'error': f'Bilinmeyen mod: {mode}'}
                if mode == 'AUTO':
                    if not self.mission:
                        return {'ok': False, 'error': 'Yüklü görev yok'}
                    if not d['armed']:
                        return {'ok': False, 'error': 'Önce ARM edin'}
                    self._set_mode('AUTO'); self.hold_until = None
                    self._mission_next()
                elif mode == 'RTL':
                    if d['armed']:
                        self._rtl()
                    else:
                        self._set_mode('RTL')
                elif mode == 'LAND':
                    self._set_mode('LAND')
                    if d['armed']:
                        self.phase = 'land'; self.target = None
                else:   # STABILIZE / ALT_HOLD / GUIDED / LOITER / POSHOLD: dur, havada bekle
                    self._set_mode(mode)
                    if d['armed']:
                        self.phase = 'loiter'; self.target = None; self.hold_until = None
                return {'ok': True}
            if name == 'mission_upload':
                items = p.get('items') or []
                if not isinstance(items, list) or len(items) > 500:
                    return {'ok': False, 'error': 'items listesi gerekli (≤ 500)'}
                mission = []
                for it in items:
                    mission.append({'seq': int(it.get('seq', len(mission))), 'frame': int(it.get('frame', 6)), 'command': int(it.get('command', NAV_WAYPOINT)),
                                    'param1': float(it.get('param1') or 0), 'param2': float(it.get('param2') or 0),
                                    'x': int(it.get('x') or 0), 'y': int(it.get('y') or 0), 'z': float(it.get('z') or 0),
                                    'lat': int(it.get('x') or 0) / 1e7, 'lon': int(it.get('y') or 0) / 1e7})
                self.mission, self.seq = mission, 0
                d['mission_count'] = len(mission); d['mission_seq'] = 0
                self._event(f'Mission uploaded: {len(mission)} items', 6)
                return {'ok': True, 'result': {'count': len(mission)}}
            if name == 'mission_download':
                return {'ok': True, 'result': {'items': [{k: v for k, v in it.items() if k not in ('lat', 'lon', '_done')} for it in self.mission]}}
            if name == 'mission_set_current':
                seq = int(p.get('seq') or 0)
                if not 0 <= seq < max(1, len(self.mission)):
                    return {'ok': False, 'error': 'Geçersiz seq'}
                self.seq = seq; d['mission_seq'] = seq
                if self.mode == 'AUTO' and d['armed']:
                    self._mission_next()
                return {'ok': True}
            if name == 'set_home':
                if p.get('lat') is not None and p.get('lon') is not None:
                    self.home = (float(p['lat']), float(p['lon']))
                else:
                    self.home = (self.lat, self.lon)
                d['home_lat'], d['home_lon'] = self.home
                self._event('Home set', 6)
                return {'ok': True}
            if name in ('link_open', 'link_close', 'disconnect'):
                return {'ok': True, 'result': {'sim': True}}   # sanal dron her zaman bağlı
            if name in ('param_list', 'param_get', 'param_set', 'reboot') or name.startswith(('kalib_', 'motor_test', 'log_')):
                return {'ok': False, 'error': 'Sanal dron bu komutu desteklemiyor'}
            return {'ok': False, 'error': 'Bilinmeyen komut'}
        except (KeyError, TypeError, ValueError) as e:
            return {'ok': False, 'error': f'Geçersiz parametre: {e}'}

    # --- yaşam döngüsü ---
    async def run(self):
        n = 0
        try:
            while True:
                await asyncio.sleep(self.TICK)
                self._step(self.TICK)
                self._publish()
                n += 1
                if n % 25 == 0:   # 5 sn: izleyici var mı
                    now = time.time()
                    if any(v.task_id == self.task_id for v in VIEWERS.values()):
                        self.last_viewer = now
                    elif now - self.last_viewer > SIM_IDLE:
                        break
                if n % 150 == 0 and await _db(_task_status, self.task_id) not in OPEN_TASK:   # 30 sn: görev kapandı/iptal
                    break
        except asyncio.CancelledError:
            pass
        except Exception:   # noqa: BLE001
            pass
        finally:
            if SIMS.get(self.id) is self:
                SIMS.pop(self.id, None)
                _broadcast({'t': 'bridge', 'bridge_id': self.id, 'online': False, 'status': 'KAPANDI'}, self.id)


class SitlDrone:
    """SANAL DRON (GÖKTUNGU birebir): görevin protocol='sanal' uçuşu için GERÇEK ArduPilot SITL süreci. Hub SITL'in SERIAL0
    TCP portuna Hepgo Dron Köprüsü çekirdeğiyle (kopru_core.MavLink) bağlanır; ham MAVLink gerçek köprüdeki gibi _feed_mavlink'e
    akar, komutlar MavLink.execute ile yürütülür (sanal dron özel kod yolu KULLANMAZ). Bridge yüzeyi SimDrone ile aynı:
    bridge_id = -drone_id, sysid = uçuş sysid || 1. İzleyici kalmayınca SIM_IDLE sonra, görev açık değilse hemen durur;
    süreç ölürse bağlantı 'KOPTU' olur."""

    def __init__(self, task_id, flight, home):
        self.task_id, self.drone_id, self.flight_id = task_id, int(flight['drone_id']), flight['id']
        self.id = -self.drone_id
        self.name = f"Sanal · {flight['label']}"
        self.sysid = int(flight.get('sysid') or 1)
        self.tip = drone_sitl.model_tipi(flight.get('drone_model'))
        self.host, self.platform, self.ver = 'sunucu', 'sitl', 'ArduPilot SITL'
        self.caps = ['set_home', 'param', 'reboot', 'mission_set_current', 'altitude_change', 'arm_force', 'mission_start', 'mission_clear']
        self.session_id, self.packets, self.connected_at, self.last_seen = None, 0, db.now(), time.time()
        self.closing, self.log, self.tlog, self.tlog_path = None, None, None, None
        self.parser = _mav()
        self.drones = {}
        self.home = (float(home[0]), float(home[1]))
        self.link = None
        self.loop = None
        self.last_viewer = time.time()
        self.task = None
        self.state = 'BASLIYOR'   # BASLIYOR | HAZIR | HATA

    def info(self):
        return {'bridge_id': self.id, 'name': self.name, 'host': self.host, 'platform': self.platform, 'bridge_ver': self.ver, 'caps': self.caps,
                'connected_at': self.connected_at, 'packets': self.packets, 'session_id': None, 'sim': True, 'sitl': True, 'sitl_state': self.state,
                'drone_id': self.drone_id, 'task_id': self.task_id, 'flight_id': self.flight_id,
                'drones': {str(s): st.d for s, st in self.drones.items()}}

    def _event(self, text, severity=6):
        _broadcast({'t': 'event', 'bridge_id': self.id, 'sysid': self.sysid, 'text': text, 'severity': severity, 'ts': time.time()}, self.id)
        console_line(self, self.sysid, 'SITL', text, 'hata' if severity <= 3 else 'uyari' if severity == 4 else 'bilgi')

    def _konsol(self, metin, sev='bilgi'):   # SITL yöneticisi (iş parçacığı) → olay döngüsü
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(console_line, self, self.sysid, 'SITL', metin, sev)

    def _publish(self):
        for st in list(self.drones.values()):
            _emit(self, st, force=True)

    def _on_bytes(self, data):   # MavLink okuyucu iş parçacığından
        self.packets += 1
        self.last_seen = time.time()
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(_feed_mavlink, self, data)

    def _on_state(self, state, err=None):
        if state == 'lost' and self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._event, f'SITL bağlantısı koptu: {err or ""}'.strip(), 3)

    async def acommand(self, name, params):
        if name in ('link_open', 'link_close', 'disconnect'):
            return {'ok': True, 'result': {'sim': True}}   # sanal dron her zaman bağlı
        if self.link is None:
            return {'ok': False, 'error': 'Sanal dron henüz hazır değil (SITL açılıyor)'}
        try:
            res = await asyncio.get_running_loop().run_in_executor(None, self.link.execute, name, params or {}, self.sysid)
            return {'ok': True, 'result': res}
        except Exception as e:   # noqa: BLE001
            return {'ok': False, 'error': str(e)[:300]}

    def command(self, name, params):   # eşzamanlı yol (yalnız eski simülatör); SITL'de kullanılmaz
        return {'ok': False, 'error': 'SITL komutu eşzamansız yürütülür'}

    def _connect(self, port):
        core = drone_sitl.kopru_cekirdegi()
        end = time.time() + SITL_CONNECT_S
        last = None
        while time.time() < end:
            link = core.MavLink({'type': 'tcp', 'host': '127.0.0.1', 'port': port, 'sysid': self.sysid}, self._on_bytes, self._on_state)
            try:
                link.open()
                return link, None
            except Exception as e:   # noqa: BLE001
                last = e
                time.sleep(1.0)
        return None, f'SITL portuna bağlanılamadı (tcp:127.0.0.1:{port}): {last}'

    async def run(self):
        self.loop = asyncio.get_running_loop()
        ex = self.loop.run_in_executor
        status = 'KAPANDI'
        try:
            self._event(f'SITL başlatılıyor ({self.tip}) · {self.name}', 6)
            port, err = await ex(None, lambda: drone_sitl.YONETICI.baslat(self.drone_id, self.tip, self.home[0], self.home[1], self.sysid,
                                                                          konsol=self._konsol))
            if not port:
                self.state = 'HATA'
                self._event(err or 'SITL başlatılamadı', 2)
                status = 'KOPTU'
                return
            link, err = await ex(None, self._connect, port)
            if link is None:
                self.state = 'HATA'
                self._event(err, 2)
                status = 'KOPTU'
                return
            self.link = link
            self.state = 'HAZIR'
            self._event(f'Sanal dron (SITL) bağlandı: tcp:127.0.0.1:{port}', 6)
            n = 0
            while True:
                await asyncio.sleep(1.0)
                n += 1
                if not drone_sitl.YONETICI.calisiyor_mu(self.drone_id) or not link.running:
                    self._event('SITL süreci sonlandı', 2)
                    status = 'KOPTU'
                    break
                if n % 5 == 0:   # izleyici var mı
                    now = time.time()
                    if any(v.task_id == self.task_id for v in VIEWERS.values()):
                        self.last_viewer = now
                    elif now - self.last_viewer > SIM_IDLE:
                        break
                if n % 30 == 0 and await _db(_task_status, self.task_id) not in OPEN_TASK:   # görev kapandı/iptal
                    break
        except asyncio.CancelledError:
            pass
        except Exception:   # noqa: BLE001
            status = 'KOPTU'
        finally:
            if self.link is not None:
                self.link.close()
            try:
                await asyncio.get_running_loop().run_in_executor(None, drone_sitl.YONETICI.durdur, self.drone_id)
            except Exception:   # noqa: BLE001
                drone_sitl.YONETICI.durdur(self.drone_id)
            if SIMS.get(self.id) is self:
                SIMS.pop(self.id, None)
                _broadcast({'t': 'bridge', 'bridge_id': self.id, 'online': False, 'status': status}, self.id)


def start_sim(task_id, flight, home):
    """Görevin sanal dronu için simülatörü başlatır (çalışıyorsa mevcut döner)."""
    sim = SIMS.get(-int(flight['drone_id']))
    if sim is not None:
        return sim
    sim = (SitlDrone if SITL_ENABLED else SimDrone)(task_id, flight, home)
    SIMS[sim.id] = sim
    sim.task = asyncio.get_running_loop().create_task(sim.run())
    _broadcast({'t': 'bridge', 'bridge_id': sim.id, 'online': True, 'info': sim.info()}, sim.id)
    if not SITL_ENABLED:
        sim._event(f'Sanal dron hazır · {sim.name}', 6)
        sim._publish()
    return sim


def stop_sim(bridge_id):
    """Sanal dronu durdurur: kayıttan hemen çıkar (run() kapanışı yeniden yayın yapmaz), görevi iptal eder, çevrimdışı bildirir."""
    sim = SIMS.pop(int(bridge_id), None)
    if sim is None:
        return False
    if sim.task is not None:
        sim.task.cancel()
    _broadcast({'t': 'bridge', 'bridge_id': sim.id, 'online': False, 'status': 'KAPANDI'}, sim.id)
    return True


async def _apply_task(v, task_id):
    """İzleyiciyi göreve bağlar: görev + uçuşlar yüklenir, izin kümesi kurulur, sanal dronlar başlatılır."""
    def load():
        with db.connect() as conn:
            task, flights = task_live(conn, task_id)
            return task, flights, (_sim_home(conn, task) if task else None)
    task, flights, home = await _db(load)
    v.task_id, v.task, v.flights = task_id, task, flights
    v.allowed = _task_allowed(flights)
    if task and task['status'] in OPEN_TASK:
        for f in flights:
            if f['sim_bridge_id'] is not None:
                start_sim(task_id, f, home)
    # görev bağlamında bridge_online sanal dronları da kapsar
    for f in flights:
        if f['sim_bridge_id'] is not None:
            f['bridge_online'] = f['sim_bridge_id'] in SIMS


async def _refresh_task(task_id):
    """Görevin uçuşları değişti (ekle/sil/bağlantı): bağlı izleyicilerin izin kümesi ve hello yenilenir; görevden çıkan
    sanal dron durdurulur."""
    viewers = [v for v in VIEWERS.values() if v.task_id == task_id]
    if not viewers:
        return
    old_allowed = set().union(*(v.allowed for v in viewers))
    for v in viewers:
        await _apply_task(v, task_id)
        v.put(json.dumps(hello_msg(v), ensure_ascii=False))
    keep = {f['sim_bridge_id'] for f in viewers[0].flights if f['sim_bridge_id'] is not None}
    for sid, sim in list(SIMS.items()):
        if sim.task_id == task_id and sid not in keep:
            stop_sim(sid)   # yayını yeni izin kümesi süzer → görevden çıkan sanal dronun kapanışı izleyicilere açıkça iletilir
            if sid in old_allowed:
                off = json.dumps({'t': 'bridge', 'bridge_id': sid, 'online': False, 'status': 'KAPANDI'}, ensure_ascii=False)
                for v in viewers:
                    v.put(off)


def task_changed(task_id):
    """İstek iş parçacığından (routers/field.py: POST/PUT/DELETE flights) çağrılır; görevi izleyen izleyicilerin olay döngüsüne
    (üretimde tek uvicorn döngüsü) yenilemeyi aktarır. İzleyen yoksa yapılacak bir şey yoktur (sanal dron yalnız izlenirken çalışır)."""
    tid = int(task_id)
    loops = {v.loop for v in list(VIEWERS.values()) if v.task_id == tid and v.loop is not None and not v.loop.is_closed()}
    for loop in loops:
        try:
            loop.call_soon_threadsafe(lambda lp=loop: lp.create_task(_refresh_task(tid)))
        except RuntimeError:
            pass


def hello_msg(v):
    """İzleyiciye hello: görev bağlamında yalnız görevin köprüleri/sanal dronları + task/flights; aksi hâlde hepsi."""
    user = v.user
    msg = {'t': 'hello', 'v': PROTO, 'me': {'id': user['id'], 'name': user['full_name'], 'can_command': can_command(user)}}
    if v.task_id is not None:
        bridges = [b for b in [*BRIDGES.values(), *SIMS.values()] if b.id in v.allowed]
        msg['task'] = v.task
        msg['flights'] = v.flights
    else:
        bridges = [*BRIDGES.values(), *SIMS.values()]
    msg['caps'] = all_caps(bridges)
    msg['bridges'] = [b.info() for b in bridges]
    return msg


# ---------------- Tarayıcı: /ws/drone/live ----------------
def _ws_user(token):
    """Oturum çerezinden kullanıcı + roller + modül izinleri (WebSocket'te Depends yok)."""
    with db.connect() as conn:
        u = auth.user_by_token(conn, token)
        if not u:
            return None
        from . import rbac
        real = auth.user_roles(conn, u['id'])
        u['master'] = auth.is_master(u['username'])
        if u['master']:
            u['roles'] = [*auth.ROLES, auth.MASTER]
            u['modules'] = [*dict.fromkeys([*auth.MODULE_ROLES.keys(), *rbac.node_keys()])]
            u['write_modules'] = list(u['modules'])
        else:
            u['roles'] = rbac.expand(real)
            u['modules'] = rbac.allowed(real)
            u['write_modules'] = rbac.writable(real)
        return u


def can_read(user):
    """Rol Yönetimi: 'field.live' alt düğümü (ayar yoksa 'field' modülünden miras alır — rbac.node_chain)."""
    return 'field.live' in user['modules']


def can_command(user):
    return 'field.live' in user['write_modules'] and (user.get('master') or auth.PILOT in user['roles'] or auth.ADMIN in user['roles'])


async def _viewer_sender(v: Viewer):
    try:
        while True:
            await v.ws.send_text(await v.q.get())
    except Exception:   # noqa: BLE001
        pass


async def send_command(user, bridge_id, sysid, name, params, viewer_ws=None, rid=None):
    """Tarayıcıdan (ya da REST'ten) köprüye komut: yetki + audit + req/res (CMD_TIMEOUT)."""
    if name not in CMD_NAMES:
        raise RuntimeError('Bilinmeyen komut')
    sim = int(bridge_id) < 0   # sanal dron (bridge_id = -drone_id): komut sunucu içi simülatöre gider
    b = _bridge_or_sim(bridge_id)
    if b is None:
        raise RuntimeError('Sanal dron çalışmıyor (görev izlenmiyor ya da kapandı)' if sim else 'Köprü bağlı değil')
    if name == 'arm_check':   # sunucu-yalnız rapor (okuma; komut yetkisi gerekmez, köprüye gitmez)
        st = b.drones.get(int(sysid))
        if st is None:
            raise RuntimeError('Bu dronun telemetrisi henüz gelmedi')
        return {'ok': True, 'result': arm_check_report(st)}
    if not can_command(user):
        raise RuntimeError('Komut için Canlı Uçuş yazma yetkisi ve Pilot rolü gerekir')

    def audit():
        with db.connect() as conn:
            if sim:
                db.audit(conn, user['id'], 'Sanal dron komutu', 'drone', b.drone_id, f'{name} · görev {b.task_id} · {json.dumps(params or {}, ensure_ascii=False)[:200]}')
            else:
                db.audit(conn, user['id'], 'Dron komutu', 'drone_bridge', b.id, f'{name} · sysid {sysid} · {json.dumps(params or {}, ensure_ascii=False)[:200]}')
            conn.commit()
    params = dict(params or {})
    if name in SEQ_CMDS:
        return await _start_sequence(user, b, sim, sysid, name, params, viewer_ws, audit)
    await _db(audit)
    ptxt = json.dumps(params, ensure_ascii=False)[:160]
    console_line(b, sysid, 'KOMUT', f"{name} {ptxt if ptxt != '{}' else ''} ← {user.get('full_name') or user.get('username') or ''}".strip(), 'bilgi')
    return await _dispatch(b, sim, sysid, name, params, viewer_ws, rid)


def _flow_key(b, sysid):
    return (b.id, int(sysid))


def _alive(b):
    return _bridge_or_sim(b.id) is b


async def _wait_for(pred, timeout, step=0.15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        await asyncio.sleep(step)
    return pred()


async def _start_sequence(user, b, sim, sysid, name, params, viewer_ws, audit):
    st = b.drones.get(int(sysid))
    key = _flow_key(b, sysid)
    who = user.get('full_name') or user.get('username') or ''
    if name == 'takeoff':
        try:
            hedef = float(params.get('alt_rel_m') or TAKEOFF_ALT)
        except (TypeError, ValueError):
            hedef = TAKEOFF_ALT
        hedef = min(500.0, max(1.0, hedef))
        checklist = params.get('kontrol')
        kontrol_id = None
        if checklist is not None:
            # GÖKTUNGU kalkis_kontrol: kayıt ve takeoff aynı işlem; kayıt yazılamazsa takeoff GÖNDERİLMEZ.
            # Tarih/saat ve pilot kimliği istemciden alınmaz, sunucuda damgalanır.
            viewer = VIEWERS.get(viewer_ws) if viewer_ws is not None else None
            task_id = getattr(b, 'task_id', None) if sim else (viewer.task_id if viewer else None)
            kontrol_id = await _db(_save_takeoff_check, user, b, sim, sysid, task_id, hedef, checklist)
        if key in _FLOWS:
            console_line(b, sysid, 'KOMUT', 'Kalkış hazırlık akışı zaten sürüyor; tekrar komut gönderilmedi.', 'uyari')
            if kontrol_id:
                await _db(_mark_takeoff_check, kontrol_id, False, 'Kalkış hazırlık akışı zaten sürüyordu')
            return {'ok': False, 'error': 'Kalkış hazırlık akışı zaten sürüyor; tekrar komut gönderilmedi.'}
        if st is None:
            if kontrol_id:
                await _db(_mark_takeoff_check, kontrol_id, False, 'Telemetri bağlantısı yok')
            return {'ok': False, 'error': 'Telemetri bağlantısı yok; kalkış komutu gönderilemedi'}
        await _db(audit)
        console_line(b, sysid, 'KOMUT', f"takeoff {hedef:.0f} m ← {who}".strip(), 'bilgi')
        if kontrol_id:
            console_line(b, sysid, 'KOMUT', f'Kontrol listesi onaylandı (kayıt #{kontrol_id}), takeoff {hedef:.0f} m', 'bilgi')
        _FLOWS[key] = asyncio.get_running_loop().create_task(_takeoff_flow(b, sim, sysid, hedef, kontrol_id, viewer_ws))
        return {'ok': True, 'result': {'kontrol_id': kontrol_id}}
    # mission_start (rota başlat): yanıt akış bitince döner (istemci görev aşamasını buna göre günceller)
    if key in _FLOWS:
        return {'ok': False, 'error': 'Bu dron için kalkış/görev akışı zaten sürüyor'}
    if st is None:
        return {'ok': False, 'error': 'Bağlantı yok'}
    await _db(audit)
    console_line(b, sysid, 'KOMUT', f"mission_start ← {who}".strip(), 'bilgi')
    task = asyncio.get_running_loop().create_task(_mission_flow(b, sim, sysid, params, viewer_ws))
    _FLOWS[key] = task
    return await task


def _save_takeoff_check(user, b, sim, sysid, task_id, hedef, items):
    if not isinstance(items, list) or not items:
        raise RuntimeError('Eksik istek (sysid veya madde listesi yok)')
    rows = []
    for i, m in enumerate(items[:80]):
        if not isinstance(m, dict):
            continue
        rows.append({'sira': int(m.get('sira', i) or 0), 'anahtar': str(m.get('anahtar') or '')[:60], 'soru': str(m.get('soru') or '')[:300],
                     'grup': str(m.get('grup') or '')[:60], 'cevap': m.get('cevap') is True,
                     'zorunlu': m.get('zorunlu') is not False, 'kaynak': str(m.get('kaynak') or '')[:60]})
    zorunlu = [r for r in rows if r['zorunlu']]
    if not zorunlu:
        raise RuntimeError('Kontrol listesi boş')
    eksik = sum(1 for r in zorunlu if not r['cevap'])
    if eksik:
        raise RuntimeError(f'{eksik} zorunlu madde onaylanmadı; kalkış reddedildi')
    st = b.drones.get(int(sysid))
    d = st.d if st else {}
    try:
        with db.connect() as conn:
            cur = conn.execute(
                'INSERT INTO drone_takeoff_checks (task_id, bridge_id, drone_id, sysid, user_id, pilot_name, vehicle_type, vehicle_type_name, '
                'alt_m, item_count, yes_count, full_ok, items, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (task_id, None if sim else b.id, b.drone_id if sim else None, int(sysid), user['id'], user.get('full_name') or user.get('username'),
                 d.get('type'), d.get('type_name'), float(hedef), len(rows), sum(1 for r in rows if r['cevap']),
                 1 if all(r['cevap'] for r in rows) else 0, json.dumps(rows, ensure_ascii=False), db.now()))
            kid = cur.lastrowid
            db.audit(conn, user['id'], 'Kalkış kontrol listesi', 'drone_takeoff_check', kid,
                     f"sysid {sysid} · görev {task_id or '—'} · {sum(1 for r in rows if r['cevap'])}/{len(rows)} EVET · {hedef:.0f} m")
            conn.commit()
            return kid
    except Exception as e:   # noqa: BLE001
        raise RuntimeError(f'Kalkış kaydı yazılamadı: {e}') from e


def _mark_takeoff_check(kid, sent, error):
    with db.connect() as conn:
        conn.execute('UPDATE drone_takeoff_checks SET takeoff_sent = ?, takeoff_error = ? WHERE id = ?', (1 if sent else 0, error, kid))
        conn.commit()


async def _takeoff_flow(b, sim, sysid, hedef, kontrol_id, viewer_ws):
    """GÖKTUNGU dron.py _kalkis_islemi: tek deneme, teyit telemetriden (mod adı ve armed bayrağı)."""
    d = b.drones[int(sysid)].d
    sent, hata = False, None

    def fail(msg):
        nonlocal hata
        hata = msg
        console_line(b, sysid, 'KOMUT', msg, 'hata')
    try:
        console_line(b, sysid, 'KOMUT', 'GUIDED/ARM teyidi bekleniyor...', 'uyari')
        r = await _dispatch(b, sim, sysid, 'set_mode', {'mode': 'GUIDED'}, viewer_ws)
        if not r['ok'] or not await _wait_for(lambda: str(d.get('mode') or '').upper() == 'GUIDED', GUIDED_CONFIRM_S):
            return fail('GUIDED modu teyit edilmedi; takeoff gönderilmedi.')
        if not d.get('armed'):
            r = await _dispatch(b, sim, sysid, 'arm', {}, viewer_ws)
            if not r['ok'] or not await _wait_for(lambda: bool(d.get('armed')), ARM_CONFIRM_S):
                return fail('ARM teyidi alınamadı; takeoff gönderilmedi. Pre-arm uyarılarını kontrol edin.')
        if not _alive(b):
            return fail('Takeoff öncesi MAVLink bağlantısı kesildi.')
        r = await _dispatch(b, sim, sysid, 'takeoff', {'alt_rel_m': hedef}, viewer_ws)
        if not r['ok']:
            return fail(f"Kalkış komut hatası: {r.get('error') or 'reddedildi'}")
        sent = True
        console_line(b, sysid, 'KOMUT', f'TAKEOFF komutu iletildi: {hedef:.0f} m', 'basari')
    except Exception as e:   # noqa: BLE001
        fail(f'Kalkış komut hatası: {e}')
    finally:
        _FLOWS.pop(_flow_key(b, sysid), None)
        if sim and _alive(b):
            b._publish()
        if kontrol_id:
            try:
                await _db(_mark_takeoff_check, kontrol_id, sent, hata)
            except Exception:   # noqa: BLE001
                pass


async def _mission_flow(b, sim, sysid, params, viewer_ws):
    """GÖKTUNGU gorev.py _gorevi_baslat: ARM değilse GUIDED → ARM → teyit; sonra AUTO → MISSION_START."""
    d = b.drones[int(sysid)].d
    try:
        if not d.get('armed'):
            r = await _dispatch(b, sim, sysid, 'set_mode', {'mode': 'GUIDED'}, viewer_ws)
            if not r['ok']:
                return r
            await asyncio.sleep(0.3)
            r = await _dispatch(b, sim, sysid, 'arm', {}, viewer_ws)
            if not r['ok'] or not await _wait_for(lambda: bool(d.get('armed')), MISSION_ARM_CONFIRM_S, 0.2):
                msg = f'D{sysid} ARM teyidi alınamadı (pre-arm kontrolleri?). Görev başlatılamadı.'
                console_line(b, sysid, 'KOMUT', msg, 'hata')
                return {'ok': False, 'error': msg}
        r = await _dispatch(b, sim, sysid, 'set_mode', {'mode': 'AUTO'}, viewer_ws)
        if not r['ok']:
            return r
        await asyncio.sleep(0.3)
        if not sim and 'mission_start' in b.caps:
            r = await _dispatch(b, sim, sysid, 'mission_start', {}, viewer_ws)
            if not r['ok']:
                return r
        name = str(params.get('rota') or '').strip()
        console_line(b, sysid, 'KOMUT', f"D{sysid} göreve gönderildi{': ' + repr(name) if name else ''}", 'basari')
        return {'ok': True}
    except Exception as e:   # noqa: BLE001
        return {'ok': False, 'error': str(e)}
    finally:
        _FLOWS.pop(_flow_key(b, sysid), None)
        if sim and _alive(b):
            b._publish()


async def _dispatch(b, sim, sysid, name, params, viewer_ws=None, rid=None):
    """Tek komutu köprüye (ya da sanal drona) gönderir, sonucu konsola yazar."""
    if sim:
        res = await b.acommand(name, params) if isinstance(b, SitlDrone) else b.command(name, params)
        ok = bool(res.get('ok'))
        console_line(b, sysid, 'KOMUT', f"{name}: {'kabul edildi' if ok else (res.get('error') or 'reddedildi')}", 'basari' if ok else 'hata')
        b._publish()
        return {'ok': ok, 'result': res.get('result'), 'error': res.get('error')}
    if name == 'disconnect':
        await disconnect_bridge(b.id, 'KAPANDI')
        return {'ok': True}
    rid = rid or secrets.token_hex(8)
    fut = asyncio.get_running_loop().create_future()
    _pending[rid] = (fut, viewer_ws, b.id)
    if name.startswith('kalib_'):   # v1.2 kalibrasyon oturumu: pencere yalnız bu andan sonraki STATUSTEXT'leri gösterir
        st = b.drones.get(int(sysid))
        if st is not None:
            st.d['kalib'] = {'tur': name[6:], 'bas': time.time()}
            if name == 'kalib_pusula_baslat':
                st.d['magkal_pct'] = 0; st.d['magkal_durum'] = None; st.d['magkal_rapor'] = None
    try:
        await b.ws.send_text(json.dumps({'t': 'cmd', 'rid': rid, 'sysid': sysid, 'name': name, 'params': params or {}}))
        res = await asyncio.wait_for(fut, CMD_TIMEOUTS.get(name, CMD_TIMEOUT))
        ok = bool(res.get('ok'))
        console_line(b, sysid, 'KOMUT', f"{name}: {'kabul edildi' if ok else (res.get('error') or 'reddedildi')}", 'basari' if ok else 'hata')
        return {'ok': ok, 'result': res.get('result'), 'error': res.get('error')}
    except asyncio.TimeoutError:
        console_line(b, sysid, 'KOMUT', f'{name}: köprü yanıt vermedi (zaman aşımı)', 'hata')
        raise RuntimeError('Köprü komuta yanıt vermedi (zaman aşımı)')
    finally:
        _pending.pop(rid, None)


@ws_router.websocket('/ws/drone/live')
async def ws_live(ws: WebSocket):
    await ws.accept()
    user = await _db(_ws_user, ws.cookies.get(auth.COOKIE))
    if not user or not can_read(user):
        await _safe_send(ws, {'t': 'error', 'error': 'auth'})
        await ws.close(code=4403)
        return
    v = Viewer(ws, user)
    VIEWERS[ws] = v
    sender = asyncio.create_task(_viewer_sender(v))
    seq_tasks = set()   # arka planda süren bileşik komutlar (rota başlat)
    hello = lambda: json.dumps(hello_msg(v), ensure_ascii=False)   # noqa: E731
    v.put(hello())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            t = msg.get('t')
            if t == 'ping':
                v.put(json.dumps({'t': 'pong'}))
            elif t == 'watch':
                if msg.get('task_id'):   # Faz 1: görev bağlamı — yalnız görevin köprüleri/sanal dronları; sanal dronlar başlatılır
                    try:
                        await _apply_task(v, int(msg['task_id']))
                    except (TypeError, ValueError):
                        v.put(json.dumps({'t': 'error', 'error': 'Geçersiz görev'}))
                        continue
                    if v.task is None:
                        v.task_id, v.allowed, v.flights = None, set(), []
                        v.put(json.dumps({'t': 'error', 'error': 'Görev bulunamadı'}))
                        continue
                else:   # eski davranış: tek köprü ya da hepsi
                    v.task_id, v.task, v.flights, v.allowed = None, None, [], set()
                    v.watch = int(msg['bridge_id']) if msg.get('bridge_id') else None
                v.put(hello())
            elif t == 'param_cache':   # v1.1: sunucudaki PARAM_VALUE önbelleği (param_list sonrası ya da yeniden bağlanınca)
                b = _bridge_or_sim(msg.get('bridge_id')); st = b.drones.get(int(msg.get('sysid') or 0)) if b else None
                v.put(json.dumps({'t': 'param_cache', 'bridge_id': msg.get('bridge_id'), 'sysid': msg.get('sysid'), 'params': dict(st.params) if st else {}}, ensure_ascii=False))
            elif t in ('console_hist', 'console_clear'):   # Haberleşme konsolu geçmişi / temizleme (dron başına)
                b = _bridge_or_sim(msg.get('bridge_id')); st = b.drones.get(int(msg.get('sysid') or 0)) if b else None
                if t == 'console_clear' and st is not None:
                    if not can_command(user):   # paylaşılan tamponu yalnız komut yetkisi olanlar temizler (izleyici yalnız kendi görünümünü)
                        v.put(json.dumps({'t': 'res', 'rid': msg.get('rid'), 'ok': False, 'error': 'Konsolu temizlemek için komut yetkisi gerekir'}, ensure_ascii=False))
                        continue
                    st.console = []
                    def audit_clear():
                        with db.connect() as conn:
                            db.audit(conn, user['id'], 'Dron konsolunu temizledi', 'drone_bridge', b.id, f"sysid {st.d['sysid']}")
                            conn.commit()
                    await _db(audit_clear)
                v.put(json.dumps({'t': 'console_hist', 'bridge_id': msg.get('bridge_id'), 'sysid': msg.get('sysid'), 'lines': list(st.console) if st else []}, ensure_ascii=False))
            elif t == 'cmd':
                rid = str(msg.get('rid') or secrets.token_hex(8))

                async def run_cmd(m=msg, rid=rid):
                    try:
                        res = await send_command(user, m.get('bridge_id'), int(m.get('sysid') or 1), str(m.get('name') or ''), m.get('params') or {}, ws, rid)
                        v.put(json.dumps({'t': 'res', 'rid': rid, **res}, ensure_ascii=False))
                    except Exception as e:   # noqa: BLE001
                        v.put(json.dumps({'t': 'res', 'rid': rid, 'ok': False, 'error': str(e)}, ensure_ascii=False))
                if str(msg.get('name') or '') in SEQ_CMDS:
                    # bileşik komut (rota başlat) birkaç saniye sürer: izleyicinin diğer mesajlarını bekletmesin
                    seq_tasks.add(asyncio.get_running_loop().create_task(run_cmd()))
                    seq_tasks.difference_update({x for x in seq_tasks if x.done()})
                else:
                    await run_cmd()
    except (WebSocketDisconnect, Exception):   # noqa: BLE001
        pass
    finally:
        VIEWERS.pop(ws, None)
        sender.cancel()


# ---------------- Açılış / bakım ----------------
def recover_on_start():
    """Sunucu yeniden başladı: önceki süreçten açık kalan köprü oturumları KESILDI, köprüler çevrimdışı."""
    try:
        with db.connect() as conn:
            conn.execute("UPDATE drone_bridge_sessions SET status = 'KESILDI', ended_at = ? WHERE ended_at IS NULL", (db.now(),))
            conn.execute("UPDATE drone_bridges SET status = 'CEVRIMDISI' WHERE status != 'CEVRIMDISI'")
            conn.commit()
    except Exception:   # noqa: BLE001
        pass


async def _maintenance():
    """30 sn'de bir: bağlı köprülerin last_seen/paket sayısı DB'ye, süresi dolan eşleştirme kodları temizlenir."""
    while True:
        await asyncio.sleep(30)
        try:
            now = time.time()
            for c, pc in list(PAIR_CODES.items()):
                if pc['exp'] < now:
                    PAIR_CODES.pop(c, None)
            items = [(b.id, b.session_id, b.packets) for b in BRIDGES.values()]
            if items:
                def work():
                    with db.connect() as conn:
                        for bid, sid, pk in items:
                            conn.execute('UPDATE drone_bridge_sessions SET packets = ?, last_seen = ? WHERE id = ?', (pk, db.now(), sid))
                            conn.execute("UPDATE drone_bridges SET last_seen = ?, status = 'CEVRIMICI' WHERE id = ?", (db.now(), bid))
                        conn.commit()
                await _db(work)
        except Exception:   # noqa: BLE001
            pass


def start():
    """main.lifespan: açılışta bir kez."""
    global _loop_task
    recover_on_start()
    if SITL_ENABLED:
        try:
            drone_sitl.YONETICI.artiklari_temizle()   # önceki süreçten kalan SITL'ler portu tutmasın (GÖKTUNGU)
        except Exception:   # noqa: BLE001
            pass
    try:
        _loop_task = asyncio.get_running_loop().create_task(_maintenance())
    except RuntimeError:
        _loop_task = None
