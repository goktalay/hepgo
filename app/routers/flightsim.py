"""Uçuş Simülatörü REST + WebSocket (`/api/drone/sim`, `/ws/drone/sim/{id}`; sözleşme docs/ucus-simulatoru.md §2–§3).

Yetki: `auth.require_module('drone.sim')` — GET okuma, POST/DELETE yazma izni ister (Rol Yönetimi; `drone` üst düğümünden miras).
WS: oturum çerezi, drone_hub._ws_user kalıbı; `cmd`/`rc` için yazma izni (`drone.sim` ∈ write_modules), aksi hâlde yalnız izler.
"""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, db, drone_hub, flightsim, flightsim_replay, sim_terrain
from .drone import _req_host

router = APIRouter(prefix='/api/drone/sim')
ws_router = APIRouter()
sim_user = auth.require_module('drone.sim')
MODUL = 'drone.sim'


class SessionIn(BaseModel):
    mode: str = 'sitl'                 # 'sitl' (SITL + Mission Planner) | 'replay' (kayıttan oynatma; type/center_id yerine log_id)
    type: Optional[str] = None
    center_id: Optional[int] = None
    log_id: Optional[int] = None
    world: Optional[dict] = None
    airframe: Optional[str] = None   # sabit kanat / VTOL 3B gövdesi: caymaz (varsayılan) | delta


class CmdIn(BaseModel):
    name: str
    params: Optional[dict] = None


def _host(request):
    return flightsim.PUBLIC_HOST or _req_host(request) or None


def _hata(e):
    kod = {'invalid': 400, 'limit': 409, 'sitl': 503}.get(e.kod, 400)
    raise HTTPException(kod, str(e))


def _centers(conn, cid=None):
    sql = '''SELECT c.id, c.name, c.lat, c.lon, c.alt, loc.name AS location_name FROM drone_route_centers c
             LEFT JOIN field_locations loc ON loc.id = c.location_id WHERE c.active = 1'''
    if cid is not None:
        return db.row(conn.execute(sql + ' AND c.id = ?', (cid,)))
    return db.rows(conn.execute(sql + ' ORDER BY c.name COLLATE NOCASE'))


@router.get('/meta')
def meta(request: Request, user=Depends(sim_user), conn=db.DB):
    mods = set(user.get('modules') or [])
    return {'types': flightsim.tipler(), 'centers': _centers(conn), 'world_defaults': dict(flightsim.WORLD_DEFAULTS),
            'limits': {'max_sessions': flightsim.MAX_SESSIONS, 'max_minutes': flightsim.MAX_MINUTES}, 'host': _host(request),
            'can_command': MODUL in user.get('write_modules', []),
            # Kayıttan oynatma: uçuş logu listesine erişim flightlogs yetkisiyle kesişir (tools → tümü, field → göreve bağlı olanlar)
            'replay': {'logs_allowed': bool({'tools', 'field'} & mods), 'hz': flightsim_replay.REPLAY_HZ, 'formats': list(flightsim_replay.UZANTILAR)},
            # Google Photorealistic 3D Tiles dünya kipi (§10): yalnız GOOGLE_MAPS_API_KEY tanımlıysa; anahtar /g3d-key ile ayrı verilir
            'google3d': {'enabled': flightsim.google3d_etkin()}}


@router.get('/g3d-key')
def g3d_key(user=Depends(sim_user)):
    """Google Map Tiles API anahtarı (yalnız oturum/önizleme açılırken; `Cache-Control: no-store`). Anahtar Google Cloud'da HTTP referrer
    kısıtlı olmalıdır (docs §10); tarayıcı karoları doğrudan Google'dan çeker, sunucu önbelleklemez. Kip kapalıysa 404."""
    if not flightsim.google3d_etkin():
        raise HTTPException(404, 'Google 3B kipi yapılandırılmamış')
    return Response(content=json.dumps({'key': flightsim.GOOGLE_KEY}), media_type='application/json',
                    headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


@router.get('/logs')
def list_logs(q: Optional[str] = None, user=Depends(sim_user), conn=db.DB):
    """Kayıttan oynatılabilir uçuş logları (analizi TAMAM; .bin/.log/.tlog) — flightlogs yetkisiyle kesişim; `q` ad/dron/pilot/konum/görev arar."""
    return flightsim_replay.loglari_listele(conn, user, q)


@router.get('/sessions')
def list_sessions(request: Request, user=Depends(sim_user)):
    return flightsim.MANAGER.listele(_host(request))


@router.post('/sessions', status_code=201)
async def open_session(body: SessionIn, request: Request, response: Response, user=Depends(sim_user)):
    owner = {'id': user['id'], 'name': user['full_name']}
    loop = asyncio.get_running_loop()
    if body.mode == 'replay':
        if body.log_id is None:
            raise HTTPException(400, 'log_id gerekir')

        def load_log():
            with db.connect() as conn:
                return flightsim_replay.log_getir(conn, body.log_id)
        log = await loop.run_in_executor(None, load_log)
        if not log or not flightsim_replay.log_izinli(user, log):
            raise HTTPException(400, 'Uçuş logu bulunamadı ya da erişim yetkiniz yok')
        try:
            s = await flightsim.MANAGER.ac_replay(log, body.world, owner)
        except flightsim.SimHata as e:
            _hata(e)
        detay = f"kayıttan oynatma · {log['file_name']} (log {log['id']})"
    elif body.mode == 'sitl':
        if not body.type or body.center_id is None:
            raise HTTPException(400, 'type ve center_id gerekir')

        def load():
            with db.connect() as conn:
                return _centers(conn, body.center_id)
        center = await loop.run_in_executor(None, load)
        if not center:
            raise HTTPException(400, 'Merkez bulunamadı (Dron Yönetimi › Rotalar › Merkezler)')
        try:
            s = await flightsim.MANAGER.ac(body.type, center, body.world, owner, body.airframe)
        except flightsim.SimHata as e:
            _hata(e)
        detay = f"{body.type} · {center['name']} · udp {s.udp_port}"
    else:
        raise HTTPException(400, 'mode sitl | replay olmalı')

    def audit():
        with db.connect() as conn:
            db.audit(conn, user['id'], 'Uçuş simülatörü oturumu açtı', 'drone_sim', s.id, detay)
            conn.commit()
    await loop.run_in_executor(None, audit)
    return s.to_dict(_host(request))


@router.get('/sessions/{sid}/replay')
def get_replay(sid: int, user=Depends(sim_user)):
    """Kayıt kareleri: önbellekteki gzip JSON olduğu gibi (Content-Encoding: gzip; tarayıcı/httpx açar). Oturum HAZIR değilse 409."""
    s = flightsim.MANAGER.get(sid)
    if s is None:
        raise HTTPException(404, 'Oturum bulunamadı')
    if getattr(s, 'mode', 'sitl') != 'replay':
        raise HTTPException(400, 'Bu oturum kayıttan oynatma değil')
    if s.state != 'HAZIR':
        raise HTTPException(409, 'Kayıt henüz hazır değil' if s.state == 'BASLIYOR' else (s.sitl.get('error') or 'Kayıt hazırlanamadı'))
    path = flightsim_replay.onbellek_yolu(s.replay['log_id'])
    if not path.exists():
        raise HTTPException(404, 'Kayıt önbelleği bulunamadı')
    return FileResponse(path, media_type='application/json',
                        headers={'Content-Encoding': 'gzip', 'Cache-Control': 'private, max-age=3600', 'Vary': 'Accept-Encoding'})


@router.get('/sessions/{sid}')
def get_session(sid: int, request: Request, user=Depends(sim_user)):
    s = flightsim.MANAGER.get(sid)
    if s is None:
        raise HTTPException(404, 'Oturum bulunamadı')
    return s.to_dict(_host(request))


@router.delete('/sessions/{sid}')
async def close_session(sid: int, user=Depends(sim_user)):
    if not await flightsim.MANAGER.kapat(sid, 'kapatildi'):
        raise HTTPException(404, 'Oturum bulunamadı')

    def audit():
        with db.connect() as conn:
            db.audit(conn, user['id'], 'Uçuş simülatörü oturumunu kapattı', 'drone_sim', sid, None)
            conn.commit()
    await asyncio.get_running_loop().run_in_executor(None, audit)
    return {'ok': True}


@router.post('/sessions/{sid}/cmd')
async def session_cmd(sid: int, body: CmdIn, user=Depends(sim_user)):
    s = flightsim.MANAGER.get(sid)
    if s is None:
        raise HTTPException(404, 'Oturum bulunamadı')
    try:
        return await s.komut(body.name, body.params or {}, kaynak=user['id'])
    except flightsim.SimHata as e:
        _hata(e)


# ---------------- Gerçek topoğrafya vekili (sim_terrain; §8) ----------------
# Senkron uçlar (FastAPI iş parçacığı havuzu); URL'ler modülde sabit — kullanıcı girdisi yalnız sayı (SSRF yok).
def _kaynak(e):
    raise HTTPException(e.kod, str(e))


@router.get('/terrain')
def terrain_plan(lat: float, lon: float, size_m: float = 4000, user=Depends(sim_user)):
    try:
        return sim_terrain.terrain_plani(lat, lon, size_m)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get('/tile/{kind}/{z}/{x}/{y}')
def terrain_tile(kind: str, z: int, x: int, y: int, user=Depends(sim_user)):
    try:
        data, ctype = sim_terrain.karo(kind, z, x, y)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except sim_terrain.KaynakHata as e:
        _kaynak(e)
    return Response(content=data, media_type=ctype, headers={'Cache-Control': 'private, max-age=86400'})


@router.get('/osm')
def terrain_osm(lat: float, lon: float, size_m: float = 4000, user=Depends(sim_user)):
    try:
        return sim_terrain.osm(lat, lon, size_m)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except sim_terrain.KaynakHata as e:
        _kaynak(e)


# ---------------- WebSocket: /ws/drone/sim/{id} ----------------
async def _sender(ws, q):
    try:
        while True:
            await ws.send_text(await q.get())
    except Exception:   # noqa: BLE001
        pass


@ws_router.websocket('/ws/drone/sim/{sid}')
async def ws_sim(ws: WebSocket, sid: int):
    await ws.accept()
    user = await asyncio.get_running_loop().run_in_executor(None, drone_hub._ws_user, ws.cookies.get(auth.COOKIE))
    if not user or MODUL not in user['modules']:
        await drone_hub._safe_send(ws, {'t': 'error', 'error': 'auth'})
        await ws.close(code=4403)
        return
    s = flightsim.MANAGER.get(sid)
    if s is None:
        await drone_hub._safe_send(ws, {'t': 'error', 'error': 'not_found'})
        await ws.close(code=4404)
        return
    yazabilir = MODUL in user.get('write_modules', [])
    host = flightsim.PUBLIC_HOST or _req_host(ws) or None
    q = s.izleyici_ekle(ws)
    sender = asyncio.create_task(_sender(ws, q))
    flightsim._kuyruga(q, json.dumps({'t': 'hello', 'session': s.to_dict(host), 'can_command': yazabilir}, ensure_ascii=False))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            t = msg.get('t')
            if t == 'ping':
                flightsim._kuyruga(q, json.dumps({'t': 'pong'}))
            elif t in ('cmd', 'rc'):
                name = 'rc' if t == 'rc' else str(msg.get('name') or '')
                if not yazabilir:
                    flightsim._kuyruga(q, json.dumps({'t': 'res', 'name': name, 'rid': msg.get('rid'), 'ok': False, 'error': 'Komut için yazma yetkisi gerekir'}, ensure_ascii=False))
                    continue
                try:
                    if t == 'rc':
                        await s.rc(msg.get('ch'))
                        continue   # 20 Hz akış: yanıt yok
                    res = await s.komut(name, msg.get('params') or {}, kaynak=user['id'])
                    flightsim._kuyruga(q, json.dumps({'t': 'res', 'name': name, 'rid': msg.get('rid'), **res}, ensure_ascii=False))
                except flightsim.SimHata as e:
                    flightsim._kuyruga(q, json.dumps({'t': 'res', 'name': name, 'rid': msg.get('rid'), 'ok': False, 'error': str(e)}, ensure_ascii=False))
    except (WebSocketDisconnect, Exception):   # noqa: BLE001
        pass
    finally:
        s.izleyici_sil(ws)
        sender.cancel()
