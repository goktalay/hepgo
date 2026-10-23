// Uçuş Simülatörü §46 / SIMUMAV §28 — sahnede yer pilotu (static/js/modules/flightsim_pilot.js) — tarayıcısız testler:
//   saf yardımcılar (RC → çubuk, yerleşim 6–10 m geride + eve dönük, bakış açıları, gövde/baş payı, omuz kamerası), katman (gerçek three.js; WebGL yok):
//   kurulum, bakış hedefi izleme + gövde dönüşü, çubuk sapması, kalite (lod/gölge) yeniden kurulumu, temizlik; basit yedek figür (HEPGO) sözleşmesi;
//   SIMUMAV kurucusu (avatar_body.buildPilotRig) ≤ 5k üçgen / ≤ 6 çizim çağrısı; flightsim3d.js bağlantısı (varsayılan kapalı, opts.pilot, Pilot gözü).
// Çalıştırma: node tests/test_flightsim_pilot.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = async (name, fn) => { await fn(); n++; console.log(`  ✓ ${name}`); };
const ctx2d = new Proxy({}, { get: (o, k) => (k in o ? o[k] : (k === 'createLinearGradient' ? () => ({ addColorStop() {} }) : () => {})), set: (o, k, v) => { o[k] = v; return true; } });
globalThis.document = { createElement: () => ({ width: 0, height: 0, style: {}, getContext: () => ctx2d }), querySelector: () => null };

const P = await import(pathToFileURL(join(ROOT, 'static/js/modules/flightsim_pilot.js')).href);
const THREE = await import(pathToFileURL(join(ROOT, 'static/vendor/three/three.module.min.js')).href);
const body = await import(pathToFileURL(join(ROOT, 'static/simumav/app/crew/avatar_body.js')).href);
const core = await import(pathToFileURL(join(ROOT, 'static/simumav/app/crew/avatar_core.js')).href);
const near = (a, b, e = 1e-6) => Math.abs(a - b) <= e;

await test('sticksFromRc: Mod 2 kanalları (1 yatış, 2 yunuslama ters, 3 gaz, 4 sapma), ölü bölge, rc yoksa gaz yüzdesi', () => {
  assert.deepEqual(P.sticksFromRc([1500, 1500, 1000, 1500]), { thr: 0, yaw: 0, pitch: 0, roll: 0 });
  const s = P.sticksFromRc([2000, 1000, 2000, 1250]);
  assert.equal(s.thr, 1); assert.equal(s.roll, 1); assert.equal(s.pitch, 1); assert.equal(s.yaw, -0.5);
  assert.equal(P.sticksFromRc([1505, 1495, 1500, 1500]).roll, 0, 'ölü bölge');
  assert.equal(P.sticksFromRc(null, 60, true).thr, 0.6); assert.equal(P.sticksFromRc(null, 60, false).thr, 0);
  assert.equal(P.sticksFromRc([0, 0, 0, 0], 30).thr, 0.3, 'geçersiz kanal (0) → telemetri gazı');
  assert.equal(P.sticksFromRc([2600, 1500, 1500, 1500], 0).thr, 0, 'aralık dışı → telemetri gazı (0)');
});

await test('placePilot: evden 6–10 m geride, eve dönük; yön kuzey/doğu/keyfi', () => {
  for (const yawDeg of [0, 90, 200, -45]) {
    const yaw = yawDeg * Math.PI / 180, home = { x: 12, y: -7 };
    const p = P.placePilot(home, yaw);
    const d = Math.hypot(p.x - home.x, p.y - home.y);
    assert.ok(d >= 6 && d <= 10, `mesafe ${d}`);
    const fx = Math.sin(yaw), fy = Math.cos(yaw);
    assert.ok((home.x - p.x) * fx + (home.y - p.y) * fy > 6, 'kalkış yönünün gerisinde');
    const la = P.lookAngles({ ...p, z: 0 }, { x: home.x, y: home.y, z: 1.6 });
    assert.ok(Math.abs(la.yaw) < 1e-9, 'eve dönük');
  }
  const k = P.placePilot({ x: 0, y: 0 }, 0, { back: 8, side: 0 }); assert.ok(near(k.x, 0) && near(k.y, -8) && near(k.yaw, 0));
});

await test('lookAngles / splitLook / approach / wrapPi / shoulderCam', () => {
  const p = { x: 0, y: 0, z: 0, yaw: 0 };
  assert.ok(near(P.lookAngles(p, { x: 10, y: 0, z: 1.6 }).yaw, Math.PI / 2), 'doğu = sağ (+)');
  assert.ok(near(P.lookAngles(p, { x: -10, y: 0, z: 1.6 }).yaw, -Math.PI / 2));
  assert.ok(P.lookAngles(p, { x: 0, y: 10, z: 11.6 }, 1.6).pitch > 0.7, 'yukarı bakış');
  const s = P.splitLook(1.0); assert.ok(near(s.torso, 0.35) && near(s.head, 0.65));
  const s2 = P.splitLook(3); assert.equal(s2.torso, P.LOOK_LIMITS.torso); assert.equal(s2.head, P.LOOK_LIMITS.head);
  assert.ok(near(P.wrapPi(3 * Math.PI), Math.PI) || near(P.wrapPi(3 * Math.PI), -Math.PI)); assert.ok(near(P.wrapPi(-0.5), -0.5));
  assert.equal(P.approach(0, 1, 5, 0), 0); assert.ok(P.approach(0, 1, 5, 1) > 0.99);
  const c = P.shoulderCam({ x: 0, y: 0, z: 2, yaw: 0 }, 1.6, { x: 0, y: 20, z: 5 });
  assert.ok(c.y < 0 && c.x > 0 && near(c.z, 2 + 1.6 + 0.18), 'omuz üstü: geride + sağda + göz üstü');
});

const sceneMock = () => new THREE.Scene();
await test('katman: kurulum, hedefi izleme (gövde + baş), ayakların dönmesi, yüzey yüksekliği, çubuklar, temizlik', () => {
  const scene = sceneMock();
  let hz = 3;
  const L = P.createPilotLayer(THREE, scene, { build: body.buildPilotRig, terrainHeight: () => hz, lod: 'mid', shadow: true });
  const home = { x: 0, y: 0 }, pp = P.placePilot(home, 0);
  L.set('me', { look: core.legacy('p03'), x: pp.x, y: pp.y, yaw: pp.yaw });
  assert.ok(L.has('me')); assert.equal(scene.children.includes(L.root), true);
  let mesh = 0, cast = 0; L.root.traverse(o => { if (o.isMesh) { mesh++; if (o.castShadow) cast++; } });
  assert.ok(mesh >= 4 && mesh <= 6 && cast === mesh, `mesh ${mesh}`);
  // dron sağ üstte → baş sağa (+) ve yukarı döner; kademeli
  const tgt = { x: 15, y: 0, z: 12 };
  for (let i = 0; i < 120; i++) L.update(1 / 30, i * 33, { target: tgt, sticks: { thr: 1, yaw: 0, pitch: -1, roll: 0.5 } });
  const me = L.info()[0];
  assert.ok(me.head > 0.3 && me.torso > 0.1 && me.pitch > 0.2, JSON.stringify(me));
  assert.equal(me.z, 3, 'yüzey yüksekliği');
  assert.ok(near(me.sticks.l[0], P.STICK_MAX, 1e-3) && near(me.sticks.r[0], -P.STICK_MAX, 1e-3) && near(me.sticks.r[1], P.STICK_MAX * 0.5, 1e-3), 'çubuklar');
  // arkada kalan hedef → ayaklar döner (gövde yönü değişir)
  const y0 = me.yaw;
  for (let i = 0; i < 300; i++) L.update(1 / 30, 4000 + i * 33, { target: { x: pp.x, y: pp.y - 30, z: 5 } });
  assert.ok(Math.abs(P.wrapPi(L.info()[0].yaw - y0)) > 1, 'gövde hedefe döndü');
  // diğer pilot: kendi hedef işlevi; kalite değişimi yeniden kurar, gölge kapanır
  L.set('p-2', { look: core.botAvatar('hard'), x: 30, y: 0, yaw: 0, target: () => ({ x: 30, y: 20, z: 10 }) });
  L.update(0.5, 20000, {});
  L.setQuality({ lod: 'low', shadow: false });
  const lo = L.info(); assert.equal(lo.length, 2); assert.ok(lo.every(x => x.lod === 'low' && x.shadow === false));
  cast = 0; L.root.traverse(o => { if (o.isMesh && o.castShadow) cast++; }); assert.equal(cast, 0);
  L.remove('p-2'); assert.equal(L.info().length, 1);
  L.dispose(); assert.equal(scene.children.includes(L.root), false);
});

await test('basit yedek figür (HEPGO) aynı sözleşme: kemikler, göz yüksekliği, ayak z = 0, yüz −Y', () => {
  const r = P.buildSimplePilot(THREE, { suit: '#334155' });
  for (const k of ['torso', 'head', 'stickL', 'stickR']) assert.ok(r.bones[k], k);
  const bb = new THREE.Box3().setFromObject(r.group);
  assert.ok(Math.abs(bb.min.z) < 0.05 && bb.max.z > 1.6 && bb.max.z < 2, `${bb.min.z} ${bb.max.z}`);
  assert.ok(bb.min.y < -0.2 && bb.max.y < 0.25, 'kumanda önde (−Y)');
  assert.ok(r.tris < 3000 && r.drawCalls <= 6);
  r.dispose();
});

await test('SIMUMAV kurucusu (avatar_body.buildPilotRig): 300 rastgele karakter ≤ 5k üçgen (mid), ≤ 3,6k (low), ≤ 6 çizim çağrısı, boy 1,6–1,9 m', () => {
  let s = 11; const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  const worst = { mid: 0, low: 0 };
  const list = [core.botAvatar('easy'), core.legacy('p01')];
  for (let i = 0; i < 300; i++) list.push(core.randomAvatar(rnd));
  for (const h of core.HAIRS) for (const g of core.HEADGEAR) list.push({ hair: h, headgear: g, beard: 'full', glasses: 'aviator', freckles: true, mole: true, mouth: 'grin', brows: 'arched', visor_open: true });
  for (const a of list) for (const lod of ['mid', 'low']) {
    const r = body.buildPilotRig(THREE, a, { lod });
    worst[lod] = Math.max(worst[lod], r.tris);
    assert.ok(r.drawCalls <= 6, `${r.drawCalls}`);
    if (lod === 'mid' && list.indexOf(a) < 5) { const bb = new THREE.Box3().setFromObject(r.group); assert.ok(bb.min.z > -0.02 && bb.max.z > 1.6 && bb.max.z < 1.95, `${bb.min.z} ${bb.max.z}`); assert.ok(r.eye > 1.4 && r.eye < 1.75); }
    r.dispose();
  }
  assert.ok(worst.mid <= 5000, `mid ${worst.mid}`); assert.ok(worst.low <= 3600, `low ${worst.low}`);
});

await test('flightsim3d.js: pilot varsayılan KAPALI (opts.pilot), Pilot gözü (Yer alt görünümü, tuş 6), §43 kalite, termal, API', () => {
  const src = readFileSync(join(ROOT, 'static/js/modules/flightsim3d.js'), 'utf8');
  assert.match(src, /from '\.\/flightsim_pilot\.js'/);
  assert.match(src, /if \(opts\.pilot && !preview\) setPilot\(/, 'yalnız opts.pilot ile');
  assert.match(src, /mode === 'pilot_eye'/); assert.match(src, /shoulderCam\(sp, sp\.eye, fp\)/);
  assert.match(src, /e\.key === '6'/);
  assert.match(src, /pil\.layer\?\.setQuality\(\{ lod: pilotLod\(\), shadow: gfx\.shadow > 0 \}\)/);
  assert.match(src, /heatRoots\.push\(pil\.layer\.root\)/);
  for (const k of ['setPilot,', 'setPilots,', 'setPilotSticks:', 'getGroundView:', 'pilotInfo:']) assert.ok(src.includes(k), k);
  assert.ok(!/CAMERA_MODES = \[[^\]]*pilot_eye/.test(src), 'CAMERA_MODES değişmedi (HEPGO 1–5)');
  const hepgo = readFileSync(join(ROOT, 'static/js/modules/flightsim.js'), 'utf8');
  assert.ok(!/pilot: \{/.test(hepgo.slice(hepgo.indexOf('createFlightSim3D('))), 'HEPGO oturumu varsayılan açmaz');
  const sm = readFileSync(join(ROOT, 'static/simumav/app/fly/session.js'), 'utf8');
  assert.match(sm, /setPilot\?\.\(normAvatar\(av\), buildPilotRig\)/); assert.match(sm, /\['pilot_eye', 'Pilot gözü'\]/); assert.match(sm, /setPilotSticks\?\.\(MPilot\.sticksFromRc/);
  const hud = readFileSync(join(ROOT, 'static/simumav/app/fly/match_hud.js'), 'utf8');
  assert.match(hud, /sim\.setPilots\(/); assert.match(hud, /playerAvatar\(p\)/); assert.match(hud, /ghostPos/);
  assert.match(readFileSync(join(ROOT, 'static/js/modules/flightsim_match3d.js'), 'utf8'), /const ghostPos = id =>/);
});

console.log(`\n${n} test geçti`);
