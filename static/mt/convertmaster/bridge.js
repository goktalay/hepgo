'use strict';

// Convert Master — HEPGO köprüsü. Masaüstündeki preload.js'nin window.api yüzeyini aynı ad ve imzalarla sağlar;
// IPC kanalları HEPGO REST uçlarına (app/routers/tools_convert.py) gider. Dönüştürme kuyruğu sunucuda çalışır
// (orijinal jobs.js mantığı), ilerleme olayları (job:items / job:state / job:finished …) kısa aralıkla yoklanır.
(function () {
  MT.init({ app: 'convertmaster' });
  const B = '/api/tools/convert';
  const post = (p, body) => MT.post(B + p, body);
  const pid = new URLSearchParams(location.search).get('id');
  let storeCache = null;

  const applyStore = (s) => {
    storeCache = s;
    if (s && s.settings) {
      MT.theme.apply(s.settings.appTheme || 'system');
      MT.cachedSetting('lang', s.settings.language || null);
    }
    return s;
  };
  const mutate = (p, body) => post(p, body).then((r) => {
    if (r && r.store) { applyStore(r.store); MT.emit('store:changed', r.store); }
    if (r && r.stats) MT.emit('projects:stats', r.stats);
    return r;
  });
  const pj = (p, body) => post('/pj' + p, { id: pid, ...body });
  const dl = (path, params) => MT.download(`${B}${path}?${new URLSearchParams({ id: pid, ...params })}`);

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
    showMain: async () => MT.child.showMain(),

    // --- Depo ----------------------------------------------------------------------------------
    getStore: () => MT.get(B + '/store').then(applyStore),
    onStoreChanged: MT.on('store:changed'),
    setSettings: async (patch) => {
      const r = await mutate('/settings', { patch });
      if ('language' in patch) { MT.cachedSetting('lang', patch.language || null); location.reload(); }
      return r;
    },

    // --- Projeler ve klasörler (ana pencere) -----------------------------------------------------------
    saveProject: (form) => mutate('/project/save', { form }).then((r) => r.id),
    deleteProject: (id) => mutate('/project/delete', { id }).then(() => { if (!MT.isChild) MT.win.close(id, true); }),
    duplicateProject: (id) => mutate('/project/duplicate', { id }),
    moveProject: (id, folderId) => mutate('/project/move', { id, folderId }),
    openProject: async (id) => {
      const p = storeCache && storeCache.projects.find((x) => x.id === id);
      const url = `project.html?id=${encodeURIComponent(id)}`;
      (MT.isChild ? window.parent.MT : MT).win.open(id, url, p ? p.name : id);
    },
    clearProjectOutputs: (id, transcripts) => mutate('/project/clearOutputs', { id, transcripts }),
    projectStats: () => MT.get(B + '/projects/stats'),
    onProjectStats: MT.on('projects:stats'),
    saveFolder: (f) => mutate('/folder/save', f).then((r) => r.id),
    moveFolder: (id, parentId) => mutate('/folder/move', { id, parentId }).then((r) => r.ok),
    deleteFolder: (id) => mutate('/folder/delete', { id }),
    // Kaynak: kullanıcının sunucudaki dosya alanı (dosya/klasör seçilir ya da diyalogdan yüklenir)
    pickSource: ({ mode, type, exts, defaultPath }) => MT.pickPath({ mode: mode === 'folder' ? 'folder' : 'file', start: defaultPath || '/', exts: mode === 'folder' ? null : ((window.FORMATS && FORMATS.TYPES[type]) || {}).source || exts || null }),

    // --- Proje penceresi ------------------------------------------------------------------------------
    pjInit: () => pj('/init').then((r) => { startEvents(); return r; }),
    pjScan: () => pj('/scan'),
    pjCheck: (rels, checked) => pj('/check', { rels, checked }),
    pjStart: (opts) => pj('/start', { opts: opts || {} }),
    pjStop: () => pj('/stop'),
    pjTranscribe: (rels) => pj('/transcribe', { rels }),
    pjTranscript: (rel) => pj('/transcript', { rel }),
    pjExportTranscript: (rel, format) => { dl('/pj/exportTranscript', { rel, format }); return Promise.resolve(`${rel}.${format}`); },
    pjDeleteOutputs: (opts) => pj('/deleteOutputs', { opts: opts || {} }),
    pjSetConcurrency: (n) => pj('/setConcurrency', { n }),
    pjChangeSource: async () => {
      const p = storeCache ? storeCache.projects.find((x) => x.id === pid) : null;
      const picked = await MT.pickPath({ mode: p && p.sourceMode === 'file' ? 'file' : 'folder', start: (p && p.sourcePath) || '/', exts: p && p.sourceMode === 'file' ? ((window.FORMATS && FORMATS.TYPES[p.type]) || {}).source : null });
      if (!picked) return null;
      const r = await mutate('/pj/changeSource', { id: pid, sourcePath: picked });
      if (r.project) MT.emit('project:changed', r.project, { local: true });
      return r.snapshot;
    },
    pjPreview: (rel, which) => pj('/preview', { rel, which }),
    pjProxy: (rel, which) => pj('/proxy', { rel, which }).then((r) => r.url),
    // Dosyayı aç / klasörde göster: tarayıcıda indirme
    pjOpen: async (rel, which) => dl('/pj/file', { rel, which }),
    pjReveal: (rel, which) => dl('/pj/file', { rel, which }),
    pjOpenOutDir: () => dl('/pj/exportOutputs', {}),
    pjExportOutputs: async (rels) => {
      const r = await pj('/exportCount', { rels: rels || null });
      if (!r.count) return { count: 0, dest: '' };
      dl('/pj/exportOutputs', rels && rels.length ? { rels: rels.join('\n') } : {});
      return { count: r.count, dest: 'ZIP' };
    },
    pjOutSize: () => pj('/outSize').then((r) => r.bytes),
    onJobItems: MT.on('job:items'),
    onJobState: MT.on('job:state'),
    onJobFinished: MT.on('job:finished'),
    onProjectChanged: MT.on('project:changed'),
    onPreviewProgress: MT.on('preview:progress'),

    // --- Konuşma motoru / OCR / depolama (ayarlar) ---------------------------------------------------
    speechStatus: () => MT.get(B + '/speech/status'),
    speechDownload: (model) => post('/speech/download', { model }),
    speechCancelDownload: async () => {},
    speechDeleteModel: (model) => post('/speech/deleteModel', { model }),
    onSpeechDownload: MT.on('speech:download'),
    ocrStatus: () => MT.get(B + '/ocr/status'),
    ocrDownload: (lang) => post('/ocr/download', { lang }),
    ocrCancelDownload: async () => {},
    ocrDelete: (lang) => post('/ocr/delete', { lang }),
    storageInfo: () => MT.get(B + '/storage/info'),
    clearConverted: (transcripts) => mutate('/storage/clearConverted', { transcripts }),
    clearCache: () => post('/storage/clearCache'),
    openStorage: async () => {},   // sunucu klasörü tarayıcıdan açılamaz
  };

  // İş kuyruğu olayları: sunucudaki çalıştırıcıdan sıra numarasıyla çekilir, pencereye masaüstündeki kanallarla dağıtılır
  let stopEvents = null;
  function startEvents() {
    if (stopEvents || !pid) return;
    let since = 0;
    stopEvents = MT.poll(async () => {
      const r = await MT.get(`${B}/pj/events?id=${encodeURIComponent(pid)}&since=${since}`);
      since = r.seq;
      for (const ev of r.events) {
        MT.emit(ev.ch, ev.data, { local: true });
        if (ev.ch === 'job:finished') MT.get(B + '/projects/stats').then((s) => MT.emit('projects:stats', s)).catch(() => {});
      }
    }, 400);
  }
  // Pencere kapanınca çalıştırıcı kapanır (masaüstünde pencere kapanınca runner.close)
  MT.onClosed = () => { if (pid) navigator.sendBeacon(`${B}/pj/close`, new Blob([JSON.stringify({ id: pid })], { type: 'application/json' })); };
  window.addEventListener('pagehide', () => MT.onClosed());
})();
