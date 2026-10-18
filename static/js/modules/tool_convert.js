// Araçlar › Convert Master (web): görsel (Pillow), PDF↔görsel, metin kodlama/satır sonu, JSON↔CSV↔XLSX, base64/hex/url, birim.
// Sürükle-bırak yükleme; çıktı indirme bağlantısı (sunucuda 1 saat saklanır). Kodlama ve birim dönüşümü tarayıcıda.
import { api } from '../api.js';
import { clear, h, pageHead, toast, toastError } from '../ui.js';
import { btn, dropZone, fmtBytes, inp, lab, progress, sel, shell, uploadRaw } from './tool_mt.js';

const TABS = [['image', 'Görsel'], ['pdf', 'PDF'], ['text', 'Metin'], ['data', 'Veri (JSON/CSV/XLSX)'], ['enc', 'Base64 / Hex / URL'], ['unit', 'Birim']];
const UNITS = {
  'Uzunluk': { m: 1, km: 1000, cm: 0.01, mm: 0.001, mi: 1609.344, yd: 0.9144, ft: 0.3048, in: 0.0254, nmi: 1852 },
  'Ağırlık': { kg: 1, g: 0.001, mg: 1e-6, t: 1000, lb: 0.45359237, oz: 0.028349523125 },
  'Alan': { 'm²': 1, 'km²': 1e6, 'cm²': 1e-4, ha: 1e4, dönüm: 1000, 'ft²': 0.09290304, acre: 4046.8564224 },
  'Hacim': { L: 1, mL: 0.001, 'm³': 1000, gal: 3.785411784, 'fl oz': 0.0295735296, 'cup': 0.2365882365 },
  'Hız': { 'm/s': 1, 'km/h': 1 / 3.6, mph: 0.44704, knot: 0.514444, 'ft/s': 0.3048 },
  'Veri': { B: 1, KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3, TB: 1024 ** 4, bit: 1 / 8 },
  'Basınç': { Pa: 1, kPa: 1000, bar: 1e5, atm: 101325, psi: 6894.757, mmHg: 133.322 },
  'Sıcaklık': null,   // özel
};

export async function render(view, params, ctx) {
  let caps = {};
  const tabs = h('div', { class: 'mt-tabs' });
  const pane = h('div', { class: 'mt-panel' });
  let active = 'image';
  const draw = () => {
    clear(tabs, TABS.map(([k, l]) => h('button', { class: `mt-tab ${k === active ? 'on' : ''}`, type: 'button', onclick: () => { active = k; draw(); } }, l)));
    clear(pane, { image: imagePane, pdf: pdfPane, text: textPane, data: dataPane, enc: encPane, unit: unitPane }[active]());
  };

  // Ortak sonuç kutusu
  const resultBox = r => h('div', { class: 'mt-bar', style: { marginTop: '8px' } },
    h('a', { class: 'mt-btn ok', href: r.url, download: r.name }, '⬇ İndir: ' + r.name), h('span', { class: 'mt-status' }, fmtBytes(r.size),
      r.width ? ` · ${r.width}×${r.height}` : '', r.pages ? ` · ${r.pages} sayfa` : '', r.rows != null ? ` · ${r.rows} satır` : '', ' · 1 saat saklanır'));

  async function send(url, fd, prog) {
    try { const r = await uploadRaw(url, fd, pct => prog.set(pct)); return r; } catch (e) { toastError(e); return null; } finally { prog.done(); }
  }

  // --- Görsel ---
  function imagePane() {
    const fmt = sel((caps.image || ['png', 'jpg', 'webp', 'bmp', 'ico']).map(f => [f, f.toUpperCase()]), 'jpg');
    const w = inp({ cls: 'w-s', type: 'number', placeholder: 'genişlik' }), hh = inp({ cls: 'w-s', type: 'number', placeholder: 'yükseklik' });
    const q = inp({ cls: 'w-s', type: 'number', value: 88, min: 1, max: 100 });
    const keep = sel([['1', 'Oranı koru'], ['0', 'Tam boyut']], '1');
    const out = h('div'), prog = progress();
    const go = async files => {
      for (const f of files) {
        const fd = new FormData(); fd.append('file', f, f.name); fd.append('fmt', fmt.value); fd.append('quality', q.value); fd.append('keep_ratio', keep.value === '1');
        if (w.value) fd.append('width', w.value); if (hh.value) fd.append('height', hh.value);
        const r = await send('/api/tools/convert/image', fd, prog);
        if (r) out.prepend(resultBox(r));
      }
    };
    return [h('div', { class: 'mt-form' }, lab('Hedef biçim', fmt), lab('Genişlik', w), lab('Yükseklik', hh), lab('Kalite', q), lab('Boyutlandırma', keep)),
      h('div', { style: { marginTop: '8px' } }, dropZone('Görselleri sürükleyin (png/jpg/webp/bmp/gif/tiff/ico) — seçilen biçime dönüştürülür', go, { accept: 'image/*' })), prog, out];
  }

  // --- PDF ---
  function pdfPane() {
    const fmt = sel([['png', 'PNG'], ['jpg', 'JPG']], 'png'), dpi = inp({ cls: 'w-s', type: 'number', value: 150 });
    const out = h('div'), prog = progress();
    const go = async files => {
      const fd = new FormData(); files.forEach(f => fd.append('files', f, f.name)); fd.append('fmt', fmt.value); fd.append('dpi', dpi.value);
      const r = await send('/api/tools/convert/pdf', fd, prog);
      if (r) out.prepend(resultBox(r));
    };
    return [h('div', { class: 'mt-form' }, lab('PDF → görsel biçimi', fmt), lab('DPI', dpi),
      h('span', { class: `mt-status ${caps.pdf_to_image ? 'ok' : ''}` }, caps.pdf_to_image ? 'PDF→görsel ve görsel→PDF kullanılabilir' : (caps.pdf_note || ''))),
      h('div', { style: { marginTop: '8px' } }, dropZone('Birden çok görsel → tek PDF (sıra: seçim sırası) · ya da bir PDF → sayfa görselleri (zip)', go, { accept: 'image/*,.pdf' })), prog, out];
  }

  // --- Metin ---
  function textPane() {
    const encs = ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'cp1254', 'iso-8859-9', 'cp1252', 'iso-8859-1', 'cp1251', 'cp1256', 'ascii'].map(e => [e, e]);
    const from = sel(encs, 'utf-8'), to = sel(encs, 'utf-8'), eol = sel([['keep', 'Satır sonu: değiştirme'], ['lf', 'LF (Unix)'], ['crlf', 'CRLF (Windows)'], ['cr', 'CR']], 'keep');
    const area = h('textarea', { class: 'mt-area', placeholder: 'Metni yapıştırın ya da dosya sürükleyin' });
    const out = h('div'), prog = progress();
    const goText = async () => {
      const fd = new FormData(); fd.append('content', area.value); fd.append('enc_from', from.value); fd.append('enc_to', to.value); fd.append('eol', eol.value); fd.append('name', `metin-${to.value}.txt`);
      const r = await send('/api/tools/convert/text', fd, prog); if (r) out.prepend(resultBox(r));
    };
    const goFiles = async files => {
      for (const f of files) {
        const fd = new FormData(); fd.append('file', f, f.name); fd.append('enc_from', from.value); fd.append('enc_to', to.value); fd.append('eol', eol.value);
        const r = await send('/api/tools/convert/text', fd, prog); if (r) out.prepend(resultBox(r));
      }
    };
    return [h('div', { class: 'mt-form' }, lab('Kaynak kodlama', from), lab('Hedef kodlama', to), lab('Satır sonu', eol), btn('Metni dönüştür', { cls: 'primary', onclick: goText })),
      h('div', { style: { marginTop: '8px' } }, area), h('div', { style: { marginTop: '8px' } }, dropZone('Metin dosyalarını sürükleyin', goFiles)), prog, out];
  }

  // --- Veri ---
  function dataPane() {
    const src = sel([['json', 'JSON'], ['csv', 'CSV'], ['xlsx', 'XLSX']], 'json'), dst = sel([['csv', 'CSV'], ['json', 'JSON'], ['xlsx', 'XLSX']], 'csv');
    const delim = sel([['', 'CSV ayracı: otomatik'], [',', 'Virgül'], [';', 'Noktalı virgül'], ['\t', 'Sekme'], ['|', 'Dik çizgi']], '');
    const odelim = sel([[',', 'Çıkış ayracı: virgül'], [';', 'Noktalı virgül'], ['\t', 'Sekme']], ';');
    const objects = sel([['1', 'JSON: nesne listesi'], ['0', 'JSON: satır dizileri']], '1');
    const area = h('textarea', { class: 'mt-area', placeholder: '[{"ad": "Ali", "yas": 30}, …]  ya da CSV metni; XLSX için dosya sürükleyin' });
    const preview = h('pre', { class: 'mt-panel', style: { display: 'none', maxHeight: '240px', overflow: 'auto', fontSize: '12px' } });
    const out = h('div'), prog = progress();
    const fill = fd => { fd.append('src', src.value); fd.append('dst', dst.value); fd.append('delimiter', delim.value); fd.append('out_delimiter', odelim.value); fd.append('objects', objects.value === '1'); };
    const show = r => { if (!r) return; out.prepend(resultBox(r)); if (r.preview != null) { preview.style.display = ''; preview.textContent = r.preview; } };
    const goText = async () => { const fd = new FormData(); fd.append('content', area.value); fd.append('name', 'veri'); fill(fd); show(await send('/api/tools/convert/data', fd, prog)); };
    const goFiles = async files => {
      for (const f of files) {
        const ext = f.name.split('.').pop().toLowerCase(); if (['json', 'csv', 'xlsx'].includes(ext)) src.value = ext;
        const fd = new FormData(); fd.append('file', f, f.name); fill(fd); show(await send('/api/tools/convert/data', fd, prog));
      }
    };
    return [h('div', { class: 'mt-form' }, lab('Kaynak', src), lab('Hedef', dst), lab('CSV ayracı', delim), lab('Çıkış ayracı', odelim), lab('JSON biçimi', objects), btn('Metni dönüştür', { cls: 'primary', onclick: goText })),
      h('div', { style: { marginTop: '8px' } }, area), h('div', { style: { marginTop: '8px' } }, dropZone('JSON / CSV / XLSX dosyası sürükleyin (biçim uzantıdan seçilir)', goFiles, { accept: '.json,.csv,.xlsx' })), prog, out, preview];
  }

  // --- Base64 / Hex / URL (tarayıcıda) ---
  function encPane() {
    const mode = sel([['b64', 'Base64'], ['hex', 'Hex'], ['url', 'URL'], ['html', 'HTML varlıkları']], 'b64');
    const a = h('textarea', { class: 'mt-area', placeholder: 'Girdi' }), b = h('textarea', { class: 'mt-area', placeholder: 'Çıktı', readonly: true });
    const enc = new TextEncoder(), dec = new TextDecoder();
    const run = dir => {
      try {
        const s = a.value; let r;
        if (mode.value === 'b64') r = dir ? btoa(String.fromCharCode(...enc.encode(s))) : dec.decode(Uint8Array.from(atob(s.replace(/\s/g, '')), c => c.charCodeAt(0)));
        else if (mode.value === 'hex') r = dir ? [...enc.encode(s)].map(x => x.toString(16).padStart(2, '0')).join(' ') : dec.decode(Uint8Array.from(s.replace(/[^0-9a-f]/gi, '').match(/../g) || [], x => parseInt(x, 16)));
        else if (mode.value === 'url') r = dir ? encodeURIComponent(s) : decodeURIComponent(s.replace(/\+/g, ' '));
        else r = dir ? s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])) : h('textarea', { html: s }).value;
        b.value = r;
      } catch (e) { toastError(new Error('Dönüştürülemedi: ' + e.message)); }
    };
    return [h('div', { class: 'mt-form' }, lab('Tür', mode), btn('Kodla →', { cls: 'primary', onclick: () => run(true) }), btn('← Çöz', { onclick: () => run(false) }),
      btn('Çıktıyı kopyala', { cls: 'sm', onclick: async () => { try { await navigator.clipboard.writeText(b.value); toast('Kopyalandı'); } catch { /* */ } } }),
      btn('Takas', { cls: 'sm', onclick: () => { const t0 = a.value; a.value = b.value; b.value = t0; } })),
      h('div', { class: 'mt-split half', style: { marginTop: '8px' } }, a, b)];
  }

  // --- Birim ---
  function unitPane() {
    const cat = sel(Object.keys(UNITS).map(k => [k, k]), 'Uzunluk');
    const from = sel([], ''), to = sel([], '');
    const val = inp({ cls: 'w-m', type: 'number', value: 1, step: 'any' });
    const res = h('div', { class: 'mt-panel', style: { fontSize: '20px', marginTop: '8px' } });
    const temps = ['°C', '°F', 'K'];
    const fillUnits = () => {
      const names = UNITS[cat.value] ? Object.keys(UNITS[cat.value]) : temps;
      clear(from, names.map(n => h('option', { value: n }, n))); clear(to, names.map(n => h('option', { value: n }, n)));
      to.selectedIndex = Math.min(1, names.length - 1); calc();
    };
    const calc = () => {
      const v = Number(val.value); if (!Number.isFinite(v)) return;
      let r;
      if (!UNITS[cat.value]) {
        const c = from.value === '°C' ? v : from.value === '°F' ? (v - 32) * 5 / 9 : v - 273.15;
        r = to.value === '°C' ? c : to.value === '°F' ? c * 9 / 5 + 32 : c + 273.15;
      } else r = v * UNITS[cat.value][from.value] / UNITS[cat.value][to.value];
      res.textContent = `${v} ${from.value} = ${Number(r.toPrecision(10))} ${to.value}`;
    };
    [cat].forEach(e => e.addEventListener('change', fillUnits));
    [from, to, val].forEach(e => { e.addEventListener('change', calc); e.addEventListener('input', calc); });
    fillUnits();
    return [h('div', { class: 'mt-form' }, lab('Kategori', cat), lab('Değer', val), lab('Kaynak', from), lab('Hedef', to), btn('⇄', { cls: 'sm', onclick: () => { const t0 = from.value; from.value = to.value; to.value = t0; calc(); } })), res];
  }

  clear(view,
    pageHead('Convert Master', { back: '#/tools', sub: 'Görsel · PDF · metin kodlama · JSON/CSV/XLSX · Base64/Hex/URL · birim' }),
    shell(tabs, pane, h('div', { class: 'small muted' }, 'Dönüştürülen dosyalar sunucuda 1 saat saklanır, sonra silinir.')));
  try { caps = await api.get('/api/tools/convert/caps'); } catch (e) { toastError(e); }
  draw();
}
