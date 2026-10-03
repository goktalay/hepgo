"""Veilox Merkez (HEPGO merkez modu): üyelik yönetimi, yumuşak askı, ödeme takibi, destek talepleri (ticket), toplu SMS.

- Kurulum/provisioning kayıtları Veilox kurulum servisinde (veilox.main) kalır; Merkez onu yerel soketten İÇ anahtarla çağırır
  (CENTRAL_API_SECRET — firmalarda bulunmaz). Böylece kanıtlanmış kurulum kodu korunur, arayüz HEPGO standardında olur.
- Firma instance'ları /api/federation/* uçlarını paylaşılan federasyon anahtarı + firma slug'ı ile çağırır
  (askı durumu, üyelik/ödeme bilgisi, destek talepleri).
"""
import hmac
import json
import re
import time
import urllib.parse
from datetime import date
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import auth, cameras as camlib, config, db, push

router = APIRouter(prefix='/api/central')
fed_router = APIRouter(prefix='/api/federation')
members_user = auth.require_module('members')
tickets_user = auth.require_module('tickets')
sms_user = auth.require_module('sms')


# ---------------- Veilox kurulum servisi (yerel soket, iç anahtar) ----------------
def _vx(method, path, json_body=None, raw=False):
    if not config.FEDERATION_CENTRAL:
        raise HTTPException(404, 'Bulunamadı')
    if not config.CENTRAL_API_SECRET:
        raise HTTPException(503, 'Kurulum servisi anahtarı tanımlı değil')
    try:
        transport = httpx.HTTPTransport(uds=config.VEILOX_SOCKET)
        with httpx.Client(transport=transport, base_url='http://veilox', timeout=120) as c:
            r = c.request(method, path, json=json_body, headers={'X-Central-Secret': config.CENTRAL_API_SECRET})
    except httpx.HTTPError:
        raise HTTPException(503, 'Kurulum servisine (Veilox) ulaşılamıyor')
    if r.status_code >= 400:
        try:
            detail = r.json().get('detail')
        except ValueError:
            detail = None
        raise HTTPException(r.status_code, detail or 'Kurulum servisi hatası')
    return r if raw else r.json()


_COMP_CACHE = {'at': 0.0, 'rows': None}


def _companies(fresh=False):
    now = time.monotonic()
    if fresh or _COMP_CACHE['rows'] is None or now - _COMP_CACHE['at'] > 60:
        _COMP_CACHE['rows'] = _vx('GET', '/api/companies')
        _COMP_CACHE['at'] = now
    return _COMP_CACHE['rows']


def _packages():
    return _vx('GET', '/api/packages')


def _fee(c, pkgs):
    if c.get('monthly_fee'):
        return float(c['monthly_fee'])
    p = next((p for p in pkgs if p.get('id') == c.get('package_id')), None)
    return float(p['monthly_fee']) if p else 0.0


def _period(d=None):
    return (d or date.today()).isoformat()[:7]


def _pay_status(fee, paid, period):
    if fee <= 0:
        return 'ucretsiz'
    if paid >= fee - 0.005:
        return 'odendi'
    if paid > 0:
        return 'kismi'
    return 'gecikti' if period < _period() else 'bekliyor'


# ---------------- Üyelik yönetimi ----------------
@router.get('/members')
def members(user=Depends(members_user), conn=db.DB):
    comps = _companies(fresh=True)
    pkgs = _packages()
    pkg_name = {p['id']: p['name'] for p in pkgs}
    flags = {r['slug']: r for r in db.rows(conn.execute('SELECT * FROM member_flags'))}
    per = _period()
    paid = {r[0]: r[1] for r in conn.execute('SELECT slug, SUM(amount) FROM member_payments WHERE period=? GROUP BY slug', (per,))}
    open_t = {r[0]: r[1] for r in conn.execute("SELECT slug, COUNT(*) FROM tickets WHERE status NOT IN ('cozuldu','kapali') GROUP BY slug")}
    out = []
    for c in comps:
        f = flags.get(c['slug'], {})
        fee = _fee(c, pkgs)
        p = paid.get(c['slug'], 0) or 0
        out.append({**c, 'package_name': pkg_name.get(c.get('package_id')), 'fee': fee,
                    'suspended': bool(f.get('suspended')), 'suspend_reason': f.get('reason') or '', 'phone': f.get('phone') or '',
                    'flag_note': f.get('note') or '', 'paid_this_month': p, 'pay_status': _pay_status(fee, p, per),
                    'open_tickets': open_t.get(c['slug'], 0)})
    return {'members': out, 'packages': pkgs, 'period': per}


class MemberIn(BaseModel):
    name: str
    master_username: str
    master_name: str = ''
    package_slug: str = ''
    mode: str = 'online'
    modules: List[str] = []
    url: str = ''
    password: str = ''
    white_label: bool = False
    note: str = ''


@router.post('/members')
def member_create(body: MemberIn, user=Depends(members_user), conn=db.DB):
    r = _vx('POST', '/api/companies', body.model_dump())
    db.audit(conn, user['id'], 'Merkez: firma oluşturdu', 'member', r.get('slug'), body.name)
    _COMP_CACHE['rows'] = None
    return r


@router.put('/members/{cid}')
def member_update(cid: int, body: MemberIn, user=Depends(members_user), conn=db.DB):
    r = _vx('PUT', f'/api/companies/{cid}', body.model_dump())
    db.audit(conn, user['id'], 'Merkez: firma bilgisini düzenledi', 'member', r.get('slug'), body.name)
    _COMP_CACHE['rows'] = None
    return r


@router.post('/members/{cid}/{action}')
def member_action(cid: int, action: str, user=Depends(members_user), conn=db.DB):
    """Onayla / Kur (provision) / Kurulum linki. Sert servis kaldırma (deprovision) bilinçli olarak sunulmaz."""
    path = {'approve': 'approve', 'provision': 'provision', 'download-link': 'download-link'}.get(action)
    if not path:
        raise HTTPException(400, 'Geçersiz işlem')
    r = _vx('POST', f'/api/companies/{cid}/{path}')
    db.audit(conn, user['id'], f'Merkez: firma işlemi ({action})', 'member', cid)
    _COMP_CACHE['rows'] = None
    if action == 'download-link' and r.get('url'):
        r['full_url'] = f'https://veilox.app{r["url"]}'
    return r


@router.delete('/members/{cid}')
def member_delete(cid: int, confirm: str = '', user=Depends(members_user), conn=db.DB):
    c = next((c for c in _companies(fresh=True) if c['id'] == cid), None)
    if not c:
        raise HTTPException(404, 'Firma bulunamadı')
    if confirm.strip() != c['name']:
        raise HTTPException(400, 'Onay için firma adını aynen yazın')
    _vx('DELETE', f'/api/companies/{cid}')
    db.audit(conn, user['id'], 'Merkez: firma kaydını sildi', 'member', c['slug'], c['name'])
    _COMP_CACHE['rows'] = None
    return {'ok': True}


class FlagIn(BaseModel):
    suspended: Optional[bool] = None
    reason: Optional[str] = None
    phone: Optional[str] = None
    note: Optional[str] = None


@router.put('/members/flags/{slug}')
def member_flags(slug: str, body: FlagIn, user=Depends(members_user), conn=db.DB):
    """Yumuşak askı (pasife al / aktif et) + iletişim telefonu. Firma instance'ı ~5 dk içinde uygular; veri ve servis korunur."""
    cur = db.row(conn.execute('SELECT * FROM member_flags WHERE slug=?', (slug,))) or {}
    vals = {'suspended': int(body.suspended) if body.suspended is not None else int(cur.get('suspended') or 0),
            'reason': body.reason if body.reason is not None else cur.get('reason'),
            'phone': body.phone if body.phone is not None else cur.get('phone'),
            'note': body.note if body.note is not None else cur.get('note')}
    conn.execute('''INSERT INTO member_flags (slug,suspended,reason,phone,note,updated_at) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(slug) DO UPDATE SET suspended=excluded.suspended, reason=excluded.reason, phone=excluded.phone,
                    note=excluded.note, updated_at=excluded.updated_at''',
                 (slug, vals['suspended'], vals['reason'], vals['phone'], vals['note'], db.now()))
    if body.suspended is not None:
        db.audit(conn, user['id'], 'Merkez: firmayı pasife aldı' if body.suspended else 'Merkez: firmayı aktif etti', 'member', slug, vals['reason'] or '')
    conn.commit()
    return {'ok': True, **vals}


# ---------------- Paketler ----------------
class PackageIn(BaseModel):
    name: str
    description: str = ''
    modules: List[str] = []
    monthly_fee: float = 0
    mode: str = 'online'
    visible: bool = True
    white_label: bool = False
    sort: int = 0


@router.get('/packages')
def packages(user=Depends(members_user)):
    return {'packages': _packages(), 'modules': _vx('GET', '/api/modules')}


@router.post('/packages')
def package_create(body: PackageIn, user=Depends(members_user)):
    return _vx('POST', '/api/packages', body.model_dump())


@router.put('/packages/{pid}')
def package_update(pid: int, body: PackageIn, user=Depends(members_user)):
    return _vx('PUT', f'/api/packages/{pid}', body.model_dump())


@router.delete('/packages/{pid}')
def package_delete(pid: int, user=Depends(members_user)):
    return _vx('DELETE', f'/api/packages/{pid}')


# ---------------- Ödeme takibi ----------------
@router.get('/payments')
def payments(period: str = '', user=Depends(members_user), conn=db.DB):
    per = period if re.fullmatch(r'\d{4}-\d{2}', period or '') else _period()
    comps = _companies()
    pkgs = _packages()
    rows = db.rows(conn.execute('SELECT * FROM member_payments WHERE period=? ORDER BY paid_at DESC', (per,)))
    by = {}
    for r in rows:
        by.setdefault(r['slug'], []).append(r)
    out, tot_fee, tot_paid = [], 0.0, 0.0
    for c in comps:
        fee = _fee(c, pkgs)
        lst = by.get(c['slug'], [])
        paid = sum(r['amount'] for r in lst)
        tot_fee += fee; tot_paid += paid
        out.append({'id': c['id'], 'slug': c['slug'], 'name': c['name'], 'status': c['status'], 'fee': fee, 'paid': paid,
                    'pay_status': _pay_status(fee, paid, per), 'payments': lst})
    months = db.rows(conn.execute('''SELECT period, SUM(amount) AS total FROM member_payments
                                     GROUP BY period ORDER BY period DESC LIMIT 12'''))
    return {'period': per, 'rows': out, 'total_fee': tot_fee, 'total_paid': tot_paid, 'history': list(reversed(months))}


class PaymentIn(BaseModel):
    slug: str
    period: str
    amount: float
    method: str = 'havale'
    note: str = ''
    paid_at: str = ''


@router.post('/payments')
def payment_add(body: PaymentIn, user=Depends(members_user), conn=db.DB):
    if not re.fullmatch(r'\d{4}-\d{2}', body.period):
        raise HTTPException(400, 'Dönem YYYY-AA biçiminde olmalı')
    if body.amount <= 0:
        raise HTTPException(400, 'Tutar sıfırdan büyük olmalı')
    cur = conn.execute('''INSERT INTO member_payments (slug,period,amount,paid_at,method,note,created_by,created_at)
                          VALUES (?,?,?,?,?,?,?,?)''',
                       (body.slug, body.period, round(body.amount, 2), (body.paid_at or db.now())[:10], body.method, body.note,
                        user['id'], db.now()))
    db.audit(conn, user['id'], 'Merkez: üyelik ödemesi kaydetti', 'member_payment', cur.lastrowid, f'{body.slug} {body.period} {body.amount}')
    conn.commit()
    return {'id': cur.lastrowid}


@router.delete('/payments/{pid}')
def payment_delete(pid: int, user=Depends(members_user), conn=db.DB):
    conn.execute('DELETE FROM member_payments WHERE id=?', (pid,))
    db.audit(conn, user['id'], 'Merkez: üyelik ödemesini sildi', 'member_payment', pid)
    conn.commit()
    return {'ok': True}


# ---------------- Destek talepleri (merkez ekibi) ----------------
STATUSES = ('acik', 'yanit_bekliyor', 'cozuldu', 'kapali')
PRIORITIES = ('dusuk', 'normal', 'yuksek', 'acil')


def _staff_ids(conn):
    roles = (auth.ADMIN, auth.SUPPORT_ROLE)
    ids = {r[0] for r in conn.execute(f'SELECT user_id FROM user_roles WHERE role IN ({",".join("?" * len(roles))})', roles)}
    ids |= {r[0] for r in conn.execute('SELECT id, username FROM users WHERE active=1') if auth.is_master(r[1])}
    return ids


def _ticket(conn, tid):
    t = db.row(conn.execute('''SELECT t.*, u.full_name AS assignee_name FROM tickets t
                               LEFT JOIN users u ON u.id=t.assignee_id WHERE t.id=?''', (tid,)))
    if not t:
        raise HTTPException(404, 'Talep bulunamadı')
    t['messages'] = db.rows(conn.execute('SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id', (tid,)))
    return t


@router.get('/tickets')
def tickets(status: str = '', q: str = '', slug: str = '', user=Depends(tickets_user), conn=db.DB):
    where, args = ['1=1'], []
    if status == 'open':
        where.append("t.status NOT IN ('cozuldu','kapali')")
    elif status in STATUSES:
        where.append('t.status=?'); args.append(status)
    if slug:
        where.append('t.slug=?'); args.append(slug)
    if q:
        where.append('(t.subject LIKE ? OR t.company_name LIKE ? OR t.code LIKE ?)'); args += [f'%{q}%'] * 3
    rows = db.rows(conn.execute(f'''SELECT t.*, u.full_name AS assignee_name,
                                     (SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id=t.id) AS msg_count
                                     FROM tickets t LEFT JOIN users u ON u.id=t.assignee_id
                                     WHERE {" AND ".join(where)} ORDER BY t.support_unread DESC, t.updated_at DESC LIMIT 500''', args))
    stats = {r[0]: r[1] for r in conn.execute('SELECT status, COUNT(*) FROM tickets GROUP BY status')}
    return {'tickets': rows, 'stats': stats}


@router.get('/tickets/{tid}')
def ticket_detail(tid: int, user=Depends(tickets_user), conn=db.DB):
    t = _ticket(conn, tid)
    if t['support_unread']:
        conn.execute('UPDATE tickets SET support_unread=0 WHERE id=?', (tid,)); conn.commit()
    return t


class MsgIn(BaseModel):
    body: str
    name: str = ''


@router.post('/tickets/{tid}/messages')
def ticket_reply(tid: int, body: MsgIn, user=Depends(tickets_user), conn=db.DB):
    text = body.body.strip()[:5000]
    if not text:
        raise HTTPException(400, 'Mesaj boş olamaz')
    _ticket(conn, tid)
    conn.execute('INSERT INTO ticket_messages (ticket_id,author_kind,author_name,body,created_at) VALUES (?,?,?,?,?)',
                 (tid, 'support', user['full_name'], text, db.now()))
    conn.execute("""UPDATE tickets SET status=CASE WHEN status IN ('acik','yanit_bekliyor') THEN 'yanit_bekliyor' ELSE status END,
                    company_unread=company_unread+1, support_unread=0, updated_at=?,
                    assignee_id=COALESCE(assignee_id, ?) WHERE id=?""", (db.now(), user['id'], tid))
    db.audit(conn, user['id'], 'Merkez: destek talebini yanıtladı', 'ticket', tid)
    conn.commit()
    return _ticket(conn, tid)


class TicketUpd(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[int] = None


@router.put('/tickets/{tid}')
def ticket_update(tid: int, body: TicketUpd, user=Depends(tickets_user), conn=db.DB):
    t = _ticket(conn, tid)
    if body.status and body.status in STATUSES and body.status != t['status']:
        conn.execute('UPDATE tickets SET status=?, updated_at=? WHERE id=?', (body.status, db.now(), tid))
        label = {'acik': 'açık', 'yanit_bekliyor': 'yanıt bekliyor', 'cozuldu': 'çözüldü', 'kapali': 'kapalı'}[body.status]
        conn.execute('INSERT INTO ticket_messages (ticket_id,author_kind,author_name,body,created_at) VALUES (?,?,?,?,?)',
                     (tid, 'system', user['full_name'], f'Durum “{label}” olarak değiştirildi.', db.now()))
        if body.status in ('cozuldu', 'kapali'):
            conn.execute('UPDATE tickets SET company_unread=company_unread+1 WHERE id=?', (tid,))
    if body.priority and body.priority in PRIORITIES:
        conn.execute('UPDATE tickets SET priority=?, updated_at=? WHERE id=?', (body.priority, db.now(), tid))
    if body.assignee_id is not None:
        conn.execute('UPDATE tickets SET assignee_id=?, updated_at=? WHERE id=?', (body.assignee_id or None, db.now(), tid))
    conn.commit()
    return _ticket(conn, tid)


@router.get('/staff')
def staff(user=Depends(tickets_user), conn=db.DB):
    ids = _staff_ids(conn)
    if not ids:
        return []
    return db.rows(conn.execute(f'SELECT id, full_name FROM users WHERE active=1 AND id IN ({",".join("?" * len(ids))}) ORDER BY full_name',
                                tuple(ids)))


# ---------------- Toplu SMS ----------------
SMS_KEY = 'sms_config'


def _sms_cfg(conn):
    r = conn.execute('SELECT v FROM app_kv WHERE k=?', (SMS_KEY,)).fetchone()
    try:
        return json.loads(r[0]) if r else {}
    except ValueError:
        return {}


@router.get('/sms/config')
def sms_config(user=Depends(sms_user), conn=db.DB):
    c = _sms_cfg(conn)
    return {'provider': c.get('provider', 'netgsm'), 'usercode': c.get('usercode', ''), 'header': c.get('header', ''),
            'has_password': bool(c.get('password_enc'))}


class SmsCfgIn(BaseModel):
    provider: str = 'netgsm'
    usercode: str = ''
    password: str = ''   # boşsa değişmez
    header: str = ''


@router.put('/sms/config')
def sms_config_set(body: SmsCfgIn, user=Depends(sms_user), conn=db.DB):
    c = _sms_cfg(conn)
    c.update({'provider': body.provider, 'usercode': body.usercode.strip(), 'header': body.header.strip()})
    if body.password:
        c['password_enc'] = camlib.encrypt(body.password)
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (SMS_KEY, json.dumps(c)))
    db.audit(conn, user['id'], 'Merkez: SMS sağlayıcı ayarını güncelledi', 'sms', None, body.provider)
    conn.commit()
    return {'ok': True}


def _norm_tr(n):
    d = re.sub(r'\D', '', n or '')
    if d.startswith('90') and len(d) == 12:
        d = d[2:]
    if d.startswith('0') and len(d) == 11:
        d = d[1:]
    return d if re.fullmatch(r'5\d{9}', d) else None


class SmsIn(BaseModel):
    numbers: List[str]
    message: str


@router.post('/sms/send')
def sms_send(body: SmsIn, user=Depends(sms_user), conn=db.DB):
    nums = sorted({x for x in (_norm_tr(n) for n in body.numbers) if x})
    msg = body.message.strip()
    if not nums:
        raise HTTPException(400, 'Geçerli bir cep telefonu numarası yok (5xx xxx xx xx)')
    if not msg:
        raise HTTPException(400, 'Mesaj boş olamaz')
    c = _sms_cfg(conn)
    status, resp = 'dry', 'SMS sağlayıcısı tanımlı değil — gönderilmedi (kayıt alındı)'
    if c.get('usercode') and c.get('password_enc') and c.get('header'):
        if c.get('provider', 'netgsm') == 'netgsm':
            q = urllib.parse.urlencode({'usercode': c['usercode'], 'password': camlib.decrypt(c['password_enc']),
                                        'gsmno': ','.join(nums), 'message': msg, 'msgheader': c['header'], 'dil': 'TR'})
            try:
                r = httpx.get(f'https://api.netgsm.com.tr/sms/send/get/?{q}', timeout=20)
                resp = r.text.strip()[:300]
                status = 'sent' if resp.split(' ')[0] in ('00', '01', '02') else 'failed'
            except httpx.HTTPError as e:
                status, resp = 'failed', str(e)[:300]
    conn.execute('INSERT INTO sms_log (numbers,message,status,provider,response,sent_by,created_at) VALUES (?,?,?,?,?,?,?)',
                 (json.dumps(nums), msg, status, c.get('provider', 'netgsm'), resp, user['id'], db.now()))
    db.audit(conn, user['id'], 'Merkez: toplu SMS', 'sms', None, f'{len(nums)} numara · {status}')
    conn.commit()
    return {'status': status, 'count': len(nums), 'response': resp}


@router.get('/sms/log')
def sms_log(user=Depends(sms_user), conn=db.DB):
    rows = db.rows(conn.execute('''SELECT s.*, u.full_name AS sender FROM sms_log s LEFT JOIN users u ON u.id=s.sent_by
                                   ORDER BY s.id DESC LIMIT 200'''))
    for r in rows:
        try:
            r['numbers'] = json.loads(r['numbers'])
        except ValueError:
            r['numbers'] = []
    return rows


@router.get('/sms/recipients')
def sms_recipients(user=Depends(sms_user), conn=db.DB):
    flags = {r['slug']: r for r in db.rows(conn.execute('SELECT slug, phone FROM member_flags'))}
    try:
        comps = _companies()
    except HTTPException:
        comps = []
    return [{'slug': c['slug'], 'name': c['name'], 'phone': (flags.get(c['slug']) or {}).get('phone') or '', 'status': c['status']}
            for c in comps]


# ---------------- Firma → Merkez federasyon uçları ----------------
def _fed(request: Request, slug: str):
    if not config.FEDERATION_CENTRAL:
        raise HTTPException(404, 'Bulunamadı')
    secret = request.headers.get('x-fed-secret', '')
    if not config.FEDERATION_SECRET or not hmac.compare_digest(secret, config.FEDERATION_SECRET):
        raise HTTPException(403, 'Yetkisiz')
    slug = (slug or '').strip().lower()
    if not re.fullmatch(r'[a-z0-9-]{2,60}', slug):
        raise HTTPException(400, 'Geçersiz firma kimliği')
    try:   # kurulum servisine ulaşılabiliyorsa firmanın gerçekten kayıtlı olduğunu doğrula
        comps = _companies()
        c = next((c for c in comps if c['slug'] == slug), None)
        if comps and not c:
            raise HTTPException(404, 'Firma merkezde kayıtlı değil')
        return slug, c
    except HTTPException as e:
        if e.status_code == 404:
            raise
        return slug, None


@fed_router.get('/status')
def fed_status(request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    f = db.row(conn.execute('SELECT suspended, reason FROM member_flags WHERE slug=?', (slug,))) or {}
    return {'suspended': bool(f.get('suspended')), 'reason': f.get('reason') or ''}


@fed_router.get('/membership')
def fed_membership(request: Request, slug: str = '', conn=db.DB):
    slug, c = _fed(request, slug)
    pkgs = []
    try:
        pkgs = _packages()
    except HTTPException:
        pass
    fee = _fee(c, pkgs) if c else 0.0
    pkg = next((p for p in pkgs if c and p.get('id') == c.get('package_id')), None)
    pays = db.rows(conn.execute('SELECT period, amount, paid_at, method, note FROM member_payments WHERE slug=? ORDER BY period DESC, paid_at DESC LIMIT 60', (slug,)))
    per = _period()
    paid_now = sum(p['amount'] for p in pays if p['period'] == per)
    f = db.row(conn.execute('SELECT suspended, reason FROM member_flags WHERE slug=?', (slug,))) or {}
    return {
        'company': {k: (c or {}).get(k) for k in ('name', 'slug', 'url', 'status', 'mode', 'modules', 'master_username', 'created_at', 'provisioned_at')},
        'package': {'name': pkg['name'], 'description': pkg.get('description', '')} if pkg else None,
        'fee': fee, 'period': per, 'paid_this_month': paid_now, 'pay_status': _pay_status(fee, paid_now, per),
        'payments': pays, 'suspended': bool(f.get('suspended')), 'suspend_reason': f.get('reason') or '',
    }


@fed_router.get('/tickets')
def fed_tickets(request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    return db.rows(conn.execute('''SELECT id, code, subject, category, priority, status, company_unread, created_at, updated_at,
                                   (SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id=t.id) AS msg_count
                                   FROM tickets t WHERE slug=? ORDER BY updated_at DESC LIMIT 300''', (slug,)))


class FedTicketIn(BaseModel):
    subject: str
    body: str
    category: str = 'teknik'
    priority: str = 'normal'
    name: str = ''
    email: str = ''
    company_name: str = ''


@fed_router.post('/tickets')
def fed_ticket_create(body: FedTicketIn, request: Request, slug: str = '', conn=db.DB):
    slug, c = _fed(request, slug)
    subj, text = body.subject.strip()[:200], body.body.strip()[:5000]
    if not subj or not text:
        raise HTTPException(400, 'Konu ve açıklama gerekli')
    pr = body.priority if body.priority in PRIORITIES else 'normal'
    cname = (c or {}).get('name') or body.company_name[:120] or slug
    now = db.now()
    cur = conn.execute('''INSERT INTO tickets (slug,company_name,subject,category,priority,status,opened_by_name,opened_by_email,
                          company_unread,support_unread,created_at,updated_at) VALUES (?,?,?,?,?,'acik',?,?,0,1,?,?)''',
                       (slug, cname, subj, body.category[:30], pr, body.name[:120], body.email[:160], now, now))
    tid = cur.lastrowid
    conn.execute('UPDATE tickets SET code=? WHERE id=?', (f'T-{tid:04d}', tid))
    conn.execute('INSERT INTO ticket_messages (ticket_id,author_kind,author_name,body,created_at) VALUES (?,?,?,?,?)',
                 (tid, 'company', body.name[:120] or cname, text, now))
    conn.commit()
    push.send(_staff_ids(conn), {'type': 'ticket', 'title': f'Yeni destek talebi · {cname}', 'body': subj,
                                 'url': f'/app#/tickets/{tid}', 'tag': f'ticket-{tid}'})
    return {'id': tid, 'code': f'T-{tid:04d}'}


def _fed_ticket(conn, slug, tid):
    t = db.row(conn.execute('SELECT * FROM tickets WHERE id=? AND slug=?', (tid, slug)))
    if not t:
        raise HTTPException(404, 'Talep bulunamadı')
    t['messages'] = db.rows(conn.execute('SELECT author_kind, author_name, body, created_at FROM ticket_messages WHERE ticket_id=? ORDER BY id', (tid,)))
    return t


@fed_router.get('/tickets/{tid}')
def fed_ticket_detail(tid: int, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    t = _fed_ticket(conn, slug, tid)
    if t['company_unread']:
        conn.execute('UPDATE tickets SET company_unread=0 WHERE id=?', (tid,)); conn.commit()
    t.pop('assignee_id', None)
    return t


@fed_router.post('/tickets/{tid}/messages')
def fed_ticket_reply(tid: int, body: MsgIn, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    t = _fed_ticket(conn, slug, tid)
    text = body.body.strip()[:5000]
    if not text:
        raise HTTPException(400, 'Mesaj boş olamaz')
    now = db.now()
    conn.execute('INSERT INTO ticket_messages (ticket_id,author_kind,author_name,body,created_at) VALUES (?,?,?,?,?)',
                 (tid, 'company', body.name[:120] or t['company_name'], text, now))
    conn.execute("UPDATE tickets SET status='acik', support_unread=support_unread+1, company_unread=0, updated_at=? WHERE id=?", (now, tid))
    conn.commit()
    push.send(_staff_ids(conn), {'type': 'ticket', 'title': f'Destek talebine yanıt · {t["company_name"]}', 'body': t['subject'],
                                 'url': f'/app#/tickets/{tid}', 'tag': f'ticket-{tid}'})
    return _fed_ticket(conn, slug, tid)
