#!/usr/bin/env python3
"""SIMUMAV gerçekçi dron modelleri: açık kaynak Gazebo/SDF modelleri (PX4 gazebo-classic, Gazebo Fuel) ve hazır GLB'ler → optimize GLB.

Kullanım:  .venv/bin/python -I tools/simumav_models_build.py --src /tmp/smmodels-dl --out static/simumav/models [--only iris,x500]
Gereksinim (yalnız geliştirme makinesi; PROD'da çalışmaz): trimesh pycollada pygltflib fast-simplification pillow numpy.

Boru hattı (SDF): model.sdf (jinja kalıntıları temizlenir) → her <link> (pose) → her <visual> (pose; mesh DAE/STL + scale; box/cylinder)
→ pycollada ile geometri + materyal (düz renk ya da doku; `<submesh>` adıyla seçim) → Gazebo malzeme betikleri (Gazebo/Blue → "accent"
materyali; hangar kullanıcı rengini ona uygular) → fast_simplification ile üçgen bütçesi (dokusuz geometriler) → dokular ≤ 1024²
→ kök dönüşü Gazebo (X ileri, Y sol, Z yukarı) → glTF (X ileri/burun, Y yukarı, Z sağ) → trimesh GLB. Düğüm adları link adlarıdır:
`rotor_*` / `propeller*` pervaneler (flightsim3d PROP_RE), kontrol yüzeyleri `aileron_l/r`, `elevon_l/r`, `flap_l/r`, `elevator`, `rudder`
(flightsim3d CTRL_RE; left_aileron → aileron_l eşlemesi); menteşe düğümü eklem (joint) konumuna taşınır.
Boru hattı (GLB): hazır GLB → ölçek (m) + yaw düzeltmesi + yeniden adlandırma eşlemesi (rotor düğümleri) → GLB.
Çıktı: <out>/<ad>.glb ve rapor (stdout): üçgen, doku, bayt.
"""
import argparse
import io
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

try:
    import collada
    from collada import material as cmaterial
except ImportError:  # pragma: no cover
    collada = None
try:
    import fast_simplification
except ImportError:  # pragma: no cover
    fast_simplification = None

TRI_BUTCE = 55_000
DOKU_MAX = 1024
# Gazebo malzeme betikleri (media/materials/scripts/gazebo.material) → RGBA
GAZEBO_RENK = {
    'Gazebo/Blue': (0.0, 0.0, 1.0, 1.0), 'Gazebo/DarkGrey': (0.175, 0.175, 0.175, 1.0), 'Gazebo/DarkGray': (0.175, 0.175, 0.175, 1.0),
    'Gazebo/Grey': (0.7, 0.7, 0.7, 1.0), 'Gazebo/Gray': (0.7, 0.7, 0.7, 1.0), 'Gazebo/Black': (0.05, 0.05, 0.05, 1.0), 'Gazebo/White': (1.0, 1.0, 1.0, 1.0),
    'Gazebo/Red': (1.0, 0.0, 0.0, 1.0), 'Gazebo/Green': (0.0, 1.0, 0.0, 1.0), 'Gazebo/Yellow': (1.0, 1.0, 0.0, 1.0), 'Gazebo/Orange': (1.0, 0.5088, 0.0545, 1.0),
    'Gazebo/FlatBlack': (0.1, 0.1, 0.1, 1.0), 'Gazebo/Purple': (1.0, 0.0, 1.0, 1.0), 'Gazebo/SkyBlue': (0.13, 0.44, 0.7, 1.0), 'Gazebo/Turquoise': (0.0, 1.0, 1.0, 1.0),
    'Gazebo/Indigo': (0.0, 0.0, 0.5, 1.0), 'Gazebo/Gold': (0.4, 0.248, 0.02, 1.0), 'Gazebo/Wood': (0.6, 0.4, 0.2, 1.0), 'Gazebo/RedBright': (0.87, 0.26, 0.07, 1.0),
    'Gazebo/GreyTransparent': (0.7, 0.7, 0.7, 0.4), 'Gazebo/BlueTransparent': (0.0, 0.0, 1.0, 0.3), 'Gazebo/RedTransparent': (1.0, 0.0, 0.0, 0.3),
}
ACCENT = {'Gazebo/Blue', 'Gazebo/Red', 'Gazebo/Orange'}
# SDF link adı → flightsim3d CTRL_RE adı
CTRL_AD = {'left_aileron': 'aileron_l', 'right_aileron': 'aileron_r', 'left_elevon': 'elevon_l', 'right_elevon': 'elevon_r', 'left_flap': 'flap_l',
           'right_flap': 'flap_r', 'elevators': 'elevator', 'elevator': 'elevator', 'rudder': 'rudder', 'flap_left': 'flap_l', 'flap_right': 'flap_r',
           'taileron_left': 'elevator_l', 'taileron_right': 'elevator_r'}
# Gazebo (X ileri, Y sol, Z yukarı) → glTF (X ileri, Y yukarı, Z sağ): (x, y, z) → (x, z, -y)
GZ2GLTF = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=float)


# ---------- yardımcılar ----------
def pose_mat(txt):
    """SDF '<x> <y> <z> <roll> <pitch> <yaw>' → 4×4 (T · Rz · Ry · Rx)."""
    v = [float(x) for x in (txt or '0 0 0 0 0 0').split()] + [0.0] * 6
    x, y, z, r, p, w = v[:6]
    T = trimesh.transformations.translation_matrix([x, y, z])
    R = trimesh.transformations.euler_matrix(r, p, w, 'sxyz')
    return T @ R


def jinja_temizle(s):
    s = re.sub(r'\{%.*?%\}', '', s, flags=re.S)
    s = re.sub(r'\{\{.*?\}\}', '0', s, flags=re.S)
    s = re.sub(r'<\?xml[^>]*\?>', '', s)
    return s


def sdf_oku(path):
    root = ET.fromstring(jinja_temizle(Path(path).read_text(encoding='utf-8', errors='ignore')))
    return root.find('.//model') if root.tag != 'model' else root


def uri_coz(uri, model_dir):
    """model://<ad>/meshes/x.dae → model_dir/meshes/x.dae (model adı yoksayılır: dosya adıyla eşle)."""
    m = re.match(r'^(?:model|file)://[^/]+/(.+)$', uri.strip())
    rel = m.group(1) if m else uri.strip()
    p = Path(model_dir) / rel
    if p.is_file():
        return p
    hits = list(Path(model_dir).rglob(Path(rel).name))
    if not hits:
        raise FileNotFoundError(f'{uri} → {model_dir}')
    return hits[0]


def doku_kucult(img):
    img = img.convert('RGBA') if img.mode not in ('RGB', 'RGBA') else img
    if max(img.size) > DOKU_MAX:
        r = DOKU_MAX / max(img.size)
        img = img.resize((max(1, int(img.size[0] * r)), max(1, int(img.size[1] * r))), Image.LANCZOS)
    return img


def pbr(renk=None, doku=None, ad=None, metal=0.1, rough=0.6):
    m = trimesh.visual.material.PBRMaterial(name=ad, baseColorFactor=[int(round(c * 255)) for c in (renk or (0.8, 0.8, 0.8, 1.0))],
                                            metallicFactor=metal, roughnessFactor=rough, baseColorTexture=doku)
    if renk is not None and renk[3] < 0.99:
        m.alphaMode = 'BLEND'
    return m


# ---------- DAE ----------
_dae_cache = {}
_mat_cache = {}


def dokusuz(mesh):
    """Dokulu geometriyi düz renge indir (UV atılır; renk = doku ortalaması) — decimate edilebilsin diye."""
    m = getattr(mesh.visual, 'material', None)
    img = getattr(m, 'baseColorTexture', None)
    renk = (0.5, 0.5, 0.5, 1.0)
    if img is not None:
        arr = np.asarray(img.convert('RGB').resize((32, 32)), dtype=float).reshape(-1, 3).mean(axis=0) / 255.0
        renk = (float(arr[0]), float(arr[1]), float(arr[2]), 1.0)
    out = trimesh.Trimesh(mesh.vertices, mesh.faces, process=True)
    out.visual = trimesh.visual.TextureVisuals(material=pbr(renk, None, ad=getattr(m, 'name', None), metal=0.3, rough=0.5))
    return out


def dae_yukle(path):
    """→ liste[(geom_id, geom_name, Trimesh)]; birim çarpanı uygulanır (Gazebo gibi), up_axis UYGULANMAZ (Gazebo gibi)."""
    key = str(path)
    if key in _dae_cache:
        return _dae_cache[key]
    c = collada.Collada(str(path), ignore=[collada.common.DaeUnsupportedError, collada.common.DaeBrokenRefError])
    birim = float(c.assetInfo.unitmeter or 1.0)
    out, gorulen = [], set()
    for bg in c.scene.objects('geometry'):
        gid = bg.original.id
        for pi, pr in enumerate(bg.primitives()):
            if not isinstance(pr, collada.triangleset.BoundTriangleSet):
                if not hasattr(pr, 'triangleset'):
                    continue
                pr = pr.triangleset()
            if len(pr.vertex_index) == 0:
                continue
            imza = (gid, pi, len(pr.vertex_index))
            if imza in gorulen:       # SketchUp çift yüz: aynı geometri ikinci (arka yüz) materyalle → atla
                continue
            gorulen.add(imza)
            vi = np.asarray(pr.vertex_index).reshape(-1, 3)
            V = np.asarray(pr.vertex, dtype=float)[vi.reshape(-1)] * birim
            F = np.arange(len(V)).reshape(-1, 3)
            renk, doku = (0.8, 0.8, 0.8, 1.0), None
            mat = pr.material
            eff = mat.effect if mat is not None else None
            if eff is not None:
                d = eff.diffuse
                if isinstance(d, cmaterial.Map):
                    try:
                        ipath = d.sampler.surface.image.path
                        img = Path(path).parent / ipath
                        if not img.is_file():
                            hits = list(Path(path).parents[1].rglob(Path(ipath).name))
                            img = hits[0] if hits else None
                        if img is not None:
                            doku = doku_kucult(Image.open(img))
                        renk = (1.0, 1.0, 1.0, 1.0)
                    except Exception as e:  # noqa: BLE001
                        print(f'    doku okunamadı {path.name}: {e}', file=sys.stderr)
                elif isinstance(d, (tuple, list)) and len(d) >= 3:
                    renk = (float(d[0]), float(d[1]), float(d[2]), float(d[3]) if len(d) > 3 else 1.0)
                    if hasattr(eff, 'transparency') and isinstance(eff.transparency, float) and eff.transparent is not None and renk[3] >= 0.99:
                        pass
            uv = None
            if doku is not None and pr.texcoordset is not None and len(pr.texcoordset):
                ti = np.asarray(pr.texcoord_indexset[0]).reshape(-1, 3)
                uv = np.asarray(pr.texcoordset[0], dtype=float)[ti.reshape(-1)]
            mesh = trimesh.Trimesh(V, F, process=False)
            mkey = (key, mat.name if mat is not None else None, uv is not None)
            if uv is not None:
                if mkey not in _mat_cache:
                    _mat_cache[mkey] = pbr((1.0, 1.0, 1.0, 1.0), doku, ad=mat.name if mat is not None else None)   # aynı doku tek kez gömülür
                mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=_mat_cache[mkey])
            else:
                mesh.merge_vertices()
                mesh.visual = trimesh.visual.TextureVisuals(material=pbr(renk, None, ad=mat.name if mat is not None else None))
            out.append((gid, bg.original.name or gid, mesh))
    _dae_cache[key] = out
    return out


def stl_yukle(path):
    m = trimesh.load(str(path), force='mesh')
    return [(path.stem, path.stem, m)]


def kumele(mesh, hedef):
    """Köşe kümeleme (vertex clustering): açık kenarlı/çok parçalı mesh'lerde fast_simplification sınır kenarlarını koruduğu için hedefe
    inemez; ızgara hücresi büyütülerek hedefin altına inen ilk sonuç döner."""
    V, F = np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces)
    lo = mesh.bounds[0]
    ext = float((mesh.bounds[1] - lo).max()) or 1.0
    for n in (200, 150, 110, 80, 60, 44, 32, 24, 16):
        key = np.floor((V - lo) / (ext / n)).astype(np.int64)
        _, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        nv = np.zeros((inv.max() + 1, 3)); np.add.at(nv, inv, V); nv /= np.bincount(inv)[:, None]
        nf = inv[F]
        nf = nf[(nf[:, 0] != nf[:, 1]) & (nf[:, 1] != nf[:, 2]) & (nf[:, 0] != nf[:, 2])]
        if len(nf) <= hedef:
            out = trimesh.Trimesh(nv, nf, process=True)
            out.visual = mesh.visual
            return out
    return mesh


def decimate(mesh, hedef):
    if fast_simplification is None or len(mesh.faces) <= hedef:
        return mesh
    V, F = fast_simplification.simplify(np.asarray(mesh.vertices, dtype=np.float32), np.asarray(mesh.faces, dtype=np.int32), target_count=int(hedef))
    out = trimesh.Trimesh(V, F, process=True)
    out.visual = mesh.visual
    if len(out.faces) > hedef * 1.25:   # sınır kenarları yüzünden inemedi → köşe kümeleme
        out = kumele(mesh, hedef)
    return out


# ---------- SDF → sahne ----------
class Parca:
    def __init__(self, link, mesh, T, dokulu):
        self.link, self.mesh, self.T, self.dokulu = link, mesh, T, dokulu


def sdf_parcalar(sdf_path, model_dir, cfg):
    """→ (linkler{ad: T}, parçalar[Parca]) Gazebo çerçevesinde (eklem kaydırmaları uygulanmış)."""
    model = sdf_oku(sdf_path)
    linkler, parcalar = {}, []
    ad_esle = cfg.get('rename', {})
    atla = set(cfg.get('skip_links', ()))
    link_T = {}
    for ln in model.findall('link'):
        ad = ln.get('name', '')
        pose = ln.find('pose')
        T = pose_mat(pose.text if pose is not None else None)
        rel = pose.get('relative_to') if pose is not None else None
        if rel and rel in link_T:
            T = link_T[rel] @ T
        link_T[ad] = T
    # eklemler: child link düğümünü eklem konumuna taşı (menteşe), görseller geri telafi
    eklem = {}
    for jn in model.findall('joint'):
        child = (jn.findtext('child') or '').strip()
        p = jn.find('pose')
        if child and p is not None and p.text and any(abs(float(x)) > 1e-9 for x in p.text.split()):
            eklem[child] = pose_mat(p.text)
    for ln in model.findall('link'):
        ad = ln.get('name', '')
        if ad in atla or 'imu' in ad.lower() or 'airspeed' in ad.lower():
            continue
        T = link_T[ad]
        Tj = eklem.get(ad, np.eye(4))
        kisa = ad.split('::')[-1].split('/')[-1]
        dugum = ad_esle.get(kisa, CTRL_AD.get(kisa, kisa))
        linkler[dugum] = T @ Tj
        Tj_inv = np.linalg.inv(Tj)
        link_renk = cfg.get('link_colors', {}).get(dugum)
        for vis in ln.findall('visual'):
            if (vis.get('name') or '').startswith(tuple(cfg.get('skip_visual_prefix', ('LD',)))):   # Gazebo LiftDrag hata ayıklama kutuları
                continue
            vp = vis.find('pose')
            Tv = Tj_inv @ pose_mat(vp.text if vp is not None else None)
            geo = vis.find('geometry')
            if geo is None:
                continue
            renk = None
            mat = vis.find('material')
            accent = False
            if mat is not None:
                sc = mat.find('script/name')
                if sc is not None and sc.text:
                    renk = GAZEBO_RENK.get(sc.text.strip())
                    accent = sc.text.strip() in ACCENT
            if link_renk:
                renk, accent = GAZEBO_RENK.get(link_renk, renk), link_renk in ACCENT
                for tag in ('diffuse', 'ambient'):
                    e = mat.find(tag)
                    if renk is None and e is not None and e.text:
                        v = [float(x) for x in e.text.split()] + [1.0]
                        renk = tuple(v[:4])
            mesh_e = geo.find('mesh')
            if mesh_e is not None:
                uri = mesh_e.findtext('uri') or ''
                sc_txt = mesh_e.findtext('scale')
                S = np.eye(4)
                if sc_txt:
                    S = np.diag([float(x) for x in sc_txt.split()] + [1.0])
                sub = (mesh_e.findtext('submesh/name') or '').strip()
                sub_center = (mesh_e.findtext('submesh/center') or '').strip().lower() in ('true', '1')
                p = uri_coz(uri, model_dir)
                geoms = dae_yukle(p) if p.suffix.lower() == '.dae' else stl_yukle(p)
                for gid, gname, m in geoms:
                    if sub:
                        a, b = sub.lower(), (gname or gid).lower().replace('geom-', '')
                        if not (a == b or a.startswith(b) or b.startswith(a)):   # 'Propeller' ↔ 'Prop'
                            continue
                    mm = m.copy()
                    if sub and sub_center:   # Gazebo <center>: alt mesh kendi sınır kutusu merkezine taşınır
                        mm.apply_translation(-(mm.bounds[0] + mm.bounds[1]) / 2)
                    dokulu = isinstance(mm.visual, trimesh.visual.TextureVisuals) and mm.visual.uv is not None and len(mm.visual.uv)
                    if dokulu and cfg.get('decimate_textured'):
                        mm, dokulu = dokusuz(mm), False
                    if renk is not None and not dokulu:
                        mm.visual = trimesh.visual.TextureVisuals(material=pbr(renk, None, ad='accent' if accent else None, metal=0.2 if accent else 0.1))
                    elif p.suffix.lower() == '.stl' and not dokulu:
                        mm.visual = trimesh.visual.TextureVisuals(material=pbr((0.45, 0.45, 0.47, 1.0), None))
                    mm.apply_transform(S)   # ölçek geometriye (GLB'de birim metre; düğüm ölçeği yok)
                    parcalar.append(Parca(dugum, mm, Tv, bool(dokulu)))
            else:
                prim = None
                if geo.find('box') is not None:
                    sz = [float(x) for x in geo.findtext('box/size').split()]
                    prim = trimesh.creation.box(sz)
                elif geo.find('cylinder') is not None:
                    prim = trimesh.creation.cylinder(radius=float(geo.findtext('cylinder/radius')), height=float(geo.findtext('cylinder/length')), sections=24)
                elif geo.find('sphere') is not None:
                    prim = trimesh.creation.icosphere(subdivisions=2, radius=float(geo.findtext('sphere/radius')))
                if prim is not None:
                    prim.visual = trimesh.visual.TextureVisuals(material=pbr(renk or (0.1, 0.1, 0.1, 1.0), None))
                    parcalar.append(Parca(dugum, prim, Tv, False))
    return linkler, parcalar


def sahne_kur(linkler, parcalar, cfg, ekler=()):
    """Gazebo çerçevesindeki link/parçalar → trimesh Scene (glTF eksenleri, üçgen bütçesi, kök yaw/ölçek/ofset)."""
    yaw = math.radians(float(cfg.get('yaw_deg', 0)))
    olcek = float(cfg.get('scale', 1.0))
    ofs = cfg.get('offset', [0, 0, 0])
    R0 = GZ2GLTF @ trimesh.transformations.translation_matrix(ofs) @ np.diag([olcek, olcek, olcek, 1.0]) @ trimesh.transformations.rotation_matrix(yaw, [0, 0, 1])
    sc = trimesh.Scene()
    sc.graph.update(frame_to='root', frame_from=sc.graph.base_frame, matrix=R0)
    for ad, T in linkler.items():
        sc.graph.update(frame_to=ad, frame_from='root', matrix=T)
    for ek_ad, T in ekler:
        sc.graph.update(frame_to=ek_ad, frame_from='root', matrix=T)
    # üçgen bütçesi: dokusuz geometriler azaltılır — küçük parçalara taban (ince çubuklar bozulmasın), kalan bütçe büyüklere orantılı
    butce = int(cfg.get('tri_budget', TRI_BUTCE))
    taban = int(cfg.get('tri_floor', 1500))
    sabit = sum(len(p.mesh.faces) for p in parcalar if p.dokulu) + sum(min(len(p.mesh.faces), taban) for p in parcalar if not p.dokulu)
    buyuk = sum(len(p.mesh.faces) - taban for p in parcalar if not p.dokulu and len(p.mesh.faces) > taban)
    oran = min(1.0, max(0.0, (butce - sabit) / buyuk)) if buyuk else 1.0
    sayac = {}
    for p in parcalar:
        m = p.mesh
        if not p.dokulu and len(m.faces) > taban and oran < 1.0:
            m = decimate(m, taban + int((len(m.faces) - taban) * oran))
        n = sayac.get(p.link, 0)
        sayac[p.link] = n + 1
        sc.add_geometry(m, node_name=f'{p.link}_v{n}', geom_name=f'{p.link}_g{n}', parent_node_name=p.link, transform=p.T)
    return sc


def glb_yaz(sc, out_path):
    data = sc.export(file_type='glb')
    Path(out_path).write_bytes(data)
    return len(data)


def rapor(out_path):
    s = trimesh.load(str(out_path), force='scene')
    tri = sum(len(g.faces) for g in s.geometry.values())
    dokular = []
    for g in s.geometry.values():
        m = getattr(g.visual, 'material', None)
        img = getattr(m, 'baseColorTexture', None)
        if img is not None:
            dokular.append(img.size)
    ext = (s.bounds[1] - s.bounds[0]).round(3).tolist() if s.geometry else None
    import pygltflib
    g = pygltflib.GLTF2().load(str(out_path))
    adlar = [n.name for n in g.nodes if n.name]
    props = [a for a in adlar if re.search(r'prop|propeller|rotor|pervane', a, re.I) and not re.search(r'_v\d+$', a)]
    ctrl = [a for a in adlar if re.match(r'^(elevon|flap|aileron|elevator|rudder)(_?(l|r|left|right))?$', a, re.I)]
    return {'tri': tri, 'textures': dokular, 'bytes': Path(out_path).stat().st_size, 'ext_m': ext, 'props': props, 'ctrl': ctrl, 'nodes': len(adlar)}


# ---------- hazır GLB yeniden paketleme ----------
def glb_paketle(src, cfg):
    """Hazır GLB → ölçek/yaw/pitch/merkezleme geometriye uygulanır (düğüm ölçeği kalmaz); her parça kendi sınır kutusu merkezinde origin'li
    bir düğüm olur (rotor düğümleri yerinde döner); düğümler yeniden adlandırılır (rotor_*)."""
    s = trimesh.load(str(src), force='scene')
    olcek = float(cfg.get('scale', 1.0))
    yaw = math.radians(float(cfg.get('yaw_deg', 0)))
    pitch = math.radians(float(cfg.get('pitch_deg', 0)))
    R = trimesh.transformations.rotation_matrix(yaw, [0, 1, 0]) @ trimesh.transformations.rotation_matrix(pitch, [0, 0, 1]) @ np.diag([olcek, olcek, olcek, 1.0])
    if cfg.get('center', True):
        pts = np.vstack([trimesh.transformations.transform_points(s.geometry[g].bounds, R @ T) for n in s.graph.nodes_geometry for T, g in [s.graph.get(n)]])
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        c = (lo + hi) / 2
        R = trimesh.transformations.translation_matrix([-c[0], -lo[1] if cfg.get('ground') else -c[1], -c[2]]) @ R
    out = trimesh.Scene()
    esle = cfg.get('rename', {})
    for node in s.graph.nodes_geometry:
        T, gname = s.graph.get(node)
        g = s.geometry[gname].copy()
        g.apply_transform(R @ T)                       # dünya (çıktı) koordinatları
        c = (g.bounds[0] + g.bounds[1]) / 2
        g.apply_translation(-c)                        # düğüm origin'i parçanın merkezinde: rotor düğümü kendi ekseninde döner (flightsim3d/hangar)
        ad = esle.get(node, esle.get(gname, node))
        out.add_geometry(g, node_name=ad, geom_name=f'{ad}_g', parent_node_name=out.graph.base_frame, transform=trimesh.transformations.translation_matrix(c))
    for i, (x, y, z, r, eksen) in enumerate(cfg.get('extra_rotors', [])):   # prosedürel ek rotor (ör. kuyruk rotoru): çıktı çerçevesinde, m
        hub = trimesh.creation.cylinder(radius=r * 0.12, height=r * 0.1, sections=12)
        hub.visual = trimesh.visual.TextureVisuals(material=pbr((0.1, 0.1, 0.1, 1.0), None, metal=0.6, rough=0.4))
        palalar = [hub]
        for k in range(2):
            b = trimesh.creation.box([r * 2, r * 0.03, r * 0.14]); b.apply_transform(trimesh.transformations.rotation_matrix(math.pi * k / 2, [0, 1, 0]))
            b.visual = trimesh.visual.TextureVisuals(material=pbr((0.2, 0.2, 0.2, 1.0), None, metal=0.3, rough=0.6)); palalar.append(b)
        rot = trimesh.util.concatenate(palalar)   # yerel: pervane düzlemi XZ, ekseni Y
        Tr = trimesh.transformations.translation_matrix([x, y, z])
        if eksen == 'z':
            Tr = Tr @ trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0])
        elif eksen == 'x':
            Tr = Tr @ trimesh.transformations.rotation_matrix(math.pi / 2, [0, 0, 1])
        out.add_geometry(rot, node_name=f'rotor_extra_{i}', geom_name=f'rotor_extra_{i}_g', parent_node_name=out.graph.base_frame, transform=Tr)
    return out


# ---------- model tanımları ----------
def tanimlar(src):
    px4 = src / 'px4/repo/models'
    fuel = src / 'fuel'
    poly = src / 'poly/glb'
    iris_renk = {'rotor_0': 'Gazebo/Blue', 'rotor_2': 'Gazebo/Blue', 'rotor_1': 'Gazebo/DarkGrey', 'rotor_3': 'Gazebo/DarkGrey'}   # ön pervaneler mavi (3DR Iris)
    return {
        'iris': {'kind': 'sdf', 'sdf': px4 / 'iris/iris.sdf.jinja', 'dir': px4 / 'iris', 'tri_budget': 40_000, 'link_colors': iris_renk},
        'iris_fpv': {'kind': 'sdf', 'sdf': px4 / 'iris/iris.sdf.jinja', 'dir': px4 / 'iris', 'tri_budget': 40_000, 'fpv_cam': True, 'link_colors': iris_renk},
        'x500': {'kind': 'sdf', 'sdf': fuel / 'x500/model.sdf', 'dir': fuel / 'x500', 'tri_budget': 50_000, 'decimate_textured': True},
        'typhoon_h480': {'kind': 'sdf', 'sdf': px4 / 'typhoon_h480/typhoon_h480.sdf.jinja', 'dir': px4 / 'typhoon_h480', 'tri_budget': 50_000, 'tri_floor': 2000,
                         'skip_links': ('left_leg', 'right_leg')},   # iniş ayakları (STL'ler kopuk; uçuşta zaten çekili)
        'rc_cessna': {'kind': 'sdf', 'sdf': fuel / 'rc_cessna/model.sdf', 'dir': fuel / 'rc_cessna', 'tri_budget': 40_000},
        'standard_vtol': {'kind': 'sdf', 'sdf': px4 / 'standard_vtol/standard_vtol.sdf.jinja', 'dir': px4 / 'standard_vtol', 'tri_budget': 50_000},
        'zephyr': {'kind': 'sdf', 'sdf': fuel / 'zephyr/model.sdf', 'dir': fuel / 'zephyr', 'yaw_deg': 90, 'tri_budget': 20_000},   # Zephyr burnu -Y → +X
        'believer': {'kind': 'sdf', 'sdf': px4 / 'believer/believer.sdf', 'dir': px4 / 'believer', 'tri_budget': 50_000},
        # Poly Pizza hazır GLB'ler (glTF Y yukarı; burun +Z → yaw 90° ile +X)
        'heli': {'kind': 'glb', 'glb': poly / 'EQJ2MECUbx.glb', 'scale': 0.36, 'yaw_deg': 90, 'rename': {'Cube_3': 'rotor_main'}, 'ground': True,
                 'extra_rotors': [(-0.8, 0.3, 0.06, 0.12, 'z')]},   # kuyruk rotoru (modelde yok)
        'jet': {'kind': 'glb', 'glb': poly / '6fyLMORhgGK.glb', 'scale': 0.36, 'yaw_deg': 90, 'ground': True},
    }


def fpv_ekleri():
    """FPV kamerası (kutu + lens) ve iki anten — Gazebo çerçevesinde base_link'e göre (iris 0.47 m)."""
    parcalar = []
    cam = trimesh.creation.box([0.022, 0.022, 0.022]); cam.visual = trimesh.visual.TextureVisuals(material=pbr((0.05, 0.05, 0.05, 1.0), None, metal=0.3, rough=0.5))
    Tc = trimesh.transformations.translation_matrix([0.09, 0, 0.055]) @ trimesh.transformations.rotation_matrix(math.radians(-25), [0, 1, 0])
    parcalar.append(Parca('fpv_cam', cam, Tc, False))
    lens = trimesh.creation.cylinder(radius=0.008, height=0.012, sections=20); lens.visual = trimesh.visual.TextureVisuals(material=pbr((0.3, 0.6, 1.0, 1.0), None, metal=0.9, rough=0.1))
    Tl = Tc @ trimesh.transformations.translation_matrix([0.016, 0, 0]) @ trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0])
    parcalar.append(Parca('fpv_cam', lens, Tl, False))
    for side in (-1, 1):
        ant = trimesh.creation.cylinder(radius=0.003, height=0.14, sections=10); ant.visual = trimesh.visual.TextureVisuals(material=pbr((1.0, 0.0, 0.0, 1.0), None, ad='accent'))
        Ta = trimesh.transformations.translation_matrix([-0.12, side * 0.03, 0.09]) @ trimesh.transformations.rotation_matrix(math.radians(-35), [0, 1, 0]) @ trimesh.transformations.rotation_matrix(side * math.radians(20), [1, 0, 0])
        parcalar.append(Parca('fpv_cam', ant, Ta, False))
        tip = trimesh.creation.icosphere(subdivisions=1, radius=0.009); tip.visual = trimesh.visual.TextureVisuals(material=pbr((1.0, 1.0, 1.0, 1.0), None))
        parcalar.append(Parca('fpv_cam', tip, Ta @ trimesh.transformations.translation_matrix([0, 0, 0.07]), False))
    return parcalar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--only', default='')
    ap.add_argument('--glb', action='append', default=[], help='hazır GLB: ad=yol[,scale=..,yaw_deg=..,pitch_deg=..,rename=a:b;c:d,ground=1]')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    secim = {s for s in a.only.split(',') if s}
    sonuc = {}
    for ad, cfg in tanimlar(a.src).items():
        if secim and ad not in secim:
            continue
        kaynak = Path(cfg.get('sdf') or cfg.get('glb'))
        if not kaynak.is_file():
            print(f'-- {ad}: kaynak yok, atlandı', file=sys.stderr)
            continue
        print(f'== {ad}')
        if cfg['kind'] == 'glb':
            sc = glb_paketle(kaynak, cfg)
            out = a.out / f'{ad}.glb'
            glb_yaz(sc, out)
            sonuc[ad] = rapor(out)
            print('  ', json.dumps(sonuc[ad]))
            continue
        linkler, parcalar = sdf_parcalar(cfg['sdf'], cfg['dir'], cfg)
        ekler = []
        if cfg.get('fpv_cam'):
            linkler['fpv_cam'] = np.eye(4)
            parcalar += fpv_ekleri()
        sc = sahne_kur(linkler, parcalar, cfg, ekler)
        out = a.out / f'{ad}.glb'
        glb_yaz(sc, out)
        sonuc[ad] = rapor(out)
        print('  ', json.dumps(sonuc[ad]))
    for spec in a.glb:
        ad, _, rest = spec.partition('=')
        parts = rest.split(',')
        yol = parts[0]
        cfg = {}
        for kv in parts[1:]:
            k, _, v = kv.partition('=')
            if k == 'rename':
                cfg[k] = dict(x.split(':') for x in v.split(';') if ':' in x)
            elif k in ('scale', 'yaw_deg', 'pitch_deg'):
                cfg[k] = float(v)
            elif k == 'ground':
                cfg[k] = v not in ('0', '')
        print(f'== {ad} (glb)')
        sc = glb_paketle(Path(yol), cfg)
        out = a.out / f'{ad}.glb'
        glb_yaz(sc, out)
        sonuc[ad] = rapor(out)
        print('  ', json.dumps(sonuc[ad]))
    print(json.dumps(sonuc, ensure_ascii=False))   # rapor stdout'a (çıktı dizinine yazılmaz: static/simumav/** pakete girer)


if __name__ == '__main__':
    main()
