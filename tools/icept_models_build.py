#!/usr/bin/env python3
"""ICEPT önleyici + hedef dron modelleri → SIMUMAV için optimize GLB (static/simumav/models/<ad>.glb).

Kullanım:
  .venv/bin/python -I tools/icept_models_build.py --ref ~/mt-work/icept-ref --work /tmp/icept-mdl --out static/simumav/models [--only icept_x4,sting]
Gereksinim (yalnız geliştirme makinesi): trimesh, numpy, pillow, fast_simplification, pygltflib; Altius için node + geçici
`three@0.170` ve `node-unrar-js` (`cd /tmp/icept-node && npm i three@0.170.0 node-unrar-js`; NODE_PATH=/tmp/icept-node/node_modules —
depoya node_modules girmez). Node adımları ayrı betiklerdir: tools/unrar_extract.mjs (RAR çıkarma), tools/fbx_dump.mjs (FBX → JSON).

Girdiler güvenilmeyen veridir: arşivler `--work/<ad>/` altında kendi boş dizinlerine çıkarılır (zip: zipfile, '..'/mutlak yol reddedilir;
rar: tools/unrar_extract.mjs), arşivden gelen hiçbir betik çalıştırılmaz; dosyalar yalnız ayrıştırılır.

Konvansiyon (static/simumav/models/*.glb ile aynı): glTF metre, Y yukarı, burun +X, sağ +Z; orijin = modelin sınır kutusu merkezi;
pervaneler ayrı düğüm `prop_1..N` (orijin göbek merkezi, rotation kimlik — dönüş ağa pişirilir; pala fazı 45°'ye çevrilir ki düğüm yerel
sınır kutusunun en ince ekseni kesin olarak dönüş ekseni olsun: flightsim3d bu ekseni seçer). Diğer düğümlerin adında prop/rotor geçmez;
ana gövde `body`. Diğer düğümler: orijin kendi sınır kutusu merkezinde (dönüş yok). Üçgen bütçesi ≤ 55 k (depo testi ≤ 60 k); dokular ≤ 1024² JPEG;
Draco/meshopt YOK.

Modeller:
  icept_x4     final_assembly.stp (metre, üçgen ağ STEP; 8 parça / 17 yerleşim) → tools/step_mapped2glb.py; 4 pervaneli tailsitter,
               çekici pervaneler burun tarafında; X kanat görünümü (yukarı = iki kol arasındaki açıortay)
  p1sun        p1sun.glb (ayakta duran tailsitter: burun +Y) → blade1-4 = prop_1..4
  sting        stinger.glb (tek mesh, ölçek 0,01 ve kayık) → bağlantısız bileşenlerden 4 pervane ayrılır; uzunluk 0,45 m
  tgt_sw300    Switchblade 300 glb.zip → swblsc.glb (fırlatma tüpü atılır; fan+blade1+blade2 = prop_1); uzunluk 0,50 m
  tgt_lancet   Zala Lancet OBJ zip (gövde + itici pervane nesnesi; PBR dokular) ; uzunluk 1,65 m
  tgt_altius   Altius 600M altius-zip/altius-fbx (ZIP; yoksa altius-fbx.rar) → FBX (three.js FBXLoader, node) → JSON → GLB; pervane bileşenlerden ayrılır; uzunluk 1,02 m
  tgt_octopus  Octopus 100 OBJ+MTL (düz renkler; twxtures.zip'teki 3 JPEG UV atlası değil, genel döşeme dokusu → kullanılmadı);
               uzunluk 0,75 m kabulü (motor çanı Ø 35 mm → 28xx FPV motoru)
"""
import argparse
import io
import json
import math
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

import fast_simplification

ARAC = Path(__file__).resolve().parent
KOK = ARAC.parent
sys.path.insert(0, str(ARAC))   # -I betik dizinini sys.path'e koymaz; yalnız kendi tools/ dizinimiz
import step_mapped2glb as smg   # noqa: E402

TRI_BUTCE = 55_000     # tests/test_simumav_models.py: ≤ 60 k üçgen, ≤ 3 MB, doku ≤ 1024²
DOKU_MAX = 1024
DOKU_YAN = 1024        # normal / metal-pürüzlülük dokuları
JPEG_Q = 85
NODE_PATH = os.environ.get('NODE_PATH', '/tmp/icept-node/node_modules')

DRONES = Path('targets/Drones')
KAYNAK = {
    'sw300_zip': DRONES / 'Switchblade 300 Drone SC' / 'glb.zip',
    'lancet_zip': DRONES / 'Zala Lancet' / 'Lancet_drone_OBJ.zip',
    'altius_rar': DRONES / 'Altius 600m Drone' / 'altius-fbx.rar',
    'octo_obj': DRONES / 'Octobus 100' / 'Octopus-100-Military-Interceptor-Drone-UAV-FPV-Game-Ready-PBR-High-Detail-2021-obj.obj',
    'octo_tex_zip': DRONES / 'Octobus 100' / 'twxtures.zip',
}


# ---------- arşiv ----------
def zip_cikar(arsiv, hedef):
    """Güvenli zip çıkarma: hedef dizin dışına yazan ('..', mutlak) girdiler reddedilir. Zaten çıkarılmışsa dokunmaz."""
    hedef = Path(hedef)
    if hedef.is_dir() and any(hedef.iterdir()):
        return hedef
    hedef.mkdir(parents=True, exist_ok=True)
    kok = hedef.resolve()
    with zipfile.ZipFile(arsiv) as z:
        for i in z.infolist():
            ad = i.filename.replace('\\', '/')
            yol = (kok / ad).resolve()
            if kok not in yol.parents and yol != kok:
                print(f'  reddedildi (dizin dışı): {ad}', file=sys.stderr)
                continue
            if i.is_dir():
                yol.mkdir(parents=True, exist_ok=True)
                continue
            yol.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as kaynak, open(yol, 'wb') as cikti:
                shutil.copyfileobj(kaynak, cikti)
    return hedef


def rar_cikar(arsiv, hedef):
    hedef = Path(hedef)
    if hedef.is_dir() and any(hedef.iterdir()):
        return hedef
    subprocess.run(['node', str(ARAC / 'unrar_extract.mjs'), str(arsiv), str(hedef)], check=True, stdout=sys.stderr, env=dict(os.environ, NODE_PATH=NODE_PATH),
                   cwd=str(KOK))
    return hedef


# ---------- doku / malzeme ----------
def _jpeg(img, en):
    img = img.convert('RGB')
    if max(img.size) > en:
        r = en / max(img.size)
        img = img.resize((max(1, round(img.size[0] * r)), max(1, round(img.size[1] * r))), Image.LANCZOS)
    b = io.BytesIO()
    img.save(b, format='JPEG', quality=JPEG_Q, optimize=True)
    b.seek(0)
    out = Image.open(b)
    out.load()
    return out   # format == 'JPEG' → trimesh yeniden PNG'ye çevirmez


def malzeme_kucult(mat, _gor=None):
    """PBRMaterial dokularını ≤ 1024² JPEG'e indir (alfa kullanılmıyorsa); aynı malzeme nesnesi bir kez işlenir."""
    _gor = {} if _gor is None else _gor
    if mat is None or id(mat) in _gor:
        return mat
    _gor[id(mat)] = True
    if isinstance(mat, trimesh.visual.material.SimpleMaterial):
        return mat
    alfa = getattr(mat, 'alphaMode', None) in ('BLEND', 'MASK')
    for at, en in (('baseColorTexture', DOKU_MAX), ('metallicRoughnessTexture', DOKU_YAN), ('normalTexture', DOKU_YAN),
                   ('occlusionTexture', DOKU_YAN), ('emissiveTexture', DOKU_YAN)):
        img = getattr(mat, at, None)
        if img is None or not hasattr(img, 'size'):
            continue
        if at == 'baseColorTexture' and alfa and img.mode in ('RGBA', 'LA'):
            if max(img.size) > en:
                r = en / max(img.size)
                img = img.resize((round(img.size[0] * r), round(img.size[1] * r)), Image.LANCZOS)
            setattr(mat, at, img)
            continue
        setattr(mat, at, _jpeg(img, en))
    return mat


def pbr(renk_hex=None, doku=None, ad=None, metal=0.0, rough=0.7, **ek):
    rgba = smg.srgb_lineer(renk_hex) if renk_hex else (1.0, 1.0, 1.0, 1.0)
    return trimesh.visual.material.PBRMaterial(name=ad, baseColorFactor=[int(round(c * 255)) for c in rgba], metallicFactor=metal,
                                               roughnessFactor=rough, baseColorTexture=doku, **ek)


# ---------- ağ işlemleri ----------
def seyrelt(mesh, hedef, sinir_koru=True):
    """Üçgen sayısını hedefe indir. Dokulu ağda UV korunur: fast_simplification çöküş geçmişi yeniden oynatılır (replay) ve her yeni
    köşeye eşlendiği özgün köşenin UV'si verilir; UV dikişleri (ağ sınırları) korunur (preserve_border)."""
    F0 = np.asarray(mesh.faces)
    if len(F0) <= hedef:
        return mesh
    V = np.asarray(mesh.vertices, dtype=np.float32)
    F = np.ascontiguousarray(F0, dtype=np.int32)
    uv = getattr(mesh.visual, 'uv', None) if mesh.visual.kind == 'texture' else None
    N = normal(mesh)
    if uv is None and N is None:
        V2, F2 = fast_simplification.simplify(V, F, target_count=int(hedef))
        out = trimesh.Trimesh(V2, F2, process=False)
        out.visual = trimesh.visual.TextureVisuals(material=getattr(mesh.visual, 'material', None)) if mesh.visual.kind == 'texture' else mesh.visual
        return out
    _, _, coll = fast_simplification.simplify(V, F, target_count=int(hedef), return_collapses=True, preserve_border=sinir_koru and uv is not None)
    V2, F2, esle = fast_simplification.replay_simplification(V, F, coll)
    ok = esle >= 0
    N2 = None
    if N is not None:   # kaynak normalleri (sanatçı normalleri) aynı eşlemeyle taşınır
        N2 = np.zeros((len(V2), 3))
        N2[esle[ok]] = N[ok]
    out = trimesh.Trimesh(V2, F2, vertex_normals=N2, process=False)
    if uv is not None:
        uv2 = np.zeros((len(V2), 2))
        uv2[esle[ok]] = np.asarray(uv)[ok]
        out.visual = trimesh.visual.TextureVisuals(uv=uv2, material=mesh.visual.material)
    else:
        out.visual = mesh.visual
    if N2 is not None:
        out.vertex_normals = N2
    return out


def normal(mesh):
    """Kaynakta (glTF NORMAL / OBJ vn / FBX) gelen köşe normalleri varsa döndür; yoksa None (çıktı düz gölgeli kalır — mevcut
    static/simumav/models GLB'leri gibi)."""
    return np.asarray(mesh._cache.cache['vertex_normals']) if 'vertex_normals' in mesh._cache.cache else None


def bilesenler(mesh, tol=1e-6):
    """Konuma göre (UV dikişleri yok sayılarak) bağlantılı bileşen etiketleri (yüz başına)."""
    V, F = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    _, inv = np.unique(np.round(V / tol).astype(np.int64), axis=0, return_inverse=True)
    Fm = inv.reshape(-1)[F]
    m = trimesh.Trimesh(np.zeros((Fm.max() + 1, 3)), Fm, process=False)
    return trimesh.graph.connected_component_labels(m.face_adjacency, node_count=len(Fm))


def alt_ag(mesh, yuzler):
    """Yüz alt kümesi → yeni Trimesh (UV + malzeme korunur)."""
    F = np.asarray(mesh.faces)[yuzler]
    kul, ters = np.unique(F.reshape(-1), return_inverse=True)
    N = normal(mesh)
    m = trimesh.Trimesh(np.asarray(mesh.vertices)[kul], ters.reshape(-1, 3), vertex_normals=None if N is None else N[kul], process=False)
    if mesh.visual.kind == 'texture':
        uv = getattr(mesh.visual, 'uv', None)
        m.visual = trimesh.visual.TextureVisuals(uv=None if uv is None else np.asarray(uv)[kul], material=mesh.visual.material)
    if N is not None:
        m.vertex_normals = N[kul]
    return m


def alan_merkezi(mesh):
    a = mesh.area_faces
    return (mesh.triangles_center * a[:, None]).sum(0) / max(a.sum(), 1e-12)


def pervane_bul(mesh, eksen, n=4, min_cap=0.1, ince=0.15):
    """Bağlantısız bileşenlerden pervane diskleri: eksene göre ince (eksenel boy < ince × düzlem içi boy), düzlem içi boy > min_cap ×
    model boyu, aynı yüz sayısında `n` tane. → [(yüz indeksleri, göbek)] (göbek = alan ağırlıklı merkez; simetrik pervane)."""
    lab = bilesenler(mesh)
    eksen = np.asarray(eksen, float) / np.linalg.norm(eksen)
    L = float(np.ptp(mesh.vertices, axis=0).max())
    gruplar = {}
    for i in range(lab.max() + 1):
        f = np.where(lab == i)[0]
        if len(f) < 50:
            continue
        P = np.asarray(mesh.vertices)[np.asarray(mesh.faces)[f].reshape(-1)]
        eks = np.ptp(P @ eksen)
        dz = P - np.outer(P @ eksen, eksen)
        duz = np.ptp(dz, axis=0).max()
        if duz > min_cap * L and eks < ince * duz:
            gruplar.setdefault(len(f), []).append(f)
    aday = [g for g in gruplar.values() if len(g) == n]
    if not aday:
        return []
    g = max(aday, key=lambda g: len(g[0]))
    return [(f, alan_merkezi(alt_ag(mesh, f))) for f in g]


def faz45(V, k=0):
    """→ (V', 3×3 dönüş). Pervane ağını (yerel, göbek orijinde) k ekseni etrafında döndür: düzlem içi ana doğrultu (PCA) diğer iki eksenin açıortayına gelsin."""
    i, j = [x for x in range(3) if x != k]
    P = V[:, [i, j]] - V[:, [i, j]].mean(0)
    w, U = np.linalg.eigh(P.T @ P)
    b = U[:, int(np.argmax(w))]
    aci = math.atan2(1, 1) - math.atan2(b[1], b[0])
    c, s = math.cos(aci), math.sin(aci)
    Rm = np.eye(3)
    Rm[i, i], Rm[i, j], Rm[j, i], Rm[j, j] = c, -s, s, c
    return V @ Rm.T, Rm


def normal_sarim_uyumu(V, F, N):
    """Kaynak köşe normali komşu yüzlerin sarım (winding) normaliyle ters yöndeyse çevir: tek yüzlü çizimde görünen yüz sarımla
    belirlenir; ters normal o yüzü karanlık gösteriyordu (Lancet kanatlarında kaynak kusuru)."""
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    ort = np.zeros_like(N)
    for k in range(3):
        np.add.at(ort, F[:, k], fn)
    N = N.copy()
    ters = (ort * N).sum(1) < 0
    N[ters] *= -1
    return N


# ---------- sahne yazımı ----------
class Parca:
    def __init__(self, ad, mesh, gobek=None):
        self.ad, self.mesh, self.gobek = ad, mesh, None if gobek is None else np.asarray(gobek, float)


def eksen_matrisi(ileri, yukari):
    """Kaynak çerçevede burun (ileri) ve yukarı vektörleri → 3×3 (kaynak → glTF: X burun, Y yukarı, Z sağ = X × Y)."""
    f = np.asarray(ileri, float)
    f /= np.linalg.norm(f)
    u = np.asarray(yukari, float)
    u = u - f * (u @ f)
    u /= np.linalg.norm(u)
    return np.vstack([f, u, np.cross(f, u)])


def model_yaz(parcalar, R, out, olcek=1.0, uzunluk=None, eksen_k=0):
    """Parçalar (kaynak dünya koordinatında) → R (3×3) + ölçek → merkezleme → GLB. `uzunluk` verilirse ölçek, X (burun) boyu bu olacak
    şekilde seçilir. Pervane parçaları göbekte, rotation kimlik, faz 45°."""
    R = np.asarray(R, float)
    if uzunluk:
        P = np.vstack([np.asarray(p.mesh.vertices) @ R.T for p in parcalar])
        olcek = uzunluk / float(np.ptp(P[:, 0]))
    M = R * olcek
    nrm = {}
    for p in parcalar:
        N = normal(p.mesh)
        p.mesh = p.mesh.copy()
        p.mesh.vertices = np.asarray(p.mesh.vertices) @ M.T
        if N is not None:
            nrm[id(p)] = N @ R.T
        if p.gobek is not None:
            p.gobek = M @ p.gobek
    P = np.vstack([p.mesh.vertices for p in parcalar])
    c = (P.min(0) + P.max(0)) / 2
    sc = trimesh.Scene()
    gor = {}
    for p in parcalar:
        malzeme_kucult(getattr(p.mesh.visual, 'material', None), gor)
        N = nrm.get(id(p))
        if p.gobek is not None:
            o = p.gobek - c
            V = np.asarray(p.mesh.vertices) - c - o
            V, Rm = faz45(V, eksen_k)
            if N is not None:   # aynı dönüş normallere
                N = N @ Rm.T
        else:
            V = np.asarray(p.mesh.vertices) - c
            o = (V.min(0) + V.max(0)) / 2
            V = V - o
        if N is not None:
            N = normal_sarim_uyumu(V, np.asarray(p.mesh.faces), N)
        m = trimesh.Trimesh(V, p.mesh.faces, visual=p.mesh.visual, vertex_normals=N, process=False)
        if N is not None:
            m.vertex_normals = N
        sc.add_geometry(m, node_name=p.ad, geom_name=f'{p.ad}_g', parent_node_name=sc.graph.base_frame, transform=smg._tasima(o))
    data = sc.export(file_type='glb')
    Path(out).write_bytes(data)
    return olcek


# ---------- rapor ----------
def rapor(path):
    import pygltflib
    g = pygltflib.GLTF2().load(str(path))
    s = trimesh.load(str(path), force='scene')
    tri = sum(len(x.faces) for x in s.geometry.values())
    lo, hi = s.bounds
    adlar = [n.name for n in g.nodes if n.name]
    pr = []
    for nd in s.graph.nodes_geometry:
        if not nd.startswith('prop_'):
            continue
        T, gn = s.graph.get(nd)
        V = np.asarray(s.geometry[gn].vertices)
        b = np.ptp(V, axis=0)
        k = int(np.argmin(b))
        rr = float(np.linalg.norm(np.delete(V, k, axis=1), axis=1).max())
        pr.append({'ad': nd, 'gobek': np.round(T[:3, 3], 3).tolist(), 'r': round(rr, 3), 'eksen': 'xyz'[k],
                   'rot_kimlik': bool(np.allclose(T[:3, :3], np.eye(3), atol=1e-6))})
    dok = [(im.mimeType, g.bufferViews[im.bufferView].byteLength) for im in g.images]
    return {'dosya': str(path), 'MB': round(Path(path).stat().st_size / 1e6, 2), 'ucgen': tri, 'boy_m': np.round(hi - lo, 3).tolist(),
            'merkez': np.round((hi + lo) / 2, 3).tolist(), 'dugumler': adlar, 'pervaneler': sorted(pr, key=lambda p: p['ad']), 'dokular': dok}


# ---------- modeller ----------
def m_icept_x4(a, out):
    parcalar, yer = smg.oku(a.ref / 'final_assembly.stp')
    adlar = smg.siniflandir(parcalar, yer)
    # üçgen bütçesi (yerleşimler sayılarak ≤ TRI_BUTCE): > 1000 üçgenli benzersiz parçalar orantılı seyreltilir. STEP POLY_LOOP
    # köşeleri paylaşılmıyor olabilir: önce köşeler birleştirilir (birleşmemiş "üçgen çorbası" seyreltilince paramparça olur)
    say = {}
    for mid, _ in yer:
        say[mid] = say.get(mid, 0) + 1
    toplam = sum(len(parcalar[m][1]) * k for m, k in say.items())
    f = min(1.0, TRI_BUTCE / toplam)
    for mid in say:
        V, F = parcalar[mid]
        if f < 1.0 and len(F) > 1000:
            mm = trimesh.Trimesh(V, F, process=True)
            V2, F2 = fast_simplification.simplify(mm.vertices.astype(np.float32), mm.faces.astype(np.int32), target_count=max(1000, int(len(F) * f)))
            parcalar[mid] = (V2.astype(float), F2.astype(np.int64))
    adlar = smg.siniflandir(parcalar, yer)   # pervane göbeği (sınır kutusu merkezi) seyreltilmiş ağdan
    lo, hi = smg.sinir_kutusu(parcalar, yer)
    c = (lo + hi) / 2
    gob = [(T @ np.append(piv, 1))[:3] for (mid, T), (ad, rol, piv) in zip(yer, adlar) if rol == 'prop']
    T0, piv0 = next((T, piv) for (mid, T), (ad, rol, piv) in zip(yer, adlar) if rol == 'prop')
    mid0 = next(mid for (mid, T), (ad, rol, piv) in zip(yer, adlar) if rol == 'prop')
    eks = T0[:3, int(np.argmin(np.ptp(parcalar[mid0][0], axis=0)))]
    eks = eks / np.linalg.norm(eks)
    G = np.array(gob)
    f = eks * np.sign((G.mean(0) - c) @ eks)        # burun: çekici pervanelerin olduğu uç
    ax = G.mean(0)                                  # gövde ekseni bu noktadan geçer (4'lü simetri)
    r = [(g - ax) - f * ((g - ax) @ f) for g in G]
    r = [v / np.linalg.norm(v) for v in r]
    # X görünümü: yukarı = komşu iki kolun açıortayı; 4 açıortaydan STEP +Z'ye en yakın olanı (belirlenimci seçim)
    aci = sorted(r, key=lambda v: math.atan2(np.cross(r[0], v) @ f, r[0] @ v))
    diag = [(aci[i] + aci[(i + 1) % 4]) for i in range(4)]
    diag = [d / np.linalg.norm(d) for d in diag]
    up = max(diag, key=lambda d: d @ np.array([0, 0, 1.0]) + 1e-3 * (d @ np.array([1.0, 0, 0])))
    R = eksen_matrisi(f, up)
    lo2, hi2 = smg.sinir_kutusu(parcalar, yer, np.block([[R, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    kok = np.eye(4)
    kok[:3, :3] = R
    kok[:3, 3] = -(lo2 + hi2) / 2
    # tek yerleşen parçaların adları (geometrik kural): kanat (en geniş radyal), gövde (en uzun eksenel), öndekiler burun, arkadakiler kuyruk
    tek = []
    for i, ((mid, T), (ad, rol, piv)) in enumerate(zip(yer, adlar)):
        if rol == 'body' and (ad == 'body' or ad.startswith('part_')):
            V = parcalar[mid][0] @ (kok @ T)[:3, :3].T + (kok @ T)[:3, 3]
            tek.append((i, V[:, 0].min(), V[:, 0].max(), np.ptp(V[:, 1:], axis=0).max()))
    kanat = max(tek, key=lambda t: t[3])
    kalan = [t for t in tek if t is not kanat]
    govde = max(kalan, key=lambda t: t[2] - t[1])
    on = sorted([t for t in kalan if t is not govde and (t[1] + t[2]) / 2 > (govde[1] + govde[2]) / 2], key=lambda t: t[1])
    arka = sorted([t for t in kalan if t is not govde and (t[1] + t[2]) / 2 <= (govde[1] + govde[2]) / 2], key=lambda t: -t[2])
    yeni = {kanat[0]: 'wings', govde[0]: 'body'}
    for k, t in enumerate(on):
        yeni[t[0]] = 'nose' if k == 0 else ('nose_tip' if k == len(on) - 1 else f'nose_{k + 1}')
    for k, t in enumerate(arka):
        yeni[t[0]] = 'tail' if k == 0 else f'tail_{k + 1}'
    adlar = [(yeni.get(i, x[0]), x[1], x[2]) for i, x in enumerate(adlar)]
    sc = smg.glb_kur(parcalar, yer, adlar, kok)
    Path(out).write_bytes(sc.export(file_type='glb'))
    return {'not': 'STEP metre (ölçek 1); burun = çekici pervanelerin olduğu uç (STEP −Y)', 'yukari_step': np.round(up, 3).tolist()}


def _glb_parcalar(yol, atla=()):
    """Hazır GLB → {düğüm adı: Trimesh (dünya koordinatında)}."""
    s = trimesh.load(str(yol), force='scene')
    out = {}
    for nd in s.graph.nodes_geometry:
        if nd in atla:
            continue
        T, gn = s.graph.get(nd)
        out[nd] = donustur(s.geometry[gn], T)
    return out


def donustur(mesh, T):
    """Kopya + 4×4 dönüşüm; kaynak normalleri (trimesh copy() önbelleği boşaltır) korunur ve döndürülür."""
    N = normal(mesh)
    m = mesh.copy()
    m.apply_transform(T)
    if N is not None:
        A = np.linalg.inv(np.asarray(T, float)[:3, :3]).T
        N = N @ A.T
        m.vertex_normals = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    return m


def gorunum(mesh, visual):
    """visual ata; normaller korunur (atama önbelleği boşaltır)."""
    N = normal(mesh)
    mesh.visual = visual
    if N is not None:
        mesh.vertex_normals = N
    return mesh


# ayakta duran tailsitter (burun +Y): yukarı = −X−Z açıortayı → X düzeni; kamera/anten tarafı (+X+Z) alta gelir
R_AYAKTA = eksen_matrisi([0, 1, 0], [-1, 0, -1])


def m_p1sun(a, out):
    p = _glb_parcalar(a.ref / 'p1sun.glb')
    parca = [Parca('body', p['body']), Parca('camera', p['camera'])]
    for i in range(1, 5):
        m = p[f'blade{i}']
        parca.append(Parca(f'prop_{i}', m, (m.bounds[0] + m.bounds[1]) / 2))
    model_yaz(parca, R_AYAKTA, out, olcek=1.0)
    return {'not': 'ölçek 1 (kaynak zaten metre; boy 0,448 m)'}


def m_sting(a, out):
    p = _glb_parcalar(a.ref / 'stinger.glb')
    m = next(iter(p.values()))
    pr = pervane_bul(m, [0, 1, 0], n=4)
    maske = np.ones(len(m.faces), bool)
    parca = []
    for i, (f, gobek) in enumerate(sorted(pr, key=lambda t: math.atan2(t[1][2], t[1][0]))):
        maske[f] = False
        parca.append(Parca(f'prop_{i + 1}', seyrelt(alt_ag(m, f), 1500), gobek))
    govde = seyrelt(alt_ag(m, np.where(maske)[0]), TRI_BUTCE - 4 * 1500, sinir_koru=False)   # dikiş koruması 86 k'da takılıyor, kubbe köşeli kalıyordu
    parca.insert(0, Parca('body', govde))
    olcek = model_yaz(parca, R_AYAKTA, out, uzunluk=0.45)
    return {'not': f'uzunluk 0,45 m kabulü → ölçek {olcek:.4f} (kaynak düğüm ölçeği dahil dünya birimine göre); {len(pr)} pervane bileşenlerden'}


def m_sw300(a, out):
    d = zip_cikar(a.ref / KAYNAK['sw300_zip'], a.work / 'sw300')
    p = _glb_parcalar(d / 'swblsc.glb', atla=('launcher',))   # fırlatma tüpü + sehpa atılır
    fan = p.pop('fan')
    gobek = (fan.bounds[0] + fan.bounds[1]) / 2
    prop = trimesh.util.concatenate([fan, p.pop('blade1'), p.pop('blade2')])
    ad = {'swblade': 'body', 'wingl1': 'wing_fl', 'wingr1': 'wing_fr', 'wingl2': 'wing_rl', 'wingr2': 'wing_rr', 'pivot1': 'wing_pivot_f',
          'pivot2': 'wing_pivot_r', 'rudderl': 'fin_l', 'rudderr': 'fin_r', 'pivotrul': 'fin_pivot_l', 'pivotrur': 'fin_pivot_r'}
    parca = [Parca(ad.get(k, k), v) for k, v in p.items()] + [Parca('prop_1', prop, gobek)]
    # kaynak: Y yukarı, burun +Z (itici pervane −Z ucunda)
    olcek = model_yaz(parca, eksen_matrisi([0, 0, 1], [0, 1, 0]), out, uzunluk=0.50)
    return {'not': f'uzunluk 0,50 m kabulü → ölçek {olcek:.4f} (dünya birimine göre; grup ölçeği 100 dahil)'}


def m_lancet(a, out):
    d = zip_cikar(a.ref / KAYNAK['lancet_zip'], a.work / 'lancet')
    s = trimesh.load(str(d / 'Lancet_drone.obj'), force='scene', split_object=True, group_material=False, skip_materials=True)
    geo = [g for g in s.geometry.values()]
    # pervane nesnesi: gövde ekseni (Z) boyunca en ince olan
    prop = min(geo, key=lambda g: np.ptp(g.vertices[:, 2]) / max(np.ptp(g.vertices[:, :2], axis=0).max(), 1e-9))
    kalan = [g for g in geo if g is not prop]
    govde = kalan[0] if len(kalan) == 1 else trimesh.util.concatenate(kalan)   # tek ağda concatenate normalleri düşürüyor
    tx = d / 'Textures'
    base = Image.open(tx / 'Lancet_M_Drone_BaseColor.png')
    rough = Image.open(tx / 'Lancet_M_Drone_Roughness.png').convert('L')
    metal = Image.open(tx / 'Lancet_M_Drone_Metallic.png').convert('L').resize(rough.size)
    mr = Image.merge('RGB', (Image.new('L', rough.size, 255), rough, metal))
    mat = trimesh.visual.material.PBRMaterial(name='lancet', baseColorTexture=base, metallicRoughnessTexture=mr, metallicFactor=1.0,
                                              roughnessFactor=1.0, normalTexture=Image.open(tx / 'Lancet_M_Drone_Normal.png'))
    for g in (prop, govde):
        gorunum(g, trimesh.visual.TextureVisuals(uv=getattr(g.visual, 'uv', None), material=mat))
    hub = trimesh.Trimesh(prop.vertices, prop.faces, process=False)
    gobek = alan_merkezi(hub)
    parca = [Parca('body', govde), Parca('prop_1', prop, gobek)]
    # kaynak: Y yukarı, burun −Z (itici pervane +Z ucunda)
    olcek = model_yaz(parca, eksen_matrisi([0, 0, -1], [0, 1, 0]), out, uzunluk=1.65)
    return {'not': f'uzunluk 1,65 m → ölçek {olcek:.4f}'}


def m_altius(a, out):
    # Kullanıcı ZIP'i (targets/altius-zip/altius-fbx: FBX + texture/) varsa doğrudan o; yoksa RAR (node-unrar-js) çıkarılır — içerik birebir aynı (cmp)
    zipd = a.ref / 'targets' / 'altius-zip' / 'altius-fbx'
    d = zipd if zipd.is_dir() else rar_cikar(a.ref / KAYNAK['altius_rar'], a.work / 'altius')
    fbx = next(d.rglob('*.[Ff][Bb][Xx]'))
    js = a.work / 'out' / 'altius_dump.json'
    if not js.is_file():
        js.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['node', str(ARAC / 'fbx_dump.mjs'), str(fbx), str(js)], check=True, stdout=sys.stderr, env=dict(os.environ, NODE_PATH=NODE_PATH), cwd=str(KOK))
    dump = json.loads(js.read_text())
    tex = {p.name.lower(): p for p in d.rglob('*') if p.suffix.lower() in ('.jpg', '.png')}
    ms = []
    for me in dump['meshes']:
        P = np.array(me['position'], float).reshape(-1, 3)
        Mw = np.array(me['matrixWorld'], float).reshape(4, 4).T
        P = P @ Mw[:3, :3].T + Mw[:3, 3]
        F = np.array(me['index'], np.int64).reshape(-1, 3) if me['index'] else np.arange(len(P)).reshape(-1, 3)
        uv = np.array(me['uv'], float).reshape(-1, 2) if me['uv'] else None
        harita = (me['materials'][0] or {}).get('map')
        img = Image.open(tex[Path(harita).name.lower()]) if harita and Path(harita).name.lower() in tex else None
        mat = pbr(None, img, ad='altius', metal=0.1, rough=0.6)
        N = np.array(me['normal'], float).reshape(-1, 3) @ np.linalg.inv(Mw[:3, :3]) if me.get('normal') else None
        # köşe birleştirme (konum + UV + normal aynıysa): UV dikişleri ve sert kenarlar korunur (trimesh merge_vertices normalleri atıyor)
        anahtar = [P] + ([uv] if uv is not None else []) + ([N] if N is not None else [])
        _, ilk, ters = np.unique(np.round(np.hstack(anahtar), 6), axis=0, return_index=True, return_inverse=True)
        ters = ters.reshape(-1)
        P, F = P[ilk], ters[F]
        uv = uv[ilk] if uv is not None else None
        N = N[ilk] if N is not None else None
        m = trimesh.Trimesh(P, F, vertex_normals=N, process=False)
        gorunum(m, trimesh.visual.TextureVisuals(uv=uv, material=mat))
        ms.append(m)
    m = trimesh.util.concatenate(ms) if len(ms) > 1 else ms[0]
    # kaynak (three/FBX dünya): Y yukarı, burun +Z, kanat açıklığı X; itici pervane −Z ucunda, ekseni Z
    R = eksen_matrisi([0, 0, 1], [0, 1, 0])
    lab = bilesenler(m)
    Vz = np.asarray(m.vertices)[:, 2]
    zmin, L = Vz.min(), np.ptp(Vz)
    ax = np.array([np.median(m.vertices[:, 0]), 0, 0])
    prop_f = []
    ozet = []
    for i in range(lab.max() + 1):
        f = np.where(lab == i)[0]
        P = np.asarray(m.vertices)[np.asarray(m.faces)[f].reshape(-1)]
        ozet.append((len(f), P.min(0), P.max(0)))
        # arka uçtaki (son %8) ve gövde eksenine yakın, eksenel ince bileşenler: pala + göbek
        if P[:, 2].max() < zmin + 0.08 * L:
            prop_f.append(f)
    gobek = None
    if prop_f:
        f = np.concatenate(prop_f)
        pm = alt_ag(m, f)
        b = pm.bounds
        gobek = np.array([(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2, (b[0][2] + b[1][2]) / 2])
        maske = np.ones(len(m.faces), bool)
        maske[f] = False
        parca = [Parca('body', alt_ag(m, np.where(maske)[0])), Parca('prop_1', pm, gobek)]
    else:
        parca = [Parca('body', m)]
    olcek = model_yaz(parca, R, out, uzunluk=1.02)
    return {'not': f'FBX (three.js FBXLoader) dönüştürüldü; uzunluk 1,02 m → ölçek {olcek:.6f}; pervane bileşenleri {len(prop_f)}',
            'bilesen': len(ozet)}


def _mtl_renk(yol):
    renk, ad = {}, None
    for sat in Path(yol).read_text(errors='replace').splitlines():
        t = sat.split()
        if not t:
            continue
        if t[0] == 'newmtl':
            ad = t[1]
        elif t[0] == 'Kd' and ad:
            renk[ad] = tuple(float(x) for x in t[1:4])
    return renk


def m_octopus(a, out):
    obj = a.ref / KAYNAK['octo_obj']
    renk = _mtl_renk(obj.with_suffix('.mtl'))
    # malzeme adı trimesh'ten (nesne başına tek usemtl); renk MTL Kd'den kendi PBR'ımıza (sRGB → doğrusal)
    s = trimesh.load(str(obj), force='scene', split_object=True, group_material=False)
    geo = list(s.geometry.values())
    mats = {}

    def mat(ad):
        if ad not in mats:
            r = renk.get(ad, (0.3, 0.3, 0.3))
            h = '#%02x%02x%02x' % tuple(int(round(min(max(x, 0), 1) * 255)) for x in r)
            mats[ad] = pbr(h, None, ad=ad, metal=0.15, rough=0.6)
        return mats[ad]
    ms = []
    for g in geo:
        ad = getattr(getattr(g.visual, 'material', None), 'name', None)
        m = trimesh.Trimesh(g.vertices, g.faces, process=True)   # köşeler birleşir (vt ile bölünmüş köşeler seyreltmeyi durduruyordu)
        m.visual = trimesh.visual.TextureVisuals(material=mat(ad or 'wire_115115115'))
        ms.append(m)
    # pervane nesnesi: gövde eksenine (Z) göre ince (eksenel boy < 0,05 × düzlem içi boy) nesnelerden en çok yüzlüsü (kaynakta 006:
    # 4 pervane = göbek diski + palalar + vidalar). Göbekler: nesnenin en büyük 4 bileşeninin (göbek diskleri) merkezi; her bileşen en
    # yakın göbeğe atanır.
    ince = [k for k, m in enumerate(ms) if np.ptp(m.vertices[:, 2]) < 0.05 * np.ptp(m.vertices[:, :2], axis=0).max()]
    kp = max(ince, key=lambda k: len(ms[k].faces)) if ince else None
    parca, cap_raw = [], None
    if kp is not None:
        pm_all = ms.pop(kp)
        lab = bilesenler(pm_all)
        comps = [np.where(lab == i)[0] for i in range(lab.max() + 1)]
        comps.sort(key=len, reverse=True)
        merk = lambda f: (lambda P: (P.min(0) + P.max(0)) / 2)(pm_all.vertices[pm_all.faces[f].reshape(-1)])
        gob = [merk(f) for f in comps[:4]]
        ata = {i: [] for i in range(4)}
        for f in comps:
            c = merk(f)
            ata[int(np.argmin([np.linalg.norm((c - g)[:2]) for g in gob]))].append(f)
        sira_g = sorted(range(4), key=lambda i: math.atan2(gob[i][1] - pm_all.centroid[1], gob[i][0] - pm_all.centroid[0]))
        boy = lambda f: float(np.ptp(pm_all.vertices[pm_all.faces[f].reshape(-1)], axis=0).max())
        for n, i in enumerate(sira_g):
            # vida/somun gibi küçük bileşenler (< %8 × kümenin en büyük bileşeni) atılır: görünmezler, seyreltmeyi kilitliyorlar
            enb = max(boy(f) for f in ata[i])
            pm = alt_ag(pm_all, np.concatenate([f for f in ata[i] if boy(f) >= 0.08 * enb]))
            r = float(np.linalg.norm(pm.vertices[:, :2] - gob[i][:2], axis=1).max())
            cap_raw = max(cap_raw or 0, 2 * r)
            parca.append(Parca(f'prop_{n + 1}', seyrelt(pm, 1500), gob[i]))
    toplam = sum(len(m.faces) for m in ms)
    hedef = TRI_BUTCE - sum(len(p.mesh.faces) for p in parca)
    govde = [seyrelt(m, max(60, int(len(m.faces) * hedef / toplam))) for m in ms]
    # malzemeye göre birleştir (düğüm sayısını azalt)
    grup = {}
    for g in govde:
        grup.setdefault(id(g.visual.material), []).append(g)
    gv = [trimesh.util.concatenate(v) if len(v) > 1 else v[0] for v in grup.values()]
    gv.sort(key=lambda g: -len(g.faces))
    parca = [Parca('body' if i == 0 else f'part_{i}', g) for i, g in enumerate(gv)] + parca
    # ölçek: toplam uzunluk 0,75 m kabulü — motor çanı Ø (ham 45,2) → 35 mm (28xx sınıfı FPV motoru), gövde tüpü Ø ≈ 79 mm,
    # pervane Ø ≈ 0,15 m (6"); Octopus-100'ün açık kaynaklı ölçüsü yok
    olcek = model_yaz(parca, eksen_matrisi([0, 0, 1], [0, 1, 0]), out, uzunluk=0.75)
    return {'not': f'uzunluk 0,75 m → ölçek {olcek:.6f}; pervane Ø {cap_raw * olcek if cap_raw else 0:.3f} m; motor çanı Ø {45.2 * olcek:.3f} m',
            'renkler': len(mats)}


MODELLER = {'icept_x4': m_icept_x4, 'p1sun': m_p1sun, 'sting': m_sting, 'tgt_sw300': m_sw300, 'tgt_lancet': m_lancet,
            'tgt_altius': m_altius, 'tgt_octopus': m_octopus}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--ref', type=Path, required=True, help='kullanıcı kaynak dizini (~/mt-work/icept-ref)')
    ap.add_argument('--work', type=Path, required=True, help='çalışma dizini (arşivler buraya çıkarılır)')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--only', default='', help='virgülle ayrılmış model adları')
    a = ap.parse_args(argv)
    a.ref, a.work = a.ref.expanduser().resolve(), a.work.expanduser().resolve()
    a.out.mkdir(parents=True, exist_ok=True)
    secim = [x.strip() for x in a.only.split(',') if x.strip()] or list(MODELLER)
    for ad in secim:
        out = a.out / f'{ad}.glb'
        bilgi = MODELLER[ad](a, out)
        r = rapor(out)
        r.update(bilgi or {})
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
