// Saha Yönetimi: görevler; görev detayında Uçuş, Masraf ve Yol alt modülleri; görev yerleri ve araçlar
import { api, fileUrl, uploadChunked, uploadLarge } from '../api.js';
import { icons } from '../icons.js';
import { printTaskForm, printTaskReport } from '../print.js';
import { ORDER_STATES, TASK_STATES, USAGE_TYPES, badge, queuePlate } from '../status.js';
import { segIcon } from '../segicons.js';
import { stockPicker } from '../stockpick.js';
import {
  clear, confirmDialog, dateTimeInput, every, field, fmtDate, fmtDateTime, fmtDuration, h, matches, modal, moduleToolbar, pageHead, pref,
  progressBar, secondsSince, segmented, selectInput, setPref, statStrip, svgIcon, toast, toastError, uploadPanel, localUploadNotice,
  internTag, nameWithIntern, periodFilter
} from '../ui.js';
import { clock } from '../chart.js';
import { render3D } from './replay3d.js';
import { renderFlight } from './flight.js';
import { logBadge, renderReportView } from './tools.js';

// Görev başlatma ekranında gösterilen uyarılar. İhtiyaca göre düzenlenir.
const START_WARNINGS = [
  'Hava durumu ve rüzgâr hızını kontrol edin.',
  'Uçuş bölgesi izinlerinin geçerli olduğundan emin olun.',
  'Batarya ve yedek batarya şarj seviyelerini kontrol edin.',
  'Kumanda ve telemetri bağlantısını test edin.',
  'Ekipteki herkesin koruyucu ekipmanı tam olmalı.',
];
const LAUNCH = { ARAC_USTU: 'Araç Üstü', RAMPA: 'Fırlatma Rampası' };
const IN_ASSEMBLY = ['MONTAJ', 'SAHADA_MONTAJ'];   // montajı bitmemiş uçak
const tl = v => `${Number(v || 0).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;
const km = v => (v === null || v === undefined ? '—' : `${Number(v).toLocaleString('tr-TR')} km`);
const isManager = ctx => ctx.user.roles.some(r => r === 'Sistem Yöneticisi' || r === 'Saha Sorumlusu');

// Görevin şoförleri: araç satırlarındaki şoförler (eski görevlerde görev düzeyindeki şoför)
const driverPairs = t => [...(t.driver_id ? [[t.driver_id, t.driver_name]] : []),
  ...t.vehicles.filter(v => v.driver_id).map(v => [v.driver_id, v.driver_name])];
export const driversOf = t => [...new Set(driverPairs(t).map(([, n]) => n))].join(', ');

export async function render(view, params, ctx) {
  if (params[0] === 'report' && params[2] === '3d') return render3D(view, Number(params[1]), `#/field/report/${params[1]}`);
  if (params[0] === 'report') return renderReportView(view, Number(params[1]), '#/field', ctx);
  if (params[0] === 'task') return renderTask(view, Number(params[1]), ctx);
  if (params[0] === 'flight') return renderFlight(view, Number(params[1]), ctx, params[2]);
  if (params[0] === 'places') return renderPlaces(view, ctx);
  if (params[0] === 'flights' || (!params[0] && pref('field.view', 'tasks') === 'flights')) return renderFlightsList(view, ctx);
  return renderList(view, ctx);
}

// ---------- Görev listesi ----------
async function renderList(view, ctx) {
  const manager = isManager(ctx);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Görev, uçak, kişi, yer ara…', style: { width: '220px' } });
  const status = selectInput(Object.entries(TASK_STATES).map(([k, s]) => [k, s.label]), { all: 'Tüm durumlar' });
  const driver = h('select', { class: 'input' });
  const place = h('select', { class: 'input' });
  const mineOnly = h('input', { type: 'checkbox' });
  const stats = statStrip();
  const body = h('div');
  let tasks = [];
  let available = null;

  const mine = t => [t.driver_id, t.lead_id, t.pilot_id, t.created_by].includes(ctx.user.id) || t.staff.some(s => s.id === ctx.user.id)
    || t.vehicles.some(v => v.driver_id === ctx.user.id);
  const refill = (sel, pairs, all) => {
    const cur = sel.value;
    clear(sel, h('option', { value: '' }, all), pairs.map(([v, l]) => h('option', { value: v, selected: String(v) === cur }, l)));
  };
  const draw = () => {
    const n = k => tasks.filter(t => t.status === k).length;
    const open = tasks.filter(t => !['RAPOR_TAMAMLANDI', 'IPTAL'].includes(t.status));
    stats.set([
      { label: 'Toplam görev', value: tasks.length },
      { label: 'Başlangıçta bekleyen', value: n('BASLANGIC') },
      { label: 'Görevde', value: n('GOREVDE'), tone: n('GOREVDE') ? 'ok' : '' },
      { label: 'Rapor bekleyen', value: n('GOREV_TAMAMLANDI') + n('BASARISIZ'), tone: n('GOREV_TAMAMLANDI') + n('BASARISIZ') ? 'alert' : '' },
      { label: 'Toplam uçuş', value: tasks.reduce((a, t) => a + t.flights.length, 0), sub: `raporu hazır: ${tasks.reduce((a, t) => a + t.logs_ready, 0)}` },
      { label: 'Toplam masraf', value: tl(tasks.reduce((a, t) => a + t.expense_total, 0)) },
      { label: 'Toplam yol', value: km(tasks.reduce((a, t) => a + (t.distance_km || 0), 0)) },
      { label: 'Benim açık görevlerim', value: open.filter(mine).length },
      manager ? { label: 'Göreve götürülebilir uçak', value: available ?? '—', sub: 'saha deposu + montajda' } : null,
    ]);
    refill(driver, [...new Map(tasks.flatMap(driverPairs))], 'Tüm şoförler');
    refill(place, [...new Map(tasks.filter(t => t.location_id).map(t => [t.location_id, t.location_name]))], 'Tüm görev yerleri');
    const list = tasks.filter(t => (!status.value || t.status === status.value) &&
      (!driver.value || driverPairs(t).some(([d]) => String(d) === driver.value)) &&
      (!place.value || String(t.location_id) === place.value) &&
      (!mineOnly.checked || mine(t)) &&
      matches(q.value, t.code, t.aircraft, t.lead_name, driversOf(t), t.pilot_name, t.location_name, t.vehicle_plate,
        ...t.staff.map(s => s.full_name), ...t.flights.map(f => f.order_code)));
    // Satır: temel bilgi kalın, ayrıntılar altında küçük yazıyla (kişi adları taşmasın)
    const line = (label, value) => (value ? h('div', { class: 'task-sub' }, h('span', null, `${label}: `), value) : null);
    clear(body, list.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'task-table' },
      h('thead', null, h('tr', null, ['Görev', 'Uçaklar', 'Ekip', 'Görev yeri / araçlar', 'Rapor', 'Oluşturma']
        .map(c => h('th', null, c)))),
      h('tbody', null, list.map(t => h('tr', { class: 'click', onclick: () => { location.hash = `#/field/task/${t.id}`; } },
        h('td', null, h('b', { class: 'mono' }, t.code), h('div', { style: { marginTop: '4px' } }, badge(TASK_STATES, t.status))),
        h('td', null, h('b', { class: 'mono' }, t.aircraft || '—'), h('div', { class: 'task-sub' }, `${t.flights.length} uçuş`)),
        h('td', null,
          h('b', null, t.lead_name || '—'), h('span', { class: 'small muted' }, ' · saha sorumlusu'),
          line('Pilot', t.pilot_name),
          line('Şoför', driversOf(t)),
          line('Personel', t.staff.map(x => x.full_name).join(', '))),
        h('td', null, h('b', null, t.location_name || '—'),
          t.vehicles.length ? h('div', { class: 'task-sub mono' }, t.vehicles.map(v => v.plate).join(' · ')) : null,
          t.distance_km != null ? line('Yol', km(t.distance_km)) : null),
        h('td', null, h('b', null, `${t.logs_ready}/${t.flights.length}`), h('div', { class: 'task-sub' }, 'hazır rapor')),
        h('td', { class: 'muted' }, fmtDateTime(t.created_at)))))))
      : h('div', { class: 'card empty' }, 'Filtreye uyan görev yok'));
  };
  const period = periodFilter('fieldTasks', () => load(), { title: 'Açık görevler her zaman; bitenler seçilen dönemde' });
  const load = async () => {
    [tasks, available] = await Promise.all([api.get(`/api/field/tasks?${period.qs()}`),
      manager ? api.get('/api/field/available-aircraft').then(a => a.length).catch(() => null) : null]);
    draw();
  };
  q.addEventListener('input', draw);
  [status, driver, place, mineOnly].forEach(el => el.addEventListener('change', draw));
  clear(view,
    pageHead('Saha Yönetimi', { back: '#/', tabs: fieldViewSwitch('tasks') }),
    stats,
    h('div', { class: 'filters' }, q, status, driver, place, period.el, h('label', { class: 'check' }, mineOnly, 'Sadece benim görevlerim'),
      h('span', { class: 'spacer' }),
      h('a', { class: 'btn', href: '#/field/places' }, 'Görev Yerleri ve Araçlar'),
      manager ? h('button', { class: 'btn primary', onclick: () => newTask(ctx, load) }, svgIcon(icons.plus), 'Yeni Saha Görevi') : null),
    body);
  await load();
  every(30000, () => load().catch(() => {}));
}

// ---------- Görünüm seçici: Saha Görevi (görev listesi) | Uçuş Yönetimi (görevlerdeki uçaklar)
const fieldViewSwitch = current => segmented([['tasks', 'Saha Görevi'], ['flights', 'Uçuş Yönetimi']], current, v => {
  setPref('field.view', v);
  location.hash = v === 'flights' ? '#/field/flights' : '#/field';
  if (v === 'tasks') window.dispatchEvent(new HashChangeEvent('hashchange'));
}, { tabs: true });

// ---------- Uçuş Yönetimi: saha görevlerine eklenmiş uçaklar; tıklayınca uçuş detayı
async function renderFlightsList(view, ctx) {
  let mode = pref('field.flights', 'ready');
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Uçak, görev, yer, pilot ara…', style: { width: '240px' } });
  const stats = statStrip();
  const body = h('div');
  let rows = [];
  const draw = () => {
    const list = rows.filter(f => matches(q.value, f.queue_no, f.order_code, f.product_name, f.task_code, f.location_name, f.pilot_name));
    stats.set([
      { label: mode === 'ready' ? 'Uçuşa hazır uçak' : mode === 'flown' ? 'Uçmuş uçak' : 'Görevlerdeki uçak', value: rows.length },
      { label: 'Raporu hazır', value: rows.filter(f => f.log_status === 'TAMAM').length, tone: 'ok' },
      { label: 'Hurda (uçtu)', value: rows.filter(f => f.order_status === 'HURDA').length },
      { label: 'Uçuş notu', value: rows.reduce((a, f) => a + f.note_count, 0) },
    ]);
    clear(body, list.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Uçak', 'Ürün', 'Saha görevi', 'Görev yeri / pilot', 'Uçuş logu', 'Havada', 'Not / medya'].map(c => h('th', null, c)))),
      h('tbody', null, list.map(f => h('tr', { class: 'click', onclick: () => { location.hash = `#/field/flight/${f.id}`; } },
        h('td', null, f.queue_no ? queuePlate(f.queue_no) : h('b', { class: 'mono' }, f.order_code), h('div', { class: 'small muted' }, f.order_code),
          f.order_status !== 'TAMAMLANDI' ? badge(ORDER_STATES, f.order_status) : null),
        h('td', null, f.product_name || '—', h('div', null, h('span', { class: `badge ${USAGE_TYPES[f.usage_type]?.badge || 'gray'}` },
          USAGE_TYPES[f.usage_type]?.label || '—'))),
        h('td', null, h('b', null, f.task_code), h('div', null, badge(TASK_STATES, f.task_status))),
        h('td', null, f.location_name || '—', h('div', { class: 'small muted' }, f.pilot_name || '')),
        h('td', null, f.log_status ? logBadge(f.log_status) : h('span', { class: 'muted' }, 'Yüklenmedi')),
        h('td', null, f.flight_s != null ? clock(f.flight_s) : '—'),
        h('td', { class: 'small' }, `${f.note_count} not · ${f.media_count} dosya`))))))
      : h('div', { class: 'card empty' }, mode === 'ready' ? 'Uçuşa hazır uçak yok. Saha görevine eklenen, montajı bitmiş uçaklar burada görünür.'
        : 'Kayıt yok'));
  };
  const period = periodFilter('fieldFlights', () => load(), { title: 'Uçmuş / tüm uçaklarda görevin başladığı dönem' });
  const load = async () => { period.el.hidden = mode === 'ready'; rows = await api.get(`/api/field/flights?view=${mode}&${period.qs()}`); draw(); };
  const modeSeg = selectInput([['ready', 'Uçuşa hazır'], ['flown', 'Uçmuş'], ['all', 'Tüm uçaklar']], { all: null, value: mode });
  modeSeg.addEventListener('change', () => { mode = modeSeg.value; setPref('field.flights', mode); load().catch(toastError); });
  q.addEventListener('input', draw);
  clear(view,
    pageHead('Saha Yönetimi', { back: '#/', sub: 'Uçuş Yönetimi: saha görevlerine eklenmiş uçaklar', tabs: fieldViewSwitch('flights') }),
    stats,
    h('div', { class: 'filters' }, modeSeg, q, period.el),
    body);
  await load();
  every(30000, () => load().catch(() => {}));
}

// ---------- Yeni görev ----------
async function newTask(ctx, done) {
  const role = r => api.get(`/api/people?role=${encodeURIComponent(r)}`);
  const [aircraft, leads, admins, drivers, staff, locations, pilots] = await Promise.all([
    api.get('/api/field/available-aircraft'), role('Saha Sorumlusu'), role('Sistem Yöneticisi'), role('Şoför'),
    role('Saha Personeli'), api.get('/api/field/locations'), role('Pilot'),
  ]);
  const leadList = [...new Map([...leads, ...admins].map(u => [u.id, u])).values()];
  const picked = new Set();
  const planes = h('div', { class: 'pick-list', style: { maxHeight: '220px' } }, aircraft.length ? aircraft.map(a => {
    const cb = h('input', { type: 'checkbox' });
    const el = h('label', { class: 'pick' }, cb, h('div', { class: 'grow' }, a.queue_no ? queuePlate(a.queue_no) : h('b', { class: 'mono' }, a.code),
      h('span', { class: 'small muted' }, [a.queue_no ? a.code : null, a.product_name, a.note].filter(Boolean).join(' · '))),
      h('span', { class: `badge ${USAGE_TYPES[a.usage_type]?.badge || 'gray'}`,
        title: a.usage_type === 'TEK' ? 'Uçtuktan sonra hurdaya ayrılır, yeniden sahaya gidemez' : 'Görev bittikten sonra yeniden sahaya gidebilir' },
        USAGE_TYPES[a.usage_type]?.label || a.usage_type),
      a.past_tasks ? h('span', { class: 'badge blue', title: 'Daha önce saha görevine gitti (uçmadı ya da çoklu kullanım)' }, `${a.past_tasks} görev yaptı`) : null,
      a.status === 'MONTAJ' ? h('span', { class: 'badge yellow', title: 'Montajı sahada tamamlanacak' }, 'Montajda')
        : h('span', { class: 'badge green' }, 'Saha deposu'));
    cb.addEventListener('change', () => { cb.checked ? picked.add(a.id) : picked.delete(a.id); el.classList.toggle('on', cb.checked); });
    return el;
  }) : h('div', { class: 'empty small' }, 'Saha deposunda ya da montajda göreve götürülebilecek uçak yok (tek kullanımlık uçaklar uçtuktan sonra hurdaya ayrılır)'));
  const lead = h('select', { class: 'input' }, leadList.map(u => h('option', { value: u.id, selected: u.id === ctx.user.id }, u.full_name)));
  const pilot = h('select', { class: 'input' }, h('option', { value: '' }, pilots.length ? 'Pilot seçin' : 'Pilot rolünde kullanıcı yok'),
    pilots.map(p => h('option', { value: p.id }, p.full_name)));
  const place = h('select', { class: 'input' }, h('option', { value: '' }, 'Sonra seçilecek'),
    locations.filter(l => l.active).map(l => h('option', { value: l.id }, l.name)));
  const person = h('select', { class: 'input' });
  const chosen = new Map();
  const chips = h('div', { class: 'chips', style: { justifyContent: 'flex-start', marginTop: '8px' } });
  const note = h('textarea', { class: 'input', rows: 2, placeholder: 'İsteğe bağlı' });
  const drawStaff = () => {
    clear(person, h('option', { value: '' }, 'Personel seçin'),
      staff.filter(s => !chosen.has(s.id)).map(s => h('option', { value: s.id }, nameWithIntern(s))));
    clear(chips, chosen.size ? [...chosen.values()].map(s => h('span', { class: `chip x ${s.intern ? 'intern' : ''}` }, s.full_name, internTag(s),
      h('button', { type: 'button', 'aria-label': 'Çıkar', onclick: () => { chosen.delete(s.id); drawStaff(); } }, '×')))
      : h('span', { class: 'small muted' }, 'Henüz personel eklenmedi'));
  };
  drawStaff();
  modal({
    title: 'Yeni Saha Görevi',
    wide: true,
    body: h('div', null,
      field('Götürülecek uçaklar (saha deposu ve montajdakiler)', planes, 'Her uçak görevde bir uçuş olarak listelenir. Montajdaki uçağın montajı sahada Üretim ekranından sürdürülür.'),
      h('div', { class: 'row' }, field('Saha sorumlusu', lead), field('Pilot', pilot)),
      h('div', { class: 'small muted', style: { marginTop: '-6px', marginBottom: '10px' } },
        'Araçlar ve şoförleri görev oluşturulduktan sonra görevin Yol Yönetimi bölümünden eklenir (birden fazla olabilir).'),
      field('Saha personeli', h('div', null,
        h('div', { style: { display: 'flex', gap: '8px' } }, person,
          h('button', { class: 'btn', type: 'button', onclick: () => {
            const s = staff.find(x => x.id === Number(person.value));
            if (s) { chosen.set(s.id, s); drawStaff(); }
          } }, 'Ekle')),
        chips)),
      h('div', { class: 'row' }, field('Görev yeri', place), field('Not', note))),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Görevi Oluştur', class: 'primary', onClick: async () => {
          if (!picked.size) throw new Error('En az bir uçak seçin');
          if (!lead.value) throw new Error('Saha sorumlusu seçin');
          if (!pilot.value) throw new Error('Pilot seçin');
          if (!chosen.size) throw new Error('En az bir saha personeli ekleyin');
          const { id, code } = await api.post('/api/field/tasks', {
            order_ids: [...picked], lead_id: Number(lead.value), pilot_id: Number(pilot.value),
            staff_ids: [...chosen.keys()], location_id: place.value ? Number(place.value) : null, note: note.value.trim() || null,
          });
          toast(`${code} görev kodu ile oluşturuldu`);
          done?.();
          location.hash = `#/field/task/${id}`;
        },
      },
    ],
  });
}

// ---------- Görev detayı ----------
async function renderTask(view, id, ctx) {
  let tab = pref('field.tab', 'flights');
  const head = h('div');
  // Yerleşim: üstte görev bilgileri (katlanabilir), altında alt modül sekmeleri, en altta seçili alt modül
  const TABS = [['flights', 'Uçuş Yönetimi'], ['expenses', 'Masraf Yönetimi'], ['road', 'Yol Yönetimi'], ['equipment', 'Ekipman Listesi'], ['isg', 'İSG Kontrol']];
  // Sekme çubuğu: solda alt modüller, en sağda seçili alt modülün işlemleri (Ekle vb.; formlar açılır pencerede)
  const tabList = h('div', { class: 'tabbar', role: 'tablist' });
  const tabActs = h('div', { class: 'task-tab-acts' });
  const tabSeg = h('div', { class: 'task-tabs' }, tabList, h('span', { class: 'spacer' }), tabActs);
  const setTabActions = (...nodes) => clear(tabActs, nodes.flat().filter(Boolean));
  const drawTabs = () => clear(tabList, TABS.map(([k, l]) => h('button', { class: `tab ${k === tab ? 'on' : ''}`, type: 'button', role: 'tab',
    'aria-selected': k === tab ? 'true' : 'false', onclick: () => { tab = k; setPref('field.tab', k); drawTabs(); drawTab(); } }, segIcon(l), l)));
  drawTabs();
  const stats = statStrip();
  let infoOpen = pref('field.infoOpen', '1') === '1';
  const info = h('div', { class: 'card task-info' });
  const body = h('div');
  let t;

  const load = async () => {
    t = await api.get(`/api/field/tasks/${id}`);
    drawHead();
    await drawTab();
  };

  function drawHead() {
    const c = t.can;
    // Başlığın en sağında iki birleşik düğme grubu: görev durumu · belgeler (sade, tek renk; vurgu yalnız ikon renginde)
    const actions = [];
    const ico = (d, tone) => { const e = svgIcon(`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`); if (tone) e.classList.add(tone); return e; };
    const I = {
      play: '<path d="M7 5l12 7-12 7z"/>', stop: '<path d="M6 6l12 12M18 6L6 18"/>',
      ok: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', fail: '<path d="M6 6l12 12M18 6L6 18"/>',
      form: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
      print: '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
    };
    if (c.manage && t.status === 'BASLANGIC') {
      actions.push(h('div', { class: 'btn-join', role: 'group', 'aria-label': 'Görev durumu' },
        h('button', { class: 'btn', type: 'button', onclick: cancel }, ico(I.stop, 'ic-bad'), 'İptal Et'),
        h('button', { class: 'btn', type: 'button', onclick: start }, ico(I.play, 'ic-pri'), 'Görevi Başlat')));
    } else if (c.manage && t.status === 'GOREVDE') {
      actions.push(h('div', { class: 'btn-join', role: 'group', 'aria-label': 'Görevi tamamla' },
        h('button', { class: 'btn', type: 'button', title: 'Görevi başarılı olarak tamamla', onclick: () => finish(true) }, ico(I.ok, 'ic-ok'), 'Başarılı'),
        h('button', { class: 'btn', type: 'button', title: 'Görevi başarısız olarak tamamla', onclick: () => finish(false) }, ico(I.fail, 'ic-bad'), 'Başarısız')));
    }
    const formBtn = h('button', { class: 'btn', type: 'button', title: 'Boş / doldurulacak görev formu', onclick: () => printTaskForm(t, ctx.meta.company) }, ico(I.form), 'Görev Formu');
    const repBtn = h('button', { class: 'btn', type: 'button', title: 'Adım adım yapılan işlemler, görev tanımları, İSG, ekipman, imza ve uçuş raporları — tek belgede' }, ico(I.print), 'Görev Raporu');
    repBtn.addEventListener('click', async () => {
      repBtn.disabled = true;
      try { printTaskReport(await api.get(`/api/field/tasks/${id}/report`), ctx.meta.company); }
      catch (err) { toastError(err); } finally { repBtn.disabled = false; }
    });
    actions.push(h('div', { class: 'btn-join', role: 'group', 'aria-label': 'Belgeler' }, formBtn, repBtn));
    clear(head, pageHead(`Saha görevi ${t.code}`, {
      back: '#/field',
      sub: h('span', null, badge(TASK_STATES, t.status), '  ', `Saha sorumlusu: ${t.lead_name || '—'}`),
    }), moduleToolbar(actions));
    stats.set([
      { label: 'Uçuş', value: t.flights.length },
      { label: 'Raporu hazır uçuş', value: `${t.logs_ready}/${t.flights.length}`, tone: t.logs_ready === t.flights.length && t.flights.length ? 'ok' : '' },
      { label: 'Toplam masraf', value: tl(t.expense_total), sub: `${t.expense_count} kalem` },
      { label: 'Gidilen yol', value: km(t.distance_km), sub: t.vehicle_plate || 'plaka girilmedi' },
      { label: 'Görev süresi', value: t.started_at ? fmtDuration(t.duration_seconds) : '—' },
      { label: 'Toplam havada', value: clock(t.flights.reduce((a, f) => a + (f.flight_s || 0), 0)), sub: 'hazır raporlardan' },
    ]);
    const plates = t.flights.length ? h('span', { class: 'task-plates' }, t.flights.map(f => f.queue_no ? queuePlate(f.queue_no) : h('span', { class: 'mono' }, f.order_code))) : '—';
    const kv = (k, v) => h('div', { class: 'task-kv' }, h('span', null, k), h('b', null, v || '—'));
    const toggle = h('button', { class: 'task-toggle', type: 'button', title: infoOpen ? 'Bilgileri gizle' : 'Bilgileri göster' }, infoOpen ? '▴' : '▾');
    const summary = h('div', { class: 'task-sum', onclick: () => { infoOpen = !infoOpen; setPref('field.infoOpen', infoOpen ? '1' : '0'); drawHead(); } },
      h('b', null, 'Görev Bilgileri'), badge(TASK_STATES, t.status),
      t.result ? h('span', { class: `badge ${t.result === 'BASARILI' ? 'green' : 'red'}` }, t.result === 'BASARILI' ? 'Başarılı' : 'Başarısız') : null,
      h('span', { class: 'task-sum-txt' }, [t.lead_name, t.pilot_name, t.location_name].filter(Boolean).join(' · ')),
      infoOpen ? null : plates, h('span', { class: 'spacer' }), toggle);
    clear(info, summary, infoOpen ? h('div', { class: 'task-info-body' },
      stats,
      h('div', { class: 'task-kv-grid' },
        kv('Saha sorumlusu', t.lead_name), kv('Pilot', t.pilot_name), kv('Şoför', driversOf(t)),
        kv('Personel', t.staff.map(s => s.full_name).join(', ')), kv('Görev yeri', t.location_name), kv('Araç plakası', t.vehicle_plate),
        kv('Oluşturan', `${t.created_by_name || '—'} · ${fmtDateTime(t.created_at)}`),
        kv('Başlama / bitiş', t.started_at ? `${fmtDateTime(t.started_at)} – ${t.finished_at ? fmtDateTime(t.finished_at) : 'devam ediyor'}` : 'Başlamadı'),
        h('div', { class: 'task-kv wide' }, h('span', null, 'Uçaklar'), plates),
        t.note ? h('div', { class: 'task-kv wide' }, h('span', null, 'Not'), h('b', null, t.note)) : null)) : null);
  }

  function drawTab() {
    setTabActions();
    if (tab === 'expenses') return drawExpenses();
    if (tab === 'road') return drawRoad();
    if (tab === 'equipment') return drawEquipment();
    if (tab === 'isg') return drawIsg();
    return drawFlights();
  }

  // Uçuş Yönetimi
  function drawFlights() {
    clear(body, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Uçak', 'Ürün', 'Fırlatma sistemi', 'Uçuş logu', 'Havada', 'Video', ''].map(c => h('th', null, c)))),
      h('tbody', null, t.flights.map(f => h('tr', { class: 'click', title: IN_ASSEMBLY.includes(f.order_status)
        ? 'Uçak sahada montajda: montaj detayına git' : 'Uçuş detayına git', onclick: e => { if (!e.target.closest('a,button')) openAircraft(f); } },
        h('td', null, queuePlate(f.queue_no) || '—', h('div', { class: 'small muted' }, f.order_code),
          IN_ASSEMBLY.includes(f.order_status) ? h('span', { class: 'badge yellow', style: { marginTop: '3px' } }, 'Sahada montaj') : null),
        h('td', null, f.product_name || '—', h('div', { class: 'small muted mono' }, f.product_serial || '')),
        h('td', null, f.launch ? h('span', { class: `badge ${f.launch === 'RAMPA' ? 'purple' : 'blue'}` }, LAUNCH[f.launch]) : h('span', { class: 'muted' }, 'Seçilmedi')),
        h('td', null, f.log_status ? logBadge(f.log_status) : h('span', { class: 'muted' }, 'Yüklenmedi'),
          f.log_file ? h('div', { class: 'small muted' }, f.log_file) : null,
          f.log_error ? h('div', { class: 'small', style: { color: 'var(--danger)', whiteSpace: 'normal' } }, f.log_error) : null),
        h('td', null, f.flight_s != null ? clock(f.flight_s) : '—'),
        h('td', null, f.videos.length ? h('span', { class: 'badge blue' }, `${f.videos.length} video`) : h('span', { class: 'muted' }, '—')),
        h('td', { class: 'num' },
          f.log_status === 'TAMAM' ? h('a', { class: 'btn sm', href: `#/field/report/${f.log_id}` }, 'Uçuş Raporu') : null,
          t.can.flights ? h('button', { class: 'btn sm primary', onclick: () => flightModal(f) }, 'Düzenle') : null))))),
      h('p', { class: 'small muted', style: { margin: '8px 2px 0' } },
        'Uçağa tıklayınca uçuş detayı açılır (rapor, 3B izleme, notlar, video ve resimler); sahada montajdaki uçak montaj detayına gider. "Düzenle" ile fırlatma sistemi ve log. Görev bittiğinde tüm uçuşların raporu hazırsa görev "Rapor Tamamlandı" olur.')));
  }

  // Uçağa tıklayınca: montajı bitmemişse (sahada montaj) üretim detayına, bitmişse uçuş detayına
  function openAircraft(f) {
    if (IN_ASSEMBLY.includes(f.order_status)) {
      if (!ctx.user.modules.includes('production')) {
        toast('Uçak sahada montaj aşamasında; montaj Üretim Yönetimi\'nden tamamlanır');
        return;
      }
      location.hash = `#/production/${f.order_id}`;
      return;
    }
    location.hash = `#/field/flight/${f.id}`;
  }

  function flightModal(f) {
    const can = t.can.flights;
    let launch = f.launch || '';
    const choice = h('div', { class: 'seg' }, Object.entries(LAUNCH).map(([k, label]) => {
      const b = h('button', { type: 'button', class: k === launch ? 'on' : '', disabled: !can }, label);
      b.addEventListener('click', () => { launch = k; choice.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); });
      return b;
    }));
    const note = h('textarea', { class: 'input', rows: 2, disabled: !can }, f.note || '');
    const file = h('input', { class: 'input', type: 'file', accept: '.bin,.BIN,.log,.LOG', style: { height: 'auto', padding: '6px' } });
    const progress = uploadPanel();
    const remote = ctx.meta.remote;   // internetten bağlanıldı: video/log yalnızca yerel ağdan yüklenir
    const canUpload = can && !['BASLANGIC', 'IPTAL'].includes(t.status) && f.log_status !== 'ISLENIYOR';
    const canVideo = can && !['BASLANGIC', 'IPTAL'].includes(t.status);
    const videoInput = h('input', { class: 'input', type: 'file', accept: 'video/*', multiple: true, style: { height: 'auto', padding: '6px' } });
    const videoProgress = uploadPanel();
    const videoList = h('div', { class: 'video-list' }, f.videos.length ? f.videos.map(v => h('div', { class: 'video-item' },
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => playVideo(v) }, '▶ İzle'),
      h('div', { class: 'grow' }, h('b', null, v.file_name),
        h('div', { class: 'small muted' }, `${(v.size / 1048576).toFixed(1)} MB · ${v.uploaded_by_name || ''} · ${fmtDateTime(v.uploaded_at)}`)),
      (t.can.manage || v.uploaded_by === ctx.user.id) ? h('button', { class: 'btn sm ghost', type: 'button', onclick: async () => {
        if (!await confirmDialog('Videoyu sil', `${v.file_name} silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
        try { await api.del(`/api/field/videos/${v.id}`); toast('Video silindi'); await load(); } catch (err) { toastError(err); }
      } }, 'Sil') : null)) : h('div', { class: 'small muted' }, 'Henüz video yüklenmedi'));
    modal({
      title: `Uçuş — ${f.queue_no || f.order_code}`,
      onClose: () => { progress.abort(); videoProgress.abort(); },   // pencere kapanırsa süren yükleme iptal edilir
      body: h('div', null,
        field('Fırlatma sistemi', choice),
        field('Uçuş notu', note),
        field('Uçuş logu', h('div', null,
          f.log_status ? h('div', { style: { marginBottom: '8px' } }, logBadge(f.log_status), ' ', h('span', { class: 'small muted' }, f.log_file || ''),
            f.log_status === 'TAMAM' ? [' · ', h('a', { href: `#/field/report/${f.log_id}` }, 'Raporu aç')] : null) : null,
          canUpload ? (remote ? localUploadNotice(ctx.meta, 'Uçuş logu') : [file, progress]) : h('div', { class: 'small muted' },
            t.status === 'BASLANGIC' ? 'Log, görev başladıktan sonra yüklenebilir.' : f.log_status === 'ISLENIYOR' ? 'Log analiz ediliyor…' : 'Log yükleme yetkiniz yok.')),
        canUpload ? 'Yeni log yüklerseniz bu uçuşun raporu yeniden oluşturulur. En fazla 2 GB.' : null),
        field(`Uçuş videoları (${f.videos.length})`, h('div', null, videoList,
          canVideo ? h('div', { style: { marginTop: '8px' } }, remote ? localUploadNotice(ctx.meta, 'Uçuş videosu') : [videoInput, videoProgress]) : null),
          canVideo ? 'Birden fazla video seçebilirsiniz; boyut sınırı yoktur, büyük dosyalar parça parça yüklenir.' : null)),
      actions: can ? [
        { label: 'Vazgeç' },
        {
          label: 'Kaydet', class: 'primary', onClick: async () => {
            await api.put(`/api/field/flights/${f.id}`, { launch: launch || null, note: note.value.trim() || null });
            const vids = remote ? [] : [...(videoInput.files || [])];
            try {
              if (vids.length) {
                const signal = videoProgress.start();
                for (const [i, v] of vids.entries()) {
                  await uploadChunked(v, `/api/field/flights/${f.id}/videos`,
                    pct => videoProgress.set(`${v.name} (${i + 1}/${vids.length}) yükleniyor…`, pct), signal);
                }
                videoProgress.done();
                toast(`${vids.length} video yüklendi`);
              }
              if (!remote && file.files?.[0]) {
                const signal = progress.start();
                const uploadId = await uploadLarge(file.files[0], 'flightlogs', pct => progress.set(`${file.files[0].name} yükleniyor…`, pct), signal);
                progress.done();
                await api.post(`/api/field/flights/${f.id}/flight-log/chunked`, { upload_id: uploadId });
                toast('Log yüklendi, analiz ediliyor');
              } else if (!vids.length) {
                toast('Uçuş bilgisi kaydedildi');
              }
            } catch (err) {
              progress.done();
              videoProgress.done();
              if (!err.canceled) throw err;
              toast('Yükleme iptal edildi');
              await load();
              return true;   // pencere açık kalır; yeniden dosya seçilebilir
            }
            await load();
          },
        },
      ] : [{ label: 'Kapat' }],
    });
  }

  function playVideo(v) {
    const player = h('video', { src: fileUrl(v.file), controls: true, autoplay: true, playsinline: true, preload: 'metadata', class: 'video-player' });
    modal({
      title: v.file_name, wide: true, onClose: () => { player.pause(); player.removeAttribute('src'); player.load(); },
      body: h('div', null, player,
        h('div', { class: 'small muted', style: { marginTop: '6px' } },
          'Oynatılamıyorsa (ör. iPhone HEVC .mov) ', h('a', { href: fileUrl(v.file), download: v.file_name }, 'dosyayı indirin'), '.')),
      actions: [{ label: 'Kapat', class: 'primary' }],
    });
  }

  // Masraf Yönetimi
  async function drawExpenses() {
    const [meta, people] = await Promise.all([api.get('/api/field/meta'), api.get('/api/people')]);
    if (tab !== 'expenses') return;   // beklerken başka sekmeye geçildi
    const spender = h('select', { class: 'input' }, people.map(p => h('option', { value: p.id, selected: p.id === ctx.user.id }, p.full_name)));
    const date = h('input', { class: 'input', type: 'date', value: new Date().toISOString().slice(0, 10) });
    const cat = h('select', { class: 'input' }, meta.expense_categories.map(c => h('option', { value: c }, c)));
    const amount = h('input', { class: 'input', type: 'number', min: '0', step: '0.01', placeholder: '0,00' });
    const desc = h('input', { class: 'input', placeholder: 'Açıklama' });
    const receipt = h('input', { class: 'input', type: 'file', accept: 'image/*,.pdf', style: { height: 'auto', padding: '6px' } });
    const addModal = () => modal({
      title: 'Masraf Ekle',
      body: h('div', null,
        h('div', { class: 'row' }, field('Tarih', date), field('Tutar (₺)', amount)),
        h('div', { class: 'row' }, field('Masrafı yapan', spender), field('Kategori', cat)),
        field('Açıklama', desc), field('Fiş / fatura (isteğe bağlı)', receipt)),
      actions: [{ label: 'Vazgeç' }, { label: 'Masraf Ekle', class: 'primary', onClick: async () => {
        if (!(Number(amount.value) > 0)) throw new Error('Tutar girin');
        const fd = new FormData();
        fd.append('spent_on', date.value);
        fd.append('category', cat.value);
        fd.append('amount', amount.value);
        fd.append('description', desc.value.trim());
        if (spender.value) fd.append('spent_by', spender.value);
        if (receipt.files[0]) fd.append('receipt', receipt.files[0]);
        await api.post(`/api/field/tasks/${id}/expenses`, fd);
        toast('Masraf eklendi');
        await load();
      } }],
    });
    if (t.can.expenses) setTabActions(h('button', { class: 'btn primary', type: 'button', onclick: addModal }, svgIcon(icons.plus), 'Masraf Ekle'));
    const byCat = {};
    const byPerson = {};
    t.expenses.forEach(e => {
      byCat[e.category] = (byCat[e.category] || 0) + e.amount;
      const who = e.spent_by_name || e.created_by_name || '—';
      byPerson[who] = (byPerson[who] || 0) + e.amount;
    });
    clear(body,
      Object.keys(byCat).length ? h('div', { class: 'chips', style: { justifyContent: 'flex-start', margin: '0 0 10px' } },
        Object.entries(byCat).map(([k, v]) => h('span', { class: 'chip' }, `${k}: ${tl(v)}`)),
        h('span', { class: 'chip', style: { fontWeight: 700 } }, `Toplam: ${tl(t.expense_total)}`)) : null,
      Object.keys(byPerson).length > 1 ? h('div', { class: 'chips', style: { justifyContent: 'flex-start', margin: '0 0 10px' } },
        Object.entries(byPerson).map(([k, v]) => h('span', { class: 'chip' }, `${k}: ${tl(v)}`))) : null,
      t.expenses.length ? h('div', { class: 'table-wrap' }, h('table', null,
        h('thead', null, h('tr', null, ['Tarih', 'Masrafı yapan', 'Kategori', 'Açıklama', 'Tutar', 'Fiş', 'Giren', ''].map(c => h('th', { class: c === 'Tutar' ? 'num' : '' }, c)))),
        h('tbody', null, t.expenses.map(e => h('tr', null,
          h('td', null, fmtDate(e.spent_on)),
          h('td', null, h('b', null, e.spent_by_name || e.created_by_name || '—')),
          h('td', null, e.category),
          h('td', { style: { whiteSpace: 'normal' } }, e.description || '—'),
          h('td', { class: 'num' }, h('b', null, tl(e.amount))),
          h('td', null, e.receipt ? h('a', { href: `/api/files/${e.receipt}`, target: '_blank' }, 'Görüntüle') : '—'),
          h('td', { class: 'muted' }, e.created_by_name || '—'),
          h('td', { class: 'num' }, (t.can.manage || e.created_by === ctx.user.id)
            ? h('button', { class: 'btn sm ghost', onclick: async () => {
              if (!await confirmDialog('Masrafı sil', `${e.category} · ${tl(e.amount)} silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
              try { await api.del(`/api/field/expenses/${e.id}`); toast('Silindi'); await load(); } catch (err) { toastError(err); }
            } }, 'Sil') : null))))))
        : h('div', { class: 'card empty' }, 'Bu görev için masraf girilmedi'));
  }

  // Yol Yönetimi: görev yeri + göreve giden araçlar (her aracın şoförü ve km'leri ayrı)
  // İSG Kontrol: görevdeki her kişinin KKD maddeleri için saha sorumlusunun Yaptı / Yapmadı işareti (raporda da görünür)
  async function drawIsg() {
    let list;
    try { list = await api.get(`/api/field/tasks/${id}/isg`); } catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    const can = t.can.isg;
    const set = async (p, item, status) => {
      try { list = await api.put(`/api/field/tasks/${id}/isg`, { user_id: p.user_id, item: item.name, status, note: item.note || '' }); render(); }
      catch (err) { toastError(err); }
    };
    const render = () => {
      const total = list.reduce((a, p) => a + p.ppe.length, 0), done = list.reduce((a, p) => a + p.ppe.filter(x => x.status).length, 0);
      clear(body, h('div', { class: 'isgc' },
        h('div', { class: 'card card-pad isgc-head' }, h('b', null, `İSG Kontrolü · ${done}/${total} madde işaretlendi`),
          h('span', { class: 'small muted' }, can ? 'Her kişinin KKD maddeleri için sahada “Yaptı” ya da “Yapmadı” işaretleyin. Görev raporunda görünür.'
            : 'İşaretlemeyi saha sorumlusu yapar.')),
        list.map(p => h('section', { class: 'card card-pad isgc-person' },
          h('div', { class: 'isgc-ph' }, h('b', null, p.name), h('span', { class: 'small muted' }, p.roles.join(', ')),
            p.position ? h('span', { class: 'badge blue' }, p.position) : null),
          p.emergency ? h('div', { class: 'isgc-em' }, h('b', null, 'Acil durum görevi: '), p.emergency) : null,
          p.trainings_expired.length || p.trainings_missing.length ? h('div', { class: 'isgc-warn' },
            p.trainings_expired.length ? `Süresi dolan eğitim: ${p.trainings_expired.join(', ')}. ` : '',
            p.trainings_missing.length ? `Alındığı tarihi girilmemiş eğitim: ${p.trainings_missing.length}` : '') : null,
          p.ppe.length ? h('table', { class: 'table isgc-table' },
            h('thead', null, h('tr', null, ['KKD', 'Kullanım yeri / zamanı', 'Durum'].map(c => h('th', null, c)))),
            h('tbody', null, p.ppe.map(x => h('tr', { class: x.status === 'YAPMADI' ? 'no' : x.status === 'YAPTI' ? 'yes' : '' },
              h('td', null, x.name), h('td', { class: 'small' }, x.usage || ''),
              h('td', { class: 'nowrap' },
                h('button', { class: `isgc-btn yes ${x.status === 'YAPTI' ? 'on' : ''}`, type: 'button', disabled: !can, onclick: () => set(p, x, x.status === 'YAPTI' ? null : 'YAPTI') }, '✓ Yaptı'),
                h('button', { class: `isgc-btn no ${x.status === 'YAPMADI' ? 'on' : ''}`, type: 'button', disabled: !can, onclick: () => set(p, x, x.status === 'YAPMADI' ? null : 'YAPMADI') }, '✗ Yapmadı'),
                x.checked_by_name ? h('div', { class: 'small muted' }, `${x.checked_by_name} · ${fmtDateTime(x.checked_at)}`) : null)))))
            : h('div', { class: 'small muted' }, 'Bu kişi için İK’da KKD tanımlı değil (İK › personel › İSG › KKD).')))));
    };
    render();
  }

  // Ekipman Listesi: Modül Ayarları'ndaki standart liste göreve kopyalanır; saha yöneticisi göreve özel çıkarır / ekler / miktar girer
  function drawEquipment() {
    const can = t.can.manage;
    const list = t.equipment || [];
    const fmtQ = v => Number(v).toLocaleString('tr-TR', { maximumFractionDigits: 2 });
    const save = async (e, patch) => {
      try { t.equipment = await api.put(`/api/field/tasks/${id}/equipment/${e.id}`, patch); drawEquipment(); } catch (err) { toastError(err); }
    };
    const rows = list.map((e, i) => {
      const q = h('input', { class: 'input eq-qty', type: 'number', min: '0', step: 'any', value: e.qty, disabled: !can });
      q.addEventListener('change', () => save(e, { qty: Number(q.value) || 0 }));
      return h('tr', null,
        h('td', { class: 'num muted' }, i + 1),
        h('td', null, h('b', null, e.name), e.product_code ? h('span', { class: 'eq-code', style: { marginLeft: '6px' } }, e.product_code) : null, e.std_id ? null : h('span', { class: 'badge blue', style: { marginLeft: '6px' } }, 'göreve özel'),
          e.note ? h('div', { class: 'small muted' }, e.note) : null),
        h('td', { class: 'nowrap' }, can ? q : fmtQ(e.qty), ' ', h('span', { class: 'muted' }, e.unit || '')),
        h('td', { class: 'num' }, can ? h('button', { class: 'btn sm danger', title: 'Bu görevden çıkar', onclick: async () => {
          try { t.equipment = await api.del(`/api/field/tasks/${id}/equipment/${e.id}`); drawEquipment(); } catch (err) { toastError(err); }
        } }, 'Çıkar') : null));
    });
    let chosen = null;
    const unit0 = () => unit;
    const pick = stockPicker({ onPick: p => { chosen = p; if (p?.unit) unit0().value = p.unit; } });
    const qty = h('input', { class: 'input eq-qty', type: 'number', min: '0', step: 'any', value: '1' });
    const unit = h('input', { class: 'input eq-unit', placeholder: 'birim', value: 'adet' });
    const addModal = () => modal({
      title: 'Ekipman Ekle',
      body: h('div', null, field('Ekipman (stoktan)', pick.el), h('div', { class: 'row' }, field('Miktar', qty), field('Birim', unit)),
        h('p', { class: 'small muted' }, 'Stoktaki tüm ürünlerden aranır (en az 3 harf). Yalnızca bu göreve eklenir; standart liste Program Ayarları › Modül Ayarları’ndan değişir.')),
      actions: [{ label: 'Vazgeç' }, { label: 'Ekle', class: 'primary', onClick: async () => {
        if (!chosen) throw new Error('Ekipmanı stoktaki ürünlerden arayıp seçin');
        t.equipment = await api.post(`/api/field/tasks/${id}/equipment`, { product_id: chosen.id, qty: Number(qty.value) || 1, unit: unit.value.trim() });
        drawEquipment();
      } }],
    });
    if (can) setTabActions(h('div', { class: 'btn-join' },
      h('button', { class: 'btn', type: 'button', title: 'Görevdeki değişiklikleri silip standart listeyi yeniden yükle', onclick: async () => {
        if (!await confirmDialog('Standart listeye dön', 'Bu görevdeki ekipman değişiklikleri silinip standart liste yeniden yüklensin mi?', { okLabel: 'Standart listeyi yükle' })) return;
        try { t.equipment = await api.post(`/api/field/tasks/${id}/equipment/reset`, {}); drawEquipment(); } catch (err) { toastError(err); }
      } }, 'Standart Liste')),
      h('button', { class: 'btn primary', type: 'button', onclick: addModal }, svgIcon(icons.plus), 'Ekipman Ekle'));
    clear(body, h('div', { class: 'card card-pad' },
      h('div', { class: 'eq-head' }, h('div', null, h('b', null, `Ekipman Listesi (${list.length} kalem)`),
        h('div', { class: 'small muted' }, 'Program Ayarları › Modül Ayarları › Saha Yönetimi’ndeki standart liste her göreve otomatik eklenir. Bu görev için çıkarabilir, ekleyebilir ve miktarları değiştirebilirsiniz.'))),
      list.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'eq-table' },
        h('thead', null, h('tr', null, ['#', 'Ekipman', 'Miktar', ''].map(c => h('th', null, c)))), h('tbody', null, rows)))
        : h('div', { class: 'empty small' }, 'Bu görev için ekipman listesi boş.')));
  }

  async function drawRoad() {
    const [locations, vehicles, drivers] = await Promise.all([api.get('/api/field/locations'), api.get('/api/field/vehicles'),
      api.get(`/api/people?role=${encodeURIComponent('Şoför')}`)]);
    if (tab !== 'road') return;
    const can = t.can.road;
    const opt = (list, cur, label, text) => [h('option', { value: '' }, label),
      ...list.filter(x => x.active !== 0 || x.id === cur).map(x => h('option', { value: x.id, selected: x.id === cur }, text(x)))];
    const num = v => (v === '' ? null : Number(v));
    const kmInput = (value, disabled) => h('input', { class: 'input', type: 'number', min: '0', step: '1', value: value ?? '', disabled, style: { width: '120px' } });

    // Görev geneli: görev yeri ve not
    const place = h('select', { class: 'input', disabled: !can }, opt(locations, t.location_id, 'Görev yeri seçin', l => l.name));
    const note = h('input', { class: 'input', value: t.road_note || '', disabled: !can, placeholder: 'Güzergâh, açıklama…' });
    const saveTask = h('button', { class: 'btn primary', onclick: async () => {
      saveTask.disabled = true;
      try {
        await api.put(`/api/field/tasks/${id}/road`, { location_id: place.value ? Number(place.value) : null, road_note: note.value.trim() || null });
        toast('Görev yeri kaydedildi');
        await load();
      } catch (err) { toastError(err); } finally { saveTask.disabled = false; }
    } }, 'Kaydet');

    // Araç satırları
    const rows = t.vehicles.map(v => {
      const editable = can || t.can.road_own.includes(v.id);
      const drv = h('select', { class: 'input', disabled: !can }, opt(drivers, v.driver_id, 'Şoför seçin', d => d.full_name));
      const s0 = kmInput(v.start_km, !editable), s1 = kmInput(v.end_km, !editable);
      const dist = h('b', { class: 'road-dist' });
      const calc = () => {
        dist.textContent = s0.value !== '' && s1.value !== '' ? (Number(s1.value) >= Number(s0.value) ? km(Number(s1.value) - Number(s0.value)) : 'Hatalı') : '—';
      };
      [s0, s1].forEach(i => i.addEventListener('input', calc));
      calc();
      const save = h('button', { class: 'btn sm primary', onclick: async () => {
        try {
          await api.put(`/api/field/task-vehicles/${v.id}`, { driver_id: drv.value ? Number(drv.value) : null, start_km: num(s0.value), end_km: num(s1.value), note: v.note });
          toast(`${v.plate} kaydedildi`);
          await load();
        } catch (err) { toastError(err); }
      } }, 'Kaydet');
      const del = h('button', { class: 'btn sm danger', onclick: async () => {
        if (!await confirmDialog('Aracı çıkar', `${v.plate} bu görevden çıkarılsın mı?`, { okLabel: 'Çıkar', danger: true })) return;
        try { await api.del(`/api/field/task-vehicles/${v.id}`); toast('Araç çıkarıldı'); await load(); } catch (err) { toastError(err); }
      } }, 'Çıkar');
      return h('tr', null,
        h('td', null, h('b', { class: 'mono' }, v.plate), v.vehicle_description ? h('div', { class: 'small muted' }, v.vehicle_description) : null),
        h('td', null, drv), h('td', null, s0), h('td', null, s1), h('td', null, dist),
        h('td', { style: { whiteSpace: 'nowrap' } }, editable ? save : null, ' ', can ? del : null));
    });

    // Araç ekleme
    const used = new Set(t.vehicles.map(v => v.vehicle_id));
    const newPlate = h('select', { class: 'input' }, h('option', { value: '' }, 'Araç seçin'),
      vehicles.filter(v => v.active && !used.has(v.id)).map(v => h('option', { value: v.id }, `${v.plate}${v.description ? ` · ${v.description}` : ''}`)));
    const newDriver = h('select', { class: 'input' }, opt(drivers, t.driver_id, 'Şoför seçin', d => d.full_name));
    const newStart = kmInput('', false);
    newStart.placeholder = 'Başlangıç km';
    const addModal = () => modal({
      title: 'Göreve Araç Ekle',
      body: h('div', null, field('Araç', newPlate), field('Şoför', newDriver), field('Başlangıç km', newStart),
        h('p', { class: 'small muted' }, 'Bitiş km’sini görev dönüşünde şoför ya da saha yöneticisi girer. Listede olmayan araç için: ',
          h('a', { href: '#/field/places' }, 'görev yerlerini ve araçları yönet'), '.')),
      actions: [{ label: 'Vazgeç' }, { label: 'Araç Ekle', class: 'primary', onClick: async () => {
        if (!newPlate.value) throw new Error('Araç seçin');
        await api.post(`/api/field/tasks/${id}/vehicles`, { vehicle_id: Number(newPlate.value),
          driver_id: newDriver.value ? Number(newDriver.value) : null, start_km: num(newStart.value) });
        toast('Araç eklendi');
        await load();
      } }],
    });
    if (can) setTabActions(h('button', { class: 'btn primary', type: 'button', onclick: addModal }, svgIcon(icons.plus), 'Araç Ekle'));

    clear(body,
      h('div', { class: 'card card-pad', style: { marginBottom: '12px' } },
        h('div', { class: 'row' }, field('Görev yeri', place), field('Not', note)),
        can ? h('div', { style: { display: 'flex', justifyContent: 'flex-end' } }, saveTask) : null),
      h('div', { class: 'card card-pad' },
        h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px', flexWrap: 'wrap' } },
          h('h2', { style: { fontSize: '15px', margin: 0 } }, `Göreve giden araçlar (${t.vehicles.length})`),
          h('span', { style: { flex: 1 } }),
          h('span', null, 'Toplam gidilen yol: ', h('b', null, km(t.distance_km)))),
        t.vehicles.length ? h('div', { class: 'table-wrap' }, h('table', null,
          h('thead', null, h('tr', null, ['Araç', 'Şoför', 'Başlangıç km', 'Bitiş km', 'Gidilen yol', ''].map(c => h('th', null, c)))),
          h('tbody', null, rows))) : h('div', { class: 'empty small' }, 'Bu göreve henüz araç eklenmedi'),
        h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px', marginTop: '10px' } },
          h('a', { href: '#/field/places' }, 'Görev yerlerini ve araçları yönet'),
          h('span', { style: { flex: 1 } }),
          h('span', { class: 'small muted' }, can ? 'Her aracın km bilgisini kendi şoförü de girebilir.'
            : 'Yalnızca şoförü olduğunuz aracın km bilgisini girebilirsiniz.'))));
  }

  async function start() {
    const when = dateTimeInput({ min: t.created_at });
    modal({
      title: `Göreve başlat — ${t.code}`,
      body: h('div', null, h('div', { class: 'alert warn' }, h('b', null, 'Başlamadan önce'), h('ul', null, START_WARNINGS.map(w => h('li', null, w)))),
        field('Başlama zamanı', when)),
      actions: [{ label: 'Vazgeç' }, {
        label: 'Görevi Başlat', class: 'primary',
        onClick: async () => { await api.post(`/api/field/tasks/${id}/start`, { at: when.getValue() }); toast('Görev başladı'); await load(); },
      }],
    });
  }
  async function cancel() {
    if (!await confirmDialog('Görevi iptal et', `${t.code} iptal edilsin mi? Uçaklar depoya geri döner.`, { okLabel: 'İptal Et', danger: true })) return;
    try { await api.post(`/api/field/tasks/${id}/cancel`); toast('Görev iptal edildi'); await load(); } catch (err) { toastError(err); }
  }
  function finish(success) {
    const when = dateTimeInput({ min: t.started_at });
    modal({
      title: success ? 'Başarılı tamamla' : 'Başarısız tamamla',
      body: h('div', null,
        h('p', { style: { marginTop: 0 } }, `${t.code} görevi ${success ? 'başarılı' : 'başarısız'} olarak kapatılsın mı? `
          + `Şu ana kadarki süre: ${fmtDuration(secondsSince(t.started_at))}`),
        field('Bitiş zamanı', when)),
      actions: [{ label: 'Vazgeç' }, {
        label: 'Tamamla', class: success ? 'success' : 'danger',
        onClick: async () => { await api.post(`/api/field/tasks/${id}/finish`, { success, at: when.getValue() }); toast('Görev tamamlandı'); await load(); },
      }],
    });
  }

  clear(view, head, info, tabSeg, body);
  await load();
  every(8000, () => { if (tab === 'flights' && t.flights.some(f => f.log_status === 'ISLENIYOR')) load().catch(() => {}); });
}

// ---------- Görev yerleri ve araçlar ----------
async function renderPlaces(view, ctx) {
  const canEdit = ctx.user.roles.some(r => ['Sistem Yöneticisi', 'Saha Sorumlusu', 'Şoför'].includes(r));
  const locBox = h('div', { class: 'card card-pad' });
  const vehBox = h('div', { class: 'card card-pad' });
  const stats = statStrip();
  let locations = [], vehicles = [];
  const load = async () => {
    [locations, vehicles] = await Promise.all([api.get('/api/field/locations'), api.get('/api/field/vehicles')]);
    const top = [...locations].sort((a, b) => b.task_count - a.task_count)[0];
    stats.set([
      { label: 'Görev yeri', value: locations.length, sub: `aktif ${locations.filter(l => l.active).length}` },
      { label: 'Araç', value: vehicles.length, sub: `aktif ${vehicles.filter(v => v.active).length}` },
      { label: 'En çok gidilen yer', value: top?.task_count || 0, sub: top?.name || '—' },
    ]);
    drawList(locBox, 'Görev yerleri', locations, { key: 'name', label: 'Görev yeri adı', path: 'locations', noun: 'görev yeri' });
    drawList(vehBox, 'Araçlar', vehicles, { key: 'plate', label: 'Plaka', path: 'vehicles', noun: 'araç', mono: true });
  };
  function drawList(box, title, rows, o) {
    const name = h('input', { class: `input ${o.mono ? 'mono' : ''}`, placeholder: o.label });
    const desc = h('input', { class: 'input', placeholder: 'Açıklama (isteğe bağlı)' });
    const q = h('input', { class: 'input', type: 'search', placeholder: `${title} içinde ara…` });
    const tbody = h('tbody');
    const payload = r => ({ [o.key]: r[o.key], description: r.description, active: !!r.active });
    const toggle = async r => {
      try { await api.put(`/api/field/${o.path}/${r.id}`, { ...payload(r), active: !r.active }); await load(); } catch (err) { toastError(err); }
    };
    const remove = async r => {
      if (!await confirmDialog('Sil', `${r[o.key]} silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
      try { await api.del(`/api/field/${o.path}/${r.id}`); toast('Silindi'); await load(); } catch (err) { toastError(err); }
    };
    const edit = r => {
      const n = h('input', { class: `input ${o.mono ? 'mono' : ''}`, value: r[o.key] });
      const d = h('input', { class: 'input', value: r.description || '' });
      modal({
        title: `${r[o.key]} — düzenle`,
        body: h('div', null, field(o.label, n), field('Açıklama', d)),
        actions: [{ label: 'Vazgeç' }, {
          label: 'Kaydet', class: 'primary',
          onClick: async () => {
            await api.put(`/api/field/${o.path}/${r.id}`, { ...payload(r), [o.key]: n.value, description: d.value || null });
            toast('Kaydedildi');
            await load();
          },
        }],
      });
    };
    const draw = () => clear(tbody, rows.filter(r => matches(q.value, r[o.key], r.description)).map(r => h('tr', null,
      h('td', null, h('b', { class: o.mono ? 'mono' : '' }, r[o.key]), r.description ? h('div', { class: 'small muted' }, r.description) : null),
      h('td', null, r.active ? h('span', { class: 'badge green' }, 'Aktif') : h('span', { class: 'badge gray' }, 'Pasif')),
      h('td', null, r.task_count),
      h('td', { class: 'num' }, canEdit ? [
        h('button', { class: 'btn sm ghost', onclick: () => edit(r) }, 'Düzenle'),
        h('button', { class: 'btn sm ghost', onclick: () => toggle(r) }, r.active ? 'Pasife al' : 'Aktifleştir'),
        h('button', { class: 'btn sm ghost', onclick: () => remove(r) }, 'Sil')] : null))));
    q.addEventListener('input', draw);
    const add = h('button', { class: 'btn primary' }, svgIcon(icons.plus), 'Ekle');
    add.addEventListener('click', async () => {
      try {
        await api.post(`/api/field/${o.path}`, { [o.key]: name.value, description: desc.value || null });
        toast('Eklendi');
        await load();
      } catch (err) { toastError(err); }
    });
    clear(box, h('h2', { class: 'side-title' }, `${title} (${rows.length})`),
      canEdit ? h('div', { class: 'row', style: { alignItems: 'flex-end', marginBottom: '10px' } }, name, desc,
        h('div', { style: { flex: '0 0 auto' } }, add)) : null,
      rows.length ? [h('div', { style: { marginBottom: '8px' } }, q), h('div', { class: 'table-wrap' }, h('table', null,
        h('thead', null, h('tr', null, [o.label, 'Durum', 'Görev', ''].map(c => h('th', null, c)))), tbody))]
        : h('div', { class: 'empty' }, `Kayıtlı ${o.noun} yok`));
    draw();
  }
  clear(view, pageHead('Görev Yerleri ve Araçlar', { back: '#/field', sub: 'Yol Yönetimi\'nde seçilen görev yerleri ve araç plakaları' }),
    stats, h('div', { class: 'places-grid' }, locBox, vehBox));
  await load();
}
