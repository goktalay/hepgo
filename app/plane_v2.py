"""CAYMAZ V2 parça şeması (GÖKKUBBE, 2026-09-28).

V1'e (app/plane.py) göre değişiklikler:
- Benzin deposunun rahat yerleşmesi için gövde kapakları büyütüldü: K02, K03 ve KAPAK7 yok; yerlerine 05 / 04 / 03
  üzerine gelen iki büyük kapak K08 (üstte) ve K09 (altta) eklendi (yanlarda delikli montaj kulakçıkları).
- Ön kısma ek karbon borular ve kanatlara kelepçe sistemi eklendiği için şu parçalar yeniden çizildi ve ayrı
  parçalar oldu (kod sonuna -V2): L18, R18, L15A, L15B, R15A, R15B, L4, R4, 01, 03, 04, 05, 06, 07, 08.
  Yeni çizimleri gelene kadar şekilleri V1 ile aynı gösterilir.
- Diğer tüm parçalar V1 ile aynıdır (aynı yedek parça ürünü, aynı stok).
"""
import copy
from functools import lru_cache

from . import plane as base

GROUPS = base.GROUPS
ASSEMBLY_SECTIONS = base.ASSEMBLY_SECTIONS
ELECTRONICS_PARTS = base.ELECTRONICS_PARTS
VIEWBOX = base.VIEWBOX

CHANGED = ['L18', 'R18', 'L15A', 'L15B', 'R15A', 'R15B', 'L4', 'R4', '01', '03', '04', '05', '06', '07', '08']
REMOVED = {'K02', 'K03', 'KAPAK7'}
NEW_COVERS = ['K08', 'K09']


def v2(pid):
    return f'{pid}-V2'


def _cover(pid, top, bottom, hole_ys):
    """05-04-03 üzerindeki büyük kapak (uçak koordinatları): orta panel + iki yanda delikli kulakçık.
    Ölçüler kullanıcının çiziminden (04 yüksekliği = 192 birim ölçeğiyle) alınmıştır."""
    x0, x1 = 837.3, 1004.7          # kapak dış kenarları (gövde 825–1017 içinde, ortalı)
    t0, t1 = 869.3, 972.7           # kulakçık / orta panel sınırı
    pts = base.box(x0, top, x1, bottom)
    holes = [[x, y, 3.0] for x in (848.6, 993.4) for y in hole_ys]
    return {'id': pid, 'group': 'cover', 'side': 'M', 'name': None,
            'shapes': [{'pts': pts, 'holes': holes, 'slots': [],
                        'inner': [[[t0, top], [t0, bottom]], [[t1, top], [t1, bottom]]]}]}


@lru_cache(maxsize=1)
def build():
    parts = []
    for p in copy.deepcopy(base.build()):
        if p['id'] in REMOVED:
            continue
        if p['id'] in CHANGED:
            p['id'] = v2(p['id'])
            if p.get('parent'):
                p['parent'] = v2(p['parent'])
        if p.get('hosts'):
            p['hosts'] = [v2(x) if x in CHANGED else x for x in p['hosts']]
        parts.append(p)
    covers = [_cover('K08', 833.9, 998.8, (861.0, 976.7)), _cover('K09', 998.8, 1161.3, (1021.0, 1134.2))]
    structure = [p for p in parts if p['group'] not in ('cover', 'electronics')]
    for c in covers:
        pts = c['shapes'][0]['pts']
        c['hosts'] = [p['id'] for p in structure if p['section'] == 'GOVDE' and any(
            base.in_poly(q, p['shapes'][0]['pts']) for q in ([sum(x for x, _ in pts) / 4, pts[0][1] + 2],
                                                              [sum(x for x, _ in pts) / 4, pts[2][1] - 2]))]
        c.pop('name')
        c['area'] = round(base.poly_area(pts))
        c['section'] = base.section_of(c)
        c['layer'] = base.layer_of(c)
    ek = [p for p in parts if p['layer'] == 'electronics' and p['group'] == 'electronics']
    rest = [p for p in parts if p not in ek]
    return rest + covers + ek


def part_ids():
    return [p['id'] for p in build()]


def plane_json():
    return {'viewBox': VIEWBOX, 'groups': GROUPS, 'sections': ASSEMBLY_SECTIONS, 'parts': build()}
