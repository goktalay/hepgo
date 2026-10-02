// Mikro ERP → sistem tek yönlü veri aktarımı. İki sekme: Cari Aktarımı ve Stok Aktarımı.
// Kullanıcı Mikro'daki kayıtları arar, seçtiklerini "Aktar" der. Daha önce aktarılanlar işaretli gelir;
// tekrar aktarılınca eşleşen yerel kayıt güncellenir. Sistem Mikro'ya HİÇBİR ŞEY yazmaz (yalnızca okur).
import { api } from '../api.js';
import { clear, confirmDialog, fmtDate, fmtDateTime, h, matches, pageHead, pref, setPref, toast, toastError } from '../ui.js';

const STOK_TYPES = [['SARF', 'Sarf malzeme'], ['YEDEK_PARCA', 'Yedek parça'], ['HAMMADDE', 'Hammadde'], ['DEMIRBAS', 'Demirbaş']];
const CARI_TIP = { tedarikci: ['Tedarikçi', 'green'], musteri: ['Müşteri', 'blue'], diger: ['Diğer', 'gray'] };
const num = v => (v == null ? '—' : (Math.round(Number(v) * 1000) / 1000).toLocaleString('tr-TR'));
const money = v => (v == null ? '—' : Number(v).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₺');
const shortDate = v => (v ? fmtDate(String(v).slice(0, 10)) : '—');

export async function render(view, params, ctx) {
  let status;
  try {
    status = await api.get('/api/mikro/status');
  } catch (err) { clear(view, h('div', { class: 'card empty' }, err.message)); return; }

  if (!status.configured) {
    clear(view, pageHead('Mikro ERP', { back: '#/', sub: 'Veri Aktarımı' }),
      h('div', { class: 'card empty' }, 'Mikro ERP bağlantısı tanımlı değil. Sunucu ayarlarında (.env) bağlantı bilgilerini girin.'));
    return;
  }
  const canImport = !!status.can_import;

  const count = h('span', { class: 'small muted', style: { marginLeft: 'auto' } });
  const setCount = s => { count.textContent = `Aktarılmış: ${s.imported?.cari || 0} cari · ${s.imported?.stok || 0} stok`; };
  if (status.ok) setCount(status);
  const refreshCount = async () => { try { setCount(await api.get('/api/mikro/status')); } catch { /* sessizce geç */ } };
  const banner = status.ok
    ? h('div', { class: 'mk-conn ok' }, h('span', { class: 'dot' }), `Bağlı · ${status.db || 'Mikro ERP'}`, count)
    : h('div', { class: 'mk-conn err' }, h('span', { class: 'dot' }), `Bağlanılamadı: ${status.error || 'bilinmeyen hata'}`);

  const TABS = [['cari', 'Cari'], ['stok', 'Stok'], ['alis', 'Alış Faturaları'], ['satis', 'Satış Faturaları']];
  const RENDER = { cari: cariTab, stok: stokTab, alis: r => faturaTab(r, 'alis'), satis: r => faturaTab(r, 'satis') };
  let tab = pref('mikro.tab', 'cari');
  if (!TABS.some(([k]) => k === tab)) tab = 'cari';
  const seg = h('div', { class: 'seg wrap' });
  const stage = h('div', { class: 'mk-stage' });
  const drawTabs = () => clear(seg, TABS.map(([k, l]) =>
    h('button', { class: k === tab ? 'on' : '', type: 'button', onclick: () => { tab = k; setPref('mikro.tab', k); drawTabs(); load(); } }, l)));

  const load = () => { clear(stage); RENDER[tab](stage, { canImport, onImported: refreshCount }); };

  // Senkron stoğunu sıfırla: eski "Stok Aktarımı" sayım hareketlerini siler; stok artık fatura hareketlerinden oluşur.
  const resetBtn = h('button', { class: 'btn ghost sm', type: 'button', title: 'Stok Aktarımı’nda yazılan Mikro senkron sayım hareketlerini siler (fatura hareketlerine dokunmaz)' }, 'Senkron stoğu sıfırla');
  resetBtn.addEventListener('click', async () => {
    if (!await confirmDialog('Senkron stoğu sıfırla', 'Daha önce “Stok Aktarımı” ile yazılan Mikro senkron stok miktarları (sayım hareketleri) silinecek. Fatura kaynaklı stok hareketleri korunur. Devam edilsin mi?', { okLabel: 'Sıfırla', danger: true })) return;
    try { const r = await api.post('/api/mikro/reset-stock', {}); toast(`${r.deleted} senkron stok hareketi silindi.`, 'success'); await refreshCount(); }
    catch (err) { toastError(err); }
  });

  clear(view, pageHead('Mikro ERP', { back: '#/', sub: 'Veri Aktarımı · tek yönlü', right: canImport ? resetBtn : null }),
    banner, h('div', { class: 'mk-tabs', style: { margin: '12px 0' } }, seg), stage);
  drawTabs();
  load();
}

// Ortak: arama + seçim + tablo kabuğu. cfg.columns(row)->hücreler, cfg.fetch(q)->satırlar, cfg.doImport(codes),
// cfg.key(row)->mikro kodu, cfg.head->başlık hücreleri, cfg.controls->tablo üstü ek kontrol (stok tipi/depo).
function tableScreen(root, cfg, canImport) {
  const search = h('input', { class: 'input', type: 'search', placeholder: cfg.placeholder, style: { flex: '1 1 240px', minWidth: '200px' } });
  const info = h('span', { class: 'small muted' });
  const selAll = h('input', { type: 'checkbox', title: 'Tümünü seç' });
  const btn = h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Aktar');
  const body = h('tbody');
  const table = h('table', { class: 'table mk-table' },
    h('thead', null, h('tr', null, h('th', { class: 'mk-chk' }, selAll), ...cfg.head)), body);
  const wrap = h('div', { class: 'card table-wrap' }, table);
  const selected = new Set();
  let rows = [];
  let hidden = 0;
  let showImported = false;
  const showChk = h('input', { type: 'checkbox' });
  showChk.addEventListener('change', () => { showImported = showChk.checked; run(); });
  const showTog = h('label', { class: 'mk-showimp' }, showChk, h('span', null, 'Aktarılanları da göster'));

  const updateBtn = () => {
    btn.disabled = !canImport || selected.size === 0;
    btn.textContent = selected.size ? `Aktar (${selected.size})` : 'Aktar';
  };
  const draw = () => {
    const q = search.value.trim();
    const shown = rows.filter(r => matches(q, ...cfg.searchFields(r)));
    clear(body, shown.length ? shown.map(r => rowEl(r)) : [h('tr', null, h('td', { class: 'muted', colspan: cfg.head.length + 1, style: { padding: '18px', textAlign: 'center' } }, 'Kayıt yok'))]);
    const codes = shown.map(cfg.key);
    selAll.checked = codes.length > 0 && codes.every(c => selected.has(c));
    info.textContent = `${shown.length} kayıt${selected.size ? ` · ${selected.size} seçili` : ''}`
      + (hidden && !showImported ? ` · ${hidden} aktarılmış gizli` : '');
    updateBtn();
  };
  const rowEl = r => {
    const code = cfg.key(r);
    const chk = h('input', { type: 'checkbox', checked: selected.has(code),
      onchange: e => { e.target.checked ? selected.add(code) : selected.delete(code); tr.classList.toggle('sel', e.target.checked); selAll.checked = false; info.textContent = `${rows.length} kayıt · ${selected.size} seçili`; updateBtn(); } });
    const badge = r.imported
      ? h('span', { class: 'badge green', title: r.imported_at ? `Aktarım: ${fmtDateTime(r.imported_at)}` : '' }, 'Aktarıldı')
      : h('span', { class: 'badge gray' }, 'Yeni');
    const tr = h('tr', { class: selected.has(code) ? 'sel' : '' }, h('td', { class: 'mk-chk' }, chk), ...cfg.columns(r), h('td', null, badge));
    return tr;
  };
  selAll.addEventListener('change', () => {
    const q = search.value.trim();
    rows.filter(r => matches(q, ...cfg.searchFields(r))).forEach(r => { const c = cfg.key(r); selAll.checked ? selected.add(c) : selected.delete(c); });
    draw();
  });
  let t;
  const run = async () => {
    clear(body, h('tr', null, h('td', { class: 'loading', colspan: cfg.head.length + 1, style: { padding: '18px' } }, 'Yükleniyor…')));
    try {
      const res = await cfg.fetch(search.value.trim(), showImported);
      rows = Array.isArray(res) ? res : (res.rows || []);
      hidden = Array.isArray(res) ? 0 : (res.hidden || 0);
      selected.forEach(c => { if (!rows.some(r => cfg.key(r) === c)) selected.delete(c); });
      draw();
    } catch (err) { clear(body, h('tr', null, h('td', { colspan: cfg.head.length + 1, style: { padding: '18px' } }, h('span', { class: 'muted' }, err.message)))); }
  };
  search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(run, 350); });

  btn.addEventListener('click', async () => {
    if (!selected.size) return;
    const codes = [...selected];
    const already = rows.filter(r => selected.has(cfg.key(r)) && r.imported).length;
    const msg = `${codes.length} kayıt aktarılacak${already ? ` (${already} tanesi daha önce aktarılmış, güncellenecek)` : ''}. ${cfg.confirmExtra ? cfg.confirmExtra() : ''}`;
    const ok = await confirmDialog('Aktarımı onayla', msg, { okLabel: 'Aktar' });
    if (!ok) return;
    btn.disabled = true; btn.textContent = 'Aktarılıyor…';
    try {
      const res = await cfg.doImport(codes);
      toast(`${res.added} yeni, ${res.updated} güncellendi.${res.unmapped ? ` (${res.unmapped} satır eşleşmedi, stok işlenmedi)` : ''}`, 'success');
      selected.clear();
      await run();
      cfg.onImported?.();
    } catch (err) { toastError(err); updateBtn(); }
  });

  const toolbar = h('div', { class: 'mk-toolbar' }, search, ...(cfg.controls || []), showTog, h('div', { class: 'spacer' }), info, btn);
  clear(root, toolbar, wrap);
  if (!canImport) btn.title = 'Aktarım yalnızca sistem sahibine (MASTER) açıktır';
  run();
}

function cariTab(root, { canImport, onImported }) {
  tableScreen(root, {
    onImported,
    placeholder: 'Cari kodu veya ünvan ara…',
    head: [h('th', null, 'Kod'), h('th', null, 'Ünvan'), h('th', null, 'Tip'), h('th', null, 'Telefon'), h('th', null, 'E-posta'), h('th', null, 'İl'), h('th', null, 'Durum')],
    searchFields: r => [r.cari_kod, r.cari_unvan1, r.cari_CepTel, r.il],
    key: r => r.cari_kod,
    columns: r => {
      const [lbl, tone] = CARI_TIP[r.tip] || CARI_TIP.diger;
      return [h('td', { class: 'mono small' }, r.cari_kod), h('td', { class: 'mk-name', title: r.cari_unvan1 || '' }, r.cari_unvan1 || '—'),
        h('td', null, h('span', { class: `badge ${tone}` }, lbl)),
        h('td', { class: 'small' }, (r.cari_CepTel || '').trim() || '—'),
        h('td', { class: 'small' }, (r.cari_EMail || '').trim() || '—'),
        h('td', { class: 'small' }, (r.il || '').trim() || '—')];
    },
    fetch: (q, si) => api.get(`/api/mikro/cari?q=${encodeURIComponent(q)}&show_imported=${si ? 1 : 0}`),
    doImport: codes => api.post('/api/mikro/import/cari', { codes }),
  }, canImport);
}

function stokTab(root, { canImport, onImported }) {
  const typeSel = h('select', { class: 'input', style: { width: 'auto' } }, STOK_TYPES.map(([v, l]) => h('option', { value: v }, l)));
  typeSel.value = pref('mikro.stokType', 'SARF');
  typeSel.addEventListener('change', () => setPref('mikro.stokType', typeSel.value));
  const setStock = h('input', { type: 'checkbox' });   // varsayılan kapalı: stok artık alış/satış faturalarından oluşur
  const setStockLbl = h('label', { class: 'mk-check', title: 'İşaretlenirse Mikro’daki güncel miktar Ana Depo’ya sayım olarak yazılır. Fatura bazlı stok kullanıyorsanız kapalı bırakın.' },
    setStock, h('span', null, 'Stok miktarını da aktar'));

  tableScreen(root, {
    onImported,
    placeholder: 'Stok kodu, isim veya marka ara…',
    controls: [h('label', { class: 'small muted', style: { alignSelf: 'center' } }, 'Tip:'), typeSel, setStockLbl],
    head: [h('th', null, 'Kod'), h('th', null, 'İsim'), h('th', null, 'Marka'), h('th', null, 'Barkod'), h('th', { class: 'right' }, 'Miktar'), h('th', null, 'Durum')],
    searchFields: r => [r.sto_kod, r.sto_isim, r.sto_marka_kodu, r.barkod],
    key: r => r.sto_kod,
    columns: r => [h('td', { class: 'mono small' }, r.sto_kod), h('td', { class: 'mk-name', title: r.sto_isim || '' }, r.sto_isim || '—'),
      h('td', { class: 'small' }, (r.sto_marka_kodu || '').trim() || '—'),
      h('td', { class: 'mono small' }, (r.barkod || '').trim() || '—'),
      h('td', { class: 'right' }, num(r.miktar))],
    confirmExtra: () => `Malzeme tipi: ${STOK_TYPES.find(t => t[0] === typeSel.value)[1]}.` + (setStock.checked ? ' Güncel stok miktarı Ana Depo’ya yazılacak.' : ''),
    fetch: (q, si) => api.get(`/api/mikro/stok?q=${encodeURIComponent(q)}&show_imported=${si ? 1 : 0}`),
    doImport: codes => api.post('/api/mikro/import/stok', { codes, type: typeSel.value, set_stock: setStock.checked }),
  }, canImport);
}

function faturaTab(root, kind) {
  const isAlis = kind === 'alis';
  const yon = isAlis ? 'stoğa giriş yapar' : 'stoktan çıkış yapar';
  const note = h('div', { class: 'mk-fat-note small muted' },
    isAlis ? 'Alış faturaları aktarıldığında eşleşen malzemeler için Ana Depo’ya stok girişi yapılır.'
           : 'Satış faturaları aktarıldığında eşleşen malzemeler için Ana Depo’dan stok çıkışı yapılır.');
  const wrap = h('div');
  tableScreen(wrap, {
    placeholder: 'Belge no, cari veya seri ara…',
    head: [h('th', null, 'Belge No'), h('th', null, 'Cari'), h('th', null, 'Tarih'), h('th', { class: 'right' }, 'Satır'), h('th', { class: 'right' }, 'Tutar'), h('th', null, 'Durum')],
    searchFields: r => [r.belge, r.cari, r.cari_ad, r.seri],
    key: r => r.evrak,
    columns: r => [h('td', { class: 'mono small' }, r.belge || r.evrak),
      h('td', { class: 'mk-name', title: r.cari_ad || r.cari || '' }, r.cari_ad || r.cari || '—'),
      h('td', { class: 'small' }, shortDate(r.tarih)),
      h('td', { class: 'right small' }, num(r.satir)),
      h('td', { class: 'right' }, money(r.tutar))],
    confirmExtra: () => `Aktarım, eşleşen malzemeler için ${yon} (Ana Depo).`,
    fetch: (q, si) => api.get(`/api/mikro/${kind}?q=${encodeURIComponent(q)}&show_imported=${si ? 1 : 0}`),
    doImport: evraks => api.post(`/api/mikro/import/${kind}`, { evraks }),
  }, true);
  clear(root, note, wrap);
}
