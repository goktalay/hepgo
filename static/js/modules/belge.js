// Evrak › Belge Yönetim: uygulama içi Excel/Word/Sunum. Sahip paylaşım izni verir (görüntüle/düzenle),
// her kaydetmede sürüm geçmişi tutulur. Dış programsız, tarayıcı içinde.
import { api } from '../api.js';
import { clear, confirmDialog, fmtDateTime, h, modal, pageHead, segmented, svgIcon, toast, toastError } from '../ui.js';
import { icons } from '../icons.js';

const KIND = { excel: 'Excel', word: 'Word', sunum: 'Sunum' };
const KIND_ICON = { excel: icons.reports || icons.documents, word: icons.documents, sunum: icons.flight || icons.documents };

function subTabs(active) {
  return h('div', { class: 'module-tabs' }, segmented([['evrak', 'Evraklar'], ['belge', 'Belge Yönetim']], active,
    v => { location.hash = v === 'belge' ? '#/documents/belge' : '#/documents'; }, { tabs: true }));
}

export async function render(view, params, ctx) {
  if (params[0]) return editor(view, Number(params[0]), ctx);
  return list(view, ctx);
}

// ---------- Liste
async function list(view, ctx) {
  let docs = [];
  try { docs = await api.get('/api/belge'); } catch (e) { return toastError(e); }
  const body = h('div');
  const draw = () => clear(body, docs.length
    ? h('div', { class: 'bz-grid' }, docs.map(card))
    : h('div', { class: 'card empty' }, 'Henüz belge yok. “Yeni” ile Excel, Word ya da Sunum oluşturun.'));

  const newMenu = h('div', { class: 'bz-newmenu', hidden: true },
    Object.entries(KIND).map(([k, label]) => h('button', { class: 'bz-newitem', type: 'button',
      onclick: async () => { newMenu.hidden = true; try { const d = await api.post('/api/belge', { kind: k }); location.hash = `#/documents/belge/${d.id}`; } catch (e) { toastError(e); } } },
      svgIcon(KIND_ICON[k]), label)));
  const newBtn = h('button', { class: 'btn primary', type: 'button', onclick: e => { e.stopPropagation(); newMenu.hidden = !newMenu.hidden; } }, '+ Yeni');
  document.addEventListener('click', () => { newMenu.hidden = true; }, { once: false });

  clear(view,
    pageHead('Evrak Yönetimi', { back: '#/', right: h('div', { class: 'bz-newwrap' }, newBtn, newMenu) }),
    subTabs('belge'),
    body);
  draw();
}

function card(d) {
  const perm = d.my_perm === 'owner' ? 'Sahibi' : d.can_write ? 'Düzenleyebilir' : 'Görüntüleyebilir';
  return h('a', { class: 'card bz-card', href: `#/documents/belge/${d.id}` },
    h('span', { class: `bz-icon k-${d.kind}` }, svgIcon(KIND_ICON[d.kind])),
    h('div', { class: 'grow' },
      h('div', { class: 'bz-title' }, h('b', null, d.title), ' ', h('span', { class: 'badge gray' }, KIND[d.kind])),
      h('div', { class: 'small muted' }, `${d.owner_name} · ${fmtDateTime(d.updated_at)}`)),
    h('span', { class: `bz-perm ${d.can_write ? 'w' : ''}` }, perm));
}

// ---------- Editör
async function editor(view, id, ctx) {
  let doc;
  try { doc = await api.get(`/api/belge/${id}`); } catch (e) { return toastError(e); }
  const canWrite = doc.can_write;
  let content = doc.content || {};
  let dirty = false, saving = false;
  const saveState = h('span', { class: 'bz-savestate small muted' }, canWrite ? 'Kaydedildi' : 'Salt-okunur');

  const title = h('input', { class: 'input bz-title-in', value: doc.title, readonly: !canWrite });
  title.addEventListener('input', () => mark());

  const mark = () => { if (!canWrite) return; dirty = true; saveState.textContent = 'Kaydedilmedi'; scheduleSave(); };
  let timer;
  const scheduleSave = () => { clearTimeout(timer); timer = setTimeout(() => save(), 1400); };
  const save = async () => {
    if (!canWrite || saving || !dirty) return;
    saving = true; saveState.textContent = 'Kaydediliyor…';
    try {
      content = collect();
      await api.put(`/api/belge/${id}`, { title: title.value, content });
      dirty = false; saveState.textContent = 'Kaydedildi ✓';
    } catch (e) { saveState.textContent = 'Kaydedilemedi'; toastError(e); }
    finally { saving = false; if (dirty) scheduleSave(); }
  };

  // türüne göre editör gövdesi + collect()
  let collect = () => content;
  const bodyEl = h('div', { class: 'bz-editor' });
  if (doc.kind === 'word') collect = mountWord(bodyEl, content, canWrite, mark);
  else if (doc.kind === 'excel') collect = mountExcel(bodyEl, content, canWrite, mark);
  else collect = mountSunum(bodyEl, content, canWrite, mark);

  const actions = [];
  if (canWrite) actions.push(h('button', { class: 'btn sm', type: 'button', onclick: () => save() }, 'Kaydet'));
  actions.push(h('button', { class: 'btn sm', type: 'button', onclick: () => historyModal(id, doc.kind, canWrite) }, 'Geçmiş'));
  if (doc.my_perm === 'owner') actions.push(h('button', { class: 'btn sm', type: 'button', onclick: () => shareModal(id) }, 'Paylaş'));

  window.addEventListener('beforeunload', beforeUnload);
  function beforeUnload(e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } }

  clear(view,
    pageHead(doc.title, { back: '#/documents/belge',
      right: h('div', { class: 'bz-toolbar' }, h('span', { class: 'badge gray' }, KIND[doc.kind]), saveState, actions) }),
    h('div', { class: 'bz-title-row' }, title),
    bodyEl);
}

// ---------- WORD (zengin metin)
function mountWord(root, content, canWrite, mark) {
  const cmd = (c, v) => { document.execCommand(c, false, v); ed.focus(); mark(); };
  const tb = h('div', { class: 'bz-wordbar' },
    tbtn('B', () => cmd('bold'), 'Kalın'), tbtn('I', () => cmd('italic'), 'İtalik', 'i'),
    tbtn('U', () => cmd('underline'), 'Altı çizili', 'u'),
    sep(),
    tbtn('H1', () => cmd('formatBlock', 'H1')), tbtn('H2', () => cmd('formatBlock', 'H2')), tbtn('P', () => cmd('formatBlock', 'P')),
    sep(),
    tbtn('•', () => cmd('insertUnorderedList')), tbtn('1.', () => cmd('insertOrderedList')),
    sep(),
    tbtn('⯇', () => cmd('justifyLeft')), tbtn('≡', () => cmd('justifyCenter')), tbtn('⯈', () => cmd('justifyRight')));
  const ed = h('div', { class: 'bz-word', contenteditable: canWrite ? 'true' : 'false', html: content.html || '' });
  ed.addEventListener('input', mark);
  clear(root, canWrite ? tb : null, ed);
  return () => ({ html: ed.innerHTML });
}
const tbtn = (label, on, title, tag) => h('button', { class: 'bz-tb', type: 'button', title: title || label, onmousedown: e => e.preventDefault(), onclick: on }, tag ? h(tag, null, label) : label);
const sep = () => h('span', { class: 'bz-sep' });

// ---------- EXCEL (hücre tablosu)
function mountExcel(root, content, canWrite, mark) {
  let rows = content.rows || 40, cols = content.cols || 12;
  const cells = { ...(content.cells || {}) };
  const colName = n => { let s = ''; n++; while (n > 0) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); } return s; };
  const wrap = h('div', { class: 'bz-xl-wrap' });
  const build = () => {
    const head = h('tr', null, h('th', { class: 'bz-xl-corner' }), Array.from({ length: cols }, (_, c) => h('th', null, colName(c))));
    const body = Array.from({ length: rows }, (_, r) => h('tr', null,
      h('th', { class: 'bz-xl-rownum' }, r + 1),
      Array.from({ length: cols }, (_, c) => {
        const key = `${r},${c}`;
        const td = h('td', null, h('input', { class: 'bz-xl-cell', value: cells[key] || '', readonly: !canWrite,
          oninput: e => { if (e.target.value) cells[key] = e.target.value; else delete cells[key]; mark(); } }));
        return td;
      })));
    clear(wrap, h('table', { class: 'bz-xl' }, h('thead', null, head), h('tbody', null, body)));
  };
  const bar = canWrite ? h('div', { class: 'bz-xl-bar' },
    h('button', { class: 'btn sm', type: 'button', onclick: () => { rows += 10; build(); mark(); } }, '+ Satır'),
    h('button', { class: 'btn sm', type: 'button', onclick: () => { cols += 3; build(); mark(); } }, '+ Sütun')) : null;
  clear(root, bar, wrap);
  build();
  return () => ({ rows, cols, cells });
}

// ---------- SUNUM (slaytlar)
function mountSunum(root, content, canWrite, mark) {
  let slides = (content.slides && content.slides.length) ? content.slides.map(s => ({ html: s.html || '' })) : [{ html: '' }];
  let cur = 0;
  const strip = h('div', { class: 'bz-slides' });
  const stage = h('div', { class: 'bz-stage' });
  const draw = () => {
    clear(strip, slides.map((s, i) => h('button', { class: `bz-slidethumb ${i === cur ? 'on' : ''}`, type: 'button',
      onclick: () => { cur = i; draw(); } }, h('span', { class: 'bz-slidenum' }, i + 1), h('div', { class: 'bz-thumbinner', html: s.html || '' }))),
      canWrite ? h('button', { class: 'bz-slideadd', type: 'button', title: 'Slayt ekle',
        onclick: () => { slides.splice(cur + 1, 0, { html: '' }); cur++; draw(); mark(); } }, '+') : null);
    const ed = h('div', { class: 'bz-slide-edit', contenteditable: canWrite ? 'true' : 'false', html: slides[cur]?.html || '' });
    ed.addEventListener('input', () => { slides[cur].html = ed.innerHTML; mark(); });
    const tools = canWrite ? h('div', { class: 'bz-slide-tools' },
      h('button', { class: 'btn sm', type: 'button', onclick: () => { if (slides.length > 1) { slides.splice(cur, 1); cur = Math.max(0, cur - 1); draw(); mark(); } } }, 'Slaytı sil'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { if (cur > 0) { [slides[cur - 1], slides[cur]] = [slides[cur], slides[cur - 1]]; cur--; draw(); mark(); } } }, '↑'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { if (cur < slides.length - 1) { [slides[cur + 1], slides[cur]] = [slides[cur], slides[cur + 1]]; cur++; draw(); mark(); } } }, '↓')) : null;
    clear(stage, tools, ed);
  };
  clear(root, h('div', { class: 'bz-sunum' }, strip, stage));
  draw();
  return () => ({ slides });
}

// ---------- Geçmiş
async function historyModal(id, kind, canWrite) {
  let vers = [];
  try { vers = await api.get(`/api/belge/${id}/versions`); } catch (e) { return toastError(e); }
  const body = vers.length ? h('div', { class: 'bz-vers' }, vers.map(v => h('div', { class: 'bz-ver' },
    h('div', { class: 'grow' }, h('b', null, fmtDateTime(v.saved_at)), h('span', { class: 'small muted' }, v.saved_by_name || '')),
    canWrite ? h('button', { class: 'btn sm', type: 'button', onclick: async () => {
      if (!await confirmDialog({ title: 'Sürümü geri yükle', message: 'Bu sürüm geri yüklensin mi? Mevcut içerik de geçmişe eklenir.' })) return;
      try { await api.post(`/api/belge/${id}/versions/${v.id}/restore`); toast('Sürüm geri yüklendi'); location.reload(); } catch (e) { toastError(e); }
    } }, 'Geri yükle') : null)))
    : h('div', { class: 'empty small muted' }, 'Henüz sürüm yok. Her kaydetmede önceki hâl buraya eklenir.');
  modal({ title: 'Sürüm geçmişi', body });
}

// ---------- Paylaşım
async function shareModal(id) {
  let shares = [], people = [];
  try { [shares, people] = await Promise.all([api.get(`/api/belge/${id}/shares`), api.get('/api/people')]); } catch (e) { return toastError(e); }
  const listEl = h('div', { class: 'bz-shares' });
  const drawShares = () => clear(listEl, shares.length ? shares.map(s => h('div', { class: 'bz-share' },
    h('span', { class: 'grow' }, s.full_name),
    h('span', { class: 'badge gray' }, s.perm === 'write' ? 'Düzenleyebilir' : 'Görüntüler'),
    h('button', { class: 'btn sm ghost', type: 'button', onclick: async () => { try { await api.del(`/api/belge/${id}/shares/${s.user_id}`); shares = shares.filter(x => x.user_id !== s.user_id); drawShares(); } catch (e) { toastError(e); } } }, 'Kaldır')))
    : h('div', { class: 'small muted' }, 'Henüz kimseyle paylaşılmadı. (Varsayılan: herkes görüntüleyebilir.)'));
  const sel = h('select', { class: 'input' }, h('option', { value: '' }, 'Kişi seç…'),
    people.map(p => h('option', { value: p.id }, p.full_name)));
  const perm = h('select', { class: 'input' }, h('option', { value: 'write' }, 'Düzenleyebilir'), h('option', { value: 'read' }, 'Yalnız görüntüler'));
  const add = h('button', { class: 'btn', type: 'button', onclick: async () => {
    if (!sel.value) return;
    try { await api.post(`/api/belge/${id}/shares`, { user_id: Number(sel.value), perm: perm.value });
      shares = await api.get(`/api/belge/${id}/shares`); drawShares(); sel.value = ''; } catch (e) { toastError(e); }
  } }, 'Ekle');
  drawShares();
  modal({ title: 'Paylaş', body: h('div', { class: 'cform' },
    h('p', { class: 'small muted' }, 'Erişim vermezseniz diğer kullanıcılar belgeyi yalnızca görüntüler. Düzenleme izni verdiklerinizi aşağıya ekleyin.'),
    listEl, h('div', { class: 'bz-shareadd' }, sel, perm, add)) });
}
