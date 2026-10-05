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


ENROLL_CAP = 8   # bir atamadan eğitime en çok bu kadar yüz aktarılır (eğitim verisini şişirmemek için)


def _select_diverse(rows, cap=ENROLL_CAP, sim_max=0.95):
    """Eğitime aktarılacak görülmeleri seçer: en yüksek skorlu + birbirine çok benzemeyen (çeşitli) en çok `cap` adet.
    Neredeyse aynı kare (kosinüs > sim_max) atlanır; embedding/kırpığı eksik satırlar elenir."""
    ranked = sorted(rows, key=lambda r: r.get('score') or 0, reverse=True)
    picked, vecs = [], []
    for r in ranked:
        emb, crop = r.get('embedding'), r.get('crop')
        if not emb or not crop:
            continue
        v = _norm(np.frombuffer(emb, dtype=np.float32).astype(np.float32))
        if any(float(np.dot(v, p)) > sim_max for p in vecs):
            continue
        picked.append(r)
        vecs.append(v)
        if len(picked) >= cap:
            break
    return picked


def _enroll_payload(rows):
    """Atanan görülmelerin eğitim yükü: merkezin YENİDEN TESPİT olmadan enroll edebilmesi için
    [{embedding: base64(128 float32 bayt), crop: dosya yolu, score}]. Embedding ajan sınırında base64 ile taşınır
    (push_config / push ile aynı biçim)."""
    out = []
    for r in _select_diverse(rows):
        out.append({'embedding': base64.b64encode(r['embedding']).decode(),
                    'crop': r['crop'], 'score': r.get('score') or 0})
    return out


GROUP_SELECT = '''SELECT g.id, g.person_id, g.user_id, g.family_id, g.visitor_id, g.samples, g.best_crop, g.first_seen, g.last_seen, g.assigned_at,
       u.full_name AS user_name, p.full_name AS person_name, pc.name AS person_company, fm.full_name AS family_name, vz.full_name AS visitor_name,
       vz.company AS visitor_company, c.name AS last_camera_name,
       (SELECT COUNT(*) FROM face_sightings s WHERE s.group_id = g.id) AS sightings,
       (SELECT group_concat(DISTINCT cc.name) FROM face_sightings s JOIN cameras cc ON cc.id = s.camera_id WHERE s.group_id = g.id) AS cameras
FROM face_groups g LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people p ON p.id = g.person_id
LEFT JOIN companies pc ON pc.id = p.company_id LEFT JOIN family_members fm ON fm.id = g.family_id
LEFT JOIN visitors vz ON vz.id = g.visitor_id LEFT JOIN cameras c ON c.id = g.last_camera'''


def groups(conn, state='unknown'):
    where = ('g.person_id IS NULL AND g.user_id IS NULL AND g.family_id IS NULL AND g.visitor_id IS NULL' if state == 'unknown'
             else 'g.person_id IS NOT NULL OR g.user_id IS NOT NULL OR g.family_id IS NOT NULL OR g.visitor_id IS NOT NULL')
    return db.rows(conn.execute(GROUP_SELECT + f' WHERE {where} ORDER BY g.last_seen DESC LIMIT 500'))


def group(conn, gid):
    g = db.row(conn.execute(GROUP_SELECT + ' WHERE g.id = ?', (gid,)))
    if not g:
        raise NotFound('Yüz grubu bulunamadı')
    g['items'] = db.rows(conn.execute(
        '''SELECT s.id, s.at, s.crop, s.frame, s.clip, s.score, s.threshold, c.name AS camera_name FROM face_sightings s
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


def assign(conn, gid, user_id, person_id, by, validate=True, family_id=None, visitor_id=None):
    if sum(bool(x) for x in (user_id, person_id, family_id, visitor_id)) != 1:
        raise ValueError('Bir kullanıcı, firma kişisi, aile üyesi ya da ziyaretçi seçin')
    # Dağıtık kurulumda varlık BULUTTA doğrulanır (fabrika DB'si eski olabilir); validate=False gelir.
    if validate and user_id and not conn.execute('SELECT 1 FROM users WHERE id = ?', (user_id,)).fetchone():
        raise ValueError('Kullanıcı bulunamadı')
    if validate and person_id and not conn.execute('SELECT 1 FROM company_people WHERE id = ?', (person_id,)).fetchone():
        raise ValueError('Kişi bulunamadı')
    if validate and family_id and not conn.execute('SELECT 1 FROM family_members WHERE id = ?', (family_id,)).fetchone():
        raise ValueError('Aile üyesi bulunamadı')
    if validate and visitor_id and not conn.execute('SELECT 1 FROM visitors WHERE id = ?', (visitor_id,)).fetchone():
        raise ValueError('Ziyaretçi bulunamadı')
    if not conn.execute('SELECT 1 FROM face_groups WHERE id = ?', (gid,)).fetchone():
        raise NotFound('Yüz grubu bulunamadı')
    # Atanan grubun görülmelerini eğitime aktarmak için — birleşmeden ÖNCE, yalnız bu grubun yüzleri (en iyi N / çeşitli)
    enroll_rows = db.rows(conn.execute('SELECT crop, embedding, score FROM face_sightings WHERE group_id = ?', (gid,)))
    col, val = (('user_id', user_id) if user_id else ('person_id', person_id) if person_id
                else ('family_id', family_id) if family_id else ('visitor_id', visitor_id))
    existing = conn.execute(f'SELECT id FROM face_groups WHERE {col} = ? AND id != ? ORDER BY samples DESC LIMIT 1', (val, gid)).fetchone()
    target = existing[0] if existing else gid
    if existing:
        _merge(conn, target, [gid])
    conn.execute('UPDATE face_groups SET person_id = ?, user_id = ?, family_id = ?, visitor_id = ?, assigned_by = ?, assigned_at = ? WHERE id = ?',
                 (person_id, user_id, family_id, visitor_id, by, db.now(), target))
    return {'id': target, 'enroll_faces': _enroll_payload(enroll_rows)}


def merge(conn, ids):
    ids = list(dict.fromkeys(ids))
    if len(ids) < 2:
        raise ValueError('En az iki grup seçin')
    _merge(conn, ids[0], ids[1:])
    return {'id': ids[0]}


def unassign(conn, gid):
    conn.execute('UPDATE face_groups SET person_id = NULL, user_id = NULL, family_id = NULL, visitor_id = NULL, assigned_by = NULL, assigned_at = NULL WHERE id = ?', (gid,))
    return {'ok': True}


def delete_group(conn, gid):
    files = [r[0] for r in conn.execute('SELECT crop FROM face_sightings WHERE group_id = ? UNION SELECT frame FROM face_sightings WHERE group_id = ? '
                                        'UNION SELECT clip FROM face_sightings WHERE group_id = ? UNION SELECT best_crop FROM face_groups WHERE id = ?',
                                        (gid, gid, gid, gid)) if r[0]]
    cen = conn.execute('SELECT centroid FROM face_groups WHERE id = ?', (gid,)).fetchone()
    if cen and cen[0]:   # bu yüze benzeyen yeni görülmeler tekrar listeye alınmaz
        conn.execute('INSERT INTO face_ignored (centroid, created_at) VALUES (?, ?)', (cen[0], db.now()))
    conn.execute('DELETE FROM face_groups WHERE id = ?', (gid,))
    for f in files:
        (config.UPLOAD_DIR / f).unlink(missing_ok=True)
    return {'ok': True, 'files': len(files)}


def delete_sighting(conn, sid):
    """Bir gruptan tek bir görülme (resim) çıkarır — kalanlar kalır. Grup boşalırsa grubu da siler."""
    row = conn.execute('SELECT crop, frame, clip, group_id FROM face_sightings WHERE id = ?', (sid,)).fetchone()
    if not row:
        raise NotFound('Görülme bulunamadı')
    conn.execute('DELETE FROM face_sightings WHERE id = ?', (sid,))
    for f in (row[0], row[1], row[2]):
        if f:
            (config.UPLOAD_DIR / f).unlink(missing_ok=True)
    left = conn.execute('SELECT COUNT(*) FROM face_sightings WHERE group_id = ?', (row[3],)).fetchone()[0]
    if left == 0:   # grupta görülme kalmadı → grubu kaldır
        conn.execute('DELETE FROM face_groups WHERE id = ?', (row[3],))
    return {'ok': True, 'group_id': row[3], 'left': left}


def _sighting_rows(conn, ids):
    """Seçili görülme satırları (geçersiz / yinelenen id'ler elenir)."""
    ids = [int(i) for i in dict.fromkeys(ids or [])]
    if not ids:
        raise ValueError('Görülme seçin')
    rows = db.rows(conn.execute(
        f'SELECT id, group_id, camera_id, at, crop, frame, clip, embedding, score FROM face_sightings '
        f'WHERE id IN ({",".join("?" * len(ids))})', ids))
    if not rows:
        raise NotFound('Görülme bulunamadı')
    return rows


def _recompute_group(conn, gid):
    """Grubun özetini (centroid, samples, best_crop, first/last) KALAN görülmelerinden yeniden hesaplar.
    Görülme kalmazsa grubu siler. Döner: kalan görülme sayısı."""
    rows = db.rows(conn.execute('SELECT at, crop, embedding, score FROM face_sightings WHERE group_id = ?', (gid,)))
    if not rows:
        conn.execute('DELETE FROM face_groups WHERE id = ?', (gid,))
        return 0
    acc = np.zeros(128, np.float32)
    for r in rows:
        acc += np.frombuffer(r['embedding'], dtype=np.float32)
    best = max(rows, key=lambda r: r['score'] or 0)
    ats = [r['at'] for r in rows]
    conn.execute('''UPDATE face_groups SET centroid = ?, samples = ?, best_crop = ?, best_score = ?, first_seen = ?, last_seen = ?
                    WHERE id = ?''',
                 (_norm(acc).astype(np.float32).tobytes(), len(rows), best['crop'], best['score'] or 0, min(ats), max(ats), gid))
    return len(rows)


def delete_sightings(conn, ids):
    """Birden çok görülmeyi (resmi) toplu siler; kaynak grupların özeti kalanlardan yeniden hesaplanır,
    boşalan grup silinir. Döner: {ok, deleted, left} (left: dokunulan gruplarda kalan görülme sayısı)."""
    rows = _sighting_rows(conn, ids)
    gids = {r['group_id'] for r in rows}
    files = [f for r in rows for f in (r['crop'], r['frame'], r['clip'])]
    conn.execute(f'DELETE FROM face_sightings WHERE id IN ({",".join("?" * len(rows))})', [r['id'] for r in rows])
    left = sum(_recompute_group(conn, gid) for gid in gids)
    for f in files:
        if f:
            (config.UPLOAD_DIR / f).unlink(missing_ok=True)
    return {'ok': True, 'deleted': len(rows), 'left': left}


def assign_sightings(conn, ids, user_id, person_id, by, validate=True, family_id=None, visitor_id=None):
    """Seçili görülmeleri mevcut gruplarından ÇIKARIP yalnız onlardan yeni bir grup oluşturur ve o grubu kişiye atar
    (kişinin grubu zaten varsa `assign` ile birleşir). Kaynak gruplar kalanlardan yeniden hesaplanır / boşalırsa silinir.
    Yeni grubun centroid'i seçili görülmelerin embedding'lerinden kurulur."""
    if sum(bool(x) for x in (user_id, person_id, family_id, visitor_id)) != 1:
        raise ValueError('Bir kullanıcı, firma kişisi, aile üyesi ya da ziyaretçi seçin')
    rows = _sighting_rows(conn, ids)
    src_gids = {r['group_id'] for r in rows}
    acc = np.zeros(128, np.float32)
    for r in rows:
        acc += np.frombuffer(r['embedding'], dtype=np.float32)
    best = max(rows, key=lambda r: r['score'] or 0)
    ats = [r['at'] for r in rows]
    last_cam = next((r['camera_id'] for r in sorted(rows, key=lambda r: r['at'], reverse=True) if r['camera_id']), None)
    cur = conn.execute(
        '''INSERT INTO face_groups (centroid, samples, best_crop, best_score, first_seen, last_seen, last_camera)
           VALUES (?,?,?,?,?,?,?)''',
        (_norm(acc).astype(np.float32).tobytes(), len(rows), best['crop'], best['score'] or 0, min(ats), max(ats), last_cam))
    new_gid = cur.lastrowid
    conn.execute(f'UPDATE face_sightings SET group_id = ? WHERE id IN ({",".join("?" * len(rows))})',
                 (new_gid, *[r['id'] for r in rows]))
    for gid in src_gids:   # seçilenler çıkınca kaynak grupları tazele / boşalanı sil
        if gid != new_gid:
            _recompute_group(conn, gid)
    return assign(conn, new_gid, user_id, person_id, by, validate, family_id, visitor_id)


def recent(conn):
    return db.rows(conn.execute(
        '''SELECT s.id, s.at, s.crop, s.frame, s.clip, c.name AS camera_name, g.id AS group_id, g.user_id, g.person_id, g.family_id, g.visitor_id,
                  u.full_name AS user_name, p.full_name AS person_name, pc.name AS person_company, fm.full_name AS family_name,
                  vz.full_name AS visitor_name, vz.company AS visitor_company
           FROM face_sightings s JOIN face_groups g ON g.id = s.group_id LEFT JOIN cameras c ON c.id = s.camera_id
           LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people p ON p.id = g.person_id LEFT JOIN companies pc ON pc.id = p.company_id
           LEFT JOIN family_members fm ON fm.id = g.family_id LEFT JOIN visitors vz ON vz.id = g.visitor_id
           WHERE g.user_id IS NOT NULL OR g.person_id IS NOT NULL OR g.family_id IS NOT NULL OR g.visitor_id IS NOT NULL ORDER BY s.at DESC LIMIT 200'''))


def events(conn, date_from, date_to, kind='known', limit=500):
    where = "s.at >= ? AND s.at < ?"
    args = [date_from, date_to + '~']
    if kind == 'known':
        where += " AND (g.user_id IS NOT NULL OR g.person_id IS NOT NULL OR g.family_id IS NOT NULL OR g.visitor_id IS NOT NULL)"
    return {'events': db.rows(conn.execute(
        f'''SELECT s.id, s.at, s.crop, s.frame, s.clip, s.score, s.threshold, c.name AS camera_name, g.id AS group_id, g.user_id, g.person_id, g.family_id, g.visitor_id,
                   u.full_name AS user_name, p.full_name AS person_name, pc.name AS person_company, fm.full_name AS family_name,
                   vz.full_name AS visitor_name, vz.company AS visitor_company
            FROM face_sightings s JOIN face_groups g ON g.id = s.group_id LEFT JOIN cameras c ON c.id = s.camera_id
            LEFT JOIN users u ON u.id = g.user_id LEFT JOIN company_people p ON p.id = g.person_id
            LEFT JOIN companies pc ON pc.id = p.company_id LEFT JOIN family_members fm ON fm.id = g.family_id
            LEFT JOIN visitors vz ON vz.id = g.visitor_id
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


def family_shots(conn, family_ids, per=6):
    """Aile üyelerine ATANMIŞ kamera gruplarından son görülme kırpıkları. {family_id: [{crop, frame, at, threshold, camera_name}]}."""
    out = {}
    for fid in family_ids or []:
        rows = db.rows(conn.execute(
            '''SELECT s.crop, s.frame, s.at, s.threshold, c.name AS camera_name
               FROM face_sightings s JOIN face_groups g ON g.id = s.group_id LEFT JOIN cameras c ON c.id = s.camera_id
               WHERE g.family_id = ? ORDER BY s.at DESC LIMIT ?''', (int(fid), int(per))))
        if rows:
            out[str(int(fid))] = rows
    return {'shots': out}


def subject_shots(conn, kind, id, limit=12):
    """Bir kişiye (user/person/family) ATANMIŞ kamera gruplarından görülmeler + özet. Rehber/yüz tanıma kaydı için."""
    col = {'user': 'user_id', 'person': 'person_id', 'family': 'family_id', 'visitor': 'visitor_id'}.get(kind)
    if not col:
        return {'shots': [], 'sightings': 0, 'groups': 0}
    grp = db.rows(conn.execute(f'SELECT id, samples, first_seen, last_seen FROM face_groups WHERE {col} = ?', (int(id),)))
    shots = db.rows(conn.execute(
        f'''SELECT s.crop, s.frame, s.at, s.threshold, c.name AS camera_name
            FROM face_sightings s JOIN face_groups g ON g.id = s.group_id LEFT JOIN cameras c ON c.id = s.camera_id
            WHERE g.{col} = ? ORDER BY s.at DESC LIMIT ?''', (int(id), int(limit))))
    total = conn.execute(f'SELECT COUNT(*) FROM face_sightings s JOIN face_groups g ON g.id = s.group_id WHERE g.{col} = ?', (int(id),)).fetchone()[0]
    return {'shots': shots, 'sightings': total, 'groups': len(grp),
            'first_seen': min((g['first_seen'] for g in grp), default=None),
            'last_seen': max((g['last_seen'] for g in grp), default=None)}


def avatars(conn, keys):
    """Kişiler için tanınan en iyi yüz kırpığı (fotoğrafı olmayanlara avatar). keys: ['family:3','user:5','visitor:7',...] → {key: crop}."""
    col = {'user': 'user_id', 'person': 'person_id', 'family': 'family_id', 'visitor': 'visitor_id'}
    out = {}
    for k in keys or []:
        kind, _, sid = str(k).partition(':')
        if kind not in col or not sid.isdigit():
            continue
        r = conn.execute(f'SELECT best_crop FROM face_groups WHERE {col[kind]} = ? AND best_crop IS NOT NULL ORDER BY best_score DESC LIMIT 1', (int(sid),)).fetchone()
        if r and r[0]:
            out[k] = r[0]
    return {'avatars': out}


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
    conn.execute('PRAGMA foreign_keys = OFF')   # fabrika aynası: bulut id'leri (employee/family/visitor) yerel parent olmadan taşınır
    # Eğitilmiş aile üyesi stub'ları (face_groups.family_id FK'si + ad için)
    for fmrow in cfg.get('family') or []:
        conn.execute('INSERT OR REPLACE INTO family_members (id, employee_id, full_name, created_at) VALUES (?,?,?,?)',
                     (fmrow['id'], fmrow.get('employee_id'), fmrow.get('full_name') or '(aile)', db.now()))
    # Eğitilmiş ziyaretçi stub'ları (face_groups.visitor_id FK'si + ad çözümü için)
    for vzrow in cfg.get('visitors') or []:
        conn.execute('INSERT OR REPLACE INTO visitors (id, full_name, company, created_at) VALUES (?,?,?,?)',
                     (vzrow['id'], vzrow.get('full_name') or '(ziyaretçi)', vzrow.get('company'), db.now()))
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
        conn.execute('''INSERT INTO face_enroll (subject_type, user_id, person_id, family_id, visitor_id, crop, embedding, created_at)
                        VALUES (?,?,?,?,?,?,?,?)''',
                     (e['subject_type'], e.get('user_id'), e.get('person_id'), e.get('family_id'), e.get('visitor_id'), '(bulut)', emb, db.now()))
        n += 1
    cams = nvr.sync_cameras(conn)   # yüz tanıma açık kanalları kamera listesine köprüle
    conn.commit()
    return {'ok': True, 'enroll': n, 'cameras': cams, 'channels': len(cfg.get('channels') or {})}


def recognize_frame(conn, args):
    """Tek bir kareyi (JPEG, base64) eğitilmiş izlerle eşleştirir — CANLI TEST için.

    Kamera servisiyle AYNI modeli kullanır (YUNET tespit + SFACE iz + document_media.known_identities eşleştirme).
    Dönüş: {'w','h','faces':[{box:[x,y,w,h], score, user_id|person_id|family_id|visitor_id}]}.
    Eşleşmeyen yüz: score None, tüm *_id None (çerçeve yine çizilir, 'Tanımsız' etiketlenir). İsim çözümü BULUTTA
    (facebridge.resolve_names) yapılır; burada yalnız id döner."""
    import cv2
    from . import document_media as dm
    a = args or {}
    try:
        buf = base64.b64decode(a.get('jpg') or a.get('b64') or '')
    except Exception:
        buf = b''
    if not buf:
        return {'w': 0, 'h': 0, 'faces': []}
    img = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {'w': 0, 'h': 0, 'faces': []}
    h, w = img.shape[:2]
    min_face = int(a.get('min_face') or 44)
    det_thr = float(a.get('det_thr') or 0.8)
    match_thr = float(a.get('thr') or dm.KNOWN_PERSON)
    detector = cv2.FaceDetectorYN.create(str(dm.YUNET), '', (w, h), det_thr, 0.3, 50)
    detector.setInputSize((w, h))
    recognizer = cv2.FaceRecognizerSF.create(str(dm.SFACE), '')
    _, faces = detector.detect(img)
    known = dm.known_identities(conn)
    out = []
    for f in faces if faces is not None else []:
        x, y, fw, fh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
        if min(fw, fh) < min_face:
            continue
        emb = _norm(recognizer.feature(recognizer.alignCrop(img, f)).flatten().astype(np.float32))
        best, best_sim = None, match_thr
        for key, v in known:
            sim = float(np.dot(v, emb))
            if sim >= best_sim:
                best, best_sim = key, sim
        rec = {'box': [round(x), round(y), round(fw), round(fh)],
               'score': round(best_sim, 3) if best else None,
               'user_id': None, 'person_id': None, 'family_id': None, 'visitor_id': None}
        if best:
            rec[f'{best[0]}_id'] = best[1]
        out.append(rec)
    return {'w': w, 'h': h, 'faces': out}


def rpc(conn, method, args):
    """face.rpc dağıtıcısı: bulutun istediği yüz işlemini yerel bağlantıyla çalıştırır."""
    a = args or {}
    if method == 'recognize_frame':
        return recognize_frame(conn, a)
    if method == 'groups':
        return groups(conn, a.get('state', 'unknown'))
    if method == 'group':
        return group(conn, a['gid'])
    if method == 'assign':
        return assign(conn, a['gid'], a.get('user_id'), a.get('person_id'), a.get('by'), a.get('validate', True), a.get('family_id'), a.get('visitor_id'))
    if method == 'merge':
        return merge(conn, a['ids'])
    if method == 'unassign':
        return unassign(conn, a['gid'])
    if method == 'delete_group':
        return delete_group(conn, a['gid'])
    if method == 'delete_sighting':
        return delete_sighting(conn, a['sid'])
    if method == 'delete_sightings':
        return delete_sightings(conn, a.get('ids') or [])
    if method == 'assign_sightings':
        return assign_sightings(conn, a.get('ids') or [], a.get('user_id'), a.get('person_id'), a.get('by'),
                                a.get('validate', True), a.get('family_id'), a.get('visitor_id'))
    if method == 'recent':
        return recent(conn)
    if method == 'events':
        return events(conn, a['date_from'], a['date_to'], a.get('kind', 'known'), a.get('limit', 500))
    if method == 'cameras_list':
        return cameras_list(conn)
    if method == 'overlays':
        return overlays(conn, a.get('ids') or [])
    if method == 'family_shots':
        return family_shots(conn, a.get('family_ids') or [], a.get('per', 6))
    if method == 'subject_shots':
        return subject_shots(conn, a.get('kind'), a.get('id'), a.get('limit', 12))
    if method == 'avatars':
        return avatars(conn, a.get('keys') or [])
    if method == 'push_config':
        return push_config(conn, a.get('cfg') or {})
    if method == 'watch':
        return watch_live(conn, a['cid'], a.get('ttl', 25))
    raise ValueError(f'Bilinmeyen yüz işlemi: {method}')


def watch_live(conn, cid, ttl=25):
    """Canlı izleme talebi: kamera servisinin, yüz tanıma kapalı olsa bile bu kamerayı canlı yakalaması için
    app_kv['live_watch'] = {cid: bitiş_zamanı}. Tarayıcı kareyi çektikçe tazelenir; süre dolunca yakalama durur."""
    import time as _t
    row = conn.execute("SELECT v FROM app_kv WHERE k = 'live_watch'").fetchone()
    d = {}
    if row:
        try:
            d = json.loads(row[0]) or {}
        except Exception:
            d = {}
    now = _t.time()
    d = {k: v for k, v in d.items() if float(v) > now}   # süresi geçenleri temizle
    d[str(int(cid))] = now + float(ttl)
    conn.execute("INSERT OR REPLACE INTO app_kv (k, v) VALUES ('live_watch', ?)", (json.dumps(d),))
    return {'ok': True, 'until': d[str(int(cid))]}


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
