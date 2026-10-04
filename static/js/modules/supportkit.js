// Destek ortak arayüz parçaları — Merkez › Destek Merkezi ve firma › Üyeliğim & Destek aynı bileşenleri kullanır:
// durum / öncelik / kategori rozetleri, yazışma (dosya ekleri, iç notlar), dosya eklenebilen yanıt kutusu (sürükle-bırak,
// panodan ekran görüntüsü yapıştırma, hazır yanıt), SLA etiketi, yıldızlı değerlendirme, canlı sohbet balonları.
import { clear, fmtDateTime, h, t, toastError } from '../ui.js';

export const STATUS = { acik: ['blue', 'Açık'], yanit_bekliyor: ['yellow', 'Yanıt bekliyor'], cozuldu: ['green', 'Çözüldü'], kapali: ['', 'Kapalı'] };
export const STATUS_FIRM = { acik: ['blue', 'Destek inceliyor'], yanit_bekliyor: ['yellow', 'Yanıtınız bekleniyor'], cozuldu: ['green', 'Çözüldü'], kapali: ['', 'Kapalı'] };
export const PRIORITY = { dusuk: ['', 'Düşük'], normal: ['blue', 'Normal'], yuksek: ['yellow', 'Yüksek'], acil: ['red', 'Acil'] };
export const CATEGORY = { teknik: 'Teknik', fatura: 'Fatura / ödeme', oneri: 'Öneri / istek', egitim: 'Eğitim', diger: 'Diğer' };
export const PRESENCE = { online: ['#16a34a', 'Müsait'], busy: ['#d97706', 'Meşgul'], away: ['#64748b', 'Molada'], offline: ['#94a3b8', 'Çevrimdışı'] };
export const badge = (map, k) => { const [c, l] = map[k] || ['', k]; return h('span', { class: `badge ${c}` }, l); };
export const presenceDot = p => h('span', { class: 'dm-dot', style: `--c:${(PRESENCE[p] || PRESENCE.offline)[0]}`, title: (PRESENCE[p] || PRESENCE.offline)[1] });

const size = b => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const ago = iso => {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return 'şimdi';
  if (m < 60) return t('{n} dk', { n: m });
  if (m < 1440) return t('{h} sa {m} dk', { h: Math.floor(m / 60), m: m % 60 });
  return t('{d} gün', { d: Math.floor(m / 1440) });
};
export const waitFor = iso => ago(iso);

// Dosya eki: resimler küçük önizleme, diğerleri çip
export function fileChip(f, urlOf) {
  const url = urlOf(f.token);
  if ((f.mime || '').startsWith('image/')) {
    return h('a', { class: 'sk-img', href: url, target: '_blank', rel: 'noopener', title: f.name }, h('img', { src: url, alt: f.name, loading: 'lazy' }));
  }
  return h('a', { class: 'sk-file', href: url, target: '_blank', rel: 'noopener' }, h('span', { class: 'sk-file-i' }, (f.name.split('.').pop() || '').slice(0, 4).toUpperCase()),
    h('span', { class: 'sk-file-t' }, h('b', null, f.name), h('small', null, size(f.size))));
}

// Talep yazışması: "mine" tarafı sağda (merkezde support, firmada company); iç notlar (yalnız merkez) sarı
export function threadView(messages, mine, urlOf) {
  return h('div', { class: 'tk-thread' }, messages.map(m => {
    if (m.author_kind === 'system') return h('div', { class: 'tk-sys' }, `${m.body} · ${fmtDateTime(m.created_at)}`);
    const note = m.author_kind === 'note';
    return h('div', { class: `tk-msg ${m.author_kind === mine || note ? 'mine' : ''} ${note ? 'note' : ''}` },
      h('div', { class: 'tk-bubble' },
        h('div', { class: 'tk-who' }, m.author_name || (m.author_kind === 'support' ? 'Destek' : 'Firma'),
          m.author_kind === 'support' ? h('span', { class: 'tk-tag' }, 'Destek') : null, note ? h('span', { class: 'tk-tag note' }, '🔒 İç not') : null),
        m.body ? h('div', { class: 'tk-body' }, m.body) : null,
        m.files?.length && urlOf ? h('div', { class: 'sk-files' }, m.files.map(f => fileChip(f, urlOf))) : null),
      h('small', { class: 'muted' }, fmtDateTime(m.created_at)));
  }));
}

// Yanıt kutusu: metin + dosyalar (seç / sürükle / panodan yapıştır). opts.note → "Yanıt / İç not" seçimi; opts.canned → hazır yanıt listesi
// opts.extra → gönderme düğmesinin yanına ek eylem (ör. "Gönder ve çözüldü yap"). onSend({ body, files, internal, extra })
export function composer(onSend, opts = {}) {
  const ta = h('textarea', { class: 'input tk-input', rows: opts.rows || 3, placeholder: opts.placeholder || 'Yanıtınızı yazın…' });
  const files = [];
  const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
  const chips = h('div', { class: 'sk-pending' });
  const drawChips = () => clear(chips, files.map((f, i) => h('span', { class: 'sk-chip' }, '📎 ', f.name, h('small', null, ` ${size(f.size)}`),
    h('button', { type: 'button', title: 'Kaldır', onclick: () => { files.splice(i, 1); drawChips(); } }, '×'))));
  const add = list => { for (const f of list) if (files.length < 5) files.push(f); drawChips(); };
  fileIn.addEventListener('change', () => { add(fileIn.files); fileIn.value = ''; });
  ta.addEventListener('paste', e => {
    const imgs = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
    if (imgs.length) { e.preventDefault(); add(imgs.map((f, i) => new File([f], `ekran-goruntusu-${Date.now()}${i ? `-${i}` : ''}.png`, { type: f.type }))); }
  });
  let internal = false;
  const modeSeg = opts.note ? h('div', { class: 'seg sk-mode' },
    ...[['reply', 'Firmaya yanıt'], ['note', '🔒 İç not']].map(([k, l]) => h('button', { type: 'button', class: k === 'reply' ? 'on' : '', onclick: e => {
      internal = k === 'note'; [...e.currentTarget.parentElement.children].forEach(b => b.classList.toggle('on', b === e.currentTarget));
      box.classList.toggle('note', internal); ta.placeholder = internal ? 'Yalnızca destek ekibinin göreceği not…' : (opts.placeholder || 'Yanıtınızı yazın…');
    } }, l))) : null;
  const cannedSel = opts.canned?.length ? h('select', { class: 'input sk-canned', title: 'Hazır yanıt ekle', onchange: e => {
    const c = opts.canned.find(x => String(x.id) === e.target.value);
    if (c) { ta.value = ta.value ? `${ta.value}\n${c.body}` : c.body; ta.focus(); }
    e.target.value = '';
  } }, h('option', { value: '' }, '⚡ Hazır yanıt…'), opts.canned.map(c => h('option', { value: c.id }, c.shortcut ? `/${c.shortcut} · ${c.title}` : c.title))) : null;
  if (opts.canned?.length) {   // "/kısayol" + boşluk → hazır yanıt metni
    ta.addEventListener('keyup', e => {
      if (e.key !== ' ') return;
      const m = ta.value.match(/(^|\s)\/([\wğüşıöç-]+) $/);
      const c = m && opts.canned.find(x => x.shortcut === m[2]);
      if (c) ta.value = ta.value.slice(0, ta.value.length - m[2].length - 2) + c.body;
    });
  }
  const btn = h('button', { class: 'btn primary', type: 'button' }, opts.sendLabel || 'Gönder');
  let busy = false;
  const send = async extra => {
    const v = ta.value.trim();
    if ((!v && !files.length) || busy) return;
    busy = true; btn.disabled = true;
    try { await onSend({ body: v, files: [...files], internal, extra }); ta.value = ''; files.length = 0; drawChips(); }
    catch (e) { toastError(e); } finally { busy = false; btn.disabled = false; }
  };
  btn.addEventListener('click', () => send(null));
  ta.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (opts.enterSends ? !e.shiftKey : (e.ctrlKey || e.metaKey))) { e.preventDefault(); send(null); }
    else opts.onTyping?.();
  });
  const box = h('div', { class: 'tk-compose sk-compose' }, modeSeg, ta, chips,
    h('div', { class: 'tk-compose-bar' },
      h('button', { class: 'btn sm ghost', type: 'button', title: 'Dosya ekle (ekran görüntüsünü yapıştırabilirsiniz)', onclick: () => fileIn.click() }, '📎 Dosya'), fileIn,
      cannedSel,
      h('small', { class: 'muted grow' }, opts.enterSends ? 'Enter gönderir · Shift+Enter yeni satır' : 'Ctrl+Enter ile gönder · ekran görüntüsünü yapıştırabilirsiniz'),
      opts.extra ? h('button', { class: 'btn', type: 'button', onclick: () => send(opts.extra.key) }, opts.extra.label) : null,
      btn));
  box.addEventListener('dragover', e => { e.preventDefault(); box.classList.add('drop'); });
  box.addEventListener('dragleave', () => box.classList.remove('drop'));
  box.addEventListener('drop', e => { e.preventDefault(); box.classList.remove('drop'); add(e.dataTransfer.files); });
  box.focus = () => ta.focus();
  box.getText = () => ta.value;
  box.getFiles = () => [...files];
  if (opts.noSend) { btn.hidden = true; box.querySelector('.tk-compose-bar small').textContent = 'Dosya ekleyebilir, ekran görüntüsünü yapıştırabilir ya da sürükleyebilirsiniz'; }
  return box;
}

export function formData(fields, files = []) {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => { if (v !== undefined && v !== null) fd.append(k, v); });
  files.forEach(f => fd.append('files', f));
  return fd;
}

// SLA etiketi: ilk yanıt / çözüm hedefi — kalan süre ya da aşım
export function slaChip(tk) {
  if (!tk.sla) return null;
  const now = Date.now();
  if (tk.sla.first === 'due' || tk.sla.first === 'late') {
    const d = (new Date(tk.due_at).getTime() - now) / 60000;
    return h('span', { class: `sk-sla ${d < 0 ? 'late' : d < 60 ? 'soon' : ''}`, title: `İlk yanıt hedefi: ${fmtDateTime(tk.due_at)}` },
      d < 0 ? `⏱ İlk yanıt ${fmtM(-d)} gecikti` : `⏱ İlk yanıt: ${fmtM(d)}`);
  }
  if (tk.sla.resolve === 'due' || tk.sla.resolve === 'late') {
    const d = (new Date(tk.resolve_due_at).getTime() - now) / 60000;
    return h('span', { class: `sk-sla ${d < 0 ? 'late' : d < 120 ? 'soon' : 'ok'}`, title: `Çözüm hedefi: ${fmtDateTime(tk.resolve_due_at)}` },
      d < 0 ? `Çözüm ${fmtM(-d)} gecikti` : `Çözüm: ${fmtM(d)}`);
  }
  return null;
}
export const fmtM = min => (min < 60 ? t('{n} dk', { n: Math.round(min) }) : min < 1440 ? t('{h} sa {m} dk', { h: Math.floor(min / 60), m: Math.round(min % 60) })
  : t('{d} gün {h} sa', { d: Math.floor(min / 1440), h: Math.floor((min % 1440) / 60) }));

// Yıldızlı değerlendirme (1-5) + isteğe bağlı yorum
export function ratingBox(title, onRate) {
  let val = 0;
  const stars = h('div', { class: 'sk-stars' });
  const note = h('input', { class: 'input', placeholder: 'Yorumunuz (isteğe bağlı)', maxlength: 500 });
  const btn = h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Gönder');
  const draw = () => clear(stars, [1, 2, 3, 4, 5].map(n => h('button', { type: 'button', class: n <= val ? 'on' : '', title: `${n}/5`,
    onclick: () => { val = n; btn.disabled = false; draw(); } }, '★')));
  draw();
  btn.addEventListener('click', async () => { btn.disabled = true; try { await onRate(val, note.value.trim()); } catch (e) { toastError(e); btn.disabled = false; } });
  return h('div', { class: 'sk-rate' }, h('b', null, title), stars, h('div', { class: 'sk-rate-row' }, note, btn));
}
export const starsOf = n => (n ? h('span', { class: 'sk-stars-ro', title: `${n}/5` }, '★'.repeat(n), h('i', null, '★'.repeat(5 - n))) : null);

// Canlı sohbet balonları (mine: 'support' | 'company')
export function chatMessage(m, mine, urlOf) {
  if (m.author_kind === 'system') return h('div', { class: 'lc-sys' }, m.body);
  const own = m.author_kind === mine;
  let body;
  if (m.kind === 'file' && m.file) body = fileChip(m.file, urlOf);
  else if (m.kind === 'screen') {
    body = h('div', { class: 'lc-screen' }, h('b', null, '🖥️ Ekran paylaşımı'),
      h('small', null, own ? 'Ekranınızı paylaştınız; destek uzmanı bağlantıdan izleyip yol gösterebilir.' : 'Firma ekranını paylaştı.'),
      own ? null : h('a', { class: 'btn sm primary', href: m.body, target: '_blank', rel: 'noopener' }, 'Ekranı izle →'));
  } else body = h('div', { class: 'lc-text' }, m.body);
  return h('div', { class: `lc-msg ${own ? 'mine' : ''}` },
    own ? null : h('div', { class: 'lc-who' }, m.author_name),
    h('div', { class: 'lc-bubble' }, body),
    h('small', { class: 'lc-time' }, (m.created_at || '').slice(11, 16)));
}
