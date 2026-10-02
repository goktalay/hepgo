"""Toplantı ekranı: başlat / bitir, canlı katılım, kişisel notlar, ses kaydı, konuşmacılar ve toplantı özeti.

- Toplantıyı yalnızca düzenleyen başlatır ve bitirir. Notlar ve ses kaydı toplantı başladıktan sonra, bitene kadar çalışır.
- Ses kaydı düzenleyenin cihazından alınır ve kayıt sürerken parça parça (sıra numarasıyla) sunucuya eklenir; bağlantı
  kopsa bile gelen kısım kaybolmaz.
- "Toplantıyı bitir" denince kayıtlar arka planda işlenir (app/meeting_audio.py): metne çevrilir, konuşmacılara ayrılır,
  kayıtlı ses profilleriyle eşleşenler tanınır, kalanlar "Tanımsız kişi N" olur.
- Konuşmacı bir kişiye atanınca o kişinin ses profili öğrenilir (sonraki toplantılarda otomatik tanınır) ve bu toplantının
  diğer tanımsız konuşmacıları güncel profillerle yeniden denenir.
- Özet: katılımcılar, konuşma süreleri, kararlar / yapılacaklar / sorular (dökümden anahtar ifadelerle), herkesin notları ve
  konuşmacı adlı tam döküm. Katılımcılar görür; notlar toplantı bitince herkese açılır.
"""
import json
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from .. import auth, config, db, meeting_audio
from .meetings import _get

router = APIRouter(prefix='/api/meetings')
CHUNK_MAX = 8 * 1024 * 1024
_presence = {}   # (toplantı, kullanıcı) → son görülme (sn)


def _organizer(m, user):
    if not m['can_edit']:
        raise HTTPException(403, 'Bunu yalnızca toplantıyı düzenleyen yapabilir')


def _state(m):
    return 'BITTI' if m['ended_at'] else 'DEVAM' if m['started_at'] else 'BASLAMADI'


def _room(conn, m, user):
    now = time.time()
    online = {uid for (mid, uid), t in _presence.items() if mid == m['id'] and now - t < 20}
    people = [{'id': m['created_by'], 'full_name': m['organizer'], 'status': 'DUZENLEYEN', 'online': m['created_by'] in online,
               'photo': conn.execute('SELECT photo FROM users WHERE id = ?', (m['created_by'],)).fetchone()[0]}]
    people += [{'id': i['user_id'], 'full_name': i['full_name'], 'photo': i['photo'], 'status': i['status'], 'online': i['user_id'] in online}
               for i in m['invites']]
    note = conn.execute('SELECT body, updated_at FROM team_meeting_notes WHERE meeting_id = ? AND user_id = ?', (m['id'], user['id'])).fetchone()
    rec = db.row(conn.execute('SELECT id, started_at, chunks FROM team_meeting_audio WHERE meeting_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1',
                              (m['id'],)))
    recorded = conn.execute('SELECT COUNT(*), SUM(chunks) FROM team_meeting_audio WHERE meeting_id = ?', (m['id'],)).fetchone()
    return {**m, 'state': _state(m), 'people': people, 'my_note': note[0] if note else '', 'note_saved_at': note[1] if note else None,
            'recording': rec, 'recordings': recorded[0], 'audio_available': meeting_audio.available(), 'server_time': db.now()}


@router.get('/{mid}/room')
def room(mid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    if m['cancelled_at']:
        raise HTTPException(400, 'Toplantı iptal edildi')
    _presence[(mid, user['id'])] = time.time()
    if m['started_at'] and not m['ended_at'] and user['id'] != m['created_by']:
        conn.execute('UPDATE team_meeting_invites SET joined_at = IFNULL(joined_at, ?), last_seen = ? WHERE meeting_id = ? AND user_id = ?',
                     (db.now(), db.now(), mid, user['id']))
    return _room(conn, m, user)


@router.post('/{mid}/start')
def start(mid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    _organizer(m, user)
    if m['cancelled_at'] or m['ended_at']:
        raise HTTPException(400, 'Toplantı iptal edildi ya da bitti')
    if not m['started_at']:
        conn.execute('UPDATE team_meetings SET started_at = ? WHERE id = ?', (db.now(), mid))
        db.audit(conn, user['id'], 'Toplantıyı başlattı', 'meeting', mid, m['title'])
    return _room(conn, _get(conn, mid, user), user)


@router.post('/{mid}/end')
def end(mid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    _organizer(m, user)
    if not m['started_at']:
        raise HTTPException(400, 'Toplantı başlamadı')
    if m['ended_at']:
        raise HTTPException(400, 'Toplantı zaten bitti')
    now = db.now()
    conn.execute('UPDATE team_meeting_audio SET ended_at = ? WHERE meeting_id = ? AND ended_at IS NULL', (now, mid))
    has_audio = conn.execute('SELECT COUNT(*) FROM team_meeting_audio WHERE meeting_id = ? AND chunks > 0', (mid,)).fetchone()[0]
    conn.execute('UPDATE team_meetings SET ended_at = ?, process_status = ? WHERE id = ?',
                 (now, 'ISLENIYOR' if has_audio and meeting_audio.available() else 'TAMAM', mid))
    db.audit(conn, user['id'], 'Toplantıyı bitirdi', 'meeting', mid, m['title'])
    conn.commit()
    if has_audio and meeting_audio.available():
        meeting_audio.start(mid)
    return _room(conn, _get(conn, mid, user), user)


# ---------- Notlar
class NoteIn(BaseModel):
    body: str
    user_id: Optional[int] = None   # toplantı bittikten sonra düzenleyen, katılımcının notunu düzeltebilir


@router.put('/{mid}/notes')
def save_note(mid: int, body: NoteIn, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    if not m['started_at']:
        raise HTTPException(400, 'Notlar toplantı başlayınca alınabilir')
    owner = user['id']
    if body.user_id and body.user_id != user['id']:   # başkasının notu: yalnızca düzenleyen, toplantı bittikten sonra
        if not m['ended_at']:
            raise HTTPException(400, 'Katılımcı notları toplantı bitince düzenlenebilir')
        _organizer(m, user)
        if not conn.execute('SELECT 1 FROM team_meeting_notes WHERE meeting_id = ? AND user_id = ?', (mid, body.user_id)).fetchone():
            raise HTTPException(404, 'Not bulunamadı')
        owner = body.user_id
    conn.execute('''INSERT INTO team_meeting_notes (meeting_id, user_id, body, updated_at, edited_by) VALUES (?,?,?,?,?)
                    ON CONFLICT(meeting_id, user_id) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at,
                    edited_by = excluded.edited_by''',
                 (mid, owner, body.body[:20000], db.now(), user['id'] if owner != user['id'] else None))
    if m['ended_at']:
        db.audit(conn, user['id'], 'Toplantı notunu düzenledi (toplantı sonrası)', 'meeting', mid, m['title'])
    return {'saved_at': db.now()}


# ---------- Ses kaydı (düzenleyenin cihazı; parça parça)
def _audio_dir(mid):
    d = config.UPLOAD_DIR / 'meetings' / str(mid)
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post('/{mid}/audio/start')
def audio_start(mid: int, ext: str = 'webm', user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    _organizer(m, user)
    if not m['started_at'] or m['ended_at']:
        raise HTTPException(400, 'Ses kaydı toplantı başladıktan sonra, bitene kadar açılabilir')
    ext = ext if ext in ('webm', 'ogg', 'm4a', 'mp4') else 'webm'
    conn.execute('UPDATE team_meeting_audio SET ended_at = ? WHERE meeting_id = ? AND ended_at IS NULL', (db.now(), mid))
    aid = conn.execute('INSERT INTO team_meeting_audio (meeting_id, file, started_at) VALUES (?,?,?)', (mid, '', db.now())).lastrowid
    rel = f'meetings/{mid}/kayit-{aid}.{ext}'
    (_audio_dir(mid) / f'kayit-{aid}.{ext}').write_bytes(b'')
    conn.execute('UPDATE team_meeting_audio SET file = ? WHERE id = ?', (rel, aid))
    db.audit(conn, user['id'], 'Toplantı ses kaydını başlattı', 'meeting', mid, None)
    return {'id': aid}


@router.post('/{mid}/audio/{aid}/chunk')
async def audio_chunk(mid: int, aid: int, seq: int, request: Request, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    _organizer(m, user)
    a = db.row(conn.execute('SELECT * FROM team_meeting_audio WHERE id = ? AND meeting_id = ?', (aid, mid)))
    if not a or a['ended_at']:
        raise HTTPException(400, 'Kayıt kapalı')
    if seq != a['chunks']:   # sıra dışı / tekrar gönderilen parça
        return {'chunks': a['chunks'], 'skipped': True}
    data = await request.body()
    if len(data) > CHUNK_MAX:
        raise HTTPException(400, 'Parça çok büyük')
    with open(config.UPLOAD_DIR / a['file'], 'ab') as f:
        f.write(data)
    conn.execute('UPDATE team_meeting_audio SET chunks = chunks + 1 WHERE id = ?', (aid,))
    return {'chunks': a['chunks'] + 1}


@router.post('/{mid}/audio/{aid}/stop')
def audio_stop(mid: int, aid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    _organizer(m, user)
    conn.execute('UPDATE team_meeting_audio SET ended_at = IFNULL(ended_at, ?) WHERE id = ? AND meeting_id = ?', (db.now(), aid, mid))
    return {'ok': True}


# ---------- Özet, konuşmacılar
DECISION = re.compile(r'\b(karar|kararlaştır|onayla|anlaştık|uzlaş|kesinleş|netleş)', re.I)
ACTION = re.compile(r'\b(yapılacak|yapacağ|yapalım|yapsın|hazırla|gönder|teslim|bitir|takip|sorumlu|görev|ayarla|kontrol|ilet|'
                    r'araştır|sipariş ver|planla|tamamla|düzelt|başla|hallet)|\w+(?:ecek|acak|ecekler|acaklar|meli|malı)\b', re.I)   # gelecek zaman / gereklilik
WHEN = re.compile(r'\b(bugün|yarın|pazartesi|salı|çarşamba|perşembe|cuma|cumartesi|pazar|hafta|ay sonu|ay başı|saat \d+|\d{1,2}[./]\d{1,2})', re.I)


def _sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 8]


def summary_data(conn, m):
    speakers = db.rows(conn.execute(
        '''SELECT s.id, s.label, s.user_id, s.auto, s.score, s.seconds, u.full_name FROM team_meeting_speakers s
           LEFT JOIN users u ON u.id = s.user_id WHERE s.meeting_id = ? ORDER BY s.seconds DESC''', (m['id'],)))
    names = {s['id']: (s['full_name'] or s['label']) for s in speakers}
    segs = db.rows(conn.execute('SELECT id, audio_id, speaker_id, t0, t1, at, text FROM team_meeting_segments WHERE meeting_id = ? ORDER BY at, t0',
                                (m['id'],)))
    for s in segs:
        s['speaker'] = names.get(s['speaker_id'], '—')
    notes = db.rows(conn.execute(
        '''SELECT n.user_id, u.full_name, n.body, n.updated_at, e.full_name AS edited_by_name FROM team_meeting_notes n
           JOIN users u ON u.id = n.user_id LEFT JOIN users e ON e.id = n.edited_by
           WHERE n.meeting_id = ? AND TRIM(n.body) != '' ORDER BY u.full_name''', (m['id'],)))
    points = {'decisions': [], 'actions': [], 'questions': []}
    for s in segs:
        for sent in _sentences(s['text']):
            item = {'speaker': s['speaker'], 'at': s['at'], 'text': sent, 'when': bool(WHEN.search(sent))}
            if DECISION.search(sent):
                points['decisions'].append(item)
            elif ACTION.search(sent):
                points['actions'].append(item)
            elif sent.endswith('?'):
                points['questions'].append(item)
    for n in notes:   # notlardaki madde satırları da kararlar / yapılacaklar arasına
        for line in n['body'].splitlines():
            line = line.strip(' -*•\t')
            if len(line) < 6:
                continue
            item = {'speaker': f'{n["full_name"]} (not)', 'at': n['updated_at'], 'text': line, 'when': bool(WHEN.search(line))}
            if DECISION.search(line):
                points['decisions'].append(item)
            elif ACTION.search(line):
                points['actions'].append(item)
    total = sum(s['seconds'] for s in speakers) or 0
    for s in speakers:
        s['share'] = round(100 * s['seconds'] / total) if total else 0
    rec = conn.execute('SELECT SUM(seconds) FROM team_meeting_audio WHERE meeting_id = ?', (m['id'],)).fetchone()[0]
    return {'speakers': speakers, 'segments': segs, 'notes': notes, 'points': points, 'recorded_seconds': rec or 0}


@router.get('/{mid}/summary')
def summary(mid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    if not m['ended_at']:
        raise HTTPException(400, 'Özet toplantı bitince hazırlanır')
    out = {**m, **summary_data(conn, m)}
    out['people'] = _room(conn, m, user)['people']
    out['joined'] = [r[0] for r in conn.execute('SELECT user_id FROM team_meeting_invites WHERE meeting_id = ? AND joined_at IS NOT NULL', (mid,))]
    out['me'] = user['id']
    return out


class SpeakerIn(BaseModel):
    user_id: int | None = None


@router.put('/{mid}/speakers/{sid}')
def assign_speaker(mid: int, sid: int, body: SpeakerIn, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    _organizer(m, user)
    sp = db.row(conn.execute('SELECT * FROM team_meeting_speakers WHERE id = ? AND meeting_id = ?', (sid, mid)))
    if not sp:
        raise HTTPException(404, 'Konuşmacı bulunamadı')
    if body.user_id is None:
        n = conn.execute("SELECT COUNT(*) FROM team_meeting_speakers WHERE meeting_id = ? AND user_id IS NULL", (mid,)).fetchone()[0]
        conn.execute('UPDATE team_meeting_speakers SET user_id = NULL, auto = 0, label = ? WHERE id = ?', (f'Tanımsız kişi {n + 1}', sid))
        return summary(mid, user, conn)
    u = conn.execute('SELECT full_name FROM users WHERE id = ? AND deleted_at IS NULL', (body.user_id,)).fetchone()
    if not u:
        raise HTTPException(400, 'Kişi bulunamadı')
    # Aynı kişiye atanmış başka konuşmacı varsa birleştir (bölütler bu konuşmacıya geçer)
    for other in db.rows(conn.execute('SELECT id, seconds FROM team_meeting_speakers WHERE meeting_id = ? AND user_id = ? AND id != ?',
                                      (mid, body.user_id, sid))):
        conn.execute('UPDATE team_meeting_segments SET speaker_id = ? WHERE speaker_id = ?', (sid, other['id']))
        conn.execute('UPDATE team_meeting_speakers SET seconds = seconds + ? WHERE id = ?', (other['seconds'], sid))
        conn.execute('DELETE FROM team_meeting_speakers WHERE id = ?', (other['id'],))
    conn.execute('UPDATE team_meeting_speakers SET user_id = ?, auto = 0, label = ? WHERE id = ?', (body.user_id, u[0], sid))
    if sp['embedding']:   # ses profili: bu konuşma süresi kadar ağırlıkla öğren
        meeting_audio.learn(conn, body.user_id, json.loads(sp['embedding']), weight=max(1, min(10, round((sp['seconds'] or 0) / 30))))
    meeting_audio.rematch(conn, mid)
    db.audit(conn, user['id'], 'Toplantı konuşmacısını atadı', 'meeting', mid, u[0])
    return summary(mid, user, conn)


@router.post('/{mid}/reprocess')
def reprocess(mid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _get(conn, mid, user)
    _organizer(m, user)
    if not m['ended_at'] or not meeting_audio.available():
        raise HTTPException(400, 'Yeniden işlenemez')
    conn.execute("UPDATE team_meetings SET process_status = 'ISLENIYOR' WHERE id = ?", (mid,))
    conn.commit()
    meeting_audio.start(mid)
    return {'ok': True}


def _wav_of(conn, mid, aid):
    a = db.row(conn.execute('SELECT wav FROM team_meeting_audio WHERE id = ? AND meeting_id = ?', (aid, mid)))
    if not a or not a['wav'] or not (config.UPLOAD_DIR / a['wav']).exists():
        raise HTTPException(404, 'Ses bulunamadı')
    return config.UPLOAD_DIR / a['wav']


@router.get('/{mid}/speakers/{sid}/sample')
def speaker_sample(mid: int, sid: int, user=Depends(auth.current_user), conn=db.DB):
    _get(conn, mid, user)
    seg = db.row(conn.execute('SELECT audio_id, t0, t1 FROM team_meeting_segments WHERE meeting_id = ? AND speaker_id = ? '
                              'ORDER BY (t1 - t0) DESC LIMIT 1', (mid, sid)))
    if not seg:
        raise HTTPException(404, 'Örnek yok')
    t1 = min(seg['t1'], seg['t0'] + 15)
    return Response(meeting_audio.clip_wav(_wav_of(conn, mid, seg['audio_id']), seg['t0'], t1), media_type='audio/wav',
                    headers={'Cache-Control': 'private, max-age=600'})


@router.get('/{mid}/segments/{seg_id}/audio')
def segment_audio(mid: int, seg_id: int, user=Depends(auth.current_user), conn=db.DB):
    _get(conn, mid, user)
    seg = db.row(conn.execute('SELECT audio_id, t0, t1 FROM team_meeting_segments WHERE id = ? AND meeting_id = ?', (seg_id, mid)))
    if not seg:
        raise HTTPException(404, 'Bölüt bulunamadı')
    return Response(meeting_audio.clip_wav(_wav_of(conn, mid, seg['audio_id']), seg['t0'], min(seg['t1'], seg['t0'] + 60)),
                    media_type='audio/wav', headers={'Cache-Control': 'private, max-age=600'})

