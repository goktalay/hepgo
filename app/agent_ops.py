"""Fabrika ajanı operasyonları — ortak kayıt defteri.

Bu op'lar fabrika-yerel kaynaklara (Mikro ERP, PDKS, yazıcılar) erişir. HEM 'local' modda (merkez ve cihazlar
aynı makinede; doğrudan) HEM 'remote' modda (fabrikadaki ajan çalıştırır) aynı fonksiyonlar kullanılır.
Her op, ilgili modülün DOĞRUDAN (_..._direct) implementasyonunu çağırır — böylece yönlendirme döngüsü olmaz.

Her op: fn(args: dict) -> JSON-serileştirilebilir sonuç. Bloklayıcı olabilir (ağ/DB).
"""
from . import config
import time


def _ping(args):
    return {'pong': True, 'ts': time.time()}


# --- Mikro ERP (MSSQL) ---
def _cfg(args):
    """Merkezden gelen bağlantı bilgileri (Program Ayarları › Entegrasyonlar) ajanda geçerli olur. Yalnız MIKRO_/PDKS_
    alanları kabul edilir; boş değer mevcut (ajan .env) değerini ezmez."""
    for k, v in (args.get('cfg') or {}).items():
        if k.startswith(('MIKRO_', 'PDKS_')) and hasattr(config, k) and v not in (None, ''):
            setattr(config, k, int(v) if k.endswith('_PORT') else v)


def _mikro_query(args):
    _cfg(args)
    from . import mikro
    return mikro._query_direct(args['sql'], args.get('params'), args.get('db'))


def _mikro_ping(args):
    _cfg(args)
    from . import mikro
    return mikro.ping()          # query() üstüne kurulu; ajanda yerel çalışır


def _mikro_databases(args):
    _cfg(args)
    from . import mikro
    return mikro.databases()


# --- PDKS (Firebird) ---
def _pdks_personnel(args):
    _cfg(args)
    from . import pdks
    return pdks._fetch_personnel_direct()


def _pdks_attendance(args):
    _cfg(args)
    from . import pdks
    return pdks._daily_attendance_direct(args.get('date_from'), args.get('date_to'))


def _pdks_test(args):
    _cfg(args)
    from . import pdks
    ok, msg = pdks._test_direct()
    return {'ok': ok, 'message': msg}


# --- Yazıcılar (Moonraker) ---
def _printer_probe(args):
    from . import printer_driver
    return printer_driver._probe_direct(args['ip'])


def _printer_discover(args):
    from . import printer_driver
    return printer_driver._discover_local()   # fabrika LAN'ında tüm /24 bloğu taranır (ajan ağda)


def _printer_send(args):
    from . import printer_send
    return printer_send.agent_send(args)


# --- NVR (ağ kayıt cihazı — kameralar arkasında; ONVIF/RTSP, fabrika LAN'ında) ---
def _nvr_probe(args):
    from . import nvr
    return nvr._probe_direct(args)


def _nvr_channels(args):
    from . import nvr
    return nvr._channels_direct(args)


def _nvr_gpu(args):
    from . import nvr
    return nvr._gpu_capacity_direct(args)


def _nvr_snapshot(args):
    from . import nvr
    return nvr._snapshot_direct(args)


# --- Yüz tanıma (fabrika-yerel DB) — bulut bu op'larla görülme/grup/olay verisini çeker ve config iter ---
def _face_rpc(args):
    from . import db, facecore
    try:
        with db.connect() as conn:
            conn.execute('PRAGMA foreign_keys = OFF')   # fabrika aynası: bulut id'leri (user/person/family) yerel parent olmadan taşınır
            res = facecore.rpc(conn, args['method'], args.get('args') or {})
            conn.commit()
        return res
    except facecore.NotFound as e:
        return {'_err': 'notfound', 'msg': str(e)}
    except ValueError as e:
        return {'_err': 'bad', 'msg': str(e)}


def _face_media(args):
    from . import facecore
    try:
        return facecore.media_bytes(args['path'])
    except facecore.NotFound as e:
        return {'_err': 'notfound', 'msg': str(e)}


# --- Konuşma tanıma (GX10 ekran kartı): merkez WAV'ı kısa ömürlü bağlantıyla paylaşır, ajan indirip işler, metni döner ---
def _speech_status(args):
    import shutil
    import socket
    import subprocess
    from . import document_media as m
    gpu = None
    if shutil.which('nvidia-smi'):
        try:
            gpu = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True, text=True,
                                 timeout=10).stdout.strip().splitlines()[0] or None
        except Exception:   # noqa: BLE001
            gpu = None
    return {'whisper': m.WHISPER.exists(), 'model': m.WHISPER_MODEL.exists(), 'gpu': gpu, 'host': socket.gethostname()}


def _central_base():
    """Merkez adresi ajanın bağlandığı WS adresinden: wss://caymaz.app/ws/agent → https://caymaz.app"""
    import os
    url = os.environ.get('CAYMAZ_AGENT_CENTRAL_URL') or config.AGENT_CENTRAL_URL
    url = url.replace('wss://', 'https://', 1).replace('ws://', 'http://', 1)
    return url.split('/ws/', 1)[0].rstrip('/')


def _download(url, dest):
    import httpx
    with httpx.stream('GET', url, timeout=httpx.Timeout(60, read=300), follow_redirects=False) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)


def _speech_transcribe(args):
    import tempfile
    from pathlib import Path
    from . import document_media as m
    url = args['url']
    if not url.startswith('/api/agent/media/'):
        raise RuntimeError('geçersiz ses adresi')
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / 'a.wav'
        _download(_central_base() + url, wav)
        data = m.run_whisper(wav, args.get('lang') or 'auto', float(args.get('seconds') or 60))
    # yalnız gereken alanlar geri gönderilir (WS mesajı küçük kalsın)
    return {'result': {'language': (data.get('result') or {}).get('language')},
            'transcription': [{'text': s.get('text'), 'offsets': s.get('offsets')} for s in data.get('transcription', [])]}


# --- Entegrasyon makinesi (fabrika) kaynak grafiği — merkez sunucu DEĞİL ---
def _sysstat(args):
    from . import sysstat
    return sysstat.snapshot()


def _firmstat(args):
    """Firmanın entegrasyon süreçlerinin (camera_service/agent/…) kaynak kullanımı — makinenin tamamı değil."""
    from . import sysstat
    return sysstat.firm_load()


OPS = {
    'ping': _ping,
    'mikro.query': _mikro_query,
    'mikro.ping': _mikro_ping,
    'mikro.databases': _mikro_databases,
    'pdks.personnel': _pdks_personnel,
    'pdks.attendance': _pdks_attendance,
    'pdks.test': _pdks_test,
    'printer.probe': _printer_probe,
    'printer.discover': _printer_discover,
    'printer.send': _printer_send,
    'nvr.probe': _nvr_probe,
    'nvr.channels': _nvr_channels,
    'nvr.gpu': _nvr_gpu,
    'nvr.snapshot': _nvr_snapshot,
    'face.rpc': _face_rpc,
    'face.media': _face_media,
    'sysstat': _sysstat,
    'firmstat': _firmstat,
    'speech.status': _speech_status,
    'speech.transcribe': _speech_transcribe,
}


def register(name, fn):
    OPS[name] = fn
