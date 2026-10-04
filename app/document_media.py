"""Ses, video ve resim evrakları: konuşmayı metne çevirme (Whisper) ve videoda / resimde yüz bulma / tanıma.

Tümü bu sunucuda çalışır; ses ve görüntü dışarı gönderilmez.
- Ses / video sesi: PyAV ile 16 kHz tek kanal WAV'a çevrilir, whisper.cpp (GB10 ekran kartı) ile metne dökülür.
  Metin "[dd:ss] cümle" satırları olarak documents.ocr_text'e yazılır (evrak aramasında bulunur).
- Video yüzleri: saniyede bir kare alınır; OpenCV YuNet ile yüzler bulunur, SFace ile 128 boyutlu yüz izi çıkarılır.
  Aynı kişiye ait yüzler (kosinüs benzerliği) gruplanır; her grup için en net yüz kırpılıp kaydedilir
  (document_faces). Daha önce bir firma kişisine ya da personele bağlanmış yüze yeterince benzeyen grup otomatik
  olarak o kişiye önerilir (auto = 1); kullanıcı değiştirebilir.
- Resim yüzleri: resimdeki her yüz ayrı kişi olarak kaydedilir; tanıma ve öneri videodakiyle aynıdır.

Araçlar: vendor/whisper/whisper-cli, vendor/models/*.onnx ve ggml-large-v3-turbo-q8_0.bin (bkz. README).
"""
import json
import os
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

from . import config, db

os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')   # OpenCV DNN arka uç uyarıları günlüğü doldurmasın

MODELS = config.BASE_DIR / 'vendor' / 'models'
WHISPER = config.BASE_DIR / 'vendor' / 'whisper' / 'whisper-cli'
WHISPER_MODEL = MODELS / 'ggml-large-v3-turbo-q8_0.bin'
YUNET = MODELS / 'face_detection_yunet_2023mar.onnx'
SFACE = MODELS / 'face_recognition_sface_2021dec.onnx'

AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.flac', '.wma', '.amr', '.3ga', '.weba', '.mka'}

SAME_PERSON = 0.363    # SFace kosinüs eşiği: aynı kişi (videodaki yüzleri gruplama)
KNOWN_PERSON = 0.42    # tanınan kişiye otomatik öneri için daha sıkı eşik
MAX_SAMPLES = 900      # en fazla örnek kare (uzun videoda aralık genişler)
MIN_FACE = 40          # piksel (1280 px'e küçültülmüş karede)

_gpu = threading.Lock()   # aynı anda tek Whisper işi


def whisper_available():
    """Konuşma tanıma kullanılabilir mi: entegrasyon açık (config.SPEECH_ENABLED) ve Whisper + model kurulu."""
    return config.SPEECH_ENABLED and WHISPER.exists() and WHISPER_MODEL.exists()


def faces_available():
    return YUNET.exists() and SFACE.exists()


# ---------- Ses → metin

def _to_wav(path, wav_path):
    """Ses / video dosyasının sesini 16 kHz tek kanal 16 bit WAV'a çevirir; süre (sn) ya da ses yoksa None döner."""
    import av
    with av.open(str(path)) as src:
        if not src.streams.audio:
            return None
        stream = src.streams.audio[0]
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        frames = 0
        with wave.open(str(wav_path), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            for frame in src.decode(stream):
                for f in resampler.resample(frame):
                    data = f.to_ndarray().tobytes()
                    out.writeframes(data)
                    frames += len(data) // 2
            for f in resampler.resample(None):
                data = f.to_ndarray().tobytes()
                out.writeframes(data)
                frames += len(data) // 2
    return frames / 16000


def _stamp(ms):
    s = int(ms // 1000)
    return f'{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}' if s >= 3600 else f'{s // 60:02d}:{s % 60:02d}'


def transcribe(path, lang='auto', stamps=True):
    """(metin, süre sn). Ses yoksa ('', süre/None). stamps: '[dd:ss] cümle' satırları; değilse düz metin (dikte)."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / 'a.wav'
        seconds = _to_wav(path, wav)
        if not seconds or seconds < 0.5:
            return '', seconds
        if not whisper_available():
            raise RuntimeError('Konuşma tanıma kapalı ya da kurulu değil (Program Ayarları › Entegrasyonlar › Konuşma Tanıma)')
        out = Path(tmp) / 'out'
        with _gpu:
            r = subprocess.run([str(WHISPER), '-m', str(WHISPER_MODEL), '-f', str(wav), '-l', lang, '-oj', '-of', str(out),
                                '-np', '-t', '8'], capture_output=True, timeout=max(600, int(seconds * 2)))
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors='replace')[-300:] or 'Whisper hatası')
        data = json.loads(out.with_suffix('.json').read_text(encoding='utf-8', errors='replace'))
        lines = []
        for seg in data.get('transcription', []):
            text = (seg.get('text') or '').strip()
            if text and not (text.startswith('[') and text.endswith(']')):   # [Müzik], [BLANK_AUDIO] vb.
                lines.append(f'[{_stamp(seg.get("offsets", {}).get("from", 0))}] {text}' if stamps else text)
        if not stamps:
            return ' '.join(lines), seconds
        lang = (data.get('result') or {}).get('language')
        head = f'(Dil: {lang})\n' if lang and lang != 'tr' else ''
        return head + '\n'.join(lines), seconds


# ---------- Video: küçük resim ve yüzler

def _frames(path, every_sec):
    """(zaman sn, BGR kare) — her every_sec saniyede bir, en uzun kenar 1280 px."""
    import av
    import cv2
    with av.open(str(path)) as src:
        if not src.streams.video:
            return
        stream = src.streams.video[0]
        stream.thread_type = 'AUTO'
        next_t = 0.0
        for frame in src.decode(stream):
            t = float(frame.time or 0)
            if t + 1e-6 < next_t:
                continue
            next_t = t + every_sec
            img = frame.to_ndarray(format='bgr24')
            h, w = img.shape[:2]
            k = 1280 / max(h, w)
            if k < 1:
                img = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
            yield t, img


def video_duration(path):
    import av
    with av.open(str(path)) as src:
        if src.duration:
            return src.duration / 1_000_000
        s = src.streams.video[0] if src.streams.video else None
        return float(s.duration * s.time_base) if s and s.duration else None


def video_thumb(path, thumb):
    import cv2
    for t, img in _frames(path, 1.0):
        if t >= 1.0 or t > 0:
            h, w = img.shape[:2]
            k = 480 / max(h, w)
            cv2.imwrite(str(thumb), cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA))
            return True
    return False


def _norm(v):
    import numpy as np
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _face_crop(img, f):
    """Yüzün %40 fazlasını kapsayan kare kırpık (256 px)."""
    import cv2
    h, w = img.shape[:2]
    x, y, fw, fh = f[0], f[1], f[2], f[3]
    cx, cy, side = x + fw / 2, y + fh / 2, max(fw, fh) * 1.4
    x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    x1, y1 = int(min(w, cx + side / 2)), int(min(h, cy + side / 2))
    return cv2.resize(img[y0:y1, x0:x1], (256, 256), interpolation=cv2.INTER_AREA)


def detect_faces_image(path):
    """Resimdeki kişiler: her yüz ayrı kişi (aynı kişi bir resimde iki kez görünmez); en büyük yüz önce."""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert('RGB')
        im.thumbnail((1600, 1600))
        img = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    detector = cv2.FaceDetectorYN.create(str(YUNET), '', (w, h), 0.88, 0.3, 100)
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE), '')
    _, faces = detector.detect(img)
    out = []
    for f in faces if faces is not None else []:
        if min(f[2], f[3]) < 32:
            continue
        feat = _norm(recognizer.feature(recognizer.alignCrop(img, f)).flatten().astype(np.float32))
        out.append({'embedding': feat, 'samples': 1, 'first_at': None, 'crop': _face_crop(img, f), 'area': float(f[2] * f[3])})
    return sorted(out, key=lambda c: -c['area'])


def detect_faces(path, duration):
    """Videodaki kişiler: [{'embedding': ndarray(128), 'samples': n, 'first_at': sn, 'crop': BGR resim}] (en çok görünen önce)."""
    import cv2
    import numpy as np
    every = max(1.0, (duration or 0) / MAX_SAMPLES)
    detector = cv2.FaceDetectorYN.create(str(YUNET), '', (320, 320), 0.88, 0.3, 50)
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE), '')
    clusters = []   # {'sum': ndarray, 'n': int, 'best': (kalite, crop), 'first_at': t}
    frames = 0
    for t, img in _frames(path, every):
        frames += 1
        h, w = img.shape[:2]
        detector.setInputSize((w, h))
        _, faces = detector.detect(img)
        for f in faces if faces is not None else []:
            x, y, fw, fh, score = f[0], f[1], f[2], f[3], f[14]
            if min(fw, fh) < MIN_FACE:
                continue
            feat = _norm(recognizer.feature(recognizer.alignCrop(img, f)).flatten().astype(np.float32))
            best, best_sim = None, SAME_PERSON
            for c in clusters:
                sim = float(np.dot(feat, _norm(c['sum'])))
                if sim >= best_sim:
                    best, best_sim = c, sim
            quality = fw * fh * score
            if best is None:
                best = {'sum': np.zeros(128, np.float32), 'n': 0, 'best': (0, None), 'first_at': t}
                clusters.append(best)
            best['sum'] += feat
            best['n'] += 1
            if quality > best['best'][0]:   # kare kırpma: yüzün %40 fazlası
                best['best'] = (quality, _face_crop(img, f))
    min_n = 2 if frames >= 5 else 1   # tek karede görünen gelip geçen yüzler (yanlış tespit) atlanır
    out = [{'embedding': _norm(c['sum']), 'samples': c['n'], 'first_at': c['first_at'], 'crop': c['best'][1]}
           for c in clusters if c['n'] >= min_n and c['best'][1] is not None]
    return sorted(out, key=lambda c: -c['samples'])


def known_identities(conn):
    """Kimlik izleri: elle evrağa bağlanan yüzler + Yüz Tanıma Eğitimi fotoğrafları. [(('person'|'user', id), ortalama iz)]."""
    import numpy as np
    sums = {}
    for r in conn.execute('''SELECT person_id, user_id, embedding FROM document_faces
                             WHERE (person_id IS NOT NULL OR user_id IS NOT NULL) AND auto = 0'''):
        key = ('person', r[0]) if r[0] else ('user', r[1])
        sums[key] = sums.get(key, 0) + np.frombuffer(r[2], dtype=np.float32)
    # Yüz Tanıma Eğitimi (faceenroll) izleri — tablo yoksa sorun değil (eski kurulum)
    try:
        for r in conn.execute("SELECT subject_type, user_id, person_id, family_id, embedding FROM face_enroll"):
            if r[0] == 'user':
                key = ('user', r[1])
            elif r[0] == 'person':
                key = ('person', r[2])
            elif r[0] == 'family':
                key = ('family', r[3])
            else:
                continue
            sums[key] = sums.get(key, 0) + np.frombuffer(r[4], dtype=np.float32)
    except Exception:   # noqa: BLE001 — face_enroll yoksa yalnızca evrak yüzleri
        pass
    return [(k, _norm(v)) for k, v in sums.items()]


def match(known, embedding):
    import numpy as np
    best, best_sim = None, KNOWN_PERSON
    for key, v in known:
        sim = float(np.dot(v, embedding))
        if sim >= best_sim:
            best, best_sim = key, sim
    return best


def save_faces(conn, doc_id, file_path, faces):
    """Önceki yüzleri siler, yenilerini kaydeder; tanınan kişiye otomatik bağlar (kişi evrağın kişilerine eklenir)."""
    import cv2
    known = known_identities(conn)   # yeniden işlemede bu evraktaki elle yapılmış bağlamalar da korunur (benzerlikle)
    for crop, person_id, added in conn.execute(
            'SELECT crop, person_id, added_link FROM document_faces WHERE document_id = ?', (doc_id,)).fetchall():
        (config.UPLOAD_DIR / crop).unlink(missing_ok=True)
        if added and person_id:
            conn.execute('DELETE FROM document_people WHERE document_id = ? AND person_id = ?', (doc_id, person_id))
    conn.execute('DELETE FROM document_faces WHERE document_id = ?', (doc_id,))
    for i, f in enumerate(faces, 1):
        name = f'{file_path.name}.face{i}.jpg'
        cv2.imwrite(str(file_path.with_name(name)), f['crop'], [cv2.IMWRITE_JPEG_QUALITY, 88])
        who = match(known, f['embedding'])
        person_id = who[1] if who and who[0] == 'person' else None
        user_id = who[1] if who and who[0] == 'user' else None
        added = 0
        if person_id and not conn.execute('SELECT 1 FROM document_people WHERE document_id = ? AND person_id = ?',
                                          (doc_id, person_id)).fetchone():
            conn.execute('INSERT INTO document_people (document_id, person_id) VALUES (?, ?)', (doc_id, person_id))
            added = 1
        conn.execute('''INSERT INTO document_faces (document_id, crop, embedding, samples, first_at, person_id, user_id, auto,
                        added_link, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                     (doc_id, f'documents/{name}', f['embedding'].astype('float32').tobytes(), f['samples'],
                      None if f['first_at'] is None else round(f['first_at'], 1), person_id, user_id, 1 if who else 0, added, db.now()))
