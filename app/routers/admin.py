"""Yönetim: yalnızca Sistem Yöneticisinin gördüğü canlı durum paneli (5 sn'de bir yenilenir)."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from .. import auth, db

router = APIRouter(prefix='/api/admin')
admin_user = auth.require_module('admin')

ONLINE_WINDOW = timedelta(minutes=2)


@router.get('/dashboard')
def dashboard(user=Depends(admin_user), conn=db.DB):
    now = datetime.now()
    today = now.date().isoformat()
    cutoff = (now - ONLINE_WINDOW).isoformat(timespec='seconds')

    online = db.rows(conn.execute(
        '''SELECT id, username, full_name, photo, last_seen FROM users
           WHERE active = 1 AND last_seen >= ? AND EXISTS (
               SELECT 1 FROM sessions s WHERE s.user_id = users.id AND s.expires_at > ?)
           ORDER BY last_seen DESC''', (cutoff, now.isoformat(timespec='seconds'))))
    for u in online:
        u['roles'] = auth.user_roles(conn, u['id'])
        u['seconds_ago'] = int((now - datetime.fromisoformat(u['last_seen'])).total_seconds())

    printers = db.rows(conn.execute(
        '''SELECT p.id, p.name, p.ip, p.live_state, p.live_progress, p.live_file, p.last_seen,
                  op.part_id AS current_part, o.code AS current_order
           FROM printers p
           LEFT JOIN order_parts op ON op.id = p.current_part_id
           LEFT JOIN orders o ON o.id = op.order_id
           ORDER BY p.name'''))

    # Yazıcıdaki (üretimdeki) parçalar, ürün tipine göre
    printing = db.rows(conn.execute(
        '''SELECT op.part_id, op.started_at, o.id AS order_id, o.code AS order_code, o.product_id,
                  p.name AS printer, p.live_state, p.live_progress
           FROM order_parts op
           JOIN orders o ON o.id = op.order_id
           LEFT JOIN printers p ON p.id = op.printer_id
           WHERE op.state = 'URETIMDE' ORDER BY op.started_at'''))
    for r in printing:
        live = r['live_state'] == 'YAZDIRIYOR' and r['live_progress'] is not None
        r['remaining'] = round(100 - r['live_progress']) if live else None
        r['elapsed_seconds'] = int((now - datetime.fromisoformat(r['started_at'])).total_seconds()) if r['started_at'] else None

    # Üretimdeki ürün tipleri: açık siparişi ya da yazıcıda parçası olan ürünler; yoksa ilk aktif ürün
    products = db.rows(conn.execute(
        '''SELECT p.id, p.name, p.serial, p.code,
                  (SELECT COUNT(*) FROM orders o WHERE o.product_id = p.id AND o.status NOT IN ('SIPARIS', 'TAMAMLANDI', 'HURDA')) AS open_orders
           FROM products p
           WHERE EXISTS (SELECT 1 FROM orders o WHERE o.product_id = p.id AND o.status NOT IN ('SIPARIS', 'TAMAMLANDI', 'HURDA'))
              OR p.id IN (SELECT o.product_id FROM order_parts op JOIN orders o ON o.id = op.order_id WHERE op.state = 'URETIMDE')
           ORDER BY p.id'''))
    if not products:
        products = db.rows(conn.execute(
            'SELECT id, name, serial, code, 0 AS open_orders FROM products WHERE active = 1 ORDER BY id LIMIT 1'))
    for p in products:
        p['printing'] = [r for r in printing if r['product_id'] == p['id']]

    count = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]
    # Yazıcının kendi bildirdiği duruma göre: yazdırmıyor (hazır ya da baskısı bitmiş) ve çevrimiçi
    not_printing = ('HAZIR', 'TAMAMLANDI')
    really_idle = [pr for pr in printers if pr['live_state'] in not_printing and not pr['current_part']]
    stale = [pr for pr in printers if pr['live_state'] in not_printing and pr['current_part']]
    # Tersi: sistemde yazıcıya atanmış iş yok ama yazıcı baskı yapıyor
    outside = [pr for pr in printers if pr['live_state'] == 'YAZDIRIYOR' and not pr['current_part']]
    for pr in printers:
        pr['stale'] = pr in stale
        pr['outside'] = pr in outside
    states = {}
    for pr in printers:
        states[pr['live_state'] or 'BILINMIYOR'] = states.get(pr['live_state'] or 'BILINMIYOR', 0) + 1
    summary = {
        'online_users': len(online),
        'printers_total': len(printers),
        'printers_printing': states.get('YAZDIRIYOR', 0),
        'printers_idle': states.get('HAZIR', 0) + states.get('TAMAMLANDI', 0),
        'printers_offline': states.get('CEVRIMDISI', 0) + states.get('BILINMIYOR', 0),
        'printers_problem': states.get('HATA', 0) + states.get('DURAKLADI', 0),
        'printers_really_idle': len(really_idle),
        'printers_stale': len(stale),
        'stale_printers': [{'name': pr['name'], 'order': pr['current_order'], 'part': pr['current_part']} for pr in stale],
        'printing_outside': len(outside),
        'outside_printers': [{'name': pr['name'], 'file': pr['live_file']} for pr in outside],
        'parts_printing': len(printing),
        'parts_error': count("SELECT COUNT(*) FROM order_parts WHERE state = 'HATA'"),
        'parts_pending_approval': count("SELECT COUNT(*) FROM order_parts WHERE state = 'DEPO' AND approved_at IS NULL"),
        'orders_open': count("SELECT COUNT(*) FROM orders WHERE status NOT IN ('TAMAMLANDI', 'HURDA')"),
        'aircraft_ready': count('''SELECT COUNT(*) FROM orders o JOIN products p ON p.id = o.product_id
                                   WHERE o.status = 'TAMAMLANDI' AND p.type = 'MAMUL' AND NOT EXISTS (
                                   SELECT 1 FROM field_flights f JOIN field_tasks t ON t.id = f.task_id
                                   WHERE f.order_id = o.id AND t.status != 'IPTAL')'''),
        'field_active': count("SELECT COUNT(*) FROM field_tasks WHERE status = 'GOREVDE'"),
        'today_done': count("SELECT COUNT(*) FROM part_events WHERE event = 'URETIM_TAMAMLANDI' AND at >= ?", (today,)),
        'today_errors': count("SELECT COUNT(*) FROM part_events WHERE event = 'HATA' AND at >= ?", (today,)),
    }
    return {'at': now.isoformat(timespec='seconds'), 'summary': summary, 'online': online,
            'products': products, 'printers': printers}


# ---------- Sistem durumu (Yönetim → Sistem Durumu): sunucu, servisler, veritabanı, depolama, yedek, güvenlik, aktivite

import os  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

from .. import config, sysstat  # noqa: E402

SERVICES = [('caymaz', 'GÖKKUBBE web (caymaz.app)'), ('caymaz-turkbey', 'Türkbey web (turkbey.app)'), ('veilox', 'Veilox (veilox.app)'),
            ('caymaz-cameras', 'Kamera ve yüz tanıma (GÖKKUBBE)'), ('caymaz-turkbey-cameras', 'Kamera ve yüz tanıma (Türkbey)'),
            ('caymaz-backup.timer', 'Gece yedeği zamanlayıcısı (03:00)')]
_cache = {}
_STARTED = time.time()


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _run(cmd, timeout=4):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ''


def _dir_size(path):
    total = files = 0
    for root, _, names in os.walk(path):
        for n in names:
            try:
                total += os.lstat(os.path.join(root, n)).st_size
                files += 1
            except OSError:
                pass
    return total, files


def _storage():
    up = config.UPLOAD_DIR
    kinds = []
    if up.exists():
        for d in sorted(p for p in up.iterdir() if p.is_dir()):
            size, n = _dir_size(d)
            kinds.append({'kind': d.name, 'size': size, 'files': n})
    backups = config.DATA_DIR / 'backups'
    bsize, _ = _dir_size(backups) if backups.exists() else (0, 0)
    return {'uploads': kinds, 'uploads_total': sum(k['size'] for k in kinds), 'backups_size': bsize}


def _backups():
    nightly = config.DATA_DIR / 'backups' / 'nightly'
    dbs = sorted(nightly.glob('caymaz-*.db')) if nightly.exists() else []
    manual = sorted((config.DATA_DIR / 'backups').glob('caymaz-*.db'))
    last = dbs[-1] if dbs else None
    age_h = round((time.time() - last.stat().st_mtime) / 3600, 1) if last else None
    return {'nightly_count': len(dbs), 'nightly_last': last.name if last else None, 'nightly_age_h': age_h,
            'nightly_size': last.stat().st_size if last else None,
            'uploads_snapshots': len(list(nightly.glob('uploads-*'))) if nightly.exists() else 0,
            'manual_count': len(manual), 'manual_last': manual[-1].name if manual else None,
            'camera_key_backed': (nightly / 'camera.key').exists() or not (config.DATA_DIR / 'camera.key').exists(),
            'ok': age_h is not None and age_h < 30}


def _services():
    out = []
    for unit, label in SERVICES:
        state = _run(['systemctl', '--user', 'is-active', unit]) or 'bilinmiyor'
        since = _run(['systemctl', '--user', 'show', unit, '-p', 'ActiveEnterTimestamp', '--value'])
        out.append({'unit': unit, 'label': label, 'state': state, 'since': since})
    tunnel = _run(['docker', 'ps', '--filter', 'name=caymaz-tunnel', '--format', '{{.Status}}'])
    out.append({'unit': 'caymaz-tunnel', 'label': 'Cloudflare tüneli (internet erişimi)', 'state': 'active' if tunnel.startswith('Up') else (tunnel or 'bilinmiyor'),
                'since': tunnel})
    return out


def _errors():
    unit = 'caymaz-turkbey' if 'turkbey' in str(config.DATA_DIR) else 'caymaz'
    txt = _run(['journalctl', '--user', '-u', unit, '-u', f'{unit}-cameras', '-p', 'err', '--since', '24 hours ago', '-o', 'short-iso', '--no-pager'], 6)
    lines = [ln for ln in txt.splitlines() if ln and not ln.startswith('--')]
    return {'count': len(lines), 'last': lines[-12:]}


@router.get('/system')
def system(user=Depends(admin_user), conn=db.DB):
    now = datetime.now()
    day = now.date().isoformat()
    since24 = (now - timedelta(hours=24)).isoformat(timespec='seconds')
    since7 = (now - timedelta(days=7)).isoformat(timespec='seconds')
    count = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]
    snap = sysstat.snapshot()
    snap.pop('history', None)
    try:
        uptime_s = float(Path('/proc/uptime').read_text().split()[0])
        load = os.getloadavg()
    except Exception:
        uptime_s, load = None, (0, 0, 0)
    dbp = Path(config.DB_PATH)
    wal = Path(str(dbp) + '-wal')
    tables = ['users', 'orders', 'order_parts', 'part_events', 'printers', 'products', 'companies', 'company_people', 'documents',
              'field_tasks', 'flight_logs', 'guest_visits', 'vehicle_visits', 'cargo', 'cameras', 'face_groups', 'face_sightings',
              'audit_logs', 'login_logs']
    counts = {t: count(f'SELECT COUNT(*) FROM {t}') for t in tables}

    # Kullanıcı ve güvenlik
    users = db.rows(conn.execute('SELECT id, username, full_name, active, last_seen, created_at FROM users WHERE deleted_at IS NULL'))
    roles = Counter(r[0] for r in conn.execute('SELECT role FROM user_roles JOIN users u ON u.id = user_id WHERE u.active = 1 AND u.deleted_at IS NULL'))
    with_role = {r[0] for r in conn.execute('SELECT DISTINCT user_id FROM user_roles')}
    logged = {r[0] for r in conn.execute('SELECT DISTINCT user_id FROM login_logs WHERE success = 1 AND user_id IS NOT NULL')}
    fails = db.rows(conn.execute('SELECT username, ip, at FROM login_logs WHERE success = 0 AND at >= ? ORDER BY at DESC', (since24,)))
    by_name, by_ip = Counter(f['username'] for f in fails), Counter(f['ip'] or '—' for f in fails)
    suspicious = [{'what': 'Kullanıcı adı', 'key': k, 'n': v} for k, v in by_name.items() if v >= 5] + \
                 [{'what': 'IP adresi', 'key': k, 'n': v} for k, v in by_ip.items() if v >= 5]
    stale_cut = (now - timedelta(days=30)).isoformat(timespec='seconds')
    security = {
        'users_total': len(users), 'users_active': sum(u['active'] for u in users),
        'online': sum(1 for u in users if u['last_seen'] and u['last_seen'] >= (now - ONLINE_WINDOW).isoformat(timespec='seconds')),
        'sessions': count('SELECT COUNT(*) FROM sessions WHERE expires_at > ?', (now.isoformat(timespec='seconds'),)),
        'logins_today': count('SELECT COUNT(*) FROM login_logs WHERE success = 1 AND at >= ?', (day,)),
        'fails_24h': len(fails), 'suspicious': suspicious,
        'recent_fails': fails[:10],
        'no_role': [u['full_name'] for u in users if u['active'] and u['id'] not in with_role],
        'never_logged': [u['full_name'] for u in users if u['active'] and u['id'] not in logged],
        'inactive_30d': [u['full_name'] for u in users if u['active'] and u['id'] in logged and (u['last_seen'] or '') < stale_cut],
        'roles': roles.most_common(),
    }

    # Aktivite: son 14 gün işlem ve giriş; en aktif kullanıcılar; son işlemler; gün × saat
    d14 = [(now.date() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    acts = Counter(r[0] for r in conn.execute('SELECT substr(at, 1, 10) FROM audit_logs WHERE at >= ?', (d14[0],)))
    logins = Counter(r[0] for r in conn.execute('SELECT substr(at, 1, 10) FROM login_logs WHERE success = 1 AND at >= ?', (d14[0],)))
    top = db.rows(conn.execute('''SELECT u.full_name AS name, COUNT(*) AS n FROM audit_logs a JOIN users u ON u.id = a.user_id
                                  WHERE a.at >= ? GROUP BY a.user_id ORDER BY n DESC LIMIT 10''', (since7,)))
    recent = db.rows(conn.execute('''SELECT a.at, a.action, a.detail, u.full_name AS who FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id
                                     WHERE a.action NOT IN ('Rapor görüntüledi') ORDER BY a.id DESC LIMIT 25'''))
    grid = [[0] * 24 for _ in range(7)]
    for (at,) in conn.execute('SELECT at FROM audit_logs WHERE at >= ?', (since7,)):
        try:
            t = datetime.fromisoformat(at[:19])
            grid[t.weekday()][t.hour] += 1
        except ValueError:
            pass

    # Veri büyümesi: son 14 günde modüllere göre yeni kayıt
    growth_src = [('Sipariş', 'orders', 'created_at'), ('Parça olayı', 'part_events', 'at'), ('Evrak', 'documents', 'uploaded_at'),
                  ('Misafir', 'guest_visits', 'created_at'), ('Araç', 'vehicle_visits', 'entered_at'), ('Kargo', 'cargo', 'created_at'),
                  ('Yüz görülme', 'face_sightings', 'at'), ('Uçuş logu', 'flight_logs', 'uploaded_at')]
    growth = []
    for label, t, col in growth_src:
        c = Counter(r[0] for r in conn.execute(f'SELECT substr({col}, 1, 10) FROM {t} WHERE {col} >= ?', (d14[0],)))
        growth.append({'label': label, 'data': [c.get(d, 0) for d in d14]})

    # Entegrasyonlar
    from ..document_media import faces_available, whisper_available
    pr = Counter(r[0] or 'BILINMIYOR' for r in conn.execute('SELECT live_state FROM printers'))
    cams = Counter(r[0] or 'BEKLIYOR' for r in conn.execute('SELECT status FROM cameras WHERE active = 1'))
    integrations = [
        {'name': 'Yazıcılar (Moonraker / Creality)', 'ok': pr.get('CEVRIMDISI', 0) + pr.get('BILINMIYOR', 0) < max(1, sum(pr.values())) // 2,
         'detail': f'{sum(pr.values()) - pr.get("CEVRIMDISI", 0) - pr.get("BILINMIYOR", 0)} / {sum(pr.values())} çevrimiçi'},
        {'name': 'Kameralar (ONVIF)', 'ok': not cams or cams.get('CANLI', 0) == sum(cams.values()),
         'detail': f'{cams.get("CANLI", 0)} / {sum(cams.values())} canlı' if cams else 'kamera eklenmemiş'},
        {'name': 'Yüz tanıma modelleri (YuNet / SFace)', 'ok': faces_available(), 'detail': 'yüklü' if faces_available() else 'eksik'},
        {'name': 'Konuşma → metin (Whisper)', 'ok': whisper_available(), 'detail': 'yüklü' if whisper_available() else 'eksik'},
        {'name': 'Grafik kütüphanesi (Chart.js)', 'ok': (config.STATIC_DIR / 'vendor/chartjs/chart.umd.min.js').exists(), 'detail': 'yerel kopya'},
        {'name': '3B kütüphanesi (Three.js)', 'ok': (config.STATIC_DIR / 'vendor/three/three.module.min.js').exists(), 'detail': 'yerel kopya'},
    ]
    return {
        'at': now.isoformat(timespec='seconds'), 'company': config.COMPANY_NAME, 'host': socket.gethostname(),
        'server': {'uptime_s': uptime_s, 'app_uptime_s': time.time() - _STARTED, 'load': load, 'cpus': os.cpu_count(), **snap},
        'services': _cached('services', 30, _services),
        'database': {'size': dbp.stat().st_size if dbp.exists() else 0, 'wal': wal.stat().st_size if wal.exists() else 0, 'counts': counts},
        'storage': _cached('storage', 60, _storage), 'backups': _backups(), 'errors': _cached('errors', 60, _errors),
        'security': security,
        'activity': {'days': d14, 'actions': [acts.get(d, 0) for d in d14], 'logins': [logins.get(d, 0) for d in d14], 'top': top,
                     'recent': recent, 'heat': {'rows': ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'], 'cols': [f'{h:02d}' for h in range(24)], 'values': grid}},
        'growth': {'days': d14, 'series': growth},
        'integrations': integrations,
    }
