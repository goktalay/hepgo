"""Dron görüntü köprüsü hub'ı (Dron Yönetimi › Kameralar; protokol v1.3 — docs/dron-kopru-protokolu.md).

Köprü (ör. Jetson üzerindeki Hepgo Dron Köprüsü, bridge/dron_koprusu/goruntu_core.py) sunucuya telemetriden AYRI ikinci bir WebSocket
açar (DIŞA DOĞRU; NAT/4G arkasında port açılmaz): wss://<alan>/ws/drone/video, telemetriyle aynı köprü anahtarıyla kimlik.
Sunucu köprüye bağlı kameraların yapılandırmasını gönderir ({t:'video_cfg', cameras}); köprü RTSP/RTP kaynağını kendi ağında açar,
H.264'ü (FPS kaynakla aynıysa yeniden kodlamadan) parçalı MP4'e (fMP4) böler ve ikili çerçevelerle iter:
    [tür:1 bayt][kamera_id:4 bayt big-endian][yük]   tür 1 = init (ftyp+moov) · 2 = anahtar kareyle başlayan parça (moof+mdat)
                                                     3 = ara parça · 4 = JPEG anlık görüntü
Tarayıcı /ws/drone/video/watch?camera_id=N (oturum çerezi) ile izler: önce {t:'init', mime} + ikili init, sonra son GOP'un önbelleği
(anahtar parçadan itibaren) ve canlı parçalar — ikili çerçeveler [tür:1][yük]; MSE ile oynatılır.
Bellek sınırları: kamera başına GOP önbelleği GOP_MAX, izleyici kuyruğu VIEWER_MAX_BYTES (aşınca parçalar atlanır, sonraki anahtar
parçayla devam edilir — yavaş izleyici diğerlerini ve köprüyü bekletmez), izleyici sayısı VIEWERS_PER_CAM, tek çerçeve FRAME_MAX.
Bant tasarrufu: köprü yalnız izleyici varken yayınlar — ilk izleyicide {t:'want', camera_id, on:true}, son izleyici gidince LINGER sn
sonra on:false. JPEG anlık görüntü ({t:'snap', camera_id}) yayın olmadan da çalışır (düşük bant).
Tek uvicorn süreci varsayılır (drone_hub ile aynı).
"""
import asyncio
import json
import logging
import secrets
import struct
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth, cameras, db, drone_hub, data_packages

log = logging.getLogger('hepgo.drone_video')

ws_router = APIRouter()

T_INIT, T_KEY, T_DELTA, T_JPEG = 1, 2, 3, 4
FRAME_MAX = 4 * 1024 * 1024          # tek parça/init/JPEG üst sınırı
GOP_MAX = 6 * 1024 * 1024            # kamera başına son GOP önbelleği (yeni izleyici anahtar kareden başlar)
VIEWER_MAX_BYTES = 3 * 1024 * 1024   # izleyici kuyruğunda bekleyen bayt; aşılınca parça atlanır (sonraki anahtar parçaya dek)
VIEWERS_PER_CAM = 20
LINGER = 2                           # son izleyici gidince (önizleme/pencere kapatıldı ya da ■ Durdur) köprüye want:false — yalnız kısa yeniden bağlanma payı (sn)
LIVE_S = 5                           # son parçadan bu kadar süre geçmediyse "canlı"
SNAP_TIMEOUT = 15
AUTH_TIMEOUT = 15
FPS_CHOICES = (0, 5, 10, 15, 20, 25, 30)   # 0 = kaynak FPS'i
CAP = 'video'

# Etkin köprü: açık saha görevinde (Canlı Uçuş › Kameralar) köprü seçilmişse o, yoksa kamera kaydındaki köprü (c = drone_cameras takma adı)
EFF_BRIDGE = ("(COALESCE((SELECT a.bridge_id FROM field_task_cameras a JOIN field_tasks t ON t.id = a.task_id WHERE a.camera_id = c.id "
              "AND a.bridge_id IS NOT NULL AND t.status IN ('BASLANGIC', 'GOREVDE') ORDER BY a.id DESC LIMIT 1), c.bridge_id))")
RESYNC_S = 30                        # görev açılıp kapanınca etkin köprü değişir: bağlı köprülerin kamera listesi düzenli denetlenir

VBRIDGES = {}   # bridge_id → VBridge (canlı görüntü bağlantıları)
STREAMS = {}    # camera_id → CamStream (izleyici ya da veri olan kameralar)
_loop = None


class CamStream:
    def __init__(self, cam_id):
        self.id = cam_id
        self.init = None          # son init segmenti (bayt)
        self.mime = None          # 'video/mp4; codecs="avc1.640028"'
        self.gop = []             # son anahtar parçadan bu yana parçalar ([tür+yük] bayt)
        self.gop_bytes = 0
        self.viewers = set()      # VViewer
        self.state = None         # köprünün bildirdiği durum: bekliyor | basliyor | canli | kare_yok | hata | h265 | durdu
        self.detail = ''
        self.stat = {}            # {kbps, fps, w, h, codec, copy}
        self.last_frag = 0.0
        self.frags = 0
        self.bytes = 0
        self.off_task = None      # LINGER sonrası want:false
        self.next_fts = None      # köprünün bildirdiği sonraki parçanın çıkış anı (sunucu saati, ms)
        self.snap = None          # bekleyen anlık görüntü Future'ı
        self.snap_jpg = None      # son anlık görüntü (uydu video kısıtında aralık dolmadan tekrar verilir)
        self.snap_at = 0.0

    def summary(self):
        return {'state': self.state, 'detail': self.detail, 'stat': self.stat, 'mime': self.mime, 'viewers': len(self.viewers),
                'last_frag_age': round(time.time() - self.last_frag, 1) if self.last_frag else None, 'frags': self.frags}


class VBridge:
    def __init__(self, ws, row, host, ver):
        self.ws, self.id, self.name, self.host, self.ver = ws, row['id'], row['name'], host, ver
        self.cams = set()          # bu köprüye gönderilen (yetkili) kamera kimlikleri
        self.cfg_sig = None        # son gönderilen yapılandırmanın imzası (değişmediyse yeniden gönderilmez)
        self.connected_at = db.now()
        self.closing = False


class VViewer:
    def __init__(self, ws, user, cam_id):
        self.ws, self.user, self.cam_id = ws, user, cam_id
        self.q = asyncio.Queue()
        self.pending = 0           # kuyruktaki bayt
        self.need_key = True       # init gönderildikten sonra ilk anahtar parçayı bekler
        self.dropped = 0

    def put(self, item, size=0):
        self.pending += size
        self.q.put_nowait((item, size))


# ---------------- yardımcılar ----------------
def stream(cam_id):
    st = STREAMS.get(cam_id)
    if st is None:
        st = STREAMS[cam_id] = CamStream(cam_id)
    return st


def bridge_online(bridge_id):
    return bridge_id in VBRIDGES


def camera_status(cam):
    """Liste/durum rozeti: pasif | kopru_yok | kopru_cevrimdisi | canli | goruntu_yok | hazir (+ ayrıntı)."""
    if not cam.get('active'):
        return {'status': 'pasif'}
    bid = cam.get('eff_bridge_id', cam.get('bridge_id'))
    if not bid:
        return {'status': 'kopru_yok'}
    if bid not in VBRIDGES:
        return {'status': 'kopru_cevrimdisi'}
    st = STREAMS.get(cam['id'])
    if st is None:
        return {'status': 'hazir'}
    s = st.summary()
    age = s['last_frag_age']
    if age is not None and age < LIVE_S:
        return {'status': 'canli', **s}
    if st.state in ('kare_yok', 'hata') or (st.viewers and age is not None):   # izlenirken parça kesildi ya da köprü kare alamıyor
        return {'status': 'goruntu_yok', **s}
    return {'status': 'hazir', **s}


def cam_cfg(row):
    """Köprüye giden kamera yapılandırması (parola çözülmüş — yalnız köprüye; tarayıcıya ASLA)."""
    return {'id': row['id'], 'name': row['name'], 'kind': row['kind'], 'url': row['url'], 'username': row['username'] or '',
            'password': cameras.decrypt(row['password_enc']) if row['password_enc'] else '', 'transport': row['transport'] or 'tcp',
            'rtp_port': row['rtp_port'], 'codec': row['codec'] or 'h264', 'payload_type': row['payload_type'] or 96, 'sdp': row['sdp'] or '',
            'fps': row['fps'] or 0, 'width': row['width'], 'height': row['height'], 'bitrate_kbps': row['bitrate_kbps']}


def _bridge_cameras(bridge_id):
    with db.connect() as conn:
        rows = db.rows(conn.execute(f'SELECT c.* FROM drone_cameras c WHERE {EFF_BRIDGE} = ? AND c.active = 1 ORDER BY c.id', (bridge_id,)))
    return [cam_cfg(r) for r in rows]


async def _send(ws, obj):
    try:
        await ws.send_text(json.dumps(obj, ensure_ascii=False))
        return True
    except Exception:   # noqa: BLE001
        return False


async def push_cfg(bridge_id, only_changed=False):
    """Kamera kaydı değişti: bağlı köprüye güncel listeyi gönder; artık bu köprüde olmayan kameraların izleyicilerine durum bildir."""
    vb = VBRIDGES.get(bridge_id)
    if vb is None:
        return False
    cams = await asyncio.to_thread(_bridge_cameras, bridge_id)
    sig = json.dumps(cams, sort_keys=True)
    if only_changed and sig == vb.cfg_sig:
        return False
    vb.cfg_sig = sig
    old = set(vb.cams)
    vb.cams = {c['id'] for c in cams}
    await _send(vb.ws, {'t': 'video_cfg', 'cameras': cams})
    for cid in old - vb.cams:
        st = STREAMS.get(cid)
        if st:
            st.init, st.gop, st.gop_bytes, st.state = None, [], 0, 'durdu'
            _to_viewers(st, {'t': 'state', 'state': 'durdu', 'detail': 'Kamera bu köprüden kaldırıldı ya da pasif'})
    for cid in vb.cams:   # izleyicisi olan kameralar için yayını iste
        st = STREAMS.get(cid)
        if st and st.viewers:
            await _send(vb.ws, {'t': 'want', 'camera_id': cid, 'on': True})
    return True


def notify_changed(*bridge_ids):
    """Senkron REST uçlarından (iş parçacığı) çağrılır: ilgili köprülere video_cfg gönderilir."""
    if _loop is None:
        return
    # etkin köprü görev atamasıyla değişebildiği için bağlı TÜM köprüler denetlenir; listesi değişmeyene gönderilmez
    for bid in set(VBRIDGES) | {b for b in bridge_ids if b}:
        try:
            asyncio.run_coroutine_threadsafe(push_cfg(bid, only_changed=True), _loop)
        except RuntimeError:
            pass


def _to_viewers(st, obj):
    txt = json.dumps(obj, ensure_ascii=False)
    for v in list(st.viewers):
        v.put(txt)


def _cam_bridge(cam_id):
    for vb in VBRIDGES.values():
        if cam_id in vb.cams:
            return vb
    return None


async def _want(cam_id, on):
    vb = _cam_bridge(cam_id)
    if vb is not None:
        await _send(vb.ws, {'t': 'want', 'camera_id': cam_id, 'on': bool(on)})


async def disconnect(bridge_id):
    """Görüntü bağlantısını kapatır (Bağlantıyı kes / Kodu yenile). Köprü yeniden bağlanabilir (yeni kodla)."""
    vb = VBRIDGES.get(bridge_id)
    if vb is None:
        return False
    vb.closing = True
    try:
        await vb.ws.close(code=1000)
    except Exception:   # noqa: BLE001
        pass
    return True


def disconnect_threadsafe(bridge_id):
    if _loop is not None and bridge_id in VBRIDGES:
        try:
            asyncio.run_coroutine_threadsafe(disconnect(bridge_id), _loop)
        except RuntimeError:
            pass


def mime_from_init(init):
    """init segmentinden MSE tipi (köprünün vstate.mime'ı init'ten sonra gelebilir): avcC → avc1.PPCCLL; hvc1/hev1 → yaklaşık dizge."""
    i = init.find(b'avcC')
    if i >= 0 and i + 8 <= len(init):
        return 'video/mp4; codecs="avc1.{:02x}{:02x}{:02x}"'.format(init[i + 5], init[i + 6], init[i + 7])
    for tag in (b'hvc1', b'hev1'):
        if init.find(tag) >= 0:
            return f'video/mp4; codecs="{tag.decode()}.1.6.L93.B0"'
    return None


# ---------------- köprüden gelen ikili çerçeveler ----------------
def _on_frame(vb, data):
    if len(data) < 6 or len(data) > FRAME_MAX + 5:
        return
    typ, cam_id = data[0], struct.unpack('>I', data[1:5])[0]
    if cam_id not in vb.cams:
        return   # bu köprüye ait olmayan kamera: yok say
    payload = data[5:]
    st = stream(cam_id)
    if typ == T_INIT:
        if payload[4:8] != b'ftyp':
            return
        st.init = bytes(payload)
        st.mime = mime_from_init(st.init) or st.mime
        st.gop, st.gop_bytes = [], 0
        for v in list(st.viewers):   # yeni init: herkes yeniden başlatır (kodek/çözünürlük değişmiş olabilir)
            v.need_key = True
            v.put(json.dumps({'t': 'init', 'mime': st.mime}))
            v.put(bytes([T_INIT]) + st.init, len(st.init))
        return
    if typ in (T_KEY, T_DELTA):
        if st.init is None:
            return
        frame = bytes([typ]) + payload
        now = time.time()
        fts, src = getattr(st, 'next_fts', None), 'kopru'   # gerçek gecikme: köprü damgası yoksa sunucuya varış anı
        st.next_fts = None
        if fts is None or abs(fts - now * 1000) > 120000:
            fts, src = now * 1000, 'sunucu'
        fmsg = json.dumps({'t': 'fts', 'ms': round(fts), 'src': src})
        st.last_frag, st.frags, st.bytes = now, st.frags + 1, st.bytes + len(payload)
        if typ == T_KEY:
            st.gop, st.gop_bytes = [frame], len(frame)
        elif st.gop and st.gop_bytes + len(frame) <= GOP_MAX:
            st.gop.append(frame)
            st.gop_bytes += len(frame)
        else:
            st.gop, st.gop_bytes = [], 0   # GOP çok uzun: önbellek bırakılır, yeni izleyici sonraki anahtar parçayı bekler
        for v in list(st.viewers):
            if v.need_key and typ != T_KEY:
                continue
            if v.pending + len(frame) > VIEWER_MAX_BYTES:
                v.need_key = True   # yavaş izleyici: bu ve sonraki ara parçalar atlanır
                v.dropped += 1
                continue
            v.need_key = False
            v.put(fmsg)
            v.put(frame, len(frame))
        return
    if typ == T_JPEG:
        fut = st.snap
        if fut is not None and not fut.done():
            fut.set_result(bytes(payload))


def _on_text(vb, msg):
    t = msg.get('t')
    try:
        cid = int(msg.get('camera_id') or 0)
    except (TypeError, ValueError):
        cid = 0
    if t in ('vstate', 'stat', 'snap_err', 'fts') and cid not in vb.cams:
        return None
    if t == 'fts':   # sonraki parçanın köprüden çıkış anı (sunucu saatiyle; köprü ≥ 1.1.4)
        try:
            stream(cid).next_fts = float(msg.get('ms'))
        except (TypeError, ValueError):
            pass
        return t
    if t == 'vstate':
        st = stream(cid)
        yeni = (str(msg.get('state') or '')[:20], str(msg.get('detail') or '')[:300])
        if yeni != (st.state, st.detail):   # tanı: köprünün bildirdiği durum/hata (ffmpeg iletisi) sunucu günlüğüne
            log.warning('Görüntü köprüsü %s (#%s) kamera %s: %s — %s', vb.name, vb.id, cid, yeni[0], yeni[1])
        st.state, st.detail = yeni
        if msg.get('mime'):
            st.mime = str(msg['mime'])[:120]
        _to_viewers(st, {'t': 'state', 'state': st.state, 'detail': st.detail, 'mime': st.mime})
    elif t == 'stat':
        st = stream(cid)
        st.stat = {k: msg.get(k) for k in ('kbps', 'fps', 'w', 'h', 'codec', 'copy', 'src_fps') if msg.get(k) is not None}
        if msg.get('mime'):
            st.mime = str(msg['mime'])[:120]
        _to_viewers(st, {'t': 'stat', **st.stat, 'age': round(time.time() - st.last_frag, 2) if st.last_frag else None})
    elif t == 'snap_err':
        log.warning('Görüntü köprüsü %s (#%s) kamera %s anlık görüntü hatası: %s', vb.name, vb.id, cid, str(msg.get('error') or '')[:300])
        st = stream(cid)
        if st.snap is not None and not st.snap.done():
            st.snap.set_exception(RuntimeError(str(msg.get('error') or 'Anlık görüntü alınamadı')[:300]))
    return t


# ---------------- Köprü: /ws/drone/video ----------------
@ws_router.websocket('/ws/drone/video')
async def ws_video_bridge(ws: WebSocket):
    global _loop
    _loop = asyncio.get_running_loop()
    await ws.accept()
    ip = (ws.client.host if ws.client else '') or ''
    if drone_hub._rate_limited(ip):
        await ws.close(code=4429)
        return
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT))
    except Exception:   # noqa: BLE001
        await ws.close(code=4400)
        return
    row = None
    if first.get('t') == 'auth':
        row = await asyncio.to_thread(drone_hub._resolve_key, str(first.get('key') or ''))
    if row is None:
        drone_hub._note_fail(ip)
        await _send(ws, {'t': 'auth_err', 'code': 4403})
        await ws.close(code=4403)
        return
    vb = VBridge(ws, row, str(first.get('host') or '')[:120], str(first.get('bridge_ver') or '')[:40])
    prev = VBRIDGES.get(vb.id)
    VBRIDGES[vb.id] = vb
    if prev is not None and prev.ws is not ws:   # aynı köprünün ikinci görüntü bağlantısı: eskisi 4409 ile kapanır
        prev.closing = True
        try:
            await prev.ws.close(code=4409)
        except Exception:   # noqa: BLE001
            pass
    cams = await asyncio.to_thread(_bridge_cameras, vb.id)
    vb.cams = {c['id'] for c in cams}
    vb.cfg_sig = json.dumps(cams, sort_keys=True)
    _ensure_resync()
    await _send(ws, {'t': 'auth_ok', 'v': 1, 'bridge_id': vb.id, 'name': vb.name, 'server_time': db.now(), 'cameras': cams})
    for cid in vb.cams:   # bağlantı koptuğunda izleyiciler beklemişse yayını yeniden iste
        st = STREAMS.get(cid)
        if st and st.viewers:
            await _send(ws, {'t': 'want', 'camera_id': cid, 'on': True})
            _to_viewers(st, {'t': 'state', 'state': 'basliyor', 'detail': 'Köprü bağlandı'})
    try:
        while True:
            m = await ws.receive()
            if m.get('type') == 'websocket.disconnect':
                break
            # Veri Paketleri: görüntü köprüden sunucuya uydu hattından gelir (giden yön yalnız küçük denetim mesajları)
            data_packages.count(vb.id, 'kopru_sunucu', len(m.get('bytes') or b'') or len((m.get('text') or '').encode()))
            if m.get('bytes') is not None:
                _on_frame(vb, m['bytes'])
            elif m.get('text'):
                try:
                    msg = json.loads(m['text'])
                except ValueError:
                    continue
                if msg.get('t') == 'ping':
                    await _send(ws, {'t': 'pong', 'server_time': db.now(), 'ms': round(time.time() * 1000), 'c': msg.get('c')})
                else:
                    _on_text(vb, msg)
    except (WebSocketDisconnect, Exception):   # noqa: BLE001
        pass
    finally:
        if VBRIDGES.get(vb.id) is vb:
            VBRIDGES.pop(vb.id, None)
            for cid in vb.cams:
                st = STREAMS.get(cid)
                if st is None:
                    continue
                st.init, st.gop, st.gop_bytes, st.state, st.last_frag = None, [], 0, 'kopru_cevrimdisi', 0.0
                if st.snap is not None and not st.snap.done():
                    st.snap.set_exception(RuntimeError('Köprü bağlantısı koptu'))
                _to_viewers(st, {'t': 'state', 'state': 'kopru_cevrimdisi', 'detail': 'Görüntü köprüsü çevrim dışı'})
                if not st.viewers:
                    STREAMS.pop(cid, None)


# ---------------- Tarayıcı: /ws/drone/video/watch?camera_id=N ----------------
def can_view(user):
    """Kamera görüntüsü: Dron Kameraları okuma, Canlı Uçuş ya da Dron Envanteri (dron paneli) yetkisi."""
    mods = user.get('modules') or []
    return any(k in mods for k in ('drone.cameras', 'field.live', 'drone.drones'))


def can_edit(user):
    return 'drone.cameras' in (user.get('write_modules') or [])


def _with_conn(fn, *a):
    with db.connect() as conn:
        return fn(conn, *a)


def _camera_row(cam_id):
    with db.connect() as conn:
        return db.row(conn.execute(f'SELECT c.id, c.name, {EFF_BRIDGE} AS bridge_id, c.drone_id, c.active, c.kind, c.codec, c.fps FROM drone_cameras c WHERE c.id = ?',
                                   (cam_id,)))


def video_limit(conn, cam_id):
    """Uydu / ücretli hat video kısıtı: kameranın etkin köprüsünü kullanan AÇIK görevdeki uçuşların link.video_pm değerlerinin
    en sıkısı (dakikada kare). 0 = sınırsız (canlı yayın serbest)."""
    bid = effective_bridge(conn, cam_id)
    if bid is None:
        return 0
    lim = 0
    for (txt,) in conn.execute("""SELECT f.link FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                                  WHERE f.bridge_id = ? AND t.status IN ('BASLANGIC', 'GOREVDE') AND f.link IS NOT NULL""", (bid,)):
        try:
            v = int((json.loads(txt) or {}).get('video_pm') or 0)
        except (ValueError, TypeError, AttributeError):
            v = 0
        if v > 0:
            lim = v if not lim else min(lim, v)
    return lim


def snap_cached(cam_id, limit_pm):
    """Kısıtlı kamerada aralık dolmadıysa son kare (yoksa None): birden çok izleyici uydudan fazladan kare çekmez."""
    st = STREAMS.get(cam_id)
    if not limit_pm or st is None or st.snap_jpg is None:
        return None
    return st.snap_jpg if time.time() - st.snap_at < 60.0 / limit_pm else None


def effective_bridge(conn, cam_id):
    r = conn.execute(f'SELECT {EFF_BRIDGE} FROM drone_cameras c WHERE c.id = ?', (cam_id,)).fetchone()
    return r[0] if r else None


_resync_task = None


def _ensure_resync():
    global _resync_task
    if _resync_task is None or _resync_task.done():
        _resync_task = asyncio.get_running_loop().create_task(_resync_loop())


async def _resync_loop():
    """Görev açılıp kapanınca (etkin köprü) ya da başka süreçten kayıt değişince bağlı köprülerin listesi tazelenir."""
    while VBRIDGES:
        await asyncio.sleep(RESYNC_S)
        for bid in list(VBRIDGES):
            try:
                await push_cfg(bid, only_changed=True)
            except Exception:   # noqa: BLE001
                pass


async def _viewer_sender(v):
    try:
        while True:
            item, size = await v.q.get()
            v.pending -= size
            if isinstance(item, (bytes, bytearray)):
                await v.ws.send_bytes(item)
            else:
                await v.ws.send_text(item)
    except Exception:   # noqa: BLE001
        pass


async def _linger_off(st):
    try:
        await asyncio.sleep(LINGER)
    except asyncio.CancelledError:
        return
    st.off_task = None
    if not st.viewers:
        await _want(st.id, False)
        if st.id not in {c for vb in VBRIDGES.values() for c in vb.cams}:
            STREAMS.pop(st.id, None)


@ws_router.websocket('/ws/drone/video/watch')
async def ws_video_watch(ws: WebSocket):
    global _loop
    _loop = asyncio.get_running_loop()
    await ws.accept()
    user = await asyncio.to_thread(drone_hub._ws_user, ws.cookies.get(auth.COOKIE))
    if not user or not can_view(user):
        await _send(ws, {'t': 'error', 'error': 'auth'})
        await ws.close(code=4403)
        return
    try:
        cam_id = int(ws.query_params.get('camera_id') or 0)
    except ValueError:
        cam_id = 0
    cam = await asyncio.to_thread(_camera_row, cam_id) if cam_id else None
    if not cam or not cam['active']:
        await _send(ws, {'t': 'error', 'error': 'Kamera bulunamadı ya da pasif'})
        await ws.close(code=4404)
        return
    limit = await asyncio.to_thread(lambda: _with_conn(video_limit, cam_id))
    if limit:   # uydu video kısıtı: canlı yayın yok; istemci dakikada N kare anlık görüntüye geçer
        await _send(ws, {'t': 'error', 'error': f'Bu uçuşta video dakikada {limit} kare ile sınırlı (uydu veri kısıtı)', 'limit_pm': limit})
        await ws.close(code=4430)
        return
    st = stream(cam_id)
    if len(st.viewers) >= VIEWERS_PER_CAM:
        await _send(ws, {'t': 'error', 'error': 'Bu kamerayı izleyen kişi sayısı sınırda; biraz sonra deneyin'})
        await ws.close(code=4429)
        return
    v = VViewer(ws, user, cam_id)
    first = not st.viewers
    st.viewers.add(v)
    if st.off_task is not None:
        st.off_task.cancel()
        st.off_task = None
    sender = asyncio.create_task(_viewer_sender(v))
    online = cam['bridge_id'] in VBRIDGES and cam_id in VBRIDGES[cam['bridge_id']].cams
    v.put(json.dumps({'t': 'hello', 'camera': {'id': cam['id'], 'name': cam['name'], 'kind': cam['kind'], 'codec': cam['codec'], 'fps': cam['fps']},
                      'bridge_online': online, 'state': st.state if online else 'kopru_cevrimdisi', 'detail': st.detail if online else '',
                      'mime': st.mime, 'stat': st.stat}, ensure_ascii=False))
    if st.init is not None:
        v.put(json.dumps({'t': 'init', 'mime': st.mime}))
        v.put(bytes([T_INIT]) + st.init, len(st.init))
        if st.gop:
            for fr in st.gop:
                v.put(fr, len(fr))
            v.need_key = False
    if first and online:
        await _want(cam_id, True)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get('t') == 'ping':
                v.put(json.dumps({'t': 'pong', 'age': round(time.time() - st.last_frag, 2) if st.last_frag else None,
                                  'ms': round(time.time() * 1000), 'c': msg.get('c')}))
    except (WebSocketDisconnect, Exception):   # noqa: BLE001
        pass
    finally:
        sender.cancel()
        st.viewers.discard(v)
        if not st.viewers and st.off_task is None:
            st.off_task = asyncio.get_running_loop().create_task(_linger_off(st))


# ---------------- JPEG anlık görüntü (REST: routers/drone.py) ----------------
async def snapshot(cam_id, bridge_id, small=False):
    """Köprüden tek JPEG ister (yayın gerekmez). Hata: RuntimeError (çevrim dışı / zaman aşımı / köprü hatası)."""
    vb = VBRIDGES.get(bridge_id)
    if vb is None or cam_id not in vb.cams:
        raise RuntimeError('Görüntü köprüsü çevrim dışı')
    st = stream(cam_id)
    if st.snap is not None and not st.snap.done():
        fut = st.snap   # aynı anda gelen istekler tek isteği paylaşır
    else:
        fut = st.snap = asyncio.get_running_loop().create_future()
        await _send(vb.ws, {'t': 'snap', 'camera_id': cam_id, 'rid': secrets.token_hex(6), **({'small': 1} if small else {})})
    try:
        jpg = await asyncio.wait_for(asyncio.shield(fut), SNAP_TIMEOUT)
    except asyncio.TimeoutError:
        raise RuntimeError('Anlık görüntü zaman aşımı (köprü yanıt vermedi)')
    st.snap_jpg, st.snap_at = jpg, time.time()
    return jpg


def snapshot_all():
    """Yönetim/test: canlı görüntü köprüleri ve akış özetleri."""
    return {'bridges': [{'bridge_id': b.id, 'name': b.name, 'host': b.host, 'bridge_ver': b.ver, 'cameras': sorted(b.cams),
                         'connected_at': b.connected_at} for b in VBRIDGES.values()],
            'streams': {cid: st.summary() for cid, st in STREAMS.items()}}
