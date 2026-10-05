// Görev Formu (Kişisel): personel görevlendirme + çıkış izni. Onaylanınca QR'lı çıkış izni oluşur (güvenlikte okutulur).
// "Formlarım": benim oluşturduğum görev formları. "Onay Bekleyenler": benim onayıma düşen talepler.
import { api } from '../api.js';
import {
  clear, confirmDialog, dateTimeInput, field, fmtDateTime, h, modal, moduleTabs, moduleToolbar, pageHead, t, toast, toastError,
} from '../ui.js';
import { qrSvg, qrSvgEl } from '../qr.js';

const STATUS = { BEKLIYOR: ['Onay bekliyor', 'gray'], ONAYLANDI: ['Onaylandı', 'green'], REDDEDILDI: ['Reddedildi', 'red'], IPTAL: ['İptal', 'muted'] };
const badge = s => h('span', { class: `badge ${(STATUS[s] || [])[1] || 'gray'}` }, (STATUS[s] || [s])[0]);
const TABS = [['mine', 'Formlarım'], ['pending', 'Onay Bekleyenler']];

let COMPANY = '';

export async function render(view, params, ctx) {
  COMPANY = ctx?.meta?.company || '';
  const tab = TABS.some(x => x[0] === params[0]) ? params[0] : 'mine';
  const nav = moduleTabs(TABS, tab, v => { location.hash = v === 'mine' ? '#/my-duties' : `#/my-duties/${v}`; });
  const addBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => newDutyForm(ctx, () => reload()) }, '＋ Yeni Görev Formu');
  const body = h('div');
  clear(view, pageHead('Görev Formu', { back: '#/', sub: 'Personel görevlendirme ve çıkış izni' }),
    nav, moduleToolbar(tab === 'mine' ? addBtn : null), body);

  const reload = () => (tab === 'pending' ? loadPending(body) : loadMine(body, ctx)).catch(err => clear(body, h('div', { class: 'card empty' }, err.message)));
  return reload();
}

async function loadMine(body, ctx) {
  const data = await api.get('/api/me/duties');
  const items = data.items || [];
  clear(body, items.length
    ? h('div', { class: 'duty-grid' }, items.map(d => dutyCard(d, { mine: true }, () => loadMine(body, ctx))))
    : h('div', { class: 'card empty' }, 'Henüz görev formunuz yok. "Yeni Görev Formu" ile oluşturun.'));
}

async function loadPending(body) {
  const data = await api.get('/api/duties/pending');
  const items = data.items || [];
  clear(body, items.length
    ? h('div', { class: 'duty-grid' }, items.map(d => dutyCard(d, { approve: true }, () => loadPending(body))))
    : h('div', { class: 'card empty' }, 'Onayınıza düşen görev formu yok.'));
}

function dutyCard(d, { mine = false, approve = false } = {}, reload) {
  const whenRow = (lbl, v) => (v ? [h('dt', null, lbl), h('dd', null, fmtDateTime(v))] : null);
  return h('div', { class: `card duty-card st-${String(d.status || '').toLowerCase()}` },
    h('div', { class: 'duty-card-head' }, h('b', null, d.employee_name || '—'), badge(d.status)),
    d.employee_title ? h('div', { class: 'small muted' }, d.employee_title) : null,
    h('dl', { class: 'duty-kv' },
      h('dt', null, 'Gideceği yer'), h('dd', null, d.destination || '—'),
      whenRow('Çıkış', d.depart_at),
      whenRow('Dönüş', d.return_at),
      d.vehicle_plate ? [h('dt', null, 'Araç'), h('dd', null, d.vehicle_plate)] : null,
      d.purpose ? [h('dt', null, 'Açıklama'), h('dd', null, d.purpose)] : null,
      d.approver_name ? [h('dt', null, 'Onaylayacak'), h('dd', null, d.approver_name)] : null,
      d.decision_note ? [h('dt', null, 'Not'), h('dd', null, d.decision_note)] : null),
    h('div', { class: 'duty-actions' },
      d.status === 'ONAYLANDI' && d.pass_token ? h('button', { class: 'btn sm primary', type: 'button', onclick: () => showPassModal(d) }, 'QR Göster') : null,
      mine && d.status === 'BEKLIYOR' ? h('button', { class: 'btn sm', type: 'button', onclick: () => cancelDuty(d, reload) }, 'Vazgeç') : null,
      approve && d.status === 'BEKLIYOR' ? [
        h('button', { class: 'btn sm primary', type: 'button', onclick: () => decideModal(d, 'approve', reload) }, 'Onayla'),
        h('button', { class: 'btn sm', type: 'button', onclick: () => decideModal(d, 'reject', reload) }, 'Reddet'),
      ] : null));
}

// ---------- QR / çıkış izni gösterimi ----------
function showPassModal(d) {
  const dates = h('dl', { class: 'duty-kv' },
    h('dt', null, 'Personel'), h('dd', null, d.employee_name || '—'),
    d.employee_title ? [h('dt', null, 'Görev'), h('dd', null, d.employee_title)] : null,
    h('dt', null, 'Gideceği yer'), h('dd', null, d.destination || '—'),
    h('dt', null, 'Çıkış'), h('dd', null, fmtDateTime(d.depart_at)),
    d.return_at ? [h('dt', null, 'Dönüş'), h('dd', null, fmtDateTime(d.return_at))] : null);
  modal({
    title: 'Çıkış İzni · QR',
    body: h('div', null,
      h('div', { class: 'qr-box' }, qrSvgEl(d.pass_token, { cell: 5, margin: 2 })),
      h('p', { class: 'small muted', style: { textAlign: 'center' } }, 'Fabrika çıkışında güvenliğe okutun.'),
      dates),
    actions: [
      { label: 'Yazdır', onClick: () => { printDutyForm(d); return true; } },
      { label: 'Kapat', class: 'primary' },
    ],
  });
}

// Onaylı görev formu yazdırma (QR başlıkta). QR, yazdırılan bağımsız belgeye string olarak gömülür.
async function printDutyForm(d) {
  let qr = '';
  try { if (d.pass_token) qr = await qrSvg(d.pass_token, { cell: 4, margin: 1 }); } catch { /* QR yoksa formu yine de yazdır */ }
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const row = (k, v) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`;
  const w = window.open('', '_blank');
  if (!w) { toast('Açılır pencere engellendi; tarayıcıda izin verin', 'err'); return; }
  w.document.write(`<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>GÖREV FORMU · ${esc(d.employee_name)}</title>
<style>body{font-family:system-ui,sans-serif;margin:40px;color:#111}
.hd{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:24px}
.hd-t h1{font-size:20px;margin:0 0 4px}.hd-t .co{color:#555}
.qr{width:120px;height:120px;flex:0 0 120px}.qr svg{width:100%;height:100%}
table{width:100%;border-collapse:collapse;margin-bottom:28px}
th,td{border:1px solid #999;padding:9px 12px;text-align:left;font-size:14px}th{width:34%;background:#f3f3f3}
.sig{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin-top:40px}.sig div{border-top:1px solid #333;padding-top:6px;text-align:center;font-size:13px;min-height:70px}
.note{font-size:12px;color:#555}@media print{body{margin:18mm}}</style></head><body>
<div class="hd"><div class="hd-t"><h1>GÖREV FORMU</h1><div class="co">${esc(COMPANY || '')}</div></div>${qr ? `<div class="qr">${qr}</div>` : ''}</div>
<table>${row('Adı Soyadı', d.employee_name)}${row('Görevi', d.employee_title || '')}
${row('Gideceği yer', d.destination)}${row('Çıkış', fmtDateTime(d.depart_at))}${d.return_at ? row('Tahmini dönüş', fmtDateTime(d.return_at)) : ''}
${d.vehicle_plate ? row('Araç plakası', d.vehicle_plate) : ''}${row('Görevlendirme açıklaması', d.purpose || '')}
${d.approver_name ? row('Onaylayan', d.approver_name) : ''}${d.decision_note ? row('Not', d.decision_note) : ''}</table>
<p class="note">Yukarıdaki görevlendirme kapsamında fabrikadan çıkış yapacağımı beyan ederim.</p>
<div class="sig"><div>Personel<br>İmza</div><div>Onaylayan<br>İmza</div><div>Güvenlik<br>İmza</div></div>
<script>window.onload=()=>window.print()<\/script></body></html>`);
  w.document.close();
}

// ---------- Yeni görev formu ----------
async function newDutyForm(ctx, reload) {
  const [employees, users] = await Promise.all([loadEmployees(ctx), loadUsers()]);
  const emp = searchSelect(employees, { placeholder: 'Göreve gidecek personeli ara…' });
  const dest = h('input', { class: 'input', placeholder: 'Gideceği yer (ör. İstanbul · müşteri ziyareti)' });
  const depart = dateTimeInput();
  const ret = dateTimeInput();
  const purpose = h('textarea', { class: 'input', rows: 3, placeholder: 'Görevlendirme açıklaması' });
  const plate = h('input', { class: 'input', placeholder: 'Araç plakası (isteğe bağlı)', autocapitalize: 'characters' });
  const approver = h('select', { class: 'input' }, h('option', { value: '' }, 'Seçilmedi'),
    users.map(u => h('option', { value: u.id }, u.full_name || u.username || `#${u.id}`)));

  modal({
    title: 'Yeni Görev Formu', wide: true,
    body: h('div', null,
      field('Göreve gidecek personel *', emp),
      field('Gideceği yer *', dest),
      h('div', { class: 'row' }, field('Çıkış zamanı *', depart), field('Tahmini dönüş', ret)),
      field('Görevlendirme açıklaması', purpose),
      field('Araç plakası', plate),
      field('Onaylayacak yönetici', approver, 'Boş bırakılırsa yetkili yöneticiye düşer.')),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      if (!emp.value) { toast('Göreve gidecek personeli seçin', 'err'); return true; }
      if (!dest.value.trim()) { toast('Gideceği yeri girin', 'err'); return true; }
      await api.post('/api/me/duties', {
        employee_id: emp.value,
        destination: dest.value.trim(),
        purpose: purpose.value.trim(),
        depart_at: depart.getValue(),
        return_at: ret.getValue() || null,
        vehicle_plate: plate.value.trim() || null,
        approver_id: approver.value ? Number(approver.value) : null,
      });
      toast('Görev formu oluşturuldu; onaya gönderildi', 'success');
      reload();
    } }],
  });
}

function decideModal(d, action, reload) {
  const note = h('textarea', { class: 'input', rows: 3, placeholder: action === 'reject' ? 'Reddetme sebebi' : 'Not (isteğe bağlı)' });
  modal({
    title: t('{name} · Görev Formu', { name: d.employee_name || '' }),
    body: h('div', null,
      h('p', { style: { marginTop: 0 } }, `${d.destination || ''} · ${fmtDateTime(d.depart_at)}`),
      field(action === 'reject' ? 'Reddetme sebebi *' : 'Not', note)),
    actions: [{ label: 'Vazgeç' }, {
      label: action === 'reject' ? 'Reddet' : 'Onayla', class: action === 'reject' ? 'danger' : 'primary',
      onClick: async () => {
        await api.post(`/api/duties/${d.id}/${action}`, { note: note.value.trim() });
        toast(action === 'reject' ? 'Görev formu reddedildi' : 'Görev formu onaylandı', 'success');
        reload();
      },
    }],
  });
}

async function cancelDuty(d, reload) {
  if (!await confirmDialog('Görev formunu geri çek', 'Bu görev formu talebinden vazgeçilsin mi?', { okLabel: 'Vazgeç', danger: true })) return;
  try { await api.del(`/api/me/duties/${d.id}`); toast('Görev formu geri çekildi'); reload(); } catch (err) { toastError(err); }
}

// ---------- Veri kaynakları ----------
// Aktif personel (göreve gidecek): herkese açık /api/me/duties/staff — her zaman gerçek employee_id döner.
async function loadEmployees(ctx) {
  try {
    const { items } = await api.get('/api/me/duties/staff');
    return (items || []).map(e => ({ id: e.id, label: e.name || `#${e.id}`, sub: [e.title, e.department].filter(Boolean).join(' · ') }));
  } catch { return []; }
}
async function loadUsers() {
  try { return await api.get('/api/voice/users'); } catch { return []; }
}

// Aranabilir tekli seçim: metin girişi + açılır liste. .value → seçilen id (yoksa null).
function searchSelect(items, { placeholder = 'Ara…' } = {}) {
  let chosen = null;
  const input = h('input', { class: 'input', type: 'text', placeholder, autocomplete: 'off' });
  const panel = h('div', { class: 'fsel-panel', hidden: true });
  const wrap = h('div', { class: 'fsel' }, input, panel);
  const draw = () => {
    const term = input.value.trim().toLocaleLowerCase('tr');
    const rows = items.filter(it => !term || String(it.label).toLocaleLowerCase('tr').includes(term)).slice(0, 50);
    clear(panel, rows.length ? rows.map(it => h('div', { class: 'fsel-row', onmousedown: e => {
      e.preventDefault();
      chosen = it.id; input.value = it.label; panel.hidden = true;
    } }, h('b', null, it.label), it.sub ? h('span', { class: 'small muted' }, it.sub) : null))
      : h('div', { class: 'fsel-row muted' }, 'Sonuç yok'));
  };
  input.addEventListener('focus', () => { panel.hidden = false; draw(); });
  input.addEventListener('input', () => { chosen = null; panel.hidden = false; draw(); });
  input.addEventListener('blur', () => { setTimeout(() => { panel.hidden = true; }, 150); });
  Object.defineProperty(wrap, 'value', { get: () => chosen });
  return wrap;
}
