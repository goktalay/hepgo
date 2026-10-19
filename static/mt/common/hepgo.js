'use strict';

// Master Tool web sürümleri — HEPGO köprü çekirdeği (SQL Master · Notepad Master · Convert Master ortak).
// Electron'da preload + ana süreç ne yapıyorsa burada web karşılığı var: REST çağrıları, pencereler arası yayın
// (BroadcastChannel), pencere yöneticisi (ayrı BrowserWindow'lar → sekmeli iframe'ler), tema (nativeTheme →
// prefers-color-scheme kurallarının yeniden yazımı), dosya diyalogları (kullanıcının sunucudaki dosya alanı).
// Her uygulamanın bridge.js'i window.api'yi preload ile aynı ad/imzalarla bu çekirdek üzerinden kurar.
(function (root) {
  const SUPPORTED = ['tr', 'en', 'fr', 'de', 'es', 'ar', 'zh', 'ru'];
  // mtweb (Mastertool web servisi): sunucu yapılandırması window.MTWEB (/web/config.js + mtweb.js). HEPGO'da yok → eski davranış.
  const WEB = root.MTWEB || null;
  const MT = { app: null, isChild: window.parent !== window && !!safeParent(), version: WEB ? 'Web' : 'HEPGO', web: WEB };
  root.MT = MT;

  function safeParent() { try { return window.parent.MT || null; } catch { return null; } }

  // --- Dil ----------------------------------------------------------------------------------
  // Uygulama ayarı (settings.language) önce; yoksa HEPGO'nun dili (caymaz.lang); o da yoksa Türkçe.
  MT.hepgoLang = () => {
    if (WEB && WEB.lang) return SUPPORTED.includes(WEB.lang) ? WEB.lang : 'en';   // mtweb: site dili → tarayıcı dili → en
    let l = 'tr';
    try { l = localStorage.getItem('caymaz.lang') || 'tr'; } catch { /* yok */ }
    l = String(l).toLowerCase().split(/[-_]/)[0];
    return SUPPORTED.includes(l) ? l : 'en';
  };
  MT.cachedSetting = (k, v) => {
    const key = () => `mt.${MT.app}.${k}`;
    if (v === undefined) { try { return localStorage.getItem(key()); } catch { return null; } }
    try { if (v === null) localStorage.removeItem(key()); else localStorage.setItem(key(), v); } catch { /* yok */ }
    return v;
  };
  MT.lang = () => {
    const l = MT.cachedSetting('lang');
    return l && SUPPORTED.includes(l) ? l : MT.hepgoLang();
  };

  // Çekirdeğin kendi küçük sözlüğü (dosya diyaloğu, pencere şeridi). Uygulama metinleri uygulamanın i18n'inden gelir.
  const STR = {
    tr: { choose: 'Seç', cancel: 'İptal', upload: 'Dosya yükle', uploadDir: 'Klasör yükle', newFolder: 'Yeni klasör', up: 'Üst klasör', home: 'Kök', empty: 'Boş klasör', name: 'Dosya adı', folderName: 'Klasör adı', main: 'Ana pencere', newTab: 'Yeni sekmede aç', close: 'Kapat', closeDirty: 'Kaydedilmemiş değişiklikler var. Pencere kapatılırsa kaybolacak.', storage: 'Sunucudaki alanınız', delete: 'Sil', deleteAsk: 'Silinsin mi?' },
    en: { choose: 'Choose', cancel: 'Cancel', upload: 'Upload files', uploadDir: 'Upload folder', newFolder: 'New folder', up: 'Parent folder', home: 'Root', empty: 'Empty folder', name: 'File name', folderName: 'Folder name', main: 'Main window', newTab: 'Open in new tab', close: 'Close', closeDirty: 'There are unsaved changes. They will be lost if the window is closed.', storage: 'Your space on the server', delete: 'Delete', deleteAsk: 'Delete?' },
    de: { choose: 'Wählen', cancel: 'Abbrechen', upload: 'Dateien hochladen', uploadDir: 'Ordner hochladen', newFolder: 'Neuer Ordner', up: 'Übergeordneter Ordner', home: 'Stammordner', empty: 'Leerer Ordner', name: 'Dateiname', folderName: 'Ordnername', main: 'Hauptfenster', newTab: 'In neuem Tab öffnen', close: 'Schließen', closeDirty: 'Es gibt ungespeicherte Änderungen. Sie gehen beim Schließen verloren.', storage: 'Ihr Bereich auf dem Server', delete: 'Löschen', deleteAsk: 'Löschen?' },
    fr: { choose: 'Choisir', cancel: 'Annuler', upload: 'Téléverser des fichiers', uploadDir: 'Téléverser un dossier', newFolder: 'Nouveau dossier', up: 'Dossier parent', home: 'Racine', empty: 'Dossier vide', name: 'Nom du fichier', folderName: 'Nom du dossier', main: 'Fenêtre principale', newTab: 'Ouvrir dans un nouvel onglet', close: 'Fermer', closeDirty: 'Des modifications non enregistrées seront perdues si la fenêtre est fermée.', storage: 'Votre espace sur le serveur', delete: 'Supprimer', deleteAsk: 'Supprimer ?' },
    es: { choose: 'Elegir', cancel: 'Cancelar', upload: 'Subir archivos', uploadDir: 'Subir carpeta', newFolder: 'Nueva carpeta', up: 'Carpeta superior', home: 'Raíz', empty: 'Carpeta vacía', name: 'Nombre de archivo', folderName: 'Nombre de carpeta', main: 'Ventana principal', newTab: 'Abrir en pestaña nueva', close: 'Cerrar', closeDirty: 'Hay cambios sin guardar. Se perderán al cerrar la ventana.', storage: 'Su espacio en el servidor', delete: 'Eliminar', deleteAsk: '¿Eliminar?' },
    ar: { choose: 'اختيار', cancel: 'إلغاء', upload: 'رفع ملفات', uploadDir: 'رفع مجلد', newFolder: 'مجلد جديد', up: 'المجلد الأعلى', home: 'الجذر', empty: 'مجلد فارغ', name: 'اسم الملف', folderName: 'اسم المجلد', main: 'النافذة الرئيسية', newTab: 'فتح في لسان جديد', close: 'إغلاق', closeDirty: 'هناك تغييرات غير محفوظة ستُفقد عند إغلاق النافذة.', storage: 'مساحتك على الخادم', delete: 'حذف', deleteAsk: 'حذف؟' },
    zh: { choose: '选择', cancel: '取消', upload: '上传文件', uploadDir: '上传文件夹', newFolder: '新建文件夹', up: '上级文件夹', home: '根目录', empty: '空文件夹', name: '文件名', folderName: '文件夹名', main: '主窗口', newTab: '在新标签页打开', close: '关闭', closeDirty: '有未保存的更改，关闭窗口将丢失。', storage: '您在服务器上的空间', delete: '删除', deleteAsk: '删除？' },
    ru: { choose: 'Выбрать', cancel: 'Отмена', upload: 'Загрузить файлы', uploadDir: 'Загрузить папку', newFolder: 'Новая папка', up: 'Родительская папка', home: 'Корень', empty: 'Пустая папка', name: 'Имя файла', folderName: 'Имя папки', main: 'Главное окно', newTab: 'Открыть в новой вкладке', close: 'Закрыть', closeDirty: 'Есть несохранённые изменения. При закрытии окна они будут потеряны.', storage: 'Ваше место на сервере', delete: 'Удалить', deleteAsk: 'Удалить?' },
  };
  MT.t = (k) => {
    if (WEB && k === 'storage' && WEB.t) return WEB.t('files');   // mtweb: "Sunucudaki alanınız" yerine "Dosyalarınız"
    return (STR[MT.lang()] || STR.en)[k] || STR.en[k] || k;
  };

  // --- REST ---------------------------------------------------------------------------------
  class ApiError extends Error { constructor(status, message) { super(message); this.status = status; } }
  MT.ApiError = ApiError;
  async function parse(res) {
    const ct = res.headers.get('content-type') || '';
    const data = ct.includes('json') ? await res.json().catch(() => null) : await res.text().catch(() => '');
    if (!res.ok) {
      if (res.status === 401) { try { window.top.dispatchEvent(new Event('caymaz:unauthorized')); } catch { /* */ } }
      const d = data && typeof data === 'object' ? data.detail : data;
      throw new ApiError(res.status, typeof d === 'string' && d ? d : Array.isArray(d) && d[0] && d[0].msg ? d[0].msg : `HTTP ${res.status}`);
    }
    return data;
  }
  MT.call = (method, url, body) => fetch(url, {
    method, credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).then(parse);
  MT.get = (url) => MT.call('GET', url);
  MT.post = (url, body = {}) => MT.call('POST', url, body);
  MT.upload = (url, fd, onProgress) => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* boş */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
      reject(new ApiError(xhr.status, (data && typeof data.detail === 'string' && data.detail) || `HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new ApiError(0, 'Bağlantı hatası'));
    xhr.send(fd);
  });
  MT.base = () => `/api/tools/mt/${MT.app}`;

  // Uzun işler için kısa aralıklı yoklama (sunucudaki iş kuyruğu olayları)
  MT.poll = (fn, ms = 400) => {
    let stop = false;
    (async () => {
      while (!stop) {
        try { await fn(); } catch (e) { if (e && e.status === 401) break; }
        await new Promise((r) => setTimeout(r, ms));
      }
    })();
    return () => { stop = true; };
  };

  // --- Pencereler arası yayın (webContents.send karşılığı) ----------------------------------------
  const listeners = new Map();
  let channel = null;
  function bc() {
    if (channel || !('BroadcastChannel' in window)) return channel;
    channel = new BroadcastChannel(`hepgo-mt-${MT.app}`);
    channel.onmessage = (e) => deliver(e.data.ch, e.data.data);
  }
  function deliver(ch, data) { for (const cb of listeners.get(ch) || []) { try { cb(data); } catch (err) { console.error(err); } } }
  MT.on = (ch) => (cb) => {
    bc();
    if (!listeners.has(ch)) listeners.set(ch, new Set());
    listeners.get(ch).add(cb);
    return () => listeners.get(ch).delete(cb);
  };
  // local: yalnız bu pencere; broadcast: tüm pencereler (diğer iframe/sekmeler dahil)
  MT.emit = (ch, data, { local = false } = {}) => {
    deliver(ch, data);
    if (!local && bc()) channel.postMessage({ ch, data });
  };

  // --- Tema: Electron nativeTheme.themeSource karşılığı ----------------------------------------------
  // Stil dosyalarındaki "@media (prefers-color-scheme: light)" kuralları seçime göre açılır/kapanır ve
  // matchMedia aynı sorgu için seçimi yansıtır (uygulama kodu themeButton/Monaco teması için ona bakar).
  const sysLight = window.matchMedia('(prefers-color-scheme: light)');
  const fakeMql = new Set();
  let appTheme = 'system';
  const effectiveLight = () => (appTheme === 'system' ? sysLight.matches : appTheme === 'light');
  const realMatch = window.matchMedia.bind(window);
  window.matchMedia = function (q) {
    const s = String(q);
    if (!/prefers-color-scheme/.test(s)) return realMatch(q);
    const wantLight = /light/.test(s);
    const cbs = new Set();
    const m = {
      media: s, onchange: null,
      get matches() { return wantLight ? effectiveLight() : !effectiveLight(); },
      addEventListener: (_t, cb) => cbs.add(cb), removeEventListener: (_t, cb) => cbs.delete(cb),
      addListener: (cb) => cbs.add(cb), removeListener: (cb) => cbs.delete(cb),
      dispatchEvent: () => true,
      _fire() { const ev = { media: s, matches: m.matches, type: 'change' }; for (const cb of cbs) cb(ev); if (m.onchange) m.onchange(ev); },
    };
    fakeMql.add(m);
    return m;
  };
  function rewriteSheets() {
    const light = effectiveLight();
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; }
      if (!rules) continue;
      for (const r of rules) {
        if (!(r instanceof CSSMediaRule)) continue;
        const orig = r._mtMedia || r.media.mediaText;
        if (!/prefers-color-scheme/.test(orig)) continue;
        r._mtMedia = orig;
        const wantLight = /light/.test(orig);
        r.media.mediaText = (wantLight ? light : !light) ? 'all' : 'not all';
      }
    }
    document.documentElement.style.colorScheme = light ? 'light' : 'dark';
  }
  MT.theme = {
    get: () => appTheme,
    apply(v) {
      appTheme = v === 'light' || v === 'dark' ? v : 'system';
      MT.cachedSetting('theme', appTheme);
      rewriteSheets();
      for (const m of fakeMql) m._fire();
    },
    refresh: rewriteSheets,
  };
  sysLight.addEventListener('change', () => { if (appTheme === 'system') MT.theme.apply('system'); });
  // Stil dosyaları yüklenince ve açılışta (önbellekteki seçimle; ilk çizim doğru temada olsun)
  document.addEventListener('DOMContentLoaded', () => {
    MT.theme.apply(MT.cachedSetting('theme') || 'system');
    for (const l of document.querySelectorAll('link[rel=stylesheet]')) l.addEventListener('load', rewriteSheets);
  });
  window.addEventListener('load', rewriteSheets);

  // --- Küçük DOM yardımcıları ------------------------------------------------------------------------
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const h = (html) => { const tpl = document.createElement('template'); tpl.innerHTML = html.trim(); return tpl.content.firstElementChild; };
  MT.esc = esc; MT.h = h;
  const SVG = {
    up: '<path d="M12 19V5M5 12l7-7 7 7"/>', home: '<path d="m3 11 9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    upload: '<path d="M12 20V9M7 14l5-5 5 5M5 4h14"/>', folderPlus: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 11v5M9.5 13.5h5"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>', open: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  };
  const icon = (n) => `<svg class="i" viewBox="0 0 24 24">${SVG[n] || ''}</svg>`;
  MT.icon = icon;
  const fmtSize = (n) => { const u = ['B', 'KB', 'MB', 'GB']; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return `${n < 10 && i ? n.toFixed(1) : Math.round(n)} ${u[i]}`; };

  // Dosya indirme (shell.openPath / showItemInFolder / kaydetme diyaloğu karşılığı)
  MT.download = (url, name) => {
    const a = document.createElement('a');
    a.href = url; a.download = name || ''; a.rel = 'noopener';
    document.body.appendChild(a); a.click(); a.remove();
  };

  // --- Dosya diyaloğu: kullanıcının sunucudaki dosya alanı (dialog.showOpenDialog / showSaveDialog) -------------
  //   MT.pickPath({ mode: 'file' | 'folder' | 'save', title, start, exts, defaultName }) → '/klasör/dosya' | null
  MT.pickPath = ({ mode = 'file', title = '', start = '/', exts = null, defaultName = '' } = {}) => new Promise((resolve) => {
    const t = MT.t;
    const parent = (p) => (p === '/' ? '/' : p.replace(/\/+$/, '').replace(/\/[^/]*$/, '') || '/');
    let dir = start && start !== '/' ? (mode === 'folder' ? start : parent(start)) : '/';
    let picked = mode === 'file' && start && !start.endsWith('/') ? start : null;
    const back = h('<div class="modal-backdrop mt-dialog"></div>');
    const modal = h(`<div class="modal" style="width:min(640px, calc(100vw - 32px))">
      <header><span style="color:var(--accent)">${icon('folder')}</span><h2>${esc(title || t('choose'))}</h2></header>
      <div class="body">
        <div class="mt-fs-bar">
          <button class="icon-btn" data-a="up" title="${esc(t('up'))}">${icon('up')}</button>
          <button class="icon-btn" data-a="home" title="${esc(t('home'))}">${icon('home')}</button>
          <input class="input mt-fs-path" spellcheck="false">
          <button class="icon-btn" data-a="mkdir" title="${esc(t('newFolder'))}">${icon('folderPlus')}</button>
          <button class="icon-btn" data-a="upload" title="${esc(t('upload'))}">${icon('upload')}</button>
          <button class="icon-btn" data-a="uploaddir" title="${esc(t('uploadDir'))}">${icon('folderPlus')}${icon('upload')}</button>
          <button class="icon-btn" data-a="del" title="${esc(t('delete'))}">${icon('trash')}</button>
        </div>
        <div class="mt-fs-list"></div>
        ${mode === 'save' ? `<div class="field"><label>${esc(t('name'))}</label><input class="input mt-fs-name" value="${esc(defaultName)}" spellcheck="false"></div>` : ''}
        <div class="mt-fs-hint">${esc(t('storage'))}: <code class="mt-fs-sel"></code></div>
        <input type="file" multiple class="mt-fs-file" hidden><input type="file" webkitdirectory multiple class="mt-fs-dir" hidden>
      </div>
      <footer><span class="spacer"></span><button class="btn" data-a="cancel">${esc(t('cancel'))}</button><button class="btn primary" data-a="ok">${esc(t('choose'))}</button></footer>
    </div>`);
    back.appendChild(modal);
    const q = (s) => modal.querySelector(s);
    const list = q('.mt-fs-list');
    const pathEl = q('.mt-fs-path');
    const selEl = q('.mt-fs-sel');
    const close = (v) => { back.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const current = () => {
      if (mode === 'folder') return picked || dir;
      if (mode === 'save') { const n = (q('.mt-fs-name').value || '').trim(); return n ? `${dir === '/' ? '' : dir}/${n}` : null; }
      return picked;
    };
    const paintSel = () => { const c = current(); selEl.textContent = c || '—'; q('[data-a=ok]').disabled = !c; };
    const okExt = (name) => !exts || !exts.length || exts.includes((name.split('.').pop() || '').toLowerCase());
    async function load(d) {
      list.innerHTML = '<div class="mt-fs-empty"><span class="spin"></span></div>';
      try {
        const r = await MT.get(`${MT.base()}/fs/list?path=${encodeURIComponent(d)}`);
        dir = d;
        pathEl.value = dir;
        if (mode !== 'file') picked = null;
        list.innerHTML = '';
        if (!r.items.length) list.appendChild(h(`<div class="mt-fs-empty">${esc(t('empty'))}</div>`));
        for (const it of r.items) {
          if (!it.isDir && mode === 'folder') continue;
          const dim = !it.isDir && !okExt(it.name) ? ' dim' : '';
          const row = h(`<div class="mt-fs-item${dim}">${icon(it.isDir ? 'folder' : 'file')}<span class="n">${esc(it.name)}</span><span class="s">${it.isDir ? '' : fmtSize(it.size)}</span></div>`);
          row.onclick = () => {
            list.querySelectorAll('.mt-fs-item').forEach((x) => x.classList.remove('sel'));
            row.classList.add('sel');
            picked = it.path;
            if (mode === 'save' && !it.isDir) q('.mt-fs-name').value = it.name;
            paintSel();
          };
          row.ondblclick = () => { if (it.isDir) load(it.path); else if (mode === 'file' && okExt(it.name)) { picked = it.path; close(picked); } };
          list.appendChild(row);
        }
        paintSel();
      } catch (err) {
        list.innerHTML = `<div class="mt-fs-empty" style="color:var(--err)">${esc(err.message)}</div>`;
        pathEl.value = dir;
      }
    }
    q('[data-a=up]').onclick = () => load(parent(dir));
    q('[data-a=home]').onclick = () => load('/');
    pathEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); load(pathEl.value.trim() || '/'); } });
    q('[data-a=mkdir]').onclick = async () => {
      const name = window.prompt(t('folderName'));
      if (!name) return;
      await MT.post(`${MT.base()}/fs/mkdir`, { path: dir, name }).catch((e) => alert(e.message));
      load(dir);
    };
    q('[data-a=del]').onclick = async () => {
      const sel = list.querySelector('.mt-fs-item.sel .n');
      if (!sel || !picked || !window.confirm(`${sel.textContent} — ${t('deleteAsk')}`)) return;
      await MT.post(`${MT.base()}/fs/delete`, { path: picked }).catch((e) => alert(e.message));
      picked = null; load(dir);
    };
    const doUpload = async (input) => {
      if (!input.files.length) return;
      const fd = new FormData();
      fd.append('dir', dir);
      for (const f of input.files) fd.append('files', f, f.webkitRelativePath || f.name);
      list.innerHTML = '<div class="mt-fs-empty"><span class="spin"></span> 0%</div>';
      try {
        await MT.upload(`${MT.base()}/fs/upload`, fd, (p) => { const e = list.querySelector('.mt-fs-empty'); if (e) e.lastChild.textContent = ` ${Math.round(p * 100)}%`; });
      } catch (e) { alert(e.message); }
      input.value = '';
      load(dir);
    };
    q('[data-a=upload]').onclick = () => q('.mt-fs-file').click();
    q('[data-a=uploaddir]').onclick = () => q('.mt-fs-dir').click();
    q('.mt-fs-file').onchange = (e) => doUpload(e.target);
    q('.mt-fs-dir').onchange = (e) => doUpload(e.target);
    if (mode === 'save') q('.mt-fs-name').addEventListener('input', paintSel);
    q('[data-a=cancel]').onclick = () => close(null);
    q('[data-a=ok]').onclick = () => { const c = current(); if (c) close(c); };
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(null); } };
    document.addEventListener('keydown', onKey, true);
    back.addEventListener('mousedown', (e) => { if (e.target === back) close(null); });
    document.body.appendChild(back);
    load(dir);
  });

  // --- Pencere yöneticisi (BrowserWindow karşılığı: ana sayfada sekmeli iframe'ler) ----------------------
  // Ana sayfa: MT.win.open(key, url, title) → üstte pencere şeridi, içerik iframe'de; ana içerik gizlenir.
  // Alt pencere: parent.MT.win üzerinden showMain/close/setTitle. "↗" aynı sayfayı gerçek tarayıcı sekmesinde açar.
  const wins = new Map();
  let active = null; // null = ana pencere
  function bar() {
    let b = document.getElementById('mt-winbar');
    if (b) return b;
    b = h('<div id="mt-winbar" class="hidden"><button class="mt-wtab main on" data-k=""></button></div>');
    b.querySelector('.main').innerHTML = `${icon('home')}<span>${esc(MT.t('main'))}</span>`;
    b.querySelector('.main').onclick = () => MT.win.showMain();
    document.body.prepend(b);
    document.body.appendChild(h('<div id="mt-winhost" class="hidden"></div>'));
    return b;
  }
  const mainRoot = () => document.querySelector('body > .app') || document.body.firstElementChild;
  function paintWins() {
    const b = bar();
    b.classList.toggle('hidden', wins.size === 0);
    document.getElementById('mt-winhost').classList.toggle('hidden', active === null);
    if (mainRoot()) mainRoot().classList.toggle('mt-hidden', active !== null);
    for (const tab of b.querySelectorAll('.mt-wtab')) tab.classList.toggle('on', (tab.dataset.k || null) === active);
    for (const [k, w] of wins) w.frame.classList.toggle('on', k === active);
    document.body.classList.toggle('mt-winmode', wins.size > 0);
  }
  MT.win = {
    open(key, url, title) {
      const existing = wins.get(key);
      if (existing) return this.focus(key);
      const b = bar();
      const tab = h(`<button class="mt-wtab" data-k="${esc(key)}"><span class="t">${esc(title || key)}</span><span class="icon-btn x" title="${esc(MT.t('newTab'))}">${icon('open')}</span><span class="icon-btn x" title="${esc(MT.t('close'))}">${icon('x')}</span></button>`);
      const [ext, close] = tab.querySelectorAll('.x');
      tab.onclick = (e) => { if (!e.target.closest('.x')) this.focus(key); };
      ext.onclick = (e) => { e.stopPropagation(); window.open(url, '_blank', 'noopener'); this.close(key, true); };
      close.onclick = (e) => { e.stopPropagation(); this.close(key); };
      const frame = h(`<iframe class="mt-win" src="${esc(url)}" title="${esc(title || key)}"></iframe>`);
      b.appendChild(tab);
      document.getElementById('mt-winhost').appendChild(frame);
      wins.set(key, { tab, frame, url });
      this.focus(key);
    },
    focus(key) { active = wins.has(key) ? key : null; paintWins(); const w = wins.get(key); if (w) setTimeout(() => { try { w.frame.contentWindow.focus(); } catch { /* */ } }, 0); },
    showMain() { active = null; paintWins(); },
    setTitle(key, title) { const w = wins.get(key); if (w) w.tab.querySelector('.t').textContent = title; },
    has: (key) => wins.has(key),
    close(key, force = false) {
      const w = wins.get(key);
      if (!w) return;
      if (!force) {
        let dirty = false;
        try { dirty = !!(w.frame.contentWindow.MT && w.frame.contentWindow.MT.isDirty()); } catch { /* */ }
        if (dirty && !window.confirm(MT.t('closeDirty'))) return;
      }
      try { w.frame.contentWindow.MT.onClosed && w.frame.contentWindow.MT.onClosed(); } catch { /* */ }
      w.tab.remove(); w.frame.remove(); wins.delete(key);
      if (active === key) active = null;
      paintWins();
    },
  };
  // Alt pencere tarafı: kaydedilmemiş sekme kontrolü (renderer'ın beforeunload dinleyicisi iptal ediyorsa kirli)
  MT.isDirty = () => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; };
  MT.onClosed = null;
  MT.child = {
    key: new URLSearchParams(location.search).get('id'),
    showMain() { const p = safeParent(); if (p) p.win.showMain(); else window.open('index.html', '_blank'); },
    watchTitle() {
      const p = safeParent();
      if (!p) return;
      const push = () => p.win.setTitle(MT.child.key, document.title.replace(/ — .*$/, ''));
      new MutationObserver(push).observe(document.querySelector('title') || document.head, { childList: true, subtree: true, characterData: true });
      push();
    },
  };

  MT.init = ({ app }) => { MT.app = app; bc(); if (MT.isChild || new URLSearchParams(location.search).get('id')) MT.child.watchTitle(); };
})(window);
