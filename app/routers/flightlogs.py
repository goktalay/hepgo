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
           l.note, l.uploaded_at, l.analyzed_at, u.full_name AS uploaded_by_name, t.code AS task_code,
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
    if not path.exists():
        try:
            data = await run_in_threadpool(replay, config.UPLOAD_DIR / log['file'])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
        tmp.rename(path)
    return FileResponse(path, media_type='application/json', headers={'Cache-Control': 'private, max-age=86400'})
