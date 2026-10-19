"""Dron Yönetimi (Saha Yönetimi alt modülleri — Faz 1): dron envanteri, köprüler (köprü kodu / eşleştirme kodu / anahtar),
canlı uçuş oturumları, rota merkezleri + rotalar + ara noktalar. Canlı telemetri WebSocket'leri app/drone_hub.py'de.

Faz 1 kararları: dron kaydında BAĞLANTI BİLGİSİ yok (köprü/sysid/seri-tcp-udp saha görevindeki uçuşta seçilir — routers/field.py);
protocol mavlink | sanal (sunucu içi simülatör) | dji; köprü eklenince <domain>/<key> biçiminde KÖPRÜ KODU bir kez döner.

Rol Yönetimi düğümleri: field.drones (Dron Envanteri), field.live (Canlı Uçuş), field.routes (Rotalar), field.bridges
(Dron Köprüleri). Ayar yoksa 'field' modülünün izni miras alınır (rbac.node_chain).
"""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import agentkeys, auth, db, drone_hub, drone_params, drone_sitl

router = APIRouter(prefix='/api/drone')
drones_user = auth.require_module('drone.drones')
live_user = auth.require_module('field.live')
routes_user = auth.require_module('drone.routes')
bridges_user = auth.require_module('drone.bridges')

DRONE_STATUS = {'AKTIF': 'Aktif', 'BAKIMDA': 'Bakımda', 'ARIZALI': 'Arızalı', 'PASIF': 'Pasif'}
PROTOCOLS = {'mavlink': 'MAVLink', 'sanal': 'Sanal Dron', 'dji': 'DJI'}
SESSION_STATUS = {'ACIK': 'Açık', 'KAPANDI': 'Kapandı', 'KOPTU': 'Koptu', 'KESILDI': 'Kesildi (sunucu yeniden başladı)'}
PLATFORMS = ('android', 'windows', 'linux', 'macos', 'other')
CONN_TYPES = ('tcp', 'udp', 'serial')   # uçuşun link.type seçenekleri (field_flights.link; routers/field.py doğrular)
ROUTE_KINDS = {'line': 'Hat', 'loop': 'Döngü', 'survey': 'Tarama'}
WP_ACTIONS = {'waypoint': 'Ara nokta', 'loiter': 'Bekle (loiter)', 'takeoff': 'Kalkış', 'land': 'İniş', 'rtl': 'Eve dön (RTL)'}


class DroneIn(BaseModel):
    """Dron envanteri kaydı — conn_* / bridge_id / sysid YOK (bağlantı uçuş düzeyinde)."""
    name: str
    serial: Optional[str] = None
    model: Optional[str] = None
    protocol: str = 'mavlink'       # mavlink | sanal | dji
    order_id: Optional[int] = None
    pilot_id: Optional[int] = None
    status: str = 'AKTIF'
    note: Optional[str] = None
    active: bool = True


class BridgeIn(BaseModel):
    name: str
    platform: Optional[str] = None
    owner_id: Optional[int] = None
    note: Optional[str] = None
    active: bool = True


class CenterIn(BaseModel):
    name: str
    lat: float
    lon: float
    alt: Optional[float] = None
    location_id: Optional[int] = None
    note: Optional[str] = None
    active: bool = True


class WaypointIn(BaseModel):
    lat: float
    lon: float
    alt: Optional[float] = None
    action: str = 'waypoint'
    hold_s: Optional[float] = None
    note: Optional[str] = None


class RouteIn(BaseModel):
    name: str
    center_id: Optional[int] = None
    kind: str = 'line'
    cruise_alt: Optional[float] = None
    cruise_speed: Optional[float] = None
    note: Optional[str] = None
    active: bool = True
    waypoints: list[WaypointIn] = []


class CmdIn(BaseModel):
    bridge_id: int
    sysid: int = 1
    name: str
    params: dict = {}


class ParamImportIn(BaseModel):
    text: str                       # Mission Planner .param içeriği (AD,DEĞER satırları)


def _clean(s, n=200):
    s = (s or '').strip()
    return s[:n] or None


def _latlon(lat, lon):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, 'Enlem -90…90, boylam -180…180 olmalı')


def _req_host(request):
    """İsteğin Host başlığı (ters vekil arkasında x-forwarded-host) — şemasız, port'suz, yol'suz."""
    host = (request.headers.get('x-forwarded-host') or request.headers.get('host') or '').split(',')[0].strip()
    host = re.sub(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', '', host).split('/', 1)[0]
    if host.startswith('['):   # IPv6 [::1]:8000
        return host.split(']', 1)[0] + ']'
    return host.rsplit(':', 1)[0] if host.count(':') == 1 else host


def bridge_code(conn, request_host, key):
    """KÖPRÜ KODU `<domain>/<key>`: domain = Entegrasyonlar'daki ortak domain (agentkeys.domain) varsa o, yoksa isteğin Host'u.
    Köprüyü kuran kişi bu kodu köprü yazılımına girer; yazılım domain'den wss://<domain>/ws/drone/bridge adresini türetir ve
    key ile `auth` olur → köprü bu şirkete (tenant) ve köprü kaydının sahibine (owner) bağlanır. Kod bir kez gösterilir."""
    domain = agentkeys._strip_scheme(agentkeys.domain(conn)) or request_host or ''
    return f'{domain}/{key}'


# ---------------- Meta ----------------
@router.get('/meta')
def meta(user=Depends(auth.current_user)):
    return {'drone_status': DRONE_STATUS, 'protocols': PROTOCOLS, 'session_status': SESSION_STATUS, 'platforms': PLATFORMS,
            'conn_types': CONN_TYPES, 'route_kinds': ROUTE_KINDS, 'wp_actions': WP_ACTIONS, 'commands': sorted(drone_hub.CMD_NAMES),
            'can': {'drones': 'drone.drones' in user['modules'], 'live': 'field.live' in user['modules'],
                    'routes': 'drone.routes' in user['modules'], 'bridges': 'drone.bridges' in user['modules'],
                    'sim': 'drone.sim' in user['modules'],
                    'command': drone_hub.can_command(user) if 'write_modules' in user else False},
            'write': {'drones': 'drone.drones' in user.get('write_modules', [])}}


# ---------------- Dron envanteri ----------------
def _drones(conn, where='1=1', args=()):
    """Envanter satırları: bağlantı/köprü/canlı alanları YOK (Faz 1); protocol_text eklenir."""
    rows = db.rows(conn.execute(
        f'''SELECT d.*, pl.full_name AS pilot_name, o.code AS order_code, o.queue_no,
                   (SELECT COUNT(*) FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                    WHERE f.drone_id = d.id AND t.status != 'IPTAL') AS task_count,
                   (SELECT t.code FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                    WHERE f.drone_id = d.id AND t.status IN ('BASLANGIC', 'GOREVDE') ORDER BY t.id DESC LIMIT 1) AS open_task_code,
                   (SELECT MAX(l.uploaded_at) FROM flight_logs l JOIN field_flights f ON f.id = l.flight_id WHERE f.drone_id = d.id) AS last_log_at
            FROM drone_drones d
            LEFT JOIN users pl ON pl.id = d.pilot_id
            LEFT JOIN orders o ON o.id = d.order_id
            WHERE {where} ORDER BY d.active DESC, d.code''', args))
    for r in rows:
        r['status_text'] = DRONE_STATUS.get(r['status'], r['status'])
        r['protocol_text'] = PROTOCOLS.get(r['protocol'], r['protocol'])
    return rows


def _check_drone_refs(conn, body):
    if body.status not in DRONE_STATUS:
        raise HTTPException(400, 'Geçersiz durum')
    if body.protocol not in PROTOCOLS:
        raise HTTPException(400, 'Dron türü MAVLink, Sanal Dron ya da DJI olmalı')
    if body.pilot_id and not conn.execute('SELECT 1 FROM users u JOIN user_roles r ON r.user_id = u.id WHERE u.id = ? AND r.role = ?',
                                          (body.pilot_id, auth.PILOT)).fetchone():
        raise HTTPException(400, 'Seçilen kişi pilot değil')
    if body.order_id and not conn.execute('SELECT 1 FROM orders WHERE id = ?', (body.order_id,)).fetchone():
        raise HTTPException(400, 'Sipariş bulunamadı')


@router.get('/drones')
def list_drones(user=Depends(drones_user), conn=db.DB):
    return _drones(conn)


@router.get('/drones/{did}')
def get_drone(did: int, user=Depends(drones_user), conn=db.DB):
    rows = _drones(conn, 'd.id = ?', (did,))
    if not rows:
        raise HTTPException(404, 'Dron bulunamadı')
    d = rows[0]
    d['flights'] = db.rows(conn.execute(
        '''SELECT f.id, f.task_id, t.code AS task_code, t.status AS task_status, t.started_at, t.finished_at, loc.name AS location_name,
                  l.id AS log_id, l.status AS log_status, l.source AS log_source, json_extract(l.analysis, '$.summary.flight_s') AS flight_s
           FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
           LEFT JOIN field_locations loc ON loc.id = t.location_id
           LEFT JOIN flight_logs l ON l.id = (SELECT MAX(id) FROM flight_logs WHERE flight_id = f.id)
           WHERE f.drone_id = ? ORDER BY t.id DESC''', (did,)))
    d['sessions'] = db.rows(conn.execute(
        '''SELECT s.*, b.name AS bridge_name, u.full_name AS started_by_name FROM drone_bridge_sessions s
           JOIN drone_bridges b ON b.id = s.bridge_id LEFT JOIN users u ON u.id = s.started_by
           WHERE s.drone_id = ? ORDER BY s.id DESC LIMIT 50''', (did,)))
    return d


@router.post('/drones')
def add_drone(body: DroneIn, user=Depends(drones_user), conn=db.DB):
    name = _clean(body.name, 120)
    if not name:
        raise HTTPException(400, 'Dron adı gerekli')
    _check_drone_refs(conn, body)
    serial = _clean(body.serial, 80)
    if serial and conn.execute('SELECT 1 FROM drone_drones WHERE serial = ? COLLATE NOCASE', (serial,)).fetchone():
        raise HTTPException(400, 'Bu seri numarası kayıtlı')
    code = db.next_code(conn, 'drone_drones', 'code', 'D')
    cur = conn.execute(
        '''INSERT INTO drone_drones (code, name, serial, model, protocol, order_id, pilot_id, status, note, active, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (code, name, serial, _clean(body.model, 80), body.protocol, body.order_id, body.pilot_id, body.status,
         _clean(body.note, 1000), int(body.active), user['id'], db.now()))
    db.audit(conn, user['id'], 'Dron ekledi', 'drone', cur.lastrowid, f'{code} {name} · {PROTOCOLS[body.protocol]}')
    return {'id': cur.lastrowid, 'code': code}


@router.put('/drones/{did}')
def update_drone(did: int, body: DroneIn, user=Depends(drones_user), conn=db.DB):
    old = db.row(conn.execute('SELECT * FROM drone_drones WHERE id = ?', (did,)))
    if not old:
        raise HTTPException(404, 'Dron bulunamadı')
    name = _clean(body.name, 120)
    if not name:
        raise HTTPException(400, 'Dron adı gerekli')
    _check_drone_refs(conn, body)
    serial = _clean(body.serial, 80)
    if serial and conn.execute('SELECT 1 FROM drone_drones WHERE serial = ? COLLATE NOCASE AND id != ?', (serial, did)).fetchone():
        raise HTTPException(400, 'Bu seri numarası başka bir dronda kayıtlı')
    conn.execute(
        '''UPDATE drone_drones SET name = ?, serial = ?, model = ?, protocol = ?, order_id = ?, pilot_id = ?, status = ?, note = ?, active = ?,
                  updated_at = ? WHERE id = ?''',
        (name, serial, _clean(body.model, 80), body.protocol, body.order_id, body.pilot_id, body.status,
         _clean(body.note, 1000), int(body.active), db.now(), did))
    db.audit(conn, user['id'], 'Dron güncelledi', 'drone', did, f"{old['code']} {name}")
    return {'ok': True}


@router.delete('/drones/{did}')
def delete_drone(did: int, user=Depends(drones_user), conn=db.DB):
    old = db.row(conn.execute('SELECT * FROM drone_drones WHERE id = ?', (did,)))
    if not old:
        raise HTTPException(404, 'Dron bulunamadı')
    used = conn.execute('SELECT COUNT(*) FROM field_flights WHERE drone_id = ?', (did,)).fetchone()[0]
    if used:   # uçuş geçmişi olan dron silinmez; pasife alınır
        conn.execute("UPDATE drone_drones SET active = 0, status = 'PASIF', updated_at = ? WHERE id = ?", (db.now(), did))
        db.audit(conn, user['id'], 'Dronu pasife aldı', 'drone', did, f"{old['code']} ({used} uçuş kaydı var)")
        return {'ok': True, 'deactivated': True}
    conn.execute('DELETE FROM drone_drones WHERE id = ?', (did,))
    db.audit(conn, user['id'], 'Dron sildi', 'drone', did, old['code'])
    return {'ok': True}


# ---------------- Sanal dron kalıcı parametreleri (drone_params; tablo drone_sitl_params) ----------------
def _sanal_dron(conn, did):
    d = db.row(conn.execute('SELECT id, code, name, protocol, model FROM drone_drones WHERE id = ?', (did,)))
    if not d:
        raise HTTPException(404, 'Dron bulunamadı')
    if d['protocol'] != 'sanal':
        raise HTTPException(400, 'Kalıcı parametreler yalnız sanal dronlarda tutulur')
    return d


@router.get('/drones/{did}/sitl-params')
def list_sitl_params(did: int, user=Depends(drones_user), conn=db.DB):
    """Dronun kayıtlı SITL parametreleri + hariç tutma listesi (okuma yetkisi yeter)."""
    d = _sanal_dron(conn, did)
    items = drone_params.yukle(did, conn)
    # §20.1 sanal montaj: SITL ikilisi SIM_SRV_REV tanıyor mu (rozet metni) + kayıtlı SERVOn_REVERSED'den üretilen maske
    tip = drone_sitl.model_tipi(d.get('model'))
    sanal_montaj = drone_sitl.sanal_montaj_destegi(tip)
    motor = []
    mask = drone_params.srv_rev_mask(items, tip, motor)
    return {'items': items, 'count': len(items), 'excluded': drone_params.haric_listesi(), 'can_write': 'drone.drones' in user.get('write_modules', []),
            'mount': {'virtual_mount': sanal_montaj, 'srv_rev_mask': mask, 'motor_skipped': motor,
                      'badge': drone_params.MONTAJ_ROZET if sanal_montaj else drone_params.MONTAJ_ROZET_NOTR,
                      'note': None if sanal_montaj else drone_params.MONTAJ_DESTEK_YOK}}


@router.get('/drones/{did}/sitl-params/export')
def export_sitl_params(did: int, user=Depends(drones_user), conn=db.DB):
    """Mission Planner `.param` dosyası (`AD,DEĞER`)."""
    d = _sanal_dron(conn, did)
    rows = drone_params.yukle(did, conn)
    body = drone_params.param_metni(rows, f"HEPGO {d['code']} {d['name']} · {len(rows)} parametre · {db.now()}")
    return PlainTextResponse(body, media_type='text/plain; charset=utf-8',
                             headers={'Content-Disposition': f'attachment; filename="{d["code"]}.param"'})


@router.post('/drones/{did}/sitl-params/import')
def import_sitl_params(did: int, body: ParamImportIn, user=Depends(drones_user), conn=db.DB):
    """`.param` metnini kayıtlara yazar (source hepgo); hariç/bozuk satırlar atlanır. Çalışan SITL'e sonraki açılışta yüklenir."""
    d = _sanal_dron(conn, did)
    if len(body.text) > 2_000_000:
        raise HTTPException(400, 'Dosya çok büyük (en çok 2 MB)')
    try:
        r = drone_params.ice_aktar(did, body.text, user['id'], conn)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.audit(conn, user['id'], 'Sanal dron parametreleri içe aktardı', 'drone', did, f"{d['code']} · {r['imported']} parametre, {r['skipped_count']} atlandı")
    return r


@router.delete('/drones/{did}/sitl-params')
def reset_sitl_params(did: int, user=Depends(drones_user), conn=db.DB):
    """Tümünü sıfırla: dronun kayıtlı parametreleri silinir (çalışan SITL etkilenmez; sonraki açılış firmware varsayılanlarıyla)."""
    d = _sanal_dron(conn, did)
    n = drone_params.sil(did, None, conn)
    db.audit(conn, user['id'], 'Sanal dron parametrelerini sıfırladı', 'drone', did, f"{d['code']} · {n} parametre")
    return {'ok': True, 'deleted': n}


@router.delete('/drones/{did}/sitl-params/{name}')
def delete_sitl_param(did: int, name: str, user=Depends(drones_user), conn=db.DB):
    d = _sanal_dron(conn, did)
    n = drone_params.sil(did, name, conn)
    if not n:
        raise HTTPException(404, 'Parametre kaydı bulunamadı')
    db.audit(conn, user['id'], 'Sanal dron parametresi sildi', 'drone', did, f"{d['code']} · {name.upper()}")
    return {'ok': True}


# ---------------- Köprüler ----------------
def _bridges(conn, where='1=1', args=()):
    """Köprü satırları: anahtar/kod ASLA dönmez (has_key yalnız tanımlı mı); flight_count = köprüye bağlı uçuşlar (açık görevler)."""
    rows = db.rows(conn.execute(
        f'''SELECT b.id, b.name, b.platform, b.owner_id, b.host, b.bridge_ver, b.status, b.last_seen, b.note, b.active, b.created_at,
                   b.key_enc IS NOT NULL AS has_key, u.full_name AS owner_name,
                   (SELECT COUNT(*) FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                    WHERE f.bridge_id = b.id AND t.status IN ('BASLANGIC', 'GOREVDE')) AS flight_count,
                   (SELECT COUNT(*) FROM drone_bridge_sessions s WHERE s.bridge_id = b.id) AS session_count
            FROM drone_bridges b LEFT JOIN users u ON u.id = b.owner_id WHERE {where} ORDER BY b.active DESC, b.name COLLATE NOCASE''', args))
    online = drone_hub.online_bridges()
    for r in rows:
        r['has_key'] = bool(r['has_key'])
        r['drone_count'] = r['flight_count']   # eski alan adı (liste sütunu) — açık görevlerdeki bağlı uçuş sayısı
        r['online'] = r['id'] in online
        r['live'] = online.get(r['id'])
    return rows


@router.get('/bridges')
def list_bridges(user=Depends(bridges_user), conn=db.DB):
    return _bridges(conn)


@router.post('/bridges')
def add_bridge(body: BridgeIn, request: Request, user=Depends(bridges_user), conn=db.DB):
    """Köprü oluşturur ve KÖPRÜ KODU döndürür ({id, code}; code = <domain>/<key>, anahtar o anda üretilir, yalnız bu yanıtta görünür).
    Sahip (owner_id) verilmezse oluşturan kullanıcı olur: köprü bu şirkete ve bu kişiye bağlanır."""
    name = _clean(body.name, 80)
    if not name:
        raise HTTPException(400, 'Köprü adı gerekli')
    if body.platform and body.platform not in PLATFORMS:
        raise HTTPException(400, 'Geçersiz platform')
    if conn.execute('SELECT 1 FROM drone_bridges WHERE name = ? COLLATE NOCASE', (name,)).fetchone():
        raise HTTPException(400, 'Bu adda köprü var')
    owner = body.owner_id or user['id']
    cur = conn.execute('INSERT INTO drone_bridges (name, platform, owner_id, note, active, created_by, created_at) VALUES (?,?,?,?,?,?,?)',
                       (name, body.platform, owner, _clean(body.note, 1000), int(body.active), user['id'], db.now()))
    key = drone_hub.issue_key(conn, cur.lastrowid)
    db.audit(conn, user['id'], 'Dron köprüsü ekledi', 'drone_bridge', cur.lastrowid, f'{name} · köprü kodu üretildi')
    return {'id': cur.lastrowid, 'code': bridge_code(conn, _req_host(request), key)}


@router.put('/bridges/{bid}')
def update_bridge(bid: int, body: BridgeIn, user=Depends(bridges_user), conn=db.DB):
    old = db.row(conn.execute('SELECT * FROM drone_bridges WHERE id = ?', (bid,)))
    if not old:
        raise HTTPException(404, 'Köprü bulunamadı')
    name = _clean(body.name, 80)
    if not name:
        raise HTTPException(400, 'Köprü adı gerekli')
    if body.platform and body.platform not in PLATFORMS:
        raise HTTPException(400, 'Geçersiz platform')
    if conn.execute('SELECT 1 FROM drone_bridges WHERE name = ? COLLATE NOCASE AND id != ?', (name, bid)).fetchone():
        raise HTTPException(400, 'Bu adda köprü var')
    conn.execute('UPDATE drone_bridges SET name = ?, platform = ?, owner_id = ?, note = ?, active = ?, updated_at = ? WHERE id = ?',
                 (name, body.platform, body.owner_id, _clean(body.note, 1000), int(body.active), db.now(), bid))
    db.audit(conn, user['id'], 'Dron köprüsü güncelledi', 'drone_bridge', bid, name)
    return {'ok': True}


@router.delete('/bridges/{bid}')
def delete_bridge(bid: int, user=Depends(bridges_user), conn=db.DB):
    old = db.row(conn.execute('SELECT * FROM drone_bridges WHERE id = ?', (bid,)))
    if not old:
        raise HTTPException(404, 'Köprü bulunamadı')
    if bid in drone_hub.BRIDGES:
        raise HTTPException(400, 'Köprü şu an bağlı; önce bağlantıyı kesin')
    conn.execute('DELETE FROM drone_bridges WHERE id = ?', (bid,))   # oturumlar CASCADE, uçuşların (field_flights) bridge_id NULL
    db.audit(conn, user['id'], 'Dron köprüsü sildi', 'drone_bridge', bid, old['name'])
    return {'ok': True}


@router.post('/bridges/{bid}/pair')
def pair_bridge(bid: int, user=Depends(bridges_user), conn=db.DB):
    """6 karakterlik tek kullanımlık eşleştirme kodu (10 dk). Köprü yazılımı bu kodla bağlanır, kalıcı anahtarını alır."""
    b = db.row(conn.execute('SELECT id, name, active FROM drone_bridges WHERE id = ?', (bid,)))
    if not b or not b['active']:
        raise HTTPException(404, 'Köprü bulunamadı ya da pasif')
    out = drone_hub.make_pair_code(bid)
    db.audit(conn, user['id'], 'Dron köprüsü eşleştirme kodu üretti', 'drone_bridge', bid, b['name'])
    return out


@router.post('/bridges/{bid}/rekey')
def rekey_bridge(bid: int, request: Request, user=Depends(bridges_user), conn=db.DB):
    """Yeni kalıcı anahtar + köprü kodu ({key, code}; düz metin yalnız bu yanıtta); eski anahtar hemen geçersiz, bağlı köprü düşürülür."""
    b = db.row(conn.execute('SELECT id, name FROM drone_bridges WHERE id = ?', (bid,)))
    if not b:
        raise HTTPException(404, 'Köprü bulunamadı')
    key = drone_hub.issue_key(conn, bid)
    db.audit(conn, user['id'], 'Dron köprüsü anahtarını yeniledi', 'drone_bridge', bid, b['name'])
    live = drone_hub.BRIDGES.get(bid)
    if live is not None:
        import asyncio
        try:
            asyncio.get_running_loop().create_task(drone_hub.disconnect_bridge(bid, 'KAPANDI'))
        except RuntimeError:
            pass
    return {'key': key, 'code': bridge_code(conn, _req_host(request), key)}


@router.post('/bridges/{bid}/disconnect')
async def disconnect_bridge(bid: int, user=Depends(bridges_user), conn=db.DB):
    if not await drone_hub.disconnect_bridge(bid, 'KAPANDI'):
        raise HTTPException(400, 'Köprü bağlı değil')
    db.audit(conn, user['id'], 'Dron köprüsü bağlantısını kesti', 'drone_bridge', bid)
    return {'ok': True}


@router.get('/bridges/{bid}/sessions')
def bridge_sessions(bid: int, limit: int = 100, user=Depends(bridges_user), conn=db.DB):
    rows = db.rows(conn.execute(
        '''SELECT s.*, u.full_name AS started_by_name, d.code AS drone_code FROM drone_bridge_sessions s
           LEFT JOIN users u ON u.id = s.started_by LEFT JOIN drone_drones d ON d.id = s.drone_id
           WHERE s.bridge_id = ? ORDER BY s.id DESC LIMIT ?''', (bid, max(1, min(limit, 500)))))
    for r in rows:
        r['status_text'] = SESSION_STATUS.get(r['status'], r['status'])
    return rows


# ---------------- Canlı uçuş ----------------
@router.get('/live')
def live_state(user=Depends(live_user), conn=db.DB):
    """Anlık durum (WebSocket açılmadan önce / yedek): bağlı köprüler (+ çalışan sanal dronlar) + son bilinen dron durumları + envanter.
    Görev bağlamı (uçuş → köprü/sysid eşlemesi) için GET /api/field/tasks/{id}/live kullanılır."""
    snap = drone_hub.snapshot()
    drones = db.rows(conn.execute('SELECT id, code, name, model, protocol, status FROM drone_drones WHERE active = 1 ORDER BY code'))
    return {**snap, 'drones': drones, 'can_command': drone_hub.can_command(user),
            'sessions': db.rows(conn.execute(
                '''SELECT s.id, s.bridge_id, b.name AS bridge_name, s.started_at, s.packets, s.last_seen
                   FROM drone_bridge_sessions s JOIN drone_bridges b ON b.id = s.bridge_id WHERE s.ended_at IS NULL ORDER BY s.id DESC'''))}


@router.post('/live/cmd')
async def live_cmd(body: CmdIn, user=Depends(live_user)):
    """Tarayıcı WebSocket yerine REST ile komut (aynı yetki: field.live yazma + Pilot/Admin rolü; audit)."""
    try:
        return await drone_hub.send_command(user, body.bridge_id, body.sysid, body.name, body.params)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get('/sessions')
def list_sessions(limit: int = 100, user=Depends(live_user), conn=db.DB):
    rows = db.rows(conn.execute(
        '''SELECT s.*, b.name AS bridge_name, u.full_name AS started_by_name, d.code AS drone_code FROM drone_bridge_sessions s
           JOIN drone_bridges b ON b.id = s.bridge_id LEFT JOIN users u ON u.id = s.started_by LEFT JOIN drone_drones d ON d.id = s.drone_id
           ORDER BY s.id DESC LIMIT ?''', (max(1, min(limit, 500)),)))
    for r in rows:
        r['status_text'] = SESSION_STATUS.get(r['status'], r['status'])
    return rows


# ---------------- Rota merkezleri ve rotalar ----------------
@router.get('/centers')
def list_centers(user=Depends(routes_user), conn=db.DB):
    return db.rows(conn.execute(
        '''SELECT c.*, loc.name AS location_name, (SELECT COUNT(*) FROM drone_routes r WHERE r.center_id = c.id) AS route_count
           FROM drone_route_centers c LEFT JOIN field_locations loc ON loc.id = c.location_id ORDER BY c.active DESC, c.name COLLATE NOCASE'''))


@router.post('/centers')
def add_center(body: CenterIn, user=Depends(routes_user), conn=db.DB):
    name = _clean(body.name, 120)
    if not name:
        raise HTTPException(400, 'Merkez adı gerekli')
    _latlon(body.lat, body.lon)
    if conn.execute('SELECT 1 FROM drone_route_centers WHERE name = ? COLLATE NOCASE', (name,)).fetchone():
        raise HTTPException(400, 'Bu adda merkez var')
    cur = conn.execute('INSERT INTO drone_route_centers (name, lat, lon, alt, location_id, note, active, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                       (name, body.lat, body.lon, body.alt, body.location_id, _clean(body.note, 1000), int(body.active), user['id'], db.now()))
    db.audit(conn, user['id'], 'Rota merkezi ekledi', 'drone_center', cur.lastrowid, name)
    return {'id': cur.lastrowid}


@router.put('/centers/{cid}')
def update_center(cid: int, body: CenterIn, user=Depends(routes_user), conn=db.DB):
    if not conn.execute('SELECT 1 FROM drone_route_centers WHERE id = ?', (cid,)).fetchone():
        raise HTTPException(404, 'Merkez bulunamadı')
    name = _clean(body.name, 120)
    if not name:
        raise HTTPException(400, 'Merkez adı gerekli')
    _latlon(body.lat, body.lon)
    if conn.execute('SELECT 1 FROM drone_route_centers WHERE name = ? COLLATE NOCASE AND id != ?', (name, cid)).fetchone():
        raise HTTPException(400, 'Bu adda merkez var')
    conn.execute('UPDATE drone_route_centers SET name = ?, lat = ?, lon = ?, alt = ?, location_id = ?, note = ?, active = ? WHERE id = ?',
                 (name, body.lat, body.lon, body.alt, body.location_id, _clean(body.note, 1000), int(body.active), cid))
    db.audit(conn, user['id'], 'Rota merkezi güncelledi', 'drone_center', cid, name)
    return {'ok': True}


@router.delete('/centers/{cid}')
def delete_center(cid: int, user=Depends(routes_user), conn=db.DB):
    old = db.row(conn.execute('SELECT * FROM drone_route_centers WHERE id = ?', (cid,)))
    if not old:
        raise HTTPException(404, 'Merkez bulunamadı')
    conn.execute('DELETE FROM drone_route_centers WHERE id = ?', (cid,))   # rotaların center_id NULL olur
    db.audit(conn, user['id'], 'Rota merkezi sildi', 'drone_center', cid, old['name'])
    return {'ok': True}


def _route_rows(conn, where='1=1', args=()):
    rows = db.rows(conn.execute(
        f'''SELECT r.*, c.name AS center_name, u.full_name AS created_by_name,
                   (SELECT COUNT(*) FROM drone_waypoints w WHERE w.route_id = r.id) AS wp_count
            FROM drone_routes r LEFT JOIN drone_route_centers c ON c.id = r.center_id LEFT JOIN users u ON u.id = r.created_by
            WHERE {where} ORDER BY r.active DESC, r.name COLLATE NOCASE''', args))
    for r in rows:
        r['kind_text'] = ROUTE_KINDS.get(r['kind'], r['kind'])
    return rows


def _waypoints(conn, rid):
    return db.rows(conn.execute('SELECT * FROM drone_waypoints WHERE route_id = ? ORDER BY ord', (rid,)))


def _check_route(conn, body):
    if body.kind not in ROUTE_KINDS:
        raise HTTPException(400, 'Geçersiz rota türü')
    if body.center_id and not conn.execute('SELECT 1 FROM drone_route_centers WHERE id = ?', (body.center_id,)).fetchone():
        raise HTTPException(400, 'Merkez bulunamadı')
    if len(body.waypoints) > 500:
        raise HTTPException(400, 'En çok 500 ara nokta')
    for w in body.waypoints:
        _latlon(w.lat, w.lon)
        if w.action not in WP_ACTIONS:
            raise HTTPException(400, 'Geçersiz ara nokta eylemi')


def _save_waypoints(conn, rid, wps):
    conn.execute('DELETE FROM drone_waypoints WHERE route_id = ?', (rid,))
    conn.executemany('INSERT INTO drone_waypoints (route_id, ord, lat, lon, alt, action, hold_s, note) VALUES (?,?,?,?,?,?,?,?)',
                     [(rid, i + 1, w.lat, w.lon, w.alt, w.action, w.hold_s, _clean(w.note, 200)) for i, w in enumerate(wps)])


@router.get('/routes')
def list_routes(center_id: Optional[int] = None, user=Depends(routes_user), conn=db.DB):
    return _route_rows(conn, 'r.center_id = ?', (center_id,)) if center_id else _route_rows(conn)


@router.get('/routes/{rid}')
def get_route(rid: int, user=Depends(routes_user), conn=db.DB):
    rows = _route_rows(conn, 'r.id = ?', (rid,))
    if not rows:
        raise HTTPException(404, 'Rota bulunamadı')
    r = rows[0]
    r['waypoints'] = _waypoints(conn, rid)
    return r


@router.post('/routes')
def add_route(body: RouteIn, user=Depends(routes_user), conn=db.DB):
    name = _clean(body.name, 120)
    if not name:
        raise HTTPException(400, 'Rota adı gerekli')
    _check_route(conn, body)
    cur = conn.execute(
        '''INSERT INTO drone_routes (center_id, name, kind, cruise_alt, cruise_speed, note, active, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        (body.center_id, name, body.kind, body.cruise_alt, body.cruise_speed, _clean(body.note, 1000), int(body.active), user['id'], db.now()))
    _save_waypoints(conn, cur.lastrowid, body.waypoints)
    db.audit(conn, user['id'], 'Rota ekledi', 'drone_route', cur.lastrowid, f'{name} ({len(body.waypoints)} nokta)')
    return {'id': cur.lastrowid}


@router.put('/routes/{rid}')
def update_route(rid: int, body: RouteIn, user=Depends(routes_user), conn=db.DB):
    if not conn.execute('SELECT 1 FROM drone_routes WHERE id = ?', (rid,)).fetchone():
        raise HTTPException(404, 'Rota bulunamadı')
    name = _clean(body.name, 120)
    if not name:
        raise HTTPException(400, 'Rota adı gerekli')
    _check_route(conn, body)
    conn.execute('''UPDATE drone_routes SET center_id = ?, name = ?, kind = ?, cruise_alt = ?, cruise_speed = ?, note = ?, active = ?, updated_at = ?
                    WHERE id = ?''',
                 (body.center_id, name, body.kind, body.cruise_alt, body.cruise_speed, _clean(body.note, 1000), int(body.active), db.now(), rid))
    _save_waypoints(conn, rid, body.waypoints)
    db.audit(conn, user['id'], 'Rota güncelledi', 'drone_route', rid, f'{name} ({len(body.waypoints)} nokta)')
    return {'ok': True}


@router.delete('/routes/{rid}')
def delete_route(rid: int, user=Depends(routes_user), conn=db.DB):
    old = db.row(conn.execute('SELECT * FROM drone_routes WHERE id = ?', (rid,)))
    if not old:
        raise HTTPException(404, 'Rota bulunamadı')
    conn.execute('DELETE FROM drone_routes WHERE id = ?', (rid,))   # ara noktalar CASCADE
    db.audit(conn, user['id'], 'Rota sildi', 'drone_route', rid, old['name'])
    return {'ok': True}


@router.get('/routes/{rid}/mission')
def route_mission(rid: int, user=Depends(routes_user), conn=db.DB):
    """Rotayı MAVLink MISSION_ITEM_INT listesine çevirir (köprüye mission_upload komutunun 'items' parametresi).
    Çerçeve MAV_FRAME_GLOBAL_RELATIVE_ALT_INT (6); 0. öğe ev konumu yerine ilk nokta (ArduPilot ev noktasını kendi ekler)."""
    r = get_route(rid, user, conn)
    cmd = {'waypoint': 16, 'loiter': 19, 'takeoff': 22, 'land': 21, 'rtl': 20}   # MAV_CMD_NAV_*: WAYPOINT, LOITER_TIME, TAKEOFF, LAND, RETURN_TO_LAUNCH
    items = []
    wps = r['waypoints']
    # GÖKTUNGU rota mekanizması: rotanın İLK öğesi TAKEOFF'tur (irtifa = ilk noktanın irtifası, en az 2 m). "Rotayı başlat"
    # ARM + AUTO yapar, kalkışı ArduPilot bu öğeyle kendisi yapar. Kullanıcı ilk noktayı zaten 'takeoff' yaptıysa eklenmez.
    auto_takeoff = bool(wps) and wps[0]['action'] != 'takeoff'
    if auto_takeoff:
        a0 = wps[0]['alt'] if wps[0]['alt'] is not None else (r['cruise_alt'] or 100)
        items.append({'seq': 0, 'frame': 6, 'command': 22, 'current': 1, 'autocontinue': 1, 'param1': 0.0, 'param2': 0.0, 'param3': 0.0,
                      'param4': 0.0, 'x': 0, 'y': 0, 'z': float(max(2.0, a0)), 'mission_type': 0})
    for w in wps:
        i = len(items)
        alt = w['alt'] if w['alt'] is not None else (r['cruise_alt'] or 100)
        items.append({'seq': i, 'frame': 6, 'command': cmd[w['action']], 'current': 1 if i == 0 else 0, 'autocontinue': 1,
                      'param1': float(w['hold_s'] or 0), 'param2': 0.0, 'param3': 0.0, 'param4': 0.0,
                      'x': int(round(w['lat'] * 1e7)), 'y': int(round(w['lon'] * 1e7)), 'z': float(alt), 'mission_type': 0})
    if r['kind'] == 'loop' and len(wps) > 1:   # döngü: son noktadan ilk ROTA noktasına (kalkış öğesine değil) DO_JUMP (177) sonsuz tekrar
        items.append({'seq': len(items), 'frame': 2, 'command': 177, 'current': 0, 'autocontinue': 1,
                      'param1': 1.0 if auto_takeoff else 0.0, 'param2': -1.0, 'param3': 0.0, 'param4': 0.0, 'x': 0, 'y': 0, 'z': 0.0, 'mission_type': 0})
    return {'route_id': rid, 'name': r['name'], 'items': items, 'cruise_speed': r['cruise_speed'], 'auto_takeoff': auto_takeoff}
