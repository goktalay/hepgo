// Köşedeki yapay zeka maskotu: sürekli farklı animasyonlar yapar (el sallama, zıplama, kafa şişip patlama…);
// tıklanınca Claude API sohbet penceresi açılır. Sürüklenip taşınabilir (yeri cihazda saklanır) ve orada oynamaya
// devam eder. Karakter Kişisel Ayarlar → Maskot'tan seçilir (kullanıcıya kayıtlı). Anahtar tanımlı değilse gösterilmez.
import { api } from '../api.js';
import { h, clear, svgIcon, t } from '../ui.js';
import { icons } from '../icons.js';
import { createMascot3D, mascot3dSnapshot, webglOK } from './mascot3d.js';

// ---- Maskot karakterleri (SVG). Ortak sınıf kancaları: .m-pop (kafa → şişip patlama), .m-wavearm (el sallama). ----
const MASCOTS = {
  kubbe: {
    name: 'Kubbe', desc: 'Şişman adam', svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="34" ry="6"/>
      <rect class="m-leg" x="44" y="104" width="13" height="26" rx="6"/>
      <rect class="m-leg" x="63" y="104" width="13" height="26" rx="6"/>
      <g class="m-arm m-wavearm"><rect x="90" y="70" width="14" height="34" rx="7"/></g>
      <g class="m-arm"><rect x="16" y="70" width="14" height="34" rx="7"/></g>
      <ellipse class="m-belly" cx="60" cy="86" rx="38" ry="34"/>
      <ellipse class="m-shirt" cx="60" cy="98" rx="30" ry="22"/>
      <g class="m-pop">
        <circle class="m-head" cx="60" cy="40" r="26"/>
        <path class="m-hair" d="M36 30 Q60 6 84 30 Q60 20 36 30 Z"/>
        <circle class="m-eye" cx="51" cy="38" r="3.4"/><circle class="m-eye" cx="69" cy="38" r="3.4"/>
        <circle class="m-cheek" cx="45" cy="48" r="4"/><circle class="m-cheek" cx="75" cy="48" r="4"/>
        <path class="m-smile" d="M50 50 Q60 60 70 50"/>
      </g>` },
  robo: {
    name: 'Robo', desc: 'Robot', svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="32" ry="6"/>
      <rect class="m-leg" x="46" y="108" width="12" height="22" rx="4"/>
      <rect class="m-leg" x="62" y="108" width="12" height="22" rx="4"/>
      <g class="m-arm m-wavearm"><rect x="90" y="66" width="12" height="32" rx="6"/></g>
      <g class="m-arm"><rect x="18" y="66" width="12" height="32" rx="6"/></g>
      <rect class="m-belly" x="30" y="64" width="60" height="52" rx="12"/>
      <rect class="m-shirt" x="44" y="88" width="32" height="18" rx="4"/>
      <g class="m-pop">
        <line class="m-ant" x1="60" y1="14" x2="60" y2="26"/><circle class="m-antdot" cx="60" cy="12" r="4"/>
        <rect class="m-head" x="36" y="24" width="48" height="38" rx="10"/>
        <circle class="m-eye" cx="51" cy="42" r="5"/><circle class="m-eye" cx="69" cy="42" r="5"/>
        <rect class="m-smile2" x="49" y="52" width="22" height="4" rx="2"/>
      </g>` },
  kedi: {
    name: 'Pati', desc: 'Kedi', svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="32" ry="6"/>
      <g class="m-arm m-wavearm"><rect x="86" y="82" width="12" height="28" rx="6"/></g>
      <g class="m-arm"><rect x="22" y="82" width="12" height="28" rx="6"/></g>
      <ellipse class="m-belly" cx="60" cy="92" rx="34" ry="32"/>
      <ellipse class="m-shirt" cx="60" cy="100" rx="20" ry="18"/>
      <path class="m-tail" d="M92 108 Q112 100 104 78" fill="none"/>
      <g class="m-pop">
        <path class="m-ear" d="M40 26 L34 6 L54 20 Z"/><path class="m-ear" d="M80 26 L86 6 L66 20 Z"/>
        <circle class="m-head" cx="60" cy="40" r="26"/>
        <circle class="m-eye" cx="50" cy="38" r="4"/><circle class="m-eye" cx="70" cy="38" r="4"/>
        <path class="m-nose" d="M57 46 L63 46 L60 50 Z"/>
        <path class="m-whisk" d="M38 44 H20 M38 50 H22 M82 44 H100 M82 50 H98" fill="none"/>
        <path class="m-smile" d="M52 50 Q60 58 68 50"/>
      </g>` },
  hayalet: {
    name: 'Boo', desc: 'Hayalet', svg: `
      <ellipse class="m-shadow" cx="60" cy="130" rx="30" ry="6"/>
      <g class="m-arm m-wavearm"><path d="M88 74 Q104 74 100 92" fill="none" stroke-width="12" stroke-linecap="round"/></g>
      <g class="m-pop">
        <path class="m-ghost" d="M28 70 Q28 22 60 22 Q92 22 92 70 L92 116 Q84 106 76 116 Q68 106 60 116 Q52 106 44 116 Q36 106 28 116 Z"/>
        <circle class="m-eye" cx="50" cy="60" r="5"/><circle class="m-eye" cx="70" cy="60" r="5"/>
        <ellipse class="m-cheek" cx="44" cy="72" rx="4" ry="3"/><ellipse class="m-cheek" cx="76" cy="72" rx="4" ry="3"/>
        <path class="m-smile" d="M52 72 Q60 82 68 72"/>
      </g>` },
  penguen: {
    name: 'Pinti', desc: 'Penguen', svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="30" ry="6"/>
      <path class="m-foot" d="M46 124 q-8 6 2 8 h10 z"/><path class="m-foot" d="M74 124 q8 6 -2 8 h-10 z"/>
      <g class="m-arm m-wavearm"><path d="M88 76 q16 4 10 26" fill="none" stroke-width="13" stroke-linecap="round"/></g>
      <g class="m-arm"><path d="M32 76 q-16 4 -10 26" fill="none" stroke-width="13" stroke-linecap="round"/></g>
      <ellipse class="m-belly" cx="60" cy="82" rx="34" ry="46"/>
      <ellipse class="m-shirt" cx="60" cy="90" rx="22" ry="34"/>
      <g class="m-pop">
        <circle class="m-head" cx="60" cy="38" r="26"/>
        <circle class="m-eye" cx="51" cy="36" r="3.6"/><circle class="m-eye" cx="69" cy="36" r="3.6"/>
        <path class="m-beak" d="M53 44 L67 44 L60 52 Z"/>
      </g>` },
  uzayli: {
    name: 'Zog', desc: 'Uzaylı', svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="28" ry="6"/>
      <rect class="m-leg" x="48" y="108" width="9" height="22" rx="4"/>
      <rect class="m-leg" x="63" y="108" width="9" height="22" rx="4"/>
      <g class="m-arm m-wavearm"><rect x="88" y="72" width="10" height="30" rx="5"/></g>
      <g class="m-arm"><rect x="22" y="72" width="10" height="30" rx="5"/></g>
      <ellipse class="m-belly" cx="60" cy="90" rx="28" ry="26"/>
      <g class="m-pop">
        <line class="m-ant" x1="48" y1="18" x2="44" y2="6"/><circle class="m-antdot" cx="43" cy="4" r="3.5"/>
        <line class="m-ant" x1="72" y1="18" x2="76" y2="6"/><circle class="m-antdot" cx="77" cy="4" r="3.5"/>
        <ellipse class="m-head" cx="60" cy="40" rx="30" ry="26"/>
        <ellipse class="m-eye2" cx="50" cy="40" rx="5" ry="8"/><ellipse class="m-eye2" cx="70" cy="40" rx="5" ry="8"/>
        <path class="m-smile" d="M52 52 Q60 58 68 52"/>
      </g>` },
  // ---- Yeni maskotlar (yalnız 2D; her birinin kendine özel numaraları var) ----
  drone: {
    name: 'Pervane', desc: 'Drone', tricks: ['hover', 'propeller', 'tilt'], svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="28" ry="6"/>
      <rect class="m-drone-arm" x="14" y="60" width="34" height="7" rx="3.5"/>
      <rect class="m-drone-arm" x="72" y="60" width="34" height="7" rx="3.5"/>
      <g class="m-prop"><ellipse class="m-drone-rotor" cx="26" cy="58" rx="19" ry="4"/></g>
      <g class="m-prop"><ellipse class="m-drone-rotor" cx="94" cy="58" rx="19" ry="4"/></g>
      <circle class="m-drone-hub" cx="26" cy="58" r="4"/><circle class="m-drone-hub" cx="94" cy="58" r="4"/>
      <path class="m-drone-leg" d="M46 102 L40 120" fill="none"/><path class="m-drone-leg" d="M74 102 L80 120" fill="none"/>
      <rect class="m-drone-body" x="36" y="62" width="48" height="44" rx="18"/>
      <circle class="m-drone-lens" cx="60" cy="84" r="16"/>
      <circle class="m-eye" cx="60" cy="84" r="9"/>
      <circle class="m-drone-glint" cx="55" cy="79" r="3"/>
      <path class="m-smile" d="M50 98 Q60 104 70 98"/>` },
  slime: {
    name: 'Jölo', desc: 'Jöle', tricks: ['squish', 'blobjump'], svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="32" ry="6"/>
      <path class="m-slime-body" d="M18 120 Q10 66 60 52 Q110 66 102 120 Q82 110 62 120 Q42 110 18 120 Z"/>
      <ellipse class="m-slime-shine" cx="46" cy="80" rx="9" ry="15"/>
      <circle class="m-eye" cx="50" cy="92" r="5.5"/><circle class="m-eye" cx="72" cy="92" r="5.5"/>
      <circle class="m-slime-glint" cx="48" cy="90" r="1.8"/><circle class="m-slime-glint" cx="70" cy="90" r="1.8"/>
      <path class="m-smile" d="M51 104 Q61 113 71 104"/>
      <circle class="m-cheek" cx="40" cy="102" r="4.5"/><circle class="m-cheek" cx="82" cy="102" r="4.5"/>` },
  buyucu: {
    name: 'Merlin', desc: 'Büyücü', tricks: ['cast', 'levitate'], svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="28" ry="6"/>
      <path class="m-wiz-robe" d="M34 128 L47 86 Q60 80 73 86 L86 128 Z"/>
      <g class="m-arm m-wavearm"><path d="M72 94 q16 4 12 26" fill="none" stroke-width="11" stroke-linecap="round"/></g>
      <g class="m-arm"><path d="M48 94 q-16 4 -12 26" fill="none" stroke-width="11" stroke-linecap="round"/></g>
      <line class="m-wiz-wand" x1="84" y1="118" x2="99" y2="92"/>
      <circle class="m-wiz-spark" cx="100" cy="90" r="4.5"/>
      <circle class="m-head" cx="60" cy="72" r="18"/>
      <circle class="m-eye" cx="53" cy="70" r="3"/><circle class="m-eye" cx="67" cy="70" r="3"/>
      <path class="m-wiz-beard" d="M45 76 Q60 106 75 76 Q60 86 45 76 Z"/>
      <ellipse class="m-wiz-brim" cx="60" cy="58" rx="27" ry="6"/>
      <path class="m-wiz-hat" d="M39 58 L60 12 L81 58 Z"/>
      <path class="m-wiz-star" d="M60 28 l2.2 5 5.4 .5 -4.1 3.6 1.2 5.3 -4.7-2.8 -4.7 2.8 1.2-5.3 -4.1-3.6 5.4-.5 z"/>` },
  dino: {
    name: 'Riko', desc: 'Dino', tricks: ['stomp', 'roar'], svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="34" ry="6"/>
      <path class="m-dino-tail" d="M90 116 Q114 110 108 86" fill="none"/>
      <rect class="m-dino-leg" x="46" y="108" width="13" height="22" rx="5"/>
      <rect class="m-dino-leg" x="61" y="108" width="13" height="22" rx="5"/>
      <path class="m-dino-spike" d="M33 76 l8 -15 8 15 z"/>
      <path class="m-dino-spike" d="M50 68 l8 -17 8 17 z"/>
      <path class="m-dino-spike" d="M67 68 l8 -17 8 17 z"/>
      <ellipse class="m-dino-body" cx="60" cy="92" rx="34" ry="34"/>
      <ellipse class="m-dino-belly" cx="60" cy="100" rx="21" ry="20"/>
      <g class="m-arm m-wavearm"><rect x="86" y="80" width="10" height="22" rx="5"/></g>
      <g class="m-arm"><rect x="24" y="80" width="10" height="22" rx="5"/></g>
      <g class="m-dino-head-g">
        <circle class="m-dino-head" cx="60" cy="46" r="26"/>
        <ellipse class="m-dino-snout" cx="60" cy="56" rx="18" ry="12"/>
        <circle class="m-eye" cx="51" cy="40" r="3.6"/><circle class="m-eye" cx="69" cy="40" r="3.6"/>
        <circle class="m-dino-nostril" cx="54" cy="54" r="1.8"/><circle class="m-dino-nostril" cx="66" cy="54" r="1.8"/>
        <path class="m-dino-mouth" d="M50 60 q10 6 20 0" fill="none"/>
      </g>` },
  ari: {
    name: 'Vızıl', desc: 'Arı', tricks: ['buzz', 'loop'], svg: `
      <ellipse class="m-shadow" cx="60" cy="132" rx="26" ry="6"/>
      <g class="m-wing m-wing-l"><ellipse class="m-ari-wing" cx="38" cy="58" rx="15" ry="22"/></g>
      <g class="m-wing m-wing-r"><ellipse class="m-ari-wing" cx="82" cy="58" rx="15" ry="22"/></g>
      <ellipse class="m-ari-body" cx="60" cy="86" rx="27" ry="32"/>
      <ellipse class="m-ari-stripe" cx="60" cy="74" rx="22" ry="4.5"/>
      <ellipse class="m-ari-stripe" cx="60" cy="90" rx="24" ry="4.5"/>
      <ellipse class="m-ari-stripe" cx="60" cy="106" rx="18" ry="4.5"/>
      <path class="m-ari-sting" d="M60 118 l-5 10 10 0 z"/>
      <line class="m-ant" x1="52" y1="56" x2="47" y2="44"/><circle class="m-antdot" cx="46" cy="42" r="3"/>
      <line class="m-ant" x1="68" y1="56" x2="73" y2="44"/><circle class="m-antdot" cx="74" cy="42" r="3"/>
      <circle class="m-eye" cx="51" cy="70" r="4"/><circle class="m-eye" cx="69" cy="70" r="4"/>
      <path class="m-smile" d="M52 80 Q60 88 68 80"/>
      <circle class="m-cheek" cx="42" cy="80" r="4"/><circle class="m-cheek" cx="78" cy="80" r="4"/>` },
};

// 3D modeli yalnız orijinal 6 karakter için var (mascot3d.buildCharacter). Yeni maskotlar daima 2D çizilir.
const THREE_D_IDS = new Set(['kubbe', 'robo', 'kedi', 'hayalet', 'penguen', 'uzayli']);
export const has3d = id => THREE_D_IDS.has(id);

export const MASCOT_LIST = Object.entries(MASCOTS).map(([id, m]) => ({ id, name: m.name, desc: m.desc }));
const DEFAULT_ID = 'kubbe';

function figSvg(id) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 120 140');
  const use = MASCOTS[id] ? id : DEFAULT_ID;
  svg.setAttribute('class', `mascot-svg m-${use}`);
  svg.innerHTML = MASCOTS[use].svg;
  return svg;
}

// Ayarlar önizlemesi için dışa açık
export const mascotSvg = figSvg;

// 3D maskot: kullanıcı kapatmadıysa, cihaz WebGL destekliyorsa ve "hareketleri azalt" kapalıysa (aksi halde klasik 2D çizim)
const reduceMotion = () => document.documentElement.classList.contains('reduce-motion') || matchMedia('(prefers-reduced-motion: reduce)').matches;
let want3d = true;
const can3d = () => want3d && has3d(curId) && webglOK() && !reduceMotion();
// Önizleme (ayarlar kartı, sohbet başlığı): 3D'de anlık görüntü, hazır olana dek 2D çizim.
// Yeni (3D'si olmayan) maskotlar için daima 2D svg gösterilir.
export function mascotPreview(id, threeD = can3d()) {
  const box = h('span', { class: 'mascot-prev' }, figSvg(id));
  if (threeD && has3d(id) && webglOK()) {
    mascot3dSnapshot(id).then(url => clear(box, h('img', { class: 'mascot-snap', src: url, alt: '' }))).catch(() => {});
  }
  return box;
}

const TRICKS = ['wave', 'jump', 'wobble', 'spin', 'pop', 'dance', 'peek'];
const POS_KEY = 'caymaz.mascotPos';

// ---- Maskot sesleri (Web Audio ile sentezlenir; dosya yok). Varsayılan KAPALI ("Maskot sesli" ayarı).
// Tarayıcılar ilk kullanıcı etkileşiminden önce sesi engeller: AudioContext ilk dokunuşta açılır/sürdürülür.
let mascotSound = false;        // kullanıcı ayarı (users.prefs.settings.mascotSound — anahtar adı geriye uyumlu)
let audioCtx = null, master = null;
function ensureAudio() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!audioCtx) audioCtx = new Ctx();
    if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
    return audioCtx;
  } catch { return null; }
}
// Tüm maskot sesleri ortak, KISIK bir ana kazançtan geçer (rahatsız etmesin)
const out = ac => {
  if (!master || master.context !== ac) { master = ac.createGain(); master.gain.value = 0.55; master.connect(ac.destination); }
  return master;
};
// Ayarlar › Maskot › "Maskot sesli" anahtarı
export function setMascotSound(on) { mascotSound = on === true; if (mascotSound) ensureAudio(); }

function _tone(ac, { type = 'sine', f0, f1, dur, gain = 0.05, when = 0, vib, dest, filter } = {}) {
  const t0 = ac.currentTime + when;
  const osc = ac.createOscillator(); osc.type = type;
  osc.frequency.setValueAtTime(f0, t0);
  if (f1 != null) osc.frequency.exponentialRampToValueAtTime(Math.max(1, f1), t0 + dur);
  const g = ac.createGain();
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.linearRampToValueAtTime(gain, t0 + Math.min(0.03, dur * 0.3));
  g.gain.exponentialRampToValueAtTime(0.0006, t0 + dur);
  let node = osc;
  if (filter) { const bq = ac.createBiquadFilter(); bq.type = filter[0]; bq.frequency.value = filter[1]; bq.Q.value = filter[2] || 1; osc.connect(bq); node = bq; }
  node.connect(g); g.connect(dest || out(ac));
  if (vib) { const lfo = ac.createOscillator(); lfo.frequency.value = vib[0]; const lg = ac.createGain(); lg.gain.value = vib[1]; lfo.connect(lg); lg.connect(osc.frequency); lfo.start(t0); lfo.stop(t0 + dur); }
  osc.start(t0); osc.stop(t0 + dur + 0.03);
}
function _noise(ac, { dur, gain = 0.05, when = 0, f = 1200, q = 1 } = {}) {
  const n = Math.max(1, Math.floor(ac.sampleRate * dur)), buf = ac.createBuffer(1, n, ac.sampleRate), d = buf.getChannelData(0);
  for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
  const src = ac.createBufferSource(); src.buffer = buf;
  const bp = ac.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = f; bp.Q.value = q;
  const g = ac.createGain(), t0 = ac.currentTime + when;
  g.gain.setValueAtTime(0.0001, t0); g.gain.linearRampToValueAtTime(gain, t0 + 0.02); g.gain.exponentialRampToValueAtTime(0.0006, t0 + dur);
  src.connect(bp); bp.connect(g); g.connect(out(ac));
  src.start(t0); src.stop(t0 + dur + 0.02);
}
// "Ho-ho" gibi ünlü sesi: testere dalga + iki formant süzgeci (ağız rezonansı)
function _vowel(ac, { f0, f1, dur, when = 0, gain = 0.05, formants = [600, 1000] }) {
  formants.forEach((fr, i) => _tone(ac, { type: 'sawtooth', f0, f1, dur, when, gain: gain * (i ? 0.55 : 1), filter: ['bandpass', fr, 6] }));
}
// Her maskota KENDİ karakterine uygun, kısa ve sevimli ses
const MASCOT_SOUNDS = {
  kubbe: ac => { _vowel(ac, { f0: 150, f1: 132, dur: 0.2, gain: 0.09, formants: [520, 900] }); _vowel(ac, { f0: 140, f1: 118, dur: 0.26, when: 0.24, gain: 0.09, formants: [520, 900] }); },   // tok kahkaha "ho-ho"
  robo: ac => [[880, 0], [660, 0.1], [990, 0.2], [740, 0.3]].forEach(([f, w]) => _tone(ac, { type: 'square', f0: f, dur: 0.075, gain: 0.03, when: w, filter: ['lowpass', 2400, 0.7] })),   // bip-bop
  kedi: ac => { _tone(ac, { type: 'triangle', f0: 620, f1: 900, dur: 0.13, gain: 0.06, vib: [12, 20] }); _tone(ac, { type: 'triangle', f0: 880, f1: 500, dur: 0.24, gain: 0.055, when: 0.12, vib: [10, 18] }); },   // miyav
  hayalet: ac => _tone(ac, { type: 'sine', f0: 175, f1: 115, dur: 1.05, gain: 0.045, vib: [5, 14] }),   // ürpertici "uuu"
  penguen: ac => { _noise(ac, { dur: 0.07, gain: 0.05, f: 900, q: 1.5 }); _noise(ac, { dur: 0.06, gain: 0.045, when: 0.1, f: 1500, q: 2 }); _tone(ac, { type: 'square', f0: 700, f1: 520, dur: 0.08, gain: 0.015, when: 0.1 }); },   // cıyak cıyak
  uzayli: ac => _tone(ac, { type: 'sine', f0: 520, f1: 720, dur: 0.75, gain: 0.05, vib: [9, 130] }),   // uzaylı theremin
  drone: ac => { _tone(ac, { type: 'sawtooth', f0: 92, f1: 104, dur: 0.9, gain: 0.045, vib: [22, 8] }); _tone(ac, { type: 'square', f0: 184, dur: 0.9, gain: 0.015, vib: [22, 10] }); },   // pervane vızıltısı
  slime: ac => { _tone(ac, { type: 'sine', f0: 180, f1: 420, dur: 0.12, gain: 0.06 }); _tone(ac, { type: 'sine', f0: 300, f1: 260, dur: 0.4, gain: 0.05, when: 0.1, vib: [18, 60] }); },   // jöle "blop-boing"
  buyucu: ac => [660, 880, 1100, 1320].forEach((f, i) => _tone(ac, { type: 'sine', f0: f, dur: 0.1, gain: 0.045, when: i * 0.07 })),   // büyü ışıltısı
  dino: ac => { _tone(ac, { type: 'sawtooth', f0: 150, f1: 68, dur: 0.6, gain: 0.06, vib: [7, 10] }); _noise(ac, { dur: 0.5, gain: 0.03, f: 300, q: 0.8 }); },   // minik kükreme
  ari: ac => _tone(ac, { type: 'sawtooth', f0: 205, f1: 235, dur: 0.7, gain: 0.04, vib: [32, 30] }),   // arı vızıltısı
};
function _play(ac, id) { try { (MASCOT_SOUNDS[id] || MASCOT_SOUNDS.robo)(ac); } catch { /* ses engellendi: sessiz */ } }
function playMascotSound(id) {
  if (!mascotSound || document.hidden) return;
  const ac = audioCtx;
  if (!ac || ac.state !== 'running') return;
  _play(ac, id);
}
// Ayarlar › Maskot: "Sesini dinle" (kullanıcı jestiyle çağrılır; "Maskot sesli" kapalı olsa da çalar)
export function previewMascotSound(id) {
  const ac = ensureAudio();
  if (!ac) return;
  if (ac.state === 'running') _play(ac, id);
  else ac.resume().then(() => _play(ac, id)).catch(() => {});
}

// Ayarlar › Maskot seçici: kutucukta CANLI maskot (köşedeki maskotun aynı canlandırması: boşta salınım + rastgele numaralar).
// Yalnız görünürken oynar (IntersectionObserver); "hareketleri azalt" açıkken durağan kalır. Kutucuk DOM'dan çıkınca kendiliğinden durur.
export function mascotLivePreview(id, threeD) {
  const fig = h('span', { class: 'mascot-fig mascot-live' }, mascotPreview(id, threeD), h('span', { class: 'm-burst' }));
  let visible = false, timer = 0;
  const list = MASCOTS[id]?.tricks || TRICKS;
  const trick = () => {
    if (!fig.isConnected || reduceMotion()) return;
    const tr = list[Math.floor(Math.random() * list.length)];
    fig.classList.add(`trick-${tr}`);
    setTimeout(() => fig.classList.remove(`trick-${tr}`), 1700);
  };
  const loop = () => {
    clearTimeout(timer);
    if (!fig.isConnected && timer) { io.disconnect(); return; }
    if (visible) trick();
    timer = setTimeout(loop, 2600 + Math.random() * 3200);
  };
  const io = new IntersectionObserver(es => { visible = es.some(e => e.isIntersecting); }, { threshold: 0.4 });
  io.observe(fig);
  timer = setTimeout(loop, 600 + Math.random() * 1800);
  fig.playTrick = trick;   // üzerine gelince / seçilince hemen bir numara
  return fig;
}

let mounted = false;
let convo = [];        // {role, content}
let curId = DEFAULT_ID;
let els = null;        // { fig, btn }
let ctl = null;        // 3D maskot denetleyicisi (yoksa 2D SVG)
let _btn = null, _panel = null;   // kullanıcı maskotu kapatınca gizlemek için

// Kullanıcı maskotu kapatıp açabilir (Ayarlar › Maskot). Gizliyken panel de kapanır.
export function applyMascotHidden(hidden) {
  if (_btn) _btn.style.display = hidden ? 'none' : '';
  if (hidden && _panel) { _panel.hidden = true; _btn?.classList.remove('open'); }
}

// Kişisel ayarlardan canlı karakter değişimi (maskot + sohbet başlığı/avatarı)
export function setMascot(id) {
  curId = MASCOTS[id] ? id : DEFAULT_ID;
  if (!els) return;
  // Yeni maskotun 3D modeli yoksa (ya da 3D kapalıysa) canlı 3D'yi söküp 2D çizime dön
  if (ctl && !can3d()) {
    ctl.destroy(); ctl = null;
    els.fig.classList.remove('m3d'); els.btn.classList.remove('is3d');
  }
  if (ctl) ctl.setCharacter(curId);
  else {
    clear(els.fig, [figSvg(curId), h('span', { class: 'm-burst' })]);
    if (can3d()) start3d();   // 2D'den 3D'si olan bir karaktere geçildiyse canlıya çevir
  }
  if (els.headAva) clear(els.headAva, mascotPreview(curId, !!ctl));
  if (els.headName) els.headName.textContent = MASCOTS[curId].name;
}

// Ayarlar › Maskot › "3D maskot" anahtarı: canlı aç / kapat
export async function setMascot3D(on) {
  want3d = on !== false;
  if (!els) return;
  if (can3d() && !ctl) await start3d();
  else if (!can3d() && ctl) {
    ctl.destroy(); ctl = null;
    els.fig.classList.remove('m3d'); els.btn.classList.remove('is3d');
    clear(els.fig, [figSvg(curId), h('span', { class: 'm-burst' })]);
  }
  if (els.headAva) clear(els.headAva, mascotPreview(curId, !!ctl));
}
async function start3d() {
  try {
    const c = await createMascot3D(els.fig, curId);
    if (ctl) { c.destroy(); return; }
    ctl = c;
    els.fig.querySelector('.mascot-svg')?.remove();
    els.fig.classList.add('m3d'); els.btn.classList.add('is3d');
  } catch { /* WebGL açılamadı: 2D kalır */ }
}

export async function mountMascot(ctx) {
  if (mounted) return;
  let status;
  try { status = await api.get('/api/assistant/status'); } catch { return; }
  if (!status?.enabled) return;
  mounted = true;
  curId = ctx?.user?.prefs?.settings?.mascot && MASCOTS[ctx.user.prefs.settings.mascot] ? ctx.user.prefs.settings.mascot : DEFAULT_ID;
  want3d = ctx?.user?.prefs?.settings?.mascot3d !== false;
  mascotSound = ctx?.user?.prefs?.settings?.mascotSound === true;   // varsayılan kapalı
  // Otomatik oynatma engeli: ses motorunu ilk kullanıcı etkileşiminde aç/sürdür (hata fırlatmaz)
  const armAudio = () => { if (mascotSound) ensureAudio(); };
  window.addEventListener('pointerdown', armAudio, { passive: true });
  window.addEventListener('click', armAudio, { passive: true });

  const fig = h('div', { class: 'mascot-fig' }, figSvg(curId), h('span', { class: 'm-burst' }));
  const btn = h('button', { class: 'mascot', type: 'button', title: 'Asistana sor (sürükleyip taşıyabilirsin)', 'aria-label': 'Yapay zeka asistanı' },
    fig, h('span', { class: 'mascot-badge' }, svgIcon(icons.chat)));
  document.body.append(btn);
  _btn = btn;
  if (ctx?.user?.prefs?.settings?.mascotOff) btn.style.display = 'none';   // kullanıcı kapatmışsa gizli başla
  els = { fig, btn };

  // Kayıtlı konum (bu cihaz)
  applyPos(loadPos());
  if (can3d()) start3d();
  // 3D: gözler / baş imleci izler, üzerine gelince sevinir
  let lookRaf = 0;
  window.addEventListener('pointermove', e => {
    if (!ctl || lookRaf) return;
    lookRaf = requestAnimationFrame(() => { lookRaf = 0; ctl?.lookAt(e.clientX, e.clientY); });
  }, { passive: true });
  btn.addEventListener('pointerenter', () => ctl?.happy(true));
  btn.addEventListener('pointerleave', () => ctl?.happy(false));

  // Sürükle-taşı (tıklamadan ayırt et)
  let drag = null;
  btn.addEventListener('pointerdown', e => {
    if (e.button != null && e.button !== 0) return;
    const r = btn.getBoundingClientRect();
    drag = { dx: e.clientX - r.left, dy: e.clientY - r.top, x0: e.clientX, y0: e.clientY, moved: false };
    btn.setPointerCapture(e.pointerId);
  });
  btn.addEventListener('pointermove', e => {
    if (!drag) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 6) return;
    drag.moved = true; btn.classList.add('dragging');
    applyPos({ left: e.clientX - drag.dx, top: e.clientY - drag.dy });
  });
  const endDrag = e => {
    if (!drag) return;
    const moved = drag.moved; drag = null; btn.classList.remove('dragging');
    try { btn.releasePointerCapture(e.pointerId); } catch { /* */ }
    if (moved) { savePos(); } else { toggle(); }   // taşınmadıysa = tıklama
  };
  btn.addEventListener('pointerup', endDrag);
  btn.addEventListener('pointercancel', endDrag);
  // Pencere küçülürse maskot ekran dışında kalmasın
  window.addEventListener('resize', () => applyPos(loadPos()));

  // Sürekli hareket: sohbet kapalıyken rastgele numaralar
  const doTrick = () => {
    if (!panel.hidden || btn.classList.contains('dragging') || btn.style.display === 'none') return;
    if (Math.random() < 0.3) playMascotSound(curId);   // arada bir (~%30) maskota özgü ses (dron=vızıltı, kedi=miyav…)
    const list = MASCOTS[curId]?.tricks || TRICKS;   // maskota özel numaralar varsa onlardan seç, yoksa ortak liste
    const tr = list[Math.floor(Math.random() * list.length)];
    if (ctl) return ctl.play(tr);
    fig.classList.add(`trick-${tr}`);
    setTimeout(() => fig.classList.remove(`trick-${tr}`), 1700);
  };
  const scheduleTrick = () => setTimeout(() => { doTrick(); scheduleTrick(); }, 3200 + Math.random() * 4200);
  scheduleTrick();

  // ---- Sohbet penceresi ----
  const log = h('div', { class: 'mchat-log' });
  const input = h('textarea', { class: 'mchat-input', rows: 1, placeholder: 'Bir şey sor…' });
  const sendBtn = h('button', { class: 'mchat-send', type: 'button', title: 'Gönder' }, svgIcon(icons.send));
  const closeBtn = h('button', { class: 'mchat-x', type: 'button', title: 'Kapat', onclick: () => toggle(false) }, '✕');
  const headAva = h('span', { class: 'mchat-ava' }, mascotPreview(curId, can3d()));
  const headName = h('b', null, MASCOTS[curId].name);
  const panel = h('div', { class: 'mchat', hidden: true },
    h('div', { class: 'mchat-head' }, headAva, h('div', { class: 'grow' }, headName, h('small', null, 'Yapay zeka asistanı')), closeBtn),
    log, h('div', { class: 'mchat-bar' }, input, sendBtn));
  document.body.append(panel);
  _panel = panel;
  els.headAva = headAva; els.headName = headName;

  function bubble(role, text, cls = '') {
    const b = h('div', { class: `mchat-msg ${role} ${cls}` }, h('div', { class: 'mchat-bubble' }, text));
    log.append(b); log.scrollTop = log.scrollHeight;
    return b;
  }
  const greet = () => bubble('assistant', t('Merhaba! Ben {name} 👋 Sana nasıl yardımcı olabilirim?', { name: MASCOTS[curId].name }));
  if (!convo.length) greet(); else for (const m of convo) bubble(m.role, m.content);

  let busy = false;
  async function send() {
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = ''; autosize(); busy = true; sendBtn.disabled = true;
    convo.push({ role: 'user', content: text });
    bubble('user', text);
    const typing = bubble('assistant', '', 'typing');
    clear(typing.querySelector('.mchat-bubble'), h('span', { class: 'mchat-dots' }, h('i'), h('i'), h('i')));
    ctl?.setState('thinking');   // 3D: el çenede, yukarı bakar
    try {
      const d = await api.post('/api/assistant/chat', { messages: convo });
      typing.remove(); convo.push({ role: 'assistant', content: d.reply }); bubble('assistant', d.reply);
      ctl?.setState('idle'); ctl?.talk(String(d.reply || '').length * 0.04);   // cevabı "söyler"
    } catch (err) {
      typing.remove(); bubble('assistant', err?.message || 'Şu an cevap veremedim, birazdan tekrar dene.', 'err'); convo.pop();
      ctl?.setState('idle'); ctl?.play('wobble');
    } finally { busy = false; sendBtn.disabled = false; input.focus(); }
  }
  const autosize = () => { input.style.height = 'auto'; input.style.height = `${Math.min(96, input.scrollHeight)}px`; };
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  sendBtn.addEventListener('click', send);

  function positionPanel() {
    if (window.matchMedia('(max-width:820px)').matches) { panel.style.left = panel.style.top = panel.style.right = panel.style.bottom = ''; return; }
    const r = btn.getBoundingClientRect(), pw = Math.min(380, window.innerWidth - 32), ph = Math.min(560, window.innerHeight - 40);
    let left = Math.min(Math.max(12, r.right - pw), window.innerWidth - pw - 12);
    let top = r.top - ph - 12;
    if (top < 12) top = Math.min(r.bottom + 12, window.innerHeight - ph - 12);
    panel.style.left = `${left}px`; panel.style.top = `${top}px`; panel.style.right = 'auto'; panel.style.bottom = 'auto';
  }
  async function showDecisions() {
    try {
      const d = await api.get('/api/assistant/changes');
      if (!d.unseen?.length) return;
      for (const r of d.unseen) {
        const msg = r.status === 'ONAYLANDI' ? t('✅ İsteğin onaylandı ve uygulandı: “{summary}”{extra}', { summary: r.summary, extra: r.affected != null ? t(' ({n} kayıt)', { n: r.affected }) : '' })
          : r.status === 'RED' ? t('❌ İsteğin reddedildi: “{summary}”{note}', { summary: r.summary, note: r.note ? ` — ${r.note}` : '' })
          : t('⚠️ İsteğin onaylandı ama uygulanamadı: “{summary}”{note}', { summary: r.summary, note: r.note ? ` — ${r.note}` : '' });
        bubble('assistant', msg);
      }
      api.post('/api/assistant/changes/ack', {}).catch(() => {});
    } catch { /* */ }
  }
  function toggle(open) {
    const show = open ?? panel.hidden;
    if (show) positionPanel();
    panel.hidden = !show; btn.classList.toggle('open', show);
    ctl?.poke();
    if (show) ctl?.play('wave');
    if (show) { setTimeout(() => input.focus(), 50); showDecisions().then(() => { log.scrollTop = log.scrollHeight; }); }
  }
}

function loadPos() { try { return JSON.parse(localStorage.getItem(POS_KEY) || 'null'); } catch { return null; } }
function savePos() { try { const b = els.btn.getBoundingClientRect(); localStorage.setItem(POS_KEY, JSON.stringify({ left: b.left, top: b.top })); } catch { /* */ } }
function applyPos(p) {
  if (!els) return;
  const b = els.btn;
  if (!p || typeof p.left !== 'number') { b.style.left = b.style.top = b.style.right = b.style.bottom = ''; return; }
  const w = b.offsetWidth || 76, hh = b.offsetHeight || 84;
  const left = Math.min(Math.max(6, p.left), window.innerWidth - w - 6);
  const top = Math.min(Math.max(6, p.top), window.innerHeight - hh - 6);
  b.style.left = `${left}px`; b.style.top = `${top}px`; b.style.right = 'auto'; b.style.bottom = 'auto';
}
