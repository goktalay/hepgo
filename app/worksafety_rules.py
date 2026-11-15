"""İş Güvenliği — kural kataloğu ve kural motoru (saf hesap; görüntü çıkarımı worksafety_detect'te).

Motor bir kameranın tek karelik GÖZLEMİNİ (kişiler, araçlar, nesneler, KKD, duruş, hız; hepsi 0-1 normalize) ve
kameranın bölgelerini alır, kural başına "kaç birim denetlendi / kaçı ihlalli" döndürür (evaluate). Olay üretimi ayrı
bir onay katmanıdır (Tracker): ihlal art arda `confirm` gözlemde ve `hold` saniye sürerse, aynı kamera + kural + bölge
için `cooldown` saniyede en çok bir olay açılır — tek karelik yanlış tespit olay üretmez.

Risk puanı = şiddet (1-5) × olasılık (1-5); seviye: ≥20 KRİTİK, ≥15 CİDDİ RİSK, ≥10 YÜKSEK, ≥5 ORTA, <5 DÜŞÜK."""
import math

LEVELS = ((20, 'KRİTİK'), (15, 'CİDDİ RİSK'), (10, 'YÜKSEK'), (5, 'ORTA'), (0, 'DÜŞÜK'))
CATS = (('kkd', 'Kişisel koruyucu donanım'), ('zone', 'Bölge ve erişim'), ('behavior', 'Davranış'),
        ('vehicle', 'Araç'), ('object', 'Nesne'), ('ergo', 'Ergonomi'))
VEHICLES = ('forklift', 'car', 'truck', 'bus', 'motorcycle', 'bicycle', 'vehicle')
BAGS = ('backpack', 'handbag', 'suitcase')
KKD = ('hardhat', 'vest', 'gloves', 'goggles', 'shoes', 'apron', 'mask', 'faceshield', 'earmuff', 'harness', 'coverall', 'sleeves')
KKD_NAMES = {'hardhat': 'Baret', 'vest': 'Reflektif yelek', 'gloves': 'Eldiven', 'goggles': 'Koruyucu gözlük',
             'shoes': 'İş ayakkabısı', 'apron': 'Önlük', 'mask': 'Yüz maskesi', 'faceshield': 'Yüz siperi',
             'earmuff': 'Kulak koruyucu', 'harness': 'Emniyet kemeri', 'coverall': 'Koruyucu giysi', 'sleeves': 'Kolluk'}
COLORS = (('red', 'Kırmızı'), ('orange', 'Turuncu'), ('yellow', 'Sarı'), ('green', 'Yeşil'), ('blue', 'Mavi'),
          ('purple', 'Mor'), ('white', 'Beyaz'), ('gray', 'Gri'), ('black', 'Siyah'))

# Bölge türleri: (anahtar, ad, renk, hangi kurallar kullanır, bölge parametreleri)
ZONE_TYPES = (
    ('ppe_zone', 'KKD zorunlu alan', '#0ea5e9', ['no_' + k for k in KKD], ['items']),
    ('restricted', 'Yasak bölge', '#ef4444', ['restricted_entry'], []),
    ('timed', 'Saat kısıtlı bölge', '#f97316', ['after_hours'], ['from', 'to']),
    ('machine', 'Makine bölgesi', '#a855f7', ['machine_unauth'], ['auth_colors']),
    ('count', 'Kişi sayısı bölgesi', '#14b8a6', ['over_count', 'under_count'], ['min', 'max']),
    ('confined', 'Dar alan', '#e11d48', ['confined_crowd'], ['max']),
    ('electrical', 'Elektrik tehlikesi bölgesi', '#eab308', ['electrical_entry'], []),
    ('height', 'Yüksekte çalışma alanı', '#6366f1', ['work_at_height'], []),
    ('collision', 'Çarpışma riski bölgesi', '#dc2626', ['collision_zone'], []),
    ('walkway', 'Yaya yolu', '#22c55e', ['off_walkway'], []),
    ('crossing', 'Yaya geçidi', '#84cc16', ['crossing_obstacle', 'off_walkway'], []),
    ('vehicle_lane', 'Araç yolu', '#3b82f6', ['vehicle_off_lane', 'wrong_way', 'lane_obstacle'], ['dir']),
    ('no_vehicle', 'Araç giremez bölge', '#f43f5e', ['vehicle_no_entry'], []),
    ('ladder', 'Merdiven', '#8b5cf6', ['ladder_3pt'], []),
    ('no_climb', 'Tırmanma yasak alan', '#fb923c', ['climbing'], []),
    ('attended', 'Gözetim gerektiren alan', '#06b6d4', ['unattended'], []),
)
ZONE_KEYS = tuple(z[0] for z in ZONE_TYPES)


def _r(no, key, name, cat, sev, lik, desc, zone=None, zone_req=False, params=None, hold=0, confirm=2, on=True, motion=False):
    return {'no': no, 'key': key, 'name': name, 'cat': cat, 'sev': sev, 'lik': lik, 'desc': desc, 'zone': zone,
            'zone_req': zone_req, 'params': params or {}, 'hold': hold, 'confirm': confirm, 'on': on, 'motion': motion}


def _kkd(no, k, name, sev, lik):
    r = _r(no, 'no_' + k, name, 'kkd', sev, lik,
           f'{KKD_NAMES[k]} takmayan kişi. Yalnız "KKD zorunlu" işaretli kamerada ya da KKD zorunlu alan içinde denetlenir.',
           zone='ppe_zone', confirm=3)
    r['ppe'] = k
    return r


RULES = (
    _kkd(1, 'hardhat', 'Baret yok', 4, 3),
    _kkd(2, 'vest', 'Reflektif yelek yok', 3, 3),
    _kkd(3, 'gloves', 'Eldiven yok', 3, 3),
    _kkd(4, 'goggles', 'Koruyucu gözlük yok', 4, 3),
    _kkd(5, 'shoes', 'İş ayakkabısı yok', 3, 3),
    _kkd(6, 'apron', 'Önlük yok', 2, 3),
    _kkd(7, 'mask', 'Yüz maskesi yok', 3, 3),
    _kkd(8, 'faceshield', 'Yüz siperi yok', 4, 3),
    _kkd(9, 'earmuff', 'Kulak koruyucu yok', 3, 3),
    _kkd(10, 'harness', 'Emniyet kemeri yok', 5, 4),
    _kkd(11, 'coverall', 'Koruyucu giysi yok', 3, 3),
    _kkd(12, 'sleeves', 'Kolluk yok', 2, 3),
    _r(13, 'collision_zone', 'Çarpışma riski bölgesinde kişi ve araç', 'zone', 5, 4,
       'Çarpışma riski bölgesinde aynı anda hem kişi hem araç var.', 'collision', True),
    _r(14, 'machine_unauth', 'Makine bölgesinde yetkisiz kişi', 'zone', 5, 3,
       'Makine bölgesine yetkili kıyafet renginde olmayan kişi girdi (renk tanımlı değilse giren herkes yetkisiz sayılır).',
       'machine', True),
    _r(15, 'over_count', 'Alanda fazla kişi', 'zone', 3, 3, 'Kişi sayısı bölgesinde üst sınırdan fazla kişi.', 'count', True),
    _r(16, 'under_count', 'Alanda eksik kişi', 'zone', 3, 2, 'Kişi sayısı bölgesinde alt sınırdan az kişi.', 'count', True, hold=60),
    _r(17, 'forbidden_object', 'Yasak nesne', 'object', 3, 3,
       'Karede yasak olarak seçilmiş bir nesne görüldü (liste boşsa kural çalışmaz).', params={'objects': []}),
    _r(18, 'restricted_entry', 'Yasak bölgeye giriş', 'zone', 4, 4, 'Yasak bölgede kişi.', 'restricted', True),
    _r(19, 'after_hours', 'İzinsiz saatte giriş', 'zone', 3, 3,
       'Belirlenen saat aralığında kişi görüldü (saat kısıtlı bölge varsa yalnız içinde, yoksa tüm karede).',
       'timed', params={'from': '22:00', 'to': '06:00'}, on=False),
    _r(20, 'unattended', 'Gözetimsiz kalan alan', 'zone', 3, 3,
       'Gözetim gerektiren alanda belirlenen saatlerde kimse yok.', 'attended', True,
       params={'from': '08:00', 'to': '18:00'}, hold=300),
    _r(21, 'climbing', 'Tırmanma', 'behavior', 4, 4,
       'Tırmanma yasak alanda kişi; alan çizilmemişse vücut duruşundan tırmanma hareketi.', 'no_climb', params={'pose': True}, confirm=3),
    _r(22, 'confined_crowd', 'Dar alanda kalabalık', 'zone', 5, 3, 'Dar alanda izin verilenden fazla kişi.', 'confined', True),
    _r(23, 'electrical_entry', 'Elektrik tehlikesi bölgesine giriş', 'zone', 5, 4, 'Elektrik tehlikesi bölgesinde kişi.', 'electrical', True),
    _r(24, 'ladder_3pt', 'Merdivende üç nokta teması yok', 'behavior', 4, 3,
       'Merdivendeki kişinin el ve ayaklarından üçten azı merdivene temas ediyor.', 'ladder', confirm=3),
    _r(25, 'running', 'Koşma', 'behavior', 3, 3, 'Kişi koşuyor (hız eşiği: saniyede boy uzunluğu cinsinden).',
       params={'speed': 1.5}, confirm=1, motion=True),
    _r(26, 'off_walkway', 'Yaya yolunun dışında yürüme', 'behavior', 3, 3,
       'Yaya yolu çizili kamerada yürüyen kişi yaya yolu / geçidi dışında.', 'walkway', True, motion=True),
    _r(27, 'too_close', 'Kişiler birbirine çok yakın', 'behavior', 2, 3,
       'İki kişi arasındaki mesafe boyun belirlenen katından az.', params={'dist': 0.5}, confirm=3, on=False),
    _r(28, 'work_at_height', 'Yüksekte çalışma', 'behavior', 5, 3,
       'Yüksekte çalışma alanında ya da merdivenin üst yarısında kişi.', 'height'),
    _r(29, 'fall', 'Düşen kişi', 'behavior', 5, 4, 'Yere düşmüş / yatan kişi.'),
    _r(30, 'vehicle_off_lane', 'Araç kendi yolunun dışında', 'vehicle', 3, 3,
       'Araç yolu çizili kamerada hareket eden araç yolun dışında.', 'vehicle_lane', True, motion=True),
    _r(31, 'vehicle_no_entry', 'Araç giremez bölgede araç', 'vehicle', 4, 4, 'Araç giremez bölgede araç.', 'no_vehicle', True),
    _r(32, 'vehicle_ped', 'Araç–yaya yakınlığı', 'vehicle', 5, 4,
       'Hareket eden araç ile yaya arasındaki mesafe boyun belirlenen katından az.', params={'dist': 1.0}, motion=True),
    _r(33, 'vehicle_vehicle', 'Araç–araç yakınlığı', 'vehicle', 4, 3,
       'En az biri hareketli iki araç arasındaki boşluk küçük aracın genişliğinin belirlenen katından az.',
       params={'gap': 0.5}, motion=True),
    _r(34, 'wrong_way', 'Ters yönde sürüş', 'vehicle', 4, 3,
       'Yönü tanımlı araç yolunda ters yönde giden araç.', 'vehicle_lane', True, motion=True),
    _r(35, 'lane_obstacle', 'Araç yolunda engel', 'object', 3, 3,
       'Araç yolunda duran, hareketsiz yabancı cisim.', 'vehicle_lane', True, params={'ratio': 0.04}, hold=20),
    _r(36, 'crossing_obstacle', 'Geçitte engel', 'object', 3, 3,
       'Yaya geçidinde duran, hareketsiz yabancı cisim.', 'crossing', True, params={'ratio': 0.04}, hold=20),
    _r(37, 'abandoned_object', 'Bırakılmış nesne', 'object', 2, 3,
       'Çanta / valiz belirlenen süredir yerinde duruyor ve yakınında kimse yok.', params={'seconds': 120}, confirm=1),
    _r(38, 'reba', 'Zorlayıcı duruş (REBA)', 'ergo', 3, 3,
       'Tüm vücut duruş puanı (REBA, kameradan 2B tahmin) eşiğin üstünde.', params={'min': 8}, hold=10, confirm=3),
    _r(39, 'rula', 'Üst vücut ergonomi riski (RULA)', 'ergo', 3, 3,
       'Üst vücut duruş puanı (RULA, kameradan 2B tahmin) eşiğin üstünde.', params={'min': 6}, hold=10, confirm=3),
)
BY_KEY = {r['key']: r for r in RULES}


def level(risk):
    return next(name for lim, name in LEVELS if risk >= lim)


def effective(cfg):
    """Katalog varsayılanları + kullanıcının kural ayarları → {anahtar: kural}."""
    user = (cfg or {}).get('rules') or {}
    cool = float((cfg or {}).get('cooldown') or 300)
    out = {}
    for r in RULES:
        u = user.get(r['key']) or {}
        e = dict(r)
        e['enabled'] = bool(u['enabled']) if 'enabled' in u else r['on']
        e['sev'] = min(5, max(1, int(u.get('sev') or r['sev'])))
        e['lik'] = min(5, max(1, int(u.get('lik') or r['lik'])))
        e['params'] = {**r['params'], **(u.get('params') or {})}
        e['cooldown'] = float(u.get('cooldown') or cool)
        e['risk'] = e['sev'] * e['lik']
        e['level'] = level(e['risk'])
        out[r['key']] = e
    return out


def model_ok(rule, caps, cam=None):
    """Kuralın gerektirdiği model var mı? → (bool, eksik açıklaması). cam verilirse bölgeyle karşılanan gerekler sayılır."""
    caps = caps or {}
    ppe, classes = set(caps.get('ppe') or []), set(caps.get('classes') or [])
    zt = {z.get('type') for z in ((cam or {}).get('zones') or [])}
    if not caps.get('objects'):
        return False, 'Nesne modeli (yolox_s.onnx) yok'
    k = rule.get('ppe')
    if k:
        if k + ':neg' in ppe or k in ppe:
            return True, None
        return False, f'{KKD_NAMES[k]} sınıfını tanıyan KKD modeli yok'
    key = rule['key']
    if key in ('reba', 'rula') and not caps.get('pose'):
        return False, 'Duruş modeli (rtmpose_s.onnx) yok'
    if key == 'climbing' and not caps.get('pose') and 'no_climb' not in zt:
        return False, 'Duruş modeli yok (tırmanma yasak alan çizilirse model gerekmez)'
    if key == 'ladder_3pt':
        if not caps.get('pose'):
            return False, 'Duruş modeli (rtmpose_s.onnx) yok'
        if 'ladder' not in classes and 'ladder' not in zt:
            return False, 'Merdiven sınıfı yok (merdiven bölgesi çizilirse gerekmez)'
    if key == 'work_at_height' and 'ladder' not in classes and 'height' not in zt:
        return False, 'Merdiven sınıfı yok (yüksekte çalışma alanı çizilirse gerekmez)'
    if key == 'fall' and 'fall' not in classes and not caps.get('pose'):
        return False, 'Düşme sınıfı ya da duruş modeli yok'
    return True, None


def cam_rules(cam, rules):
    """Bu kamerada etkin kural anahtarları (kamera kendi listesini verdiyse onunla kesişim)."""
    only = cam.get('rules')
    return [k for k, r in rules.items() if r['enabled'] and (only is None or k in only)]


def needs(cam, rules, caps):
    """Kamera için hangi çıkarımlar gerekli? (işleyici gereksiz modeli çalıştırmaz)"""
    keys = cam_rules(cam, rules)
    zt = {z.get('type') for z in (cam.get('zones') or [])}
    act = [k for k in keys if model_ok(rules[k], caps, cam)[0] and (not rules[k]['zone_req'] or rules[k]['zone'] in zt)]
    kkd_on = any(rules[k].get('ppe') for k in act) and (cam.get('ppe') or 'ppe_zone' in zt)
    return {
        'active': act,
        'ppe': bool(kkd_on or (set(act) & {'fall', 'ladder_3pt', 'work_at_height'})),
        'pose': bool(set(act) & {'reba', 'rula', 'fall', 'ladder_3pt'} or ('climbing' in act and 'no_climb' not in zt)),
        'motion': any(rules[k]['motion'] for k in act),
        'static': bool(set(act) & {'lane_obstacle', 'crossing_obstacle'}),
        'color': 'machine_unauth' in act and any(z.get('type') == 'machine' and (z.get('params') or {}).get('auth_colors')
                                                 for z in (cam.get('zones') or [])),
    }


# ---------------------------------------------------------------- geometri
def in_poly(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-9) + x1:
            inside = not inside
    return inside


def center(b):
    return (b[0] + b[2] / 2, b[1] + b[3] / 2)


def foot(b):
    return (b[0] + b[2] / 2, b[1] + b[3])


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    u = a[2] * a[3] + b[2] * b[3] - inter
    return inter / u if u > 0 else 0.0


def _in_box(pt, b, pad=0.0):
    return b[0] - b[2] * pad <= pt[0] <= b[0] + b[2] * (1 + pad) and b[1] - b[3] * pad <= pt[1] <= b[1] + b[3] * (1 + pad)


def _dist(a, b, aspect):
    return math.hypot((a[0] - b[0]) * aspect, a[1] - b[1])


def _box_gap(a, b, aspect):
    """İki kutu arasındaki boşluk (y birimi); örtüşüyorsa 0."""
    dx = max(0.0, max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2])) * aspect
    dy = max(0.0, max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3]))
    return math.hypot(dx, dy)


def _pt_box_dist(pt, b, aspect):
    dx = max(b[0] - pt[0], 0.0, pt[0] - (b[0] + b[2])) * aspect
    dy = max(b[1] - pt[1], 0.0, pt[1] - (b[1] + b[3]))
    return math.hypot(dx, dy)


def _minutes(s, default=0):
    try:
        hh, mm = str(s).split(':')[:2]
        return (int(hh) * 60 + int(mm)) % 1440
    except (ValueError, TypeError):
        return default


def in_clock(now_min, a, b):
    """now_min (0-1439) [a, b) aralığında mı? Aralık gece yarısını aşabilir; a == b tüm gün."""
    a, b = _minutes(a), _minutes(b)
    if a == b:
        return True
    return a <= now_min < b if a < b else (now_min >= a or now_min < b)


# ---------------------------------------------------------------- gözlem hazırlığı (işleyici çağırır)
def assign_ppe(persons, dets, inferred=()):
    """KKD tespitlerini kişilere bağlar: p['ppe'][anahtar] = True (takılı) / False (eksik).
    Tespit merkezi kişinin kutusundaysa ve birden çok kişi uyuyorsa merkezi en yakın olana yazılır. `inferred`: yalnız
    "takılı" sınıfı olan anahtarlar — yeterince büyük görünen kişide tespit yoksa eksik sayılır."""
    for p in persons:
        p.setdefault('ppe', {})
    for d in dets:
        if not d.get('key'):
            continue
        c = center(d['box'])
        best, bd = None, 9.0
        for p in persons:
            if _in_box(c, p['box'], 0.05):
                dd = math.hypot(c[0] - center(p['box'])[0], c[1] - center(p['box'])[1])
                if dd < bd:
                    best, bd = p, dd
        if best is None:
            continue
        cur = best['ppe'].get(d['key'])
        val = not d['neg']
        if cur is None or (cur is True and val is False and d['score'] >= 0.5):
            best['ppe'][d['key']] = val
    for k in inferred:
        for p in persons:
            if k not in p['ppe'] and p['box'][3] >= 0.35:
                p['ppe'][k] = False
    return persons


def match_motion(cur, prev, dt, aspect):
    """Şimdiki ve ~1 sn önceki tespitleri eşleştirip hız yazar: o['vel'] (norm/sn, x en-boy düzeltmeli) ve o['speed'] (boy/sn)."""
    used = set()
    for o in cur:
        o['speed'] = o['vel'] = None
        if dt <= 0.2:
            continue
        c, h = center(o['box']), o['box'][3] or 1e-6
        best, bd = None, 1.5 * h
        for i, q in enumerate(prev):
            if i in used or q['cls'] != o['cls']:
                continue
            ratio = (q['box'][3] or 1e-6) / h
            if not 0.6 <= ratio <= 1.6:
                continue
            d = _dist(c, center(q['box']), aspect)
            if d < bd:
                best, bd = i, d
        if best is None:
            continue
        used.add(best)
        qc = center(prev[best]['box'])
        o['vel'] = ((c[0] - qc[0]) * aspect / dt, (c[1] - qc[1]) / dt)
        o['speed'] = math.hypot(*o['vel']) / h
    return cur


def dominant_color(bgr):
    """Kıyafet (gövde) kırpığının baskın rengi → COLORS anahtarı (numpy dizisi; OpenCV yalnız burada gerekir)."""
    import cv2
    if bgr is None or bgr.size < 30:
        return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    h, s, v = hsv[:, 0].astype(int), hsv[:, 1].astype(int), hsv[:, 2].astype(int)
    chroma = (s >= 70) & (v >= 60)
    counts = {'black': int(((v < 60)).sum()), 'white': int(((s < 45) & (v >= 170)).sum()),
              'gray': int(((s < 70) & (v >= 60) & ~((s < 45) & (v >= 170))).sum())}
    for name, lo, hi in (('orange', 8, 20), ('yellow', 20, 33), ('green', 33, 85), ('blue', 85, 130), ('purple', 130, 170)):
        counts[name] = int((chroma & (h >= lo) & (h < hi)).sum())
    counts['red'] = int((chroma & ((h < 8) | (h >= 170))).sum())
    return max(counts, key=counts.get)


class StaticScene:
    """Hareketsiz yabancı cisim: iki hızda güncellenen gri arka plan. Yeni gelip duran cisim hızlı arka plana karışır
    ama yavaş arka plandan uzun süre ayrı kalır → "durağan" maske. Kişiler maskeden çıkarılır."""
    W, H = 160, 90

    def __init__(self):
        self.fast = self.slow = None
        self.t = self.t0 = 0.0
        self.n = 0
        self.mask = None

    def update(self, frame_bgr, t, person_boxes=()):
        import cv2
        import numpy as np
        g = cv2.cvtColor(cv2.resize(frame_bgr, (self.W, self.H), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
        g = cv2.GaussianBlur(g, (5, 5), 0)
        if self.fast is None or t - self.t > 120:      # ilk kare ya da uzun kesinti: baştan
            self.fast, self.slow, self.t, self.t0, self.n, self.mask = g.copy(), g.copy(), t, t, 0, None
            return None
        dt, self.t = max(0.05, t - self.t), t
        g = g + (float(np.median(self.slow)) - float(np.median(g)))    # genel aydınlatma kayması
        self.fast += (g - self.fast) * (1 - math.exp(-dt / 20.0))
        self.n += 1
        m = (np.abs(g - self.slow) > 28) & (np.abs(g - self.fast) < 12)
        for b in person_boxes:
            x1, y1 = int(max(0, b[0] - 0.02) * self.W), int(max(0, b[1] - 0.02) * self.H)
            x2, y2 = int(min(1, b[0] + b[2] + 0.02) * self.W) + 1, int(min(1, b[1] + b[3] + 0.02) * self.H) + 1
            m[y1:y2, x1:x2] = False
        keep = ~m      # durağan cisim yavaş arka plana karışmasın diye o piksellerde yavaş model dondurulur (en çok 10 dk)
        a = 1 - math.exp(-dt / 600.0)
        self.slow[keep] += (g[keep] - self.slow[keep]) * a
        self.slow[m] += (g[m] - self.slow[m]) * (a * 0.1)
        self.mask = m
        return m

    def ready(self):
        return self.mask is not None and self.n >= 5 and self.t - self.t0 >= 60

    def ratio(self, poly):
        """Poligon içindeki durağan piksel oranı (0-1)."""
        import cv2
        import numpy as np
        if self.mask is None or len(poly) < 3:
            return 0.0
        zm = np.zeros((self.H, self.W), np.uint8)
        cv2.fillPoly(zm, [np.int32([[p[0] * self.W, p[1] * self.H] for p in poly])], 1)
        area = int(zm.sum())
        return float((self.mask & (zm > 0)).sum()) / area if area else 0.0


# ---------------------------------------------------------------- ergonomi (REBA / RULA, 2B tahmin)
_REBA_A = (((1, 2, 3, 4), (2, 3, 4, 5), (2, 4, 5, 6), (3, 5, 6, 7), (4, 6, 7, 8)),
           ((1, 2, 3, 4), (3, 4, 5, 6), (4, 5, 6, 7), (5, 6, 7, 8), (6, 7, 8, 9)),
           ((3, 3, 5, 6), (4, 5, 6, 7), (5, 6, 7, 8), (6, 7, 8, 9), (7, 8, 9, 9)))
_REBA_B = (((1, 2, 2), (1, 2, 3), (3, 4, 5), (4, 5, 5), (6, 7, 8), (7, 8, 8)),
           ((1, 2, 3), (2, 3, 4), (4, 5, 5), (5, 6, 7), (7, 8, 8), (8, 9, 9)))
_REBA_C = ((1, 1, 1, 2, 3, 3, 4, 5, 6, 7, 7, 7), (1, 2, 2, 3, 4, 4, 5, 6, 6, 7, 7, 8), (2, 3, 3, 3, 4, 5, 6, 7, 7, 8, 8, 8),
           (3, 4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9), (4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9, 9), (6, 6, 6, 7, 8, 8, 9, 9, 10, 10, 10, 10),
           (7, 7, 7, 8, 9, 9, 9, 10, 10, 11, 11, 11), (8, 8, 8, 9, 10, 10, 10, 10, 10, 11, 11, 11),
           (9, 9, 9, 10, 10, 10, 11, 11, 11, 12, 12, 12), (10, 10, 10, 11, 11, 11, 11, 12, 12, 12, 12, 12),
           (11, 11, 11, 11, 12, 12, 12, 12, 12, 12, 12, 12), (12,) * 12)
_RULA_A = ((1, 2, 2), (2, 3, 3), (3, 3, 4), (4, 4, 4), (5, 5, 6), (7, 8, 9))       # bilek 1, bilek dönüşü 1
_RULA_B = ((1, 2, 3, 5, 6, 7), (2, 2, 4, 5, 6, 7), (3, 3, 4, 5, 6, 7), (5, 5, 6, 7, 7, 8), (7, 7, 7, 8, 8, 8), (8, 8, 8, 8, 9, 9))  # bacak 1
_RULA_C = ((1, 2, 3, 3, 4, 5, 5), (2, 2, 3, 4, 4, 5, 5), (3, 3, 3, 4, 4, 5, 6), (3, 3, 3, 4, 5, 6, 6), (4, 4, 4, 5, 6, 7, 7),
           (4, 4, 5, 6, 6, 7, 7), (5, 5, 6, 6, 7, 7, 7), (5, 5, 6, 7, 7, 7, 7))


def _ang(a, b):
    na, nb = math.hypot(*a), math.hypot(*b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (na * nb)))))


def _vec(a, b):
    return (b[0] - a[0], b[1] - a[1])


def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def posture(kpts, aspect=1.0, min_conf=0.4):
    """17 eklem (COCO sırası, [x, y, güven]) → eklem açıları (derece) ya da None (gövde görünmüyorsa)."""
    if not kpts or len(kpts) < 17:
        return None
    k = [(p[0] * aspect, p[1], p[2]) for p in kpts]
    ok = lambda *i: all(k[j][2] >= min_conf for j in i)   # noqa: E731
    if not ok(5, 6, 11, 12):
        return None
    sh, hip = _mid(k[5], k[6]), _mid(k[11], k[12])
    trunk_v = _vec(hip, sh)
    if math.hypot(*trunk_v) < 1e-6:
        return None
    out = {'trunk': _ang(trunk_v, (0, -1)), 'neck': None, 'upper': None, 'lower': None, 'knee': None}
    head = _mid(k[3], k[4]) if ok(3, 4) else (k[0][:2] if ok(0) else None)
    if head:
        out['neck'] = _ang(_vec(sh, head), trunk_v)
    down = _vec(sh, hip)
    for s, e, w in ((5, 7, 9), (6, 8, 10)):
        if ok(s, e):
            u = _vec(k[s], k[e])
            out['upper'] = max(out['upper'] or 0.0, _ang(u, down))
            if ok(w):
                fl = _ang(_vec(k[e], k[w]), u)
                if out['lower'] is None or abs(fl - 80) > abs(out['lower'] - 80):
                    out['lower'] = fl
    for hp, kn, an in ((11, 13, 15), (12, 14, 16)):
        if ok(hp, kn, an):
            out['knee'] = max(out['knee'] or 0.0, _ang(_vec(k[kn], k[an]), _vec(k[hp], k[kn])))
    return out


def _upper_score(a):
    return 1 if a <= 20 else 2 if a <= 45 else 3 if a <= 90 else 4


def reba(p):
    """Duruş açılarından REBA (bilek 1; yük, kavrama, aktivite 0 kabul edilir) → puan ya da None."""
    if not p or p.get('upper') is None:
        return None
    t = p['trunk']
    trunk = 1 if t <= 5 else 2 if t <= 20 else 3 if t <= 60 else 4
    neck = 1 if (p.get('neck') or 0) <= 20 else 2
    kn = p.get('knee') or 0
    legs = 1 + (2 if kn > 60 else 1 if kn > 30 else 0)
    upper = _upper_score(p['upper'])
    lower = 1 if p.get('lower') is None or 60 <= p['lower'] <= 100 else 2
    a = _REBA_A[neck - 1][trunk - 1][legs - 1]
    b = _REBA_B[lower - 1][upper - 1][0]
    return _REBA_C[min(a, 12) - 1][min(b, 12) - 1]


def rula(p):
    """Duruş açılarından RULA (bilek 1, bilek dönüşü 1, bacak 1; kas kullanımı / yük 0) → puan ya da None."""
    if not p or p.get('upper') is None:
        return None
    upper = _upper_score(p['upper'])
    lower = 1 if p.get('lower') is None or 60 <= p['lower'] <= 100 else 2
    n = p.get('neck') or 0
    neck = 1 if n <= 10 else 2 if n <= 20 else 3
    t = p['trunk']
    trunk = 1 if t <= 5 else 2 if t <= 20 else 3 if t <= 60 else 4
    a = _RULA_A[upper - 1][lower - 1]
    b = _RULA_B[neck - 1][trunk - 1]
    return _RULA_C[min(a, 8) - 1][min(b, 7) - 1]


def _lying(p, aspect):
    """Duruştan yatma: omuz-kalça ekseni yataya yakın ve kutu enine."""
    k = p.get('kpts')
    b = p['box']
    if not k or b[3] <= 0 or (b[2] * aspect) / b[3] < 1.1:
        return False
    if min(k[5][2], k[6][2], k[11][2], k[12][2]) < 0.4:
        return False
    sh, hip = _mid(k[5], k[6]), _mid(k[11], k[12])
    return _ang(((sh[0] - hip[0]) * aspect, sh[1] - hip[1]), (0, -1)) > 60 and \
        _ang(((sh[0] - hip[0]) * aspect, sh[1] - hip[1]), (0, 1)) > 60


def _climbing_pose(p):
    k = p.get('kpts')
    if not k:
        return False
    c = lambda *i: all(k[j][2] >= 0.4 for j in i)   # noqa: E731
    if not c(5, 6, 9, 10, 11, 12):
        return False
    sh_y, hip_y = (k[5][1] + k[6][1]) / 2, (k[11][1] + k[12][1]) / 2
    torso = hip_y - sh_y
    if torso <= 0 or not (k[9][1] < sh_y and k[10][1] < sh_y):     # iki el de omuz üstünde
        return False
    for kn, an in ((13, 15), (14, 16)):                            # bir diz kalça hizasına çekilmiş
        if c(kn) and k[kn][1] - hip_y < 0.25 * torso and (not c(an) or k[an][1] > k[kn][1]):
            return True
    return False


# ---------------------------------------------------------------- değerlendirme
def evaluate(obs, cam, rules, caps, mem=None):
    """Tek gözlem → [{'rule', 'zone', 'zone_name', 'slot', 'checks', 'viol', 'boxes', 'detail', 'meta'}].
    obs: {'t', 'aspect', 'clock' (dakika), 'persons': [{'box', 'ppe', 'kpts', 'speed', 'vel', 'color'}],
          'vehicles': [{'box', 'cls', 'speed', 'vel'}], 'objects': [{'cls', 'box'}], 'ladders': [box], 'falls': [box],
          'static': {bölge id: oran} | None}
    mem: kameraya özel kalıcı sözlük (bırakılmış nesne takibi)."""
    mem = mem if mem is not None else {}
    aspect = obs.get('aspect') or 1.0
    P, V, O = obs.get('persons') or [], obs.get('vehicles') or [], obs.get('objects') or []
    zones = [z for z in (cam.get('zones') or []) if len(z.get('points') or []) >= 3]
    Z = {}
    for z in zones:
        Z.setdefault(z.get('type'), []).append(z)
    act = set(needs(cam, rules, caps)['active'])
    out = []

    def add(key, checks, viol_boxes, detail='', zone=None, slot='', meta=None, n=None):
        if key in act and checks > 0:
            out.append({'rule': key, 'zone': zone.get('id') if zone else None, 'zone_name': zone.get('name') if zone else None,
                        'slot': slot, 'checks': int(checks), 'viol': len(viol_boxes) if n is None else int(n),
                        'boxes': [list(b) for b in viol_boxes][:12], 'detail': detail, 'meta': meta or {}})

    def inside(z, items, pt=foot):
        return [o for o in items if in_poly(pt(o['box']), z['points'])]

    # ---- 1-12 KKD
    ppe_zones = Z.get('ppe_zone') or []
    if cam.get('ppe') or ppe_zones:
        for r in RULES[:12]:
            k = r['ppe']
            if r['key'] not in act:
                continue
            scope = []
            for p in P:
                if p['box'][3] < 0.12:      # çok uzaktaki kişide KKD seçilemez
                    continue
                if cam.get('ppe'):
                    scope.append(p)
                else:
                    for z in ppe_zones:
                        items = (z.get('params') or {}).get('items') or []
                        if (not items or k in items) and in_poly(foot(p['box']), z['points']):
                            scope.append(p)
                            break
            known = [p for p in scope if (p.get('ppe') or {}).get(k) is not None]
            bad = [p['box'] for p in known if p['ppe'][k] is False]
            add(r['key'], len(known), bad, f'{len(bad)} kişide {KKD_NAMES[k].lower()} yok' if bad else '')

    # ---- 13 çarpışma riski bölgesinde kişi ve araç
    for z in Z.get('collision') or []:
        ps, vs = inside(z, P), inside(z, V)
        both = bool(ps and vs)
        add('collision_zone', 1, [o['box'] for o in ps + vs] if both else [], f'{len(ps)} kişi, {len(vs)} araç' if both else '', z, n=int(both))
    # ---- 14 makine bölgesinde yetkisiz kişi
    for z in Z.get('machine') or []:
        ps = inside(z, P)
        auth = (z.get('params') or {}).get('auth_colors') or []
        bad = [p['box'] for p in ps if not auth or (p.get('color') is not None and p['color'] not in auth)]
        add('machine_unauth', len(ps), bad, f'{len(bad)} yetkisiz kişi' if bad else '', z)
    # ---- 15 / 16 kişi sayısı
    for z in Z.get('count') or []:
        ps = inside(z, P)
        prm = z.get('params') or {}
        mx, mn = prm.get('max'), prm.get('min')
        if mx not in (None, ''):
            over = len(ps) > int(mx)
            add('over_count', 1, [p['box'] for p in ps] if over else [], f'{len(ps)} kişi (en çok {int(mx)})' if over else '', z, n=int(over))
        if mn not in (None, '') and int(mn) > 0:
            under = len(ps) < int(mn)
            add('under_count', 1, [], f'{len(ps)} kişi (en az {int(mn)})' if under else '', z, n=int(under))
    # ---- 17 yasak nesne
    banned = set(rules['forbidden_object']['params'].get('objects') or [])
    if banned:
        hit = [o for o in O + V if o['cls'] in banned]
        add('forbidden_object', 1, [o['box'] for o in hit], ', '.join(sorted({o['cls'] for o in hit})))
    # ---- 18 / 23 yasak ve elektrik bölgesi
    for key, zt, text in (('restricted_entry', 'restricted', 'yasak bölgede'), ('electrical_entry', 'electrical', 'elektrik tehlikesi bölgesinde')):
        for z in Z.get(zt) or []:
            ps = inside(z, P)
            add(key, max(1, len(P)), [p['box'] for p in ps], f'{len(ps)} kişi {text}' if ps else '', z)
    # ---- 19 izinsiz saat
    clock = obs.get('clock')
    if clock is not None:
        rp = rules['after_hours']['params']
        tz = Z.get('timed') or []
        if tz:
            for z in tz:
                zp = z.get('params') or {}
                if in_clock(clock, zp.get('from') or rp.get('from'), zp.get('to') or rp.get('to')):
                    ps = inside(z, P)
                    add('after_hours', max(1, len(P)), [p['box'] for p in ps], f'{len(ps)} kişi' if ps else '', z)
        elif in_clock(clock, rp.get('from'), rp.get('to')):
            add('after_hours', max(1, len(P)), [p['box'] for p in P], f'{len(P)} kişi' if P else '')
        # ---- 20 gözetimsiz alan
        up = rules['unattended']['params']
        if in_clock(clock, up.get('from'), up.get('to')):
            for z in Z.get('attended') or []:
                empty = not inside(z, P)
                add('unattended', 1, [], 'alanda kimse yok' if empty else '', z, n=int(empty))
    # ---- 21 tırmanma
    nz = Z.get('no_climb') or []
    if nz:
        for z in nz:
            ps = inside(z, P, center)
            add('climbing', max(1, len(P)), [p['box'] for p in ps], f'{len(ps)} kişi tırmanma yasak alanda' if ps else '', z)
    elif rules['climbing']['params'].get('pose') and caps.get('pose'):
        seen = [p for p in P if p.get('kpts')]
        cl = [p['box'] for p in seen if _climbing_pose(p)]
        add('climbing', len(seen), cl, 'tırmanma hareketi' if cl else '')
    # ---- 22 dar alanda kalabalık
    for z in Z.get('confined') or []:
        ps = inside(z, P)
        mx = int((z.get('params') or {}).get('max') or 1)
        over = len(ps) > mx
        add('confined_crowd', 1, [p['box'] for p in ps] if over else [], f'{len(ps)} kişi (en çok {mx})' if over else '', z, n=int(over))
    # ---- 24 merdivende üç nokta teması
    ladders = [{'box': b, 'zone': None} for b in (obs.get('ladders') or [])]
    for z in Z.get('ladder') or []:
        xs, ys = [p[0] for p in z['points']], [p[1] for p in z['points']]
        ladders.append({'box': [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)], 'zone': z})
    for ld in ladders:
        on = [p for p in P if p.get('kpts') and _in_box(center(p['box']), ld['box'], 0.15)]
        bad = []
        for p in on:
            pts = [p['kpts'][i] for i in (9, 10, 15, 16)]
            if sum(1 for q in pts if q[2] >= 0.3) < 3:
                continue        # eller / ayaklar görünmüyor: karar verilmez
            if sum(1 for q in pts if q[2] >= 0.3 and _in_box(q, ld['box'], 0.12)) < 3:
                bad.append(p['box'])
        add('ladder_3pt', len(on), bad, 'üç nokta teması yok' if bad else '', ld['zone'])
    # ---- 25 koşma
    moving = [p for p in P if p.get('speed') is not None]
    thr = float(rules['running']['params'].get('speed') or 1.5)
    run = [p for p in moving if p['speed'] >= thr and p['box'][3] >= 0.1]
    add('running', len(moving), [p['box'] for p in run], f"hız {max(p['speed'] for p in run):.1f} boy/sn" if run else '')
    # ---- 26 yaya yolu dışında yürüme
    wz = (Z.get('walkway') or []) + (Z.get('crossing') or [])
    if Z.get('walkway'):
        walk = [p for p in moving if p['speed'] >= 0.3]
        off = [p['box'] for p in walk if not any(in_poly(foot(p['box']), z['points']) for z in wz)]
        add('off_walkway', len(walk), off, f'{len(off)} kişi yaya yolu dışında' if off else '')
    # ---- 27 kişiler birbirine çok yakın
    if len(P) >= 2:
        dmul = float(rules['too_close']['params'].get('dist') or 0.5)
        close = {}
        for i in range(len(P)):
            for j in range(i + 1, len(P)):
                a, b = P[i]['box'], P[j]['box']
                if min(a[3], b[3]) < 0.12 or not 0.6 <= a[3] / (b[3] or 1e-6) <= 1.6:
                    continue
                if _dist(foot(a), foot(b), aspect) < dmul * (a[3] + b[3]) / 2:
                    close[i], close[j] = a, b
        add('too_close', len(P), list(close.values()), f'{len(close)} kişi birbirine çok yakın' if close else '')
    # ---- 28 yüksekte çalışma
    hz = Z.get('height') or []
    high = {}
    for i, p in enumerate(P):
        f = foot(p['box'])
        if any(in_poly(f, z['points']) for z in hz):
            high[i] = p['box']
        for b in obs.get('ladders') or []:
            if b[0] <= f[0] <= b[0] + b[2] and b[1] <= f[1] <= b[1] + b[3] * 0.5:
                high[i] = p['box']
    if hz or obs.get('ladders'):
        add('work_at_height', max(1, len(P)), list(high.values()), f'{len(high)} kişi yüksekte' if high else '', hz[0] if len(hz) == 1 else None)
    # ---- 29 düşen kişi
    falls = list(obs.get('falls') or [])
    fallen = []
    for p in P:
        if _lying(p, aspect) or any(iou(p['box'], f) > 0.3 or _in_box(center(f), p['box']) for f in falls):
            fallen.append(p['box'])
    fallen += [f for f in falls if not any(iou(f, b) > 0.3 or _in_box(center(f), b) for b in fallen)]
    add('fall', max(1, len(P)), fallen, f'{len(fallen)} kişi yerde' if fallen else '')
    # ---- 30 / 34 araç yolu, 31 araç giremez bölge
    lanes = Z.get('vehicle_lane') or []
    mv = [v for v in V if (v.get('speed') or 0) >= 0.15]
    if lanes:
        off = [v['box'] for v in mv if not any(in_poly(foot(v['box']), z['points']) for z in lanes)]
        add('vehicle_off_lane', len(mv), off, f'{len(off)} araç yol dışında' if off else '')
        for z in lanes:
            d = (z.get('params') or {}).get('dir')
            if d in (None, ''):
                continue
            dv = (math.cos(math.radians(float(d))), math.sin(math.radians(float(d))))
            ins = [v for v in mv if v.get('vel') and in_poly(foot(v['box']), z['points'])]
            wrong = [v['box'] for v in ins if (v['vel'][0] * dv[0] + v['vel'][1] * dv[1]) / (math.hypot(*v['vel']) or 1e-9) < -0.5]
            add('wrong_way', len(ins), wrong, f'{len(wrong)} araç ters yönde' if wrong else '', z)
    for z in Z.get('no_vehicle') or []:
        vs = inside(z, V)
        add('vehicle_no_entry', max(1, len(V)), [v['box'] for v in vs], f'{len(vs)} araç' if vs else '', z)
    # ---- 32 araç–yaya, 33 araç–araç yakınlığı
    if mv and P:
        dmul = float(rules['vehicle_ped']['params'].get('dist') or 1.0)
        near = {}
        for v in mv:
            for i, p in enumerate(P):
                if p['box'][3] >= 0.08 and iou(p['box'], v['box']) < 0.6 and \
                        _pt_box_dist(foot(p['box']), v['box'], aspect) < dmul * p['box'][3]:
                    near[i] = p['box']
                    near[id(v)] = v['box']
        add('vehicle_ped', len(P), list(near.values()), 'araç yayaya çok yakın' if near else '', n=sum(1 for k in near if k < len(P)))
    if len(V) >= 2 and mv:
        gmul = float(rules['vehicle_vehicle']['params'].get('gap') or 0.5)
        near = {}
        for i in range(len(V)):
            for j in range(i + 1, len(V)):
                a, b = V[i], V[j]
                if not ((a.get('speed') or 0) >= 0.15 or (b.get('speed') or 0) >= 0.15) or iou(a['box'], b['box']) > 0.6:
                    continue
                if _box_gap(a['box'], b['box'], aspect) < gmul * min(a['box'][2], b['box'][2]) * aspect:
                    near[i], near[j] = a['box'], b['box']
        add('vehicle_vehicle', len(V), list(near.values()), 'araçlar birbirine çok yakın' if near else '')
    # ---- 35 / 36 araç yolunda / geçitte engel
    st = obs.get('static')
    if st is not None:
        for key, zt in (('lane_obstacle', 'vehicle_lane'), ('crossing_obstacle', 'crossing')):
            thr = float(rules[key]['params'].get('ratio') or 0.04)
            for z in Z.get(zt) or []:
                ratio = st.get(z.get('id'))
                if ratio is None:
                    continue
                hit = ratio >= thr
                add(key, 1, [], f'bölgenin %{ratio * 100:.0f} kadarı hareketsiz cisimle kapalı' if hit else '', z, n=int(hit))
    # ---- 37 bırakılmış nesne
    t = obs.get('t') or 0.0
    bags = [o for o in O if o['cls'] in BAGS]
    tracks = mem.setdefault('bags', [])
    for tr in tracks:
        tr['hit'] = False
    for o in bags:
        c = center(o['box'])
        tr = next((x for x in tracks if not x['hit'] and _dist(c, x['c'], aspect) < 0.06), None)
        if tr is None:
            tr = {'c': c, 'since': t, 'alone': t}
            tracks.append(tr)
        tr.update(hit=True, last=t, box=o['box'], cls=o['cls'])
        size = max(o['box'][3], 0.05)
        if any(_dist(foot(p['box']), c, aspect) < 2 * max(p['box'][3], size) for p in P):
            tr['alone'] = t       # yanında biri var: "yalnız" süresi baştan
    mem['bags'] = tracks = [x for x in tracks if t - x.get('last', t) < 30]
    secs = float(rules['abandoned_object']['params'].get('seconds') or 120)
    left = [x for x in tracks if x.get('hit') and t - x['alone'] >= secs]
    add('abandoned_object', max(1, len(bags)) if (bags or tracks) else 0, [x['box'] for x in left],
        f"{', '.join(sorted({x['cls'] for x in left}))} {int(max(t - x['alone'] for x in left) // 60)} dk'dır sahipsiz" if left else '')
    # ---- 38 / 39 ergonomi
    scored = []
    for p in P:
        if p.get('kpts') and p['box'][3] >= 0.25:
            pp = posture(p['kpts'], aspect)
            if pp and pp.get('upper') is not None:
                scored.append((p, reba(pp), rula(pp)))
    for key, idx in (('reba', 1), ('rula', 2)):
        mn = int(rules[key]['params'].get('min') or (8 if key == 'reba' else 6))
        bad = [s for s in scored if s[idx] is not None and s[idx] >= mn]
        add(key, len(scored), [s[0]['box'] for s in bad],
            f"{key.upper()} {max(s[idx] for s in bad)}" if bad else '', meta={'score': max(s[idx] for s in bad)} if bad else None)
    return out


class Tracker:
    """Onay katmanı: ihlal `confirm` gözlem üst üste ve `hold` saniye sürerse, cooldown'da bir kez olay."""

    def __init__(self):
        self.s = {}

    def step(self, cam_id, results, t, rules):
        events, seen = [], set()
        for r in results:
            rule = rules[r['rule']]
            key = (cam_id, r['rule'], r['zone'], r['slot'])
            seen.add(key)
            st = self.s.setdefault(key, {'hits': 0, 'since': None, 'miss': 0, 'last_event': 0.0, 'seen': t})
            st['seen'] = t
            if r['viol'] <= 0:
                st['miss'] += 1
                if st['miss'] > (2 if rule['hold'] else 0):     # süre gerektiren kuralda iki kaçırılan gözlem hoş görülür
                    st['hits'], st['since'] = 0, None
                continue
            st['miss'] = 0
            st['hits'] += 1
            st['since'] = st['since'] or t
            if st['hits'] >= rule['confirm'] and t - st['since'] >= rule['hold'] and t - st['last_event'] >= rule['cooldown']:
                st['last_event'] = t
                events.append({**r, 'name': rule['name'], 'sev': rule['sev'], 'lik': rule['lik'], 'risk': rule['risk'],
                               'level': rule['level'], 'cat': rule['cat'], 'duration': round(t - st['since'], 1)})
        for key in [k for k, st in self.s.items() if k[0] == cam_id and k not in seen and t - st['seen'] > 3600]:
            del self.s[key]
        return events
