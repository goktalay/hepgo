// Araçlar › Notepad Master (web): çok sekmeli metin editörü — satır numaraları, basit sözdizimi vurgusu (json/py/js/sql),
// otomatik kayıt (localStorage), sunucuya kaydet/aç (kullanıcı başına data/tools/notes/<uid>/), bul/değiştir. Ağır bağımlılık yok.
import { api } from '../api.js';
import { clear, confirmDialog, h, modal, onLeave, pageHead, toast, toastError } from '../ui.js';
import { btn, downloadText, fmtBytes, inp, sel, setStatus, shell, status } from './tool_mt.js';

const LS = 'mt.notepad.docs';
const LANGS = [['plain', 'Düz metin'], ['json', 'JSON'], ['py', 'Python'], ['js', 'JavaScript'], ['sql', 'SQL']];
const EXT = { json: 'json', py: 'py', js: 'js', mjs: 'js', sql: 'sql', txt: 'plain', md: 'plain' };
const KW = {
  py: 'def|class|return|if|elif|else|for|while|import|from|as|with|try|except|finally|raise|lambda|yield|pass|break|continue|and|or|not|in|is|None|True|False|async|await|global|nonlocal|del|assert',
  js: 'const|let|var|function|return|if|else|for|while|do|switch|case|break|continue|new|class|extends|import|export|from|default|try|catch|finally|throw|async|await|typeof|instanceof|in|of|null|undefined|true|false|this|yield|delete|void',
  sql: 'SELECT|FROM|WHERE|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|DROP|ALTER|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|AS|AND|OR|NOT|NULL|IS|IN|LIKE|BETWEEN|DISTINCT|COUNT|SUM|AVG|MIN|MAX|UNION|ALL|PRIMARY|KEY|INDEX|VIEW|IF|EXISTS|CASE|WHEN|THEN|ELSE|END|DESC|ASC|WITH|PRAGMA|BEGIN|COMMIT|ROLLBACK',
};
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// Basit vurgu: yorum, dizge, sayı, anahtar sözcük (sıra önemli; tek regex ile parçala)
function highlight(src, lang) {
  if (lang === 'plain' || !src) return esc(src);
  const kw = KW[lang];
  const parts = [
    lang === 'py' ? '(#[^\\n]*)' : lang === 'sql' ? '(--[^\\n]*|/\\*[\\s\\S]*?\\*/)' : lang === 'js' ? '(//[^\\n]*|/\\*[\\s\\S]*?\\*/)' : '(\\0)',
    '("(?:[^"\\\\\\n]|\\\\.)*"|\'(?:[^\'\\\\\\n]|\\\\.)*\'|`(?:[^`\\\\]|\\\\.)*`)',
    '(\\b-?\\d+(?:\\.\\d+)?(?:e[+-]?\\d+)?\\b)',
    kw ? `(\\b(?:${kw})\\b)` : '(\\0)',
  ];
  const re = new RegExp(parts.join('|'), lang === 'sql' ? 'gi' : 'g');
  let out = '', last = 0, m;
  while ((m = re.exec(src))) {
    out += esc(src.slice(last, m.index));
    const cls = m[1] != null ? 'c' : m[2] != null ? 's' : m[3] != null ? 'n' : 'k';
    if (lang === 'json' && cls === 's' && /^\s*:/.test(src.slice(re.lastIndex, re.lastIndex + 3))) out += `<span class="p">${esc(m[0])}</span>`;
    else out += `<span class="${cls}">${esc(m[0])}</span>`;
    last = re.lastIndex;
  }
  return out + esc(src.slice(last));
}

export async function render(view, params, ctx) {
  const st = status('');
  let docs = load(), cur = null, saveT = null;
  const uid = ctx.user.id;

  const tabs = h('div', { class: 'mt-tabs' });
  const gutter = h('div', { class: 'mt-gutter' }, '1');
  const pre = h('pre');
  const ta = h('textarea', { spellcheck: false, wrap: 'off' });
  const ed = h('div', { class: 'mt-editor' }, gutter, h('div', { class: 'mt-code' }, pre, ta));
  const langSel = sel(LANGS, 'plain');
  const pos = h('span', { class: 'mt-status' });

  // Bul / değiştir
  const findIn = inp({ cls: 'w-m', placeholder: 'Bul' });
  const replIn = inp({ cls: 'w-m', placeholder: 'Değiştir' });
  const findBar = h('div', { class: 'mt-bar', style: { display: 'none' } }, findIn, replIn,
    btn('Sonraki', { cls: 'sm', onclick: () => findNext() }), btn('Değiştir', { cls: 'sm', onclick: () => replaceOne() }), btn('Tümünü değiştir', { cls: 'sm', onclick: () => replaceAll() }),
    btn('Kapat', { cls: 'sm', onclick: () => { findBar.style.display = 'none'; ta.focus(); } }));
  findIn.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); findNext(); } });

  const toolbar = h('div', { class: 'mt-bar' },
    btn('Yeni', { cls: 'primary', onclick: () => newDoc() }),
    btn('Sunucudan aç', { onclick: () => openRemote() }),
    btn('Sunucuya kaydet', { onclick: () => saveRemote() }),
    btn('İndir', { onclick: () => cur && downloadText(cur.content, cur.name) }),
    btn('Bul/Değiştir', { onclick: () => { findBar.style.display = ''; findIn.focus(); } }),
    btn('Yerel dosya aç…', { onclick: () => localIn.click() }),
    h('span', { class: 'mt-bar right' }, langSel, pos));
  const localIn = h('input', { type: 'file', multiple: true, style: { display: 'none' }, onchange: async () => {
    for (const f of localIn.files) newDoc(f.name, await f.text());
    localIn.value = '';
  } });

  function load() {
    try { const d = JSON.parse(localStorage.getItem(LS) || '[]'); return Array.isArray(d) && d.length ? d : [mk('not1.txt', '')]; } catch { return [mk('not1.txt', '')]; }
  }
  function mk(name, content) { return { id: Date.now() + Math.random().toString(36).slice(2, 7), name, content, lang: EXT[name.split('.').pop().toLowerCase()] || 'plain', dirty: false }; }
  function persist() { try { localStorage.setItem(LS, JSON.stringify(docs.map(d => ({ ...d })))); } catch { /* */ } }
  function newDoc(name, content = '') {
    const n = name || `not${docs.length + 1}.txt`;
    const d = mk(n, content); docs.push(d); open(d); persist();
  }
  function open(d) {
    cur = d; ta.value = d.content; langSel.value = d.lang; drawTabs(); paint(); updPos();
    setStatus(st, d.remote ? `Sunucu: ${d.name}` : 'Yerel (otomatik kayıt)', d.remote ? 'ok' : '');
    ta.focus();
  }
  async function close(d) {
    if (d.dirty && d.remote && !await confirmDialog('Kaydedilmedi', `${d.name} sunucuya kaydedilmemiş değişiklik içeriyor. Kapatılsın mı?`, { okLabel: 'Kapat', danger: true })) return;
    const i = docs.indexOf(d); docs.splice(i, 1);
    if (!docs.length) docs.push(mk('not1.txt', ''));
    if (cur === d) open(docs[Math.max(0, i - 1)]); else drawTabs();
    persist();
  }
  function drawTabs() {
    clear(tabs, docs.map(d => h('button', { class: `mt-tab ${d === cur ? 'on' : ''}`, type: 'button', onclick: () => open(d), ondblclick: () => renameDoc(d) },
      d.name + (d.dirty ? ' •' : ''), h('span', { class: 'x', onclick: e => { e.stopPropagation(); close(d); } }, '×'))),
    h('button', { class: 'mt-tab', type: 'button', onclick: () => newDoc(), title: 'Yeni sekme' }, '+'));
  }
  function renameDoc(d) {
    const n = prompt('Dosya adı', d.name);
    if (n && n !== d.name) { d.name = n.replace(/[\\/]/g, '_').slice(0, 120); d.lang = EXT[n.split('.').pop().toLowerCase()] || d.lang; d.dirty = true; open(d); persist(); }
  }
  function paint() {
    const lines = ta.value.split('\n').length;
    gutter.textContent = Array.from({ length: lines }, (_, i) => i + 1).join('\n');
    pre.innerHTML = highlight(ta.value, cur.lang) + '\n';
    sync();
  }
  function sync() { pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft; gutter.scrollTop = ta.scrollTop; }
  function updPos() {
    const before = ta.value.slice(0, ta.selectionStart);
    const line = before.split('\n').length, col = before.length - before.lastIndexOf('\n');
    pos.textContent = `Satır ${line}, Sütun ${col} · ${ta.value.length} karakter`;
  }
  ta.addEventListener('input', () => {
    cur.content = ta.value; cur.dirty = true; paint(); updPos(); drawTabs();
    clearTimeout(saveT); saveT = setTimeout(persist, 400);
  });
  ta.addEventListener('scroll', sync);
  ta.addEventListener('keyup', updPos); ta.addEventListener('click', updPos);
  ta.addEventListener('keydown', e => {
    if (e.key === 'Tab') { e.preventDefault(); const s = ta.selectionStart; ta.setRangeText('    ', s, ta.selectionEnd, 'end'); ta.dispatchEvent(new Event('input')); }
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveRemote(); }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'f' || e.key === 'h')) { e.preventDefault(); findBar.style.display = ''; findIn.focus(); }
  });
  langSel.addEventListener('change', () => { cur.lang = langSel.value; paint(); persist(); });

  function findNext() {
    const q = findIn.value; if (!q) return;
    const from = ta.selectionEnd, i = ta.value.indexOf(q, from) >= 0 ? ta.value.indexOf(q, from) : ta.value.indexOf(q);
    if (i < 0) return toast('Bulunamadı');
    ta.focus(); ta.setSelectionRange(i, i + q.length);
    const line = ta.value.slice(0, i).split('\n').length; ta.scrollTop = Math.max(0, (line - 5) * 19.5); sync(); updPos();
  }
  function replaceOne() {
    const q = findIn.value; if (!q) return;
    if (ta.value.slice(ta.selectionStart, ta.selectionEnd) === q) { ta.setRangeText(replIn.value, ta.selectionStart, ta.selectionEnd, 'end'); ta.dispatchEvent(new Event('input')); }
    findNext();
  }
  function replaceAll() {
    const q = findIn.value; if (!q) return;
    const n = ta.value.split(q).length - 1;
    ta.value = ta.value.split(q).join(replIn.value); ta.dispatchEvent(new Event('input')); toast(`${n} değiştirildi`);
  }

  async function saveRemote() {
    if (!cur) return;
    const name = cur.remote ? cur.name : prompt('Sunucuda dosya adı', cur.name);
    if (!name) return;
    try {
      const r = await api.put('/api/tools/notepad/file', { name, content: cur.content });
      cur.name = r.name; cur.remote = true; cur.dirty = false; persist(); drawTabs(); setStatus(st, `Kaydedildi: ${r.name} (${fmtBytes(r.size)})`, 'ok'); toast('Sunucuya kaydedildi');
    } catch (e) { toastError(e); }
  }
  async function openRemote() {
    let files;
    try { files = await api.get('/api/tools/notepad/files'); } catch (e) { return toastError(e); }
    const list = h('div', { class: 'mt mt-list' });
    const m = modal({ title: 'Sunucudaki notlar', body: h('div', null, files.length ? list : h('div', { class: 'muted' }, 'Henüz kaydedilmiş dosya yok')) });
    const draw = () => clear(list, files.map(f => h('div', { class: 'it', style: { color: 'inherit' }, onclick: async () => {
      try { const r = await api.get(`/api/tools/notepad/file?name=${encodeURIComponent(f.name)}`); const d = mk(r.name, r.content); d.remote = true; docs.push(d); open(d); persist(); m.close?.(); } catch (e) { toastError(e); }
    } }, '📄', f.name, h('small', null, `${fmtBytes(f.size)} · ${new Date(f.mtime * 1000).toLocaleString('tr-TR')}`),
    h('button', { class: 'btn sm ghost', onclick: async e => { e.stopPropagation(); if (!await confirmDialog('Sil', `${f.name} sunucudan silinsin mi?`, { okLabel: 'Sil', danger: true })) return; await api.del(`/api/tools/notepad/file?name=${encodeURIComponent(f.name)}`); files = files.filter(x => x !== f); draw(); } }, 'Sil'))));
    draw();
  }

  onLeave(() => { clearTimeout(saveT); persist(); });
  clear(view,
    pageHead('Notepad Master', { back: '#/tools', sub: 'Çok sekmeli metin editörü — otomatik kayıt, sunucuya kaydet, bul/değiştir', right: st }),
    shell(toolbar, findBar, tabs, ed, localIn, h('div', { class: 'small muted' }, `Sekmeler bu tarayıcıda otomatik saklanır; "Sunucuya kaydet" ile hesabınıza (kullanıcı #${uid}) bağlı klasöre yazılır.`)));
  open(docs[0]);
}
