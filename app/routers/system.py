"""Alt durum çubuğu (aktif kullanıcı sayısı, sunucu durumu) ve sesle yazdırma (dikte).

Dikte: metin kutusundaki mikrofon düğmesiyle kaydedilen kısa ses bu sunucudaki Whisper ile metne çevrilir
(ses dışarı gönderilmez, kaydedilmez; geçici dosya hemen silinir).
"""
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import auth, config, db, document_media, sysstat
from .admin import ONLINE_WINDOW

router = APIRouter(prefix='/api/system')
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
    return {'active_users': active, 'online_ids': online_ids, **snap}


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
