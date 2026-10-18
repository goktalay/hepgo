'use strict';

// Site penceresi: solda yerel dosya yöneticisi (Windows), ortada sunucu, sağda aktarım ağacı.

const $ = (s) => document.querySelector(s);
const posix = {
  join: (...p) => p.join('/').replace(/\/+/g, '/'),
  dirname: (p) => { const s = p.replace(/\/+$/, ''); const i = s.lastIndexOf('/'); return i <= 0 ? '/' : s.slice(0, i); },
};
const winPath = {
  join: (dir, name) => (dir.endsWith('\\') ? dir + name : dir + '\\' + name),
  dirname: (p) => {
    const s = p.replace(/\\+$/, '');
    if (/^[A-Za-z]:$/.test(s)) return s + '\\';
    const i = s.lastIndexOf('\\');
    if (i < 0) return p;
    const d = s.slice(0, i);
    return /^[A-Za-z]:$/.test(d) ? d + '\\' : d;
  },
  isRoot: (p) => /^[A-Za-z]:\\?$/.test(p),
};

const params = new URLSearchParams(location.search);
const siteId = params.get('id');

let data = { connections: [], folders: [], settings: {} };
let site = null;
let connected = false;
let home = '/';
let remoteDir = '/';
let localDir = '';
let localItems = [];
let remoteItems = [];

// --- Ana öğeler ----------------------------------------------------------------
document.querySelectorAll('.panel-ico').forEach((el) => (el.innerHTML = icon(el.textContent.replace(/[{}]/g, ''))));
document.querySelectorAll('[data-t]').forEach((el) => (el.textContent = t(el.dataset.t)));

const colLocal = $('#colLocal');
const colRemote = $('#colRemote');
const colTransfers = $('#colTransfers');
const localPath = colLocal.querySelector('.path-input');
const remotePath = colRemote.querySelector('.path-input');

const setBtn = (el, ic, title) => { el.innerHTML = icon(ic); el.title = title; };
setBtn($('#btnLocal'), 'sidebar', t('site.toggleLocal'));
setBtn($('#btnTransfers'), 'swap', t('site.toggleTransfers'));
setBtn($('#btnSettings'), 'gear', t('app.settings'));
$('#btnReconnect').innerHTML = icon('reconnect') + esc(t('site.reconnect'));
setBtn(colLocal.querySelector('[data-a=places]'), 'drive', t('site.places'));
setBtn(colLocal.querySelector('[data-a=up]'), 'up', t('site.up'));
setBtn(colLocal.querySelector('[data-a=refresh]'), 'refresh', t('common.refresh') + ' (F5)');
setBtn(colLocal.querySelector('[data-a=mkdir]'), 'folderPlus', t('common.newFolder'));
setBtn(colRemote.querySelector('[data-a=home]'), 'home', t('site.home'));
setBtn(colRemote.querySelector('[data-a=up]'), 'up', t('site.up'));
setBtn(colRemote.querySelector('[data-a=refresh]'), 'refresh', t('common.refresh') + ' (F5)');
setBtn(colRemote.querySelector('[data-a=mkdir]'), 'folderPlus', t('common.newFolder'));
setBtn(colTransfers.querySelector('[data-a=clear]'), 'broom', t('tr.clearDone'));
setBtn(colTransfers.querySelector('[data-a=cancelAll]'), 'stop', t('tr.cancelAll'));

const paintThemeBtn = themeButton($('#btnTheme'), () => data.settings || {});
mountMastertool($('.bar-actions'));
$('#btnSettings').onclick = () => openSettings(data.settings || {});
$('#btnReconnect').onclick = () => connect();
$('#stLimit').onclick = () => openSettings(data.settings || {}, { focusSpeed: true });

// --- Dosya listeleri ------------------------------------------------------------
const localList = new FileList(colLocal.querySelector('.file-list'), {
  kind: 'local',
  onOpen: (it) => (it.isDir ? goLocal(it.path) : upload([it])),
  onUp: () => !winPath.isRoot(localDir) && goLocal(winPath.dirname(localDir)),
  onContext: localContext,
  onDropItems: ({ from, items }) => { if (from === 'remote') download(items); },
  onKey: (e, items) => {
    if (e.key === 'F5') { e.preventDefault(); loadLocal(); }
    if (e.key === 'Delete' && items.length) trashLocal(items);
    if (e.key === 'F2' && items.length === 1) renameLocal(items[0]);
  },
});

const remoteList = new FileList(colRemote.querySelector('.file-list'), {
  kind: 'remote',
  onOpen: (it) => (it.isDir ? goRemote(it.path) : download([it])),
  onUp: () => remoteDir !== '/' && goRemote(posix.dirname(remoteDir)),
  onContext: remoteContext,
  onDropItems: ({ from, items, paths }) => {
    if (from === 'local') upload(items);
    if (from === 'explorer' && paths.length) uploadPaths(paths);
  },
  onKey: (e, items) => {
    if (e.key === 'F5') { e.preventDefault(); loadRemote(true); }
    if (e.key === 'Delete' && items.length) deleteRemote(items);
    if (e.key === 'F2' && items.length === 1) renameRemote(items[0]);
  },
});

// --- Yerel panel ---------------------------------------------------------------
async function goLocal(dir, selectName) {
  localDir = dir;
  localPath.value = dir;
  await loadLocal(selectName);
  rememberDirs();
}

async function loadLocal(selectName) {
  const dir = localDir;
  try {
    const items = await window.api.localList(dir);
    if (dir !== localDir) return;
    localItems = items;
    localList.setItems(items, { canUp: !winPath.isRoot(dir) });
    if (selectName) localList.selectByName(selectName);
  } catch (err) {
    localItems = [];
    localList.canUp = !winPath.isRoot(dir);
    localList.setError(cleanErr(err));
  }
  updateStatus();
}

localPath.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') goLocal(localPath.value.trim() || localDir);
  if (e.key === 'Escape') { localPath.value = localDir; localPath.blur(); }
});

colLocal.querySelector('[data-a=up]').onclick = () => !winPath.isRoot(localDir) && goLocal(winPath.dirname(localDir));
colLocal.querySelector('[data-a=refresh]').onclick = () => loadLocal();
colLocal.querySelector('[data-a=mkdir]').onclick = () => mkdirLocal();
colLocal.querySelector('[data-a=places]').onclick = async (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  const sp = await window.api.localSpecial();
  const drives = await window.api.localDrives();
  contextMenu(r.left, r.bottom + 4, [
    { label: t('site.desktop'), icon: 'monitor', action: () => goLocal(sp.desktop) },
    { label: t('site.downloads'), icon: 'download', action: () => goLocal(sp.downloads) },
    { label: t('site.documents'), icon: 'file', action: () => goLocal(sp.documents) },
    { label: t('site.homeDir'), icon: 'home', action: () => goLocal(sp.home) },
    '-',
    ...drives.map((d) => ({ label: d, icon: 'drive', action: () => goLocal(d) })),
  ]);
};

function localContext(e, items) {
  if (!items.length) {
    contextMenu(e.clientX, e.clientY, [
      { label: t('common.newFolder'), icon: 'folderPlus', action: () => mkdirLocal() },
      { label: t('common.refresh'), icon: 'refresh', kbd: 'F5', action: () => loadLocal() },
      { label: t('site.openExplorer'), icon: 'open', action: () => window.api.localOpen(localDir) },
    ]);
    return;
  }
  const one = items.length === 1 ? items[0] : null;
  contextMenu(e.clientX, e.clientY, [
    {
      label: items.length > 1 ? t('site.uploadN', { n: items.length }) : t('site.upload'),
      icon: 'upload', disabled: !connected, action: () => upload(items),
    },
    { label: t('site.uploadTo', { dir: remoteDir }), icon: 'server', disabled: true, action: () => {} },
    '-',
    one && one.isDir ? { label: t('common.open'), icon: 'open', kbd: 'Enter', action: () => goLocal(one.path) } : null,
    one && !one.isDir ? { label: t('site.openFile'), icon: 'open', action: () => window.api.localOpen(one.path) } : null,
    one ? { label: t('site.showExplorer'), icon: 'folder', action: () => window.api.localReveal(one.path) } : null,
    one ? { label: t('common.rename'), icon: 'edit', kbd: 'F2', action: () => renameLocal(one) } : null,
    { label: t('common.copyPath'), icon: 'copy', action: () => window.api.clipboardWrite(items.map((x) => x.path).join('\n')) },
    '-',
    { label: t('site.trash'), icon: 'trash', danger: true, kbd: 'Del', action: () => trashLocal(items) },
  ]);
}

async function mkdirLocal() {
  const name = await prompt(t('common.newFolder'), { label: t('common.folderName'), okText: t('common.create'), iconName: 'folderPlus' });
  if (!name) return;
  try {
    await window.api.localMkdir(winPath.join(localDir, name));
    await loadLocal(name);
  } catch (err) { toast(t('site.mkdirFail'), { type: 'err', sub: cleanErr(err) }); }
}

async function renameLocal(it) {
  const name = await prompt(t('common.rename'), { label: t('common.newName'), value: it.name, okText: t('common.save') });
  if (!name || name === it.name) return;
  try {
    await window.api.localRename(it.path, winPath.join(localDir, name));
    await loadLocal(name);
  } catch (err) { toast(t('site.renameFail'), { type: 'err', sub: cleanErr(err) }); }
}

async function trashLocal(items) {
  const msg = items.length === 1 ? t('site.trashOne', { name: esc(items[0].name) }) : t('site.trashMany', { n: items.length });
  if (!(await confirmBox(t('site.trash'), msg, { okText: t('site.trashOk') }))) return;
  try {
    await window.api.localTrash(items.map((x) => x.path));
  } catch (err) { toast(t('site.deleteFail'), { type: 'err', sub: cleanErr(err) }); }
  await loadLocal();
}

// --- Uzak panel ----------------------------------------------------------------
async function goRemote(dir, { refresh = false, selectName } = {}) {
  remoteDir = dir || '/';
  remotePath.value = remoteDir;
  await loadRemote(refresh, selectName);
  rememberDirs();
}

async function loadRemote(refresh, selectName) {
  if (!connected) return;
  const dir = remoteDir;
  remoteList.setLoading();
  try {
    const items = await window.api.siteList(dir, !!refresh);
    if (dir !== remoteDir) return;
    remoteItems = items;
    remoteList.setItems(items, { canUp: dir !== '/' });
    if (selectName) remoteList.selectByName(selectName);
  } catch (err) {
    if (dir !== remoteDir) return;
    remoteItems = [];
    remoteList.canUp = dir !== '/';
    remoteList.setError(cleanErr(err));
  }
  updateStatus();
}

remotePath.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') goRemote(remotePath.value.trim() || '/');
  if (e.key === 'Escape') { remotePath.value = remoteDir; remotePath.blur(); }
});
colRemote.querySelector('[data-a=home]').onclick = () => goRemote(home);
colRemote.querySelector('[data-a=up]').onclick = () => remoteDir !== '/' && goRemote(posix.dirname(remoteDir));
colRemote.querySelector('[data-a=refresh]').onclick = () => loadRemote(true);
colRemote.querySelector('[data-a=mkdir]').onclick = () => mkdirRemote();

function remoteContext(e, items) {
  if (!connected) return;
  if (!items.length) {
    contextMenu(e.clientX, e.clientY, [
      { label: t('common.newFolder'), icon: 'folderPlus', action: () => mkdirRemote() },
      { label: t('common.refresh'), icon: 'refresh', kbd: 'F5', action: () => loadRemote(true) },
      { label: t('common.copyPath'), icon: 'copy', action: () => window.api.clipboardWrite(remoteDir) },
    ]);
    return;
  }
  const one = items.length === 1 ? items[0] : null;
  contextMenu(e.clientX, e.clientY, [
    {
      label: items.length > 1 ? t('site.downloadN', { n: items.length }) : t('site.download'),
      icon: 'download', action: () => download(items),
    },
    { label: t('site.downloadTo', { dir: localDir }), icon: 'monitor', disabled: true, action: () => {} },
    '-',
    one && one.isDir ? { label: t('common.open'), icon: 'open', kbd: 'Enter', action: () => goRemote(one.path) } : null,
    one ? { label: t('common.rename'), icon: 'edit', kbd: 'F2', action: () => renameRemote(one) } : null,
    { label: t('common.copyPath'), icon: 'copy', action: () => window.api.clipboardWrite(items.map((x) => x.path).join('\n')) },
    { label: t('common.newFolder'), icon: 'folderPlus', action: () => mkdirRemote() },
    '-',
    { label: t('common.delete'), icon: 'trash', danger: true, kbd: 'Del', action: () => deleteRemote(items) },
  ]);
}

async function mkdirRemote() {
  const name = await prompt(t('common.newFolder'), { label: t('common.folderName'), okText: t('common.create'), iconName: 'folderPlus' });
  if (!name) return;
  try {
    await window.api.siteMkdir(posix.join(remoteDir, name));
    await loadRemote(true, name);
  } catch (err) { toast(t('site.mkdirFail'), { type: 'err', sub: cleanErr(err) }); }
}

async function renameRemote(it) {
  const name = await prompt(t('common.rename'), { label: t('common.newName'), value: it.name, okText: t('common.save') });
  if (!name || name === it.name) return;
  try {
    await window.api.siteRename(it.path, posix.join(remoteDir, name));
    await loadRemote(true, name);
  } catch (err) { toast(t('site.renameFail'), { type: 'err', sub: cleanErr(err) }); }
}

async function deleteRemote(items) {
  const msg = items.length === 1
    ? t(items[0].isDir ? 'site.delDirOne' : 'site.delOne', { name: esc(items[0].name) })
    : t('site.delMany', { n: items.length });
  if (!(await confirmBox(t('site.deleteTitle'), msg))) return;
  const tst = toast(t('site.deleting'), { timeout: 0 });
  try {
    await window.api.siteDelete(items.map(({ path, isDir, isLink }) => ({ path, isDir, isLink })));
    toast(t('site.deleted'), { type: 'ok' });
  } catch (err) { toast(t('site.deleteFail'), { type: 'err', sub: cleanErr(err) }); }
  tst.remove();
  await loadRemote(true);
}

// --- İndir / yükle ---------------------------------------------------------------
function download(items) {
  if (!connected || !items.length) return;
  window.api.siteDownload(items.map(({ path, name, isDir, size, mtime }) => ({ path, name, isDir, size, mtime })), localDir);
  if (!colTransfers.classList.contains('closed')) return;
  setTransfersOpen(true);
}

function upload(items) {
  uploadPaths(items.map((x) => x.path));
}

function uploadPaths(paths) {
  if (!connected || !paths.length) return;
  window.api.siteUpload(paths, remoteDir);
  if (colTransfers.classList.contains('closed')) setTransfersOpen(true);
}

// --- Aktarım ağacı ----------------------------------------------------------------
$('#treeBody').dataset.empty = t('tr.empty');
const tree = new TransferTree({
  root: $('#tree'),
  cols: (data.settings || {}).trCols,
  onColsChange: (cols) => window.api.setSettings({ trCols: cols }),
  onOpen: (n) => revealNode(n),
  onStats: updateStatus,
  onKey: (_e, n) => removeOrCancel(n),
  onContext: (e, n) => {
    if (!n) {
      contextMenu(e.clientX, e.clientY, [
        { label: t('tr.clearDone'), icon: 'broom', action: clearDone },
        { label: t('tr.cancelAll'), icon: 'stop', danger: true, action: () => window.api.transferCancelAll() },
      ]);
      return;
    }
    const finished = FINISHED.includes(n.status);
    const root = tree.nodes.get(n.rootId) || n;
    const canRetry = n.status === 'error' || n.status === 'cancelled';
    contextMenu(e.clientX, e.clientY, [
      !finished ? { label: n.isDir ? t('tr.cancelDir') : t('tr.cancel'), icon: 'stop', danger: true, action: () => window.api.transferCancel(n.id) } : null,
      canRetry ? { label: t('tr.retry'), icon: 'refresh', action: () => window.api.transferRetry(n.id) } : null,
      { label: n.kind === 'download' ? t('tr.showLocal') : t('tr.showRemote'), icon: 'folder', action: () => revealNode(n) },
      n.error ? { label: t('tr.copyError'), icon: 'copy', action: () => window.api.clipboardWrite(n.error) } : null,
      '-',
      !n.parentId && finished ? { label: t('tr.remove'), icon: 'x', action: () => removeRoots([n.id]) } : null,
      FINISHED.includes(root.status) && n.parentId ? { label: t('tr.removeRoot'), icon: 'x', action: () => removeRoots([root.id]) } : null,
      { label: t('tr.clearDone'), icon: 'broom', action: clearDone },
    ]);
  },
});

// Yerel öğeyi Gezgin'de göster; uzak öğe için sunucu panelinde ilgili klasöre git
function revealNode(n) {
  if (n.kind === 'download') {
    window.api.localReveal(n.dst);
  } else {
    const dir = n.isDir ? n.dst : posix.dirname(n.dst);
    goRemote(dir, { refresh: true, selectName: n.isDir ? undefined : n.dst.split('/').pop() });
  }
}

function removeOrCancel(n) {
  if (FINISHED.includes(n.status)) { if (!n.parentId) removeRoots([n.id]); } else window.api.transferCancel(n.id);
}

async function removeRoots(ids) {
  const removed = await window.api.transferClear(ids);
  tree.remove(removed);
}

async function clearDone() {
  const removed = await window.api.transferClear();
  tree.remove(removed);
}

colTransfers.querySelector('[data-a=clear]').onclick = clearDone;
colTransfers.querySelector('[data-a=cancelAll]').onclick = async () => {
  if (!tree.stats().active) return;
  if (await confirmBox(t('tr.cancelAll'), esc(t('tr.cancelAllMsg')), { okText: t('tr.cancelAllOk') })) window.api.transferCancelAll();
};

window.api.onTransferUpdate((u) => tree.apply(u));
window.api.onTransferRootDone((r) => {
  if (r.kind === 'download') {
    if (r.dstDir === localDir) loadLocal();
    if (r.status === 'done') toast(t('tr.downloadDone'), { type: 'ok', sub: r.name });
  } else {
    if (r.dstDir === remoteDir) loadRemote(true);
    if (r.status === 'done') toast(t('tr.uploadDone'), { type: 'ok', sub: r.name });
  }
  if (r.status === 'error') toast(t(r.kind === 'download' ? 'tr.downloadFailed' : 'tr.uploadFailed', { name: r.name }), { type: 'err', sub: r.failed > 1 ? t('tr.failedFiles', { n: r.failed }) : '' });
});

// --- Durum çubuğu -------------------------------------------------------------------
function updateStatus() {
  $('#stLocal').innerHTML = `${icon('monitor')} ${esc(t('site.items', { n: localItems.length }))}`;
  $('#stRemote').innerHTML = `${icon('server')} ${esc(connected ? t('site.items', { n: remoteItems.length }) : t('site.offline'))}`;
  const s = tree.stats();
  $('#stActive').textContent = s.active ? t('tr.activeN', { n: s.active }) : '';
  $('#stDown').innerHTML = s.down ? `${icon('download')} ${esc(formatSize(s.down))}/s` : '';
  $('#stUp').innerHTML = s.up ? `${icon('upload')} ${esc(formatSize(s.up))}/s` : '';
  const badge = $('#trBadge');
  badge.textContent = s.active;
  badge.classList.toggle('hidden', !s.active);
  const st = data.settings || {};
  const lim = $('#stLimit');
  lim.innerHTML = `${icon('gauge')} ${esc(st.speedLimitOn ? t('site.limit', { v: formatSize((st.speedLimitKB || 0) * 1024) + '/s' }) : t('site.noLimit'))}`;
  lim.classList.toggle('on', !!st.speedLimitOn);
  lim.title = t('site.limitTitle');
}

// --- Paneller: genişlik, aç/kapa ------------------------------------------------------
function setLocalOpen(open, save = true) {
  colLocal.classList.toggle('closed', !open);
  $('#splitLocal').classList.toggle('hidden', !open);
  $('#btnLocal').classList.toggle('active', open);
  if (save) window.api.setSettings({ localOpen: open });
}

function setTransfersOpen(open, save = true) {
  colTransfers.classList.toggle('closed', !open);
  $('#splitTransfers').classList.toggle('hidden', !open);
  $('#btnTransfers').classList.toggle('active', open);
  if (save) window.api.setSettings({ transferOpen: open });
}

$('#btnLocal').onclick = () => setLocalOpen(colLocal.classList.contains('closed'));
$('#btnTransfers').onclick = () => setTransfersOpen(colTransfers.classList.contains('closed'));

// Ayırıcı sürükleme: sol ayırıcı yerel paneli, sağ ayırıcı aktarım panelini boyutlandırır
function makeSplitter(split, col, key, side) {
  split.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = col.getBoundingClientRect().width;
    const rtl = document.documentElement.dir === 'rtl';
    split.classList.add('active');
    document.body.classList.add('resizing-col');
    const move = (ev) => {
      let dx = ev.clientX - startX;
      if (rtl) dx = -dx;
      const max = $('#body').clientWidth - 320;
      const w = Math.max(220, Math.min(max, side === 'left' ? startW + dx : startW - dx));
      col.style.width = w + 'px';
    };
    const up = () => {
      split.classList.remove('active');
      document.body.classList.remove('resizing-col');
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      window.api.setSettings({ [key]: Math.round(col.getBoundingClientRect().width) });
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  });
}
makeSplitter($('#splitLocal'), colLocal, 'localWidth', 'left');
makeSplitter($('#splitTransfers'), colTransfers, 'transferWidth', 'right');

document.addEventListener('keydown', (e) => {
  if (document.querySelector('.modal-backdrop')) return;
  if (e.ctrlKey && e.key.toLowerCase() === 'b') { e.preventDefault(); $('#btnLocal').click(); }
  if (e.ctrlKey && e.key.toLowerCase() === 'j') { e.preventDefault(); $('#btnTransfers').click(); }
});

// --- Son klasör ---------------------------------------------------------------------
let dirTimer = null;
function rememberDirs() {
  clearTimeout(dirTimer);
  dirTimer = setTimeout(() => window.api.siteLastDir(connected ? remoteDir : null, localDir), 400);
}

// --- Bağlantı ------------------------------------------------------------------------
function cleanErr(err) {
  return String((err && err.message) || err).replace(/^Error invoking remote method '[^']+': (Error: )?/, '');
}

function setState(state) {
  connected = state === 'connected';
  const dot = $('#dot');
  dot.className = `status-dot ${state === 'connected' ? 'on' : state === 'disconnected' ? 'off' : ''}`;
  dot.title = t('site.state.' + state);
  $('#btnReconnect').classList.toggle('hidden', state !== 'disconnected');
  colRemote.classList.toggle('offline', state === 'disconnected');
  updateStatus();
}

function paintHeader() {
  if (!site) return;
  const p = { ftp: 'FTP', 'ftps-implicit': 'FTPS', 'ftps-ssl': 'FTPS', 'ftps-tls': 'FTPS', sftp: 'SFTP' }[site.protocol] || 'FTP';
  const secure = site.protocol !== 'ftp';
  document.title = `${site.name} — FTP Masters`;
  $('#siteName').textContent = site.name;
  const user = site.loginMethod === 'anonymous' ? 'anonymous' : site.username;
  $('#siteSub').textContent = `${user ? user + '@' : ''}${site.host}:${site.port}`;
  $('#siteProto').className = `tag proto ${secure ? 'secure' : ''}`;
  $('#siteProto').innerHTML = icon(secure ? 'lock' : 'globe') + esc(p);
  document.body.style.setProperty('--c', site.color || 'var(--accent)');
}

async function connect() {
  setState('connecting');
  remoteList.setLoading();
  const res = await window.api.siteOpen();
  if (!res.ok) {
    setState('disconnected');
    remoteList.canUp = false;
    remoteList.setError(t('site.connectFail', { msg: res.message }));
    toast(t('site.connectFailTitle'), { type: 'err', sub: res.message, timeout: 6000 });
    return;
  }
  setState('connected');
  home = res.home || '/';
  if (res.info) $('#siteSub').title = res.info;
  await goRemote(res.startRemote || home);
  if (!localDir) await goLocal(res.startLocal);
}

window.api.onSessionStatus(({ state }) => {
  setState(state);
  if (state === 'connected') loadRemote(false);
});

window.api.onStoreChanged((d) => {
  data = d;
  site = data.connections.find((c) => c.id === siteId) || site;
  paintHeader();
  paintThemeBtn();
  updateStatus();
});

(async () => {
  data = await window.api.getStore();
  site = data.connections.find((c) => c.id === siteId);
  const s = data.settings || {};
  colLocal.style.width = (s.localWidth || 360) + 'px';
  colTransfers.style.width = (s.transferWidth || 560) + 'px';
  setLocalOpen(s.localOpen !== false, false);
  setTransfersOpen(s.transferOpen !== false, false);
  tree.cols = (s.trCols && s.trCols.length === 4 ? s.trCols : tree.cols).slice();
  tree.applyCols();
  paintThemeBtn();
  if (!site) { remoteList.setError(t('main.errConnNotFound')); return; }
  paintHeader();
  updateStatus();
  // Yerel klasör bağlantıdan bağımsız hemen açılsın
  const startLocal = (site.rememberLastDir && site.lastLocalDir) || site.localDir || s.localDir;
  if (startLocal) goLocal(startLocal);
  await connect();
  if (!localDir) goLocal((await window.api.localSpecial()).home);
})();
