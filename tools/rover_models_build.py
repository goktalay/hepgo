#!/usr/bin/env python3
"""KARA ARACI (§31) prosedürel GLB modelleri → static/simumav/models/<ad>.glb (HEPGO + SIMUMAV ortak; kaynak dosya gerekmez, HEPGO üretimi).

Kullanım:
  .venv/bin/python -I tools/rover_models_build.py --out static/simumav/models [--only rover_4x4,rover_ugv,rover_bot]
Gereksinim (yalnız geliştirme makinesi): trimesh, numpy (pygltflib yalnız rapor için).

Konvansiyon (static/simumav/models/*.glb ile aynı): glTF metre, Y yukarı, burun +X, sağ +Z; orijin = modelin sınır kutusu merkezi.
Hareketli düğümler (flightsim3d / flightsim_rover.js + SIMUMAV hangar bu adları tanır; adlarında prop/rotor GEÇMEZ):
  wheel_<f|m|r><l|r>   tekerlek: orijin teker merkezi, aks yerel +Z (sağ) — ileri yuvarlanma yerel Z etrafında NEGATİF dönüş
  wheel_<l|r><1..n>    paletli araçta yol tekerleri / zincir dişlisi (aynı eksen kuralı; sol/sağ palet ayrı hızla döner)
  steer_<fl|fr>        Ackermann direksiyon mafsalı: orijin teker merkezi (pim ekseni yerel +Y); sağa dönüş = yerel Y etrafında NEGATİF açı.
                       Ön tekerlek düğümü (wheel_fl/fr) bu düğümün çocuğudur (kimlik dönüşüm).
  track_<l|r>          palet kayışı (statik; animasyon tekerlerden)
extras (GLB kök düğümü `rover`): drive (ackermann | skid), wheel_r (m), wheelbase (m), track (m), cockpit / sensor [x ileri, y zeminden yükseklik, z sağ]
(m; merkezlemeden ÖNCEKİ çerçeve = zemin y 0, kök düğüm öteleme −merkez) — istemci kokpit (sürücü gözü) ve gimbal kamerası noktasını buradan okur.
Üçgen bütçesi ≤ 30 k / model; doku yok (düz PBR renkler); Draco/meshopt YOK.

Modeller:
  rover_4x4  Keşif 4×4 (Ackermann): 2,05 m × 1,30 m, teker Ø 0,66 m, dingil mesafesi 1,30 m; açık kasa, roll-bar, sensör direği (EO top + LIDAR),
             ışık barı, yedek teker, çamurluklar. Kum/haki gövde, siyah tampon.
  rover_ugv  Paletli UGV (skid): 2,40 m × 2,00 m; iki palet modülü (her biri 6 yol tekeri + ön dişli + arka avara), orta gövde, uzaktan kumandalı
             sensör kulesi, anten. Koyu yeşil.
  rover_bot  Teslimat robotu (skid, 6 teker): 0,72 m × 0,57 m × 0,55 m (+ 1,2 m bayrak direği); beyaz gövde, siyah alt şasi, kapak, ön ışık şeridi.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import trimesh

TRI_BUTCE = 30_000


def pbr(renk, metal=0.1, rough=0.6, ad=None, cift=False):
    m = trimesh.visual.material.PBRMaterial(name=ad, baseColorFactor=[int(round(c * 255)) for c in renk], metallicFactor=metal, roughnessFactor=rough,
                                            doubleSided=cift or None)
    if renk[3] < 0.99:
        m.alphaMode = 'BLEND'
    return m


def boya(mesh, renk, metal=0.1, rough=0.6, ad=None, cift=False):
    mesh.visual = trimesh.visual.TextureVisuals(material=pbr(renk, metal, rough, ad, cift))
    return mesh


def kutu(sx, sy, sz, x=0.0, y=0.0, z=0.0):
    b = trimesh.creation.box([sx, sy, sz])
    b.apply_translation([x, y, z])
    return b


def pah_kutu(sx, sy, sz, pah, x=0.0, y=0.0, z=0.0, ust_pah=None):
    """Pahlı (kenarları kırık) kutu: 24 noktanın dışbükey zarfı. ust_pah: üst kenarlar için ayrı pah (yoksa pah)."""
    up = pah if ust_pah is None else ust_pah
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    pts = []
    for sy_, p in ((-1, pah), (1, up)):
        yd = sy_ * hy
        yi = sy_ * (hy - p)
        for xs in (-1, 1):
            for zs in (-1, 1):
                pts.append([xs * (hx - p), yd, zs * (hz - p)])
                pts.append([xs * hx, yi, zs * (hz - p)])
                pts.append([xs * (hx - p), yi, zs * hz])
    m = trimesh.convex.convex_hull(np.array(pts))
    m.apply_translation([x, y, z])
    return m


def zarf(noktalar, x=0.0, y=0.0, z=0.0):
    m = trimesh.convex.convex_hull(np.array(noktalar, dtype=float))
    m.apply_translation([x, y, z])
    return m


def silindir(r, h, eksen='z', n=24, x=0.0, y=0.0, z=0.0):
    c = trimesh.creation.cylinder(radius=r, height=h, sections=n)   # ekseni Z
    if eksen == 'x':
        c.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
    elif eksen == 'y':
        c.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
    c.apply_translation([x, y, z])
    return c


def boru(a, b, r, n=10):
    """a → b arası silindir (roll-bar, anten)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    L = float(np.linalg.norm(d))
    c = trimesh.creation.cylinder(radius=r, height=L, sections=n)
    z = np.array([0, 0, 1.0])
    v = np.cross(z, d / L)
    s = np.linalg.norm(v)
    if s > 1e-9:
        R = trimesh.transformations.rotation_matrix(math.atan2(s, float(np.dot(z, d / L))), v / s)
        c.apply_transform(R)
    elif np.dot(z, d) < 0:
        c.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
    c.apply_translation((a + b) / 2)
    return c


def kure(r, x=0.0, y=0.0, z=0.0, n=2):
    s = trimesh.creation.icosphere(subdivisions=n, radius=r)
    s.apply_translation([x, y, z])
    return s


# ---------- tekerlek (yerel: aks +Z, merkez orijin) ----------
def teker(R, W, renk_lastik, renk_jant, lug=18, jant_oran=0.62, dis=True):
    """Arazi lastiği: gövde silindiri + diş blokları (lug) + jant + göbek. Aks yerel Z. Dönüşte diş blokları görünür (animasyon algısı)."""
    parca = []
    govde = silindir(R * 0.93, W, 'z', 28)
    parca.append(boya(govde, renk_lastik, 0.0, 0.92))
    if dis:
        for k in range(lug):
            a = 2 * math.pi * k / lug
            for s in (-1, 1):   # V diş: iki yarı, kaydırılmış
                b = kutu(R * 0.16, R * 0.10, W * 0.46)
                b.apply_translation([0, R * 0.95, s * W * 0.25])
                b.apply_transform(trimesh.transformations.rotation_matrix(a + s * math.pi / lug * 0.5, [0, 0, 1]))
                parca.append(boya(b, renk_lastik, 0.0, 0.92))
    jant = silindir(R * jant_oran, W * 1.02, 'z', 20)
    parca.append(boya(jant, renk_jant, 0.6, 0.35))
    for k in range(6):   # jant bijonları / kollar (dönüşü belli eder)
        a = 2 * math.pi * k / 6
        kol = kutu(R * jant_oran * 0.9, R * 0.08, W * 0.08)
        kol.apply_translation([R * jant_oran * 0.45, 0, 0])
        kol.apply_transform(trimesh.transformations.rotation_matrix(a, [0, 0, 1]))
        for s in (-1, 1):
            k2 = kol.copy(); k2.apply_translation([0, 0, s * W * 0.52])
            parca.append(boya(k2, (0.12, 0.12, 0.13, 1.0), 0.5, 0.4))
    for s in (-1, 1):
        gb = silindir(R * 0.16, W * 0.12, 'z', 14, z=s * W * 0.55)
        parca.append(boya(gb, (0.15, 0.15, 0.16, 1.0), 0.7, 0.3))
    return trimesh.util.concatenate(parca)


# ---------- sahne kurucu ----------
class Sahne:
    def __init__(self, ad, extras):
        self.sc = trimesh.Scene()
        self.kok = ad
        self.sc.graph.update(frame_to=ad, frame_from=self.sc.graph.base_frame, matrix=np.eye(4))
        self.extras = extras
        self.dugumler = {ad}
        self.sayac = {}

    def dugum(self, ad, ebeveyn=None, konum=(0, 0, 0)):
        self.sc.graph.update(frame_to=ad, frame_from=ebeveyn or self.kok, matrix=trimesh.transformations.translation_matrix(konum))
        self.dugumler.add(ad)
        return ad

    def ekle(self, mesh, dugum=None):
        d = dugum or self.kok
        n = self.sayac.get(d, 0); self.sayac[d] = n + 1
        self.sc.add_geometry(mesh, node_name=f'{d}_v{n}', geom_name=f'{d}_g{n}', parent_node_name=d)

    def bitir(self):
        """Kök düğümü sınır kutusu merkezine taşır (orijin = sınır kutusu merkezi)."""
        lo, hi = self.sc.bounds
        c = (lo + hi) / 2
        self.sc.graph.update(frame_to=self.kok, frame_from=self.sc.graph.base_frame, matrix=trimesh.transformations.translation_matrix(-c))
        self.extras['ground_y'] = round(float(-c[1] + lo[1]), 4)   # bilgi: yer düzlemi (kök çerçevesinde)
        return self.sc


def glb_yaz(sahne, out_path):
    data = sahne.sc.export(file_type='glb')
    # kök düğüme extras (drive, wheel_r…): pygltflib ile işlenir
    try:
        import pygltflib
        g = pygltflib.GLTF2.load_from_bytes(data)
        for n in g.nodes:
            if n.name == sahne.kok:
                n.extras = dict(sahne.extras)
        data = b''.join(g.save_to_bytes())
    except Exception as e:   # noqa: BLE001 — extras yalnız bilgi; ad kuralı yeter
        print(f'   (extras yazılamadı: {e})', file=sys.stderr)
    Path(out_path).write_bytes(data)
    return len(data)


# ---------- 1. Keşif 4×4 (Ackermann) ----------
def rover_4x4():
    KUM, HAKI, SIYAH, KOYU, GRI = (0.70, 0.62, 0.45, 1.0), (0.42, 0.44, 0.30, 1.0), (0.07, 0.07, 0.08, 1.0), (0.16, 0.17, 0.18, 1.0), (0.55, 0.57, 0.6, 1.0)
    CAM, TURUNCU, BEYAZ = (0.12, 0.18, 0.24, 1.0), (1.0, 0.5, 0.08, 1.0), (0.95, 0.95, 0.9, 1.0)
    R, Wt, L, IZ = 0.33, 0.24, 1.30, 1.06          # teker yarıçapı, genişliği, dingil mesafesi, iz genişliği (teker merkezleri arası)
    yc = R                                           # teker merkez yüksekliği (zemin y=0)
    S = Sahne('rover', {'drive': 'ackermann', 'wheel_r': R, 'wheelbase': L, 'track': IZ, 'kind': 'rover_4x4',
                        'cockpit': [0.02, yc + 0.80, -0.22], 'sensor': [0.17, yc + 1.16, 0.0]})
    # şasi + gövde
    S.ekle(boya(pah_kutu(1.86, 0.30, 0.86, 0.06, x=0.0, y=yc + 0.10), KOYU, 0.3, 0.6))               # alt şasi
    S.ekle(boya(pah_kutu(1.70, 0.34, 1.12, 0.08, x=-0.05, y=yc + 0.36, ust_pah=0.05), KUM, 0.15, 0.55))  # gövde kasası
    S.ekle(boya(zarf([[0.62, 0, -0.54], [0.62, 0, 0.54], [0.98, 0, -0.50], [0.98, 0, 0.50], [0.62, 0.30, -0.53], [0.62, 0.30, 0.53], [0.92, 0.18, -0.49], [0.92, 0.18, 0.49]],
                     y=yc + 0.20), KUM, 0.15, 0.55))                                                     # kaput (eğimli)
    S.ekle(boya(pah_kutu(0.20, 0.10, 0.96, 0.02, x=0.30, y=yc + 0.58), HAKI, 0.2, 0.6))               # ön konsol
    # ön cam çerçevesi + cam
    for s in (-1, 1):
        S.ekle(boya(boru([0.36, yc + 0.53, s * 0.52], [0.24, yc + 0.98, s * 0.50], 0.025), SIYAH, 0.5, 0.4))
    S.ekle(boya(boru([0.24, yc + 0.98, -0.50], [0.24, yc + 0.98, 0.50], 0.025), SIYAH, 0.5, 0.4))
    S.ekle(boya(zarf([[0.355, yc + 0.56, -0.48], [0.355, yc + 0.56, 0.48], [0.255, yc + 0.95, -0.47], [0.255, yc + 0.95, 0.47],
                      [0.345, yc + 0.56, -0.48], [0.245, yc + 0.95, 0.47]]), (0.62, 0.78, 0.9, 0.18), 0.0, 0.1, cift=True))   # ön cam: saydam (kokpit görüşü)
    # roll-bar (arka) + çapraz boru
    for s in (-1, 1):
        S.ekle(boya(boru([-0.30, yc + 0.53, s * 0.50], [-0.30, yc + 1.06, s * 0.46], 0.032), SIYAH, 0.5, 0.4))
        S.ekle(boya(boru([-0.30, yc + 1.06, s * 0.46], [0.24, yc + 0.98, s * 0.50], 0.025), SIYAH, 0.5, 0.4))
        S.ekle(boya(boru([-0.30, yc + 1.06, s * 0.46], [-0.78, yc + 0.55, s * 0.50], 0.028), SIYAH, 0.5, 0.4))
    S.ekle(boya(boru([-0.30, yc + 1.06, -0.46], [-0.30, yc + 1.06, 0.46], 0.032), SIYAH, 0.5, 0.4))
    # koltuklar (insansız araç: sürücü yeri boş — elektronik kutuları)
    S.ekle(boya(pah_kutu(0.42, 0.26, 0.40, 0.04, x=-0.02, y=yc + 0.66, z=-0.24), KOYU, 0.2, 0.7))
    S.ekle(boya(pah_kutu(0.42, 0.20, 0.40, 0.04, x=-0.02, y=yc + 0.63, z=0.24), HAKI, 0.2, 0.7))
    # ışık barı + farlar
    S.ekle(boya(kutu(0.08, 0.06, 0.70, x=0.22, y=yc + 1.03), KOYU, 0.4, 0.4))
    for k in range(6):
        S.ekle(boya(kutu(0.012, 0.04, 0.09, x=0.265, y=yc + 1.03, z=-0.28 + k * 0.112), BEYAZ, 0.0, 0.2))
    for s in (-1, 1):
        S.ekle(boya(silindir(0.06, 0.04, 'x', 16, x=0.995, y=yc + 0.33, z=s * 0.38), BEYAZ, 0.2, 0.15))
        S.ekle(boya(kutu(0.02, 0.05, 0.10, x=-0.905, y=yc + 0.42, z=s * 0.45), (0.85, 0.1, 0.08, 1.0), 0.0, 0.3))   # stop lambası
    # tamponlar
    S.ekle(boya(pah_kutu(0.12, 0.14, 1.18, 0.03, x=1.02, y=yc + 0.10), SIYAH, 0.4, 0.5))
    S.ekle(boya(pah_kutu(0.10, 0.12, 1.12, 0.03, x=-0.97, y=yc + 0.12), SIYAH, 0.4, 0.5))
    # çamurluklar (teker üstü kemerler)
    for x in (L / 2, -L / 2):
        for s in (-1, 1):
            pts = []
            for a in np.linspace(math.radians(15), math.radians(165), 7):
                for zz in (s * (IZ / 2 - 0.15), s * (IZ / 2 + 0.16)):
                    pts += [[x + math.cos(a) * (R + 0.06), yc + math.sin(a) * (R + 0.06), zz], [x + math.cos(a) * (R + 0.11), yc + math.sin(a) * (R + 0.11), zz]]
            # kemeri ince parçalar halinde (dışbükey zarf tek parça olursa dolu olur)
            for i in range(0, 6):
                seg = [p for j, p in enumerate(pts) if j // 4 in (i, i + 1)]
                S.ekle(boya(zarf(seg), SIYAH, 0.2, 0.7))
    # sensör direği: EO/IR topu + LIDAR + GPS mantarları + anten
    S.ekle(boya(boru([-0.55, yc + 0.53, 0.0], [-0.55, yc + 1.32, 0.0], 0.03), KOYU, 0.5, 0.4))
    S.ekle(boya(silindir(0.075, 0.07, 'y', 20, x=-0.55, y=yc + 1.37), KOYU, 0.4, 0.4))                # LIDAR
    S.ekle(boya(silindir(0.07, 0.03, 'y', 20, x=-0.55, y=yc + 1.42), (0.05, 0.05, 0.05, 1.0), 0.6, 0.2))
    S.ekle(boya(kure(0.11, x=0.05, y=yc + 1.16, z=0.0), GRI, 0.5, 0.35))                                # EO/IR top (roll-bar üstü)
    S.ekle(boya(kure(0.05, x=0.14, y=yc + 1.16, z=0.0), CAM, 0.8, 0.1))
    for s in (-1, 1):
        S.ekle(boya(silindir(0.045, 0.03, 'y', 16, x=-0.75, y=yc + 0.55, z=s * 0.35), BEYAZ, 0.1, 0.5))   # GPS
        S.ekle(boya(boru([-0.82, yc + 0.53, s * 0.42], [-0.86, yc + 1.55, s * 0.44], 0.008, 6), SIYAH, 0.3, 0.5))  # kırbaç anten
    S.ekle(boya(kutu(0.04, 0.12, 0.12, x=-0.86, y=yc + 1.58, z=0.44), TURUNCU, 0.0, 0.5))               # anten bayrağı
    # yedek teker (arka kapak)
    yt = teker(R * 0.92, Wt * 0.9, SIYAH, KOYU, lug=14)
    yt.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
    yt.apply_translation([-1.0, yc + 0.48, 0.0])
    S.ekle(yt)
    # süspansiyon kolları (statik görsel)
    for x in (L / 2, -L / 2):
        for s in (-1, 1):
            S.ekle(boya(boru([x, yc + 0.06, s * 0.30], [x, yc, s * (IZ / 2 - Wt / 2 - 0.02)], 0.03, 8), KOYU, 0.5, 0.4))
            S.ekle(boya(boru([x - 0.08, yc + 0.40, s * 0.38], [x, yc + 0.05, s * (IZ / 2 - Wt / 2 - 0.04)], 0.035, 8), TURUNCU, 0.4, 0.4))   # amortisör
    # tekerlekler: ön direksiyon mafsalı + teker; arka teker doğrudan
    for (ad, x, s) in (('fl', L / 2, -1), ('fr', L / 2, 1), ('rl', -L / 2, -1), ('rr', -L / 2, 1)):
        konum = (x, yc, s * IZ / 2)
        if ad[0] == 'f':
            S.dugum(f'steer_{ad}', konum=konum)
            S.dugum(f'wheel_{ad}', ebeveyn=f'steer_{ad}')
        else:
            S.dugum(f'wheel_{ad}', konum=konum)
        S.ekle(teker(R, Wt, SIYAH, KOYU), f'wheel_{ad}')
    return S


# ---------- 2. Paletli UGV (skid) ----------
def _palet_dongusu(x0, x1, r0, r1, n=56):
    """Stadyum benzeri palet döngüsü (XY düzleminde): ön teker merkezi x0 (yarıçap r0), arka x1 (r1); n nokta, saat yönü."""
    pts = []
    for a in np.linspace(-math.pi / 2, math.pi / 2, n // 4):
        pts.append([x0 + r0 * math.cos(a), r0 + r0 * math.sin(a)])
    for t in np.linspace(0, 1, n // 4)[1:-1]:
        pts.append([x0 + (x1 - x0) * t, 2 * r0 + (2 * r1 - 2 * r0) * t])
    for a in np.linspace(math.pi / 2, 3 * math.pi / 2, n // 4):
        pts.append([x1 + r1 * math.cos(a), r1 + r1 * math.sin(a)])
    for t in np.linspace(0, 1, n // 4)[1:-1]:
        pts.append([x1 + (x0 - x1) * t, 0.0])
    return np.array(pts)


def rover_ugv():
    YESIL, KOYU, SIYAH, GRI, CAM = (0.27, 0.33, 0.22, 1.0), (0.14, 0.15, 0.13, 1.0), (0.06, 0.06, 0.06, 1.0), (0.45, 0.47, 0.45, 1.0), (0.1, 0.16, 0.2, 1.0)
    L, IZ, PW = 2.40, 1.56, 0.42   # uzunluk, palet merkezleri arası, palet genişliği
    r_dis, r_yol = 0.27, 0.19     # ön dişli / yol tekeri yarıçapı
    S = Sahne('rover', {'drive': 'skid', 'wheel_r': r_yol, 'wheelbase': 1.80, 'track': IZ, 'kind': 'rover_ugv', 'tracked': True,
                        'cockpit': [1.05, 0.86, 0.0], 'sensor': [0.72, 1.06, 0.0]})
    x_on, x_arka = 0.92, -0.95
    for s, yan in ((-1, 'l'), (1, 'r')):
        z = s * IZ / 2
        # palet kayışı: döngü kesitini palet genişliğinde süpür (iç + dış yüzey → kalınlık)
        dong = _palet_dongusu(x_on, x_arka, r_dis + 0.035, r_dis + 0.035, 64)
        ic = _palet_dongusu(x_on, x_arka, r_dis - 0.005, r_dis - 0.005, 64)
        ic[:, 1] += 0.04
        kes = []
        for zz in (z - PW / 2, z + PW / 2):
            kes.append(np.column_stack([dong[:, 0], dong[:, 1], np.full(len(dong), zz)]))
            kes.append(np.column_stack([ic[:, 0], ic[:, 1], np.full(len(ic), zz)]))
        N = len(dong)
        V = np.vstack(kes)
        F = []
        for a, b in ((0, 2), (1, 3), (0, 1), (2, 3)):   # dış yüzey, iç yüzey, sol kenar, sağ kenar
            for i in range(N):
                i2 = (i + 1) % N
                F += [[a * N + i, b * N + i, b * N + i2], [a * N + i, b * N + i2, a * N + i2]]
        kayis = trimesh.Trimesh(V, np.array(F), process=True)   # sarım yönü karışık olabilir (networkx yok) → çift yüzlü malzeme
        S.dugum(f'track_{yan}')
        S.ekle(boya(kayis, SIYAH, 0.3, 0.85, cift=True), f'track_{yan}')
        # paletin dış yüzeyinde tırnaklar (grouser) — statik
        for i in range(0, N, 2):
            p, q = dong[i], dong[(i + 1) % N]
            d = q - p
            a = math.atan2(d[1], d[0])
            g = kutu(0.05, 0.03, PW * 0.96)
            g.apply_transform(trimesh.transformations.rotation_matrix(a, [0, 0, 1]))
            nrm = np.array([d[1], -d[0]]) / max(1e-9, np.hypot(*d))
            g.apply_translation([p[0] + nrm[0] * 0.012, p[1] + nrm[1] * 0.012, z])
            S.ekle(boya(g, KOYU, 0.4, 0.7), f'track_{yan}')
        # tekerler: ön dişli (1), 5 yol tekeri (2..6), arka avara (7)
        tek = [(x_on, r_dis + 0.035, r_dis)] + [(x, r_yol + 0.035, r_yol) for x in np.linspace(0.55, -0.62, 5)] + [(x_arka, r_dis + 0.035, r_dis)]
        for k, (x, yc, r) in enumerate(tek, start=1):
            ad = f'wheel_{yan}{k}'
            S.dugum(ad, konum=(x, yc, z))
            S.ekle(teker(r, PW * 0.78, KOYU, GRI, lug=12 if r > 0.22 else 8, jant_oran=0.7, dis=r > 0.22), ad)
        # palet modülü üst çamurluk + yan zırh
        S.ekle(boya(pah_kutu(2.30, 0.05, PW + 0.08, 0.02, x=-0.01, y=2 * r_dis + 0.12, z=z), YESIL, 0.2, 0.6))
        S.ekle(boya(pah_kutu(1.70, 0.22, 0.04, 0.015, x=-0.02, y=r_dis + 0.18, z=z + s * (PW / 2 + 0.03)), YESIL, 0.2, 0.6))
    # orta gövde (batarya/motor modülü)
    S.ekle(boya(pah_kutu(2.20, 0.42, IZ - PW - 0.04, 0.05, x=0.0, y=0.48, ust_pah=0.08), YESIL, 0.2, 0.55))
    S.ekle(boya(zarf([[1.10, 0.30, -0.36], [1.10, 0.30, 0.36], [1.22, 0.45, -0.34], [1.22, 0.45, 0.34], [1.10, 0.69, -0.36], [1.10, 0.69, 0.36]]), YESIL, 0.2, 0.55))
    S.ekle(boya(pah_kutu(2.0, 0.06, 1.95, 0.02, x=0.0, y=0.72), KOYU, 0.3, 0.6))                         # yük platformu
    for x in np.linspace(-0.8, 0.8, 5):
        S.ekle(boya(kutu(0.04, 0.04, 1.90, x=x, y=0.77), GRI, 0.6, 0.4))                                 # bağlama rayları
    # uzaktan kumandalı sensör kulesi
    S.ekle(boya(silindir(0.30, 0.10, 'y', 28, x=0.25, y=0.82), KOYU, 0.4, 0.5))
    S.ekle(boya(pah_kutu(0.52, 0.30, 0.46, 0.05, x=0.27, y=1.02), YESIL, 0.2, 0.55))
    S.ekle(boya(pah_kutu(0.22, 0.20, 0.30, 0.03, x=0.58, y=1.04), GRI, 0.5, 0.4))                         # EO kafası
    for zz in (-0.07, 0.07):
        S.ekle(boya(silindir(0.05, 0.03, 'x', 18, x=0.70, y=1.06, z=zz), CAM, 0.8, 0.1))
    S.ekle(boya(boru([0.10, 1.17, 0.20], [0.08, 1.95, 0.22], 0.012, 6), SIYAH, 0.3, 0.5))                 # anten
    S.ekle(boya(boru([-0.85, 0.75, -0.75], [-0.88, 1.65, -0.78], 0.010, 6), SIYAH, 0.3, 0.5))
    for s in (-1, 1):   # farlar
        S.ekle(boya(kutu(0.03, 0.08, 0.16, x=1.13, y=0.58, z=s * 0.22), (0.95, 0.95, 0.88, 1.0), 0.0, 0.2))
    return S


# ---------- 3. Teslimat robotu (6 teker, skid) ----------
def rover_bot():
    BEYAZ, SIYAH, GRI, TURUNCU, CAM = (0.93, 0.94, 0.95, 1.0), (0.08, 0.08, 0.09, 1.0), (0.55, 0.56, 0.58, 1.0), (1.0, 0.42, 0.05, 1.0), (0.08, 0.1, 0.12, 1.0)
    R, Wt, IZ = 0.10, 0.07, 0.50
    S = Sahne('rover', {'drive': 'skid', 'wheel_r': R, 'wheelbase': 0.50, 'track': IZ, 'kind': 'rover_bot',
                        'cockpit': [0.37, R + 0.25, 0.0], 'sensor': [0.37, R + 0.33, 0.0]})
    yc = R
    S.ekle(boya(pah_kutu(0.66, 0.16, 0.44, 0.04, x=0.0, y=yc + 0.07), SIYAH, 0.2, 0.7))                  # alt şasi
    S.ekle(boya(pah_kutu(0.70, 0.30, 0.56, 0.06, x=0.0, y=yc + 0.29, ust_pah=0.10), BEYAZ, 0.05, 0.35))   # gövde
    S.ekle(boya(pah_kutu(0.60, 0.035, 0.48, 0.03, x=-0.01, y=yc + 0.455), BEYAZ, 0.05, 0.3))              # kapak
    S.ekle(boya(kutu(0.62, 0.006, 0.50, x=-0.01, y=yc + 0.437), GRI, 0.2, 0.5))                           # kapak çizgisi
    S.ekle(boya(kutu(0.012, 0.03, 0.40, x=0.352, y=yc + 0.33), (0.85, 0.95, 1.0, 1.0), 0.0, 0.15))        # ön ışık şeridi
    for zz in (-0.16, 0.0, 0.16):
        S.ekle(boya(silindir(0.016, 0.01, 'x', 12, x=0.353, y=yc + 0.25, z=zz), CAM, 0.8, 0.1))          # kameralar
    for s in (-1, 1):
        S.ekle(boya(silindir(0.016, 0.01, 'z', 12, x=0.12, y=yc + 0.30, z=s * 0.282), CAM, 0.8, 0.1))
        S.ekle(boya(kutu(0.010, 0.03, 0.10, x=-0.352, y=yc + 0.30, z=s * 0.16), (0.9, 0.08, 0.06, 1.0), 0.0, 0.3))
    # bayrak direği + turuncu bayrak
    S.ekle(boya(boru([-0.26, yc + 0.47, 0.20], [-0.26, yc + 1.30, 0.20], 0.006, 6), SIYAH, 0.3, 0.5))
    S.ekle(boya(zarf([[-0.26, yc + 1.30, 0.20], [-0.26, yc + 1.16, 0.20], [-0.42, yc + 1.23, 0.20], [-0.26, yc + 1.30, 0.205], [-0.26, yc + 1.16, 0.205], [-0.42, yc + 1.23, 0.205]]),
                TURUNCU, 0.0, 0.6))
    # 6 teker (rocker-bogie görünümü)
    for s, yan in ((-1, 'l'), (1, 'r')):
        S.ekle(boya(boru([0.25, yc, s * (IZ / 2 - 0.05)], [-0.25, yc, s * (IZ / 2 - 0.05)], 0.018, 8), SIYAH, 0.3, 0.6))
        for ad, x in (('f', 0.25), ('m', 0.0), ('r', -0.25)):
            d = f'wheel_{ad}{yan}'
            S.dugum(d, konum=(x, yc, s * IZ / 2))
            S.ekle(teker(R, Wt, SIYAH, GRI, lug=10, jant_oran=0.55), d)
    return S


MODELLER = {'rover_4x4': rover_4x4, 'rover_ugv': rover_ugv, 'rover_bot': rover_bot}


def rapor(out_path):
    s = trimesh.load(str(out_path), force='scene')
    tri = sum(len(g.faces) for g in s.geometry.values())
    ext = (s.bounds[1] - s.bounds[0]).round(3).tolist()
    import pygltflib
    g = pygltflib.GLTF2().load(str(out_path))
    adlar = [n.name for n in g.nodes if n.name and not re.search(r'_v\d+$', n.name)]
    return {'tri': tri, 'bytes': Path(out_path).stat().st_size, 'ext_m': ext, 'wheels': sorted(a for a in adlar if a.startswith('wheel_')),
            'steer': sorted(a for a in adlar if a.startswith('steer_')), 'tracks': sorted(a for a in adlar if a.startswith('track_'))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    secim = {s for s in a.only.split(',') if s}
    for ad, fn in MODELLER.items():
        if secim and ad not in secim:
            continue
        sahne = fn()
        sahne.bitir()
        out = a.out / f'{ad}.glb'
        glb_yaz(sahne, out)
        r = rapor(out)
        print(f'== {ad}', json.dumps(r, ensure_ascii=False))
        if r['tri'] > TRI_BUTCE:
            print(f'   UYARI: üçgen bütçesi aşıldı ({r["tri"]} > {TRI_BUTCE})', file=sys.stderr)


if __name__ == '__main__':
    main()
