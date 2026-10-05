"""Fabrika (fabrika dijital ikizi) modülü — 2D çok katlı kat planı editörü + personel/kamera yerleşimi +
yüz tanıma görülmelerinden otomatik personel hareketi çizimi.

Kullanıcının istediği: Odaları 2D'de SERBEST POLİGON olarak (köşe köşe) çiz, yerleşim planı üret, sonra bu
plana PERSONEL ve NVR KAMERALARINI yerleştir, odaları ADLANDIR, KAT (kat) ve MERDİVEN (merdiven) tasarla
(çok katlı), ve bu yerleşim + yüz tanıma + bir kişiyi hangi kamera okuduğu bilgisine dayanarak her kişinin
fabrikada NASIL DOLAŞTIĞINI OTOMATİK ÇİZ.

ÖNEMLİ — ŞEMA: Bu modülün tabloları app/db.py'de DEĞİL, aşağıdaki `_ensure_schema(conn)` içinde oluşturulur
(başka bir ajan db.py'yi düzenliyor). `_ensure_schema` modül yüklenirken (import) bir kez çalıştırılır; ayrıca
her isteğin başında da (idempotent, çok ucuz) güvenceye alınır.

YENİDEN KULLANIM:
 - NVR kamera listesi: mevcut yüz/kamera yolu üzerinden (`app.routers.cameras._face(conn, 'cameras_list')`),
   böylece dağıtık (fabrika ajanı) ve yerel kurulum ikisi de çalışır. Kamera plumbing'i YENİDEN YAZILMADI.
 - Yüz görülmeleri: mevcut `events` / `recent` yolu (yine `_face`), kişi başına görülmeler camera_name + at ile
   gelir. Hareket, bu görülmeler camera_name → NVR camera_id → factory_cameras.room_id/floor_id eşlenerek üretilir.
   (DİKKAT: `events`/`recent` çıktısı camera_id DEĞİL camera_name içerir; bu yüzden ad üzerinden eşleriz.)
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/factory')
fab_user = auth.require_module('factory')   # Fabrika modülü: Sistem Yöneticisi + "Kamera Yetkilisi" rolü

# Oda poligonları ve işaretçi koordinatları, plan birimi (ölçeksiz) olarak saklanır; editör SVG'de 1 birim = 1 px.
_SCHEMA_READY = False


def _ensure_schema(conn):
    """Fabrika tablolarını (yoksa) oluşturur ve eksik sütunları korumalı ALTER ile ekler. db.py'nin korumalı
    CREATE TABLE IF NOT EXISTS + guarded ALTER biçimini TAKLİT eder ama tabloları db.py'ye DEĞİL buraya koyar."""
    conn.executescript('''
        -- Kat (kat): bina katları; ordinal = sıra (0 en alt / zemin)
        CREATE TABLE IF NOT EXISTS factory_floors (
            id         INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            ordinal    INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        );

        -- Oda: serbest poligon (köşe listesi JSON); bir kata ait
        CREATE TABLE IF NOT EXISTS factory_rooms (
            id         INTEGER PRIMARY KEY,
            floor_id   INTEGER NOT NULL REFERENCES factory_floors(id) ON DELETE CASCADE,
            name       TEXT NOT NULL DEFAULT '',
            points     TEXT NOT NULL DEFAULT '[]',   -- JSON [[x,y],...] poligon köşeleri
            color      TEXT,
            created_at TEXT
        );

        -- Yerleştirilmiş kamera: bir NVR kamerasını (cameras.id) plan üzerinde bir konuma + (opsiyonel) odaya bağlar
        CREATE TABLE IF NOT EXISTS factory_cameras (
            id         INTEGER PRIMARY KEY,
            camera_id  INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
            floor_id   INTEGER NOT NULL REFERENCES factory_floors(id) ON DELETE CASCADE,
            x          REAL NOT NULL DEFAULT 0,
            y          REAL NOT NULL DEFAULT 0,
            direction  REAL NOT NULL DEFAULT 0,       -- derece: kameranın görüş yönü (0 = sağ/doğu, saat yönü)
            room_id    INTEGER REFERENCES factory_rooms(id) ON DELETE SET NULL,
            created_at TEXT,
            UNIQUE (camera_id)                         -- her NVR kamerası planda bir kez
        );

        -- Merdiven: iki katı birbirine bağlar (çok katlı geçiş)
        CREATE TABLE IF NOT EXISTS factory_stairs (
            id            INTEGER PRIMARY KEY,
            name          TEXT NOT NULL DEFAULT 'Merdiven',
            from_floor_id INTEGER NOT NULL REFERENCES factory_floors(id) ON DELETE CASCADE,
            to_floor_id   INTEGER NOT NULL REFERENCES factory_floors(id) ON DELETE CASCADE,
            x             REAL NOT NULL DEFAULT 0,     -- kaynak kattaki konum
            y             REAL NOT NULL DEFAULT 0,
            to_x          REAL,                         -- hedef kattaki konum (opsiyonel)
            to_y          REAL,
            created_at    TEXT
        );

        -- Statik işaretçiler (masa / etiket): hareketten türemez, kullanıcı elle koyar (opsiyonel kolaylık)
        CREATE TABLE IF NOT EXISTS factory_markers (
            id         INTEGER PRIMARY KEY,
            floor_id   INTEGER NOT NULL REFERENCES factory_floors(id) ON DELETE CASCADE,
            kind       TEXT NOT NULL DEFAULT 'label',  -- 'label' | 'desk' | 'door' ...
            label      TEXT NOT NULL DEFAULT '',
            x          REAL NOT NULL DEFAULT 0,
            y          REAL NOT NULL DEFAULT 0,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS ix_factory_rooms_floor   ON factory_rooms(floor_id);
        CREATE INDEX IF NOT EXISTS ix_factory_cameras_floor ON factory_cameras(floor_id);
        CREATE INDEX IF NOT EXISTS ix_factory_markers_floor ON factory_markers(floor_id);
    ''')
    # Korumalı ALTER (db.py biçimi): ileride sütun eklenirse buraya eklenir, mevcut veritabanı güncellenir.
    cam_cols = {r[1] for r in conn.execute('PRAGMA table_info(factory_cameras)')}
    if 'direction' not in cam_cols:
        conn.execute('ALTER TABLE factory_cameras ADD COLUMN direction REAL NOT NULL DEFAULT 0')
    conn.commit()


def _ensure(conn):
    """Her istekte ucuz güvence (ilk istekte tabloyu oluşturur; sonra no-op)."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    _ensure_schema(conn)
    _SCHEMA_READY = True


# Modül yüklenirken şemayı bir kez oluştur (import/startup). Hata olursa (ör. cameras tablosu henüz yok)
# sessiz geç — ilk istekte _ensure tekrar dener.
try:   # noqa: SIM105
    with db.connect() as _c:
        _ensure_schema(_c)
        _SCHEMA_READY = True
except Exception:   # noqa: BLE001
    pass


# ----------------------------------------------------------------------------- yardımcılar

def _face(conn, method, **args):
    """Yüz/kamera işlemlerini mevcut yol üzerinden çalıştırır (cameras router'ındaki _face ile aynı davranış:
    dağıtıksa facebridge.rpc, yerelse facecore.rpc). Döngüsel import olmasın diye fonksiyon içinde import edilir."""
    from .cameras import _face as cam_face
    return cam_face(conn, method, **args)


def _resolve_names(conn, rows):
    from .cameras import _resolve_names as cam_resolve
    return cam_resolve(conn, rows)


def _nvr_cameras(conn):
    """NVR kamera listesi (id + name + kanal/konum). Mevcut kamera yolu yeniden kullanılır."""
    try:
        return _face(conn, 'cameras_list') or []
    except Exception:   # noqa: BLE001 — NVR/fabrika erişilemezse boş liste (editör yine çalışır)
        return []


def _subject_of(e):
    """Bir görülme/olay satırından (events/recent çıktısı) özne tipini, kimliğini ve adını çıkarır."""
    if e.get('user_id'):
        return 'user', e['user_id'], e.get('user_name') or 'Kullanıcı'
    if e.get('person_id'):
        return 'person', e['person_id'], e.get('person_name') or 'Kişi'
    if e.get('family_id'):
        return 'family', e['family_id'], e.get('family_name') or 'Aile üyesi'
    if e.get('visitor_id'):
        return 'visitor', e['visitor_id'], e.get('visitor_name') or 'Ziyaretçi'
    return None, None, None


def _placements(conn):
    """Yerleştirilmiş kameralar: camera_id → {room_id, floor_id, room_name, floor_name, direction, x, y}."""
    rows = db.rows(conn.execute('''
        SELECT fc.camera_id, fc.room_id, fc.floor_id, fc.x, fc.y, fc.direction,
               r.name AS room_name, f.name AS floor_name
        FROM factory_cameras fc
        LEFT JOIN factory_rooms  r ON r.id = fc.room_id
        LEFT JOIN factory_floors f ON f.id = fc.floor_id'''))
    return {r['camera_id']: r for r in rows}


def _name_to_id(conn):
    """NVR kamera adı → id eşlemesi (events/recent yalnız camera_name verdiği için gerekir)."""
    out = {}
    for c in _nvr_cameras(conn):
        nm = c.get('name')
        if nm and c.get('id') is not None:
            out[nm] = c['id']
    return out


# ----------------------------------------------------------------------------- Katlar (floors)

class FloorIn(BaseModel):
    name: str
    ordinal: Optional[int] = None


class FloorPatch(BaseModel):
    name: Optional[str] = None
    ordinal: Optional[int] = None


class ReorderIn(BaseModel):
    ids: list[int]   # yeni sıra (ilk = en alt kat)


@router.get('/floors')
def list_floors(user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    return db.rows(conn.execute('SELECT * FROM factory_floors ORDER BY ordinal, id'))


@router.post('/floors')
def add_floor(body: FloorIn, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    name = (body.name or '').strip() or 'Kat'
    ordv = body.ordinal if body.ordinal is not None else \
        (conn.execute('SELECT COALESCE(MAX(ordinal), -1) + 1 FROM factory_floors').fetchone()[0])
    cur = conn.execute('INSERT INTO factory_floors (name, ordinal, created_at) VALUES (?,?,?)',
                       (name, ordv, db.now()))
    db.audit(conn, user['id'], 'Fabrika katı ekledi', 'factory_floor', cur.lastrowid, name)
    return db.row(conn.execute('SELECT * FROM factory_floors WHERE id = ?', (cur.lastrowid,)))


@router.patch('/floors/{fid}')
def update_floor(fid: int, body: FloorPatch, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    f = db.row(conn.execute('SELECT * FROM factory_floors WHERE id = ?', (fid,)))
    if not f:
        raise HTTPException(404, 'Kat bulunamadı')
    name = (body.name.strip() if body.name is not None else f['name']) or f['name']
    ordv = body.ordinal if body.ordinal is not None else f['ordinal']
    conn.execute('UPDATE factory_floors SET name = ?, ordinal = ? WHERE id = ?', (name, ordv, fid))
    db.audit(conn, user['id'], 'Fabrika katını güncelledi', 'factory_floor', fid, name)
    return db.row(conn.execute('SELECT * FROM factory_floors WHERE id = ?', (fid,)))


@router.post('/floors/reorder')
def reorder_floors(body: ReorderIn, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    for i, fid in enumerate(body.ids):
        conn.execute('UPDATE factory_floors SET ordinal = ? WHERE id = ?', (i, fid))
    db.audit(conn, user['id'], 'Fabrika katlarını sıraladı', 'factory_floor', None, f'{len(body.ids)} kat')
    return {'ok': True}


@router.delete('/floors/{fid}')
def delete_floor(fid: int, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    if not conn.execute('SELECT 1 FROM factory_floors WHERE id = ?', (fid,)).fetchone():
        raise HTTPException(404, 'Kat bulunamadı')
    conn.execute('DELETE FROM factory_floors WHERE id = ?', (fid,))   # odalar/kameralar CASCADE
    db.audit(conn, user['id'], 'Fabrika katını sildi', 'factory_floor', fid, None)
    return {'ok': True}


# ----------------------------------------------------------------------------- Odalar (rooms)

class RoomIn(BaseModel):
    floor_id: int
    name: str = ''
    points: list = []          # [[x,y],...]
    color: Optional[str] = None


class RoomPatch(BaseModel):
    name: Optional[str] = None
    points: Optional[list] = None
    color: Optional[str] = None
    floor_id: Optional[int] = None


def _dump_points(points):
    import json
    pts = []
    for p in points or []:
        try:
            pts.append([round(float(p[0]), 2), round(float(p[1]), 2)])
        except (TypeError, ValueError, IndexError):
            continue
    return json.dumps(pts)


def _room_out(r):
    import json
    d = dict(r)
    try:
        d['points'] = json.loads(d.get('points') or '[]')
    except ValueError:
        d['points'] = []
    return d


@router.get('/rooms')
def list_rooms(floor: Optional[int] = None, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    if floor is not None:
        rows = db.rows(conn.execute('SELECT * FROM factory_rooms WHERE floor_id = ? ORDER BY id', (floor,)))
    else:
        rows = db.rows(conn.execute('SELECT * FROM factory_rooms ORDER BY floor_id, id'))
    return [_room_out(r) for r in rows]


@router.post('/rooms')
def add_room(body: RoomIn, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    if not conn.execute('SELECT 1 FROM factory_floors WHERE id = ?', (body.floor_id,)).fetchone():
        raise HTTPException(400, 'Kat bulunamadı')
    cur = conn.execute(
        'INSERT INTO factory_rooms (floor_id, name, points, color, created_at) VALUES (?,?,?,?,?)',
        (body.floor_id, (body.name or '').strip(), _dump_points(body.points), body.color, db.now()))
    db.audit(conn, user['id'], 'Fabrika odası ekledi', 'factory_room', cur.lastrowid, (body.name or '').strip())
    return _room_out(db.row(conn.execute('SELECT * FROM factory_rooms WHERE id = ?', (cur.lastrowid,))))


@router.patch('/rooms/{rid}')
def update_room(rid: int, body: RoomPatch, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    r = db.row(conn.execute('SELECT * FROM factory_rooms WHERE id = ?', (rid,)))
    if not r:
        raise HTTPException(404, 'Oda bulunamadı')
    name = (body.name.strip() if body.name is not None else r['name'])
    points = _dump_points(body.points) if body.points is not None else r['points']
    color = body.color if body.color is not None else r['color']
    floor_id = body.floor_id if body.floor_id is not None else r['floor_id']
    conn.execute('UPDATE factory_rooms SET name = ?, points = ?, color = ?, floor_id = ? WHERE id = ?',
                 (name, points, color, floor_id, rid))
    db.audit(conn, user['id'], 'Fabrika odasını güncelledi', 'factory_room', rid, name)
    return _room_out(db.row(conn.execute('SELECT * FROM factory_rooms WHERE id = ?', (rid,))))


@router.delete('/rooms/{rid}')
def delete_room(rid: int, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    if not conn.execute('SELECT 1 FROM factory_rooms WHERE id = ?', (rid,)).fetchone():
        raise HTTPException(404, 'Oda bulunamadı')
    conn.execute('DELETE FROM factory_rooms WHERE id = ?', (rid,))
    db.audit(conn, user['id'], 'Fabrika odasını sildi', 'factory_room', rid, None)
    return {'ok': True}


# ----------------------------------------------------------------------------- Kameralar (placed)

class PlaceCameraIn(BaseModel):
    camera_id: int
    floor_id: int
    x: float = 0
    y: float = 0
    direction: float = 0
    room_id: Optional[int] = None


class CameraPatch(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    direction: Optional[float] = None
    room_id: Optional[int] = None
    floor_id: Optional[int] = None


def _placed_camera_out(conn):
    return db.rows(conn.execute('''
        SELECT fc.*, r.name AS room_name, f.name AS floor_name
        FROM factory_cameras fc
        LEFT JOIN factory_rooms  r ON r.id = fc.room_id
        LEFT JOIN factory_floors f ON f.id = fc.floor_id
        ORDER BY fc.id'''))


@router.get('/cameras')
def list_placed_cameras(floor: Optional[int] = None, user=Depends(fab_user), conn=db.DB):
    """Plana yerleştirilmiş kameralar (NVR adı da eklenir)."""
    _ensure(conn)
    rows = _placed_camera_out(conn)
    if floor is not None:
        rows = [r for r in rows if r['floor_id'] == floor]
    names = {c['id']: c.get('name') for c in _nvr_cameras(conn)}
    for r in rows:
        r['camera_name'] = names.get(r['camera_id'])
    return rows


@router.get('/available-cameras')
def available_cameras(user=Depends(fab_user), conn=db.DB):
    """Henüz plana yerleştirilmemiş NVR kameraları (seçim listesi)."""
    _ensure(conn)
    placed = {r[0] for r in conn.execute('SELECT camera_id FROM factory_cameras')}
    out = []
    for c in _nvr_cameras(conn):
        if c.get('id') in placed:
            continue
        out.append({'id': c.get('id'), 'name': c.get('name'), 'location': c.get('location'),
                    'status': c.get('status')})
    return out


@router.post('/cameras')
def place_camera(body: PlaceCameraIn, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    if not conn.execute('SELECT 1 FROM factory_floors WHERE id = ?', (body.floor_id,)).fetchone():
        raise HTTPException(400, 'Kat bulunamadı')
    # NVR kamerasının varlığını mevcut listeden doğrula (cameras tablosu yerelde olmayabilir → dağıtık kurulum)
    if body.camera_id not in {c.get('id') for c in _nvr_cameras(conn)}:
        raise HTTPException(400, 'Kamera bulunamadı')
    if conn.execute('SELECT 1 FROM factory_cameras WHERE camera_id = ?', (body.camera_id,)).fetchone():
        raise HTTPException(400, 'Bu kamera zaten yerleştirilmiş')
    cur = conn.execute(
        '''INSERT INTO factory_cameras (camera_id, floor_id, x, y, direction, room_id, created_at)
           VALUES (?,?,?,?,?,?,?)''',
        (body.camera_id, body.floor_id, body.x, body.y, body.direction, body.room_id, db.now()))
    db.audit(conn, user['id'], 'Fabrika planına kamera yerleştirdi', 'factory_camera', cur.lastrowid,
             f'camera={body.camera_id}')
    return db.row(conn.execute('SELECT * FROM factory_cameras WHERE id = ?', (cur.lastrowid,)))


@router.patch('/cameras/{cid}')
def update_placed_camera(cid: int, body: CameraPatch, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    c = db.row(conn.execute('SELECT * FROM factory_cameras WHERE id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'Yerleştirilmiş kamera bulunamadı')
    x = body.x if body.x is not None else c['x']
    y = body.y if body.y is not None else c['y']
    direction = body.direction if body.direction is not None else c['direction']
    floor_id = body.floor_id if body.floor_id is not None else c['floor_id']
    # room_id özel: PATCH'te None, "gönderilmedi" ile "oda bağını kaldır"ı ayıramaz. Alan gövdede VARSA
    # (model_fields_set) gelen değeri (None olsa bile) yaz; yoksa mevcut değeri koru.
    room_id = body.room_id if 'room_id' in body.model_fields_set else c['room_id']
    conn.execute('UPDATE factory_cameras SET x = ?, y = ?, direction = ?, room_id = ?, floor_id = ? WHERE id = ?',
                 (x, y, direction, room_id, floor_id, cid))
    db.audit(conn, user['id'], 'Fabrika kamerasını güncelledi', 'factory_camera', cid, None)
    return db.row(conn.execute('SELECT * FROM factory_cameras WHERE id = ?', (cid,)))


@router.delete('/cameras/{cid}')
def remove_placed_camera(cid: int, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    if not conn.execute('SELECT 1 FROM factory_cameras WHERE id = ?', (cid,)).fetchone():
        raise HTTPException(404, 'Yerleştirilmiş kamera bulunamadı')
    conn.execute('DELETE FROM factory_cameras WHERE id = ?', (cid,))
    db.audit(conn, user['id'], 'Fabrika kamerasını kaldırdı', 'factory_camera', cid, None)
    return {'ok': True}


# ----------------------------------------------------------------------------- Merdivenler (stairs)

class StairIn(BaseModel):
    name: str = 'Merdiven'
    from_floor_id: int
    to_floor_id: int
    x: float = 0
    y: float = 0
    to_x: Optional[float] = None
    to_y: Optional[float] = None


class StairPatch(BaseModel):
    name: Optional[str] = None
    from_floor_id: Optional[int] = None
    to_floor_id: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    to_x: Optional[float] = None
    to_y: Optional[float] = None


@router.get('/stairs')
def list_stairs(floor: Optional[int] = None, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    rows = db.rows(conn.execute('SELECT * FROM factory_stairs ORDER BY id'))
    if floor is not None:   # ilgili kata dokunan merdivenler (kaynak ya da hedef)
        rows = [r for r in rows if r['from_floor_id'] == floor or r['to_floor_id'] == floor]
    return rows


@router.post('/stairs')
def add_stair(body: StairIn, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    for fid in (body.from_floor_id, body.to_floor_id):
        if not conn.execute('SELECT 1 FROM factory_floors WHERE id = ?', (fid,)).fetchone():
            raise HTTPException(400, 'Kat bulunamadı')
    cur = conn.execute(
        '''INSERT INTO factory_stairs (name, from_floor_id, to_floor_id, x, y, to_x, to_y, created_at)
           VALUES (?,?,?,?,?,?,?,?)''',
        ((body.name or 'Merdiven').strip(), body.from_floor_id, body.to_floor_id, body.x, body.y,
         body.to_x, body.to_y, db.now()))
    db.audit(conn, user['id'], 'Fabrika merdiveni ekledi', 'factory_stair', cur.lastrowid, body.name)
    return db.row(conn.execute('SELECT * FROM factory_stairs WHERE id = ?', (cur.lastrowid,)))


@router.patch('/stairs/{sid}')
def update_stair(sid: int, body: StairPatch, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    s = db.row(conn.execute('SELECT * FROM factory_stairs WHERE id = ?', (sid,)))
    if not s:
        raise HTTPException(404, 'Merdiven bulunamadı')
    vals = {k: (getattr(body, k) if getattr(body, k) is not None else s[k])
            for k in ('name', 'from_floor_id', 'to_floor_id', 'x', 'y', 'to_x', 'to_y')}
    conn.execute('''UPDATE factory_stairs SET name = ?, from_floor_id = ?, to_floor_id = ?, x = ?, y = ?,
                    to_x = ?, to_y = ? WHERE id = ?''',
                 (vals['name'], vals['from_floor_id'], vals['to_floor_id'], vals['x'], vals['y'],
                  vals['to_x'], vals['to_y'], sid))
    db.audit(conn, user['id'], 'Fabrika merdivenini güncelledi', 'factory_stair', sid, vals['name'])
    return db.row(conn.execute('SELECT * FROM factory_stairs WHERE id = ?', (sid,)))


@router.delete('/stairs/{sid}')
def delete_stair(sid: int, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    if not conn.execute('SELECT 1 FROM factory_stairs WHERE id = ?', (sid,)).fetchone():
        raise HTTPException(404, 'Merdiven bulunamadı')
    conn.execute('DELETE FROM factory_stairs WHERE id = ?', (sid,))
    db.audit(conn, user['id'], 'Fabrika merdivenini sildi', 'factory_stair', sid, None)
    return {'ok': True}


# ----------------------------------------------------------------------------- Statik işaretçiler (markers)

class MarkerIn(BaseModel):
    floor_id: int
    kind: str = 'label'
    label: str = ''
    x: float = 0
    y: float = 0


class MarkerPatch(BaseModel):
    kind: Optional[str] = None
    label: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    floor_id: Optional[int] = None


@router.get('/markers')
def list_markers(floor: Optional[int] = None, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    if floor is not None:
        return db.rows(conn.execute('SELECT * FROM factory_markers WHERE floor_id = ? ORDER BY id', (floor,)))
    return db.rows(conn.execute('SELECT * FROM factory_markers ORDER BY floor_id, id'))


@router.post('/markers')
def add_marker(body: MarkerIn, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    if not conn.execute('SELECT 1 FROM factory_floors WHERE id = ?', (body.floor_id,)).fetchone():
        raise HTTPException(400, 'Kat bulunamadı')
    cur = conn.execute(
        'INSERT INTO factory_markers (floor_id, kind, label, x, y, created_at) VALUES (?,?,?,?,?,?)',
        (body.floor_id, (body.kind or 'label').strip(), (body.label or '').strip(), body.x, body.y, db.now()))
    return db.row(conn.execute('SELECT * FROM factory_markers WHERE id = ?', (cur.lastrowid,)))


@router.patch('/markers/{mid}')
def update_marker(mid: int, body: MarkerPatch, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    m = db.row(conn.execute('SELECT * FROM factory_markers WHERE id = ?', (mid,)))
    if not m:
        raise HTTPException(404, 'İşaretçi bulunamadı')
    vals = {k: (getattr(body, k) if getattr(body, k) is not None else m[k])
            for k in ('kind', 'label', 'x', 'y', 'floor_id')}
    conn.execute('UPDATE factory_markers SET kind = ?, label = ?, x = ?, y = ?, floor_id = ? WHERE id = ?',
                 (vals['kind'], vals['label'], vals['x'], vals['y'], vals['floor_id'], mid))
    return db.row(conn.execute('SELECT * FROM factory_markers WHERE id = ?', (mid,)))


@router.delete('/markers/{mid}')
def delete_marker(mid: int, user=Depends(fab_user), conn=db.DB):
    _ensure(conn)
    conn.execute('DELETE FROM factory_markers WHERE id = ?', (mid,))
    return {'ok': True}


# ----------------------------------------------------------------------------- HAREKET (movement)

@router.get('/movement')
def movement(subject_type: str, subject_id: int, date_from: str, date_to: str,
             user=Depends(fab_user), conn=db.DB):
    """Bir kişinin (user/person/family/visitor) verilen aralıktaki fabrika içi yolu.

    Türetme:
      1) Mevcut yüz OLAY yolu (`events`) ile aralıktaki tanınmış görülmeler çekilir.
      2) Yalnız seçilen özneye (subject_type + subject_id) ait olanlar süzülür.
      3) Her görülmenin camera_name'i → NVR camera_id → factory_cameras (room_id, floor_id, oda adı) eşlenir.
      4) Zamana göre (artan) sıralanır; ardışık AYNI oda girişleri segmentlere toplanır
         {room_id, floor_id, room_name, floor_name, enter, leave, count}.
    Kat değişimi, iki segmentin floor_id'si farklıysa oluşur (frontend merdivenle çizer).
    """
    if subject_type not in ('user', 'person', 'family', 'visitor'):
        raise HTTPException(400, 'Geçersiz özne tipi')
    _ensure(conn)
    col = {'user': 'user_id', 'person': 'person_id', 'family': 'family_id', 'visitor': 'visitor_id'}[subject_type]

    data = _face(conn, 'events', date_from=date_from, date_to=date_to, kind='known', limit=2000)
    evs = data.get('events', []) if isinstance(data, dict) else (data or [])
    _resolve_names(conn, evs)   # dağıtık kurulumda adları çözer (yerel zaten çözülü gelir)
    subj = [e for e in evs if e.get(col) == subject_id]
    subj.sort(key=lambda e: e.get('at') or '')

    name2id = _name_to_id(conn)
    placed = _placements(conn)

    points = []   # her görülme: eşlenen oda/kat ile
    for e in subj:
        cam_name = e.get('camera_name')
        cid = name2id.get(cam_name)
        pl = placed.get(cid) if cid is not None else None
        points.append({
            'at': e.get('at'),
            'camera_id': cid,
            'camera_name': cam_name,
            'room_id': pl['room_id'] if pl else None,
            'room_name': (pl.get('room_name') if pl else None),
            'floor_id': pl['floor_id'] if pl else None,
            'floor_name': (pl.get('floor_name') if pl else None),
            'crop': e.get('crop'),
        })

    # Ardışık aynı oda (kat + oda) → segment. Oda eşlenmemişse (kamera yerleştirilmemiş) kamera adıyla gruplanır.
    segments = []
    for p in points:
        key = (p['floor_id'], p['room_id'], None if p['room_id'] else p['camera_id'])
        if segments and segments[-1]['_key'] == key:
            seg = segments[-1]
            seg['leave'] = p['at']
            seg['count'] += 1
        else:
            segments.append({
                '_key': key,
                'room_id': p['room_id'], 'room_name': p['room_name'],
                'floor_id': p['floor_id'], 'floor_name': p['floor_name'],
                'camera_id': p['camera_id'], 'camera_name': p['camera_name'],
                'enter': p['at'], 'leave': p['at'], 'count': 1,
            })
    for s in segments:
        s.pop('_key', None)

    stype, sid, sname = (subject_type, subject_id, None)
    if subj:
        stype, sid, sname = _subject_of(subj[0])
    return {
        'subject_type': subject_type, 'subject_id': subject_id, 'subject_name': sname,
        'date_from': date_from, 'date_to': date_to,
        'sightings': points, 'segments': segments,
    }


@router.get('/now')
def who_is_where(minutes: int = 10, user=Depends(fab_user), conn=db.DB):
    """Canlı "şu an kim nerede": son `minutes` dakikadaki görülmeler odalara eşlenir, her özne için en son
    görülme tutulur. Mevcut `recent` yolu yeniden kullanılır."""
    _ensure(conn)
    minutes = max(1, min(int(minutes or 10), 240))
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec='seconds')

    rows = _face(conn, 'recent') or []
    _resolve_names(conn, rows)
    name2id = _name_to_id(conn)
    placed = _placements(conn)

    latest = {}   # (type,id) → en son görülme kaydı
    for e in rows:
        if (e.get('at') or '') < cutoff:
            continue
        stype, sid, sname = _subject_of(e)
        if not stype:
            continue
        key = (stype, sid)
        if key in latest and (e.get('at') or '') <= latest[key]['at']:
            continue
        cid = name2id.get(e.get('camera_name'))
        pl = placed.get(cid) if cid is not None else None
        latest[key] = {
            'subject_type': stype, 'subject_id': sid, 'subject_name': sname,
            'at': e.get('at'), 'camera_id': cid, 'camera_name': e.get('camera_name'),
            'room_id': pl['room_id'] if pl else None,
            'room_name': (pl.get('room_name') if pl else None),
            'floor_id': pl['floor_id'] if pl else None,
            'floor_name': (pl.get('floor_name') if pl else None),
            'crop': e.get('crop'),
        }
    people = sorted(latest.values(), key=lambda r: r['at'] or '', reverse=True)
    return {'minutes': minutes, 'people': people}
