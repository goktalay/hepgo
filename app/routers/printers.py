import ipaddress
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import auth, config, db, printer_driver, printer_layout

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
    """Tarama sonuçlarını GEÇİCİ bir tabloya (_scan) alır, mevcut yazıcılarla FİZİKSEL ADRESE (kalıcı donanım kimliği —
    Moonraker seri-adı) göre eşleştirir ve yeni bilgileri (IP + canlı durum) eskinin ÜZERİNE yazar. Donanım kimliği sabit
    olduğundan, elektrik kesintisinde IP'ler değişse hatta takas olsa bile kayıt silinmez; yalnız IP güncellenir.
    IP benzersizlik çakışmasını (A↔B takası ya da IP'yi hâlâ tutan eski kayıt) iki aşamalı yazımla aşar: önce çakışanlar
    geçici bir değere park edilir, sonra gerçek IP yazılır. Kimliği okunamayan (hw yok) cihazlar IP'ye göre eklenir."""
    from concurrent.futures import ThreadPoolExecutor
    added, moved = [], []
    # Donanım kimliği taramada geldiyse onu kullan (uzak modda ajan döner); yoksa yerelde oku
    hwids, missing = {}, []
    for ip, live in found:
        if isinstance(live, dict) and 'hw' in live:
            hwids[ip] = live['hw']
        else:
            missing.append(ip)
    if missing:
        with ThreadPoolExecutor(max_workers=24) as pool:
            hwids.update(zip(missing, pool.map(printer_driver.hardware_id, missing)))
    # Tarama satırları; aynı cihaz iki IP'de göründüyse (kablolu+Wi-Fi) ilk IP'de bir kez
    scan, seen_hw = [], set()
    for ip, live in sorted((f for f in found if isinstance(f[1], dict)), key=lambda f: ipaddress.IPv4Address(f[0])):
        hw = hwids.get(ip)
        if hw:
            if hw in seen_hw:
                continue
            seen_hw.add(hw)
        scan.append({'ip': ip, 'hw': hw, 'live': live})

    with db.connect() as conn:
        now = db.now()
        conn.execute('DROP TABLE IF EXISTS _scan')
        conn.execute('CREATE TEMP TABLE _scan (ip TEXT, hw TEXT, state TEXT, progress REAL, file TEXT, source TEXT, model TEXT, hostname TEXT)')
        conn.executemany('INSERT INTO _scan (ip, hw, state, progress, file, source, model, hostname) VALUES (?,?,?,?,?,?,?,?)',
                         [(s['ip'], s['hw'], s['live'].get('state'), s['live'].get('progress'), s['live'].get('file'),
                           s['live'].get('source'), s['live'].get('model'), s['live'].get('hostname')) for s in scan])
        existing = db.rows(conn.execute('SELECT id, name, ip, hw_id, hw_alias FROM printers'))

        # Geçici tabloyu eski tabloyla fiziksel adrese göre eşleştir (her kayıt bir kez): eşleşen → güncelle, yoksa → ekle
        matched_pid, scan_ip_owner = {}, {}   # pid → tarama satırı ; hedef IP → onu hak eden pid
        for r in db.rows(conn.execute('''SELECT p.id AS pid, s.ip AS ip FROM _scan s
                                         JOIN printers p ON s.hw IS NOT NULL AND (s.hw = p.hw_id OR s.hw = p.hw_alias)''')):
            matched_pid.setdefault(r['pid'], r['ip'])
            scan_ip_owner.setdefault(r['ip'], r['pid'])
        # hw ile eşleşmemiş tarama satırı mevcut bir IP'deyse: aynı cihaz say ANCAK kimlikler çelişmiyorsa (tarama kimliksiz
        # ya da kayıt kimliksiz ya da ikisinin kimliği aynı). Farklı kimlikli bir cihaz aynı IP'deyse eski kayıt feragat eder.
        by_id = {r['id']: r for r in existing}
        ip_to_pid = {r['ip']: r['id'] for r in existing}
        for s in scan:
            if s['ip'] in scan_ip_owner:
                continue
            pid = ip_to_pid.get(s['ip'])
            if pid is None or pid in matched_pid:
                continue
            pr_hw = {by_id[pid]['hw_id'], by_id[pid]['hw_alias']} - {None}
            if (not s['hw']) or (not pr_hw) or (s['hw'] in pr_hw):
                matched_pid[pid] = s['ip']
                scan_ip_owner[s['ip']] = pid
        live_of = {s['ip']: s['live'] for s in scan}
        name_of = {r['id']: r['name'] for r in existing}

        # Park: bir tarama IP'sini tutan ama o IP'nin sahibi OLMAYAN kayıtları geçici benzersiz değere çek (çakışmayı kır)
        scan_ips = {s['ip'] for s in scan}
        for r in existing:
            if r['ip'] in scan_ips and scan_ip_owner.get(r['ip']) != r['id']:
                conn.execute("UPDATE printers SET ip = '#tasima-' || id WHERE id = ?", (r['id'],))

        # Eşleşenler: IP + canlı durum eskinin üzerine yazılır (fiziksel adres aynı → aynı yazıcı)
        for pid, ip in matched_pid.items():
            old = next((r['ip'] for r in existing if r['id'] == pid), None)
            live = live_of.get(ip, {})
            conn.execute('''UPDATE printers SET ip = ?, live_state = ?, live_progress = ?, live_file = ?, live_source = ?,
                            last_seen = ? WHERE id = ?''',
                         (ip, live.get('state'), live.get('progress'), live.get('file'), live.get('source'), now, pid))
            if old and old != ip:
                moved.append({'id': pid, 'name': name_of.get(pid), 'old': old, 'ip': ip})
                db.audit(conn, user['id'], 'Yazıcının IP adresini düzeltti (ağ taraması)', 'printer', pid,
                         f"{name_of.get(pid) or pid}: {old} → {ip}")

        # Eşleşmeyen tarama satırları: IP artık boşsa yeni yazıcı olarak eklenir
        count = conn.execute('SELECT COUNT(*) FROM printers').fetchone()[0]
        for s in scan:
            if s['ip'] in scan_ip_owner:   # zaten mevcut bir yazıcıya (fiziksel adres) eşleşti
                continue
            if conn.execute('SELECT 1 FROM printers WHERE ip = ?', (s['ip'],)).fetchone():
                continue
            count += 1
            live = s['live']
            name = live.get('hostname') or f'K2 Plus {count:02d}'
            cur = conn.execute(
                '''INSERT INTO printers (name, ip, hw_id, model, auto_added, created_at, live_state, live_progress,
                   live_file, live_source, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (name, s['ip'], s['hw'], live.get('model') or 'Creality K2 Plus', 1, now, live.get('state'),
                 live.get('progress'), live.get('file'), live.get('source'), now))
            db.audit(conn, user['id'], 'Yazıcı otomatik ekledi', 'printer', cur.lastrowid, f"{name} ({s['ip']})")
            added.append({'name': name, 'ip': s['ip']})

        conn.execute('DROP TABLE IF EXISTS _scan')
        printer_layout.assign_missing(conn)
    return {'found': len(found), 'added': added, 'moved': moved}
