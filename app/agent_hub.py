"""Merkez tarafı: fabrika ajanı hub'ı (/ws/agent).

Fabrikadaki ajan buraya DIŞA DOĞRU (WSS) bağlanır; merkez bu bağlantı üzerinden cihaz op'ları çağırır
(istek/yanıt, id ile eşlenir). Her firma süreci tek ajan bekler (bir fabrika = bir tenant).

Kimlik: ajan ilk mesajda paylaşılan anahtarı (config.AGENT_KEY) yollar. Bağlı değilse agent_call hata verir.
"""
import asyncio
import datetime
import json
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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
_info = {'connected_at': None, 'host': None}
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


@ws_router.websocket('/ws/agent')
async def ws_agent(ws: WebSocket):
    await ws.accept()
    # Kimlik: ilk mesaj {t:'auth', key:..., host:...}
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), 15))
    except Exception:   # noqa: BLE001
        await ws.close(code=4400)
        return
    if first.get('t') != 'auth' or not config.AGENT_KEY or first.get('key') != config.AGENT_KEY:
        try:
            await ws.send_text(json.dumps({'t': 'auth', 'ok': False}))
        except Exception:   # noqa: BLE001
            pass
        await ws.close(code=4403)
        return

    global _agent
    prev = _agent
    _agent = ws
    _info.update(connected_at=db.now(), host=str(first.get('host') or ''))
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
    except (WebSocketDisconnect, Exception):   # noqa: BLE001
        pass
    finally:
        if _agent is ws:
            _agent = None
        for fut in list(_pending.values()):
            if not fut.done():
                fut.set_exception(RuntimeError('Fabrika ajanı bağlantısı koptu'))
