"""Entegrasyon sağlık denetimi: ayarlı entegrasyonlar düzenli aralıkla denenir (integrations.test — "Bağlantıyı Test Et" ile
aynı deneme). Bir entegrasyon ancak son denemesi başarılıysa "Bağlı" görünür; ulaşılamıyorsa "Çevrimdışı" olur ve sistem
yöneticisinin bildirimlerine düşer (notifications: integrations-offline).

Aralık entegrasyon başına ayarlanır (varsayılan 5 dk, en az 30 sn): app_kv['integrations.intervals'].
Son durumlar app_kv['integrations.health']'te saklanır (yeniden başlatmada son bilinen durum gösterilir).
Yalnız gerçekten bir yere bağlanan entegrasyonlar denetlenir (CHECKED); diğerleri yalnız anahtar tutar.
"""
import json
import threading
import time

from . import config, db

CHECKED = ('ai', 'mikro', 'pdks', 'nvr', 'x', 'speech')
DEFAULT_INTERVAL = 300
MIN_INTERVAL = 30
MAX_INTERVAL = 86400
TICK = 10
HEALTH_KEY = 'integrations.health'
INTERVAL_KEY = 'integrations.intervals'

_lock = threading.Lock()


def _kv(conn, key):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (key,)).fetchone()
    try:
        return json.loads(row[0]) if row else {}
    except ValueError:
        return {}


def _put(conn, key, data):
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (key, json.dumps(data)))
    conn.commit()


def intervals(conn):
    data = _kv(conn, INTERVAL_KEY)
    return {g: int(data.get(g) or DEFAULT_INTERVAL) for g in CHECKED}


def set_interval(conn, group, seconds):
    if group not in CHECKED:
        raise KeyError(group)
    seconds = int(seconds)
    if not MIN_INTERVAL <= seconds <= MAX_INTERVAL:
        raise ValueError(f'Kontrol aralığı {MIN_INTERVAL} sn ile {MAX_INTERVAL // 3600} saat arasında olmalı')
    with _lock:
        data = _kv(conn, INTERVAL_KEY)
        data[group] = seconds
        _put(conn, INTERVAL_KEY, data)


def states(conn):
    return _kv(conn, HEALTH_KEY)


HISTORY_LEN = 60   # son N denetim (grafik + çalışma süresi için)


def record(conn, group, ok, message, latency_ms=None):
    """Bir denemenin sonucunu kaydeder. Ek: art arda hata sayısı (fails), yanıt süresi (latency_ms) ve
    son HISTORY_LEN denetimin geçmişi (history: [checked_at, ok(0/1), latency_ms]) — detaylı durum + grafik için."""
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    ok = bool(ok)
    lat = int(latency_ms) if latency_ms is not None else None
    with _lock:
        data = _kv(conn, HEALTH_KEY)
        prev = data.get(group) or {}
        fails = 0 if ok else int(prev.get('fails') or 0) + 1
        since = prev.get('since') if prev.get('ok') == ok and prev.get('since') else now
        hist = list(prev.get('history') or [])
        hist.append([now, 1 if ok else 0, lat])
        hist = hist[-HISTORY_LEN:]
        data[group] = {'ok': ok, 'message': (message or '')[:300], 'checked_at': now,
                       'since': since, 'fails': fails, 'latency_ms': lat, 'history': hist}
        _put(conn, HEALTH_KEY, data)
    return data[group]


def forget(conn, group):
    """Ayarı kaldırılan entegrasyonun eski durumu silinir (ayarlanmadı → çevrimdışı uyarısı vermesin)."""
    with _lock:
        data = _kv(conn, HEALTH_KEY)
        if data.pop(group, None) is not None:
            _put(conn, HEALTH_KEY, data)


def _configured(conn):
    from . import integrations
    return {g['key'] for g in integrations.view(conn, health=False) if g['configured']}


def check(conn, group):
    from . import integrations
    t0 = time.monotonic()
    try:
        ok, message = integrations.test(group)
    except Exception as e:   # noqa: BLE001 — denetim hiçbir zaman çökmez; hata çevrimdışı sayılır
        ok, message = False, f'Denetim hatası: {str(e)[:150] or type(e).__name__}'
    latency = int((time.monotonic() - t0) * 1000)
    return record(conn, group, ok, message, latency_ms=latency)


def check_due(conn, now=None):
    """Zamanı gelen (ayarlı ve denetlenen) entegrasyonları dener. Döner: denenen gruplar."""
    now = now or time.time()
    conf, iv, st = _configured(conn), intervals(conn), states(conn)
    for g in [g for g in list(st) if g not in conf]:
        forget(conn, g)
    done = []
    for g in CHECKED:
        if g not in conf:
            continue
        last = (st.get(g) or {}).get('checked_at')
        try:
            age = now - time.mktime(time.strptime(last, '%Y-%m-%dT%H:%M:%S')) if last else None
        except ValueError:
            age = None
        if age is None or age >= iv[g]:
            check(conn, g)
            done.append(g)
    return done


def offline(conn):
    """Ayarlı ama son denemesi başarısız entegrasyonlar: [(grup, başlık, mesaj, since)]."""
    from . import integrations
    st = states(conn)
    return [(g['key'], g['title'], st[g['key']]['message'], st[g['key']]['since'])
            for g in integrations.view(conn, health=False)
            if g['configured'] and g['key'] in CHECKED and g['key'] in st and not st[g['key']]['ok']]


def _loop():
    time.sleep(20)   # açılışta servisler otursun
    while True:
        try:
            with db.connect() as conn:
                check_due(conn)
        except Exception:   # noqa: BLE001
            pass
        time.sleep(TICK)


_started = False


def start():
    global _started
    if not _started and config.PRINTER_POLL_ENABLED:   # testlerde (CAYMAZ_PRINTER_POLL=0) arka plan denetimi yok
        _started = True
        threading.Thread(target=_loop, daemon=True, name='integration-health').start()
