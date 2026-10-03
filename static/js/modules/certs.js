// Sertifikasyon: şirketin sahip olduğu ve almaya çalıştığı sertifikalar (ISO 9001, tesis güvenlik, üretim izni…).
// Liste A4 dikey kartlar (taranmış görsel); detayda bilgiler, yüzlerce doküman (klasörlü, toplu yükleme) ve denetimler.
import { api, fileUrl, upload, uploadLarge } from '../api.js';
import { clear, confirmDialog, field, fmtDate, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, segmented, statStrip, toast, toastError } from '../ui.js';

const SUBS = [['list', 'Sertifikalar'], ['audits', 'Denetimler']];
const ST_TONE = { hazirlik: '', basvuru: 'blue', gecerli: 'green', askida: 'yellow', suresi_doldu: 'red', iptal: '' };
const RES_TONE = { planlandi: 'blue', basarili: 'green', sartli: 'yellow', basarisiz: 'red', iptal: '' };
let META = null;

const left = (days, status) => {
  if (days == null || !['gecerli', 'askida'].includes(status)) return null;
  const cls = days < 0 ? 'red' : days <= 90 ? 'yellow' : 'green';
  const txt = days < 0 ? `${-days} gün önce doldu` : days === 0 ? 'Bugün doluyor' : `${days} gün kaldı`;
  return h('span', { class: `cf-left ${cls}` }, txt);
};
const size = n => (n == null ? '' : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`);
const ext = n => (String(n).split('.').pop() || '').toLowerCase();
const EXT_TONE = { pdf: '#e11d48', doc: '#2563eb', docx: '#2563eb', xls: '#16a34a', xlsx: '#16a34a', csv: '#16a34a', ppt: '#ea580c', pptx: '#ea580c',
  jpg: '#7c3aed', jpeg: '#7c3aed', png: '#7c3aed', webp: '#7c3aed', heic: '#7c3aed', tif: '#7c3aed', tiff: '#7c3aed', zip: '#64748b', rar: '#64748b', '7z': '#64748b' };
const extBadge = n => { const e = ext(n); return h('span', { class: 'cf-ext', style: { background: EXT_TONE[e] || '#475569' } }, (e || '?').slice(0, 4).toUpperCase()); };
const badge = (map, tone, k) => h('span', { class: `badge ${tone[k] || ''}` }, map?.[k] || k);

export async function render(view, params, ctx) {
  if (/^\d+$/.test(params[0] || '')) return detail(view, Number(params[0]), ctx);
  const sub = params[0] === 'audits' ? 'audits' : 'list';
  const nav = segmented(SUBS, sub, v => { location.hash = v === 'list' ? '#/certs' : `#/certs/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Sertifikasyon', { back: '#/', sub: 'Sertifikalar, başvurular, dokümanlar ve denetimler', tabs: nav }), body);
  return sub === 'audits' ? auditsView(body) : listView(body);
}

// ---------------- Sertifikalar (A4 kartlar) ----------------
async function listView(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get('/api/certs'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  META = d;
  let filter = 'all', q = '';
  const rows = d.rows;
  const soon = r => ['gecerli', 'askida'].includes(r.status) && r.days_left != null && r.days_left <= 90;
  const strip = statStrip();
  strip.set([{ label: 'Toplam sertifika', value: rows.length },
    { label: 'Geçerli', value: rows.filter(r => r.status === 'gecerli').length, tone: 'ok' },
    { label: 'Başvuru / hazırlık', value: rows.filter(r => ['basvuru', 'hazirlik'].includes(r.status)).length },
    { label: '90 gün içinde dolacak', value: rows.filter(r => soon(r) && r.days_left >= 0).length, tone: rows.some(r => soon(r) && r.days_left >= 0) ? 'alert' : '' },
    { label: 'Yaklaşan denetim', value: rows.filter(r => r.next_audit).length }]);
  const grid = h('div', { class: 'cf-grid' });
  const draw = () => {
    const shown = rows.filter(r => (filter === 'all' || (filter === 'gecerli' && r.status === 'gecerli') || (filter === 'surec' && ['basvuru', 'hazirlik'].includes(r.status))
      || (filter === 'yaklasan' && soon(r) && r.days_left >= 0) || (filter === 'dolmus' && (r.status === 'suresi_doldu' || (soon(r) && r.days_left < 0))))
      && matches(q, r.name, r.standard, r.issuer, r.cert_no));
    clear(grid, shown.length ? shown.map(card) : h('div', { class: 'card empty', style: { gridColumn: '1/-1' } },
      rows.length ? 'Bu filtrede sertifika yok.' : 'Henüz sertifika yok. “＋ Yeni sertifika” ile ekleyin; taranmış belgeyi A4 dikey görsel olarak yükleyin.'));
  };
  const card = r => h('a', { class: 'cf-card', href: `#/certs/${r.id}` },
    h('div', { class: 'cf-a4' }, r.image ? h('img', { src: fileUrl(r.image, 512), alt: '', loading: 'lazy' })
      : h('div', { class: 'cf-ph' }, h('span', null, '📄'), h('small', null, 'Tarama yok')),
      h('span', { class: 'cf-st' }, badge(META.statuses, ST_TONE, r.status))),
    h('div', { class: 'cf-meta' }, h('b', null, r.name), h('small', { class: 'muted' }, [r.standard, r.issuer].filter(Boolean).join(' · ') || '—'),
      h('div', { class: 'cf-line' }, left(r.days_left, r.status) || (r.apply_date && ['basvuru', 'hazirlik'].includes(r.status) ? h('span', { class: 'cf-left blue' }, `Başvuru ${fmtDate(r.apply_date)}`) : null),
        h('span', { class: 'cf-count', title: 'Doküman / denetim' }, `📎 ${r.doc_count} · 🔎 ${r.audit_count}`))));
  const filt = segmented([['all', 'Tümü'], ['gecerli', 'Geçerli'], ['surec', 'Başvuru süreci'], ['yaklasan', 'Süresi yaklaşan'], ['dolmus', 'Süresi dolmuş']], 'all', v => { filter = v; draw(); });
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Sertifika, standart, kuruluş ara…', style: { maxWidth: '260px' } });
  search.addEventListener('input', () => { q = search.value.trim(); draw(); });
  clear(view, moduleToolbar(h('button', { class: 'btn primary', type: 'button', onclick: () => certForm(null, id => { location.hash = `#/certs/${id}`; }) }, '＋ Yeni sertifika')),
    strip, h('div', { class: 'filters' }, filt, search), grid);
  draw();
}

function certForm(c, done) {
  const isNew = !c;
  c = c || { status: 'gecerli' };
  const v = k => c[k] || '';
  const name = h('input', { class: 'input', value: v('name'), placeholder: 'ör. ISO 9001 Kalite Yönetim Sistemi' });
  const standard = h('input', { class: 'input', value: v('standard'), placeholder: 'ör. ISO 9001:2015' });
  const issuer = h('input', { class: 'input', value: v('issuer'), placeholder: 'Belgelendirme kuruluşu / kurum' });
  const certNo = h('input', { class: 'input', value: v('cert_no') });
  const status = h('select', { class: 'input' }, Object.entries(META?.statuses || {}).map(([k, l]) => h('option', { value: k, selected: k === c.status }, l)));
  const apply = h('input', { class: 'input', type: 'date', value: v('apply_date') });
  const issue = h('input', { class: 'input', type: 'date', value: v('issue_date') });
  const expiry = h('input', { class: 'input', type: 'date', value: v('expiry_date') });
  const scope = h('textarea', { class: 'input', rows: 2, placeholder: 'Kapsam (ör. tasarım, üretim ve satış faaliyetleri)' }); scope.value = v('scope');
  const note = h('textarea', { class: 'input', rows: 2 }); note.value = v('note');
  const img = h('input', { type: 'file', accept: 'image/*' });
  const prev = h('div', { class: 'cf-a4 cf-a4-sm' }, c.image ? h('img', { src: fileUrl(c.image, 512), alt: '' }) : h('div', { class: 'cf-ph' }, h('span', null, '📄'), h('small', null, 'A4 dikey tarama')));
  img.addEventListener('change', () => { const f = img.files[0]; if (f) clear(prev, h('img', { src: URL.createObjectURL(f), alt: '' })); });
  modal({ title: isNew ? 'Yeni sertifika' : 'Sertifika bilgileri', wide: true,
    body: h('div', { class: 'cf-form' }, h('div', { class: 'cf-form-img' }, prev, h('label', { class: 'btn sm' }, 'Tarama seç', img), h('small', { class: 'muted' }, 'Belge A4 dikey olarak gösterilir')),
      h('div', { class: 'cf-form-f' }, field('Sertifika adı', name), h('div', { class: 'cf-2' }, field('Standart', standard), field('Belge no', certNo)),
        h('div', { class: 'cf-2' }, field('Kuruluş', issuer), field('Durum', status)),
        h('div', { class: 'cf-3' }, field('Başvuru tarihi', apply), field('Belge tarihi', issue), field('Geçerlilik bitişi', expiry)),
        field('Kapsam', scope), field('Not', note))),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const b = { name: name.value, standard: standard.value, issuer: issuer.value, cert_no: certNo.value, status: status.value,
        apply_date: apply.value || null, issue_date: issue.value || null, expiry_date: expiry.value || null, scope: scope.value, note: note.value };
      let id = c.id;
      if (isNew) id = (await api.post('/api/certs', b)).id; else await api.put(`/api/certs/${id}`, b);
      if (img.files[0]) { const fd = new FormData(); fd.append('file', img.files[0]); await upload(`/api/certs/${id}/image`, fd); }
      toast('Kaydedildi', 'success'); done?.(id);
    } }] });
}

// ---------------- Sertifika detayı ----------------
async function detail(view, id, ctx) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let c;
  try { if (!META) META = await api.get('/api/certs'); c = await api.get(`/api/certs/${id}`); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const reload = () => detail(view, id, ctx);
  let tab = location.hash.includes('?audits') ? 'audits' : 'docs';
  const pane = h('div');
  const tabs = segmented([['docs', `Dokümanlar (${c.doc_count})`], ['audits', `Denetimler (${c.audit_count})`]], tab, v => { tab = v; drawTab(); }, { tabs: true });
  const drawTab = () => (tab === 'docs' ? docsPane(pane, c, null, reload) : auditsPane(pane, c, reload));
  const imgBox = h('div', { class: 'cf-a4 cf-a4-lg', onclick: () => c.image && bigImage(c) }, c.image ? h('img', { src: fileUrl(c.image, 1024), alt: '' })
    : h('div', { class: 'cf-ph' }, h('span', null, '📄'), h('small', null, 'Taranmış sertifika yok')));
  const imgIn = h('input', { type: 'file', accept: 'image/*', hidden: true });
  imgIn.addEventListener('change', async () => {
    if (!imgIn.files[0]) return;
    const fd = new FormData(); fd.append('file', imgIn.files[0]);
    try { await upload(`/api/certs/${id}/image`, fd); toast('Görsel güncellendi', 'success'); reload(); } catch (e) { toastError(e); }
  });
  const kv = (k, v2) => (v2 ? [h('dt', null, k), h('dd', null, v2)] : null);
  clear(view,
    h('div', { class: 'cf-head' }, h('a', { class: 'small', href: '#/certs' }, '← Sertifikalar')),
    h('div', { class: 'cf-detail' },
      h('aside', { class: 'cf-side' }, imgBox, h('div', { class: 'cf-side-acts' }, h('button', { class: 'btn sm', type: 'button', onclick: () => imgIn.click() }, c.image ? 'Taramayı değiştir' : 'Tarama yükle'), imgIn,
        c.image ? h('a', { class: 'btn sm', href: `${fileUrl(c.image)}?dl=1` }, 'İndir') : null),
        h('section', { class: 'card card-pad cf-info' },
          h('div', { class: 'cf-info-h' }, h('h3', null, c.name), badge(META.statuses, ST_TONE, c.status)),
          left(c.days_left, c.status),
          h('dl', { class: 'sys-kv' }, kv('Standart', c.standard), kv('Belge no', c.cert_no), kv('Kuruluş', c.issuer),
            kv('Başvuru tarihi', c.apply_date && fmtDate(c.apply_date)), kv('Belge tarihi', c.issue_date && fmtDate(c.issue_date)),
            kv('Geçerlilik bitişi', c.expiry_date && fmtDate(c.expiry_date)), kv('Sonraki denetim', c.next_audit && fmtDate(c.next_audit)), kv('Kapsam', c.scope), kv('Not', c.note)),
          h('div', { class: 'ct-acts' }, h('button', { class: 'btn sm primary', type: 'button', onclick: () => certForm(c, reload) }, 'Düzenle'),
            h('button', { class: 'btn sm ghost', type: 'button', onclick: () => deleteCert(c) }, 'Sil')))),
      h('section', { class: 'cf-main' }, h('div', { class: 'cf-tabs' }, tabs), pane)));
  drawTab();
}

function bigImage(c) {
  modal({ title: c.name, wide: true, body: h('div', { class: 'cf-big' }, h('img', { src: fileUrl(c.image), alt: '' })),
    actions: [{ label: 'İndir', onClick: () => { location.href = `${fileUrl(c.image)}?dl=1`; return true; } }, { label: 'Kapat', class: 'primary' }] });
}

function deleteCert(c) {
  const inp = h('input', { class: 'input', placeholder: c.name });
  modal({ title: 'Sertifikayı sil', body: h('div', null, h('p', null, `“${c.name}” ve ona ait ${c.doc_count} doküman ile ${c.audit_count} denetim kalıcı olarak silinecek. Onaylamak için sertifika adını yazın:`), inp),
    actions: [{ label: 'Vazgeç' }, { label: 'Sil', class: 'danger', onClick: async () => {
      await api.del(`/api/certs/${c.id}?confirm=${encodeURIComponent(inp.value)}`); toast('Silindi'); location.hash = '#/certs';
    } }] });
}

// ---- Dokümanlar (sertifikaya ya da bir denetime ait)
async function docsPane(root, c, audit, reload) {
  clear(root, h('div', { class: 'loading' }, 'Yükleniyor…'));
  let docs;
  try { docs = await api.get(`/api/certs/${c.id}/docs${audit ? `?audit_id=${audit.id}` : ''}`); } catch (e) { return clear(root, h('div', { class: 'card empty' }, e.message)); }
  let folder = '', q = '';
  const folders = [...new Set(docs.map(d => d.folder).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'tr'));
  const list = h('div', { class: 'card table-wrap' });
  const queue = h('div', { class: 'cf-queue' });
  const drawList = () => {
    const shown = docs.filter(d => (!folder || (folder === '__audit' ? d.audit_id : d.folder === folder)) && matches(q, d.name, d.folder));
    clear(list, shown.length ? h('table', { class: 'table cf-docs' },
      h('thead', null, h('tr', null, ['', 'Doküman', 'Klasör', 'Boyut', 'Yükleyen', ''].map(x => h('th', null, x)))),
      h('tbody', null, shown.map(d => h('tr', null, h('td', null, extBadge(d.name)),
        h('td', null, h('a', { href: fileUrl(d.path), target: '_blank', rel: 'noopener' }, d.name),
          d.audit_id && !audit ? h('div', { class: 'small muted' }, `Denetim · ${fmtDate(d.audit_date)}`) : null),
        h('td', { class: 'small' }, d.folder || '—'), h('td', { class: 'small num' }, size(d.size)),
        h('td', { class: 'small muted' }, d.uploaded_by_name || '', h('div', null, fmtDateTime(d.created_at))),
        h('td', { class: 'cf-doc-acts' }, h('a', { class: 'btn sm', href: `${fileUrl(d.path)}?dl=1`, title: 'İndir' }, '⬇'),
          h('button', { class: 'btn sm', type: 'button', title: 'Ad / klasör', onclick: () => editDoc(d, folders, () => docsPane(root, c, audit, reload)) }, '✎'),
          h('button', { class: 'btn sm ghost', type: 'button', title: 'Sil', onclick: async () => {
            if (!await confirmDialog('Dokümanı sil', `“${d.name}” silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
            try { await api.del(`/api/certs/docs/${d.id}`); docsPane(root, c, audit, reload); } catch (e) { toastError(e); }
          } }, '🗑'))))))
      : h('div', { class: 'empty' }, docs.length ? 'Bu klasörde doküman yok.' : 'Henüz doküman yok. Dosyaları sürükleyip bırakın ya da “Dosya yükle”ye dokunun.'));
  };
  const folderIn = h('input', { class: 'input', placeholder: 'Klasör (ops.) — ör. Prosedürler', list: `cf-fl-${c.id}`, style: { maxWidth: '220px' } });
  const dl = h('datalist', { id: `cf-fl-${c.id}` }, folders.map(f => h('option', { value: f })));
  const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
  async function sendFiles(files) {
    const arr = [...files];
    if (!arr.length) return;
    let ok = 0;
    for (const f of arr) {
      const bar = h('i');
      const row = h('div', { class: 'cf-q' }, extBadge(f.name), h('span', { class: 'cf-q-n' }, f.name), h('div', { class: 'cf-q-bar' }, bar));
      queue.append(row);
      try {
        const token = await uploadLarge(f, 'certs', p => { bar.style.width = `${p}%`; });
        await api.post(`/api/certs/${c.id}/docs`, { upload_id: token, folder: folderIn.value || null, audit_id: audit?.id || null });
        row.classList.add('done'); ok++;
      } catch (e) { row.classList.add('err'); row.title = e.message; }
    }
    toast(`${ok} / ${arr.length} doküman yüklendi`, ok === arr.length ? 'success' : 'err');
    setTimeout(() => { queue.querySelectorAll('.cf-q.done').forEach(x => x.remove()); }, 1500);
    docs = await api.get(`/api/certs/${c.id}/docs${audit ? `?audit_id=${audit.id}` : ''}`);
    drawFolders(); drawList();
  }
  fileIn.addEventListener('change', () => { sendFiles(fileIn.files); fileIn.value = ''; });
  const drop = h('div', { class: 'cf-drop' }, h('b', null, 'Dosyaları buraya sürükleyin'), h('span', { class: 'small muted' }, 'PDF, Word, Excel, resim, ZIP… — çoklu seçim ve büyük dosya desteklenir'),
    h('div', { class: 'ct-acts' }, h('button', { class: 'btn primary sm', type: 'button', onclick: () => fileIn.click() }, 'Dosya yükle'), folderIn, dl, fileIn));
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); sendFiles(e.dataTransfer.files); });
  const chips = h('div', { class: 'cf-chips' });
  const drawFolders = () => {
    const fs = [...new Set(docs.map(d => d.folder).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'tr'));
    const items = [['', `Tümü (${docs.length})`], ...fs.map(f => [f, `${f} (${docs.filter(d => d.folder === f).length})`])];
    if (!audit && docs.some(d => d.audit_id)) items.push(['__audit', `Denetim dokümanları (${docs.filter(d => d.audit_id).length})`]);
    clear(chips, items.map(([k, l]) => h('button', { class: `cf-chip ${folder === k ? 'on' : ''}`, type: 'button', onclick: () => { folder = k; drawFolders(); drawList(); } }, l)));
  };
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Doküman ara…', style: { maxWidth: '240px' } });
  search.addEventListener('input', () => { q = search.value.trim(); drawList(); });
  clear(root, drop, queue, h('div', { class: 'filters' }, chips, h('span', { class: 'spacer' }), search), list);
  drawFolders(); drawList();
}

function editDoc(d, folders, done) {
  const name = h('input', { class: 'input', value: d.name });
  const folder = h('input', { class: 'input', value: d.folder || '', list: 'cf-edit-fl' });
  modal({ title: 'Doküman', body: h('div', null, field('Ad', name), field('Klasör', folder), h('datalist', { id: 'cf-edit-fl' }, folders.map(f => h('option', { value: f })))),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => { await api.put(`/api/certs/docs/${d.id}`, { name: name.value, folder: folder.value }); done?.(); } }] });
}

// ---- Denetimler (sertifika)
function auditsPane(root, c, reload) {
  const add = h('button', { class: 'btn primary sm', type: 'button', onclick: () => auditForm(c, null, reload) }, '＋ Denetim ekle');
  const items = c.audits.map(a => {
    const planned = a.result === 'planlandi';
    const days = Math.round((new Date(a.date) - new Date(new Date().toISOString().slice(0, 10))) / 86400000);
    return h('div', { class: `card cf-audit ${planned ? 'planned' : ''}` },
      h('div', { class: 'cf-audit-date' }, h('b', null, fmtDate(a.date)), planned ? h('small', null, days >= 0 ? `${days} gün sonra` : `${-days} gün geçti`) : null),
      h('div', { class: 'cf-audit-main' },
        h('div', { class: 'cf-audit-h' }, h('span', { class: 'badge' }, META.audit_kinds[a.kind] || a.kind), badge(META.audit_results, RES_TONE, a.result),
          a.body ? h('span', { class: 'small muted' }, a.body) : null, a.auditor ? h('span', { class: 'small muted' }, `· ${a.auditor}`) : null),
        !planned ? h('div', { class: 'cf-nc' }, h('span', { class: `cf-ncb ${a.major ? 'red' : ''}` }, `Majör ${a.major}`), h('span', { class: `cf-ncb ${a.minor ? 'yellow' : ''}` }, `Minör ${a.minor}`),
          h('span', { class: 'cf-ncb' }, `Gözlem ${a.observations}`), a.capa_due ? h('span', { class: 'small muted' }, `Düzeltici faaliyet son tarihi ${fmtDate(a.capa_due)}`) : null) : null,
        a.notes ? h('p', { class: 'small', style: { margin: '4px 0 0', whiteSpace: 'pre-wrap' } }, a.notes) : null,
        a.next_date ? h('div', { class: 'small muted' }, `Sonraki denetim: ${fmtDate(a.next_date)}`) : null),
      h('div', { class: 'cf-audit-acts' }, h('button', { class: 'btn sm', type: 'button', onclick: () => auditDocs(c, a, reload) }, `📎 ${a.doc_count}`),
        h('button', { class: 'btn sm', type: 'button', onclick: () => auditForm(c, a, reload) }, 'Düzenle')));
  });
  clear(root, h('div', { class: 'filters' }, h('span', { class: 'small muted' }, 'İlk belgelendirme, gözetim, yeniden belgelendirme ve iç denetimler'), h('span', { class: 'spacer' }), add),
    items.length ? h('div', { class: 'cf-audits' }, items) : h('div', { class: 'card empty' }, 'Henüz denetim kaydı yok.'));
}

function auditForm(c, a, done) {
  a = a || { kind: 'gozetim', result: 'planlandi', date: new Date().toISOString().slice(0, 10), major: 0, minor: 0, observations: 0 };
  const date = h('input', { class: 'input', type: 'date', value: a.date || '' });
  const kind = h('select', { class: 'input' }, Object.entries(META.audit_kinds).map(([k, l]) => h('option', { value: k, selected: k === a.kind }, l)));
  const result = h('select', { class: 'input' }, Object.entries(META.audit_results).map(([k, l]) => h('option', { value: k, selected: k === a.result }, l)));
  const body = h('input', { class: 'input', value: a.body || c.issuer || '', placeholder: 'Denetleyen kuruluş' });
  const auditor = h('input', { class: 'input', value: a.auditor || '', placeholder: 'Denetçi(ler)' });
  const num = v => h('input', { class: 'input', type: 'number', min: 0, value: v || 0 });
  const major = num(a.major), minor = num(a.minor), obs = num(a.observations);
  const capa = h('input', { class: 'input', type: 'date', value: a.capa_due || '' });
  const next = h('input', { class: 'input', type: 'date', value: a.next_date || '' });
  const notes = h('textarea', { class: 'input', rows: 3, placeholder: 'Bulgular, uygunsuzluklar, alınacak aksiyonlar…' }); notes.value = a.notes || '';
  const actions = [{ label: 'Vazgeç' }];
  if (a.id) actions.push({ label: 'Sil', class: 'danger', onClick: async () => { if (!await confirmDialog('Denetimi sil', 'Denetim ve dokümanları silinsin mi?', { okLabel: 'Sil', danger: true })) return true; await api.del(`/api/certs/audits/${a.id}`); done?.(); } });
  actions.push({ label: 'Kaydet', class: 'primary', onClick: async () => {
    const b = { date: date.value, kind: kind.value, result: result.value, body: body.value, auditor: auditor.value, major: Number(major.value) || 0, minor: Number(minor.value) || 0,
      observations: Number(obs.value) || 0, capa_due: capa.value || null, next_date: next.value || null, notes: notes.value };
    if (a.id) await api.put(`/api/certs/audits/${a.id}`, b); else await api.post(`/api/certs/${c.id}/audits`, b);
    toast('Kaydedildi', 'success'); done?.();
  } });
  modal({ title: a.id ? 'Denetim' : 'Yeni denetim', wide: true,
    body: h('div', null, h('div', { class: 'cf-3' }, field('Tarih', date), field('Tür', kind), field('Sonuç', result)),
      h('div', { class: 'cf-2' }, field('Kuruluş', body), field('Denetçi', auditor)),
      h('div', { class: 'cf-3' }, field('Majör uygunsuzluk', major), field('Minör uygunsuzluk', minor), field('Gözlem', obs)),
      h('div', { class: 'cf-2' }, field('Düzeltici faaliyet son tarihi', capa), field('Sonraki denetim (planlanır)', next)), field('Notlar / bulgular', notes)),
    actions });
}

function auditDocs(c, a, done) {
  const box = h('div');
  modal({ title: `Denetim dokümanları · ${fmtDate(a.date)}`, wide: true, body: box, actions: [{ label: 'Kapat', class: 'primary', onClick: () => { done?.(); } }] });
  docsPane(box, c, a, done);
}

// ---------------- Tüm denetimler ----------------
async function auditsView(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get('/api/certs/audits/all'); if (!META) META = await api.get('/api/certs'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  let mode = 'upcoming';
  const out = h('div');
  const draw = () => {
    const rows = mode === 'upcoming' ? d.rows.filter(r => r.result === 'planlandi').sort((a, b) => a.date.localeCompare(b.date)) : d.rows.filter(r => r.result !== 'planlandi');
    clear(out, rows.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Tarih', 'Sertifika', 'Tür', 'Kuruluş', 'Sonuç', 'Uygunsuzluk', 'Doküman'].map(x => h('th', null, x)))),
      h('tbody', null, rows.map(r => h('tr', { class: 'clickable', onclick: () => { location.hash = `#/certs/${r.cert_id}`; } },
        h('td', null, fmtDate(r.date), mode === 'upcoming' && r.days_left != null ? h('div', { class: `small ${r.days_left <= 14 ? 'fin-late' : 'muted'}` }, r.days_left >= 0 ? `${r.days_left} gün sonra` : `${-r.days_left} gün geçti`) : null),
        h('td', null, h('b', null, r.cert_name), r.standard ? h('div', { class: 'small muted' }, r.standard) : null),
        h('td', null, d.audit_kinds[r.kind] || r.kind), h('td', { class: 'small' }, [r.body, r.auditor].filter(Boolean).join(' · ') || '—'),
        h('td', null, badge(d.audit_results, RES_TONE, r.result)),
        h('td', { class: 'small' }, r.result === 'planlandi' ? '—' : `M ${r.major} · m ${r.minor} · G ${r.observations}`),
        h('td', { class: 'small num' }, r.doc_count)))))) : h('div', { class: 'card empty' }, mode === 'upcoming' ? 'Planlı denetim yok.' : 'Geçmiş denetim yok.'));
  };
  clear(view, h('div', { class: 'filters' }, segmented([['upcoming', 'Planlı'], ['past', 'Gerçekleşen']], mode, v => { mode = v; draw(); })), out);
  draw();
}
