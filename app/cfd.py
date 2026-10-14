"""3B CFD (OpenFOAM v2406): montaj STL'si etrafında dış akış — snappyHexMesh ağı + simpleFoam (kararlı RANS, k-ω SST).

Koordinat sözleşmesi: istemci STL'yi akış +x, yukarı +z, birim metre olacak biçimde çevirip gönderir (hücum açısı dahil).
Her analiz DATA_DIR/cfd/<run_id>/ altında tam bir OpenFOAM durumu (case) olarak oluşturulur; Allrun betiği aşamaları
'phase' dosyasına yazar; sonuçlar (katsayılar, yakınsama, yüzey basıncı, kesit düzlemleri, akım çizgileri) tarayıcı için
sıkıştırılmış ikili dosyalara (float32/uint32) çevrilir. Tek seferde bir analiz koşar (kuyruk, arka plan iş parçacığı).

Ortam: CAYMAZ_OPENFOAM_DIR (varsayılan: /usr/lib/openfoam/openfoam2406 ya da /opt/hepgo/openfoam/... [paketten çıkarılmış, DEV]),
CAYMAZ_CFD_CORES (0 = otomatik: mpirun varsa min(16, çekirdek/3), yoksa 1)."""
import json
import math
import os
import re
import shutil
import signal
import struct
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import config, db

_CANDIDATES = ['/usr/lib/openfoam/openfoam2406', '/opt/hepgo/openfoam/usr/lib/openfoam/openfoam2406']
OPENFOAM_DIR = Path(os.environ.get('CAYMAZ_OPENFOAM_DIR') or next((p for p in _CANDIDATES if Path(p, 'etc/bashrc').exists()), _CANDIDATES[0]))
CFD_DIR = config.DATA_DIR / 'cfd'
RES = {   # çözünürlük: n = gövde boyu başına taban hücre; surf = yüzey arıtma (min max); box = gövde çevresi kutu arıtma; iters = en çok yineleme
    'coarse': {'n': 24, 'surf': (1, 2), 'box': 1, 'iters': 250, 'label': 'Kaba'},
    'medium': {'n': 36, 'surf': (2, 3), 'box': 1, 'iters': 400, 'label': 'Orta'},
    'fine': {'n': 50, 'surf': (2, 4), 'box': 2, 'iters': 600, 'label': 'İnce'},
}


def available():
    return (OPENFOAM_DIR / 'etc' / 'bashrc').exists()


def cores():
    n = int(os.environ.get('CAYMAZ_CFD_CORES') or 0)
    if n > 0:
        return n
    if not shutil.which('mpirun'):
        return 1
    return max(1, min(16, (os.cpu_count() or 2) // 3))


def env_prefix():
    """Allrun içinde OpenFOAM ortamı: paketten çıkarılmış kurulumda (DEV) sistem kütüphaneleri de eklenir; MPI yoksa DUMMY."""
    extra = OPENFOAM_DIR.parents[1] / 'x86_64-linux-gnu'   # /opt/hepgo/openfoam/usr/lib/x86_64-linux-gnu (paketten çıkarılmış DEV kurulumu)
    lines = ['export FOAM_SIGFPE=', 'export OMPI_MCA_btl_vader_single_copy_mechanism=none']
    if extra.exists():
        lines.append(f'export LD_LIBRARY_PATH={extra}:$LD_LIBRARY_PATH')
    mpl = 'SYSTEMOPENMPI' if shutil.which('mpirun') else 'DUMMY'
    lines.append(f'source {OPENFOAM_DIR}/etc/bashrc WM_MPLIB={mpl} >/dev/null 2>&1 || true')
    return '\n'.join(lines)


# ---------------- STL okuma ve geometri ----------------
def read_stl(path):
    """Binary ya da ASCII STL → numpy (n,3,3) köşe dizisi."""
    import numpy as np
    data = Path(path).read_bytes()
    if len(data) >= 84:
        n = struct.unpack('<I', data[80:84])[0]
        if 84 + n * 50 == len(data) and not data[:5].lower().startswith(b'solid'):
            arr = np.frombuffer(data[84:84 + n * 50], dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]))
            return arr['v'].astype(np.float64)
        if 84 + n * 50 == len(data):   # 'solid' ile başlayan binary
            arr = np.frombuffer(data[84:84 + n * 50], dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]))
            return arr['v'].astype(np.float64)
    txt = data.decode('utf-8', errors='replace')
    vs = re.findall(r'vertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)', txt)
    v = np.array(vs, dtype=np.float64)
    return v.reshape(-1, 3, 3)


def geometry(tris):
    """Sınır kutusu, izdüşüm alanları (kapalı yüzey: Σ|A·n|/2), hacim yaklaşımı."""
    import numpy as np
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    cr = np.cross(b - a, c - a)          # 2·alan · normal
    mn, mx = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    frontal = float(np.abs(cr[:, 0]).sum() / 4)   # yz düzlemine izdüşüm (x akış)
    planform = float(np.abs(cr[:, 2]).sum() / 4)  # xy düzlemine izdüşüm
    side = float(np.abs(cr[:, 1]).sum() / 4)
    vol = float(abs((a * cr).sum() / 6))
    return {'min': mn.tolist(), 'max': mx.tolist(), 'size': (mx - mn).tolist(), 'frontal_area': frontal, 'planform_area': planform, 'side_area': side,
            'volume': vol, 'triangles': int(len(tris)), 'center': ((mn + mx) / 2).tolist()}


# ---------------- Durum (case) üretimi ----------------
HEADER = '''FoamFile
{{
    version     2.0;
    format      ascii;
    class       {cls};
    object      {obj};
}}
'''


def _dict(cls, obj, body):
    return HEADER.format(cls=cls, obj=obj) + body


def write_case(case: Path, geo, p):
    """p: {'U','rho','nu','res','cores','turb_intensity'} — gövde STL constant/triSurface/body.stl içinde olmalı."""
    import numpy as np
    r = RES[p['res']]
    L = max(geo['size'][0], 1e-3); W = max(geo['size'][1], 1e-3); H = max(geo['size'][2], 1e-3)
    cx, cy, cz = geo['center']
    big = max(W, H)
    x0, x1 = geo['min'][0] - 3.0 * L, geo['max'][0] + 7.0 * L
    y0, y1 = cy - 3.0 * big - W / 2, cy + 3.0 * big + W / 2
    z0, z1 = cz - 3.0 * big - H / 2, cz + 3.0 * big + H / 2
    cell = L / r['n']
    nx, ny, nz = (max(8, int(round((x1 - x0) / cell))), max(8, int(round((y1 - y0) / cell))), max(8, int(round((z1 - z0) / cell))))
    while nx * ny * nz > 400_000:   # arka plan ağı sınırı (arıtma snappy'de)
        cell *= 1.15; nx, ny, nz = (max(8, int(round((x1 - x0) / cell))), max(8, int(round((y1 - y0) / cell))), max(8, int(round((z1 - z0) / cell))))
    U = float(p['U']); I = float(p.get('turb_intensity', 0.01))
    k = 1.5 * (I * U) ** 2
    omega = math.sqrt(k) / (0.09 ** 0.25 * 0.07 * L)
    Aref = max(geo['frontal_area'], 1e-6)
    iters = int(p.get('iters') or r['iters'])
    (case / 'system').mkdir(parents=True, exist_ok=True); (case / 'constant').mkdir(exist_ok=True); (case / '0').mkdir(exist_ok=True)

    (case / 'system' / 'blockMeshDict').write_text(_dict('dictionary', 'blockMeshDict', f'''
scale 1;
vertices
(
    ({x0} {y0} {z0}) ({x1} {y0} {z0}) ({x1} {y1} {z0}) ({x0} {y1} {z0})
    ({x0} {y0} {z1}) ({x1} {y0} {z1}) ({x1} {y1} {z1}) ({x0} {y1} {z1})
);
blocks ( hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1) );
edges ();
boundary
(
    inlet  {{ type patch; faces ((0 4 7 3)); }}
    outlet {{ type patch; faces ((1 2 6 5)); }}
    sides  {{ type patch; faces ((0 1 5 4) (3 7 6 2)); }}
    bottom {{ type patch; faces ((0 3 2 1)); }}
    top    {{ type patch; faces ((4 5 6 7)); }}
);
mergePatchPairs ();
'''))
    bx0, bx1 = geo['min'][0] - 0.6 * L, geo['max'][0] + 1.6 * L
    by0, by1 = geo['min'][1] - 0.6 * big, geo['max'][1] + 0.6 * big
    bz0, bz1 = geo['min'][2] - 0.6 * big, geo['max'][2] + 0.6 * big
    loc = (x1 - 0.2 * L, y1 - 0.2 * big, z1 - 0.2 * big)   # kesinlikle gövde dışında (akış alanı)
    (case / 'system' / 'snappyHexMeshDict').write_text(_dict('dictionary', 'snappyHexMeshDict', f'''
castellatedMesh true;
snap            true;
addLayers       false;
geometry
{{
    body.stl {{ type triSurfaceMesh; name body; }}
    refBox {{ type searchableBox; min ({bx0} {by0} {bz0}); max ({bx1} {by1} {bz1}); }}
    wakeBox {{ type searchableBox; min ({geo['min'][0]} {by0} {bz0}); max ({geo['max'][0] + 3.5 * L} {by1} {bz1}); }}
}}
castellatedMeshControls
{{
    maxLocalCells 4000000;
    maxGlobalCells 9000000;
    minRefinementCells 10;
    maxLoadUnbalance 0.10;
    nCellsBetweenLevels 3;
    features ( {{ file "body.eMesh"; level {r['surf'][1]}; }} );
    refinementSurfaces {{ body {{ level ({r['surf'][0]} {r['surf'][1]}); patchInfo {{ type wall; }} }} }}
    resolveFeatureAngle 30;
    refinementRegions
    {{
        refBox {{ mode inside; levels ((1E15 {r['box']})); }}
        wakeBox {{ mode inside; levels ((1E15 {max(0, r['box'] - 1)})); }}
    }}
    locationInMesh ({loc[0]} {loc[1]} {loc[2]});
    allowFreeStandingZoneFaces true;
}}
snapControls
{{
    nSmoothPatch 3;
    tolerance 2.0;
    nSolveIter 30;
    nRelaxIter 5;
    nFeatureSnapIter 10;
    implicitFeatureSnap false;
    explicitFeatureSnap true;
    multiRegionFeatureSnap false;
}}
addLayersControls
{{
    relativeSizes true;
    layers {{ }}
    expansionRatio 1.0;
    finalLayerThickness 0.3;
    minThickness 0.1;
    nGrow 0;
    featureAngle 60;
    slipFeatureAngle 30;
    nRelaxIter 3;
    nSmoothSurfaceNormals 1;
    nSmoothNormals 3;
    nSmoothThickness 10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedianAxisAngle 90;
    nBufferCellsNoExtrude 0;
    nLayerIter 50;
}}
meshQualityControls
{{
    #includeEtc "caseDicts/meshQualityDict"
    nSmoothScale 4;
    errorReduction 0.75;
}}
writeFlags ();
mergeTolerance 1e-6;
'''))
    (case / 'system' / 'surfaceFeatureExtractDict').write_text(_dict('dictionary', 'surfaceFeatureExtractDict', '''
body.stl
{
    extractionMethod extractFromSurface;
    includedAngle 150;
    subsetFeatures { nonManifoldEdges no; openEdges yes; }
    writeObj no;
}
'''))
    (case / 'system' / 'controlDict').write_text(_dict('dictionary', 'controlDict', f'''
application     simpleFoam;
startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         {iters};
deltaT          1;
writeControl    timeStep;
writeInterval   {iters};
purgeWrite      1;
writeFormat     ascii;
writePrecision  7;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
functions
{{
    forceCoeffs
    {{
        type            forceCoeffs;
        libs            (forces);
        writeControl    timeStep;
        writeInterval   1;
        log             false;
        patches         (body);
        rho             rhoInf;
        rhoInf          {float(p['rho'])};
        CofR            ({cx} {cy} {cz});
        liftDir         (0 0 1);
        dragDir         (1 0 0);
        pitchAxis       (0 1 0);
        magUInf         {U};
        lRef            {L};
        Aref            {Aref};
    }}
    solverInfo
    {{
        type            solverInfo;
        libs            (utilityFunctionObjects);
        fields          (U p k omega);
        writeResidualFields false;
        writeControl    timeStep;
        writeInterval   1;
    }}
    yPlus
    {{
        type            yPlus;
        libs            (fieldFunctionObjects);
        executeControl  onEnd;
        writeControl    onEnd;
        log             false;
    }}
    wallShearStress
    {{
        type            wallShearStress;
        libs            (fieldFunctionObjects);
        patches         (body);
        executeControl  onEnd;
        writeControl    onEnd;
        log             false;
    }}
    slices
    {{
        type            surfaces;
        libs            (sampling);
        executeControl  onEnd;
        writeControl    onEnd;
        surfaceFormat   vtk;
        formatOptions   {{ vtk {{ format ascii; }} }}
        fields          (U p);
        interpolationScheme cellPoint;
        surfaces
        {{
            side {{ type cuttingPlane; planeType pointAndNormal; pointAndNormalDict {{ point ({cx} {cy} {cz}); normal (0 1 0); }} interpolate true; bounds ({x0} {y0} {z0}) ({x1} {y1} {z1}); }}
            top  {{ type cuttingPlane; planeType pointAndNormal; pointAndNormalDict {{ point ({cx} {cy} {cz}); normal (0 0 1); }} interpolate true; bounds ({x0} {y0} {z0}) ({x1} {y1} {z1}); }}
        }}
    }}
    streams
    {{
        type            streamLine;
        libs            (fieldFunctionObjects);
        executeControl  onEnd;
        writeControl    onEnd;
        setFormat       vtk;
        formatOptions   {{ vtk {{ format ascii; }} }}
        U               U;
        fields          (U p);
        direction       forward;
        lifeTime        20000;
        nSubCycle       4;
        cloud           particleTracks;
        seedSampleSet
        {{
            type        uniform;
            axis        xyz;
            start       ({geo['min'][0] - 1.5 * L} {cy - 0.55 * W} {cz - 0.55 * H});
            end         ({geo['min'][0] - 1.5 * L} {cy + 0.55 * W} {cz + 0.55 * H});
            nPoints     36;
        }}
    }}
    streams2
    {{
        $streams;
        seedSampleSet
        {{
            type        uniform;
            axis        xyz;
            start       ({geo['min'][0] - 1.5 * L} {cy - 0.55 * W} {cz + 0.55 * H});
            end         ({geo['min'][0] - 1.5 * L} {cy + 0.55 * W} {cz - 0.55 * H});
            nPoints     36;
        }}
    }}
}}
'''))
    (case / 'system' / 'fvSchemes').write_text(_dict('dictionary', 'fvSchemes', '''
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; limited cellLimited Gauss linear 1; grad(U) $limited; grad(k) $limited; grad(omega) $limited; }
divSchemes
{
    default none;
    div(phi,U) bounded Gauss linearUpwindV limited;
    turbulence bounded Gauss limitedLinear 1;
    div(phi,k) $turbulence;
    div(phi,omega) $turbulence;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear limited corrected 0.33; }
interpolationSchemes { default linear; }
snGradSchemes { default limited corrected 0.33; }
wallDist { method meshWave; }
'''))
    (case / 'system' / 'fvSolution').write_text(_dict('dictionary', 'fvSolution', '''
solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-7; relTol 0.01; }
    "(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.1; nSweeps 2; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 0;
    consistent yes;
    residualControl { p 2e-4; U 1e-4; "(k|omega)" 1e-4; }
}
potentialFlow { nNonOrthogonalCorrectors 10; }
relaxationFactors
{
    equations { U 0.9; ".*" 0.9; }
}
cache { grad(U); }
'''))
    nproc = int(p.get('cores') or 1)
    (case / 'system' / 'decomposeParDict').write_text(_dict('dictionary', 'decomposeParDict', f'''
numberOfSubdomains {nproc};
method scotch;
'''))
    (case / 'constant' / 'turbulenceProperties').write_text(_dict('dictionary', 'turbulenceProperties', '''
simulationType RAS;
RAS { RASModel kOmegaSST; turbulence on; printCoeffs off; }
'''))
    (case / 'constant' / 'transportProperties').write_text(_dict('dictionary', 'transportProperties', f'''
transportModel Newtonian;
nu {float(p['nu'])};
'''))
    bc = lambda inlet, outlet, lateral, body: f'''
boundaryField
{{
    inlet  {{ {inlet} }}
    outlet {{ {outlet} }}
    "(sides|top|bottom)" {{ {lateral} }}
    body   {{ {body} }}
}}
'''
    (case / '0' / 'U').write_text(_dict('volVectorField', 'U', f'dimensions [0 1 -1 0 0 0 0];\ninternalField uniform ({U} 0 0);' + bc(
        f'type fixedValue; value uniform ({U} 0 0);', f'type inletOutlet; inletValue uniform (0 0 0); value uniform ({U} 0 0);', 'type slip;', 'type noSlip;')))
    (case / '0' / 'p').write_text(_dict('volScalarField', 'p', 'dimensions [0 2 -2 0 0 0 0];\ninternalField uniform 0;' + bc(
        'type zeroGradient;', 'type fixedValue; value uniform 0;', 'type zeroGradient;', 'type zeroGradient;')))
    (case / '0' / 'k').write_text(_dict('volScalarField', 'k', f'dimensions [0 2 -2 0 0 0 0];\ninternalField uniform {k};' + bc(
        f'type fixedValue; value uniform {k};', f'type inletOutlet; inletValue uniform {k}; value uniform {k};', 'type slip;', f'type kqRWallFunction; value uniform {k};')))
    (case / '0' / 'omega').write_text(_dict('volScalarField', 'omega', f'dimensions [0 0 -1 0 0 0 0];\ninternalField uniform {omega};' + bc(
        f'type fixedValue; value uniform {omega};', f'type inletOutlet; inletValue uniform {omega}; value uniform {omega};', 'type slip;', f'type omegaWallFunction; value uniform {omega};')))
    (case / '0' / 'nut').write_text(_dict('volScalarField', 'nut', 'dimensions [0 2 -1 0 0 0 0];\ninternalField uniform 0;' + bc(
        'type calculated; value uniform 0;', 'type calculated; value uniform 0;', 'type calculated; value uniform 0;', 'type nutkWallFunction; value uniform 0;')))
    par = nproc > 1
    (case / 'Allrun').write_text(f'''#!/bin/bash
cd "$(dirname "$0")"
{env_prefix()}
set -o pipefail
ph() {{ echo "$1" > phase; echo "=== $1 ($(date +%H:%M:%S))"; }}
ph "features"
surfaceFeatureExtract > log.surfaceFeatureExtract 2>&1 || {{ echo FAIL surfaceFeatureExtract > phase; exit 2; }}
ph "blockMesh"
blockMesh > log.blockMesh 2>&1 || {{ echo FAIL blockMesh > phase; exit 2; }}
ph "snappyHexMesh"
snappyHexMesh -overwrite > log.snappyHexMesh 2>&1 || {{ echo FAIL snappyHexMesh > phase; exit 2; }}
ph "checkMesh"
checkMesh > log.checkMesh 2>&1 || true
ph "simpleFoam"
{'decomposePar -force > log.decomposePar 2>&1 || { echo FAIL decomposePar > phase; exit 2; }' if par else ''}
{'nice -n 10 mpirun --oversubscribe -np ' + str(nproc) + ' simpleFoam -parallel > log.simpleFoam 2>&1 || { echo FAIL simpleFoam > phase; exit 2; }' if par else 'nice -n 10 simpleFoam > log.simpleFoam 2>&1 || { echo FAIL simpleFoam > phase; exit 2; }'}
{'reconstructPar -latestTime > log.reconstructPar 2>&1 || { echo FAIL reconstructPar > phase; exit 2; }' if par else ''}
ph "post"
foamToVTK -latestTime -no-internal -patches body -fields "(p U wallShearStress yPlus)" -ascii > log.foamToVTK 2>&1 || {{ echo FAIL foamToVTK > phase; exit 2; }}
ph "done"
''')
    os.chmod(case / 'Allrun', 0o755)
    return {'domain': [x0, y0, z0, x1, y1, z1], 'cell': cell, 'bg_cells': nx * ny * nz, 'k': k, 'omega': omega, 'Aref': Aref, 'lRef': L, 'iters': iters, 'cores': nproc}


# ---------------- Sonuç ayrıştırma ----------------
def _read_dat(path):
    """OpenFOAM .dat (başlık '# Time a b c…') → (sütun adları, satırlar float)."""
    cols, rows = [], []
    for line in Path(path).read_text(errors='replace').splitlines():
        if line.startswith('#'):
            s = line.lstrip('#').strip()
            if s.startswith('Time') or ('Time' in s and len(s.split()) > 3):
                cols = s.replace('\t', ' ').split()
            continue
        parts = line.replace('(', ' ').replace(')', ' ').split()
        if parts:
            vals = []
            for x in parts:   # solverInfo satırlarında metin (smoothSolver, true/false) da var → None
                try:
                    vals.append(float(x))
                except ValueError:
                    vals.append(None)
            if vals[0] is not None:
                rows.append(vals)
    return cols, rows


def parse_coeffs(case):
    f = next(iter(sorted((case / 'postProcessing' / 'forceCoeffs').rglob('coefficient.dat'))), None)
    if not f:
        return None
    cols, rows = _read_dat(f)
    if not rows:
        return None
    n = max(1, len(rows) // 5)
    tail = rows[-n:]
    avg = [sum((r[i] or 0.0) for r in tail) / len(tail) for i in range(min(len(c) for c in tail))]
    idx = {c: i for i, c in enumerate(cols)}
    g = lambda name: (avg[idx[name]] if name in idx and idx[name] < len(avg) else None)
    hist = [[r[0], r[idx['Cd']] if 'Cd' in idx else None, r[idx['Cl']] if 'Cl' in idx else None] for r in rows[::max(1, len(rows) // 400)]]
    return {'Cd': g('Cd'), 'Cl': g('Cl'), 'Cs': g('Cs'), 'CmPitch': g('CmPitch'), 'CmRoll': g('CmRoll'), 'CmYaw': g('CmYaw'), 'last_iter': rows[-1][0], 'history': hist, 'columns': cols}


def parse_residuals(case):
    f = next(iter(sorted((case / 'postProcessing' / 'solverInfo').rglob('solverInfo.dat'))), None)
    if not f:
        return None
    cols, rows = _read_dat(f)
    if not rows or not cols:
        return None
    want = [c for c in cols if c.endswith('_initial')]
    idx = {c: cols.index(c) for c in want}
    step = max(1, len(rows) // 400)
    out = {'iters': [r[0] for r in rows[::step]]}
    for c in want:
        i = idx[c]
        out[c.replace('_initial', '')] = [r[i] if i < len(r) else None for r in rows[::step]]
    return out


def _vtk_xml_poly(path):
    """VTK XML PolyData (ascii) → dict(points (n,3), polys [list of index lists], lines [...], point_data {name: array}, cell_data {name: array})."""
    import numpy as np
    root = ET.parse(path).getroot()
    piece = root.find('.//Piece')
    out = {'points': None, 'polys': [], 'lines': [], 'point_data': {}, 'cell_data': {}}

    def arr(el):
        comp = int(el.get('NumberOfComponents') or 1)
        txt = el.text or ''
        a = np.fromstring(txt, sep=' ', dtype=np.float64)
        return a.reshape(-1, comp) if comp > 1 else a
    pts = piece.find('Points/DataArray')
    if pts is not None:
        out['points'] = arr(pts).reshape(-1, 3)
    for sec, key in (('Polys', 'polys'), ('Lines', 'lines')):
        s = piece.find(sec)
        if s is None:
            continue
        conn = offs = None
        for da in s.findall('DataArray'):
            if da.get('Name') == 'connectivity':
                conn = np.fromstring(da.text or '', sep=' ', dtype=np.int64)
            elif da.get('Name') == 'offsets':
                offs = np.fromstring(da.text or '', sep=' ', dtype=np.int64)
        if conn is not None and offs is not None:
            start = 0
            cells = []
            for o in offs:
                cells.append(conn[start:int(o)]); start = int(o)
            out[key] = cells
    for sec, key in (('PointData', 'point_data'), ('CellData', 'cell_data')):
        s = piece.find(sec)
        if s is None:
            continue
        for da in s.findall('DataArray'):
            out[key][da.get('Name')] = arr(da)
    return out


def _tri_bundle(poly, scalars):
    """Çokgen yüzey → üçgenlere ayrılmış, köşe başına skaler (hücre verisi yelpaze ile köşelere yazılır).
    Döner: positions (m,3) f32, values {name: (m,) f32} — indeks dizisi yok (düz üçgenler, düz renk)."""
    import numpy as np
    P = poly['points']
    tri_idx, cell_ids = [], []
    for ci, cell in enumerate(poly['polys']):
        for j in range(1, len(cell) - 1):
            tri_idx.append((cell[0], cell[j], cell[j + 1])); cell_ids.append(ci)
    if not tri_idx:
        return np.zeros((0, 3), np.float32), {}
    ti = np.array(tri_idx, dtype=np.int64); ci = np.array(cell_ids, dtype=np.int64)
    pos = P[ti.reshape(-1)].astype(np.float32)
    vals = {}
    for name in scalars:
        if name in poly['cell_data']:
            v = poly['cell_data'][name]
            v = np.linalg.norm(v, axis=1) if v.ndim == 2 else v
            vals[name] = np.repeat(v[ci], 3).astype(np.float32)
        elif name in poly['point_data']:
            v = poly['point_data'][name]
            v = np.linalg.norm(v, axis=1) if v.ndim == 2 else v
            vals[name] = v[ti.reshape(-1)].astype(np.float32)
    return pos, vals


def _write_bundle(path, pos, vals, extra=None):
    """İkili paket: [u32 json_len][json başlık][float32 positions][float32 değerler…]. Başlık: n (köşe), fields [adlar], extra."""
    import numpy as np
    head = json.dumps({'n': int(len(pos)), 'fields': list(vals.keys()), **(extra or {})}).encode()
    with open(path, 'wb') as f:
        f.write(struct.pack('<I', len(head))); f.write(head)
        f.write(np.ascontiguousarray(pos, dtype=np.float32).tobytes())
        for k in vals:
            f.write(np.ascontiguousarray(vals[k], dtype=np.float32).tobytes())


def postprocess(case: Path, params, geo, out_dir: Path):
    """Sonuç dosyalarını üret: meta.json, body.bin (Cp, |τ|, y+), slice_side.bin / slice_top.bin (|U|/U∞, Cp), lines.bin (akım çizgileri)."""
    import numpy as np
    out_dir.mkdir(parents=True, exist_ok=True)
    U = float(params['U']); rho = float(params['rho']); q = 0.5 * rho * U * U
    coeffs = parse_coeffs(case); resid = parse_residuals(case)
    meta = {'coeffs': coeffs, 'residuals': resid, 'q': q, 'files': {}}
    # gövde yüzeyi
    body = next(iter(sorted((case / 'VTK').rglob('body*.vtp'))), None)
    if body:
        poly = _vtk_xml_poly(body)
        if 'p' in poly['cell_data']: poly['cell_data']['Cp'] = poly['cell_data']['p'] / (0.5 * U * U)
        elif 'p' in poly['point_data']: poly['point_data']['Cp'] = poly['point_data']['p'] / (0.5 * U * U)
        pos, vals = _tri_bundle(poly, ['Cp', 'wallShearStress', 'yPlus'])
        if 'wallShearStress' in vals: vals['wallShearStress'] = vals['wallShearStress'] * rho   # kinematik → Pa
        _write_bundle(out_dir / 'body.bin', pos, vals, {'ranges': {k: [float(v.min()), float(v.max())] for k, v in vals.items() if len(v)}})
        meta['files']['body'] = 'body.bin'; meta['body_faces'] = int(len(pos) // 3)
    # kesitler
    for name in ('side', 'top'):
        f = next(iter(sorted((case / 'postProcessing' / 'slices').rglob(f'{name}.vtp'))), None) or next(iter(sorted((case / 'postProcessing' / 'slices').rglob(f'*{name}*.vtp'))), None)
        if not f:
            continue
        poly = _vtk_xml_poly(f)
        for store in ('point_data', 'cell_data'):
            if 'U' in poly[store]: poly[store]['Umag'] = np.linalg.norm(poly[store]['U'], axis=1) / U
            if 'p' in poly[store]: poly[store]['Cp'] = poly[store]['p'] / (0.5 * U * U)
        pos, vals = _tri_bundle(poly, ['Umag', 'Cp'])
        _write_bundle(out_dir / f'slice_{name}.bin', pos, vals, {'ranges': {k: [float(v.min()), float(v.max())] for k, v in vals.items() if len(v)}})
        meta['files'][f'slice_{name}'] = f'slice_{name}.bin'
    # akım çizgileri (iki tohum kümesi)
    segs, svals = [], []
    for sub in ('streams', 'streams2'):   # v2406: postProcessing/sets/<ad>/<zaman>/track0.vtp
        for f in sorted(f for f in (case / 'postProcessing').rglob('*.vtp') if sub in f.parts and 'slices' not in f.parts):
            poly = _vtk_xml_poly(f)
            P = poly['points']
            if P is None:
                continue
            Um = None
            if 'U' in poly['point_data']: Um = np.linalg.norm(poly['point_data']['U'], axis=1) / U
            for line in poly['lines']:
                if len(line) < 2:
                    continue
                a, b = line[:-1], line[1:]
                segs.append(np.stack([P[a], P[b]], axis=1).reshape(-1, 3))
                if Um is not None: svals.append(np.stack([Um[a], Um[b]], axis=1).reshape(-1))
    if segs:
        pos = np.concatenate(segs).astype(np.float32)
        vals = {'Umag': np.concatenate(svals).astype(np.float32)} if svals else {}
        _write_bundle(out_dir / 'lines.bin', pos, vals, {'kind': 'lines'})
        meta['files']['lines'] = 'lines.bin'; meta['line_segments'] = int(len(pos) // 2)
    # ağ sayısı
    cm = case / 'log.checkMesh'
    if cm.exists():
        m = re.search(r'cells:\s+(\d+)', cm.read_text(errors='replace'))
        if m: meta['cells'] = int(m.group(1))
    # kuvvetler
    if coeffs and coeffs.get('Cd') is not None:
        A = geo['frontal_area']
        meta['forces'] = {'drag_N': coeffs['Cd'] * q * A, 'lift_N': (coeffs['Cl'] or 0) * q * A, 'side_N': (coeffs.get('Cs') or 0) * q * A, 'Aref': A,
                          'LD': (coeffs['Cl'] / coeffs['Cd']) if coeffs['Cd'] else None}
    (out_dir / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False))
    return meta


# ---------------- Çalıştırıcı (kuyruk) ----------------
_lock = threading.Lock()
_worker = None
_procs = {}   # run_id → Popen


def _conn():
    return db.connect()


def enqueue(run_id):
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, daemon=True, name='cfd-runner')
            _worker.start()


def _loop():
    while True:
        with _conn() as conn:
            row = db.row(conn.execute("SELECT * FROM design_cfd_runs WHERE status = 'queued' ORDER BY id LIMIT 1"))
        if not row:
            return
        _run(row)


def _set(run_id, **kw):
    with _conn() as conn:
        sets = ', '.join(f'{k} = ?' for k in kw)
        conn.execute(f'UPDATE design_cfd_runs SET {sets} WHERE id = ?', (*kw.values(), run_id))


def _run(row):
    run_id = row['id']
    case = Path(row['dir'])
    params = json.loads(row['params'] or '{}')
    geo = json.loads(row['geometry'] or '{}')
    _set(run_id, status='running', phase='start', started_at=db.now())
    try:
        proc = subprocess.Popen(['bash', str(case / 'Allrun')], cwd=str(case), stdout=open(case / 'run.log', 'ab'), stderr=subprocess.STDOUT, start_new_session=True)
        _procs[run_id] = proc
        last_phase = ''
        while proc.poll() is None:
            time.sleep(2)
            ph = (case / 'phase').read_text().strip() if (case / 'phase').exists() else ''
            it = _progress_iter(case)
            if ph != last_phase or it:
                last_phase = ph
                _set(run_id, phase=ph, iters=it or 0, cells=_cells(case) or 0)
            with _conn() as conn:
                st = conn.execute('SELECT status FROM design_cfd_runs WHERE id = ?', (run_id,)).fetchone()
            if st and st[0] == 'cancelling':
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=30)
                _set(run_id, status='cancelled', phase='cancelled', finished_at=db.now())
                return
        rc = proc.returncode
        ph = (case / 'phase').read_text().strip() if (case / 'phase').exists() else ''
        if rc != 0 or ph != 'done':
            err = _tail(case / ('log.' + ph.replace('FAIL ', '')) if ph.startswith('FAIL') else case / 'run.log', 40)
            _set(run_id, status='failed', phase=ph or f'exit {rc}', error=err[:4000], finished_at=db.now())
            return
        _set(run_id, phase='results')
        meta = postprocess(case, params, geo, case / 'results')
        _set(run_id, status='done', phase='done', iters=int((meta.get('coeffs') or {}).get('last_iter') or 0), cells=meta.get('cells') or 0,
             result=json.dumps({k: v for k, v in meta.items() if k != 'residuals'}, ensure_ascii=False), finished_at=db.now())
    except Exception as e:   # noqa: BLE001
        _set(run_id, status='failed', phase='error', error=str(e)[:4000], finished_at=db.now())
    finally:
        _procs.pop(run_id, None)


def _tail(path, n):
    try:
        lines = Path(path).read_text(errors='replace').splitlines()
        return '\n'.join(lines[-n:])
    except OSError:
        return ''


def _progress_iter(case):
    log = case / 'log.simpleFoam'
    if not log.exists():
        return 0
    try:
        with open(log, 'rb') as f:
            f.seek(max(0, log.stat().st_size - 4000))
            chunk = f.read().decode('utf-8', errors='replace')
        m = re.findall(r'^Time = (\d+)', chunk, flags=re.M)
        return int(m[-1]) if m else 0
    except OSError:
        return 0


def _cells(case):
    log = case / 'log.snappyHexMesh'
    if not log.exists():
        return 0
    try:
        txt = _tail(log, 400)
        m = re.findall(r'cells:(\d+)', txt.replace(' ', ''))
        return int(m[-1]) if m else 0
    except OSError:
        return 0


def log_tail(run_id, n=60):
    with _conn() as conn:
        row = db.row(conn.execute('SELECT dir, phase FROM design_cfd_runs WHERE id = ?', (run_id,)))
    if not row:
        return ''
    case = Path(row['dir'])
    ph = (row['phase'] or '').replace('FAIL ', '')
    for name in (f'log.{ph}', 'run.log'):
        if (case / name).exists():
            return _tail(case / name, n)
    return ''


def recover_on_start():
    """Uygulama yeniden başladıysa yarım kalan koşular 'failed' olur; kuyruktakiler sürer."""
    try:
        with _conn() as conn:
            conn.execute("UPDATE design_cfd_runs SET status = 'failed', error = 'Sunucu yeniden başlatıldı', finished_at = ? WHERE status IN ('running','cancelling')", (db.now(),))
            n = conn.execute("SELECT COUNT(*) FROM design_cfd_runs WHERE status = 'queued'").fetchone()[0]
        if n:
            enqueue(None)
    except Exception:   # noqa: BLE001
        pass
