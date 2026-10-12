"""CAYMAZ V3 parça şeması (GÖKKUBBE, 2026-10-12).

V2'ye (app/plane_v2.py) göre tek fark: üç parça yeniden çizildi ve ayrı parçalar oldu (kod sonu -V3):
L4 (CAYMAZ - L4V3), R4 (CAYMAZ - R4V3) ve gövde 01 (CAYMAZ O1 - V3). Diğer tüm parçalar V2 ile aynıdır
(aynı yedek parça ürünü, aynı stok). Yeni çizimler gelene kadar şekilleri V2 ile aynı gösterilir.
"""
import copy
from functools import lru_cache

from . import plane_v2 as base

GROUPS = base.GROUPS
ASSEMBLY_SECTIONS = base.ASSEMBLY_SECTIONS
ELECTRONICS_PARTS = base.ELECTRONICS_PARTS
VIEWBOX = base.VIEWBOX

# V2 parça kodu → V3 parça kodu
CHANGED = {'L4-V2': 'L4-V3', 'R4-V2': 'R4-V3', '01-V2': '01-V3'}


def v3(pid):
    return CHANGED.get(pid, pid)


@lru_cache(maxsize=1)
def build():
    parts = []
    for p in copy.deepcopy(base.build()):
        p['id'] = v3(p['id'])
        if p.get('parent'):
            p['parent'] = v3(p['parent'])
        if p.get('hosts'):
            p['hosts'] = [v3(x) for x in p['hosts']]
        parts.append(p)
    return parts


def part_ids():
    return [p['id'] for p in build()]


def plane_json():
    return {'viewBox': VIEWBOX, 'groups': GROUPS, 'sections': ASSEMBLY_SECTIONS, 'parts': build()}
