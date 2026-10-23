// §27.1.1 kumanda modu (Mode 1–4): saf eşleme + SIMUMAV virtualRC klavye/çubuk eşlemesi + gamepad standart eksen geçişi.
// node tests/test_flightsim_stickmode.mjs
import assert from 'node:assert/strict';
import { STICK_MAP, keyHint, loadStickMode, modePadAxes, normStickMode, saveStickMode, sideOf, stickLabels, stickMap } from '../static/js/modules/flightsim_stickmode.js';
import { STICK_MAP as RC_STICK_MAP, virtualRC } from '../static/simumav/app/fly/rc.js';
import { applyStickModeToPad, loadPadCfg } from '../static/js/modules/flightsim_gamepad.js';

let n = 0;
const test = (ad, fn) => { fn(); n++; console.log(`  ✓ ${ad}`); };
const mem = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }; };

test('eşleme: 4 mod, her modda 4 eksen bir kez; SIMUMAV kopyası birebir', () => {
  for (const m of [1, 2, 3, 4]) assert.deepEqual([...STICK_MAP[m]].sort(), ['pitch', 'roll', 'thr', 'yaw']);
  assert.deepEqual(RC_STICK_MAP, STICK_MAP);
  assert.equal(normStickMode('x'), 2); assert.equal(normStickMode(3), 3);
  assert.deepEqual(stickMap(1), { lx: 'yaw', ly: 'pitch', rx: 'roll', ry: 'thr' });
  assert.equal(sideOf(2, 'thr'), 'l'); assert.equal(sideOf(1, 'thr'), 'r'); assert.equal(sideOf(3, 'roll'), 'l');
});
test('etiketler / klavye ipucu: Mode 2 eski metinle aynı; Mode 3 A/D roll, ←→ yaw', () => {
  assert.deepEqual(stickLabels(2), { left: 'Gaz / Yaw', right: 'Pitch / Roll' });
  assert.equal(keyHint(2), 'W/S gaz · A/D yaw · ↑↓ pitch · ←→ roll');
  assert.equal(keyHint(3), 'W/S pitch · A/D roll · ↑↓ gaz · ←→ yaw');
});
test('tercih: kaydet / yükle, geçersiz → 2', () => {
  const st = mem();
  assert.equal(loadStickMode(st), 2);
  saveStickMode(4, st, null); assert.equal(loadStickMode(st), 4);
  st.setItem('fs.rc.mode', '9'); assert.equal(loadStickMode(st), 2);
});
test('gamepad: varsayılan eksenler moda çekilir, elle atama korunur', () => {
  const all = loadPadCfg(null);
  assert.equal(applyStickModeToPad(all, 1), true);
  assert.deepEqual(all.standard.axes, modePadAxes(1));
  assert.equal(all.standard.axes.thr.i, 3); assert.equal(all.standard.axes.pitch.i, 1);
  all.standard.axes.thr = { i: 5, inv: false };   // elle
  assert.equal(applyStickModeToPad(all, 2), false); assert.equal(all.standard.axes.thr.i, 5);
});

// tarayıcısız virtualRC: zamanlayıcı elle, klavye olayları elle
function rig(mode, plane = false) {
  const L = {}, win = { addEventListener: (t, f) => { L[t] = f; }, removeEventListener() {} };
  const stick = () => ({ querySelector: () => null, addEventListener() {}, removeEventListener() {}, classList: { add() {}, remove() {} } });
  let t = 0; const sent = [];
  const rc = virtualRC({ plane, stickL: stick(), stickR: stick(), send: ch => sent.push(ch), stickMode: () => mode,
    env: { window: win, document: { activeElement: null }, now: () => t, setInterval: () => 1, clearInterval() {} } });
  const key = (k, down = true) => L[down ? 'keydown' : 'keyup']({ key: k, preventDefault() {} });
  const run = (ms) => { for (let i = 0; i < ms / 50; i++) { t += 50; rc.tick(); } return sent.at(-1); };
  return { rc, key, run };
}
test('virtualRC Mode 2: D → yaw (ch4), → → roll (ch1)', () => {
  const r = rig(2); r.key('d'); const ch = r.run(500); assert.ok(ch[3] > 1700 && Math.abs(ch[0] - 1500) < 5, ch);
  r.key('d', false); r.key('arrowright'); const c2 = r.run(1000); assert.ok(c2[0] > 1700 && Math.abs(c2[3] - 1500) < 30, c2);
});
test('virtualRC Mode 3: D → roll (ch1), → → yaw (ch4), ↑ → gaz (ch3)', () => {
  const r = rig(3); r.key('d'); const ch = r.run(500); assert.ok(ch[0] > 1700 && Math.abs(ch[3] - 1500) < 5, ch);
  r.key('d', false); r.key('arrowright'); const c2 = r.run(1000); assert.ok(c2[3] > 1700, c2);
  r.key('arrowright', false); r.key('arrowup'); const c3 = r.run(500); assert.ok(c3[2] > 1700, c3);
});
test('virtualRC Mode 1: W → pitch ileri (ch2 düşük), ↑ → gaz', () => {
  const r = rig(1); r.key('w'); const ch = r.run(500); assert.ok(ch[1] < 1300 && Math.abs(ch[2] - 1500) < 5, ch);
  r.key('w', false); r.key('arrowup'); const c2 = r.run(1000); assert.ok(c2[2] > 1700, c2);
});
test('virtualRC Mode 4 uçak: ↑ gaz tutmalı değil (pitch), W gaz tutmalı', () => {
  const r = rig(4, true); r.key('w'); r.run(1000); r.key('w', false); const ch = r.run(1000); assert.ok(ch[2] > 1200, ch);   // bırakınca yerinde kalır
  r.key('arrowup'); const c2 = r.run(500); assert.ok(c2[1] < 1300, c2);
});
console.log(`\n${n} test geçti`);
