"""CAYMAZ parça haritası: tüm parçaların tek kaynağı.

Çizim ızgara hücrelerinin konumsal adlarıyla (KL-A1 = sol kanat A satırı 1. sütun gibi) üretilir;
her hücrenin parça kodu PART_CODES tablosundadır.

Koordinatlar referans çizimin piksel uzayındadır (≈1920×1920). Simetri ekseni
x = 921; sağ taraf sol tarafın aynasıdır. Sipariş parçaları da bu listeden
üretilir, bu yüzden parça eklemek/bölmek/birleştirmek yalnızca burada yapılır.
"""
import math
from functools import lru_cache

AXIS2 = 1842
VIEWBOX = [50, 50, 1745, 1770]

GROUPS = {
    'nose': 'Burun',
    'body': 'Gövde',
    'strake': 'Yan Şerit',
    'wing': 'Kanat',
    'elevon': 'Elevon',
    'cover': 'Kapak',
    'electronics': 'Elektronik',
}

# Elektronik kat: uçağın dışında (çizimin sağ üstünde) gösterilen ayrı baskı parçası. Diğer parçalar gibi
# üretilir ve depoya girer; depoda elektronik komponentleri takılır. Montaj bölümlerine ait değildir
# (section None). Depoya girmeden sipariş montaja geçmez; elektronik montajı bitmeden uçak kalibrasyona geçemez.
# Şekli şimdilik kare (kullanıcı gerçek şekli verecek).
ELECTRONICS_PART = 'EK'
# Elektronik katmanındaki parçalar: her birine ayrı elektronik montaj adımı yapılır (adım: ELEKTRONIK_<kod>)
ELECTRONICS_PARTS = {'EK': 'Elektronik Kat', 'K04': 'K04 kapağı'}
ELECTRONICS_BOX = [[1530, 80], [1720, 80], [1720, 347], [1530, 347]]   # dış çerçeve (uçak koordinatları)


def _electronics_shape():
    """Elektronik kat çizimi (kullanıcının teknik resminden): dikey dikdörtgen gövde, iki yanda ray, üstte orta girinti
    ve köşe braketleri, ortada pencere, 4 vida + 2 alt köşe deliği, üstte ve altta bağlantı noktaları.
    Teknik resim piksel koordinatları çerçeveye (x 88–216, y 65–245) ölçeklenir."""
    k = (ELECTRONICS_BOX[1][0] - ELECTRONICS_BOX[0][0]) / 128
    P = lambda x, y: [ELECTRONICS_BOX[0][0] + (x - 88) * k, ELECTRONICS_BOX[0][1] + (y - 65) * k]
    rect = lambda x0, y0, x1, y1: [P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)]
    ring = lambda x, y, r: [P(x + r * math.cos(2 * math.pi * i / 20), y + r * math.sin(2 * math.pi * i / 20)) for i in range(20)]
    inner = [rect(97, 80, 103, 240), rect(205, 80, 211, 240),          # yan raylar
             rect(122, 65, 192, 78),                                    # üst orta girinti
             rect(90, 67, 114, 80), rect(194, 67, 214, 80),             # köşe braketleri
             rect(137, 110, 167, 160),                                  # orta pencere
             ring(117, 97, 6.5), ring(190, 97, 6.5), ring(117, 200, 6.5), ring(190, 200, 6.5),   # vidalar
             ring(110, 237, 4), ring(200, 237, 4)]                      # alt köşe delikleri
    dots = [(148, 80), (160, 80), (148, 97), (160, 97), (133, 197), (163, 197), (133, 227), (163, 227)]
    holes = [[*P(x, y), 1.6 * k] for x, y in dots]
    return {'pts': [P(88, 65), P(216, 65), P(216, 245), P(88, 245)], 'holes': holes, 'slots': [], 'inner': inner}

# Montaj bölümleri: uçak montajda üç parça olarak birleştirilir. Parçalar taraflarına göre ayrılır
# (L: sol kanat, R: sağ kanat, orta ve iki tarafa yayılan kapaklar: gövde).
ASSEMBLY_SECTIONS = {'SOL_KANAT': 'Sol Kanat', 'SAG_KANAT': 'Sağ Kanat', 'GOVDE': 'Orta Gövde'}


def layer_of(part):
    """Arayüz katmanı: body (GÖVDE) | cover (KAPAK) | electronics (ELEKTRONİK)."""
    if part['id'] in ELECTRONICS_PARTS:
        return 'electronics'
    return 'cover' if part['group'] == 'cover' else 'body'


def section_of(part):
    if part['group'] == 'electronics' or part['id'] in ELECTRONICS_PARTS:
        return None
    return {'L': 'SOL_KANAT', 'R': 'SAG_KANAT'}.get(part['side'], 'GOVDE')


def mirror(pts):
    return [[AXIS2 - x, y] for x, y in pts][::-1]


def box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def signed_area(pts):
    return sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1])) / 2


def poly_area(pts):
    return abs(signed_area(pts))


def clip(subject, clipper):
    """Sutherland–Hodgman, dışbükey kırpıcı."""
    sgn = 1 if signed_area(clipper) > 0 else -1

    def inside(p, a, b):
        return sgn * ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) >= 0

    def hit(p, q, a, b):
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = p, q, a, b
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
        return [x1 + t * (x2 - x1), y1 + t * (y2 - y1)]

    out = subject
    for i in range(len(clipper)):
        if not out:
            break
        a, b = clipper[i], clipper[(i + 1) % len(clipper)]
        src, out = out, []
        for j in range(len(src)):
            p, q = src[j], src[(j + 1) % len(src)]
            pin, qin = inside(p, a, b), inside(q, a, b)
            if pin:
                out.append(p)
                if not qin:
                    out.append(hit(p, q, a, b))
            elif qin:
                out.append(hit(p, q, a, b))
    return out


def in_poly(pt, pts):
    x, y = pt
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        (xi, yi), (xj, yj) = pts[i], pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _nose_band(y0, y1):
    w = lambda y: 77 * math.sqrt(max(0, (y - 78) / 209))
    ys = [y0 + (y1 - y0) * i / 16 for i in range(17)]
    left = [[920 - w(y), y] for y in ys]
    right = [[920 + w(y), y] for y in ys]
    return left + right[::-1]


# Kanat ızgarası
WING_OUTLINE = [[775, 648], [825, 648], [825, 1770], [818, 1788], [800, 1795], [85, 1795], [92, 1560]]
COLS = [825, 633, 443, 252, 80]          # kökten uca
ROWS = [648, 838, 1030, 1222, 1413, 1602, 1795]
ROW_NAME = 'ABCDEF'

# Birleşik hücreler: hücre kodu → kaç sütun boyunca uca doğru uzandığı
SPANS = {
    'D3': 2,   # D3 + D4 tek parça
}

# Bölünen parçalar: A ve B ayrı yazıcılarda basılır. y: yatay kesim (A üst, B alt)
SPLITS = {
    'KL-C1': 1126,
    'KR-C1': 1126,
}

# Kapaklar. Koordinatlar kapak çizimlerinin 2000 px uzayındadır; IMG ile ölçeklenir.
# Aynı id'yi taşıyan kapaklar tek yazıcıda tek baskıdır ve tek parça sayılır.
# holes: [x, y, r] delikler; slots: [x, y, genişlik, yükseklik] iç kanal/çentikler
IMG = 1 / 1.0345


def _plane_pts(pts):
    """Uçak koordinatlarında verilen şekli kapak çizim uzayına çevirir (build IMG ile geri ölçekler)."""
    return [[x / IMG, y / IMG] for x, y in pts]


def _plane_holes(holes):
    return [[x / IMG, y / IMG, r / IMG] for x, y, r in holes]


def _d_shape(cx, top, bottom, half, corner, n=24):
    """Üstü yarım daire, altı düz ve köşeleri yuvarlatılmış 'D' biçimi (uçak koordinatlarında)."""
    cy = top + half                      # yay merkezi: tepe noktası top'ta
    arc = [[cx - half * math.cos(math.pi * i / n), cy - half * math.sin(math.pi * i / n)] for i in range(n + 1)]
    right = [[cx + half - corner + corner * math.cos(math.pi / 2 * i / 6), bottom - corner + corner * math.sin(math.pi / 2 * i / 6)]
             for i in range(7)]
    left = [[cx - half + corner - corner * math.sin(math.pi / 2 * i / 6), bottom - corner + corner * math.cos(math.pi / 2 * i / 6)]
            for i in range(7)]
    return arc + right + left


def _araba_kapak(x0=120, y0=275, size=140):
    """Araba kapağı: dört delikli kare kapak, araba tutucuyla aynı boyutta
    (delikler kenardan %23 içeride, çap kenarın %14'ü)."""
    inset, r = size * 10 / 43, size * 3 / 43
    x1, y1 = x0 + size, y0 + size
    holes = [[x, y, r] for x in (x0 + inset, x1 - inset) for y in (y0 + inset, y1 - inset)]
    return dict(id='ARABA-KAPAK', side='M', pts=_plane_pts(box(x0, y0, x1, y1)), holes=_plane_holes(holes))


def _araba_tutucu(x0=120, y0=95, size=140):
    """Araba tutucu (küçük parça): üç dikey bölmeli kare, her bölmede iki delik (kullanıcının çiziminden;
    çizim pikselleri x 7–62, y 3–60). Yeri kesinleşene kadar çizimin sol üst boş alanında."""
    k = size / 55
    P = lambda x, y: [x0 + (x - 7) * k, y0 + (y - 3) * k]
    rect = lambda a, b, c, d: [P(a, b), P(c, b), P(c, d), P(a, d)]
    ring = lambda x, y, r: [P(x + r * math.cos(2 * math.pi * i / 16), y + r * math.sin(2 * math.pi * i / 16)) for i in range(16)]
    inner = [rect(23.6, 3, 24.4, 60), rect(40.6, 3, 41.4, 60)]
    inner += [ring(x, y, 2.6) for x, y in ((16, 30), (33, 28), (50, 30), (16, 51), (33, 54), (50, 51))]
    return dict(id='ARABA-TUTUCU', side='M', pts=_plane_pts(rect(7, 3, 62, 60)), inner=[_plane_pts(line) for line in inner])


def _ellipse(cx, cy, rx, ry, n=28):
    return [[cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)] for i in range(n)]
COVERS = [
    # Gövde kapakları
    dict(id='K01', side='M', pts=[[920, 1575], [984, 1575], [988, 1732], [916, 1732]]),
    dict(id='K02', side='M', pts=[[910, 1159], [993, 1159], [997, 1351], [906, 1351]]),
    dict(id='K03', side='M', pts=[[921, 776], [983, 776], [988, 933], [916, 933]]),
    dict(id='K04', side='M', pts=box(881, 567, 1024, 751), scale=0.7,
         holes=[[899, 605, 4], [952, 599, 7], [952, 632, 5], [1005, 604, 4]]),
    # 04 üzerindeki kapak, 07 ile 08 arasındaki kapak ve 08 üzerindeki elips kapak (uçak koordinatlarında)
    dict(id='KAPAK7', side='M', pts=_plane_pts([[885, 945], [955, 945], [959, 1095], [881, 1095]])),
    # KAPAK5: 07 üzerinde dikdörtgen kapak; köşelerde ve üst/alt kenar ortasında bağlantı noktaları
    dict(id='KAPAK5', side='M', pts=_plane_pts(box(846, 318, 996, 508)),
         holes=_plane_holes([[851, 323, 2.2], [991, 323, 2.2], [851, 503, 2.2], [991, 503, 2.2], [921, 322, 2.2], [921, 504, 2.2]])),
    # KAPAK6: 08 üzerinde üstü yay, altı düz 'D' biçimli çift çizgili kapak
    dict(id='KAPAK6', side='M', pts=_plane_pts(_d_shape(920, 156, 256, 50, 12)),
         inner=[_plane_pts(_d_shape(920, 164, 248, 42, 8))]),
    # Flap kapakları: sol ve sağ kanattaki dördü tek baskı
    dict(id='FLAP-KAPAK', side='L', pts=box(577, 1674, 648, 1734), slots=[[583, 1684, 11, 40]]),
    dict(id='FLAP-KAPAK', side='L', pts=box(268, 1674, 340, 1734), slots=[[274, 1684, 11, 40]]),
    dict(id='FLAP-KAPAK', side='R', pts=box(1256, 1674, 1328, 1734),
         slots=[[1286, 1674, 12, 13], [1286, 1721, 12, 13]]),
    dict(id='FLAP-KAPAK', side='R', pts=box(1564, 1674, 1636, 1734),
         slots=[[1594, 1674, 12, 13], [1594, 1721, 12, 13]]),
    # Araba tutucu ve araba kapağı: gerçek yer verilene kadar sol üstte
    _araba_tutucu(),
    _araba_kapak(),
]

# Izgara hücresi / çizim parçası → parça kodu
PART_CODES = {
    'BR-01': '09', 'BR-02': '08',
    'GV-01': '07', 'GV-02': '06', 'GV-03': '05', 'GV-04': '04', 'GV-05': '03', 'GV-06': '02', 'GV-07': '01',
    'YS-L1': 'L20', 'YS-R1': 'R20', 'YS-L2': 'L19', 'YS-R2': 'R19',
    'KL-A1': 'L18', 'KR-A1': 'R18', 'KL-B1': 'L17', 'KR-B1': 'R17', 'KL-B2': 'L16', 'KR-B2': 'R16',
    'KL-C1-A': 'L15A', 'KL-C1-B': 'L15B', 'KR-C1-A': 'R15A', 'KR-C1-B': 'R15B',
    'KL-C2': 'L14', 'KR-C2': 'R14', 'KL-C3': 'L13', 'KR-C3': 'R13',
    'KL-D1': 'L12', 'KR-D1': 'R12', 'KL-D2': 'L11', 'KR-D2': 'R11', 'KL-D3': 'L9-10', 'KR-D3': 'R9-10',
    'KL-E1': 'L8', 'KR-E1': 'R8', 'KL-E2': 'L7', 'KR-E2': 'R7', 'KL-E3': 'L6', 'KR-E3': 'R6',
    'KL-E4': 'L5', 'KR-E4': 'R5',
    'KL-F1': 'L4', 'KR-F1': 'R4', 'KL-F2': 'L3', 'KR-F2': 'R3', 'KL-F3': 'L2', 'KR-F3': 'R2',
    'KL-F4': 'L1', 'KR-F4': 'R1',
    'EL-L1': 'FL2', 'EL-R1': 'FR2', 'EL-L2': 'FL1', 'EL-R2': 'FR1',
}


@lru_cache(maxsize=1)
def build():
    parts = []

    def add(pid, group, side, pts):
        parts.append({'id': pid, 'group': group, 'side': side, 'pts': pts})

    add('BR-01', 'nose', 'M', _nose_band(78, 155))
    add('BR-02', 'nose', 'M', _nose_band(155, 287))

    add('GV-01', 'body', 'M', [[843, 287], [997, 287], [1017, 335], [1017, 540], [825, 540], [825, 335]])
    body_y = [540, 733, 925, 1117, 1310, 1502, 1695]
    for i in range(len(body_y) - 1):
        add(f'GV-0{i + 2}', 'body', 'M', box(825, body_y[i], 1017, body_y[i + 1]))

    strakes = [
        ('1', [[808, 345], [815, 332], [825, 328], [825, 460], [808, 460]]),
        ('2', [[808, 460], [825, 460], [825, 648], [775, 648], [808, 490]]),
    ]
    for n, pts in strakes:
        add(f'YS-L{n}', 'strake', 'L', pts)
        add(f'YS-R{n}', 'strake', 'R', mirror(pts))

    for r in range(len(ROWS) - 1):
        c = 0
        while c < len(COLS) - 1:
            code = f'{ROW_NAME[r]}{c + 1}'
            span = SPANS.get(code, 1)
            outer = COLS[c + span]
            rect = [[outer, ROWS[r]], [COLS[c], ROWS[r]], [COLS[c], ROWS[r + 1]], [outer, ROWS[r + 1]]]
            pts = clip(rect, WING_OUTLINE)
            if len(pts) >= 3 and poly_area(pts) >= 200:
                add(f'KL-{code}', 'wing', 'L', pts)
                add(f'KR-{code}', 'wing', 'R', mirror(pts))
            c += span

    elevons = [
        ('1', [[420, 1793], [420, 1733], [432, 1733], [432, 1715], [715, 1715], [715, 1793]]),
        ('2', [[120, 1715], [405, 1715], [405, 1733], [415, 1733], [415, 1793], [120, 1793]]),
    ]
    for n, pts in elevons:
        add(f'EL-L{n}', 'elevon', 'L', pts)
        add(f'EL-R{n}', 'elevon', 'R', mirror(pts))

    big = 1e4
    for pid, y in SPLITS.items():
        i = next((k for k, p in enumerate(parts) if p['id'] == pid), None)
        if i is None:
            continue
        p = parts[i]
        top = [[-big, -big], [big, -big], [big, y], [-big, y]]
        bottom = [[-big, y], [big, y], [big, big], [-big, big]]
        parts[i:i + 1] = [
            {**p, 'id': f'{pid}-A', 'parent': pid, 'sub': 'A', 'pts': clip(p['pts'], top)},
            {**p, 'id': f'{pid}-B', 'parent': pid, 'sub': 'B', 'pts': clip(p['pts'], bottom)},
        ]

    # Yapısal parçalar tek şekillidir; ortak biçime (shapes) çevrilir ve parça kodlarını alır.
    for p in parts:
        p['shapes'] = [{'pts': p.pop('pts'), 'holes': [], 'slots': []}]
        p['id'] = PART_CODES[p['id']]
        if 'parent' in p:
            p['parent'] = p['id'][:-1]   # L15A → L15

    structure = list(parts)
    by_id = {}
    for c in COVERS:
        # scale: kapak merkezine göre küçültme/büyütme (delikler ve yuvalar dahil)
        k = c.get('scale', 1)
        cx = sum(x for x, _ in c['pts']) / len(c['pts'])
        cy = sum(y for _, y in c['pts']) / len(c['pts'])
        sx = lambda x: (cx + (x - cx) * k) * IMG
        sy = lambda y: (cy + (y - cy) * k) * IMG
        pts = [[sx(x), sy(y)] for x, y in c['pts']]
        mid = [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]
        shape = {
            'pts': pts,
            'holes': [[sx(x), sy(y), r * k * IMG] for x, y, r in c.get('holes', [])],
            'slots': [[sx(x), sy(y), w * k * IMG, hh * k * IMG] for x, y, w, hh in c.get('slots', [])],
            'inner': [[[sx(x), sy(y)] for x, y in line] for line in c.get('inner', [])],   # iç hat (çift çizgi)
        }
        host = next((p['id'] for p in structure if in_poly(mid, p['shapes'][0]['pts'])), None)
        existing = by_id.get(c['id'])
        if existing:
            existing['shapes'].append(shape)
            if host:
                existing['hosts'].append(host)
            if existing['side'] != c['side']:
                existing['side'] = 'LR'
            continue
        part = {'id': c['id'], 'group': 'cover', 'side': c['side'], 'shapes': [shape],
                'hosts': [host] if host else []}
        by_id[c['id']] = part
        parts.append(part)

    parts.append({'id': ELECTRONICS_PART, 'group': 'electronics', 'side': 'M', 'name': 'Elektronik Kat',
                  'shapes': [_electronics_shape()]})

    for p in parts:
        for s in p['shapes']:
            s['pts'] = [[round(x, 1), round(y, 1)] for x, y in s['pts']]
            s['holes'] = [[round(v, 1) for v in h] for h in s['holes']]
            s['slots'] = [[round(v, 1) for v in h] for h in s['slots']]
            s['inner'] = [[[round(x, 1), round(y, 1)] for x, y in line] for line in s.get('inner', [])]
        p['area'] = round(sum(poly_area(s['pts']) for s in p['shapes']))
        p['section'] = section_of(p)
        p['layer'] = layer_of(p)
    return parts


def plane_json():
    return {'viewBox': VIEWBOX, 'groups': GROUPS, 'sections': ASSEMBLY_SECTIONS, 'parts': build()}


def part_ids():
    return [p['id'] for p in build()]
