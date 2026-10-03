// Köşedeki yapay zeka maskotu: sürekli farklı animasyonlar yapar (el sallama, zıplama, kafa şişip patlama…);
// tıklanınca Claude API sohbet penceresi açılır. Sürüklenip taşınabilir (yeri cihazda saklanır) ve orada oynamaya
// devam eder. Karakter Kişisel Ayarlar → Maskot'tan seçilir (kullanıcıya kayıtlı). Anahtar tanımlı değilse gösterilmez.
import { api } from '../api.js';
import { h, clear, svgIcon, t } from '../ui.js';
import { icons } from '../icons.js';

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
};

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

const TRICKS = ['wave', 'jump', 'wobble', 'spin', 'pop', 'dance', 'peek'];
const POS_KEY = 'caymaz.mascotPos';

let mounted = false;
let convo = [];        // {role, content}
let curId = DEFAULT_ID;
let els = null;        // { fig, btn }

// Kişisel ayarlardan canlı karakter değişimi (maskot + sohbet başlığı/avatarı)
export function setMascot(id) {
  curId = MASCOTS[id] ? id : DEFAULT_ID;
  if (!els) return;
  clear(els.fig, [figSvg(curId), h('span', { class: 'm-burst' })]);
  if (els.headAva) clear(els.headAva, figSvg(curId));
  if (els.headName) els.headName.textContent = MASCOTS[curId].name;
}

export async function mountMascot(ctx) {
  if (mounted) return;
  let status;
  try { status = await api.get('/api/assistant/status'); } catch { return; }
  if (!status?.enabled) return;
  mounted = true;
  curId = ctx?.user?.prefs?.settings?.mascot && MASCOTS[ctx.user.prefs.settings.mascot] ? ctx.user.prefs.settings.mascot : DEFAULT_ID;

  const fig = h('div', { class: 'mascot-fig' }, figSvg(curId), h('span', { class: 'm-burst' }));
  const btn = h('button', { class: 'mascot', type: 'button', title: 'Asistana sor (sürükleyip taşıyabilirsin)', 'aria-label': 'Yapay zeka asistanı' },
    fig, h('span', { class: 'mascot-badge' }, svgIcon(icons.chat)));
  document.body.append(btn);
  els = { fig, btn };

  // Kayıtlı konum (bu cihaz)
  applyPos(loadPos());

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
    if (!panel.hidden || btn.classList.contains('dragging')) return;
    const t = TRICKS[Math.floor(Math.random() * TRICKS.length)];
    fig.classList.add(`trick-${t}`);
    setTimeout(() => fig.classList.remove(`trick-${t}`), 1700);
  };
  const scheduleTrick = () => setTimeout(() => { doTrick(); scheduleTrick(); }, 3200 + Math.random() * 4200);
  scheduleTrick();

  // ---- Sohbet penceresi ----
  const log = h('div', { class: 'mchat-log' });
  const input = h('textarea', { class: 'mchat-input', rows: 1, placeholder: 'Bir şey sor…' });
  const sendBtn = h('button', { class: 'mchat-send', type: 'button', title: 'Gönder' }, svgIcon(icons.send));
  const closeBtn = h('button', { class: 'mchat-x', type: 'button', title: 'Kapat', onclick: () => toggle(false) }, '✕');
  const headAva = h('span', { class: 'mchat-ava' }, figSvg(curId));
  const headName = h('b', null, MASCOTS[curId].name);
  const panel = h('div', { class: 'mchat', hidden: true },
    h('div', { class: 'mchat-head' }, headAva, h('div', { class: 'grow' }, headName, h('small', null, 'Yapay zeka asistanı')), closeBtn),
    log, h('div', { class: 'mchat-bar' }, input, sendBtn));
  document.body.append(panel);
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
    try {
      const d = await api.post('/api/assistant/chat', { messages: convo });
      typing.remove(); convo.push({ role: 'assistant', content: d.reply }); bubble('assistant', d.reply);
    } catch (err) {
      typing.remove(); bubble('assistant', err?.message || 'Şu an cevap veremedim, birazdan tekrar dene.', 'err'); convo.pop();
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
