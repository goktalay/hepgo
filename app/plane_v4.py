"""CAYMAZ V4 parça şeması (GÖKKUBBE, 2026-10-19).

V2'nin (app/plane_v2.py) kopyasıdır; farklar:
- Kanat parçaları L2, L3, R2, R3 ile burun parçaları 08 ve 09 yeniden çizildi ve ayrı parçalar oldu (kod sonu -V4;
  G-code dosyaları 'V3' çizimleridir: L2 - V3, L3 - V3, O8 - V3, O9 - V3, R2 - V3, R3 - V3).
- Gövde üstüne servo kapağı eklendi (SERVO-KAPAK-V2, 'SERVO KAPAK - V2' G-code'u): 02 parçası üzerinde kapak.
Diğer tüm parçalar V2 ile aynıdır (aynı yedek parça ürünü, aynı stok). Yeniden çizilen parçaların üstten 2B görünüşü
V2'deki karşılıklarıyla aynıdır: şekiller V2'den aynen alınır, yedek parça kaydı V2 parçasının resmini (aynı dosya) kullanır.
"""
import copy
from functools import lru_cache

from . import plane as root
from . import plane_v2 as base

GROUPS = base.GROUPS
ASSEMBLY_SECTIONS = base.ASSEMBLY_SECTIONS
ELECTRONICS_PARTS = base.ELECTRONICS_PARTS
VIEWBOX = base.VIEWBOX

# V2 parça kodu → V4 parça kodu
CHANGED = {'L2': 'L2-V4', 'L3': 'L3-V4', 'R2': 'R2-V4', 'R3': 'R3-V4', '08-V2': '08-V4', '09': '09-V4'}
SERVO_COVER = 'SERVO-KAPAK-V2'
NEW_PARTS = list(CHANGED.values()) + [SERVO_COVER]

def v4(pid):
    return CHANGED.get(pid, pid)


def _servo_cover():
    """Servo kapağı (uçak koordinatları): gövde 02 parçası üzerinde, baskı ölçülerine (244×204 mm) uygun oranda
    dikdörtgen kapak, dört köşede vida deliği; gövde genişliğine (192) sığacak şekilde ölçeklenmiştir."""
    w, h = 146, 122
    cx, cy = 921, 1406
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    pts = root.box(x0, y0, x1, y1)
    holes = [[x, y, 3.0] for x in (x0 + 9, x1 - 9) for y in (y0 + 9, y1 - 9)]
    return {'id': SERVO_COVER, 'group': 'cover', 'side': 'M', 'name': 'Servo Kapak V2',
            'shapes': [{'pts': pts, 'holes': holes, 'slots': [], 'inner': []}]}


@lru_cache(maxsize=1)
def build():
    parts = []
    for p in copy.deepcopy(base.build()):
        p['id'] = v4(p['id'])
        if p.get('parent'):
            p['parent'] = v4(p['parent'])
        if p.get('hosts'):
            p['hosts'] = [v4(x) for x in p['hosts']]
        parts.append(p)
    cover = _servo_cover()
    pts = cover['shapes'][0]['pts']
    mid = [sum(x for x, _ in pts) / 4, sum(y for _, y in pts) / 4]
    structure = [p for p in parts if p['group'] not in ('cover', 'electronics')]
    cover['hosts'] = [p['id'] for p in structure if p['section'] == 'GOVDE' and root.in_poly(mid, p['shapes'][0]['pts'])]
    cover['area'] = round(root.poly_area(pts))
    cover['section'] = root.section_of(cover)
    cover['layer'] = root.layer_of(cover)
    ek = [p for p in parts if p['layer'] == 'electronics' and p['group'] == 'electronics']
    rest = [p for p in parts if p not in ek]
    return rest + [cover] + ek


def part_ids():
    return [p['id'] for p in build()]


def plane_json():
    return {'viewBox': VIEWBOX, 'groups': GROUPS, 'sections': ASSEMBLY_SECTIONS, 'parts': build()}
