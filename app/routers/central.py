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
    # son 12 dönemin ödeme durumu (üyelik başlangıcından önceki aylar gösterilmez)
    start = ((c or {}).get('provisioned_at') or (c or {}).get('created_at') or '')[:7]
    months, y, m = [], int(per[:4]), int(per[5:7])
    for _ in range(12):
        p_ = f'{y:04d}-{m:02d}'
        if start and p_ < start:
            break
        paid = sum(x['amount'] for x in pays if x['period'] == p_)
        months.append({'period': p_, 'paid': paid, 'status': _pay_status(fee, paid, p_)})
        m -= 1
        if not m:
            y, m = y - 1, 12
    from .. import support
    notices = db.rows(conn.execute('''SELECT id, period, amount, paid_at, method, reference, status, decision_note, created_at FROM payment_notices
                                      WHERE slug=? ORDER BY created_at DESC LIMIT 30''', (slug,)))
    return {
        'company': {k: (c or {}).get(k) for k in ('name', 'slug', 'url', 'status', 'mode', 'modules', 'master_username', 'created_at', 'provisioned_at')},
        'package': {'name': pkg['name'], 'description': pkg.get('description', ''), 'modules': pkg.get('modules', [])} if pkg else None,
        'fee': fee, 'period': per, 'paid_this_month': paid_now, 'pay_status': _pay_status(fee, paid_now, per),
        'payments': pays, 'months': months, 'notices': notices, 'suspended': bool(f.get('suspended')), 'suspend_reason': f.get('reason') or '',
        'open_tickets': conn.execute("SELECT COUNT(*) FROM tickets WHERE slug=? AND status IN ('acik','yanit_bekliyor')", (slug,)).fetchone()[0],
        'unread_tickets': conn.execute('SELECT COUNT(*) FROM tickets WHERE slug=? AND company_unread > 0', (slug,)).fetchone()[0],
        'support': support.public_status(conn),
    }


# ---------------- Üyelik sözleşmeleri (Merkez) ----------------
from .. import contracts as ct   # noqa: E402

DOC_STATUS = ('draft', 'published', 'archived')


def _firm_ctx(conn, slug, comps=None, pkgs=None):
    """Firmanın sözleşme alanları için kayıt, paket ve ücret."""
    if comps is None:
        try:
            comps = _companies()
        except HTTPException:
            comps = []
    c = next((x for x in comps if x.get('slug') == slug), None) or {'slug': slug, 'name': slug}
    if pkgs is None:
        try:
            pkgs = _packages()
        except HTTPException:
            pkgs = []
    pkg = next((p for p in pkgs if p.get('id') == c.get('package_id')), None)
    return c, pkg, _fee(c, pkgs)


def _rendered(conn, doc, slug, comps=None, pkgs=None):
    c, pkg, fee = _firm_ctx(conn, slug, comps, pkgs)
    text = ct.render(doc['body'], ct.values(conn, c, pkg, fee))
    return text, ct.fingerprint(doc['title'], doc['version'], text), c


@router.get('/contracts')
def contracts_list(user=Depends(members_user), conn=db.DB):
    ct.seed(conn, user['id'])
    docs = db.rows(conn.execute('''SELECT id, kind, title, version, summary, required, status, published_at, created_at, updated_at
                                   FROM contract_docs ORDER BY CASE status WHEN 'published' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END, kind, id DESC'''))
    try:
        firms = [c for c in _companies() if c.get('status') not in ('pending', 'rejected')]
    except HTTPException:
        firms = []
    for d in docs:
        d['accepted'] = conn.execute('SELECT COUNT(*) FROM contract_acceptances WHERE doc_id=?', (d['id'],)).fetchone()[0]
        d['firms'] = len(firms)
    return {'docs': docs, 'kinds': ct.KINDS, 'fields': ct.FIELDS, 'provider': ct.provider(conn)}


class DocIn(BaseModel):
    kind: str
    title: str
    version: str
    summary: str = ''
    body: str
    required: bool = True


def _doc(conn, did):
    d = db.row(conn.execute('SELECT * FROM contract_docs WHERE id=?', (did,)))
    if not d:
        raise HTTPException(404, 'Sözleşme bulunamadı')
    return d


@router.post('/contracts')
def contract_create(body: DocIn, user=Depends(members_user), conn=db.DB):
    if not body.title.strip() or not body.body.strip() or not body.version.strip():
        raise HTTPException(400, 'Başlık, sürüm ve metin gerekli')
    now = db.now()
    cur = conn.execute('''INSERT INTO contract_docs (kind, title, version, summary, body, required, status, created_by, created_at, updated_at)
                          VALUES (?,?,?,?,?,?, 'draft', ?,?,?)''',
                       (body.kind if body.kind in ct.KINDS else 'diger', body.title.strip()[:160], body.version.strip()[:20], body.summary.strip()[:400],
                        body.body.strip(), 1 if body.required else 0, user['id'], now, now))
    db.audit(conn, user['id'], 'Sözleşme taslağı oluşturdu', 'contract', cur.lastrowid, body.title[:80])
    conn.commit()
    return {'id': cur.lastrowid}


@router.put('/contracts/{did}')
def contract_update(did: int, body: DocIn, user=Depends(members_user), conn=db.DB):
    d = _doc(conn, did)
    if d['status'] != 'draft':
        raise HTTPException(409, 'Yayınlanmış sözleşme değiştirilemez; yeni sürüm (taslak) oluşturun')
    conn.execute('UPDATE contract_docs SET kind=?, title=?, version=?, summary=?, body=?, required=?, updated_at=? WHERE id=?',
                 (body.kind if body.kind in ct.KINDS else 'diger', body.title.strip()[:160], body.version.strip()[:20], body.summary.strip()[:400],
                  body.body.strip(), 1 if body.required else 0, db.now(), did))
    conn.commit()
    return {'ok': True}


@router.delete('/contracts/{did}')
def contract_delete(did: int, user=Depends(members_user), conn=db.DB):
    d = _doc(conn, did)
    if d['status'] != 'draft':
        raise HTTPException(409, 'Yalnızca taslak silinebilir (yayınlanmış sözleşmeler ve onay kanıtları saklanır)')
    conn.execute('DELETE FROM contract_docs WHERE id=?', (did,))
    conn.commit()
    return {'ok': True}


@router.post('/contracts/{did}/new-version')
def contract_new_version(did: int, user=Depends(members_user), conn=db.DB):
    """Yayındaki sözleşmeden yeni sürüm taslağı (sürüm numarası bir artar)."""
    d = _doc(conn, did)
    parts = d['version'].split('.')
    try:
        parts[-1] = str(int(parts[-1]) + 1)
        ver = '.'.join(parts)
    except ValueError:
        ver = d['version'] + '.1'
    now = db.now()
    cur = conn.execute('''INSERT INTO contract_docs (kind, title, version, summary, body, required, status, created_by, created_at, updated_at)
                          VALUES (?,?,?,?,?,?,'draft',?,?,?)''', (d['kind'], d['title'], ver, '', d['body'], d['required'], user['id'], now, now))
    conn.commit()
    return {'id': cur.lastrowid, 'version': ver}


@router.post('/contracts/{did}/publish')
def contract_publish(did: int, user=Depends(members_user), conn=db.DB):
    """Yayınla: aynı türdeki önceki yayın arşivlenir; firmalardan bu sürüm için onay beklenir."""
    d = _doc(conn, did)
    if d['status'] != 'draft':
        raise HTTPException(409, 'Yalnızca taslak yayınlanabilir')
    now = db.now()
    conn.execute("UPDATE contract_docs SET status='archived' WHERE kind=? AND status='published' AND kind != 'diger'", (d['kind'],))
    conn.execute("UPDATE contract_docs SET status='published', published_at=?, updated_at=? WHERE id=?", (now, now, did))
    db.audit(conn, user['id'], 'Sözleşme yayınladı', 'contract', did, f"{d['title']} v{d['version']}")
    conn.commit()
    return {'ok': True}


@router.post('/contracts/{did}/archive')
def contract_archive(did: int, user=Depends(members_user), conn=db.DB):
    d = _doc(conn, did)
    if d['status'] != 'published':
        raise HTTPException(409, 'Yalnızca yayındaki sözleşme yayından kaldırılabilir')
    conn.execute("UPDATE contract_docs SET status='archived', updated_at=? WHERE id=?", (db.now(), did))
    db.audit(conn, user['id'], 'Sözleşmeyi yayından kaldırdı', 'contract', did, d['title'])
    conn.commit()
    return {'ok': True}


@router.get('/contracts/{did}')
def contract_detail(did: int, slug: str = '', user=Depends(members_user), conn=db.DB):
    """Şablon + (slug verilirse) o firmaya göre doldurulmuş önizleme + firma bazında onay durumu."""
    d = _doc(conn, did)
    try:
        comps, pkgs = _companies(), _packages()
    except HTTPException:
        comps, pkgs = [], []
    firms = [c for c in comps if c.get('status') not in ('pending', 'rejected')]
    acc = {r['slug']: r for r in db.rows(conn.execute(
        'SELECT slug, company_name, signer_name, signer_title, signer_email, doc_hash, ip, accepted_at FROM contract_acceptances WHERE doc_id=?', (did,)))}
    d['firms'] = [{'slug': c['slug'], 'name': c.get('name'), 'status': c.get('status'), 'acceptance': acc.get(c['slug'])} for c in firms]
    target = slug or (firms[0]['slug'] if firms else '')
    if target:
        d['preview'], d['preview_hash'], c = _rendered(conn, d, target, comps, pkgs)
        d['preview_firm'] = c.get('name') or target
    return d


@router.get('/contracts/{did}/acceptance/{slug}')
def contract_acceptance(did: int, slug: str, user=Depends(members_user), conn=db.DB):
    """Onay kanıtı: onaylanan metnin birebir kopyası + parmak izi + imzalayan + IP + tarayıcı."""
    r = db.row(conn.execute('''SELECT a.*, d.title, d.version FROM contract_acceptances a JOIN contract_docs d ON d.id=a.doc_id
                               WHERE a.doc_id=? AND a.slug=?''', (did, slug)))
    if not r:
        raise HTTPException(404, 'Onay kaydı yok')
    r['hash_ok'] = ct.fingerprint(r['title'], r['version'], r['body']) == r['doc_hash']
    return r


class ProviderIn(BaseModel):
    saglayici: str = ''
    saglayici_adres: str = ''
    saglayici_vergi: str = ''
    saglayici_mersis: str = ''
    saglayici_eposta: str = ''
    saglayici_kep: str = ''
    mahkeme: str = ''


@router.put('/contracts-provider')
def contracts_provider(body: ProviderIn, user=Depends(members_user), conn=db.DB):
    v = {k: (getattr(body, k) or '').strip()[:300] for k in ct.PROVIDER_DEFAULT}
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (ct.PROVIDER_KEY, json.dumps(v, ensure_ascii=False)))
    conn.commit()
    return ct.provider(conn)


# ---- Firma → Merkez: sözleşmeler (federasyon)
@fed_router.get('/contracts')
def fed_contracts(request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    docs = db.rows(conn.execute("SELECT id, kind, title, version, summary, required, published_at FROM contract_docs WHERE status='published' ORDER BY kind"))
    acc = {r['doc_id']: r for r in db.rows(conn.execute(
        'SELECT doc_id, signer_name, signer_title, accepted_at FROM contract_acceptances WHERE slug=?', (slug,)))}
    for d in docs:
        d['acceptance'] = acc.get(d['id'])
        prev = db.row(conn.execute('''SELECT d.version, a.accepted_at FROM contract_acceptances a JOIN contract_docs d ON d.id=a.doc_id
                                      WHERE a.slug=? AND d.kind=? AND d.id != ? ORDER BY a.accepted_at DESC LIMIT 1''', (slug, d['kind'], d['id'])))
        d['previous'] = prev
    history = db.rows(conn.execute('''SELECT a.doc_id, d.title, d.version, d.status, a.signer_name, a.signer_title, a.accepted_at
                                      FROM contract_acceptances a JOIN contract_docs d ON d.id=a.doc_id WHERE a.slug=? ORDER BY a.accepted_at DESC''', (slug,)))
    return {'docs': docs, 'pending': sum(1 for d in docs if d['required'] and not d['acceptance']), 'history': history}


@fed_router.get('/contracts/{did}')
def fed_contract(did: int, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    d = _doc(conn, did)
    a = db.row(conn.execute('SELECT signer_name, signer_title, signer_email, doc_hash, body, ip, user_agent, accepted_at FROM contract_acceptances WHERE doc_id=? AND slug=?', (did, slug)))
    if d['status'] != 'published' and not a:
        raise HTTPException(404, 'Sözleşme bulunamadı')
    if a:   # onaylanmış: o gün onaylanan metin birebir
        text, h = a.pop('body'), a['doc_hash']
    else:
        text, h, _c = _rendered(conn, d, slug)
    return {'id': d['id'], 'kind': d['kind'], 'title': d['title'], 'version': d['version'], 'summary': d['summary'], 'required': d['required'],
            'status': d['status'], 'published_at': d['published_at'], 'body': text, 'hash': h, 'acceptance': a}


class FedAcceptIn(BaseModel):
    hash: str
    signer_name: str
    signer_title: str = ''
    signer_email: str = ''
    ip: str = ''
    user_agent: str = ''


@fed_router.post('/contracts/{did}/accept')
def fed_contract_accept(did: int, body: FedAcceptIn, request: Request, slug: str = '', conn=db.DB):
    slug, _ = _fed(request, slug)
    d = _doc(conn, did)
    if d['status'] != 'published':
        raise HTTPException(409, 'Bu sözleşme yayında değil')
    if conn.execute('SELECT 1 FROM contract_acceptances WHERE doc_id=? AND slug=?', (did, slug)).fetchone():
        raise HTTPException(409, 'Bu sözleşme zaten onaylanmış')
    if len(body.signer_name.strip()) < 3:
        raise HTTPException(400, 'İmzalayan yetkilinin adı soyadı gerekli')
    text, h, c = _rendered(conn, d, slug)
    if not hmac.compare_digest(h, (body.hash or '').strip()):
        raise HTTPException(409, 'Sözleşme metni siz okurken güncellendi; lütfen sayfayı yenileyip tekrar okuyun')
    now = db.now()
    conn.execute('''INSERT INTO contract_acceptances (doc_id, slug, company_name, signer_name, signer_title, signer_email, doc_hash, body, ip, user_agent, accepted_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (did, slug, c.get('name'), body.signer_name.strip()[:120], body.signer_title.strip()[:120],
                                                         body.signer_email.strip()[:160], h, text, body.ip[:64], body.user_agent[:300], now))
    conn.commit()
    return {'ok': True, 'accepted_at': now, 'hash': h}
