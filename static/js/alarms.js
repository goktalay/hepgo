// Alarmlar (cihazda saklanır): belirli saat + haftanın günleri; saat gelince alarm sesiyle uyarır. Global denetleyici
// pano açık olmasa da çalışır (app.js başlangıcında initAlarms). Ses WebAudio ile üretilir (dosya gerekmez).
import { h, modal, field, toast } from './ui.js';

const KEY = 'caymaz.alarms';
export const DAYS = [['1', 'Pzt'], ['2', 'Sal'], ['3', 'Çar'], ['4', 'Per'], ['5', 'Cum'], ['6', 'Cmt'], ['0', 'Paz']];
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

export function getAlarms() { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; } }
export function saveAlarms(a) { try { localStorage.setItem(KEY, JSON.stringify(a)); } catch { /* */ } window.dispatchEvent(new CustomEvent('caymaz:alarms-changed')); }

const fired = new Set();   // `${id}:${YYYY-MM-DDTHH:MM}` bir dakikada bir kez
let audioCtx = null, timer = null, ringing = null;

function beep() {
  try {
    audioCtx ||= new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.type = 'sine'; o.frequency.value = 880; g.gain.value = 0.0001; o.connect(g); g.connect(audioCtx.destination);
    const t = audioCtx.currentTime;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.5);
    o.start(t); o.stop(t + 0.5);
  } catch { /* ses açılamadı */ }
}

function ring(alarm) {
  if (ringing) return;
  beep();
  const iv = setInterval(beep, 900);
  const stop = () => { clearInterval(iv); ringing = null; };
  ringing = { stop };
  modal({
    title: '⏰ Alarm',
    body: h('div', { style: { textAlign: 'center', padding: '8px 0' } },
      h('div', { style: { fontSize: '40px', fontWeight: '800' } }, alarm.time),
      alarm.label ? h('div', { class: 'muted', style: { marginTop: '6px' } }, alarm.label) : null),
    actions: [{ label: 'Kapat', class: 'primary', onClick: stop }],
    onClose: stop,
  });
}

function check() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
  const day = String(now.getDay());   // 0=Paz
  const stamp = now.toISOString().slice(0, 16);
  for (const a of getAlarms()) {
    if (!a.enabled) continue;
    const days = a.days && a.days.length ? a.days : [day];   // gün seçilmediyse her gün
    if (!days.includes(day) || a.time !== hh) continue;
    const key = `${a.id}:${stamp}`;
    if (fired.has(key)) continue;
    fired.add(key);
    if (fired.size > 200) fired.clear();
    ring(a);
  }
}

export function initAlarms() {
  if (timer) return;
  // kullanıcı ilk tıklamasında ses bağlamını hazırla (otomatik oynatma engeli)
  const unlock = () => { try { audioCtx ||= new (window.AudioContext || window.webkitAudioContext)(); audioCtx.resume(); } catch { /* */ } };
  window.addEventListener('pointerdown', unlock, { once: true });
  check();
  timer = setInterval(check, 15000);
}

// Alarm ekle/düzenle penceresi
export function alarmForm(existing, done) {
  const a = existing || { id: uid(), time: '08:00', days: ['1', '2', '3', '4', '5'], label: '', enabled: true };
  const time = h('input', { class: 'input', type: 'time', value: a.time, step: 60, style: { width: '140px' } });
  const label = h('input', { class: 'input', value: a.label || '', placeholder: 'Etiket (isteğe bağlı)' });
  const sel = new Set(a.days || []);
  const dayBtns = DAYS.map(([d, l]) => { const b = h('button', { type: 'button', class: `alarm-day ${sel.has(d) ? 'on' : ''}` }, l);
    b.addEventListener('click', () => { sel.has(d) ? sel.delete(d) : sel.add(d); b.classList.toggle('on'); }); return b; });
  modal({
    title: existing ? 'Alarmı düzenle' : 'Yeni alarm',
    body: h('div', null, field('Saat', time), field('Günler', h('div', { class: 'alarm-days' }, dayBtns)),
      h('div', { class: 'small muted', style: { margin: '-6px 0 10px' } }, 'Gün seçmezseniz her gün çalar.'), field('Etiket', label)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: () => {
      a.time = time.value || '08:00'; a.days = [...sel]; a.label = label.value.trim().slice(0, 80); a.enabled = a.enabled !== false;
      const all = getAlarms().filter(x => x.id !== a.id); all.push(a); saveAlarms(all);
      toast('Alarm kaydedildi'); done?.();
    } }],
  });
}
