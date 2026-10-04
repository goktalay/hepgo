// Proje kararı: her finansal hareket (cari / kasa / banka hareketi, fatura, Satın Alma belgesi) için "Projesiz", tek proje,
// tutar bölüşümü ya da kalem bazında (alış faturasındaki malzemeler / muhasebe satırları) proje seçimi.
// Proje bir gruplamadır; karar yalnızca etiket yazar, hareketi değiştirmez.
import { api } from '../api.js';
import { clear, field, fmtDate, h, modal, segmented, t, toast } from '../ui.js';

export const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 2 }).format(n || 0);
const NAT = { gelir: ['Gelir', 'green'], gider: ['Gider', 'red'], odeme: ['Tahsilat / ödeme', 'blue'] };
export const natureBadge = n => h('span', { class: `badge ${NAT[n]?.[1] || ''}` }, NAT[n]?.[0] || n);

// Hareket tablolarındaki proje hücresi: karar yoksa "Proje?" uyarısı
export function projectChip(tags, onClick) {
  const named = (tags || []).filter(x => x.project_id);
  const label = !tags || !tags.length ? t('Proje?') : named.length ? named.map(x => x.code || x.name).filter((v, i, a) => a.indexOf(v) === i).join(', ') : t('Projesiz');
  const cls = !tags || !tags.length ? 'none' : named.length ? 'set' : 'free';
  return h('button', { class: `pj-chip ${cls}`, type: 'button', title: named.map(x => x.name).join(', ') || label, onclick: e => { e.stopPropagation(); onClick?.(); } }, label);
}

const projOpts = (projects, sel, empty = '— Proje seçin —') => [h('option', { value: '' }, empty), ...projects.map(p => h('option', { value: p.id, selected: p.id === sel }, `${p.code ? `${p.code} · ` : ''}${p.name}`))];

export async function decideModal(source, ref, done) {
  let m;
  try { m = await api.get(`/api/projects/movement/one?source=${source}&ref=${ref}`); } catch (e) { return toast(e.message, 'err'); }
  const cur = m.tags || [];
  const lineTags = cur.filter(x => x.line_ref);
  const named = cur.filter(x => x.project_id && !x.line_ref);
  let mode = !cur.length ? 'one' : lineTags.length ? 'lines' : named.length > 1 || (named.length === 1 && cur.length > 1) ? 'split' : named.length ? 'one' : 'none';
  const pane = h('div');
  const one = h('select', { class: 'input' }, projOpts(m.projects, named[0]?.project_id));
  const splitRows = h('div', { class: 'pj-split' });
  const splitInfo = h('div', { class: 'small muted' });
  const rows = [];
  const recalc = () => {
    const s = rows.reduce((a, r) => a + (Number(r.amt.value) || 0), 0);
    const rest = Math.round((m.amount - s) * 100) / 100;
    clear(splitInfo, t('Dağıtılan {a} / {b}', { a: money(s), b: money(m.amount) }), rest > 0.009 ? t(' · kalan {r} projesiz sayılır', { r: money(rest) }) : rest < -0.009 ? h('span', { class: 'fin-late' }, t(' · fazla {r}', { r: money(-rest) })) : ' ✓');
  };
  const addRow = (pid, amount) => {
    const sel = h('select', { class: 'input' }, projOpts(m.projects, pid));
    const amt = h('input', { class: 'input', type: 'number', step: '0.01', min: 0, value: amount ?? '' });
    amt.addEventListener('input', recalc);
    const row = { sel, amt, el: h('div', { class: 'pj-split-row' }, sel, amt, h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { rows.splice(rows.indexOf(row), 1); row.el.remove(); recalc(); } }, '×')) };
    rows.push(row); splitRows.append(row.el); recalc();
  };
  (named.length ? named : [{}]).forEach(x => addRow(x.project_id, x.amount));
  const lineSel = new Map();
  const linesBox = h('div', { class: 'pj-lines' }, m.lines.map(ln => {
    const s = h('select', { class: 'input' }, projOpts(m.projects, lineTags.find(x => x.line_ref === ln.line_ref)?.project_id, '— Projesiz —'));
    lineSel.set(ln.line_ref, s);
    return h('div', { class: 'pj-line' }, h('span', null, ln.desc), h('b', null, money(ln.net)), s);
  }));
  const draw = () => clear(pane,
    mode === 'none' ? h('p', { class: 'muted' }, 'Bu hareket hiçbir projeye ait değil olarak işaretlenir.')
      : mode === 'one' ? field('Proje', one)
        : mode === 'split' ? h('div', null, splitRows, h('div', { class: 'ct-acts' }, h('button', { class: 'btn sm', type: 'button', onclick: () => addRow(null, null) }, '＋ Proje ekle'), splitInfo))
          : h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Proje için alınan kalemleri seçin; seçilmeyen kalemler projesiz sayılır.'), linesBox));
  const modes = [['none', 'Projesiz'], ['one', 'Tek proje'], ['split', 'Tutarı böl']];
  if (m.lines.length) modes.push(['lines', 'Kalem bazında']);
  const seg = segmented(modes, mode, v => { mode = v; draw(); });
  const actions = [{ label: 'Vazgeç' }];
  if (cur.length) actions.push({ label: 'Kararı kaldır', class: 'danger', onClick: async () => { await api.del(`/api/projects/decide?source=${source}&ref=${ref}`); toast('Proje kararı kaldırıldı'); done?.(); } });
  actions.push({ label: 'Kaydet', class: 'primary', onClick: async () => {
    let allocations;
    if (mode === 'none') allocations = [{ project_id: null }];
    else if (mode === 'one') {
      if (!one.value) throw new Error(t('Proje seçin ya da “Projesiz” deyin'));
      allocations = [{ project_id: Number(one.value) }];
    } else if (mode === 'split') {
      allocations = rows.filter(r => r.sel.value && Number(r.amt.value) > 0).map(r => ({ project_id: Number(r.sel.value), amount: Number(r.amt.value) }));
      if (!allocations.length) throw new Error(t('En az bir proje ve tutar girin'));
      if (allocations.length === 1 && Math.abs(allocations[0].amount - m.amount) < 0.01) allocations = [{ project_id: allocations[0].project_id }];
    } else {
      allocations = [...lineSel].filter(([, s]) => s.value).map(([line_ref, s]) => ({ project_id: Number(s.value), line_ref }));
      if (!allocations.length) allocations = [{ project_id: null }];
    }
    await api.put('/api/projects/decide', { source, ref, allocations });
    toast('Proje kararı kaydedildi', 'success'); done?.();
  } });
  modal({ title: 'Hareketin projesi', wide: true, body: h('div', null,
    h('div', { class: 'fl-mv-info' }, h('div', null, natureBadge(m.nature), ' ', h('b', null, m.title)),
      h('div', { class: 'small muted' }, [fmtDate(m.date), m.account, m.doc_no].filter(Boolean).join(' · ')),
      h('div', { class: 'fl-mv-big' }, money(m.amount)),
      m.nature !== 'odeme' ? h('div', { class: 'small muted' }, m.net_exact ? t('KDV hariç {n} (proje kâr-zararına bu tutar girer)', { n: money(m.net) }) : t('KDV ayrıştırılamadı; brüt tutar kullanılır')) : h('div', { class: 'small muted' }, 'Tahsilat / ödeme: proje nakit akışında görünür, kâr-zarara girmez.')),
    h('div', { style: { margin: '10px 0' } }, seg), pane), actions });
  draw();
}

// Elle girilen hareket / fatura formları için zorunlu proje seçimi (— seçin — / Projesiz / proje)
export async function projectSelect(required = true) {
  let list = [];
  try { list = await api.get('/api/projects/options'); } catch { return null; }   // proje modülüne erişim yoksa sorulmaz
  const sel = h('select', { class: 'input' }, h('option', { value: '' }, required ? '— Proje seçin (zorunlu) —' : '— Proje —'), h('option', { value: 'none' }, 'Projesiz'),
    list.map(p => h('option', { value: p.id }, `${p.code ? `${p.code} · ` : ''}${p.name}`)));
  sel.payload = () => {
    if (!sel.value) { if (required) throw new Error(t('Proje seçin ya da “Projesiz” seçeneğini işaretleyin')); return {}; }
    return sel.value === 'none' ? { project_none: true } : { project_id: Number(sel.value) };
  };
  return sel;
}
