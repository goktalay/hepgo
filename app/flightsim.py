"""Uçuş Simülatörü (`drone.sim`) — sunucu tarafı (sözleşme: docs/ucus-simulatoru.md §1–§4).

Oturum = gerçek ArduPilot SITL süreci (app/drone_sitl.py yöneticisi, kimlik 9000+N) + UDP sunucu (Mission Planner bağlanır)
+ MAVLink köprüsü (SITL SERIAL0 TCP ↔ UDP, ham bayt) + telemetri ayrıştırıcı (pymavlink) + 20 Hz WebSocket yayını.

Kurallar:
- SERIAL0 TCP bağlantısı oturum boyunca AÇIK tutulur (kapanınca SITL çıkar — drone_sitl Tuzak F).
- UDP'de ilk paket gönderen adres GCS olarak kilitlenir; 30 sn sessizlikte kilit kalkar. Başka adresten gelen paketler iletilmez.
- İzleyici yok + GCS yok → BOSTA_SURE sonra oturum kapanır; SIM_MAX_MINUTES dolunca kapanır; lifespan kapanışında hepsi kapanır.
- `HEPGO_SITL=0` (testler): SITL yerine sahte kinematik (merkez etrafında daire); köprü, `MANAGER.sahte_tcp_port` verilirse
  o TCP adresine bağlanır (test içindeki sahte "SITL" sunucusu) — böylece TCP↔UDP yolu gerçek kodla sınanır.

Ortam değişkenleri: SIM_UDP_BASE (14550; +99'a kadar boş port aranır), SIM_MAX_SESSIONS (2), SIM_MAX_MINUTES (120),
SIM_PUBLIC_HOST (Mission Planner'a verilecek adres; yoksa istek Host'u), HEPGO_SITL, HEPGO_SITL_DIR (drone_sitl).
"""
import asyncio
import json
import math
import os
import time

from . import db, drone_sitl

SITL_ENABLED = os.environ.get('HEPGO_SITL', '1') != '0'
UDP_BASE = int(os.environ.get('SIM_UDP_BASE', '14550'))
UDP_ARALIK = 100                      # SIM_UDP_BASE … SIM_UDP_BASE+99
MAX_SESSIONS = max(1, int(os.environ.get('SIM_MAX_SESSIONS', '2')))
MAX_MINUTES = max(1, int(os.environ.get('SIM_MAX_MINUTES', '120')))
PUBLIC_HOST = os.environ.get('SIM_PUBLIC_HOST', '').strip()
KIMLIK_TABANI = 9000                  # SITL yöneticisinde oturum kimliği (saha görevlerinin sanal dronlarıyla çakışmaz)
TELE_HZ = 20
GCS_SESSIZLIK = 30.0                  # sn: GCS kilidi kalkar
BOSTA_SURE = 600.0                    # sn: izleyici + GCS yokken oturum kapanır
SITL_BAGLANTI_S = 40                  # SITL SERIAL0'ı dinleyene dek bağlanma denemesi (Tuzak D)
VIEWER_QUEUE = 32
GCS_SYSID, GCS_COMP = 255, 191        # kendi MAVLink kaynağımız (255 = SYSID_MYGCS: RC override kabul edilir; 191 ≠ Mission Planner'ın 190'ı)
EV_IRTIFA = 100.0
RC_HZ_MIN_ARALIK = 1.0 / 20

TIP_ADLARI = {'multirotor': 'Multikopter', 'hexarotor': 'Hexakopter', 'helikopter': 'Helikopter', 'sabit_kanat': 'Sabit Kanat', 'vtol': 'VTOL'}
PLANE_TIPLERI = ('sabit_kanat', 'vtol')
KOMUTLAR = ('arm', 'disarm', 'mode', 'takeoff', 'rtl', 'reset', 'crash', 'set_home', 'rc')

WORLD_DEFAULTS = {'seed': 12345, 'size_m': 4000, 'tree_density': 0.3, 'mountain_height': 300, 'mountain_count': 4, 'building_count': 40,
                  'runway': True, 'runway_heading': 0, 'water': 0.1, 'time': 'day', 'wind_ms': 3, 'wind_dir': 270, 'fog': 0.2}
# alan → (tür, alt, üst) — sayısal alanlar; 'time' ve 'runway' ayrı denetlenir
_WORLD_SINIR = {'seed': (int, 0, 2 ** 31 - 1), 'size_m': (int, 500, 20000), 'tree_density': (float, 0, 1), 'mountain_height': (float, 0, 3000),
                'mountain_count': (int, 0, 50), 'building_count': (int, 0, 500), 'runway_heading': (float, 0, 359.99), 'water': (float, 0, 1),
                'wind_ms': (float, 0, 30), 'wind_dir': (float, 0, 359.99), 'fog': (float, 0, 1)}
_WORLD_ZAMAN = ('day', 'dusk', 'night')


class SimHata(Exception):
    """kod: 'invalid' (400) · 'limit' (409) · 'sitl' (503)"""
    def __init__(self, kod, mesaj):
        super().__init__(mesaj)
        self.kod = kod


def world_dogrula(w):
    """Ön yüzün ürettiği dünya tanımını doğrular; eksik alanlar varsayılanla dolar. Hatalıysa SimHata('invalid')."""
    if w is None:
        w = {}
    if not isinstance(w, dict):
        raise SimHata('invalid', 'world bir nesne olmalı')
    out = dict(WORLD_DEFAULTS)
    for k, (tur, alt, ust) in _WORLD_SINIR.items():
        if k not in w or w[k] is None:
            continue
        v = w[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise SimHata('invalid', f'world.{k} sayı olmalı')
        if not (alt <= v <= ust):
            raise SimHata('invalid', f'world.{k} {alt}…{ust} arasında olmalı')
        out[k] = tur(v)
    if 'runway' in w and w['runway'] is not None:
        if not isinstance(w['runway'], bool):
            raise SimHata('invalid', 'world.runway doğru/yanlış olmalı')
        out['runway'] = w['runway']
    if 'time' in w and w['time'] is not None:
        if w['time'] not in _WORLD_ZAMAN:
            raise SimHata('invalid', 'world.time day | dusk | night olmalı')
        out['time'] = w['time']
    return out


def tipler():
    """GET /meta types: SITL tipleri + ikili var mı (sahte kipte her zaman var sayılır)."""
    return [{'key': k, 'name': TIP_ADLARI.get(k, k), 'binary': (not SITL_ENABLED) or drone_sitl.ikili_yolu(k).is_file()}
            for k in drone_sitl.TIP_ESLEME]


def _dialect():
    from pymavlink.dialects.v20 import ardupilotmega as d
    return d


def _mod_adi(vtype, num):
    try:
        from pymavlink import mavutil
        return (mavutil.mode_mapping_bynumber(vtype) or {}).get(num) or str(num)
    except Exception:   # noqa: BLE001
        return str(num)


def _modlar(vtype):
    from pymavlink import mavutil
    return mavutil.mode_mapping_byname(vtype) or {}


def _varsayilan_vtype(tip):
    return 1 if tip in PLANE_TIPLERI else 2


def _rc_dogrula(ch):
    if not isinstance(ch, (list, tuple)) or len(ch) != 8:
        raise SimHata('invalid', 'rc.ch 8 kanal olmalı')
    out = []
    for v in ch:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise SimHata('invalid', 'rc kanal değeri sayı olmalı')
        v = int(v)
        if v != 0 and not (1000 <= v <= 2000):
            raise SimHata('invalid', 'rc kanal değeri 1000–2000 (0 = yoksay) olmalı')
        out.append(v)
    return out


def _kuyruga(q, txt):
    """İzleyici kuyruğu kalıbı (drone_hub.Viewer.put): dolunca en eskisi atılır — eski telemetri değersiz."""
    try:
        q.put_nowait(txt)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            q.put_nowait(txt)
        except asyncio.QueueFull:
            pass


# ======================================================================
# Sahte kinematik (HEPGO_SITL=0): merkez etrafında daire; komutlara mantıklı tepki
# ======================================================================
class SahteKinematik:
    YARICAP = 150.0      # m
    HIZ = 12.0           # m/s
    TIRMANMA = 3.0       # m/s

    def __init__(self, tip, lat, lon, alt, ruzgar_ms):
        self.tip = tip
        self.plane = tip in PLANE_TIPLERI
        self.lat0, self.lon0, self.alt0 = float(lat), float(lon), float(alt or 0)
        self.ruzgar = float(ruzgar_ms or 0)
        self.sifirla()

    def sifirla(self):
        self.lat, self.lon, self.alt_rel = self.lat0, self.lon0, 0.0
        self.home = {'lat': self.lat0, 'lon': self.lon0, 'alt': self.alt0}
        self.armed = False
        self.mode = 'MANUAL' if self.plane else 'STABILIZE'
        self.hedef_alt = 0.0
        self.aci = 0.0
        self.roll = self.pitch = self.yaw = 0.0
        self.vn = self.ve = self.vd = 0.0
        self.rc = [1500, 1500, 1000, 1500, 1500, 1500, 1500, 1500]
        self.throttle = 0.0
        self.batt_v = 12.6
        self.eve = False

    def komut(self, name, p):
        p = p or {}
        if name == 'arm':
            self.armed = True
        elif name == 'disarm':
            self.armed = False
            if self.alt_rel < 0.5:
                self.alt_rel, self.hedef_alt = 0.0, 0.0
        elif name == 'mode':
            self.mode = str(p.get('mode') or '').upper() or self.mode
            self.eve = self.mode in ('RTL', 'QRTL')
        elif name == 'takeoff':
            self.armed = True
            self.mode = 'TAKEOFF' if self.plane else 'GUIDED'
            self.hedef_alt = max(1.0, float(p.get('alt') or (50 if self.plane else 10)))
            self.eve = False
        elif name == 'rtl':
            self.mode = 'RTL'
            self.eve = True
        elif name in ('reset', 'crash'):
            self.sifirla()
        elif name == 'set_home':
            if p.get('lat') is not None and p.get('lon') is not None:
                self.home = {'lat': float(p['lat']), 'lon': float(p['lon']), 'alt': float(p.get('alt') or self.alt0)}
            else:
                self.home = {'lat': self.lat, 'lon': self.lon, 'alt': self.alt0 + self.alt_rel}
        elif name == 'rc':
            self.rc = list(p['ch'])
            if self.rc[2]:
                self.throttle = max(0.0, min(100.0, (self.rc[2] - 1000) / 10.0))

    def adim(self, dt):
        if not self.armed:
            self.vn = self.ve = self.vd = 0.0
            self.roll = self.pitch = 0.0
            self.throttle = 0.0
            return
        self.batt_v = max(10.5, self.batt_v - 0.0004 * dt)
        if self.eve:   # eve dön: önce eve yaklaş, sonra alçal; yerde kendiliğinden disarm
            dn = (self.home['lat'] - self.lat) * 110574.0
            de = (self.home['lon'] - self.lon) * 111320.0 * math.cos(math.radians(self.lat0))
            mesafe = math.hypot(dn, de)
            if mesafe > 2.0:
                adim = min(mesafe, self.HIZ * dt)
                self.lat += dn / mesafe * adim / 110574.0
                self.lon += de / mesafe * adim / (111320.0 * math.cos(math.radians(self.lat0)))
                self.vn, self.ve = dn / mesafe * self.HIZ, de / mesafe * self.HIZ
                self.yaw = math.atan2(de, dn)
            else:
                self.vn = self.ve = 0.0
                self.alt_rel = max(0.0, self.alt_rel - self.TIRMANMA * dt)
                self.vd = self.TIRMANMA if self.alt_rel > 0 else 0.0
                if self.alt_rel <= 0.0:
                    self.armed, self.eve = False, False
                    self.mode = 'MANUAL' if self.plane else 'STABILIZE'
            self.throttle = 50.0
            return
        if self.alt_rel < self.hedef_alt:   # tırmanış
            self.alt_rel = min(self.hedef_alt, self.alt_rel + self.TIRMANMA * dt)
            self.vd = -self.TIRMANMA
            self.throttle = 75.0
        else:
            self.vd = 0.0
            self.throttle = 50.0
        if self.alt_rel > 1.0:   # merkez etrafında daire (saat yönü)
            w = self.HIZ / self.YARICAP
            self.aci += w * dt
            cos_lat = math.cos(math.radians(self.lat0))
            self.lat = self.lat0 + self.YARICAP * math.cos(self.aci) / 110574.0
            self.lon = self.lon0 + self.YARICAP * math.sin(self.aci) / (111320.0 * cos_lat)
            self.vn, self.ve = -self.HIZ * math.sin(self.aci), self.HIZ * math.cos(self.aci)
            self.yaw = math.atan2(self.ve, self.vn)
            self.roll = math.atan((self.HIZ ** 2) / (self.YARICAP * 9.81)) if self.plane else 0.12
            self.pitch = 0.05 if self.plane else -0.05
        else:
            self.vn = self.ve = 0.0

    def tele(self):
        hs = math.hypot(self.vn, self.ve)
        return {'lat': round(self.lat, 7), 'lon': round(self.lon, 7), 'alt_msl': round(self.alt0 + self.alt_rel, 2), 'alt_rel': round(self.alt_rel, 2),
                'roll': round(self.roll, 4), 'pitch': round(self.pitch, 4), 'yaw': round(self.yaw, 4),
                'vn': round(self.vn, 2), 've': round(self.ve, 2), 'vd': round(self.vd, 2),
                'airspeed': round(hs + self.ruzgar * 0.3, 2), 'groundspeed': round(hs, 2), 'heading': round(math.degrees(self.yaw) % 360, 1),
                'climb': round(-self.vd, 2), 'mode': self.mode, 'armed': self.armed, 'gps_fix': 3, 'sats': 12,
                'batt_v': round(self.batt_v, 2), 'batt_pct': int(max(0, min(100, (self.batt_v - 10.5) / 2.1 * 100))),
                'throttle': round(self.throttle, 1), 'rc': list(self.rc), 'home': dict(self.home)}


# ======================================================================
# UDP sunucu (Mission Planner tarafı)
# ======================================================================
class _UdpProto(asyncio.DatagramProtocol):
    def __init__(self, oturum):
        self.oturum = oturum
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.oturum._udp_geldi(data, addr)

    def error_received(self, exc):
        pass


# ======================================================================
# Oturum
# ======================================================================
class SimSession:
    def __init__(self, sid, tip, center, world, owner, yonetici):
        self.id = int(sid)
        self.kimlik = KIMLIK_TABANI + self.id
        self.type, self.center, self.world, self.owner = tip, center, world, owner
        self.yonetici = yonetici
        self.state = 'BASLIYOR'          # BASLIYOR | HAZIR | HATA | KAPANDI
        self.udp_port = None
        self.created_at = db.now()
        self.started = time.time()
        self.sitl = {'pid': None, 'port': None, 'error': None}
        self.gcs_addr, self.gcs_since, self.gcs_last = None, None, 0.0
        self.gcs_rx = 0                  # GCS'den gelen datagram sayısı
        self.gcs_atilan = 0              # kilit dışı adreslerden gelen (iletilmeyen) datagram
        self.sitl_rx = 0                 # SITL'den gelen bayt
        self.viewers = {}                # ws → asyncio.Queue
        self.last_viewer = time.time()
        self.loop = None
        self.task = None
        self._tcp_task = None
        self._udp = None                 # DatagramTransport
        self._tcp_w = None
        self._tcp_r = None
        self._rc_son = 0.0
        self.end_reason = None
        self.sahte = None
        if not SITL_ENABLED:
            self.sahte = SahteKinematik(tip, center['lat'], center['lon'], center.get('alt'), world.get('wind_ms'))
        d = _dialect()
        self.mav = d.MAVLink(None, srcSystem=GCS_SYSID, srcComponent=GCS_COMP)   # kodlayıcı
        self.parser = d.MAVLink(None)                                             # ayrıştırıcı (SITL → telemetri)
        self.parser.robust_parsing = True
        self.sysid, self.comp, self.vtype = 1, 1, None
        self._heartbeat_alindi = False
        self.param_types = {}
        alt0 = float(center.get('alt') or 0)
        self.tele = {'lat': float(center['lat']), 'lon': float(center['lon']), 'alt_msl': alt0, 'alt_rel': 0.0, 'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0,
                     'vn': 0.0, 've': 0.0, 'vd': 0.0, 'airspeed': 0.0, 'groundspeed': 0.0, 'heading': 0.0, 'climb': 0.0, 'mode': None, 'armed': False,
                     'gps_fix': 0, 'sats': 0, 'batt_v': None, 'batt_pct': None, 'throttle': 0.0, 'rc': [0] * 8, 'home': None}

    # ---- dışa görünüm ----
    def to_dict(self, host=None):
        return {'id': self.id, 'type': self.type, 'center': dict(self.center), 'world': dict(self.world), 'state': self.state,
                'udp_port': self.udp_port, 'host': host or PUBLIC_HOST or None, 'created_at': self.created_at, 'owner': dict(self.owner),
                'gcs': {'connected': self.gcs_addr is not None, 'addr': f'{self.gcs_addr[0]}:{self.gcs_addr[1]}' if self.gcs_addr else None,
                        'since': self.gcs_since},
                'sitl': dict(self.sitl)}

    # ---- yayın ----
    def _yay(self, obj):
        txt = json.dumps(obj, ensure_ascii=False)
        for q in list(self.viewers.values()):
            _kuyruga(q, txt)

    def _olay(self, text, severity=6):
        self._yay({'t': 'event', 'text': str(text)[:300], 'severity': int(severity), 'ts': time.time()})

    def _durum(self, state):
        self.state = state
        self._yay({'t': 'state', 'state': state})

    def _konsol(self, metin, sev='bilgi'):   # SITL yöneticisi (iş parçacığı) → olay döngüsü
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._olay, metin, 2 if sev == 'hata' else 4 if sev == 'uyari' else 6)

    def izleyici_ekle(self, ws):
        q = asyncio.Queue(maxsize=VIEWER_QUEUE)
        self.viewers[ws] = q
        self.last_viewer = time.time()
        return q

    def izleyici_sil(self, ws):
        self.viewers.pop(ws, None)
        self.last_viewer = time.time()

    # ---- UDP (GCS) ----
    def _udp_geldi(self, data, addr):
        now = time.time()
        if self.gcs_addr is None or now - self.gcs_last > GCS_SESSIZLIK:
            if self.gcs_addr != addr:
                self.gcs_addr, self.gcs_since = addr, db.now()
                self._olay(f'GCS bağlandı: {addr[0]}:{addr[1]}', 6)
        elif addr != self.gcs_addr:
            self.gcs_atilan += 1   # GCS kilidi: başka adresten gelen iletilmez
            return
        self.gcs_last = now
        self.gcs_rx += 1
        if self._tcp_w is not None and not self._tcp_w.is_closing():
            try:
                self._tcp_w.write(data)
            except Exception:   # noqa: BLE001
                pass

    def _gcs_gonder(self, data):
        if self._udp is not None and self.gcs_addr is not None and not self._udp.is_closing():
            try:
                self._udp.sendto(data, self.gcs_addr)
            except Exception:   # noqa: BLE001
                pass

    async def _udp_ac(self):
        """SIM_UDP_BASE … +99 arasında boş UDP portuna bağlanır."""
        kullanilan = {s.udp_port for s in self.yonetici.sessions.values() if s is not self}
        son = None
        for p in range(UDP_BASE, UDP_BASE + UDP_ARALIK):
            if p in kullanilan:
                continue
            try:
                tr, _ = await self.loop.create_datagram_endpoint(lambda: _UdpProto(self), local_addr=('0.0.0.0', p))
            except OSError as e:
                son = e
                continue
            self._udp, self.udp_port = tr, p
            return
        raise SimHata('sitl', f'Boş UDP portu yok ({UDP_BASE}–{UDP_BASE + UDP_ARALIK - 1}): {son}')

    # ---- SITL / TCP ----
    async def _sitl_ac(self):
        """SITL'i başlatır ve SERIAL0 TCP'ye bağlanır (sahte kipte MANAGER.sahte_tcp_port'a). Hata → state HATA."""
        ex = self.loop.run_in_executor
        if SITL_ENABLED:
            c = self.center
            self._olay(f'SITL başlatılıyor ({TIP_ADLARI.get(self.type, self.type)}) · {c.get("name") or ""}', 6)
            port, err = await ex(None, lambda: drone_sitl.YONETICI.baslat(self.kimlik, self.type, c['lat'], c['lon'], sysid=1,
                                                                          irtifa=c.get('alt') or EV_IRTIFA, konsol=self._konsol))
            if not port:
                self.sitl['error'] = err or 'SITL başlatılamadı'
                self._olay(self.sitl['error'], 2)
                self._durum('HATA')
                return False
            self.sitl.update(port=port, pid=drone_sitl.YONETICI.bilgi(self.kimlik).get('pid'), error=None)
        else:
            port = self.yonetici.sahte_tcp_port
            self.sitl.update(port=port, pid=None, error=None)
        if port:
            son = None
            bitis = time.time() + (SITL_BAGLANTI_S if SITL_ENABLED else 5)
            while time.time() < bitis:
                try:
                    self._tcp_r, self._tcp_w = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', port), 3)
                    break
                except (OSError, asyncio.TimeoutError) as e:
                    son = e
                    await asyncio.sleep(1.0)
            if self._tcp_w is None:
                self.sitl['error'] = f'SITL portuna bağlanılamadı (tcp:127.0.0.1:{port}): {son}'
                self._olay(self.sitl['error'], 2)
                self._durum('HATA')
                return False
            self._tcp_task = self.loop.create_task(self._tcp_okuyucu())
            self._olay(f'SITL bağlandı: tcp:127.0.0.1:{port}', 6)
        self._heartbeat_alindi = False
        self._durum('HAZIR')
        return True

    async def _tcp_kapat(self):
        if self._tcp_task is not None:
            self._tcp_task.cancel()
            self._tcp_task = None
        if self._tcp_w is not None:
            try:
                self._tcp_w.close()
            except Exception:   # noqa: BLE001
                pass
        self._tcp_r = self._tcp_w = None

    async def _tcp_okuyucu(self):
        """SITL → (UDP GCS'ye ham) + (pymavlink ayrıştırıcı → telemetri)."""
        try:
            while True:
                data = await self._tcp_r.read(4096)
                if not data:
                    break
                self.sitl_rx += len(data)
                self._gcs_gonder(data)
                if SITL_ENABLED:
                    self._ayristir(data)
        except asyncio.CancelledError:
            return
        except Exception:   # noqa: BLE001
            pass
        if self.state not in ('KAPANDI',):
            self.sitl['error'] = 'SITL bağlantısı koptu'
            self._olay(self.sitl['error'], 2)
            self._durum('HATA')

    def _gonder(self, msg):
        """MAVLink mesajını SITL'e yazar (kodlayıcı seq'i elle artırılır: MAVLink.send yok, dosya yok)."""
        if self._tcp_w is None or self._tcp_w.is_closing():
            return False
        try:
            buf = msg.pack(self.mav)
            self.mav.seq = (self.mav.seq + 1) % 256
            self._tcp_w.write(buf)
            return True
        except Exception:   # noqa: BLE001
            return False

    def _ayristir(self, data):
        try:
            msgs = self.parser.parse_buffer(data) or []
        except Exception:   # noqa: BLE001
            return
        for m in msgs:
            try:
                self._isle(m)
            except Exception:   # noqa: BLE001
                continue

    def _isle(self, m):
        t = m.get_type()
        if t == 'BAD_DATA':
            return
        src = m.get_srcSystem()
        if src == GCS_SYSID:
            return   # GCS yankısı
        te = self.tele
        if t == 'HEARTBEAT':
            if m.type in (6, 18):   # GCS / ONBOARD_CONTROLLER değil, araç lazım
                return
            self.sysid, self.comp, self.vtype = src, m.get_srcComponent(), m.type
            te['armed'] = bool(m.base_mode & 128)
            te['mode'] = _mod_adi(m.type, m.custom_mode)
            if not self._heartbeat_alindi:
                self._heartbeat_alindi = True
                self._ilk_heartbeat()
        elif src != self.sysid:
            return
        elif t == 'GLOBAL_POSITION_INT':
            te['lat'], te['lon'] = m.lat / 1e7, m.lon / 1e7
            te['alt_msl'], te['alt_rel'] = m.alt / 1000.0, m.relative_alt / 1000.0
            te['vn'], te['ve'], te['vd'] = m.vx / 100.0, m.vy / 100.0, m.vz / 100.0
            if m.hdg != 65535:
                te['heading'] = m.hdg / 100.0
        elif t == 'ATTITUDE':
            te['roll'], te['pitch'], te['yaw'] = m.roll, m.pitch, m.yaw
        elif t == 'VFR_HUD':
            te['airspeed'], te['groundspeed'], te['throttle'], te['climb'] = m.airspeed, m.groundspeed, m.throttle, m.climb
            te['heading'] = float(m.heading)
        elif t == 'SYS_STATUS':
            te['batt_v'] = m.voltage_battery / 1000.0 if m.voltage_battery != 65535 else None
            te['batt_pct'] = m.battery_remaining if m.battery_remaining >= 0 else None
        elif t == 'GPS_RAW_INT':
            te['gps_fix'] = m.fix_type
            te['sats'] = m.satellites_visible if m.satellites_visible != 255 else None
        elif t == 'RC_CHANNELS':
            te['rc'] = [m.chan1_raw, m.chan2_raw, m.chan3_raw, m.chan4_raw, m.chan5_raw, m.chan6_raw, m.chan7_raw, m.chan8_raw]
        elif t == 'STATUSTEXT':
            self._olay(str(m.text).rstrip('\x00'), m.severity)
        elif t == 'HOME_POSITION':
            te['home'] = {'lat': m.latitude / 1e7, 'lon': m.longitude / 1e7, 'alt': m.altitude / 1000.0}
        elif t == 'COMMAND_ACK':
            if m.result not in (0, 5):
                self._olay(f'Komut {m.command} reddedildi (MAV_RESULT {m.result})', 4)
        elif t == 'PARAM_VALUE':
            self.param_types[str(m.param_id).rstrip('\x00')] = m.param_type

    def _ilk_heartbeat(self):
        """İlk araç kalp atışı: veri akışı 10 Hz, HOME iste, rüzgâr parametreleri."""
        d = _dialect()
        self._gonder(self.mav.request_data_stream_encode(self.sysid, self.comp, 0, 10, 1))   # MAV_DATA_STREAM_ALL
        self._gonder(self.mav.command_long_encode(self.sysid, self.comp, 511, 0, 242, 5000000, 0, 0, 0, 0, 0))   # HOME_POSITION 5 sn
        self._gonder(self.mav.command_long_encode(self.sysid, self.comp, 512, 0, 242, 0, 0, 0, 0, 0, 0))         # HOME bir kez
        self._ruzgar_yaz(d)
        self._olay('SITL kalp atışı alındı; veri akışı 10 Hz istendi', 6)

    def _ruzgar_yaz(self, d=None):
        d = d or _dialect()
        for ad, deger in (('SIM_WIND_SPD', self.world.get('wind_ms', 0)), ('SIM_WIND_DIR', self.world.get('wind_dir', 0))):
            self._gonder(self.mav.param_set_encode(self.sysid, self.comp, ad.encode(), float(deger), d.MAV_PARAM_TYPE_REAL32))

    def _gcs_heartbeat(self):
        self._gonder(self.mav.heartbeat_encode(6, 8, 0, 0, 0))   # MAV_TYPE_GCS, MAV_AUTOPILOT_INVALID

    # ---- komutlar ----
    async def komut(self, name, params, kaynak=None):
        """REST ve WS `cmd`: sözleşme §2. Hatalı ad/parametre → SimHata('invalid')."""
        p = params if isinstance(params, dict) else {}
        if name not in KOMUTLAR:
            raise SimHata('invalid', f'Bilinmeyen komut: {name}')
        if name == 'rc':
            p = {'ch': _rc_dogrula(p.get('ch'))}
        elif name == 'takeoff':
            alt = p.get('alt')
            if alt is None:
                alt = 50.0 if self.type in PLANE_TIPLERI else 10.0
            if isinstance(alt, bool) or not isinstance(alt, (int, float)) or not (1 <= alt <= 1000):
                raise SimHata('invalid', 'takeoff.alt 1…1000 m olmalı')
            p = {'alt': float(alt)}
        elif name == 'mode':
            mode = str(p.get('mode') or '').upper()
            if mode not in _modlar(self.vtype if self.vtype is not None else _varsayilan_vtype(self.type)):
                raise SimHata('invalid', f'Bilinmeyen uçuş modu: {mode or "-"}')
            p = {'mode': mode}
        if name == 'reset':
            await self.reset()
            return {'ok': True}
        if self.state != 'HAZIR':
            raise SimHata('invalid', 'Oturum hazır değil')
        if self.sahte is not None:
            self.sahte.komut(name, p)
            if name == 'crash':
                self._olay('ÇARPIŞMA — araç zorla disarm edildi', 2)
            return {'ok': True}
        if not self._heartbeat_alindi:
            raise SimHata('invalid', 'SITL henüz kalp atışı göndermedi')
        enc = self.mav
        s, c = self.sysid, self.comp
        if name == 'arm':
            self._gonder(enc.command_long_encode(s, c, 400, 0, 1, 21196, 0, 0, 0, 0, 0))
        elif name == 'disarm':
            self._gonder(enc.command_long_encode(s, c, 400, 0, 0, 21196, 0, 0, 0, 0, 0))
        elif name == 'crash':
            self._gonder(enc.command_long_encode(s, c, 400, 0, 0, 21196, 0, 0, 0, 0, 0))
            self._olay('ÇARPIŞMA — araç zorla disarm edildi', 2)
        elif name == 'mode':
            self._mod_gonder(p['mode'])
        elif name == 'takeoff':
            if self.type not in PLANE_TIPLERI and (self.tele.get('mode') or '').upper() != 'GUIDED':
                self._mod_gonder('GUIDED')   # kopter NAV_TAKEOFF'u yalnız GUIDED'da kabul eder; uçak TAKEOFF moduna geçer
            self._gonder(enc.command_long_encode(s, c, 22, 0, 0, 0, 0, 0, 0, 0, p['alt']))   # MAV_CMD_NAV_TAKEOFF
        elif name == 'rtl':
            self._gonder(enc.command_long_encode(s, c, 20, 0, 0, 0, 0, 0, 0, 0, 0))     # MAV_CMD_NAV_RETURN_TO_LAUNCH
        elif name == 'set_home':
            if p.get('lat') is not None and p.get('lon') is not None:
                try:
                    lat, lon, alt = float(p['lat']), float(p['lon']), float(p.get('alt') or self.tele.get('alt_msl') or 0)
                except (TypeError, ValueError):
                    raise SimHata('invalid', 'set_home lat/lon/alt sayı olmalı')
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise SimHata('invalid', 'set_home lat/lon aralık dışı')
                self._gonder(enc.command_long_encode(s, c, 179, 0, 0, 0, 0, 0, lat, lon, alt))   # MAV_CMD_DO_SET_HOME (verilen konum)
            else:
                self._gonder(enc.command_long_encode(s, c, 179, 0, 1, 0, 0, 0, 0, 0, 0))         # mevcut konum
        elif name == 'rc':
            self._gonder(enc.rc_channels_override_encode(s, c, *p['ch']))
        return {'ok': True}

    def _mod_gonder(self, mode):
        mode = mode.upper()
        modlar = _modlar(self.vtype if self.vtype is not None else _varsayilan_vtype(self.type))
        if mode not in modlar:
            raise SimHata('invalid', f'Bilinmeyen uçuş modu: {mode}')
        self._gonder(self.mav.command_long_encode(self.sysid, self.comp, 176, 0, 1, modlar[mode], 0, 0, 0, 0, 0))   # MAV_CMD_DO_SET_MODE

    async def rc(self, ch):
        """WS `rc` (en çok 20 Hz; fazlası atılır)."""
        now = time.time()
        if now - self._rc_son < RC_HZ_MIN_ARALIK:
            return
        self._rc_son = now
        await self.komut('rc', {'ch': ch})

    async def reset(self):
        """SITL'i aynı ayarlarla yeniden başlatır (sahte kipte kinematiği sıfırlar)."""
        if self.state == 'KAPANDI':
            raise SimHata('invalid', 'Oturum kapandı')
        self._olay('Sıfırlanıyor', 6)
        self._durum('BASLIYOR')
        if self.sahte is not None:
            self.sahte.sifirla()
            if self.yonetici.sahte_tcp_port and self._tcp_w is None:
                await self._sitl_ac()
            else:
                self._durum('HAZIR')
            return
        await self._tcp_kapat()
        await self.loop.run_in_executor(None, drone_sitl.YONETICI.durdur, self.kimlik)
        self.tele.update(mode=None, armed=False, alt_rel=0.0, home=None)
        await self._sitl_ac()

    # ---- yaşam döngüsü ----
    async def run(self):
        self.loop = asyncio.get_running_loop()
        yayin = None
        try:
            try:
                await self._udp_ac()
            except SimHata as e:
                self.sitl['error'] = str(e)
                self._olay(str(e), 2)
                self._durum('HATA')
            if self.udp_port is not None:
                await self._sitl_ac()   # gerçek: SITL + TCP; sahte: TCP yalnız sahte_tcp_port verilmişse
            yayin = self.loop.create_task(self._yayin())
            await self._dongu()
        except asyncio.CancelledError:
            pass
        except Exception as e:   # noqa: BLE001
            self.sitl['error'] = f'Oturum hatası: {e}'[:300]
            self._olay(self.sitl['error'], 2)
        finally:
            if yayin is not None:
                yayin.cancel()
            await self._temizle()

    async def _yayin(self):
        """20 Hz telemetri (+ sahte kinematik adımı; sahte kipte GCS'ye 1 Hz heartbeat)."""
        aralik = 1.0 / TELE_HZ
        son = time.time()
        hb = 0.0
        while True:
            await asyncio.sleep(aralik)
            now = time.time()
            dt, son = now - son, now
            if self.sahte is not None:
                self.sahte.adim(min(dt, 0.5))
                self.tele.update(self.sahte.tele())
                if now - hb >= 1.0 and self.gcs_addr is not None:
                    hb = now
                    try:
                        m = self.mav.heartbeat_encode(1 if self.type in PLANE_TIPLERI else 2, 3, 128 if self.sahte.armed else 0, 0, 4)
                        self._gcs_gonder(m.pack(self.mav))
                        self.mav.seq = (self.mav.seq + 1) % 256
                    except Exception:   # noqa: BLE001
                        pass
            if not self.viewers:
                continue
            self._yay({'t': 'tele', 'ts': now, **self.tele, 'gcs_connected': self.gcs_addr is not None,
                       'gcs_addr': f'{self.gcs_addr[0]}:{self.gcs_addr[1]}' if self.gcs_addr else None})

    async def _dongu(self):
        """1 sn: GCS sessizliği, SITL süreci, boşta / süre zaman aşımları, GCS kalp atışı."""
        while True:
            await asyncio.sleep(1.0)
            now = time.time()
            if self.gcs_addr is not None and now - self.gcs_last > GCS_SESSIZLIK:
                self._olay(f'GCS bağlantısı kesildi ({self.gcs_addr[0]}:{self.gcs_addr[1]}, {int(GCS_SESSIZLIK)} sn sessizlik)', 4)
                self.gcs_addr, self.gcs_since = None, None
            if SITL_ENABLED and self.state == 'HAZIR':
                if not drone_sitl.YONETICI.calisiyor_mu(self.kimlik):
                    self.sitl['error'] = 'SITL süreci sonlandı'
                    self._olay(self.sitl['error'], 2)
                    self._durum('HATA')
                else:
                    self._gcs_heartbeat()
            if self.viewers:
                self.last_viewer = now
            if self.gcs_addr is None and not self.viewers and now - max(self.last_viewer, self.gcs_last) > BOSTA_SURE:
                self.end_reason = 'bosta'
                return
            if now - self.started > MAX_MINUTES * 60:
                self.end_reason = 'sure'
                return

    async def kapat(self, reason='kapatildi'):
        """Dışarıdan kapatma (DELETE / lifespan): görev iptal edilir, temizlik run() finally'de."""
        if self.state == 'KAPANDI':
            return
        self.end_reason = self.end_reason or reason
        if self.task is not None and not self.task.done() and self.task is not asyncio.current_task():
            self.task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 10)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):   # noqa: BLE001
                pass
        else:
            await self._temizle()

    async def _temizle(self):
        if self.state == 'KAPANDI':
            return
        self.state = 'KAPANDI'
        await self._tcp_kapat()
        if self._udp is not None:
            try:
                self._udp.close()
            except Exception:   # noqa: BLE001
                pass
            self._udp = None
        if SITL_ENABLED:
            try:
                await asyncio.get_running_loop().run_in_executor(None, drone_sitl.YONETICI.durdur, self.kimlik)
            except Exception:   # noqa: BLE001
                drone_sitl.YONETICI.durdur(self.kimlik)
        self._yay({'t': 'end', 'reason': self.end_reason or 'kapatildi'})
        self.yonetici.sessions.pop(self.id, None)


# ======================================================================
# Yönetici (kiracı başına tek örnek)
# ======================================================================
class SimManager:
    def __init__(self):
        self.sessions = {}
        self._next = 1
        self.sahte_tcp_port = None   # HEPGO_SITL=0: testin sahte "SITL" TCP sunucusu (köprü yolu sınaması)

    def get(self, sid):
        try:
            s = self.sessions.get(int(sid))
        except (TypeError, ValueError):
            return None
        return s if s is not None and s.state != 'KAPANDI' else None

    def listele(self, host=None):
        return [s.to_dict(host) for s in self.sessions.values() if s.state != 'KAPANDI']

    def acik_sayisi(self):
        return len([s for s in self.sessions.values() if s.state != 'KAPANDI'])

    async def ac(self, tip, center, world, owner):
        """Yeni oturum: doğrulama (400) → limit (409) → SITL ikilisi (503) → UDP port (503, oturum içinde HATA) → görev."""
        if tip not in drone_sitl.TIP_ESLEME:
            raise SimHata('invalid', 'Geçersiz dron tipi')
        if not center or center.get('lat') is None or center.get('lon') is None:
            raise SimHata('invalid', 'Merkez bulunamadı')
        world = world_dogrula(world)
        if self.acik_sayisi() >= MAX_SESSIONS:
            raise SimHata('limit', f'En fazla {MAX_SESSIONS} açık oturum')
        if SITL_ENABLED and not drone_sitl.ikili_yolu(tip).is_file():
            loop = asyncio.get_running_loop()
            try:   # ikili yoksa yönetici indirir (sabit sürüm); olmazsa 503
                yol, err = await asyncio.wait_for(loop.run_in_executor(None, drone_sitl.indir, tip), 180)
            except asyncio.TimeoutError:
                yol, err = None, 'SITL ikilisi indirme zaman aşımı'
            if not yol:
                raise SimHata('sitl', err or 'SITL ikilisi yok')
        if not self._udp_bos_var():
            raise SimHata('sitl', 'Boş UDP portu yok')
        sid = self._next
        self._next += 1
        s = SimSession(sid, tip, {'id': center.get('id'), 'name': center.get('name'), 'lat': float(center['lat']), 'lon': float(center['lon']),
                                  'alt': float(center['alt']) if center.get('alt') is not None else None}, world, owner, self)
        self.sessions[sid] = s
        s.task = asyncio.get_running_loop().create_task(s.run())
        return s

    def _udp_bos_var(self):
        import socket
        kullanilan = {s.udp_port for s in self.sessions.values()}
        for p in range(UDP_BASE, UDP_BASE + UDP_ARALIK):
            if p in kullanilan:
                continue
            sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sk.bind(('0.0.0.0', p))
                return True
            except OSError:
                continue
            finally:
                sk.close()
        return False

    async def kapat(self, sid, reason='kapatildi'):
        s = self.get(sid)
        if s is None:
            return False
        await s.kapat(reason)
        return True

    async def kapat_hepsi(self):
        """main.lifespan kapanışı: tüm oturumlar (SITL süreçleri, UDP) kapanır."""
        for s in list(self.sessions.values()):
            try:
                await s.kapat('sunucu_kapaniyor')
            except Exception:   # noqa: BLE001
                pass
        self.sessions.clear()


MANAGER = SimManager()
