"""Toplantı ses kaydının işlenmesi: konuşma → metin, konuşmacılara ayırma (diarization) ve ses profilleriyle tanıma.

Akış (toplantı sonlandırılınca arka planda):
1. Tarayıcı kaydı (webm/ogg) 16 kHz tek kanal WAV'a çevrilir (PyAV).
2. Whisper (whisper.cpp, yerel) zaman damgalı parçalara çevirir.
3. Her parçanın ses kimliği (256 boyutlu vektör) WeSpeaker ResNet34 modeliyle (ONNX, yerel) çıkarılır.
4. Parçalar kosinüs benzerliğiyle ortalama bağlantılı kümelemeyle konuşmacılara ayrılır.
5. Her konuşmacı kayıtlı ses profilleriyle (voice_profiles) karşılaştırılır; eşleşen kişiye otomatik atanır, kalanlar
   "Tanımsız kişi N" olarak bekler. Kullanıcı bir grubu kişiye atayınca o kişinin ses profili güncellenir; sonraki
   toplantılarda o kişi otomatik tanınır.
Ses ve metin sunucu dışına çıkmaz.
"""
import json
import re
import threading
import wave
from datetime import datetime, timedelta

import numpy as np

from . import config, db
from .document_media import _to_wav, whisper_data

MODEL = config.BASE_DIR / 'vendor' / 'models' / 'wespeaker_resnet34_LM.onnx'
SR = 16000
# Whisper'ın sessizlik / müzik / bip üzerinde uydurduğu bilinen kalıplar (ör. altyazı imzaları)
HALLUCINATIONS = re.compile(r'altyaz[ıi]|izlediğiniz için teşekkür|abone ol|thanks for watching|subtitles by|amara\.org|^\W*$', re.I)
MIN_RMS = 0.006   # bundan zayıf parça konuşma sayılmaz
SAME = 0.45        # aynı konuşmacı sayılacak en düşük benzerlik (kümeleme)
PROFILE_MATCH = 0.50   # kayıtlı ses profiliyle otomatik tanıma eşiği
_session = None
_lock = threading.Lock()


def available():
    from . import speech   # entegrasyon + Modül Ayarları › Toplantılar anahtarı
    return MODEL.exists() and speech.enabled('meetings')


# ---------- ses kimliği
def _fbank(sig):
    """Kaldi uyumlu 80 kanallı log-mel filtre bankası (25 ms pencere, 10 ms kayma), ortalaması çıkarılmış."""
    x = sig.astype(np.float32) * 32768.0
    if len(x) < 400:
        x = np.pad(x, (0, 400 - len(x)))
    n = 1 + (len(x) - 400) // 160
    idx = np.arange(400)[None, :] + 160 * np.arange(n)[:, None]
    fr = x[idx]
    fr = fr - fr.mean(axis=1, keepdims=True)
    fr = np.concatenate([fr[:, :1] - 0.97 * fr[:, :1], fr[:, 1:] - 0.97 * fr[:, :-1]], axis=1)
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(400) / 399)) ** 0.85
    spec = np.abs(np.fft.rfft(fr * win, n=512)) ** 2
    mel = lambda f: 1127.0 * np.log(1 + f / 700.0)
    lo, hi = mel(20.0), mel(SR / 2)
    centers = np.linspace(lo, hi, 82)
    fft_mel = mel(np.arange(256) * SR / 512)
    banks = np.zeros((80, 256), np.float32)
    for m in range(80):
        left, c, right = centers[m], centers[m + 1], centers[m + 2]
        up = (fft_mel - left) / (c - left)
        down = (right - fft_mel) / (right - c)
        banks[m] = np.maximum(0, np.minimum(up, down))
    feats = np.log(np.maximum(spec[:, :256] @ banks.T, np.finfo(np.float32).eps))
    return (feats - feats.mean(axis=0)).astype(np.float32)


def embed(sig):
    global _session
    with _lock:
        if _session is None:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 4
            _session = ort.InferenceSession(str(MODEL), opts, providers=['CPUExecutionProvider'])
        v = _session.run(None, {'feats': _fbank(sig)[None]})[0][0]
    return v / (np.linalg.norm(v) + 1e-9)


def _unit(v):
    v = np.asarray(v, np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


# ---------- kümeleme
def cluster(embs, weights):
    """Ortalama bağlantılı yığılmalı kümeleme (kosinüs). Dönen: her öğenin küme numarası."""
    groups = [[i] for i in range(len(embs))]
    cents = [embs[i] * weights[i] for i in range(len(embs))]
    while len(groups) > 1:
        c = np.array([_unit(x) for x in cents])
        sim = c @ c.T
        np.fill_diagonal(sim, -1)
        i, j = np.unravel_index(np.argmax(sim), sim.shape)
        if sim[i, j] < SAME:
            break
        i, j = min(i, j), max(i, j)
        groups[i] += groups.pop(j)
        cents[i] = cents[i] + cents.pop(j)
    label = [0] * len(embs)
    for g, members in enumerate(groups):
        for m in members:
            label[m] = g
    return label, [_unit(x) for x in cents]


def profiles(conn):
    return {r['user_id']: _unit(json.loads(r['embedding'])) for r in db.rows(conn.execute('SELECT user_id, embedding FROM voice_profiles'))}


def best_profile(vec, profs, exclude=()):
    best = (None, 0.0)
    for uid, p in profs.items():
        if uid in exclude:
            continue
        s = float(vec @ p)
        if s > best[1]:
            best = (uid, s)
    return best if best[1] >= PROFILE_MATCH else (None, best[1])


def _emb_from(raw):
    """voice örneği embedding'ini çöz: JSON liste ya da float32 BLOB olabilir. Başarısızsa None."""
    if raw is None:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            try:
                return _unit(np.asarray(json.loads(raw.decode()), np.float32))
            except Exception:   # noqa: BLE001
                return _unit(np.frombuffer(raw, dtype=np.float32))
        return _unit(np.asarray(json.loads(raw), np.float32))
    except Exception:   # noqa: BLE001
        return None


def add_sample(conn, user_id, vec, source='manual', clip=None, seconds=None, created_by=None):
    """Kişiye (user) bir ses izi örneği ekler (voice_samples) ve profilini örneklerden yeniden kurar. vec: 256-d."""
    v = _unit(vec)
    conn.execute('''INSERT INTO voice_samples (user_id, embedding, clip, source, seconds, created_by, created_at)
                    VALUES (?,?,?,?,?,?,?)''',
                 (int(user_id), json.dumps([round(float(x), 6) for x in v]), clip, source, seconds, created_by, db.now()))
    return rebuild_profile(conn, user_id)


def rebuild_profile(conn, user_id):
    """Kişinin voice_profiles izini TÜM bilinen örneklerin ortalamasından yeniden kurar: voice_samples (elle/otomatik)
    + toplantı/arama konuşmacı kümeleri (voice_call_speakers, o kişiye atanmış). Hiç örnek yoksa profili siler."""
    vecs = []
    for r in conn.execute('SELECT embedding FROM voice_samples WHERE user_id = ?', (int(user_id),)):
        v = _emb_from(r[0])
        if v is not None and v.size == 256:
            vecs.append(v)
    try:
        for r in conn.execute('SELECT embedding FROM voice_call_speakers WHERE user_id = ? AND embedding IS NOT NULL', (int(user_id),)):
            v = _emb_from(r[0])
            if v is not None and v.size == 256:
                vecs.append(v)
    except Exception:   # noqa: BLE001 — tablo yoksa yalnız voice_samples
        pass
    if not vecs:
        conn.execute('DELETE FROM voice_profiles WHERE user_id = ?', (int(user_id),))
        return 0
    mean = _unit(np.sum(vecs, axis=0))
    conn.execute('''INSERT INTO voice_profiles (user_id, embedding, samples, updated_at) VALUES (?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET embedding = excluded.embedding, samples = excluded.samples, updated_at = excluded.updated_at''',
                 (int(user_id), json.dumps([round(float(x), 6) for x in mean]), len(vecs), db.now()))
    return len(vecs)


def learn(conn, user_id, vec, weight=1):
    """Kişinin ses profilini günceller (ağırlıklı ortalama)."""
    r = db.row(conn.execute('SELECT embedding, samples FROM voice_profiles WHERE user_id = ?', (user_id,)))
    vec = _unit(vec)
    if r:
        old = _unit(json.loads(r['embedding']))
        n = r['samples']
        new = _unit(old * n + vec * weight)
        conn.execute('UPDATE voice_profiles SET embedding = ?, samples = ?, updated_at = ? WHERE user_id = ?',
                     (json.dumps([round(float(x), 6) for x in new]), n + weight, db.now(), user_id))
    else:
        conn.execute('INSERT INTO voice_profiles (user_id, embedding, samples, updated_at) VALUES (?,?,?,?)',
                     (user_id, json.dumps([round(float(x), 6) for x in vec]), weight, db.now()))


# ---------- konuşma → metin (zaman damgalı parçalar)
def whisper_segments(wav, seconds, lang='tr'):
    data = whisper_data(wav, lang, seconds)   # bu sunucu ya da fabrikadaki GX10 (entegrasyon ayarı)
    segs = []
    for s in data.get('transcription', []):
        text = (s.get('text') or '').strip()
        if not text or (text.startswith('[') and text.endswith(']')):
            continue
        off = s.get('offsets', {})
        segs.append({'t0': off.get('from', 0) / 1000, 't1': off.get('to', 0) / 1000, 'text': text})
    return segs


def read_wav(path):
    with wave.open(str(path), 'rb') as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0


def clip_wav(path, t0, t1):
    """WAV dosyasının [t0, t1] aralığı (WAV baytları) — konuşmacı örneği dinletmek için."""
    import io
    with wave.open(str(path), 'rb') as w:
        w.setpos(int(max(0, t0) * SR))
        frames = w.readframes(int(max(0.1, t1 - t0) * SR))
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(SR)
        o.writeframes(frames)
    return buf.getvalue()


# ---------- toplantının tüm kayıtlarını işle
def process(meeting_id):
    """Arka plan: kayıtları metne çevir, konuşmacılara ayır, ses profilleriyle eşleştir. Durum team_meetings.process_status."""
    if not available():   # konuşma tanıma kapalı: yalnız kayıt saklanır, metin / konuşmacı yok
        with db.connect() as conn:
            conn.execute("UPDATE team_meetings SET process_status = 'TAMAM', process_error = NULL WHERE id = ?", (meeting_id,))
            conn.commit()
        return
    with db.connect() as conn:
        try:
            conn.execute("UPDATE team_meetings SET process_status = 'ISLENIYOR', process_error = NULL WHERE id = ?", (meeting_id,))
            conn.commit()
            audios = db.rows(conn.execute('SELECT * FROM team_meeting_audio WHERE meeting_id = ? ORDER BY id', (meeting_id,)))
            # 1) Uzun iş (WAV, Whisper, ses kimliği) YAZMA İŞLEMİ AÇILMADAN: yalnız okuma — veritabanı kilitlenmez.
            #    (Önceden silme ile başlayan işlem döküm boyunca açık kalıyor, her yazma 'database is locked' alıyordu.)
            items = []   # (audio_id, t0, t1, at, text, emb, dur)
            audio_upd = []
            for a in audios:
                src = config.UPLOAD_DIR / a['file']
                if not src.exists() or src.stat().st_size < 2000:
                    continue
                wav = src.with_suffix('.wav')
                seconds = _to_wav(src, wav)
                if not seconds or seconds < 1:
                    continue
                audio_upd.append((str(wav.relative_to(config.UPLOAD_DIR)), seconds, a['id']))
                sig = read_wav(wav)
                start = datetime.fromisoformat(a['started_at'])
                for s in whisper_segments(wav, seconds):
                    t0, t1 = max(0.0, s['t0']), min(seconds, max(s['t1'], s['t0'] + 0.3))
                    piece = sig[int(t0 * SR):int(t1 * SR)]
                    if HALLUCINATIONS.search(s['text']) or not len(piece) or float(np.sqrt(np.mean(piece ** 2))) < MIN_RMS:
                        continue   # uydurma ya da sessiz parça
                    if len(piece) > 12 * SR:   # uzun parçada ortadaki 12 sn yeterli
                        mid = len(piece) // 2
                        piece = piece[mid - 6 * SR: mid + 6 * SR]
                    emb = embed(piece) if len(piece) >= int(0.6 * SR) else None
                    items.append((a['id'], t0, t1, (start + timedelta(seconds=t0)).isoformat(timespec='seconds'), s['text'], emb, t1 - t0))
            usable = [i for i, it in enumerate(items) if it[5] is not None and it[6] >= 1.0]
            labels = {}
            speakers = []
            lab = cents = None
            if usable:
                lab, cents = cluster([items[i][5] for i in usable], [min(items[i][6], 10) for i in usable])
            # 2) Yazmalar tek ve kısa işlemde
            conn.execute('DELETE FROM team_meeting_segments WHERE meeting_id = ?', (meeting_id,))
            conn.execute('DELETE FROM team_meeting_speakers WHERE meeting_id = ?', (meeting_id,))
            conn.executemany('UPDATE team_meeting_audio SET wav = ?, seconds = ? WHERE id = ?', audio_upd)
            if usable:
                for k, i in enumerate(usable):
                    labels[i] = lab[k]
                # kısa parçalar: en yakın konuşmacıya (yoksa önceki parçanınkine)
                for i, it in enumerate(items):
                    if i in labels:
                        continue
                    if it[5] is not None:
                        labels[i] = int(np.argmax([float(it[5] @ c) for c in cents]))
                    else:
                        prev = next((labels[j] for j in range(i - 1, -1, -1) if j in labels), 0)
                        labels[i] = prev
                # konuşma süresine göre sırala; kayıtlı ses profilleriyle eşleştir
                dur = {}
                for i, it in enumerate(items):
                    dur[labels[i]] = dur.get(labels[i], 0) + it[6]
                order = sorted(dur, key=lambda g: -dur[g])
                profs = profiles(conn)
                used, unknown = set(), 0
                ids = {}
                for g in order:
                    uid, score = best_profile(cents[g], profs, exclude=used)
                    if uid:
                        used.add(uid)
                        label = conn.execute('SELECT full_name FROM users WHERE id = ?', (uid,)).fetchone()[0]
                    else:
                        unknown += 1
                        label = f'Tanımsız kişi {unknown}'
                    ids[g] = conn.execute(
                        '''INSERT INTO team_meeting_speakers (meeting_id, label, user_id, auto, score, embedding, seconds)
                           VALUES (?,?,?,?,?,?,?)''',
                        (meeting_id, label, uid, int(bool(uid)), round(score, 3), json.dumps([round(float(x), 6) for x in cents[g]]),
                         round(dur[g], 1))).lastrowid
                    speakers.append(ids[g])
            for i, it in enumerate(items):
                conn.execute('''INSERT INTO team_meeting_segments (meeting_id, audio_id, speaker_id, t0, t1, at, text)
                                VALUES (?,?,?,?,?,?,?)''', (meeting_id, it[0], ids.get(labels.get(i)) if labels else None,
                                                            round(it[1], 2), round(it[2], 2), it[3], it[4]))
            conn.execute("UPDATE team_meetings SET process_status = 'TAMAM', processed_at = ? WHERE id = ?", (db.now(), meeting_id))
            conn.commit()
        except Exception as e:   # hata kullanıcıya gösterilir; "yeniden işle" ile tekrar denenir
            conn.rollback()
            conn.execute("UPDATE team_meetings SET process_status = 'HATA', process_error = ? WHERE id = ?", (str(e)[:500], meeting_id))
            conn.commit()


def start(meeting_id):
    threading.Thread(target=process, args=(meeting_id,), daemon=True, name=f'meeting-{meeting_id}').start()


def rematch(conn, meeting_id):
    """Atanmamış konuşmacıları güncel ses profilleriyle yeniden dener (bir kişi atanınca çağrılır)."""
    profs = profiles(conn)
    taken = {r[0] for r in conn.execute('SELECT user_id FROM team_meeting_speakers WHERE meeting_id = ? AND user_id IS NOT NULL', (meeting_id,))}
    n = 0
    for sp in db.rows(conn.execute('SELECT * FROM team_meeting_speakers WHERE meeting_id = ? AND user_id IS NULL AND embedding IS NOT NULL', (meeting_id,))):
        uid, score = best_profile(_unit(json.loads(sp['embedding'])), profs, exclude=taken)
        if uid:
            name = conn.execute('SELECT full_name FROM users WHERE id = ?', (uid,)).fetchone()[0]
            conn.execute('UPDATE team_meeting_speakers SET user_id = ?, auto = 1, score = ?, label = ? WHERE id = ?', (uid, round(score, 3), name, sp['id']))
            taken.add(uid)
            n += 1
    return n


def resume_pending():
    """Sunucu yeniden başlarken yarım kalan işlemleri sürdürür."""
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM team_meetings WHERE process_status = 'ISLENIYOR'")]
    for mid in ids:
        start(mid)
