"""3B Montaj: parçaların G-code'dan çıkarılmış gerçek 3B takım yollarını (.3d.bin) uçaktaki yerlerine oturtur.

Parçalar yazıcıda dik / çapraz basıldığı için her parçanın uçaktaki yönü geometriden bulunur:
  1. Noktaların ana eksenleri (PCA) → kalınlık ekseni adayları (kanat / kapak: en ince eksen; gövde: üçü de).
  2. Kalan iki eksendeki izdüşümün dışbükey zarfı, şemadaki parça çokgeniyle örtüşecek (IoU) şekilde döndürülür (0–360°);
     ters yüz (ayna + normal çevirme = 180° dönüş, yani gerçek bir dönüş) de denenir. Ölçek tüm uçak için tektir (mm / şema birimi).
  3. Birbirine çok yakın puanlı adaylar arasında (kare parçalarda 90° belirsizliği) komşu parçalarla ortak kenarda kalınlıkları
     en iyi uyan seçilir (yinelemeli yerel iyileştirme).
  4. Kapaklar altlarındaki gövdenin üstüne, fırlatma arabası gövdenin altına, elektronik kat gövdenin içine yerleşir.
Sonuç tek bir ikili dosyadır (int16, 0,25 mm): parça başına seyreltilmiş segmentler, uçak koordinatlarında
(X sağ, Y yukarı, Z arka; mm). Yanında parça listesi (aralık, bölüm, merkez). Önizlemeler değişmedikçe önbellekten verilir.
"""
import hashlib
import json
import math
import threading

import numpy as np

from . import catalogs, config, db, semis

ALGO = 8                  # algoritma değişince önbellek yenilenir
SCALE = 0.553             # şema birimi / mm (gövde ve kanat parçalarının medyanı)
MAX_SEGS = 12_000         # parça başına (tarayıcıda akıcı)
Q = 4.0                   # int16 nicemleme: 1/4 mm
THIN = {'wing', 'strake', 'elevon', 'cover', 'electronics'}
# Başka parçaya bağlı yerleşim: elektronik katı 06'nın içinde, K04 kapağı 06'nın üstüne kapanır
HOSTED = {'EK': ('06', 'inside'), 'K04': ('06', 'top'), 'EK-V2': ('06-V2', 'inside')}
MIN_IOU = 0.5             # bundan düşük uyumlu parça oturtulmaz; uçağın yanında (yazıcıdaki duruşuyla) gösterilir
FOLDER = 'gcode'
_lock = threading.Lock()


# ---------- 2B geometri (numpy, harici kütüphane yok)
def _hull(P):
    P = sorted(set(map(tuple, np.round(P, 2).tolist())))
    if len(P) < 3:
        return np.array(P, dtype=float)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in P:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return np.array(lo[:-1] + up[:-1], dtype=float)


def _area(P):
    if P is None or len(P) < 3:
        return 0.0
    x, y = P[:, 0], P[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _ccw(P):
    x, y = P[:, 0], P[:, 1]
    return P if (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) > 0 else P[::-1]


def _clip(subj, clipp):
    """Dışbükey çokgen kesişimi (Sutherland–Hodgman); ikisi de saat yönü tersine."""
    out = subj.tolist()
    n = len(clipp)
    for i in range(n):
        a, b = clipp[i], clipp[(i + 1) % n]
        inp, out = out, []
        if not inp:
            break
        ex, ey = b[0] - a[0], b[1] - a[1]
        s = inp[-1]
        for e in inp:
            ein = ex * (e[1] - a[1]) - ey * (e[0] - a[0]) >= 0
            sin_ = ex * (s[1] - a[1]) - ey * (s[0] - a[0]) >= 0
            if ein != sin_:
                x1, y1, x2, y2 = s[0], s[1], e[0], e[1]
                d = (x1 - x2) * (a[1] - b[1]) - (y1 - y2) * (a[0] - b[0])
                if abs(d) > 1e-12:
                    t = ((x1 - a[0]) * (a[1] - b[1]) - (y1 - a[1]) * (a[0] - b[0])) / d
                    out.append([x1 + t * (x2 - x1), y1 + t * (y2 - y1)])
            if ein:
                out.append(e)
            s = e
    return np.array(out) if len(out) >= 3 else None


def _iou(A, B):
    ia = _area(_clip(A, B))
    return ia / max(1e-9, _area(A) + _area(B) - ia)


def _rot(t):
    return np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])


# ---------- Parça verisi
def _load(path):
    a = np.fromfile(config.UPLOAD_DIR / path, dtype='<f4')
    return a[6:].reshape(-1, 6)   # x1 y1 z1 x2 y2 z2


def _components(segs, cell=6.0):
    """Tek baskıda birden çok adet: XY'de ayrık kümeler (ızgara komşuluğu)."""
    p = segs[:, :2]
    keys = np.floor(p / cell).astype(np.int64)
    cells = {}
    for i, k in enumerate(map(tuple, keys)):
        cells.setdefault(k, []).append(i)
    seen, comps = set(), []
    for k in cells:
        if k in seen:
            continue
        stack, comp = [k], []
        seen.add(k)
        while stack:
            c = stack.pop()
            comp.extend(cells[c])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (c[0] + dx, c[1] + dy)
                    if nb in cells and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        comps.append(np.array(comp))
    comps.sort(key=len, reverse=True)
    return [segs[c] for c in comps if len(c) > len(segs) * 0.02]


def _level(Qp, n, u):
    """Plakanın gerçek normali: üstten izdüşüm alanının en büyük olduğu yön (±12° içinde iki eksende arama)."""
    sub = Qp[np.random.default_rng(2).choice(len(Qp), min(len(Qp), 2500), replace=False)]
    v = np.cross(n, u)

    def basis(a, b):
        nn = n + math.tan(a) * u + math.tan(b) * v
        nn /= np.linalg.norm(nn)
        uu = u - nn * np.dot(u, nn)
        uu /= np.linalg.norm(uu)
        return nn, uu

    def area_of(a, b):
        nn, uu = basis(a, b)
        vv = np.cross(nn, uu)
        return _area(_hull(np.c_[sub @ uu, sub @ vv]))
    best, ba, bb = area_of(0, 0), 0.0, 0.0
    for step, span in ((math.radians(4), 3), (math.radians(1.5), 2), (math.radians(0.5), 2)):
        ca, cb = ba, bb
        for i in range(-span, span + 1):
            for j in range(-span, span + 1):
                a, b = ca + i * step, cb + j * step
                if abs(a) > math.radians(14) or abs(b) > math.radians(14):
                    continue
                x = area_of(a, b)
                if x > best * 1.0005:
                    best, ba, bb = x, a, b
    return basis(ba, bb)


def _candidates(pts, poly, thin):
    """Yön adayları: [(iou, R(3x3: satırlar dünya X, Y, Z eksenlerinin parça çerçevesindeki karşılığı), c)]"""
    c = (pts.min(0) + pts.max(0)) / 2
    Qp = pts - c
    _, V = np.linalg.eigh(np.cov(Qp.T))
    S = _ccw(_hull(poly))
    S0 = S - S.mean(0)
    out = []
    axes = [(k, V[:, k], V[:, (k + 1) % 3]) for k in (0, 1, 2)]
    if thin:   # kama biçimli (incelen) plakada PCA normali birkaç derece kayar: eğikliği düzeltilmiş eksen de aday
        n0, u0 = _level(Qp, V[:, 0], V[:, 1])
        axes.insert(1, (0, n0, u0))
    for k, n, u in axes:
        v = np.cross(n, u)
        q = np.c_[Qp @ u, Qp @ v]
        H = _hull(q)
        hm = H.mean(0)
        for m in (1, -1):
            Hm = (H - hm) * [1, m] * SCALE

            def score(t):
                return _iou(_ccw(Hm @ _rot(t).T), S0)
            coarse = sorted(((score(math.radians(a)), math.radians(a)) for a in range(0, 360, 5)), reverse=True)
            picked = []
            for sc, t0 in coarse:   # birbirinden ayrı yerel tepeler (90° belirsizliği için)
                if any(abs(((t0 - t1 + math.pi) % (2 * math.pi)) - math.pi) < math.radians(25) for _, t1 in picked):
                    continue
                picked.append((sc, t0))
                if len(picked) == 4:
                    break
            for sc, t0 in picked:
                for a in np.arange(-5, 5.01, 1.0):
                    t = t0 + math.radians(a)
                    x = score(t)
                    if x > sc:
                        sc, t0 = x, t
                R2 = _rot(t0) @ np.diag([1, m])
                # dünya X (sağ) ve Z (arka) = döndürülmüş (u, v); Y (yukarı) = m·n  → gerçek dönüş (det = +1)
                ax = R2[0, 0] * u + R2[0, 1] * v
                az = R2[1, 0] * u + R2[1, 1] * v
                ay = np.cross(az, ax)
                R = np.vstack([ax, ay, az])
                if np.linalg.det(R) < 0:
                    ay = -ay
                    R = np.vstack([ax, ay, az])
                # zarf merkezinin (u,v)'deki yeri: dünya konumunu şema merkezine taşımak için
                off = R2 @ (hm * [1, 1])
                # ince parçada (kanat, kapak) kalınlık büyük olasılıkla en ince eksendir: diğer eksenlere küçük ceza
                out.append({'iou': sc, 'R': R, 'c': c, 'hoff': off, 'rank': sc - (0.12 if thin and k else 0)})
    out.sort(key=lambda x: -x['rank'])
    return out


def _edge_thick(world, bbox):
    """Parçanın dört kenarındaki kalınlık (Y aralığı): {'W','E','N','S'}"""
    x0, x1, z0, z1 = bbox
    wx, wz = (x1 - x0) * 0.12, (z1 - z0) * 0.12
    X, Y, Z = world[:, 0], world[:, 1], world[:, 2]
    res = {}
    for side, mask in (('W', X < x0 + wx), ('E', X > x1 - wx), ('N', Z < z0 + wz), ('S', Z > z1 - wz)):
        res[side] = float(Y[mask].max() - Y[mask].min()) if mask.sum() > 20 else None
    return res


def _adjacent(polys):
    """Şemada ortak kenarı olan parça çiftleri: (a, yan_a, b, yan_b)"""
    bb = {k: (P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max()) for k, P in polys.items()}
    out = []
    keys = list(bb)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            A, B = bb[a], bb[b]
            oy = min(A[3], B[3]) - max(A[2], B[2])
            ox = min(A[1], B[1]) - max(A[0], B[0])
            if abs(A[1] - B[0]) < 4 and oy > 0.3 * min(A[3] - A[2], B[3] - B[2]):
                out.append((a, 'E', b, 'W'))
            elif abs(B[1] - A[0]) < 4 and oy > 0.3 * min(A[3] - A[2], B[3] - B[2]):
                out.append((a, 'W', b, 'E'))
            elif abs(A[3] - B[2]) < 4 and ox > 0.3 * min(A[1] - A[0], B[1] - B[0]):
                out.append((a, 'S', b, 'N'))
            elif abs(B[3] - A[2]) < 4 and ox > 0.3 * min(A[1] - A[0], B[1] - B[0]):
                out.append((a, 'N', b, 'S'))
    return out


def _peak_mod90(dx, dz, w):
    """Yön histogramının (90° kipinde) tepe açısı (radyan, [-π/4, π/4))."""
    ang = np.mod(np.arctan2(dz, dx), math.pi / 2)
    hist, edges = np.histogram(ang, bins=180, range=(0, math.pi / 2), weights=w)
    hist = hist + np.roll(hist, 1) + np.roll(hist, -1)   # yumuşat (dairesel)
    a = (edges[np.argmax(hist)] + math.pi / 360)
    return (a + math.pi / 4) % (math.pi / 2) - math.pi / 4


def _square_up(W, poly):
    """İnce ayar: parçanın yatay duvar çizgilerinin baskın yönünü şema çokgeninin kenar yönlerine hizala (±12°)."""
    S = W.reshape(-1, 6)
    dx, dy, dz = S[:, 3] - S[:, 0], S[:, 4] - S[:, 1], S[:, 5] - S[:, 2]
    L = np.hypot(dx, dz)
    m = (L > 2) & (np.abs(dy) < 0.3 * L)
    if m.sum() < 50:
        return W
    pa = _peak_mod90(dx[m], dz[m], L[m])
    P = np.asarray(poly, dtype=float)
    E = np.roll(P, -1, axis=0) - P
    pe = _peak_mod90(E[:, 0], E[:, 1], np.hypot(E[:, 0], E[:, 1]))
    d = (pe - pa + math.pi / 4) % (math.pi / 2) - math.pi / 4
    if abs(d) < math.radians(0.5) or abs(d) > math.radians(12):
        return W
    c = np.array([(W[:, 0].min() + W[:, 0].max()) / 2, 0, (W[:, 2].min() + W[:, 2].max()) / 2])
    cs, sn = math.cos(d), math.sin(d)
    X, Z = W[:, 0] - c[0], W[:, 2] - c[2]
    out = W.copy()
    out[:, 0] = c[0] + X * cs - Z * sn
    out[:, 2] = c[2] + X * sn + Z * cs
    return out


def _decimate(segs):
    if len(segs) <= MAX_SEGS:
        return segs
    zs = np.unique(np.round(segs[:, 2], 2))
    step = max(1, math.ceil(len(segs) / MAX_SEGS))
    keep = set(np.round(zs[::step], 2).tolist())
    m = np.isin(np.round(segs[:, 2], 2), list(keep))
    out = segs[m]
    if len(out) > MAX_SEGS * 1.3:   # katman başına çok segment: düzenli seyrelt
        out = out[:: math.ceil(len(out) / MAX_SEGS)]
    return out


# ---------- Montaj
def _signature(schema_key, previews):
    h = hashlib.sha1(f'{ALGO}|{schema_key}|'.encode())
    for pid in sorted(previews):
        f = config.UPLOAD_DIR / previews[pid]
        st = f.stat() if f.exists() else None
        h.update(f'{pid}:{previews[pid]}:{st.st_size if st else 0}:{int(st.st_mtime) if st else 0};'.encode())
    return h.hexdigest()[:16]


def build(conn, schema_key):
    """Montaj dosyası (önbellekli): {'file', 'parts': [...], 'scale', 'missing': [...]}"""
    mod = catalogs.schema(schema_key)
    base = getattr(mod, 'base', None)   # yarı mamul şeması: ana şemanın alt kümesi (yerleşim ana şemadan)
    parts = [p for p in (base.build() if base else mod.build())]
    if base:
        ids = set(mod.part_ids())
        parts = [p for p in parts if p['id'] in ids]
    info = semis.print_info(conn)
    previews = {p['id']: info[p['id']]['gcode_preview'] for p in parts if info.get(p['id'], {}).get('gcode_preview')}
    sig = _signature(schema_key, previews)
    out = config.UPLOAD_DIR / FOLDER / f'assembly-{schema_key}-{sig}.bin'
    meta_f = out.with_suffix('.json')
    with _lock:
        if out.exists() and meta_f.exists():
            return json.loads(meta_f.read_text())
        meta = _compute(parts, previews, out)
        meta['file'] = f'{FOLDER}/{out.name}'
        meta_f.write_text(json.dumps(meta, ensure_ascii=False))
        for old in (config.UPLOAD_DIR / FOLDER).glob(f'assembly-{schema_key}-*'):   # eski sürümler
            if sig not in old.name:
                old.unlink(missing_ok=True)
        return meta


def _compute(parts, previews, out):
    loose = lambda p: not p.get('section') or p['id'].startswith('ARABA')
    allpts = np.array([q for p in parts if not loose(p) for s in p['shapes'] for q in s['pts']], dtype=float)
    CX, CY = (allpts[:, 0].min() + allpts[:, 0].max()) / 2, (allpts[:, 1].min() + allpts[:, 1].max()) / 2
    body = np.array([q for p in parts if p.get('section') == 'GOVDE' and p['group'] in ('body', 'nose')
                     for s in p['shapes'] for q in s['pts']], dtype=float)
    bx = (body[:, 0].min(), body[:, 0].max()) if len(body) else (CX, CX)
    by = (body[:, 1].min(), body[:, 1].max()) if len(body) else (CY, CY)

    # Her parça çokgeni (ayrı çizilenler gövdeye taşınır)
    under_n = 0
    shapes = {}
    for p in parts:
        polys = [np.array(s['pts'], dtype=float) for s in p['shapes']]
        if loose(p):
            P = np.vstack(polys)
            cx, cy = P[:, 0].mean(), P[:, 1].mean()
            if cx < bx[0] or cx > bx[1] or cy < by[0] or cy > by[1]:
                k = under_n if p['layer'] != 'electronics' else 0
                if p['layer'] != 'electronics':
                    under_n += 1
                tx, ty = (bx[0] + bx[1]) / 2 - cx, by[0] * 0.55 + by[1] * 0.45 + k * 170 - cy
                polys = [P_ + [tx, ty] for P_ in polys]
        shapes[p['id']] = polys
    for pid, (host, _) in HOSTED.items():   # yönü ev sahibi parçanın çokgenine göre bulunur
        if pid in shapes and host in shapes:
            shapes[pid] = [shapes[host][0]]

    # Aday yönler
    cand, data = {}, {}
    for p in parts:
        if p['id'] not in previews:
            continue
        try:
            segs = _load(previews[p['id']])
        except OSError:
            continue
        if not len(segs):
            continue
        comps = _components(segs) if len(shapes[p['id']]) > 1 else [segs]
        main = comps[0] if len(comps) >= 1 else segs
        pts = main.reshape(-1, 3)
        rng = np.random.default_rng(1)
        sample = pts[rng.choice(len(pts), min(len(pts), 16000), replace=False)]
        thin = p['group'] in THIN or p.get('layer') in ('cover', 'electronics')
        cs = _candidates(sample, shapes[p['id']][0], thin)
        best = cs[0]['rank']
        cand[p['id']] = [c for c in cs if c['rank'] >= best - 0.06][:8]
        data[p['id']] = _decimate(main)

    # Oturtulamayanlar: şemada ayrı çizilenler (elektronik kat, fırlatma arabası) ve şemaya uyumu düşük olanlar
    hosted = {pid for pid, (host, _) in HOSTED.items() if pid in cand and host in cand}
    outside = {p['id'] for p in parts if p['id'] in cand and p['id'] not in hosted and (loose(p) or cand[p['id']][0]['iou'] < MIN_IOU)}
    for pid in outside:
        cand.pop(pid, None)
    outside_data = {pid: data[pid] for pid in outside}

    def world(pid, c, segs=None, shape_i=0):
        P = (data[pid] if segs is None else segs).reshape(-1, 3)
        W = (P - c['c']) @ c['R'].T
        poly = shapes[pid][shape_i]
        sc = _hull(poly).mean(0)
        W[:, 0] += -c['hoff'][0] + (sc[0] - CX) / SCALE
        W[:, 2] += -c['hoff'][1] + (sc[1] - CY) / SCALE
        W[:, 1] -= (W[:, 1].max() + W[:, 1].min()) / 2
        return W

    # Komşu kenar uyumu (yinelemeli): maliyet = kenar kalınlık farkı (mm) / 25 − 3 × IoU
    polys1 = {pid: shapes[pid][0] for pid in cand}
    adj = _adjacent(polys1)
    choice = {pid: 0 for pid in cand}
    edges = {}

    def edge(pid, i):
        if (pid, i) not in edges:
            W = world(pid, cand[pid][i])
            P = polys1[pid]
            bb = ((P[:, 0].min() - CX) / SCALE, (P[:, 0].max() - CX) / SCALE, (P[:, 1].min() - CY) / SCALE, (P[:, 1].max() - CY) / SCALE)
            edges[(pid, i)] = _edge_thick(W, bb)
        return edges[(pid, i)]
    nb = {}
    for a, sa, b, sb in adj:
        nb.setdefault(a, []).append((sa, b, sb))
        nb.setdefault(b, []).append((sb, a, sa))
    for _ in range(4):
        changed = False
        for pid in cand:
            if len(cand[pid]) < 2 or pid not in nb:
                continue
            best_i, best_c = choice[pid], None
            for i, c in enumerate(cand[pid]):
                e = edge(pid, i)
                cost = -3 * c['rank']
                for side, other, oside in nb[pid]:
                    t1, t2 = e.get(side), edge(other, choice[other]).get(oside)
                    if t1 is not None and t2 is not None:
                        cost += abs(t1 - t2) / 25
                if best_c is None or cost < best_c - 1e-6:
                    best_i, best_c = i, cost
            if best_i != choice[pid]:
                choice[pid] = best_i
                changed = True
        if not changed:
            break

    # Yerleştir: gövde / kanat merkezde; kapaklar üstte, araba altta, elektronik içte
    placed, order = {}, []
    for p in sorted(parts, key=lambda p: (p.get('layer') == 'cover' or p['group'] == 'cover', loose(p))):
        pid = p['id']
        if pid not in cand:
            continue
        c = cand[pid][choice[pid]]
        segs_list = []
        comps = None
        if len(shapes[pid]) > 1:
            full = _load(previews[pid])
            comps = _components(full)
        for si in range(len(shapes[pid])):
            src = _decimate(comps[si]) if comps and si < len(comps) and len(comps) == len(shapes[pid]) else data[pid]
            # her kopya aynı yönde, kendi kümesinin merkezine göre
            cc = dict(c)
            if comps and si < len(comps) and len(comps) == len(shapes[pid]):
                P = src.reshape(-1, 3)
                cc['c'] = c['c'] + ((P.min(0) + P.max(0)) / 2 - (data[pid].reshape(-1, 3).min(0) + data[pid].reshape(-1, 3).max(0)) / 2)
            W = world(pid, cc, src, si)
            W = _square_up(W, shapes[pid][si])
            cover = p.get('layer') == 'cover' or p['group'] == 'cover'
            if cover or (loose(p) and p.get('layer') != 'electronics'):
                # altındaki / üstündeki yerleşmiş parçaların yüzeyi (aynı XZ bölgesi)
                x0, x1, z0, z1 = W[:, 0].min(), W[:, 0].max(), W[:, 2].min(), W[:, 2].max()
                ys = []
                for q in placed.values():
                    m = (q[:, 0] > x0) & (q[:, 0] < x1) & (q[:, 2] > z0) & (q[:, 2] < z1)
                    if m.sum() > 10:
                        ys.append((q[m, 1].max(), q[m, 1].min()))
                h = W[:, 1].max() - W[:, 1].min()
                if cover and not loose(p):
                    top = max((y[0] for y in ys), default=0)
                    W[:, 1] += top + 1 - W[:, 1].min()
                else:
                    bot = min((y[1] for y in ys), default=-h)
                    W[:, 1] += bot - 1 - W[:, 1].max()
            segs_list.append(W)
        W = np.vstack(segs_list)
        if pid in hosted and HOSTED[pid][0] in placed:
            Hw = placed[HOSTED[pid][0]]
            W[:, 0] += (Hw[:, 0].min() + Hw[:, 0].max()) / 2 - (W[:, 0].min() + W[:, 0].max()) / 2
            W[:, 2] += (Hw[:, 2].min() + Hw[:, 2].max()) / 2 - (W[:, 2].min() + W[:, 2].max()) / 2
            if HOSTED[pid][1] == 'top':
                W[:, 1] += Hw[:, 1].max() + 1 - W[:, 1].min()
            else:
                W[:, 1] += (Hw[:, 1].min() + Hw[:, 1].max()) / 2 - (W[:, 1].min() + W[:, 1].max()) / 2
        placed[pid] = W
        order.append(p)

    # Oturtulamayanlar: yazıcıdaki duruşuyla (G-code Z → yukarı), sağ kanat ucunun yanında bir sıra halinde, zemine oturmuş
    if outside and placed:
        allw = np.vstack(list(placed.values()))
        x = allw[:, 0].max() + 250
        floor = allw[:, 1].min()
        z = allw[:, 2].min()
        for p in sorted((p for p in parts if p['id'] in outside), key=lambda p: p['id']):
            P = outside_data[p['id']].reshape(-1, 3)
            W = np.c_[P[:, 0], P[:, 2], P[:, 1]].astype(float)   # (x, y, z) → (X, Y yukarı, Z)
            W -= [W[:, 0].min(), W[:, 1].min(), W[:, 2].min()]
            if z + (W[:, 2].max()) > allw[:, 2].max():   # sütun doldu: yeni sütun
                x += 450
                z = allw[:, 2].min()
            W += [x, floor, z]
            z += W[:, 2].max() - W[:, 2].min() + 120
            placed[p['id']] = W
            order.append(p)

    # Yaz: int16 (¼ mm), parça aralıkları
    chunks, meta_parts, start = [], [], 0
    for p in order:
        W = placed[p['id']]
        n = len(W) // 2
        q = np.clip(np.round(W * Q), -32767, 32767).astype('<i2')
        chunks.append(q.reshape(-1))
        c = W.mean(0)
        meta_parts.append({'id': p['id'], 'start': start, 'count': n, 'section': p.get('section'), 'group': p['group'],
                           'layer': p.get('layer') or 'body', 'center': [round(float(x), 1) for x in c],
                           'outside': p['id'] in outside,
                           'iou': round(float(cand[p['id']][choice[p['id']]]['iou']), 2) if p['id'] in cand else None})
        start += n
    arr = np.concatenate(chunks) if chunks else np.zeros(0, dtype='<i2')
    out.parent.mkdir(parents=True, exist_ok=True)
    arr.tofile(out)
    return {'parts': meta_parts, 'quant': Q, 'scale': SCALE, 'segments': int(start),
            'missing': [p['id'] for p in parts if p['id'] not in placed]}


# ---------- Elle düzeltmeler (3B Montaj düzenleyicisi): otomatik yerleşimin üstüne parça başına konum / dönüş
def _ov_key(schema_key):
    return f'assembly3d.overrides.{schema_key}'


def overrides(conn, schema_key):
    r = conn.execute('SELECT v FROM app_kv WHERE k = ?', (_ov_key(schema_key),)).fetchone()
    try:
        return json.loads(r[0]) if r else {}
    except ValueError:
        return {}


def save_overrides(conn, schema_key, parts):
    cur = overrides(conn, schema_key)
    for pid, v in (parts or {}).items():
        pid = str(pid)[:40]
        if not v:
            cur.pop(pid, None)
            continue
        try:
            p = [max(-20000.0, min(20000.0, float(x))) for x in (v.get('p') or [0, 0, 0])][:3]
            r = [float(x) % 360 for x in (v.get('r') or [0, 0, 0])][:3]
        except (TypeError, ValueError, AttributeError):
            continue
        if len(p) == 3 and len(r) == 3:
            cur[pid] = {'p': [round(x, 1) for x in p], 'r': [round(x, 2) for x in r]}
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (_ov_key(schema_key), json.dumps(cur)))
    return cur
