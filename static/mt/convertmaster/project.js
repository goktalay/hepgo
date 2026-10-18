'use strict';

// Proje penceresi: önizleme (orijinal | dönüştürülmüş), klasör ağacı, dosya listesi (her satırda ilerleme),
// konuşma metni (saniye · dil · metin), Başlat / Durdur.

const $ = (s) => document.querySelector(s);
const ROW_H = 30;
const TROW_H = 26;

let project = null;
let settings = {};
let snap = { files: [], root: '', sourcePath: '', running: false, counts: {} };
let files = new Map();       // rel -> dosya (+ durum)
let running = false;
let selected = null;         // seçili dosya (rel)
let treeFolder = null;       // ağaçta seçilen klasör (liste bu klasörle süzülür); null = tümü
const expanded = new Set(['']);
let listRows = [];           // listede görünen dosyalar (süzülmüş, sıralı)
let treeRows = [];
let sort = { key: 'name', dir: 'asc' };
let filterText = '';
let statusFilter = 'all';
let transcript = null;       // { rel, segments }
let outSize = 0;

for (const el of document.querySelectorAll('[data-t]')) el.textContent = t(el.dataset.t);

const T = () => FORMATS.TYPES[project.type] || FORMATS.TYPES.video;
const isAV = () => project && (project.type === 'video' || project.type === 'audio');
const isImage = () => project && project.type === 'image';
// Metin çıkarma: video/seste konuşmadan metne, resimde OCR — ikisi de projede istenirse açık
const speechOn = () => (isImage() ? !!(project.ocr && project.ocr.enabled) : !!(isAV() && project.speech && project.speech.enabled));
const textIcon = () => (isImage() ? 'text' : 'mic');
const textActionLabel = (again) => (isImage() ? t(again ? 'pj.reocr' : 'pj.ocrThis') : t(again ? 'pj.retranscribe' : 'pj.transcribeThis'));
const noTextLabel = () => (isImage() ? t('pj.noText') : t('pj.noAudio'));
const noTextHint = () => (isImage() ? t('pj.noTextHint') : t('err.noAudio'));
const fmtDur = (s) => {
  if (!s && s !== 0) return '';
  s = Math.round(s);
  const hh = Math.floor(s / 3600);
  const mm = Math.floor(s / 60) % 60;
  const ss = String(s % 60).padStart(2, '0');
  return hh ? `${hh}:${String(mm).padStart(2, '0')}:${ss}` : `${mm}:${ss}`;
};
const fmtSec = (s) => `⁦${s.toFixed(1)} ${t('pj.secUnit')}⁩`;
const dirOf = (rel) => (rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '');
const nameOf = (rel) => rel.slice(rel.lastIndexOf('/') + 1);

// --- Üst çubuk -----------------------------------------------------------------
$('#btnSource').innerHTML = icon('folder') + esc(t('pj.changeSource'));
$('#btnOutDir').innerHTML = icon('open');
$('#btnOutDir').title = t('pj.openOutDir');
$('#btnExport').innerHTML = icon('export');
$('#btnExport').title = t('pj.exportOutputs');
$('#btnClear').innerHTML = icon('broom');
$('#btnClear').title = t('pj.clearOutputs');
$('#btnSettings').innerHTML = icon('gear');
$('#btnSettings').title = t('app.projectSettings');
$('#pvLink').innerHTML = icon('link');
$('#icoTree').innerHTML = icon('folder');
$('#icoList').innerHTML = icon('layers');
$('#icoTr').innerHTML = icon('text');
$('#lfIco').innerHTML = icon('search');
$('#listFilter').placeholder = t('pj.filterPh');
document.querySelector('#treeCol [data-a="expand"]').innerHTML = icon('chevronDown');
document.querySelector('#treeCol [data-a="expand"]').title = t('pj.expandAll');
document.querySelector('#treeCol [data-a="collapse"]').innerHTML = icon('chevronRight');
document.querySelector('#treeCol [data-a="collapse"]').title = t('pj.collapseAll');
document.querySelector('#treeCol [data-a="refresh"]').innerHTML = icon('refresh');
document.querySelector('#treeCol [data-a="refresh"]').title = t('pj.rescan') + ' (F5)';

document.querySelector('#trCol [data-a="export"]').innerHTML = icon('download');
document.querySelector('#trCol [data-a="export"]').title = t('pj.exportTranscript');
$('#statusFilter').innerHTML = [['all', t('pj.fAll')], ['pending', t('pj.fPending')], ['active', t('pj.fActive')], ['done', t('pj.fDone')], ['error', t('pj.fError')]]
  .map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('');
mountMastertool($('.bar-actions'));
const paintThemeBtn = themeButton($('#btnTheme'), () => settings);

window.api.getStore().then((d) => { settings = d.settings; applyLayout(); paintThemeBtn(); });
window.api.onStoreChanged((d) => { settings = d.settings; paintThemeBtn(); });

function paintHeader() {
  const c = T().color;
  document.body.style.setProperty('--c', c);
  $('#pjAvatar').innerHTML = icon(TYPE_ICONS[project.type] || 'video');
  $('#pjName').textContent = project.name;
  document.title = `${project.name} — Convert Master`;
  const src = project.sourceMode === 'file' && project.sourcePath ? FORMATS.extOf(project.sourcePath).toUpperCase()
    : (project.sourceExts || []).length === T().source.length ? t('app.allExts') : (project.sourceExts || []).map((x) => x.toUpperCase()).join(', ');
  $('#pjConv').innerHTML = `<span class="ext">${esc(src)}</span>${icon('arrowRight')}<span class="ext to">${esc(project.targetExt.toUpperCase())}</span>`;
  $('#pjSrc').textContent = project.sourcePath || t('app.noSource');
  $('#pjSrc').title = project.sourcePath || '';
  $('#btnSource').innerHTML = icon(project.sourceMode === 'file' ? 'file' : 'folder') + esc(project.sourcePath ? t('pj.changeSource') : t('pj.pickSource'));
  $('#listCol').classList.toggle('speech', !!speechOn());
  // Metin paneli: video/seste konuşma (saniye · dil · metin), resimde OCR (satır · güven · metin)
  const tb = document.querySelector('#trCol [data-a="transcribe"]');
  tb.innerHTML = icon(textIcon());
  tb.title = textActionLabel(false);
  document.querySelector('#trCol .panel-title').textContent = isImage() ? t('pj.ocrPanel') : t('pj.transcript');
  document.querySelector('#trCol .tr-head').innerHTML = isImage()
    ? `<span>${esc(t('pj.trLine'))}</span><span>${esc(t('pj.trConf'))}</span><span>${esc(t('pj.trText'))}</span>`
    : `<span>${esc(t('pj.trSecond'))}</span><span>${esc(t('pj.trLang'))}</span><span>${esc(t('pj.trText'))}</span>`;
  paintListHead();
}

function paintRun() {
  const b = $('#btnRun');
  b.classList.toggle('stop', running);
  b.innerHTML = running ? icon('stop') + esc(t('pj.stop')) : icon('play') + esc(t('pj.start'));
  b.title = (running ? t('pj.stop') : t('pj.start')) + ' (Ctrl+Enter)';
  b.disabled = !snap.root || (!running && !selectedFiles().length);
}

$('#btnRun').onclick = () => (running ? window.api.pjStop() : startAll());
$('#btnSource').onclick = changeSource;
$('#btnOutDir').onclick = () => window.api.pjOpenOutDir();
$('#btnExport').onclick = async () => {
  const r = await window.api.pjExportOutputs(null);
  if (r) toast(t('pj.exported', { n: r.count }), { type: 'ok', sub: r.dest });
};
$('#btnClear').onclick = async () => {
  const r = await clearOutputsDialog(t('pj.clearOutputs'), t('app.clearOutputsMsg', { name: esc(project.name) }), { speech: true });
  if (!r) return;
  await window.api.pjDeleteOutputs({ transcripts: r.transcripts });
  toast(t('set.clearedConverted'), { type: 'ok' });
  refreshOutSize();
  loadPreviews(true);
  if (r.transcripts) loadTranscript();
};
$('#btnSettings').onclick = async () => {
  const before = JSON.stringify([project.sourceExts, project.includeSubfolders, project.sourceMode, project.sourcePath, project.targetExt]);
  const id = await editProject(project, { settings });
  if (!id) return;
  toast(t('common.saved'), { type: 'ok' });
  // project:changed olayı başlığı günceller; kaynak kuralları değiştiyse yeniden tara
  setTimeout(async () => {
    const after = JSON.stringify([project.sourceExts, project.includeSubfolders, project.sourceMode, project.sourcePath, project.targetExt]);
    if (after !== before) applySnapshot(await window.api.pjScan());
  }, 50);
};

async function startAll() {
  if (!selectedFiles().length) return;
  await window.api.pjStart({});
}

async function changeSource() {
  const s = await window.api.pjChangeSource();
  if (s) { selected = null; treeFolder = null; applySnapshot(s); }
}

// --- Bölücüler (önizleme yüksekliği, ağaç ve metin genişliği) ---------------------
function applyLayout() {
  $('#preview').style.height = `${settings.previewHeight || 320}px`;
  $('#treeCol').style.width = `${settings.treeWidth || 280}px`;
  $('#trCol').style.width = `${settings.transcriptWidth || 380}px`;
  $('#pvLink').classList.toggle('on', settings.linkPreview !== false);
  $('#pvLink').title = t('pj.linkPreview');
}
function splitter(el, { axis, get, set, invert = false, min, max, key }) {
  el.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const start = axis === 'x' ? e.clientX : e.clientY;
    const base = get();
    const rtl = document.documentElement.dir === 'rtl' && axis === 'x';
    el.classList.add('active');
    document.body.classList.add(axis === 'x' ? 'resizing-col' : 'resizing-row');
    const move = (ev) => {
      let d = (axis === 'x' ? ev.clientX : ev.clientY) - start;
      if (invert !== rtl) d = -d;
      set(Math.max(min, Math.min(max(), base + d)));
      renderLists();
    };
    const up = () => {
      el.classList.remove('active');
      document.body.classList.remove('resizing-col', 'resizing-row');
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      window.api.setSettings({ [key]: Math.round(get()) });
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  });
}
splitter($('#splitPreview'), { axis: 'y', key: 'previewHeight', min: 140, max: () => innerHeight - 260,
  get: () => $('#preview').getBoundingClientRect().height, set: (v) => ($('#preview').style.height = `${v}px`) });
splitter($('#splitTree'), { axis: 'x', key: 'treeWidth', min: 160, max: () => innerWidth * 0.4,
  get: () => $('#treeCol').getBoundingClientRect().width, set: (v) => ($('#treeCol').style.width = `${v}px`) });
splitter($('#splitTr'), { axis: 'x', key: 'transcriptWidth', invert: true, min: 240, max: () => innerWidth * 0.5,
  get: () => $('#trCol').getBoundingClientRect().width, set: (v) => ($('#trCol').style.width = `${v}px`) });
$('#pvLink').onclick = () => { settings.linkPreview = settings.linkPreview === false; applyLayout(); window.api.setSettings({ linkPreview: settings.linkPreview }); };

// --- Sanal liste -----------------------------------------------------------------
function virtual(el, rowH, getRows, renderRow) {
  const spacer = el.querySelector('.vspacer');
  const rowsEl = el.querySelector('.vrows');
  let lastKey = '';
  const draw = (force) => {
    const rows = getRows();
    spacer.style.height = `${rows.length * rowH}px`;
    const first = Math.max(0, Math.floor(el.scrollTop / rowH) - 5);
    const last = Math.min(rows.length, Math.ceil((el.scrollTop + el.clientHeight) / rowH) + 5);
    const key = `${first}:${last}:${rows.length}`;
    if (!force && key === lastKey) return;
    lastKey = key;
    rowsEl.style.transform = `translateY(${first * rowH}px)`;
    const frag = document.createDocumentFragment();
    for (let i = first; i < last; i++) frag.appendChild(renderRow(rows[i], i));
    rowsEl.replaceChildren(frag);
  };
  el.addEventListener('scroll', () => draw(false));
  new ResizeObserver(() => draw(true)).observe(el);
  return {
    draw: () => draw(true),
    scrollTo(i) {
      const top = i * rowH;
      if (top < el.scrollTop) el.scrollTop = top;
      else if (top + rowH > el.scrollTop + el.clientHeight) el.scrollTop = top + rowH - el.clientHeight;
    },
  };
}

// --- Klasör ağacı ------------------------------------------------------------------
let treeRoot = null;
function buildTree() {
  const root = { path: '', name: '', dirs: new Map(), files: [] };
  for (const f of files.values()) {
    const parts = f.rel.split('/');
    let node = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const p = parts.slice(0, i + 1).join('/');
      if (!node.dirs.has(parts[i])) node.dirs.set(parts[i], { path: p, name: parts[i], dirs: new Map(), files: [] });
      node = node.dirs.get(parts[i]);
    }
    node.files.push(f);
  }
  const count = (n) => {
    n.total = n.files.length;
    n.checked = n.files.filter((f) => f.checked).length;
    for (const d of n.dirs.values()) { count(d); n.total += d.total; n.checked += d.checked; }
  };
  count(root);
  root.name = (snap.root || '').split(/[\\/]/).filter(Boolean).pop() || snap.root || '';
  treeRoot = root;
}

function flattenTree() {
  const rows = [];
  if (!treeRoot) return rows;
  const byName = (a, b) => a.name.localeCompare(b.name, LANG, { numeric: true, sensitivity: 'base' });
  const walk = (node, depth) => {
    for (const d of [...node.dirs.values()].sort(byName)) {
      rows.push({ dir: d, depth });
      if (expanded.has(d.path)) walk(d, depth + 1);
    }
    for (const f of [...node.files].sort((a, b) => byName({ name: nameOf(a.rel) }, { name: nameOf(b.rel) }))) rows.push({ file: f, depth });
  };
  rows.push({ dir: treeRoot, depth: 0, root: true });
  if (expanded.has('')) walk(treeRoot, 1);
  treeRows = rows;
  return rows;
}

const filesUnder = (node) => {
  const out = [...node.files];
  for (const d of node.dirs.values()) out.push(...filesUnder(d));
  return out;
};

const tree = virtual($('#tree'), TROW_H, () => treeRows, (row) => {
  const pad = 6 + row.depth * 16;
  if (row.dir) {
    const d = row.dir;
    const el = h(`<div class="trow ${treeFolder === d.path || (row.root && treeFolder === null) ? 'sel' : ''}" style="padding-inline-start:${pad}px">
      <span class="tw ${expanded.has(d.path) ? 'open' : ''}">${d.dirs.size || d.files.length ? icon('chevronRight') : ''}</span>
      <input type="checkbox"><span class="ti dir">${icon('folder')}</span><span class="tn"></span><span class="tc">${d.checked}/${d.total}</span></div>`);
    el.querySelector('.tn').textContent = d.name || '/';
    el.title = row.root ? snap.root : d.path;
    const cb = el.querySelector('input');
    cb.checked = d.total > 0 && d.checked === d.total;
    cb.indeterminate = d.checked > 0 && d.checked < d.total;
    cb.onclick = (e) => { e.stopPropagation(); setChecked(filesUnder(d), !(d.checked === d.total)); };
    el.querySelector('.tw').onclick = (e) => {
      e.stopPropagation();
      if (expanded.has(d.path)) expanded.delete(d.path); else expanded.add(d.path);
      renderTree();
    };
    el.onclick = () => { treeFolder = row.root ? null : d.path; renderTree(); renderList(); };
    el.ondblclick = () => { if (expanded.has(d.path)) expanded.delete(d.path); else expanded.add(d.path); renderTree(); };
    return el;
  }
  const f = row.file;
  const el = h(`<div class="trow ${selected === f.rel ? 'sel' : ''}" style="padding-inline-start:${pad + 16}px">
    <input type="checkbox" ${f.checked ? 'checked' : ''}><span class="ti file">${icon(TYPE_ICONS[project.type])}</span><span class="tn"></span><span class="st-dot ${f.status}"></span></div>`);
  el.querySelector('.tn').textContent = nameOf(f.rel);
  el.title = f.rel;
  el.querySelector('input').onclick = (e) => { e.stopPropagation(); setChecked([f], e.target.checked); };
  el.onclick = () => { if (f.checked) select(f.rel, { scroll: true }); };
  return el;
});

function renderTree() {
  buildTree();
  flattenTree();
  tree.draw();
}

async function setChecked(list, checked) {
  const rels = list.filter((f) => f.checked !== checked).map((f) => f.rel);
  if (!rels.length) return;
  for (const rel of rels) files.get(rel).checked = checked;
  const lostSel = !checked && rels.includes(selected);
  if (lostSel) selected = null;
  renderTree();
  renderList();
  paintStatus();
  if (lostSel) { loadPreviews(true); loadTranscript(); }
  await window.api.pjCheck(rels, checked);
}

$('#treeCol [data-a="expand"]').onclick = () => {
  const walk = (n) => { expanded.add(n.path); for (const d of n.dirs.values()) walk(d); };
  if (treeRoot) walk(treeRoot);
  renderTree();
};
$('#treeCol [data-a="collapse"]').onclick = () => { expanded.clear(); expanded.add(''); renderTree(); };
$('#treeCol [data-a="refresh"]').onclick = rescan;

async function rescan() {
  applySnapshot(await window.api.pjScan());
}

// --- Dosya listesi --------------------------------------------------------------------
const COLS = () => [
  ['num', '#'], ['name', t('pj.colName')], ['dir', t('pj.colFolder')], ['size', t('pj.colSize')], ['progress', t('pj.colProgress')],
  ['status', t('pj.colStatus')], ...(speechOn() ? [['speech', t('pj.colSpeech')]] : []), ['out', t('pj.colOut')],
];

function paintListHead() {
  const head = $('#listHead');
  head.innerHTML = '';
  for (const [k, l] of COLS()) {
    const s = h(`<span class="${sort.key === k ? 'sorted' : ''}" data-dir="${sort.dir}" ${['size', 'out'].includes(k) ? 'style="text-align:end"' : ''}>${esc(l)}</span>`);
    s.onclick = () => {
      if (k === 'num') { sort = { key: 'name', dir: 'asc' }; } else sort = { key: k, dir: sort.key === k && sort.dir === 'asc' ? 'desc' : 'asc' };
      paintListHead();
      renderList();
    };
    head.appendChild(s);
  }
}

const STATUS_ORDER = { converting: 0, queued: 1, error: 2, pending: 3, done: 4 };
function computeList() {
  const q = filterText.toLowerCase();
  let rows = [...files.values()].filter((f) => f.checked);
  if (treeFolder) rows = rows.filter((f) => f.rel === treeFolder || f.rel.startsWith(treeFolder + '/'));
  if (q) rows = rows.filter((f) => f.rel.toLowerCase().includes(q));
  if (statusFilter === 'active') rows = rows.filter((f) => f.status === 'converting' || f.status === 'queued' || (f.speech && ['running', 'queued'].includes(f.speech.status)));
  else if (statusFilter !== 'all') rows = rows.filter((f) => f.status === statusFilter);
  const cmp = {
    name: (a, b) => a.rel.localeCompare(b.rel, LANG, { numeric: true, sensitivity: 'base' }),
    dir: (a, b) => dirOf(a.rel).localeCompare(dirOf(b.rel), LANG, { numeric: true }) || nameOf(a.rel).localeCompare(nameOf(b.rel), LANG, { numeric: true }),
    size: (a, b) => a.size - b.size,
    out: (a, b) => (a.outSize || 0) - (b.outSize || 0),
    progress: (a, b) => (a.status === 'done' ? 1 : a.progress) - (b.status === 'done' ? 1 : b.progress),
    status: (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status],
    speech: (a, b) => (a.speech ? a.speech.progress : -1) - (b.speech ? b.speech.progress : -1),
  }[sort.key] || ((a, b) => a.rel.localeCompare(b.rel));
  rows.sort((a, b) => (sort.dir === 'asc' ? cmp(a, b) : -cmp(a, b)));
  listRows = rows;
}

function statusCell(f) {
  switch (f.status) {
    case 'converting': return `<span class="stat converting"><span class="spin"></span>${esc(t('st.converting'))}</span>`;
    case 'queued': return `<span class="stat queued">${icon('history')}${esc(t('st.queued'))}</span>`;
    case 'done': return `<span class="stat done">${icon('check')}${esc(t('st.done'))}</span>`;
    case 'error': return `<span class="stat error" title="${esc(f.error)}">${icon('x')}${esc(t('st.error'))}</span>`;
    default: return `<span class="stat pending">${esc(t('st.pending'))}</span>`;
  }
}
function progCell(f) {
  const p = f.status === 'done' ? 1 : f.progress || 0;
  const cls = f.status === 'done' ? 'done' : f.status === 'error' ? 'error' : '';
  return `<div class="cell-prog ${cls}"><div class="bar"><div style="width:${(f.status === 'error' ? 1 : p) * 100}%"></div></div><span class="pct">${f.status === 'pending' ? '' : Math.floor(p * 100) + '%'}</span></div>`;
}
function speechCell(f) {
  const s = f.speech;
  if (!s) return '';
  if (s.status === 'done') return `<span class="stat done" title="${esc(isImage() ? ocrLangNames(s.language) : langName(s.language))}">${icon('text')}${esc(t(isImage() ? 'pj.lines' : 'pj.segments', { n: s.count || 0 }))}</span>`;
  if (s.status === 'error') return `<span class="stat error" title="${esc(s.error)}">${icon('x')}${esc(t('st.error'))}</span>`;
  if (s.status === 'queued') return `<span class="stat queued">${icon('history')}${esc(t('st.queued'))}</span>`;
  if (s.status === 'canceled') return `<span class="stat pending">${esc(t('st.canceled'))}</span>`;
  if (s.status === 'none') return `<span class="stat pending" title="${esc(noTextHint())}">${esc(noTextLabel())}</span>`;
  return `<div class="cell-prog speech"><div class="bar"><div style="width:${(s.progress || 0) * 100}%"></div></div><span class="pct">${Math.floor((s.progress || 0) * 100)}%</span></div>`;
}
function outCell(f) {
  if (!f.outSize) return '';
  const good = f.outSize < f.size;
  return `<span class="osz ${good ? 'good' : ''}" title="${esc(good ? '−' : '+')}${Math.abs(Math.round((1 - f.outSize / f.size) * 100))}%">${formatSize(f.outSize)}</span>`;
}

const list = virtual($('#list'), ROW_H, () => listRows, (f, i) => {
  const el = h(`<div class="lrow ${selected === f.rel ? 'sel' : ''}" data-rel="${esc(f.rel)}">
    <span class="num">${i + 1}</span>
    <span class="nm">${icon(TYPE_ICONS[project.type])}<span></span></span>
    <span class="dir"></span>
    <span class="sz">${formatSize(f.size)}</span>
    <span>${progCell(f)}</span>
    <span>${statusCell(f)}</span>
    ${speechOn() ? `<span>${speechCell(f)}</span>` : ''}
    <span class="osz-c" style="text-align:end">${outCell(f)}</span></div>`);
  el.querySelector('.nm span').textContent = nameOf(f.rel);
  el.querySelector('.dir').textContent = dirOf(f.rel);
  el.title = f.error ? `${f.rel}\n${f.error}` : f.rel;
  el.onclick = () => select(f.rel);
  el.ondblclick = () => window.api.pjOpen(f.rel, f.status === 'done' ? 'out' : 'src').catch((e) => toast(e.message, { type: 'err' }));
  el.oncontextmenu = (e) => { e.preventDefault(); select(f.rel); rowMenu(e.clientX, e.clientY, f); };
  return el;
});

function renderList() {
  computeList();
  $('#listCount').textContent = `(${listRows.length})`;
  const empty = $('#list .empty-list');
  if (empty) empty.remove();
  list.draw();
  if (!listRows.length && project && project.sourceMode !== 'file' && snap.root) {
    const any = [...files.values()].some((f) => f.checked);
    $('#list').appendChild(h(`<div class="empty-list">${icon(files.size ? 'checkSquare' : 'search')}${esc(!files.size ? t('pj.noFiles', { exts: (project.sourceExts || []).join(', ') }) : any ? t('pj.noMatch') : t('pj.noneChecked'))}</div>`));
  }
  paintRun();
}

function renderLists() { tree.draw(); list.draw(); }

$('#listFilter').addEventListener('input', (e) => { filterText = e.target.value.trim(); renderList(); });
$('#statusFilter').onchange = (e) => { statusFilter = e.target.value; renderList(); };

function rowMenu(x, y, f) {
  const done = f.status === 'done';
  const busy = f.status === 'converting' || f.status === 'queued';
  contextMenu(x, y, [
    { label: done ? t('pj.reconvert') : t('pj.convertThis'), icon: 'play', disabled: busy, action: () => window.api.pjStart({ rels: [f.rel], force: true }) },
    { label: textActionLabel(f.speech && f.speech.status === 'done'), icon: textIcon(), action: () => window.api.pjTranscribe([f.rel]) },
    '-',
    { label: t('pj.openOut'), icon: 'open', disabled: !done, action: () => window.api.pjOpen(f.rel, 'out').catch((e) => toast(e.message, { type: 'err' })) },
    { label: t('pj.revealOut'), icon: 'folder', disabled: !done, action: () => window.api.pjReveal(f.rel, 'out') },
    { label: t('pj.openSrc'), icon: 'file', action: () => window.api.pjOpen(f.rel, 'src').catch((e) => toast(e.message, { type: 'err' })) },
    { label: t('pj.revealSrc'), icon: 'folder', action: () => window.api.pjReveal(f.rel, 'src') },
    '-',
    { label: t('pj.exportThis'), icon: 'export', disabled: !done, action: async () => { const r = await window.api.pjExportOutputs([f.rel]); if (r) toast(t('pj.exported', { n: r.count }), { type: 'ok', sub: r.dest }); } },
    { label: t('pj.deleteOut'), icon: 'trash', disabled: !done, action: async () => { await window.api.pjDeleteOutputs({ rels: [f.rel] }); refreshOutSize(); if (selected === f.rel) loadPreviews(true); } },
    project.sourceMode === 'folder' ? { label: t('pj.uncheck'), icon: 'x', danger: true, action: () => setChecked([f], false) } : null,
  ]);
}

// Klavye: ↑/↓ seçim, Enter aç, Ctrl+Enter başlat/durdur, F5 yeniden tara
document.addEventListener('keydown', (e) => {
  if (document.querySelector('.modal-backdrop')) return;
  const inInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
  if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); $('#btnRun').click(); return; }
  if (e.key === 'F5') { e.preventDefault(); rescan(); return; }
  if (inInput) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    if (!listRows.length) return;
    e.preventDefault();
    const i = listRows.findIndex((f) => f.rel === selected);
    const n = e.key === 'ArrowDown' ? Math.min(listRows.length - 1, i + 1) : Math.max(0, i - 1);
    select(listRows[n].rel, { scroll: true });
  }
  if (e.key === 'Enter' && selected) {
    const f = files.get(selected);
    window.api.pjOpen(selected, f && f.status === 'done' ? 'out' : 'src').catch((err) => toast(err.message, { type: 'err' }));
  }
});

// --- Tek dosya modu --------------------------------------------------------------------
function renderSingle() {
  const el = $('#single');
  const f = [...files.values()][0];
  if (!f) {
    el.innerHTML = `<div class="empty-list">${icon('file')}${esc(t('pj.fileMissing'))}</div>`;
    return;
  }
  const p = f.status === 'done' ? 1 : f.progress || 0;
  const cls = f.status === 'done' ? 'done' : f.status === 'error' ? 'error' : '';
  const sp = f.speech;
  el.innerHTML = `<div class="single-card">
    <div class="sc-head"><span class="pj-avatar">${icon(TYPE_ICONS[project.type])}</span>
      <div style="min-width:0"><div class="sc-name"></div><div class="sc-sub">${formatSize(f.size)}${f.duration ? ' · ' + fmtDur(f.duration) : ''}</div></div></div>
    <div class="big-prog ${cls}"><div class="bp-row"><span>${statusCell(f)}</span><b>${f.status === 'pending' ? '' : Math.floor(p * 100) + '%'}</b></div>
      <div class="bar"><div style="width:${(f.status === 'error' ? 1 : p) * 100}%"></div></div>
      ${f.outSize ? `<div class="bp-row"><span>${esc(t('pj.colOut'))}: ${formatSize(f.outSize)}</span><span>${f.outSize < f.size ? '−' : '+'}${Math.abs(Math.round((1 - f.outSize / f.size) * 100))}%</span></div>` : ''}
    </div>
    ${f.error ? `<div class="err-box">${esc(f.error)}</div>` : ''}
    ${sp ? `<div class="big-prog speech ${sp.status === 'error' ? 'error' : ''}"><div class="bp-row"><span>${icon(textIcon())} ${esc(t('pj.colSpeech'))}</span><span>${sp.status === 'done' ? esc(t(isImage() ? 'pj.lines' : 'pj.segments', { n: sp.count || 0 })) + ' · ' + esc(isImage() ? ocrLangNames(sp.language) : langName(sp.language)) : sp.status === 'none' ? esc(noTextHint()) : sp.status === 'error' ? esc(t('st.error')) : sp.status === 'queued' ? esc(t('st.queued')) : Math.floor((sp.progress || 0) * 100) + '%'}</span></div>
      <div class="bar"><div style="width:${(sp.status === 'done' ? 1 : sp.progress || 0) * 100}%"></div></div>${sp.error ? `<div class="err-box">${esc(sp.error)}</div>` : ''}</div>` : ''}
    <div class="sc-actions">
      ${f.status === 'done' ? `<button class="btn sm" data-a="again">${icon('refresh')}${esc(t('pj.reconvert'))}</button>
        <button class="btn sm" data-a="open">${icon('open')}${esc(t('pj.openOut'))}</button>
        <button class="btn sm" data-a="reveal">${icon('folder')}${esc(t('pj.revealOut'))}</button>
        <button class="btn sm" data-a="export">${icon('export')}${esc(t('pj.exportThis'))}</button>` : ''}
      ${f.status !== 'converting' && (!sp || ['error', 'canceled', 'done'].includes(sp.status)) ? `<button class="btn sm" data-a="speech">${icon(textIcon())}${esc(textActionLabel(sp && sp.status === 'done'))}</button>` : ''}
    </div></div>`;
  el.querySelector('.sc-name').textContent = nameOf(f.rel);
  el.querySelector('.sc-name').title = snap.sourcePath;
  const act = (a, fn) => { const b = el.querySelector(`[data-a="${a}"]`); if (b) b.onclick = fn; };
  act('again', () => window.api.pjStart({ rels: [f.rel], force: true }));
  act('open', () => window.api.pjOpen(f.rel, 'out').catch((e) => toast(e.message, { type: 'err' })));
  act('reveal', () => window.api.pjReveal(f.rel, 'out'));
  act('export', async () => { const r = await window.api.pjExportOutputs([f.rel]); if (r) toast(t('pj.exported', { n: r.count }), { type: 'ok', sub: r.dest }); });
  act('speech', () => window.api.pjTranscribe([f.rel]));
}

// --- Seçim ve önizleme ---------------------------------------------------------------------
function select(rel, { scroll = false } = {}) {
  if (selected === rel) return;
  selected = rel;
  renderLists();
  if (scroll) {
    const i = listRows.findIndex((f) => f.rel === rel);
    if (i >= 0) list.scrollTo(i);
  }
  loadPreviews(true);
  loadTranscript();
}

const loaded = { src: null, out: null }; // "rel|status|outSize" — gereksiz yeniden yüklemeyi önler
const mediaEls = { src: null, out: null };

function pane(which) { return document.querySelector(`.pv[data-which="${which}"]`); }

function emptyPane(which, html) {
  const p = pane(which);
  p.querySelector('.pv-name').textContent = '';
  p.querySelector('.pv-info').innerHTML = '';
  p.querySelector('.pv-body').innerHTML = `<div class="pv-empty">${html}</div>`;
  mediaEls[which] = null;
}

async function loadPreviews(force) {
  const f = selected && files.get(selected);
  if (!f) {
    loaded.src = loaded.out = null;
    emptyPane('src', `${icon(TYPE_ICONS[project.type] || 'video')}${esc(t('pj.pickToPreview'))}`);
    emptyPane('out', `${icon('arrowRight')}${esc(t('pj.outPreviewHint'))}`);
    return;
  }
  const keySrc = `${f.rel}`;
  if (force || loaded.src !== keySrc) { loaded.src = keySrc; showPane('src', f); }
  const keyOut = `${f.rel}|${f.status}|${f.outSize}`;
  if (force || loaded.out !== keyOut) {
    loaded.out = keyOut;
    if (f.status === 'done') showPane('out', f);
    else if (f.status === 'converting') emptyPane('out', `<span class="spin" style="width:22px;height:22px;color:var(--accent);margin-bottom:8px"></span><br>${esc(t('pj.converting'))}`);
    else if (f.status === 'error') emptyPane('out', `${icon('x')}<b style="color:var(--err)">${esc(t('st.error'))}</b><br>${esc(f.error)}`);
    else emptyPane('out', `${icon('arrowRight')}${esc(t('pj.outPreviewHint'))}`);
  }
}

function infoChips(pv, which) {
  const i = pv.info || {};
  const out = [];
  if (i.video && i.video.width) out.push(`${i.video.width}×${i.video.height}`);
  if (pv.kind === 'video' && i.video) out.push(i.video.codec);
  if (pv.kind === 'audio' && i.audio) out.push(`${i.audio.codec}${i.audio.sampleRate ? ' · ' + i.audio.sampleRate / 1000 + ' kHz' : ''}`);
  if (pv.kind !== 'image' && i.duration) out.push(fmtDur(i.duration));
  if (i.bitrate && pv.kind !== 'image') out.push(`${i.bitrate} kb/s`);
  const chips = out.filter(Boolean).map((x) => `<span class="chip-i">${esc(x)}</span>`);
  chips.push(`<span class="chip-i">${formatSize(i.size)}</span>`);
  if (which === 'out') {
    const f = files.get(selected);
    if (f && f.size && i.size) {
      const d = Math.round((1 - i.size / f.size) * 100);
      chips.push(`<span class="chip-i ${d >= 0 ? 'good' : 'bad'}">${d >= 0 ? '−' : '+'}${Math.abs(d)}%</span>`);
    }
  }
  return chips.join('');
}

async function showPane(which, f) {
  const p = pane(which);
  const body = p.querySelector('.pv-body');
  body.innerHTML = `<div class="pv-empty"><span class="spin" style="width:20px;height:20px;color:var(--accent)"></span></div>`;
  mediaEls[which] = null;
  let pv;
  try {
    pv = await window.api.pjPreview(f.rel, which);
  } catch (e) {
    if (selected !== f.rel) return;
    emptyPane(which, `${icon('x')}${esc(e.message)}`);
    return;
  }
  if (selected !== f.rel) return;
  if (!pv) {
    emptyPane(which, which === 'out' ? `${icon('arrowRight')}${esc(t('pj.outPreviewHint'))}` : `${icon('x')}${esc(t('pj.fileMissing'))}`);
    return;
  }
  p.querySelector('.pv-name').textContent = pv.name;
  p.querySelector('.pv-name').title = pv.path;
  p.querySelector('.pv-info').innerHTML = infoChips(pv, which);
  if (pv.kind === 'image') {
    body.innerHTML = '';
    const img = h('<img class="full" alt="">');
    img.src = pv.url;
    body.appendChild(img);
    body.appendChild(h('<div class="ocr-box hidden"></div>'));
    mediaEls[which] = img;
    img.addEventListener('load', () => { if (ocrSel >= 0) showOcrBox(ocrSel); });
    return;
  }
  if (pv.kind === 'audio') {
    body.innerHTML = `<div class="pv-audio"><div class="wave"><div class="head"></div></div><audio controls preload="metadata"></audio></div>`;
    const a = body.querySelector('audio');
    const wave = body.querySelector('.wave');
    if (pv.waveform) wave.style.backgroundImage = `url("${pv.waveform}")`;
    a.src = pv.url;
    a.addEventListener('timeupdate', () => { if (a.duration) wave.querySelector('.head').style.left = `${(a.currentTime / a.duration) * 100}%`; });
    wave.onclick = (e) => { const r = wave.getBoundingClientRect(); if (a.duration) a.currentTime = ((e.clientX - r.left) / r.width) * a.duration; };
    attachMedia(which, a);
    return;
  }
  // video
  const showProxyBox = (msg) => {
    body.innerHTML = `<div class="pv-poster">${pv.poster ? `<img src="${pv.poster}" alt="">` : ''}
      <div class="proxy-box"><span>${esc(msg)}</span><button class="btn sm primary">${icon('play')}${esc(t('pj.makePreview'))}</button></div></div>`;
    body.querySelector('button').onclick = async () => {
      const box = body.querySelector('.proxy-box');
      box.innerHTML = `<span>${esc(t('pj.makingPreview'))}</span><div class="progress"><div></div></div>`;
      try {
        const url = await window.api.pjProxy(f.rel, which);
        if (selected !== f.rel) return;
        playVideo(url);
      } catch (e) { box.innerHTML = `<span style="color:var(--err)">${esc(e.message)}</span>`; }
    };
  };
  const playVideo = (url) => {
    body.innerHTML = '';
    const v = h('<video controls preload="metadata"></video>');
    if (pv.poster) v.poster = pv.poster;
    v.src = url;
    v.addEventListener('error', () => { if (!pv.proxy) showProxyBox(t('pj.cantPlay')); }, { once: true });
    // Ses var ama görüntü çözülemiyorsa (ör. desteklenmeyen kodek) de önizleme kopyası öner
    v.addEventListener('loadedmetadata', () => { if (pv.info.video && !v.videoWidth && !pv.proxy) showProxyBox(t('pj.cantPlay')); }, { once: true });
    body.appendChild(v);
    attachMedia(which, v);
  };
  if (pv.url) playVideo(pv.url);
  else showProxyBox(t('pj.cantPlay'));
}

// İki oynatıcıyı bağla: biri oynayınca/durunca/sarılınca diğeri de (bağlantı açıksa)
let syncing = false;
function attachMedia(which, el) {
  mediaEls[which] = el;
  const other = () => mediaEls[which === 'src' ? 'out' : 'src'];
  const linked = () => settings.linkPreview !== false && other() && other().isConnected && other().tagName !== 'IMG';
  const guard = (fn) => () => { if (syncing || !linked()) return; syncing = true; try { fn(other()); } finally { setTimeout(() => (syncing = false), 50); } };
  el.addEventListener('play', guard((o) => { o.currentTime = el.currentTime; o.play().catch(() => {}); }));
  el.addEventListener('pause', guard((o) => o.pause()));
  el.addEventListener('seeked', guard((o) => { if (Math.abs(o.currentTime - el.currentTime) > 0.25) o.currentTime = el.currentTime; }));
  el.addEventListener('timeupdate', () => highlightSegment(el.currentTime, which));
}

// --- Metin (konuşma) ------------------------------------------------------------------------
async function loadTranscript() {
  const body = $('#trBody');
  transcript = null;
  const f = selected && files.get(selected);
  const showEmpty = (msg, withBtn) => {
    body.innerHTML = `<div class="tr-empty">${icon(textIcon())}<span>${esc(msg)}</span>${withBtn ? `<button class="btn sm">${icon(textIcon())}${esc(textActionLabel(false))}</button>` : ''}</div>`;
    const b = body.querySelector('button');
    if (b) b.onclick = () => window.api.pjTranscribe([f.rel]);
  };
  ocrSel = -1;
  hideOcrBoxes();
  if (!f) return showEmpty(t('pj.trPick'), false);
  const s = f.speech;
  if (!s) return showEmpty(speechOn() ? t(isImage() ? 'pj.ocrAfter' : 'pj.trAfter') : t(isImage() ? 'pj.ocrOff' : 'pj.trOff'), true);
  if (s.status === 'queued') return showEmpty(t('st.queued'), false);
  if (s.status === 'running') return showEmpty(t(isImage() ? 'pj.ocrRunning' : 'pj.trRunning', { p: Math.floor((s.progress || 0) * 100) }), false);
  if (s.status === 'error') return showEmpty(`${t('st.error')}: ${s.error}`, true);
  if (s.status === 'canceled') return showEmpty(t('st.canceled'), true);
  if (s.status === 'none') return showEmpty(noTextHint(), isImage());
  const tr = await window.api.pjTranscript(f.rel);
  if (selected !== f.rel) return;
  if (tr && tr.kind === 'ocr') return renderOcr(f.rel, tr);
  if (!tr || !(tr.segments || []).length) return showEmpty(t('pj.trNone'), true);
  transcript = { rel: f.rel, segments: tr.segments };
  const frag = document.createDocumentFragment();
  tr.segments.forEach((seg, i) => {
    const r = h(`<div class="tr-row" data-i="${i}"><span class="ts"></span><span class="lg"></span><span class="tx"></span></div>`);
    r.querySelector('.ts').textContent = fmtSec(seg.start);
    r.querySelector('.ts').title = `${fmtDur(seg.start)} – ${fmtDur(seg.end)}`;
    r.querySelector('.lg').textContent = langName(seg.lang);
    r.querySelector('.lg').title = seg.lang;
    r.querySelector('.tx').textContent = seg.text;
    r.onclick = (e) => { if (!window.getSelection().toString()) seekTo(seg.start); };
    frag.appendChild(r);
  });
  body.replaceChildren(frag);
}

// --- OCR: satır · güven · metin; satıra tıklayınca resimde konumu vurgulanır ---------------------
let ocrSel = -1;
function ocrLangNames(code) {
  return String(code || '').split('+').filter(Boolean).map((c) => langName(FORMATS.OCR_ISO[c] || c)).join(', ');
}

function renderOcr(rel, tr) {
  const body = $('#trBody');
  if (!(tr.lines || []).length) {
    body.innerHTML = `<div class="tr-empty">${icon('text')}<span>${esc(noTextHint())}</span></div>`;
    return;
  }
  transcript = { rel, ocr: tr };
  const frag = document.createDocumentFragment();
  const tools = h(`<div class="ocr-tools"><span>${esc(ocrLangNames((tr.languages || []).join('+')))}</span>
    <button class="btn sm ghost">${icon('copy')}${esc(t('pj.copyAll'))}</button></div>`);
  tools.querySelector('button').onclick = async () => { await navigator.clipboard.writeText(tr.text || tr.lines.map((l) => l.text).join('\n')); toast(t('pj.copied'), { type: 'ok' }); };
  frag.appendChild(tools);
  tr.lines.forEach((l, i) => {
    const r = h(`<div class="tr-row" data-i="${i}"><span class="ts">${i + 1}</span><span class="lg"><span class="conf ${l.conf >= 85 ? 'hi' : l.conf >= 60 ? 'mid' : 'lo'}">${LANG === 'tr' ? `%${l.conf}` : `${l.conf}%`}</span></span><span class="tx"></span></div>`);
    r.querySelector('.tx').textContent = l.text;
    r.onclick = () => {
      if (window.getSelection().toString()) return;
      body.querySelectorAll('.tr-row.now').forEach((x) => x.classList.remove('now'));
      r.classList.add('now');
      showOcrBox(i);
    };
    frag.appendChild(r);
  });
  body.replaceChildren(frag);
}

function hideOcrBoxes() { document.querySelectorAll('.ocr-box').forEach((b) => b.classList.add('hidden')); }

// OCR koordinatları kaynak resme göredir; her önizlemede resmin ekrandaki (object-fit: contain) yerine ölçeklenir
function showOcrBox(i) {
  ocrSel = i;
  const tr = transcript && transcript.ocr;
  const line = tr && tr.lines[i];
  if (!line) return;
  for (const which of ['src', 'out']) {
    const img = mediaEls[which];
    const box = pane(which).querySelector('.ocr-box');
    if (!img || !box || img.tagName !== 'IMG' || !img.naturalWidth) { if (box) box.classList.add('hidden'); continue; }
    const W = img.clientWidth;
    const H = img.clientHeight;
    const s = Math.min(W / img.naturalWidth, H / img.naturalHeight);
    const offX = img.offsetLeft + (W - img.naturalWidth * s) / 2;
    const offY = img.offsetTop + (H - img.naturalHeight * s) / 2;
    const k = img.naturalWidth / (tr.width || img.naturalWidth); // dönüştürülmüş resim küçültülmüş olabilir
    const b = line.bbox;
    Object.assign(box.style, {
      left: `${offX + b.x0 * k * s - 3}px`, top: `${offY + b.y0 * k * s - 3}px`,
      width: `${(b.x1 - b.x0) * k * s + 6}px`, height: `${(b.y1 - b.y0) * k * s + 6}px`,
    });
    box.classList.remove('hidden');
  }
}
window.addEventListener('resize', () => { if (ocrSel >= 0) showOcrBox(ocrSel); });

function seekTo(sec) {
  const els = [mediaEls.src, mediaEls.out].filter((x) => x && x.isConnected && x.tagName !== 'IMG');
  if (!els.length) return;
  const linked = settings.linkPreview !== false;
  syncing = true;
  for (const el of linked ? els : els.slice(0, 1)) { el.currentTime = sec; el.play().catch(() => {}); }
  setTimeout(() => (syncing = false), 80);
}

let lastSeg = -1;
function highlightSegment(time, which) {
  if (!transcript || !transcript.segments || (which === 'out' && mediaEls.src && !mediaEls.src.paused)) return;
  const segs = transcript.segments;
  let lo = 0;
  let hi = segs.length - 1;
  let idx = -1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (segs[m].start <= time) { idx = m; lo = m + 1; } else hi = m - 1;
  }
  if (idx >= 0 && time > segs[idx].end + 1.5) idx = -1;
  if (idx === lastSeg) return;
  lastSeg = idx;
  $('#trBody').querySelectorAll('.tr-row.now').forEach((x) => x.classList.remove('now'));
  const row = idx >= 0 && $('#trBody').querySelector(`.tr-row[data-i="${idx}"]`);
  if (row) { row.classList.add('now'); row.scrollIntoView({ block: 'nearest' }); }
}

$('#trCol [data-a="transcribe"]').onclick = () => { if (selected) window.api.pjTranscribe([selected]); };
$('#trCol [data-a="export"]').onclick = (e) => {
  if (!transcript) return toast(t('pj.trNoExport'), { type: 'err' });
  const r = e.currentTarget.getBoundingClientRect();
  const fmts = transcript.ocr ? [['txt', t('pj.fmtTxt')], ['csv', t('pj.fmtCsv')], ['json', 'JSON']]
    : [['srt', t('pj.fmtSrt')], ['vtt', t('pj.fmtVtt')], ['txt', t('pj.fmtTxt')], ['csv', t('pj.fmtCsv')], ['json', 'JSON']];
  contextMenu(r.left - 150, r.bottom + 4, fmts.map(([k, l]) => ({
    label: l, icon: 'download', action: async () => {
      const p = await window.api.pjExportTranscript(transcript.rel, k);
      if (p) toast(t('pj.trSaved'), { type: 'ok', sub: p });
    },
  })));
};

// Model / motor indirme şeridi
window.api.onSpeechDownload((x) => {
  const bar = $('#dlBar');
  if (!x) { bar.classList.add('hidden'); return; }
  bar.classList.remove('hidden');
  const what = x.what === 'engine' ? t('speech.dlEngine') : x.what === 'ocr' ? t('ocr.dl', { lang: ocrLangNames(x.lang) })
    : t('speech.dlModel', { model: t(`speech.model.${x.model}`) });
  bar.innerHTML = `<span>${esc(what)} — ${Math.floor((x.progress || 0) * 100)}%${x.total ? ` (${formatSize(x.got)} / ${formatSize(x.total)})` : ''}</span><div class="progress"><div style="width:${(x.progress || 0) * 100}%"></div></div>`;
});

// --- Durum çubuğu ----------------------------------------------------------------------------
function selectedFiles() { return [...files.values()].filter((f) => f.checked); }

function paintStatus() {
  const sel = selectedFiles();
  let done = 0;
  let err = 0;
  let active = 0;
  let sum = 0;
  for (const f of sel) {
    if (f.status === 'done') { done++; sum += 1; } else if (f.status === 'error') err++;
    else if (f.status === 'converting') { active++; sum += f.progress || 0; }
  }
  const speechActive = sel.filter((f) => f.speech && f.speech.status === 'running').length;
  $('#stTotal').innerHTML = `${icon('layers')}${esc(t('pj.stTotal', { n: sel.length }))}`;
  $('#stDone').innerHTML = done ? `${icon('check')}${esc(t('pj.stDone', { n: done }))}` : '';
  $('#stErr').innerHTML = err ? `${icon('x')}${esc(t('pj.stErr', { n: err }))}` : '';
  $('#stActive').innerHTML = active || speechActive ? `<span class="spin" style="width:11px;height:11px;border-width:1.5px"></span>${esc(t('pj.stActive', { n: active }))}${speechActive ? ' · ' + esc(t('pj.stSpeech', { n: speechActive })) : ''}` : '';
  const pct = sel.length ? sum / sel.length : 0;
  $('#stBar').style.width = `${pct * 100}%`;
  $('#stPct').textContent = sel.length ? `${Math.floor(pct * 100)}%` : '';
  $('#stOut').innerHTML = outSize ? `${icon('hdd')}${esc(t('pj.stOut', { size: '' }))}${formatSize(outSize)}` : '';
  $('#stConc').innerHTML = `${icon('bolt')}${esc(t('pj.stConc', { n: project ? project.concurrency : 2 }))}`;
  $('#stConc').title = t('pf.concurrency');
}

let outTimer = null;
function refreshOutSize() {
  clearTimeout(outTimer);
  outTimer = setTimeout(async () => { outSize = await window.api.pjOutSize(); paintStatus(); }, 300);
}

$('#stConc').onclick = async () => {
  const n = await openModal({
    title: t('pf.concurrency'), iconName: 'bolt',
    body: `<div class="field"><label>${esc(t('pf.concurrency'))}</label>
      <div class="inline"><input class="input" id="cc" type="number" min="1" max="32" value="${esc(project.concurrency)}"><div class="chips" id="ccc"></div></div>
      <small class="hint">${esc(t('pf.concurrencyHint'))}</small></div>`,
    onMount: (m) => {
      for (const v of [1, 2, 3, 4, 6, 8, 12, 16]) {
        const b = h(`<button type="button" class="chip">${v}</button>`);
        b.onclick = () => (m.querySelector('#cc').value = v);
        m.querySelector('#ccc').appendChild(b);
      }
    },
    buttons: [
      { label: t('common.cancel'), value: null },
      { label: t('common.save'), cls: 'primary', onClick: (m) => Number(m.querySelector('#cc').value) || null },
    ],
  });
  if (n) { project.concurrency = await window.api.pjSetConcurrency(n); paintStatus(); }
};

// --- Görünüm modu ve anlık görüntü --------------------------------------------------------------
function applyMode() {
  const noSource = !snap.root;
  const single = project.sourceMode === 'file';
  $('#treeCol').classList.toggle('closed', single || noSource);
  $('#splitTree').classList.toggle('closed', single || noSource);
  $('#list').classList.toggle('hidden', single || noSource);
  $('#listHead').classList.toggle('hidden', single || noSource);
  $('#single').classList.toggle('hidden', !single || noSource);
  $('#noSource').classList.toggle('hidden', !noSource);
  $('#listCol').classList.toggle('single-mode', single);
  document.querySelector('#listCol .list-filter').classList.toggle('hidden', single || noSource);
  $('#statusFilter').classList.toggle('hidden', single || noSource);
  if (noSource) {
    $('#noSource').innerHTML = `<div class="box">${icon('info')}<b>${esc(project.sourcePath ? t('pj.sourceGone') : t('pj.noSourceTitle'))}</b>
      <span>${esc(project.sourcePath ? project.sourcePath : t('pj.noSourceHint'))}</span>
      <button class="btn primary">${icon(project.sourceMode === 'file' ? 'file' : 'folder')}${esc(t('pj.pickSource'))}</button></div>`;
    $('#noSource button').onclick = changeSource;
  }
}

function applySnapshot(s) {
  snap = s;
  running = !!s.running;
  files = new Map(s.files.map((f) => [f.rel, f]));
  if (selected && !files.has(selected)) selected = null;
  if (treeFolder && ![...files.keys()].some((r) => r.startsWith(treeFolder + '/'))) treeFolder = null;
  if (project.sourceMode === 'file' && files.size) selected = [...files.keys()][0];
  if (!selected) { const first = [...files.values()].find((f) => f.checked); if (first && files.size <= 5000) selected = first.rel; }
  applyMode();
  renderTree();
  renderList();
  if (project.sourceMode === 'file') renderSingle();
  paintStatus();
  paintRun();
  loadPreviews(true);
  loadTranscript();
  refreshOutSize();
}

// --- İş olayları ----------------------------------------------------------------------------------
let listTimer = null;
window.api.onJobItems((items) => {
  let selChanged = false;
  let speechDone = false;
  for (const it of items) {
    const f = files.get(it.rel);
    if (!f) continue;
    const prevSpeech = f.speech && f.speech.status;
    Object.assign(f, { status: it.status, progress: it.progress || 0, error: it.error || '', outSize: it.outSize || 0, duration: it.duration || f.duration, speech: it.speech || null });
    if (it.rel === selected) { selChanged = true; if ((f.speech && f.speech.status) !== prevSpeech) speechDone = true; }
  }
  // Durum/ilerlemeye göre süzme ya da sıralama varsa listeyi yeniden kur (seyrek), yoksa yalnız görünen satırları çiz
  if (statusFilter !== 'all' || ['status', 'progress', 'speech', 'out'].includes(sort.key)) {
    if (!listTimer) listTimer = setTimeout(() => { listTimer = null; renderList(); }, 600);
  } else list.draw();
  tree.draw();
  if (project.sourceMode === 'file') renderSingle();
  if (selChanged) {
    loadPreviews(false);
    if (speechDone) loadTranscript();
    else if (!transcript) {
      const f = files.get(selected);
      if (f && f.speech && f.speech.status === 'running') $('#trBody .tr-empty span') && ($('#trBody .tr-empty span').textContent = t('pj.trRunning', { p: Math.floor((f.speech.progress || 0) * 100) }));
    }
  }
  paintStatus();
});

window.api.onJobState((st) => {
  running = !!st.running;
  paintRun();
});

window.api.onJobFinished((st) => {
  running = false;
  paintRun();
  refreshOutSize();
  const c = st.counts || {};
  toast(t('pj.finished'), { type: c.error ? 'err' : 'ok', sub: t('pj.finishedSub', { done: c.done || 0, total: c.total || 0, err: c.error || 0 }), timeout: 6000 });
});

window.api.onPreviewProgress(({ rel, progress }) => {
  if (rel !== selected) return;
  document.querySelectorAll('.proxy-box .progress > div').forEach((d) => (d.style.width = `${progress * 100}%`));
});

window.api.onProjectChanged((p) => {
  if (!p) return;
  const modeChanged = project.sourceMode !== p.sourceMode;
  project = p;
  paintHeader();
  if (modeChanged) applyMode();
  renderLists();
  paintStatus();
});

// --- Başlangıç --------------------------------------------------------------------------------------
window.api.pjInit().then(({ project: p, snapshot }) => {
  project = p;
  paintHeader();
  applySnapshot(snapshot);
}).catch((e) => {
  document.body.innerHTML = `<div class="empty-list">${icon('x')}${esc(e.message)}</div>`;
});
