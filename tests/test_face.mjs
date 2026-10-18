// Yüz ile giriş — static/js/facemath.js saf fonksiyon testleri (sunucu app/facelogin.py ile aynı eşleme).
// Çalıştırma: node tests/test_face.mjs
import assert from 'node:assert/strict';
import { SEGMENTS, SLOTS, R_CENTER, R_SEG, segmentOf, poseMatches, cosine, normalize, ringProgress, nextSegment,
  framing, framingHint, DIRECTION_TEXT, screenPose } from '../static/js/facemath.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };

test('yuva listesi: merkez + 8 yön, sağdan saat yönünün tersine', () => {
  assert.deepEqual(SEGMENTS, ['right', 'up_right', 'up', 'up_left', 'left', 'down_left', 'down', 'down_right']);
  assert.equal(SLOTS.length, 9); assert.equal(SLOTS[0], 'center');
  assert.ok(R_CENTER < R_SEG);
});

test('aynalı ekran pozu: ham yaw<0 → ekranda sağ, pitch<0 → yukarı', () => {
  assert.deepEqual(screenPose(-0.5, -0.3), { sx: 0.5, sy: 0.3 });
  assert.deepEqual(screenPose(0.5, 0.3, false), { sx: 0.5, sy: -0.3 });
});

test('segmentOf: merkez / 8 yön / ara bölge (sunucu testiyle aynı değerler)', () => {
  assert.equal(segmentOf(0, 0), 'center');
  assert.equal(segmentOf(0.1, -0.05), 'center');
  assert.equal(segmentOf(-0.5, 0), 'right');
  assert.equal(segmentOf(0.5, 0), 'left');
  assert.equal(segmentOf(0, -0.5), 'up');
  assert.equal(segmentOf(0, 0.5), 'down');
  assert.equal(segmentOf(-0.4, -0.4), 'up_right');
  assert.equal(segmentOf(0.4, -0.4), 'up_left');
  assert.equal(segmentOf(0.4, 0.4), 'down_left');
  assert.equal(segmentOf(-0.4, 0.4), 'down_right');
  assert.equal(segmentOf(-0.17, 0), null);           // belirsiz halka
  assert.equal(segmentOf(-0.5, 0, false), 'left');   // aynasız
  // dilim sınırları: 22,5° ekseninde deterministik
  assert.equal(segmentOf(-0.3, -Math.tan((22.4 * Math.PI) / 180) * 0.3), 'right');
  assert.equal(segmentOf(-0.3, -Math.tan((22.6 * Math.PI) / 180) * 0.3), 'up_right');
});

test('poseMatches: canlılık yönü eşiği 0,18', () => {
  assert.ok(poseMatches(-0.3, 0, 'right')); assert.ok(!poseMatches(0.3, 0, 'right')); assert.ok(!poseMatches(-0.1, 0, 'right'));
  assert.ok(poseMatches(0.3, 0, 'left')); assert.ok(poseMatches(0, -0.3, 'up')); assert.ok(poseMatches(0, 0.3, 'down'));
  assert.ok(!poseMatches(0, 0, 'yok'));
});

test('cosine / normalize', () => {
  const a = [1, 0, 0, 0], b = [0, 1, 0, 0], c = [2, 0, 0, 0];
  assert.equal(cosine(a, a), 1); assert.equal(cosine(a, b), 0); assert.ok(Math.abs(cosine(a, c) - 1) < 1e-9);
  assert.equal(cosine([0, 0], [0, 0]), 0);
  const nrm = normalize([3, 4]); assert.ok(Math.abs(nrm[0] - 0.6) < 1e-9 && Math.abs(nrm[1] - 0.8) < 1e-9);
});

test('ringProgress: 9 pay', () => {
  assert.equal(ringProgress([]), 0);
  assert.ok(Math.abs(ringProgress(['center']) - 1 / 9) < 1e-9);
  assert.equal(ringProgress(SLOTS), 1);
  assert.equal(ringProgress(['bilinmeyen']), 0);
});

test('nextSegment: önce merkez, sonra saat yönünde en yakın boş yön', () => {
  assert.equal(nextSegment([]), 'center');
  assert.equal(nextSegment(['center']), 'right');
  assert.equal(nextSegment(['center', 'right']), 'up_right');
  assert.equal(nextSegment(['center', 'right', 'up_right', 'up']), 'up_left');
  assert.equal(nextSegment(['center', 'down_right']), 'right');            // sarmal
  assert.equal(nextSegment(['center', 'right', 'up']), 'up_left');          // son dolu = up → sıradaki boş
  assert.equal(nextSegment(SLOTS), null);
});

test('framing / framingHint', () => {
  assert.equal(framing(null, 480, 360), null);
  const good = framing([140, 60, 200, 240], 480, 360);
  assert.ok(good.off < 0.05 && good.size > 0.6);
  assert.equal(framingHint(good), null);
  assert.equal(framingHint(framing([200, 150, 60, 60], 480, 360)), 'Biraz yaklaşın');
  assert.equal(framingHint(framing([0, 0, 470, 350], 480, 360)), 'Biraz uzaklaşın');
  assert.equal(framingHint(framing([0, 0, 180, 180], 480, 360)), 'Yüzünüzü ortalayın');
  assert.equal(framingHint(null), null);
});

test('yönlendirme metinleri her yuva için var', () => {
  for (const s of SLOTS) assert.ok(DIRECTION_TEXT[s] && DIRECTION_TEXT[s].length > 5, s);
});

console.log(`${n} test geçti.`);
