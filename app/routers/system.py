"""Alt durum çubuğu (aktif kullanıcı sayısı, sunucu durumu) ve sesle yazdırma (dikte).

Dikte: metin kutusundaki mikrofon düğmesiyle kaydedilen kısa ses bu sunucudaki Whisper ile metne çevrilir
(ses dışarı gönderilmez, kaydedilmez; geçici dosya hemen silinir).
"""
import json
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from typing import Optional
from pydantic import BaseModel

from .. import auth, config, db, document_media, policy, sysstat
from .admin import ONLINE_WINDOW

router = APIRouter(prefix='/api/system')

import re as _re
import subprocess as _sp
import time as _time

_ver = {'v': None, 't': 0.0}
_SVC_RE = _re.compile(r'^caymaz[a-z0-9-]*\.service$')
_SVC_LABELS = {
    'caymaz.service': 'Ana Uygulama (GÖKKUBBE)', 'caymaz-turkbey.service': 'Türkbey Uygulaması',
    'caymaz-cameras.service': 'Kamera Servisi (GÖKKUBBE)', 'caymaz-turkbey-cameras.service': 'Kamera Servisi (Türkbey)',
    'caymaz-backup.service': 'Gece Yedeği', 'caymaz-backup.timer': 'Yedek Zamanlayıcı',
}


def _is_sysadmin(user):
    return auth.ADMIN in user['roles'] or user.get('master')


@router.get('/services')
def services(user=Depends(auth.current_user)):
    """Sistem servisleri (systemd --user) ve durumları. Yalnızca Sistem Yöneticisi / MASTER."""
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Bu bilgi yalnızca sistem yöneticisine açıktır')
    try:
        out = _sp.run(['systemctl', '--user', 'list-units', '--type=service,timer', '--all', '--plain', '--no-legend', 'caymaz*'],
                      capture_output=True, text=True, timeout=8).stdout
    except Exception as e:
        raise HTTPException(500, f'Servisler okunamadı: {e}')
    rows = []
    for line in out.splitlines():
        p = line.split()
        if not p:
            continue
        name = p[0]
        active = p[2] if len(p) > 2 else '?'
        sub = p[3] if len(p) > 3 else ''
        rows.append({'name': name, 'label': _SVC_LABELS.get(name, name), 'active': active, 'sub': sub,
                     'running': sub in ('running', 'waiting'), 'restartable': bool(_SVC_RE.match(name))})
    return rows


@router.get('/security')
def get_security(user=Depends(auth.current_user), conn=db.DB):
    """Güvenlik / şifre kuralları (Program Ayarları → Güvenlik). Yalnızca Sistem Yöneticisi / MASTER."""
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Bu ayarlar yalnızca sistem yöneticisine açıktır')
    return {'policy': policy.get(conn), 'defaults': policy.DEFAULTS}


@router.put('/security')
def put_security(body: dict = None, user=Depends(auth.current_user), conn=db.DB):
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    saved = policy.save(conn, body or {})
    db.audit(conn, user['id'], 'Güvenlik / şifre kurallarını güncelledi', 'settings', None)
    return {'policy': saved}


@router.get('/ai-usage')
def ai_usage(user=Depends(auth.current_user), conn=db.DB):
    """Yapay zeka (maskot) token kullanımı ve kişiye özel aylık kotalar. Yalnızca Sistem Yöneticisi / MASTER."""
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Bu bilgi yalnızca sistem yöneticisine açıktır')
    from . import assistant
    cfg = assistant._quota_cfg(conn)
    ym = assistant._month()
    rows = db.rows(conn.execute(
        '''SELECT u.id, u.full_name, u.username, u.photo,
                  IFNULL(SUM(CASE WHEN a.ym = ? THEN a.in_tokens + a.out_tokens END), 0) AS used_month,
                  IFNULL(SUM(a.in_tokens + a.out_tokens), 0) AS used_total
           FROM users u LEFT JOIN ai_usage a ON a.user_id = u.id
           WHERE u.deleted_at IS NULL AND u.active = 1
           GROUP BY u.id ORDER BY used_month DESC, u.full_name''', (ym,)))
    for r in rows:
        r['quota'] = assistant._quota_for(cfg, r['id'])
        r['custom'] = str(r['id']) in cfg['users']
    return {'month': ym, 'default': cfg['default'], 'model': config.AI_MODEL, 'enabled': bool(config.AI_API_KEY), 'users': rows}


@router.get('/ai-usage/{uid}')
def ai_usage_user(uid: int, user=Depends(auth.current_user), conn=db.DB):
    """Bir kullanıcının token geçmişi: bu ay / toplam, son 30 gün (günlük) ve son 12 ay (aylık)."""
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Bu bilgi yalnızca sistem yöneticisine açıktır')
    from . import assistant
    u = db.row(conn.execute('SELECT id, full_name, username, photo FROM users WHERE id = ?', (uid,)))
    if not u:
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    ym = assistant._month()
    tot = db.row(conn.execute(
        '''SELECT IFNULL(SUM(in_tokens), 0) AS in_total, IFNULL(SUM(out_tokens), 0) AS out_total, COUNT(*) AS calls,
                  IFNULL(SUM(CASE WHEN ym = ? THEN in_tokens + out_tokens END), 0) AS month,
                  IFNULL(SUM(CASE WHEN ym = ? THEN 1 END), 0) AS month_calls,
                  MIN(at) AS first_at, MAX(at) AS last_at
           FROM ai_usage WHERE user_id = ?''', (ym, ym, uid)))
    daily = db.rows(conn.execute(
        '''SELECT substr(at, 1, 10) AS d, SUM(in_tokens) AS i, SUM(out_tokens) AS o, COUNT(*) AS n
           FROM ai_usage WHERE user_id = ? AND at >= date('now', 'localtime', '-29 days')
           GROUP BY d ORDER BY d''', (uid,)))
    monthly = db.rows(conn.execute(
        '''SELECT ym AS d, SUM(in_tokens) AS i, SUM(out_tokens) AS o, COUNT(*) AS n
           FROM ai_usage WHERE user_id = ? GROUP BY ym ORDER BY ym DESC LIMIT 12''', (uid,)))[::-1]
    cfg = assistant._quota_cfg(conn)
    return {'user': u, 'month': ym, 'quota': assistant._quota_for(cfg, uid),
            'total': tot['in_total'] + tot['out_total'], **tot, 'daily': daily, 'monthly': monthly}


@router.get('/integrations')
def get_integrations(user=Depends(auth.current_user), conn=db.DB):
    """Entegrasyon ayarları (Claude API, Mikro ERP, Google, genel). Gizli değerler asla dönmez."""
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Bu ayarlar yalnızca sistem yöneticisine açıktır')
    from .. import integrations
    return {'groups': integrations.view(conn)}


class IntegrationIn(BaseModel):
    values: dict = {}
    clear: list = []


@router.put('/integrations/{group}')
def put_integrations(group: str, body: IntegrationIn, user=Depends(auth.current_user), conn=db.DB):
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    from .. import integrations
    try:
        changed = integrations.save(conn, group, body.values, body.clear)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if changed:   # değerler loglanmaz, yalnızca hangi alanların değiştiği
        db.audit(conn, user['id'], f'Entegrasyon ayarlarını güncelledi: {integrations.GROUPS[group]["title"]} ({", ".join(changed)})', 'settings', None)
    return {'groups': integrations.view(conn), 'changed': changed}


@router.get('/sync')
def sync_status(user=Depends(auth.current_user), conn=db.DB):
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    from .. import sync
    return {'sync': sync.status(conn)}


class SyncCfgIn(BaseModel):
    enabled: Optional[bool] = None
    interval: Optional[int] = None


@router.put('/sync/{group}')
def set_sync(group: str, body: SyncCfgIn, user=Depends(auth.current_user), conn=db.DB):
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    from .. import sync
    try:
        sync.set_config(conn, group, body.enabled, body.interval)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.audit(conn, user['id'], f'Otomatik senkronizasyon ayarı: {group}', 'settings', None,
             f"açık={body.enabled} aralık={body.interval}")
    return {'sync': sync.status(conn)}


@router.post('/sync/{group}/run')
async def run_sync(group: str, user=Depends(auth.current_user)):
    from fastapi.concurrency import run_in_threadpool
    from .. import sync
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    if group not in sync.JOBS:
        raise HTTPException(404, 'Bilinmeyen entegrasyon')
    ok, msg = await run_in_threadpool(sync.run, group)
    return {'ok': ok, 'message': msg}


@router.post('/integrations/{group}/test')
def test_integration(group: str, user=Depends(auth.current_user)):
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    from .. import integrations
    ok, msg = integrations.test(group)
    return {'ok': ok, 'message': msg}


class AiQuotaIn(BaseModel):
    default: int = 0
    users: dict = {}


@router.put('/ai-quota')
def set_ai_quota(body: AiQuotaIn, user=Depends(auth.current_user), conn=db.DB):
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    from . import assistant
    users = {}
    for k, v in (body.users or {}).items():
        try:
            n = max(0, int(v))
        except (TypeError, ValueError):
            continue
        if n > 0:   # 0/boş = kişiye özel kota yok (varsayılana döner)
            users[str(int(k))] = n
    data = {'default': max(0, int(body.default or 0)), 'users': users}
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (assistant.QUOTA_KEY, json.dumps(data)))
    db.audit(conn, user['id'], 'Yapay zeka kotalarını güncelledi', 'settings', None)
    return {'ok': True, **data}


@router.get('/ai-changes')
def ai_changes(user=Depends(auth.current_user), conn=db.DB):
    """Yapay zekanın önerdiği kayıt değişiklikleri (onay bekleyen + son kararlar). Yalnızca Sistem Yöneticisi / MASTER."""
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Bu bilgi yalnızca sistem yöneticisine açıktır')
    rows = db.rows(conn.execute(
        '''SELECT r.id, r.user_id, u.full_name AS user_name, r.summary, r.sql, r.status, r.created_at,
                  r.decided_at, r.note, r.affected, r.preview, du.full_name AS decided_by_name
           FROM ai_change_requests r JOIN users u ON u.id = r.user_id
           LEFT JOIN users du ON du.id = r.decided_by
           ORDER BY (r.status = 'BEKLIYOR') DESC, r.id DESC LIMIT 100'''))
    return {'items': rows, 'pending': sum(1 for r in rows if r['status'] == 'BEKLIYOR')}


def _requester(conn, uid):
    """İsteği yapan kullanıcının yetki bağlamı (yazma bu kullanıcının tablo yetkisiyle sınırlanır)."""
    u = db.row(conn.execute('SELECT id, username FROM users WHERE id = ?', (uid,)))
    if not u:
        return None
    roles = auth.user_roles(conn, uid)
    u['roles'] = roles
    u['master'] = auth.is_master(u['username'])
    u['modules'] = [*auth.MODULE_ROLES.keys()] if u['master'] else auth.allowed_modules(roles)
    return u


class DecideIn(BaseModel):
    note: str = ''


@router.post('/ai-changes/{cid}/approve')
def approve_change(cid: int, user=Depends(auth.current_user), conn=db.DB):
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    from .. import ai_query
    r = db.row(conn.execute("SELECT * FROM ai_change_requests WHERE id = ? AND status = 'BEKLIYOR'", (cid,)))
    if not r:
        raise HTTPException(404, 'Bekleyen talep bulunamadı')
    req = _requester(conn, r['user_id'])
    if not req:
        raise HTTPException(400, 'Talebi yapan kullanıcı bulunamadı')
    res = ai_query.run_write(req, r['sql'])
    now = db.now()
    if res.get('ok'):
        conn.execute("UPDATE ai_change_requests SET status = 'ONAYLANDI', decided_by = ?, decided_at = ?, affected = ? WHERE id = ?",
                     (user['id'], now, res['affected'], cid))
        db.audit(conn, user['id'], 'Yapay zeka değişikliğini onayladı ve uyguladı', 'ai_change', cid, r['summary'][:200])
        out = {'ok': True, 'affected': res['affected']}
    else:
        note = 'Yetki reddedildi (kullanıcının tablo yetkisi yok).' if res.get('denied') else res.get('error', 'Bilinmeyen hata')
        conn.execute("UPDATE ai_change_requests SET status = 'HATA', decided_by = ?, decided_at = ?, note = ? WHERE id = ?",
                     (user['id'], now, note, cid))
        out = {'ok': False, 'error': note}
    conn.commit()
    return out


@router.post('/ai-changes/{cid}/preview')
def preview_change(cid: int, user=Depends(auth.current_user), conn=db.DB):
    """Onaydan önce ön deneme: SQL çalıştırılıp geri alınır; kaç satır etkileneceği ya da hata döner."""
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    from .. import ai_query
    r = db.row(conn.execute('SELECT * FROM ai_change_requests WHERE id = ?', (cid,)))
    if not r:
        raise HTTPException(404, 'Talep bulunamadı')
    req = _requester(conn, r['user_id'])
    if not req:
        raise HTTPException(400, 'Talebi yapan kullanıcı bulunamadı')
    res = ai_query.run_write(req, r['sql'], dry_run=True)
    if res.get('ok'):
        return {'ok': True, 'affected': res['affected'], 'each': res['each']}
    return {'ok': False, 'error': 'Yetki reddedildi (kullanıcının tablo yetkisi yok).' if res.get('denied') else res.get('error')}


class EditSqlIn(BaseModel):
    sql: str


@router.put('/ai-changes/{cid}')
def edit_change(cid: int, body: EditSqlIn, user=Depends(auth.current_user), conn=db.DB):
    """Yönetici bekleyen ya da hata almış talebin SQL'ini düzeltir; ön denemeden geçerse yeniden onay bekler."""
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    from .. import ai_query
    r = db.row(conn.execute("SELECT * FROM ai_change_requests WHERE id = ? AND status IN ('BEKLIYOR', 'HATA')", (cid,)))
    if not r:
        raise HTTPException(404, 'Düzenlenebilir talep bulunamadı')
    req = _requester(conn, r['user_id'])
    sql = (body.sql or '').strip()[:8000]
    res = ai_query.run_write(req, sql, dry_run=True)
    if not res.get('ok'):
        raise HTTPException(400, 'Ön deneme başarısız: ' + ('yetki reddedildi' if res.get('denied') else res.get('error', 'hata')))
    conn.execute("UPDATE ai_change_requests SET sql = ?, status = 'BEKLIYOR', note = NULL, decided_by = NULL, decided_at = NULL, "
                 "preview = ? WHERE id = ?", (sql, json.dumps({'affected': res['affected'], 'each': res['each']}), cid))
    db.audit(conn, user['id'], 'Yapay zeka talebinin SQL\'ini düzenledi', 'ai_change', cid, r['summary'][:200])
    return {'ok': True, 'affected': res['affected']}


@router.post('/ai-changes/{cid}/reject')
def reject_change(cid: int, body: DecideIn = None, user=Depends(auth.current_user), conn=db.DB):
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    r = conn.execute("SELECT user_id, summary FROM ai_change_requests WHERE id = ? AND status = 'BEKLIYOR'", (cid,)).fetchone()
    if not r:
        raise HTTPException(404, 'Bekleyen talep bulunamadı')
    conn.execute("UPDATE ai_change_requests SET status = 'RED', decided_by = ?, decided_at = ?, note = ? WHERE id = ?",
                 (user['id'], db.now(), (body.note if body else '') or 'Reddedildi', cid))
    db.audit(conn, user['id'], 'Yapay zeka değişikliğini reddetti', 'ai_change', cid, r[1][:200])
    return {'ok': True}


@router.post('/services/{name}/restart')
def restart_service(name: str, user=Depends(auth.current_user)):
    if not _is_sysadmin(user):
        raise HTTPException(403, 'Yetkiniz yok')
    if not _SVC_RE.match(name):
        raise HTTPException(400, 'Geçersiz servis')
    try:   # gecikmeli: yanıt döndükten sonra başlatır (uygulama kendi servisini de yeniden başlatabilsin)
        _sp.Popen(['bash', '-c', f'sleep 1; systemctl --user restart {name}'])
    except Exception as e:
        raise HTTPException(500, f'Yeniden başlatılamadı: {e}')
    with db.connect() as conn:
        db.audit(conn, user['id'], 'Servisi yeniden başlattı', 'service', None, name)
    return {'ok': True}


def app_version():
    """İstemci arayüz sürümü: static (js/css) dosyalarının en yeni değişiklik zamanı. Değişince istemci 'yeni sürüm' uyarısı gösterir."""
    now = _time.time()
    if _ver['v'] is None or now - _ver['t'] > 15:
        latest = 0.0
        for sub in ('js', 'css'):
            d = config.BASE_DIR / 'static' / sub
            if d.exists():
                for p in d.rglob('*'):
                    if p.is_file():
                        latest = max(latest, p.stat().st_mtime)
        _ver['v'] = str(int(latest))
        _ver['t'] = now
    return _ver['v']
DICTATE_MAX = 30 * 1024 * 1024   # ~ 10 dk sıkıştırılmış ses
DICTATE_EXT = {'.webm', '.ogg', '.oga', '.opus', '.mp4', '.m4a', '.mp3', '.wav', '.aac'}


@router.post('/dictate')
async def dictate(file: UploadFile, lang: str = 'tr', user=Depends(auth.current_user)):
    """Sesle yazdırma: kayıt → düz metin (varsayılan dil Türkçe)."""
    if not document_media.whisper_available():
        raise HTTPException(503, 'Konuşma tanıma bu sunucuda kurulu değil')
    ext = Path(file.filename or 'a.webm').suffix.lower() or '.webm'
    if ext not in DICTATE_EXT:
        raise HTTPException(400, 'Desteklenmeyen ses biçimi')
    if lang not in ('tr', 'en', 'auto'):
        raise HTTPException(400, 'Geçersiz dil')
    data = await file.read(DICTATE_MAX + 1)
    if len(data) > DICTATE_MAX:
        raise HTTPException(400, 'Kayıt çok uzun')
    if not data:
        raise HTTPException(400, 'Kayıt boş')

    def run():
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f'dikte{ext}'
            path.write_bytes(data)
            try:
                return document_media.transcribe(path, lang=lang, stamps=False)
            except Exception as exc:
                raise HTTPException(400, 'Ses çözülemedi; kaydı yeniden deneyin') from exc

    text, seconds = await run_in_threadpool(run)
    return {'text': text, 'seconds': round(seconds or 0, 1)}


@router.get('/status')
def status(since: int = 0, user=Depends(auth.current_user), conn=db.DB):
    now = datetime.now()
    rows = conn.execute(
        '''SELECT id, IFNULL(json_extract(prefs, '$.settings.privacy.hide_online'), 0) FROM users WHERE active = 1 AND last_seen >= ? AND EXISTS (
               SELECT 1 FROM sessions s WHERE s.user_id = users.id AND s.expires_at > ?)''',
        ((now - ONLINE_WINDOW).isoformat(timespec='seconds'), now.isoformat(timespec='seconds'))).fetchall()
    active = len(rows)
    admin = auth.ADMIN in user['roles']
    # Çevrimiçi olan / ayrılan kullanıcı sesi için kimlikler (kendisi ve çevrimiçi durumunu gizleyenler hariç; yönetici hepsini görür)
    online_ids = sorted(r[0] for r in rows if r[0] != user['id'] and (admin or not r[1]))
    snap = sysstat.snapshot()
    snap['history'] = [p for p in snap['history'] if p['t'] > since]   # istemci yalnızca yeni örnekleri alır
    from .. import changelog
    return {'active_users': active, 'online_ids': online_ids, 'build': app_version(), 'version': changelog.VERSION, **snap}


@router.get('/about')
def about(user=Depends(auth.current_user)):
    """Program Hakkında: sürüm numarası ve değişiklik geçmişi (tarihçe)."""
    from .. import changelog
    return {'version': changelog.VERSION, 'entries': changelog.CHANGELOG}


@router.get('/details')
def details(what: str, user=Depends(auth.current_user), conn=db.DB):
    """Durum çubuğu ayrıntı kutucukları: çevrimiçi kullanıcılar, disk ve sunucu. Sayfa ve dosya dökümü yalnızca yöneticiye."""
    admin = auth.ADMIN in user['roles']
    now = datetime.now()
    if what == 'users':
        rows = db.rows(conn.execute(
            '''SELECT id, full_name, photo, last_seen FROM users u WHERE active = 1 AND last_seen >= ? AND EXISTS (
                   SELECT 1 FROM sessions s WHERE s.user_id = u.id AND s.expires_at > ?)
                   AND (? OR u.id = ? OR IFNULL(json_extract(u.prefs, '$.settings.privacy.hide_online'), 0) = 0)
               ORDER BY full_name''',   # çevrimiçi durumunu gizleyen yalnızca yöneticiye görünür
            ((now - ONLINE_WINDOW).isoformat(timespec='seconds'), now.isoformat(timespec='seconds'), admin, user['id'])))
        for u in rows:
            u['roles'] = auth.user_roles(conn, u['id'])
            u['seconds_ago'] = int((now - datetime.fromisoformat(u['last_seen'])).total_seconds())
            if admin:
                r = conn.execute("SELECT detail FROM audit_logs WHERE user_id = ? AND action = 'Sayfaya girdi' ORDER BY id DESC LIMIT 1",
                                 (u['id'],)).fetchone()
                u['page'] = r[0] if r else None
        today = now.date().isoformat()
        return {'me': user['id'], 'users': rows, 'logins_today': conn.execute('SELECT COUNT(DISTINCT user_id) FROM login_logs WHERE success = 1 AND at >= ?',
                                                             (today,)).fetchone()[0]}
    if what == 'disk':
        snap = sysstat.snapshot()
        out = {k: snap.get(k) for k in ('disk_total', 'disk_used', 'disk_free')}
        if admin:
            from .admin import _cached, _storage
            dbp = Path(config.DB_PATH)
            out.update(_cached('storage', 60, _storage))
            out['db_size'] = dbp.stat().st_size if dbp.exists() else 0
        return out
    if what == 'server':
        import os
        snap = sysstat.snapshot()
        try:
            uptime = float(Path('/proc/uptime').read_text().split()[0])
        except Exception:
            uptime = None
        return {**snap, 'cpus': os.cpu_count(), 'load': os.getloadavg(), 'uptime_s': uptime}
    raise HTTPException(400, 'Geçersiz istek')
