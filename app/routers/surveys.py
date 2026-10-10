"""Anket modülü: Sistem Yöneticisi (master) anket açar (sorular), TÜM personel zorunlu cevaplar,
yönetici cevapları/sonuçları görür. Zorunlu (mandatory) + cevaplanmamış aktif anket varsa ana ekranda uyarı şeridi.
Soru tipleri: text (serbest), single (tek seçim), multi (çok seçim), rating (1-5), yesno (Evet/Hayır).
Anonim anket (anonymous=1) → yönetici kimin cevapladığını görmez, yalnız toplam dağılımları görür."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api')
me_user = auth.current_user

QTYPES = ('text', 'single', 'multi', 'rating', 'yesno')


def _master(user=Depends(auth.current_user)):
    if not (user.get('master') or auth.ADMIN in user.get('roles', [])):
        raise HTTPException(403, 'Yalnız Sistem Yöneticisi anket yönetebilir')
    return user


def _loads(s, default=None):
    try:
        return json.loads(s) if s else (default if default is not None else [])
    except (ValueError, TypeError):
        return default if default is not None else []


def _staff_total(conn):
    """Hedef kitle: tüm aktif (silinmemiş) kullanıcı sayısı — tamamlanma oranı için."""
    r = db.row(conn.execute('SELECT COUNT(*) AS n FROM users WHERE deleted_at IS NULL'))
    return r['n'] if r else 0


def _questions(conn, survey_id):
    rows = db.rows(conn.execute(
        'SELECT id, ord, text, qtype, options, required FROM survey_questions WHERE survey_id = ? ORDER BY ord, id',
        (survey_id,)))
    return [{'id': r['id'], 'ord': r['ord'], 'text': r['text'], 'qtype': r['qtype'],
             'options': _loads(r['options']), 'required': bool(r['required'])} for r in rows]


# ---------- Kullanıcı: kendi anketleri ----------
def pending_for(conn, uid):
    """uid kullanıcısının CEVAPLAMADIĞI aktif + zorunlu anketleri (rozet + uyarı şeridi için)."""
    return db.rows(conn.execute(
        '''SELECT s.id, s.title FROM surveys s
           WHERE s.active = 1 AND s.mandatory = 1
             AND NOT EXISTS (SELECT 1 FROM survey_responses r WHERE r.survey_id = s.id AND r.user_id = ?)
           ORDER BY s.created_at''', (uid,)))


@router.get('/my/surveys')
def my_surveys(user=Depends(me_user), conn=db.DB):
    """Aktif anketler + kullanıcının her birini cevaplayıp cevaplamadığı."""
    rows = db.rows(conn.execute(
        '''SELECT s.id, s.title, s.description, s.mandatory, s.anonymous, s.created_at,
                  r.submitted_at,
                  (SELECT COUNT(*) FROM survey_questions q WHERE q.survey_id = s.id) AS q_count
           FROM surveys s
           LEFT JOIN survey_responses r ON r.survey_id = s.id AND r.user_id = ?
           WHERE s.active = 1
           ORDER BY (r.submitted_at IS NOT NULL), s.mandatory DESC, s.created_at DESC''', (user['id'],)))
    out = [{'id': r['id'], 'title': r['title'], 'description': r['description'],
            'mandatory': bool(r['mandatory']), 'anonymous': bool(r['anonymous']),
            'q_count': r['q_count'], 'answered': bool(r['submitted_at']), 'submitted_at': r['submitted_at']}
           for r in rows]
    return {'surveys': out,
            'pending': sum(1 for s in out if not s['answered']),
            'pending_mandatory': sum(1 for s in out if s['mandatory'] and not s['answered'])}


@router.get('/my/surveys/{survey_id}')
def my_survey(survey_id: int, user=Depends(me_user), conn=db.DB):
    """Anket + soruları + (daha önce cevapladıysa) kendi cevapları."""
    s = db.row(conn.execute('SELECT * FROM surveys WHERE id = ? AND active = 1', (survey_id,)))
    if not s:
        raise HTTPException(404, 'Anket bulunamadı')
    resp = db.row(conn.execute('SELECT id, submitted_at FROM survey_responses WHERE survey_id = ? AND user_id = ?',
                               (survey_id, user['id'])))
    answers = {}
    if resp:
        for a in db.rows(conn.execute('SELECT question_id, value FROM survey_answers WHERE response_id = ?', (resp['id'],))):
            answers[a['question_id']] = a['value']
    return {'id': s['id'], 'title': s['title'], 'description': s['description'],
            'mandatory': bool(s['mandatory']), 'anonymous': bool(s['anonymous']),
            'questions': _questions(conn, survey_id),
            'answered': bool(resp), 'submitted_at': resp['submitted_at'] if resp else None,
            'my_answers': answers}


class SubmitIn(BaseModel):
    answers: dict   # {question_id(str): value}  (multi: liste; diğer: metin/sayı)


@router.post('/my/surveys/{survey_id}/submit')
def submit_survey(survey_id: int, body: SubmitIn, user=Depends(me_user), conn=db.DB):
    """Kullanıcının cevaplarını kaydeder (tek sefer; zorunlu sorular boş bırakılamaz)."""
    s = db.row(conn.execute('SELECT id FROM surveys WHERE id = ? AND active = 1', (survey_id,)))
    if not s:
        raise HTTPException(404, 'Anket bulunamadı')
    if db.row(conn.execute('SELECT id FROM survey_responses WHERE survey_id = ? AND user_id = ?', (survey_id, user['id']))):
        raise HTTPException(409, 'Bu anketi zaten cevapladınız')
    qs = _questions(conn, survey_id)
    clean = {}   # question_id -> saklanacak metin değeri
    for q in qs:
        raw = body.answers.get(str(q['id']))
        if q['qtype'] == 'multi':
            vals = [str(x).strip() for x in (raw or []) if str(x).strip()]
            vals = [v for v in vals if v in q['options']]
            if q['required'] and not vals:
                raise HTTPException(400, f"Zorunlu soru boş bırakılamaz: {q['text']}")
            clean[q['id']] = json.dumps(vals, ensure_ascii=False) if vals else None
        else:
            val = ('' if raw is None else str(raw)).strip()
            if q['qtype'] == 'single' and val and val not in q['options']:
                raise HTTPException(400, f"Geçersiz seçenek: {q['text']}")
            if q['qtype'] == 'rating':
                val = val if val in ('1', '2', '3', '4', '5') else ''
            if q['qtype'] == 'yesno' and val and val not in ('Evet', 'Hayır'):
                val = ''
            if q['qtype'] == 'text':
                val = val[:2000]
            if q['required'] and not val:
                raise HTTPException(400, f"Zorunlu soru boş bırakılamaz: {q['text']}")
            clean[q['id']] = val or None
    cur = conn.execute('INSERT INTO survey_responses (survey_id, user_id, submitted_at) VALUES (?,?,?)',
                       (survey_id, user['id'], db.now()))
    rid = cur.lastrowid
    for qid, val in clean.items():
        conn.execute('INSERT INTO survey_answers (response_id, question_id, value) VALUES (?,?,?)', (rid, qid, val))
    return {'ok': True}


# ---------- Sistem Yöneticisi: anket yönetimi ----------
class QuestionIn(BaseModel):
    text: str
    qtype: str = 'single'
    options: list | None = None
    required: bool = True


class SurveyIn(BaseModel):
    title: str
    description: str | None = None
    mandatory: bool = True
    anonymous: bool = False
    active: bool = True
    questions: list[QuestionIn] = []


def _validate(body: SurveyIn):
    title = (body.title or '').strip()[:200]
    if not title:
        raise HTTPException(400, 'Anket başlığı zorunlu')
    if not body.questions:
        raise HTTPException(400, 'En az bir soru ekleyin')
    qs = []
    for i, q in enumerate(body.questions):
        qt = q.qtype if q.qtype in QTYPES else 'single'
        text = (q.text or '').strip()[:500]
        if not text:
            raise HTTPException(400, f'{i + 1}. sorunun metni boş olamaz')
        opts = [str(o).strip()[:200] for o in (q.options or []) if str(o).strip()] if qt in ('single', 'multi') else []
        if qt in ('single', 'multi') and len(opts) < 2:
            raise HTTPException(400, f'{i + 1}. soru için en az 2 seçenek girin')
        qs.append((i, text, qt, json.dumps(opts, ensure_ascii=False) if opts else None, int(bool(q.required))))
    return title, qs


def _write_questions(conn, survey_id, qs):
    for ord_, text, qt, opts, req in qs:
        conn.execute('INSERT INTO survey_questions (survey_id, ord, text, qtype, options, required) VALUES (?,?,?,?,?,?)',
                     (survey_id, ord_, text, qt, opts, req))


@router.get('/surveys')
def list_surveys(user=Depends(_master), conn=db.DB):
    """Tüm anketler + kaç kişi cevapladı / toplam personel (tamamlanma oranı)."""
    total = _staff_total(conn)
    rows = db.rows(conn.execute(
        '''SELECT s.id, s.title, s.description, s.mandatory, s.anonymous, s.active, s.created_at, s.closed_at,
                  (SELECT COUNT(*) FROM survey_questions q WHERE q.survey_id = s.id) AS q_count,
                  (SELECT COUNT(*) FROM survey_responses r WHERE r.survey_id = s.id) AS answered
           FROM surveys s ORDER BY s.active DESC, s.created_at DESC'''))
    return {'total_staff': total,
            'surveys': [{'id': r['id'], 'title': r['title'], 'description': r['description'],
                         'mandatory': bool(r['mandatory']), 'anonymous': bool(r['anonymous']),
                         'active': bool(r['active']), 'created_at': r['created_at'], 'closed_at': r['closed_at'],
                         'q_count': r['q_count'], 'answered': r['answered'], 'total': total} for r in rows]}


@router.get('/surveys/{survey_id}')
def get_survey(survey_id: int, user=Depends(_master), conn=db.DB):
    s = db.row(conn.execute('SELECT * FROM surveys WHERE id = ?', (survey_id,)))
    if not s:
        raise HTTPException(404, 'Anket bulunamadı')
    answered = db.row(conn.execute('SELECT COUNT(*) AS n FROM survey_responses WHERE survey_id = ?', (survey_id,)))['n']
    return {'id': s['id'], 'title': s['title'], 'description': s['description'], 'mandatory': bool(s['mandatory']),
            'anonymous': bool(s['anonymous']), 'active': bool(s['active']), 'questions': _questions(conn, survey_id),
            'answered': answered, 'locked': answered > 0}


@router.post('/surveys')
def create_survey(body: SurveyIn, user=Depends(_master), conn=db.DB):
    title, qs = _validate(body)
    cur = conn.execute(
        '''INSERT INTO surveys (title, description, mandatory, anonymous, active, created_by, created_at)
           VALUES (?,?,?,?,?,?,?)''',
        (title, (body.description or '').strip()[:2000] or None, int(body.mandatory), int(body.anonymous),
         int(body.active), user['id'], db.now()))
    sid = cur.lastrowid
    _write_questions(conn, sid, qs)
    _notify_staff(conn, title, sid)
    return {'id': sid}


@router.put('/surveys/{survey_id}')
def edit_survey(survey_id: int, body: SurveyIn, user=Depends(_master), conn=db.DB):
    """Düzenle. Cevap gelmişse sorular DEĞİŞTİRİLEMEZ (yalnız başlık/açıklama/zorunluluk/aktiflik)."""
    s = db.row(conn.execute('SELECT id FROM surveys WHERE id = ?', (survey_id,)))
    if not s:
        raise HTTPException(404, 'Anket bulunamadı')
    answered = db.row(conn.execute('SELECT COUNT(*) AS n FROM survey_responses WHERE survey_id = ?', (survey_id,)))['n']
    title, qs = _validate(body)
    conn.execute('UPDATE surveys SET title = ?, description = ?, mandatory = ?, anonymous = ?, active = ? WHERE id = ?',
                 (title, (body.description or '').strip()[:2000] or None, int(body.mandatory),
                  int(body.anonymous), int(body.active), survey_id))
    if not answered:   # henüz cevap yok → soruları tazele
        conn.execute('DELETE FROM survey_questions WHERE survey_id = ?', (survey_id,))
        _write_questions(conn, survey_id, qs)
    return {'ok': True, 'questions_locked': answered > 0}


@router.post('/surveys/{survey_id}/close')
def close_survey(survey_id: int, user=Depends(_master), conn=db.DB):
    """Anketi kapat (yeni cevap alınmaz; sonuçlar kalır). Yeniden açmak için reopen."""
    if not conn.execute('UPDATE surveys SET active = 0, closed_at = ? WHERE id = ?', (db.now(), survey_id)).rowcount:
        raise HTTPException(404, 'Anket bulunamadı')
    return {'ok': True}


@router.post('/surveys/{survey_id}/reopen')
def reopen_survey(survey_id: int, user=Depends(_master), conn=db.DB):
    if not conn.execute('UPDATE surveys SET active = 1, closed_at = NULL WHERE id = ?', (survey_id,)).rowcount:
        raise HTTPException(404, 'Anket bulunamadı')
    return {'ok': True}


@router.delete('/surveys/{survey_id}')
def delete_survey(survey_id: int, user=Depends(_master), conn=db.DB):
    if not conn.execute('DELETE FROM surveys WHERE id = ?', (survey_id,)).rowcount:
        raise HTTPException(404, 'Anket bulunamadı')
    return {'ok': True}


@router.get('/surveys/{survey_id}/results')
def survey_results(survey_id: int, user=Depends(_master), conn=db.DB):
    """Sonuç özeti: her soru için dağılım (seçmeli) ya da metin cevap listesi + kişi bazlı cevaplar.
    Anonim anketlerde kişi adı gizlenir (yalnız dağılımlar)."""
    s = db.row(conn.execute('SELECT * FROM surveys WHERE id = ?', (survey_id,)))
    if not s:
        raise HTTPException(404, 'Anket bulunamadı')
    anon = bool(s['anonymous'])
    qs = _questions(conn, survey_id)
    total = _staff_total(conn)
    responses = db.rows(conn.execute(
        '''SELECT r.id, r.user_id, r.submitted_at, u.full_name
           FROM survey_responses r JOIN users u ON u.id = r.user_id
           WHERE r.survey_id = ? ORDER BY r.submitted_at''', (survey_id,)))
    # cevapları response bazında topla
    ans_by_resp = {}
    for a in db.rows(conn.execute(
            '''SELECT a.response_id, a.question_id, a.value FROM survey_answers a
               JOIN survey_responses r ON r.id = a.response_id WHERE r.survey_id = ?''', (survey_id,))):
        ans_by_resp.setdefault(a['response_id'], {})[a['question_id']] = a['value']

    # soru bazlı dağılım
    summary = []
    for q in qs:
        item = {'id': q['id'], 'text': q['text'], 'qtype': q['qtype'], 'options': q['options']}
        if q['qtype'] in ('single', 'multi', 'yesno', 'rating'):
            opts = q['options'] if q['qtype'] in ('single', 'multi') else (
                ['Evet', 'Hayır'] if q['qtype'] == 'yesno' else ['1', '2', '3', '4', '5'])
            counts = {o: 0 for o in opts}
            for resp in responses:
                v = ans_by_resp.get(resp['id'], {}).get(q['id'])
                if not v:
                    continue
                picks = _loads(v) if q['qtype'] == 'multi' else [v]
                for p in picks:
                    if p in counts:
                        counts[p] += 1
            item['counts'] = [{'option': o, 'count': counts[o]} for o in opts]
        else:   # text
            item['texts'] = [{'name': None if anon else resp['full_name'],
                              'value': ans_by_resp.get(resp['id'], {}).get(q['id'])}
                             for resp in responses if ans_by_resp.get(resp['id'], {}).get(q['id'])]
        summary.append(item)

    # kişi bazlı (anonim değilse)
    people = []
    if not anon:
        for resp in responses:
            people.append({'name': resp['full_name'], 'submitted_at': resp['submitted_at'],
                           'answers': [{'q': q['text'], 'qtype': q['qtype'],
                                        'value': _fmt(ans_by_resp.get(resp['id'], {}).get(q['id']), q['qtype'])}
                                       for q in qs]})
    return {'id': s['id'], 'title': s['title'], 'anonymous': anon, 'mandatory': bool(s['mandatory']),
            'active': bool(s['active']), 'total_staff': total, 'answered': len(responses),
            'summary': summary, 'people': people}


def _fmt(value, qtype):
    if value is None:
        return ''
    if qtype == 'multi':
        return ', '.join(_loads(value))
    return value


def _notify_staff(conn, title, survey_id):
    """Yeni anket açılınca tüm aktif kullanıcılara anında push (uygulama içi rozet 'survey' notifier'ından da gelir)."""
    try:
        from .. import push
        uids = [r['id'] for r in db.rows(conn.execute('SELECT id FROM users WHERE deleted_at IS NULL'))]
        if uids:
            push.send(uids, {'type': 'notif', 'title': 'Yeni anket', 'tag': 'notif-survey',
                             'body': title, 'url': '/app#/my-surveys'})
    except Exception:   # noqa: BLE001 — bildirim hatası anket oluşturmayı bozmasın
        pass
