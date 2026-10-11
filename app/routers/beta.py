"""Beta geri bildirim: firma kullanıcısı footer'daki 'Beta' düğmesinden hata/tavsiye/diğer bildirir.

Kayıt yerel (beta_feedback) tutulur ve federasyon varsa merkeze (Veilox) bir DESTEK TALEBİ (ticket, [BETA] başlıklı)
olarak iletilir; merkez Destek Merkezi'nde görülüp cevaplanır, cevap buraya senkronlanır. Federasyon yoksa kayıt
yerelde kalır (master yerelde görür). Her giriş yapmış kullanıcı bildirim gönderir; kendi bildirimlerini görür
(master tümünü görür).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, central_client, config, db

router = APIRouter(prefix='/api/beta')
CATS = ('hata', 'tavsiye', 'diger')
CAT_LBL = {'hata': 'Hata', 'tavsiye': 'Tavsiye', 'diger': 'Diğer'}
CAT_TICKET = {'hata': 'teknik', 'tavsiye': 'oneri', 'diger': 'diger'}   # merkez ticket kategorisi


class FeedbackIn(BaseModel):
    category: str = 'diger'
    message: str
    screenshot: str = ''     # opsiyonel data URI (ekran görüntüsü) — yerelde saklanır
    page: str = ''


def _pub(r):
    r.pop('screenshot', None)
    return r


def _push_central(user, cat, msg):
    """Beta bildirimini merkeze [BETA] destek talebi olarak aç. (remote_id, code) veya (None, None)."""
    if not central_client.enabled():
        return None, None
    data = {'subject': f'[BETA] {CAT_LBL.get(cat, "Diğer")} — {msg[:60]}', 'body': msg,
            'category': CAT_TICKET.get(cat, 'diger'), 'priority': 'dusuk', 'channel': 'beta',
            'company_name': config.COMPANY_NAME, 'name': user.get('full_name') or '', 'email': user.get('email') or ''}
    r = central_client.call('POST', '/tickets', data=data, timeout=30)
    return r.get('id'), r.get('code')


@router.post('/feedback')
def send_feedback(body: FeedbackIn, user=Depends(auth.current_user), conn=db.DB):
    msg = (body.message or '').strip()
    if not msg:
        raise HTTPException(400, 'Lütfen bir mesaj yazın')
    cat = body.category if body.category in CATS else 'diger'
    shot = (body.screenshot or '').strip()[:900000] or None
    fid = conn.execute(
        '''INSERT INTO beta_feedback (user_id, user_name, category, message, screenshot, page, status, created_at)
           VALUES (?,?,?,?,?,?,'NEW',?)''',
        (user['id'], user.get('full_name'), cat, msg[:5000], shot, (body.page or '')[:200], db.now())).lastrowid
    conn.commit()
    db.audit(conn, user['id'], 'Beta geri bildirim', 'beta_feedback', fid, cat)
    try:   # merkeze ilet (federasyon varsa); başarısızlık bildirimi engellemez, yerel kalır
        rid, code = _push_central(user, cat, msg[:5000])
        if rid:
            conn.execute("UPDATE beta_feedback SET status='SENT', remote_id=? WHERE id=?", (rid, fid))
            conn.commit()
    except Exception:   # noqa: BLE001
        pass
    return {'id': fid}


def _sync_replies(conn, rows):
    """SENT bildirimler için merkez ticket'ındaki son destek cevabını çek, yerele işle."""
    if not central_client.enabled():
        return
    for r in rows:
        if r.get('reply') or r['status'] not in ('SENT',) or not r.get('remote_id'):
            continue
        try:
            t = central_client.call('GET', f"/tickets/{r['remote_id']}", timeout=12)
            sup = [m for m in (t.get('messages') or []) if m.get('author_kind') == 'support']
            if sup:
                r['reply'] = sup[-1].get('body'); r['status'] = 'ANSWERED'
                conn.execute("UPDATE beta_feedback SET reply=?, status='ANSWERED', replied_at=? WHERE id=?",
                             (r['reply'], db.now(), r['id']))
        except Exception:   # noqa: BLE001
            pass
    conn.commit()


@router.get('/feedback')
def my_feedback(user=Depends(auth.current_user), conn=db.DB):
    """master/Sistem Yöneticisi tüm firma bildirimlerini, diğerleri yalnız kendi bildirimlerini görür (+merkez cevabı)."""
    is_admin = bool(user.get('master')) or ('Sistem Yöneticisi' in (user.get('roles') or []))
    if is_admin:
        rows = db.rows(conn.execute('SELECT * FROM beta_feedback ORDER BY id DESC LIMIT 300'))
    else:
        rows = db.rows(conn.execute('SELECT * FROM beta_feedback WHERE user_id = ? ORDER BY id DESC LIMIT 100', (user['id'],)))
    try:
        _sync_replies(conn, rows)
    except Exception:   # noqa: BLE001
        pass
    return [_pub(r) for r in rows]
