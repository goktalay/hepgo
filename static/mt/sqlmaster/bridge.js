'use strict';

// SQL Master — HEPGO köprüsü. Masaüstündeki preload.ts'nin window.api yüzeyini aynı ad ve imzalarla sağlar;
// IPC kanalları HEPGO REST uçlarına (app/routers/tools_sql.py) gider. Veritabanı oturumu sunucuda (dbhost karşılığı);
// çalıştırma olayları (db:event / db:progress / db:reset) kısa aralıkla yoklanır. Oturum HEPGO oturumudur.
(function () {
  MT.init({ app: 'sqlmaster' });
  const B = '/api/tools/sql';
  const post = (p, body) => MT.post(B + p, body);
  const connId = new URLSearchParams(location.search).get('id');
  let sid = null;           // bağlantı penceresinin sunucu oturumu (cw:connect sonrası)
  let storeCache = null;

  const applyStore = (s) => {
    storeCache = s;
    if (s && s.settings) {
      MT.theme.apply(s.settings.appTheme || 'system');
      MT.cachedSetting('lang', s.settings.language || null);
    }
    return s;
  };
  const mutate = (p, body) => post(p, body).then((r) => { if (r && r.store) { applyStore(r.store); MT.emit('store:changed', r.store); } return r; });
  const needSid = () => { if (!sid) throw new Error('Bağlantı açık değil'); return sid; };
  const db = (p, body) => post('/db' + p, { sid: needSid(), ...body });
  const EXTS = { sqlite: ['db', 'sqlite', 'sqlite3', 'db3'], duckdb: ['duckdb', 'db', 'csv', 'parquet', 'json', 'xlsx'] };

  window.api = {
    lang: MT.lang(),
    version: MT.version,
    providers: () => MT.get(B + '/providers'),
    showMain: async () => MT.child.showMain(),
    clipboardWrite: async (text) => { try { await navigator.clipboard.writeText(String(text ?? '')); } catch { /* izin yok */ } },
    // Dosya diyaloğu: kullanıcının sunucudaki dosya alanı (SQLite dosyası seç/yükle ya da kaydet)
    openFileDialog: (opts = {}) => MT.pickPath({ mode: opts.save ? 'save' : 'file', start: opts.defaultPath || '/', exts: EXTS[opts.provider] || null,
      defaultName: opts.save && opts.defaultPath ? opts.defaultPath.split(/[\\/]/).pop() : '' }),
    about: async () => ({ version: MT.version, electron: 'HEPGO', chrome: (navigator.userAgentData && navigator.userAgentData.brands.map((b) => `${b.brand} ${b.version}`).join(', ')) || navigator.userAgent, node: '-' }),
    checkUpdate: async () => ({ ok: true, version: null, newer: false }),
    openLicenses: async () => window.open('https://mastertool.download/', '_blank', 'noopener'),

    // --- Hesap: HEPGO oturumu ------------------------------------------------------------------
    accountState: () => MT.get('/api/tools/mt/account'),
    login: async () => ({ ok: true }),
    logout: async () => { await MT.post('/api/auth/logout').catch(() => {}); try { window.top.location.href = '/'; } catch { location.href = '/'; } },
    syncNow: async () => {},
    setSyncEnabled: async () => ({ ok: false, code: 'hepgo' }),
    deleteRemoteLibrary: async () => ({ ok: false, code: 'hepgo' }),
    openWeb: async (page) => { window.open(page === 'mastertool' ? 'https://mastertool.download/' : '/#/', '_blank', 'noopener'); },
    onAccountStatus: (cb) => { MT.get('/api/tools/mt/account').then(cb).catch(() => {}); return MT.on('account:status')(cb); },
    onUpdateAvailable: MT.on('app:update'),
    onLibraryBackup: MT.on('account:backup'),

    // --- Depo ----------------------------------------------------------------------------------
    getStore: () => MT.get(B + '/store').then(applyStore),
    onStoreChanged: MT.on('store:changed'),
    setSettings: async (patch) => {
      const r = await mutate('/settings', { patch });
      if ('language' in patch) { MT.cachedSetting('lang', patch.language || null); location.reload(); }
      return r;
    },

    // --- Bağlantılar / klasörler -------------------------------------------------------------------
    saveConnection: (form) => mutate('/conn/save', { form }).then((r) => r.id),
    deleteConnection: (id) => mutate('/conn/delete', { id }),
    duplicateConnection: (id) => mutate('/conn/duplicate', { id }),
    moveConnection: (id, folderId) => mutate('/conn/move', { id, folderId }),
    testConnection: (form) => post('/conn/test', { form }),
    openConnection: async (id) => {
      const c = storeCache && storeCache.connections.find((x) => x.id === id);
      const url = new URL(`../conn/conn.html?id=${encodeURIComponent(id)}`, location.href).href;
      (MT.isChild ? window.parent.MT : MT).win.open(id, url, c ? c.name : id);
    },
    saveFolder: (f) => mutate('/folder/save', f).then((r) => r.id),
    moveFolder: (id, parentId) => mutate('/folder/move', { id, parentId }).then((r) => r.ok),
    deleteFolder: (id) => mutate('/folder/delete', { id }),

    // --- Bağlantı penceresi -------------------------------------------------------------------------
    cwInfo: () => MT.get(`${B}/cw/info?id=${encodeURIComponent(connId)}`),
    cwConnect: async (opts = {}) => {
      const r = await post('/cw/connect', { id: connId, prev: sid, password: opts.password });
      if (r.ok) { sid = r.sid; startEvents(); }
      return r;
    },
    dbChildren: (node) => db('/children', { node }),
    dbDdl: (node) => db('/ddl', { node }),
    dbColumns: (path) => db('/columns', { path }),
    dbCompletion: (database) => db('/completion', { database }),
    dbExecute: ({ runId, req }) => db('/execute', { runId, req }),
    dbCancel: (runId) => db('/cancel', { runId }),
    dbSetReadOnly: (on) => db('/setReadOnly', { on }).then((r) => r.on),
    // Dışa aktarma: sunucuda dosyaya akıtılır, bitince indirilir (kaydetme diyaloğu yerine tarayıcı indirmesi)
    dbExport: async ({ runId, sql, database, format, defaultName }) => {
      const r = await db('/export', { runId, sql, database, format, defaultName });
      if (!r) return null;
      MT.download(`${B}/db/download?token=${encodeURIComponent(r.token)}`, r.fileName);
      return { rows: r.rows, bytes: r.bytes, cancelled: r.cancelled, filePath: r.fileName };
    },
    historyList: () => MT.get(`${B}/history?id=${encodeURIComponent(connId)}`),
    reveal: async () => {},   // indirme dbExport'ta tetiklendi
    onDbEvent: MT.on('db:event'),
    onDbProgress: MT.on('db:progress'),
    onDbReset: MT.on('db:reset'),
  };

  // Çalıştırma akışı: sunucu oturumundaki olaylar sıra numarasıyla çekilir (utilityProcess → ana süreç → pencere yolunun karşılığı)
  let stopEvents = null;
  function startEvents() {
    if (stopEvents) stopEvents();
    let since = 0;
    const mySid = sid;
    stopEvents = MT.poll(async () => {
      if (sid !== mySid) return;
      const r = await MT.get(`${B}/db/events?sid=${encodeURIComponent(mySid)}&since=${since}`);
      if (r.gone) { MT.emit('db:reset', { reason: 'exit' }, { local: true }); stopEvents(); stopEvents = null; return; }
      since = r.seq;
      for (const ev of r.events) MT.emit(ev.ch, ev.data, { local: true });
    }, 250);
  }
  MT.onClosed = () => { if (sid) { navigator.sendBeacon(`${B}/cw/close`, new Blob([JSON.stringify({ sid })], { type: 'application/json' })); sid = null; } };
  window.addEventListener('pagehide', () => MT.onClosed());
})();
