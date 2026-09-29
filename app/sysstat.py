"""Sunucu durumu (alt durum çubuğu): CPU, GPU, RAM ve disk; saniyede bir örneklenir, son 60 örnek tutulur.

Ek paket gerekmez: CPU ve RAM /proc'tan, GPU NVIDIA NVML'den (libnvidia-ml, ctypes), disk shutil'den okunur.
Tek bir arka plan iş parçacığı örnekler; istekler yalnızca hazır görüntüyü okur (istemci sayısı yükü artırmaz).
"""
import ctypes
import shutil
import threading
import time
from collections import deque

from . import config

HISTORY = 300   # 5 dk (durum çubuğu ayrıntı grafiği)
_lock = threading.Lock()
_history = deque(maxlen=HISTORY)   # [{'t', 'cpu', 'gpu', 'ram'}]
_latest = {}
_started = False


def _cpu_times():
    with open('/proc/stat') as f:
        v = [int(x) for x in f.readline().split()[1:]]
    idle = v[3] + (v[4] if len(v) > 4 else 0)   # idle + iowait
    return sum(v), idle


def _ram():
    info = {}
    with open('/proc/meminfo') as f:
        for line in f:
            k, v = line.split(':', 1)
            info[k] = int(v.split()[0]) * 1024
    total, avail = info['MemTotal'], info.get('MemAvailable', info['MemFree'])
    return total, total - avail


class _Gpu:
    """NVML ile GPU kullanımı ve sıcaklığı; sürücü yoksa None döner."""

    class _Util(ctypes.Structure):
        _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]

    def __init__(self):
        self.lib = self.handle = None
        self.name = None
        try:
            lib = ctypes.CDLL('libnvidia-ml.so.1')
            if lib.nvmlInit_v2() != 0:
                return
            h = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) != 0:
                return
            buf = ctypes.create_string_buffer(96)
            if lib.nvmlDeviceGetName(h, buf, 96) == 0:
                self.name = buf.value.decode(errors='replace')
            self.lib, self.handle = lib, h
        except OSError:
            pass

    def sample(self):
        if not self.lib:
            return None, None
        u, t = self._Util(), ctypes.c_uint()
        util = u.gpu if self.lib.nvmlDeviceGetUtilizationRates(self.handle, ctypes.byref(u)) == 0 else None
        temp = t.value if self.lib.nvmlDeviceGetTemperature(self.handle, 0, ctypes.byref(t)) == 0 else None
        return util, temp


def _loop():
    gpu = _Gpu()
    prev = _cpu_times()
    while True:
        time.sleep(1)
        try:
            cur = _cpu_times()
            dt, di = cur[0] - prev[0], cur[1] - prev[1]
            prev = cur
            cpu = round(100 * (dt - di) / dt, 1) if dt > 0 else 0.0
            total, used = _ram()
            g, temp = gpu.sample()
            disk = shutil.disk_usage(config.DATA_DIR)
            point = {'t': int(time.time()), 'cpu': cpu, 'gpu': g, 'ram': round(100 * used / total, 1)}
            with _lock:
                _history.append(point)
                _latest.update(cpu=cpu, gpu=g, gpu_temp=temp, gpu_name=gpu.name, ram_total=total, ram_used=used,
                               disk_total=disk.total, disk_used=disk.used, disk_free=disk.free)
        except Exception:
            pass


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name='sysstat').start()


def snapshot():
    with _lock:
        return {**_latest, 'history': list(_history)}
