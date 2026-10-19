'use strict';

// Notepad Master — HEPGO köprüsü. Masaüstündeki preload.js'nin window.api yüzeyini aynı ad ve imzalarla sağlar;
// IPC kanalları HEPGO REST uçlarına (app/routers/tools_notepad.py) gider. Oturum HEPGO oturumudur; Master Tool
// hesap/senkron katmanı yoktur (hesap durumu "senkron kapalı" olarak görünür).
(function () {
  MT.init({ app: 'notepadmaster' });
  const B = '/api/tools/notepad';
  const post = (p, body) => MT.post(B + p, body);
  const connId = new URLSearchParams(location.search).get('id');
  let sid = null;            // proje oturumu (proj:open sonrası)
  let storeCache = null;

  // Depo değişince tüm pencerelere yayın (ana süreçteki broadcastStore)
  const applyStore = (s) => {
    storeCache = s;
    if (s && s.settings) {
      MT.theme.apply(s.settings.appTheme || 'system');
      MT.cachedSetting('lang', s.settings.language || null);
    }
    return s;
  };
  const mutate = (p, body) => post(p, body).then((r) => { if (r && r.store) { applyStore(r.store); MT.emit('store:changed', r.store); } return r; });

  const sessionArgs = (o) => ({ sid, ...o });
  const needSid = () => { if (!sid) throw new Error('Proje oturumu açık değil'); };

  // Dosya diyalogları: kullanıcının sunucudaki dosya alanı (Electron dosya seçicilerinin karşılığı)
  const pickFolder = (start) => MT.pickPath({ mode: 'folder', start: start || '/' });
  const pickFile = (start) => MT.pickPath({ mode: 'file', start: start || '/' });
  // Özel anahtar dosyası tarayıcıdan yüklenir; sunucuda kullanıcının keys/ klasöründe saklanır
  const pickKeyFile = () => new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.onchange = async () => {
      const f = input.files[0];
      if (!f) return resolve(null);
      const fd = new FormData();
      fd.append('file', f, f.name);
      try { const r = await MT.upload(B + '/keys/upload', fd); resolve(r.path); } catch (e) { alert(e.message); resolve(null); }
    };
    input.click();
  });

  window.api = {
    lang: MT.lang(),
    version: MT.version,

    // --- Hesap: HEPGO oturumu ------------------------------------------------------------------
    accountState: () => MT.get('/api/tools/mt/account'),
    login: async () => ({ ok: true }),
    logout: async () => {
      if (MT.web) { try { window.top.MTWEB.logout(); } catch { MT.web.logout(); } return; }   // mtweb: Mastertool hesabından çıkış
      await MT.post('/api/auth/logout').catch(() => {}); try { window.top.location.href = '/'; } catch { location.href = '/'; }
    },
    syncNow: async () => {},
    setSyncEnabled: async () => ({ ok: false, code: 'hepgo' }),
    deleteRemoteLibrary: async () => ({ ok: false, code: 'hepgo' }),
    openWeb: (page) => { window.open(page === 'mastertool' || MT.web ? 'https://mastertool.download/' : '/#/', '_blank', 'noopener'); },
    onAccountStatus: (cb) => { MT.get('/api/tools/mt/account').then(cb).catch(() => {}); return MT.on('account:status')(cb); },
    onUpdateAvailable: MT.on('app:update'),
    onLibraryBackup: MT.on('account:backup'),
    openMastertool: () => window.open('https://mastertool.download/', '_blank', 'noopener'),
    about: async () => ({ version: MT.version, electron: MT.web ? 'Web' : 'HEPGO', chrome: (navigator.userAgentData && navigator.userAgentData.brands.map((b) => `${b.brand} ${b.version}`).join(', ')) || navigator.userAgent, node: '-', openAtLogin: false }),
    checkUpdate: async () => ({ ok: true, version: null, newer: false }),
    openLicenses: () => window.open('https://mastertool.download/', '_blank', 'noopener'),

    // --- Depo ----------------------------------------------------------------------------------
    getStore: () => MT.get(B + '/store').then(applyStore),
    onStoreChanged: MT.on('store:changed'),
    setSettings: async (patch) => {
      const r = await mutate('/settings', { patch });
      if ('language' in patch) { MT.cachedSetting('lang', patch.language || null); location.reload(); }
      return r;
    },
    showMain: async () => MT.child.showMain(),
    clearCache: () => post('/cache/clear'),
    openCacheDir: async () => {},   // sunucudaki çalışma kopyası klasörü tarayıcıdan açılamaz; dosyalar "Çalışma kopyasını göster" ile indirilir

    // --- Bağlantılar ---------------------------------------------------------------------------------
    saveConnection: (form) => mutate('/conn/save', { form }).then((r) => r.id),
    deleteConnection: (id) => mutate('/conn/delete', { id }),
    duplicateConnection: (id) => mutate('/conn/duplicate', { id }),
    moveConnection: (id, folderId) => mutate('/conn/move', { id, folderId }),
    setLocalPath: (id, localPath) => mutate('/conn/setLocalPath', { id, localPath }),
    testConnection: (form) => post('/conn/test', { form }),
    openConnection: async (id) => {
      const c = storeCache && storeCache.connections.find((x) => x.id === id);
      const url = `project.html?id=${encodeURIComponent(id)}`;
      if (MT.isChild) { window.parent.MT.win.open(id, url, c ? c.name : id); return; }
      MT.win.open(id, url, c ? c.name : id);
    },
    pickKeyFile,
    pickFolder,
    pickFile,

    // bağlantı formu: uzak klasör seçici
    browseOpen: (form) => post('/browse/open', { form }),
    browseList: (token, dir) => post('/browse/list', { token, dir }),
    browseClose: (token) => post('/browse/close', { token }),

    // klasörler
    saveFolder: (f) => mutate('/folder/save', f).then((r) => r.id),
    moveFolder: (id, parentId) => mutate('/folder/move', { id, parentId }).then((r) => r.ok),
    deleteFolder: (id) => mutate('/folder/delete', { id }),

    // --- Proje penceresi ------------------------------------------------------------------------------
    projOpen: async () => {
      const r = await post('/proj/open', { id: connId, prev: sid });
      if (r.ok) { sid = r.sid; startStatusWatch(); }
      return r;
    },
    projReconnect: () => { needSid(); return post('/proj/reconnect', sessionArgs({})); },
    projList: (dir) => { needSid(); return post('/proj/list', sessionArgs({ dir })); },
    projRead: (path, encoding, fallback) => { needSid(); return post('/proj/read', sessionArgs({ path, encoding, fallback })); },
    projSave: (args) => { needSid(); return post('/proj/save', sessionArgs(args)); },
    projNewFile: (p) => { needSid(); return post('/proj/newFile', sessionArgs({ path: p })); },
    projMkdir: (p) => { needSid(); return post('/proj/mkdir', sessionArgs({ path: p })); },
    projRename: (from, to) => { needSid(); return post('/proj/rename', sessionArgs({ from, to })); },
    projDelete: (path, isDir) => { needSid(); return post('/proj/delete', sessionArgs({ path, isDir })); },
    projTabs: (openTabs, activeTab) => { if (sid) post('/proj/tabs', sessionArgs({ openTabs, activeTab })).catch(() => {}); },
    // Çalışma kopyasını göster: sunucudaki kopya indirilir (Gezgin yok)
    projRevealCache: (p) => { if (sid && p) MT.download(`${B}/proj/cache?sid=${encodeURIComponent(sid)}&path=${encodeURIComponent(p)}`); },
    onProjStatus: MT.on('proj:status'),

    revealLocal: (p) => { if (p) MT.download(`/api/tools/mt/notepadmaster/fs/download?path=${encodeURIComponent(p)}`); },
    clipboardWrite: async (text) => { try { await navigator.clipboard.writeText(String(text ?? '')); } catch { /* izin yok */ } },
  };

  // Bağlantı durumu (proj:status): sunucu oturumunun durumu yoklanır
  let stopWatch = null;
  function startStatusWatch() {
    if (stopWatch) stopWatch();
    let last = null;
    stopWatch = MT.poll(async () => {
      if (!sid) return;
      const r = await MT.get(`${B}/proj/status?sid=${encodeURIComponent(sid)}`);
      if (r.status !== last) { last = r.status; MT.emit('proj:status', r.status, { local: true }); }
    }, 5000);
  }
  // Pencere kapanınca sunucu oturumu kapatılır
  MT.onClosed = () => { if (sid) { navigator.sendBeacon(`${B}/proj/close`, new Blob([JSON.stringify({ sid })], { type: 'application/json' })); sid = null; } };
  window.addEventListener('pagehide', () => MT.onClosed());
})();
