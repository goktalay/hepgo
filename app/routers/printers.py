import ipaddress

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, config, db, printer_driver, printer_identity, printer_layout

router = APIRouter(prefix='/api/printers')
printer_admin = auth.require_module('printers')


def _printer_reader(user=Depends(auth.current_user)):
    # Üretim ekranı yazıcı seçtirdiği için üretim kullanıcıları da listeyi okuyabilir.
    if not {'printers', 'production'} & set(user['modules']):
        raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
    return user


class PrinterIn(BaseModel):
    name: str
    ip: str = ''     # son görülen IP (isteğe bağlı; gönderimde MAC ile doğrulanır / bulunur)
    mac: str = ''    # benzersiz kimlik


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
    ip = body.ip.strip()
    if ip:
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            raise HTTPException(400, 'Geçersiz IP adresi')
        other = db.row(conn.execute('SELECT name FROM printers WHERE ip = ? AND id IS NOT ?', (ip, pid)))
        if other:
            raise HTTPException(400, f'Bu IP adresi şu an “{other["name"]}” yazıcısında görülüyor')
    mac = _mac(body.mac)
    if mac:
        other = db.row(conn.execute('SELECT name FROM printers WHERE mac = ? AND id IS NOT ?', (mac, pid)))
        if other:
            raise HTTPException(409, f'Bu MAC adresi zaten “{other["name"]}” yazıcısında kayıtlı (MAC benzersiz kimliktir)')
    return ip or None, mac


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
    """MAC'i normalize eder (AA:BB:CC:DD:EE:FF). Boşsa None."""
    try:
        return printer_identity.normalize_mac(raw)
    except ValueError:
        raise HTTPException(400, 'MAC adresi 12 onaltılık haneden oluşmalı (ör. FC:EE:28:0F:36:97)')


@router.post('')
def add_printer(body: PrinterIn, user=Depends(printer_admin), conn=db.DB):
    ip, mac = _validate(conn, body)
    cur = conn.execute('INSERT INTO printers (name, ip, created_at, mac, mac_source, hw_id) VALUES (?,?,?,?,?,?)',
                       (body.name.strip(), ip, db.now(), mac, 'elle' if mac else None, printer_identity.hw_from_mac(mac)))
    db.audit(conn, user['id'], 'Yazıcı ekledi', 'printer', cur.lastrowid, f'{body.name} (MAC {mac or "—"}, IP {ip or "—"})')
    printer_layout.assign_missing(conn)   # odada ilk boş rafa
    return {'id': cur.lastrowid}


@router.put('/{pid}')
def update_printer(pid: int, body: PrinterIn, user=Depends(printer_admin), conn=db.DB):
    cur = db.row(conn.execute('SELECT mac, mac_source FROM printers WHERE id = ?', (pid,)))
    if not cur:
        raise HTTPException(404, 'Yazıcı bulunamadı')
    ip, mac = _validate(conn, body, pid)
    src = cur['mac_source'] if mac == cur['mac'] else ('elle' if mac else None)
    conn.execute('UPDATE printers SET name = ?, ip = ?, mac = ?, mac_source = ?, hw_id = COALESCE(hw_id, ?), '
                 'mac_checked_at = CASE WHEN mac IS ? THEN mac_checked_at ELSE NULL END WHERE id = ?',
                 (body.name.strip(), ip, mac, src, printer_identity.hw_from_mac(mac), mac, pid))
    db.audit(conn, user['id'], 'Yazıcı düzenledi', 'printer', pid, f'{body.name} (MAC {mac or "—"}, IP {ip or "—"})')
    return {'ok': True}


@router.post('/{pid}/learn-mac')
async def learn_mac(pid: int, user=Depends(printer_admin)):
    """MAC'i olmayan yazıcının MAC'ini cihazdan öğrenir (son görülen IP'de ARP / yazıcının API'si; ulaşılamazsa kayıtlı
    ağ adıyla ağ taraması). O IP'de başka bir yazıcı varsa reddedilir."""
    try:
        return await run_in_threadpool(printer_identity.learn_mac, pid, user['id'])
    except printer_identity.IdentityError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:   # noqa: BLE001 — ajan/ağ hatası
        raise HTTPException(502, f'MAC okunamadı: {e}') from e


@router.post('/{pid}/locate')
async def locate(pid: int, user=Depends(printer_admin)):
    """Yazıcıyı MAC ile bulur: bilinen IP'de doğrular, değilse ağı tarar ve güncel IP'yi kaydeder (gönderimle aynı yol)."""
    try:
        return await run_in_threadpool(printer_identity.resolve_ip, pid, user['id'])
    except printer_identity.IdentityError as e:
        raise HTTPException(409, str(e)) from e


class MaintIn(BaseModel):
    on: bool


@router.post('/{pid}/maintenance')
def set_maintenance(pid: int, body: MaintIn, user=Depends(printer_admin), conn=db.DB):
    """Yazıcıyı bakıma al / hatta geri ver. Bakımdaki yazıcı BAKIM durumunda görünür (vurgulu renk) ve arıza/çevrimdışı
    sayılmaz; bakımda geçen süre takip edilir (maint_since). Üretim yetkisi olan personel yapar."""
    p = db.row(conn.execute('SELECT id, name, maint_since FROM printers WHERE id = ?', (pid,)))
    if not p:
        raise HTTPException(404, 'Yazıcı bulunamadı')
    if body.on:
        if not p['maint_since']:
            conn.execute('UPDATE printers SET maint_since = ? WHERE id = ?', (db.now(), pid))
        db.audit(conn, user['id'], 'Yazıcıyı bakıma aldı', 'printer', pid, p['name'])
    else:
        conn.execute('UPDATE printers SET maint_since = NULL WHERE id = ?', (pid,))
        db.audit(conn, user['id'], 'Yazıcıyı hatta geri verdi (bakım bitti)', 'printer', pid, p['name'])
    conn.commit()
    return {'ok': True, 'maint_since': None if not body.on else (p['maint_since'] or db.now())}


class ArgeIn(BaseModel):
    on: bool


@router.post('/{pid}/arge')
def set_arge(pid: int, body: ArgeIn, user=Depends(printer_admin), conn=db.DB):
    """Yazıcıyı Ar-Ge moduna al / hatta geri ver. Ar-Ge'deki yazıcı AR-GE durumunda görünür (vurgulu renk) ve
    arıza/çevrimdışı/HATA sayılmaz — Ar-Ge denemelerinde gcode/baskı hatası alarm üretmez (bakım gibi).
    Ar-Ge'de geçen süre takip edilir (arge_since). Üretim yetkisi olan personel yapar."""
    p = db.row(conn.execute('SELECT id, name, arge_since FROM printers WHERE id = ?', (pid,)))
    if not p:
        raise HTTPException(404, 'Yazıcı bulunamadı')
    if body.on:
        if not p['arge_since']:
            conn.execute('UPDATE printers SET arge_since = ? WHERE id = ?', (db.now(), pid))
        db.audit(conn, user['id'], 'Yazıcıyı Ar-Ge moduna aldı', 'printer', pid, p['name'])
    else:
        conn.execute('UPDATE printers SET arge_since = NULL WHERE id = ?', (pid,))
        db.audit(conn, user['id'], 'Yazıcıyı hatta geri verdi (Ar-Ge bitti)', 'printer', pid, p['name'])
    conn.commit()
    return {'ok': True, 'arge_since': None if not body.on else (p['arge_since'] or db.now())}


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
                         pool.map(lambda p: printer_driver.device_name(p['ip']) if p['ip'] else None, printers)))
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
            final[p['id']] = nm if p['id'] == winner else f'{nm} ({(p["ip"] or "").rsplit(".", 1)[-1] or p["id"]})'
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
        found, _ = await run_in_threadpool(printer_identity.scan, 0)   # elle tarama: taze (önbelleği de tazeler)
    except Exception as e:   # noqa: BLE001 — uzak modda ajan bağlı değil / eski ajan: anlaşılır mesaj
        msg = str(e)
        if 'bilinmeyen op' in msg.lower():
            raise HTTPException(503, 'Fabrikadaki ajan güncel değil (yazıcı taraması bu sürümde yok). GX10’da ajanı güncelleyin: '
                                     'cd ~/caymazbuild && git pull && systemctl --user restart hepgo-agent') from e
        if 'bağlı değil' in msg.lower() or 'ajan' in msg.lower() or 'agent' in msg.lower():
            raise HTTPException(503, 'Fabrikadaki ajana ulaşılamadı; yazıcı taraması yapılamadı. Ajanın çevrimiçi ve güncel olduğundan emin olun.') from e
        raise HTTPException(502, f'Yazıcı taraması başarısız: {msg}') from e
    try:
        return await run_in_threadpool(_add_discovered, found, user)
    except HTTPException:
        raise
    except Exception as e:   # noqa: BLE001 — beklenmeyen: hata türü + ilk fark edilen sebep yanıtta görünsün
        import traceback
        tb = traceback.format_exc()
        try:   # ayrıntı denetim/log için data'ya yazılır (sahibi okuyabilir)
            (config.DATA_DIR / 'printer-discover-error.log').write_text(tb)
        except Exception:   # noqa: BLE001
            pass
        raise HTTPException(500, f'Yazıcılar işlenirken hata: {type(e).__name__}: {str(e)[:300]}') from e


def _add_discovered(found, user):
    """Tarama sonuçlarını kayıtlarla MAC MERKEZLİ eşleştirir (printer_identity.apply_scan): MAC'i (ya da MAC'ten
    türeyen ağ adı / kayıtlı ağ adı) eşleşen yazıcının yalnız son görülen IP'si ve canlı durumu güncellenir — elektrik
    kesintisinde IP'ler değişse hatta takas olsa bile kayıt silinmez. Aynı IP'yi tutan eski kaydın IP'si boşaltılır
    (UNIQUE çakışması yok). Eşleşmeyen cihazlar MAC'leriyle yeni yazıcı olarak eklenir; MAC'i olmayan kayıtlara
    taramadan gelen kablolu MAC yazılır."""
    return printer_identity.apply_scan(found, user['id'], add_new=True)
