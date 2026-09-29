"""Üretim planlayıcı (Araçlar → Üretim Planlayıcı): seçilen mamulden N adet için hangi parçanın hangi yazıcıda,
hangi sırayla basılacağını hesaplar.

Yazıcı durumu: boştaki (HAZIR / TAMAMLANDI) yazıcı hemen, baskıdaki (YAZDIRIYOR / DURAKLADI) yazıcı kalan süre
sonunda kullanılabilir; çevrimdışı ya da hatalı yazıcı plana alınmaz. Kalan süre: yazıcının bastığı dosyanın parça
baskı süresi × (1 − ilerleme); ilerleme yoksa üretime başlama zamanından. İki baskı arasına tabla boşaltma / hazırlık
süresi (change_minutes) eklenir. assume_idle ile anlık durum yok sayılır: tüm yazıcılar boşmuş gibi planlanır.

Sıralama (liste çizelgeleme): her iş, en erken boşalacak yazıcıya verilir.
- aircraft (varsayılan): uçak uçak — önce 1. uçağın parçaları (uzun olan önce), sonra 2. uçağınki; ilk uçak en erken biter.
- fastest: tüm parçalar en uzundan kısaya — toplam bitiş en erken olur.
"""
from datetime import datetime, timedelta

from . import catalogs, db, semis

FREE = ('HAZIR', 'TAMAMLANDI')
BUSY = ('YAZDIRIYOR', 'DURAKLADI')
DEFAULT_MINUTES = 8 * 60   # baskı süresi bilinmeyen parça için varsayım (planda işaretlenir)


def _iso(t):
    return t.isoformat(timespec='minutes')


def printer_availability(conn, now, change_minutes, assume_idle=False):
    """[(yazıcı, kullanılabileceği an, meşguliyet bilgisi)] ve plana alınamayanlar.
    assume_idle: yazıcıların anlık durumu yok sayılır; sistemdeki tüm yazıcılar şu an boşmuş gibi plana alınır."""
    from .alerts import expected_files, norm_file
    files = expected_files(conn)
    by_file = {norm_file(f): pid for pid, f in files.items()}
    minutes = {pid: i['print_minutes'] for pid, i in semis.print_info(conn).items()}
    rows = db.rows(conn.execute(
        '''SELECT p.id, p.name, p.live_state, p.live_progress, p.live_file, p.live_since, p.current_part_id,
                  op.part_id, op.started_at, o.code AS order_code
           FROM printers p LEFT JOIN order_parts op ON op.id = p.current_part_id LEFT JOIN orders o ON o.id = op.order_id
           ORDER BY CAST(p.name AS INTEGER), p.name'''))
    usable, unusable = [], []
    for p in rows:
        state = p['live_state']
        if assume_idle:
            usable.append({**p, 'available_at': now, 'busy': None, 'note': None})
        elif state in FREE:
            usable.append({**p, 'available_at': now, 'busy': None,
                           'note': 'Tablada biten parça var; önce çıkarılmalı' if p['current_part_id'] else None})
        elif state in BUSY:
            part = p['part_id'] or by_file.get(norm_file(p['live_file']))
            total = minutes.get(part)
            if total and p['live_progress']:
                left = total * (1 - min(99.0, p['live_progress']) / 100)
            elif total and (p['started_at'] or p['live_since']):
                left = max(10, total - (now - datetime.fromisoformat(p['started_at'] or p['live_since'])).total_seconds() / 60)
            else:
                left = 60   # süresi bilinmeyen iş: 1 saat varsayılır
            until = now + timedelta(minutes=left)
            usable.append({**p, 'available_at': until + timedelta(minutes=change_minutes),
                           'busy': {'part': part, 'order': p['order_code'], 'recorded': bool(p['current_part_id']),
                                    'file': p['live_file'], 'until': until, 'estimated': not total}})
        else:
            unusable.append({'id': p['id'], 'name': p['name'], 'state': state or 'BILINMIYOR'})
    return usable, unusable


def plan(conn, product, quantity, mode='aircraft', change_minutes=15, now=None, assume_idle=False):
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    info = semis.print_info(conn)
    part_ids = catalogs.part_ids(product['schema'])
    known = sorted(m for m in (info.get(p, {}).get('print_minutes') for p in part_ids) if m)
    unknown = [p for p in part_ids if not info.get(p, {}).get('print_minutes')]
    fallback = known[len(known) // 2] if known else DEFAULT_MINUTES

    def job(n, pid):
        i = info.get(pid, {})
        return {'aircraft': n, 'part': pid, 'file': i.get('print_file'), 'minutes': i.get('print_minutes') or fallback,
                'estimated': not i.get('print_minutes')}

    jobs = [job(n, pid) for n in range(1, quantity + 1) for pid in part_ids]
    by_aircraft = sorted(jobs, key=lambda j: (j['aircraft'], -j['minutes'], j['part']))
    longest_first = sorted(jobs, key=lambda j: (-j['minutes'], j['aircraft'], j['part']))
    base, unusable = printer_availability(conn, now, change_minutes, assume_idle)

    def schedule(order):
        printers = [{**p, 'jobs': []} for p in base]
        if printers:
            for j in order:
                p = min(printers, key=lambda x: (x['available_at'], x['name']))
                start = p['available_at']
                end = start + timedelta(minutes=j['minutes'])
                p['jobs'].append({**j, 'start': _iso(start), 'end': _iso(end)})
                p['available_at'] = end + timedelta(minutes=change_minutes)
        return printers

    def finish(printers):
        return max((j['end'] for p in printers for j in p['jobs']), default='')

    printers = schedule(by_aircraft)
    if mode == 'fastest':   # en uzun iş önce genelde daha kısa sürer; hangisi erken bitiyorsa o
        alt = schedule(longest_first)
        if finish(alt) < finish(printers):
            printers = alt

    done = {}
    for p in printers:
        for j in p['jobs']:
            done[j['aircraft']] = max(done.get(j['aircraft'], ''), j['end'])
    first = [{'printer': p['name'], 'printer_id': p['id'], **p['jobs'][0]}
             for p in printers if p['jobs'] and p['jobs'][0]['start'] == _iso(now)]
    out_printers = [{
        'id': p['id'], 'name': p['name'], 'state': p['live_state'], 'note': p['note'] if 'note' in p else None,
        'busy': {**p['busy'], 'until': _iso(p['busy']['until'])} if p['busy'] else None,
        'jobs': p['jobs'],
    } for p in printers]
    return {
        'product': {'id': product['id'], 'name': product['name'], 'code': product['code']},
        'quantity': quantity, 'mode': mode, 'change_minutes': change_minutes, 'now': _iso(now), 'assume_idle': assume_idle,
        'printers': out_printers, 'unusable': unusable, 'first_loads': first,
        'aircraft_done': [{'aircraft': n, 'end': e} for n, e in sorted(done.items())],
        'end': max(done.values()) if done else None,
        'total_print_minutes': sum(j['minutes'] for j in jobs), 'jobs': len(jobs),
        'unknown_parts': unknown, 'fallback_minutes': fallback if unknown else None,
    }
