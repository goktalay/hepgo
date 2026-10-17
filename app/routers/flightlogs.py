"""ArduPilot uçuş logu yükleme ve uçuş raporları.

İki giriş noktası aynı analiz motorunu kullanır:
  * Saha Yönetimi: görevdeki her uçuşa (uçağa) log yüklenir; görev bitmiş ve tüm uçuşların raporu hazırsa
    görev "Rapor Tamamlandı" olur.
  * Araçlar → Uçuş Logu Analizi: herhangi bir göreve bağlı olmadan log yüklenir.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, config, db, flight_analysis
from ..flightlog import replay
from ..files import FLIGHT_LOG_MAX_BYTES, local_only, save_upload_stream, take_upload
from .field import flight_row, get_task, require_flight_editor, field_user

router = APIRouter(prefix='/api')
tools_user = auth.require_module('tools')

_SELECT = '''
    SELECT l.id, l.task_id, l.flight_id, l.file, l.file_name, l.size, l.status, l.error, l.aircraft, l.pilot, l.location,
           l.note, l.fuel, l.uploaded_at, l.analyzed_at, u.full_name AS uploaded_by_name, t.code AS task_code,
           json_extract(l.analysis, '$.summary.vehicle') AS vehicle,
           json_extract(l.analysis, '$.summary.flight_s') AS flight_s,
           json_extract(l.analysis, '$.summary.takeoff_utc') AS takeoff_utc,
           json_extract(l.analysis, '$.summary.start_utc') AS start_utc
    FROM flight_logs l
    LEFT JOIN users u ON u.id = l.uploaded_by
    LEFT JOIN field_tasks t ON t.id = l.task_id
'''


class ChunkedLogIn(BaseModel):
    upload_id: str
    aircraft: Optional[str] = None
    pilot: Optional[str] = None
    location: Optional[str] = None
    note: Optional[str] = None


async def _receive(user, file=None, upload_id=None):
    """Log dosyası: tek istekte (multipart) ya da parça parça yükleme jetonuyla. (yol, boyut, ad) döner."""
    if upload_id:
        return await run_in_threadpool(take_upload, upload_id, user, 'flightlogs')
    path, size = await save_upload_stream('flightlogs', file, FLIGHT_LOG_MAX_BYTES)
    return path, size, file.filename


async def _store(conn, user, stored, task_id=None, flight_id=None, aircraft=None, pilot=None, location=None, note=None):
    path, size, file_name = stored

    def write():   # dosya yüklenene kadar yazma kilidi alınmaz; yazım iş parçacığında
        cur = conn.execute(
            '''INSERT INTO flight_logs (task_id, flight_id, file, file_name, size, aircraft, pilot, location, note,
                                        uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (task_id, flight_id, path, file_name, size, aircraft, pilot, location, note, user['id'], db.now()))
        conn.commit()   # analiz iş parçacığı kaydı görebilsin
        return cur.lastrowid
    log_id = await run_in_threadpool(write)
    flight_analysis.start(log_id)
    return log_id


def _clean(v):
    return v.strip() or None if v else None


# ---------- Saha görevi: uçuş başına log ----------

async def _field_log(conn, user, fid, file=None, upload_id=None):
    require_flight_editor(user)
    flight = flight_row(conn, fid)
    task = get_task(conn, flight['task_id'])
    if task['status'] in ('BASLANGIC', 'IPTAL'):
        raise HTTPException(400, 'Uçuş logu görev başladıktan sonra yüklenebilir')
    if conn.execute("SELECT 1 FROM flight_logs WHERE flight_id = ? AND status = 'ISLENIYOR'", (fid,)).fetchone():
        raise HTTPException(409, 'Bu uçuş için bir log zaten analiz ediliyor')
    stored = await _receive(user, file, upload_id)
    f = next(x for x in task['flights'] if x['id'] == fid)
    crew = task['pilot_name'] or ', '.join(s['full_name'] for s in task['staff'])   # eski görevlerde pilot yok
    log_id = await _store(conn, user, stored, task_id=task['id'], flight_id=fid, aircraft=f['queue_no'] or f['order_code'],
                          pilot=crew or None, location=task['location_name'])
    await run_in_threadpool(db.audit, conn, user['id'], 'Uçuş logu yükledi', 'field_task', task['id'],
                            f'{task["code"]} / {f["queue_no"] or f["order_code"]}: {stored[2]}')
    return {'id': log_id}


@router.post('/field/flights/{fid}/flight-log', dependencies=[Depends(local_only)])
async def upload_flight_log(fid: int, file: UploadFile, user=Depends(field_user), conn=db.DB):
    return await _field_log(conn, user, fid, file=file)


@router.post('/field/flights/{fid}/flight-log/chunked')
async def chunked_flight_log(fid: int, body: ChunkedLogIn, user=Depends(field_user), conn=db.DB):
    """Parça parça yüklenmiş log (büyük dosyalar; bkz. /api/uploads)."""
    return await _field_log(conn, user, fid, upload_id=body.upload_id)


# ---------- Araçlar → Uçuş Logu Analizi ----------

async def _tool_log(conn, user, stored, aircraft, pilot, location, note):
    log_id = await _store(conn, user, stored, aircraft=_clean(aircraft), pilot=_clean(pilot),
                          location=_clean(location), note=_clean(note))
    await run_in_threadpool(db.audit, conn, user['id'], 'Uçuş logu analize gönderdi', 'flight_log', log_id, stored[2])
    return {'id': log_id}


@router.post('/tools/flight-logs', dependencies=[Depends(local_only)])
async def upload_tool_log(file: UploadFile, aircraft: Optional[str] = Form(None), pilot: Optional[str] = Form(None),
                          location: Optional[str] = Form(None), note: Optional[str] = Form(None),
                          user=Depends(tools_user), conn=db.DB):
    return await _tool_log(conn, user, await _receive(user, file), aircraft, pilot, location, note)


@router.post('/tools/flight-logs/chunked')
async def chunked_tool_log(body: ChunkedLogIn, user=Depends(tools_user), conn=db.DB):
    return await _tool_log(conn, user, await _receive(user, upload_id=body.upload_id),
                           body.aircraft, body.pilot, body.location, body.note)


@router.get('/tools/flight-logs')
def list_logs(user=Depends(tools_user), conn=db.DB):
    return db.rows(conn.execute(_SELECT + ' ORDER BY l.id DESC LIMIT 500'))


@router.delete('/tools/flight-logs/{lid}')
def delete_log(lid: int, user=Depends(tools_user), conn=db.DB):
    log = db.row(conn.execute('SELECT * FROM flight_logs WHERE id = ?', (lid,)))
    if not log:
        raise HTTPException(404, 'Kayıt bulunamadı')
    if log['task_id']:
        raise HTTPException(400, 'Saha görevine bağlı uçuş raporu buradan silinemez')
    if log['status'] == 'ISLENIYOR':
        raise HTTPException(400, 'Analiz sürerken silinemez')
    (config.UPLOAD_DIR / log['file']).unlink(missing_ok=True)
    _replay_path(log).unlink(missing_ok=True)
    try:   # Uçuş Simülatörü kayıttan oynatma önbelleği (DATA_DIR/sim_replay/<id>.json.gz)
        from ..flightsim_replay import onbellek_yolu
        onbellek_yolu(lid).unlink(missing_ok=True)
    except OSError:
        pass
    conn.execute('DELETE FROM flight_logs WHERE id = ?', (lid,))
    db.audit(conn, user['id'], 'Uçuş logu sildi', 'flight_log', lid, log['file_name'])
    return {'ok': True}


# ---------- Rapor ----------

@router.get('/flight-logs/{lid}')
def get_log(lid: int, user=Depends(auth.current_user), conn=db.DB):
    log = db.row(conn.execute(_SELECT.replace('SELECT l.id,', 'SELECT l.analysis, l.id,') + ' WHERE l.id = ?', (lid,)))
    if not log:
        raise HTTPException(404, 'Kayıt bulunamadı')
    allowed = {'tools'} | ({'field'} if log['task_id'] else set())
    if not allowed & set(user['modules']):
        raise HTTPException(403, 'Bu rapora erişim yetkiniz yok')
    log['analysis'] = json.loads(log['analysis']) if log['analysis'] else None
    log['fuel'] = json.loads(log['fuel']) if log.get('fuel') else None
    if log['fuel']:   # rapor için seyreltilmiş seri (≤ 600 nokta) + motor çalışırken en düşük tüketim
        try:
            fdata = json.loads(_fuel_path(log).read_text(encoding='utf-8'))
            smp = fdata.get('samples') or []
            step = max(1, len(smp) // 600)
            log['fuel']['series'] = [[r[0], r[1], r[2], r[3]] for r in smp[::step]] + ([smp[-1][:4]] if smp and (len(smp) - 1) % step else [])
            running = [r[1] for r in smp if r[1] > 0]
            log['fuel']['min_lph'] = round(min(running), 2) if running else None
        except (OSError, ValueError):
            pass
    log['task'] = get_task(conn, log['task_id']) if log['task_id'] else None
    log['flight'] = next((f for f in log['task']['flights'] if f['id'] == log['flight_id']), None) if log['task'] else None
    return log


def _replay_path(log):
    return config.UPLOAD_DIR / (log['file'] + '.replay.json')


@router.get('/flight-logs/{lid}/replay')
async def get_replay(lid: int, user=Depends(auth.current_user), conn=db.DB):
    """3B oynatma verisi: .bin dosyasından ilk istekte üretilir ve log dosyasının yanında saklanır."""
    log = await run_in_threadpool(get_log, lid, user, conn)   # erişim kontrolü aynı
    if log['status'] != 'TAMAM':
        raise HTTPException(400, 'Log analizi tamamlanmadan 3B oynatma açılamaz')
    path = _replay_path(log)
    if path.exists():   # eski önbellek (rpm alanı yok) → yeniden üret
        try:
            if '"rpm"' not in path.read_text(encoding='utf-8', errors='replace')[:400]:
                path.unlink()
        except OSError:
            pass
    if not path.exists():
        try:
            data = await run_in_threadpool(replay, config.UPLOAD_DIR / log['file'])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
        tmp.rename(path)
    return FileResponse(path, media_type='application/json', headers={'Cache-Control': 'private, max-age=86400'})


# ---------- Yakıt: başlangıç / bitiş litre → toplam tüketim, motor itkisine (gaz) göre zamana dağıtım ----------
class FuelIn(BaseModel):
    start_l: float
    end_l: float
    thrust_max_kg: float = 51.0   # motorun azami statik itkisi (DLE-222: 51 kg); itki tahmini için


def _fuel_path(log):
    return config.UPLOAD_DIR / (log['file'] + '.fuel.json')


def fuel_series(samples, total_l, thrust_max_kg):
    """Telemetriye (5 Hz) yakıt dağıtımı. Gaz (%) ile motor gücü arasında p = 0,08 + 0,92·(gaz/100)^1,5 ilişkisi varsayılır
    (rölanti ~%8); toplam yakılan litre bu ağırlıkla zamana paylaştırılır → anlık tüketim (L/sa) ve birikimli yakılan (L).
    İtki: T = T_max · (gaz/100)² · (1 − 0,6·min(1, hava hızı/45)) — pervane itkisi hız arttıkça düşer (kaba tahmin)."""
    n = len(samples)
    eff = [0.0] * n
    for i, s in enumerate(samples):
        thr = s[9]
        if thr is None or thr <= 0:
            continue
        eff[i] = 0.08 + 0.92 * (min(100.0, thr) / 100.0) ** 1.5
    W = 0.0
    dts = [0.0] * n
    for i in range(1, n):
        dts[i] = max(0.0, min(5.0, samples[i][0] - samples[i - 1][0]))
        W += eff[i] * dts[i]
    out, burned = [], 0.0
    peak_rate = 0.0; peak_thrust = 0.0; run_s = 0.0
    for i, s in enumerate(samples):
        rate_lps = (total_l * eff[i] / W) if W > 0 else 0.0
        burned += rate_lps * dts[i]
        thr = max(0.0, min(100.0, s[9] or 0.0))
        aspd = s[8] or 0.0
        thrust = thrust_max_kg * (thr / 100.0) ** 2 * (1 - 0.6 * min(1.0, aspd / 45.0))
        lph = rate_lps * 3600
        peak_rate = max(peak_rate, lph); peak_thrust = max(peak_thrust, thrust)
        if eff[i] > 0:
            run_s += dts[i]
        out.append([round(s[0], 1), round(lph, 2), round(burned, 3), round(thrust, 2), round(thr)])
    return out, {'engine_s': round(run_s), 'peak_lph': round(peak_rate, 1), 'peak_thrust_kg': round(peak_thrust, 1),
                 'avg_lph': round(total_l / (run_s / 3600), 2) if run_s > 0 else None}


@router.post('/flight-logs/{lid}/fuel')
async def compute_fuel(lid: int, body: FuelIn, user=Depends(auth.current_user), conn=db.DB):
    """Yakıt hesapla: başlangıç − bitiş = toplam yakılan; gaz/itki ağırlığıyla telemetriye dağıtılır ve dosyaya yazılır (bir kez)."""
    log = await run_in_threadpool(get_log, lid, user, conn)
    if log['status'] != 'TAMAM':
        raise HTTPException(400, 'Önce uçuş logu (.bin) yüklenip analizi tamamlanmalı')
    if body.start_l < 0 or body.end_l < 0 or body.start_l > 500:
        raise HTTPException(400, 'Litre değerleri geçersiz')
    if body.end_l > body.start_l:
        raise HTTPException(400, 'Bitiş yakıtı başlangıçtan fazla olamaz')
    total = body.start_l - body.end_l
    rpath = _replay_path(log)
    if not rpath.exists():
        try:
            data = await run_in_threadpool(replay, config.UPLOAD_DIR / log['file'])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        rpath.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    else:
        data = json.loads(rpath.read_text(encoding='utf-8'))
    series, stats = await run_in_threadpool(fuel_series, data['samples'], total, float(body.thrust_max_kg or 51))
    summary = {'start_l': body.start_l, 'end_l': body.end_l, 'total_l': round(total, 3), 'thrust_max_kg': float(body.thrust_max_kg or 51),
               'flight_s': log.get('flight_s'), 'computed_at': db.now(), 'computed_by': user['full_name'], **stats}
    fs = log.get('flight_s') or 0
    summary['lph_flight'] = round(total / (fs / 3600), 2) if fs else None   # havada geçen saate göre
    dist = ((log.get('analysis') or {}).get('summary') or {}).get('distance_m')
    summary['l_per_km'] = round(total / (dist / 1000), 3) if dist else None
    tmp = _fuel_path(log).with_suffix('.tmp')
    tmp.write_text(json.dumps({'summary': summary, 'samples': series}, separators=(',', ':')), encoding='utf-8')
    tmp.rename(_fuel_path(log))
    conn.execute('UPDATE flight_logs SET fuel = ? WHERE id = ?', (json.dumps(summary, ensure_ascii=False), lid))
    db.audit(conn, user['id'], 'Uçuş yakıtı hesapladı', 'flight_log', lid, f"{body.start_l:g} → {body.end_l:g} L · {total:g} L")
    return summary


@router.get('/flight-logs/{lid}/fuel')
async def get_fuel(lid: int, user=Depends(auth.current_user), conn=db.DB):
    """Yakıt serisi (3B izleme HUD'u için): [[t, L/sa, yakılan L, itki kg, gaz %]…] + özet."""
    log = await run_in_threadpool(get_log, lid, user, conn)
    path = _fuel_path(log)
    if not path.exists():
        raise HTTPException(404, 'Yakıt hesaplanmamış')
    return FileResponse(path, media_type='application/json', headers={'Cache-Control': 'private, max-age=3600'})
