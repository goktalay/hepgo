"""Kilitlenme dedektörü: olay döngüsü (asyncio) belirli süreden uzun yanıt vermezse o anda tüm iş parçacıklarının
yığın izlerini veri klasörüne (stall-*.log) yazar. Sunucu donduğunda nedenin bulunabilmesi için."""
import asyncio
import sys
import threading
import time
import traceback
from datetime import datetime

from . import config

_last = time.monotonic()
STALL_SECONDS = 10


async def _beat():
    global _last
    while True:
        _last = time.monotonic()
        await asyncio.sleep(1)


def _dump(stalled):
    names = {t.ident: t.name for t in threading.enumerate()}
    lines = [f'# Olay döngüsü {stalled:.0f} sn yanıt vermedi · {datetime.now().isoformat(timespec="seconds")}\n']
    for tid, frame in sys._current_frames().items():
        lines.append(f'\n--- İş parçacığı {names.get(tid, "?")} ({tid}) ---\n')
        lines.extend(traceback.format_stack(frame))
    path = config.DATA_DIR / f'stall-{datetime.now():%Y%m%d-%H%M%S}.log'
    path.write_text(''.join(lines), encoding='utf-8')
    print(f'[watchdog] olay döngüsü dondu ({stalled:.0f} sn) → {path}', flush=True)


def _watch():
    dumped = False
    while True:
        time.sleep(2)
        stalled = time.monotonic() - _last
        if stalled > STALL_SECONDS and not dumped:
            try:
                _dump(stalled)
            except Exception as e:   # noqa: BLE001
                print(f'[watchdog] yazılamadı: {e}', flush=True)
            dumped = True
        elif stalled < 3:
            dumped = False


def start():
    asyncio.get_running_loop().create_task(_beat())
    threading.Thread(target=_watch, daemon=True, name='watchdog').start()
