"""Sesli görüşme kaydının işlenmesi: konuşma → metin (Whisper), konuşmacılara ayırma ve ses profilleriyle tanıma.

Toplantı ses işleme hattını (meeting_audio) yeniden kullanır; yalnızca voice_call_* tablolarına yazar.
Özet: uygulamada LLM olmadığından çıkarımsal (öne çıkan/uzun cümleler, kronolojik) bir özet üretilir.
"""
import json
import threading
from datetime import datetime, timedelta

import numpy as np

from . import config, db
from .meeting_audio import (HALLUCINATIONS, MIN_RMS, SR, _to_wav, _unit, best_profile, cluster, embed,
                            learn, profiles, read_wav, whisper_available, whisper_segments)

__all__ = ['process', 'start', 'schedule', 'resume_pending', 'available']


def available():
    """Görüşme kaydı için yalnızca konuşma→metin (Whisper) yeterli. Ses kimliği (konuşmacı) modeli isteğe bağlıdır."""
    return whisper_available()


def _safe_embed(clip):
    """Ses kimliği eğitimi için gömme (best-effort): model yoksa/başarısızsa None döner, transkripsiyonu etkilemez."""
    try:
        return embed(clip)
    except Exception:
        return None


def _summary(conn, call_id):
    """Konuşmacılı transkriptten kısa çıkarımsal özet: en uzun (öne çıkan) cümleler, kronolojik, konuşmacı adıyla."""
    segs = db.rows(conn.execute(
        '''SELECT s.text, s.t0, sp.label FROM voice_call_segments s
           LEFT JOIN voice_call_speakers sp ON sp.id = s.speaker_id WHERE s.call_id = ? ORDER BY s.audio_id, s.t0''', (call_id,)))
    clean = [s for s in segs if len((s['text'] or '').strip()) > 12]
    if not clean:
        return None
    order = sorted(range(len(clean)), key=lambda i: -len(clean[i]['text']))[:6]
    pick = sorted(order)
    lines = [f"{(clean[i]['label'] or 'Konuşmacı')}: {clean[i]['text'].strip()}" for i in pick]
    return '\n'.join(lines)


def process(call_id):
    """Arka plan: görüşme kaydını metne çevir, konuşmacılara ayır, ses profilleriyle eşleştir, özetle."""
    if not available():   # konuşma tanıma kapalı: yalnız kayıt saklanır, metin / konuşmacı yok
        with db.connect() as conn:
            conn.execute("UPDATE voice_calls SET process_status = 'TAMAM', process_error = NULL WHERE id = ?", (call_id,))
            conn.commit()
        return
    with db.connect() as conn:
        try:
            conn.execute("UPDATE voice_calls SET process_status = 'ISLENIYOR', process_error = NULL WHERE id = ?", (call_id,))
            conn.commit()
            audios = db.rows(conn.execute('SELECT * FROM voice_call_audio WHERE call_id = ? ORDER BY id', (call_id,)))
            # 1) Uzun iş (WAV, Whisper, ses kimliği) YAZMA İŞLEMİ AÇILMADAN — veritabanı döküm boyunca kilitlenmez
            audio_upd = []
            tagged = []      # kişiye ait dosya (uploader belli): (audio_id, t0, t1, at, text, user_id, emb, dur)
            untagged = []    # kimliksiz karışık ses (eski): (audio_id, t0, t1, at, text, emb, dur)
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
                        continue
                    clip = piece if len(piece) <= 12 * SR else piece[len(piece) // 2 - 6 * SR: len(piece) // 2 + 6 * SR]
                    emb = _safe_embed(clip) if len(clip) >= int(0.6 * SR) else None   # ses kimliği eğitimi için best-effort
                    at = (start + timedelta(seconds=t0)).isoformat(timespec='seconds')
                    if a['user_id']:
                        tagged.append((a['id'], t0, t1, at, s['text'], a['user_id'], emb, t1 - t0))
                    else:
                        untagged.append((a['id'], t0, t1, at, s['text'], emb, t1 - t0))

            # 2) Yazmalar tek ve kısa işlemde
            conn.execute('DELETE FROM voice_call_segments WHERE call_id = ?', (call_id,))
            conn.execute('DELETE FROM voice_call_speakers WHERE call_id = ?', (call_id,))
            conn.executemany('UPDATE voice_call_audio SET wav = ?, seconds = ? WHERE id = ?', audio_upd)
            # Kişiye ait dosyalar: her uploader = tek konuşmacı (kesin tanıma). Ses profili de öğrenilir.
            user_speaker = {}
            for uid in dict.fromkeys(it[5] for it in tagged):
                embs = [it[6] for it in tagged if it[5] == uid and it[6] is not None]
                secs = round(sum(it[7] for it in tagged if it[5] == uid), 1)
                mean = _unit(np.mean(embs, axis=0)) if embs else None
                name = conn.execute('SELECT full_name FROM users WHERE id = ?', (uid,)).fetchone()
                user_speaker[uid] = conn.execute(
                    '''INSERT INTO voice_call_speakers (call_id, label, user_id, auto, score, embedding, seconds)
                       VALUES (?,?,?,1,1.0,?,?)''',
                    (call_id, name[0] if name else f'Kullanıcı {uid}', uid,
                     json.dumps([round(float(x), 6) for x in mean]) if mean is not None else None, secs)).lastrowid
                if mean is not None:
                    try:
                        learn(conn, uid, mean.tolist(), max(1, int(secs)))   # arka planda ses kimliği eğitimi (best-effort)
                    except Exception:
                        pass

            # Kimliksiz ses varsa (eski karışık kayıt): konuşmacılara ayır + ses profilleriyle tanı.
            labels, ids = {}, {}
            usable = [i for i, it in enumerate(untagged) if it[5] is not None and it[6] >= 1.0]
            if usable:
                lab, cents = cluster([untagged[i][5] for i in usable], [min(untagged[i][6], 10) for i in usable])
                for k, i in enumerate(usable):
                    labels[i] = lab[k]
                for i, it in enumerate(untagged):
                    if i in labels:
                        continue
                    labels[i] = int(np.argmax([float(it[5] @ c) for c in cents])) if it[5] is not None else next((labels[j] for j in range(i - 1, -1, -1) if j in labels), 0)
                dur = {}
                for i in range(len(untagged)):
                    dur[labels[i]] = dur.get(labels[i], 0) + untagged[i][6]
                profs = profiles(conn)
                used = set(user_speaker)
                unknown = 0
                for g in sorted(dur, key=lambda x: -dur[x]):
                    uid, score = best_profile(cents[g], profs, exclude=used)
                    if uid:
                        used.add(uid)
                        label = conn.execute('SELECT full_name FROM users WHERE id = ?', (uid,)).fetchone()[0]
                    else:
                        unknown += 1
                        label = f'Kişi {unknown}'
                    ids[g] = conn.execute(
                        '''INSERT INTO voice_call_speakers (call_id, label, user_id, auto, score, embedding, seconds)
                           VALUES (?,?,?,?,?,?,?)''',
                        (call_id, label, uid, int(bool(uid)), round(score, 3),
                         json.dumps([round(float(x), 6) for x in cents[g]]), round(dur[g], 1))).lastrowid

            for it in tagged:
                conn.execute('INSERT INTO voice_call_segments (call_id, audio_id, speaker_id, t0, t1, at, text) VALUES (?,?,?,?,?,?,?)',
                             (call_id, it[0], user_speaker.get(it[5]), round(it[1], 2), round(it[2], 2), it[3], it[4]))
            for i, it in enumerate(untagged):
                conn.execute('INSERT INTO voice_call_segments (call_id, audio_id, speaker_id, t0, t1, at, text) VALUES (?,?,?,?,?,?,?)',
                             (call_id, it[0], ids.get(labels.get(i)), round(it[1], 2), round(it[2], 2), it[3], it[4]))
            summary = _summary(conn, call_id)
            conn.execute("UPDATE voice_calls SET process_status = 'TAMAM', processed_at = ?, summary = ? WHERE id = ?",
                         (db.now(), summary, call_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.execute("UPDATE voice_calls SET process_status = 'HATA', process_error = ? WHERE id = ?", (str(e)[:500], call_id))
            conn.commit()


def start(call_id):
    threading.Thread(target=process, args=(call_id,), daemon=True, name=f'call-{call_id}').start()


_timers = {}
_tlock = threading.Lock()


def schedule(call_id, delay=6.0):
    """Kaydı işlemeyi geciktirir; kısa sürede gelen birden çok katılımcı kaydını tek işlemede toplar."""
    with _tlock:
        t = _timers.get(call_id)
        if t:
            t.cancel()
        timer = threading.Timer(delay, lambda: _fire(call_id))
        timer.daemon = True
        _timers[call_id] = timer
        timer.start()


def _fire(call_id):
    with _tlock:
        _timers.pop(call_id, None)
    process(call_id)


def resume_pending():
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM voice_calls WHERE process_status = 'ISLENIYOR'")]
    for cid in ids:
        start(cid)
