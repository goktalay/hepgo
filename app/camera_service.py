"""Kamera servisi (ayrı süreç: `python -m app.camera_service`, systemd: caymaz-cameras).

Her etkin kamera için iki iş parçacığı:
- okuma: RTSP akışını sürekli okur (tampon birikmesin), izleme ekranı için küçültülmüş son kareyi
  data/cameras/live/<id>.jpg olarak ~5 kare/sn yazar; bağlantı koparsa yeniden bağlanır.
- yüz: son kareye saniyede 2 kez YuNet + SFace uygular. Her yüz benzer yüzlerin grubuna (face_groups) katılır;
  grup yoksa açılır. Evrak / kamera yüzlerinden bilinen kişiye benziyorsa o kişinin grubuna gider. Bir grup için
  aynı kamerada en fazla 20 sn'de bir görülme (face_sightings) saklanır: yüz kırpığı ve yüzün görüldüğü anın tam karesi.
Kamera listesi ve grup atamaları (web'den yapılan kişiye atama / birleştirme) periyodik olarak veritabanından okunur.
"""
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import deque

os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS', 'rtsp_transport;tcp|stimeout;5000000')

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from . import cameras as camlib, config, db, shifts  # noqa: E402
from .document_media import KNOWN_PERSON, SFACE, YUNET, _face_crop, _norm, known_identities  # noqa: E402

log = logging.getLogger('camera_service')
LIVE_DIR = config.DATA_DIR / 'cameras' / 'live'
CLIP_DIR = config.UPLOAD_DIR / 'camclips'       # görülme anının kısa videosu (lokal)
FACE_DIR = config.UPLOAD_DIR / 'camfaces'
CLIP_SECONDS, CLIP_FPS = 6, 5                    # kaydedilen klip: görülme öncesi ~6 sn, 5 kare/sn
_CH_RE = re.compile(r'/unicast/c(\d+)/')         # NVR kanal numarası (stream_url'den)
LIVE_EVERY, LIVE_WIDTH = 0.2, 960        # izleme karesi
FACE_EVERY, FACE_WIDTH = 0.5, 1600       # yüz arama (giriş kameralarında uzak/açılı yüzler için daha geniş)
FRAME_WIDTH = 1920                       # saklanan tam kare
MIN_FACE, MIN_SCORE = 36, 0.6            # yürüyen/açılı yüzler 0.9'u geçemiyordu; 0.6 daha çok yakalar
SAME_GROUP = 0.40                        # SFace kosinüs: aynı kişinin grubu
IGNORE_SIM = 0.42                        # silinmiş yüze bu kadar benzeyen yeni görülme listeye alınmaz
STORE_EVERY = 20                         # sn: aynı grup, aynı kamera için görülme saklama aralığı
ISG_EVERY = 90                           # sn: aynı kişi + kamera için İSG/KKD alarmı tekrar aralığı (spam engeli)
_isg_last = {}                           # (cam_id, kind, id) → son alarm zamanı
RELOAD_EVERY = 10                        # sn: kamera listesi ve gruplar


def _resize(img, width):
    h, w = img.shape[:2]
    return img if w <= width else cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)


def _write_jpg(path, img, quality):
    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return False
    tmp = path.with_suffix('.tmp')
    tmp.write_bytes(buf.tobytes())
    os.replace(tmp, path)
    return True


class Identities:
    """Yüz grupları (ağırlık merkezleri) ve evraklardan bilinen kişiler; kamera iş parçacıkları arasında paylaşılır."""

    def __init__(self):
        self.lock = threading.Lock()
        self.groups = {}      # id → {'c': ndarray, 'n', 'person_id', 'user_id'}
        self.known = []       # [(('person'|'user', id), iz)] evraklardan
        self.ignored = []     # silinen grupların izleri (kara liste)
        self.last_store = {}  # (grup, kamera) → zaman
        self.loaded = 0

    def reload(self):
        with db.connect() as conn:
            rows = conn.execute('SELECT id, centroid, samples, person_id, user_id, family_id, visitor_id FROM face_groups').fetchall()
            known = known_identities(conn)
            try:
                ign = [np.frombuffer(r[0], dtype=np.float32) for r in conn.execute('SELECT centroid FROM face_ignored')]
            except Exception:   # noqa: BLE001 — tablo yoksa
                ign = []
        with self.lock:
            self.groups = {r[0]: {'c': np.frombuffer(r[1], dtype=np.float32).copy(), 'n': r[2], 'person_id': r[3], 'user_id': r[4], 'family_id': r[5], 'visitor_id': r[6]}
                           for r in rows}
            self.known = known
            self.ignored = ign
            self.loaded = time.time()

    def is_ignored(self, emb):
        """Silinmiş (gereksiz) bir yüze benziyor mu? Benziyorsa yeni görülme listeye alınmaz."""
        with self.lock:
            return any(float(np.dot(v, emb)) >= IGNORE_SIM for v in getattr(self, 'ignored', ()))

    def assign(self, emb):
        """Yüzün grubu: (grup id, yeni mi). Önce en benzer grup, sonra evraklardan bilinen kişi, yoksa yeni grup."""
        with self.lock:
            best, best_sim = None, SAME_GROUP
            for gid, g in self.groups.items():
                sim = float(np.dot(g['c'], emb))
                if sim >= best_sim:
                    best, best_sim = gid, sim
            if best is not None:
                g = self.groups[best]
                g['c'] = _norm(g['c'] * min(g['n'], 50) + emb).astype(np.float32)   # iz yavaşça güncellenir
                g['n'] += 1
                return best, None
            who, who_sim = None, KNOWN_PERSON
            for key, v in self.known:
                sim = float(np.dot(v, emb))
                if sim >= who_sim:
                    who, who_sim = key, sim
            if who:   # bilinen kişinin grubu varsa ona
                col = {'person': 'person_id', 'user': 'user_id', 'family': 'family_id', 'visitor': 'visitor_id'}[who[0]]
                gid = next((i for i, g in self.groups.items() if g.get(col) == who[1]), None)
                if gid is not None:
                    return gid, None
            return None, who

    def identify(self, emb):
        """Salt-okunur: yüz tanınan (atanmış ya da eğitilmiş) bir kişiye mi ait? ('person'|'user', id) ya da None.
        Canlı çerçeve etiketi için; grupları değiştirmez."""
        with self.lock:
            best, sim0 = None, SAME_GROUP
            for g in self.groups.values():
                if g.get('person_id') or g.get('user_id') or g.get('family_id') or g.get('visitor_id'):
                    sim = float(np.dot(g['c'], emb))
                    if sim >= sim0:
                        best = (('person', g['person_id']) if g['person_id'] else
                                ('user', g['user_id']) if g['user_id'] else
                                ('family', g['family_id']) if g['family_id'] else ('visitor', g['visitor_id']))
                        sim0 = sim
            if best:
                return best
            who, who_sim = None, KNOWN_PERSON
            for key, v in self.known:
                sim = float(np.dot(v, emb))
                if sim >= who_sim:
                    who, who_sim = key, sim
            return who


def _write_overlay(cid, boxes):
    """Canlı çerçeve metadata'sı (yüz kutuları + kimlik) — izleme ekranı overlay'i için. live/<cid>.json."""
    try:
        LIVE_DIR.mkdir(parents=True, exist_ok=True)
        p = LIVE_DIR / f'{cid}.json'
        tmp = p.with_suffix('.json.tmp')
        tmp.write_text(json.dumps({'boxes': boxes, 'ts': time.time()}))
        os.replace(tmp, p)
    except Exception:   # noqa: BLE001
        pass


def _channel_of(stream_url):
    m = _CH_RE.search(stream_url or '')
    return int(m.group(1)) if m else None


class Schedule:
    """NVR kanallarının yüz-tanıma zamanlaması (tüm gün / gündüz / gece / özel) + fabrika vardiyası. app_kv'den okunur."""

    def __init__(self):
        self.ch = {}
        self.shift = {k: list(v) for k, v in shifts.DEFAULT.items()}
        self.score = MIN_SCORE      # yüz tanıma eşiği (eklenti ayarlarından değişir)
        self.min_face = MIN_FACE
        self.ppe_req = {}           # İSG/KKD: "type:id" → ['kask',...] (kamerayla denetlenecek zorunlu KKD)

    def reload(self):
        try:
            with db.connect() as conn:
                self.shift = shifts.get(conn)
                row = conn.execute("SELECT v FROM app_kv WHERE k = 'nvr_channels'").fetchone()
                self.ch = json.loads(row[0]) if row else {}
                cfg = conn.execute("SELECT v FROM app_kv WHERE k = 'facerec_config'").fetchone()
                if cfg:
                    d = json.loads(cfg[0])
                    self.score = float(d.get('score', MIN_SCORE))
                    self.min_face = int(d.get('min_face', MIN_FACE))
                prow = conn.execute("SELECT v FROM app_kv WHERE k = 'ppe_required'").fetchone()
                self.ppe_req = (json.loads(prow[0]) if prow else {}) or {}
        except Exception:   # noqa: BLE001 — okunamazsa varsayılanlar
            self.ch = {}

    def active(self, channel):
        """Bu kanalda şu an yüz tanıma çalışmalı mı? NVR dışı kameralar (channel None) daima aktif."""
        if channel is None:
            return True
        c = self.ch.get(str(channel))
        if not c:
            return True
        sched = c.get('schedule', 'all')
        if sched == 'all':
            return True
        now = time.strftime('%H:%M')
        if sched == 'day':
            return shifts.in_window(now, *self.shift['day'])
        if sched == 'night':
            return shifts.in_window(now, *self.shift['night'])
        if sched == 'custom':
            return any(a and b and shifts.in_window(now, a, b) for a, b in c.get('custom', []))
        return True


def _write_clip(frames, out_path):
    """Tampondaki kareleri küçük bir MP4 olarak yazar (lokal). En büyük kareye göre boyutlandırır."""
    if not frames:
        return False
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*'mp4v'), CLIP_FPS, (w, h))
    if not writer.isOpened():
        return False
    try:
        for fr in frames:
            writer.write(fr if fr.shape[:2] == (h, w) else cv2.resize(fr, (w, h)))
    finally:
        writer.release()
    return True


def _store_sighting(ident, cam_id, emb, crop, frame, score, now_iso, threshold=None):
    """Grubu günceller ya da yeni grup açar; 20 sn kuralına göre görülmeyi (kırpık + tam kare) saklar."""
    gid, who = ident.assign(emb)
    if gid is None and not who and ident.is_ignored(emb):   # silinmiş (gereksiz) yüze benziyor → listeye alma
        return None
    now = time.time()
    FACE_DIR.mkdir(parents=True, exist_ok=True)
    with db.connect() as conn:
        conn.execute('PRAGMA foreign_keys = OFF')   # fabrika aynası: eşleşen kişi/aile id'si yerelde olmayabilir
        if gid is None:
            name = uuid.uuid4().hex
            _write_jpg(FACE_DIR / f'{name}.jpg', crop, 88)
            pid = who[1] if who and who[0] == 'person' else None
            uid = who[1] if who and who[0] == 'user' else None
            fid = who[1] if who and who[0] == 'family' else None
            vid = who[1] if who and who[0] == 'visitor' else None
            cur = conn.execute(
                '''INSERT INTO face_groups (person_id, user_id, family_id, visitor_id, centroid, samples, best_crop, best_score, first_seen, last_seen, last_camera)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (pid, uid, fid, vid, emb.astype(np.float32).tobytes(), 1, f'camfaces/{name}.jpg', score, now_iso, now_iso, cam_id))
            gid = cur.lastrowid
            with ident.lock:
                ident.groups[gid] = {'c': emb.astype(np.float32), 'n': 1, 'person_id': pid, 'user_id': uid, 'family_id': fid, 'visitor_id': vid}
            crop_path = f'camfaces/{name}.jpg'
        else:
            g = ident.groups.get(gid)
            conn.execute('UPDATE face_groups SET centroid = ?, samples = samples + 1, last_seen = ?, last_camera = ? WHERE id = ?',
                         (g['c'].tobytes() if g else emb.tobytes(), now_iso, cam_id, gid))
            crop_path = None
        key = (gid, cam_id)
        if now - ident.last_store.get(key, 0) < STORE_EVERY:
            return None
        ident.last_store[key] = now
        if crop_path is None:
            name = uuid.uuid4().hex
            _write_jpg(FACE_DIR / f'{name}.jpg', crop, 88)
            crop_path = f'camfaces/{name}.jpg'
            best = conn.execute('SELECT best_score FROM face_groups WHERE id = ?', (gid,)).fetchone()
            if best and score > best[0]:   # grubun en iyi yüzü
                conn.execute('UPDATE face_groups SET best_crop = ?, best_score = ? WHERE id = ?', (crop_path, score, gid))
        fname = uuid.uuid4().hex
        _write_jpg(FACE_DIR / f'{fname}.jpg', frame, 85)
        cur = conn.execute('INSERT INTO face_sightings (group_id, camera_id, at, crop, frame, embedding, score, threshold) VALUES (?,?,?,?,?,?,?,?)',
                           (gid, cam_id, now_iso, crop_path, f'camfaces/{fname}.jpg', emb.astype(np.float32).tobytes(), score, threshold))
        return cur.lastrowid


class Camera:
    def __init__(self, row, ident, sched=None):
        self.row, self.ident, self.sched = row, ident, sched
        self.channel = _channel_of(row['stream_url'])   # NVR kanalı (zamanlama için); NVR dışı ise None
        self.stop = threading.Event()
        self.latest = None   # (zaman, kare)
        self.clipbuf = deque(maxlen=CLIP_SECONDS * CLIP_FPS)   # son ~6 sn küçük kare (klip için)
        self._last_buf = 0
        self.status = None
        self.threads = [threading.Thread(target=self._read, daemon=True, name=f'cam{row["id"]}-read')]
        if row['faces']:
            self.threads.append(threading.Thread(target=self._faces, daemon=True, name=f'cam{row["id"]}-faces'))
        for t in self.threads:
            t.start()

    def _set(self, status, error=None, frame_at=None):
        if status == self.status and frame_at is None:
            return
        self.status = status
        try:
            with db.connect() as conn:
                conn.execute('UPDATE cameras SET status = ?, error = ?, last_frame_at = COALESCE(?, last_frame_at) WHERE id = ?',
                             (status, error, frame_at, self.row['id']))
        except Exception:
            log.exception('durum yazılamadı')

    def _read(self):
        cid = self.row['id']
        LIVE_DIR.mkdir(parents=True, exist_ok=True)
        live = LIVE_DIR / f'{cid}.jpg'
        url = camlib.with_credentials(self.row['stream_url'], self.row['username'], camlib.decrypt(self.row['password_enc']))
        is_file = os.path.exists(self.row['stream_url'] or '')
        while not self.stop.is_set():
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                self._set('HATA', 'Akışa bağlanılamadı')
                self.stop.wait(10)
                continue
            self._set('CANLI')
            last_live = last_beat = 0
            fails = 0
            delay = 1 / max(1, cap.get(cv2.CAP_PROP_FPS) or 25) if is_file else 0
            while not self.stop.is_set():
                ok, img = cap.read()
                if not ok:
                    fails += 1
                    if fails > 25:
                        break
                    time.sleep(0.1)
                    continue
                fails = 0
                now = time.time()
                self.latest = (now, img)
                if now - self._last_buf >= 1 / CLIP_FPS:   # klip tamponu (küçük kare)
                    self._last_buf = now
                    self.clipbuf.append(_resize(img, 640))
                if now - last_live >= LIVE_EVERY:
                    last_live = now
                    _write_jpg(live, _resize(img, LIVE_WIDTH), 72)
                if now - last_beat >= 10:
                    last_beat = now
                    self._set('CANLI', None, db.now())
                if delay:
                    time.sleep(delay)   # dosya kaynağı (deneme): gerçek hızında oynatılır
            cap.release()
            if not self.stop.is_set():
                self._set('KOPTU', 'Görüntü kesildi; yeniden bağlanılıyor')
                self.stop.wait(3)

    def _faces(self):
        detector = cv2.FaceDetectorYN.create(str(YUNET), '', (320, 320), MIN_SCORE, 0.3, 50)
        recognizer = cv2.FaceRecognizerSF.create(str(SFACE), '')
        seen_at = 0
        while not self.stop.is_set():
            self.stop.wait(FACE_EVERY)
            if not self.latest or self.latest[0] == seen_at:
                continue
            if self.sched is not None and not self.sched.active(self.channel):
                continue   # kanalın zamanlaması dışında (ör. sadece gündüz) — yüz tanıma atlanır
            seen_at, frame = self.latest
            try:
                score_thr = self.sched.score if self.sched else MIN_SCORE
                min_face = self.sched.min_face if self.sched else MIN_FACE
                detector.setScoreThreshold(score_thr)   # eşik eklenti ayarlarından değişebilir
                img = _resize(frame, FACE_WIDTH)
                h, w = img.shape[:2]
                detector.setInputSize((w, h))
                _, faces = detector.detect(img)
                boxes = []
                full = None
                idfaces = []   # (f, who) — kabul edilen yüzler; İSG/KKD denetimi için
                now_iso = db.now()
                for f in (faces if faces is not None else []):
                    if min(f[2], f[3]) < min_face:
                        continue
                    emb = _norm(recognizer.feature(recognizer.alignCrop(img, f)).flatten().astype(np.float32))
                    who = self.ident.identify(emb)   # canlı çerçeve etiketi (salt-okunur)
                    boxes.append({'x': round(float(f[0]) / w, 4), 'y': round(float(f[1]) / h, 4),
                                  'w': round(float(f[2]) / w, 4), 'h': round(float(f[3]) / h, 4),
                                  'kind': who[0] if who else None, 'id': who[1] if who else None})
                    idfaces.append((f, who))
                    full = full if full is not None else _resize(frame, FRAME_WIDTH)
                    sid = _store_sighting(self.ident, self.row['id'], emb, _face_crop(img, f), full, float(f[2] * f[3] * f[14]), now_iso, round(score_thr, 2))
                    if sid:
                        self._save_clip(sid)
                _write_overlay(self.row['id'], boxes)   # yüz yoksa boş → çerçeveler temizlenir
                self._isg_check(img, w, h, idfaces, now_iso)   # İSG/KKD denetimi (model yoksa anında döner)
            except Exception:
                log.exception('yüz işleme hatası (kamera %s)', self.row['id'])

    def _isg_check(self, img, w, h, idfaces, now_iso):
        """İSG/KKD denetimi: tanınan + zorunlu KKD'si olan kişiler için kask/eldiven vb. eksikse isg_alarms üretir.
        KKD modeli yoksa (ppe.available()=False) ya da denetlenecek kişi yoksa hiçbir iş yapmaz (yüz tanımayı etkilemez)."""
        try:
            req_map = self.sched.ppe_req if self.sched else {}
            if not req_map or not idfaces:
                return
            targets = []   # (f, who, required)
            for f, who in idfaces:
                if not who:
                    continue
                required = req_map.get(f'{who[0]}:{who[1]}')
                if required:
                    targets.append((f, who, required))
            if not targets:
                return
            from . import ppe
            if not ppe.available():
                return
            dets = ppe.detect(img)
            for f, who, required in targets:
                missing = ppe.missing_for(required, dets, [float(f[0]), float(f[1]), float(f[2]), float(f[3])], w, h)
                if missing:
                    self._store_isg_alarm(who, missing, _face_crop(img, f), now_iso)
        except Exception:   # noqa: BLE001 — İSG denetim hatası yüz tanımayı durdurmamalı
            log.exception('İSG/KKD denetim hatası (kamera %s)', self.row['id'])

    def _store_isg_alarm(self, who, missing, crop, now_iso):
        """İSG alarmını yerel DB'ye yazar (spam engelli). Bulut facecore.isg_alarms ile çeker, isimleri çözer."""
        key = (self.row['id'], who[0], who[1])
        now = time.time()
        if now - _isg_last.get(key, 0) < ISG_EVERY:
            return
        _isg_last[key] = now
        col = {'user': 'user_id', 'person': 'person_id', 'family': 'family_id', 'visitor': 'visitor_id'}.get(who[0])
        if not col:
            return
        FACE_DIR.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex
        try:
            _write_jpg(FACE_DIR / f'{name}.jpg', crop, 88)
            crop_path = f'camfaces/{name}.jpg'
        except Exception:   # noqa: BLE001
            crop_path = None
        try:
            cam_name = self.row['name']
        except Exception:   # noqa: BLE001
            cam_name = None
        with db.connect() as conn:
            conn.execute('PRAGMA foreign_keys = OFF')
            conn.execute(
                f'''INSERT INTO isg_alarms (camera_id, camera_name, subject_type, {col}, missing, at, crop, created_at)
                    VALUES (?,?,?,?,?,?,?,?)''',
                (self.row['id'], cam_name, who[0], who[1], json.dumps(missing), now_iso, crop_path, now_iso))

    def _save_clip(self, sighting_id):
        """Görülme anının kısa videosunu (tampondaki son ~6 sn) lokal olarak kaydeder ve kayda bağlar. En iyi çaba."""
        try:
            frames = list(self.clipbuf)
            if len(frames) < CLIP_FPS:   # en az ~1 sn
                return
            CLIP_DIR.mkdir(parents=True, exist_ok=True)
            name = f'{uuid.uuid4().hex}.mp4'
            if _write_clip(frames, CLIP_DIR / name):
                with db.connect() as conn:
                    conn.execute('UPDATE face_sightings SET clip = ? WHERE id = ?', (f'camclips/{name}', sighting_id))
        except Exception:   # noqa: BLE001 — klip kaydı başarısız olsa da tanıma sürer
            log.exception('klip kaydedilemedi (kamera %s)', self.row['id'])

    def close(self):
        self.stop.set()


def _signature(r):
    return (r['stream_url'], r['username'], r['password_enc'], r['faces'])


def _watched_ids():
    """Canlı izleme talebi olan kamera id'leri (app_kv['live_watch'], süresi dolmamış). Bulut, kare çektikçe tazeler."""
    try:
        with db.connect() as conn:
            row = conn.execute("SELECT v FROM app_kv WHERE k = 'live_watch'").fetchone()
        if not row:
            return set()
        d = json.loads(row[0]) or {}
        now = time.time()
        return {int(k) for k, v in d.items() if float(v) > now}
    except Exception:
        return set()


WATCH_TICK = 2   # sn: canlı izleme talebini hızlı yakalamak için döngü sıklığı (ağır yenileme RELOAD_EVERY'de)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    cv2.setNumThreads(2)
    db.init()
    ident = Identities()
    sched = Schedule()
    running = {}   # id → (imza, Camera)
    last_heavy = 0
    log.info('kamera servisi başladı (%s)', config.DATA_DIR)
    while True:
        try:
            now = time.time()
            if now - last_heavy >= RELOAD_EVERY:   # yüz grupları + zamanlama ağır; seyrek yenile
                last_heavy = now
                ident.reload()
                sched.reload()
            watched = _watched_ids()
            with db.connect() as conn:
                allrows = {r['id']: r for r in db.rows(conn.execute(
                    "SELECT * FROM cameras WHERE stream_url IS NOT NULL AND stream_url != ''"))}
            want = {}
            for cid, r in allrows.items():
                if r['active']:                 # yüz tanıma açık kanal: canlı + yüz
                    want[cid] = r
                elif cid in watched:            # yüz tanıma kapalı ama izleniyor: yalnız canlı
                    rr = dict(r)
                    rr['faces'] = 0
                    want[cid] = rr
            for cid in list(running):
                if cid not in want or _signature(want[cid]) != running[cid][0]:
                    running.pop(cid)[1].close()
                    log.info('kamera %s durduruldu', cid)
            for cid, r in want.items():
                if cid not in running:
                    running[cid] = (_signature(r), Camera(r, ident, sched))
                    log.info('kamera %s (%s) başlatıldı%s', cid, r['name'], '' if r['faces'] else ' (yalnız izleme)')
            with db.connect() as conn:   # çalışmayan (pasif + izlenmeyen) kameraları KAPALI işaretle
                keep = tuple(want) or (-1,)
                conn.execute(f"UPDATE cameras SET status = 'KAPALI' WHERE active = 0 AND COALESCE(status, '') != 'KAPALI' "
                             f"AND id NOT IN ({','.join('?' * len(keep))})", keep)
        except Exception:
            log.exception('kamera döngüsü hatası')
        time.sleep(WATCH_TICK)


if __name__ == '__main__':
    main()
