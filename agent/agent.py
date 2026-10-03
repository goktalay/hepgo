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
from app import agent_ops, config, sysstat   # noqa: E402

sysstat.start()   # entegrasyon makinesinin (fabrika) kaynak grafiği için örnekleme

URL = os.environ.get('CAYMAZ_AGENT_CENTRAL_URL') or config.AGENT_CENTRAL_URL
KEY = os.environ.get('CAYMAZ_AGENT_KEY') or config.AGENT_KEY


async def _handle(ws, m):
    rid, op = m.get('id'), m.get('op')
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
                await ws.send(json.dumps({'t': 'auth', 'key': KEY, 'host': socket.gethostname()}))
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
                    if m.get('t') == 'req':
                        asyncio.create_task(_handle(ws, m))
        except Exception as e:   # noqa: BLE001
            print(f'Bağlantı koptu/başarısız ({e}); 5 sn sonra yeniden denenecek.')
            await asyncio.sleep(5)


if __name__ == '__main__':
    asyncio.run(run())
