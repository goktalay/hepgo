// Sesle yazdırma (dikte): uygulamadaki her çok satırlı metin kutusuna (textarea.input) mikrofon düğmesi eklenir.
// Düğmeye basınca kayıt başlar, yeniden basınca durur; kayıt bu sunucudaki Whisper ile metne çevrilip imlecin
// bulunduğu yere yazılır. Ses sunucuda saklanmaz. Bir kutuda istenmiyorsa: data-no-mic.
import { api } from './api.js';
import { icons } from './icons.js';
import { getLang } from './i18n.js';
import { h, svgIcon, toast, toastError } from './ui.js';

// Sesten yazıya dili arayüz diliyle aynı (Whisper dil kodları birebir). Desteklenmeyen dilde otomatik algıla.
const STT_LANGS = ['tr', 'en', 'de', 'fr', 'es', 'ar', 'ru'];
const sttLang = () => (STT_LANGS.includes(getLang()) ? getLang() : 'auto');

const MAX_SECONDS = 300;   // tek kayıt en çok 5 dakika
let active = null;         // aynı anda tek kayıt

function pickType() {
  const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
  return types.find(t => window.MediaRecorder?.isTypeSupported?.(t)) || '';
}
const extOf = type => (type.includes('webm') ? '.webm' : type.includes('ogg') ? '.ogg' : type.includes('mp4') ? '.m4a' : '.webm');

function insertText(ta, text) {
  const start = ta.selectionStart ?? ta.value.length;
  const end = ta.selectionEnd ?? ta.value.length;
  const before = ta.value.slice(0, start);
  const after = ta.value.slice(end);
  const lead = before && !/\s$/.test(before) ? ' ' : '';
  const trail = after && !/^\s/.test(after) ? ' ' : '';
  ta.value = before + lead + text + trail + after;
  const pos = (before + lead + text).length;
  ta.focus();
  ta.setSelectionRange(pos, pos);
  ta.dispatchEvent(new Event('input', { bubbles: true }));
}

function attach(ta) {
  if (ta.dataset.mic || ta.hasAttribute('data-no-mic') || ta.disabled || ta.readOnly) return;
  ta.dataset.mic = '1';
  const btn = h('button', { type: 'button', class: 'dict-btn', title: 'Sesle yazdır (konuşun, tekrar basınca metne çevrilir)',
    'aria-label': 'Sesle yazdır' }, svgIcon(icons.mic));
  const timer = h('span', { class: 'dict-time', hidden: true });
  const wrap = h('div', { class: 'dict-wrap' });
  ta.replaceWith(wrap);
  wrap.append(ta, btn, timer);
  ta.classList.add('has-mic');

  let rec = null, stream = null, chunks = [], started = 0, tick = null;
  const setState = state => {
    btn.className = `dict-btn ${state}`;
    btn.disabled = state === 'busy';
    btn.replaceChildren(state === 'busy' ? h('span', { class: 'dict-spin' }) : svgIcon(icons.mic));
    btn.title = state === 'rec' ? 'Kaydı bitir ve metne çevir' : state === 'busy' ? 'Metne çevriliyor…' : 'Sesle yazdır';
    timer.hidden = state !== 'rec';
  };
  const stop = () => { if (rec && rec.state === 'recording') rec.stop(); };
  const start = async () => {
    if (active && active !== stop) active();   // başka kutudaki kaydı bitir
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      toastError(new Error(window.isSecureContext ? 'Bu tarayıcı ses kaydını desteklemiyor'
        : 'Mikrofon yalnızca güvenli bağlantıda çalışır: sistemi https:// adresinden açın'));
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      toastError(new Error('Mikrofon izni verilmedi'));
      return;
    }
    const type = pickType();
    rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = [];
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      clearInterval(tick);
      stream.getTracks().forEach(t => t.stop());
      if (active === stop) active = null;
      const blob = new Blob(chunks, { type: rec.mimeType || type || 'audio/webm' });
      if (Date.now() - started < 700 || blob.size < 1000) { setState('idle'); return; }   // yanlışlıkla basma
      setState('busy');
      try {
        const form = new FormData();
        form.append('file', blob, `dikte${extOf(blob.type)}`);
        form.append('lang', sttLang());   // arayüz diline göre konuşma tanıma
        const r = await api.post('/api/system/dictate', form);
        if (r.text?.trim()) insertText(ta, r.text.trim());
        else toast('Konuşma anlaşılamadı; biraz daha yüksek sesle tekrar deneyin');
      } catch (err) {
        toastError(err);
      } finally {
        setState('idle');
      }
    };
    rec.start(1000);
    started = Date.now();
    active = stop;
    setState('rec');
    timer.textContent = '0:00';
    tick = setInterval(() => {
      const s = Math.floor((Date.now() - started) / 1000);
      timer.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
      if (s >= MAX_SECONDS) stop();
    }, 500);
  };
  btn.addEventListener('click', () => (rec && rec.state === 'recording' ? stop() : start()));
  setState('idle');
}

export function enableDictation(root = document.body) {
  const scan = node => {
    if (node.nodeType !== 1) return;
    if (node.matches('textarea.input')) attach(node);
    node.querySelectorAll?.('textarea.input').forEach(attach);
  };
  scan(root);
  new MutationObserver(list => list.forEach(m => m.addedNodes.forEach(scan))).observe(root, { childList: true, subtree: true });
  // sayfa değişince süren kayıt biter
  window.addEventListener('hashchange', () => { if (active) active(); });
}
