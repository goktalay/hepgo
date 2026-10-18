"""Firma paneli — Üyeliğim & Destek: merkezle (HEPGO / Veilox) ilişki. Paket ve modüller, aylık ücret, ödeme geçmişi ve
ödeme bildirimi, destek talepleri (dosya ekli; değerlendirme, kapatma), canlı destek sohbeti (ekran paylaşımıyla), üyelik
sözleşmeleri. Veriler merkezdedir; burası federasyon üzerinden okur / yazar (central_client). Merkezin iç notları buraya gelmez."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from .. import auth, central_client, config, db

router = APIRouter(prefix='/api/membership')
member_user = auth.require_module('uyelik')
MAX_FILES, MAX_TOTAL = 5, 25 * 1024 * 1024


async def _form(request: Request):
    """Çok parçalı (dosyalı) ya da JSON gövde → (alanlar, [(ad, tür, bayt)])."""
    if request.headers.get('content-type', '').startswith(('multipart/form-data', 'application/x-www-form-urlencoded')):
        form = await request.form()
        fields, files, total = {}, [], 0
        for k, v in form.multi_items():
            if hasattr(v, 'filename'):
                if v.filename and len(files) < MAX_FILES:
                    data = await v.read()
                    total += len(data)
                    if total > MAX_TOTAL:
                        raise HTTPException(400, 'Ekler toplam 25 MB sınırını aşıyor')
                    files.append((v.filename, data, v.content_type or 'application/octet-stream'))
            else:
                fields[k] = v
        return fields, files
    try:
        return (await request.json()) or {}, []
    except ValueError:
        return {}, []


def _who(user):
    return {'name': user['full_name'], 'email': user['username'] if '@' in (user.get('username') or '') else ''}


@router.get('')
def overview(user=Depends(member_user)):
    return central_client.call('GET', '/membership')


@router.get('/modules')
def modules(user=Depends(member_user), conn=db.DB):
    """Üyelik › "Paketinizdeki Modüller" kutucukları: firmanın tüm modül kataloğu ve her birinin bu kullanıcı için durumu.
    Merkeze gitmez; yerel kurulumun paket kurallarından (CAYMAZ_MODULES, esnaf / dron paketi, Modül Yönetimi'nde kapatılanlar)
    ve kullanıcının rol yetkilerinden türetilir.
      open    paket içinde, kullanıcı açabilir          → tıklanınca modüle gider
      locked  paket içinde, kullanıcının yetkisi yok     → kilit; tıklanmaz
      off     paket içinde, master Modül Yönetimi'nden kapatmış
      missing pakette yok                               → soluk + "Pakette yok"; tıklanınca yükseltme bilgisi"""
    import json

    from .. import modules_tier, rbac
    hidden = {'users', 'orders', 'master', 'mikro', 'uyelik'}   # alt sekme / ayarlardan açılan / bu sayfa
    keys = [n['key'] for n in rbac.catalog() if n['parent'] is None and n['key'] not in hidden]
    titles = {k: t for k, t, _ in rbac.CATALOG}
    try:
        row = conn.execute("SELECT v FROM app_kv WHERE k = 'modules.disabled'").fetchone()
        off = set(json.loads(row[0])) if row and row[0] else set()
    except (ValueError, TypeError):
        off = set()
    esnaf = {'pos', 'sections', 'services', 'reservations', 'waiter'}
    drone_ok = auth.drone_visible(conn)
    mine = {m.split('.')[0] for m in user['modules']}
    out = []
    for k in keys:
        in_pkg = (k in config.MODULES) if config.MODULES is not None else True
        if k in esnaf and not config.ESNAF_PKG:
            in_pkg = False
        if k == 'drone' and not drone_ok:
            in_pkg = False
        if not in_pkg:
            state = 'missing'
        elif k in off and modules_tier.tier(k) not in ('required', 'always'):
            state = 'off'
        elif k in mine:
            state = 'open'
        else:
            state = 'locked'
        out.append({'key': k, 'title': titles.get(k, k), 'state': state, 'tier': modules_tier.tier(k)})
    return {'modules': out, 'in_package': sum(1 for m in out if m['state'] != 'missing')}


@router.get('/support-status')
def support_status(user=Depends(member_user)):
    return central_client.call('GET', '/support/status', timeout=6)


# ---------------- destek talepleri ----------------
@router.get('/tickets')
def tickets(user=Depends(member_user)):
    return central_client.call('GET', '/tickets')


@router.post('/tickets')
async def ticket_create(request: Request, user=Depends(member_user), conn=db.DB):
    f, files = await _form(request)
    data = {'subject': f.get('subject', ''), 'body': f.get('body', ''), 'category': f.get('category', 'teknik'),
            'priority': f.get('priority', 'normal'), 'company_name': config.COMPANY_NAME, **_who(user)}
    r = central_client.call('POST', '/tickets', data=data, files=files, timeout=60)
    db.audit(conn, user['id'], 'Merkeze destek talebi açtı', 'ticket', r.get('code'), str(data['subject'])[:80])
    central_client.forget_unread()
    return r


@router.get('/tickets/{tid}')
def ticket_detail(tid: int, user=Depends(member_user)):
    central_client.forget_unread()
    return central_client.call('GET', f'/tickets/{tid}')


@router.post('/tickets/{tid}/messages')
async def ticket_reply(tid: int, request: Request, user=Depends(member_user)):
    f, files = await _form(request)
    return central_client.call('POST', f'/tickets/{tid}/messages', data={'body': f.get('body', ''), 'name': user['full_name']}, files=files, timeout=60)


class RateIn(BaseModel):
    rating: int
    note: str = ''


@router.post('/tickets/{tid}/rate')
def ticket_rate(tid: int, body: RateIn, user=Depends(member_user)):
    return central_client.call('POST', f'/tickets/{tid}/rate', json=body.model_dump())


@router.post('/tickets/{tid}/close')
def ticket_close(tid: int, user=Depends(member_user), conn=db.DB):
    r = central_client.call('POST', f'/tickets/{tid}/close', json={'name': user['full_name']})
    db.audit(conn, user['id'], 'Destek talebini çözüldü olarak kapattı', 'ticket', tid)
    return r


@router.get('/files/{token}')
def file(token: str, user=Depends(member_user)):
    r = central_client.call('GET', f'/files/{token}', raw=True, timeout=60)
    keep = {k: v for k, v in r.headers.items() if k.lower() in ('content-disposition', 'content-security-policy', 'x-content-type-options')}
    return Response(r.content, media_type=r.headers.get('content-type', 'application/octet-stream'), headers={**keep, 'Cache-Control': 'private, max-age=3600'})


# ---------------- canlı destek ----------------
@router.get('/chats')
def chats(user=Depends(member_user)):
    return central_client.call('GET', '/chats')


class ChatIn(BaseModel):
    topic: str = ''
    category: str = 'teknik'
    message: str


@router.post('/chats')
def chat_start(body: ChatIn, user=Depends(member_user), conn=db.DB):
    r = central_client.call('POST', '/chats', json={**body.model_dump(), 'company_name': config.COMPANY_NAME, **_who(user)})
    db.audit(conn, user['id'], 'Canlı destek başlattı' if not r.get('offline') else 'Canlı destek mesajı bıraktı (talep)', 'chat', r.get('id'))
    return r


@router.get('/chats/{cid}')
def chat(cid: int, after: int = 0, user=Depends(member_user)):
    return central_client.call('GET', f'/chats/{cid}', params={'after': after}, timeout=8)


@router.post('/chats/{cid}/messages')
async def chat_send(cid: int, request: Request, user=Depends(member_user)):
    f, files = await _form(request)
    data = {'body': f.get('body', ''), 'kind': f.get('kind', 'text'), 'name': user['full_name']}
    if files:
        return central_client.call('POST', f'/chats/{cid}/messages', data=data, files=files, timeout=60)
    return central_client.call('POST', f'/chats/{cid}/messages', data=data)


@router.post('/chats/{cid}/typing')
def chat_typing(cid: int, user=Depends(member_user)):
    try:
        return central_client.call('POST', f'/chats/{cid}/typing', timeout=4)
    except HTTPException:
        return {'ok': False}


@router.post('/chats/{cid}/end')
def chat_end(cid: int, user=Depends(member_user)):
    return central_client.call('POST', f'/chats/{cid}/end', json={'name': user['full_name']})


@router.post('/chats/{cid}/rate')
def chat_rate(cid: int, body: RateIn, user=Depends(member_user)):
    return central_client.call('POST', f'/chats/{cid}/rate', json=body.model_dump())


# ---------------- ödeme bildirimi ----------------
class NoticeIn(BaseModel):
    period: str = ''
    amount: float
    paid_at: str = ''
    method: str = 'havale'
    reference: str = ''
    note: str = ''


@router.post('/payment-notices')
def notice(body: NoticeIn, user=Depends(member_user), conn=db.DB):
    r = central_client.call('POST', '/payment-notices', json={**body.model_dump(), **_who(user)})
    db.audit(conn, user['id'], 'Merkeze ödeme bildirdi', 'payment_notice', r.get('id'), f'{body.amount} {body.period}')
    return r


# ---- Sözleşmeler: Merkez'in yayınladığı üyelik sözleşmeleri; yetkili kişi okuyup elektronik olarak onaylar
@router.get('/contracts')
def contracts(user=Depends(member_user)):
    return central_client.call('GET', '/contracts')


@router.get('/contracts/{did}')
def contract(did: int, user=Depends(member_user)):
    return central_client.call('GET', f'/contracts/{did}')


class AcceptIn(BaseModel):
    hash: str
    signer_name: str
    signer_title: str = ''
    agree: bool = False


@router.post('/contracts/{did}/accept')
def contract_accept(did: int, body: AcceptIn, request: Request, user=Depends(member_user), conn=db.DB):
    if not body.agree:
        raise HTTPException(400, 'Onay için “Okudum, kabul ediyorum” kutusunu işaretleyin')
    ip = (request.headers.get('cf-connecting-ip') or (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
          or (request.client.host if request.client else ''))
    r = central_client.call('POST', f'/contracts/{did}/accept', json={
        'hash': body.hash, 'signer_name': body.signer_name, 'signer_title': body.signer_title,
        'signer_email': user['username'] if '@' in (user.get('username') or '') else '',
        'ip': ip, 'user_agent': request.headers.get('user-agent', '')})
    central_client.forget_contracts()
    db.audit(conn, user['id'], 'Üyelik sözleşmesini onayladı', 'contract', did, f"{body.signer_name} · {r.get('hash', '')[:12]}")
    return r
