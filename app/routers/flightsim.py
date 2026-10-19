"""Uçuş Simülatörü REST + WebSocket (`/api/drone/sim`, `/ws/drone/sim/{id}`; sözleşme docs/ucus-simulatoru.md §2–§3).

Yetki: `auth.require_module('drone.sim')` — GET okuma, POST/DELETE yazma izni ister (Rol Yönetimi; `drone` üst düğümünden miras).
WS: oturum çerezi, drone_hub._ws_user kalıbı; `cmd`/`rc` için yazma izni (`drone.sim` ∈ write_modules), aksi hâlde yalnız izler.
"""
import asyncio
import json
from typing import Optional

from typing import Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, config, db, drone_hub, flightsim, flightsim_mission, flightsim_models, flightsim_rec, flightsim_replay, flightsim_runs, sim_terrain
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
    airframe: Optional[str] = None   # ESKİ: sabit kanat / VTOL 3B gövdesi caymaz | delta → model {id:'builtin:…'} olarak eşlenir (§12)
    model: Optional[Union[dict, str]] = None   # görsel model: {id, orient?} ya da kimlik dizgesi ('builtin:caymaz', '12'); eksikse tipin varsayılanı
    drone_id: Optional[int] = None   # §14 isteğe bağlı: Dron Envanteri kaydı — harekât panelinde telemetri bu dronun adıyla akar (yoksa "Simülatör #N")
    rec: Optional[dict] = None       # §19 kayıt seçenekleri: {bin: bool} — SITL DataFlash .BIN kaydı, kapanışta Uçuş Logları'na (yalnız sitl)
    power: Optional[dict] = None     # §23 güç ve yakıt: {max_speed_ms, fuel_l, fuel_km_per_l, elec_cells, elec_mah, elec_w}; eksikler dron kaydı önerisi → tip varsayılanı


class ModelPatch(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    orient: Optional[dict] = None
    has_prop: Optional[bool] = None


class FromDesignIn(BaseModel):
    version_id: int
    type: str
    name: Optional[str] = None


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
    s = await oturum_ac(body, owner, user, user['id'])
    return s.to_dict(_host(request))


async def oturum_ac(body: SessionIn, owner, user, audit_uid, client=None):
    """Oturum açma çekirdeği (web `POST /sessions` ve CAYSIM `POST /api/caysim/v1/sessions` ortak): doğrulama → MANAGER.ac / ac_replay →
    iz kaydı. `user` kayıttan oynatma log yetkisi için (modules); `client` {id, name} verilirse oturuma CAYSIM işareti konur.
    Hatalar HTTPException (400 invalid · 409 limit · 503 sitl)."""
    loop = asyncio.get_running_loop()
    if body.mode == 'replay':
        if body.log_id is None:
            raise HTTPException(400, 'log_id gerekir')

        def load_log():
            with db.connect() as conn:
                log = flightsim_replay.log_getir(conn, body.log_id)
                # görsel model (§12): log'un araç tipine göre kütüphaneden; eksikse tipin varsayılanı
                mdl = flightsim_models.coz(conn, flightsim_replay.arac_tipi((log or {}).get('vehicle')), body.model) if log and body.model else None
                return log, mdl
        try:
            log, mdl = await loop.run_in_executor(None, load_log)
        except flightsim.SimHata as e:
            _hata(e)
        if not log or not flightsim_replay.log_izinli(user, log):
            raise HTTPException(400, 'Uçuş logu bulunamadı ya da erişim yetkiniz yok')
        try:
            s = await flightsim.MANAGER.ac_replay(log, body.world, owner, mdl)
        except flightsim.SimHata as e:
            _hata(e)
        detay = f"kayıttan oynatma · {log['file_name']} (log {log['id']})"
    elif body.mode == 'sitl':
        if not body.type or body.center_id is None:
            raise HTTPException(400, 'type ve center_id gerekir')
        if body.type not in flightsim.TIP_ADLARI:
            raise HTTPException(400, 'Geçersiz dron tipi')

        def load():
            with db.connect() as conn:
                # görsel model (§12): `model` {id, orient} ya da eski `airframe`; bilinmeyen kimlik / tip uyumsuzluğu → 400
                drone = None
                if body.drone_id is not None:   # §14: dron kaydı (yalnız aktif envanter kaydı; sanal/mavlink fark etmez — simülatör SITL'dir)
                    drone = db.row(conn.execute('SELECT id, code, name, model, protocol FROM drone_drones WHERE id = ? AND active = 1', (body.drone_id,)))
                return _centers(conn, body.center_id), flightsim_models.coz(conn, body.type, body.model, body.airframe), drone
        try:
            center, mdl, drone = await loop.run_in_executor(None, load)
        except flightsim.SimHata as e:
            _hata(e)
        if not center:
            raise HTTPException(400, 'Merkez bulunamadı (Dron Yönetimi › Rotalar › Merkezler)')
        if body.drone_id is not None and not drone:
            raise HTTPException(400, 'Dron kaydı bulunamadı (Dron Yönetimi › Dron Envanteri)')
        try:
            s = await flightsim.MANAGER.ac(body.type, center, body.world, owner, body.airframe, mdl, drone, body.rec, body.power)
        except flightsim.SimHata as e:
            _hata(e)
        detay = f"{body.type} · {center['name']} · udp {s.udp_port}" + (f" · dron {drone['code']}" if drone else '') + (' · .bin kaydı' if s.rec['bin'] else '')
        pw = s.power
        detay += f" · güç: {pw.get('max_speed_ms') or '-'} m/s, {pw.get('fuel_l'):g} L @ {pw.get('fuel_km_per_l'):g} km/L, {pw.get('elec_cells')}S {pw.get('elec_mah'):g} mAh {pw.get('elec_w'):g} W"
    else:
        raise HTTPException(400, 'mode sitl | replay olmalı')
    if client:
        s.client = {'id': client['id'], 'name': client['name']}
        detay += f" · CAYSIM istemcisi {client['name']}"

    def audit():
        with db.connect() as conn:
            db.audit(conn, audit_uid, 'Uçuş simülatörü oturumu açtı', 'drone_sim', s.id, detay)
            conn.commit()
    await loop.run_in_executor(None, audit)
    return s


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


@router.get('/sessions/{sid}/live')
def session_live(sid: int, request: Request, user=Depends(sim_user)):
    """§14 harekât paneli bağlamı (static/ops ?sim=<id>; /api/field/tasks/{id}/live biçimi): sahte görev + tek 'sanal' uçuş + can_command
    (drone.sim yazma izni). Kayıttan oynatma oturumunda köprü yok → 400."""
    s = flightsim.MANAGER.get(sid)
    if s is None:
        raise HTTPException(404, 'Oturum bulunamadı')
    from .. import flightsim_hub
    y = flightsim_hub.live_payload(s, user)
    if y is None:
        raise HTTPException(400, 'Bu oturumun harekât paneli köprüsü yok (kayıttan oynatma ya da henüz açılmadı)')
    y['session'] = s.to_dict(_host(request))
    return y


@router.get('/drones')
def sim_drones(user=Depends(sim_user), conn=db.DB):
    """§14 sihirbaz "Dron kaydı (isteğe bağlı)": aktif envanter kayıtları (kod, ad, model, protokol) + §23 güç/yakıt önerisi (`power`:
    dron kaydındaki son ölçümler/ayarlar; boş sözlük = tip varsayılanı)."""
    from .. import drone_params
    rows = db.rows(conn.execute('SELECT id, code, name, model, protocol, status FROM drone_drones WHERE active = 1 ORDER BY code COLLATE NOCASE'))
    for r in rows:
        try:
            r['power'] = drone_params.guc_onerisi(r['id'], conn)
        except Exception:   # noqa: BLE001
            r['power'] = {}
    return rows


@router.get('/power-defaults')
def power_defaults(type: Optional[str] = None, drone_id: Optional[int] = None, user=Depends(sim_user), conn=db.DB):   # noqa: A002
    """§23 sihirbaz "Güç ve yakıt" bölümü: tip varsayılanı (CAYMAZ 45 m/s · 5 L · 25 km/L · 4S 10000 mAh 30 W; kopter yakıtsız) + dron kaydı önerisi
    + sınırlar + stok SITL tam gaz hızı + ikilinin itki ölçeği desteği."""
    from .. import drone_params, drone_sitl, flightsim_power
    tip = type if type in flightsim.TIP_ADLARI else 'sabit_kanat'
    oneri = {}
    if drone_id is not None:
        try:
            oneri = drone_params.guc_onerisi(drone_id, conn)
        except Exception:   # noqa: BLE001
            oneri = {}
    out = flightsim_power.dogrula({}, tip, oneri)
    return {'type': tip, 'defaults': flightsim_power.varsayilanlar(tip), 'suggested': out, 'from_drone': oneri, 'limits': {k: list(v) for k, v in flightsim_power.SINIRLAR.items()},
            'stock_max_ms': round(flightsim_power.plane_tam_gaz_hizi(), 1), 'thr_mul': flightsim_power.thr_mul_icin(out['max_speed_ms']) if out.get('max_speed_ms') else None,
            'thr_scale_supported': drone_sitl.hiz_olcegi_destegi(tip) if flightsim.SITL_ENABLED else False, 'speedups': list(flightsim_power.SPEEDUPS)}


@router.get('/sessions/{sid}')
def get_session(sid: int, request: Request, user=Depends(sim_user)):
    s = flightsim.MANAGER.get(sid)
    if s is None:
        raise HTTPException(404, 'Oturum bulunamadı')
    return s.to_dict(_host(request))


@router.delete('/sessions/{sid}')
async def close_session(sid: int, user=Depends(sim_user)):
    """Kapatır (SITL/UDP kapanır). §19: `rec.bin` açıksa kapanışta DataFlash .BIN uçuş loglarına kaydedilir → `bin: {log_id, file_name, size} | {error} | null`."""
    s = flightsim.MANAGER.get(sid)
    if s is None or not await flightsim.MANAGER.kapat(sid, 'kapatildi'):
        raise HTTPException(404, 'Oturum bulunamadı')

    def audit():
        with db.connect() as conn:
            db.audit(conn, user['id'], 'Uçuş simülatörü oturumunu kapattı', 'drone_sim', sid, None)
            conn.commit()
    await asyncio.get_running_loop().run_in_executor(None, audit)
    return {'ok': True, 'bin': getattr(s, 'bin_sonuc', None)}


@router.post('/sessions/{sid}/cmd')
async def session_cmd(sid: int, body: CmdIn, user=Depends(sim_user)):
    s = flightsim.MANAGER.get(sid)
    if s is None:
        raise HTTPException(404, 'Oturum bulunamadı')
    try:
        return await s.komut(body.name, body.params or {}, kaynak=user['id'])
    except flightsim.SimHata as e:
        _hata(e)


# ---------------- Görev / çarpışma / özet rapor (flightsim_mission; §18) ----------------
class ShareIn(BaseModel):
    text: Optional[str] = None   # istemcinin kendi dilinde rapor metni; boşsa sunucu Türkçe üretir


@router.get('/sessions/{sid}/summary')
async def session_summary(sid: int, user=Depends(sim_user)):
    """Oturum özet raporu (Bitir akışı: kayıt yüklemesinden sonra, kapatmadan önce): istatistikler sunucu izinden; `summary` olayı olarak
    drone_sim_events'e yazılır/güncellenir (dönen `id` ile GET /reports/{id}, paylaşım). Kayıttan oynatma oturumunda 400."""
    s = flightsim.MANAGER.get(sid)
    if s is None:
        raise HTTPException(404, 'Oturum bulunamadı')
    if getattr(s, 'gorev', None) is None:
        raise HTTPException(400, 'Bu oturumun özet raporu yok (kayıttan oynatma)')
    return await s.gorev.ozet_kaydet()


@router.get('/reports')
def list_reports(limit: int = 20, mine: int = 0, user=Depends(sim_user), conn=db.DB):
    """Son simülasyon raporları (sihirbaz "Son simülasyon raporları"); `mine=1` yalnız kendi oturumlarım."""
    return {'items': flightsim_mission.raporlar(conn, limit, user['id'] if mine else None)}


@router.get('/reports/{rid}')
def get_report(rid: int, user=Depends(sim_user), conn=db.DB):
    d = flightsim_mission.rapor(conn, rid)
    if not d:
        raise HTTPException(404, 'Rapor bulunamadı')
    return d


@router.post('/reports/{rid}/share')
async def share_report(rid: int, body: ShareIn, user=Depends(sim_user), conn=db.DB):
    """Raporu metin olarak Şirketten Haberler'e paylaş (yazma izni; paylaşım rapor sahibi adına, sahip yoksa paylaşan)."""
    d = flightsim_mission.rapor(conn, rid)
    if not d:
        raise HTTPException(404, 'Rapor bulunamadı')
    owner_id = (d.get('owner') or {}).get('id') or user['id']
    owner = db.row(conn.execute('SELECT id, full_name FROM users WHERE id = ?', (owner_id,))) or {'id': user['id'], 'full_name': user['full_name']}
    txt = (body.text or '').strip()[:4000] or flightsim_mission.rapor_metni(d)
    from .. import feed
    pid = feed.add_post(conn, owner['id'], txt, None)
    db.audit(conn, user['id'], 'Uçuş simülatörü raporunu paylaştı', 'feed', pid, f'rapor {rid} · oturum {d.get("session_id")}')
    conn.commit()
    from .feed import _announce
    await _announce(conn, pid, owner, txt, [])
    return {'ok': True, 'post_id': pid, 'text': txt, 'link': '#/home'}


# ---------------- Simülasyon kayıtları (flightsim_runs; §21) ----------------
# Her oturum kapanışında bir satır: özet + .bin + video + son parametreler (.param) + scripts (zip). Liste/tek kayıt/video okuma izni;
# parametre ve script indirme YALNIZ MASTER (403); silme sahip ya da yazma izni (DELETE → require_module yazma ister).
def _master(user):
    if not user.get('master'):
        raise HTTPException(403, 'Bu dosyayı yalnız sistem sahibi (MASTER) indirebilir')


def _run(conn, rid, user):
    r = flightsim_runs.getir(conn, rid, user)
    if not r:
        raise HTTPException(404, 'Simülasyon kaydı bulunamadı')
    return r


@router.get('/runs')
def list_runs(request: Request, user=Depends(sim_user), conn=db.DB):
    """`?from&to&center_id&type&owner_id&result&mode&q&sort&page` → `{items, total, page, pages, per_page, facets:{centers, owners, types}}`.
    `sort`: started_at | owner | type | center | duration_s | result | mode (başına - → azalan)."""
    qp = request.query_params

    def _int(k):
        v = qp.get(k)
        try:
            return int(v) if v not in (None, '') else None
        except ValueError:
            raise HTTPException(400, f'{k} tam sayı olmalı')
    return flightsim_runs.listele(conn, user, dfrom=qp.get('from') or None, dto=qp.get('to') or None, center_id=_int('center_id'), type=qp.get('type') or None,
                                  owner_id=_int('owner_id'), result=qp.get('result') or None, mode=qp.get('mode') or None, q=qp.get('q') or None,
                                  sort=qp.get('sort') or '-started_at', page=_int('page') or 1)


@router.get('/runs/stats')
def runs_stats(days: int = 30, user=Depends(sim_user), conn=db.DB):
    """Sayfa üstü bilgi kutuları: `{days, total, total_all, flight_s, avg_s, crash, crash_events, crash_rate, last_crash_at, open_sessions, last_run}`.
    `/runs/{rid}`'den ÖNCE tanımlıdır (yoksa 'stats' tam sayıya çözülemez → 422)."""
    acik = sum(1 for s in flightsim.MANAGER.sessions.values() if s.state != 'KAPANDI')
    return flightsim_runs.istatistik(conn, days, acik)


@router.get('/runs/{rid}')
def get_run(rid: int, user=Depends(sim_user), conn=db.DB):
    return _run(conn, rid, user)


@router.get('/runs/{rid}/params')
def run_params(rid: int, user=Depends(sim_user), conn=db.DB):
    """Son parametre dökümü (.param, Mission Planner biçimi) — YALNIZ MASTER."""
    _master(user)
    r = _run(conn, rid, user)
    d = flightsim_runs.dosya(r, 'params')
    if not d:
        raise HTTPException(404, 'Bu kaydın parametre dökümü yok')
    return FileResponse(d[0], media_type=d[2], filename=d[1], headers={'Cache-Control': 'private, no-store'})


@router.get('/runs/{rid}/scripts')
def run_scripts(rid: int, user=Depends(sim_user), conn=db.DB):
    """SITL scripts/ içeriği (zip) — YALNIZ MASTER."""
    _master(user)
    r = _run(conn, rid, user)
    d = flightsim_runs.dosya(r, 'scripts')
    if not d:
        raise HTTPException(404, 'Bu kaydın script arşivi yok')
    return FileResponse(d[0], media_type=d[2], filename=d[1], headers={'Cache-Control': 'private, no-store'})


@router.get('/runs/{rid}/bin')
def run_bin(rid: int, user=Depends(sim_user), conn=db.DB):
    """Kapanışta kaydedilen SITL .BIN uçuş logu (flight_logs; §19) — drone.sim okuma izniyle indirme."""
    r = _run(conn, rid, user)
    if not r.get('bin_log_id'):
        raise HTTPException(404, 'Bu kaydın .bin uçuş logu yok')
    lg = db.row(conn.execute('SELECT file, file_name FROM flight_logs WHERE id = ?', (r['bin_log_id'],)))
    if not lg or not lg.get('file') or '..' in lg['file']:
        raise HTTPException(404, 'Uçuş logu dosyası bulunamadı')
    p = config.UPLOAD_DIR / lg['file']
    if not p.is_file():
        raise HTTPException(404, 'Uçuş logu dosyası bulunamadı')
    return FileResponse(p, media_type='application/octet-stream', filename=lg.get('file_name') or p.name, headers={'Cache-Control': 'private, no-store'})


@router.get('/runs/{rid}/video')
def run_video(rid: int, dl: int = 0, user=Depends(sim_user), conn=db.DB):
    """Ekran kaydı: paylaşılmışsa Şirketten Haberler dosyası (UPLOAD_DIR/feed/…), değilse saklanan/yarım kayıt (sim_rec)."""
    r = _run(conn, rid, user)
    p, mime = None, 'video/webm'
    if r.get('video_path') and '..' not in r['video_path'] and r['video_path'].startswith('feed/'):
        cand = config.UPLOAD_DIR / r['video_path']
        if cand.is_file():
            p = cand
            mime = {'.mp4': 'video/mp4', '.mkv': 'video/x-matroska'}.get(cand.suffix.lower(), 'video/webm')
    if p is None and r.get('video_rec_id'):
        v = flightsim_rec.video_yolu(r['video_rec_id'])
        if v:
            p, mime = v[0], v[1]
    if p is None:
        raise HTTPException(404, 'Bu kaydın videosu yok')
    ts = (r.get('started_at') or '')[:16].replace(':', '-').replace('T', '-')
    ad = f"ucus-simulatoru-{r['session_id']}-{ts}{p.suffix}"
    hdr = {'Cache-Control': 'private, no-store'}
    if dl:
        return FileResponse(p, media_type=mime, filename=ad, headers=hdr)
    return FileResponse(p, media_type=mime, headers=hdr)


@router.delete('/runs/{rid}')
def delete_run(rid: int, user=Depends(sim_user), conn=db.DB):
    """Kayıt satırı + params/scripts dosyaları silinir (sahip ya da yazma izni). Özet, .bin ve video kendi yerlerinde kalır."""
    r = _run(conn, rid, user)
    if not (user.get('master') or r.get('owner_id') == user['id'] or _yazar(user)):
        raise HTTPException(403, 'Bu kaydı silme yetkiniz yok')
    flightsim_runs.sil(conn, rid)
    db.audit(conn, user['id'], 'Uçuş simülatörü kaydını sildi', 'drone_sim_run', rid, f"oturum {r.get('session_id')} · {r.get('started_at')}")
    conn.commit()
    return {'ok': True}


# ---------------- Ekran kaydı (flightsim_rec; §17) ----------------
# Tarayıcı MediaRecorder parçaları oturum boyunca akıtılır; Bitir'de dosya Şirketten Haberler deposuna taşınır, oturum SAHİBİ adına paylaşım.
# Yetki: start oturum sahibi ya da drone.sim yazma izni; chunk/thumb/finish/delete başlatan, sahip ya da yazma izni. GET /rec/pending yarım kayıtlar.
class RecStartIn(BaseModel):
    mime: Optional[str] = None


class RecFinishIn(BaseModel):
    duration_s: Optional[float] = None
    mime: Optional[str] = None
    text: Optional[str] = None   # istemcinin kendi dilinde ürettiği metin (aynı yapı); boşsa sunucu Türkçe üretir
    share: bool = True           # False: Şirketten Haberler'e paylaşmaz, dosya sunucuda saklanır ("Kayıtlarım": indir / sonradan paylaş / sil)


def _rec_hata(e):
    raise HTTPException(e.kod, str(e))


def _yazar(user):
    return MODUL in user.get('write_modules', [])


@router.post('/sessions/{sid}/rec/start', status_code=201)
def rec_start(sid: int, body: RecStartIn, user=Depends(sim_user)):
    s = flightsim.MANAGER.get(sid)
    if s is None:
        raise HTTPException(404, 'Oturum bulunamadı')
    try:
        m = flightsim_rec.basla(s.to_dict(), user, _yazar(user), body.mime)
    except flightsim_rec.RecHata as e:
        _rec_hata(e)
    return {'rec_id': m['id'], 'max_bytes': m['max_bytes'], 'chunk_max': flightsim_rec.CHUNK_MAX, 'ext': m['ext']}


@router.put('/rec/{rec_id}/chunk')
async def rec_chunk(rec_id: str, request: Request, seq: int = 0, user=Depends(sim_user)):
    data = await _govde(request, flightsim_rec.CHUNK_MAX)
    try:
        m = await asyncio.get_running_loop().run_in_executor(None, flightsim_rec.parca, rec_id, user, _yazar(user), seq, data)
    except flightsim_rec.RecHata as e:
        _rec_hata(e)
    return {'ok': True, 'seq': m['seq'], 'size': m['size'], 'max_bytes': m.get('max_bytes')}


@router.put('/rec/{rec_id}/thumb')
async def rec_thumb(rec_id: str, request: Request, user=Depends(sim_user)):
    data = await _govde(request, flightsim_rec.THUMB_MAX)
    try:
        flightsim_rec.kucuk_resim(rec_id, user, _yazar(user), data)
    except flightsim_rec.RecHata as e:
        _rec_hata(e)
    return {'ok': True}


@router.post('/rec/{rec_id}/finish')
async def rec_finish(rec_id: str, body: RecFinishIn, user=Depends(sim_user), conn=db.DB):
    """Bitir: `share` (varsayılan) → Şirketten Haberler paylaşımı; `share:false` → dosya sunucuda saklanır (`kept`), `{kept:true, rec_id, size, text,
    file: '/api/drone/sim/rec/<id>/file'}` döner."""
    if not body.share:
        try:
            r = flightsim_rec.sakla(rec_id, user, _yazar(user), body.duration_s, body.text)
        except flightsim_rec.RecHata as e:
            _rec_hata(e)
        flightsim_runs.video_bagla(r.get('sid'), rec_id, conn=conn)   # §21: simülasyon kaydına video bağı (saklanan dosya)
        conn.commit()
        return {'ok': True, 'kept': True, 'rec_id': rec_id, 'size': r['size'], 'text': r['text'], 'file': f'/api/drone/sim/rec/{rec_id}/file', 'link': None}
    try:
        r = flightsim_rec.bitir(conn, rec_id, user, _yazar(user), body.duration_s, body.text)
    except flightsim_rec.RecHata as e:
        _rec_hata(e)
    flightsim_runs.video_bagla(r.get('sid'), rec_id, r['post_id'], r['path'], conn=conn)   # §21: paylaşım kimliği + dosya yolu
    conn.commit()
    owner = db.row(conn.execute('SELECT id, full_name FROM users WHERE id = ?', (r['owner_id'],))) or {'id': user['id'], 'full_name': user['full_name']}
    from .feed import _announce
    await _announce(conn, r['post_id'], owner, r['text'], [{'type': 'video', 'path': r['path']}])
    return {'ok': True, 'post_id': r['post_id'], 'path': r['path'], 'thumb': r['thumb'], 'text': r['text'], 'size': r['size'], 'link': '#/home'}


@router.post('/rec/{rec_id}/share')
async def rec_share(rec_id: str, body: RecFinishIn, user=Depends(sim_user), conn=db.DB):
    """Saklanan ('kept') kaydı sonradan Şirketten Haberler'e paylaşır (finish ile aynı; metin/süre saklanandan)."""
    body.share = True
    return await rec_finish(rec_id, body, user, conn)


@router.get('/rec/mine')
def rec_mine(user=Depends(sim_user)):
    """"Kayıtlarım": kullanıcının paylaşılmadan saklanan videoları → indir / paylaş / sil."""
    return {'items': flightsim_rec.listem(user), 'keep_days': flightsim_rec.KEEP_DAYS}


@router.get('/rec/{rec_id}/file')
def rec_file(rec_id: str, user=Depends(sim_user)):
    """Saklanan kaydı indir (sahip / başlatan / yazma izni)."""
    try:
        p, mime, ad = flightsim_rec.dosya(rec_id, user, _yazar(user))
    except flightsim_rec.RecHata as e:
        _rec_hata(e)
    return FileResponse(p, media_type=mime, filename=ad, headers={'Cache-Control': 'private, no-store'})


@router.delete('/rec/{rec_id}')
def rec_delete(rec_id: str, user=Depends(sim_user)):
    try:
        flightsim_rec.sil(rec_id, user, _yazar(user))
    except flightsim_rec.RecHata as e:
        _rec_hata(e)
    return {'ok': True}


@router.get('/rec/pending')
def rec_pending(user=Depends(sim_user)):
    """Kullanıcının yarım kayıtları (oturumu kapanmış, bitirilmemiş): paylaşıma dönüştür (finish) ya da sil."""
    acik = [s.id for s in flightsim.MANAGER.sessions.values() if s.state != 'KAPANDI']
    return {'items': flightsim_rec.bekleyenler(user, acik), 'max_mb': flightsim_rec.MAX_MB}


# ---------------- Görsel model kütüphanesi (flightsim_models; §12) ----------------
# Okuma require_module('drone.sim'); POST/PUT/DELETE yazma izni (require_module yöntemden türetir). Kimlikler flightsim_models.kimlik_coz ile
# doğrulanır (tam sayı ya da builtin:<ad>), dosya yolları yalnız kimlikten türetilir (yol gezinmesi yok). Boyut/uzantı/başlık denetimleri modülde.
def _mid(mid):
    k = flightsim_models.kimlik_coz(mid)
    if not k:
        raise HTTPException(404, 'Model bulunamadı')
    return k


def _db_mid(mid):
    k = _mid(mid)
    if k[0] != 'db':
        raise HTTPException(400, 'Dahili model üzerinde bu işlem yapılamaz')
    return k[1]


async def _govde(request: Request, sinir):
    """PUT ham gövdesi (application/octet-stream ya da image/png); Content-Length sınırı önce, okunan boyut sonra denetlenir."""
    try:
        cl = int(request.headers.get('content-length') or 0)
    except ValueError:
        cl = 0
    if cl > sinir:
        raise HTTPException(413, f'Gövde {sinir // 1024 ** 2} MB sınırını aşıyor')
    data = await request.body()
    if len(data) > sinir:
        raise HTTPException(413, f'Gövde {sinir // 1024 ** 2} MB sınırını aşıyor')
    return data


@router.get('/models')
def list_models(type: Optional[str] = None, user=Depends(sim_user), conn=db.DB):
    """Kütüphane: dahili (her tip için) + yüklenen/tasarım modelleri. `type` verilirse yalnız o tip (dahili adlar tipe göre: VTOL-Caymaz)."""
    if type is not None and type not in flightsim.TIP_ADLARI:
        raise HTTPException(400, 'type geçersiz')
    return {'models': flightsim_models.listele(conn, type), 'defaults': dict(flightsim_models.VARSAYILAN),
            'can_write': MODUL in user.get('write_modules', []), 'design_allowed': 'design' in (user.get('modules') or []),
            'limits': {'max_bytes': flightsim_models.MAX_BYTES, 'formats': list(flightsim_models.UZANTILAR)}}


@router.get('/models/design-files')
def design_files(user=Depends(sim_user), conn=db.DB):
    """Tasarım modülündeki 3B sürüm dosyaları (STEP/GLB/GLTF/OBJ) — yalnız `design` modülü görünür olan kullanıcıya."""
    if 'design' not in (user.get('modules') or []):
        raise HTTPException(403, 'Tasarım dosyaları için Endüstriyel Tasarım modülü yetkisi gerekir')
    return flightsim_models.tasarim_dosyalari(conn)


@router.post('/models', status_code=201)
async def upload_model(request: Request, file: UploadFile = File(...), type: str = Form(...), name: Optional[str] = Form(None), user=Depends(sim_user)):
    """Simülatöre doğrudan 3B dosya yükleme (.glb/.gltf/.step/.stp/.obj; ≤ 50 MB; yazma izni)."""
    data = b''
    while chunk := await file.read(1024 * 1024):
        data += chunk
        if len(data) > flightsim_models.MAX_BYTES:
            raise HTTPException(413, 'Dosya 50 MB sınırını aşıyor')
    with db.connect() as conn:
        try:
            m = flightsim_models.yukle(conn, user, name, type, file.filename, data)
        except flightsim.SimHata as e:
            _hata(e)
        db.audit(conn, user['id'], 'Simülatör modeli yükledi', 'drone_sim_model', m['id'], f"{file.filename} · {type}")
        conn.commit()
    return m


@router.post('/models/from-design', status_code=201)
def model_from_design(body: FromDesignIn, user=Depends(sim_user), conn=db.DB):
    """Tasarım sürüm dosyasını kütüphaneye ekler (dosya kopyalanmaz; GLB/küçük resim tarayıcıda üretilip PUT edilir)."""
    if 'design' not in (user.get('modules') or []):
        raise HTTPException(403, 'Tasarım dosyaları için Endüstriyel Tasarım modülü yetkisi gerekir')
    try:
        m = flightsim_models.tasarimdan_ekle(conn, user, body.version_id, body.type, body.name)
    except flightsim.SimHata as e:
        _hata(e)
    db.audit(conn, user['id'], 'Simülatör modeli ekledi (tasarım dosyası)', 'drone_sim_model', m['id'], f"sürüm {body.version_id} · {body.type}")
    return m


@router.get('/models/{mid}')
def get_model(mid: str, type: Optional[str] = None, user=Depends(sim_user), conn=db.DB):
    _mid(mid)
    m = flightsim_models.getir(conn, mid, type)
    if not m:
        raise HTTPException(404, 'Model bulunamadı')
    return m


@router.put('/models/{mid}')
def patch_model(mid: str, body: ModelPatch, user=Depends(sim_user), conn=db.DB):
    """Ad / tip / yönelim (orient) / pervane bayrağı — yüklenen ve tasarım modelleri."""
    iid = _db_mid(mid)
    try:
        m = flightsim_models.guncelle(conn, iid, body.model_dump(exclude_unset=True))
    except flightsim.SimHata as e:
        _hata(e)
    if not m:
        raise HTTPException(404, 'Model bulunamadı')
    return m


@router.delete('/models/{mid}')
def delete_model(mid: str, user=Depends(sim_user), conn=db.DB):
    iid = _db_mid(mid)
    r = flightsim_models.sil(conn, iid)
    if not r:
        raise HTTPException(404, 'Model bulunamadı')
    db.audit(conn, user['id'], 'Simülatör modelini sildi', 'drone_sim_model', iid, r['name'])
    return {'ok': True}


@router.get('/models/{mid}/file')
def model_file(mid: str, user=Depends(sim_user), conn=db.DB):
    """Özgün dosya (STEP/OBJ/GLTF/GLB) — tarayıcıda GLB'ye dönüştürmek için."""
    iid = _db_mid(mid)
    r = flightsim_models._row(conn, iid)
    p = flightsim_models.dosya_yolu(r) if r else None
    if not p or not p.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return FileResponse(p, filename=r.get('file_name') or p.name, media_type='application/octet-stream',
                        headers={'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff'})


@router.get('/models/{mid}/glb')
def model_glb(mid: str, user=Depends(sim_user), conn=db.DB):
    iid = _db_mid(mid)
    p = flightsim_models.glb_yolu(conn, iid)
    if not p:
        raise HTTPException(404, 'GLB henüz üretilmedi')
    return FileResponse(p, media_type='model/gltf-binary', headers={'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff'})


@router.put('/models/{mid}/glb')
async def put_model_glb(mid: str, request: Request, user=Depends(sim_user)):
    """Tarayıcıda üretilen GLB (ham gövde, ≤ 50 MB, 'glTF' başlığı) → model.glb; `ready=true`."""
    iid = _db_mid(mid)
    data = await _govde(request, flightsim_models.MAX_BYTES)
    with db.connect() as conn:
        try:
            m = flightsim_models.glb_kaydet(conn, iid, data)
        except flightsim.SimHata as e:
            _hata(e)
        if not m:
            raise HTTPException(404, 'Model bulunamadı')
        conn.commit()
    return m


@router.get('/models/{mid}/thumb')
def model_thumb(mid: str, type: Optional[str] = None, user=Depends(sim_user), conn=db.DB):
    _mid(mid)
    p = flightsim_models.thumb_yolu(conn, mid, type)
    if not p:
        raise HTTPException(404, 'Küçük resim yok')
    return FileResponse(p, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600', 'X-Content-Type-Options': 'nosniff'})


@router.put('/models/{mid}/thumb')
async def put_model_thumb(mid: str, request: Request, type: Optional[str] = None, user=Depends(sim_user)):
    """320×240 PNG (ham gövde, ≤ 2 MB). Dahili modeller için de (ilk kullanıcı üretir; `type` ile VTOL varyantı)."""
    _mid(mid)
    data = await _govde(request, flightsim_models.THUMB_MAX)
    with db.connect() as conn:
        try:
            m = flightsim_models.thumb_kaydet(conn, mid, data, type)
        except flightsim.SimHata as e:
            _hata(e)
        if not m:
            raise HTTPException(404, 'Model bulunamadı')
        conn.commit()
    return m


# ---------------- Gerçek topoğrafya vekili (sim_terrain; §8) ----------------
# Senkron uçlar (FastAPI iş parçacığı havuzu); URL'ler modülde sabit — kullanıcı girdisi yalnız sayı (SSRF yok).
def _kaynak(e):
    raise HTTPException(e.kod, str(e))


@router.get('/terrain')
def terrain_plan(lat: float, lon: float, size_m: float = None, far: int = 0, user=Depends(sim_user)):
    try:
        return sim_terrain.terrain_plani(lat, lon, size_m, uzak=bool(far))   # far=1: ufuk için kaba uzak arazi planı (§9)
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
    await ws_dongu(ws, s, {'t': 'hello', 'session': s.to_dict(host), 'can_command': yazabilir}, yazabilir, user['id'])


async def ws_dongu(ws, s, hello, yazabilir, kaynak):
    """İzleyici döngüsü (web `/ws/drone/sim/{id}` ve CAYSIM `/ws/caysim/v1/sessions/{id}` ortak): izleyici kuyruğu + gönderici görevi,
    `hello` çerçevesi, ardından istemciden `ping` → `pong`, `cmd` → `res`, `rc` → s.rc (yanıt yok). Bağlantı kopunca izleyici silinir."""
    q = s.izleyici_ekle(ws)
    sender = asyncio.create_task(_sender(ws, q))
    flightsim._kuyruga(q, json.dumps(hello, ensure_ascii=False))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
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
                    res = await s.komut(name, msg.get('params') or {}, kaynak=kaynak)
                    flightsim._kuyruga(q, json.dumps({'t': 'res', 'name': name, 'rid': msg.get('rid'), **res}, ensure_ascii=False))
                except flightsim.SimHata as e:
                    flightsim._kuyruga(q, json.dumps({'t': 'res', 'name': name, 'rid': msg.get('rid'), 'ok': False, 'error': str(e)}, ensure_ascii=False))
    except (WebSocketDisconnect, Exception):   # noqa: BLE001
        pass
    finally:
        s.izleyici_sil(ws)
        sender.cancel()
