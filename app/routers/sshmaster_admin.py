"""Merkez › Mastertool: Mastertool hesap servisi (SSH Master + FTP Masters; mastertool.download) kullanıcı, uygulama lisansı ve sürüm
yönetimi; Mastertool kullanıcılarının destek talepleri (Hesabım › Destek) için iç köprü.

SSH Master hesap servisi (central/sshmaster_server, systemd hepgo-sshmasters) aynı sunucuda 127.0.0.1:8095'te çalışır; Merkez onu
Veilox'taki gibi İÇ anahtarla (X-Central-Secret = CAYMAZ_CENTRAL_API_SECRET, servis tarafında VEILOX_CENTRAL_API_SECRET) çağırır.
Yalnız merkez modunda (CAYMAZ_FEDERATION_CENTRAL=1) ve 'sshmaster' modül yetkisiyle. Kullanıcıların şifreleri/kütüphaneleri Merkez'e
gelmez (sunucu da okuyamaz; uçtan uca şifreli)."""
import hmac
import os
import threading

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from .. import auth, config, db, support

router = APIRouter(prefix='/api/central/sshm')
fed = APIRouter(prefix='/api/federation/mastertool')
APPS = {'sm': 'SSH Master', 'fm': 'FTP Masters', 'sq': 'SQL Master', 'np': 'Notepad Master', 'cv': 'Convert Master'}
sshm_user = auth.require_module('sshmaster')
SSHM_URL = os.environ.get('CAYMAZ_SSHM_URL', 'http://127.0.0.1:8095').rstrip('/')


def _sm(method, path, json_body=None, files=None, data=None, timeout=30):
    if not config.FEDERATION_CENTRAL:
        raise HTTPException(404, 'Bulunamadı')
    if not config.CENTRAL_API_SECRET:
        raise HTTPException(503, 'Merkez iç anahtarı tanımlı değil')
    try:
        with httpx.Client(base_url=SSHM_URL, timeout=timeout) as c:
            r = c.request(method, path, json=json_body, files=files, data=data, headers={'X-Central-Secret': config.CENTRAL_API_SECRET})
    except httpx.HTTPError:
        raise HTTPException(503, 'SSH Master servisine ulaşılamıyor')
    if r.status_code >= 400:
        try:
            msg = r.json().get('message') or r.json().get('detail')
        except ValueError:
            msg = None
        raise HTTPException(r.status_code, msg or 'SSH Master servisi hatası')
    return r.json()


@router.get('/users')
def users(user=Depends(sshm_user)):
    return _sm('GET', '/api/sm/admin/users')


@router.get('/users/{uid}')
def user_detail(uid: int, user=Depends(sshm_user)):
    return _sm('GET', f'/api/sm/admin/users/{uid}')


@router.put('/users/{uid}')
async def user_update(uid: int, request: Request, user=Depends(sshm_user), conn=db.DB):
    b = await request.json()
    body = {k: b[k] for k in ('status', 'name', 'note', 'apps') if k in b}
    r = _sm('PUT', f'/api/sm/admin/users/{uid}', body)
    db.audit(conn, user['id'], 'Merkez: Mastertool kullanıcısını düzenledi', 'sshm_user', uid, ', '.join(f'{k}={v}' for k, v in body.items())[:300])
    return r


@router.delete('/users/{uid}')
def user_delete(uid: int, user=Depends(sshm_user), conn=db.DB):
    r = _sm('DELETE', f'/api/sm/admin/users/{uid}')
    db.audit(conn, user['id'], 'Merkez: Mastertool kullanıcısını sildi', 'sshm_user', uid)
    return r


@router.post('/users/{uid}/reset-mail')
def user_reset_mail(uid: int, user=Depends(sshm_user), conn=db.DB):
    r = _sm('POST', f'/api/sm/admin/users/{uid}/reset-mail')
    db.audit(conn, user['id'], 'Merkez: Mastertool e-postası gönderdi', 'sshm_user', uid, r.get('sent'))
    return r


@router.get('/releases')
def releases(app: str = '', user=Depends(sshm_user)):
    return _sm('GET', f'/api/sm/admin/releases?app={app}' if app in APPS else '/api/sm/admin/releases')


@router.post('/releases')
def release_upload(version: str = Form(...), notes: str = Form(''), setup: UploadFile = File(...), portable: UploadFile = File(None),
                   app: str = Form('sm'), user=Depends(sshm_user), conn=db.DB):
    if app not in APPS:
        raise HTTPException(400, 'Uygulama geçersiz')
    files = {'setup': (setup.filename or 'setup.exe', setup.file, 'application/octet-stream')}
    if portable is not None and portable.filename:
        files['portable'] = (portable.filename, portable.file, 'application/octet-stream')
    r = _sm('POST', f'/api/{app}/releases', files=files, data={'version': version, 'notes': notes}, timeout=600)
    db.audit(conn, user['id'], f'Merkez: {APPS[app]} sürümü yükledi', 'sshm_release', r.get('version'), r.get('sha256'))
    return r


@router.delete('/releases/{rid}')
def release_delete(rid: int, user=Depends(sshm_user), conn=db.DB):
    r = _sm('DELETE', f'/api/sm/admin/releases/{rid}')
    db.audit(conn, user['id'], 'Merkez: Mastertool sürümünü sildi', 'sshm_release', rid)
    return r


# ======================= MASTERWORLD canlı veri kaynakları (docs/masterworld.md §3.2) =======================
# Hesap servisinin /api/sm/admin/mw/* uçlarına iç anahtarla vekil; her değişiklik audit'e yazılır (api_key DEĞERİ asla yazılmaz).
MW_SRC_FIELDS = ('slug', 'category', 'kind', 'name', 'data_desc', 'endpoint', 'protocol', 'auth', 'push_pull', 'scale', 'license', 'note', 'adapter',
                 'params', 'api_key', 'key_required', 'noncommercial', 'attribution_required', 'attribution', 'attribution_url', 'rate_per_min',
                 'ttl_s', 'enabled', 'default_on', 'sort')
MW_PT_FIELDS = ('name', 'lat', 'lon', 'media_type', 'media_url', 'props', 'enabled')


def _mw_body(b, fields):
    if not isinstance(b, dict):
        raise HTTPException(422, 'İstek gövdesi geçersiz')
    return {k: b[k] for k in fields if k in b}


def _mw_detail(body):
    """Audit ayrıntısı: alan adları ve değerleri; anahtar yalnız 'api_key=değişti/silindi' olarak."""
    out = []
    for k, v in body.items():
        if k == 'api_key':
            out.append('api_key=' + ('silindi' if v == '' else 'değişti') if v is not None else '')
        elif k == 'params':
            out.append('params=…')
        else:
            out.append(f'{k}={v}')
    return ', '.join(x for x in out if x)[:300]


@router.get('/mw/sources')
def mw_sources(user=Depends(sshm_user)):
    return _sm('GET', '/api/sm/admin/mw/sources')


@router.post('/mw/sources')
async def mw_source_create(request: Request, user=Depends(sshm_user), conn=db.DB):
    body = _mw_body(await request.json(), MW_SRC_FIELDS)
    r = _sm('POST', '/api/sm/admin/mw/sources', body)
    db.audit(conn, user['id'], 'Merkez: MASTERWORLD kaynağı ekledi', 'mw_source', r.get('id'), _mw_detail(body))
    return r


@router.put('/mw/sources/{sid}')
async def mw_source_update(sid: int, request: Request, user=Depends(sshm_user), conn=db.DB):
    body = _mw_body(await request.json(), MW_SRC_FIELDS)
    r = _sm('PUT', f'/api/sm/admin/mw/sources/{sid}', body)
    db.audit(conn, user['id'], 'Merkez: MASTERWORLD kaynağını düzenledi', 'mw_source', sid, _mw_detail(body))
    return r


@router.delete('/mw/sources/{sid}')
def mw_source_delete(sid: int, user=Depends(sshm_user), conn=db.DB):
    r = _sm('DELETE', f'/api/sm/admin/mw/sources/{sid}')
    db.audit(conn, user['id'], 'Merkez: MASTERWORLD kaynağını sildi', 'mw_source', sid, r.get('slug'))
    return r


@router.post('/mw/import')
def mw_import(file: UploadFile = File(...), user=Depends(sshm_user), conn=db.DB):
    data = file.file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, 'Dosya 5 MB sınırını aşıyor')
    r = _sm('POST', '/api/sm/admin/mw/import', files={'file': (file.filename or 'kaynaklar.xlsx', data,
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}, timeout=120)
    db.audit(conn, user['id'], "Merkez: MASTERWORLD kaynaklarını Excel'den içe aktardı", 'mw_source', None,
             f"{(file.filename or '')[:80]}: +{r.get('added')} ~{r.get('updated')} ={r.get('unchanged')} atlanan {len(r.get('skipped') or [])}")
    return r


@router.get('/mw/sources/{sid}/points')
def mw_points(sid: int, user=Depends(sshm_user)):
    return _sm('GET', f'/api/sm/admin/mw/sources/{sid}/points')


@router.post('/mw/sources/{sid}/points')
async def mw_point_create(sid: int, request: Request, user=Depends(sshm_user), conn=db.DB):
    body = _mw_body(await request.json(), MW_PT_FIELDS)
    r = _sm('POST', f'/api/sm/admin/mw/sources/{sid}/points', body)
    db.audit(conn, user['id'], 'Merkez: MASTERWORLD noktası ekledi', 'mw_point', r.get('id'), f"kaynak {sid}: {body.get('name')}"[:300])
    return r


@router.put('/mw/points/{pid}')
async def mw_point_update(pid: int, request: Request, user=Depends(sshm_user), conn=db.DB):
    body = _mw_body(await request.json(), MW_PT_FIELDS)
    r = _sm('PUT', f'/api/sm/admin/mw/points/{pid}', body)
    db.audit(conn, user['id'], 'Merkez: MASTERWORLD noktasını düzenledi', 'mw_point', pid, _mw_detail(body))
    return r


@router.delete('/mw/points/{pid}')
def mw_point_delete(pid: int, user=Depends(sshm_user), conn=db.DB):
    r = _sm('DELETE', f'/api/sm/admin/mw/points/{pid}')
    db.audit(conn, user['id'], 'Merkez: MASTERWORLD noktasını sildi', 'mw_point', pid)
    return r


# ======================= Mastertool destek köprüsü =======================
# Mastertool hesap servisi, kullanıcının Hesabım › Destek isteklerini İÇ anahtarla buraya iletir (kullanıcı Merkez'i hiç görmez).
# Talepler mevcut talep ekranına slug='mastertool', kanal 'mastertool', etiket = uygulama adıyla düşer; kullanıcı yalnız kendi
# e-postasıyla açılmış talepleri görür. İç notlar ve atanan kişi bilgisi dışarı verilmez.
SLUG = 'mastertool'
TICKET_APPS = {'sm': 'SSH Master', 'fm': 'FTP Masters', 'sq': 'SQL Master', 'np': 'Notepad Master', 'cv': 'Convert Master', 'mt': 'Hesap / genel',
               'sv': 'SIMUMAV', 'mw': 'MASTERWORLD'}   # mw: masterworld.app (henüz talep köprüsü yok; Hesabım › Destek'ten açılabilir) · sv: simumav.com oyunu — talep SIMUMAV sunucusu → hesap servisi (/api/sv/tickets, X-Simumav-Secret) → buraya (docs/simumav.md §9)
_APP_OF = {v: k for k, v in TICKET_APPS.items()}


def _mt(request: Request):
    if not config.FEDERATION_CENTRAL:
        raise HTTPException(404, 'Bulunamadı')
    sec = request.headers.get('x-central-secret') or ''
    if not config.CENTRAL_API_SECRET or not hmac.compare_digest(sec.encode(), config.CENTRAL_API_SECRET.encode()):
        raise HTTPException(403, 'Yetkisiz')


def _email(v):
    e = str(v or '').strip().lower()
    if '@' not in e or len(e) > 160:
        raise HTTPException(400, 'E-posta geçersiz')
    return e


def _own(conn, tid, email):
    t = db.row(conn.execute('SELECT * FROM tickets WHERE id = ? AND slug = ? AND lower(opened_by_email) = ?', (tid, SLUG, email)))
    if not t:
        raise HTTPException(404, 'Talep bulunamadı')
    return t


def _view(conn, t):
    msgs = [{k: m[k] for k in ('id', 'author_kind', 'author_name', 'body', 'created_at')}
            for m in support.ticket_messages(conn, t['id'], internal=False)]
    return {'id': t['id'], 'code': t['code'], 'subject': t['subject'], 'status': t['status'], 'category': t['category'],
            'app': _APP_OF.get(t.get('tags') or '', 'mt'), 'created_at': t['created_at'], 'updated_at': t['updated_at'], 'messages': msgs}


@fed.get('/tickets')
def mt_tickets(request: Request, email: str = '', conn=db.DB):
    _mt(request)
    rows = db.rows(conn.execute('''SELECT id, code, subject, status, category, tags, company_unread, created_at, updated_at FROM tickets
                                   WHERE slug = ? AND lower(opened_by_email) = ? ORDER BY updated_at DESC LIMIT 200''', (SLUG, _email(email))))
    return [{'id': r['id'], 'code': r['code'], 'subject': r['subject'], 'status': r['status'], 'category': r['category'],
             'app': _APP_OF.get(r['tags'] or '', 'mt'), 'unread': r['company_unread'], 'created_at': r['created_at'],
             'updated_at': r['updated_at']} for r in rows]


@fed.post('/tickets')
async def mt_ticket_create(request: Request, conn=db.DB):
    _mt(request)
    b = await request.json()
    email, app = _email(b.get('email')), b.get('app') if b.get('app') in TICKET_APPS else 'mt'
    try:
        r = support.create_ticket(conn, SLUG, f'Mastertool · {TICKET_APPS[app]}', str(b.get('subject') or ''), str(b.get('body') or ''),
                                  str(b.get('category') or 'teknik'), 'normal', str(b.get('name') or '')[:120], email, channel='mastertool')
    except support.SupportError as e:
        raise HTTPException(400, str(e)) from e
    conn.execute('UPDATE tickets SET tags = ? WHERE id = ?', (TICKET_APPS[app], r['id']))
    conn.commit()
    return r


@fed.get('/tickets/{tid}')
def mt_ticket(tid: int, request: Request, email: str = '', conn=db.DB):
    _mt(request)
    t = _own(conn, tid, _email(email))
    if t['company_unread']:
        conn.execute('UPDATE tickets SET company_unread = 0 WHERE id = ?', (tid,))
        conn.commit()
    return _view(conn, t)


@fed.post('/tickets/{tid}/messages')
async def mt_ticket_reply(tid: int, request: Request, conn=db.DB):
    _mt(request)
    b = await request.json()
    t = _own(conn, tid, _email(b.get('email')))
    try:
        support.company_reply(conn, t, str(b.get('body') or ''), str(b.get('name') or '')[:120])
    except support.SupportError as e:
        raise HTTPException(400, str(e)) from e
    return _view(conn, _own(conn, tid, t['opened_by_email'].lower()))


@fed.post('/tickets/{tid}/close')
async def mt_ticket_close(tid: int, request: Request, conn=db.DB):
    _mt(request)
    b = await request.json()
    t = _own(conn, tid, _email(b.get('email')))
    support.set_status_ticket(conn, t, 'cozuldu', str(b.get('name') or 'Kullanıcı')[:120])
    conn.execute('UPDATE tickets SET company_unread = 0 WHERE id = ?', (tid,))
    conn.commit()
    return _view(conn, _own(conn, tid, t['opened_by_email'].lower()))


def notify_reply(t):
    """Destek ekibi Mastertool talebine (iç not değil) yanıt yazdı → hesap servisi kullanıcıya markalı e-posta gönderir. Arka planda,
    hata sessiz (talep kaydı zaten Hesabım'da görünür)."""
    if not t or t.get('slug') != SLUG or not t.get('opened_by_email') or not config.CENTRAL_API_SECRET:
        return
    payload = {'id': t['id'], 'code': t['code'], 'subject': t['subject'], 'email': t['opened_by_email'], 'app': _APP_OF.get(t.get('tags') or '', 'mt')}

    def run():
        try:
            with httpx.Client(base_url=SSHM_URL, timeout=20) as c:
                c.post('/api/mt/internal/ticket-reply', json=payload, headers={'X-Central-Secret': config.CENTRAL_API_SECRET})
        except httpx.HTTPError:
            pass
    threading.Thread(target=run, daemon=True).start()
