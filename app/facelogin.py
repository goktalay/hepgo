"""Yüz ile giriş (Face ID tarzı) — çekirdek: gömme hesabı, eğitim oturumu, giriş meydan okuması, eşleme.

TEKNİK SEÇİM (bkz. docs/yuz-tanima.md §1): yüz tespiti + gömme (embedding) SUNUCUDA, kamera modülüyle AYNI modellerle
yapılır — YuNet 2023mar (tespit + 5 nokta, 233 KB) ve SFace 2021dec (128-d gömme, 38,7 MB), ikisi de OpenCV Zoo /
Apache-2.0, `vendor/models/`. Tarayıcı yalnızca küçük JPEG kareler (≈480 px, ~30 KB) gönderir; gömme İSTEMCİDEN HİÇ
KABUL EDİLMEZ (sahte gömme enjeksiyonu imkânsız) ve biyometrik şablon istemciye hiç dönmez. Tarayıcıya model indirme,
wasm/CSP/worker değişikliği, iOS Safari wasm sorunu yok; SFace 38,7 MB zaten "≤ 10 MB" sınırına sığmazdı.

VERİ: user_face (kullanıcı başına tek satır); gömmeler cameras.encrypt ile şifreli JSON (nonce + HMAC-SHA256 etiket +
XOR akışı, anahtar DATA_DIR/cameras.key 0600). Ham kare / kırpık SAKLANMAZ. KVKK: kullanıcının kendi hesabı için açık
tercih; "Yüz verisini sil" tek tıkla kalıcı siler (audit).

GİRİŞ AKIŞI: yalnızca GÜVENİLİR CİHAZ (trusted_devices; PIN ile aynı kural) → POST challenge (tek kullanımlık nonce,
60 sn, rastgele canlılık yönü) → kareler POST verify: (1) eşleme aşaması: kosinüs ≥ eşik (policy.face_threshold / 100)
(2) canlılık aşaması: istenen yöne baş çevirme (yaw/pitch) + eşleşme sürer → (3) kipe göre oturum ya da PIN adımı.
Eşleşmeyen kare sayısı sınırı aşılınca meydan okuma kapanır ve login_logs'a başarısız giriş yazılır (kaba kuvvet kilidi
PIN ile aynı: policy.lockout_*). Hız sınırı: kullanıcı/IP başına dakikada en çok FACE_RATE meydan okuma.

SINIRLAR (dürüstçe): canlılık yalnızca "baş çevirme" (fotoğrafı yener; yüksek çözünürlüklü VİDEO replay'ini yenmez);
derin canlılık (IR/3B/ışık yanıtı) yok. Bu yüzden yüz girişi güvenilir cihaza bağlıdır ve isteğe bağlı "yüz + PIN" kipi
vardır. Ağ üzerindeki kare TLS ile korunur (HTTPS zorunlu — getUserMedia zaten yalnız güvenli bağlamda çalışır).
"""
import base64
import json
import math
import os
import secrets
import threading
import time

import numpy as np

from . import cameras, config, db

MODEL_VER = 'yunet2023mar+sface2021dec'
EMB_DIM = 128
# 8 yön (ekran koordinatı: kullanıcının kendi sağı = 'right'; ön kamera aynalı gösterildiği için ham yaw ters çevrilir)
SEGMENTS = ['right', 'up_right', 'up', 'up_left', 'left', 'down_left', 'down', 'down_right']
SLOTS = ['center', *SEGMENTS]
# Eğitim kabulü için en az dolu yuva (merkez zorunlu). Üretimde 5; yalnız test ortamı (sentetik yüz yukarı/aşağı bakamaz) 3'e düşürür.
MIN_SLOTS = max(3, min(9, int(os.environ.get('CAYMAZ_FACE_MIN_SLOTS', '5') or 5)))
MAX_EMB = 18             # kullanıcı başına en çok gömme (ikinci tarama ile)
R_CENTER = 0.14          # |pose| < R_CENTER → merkez
R_SEG = 0.20             # |pose| ≥ R_SEG → yön segmenti (arası: belirsiz, yuva verilmez)
R_REF = 0.35             # referans (kalibrasyon) karesi için kaba merkez kapısı: |ham poz| < R_REF
# Poz KALİBRASYONU: _head_pose'un nötr sabitleri (0,55 / 0,45) kişiye ve kameraya göre ±0,15 kayar (burun uzunluğu,
# kamera yüksekliği). Eğitimde ve girişte ilk "merkez" karesi referans alınır; sonraki pozlar referansa GÖRE ölçülür
# (iPhone da başlangıç duruşunu merkez sayar). Böylece 8 yön ve canlılık adımı herkeste aynı davranır.
SAME_FACE = 0.30         # eğitimde: merkez kaydına göre bu kadar benzemeyen yüz başka kişidir → eklenmez
ENROLL_TTL = 10 * 60     # eğitim oturumu ömrü (sn)
CHALLENGE_TTL = 60       # giriş meydan okuması ömrü (sn)
MAX_FRAMES = 60          # bir meydan okumada en çok işlenen kare
MAX_MISS = 10            # eşleşmeyen yüz karesi sınırı → başarısız giriş
FACE_RATE = 5            # kullanıcı ya da IP başına dakikada meydan okuma
# İstenebilecek canlılık yönleri (CAYMAZ_FACE_POSES ile daraltılabilir; ör. test ortamında sentetik yüz yukarı bakamaz → 'left,right')
LIVENESS_POSES = [p for p in os.environ.get('CAYMAZ_FACE_POSES', 'left,right,up').split(',') if p in ('left', 'right', 'up', 'down')] or ['left', 'right']
POSE_MIN = 0.18          # canlılık adımında yön bileşeninin en az büyüklüğü
MIN_FACE = 56            # piksel: daha küçük yüz "yaklaşın"
MIN_DET = 0.7            # YuNet skor eşiği

_lock = threading.Lock()
_models = {}             # 'det:WxH' → FaceDetectorYN, 'rec' → FaceRecognizerSF


def engine_available():
    """Yüz motoru bu sunucuda çalışır mı (modeller + OpenCV) ya da fabrika köprüsü (remote) var mı?"""
    try:
        from . import document_media as dm, facebridge
        if facebridge.remote():
            return True
        if not dm.faces_available():
            return False
        import cv2  # noqa: F401
        return hasattr(cv2, 'FaceDetectorYN')
    except Exception:   # noqa: BLE001
        return False


def _norm(v):
    v = np.asarray(v, dtype=np.float32).flatten()
    n = float(np.linalg.norm(v))
    return v / n if n else v


def cosine(a, b):
    return float(np.dot(_norm(a), _norm(b)))


def segment_of(yaw, pitch, mirror=True):
    """Ham baş pozundan (facecore._head_pose: yaw>0 görüntüde sağa = kullanıcının SOLU) ekran yuvası.
    Dönüş: 'center' | SEGMENTS[i] | None (ara bölge). Ekran yönleri: sağ=0°, üst=90° (pitch<0 yukarı)."""
    sx = -yaw if mirror else yaw
    sy = -pitch
    r = math.hypot(sx, sy)
    if r < R_CENTER:
        return 'center'
    if r < R_SEG:
        return None
    ang = math.degrees(math.atan2(sy, sx)) % 360.0
    return SEGMENTS[int(((ang + 22.5) % 360.0) // 45.0)]


def pose_matches(yaw, pitch, want, mirror=True):
    """Canlılık: istenen yöne (left/right/up/down) yeterince bakılıyor mu?"""
    sx = -yaw if mirror else yaw
    sy = -pitch
    return {'right': sx >= POSE_MIN, 'left': sx <= -POSE_MIN, 'up': sy >= POSE_MIN, 'down': sy <= -POSE_MIN}.get(want, False)


# ---------- gömme hesabı (sunucu; testte EMBED değiştirilebilir)

def _embed_local(jpg_b64):
    """Tek kare → en büyük yüzün gömmesi + poz. Modeller önbellekte, tek kilit (cv2 nesneleri iş parçacığı güvenli değil)."""
    import cv2
    from . import document_media as dm, facecore
    try:
        buf = base64.b64decode(jpg_b64 or '')
    except Exception:   # noqa: BLE001
        buf = b''
    if not buf or len(buf) > 2_000_000:
        return {'found': False}
    img = facecore._decode_bgr(buf)
    if img is None:
        return {'found': False}
    h, w = img.shape[:2]
    if w > 1280 or h > 1280:   # çok büyük kareyi küçült (hız + sabit ölçek)
        s = 1280.0 / max(w, h)
        img = cv2.resize(img, (int(w * s), int(h * s)))
        h, w = img.shape[:2]
    with _lock:
        key = f'det:{w}x{h}'
        det = _models.get(key)
        if det is None:
            det = dm.make_face_detector((w, h), score=MIN_DET, nms=0.3, top_k=50)
            det.setInputSize((w, h))
            _models[key] = det
            for k in [k for k in _models if k.startswith('det:') and k != key][:-3]:   # en çok 4 boyut önbellekte
                _models.pop(k, None)
        rec = _models.get('rec')
        if rec is None:
            rec = _models['rec'] = dm.make_face_recognizer()
        _, faces = det.detect(img)
        faces = [f for f in (faces if faces is not None else []) if min(float(f[2]), float(f[3])) >= 8]
        if not faces:
            return {'found': False, 'w': w, 'h': h}
        f = max(faces, key=lambda x: float(x[2]) * float(x[3]))
        if min(float(f[2]), float(f[3])) < MIN_FACE:
            return {'found': False, 'w': w, 'h': h, 'small': True,
                    'box': [round(float(f[0])), round(float(f[1])), round(float(f[2])), round(float(f[3]))]}
        emb = _norm(rec.feature(rec.alignCrop(img, f)).flatten())
    yaw, pitch = facecore._head_pose(f)
    return {'found': True, 'w': w, 'h': h, 'faces': len(faces),
            'box': [round(float(f[0])), round(float(f[1])), round(float(f[2])), round(float(f[3]))],
            'score': round(float(f[14]), 3), 'yaw': round(yaw, 3), 'pitch': round(pitch, 3), 'emb': emb}


def _embed_remote(jpg_b64):
    """Dağıtık kurulum (AGENT_MODE=remote): kare fabrika yüz ajanında işlenir (facecore.embed_frame)."""
    from . import facebridge
    r = facebridge.rpc('embed_frame', jpg=jpg_b64)
    if not isinstance(r, dict) or not r.get('found'):
        return {'found': False}
    emb = _norm(np.frombuffer(base64.b64decode(r['embedding']), dtype=np.float32))
    return {'found': True, 'w': r.get('w'), 'h': r.get('h'), 'box': r.get('box'), 'score': r.get('score'),
            'yaw': r.get('yaw') or 0.0, 'pitch': r.get('pitch') or 0.0, 'emb': emb}


def _embed(jpg_b64):
    from . import facebridge
    return _embed_remote(jpg_b64) if facebridge.remote() else _embed_local(jpg_b64)


EMBED = _embed   # testler sahte gömme için değiştirir: facelogin.EMBED = lambda jpg: {...}


def embed(jpg_b64):
    return EMBED(jpg_b64)


# ---------- kalıcı kayıt (user_face)

def _pack(embs, slots):
    return cameras.encrypt(json.dumps({'v': 1, 'embeddings': [[round(float(x), 5) for x in e] for e in embs], 'slots': slots}))


def _unpack(blob):
    try:
        d = json.loads(cameras.decrypt(blob) or '{}')
        embs = [np.asarray(e, dtype=np.float32) for e in d.get('embeddings', []) if len(e) == EMB_DIM]
        return embs, list(d.get('slots', []))
    except Exception:   # noqa: BLE001
        return [], []


def record(conn, uid):
    return db.row(conn.execute('SELECT user_id, data, model_ver, mode, enabled, count, created_at, updated_at FROM user_face WHERE user_id = ?', (uid,)))


def status(conn, uid):
    r = record(conn, uid)
    return {'enrolled': bool(r and r['enabled'] and r['count']), 'count': (r or {}).get('count') or 0,
            'mode': (r or {}).get('mode') or 'face', 'updated_at': (r or {}).get('updated_at'),
            'created_at': (r or {}).get('created_at'), 'model_ver': (r or {}).get('model_ver')}


def embeddings_of(conn, uid):
    r = record(conn, uid)
    if not r or not r['enabled']:
        return []
    return _unpack(r['data'])[0]


def has_face(conn, uid):
    r = conn.execute('SELECT enabled, count FROM user_face WHERE user_id = ?', (uid,)).fetchone()
    return bool(r and r[0] and r[1])


def save(conn, uid, embs, slots, mode=None, append=False):
    """Eğitim sonucunu yazar. append: mevcut gömmelere ekler (ikinci tarama), en çok MAX_EMB."""
    old = record(conn, uid)
    if append and old:
        oe, os_ = _unpack(old['data'])
        embs, slots = [*oe, *embs][-MAX_EMB:], [*os_, *slots][-MAX_EMB:]
    mode = mode or (old['mode'] if old else None) or 'face'
    now = db.now()
    conn.execute('''INSERT INTO user_face (user_id, data, model_ver, mode, enabled, count, created_at, updated_at)
                    VALUES (?,?,?,?,1,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, model_ver = excluded.model_ver, mode = excluded.mode,
                      enabled = 1, count = excluded.count, updated_at = excluded.updated_at''',
                 (uid, _pack(embs, slots), MODEL_VER, mode, len(embs), old['created_at'] if old else now, now))
    return len(embs)


def set_mode(conn, uid, mode):
    if mode not in ('face', 'face_pin'):
        raise ValueError('Geçersiz kip')
    conn.execute('UPDATE user_face SET mode = ?, updated_at = ? WHERE user_id = ?', (mode, db.now(), uid))


def delete(conn, uid):
    cur = conn.execute('DELETE FROM user_face WHERE user_id = ?', (uid,))
    return cur.rowcount > 0


def match(embs, emb):
    """Kayıtlı gömmelere karşı en iyi kosinüs benzerliği (0 → kayıt yok)."""
    if not embs:
        return 0.0
    e = _norm(emb)
    return max(float(np.dot(_norm(x), e)) for x in embs)


# ---------- eğitim oturumları (bellek; 10 dk)

_enroll = {}    # eid → {uid, exp, slots: {slot: (emb, score)}, append, ref}


def _sweep():
    now = time.time()
    for d in (_enroll, _challenges):
        for k in [k for k, v in d.items() if v['exp'] < now]:
            d.pop(k, None)


def enroll_start(uid, append=False):
    _sweep()
    for k in [k for k, v in _enroll.items() if v['uid'] == uid]:   # aynı kullanıcının eski oturumu kapanır
        _enroll.pop(k, None)
    eid = secrets.token_urlsafe(24)
    _enroll[eid] = {'uid': uid, 'exp': time.time() + ENROLL_TTL, 'slots': {}, 'append': bool(append), 'ref': None, 'ref_pose': None}
    return eid


def enroll_get(eid, uid):
    _sweep()
    e = _enroll.get(eid or '')
    if not e or e['uid'] != uid:
        return None
    return e


def enroll_frame(e, jpg_b64):
    """Bir kareyi eğitim oturumuna işler: yuva (merkez / 8 yön) hesaplanır, gömme yuvaya yazılır (daha yüksek skor kazanır).
    Başka bir kişinin yüzü (merkez kaydına benzemeyen) eklenmez → other_face."""
    r = embed(jpg_b64)
    out = {'found': bool(r.get('found')), 'w': r.get('w'), 'h': r.get('h'), 'box': r.get('box'), 'small': bool(r.get('small')),
           'slots': sorted(e['slots'].keys(), key=SLOTS.index), 'complete': False}
    if not r.get('found'):
        return out
    yaw, pitch = float(r.get('yaw') or 0), float(r.get('pitch') or 0)
    emb = r['emb']
    if e['ref'] is None:
        if math.hypot(yaw, pitch) >= R_REF:   # ilk kayıt (referans yüz + referans poz) kabaca merkezden alınır
            out.update(yaw=yaw, pitch=pitch, score=r.get('score'), slot=None, need_center=True)
            return out
        e['ref'] = emb
        e['ref_pose'] = (yaw, pitch)
    ry, rp = e.get('ref_pose') or (0.0, 0.0)
    yaw, pitch = yaw - ry, pitch - rp   # referansa göre poz
    out.update(yaw=round(yaw, 3), pitch=round(pitch, 3), score=r.get('score'))
    slot = segment_of(yaw, pitch)
    out['slot'] = slot
    if float(np.dot(_norm(e['ref']), _norm(emb))) < SAME_FACE:
        out['other_face'] = True
        return out
    if slot:
        cur = e['slots'].get(slot)
        if cur is None or float(r.get('score') or 0) > cur[1]:
            e['slots'][slot] = (emb, float(r.get('score') or 0))
            out['added'] = True
    out['slots'] = sorted(e['slots'].keys(), key=SLOTS.index)
    out['complete'] = len(e['slots']) >= len(SLOTS)
    out['enough'] = 'center' in e['slots'] and len(e['slots']) >= MIN_SLOTS
    return out


def enroll_finish(conn, e, eid, mode=None):
    if 'center' not in e['slots'] or len(e['slots']) < MIN_SLOTS:
        raise ValueError(f'Yeterli açı toplanmadı (en az {MIN_SLOTS} yuva, merkez dâhil)')
    slots = sorted(e['slots'].keys(), key=SLOTS.index)
    n = save(conn, e['uid'], [e['slots'][s][0] for s in slots], slots, mode=mode, append=e['append'])
    _enroll.pop(eid, None)
    return n, slots


def enroll_cancel(eid):
    _enroll.pop(eid, None)


# ---------- giriş meydan okuması

_challenges = {}   # nonce → {uid, device_id, exp, pose, stage, frames, misses, ip, mode, best}
_rate = {}         # anahtar → [zamanlar]


def rate_ok(key):
    now = time.time()
    lst = [t for t in _rate.get(key, []) if now - t < 60]
    _rate[key] = lst
    if len(lst) >= FACE_RATE:
        return False
    lst.append(now)
    return True


def challenge_new(uid, device_id, ip, mode, liveness=True):
    _sweep()
    for k in [k for k, v in _challenges.items() if v['uid'] == uid and v['device_id'] == device_id]:
        _challenges.pop(k, None)
    nonce = secrets.token_urlsafe(24)
    _challenges[nonce] = {'uid': uid, 'device_id': device_id, 'exp': time.time() + CHALLENGE_TTL, 'ip': ip, 'mode': mode,
                          'pose': secrets.choice(LIVENESS_POSES) if liveness else None,
                          'stage': 'match', 'frames': 0, 'misses': 0, 'best': 0.0, 'ref_pose': None}
    return nonce, _challenges[nonce]


def challenge_get(nonce):
    _sweep()
    return _challenges.get(nonce or '')


def challenge_drop(nonce):
    _challenges.pop(nonce, None)


def verify_frame(ch, embs, jpg_b64, thr):
    """Bir kareyi meydan okumaya işler. Dönüş: {found, matched, sim, stage, pose, done, fail}.
    fail=True → kare sınırı/eşleşmeme sınırı aşıldı (çağıran meydan okumayı kapatır ve başarısız giriş yazar)."""
    ch['frames'] += 1
    out = {'found': False, 'matched': False, 'stage': ch['stage'], 'pose': ch['pose'], 'done': False, 'fail': False}
    if ch['frames'] > MAX_FRAMES:
        out['fail'] = True
        out['reason'] = 'Süre doldu; yüz doğrulanamadı'
        return out
    r = embed(jpg_b64)
    out['small'] = bool(r.get('small'))
    if not r.get('found'):
        return out
    out['found'] = True
    sim = match(embs, r['emb'])
    yaw, pitch = float(r.get('yaw') or 0), float(r.get('pitch') or 0)
    ry, rp = ch.get('ref_pose') or (0.0, 0.0)
    out.update(sim=round(sim, 3), yaw=round(yaw - ry, 3), pitch=round(pitch - rp, 3), box=r.get('box'))
    ch['best'] = max(ch['best'], sim)
    if ch['stage'] == 'match':
        if sim >= thr and math.hypot(yaw, pitch) < R_REF:   # kabaca önden bakış = referans poz
            out['matched'] = True
            ch['ref_pose'] = (yaw, pitch)
            ch['stage'] = 'pose' if ch['pose'] else ('pin' if ch['mode'] == 'face_pin' else 'done')
        elif sim < thr:
            ch['misses'] += 1
            if ch['misses'] >= MAX_MISS:
                out['fail'] = True
                out['reason'] = 'Yüz eşleşmedi'
    elif ch['stage'] == 'pose':
        # dönük yüzde benzerlik düşer; eşleme eşiği biraz gevşer ama yüz yine aynı kişi olmalı; poz referansa göre
        if sim >= thr - 0.08 and pose_matches(yaw - ry, pitch - rp, ch['pose']):
            out['matched'] = True
            ch['stage'] = 'pin' if ch['mode'] == 'face_pin' else 'done'
        elif sim < thr - 0.08:
            ch['misses'] += 1
            if ch['misses'] >= MAX_MISS:
                out['fail'] = True
                out['reason'] = 'Yüz eşleşmedi'
    out['stage'] = ch['stage']
    out['done'] = ch['stage'] == 'done'
    out['need_pin'] = ch['stage'] == 'pin'
    return out


def threshold(pol):
    try:
        return max(0.30, min(0.80, int(pol.get('face_threshold', 45)) / 100.0))
    except (TypeError, ValueError):
        return 0.45
