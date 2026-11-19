// Uçuş Simülatörü — KARIŞTIRMA 3B katmanı (docs/ucus-simulatoru.md §49). flightsim_jam.js sahne modelini (sceneModel) 3B dünyaya çizer:
//   • karıştırıcı bölgesi: yarı saydam silindir duvar + araziyi izleyen zemin çemberi + üst çember + merkez direği + etiket
//     (kırmızı: araç içeride · turuncu: araç dışarıda · mavi kesikli: panelde henüz uygulanmamış taslak),
//   • "hayalet": otopilotun sandığı konum (tele.nav_lat / nav_lon; aracın irtifasında) — fuşya küre + sabit ekran boyutlu simge + etiket,
//     gerçek araca kesikli bağlantı çizgisi ve zemine düşey çizgi.
// three import ETMEZ: flightsim3d.js nesnesinin `three`, `scene`, `toLocal`, `terrainHeight`, `position`, `addFrameHook` alanlarını kullanır
// (yerel eksenler: x doğu, y kuzey, z yukarı — m).
// createJamLayer(sim) → { set(model, { zone: etiket, ghost: etiket }), dispose() } ya da sim uygun değilse null.
export const ZONE_COLORS = { in: 0xef4444, out: 0xf59e0b, draft: 0x38bdf8 };
export const GHOST_COLOR = 0xe879f9;
const SEG = 96, REGROUND_MS = 3000;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const hex = c => `#${c.toString(16).padStart(6, '0')}`;

export function createJamLayer(sim) {
  const T = sim?.three;
  if (!T || !sim.scene || !sim.toLocal) return null;
  const root = new T.Group(); root.name = 'fs-jam'; sim.scene.add(root);
  const ground = (x, y) => { try { const v = Number(sim.terrainHeight?.(x, y)); return Number.isFinite(v) ? v : 0; } catch { return 0; } };
  const vehPos = () => { try { const p = sim.position?.(); return p && Number.isFinite(p.x) ? p : null; } catch { return null; } };
  const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

  // Sabit ekran boyutlu etiket (metin değişince tuval yeniden çizilir)
  function label(color, scale) {
    const w = 512, hgt = 88, cv = document.createElement('canvas'); cv.width = w; cv.height = hgt;
    const tex = new T.CanvasTexture(cv); tex.colorSpace = T.SRGBColorSpace;
    const spr = new T.Sprite(new T.SpriteMaterial({ map: tex, depthTest: false, transparent: true, sizeAttenuation: false }));
    spr.scale.set(scale * w / hgt, scale, 1); spr.renderOrder = 23;
    let text = null, col = color;
    spr.userData.set = (t, c = col) => {
      if (t === text && c === col) return;
      text = t; col = c;
      const g = cv.getContext('2d'); g.clearRect(0, 0, w, hgt);
      g.font = 'bold 38px ui-monospace, SFMono-Regular, Menlo, monospace';
      const tw = Math.min(w - 16, g.measureText(String(t)).width + 44), x0 = (w - tw) / 2;
      g.fillStyle = 'rgba(11,18,32,.84)'; g.beginPath(); g.roundRect(x0, 6, tw, hgt - 12, 18); g.fill();
      g.lineWidth = 5; g.strokeStyle = hex(col); g.stroke();
      g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(String(t), w / 2, hgt / 2 + 2, tw - 28);
      tex.needsUpdate = true;
    };
    return spr;
  }

  // ---- karıştırıcı bölgesi ----
  const zg = new T.Group(); zg.visible = false; root.add(zg);          // birim silindir: konum (cx, cy, taban), ölçek (r, r, yükseklik)
  const cyl = new T.CylinderGeometry(1, 1, 1, SEG, 1, true); cyl.rotateX(Math.PI / 2); cyl.translate(0, 0, 0.5);   // eksen +Z, taban z = 0
  const wallMat = new T.MeshBasicMaterial({ color: ZONE_COLORS.out, transparent: true, opacity: 0.11, side: T.DoubleSide, depthWrite: false });
  const wall = new T.Mesh(cyl, wallMat); wall.renderOrder = 20; zg.add(wall);
  const unit = new Float32Array(SEG * 3);
  for (let i = 0; i < SEG; i++) { const a = i / SEG * Math.PI * 2; unit[i * 3] = Math.cos(a); unit[i * 3 + 1] = Math.sin(a); unit[i * 3 + 2] = 1; }
  const topGeo = new T.BufferGeometry(); topGeo.setAttribute('position', new T.BufferAttribute(unit, 3));
  const lineMat = new T.LineBasicMaterial({ color: ZONE_COLORS.out, transparent: true, opacity: 0.9, depthWrite: false });
  const dashMat = new T.LineDashedMaterial({ color: ZONE_COLORS.draft, transparent: true, opacity: 0.95, depthWrite: false, dashSize: 12, gapSize: 9 });
  const top = new T.LineLoop(topGeo, lineMat); top.renderOrder = 21; zg.add(top);
  const poleGeo = new T.BufferGeometry(); poleGeo.setAttribute('position', new T.BufferAttribute(new Float32Array([0, 0, 0, 0, 0, 1]), 3));
  const pole = new T.Line(poleGeo, lineMat); pole.renderOrder = 21; zg.add(pole);
  const gPos = new Float32Array((SEG + 1) * 3);                          // zemin çemberi: dünya koordinatı (arazi takipli), kapalı çizgi
  const gGeo = new T.BufferGeometry(); gGeo.setAttribute('position', new T.BufferAttribute(gPos, 3));
  const gLine = new T.Line(gGeo, lineMat); gLine.visible = false; gLine.frustumCulled = false; gLine.renderOrder = 21; root.add(gLine);
  const zLabel = label(ZONE_COLORS.out, 0.034); zLabel.center.set(0.5, 0); zLabel.visible = false; root.add(zLabel);
  let zKey = '', zAt = 0, zBase = 0, zTop = 0;
  function layZone(z, c) {
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i <= SEG; i++) {
      const a = (i % SEG) / SEG * Math.PI * 2, x = c.x + Math.cos(a) * z.r_m, y = c.y + Math.sin(a) * z.r_m, h = ground(x, y);
      gPos[i * 3] = x; gPos[i * 3 + 1] = y; gPos[i * 3 + 2] = h + 0.8;
      if (h < lo) lo = h; if (h > hi) hi = h;
    }
    const hc = ground(c.x, c.y); lo = Math.min(lo, hc); hi = Math.max(hi, hc);
    gGeo.attributes.position.needsUpdate = true; gGeo.computeBoundingSphere(); gLine.computeLineDistances();
    zBase = lo - 30; zTop = hi + clamp(z.r_m, 250, 1500);
  }
  function setZone(z, text) {
    if (!z) { zg.visible = gLine.visible = zLabel.visible = false; zKey = ''; return; }
    const c = sim.toLocal(z.lat, z.lon), key = `${Math.round(c.x)}|${Math.round(c.y)}|${z.r_m}`, t = now();
    if (key !== zKey || t - zAt > REGROUND_MS) { layZone(z, c); zKey = key; zAt = t; }   // arazi karoları sonradan yüklenir: aralıklı yeniden oturt
    const v = vehPos(), topZ = v && v.z > zTop - 60 ? v.z + 200 : zTop;                    // araç tavanın üstüne çıkmasın: duvar uzar
    const col = ZONE_COLORS[z.state] ?? ZONE_COLORS.out, draft = z.state === 'draft';
    wallMat.color.setHex(col); wallMat.opacity = z.state === 'in' ? 0.14 : draft ? 0.07 : 0.1;
    lineMat.color.setHex(col); dashMat.color.setHex(col);
    gLine.material = draft ? dashMat : lineMat; top.material = draft ? dashMat : lineMat;
    if (draft) top.computeLineDistances();
    zg.position.set(c.x, c.y, zBase); zg.scale.set(z.r_m, z.r_m, Math.max(10, topZ - zBase));
    zLabel.position.set(c.x, c.y, topZ + 4); zLabel.userData.set(text || '', col);
    zg.visible = gLine.visible = true; zLabel.visible = !!text;
  }

  // ---- hayalet: otopilotun sandığı konum ----
  const gg = new T.Group(); gg.visible = false; root.add(gg);
  const orbGeo = new T.SphereGeometry(1.6, 20, 14);
  const orbMat = new T.MeshBasicMaterial({ color: GHOST_COLOR, transparent: true, opacity: 0.3, depthWrite: false });
  const wireMat = new T.MeshBasicMaterial({ color: GHOST_COLOR, wireframe: true, transparent: true, opacity: 0.85, depthWrite: false });
  const orb = new T.Mesh(orbGeo, orbMat), wire = new T.Mesh(orbGeo, wireMat); orb.renderOrder = wire.renderOrder = 21; gg.add(orb, wire);
  const icv = document.createElement('canvas'); icv.width = icv.height = 96;   // sabit ekran boyutlu simge: halka + artı (uzaktan da seçilir)
  { const g = icv.getContext('2d'); g.strokeStyle = hex(GHOST_COLOR); g.lineWidth = 7; g.beginPath(); g.arc(48, 48, 30, 0, Math.PI * 2); g.stroke();
    g.lineWidth = 5; g.beginPath(); g.moveTo(48, 6); g.lineTo(48, 34); g.moveTo(48, 62); g.lineTo(48, 90); g.moveTo(6, 48); g.lineTo(34, 48); g.moveTo(62, 48); g.lineTo(90, 48); g.stroke(); }
  const iTex = new T.CanvasTexture(icv); iTex.colorSpace = T.SRGBColorSpace;
  const icon = new T.Sprite(new T.SpriteMaterial({ map: iTex, depthTest: false, transparent: true, sizeAttenuation: false })); icon.scale.set(0.045, 0.045, 1); icon.renderOrder = 23; gg.add(icon);
  const gLabel = label(GHOST_COLOR, 0.032); gLabel.center.set(0.5, -0.85); gLabel.renderOrder = 24; gg.add(gLabel);
  const linkMat = new T.LineDashedMaterial({ color: GHOST_COLOR, transparent: true, opacity: 0.9, depthTest: false, dashSize: 3, gapSize: 2 });
  const linkGeo = new T.BufferGeometry(); linkGeo.setAttribute('position', new T.BufferAttribute(new Float32Array(6), 3));
  const link = new T.Line(linkGeo, linkMat); link.visible = false; link.frustumCulled = false; link.renderOrder = 22; root.add(link);
  const dropGeo = new T.BufferGeometry(); dropGeo.setAttribute('position', new T.BufferAttribute(new Float32Array(6), 3));
  const drop = new T.Line(dropGeo, new T.LineBasicMaterial({ color: GHOST_COLOR, transparent: true, opacity: 0.45, depthWrite: false })); drop.visible = false; drop.frustumCulled = false; root.add(drop);
  let gTarget = null, gFresh = true;
  function setGhost(gh, text) {
    if (!gh) { gg.visible = link.visible = drop.visible = false; gTarget = null; gFresh = true; return; }
    const l = sim.toLocal(gh.lat, gh.lon); gTarget = { x: l.x, y: l.y };
    gLabel.userData.set(text || ''); gLabel.visible = !!text;
  }
  // Render sonrası kanca: hayalet araçla aynı karede ilerlesin (telemetri 10 Hz, sahne 60 Hz → yumuşatma)
  function tick() {
    if (!gTarget) return;
    const v = vehPos(); if (!v) return;
    if (gFresh) { gg.position.set(gTarget.x, gTarget.y, v.z); gFresh = false; }
    else { gg.position.x += (gTarget.x - gg.position.x) * 0.2; gg.position.y += (gTarget.y - gg.position.y) * 0.2; gg.position.z = v.z; }
    const p = gg.position, a = linkGeo.attributes.position.array, d = dropGeo.attributes.position.array;
    a[0] = v.x; a[1] = v.y; a[2] = v.z; a[3] = p.x; a[4] = p.y; a[5] = p.z;
    linkGeo.attributes.position.needsUpdate = true; link.computeLineDistances();
    d[0] = p.x; d[1] = p.y; d[2] = p.z; d[3] = p.x; d[4] = p.y; d[5] = Math.min(p.z, ground(p.x, p.y));
    dropGeo.attributes.position.needsUpdate = true;
    gg.visible = link.visible = drop.visible = true;
  }
  const unhook = sim.addFrameHook ? sim.addFrameHook(() => tick()) : null;

  return {
    /** model = sceneModel(...) çıktısı; labels = { zone, ghost } (çevrilmiş etiket metinleri). */
    set(model, labels = {}) {
      setZone(model?.zone || null, labels.zone);
      setGhost(model?.ghost || null, labels.ghost);
      if (!unhook) tick();
    },
    dispose() {
      unhook?.();
      sim.scene.remove(root);
      root.traverse(o => { o.geometry?.dispose?.(); const m = o.material; if (m) { m.map?.dispose?.(); m.dispose?.(); } });
      dashMat.dispose(); lineMat.dispose();
    },
  };
}
