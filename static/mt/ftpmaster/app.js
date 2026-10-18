'use strict';

// Ana pencere: site kartları, klasörler, site formu (Genel / Eylemler / Tür / Seçenekler), ayarlar

const COLORS = ['#22d3ee', '#3b82f6', '#6366f1', '#a855f7', '#ec4899', '#f97316', '#fbbf24', '#34d399', '#94a3b8'];

const PROTOCOLS = {
  ftp: { port: 21, short: 'FTP', secure: false },
  'ftps-implicit': { port: 990, short: 'FTPS', secure: true },
  'ftps-ssl': { port: 21, short: 'FTPS', secure: true },
  'ftps-tls': { port: 21, short: 'FTPS', secure: true },
  sftp: { port: 22, short: 'SFTP', secure: true },
};

let data = { folders: [], connections: [], settings: {} };
let currentFolder = null;
let query = '';
let selectedId = null;

const $ = (s) => document.querySelector(s);

// --- Başlangıç ---------------------------------------------------------------
$('.search-ico').innerHTML = icon('search');
$('#btnSettings').innerHTML = icon('gear');
$('#btnSettings').title = t('app.settings');
$('#btnNewFolder').innerHTML = icon('folderPlus') + esc(t('common.newFolder'));
$('#btnNewConn').innerHTML = icon('plus') + esc(t('app.newConn'));
$('#search').placeholder = t('app.searchPh');
const paintThemeBtn = themeButton($('#btnTheme'), () => data.settings || {});
mountMastertool($('.topbar .actions'));

$('#btnSettings').onclick = () => openSettings(data.settings || {});
$('#content').addEventListener('mousedown', (e) => {
  if (!e.target.closest('.card, .new-card')) { selectedId = null; updateSelectionUI(); }
});
$('#btnNewFolder').onclick = () => newFolder();
$('#btnNewConn').onclick = () => editConnection(null);
$('#search').addEventListener('input', (e) => { query = e.target.value.trim().toLowerCase(); render(); });

document.addEventListener('keydown', (e) => {
  if (document.querySelector('.modal-backdrop')) return;
  const inInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
  if (e.ctrlKey && e.key.toLowerCase() === 'f') { e.preventDefault(); $('#search').focus(); $('#search').select(); }
  if (e.ctrlKey && e.key.toLowerCase() === 'n') { e.preventDefault(); editConnection(null); }
  if (e.key === 'Escape' && document.activeElement === $('#search')) { $('#search').value = ''; query = ''; render(); $('#search').blur(); }
  if (e.key === 'Backspace' && !inInput && currentFolder) goFolder(folderById(currentFolder)?.parentId || null);
  const sel = data.connections.find((c) => c.id === selectedId);
  if (sel && !inInput) {
    if (e.key === 'Enter') window.api.openConnection(sel.id);
    if (e.key === 'Delete') deleteConnection(sel);
    if (e.key === 'F2') editConnection(sel);
  }
});

window.api.onStoreChanged((d) => { data = d; render(); paintThemeBtn(); });

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
  // Kalıcı hatalar bir kez bildirilir
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

// Yeni sürüm bildirimi: exe yalnız hesabın kişiye özel bağlantısından indirilir
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
window.api.getStore().then((d) => { data = d; render(); paintThemeBtn(); });

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
  // Alt klasörler dahil site sayısı
  let n = data.connections.filter((c) => (c.folderId || null) === folderId).length;
  for (const sub of data.folders.filter((f) => (f.parentId || null) === folderId)) n += countIn(sub.id);
  return n;
}

function goFolder(id) {
  currentFolder = id && folderById(id) ? id : null;
  selectedId = null;
  render();
}

function updateSelectionUI() {
  document.querySelectorAll('.conn-card').forEach((x) => x.classList.toggle('selected', x.dataset.id === selectedId));
}

// --- Çizim -------------------------------------------------------------------
function render() {
  if (currentFolder && !folderById(currentFolder)) currentFolder = null;
  renderCrumbs();
  renderGrid();
  updateSelectionUI();
  const nc = data.connections.length;
  $('#stats').textContent = nc ? t('app.stats', { c: nc, f: data.folders.length }) : t('app.welcome');
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

  if (!data.connections.length && !data.folders.length) {
    const w = h(`<div class="welcome"><div class="new-card">
      <div class="plus">${icon('plus')}</div>
      <div class="lbl">${esc(t('common.new'))}</div>
      <div class="hint">${t('app.welcomeHint')}</div>
    </div></div>`);
    w.querySelector('.new-card').onclick = () => editConnection(null);
    grid.appendChild(w);
    return;
  }

  let folders;
  let conns;
  if (query) {
    folders = data.folders.filter((f) => f.name.toLowerCase().includes(query));
    conns = data.connections.filter((c) =>
      [c.name, c.host, c.username, String(c.port), c.comments, PROTOCOLS[c.protocol]?.short].some((v) => String(v || '').toLowerCase().includes(query))
    );
  } else {
    folders = data.folders.filter((f) => (f.parentId || null) === currentFolder);
    conns = data.connections.filter((c) => (c.folderId || null) === currentFolder);
  }
  folders.sort(sortByName);
  conns.sort(sortByName);

  if (folders.length) {
    grid.appendChild(h(`<div class="section-title">${esc(t('app.folders'))}</div>`));
    for (const f of folders) grid.appendChild(folderCard(f));
  }
  grid.appendChild(h(`<div class="section-title">${esc(t('app.connections'))}${conns.length ? `<span class="hint">${esc(t('app.dblHint'))}</span>` : ''}</div>`));
  for (const c of conns) grid.appendChild(connCard(c));

  if (!query) {
    const n = h(`<div class="new-card"><div class="plus">${icon('plus')}</div><div class="lbl">${esc(t('common.new'))}</div></div>`);
    n.onclick = () => editConnection(null);
    grid.appendChild(n);
  } else if (!conns.length && !folders.length) {
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
      { label: t('app.newConnHere'), icon: 'plus', action: () => editConnection(null, f.id) },
      { label: t('app.newSubfolder'), icon: 'folderPlus', action: () => newFolder(f.id) },
      '-',
      { label: t('common.rename'), icon: 'edit', action: () => renameFolder(f) },
      { label: t('common.moveEllipsis'), icon: 'move', action: () => moveDialog({ type: 'folder', item: f }) },
      '-',
      { label: t('common.delete'), icon: 'trash', danger: true, action: () => deleteFolder(f) },
    ]);
  });
  el.addEventListener('dragstart', (e) => {
    e.dataTransfer.setData('application/x-ftpm', JSON.stringify({ type: 'folder', id: f.id }));
    el.classList.add('dragging');
  });
  el.addEventListener('dragend', () => el.classList.remove('dragging'));
  makeDropTarget(el, f.id);
  return el;
}

function protoLabel(c) {
  const p = PROTOCOLS[c.protocol] || PROTOCOLS.ftp;
  return p.short;
}

function connCard(c) {
  const where = query && c.folderId ? folderPath(c.folderId).map((f) => f.name).join(' / ') : '';
  const p = PROTOCOLS[c.protocol] || PROTOCOLS.ftp;
  const user = c.loginMethod === 'anonymous' ? 'anonymous' : c.username;
  const lastDir = c.rememberLastDir ? c.lastRemoteDir : '';
  const el = h(`<div class="card conn-card ${selectedId === c.id ? 'selected' : ''}" data-id="${esc(c.id)}" draggable="true" style="--c:${esc(c.color || '#22d3ee')}">
    <div class="card-head">
      <div class="avatar">${icon(p.secure ? 'lock' : 'server')}</div>
      <div style="min-width:0;flex:1">
        <div class="card-title">${esc(c.name)}</div>
        <div class="card-sub">${user ? esc(user) + '@' : ''}${esc(c.host)}${Number(c.port) !== p.port ? ':' + esc(c.port) : ''}</div>
      </div>
    </div>
    <div class="quick">
      <button class="icon-btn" data-a="edit" title="${esc(t('common.edit'))}">${icon('edit')}</button>
      <button class="icon-btn connect" data-a="open" title="${esc(t('common.connect'))}">${icon('play')}</button>
    </div>
    <div class="card-foot">
      <span class="tag proto ${p.secure ? 'secure' : ''}">${icon(p.secure ? 'lock' : 'globe')}${esc(protoLabel(c))}</span>
      ${c.authType === 'key' && c.protocol === 'sftp' ? `<span class="tag">${icon('key')}${esc(t('app.keyTag'))}</span>` : ''}
      ${c.rememberLastDir ? `<span class="tag dir" title="${esc(t('app.lastDir'))}">${icon('history')}${esc(lastDir || t('app.lastDirTag'))}</span>`
        : c.remoteDir ? `<span class="tag dir">${icon('folder')}${esc(c.remoteDir)}</span>` : ''}
      ${where ? `<span class="tag">${icon('folder')}${esc(where)}</span>` : ''}
    </div></div>`);
  if (c.comments) el.title = c.comments;
  el.addEventListener('click', (e) => {
    const a = e.target.closest('[data-a]')?.dataset.a;
    if (a === 'open') return window.api.openConnection(c.id);
    if (a === 'edit') return editConnection(c);
    selectedId = c.id;
    updateSelectionUI();
  });
  el.addEventListener('dblclick', (e) => {
    if (e.target.closest('[data-a]')) return;
    window.api.openConnection(c.id);
  });
  el.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    selectedId = c.id;
    updateSelectionUI();
    contextMenu(e.clientX, e.clientY, [
      { label: t('common.connect'), icon: 'play', kbd: 'Enter', action: () => window.api.openConnection(c.id) },
      '-',
      { label: t('common.edit'), icon: 'edit', kbd: 'F2', action: () => editConnection(c) },
      { label: t('app.duplicate'), icon: 'copy', action: () => window.api.duplicateConnection(c.id) },
      { label: t('app.moveToFolder'), icon: 'move', action: () => moveDialog({ type: 'conn', item: c }) },
      c.rememberLastDir && (c.lastRemoteDir || c.lastLocalDir) ? { label: t('app.resetLastDir'), icon: 'history', action: () => window.api.resetLastDir(c.id) } : null,
      '-',
      { label: t('common.delete'), icon: 'trash', danger: true, kbd: 'Del', action: () => deleteConnection(c) },
    ]);
  });
  el.addEventListener('dragstart', (e) => {
    e.dataTransfer.setData('application/x-ftpm', JSON.stringify({ type: 'conn', id: c.id }));
    el.classList.add('dragging');
  });
  el.addEventListener('dragend', () => el.classList.remove('dragging'));
  return el;
}

// Sürükle-bırak: site/klasörü bir klasöre (veya üst seviyeye) taşı
function makeDropTarget(el, folderId) {
  let depth = 0;
  el.addEventListener('dragenter', (e) => {
    if (!e.dataTransfer.types.includes('application/x-ftpm')) return;
    depth++;
    el.classList.add('drop');
  });
  el.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; el.classList.remove('drop'); } });
  el.addEventListener('dragover', (e) => {
    if (e.dataTransfer.types.includes('application/x-ftpm')) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
  });
  el.addEventListener('drop', async (e) => {
    e.preventDefault();
    depth = 0;
    el.classList.remove('drop');
    const d = JSON.parse(e.dataTransfer.getData('application/x-ftpm') || '{}');
    if (d.type === 'conn') {
      await window.api.moveConnection(d.id, folderId);
      toast(t('app.connMoved'), { type: 'ok', sub: folderId ? folderById(folderId).name : t('app.all') });
    } else if (d.type === 'folder' && d.id !== folderId) {
      const ok = await window.api.moveFolder(d.id, folderId);
      if (!ok) toast(t('app.folderIntoSelf'), { type: 'err' });
    }
  });
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
  const ok = await confirmBox(t('app.deleteFolder'), t('app.deleteFolderMsg', { name: esc(f.name) }) + (n ? t('app.deleteFolderConns', { n }) : ''));
  if (ok) await window.api.deleteFolder(f.id);
}

function folderOptions(selected, excludeId) {
  // Hiyerarşik klasör listesi (select için)
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
  const current = type === 'conn' ? item.folderId : item.parentId;
  const target = await openModal({
    title: t('app.moveTitle', { name: item.name }), iconName: 'move',
    body: `<div class="field"><label>${esc(t('app.targetFolder'))}</label><select class="input" id="mv">${folderOptions(current, type === 'folder' ? item.id : null)}</select></div>`,
    buttons: [
      { label: t('common.cancel'), value: null },
      { label: t('common.move'), cls: 'primary', onClick: (m) => ({ v: m.querySelector('#mv').value || null }) },
    ],
  });
  if (!target) return;
  if (type === 'conn') await window.api.moveConnection(item.id, target.v);
  else if (!(await window.api.moveFolder(item.id, target.v))) toast(t('app.folderIntoSelf'), { type: 'err' });
}

async function deleteConnection(c) {
  const ok = await confirmBox(t('app.deleteConn'), t('app.deleteConnMsg', { name: esc(c.name), target: esc(c.host) }));
  if (ok) { await window.api.deleteConnection(c.id); if (selectedId === c.id) selectedId = null; }
}

// --- Site formu ----------------------------------------------------------------
const sel = (list, v) => list.map(([k, l]) => `<option value="${k}" ${String(k) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('');

function timezoneOptions(v) {
  const list = [[0, t('type.tzNone')]];
  for (let i = -12; i <= 14; i++) if (i) list.push([i, `${i > 0 ? '+' : '−'}${Math.abs(i)} ${t('type.tzHours')}`]);
  return sel(list, v || 0);
}

async function editConnection(conn, folderId) {
  const isNew = !conn;
  const s = data.settings || {};
  const c = conn || {
    name: '', host: '', protocol: 'ftp', port: 21, username: '', loginMethod: 'normal', authType: 'password', keyPath: '', comments: '',
    folderId: folderId ?? currentFolder, color: COLORS[data.connections.length % COLORS.length],
    remoteDir: '', localDir: '', rememberLastDir: true, cacheMode: 'session', uploadCase: 'preserve',
    transferType: 'global', timezone: 0,
    siteOptions: 'global', retryAttempts: s.retryAttempts ?? 3, retryDelay: s.retryDelay ?? 10, maxConcurrent: s.maxConcurrent || 4,
    conflict: s.conflict || 'overwrite', encoding: 'auto',
  };
  let color = c.color || COLORS[0];
  let authType = c.authType || 'password';
  let loginMethod = c.loginMethod || 'normal';
  let testedHostKey = null;
  let portTouched = !isNew;

  const body = h(`<div class="site-form">
    <div class="tabs" id="f-tabs">
      <button data-tab="general" class="on">${icon('server')}${esc(t('form.tabGeneral'))}</button>
      <button data-tab="actions">${icon('folder')}${esc(t('form.tabActions'))}</button>
      <button data-tab="type">${icon('swap')}${esc(t('form.tabType'))}</button>
      <button data-tab="options">${icon('gear')}${esc(t('form.tabOptions'))}</button>
    </div>

    <section class="tab-panel" data-panel="general">
      <div class="field"><label>${esc(t('form.name'))}</label><input class="input" id="f-name" placeholder="${esc(t('form.namePh'))}" value="${esc(c.name)}"></div>
      <div class="row c-3-1">
        <div class="field"><label>${esc(t('form.host'))}</label><input class="input" id="f-host" placeholder="${esc(t('form.hostPh'))}" value="${esc(c.host)}" spellcheck="false"></div>
        <div class="field"><label>${esc(t('form.port'))}</label><input class="input" id="f-port" type="number" min="1" max="65535" value="${esc(c.port || 21)}"></div>
      </div>
      <div class="field">
        <label>${esc(t('form.loginMethod'))}</label>
        <div class="seg" id="f-login"><button data-v="normal">${esc(t('form.loginNormal'))}</button><button data-v="anonymous">${esc(t('form.loginAnon'))}</button></div>
      </div>
      <div id="cred-fields" style="display:grid;gap:14px">
        <div class="row c-1-1">
          <div class="field"><label>${esc(t('form.user'))}</label><input class="input" id="f-user" value="${esc(c.username)}" spellcheck="false" autocomplete="off"></div>
          <div class="field" id="pw-field"><label>${esc(t('form.password'))}</label>
            <div class="pw-wrap"><input class="input" id="f-pass" type="password" placeholder="${c.hasPassword ? esc(t('form.pwSaved')) : ''}" autocomplete="new-password">
            <button class="icon-btn" id="f-eye" type="button" title="${esc(t('common.show'))}">${icon('eye')}</button></div>
          </div>
        </div>
        <div class="field sftp-only" id="auth-field">
          <label>${esc(t('form.auth'))}</label>
          <div class="seg" id="f-auth"><button data-v="password">${esc(t('form.password'))}</button><button data-v="key">${esc(t('form.privateKey'))}</button></div>
        </div>
        <div id="key-fields" class="hidden" style="display:grid;gap:14px">
          <div class="field"><label>${esc(t('form.keyFile'))}</label>
            <div class="key-wrap"><input class="input" id="f-key" value="${esc(c.keyPath)}" placeholder="C:\\Users\\…\\.ssh\\id_ed25519" spellcheck="false"><button class="btn" id="f-keypick" type="button">${esc(t('common.choose'))}</button></div>
          </div>
          <div class="field"><label>${esc(t('form.passphrase'))}</label><input class="input" id="f-phrase" type="password" placeholder="${esc(c.hasPassphrase ? t('form.passSaved') : t('form.passEmpty'))}"></div>
        </div>
      </div>
      <div class="row c-1-1">
        <div class="field"><label>${esc(t('form.folder'))}</label><select class="input" id="f-folder">${folderOptions(c.folderId)}</select></div>
        <div class="field"><label>${esc(t('form.color'))}</label><div class="colors" id="f-colors" style="height:36px;align-items:center"></div></div>
      </div>
      <div class="field"><label>${esc(t('form.comments'))}</label><textarea class="input plain" id="f-notes" rows="2">${esc(c.comments)}</textarea></div>
    </section>

    <section class="tab-panel hidden" data-panel="actions">
      <div class="field"><label>${esc(t('form.remoteDir'))}</label><input class="input" id="f-rdir" value="${esc(c.remoteDir)}" placeholder="/public_html" spellcheck="false"></div>
      <div class="field"><label>${esc(t('form.localDir'))}</label>
        <div class="key-wrap"><input class="input" id="f-ldir" value="${esc(c.localDir)}" placeholder="${esc(t('form.localDirPh'))}" spellcheck="false"><button class="btn" id="f-ldirpick" type="button">${icon('folder')}</button></div></div>
      <label class="check"><input type="checkbox" id="f-last" ${c.rememberLastDir ? 'checked' : ''}>
        <span>${esc(t('form.lastDir'))}<small>${esc(t('form.lastDirHint'))}${c.lastRemoteDir ? ` ${esc(t('form.lastDirNow'))} <code>${esc(c.lastRemoteDir)}</code>` : ''}</small></span></label>
      <div class="field"><label>${esc(t('form.cache'))}</label><select class="input" id="f-cache">${sel([['session', t('form.cacheSession')], ['always', t('form.cacheAlways')], ['never', t('form.cacheNever')]], c.cacheMode)}</select></div>
      <div class="field"><label>${esc(t('form.uploadCase'))}</label><select class="input" id="f-case">${sel([['preserve', t('form.casePreserve')], ['lower', t('form.caseLower')], ['upper', t('form.caseUpper')]], c.uploadCase)}</select></div>
    </section>

    <section class="tab-panel hidden" data-panel="type">
      <div class="row c-3-1">
        <div class="field"><label>${esc(t('type.protocol'))}</label><select class="input" id="f-proto">${sel([
          ['ftp', t('type.ftp')], ['ftps-implicit', t('type.ftpsImplicit')], ['ftps-ssl', t('type.ftpsSsl')], ['ftps-tls', t('type.ftpsTls')], ['sftp', t('type.sftp')],
        ], c.protocol)}</select></div>
        <div class="field"><label>${esc(t('form.port'))}</label><input class="input" id="f-port2" type="number" min="1" max="65535" value="${esc(c.port || 21)}"></div>
      </div>
      <div class="proto-note" id="f-proto-note"></div>
      <div class="row c-1-1">
        <div class="field"><label>${esc(t('type.transferType'))}</label><select class="input" id="f-ttype">${sel([
          ['global', t('type.useGlobal', { v: (TRANSFER_TYPES().find((x) => x[0] === (s.transferType || 'binary')) || [])[1] })], ...TRANSFER_TYPES(),
        ], c.transferType || 'global')}</select></div>
        <div class="field ftp-only"><label>${esc(t('type.dataConn'))}</label><select class="input" disabled><option>${esc(t('type.passive'))}</option></select></div>
      </div>
      <div class="field"><label>${esc(t('type.timezone'))}</label><select class="input" id="f-tz">${timezoneOptions(c.timezone)}</select>
        <small class="hint">${esc(t('type.timezoneHint'))}</small></div>
    </section>

    <section class="tab-panel hidden" data-panel="options">
      <div class="field"><label>${esc(t('opt.siteOptions'))}</label><select class="input" id="f-siteopt">${sel([['global', t('opt.useGlobal')], ['custom', t('opt.custom')]], c.siteOptions)}</select></div>
      <div class="row c-1-1">
        <div class="field"><label>${esc(t('opt.retry'))}</label><input class="input custom-opt" id="f-retry" type="number" min="0" max="99" value="${esc(c.retryAttempts ?? 3)}"></div>
        <div class="field"><label>${esc(t('opt.retryDelay'))}</label><input class="input custom-opt" id="f-delay" type="number" min="0" max="3600" value="${esc(c.retryDelay ?? 10)}"></div>
      </div>
      <div class="row c-1-1">
        <div class="field"><label>${esc(t('opt.maxConcurrent'))}</label><input class="input custom-opt" id="f-conc" type="number" min="1" max="20" value="${esc(c.maxConcurrent || 4)}"></div>
        <div class="field"><label>${esc(t('opt.conflict'))}</label><select class="input custom-opt" id="f-conflict">${options(CONFLICT_OPTS(), c.conflict || 'overwrite')}</select></div>
      </div>
      <div class="field ftp-only"><label>${esc(t('opt.encoding'))}</label>
        <div class="seg" id="f-enc"><button data-v="utf8">UTF-8</button><button data-v="ascii">ASCII</button><button data-v="auto">${esc(t('opt.encAuto'))}</button></div></div>
    </section>

    <div class="test-result" id="f-result"></div>
  </div>`);

  const q = (s2) => body.querySelector(s2);

  // Sekmeler
  body.querySelectorAll('#f-tabs button').forEach((b) => (b.onclick = () => {
    body.querySelectorAll('#f-tabs button').forEach((x) => x.classList.toggle('on', x === b));
    body.querySelectorAll('.tab-panel').forEach((p) => p.classList.toggle('hidden', p.dataset.panel !== b.dataset.tab));
  }));

  // Port alanı iki sekmede de var; birbirine bağlı
  const ports = [q('#f-port'), q('#f-port2')];
  ports.forEach((p) => p.addEventListener('input', () => { portTouched = true; ports.forEach((x) => { if (x !== p) x.value = p.value; }); }));

  const setLogin = (v) => {
    loginMethod = v;
    body.querySelectorAll('#f-login button').forEach((b) => b.classList.toggle('on', b.dataset.v === v));
    q('#cred-fields').classList.toggle('hidden', v === 'anonymous');
  };
  body.querySelectorAll('#f-login button').forEach((b) => (b.onclick = () => setLogin(b.dataset.v)));

  const setAuth = (v) => {
    authType = v;
    body.querySelectorAll('#f-auth button').forEach((b) => b.classList.toggle('on', b.dataset.v === v));
    const key = v === 'key' && q('#f-proto').value === 'sftp';
    q('#key-fields').classList.toggle('hidden', !key);
    q('#pw-field').classList.toggle('hidden', key);
  };
  body.querySelectorAll('#f-auth button').forEach((b) => (b.onclick = () => setAuth(b.dataset.v)));

  let encoding = c.encoding || 'auto';
  const setEnc = (v) => { encoding = v; body.querySelectorAll('#f-enc button').forEach((b) => b.classList.toggle('on', b.dataset.v === v)); };
  body.querySelectorAll('#f-enc button').forEach((b) => (b.onclick = () => setEnc(b.dataset.v)));
  setEnc(encoding);

  const onProto = () => {
    const p = q('#f-proto').value;
    const sftp = p === 'sftp';
    body.querySelectorAll('.sftp-only').forEach((x) => x.classList.toggle('hidden', !sftp));
    body.querySelectorAll('.ftp-only').forEach((x) => x.classList.toggle('hidden', sftp));
    if (sftp && loginMethod === 'anonymous') setLogin('normal');
    q('#f-login').parentElement.classList.toggle('hidden', sftp);
    q('#f-proto-note').innerHTML = `${icon(PROTOCOLS[p].secure ? 'lock' : 'info')}<span>${esc(t('type.note.' + p))}</span>`;
    q('#f-proto-note').classList.toggle('secure', PROTOCOLS[p].secure);
    setAuth(authType);
  };
  q('#f-proto').addEventListener('change', () => {
    // Port elle değiştirilmediyse protokolün varsayılan portunu kullan
    const p = q('#f-proto').value;
    const prevDefault = Object.values(PROTOCOLS).some((x) => String(x.port) === ports[0].value);
    if (!portTouched || prevDefault) ports.forEach((x) => (x.value = PROTOCOLS[p].port));
    onProto();
  });
  setLogin(loginMethod);
  onProto();

  const syncSiteOpt = () => {
    const custom = q('#f-siteopt').value === 'custom';
    body.querySelectorAll('.custom-opt').forEach((x) => (x.disabled = !custom));
    if (!custom) {
      q('#f-retry').value = s.retryAttempts ?? 3;
      q('#f-delay').value = s.retryDelay ?? 10;
      q('#f-conc').value = s.maxConcurrent || 4;
      q('#f-conflict').value = s.conflict || 'overwrite';
    }
  };
  q('#f-siteopt').onchange = syncSiteOpt;
  syncSiteOpt();

  q('#f-eye').onclick = () => {
    const p = q('#f-pass');
    p.type = p.type === 'password' ? 'text' : 'password';
    q('#f-eye').innerHTML = icon(p.type === 'password' ? 'eye' : 'eyeOff');
  };
  q('#f-keypick').onclick = async () => { const p = await window.api.pickKeyFile(); if (p) q('#f-key').value = p; };
  q('#f-ldirpick').onclick = async () => { const p = await window.api.pickFolder(q('#f-ldir').value); if (p) q('#f-ldir').value = p; };

  const colorsEl = q('#f-colors');
  for (const col of COLORS) {
    const b = h(`<button type="button" style="--c:${col}" class="${col === color ? 'on' : ''}"></button>`);
    b.onclick = () => { color = col; colorsEl.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b)); };
    colorsEl.appendChild(b);
  }

  const readForm = () => {
    const protocol = q('#f-proto').value;
    return {
      id: c.id,
      name: q('#f-name').value.trim() || q('#f-host').value.trim(),
      host: q('#f-host').value.trim(),
      port: Number(ports[0].value) || PROTOCOLS[protocol].port,
      protocol,
      loginMethod: protocol === 'sftp' ? 'normal' : loginMethod,
      username: q('#f-user').value.trim(),
      authType: protocol === 'sftp' ? authType : 'password',
      password: authType === 'password' || protocol !== 'sftp' ? q('#f-pass').value : '',
      keyPath: protocol === 'sftp' && authType === 'key' ? q('#f-key').value.trim() : '',
      passphrase: protocol === 'sftp' && authType === 'key' ? q('#f-phrase').value : '',
      comments: q('#f-notes').value,
      folderId: q('#f-folder').value || null,
      color,
      remoteDir: q('#f-rdir').value.trim(),
      localDir: q('#f-ldir').value.trim(),
      rememberLastDir: q('#f-last').checked,
      cacheMode: q('#f-cache').value,
      uploadCase: q('#f-case').value,
      transferType: q('#f-ttype').value,
      timezone: Number(q('#f-tz').value) || 0,
      siteOptions: q('#f-siteopt').value,
      retryAttempts: Number(q('#f-retry').value),
      retryDelay: Number(q('#f-delay').value),
      maxConcurrent: Number(q('#f-conc').value),
      conflict: q('#f-conflict').value,
      encoding,
      testedHostKey,
    };
  };

  const goTab = (name) => body.querySelector(`#f-tabs button[data-tab="${name}"]`).click();

  const validate = () => {
    const f = readForm();
    let ok = true;
    const mark = (id, bad) => { q(id).classList.toggle('invalid', bad); if (bad) ok = false; };
    mark('#f-host', !f.host);
    mark('#f-user', f.loginMethod !== 'anonymous' && !f.username);
    if (f.protocol === 'sftp' && f.authType === 'key') mark('#f-key', !f.keyPath);
    if (!ok) goTab('general');
    return ok;
  };

  const showResult = (cls, html) => {
    const r = q('#f-result');
    r.className = `test-result show ${cls}`;
    r.innerHTML = html;
  };

  const runTest = async (btn) => {
    if (!validate()) return false;
    btn.disabled = true;
    showResult('', `<span class="spin" style="color:var(--accent);margin-top:2px"></span><div>${esc(t('form.connecting'))}</div>`);
    const res = await window.api.testConnection(readForm());
    btn.disabled = false;
    if (res.ok) {
      testedHostKey = res.fingerprint || null;
      const lines = [];
      if (res.info) lines.push(esc(res.info));
      if (res.home) lines.push(esc(t('form.homeDir', { dir: res.home })));
      if (!res.remoteDirOk) lines.push(`<span style="color:var(--warn)">${esc(t('form.remoteDirMissing'))}</span>`);
      showResult('ok', `${icon('check')}<div><b>${esc(t('form.testOk'))}</b> · ${res.ms} ms${lines.length ? '<br>' + lines.join('<br>') : ''}
        ${res.fingerprint ? `<div class="fp">${esc(t('form.hostKey', { fp: res.fingerprint }))}</div>` : ''}</div>`);
    } else {
      showResult('err', `${icon('x')}<div><b>${esc(t('form.testFail'))}</b><br>${esc(res.message)}</div>`);
    }
    return false;
  };

  const save = async (andConnect) => {
    if (!validate()) return false;
    const id = await window.api.saveConnection(readForm());
    toast(isNew ? t('form.saved') : t('form.changesSaved'), { type: 'ok', sub: q('#f-name').value || q('#f-host').value });
    if (andConnect) window.api.openConnection(id);
    return true;
  };

  await openModal({
    title: isNew ? t('form.titleNew') : t('form.titleEdit', { name: c.name }),
    iconName: 'server',
    width: 640,
    body,
    buttons: [
      { label: t('form.test'), icon: 'bolt', left: true, onClick: (_m, btn) => runTest(btn) },
      { label: t('common.cancel'), cls: 'ghost', value: null },
      { label: t('form.saveConnect'), onClick: () => save(true) },
      { label: t('common.save'), cls: 'primary', onClick: () => save(false) },
    ],
  });
}
