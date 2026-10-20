#!/usr/bin/env python3
"""Üçgen ağlı (FACETED_BREP) STEP montajı → GLB; her MAPPED_ITEM yerleşimi ayrı düğüm.

Kullanım:  .venv/bin/python -I tools/step_mapped2glb.py girdi.stp cikti.glb [--no-classify] [--json]

Saf Python ayrıştırıcı (OCCT gerekmez); yalnız "convert3d" / SolidWorks tarzı üçgen ağ STEP'lerini okur:
  CARTESIAN_POINT, DIRECTION, AXIS2_PLACEMENT_3D, POLY_LOOP, FACE_OUTER_BOUND/FACE_BOUND, FACE_SURFACE/ADVANCED_FACE/FACE,
  CLOSED_SHELL/OPEN_SHELL, FACETED_BREP/MANIFOLD_SOLID_BREP, *SHAPE_REPRESENTATION, REPRESENTATION_MAP, MAPPED_ITEM,
  LENGTH_UNIT (SI_UNIT önekleri: MILLI/CENTI/DECI/KILO; CONVERSION_BASED_UNIT 'INCH'/'FOOT').
Eğri yüzeyli (B-spline) gerçek B-rep için tools/step2glb.js (occt-import-js) kullanılır.

Çıktı çerçevesi: STEP koordinatları metreye çevrilir; eksen dönüşümü YAPILMAZ (çağıran `kok` 4×4 matrisiyle verir).
Her yerleşim bir düğüm: düğüm dönüşümü = kök · yerleşim; mesh köşeleri parçanın kendi (REPRESENTATION_MAP) çerçevesinde.
`pivot` verilirse (parça yerel) düğüm orijini oraya taşınır (pervane göbeği).

Sınıflandırma (`siniflandir`): tekrar sayısı + biçim kuralları → ad + malzeme rolü (INTERCEPTOR montajı için ayarlı;
genel montajda bilinmeyen parça `part_<i>` olur):
  * ≥ 2 kez yerleşen, en ince sınır kutusu ekseni / en büyük eksen < 0,12 olan parça → pervane (`prop_N`, rol 'prop')
  * ≥ 2 kez yerleşen, pervane ile eş sayıda ve küçük (en büyük boyut < 0,4 × en uzun parça ve < 1,2 × pervane çapı) parçalardan
    yerleşimleri pervane göbeklerine ortalama en yakın olan grup → motor (`motor_N`, rol 'motor')
  * ≥ 2 kez yerleşen diğerleri → gondol (`nacelle_N`, rol 'body')
Pervane düğümleri: orijin göbekte, rotation kimlik (dönüş ağa pişirilir) — flightsim3d dönüş eksenini düğüm yerel sınır kutusunun en
ince ekseninden seçer.
  * tek yerleşenler: en uzun → `body`, diğerleri `part_<i>` (rol 'body')
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

_ENT = re.compile(r'#(\d+)\s*=\s*(.*?);\s*(?=#\d+\s*=|ENDSEC)', re.S)
_REF = re.compile(r'#(\d+)')
_NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
_TIP = re.compile(r'^([A-Z_0-9]+)\s*\((.*)\)$', re.S)

ON_EK = {'MILLI': 1e-3, 'CENTI': 1e-2, 'DECI': 1e-1, 'KILO': 1e3, 'MICRO': 1e-6}


def ayristir(metin):
    """STEP DATA bölümü → {id: (TİP, argüman metni)}; karmaşık (parantezli) varlıklarda TİP 'COMPLEX'."""
    i = metin.find('DATA;')
    govde = metin[i + 5:] if i >= 0 else metin
    ent = {}
    for m in _ENT.finditer(govde):
        eid, ic = int(m.group(1)), m.group(2).strip()
        t = _TIP.match(ic)
        ent[eid] = (t.group(1), t.group(2)) if t and not ic.startswith('(') else ('COMPLEX', ic)
    return ent


def _refs(s):
    return [int(x) for x in _REF.findall(s)]


def _sayilar(s):
    return [float(x) for x in _NUM.findall(s)]


def birim_olcek(ent):
    for tip, arg in ent.values():
        if tip == 'COMPLEX' and 'LENGTH_UNIT' in arg:
            m = re.search(r'SI_UNIT\s*\(\s*\.?(\w*)\.?\s*,\s*\.METRE\.\s*\)', arg)
            if m:
                return ON_EK.get(m.group(1).strip('.'), 1.0)
            if 'CONVERSION_BASED_UNIT' in arg:
                if re.search(r"'INCH'", arg, re.I):
                    return 0.0254
                if re.search(r"'FOOT'", arg, re.I):
                    return 0.3048
    return 1.0


class Step:
    def __init__(self, metin):
        self.ent = ayristir(metin)
        self.olcek = birim_olcek(self.ent)
        self._pt = {}

    def nokta(self, eid):
        p = self._pt.get(eid)
        if p is None:
            tip, arg = self.ent[eid]
            # CARTESIAN_POINT('',(x,y,z)) — ad dizesinde sayı olabilir: son parantez grubunu al
            p = np.array(_sayilar(arg[arg.rfind('('):])[:3], dtype=float)
            self._pt[eid] = p
        return p

    def yon(self, eid):
        tip, arg = self.ent[eid]
        v = np.array(_sayilar(arg[arg.rfind('('):])[:3], dtype=float)
        n = np.linalg.norm(v)
        return v / n if n else v

    def yerlesim(self, eid):
        """AXIS2_PLACEMENT_3D → 4×4 (metre)."""
        tip, arg = self.ent[eid]
        r = _refs(arg)
        o = self.nokta(r[0]) * self.olcek
        z = self.yon(r[1]) if len(r) > 1 else np.array([0, 0, 1.0])
        x = self.yon(r[2]) if len(r) > 2 else (np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0]))
        x = x - z * float(x @ z)
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        T = np.eye(4)
        T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, z, o
        return T

    def _yuz_ucgenleri(self, fid, V, F, idx):
        tip, arg = self.ent[fid]
        sense = not arg.rstrip().endswith('.F.')
        for bid in _refs(arg.split('),')[0] if '),' in arg else arg)[:]:
            if bid not in self.ent:
                continue
            btip, barg = self.ent[bid]
            if btip not in ('FACE_OUTER_BOUND', 'FACE_BOUND'):
                continue
            ori = not barg.rstrip().endswith('.F.')
            lid = _refs(barg)[0]
            ltip, larg = self.ent[lid]
            if ltip != 'POLY_LOOP':
                continue
            pts = _refs(larg)
            if len(pts) < 3:
                continue
            ii = []
            for p in pts:
                k = idx.get(p)
                if k is None:
                    k = idx[p] = len(V)
                    V.append(self.nokta(p))
                ii.append(k)
            if ori != sense:
                ii = ii[::-1]
            for j in range(1, len(ii) - 1):   # yelpaze üçgenleme (POLY_LOOP genelde üçgen)
                F.append((ii[0], ii[j], ii[j + 1]))
            if btip == 'FACE_OUTER_BOUND':
                break

    def kabuk_ag(self, sid):
        tip, arg = self.ent[sid]
        V, F, idx = [], [], {}
        for fid in _refs(arg):
            if fid in self.ent and self.ent[fid][0] in ('FACE_SURFACE', 'ADVANCED_FACE', 'FACE'):
                self._yuz_ucgenleri(fid, V, F, idx)
        return V, F

    def temsil_ag(self, rid):
        """Şekil temsili → (V (metre), F); FACETED_BREP/MANIFOLD_SOLID_BREP/kabuklar."""
        tip, arg = self.ent[rid]
        V, F = [], []
        yigin = _refs(arg.split(')')[0] if '(' in arg else arg)
        gor = set()
        while yigin:
            e = yigin.pop()
            if e in gor or e not in self.ent:
                continue
            gor.add(e)
            t, a = self.ent[e]
            if t in ('FACETED_BREP', 'MANIFOLD_SOLID_BREP', 'BREP_WITH_VOIDS', 'SHELL_BASED_SURFACE_MODEL'):
                yigin.extend(_refs(a))
            elif t in ('CLOSED_SHELL', 'OPEN_SHELL'):
                v, f = self.kabuk_ag(e)
                n = len(V)
                V.extend(v)
                F.extend((a0 + n, a1 + n, a2 + n) for a0, a1, a2 in f)
        V = np.array(V, dtype=float).reshape(-1, 3) * self.olcek
        return V, np.array(F, dtype=np.int64).reshape(-1, 3)

    def montaj(self):
        """→ parcalar {map_id: (V, F)}, yerlesimler [(map_id, T 4×4)] (MAPPED_ITEM sırasıyla)."""
        parcalar, yer = {}, []
        for eid in sorted(self.ent):
            tip, arg = self.ent[eid]
            if tip != 'MAPPED_ITEM':
                continue
            r = _refs(arg)
            mid, hedef = r[0], r[1]
            mtip, marg = self.ent[mid]
            mr = _refs(marg)
            kaynak = self.yerlesim(mr[0]) if self.ent[mr[0]][0] == 'AXIS2_PLACEMENT_3D' else np.eye(4)
            if mid not in parcalar:
                parcalar[mid] = self.temsil_ag(mr[1])
            T = (self.yerlesim(hedef) if self.ent[hedef][0] == 'AXIS2_PLACEMENT_3D' else np.eye(4)) @ np.linalg.inv(kaynak)
            yer.append((mid, T))
        if not yer:   # MAPPED_ITEM yok: her FACETED_BREP birim dönüşümle tek yerleşim
            for eid in sorted(self.ent):
                if self.ent[eid][0] == 'FACETED_BREP':
                    parcalar[eid] = self.temsil_ag_brep(eid)
                    yer.append((eid, np.eye(4)))
        return parcalar, yer

    def temsil_ag_brep(self, bid):
        V, F = [], []
        for sid in _refs(self.ent[bid][1]):
            v, f = self.kabuk_ag(sid)
            n = len(V)
            V.extend(v)
            F.extend((a + n, b + n, c + n) for a, b, c in f)
        return np.array(V, dtype=float).reshape(-1, 3) * self.olcek, np.array(F, dtype=np.int64).reshape(-1, 3)


def oku(yol):
    s = Step(Path(yol).read_text(encoding='latin-1'))
    return s.montaj()


# ---------- sınıflandırma ----------
def _dunya_merkez(V, T, piv=None):
    c = (V.max(0) + V.min(0)) / 2 if piv is None else piv
    return (T @ np.append(c, 1.0))[:3]


def siniflandir(parcalar, yer):
    """→ her yerleşim için (ad, rol, pivot_yerel|None). Kurallar modül belgesinde."""
    say = {}
    for mid, _ in yer:
        say[mid] = say.get(mid, 0) + 1
    boy = {mid: (V.max(0) - V.min(0)) if len(V) else np.zeros(3) for mid, (V, F) in parcalar.items()}
    tekrar = [m for m in say if say[m] >= 2]
    tek = [m for m in say if say[m] == 1]
    en_uzun = max((boy[m].max() for m in parcalar), default=1.0) or 1.0
    rol = {}
    pervane = [m for m in tekrar if boy[m].max() > 0 and boy[m].min() / boy[m].max() < 0.12]
    for m in pervane:
        rol[m] = 'prop'
    # göbek (dünya) konumları: pervane parçasının sınır kutusu merkezi (simetrik pervane)
    gobek = [_dunya_merkez(parcalar[m][0], T) for m, T in yer if m in pervane]
    np_ = {say[m] for m in pervane}
    pmax = max((boy[p].max() for p in pervane), default=0.0)
    # motor: pervane sayısında tekrar eden, küçük (< 0,4 × en uzun parça, < 1,2 × pervane çapı) parçalardan yerleşimleri göbeklere
    # ORTALAMA EN YAKIN olan grup; diğer tekrar edenler gondol (nacelle) — ör. motor kapağı/gondol konisi turuncu boyanmasın
    aday = [m for m in tekrar if m not in rol and say[m] in np_ and boy[m].max() < 0.4 * en_uzun and boy[m].max() < 1.2 * pmax]
    motor = None
    if aday and gobek:
        G = np.array(gobek)

        def uzaklik(m):
            return float(np.mean([np.linalg.norm(G - _dunya_merkez(parcalar[m][0], T), axis=1).min() for mm, T in yer if mm == m]))
        motor = min(aday, key=uzaklik)
    for m in tekrar:
        if m not in rol:
            rol[m] = 'motor' if m == motor else 'nacelle'
    govde = max(tek, key=lambda m: boy[m].max()) if tek else None
    sayac, out = {}, []
    for mid, T in yer:
        r = rol.get(mid)
        if r is None:
            ad, r2 = ('body', 'body') if mid == govde else (f'part_{tek.index(mid) + 1}', 'body')
            out.append((ad, r2, None))
            continue
        sayac[r] = sayac.get(r, 0) + 1
        piv = None
        if r == 'prop':
            V = parcalar[mid][0]
            piv = (V.max(0) + V.min(0)) / 2   # göbek = sınır kutusu merkezi (simetrik pervane)
        out.append((f'{r}_{sayac[r]}', 'body' if r == 'nacelle' else r, piv))
    return out


def srgb_lineer(h):
    """'#rrggbb' → doğrusal RGBA (glTF baseColorFactor doğrusaldır; three.js Color.setHex ile aynı görünüm)."""
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1.0,)


ROL_MALZEME = {   # rol → (doğrusal RGBA, metal, pürüzlülük)
    'body': (srgb_lineer('#161616'), 0.0, 0.8),
    'motor': (srgb_lineer('#ff7a1a'), 0.0, 0.55),
    'prop': (srgb_lineer('#2b2b2e'), 0.1, 0.5),
}


def sinir_kutusu(parcalar, yer, kok=None):
    """Tüm yerleşimlerin (kök çerçevesinde) sınır kutusu → (lo, hi)."""
    kok = np.eye(4) if kok is None else np.asarray(kok, dtype=float)
    pts = []
    for mid, T in yer:
        V = parcalar[mid][0]
        if len(V):
            M = kok @ T
            pts.append(V @ M[:3, :3].T + M[:3, 3])
    P = np.vstack(pts)
    return P.min(0), P.max(0)


def _faz45(Vb, a, b):
    """Pervane ağını dönüş ekseni a etrafında döndür: pala yönü b, a'ya dik iki ana eksenin açıortayına gelsin (düğüm yerel sınır
    kutusunda en ince eksen kesin olarak dönüş ekseni olur; pala fazı görsel olarak önemsiz — pervane sahnede döner)."""
    k = int(np.argmax(np.abs(a)))
    if abs(a[k]) < 0.99:
        return Vb
    i, j = [x for x in range(3) if x != k]
    d = np.zeros(3)
    d[i] = d[j] = 1 / np.sqrt(2)
    b = b - a * float(b @ a)
    if np.linalg.norm(b) < 1e-9:
        return Vb
    b = b / np.linalg.norm(b)
    aci = np.arctan2(float(np.cross(b, d) @ a), float(b @ d))
    R = _eksen_aci(a, aci)
    return Vb @ R.T


def _eksen_aci(a, t):
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * (K @ K)


def glb_kur(parcalar, yer, adlar, kok=None, malzeme=None):
    """trimesh.Scene: her yerleşim kök altında düğüm; malzeme role göre. kok: STEP(m) → çıktı çerçevesi 4×4.
    Pervane (`piv` verilen) düğümleri: düğüm dönüşümü YALNIZ öteleme (göbek), dönüş ağa pişirilir (rotation = kimlik); pala fazı 45°'ye
    normalize edilir. Diğer düğümler: düğüm dönüşümü = kök · yerleşim (ağ parçanın kendi çerçevesinde, örnekler paylaşılır)."""
    import trimesh
    kok = np.eye(4) if kok is None else np.asarray(kok, dtype=float)
    tablo = dict(ROL_MALZEME, **(malzeme or {}))
    mats = {r: trimesh.visual.material.PBRMaterial(name=r, baseColorFactor=[int(round(c * 255)) for c in rgba], metallicFactor=me, roughnessFactor=ro)
            for r, (rgba, me, ro) in tablo.items()}
    sc = trimesh.Scene()
    geo = {}
    for (mid, T), (ad, rol, piv) in zip(yer, adlar):
        V, F = parcalar[mid]
        Tn = kok @ T
        mat = mats.get(rol, mats['body'])
        if piv is not None:
            R = Tn[:3, :3]
            b_ = V.max(0) - V.min(0)
            Vb = (V - piv) @ R.T
            Vb = _faz45(Vb, R[:, int(np.argmin(b_))] / np.linalg.norm(R[:, int(np.argmin(b_))]), R[:, int(np.argmax(b_))])
            m = trimesh.Trimesh(Vb, F, process=False)
            m.merge_vertices()
            m.visual = trimesh.visual.TextureVisuals(material=mat)
            sc.add_geometry(m, node_name=ad, geom_name=f'{ad}_g', parent_node_name=sc.graph.base_frame, transform=_tasima(Tn[:3, :3] @ piv + Tn[:3, 3]))
            continue
        key = (mid, rol)
        if key not in geo:
            m = trimesh.Trimesh(V, F, process=False)
            m.merge_vertices()
            m.visual = trimesh.visual.TextureVisuals(material=mat)
            geo[key] = (f'g{len(geo)}_{rol}', m)
        gname, m = geo[key]
        sc.add_geometry(m, node_name=ad, geom_name=gname, parent_node_name=sc.graph.base_frame, transform=Tn)
    return sc


def _tasima(p):
    T = np.eye(4)
    T[:3, 3] = p
    return T


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('girdi')
    ap.add_argument('cikti')
    ap.add_argument('--no-classify', action='store_true', help='adlar part_<i>, tek malzeme')
    ap.add_argument('--json', action='store_true', help='parça/yerleşim özetini yazdır')
    a = ap.parse_args(argv)
    parcalar, yer = oku(a.girdi)
    adlar = [(f'part_{i + 1}', 'body', None) for i in range(len(yer))] if a.no_classify else siniflandir(parcalar, yer)
    if a.json:
        for (mid, T), (ad, rol, _) in zip(yer, adlar):
            V = parcalar[mid][0]
            print(json.dumps({'ad': ad, 'rol': rol, 'map': mid, 'tri': len(parcalar[mid][1]), 'boy': (V.max(0) - V.min(0)).round(4).tolist(),
                              'merkez_yerel': ((V.max(0) + V.min(0)) / 2).round(4).tolist(), 'T': T.round(5).tolist()}))
    sc = glb_kur(parcalar, yer, adlar)
    data = sc.export(file_type='glb')
    Path(a.cikti).write_bytes(data)
    print(f'{a.cikti}: {len(yer)} düğüm, {sum(len(parcalar[m][1]) for m, _ in yer)} üçgen, {len(data)} bayt', file=sys.stderr)


if __name__ == '__main__':
    main()
