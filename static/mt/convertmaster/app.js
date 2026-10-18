'use strict';

// Ana pencere: proje kartları, proje klasörleri, Yeni (proje formu), ayarlar

let data = { folders: [], projects: [], settings: {} };
let stats = {};
let currentFolder = null;
let query = '';
let selectedId = null;

const $ = (s) => document.querySelector(s);

// --- Başlangıç ---------------------------------------------------------------
$('.search-ico').innerHTML = icon('search');
$('#btnSettings').innerHTML = icon('gear');
$('#btnSettings').title = t('app.settings');
$('#btnNewFolder').innerHTML = icon('folderPlus') + esc(t('common.newFolder'));
$('#btnNew').innerHTML = icon('plus') + esc(t('common.new'));
$('#btnNew').title = t('app.newProject') + ' (Ctrl+N)';
$('#search').placeholder = t('app.searchPh');
const paintThemeBtn = themeButton($('#btnTheme'), () => data.settings || {});
mountMastertool($('.topbar .actions'));

$('#btnSettings').onclick = () => openSettings(data.settings || {});
$('#content').addEventListener('mousedown', (e) => {
  if (!e.target.closest('.card, .new-card')) { selectedId = null; updateSelectionUI(); }
});
$('#btnNewFolder').onclick = () => newFolder();
$('#btnNew').onclick = () => newProject();
$('#search').addEventListener('input', (e) => { query = e.target.value.trim().toLowerCase(); render(); });

document.addEventListener('keydown', (e) => {
  if (document.querySelector('.modal-backdrop')) return;
  const inInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
  if (e.ctrlKey && e.key.toLowerCase() === 'f') { e.preventDefault(); $('#search').focus(); $('#search').select(); }
  if (e.ctrlKey && e.key.toLowerCase() === 'n') { e.preventDefault(); newProject(); }
  if (e.key === 'Escape' && document.activeElement === $('#search')) { $('#search').value = ''; query = ''; render(); $('#search').blur(); }
  if (e.key === 'Backspace' && !inInput && currentFolder) goFolder(folderById(currentFolder)?.parentId || null);
  const sel = data.projects.find((c) => c.id === selectedId);
  if (sel && !inInput) {
    if (e.key === 'Enter') window.api.openProject(sel.id);
    if (e.key === 'Delete') deleteProject(sel);
    if (e.key === 'F2') editExisting(sel);
  }
});

window.api.onStoreChanged((d) => { data = d; render(); paintThemeBtn(); });
window.api.onProjectStats((s) => { stats = s; render(); });

// --- Hesap rozeti ve senkron durumu ---------------------------------------------
let lastErrorShown = null;
onAcct((st) => {
  const b = $('#btnAccount');
  const name = (st.user && (st.user.name || st.user.email)) || st.email || '?';
  b.querySelector('.ac-avatar').textContent = name.trim().slice(0, 1).toUpperCase();
  const s = !st.syncEnabled || st.state === 'off' ? 'off' : st.state || 'idle';
  b.className = `account-chip s-${s}`;
  b.querySelector('.ac-sync').innerHTML = s === 'syncing' ? '<span class="spin"></span>' : icon(['off', 'offline', 'error'].includes(s) ? 'cloudOff' : 'cloud');
  b.title = `${(st.user && st.user.email) || st.email || ''}\n${syncText(st)}`;
  if (st.state === 'error' && st.error !== lastErrorShown) {
    lastErrorShown = st.error;
    toast(syncText(st), { type: 'err', timeout: 9000 });
  }
  if (st.state === 'ok') lastErrorShown = null;
});

$('#btnAccount').onclick = (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  contextMenu(r.right - 260, r.bottom + 6, [
    { label: (acct.user && acct.user.email) || acct.email || '', icon: 'user', disabled: true, action: () => {} },
    { label: syncText(acct), icon: acct.syncEnabled ? 'cloud' : 'cloudOff', disabled: true, action: () => {} },
    '-',
    { label: t('acct.syncNow'), icon: 'refresh', disabled: !acct.syncEnabled, action: () => window.api.syncNow() },
    { label: t('acct.myAccount'), icon: 'open', action: () => window.api.openWeb('account') },
    { label: t('app.settings'), icon: 'gear', action: () => openSettings(data.settings || {}) },
    '-',
    { label: t('acct.logout'), icon: 'logout', danger: true, action: logout },
  ]);
};

// Yeni sürüm bildirimi: exe hesabın kişiye özel bağlantısından indirilir
window.api.onUpdateAvailable(({ version }) => {
  const bar = $('#updateBar');
  bar.innerHTML = `${icon('download')}<span>${esc(t('update.available', { version }))} — ${esc(t('update.hint'))}</span>
    <button class="btn sm primary" data-a="open">${esc(t('update.open'))}</button>
    <button class="icon-btn" data-a="close" title="${esc(t('common.cancel'))}">${icon('x')}</button>`;
  bar.classList.remove('hidden');
  bar.querySelector('[data-a="open"]').onclick = () => window.api.openWeb('account');
  bar.querySelector('[data-a="close"]').onclick = () => bar.classList.add('hidden');
});

window.api.onLibraryBackup((file) => toast(t('acct.backupNotice'), { sub: file, timeout: 12000 }));
Promise.all([window.api.getStore(), window.api.projectStats()]).then(([d, s]) => { data = d; stats = s; render(); paintThemeBtn(); });

// --- Yardımcılar -------------------------------------------------------------
const folderById = (id) => data.folders.find((f) => f.id === id);
const sortByName = (a, b) => a.name.localeCompare(b.name, LANG, { sensitivity: 'base' });

function folderPath(id) {
  const out = [];
  let f = folderById(id);
  while (f) { out.unshift(f); f = folderById(f.parentId); }
  return out;
}

function countIn(folderId) {
  let n = data.projects.filter((c) => (c.folderId || null) === folderId).length;
  for (const sub of data.folders.filter((f) => (f.parentId || null) === folderId)) n += countIn(sub.id);
  return n;
}

function goFolder(id) {
  currentFolder = id && folderById(id) ? id : null;
  selectedId = null;
  render();
}

function updateSelectionUI() {
  document.querySelectorAll('.proj-card').forEach((x) => x.classList.toggle('selected', x.dataset.id === selectedId));
}

// --- Çizim -------------------------------------------------------------------
function render() {
  if (currentFolder && !folderById(currentFolder)) currentFolder = null;
  renderCrumbs();
  renderGrid();
  updateSelectionUI();
  const n = data.projects.length;
  $('#stats').textContent = n ? t('app.stats', { c: n, f: data.folders.length }) : t('app.welcome');
}

function renderCrumbs() {
  const el = $('#crumbs');
  el.innerHTML = '';
  if (query) {
    el.appendChild(h(`<span class="crumb current">${icon('search')} ${esc(t('app.results', { q: query }))}</span>`));
    return;
  }
  const parts = [{ id: null, name: t('app.all') }, ...folderPath(currentFolder)];
  parts.forEach((p, i) => {
    const last = i === parts.length - 1;
    const c = h(`<span class="crumb ${last ? 'current' : ''}">${i === 0 ? icon('home') : icon('folder')}${esc(p.name)}</span>`);
    if (!last) {
      c.onclick = () => goFolder(p.id);
      makeDropTarget(c, p.id);
    }
    el.appendChild(c);
    if (!last) el.appendChild(h(`<span class="crumb-sep">${icon('chevronRight')}</span>`));
  });
}

function renderGrid() {
  const grid = $('#grid');
  grid.innerHTML = '';

  if (!data.projects.length && !data.folders.length) {
    const w = h(`<div class="welcome"><div class="new-card">
      <div class="plus">${icon('plus')}</div>
      <div class="lbl">${esc(t('common.new'))}</div>
      <div class="hint">${t('app.welcomeHint')}</div>
    </div></div>`);
    w.querySelector('.new-card').onclick = () => newProject();
    grid.appendChild(w);
    return;
  }

  let folders;
  let projects;
  if (query) {
    folders = data.folders.filter((f) => f.name.toLowerCase().includes(query));
    projects = data.projects.filter((c) =>
      [c.name, c.sourcePath, c.targetExt, (c.sourceExts || []).join(' '), t(`type.${c.type}`)].some((v) => String(v || '').toLowerCase().includes(query))
    );
  } else {
    folders = data.folders.filter((f) => (f.parentId || null) === currentFolder);
    projects = data.projects.filter((c) => (c.folderId || null) === currentFolder);
  }
  folders.sort(sortByName);
  projects.sort(sortByName);

  if (folders.length) {
    grid.appendChild(h(`<div class="section-title">${esc(t('app.folders'))}</div>`));
    for (const f of folders) grid.appendChild(folderCard(f));
  }
  grid.appendChild(h(`<div class="section-title">${esc(t('app.projects'))}${projects.length ? `<span class="hint">${esc(t('app.dblHint'))}</span>` : ''}</div>`));
  for (const c of projects) grid.appendChild(projectCard(c));

  if (!query) {
    const n = h(`<div class="new-card"><div class="plus">${icon('plus')}</div><div class="lbl">${esc(t('common.new'))}</div></div>`);
    n.onclick = () => newProject();
    grid.appendChild(n);
  } else if (!projects.length && !folders.length) {
    grid.appendChild(h(`<div class="empty-note" style="grid-column:1/-1">${esc(t('app.noMatch'))}</div>`));
  }
}

function folderCard(f) {
  const n = countIn(f.id);
  const el = h(`<div class="card folder-card" draggable="true">
    <div class="avatar">${icon('folder')}</div>
    <div style="min-width:0">
      <div class="card-title">${esc(f.name)}</div>
      <div class="card-sub">${esc(t('app.folderCount', { n }))}</div>
    </div></div>`);
  el.addEventListener('dblclick', () => { $('#search').value = ''; query = ''; goFolder(f.id); });
  el.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    contextMenu(e.clientX, e.clientY, [
      { label: t('common.open'), icon: 'open', action: () => goFolder(f.id) },
      { label: t('app.newProjectHere'), icon: 'plus', action: () => newProject(f.id) },
      { label: t('app.newSubfolder'), icon: 'folderPlus', action: () => newFolder(f.id) },
      '-',
      { label: t('common.rename'), icon: 'edit', action: () => renameFolder(f) },
      { label: t('common.moveEllipsis'), icon: 'move', action: () => moveDialog({ type: 'folder', item: f }) },
      '-',
      { label: t('common.delete'), icon: 'trash', danger: true, action: () => deleteFolder(f) },
    ]);
  });
  el.addEventListener('dragstart', (e) => {
    e.dataTransfer.setData('application/x-cvm', JSON.stringify({ type: 'folder', id: f.id }));
    el.classList.add('dragging');
  });
  el.addEventListener('dragend', () => el.classList.remove('dragging'));
  makeDropTarget(el, f.id);
  return el;
}

const shortPath = (p) => {
  if (!p) return '';
  const parts = p.split(/[\\/]/).filter(Boolean);
  return parts.length > 3 ? `…\\${parts.slice(-2).join('\\')}` : p;
};

function projectCard(c) {
  const T = FORMATS.TYPES[c.type] || FORMATS.TYPES.video;
  const color = T.color;
  const where = query && c.folderId ? folderPath(c.folderId).map((f) => f.name).join(' / ') : '';
  const st = stats[c.id] || {};
  const src = (c.sourceExts || []).length === T.source.length ? t('app.allExts') : (c.sourceExts || []).map((x) => x.toUpperCase()).join(', ');
  const el = h(`<div class="card proj-card ${selectedId === c.id ? 'selected' : ''}" data-id="${esc(c.id)}" draggable="true" style="--c:${color}">
    <div class="card-head">
      <div class="avatar">${icon(TYPE_ICONS[c.type] || 'video')}</div>
      <div style="min-width:0;flex:1">
        <div class="card-title">${esc(c.name)}</div>
        <div class="card-sub" title="${esc(c.sourcePath)}">${c.sourcePath ? esc(shortPath(c.sourcePath)) : `<span style="color:var(--warn)">${esc(t('app.noSource'))}</span>`}</div>
      </div>
    </div>
    <div class="quick">
      <button class="icon-btn" data-a="edit" title="${esc(t('app.projectSettings'))}">${icon('gear')}</button>
      <button class="icon-btn connect" data-a="open" title="${esc(t('common.open'))}">${icon('play')}</button>
    </div>
    <div class="conv"><span class="ext" title="${esc(src)}">${esc(c.sourceMode === 'file' && c.sourcePath ? FORMATS.extOf(c.sourcePath).toUpperCase() : src)}</span>${icon('arrowRight')}<span class="ext to">${esc((c.targetExt || '').toUpperCase())}</span></div>
    <div class="card-foot">
      <span class="tag" title="${esc(c.sourceMode === 'file' ? t('pf.modeFile') : t('pf.modeFolder'))}">${icon(c.sourceMode === 'file' ? 'file' : 'folder')}${esc(c.sourceMode === 'file' ? t('pf.modeFile') : t('pf.modeFolder'))}</span>
      ${st.running ? `<span class="tag run"><span class="spin" style="width:10px;height:10px;border-width:1.5px;color:var(--accent)"></span>${esc(t('app.running'))}</span>` : ''}
      ${st.done ? `<span class="tag ok" title="${esc(t('app.doneCount', { n: st.done }))}">${icon('check')}${st.done}</span>` : ''}
      ${st.error ? `<span class="tag err" title="${esc(t('app.errorCount', { n: st.error }))}">${icon('x')}${st.error}</span>` : ''}
      ${c.type !== 'image' && c.speech && c.speech.enabled ? `<span class="tag" title="${esc(t('pf.speechAsk'))}">${icon('mic')}</span>` : ''}
      ${c.type === 'image' && c.ocr && c.ocr.enabled ? `<span class="tag" title="${esc(t('pf.ocrAsk'))}">${icon('text')}</span>` : ''}
      ${where ? `<span class="tag">${icon('folder')}${esc(where)}</span>` : ''}
    </div></div>`);
  el.addEventListener('click', (e) => {
    const a = e.target.closest('[data-a]')?.dataset.a;
    if (a === 'open') return window.api.openProject(c.id);
    if (a === 'edit') return editExisting(c);
    selectedId = c.id;
    updateSelectionUI();
  });
  el.addEventListener('dblclick', (e) => {
    if (e.target.closest('[data-a]')) return;
    window.api.openProject(c.id);
  });
  el.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    selectedId = c.id;
    updateSelectionUI();
    contextMenu(e.clientX, e.clientY, [
      { label: t('common.open'), icon: 'play', kbd: 'Enter', action: () => window.api.openProject(c.id) },
      '-',
      { label: t('app.projectSettings'), icon: 'gear', kbd: 'F2', action: () => editExisting(c) },
      { label: t('app.duplicate'), icon: 'copy', action: () => window.api.duplicateProject(c.id) },
      { label: t('app.moveToFolder'), icon: 'move', action: () => moveDialog({ type: 'project', item: c }) },
      '-',
      { label: t('app.clearOutputs'), icon: 'broom', disabled: !st.done, action: () => clearOutputs(c) },
      '-',
      { label: t('common.delete'), icon: 'trash', danger: true, kbd: 'Del', action: () => deleteProject(c) },
    ]);
  });
  el.addEventListener('dragstart', (e) => {
    e.dataTransfer.setData('application/x-cvm', JSON.stringify({ type: 'project', id: c.id }));
    el.classList.add('dragging');
  });
  el.addEventListener('dragend', () => el.classList.remove('dragging'));
  return el;
}

// Sürükle-bırak: proje/klasörü bir klasöre (veya üst seviyeye) taşı
function makeDropTarget(el, folderId) {
  let depth = 0;
  el.addEventListener('dragenter', (e) => {
    if (!e.dataTransfer.types.includes('application/x-cvm')) return;
    depth++;
    el.classList.add('drop');
  });
  el.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; el.classList.remove('drop'); } });
  el.addEventListener('dragover', (e) => {
    if (e.dataTransfer.types.includes('application/x-cvm')) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
  });
  el.addEventListener('drop', async (e) => {
    e.preventDefault();
    depth = 0;
    el.classList.remove('drop');
    const d = JSON.parse(e.dataTransfer.getData('application/x-cvm') || '{}');
    if (d.type === 'project') {
      await window.api.moveProject(d.id, folderId);
      toast(t('app.projectMoved'), { type: 'ok', sub: folderId ? folderById(folderId).name : t('app.all') });
    } else if (d.type === 'folder' && d.id !== folderId) {
      const ok = await window.api.moveFolder(d.id, folderId);
      if (!ok) toast(t('app.folderIntoSelf'), { type: 'err' });
    }
  });
}

// --- Projeler ------------------------------------------------------------------
async function newProject(folderId = currentFolder) {
  const id = await editProject(null, { folderId: typeof folderId === 'string' ? folderId : currentFolder, folders: data.folders, settings: data.settings });
  if (id) {
    toast(t('app.projectSaved'), { type: 'ok', sub: t('app.dblHint') });
    selectedId = id;
  }
}

async function editExisting(c) {
  const id = await editProject(c, { folders: data.folders, settings: data.settings });
  if (id) toast(t('common.saved'), { type: 'ok' });
}

async function deleteProject(c) {
  const ok = await confirmBox(t('app.deleteProject'), t('app.deleteProjectMsg', { name: esc(c.name) }));
  if (ok) { await window.api.deleteProject(c.id); if (selectedId === c.id) selectedId = null; }
}

async function clearOutputs(c) {
  const r = await clearOutputsDialog(t('app.clearOutputs'), t('app.clearOutputsMsg', { name: esc(c.name) }), { speech: c.type !== 'image' });
  if (!r) return;
  await window.api.clearProjectOutputs(c.id, r.transcripts);
  toast(t('set.clearedConverted'), { type: 'ok' });
}

// --- Klasör işlemleri ----------------------------------------------------------
async function newFolder(parentId = currentFolder) {
  const name = await prompt(t('common.newFolder'), { label: t('common.folderName'), placeholder: t('app.folderPh'), okText: t('common.create'), iconName: 'folderPlus' });
  if (name) await window.api.saveFolder({ name, parentId: typeof parentId === 'string' ? parentId : currentFolder });
}

async function renameFolder(f) {
  const name = await prompt(t('app.renameFolder'), { label: t('common.folderName'), value: f.name, okText: t('common.save') });
  if (name) await window.api.saveFolder({ id: f.id, name });
}

async function deleteFolder(f) {
  const n = countIn(f.id);
  const ok = await confirmBox(t('app.deleteFolder'), t('app.deleteFolderMsg', { name: esc(f.name) }) + (n ? t('app.deleteFolderProjects', { n }) : ''));
  if (ok) await window.api.deleteFolder(f.id);
}

function folderOptions(selected, excludeId) {
  const out = [`<option value="">${esc(t('app.rootFolder'))}</option>`];
  const walk = (parentId, depth) => {
    for (const f of data.folders.filter((x) => (x.parentId || null) === parentId).sort(sortByName)) {
      if (f.id === excludeId) continue;
      out.push(`<option value="${f.id}" ${f.id === selected ? 'selected' : ''}>${'&nbsp;&nbsp;&nbsp;'.repeat(depth)}${esc(f.name)}</option>`);
      walk(f.id, depth + 1);
    }
  };
  walk(null, 1);
  return out.join('');
}

async function moveDialog({ type, item }) {
  const current = type === 'project' ? item.folderId : item.parentId;
  const target = await openModal({
    title: t('app.moveTitle', { name: item.name }), iconName: 'move',
    body: `<div class="field"><label>${esc(t('app.targetFolder'))}</label><select class="input" id="mv">${folderOptions(current, type === 'folder' ? item.id : null)}</select></div>`,
    buttons: [
      { label: t('common.cancel'), value: null },
      { label: t('common.move'), cls: 'primary', onClick: (m) => ({ v: m.querySelector('#mv').value || null }) },
    ],
  });
  if (!target) return;
  if (type === 'project') await window.api.moveProject(item.id, target.v);
  else if (!(await window.api.moveFolder(item.id, target.v))) toast(t('app.folderIntoSelf'), { type: 'err' });
}
