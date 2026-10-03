"""Ekran paylaşımı / uzaktan destek — HEPGO uygulaması için.

Kullanıcı "Ekranı Paylaş" der; uygulama ekranı (DOM, rrweb ile) bir link üzerinden izleyiciye birebir yansır
(paylaşanın kendi boyutlarında; mobil dâhil). İzleyici imleciyle yol gösterir, tıklama/kaydırma/yazma ile müdahale
edebilir ve paylaşanla sesli/görüntülü konuşabilir (WebRTC). Oturum kısa ömürlü ve bellek-içidir; link'e şifre eklenebilir.

Sinyalleşme /ws/screen/{code} üzerinden relay edilir: paylaşan(host) ↔ izleyici(viewer). rrweb olayları ve kontrol/ses
sinyalleri aynı kanaldan taşınır (ekran görüntüsü düşük bant; ses/görüntü WebRTC ile uçtan uca).
"""
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(prefix='/api/screen')
ws_router = APIRouter()

# code -> oturum. Bellek-içi (kısa ömürlü); yeniden başlatmada düşer.
SESSIONS = {}
VIEWER_TOKENS = {}   # viewer_token -> code
TTL = 6 * 3600       # boşta kalan oturum üst sınırı


def _code():
    return ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(7))


def _public_base():
    from .. import config
    import os
    return (os.environ.get('CAYMAZ_PUBLIC_URL') or config.LOCAL_URL or '').rstrip('/')


class CreateIn(BaseModel):
    password: str = ''
    control: bool = True   # izleyici müdahale edebilsin mi (tıklama/kaydırma/yazma)


@router.post('')
def create(body: CreateIn, user=Depends(auth.current_user)):
    code = _code()
    while code in SESSIONS:
        code = _code()
    SESSIONS[code] = {
        'host_id': user['id'], 'host_name': user['full_name'],
        'pass_hash': auth.hash_password(body.password) if body.password.strip() else None,
        'control': bool(body.control), 'host_ws': None, 'viewers': {}, 'dims': None,
        'created': time.time(),
    }
    return {'code': code, 'link': f'{_public_base()}/s/{code}', 'control': bool(body.control), 'has_password': bool(body.password.strip())}


@router.get('/{code}')
def info(code: str):
    s = SESSIONS.get(code)
    if not s:
        return {'ok': False}
    return {'ok': True, 'host_name': s['host_name'], 'needs_password': bool(s['pass_hash']), 'live': s['host_ws'] is not None}


class AuthIn(BaseModel):
    password: str = ''
    name: str = ''


@router.post('/{code}/auth')
def auth_viewer(code: str, body: AuthIn):
    """İzleyici kapısı: şifre doğruysa (ya da şifre yoksa) WS için kısa ömürlü izleyici jetonu verir."""
    s = SESSIONS.get(code)
    if not s:
        raise HTTPException(404, 'Oturum bulunamadı ya da sona ermiş')
    if s['pass_hash'] and not auth.verify_password(body.password, s['pass_hash']):
        raise HTTPException(403, 'Şifre hatalı')
    tok = secrets.token_urlsafe(18)
    VIEWER_TOKENS[tok] = code
    return {'viewer_token': tok, 'host_name': s['host_name'], 'control': s['control']}


@router.post('/{code}/end')
def end(code: str, user=Depends(auth.current_user)):
    s = SESSIONS.get(code)
    if not s or s['host_id'] != user['id']:
        raise HTTPException(404, 'Oturum bulunamadı')
    SESSIONS.pop(code, None)
    return {'ok': True}


async def _send(ws, msg):
    try:
        await ws.send_json(msg)
    except Exception:   # noqa: BLE001
        pass


async def _to_viewers(s, msg, exclude=None):
    for cid, vw in list(s['viewers'].items()):
        if cid != exclude:
            await _send(vw['ws'], msg)


@ws_router.websocket('/ws/screen/{code}')
async def ws_screen(ws: WebSocket, code: str, role: str = 'viewer', vt: str = '', name: str = ''):
    await ws.accept()
    s = SESSIONS.get(code)
    if not s:
        await _send(ws, {'t': 'error', 'msg': 'Oturum yok'})
        await ws.close()
        return

    is_host = False
    if role == 'host':
        with db.connect() as conn:
            u = auth.user_by_token(conn, ws.cookies.get(auth.COOKIE))
        if not u or u['id'] != s['host_id']:
            await _send(ws, {'t': 'error', 'msg': 'Yetkisiz'})
            await ws.close()
            return
        is_host = True
        s['host_ws'] = ws
        # Geç bağlanan izleyiciler için host hazır; mevcut izleyicilere host'un geldiğini bildir
        await _to_viewers(s, {'t': 'host_online'})
    else:
        if VIEWER_TOKENS.get(vt) != code:
            await _send(ws, {'t': 'error', 'msg': 'Geçersiz bağlantı'})
            await ws.close()
            return
        cid = secrets.token_hex(6)
        s['viewers'][cid] = {'ws': ws, 'name': (name or 'İzleyici')[:60]}
        await _send(ws, {'t': 'ready', 'control': s['control'], 'host_name': s['host_name'], 'host_online': s['host_ws'] is not None})
        if s['dims']:
            await _send(ws, {'t': 'meta', 'dims': s['dims']})
        if s['host_ws']:   # host'tan yeni izleyici için tam anlık görüntü (full snapshot) iste
            await _send(s['host_ws'], {'t': 'viewer_join', 'cid': cid, 'name': s['viewers'][cid]['name']})

    try:
        while True:
            msg = await ws.receive_json()
            t = msg.get('t')
            if is_host:
                if t == 'dom':                       # rrweb olayları → izleyicilere
                    await _to_viewers(s, msg)
                elif t == 'meta':                    # paylaşanın ekran boyutu
                    s['dims'] = msg.get('dims')
                    await _to_viewers(s, msg)
                elif t in ('rtc', 'cursor', 'snapshot'):   # ses/görüntü sinyali ya da imleç → hedef izleyici
                    target = msg.get('to')
                    vw = s['viewers'].get(target)
                    if vw:
                        await _send(vw['ws'], msg)
                    elif t == 'snapshot':
                        await _to_viewers(s, msg)
                elif t == 'ended':
                    await _to_viewers(s, {'t': 'ended'})
            else:
                msg['from'] = cid
                if t in ('ctrl', 'cursor', 'rtc', 'full'):   # müdahale / imleç / ses sinyali / tam görüntü isteği → host
                    if s['control'] is False and t == 'ctrl':
                        continue
                    if s['host_ws']:
                        await _send(s['host_ws'], msg)
    except WebSocketDisconnect:
        pass
    except Exception:   # noqa: BLE001
        pass
    finally:
        if is_host:
            if s.get('host_ws') is ws:
                s['host_ws'] = None
            await _to_viewers(s, {'t': 'host_offline'})
        else:
            s['viewers'].pop(cid, None)
            if s.get('host_ws'):
                await _send(s['host_ws'], {'t': 'viewer_left', 'cid': cid})
