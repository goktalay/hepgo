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


def _net_bytes():
    """Tüm fiziksel arayüzlerin (lo hariç) toplam alınan / gönderilen bayt sayısı (/proc/net/dev)."""
    rx = tx = 0
    with open('/proc/net/dev') as f:
        for line in f.readlines()[2:]:
            name, data = line.split(':', 1)
            if name.strip() == 'lo':
                continue
            v = data.split()
            rx += int(v[0]); tx += int(v[8])
    return rx, tx


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
    try:
        pnet = _net_bytes()
    except Exception:   # noqa: BLE001
        pnet = None
    while True:
        time.sleep(1)
        try:
            cur = _cpu_times()
            dt, di = cur[0] - prev[0], cur[1] - prev[1]
            prev = cur
            # ağ: saniyelik alınan / gönderilen bayt (anlık hız)
            rx_bps = tx_bps = None
            try:
                nnet = _net_bytes()
                if pnet:
                    rx_bps, tx_bps = max(0, nnet[0] - pnet[0]), max(0, nnet[1] - pnet[1])
                pnet = nnet
            except Exception:   # noqa: BLE001
                pass
            cpu = round(100 * (dt - di) / dt, 1) if dt > 0 else 0.0
            total, used = _ram()
            g, temp = gpu.sample()
            disk = shutil.disk_usage(config.DATA_DIR)
            point = {'t': int(time.time()), 'cpu': cpu, 'gpu': g, 'ram': round(100 * used / total, 1), 'rx': rx_bps, 'tx': tx_bps}
            with _lock:
                _history.append(point)
                hist = [p for p in _history if p.get('rx') is not None][-60:]
                _latest.update(cpu=cpu, gpu=g, gpu_temp=temp, gpu_name=gpu.name, ram_total=total, ram_used=used,
                               disk_total=disk.total, disk_used=disk.used, disk_free=disk.free,
                               net_rx_bps=rx_bps, net_tx_bps=tx_bps,
                               net_rx_avg=round(sum(p['rx'] for p in hist) / len(hist)) if hist else None,
                               net_tx_avg=round(sum(p['tx'] for p in hist) / len(hist)) if hist else None,
                               net_rx_total=nnet[0] if pnet else None, net_tx_total=nnet[1] if pnet else None)
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


# ---- Firmaya özel (süreç-bazlı) kaynak: paylaşımlı makinede firma YALNIZ kendi entegrasyon yükünü görür ----
FIRM_PATTERNS = ('app.camera_service', 'app.main', 'agent.service', 'agent.agent', 'app.pdks', 'app.mikro', 'app.nvr')


def _cmdline(pid):
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return f.read().replace(b'\x00', b' ').decode(errors='replace')
    except OSError:
        return ''


def _pstat_cpu(pid):
    try:
        with open(f'/proc/{pid}/stat') as f:
            p = f.read().rsplit(')', 1)[1].split()   # ')' sonrası alanlar (isimde boşluk olabilir)
        return int(p[11]) + int(p[12])               # utime + stime (')' sonrası 12.-13. alan)
    except (OSError, IndexError, ValueError):
        return None


def _rss_mb(pid):
    import os
    try:
        with open(f'/proc/{pid}/statm') as f:
            return int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE') / 1e6
    except (OSError, IndexError, ValueError):
        return 0.0


def _firm_pids():
    import os
    out = {}
    try:
        entries = os.listdir('/proc')
    except OSError:
        return out
    for d in entries:
        if not d.isdigit():
            continue
        cmd = _cmdline(d)
        hit = next((p for p in FIRM_PATTERNS if p in cmd), None)
        if hit:
            out[int(d)] = hit.split('.')[-1]
    return out


def _gpu_procs(gpu):
    """NVML: {pid: GPU_bellek_MB} + toplam GPU bellek MB (sürüm farkına dayanıklı)."""
    out, total_mb = {}, None
    if not getattr(gpu, 'lib', None):
        return out, total_mb
    try:
        class _Mem(ctypes.Structure):
            _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]
        m = _Mem()
        if gpu.lib.nvmlDeviceGetMemoryInfo(gpu.handle, ctypes.byref(m)) == 0:
            total_mb = m.total / 1e6
    except Exception:   # noqa: BLE001
        pass
    for ver, fields in (('_v3', [('pid', ctypes.c_uint), ('used', ctypes.c_ulonglong),
                                 ('gi', ctypes.c_uint), ('ci', ctypes.c_uint)]),
                        ('_v2', [('pid', ctypes.c_uint), ('used', ctypes.c_ulonglong),
                                 ('gi', ctypes.c_uint), ('ci', ctypes.c_uint)]),
                        ('', [('pid', ctypes.c_uint), ('used', ctypes.c_ulonglong)])):
        fn = getattr(gpu.lib, 'nvmlDeviceGetComputeRunningProcesses' + ver, None)
        if not fn:
            continue
        try:
            Proc = type('Proc', (ctypes.Structure,), {'_fields_': fields})
            cnt = ctypes.c_uint(0)
            fn(gpu.handle, ctypes.byref(cnt), None)
            n = max(cnt.value, 1) + 8
            arr = (Proc * n)()
            cnt = ctypes.c_uint(n)
            if fn(gpu.handle, ctypes.byref(cnt), arr) == 0:
                for i in range(min(cnt.value, n)):
                    out[arr[i].pid] = arr[i].used / 1e6
                return out, total_mb
        except Exception:   # noqa: BLE001
            continue
    return out, total_mb


def firm_load():
    """Firmanın entegrasyon süreçlerinin anlık kaynak kullanımı (CPU çekirdek-%, RAM MB, GPU bellek + GPU util).
    Paylaşımlı makinede diğer uygulamalar (ör. başka servisler) HARİÇ — yalnız HEPGO entegrasyon süreçleri."""
    import os
    ncpu = os.cpu_count() or 1
    pids = _firm_pids()
    t0 = {p: _pstat_cpu(p) for p in pids}
    s0 = _cpu_times()[0]
    time.sleep(0.4)
    s1 = _cpu_times()[0]
    dsys = max(1, s1 - s0)
    procs, cpu_sum, ram_sum = [], 0.0, 0.0
    for pid, name in pids.items():
        a, b = t0.get(pid), _pstat_cpu(pid)
        if a is None or b is None:
            continue
        cpu = round(100.0 * ncpu * (b - a) / dsys, 1)   # top tarzı: 100% = 1 çekirdek
        rss = round(_rss_mb(pid))
        cpu_sum += cpu
        ram_sum += rss
        procs.append({'pid': pid, 'name': name, 'cpu': cpu, 'ram_mb': rss})
    gpu = _Gpu()
    util, temp = gpu.sample()
    gmem, gtotal = _gpu_procs(gpu)
    gpu_mb = round(sum(v for p, v in gmem.items() if p in pids))
    return {'cpu': round(cpu_sum, 1), 'cpu_count': ncpu, 'ram_mb': round(ram_sum),
            'gpu_util': util, 'gpu_temp': temp, 'gpu_name': gpu.name,
            'gpu_mem_mb': gpu_mb, 'gpu_mem_total_mb': round(gtotal) if gtotal else None,
            'procs': sorted(procs, key=lambda x: -x['cpu'])[:8], 't': int(time.time())}
