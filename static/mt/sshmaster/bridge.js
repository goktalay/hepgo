'use strict';

// SSH Master — HEPGO web köprüsü: preload.js'in window.api yüzeyi (aynı isim ve imzalar).
// Kabuk, SFTP ve aktarımlar tek WebSocket üzerinden (/ws/tools/ssh); her çağrı bölme kimliği (pane) taşır.
// Kabuk verisi ikili çerçevedir: [1B uzunluk][pane][veri]; xterm'e Uint8Array verilir (UTF-8 parçalanması bozulmaz).
(function () {
  const C = window.MTCore;
  const ws = C.wsClient('/ws/tools/ssh');
  const started = new Set(); // bu pencerede açılmış bölmeler (bağlantı düşerse hepsine ssh:closed verilir)

  const binListeners = new Set();
  ws.onBinary((pane, data) => binListeners.forEach((cb) => cb({ pane, data })));
  ws.onClose(() => {
    for (const pane of started) C.emit('ssh:closed', { pane });
    started.clear();
  });

  window.api = {
    ...C.commonApi(),

    // bağlantılar: terminal penceresi gömülü HEPGO'da #/tools/ssh/term/<id,id> rotasıdır
    setConnectionTheme: (id, theme) => C.invoke('conn:setTheme', { id, theme }),
    openConnection: async (ids) => {
      ids = (Array.isArray(ids) ? ids : [ids]).filter(Boolean);
      if (ids.length) C.navigate(`term/${ids.join(',')}`, `terminal.html?ids=${encodeURIComponent(ids.join(','))}`);
    },

    // kısayollar
    saveShortcut: (s) => C.invoke('shortcut:save', s),
    deleteShortcut: (id) => C.invoke('shortcut:delete', id),
    reorderShortcuts: (ids) => C.invoke('shortcut:reorder', ids),

    // terminal (her çağrı bir bölme kimliği "pane" taşır)
    sshStart: async (o) => {
      const r = await ws.call('ssh:start', o);
      if (r && r.ok) started.add(o.pane);
      return r;
    },
    sshWrite: (pane, data) => ws.sendBinary(pane, data),
    sshResize: (pane, cols, rows) => ws.send('ssh:resize', { pane, cols, rows }),
    sshStop: (pane) => { started.delete(pane); ws.send('ssh:stop', { pane }); },
    sshLastDir: (pane, dir) => ws.send('ssh:lastDir', { pane, dir }),
    onSshData: (cb) => { binListeners.add(cb); return () => binListeners.delete(cb); },
    onSshClosed: (cb) => {
      const a = ws.on('ssh:closed')((d) => { started.delete(d.pane); cb(d); });
      const b = C.on('ssh:closed')(cb);
      return () => { a(); b(); };
    },

    // uzak dosyalar (SFTP yan kanalı)
    sftpRealpath: (pane, p) => ws.call('sftp:realpath', { pane, p }),
    sftpList: (pane, dir) => ws.call('sftp:list', { pane, dir }),
    sftpStat: (pane, p) => ws.call('sftp:stat', { pane, p }),
    sftpDownload: (o) => ws.call('sftp:download', o), // { pane, id, remotePath, isDir, localDir }
    sftpUpload: async (o) => {                         // { pane, id, localPath, remoteDir } — tarayıcıdan sürüklenen dosya önce HEPGO alanına yüklenir
      const [localPath] = await C.resolvePaths([o.localPath]);
      if (!localPath) return { ok: false, message: 'Dosya okunamadı' };
      return ws.call('sftp:upload', { ...o, localPath });
    },
    transferCancel: (id) => ws.send('transfer:cancel', id),
    sftpMkdir: (pane, p) => ws.call('sftp:mkdir', { pane, p }),
    sftpRename: (pane, from, to) => ws.call('sftp:rename', { pane, from, to }),
    sftpDelete: (pane, p, isDir) => ws.call('sftp:delete', { pane, p, isDir }),
    onTransferProgress: ws.on('transfer:progress'),

    // pano
    clipboardRead: async () => { try { return await navigator.clipboard.readText(); } catch { return ''; } },
  };
})();
