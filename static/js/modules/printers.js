// Yazıcı Yönetimi: Creality K2 Plus filosu
import { api } from '../api.js';
import { icons } from '../icons.js';
import { PRINTER_STATES, badge } from '../status.js';
import { printerRoom } from './printers3d.js';
import {
  clear, confirmDialog, every, field, fmtDateTime, h, matches, modal, pageHead, pref, segmented, selectInput, setPref, statStrip,
  svgIcon, toast, toastError,
} from '../ui.js';

export async function render(view, params, ctx) {
  const body = h('div');
  const canOpen = ctx.user.modules.includes('production');
  const stats = statStrip();
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Yazıcı adı, IP veya dosya ara…', style: { width: '230px' } });
  const state = selectInput([
    ...Object.entries(PRINTER_STATES).map(([k, s]) => [k, s.label]),
    ['SYSTEM', 'Sistemde işi olan'], ['MISMATCH', 'Durumu uyumsuz olan'], ['AUTO', 'Otomatik eklenen'],
  ], { all: 'Tüm durumlar' });
  let printers = [];
  // Görünüm: Liste | 3B (yazıcı odası); seçim kullanıcı tercihinde saklanır
  let mode = pref('printers.view', 'list');
  let room = null;
  const modeSeg = segmented([['list', 'Liste'], ['3d', '3B Görünüm']], mode, v => { mode = v; setPref('printers.view', v); draw(); });
  const idle = p => p.live_state === 'HAZIR' || p.live_state === 'TAMAMLANDI';
  const mismatch = p => (idle(p) && p.current_part) || (p.live_state === 'YAZDIRIYOR' && !p.current_part);
  const draw = () => {
    const n = f => printers.filter(f).length;
    stats.set([
      { label: 'Toplam yazıcı', value: printers.length },
      { label: 'Yazdıran', value: n(p => p.live_state === 'YAZDIRIYOR'), tone: 'ok' },
      { label: 'Hazır (boşta)', value: n(p => p.live_state === 'HAZIR') },
      { label: 'Baskısı biten', value: n(p => p.live_state === 'TAMAMLANDI'), sub: 'tabla boşaltılmalı' },
      { label: 'Hata / duraklatıldı', value: n(p => p.live_state === 'HATA' || p.live_state === 'DURAKLADI'),
        tone: n(p => p.live_state === 'HATA' || p.live_state === 'DURAKLADI') ? 'alert' : '' },
      { label: 'Çevrimdışı', value: n(p => !p.live_state || p.live_state === 'CEVRIMDISI'), tone: 'muted' },
      { label: 'Sistemde işi olan', value: n(p => p.current_part) },
      { label: 'Durumu uyumsuz', value: n(mismatch), tone: n(mismatch) ? 'alert' : '', sub: 'yazıcı ↔ sistem' },
    ]);
    const list = printers.filter(p =>
      (!state.value || (state.value === 'SYSTEM' ? p.current_part : state.value === 'MISMATCH' ? mismatch(p)
        : state.value === 'AUTO' ? p.auto_added : p.live_state === state.value)) &&
      matches(q.value, p.name, p.ip, p.model, p.live_file, p.last_job, p.current_order, p.current_part));
    if (mode === '3d') {   // oda tüm yazıcıları gösterir; filtreler liste görünümü içindir
      room ??= printerRoom({ canEdit: ctx.user.modules.includes('printers'), canOpen, reload: () => load() });
      if (!body.contains(room.el)) clear(body, room.el);
      room.update(printers);
      q.hidden = state.hidden = true;
      return;
    }
    q.hidden = state.hidden = false;
    clear(body, !printers.length
      ? h('div', { class: 'card empty' }, 'Kayıtlı yazıcı yok. “Yeni Yazıcı” ile ekleyin ya da “Otomatik Ekle” ile ağı tarayın.')
      : list.length ? table(list, load, canOpen) : h('div', { class: 'card empty' }, 'Filtreye uyan yazıcı yok'));
  };
  const load = async () => { printers = await api.get('/api/printers'); draw(); };
  q.addEventListener('input', draw);
  state.addEventListener('change', draw);

  const refreshBtn = h('button', { class: 'btn' }, svgIcon(icons.refresh), 'Durumları Yenile');
  refreshBtn.addEventListener('click', () => busy(refreshBtn, async () => {
    await api.post('/api/printers/refresh');
    await load();
    toast('Yazıcı durumları güncellendi');
  }));
  const discoverBtn = h('button', { class: 'btn' }, svgIcon(icons.radar), 'Otomatik Ekle');
  discoverBtn.addEventListener('click', () => busy(discoverBtn, async () => {
    toast('Ağ taranıyor, bu işlem birkaç saniye sürebilir…');
    const res = await api.post('/api/printers/discover');
    await load();
    if (res.added.length) toast(`${res.added.length} yazıcı eklendi: ${res.added.map(a => a.ip).join(', ')}`);
    else toast(res.found ? 'Ağdaki yazıcıların hepsi zaten kayıtlı' : 'Ağda yazıcı bulunamadı', res.found ? '' : 'err');
  }));

  clear(view,
    pageHead('Yazıcı Yönetimi', { back: '#/', sub: 'Durumlar her 10 saniyede yazıcılardan okunur', right: h('div', { class: 'head-right' }, modeSeg) }),
    stats,
    h('div', { class: 'filters' },
      q, state,
      h('span', { class: 'spacer' }),
      refreshBtn, discoverBtn,
      h('button', { class: 'btn primary', onclick: () => printerForm(null, load) }, svgIcon(icons.plus), 'Yeni Yazıcı')),
    body);
  await load();
  every(10000, () => load().catch(() => {}));
}

async function busy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (err) { toastError(err); } finally { btn.disabled = false; }
}

function status(p) {
  if (!p.live_state) return h('span', { class: 'badge gray' }, 'Bilinmiyor');
  const b = badge(PRINTER_STATES, p.live_state);
  return p.live_state === 'YAZDIRIYOR' && p.live_progress != null
    ? h('span', null, b, h('span', { class: 'small muted' }, ` %${Math.round(p.live_progress)}`)) : b;
}

function table(printers, reload, canOpen) {
  return h('div', { class: 'table-wrap' }, h('table', null,
    h('thead', null, h('tr', null,
      ['Yazıcı', 'IP adresi', 'Durum', 'Son yüklenen iş', 'İş başlama', 'İş bitiş', 'Son görülme', ''].map(t => h('th', null, t)))),
    h('tbody', null, printers.map(p => h('tr', null,
      h('td', null, h('b', null, p.name), h('div', { class: 'small muted' }, [p.model, p.auto_added ? 'otomatik eklendi' : null].filter(Boolean).join(' · ') || '—')),
      h('td', { class: 'mono' }, p.ip),
      h('td', null, status(p),
        p.current_part ? h('div', { class: 'small' }, 'Sistemde: ', canOpen
          ? h('a', { href: `#/production/${p.current_order_id}` }, `${p.current_order} / ${p.current_part}`)
          : `${p.current_order} / ${p.current_part}`) : null,
        p.live_file ? h('div', { class: 'small muted' }, p.live_file) : null),
      h('td', null, p.last_job || '—'),
      h('td', { class: 'muted' }, fmtDateTime(p.last_job_start)),
      h('td', { class: 'muted' }, p.last_job_start && !p.last_job_end ? 'Devam ediyor' : fmtDateTime(p.last_job_end)),
      h('td', { class: 'muted' }, fmtDateTime(p.last_seen)),
      h('td', { class: 'num' },
        h('button', { class: 'btn sm ghost', onclick: () => printerForm(p, reload) }, 'Düzenle'),
        h('button', { class: 'btn sm ghost', onclick: () => remove(p, reload) }, 'Sil')))))));
}

function printerForm(p, done) {
  const name = h('input', { class: 'input', value: p?.name || '', placeholder: 'Ör. K2 Plus 01' });
  const ip = h('input', { class: 'input mono', value: p?.ip || '', placeholder: '192.168.1.50', inputmode: 'decimal' });
  modal({
    title: p ? 'Yazıcıyı Düzenle' : 'Yeni Yazıcı',
    body: h('div', null, field('Yazıcı adı', name), field('IP adresi', ip)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          const body = { name: name.value.trim(), ip: ip.value.trim() };
          if (p) await api.put(`/api/printers/${p.id}`, body);
          else await api.post('/api/printers', body);
          toast('Yazıcı kaydedildi');
          done();
        },
      },
    ],
  });
}

async function remove(p, reload) {
  if (!await confirmDialog('Yazıcıyı sil', `${p.name} (${p.ip}) listeden silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
  try {
    await api.del(`/api/printers/${p.id}`);
    toast('Yazıcı silindi');
    reload();
  } catch (err) { toastError(err); }
}
