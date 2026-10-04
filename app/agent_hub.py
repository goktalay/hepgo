"""Merkez tarafı: fabrika ajanı hub'ı (/ws/agent).

Fabrikadaki ajan buraya DIŞA DOĞRU (WSS) bağlanır; merkez bu bağlantı üzerinden cihaz op'ları çağırır
(istek/yanıt, id ile eşlenir). Her firma süreci tek ajan bekler (bir fabrika = bir tenant).

Kimlik: ajan ilk mesajda paylaşılan anahtarı (config.AGENT_KEY) yollar. Bağlı değilse agent_call hata verir.
"""
import asyncio
import datetime
import hmac
import json
import secrets

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

from . import config, db


def _dec(d):
    """Ajanın işaretli taşıdığı tarihleri (agent._enc) yerel moddaki gibi datetime/date nesnesine geri çevirir."""
    if len(d) == 1:
        if '__dt__' in d:
            return datetime.datetime.fromisoformat(d['__dt__'])
        if '__d__' in d:
            return datetime.date.fromisoformat(d['__d__'])
    return d

ws_router = APIRouter()

_agent = None            # bağlı ajanın WebSocket'i (süreç başına tek)
_pending = {}            # istek id -> asyncio.Future
_info = {'connected_at': None, 'host': None, 'version': None, 'bundle': None, 'caps': []}
_terms = {}               # terminal oturumu -> asyncio.Queue (ajandan gelen çıktı; None = kapandı)
_loop = None             # ana olay döngüsü (senkron cihaz kodundan ajana köprü için)


def set_loop(loop):
    global _loop
    _loop = loop


def online():
    return _agent is not None


def call_sync(op, args=None, timeout=25):
    """Senkron (thread/threadpool) cihaz kodundan ajana çağrı köprüsü."""
    if _loop is None:
        raise RuntimeError('Olay döngüsü hazır değil')
    fut = asyncio.run_coroutine_threadsafe(agent_call(op, args, timeout), _loop)
    return fut.result(timeout + 5)


def status():
    return {'online': online(), **_info}


async def agent_call(op, args=None, timeout=25):
    """Fabrika ajanına bir op gönderir ve sonucunu bekler. Ajan bağlı değilse / zaman aşımında hata fırlatır."""
    ws = _agent
    if ws is None:
        raise RuntimeError('Fabrika ajanı bağlı değil')
    rid = secrets.token_hex(8)
    fut = asyncio.get_event_loop().create_future()
    _pending[rid] = fut
    try:
        await ws.send_text(json.dumps({'t': 'req', 'id': rid, 'op': op, 'args': args or {}}))
        return await asyncio.wait_for(fut, timeout)
    finally:
        _pending.pop(rid, None)


async def _push_face_config():
    """Ajan bağlanınca bulut yüz-tanıma ayarını fabrikaya aktarır (fabrika yeniden başlasa da senkron kalır)."""
    await asyncio.sleep(1.0)   # bağlantının oturması
    try:
        from fastapi.concurrency import run_in_threadpool
        from . import facebridge

        def work():
            with db.connect() as conn:
                return facebridge.push(conn)
        await run_in_threadpool(work)
    except Exception:   # noqa: BLE001
        pass


async def _on_event(event, data):
    """Ajandan gelen itme (push) olayları — ör. yazıcı durum güncellemesi. İleride DB'ye yazılır."""
    # Harita sonrası: 'printer.status' vb. burada işlenecek.
    return


async def send(msg):
    """Ajana tek yönlü mesaj (terminal girdisi vb.)."""
    ws = _agent
    if ws is None:
        raise RuntimeError('Fabrika ajanı bağlı değil')
    await ws.send_text(json.dumps(msg))


# ---------------- Ajan kod paketi (uzaktan güncelleme) ----------------
_bundle = {'key': None, 'data': None, 'sha': None}


def bundle():
    """Merkezde çalışan kodun ajan için paketi (app/, agent/, requirements.txt) → (tar.gz baytları, sha256).
    Dosyalar değişmedikçe aynı paket (aynı özet) döner — ajanın güncel olup olmadığı bu özetle anlaşılır."""
    import hashlib
    import io
    import tarfile
    base = config.BASE_DIR
    files = sorted(p for d in ('app', 'agent') for p in (base / d).rglob('*')
                   if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc') + [base / 'requirements.txt']
    key = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    if _bundle['key'] != key:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=6) as tar:
            for p in files:
                info = tar.gettarinfo(str(p), arcname=str(p.relative_to(base)))
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.mtime = 0   # aynı içerik → aynı özet
                with open(p, 'rb') as f:
                    tar.addfile(info, f)
        data = buf.getvalue()
        _bundle.update(key=key, data=data, sha=hashlib.sha256(data).hexdigest())
    return _bundle['data'], _bundle['sha']


@ws_router.get('/api/agent/bundle')
def agent_bundle(request: Request):
    """Ajanın kendini güncellemek için indirdiği kod paketi. Yalnız ajan anahtarıyla (X-Agent-Key)."""
    key = request.headers.get('x-agent-key', '')
    if not config.AGENT_KEY or not hmac.compare_digest(key.encode(), config.AGENT_KEY.encode()):
        raise HTTPException(403)
    data, sha = bundle()
    return Response(data, media_type='application/gzip', headers={'X-Bundle-SHA256': sha, 'Cache-Control': 'no-store'})


@ws_router.get('/api/agent/bootstrap.sh')
def agent_bootstrap():
    """Fabrikadaki makinede ajanı İLK KEZ güncellemek için betik (gizli bilgi içermez; anahtar makinenin .env'inden okunur)."""
    return FileResponse(config.BASE_DIR / 'agent' / 'bootstrap.sh', media_type='text/x-shellscript',
                        headers={'Cache-Control': 'no-store'})


@ws_router.get('/api/agent/media/{token}')
def agent_media(token: str):
    """Fabrika ajanının konuşma tanıma için indirdiği ses (16 kHz WAV). Oturum gerekmez: jeton tahmin edilemez
    (32 bayt), yalnız iş sürerken ve en çok 30 dk geçerli (document_media.share_media)."""
    from . import document_media
    path = document_media.shared_media(token)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type='audio/wav', headers={'Cache-Control': 'no-store'})


@ws_router.websocket('/ws/agent')
async def ws_agent(ws: WebSocket):
    await ws.accept()
    # Kimlik: ilk mesaj {t:'auth', key:..., host:...}
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), 15))
    except Exception:   # noqa: BLE001
        await ws.close(code=4400)
        return
    if (first.get('t') != 'auth' or not config.AGENT_KEY
            or not hmac.compare_digest(str(first.get('key') or '').encode(), config.AGENT_KEY.encode())):
        try:
            await ws.send_text(json.dumps({'t': 'auth', 'ok': False}))
        except Exception:   # noqa: BLE001
            pass
        await ws.close(code=4403)
        return

    global _agent
    prev = _agent
    _agent = ws
    _info.update(connected_at=db.now(), host=str(first.get('host') or ''), version=first.get('version'),
                 bundle=first.get('bundle'), caps=[c for c in (first.get('caps') or []) if isinstance(c, str)])
    if prev is not None:
        try:
            await prev.close()
        except Exception:   # noqa: BLE001
            pass
    await ws.send_text(json.dumps({'t': 'auth', 'ok': True}))
    try:
        with db.connect() as conn:
            db.audit(conn, None, 'Fabrika ajanı bağlandı', 'agent', None, _info['host'])
            conn.commit()
    except Exception:   # noqa: BLE001
        pass
    asyncio.create_task(_push_face_config())   # bağlanınca yüz-tanıma ayarını (NVR/kanal/vardiya/eğitim) fabrikaya aktar

    try:
        while True:
            m = json.loads(await ws.receive_text(), object_hook=_dec)
            t = m.get('t')
            if t == 'res':
                fut = _pending.get(m.get('id'))
                if fut and not fut.done():
                    if m.get('ok'):
                        fut.set_result(m.get('result'))
                    else:
                        fut.set_exception(RuntimeError(m.get('error') or 'ajan hatası'))
            elif t == 'event':
                await _on_event(m.get('event'), m.get('data'))
            elif t == 'ping':
                await ws.send_text(json.dumps({'t': 'pong'}))
            elif t in ('term.out', 'term.exit'):
                q = _terms.get(m.get('sid'))
                if q is not None:
                    q.put_nowait(m.get('d') if t == 'term.out' else None)
    except (WebSocketDisconnect, Exception):   # noqa: BLE001
        pass
    finally:
        if _agent is ws:
            _agent = None
        for fut in list(_pending.values()):
            if not fut.done():
                fut.set_exception(RuntimeError('Fabrika ajanı bağlantısı koptu'))
        for q in list(_terms.values()):
            q.put_nowait(None)
