"""Mavic Köprü — çekirdek (arayüzden bağımsız).

HEPGO Dron Yönetimi köprü protokolü v1 + v1.1 (docs/dron-kopru-protokolu.md):
- Sunucuya DIŞA DOĞRU WebSocket: wss://<alan-adı>/ws/drone/bridge, ilk çerçeve {v:1,t:'auth',key,host,platform,bridge_ver,caps}.
- Dronun yerel bağlantısından (seri / UDP / TCP; pymavlink) gelen ham MAVLink çerçeveleri ikili WebSocket çerçeveleri olarak iletilir.
- Sunucudan gelen {t:'cmd'} komutları drona MAVLink komutu olarak uygulanır, sonuç {t:'res'} ile döner.
- Bağlantı (link) sunucudan link_open/link_close ile ya da arayüzden elle açılır; durum {t:'link'} çerçevesiyle bildirilir.
- Uçuş sonrası .bin logu log_begin / ikili parçalar / log_end ile gönderilir.

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

APP_NAME = 'Mavic Köprü'          # ürün adı (mağaza adı değişirse yalnız burası ve paket bildirimi)
VERSION = '1.0.0'
CAPS = ['link', 'set_home', 'param', 'reboot', 'mission_set_current', 'altitude_change', 'arm_force']
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
    """Test/geliştirme için MAVIC_KOPRU_URL ortam değişkeni sunucu adresini ezer."""
    return os.environ.get('MAVIC_KOPRU_URL') or f'wss://{domain}/ws/drone/bridge'


def link_text(spec):
    t = spec.get('type')
    if t == 'serial':
        return f"serial:{spec.get('serial')}:{spec.get('baud') or 57600}"
    return f"{t}:{spec.get('host') or '0.0.0.0'}:{spec.get('port') or (14550 if t == 'udp' else 5760)}"


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

    def close(self):
        self.running = False
        try:
            if self.m:
                self.m.close()
        except Exception:   # noqa: BLE001
            pass

    def _gcs_heartbeat(self):
        from pymavlink import mavutil
        while self.running:
            try:
                self.m.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            except Exception:   # noqa: BLE001
                pass
            time.sleep(1)

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
            elif t == 'GLOBAL_POSITION_INT' and src == self.target:
                self.last_pos = (msg.lat, msg.lon, msg.relative_alt / 1000)
            elif t == 'PARAM_VALUE':
                self.param_types[str(msg.param_id).rstrip('\x00')] = msg.param_type
            if src == 255:
                continue   # kendi GCS kalp atışımızın yankısı
            self.rx += 1
            self.last_rx = time.time()
            try:
                self.on_bytes(bytes(msg.get_msgbuf()))
            except Exception:   # noqa: BLE001
                pass
            with self.wlock:
                ws = list(self.waiters)
            for w in ws:
                if t in w.types and (w.cond is None or w.cond(msg)):
                    w.q.put(msg)

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
        if name == 'mission_set_current':
            tgt = self._tgt(sysid)
            self.m.mav.mission_set_current_send(tgt, self.target_comp, int(p['seq']) + 1)   # +1: 0. öğe ev konumu
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
                        return {'count': len(items), 'uploaded': n}
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
# Sunucu tarafı (asyncio)
# ======================================================================
class Bridge:
    """Köprü yaşam döngüsü. ui(event, data) geri çağrısı arayüze olay verir:
    'server' (state, detail), 'link' (state, detail), 'log' (metin), 'stats' (dict)."""

    def __init__(self, code, ui=None, link_spec=None):
        self.domain, self.key = parse_code(code)
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

    # ---- iş parçacığından çağrılabilir ----
    def stop(self):
        self.stopped = True
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

    # ---- bağlantı (drona) ----
    def _on_bytes(self, data):
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
                                              'platform': platform.system().lower()[:40], 'bridge_ver': VERSION, 'caps': CAPS}))
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
                              'last_rx': self.mav.last_rx if self.mav else 0})

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
                continue
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
