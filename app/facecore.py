"""Yüz tanıma çekirdek işlemleri — HEM bulutta HEM fabrikada aynı kodla çalışır.

Dağıtık kurulumda (AGENT_MODE=remote) yüz tanıma motoru (camera_service) FABRİKADA çalışır ve görülmeleri/klipleri
fabrikanın YEREL veritabanına + dosyalarına yazar (KVKK: biyometrik veri ve video lokalde kalır). Bulut bu verileri
ajan üzerinden çeker: `face.rpc` op'u bu modülün fonksiyonlarını fabrika yerel bağlantısıyla çalıştırır, `face.media`
ise kırpık/kare/klip dosyasını getirir. Yerel (tek makine) kurulumda router doğrudan bu fonksiyonları çağırır.

Bulut → fabrika yönünde `push_config` ile NVR kimlik bilgileri, kanal/zamanlama, vardiya ve eğitim izleri (face_enroll)
fabrikaya aktarılır; camera_service bunları yerel DB'den okuyarak çalışır."""
import base64
import json

import numpy as np

from . import config, db
from .document_media import _norm


class NotFound(Exception):
    pass


GROUP_SELECT = '''SELECT g.id, g.person_id, g.user_id, g.samples, g.best_crop, g.first_seen, g.last_seen, g.assigned_at,
       u.full_name AS user_name, p.full_name AS person_name, pc.name AS person_company, c.name AS last_camera_name,
       (SELECT COUNT(*) FROM face_sightings s WHERE s.group_id = g.id) AS sightings,
       (SELECT group_concat(DISTINCT cc.name) FROM face_sightings s JOIN cameras cc ON cc.id = s.camera_id WHERE s.group_id = g.id) AS cameras
FROM face_groups g LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people p ON p.id = g.person_id
LEFT JOIN companies pc ON pc.id = p.company_id LEFT JOIN cameras c ON c.id = g.last_camera'''


def groups(conn, state='unknown'):
    where = 'g.person_id IS NULL AND g.user_id IS NULL' if state == 'unknown' else 'g.person_id IS NOT NULL OR g.user_id IS NOT NULL'
    return db.rows(conn.execute(GROUP_SELECT + f' WHERE {where} ORDER BY g.last_seen DESC LIMIT 500'))


def group(conn, gid):
    g = db.row(conn.execute(GROUP_SELECT + ' WHERE g.id = ?', (gid,)))
    if not g:
        raise NotFound('Yüz grubu bulunamadı')
    g['items'] = db.rows(conn.execute(
        '''SELECT s.id, s.at, s.crop, s.frame, s.clip, s.score, c.name AS camera_name FROM face_sightings s
           LEFT JOIN cameras c ON c.id = s.camera_id WHERE s.group_id = ? ORDER BY s.at DESC LIMIT 400''', (gid,)))
    return g


def _merge(conn, target, sources):
    rows = {r['id']: r for r in db.rows(conn.execute(
        f'SELECT * FROM face_groups WHERE id IN ({",".join("?" * (len(sources) + 1))})', (target, *sources)))}
    if target not in rows or any(s not in rows for s in sources):
        raise NotFound('Yüz grubu bulunamadı')
    acc = np.zeros(128, np.float32)
    for r in rows.values():
        acc += np.frombuffer(r['centroid'], dtype=np.float32) * max(1, r['samples'])
    best = max(rows.values(), key=lambda r: r['best_score'])
    conn.execute(f'UPDATE face_sightings SET group_id = ? WHERE group_id IN ({",".join("?" * len(sources))})', (target, *sources))
    conn.execute('''UPDATE face_groups SET centroid = ?, samples = ?, best_crop = ?, best_score = ?, first_seen = ?, last_seen = ?
                    WHERE id = ?''',
                 (_norm(acc).astype(np.float32).tobytes(), sum(r['samples'] for r in rows.values()), best['best_crop'], best['best_score'],
                  min(r['first_seen'] for r in rows.values()), max(r['last_seen'] for r in rows.values()), target))
    conn.execute(f'DELETE FROM face_groups WHERE id IN ({",".join("?" * len(sources))})', sources)


def assign(conn, gid, user_id, person_id, by, validate=True):
    if bool(user_id) == bool(person_id):
        raise ValueError('Bir kullanıcı ya da firma kişisi seçin')
    # Dağıtık kurulumda kullanıcı/kişi varlığı BULUTTA doğrulanır (fabrika DB'si eski olabilir); validate=False gelir.
    if validate and user_id and not conn.execute('SELECT 1 FROM users WHERE id = ?', (user_id,)).fetchone():
        raise ValueError('Kullanıcı bulunamadı')
    if validate and person_id and not conn.execute('SELECT 1 FROM company_people WHERE id = ?', (person_id,)).fetchone():
        raise ValueError('Kişi bulunamadı')
    if not conn.execute('SELECT 1 FROM face_groups WHERE id = ?', (gid,)).fetchone():
        raise NotFound('Yüz grubu bulunamadı')
    col, val = ('user_id', user_id) if user_id else ('person_id', person_id)
    existing = conn.execute(f'SELECT id FROM face_groups WHERE {col} = ? AND id != ? ORDER BY samples DESC LIMIT 1', (val, gid)).fetchone()
    target = existing[0] if existing else gid
    if existing:
        _merge(conn, target, [gid])
    conn.execute('UPDATE face_groups SET person_id = ?, user_id = ?, assigned_by = ?, assigned_at = ? WHERE id = ?',
                 (person_id, user_id, by, db.now(), target))
    return {'id': target}


def merge(conn, ids):
    ids = list(dict.fromkeys(ids))
    if len(ids) < 2:
        raise ValueError('En az iki grup seçin')
    _merge(conn, ids[0], ids[1:])
    return {'id': ids[0]}


def unassign(conn, gid):
    conn.execute('UPDATE face_groups SET person_id = NULL, user_id = NULL, assigned_by = NULL, assigned_at = NULL WHERE id = ?', (gid,))
    return {'ok': True}


def delete_group(conn, gid):
    files = [r[0] for r in conn.execute('SELECT crop FROM face_sightings WHERE group_id = ? UNION SELECT frame FROM face_sightings WHERE group_id = ? '
                                        'UNION SELECT clip FROM face_sightings WHERE group_id = ? UNION SELECT best_crop FROM face_groups WHERE id = ?',
                                        (gid, gid, gid, gid)) if r[0]]
    conn.execute('DELETE FROM face_groups WHERE id = ?', (gid,))
    for f in files:
        (config.UPLOAD_DIR / f).unlink(missing_ok=True)
    return {'ok': True, 'files': len(files)}


def recent(conn):
    return db.rows(conn.execute(
        '''SELECT s.id, s.at, s.crop, s.frame, s.clip, c.name AS camera_name, g.id AS group_id, g.user_id, g.person_id,
                  u.full_name AS user_name, p.full_name AS person_name, pc.name AS person_company
           FROM face_sightings s JOIN face_groups g ON g.id = s.group_id LEFT JOIN cameras c ON c.id = s.camera_id
           LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people p ON p.id = g.person_id LEFT JOIN companies pc ON pc.id = p.company_id
           WHERE g.user_id IS NOT NULL OR g.person_id IS NOT NULL ORDER BY s.at DESC LIMIT 200'''))


def events(conn, date_from, date_to, kind='known', limit=500):
    where = "s.at >= ? AND s.at < ?"
    args = [date_from, date_to + '~']
    if kind == 'known':
        where += " AND (g.user_id IS NOT NULL OR g.person_id IS NOT NULL)"
    return {'events': db.rows(conn.execute(
        f'''SELECT s.id, s.at, s.crop, s.frame, s.clip, s.score, c.name AS camera_name, g.id AS group_id, g.user_id, g.person_id,
                   u.full_name AS user_name, p.full_name AS person_name, pc.name AS person_company
            FROM face_sightings s JOIN face_groups g ON g.id = s.group_id LEFT JOIN cameras c ON c.id = s.camera_id
            LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people p ON p.id = g.person_id
            LEFT JOIN companies pc ON pc.id = p.company_id
            WHERE {where} ORDER BY s.at DESC LIMIT ?''', (*args, min(limit, 2000))))}


def overlays(conn, ids):
    """Canlı çerçeve metadata'sı (yüz kutuları + kimlik) — izleme ekranı overlay'i. live/<cid>.json'dan, bayatları atar."""
    import json as _json
    import time
    live = config.DATA_DIR / 'cameras' / 'live'
    now, out = time.time(), {}
    for cid in ids or []:
        p = live / f'{int(cid)}.json'
        if not p.is_file():
            continue
        try:
            d = _json.loads(p.read_text())
        except Exception:   # noqa: BLE001
            continue
        if now - d.get('ts', 0) > 6:   # 6 sn'den eski → kamera o an yüz görmüyor
            continue
        out[str(int(cid))] = d.get('boxes', [])
    return {'overlays': out}


def cameras_list(conn):
    """Kamera listesi (şifre hariç) — Kameralar sekmesi. Canlı kare yaşı yerel live dizininden."""
    import time
    from . import cameras as camlib
    live_dir = config.DATA_DIR / 'cameras' / 'live'
    rows = db.rows(conn.execute('SELECT id, name, ip, location, status, error, last_frame_at, faces, active, stream_url FROM cameras ORDER BY name COLLATE NOCASE, id'))
    for r in rows:
        r['stream_url'] = camlib.mask(r.get('stream_url'))
        r['has_password'] = bool(r.get('stream_url'))
        live = live_dir / f'{r["id"]}.jpg'
        r['live_age'] = round(time.time() - live.stat().st_mtime, 1) if live.exists() else None
    return rows


# ---- Bulut → fabrika yapılandırma aktarımı (push_config) ----
def push_config(conn, cfg):
    """Fabrika-yerel: NVR kimlik bilgileri + kanal/zamanlama + vardiya + eğitim izleri yerel DB'ye yazılır.
    camera_service bunları okuyarak çalışır. Eğitim izleri (embedding) yalnızca eşleştirme için; kırpık bulutta kalır."""
    from . import nvr
    nv = cfg.get('nvr') or {}
    for k, attr in (('host', 'NVR_HOST'), ('user', 'NVR_USER'), ('password', 'NVR_PASSWORD')):
        if nv.get(k) is not None:
            setattr(config, attr, nv[k])
    if nv.get('port'):
        config.NVR_PORT = int(nv['port'])
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', ('nvr_channels', json.dumps(cfg.get('channels') or {})))
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', ('shift_config', json.dumps(cfg.get('shift') or {})))
    if cfg.get('facerec') is not None:
        conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', ('facerec_config', json.dumps(cfg.get('facerec'))))
    # Eğitim izleri (bulut face_enroll aynası) — eşleştirme için embedding yeterli; kırpık yer tutucu
    conn.execute('DELETE FROM face_enroll')
    n = 0
    for e in cfg.get('enroll') or []:
        emb = base64.b64decode(e['embedding'])
        conn.execute('''INSERT INTO face_enroll (subject_type, user_id, person_id, crop, embedding, created_at)
                        VALUES (?,?,?,?,?,?)''',
                     (e['subject_type'], e.get('user_id'), e.get('person_id'), '(bulut)', emb, db.now()))
        n += 1
    cams = nvr.sync_cameras(conn)   # yüz tanıma açık kanalları kamera listesine köprüle
    conn.commit()
    return {'ok': True, 'enroll': n, 'cameras': cams, 'channels': len(cfg.get('channels') or {})}


def rpc(conn, method, args):
    """face.rpc dağıtıcısı: bulutun istediği yüz işlemini yerel bağlantıyla çalıştırır."""
    a = args or {}
    if method == 'groups':
        return groups(conn, a.get('state', 'unknown'))
    if method == 'group':
        return group(conn, a['gid'])
    if method == 'assign':
        return assign(conn, a['gid'], a.get('user_id'), a.get('person_id'), a.get('by'), a.get('validate', True))
    if method == 'merge':
        return merge(conn, a['ids'])
    if method == 'unassign':
        return unassign(conn, a['gid'])
    if method == 'delete_group':
        return delete_group(conn, a['gid'])
    if method == 'recent':
        return recent(conn)
    if method == 'events':
        return events(conn, a['date_from'], a['date_to'], a.get('kind', 'known'), a.get('limit', 500))
    if method == 'cameras_list':
        return cameras_list(conn)
    if method == 'overlays':
        return overlays(conn, a.get('ids') or [])
    if method == 'push_config':
        return push_config(conn, a.get('cfg') or {})
    raise ValueError(f'Bilinmeyen yüz işlemi: {method}')


def media_bytes(path):
    """Güvenli dosya okuma: yalnızca UPLOAD_DIR / DATA_DIR altındaki kamera medyası (kırpık/kare/klip)."""
    import os
    base = config.UPLOAD_DIR
    full = (base / path).resolve()
    if not str(full).startswith(str(base.resolve())) or not full.is_file():
        # canlı kare DATA_DIR/cameras/live altında olabilir
        live = (config.DATA_DIR / path).resolve()
        if str(live).startswith(str((config.DATA_DIR).resolve())) and live.is_file():
            full = live
        else:
            raise NotFound('Dosya yok')
    data = full.read_bytes()
    ext = os.path.splitext(full.name)[1].lower()
    ctype = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.mp4': 'video/mp4'}.get(ext, 'application/octet-stream')
    return {'b64': base64.b64encode(data).decode(), 'content_type': ctype}
