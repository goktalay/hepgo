"""Bulut tarafı yüz tanıma köprüsü (dağıtık kurulum).

AGENT_MODE=remote iken yüz verisi fabrikanın yerel DB'sindedir: bu modül görülme/grup/olay sorgularını fabrika
ajanına (`face.rpc`) yönlendirir, medyayı (`face.media`) getirir ve yapılandırmayı (NVR + kanal + vardiya + eğitim
izleri) fabrikaya aktarır (`push`). İsimler (kullanıcı/kişi) BULUT veritabanından çözülür — fabrika DB'si eski
olabilir, yalnız id'lere güvenilir. Yerel (tek makine) kurulumda router doğrudan facecore'u kullanır; bu modül devrede değil.
"""
import base64
import json

from fastapi import HTTPException

from . import config, db, devices


def remote():
    return config.AGENT_MODE == 'remote'


def rpc(method, **args):
    """Fabrika ajanında facecore.<method> çalıştırır. Hata payload'ını HTTP'ye çevirir."""
    r = devices.call_sync('face.rpc', {'method': method, 'args': args})
    if isinstance(r, dict) and r.get('_err'):
        raise HTTPException(404 if r['_err'] == 'notfound' else 400, r.get('msg') or 'Hata')
    return r


def media(path):
    """Fabrikadaki kamera medyasını (kırpık/kare/klip) getirir → (bytes, content_type)."""
    r = devices.call_sync('face.media', {'path': path}, timeout=30)
    if isinstance(r, dict) and r.get('_err'):
        raise HTTPException(404, 'Dosya yok')
    return base64.b64decode(r['b64']), r['content_type']


def resolve_names(conn, rows):
    """Fabrikadan gelen satırlardaki user_id/person_id'yi BULUT veritabanındaki adlarla doldurur."""
    rows = rows if isinstance(rows, list) else [rows]
    uids = {r['user_id'] for r in rows if r.get('user_id')}
    pids = {r['person_id'] for r in rows if r.get('person_id')}
    fids = {r['family_id'] for r in rows if r.get('family_id')}
    users = {r[0]: r[1] for r in conn.execute(
        f'SELECT id, full_name FROM users WHERE id IN ({",".join("?" * len(uids))})', tuple(uids))} if uids else {}
    people = {r[0]: (r[1], r[2]) for r in conn.execute(
        f'''SELECT p.id, p.full_name, c.name FROM company_people p LEFT JOIN companies c ON c.id = p.company_id
            WHERE p.id IN ({",".join("?" * len(pids))})''', tuple(pids))} if pids else {}
    family = {r[0]: r[1] for r in conn.execute(
        f'SELECT id, full_name FROM family_members WHERE id IN ({",".join("?" * len(fids))})', tuple(fids))} if fids else {}
    for r in rows:
        if r.get('user_id'):
            r['user_name'] = users.get(r['user_id'])
        if r.get('person_id'):
            r['person_name'], r['person_company'] = people.get(r['person_id'], (None, None))
        if r.get('family_id'):
            r['family_name'] = family.get(r['family_id'])
    return rows


def push(conn):
    """Bulut yapılandırmasını (NVR + kanal + vardiya + eğitim izleri) fabrikaya aktarır. Yerelde gerek yok."""
    if not remote():
        return {'ok': True, 'skipped': 'local'}
    from . import shifts
    row = conn.execute("SELECT v FROM app_kv WHERE k = 'nvr_channels'").fetchone()
    channels = json.loads(row[0]) if row else {}
    frow = conn.execute("SELECT v FROM app_kv WHERE k = 'facerec_config'").fetchone()
    facerec = json.loads(frow[0]) if frow else {'score': 0.6, 'min_face': 36}
    enroll = [{'subject_type': r[0], 'user_id': r[1], 'person_id': r[2], 'family_id': r[3], 'embedding': base64.b64encode(r[4]).decode()}
              for r in conn.execute('SELECT subject_type, user_id, person_id, family_id, embedding FROM face_enroll')]
    # Eğitilmiş aile üyelerinin stub kayıtları (fabrikada face_groups.family_id FK'si için + ad çözümü)
    family = [{'id': r[0], 'full_name': r[1], 'employee_id': r[2]} for r in conn.execute(
        'SELECT id, full_name, employee_id FROM family_members WHERE id IN (SELECT DISTINCT family_id FROM face_enroll WHERE family_id IS NOT NULL)')]
    cfg = {
        'nvr': {'host': config.NVR_HOST, 'port': config.NVR_PORT, 'user': config.NVR_USER, 'password': config.NVR_PASSWORD},
        'channels': channels, 'shift': shifts.get(conn), 'enroll': enroll, 'facerec': facerec, 'family': family,
    }
    return rpc('push_config', cfg=cfg)
