"""Görüntülü online toplantı (Zoom tarzı): davet kodu, bekleme odası, şirket içi/dışı katılımcı, WebRTC mesh.

Sinyalleşme /ws/meet üzerinden (içerik kullanıcı için oturum çerezi, dış katılımcı için ?token=). Ses/görüntü AKIŞI
tarayıcılar arasında uçtan uca (mesh). Toplantı başlamadıysa gelen bekler; bekleme odası açıksa host tek tek kabul eder.
Kayıt açıksa her katılımcı kendi mikrofonunu kaydeder; bitince meet_audio ile metne çevrilir.
"""
import asyncio
import json
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import auth, db, push
from ..files import save_upload

router = APIRouter(prefix='/api/meet')
ws_router = APIRouter()

# mid -> { connid -> {ws, info} }   info: {pid, name, photo, user_id, is_external, role, hand, muted, cam, sharing}
LIVE = {}
WAIT = {}
EMPTY_GRACE = 45    # herkes çıktıktan sonra (sayfa yenileme / kısa kopma için) beklenen süre; sonra toplantı kendiliğinden biter
_autoend = {}       # mid -> asyncio.Task


def _schedule_autoend(mid, delay=None):
    """Odada kimse kalmadıysa `delay` sn sonra hâlâ boşsa toplantıyı bitirir (canlı görünmeye devam etmesin)."""
    old = _autoend.pop(mid, None)
    if old and not old.done():
        old.cancel()

    async def run():
        try:
            await asyncio.sleep(EMPTY_GRACE if delay is None else delay)
        except asyncio.CancelledError:
            return
        if not LIVE.get(mid) and not WAIT.get(mid):
            await _end_meeting(mid)
        _autoend.pop(mid, None)
    _autoend[mid] = asyncio.get_running_loop().create_task(run())


def _sql(sql, args=()):
    with db.connect() as c:
        c.execute(sql, args)


async def _db(fn, *args):
    """Veritabanı işi ana döngüde değil iş parçacığında: veritabanı meşgulken sunucu donmasın."""
    return await asyncio.to_thread(fn, *args)


async def end_stale_on_startup(delay=90):
    """Sunucu yeniden başlayınca: 'devam ediyor' görünen ama kimsenin bağlanmadığı toplantılar `delay` sn sonra biter."""
    await asyncio.sleep(delay)
    def q():
        with db.connect() as c:
            return [r[0] for r in c.execute("SELECT id FROM online_meetings WHERE status = 'DEVAM'")]
    for mid in await _db(q):
        if not LIVE.get(mid) and not WAIT.get(mid):
            await _end_meeting(mid)


def _code():
    a = secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')
    return f'{a}{secrets.randbelow(900) + 100}-{secrets.randbelow(900) + 100}'


def _state(m):
    return m['status']


def _mpay(mid, m):
    """Odaya giren istemciye toplantı özeti (başlık, kayıt, başlama zamanı → süre sayacı)."""
    return {'id': mid, 'title': m['title'], 'record': bool(m['record']), 'code': m['code'],
            'started_at': m.get('started_at'), 'now': db.now(), 'invite_text': invite_text(dict(m))}


# ---------- REST ----------
class CreateIn(BaseModel):
    title: str
    waiting_room: bool = True
    record: bool = False
    scheduled_at: Optional[str] = None
    duration_min: int = 60
    send_email: bool = False           # oluşturunca katılımcılara logolu davet e-postası (sahibinin bağlı posta hesabından)
    user_ids: list[int] = []           # şirket içi davetliler
    externals: list[dict] = []         # [{name, email?}]


TR_DAYS = ('Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar')
TR_MONTHS = ('Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık')
TZ_NAME = 'Europe/Istanbul'


def when_lines(scheduled_at, duration_min):
    """'Perşembe, 15 Ekim · 15:00 – 16:00' + saat dilimi; zaman yoksa boş liste."""
    if not scheduled_at:
        return []
    from datetime import datetime, timedelta
    try:
        st = datetime.fromisoformat(scheduled_at[:19])
    except ValueError:
        return []
    en = st + timedelta(minutes=int(duration_min or 60))
    day = f'{TR_DAYS[st.weekday()]}, {st.day} {TR_MONTHS[st.month - 1]}'
    if st.year != datetime.now().year:
        day += f' {st.year}'
    return [f"{day} · {st.strftime('%H:%M')} – {en.strftime('%H:%M')}", f'Saat dilimi: {TZ_NAME}']


def invite_text(m, link=None):
    """Google Meet davet metni biçiminde: başlık, tarih-saat, saat dilimi, katılma bilgileri, bağlantı, kod."""
    from .. import config
    lines = [m['title'], *when_lines(m.get('scheduled_at'), m.get('duration_min') or 60), '',
             f'{config.COMPANY_NAME} Görüntülü Toplantı katılma bilgileri',
             f"Görüntülü görüşme bağlantısı: {link or _public_url(m['code'])}", f"Davet kodu: {m['code']}"]
    return '\n'.join(lines)


def _meeting(conn, mid):
    return db.row(conn.execute('SELECT * FROM online_meetings WHERE id = ?', (mid,)))


def _is_host(conn, mid, user):
    m = _meeting(conn, mid)
    return bool(m and m['host_id'] == user['id'])


def _participants(conn, mid):
    return db.rows(conn.execute(
        '''SELECT p.id, p.user_id, p.name, p.email, p.is_external, p.role, p.state, p.token, u.photo
           FROM online_meeting_participants p LEFT JOIN users u ON u.id = p.user_id
           WHERE p.meeting_id = ? ORDER BY p.role DESC, p.id''', (mid,)))


def _public_url(code):
    from .. import config
    base = config.PUBLIC_URL or config.LOCAL_URL
    return f'{base}/m/{code}'


@router.post('')
def create_meeting(body: CreateIn, user=Depends(auth.current_user), conn=db.DB):
    if not body.title.strip():
        raise HTTPException(400, 'Başlık zorunlu')
    code = _code()
    while conn.execute('SELECT 1 FROM online_meetings WHERE code = ?', (code,)).fetchone():
        code = _code()
    mid = conn.execute(
        '''INSERT INTO online_meetings (code, title, host_id, waiting_room, record, scheduled_at, duration_min, created_at)
           VALUES (?,?,?,?,?,?,?,?)''',
        (code, body.title.strip()[:200], user['id'], int(body.waiting_room), int(body.record),
         body.scheduled_at, max(5, min(int(body.duration_min or 60), 1440)), db.now())).lastrowid
    # host katılımcı
    conn.execute("INSERT INTO online_meeting_participants (meeting_id, user_id, name, role, state, created_at) VALUES (?,?,?,'host','KABUL',?)",
                 (mid, user['id'], user['full_name'], db.now()))
    for uid in dict.fromkeys(i for i in body.user_ids if i and i != user['id']):
        u = db.row(conn.execute('SELECT full_name FROM users WHERE id = ? AND active = 1', (uid,)))
        if u:
            conn.execute('INSERT INTO online_meeting_participants (meeting_id, user_id, name, created_at) VALUES (?,?,?,?)',
                         (mid, uid, u['full_name'], db.now()))
    out_ext = []
    for e in body.externals[:50]:
        name = (e.get('name') or '').strip()[:120]
        if not name:
            continue
        tok = secrets.token_urlsafe(18)
        conn.execute('''INSERT INTO online_meeting_participants (meeting_id, name, email, is_external, token, created_at)
                        VALUES (?,?,?,1,?,?)''', (mid, name, (e.get('email') or '').strip()[:200] or None, tok, db.now()))
        out_ext.append({'name': name, 'link': f'{_public_url(code)}?t={tok}'})
    db.audit(conn, user['id'], 'Online toplantı oluşturdu', 'online_meeting', mid, body.title[:100])
    m = _meeting(conn, mid)
    out = {'id': mid, 'code': code, 'link': _public_url(code), 'externals': out_ext, 'invite_text': invite_text(m)}
    if body.send_email:
        try:
            out['email'] = _send_invites(conn, m, user)
        except HTTPException as e:
            out['email'] = {'error': e.detail}
    return out


def _mail_html(m, link, logo_url, company):
    """Logolu davet e-postası (HTML)."""
    esc = lambda x: str(x or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    when = when_lines(m.get('scheduled_at'), m.get('duration_min') or 60)
    when_html = ''.join(f'<div style="font-size:15px;color:#334155;margin:2px 0">{esc(w)}</div>' for w in when)
    logo = f'<img src="{esc(logo_url)}" alt="{esc(company)}" style="max-height:56px;max-width:220px;display:block;margin-bottom:18px">' if logo_url else f'<div style="font-size:20px;font-weight:700;margin-bottom:18px">{esc(company)}</div>'
    return f'''<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:560px;margin:0 auto;padding:28px;border:1px solid #e2e8f0;border-radius:14px;color:#0f172a">
{logo}
<div style="font-size:22px;font-weight:700;margin-bottom:8px">{esc(m['title'])}</div>
{when_html}
<div style="margin:22px 0 10px;font-weight:600">{esc(company)} Görüntülü Toplantı katılma bilgileri</div>
<div style="font-size:14px;color:#334155">Görüntülü görüşme bağlantısı: <a href="{esc(link)}" style="color:#1d4ed8">{esc(link)}</a></div>
<div style="font-size:14px;color:#334155;margin-top:4px">Davet kodu: <b>{esc(m['code'])}</b></div>
<a href="{esc(link)}" style="display:inline-block;margin-top:22px;background:#1d4ed8;color:#fff;text-decoration:none;padding:12px 22px;border-radius:999px;font-weight:600">Toplantıya katıl</a>
<div style="font-size:12px;color:#94a3b8;margin-top:26px">Bu davet {esc(company)} HEPGO görüntülü toplantı sisteminden gönderildi. Tarayıcıdan, uygulama kurmadan katılabilirsiniz.</div>
</div>'''


def _send_invites(conn, m, user):
    """Katılımcılara (e-postası olan şirket içi kullanıcılar + e-postalı dış katılımcılar) sahibinin bağlı posta hesabından logolu davet."""
    from .. import config, mail
    from .system import brand_logo_url
    box = db.row(conn.execute('SELECT * FROM mail_boxes WHERE user_id = ? ORDER BY sort, id LIMIT 1', (user['id'],)))
    if not box:
        raise HTTPException(400, 'E-posta göndermek için önce Posta modülünde bir e-posta hesabı bağlayın')
    base = (config.PUBLIC_URL or config.LOCAL_URL or '').rstrip('/')
    lu = brand_logo_url(conn)
    logo_url = f'{base}{lu}' if (lu and base) else (f'{base}/static/img/logo.png' if base else None)
    rcpts = []
    for p in _participants(conn, m['id']):
        if p['role'] == 'host':
            continue
        email = p['email']
        if not email and p['user_id']:
            r = conn.execute('SELECT email FROM users WHERE id = ?', (p['user_id'],)).fetchone()
            email = r[0] if r else None
        if not email or '@' not in email:
            continue
        link = f"{_public_url(m['code'])}?t={p['token']}" if p['is_external'] and p['token'] else _public_url(m['code'])
        rcpts.append((p['name'], email, link))
    if not rcpts:
        raise HTTPException(400, 'E-posta adresi olan katılımcı yok')
    sent, errors = 0, []
    subject = f"Davet: {m['title']}" + (f" · {when_lines(m.get('scheduled_at'), m.get('duration_min'))[0]}" if m.get('scheduled_at') else '')
    for name, email, link in rcpts:
        try:
            mail.send(box, to=f'{name} <{email}>', subject=subject, body=invite_text(m, link), html=_mail_html(m, link, logo_url, config.COMPANY_NAME))
            sent += 1
        except Exception as e:   # noqa: BLE001
            errors.append(f'{email}: {e}')
    db.audit(conn, user['id'], 'Toplantı davet e-postası gönderdi', 'online_meeting', m['id'], f'{sent} alıcı')
    return {'sent': sent, 'total': len(rcpts), 'errors': errors[:5]}


@router.post('/{mid}/email')
async def send_invites(mid: int, user=Depends(auth.current_user)):
    """Davet e-postalarını (yeniden) gönder — yalnız sahibi."""
    def work():
        with db.connect() as conn:
            if not _is_host(conn, mid, user):
                raise HTTPException(403, 'Yalnızca toplantı sahibi gönderebilir')
            m = _meeting(conn, mid)
            if not m or m['status'] == 'BITTI':
                raise HTTPException(400, 'Toplantı sona ermiş')
            return _send_invites(conn, m, user)
    return await _db(work)


@router.get('/invitees')
def invitees(user=Depends(auth.current_user), conn=db.DB):
    """Toplantıya davet için aktif kullanıcı rehberi (tüm giriş yapmış kullanıcılara açık)."""
    return db.rows(conn.execute(
        'SELECT id, full_name, photo FROM users WHERE active = 1 AND deleted_at IS NULL ORDER BY full_name'))


class InviteIn(BaseModel):
    user_ids: list[int] = []


@router.post('/{mid}/invite')
async def invite_staff(mid: int, body: InviteIn, user=Depends(auth.current_user)):
    """Devam eden toplantıya şirket içi personel ekler (yalnızca sahibi); davet edilenlere bildirim gider."""
    def work():
        with db.connect() as conn:
            if not _is_host(conn, mid, user):
                return 'noauth'
            m = _meeting(conn, mid)
            if not m or m['status'] == 'BITTI':
                return 'bitti'
            added = []
            for uid in dict.fromkeys(i for i in body.user_ids if i and i != user['id']):
                u = db.row(conn.execute('SELECT full_name FROM users WHERE id = ? AND active = 1 AND deleted_at IS NULL', (uid,)))
                if not u:
                    continue
                ex = conn.execute('SELECT 1 FROM online_meeting_participants WHERE meeting_id = ? AND user_id = ?', (mid, uid)).fetchone()
                if not ex:
                    conn.execute('INSERT INTO online_meeting_participants (meeting_id, user_id, name, created_at) VALUES (?,?,?,?)',
                                 (mid, uid, u['full_name'], db.now()))
                added.append(uid)
            db.audit(conn, user['id'], 'Toplantıya kişi davet etti', 'online_meeting', mid, f'{len(added)} kişi')
            return {'added': added, 'title': m['title']}
    res = await _db(work)
    if res == 'noauth':
        raise HTTPException(403, 'Yalnızca toplantı sahibi davet edebilir')
    if res == 'bitti':
        raise HTTPException(400, 'Toplantı sona ermiş')
    if res['added']:
        push.send(res['added'], {'type': 'meet', 'title': 'Toplantı daveti',
                                 'body': f"{user['full_name']} sizi “{res['title']}” toplantısına davet etti",
                                 'tag': f'meet-{mid}', 'url': f'/app#/meet/{mid}'}, ttl=120)
        await _broadcast(mid, {'t': 'chat_sys', 'text': f"{len(res['added'])} kişi toplantıya davet edildi"})
    return {'ok': True, 'added': len(res['added'])}


@router.get('/history')
def meeting_history(user=Depends(auth.current_user), conn=db.DB):
    """Bitmiş toplantılar (sahibi ya da katılımcısı olunan), en yeniden eskiye."""
    rows = db.rows(conn.execute(
        '''SELECT m.id, m.title, m.code, m.record, m.host_id, m.scheduled_at, m.started_at, m.ended_at, m.created_at,
                  hu.full_name AS host_name,
                  (SELECT COUNT(*) FROM online_meeting_participants p WHERE p.meeting_id = m.id AND p.joined_at IS NOT NULL) AS joined_count,
                  (SELECT COUNT(*) FROM online_meeting_segments s WHERE s.meeting_id = m.id) AS segment_count
           FROM online_meetings m LEFT JOIN users hu ON hu.id = m.host_id
           WHERE m.status = 'BITTI' AND (m.host_id = ? OR m.id IN
                 (SELECT meeting_id FROM online_meeting_participants WHERE user_id = ?))
           ORDER BY COALESCE(m.ended_at, m.created_at) DESC LIMIT 60''', (user['id'], user['id'])))
    for m in rows:
        m['is_host'] = m['host_id'] == user['id']
        m['people'] = db.rows(conn.execute(
            '''SELECT p.name, u.photo FROM online_meeting_participants p LEFT JOIN users u ON u.id = p.user_id
               WHERE p.meeting_id = ? ORDER BY (p.joined_at IS NULL), p.role DESC, p.id LIMIT 5''', (m['id'],)))
    return rows


@router.get('')
def my_meetings(user=Depends(auth.current_user), conn=db.DB):
    rows = db.rows(conn.execute(
        '''SELECT m.*, (SELECT COUNT(*) FROM online_meeting_participants p WHERE p.meeting_id = m.id) AS participant_count,
                  hu.full_name AS host_name
           FROM online_meetings m LEFT JOIN users hu ON hu.id = m.host_id
           WHERE m.status != 'BITTI' AND (m.host_id = ? OR m.id IN
                 (SELECT meeting_id FROM online_meeting_participants WHERE user_id = ?))
           ORDER BY m.created_at DESC LIMIT 100''', (user['id'], user['id'])))
    for m in rows:
        m['is_host'] = m['host_id'] == user['id']
        m['link'] = _public_url(m['code'])
        m['invite_text'] = invite_text(m)
        m['people'] = db.rows(conn.execute(   # avatar yığını için ilk 5 katılımcı
            '''SELECT p.name, u.photo FROM online_meeting_participants p LEFT JOIN users u ON u.id = p.user_id
               WHERE p.meeting_id = ? ORDER BY p.role DESC, p.id LIMIT 5''', (m['id'],)))
    return rows


@router.get('/{mid}')
def meeting_detail(mid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _meeting(conn, mid)
    if not m:
        raise HTTPException(404, 'Toplantı bulunamadı')
    is_host = m['host_id'] == user['id']
    if not is_host and not conn.execute('SELECT 1 FROM online_meeting_participants WHERE meeting_id = ? AND user_id = ?', (mid, user['id'])).fetchone():
        raise HTTPException(403, 'Bu toplantıya katılımcı değilsiniz')
    m['is_host'] = is_host
    m['link'] = _public_url(m['code'])
    m['invite_text'] = invite_text(m)
    m['participants'] = _participants(conn, mid)
    m['live_count'] = len(LIVE.get(mid, {}))
    return m


@router.get('/public/{code}')
def public_info(code: str, conn=db.DB):
    """Dış katılımcı giriş ekranı için temel bilgi (oturum gerektirmez)."""
    from .. import config
    from .system import brand_logo_url
    m = db.row(conn.execute('SELECT title, status, waiting_room, scheduled_at, duration_min FROM online_meetings WHERE code = ?', (code,)))
    if not m or m['status'] == 'BITTI':
        raise HTTPException(404, 'Toplantı bulunamadı veya sona erdi')
    return {'title': m['title'], 'status': m['status'], 'waiting_room': bool(m['waiting_room']), 'when': when_lines(m['scheduled_at'], m['duration_min']),
            'company': config.COMPANY_NAME, 'logo_url': brand_logo_url(conn) or '/static/img/logo.png'}


class GuestIn(BaseModel):
    name: str


@router.post('/guest/{code}')
def guest_join(code: str, body: GuestIn, conn=db.DB):
    """Dış katılımcı: ad verir, erişim jetonu + toplantı kimliği alır (oturum gerektirmez)."""
    m = db.row(conn.execute("SELECT id, status FROM online_meetings WHERE code = ?", (code,)))
    if not m or m['status'] == 'BITTI':
        raise HTTPException(404, 'Toplantı bulunamadı veya sona erdi')
    name = (body.name or '').strip()[:120] or 'Misafir'
    tok = secrets.token_urlsafe(18)
    pid = conn.execute('''INSERT INTO online_meeting_participants (meeting_id, name, is_external, token, created_at)
                          VALUES (?,?,1,?,?)''', (m['id'], name, tok, db.now())).lastrowid
    return {'meeting_id': m['id'], 'token': tok, 'name': name, 'pid': pid}


@router.post('/join/{code}')
def join_by_code(code: str, user=Depends(auth.current_user), conn=db.DB):
    """Şirket içi kullanıcı davet koduyla katılır (katılımcı değilse eklenir)."""
    m = db.row(conn.execute("SELECT id, status FROM online_meetings WHERE code = ?", (code,)))
    if not m or m['status'] == 'BITTI':
        raise HTTPException(404, 'Toplantı bulunamadı veya sona erdi')
    if not conn.execute('SELECT 1 FROM online_meeting_participants WHERE meeting_id = ? AND user_id = ?', (m['id'], user['id'])).fetchone():
        conn.execute('INSERT INTO online_meeting_participants (meeting_id, user_id, name, created_at) VALUES (?,?,?,?)',
                     (m['id'], user['id'], user['full_name'], db.now()))
    return {'meeting_id': m['id']}


# ---------- WebSocket sinyalleşme ----------
async def _send(ws, msg):
    try:
        await ws.send_text(json.dumps(msg))
    except Exception:
        pass


async def _broadcast(mid, msg, exclude=None, where=LIVE):
    for cid, p in list(where.get(mid, {}).items()):
        if cid != exclude:
            await _send(p['ws'], msg)


_HAND_SEQ = 0   # el kaldırma sırası (artan sayaç; sıralamayı belirler)


def _roster(mid):
    return [{'cid': cid, **{k: p['info'][k] for k in ('pid', 'name', 'photo', 'user_id', 'role', 'hand', 'hand_seq', 'muted', 'cam', 'sharing')}}
            for cid, p in LIVE.get(mid, {}).items()]


def _waiting_list(mid):
    return [{'cid': cid, 'name': p['info']['name'], 'is_external': p['info']['is_external']} for cid, p in WAIT.get(mid, {}).items()]


async def _notify_hosts(mid, msg):
    for cid, p in list(LIVE.get(mid, {}).items()):
        if p['info']['role'] == 'host':
            await _send(p['ws'], msg)


def _identify(conn, ws, mid, token):
    """WS kimliği: içerik için çerez, dış için token. (participant_row | None)."""
    if token:
        return db.row(conn.execute('SELECT * FROM online_meeting_participants WHERE meeting_id = ? AND token = ?', (mid, token)))
    user = auth.user_by_token(conn, ws.cookies.get(auth.COOKIE))
    if not user:
        return None
    p = db.row(conn.execute('SELECT * FROM online_meeting_participants WHERE meeting_id = ? AND user_id = ?', (mid, user['id'])))
    if not p:   # katılımcı değilse ekle (koda sahip içerik kullanıcı)
        pid = conn.execute('INSERT INTO online_meeting_participants (meeting_id, user_id, name, created_at) VALUES (?,?,?,?)',
                           (mid, user['id'], user['full_name'], db.now())).lastrowid
        p = db.row(conn.execute('SELECT * FROM online_meeting_participants WHERE id = ?', (pid,)))
    p['photo_row'] = db.row(conn.execute('SELECT photo FROM users WHERE id = ?', (user['id'],))) if p['user_id'] else None
    return p


@ws_router.websocket('/ws/meet')
async def ws_meet(ws: WebSocket, mid: int, token: str = None):
    await ws.accept()

    def load():
        with db.connect() as conn:
            m = _meeting(conn, mid)
            if not m or m['status'] == 'BITTI':
                return 'Toplantı yok veya bitti', None, None, None
            p = _identify(conn, ws, mid, token)
            if not p:
                return 'Yetki yok', None, None, None
            r = conn.execute('SELECT photo FROM users WHERE id = ?', (p['user_id'],)).fetchone() if p['user_id'] else None
            return None, m, p, (r[0] if r else None)
    err, m, p, photo = await _db(load)
    if err:
        await _send(ws, {'t': 'error', 'error': err}); await ws.close(); return
    cid = secrets.token_hex(8)
    is_host = p['role'] == 'host' or m['host_id'] == p['user_id']
    info = {'pid': p['id'], 'name': p['name'], 'photo': photo, 'user_id': p['user_id'],
            'is_external': bool(p['is_external']), 'role': 'host' if is_host else 'uye',
            'hand': False, 'hand_seq': 0, 'muted': False, 'cam': False, 'sharing': False}
    entry = {'ws': ws, 'info': info}

    async def go_live():
        t = _autoend.pop(mid, None)   # biri (geri) geldi: otomatik bitirme iptal
        if t and not t.done():
            t.cancel()
        LIVE.setdefault(mid, {})[cid] = entry
        await _db(_sql, 'UPDATE online_meeting_participants SET state = ?, joined_at = COALESCE(joined_at, ?) WHERE id = ?',
                  ('KABUL', db.now(), p['id']))
        # yeni gelene mevcut canlı akran listesi; mevcutlara yeni akran (mevcutlar offer başlatır)
        me = next((r for r in _roster(mid) if r['cid'] == cid), None)
        await _send(ws, {'t': 'joined', 'self': cid, 'pid': info['pid'], 'meeting': _mpay(mid, m),
                         'peers': [r for r in _roster(mid) if r['cid'] != cid], 'is_host': is_host})
        await _broadcast(mid, {'t': 'peer_join', 'peer': me}, exclude=cid)
        await _broadcast(mid, {'t': 'chat_sys', 'text': f"{info['name']} katıldı"}, exclude=cid)

    async def go_wait(reason):
        WAIT.setdefault(mid, {})[cid] = entry
        await _send(ws, {'t': 'waiting', 'reason': reason, 'title': m['title']})
        if reason == 'admit':
            await _notify_hosts(mid, {'t': 'wait_list', 'list': _waiting_list(mid)})

    try:
        started = m['status'] == 'DEVAM'
        if is_host:
            if not started:
                await _db(_sql, "UPDATE online_meetings SET status='DEVAM', started_at=COALESCE(started_at,?) WHERE id=?", (db.now(), mid))
                m['status'] = 'DEVAM'; m['started_at'] = m.get('started_at') or db.now(); started = True
            await go_live()
            # host gelince bekleyen 'not_started' olanları değerlendir
            await _promote_waiters(mid, m)
        elif not started:
            await go_wait('not_started')
        elif m['waiting_room'] and not is_host:
            await go_wait('admit')
        else:
            await go_live()

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            await _on_msg(mid, cid, info, msg, m)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        LIVE.get(mid, {}).pop(cid, None)
        WAIT.get(mid, {}).pop(cid, None)
        try:
            await _db(_sql, 'UPDATE online_meeting_participants SET left_at = ? WHERE id = ?', (db.now(), p['id']))
        except Exception:
            pass
        await _broadcast(mid, {'t': 'peer_left', 'cid': cid})
        await _broadcast(mid, {'t': 'chat_sys', 'text': f"{info['name']} ayrıldı"})
        await _notify_hosts(mid, {'t': 'wait_list', 'list': _waiting_list(mid)})
        if not LIVE.get(mid) and not WAIT.get(mid):   # son kişi de çıktı → kısa bekleme sonrası toplantı biter
            _schedule_autoend(mid)


async def _promote_waiters(mid, m):
    """Toplantı başlayınca bekleyenleri değerlendirir: bekleme odası kapalıysa canlıya alır, açıksa kabule düşürür."""
    for cid, p in list(WAIT.get(mid, {}).items()):
        if m['waiting_room'] and p['info']['role'] != 'host':
            await _send(p['ws'], {'t': 'waiting', 'reason': 'admit', 'title': m['title']})
        else:
            WAIT.get(mid, {}).pop(cid, None)
            LIVE.setdefault(mid, {})[cid] = p
            await _send(p['ws'], {'t': 'joined', 'self': cid, 'pid': p['info']['pid'], 'meeting': _mpay(mid, m),
                                  'peers': [r for r in _roster(mid) if r['cid'] != cid], 'is_host': False})
            await _broadcast(mid, {'t': 'peer_join', 'peer': next((r for r in _roster(mid) if r['cid'] == cid), None)}, exclude=cid)
    await _notify_hosts(mid, {'t': 'wait_list', 'list': _waiting_list(mid)})


async def _on_msg(mid, cid, info, msg, m):
    t = msg.get('t')
    live = LIVE.get(mid, {})
    if t == 'ping':
        return
    if t == 'signal':
        to = msg.get('to')
        if to in live:
            await _send(live[to]['ws'], {'t': 'signal', 'from': cid, 'data': msg.get('data')})
    elif t == 'chat':
        text = (msg.get('text') or '').strip()[:2000]
        if text:
            await _broadcast(mid, {'t': 'chat', 'from': cid, 'name': info['name'], 'text': text})
    elif t == 'dm':   # kişiye özel mesaj (yalnızca hedef katılımcıya)
        to = msg.get('to'); text = (msg.get('text') or '').strip()[:2000]
        if to in live and text:
            await _send(live[to]['ws'], {'t': 'dm', 'from': cid, 'name': info['name'], 'text': text})
    elif t == 'state':   # mute/cam/screen/hand değişimi
        for k in ('muted', 'cam', 'sharing', 'hand'):
            if k in msg:
                info[k] = bool(msg[k])
        if 'hand' in msg:   # el kaldırınca sıra numarası ver, indirince sıfırla
            global _HAND_SEQ
            if info['hand']:
                _HAND_SEQ += 1; info['hand_seq'] = _HAND_SEQ
            else:
                info['hand_seq'] = 0
        await _broadcast(mid, {'t': 'peer_state', 'cid': cid, 'muted': info['muted'], 'cam': info['cam'],
                               'sharing': info['sharing'], 'hand': info['hand'], 'hand_seq': info['hand_seq']})
    elif t in ('admit', 'deny', 'mute_peer', 'kick', 'end') and info['role'] == 'host':
        target = msg.get('cid')
        if t == 'admit' and target in WAIT.get(mid, {}):
            p = WAIT[mid].pop(target)
            LIVE.setdefault(mid, {})[target] = p
            await _send(p['ws'], {'t': 'joined', 'self': target, 'pid': p['info']['pid'], 'meeting': _mpay(mid, m),
                                  'peers': [r for r in _roster(mid) if r['cid'] != target], 'is_host': False})
            await _broadcast(mid, {'t': 'peer_join', 'peer': next((r for r in _roster(mid) if r['cid'] == target), None)}, exclude=target)
            await _notify_hosts(mid, {'t': 'wait_list', 'list': _waiting_list(mid)})
        elif t == 'deny' and target in WAIT.get(mid, {}):
            p = WAIT[mid].pop(target)
            await _send(p['ws'], {'t': 'denied'})
            await _notify_hosts(mid, {'t': 'wait_list', 'list': _waiting_list(mid)})
        elif t == 'mute_peer' and target in live:
            await _send(live[target]['ws'], {'t': 'force_mute'})
        elif t == 'kick' and target in live:
            await _send(live[target]['ws'], {'t': 'kicked'})
        elif t == 'end':
            await _end_meeting(mid)


async def _end_meeting(mid):
    def q():
        with db.connect() as c:
            c.execute("UPDATE online_meetings SET status='BITTI', ended_at=? WHERE id=? AND status!='BITTI'", (db.now(), mid))
            return c.execute('SELECT record FROM online_meetings WHERE id = ?', (mid,)).fetchone()
    rec = await _db(q)
    await _broadcast(mid, {'t': 'ended'})
    await _broadcast(mid, {'t': 'ended'}, where=WAIT)
    LIVE.pop(mid, None); WAIT.pop(mid, None)
    if rec and rec[0]:
        from .. import meet_audio
        meet_audio.schedule(mid, delay=4.0)


@router.post('/{mid}/end')
async def end_meeting_rest(mid: int, user=Depends(auth.current_user)):
    """Toplantıyı listeden (oda dışından) bitirir. Odadaki herkese de 'bitti' yayınlanır ve odaları kapanır."""
    def check():
        with db.connect() as conn:
            return _is_host(conn, mid, user)
    if not await _db(check):
        raise HTTPException(403, 'Yalnızca toplantı sahibi bitirebilir')
    await _end_meeting(mid)
    return {'ok': True}


    return {'ok': True}


# ---------- Kayıt ----------
@router.post('/{mid}/recording')
async def upload_recording(mid: int, request: Request, file: UploadFile = File(...), pid: int = Form(...), token: str = Form(None), conn=db.DB):
    """Katılımcı kendi mikrofon kaydını yükler (içerik: çerez, dış: token). Katılımcı doğrulanır."""
    p = db.row(conn.execute('SELECT * FROM online_meeting_participants WHERE id = ? AND meeting_id = ?', (pid, mid)))
    if not p:
        raise HTTPException(404, 'Katılımcı yok')
    if p['is_external']:
        if not token or token != p['token']:
            raise HTTPException(403, 'Yetki yok')
    else:
        u = auth.user_by_token(conn, request.cookies.get(auth.COOKIE))
        if not u or u['id'] != p['user_id']:
            raise HTTPException(403, 'Yetki yok')
    path = await save_upload('calls', file)
    conn.execute('''INSERT INTO online_meeting_audio (meeting_id, user_id, speaker_name, file, started_at)
                    VALUES (?,?,?,?,?)''', (mid, p['user_id'], p['name'], path, db.now()))
    from .. import meet_audio
    meet_audio.schedule(mid)
    return {'ok': True}


# ---------- Dosya kutusu ----------
@router.post('/{mid}/files')
async def upload_meet_file(mid: int, request: Request, file: UploadFile = File(...), pid: int = Form(...), token: str = Form(None)):
    """Katılımcı toplantı dosya kutusuna dosya yükler (içerik: çerez, dış: token); herkese canlı duyurulur."""
    cookie = request.cookies.get(auth.COOKIE)

    def verify():
        with db.connect() as conn:
            p = db.row(conn.execute('SELECT * FROM online_meeting_participants WHERE id = ? AND meeting_id = ?', (pid, mid)))
            m = _meeting(conn, mid)
            if not p or not m or m['status'] == 'BITTI':
                return '404', None
            if p['is_external']:
                if not token or token != p['token']:
                    return '403', None
            else:
                u = auth.user_by_token(conn, cookie)
                if not u or u['id'] != p['user_id']:
                    return '403', None
            return None, p
    err, p = await _db(verify)
    if err == '403':
        raise HTTPException(403, 'Yetki yok')
    if err == '404':
        raise HTTPException(404, 'Katılımcı yok ya da toplantı bitti')
    name = (file.filename or 'dosya')[:200]
    path = await save_upload('calls', file)

    def ins():
        with db.connect() as conn:
            return conn.execute('''INSERT INTO online_meeting_files (meeting_id, uploader_pid, uploader_name, file_path, file_name, created_at)
                                   VALUES (?,?,?,?,?,?)''', (mid, p['id'], p['name'], path, name, db.now())).lastrowid
    fid = await _db(ins)
    item = {'id': fid, 'name': name, 'by': p['name'], 'at': db.now()}
    await _broadcast(mid, {'t': 'file', 'file': item})
    return {'ok': True, 'file': item}


@router.get('/{mid}/files')
def list_meet_files(mid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _meeting(conn, mid)
    if not m or (m['host_id'] != user['id'] and not conn.execute('SELECT 1 FROM online_meeting_participants WHERE meeting_id=? AND user_id=?', (mid, user['id'])).fetchone()):
        raise HTTPException(403, 'Yetki yok')
    return db.rows(conn.execute('SELECT id, file_name AS name, uploader_name AS by, created_at AS at FROM online_meeting_files WHERE meeting_id = ? ORDER BY id', (mid,)))


FILE_GRACE_MIN = 15   # toplantı bittikten sonra dosyalar bu kadar dakika daha indirilebilir


@router.get('/{mid}/file')
def download_meet_file(mid: int, fid: int, request: Request, token: str = None, conn=db.DB):
    from datetime import datetime, timedelta
    from fastapi.responses import FileResponse
    from .. import config
    f = db.row(conn.execute('SELECT * FROM online_meeting_files WHERE id = ? AND meeting_id = ?', (fid, mid)))
    if not f:
        raise HTTPException(404, 'Dosya yok')
    m = _meeting(conn, mid)
    # Toplantı bittiyse yalnızca 15 dakika daha indirilebilir
    if m and m['status'] == 'BITTI' and m.get('ended_at'):
        try:
            if datetime.fromisoformat(m['ended_at']) < datetime.now() - timedelta(minutes=FILE_GRACE_MIN):
                raise HTTPException(410, 'Dosya indirme süresi doldu (toplantı bitti)')
        except ValueError:
            pass
    u = auth.user_by_token(conn, request.cookies.get(auth.COOKIE))
    ok = bool(u and m and (u['id'] == m['host_id'] or conn.execute('SELECT 1 FROM online_meeting_participants WHERE meeting_id=? AND user_id=?', (mid, u['id'])).fetchone()))
    if not ok and token:   # link üzerinden (dış katılımcı / davet token'ı)
        ok = bool(conn.execute('SELECT 1 FROM online_meeting_participants WHERE meeting_id=? AND token=?', (mid, token)).fetchone())
    if not ok:
        raise HTTPException(403, 'Yetki yok')
    path = config.UPLOAD_DIR / f['file_path']
    if not path.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return FileResponse(path, filename=f['file_name'])


@router.get('/{mid}/detail')
def meeting_record_detail(mid: int, user=Depends(auth.current_user), conn=db.DB):
    m = _meeting(conn, mid)
    if not m:
        raise HTTPException(404, 'Toplantı yok')
    if m['host_id'] != user['id'] and not conn.execute('SELECT 1 FROM online_meeting_participants WHERE meeting_id=? AND user_id=?', (mid, user['id'])).fetchone():
        raise HTTPException(403, 'Yetki yok')
    m['segments'] = db.rows(conn.execute(
        '''SELECT s.audio_id, s.t0, s.text, sp.label AS speaker_label, sp.user_id AS speaker_user
           FROM online_meeting_segments s LEFT JOIN online_meeting_speakers sp ON sp.id = s.speaker_id
           WHERE s.meeting_id = ? ORDER BY s.t0''', (mid,)))
    m['has_audio'] = bool(conn.execute('SELECT 1 FROM online_meeting_audio WHERE meeting_id = ? LIMIT 1', (mid,)).fetchone())
    return m


@router.get('/{mid}/audio')
def meeting_audio_file(mid: int, aid: int = None, user=Depends(auth.current_user), conn=db.DB):
    from fastapi.responses import FileResponse
    from .. import config
    m = _meeting(conn, mid)
    if not m or (m['host_id'] != user['id'] and not conn.execute('SELECT 1 FROM online_meeting_participants WHERE meeting_id=? AND user_id=?', (mid, user['id'])).fetchone()):
        raise HTTPException(403, 'Yetki yok')
    a = (db.row(conn.execute('SELECT file, wav FROM online_meeting_audio WHERE meeting_id=? AND id=?', (mid, aid))) if aid
         else db.row(conn.execute('SELECT file, wav FROM online_meeting_audio WHERE meeting_id=? ORDER BY id LIMIT 1', (mid,))))
    if not a:
        raise HTTPException(404, 'Kayıt yok')
    rel = a['wav'] if a['wav'] and (config.UPLOAD_DIR / a['wav']).is_file() else a['file']
    path = config.UPLOAD_DIR / rel
    if not path.is_file():
        raise HTTPException(404, 'Ses dosyası yok')
    ext = path.suffix.lower()
    mt = {'.webm': 'audio/webm', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4', '.wav': 'audio/wav'}.get(ext, 'application/octet-stream')
    return FileResponse(path, media_type=mt)
