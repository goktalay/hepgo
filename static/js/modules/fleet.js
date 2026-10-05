// Araç Yönetimi: şirket araçları (satın alınan / kiralanan), personele zimmet + zimmet formu + elektronik teslim onayı,
// belgeler (ruhsat, kira sözleşmesi, poliçeler…) ve giderler. Giderler elle girilir ya da muhasebe (Mikro senkronu,
// Program Ayarları › Entegrasyonlar) / finans hareketleri araçlara etiketlenir; böylece araç başına toplam harcama görülür.
import { api, fileUrl, upload, uploadLarge } from '../api.js';
import { clear, confirmDialog, field, fmtDate, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, segmented, statStrip, t, toast, toastError } from '../ui.js';

const SUBS = [['list', 'Araçlar'], ['moves', 'Gider Etiketleme'], ['report', 'Rapor'], ['settings', 'Zimmet Formu']];
const CAT_TONE = { yakit: '#f97316', bakim: '#2563eb', lastik: '#475569', sigorta: '#7c3aed', vergi: '#dc2626', otoyol: '#0891b2', otopark: '#65a30d',
  kira: '#db2777', ceza: '#b91c1c', yikama: '#0ea5e9', diger: '#94a3b8' };
const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 2 }).format(n || 0);
const money0 = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 0 }).format(n || 0);
const kmTxt = n => (n == null ? '—' : `${Math.round(n).toLocaleString('tr-TR')} km`);
const sum = (arr, k) => arr.reduce((s, x) => s + (Number(k ? x[k] : x) || 0), 0);
const today = () => new Date().toISOString().slice(0, 10);
const loading = el => clear(el, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
const vname = v => [v.brand, v.model, v.year].filter(Boolean).join(' ');
let META = null;
let OPTS = null;

const CAR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 16.5v-4.3l2-5.1c.3-.8 1.1-1.3 1.9-1.3h10.2c.8 0 1.6.5 1.9 1.3l2 5.1v4.3"/><path d="M3 12.2h18"/><path d="M2.5 16.5h19"/><circle cx="7" cy="16.8" r="1.8"/><circle cx="17" cy="16.8" r="1.8"/><path d="M5.6 14.4h1.6M16.8 14.4h1.6"/></svg>';
const carIcon = () => { const s = h('span', { class: 'fl-car' }); s.innerHTML = CAR; return s; };
export const plate = (p, big) => h('span', { class: `fl-plate ${big ? 'big' : ''}` }, h('i', null, 'TR'), h('b', null, p));
const catBadge = k => h('span', { class: 'fl-catb', style: `--c:${CAT_TONE[k] || CAT_TONE.diger}` }, META?.categories?.[k] || k);
const dueText = x => (x.km
  ? `${t(x.label)}: ${x.left_km > 0 ? t('{n} km kaldı', { n: x.left_km.toLocaleString('tr-TR') }) : t('km doldu')}`
  : `${t(x.label)}: ${x.days < 0 ? t('{n} gün geçti', { n: -x.days }) : x.days === 0 ? t('bugün') : t('{n} gün kaldı', { n: x.days })}`);
const dueChip = x => h('span', { class: `fl-due ${(x.km ? x.left_km <= 0 : x.days < 0) ? 'red' : 'yellow'}` }, dueText(x));

export async function render(view, params, ctx) {
  const p0 = (params[0] || '').split('?')[0];
  if (/^\d+$/.test(p0)) return detail(view, Number(p0), ctx);
  const sub = SUBS.some(([k]) => k === p0) ? p0 : 'list';
  const nav = segmented(SUBS, sub, v => { location.hash = v === 'list' ? '#/fleet' : `#/fleet/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Araç Yönetimi', { back: '#/', sub: 'Şirket araçları, zimmet, belgeler ve giderler', tabs: nav }), body);
  if (sub === 'moves') return movesView(body);
  if (sub === 'report') return reportView(body);
  if (sub === 'settings') return settingsView(body);
  return listView(body);
}

async function options() {
  if (!OPTS) OPTS = await api.get('/api/fleet/options');
  return OPTS;
}

// ---------------- Araçlar ----------------
async function listView(root) {
  loading(root);
  let d;
  try { d = await api.get('/api/fleet'); } catch (e) { return clear(root, h('div', { class: 'card empty' }, e.message)); }
  META = d.meta;
  const rows = d.rows;
  const act = rows.filter(r => r.active);
  const dueN = act.reduce((n, r) => n + r.dues.length, 0);
  const strip = statStrip();
  strip.set([
    { icon: 'fleet', label: 'Aktif araç', value: act.length, sub: t('{a} mal · {b} kiralık', { a: act.filter(r => r.ownership !== 'leased').length, b: act.filter(r => r.ownership === 'leased').length }) },
    { icon: 'users', label: 'Zimmetli', value: act.filter(r => r.assignee).length, sub: t('{n} boşta', { n: act.filter(r => !r.assignee).length }) },
    { icon: 'finance', label: 'Toplam gider', value: money0(sum(rows, 'spend_total')) },
    { icon: 'calendar', label: 'Yaklaşan işlem', value: dueN, tone: dueN ? 'alert' : '' }]);
  const banners = [];
  if (d.open_moves) {
    banners.push(h('a', { class: 'fl-banner', href: '#/fleet/moves' }, h('span', { class: 'fl-banner-i' }, '₺'),
      h('div', null, h('b', null, t('{n} araç gideri etiketlenmeyi bekliyor', { n: d.open_moves })),
        h('div', { class: 'small muted' }, 'Muhasebedeki yakıt, bakım, kira, HGS… hareketlerini araçlara etiketleyin')), h('span', { class: 'fl-banner-go' }, '→')));
  }
  for (const a of d.unlinked_assets) {
    banners.push(h('div', { class: 'fl-banner' }, h('span', { class: 'fl-banner-i' }, '254'),
      h('div', null, h('b', null, t('Muhasebede kayıtlı taşıt: {n}', { n: a.name })), h('div', { class: 'small muted' }, `${a.code} · ${money0(a.cost)}`)),
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => linkAsset(a, root) }, a.plate_vehicle_id ? 'Araca bağla' : 'Araç olarak ekle')));
  }
  let filter = 'active', q = '';
  const grid = h('div', { class: 'fl-grid' });
  const pass = r => ({ active: r.active, owned: r.active && r.ownership !== 'leased', leased: r.active && r.ownership === 'leased', free: r.active && !r.assignee,
    due: r.active && r.dues.length, inactive: !r.active, all: true }[filter]);
  const card = r => h('a', { class: `fl-card ${r.active ? '' : 'off'}`, href: `#/fleet/${r.id}` },
    h('div', { class: 'fl-photo' }, r.photo ? h('img', { src: fileUrl(r.photo, 512), alt: '', loading: 'lazy' }) : h('div', { class: 'fl-ph' }, carIcon()),
      h('span', { class: `fl-own ${r.ownership}` }, r.ownership === 'leased' ? 'Kiralık' : 'Şirket malı'),
      r.active ? null : h('span', { class: 'fl-own off' }, META.exit_reasons[r.exit_reason] || 'Pasif')),
    h('div', { class: 'fl-body' },
      h('div', { class: 'fl-row' }, plate(r.plate), h('span', { class: 'fl-km' }, kmTxt(r.km_now))),
      h('div', { class: 'fl-name' }, vname(r) || r.description || '—', r.ownership === 'leased' && r.lessor_name ? h('small', { class: 'muted' }, ` · ${r.lessor_name}`) : null),
      h('div', { class: 'fl-who' }, r.assignee
        ? [h('span', { class: 'fl-ini' }, initials(r.assignee.full_name)), h('span', null, r.assignee.full_name),
          r.assignee.accepted_at ? null : h('span', { class: 'badge yellow' }, 'Onay bekliyor')]
        : h('span', { class: 'muted' }, r.active ? 'Boşta' : '—')),
      r.dues.length ? h('div', { class: 'fl-dues' }, r.dues.map(dueChip)) : null,
      h('div', { class: 'fl-spend' }, h('span', { class: 'muted small' }, t('{y} gideri', { y: d.year })), h('b', null, money0(r.spend_year)))));
  const draw = () => {
    const shown = rows.filter(r => pass(r) && matches(q, r.plate, r.brand, r.model, r.description, r.assignee?.full_name, r.lessor_name));
    clear(grid, shown.length ? shown.map(card) : h('div', { class: 'card empty', style: { gridColumn: '1/-1' } },
      rows.length ? 'Bu filtrede araç yok.' : 'Henüz araç yok. “＋ Yeni araç” ile ekleyin: satın alınan ya da kiralanan araçlar, zimmet ve giderleriyle burada izlenir.'));
  };
  const filt = segmented([['active', 'Aktif'], ['owned', 'Şirket malı'], ['leased', 'Kiralık'], ['free', 'Boşta'], ['due', 'İşlem bekleyen'], ['inactive', 'Pasif']],
    filter, v => { filter = v; draw(); });
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Plaka, marka, personel ara…', style: { maxWidth: '240px' } });
  search.addEventListener('input', () => { q = search.value.trim(); draw(); });
  clear(root, moduleToolbar(h('button', { class: 'btn primary', type: 'button', onclick: () => vehicleForm(null, id => { location.hash = `#/fleet/${id}`; }) }, '＋ Yeni araç')),
    strip, banners.length ? h('div', { class: 'fl-banners' }, banners) : null, h('div', { class: 'filters' }, filt, search), grid);
  draw();
}

const initials = n => String(n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toLocaleUpperCase('tr');

async function linkAsset(a, root) {
  const pre = { ownership: 'owned', asset_account: a.code, purchase_price: a.cost, purchase_date: a.date };
  if (!a.plate_vehicle_id) return vehicleForm({ plate: a.plate || '', brand: a.brand, model: a.model, active: 1, ...pre }, id => { location.hash = `#/fleet/${id}`; }, true);
  const v = await api.get(`/api/fleet/${a.plate_vehicle_id}`);
  vehicleForm({ ...v, ...pre, brand: v.brand || a.brand, model: v.model || a.model, purchase_price: v.purchase_price || a.cost, purchase_date: v.purchase_date || a.date },
    () => listView(root));
}

// ---------------- Araç formu ----------------
async function vehicleForm(v, done, prefilled) {
  let o;
  try { o = await options(); } catch (e) { return toastError(e); }
  META = META || o.meta;
  const isNew = !v?.id;
  v = v || { ownership: 'owned', active: 1 };
  const val = k => (v[k] ?? '');
  const inp = (k, attrs = {}) => h('input', { class: 'input', value: val(k), ...attrs });
  const sel = (k, map, empty = '—') => h('select', { class: 'input' }, h('option', { value: '' }, empty),
    Object.entries(map).map(([key, l]) => h('option', { value: key, selected: key === v[k] }, l)));
  const compSel = (k, onlySup) => h('select', { class: 'input' }, h('option', { value: '' }, '— Firma seçin —'),
    o.companies.filter(c => !onlySup || c.is_supplier || c.id === v[k]).map(c => h('option', { value: c.id, selected: c.id === v[k] }, c.name)));
  const f = {
    plate: inp('plate', { placeholder: '34 ABC 123', style: { textTransform: 'uppercase', fontWeight: 700 } }),
    brand: inp('brand', { placeholder: 'ör. Ford' }), model: inp('model', { placeholder: 'ör. Transit 350L Van' }),
    year: inp('year', { type: 'number', min: 1950, max: 2100, placeholder: '2025' }), body_type: sel('body_type', META.body_types), fuel_type: sel('fuel_type', META.fuel_types),
    color: inp('color'), vin: inp('vin', { placeholder: 'Şasi no' }), engine_no: inp('engine_no'), description: inp('description', { placeholder: 'Kısa açıklama (Saha listesinde de görünür)' }),
    purchase_date: inp('purchase_date', { type: 'date' }), purchase_price: inp('purchase_price', { type: 'number', step: '0.01', min: 0 }), seller_id: compSel('seller_id'),
    purchase_doc: inp('purchase_doc', { placeholder: 'Fatura / noter satış no' }),
    asset_account: h('select', { class: 'input' }, h('option', { value: '' }, '— Bağlı değil —'),
      o.assets.map(a => h('option', { value: a.code, selected: a.code === v.asset_account }, `${a.code} · ${a.name} (${money0(a.cost)})`))),
    lessor_id: compSel('lessor_id'), lease_no: inp('lease_no'), lease_start: inp('lease_start', { type: 'date' }), lease_end: inp('lease_end', { type: 'date' }),
    lease_monthly: inp('lease_monthly', { type: 'number', step: '0.01', min: 0 }),
    lease_currency: h('select', { class: 'input' }, ['TRY', 'USD', 'EUR'].map(c => h('option', { value: c, selected: c === (v.lease_currency || 'TRY') }, c))),
    lease_km_limit: inp('lease_km_limit', { type: 'number', min: 0, placeholder: 'ör. 30000 (yıllık)' }),
    start_km: inp('start_km', { type: 'number', min: 0 }), inspection_date: inp('inspection_date', { type: 'date' }), traffic_ins_date: inp('traffic_ins_date', { type: 'date' }),
    kasko_date: inp('kasko_date', { type: 'date' }), next_service_date: inp('next_service_date', { type: 'date' }), next_service_km: inp('next_service_km', { type: 'number', min: 0 }),
    match_keys: inp('match_keys', { placeholder: 'ör. HILUX, FPAD' }), exit_date: inp('exit_date', { type: 'date' }), exit_reason: sel('exit_reason', META.exit_reasons),
    note: h('textarea', { class: 'input', rows: 2 }),
  };
  f.note.value = val('note');
  f.asset_account.addEventListener('change', () => {
    const a = o.assets.find(x => x.code === f.asset_account.value);
    if (!a) return;
    if (!f.purchase_price.value) f.purchase_price.value = a.cost;
    if (!f.purchase_date.value && a.date) f.purchase_date.value = a.date;
  });
  const incl = new Set((v.lease_includes || '').split(',').filter(Boolean));
  const inclBox = h('div', { class: 'fl-checks' }, Object.entries(META.lease_includes).map(([k, l]) => {
    const c = h('input', { type: 'checkbox', checked: incl.has(k) });
    c.addEventListener('change', () => { if (c.checked) incl.add(k); else incl.delete(k); });
    return h('label', null, c, ' ', l);
  }));
  let own = v.ownership || 'owned';
  const ownedBox = h('div', null, h('div', { class: 'cf-3' }, field('Satın alma tarihi', f.purchase_date), field('Bedel (₺)', f.purchase_price), field('Fatura / belge no', f.purchase_doc)),
    h('div', { class: 'cf-2' }, field('Satıcı firma', f.seller_id), field('Muhasebe taşıt hesabı (254)', f.asset_account, 'Mikro senkronundaki sabit kıymet hesabı; bedel ve tarih buradan önerilir')));
  const leasedBox = h('div', null, h('div', { class: 'cf-2' }, field('Kiralayan firma', f.lessor_id, 'Kira faturaları bu firmadan geldiğinde araç önerilir'), field('Sözleşme no', f.lease_no)),
    h('div', { class: 'cf-3' }, field('Kira başlangıcı', f.lease_start), field('Kira bitişi', f.lease_end), field('Km limiti', f.lease_km_limit)),
    h('div', { class: 'cf-2' }, field('Aylık kira', h('div', { class: 'fl-money' }, f.lease_monthly, f.lease_currency)), field('Kiraya dahil', inclBox)),
    h('p', { class: 'small muted', style: { margin: '2px 0 0' } }, 'Kira sözleşmesini kaydettikten sonra aracın “Belgeler” sekmesinden yükleyin.'));
  const ownSeg = segmented(Object.entries(META.ownership).map(([k, l]) => [k, l]), own, k => { own = k; ownedBox.hidden = k !== 'owned'; leasedBox.hidden = k !== 'leased'; });
  ownedBox.hidden = own !== 'owned'; leasedBox.hidden = own !== 'leased';
  const active = h('input', { type: 'checkbox', checked: v.active !== 0 && v.active !== false });
  const exitBox = h('div', { class: 'cf-2' }, field('Çıkış tarihi', f.exit_date), field('Çıkış nedeni', f.exit_reason));
  const syncExit = () => { exitBox.hidden = active.checked; };
  active.addEventListener('change', syncExit); syncExit();
  const photo = h('input', { type: 'file', accept: 'image/*' });
  const sect = (title, ...kids) => h('fieldset', { class: 'fl-fs' }, h('legend', null, title), ...kids);
  modal({ title: isNew ? 'Yeni araç' : t('{p} — araç bilgileri', { p: v.plate }), wide: true,
    body: h('div', { class: 'fl-form' },
      sect('Araç', h('div', { class: 'cf-3' }, field('Plaka', f.plate), field('Marka', f.brand), field('Model', f.model)),
        h('div', { class: 'cf-3' }, field('Model yılı', f.year), field('Kasa tipi', f.body_type), field('Yakıt', f.fuel_type)),
        h('div', { class: 'cf-3' }, field('Renk', f.color), field('Şasi no', f.vin), field('Motor no', f.engine_no)),
        h('div', { class: 'cf-2' }, field('Açıklama', f.description), field('Fotoğraf', photo))),
      sect('Edinim', ownSeg, ownedBox, leasedBox),
      sect('Hatırlatmalar', h('div', { class: 'cf-3' }, field('Başlangıç km', f.start_km), field('Muayene bitişi', f.inspection_date), field('Trafik sigortası bitişi', f.traffic_ins_date)),
        h('div', { class: 'cf-3' }, field('Kasko bitişi', f.kasko_date), field('Sonraki bakım tarihi', f.next_service_date), field('Sonraki bakım km', f.next_service_km))),
      sect('Gider eşleştirme', field('Anahtar kelimeler', f.match_keys, 'Plaka zaten aranır. Muhasebe açıklamasında araç başka adla geçiyorsa (ör. kiralama şirketinin araç kodu) virgülle yazın.')),
      sect('Durum', h('label', { class: 'fl-active' }, active, ' ', 'Araç aktif (filoda)'), exitBox, field('Not', f.note))),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const num = el => (el.value === '' ? null : Number(el.value));
      const b = { plate: f.plate.value, brand: f.brand.value, model: f.model.value, year: num(f.year), body_type: f.body_type.value || null, fuel_type: f.fuel_type.value || null,
        color: f.color.value, vin: f.vin.value, engine_no: f.engine_no.value, description: f.description.value, ownership: own,
        purchase_date: f.purchase_date.value || null, purchase_price: num(f.purchase_price), seller_id: num(f.seller_id), purchase_doc: f.purchase_doc.value,
        asset_account: f.asset_account.value || null, lessor_id: num(f.lessor_id), lease_no: f.lease_no.value, lease_start: f.lease_start.value || null,
        lease_end: f.lease_end.value || null, lease_monthly: num(f.lease_monthly), lease_currency: f.lease_currency.value, lease_km_limit: num(f.lease_km_limit),
        lease_includes: [...incl], start_km: num(f.start_km), inspection_date: f.inspection_date.value || null, traffic_ins_date: f.traffic_ins_date.value || null,
        kasko_date: f.kasko_date.value || null, next_service_date: f.next_service_date.value || null, next_service_km: num(f.next_service_km),
        match_keys: f.match_keys.value, active: active.checked, exit_date: f.exit_date.value || null, exit_reason: f.exit_reason.value || null, note: f.note.value };
      let id = v.id;
      if (isNew) id = (await api.post('/api/fleet', b)).id; else await api.put(`/api/fleet/${id}`, b);
      if (photo.files[0]) { const fd = new FormData(); fd.append('file', photo.files[0]); await upload(`/api/fleet/${id}/photo`, fd); }
      OPTS = null;
      toast('Kaydedildi', 'success'); done?.(id);
    } }] });
  if (prefilled) toast('Muhasebe kaydından dolduruldu; kontrol edip kaydedin');
}

// ---------------- Araç detayı ----------------
async function detail(view, id, ctx) {
  loading(view);
  let v;
  try { v = await api.get(`/api/fleet/${id}`); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  META = v.meta;
  const reload = () => detail(view, id, ctx);
  const cur = v.assignments.find(a => !a.end_date);
  const year = String(new Date().getFullYear());
  let tab = sessionStorage.getItem('fleet.tab') || 'expenses';
  const pane = h('div');
  const tabs = segmented([['expenses', t('Giderler ({n})', { n: v.expenses.length })], ['assign', t('Zimmet ({n})', { n: v.assignments.length })],
    ['docs', t('Belgeler ({n})', { n: v.docs.length })], ['info', 'Bilgiler']], tab, k => { tab = k; try { sessionStorage.setItem('fleet.tab', k); } catch { /* */ } drawTab(); }, { tabs: true });
  const drawTab = () => ({ expenses: expensesPane, assign: assignPane, docs: docsPane, info: infoPane }[tab] || expensesPane)(pane, v, reload);
  const photoIn = h('input', { type: 'file', accept: 'image/*', hidden: true });
  photoIn.addEventListener('change', async () => {
    if (!photoIn.files[0]) return;
    const fd = new FormData(); fd.append('file', photoIn.files[0]);
    try { await upload(`/api/fleet/${id}/photo`, fd); toast('Fotoğraf güncellendi', 'success'); reload(); } catch (e) { toastError(e); }
  });
  const strip = statStrip();
  strip.set([{ icon: 'finance', label: 'Toplam gider', value: money0(v.spend_total) },
    { icon: 'fleet', label: 'Güncel km', value: kmTxt(v.km_now) },
    { icon: 'finance', label: 'Km başına maliyet', value: v.cost_per_km != null ? money(v.cost_per_km) : '—' },
    v.field.tasks ? { icon: 'field', label: 'Saha görevi', value: v.field.tasks, sub: v.field.km ? kmTxt(v.field.km) : null } : null]);
  const acts = [h('button', { class: 'btn sm primary', type: 'button', onclick: () => vehicleForm(v, reload) }, 'Düzenle')];
  if (v.active && !cur) acts.push(h('button', { class: 'btn sm', type: 'button', onclick: () => assignForm(v, null, reload) }, 'Zimmetle'));
  if (cur) acts.push(h('button', { class: 'btn sm', type: 'button', onclick: () => openForm(cur.id) }, 'Zimmet formu'),
    h('button', { class: 'btn sm', type: 'button', onclick: () => returnForm(v, cur, reload) }, 'İade al'));
  acts.push(h('button', { class: 'btn sm', type: 'button', onclick: () => expenseForm(v, null, reload) }, '＋ Gider'),
    h('button', { class: 'btn sm ghost', type: 'button', onclick: () => deleteVehicle(v) }, 'Sil'));
  clear(view,
    h('div', { class: 'cf-head' }, h('a', { class: 'small', href: '#/fleet' }, '← Araçlar')),
    h('section', { class: 'card fl-hero' },
      h('div', { class: 'fl-hero-photo', title: 'Fotoğrafı değiştir', onclick: () => photoIn.click() },
        v.photo ? h('img', { src: fileUrl(v.photo, 1024), alt: '' }) : h('div', { class: 'fl-ph' }, carIcon(), h('small', null, 'Fotoğraf ekle')), photoIn),
      h('div', { class: 'fl-hero-main' },
        h('div', { class: 'fl-row' }, plate(v.plate, true),
          h('span', { class: `fl-own ${v.ownership} inline` }, v.ownership === 'leased' ? t('Kiralık · {f}', { f: v.lessor_name || '—' }) : 'Şirket malı'),
          v.active ? null : h('span', { class: 'badge' }, META.exit_reasons[v.exit_reason] || 'Pasif')),
        h('h2', { class: 'fl-hero-name' }, vname(v) || v.description || '—'),
        h('div', { class: 'fl-hero-sub muted small' }, [META.body_types[v.body_type], META.fuel_types[v.fuel_type], v.color].filter(Boolean).join(' · ')),
        h('div', { class: 'fl-who big' }, cur
          ? [h('span', { class: 'fl-ini' }, initials(cur.full_name)), h('div', null, h('b', null, cur.full_name),
            h('div', { class: 'small muted' }, t('{d} tarihinden beri zimmetli', { d: fmtDate(cur.start_date) }), cur.accepted_at ? ' · ✓ ' : ' · ',
              cur.accepted_at ? t('onaylandı') : h('span', { class: 'fin-late' }, 'personel onayı bekleniyor')))]
          : h('span', { class: 'muted' }, v.active ? 'Araç boşta — kimseye zimmetli değil' : 'Araç pasif')),
        v.dues.length ? h('div', { class: 'fl-dues' }, v.dues.map(dueChip)) : null,
        h('div', { class: 'ct-acts' }, acts))),
    strip, h('div', { class: 'cf-tabs' }, tabs), pane);
  drawTab();
}

function deleteVehicle(v) {
  const inp = h('input', { class: 'input', placeholder: v.plate });
  modal({ title: 'Aracı sil', body: h('div', null, h('p', null, t('“{p}” ve ona ait zimmet, gider ve belge kayıtları kalıcı olarak silinecek. Filodan çıkan araçlar için silmek yerine “pasif” yapmanız önerilir. Onaylamak için plakayı yazın:', { p: v.plate })), inp),
    actions: [{ label: 'Vazgeç' }, { label: 'Sil', class: 'danger', onClick: async () => {
      await api.del(`/api/fleet/${v.id}?confirm=${encodeURIComponent(inp.value)}`); toast('Silindi'); location.hash = '#/fleet';
    } }] });
}

// ---- Giderler
function monthChart(entries, months) {
  // entries: [{ month: 'YYYY-MM', category, amount }] → yığılmış sütunlar
  const by = new Map(months.map(m => [m, {}]));
  for (const e of entries) { const b = by.get(e.month); if (b) b[e.category] = (b[e.category] || 0) + e.amount; }
  const max = Math.max(1, ...[...by.values()].map(b => sum(Object.values(b))));
  return h('div', { class: 'fl-chart' }, months.map(m => {
    const b = by.get(m); const tot = sum(Object.values(b));
    return h('div', { class: 'fl-col', title: `${m} · ${money(tot)}\n${Object.entries(b).map(([k, x]) => `${META.categories[k] || k}: ${money(x)}`).join('\n')}` },
      h('div', { class: 'fl-col-bar' }, Object.entries(b).sort((x, y) => y[1] - x[1]).map(([k, x]) => h('i', { style: { height: `${(x / max) * 100}%`, background: CAT_TONE[k] || CAT_TONE.diger } }))),
      h('small', null, m.slice(5)), tot ? h('em', null, short(tot)) : null);
  }));
}
const short = n => (n >= 1e6 ? `${(n / 1e6).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} Mn` : n >= 1e3 ? `${Math.round(n / 1e3).toLocaleString('tr-TR')} B` : Math.round(n).toLocaleString('tr-TR'));
const lastMonths = (n = 12) => {
  const d = new Date(); d.setDate(1);
  const out = [];
  for (let i = 0; i < n; i++) { out.unshift(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`); d.setMonth(d.getMonth() - 1); }
  return out;
};
const catBars = byCat => {
  const ent = Object.entries(byCat).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...ent.map(e => e[1]));
  return h('div', { class: 'fl-cats' }, ent.map(([k, x]) => h('div', { class: 'fl-cat' },
    h('span', { class: 'fl-cat-l' }, h('i', { style: { background: CAT_TONE[k] || CAT_TONE.diger } }), META.categories[k] || k),
    h('div', { class: 'fl-cat-bar' }, h('i', { style: { width: `${((x / max) * 100).toFixed(1)}%`, background: CAT_TONE[k] || CAT_TONE.diger } })),
    h('b', null, money0(x)))));
};
const SRC = { manual: ['Elle', ''], mikro: ['Muhasebe', 'blue'], finans: ['Kasa / banka', 'green'] };

function expensesPane(root, v, reload) {
  let cat = '';
  const byCat = {};
  v.expenses.forEach(e => { byCat[e.category] = (byCat[e.category] || 0) + e.amount; });
  const fuel = v.expenses.filter(e => e.category === 'yakit');
  const liters = sum(fuel, 'liters');
  const list = h('div');
  const draw = () => {
    const shown = v.expenses.filter(e => !cat || e.category === cat);
    clear(list, shown.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table fl-exp' },
      h('thead', null, h('tr', null, ['Tarih', 'Kategori', 'Açıklama', 'Kaynak', 'Litre / km', 'Tutar', ''].map(x => h('th', null, x)))),
      h('tbody', null, shown.map(e => h('tr', null, h('td', { class: 'nowrap' }, fmtDate(e.date)), h('td', null, catBadge(e.category)),
        h('td', null, h('div', null, e.vendor || e.description || '—'), e.vendor && e.description ? h('div', { class: 'small muted' }, e.description) : null,
          e.receipt ? h('a', { class: 'small', href: fileUrl(e.receipt), target: '_blank', rel: 'noopener' }, '📎 Fiş') : null),
        h('td', null, h('span', { class: `badge ${SRC[e.source]?.[1] || ''}` }, SRC[e.source]?.[0] || e.source),
          e.ref_total && e.ref_total - e.amount > 0.01 ? h('div', { class: 'small muted' }, t('bölüşüldü · {n}', { n: money0(e.ref_total) })) : null),
        h('td', { class: 'small num' }, [e.liters ? `${e.liters.toLocaleString('tr-TR')} L` : null, e.km ? kmTxt(e.km) : null].filter(Boolean).join(' · ') || '—'),
        h('td', { class: 'num' }, h('b', null, money(e.amount))),
        h('td', { class: 'cf-doc-acts' }, h('button', { class: 'btn sm', type: 'button', title: 'Düzenle', onclick: () => expenseForm(v, e, reload) }, '✎'),
          h('button', { class: 'btn sm ghost', type: 'button', title: e.source === 'manual' ? 'Sil' : 'Etiketi kaldır', onclick: async () => {
            if (!await confirmDialog(e.source === 'manual' ? 'Gideri sil' : 'Etiketi kaldır', e.source === 'manual' ? 'Gider kaydı silinsin mi?' : 'Muhasebe hareketi bu araçtan çıkarılsın mı? (Hareket “Gider Etiketleme” listesine geri döner.)', { okLabel: 'Evet', danger: true })) return;
            try { await api.del(`/api/fleet/expenses/${e.id}`); reload(); } catch (err) { toastError(err); }
          } }, '🗑'))))))) : h('div', { class: 'card empty' }, v.expenses.length ? 'Bu kategoride gider yok.' : 'Henüz gider yok. Muhasebedeki hareketleri “Gider Etiketleme”den bu araca etiketleyin ya da elle ekleyin.'));
  };
  const chips = h('div', { class: 'cf-chips' });
  const drawChips = () => clear(chips, [['', t('Tümü ({n})', { n: v.expenses.length })], ...Object.keys(byCat).map(k => [k, `${META.categories[k] || k} (${v.expenses.filter(e => e.category === k).length})`])]
    .map(([k, l]) => h('button', { class: `cf-chip ${cat === k ? 'on' : ''}`, type: 'button', onclick: () => { cat = k; drawChips(); draw(); } }, l)));
  const ms = lastMonths(12);
  clear(root,
    h('div', { class: 'filters' }, h('button', { class: 'btn primary sm', type: 'button', onclick: () => expenseForm(v, null, reload) }, '＋ Gider ekle'),
      h('a', { class: 'btn sm', href: `#/fleet/moves?v=${v.id}` }, 'Muhasebeden etiketle'), h('span', { class: 'spacer' }),
      liters ? h('span', { class: 'small muted' }, t('Toplam yakıt {l} L', { l: Math.round(liters).toLocaleString('tr-TR') })) : null),
    v.expenses.length ? h('div', { class: 'fl-two' },
      h('div', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, 'Kategoriye göre'), catBars(byCat)),
      h('div', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, 'Son 12 ay'), monthChart(v.expenses.map(e => ({ month: e.date.slice(0, 7), category: e.category, amount: e.amount })), ms))) : null,
    h('div', { class: 'filters' }, chips), list);
  drawChips(); draw();
}

function expenseForm(v, e, done) {
  const isNew = !e;
  e = e || { date: today(), category: 'yakit', source: 'manual' };
  const auto = e.source !== 'manual';
  const date = h('input', { class: 'input', type: 'date', value: e.date || '', disabled: auto });
  const cat = h('select', { class: 'input' }, Object.entries(META.categories).map(([k, l]) => h('option', { value: k, selected: k === e.category }, l)));
  const amount = h('input', { class: 'input', type: 'number', step: '0.01', min: 0, value: e.amount ?? '', disabled: auto });
  const liters = h('input', { class: 'input', type: 'number', step: '0.01', min: 0, value: e.liters ?? '' });
  const km = h('input', { class: 'input', type: 'number', min: 0, value: e.km ?? '', placeholder: v.km_now ? String(Math.round(v.km_now)) : '' });
  const vendor = h('input', { class: 'input', value: e.vendor || '', disabled: auto, placeholder: 'İstasyon / servis / firma' });
  const desc = h('input', { class: 'input', value: e.description || '' });
  const file = h('input', { type: 'file', accept: 'image/*,application/pdf' });
  const litBox = field('Litre', liters);
  const sync = () => { litBox.hidden = cat.value !== 'yakit'; };
  cat.addEventListener('change', sync); sync();
  modal({ title: isNew ? t('{p} — gider ekle', { p: v.plate }) : 'Gider', body: h('div', null,
    auto ? h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Muhasebe / finans hareketinden gelen kaydın tarihi ve tutarı kaynağa bağlıdır; kategori, litre, km ve açıklama düzenlenebilir.') : null,
    h('div', { class: 'cf-3' }, field('Tarih', date), field('Kategori', cat), field('Tutar (₺)', amount)),
    h('div', { class: 'cf-3' }, litBox, field('Km', km), field('Firma', vendor)), field('Açıklama', desc),
    isNew ? field('Fiş / fatura (ops.)', file) : null),
  actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
    const b = { date: date.value, category: cat.value, amount: Number(amount.value) || 0, liters: liters.value ? Number(liters.value) : null,
      km: km.value ? Number(km.value) : null, vendor: vendor.value, description: desc.value };
    if (isNew && file.files[0]) b.upload_id = await uploadLarge(file.files[0], 'fleet');
    if (isNew) await api.post(`/api/fleet/${v.id}/expenses`, b); else await api.put(`/api/fleet/expenses/${e.id}`, b);
    toast('Kaydedildi', 'success'); done?.();
  } }] });
}

// ---- Zimmet
function assignPane(root, v, reload) {
  const cur = v.assignments.find(a => !a.end_date);
  const past = v.assignments.filter(a => a.end_date);
  const curCard = cur ? h('div', { class: 'card fl-asg cur' },
    h('span', { class: 'fl-ini lg' }, initials(cur.full_name)),
    h('div', { class: 'fl-asg-main' }, h('b', null, cur.full_name),
      h('div', { class: 'small muted' }, t('Teslim: {d}', { d: fmtDate(cur.start_date) }), cur.start_km != null ? ` · ${kmTxt(cur.start_km)}` : '', cur.start_fuel ? ` · ${t('yakıt {f}', { f: META.fuel_levels[cur.start_fuel] || cur.start_fuel })}` : ''),
      h('div', { class: 'small' }, cur.accepted_at ? h('span', { class: 'fl-ok' }, t('✓ Personel {d} tarihinde uygulamada onayladı', { d: fmtDateTime(cur.accepted_at) }))
        : h('span', { class: 'fin-late' }, 'Personel onayı bekleniyor — Kişisel › Araç Zimmetim ekranından onaylar')),
      cur.equipment.length ? h('div', { class: 'small muted' }, t('Ekipman: {e}', { e: cur.equipment.join(', ') })) : null,
      cur.condition ? h('div', { class: 'small' }, t('Durum: {c}', { c: cur.condition })) : null),
    h('div', { class: 'fl-asg-acts' },
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => openForm(cur.id) }, 'Zimmet formu'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => returnForm(v, cur, reload) }, 'İade al'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => assignForm(v, cur, reload) }, 'Düzenle'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => uploadSigned(v, cur, reload) }, t('İmzalı formu yükle ({n})', { n: cur.doc_count })),
      h('button', { class: 'btn sm', type: 'button', onclick: () => assignForm(v, null, reload) }, 'Devret')))
    : h('div', { class: 'card empty' }, v.active ? h('div', null, h('p', null, 'Araç şu an kimseye zimmetli değil.'),
      h('button', { class: 'btn primary', type: 'button', onclick: () => assignForm(v, null, reload) }, 'Personele zimmetle')) : 'Pasif araç zimmetlenemez.');
  clear(root, curCard,
    past.length ? h('h3', { class: 'fl-h3', style: { margin: '16px 0 8px' } }, 'Zimmet geçmişi') : null,
    past.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Personel', 'Teslim', 'İade', 'Km', 'Not', ''].map(x => h('th', null, x)))),
      h('tbody', null, past.map(a => h('tr', null, h('td', null, h('b', null, a.full_name), a.accepted_at ? h('div', { class: 'small fl-ok' }, '✓ onaylı') : null),
        h('td', { class: 'nowrap' }, fmtDate(a.start_date)), h('td', { class: 'nowrap' }, fmtDate(a.end_date)),
        h('td', { class: 'small num' }, a.start_km != null && a.end_km != null ? `${kmTxt(a.start_km)} → ${kmTxt(a.end_km)} (${kmTxt(a.end_km - a.start_km)})` : kmTxt(a.end_km ?? a.start_km)),
        h('td', { class: 'small' }, a.end_note || '—'),
        h('td', { class: 'cf-doc-acts' }, h('button', { class: 'btn sm', type: 'button', onclick: () => openForm(a.id) }, 'Form'),
          h('button', { class: 'btn sm', type: 'button', title: 'İmzalı form', onclick: () => uploadSigned(v, a, reload) }, `📎 ${a.doc_count}`)))))))
      : null);
}

async function assignForm(v, a, done) {
  let o;
  try { o = await options(); } catch (e) { return toastError(e); }
  const cur = v.assignments.find(x => !x.end_date);
  const transfer = !a && cur;
  a = a || { start_date: today(), start_km: v.km_now ?? null, start_fuel: null, equipment: ['Ruhsat', 'Trafik sigortası poliçesi'] };
  const who = h('select', { class: 'input', disabled: !!a.id }, h('option', { value: '' }, '— Personel seçin —'),
    o.users.filter(u => !transfer || u.id !== cur.user_id).map(u => h('option', { value: u.id, selected: u.id === a.user_id }, [u.full_name, u.title || u.department].filter(Boolean).join(' · '))));
  const date = h('input', { class: 'input', type: 'date', value: a.start_date || today() });
  const km = h('input', { class: 'input', type: 'number', min: 0, value: a.start_km ?? '' });
  let fuel = a.start_fuel || '';
  const fuelSeg = segmented(Object.entries(META.fuel_levels), fuel, k => { fuel = k; });
  const eq = new Set(a.equipment || []);
  const all = [...new Set([...META.equipment, ...eq])];
  const eqBox = h('div', { class: 'fl-checks cols' }, all.map(x => {
    const c = h('input', { type: 'checkbox', checked: eq.has(x) });
    c.addEventListener('change', () => { if (c.checked) eq.add(x); else eq.delete(x); });
    return h('label', null, c, ' ', x);
  }));
  const cond = h('textarea', { class: 'input', rows: 2, placeholder: 'ör. Sağ ön çamurlukta çizik; iç temizlik iyi' }); cond.value = a.condition || '';
  const note = h('textarea', { class: 'input', rows: 2 }); note.value = a.note || '';
  modal({ title: a.id ? 'Zimmet bilgileri' : transfer ? t('{p} — devret', { p: v.plate }) : t('{p} — personele zimmetle', { p: v.plate }), wide: true,
    body: h('div', null,
      transfer ? h('div', { class: 'fl-warn' }, t('Araç şu an {n} üzerinde. Kaydedince o zimmet bu tarih ve km ile kapanır, araç yeni personele geçer.', { n: cur.full_name })) : null,
      a.id && a.accepted_at ? h('div', { class: 'fl-warn' }, 'Personel bu zimmeti onayladı. Teslim bilgilerini değiştirirseniz onay sıfırlanır ve personel yeniden onaylar.') : null,
      h('div', { class: 'cf-3' }, field('Personel', who), field('Teslim tarihi', date), field('Teslim km', km)),
      field('Yakıt seviyesi', fuelSeg), field('Teslim edilen ekipman / belgeler', eqBox),
      h('div', { class: 'cf-2' }, field('Hasar / durum notu', cond), field('Not', note))),
    actions: [{ label: 'Vazgeç' }, ...(a.id && !a.accepted_at ? [{ label: 'Sil', class: 'danger', onClick: async () => {
      if (!await confirmDialog('Zimmet kaydını sil', 'Henüz onaylanmamış zimmet kaydı silinsin mi?', { okLabel: 'Sil', danger: true })) return true;
      await api.del(`/api/fleet/assignments/${a.id}`); done?.();
    } }] : []), { label: a.id ? 'Kaydet' : 'Zimmetle', class: 'primary', onClick: async () => {
      const b = { user_id: Number(who.value) || a.user_id, start_date: date.value, start_km: km.value === '' ? null : Number(km.value), start_fuel: fuel || null,
        equipment: [...eq], condition: cond.value, note: note.value };
      if (!b.user_id) throw new Error(t('Personel seçin'));
      if (a.id) {
        const r = await api.put(`/api/fleet/assignments/${a.id}`, b);
        toast(r.acceptance_reset ? 'Kaydedildi — personelin yeniden onaylaması gerekiyor' : 'Kaydedildi', 'success');
        done?.();
      } else {
        const r = await api.post(`/api/fleet/${v.id}/assign`, b);
        toast('Zimmetlendi — personele onay bildirimi gitti', 'success');
        done?.();
        openForm(r.id);
      }
    } }] });
}

function returnForm(v, a, done) {
  const date = h('input', { class: 'input', type: 'date', value: today() });
  const km = h('input', { class: 'input', type: 'number', min: a.start_km || 0, value: v.km_now ?? '' });
  let fuel = '';
  const note = h('textarea', { class: 'input', rows: 3, placeholder: 'Hasar, eksik ekipman, temizlik durumu…' });
  modal({ title: t('{p} — iade al', { p: v.plate }), body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, t('{n} üzerindeki zimmet kapanacak.', { n: a.full_name })),
    h('div', { class: 'cf-2' }, field('İade tarihi', date), field('İade km', km)), field('Yakıt seviyesi', segmented(Object.entries(META.fuel_levels), fuel, k => { fuel = k; })),
    field('İade notu', note)),
  actions: [{ label: 'Vazgeç' }, { label: 'İade al', class: 'primary', onClick: async () => {
    await api.post(`/api/fleet/assignments/${a.id}/return`, { end_date: date.value, end_km: km.value === '' ? null : Number(km.value), end_fuel: fuel || null, end_note: note.value });
    toast('Araç iade alındı', 'success'); done?.();
  } }] });
}

function uploadSigned(v, a, done) {
  const docs = v.docs.filter(d => d.assignment_id === a.id);
  const file = h('input', { type: 'file', accept: 'image/*,application/pdf' });
  modal({ title: t('İmzalı zimmet formu · {n}', { n: a.full_name }), body: h('div', null,
    docs.length ? h('ul', { class: 'fl-doclist' }, docs.map(d => h('li', null, h('a', { href: fileUrl(d.path), target: '_blank', rel: 'noopener' }, d.name), h('span', { class: 'small muted' }, ` · ${fmtDateTime(d.created_at)}`)))) : null,
    h('p', { class: 'small muted' }, 'Yazdırıp imzalatılan formun taramasını (PDF / fotoğraf) yükleyin.'), file),
  actions: [{ label: 'Kapat' }, { label: 'Yükle', class: 'primary', onClick: async () => {
    if (!file.files[0]) throw new Error(t('Dosya seçin'));
    const tok = await uploadLarge(file.files[0], 'fleet');
    await api.post(`/api/fleet/${v.id}/docs`, { upload_id: tok, kind: 'zimmet', assignment_id: a.id });
    toast('Yüklendi', 'success'); done?.();
  } }] });
}

// ---- Zimmet formu (uygulamada görüntüle / yazdır / personel onayı)
const ZF_CSS = `.zf{background:#fff;color:#111;font:10.5pt/1.45 -apple-system,'Segoe UI',Arial,sans-serif;max-width:190mm;margin:0 auto}
.zf *{box-sizing:border-box}.zf-top{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #111;padding-bottom:6pt;margin-bottom:8pt}
.zf-top b{font-size:12pt}.zf-no{font:9pt/1.4 Menlo,Consolas,monospace;text-align:right;color:#444}
.zf h1{font-size:15pt;text-align:center;margin:4pt 0 10pt;letter-spacing:.06em}.zf h3{font-size:10.5pt;margin:10pt 0 4pt;text-transform:uppercase;letter-spacing:.04em;color:#333}
.zf table{width:100%;border-collapse:collapse;table-layout:fixed;margin:0}.zf td,.zf th{border:1px solid #999!important;padding:3pt 6pt;vertical-align:top;text-align:left;color:#111;background:none;font-size:10pt;height:auto}
.zf th{background:#f1f3f5!important;font-weight:600;width:19%;white-space:nowrap;text-transform:none;letter-spacing:0;color:#333}.zf .zf-eq{display:grid;grid-template-columns:repeat(3,1fr);gap:2pt 10pt;border:1px solid #999;padding:5pt 7pt}
.zf .zf-eq span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.zf ol{margin:0;padding-left:16pt}.zf li{margin:1pt 0;text-align:justify}
.zf .zf-box{border:1px solid #999;padding:5pt 7pt;min-height:26pt;white-space:pre-wrap}
.zf .zf-sig{display:grid;grid-template-columns:1fr 1fr;gap:14pt;margin-top:14pt}.zf .zf-sig div{border:1px solid #999;padding:6pt 8pt;min-height:62pt}
.zf .zf-sig small{display:block;color:#555}.zf .zf-proof{margin-top:10pt;border:1px dashed #2f855a;background:#f0fff4;color:#22543d;padding:5pt 8pt;font-size:9pt}
@media screen and (max-width:640px){.zf table,.zf tbody{display:block}.zf tr{display:grid;grid-template-columns:40% 60%}.zf th,.zf td{display:block;width:auto;white-space:normal;overflow-wrap:anywhere}
.zf .zf-eq{grid-template-columns:1fr 1fr}.zf .zf-eq span{white-space:normal}.zf h1{font-size:13pt}.zf-top{flex-direction:column;gap:4pt}.zf-no{text-align:left!important}}`;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function zimmetHtml(f) {
  const a = f.assignment, v = f.vehicle, p = f.person || {}, m = f.meta;
  const kv4 = pairs => {
    let out = '';
    for (let i = 0; i < pairs.length; i += 2) {
      const [k1, v1] = pairs[i]; const [k2, v2] = pairs[i + 1] || ['', ''];
      out += `<tr><th>${esc(k1)}</th><td>${esc(v1)}</td><th>${esc(k2)}</th><td>${esc(v2)}</td></tr>`;
    }
    return `<table>${out}</table>`;
  };
  const eqAll = [...new Set([...(m.equipment || []), ...a.equipment])];
  const clauses = (f.clauses || '').split('\n').map(s => s.trim()).filter(Boolean);
  const fuel = k => (k ? m.fuel_levels[k] || k : '');
  const kmv = n => (n == null ? '' : `${Math.round(n).toLocaleString('tr-TR')} km`);
  const ret = a.end_date ? kv4([['İade tarihi', fmtDate(a.end_date)], ['İade km', kmv(a.end_km)], ['Yakıt seviyesi', fuel(a.end_fuel)], ['Not', a.end_note || '']])
    : kv4([['İade tarihi', ''], ['İade km', ''], ['Yakıt seviyesi', ''], ['Not', '']]);
  return `<div class="zf">
  <div class="zf-top"><div><b>${esc(f.company)}</b><div style="font-size:9pt;color:#555">Araç Yönetimi</div></div>
    <div class="zf-no">Form No: Z-${esc(String(a.id).padStart(5, '0'))}<br>Düzenlenme: ${esc(fmtDate(a.created_at))}</div></div>
  <h1>ARAÇ ZİMMET TUTANAĞI</h1>
  <h3>Araç bilgileri</h3>${kv4([['Plaka', v.plate], ['Marka / Model', [v.brand, v.model].filter(Boolean).join(' ')], ['Model yılı', v.year || ''], ['Renk', v.color || ''],
    ['Şasi no', v.vin || ''], ['Motor no', v.engine_no || ''], ['Yakıt türü', m.fuel_types[v.fuel_type] || ''], ['Mülkiyet', v.ownership === 'leased' ? `Kiralık${v.lessor_name ? ` (${v.lessor_name})` : ''}` : 'Şirket malı']])}
  <h3>Teslim alan personel</h3>${kv4([['Adı soyadı', p.full_name || ''], ['T.C. kimlik no', p.tc_no || ''], ['Görevi', p.title || ''], ['Birimi', p.department || '']])}
  <h3>Teslim bilgileri</h3>${kv4([['Teslim tarihi', fmtDate(a.start_date)], ['Teslim km', kmv(a.start_km)], ['Yakıt seviyesi', fuel(a.start_fuel)], ['Teslim eden', f.delivered_by || '']])}
  <h3>Teslim edilen ekipman ve belgeler</h3><div class="zf-eq">${eqAll.map(x => `<span>${a.equipment.includes(x) ? '☑' : '☐'} ${esc(x)}</span>`).join('')}</div>
  <h3>Hasar / durum notu</h3><div class="zf-box">${esc(a.condition || '—')}</div>
  ${clauses.length ? `<h3>Kullanım şartları</h3><ol>${clauses.map(c => `<li>${esc(c)}</li>`).join('')}</ol>` : ''}
  <h3>İade bilgileri</h3>${ret}
  <div class="zf-sig"><div><b>Teslim eden</b><small>${esc(f.delivered_by || '')}</small><small style="margin-top:28pt">İmza</small></div>
    <div><b>Teslim alan</b><small>${esc(p.full_name || '')}</small><small style="margin-top:28pt">İmza</small></div></div>
  ${a.accepted_at ? `<div class="zf-proof">Bu tutanak ${esc(p.full_name || '')} tarafından ${esc(fmtDateTime(a.accepted_at))} tarihinde uygulama üzerinden okunup elektronik olarak onaylanmıştır${a.accepted_ip ? ` (IP: ${esc(a.accepted_ip)})` : ''}.</div>` : ''}
</div>`;
}

function printZimmet(f) {
  const w = window.open('', '_blank');
  if (!w) return toast('Açılır pencere engellendi', 'err');
  w.document.open();
  w.document.write(`<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>Araç Zimmet Tutanağı Z-${esc(f.assignment.id)} · ${esc(f.vehicle.plate)}</title>
    <style>@page{size:A4;margin:12mm}body{margin:0;background:#fff}${ZF_CSS}</style></head><body>${zimmetHtml(f)}</body></html>`);
  w.document.close();
  setTimeout(() => { w.focus(); w.print(); }, 350);
}

export async function openForm(aid, done) {
  let f;
  try { f = await api.get(`/api/fleet/assignments/${aid}/form`); } catch (e) { return toastError(e); }
  const box = h('div', { class: 'zf-wrap' });
  box.innerHTML = `<style>${ZF_CSS}</style>${zimmetHtml(f)}`;
  const canAccept = f.mine && !f.assignment.accepted_at && !f.assignment.end_date;
  const ok = h('input', { type: 'checkbox' });
  modal({ title: t('Araç zimmet tutanağı · {p}', { p: f.vehicle.plate }), wide: true,
    body: h('div', null, box, canAccept ? h('label', { class: 'fl-accept' }, ok, ' ', 'Tutanağı okudum; aracı ve işaretli ekipmanı belirtilen durumda teslim aldım, kullanım şartlarını kabul ediyorum.') : null),
    actions: [{ label: 'Yazdır', onClick: () => { printZimmet(f); return true; } }, 'spacer',
      ...(canAccept ? [{ label: 'Teslim aldım — onayla', class: 'primary', onClick: async () => {
        if (!ok.checked) throw new Error(t('Onaylamak için kutucuğu işaretleyin'));
        await api.post(`/api/fleet/assignments/${aid}/accept`);
        toast('Zimmet onaylandı', 'success'); done?.();
      } }] : [{ label: 'Kapat', class: 'primary' }])] });
}

// ---- Belgeler
function docsPane(root, v, reload) {
  let kind = v.ownership === 'leased' && !v.docs.some(d => d.kind === 'kira') ? 'kira' : 'ruhsat';
  const kindSel = h('select', { class: 'input', style: { maxWidth: '220px' } }, Object.entries(META.doc_kinds).map(([k, l]) => h('option', { value: k, selected: k === kind }, l)));
  kindSel.addEventListener('change', () => { kind = kindSel.value; });
  const exp = h('input', { class: 'input', type: 'date', title: 'Geçerlilik bitişi (ops.)', style: { maxWidth: '170px' } });
  const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
  const queue = h('div', { class: 'cf-queue' });
  async function send(files) {
    let n = 0;
    for (const f of [...files]) {
      const bar = h('i');
      const row = h('div', { class: 'cf-q' }, h('span', { class: 'cf-q-n' }, f.name), h('div', { class: 'cf-q-bar' }, bar));
      queue.append(row);
      try {
        const tok = await uploadLarge(f, 'fleet', p => { bar.style.width = `${p}%`; });
        await api.post(`/api/fleet/${v.id}/docs`, { upload_id: tok, kind, expires: exp.value || null });
        row.classList.add('done'); n++;
      } catch (e) { row.classList.add('err'); row.title = e.message; }
    }
    if (n) { toast(t('{n} belge yüklendi', { n }), 'success'); reload(); }
  }
  fileIn.addEventListener('change', () => { send(fileIn.files); fileIn.value = ''; });
  const drop = h('div', { class: 'cf-drop' }, h('b', null, 'Belgeleri buraya sürükleyin'),
    h('span', { class: 'small muted' }, 'Ruhsat, kira sözleşmesi, poliçeler, muayene raporu, servis formları…'),
    h('div', { class: 'ct-acts' }, kindSel, exp, h('button', { class: 'btn primary sm', type: 'button', onclick: () => fileIn.click() }, 'Dosya yükle'), fileIn));
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); send(e.dataTransfer.files); });
  const missingLease = v.ownership === 'leased' && !v.docs.some(d => d.kind === 'kira');
  clear(root, missingLease ? h('div', { class: 'fl-warn' }, 'Kiralık araç: kira sözleşmesi henüz yüklenmedi.') : null, drop, queue,
    v.docs.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Tür', 'Belge', 'Geçerlilik', 'Yükleyen', ''].map(x => h('th', null, x)))),
      h('tbody', null, v.docs.map(d => {
        const dl = d.expires ? Math.round((new Date(d.expires) - new Date(today())) / 86400000) : null;
        return h('tr', null, h('td', null, h('span', { class: 'badge' }, META.doc_kinds[d.kind] || d.kind)),
          h('td', null, h('a', { href: fileUrl(d.path), target: '_blank', rel: 'noopener' }, d.name)),
          h('td', { class: 'small' }, d.expires ? [fmtDate(d.expires), h('div', { class: dl < 0 ? 'fin-late' : dl <= 30 ? 'fl-soon' : 'muted' }, dl < 0 ? t('{n} gün geçti', { n: -dl }) : t('{n} gün kaldı', { n: dl }))] : '—'),
          h('td', { class: 'small muted' }, d.uploaded_by_name || '', h('div', null, fmtDateTime(d.created_at))),
          h('td', { class: 'cf-doc-acts' }, h('a', { class: 'btn sm', href: `${fileUrl(d.path)}?dl=1`, title: 'İndir' }, '⬇'),
            h('button', { class: 'btn sm', type: 'button', title: 'Düzenle', onclick: () => editDoc(d, reload) }, '✎'),
            h('button', { class: 'btn sm ghost', type: 'button', title: 'Sil', onclick: async () => {
              if (!await confirmDialog('Belgeyi sil', t('“{n}” silinsin mi?', { n: d.name }), { okLabel: 'Sil', danger: true })) return;
              try { await api.del(`/api/fleet/docs/${d.id}`); reload(); } catch (e) { toastError(e); }
            } }, '🗑')));
      })))) : h('div', { class: 'card empty' }, 'Henüz belge yok.'));
}

function editDoc(d, done) {
  const name = h('input', { class: 'input', value: d.name });
  const kind = h('select', { class: 'input' }, Object.entries(META.doc_kinds).map(([k, l]) => h('option', { value: k, selected: k === d.kind }, l)));
  const exp = h('input', { class: 'input', type: 'date', value: d.expires || '' });
  modal({ title: 'Belge', body: h('div', null, field('Ad', name), h('div', { class: 'cf-2' }, field('Tür', kind), field('Geçerlilik bitişi', exp))),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => { await api.put(`/api/fleet/docs/${d.id}`, { name: name.value, kind: kind.value, expires: exp.value || null }); done?.(); } }] });
}

// ---- Bilgiler
function infoPane(root, v) {
  const kv = (k, x) => (x || x === 0 ? [h('dt', null, k), h('dd', null, x)] : null);
  const incl = (v.lease_includes || '').split(',').filter(Boolean).map(k => META.lease_includes[k] || k).join(', ');
  clear(root, h('div', { class: 'fl-two' },
    h('section', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, 'Araç'),
      h('dl', { class: 'sys-kv' }, kv('Plaka', v.plate), kv('Marka / model', [v.brand, v.model].filter(Boolean).join(' ')), kv('Model yılı', v.year),
        kv('Kasa tipi', META.body_types[v.body_type]), kv('Yakıt', META.fuel_types[v.fuel_type]), kv('Renk', v.color), kv('Şasi no', v.vin), kv('Motor no', v.engine_no),
        kv('Açıklama', v.description), kv('Eşleştirme anahtarları', v.match_keys), kv('Not', v.note))),
    h('section', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, v.ownership === 'leased' ? 'Kiralama' : 'Satın alma'),
      v.ownership === 'leased'
        ? h('dl', { class: 'sys-kv' }, kv('Kiralayan', v.lessor_name), kv('Sözleşme no', v.lease_no), kv('Başlangıç', v.lease_start && fmtDate(v.lease_start)),
          kv('Bitiş', v.lease_end && fmtDate(v.lease_end)), kv('Aylık kira', v.lease_monthly != null ? `${Number(v.lease_monthly).toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ${v.lease_currency || 'TRY'}` : null),
          kv('Km limiti', v.lease_km_limit && kmTxt(v.lease_km_limit)), kv('Kiraya dahil', incl))
        : h('dl', { class: 'sys-kv' }, kv('Satın alma tarihi', v.purchase_date && fmtDate(v.purchase_date)), kv('Bedel', v.purchase_price != null ? money(v.purchase_price) : null),
          kv('Satıcı', v.seller_name), kv('Belge no', v.purchase_doc), kv('Muhasebe hesabı', v.asset_account)),
      h('h3', { class: 'fl-h3', style: { marginTop: '14px' } }, 'Hatırlatmalar'),
      h('dl', { class: 'sys-kv' }, kv('Başlangıç km', v.start_km != null ? kmTxt(v.start_km) : null), kv('Muayene bitişi', v.inspection_date && fmtDate(v.inspection_date)),
        kv('Trafik sigortası bitişi', v.traffic_ins_date && fmtDate(v.traffic_ins_date)), kv('Kasko bitişi', v.kasko_date && fmtDate(v.kasko_date)),
        kv('Sonraki bakım', [v.next_service_date && fmtDate(v.next_service_date), v.next_service_km && kmTxt(v.next_service_km)].filter(Boolean).join(' · ')),
        !v.active ? kv('Filodan çıkış', [v.exit_date && fmtDate(v.exit_date), META.exit_reasons[v.exit_reason]].filter(Boolean).join(' · ')) : null))));
}

// ---------------- Gider etiketleme (muhasebe / finans hareketleri) ----------------
async function movesView(root) {
  const focusV = Number((location.hash.match(/[?&]v=(\d+)/) || [])[1]) || null;
  let d, days = 365, mode = 'open', cat = '', q = '';
  const out = h('div');
  const head = h('div');
  const vmap = () => new Map(d.vehicles.map(x => [x.id, x]));
  const st = m => (m.ignored ? 'ignored' : m.tags.length ? (m.remaining > 0.009 ? 'partial' : 'tagged') : 'open');
  async function load() {
    loading(out);
    try { d = await api.get(`/api/fleet/movements/list?days=${days}`); } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    META = META || { categories: d.categories };
    if (!META.categories) META.categories = d.categories;
    draw();
  }
  function draw() {
    const vm = vmap();
    const rows = d.rows.filter(m => !cat || m.category === cat).filter(m => matches(q, m.vendor, m.note, m.doc_no, ...m.accounts, ...m.tags.map(x => x.plate)));
    const open = rows.filter(m => ['open', 'partial'].includes(st(m)));
    const sugg = open.filter(m => m.suggest.length);
    const strong = open.filter(m => m.match === 'plaka' && m.suggest.length === 1 && !m.tags.length);
    const counts = { open: open.length, suggested: sugg.length, tagged: rows.filter(m => st(m) === 'tagged').length, ignored: rows.filter(m => m.ignored).length, all: rows.length };
    const shown = rows.filter(m => ({ open: ['open', 'partial'].includes(st(m)), suggested: sugg.includes(m), tagged: m.tags.length && !m.ignored, ignored: m.ignored, all: true }[mode]))
      .filter(m => !focusV || mode !== 'open' || m.suggest.includes(focusV) || !m.suggest.length);
    const total = sum(shown, 'amount');
    clear(head,
      h('div', { class: 'filters' }, segmented([['open', t('Etiketsiz ({n})', { n: counts.open })], ['suggested', t('Önerilen ({n})', { n: counts.suggested })],
        ['tagged', t('Etiketli ({n})', { n: counts.tagged })], ['ignored', t('Yoksayılan ({n})', { n: counts.ignored })], ['all', 'Tümü']], mode, k => { mode = k; draw(); }),
      strong.length ? h('button', { class: 'btn sm primary', type: 'button', onclick: async () => {
        try { const r = await api.post('/api/fleet/movements/auto', { days, refs: strong.map(m => m.ref) }); toast(t('{n} hareket plakasına göre etiketlendi', { n: r.tagged }), 'success'); load(); } catch (e) { toastError(e); }
      } }, t('Plaka eşleşenleri onayla ({n})', { n: strong.length })) : null),
      h('div', { class: 'small muted fl-mv-sum' }, t('{n} hareket · {t}', { n: shown.length, t: money(total) })));
    clear(out, shown.length ? h('div', { class: 'fl-mvs' }, shown.map(m => moveRow(m, vm))) : h('div', { class: 'card empty' },
      d.accounts ? (mode === 'open' ? 'Etiketlenmemiş araç gideri yok. 🎉' : 'Bu filtrede hareket yok.')
        : 'Muhasebede araç gider hesabı bulunamadı. Mikro verisi Program Ayarları › Entegrasyonlar üzerinden senkronlanınca (yönetici) araç yakıt / bakım / kira / HGS gider hesaplarındaki hareketler burada listelenir. Kasa / banka çıkışlarından araçla ilgili olanlar da görünür.'));
  }
  function moveRow(m, vm) {
    const s = st(m);
    const quick = !m.tags.length && !m.ignored && m.suggest.length === 1 ? vm.get(m.suggest[0]) : null;
    return h('div', { class: `card fl-mv ${s}` },
      h('div', { class: 'fl-mv-date' }, h('b', null, fmtDate(m.date)), m.doc_no ? h('small', { class: 'mono' }, m.doc_no) : null),
      h('div', { class: 'fl-mv-main' },
        h('div', { class: 'fl-mv-t' }, catBadge(m.category), h('b', null, m.vendor || m.note || m.accounts[0] || '—'),
          m.source === 'finans' ? h('span', { class: 'badge green' }, 'Kasa / banka') : null),
        h('div', { class: 'small muted' }, [m.vendor ? m.note : null, m.accounts.join(' · ')].filter(Boolean).join(' — ')),
        m.tags.length ? h('div', { class: 'fl-tags' }, m.tags.map(x => h('span', { class: 'fl-tag' }, plate(x.plate), m.tags.length > 1 ? h('small', null, money0(x.amount)) : null))) : null,
        !m.tags.length && m.suggest.length ? h('div', { class: 'fl-tags' }, h('small', { class: 'muted' }, m.match === 'kiralayan' ? 'Kiralayan firmaya göre:' : 'Öneri:'),
          m.suggest.map(id => vm.get(id)).filter(Boolean).map(x => h('span', { class: 'fl-sugg' }, x.plate)))
          : null),
      h('div', { class: 'fl-mv-amt' }, h('b', null, money(m.amount)), s === 'partial' ? h('small', { class: 'fin-late' }, t('kalan {n}', { n: money(m.remaining) })) : null),
      h('div', { class: 'fl-mv-acts' },
        quick ? h('button', { class: 'btn sm primary', type: 'button', title: 'Önerilen araca etiketle', onclick: async () => {
          try { await api.post('/api/fleet/movements/tag', { ref: m.ref, allocations: [{ vehicle_id: quick.id, amount: m.amount }] }); toast(t('{p} aracına etiketlendi', { p: quick.plate }), 'success'); load(); } catch (e) { toastError(e); }
        } }, `✓ ${quick.plate}`) : null,
        m.ignored ? null : h('button', { class: `btn sm ${quick ? '' : 'primary'}`, type: 'button', onclick: () => tagModal(m, d, focusV, load) }, m.tags.length ? 'Düzenle' : 'Etiketle'),
        m.tags.length ? null : h('button', { class: 'btn sm ghost', type: 'button', title: m.ignored ? 'Listeye geri al' : 'Araçla ilgisi yok', onclick: async () => {
          try { await api.post('/api/fleet/movements/ignore', { ref: m.ref, ignore: !m.ignored }); load(); } catch (e) { toastError(e); }
        } }, m.ignored ? 'Geri al' : 'Yoksay')));
  }
  const catSel = h('select', { class: 'input', style: { maxWidth: '200px' } }, h('option', { value: '' }, 'Tüm kategoriler'));
  const daySel = h('select', { class: 'input', style: { maxWidth: '150px' } }, [[90, 'Son 3 ay'], [180, 'Son 6 ay'], [365, 'Son 1 yıl'], [730, 'Son 2 yıl'], [1825, 'Son 5 yıl']]
    .map(([n, l]) => h('option', { value: n, selected: n === days }, l)));
  daySel.addEventListener('change', () => { days = Number(daySel.value); load(); });
  catSel.addEventListener('change', () => { cat = catSel.value; draw(); });
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Firma, açıklama, belge no, plaka…', style: { maxWidth: '240px' } });
  search.addEventListener('input', () => { q = search.value.trim(); if (d) draw(); });
  clear(root, h('p', { class: 'small muted fl-intro' }, 'Muhasebedeki (Mikro senkronu) araç gider hesaplarına yazılan hareketler ile araçla ilgili kasa / banka çıkışları. Tutarlar muhasebeye gider yazılan tutardır (indirilecek KDV hariç). Bir hareket birden çok araca bölünebilir; etiketlenen tutar aracın giderine eklenir.'),
    h('div', { class: 'filters' }, daySel, catSel, search), head, out);
  await load();
  for (const [k, l] of Object.entries(d?.categories || {})) catSel.append(h('option', { value: k }, l));
}

function tagModal(m, d, focusV, done) {
  const vehicles = d.vehicles;
  const rowsBox = h('div', { class: 'fl-alloc' });
  const info = h('div', { class: 'small' });
  const allocs = [];
  const opt = (sel) => [h('option', { value: '' }, '— Araç —'), ...vehicles.map(x => h('option', { value: x.id, selected: x.id === sel }, `${x.plate}${vname(x) ? ` · ${vname(x)}` : ''}${x.active ? '' : ` (${t('pasif')})`}`))];
  const recalc = () => {
    const s = sum(allocs.map(a => Number(a.amt.value) || 0));
    const rem = Math.round((m.amount - s) * 100) / 100;
    clear(info, t('Dağıtılan {a} / {b}', { a: money(s), b: money(m.amount) }), rem > 0.009 ? h('span', { class: 'fin-late' }, ` · ${t('kalan {n}', { n: money(rem) })}`) : rem < -0.009 ? h('span', { class: 'fin-late' }, ` · ${t('fazla {n}', { n: money(-rem) })}`) : ' ✓');
    litBox.hidden = allocs.length !== 1;
  };
  const addRow = (vid, amount) => {
    const sel = h('select', { class: 'input' }, opt(vid));
    const amt = h('input', { class: 'input', type: 'number', step: '0.01', min: 0, value: amount ?? '' });
    const row = h('div', { class: 'fl-alloc-row' }, sel, amt, h('button', { class: 'btn sm ghost', type: 'button', title: 'Kaldır', onclick: () => {
      if (allocs.length === 1) return;
      allocs.splice(allocs.indexOf(a), 1); row.remove(); recalc();
    } }, '×'));
    const a = { sel, amt, row };
    amt.addEventListener('input', recalc);
    allocs.push(a); rowsBox.append(row); recalc();
  };
  const split = () => {
    const n = allocs.length; const each = Math.floor((m.amount / n) * 100) / 100;
    allocs.forEach((a, i) => { a.amt.value = (i === n - 1 ? Math.round((m.amount - each * (n - 1)) * 100) / 100 : each).toFixed(2); });
    recalc();
  };
  const cat = h('select', { class: 'input' }, Object.entries(d.categories).map(([k, l]) => h('option', { value: k, selected: k === (m.tags[0]?.category || m.category) }, l)));
  const liters = h('input', { class: 'input', type: 'number', step: '0.01', min: 0 });
  const km = h('input', { class: 'input', type: 'number', min: 0 });
  const note = h('input', { class: 'input', placeholder: m.note || '' });
  const litBox = h('div', { class: 'cf-2' }, field('Litre (yakıt)', liters), field('Km', km));
  const pre = m.tags.length ? m.tags.map(x => [x.vehicle_id, x.amount]) : (m.suggest.length ? m.suggest : focusV ? [focusV] : [null]).map(id => [id, null]);
  pre.forEach(([id, a]) => addRow(id, a));
  if (!m.tags.length) split();
  modal({ title: 'Gideri araca etiketle', wide: true, body: h('div', null,
    h('div', { class: 'fl-mv-info' }, h('div', null, catBadge(m.category), ' ', h('b', null, m.vendor || m.note || '—')),
      h('div', { class: 'small muted' }, [fmtDate(m.date), m.doc_no, m.vendor ? m.note : null].filter(Boolean).join(' · ')),
      h('div', { class: 'small muted' }, m.accounts.join(' · ')), h('div', { class: 'fl-mv-big' }, money(m.amount))),
    field('Araç ve tutar', h('div', null, rowsBox, h('div', { class: 'ct-acts' }, h('button', { class: 'btn sm', type: 'button', onclick: () => { addRow(null, null); split(); } }, '＋ Araç ekle (böl)'),
      h('button', { class: 'btn sm', type: 'button', onclick: split }, 'Eşit böl'), info))),
    h('div', { class: 'cf-2' }, field('Kategori', cat), field('Açıklama (ops.)', note)), litBox),
  actions: [{ label: 'Vazgeç' }, ...(m.tags.length ? [{ label: 'Etiketi kaldır', class: 'danger', onClick: async () => {
    await api.del(`/api/fleet/movements/tag?ref=${encodeURIComponent(m.ref)}`); toast('Etiket kaldırıldı'); done?.();
  } }] : []), { label: 'Kaydet', class: 'primary', onClick: async () => {
    const al = allocs.map(a => ({ vehicle_id: Number(a.sel.value), amount: Number(a.amt.value) || 0 })).filter(a => a.vehicle_id && a.amount > 0);
    if (!al.length) throw new Error(t('Araç ve tutar seçin'));
    await api.post('/api/fleet/movements/tag', { ref: m.ref, allocations: al, category: cat.value, liters: liters.value ? Number(liters.value) : null,
      km: km.value ? Number(km.value) : null, note: note.value || null });
    toast('Etiketlendi', 'success'); done?.();
  } }] });
}

// ---------------- Rapor ----------------
async function reportView(root, year) {
  loading(root);
  let d;
  try { d = await api.get(`/api/fleet/report/summary${year ? `?year=${year}` : ''}`); } catch (e) { return clear(root, h('div', { class: 'card empty' }, e.message)); }
  META = META || {};
  META.categories = d.categories;
  const pv = new Map();
  const catTot = {};
  for (const r of d.rows) {
    const x = pv.get(r.vehicle_id) || { plate: r.plate, name: vname(r), active: r.active, cats: {}, total: 0, liters: 0 };
    x.cats[r.category] = (x.cats[r.category] || 0) + r.amount; x.total += r.amount; x.liters += r.liters || 0;
    catTot[r.category] = (catTot[r.category] || 0) + r.amount;
    pv.set(r.vehicle_id, x);
  }
  const cats = Object.keys(catTot).sort((a, b) => catTot[b] - catTot[a]);
  const vs = [...pv.values()].sort((a, b) => b.total - a.total);
  const grand = sum(Object.values(catTot));
  const ysel = h('select', { class: 'input', style: { maxWidth: '120px' } }, [...new Set([String(d.year), ...d.years])].sort().reverse().map(y => h('option', { value: y, selected: y === String(d.year) }, y)));
  ysel.addEventListener('change', () => reportView(root, ysel.value));
  const ms = Array.from({ length: 12 }, (_, i) => `${d.year}-${String(i + 1).padStart(2, '0')}`);
  clear(root, h('div', { class: 'filters' }, ysel),
    vs.length ? [
      h('div', { class: 'fl-two' }, h('div', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, t('{y} — kategoriye göre ({t})', { y: d.year, t: money0(grand) })), catBars(catTot)),
        h('div', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, 'Aylara göre'), monthChart(d.rows.map(r => ({ month: `${d.year}-${r.month}`, category: r.category, amount: r.amount })), ms))),
      h('div', { class: 'card table-wrap' }, h('table', { class: 'table fl-rep' },
        h('thead', null, h('tr', null, h('th', null, 'Araç'), cats.map(c => h('th', { class: 'num' }, d.categories[c] || c)), h('th', { class: 'num' }, 'Toplam'))),
        h('tbody', null, vs.map(x => h('tr', null, h('td', null, plate(x.plate), x.name ? h('div', { class: 'small muted' }, x.name) : null),
          cats.map(c => h('td', { class: 'num small' }, x.cats[c] ? money0(x.cats[c]) : '—')), h('td', { class: 'num' }, h('b', null, money0(x.total)))))),
        h('tfoot', null, h('tr', null, h('th', null, 'Toplam'), cats.map(c => h('th', { class: 'num' }, money0(catTot[c]))), h('th', { class: 'num' }, money0(grand))))))]
      : h('div', { class: 'card empty' }, t('{y} yılında araç gideri yok.', { y: d.year })));
}

// ---------------- Zimmet formu ayarları ----------------
async function settingsView(root) {
  loading(root);
  let s;
  try { s = await api.get('/api/fleet/settings/form'); } catch (e) { return clear(root, h('div', { class: 'card empty' }, e.message)); }
  const clauses = h('textarea', { class: 'input', rows: 9 }); clauses.value = s.clauses;
  const eq = h('textarea', { class: 'input', rows: 9 }); eq.value = s.equipment.join('\n');
  clear(root, h('div', { class: 'fl-two' },
    h('section', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, 'Kullanım şartları'),
      h('p', { class: 'small muted' }, 'Zimmet tutanağında numaralı maddeler olarak yer alır (her satır bir madde). Şirket politikanıza göre düzenleyin; metni hukuk danışmanınıza kontrol ettirmeniz önerilir.'),
      clauses),
    h('section', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, 'Ekipman / belge listesi'),
      h('p', { class: 'small muted' }, 'Zimmet verirken işaretlenecek kalemler (her satır bir kalem).'), eq)),
  h('div', { class: 'ct-acts', style: { marginTop: '12px' } },
    h('button', { class: 'btn primary', type: 'button', onclick: async () => {
      try { await api.put('/api/fleet/settings/form', { clauses: clauses.value, equipment: eq.value.split('\n') }); OPTS = null; toast('Kaydedildi', 'success'); } catch (e) { toastError(e); }
    } }, 'Kaydet'),
    h('button', { class: 'btn', type: 'button', onclick: () => { clauses.value = s.default_clauses; eq.value = s.default_equipment.join('\n'); toast('Varsayılan metin yüklendi; kaydetmeyi unutmayın'); } }, 'Varsayılana dön')));
}

// ---------------- Kişisel › Araç Zimmetim ----------------
export async function renderMine(view) {
  const rows = await api.get('/api/fleet/mine/list');
  const cur = rows.filter(r => !r.end_date);
  const past = rows.filter(r => r.end_date);
  const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));   // yeniden çizim + Kişisel başlığı / sayaç
  clear(view, pageHead('Araç Zimmetim', { back: '#/', sub: 'Size zimmetli araçlar ve zimmet tutanakları' }),
    cur.length ? h('div', { class: 'fl-mine' }, cur.map(r => h('div', { class: `card fl-mine-c ${r.accepted_at ? '' : 'wait'}` },
      h('div', { class: 'fl-photo' }, r.photo ? h('img', { src: fileUrl(r.photo, 512), alt: '' }) : h('div', { class: 'fl-ph' }, carIcon())),
      h('div', { class: 'fl-body' }, plate(r.plate, true), h('div', { class: 'fl-name' }, vname(r) || '—'),
        h('div', { class: 'small muted' }, t('{d} tarihinden beri', { d: fmtDate(r.start_date) }), r.start_km != null ? ` · ${t('teslim {k}', { k: kmTxt(r.start_km) })}` : ''),
        r.dues?.length ? h('div', { class: 'fl-dues' }, r.dues.map(dueChip)) : null,
        r.accepted_at ? h('div', { class: 'small fl-ok' }, t('✓ {d} tarihinde onayladınız', { d: fmtDateTime(r.accepted_at) }))
          : h('div', { class: 'fl-warn' }, 'Zimmet tutanağını okuyup aracı teslim aldığınızı onaylayın.'),
        h('div', { class: 'ct-acts' }, h('button', { class: `btn sm ${r.accepted_at ? '' : 'primary'}`, type: 'button', onclick: () => openForm(r.id, reload) },
          r.accepted_at ? 'Zimmet tutanağı' : 'Tutanağı aç ve onayla'))))))
      : h('div', { class: 'card empty' }, 'Size zimmetli araç yok.'),
    past.length ? h('h3', { class: 'fl-h3', style: { margin: '18px 0 8px' } }, 'Geçmiş zimmetler') : null,
    past.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Araç', 'Teslim', 'İade', ''].map(x => h('th', null, x)))),
      h('tbody', null, past.map(r => h('tr', null, h('td', null, plate(r.plate), h('div', { class: 'small muted' }, vname(r))), h('td', null, fmtDate(r.start_date)),
        h('td', null, fmtDate(r.end_date)), h('td', null, h('button', { class: 'btn sm', type: 'button', onclick: () => openForm(r.id) }, 'Tutanak'))))))) : null);
}
