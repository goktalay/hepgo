import ipaddress
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, db, printer_driver, printer_layout

router = APIRouter(prefix='/api/printers')
printer_admin = auth.require_module('printers')


def _printer_reader(user=Depends(auth.current_user)):
    # Üretim ekranı yazıcı seçtirdiği için üretim kullanıcıları da listeyi okuyabilir.
    if not {'printers', 'production'} & set(user['modules']):
        raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
    return user


class PrinterIn(BaseModel):
    name: str
    ip: str
    mac: str = ''


class SlotIn(BaseModel):
    id: int
    side: str
    level: int
    slot: int


class LayoutIn(BaseModel):
    items: list[SlotIn]


def _validate(conn, body, pid=None):
    if not body.name.strip():
        raise HTTPException(400, 'Yazıcı adı zorunlu')
    try:
        ipaddress.IPv4Address(body.ip.strip())
    except ValueError:
        raise HTTPException(400, 'Geçersiz IP adresi')
    if conn.execute('SELECT 1 FROM printers WHERE ip = ? AND id IS NOT ?', (body.ip.strip(), pid)).fetchone():
        raise HTTPException(400, 'Bu IP adresi zaten kayıtlı')


@router.get('')
def list_printers(user=Depends(_printer_reader), conn=db.DB):
    # Ağda IP değişebildiğinden: çevrimdışı yazıcı varsa arka planda IP tazeleme taraması başlatılır (kalıcı donanım
    # kimliğiyle eşleştirme). Liste anında döner; değişen IP'ler bir sonraki tazelemede (birkaç saniye) yansır.
    printer_driver.trigger_reconcile()
    rows = db.rows(conn.execute(
        '''SELECT p.*, o.code AS current_order, op.part_id AS current_part, op.order_id AS current_order_id
           FROM printers p
           LEFT JOIN order_parts op ON op.id = p.current_part_id
           LEFT JOIN orders o ON o.id = op.order_id'''))
    rows.sort(key=lambda r: printer_layout.name_key(r['name']))   # önce numara, sonra metin (tüm ekranlar)
    # Sistemde siparişi olmayan baskı da tanınsın: yazıcıdaki dosya adından parça (ürünün baskı dosyası adıyla eşleşme)
    files = _file_parts(conn)
    for r in rows:
        r['file_part'] = match_file_part(r.get('live_file'), files) if r.get('live_file') else None
    return rows


def _norm(name, drop_suffix=False):
    import re
    s = (name or '').lower()
    s = re.sub(r'\.(gcode|bgcode|3mf)$', '', s)
    if drop_suffix:
        s = re.sub(r'[_\- ]*(abs|pla|petg|asa|tpu|pa|pc)[\s_-]*\d.*$', '', s)   # malzeme + süre eki
    return re.sub(r'[\s_\-]+', '', s)


_fp_cache = {'t': 0, 'v': ({}, {})}


def _file_parts(conn):
    """Baskı dosyası adı → parça kodu (tam ve süre eki atılmış iki eşleme); 60 sn önbellek."""
    import time
    if time.monotonic() - _fp_cache['t'] < 60:
        return _fp_cache['v']
    full, short = {}, {}
    for code, schema, pf, gf in conn.execute("SELECT code, schema, print_file, gcode_file FROM products WHERE active = 1 AND (print_file IS NOT NULL OR gcode_file IS NOT NULL)"):
        key = schema[len('part-'):] if (schema or '').startswith('part-') else code
        for n in (pf, (gf or '').rsplit('/', 1)[-1]):
            if n:
                full.setdefault(_norm(n), key)
                short.setdefault(_norm(n, True), key)
    _fp_cache.update(t=time.monotonic(), v=(full, short))
    return full, short


def match_file_part(live_file, files):
    full, short = files
    return full.get(_norm(live_file)) or short.get(_norm(live_file, True))


@router.put('/layout')
def save_layout(body: LayoutIn, user=Depends(printer_admin), conn=db.DB):
    """Yazıcı odası yerleşimi (3B görünüm): verilen yazıcıların taraf / kat / sıra bilgisi; bir yerde tek yazıcı olur."""
    ids = {r[0] for r in conn.execute('SELECT id FROM printers')}
    per_row = max(printer_layout.slots_per_row(len(ids)) + 10, len(ids))   # sıralama ekranında bir kata tüm yazıcılar konabilir
    seen = set()
    for it in body.items:
        key = (it.side, it.level, it.slot)
        if it.id not in ids or it.side not in ('L', 'R') or it.level not in (1, 2) or not 1 <= it.slot <= per_row:
            raise HTTPException(400, 'Geçersiz yerleşim')
        if key in seen:
            raise HTTPException(400, 'Aynı rafa iki yazıcı konamaz')
        seen.add(key)
    moved = {it.id for it in body.items}
    others = {tuple(r[1:]) for r in conn.execute('SELECT id, rack_side, rack_level, rack_slot FROM printers') if r[0] not in moved}
    if seen & others:
        raise HTTPException(400, 'Seçilen raf dolu')
    conn.executemany('UPDATE printers SET rack_side = NULL, rack_level = NULL, rack_slot = NULL WHERE id = ?', [(i,) for i in moved])
    conn.executemany('UPDATE printers SET rack_side = ?, rack_level = ?, rack_slot = ? WHERE id = ?',
                     [(it.side, it.level, it.slot, it.id) for it in body.items])
    db.audit(conn, user['id'], 'Yazıcı yerleşimini değiştirdi', 'printer', None, f'{len(body.items)} yazıcı')
    return {'ok': True}


def _mac(raw):
    """MAC'i normalize eder (AA:BB:CC:DD:EE:FF) ve ondan kalıcı kimliği türetir (K2Plus-EEFF). Boşsa (None, None)."""
    s = re.sub(r'[^0-9A-Fa-f]', '', raw or '').upper()
    if not s:
        return None, None
    if len(s) != 12:
        raise HTTPException(400, 'MAC adresi 12 onaltılık haneden oluşmalı (ör. FC:EE:28:0F:36:97)')
    mac = ':'.join(s[i:i + 2] for i in range(0, 12, 2))
    return mac, f'K2Plus-{s[-4:]}'


@router.post('')
def add_printer(body: PrinterIn, user=Depends(printer_admin), conn=db.DB):
    _validate(conn, body)
    mac, hw = _mac(body.mac)
    cur = conn.execute('INSERT INTO printers (name, ip, created_at, mac, hw_id) VALUES (?,?,?,?,?)',
                       (body.name.strip(), body.ip.strip(), db.now(), mac, hw))
    db.audit(conn, user['id'], 'Yazıcı ekledi', 'printer', cur.lastrowid, f'{body.name} ({body.ip})')
    printer_layout.assign_missing(conn)   # odada ilk boş rafa
    return {'id': cur.lastrowid}


@router.put('/{pid}')
def update_printer(pid: int, body: PrinterIn, user=Depends(printer_admin), conn=db.DB):
    if not conn.execute('SELECT 1 FROM printers WHERE id = ?', (pid,)).fetchone():
        raise HTTPException(404, 'Yazıcı bulunamadı')
    _validate(conn, body, pid)
    mac, hw = _mac(body.mac)
    conn.execute('UPDATE printers SET name = ?, ip = ?, mac = ?, hw_id = COALESCE(?, hw_id) WHERE id = ?',
                 (body.name.strip(), body.ip.strip(), mac, hw, pid))
    db.audit(conn, user['id'], 'Yazıcı düzenledi', 'printer', pid, f'{body.name} ({body.ip})')
    return {'ok': True}


@router.delete('/{pid}')
def delete_printer(pid: int, user=Depends(printer_admin), conn=db.DB):
    p = db.row(conn.execute('SELECT * FROM printers WHERE id = ?', (pid,)))
    if not p:
        raise HTTPException(404, 'Yazıcı bulunamadı')
    if p['current_part_id']:
        raise HTTPException(400, 'Üzerinde üretim olan yazıcı silinemez')
    conn.execute('DELETE FROM printers WHERE id = ?', (pid,))
    db.audit(conn, user['id'], 'Yazıcı sildi', 'printer', pid, f'{p["name"]} ({p["ip"]})')
    return {'ok': True}


@router.post('/refresh')
async def refresh(user=Depends(printer_admin)):
    await run_in_threadpool(printer_driver.poll_all)

    def write():
        with db.connect() as conn:
            db.audit(conn, user['id'], 'Yazıcı durumlarını elle yeniledi', 'printer')
    await run_in_threadpool(write)
    return {'ok': True}


@router.post('/refresh-names')
async def refresh_names(user=Depends(printer_admin)):
    """Yazıcıların adlarını cihazın kendi adıyla (Moonraker/Creality hostname) günceller. Değişenleri döner."""
    return await run_in_threadpool(_refresh_names, user)


def _refresh_names(user):
    """Yalnızca yazıcının ekranından girilen kullanıcı adını (Creality deviceName) sisteme çeker.
    Ağ adı (K2Plus-XXXX) kullanıcı adı olmadığından ASLA kullanılmaz; deviceName boşsa mevcut ad korunur."""
    from concurrent.futures import ThreadPoolExecutor
    with db.connect() as conn:
        printers = db.rows(conn.execute('SELECT id, name, ip FROM printers'))
    with ThreadPoolExecutor(max_workers=16) as pool:
        names = dict(zip([p['id'] for p in printers],
                         pool.map(lambda p: printer_driver.device_name(p['ip']), printers)))
    from collections import defaultdict
    changed, no_name = [], 0
    # Hedef ad: cihazdan okunan güncel ad (çevrimiçi) ya da mevcut ad (okunamayan). Aynı ada birden çok yazıcı düşerse
    # ADI CİHAZDAN OKUNAN (çevrimiçi) temiz kalır; çakışan diğer (çevrimdışı ya da fazladan) kayıt son IP baytıyla ayrılır.
    online = {p['id'] for p in printers if names.get(p['id'])}
    for p in printers:
        if not names.get(p['id']):
            no_name += 1
    desired = {p['id']: (names.get(p['id']) or p['name']) for p in printers}
    groups = defaultdict(list)
    for p in printers:
        groups[desired[p['id']]].append(p)
    final = {}
    for nm, grp in groups.items():
        if len(grp) == 1:
            final[grp[0]['id']] = nm
            continue
        on = [p for p in grp if p['id'] in online]                       # cihazdan ad okunanlar (çevrimiçi)
        inc_on = [p for p in on if p['name'] == nm]                       # adı zaten doğru olan çevrimiçi (öncelik)
        inc = [p for p in grp if p['name'] == nm]                         # adı tutan (çevrimdışı olabilir)
        if inc_on:
            winner = inc_on[0]['id']
        elif len(on) == 1:                                               # tek çevrimiçi cihaz: çevrimdışı eskiyi yener
            winner = on[0]['id']
        elif not on and len(inc) == 1:                                   # hiç çevrimiçi yok: adı tutan korur
            winner = inc[0]['id']
        else:
            winner = None
        for p in grp:
            final[p['id']] = nm if p['id'] == winner else f'{nm} ({p["ip"].rsplit(".", 1)[-1]})'
    with db.connect() as conn:
        for p in printers:
            name = final[p['id']]
            if name == p['name']:
                continue
            conn.execute('UPDATE printers SET name = ? WHERE id = ?', (name, p['id']))
            changed.append({'ip': p['ip'], 'old': p['name'], 'new': name})
        if changed:
            db.audit(conn, user['id'], 'Yazıcı adlarını cihazdan yeniledi', 'printer', None,
                     ', '.join(f'{c["old"]}→{c["new"]}' for c in changed[:20]))
    return {'changed': changed, 'no_name': no_name, 'total': len(printers)}


@router.post('/discover')
async def discover(user=Depends(printer_admin)):
    try:
        found = await run_in_threadpool(printer_driver.discover)
    except Exception as e:   # noqa: BLE001 — uzak modda ajan bağlı değil / eski ajan: anlaşılır mesaj
        msg = str(e)
        if 'ajan' in msg.lower() or 'agent' in msg.lower():
            raise HTTPException(503, 'Fabrikadaki ajana ulaşılamadı; yazıcı taraması yapılamadı. Ajanın çevrimiçi ve güncel olduğundan emin olun.') from e
        raise HTTPException(502, f'Yazıcı taraması başarısız: {msg}') from e
    return await run_in_threadpool(_add_discovered, found, user)


def _add_discovered(found, user):
    """Bulunan yazıcıları ekler. Kimlik olarak kalıcı donanım kimliği (Moonraker seri-adı) kullanılır: aynı cihaz
    IP değiştirmiş olsa bile ikinci kez eklenmez; yalnızca IP'si güncellenir. Kimliği okunamayan cihazlar IP'ye göre eklenir."""
    from concurrent.futures import ThreadPoolExecutor
    added, moved = [], []
    # Donanım kimliği (IP değişimini tanımak için) taramada geldiyse onu kullan (uzak modda ajan döner); yoksa yerelde oku
    hwids, missing = {}, []
    for ip, live in found:
        if isinstance(live, dict) and 'hw' in live:
            hwids[ip] = live['hw']
        else:
            missing.append(ip)
    if missing:
        with ThreadPoolExecutor(max_workers=24) as pool:
            hwids.update(zip(missing, pool.map(printer_driver.hardware_id, missing)))
    with db.connect() as conn:
        rows = db.rows(conn.execute('SELECT id, name, ip, hw_id, hw_alias FROM printers'))
        by_ip = {r['ip'] for r in rows}
        by_hw = {}
        for r in rows:
            for k in (r['hw_id'], r['hw_alias']):
                if k:
                    by_hw[k] = r
        count = conn.execute('SELECT COUNT(*) FROM printers').fetchone()[0]
        seen_hw = set()
        for ip, live in sorted(found, key=lambda f: ipaddress.IPv4Address(f[0])):
            hw = hwids.get(ip)
            if hw and hw in by_hw:            # aynı cihaz zaten kayıtlı: yalnızca IP güncellenir (DHCP değişimi)
                pr = by_hw[hw]
                if pr['ip'] != ip:
                    conn.execute('UPDATE printers SET ip = ? WHERE id = ?', (ip, pr['id']))
                    db.audit(conn, user['id'], 'Yazıcının IP adresini düzeltti (ağ taraması)', 'printer', pr['id'],
                             f"{pr.get('name') or pr['id']}: {pr['ip']} → {ip}")
                    moved.append({'id': pr['id'], 'name': pr.get('name'), 'old': pr['ip'], 'ip': ip})
                continue
            if hw and hw in seen_hw:           # aynı taramada aynı cihaz iki IP'de göründü: bir kez ekle
                continue
            if ip in by_ip:
                continue
            count += 1
            name = live.get('hostname') or f'K2 Plus {count:02d}'
            now = db.now()
            cur = conn.execute(
                '''INSERT INTO printers (name, ip, hw_id, model, auto_added, created_at, live_state, live_progress,
                   live_file, live_source, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (name, ip, hw, live['model'] or 'Creality K2 Plus', 1, now, live['state'], live['progress'], live['file'],
                 live['source'], now))
            if hw:
                seen_hw.add(hw)
                by_hw[hw] = {'id': cur.lastrowid, 'name': name, 'ip': ip, 'hw_id': hw}
            db.audit(conn, user['id'], 'Yazıcı otomatik ekledi', 'printer', cur.lastrowid, f'{name} ({ip})')
            added.append({'name': name, 'ip': ip})
        printer_layout.assign_missing(conn)
    return {'found': len(found), 'added': added, 'moved': moved}
