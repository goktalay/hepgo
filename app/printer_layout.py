"""Yazıcı odası yerleşimi (Yazıcı Yönetimi → 3B görünüm). Oda ortasında koridor; sağda ve solda iki katlı raflar.
Her yazıcının yeri: taraf (L sol / R sağ), kat (1 alt / 2 üst), sıra (1 = oda girişine en yakın).
Yeri olmayan yazıcı (yeni eklenen) ilk boş yere konur; sıra ad numarasına göredir: önce sol alt, sol üst, sağ alt, sağ üst."""
import math
import re

ROWS = [('L', 1), ('L', 2), ('R', 1), ('R', 2)]
MIN_SLOTS = 15   # bir raf katındaki yer sayısı (yazıcı sayısı artarsa uzar)


def _key(name):
    m = re.search(r'\d+', name or '')
    return (0, int(m.group()), name) if m and re.fullmatch(r'\s*(K2\s*Plus\s*)?\d+\s*', name or '', re.I) else (1, 0, name or '')


def slots_per_row(count):
    return max(MIN_SLOTS, math.ceil(count / len(ROWS)))


def assign_missing(conn):
    printers = conn.execute('SELECT id, name, rack_side, rack_level, rack_slot FROM printers').fetchall()
    per_row = slots_per_row(len(printers))
    used = {(p[2], p[3], p[4]) for p in printers if p[2]}
    free = [(s, lv, n) for s, lv in ROWS for n in range(1, per_row + 1) if (s, lv, n) not in used]
    for pid, name, *_ in sorted((p for p in printers if not p[2]), key=lambda p: _key(p[1])):
        if not free:
            break
        side, level, slot = free.pop(0)
        conn.execute('UPDATE printers SET rack_side = ?, rack_level = ?, rack_slot = ? WHERE id = ?', (side, level, slot, pid))
