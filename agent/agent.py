"""Fabrika ajanı — fabrikada çalışır, merkeze (bulut) DIŞA DOĞRU bağlanır ve yerel cihaz op'larını çalıştırır.

Merkez buluta taşındığında Mikro ERP, PDKS ve yazıcılar fabrika LAN'ında kalır; bu ajan onlara erişir.
Fabrikada açık port gerekmez (yalnız giden WSS bağlantısı). Merkez {t:'req',id,op,args} yollar, ajan
app.agent_ops.OPS[op](args) çalıştırıp {t:'res',id,ok,result/error} döner.

Çalıştırma (fabrikadaki caymazbuild kökünden):
  CAYMAZ_AGENT_CENTRAL_URL=wss://caymaz.app/ws/agent \
  CAYMAZ_AGENT_KEY=<merkezdeki CAYMAZ_AGENT_KEY ile aynı> \
  .venv/bin/python -m agent.agent
Fabrika cihaz bağlantı bilgileri (MIKRO_*, PDKS_*) ajanın .env'inde / ortamında olmalı; ajan AGENT_MODE=local
çalışır (op'ları doğrudan yürütür).
Uzaktan terminal ve kendini güncelleme: agent/remote.py (yalnız bu makinenin .env'inde açıkça izin verilirse).
"""
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

# caymazbuild kökünü yola ekle (app.* içe aktarmak için)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ['CAYMAZ_AGENT_MODE'] = 'local'   # ajan op'ları doğrudan çalıştırır (merkeze geri yönlendirmez)
os.environ.setdefault('CAYMAZ_PRINTER_POLL', '0')  # ajan yoklama döngüsü çalıştırmaz; merkez tetikler

import websockets   # noqa: E402
import datetime as _dt   # noqa: E402
import decimal as _dec   # noqa: E402


def _enc(o):
    """JSON'a sığmayan veritabanı tipleri (Mikro/PDKS): tarih işaretli taşınır, merkez (agent_hub) geri çevirir."""
    if isinstance(o, _dt.datetime):
        return {'__dt__': o.isoformat()}
    if isinstance(o, _dt.date):
        return {'__d__': o.isoformat()}
    if isinstance(o, _dt.time):
        return o.isoformat()
    if isinstance(o, _dec.Decimal):
        return float(o)
    if isinstance(o, (bytes, bytearray, memoryview)):
        return bytes(o).hex()
    return str(o)
from app import agent_ops, changelog, config, sysstat   # noqa: E402
from agent import remote   # noqa: E402

sysstat.start()   # entegrasyon makinesinin (fabrika) kaynak grafiği için örnekleme

URL = os.environ.get('CAYMAZ_AGENT_CENTRAL_URL') or config.AGENT_CENTRAL_URL
KEY = os.environ.get('CAYMAZ_AGENT_KEY') or config.AGENT_KEY


_terms = {}   # oturum → remote.Term (Araçlar › Terminal › Fabrika)
_restart = False


async def _term_open(ws, m):
    sid = str(m.get('sid'))
    if not remote.allowed('CAYMAZ_AGENT_TERMINAL'):
        await ws.send(json.dumps({'t': 'term.out', 'sid': sid, 'd': '\x1b[31mBu makinede uzaktan terminal izni yok '
                                  '(.env: CAYMAZ_AGENT_TERMINAL=1).\x1b[0m\r\n'}))
        await ws.send(json.dumps({'t': 'term.exit', 'sid': sid}))
        return
    term = remote.Term(m.get('rows') or 24, m.get('cols') or 80)
    _terms[sid] = term
    print(f'Uzaktan terminal açıldı ({sid[:6]})')
    try:
        while True:
            data = await asyncio.to_thread(term.read)
            if not data:
                break
            await ws.send(json.dumps({'t': 'term.out', 'sid': sid, 'd': data.decode('utf-8', 'replace')}))
    finally:
        _terms.pop(sid, None)
        await asyncio.to_thread(term.close)
        try:
            await ws.send(json.dumps({'t': 'term.exit', 'sid': sid}))
        except Exception:   # noqa: BLE001
            pass


def _term_msg(m):
    term = _terms.get(str(m.get('sid')))
    if not term:
        return
    if m['t'] == 'term.in':
        term.write(m.get('d') or '')
    elif m['t'] == 'term.resize':
        term.resize(m.get('rows') or 24, m.get('cols') or 80)
    elif m['t'] == 'term.close':
        term.close()


def _update(args):
    """Merkezden kod paketi indir, doğrula, uygula; yanıt gönderildikten sonra ajan yeniden başlar."""
    global _restart
    if not remote.allowed('CAYMAZ_AGENT_UPDATE'):
        raise RuntimeError('Bu makinede uzaktan güncelleme izni yok (.env: CAYMAZ_AGENT_UPDATE=1)')
    import httpx
    url = agent_ops._central_base() + '/api/agent/bundle'
    r = httpx.get(url, headers={'X-Agent-Key': KEY}, timeout=120)
    r.raise_for_status()
    out = remote.apply_bundle(r.content, args['sha256'])
    _restart = True
    return out


async def _handle(ws, m):
    rid, op = m.get('id'), m.get('op')
    if op == 'agent.update':
        try:
            result = await asyncio.to_thread(_update, m.get('args') or {})
            await ws.send(json.dumps({'t': 'res', 'id': rid, 'ok': True, 'result': result}))
        except Exception as e:   # noqa: BLE001
            await ws.send(json.dumps({'t': 'res', 'id': rid, 'ok': False, 'error': str(e)}))
        if _restart:
            print('Kod güncellendi; ajan yeniden başlıyor.')
            await asyncio.sleep(0.5)
            for term in list(_terms.values()):
                term.close()
            await ws.close()
            os.chdir(remote.ROOT)
            os.execv(sys.executable, [sys.executable, '-m', 'agent.agent'])
        return
    try:
        fn = agent_ops.OPS.get(op)
        if not fn:
            raise RuntimeError(f'bilinmeyen op: {op}')
        result = await asyncio.to_thread(fn, m.get('args') or {})
        await ws.send(json.dumps({'t': 'res', 'id': rid, 'ok': True, 'result': result}, default=_enc))
    except Exception as e:   # noqa: BLE001
        await ws.send(json.dumps({'t': 'res', 'id': rid, 'ok': False, 'error': str(e)}))


async def run():
    if not URL or not KEY:
        print('HATA: CAYMAZ_AGENT_CENTRAL_URL ve CAYMAZ_AGENT_KEY gerekli.')
        return
    while True:
        try:
            async with websockets.connect(URL, max_size=None, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({'t': 'auth', 'key': KEY, 'host': socket.gethostname(), 'version': changelog.VERSION,
                                          'bundle': remote.bundle_id(), 'caps': remote.caps()}))
                ack = json.loads(await ws.recv())
                if not ack.get('ok'):
                    print('Kimlik reddedildi (anahtar yanlış?). 15 sn sonra tekrar.')
                    await asyncio.sleep(15)
                    continue
                print(f'Ajan bağlı: {URL}')
                async for raw in ws:
                    try:
                        m = json.loads(raw)
                    except ValueError:
                        continue
                    t = m.get('t')
                    if t == 'req':
                        asyncio.create_task(_handle(ws, m))
                    elif t == 'term.open':
                        asyncio.create_task(_term_open(ws, m))
                    elif t in ('term.in', 'term.resize', 'term.close'):
                        _term_msg(m)
        except Exception as e:   # noqa: BLE001
            print(f'Bağlantı koptu/başarısız ({e}); 5 sn sonra yeniden denenecek.')
            await asyncio.sleep(5)


if __name__ == '__main__':
    asyncio.run(run())
