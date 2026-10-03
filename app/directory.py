"""Rehber: sistemde kaynağına bakılmaksızın "insan" olarak kayıtlı tüm kişilerin birleşik rehberi.

Kaynaklar: sistem kullanıcıları (personel), firma kişileri (company_people), personel aile üyeleri (family_members).
Kişi detayında — bakanın yetkisine göre — evraklar, yüz tanıma kayıtları, görüntülü görüşmeler, toplantılar ve
telefon notları toplanır. Veri birden çok modülden geldiği için her bölüm bakanın modül yetkisine göre süzülür.
"""
from . import db


def _can(viewer, *mods):
    return viewer.get('master') or bool(set(mods) & set(viewer.get('modules', [])))


def people(conn, q='', kind='all'):
    q = (q or '').strip().lower()
    out = []
    if kind in ('all', 'user'):
        for r in db.rows(conn.execute(
                '''SELECT u.id, u.full_name, u.photo, e.title, e.department, e.phone, e.email
                   FROM users u LEFT JOIN employees e ON e.user_id = u.id
                   WHERE u.active = 1 AND u.deleted_at IS NULL ORDER BY u.full_name''')):
            out.append({'key': f'user:{r["id"]}', 'type': 'user', 'id': r['id'], 'name': r['full_name'],
                        'subtitle': r['title'] or 'Personel', 'photo': r['photo'], 'phone': r['phone'], 'email': r['email']})
    if kind in ('all', 'person'):
        for r in db.rows(conn.execute(
                '''SELECT p.id, p.full_name, p.title, p.phone, p.email, c.name AS company FROM company_people p
                   JOIN companies c ON c.id = p.company_id ORDER BY p.full_name''')):
            out.append({'key': f'person:{r["id"]}', 'type': 'person', 'id': r['id'], 'name': r['full_name'],
                        'subtitle': ' · '.join([x for x in (r['title'], r['company']) if x]) or 'Firma kişisi',
                        'photo': None, 'phone': r['phone'], 'email': r['email']})
    if kind in ('all', 'family'):
        for r in db.rows(conn.execute(
                '''SELECT fm.id, fm.full_name, fm.relation, fm.phone, (e.first_name || ' ' || e.last_name) AS emp
                   FROM family_members fm JOIN employees e ON e.id = fm.employee_id ORDER BY fm.full_name''')):
            out.append({'key': f'family:{r["id"]}', 'type': 'family', 'id': r['id'], 'name': r['full_name'],
                        'subtitle': ' · '.join([x for x in (r['relation'], f'{r["emp"]} ailesi') if x]), 'photo': None,
                        'phone': r['phone'], 'email': None})
    if q:
        out = [p for p in out if q in (p['name'] or '').lower() or q in (p['subtitle'] or '').lower()
               or q in (p['phone'] or '').lower() or q in (p['email'] or '').lower()]
    out.sort(key=lambda p: (p['name'] or '').lower())
    return out


TYPE_LABEL = {'user': 'Personel', 'person': 'Firma kişisi', 'family': 'Aile üyesi'}


def detail(conn, viewer, type, id):
    if type not in TYPE_LABEL:
        raise ValueError('Geçersiz kişi türü')
    person = _person(conn, type, id)
    if not person:
        raise LookupError('Kişi bulunamadı')
    out = {'type': type, 'id': id, 'type_label': TYPE_LABEL[type], **person, 'sections': {}}
    s = out['sections']
    # Yüz tanıma kayıtları (Kameralar yetkisi / İK — medya erişimiyle aynı)
    if _can(viewer, 'cameras', 'hr'):
        s['face'] = _face(conn, type, id)
    # Evraklar
    if _can(viewer, 'documents', 'companies', 'hr'):
        s['documents'] = _documents(conn, viewer, type, id)
    # Toplantılar
    s['meetings'] = _meetings(conn, type, id)
    # Görüntülü görüşmeler (yalnız personel)
    if type == 'user':
        s['calls'] = _voice_calls(conn, id)
    # Telefon notları (sekreterya/admin)
    if _can(viewer, 'secretariat'):
        s['phone_calls'] = _phone_calls(conn, type, id)
    return out


def _person(conn, type, id):
    if type == 'user':
        r = db.row(conn.execute('''SELECT u.id, u.full_name, u.photo, u.username, e.title, e.department, e.phone, e.email, e.start_date
                                   FROM users u LEFT JOIN employees e ON e.user_id = u.id WHERE u.id = ?''', (id,)))
        if r:
            r['roles'] = db.rows(conn.execute('SELECT role FROM user_roles WHERE user_id = ?', (id,)))
            r['roles'] = [x['role'] for x in r['roles']]
        return r
    if type == 'person':
        return db.row(conn.execute('''SELECT p.id, p.full_name, p.title, p.phone, p.email, p.note, c.id AS company_id, c.name AS company
                                      FROM company_people p JOIN companies c ON c.id = p.company_id WHERE p.id = ?''', (id,)))
    if type == 'family':
        return db.row(conn.execute('''SELECT fm.id, fm.full_name, fm.relation, fm.birth_date, fm.phone, fm.note,
                                      fm.employee_id, (e.first_name || ' ' || e.last_name) AS employee_name
                                      FROM family_members fm JOIN employees e ON e.id = fm.employee_id WHERE fm.id = ?''', (id,)))
    return None


def _face(conn, type, id):
    from . import facebridge, facecore
    if facebridge.remote():
        try:
            return facebridge.rpc('subject_shots', kind=type, id=id, limit=12)
        except Exception:   # noqa: BLE001
            return {'shots': [], 'sightings': 0, 'groups': 0}
    return facecore.subject_shots(conn, type, id, 12)


def _documents(conn, viewer, type, id):
    if type == 'person':
        return db.rows(conn.execute(
            '''SELECT d.id, d.title, d.uploaded_at AS created_at, d.kind FROM document_people dp JOIN documents d ON d.id = dp.document_id
               WHERE dp.person_id = ? ORDER BY d.id DESC LIMIT 100''', (id,)))
    if type == 'user':
        docs = db.rows(conn.execute(
            '''SELECT DISTINCT d.id, d.title, d.uploaded_at AS created_at, d.kind FROM documents d
               JOIN document_faces f ON f.document_id = d.id WHERE f.user_id = ? ORDER BY d.id DESC LIMIT 100''', (id,)))
        if _can(viewer, 'hr'):   # özlük dosyaları yalnız İK
            eid = conn.execute('SELECT id FROM employees WHERE user_id = ?', (id,)).fetchone()
            if eid:
                for r in db.rows(conn.execute('SELECT id, kind, file_name AS title, created_at FROM employee_files WHERE employee_id = ? ORDER BY id DESC', (eid[0],))):
                    docs.append({'id': r['id'], 'title': r['title'] or r['kind'], 'created_at': r['created_at'], 'kind': 'ÖZLÜK'})
        return docs
    return []


def _meetings(conn, type, id):
    if type == 'user':
        return db.rows(conn.execute(
            '''SELECT m.id, m.title, m.starts_at, m.location FROM team_meetings m
               JOIN team_meeting_invites i ON i.meeting_id = m.id WHERE i.user_id = ? AND m.cancelled_at IS NULL
               ORDER BY m.starts_at DESC LIMIT 50''', (id,)))
    if type == 'person':
        return db.rows(conn.execute(
            '''SELECT m.id, m.subject AS title, m.meeting_at AS starts_at, m.location, c.name AS company
               FROM company_meetings m JOIN meeting_people mp ON mp.meeting_id = m.id JOIN companies c ON c.id = m.company_id
               WHERE mp.person_id = ? ORDER BY m.meeting_at DESC LIMIT 50''', (id,)))
    return []


def _voice_calls(conn, uid):
    return db.rows(conn.execute(
        '''SELECT vc.id, vc.title, vc.kind, vc.status, vc.started_at, vc.seconds, vc.recorded
           FROM voice_calls vc JOIN voice_call_participants p ON p.call_id = vc.id
           WHERE p.user_id = ? ORDER BY vc.started_at DESC LIMIT 50''', (uid,)))


def _phone_calls(conn, type, id):
    if type == 'person':
        return db.rows(conn.execute(
            'SELECT id, caller_name, subject, result, created_at FROM phone_calls WHERE person_id = ? ORDER BY id DESC LIMIT 50', (id,)))
    if type == 'user':
        return db.rows(conn.execute(
            'SELECT id, caller_name, subject, result, created_at FROM phone_calls WHERE target_id = ? ORDER BY id DESC LIMIT 50', (id,)))
    return []
