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
  tarayıcı ↔ sunucu (/ws/drone/live, oturum çerezi): ← {t:'hello',bridges,drones} {t:'status',bridge_id,sysid,state}
      {t:'bridge',bridge_id,online} {t:'event',bridge_id,sysid,text,severity} {t:'res',rid,ok,…} {t:'pong'}
      → {t:'ping'} {t:'cmd',rid,bridge_id,sysid,name,params} {t:'watch',bridge_id|null}
  Kapanış kodları: 4400 kimlik yok/zaman aşımı · 4403 anahtar/kod yanlış · 4409 aynı köprü ikinci bağlantı (eski kapatılır)
      · 4429 hız sınırı (IP başına 10 başarısız deneme / dk).
Komut adları v1: arm, disarm, set_mode{mode}, takeoff{alt_rel_m}, land, rtl, goto{lat,lon,alt_rel_m,speed_mps?},
  mission_upload{items}, mission_download, disconnect (sunucu tarafı: köprü oturumunu KAPANDI ile kapatır).
Tek uvicorn süreci varsayılır (tenant başına bir süreç; --workers>1 ile hub paylaşılamaz).
"""
import asyncio
import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth, cameras, config, db

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
CMD_TIMEOUTS = {'mission_upload': 60, 'mission_download': 60, 'log_list': 60}   # öğe başına MISSION_REQUEST_INT turu (telsizde 0,2–1 sn) → uzun rotalar
CMD_NAMES = {'arm', 'disarm', 'set_mode', 'takeoff', 'land', 'rtl', 'goto', 'mission_upload', 'mission_download', 'disconnect', 'arm_check',
             # protokol v1.1 (isteğe bağlı; köprü auth çerçevesinde caps ile bildirir, desteklemiyorsa res.error döner)
             'set_home', 'param_list', 'param_get', 'param_set', 'reboot', 'mission_set_current', 'altitude_change',
             # protokol v1.2 taslağı (docs/dron-kopru-protokolu.md; caps 'bakim' / 'log' bildiren köprüler)
             'kalib_gyro', 'kalib_baro', 'kalib_ivme', 'kalib_level', 'kalib_esc', 'kalib_radyo',
             'kalib_pusula_baslat', 'kalib_pusula_kabul', 'kalib_pusula_iptal', 'motor_test', 'motor_test_dur', 'log_list', 'log_fetch', 'log_erase'}
BRIDGE_CAPS = {'set_home', 'param', 'arm_force', 'reboot', 'mission_set_current', 'altitude_change', 'log', 'bakim'}   # köprünün bildirebileceği yetenekler

BRIDGES = {}        # bridge_id → Bridge (yalnız canlı bağlantılar)
VIEWERS = {}        # ws → Viewer
PAIR_CODES = {}     # kod → {'bridge_id', 'exp'}
_fails = {}         # ip → [zaman damgası…]
_pending = {}       # rid → (Future, viewer_ws | None)
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
        self.watch = None   # bridge_id ya da None (hepsi)

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
    txt = json.dumps(msg, ensure_ascii=False)
    for v in list(VIEWERS.values()):
        if v.watch is None or bridge_id is None or v.watch == bridge_id:
            v.put(txt)


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
    return {'bridges': [b.info() for b in BRIDGES.values()]}


def all_caps():
    """Tarayıcıya bildirilen yetenekler: sunucu yetenekleri + bağlı köprülerin bildirdikleri (köprü bazlı ayrım hello.bridges[].caps'te)."""
    caps = set(CAPS)
    for b in BRIDGES.values():
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
    b = BRIDGES.get(int(bridge_id))
    if b is None:
        raise RuntimeError('Köprü bağlı değil')
    if name == 'arm_check':   # sunucu-yalnız rapor (okuma; komut yetkisi gerekmez, köprüye gitmez)
        st = b.drones.get(int(sysid))
        if st is None:
            raise RuntimeError('Bu dronun telemetrisi henüz gelmedi')
        return {'ok': True, 'result': arm_check_report(st)}
    if not can_command(user):
        raise RuntimeError('Komut için Canlı Uçuş yazma yetkisi ve Pilot rolü gerekir')

    def audit():
        with db.connect() as conn:
            db.audit(conn, user['id'], 'Dron komutu', 'drone_bridge', b.id, f'{name} · sysid {sysid} · {json.dumps(params or {}, ensure_ascii=False)[:200]}')
            conn.commit()
    await _db(audit)
    if name == 'disconnect':
        await disconnect_bridge(b.id, 'KAPANDI')
        return {'ok': True}
    rid = rid or secrets.token_hex(8)
    fut = asyncio.get_running_loop().create_future()
    _pending[rid] = (fut, viewer_ws, b.id)
    ptxt = json.dumps(params or {}, ensure_ascii=False)[:160]
    console_line(b, sysid, 'KOMUT', f"{name} {ptxt if ptxt != '{}' else ''} ← {user.get('full_name') or user.get('username') or ''}".strip(), 'bilgi')
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
    hello = lambda: json.dumps({'t': 'hello', 'v': PROTO, 'caps': all_caps(), 'me': {'id': user['id'], 'name': user['full_name'], 'can_command': can_command(user)},   # noqa: E731
                                **snapshot()}, ensure_ascii=False)
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
                v.watch = int(msg['bridge_id']) if msg.get('bridge_id') else None
                v.put(hello())
            elif t == 'param_cache':   # v1.1: sunucudaki PARAM_VALUE önbelleği (param_list sonrası ya da yeniden bağlanınca)
                b = BRIDGES.get(int(msg.get('bridge_id') or 0)); st = b.drones.get(int(msg.get('sysid') or 0)) if b else None
                v.put(json.dumps({'t': 'param_cache', 'bridge_id': msg.get('bridge_id'), 'sysid': msg.get('sysid'), 'params': dict(st.params) if st else {}}, ensure_ascii=False))
            elif t in ('console_hist', 'console_clear'):   # Haberleşme konsolu geçmişi / temizleme (dron başına)
                b = BRIDGES.get(int(msg.get('bridge_id') or 0)); st = b.drones.get(int(msg.get('sysid') or 0)) if b else None
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
                try:
                    res = await send_command(user, msg.get('bridge_id'), int(msg.get('sysid') or 1), str(msg.get('name') or ''), msg.get('params') or {}, ws, rid)
                    v.put(json.dumps({'t': 'res', 'rid': rid, **res}, ensure_ascii=False))
                except Exception as e:   # noqa: BLE001
                    v.put(json.dumps({'t': 'res', 'rid': rid, 'ok': False, 'error': str(e)}, ensure_ascii=False))
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
    try:
        _loop_task = asyncio.get_running_loop().create_task(_maintenance())
    except RuntimeError:
        _loop_task = None
