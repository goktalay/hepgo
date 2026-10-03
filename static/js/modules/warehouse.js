// Depo Yönetimi: üretimden teslim edilen parçaların onayı, depo geçmişi ve
// kalibrasyonu biten uçakların saha deposuna alınması
import { api } from '../api.js';
import { PART_STATES, badge, queuePlate } from '../status.js';
import {
  clear, dateTimeInput, every, field, fmtDateTime, h, matches, modal, pageHead, segmented, statStrip, t, toast, toastError, periodFilter
} from '../ui.js';

export async function render(view, params, ctx) {
  let tab = params[0] === 'aircraft' ? 'aircraft' : 'pending';
  const mine = h('input', { type: 'checkbox' });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Sipariş, parça kodu, kişi ara…', style: { width: '230px' } });
  const orderSel = h('select', { class: 'input' });
  const stats = statStrip();
  const body = h('div');
  const approveBtn = h('button', { class: 'btn success' }, 'Seçilenleri Onayla');
  let selected = new Set();
  let pending = [], history = [], aircraft = { pending: [], approved: [] };

  const filt = rows => rows.filter(r =>
    (!orderSel.value || r.order_code === orderSel.value) &&
    matches(q.value, r.order_code, r.part_id, r.delivered_by_name, r.delivered_to_name, r.approved_by_name, r.printer_name));
  const filtAircraft = rows => rows.filter(o => (!orderSel.value || o.code === orderSel.value) && matches(q.value, o.code, o.queue_no, o.note));

  const draw = () => {
    approveBtn.hidden = tab !== 'pending';
    mine.parentElement.hidden = tab !== 'pending';
    const today = new Date().toISOString().slice(0, 10);
    const mineRows = pending.filter(r => r.delivered_to_name === ctx.user.full_name);
    stats.set([
      { label: 'Onay bekleyen parça', value: pending.length, tone: pending.length ? 'alert' : '' },
      { label: 'Bana teslim edilen', value: mineRows.length },
      { label: 'Bugün onaylanan', value: history.filter(r => (r.approved_at || '').startsWith(today)).length, tone: 'ok' },
      { label: 'Bekleyen sipariş', value: new Set(pending.map(r => r.order_code)).size, sub: 'onay bekleyen parçası olan' },
      { label: 'Depoda (onaylı)', value: history.filter(r => r.state === 'DEPO').length },
      { label: 'Montajda', value: history.filter(r => r.state === 'MONTAJ').length },
      { label: 'Saha deposu onayı bekleyen uçak', value: aircraft.pending.length, tone: aircraft.pending.length ? 'alert' : '' },
    ]);
    const codes = [...new Set([...pending, ...history].map(r => r.order_code).concat(
      [...aircraft.pending, ...aircraft.approved].map(o => o.code)))].sort();
    const cur = orderSel.value;
    clear(orderSel, h('option', { value: '' }, 'Tüm siparişler'), codes.map(c => h('option', { value: c, selected: c === cur }, c)));
    if (tab === 'aircraft') {
      const rows = filtAircraft(aircraft.pending), done = filtAircraft(aircraft.approved);
      clear(body,
        h('h2', { class: 'section-title' }, 'Saha deposu onayı bekleyen uçaklar'),
        rows.length ? aircraftTable(rows, true) : h('div', { class: 'card empty' }, 'Onay bekleyen uçak yok'),
        h('h2', { class: 'section-title', style: { marginTop: '18px' } }, 'Saha deposuna alınan uçaklar'),
        done.length ? aircraftTable(done, false) : h('div', { class: 'card empty' }, 'Kayıt yok'));
    } else if (tab === 'pending') {
      const rows = filt(mine.checked ? mineRows : pending);
      selected = new Set([...selected].filter(id => rows.some(r => r.id === id)));
      clear(body, rows.length ? pendingTable(rows) : h('div', { class: 'card empty' }, 'Onay bekleyen parça yok'));
    } else {
      const rows = filt(history);
      clear(body, rows.length ? historyTable(rows) : h('div', { class: 'card empty' }, 'Filtreye uyan kayıt yok'));
    }
    period.el.hidden = tab !== 'history';   // dönem yalnızca geçmişte
    approveBtn.textContent = selected.size ? t('Seçilenleri Onayla ({n})', { n: selected.size }) : 'Seçilenleri Onayla';
  };
  const period = periodFilter('whHistory', () => load().catch(toastError), { title: 'Depo Geçmişi: onay tarihi' });
  const load = async () => {
    [pending, history, aircraft] = await Promise.all([api.get('/api/warehouse/pending'), api.get(`/api/warehouse/history?${period.qs()}`),
      api.get('/api/warehouse/aircraft')]);
    draw();
  };

  function pendingTable(rows) {
    const all = h('input', { type: 'checkbox', checked: rows.length > 0 && rows.every(r => selected.has(r.id)) });
    all.addEventListener('change', () => { rows.forEach(r => (all.checked ? selected.add(r.id) : selected.delete(r.id))); draw(); });
    return h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, h('th', { style: { width: '36px' } }, all),
        ['Sipariş', 'Parça', 'Yazıcı', 'Teslim eden', 'Teslim alan', 'Teslim zamanı'].map(t => h('th', null, t)))),
      h('tbody', null, rows.map(r => {
        const cb = h('input', { type: 'checkbox', checked: selected.has(r.id) });
        cb.addEventListener('change', () => { cb.checked ? selected.add(r.id) : selected.delete(r.id); draw(); });
        return h('tr', null,
          h('td', null, cb),
          h('td', null, h('b', null, r.order_code)),
          h('td', { class: 'mono' }, r.part_id),
          h('td', null, r.printer_name || '—'),
          h('td', null, r.delivered_by_name || '—'),
          h('td', null, r.delivered_to_name || '—'),
          h('td', { class: 'muted' }, fmtDateTime(r.finished_at)));
      }))));
  }

  function historyTable(rows) {
    return h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Sipariş', 'Parça', 'Durum', 'Teslim eden', 'Onaylayan', 'Onay zamanı'].map(t => h('th', null, t)))),
      h('tbody', null, rows.map(r => h('tr', null,
        h('td', null, h('b', null, r.order_code)),
        h('td', { class: 'mono' }, r.part_id),
        h('td', null, badge(PART_STATES, r.state)),
        h('td', null, r.delivered_by_name || '—'),
        h('td', null, r.approved_by_name || '—'),
        h('td', { class: 'muted' }, fmtDateTime(r.approved_at)))))));
  }

  function aircraftTable(rows, canApprove) {
    return h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Sipariş', 'Açıklama', 'Kalibrasyon', canApprove ? '' : 'Kuyruk no', canApprove ? '' : 'Onay']
        .map(t => h('th', null, t)))),
      h('tbody', null, rows.map(o => h('tr', null,
        h('td', null, h('a', { href: `#/production/${o.id}` }, h('b', null, o.code))),
        h('td', { class: 'muted' }, o.note || '—'),
        h('td', { class: 'muted' }, fmtDateTime(o.steps.KALIBRASYON?.at)),
        canApprove
          ? h('td', null, h('button', { class: 'btn success sm', onclick: () => approveAircraft(o) }, 'Saha Deposuna Al'))
          : h('td', null, queuePlate(o.queue_no) || '—'),
        canApprove ? h('td') : h('td', { class: 'muted' },
          `${fmtDateTime(o.steps.SAHA_DEPO?.at)} · ${o.steps.SAHA_DEPO?.recorded_by_name || ''}`))))));
  }

  function approveAircraft(o) {
    const when = dateTimeInput({ min: o.steps.KALIBRASYON?.at });
    modal({
      title: t('{code} — Saha deposuna al', { code: o.code }),
      body: h('div', null,
        h('p', { style: { marginTop: 0 } }, 'Kalibrasyonu tamamlanan uçağı teslim aldınız mı? Onaylanınca uçağa kuyruk numarası verilir ve sahaya gönderilebilir.'),
        field('Teslim alma zamanı', when)),
      actions: [
        { label: 'Vazgeç' },
        {
          label: 'Onayla', class: 'success', onClick: async () => {
            const { queue_no } = await api.post(`/api/warehouse/aircraft/${o.id}/approve`, { at: when.getValue() });
            toast(t('{code} saha deposunda · kuyruk no {queue}', { code: o.code, queue: queue_no }));
            await load();
          },
        },
      ],
    });
  }

  approveBtn.addEventListener('click', () => {
    if (!selected.size) return toastError(new Error('Onaylanacak parça seçin'));
    const ids = [...selected];
    const when = dateTimeInput();
    modal({
      title: 'Depo girişini onayla',
      body: h('div', null, h('p', { style: { marginTop: 0 } }, t('{n} parça depoya alınacak.', { n: ids.length })), field('Onay zamanı', when)),
      actions: [
        { label: 'Vazgeç' },
        {
          label: 'Onayla', class: 'success', onClick: async () => {
            const { approved } = await api.post('/api/warehouse/approve', { ids, at: when.getValue() });
            toast(t('{n} parça depoya alındı', { n: approved }));
            selected.clear();
            await load();
          },
        },
      ],
    });
  });

  clear(view,
    pageHead('Onay Yönetimi', { back: '#/', tabs: segmented([['pending', 'Onay Bekleyenler'], ['history', 'Depo Geçmişi'], ['aircraft', 'Saha Deposu Onayı']], tab, v => { tab = v; draw(); }) }),
    stats,
    h('div', { class: 'filters' },
      q, orderSel, period.el,
      h('label', { class: 'check' }, mine, 'Sadece bana teslim edilenler'),
      h('span', { class: 'spacer' }),
      approveBtn),
    body);
  mine.addEventListener('change', draw);
  q.addEventListener('input', draw);
  orderSel.addEventListener('change', draw);
  await load();
  every(30000, () => load().catch(() => {}));
}
