// Yazıcı Yönetimi: Creality K2 Plus filosu
import { api } from '../api.js';
import { icons } from '../icons.js';
import { PRINTER_STATES, badge } from '../status.js';
import { printerRoom } from './printers3d.js';
import { subnav } from './production.js';
import {
  clear, confirmDialog, every, field, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, pref, segmented, selectInput, setPref,
  svgIcon, toast, toastError,
} from '../ui.js';

export async function render(view, params, ctx) {
  const body = h('div');
  const canOpen = ctx.user.modules.includes('production');
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Yazıcı adı, IP veya dosya ara…', style: { width: '230px' } });
  const state = selectInput([
    ...Object.entries(PRINTER_STATES).map(([k, s]) => [k, s.label]),
    ['SYSTEM', 'Sistemde işi olan'], ['MISMATCH', 'Durumu uyumsuz olan'], ['AUTO', 'Otomatik eklenen'],
  ], { all: 'Tüm durumlar' });
  let printers = [];
  // Görünüm: Liste | 3B (yazıcı odası); seçim kullanıcı tercihinde saklanır
  let mode = pref('printers.view', 'list');
  let room = null;
  // Sıralama: raf katlarındaki yazıcı sırası (yalnızca yazıcı yöneticisi)
  const canEdit = ctx.user.modules.includes('printers');
  if (mode === 'order' && !canEdit) mode = 'list';
  let board = null;
  const modeSeg = segmented([['list', 'Liste'], ['3d', '3B Görünüm'], ...(canEdit ? [['order', 'Sıralama']] : [])], mode,
    v => { mode = v; setPref('printers.view', v); draw(); });
  const idle = p => p.live_state === 'HAZIR' || p.live_state === 'TAMAMLANDI';
  const mismatch = p => (idle(p) && p.current_part) || (p.live_state === 'YAZDIRIYOR' && !p.current_part);
  const draw = () => {
    const list = printers.filter(p =>
      (!state.value || (state.value === 'SYSTEM' ? p.current_part : state.value === 'MISMATCH' ? mismatch(p)
        : state.value === 'AUTO' ? p.auto_added : p.live_state === state.value)) &&
      matches(q.value, p.name, p.ip, p.model, p.live_file, p.last_job, p.current_order, p.current_part));
    if (mode === '3d') {   // oda tüm yazıcıları gösterir; filtreler liste görünümü içindir
      room ??= printerRoom({ canEdit, canOpen, reload: () => load() });
      if (!body.contains(room.el)) clear(body, room.el);
      room.update(printers);
      q.hidden = state.hidden = true;
      return;
    }
    if (mode === 'order') {
      if (!board || !body.contains(board.el)) {
        if (!board?.dirty()) board = rackBoard(printers, () => { board = null; return load(); });
        clear(body, board.el);
      }
      board.refresh(printers);
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
  const namesBtn = h('button', { class: 'btn', title: 'Yazıcı ekranından girilen cihaz adını sisteme çeker (ağ adı K2Plus-XXXX kullanılmaz)' }, svgIcon(icons.tag), 'İsimleri Yenile');
  namesBtn.addEventListener('click', () => busy(namesBtn, async () => {
    const r = await api.post('/api/printers/refresh-names');
    await load();
    if (r.changed.length) toast(`${r.changed.length} yazıcının adı güncellendi: ${r.changed.map(c => `${c.old} → ${c.new}`).slice(0, 4).join(', ')}${r.changed.length > 4 ? '…' : ''}`);
    else toast(`Değişen ad yok · ${r.no_name}/${r.total} yazıcının ekranında ad girilmemiş ya da ulaşılamadı`, r.no_name ? '' : 'ok');
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
    pageHead('Yazıcı Yönetimi', { back: canOpen ? '#/production' : '#/', sub: canOpen ? 'Üretim Yönetimi · canlı durumlar' : 'Canlı yazıcı durumları', tabs: canOpen ? subnav('printers', ctx) : null }),
    // Tek toolbar: görünüm seçici + eylem düğmeleri baloncukta (Excel dahil) + arama/filtre; ayrı bar yok, istatistik kartları yok
    moduleToolbar(modeSeg, refreshBtn, namesBtn, discoverBtn,
      h('button', { class: 'btn primary', onclick: () => printerForm(null, load) }, svgIcon(icons.plus), 'Yeni Yazıcı'),
      q, state),
    body);
  await load();
  every(10000, () => load().catch(() => {}));
}

// ---------- Sıralama: dört raf katı kutusu; yazıcılar sürükle bırakla sıralanır / katlar arasında taşınır.
// Kaydedilince her yazıcının taraf / kat / sırası güncellenir, 3B oda bu yerleşimle çizilir.
const RACKS = [['L', 1, 'Sol Raf Kat 1'], ['L', 2, 'Sol Raf Kat 2'], ['R', 1, 'Sağ Raf Kat 3'], ['R', 2, 'Sağ Raf Kat 4']];

function rackBoard(printers, onSaved) {
  let dirty = false;
  const byId = new Map(printers.map(p => [p.id, p]));
  const lists = RACKS.map(() => h('div', { class: 'rack-list' }));
  const counts = RACKS.map(() => h('span', { class: 'rack-count' }));
  const dot = p => h('span', { class: `rack-dot s-${(p.live_state || 'none').toLowerCase()}`, title: PRINTER_STATES[p.live_state]?.label || 'Bilinmiyor' });
  const item = p => {
    const el = h('div', { class: 'rack-item', 'data-id': p.id },
      h('span', { class: 'rack-grip', 'aria-hidden': 'true' }, '⋮⋮'), h('span', { class: 'rack-no' }), dot(p), h('b', null, p.name),
      h('span', { class: 'small muted rack-ip' }, p.ip || ''));
    el.addEventListener('pointerdown', e => startDrag(e, el));
    return el;
  };
  const fill = () => {
    RACKS.forEach(([side, level], i) => clear(lists[i], printers.filter(p => p.rack_side === side && p.rack_level === level)
      .sort((a, b) => a.rack_slot - b.rack_slot).map(item)));
    // yeri olmayan yazıcı: en az dolu kata
    for (const p of printers.filter(p => !p.rack_side)) lists.reduce((a, b) => (b.children.length < a.children.length ? b : a)).append(item(p));
    renumber();
  };
  const renumber = () => lists.forEach((l, i) => {
    [...l.querySelectorAll('.rack-item')].forEach((el, n) => { el.querySelector('.rack-no').textContent = n + 1; });
    counts[i].textContent = `${l.querySelectorAll('.rack-item').length} yazıcı`;
  });
  const save = h('button', { class: 'btn primary', disabled: true }, 'Kaydet');
  const undo = h('button', { class: 'btn', disabled: true }, 'Değişiklikleri Geri Al');
  const hint = h('span', { class: 'small muted' }, 'Yazıcıları sürükleyip bırakarak sıralayın ya da başka bir kata taşıyın.');
  const mark = v => { dirty = v; save.disabled = undo.disabled = !v; hint.textContent = v ? 'Kaydedilmemiş değişiklik var' : 'Yazıcıları sürükleyip bırakarak sıralayın ya da başka bir kata taşıyın.'; hint.classList.toggle('warn-text', v); };
  undo.addEventListener('click', () => { fill(); mark(false); });
  save.addEventListener('click', async () => {
    const items = lists.flatMap((l, i) => [...l.querySelectorAll('.rack-item')].map((el, n) =>
      ({ id: Number(el.dataset.id), side: RACKS[i][0], level: RACKS[i][1], slot: n + 1 })));
    save.disabled = true;
    try {
      await api.put('/api/printers/layout', { items });
      toast('Raf sıralaması kaydedildi; 3B görünüm güncellendi');
      mark(false);
      await onSaved();
    } catch (err) { toastError(err); save.disabled = false; }
  });

  // Sürükle bırak (fare ve dokunmatik): tutulan öğenin kopyası imleci izler, yer tutucu bırakılacak yeri gösterir
  function startDrag(e, el) {
    if (e.button !== 0) return;
    const x0 = e.clientX, y0 = e.clientY;
    let ghost = null, holder = null, dx = 0, dy = 0;
    const move = ev => {
      if (!ghost) {
        if (Math.hypot(ev.clientX - x0, ev.clientY - y0) < 5) return;
        const r = el.getBoundingClientRect();
        dx = x0 - r.left; dy = y0 - r.top;
        ghost = el.cloneNode(true);
        ghost.classList.add('rack-ghost');
        ghost.style.width = `${r.width}px`;
        document.body.append(ghost);
        holder = h('div', { class: 'rack-holder' });
        holder.style.height = `${r.height}px`;
        el.after(holder);
        el.classList.add('rack-hidden');
      }
      ghost.style.transform = `translate(${ev.clientX - dx}px, ${ev.clientY - dy}px)`;
      const list = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.rack-list');
      if (list && lists.includes(list)) {
        const next = [...list.querySelectorAll('.rack-item:not(.rack-hidden)')]
          .find(c => { const r = c.getBoundingClientRect(); return ev.clientY < r.top + r.height / 2; });
        if (next) next.before(holder); else list.append(holder);
      }
    };
    const end = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
      if (!ghost) return;
      ghost.remove();
      holder.replaceWith(el);
      el.classList.remove('rack-hidden');
      renumber();
      mark(true);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
    e.preventDefault();
  }

  fill();
  const el = h('div', null,
    h('div', { class: 'rack-bar' }, hint, h('span', { class: 'spacer' }), undo, save),
    h('div', { class: 'rack-board' }, RACKS.map(([, , title], i) =>
      h('div', { class: 'card rack-box' }, h('div', { class: 'rack-head' }, h('b', null, title), counts[i]), lists[i]))));
  return {
    el,
    dirty: () => dirty,
    refresh(list) {   // canlı durum noktaları (sıralamayı bozmadan)
      for (const p of list) {
        byId.set(p.id, p);
        const d = el.querySelector(`.rack-item[data-id="${p.id}"] .rack-dot`);
        if (d) d.replaceWith(dot(p));
      }
    },
  };
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
          : `${p.current_order} / ${p.current_part}`)
          : p.file_part ? h('div', { class: 'small muted', title: 'Yazıcıdaki dosya adından tanındı; sistemde siparişi yok' }, `Parça: ${p.file_part} (dosyadan)`) : null,
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
  const mac = h('input', { class: 'input mono', value: p?.mac || '', placeholder: 'FC:EE:28:0F:36:97', autocapitalize: 'characters', spellcheck: 'false' });
  modal({
    title: p ? 'Yazıcıyı Düzenle' : 'Yeni Yazıcı',
    body: h('div', null, field('Yazıcı adı', name), field('IP adresi', ip),
      field('MAC adresi (kablolu)', mac),
      h('p', { class: 'small muted' }, 'MAC, yazıcının kalıcı kimliğidir: IP (DHCP) değişse de sistem yazıcıyı MAC’ten türeyen ağ adıyla (K2Plus-XXXX) bulur.')),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          const body = { name: name.value.trim(), ip: ip.value.trim(), mac: mac.value.trim() };
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
