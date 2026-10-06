"""KVKK uyum çekirdeği: açık rıza kayıtları (biyometrik yüz + ses-izi — özel nitelikli veri), veri sahibi
başvuruları (erişim/silme/itiraz, md. 11) ve saklama süresi temizliği. Rıza modeli DENETİM (audit) modudur:
canlı tanıma çalışmaya devam eder, bu modül rıza durumunu kaydeder/raporlar; 'biometric_enforce' açılırsa
rızasız kişiler için işleme ileride engellenebilir. Ayarlar app_kv['kvkk'] altında JSON olarak tutulur.
"""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

from . import db

KV = 'kvkk'
DEFAULTS = {
    'biometric_enforce': 0,          # 0 = denetim modu (engellemez), 1 = rızasız kişide biyometriyi işleme
    'retention_sightings_days': 90,  # kamera görülme kayıtları
    'retention_audio_days': 90,      # görüşme ses kayıtları
    'retention_audit_days': 365,     # giriş/işlem (audit) kayıtları
}
CONSENT_KINDS = ('biometric', 'voice')
REQUEST_KINDS = ('export', 'delete', 'object')


def settings(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KV,)).fetchone()
    data = {}
    if row:
        try:
            data = json.loads(row[0]) or {}
        except (ValueError, TypeError):
            data = {}
    return {**DEFAULTS, **data}


def save_settings(conn, patch):
    cur = settings(conn)
    for k in DEFAULTS:
        if k in patch and patch[k] is not None:
            cur[k] = int(patch[k])
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (KV, json.dumps(cur)))
    return cur


# ---------------- açık rıza ----------------
def set_consent(conn, kind, subject_type, subject_id, granted, by_user=None, note=None):
    if kind not in CONSENT_KINDS:
        raise ValueError('geçersiz rıza türü')
    conn.execute(
        '''INSERT INTO kvkk_consent (kind, subject_type, subject_id, granted, note, by_user, updated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(kind, subject_type, subject_id)
           DO UPDATE SET granted = excluded.granted, note = excluded.note, by_user = excluded.by_user, updated_at = excluded.updated_at''',
        (kind, subject_type, int(subject_id), int(bool(granted)), note, by_user, db.now()))


def has_consent(conn, kind, subject_type, subject_id):
    r = conn.execute('SELECT granted FROM kvkk_consent WHERE kind = ? AND subject_type = ? AND subject_id = ?',
                     (kind, subject_type, int(subject_id))).fetchone()
    return bool(r and r[0])


def biometric_status(conn):
    """Denetim raporu: yüz tanımaya atanmış özneler ve her biri için açık rıza var mı. Rızasızları öne çıkarır."""
    rows = db.rows(conn.execute('''SELECT person_id, user_id, family_id, visitor_id FROM face_groups
                                   WHERE person_id IS NOT NULL OR user_id IS NOT NULL OR family_id IS NOT NULL OR visitor_id IS NOT NULL'''))
    subjects = {}
    for r in rows:
        for col, st in (('user_id', 'user'), ('person_id', 'person'), ('family_id', 'family'), ('visitor_id', 'visitor')):
            if r.get(col):
                subjects[(st, r[col])] = True
    out = []
    for (st, sid) in subjects:
        out.append({'subject_type': st, 'subject_id': sid, 'consent': has_consent(conn, 'biometric', st, sid)})
    missing = sum(1 for s in out if not s['consent'])
    return {'enrolled': len(out), 'missing_consent': missing, 'subjects': out}


# ---------------- veri sahibi başvuruları (md. 11) ----------------
def create_request(conn, user_id, kind, note=None):
    if kind not in REQUEST_KINDS:
        raise ValueError('geçersiz başvuru türü')
    cur = conn.execute('INSERT INTO kvkk_requests (user_id, kind, note, status, created_at) VALUES (?,?,?,?,?)',
                       (user_id, kind, (note or '').strip()[:2000], 'open', db.now()))
    db.audit(conn, user_id, 'KVKK veri başvurusu oluşturdu', 'kvkk_request', cur.lastrowid, kind)
    return cur.lastrowid


def list_requests(conn, status=None):
    q = '''SELECT r.*, u.full_name AS user_name, u.username AS user_username, h.full_name AS handler_name
           FROM kvkk_requests r JOIN users u ON u.id = r.user_id LEFT JOIN users h ON h.id = r.handled_by'''
    args = ()
    if status:
        q += ' WHERE r.status = ?'
        args = (status,)
    q += ' ORDER BY r.created_at DESC'
    return db.rows(conn.execute(q, args))


def handle_request(conn, req_id, handler_id, resolution=None):
    conn.execute('UPDATE kvkk_requests SET status = ?, handled_by = ?, handled_at = ?, resolution = ? WHERE id = ?',
                 ('handled', handler_id, db.now(), (resolution or '').strip()[:2000], req_id))
    db.audit(conn, handler_id, 'KVKK veri başvurusunu kapattı', 'kvkk_request', req_id, resolution or '')


# ---------------- saklama süresi temizliği ----------------
def _cutoff_iso(days):
    return (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat(timespec='seconds')


def _safe_unlink(path):
    """Yalnız veri klasörü altındaki dosyayı sil (yanlış dosya silinmesin)."""
    if not path:
        return
    try:
        from . import config
        base = config.DATA_DIR.resolve()
        for cand in (config.DATA_DIR / path, config.UPLOAD_DIR / path, base / path):
            p = cand.resolve()
            if base in p.parents and p.is_file():
                p.unlink()
                return
    except Exception:   # noqa: BLE001 — temizlik en-iyi-çaba
        pass


def purge_retention(conn):
    """Saklama süresi dolan kayıtları siler. Günlük çağrılır. Dönen sayılar denetim için."""
    s = settings(conn)
    counts = {}
    # Kamera görülme kayıtları (biyometrik) — dosyalarıyla
    cut = _cutoff_iso(s['retention_sightings_days'])
    old = db.rows(conn.execute('SELECT id, crop, frame, clip FROM face_sightings WHERE at < ?', (cut,)))
    for r in old:
        for col in ('crop', 'frame', 'clip'):
            _safe_unlink(r.get(col))
    conn.execute('DELETE FROM face_sightings WHERE at < ?', (cut,))
    counts['face_sightings'] = len(old)
    # Görüşme ses kayıtları — dosyalarıyla + segmentleri
    cut = _cutoff_iso(s['retention_audio_days'])
    auds = db.rows(conn.execute('SELECT id, call_id, file, wav FROM voice_call_audio WHERE started_at < ?', (cut,)))
    call_ids = {a['call_id'] for a in auds if a.get('call_id')}
    for a in auds:
        _safe_unlink(a.get('file'))
        _safe_unlink(a.get('wav'))
    conn.execute('DELETE FROM voice_call_audio WHERE started_at < ?', (cut,))
    for cid in call_ids:
        if not conn.execute('SELECT 1 FROM voice_call_audio WHERE call_id = ?', (cid,)).fetchone():
            conn.execute('DELETE FROM voice_call_segments WHERE call_id = ?', (cid,))
    counts['voice_call_audio'] = len(auds)
    # Giriş/işlem kayıtları
    cut = _cutoff_iso(s['retention_audit_days'])
    counts['audit_logs'] = conn.execute('DELETE FROM audit_logs WHERE at < ?', (cut,)).rowcount
    counts['login_logs'] = conn.execute('DELETE FROM login_logs WHERE at < ?', (cut,)).rowcount
    conn.commit()
    return counts


# ---------------- günlük zamanlayıcı ----------------
_started = False


def _loop():
    time.sleep(120)   # açılışta servisler otursun
    while True:
        try:
            with db.connect() as conn:
                purge_retention(conn)
        except Exception:   # noqa: BLE001 — temizlik en-iyi-çaba
            pass
        time.sleep(24 * 3600)


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name='kvkk-retention').start()
