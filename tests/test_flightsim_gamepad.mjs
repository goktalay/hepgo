// Uçuş Simülatörü §37 — FİZİKSEL KUMANDA (Gamepad API) tarayıcısız birim testi (flightsim_gamepad.js saf katmanı + SIMUMAV rc.js virtualRC `pad` girdisi):
//   • profil (standard / rc), ölü bölge, girdi hassasiyeti (genel ölçek / eksen ölçeği / expo; uçak mutlak gazı tek yönlü), atama algılama, eksen eşleme + ters çevirme, ayar doğrulama / kalıcılık, düğme kenarları → eylemler
//   • sanal kumanda RC yolu: kumanda eksenleri Mode 2 kanallarına (sol gaz/sapma, sağ yunuslama/yatış), kara aracında gaz + direksiyon; dokunulan
//     sanal çubuk o tarafta öncelikli; kumanda nötr ve hareketsizken klavye çalışır; uçakta standart gamepad gaz kolu hız olarak; varsayılan açılışta
//     kopter ch3 ilk gaz girdisine dek 0 (lazyThr)
//   • metinler: HEPGO 6 dil + SIMUMAV 7 dil (pad.*); HEPGO / SIMUMAV oturumu modülü bağlar
// Çalıştırma: node tests/test_flightsim_gamepad.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_PAD, PAD_SENS_LIMITS, PAD_TEXTS, deadzone, loadPadCfg, makePadT, normPadCfg, padActionsFor, padButtonEdges, padCurve, padIsNeutral, padLearnAxis, padProfile, padThrAbs, readPadAxes, readPadRaw, savePadCfg, shapePadAxes } from '../static/js/modules/flightsim_gamepad.js';
import { virtualRC } from '../static/simumav/app/fly/rc.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≈ ${b}`);
const memStorage = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }; };
const btn = p => ({ pressed: p, value: p ? 1 : 0 });
const stdPad = (axes = [0, 0, 0, 0], pressedIdx = []) => ({ mapping: 'standard', id: 'Xbox Wireless Controller', index: 0, axes, buttons: Array.from({ length: 17 }, (_, i) => btn(pressedIdx.includes(i))) });

console.log('saf katman');
test('profil: mapping standard → standard; boş / başka → rc', () => {
  assert.equal(padProfile({ mapping: 'standard' }), 'standard'); assert.equal(padProfile({ mapping: '' }), 'rc'); assert.equal(padProfile(null), 'rc');
});
test('ölü bölge: içi 0, dışı yeniden ölçekli, uçta ±1; bozuk → 0', () => {
  assert.equal(deadzone(0.05, 0.08), 0); assert.equal(deadzone(-0.08, 0.08), 0);
  close(deadzone(0.54, 0.08), 0.5); close(deadzone(-0.54, 0.08), -0.5); assert.equal(deadzone(1, 0.08), 1); assert.equal(deadzone(-1, 0.2), -1);
  assert.equal(deadzone(NaN), 0); assert.equal(deadzone(0.3, 0), 0.3);
});
test('standart eşleme: sol Y yukarı = gaz +, sol X = sapma, sağ X = yatış, sağ Y yukarı = yunuslama + (ters)', () => {
  const a = readPadAxes(stdPad([0.5, -1, -1, -0.6]), DEFAULT_PAD.standard);
  assert.equal(a.thr, 1); assert.ok(a.yaw > 0.4 && a.yaw < 0.5); assert.equal(a.roll, -1); assert.ok(a.pitch > 0.5);
  assert.ok(padIsNeutral(readPadAxes(stdPad([0.02, -0.03, 0, 0.05]), DEFAULT_PAD.standard)), 'ölü bölgede nötr');
});
test('RC verici (eşleme ""): X kanatçık, Y irtifa (ters), Z gaz, Rx istikamet; eksik eksen → null; ters çevirme ayarı', () => {
  const gp = { mapping: '', axes: [0.2, -0.5, -1, 0.7] };
  const a = readPadAxes(gp, DEFAULT_PAD.rc);
  assert.ok(a.roll > 0.15); assert.ok(a.pitch > 0.45); assert.equal(a.thr, -1); assert.ok(a.yaw > 0.65);
  assert.equal(readPadAxes({ axes: [0.2, 0.1] }, DEFAULT_PAD.rc).thr, null);
  const c = normPadCfg({ axes: { thr: { i: 2, inv: true } } }, 'rc');
  assert.equal(readPadAxes(gp, c).thr, 1);
  assert.equal(readPadAxes(gp, normPadCfg({ axes: { yaw: { i: -1 } } }, 'rc')).yaw, null, 'atanmamış eksen');
});
test('ayar doğrulama + kalıcılık (fs.pad.cfg, profil başına); bozuk JSON → varsayılan', () => {
  const st = memStorage();
  const all = loadPadCfg(st); assert.deepEqual(all.standard, DEFAULT_PAD.standard); assert.deepEqual(all.rc, DEFAULT_PAD.rc);
  all.standard.dead = 0.15; all.standard.buttons.arm = 3; all.rc.axes.thr.inv = true; savePadCfg(st, all);
  const b = loadPadCfg(st); assert.equal(b.standard.dead, 0.15); assert.equal(b.standard.buttons.arm, 3); assert.equal(b.rc.axes.thr.inv, true);
  assert.equal(normPadCfg({ dead: 9 }).dead, 0.5); assert.equal(normPadCfg({ axes: { thr: { i: 'x' } } }).axes.thr.i, DEFAULT_PAD.standard.axes.thr.i);
  st.setItem('fs.pad.cfg', '{bozuk'); assert.deepEqual(loadPadCfg(st).standard, DEFAULT_PAD.standard);
});
test('düğmeler: yalnız yeni basılan (kenar) eylem üretir; ARM 9 / DISARM 8 / RB-LB mod / yön ch5', () => {
  let e = padButtonEdges(new Set(), stdPad([0, 0, 0, 0], [9]));
  assert.deepEqual(padActionsFor(DEFAULT_PAD.standard, e.down), ['arm']);
  e = padButtonEdges(e.set, stdPad([0, 0, 0, 0], [9]));
  assert.deepEqual(e.down, [], 'basılı tutmak tekrar etmez');
  e = padButtonEdges(e.set, stdPad([0, 0, 0, 0], [8, 5, 12]));
  assert.deepEqual(padActionsFor(DEFAULT_PAD.standard, e.down), ['disarm', 'mode_next', 'ch5_up']);
  assert.deepEqual(padActionsFor(DEFAULT_PAD.rc, [0, 1, 2]), [], 'RC vericide varsayılan düğme ataması yok');
  assert.ok(padButtonEdges(new Set(), { buttons: [0, 1] }).down.includes(1), 'sayısal düğme değeri');
});
test('hassasiyet: varsayılan kimlik (eski fs.pad.cfg aynen); ölçek / expo / kırpma; işaret korunur; 0 → 0', () => {
  for (const x of [-1, -0.6, -0.1, 0, 0.25, 0.5, 1]) close(padCurve(x), x);
  assert.ok(Object.is(padCurve(0, { rate: 150, expo: 80 }, 150), 0));
  close(padCurve(0.5, { rate: 50 }), 0.25); close(padCurve(-0.5, { rate: 50 }), -0.25);
  close(padCurve(0.5, { rate: 100 }, 50), 0.25, 1e-9); close(padCurve(0.5, { rate: 50 }, 50), 0.125);
  assert.equal(padCurve(0.8, { rate: 150 }), 1, 'üst ölçek ±1 ile kırpılır'); assert.equal(padCurve(-1, { rate: 150 }, 150), -1);
  close(padCurve(0.5, { expo: 80 }), 0.2 * 0.5 + 0.8 * 0.125);   // merkezde yumuşak
  assert.equal(padCurve(1, { expo: 80 }), 1, 'uçta tam'); assert.equal(padCurve(-1, { expo: 80 }), -1);
  close(padCurve(0.5, { expo: 300 }), padCurve(0.5, { expo: 80 }), 1e-9);   // sınır: expo ≤ %80
  close(padCurve(0.5, { rate: 1 }, 1), 0.5 * 0.25 * 0.25);                // sınır: ölçekler ≥ %25
  assert.equal(padCurve(NaN), 0);
  // expo tekdüze artan
  let prev = -2; for (let i = 0; i <= 40; i++) { const y = padCurve(-1 + i / 20, { expo: 80, rate: 120 }, 90); assert.ok(y >= prev - 1e-12); prev = y; }
});
test('ayar: scale / sens doğrulanır (aralık, tam sayı, bozuk → varsayılan); kalıcı; eski kayıt (sens yok) → %100 / 0', () => {
  const c = normPadCfg({ scale: 400, sens: { thr: { rate: 10, expo: 99.6 }, yaw: { rate: '120', expo: -3 }, pitch: 'x' } });
  assert.equal(c.scale, PAD_SENS_LIMITS.scale[1]); assert.deepEqual(c.sens.thr, { rate: 25, expo: 80 }); assert.deepEqual(c.sens.yaw, { rate: 120, expo: 0 });
  assert.deepEqual(c.sens.pitch, { rate: 100, expo: 0 }); assert.deepEqual(c.sens.roll, { rate: 100, expo: 0 });
  const old = normPadCfg({ dead: 0.1, axes: { thr: { i: 1, inv: true } } });
  assert.equal(old.scale, 100); assert.ok(Object.values(old.sens).every(q => q.rate === 100 && q.expo === 0));
  const st = memStorage(), all = loadPadCfg(st); all.standard.scale = 75; all.standard.sens.roll = { rate: 130, expo: 40 }; savePadCfg(st, all);
  const b = loadPadCfg(st); assert.equal(b.standard.scale, 75); assert.deepEqual(b.standard.sens.roll, { rate: 130, expo: 40 }); assert.equal(b.rc.scale, 100);
});
test('eksenlere uygulama: ölü bölgeden SONRA, ters çevirmeyle uyumlu; genel ölçek gaza uygulanmaz; null korunur', () => {
  const cfg = normPadCfg({ scale: 50, sens: { roll: { rate: 100, expo: 50 }, thr: { rate: 80 } } });
  const gp = stdPad([0.54, -1, -0.54, 0.05]);   // sapma +0,5 (ölü bölge sonrası), gaz tam, yatış −0,5, yunuslama ölü bölgede
  const raw = readPadRaw(gp, cfg), a = readPadAxes(gp, cfg);
  close(raw.yaw, 0.5); close(raw.roll, -0.5); assert.equal(raw.pitch, 0); assert.equal(raw.thr, 1);
  close(a.yaw, 0.25, 1e-9); close(a.roll, -(0.5 * 0.5 + 0.5 * 0.125) * 0.5, 1e-9); assert.equal(a.pitch, 0);
  close(a.thr, 0.8, 1e-9, 'gaz: yalnız eksen ölçeği (genel %50 değil)');
  const inv = normPadCfg({ scale: 50, axes: { yaw: { i: 0, inv: true } } });
  close(readPadAxes(gp, inv).yaw, -0.25, 1e-9);   // ters çevirme önce, eğri işareti korur
  assert.equal(shapePadAxes({ thr: null, yaw: 0.5, pitch: null, roll: null }, cfg).thr, null);
  assert.ok(padIsNeutral(readPadAxes(stdPad([0.02, -0.03, 0, 0.05]), normPadCfg({ scale: 150, sens: { yaw: { rate: 150, expo: 80 } } }))), 'nötr nötr kalır');
});
test('uçak mutlak gazı (RC verici): eğri rölanti…tam aralığında; rölanti hep −1, tam ölçekte uç ölçeğe göre; kimlikte aynen', () => {
  const id = normPadCfg(null, 'rc');
  for (const x of [-1, -0.5, 0, 0.7, 1]) close(padThrAbs(x, id), x);
  const c = normPadCfg({ sens: { thr: { rate: 50, expo: 60 } } }, 'rc');
  assert.equal(padThrAbs(-1, c), -1, 'rölanti'); close(padThrAbs(1, c), 0, 1e-9, 'tam kol → %50 gaz');
  assert.ok(padThrAbs(0, c) < -0.5, 'expo: alt yarı yumuşak'); assert.equal(padThrAbs(null, c), null);
  const hi = normPadCfg({ sens: { thr: { rate: 150 } } }, 'rc'); assert.equal(padThrAbs(0.5, hi), 1); assert.equal(padThrAbs(-1, hi), -1);
});
test('atama algılama: tabandan en çok oynatılan eksen (≥ eşik); yukarı itince ham azalırsa ters', () => {
  assert.equal(padLearnAxis([0, 0, 0, 0], [0.2, -0.3, 0.1, 0]), null);
  assert.deepEqual(padLearnAxis([0, 0, 0, 0], [0.2, -0.9, 0.6, 0]), { i: 1, inv: true });   // gamepad sol Y yukarı
  assert.deepEqual(padLearnAxis([0, 0, -1, 0], [0, 0, 0.2, 0.1]), { i: 2, inv: false });     // RC verici gazı −1'den yukarı
  assert.deepEqual(padLearnAxis(null, [0, 0, 0, 0.8]), { i: 3, inv: false });
});

console.log('sanal kumanda RC yolu (rc.js virtualRC pad)');
function fakeStick() {
  const knob = { style: {} }, cls = new Set(), ls = {};
  return { knob, listeners: ls, querySelector: () => knob, classList: { add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c) },
    addEventListener: (t, f) => { ls[t] = f; }, removeEventListener: t => { delete ls[t]; }, setPointerCapture: () => {},
    getBoundingClientRect: () => ({ left: 100, top: 100, width: 130, height: 130 }) };
}
function fakeEnv() {
  const wl = {}; let now = 0;
  return { step: ms => { now += ms; }, win: wl,
    env: { window: { addEventListener: (t, f) => { wl[t] = f; }, removeEventListener: t => { delete wl[t]; } }, document: { activeElement: null }, now: () => now,
      setInterval: () => 1, clearInterval: () => {} } };
}
const mk = (opts, padState) => {
  const E = fakeEnv(), L = fakeStick(), R = fakeStick(); let st = padState;
  const rc = virtualRC({ stickL: L, stickR: R, send: () => {}, env: E.env, pad: () => st, ...opts });
  return { rc, E, L, R, set: v => { st = v; }, tick: (k = 1) => { for (let i = 0; i < k; i++) { E.step(50); rc.tick(); } } };
};
test('kopter: kumanda aktif → Mode 2 kanalları (sol gaz/sapma, sağ yunuslama ileri = ch2 düşük, yatış)', () => {
  const T = mk({ plane: false }, { active: true, profile: 'standard', axes: { thr: 1, yaw: -1, pitch: 1, roll: 0.5 } });
  T.tick();
  const c = T.rc.channels();
  assert.equal(c[2], 2000); assert.equal(c[3], 1000); assert.equal(c[1], 1000); assert.equal(c[0], 1750); assert.equal(c[4], 1500);
});
test('dokunulan sanal çubuk o tarafta öncelikli (diğer taraf kumandadan)', () => {
  const T = mk({ plane: false }, { active: true, profile: 'standard', axes: { thr: 1, yaw: 0, pitch: 0, roll: 1 } });
  T.L.listeners.pointerdown({ pointerId: 1, clientX: 165, clientY: 230, preventDefault() {} });   // sol çubuk en alt
  T.tick();
  assert.equal(T.rc.channels()[2], 1000, 'gaz sanal çubuktan'); assert.equal(T.rc.channels()[0], 2000, 'yatış kumandadan');
});
test('kumanda pasif (nötr + hareketsiz) → klavye çalışır', () => {
  const T = mk({ plane: false }, { active: false, profile: 'standard', axes: { thr: 0, yaw: 0, pitch: 0, roll: 0 } });
  T.E.win.keydown({ key: 'w', preventDefault() {} }); T.tick(10);
  assert.ok(T.rc.channels()[2] > 1700, String(T.rc.channels()[2]));
});
test('uçak + standart gamepad: yaylı gaz kolu hız olarak (bırakınca gaz kalır); RC vericide mutlak', () => {
  const T = mk({ plane: true }, { active: true, profile: 'standard', axes: { thr: 1, yaw: 0, pitch: 0, roll: 0 } });
  assert.equal(T.rc.channels()[2], 1000); T.tick(40);   // 0,7 / sn × 2 sn
  const up = T.rc.channels()[2]; assert.ok(up > 1500, String(up));
  T.set({ active: true, profile: 'standard', axes: { thr: 0, yaw: 0, pitch: 0, roll: 0 } }); T.tick(5);
  assert.equal(T.rc.channels()[2], up, 'kol ortada: gaz kalır');
  const R = mk({ plane: true }, { active: true, profile: 'rc', axes: { thr: -0.2, yaw: 0, pitch: 0, roll: 0 } }); R.tick();
  assert.equal(R.rc.channels()[2], 1400, 'RC verici gaz kolu mutlak');
});
test('uçak + RC verici: thrAbs (tek yönlü eğrili) mutlak gaz olarak; kopterde axes.thr; standart gamepadte eğrili hız', () => {
  const R = mk({ plane: true }, { active: true, profile: 'rc', axes: { thr: 0, yaw: 0, pitch: 0, roll: 0 }, thrAbs: -1 }); R.tick();
  assert.equal(R.rc.channels()[2], 1000, 'rölanti (thrAbs −1) — axes.thr 0 kullanılmaz');
  const K = mk({ plane: false }, { active: true, profile: 'rc', axes: { thr: 0.2, yaw: 0, pitch: 0, roll: 0 }, thrAbs: -0.9 }); K.tick();
  assert.equal(K.rc.channels()[2], 1600, 'kopter: merkez = askı, simetrik eğri');
  const cfg = normPadCfg({ sens: { thr: { rate: 50 } } });
  const S = mk({ plane: true }, { active: true, profile: 'standard', axes: readPadAxes(stdPad([0, -1, 0, 0]), cfg) }); S.tick(40);
  const half = S.rc.channels()[2];
  const F = mk({ plane: true }, { active: true, profile: 'standard', axes: readPadAxes(stdPad([0, -1, 0, 0]), DEFAULT_PAD.standard) }); F.tick(40);
  assert.ok(half > 1000 && half < F.rc.channels()[2], `yarım ölçek yarım hız: ${half} < ${F.rc.channels()[2]}`);
});
test('kara aracı: sol dikey gaz, sağ yatay direksiyon (roverChannelsOf); sapma / yunuslama yok', () => {
  const T = mk({ plane: false, rover: true }, { active: true, profile: 'standard', axes: { thr: 0.5, yaw: 1, pitch: 1, roll: -1 } });
  T.tick();
  assert.deepEqual(T.rc.channels(), [1000, 0, 1750, 0, 1500, 0, 0, 0]);
});
test('varsayılan açılış (lazyThr): kopter ch3 = 0 (dokunma) ilk gaz girdisine dek; kumanda gazı / W / sol çubuk açar; ch5 düğmesi', () => {
  const T = mk({ plane: false, lazyThr: true }, null);
  T.tick(); assert.equal(T.rc.channels()[2], 0); assert.equal(T.rc.channels()[0], 1500);
  T.set({ active: true, profile: 'standard', axes: { thr: 0.4, yaw: 0, pitch: 0, roll: 0 } }); T.tick();
  assert.equal(T.rc.channels()[2], 1700);
  const K = mk({ plane: false, lazyThr: true }, null); K.E.win.keydown({ key: 'w', preventDefault() {} }); K.tick();
  assert.ok(K.rc.channels()[2] > 1500);
  const P = mk({ plane: true, lazyThr: true }, null); P.tick(); assert.equal(P.rc.channels()[2], 1000, 'uçakta gaz boşta 1000 (lazy yok)');
  T.rc.bumpCh5(1); assert.equal(T.rc.channels()[4], 2000); T.rc.bumpCh5(-1); T.rc.bumpCh5(-1); assert.equal(T.rc.channels()[4], 1000);
});

console.log('metinler + bağlama');
test('HEPGO 6 dil: pad metinleri', () => {
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = PAD_TEXTS.map(([, v]) => v).filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
  }
});
test('SIMUMAV 7 dil: pad.* anahtarları; makePadT keyed', () => {
  for (const l of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const d = JSON.parse(readFileSync(join(ROOT, 'static/simumav/app/i18n', `${l}.json`), 'utf8'));
    const missing = PAD_TEXTS.map(([k]) => k).filter(k => !(k in d));
    assert.deepEqual(missing, [], `${l}: eksik ${missing.join(' | ')}`);
  }
  assert.equal(makePadT(k => (k === 'pad.btn' ? 'Controller' : k), true)('pad.btn'), 'Controller');
  assert.equal(makePadT(null)('pad.connected', { n: 'X' }), 'Kumanda bağlandı: X');
});
test('HEPGO + SIMUMAV oturumu: kumanda modülü bağlı, sanal kumanda varsayılan açık, kayıtta yok', () => {
  const hp = readFileSync(join(ROOT, 'static/js/modules/flightsim.js'), 'utf8');
  assert.ok(/createGamepadCtl\(/.test(hp) && /pad: \(\) => padCtl\?\.state\(\)/.test(hp));
  assert.ok(/canWrite && !replay && pref\('fs\.rc\.on', '1'\) !== '0'\) rcToggle\(\{ auto: true \}\)/.test(hp), 'HEPGO varsayılan açık (oynatmada yok)');
  const sm = readFileSync(join(ROOT, 'static/simumav/app/fly/session.js'), 'utf8');
  assert.ok(/'flightsim_gamepad\.js'/.test(sm) && /MPad\.createGamepadCtl\(/.test(sm) && /pad: \(\) => padCtl\.state\(\)/.test(sm));
  assert.ok(/pref\('rcOn', true\) !== false\) rcToggle\(\{ auto: true \}\)/.test(sm), 'SIMUMAV varsayılan açık');
  for (const src of [hp, sm]) {
    assert.ok(/createGamepadCtl\(\{ tr,[^\n]*vehicle: rover \? 'rover'[^\n]*feelShape: \(k, v\) => rcShape\(k, v\)/.test(src), 'araç türü + ⚙ ortak eğri önizlemesi');
    assert.ok(/rcShape = rcFeel\.shaper\(\); padCtl\?\.refreshCurve\(\)/.test(src), '⚙ değişince birleşik eğri tazelenir');
    assert.ok(/ps\.thrAbs != null \? ps\.thrAbs : a\.thr/.test(src) || src === sm, 'HEPGO virtualRC: uçak mutlak gazı');
  }
  assert.ok(/ps\.thrAbs != null \? ps\.thrAbs : a\.thr/.test(readFileSync(join(ROOT, 'static/simumav/app/fly/rc.js'), 'utf8')), 'SIMUMAV rc.js: uçak mutlak gazı');
});

console.log(`\n${n} test geçti`);
