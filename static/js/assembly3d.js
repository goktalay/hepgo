// 3B Montaj: parçaların G-code'dan çıkarılmış gerçek 3B takım yolları, sunucuda uçaktaki yerlerine oturtulmuş olarak gelir
// (app/assembly3d.py). Renkler şemadaki durum renkleridir (ürün sayfasında bölüm renkleri). Altta "Patlatma" kaydırıcısı.
// Oturtulamayan parçalar uçağın yanında durur. Düzenleyici (yetkiliyse): parçaya tıkla → seç; sürükle → taşı (Shift: yukarı/aşağı);
// panelden / klavyeden döndür ve taşı; "Kaydet" ile elle düzeltmeler kalıcı olur (otomatik yerleşimin üstüne uygulanır).
import { api, fileUrl } from './api.js';
import { loadLibs } from './gcode3d.js';
import { clear, h, modal, toast, toastError, confirmDialog } from './ui.js';

async function fetchBin(url, onProgress) {
  const r = await fetch(url);
  if (!r.ok) throw new Error('3B montaj dosyası alınamadı');
  const total = +r.headers.get('content-length') || 0;
  if (!r.body?.getReader) return r.arrayBuffer();
  const reader = r.body.getReader(), parts = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value); got += value.length;
    if (total) onProgress(got / total);
  }
  const out = new Uint8Array(got);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out.buffer;
}

// Durum rengi yoksa (ürün sayfası) bölüm renkleri
const SECTION_COLOR = { SOL_KANAT: '#cbd5e1', SAG_KANAT: '#cbd5e1', GOVDE: '#e2e8f0' };
function partColor(THREE, p, fills) {
  const fill = fills?.get(p.id);
  const c = new THREE.Color();
  if (fill && fill !== 'none') { try { c.setStyle(fill); return c; } catch { /* aşağıda */ } }
  if (p.outside) return c.set('#f1c0c0');
  if (p.layer === 'electronics') return c.set('#a5b4fc');
  if (p.layer === 'cover' || p.group === 'cover') return c.set('#fcd34d');
  return c.set(SECTION_COLOR[p.section] || '#e5e7eb');
}

const DEG = Math.PI / 180;
const r1 = v => Math.round(v * 10) / 10;

/**
 * mountAssembly(host, { schema, fills, editable }) → { destroy }
 *  schema: ürün şeması (caymaz / caymaz-v2), fills: Map(parça id → CSS rengi), editable: düzenleyici açılabilir
 */
export function mountAssembly(host, { schema = 'caymaz', fills = null, editable = false } = {}) {
  const tipEl = h('div', { class: 'asm3d-tip' });
  const status = h('div', { class: 'asm3d-load' }, h('div', { class: 'asm3d-wheel' }), h('span', null, 'Parçalar G-code’dan birleştiriliyor…'));
  const panel = h('div', { class: 'asm3d-edit', hidden: true });
  const stage = h('div', { class: 'asm3d-stage' }, tipEl, status, panel);
  const range = h('input', { type: 'range', min: '0', max: '100', value: '0', class: 'asm3d-range', 'aria-label': 'Patlatma' });
  const pct = h('b', { class: 'asm3d-pct' }, '%0');
  const spin = h('input', { type: 'checkbox' });
  const editBtn = editable ? h('button', { class: 'btn sm', type: 'button' }, '✎ Düzenle') : null;
  const outsideNote = h('p', { class: 'small muted asm3d-hint' });
  const hint = h('p', { class: 'small muted asm3d-hint' }, 'Parçalar G-code dosyalarındaki gerçek 3B şekilleriyle çizilir. Fareyle döndürün, tekerlekle yakınlaştırın, sağ tuşla kaydırın.');
  clear(host, h('div', { class: 'asm3d' }, stage,
    h('div', { class: 'asm3d-bar' },
      h('span', { class: 'asm3d-lbl' }, 'Birleşik'), range, h('span', { class: 'asm3d-lbl' }, 'Patlatılmış'), pct,
      h('label', { class: 'asm3d-spin' }, spin, ' Döndür'), editBtn),
    hint, outsideNote));
  const say = t => { status.lastChild.textContent = t; };
  let destroyed = false, view = { destroy() { destroyed = true; } };

  (async () => {
    let meta, buf, THREE, OrbitControls;
    try {
      [meta, [THREE, { OrbitControls }]] = await Promise.all([api.get(`/api/products/assembly3d/${encodeURIComponent(schema)}`), loadLibs()]);
      if (destroyed) return;
      say('3B veriler indiriliyor… %0');
      buf = await fetchBin(fileUrl(meta.file), f => say(`3B veriler indiriliyor… %${Math.round(f * 100)}`));
    } catch (err) {
      status.classList.add('err'); say(err.message || '3B montaj hazırlanamadı');
      return;
    }
    if (destroyed || !stage.isConnected) return;
    status.remove();
    const all = new Int16Array(buf), Q = meta.quant || 4;
    let saved = meta.overrides || {};   // sunucudaki elle düzeltmeler
    const noteOutside = () => {
      const out = meta.parts.filter(p => p.outside && !saved[p.id]).map(p => p.id);
      outsideNote.textContent = out.length ? `Uçağa henüz oturtulamayan ${out.length} parça sağ kanadın yanında duruyor: ${out.join(', ')}.`
        + (editable ? ' “Düzenle” ile seçip yerine taşıyabilirsiniz.' : '') : '';
    };
    noteOutside();

    const w = stage.clientWidth || 900, hgt = stage.clientHeight || 560;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
    renderer.setSize(w, hgt);
    stage.prepend(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, w / hgt, 5, 100000);
    const root = new THREE.Group();
    scene.add(root);

    // Parçalar: geometri kendi merkezine taşınır (kendi etrafında döndürmek için); konum = merkez + düzeltme + patlatma
    const objs = [], geoms = [], mats = [];
    let minY = Infinity, maxY = -Infinity;
    for (const p of meta.parts) {
      const seg = all.subarray(p.start * 6, (p.start + p.count) * 6);
      const pos = new Float32Array(seg.length);
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      for (let i = 0; i < seg.length; i++) {
        const v = seg[i] / Q, k = i % 3;
        pos[i] = v;
        if (v < lo[k]) lo[k] = v;
        if (v > hi[k]) hi[k] = v;
      }
      const c = new THREE.Vector3((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2);
      for (let i = 0; i < pos.length; i += 3) { pos[i] -= c.x; pos[i + 1] -= c.y; pos[i + 2] -= c.z; }
      if (!p.outside) { minY = Math.min(minY, lo[1]); maxY = Math.max(maxY, hi[1]); }
      const base = partColor(THREE, p, fills);
      const n = pos.length / 3, col = new Float32Array(n * 3);
      for (let i = 0; i < n; i += 2) {
        const dx = pos[(i + 1) * 3] - pos[i * 3], dy = pos[(i + 1) * 3 + 1] - pos[i * 3 + 1], dz = pos[(i + 1) * 3 + 2] - pos[i * 3 + 2];
        const len = Math.hypot(dx, dy, dz) || 1;
        const shade = 0.5 + 0.6 * Math.abs((dz / len) * 0.7 - (dx / len) * 0.5 + (dy / len) * 0.5);
        for (const j of [i, i + 1]) {
          col[j * 3] = Math.min(1, base.r * shade); col[j * 3 + 1] = Math.min(1, base.g * shade); col[j * 3 + 2] = Math.min(1, base.b * shade);
        }
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      g.setAttribute('color', new THREE.BufferAttribute(col, 3));
      g.computeBoundingSphere();
      const mat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 1 });
      const obj = new THREE.LineSegments(g, mat);
      obj.userData = { id: p.id, part: p, base: c, ov: null };
      root.add(obj);
      objs.push(obj); geoms.push(g); mats.push(mat);
    }
    // Patlatma yönleri
    const inPlane = meta.parts.filter(p => !p.outside);
    const span = Math.max(...inPlane.map(p => Math.abs(p.center[0])), 1) * 2;
    const lift = Math.max(maxY - minY, 200);
    for (const o of objs) {
      const p = o.userData.part;
      const d = new THREE.Vector3(p.center[0], 0, p.center[2]);
      if (p.section === 'SOL_KANAT') d.x -= span * 0.3;
      if (p.section === 'SAG_KANAT') d.x += span * 0.3;
      const up = p.layer === 'cover' || p.group === 'cover' ? lift * 2.2 : p.layer === 'electronics' ? -lift * 1.5 : 0;
      o.userData.dir = p.outside ? null : new THREE.Vector3(d.x * 0.55, up, d.z * 0.55);
    }
    let explode = 0;
    const ovOf = o => o.userData.ov || { p: [0, 0, 0], r: [0, 0, 0] };
    const apply = o => {
      const ov = ovOf(o);
      o.position.copy(o.userData.base).add(new THREE.Vector3(...ov.p));
      if (o.userData.dir && !(o.userData.part.outside && o.userData.ov)) o.position.addScaledVector(o.userData.dir, explode);
      o.rotation.set(ov.r[0] * DEG, ov.r[1] * DEG, ov.r[2] * DEG, 'XYZ');
    };
    const loadOverrides = () => {
      for (const o of objs) {
        const s = saved[o.userData.id];
        o.userData.ov = s ? { p: [...s.p], r: [...s.r] } : null;
        apply(o);
      }
    };
    loadOverrides();

    // Kamera: uçağa odak
    const pbox = new THREE.Box3();
    for (const o of objs) if (!o.userData.part.outside) pbox.expandByObject(o);
    const sphere = (pbox.isEmpty() ? new THREE.Box3().setFromObject(root) : pbox).getBoundingSphere(new THREE.Sphere());
    sphere.radius *= 1.08;
    const fit = () => sphere.radius / Math.sin((camera.fov * Math.PI) / 360) / Math.min(1, camera.aspect * 0.9) * 0.95;
    const viewDir = new THREE.Vector3(-0.42, 0.62, 0.66).normalize();
    camera.position.copy(sphere.center).add(viewDir.clone().multiplyScalar(fit()));
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(sphere.center);
    controls.enableDamping = true;
    controls.autoRotateSpeed = 0.8;
    controls.update();
    let userMoved = false;
    controls.addEventListener('start', () => { userMoved = true; });

    range.addEventListener('input', () => {
      explode = Number(range.value) / 100;
      pct.textContent = `%${range.value}`;
      objs.forEach(apply);
      if (!userMoved) camera.position.copy(sphere.center).add(viewDir.clone().multiplyScalar(fit() * (1 + 0.5 * explode)));
    });
    spin.addEventListener('change', () => { controls.autoRotate = spin.checked; });

    // ---------- Seçim, ipucu, düzenleyici
    const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
    const pick = ev => {
      const r = renderer.domElement.getBoundingClientRect();
      mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      ray.params.Line.threshold = sphere.radius / 220;
      ray.setFromCamera(mouse, camera);
      return ray.intersectObjects(objs, false)[0] || null;
    };
    let editing = false, sel = null, hover = null;
    const dirty = new Set();
    const undo = [];
    const paint = () => {
      for (const x of objs) {
        const focus = editing ? sel : hover;
        x.material.opacity = focus && x !== focus ? (editing ? 0.22 : 0.35) : 1;
        x.material.color.setRGB(1, 1, 1);
      }
      if (editing && sel) sel.material.color.setRGB(0.75, 1.05, 1.6);
      if (box) { scene.remove(box); box.geometry.dispose(); box.material.dispose(); box = null; }
      if (editing && sel) { box = new THREE.BoxHelper(sel, 0x2563eb); scene.add(box); }
    };
    let box = null;   // seçili parçanın çerçevesi
    const pushUndo = o => { undo.push({ o, ov: o.userData.ov ? { p: [...o.userData.ov.p], r: [...o.userData.ov.r] } : null }); if (undo.length > 200) undo.shift(); };
    const touch = o => { dirty.add(o.userData.id); apply(o); drawPanel(); noteOutside(); };
    const ensureOv = o => (o.userData.ov ??= { p: [0, 0, 0], r: [0, 0, 0] });
    const move = (axis, mm) => {
      if (!sel) return;
      pushUndo(sel);
      ensureOv(sel).p[axis] = r1(sel.userData.ov.p[axis] + mm);
      touch(sel);
    };
    const rotate = (axis, deg) => {
      if (!sel) return;
      pushUndo(sel);
      ensureOv(sel);
      const ax = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)][axis];
      sel.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(ax, deg * DEG));   // dünya ekseni etrafında
      const e = new THREE.Euler().setFromQuaternion(sel.quaternion, 'XYZ');
      sel.userData.ov.r = [r1(e.x / DEG), r1(e.y / DEG), r1(e.z / DEG)];
      touch(sel);
    };
    let rotStep = 90, moveStep = 10;
    const stepSel = (opts, cur, set) => h('div', { class: 'seg asm3d-steps' }, opts.map(([v, l]) => h('button', { type: 'button', class: v === cur ? 'on' : '',
      onclick: () => { set(v); drawPanel(); } }, l)));
    const pm = (label, minus, plus, tip) => h('div', { class: 'asm3d-row', title: tip },
      h('span', { class: 'asm3d-ax' }, label),
      h('button', { class: 'btn xs', type: 'button', onclick: minus }, '−'), h('button', { class: 'btn xs', type: 'button', onclick: plus }, '+'));
    function drawPanel() {
      if (!editing) { panel.hidden = true; return; }
      panel.hidden = false;
      if (!sel) {
        clear(panel, h('b', null, 'Düzenleme'), h('p', { class: 'small muted' }, 'Bir parçaya tıklayarak seçin. Seçili parçayı fareyle sürükleyerek taşıyın (Shift: yukarı / aşağı).'),
          saveRow());
        return;
      }
      const ov = ovOf(sel), p = sel.userData.part;
      clear(panel,
        h('div', { class: 'asm3d-eh' }, h('b', null, p.id), p.outside ? h('span', { class: 'badge red' }, 'yanda') : null,
          h('button', { class: 'btn xs ghost', type: 'button', title: 'Seçimi bırak (Esc)', onclick: () => { sel = null; paint(); drawPanel(); } }, '✕')),
        h('div', { class: 'asm3d-sub' }, 'Döndür'),
        stepSel([[90, '90°'], [15, '15°'], [5, '5°'], [1, '1°']], rotStep, v => { rotStep = v; }),
        pm('X', () => rotate(0, -rotStep), () => rotate(0, rotStep), 'Yana yatır (R / F)'),
        pm('Y', () => rotate(1, -rotStep), () => rotate(1, rotStep), 'Kendi etrafında çevir (Q / E)'),
        pm('Z', () => rotate(2, -rotStep), () => rotate(2, rotStep), 'Öne / arkaya yatır (T / G)'),
        h('div', { class: 'asm3d-sub' }, 'Taşı'),
        stepSel([[100, '100 mm'], [10, '10'], [1, '1']], moveStep, v => { moveStep = v; }),
        pm('Sağ / Sol', () => move(0, -moveStep), () => move(0, moveStep), '← →'),
        pm('Yukarı', () => move(1, -moveStep), () => move(1, moveStep), 'Page Up / Page Down'),
        pm('Geri / İleri', () => move(2, -moveStep), () => move(2, moveStep), '↑ ↓'),
        h('div', { class: 'small muted asm3d-pos' }, `Kaydırma: ${ov.p.map(v => v.toFixed(1)).join(' / ')} mm · Dönüş: ${ov.r.map(v => v.toFixed(1)).join(' / ')}°`),
        h('div', { class: 'asm3d-row2' },
          h('button', { class: 'btn xs', type: 'button', disabled: !undo.length, onclick: doUndo }, '↶ Geri al'),
          h('button', { class: 'btn xs', type: 'button', disabled: !sel.userData.ov, onclick: () => { pushUndo(sel); sel.userData.ov = null; touch(sel); } }, 'Otomatiğe dön')),
        saveRow());
    }
    function saveRow() {
      return h('div', { class: 'asm3d-save' },
        h('button', { class: 'btn sm primary', type: 'button', disabled: !dirty.size, onclick: save }, dirty.size ? `Kaydet (${dirty.size})` : 'Kaydedildi'),
        h('button', { class: 'btn sm', type: 'button', disabled: !dirty.size, onclick: discard }, 'Vazgeç'));
    }
    function doUndo() {
      const u = undo.pop();
      if (!u) return;
      u.o.userData.ov = u.ov;
      sel = u.o; paint(); touch(u.o);
    }
    async function save() {
      const parts = {};
      for (const id of dirty) {
        const o = objs.find(x => x.userData.id === id);
        const ov = o?.userData.ov;
        parts[id] = ov && (ov.p.some(v => Math.abs(v) > 0.05) || ov.r.some(v => Math.abs(v) > 0.05)) ? ov : null;
      }
      try {
        const r = await api.put(`/api/products/assembly3d/${encodeURIComponent(schema)}/overrides`, { parts });
        saved = r.overrides || {};
        dirty.clear(); undo.length = 0;
        toast('3B montaj yerleşimi kaydedildi', 'success');
        drawPanel(); noteOutside();
      } catch (err) { toastError(err); }
    }
    function discard() {
      loadOverrides(); dirty.clear(); undo.length = 0; drawPanel(); noteOutside();
    }
    const setEditing = on => {
      editing = on;
      editBtn?.classList.toggle('primary', on);
      if (editBtn) editBtn.textContent = on ? '✓ Düzenleme açık' : '✎ Düzenle';
      if (!on) sel = null;
      hint.textContent = on
        ? 'Düzenleme: parçaya tıklayıp seçin; sürükleyerek taşıyın (Shift: yukarı / aşağı). Klavye: ← → ↑ ↓ taşı, Page Up/Down yükselt, Q/E · R/F · T/G döndür, Ctrl+Z geri al, Esc bırak.'
        : 'Parçalar G-code dosyalarındaki gerçek 3B şekilleriyle çizilir. Fareyle döndürün, tekerlekle yakınlaştırın, sağ tuşla kaydırın.';
      paint(); drawPanel();
    };
    editBtn?.addEventListener('click', async () => {
      if (editing && dirty.size && !await confirmDialog('Kaydedilmemiş değişiklik', `${dirty.size} parçadaki değişiklik kaydedilmedi. Düzenlemeyi kapatıp vazgeçilsin mi?`, { okLabel: 'Vazgeç ve kapat', danger: true })) return;
      if (editing && dirty.size) discard();
      setEditing(!editing);
    });

    // Fare: üzerine gelince ad; düzenlemede tıkla-seç, sürükle-taşı
    let drag = null, downAt = null;
    const cv = renderer.domElement;
    cv.addEventListener('pointerdown', ev => {
      downAt = [ev.clientX, ev.clientY];
      if (!editing || ev.button !== 0) return;
      const hit = pick(ev);
      if (hit && hit.object === sel) {
        const vertical = ev.shiftKey;
        const normal = vertical ? camera.getWorldDirection(new THREE.Vector3()).setY(0).normalize().negate() : new THREE.Vector3(0, 1, 0);
        const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, hit.point);
        drag = { plane, last: hit.point.clone(), vertical, started: false };
        controls.enabled = false;
        cv.setPointerCapture(ev.pointerId);
      }
    });
    cv.addEventListener('pointermove', ev => {
      if (drag) {
        const r = cv.getBoundingClientRect();
        mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
        ray.setFromCamera(mouse, camera);
        const pt = ray.ray.intersectPlane(drag.plane, new THREE.Vector3());
        if (!pt) return;
        const d = pt.clone().sub(drag.last);
        if (!drag.started) { pushUndo(sel); drag.started = true; }
        ensureOv(sel);
        if (drag.vertical) sel.userData.ov.p[1] = r1(sel.userData.ov.p[1] + d.y);
        else { sel.userData.ov.p[0] = r1(sel.userData.ov.p[0] + d.x); sel.userData.ov.p[2] = r1(sel.userData.ov.p[2] + d.z); }
        drag.last.copy(pt);
        dirty.add(sel.userData.id); apply(sel);
        return;
      }
      const hit = pick(ev);
      const o = hit?.object || null;
      if (!editing && hover !== o) { hover = o; paint(); }
      const p = o?.userData.part;
      const r = cv.getBoundingClientRect();
      tipEl.textContent = p ? (p.outside && !saved[p.id] ? `${p.id} · uçağa oturtulmadı` : p.id) : '';
      tipEl.style.display = p ? 'block' : 'none';
      if (p) { tipEl.style.left = `${ev.clientX - r.left + 14}px`; tipEl.style.top = `${ev.clientY - r.top + 10}px`; }
    });
    cv.addEventListener('pointerup', ev => {
      if (drag) {
        controls.enabled = true;
        const moved = drag.started;
        drag = null;
        if (moved) { drawPanel(); noteOutside(); return; }
      }
      if (!editing || !downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 5) return;   // döndürme sürüklemesi: seçim değil
      sel = pick(ev)?.object || null;
      paint(); drawPanel();
    });
    cv.addEventListener('pointerleave', () => { tipEl.style.display = 'none'; if (!editing) { hover = null; paint(); } });
    const onKey = ev => {
      if (!editing || !stage.isConnected || ev.target.closest?.('input, textarea, select')) return;
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') { doUndo(); ev.preventDefault(); return; }
      if (!sel) return;
      const k = ev.key;
      const map = {
        ArrowLeft: () => move(0, -moveStep), ArrowRight: () => move(0, moveStep), ArrowUp: () => move(2, -moveStep), ArrowDown: () => move(2, moveStep),
        PageUp: () => move(1, moveStep), PageDown: () => move(1, -moveStep),
        q: () => rotate(1, rotStep), e: () => rotate(1, -rotStep), r: () => rotate(0, rotStep), f: () => rotate(0, -rotStep),
        t: () => rotate(2, rotStep), g: () => rotate(2, -rotStep), Escape: () => { sel = null; paint(); drawPanel(); },
      };
      const fn = map[k] || map[k.toLowerCase?.()];
      if (fn) { fn(); ev.preventDefault(); }
    };
    addEventListener('keydown', onKey);

    let raf, alive = true;
    const loop = () => { if (!alive) return; controls.update(); box?.update(); renderer.render(scene, camera); raf = requestAnimationFrame(loop); };
    loop();
    const ro = new ResizeObserver(() => {
      const W = stage.clientWidth, H = stage.clientHeight;
      if (W && H) { renderer.setSize(W, H); camera.aspect = W / H; camera.updateProjectionMatrix(); }
    });
    ro.observe(stage);
    stage._asm = { camera, controls, sphere, objs, select: id => { sel = objs.find(o => o.userData.id === id) || null; paint(); drawPanel(); }, setEditing };
    view = {
      dirty: () => dirty.size,
      destroy() {
        alive = false; cancelAnimationFrame(raf); ro.disconnect(); controls.dispose(); removeEventListener('keydown', onKey);
        geoms.forEach(g => g.dispose()); mats.forEach(m => m.dispose()); renderer.dispose(); renderer.domElement.remove();
      },
    };
    if (destroyed) view.destroy();
  })();
  return { destroy: () => { destroyed = true; view.destroy(); }, dirty: () => view.dirty?.() || 0 };
}

/** Pencere (üretim / sipariş şeması): openAssembly(plane, fills) — salt görüntü; düzenleme Ürün Yönetimi › ürün › 3B'de */
export function openAssembly(plane, fills = new Map(), title = '3B Montaj') {
  const host = h('div');
  let v = null;
  modal({
    title, wide: true,
    onClose: () => v?.destroy(),
    body: host,
    actions: [{ label: 'Kapat', class: 'primary' }],
  });
  host.closest('.modal')?.classList.add('asm3d-modal');
  v = mountAssembly(host, { schema: plane.schema || 'caymaz', fills });
  // mountAssembly zaman uyumsuz değil: hemen döner, yüklemeyi kendisi yapar
}
