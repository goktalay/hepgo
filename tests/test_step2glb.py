"""tools/step_mapped2glb.py: sentetik (küçük) üçgen ağ STEP → montaj/yerleşim/birim/pervane sınıflandırması → GLB.

Çalıştırma: ./.venv/bin/python -m unittest tests.test_step2glb   (büyük dosyalara bağımlı değil; trimesh + pygltflib gerekir)
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np

KOK = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location('step_mapped2glb', KOK / 'tools' / 'step_mapped2glb.py')
smg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smg)


class _Yazici:
    """Minimal AP214 benzeri STEP metni (FACETED_BREP + REPRESENTATION_MAP + MAPPED_ITEM)."""

    def __init__(self):
        self.satir, self.n = [], 100

    def ekle(self, metin):
        self.n += 1
        self.satir.append(f'#{self.n}={metin};')
        return self.n

    def nokta(self, p):
        return self.ekle("CARTESIAN_POINT('',(%s))" % ','.join(f'{x:.6f}' for x in p))

    def eksen(self, o, z=(0, 0, 1), x=(1, 0, 0)):
        po = self.nokta(o)
        dz = self.ekle("DIRECTION('',(%s))" % ','.join(f'{v:.6f}' for v in z))
        dx = self.ekle("DIRECTION('',(%s))" % ','.join(f'{v:.6f}' for v in x))
        return self.ekle(f"AXIS2_PLACEMENT_3D('',#{po},#{dz},#{dx})")

    def kutu(self, merkez, boy):
        """Eksen hizalı kutu → SHAPE_REPRESENTATION id (6 dörtgen yüz, dışa dönük)."""
        c, h = np.asarray(merkez, float), np.asarray(boy, float) / 2
        k = [self.nokta(c + h * np.array([sx, sy, sz])) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        # köşe indeksi: (sx, sy, sz) → 4*ix + 2*iy + iz
        yuzler = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        fid = []
        for y in yuzler:
            lp = self.ekle("POLY_LOOP('',(%s))" % ','.join(f'#{k[i]}' for i in y))
            fb = self.ekle(f"FACE_OUTER_BOUND('',#{lp},.T.)")
            fid.append(self.ekle(f"FACE_SURFACE('',(#{fb}),$,.T.)"))
        sh = self.ekle("CLOSED_SHELL('',(%s))" % ','.join(f'#{f}' for f in fid))
        br = self.ekle(f"FACETED_BREP('',#{sh})")
        ax = self.eksen((0, 0, 0))
        return self.ekle(f"SHAPE_REPRESENTATION('',(#{br},#{ax}),#24)")

    def metin(self):
        bas = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('test'),'2;1');\nFILE_NAME('t','2026-01-01',(''),(''),'','','');\n"
               "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\nENDSEC;\nDATA;\n"
               "#20=(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.));\n"
               "#24=(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNIT_ASSIGNED_CONTEXT((#20)) REPRESENTATION_CONTEXT('','3D'));\n")
        return bas + '\n'.join(self.satir) + '\nENDSEC;\nEND-ISO-10303-21;\n'


def sentetik_step():
    """mm birimli montaj: gövde kutusu (300×50×50, 1 yerleşim) + ince pervane kutusu (100×4×10, merkez (10,0,0); 2 yerleşim:
    birim ve (0,0,80) mm'de Z etrafında 90°)."""
    w = _Yazici()
    govde = w.kutu((0, 0, 0), (300, 50, 50))
    pervane = w.kutu((10, 0, 0), (100, 4, 10))
    kaynak = w.eksen((0, 0, 0))
    mg = w.ekle(f'REPRESENTATION_MAP(#{kaynak},#{govde})')
    mp = w.ekle(f'REPRESENTATION_MAP(#{kaynak},#{pervane})')
    w.ekle(f"MAPPED_ITEM('',#{mg},#{w.eksen((0, 0, 0))})")
    w.ekle(f"MAPPED_ITEM('',#{mp},#{w.eksen((0, 0, 0))})")
    w.ekle(f"MAPPED_ITEM('',#{mp},#{w.eksen((0, 0, 80), z=(0, 0, 1), x=(0, 1, 0))})")
    return w.metin()


class StepMapped2Glb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.step = smg.Step(sentetik_step())
        cls.parcalar, cls.yer = cls.step.montaj()

    def test_birim_mm(self):
        self.assertAlmostEqual(self.step.olcek, 1e-3)

    def test_parca_ve_yerlesim(self):
        self.assertEqual(len(self.parcalar), 2)       # benzersiz parça
        self.assertEqual(len(self.yer), 3)            # yerleşim (MAPPED_ITEM)
        boylar = sorted(tuple(np.round(np.ptp(V, axis=0), 6)) for V, F in self.parcalar.values())
        self.assertEqual(boylar, [(0.1, 0.004, 0.01), (0.3, 0.05, 0.05)])   # metre
        for V, F in self.parcalar.values():
            self.assertEqual(len(F), 12)              # 6 dörtgen → 12 üçgen

    def test_yerlesim_donusumu(self):
        T = self.yer[2][1]
        np.testing.assert_allclose(T[:3, 3], [0, 0, 0.08], atol=1e-9)
        np.testing.assert_allclose(T[:3, :3] @ [1, 0, 0], [0, 1, 0], atol=1e-9)   # yerel X → dünya Y (Z etrafında 90°)
        np.testing.assert_allclose(self.yer[1][1], np.eye(4), atol=1e-9)

    def test_siniflandirma(self):
        adlar = smg.siniflandir(self.parcalar, self.yer)
        self.assertEqual([(a, r) for a, r, _ in adlar], [('body', 'body'), ('prop_1', 'prop'), ('prop_2', 'prop')])
        np.testing.assert_allclose(adlar[1][2], [0.01, 0, 0], atol=1e-9)   # göbek = pervane sınır kutusu merkezi (yerel)

    def test_glb(self):
        import pygltflib
        import trimesh
        adlar = smg.siniflandir(self.parcalar, self.yer)
        sc = smg.glb_kur(self.parcalar, self.yer, adlar)
        with tempfile.TemporaryDirectory() as d:
            yol = Path(d) / 't.glb'
            yol.write_bytes(sc.export(file_type='glb'))
            g = pygltflib.GLTF2().load(str(yol))
            self.assertEqual(sorted(n.name for n in g.nodes if n.mesh is not None), ['body', 'prop_1', 'prop_2'])
            s = trimesh.load(str(yol), force='scene')
        beklenen_gobek = {'prop_1': [0.01, 0, 0], 'prop_2': [0, 0.01, 0.08]}
        ince = {'prop_1': 1, 'prop_2': 0}   # dönüş ekseni (dünya): pervanenin yerel Y'si → prop_2'de dünya X
        for ad, gob in beklenen_gobek.items():
            T, gn = s.graph.get(ad)
            np.testing.assert_allclose(T[:3, :3], np.eye(3), atol=1e-6)          # pervane düğümü: rotation kimlik
            np.testing.assert_allclose(T[:3, 3], gob, atol=1e-6)                 # orijin göbekte
            V = np.asarray(s.geometry[gn].vertices)
            self.assertEqual(int(np.argmin(np.ptp(V, axis=0))), ince[ad])       # en ince yerel eksen = dönüş ekseni
            np.testing.assert_allclose((V.max(0) + V.min(0)) / 2, 0, atol=1e-6)  # ağ göbek etrafında
        # gövde malzemesi #161616 (doğrusal), pervaneler ayrı malzeme
        renk = {m.name: m.pbrMetallicRoughness.baseColorFactor for m in g.materials}
        self.assertAlmostEqual(renk['body'][0], smg.srgb_lineer('#161616')[0], places=2)
        self.assertIn('prop', renk)


if __name__ == '__main__':
    unittest.main()
