"""Uçuş Simülatörü — KAYITLI SİMÜLASYONLAR REST (`/api/drone/sim/presets`; docs/ucus-simulatoru.md §27).

Okuma `drone.sim` (herkes listeyi görür); POST/PUT/DELETE `drone.sim` yazma izni + satır yetkisi (`flightsim_presets.baslatabilir / duzenleyebilir`).
Başlat (`POST /presets/{id}/start`) oturum açma çekirdeğini (`routers.flightsim.oturum_ac`) kayıtlı gövdeyle çağırır; oturuma `preset_id` işlenir →
kapanışta `drone_sim_runs.preset_id`.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import auth, db, flightsim_presets
from .flightsim import SessionIn, _host, oturum_ac

router = APIRouter(prefix='/api/drone/sim/presets')
sim_user = auth.require_module('drone.sim')
HATA_KODU = {'invalid': 400, 'conflict': 409, 'forbidden': 403, 'notfound': 404}


class StartIn(BaseModel):
    rec: dict | None = None   # başlatanın kayıt seçimi ({bin}); verilmezse kayıtlı ayardaki


class PresetIn(BaseModel):
    name: str
    description: str | None = None
    pilot_id: int | None = None
    settings: dict


def _hata(e):
    raise HTTPException(HATA_KODU.get(e.kod, 400), str(e))


@router.get('')
def list_presets(user=Depends(sim_user), conn=db.DB):
    """Silinmemiş kayıtlı simülasyonlar (son güncellenen önce): satır + `settings` + `can_start/can_edit/mine` + `budget` (azami süre/menzil) +
    `run_count/last_run_at` + ad alanları (tasarlayan, pilot, merkez)."""
    return flightsim_presets.listele(conn, user)


@router.get('/pilots')
def list_pilots(user=Depends(sim_user), conn=db.DB):
    """Pilot seçimi: Uçuş Simülatörü yazma izni olan etkin kullanıcılar (PILOT rolü önce; kendisi de seçilebilir)."""
    return flightsim_presets.pilotlar(conn)


@router.get('/{pid}')
def get_preset(pid: int, user=Depends(sim_user), conn=db.DB):
    p = flightsim_presets.getir(conn, pid, user)
    if not p:
        raise HTTPException(404, 'Kayıtlı simülasyon bulunamadı')
    return p


@router.post('', status_code=201)
def create_preset(body: PresetIn, user=Depends(sim_user), conn=db.DB):
    try:
        pid, pilot = flightsim_presets.olustur(conn, body.model_dump(), user)
    except flightsim_presets.PresetHata as e:
        _hata(e)
    p = flightsim_presets.getir(conn, pid, user)
    db.audit(conn, user['id'], 'Kayıtlı simülasyon oluşturdu', 'drone_sim_preset', pid, f"{p['name']} · {p['type']} · pilot {p.get('pilot_name') or '-'}")
    conn.commit()
    flightsim_presets.pilota_bildir(pilot, user, p['name'], pid)
    return p


@router.put('/{pid}')
def update_preset(pid: int, body: PresetIn, user=Depends(sim_user), conn=db.DB):
    try:
        eski, yeni = flightsim_presets.guncelle(conn, pid, body.model_dump(), user)
    except flightsim_presets.PresetHata as e:
        _hata(e)
    p = flightsim_presets.getir(conn, pid, user)
    db.audit(conn, user['id'], 'Kayıtlı simülasyonu güncelledi', 'drone_sim_preset', pid, f"{p['name']} · pilot {p.get('pilot_name') or '-'}")
    conn.commit()
    if yeni != eski:   # yalnız pilot değişince (aynı pilota her düzenlemede yeniden bildirim yok)
        flightsim_presets.pilota_bildir(yeni, user, p['name'], pid)
    return p


@router.delete('/{pid}')
def delete_preset(pid: int, user=Depends(sim_user), conn=db.DB):
    """Yumuşak silme: liste ve başlatma dışı; uçuş kayıtları `preset_id` ile kalır (Serbest Uçuş altında 'silinmiş' rozetiyle)."""
    try:
        p = flightsim_presets.sil(conn, pid, user)
    except flightsim_presets.PresetHata as e:
        _hata(e)
    db.audit(conn, user['id'], 'Kayıtlı simülasyonu sildi', 'drone_sim_preset', pid, p['name'])
    conn.commit()
    return {'ok': True}


@router.post('/{pid}/start', status_code=201)
async def start_preset(pid: int, request: Request, body: StartIn | None = None, user=Depends(sim_user)):
    """Kayıtlı ayarlarla oturum aç (sihirbaz atlanır): yalnız atanan pilot ya da tasarlayan (MASTER). Hatalar başlatma ucuyla aynı
    (400 invalid — ör. merkez/model sonradan silindi · 409 limit · 503 sitl). Oturum sahibi başlatan kullanıcıdır."""
    loop = asyncio.get_running_loop()

    def load():
        with db.connect() as conn:
            return flightsim_presets.getir(conn, pid, user)
    p = await loop.run_in_executor(None, load)
    if not p:
        raise HTTPException(404, 'Kayıtlı simülasyon bulunamadı')
    if not p['can_start']:
        raise HTTPException(403, 'Bu kayıtlı simülasyonu yalnız atanan pilot ya da tasarlayan başlatabilir')
    govde = {k: v for k, v in p['settings'].items() if k in flightsim_presets.ALANLAR}
    if body is not None and body.rec is not None:   # .bin kaydı uçanın tercihi (ekran kaydı zaten istemcide)
        govde['rec'] = body.rec
    s = await oturum_ac(SessionIn(**govde, mode='sitl'), {'id': user['id'], 'name': user['full_name']}, user, user['id'])
    s.preset_id = p['id']   # kapanışta drone_sim_runs.preset_id (flightsim_runs._oturum_alanlari)
    s.preset = {'id': p['id'], 'name': p['name']}
    return {**s.to_dict(_host(request)), 'preset': s.preset}
