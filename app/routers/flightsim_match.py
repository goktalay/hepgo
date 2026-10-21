"""Uçuş Simülatörü — ÇOK OYUNCULU KARŞILAŞMA REST + WS (docs/ucus-simulatoru.md §33).

REST `/api/drone/sim/matches` (yetki `drone.sim`; oluşturma/katılma yazma izni ister):
  GET  /meta                  davet edilebilir kullanıcılar (Uçuş Simülatörü yazma izni olanlar, siz hariç), halka sınırları/varsayılanları, kapasite
  POST /rings-preview         {type, center_id, rings} → sihirbaz önizlemesi için halkalar (aynı tohum = aynı parkur)
  GET  ''                     son karşılaşmalarım (oyuncusu olduklarım; canlı olanlar bellekten)
  POST ''                     {settings, rings, invite: [user_id]} → 201 karşılaşma (LOBI; kurucu "geldi"; davetlilere bildirim)
  GET  /{id}                  anlık görüntü (bellekte değilse DB satırı)
  POST /{id}/join · /leave · /kick {user_id} · /start (kurucu: gelmeyenler olmadan) · /cancel (kurucu)
WS `/ws/drone/match/{id}` (oturum çerezi; yalnız oyuncular): hello {match, me, chat} · match (anlık görüntü) · player · state · countdown · pos (10 Hz)
  · ring · finish · wrong_way · result · chat. İstemci → ping, ready (3B dünya hazır), chat {text}.
"""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import auth, db, drone_hub, flightsim, flightsim_match, flightsim_presets
from .. import flightsim_match_core as core
from .flightsim import MODUL, _centers

router = APIRouter(prefix='/api/drone/sim/matches')
ws_router = APIRouter()
sim_user = auth.require_module('drone.sim')
HATA_KODU = {'invalid': 400, 'forbidden': 403, 'notfound': 404, 'conflict': 409, 'limit': 409}
AYAR_ALANLARI = ('type', 'center_id', 'world', 'model', 'power', 'layout', 'camera', 'drive')   # radar / EO / yer kontrol / hedefler / dron kaydı yok


class MatchIn(BaseModel):
    settings: dict
    rings: Optional[dict] = None
    invite: list


class PreviewIn(BaseModel):
    type: str
    center_id: int
    rings: Optional[dict] = None


class KickIn(BaseModel):
    user_id: int


def _hata(e):
    raise HTTPException(HATA_KODU.get(getattr(e, 'kod', 'invalid'), 400), str(e))


def _yazar(user):
    if MODUL not in user.get('write_modules', []):
        raise HTTPException(403, 'Karşılaşma için Uçuş Simülatörü yazma izni gerekir')


def _davetliler(conn, uid):
    return [u for u in flightsim_presets.pilotlar(conn) if u['id'] != uid]


@router.get('/meta')
def meta(user=Depends(sim_user), conn=db.DB):
    flightsim_match.MANAGER.kurtar()
    lim = {'players_max': core.OYUNCU_MAX, 'invite_min': core.DAVET_MIN, 'count': list(core.HALKA_SAYI), 'alt_m': list(core.YUKSEKLIK),
           'diameter_m': list(core.CAP), 'radius_m': list(core.PARKUR), 'time_limit_min': list(core.SURE_DK),
           'defaults': {'dikey': core.halka_ayar_varsayilan('multirotor'), 'ucak': core.halka_ayar_varsayilan('sabit_kanat')},
           'types': list(core.TIPLER), 'countdown_s': core.GERI_SAYIM_S, 'force_after_s': core.LOBI_ZORLA_S}
    return {'users': [{'id': u['id'], 'full_name': u['full_name'], 'username': u.get('username'), 'pilot': u.get('pilot')} for u in _davetliler(conn, user['id'])],
            'limits': lim, 'capacity': {'max': flightsim.MATCH_MAX_SESSIONS, 'used': flightsim_match.MANAGER.ayrilmis_slot()},
            'can_create': MODUL in user.get('write_modules', [])}


@router.post('/rings-preview')
def rings_preview(body: PreviewIn, user=Depends(sim_user), conn=db.DB):
    c = _centers(conn, body.center_id)
    if not c:
        raise HTTPException(400, 'Merkez bulunamadı')
    try:
        cfg = core.halka_ayar_dogrula(body.rings, body.type)
    except core.MacHata as e:
        _hata(e)
    cfg['seed'] = cfg.get('seed') or 1
    return {'cfg': cfg, 'rings': core.halkalar_uret(cfg, {'lat': c['lat'], 'lon': c['lon'], 'alt': c['alt'] or 0})}


@router.get('')
def list_matches(user=Depends(sim_user), conn=db.DB):
    flightsim_match.MANAGER.kurtar()
    rows = db.rows(conn.execute('SELECT m.*, u.full_name AS host_name FROM drone_sim_matches m LEFT JOIN users u ON u.id = m.host_id ORDER BY m.id DESC LIMIT 200'))
    out = []
    for r in rows:
        d = flightsim_match.satir_dict(r)
        canli = flightsim_match.MANAGER.get(r['id'])
        if canli is not None:
            d = {**canli.anlik(), 'live': True}
        if user['id'] != d['host_id'] and not any(p.get('id') == user['id'] for p in d['players']) and not user.get('master'):
            continue
        d['host_name'] = r['host_name']
        out.append({k: d.get(k) for k in ('id', 'state', 'reason', 'host_id', 'host_name', 'players', 'winner', 'created_at', 'started_at', 'ended_at', 'live', 'rings_cfg')}
                   | {'type': (d.get('settings') or {}).get('type'), 'center_name': ((d.get('center') or {}).get('name')) if canli else None})
        if len(out) >= 50:
            break
    return out


@router.post('', status_code=201)
async def create_match(body: MatchIn, user=Depends(sim_user)):
    _yazar(user)
    settings = {k: body.settings[k] for k in AYAR_ALANLARI if isinstance(body.settings, dict) and body.settings.get(k) is not None}
    if settings.get('type') not in core.TIPLER:
        raise HTTPException(400, 'Karşılaşmada bu araç tipi yok (halkalar havada; kara aracı seçilemez)')
    try:
        rcfg = core.halka_ayar_dogrula(body.rings, settings['type'])
    except core.MacHata as e:
        _hata(e)
    if not isinstance(body.invite, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in body.invite):
        raise HTTPException(400, 'invite kullanıcı kimlikleri listesi olmalı')

    def hazirla():
        with db.connect() as conn:
            try:
                s = flightsim_presets.ayar_dogrula(conn, settings)
            except flightsim_presets.PresetHata as e:
                raise HTTPException(400, str(e))
            izinli = {u['id']: u for u in _davetliler(conn, user['id'])}
            bad = [x for x in body.invite if x not in izinli]
            if bad:
                raise HTTPException(400, 'Davet listesinde simülatör erişimi olmayan ya da bulunamayan kullanıcı var')
            davet = [(x, izinli[x]['full_name']) for x in dict.fromkeys(body.invite)]
            return s, _centers(conn, s['center_id']), davet
    s, center, davet = await asyncio.get_running_loop().run_in_executor(None, hazirla)
    try:
        r = await flightsim_match.MANAGER.olustur({'id': user['id'], 'name': user['full_name']}, s, center, rcfg, davet)
    except core.MacHata as e:
        _hata(e)
    return r.anlik()


def _canli(mid):
    r = flightsim_match.MANAGER.get(mid)
    if r is None:
        raise HTTPException(404, 'Karşılaşma bulunamadı ya da bitti')
    return r


def _oyuncu_mu(d, user):
    return user['id'] == d['host_id'] or any(p.get('id') == user['id'] for p in d['players']) or user.get('master')


@router.get('/{mid}')
def get_match(mid: int, user=Depends(sim_user), conn=db.DB):
    r = flightsim_match.MANAGER.get(mid)
    if r is not None:
        d = {**r.anlik(), 'live': True}
    else:
        row = db.row(conn.execute('SELECT * FROM drone_sim_matches WHERE id = ?', (mid,)))
        if not row:
            raise HTTPException(404, 'Karşılaşma bulunamadı')
        d = flightsim_match.satir_dict(row)
    if not _oyuncu_mu(d, user):
        raise HTTPException(403, 'Bu karşılaşmanın oyuncusu değilsiniz')
    return d


async def _islem(mid, fn):
    import time
    r = _canli(mid)
    try:
        r.isle(fn(r.k, time.time()))
    except core.MacHata as e:
        _hata(e)
    return r.anlik()


@router.post('/{mid}/join')
async def join(mid: int, user=Depends(sim_user)):
    _yazar(user)
    return await _islem(mid, lambda k, now: k.katil(user['id'], now))


@router.post('/{mid}/leave')
async def leave(mid: int, user=Depends(sim_user)):
    return await _islem(mid, lambda k, now: k.ayril(user['id'], now))


@router.post('/{mid}/kick')
async def kick(mid: int, body: KickIn, user=Depends(sim_user)):
    return await _islem(mid, lambda k, now: k.cikar(user['id'], body.user_id, now))


@router.post('/{mid}/start')
async def force_start(mid: int, user=Depends(sim_user)):
    return await _islem(mid, lambda k, now: k.zorla_baslat(user['id'], now))


@router.post('/{mid}/cancel')
async def cancel(mid: int, user=Depends(sim_user)):
    def f(k, now):
        if user['id'] != k.kurucu_id:
            raise core.MacHata('forbidden', 'Yalnız kurucu iptal edebilir')
        return k.iptal(now, 'kurucu_iptal')
    return await _islem(mid, f)


async def _sender(ws, q):
    try:
        while True:
            await ws.send_text(await q.get())
    except Exception:   # noqa: BLE001
        pass


@ws_router.websocket('/ws/drone/match/{mid}')
async def ws_match(ws: WebSocket, mid: int):
    import time
    await ws.accept()
    user = await asyncio.get_running_loop().run_in_executor(None, drone_hub._ws_user, ws.cookies.get(auth.COOKIE))
    if not user or MODUL not in user['modules']:
        await drone_hub._safe_send(ws, {'t': 'error', 'error': 'auth'})
        await ws.close(code=4403)
        return
    r = flightsim_match.MANAGER.get(mid)
    if r is None:
        await drone_hub._safe_send(ws, {'t': 'error', 'error': 'not_found'})
        await ws.close(code=4404)
        return
    if r.k.oyuncu(user['id']) is None and not user.get('master'):
        await drone_hub._safe_send(ws, {'t': 'error', 'error': 'forbidden'})
        await ws.close(code=4403)
        return
    q = r.izleyici_ekle(ws, user['id'])
    sender = asyncio.create_task(_sender(ws, q))
    flightsim._kuyruga(q, json.dumps({'t': 'hello', 'match': r.anlik(), 'me': user['id'], 'chat': r.sohbet[-30:]}, ensure_ascii=False, default=str), True)
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
                flightsim._kuyruga(q, json.dumps({'t': 'pong', 'now': time.time()}), True)
            elif t == 'ready':   # 3B dünya kuruldu (oturum HAZIR ise döngü oyuncuyu hazır yapar)
                r.ready.add(user['id'])
            elif t == 'chat':
                txt = str(msg.get('text') or '').strip()[:flightsim_match.SOHBET_MAX]
                if txt and r.k.oyuncu(user['id']) is not None:
                    m = {'t': 'chat', 'id': user['id'], 'name': user['full_name'], 'text': txt, 'ts': time.time()}
                    r.sohbet.append(m)
                    del r.sohbet[:-100]
                    r._yay(m)
    except (WebSocketDisconnect, Exception):   # noqa: BLE001
        pass
    finally:
        r.izleyici_sil(ws)
        sender.cancel()
