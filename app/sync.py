"""Entegrasyonların zamanlanmış (otomatik) senkronizasyonu — Mikro ERP, PDKS vb.

Sistem yöneticisi her entegrasyon için otomatik senkronizasyonu açıp kapatır ve aralığını (dakika) belirler
(Program Ayarları › Entegrasyonlar). Ayarlar app_kv['integration_sync'] içinde tutulur. Arka planda tek bir döngü
(main.py lifespan) her dakika bakar; açık ve zamanı gelen entegrasyonu kendi iş parçacığında çalıştırır (olay döngüsü
bloklanmaz). Tüm senkronizasyonlar tek yönlüdür: dış sistemden okunur, dış sisteme hiçbir şey yazılmaz.
"""
import asyncio
import json
import logging
import time

from . import db

log = logging.getLogger('caymaz.sync')
KV_KEY = 'integration_sync'
DEFAULTS = {'pdks': {'enabled': False, 'interval': 30}, 'mikro': {'enabled': False, 'interval': 60}}
MIN_INTERVAL = 5
_runtime = {}   # group -> {'running': bool, 'last_run': ts, 'last_ok': bool, 'last_msg': str}


def config(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KV_KEY,)).fetchone()
    try:
        saved = json.loads(row[0]) if row else {}
    except ValueError:
        saved = {}
    out = {}
    for g, d in DEFAULTS.items():
        s = saved.get(g) or {}
        out[g] = {'enabled': bool(s.get('enabled', d['enabled'])),
                  'interval': max(MIN_INTERVAL, int(s.get('interval', d['interval'])))}
    return out


def set_config(conn, group, enabled=None, interval=None):
    if group not in DEFAULTS:
        raise ValueError('Bilinmeyen entegrasyon')
    cfg = config(conn)
    if enabled is not None:
        cfg[group]['enabled'] = bool(enabled)
    if interval is not None:
        cfg[group]['interval'] = max(MIN_INTERVAL, int(interval))
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (KV_KEY, json.dumps(cfg)))
    return cfg


def status(conn):
    """Panel için: her entegrasyonun açık/kapalı, aralık ve son çalışma bilgisi."""
    cfg = config(conn)
    out = {}
    for g, c in cfg.items():
        rt = _runtime.get(g, {})
        out[g] = {**c, 'running': rt.get('running', False),
                  'last_run': rt.get('last_run'), 'last_ok': rt.get('last_ok'), 'last_msg': rt.get('last_msg')}
    return out


# ---------- Senkronizasyon işleri (group -> fonksiyon(conn) -> (ok, mesaj))
def _sync_pdks(conn):
    from . import pdks
    from .routers import hr
    if not pdks.configured():
        return False, 'PDKS bağlantısı tanımlı değil'
    people = pdks.fetch_personnel()
    hr.pdks_links(conn, people)   # yeni kartları personelle ad eşleştir
    from datetime import date, timedelta
    today = date.today()
    att = pdks.daily_attendance((today - timedelta(days=1)).isoformat(), today.isoformat())
    links = {r[0]: r[1] for r in conn.execute('SELECT kart_id, employee_id FROM pdks_links')}
    names = {e['id']: f"{e['first_name']} {e['last_name']}" for e in db.rows(conn.execute('SELECT id, first_name, last_name FROM employees'))}
    pby = {p['kart_id']: p for p in people}
    inside = []
    for card, byday in att.items():
        v = byday.get(today.isoformat())
        if v:
            inside.append({'name': names.get(links.get(card)) or (f"{pby[card]['ad']} {pby[card]['soyad']}".strip() if card in pby else f'Kart {card}'),
                           'giris': v['giris'], 'cikis': v['cikis']})
    inside.sort(key=lambda x: x['giris'])
    snap = {'at': db.now(), 'count': len(inside), 'people': inside}
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', ('pdks.today', json.dumps(snap, ensure_ascii=False)))
    return True, f'{len(people)} personel, bugün {len(inside)} giriş'


def _sync_mikro(conn):
    """Güvenli otomatik aktarım: yalnızca henüz bağlanmamış YENİ cari ve stok kartları (ek niteliğinde).
    Faturalar finansal olduğundan otomatik aktarılmaz; Satış / Satın Alma’dan elle aktarılır."""
    from . import mikro
    from .routers import mikro as mikro_routes
    if not mikro.configured():
        return False, 'Mikro bağlantısı tanımlı değil'
    n_cari = mikro_routes.auto_import_new(conn, 'cari')
    return True, f'{n_cari} yeni cari aktarıldı (stok ve faturalar elle aktarılır)'


JOBS = {'pdks': _sync_pdks, 'mikro': _sync_mikro}


def run(group):
    """Bir entegrasyonu hemen senkronize et (iş parçacığından çağrılır). (ok, mesaj)."""
    rt = _runtime.setdefault(group, {})
    if rt.get('running'):
        return False, 'Zaten çalışıyor'
    rt['running'] = True
    try:
        with db.connect() as conn:
            ok, msg = JOBS[group](conn)
    except Exception as e:   # noqa: BLE001
        ok, msg = False, f'{type(e).__name__}: {str(e)[:160]}'
        log.warning('sync %s hata: %s', group, e)
    rt.update(running=False, last_run=db.now(), last_ok=ok, last_msg=msg)
    return ok, msg


async def loop(interval=60):
    """Arka plan döngüsü: açık ve zamanı gelen entegrasyonları çalıştırır."""
    await asyncio.sleep(25)
    last = {}
    while True:
        try:
            with db.connect() as conn:
                cfg = config(conn)
            now = time.monotonic()
            for g, c in cfg.items():
                if not c['enabled']:
                    continue
                if now - last.get(g, 0) >= c['interval'] * 60:
                    last[g] = now
                    await asyncio.to_thread(run, g)
        except Exception as e:   # noqa: BLE001
            log.warning('sync döngüsü: %s', e)
        await asyncio.sleep(interval)
