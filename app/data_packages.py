"""Dron Yönetimi › Veri Paketleri: uydu / ücretli hat veri paketleri ve tüketim (ör. Certus 100 Aviation).

Uçuş bağlantısı (field_flights.link) package_id + sat_line ile pakete bağlanır:
- sat_line 'kopru_sunucu': köprü dronun üstünde (ör. Jetson), uydu hattı köprü ↔ sunucu. Sunucu, köprünün telemetri ve görüntü
  WebSocket'lerinde giden / gelen her çerçeveyi sayar (drone_hub, drone_video → count()).
- sat_line 'dron_kopru': köprü yerde, dron TCP/UDP ile uydu üzerinden köprüye bağlı. Köprü kendi MAVLink hattını sayıp
  {t:'usage', rx, tx} ile bildirir (köprü 'veri_sayaci' yeteneği).
Sayılan baytlar bellekte biriktirilir, flush() ile data_usage'a (paket × uçuş × hat × gün) eklenir ve paketin GEÇERLİ döneminden düşer.
Ölçüm yaklaşık: çerçeve başına TCP/IP + TLS başlığı tahmini eklenir (uydu sağlayıcısı IP baytlarını ücretlendirir).
"""
import calendar
import json
import threading
from datetime import date

from . import db

PERIODS = {'AYLIK': 1, '3_AYLIK': 3, '6_AYLIK': 6, 'YILLIK': 12}
PERIOD_TEXT = {'AYLIK': 'Aylık', '3_AYLIK': '3 aylık', '6_AYLIK': '6 aylık', 'YILLIK': 'Yıllık'}
LINES = {'kopru_sunucu': 'Köprü ↔ sunucu (köprü dronda)', 'dron_kopru': 'Dron ↔ köprü (köprü yerde)'}
WS_OVERHEAD = 66        # WebSocket çerçevesi başına tahmini TCP/IP (40) + TLS kaydı (~26) baytı
OPEN_TASK = ('BASLANGIC', 'GOREVDE')
MB = 1024 * 1024

_acc = {}               # (bridge_id, line) → bayt (henüz yazılmamış)
_lock = threading.Lock()


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def current_period(pkg, today=None):
    """Geçerli dönem (başlangıç, bitiş[hariç]) — ISO metin. Otomatik yenilemede başlangıçtan itibaren dönem aralıklarıyla döner;
    yenilemesiz pakette tek dönem (bitmişse o dönem döner, durum 'sure_doldu')."""
    today = today or date.today()
    start = date.fromisoformat(pkg['start_date'][:10])
    months = PERIODS.get(pkg['period'], 1)
    if pkg['auto_renew'] and today >= start:
        k = ((today.year - start.year) * 12 + today.month - start.month) // months
        ps = add_months(start, k * months)
        if ps > today:
            k -= 1
            ps = add_months(start, k * months)
        while add_months(ps, months) <= today:
            ps = add_months(ps, months)
        return ps.isoformat(), add_months(ps, months).isoformat()
    return start.isoformat(), add_months(start, months).isoformat()


def used_bytes(conn, pkg_id, ps, pe):
    r = conn.execute('SELECT COALESCE(SUM(bytes), 0) FROM data_usage WHERE package_id = ? AND day >= ? AND day < ?', (pkg_id, ps, pe)).fetchone()
    return int(r[0] or 0)


def summary(conn, pkg, today=None):
    """Paket kartı: dönem, kullanılan / kalan MB, yüzde, kalan gün, aşım ve maliyeti, durum."""
    today = today or date.today()
    ps, pe = current_period(pkg, today)
    used = used_bytes(conn, pkg['id'], ps, pe) / MB
    quota = float(pkg['quota_mb'] or 0)
    over = max(0.0, used - quota)
    if not pkg['active']:
        status = 'pasif'
    elif today < date.fromisoformat(ps):
        status = 'baslamadi'
    elif today >= date.fromisoformat(pe):
        status = 'sure_doldu'
    elif used >= quota:
        status = 'bitti'
    else:
        status = 'aktif'
    return {**pkg, 'period_text': PERIOD_TEXT.get(pkg['period'], pkg['period']), 'period_start': ps, 'period_end': pe,
            'used_mb': round(used, 3), 'remaining_mb': round(max(0.0, quota - used), 3), 'pct': round(100 * used / quota, 1) if quota else None,
            'days_left': max(0, (date.fromisoformat(pe) - today).days), 'over_mb': round(over, 3),
            'over_cost': round(over * float(pkg['overage_per_mb'] or 0), 2) if over and pkg['overage_per_mb'] else 0.0, 'status': status}


# ---------------- ölçüm ----------------
def count(bridge_id, line, nbytes, frames=1):
    """Köprü hattında giden / gelen bayt (+ çerçeve başına başlık tahmini). Paket bağlı uçuş yoksa flush'ta atılır."""
    if not bridge_id or nbytes <= 0:
        return
    with _lock:
        k = (int(bridge_id), line)
        _acc[k] = _acc.get(k, 0) + int(nbytes) + WS_OVERHEAD * frames * (line == 'kopru_sunucu')


def _flights_for(conn, bridge_id, line):
    """Bu köprüyü kullanan, AÇIK görevdeki, pakete bağlı ve uydu hattı bu olan uçuşlar (fiziksel hat ortak: ilki sayılır)."""
    out = []
    for fid, tid, txt in conn.execute('''SELECT f.id, f.task_id, f.link FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                                         WHERE f.bridge_id = ? AND t.status IN (?, ?) AND f.link IS NOT NULL ORDER BY f.id''',
                                      (bridge_id, *OPEN_TASK)):
        try:
            lk = json.loads(txt) or {}
        except ValueError:
            continue
        if lk.get('package_id') and lk.get('sat_line', 'kopru_sunucu') == line:
            out.append((fid, tid, int(lk['package_id'])))
    return out


def flush(conn=None):
    """Biriken sayaçları data_usage'a yazar (günlük satıra ekler). Döner: yazılan bayt."""
    with _lock:
        acc = dict(_acc)
        _acc.clear()
    if not acc:
        return 0
    own = conn is None
    conn = conn or db.connect()
    total, day, now = 0, date.today().isoformat(), db.now()
    try:
        for (bid, line), n in acc.items():
            fl = _flights_for(conn, bid, line)
            if not fl:
                continue
            fid, tid, pid = fl[0]
            if not conn.execute('SELECT 1 FROM data_packages WHERE id = ?', (pid,)).fetchone():
                continue
            conn.execute('''INSERT INTO data_usage (package_id, flight_id, task_id, line, day, bytes, updated_at) VALUES (?,?,?,?,?,?,?)
                            ON CONFLICT (package_id, flight_id, line, day) DO UPDATE SET bytes = bytes + excluded.bytes,
                            updated_at = excluded.updated_at''', (pid, fid, tid, line, day, n, now))
            total += n
        conn.commit()
    finally:
        if own:
            conn.close()
    return total


def usage_detail(conn, pkg):
    """Geçerli dönemde günlük ve uçuş bazında tüketim (MB)."""
    ps, pe = current_period(pkg)
    days = [{'day': d, 'mb': round(b / MB, 3)} for d, b in conn.execute(
        'SELECT day, SUM(bytes) FROM data_usage WHERE package_id = ? AND day >= ? AND day < ? GROUP BY day ORDER BY day', (pkg['id'], ps, pe))]
    flights = [{'flight_id': r[0], 'task_code': r[1], 'label': r[2], 'line': r[3], 'line_text': LINES.get(r[3], r[3]), 'mb': round(r[4] / MB, 3),
                'first': r[5], 'last': r[6]} for r in conn.execute(
        '''SELECT u.flight_id, t.code, COALESCE(dd.code, dd.name, o.code, '#' || u.flight_id), u.line, SUM(u.bytes), MIN(u.day), MAX(u.day)
           FROM data_usage u LEFT JOIN field_flights f ON f.id = u.flight_id LEFT JOIN field_tasks t ON t.id = u.task_id
           LEFT JOIN drone_drones dd ON dd.id = f.drone_id LEFT JOIN orders o ON o.id = f.order_id
           WHERE u.package_id = ? AND u.day >= ? AND u.day < ? GROUP BY u.flight_id, u.line ORDER BY SUM(u.bytes) DESC''', (pkg['id'], ps, pe))]
    return {'period_start': ps, 'period_end': pe, 'days': days, 'flights': flights}
