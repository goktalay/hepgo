'use strict';

// HEPGO web köprüsü — ortak çekirdek (SSH Master ve FTP Masters).
//
// Masaüstü uygulamalarda renderer, preload.js'in verdiği window.api üzerinden ana süreçle (IPC) konuşur.
// Web sürümünde aynı isim ve imzalarla window.api'yi bu çekirdek + uygulamanın bridge.js'i sağlar:
//   - depo / bağlantı / klasör / ayar / yerel dosya çağrıları  → POST /api/tools/mt/<app>/invoke {m: '<ipc kanalı>', a}
//   - oturuma bağlı işler (SSH kabuğu, SFTP, FTP sitesi, aktarımlar) → WebSocket (uygulamanın bridge.js'i)
// Oturum HEPGO oturumudur (çerez); Master Tool hesabı/senkron katmanı yoktur (hesap çağrıları etkisiz döner).
// "Bilgisayarım" paneli kullanıcının HEPGO'daki kişisel dosya alanıdır; sanal sürücü harfi H:\ ile Windows yolu gibi görünür.
// Sunucudan gelen metinler {$t: 'anahtar', $p: {...}} biçimindeyse uygulamanın kendi i18n sözlüğüyle burada çevrilir.
(function (root) {
  const APP = location.pathname.split('/').slice(-2, -1)[0]; // 'sshmaster' | 'ftpmaster'
  const BASE = `/api/tools/mt/${APP}`;
  const HASH_KEY = { sshmaster: 'ssh', ftpmaster: 'ftp' }[APP] || APP;
  const EMBEDDED = (() => { try { return window.parent !== window && window.parent.location.origin === location.origin; } catch { return false; } })();
  // mtweb (Mastertool web servisi): /web/config.js + mtweb.js window.MTWEB'i kurar. HEPGO'da yok → eski davranış.
  const WEB = root.MTWEB || null;
  const unauthorized = () => { try { (EMBEDDED ? window.parent : window).dispatchEvent(new Event('caymaz:unauthorized')); } catch { /* */ } };

  // --- Olaylar (ipcRenderer.on karşılığı) ---------------------------------------------------------
  const listeners = new Map();
  function on(ch) {
    return (cb) => {
      if (!listeners.has(ch)) listeners.set(ch, new Set());
      listeners.get(ch).add(cb);
      return () => listeners.get(ch).delete(cb);
    };
  }
  function emit(ch, data) {
    for (const cb of listeners.get(ch) || []) {
      try { cb(data); } catch (err) { console.error(err); }
    }
  }

  // --- Çeviri: sunucu {$t, $p} nesnelerini uygulamanın t() fonksiyonuyla metne çevirir -------------
  function tr(v) {
    if (Array.isArray(v)) return v.map(tr);
    if (v && typeof v === 'object') {
      if (typeof v.$t === 'string') {
        // t() ui.js'te üst düzey const olarak tanımlıdır (window özelliği değil): sözcüksel genel kapsamdan erişilir
        const fn = typeof t === 'function' ? t : (k) => k;   // eslint-disable-line no-undef
        return fn(v.$t, tr(v.$p || {}));
      }
      const out = {};
      for (const k of Object.keys(v)) out[k] = tr(v[k]);
      return out;
    }
    return v;
  }
  const errorOf = (e) => new Error(typeof e === 'string' ? e : tr(e) || 'Hata');

  // --- Açılış: dil ve depo senkron alınır (orijinalde ipcRenderer.sendSync('app:lang')) --------------
  function bootSync() {
    let lang = '';
    try { lang = localStorage.getItem('caymaz.lang') || ''; } catch { /* yok */ }
    if (WEB && WEB.lang) lang = WEB.lang;
    const xhr = new XMLHttpRequest();
    xhr.open('GET', `${BASE}/boot?lang=${encodeURIComponent(lang)}`, false);
    try { xhr.send(); } catch { /* ağ yok */ }
    if (xhr.status === 200) {
      try { return JSON.parse(xhr.responseText); } catch { /* bozuk */ }
    }
    if (WEB && xhr.status === 401) setTimeout(unauthorized, 0);
    const notice = WEB ? (xhr.status === 403 ? (WEB.t ? WEB.t('disabled') : 'Unavailable') : 'Mastertool')
      : xhr.status === 401 ? 'HEPGO oturumu açık değil. Lütfen yeniden giriş yapın.'
      : xhr.status === 403 ? 'Araçlar modülü yetkiniz yok.' : 'HEPGO sunucusuna ulaşılamadı.';
    setTimeout(() => {
      const el = document.createElement('div');
      el.style.cssText = 'position:fixed;inset:0;display:grid;place-items:center;background:#0b0f17;color:#e6edf6;font:15px system-ui;z-index:9999';
      el.textContent = notice;
      document.body.appendChild(el);
    }, 0);
    return { user: {}, lang: lang || 'tr', store: { folders: [], connections: [], shortcuts: [], settings: {} }, version: 'web', dead: true };
  }
  const boot = bootSync();
  let store = boot.store;

  // --- Gece / Gündüz / Sistem: Electron nativeTheme yerine stil sayfalarındaki prefers-color-scheme kuralları açılıp kapanır
  function applyAppTheme(v) {
    const mode = v === 'dark' || v === 'light' ? v : 'system';
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; }
      for (const r of rules) {
        if (!(r instanceof CSSMediaRule)) continue;
        const m = r.media.mediaText;
        const isLight = /prefers-color-scheme:\s*light/.test(m) || r.media.__mtLight;
        if (!isLight) continue;
        r.media.__mtLight = true;
        r.media.mediaText = mode === 'system' ? '(prefers-color-scheme: light)' : mode === 'light' ? 'all' : 'not all';
      }
    }
    document.documentElement.style.colorScheme = mode === 'system' ? '' : mode;
  }
  applyAppTheme((store.settings || {}).appTheme);
  window.addEventListener('load', () => applyAppTheme((store.settings || {}).appTheme));
  // Gömülü çerçeve masaüstü penceresinden alçak olabilir: uzun iletişim kutuları (bağlantı formu) kendi içinde kaydırılır
  const fit = document.createElement('style');
  fit.textContent = '.modal { max-height: calc(100vh - 24px); overflow: auto; }';
  document.head.appendChild(fit);

  // --- REST çağrısı (ipcRenderer.invoke karşılığı) --------------------------------------------------
  async function invoke(m, a) {
    const r = await fetch(`${BASE}/invoke`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin',
      body: JSON.stringify({ m, a: a === undefined ? null : a }),
    });
    let data = null;
    try { data = await r.json(); } catch { /* boş */ }
    if (r.status === 401) { if (WEB) unauthorized(); else if (EMBEDDED) window.parent.location.reload(); throw new Error('Oturum kapandı'); }
    if (!r.ok || !data) throw new Error((data && (data.detail || data.e)) || `İstek başarısız (${r.status})`);
    if (data.store) { store = data.store; emit('store:changed', store); }
    if (!data.ok) throw errorOf(data.e);
    return tr(data.v);
  }

  // --- WebSocket istemcisi: JSON çağrı/olay + ikili çerçeve ([1B uzunluk][bölme kimliği][veri]) ----------
  function wsClient(path) {
    let ws = null;
    let opening = null;
    let seq = 0;
    const pending = new Map();
    const evs = new Map();
    const binCbs = new Set();
    const closeCbs = new Set();
    const enc = new TextEncoder();
    const dec = new TextDecoder();

    function ensure() {
      if (ws && ws.readyState === WebSocket.OPEN) return Promise.resolve(ws);
      if (opening) return opening;
      opening = new Promise((resolve, reject) => {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const s = new WebSocket(`${proto}//${location.host}${path}`);
        s.binaryType = 'arraybuffer';
        s.onopen = () => { ws = s; opening = null; resolve(s); };
        s.onerror = () => { if (opening) { opening = null; reject(new Error('WebSocket bağlantısı kurulamadı')); } };
        s.onclose = () => {
          if (ws === s) ws = null;
          opening = null;
          for (const [, p] of pending) p.reject(new Error('Bağlantı kapandı'));
          pending.clear();
          closeCbs.forEach((cb) => cb());
        };
        s.onmessage = (e) => {
          if (e.data instanceof ArrayBuffer) {
            const u = new Uint8Array(e.data);
            const n = u[0];
            binCbs.forEach((cb) => cb(dec.decode(u.subarray(1, 1 + n)), u.subarray(1 + n)));
            return;
          }
          let obj;
          try { obj = JSON.parse(e.data); } catch { return; }
          if (obj.t === 'ret') {
            const p = pending.get(obj.id);
            if (!p) return;
            pending.delete(obj.id);
            if (obj.store) { store = obj.store; emit('store:changed', store); }
            if (obj.ok) p.resolve(tr(obj.v)); else p.reject(errorOf(obj.e));
          } else if (obj.t === 'ev') {
            for (const cb of evs.get(obj.ch) || []) cb(tr(obj.d));
          }
        };
      });
      return opening;
    }

    return {
      ensure,
      async call(m, a) {
        const s = await ensure();
        const id = ++seq;
        return new Promise((resolve, reject) => {
          pending.set(id, { resolve, reject });
          s.send(JSON.stringify({ t: 'call', id, m, a: a === undefined ? null : a }));
        });
      },
      send(m, a) { ensure().then((s) => s.send(JSON.stringify({ t: 'send', m, a: a === undefined ? null : a }))).catch(() => {}); },
      sendBinary(pane, data) {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        const p = enc.encode(pane);
        const d = typeof data === 'string' ? enc.encode(data) : data;
        const out = new Uint8Array(1 + p.length + d.length);
        out[0] = p.length;
        out.set(p, 1);
        out.set(d, 1 + p.length);
        ws.send(out);
      },
      on(ch) { return (cb) => { if (!evs.has(ch)) evs.set(ch, new Set()); evs.get(ch).add(cb); return () => evs.get(ch).delete(cb); }; },
      onBinary(cb) { binCbs.add(cb); return () => binCbs.delete(cb); },
      onClose(cb) { closeCbs.add(cb); return () => closeCbs.delete(cb); },
      close() { if (ws) ws.close(); },
    };
  }

  // --- Tarayıcıdan sürüklenen dosyalar: webUtils.getPathForFile yerine sentetik yol; aktarım öncesi HEPGO alanına yüklenir
  const pendingFiles = new Map(); // token -> File
  function pathForFile(file) {
    const token = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    pendingFiles.set(token, file);
    return `upload:${token}\\${file.name}`; // ad, `p.split('\\').pop()` ile okunabilsin
  }
  async function uploadToSpace(file, dir) {
    const fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('dir', dir);
    const r = await fetch(`${BASE}/files/upload`, { method: 'POST', body: fd, credentials: 'same-origin' });
    const data = await r.json().catch(() => null);
    if (!r.ok || !data) throw new Error((data && data.detail) || `Yükleme başarısız (${r.status})`);
    return data.path;
  }
  // 'upload:' yollarını gerçek H:\ yollarına çevirir (geçici klasör H:\.upload\<jeton>; aktarım bitince sunucu siler)
  async function resolvePaths(paths) {
    const out = [];
    for (const p of paths) {
      const m = /^upload:([a-z0-9]+)\\/.exec(p);
      if (!m) { out.push(p); continue; }
      const f = pendingFiles.get(m[1]);
      pendingFiles.delete(m[1]);
      if (!f) continue;
      out.push(await uploadToSpace(f, `H:\\.upload\\${m[1]}`));
    }
    return out;
  }
  function pickLocalFile(accept) {
    return new Promise((resolve) => {
      const inp = document.createElement('input');
      inp.type = 'file';
      if (accept) inp.accept = accept;
      inp.style.display = 'none';
      document.body.appendChild(inp);
      inp.onchange = () => { const f = inp.files[0] || null; inp.remove(); resolve(f); };
      // İletişim kutusu iptal edilince change gelmez; odak dönünce kısa süre sonra çözülür
      window.addEventListener('focus', () => setTimeout(() => { if (inp.parentNode) { inp.remove(); resolve(null); } }, 600), { once: true });
      inp.click();
    });
  }

  // --- Pencereler: gömülü iken HEPGO adres çubuğu (#/tools/ssh/term/…) değişir; bağımsız açıldıysa sayfa değişir ----
  function navigate(route, page) {
    if (EMBEDDED) window.parent.location.hash = `#/tools/${HASH_KEY}${route ? '/' + route : ''}`;
    else location.href = page;
  }
  const fileUrl = (p) => `${BASE}/files/download?path=${encodeURIComponent(p)}`;
  const chromeVer = (/Chrome\/(\d+[\d.]*)/.exec(navigator.userAgent) || [])[1] || '';
  const acctState = () => ({
    loggedIn: true, user: { email: boot.user.email || '', name: boot.user.name || '' }, email: boot.user.email || '',
    syncEnabled: false, state: 'off', lastSyncAt: null, notice: null, appVersion: boot.version,
  });
  const webQuery = () => `lang=${encodeURIComponent(boot.lang)}&theme=${matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'}`;

  // preload.js'in her iki uygulamada ortak olan üyeleri (uygulama bridge.js'i kendininkini ekler)
  function commonApi() {
    return {
      lang: boot.lang,
      version: boot.version,

      // hesap ve senkron: HEPGO oturumu kullanılır; senkron yok (bağlantılar zaten HEPGO'da saklanır)
      accountState: async () => acctState(),
      login: async () => ({ ok: true }),
      logout: async () => {
        if (WEB && WEB.logout) return WEB.logout();   // mtweb: Mastertool hesabından çıkış
        await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
        (EMBEDDED ? window.parent : window).location.href = '/';
      },
      syncNow: async () => {},
      setSyncEnabled: async () => ({ ok: false, code: 'web' }),
      deleteRemoteLibrary: async () => ({ ok: false, code: 'web' }),
      openWeb: async (page) => {
        const site = APP === 'ftpmaster' ? 'https://ftpmasters.com' : 'https://sshmasters.com';
        const allowed = { forgot: '/sifremi-unuttum', register: '/kayit', account: '/hesabim' };
        if (allowed[page]) window.open(`${site}${allowed[page]}?${webQuery()}&app=${APP === 'ftpmaster' ? 'fm' : 'sm'}`, '_blank', 'noopener');
      },
      openMastertool: async () => window.open(`https://mastertool.download/?${webQuery()}`, '_blank', 'noopener'),
      about: async () => ({ version: boot.version, electron: WEB ? 'Web' : 'HEPGO web', chrome: chromeVer, openAtLogin: false }),
      checkUpdate: async () => ({ ok: true, newer: false, latest: boot.version, version: boot.version }),
      openLicenses: async () => window.open('https://www.electronjs.org/docs/latest#license', '_blank', 'noopener'),
      onAccountStatus: (cb) => { const off = on('account:status')(cb); setTimeout(() => cb(acctState()), 0); return off; },
      onUpdateAvailable: on('app:update'),
      onLibraryBackup: on('account:backup'),

      // depo
      getStore: async () => store,
      onStoreChanged: on('store:changed'),
      setSettings: async (patch) => {
        const r = await invoke('settings:set', patch);
        if ('appTheme' in patch) applyAppTheme(patch.appTheme);
        if ('language' in patch) location.reload();
        return r;
      },

      // bağlantılar / klasörler
      saveConnection: (form) => invoke('conn:save', form),
      deleteConnection: (id) => invoke('conn:delete', id),
      duplicateConnection: (id) => invoke('conn:duplicate', id),
      moveConnection: (id, folderId) => invoke('conn:move', { id, folderId }),
      resetLastDir: (id) => invoke('conn:resetLastDir', id),
      testConnection: (form) => invoke('conn:test', form),
      pickKeyFile: async () => {
        const f = await pickLocalFile();
        return f ? uploadToSpace(f, 'H:\\.ssh') : null; // özel anahtar kişisel alanda H:\.ssh altında saklanır
      },
      saveFolder: (f) => invoke('folder:save', f),
      moveFolder: (id, parentId) => invoke('folder:move', { id, parentId }),
      deleteFolder: (id) => invoke('folder:delete', id),

      // yerel dosyalar = HEPGO kişisel alanı (H:\)
      localList: (dir) => invoke('local:list', dir),
      localDrives: () => invoke('local:drives'),
      localSpecial: () => invoke('local:special'),
      localOpen: async (p) => { if (await invoke('local:isFile', p)) window.open(fileUrl(p), '_blank'); },
      localReveal: async (p) => { if (await invoke('local:isFile', p)) window.open(fileUrl(p), '_blank'); },
      localMkdir: (p) => invoke('local:mkdir', p),
      pathForFile,

      clipboardWrite: async (t) => { try { await navigator.clipboard.writeText(String(t ?? '')); } catch { /* izin yok */ } },
      closeWindow: () => navigate('', 'index.html'),
    };
  }

  root.MTCore = { APP, BASE, EMBEDDED, WEB, boot, on, emit, tr, invoke, wsClient, commonApi, navigate, resolvePaths, applyAppTheme, getStore: () => store };
})(window);
