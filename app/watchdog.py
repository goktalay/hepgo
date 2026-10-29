"""Kilitlenme dedektörü: olay döngüsü (asyncio) belirli süreden uzun yanıt vermezse o anda tüm iş parçacıklarının
yığın izlerini veri klasörüne (stall-*.log) yazar. Sunucu donduğunda nedenin bulunabilmesi için."""
import asyncio
import os
import sys
import threading
import time
import traceback
from datetime import datetime

from . import config, db

_last = time.monotonic()
STALL_SECONDS = 10
LEAK_EVERY = int(os.environ.get('CAYMAZ_LEAK_EVERY', '900'))   # sn: açık bağlantı denetimi
LEAK_WARN = int(os.environ.get('CAYMAZ_LEAK_WARN', '20'))       # bu kadar eskimiş (10 dk+) bağlantı varsa kod yerleriyle günlüğe yazılır


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


def _leak_check():
    total, old, sites = db.leak_report()
    if old < LEAK_WARN:
        return
    try:
        fds = len(os.listdir('/proc/self/fd'))
    except OSError:
        fds = -1
    print(f'[watchdog] {old} veritabanı bağlantısı 10 dk+ açık (toplam {total}, dosya tanıtıcısı {fds}): '
          + ' | '.join(f'{n}× {s}' for s, n in sites), flush=True)


def _watch():
    dumped = False
    next_leak = time.monotonic() + LEAK_EVERY
    while True:
        time.sleep(2)
        if time.monotonic() >= next_leak:
            next_leak = time.monotonic() + LEAK_EVERY
            try:
                _leak_check()
            except Exception as e:   # noqa: BLE001
                print(f'[watchdog] bağlantı denetimi: {e}', flush=True)
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
