"""Online toplantı kaydının işlenmesi: her katılımcının kendi mikrofon kaydı → metin (Whisper).

Her ses dosyası tek bir katılımcıya aittir (kendi mikrofonu), bu yüzden konuşmacı ayırma gerekmez: dosya başına bir
konuşmacı (katılımcının adı). İçerik kullanıcıları için ses profili de en iyi çabayla öğrenilir. meeting_audio hattını
yeniden kullanır; online_meeting_* tablolarına yazar.
"""
import json
import threading
from datetime import datetime, timedelta

import numpy as np

from . import config, db
from .meeting_audio import HALLUCINATIONS, MIN_RMS, SR, _to_wav, _unit, learn, read_wav, whisper_available, whisper_segments

__all__ = ['process', 'schedule', 'resume_pending', 'available']


def available():
    return whisper_available()


def _safe_embed(clip):
    try:
        from .meeting_audio import embed
        return embed(clip)
    except Exception:
        return None


def _summary(conn, mid):
    segs = db.rows(conn.execute(
        '''SELECT s.text, sp.label FROM online_meeting_segments s
           LEFT JOIN online_meeting_speakers sp ON sp.id = s.speaker_id WHERE s.meeting_id = ? ORDER BY s.t0''', (mid,)))
    clean = [s for s in segs if len((s['text'] or '').strip()) > 12]
    if not clean:
        return None
    order = sorted(range(len(clean)), key=lambda i: -len(clean[i]['text']))[:8]
    return '\n'.join(f"{(clean[i]['label'] or 'Konuşmacı')}: {clean[i]['text'].strip()}" for i in sorted(order))


def process(mid):
    with db.connect() as conn:
        try:
            conn.execute("UPDATE online_meetings SET process_status='ISLENIYOR', process_error=NULL WHERE id=?", (mid,))
            conn.commit()
            audios = db.rows(conn.execute('SELECT * FROM online_meeting_audio WHERE meeting_id = ? ORDER BY id', (mid,)))
            conn.execute('DELETE FROM online_meeting_segments WHERE meeting_id = ?', (mid,))
            conn.execute('DELETE FROM online_meeting_speakers WHERE meeting_id = ?', (mid,))
            for a in audios:
                src = config.UPLOAD_DIR / a['file']
                if not src.exists() or src.stat().st_size < 2000:
                    continue
                wav = src.with_suffix('.wav')
                seconds = _to_wav(src, wav)
                if not seconds or seconds < 1:
                    continue
                conn.execute('UPDATE online_meeting_audio SET wav=?, seconds=? WHERE id=?',
                             (str(wav.relative_to(config.UPLOAD_DIR)), seconds, a['id']))
                sig = read_wav(wav)
                label = a['speaker_name'] or (f"Kullanıcı {a['user_id']}" if a['user_id'] else 'Konuşmacı')
                sid = conn.execute('''INSERT INTO online_meeting_speakers (meeting_id, label, user_id, auto, score, seconds)
                                      VALUES (?,?,?,1,1.0,0)''', (mid, label, a['user_id'])).lastrowid
                start = datetime.fromisoformat(a['started_at'])
                total = 0.0
                embs = []
                for s in whisper_segments(wav, seconds):
                    t0, t1 = max(0.0, s['t0']), min(seconds, max(s['t1'], s['t0'] + 0.3))
                    piece = sig[int(t0 * SR):int(t1 * SR)]
                    if HALLUCINATIONS.search(s['text']) or not len(piece) or float(np.sqrt(np.mean(piece ** 2))) < MIN_RMS:
                        continue
                    at = (start + timedelta(seconds=t0)).isoformat(timespec='seconds')
                    conn.execute('INSERT INTO online_meeting_segments (meeting_id, audio_id, speaker_id, t0, t1, at, text) VALUES (?,?,?,?,?,?,?)',
                                 (mid, a['id'], sid, round(t0, 2), round(t1, 2), at, s['text']))
                    total += t1 - t0
                    if a['user_id']:
                        clip = piece if len(piece) <= 12 * SR else piece[len(piece) // 2 - 6 * SR: len(piece) // 2 + 6 * SR]
                        e = _safe_embed(clip) if len(clip) >= int(0.6 * SR) else None
                        if e is not None:
                            embs.append(e)
                conn.execute('UPDATE online_meeting_speakers SET seconds=? WHERE id=?', (round(total, 1), sid))
                if a['user_id'] and embs:   # ses kimliği eğitimi (arka plan, en iyi çaba)
                    try:
                        learn(conn, a['user_id'], _unit(np.mean(embs, axis=0)).tolist(), max(1, int(total)))
                    except Exception:
                        pass
            summary = _summary(conn, mid)
            conn.execute("UPDATE online_meetings SET process_status='TAMAM', processed_at=?, summary=? WHERE id=?",
                         (db.now(), summary, mid))
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.execute("UPDATE online_meetings SET process_status='HATA', process_error=? WHERE id=?", (str(e)[:500], mid))
            conn.commit()


_timers = {}
_tlock = threading.Lock()


def schedule(mid, delay=6.0):
    with _tlock:
        t = _timers.get(mid)
        if t:
            t.cancel()
        timer = threading.Timer(delay, lambda: _fire(mid))
        timer.daemon = True
        _timers[mid] = timer
        timer.start()


def _fire(mid):
    with _tlock:
        _timers.pop(mid, None)
    process(mid)


def resume_pending():
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM online_meetings WHERE process_status='ISLENIYOR'")]
    for mid in ids:
        threading.Thread(target=process, args=(mid,), daemon=True).start()
