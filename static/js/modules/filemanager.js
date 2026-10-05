// Dosya Yöneticisi (Kişisel): Windows Gezgini benzeri klasör/dosya yönetimi + paylaşım.
// Sol kenar çubuğu: "Paylaşılanlar" düğmesi + klasör ağacı. Sağ ana bölme: içerik ızgarası.
// Yalnızca sahibi düzenler; paylaşılan öğeler yetkiye (Görüntüleme/Düzenleme) göre açılır.
import { api, upload } from '../api.js';
import { icons } from '../icons.js';
import { clear, confirmDialog, fmtDateTime, h, modal, onLeave, pageHead, segmented, svgIcon, toast, toastError } from '../ui.js';

// Dosya boyutu: 1.2 MB, 340 KB …
function fmtSize(bytes) {
  if (bytes === null || bytes === undefined) return '';
  if (bytes < 1024) return `${bytes} B`;
  const u = ['KB', 'MB', 'GB', 'TB'];
  let n = bytes / 1024, i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
}

const PERM_LABEL = { view: 'Görüntüleme', edit: 'Düzenleme' };

// Dosya baytlarının indirme/önizleme ucu
const fileUrl = id => `/api/fm/download/${id}`;

// Dosya türü: uzantı (ve mime) → ikon/önizleme sınıfı
function fileKind(name, mime) {
  const ext = (name || '').split('.').pop().toLowerCase();
  if (['xls', 'xlsx', 'xlsm', 'csv'].includes(ext)) return 'excel';
  if (['doc', 'docx'].includes(ext)) return 'word';
  if (['ppt', 'pptx'].includes(ext)) return 'ppt';
  if (ext === 'pdf') return 'pdf';
  if (['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'svg'].includes(ext)) return 'image';
  if (['mp4', 'webm', 'mov', 'mkv', 'avi'].includes(ext)) return 'video';
  if (['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac'].includes(ext)) return 'audio';
  if (['zip', 'rar', '7z', 'tar', 'gz', 'bz2'].includes(ext)) return 'archive';
  // uzantı tanınmazsa mime türüne bak
  const m = (mime || '').toLowerCase();
  if (m.startsWith('image/')) return 'image';
  if (m.startsWith('video/')) return 'video';
  if (m.startsWith('audio/')) return 'audio';
  if (m === 'application/pdf') return 'pdf';
  return 'file';
}
const KIND_ICON = {
  excel: 'fileExcel', word: 'fileWord', ppt: 'filePpt', pdf: 'filePdf',
  video: 'fileVideo', audio: 'fileAudio', archive: 'fileArchive', file: 'file',
};

// SheetJS (xlsx) tembel yükleyici — yalnızca Excel önizlemesinde, bir kez
let xlsxLib;
function loadXLSX() {
  return xlsxLib ??= new Promise((resolve, reject) => {
    if (window.XLSX) return resolve(window.XLSX);
    const s = document.createElement('script');
    s.src = '/static/vendor/xlsx/xlsx.full.min.js';
    s.onload = () => resolve(window.XLSX);
    s.onerror = () => { xlsxLib = null; reject(new Error('Tablo bileşeni yüklenemedi')); };
    document.head.append(s);
  });
}

export async function render(view, params, ctx) {
  // ---------- durum ----------
  let treeNodes = [];                 // GET /tree → [{id,name,parent_id}]
  const expanded = new Set();         // açık (genişletilmiş) klasör id'leri
  let mode = 'folder';                // 'folder' | 'shared'
  let curParent = null;               // açık klasör id'si (null = kök)
  let curData = null;                 // son /list yanıtı (path, folders, files, can_edit)

  // Başlangıç görünümü (derin bağlantı): #/my-files/shared → paylaşılanlar, #/my-files/f/<id> → klasör
  if (params?.[0] === 'shared') mode = 'shared';
  else if (params?.[0] === 'f' && params[1]) curParent = Number(params[1]);

  // ---------- iskelet ----------
  const sharedBtn = h('button', { class: 'fm-shared-btn', type: 'button' },
    svgIcon(icons.share), h('span', null, 'Paylaşılanlar'));
  sharedBtn.addEventListener('click', () => openShared());
  const treeBox = h('div', { class: 'fm-tree' });
  const sidebar = h('aside', { class: 'fm-side' }, sharedBtn,
    h('div', { class: 'fm-side-h' }, 'Klasörlerim'), treeBox);
  const main = h('section', { class: 'fm-main' });
  // Araç çubuğu düğmeleri başlıkta (alt-modül seçicisinin yerinde); açık klasöre göre etkin/pasif olur
  const fileInput = h('input', { type: 'file', multiple: true, hidden: true });
  fileInput.addEventListener('change', () => { if (fileInput.files.length) doUpload([...fileInput.files]); fileInput.value = ''; });
  const newBtn = h('button', { class: 'btn', type: 'button', disabled: true }, '＋ Yeni Klasör');
  newBtn.addEventListener('click', () => newFolder());
  const upBtn = h('button', { class: 'btn primary', type: 'button', disabled: true }, svgIcon(icons.upload), ' Yükle');
  upBtn.addEventListener('click', () => fileInput.click());
  const headTools = h('div', { class: 'head-right fm-headtools' }, newBtn, upBtn, fileInput);
  clear(view, pageHead('Dosya Yöneticisi', { back: '#/', sub: 'Dosyalarım ve paylaşılanlar', right: headTools }),
    h('div', { class: 'fm-wrap' }, sidebar, main));

  // ---------- ağaç ----------
  async function loadTree() {
    try { treeNodes = (await api.get('/api/fm/tree')).nodes || []; } catch { treeNodes = []; }
    drawTree();
  }
  function childrenOf(pid) { return treeNodes.filter(n => (n.parent_id ?? null) === (pid ?? null)).sort((a, b) => a.name.localeCompare(b.name, 'tr')); }
  function hasChildren(id) { return treeNodes.some(n => n.parent_id === id); }

  function treeRow(node, depth) {
    const kids = hasChildren(node.id);
    const open = expanded.has(node.id);
    const chev = h('button', { class: `fm-chev ${kids ? '' : 'none'} ${open ? 'open' : ''}`, type: 'button', 'aria-label': open ? 'Daralt' : 'Genişlet' },
      kids ? '▸' : '');
    const row = h('div', {
      class: `fm-tnode ${mode === 'folder' && curParent === node.id ? 'active' : ''}`,
      style: { paddingLeft: `${8 + depth * 16}px` }, title: node.name,
    }, chev, h('span', { class: 'fm-tico' }, svgIcon(open ? icons.folderOpen : icons.folder)), h('span', { class: 'fm-tname' }, node.name));
    chev.addEventListener('click', e => { e.stopPropagation(); if (!kids) return; open ? expanded.delete(node.id) : expanded.add(node.id); drawTree(); });
    row.addEventListener('click', () => openFolder(node.id));
    const wrap = h('div', { class: 'fm-tbranch' }, row);
    if (open && kids) wrap.append(...childrenOf(node.id).map(c => treeRow(c, depth + 1)));
    return wrap;
  }
  function drawTree() {
    const rootRow = h('div', {
      class: `fm-tnode fm-troot ${mode === 'folder' && curParent === null ? 'active' : ''}`, style: { paddingLeft: '8px' },
    }, h('span', { class: 'fm-chev none' }), h('span', { class: 'fm-tico' }, svgIcon(icons.folderOpen)), h('span', { class: 'fm-tname' }, 'Dosyalarım'));
    rootRow.addEventListener('click', () => openFolder(null));
    clear(treeBox, rootRow, ...childrenOf(null).map(n => treeRow(n, 1)));
    sharedBtn.classList.toggle('active', mode === 'shared');
  }

  // Bir klasöre giden tüm ataları açık hale getir (derin bağlantı / taşımadan sonra)
  function expandAncestors(id) {
    let node = treeNodes.find(n => n.id === id);
    while (node && node.parent_id != null) { expanded.add(node.parent_id); node = treeNodes.find(n => n.id === node.parent_id); }
  }

  // ---------- klasör görünümü ----------
  async function openFolder(id) {
    mode = 'folder'; curParent = id;
    if (id != null) expandAncestors(id);
    drawTree();
    clear(main, h('div', { class: 'empty' }, 'Yükleniyor…'));
    let data;
    try { data = await api.get(`/api/fm/list?parent=${id ?? ''}`); } catch (e) { clear(main, h('div', { class: 'card empty' }, e.message)); return; }
    curData = data;
    drawFolder();
  }

  function crumbs() {
    const path = curData.path || [];
    const el = h('nav', { class: 'fm-crumbs', 'aria-label': 'Yol' });
    const root = h('a', { class: `fm-crumb ${curParent === null ? 'on' : ''}`, href: 'javascript:void 0' }, 'Dosyalarım');
    root.addEventListener('click', e => { e.preventDefault(); openFolder(null); });
    el.append(root);
    path.forEach((c, i) => {
      el.append(h('span', { class: 'fm-sep' }, '›'));
      const a = h('a', { class: `fm-crumb ${i === path.length - 1 ? 'on' : ''}`, href: 'javascript:void 0', title: c.name }, c.name);
      a.addEventListener('click', e => { e.preventDefault(); openFolder(c.id); });
      el.append(a);
    });
    return el;
  }

  function drawFolder() {
    const canEdit = !!curData.can_edit;
    newBtn.disabled = upBtn.disabled = !canEdit;   // başlıktaki düğmeler açık klasöre göre
    // içerik ızgarası
    const folders = curData.folders || [], files = curData.files || [];
    const grid = h('div', { class: 'fm-grid' });
    if (!folders.length && !files.length) grid.append(h('div', { class: 'fm-empty' }, 'Bu klasör boş.'));
    folders.forEach(f => grid.append(itemCard(f, 'folder', canEdit)));
    files.forEach(f => grid.append(itemCard(f, 'file', canEdit)));

    clear(main, crumbs(), grid);
  }

  // Klasör ya da dosya kartı
  function itemCard(it, kind, canEdit) {
    const isFolder = kind === 'folder';
    const fk = isFolder ? null : fileKind(it.name, it.mime);
    const card = h('div', { class: `fm-item ${kind} ${isFolder ? '' : `k-${fk}`} ${it.shared ? 'shared' : ''}`, tabindex: '0', title: it.name });
    // İkon: klasör → sarı; resim → küçük önizleme; diğer → tür ikonu
    let ico;
    if (isFolder) ico = h('div', { class: 'fm-item-ico' }, svgIcon(icons.folderYellow));
    else if (fk === 'image') ico = h('div', { class: 'fm-item-ico' }, h('img', { src: fileUrl(it.id), loading: 'lazy', alt: it.name }));
    else ico = h('div', { class: 'fm-item-ico' }, svgIcon(icons[KIND_ICON[fk] || 'file']));
    const name = h('div', { class: 'fm-item-name' }, it.name);
    const meta = h('div', { class: 'fm-item-meta' }, isFolder ? 'Klasör' : fmtSize(it.size));
    if (it.shared) {
      // Tıklanabilir paylaşım rozeti → paylaşım ayarlarını açar
      const badge = h('button', { class: 'fm-badge', type: 'button', title: 'Paylaşımı düzenle', 'aria-label': 'Paylaşımı düzenle' }, svgIcon(icons.share));
      badge.addEventListener('click', e => { e.stopPropagation(); shareDialog(it, kind); });
      card.append(badge);
    }
    card.append(ico, name, meta, itemMenu(it, kind, canEdit));
    const open = () => { if (isFolder) openFolder(it.id); else previewFile(it); };
    card.addEventListener('dblclick', open);
    card.addEventListener('keydown', e => { if (e.key === 'Enter') open(); });
    // tek tık klasörü açar (dosyada çift tık önizleme açar)
    if (isFolder) card.addEventListener('click', e => { if (!e.target.closest('.fm-menu')) open(); });
    return card;
  }

  // ⋯ eylem menüsü
  function itemMenu(it, kind, canEdit) {
    const isFolder = kind === 'folder';
    const menu = h('div', { class: 'dropdown fm-menu-pop', hidden: true });
    const act = (label, fn) => { const b = h('button', { type: 'button', onclick: e => { e.stopPropagation(); menu.hidden = true; fn(); } }, label); return b; };
    if (!isFolder) menu.append(act('İndir', () => downloadFile(it)));
    if (canEdit) {
      menu.append(act('Paylaş', () => shareDialog(it, kind)));
      menu.append(act('Yeniden Adlandır', () => renameItem(it, kind)));
      menu.append(act('Taşı', () => moveItem(it, kind)));
      menu.append(act('Sil', () => deleteItem(it, kind)));
    }
    if (!menu.children.length) return null;
    const btn = h('button', { class: 'icon-btn sm fm-menu-btn', type: 'button', 'aria-haspopup': 'menu', 'aria-label': 'İşlemler' }, '⋯');
    const wrap = h('div', { class: 'fm-menu' }, btn, menu);
    btn.addEventListener('click', e => { e.stopPropagation(); closeMenus(); menu.hidden = !menu.hidden; });
    return wrap;
  }
  function closeMenus() { main.querySelectorAll('.fm-menu-pop').forEach(m => { m.hidden = true; }); }
  document.addEventListener('click', closeMenus);
  onLeave(() => document.removeEventListener('click', closeMenus));

  // ---------- eylemler ----------
  async function newFolder() {
    const inp = h('input', { class: 'input', placeholder: 'Klasör adı', maxlength: 120 });
    modal({
      title: 'Yeni Klasör', body: h('div', { class: 'field' }, h('label', null, 'Ad'), inp),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'Oluştur', class: 'primary', onClick: async () => {
        const name = inp.value.trim();
        if (!name) { toast('Klasör adı girin', 'err'); return true; }
        await api.post('/api/fm/folder', { parent_id: curParent, name });
        toast('Klasör oluşturuldu');
        await loadTree();
        if (mode === 'folder') await openFolder(curParent);
      } }],
    });
  }

  async function doUpload(files) {
    const total = files.length;
    let done = 0;
    for (const file of files) {
      try {
        const fd = new FormData();
        fd.append('parent_id', curParent == null ? '' : String(curParent));
        fd.append('file', file);
        await upload('/api/fm/upload', fd);
        done++;
        toast(total > 1 ? `${file.name} yüklendi (${done}/${total})` : `${file.name} yüklendi`);
      } catch (e) { toastError(e); }
    }
    if (mode === 'folder') await openFolder(curParent);
  }

  function renameItem(it, kind) {
    const inp = h('input', { class: 'input', value: it.name, maxlength: 200 });
    modal({
      title: kind === 'folder' ? 'Klasörü Yeniden Adlandır' : 'Dosyayı Yeniden Adlandır',
      body: h('div', { class: 'field' }, h('label', null, 'Yeni ad'), inp),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        const name = inp.value.trim();
        if (!name) { toast('Ad girin', 'err'); return true; }
        await patchNode(it.id, { name });
        toast('Yeniden adlandırıldı');
        await loadTree();
        if (mode === 'folder') await openFolder(curParent);
      } }],
    });
  }

  function moveItem(it, kind) {
    let target = null;    // seçilen hedef klasör id (null = kök)
    const picker = h('div', { class: 'fm-move-tree' });
    const movingId = kind === 'folder' ? it.id : null;
    // taşınacak klasörün kendisi ve altları hedef olamaz
    const banned = new Set();
    if (movingId != null) { banned.add(movingId); const collect = p => treeNodes.filter(n => n.parent_id === p).forEach(c => { banned.add(c.id); collect(c.id); }); collect(movingId); }
    const drawPick = () => {
      const node = (n, depth) => {
        const disabled = banned.has(n.id);
        const row = h('div', { class: `fm-move-node ${target === n.id ? 'on' : ''} ${disabled ? 'disabled' : ''}`, style: { paddingLeft: `${8 + depth * 16}px` } },
          h('span', { class: 'fm-tico' }, svgIcon(icons.folder)), h('span', null, n.name));
        if (!disabled) row.addEventListener('click', () => { target = n.id; drawPick(); });
        return [row, ...treeNodes.filter(c => c.parent_id === n.id).sort((a, b) => a.name.localeCompare(b.name, 'tr')).flatMap(c => node(c, depth + 1))];
      };
      const rootRow = h('div', { class: `fm-move-node ${target === null ? 'on' : ''}`, style: { paddingLeft: '8px' } },
        h('span', { class: 'fm-tico' }, svgIcon(icons.folderOpen)), h('span', null, 'Dosyalarım (kök)'));
      rootRow.addEventListener('click', () => { target = null; drawPick(); });
      clear(picker, rootRow, ...treeNodes.filter(n => n.parent_id == null).sort((a, b) => a.name.localeCompare(b.name, 'tr')).flatMap(n => node(n, 1)));
    };
    drawPick();
    modal({
      title: `Taşı: ${it.name}`, body: h('div', null, h('div', { class: 'hint' }, 'Hedef klasörü seçin'), picker),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'Taşı', class: 'primary', onClick: async () => {
        await patchNode(it.id, { parent_id: target });
        toast('Taşındı');
        await loadTree();
        if (mode === 'folder') await openFolder(curParent);
      } }],
    });
  }

  async function deleteItem(it, kind) {
    const ok = await confirmDialog(kind === 'folder' ? 'Klasörü sil' : 'Dosyayı sil',
      `"${it.name}" silinsin mi?${kind === 'folder' ? ' İçindeki tüm öğeler de silinir.' : ''}`, { okLabel: 'Sil', danger: true });
    if (!ok) return;
    try {
      await api.del(`/api/fm/node/${it.id}`);
      toast('Silindi');
      await loadTree();
      if (mode === 'folder') await openFolder(curParent);
    } catch (e) { toastError(e); }
  }

  function downloadFile(it) {
    // İndirme ucuna yönlendir (dosya baytları) — tarayıcı indirmeyi başlatır
    const a = h('a', { href: fileUrl(it.id), download: it.name, style: { display: 'none' } });
    document.body.append(a); a.click(); a.remove();
  }

  // ---------- dosya önizleme penceresi ----------
  function previewFile(it) {
    const fk = fileKind(it.name, it.mime);
    const url = fileUrl(it.id);
    const body = h('div', { class: 'fm-prev' });
    // Her önizlemede "İndir" eylemi
    const dlBtn = { label: 'İndir', class: 'primary', onClick: () => { downloadFile(it); return true; } };

    if (fk === 'image') {
      body.append(h('img', { src: url, alt: it.name, class: 'fm-prev-img' }));
    } else if (fk === 'pdf') {
      body.append(h('iframe', { src: url, class: 'fm-prev-pdf', title: it.name }));
    } else if (fk === 'video') {
      body.append(h('video', { src: url, controls: true, playsinline: true, class: 'fm-prev-media' }));
    } else if (fk === 'audio') {
      body.append(h('audio', { src: url, controls: true, class: 'fm-prev-audio' }));
    } else if (fk === 'excel') {
      body.append(h('div', { class: 'empty' }, 'Yükleniyor…'));
      previewExcel(it, body);
    } else {
      body.append(h('div', { class: 'fm-prev-msg' },
        h('div', null, 'Bu dosya türü tarayıcıda önizlenemiyor.'),
        h('button', { class: 'btn primary', type: 'button', style: { marginTop: '12px' }, onclick: () => downloadFile(it) }, 'İndir')));
    }

    modal({ title: it.name, wide: true, body, actions: ['spacer', { label: 'Kapat' }, dlBtn] });
  }

  // Excel/CSV → SheetJS ile HTML tabloya dönüştür (sayfa sekmeleriyle)
  async function previewExcel(it, body) {
    let XLSX;
    try { XLSX = await loadXLSX(); } catch (e) { clear(body, h('div', { class: 'empty' }, e.message)); return; }
    let wb;
    try {
      const buf = await (await fetch(fileUrl(it.id), { credentials: 'same-origin' })).arrayBuffer();
      wb = XLSX.read(buf, { type: 'array' });
    } catch { clear(body, h('div', { class: 'empty' }, 'Tablo okunamadı.')); return; }
    const names = wb.SheetNames || [];
    if (!names.length) { clear(body, h('div', { class: 'empty' }, 'Tablo boş.')); return; }
    const tabBar = h('div', { class: 'fm-xl-tabs' });
    const sheetBox = h('div', { class: 'fm-xl' });
    const showSheet = name => {
      sheetBox.innerHTML = XLSX.utils.sheet_to_html(wb.Sheets[name]);   // yalnızca <table> üretir (script çalıştırmaz)
      [...tabBar.children].forEach(b => b.classList.toggle('on', b.dataset.name === name));
    };
    if (names.length > 1) {
      names.forEach(name => {
        const b = h('button', { class: 'fm-xl-tab', type: 'button' }, name);
        b.dataset.name = name;
        b.addEventListener('click', () => showSheet(name));
        tabBar.append(b);
      });
      clear(body, tabBar, sheetBox);
    } else {
      clear(body, sheetBox);
    }
    showSheet(names[0]);
  }

  // PATCH yardımcı (api.js'te PATCH yok)
  async function patchNode(id, body) {
    const res = await fetch(`/api/fm/node/${id}`, { method: 'PATCH', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || `İşlem başarısız (${res.status})`); }
    return res.json().catch(() => ({}));
  }

  // ---------- paylaşım penceresi ----------
  async function shareDialog(it, kind) {
    let users = [], roles = ctx?.meta?.roles || [];
    try { users = await api.get('/api/voice/users'); } catch { users = []; }
    const mine = ctx?.user?.id;
    users = users.filter(u => u.id !== mine);

    let tab = 'user';                  // 'user' | 'role'
    let perm = 'view';                 // seçilen yetki
    const chosenUsers = new Set();
    const chosenRoles = new Set();
    let shares = [];

    const listBox = h('div', { class: 'fm-share-list' });
    const search = h('input', { class: 'input', placeholder: 'Ara…', type: 'search' });
    const curBox = h('div', { class: 'fm-share-cur' });

    const drawList = () => {
      const term = search.value.trim().toLocaleLowerCase('tr');
      if (tab === 'user') {
        const rows = users.filter(u => !term || (u.full_name || '').toLocaleLowerCase('tr').includes(term));
        clear(listBox, rows.length ? rows.map(u => {
          const cb = h('input', { type: 'checkbox', checked: chosenUsers.has(u.id) });
          cb.addEventListener('change', () => { cb.checked ? chosenUsers.add(u.id) : chosenUsers.delete(u.id); });
          return h('label', { class: 'fm-share-row' }, cb, h('span', { class: 'grow' }, u.full_name || u.username || `#${u.id}`));
        }) : h('div', { class: 'empty small' }, 'Kullanıcı bulunamadı'));
      } else {
        const rows = roles.filter(r => !term || r.toLocaleLowerCase('tr').includes(term));
        clear(listBox, rows.length ? rows.map(r => {
          const cb = h('input', { type: 'checkbox', checked: chosenRoles.has(r) });
          cb.addEventListener('change', () => { cb.checked ? chosenRoles.add(r) : chosenRoles.delete(r); });
          return h('label', { class: 'fm-share-row' }, cb, h('span', { class: 'grow' }, r));
        }) : h('div', { class: 'empty small' }, 'Rol bulunamadı'));
      }
    };
    search.addEventListener('input', drawList);

    const drawCur = () => {
      clear(curBox, h('div', { class: 'fm-share-cur-h' }, 'Mevcut paylaşımlar'),
        shares.length ? shares.map(s => h('div', { class: 'fm-share-cur-row' },
          h('span', { class: 'grow' }, s.target_name || (s.target_type === 'role' ? s.target_role : `#${s.target_user_id}`),
            h('span', { class: `badge ${s.perm === 'edit' ? 'blue' : ''}`, style: { marginLeft: '6px' } }, PERM_LABEL[s.perm] || s.perm)),
          h('button', { class: 'x-btn sm', type: 'button', title: 'Paylaşımı kaldır', onclick: async () => {
            try { await api.del(`/api/fm/share/${s.id}`); shares = shares.filter(x => x.id !== s.id); drawCur(); toast('Paylaşım kaldırıldı'); } catch (e) { toastError(e); }
          } }, '×')))
          : h('div', { class: 'empty small' }, 'Henüz paylaşılmadı'));
    };

    const permSeg = segmented([['view', 'Görüntüleme'], ['edit', 'Düzenleme']], perm, v => { perm = v; });
    const tabSeg = segmented([['user', 'Kullanıcılar'], ['role', 'Roller']], tab, v => { tab = v; drawList(); });

    drawList();

    modal({
      title: `Paylaş: ${it.name}`, wide: true,
      body: h('div', { class: 'fm-share' },
        tabSeg, search, listBox,
        h('div', { class: 'field' }, h('label', null, 'Yetki'), permSeg),
        curBox),
      onClose: () => {},
      actions: ['spacer', { label: 'Kapat' }, { label: 'Paylaş', class: 'primary', onClick: async () => {
        const targets = [...chosenUsers].map(id => ({ type: 'user', id, perm })).concat([...chosenRoles].map(role => ({ type: 'role', role, perm })));
        if (!targets.length) { toast('En az bir kullanıcı ya da rol seçin', 'err'); return true; }
        await api.post(`/api/fm/node/${it.id}/share`, { targets });
        toast('Paylaşıldı');
        chosenUsers.clear(); chosenRoles.clear();
        try { shares = (await api.get(`/api/fm/node/${it.id}/shares`)).shares || []; } catch { /* */ }
        drawCur(); drawList();
        if (mode === 'folder') { try { curData = await api.get(`/api/fm/list?parent=${curParent ?? ''}`); drawFolder(); } catch { /* */ } }
        return true;   // pencere açık kalsın
      } }],
    });

    // mevcut paylaşımları yükle
    try { shares = (await api.get(`/api/fm/node/${it.id}/shares`)).shares || []; } catch { shares = []; }
    drawCur();
  }

  // ---------- paylaşılanlar görünümü ----------
  async function openShared() {
    mode = 'shared'; curParent = null;
    newBtn.disabled = upBtn.disabled = true;   // paylaşılanlar görünümünde klasör eylemi yok
    drawTree();
    clear(main, h('div', { class: 'empty' }, 'Yükleniyor…'));
    let items;
    try { items = (await api.get('/api/fm/shared')).items || []; } catch (e) { clear(main, h('div', { class: 'card empty' }, e.message)); return; }
    const head = h('div', { class: 'fm-crumbs' }, h('span', { class: 'fm-crumb on' }, 'Paylaşılanlar'));
    if (!items.length) { clear(main, head, h('div', { class: 'fm-empty' }, 'Sizinle paylaşılan bir şey yok.')); return; }
    const grid = h('div', { class: 'fm-grid fm-shared-grid' });
    items.forEach(s => {
      const isFolder = s.kind === 'folder';
      const fk = isFolder ? null : fileKind(s.name, s.mime);
      const card = h('div', { class: `fm-item ${isFolder ? 'folder' : `file k-${fk}`}`, tabindex: '0', title: s.name });
      const open = () => { if (isFolder) openFolder(s.node_id); else previewFile({ id: s.node_id, name: s.name, mime: s.mime }); };
      card.addEventListener('click', open);
      card.addEventListener('keydown', e => { if (e.key === 'Enter') open(); });
      let ico;
      if (isFolder) ico = h('div', { class: 'fm-item-ico' }, svgIcon(icons.folderYellow));
      else if (fk === 'image') ico = h('div', { class: 'fm-item-ico' }, h('img', { src: fileUrl(s.node_id), loading: 'lazy', alt: s.name }));
      else ico = h('div', { class: 'fm-item-ico' }, svgIcon(icons[KIND_ICON[fk] || 'file']));
      card.append(
        ico,
        h('div', { class: 'fm-item-name' }, s.name),
        h('div', { class: 'fm-item-meta' }, isFolder ? 'Klasör' : 'Dosya'),
        h('div', { class: 'fm-item-sub' }, `paylaşan: ${s.shared_by_name || '—'}`),
        h('div', { class: 'fm-item-sub' }, fmtDateTime(s.created_at)),
        h('span', { class: `badge ${s.perm === 'edit' ? 'blue' : ''} fm-perm` }, PERM_LABEL[s.perm] || s.perm));
      grid.append(card);
    });
    clear(main, head, grid);
  }

  // ---------- başlat ----------
  await loadTree();
  if (mode === 'shared') await openShared();
  else await openFolder(curParent);
}
