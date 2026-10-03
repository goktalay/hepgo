"""Yüz tanıma eğitimi: bir kişi için (personel / firma personeli / ziyaretçi) yüklenen fotoğraflardan yüz izi çıkarıp saklar.

Kameralarda (NVR kanalları) görülen yüzler bu izlerle eşleştirilir — [[document_media]].known_identities bu izleri de döndürür,
böylece hem evraklardan hem buradan eğitilen kişiler canlı görüntüde tanınır. Yüz kırpıkları UPLOAD_DIR/faces_enroll altında,
izler (embedding) veritabanında tutulur. KVKK: bu veriler fabrikada (lokal) kalır; ham fotoğraf saklanmaz, yalnızca 256px yüz kırpığı.
"""
from . import config, db, document_media

ENROLL_DIR = config.UPLOAD_DIR / 'faces_enroll'


def _subject(subject_type, user_id, person_id):
    if subject_type == 'user':
        if not user_id:
            raise ValueError('Personel seçilmeli')
        return 'user', int(user_id), None, None
    if subject_type == 'person':
        if not person_id:
            raise ValueError('Firma kişisi seçilmeli')
        return 'person', None, int(person_id), None
    raise ValueError('Geçersiz kişi türü')


def enroll(conn, subject_type, user_id, person_id, image_path, created_by):
    """Yüklenen fotoğrafın en büyük yüzünü eğitim izi olarak kaydeder. (ok, kayıt | hata) döner."""
    if not document_media.faces_available():
        raise RuntimeError('Yüz tanıma modelleri yüklü değil')
    st, uid, pid, _ = _subject(subject_type, user_id, person_id)
    faces = document_media.detect_faces_image(image_path)
    if not faces:
        return False, 'Fotoğrafta yüz bulunamadı. Net, önden çekilmiş bir fotoğraf deneyin.'
    import cv2
    f = faces[0]   # en büyük yüz
    ENROLL_DIR.mkdir(parents=True, exist_ok=True)
    name = f'{st}_{uid or pid}_{db.now().replace(":", "").replace("-", "").replace(" ", "_")[:15]}.jpg'
    cv2.imwrite(str(ENROLL_DIR / name), f['crop'], [cv2.IMWRITE_JPEG_QUALITY, 90])
    cur = conn.execute('''INSERT INTO face_enroll (subject_type, user_id, person_id, crop, embedding, created_by, created_at)
                          VALUES (?,?,?,?,?,?,?)''',
                       (st, uid, pid, f'faces_enroll/{name}', f['embedding'].astype('float32').tobytes(), created_by, db.now()))
    return True, {'id': cur.lastrowid, 'crop': f'faces_enroll/{name}'}


def list_for(conn, subject_type, user_id=None, person_id=None):
    st, uid, pid, _ = _subject(subject_type, user_id, person_id)
    col, val = ('user_id', uid) if st == 'user' else ('person_id', pid)
    return db.rows(conn.execute(
        f'SELECT id, crop, created_at FROM face_enroll WHERE subject_type = ? AND {col} = ? ORDER BY id DESC', (st, val)))


def count_by_subject(conn):
    """{('user',id): n, ('person',id): n} — rozet için eğitim fotoğrafı sayıları."""
    out = {}
    for r in conn.execute('SELECT subject_type, user_id, person_id, COUNT(*) FROM face_enroll GROUP BY subject_type, user_id, person_id'):
        out[(r[0], r[1] if r[0] == 'user' else r[2])] = r[3]
    return out


def delete(conn, enroll_id):
    row = conn.execute('SELECT crop FROM face_enroll WHERE id = ?', (enroll_id,)).fetchone()
    if row:
        (config.UPLOAD_DIR / row[0]).unlink(missing_ok=True)
        conn.execute('DELETE FROM face_enroll WHERE id = ?', (enroll_id,))
    return bool(row)


def enrolled_identities(conn):
    """Eğitim fotoğraflarından kimlik izleri: [(('person'|'user', id), ortalama iz)]. known_identities ile birleştirilir."""
    import numpy as np
    sums = {}
    for r in conn.execute('SELECT subject_type, user_id, person_id, embedding FROM face_enroll'):
        if r[0] not in ('user', 'person'):
            continue
        key = ('user', r[1]) if r[0] == 'user' else ('person', r[2])
        v = np.frombuffer(r[3], dtype=np.float32)
        sums[key] = sums.get(key, 0) + v
    return [(k, document_media._norm(v)) for k, v in sums.items()]
