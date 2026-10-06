"""Yüz tanıma eğitimi: bir kişi için (personel / firma personeli / ziyaretçi) yüklenen fotoğraflardan yüz izi çıkarıp saklar.

Kameralarda (NVR kanalları) görülen yüzler bu izlerle eşleştirilir — [[document_media]].known_identities bu izleri de döndürür,
böylece hem evraklardan hem buradan eğitilen kişiler canlı görüntüde tanınır. Yüz kırpıkları UPLOAD_DIR/faces_enroll altında,
izler (embedding) veritabanında tutulur. KVKK: bu veriler fabrikada (lokal) kalır; ham fotoğraf saklanmaz, yalnızca 256px yüz kırpığı.
"""
from . import config, db, document_media

ENROLL_DIR = config.UPLOAD_DIR / 'faces_enroll'


_COL = {'user': 'user_id', 'person': 'person_id', 'family': 'family_id', 'visitor': 'visitor_id'}


def _subject(subject_type, user_id, person_id, family_id=None, visitor_id=None):
    if subject_type == 'user':
        if not user_id:
            raise ValueError('Personel seçilmeli')
        return 'user', int(user_id), None, None, None
    if subject_type == 'person':
        if not person_id:
            raise ValueError('Firma kişisi seçilmeli')
        return 'person', None, int(person_id), None, None
    if subject_type == 'family':
        if not family_id:
            raise ValueError('Aile üyesi seçilmeli')
        return 'family', None, None, int(family_id), None
    if subject_type == 'visitor':
        if not visitor_id:
            raise ValueError('Ziyaretçi seçilmeli')
        return 'visitor', None, None, None, int(visitor_id)
    raise ValueError('Geçersiz kişi türü')


def enroll(conn, subject_type, user_id, person_id, image_path, created_by, family_id=None, visitor_id=None):
    """Yüklenen fotoğrafın en büyük yüzünü eğitim izi olarak kaydeder. (ok, kayıt | hata) döner."""
    if not document_media.faces_available():
        raise RuntimeError('Yüz tanıma modelleri yüklü değil')
    st, uid, pid, fid, vid = _subject(subject_type, user_id, person_id, family_id, visitor_id)
    faces = document_media.detect_faces_image(image_path)
    if not faces:
        return False, 'Fotoğrafta yüz bulunamadı. Net, önden çekilmiş bir fotoğraf deneyin.'
    import cv2
    f = faces[0]   # en büyük yüz
    ENROLL_DIR.mkdir(parents=True, exist_ok=True)
    name = f'{st}_{uid or pid or fid or vid}_{db.now().replace(":", "").replace("-", "").replace(" ", "_")[:15]}.jpg'
    cv2.imwrite(str(ENROLL_DIR / name), f['crop'], [cv2.IMWRITE_JPEG_QUALITY, 90])
    cur = conn.execute('''INSERT INTO face_enroll (subject_type, user_id, person_id, family_id, visitor_id, crop, embedding, source, created_by, created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?)''',
                       (st, uid, pid, fid, vid, f'faces_enroll/{name}', f['embedding'].astype('float32').tobytes(), 'manual', created_by, db.now()))
    return True, {'id': cur.lastrowid, 'crop': f'faces_enroll/{name}'}


def enroll_precomputed(conn, subject_type, user_id, person_id, family_id, crop_bytes, embedding_bytes, created_by, visitor_id=None, source='auto'):
    """Kameradan ATANAN bir yüzü YENİDEN TESPİT ETMEDEN eğitim izine ekler: görülmenin mevcut kırpığı (crop_bytes) ve
    embedding'i (128 float32 bayt) olduğu gibi kullanılır. Böylece atanan yüzler hem 'eğitim verisi' görünümünde çıkar
    hem de gerçek zamanlı tanımaya beslenir (push ile fabrika servisine). DEDUPE: aynı kişinin mevcut eğitim izlerinden
    birine kosinüs benzerliği > 0.92 ise (yakın kopya) eklemez. Eklenen kaydın id'sini, kopyaysa None döner."""
    import uuid

    import numpy as np
    st, uid, pid, fid, vid = _subject(subject_type, user_id, person_id, family_id, visitor_id)
    emb = np.frombuffer(embedding_bytes, dtype=np.float32)
    if emb.size != 128:
        raise ValueError('Geçersiz yüz izi (128 boyutlu embedding bekleniyor)')
    nv = document_media._norm(emb)
    col, val = _COL[st], (uid or pid or fid or vid)
    # DEDUPE: aynı kişinin eğitim izlerinden birine çok benziyorsa atla (yakın kopya kırpıkla eğitimi şişirme)
    for row in conn.execute(f'SELECT embedding FROM face_enroll WHERE subject_type = ? AND {col} = ?', (st, val)):
        ev = np.frombuffer(row[0], dtype=np.float32)
        if ev.size == 128 and float(np.dot(nv, document_media._norm(ev))) > 0.92:
            return None
    ENROLL_DIR.mkdir(parents=True, exist_ok=True)
    name = f'{st}_{val}_{db.now().replace(":", "").replace("-", "").replace(" ", "_")[:15]}_{uuid.uuid4().hex[:8]}.jpg'
    (ENROLL_DIR / name).write_bytes(crop_bytes)
    cur = conn.execute('''INSERT INTO face_enroll (subject_type, user_id, person_id, family_id, visitor_id, crop, embedding, source, created_by, created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?)''',
                       (st, uid, pid, fid, vid, f'faces_enroll/{name}', emb.astype('float32').tobytes(), source, created_by, db.now()))
    return cur.lastrowid


def list_for(conn, subject_type, user_id=None, person_id=None, family_id=None, visitor_id=None):
    st, uid, pid, fid, vid = _subject(subject_type, user_id, person_id, family_id, visitor_id)
    col, val = _COL[st], (uid or pid or fid or vid)
    return db.rows(conn.execute(
        f'SELECT id, crop, source, created_at FROM face_enroll WHERE subject_type = ? AND {col} = ? ORDER BY id DESC', (st, val)))


def count_by_subject(conn):
    """{('user',id): n, ...} — rozet için eğitim fotoğrafı sayıları."""
    out = {}
    for r in conn.execute('SELECT subject_type, user_id, person_id, family_id, visitor_id, COUNT(*) FROM face_enroll GROUP BY subject_type, user_id, person_id, family_id, visitor_id'):
        key_id = r[1] if r[0] == 'user' else r[2] if r[0] == 'person' else r[3] if r[0] == 'family' else r[4]
        out[(r[0], key_id)] = r[5]
    return out


def delete(conn, enroll_id):
    row = conn.execute('SELECT crop FROM face_enroll WHERE id = ?', (enroll_id,)).fetchone()
    if row:
        (config.UPLOAD_DIR / row[0]).unlink(missing_ok=True)
        conn.execute('DELETE FROM face_enroll WHERE id = ?', (enroll_id,))
    return bool(row)


def enrolled_identities(conn):
    """Eğitim fotoğraflarından kimlik izleri: [(('user'|'person'|'family'|'visitor', id), ortalama iz)]. known_identities ile birleştirilir."""
    import numpy as np
    sums = {}
    for r in conn.execute('SELECT subject_type, user_id, person_id, family_id, visitor_id, embedding FROM face_enroll'):
        if r[0] == 'user':
            key = ('user', r[1])
        elif r[0] == 'person':
            key = ('person', r[2])
        elif r[0] == 'family':
            key = ('family', r[3])
        elif r[0] == 'visitor':
            key = ('visitor', r[4])
        else:
            continue
        v = np.frombuffer(r[5], dtype=np.float32)
        sums[key] = sums.get(key, 0) + v
    return [(k, document_media._norm(v)) for k, v in sums.items()]
