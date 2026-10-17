"""CAYSIM istemci API'si — sözleşme docs/caysim-api.md (v1; kod belgeye birebir uyar).

Üç yüz:
- Yönetim (HEPGO web, oturum çerezi, `drone.sim`): `/api/drone/sim/clients` — istemci kayıtları; kod `<domain>/<key>` yalnız oluşturma/rekey yanıtında.
- CAYSIM REST (`/api/caysim/v1`, `Authorization: Bearer <key>`): hello, marka, merkezler, tipler, modeller, dünya varsayılanları, arazi vekili,
  Google anahtarı, loglar, oturumlar, komut, ham MAVLink bilgisi. Web router'ının (routers/flightsim.py) işlevleri yeniden kullanılır.
- CAYSIM WS (`/ws/caysim/v1/sessions/{id}`): `?key=` ya da ilk çerçeve `{t:'auth', key}`; sonrası web WS ile aynı döngü (flightsim_router.ws_dongu).
Hata gövdesi: `{"detail": {"error": "<kod>", "message": "<metin>"}}` (422 doğrulama hatası FastAPI biçiminde kalır).
"""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, caysim, config, db, drone_hub, flightsim, flightsim_models, flightsim_replay, sim_terrain
from . import flightsim as fs
from .drone import _req_host, bridge_code
from .system import get_brand_logo

V1 = '/api/caysim/v1'
router = APIRouter(prefix=V1)            # CAYSIM istemcisi (Bearer)
admin_router = APIRouter(prefix='/api/drone/sim')   # HEPGO web yönetimi (çerez)
ws_router = APIRouter()
sim_user = auth.require_module(fs.MODUL)
AUTH_BEKLEME_S = 15                     # WS: ilk `auth` çerçevesi için süre (köprüdeki gibi)
_HATA_KODU = {400: 'invalid', 401: 'auth', 403: 'forbidden', 404: 'not_found', 409: 'limit', 413: 'too_large', 429: 'rate_limited', 503: 'sitl'}
_KIMLIK_HTTP = {'auth': 401, 'client_inactive': 403, 'rate_limited': 429}
_KIMLIK_WS = {'auth': 4403, 'client_inactive': 4403, 'rate_limited': 4429}
_KIMLIK_MESAJ = {'auth': 'Kimlik doğrulanamadı: istemci anahtarı yok ya da yanlış', 'client_inactive': 'İstemci kaydı pasif',
                 'rate_limited': 'Çok fazla başarısız kimlik denemesi; 60 sn bekleyin'}


class ClientIn(BaseModel):
    name: str
    platform: Optional[str] = None
    owner_id: Optional[int] = None
    note: Optional[str] = None
    active: bool = True


class ClientPatch(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    owner_id: Optional[int] = None
    note: Optional[str] = None
    active: Optional[bool] = None


# ---------------- ortak ----------------
def _hata(status, kod, mesaj):
    raise HTTPException(status, {'error': kod, 'message': mesaj})


def _cevir(exc: HTTPException):
    """Yeniden kullanılan web işlevlerinin düz metin HTTPException'ını CAYSIM hata biçimine çevirir."""
    if isinstance(exc.detail, dict) and 'error' in exc.detail:
        raise exc
    _hata(exc.status_code, _HATA_KODU.get(exc.status_code, 'error'), str(exc.detail))


def _ip(req):
    return (req.client.host if req.client else '') or ''


def _clean(s, n):
    s = (s or '').strip() if isinstance(s, str) else ''
    return s[:n] or None


def _url_cevir(obj):
    """Model/arazi nesnelerindeki web yollarını CAYSIM yollarına çevirir (`/api/drone/sim/...` → `/api/caysim/v1/...`; dahili GLB'nin
    `/static/...` yolu → `/models/{id}/glb`). Yalnız istemcinin Bearer ile erişebileceği uçlar kalır."""
    if isinstance(obj, list):
        return [_url_cevir(x) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == 'glb_url' and isinstance(v, str) and v.startswith('/static/') and obj.get('id'):
                v = f"{V1}/models/{obj['id']}/glb"
            elif k == 'file_url':
                v = None
            elif isinstance(v, str) and v.startswith('/api/drone/sim/'):
                v = V1 + v[len('/api/drone/sim'):]
            else:
                v = _url_cevir(v)
            out[k] = v
        return out
    return obj


def _oturum(sid):
    s = flightsim.MANAGER.get(sid)
    if s is None:
        _hata(404, 'not_found', 'Oturum bulunamadı')
    return s


def _sess_dict(s, request):
    return _url_cevir(s.to_dict(fs._host(request)))


# ---------------- kimlik (Bearer) ----------------
def client_dep(request: Request):
    try:
        return caysim.resolve_key(caysim.bearer(request.headers), _ip(request))
    except caysim.KimlikHata as e:
        _hata(_KIMLIK_HTTP[e.kod], e.kod, _KIMLIK_MESAJ[e.kod])


CLIENT = Depends(client_dep)


@router.options('/{path:path}', include_in_schema=False)
def options_any(path: str):
    """Masaüstü istemci tarayıcı değil → CORS gerekmez; yine de gelen OPTIONS 204 (gövdesiz)."""
    return Response(status_code=204)


# ---------------- hello / marka ----------------
@router.get('/hello')
def hello(request: Request, host: Optional[str] = None, client_ver: Optional[str] = None, platform: Optional[str] = None, client=CLIENT, conn=db.DB):
    h = request.headers
    with_host = h.get('x-caysim-host') or host
    ver = h.get('x-caysim-ver') or client_ver
    plat = (h.get('x-caysim-platform') or platform or '').strip().lower() or None
    caysim.gorulme(conn, client['id'], with_host, ver, plat)
    caps = list(caysim.CAPS) + (['google3d'] if flightsim.google3d_etkin() else [])
    renk = None
    try:
        from .system import _brand
        renk = _brand(conn).get('color') or None
    except Exception:   # noqa: BLE001
        renk = None
    return {'v': 1, 'server_time': db.now(),
            'client': {'id': client['id'], 'name': client['name'], 'owner': caysim.sahip(conn, client)},
            'company': {'name': config.COMPANY_NAME, 'legal_name': config.COMPANY_LEGAL_NAME or None, 'logo_url': f'{V1}/brand/logo', 'primary_color': renk},
            'caps': caps,
            'limits': {'max_sessions': flightsim.MAX_SESSIONS, 'max_minutes': flightsim.MAX_MINUTES, 'rc_hz': int(round(1 / flightsim.RC_HZ_MIN_ARALIK)), 'tele_hz': flightsim.TELE_HZ},
            'host': fs._host(request), 'google3d': {'enabled': flightsim.google3d_etkin()}, 'sitl': {'enabled': flightsim.SITL_ENABLED},
            'ws_url': '/ws/caysim/v1/sessions/{id}'}


@router.get('/brand/logo')
def brand_logo(client=CLIENT, conn=db.DB):
    """Şirket logosu (routers/system.get_brand_logo kalıbı); hiçbiri yoksa HEPGO varsayılan logosu."""
    try:
        return get_brand_logo(conn)
    except HTTPException:
        p = config.STATIC_DIR / 'img' / 'logo.png'
        if p.is_file():
            return FileResponse(p, headers={'Cache-Control': 'private, max-age=3600'})
        _hata(404, 'not_found', 'Logo yok')


# ---------------- kataloglar ----------------
@router.get('/centers')
def centers(client=CLIENT, conn=db.DB):
    return {'centers': fs._centers(conn)}


@router.get('/types')
def types(client=CLIENT):
    return {'types': flightsim.tipler()}


@router.get('/models')
def models(type: Optional[str] = None, client=CLIENT, conn=db.DB):
    if type is not None and type not in flightsim.TIP_ADLARI:
        _hata(400, 'invalid', 'type geçersiz')
    return {'models': _url_cevir(flightsim_models.listele(conn, type)), 'defaults': dict(flightsim_models.VARSAYILAN)}


@router.get('/models/{mid}/glb')
def model_glb(mid: str, client=CLIENT, conn=db.DB):
    k = flightsim_models.kimlik_coz(mid)
    if not k:
        _hata(404, 'not_found', 'Model bulunamadı')
    if k[0] == 'builtin':
        b = flightsim_models.BUILTIN[k[1]]
        p = config.STATIC_DIR / b['glb'] if b.get('format') == 'glb' else None
    else:
        p = flightsim_models.glb_yolu(conn, k[1])
    if not p or not p.is_file():
        _hata(404, 'not_found', 'GLB yok (dahili prosedürel model ya da henüz üretilmedi)')
    return FileResponse(p, media_type='model/gltf-binary', headers={'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff'})


@router.get('/models/{mid}/thumb')
def model_thumb(mid: str, type: Optional[str] = None, client=CLIENT, conn=db.DB):
    if not flightsim_models.kimlik_coz(mid):
        _hata(404, 'not_found', 'Model bulunamadı')
    p = flightsim_models.thumb_yolu(conn, mid, type)
    if not p:
        _hata(404, 'not_found', 'Küçük resim yok')
    return FileResponse(p, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600', 'X-Content-Type-Options': 'nosniff'})


@router.get('/world-defaults')
def world_defaults(client=CLIENT):
    return {'world_defaults': dict(flightsim.WORLD_DEFAULTS),
            'limits': {k: [alt, ust] for k, (_t, alt, ust) in flightsim._WORLD_SINIR.items()},
            'modes': list(flightsim._WORLD_KIP), 'times': list(flightsim._WORLD_ZAMAN)}


# ---------------- arazi vekili (sim_terrain; web ile aynı) ----------------
@router.get('/terrain')
def terrain(lat: float, lon: float, size_m: float = 4000, client=CLIENT):
    try:
        return _url_cevir(sim_terrain.terrain_plani(lat, lon, size_m))
    except ValueError as e:
        _hata(400, 'invalid', str(e))


@router.get('/tile/{kind}/{z}/{x}/{y}')
def tile(kind: str, z: int, x: int, y: int, client=CLIENT):
    try:
        data, ctype = sim_terrain.karo(kind, z, x, y)
    except ValueError as e:
        _hata(404, 'not_found', str(e))
    except sim_terrain.KaynakHata as e:
        _hata(e.kod, _HATA_KODU.get(e.kod, 'sitl'), str(e))
    return Response(content=data, media_type=ctype, headers={'Cache-Control': 'private, max-age=86400'})


@router.get('/osm')
def osm(lat: float, lon: float, size_m: float = 4000, client=CLIENT):
    try:
        return sim_terrain.osm(lat, lon, size_m)
    except ValueError as e:
        _hata(400, 'invalid', str(e))
    except sim_terrain.KaynakHata as e:
        _hata(e.kod, _HATA_KODU.get(e.kod, 'sitl'), str(e))


@router.get('/g3d-key')
def g3d_key(client=CLIENT):
    if not flightsim.google3d_etkin():
        _hata(404, 'not_found', 'Google 3B kipi yapılandırılmamış')
    return Response(content=json.dumps({'key': flightsim.GOOGLE_KEY}), media_type='application/json',
                    headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


# ---------------- loglar / oturumlar ----------------
@router.get('/logs')
def logs(q: Optional[str] = None, client=CLIENT, conn=db.DB):
    return {'logs': flightsim_replay.loglari_listele(conn, caysim.sahip_kullanici(conn, client), q)}


@router.get('/sessions')
def sessions(request: Request, client=CLIENT):
    return {'sessions': _url_cevir(flightsim.MANAGER.listele(fs._host(request)))}


@router.post('/sessions', status_code=201)
async def open_session(body: fs.SessionIn, request: Request, client=CLIENT):
    loop = asyncio.get_running_loop()

    def yukle():
        with db.connect() as conn:
            return caysim.sahip(conn, client), caysim.sahip_kullanici(conn, client)
    owner, user = await loop.run_in_executor(None, yukle)
    try:
        s = await fs.oturum_ac(body, owner, user, owner.get('id'), client=client)
    except HTTPException as e:
        _cevir(e)
    return _sess_dict(s, request)


@router.get('/sessions/{sid}')
def get_session(sid: int, request: Request, client=CLIENT):
    return _sess_dict(_oturum(sid), request)


@router.delete('/sessions/{sid}')
async def close_session(sid: int, client=CLIENT):
    if not await flightsim.MANAGER.kapat(sid, 'kapatildi'):
        _hata(404, 'not_found', 'Oturum bulunamadı')

    def audit():
        with db.connect() as conn:
            db.audit(conn, caysim.sahip(conn, client).get('id'), 'Uçuş simülatörü oturumunu kapattı', 'drone_sim', sid, f"CAYSIM istemcisi {client['name']}")
            conn.commit()
    await asyncio.get_running_loop().run_in_executor(None, audit)
    return {'ok': True}


@router.post('/sessions/{sid}/cmd')
async def session_cmd(sid: int, body: fs.CmdIn, client=CLIENT):
    s = _oturum(sid)
    try:
        return await s.komut(body.name, body.params or {}, kaynak=f"caysim:{client['id']}")
    except flightsim.SimHata as e:
        _hata({'invalid': 400, 'limit': 409, 'sitl': 503}.get(e.kod, 400), e.kod, str(e))


@router.get('/sessions/{sid}/replay')
def get_replay(sid: int, client=CLIENT):
    try:
        return fs.get_replay(sid, user=None)
    except HTTPException as e:
        _cevir(e)


@router.get('/sessions/{sid}/mavlink')
def session_mavlink(sid: int, request: Request, client=CLIENT):
    """Ham MAVLink isteyen istemci için SITL UDP kapısı (Mission Planner ile aynı kapı; GCS kilidi: oturumda tek UDP GCS)."""
    s = _oturum(sid)
    if getattr(s, 'mode', 'sitl') != 'sitl':
        _hata(400, 'invalid', 'Kayıttan oynatma oturumunda MAVLink kapısı yok')
    return {'host': fs._host(request), 'udp_port': s.udp_port, 'gcs_locked': s.gcs_addr is not None,
            'gcs_addr': f'{s.gcs_addr[0]}:{s.gcs_addr[1]}' if s.gcs_addr else None,
            'note': 'İlk paket gönderen adres GCS olarak kilitlenir; 30 sn sessizlikte kilit kalkar. Komut için WS/REST cmd yeterlidir.'}


# ---------------- WebSocket: /ws/caysim/v1/sessions/{id} ----------------
@ws_router.websocket('/ws/caysim/v1/sessions/{sid}')
async def ws_caysim(ws: WebSocket, sid: int, key: Optional[str] = Query(None)):
    await ws.accept()
    ip = (ws.client.host if ws.client else '') or ''
    loop = asyncio.get_running_loop()
    if not key:   # ilk çerçeve {t:'auth', key} (15 sn)
        try:
            raw = await asyncio.wait_for(ws.receive_text(), AUTH_BEKLEME_S)
            msg = json.loads(raw)
            key = msg.get('key') if isinstance(msg, dict) and msg.get('t') == 'auth' else None
        except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
            await drone_hub._safe_send(ws, {'t': 'error', 'error': 'timeout'})
            await ws.close(code=4400)
            return
        if not key:
            await drone_hub._safe_send(ws, {'t': 'error', 'error': 'auth'})
            await ws.close(code=4400)
            return
    try:
        client = await loop.run_in_executor(None, caysim.resolve_key, key, ip)
    except caysim.KimlikHata as e:
        await drone_hub._safe_send(ws, {'t': 'error', 'error': e.kod})
        await ws.close(code=_KIMLIK_WS[e.kod])
        return
    s = flightsim.MANAGER.get(sid)
    if s is None:
        await drone_hub._safe_send(ws, {'t': 'error', 'error': 'not_found'})
        await ws.close(code=4404)
        return
    host = flightsim.PUBLIC_HOST or _req_host(ws) or None
    cid = client['id']

    def gorulme():
        with db.connect() as conn:
            caysim.gorulme(conn, cid)
            conn.commit()
    await loop.run_in_executor(None, gorulme)
    caysim.ws_ekle(cid, ws)
    try:
        await fs.ws_dongu(ws, s, {'t': 'hello', 'session': _url_cevir(s.to_dict(host)), 'can_command': True, 'v': 1, 'server_time': db.now()},
                          True, f'caysim:{cid}')
    finally:
        if not caysim.ws_sil(cid, ws):
            def kapandi():
                with db.connect() as conn:
                    caysim.cevrimdisi(conn, cid)
                    conn.commit()
            try:
                await loop.run_in_executor(None, kapandi)
            except Exception:   # noqa: BLE001
                pass


# ======================================================================
# Yönetim: /api/drone/sim/clients (HEPGO web; drone.sim okuma/yazma)
# ======================================================================
@admin_router.get('/clients')
def list_clients(user=Depends(sim_user), conn=db.DB):
    """Anahtar/kod dönmez (yalnız has_key)."""
    return {'clients': caysim.listele(conn), 'can_write': fs.MODUL in user.get('write_modules', []), 'platforms': list(caysim.PLATFORMS)}


@admin_router.post('/clients', status_code=201)
def add_client(body: ClientIn, request: Request, user=Depends(sim_user), conn=db.DB):
    """İstemci oluşturur ve İSTEMCİ KODU döndürür ({id, code}; code = <domain>/<key>; yalnız bu yanıtta). Sahip verilmezse oluşturan."""
    name = _clean(body.name, 80)
    if not name:
        raise HTTPException(400, 'İstemci adı gerekli')
    if body.platform and body.platform not in caysim.PLATFORMS:
        raise HTTPException(400, 'Geçersiz platform')
    if conn.execute('SELECT 1 FROM drone_sim_clients WHERE name = ? COLLATE NOCASE', (name,)).fetchone():
        raise HTTPException(400, 'Bu adda istemci var')
    owner = body.owner_id or user['id']
    if not conn.execute('SELECT 1 FROM users WHERE id = ?', (owner,)).fetchone():
        raise HTTPException(400, 'Sahip kullanıcı bulunamadı')
    cur = conn.execute('INSERT INTO drone_sim_clients (name, platform, owner_id, note, active, created_by, created_at) VALUES (?,?,?,?,?,?,?)',
                       (name, body.platform, owner, _clean(body.note, 1000), int(body.active), user['id'], db.now()))
    key = caysim.issue_key(conn, cur.lastrowid)
    db.audit(conn, user['id'], 'CAYSIM istemcisi ekledi', 'drone_sim_client', cur.lastrowid, f'{name} · istemci kodu üretildi')
    return {'id': cur.lastrowid, 'code': bridge_code(conn, _req_host(request), key)}


@admin_router.put('/clients/{cid}')
async def update_client(cid: int, body: ClientPatch, user=Depends(sim_user), conn=db.DB):
    old = db.row(conn.execute('SELECT * FROM drone_sim_clients WHERE id = ?', (cid,)))
    if not old:
        raise HTTPException(404, 'İstemci bulunamadı')
    d = body.model_dump(exclude_unset=True)
    name = _clean(d.get('name', old['name']), 80)
    if not name:
        raise HTTPException(400, 'İstemci adı gerekli')
    platform = d.get('platform', old['platform'])
    if platform and platform not in caysim.PLATFORMS:
        raise HTTPException(400, 'Geçersiz platform')
    if conn.execute('SELECT 1 FROM drone_sim_clients WHERE name = ? COLLATE NOCASE AND id != ?', (name, cid)).fetchone():
        raise HTTPException(400, 'Bu adda istemci var')
    active = int(d['active']) if 'active' in d and d['active'] is not None else old['active']
    conn.execute('UPDATE drone_sim_clients SET name = ?, platform = ?, owner_id = ?, note = ?, active = ?, updated_at = ? WHERE id = ?',
                 (name, platform, d.get('owner_id', old['owner_id']), _clean(d.get('note', old['note']), 1000), active, db.now(), cid))
    db.audit(conn, user['id'], 'CAYSIM istemcisini güncelledi', 'drone_sim_client', cid, name)
    if not active:
        await caysim.ws_kapat_hepsi(cid)   # pasif: açık bağlantılar düşer
    return {'ok': True}


@admin_router.post('/clients/{cid}/rekey')
async def rekey_client(cid: int, request: Request, user=Depends(sim_user), conn=db.DB):
    """Yeni anahtar + kod ({key, code}; düz metin yalnız bu yanıtta); eski anahtar hemen geçersiz, açık WS'ler 4403."""
    c = db.row(conn.execute('SELECT id, name FROM drone_sim_clients WHERE id = ?', (cid,)))
    if not c:
        raise HTTPException(404, 'İstemci bulunamadı')
    key = caysim.issue_key(conn, cid)
    db.audit(conn, user['id'], 'CAYSIM istemcisi anahtarını yeniledi', 'drone_sim_client', cid, c['name'])
    conn.commit()
    await caysim.ws_kapat_hepsi(cid)
    return {'key': key, 'code': bridge_code(conn, _req_host(request), key)}


@admin_router.delete('/clients/{cid}')
async def delete_client(cid: int, user=Depends(sim_user), conn=db.DB):
    old = db.row(conn.execute('SELECT id, name FROM drone_sim_clients WHERE id = ?', (cid,)))
    if not old:
        raise HTTPException(404, 'İstemci bulunamadı')
    conn.execute('DELETE FROM drone_sim_clients WHERE id = ?', (cid,))
    db.audit(conn, user['id'], 'CAYSIM istemcisini sildi', 'drone_sim_client', cid, old['name'])
    conn.commit()
    await caysim.ws_kapat_hepsi(cid)   # istemcinin açtığı oturumlar kapanmaz (sahibine kalır)
    return {'ok': True}
