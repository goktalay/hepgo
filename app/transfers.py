"""Canlı dosya aktarım (yükleme / indirme) kaydı — süreç içi, bellekte.

Her tenant (caymaz / turkbey / merkez) kendi işlemiyle çalıştığından bu kayıt TENANT KAPSAMLIDIR:
yalnızca bu uygulama işleminin gördüğü aktif aktarımları izler (dağıtık / çok işlemli kurulumda her
işlem kendi aktarımlarını görür). MASTER "Transfer İzleme" panosu bu kaydı okur ve süren bir
YÜKLEMEYİ durdurabilir; indirmeler durdurulamaz (yalnızca izlenir).

Güncellemeler hem async işleyicilerden (parça parça yükleme, indirme ara katmanı) hem de iş parçacığı
havuzundan gelebildiğinden tek bir kilit (threading.Lock) ile korunur. Kayıt bellekte küçük tutulur:
biten aktarımlar birkaç saniye sonra düşer, grafik için yalnızca son ~60 saniyenin bayt/s kovaları saklanır.
"""
import secrets
import threading
import time

HIST_SECONDS = 60      # grafik için saklanan saniye (bayt/s kovası) sayısı
EXPIRE_AFTER = 8.0     # biten aktarım bu kadar saniye sonra listeden düşer
MAX_ENTRIES = 1000     # bellek güvenlik sınırı: en fazla bu kadar kayıt

_LOCK = threading.Lock()
_XFERS = {}            # id -> aktarım kaydı (sözlük)
_BUCKETS = {}          # int(saniye) -> [up_bytes, down_bytes]  (grafik throughput'u)


def _now():
    return time.time()


def _bucket(direction, delta):
    """O anki saniye kovasına 'delta' bayt ekler (grafik için bayt/s). _LOCK tutulurken çağrılır."""
    if delta <= 0:
        return
    sec = int(_now())
    b = _BUCKETS.get(sec)
    if b is None:
        b = _BUCKETS[sec] = [0, 0]
        cut = sec - HIST_SECONDS - 2            # eski kovaları buda (bellek sınırı)
        for k in [k for k in _BUCKETS if k < cut]:
            _BUCKETS.pop(k, None)
    b[0 if direction == 'up' else 1] += delta


def register(direction, user_id, user_name, name, size, cancelable=True):
    """Yeni aktarımı kaydeder, kısa bir kimlik (id) döner. direction: 'up' | 'down'.
    cancelable=False: tek-istek (POST) yüklemeler gibi akış ortasında durdurulamayan aktarımlar."""
    direction = 'up' if direction == 'up' else 'down'
    tid = secrets.token_hex(5)
    now = _now()
    with _LOCK:
        if len(_XFERS) >= MAX_ENTRIES:   # dolduysa en eski bitmişleri at
            done_ids = sorted((k for k, v in _XFERS.items() if v['finished_at']),
                              key=lambda k: _XFERS[k]['finished_at'])
            for k in done_ids[:len(_XFERS) - MAX_ENTRIES + 1]:
                _XFERS.pop(k, None)
        _XFERS[tid] = {'id': tid, 'dir': direction, 'user_id': user_id, 'user': (user_name or '—')[:80],
                       'name': (name or '')[:200], 'size': max(0, int(size or 0)), 'done': 0, 'rate': 0.0,
                       'started': now, 'updated': now, 'finished_at': None, 'canceled': False,
                       'cancelable': bool(cancelable) and direction == 'up',
                       '_last_done': 0, '_last_t': now}
    return tid


def update(tid, done_bytes):
    """Yükleme ilerlemesini (toplam alınan bayt) günceller; hızı delta/zaman'dan yumuşatarak hesaplar."""
    now = _now()
    with _LOCK:
        e = _XFERS.get(tid)
        if not e or e['finished_at']:
            return
        done_bytes = max(0, int(done_bytes))
        delta = done_bytes - e['_last_done']
        dt = now - e['_last_t']
        if delta > 0:
            _bucket(e['dir'], delta)
        if dt > 0 and delta >= 0:
            inst = delta / dt
            e['rate'] = inst if e['rate'] <= 0 else e['rate'] * 0.6 + inst * 0.4   # yumuşatma (EMA)
        e['_last_done'] = done_bytes
        e['_last_t'] = now
        e['done'] = done_bytes
        e['updated'] = now


def finish(tid):
    """Aktarımı tamamlandı olarak işaretler. İndirmelerde (kaba izleme) kalan baytı tek seferde
    kovaya ekler ve ortalama hızı (boyut / süre) hesaplar."""
    now = _now()
    with _LOCK:
        e = _XFERS.get(tid)
        if not e or e['finished_at']:
            return
        e['finished_at'] = now
        if e['dir'] == 'down':
            remaining = (e['size'] or 0) - e['_last_done']
            if remaining > 0:
                _bucket('down', remaining)
                e['done'] = e['size']
            dur = max(0.001, now - e['started'])
            if e['size']:
                e['rate'] = e['size'] / dur
        else:
            if e['size'] and e['done'] < e['size'] and not e['canceled']:
                e['done'] = e['size']
            e['rate'] = 0.0


def cancel(tid):
    """Durdurma bayrağını koyar. Dönen değer: durdurmanın ETKİLİ olup olamayacağı
    (yalnızca süren, durdurulabilir bir yükleme için True)."""
    with _LOCK:
        e = _XFERS.get(tid)
        if not e:
            return False
        e['canceled'] = True
        return bool(e['cancelable'] and e['finished_at'] is None)


def is_canceled(tid):
    with _LOCK:
        e = _XFERS.get(tid)
        return bool(e and e['canceled'])


def snapshot():
    """Panoya veri: aktif/biten aktarımlar, son ~60 sn throughput grafiği ve toplamlar."""
    now = _now()
    with _LOCK:
        for k in [k for k, v in _XFERS.items() if v['finished_at'] and now - v['finished_at'] > EXPIRE_AFTER]:
            _XFERS.pop(k, None)   # süresi dolan bitmişleri temizle
        active, up_bps, down_bps, count = [], 0.0, 0.0, 0
        for e in sorted(_XFERS.values(), key=lambda x: x['started']):
            live = e['finished_at'] is None
            size = e['size'] or 0
            pct = min(100.0, round(100 * e['done'] / size, 1)) if size else (0.0 if live else 100.0)
            rate = e['rate'] if live else 0.0
            eta = int((size - e['done']) / rate) if (live and rate > 0 and size > e['done']) else None
            if live:
                count += 1
                if e['dir'] == 'up':
                    up_bps += rate
                else:
                    down_bps += rate
            active.append({'id': e['id'], 'dir': e['dir'], 'user': e['user'], 'name': e['name'],
                           'size': size, 'done': e['done'], 'pct': pct, 'rate': round(rate),
                           'eta': eta, 'started': e['started'], 'done_state': not live,
                           'canceled': e['canceled'], 'cancelable': e['cancelable'] and live})
        base = int(now)
        up_hist = [(_BUCKETS.get(base - i) or (0, 0))[0] for i in range(HIST_SECONDS - 1, -1, -1)]
        down_hist = [(_BUCKETS.get(base - i) or (0, 0))[1] for i in range(HIST_SECONDS - 1, -1, -1)]
    return {'active': active, 'hist': {'up': up_hist, 'down': down_hist},
            'totals': {'up_bps': round(up_bps), 'down_bps': round(down_bps), 'count': count}}
