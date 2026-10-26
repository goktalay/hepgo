"""Canlı Uçuş — MISSION PLANNER AKTARIMI (köprü üzerinden gerçek drona MP ile de bağlanmak; protokol v1.4, cap 'mp_relay').

Kullanıcı isteği: "Canlı uçuşta köprü üstünden gelen bağlantıda dışarıya UDP (MP 'UDPCl') bağlantı versin, aynı zamanda Mission Planner
ile de bağlanayım." Simülatördeki mekanizmanın (app/flightsim.py _udp_ac/_UdpProto; docs/ucus-simulatoru.md §4) canlı uçuş karşılığı:

- Uçuş (field_flights satırı = görev + dron) başına İSTEĞE BAĞLI: yetkili kullanıcı "Mission Planner bağlantısı aç"a basınca
  LIVE_MP_UDP_BASE … +LIVE_MP_UDP_COUNT-1 (varsayılan 14700–14799; simülatörün SIM_UDP_BASE 14550–14649 aralığıyla ÇAKIŞMAZ) arasında boş bir
  UDP portu 0.0.0.0'a bağlanır. Mission Planner › bağlantı türü UDPCl › <LIVE_MP_PUBLIC_HOST | SIM_PUBLIC_HOST | istek Host'u>:<port>.
  Kiracılar ayrı süreçlerdir (drone_hub tek süreç/kiracı): port bağlama işletim sisteminde tekildir, iki kiracı aynı portu alamaz;
  REST yetkisi uçuşun kendi kiracı veritabanındaki görev üyeliğiyle denetlenir.
- İki yönlü HAM aktarım: köprüden gelen ikili MAVLink çerçeveleri (drone_hub.ws_bridge) → MP adresine (uçuşun sysid'i dışındaki dronlar
  ayıklanır); MP'den gelen datagramlar → köprüye ikili WS çerçevesi `0x01 + ham MAVLink` (raw_up). Köprü raw_up'ı drona olduğu gibi yazar.
- GÜVENLİK: (1) IP kilidi — kilit yalnız geçerli bir GCS HEARTBEAT'i (MAV_TYPE_GCS) içeren datagramla kurulur (rastgele tarayıcı
  paketleri kilitlemez); kilitten sonra yalnız o IP'den (kaynak portu değişebilir — MP yeniden bağlanınca) gelenler iletilir, diğerleri
  sayılıp atılır. "IP kilidini sıfırla" kilidi kaldırır. (2) İsteğe bağlı eşleştirme: pair_sysid verilirse kilit yalnız o MAVLink
  sistem kimliğinden (MP varsayılanı 255) gelen HEARTBEAT ile kurulur; tek kullanımlıktır (sıfırlamada yeniden gerekir).
  (3) Süre: 30 dk (LIVE_MP_IDLE_MIN) MP'den paket gelmezse, görev BASLANGIC/GOREVDE dışına çıkınca ya da köprü 120 sn'den uzun
  çevrimdışı kalınca kapanır. (4) Hız/boyut: datagram ≤ 2048 bayt, MAVLink sihirli baytı (0xFE/0xFD) zorunlu, ≤ 300 paket/sn ve
  ≤ 256 KB/sn (aşan atılır). (5) Denetim günlüğü: açan, MP IP'si (ilk bağlanış / değişim), sıfırlama, kapanış (neden + sayaçlar),
  kilit dışı IP denemesi (IP başına bir kez).
- HEPGO ile birlikte çalışma: köprü ve Mission Planner aynı GCS kimliğini (255/190) kullanabilir; ArduPilot ikisine de yanıt verir.
  MP'nin ARM/DISARM, mod değişikliği, kalkış/iniş/RTL, görev yükleme/temizleme, PARAM_SET komutları dron konsoluna ve genel konsola
  "Mission Planner: …" satırı olarak düşer; HEPGO'nun kalkış/görev akışı sürerken gelirse ÇAKIŞMA uyarısıdır. MP PARAM_SET'leri, yankı
  PARAM_VALUE gelince dronun kalıcı parametre kaydına (drone_params, kaynak 'mp') işlenir (simülatördeki MP yakalamasıyla aynı mantık).
"""
import asyncio
import os
import time

from . import auth, db, drone_params

UDP_BASE = int(os.environ.get('LIVE_MP_UDP_BASE', '14700'))
UDP_COUNT = max(1, min(1000, int(os.environ.get('LIVE_MP_UDP_COUNT', '100'))))
PUBLIC_HOST = (os.environ.get('LIVE_MP_PUBLIC_HOST') or os.environ.get('SIM_PUBLIC_HOST') or '').strip()
IDLE_S = max(60, int(float(os.environ.get('LIVE_MP_IDLE_MIN', '30')) * 60))
BRIDGE_GRACE_S = 120          # köprü bu kadar çevrimdışı kalırsa aktarım kapanır (kısa kopmalarda MP bağlantısı korunur)
CONNECTED_S = 10              # son MP paketi bu kadar yeniyse "bağlı"
MAX_DGRAM = 2048
RATE_PPS, RATE_BPS = 300, 256 * 1024
RAW_UP = 0x01                 # sunucu → köprü ikili çerçeve türü (protokol v1.4)
CAP = 'mp_relay'
MIN_VERSIONS = {'linux': '1.1.6', 'windows': '1.1.0'}
MAV_MAGIC = (0xFE, 0xFD)
MAINT_S = 5
TASK_CHECK_S = 30
OPEN_TASK = ('BASLANGIC', 'GOREVDE')

RELAYS = {}                   # flight_id → Relay
_maint_task = None

# MP'den gelen dikkat çekici komutlar (COMMAND_LONG/INT) → olay satırı metni (None: param1'e bakılır)
_CMD_TEXT = {400: None, 176: None, 22: 'KALKIŞ (TAKEOFF)', 21: 'İNİŞ (LAND)', 20: 'EVE DÖN (RTL)', 300: 'GÖREVİ BAŞLAT', 246: 'YENİDEN BAŞLATMA',
             179: 'HOME AYARLA', 241: 'KALİBRASYON', 209: 'MOTOR TESTİ', 178: 'HIZ DEĞİŞTİRME', 192: 'KONUMA GİT (REPOSITION)', 183: 'SERVO AYARLA',
             84: 'DURAKLAT/DEVAM', 193: 'DURAKLAT/DEVAM'}
_ONEMLI = {400, 176, 22, 21, 20, 300, 246, 209}   # genel konsola da düşer (uyarı)


def _hub():
    from . import drone_hub
    return drone_hub


def can_manage(user):
    """Aktarımı açma/kapama/sıfırlama: Canlı Uçuş komut yetkisi (field.live yazma + Pilot/Yönetici) ya da Dron Yönetimi yazma izni olan
    Pilot/Sistem Yöneticisi (MP drona tam komut verir — komut yetkisiyle eşdeğer tutulur)."""
    if _hub().can_command(user):
        return True
    roles = set(user.get('roles') or [])
    return 'drone.drones' in (user.get('write_modules') or []) and (bool(user.get('master')) or bool({auth.PILOT, auth.ADMIN} & roles))


def bridge_supported(bridge):
    return bridge is not None and CAP in (bridge.caps or [])


def update_hint():
    return f"Köprüyü güncelleyin (Linux ≥{MIN_VERSIONS['linux']} / Windows ≥{MIN_VERSIONS['windows']})"


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, relay):
        self.relay = relay

    def datagram_received(self, data, addr):
        try:
            self.relay.from_mp(data, addr)
        except Exception:   # noqa: BLE001 — tek bozuk paket aktarımı düşürmesin
            pass

    def error_received(self, exc):
        pass


class Relay:
    def __init__(self, flight, user, pair_sysid, host):
        self.flight_id = int(flight['id'])
        self.task_id = int(flight['task_id'])
        self.drone_id = flight.get('drone_id')
        self.drone_code = flight.get('drone_code')
        self.bridge_id = int(flight['bridge_id'])
        self.sysid = int(flight['sysid']) if flight.get('sysid') else None
        self.opened_by = user['id']
        self.opened_by_name = user.get('full_name') or user.get('username') or ''
        self.opened_at = time.time()
        self.opened_iso = db.now()
        self.pair_sysid = int(pair_sysid) if pair_sysid else None
        self.host = host
        self.port = None
        self.transport = None
        self.loop = None
        self.locked_ip = None
        self.peer = None             # (ip, port) son MP adresi
        self.connected_at = None
        self.last_rx = None          # MP → sunucu
        self.last_tx = None          # sunucu → MP
        self.last_activity = self.opened_at
        self.rx_pk = self.rx_bytes = self.tx_pk = self.tx_bytes = 0
        self.dropped_ip = self.dropped_rate = self.dropped_invalid = self.dropped_offline = 0
        self.rejected_ips = set()
        self.offline_since = None
        self.closed = False
        self.close_reason = None
        self._tokens, self._btokens, self._tb = float(RATE_PPS), float(RATE_BPS), time.time()
        self._parser = None
        self._seen = {}              # olay satırı tekrar bastırma: anahtar → zaman
        self.queue = asyncio.Queue(maxsize=1000)
        self.sender = None
        self.izleyici = None
        if self.drone_id:
            try:
                self.izleyici = drone_params.Izleyici(self.drone_id, self._param_note, gercek=True)
            except Exception:   # noqa: BLE001
                self.izleyici = None

    # ---- durum ----
    def info(self):
        hub = _hub()
        b = hub.BRIDGES.get(self.bridge_id)
        now = time.time()
        return {'active': not self.closed, 'flight_id': self.flight_id, 'task_id': self.task_id, 'drone_id': self.drone_id, 'bridge_id': self.bridge_id,
                'sysid': self.sysid, 'host': self.host, 'port': self.port, 'address': f'{self.host}:{self.port}' if self.host and self.port else None,
                'opened_at': self.opened_iso, 'opened_by': self.opened_by_name, 'pair_sysid': self.pair_sysid,
                'locked_ip': self.locked_ip, 'peer': f'{self.peer[0]}:{self.peer[1]}' if self.peer else None,
                'connected': bool(self.last_rx and now - self.last_rx < CONNECTED_S),
                'last_rx': self.last_rx, 'last_tx': self.last_tx, 'last_rx_ago': round(now - self.last_rx, 1) if self.last_rx else None,
                'rx_packets': self.rx_pk, 'rx_bytes': self.rx_bytes, 'tx_packets': self.tx_pk, 'tx_bytes': self.tx_bytes,
                'dropped': {'ip': self.dropped_ip, 'rate': self.dropped_rate, 'invalid': self.dropped_invalid, 'offline': self.dropped_offline},
                'idle_timeout_s': IDLE_S, 'closes_in_s': max(0, int(IDLE_S - (now - self.last_activity))),
                'bridge_online': b is not None, 'bridge_supported': bridge_supported(b) if b is not None else None,
                'params_saved': self.izleyici.kayit_sayisi if self.izleyici else 0}

    # ---- açılış / kapanış ----
    async def open(self):
        self.loop = asyncio.get_running_loop()
        used = {r.port for r in RELAYS.values() if r is not self}
        last = None
        for p in range(UDP_BASE, UDP_BASE + UDP_COUNT):
            if p in used:
                continue
            try:
                tr, _ = await self.loop.create_datagram_endpoint(lambda: _Proto(self), local_addr=('0.0.0.0', p))
            except OSError as e:
                last = e
                continue
            self.transport, self.port = tr, p
            break
        else:
            raise RuntimeError(f'Boş UDP portu yok ({UDP_BASE}–{UDP_BASE + UDP_COUNT - 1}): {last}')
        self.sender = self.loop.create_task(self._send_loop())

    def close(self, reason):
        if self.closed:
            return
        self.closed, self.close_reason = True, reason
        try:
            if self.transport is not None:
                self.transport.close()
        except Exception:   # noqa: BLE001
            pass
        if self.sender is not None:
            self.sender.cancel()

    # ---- MP → köprü ----
    def _rate_ok(self, n):
        now = time.time()
        dt, self._tb = now - self._tb, now
        self._tokens = min(RATE_PPS * 2, self._tokens + dt * RATE_PPS)
        self._btokens = min(RATE_BPS * 2, self._btokens + dt * RATE_BPS)
        if self._tokens < 1 or self._btokens < n:
            return False
        self._tokens -= 1
        self._btokens -= n
        return True

    def _parse(self, data):
        if self._parser is None:
            self._parser = _hub()._mav()
        try:
            return [m for m in (self._parser.parse_buffer(data) or []) if m.get_type() != 'BAD_DATA']
        except Exception:   # noqa: BLE001
            return []

    def from_mp(self, data, addr):
        if self.closed:
            return
        if not data or len(data) > MAX_DGRAM or data[0] not in MAV_MAGIC:
            self.dropped_invalid += 1
            return
        ip = addr[0]
        if self.locked_ip is None:
            msgs = self._parse(data)
            hb = [m for m in msgs if m.get_type() == 'HEARTBEAT' and getattr(m, 'type', None) == 6]
            if not hb or (self.pair_sysid and not any(m.get_srcSystem() == self.pair_sysid for m in hb)):
                self.dropped_invalid += 1   # kilit yalnız (eşleşen) GCS kalp atışıyla kurulur
                return
            self.locked_ip, self.peer, self.connected_at = ip, addr, time.time()
            self._event(f'Mission Planner bağlandı: {ip}:{addr[1]}', 'basari', genel=True)
            self._audit('Mission Planner aktarımı: MP bağlandı', f'{ip}:{addr[1]}' + (f' · eşleştirme sysid {self.pair_sysid}' if self.pair_sysid else ''))
        elif ip != self.locked_ip:
            self.dropped_ip += 1
            if ip not in self.rejected_ips and len(self.rejected_ips) < 50:
                self.rejected_ips.add(ip)
                self._event(f'Mission Planner: kilit dışı adres reddedildi ({ip})', 'uyari')
                self._audit('Mission Planner aktarımı: kilit dışı IP reddedildi', f'{ip}:{addr[1]} · kilit {self.locked_ip}')
            return
        else:
            msgs = None
            if addr != self.peer:
                self.peer = addr   # aynı IP, yeni kaynak portu (MP yeniden bağlandı)
        if not self._rate_ok(len(data)):
            self.dropped_rate += 1
            return
        now = time.time()
        self.last_rx = self.last_activity = now
        self.rx_pk += 1
        self.rx_bytes += len(data)
        b = _hub().BRIDGES.get(self.bridge_id)
        if b is None or not bridge_supported(b):
            self.dropped_offline += 1
        else:
            try:
                self.queue.put_nowait(bytes([RAW_UP]) + data)
            except asyncio.QueueFull:
                self.dropped_rate += 1
        self._inspect(msgs if msgs is not None else self._parse(data))

    async def _send_loop(self):
        while True:
            frame = await self.queue.get()
            b = _hub().BRIDGES.get(self.bridge_id)
            if b is None:
                self.dropped_offline += 1
                continue
            try:
                await b.ws.send_bytes(frame)
            except Exception:   # noqa: BLE001
                self.dropped_offline += 1

    # ---- köprü → MP ----
    def to_mp(self, data):
        if self.closed or self.peer is None or self.transport is None:
            return
        try:
            self.transport.sendto(data, self.peer)
        except Exception:   # noqa: BLE001
            return
        self.tx_pk += 1
        self.tx_bytes += len(data)
        self.last_tx = time.time()

    # ---- MP komutlarını HEPGO'ya yansıtma ----
    def _target_sysid(self, b=None):
        if self.sysid:
            return self.sysid
        b = b or _hub().BRIDGES.get(self.bridge_id)
        if b is not None and b.drones:
            return sorted(b.drones)[0]
        return 1

    def _mode_text(self, custom_mode):
        b = _hub().BRIDGES.get(self.bridge_id)
        st = b.drones.get(self._target_sysid(b)) if b is not None else None
        vtype = (st.d.get('type') if st else None) or 2
        return _hub()._mode_name(vtype, int(custom_mode))

    def _inspect(self, msgs):
        for m in msgs:
            try:
                self._inspect_one(m)
            except Exception:   # noqa: BLE001
                continue

    def _once(self, key, window=3.0):
        now = time.time()
        t = self._seen.get(key)
        self._seen[key] = now
        if len(self._seen) > 200:
            self._seen = {k: v for k, v in self._seen.items() if now - v < 30}
        return t is None or now - t > window

    def _inspect_one(self, m):
        t = m.get_type()
        if t == 'HEARTBEAT':
            return
        if t == 'PARAM_SET':
            name = str(m.param_id).rstrip('\x00')
            if self.izleyici is not None:
                self.izleyici.mp_set(name, m.param_value)
            if self._once(('ps', name, round(float(m.param_value), 6))):
                self._event(f'Mission Planner: PARAM_SET {name} = {float(m.param_value):g}', 'bilgi')
            return
        if t in ('COMMAND_LONG', 'COMMAND_INT'):
            cmd = int(m.command)
            if cmd not in _CMD_TEXT:
                return
            p1, p2 = float(m.param1), float(m.param2)
            if not self._once(('cmd', cmd, round(p1, 3), round(p2, 3))):
                return   # MP komutu ACK gelene dek yineler
            if cmd == 400:
                text = ('ARM' + (' (ZORLA)' if int(p2) == 21196 else '')) if p1 >= 0.5 else ('DISARM' + (' (ZORLA)' if int(p2) == 21196 else ''))
            elif cmd == 176:
                text = f'MOD → {self._mode_text(p2)}'
            else:
                text = _CMD_TEXT[cmd]
            self._command_event(text, cmd in _ONEMLI)
            return
        if t == 'SET_MODE':
            if self._once(('mode', int(m.custom_mode))):
                self._command_event(f'MOD → {self._mode_text(m.custom_mode)}', True)
            return
        if t == 'MISSION_COUNT' and int(getattr(m, 'mission_type', 0) or 0) == 0:
            if self._once(('mc', int(m.count)), 10):
                self._command_event(f'görev yükleniyor ({max(0, int(m.count) - 1)} öğe + ev) — HEPGO rotasından farklı olabilir', True)
            return
        if t == 'MISSION_CLEAR_ALL':
            if self._once(('mclr',), 5):
                self._command_event('görev listesi temizlendi', True)
            return
        if t == 'MISSION_SET_CURRENT':
            if self._once(('msc', int(m.seq))):
                self._command_event(f'görev öğesi {int(m.seq)} etkin yapıldı', False)
            return
        if t in ('SET_POSITION_TARGET_GLOBAL_INT',) or (t in ('MISSION_ITEM', 'MISSION_ITEM_INT') and int(getattr(m, 'current', 0)) == 2):
            if self._once(('goto',), 5):
                self._command_event('GUIDED hedefi (Fly To Here)', False)

    def _command_event(self, text, important):
        hub = _hub()
        sysid = self._target_sysid()
        akis = (self.bridge_id, int(sysid)) in hub._FLOWS
        if akis:
            text += ' — DİKKAT: HEPGO kalkış/görev akışı sürüyor, komutlar çakışabilir'
        self._event(f'Mission Planner: {text}', 'uyari' if (important or akis) else 'bilgi', genel=important or akis)

    def _event(self, text, sev='bilgi', genel=False):
        hub = _hub()
        b = hub.BRIDGES.get(self.bridge_id)
        if b is None:
            return
        sysid = self._target_sysid(b)
        try:
            hub.console_line(b, sysid, 'MP', text, sev)
            if genel:
                hub.global_line(b, sysid, 'MP', f'D{sysid} {text}', sev)
        except Exception:   # noqa: BLE001
            pass

    def _param_note(self, text, severity):
        self._event(text, 'uyari' if severity <= 4 else 'bilgi')

    def _audit(self, action, detail, user_id=None):
        rid, fid = self.flight_id, self.drone_code

        def work():
            try:
                with db.connect() as conn:
                    db.audit(conn, user_id, action, 'field_flight', rid, f"{fid or ''} · köprü {self.bridge_id} · {detail}"[:500])
                    conn.commit()
            except Exception:   # noqa: BLE001
                pass
        try:
            asyncio.get_running_loop().run_in_executor(None, work)
        except RuntimeError:
            work()


# ---------------- dış yüz ----------------
def get(flight_id):
    r = RELAYS.get(int(flight_id))
    return r if r is not None and not r.closed else None


def for_bridge(bridge_id):
    return [r for r in RELAYS.values() if r.bridge_id == bridge_id and not r.closed]


async def open_relay(flight, user, pair_sysid=None, host=None):
    """flight: field_flights satırı (+ drone_code). Var olan açık aktarım aynen döner (idempotent)."""
    cur = get(flight['id'])
    if cur is not None:
        return cur, False
    hub = _hub()
    b = hub.BRIDGES.get(int(flight['bridge_id']))
    if b is None:
        raise RuntimeError('Köprü bağlı değil: Mission Planner aktarımı köprü çevrimiçiyken açılır')
    if not bridge_supported(b):
        raise RuntimeError(f"{update_hint()} — bu köprü {b.ver or 'eski sürüm'}, Mission Planner aktarımını desteklemiyor")
    if pair_sysid is not None and not (1 <= int(pair_sysid) <= 255):
        raise ValueError('Eşleştirme sysid 1–255 olmalı')
    r = Relay(flight, user, pair_sysid, host or PUBLIC_HOST or None)
    await r.open()
    RELAYS[r.flight_id] = r
    _ensure_maintenance()
    r._event(f"Mission Planner aktarımı açıldı: UDPCl {r.host or '<sunucu>'}:{r.port} ({r.opened_by_name})", 'bilgi', genel=True)
    r._audit('Mission Planner aktarımı açıldı', f"UDP {r.port}" + (f' · eşleştirme sysid {r.pair_sysid}' if r.pair_sysid else ''), user['id'])
    return r, True


def close_relay(flight_id, reason, user=None):
    r = RELAYS.pop(int(flight_id), None)
    if r is None:
        return False
    r.close(reason)
    r._event(f'Mission Planner aktarımı kapandı ({reason})', 'bilgi', genel=True)
    r._audit('Mission Planner aktarımı kapandı', f'{reason} · MP→ {r.rx_pk} paket · →MP {r.tx_pk} paket · kilit {r.locked_ip or "—"}'
             f' · reddedilen IP {r.dropped_ip}', user['id'] if user else None)
    return True


def reset_ip(flight_id, user):
    r = get(flight_id)
    if r is None:
        return None
    old = r.locked_ip
    r.locked_ip, r.peer, r.connected_at = None, None, None
    r.rejected_ips = set()
    r._event(f"Mission Planner IP kilidi sıfırlandı ({old or '—'}); sonraki GCS kalp atışı yeni adresi kilitler", 'uyari', genel=True)
    r._audit('Mission Planner aktarımı: IP kilidi sıfırlandı', f"eski {old or '—'}", user['id'])
    return r


def from_drone(bridge, data, msgs):
    """drone_hub.ws_bridge: köprüden gelen ham çerçeve(ler). Uçuşun sysid'i belirliyse ve köprüde başka dron da varsa yalnız o dronun
    (ve bileşenlerinin) çerçeveleri gider; tek dronlu köprüde ham bayt olduğu gibi (ayrıştırıcının tanımadığı mesajlar da) iletilir."""
    for r in for_bridge(bridge.id):
        if r.peer is None:
            continue
        others = r.sysid is not None and any(s != r.sysid and st.d.get('msgs') for s, st in bridge.drones.items())
        if not others:
            r.to_mp(data)
            continue
        buf = b''.join(bytes(m.get_msgbuf()) for m in (msgs or []) if m.get_type() != 'BAD_DATA' and m.get_srcSystem() == r.sysid)
        if buf:
            r.to_mp(buf)


def izleyici(bridge_id, sysid):
    """PARAM_VALUE yankısı (drone_hub._feed_msgs) için: bu köprü + sysid'e ait açık aktarımın parametre izleyicisi."""
    for r in for_bridge(bridge_id):
        if r.izleyici is not None and (r.sysid is None or r.sysid == sysid):
            return r.izleyici
    return None


def bridge_info_extra(bridge):
    """Köprü info'suna eklenen alan: açık aktarımların uçuş kimlikleri."""
    return [r.flight_id for r in for_bridge(bridge.id)]


def _ensure_maintenance():
    global _maint_task
    if _maint_task is not None and not _maint_task.done():
        return
    try:
        _maint_task = asyncio.get_running_loop().create_task(_maintenance())
    except RuntimeError:
        _maint_task = None


def _task_statuses(ids):
    with db.connect() as conn:
        q = ','.join('?' * len(ids))
        return {r[0]: r[1] for r in conn.execute(f'SELECT id, status FROM field_tasks WHERE id IN ({q})', list(ids))}


async def _maintenance():
    last_task_check = 0.0
    while RELAYS:
        await asyncio.sleep(MAINT_S)
        now = time.time()
        hub = _hub()
        for fid, r in list(RELAYS.items()):
            if now - r.last_activity > IDLE_S:
                close_relay(fid, f'{IDLE_S // 60} dk hareketsizlik')
                continue
            if r.bridge_id in hub.BRIDGES:
                r.offline_since = None
            elif r.offline_since is None:
                r.offline_since = now
            elif now - r.offline_since > BRIDGE_GRACE_S:
                close_relay(fid, 'köprü çevrimdışı')
        if RELAYS and now - last_task_check >= TASK_CHECK_S:
            last_task_check = now
            try:
                st = await asyncio.to_thread(_task_statuses, {r.task_id for r in RELAYS.values()})
            except Exception:   # noqa: BLE001
                st = None
            if st is not None:
                for fid, r in list(RELAYS.items()):
                    if st.get(r.task_id) not in OPEN_TASK:
                        close_relay(fid, 'görev kapandı')


def close_threadsafe(flight_id, reason, user=None):
    """İstek iş parçacığından (routers/field.py: uçuş bağlantısı değişti / uçuş silindi) aktarımı olay döngüsünde kapatır."""
    r = RELAYS.get(int(flight_id))
    if r is None or r.loop is None or r.loop.is_closed():
        return False
    try:
        r.loop.call_soon_threadsafe(close_relay, int(flight_id), reason, user)
    except RuntimeError:
        return False
    return True
