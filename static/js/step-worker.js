// STEP çözümleme işçisi (module worker): occt-import-js (OpenCascade WASM) ana iş parçacığını kilitlemeden çalışır.
// Mesaj: { id, buffer } → { id, ok, result: { root, meshes:[{name, color, position, normal, index}] } } (dizi tamponları aktarılır).
import occtimportjs from '/static/vendor/occt/occt-import-js.js';

let occtPromise = null;
const loadOcct = () => (occtPromise ??= occtimportjs({ locateFile: n => '/static/vendor/occt/' + n }));

self.onmessage = async e => {
  const { id, buffer } = e.data;
  try {
    const occt = await loadOcct();
    const t0 = performance.now();
    const res = occt.ReadStepFile(new Uint8Array(buffer), null);
    if (!res || !res.success) throw new Error('STEP dosyası okunamadı');
    const transfer = [];
    const meshes = (res.meshes || []).map(m => {
      const position = m.attributes?.position?.array ? Float32Array.from(m.attributes.position.array) : null;
      const normal = m.attributes?.normal?.array?.length ? Float32Array.from(m.attributes.normal.array) : null;
      const index = m.index?.array?.length ? Uint32Array.from(m.index.array) : null;
      for (const a of [position, normal, index]) if (a) transfer.push(a.buffer);
      return { name: m.name || '', color: m.color && m.color.length === 3 ? [m.color[0], m.color[1], m.color[2]] : null, position, normal, index };
    });
    const strip = n => ({ name: n.name || '', meshes: (n.meshes || []).slice(), children: (n.children || []).map(strip) });
    self.postMessage({ id, ok: true, result: { root: strip(res.root || {}), meshes, ms: Math.round(performance.now() - t0) } }, transfer);
  } catch (err) {
    self.postMessage({ id, ok: false, error: String(err && err.message || err) });
  }
};
