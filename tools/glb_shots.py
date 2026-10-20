#!/usr/bin/env python3
"""GLB görsel denetimi: three.js (static/vendor/three) ile her modeli 3 açıdan çizer → PNG.

Kullanım:  LD_LIBRARY_PATH=… CHROMIUM_PATH=… .venv/bin/python -I tools/glb_shots.py --out /tmp/icept-shots/models a.glb b.glb …
Görünümler: 3/4 (ön-sağ-üst), yan (+Z'den; burun +X sağda), üst (+Y'den; burun sağda, sağ kanat +Z aşağıda), ön (+X'ten).
Eksen işaretleri: kırmızı +X (burun), yeşil +Y (yukarı), mavi +Z (sağ). Pervane düğümleri (prop|propeller|rotor|pervane) sarı
küre (göbek = düğüm orijini) + mor çizgi (yerel sınır kutusunun en ince ekseni = flightsim3d dönüş ekseni) ile işaretlenir.
Sunucu açılmaz: Playwright `route` istekleri dosyalardan yanıtlar.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

KOK = Path(__file__).resolve().parent.parent
THREE = KOK / 'static' / 'vendor' / 'three'

HTML = r"""<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;background:#9fb3c8;font:13px monospace}
#t{position:absolute;left:6px;top:4px;color:#000;white-space:pre}</style>
<script type="importmap">{"imports":{"three":"/three/three.module.min.js"}}</script></head><body><div id="t"></div>
<script type="module">
import * as T from '/three/three.module.min.js';
import { GLTFLoader } from '/three/GLTFLoader.js';
const W = 1500, H = 1000;
const r = new T.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }); r.setSize(W, H); r.setScissorTest(true);
r.outputColorSpace = T.SRGBColorSpace; document.body.appendChild(r.domElement);
const sc = new T.Scene(); sc.background = new T.Color(0x9fb3c8);
sc.add(new T.HemisphereLight(0xffffff, 0x445566, 1.6)); const dl = new T.DirectionalLight(0xffffff, 2.2); dl.position.set(3, 5, 4); sc.add(dl);
const dl2 = new T.DirectionalLight(0xffffff, 0.8); dl2.position.set(-4, 2, -3); sc.add(dl2);
const PROP_RE = /prop|propeller|rotor|pervane/i;
window.render = async (url) => {
  const g = await new Promise((res, rej) => new GLTFLoader().load(url, res, undefined, rej));
  const m = g.scene; sc.add(m); m.updateMatrixWorld(true);
  const bb = new T.Box3().setFromObject(m), sz = bb.getSize(new T.Vector3()), c = bb.getCenter(new T.Vector3());
  const L = Math.max(sz.x, sz.y, sz.z);
  const ax = new T.AxesHelper(L * 0.75); sc.add(ax);
  const info = [];
  let tri = 0; m.traverse(o => { if (o.isMesh) tri += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3; });
  m.traverse(n => {
    if (!PROP_RE.test(n.name || '')) return;
    for (let a = n.parent; a && a !== m; a = a.parent) if (PROP_RE.test(a.name || '')) return;
    const inv = new T.Matrix4().copy(n.matrixWorld).invert(), b = new T.Box3();
    n.traverse(q => { if (q.isMesh) { q.geometry.computeBoundingBox(); b.union(q.geometry.boundingBox.clone().applyMatrix4(new T.Matrix4().multiplyMatrices(inv, q.matrixWorld))); } });
    const s = b.getSize(new T.Vector3());
    const axn = s.x <= s.y && s.x <= s.z ? 'x' : s.y <= s.z ? 'y' : 'z';
    const p = new T.Vector3().setFromMatrixPosition(n.matrixWorld);
    const k = new T.Mesh(new T.SphereGeometry(L * 0.012), new T.MeshBasicMaterial({ color: 0xffee00, depthTest: false })); k.position.copy(p); k.renderOrder = 9; sc.add(k);
    const d = new T.Vector3(); d[axn] = 1; d.transformDirection(n.matrixWorld);
    const ln = new T.Line(new T.BufferGeometry().setFromPoints([p.clone().addScaledVector(d, -L * 0.15), p.clone().addScaledVector(d, L * 0.15)]), new T.LineBasicMaterial({ color: 0xcc00ff, depthTest: false })); ln.renderOrder = 9; sc.add(ln);
    info.push(`${n.name} @(${p.x.toFixed(3)},${p.y.toFixed(3)},${p.z.toFixed(3)}) eksen ${axn} r≈${(Math.max(s.x, s.y, s.z) / 2).toFixed(3)}`);
  });
  const names = []; m.traverse(n => { if (n !== m && n.name) names.push(n.name); });
  document.getElementById('t').textContent = `${url.split('/').pop()}  boy X ${sz.x.toFixed(3)}  Y ${sz.y.toFixed(3)}  Z ${sz.z.toFixed(3)} m  merkez (${c.x.toFixed(3)},${c.y.toFixed(3)},${c.z.toFixed(3)})  üçgen ${tri}\n` +
    `düğümler: ${names.slice(0, 30).join(', ')}\n` + info.join('\n') + '\n[sol üst] 3/4   [sağ üst] yan (+Z)   [sol alt] üst (+Y)   [sağ alt] ön (+X)   kırmızı +X burun, yeşil +Y, mavi +Z sağ';
  const D = L * 1.6;
  const views = [[new T.Vector3(1, 0.7, 1.1), 0, H / 2], [new T.Vector3(0, 0, 1), W / 2, H / 2], [new T.Vector3(0, 1, 0.0001), 0, 0], [new T.Vector3(1, 0, 0), W / 2, 0]];
  for (const [dir, x, y] of views) {
    const cam = new T.PerspectiveCamera(30, (W / 2) / (H / 2), L * 0.01, L * 20);
    cam.position.copy(c).addScaledVector(dir.clone().normalize(), D * 1.4);
    if (dir.y > 0.99) cam.up.set(0, 0, -1); else cam.up.set(0, 1, 0);
    cam.lookAt(c);
    r.setViewport(x, y, W / 2, H / 2); r.setScissor(x, y, W / 2, H / 2); r.render(sc, cam);
  }
  return { sz: [sz.x, sz.y, sz.z], c: [c.x, c.y, c.z], tri, info, names };
};
window.ready = true;
</script></body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('glb', nargs='+')
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or None)
        for g in a.glb:
            gp = Path(g).resolve()
            pg = b.new_page(viewport={'width': 1500, 'height': 1000})

            def yonlendir(route, _istek=None, gp=gp):   # Playwright 2 parametreli işleyiciye (route, request) verir
                u = route.request.url.split('http://yerel', 1)[1].split('?')[0]
                if u == '/':
                    return route.fulfill(body=HTML, content_type='text/html')
                if u.startswith('/three/'):
                    f = THREE / u[len('/three/'):]
                    return route.fulfill(body=f.read_bytes(), content_type='text/javascript') if f.is_file() else route.fulfill(status=404)
                if u == '/m.glb':
                    return route.fulfill(body=gp.read_bytes(), content_type='model/gltf-binary')
                return route.fulfill(status=404)
            pg.route('http://yerel/**', yonlendir)
            pg.on('console', lambda m: print('[konsol]', m.text, file=sys.stderr) if m.type in ('error', 'warning') else None)
            pg.goto('http://yerel/')
            pg.wait_for_function('window.ready === true')
            # evaluate(promise) + senkron route birlikte kilitleniyor → başlat, sonra bekle
            pg.evaluate("window.__r = null; render('/m.glb').then(x => window.__r = x, e => window.__r = { err: String(e) }); 0")
            pg.wait_for_function('window.__r !== null', timeout=120000)
            res = pg.evaluate('window.__r')
            png = out / (gp.stem + '.png')
            pg.screenshot(path=str(png))
            print(json.dumps({'glb': str(gp), 'png': str(png), **res}, ensure_ascii=False))
            pg.close()
        b.close()


if __name__ == '__main__':
    main()
