'use strict';

// FTP Masters — HEPGO web köprüsü: preload.js'in window.api yüzeyi (aynı isim ve imzalar).
// Site penceresi (site.html?id=…) sunucuyla tek WebSocket üzerinden konuşur (/ws/tools/ftp?id=…);
// aktarım kuyruğu, bağlantı havuzu ve hız sınırı sunucu tarafındadır (orijinal session.js / remote.js / throttle.js mantığı).
(function () {
  const C = window.MTCore;
  const siteId = new URLSearchParams(location.search).get('id') || '';
  const ws = C.wsClient(`/ws/tools/ftp?id=${encodeURIComponent(siteId)}`);
  ws.onClose(() => C.emit('session:status', { state: 'disconnected' }));

  window.api = {
    ...C.commonApi(),

    showMain: async () => C.navigate('', 'index.html'),
    openConnection: async (id) => { if (id) C.navigate(`site/${id}`, `site.html?id=${encodeURIComponent(id)}`); },
    // Yerel klasör seçimi: kişisel alanda (H:\) yol yazılır
    pickFolder: async (defaultPath) => {
      const p = await window.prompt(t('form.localDir'), { label: 'H:\\…', value: defaultPath || 'H:\\', okText: t('common.ok'), iconName: 'folder' });
      return p || null;
    },

    // site penceresi: sunucu
    siteOpen: () => ws.call('site:open'),
    siteList: (dir, refresh) => ws.call('site:list', { dir, refresh }),
    siteStat: (p) => ws.call('site:stat', p),
    siteMkdir: (p) => ws.call('site:mkdir', p),
    siteRename: (from, to) => ws.call('site:rename', { from, to }),
    siteDelete: (items) => ws.call('site:delete', items),
    siteDownload: (items, localDir) => ws.call('site:download', { items, localDir }),
    siteUpload: async (paths, remoteDir) => ws.call('site:upload', { paths: await C.resolvePaths(paths), remoteDir }),
    siteLastDir: (remote, local) => ws.send('site:lastDir', { remote, local }),
    onSessionStatus: (cb) => { const a = ws.on('session:status')(cb); const b = C.on('session:status')(cb); return () => { a(); b(); }; },

    // aktarımlar
    onTransferUpdate: ws.on('transfer:update'),
    onTransferRootDone: ws.on('transfer:rootDone'),
    transferCancel: (id) => ws.send('transfer:cancel', id),
    transferCancelAll: () => ws.send('transfer:cancelAll'),
    transferRetry: (id) => ws.send('transfer:retry', id),
    transferClear: (ids) => ws.call('transfer:clear', ids),

    // yerel dosyalar (ek: yeniden adlandır, çöp kutusu = H:\.trash)
    localRename: (from, to) => C.invoke('local:rename', { from, to }),
    localTrash: (paths) => C.invoke('local:trash', paths),
  };
})();
