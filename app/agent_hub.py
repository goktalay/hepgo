"""Merkez tarafı: fabrika ajanı hub'ı (/ws/agent).

Fabrikadaki ajan buraya DIŞA DOĞRU (WSS) bağlanır; merkez bu bağlantı üzerinden cihaz op'ları çağırır
(istek/yanıt, id ile eşlenir).

AŞAMA 2 — ÇOK AJANLI YÖNLENDİRME (geriye dönük uyumlu):
Eskiden süreç başına TEK global `_agent` vardı ve bu "her şeyi yapan" ajan (gx10) tüm op'lara bakardı.
Artık her entegrasyon (Mikro ERP, PDKS, Yazıcılar, Kameralar/NVR, Yüz Tanıma) KENDİ anahtarıyla AYRI bir
ajan olarak bağlanabilir. Bağlı ajanlar bir KAYIT DEFTERİNDE (`_agents`) "slot" adıyla tutulur:
    'mikro' · 'pdks' · 'printer' · 'camera' · 'face'  (entegrasyon-başına ajanlar, Aşama 2)
    'legacy'                                            (eski tekil tüm-bir-arada ajan — gx10, CANLI)

Kimlik:
- Eğer ajan eski paylaşılan anahtarı (config.AGENT_KEY / .env) yollarsa → 'legacy' slot'una yazılır ve
  BUGÜNKÜ gibi TÜM op'lara hizmet eder (davranış AYNEN korunur — canlıda bir ajan şu an bağlı).
- Aksi halde anahtar per-entegrasyon deposundan (agentkeys.integ_for_key) çözülür → ilgili slot'a yazılır.
- Hiçbiri değilse kimlik reddi (4403), eskisi gibi.

Op yönlendirmesi (agent_call/call_sync):
- op ön-ekine göre entegrasyon bulunur (mikro.* → mikro, pdks.* → pdks, printer.* → printer,
  nvr.* → camera, face.* → face; ping/sysstat/speech.* gibi genel op'lar → entegrasyon YOK).
- Hedef ws: entegrasyonun kendi slot'u bağlıysa oraya; DEĞİLSE 'legacy' slot'una (geri düşüş — bugünkü
  tek-ajan davranışı korunur); o da yoksa eskisi gibi "Fabrika ajanı bağlı değil" hatası.
"""
import asyncio
import datetime
import json
import secrets

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import agentkeys, config, db


def _dec(d):
    """Ajanın işaretli taşıdığı tarihleri (agent._enc) yerel moddaki gibi datetime/date nesnesine geri çevirir."""
    if len(d) == 1:
        if '__dt__' in d:
            return datetime.datetime.fromisoformat(d['__dt__'])
        if '__d__' in d:
            return datetime.date.fromisoformat(d['__d__'])
    return d

ws_router = APIRouter()

# Entegrasyon-başına slot adları (agentkeys.INTEGRATIONS ile birebir aynı: mikro/pdks/printer/camera/face).
_INTEG_SLOTS = ('mikro', 'pdks', 'printer', 'camera', 'face')
# 'legacy' = eski tekil tüm-bir-arada ajan (gx10). Kayıt defterinin tüm olası slot'ları:
_SLOTS = _INTEG_SLOTS + ('legacy',)

# Op ön-eki (ilk nokta öncesi) → entegrasyon slot'u. Burada OLMAYAN op (ping, sysstat, speech.*) genel
# sayılır ve yalnız 'legacy' ajana gider (tek-ajan davranışının korunması için).
_OP_INTEG = {
    'mikro':   'mikro',
    'pdks':    'pdks',
    'printer': 'printer',
    'nvr':     'camera',   # DİKKAT: op ön-eki 'nvr' ama entegrasyon/slot adı 'camera'
    'face':    'face',
}

_agents = {}             # slot -> bağlı ajanın WebSocket'i (yalnız CANLI bağlantılar bulunur)
_infos = {}              # slot -> {'connected_at', 'host', 'slot'}
_pending = {}            # istek id -> asyncio.Future (TÜM slot'lar arası paylaşımlı; rid'ler benzersiz)
_pending_owner = {}      # istek id -> isteğin gönderildiği ws (bir ajan düşünce yalnız KENDİ istekleri iptal edilsin)
_loop = None             # ana olay döngüsü (senkron cihaz kodundan ajana köprü için)


def set_loop(loop):
    global _loop
    _loop = loop


def online():
    """Geriye dönük: HERHANGİ bir ajan (legacy ya da herhangi bir entegrasyon) bağlıysa True.
    Mevcut çağıranlar için anlam değişmez — canlı legacy ajan bağlıyken True döner."""
    return any(ws is not None for ws in _agents.values())


def online_integ(integ):
    """Belirli bir entegrasyon için erişilebilirlik: o entegrasyonun kendi slot'u YA DA legacy ajan bağlı mı?
    (legacy tüm-bir-arada ajan o entegrasyona da hizmet edebildiği için dahil edilir.)"""
    return _agents.get(integ) is not None or _agents.get('legacy') is not None


def _primary_info():
    """status()'un üst-düzey (eski biçim) connected_at/host alanları için temsili bilgi:
    legacy ajan varsa onunki; yoksa bağlı ilk slot'unki; hiçbiri yoksa boş."""
    if _infos.get('legacy'):
        return _infos['legacy']
    for slot in _SLOTS:
        if _infos.get(slot):
            return _infos[slot]
    return {'connected_at': None, 'host': None}


def status():
    """Üst-düzey alanlar ESKİ biçimde korunur (online + connected_at + host) ki mevcut admin UI bozulmasın.
    EK olarak 'slots': her slot için {connected, host, connected_at} özeti (per-entegrasyon bağlanırlık)."""
    base = _primary_info()
    slots = {}
    for slot in _SLOTS:
        info = _infos.get(slot) or {}
        slots[slot] = {
            'connected': _agents.get(slot) is not None,
            'host': info.get('host'),
            'connected_at': info.get('connected_at'),
        }
    return {'online': online(),
            'connected_at': base.get('connected_at'),
            'host': base.get('host'),
            'slots': slots}


def _slot_for_op(op):
    """op ön-ekinden (ilk nokta öncesi) hedef entegrasyon slot'u; genel op ise None."""
    prefix = (op or '').split('.', 1)[0]
    return _OP_INTEG.get(prefix)


def _target_ws(op):
    """Op için hedef ws seçimi: entegrasyonun kendi slot'u bağlıysa o; değilse legacy (geri düşüş); yoksa None.
    Genel op'larda (entegrasyon yok) doğrudan legacy ajana gider."""
    integ = _slot_for_op(op)
    if integ is not None:
        ws = _agents.get(integ)
        if ws is not None:
            return ws
    # Geri düşüş: tek tüm-bir-arada (legacy) ajan — bugünkü davranış: tek ajan her op'a bakar.
    return _agents.get('legacy')


def call_sync(op, args=None, timeout=25):
    """Senkron (thread/threadpool) cihaz kodundan ajana çağrı köprüsü."""
    if _loop is None:
        raise RuntimeError('Olay döngüsü hazır değil')
    fut = asyncio.run_coroutine_threadsafe(agent_call(op, args, timeout), _loop)
    return fut.result(timeout + 5)


async def agent_call(op, args=None, timeout=25):
    """Fabrika ajanına bir op gönderir ve sonucunu bekler. İlgili ajan bağlı değilse / zaman aşımında hata fırlatır.
    Hedef ajan op ön-ekine göre seçilir (entegrasyon slot'u → yoksa legacy geri düşüş)."""
    ws = _target_ws(op)
    if ws is None:
        raise RuntimeError('Fabrika ajanı bağlı değil')
    rid = secrets.token_hex(8)
    fut = asyncio.get_event_loop().create_future()
    _pending[rid] = fut
    _pending_owner[rid] = ws
    try:
        await ws.send_text(json.dumps({'t': 'req', 'id': rid, 'op': op, 'args': args or {}}))
        return await asyncio.wait_for(fut, timeout)
    finally:
        _pending.pop(rid, None)
        _pending_owner.pop(rid, None)


async def _push_face_config():
    """Ajan bağlanınca bulut yüz-tanıma ayarını fabrikaya aktarır (fabrika yeniden başlasa da senkron kalır).
    Yalnız 'face' veya 'legacy' slot bağlanınca anlamlı (yüz-tanıma ajanı / tüm-bir-arada ajan)."""
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


@ws_router.get('/api/agent/media/{token}')
def agent_media(token: str):
    """Fabrika ajanının konuşma tanıma için indirdiği ses (16 kHz WAV). Oturum gerekmez: jeton tahmin edilemez
    (32 bayt), yalnız iş sürerken ve en çok 30 dk geçerli (document_media.share_media)."""
    from . import document_media
    path = document_media.shared_media(token)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type='audio/wav', headers={'Cache-Control': 'no-store'})


def _resolve_slot(first):
    """İlk 'auth' mesajından slot'u belirler.
    - key == config.AGENT_KEY (dolu) → 'legacy' (eski gx10 davranışı: tüm op'lara bakar). ANAHTAR YETKİLİDİR.
    - aksi halde agentkeys.integ_for_key(key) → entegrasyon slot'u (varsa).
    - hiçbiri → None (kimlik reddi).
    Not: istemci 'integ' ipucu yollasa bile ANAHTAR yetkilidir; çelişirlerse anahtara güvenilir
    (integ_for_key zaten anahtardan çözdüğü için ipucu dikkate alınmaz)."""
    key = first.get('key')
    if key and config.AGENT_KEY and key == config.AGENT_KEY:
        return 'legacy'
    integ = agentkeys.integ_for_key(key)
    if integ in _INTEG_SLOTS:
        return integ
    return None


@ws_router.websocket('/ws/agent')
async def ws_agent(ws: WebSocket):
    await ws.accept()
    # Kimlik: ilk mesaj {t:'auth', key:..., host:..., integ?:...}
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), 15))
    except Exception:   # noqa: BLE001
        await ws.close(code=4400)
        return
    slot = _resolve_slot(first) if first.get('t') == 'auth' else None
    if slot is None:
        try:
            await ws.send_text(json.dumps({'t': 'auth', 'ok': False}))
        except Exception:   # noqa: BLE001
            pass
        await ws.close(code=4403)
        return

    # Slot'a (yeniden) bağlanma: aynı slot'taki önceki ws'yi kapat (eski tek-slot mantığının slot-başına hali).
    prev = _agents.get(slot)
    _agents[slot] = ws
    _infos[slot] = {'connected_at': db.now(), 'host': str(first.get('host') or ''), 'slot': slot}
    if prev is not None and prev is not ws:
        try:
            await prev.close()
        except Exception:   # noqa: BLE001
            pass
    await ws.send_text(json.dumps({'t': 'auth', 'ok': True}))
    try:
        with db.connect() as conn:
            db.audit(conn, None, f'Fabrika ajanı bağlandı ({slot})', 'agent', slot, _infos[slot]['host'])
            conn.commit()
    except Exception:   # noqa: BLE001
        pass
    # Yüz-tanıma ayarını yalnız ilgili ajan (face) ya da tüm-bir-arada (legacy) ajan bağlanınca fabrikaya aktar.
    if slot in ('face', 'legacy'):
        asyncio.create_task(_push_face_config())

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
        # Yalnız bu ws hâlâ slot'un sahibiyse slot'u boşalt (arada yeni bir bağlantı gelmiş olabilir).
        if _agents.get(slot) is ws:
            _agents.pop(slot, None)
            _infos.pop(slot, None)
        # Yalnız BU ws'ye gönderilmiş bekleyen istekleri iptal et (diğer ajanların istekleri etkilenmesin).
        for rid, fut in list(_pending.items()):
            if _pending_owner.get(rid) is ws and not fut.done():
                fut.set_exception(RuntimeError('Fabrika ajanı bağlantısı koptu'))
