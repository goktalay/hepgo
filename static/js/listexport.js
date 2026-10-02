// Tüm listelerde sayfa başlığının en sağında "Excel" düğmesi: listeyi .xlsx olarak indirir.
// Kaynak: modül setListExport(fn) ile kendi verisini verdiyse o (kart görünümleri için); yoksa sayfadaki en büyük liste tablosu.
// Ekranda o an görünen (filtrelenmiş) satırlar aktarılır.
import { downloadXlsx } from './xlsx.js';

let custom = null;   // { fn, hash } — modülün kaydettiği dışa aktarıcı (sayfa değişince geçersiz)
export function setListExport(fn) { custom = fn ? { fn, hash: location.hash.split('?')[0] } : null; queue(); }

const TR_NUM = /^-?\d{1,3}(\.\d{3})*(,\d+)?$|^-?\d+(,\d+)?$/;
const TR_DATE = /^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?$/;
function typed(s) {
  const t = (s || '').replace(/\s+/g, ' ').trim();
  if (!t || /^[—–-]$/.test(t)) return '';
  const money = t.replace(/\s*(₺|TL)$/, '');
  if (TR_NUM.test(money) && !/^0\d/.test(money)) return Number(money.replace(/\./g, '').replace(',', '.'));
  const d = TR_DATE.exec(t);
  if (d) return new Date(+d[3], +d[2] - 1, +d[1], +(d[4] || 0), +(d[5] || 0));
  return t;
}
const cellText = td => {
  const f = td.querySelector('input:not([type=checkbox]), select, textarea');
  if (f) return f.tagName === 'SELECT' ? (f.selectedOptions[0]?.textContent || '') : f.value;
  return td.innerText;
};

function bestTable(view) {
  let best = null, n = 0;
  for (const t of view.querySelectorAll('table')) {
    if (t.closest('.modal, .print-area, .kv, .sc-ai-detail') || !t.offsetParent) continue;
    const rows = t.tBodies[0]?.rows.length || 0;
    if (rows > n) { best = t; n = rows; }
  }
  return best;
}
function tableSpec(t) {
  const head = t.tHead?.rows[0] ? [...t.tHead.rows[0].cells] : [];
  const label = c => c.textContent.replace(/\s+/g, ' ').trim();   // textContent: CSS büyük harf dönüşümü dosyaya geçmesin
  const keep = head.map((c, i) => (label(c) ? i : -1)).filter(i => i >= 0);   // başlıksız (düğme) sütunları atla
  const columns = keep.map(i => label(head[i]));
  const rows = [];
  for (const tr of t.tBodies[0]?.rows || []) {
    if (tr.cells.length === 1 && tr.cells[0].colSpan > 1) continue;   // ara başlık / boş satır
    const cells = [...tr.cells];
    rows.push((keep.length ? keep : cells.map((_, i) => i)).map(i => typed(cells[i] ? cellText(cells[i]) : '')));
  }
  return { columns: columns.length ? columns : rows[0]?.map((_, i) => `Sütun ${i + 1}`) || [], rows };
}

function exporter(view) {
  if (/^#\/(sysconfig|settings)\b/.test(location.hash)) return null;   // ayar ekranlarında düğme yok
  if (custom && custom.hash === location.hash.split('?')[0]) return () => custom.fn();
  const t = bestTable(view);
  return t ? () => tableSpec(t) : null;
}

function title(view) {
  return (view.querySelector('.page-head h1')?.innerText || document.title || 'Liste').trim();
}

const XL_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3" fill="#1d6f42"/><path d="M8 7.5l3.2 4.5L8 16.5h2.3l2-3 2 3H16.6l-3.2-4.5 3.2-4.5h-2.3l-2 3-2-3z" fill="#fff"/></svg>';

let queued = false;
function queue() { if (!queued) { queued = true; requestAnimationFrame(sweep); } }
function sweep() {
  queued = false;
  const view = document.getElementById('view');
  if (!view) return;
  const headEl = view.querySelector('.page-head');
  const ex = headEl ? exporter(view) : null;
  let btn = view.querySelector('.xl-btn');
  if (!ex || !headEl) { btn?.remove(); return; }
  // Excel, alt-modül toolbar'ındaki düğme baloncuğuna (pill-group) girer; o yoksa toolbar'a; o da yoksa başlık bandına.
  const host = view.querySelector('.module-toolbar .module-pills') || view.querySelector('.module-toolbar') || headEl;
  if (btn && btn.parentElement === host) return;
  btn?.remove();
  btn = document.createElement('button');
  btn.type = 'button'; btn.className = 'btn xl-btn'; btn.title = 'Listeyi Excel olarak indir';
  btn.innerHTML = `${XL_ICON}<span>Excel</span>`;
  btn.addEventListener('click', () => {
    const fn = exporter(view);
    if (!fn) return;
    const spec = fn();
    if (!spec?.rows?.length) { window.dispatchEvent(new CustomEvent('caymaz:toast', { detail: 'Aktarılacak satır yok' })); return; }
    const t = title(view);
    const d = new Date(), pad = n => String(n).padStart(2, '0');
    downloadXlsx({ sheet: t, ...spec }, `${t} ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`);
  });
  host.append(btn);   // alt-modül toolbar'ı (varsa), yoksa başlık bandı
}

export function enableListExport() {
  window.addEventListener('hashchange', () => { if (custom && custom.hash !== location.hash.split('?')[0]) custom = null; });
  new MutationObserver(queue).observe(document.body, { childList: true, subtree: true });
  queue();
}
