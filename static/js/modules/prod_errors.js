// Araçlar → Üretim Hataları: üretimde parçalara girilen hata kayıtları; filtre, en çok hata verenler, fotoğraflı detay, CSV.
import { api, fileUrl } from '../api.js';
import { PART_STATES, badge } from '../status.js';
import { clear, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, pref, segmented, selectInput, setPref, statStrip, toastError, periodFilter } from '../ui.js';
import { companyTag } from './production.js';

const day = iso => (iso || '').slice(0, 10);
// Serbest girilen hata kodları gruplanırken büyük / küçük harf ve boşluk farkı yok sayılır; anlamsız kodlar "Kodsuz"
const codeKey = c => {
  const k = (c || '').trim().toLocaleUpperCase('tr').replace(/\s+/g, ' ');
  return !k || /^[.\-0]+$/.test(k) || /^(KOD YOK|HATA KODU YOK)/.test(k) ? 'Kodsuz' : k;
};
const printerLabel = r => (r.printer_name ? (/^\d+$/.test(r.printer_name) ? `Yazıcı ${r.printer_name}` : r.printer_name) : '—');

export async function renderProductionErrors(view, ctx) {
  let rows;
  const period = periodFilter('prodErrors', () => renderProductionErrors(view, ctx));   // dönem değişince sayfa yeni veriyle kurulur
  try { rows = await api.get(`/api/production-errors?${period.qs()}`); } catch (err) { toastError(err); rows = []; }
  const canOpen = ctx.user.modules.includes('production');
  const uniq = (key, label) => [...new Map(rows.filter(r => r[key] != null).map(r => [String(r[key]), label(r)])).entries()]
    .sort((a, b) => a[1].localeCompare(b[1], 'tr', { numeric: true }));

  const q = h('input', { class: 'input', type: 'search', placeholder: 'Hata kodu, açıklama, parça, sipariş ara…', style: { width: '260px' } });
  const printer = selectInput(uniq('printer_id', printerLabel), { all: 'Tüm yazıcılar' });
  const part = selectInput(uniq('part_id', r => r.part_id), { all: 'Tüm parçalar' });
  const order = selectInput(uniq('order_id', r => r.order_code), { all: 'Tüm siparişler' });
  const person = selectInput(uniq('user_id', r => r.user_name || '—'), { all: 'Kaydeden: herkes' });
  const code = selectInput([...new Set(rows.map(r => codeKey(r.error_code)))].sort((a, b) => a.localeCompare(b, 'tr')).map(c => [c, c]),
    { all: 'Tüm hata kodları' });
  const photoOnly = h('input', { type: 'checkbox' });
  const csvBtn = h('button', { class: 'btn', type: 'button' }, 'Excel (CSV) indir');
  const stats = statStrip();
  const tops = h('div', { class: 'pe-tops' });
  const body = h('div');
  let list = [];
  // Kart (varsayılan: hata resmiyle) / Liste görünümü; seçim kullanıcı tercihinde saklanır
  let mode = pref('prodErrors.view', 'card');
  const modeSeg = segmented([['card', 'Kart'], ['list', 'Liste']], mode, v => { mode = v; setPref('prodErrors.view', v); draw(); });

  const filtered = () => rows.filter(r =>

    (!printer.value || String(r.printer_id) === printer.value) && (!part.value || r.part_id === part.value) &&
    (!order.value || String(r.order_id) === order.value) && (!person.value || String(r.user_id) === person.value) &&
    (!code.value || codeKey(r.error_code) === code.value) && (!photoOnly.checked || r.photo) &&
    matches(q.value, r.error_code, r.note, r.part_id, r.order_code, r.printer_name, r.user_name, r.company_name));

  // "En çok hata" kutusu: tıklanan satır filtreye uygulanır
  const topBox = (title, items, apply) => h('div', { class: 'card card-pad pe-top' },
    h('h3', null, title),
    items.length ? h('ol', null, items.map(([key, label, n]) => h('li', { class: 'click', title: 'Filtrele', onclick: () => apply(key) },
      h('span', null, label), h('b', null, n)))) : h('div', { class: 'empty small' }, 'Kayıt yok'));
  const count = (key, label) => {
    const m = new Map();
    for (const r of list) {
      const k = key(r);
      if (k == null) continue;
      const cur = m.get(k) || [k, label(r), 0];
      cur[2]++;
      m.set(k, cur);
    }
    return [...m.values()].sort((a, b) => b[2] - a[2] || String(a[1]).localeCompare(String(b[1]), 'tr')).slice(0, 8);
  };

  function draw() {
    list = filtered();
    const today = new Date().toISOString().slice(0, 10);
    const week = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
    const parts = new Set(list.map(r => `${r.order_id}:${r.part_id}`));
    const repeated = new Set(list.filter(r => r.part_errors > 1).map(r => `${r.order_id}:${r.part_id}`));
    stats.set([
      { label: 'Hata kaydı', value: list.length, tone: list.length ? 'alert' : '' },
      { label: 'Bugün', value: list.filter(r => day(r.at) === today).length },
      { label: 'Son 7 gün', value: list.filter(r => day(r.at) >= week).length },
      { label: 'Hatalı parça', value: parts.size, sub: `${repeated.size} tekrarlayan` },
      { label: 'Hata veren yazıcı', value: new Set(list.map(r => r.printer_id).filter(Boolean)).size },
      { label: 'Resimli kayıt', value: list.filter(r => r.photo).length },
    ]);
    clear(tops,
      topBox('En çok hata veren yazıcılar', count(r => r.printer_id, printerLabel), k => { printer.value = String(k); draw(); }),
      topBox('En çok hata veren parçalar', count(r => r.part_id, r => r.part_id), k => { part.value = k; draw(); }),
      topBox('Hata kodları', count(r => codeKey(r.error_code), r => codeKey(r.error_code)), k => { code.value = k; draw(); }));
    if (!list.length) {
      clear(body, h('div', { class: 'empty' }, rows.length ? 'Filtreye uyan hata kaydı yok' : 'Henüz hata kaydı yok'));
    } else if (mode === 'card') {
      clear(body, h('div', { class: 'pe-grid' }, list.map(card)));
    } else {
      clear(body, h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Zaman', 'Sipariş', 'Parça', 'Yazıcı', 'Hata kodu', 'Açıklama', 'Kaydeden', 'Resim', 'Parça şimdi']
        .map(t => h('th', null, t)))),
      h('tbody', null, list.map(r => h('tr', { class: 'click', onclick: () => detail(r) },
        h('td', { class: 'nowrap' }, fmtDateTime(r.at)),
        h('td', null, h('b', null, r.order_code), r.company_name ? h('div', null, companyTag(r, 'xs')) : null),
        h('td', { class: 'mono' }, r.part_id, repeatBadge(r)),
        h('td', null, printerLabel(r)),
        h('td', null, h('b', null, r.error_code || '—')),
        h('td', { class: 'pe-note' }, r.note || h('span', { class: 'muted' }, '—')),
        h('td', null, r.user_name || '—'),
        h('td', null, r.photo ? h('img', { class: 'pe-thumb', src: fileUrl(r.photo, 256), alt: 'Hata resmi', loading: 'lazy' }) : h('span', { class: 'muted' }, 'Resim yok')),
        h('td', null, stateBadge(r)))))))));
    }
  }

  const repeatBadge = r => (r.part_errors > 1
    ? h('span', { class: 'badge red', style: { marginLeft: '6px' }, title: 'Bu parçanın toplam hata sayısı' }, `×${r.part_errors}`) : null);

  // Hata kartı: üstte hata resmi (yoksa "Resim yok"), altta sipariş / parça, hata kodu, açıklama, yazıcı ve kaydeden
  const card = r => h('div', { class: 'card pe-card', onclick: () => detail(r) },
    r.photo ? h('div', { class: 'pe-img' }, h('img', { src: fileUrl(r.photo, 512), alt: 'Hata resmi', loading: 'lazy' }))
      : h('div', { class: 'pe-img none' }, 'Resim yok'),
    h('div', { class: 'pe-body' },
      h('div', { class: 'pe-row' }, h('b', { class: 'mono' }, `${r.order_code} / ${r.part_id}`), repeatBadge(r), h('span', { class: 'grow' }), stateBadge(r)),
      r.company_name ? companyTag(r, 'xs') : null,
      h('div', { class: 'pe-code' }, r.error_code || 'Hata kodu yok'),
      h('div', { class: 'pe-desc' }, r.note || h('span', { class: 'muted' }, 'Açıklama yok')),
      h('div', { class: 'pe-meta' }, h('span', null, printerLabel(r)), h('span', null, r.user_name || '—'), h('span', null, fmtDateTime(r.at)))));

  const stateBadge = r => badge(PART_STATES, r.part_state);

  function detail(r) {
    modal({
      title: `${r.order_code} / ${r.part_id} — Hata`,
      body: h('div', { class: 'pe-detail' },
        r.photo ? h('a', { href: fileUrl(r.photo), target: '_blank', rel: 'noopener' },
          h('img', { class: 'pe-photo', src: fileUrl(r.photo, 1600), alt: 'Hata resmi' })) : h('div', { class: 'pe-img none' }, 'Resim yok'),
        h('dl', { class: 'kv' }, [
          ['Zaman', fmtDateTime(r.at)],
          ['Hata kodu', h('b', null, r.error_code || '—')],
          ['Açıklama', r.note || '—'],
          ['Sipariş', `${r.order_code}${r.queue_no ? ` (${r.queue_no})` : ''} · ${r.product_name || ''}`],
          r.company_name ? ['Firma', companyTag(r, 'xs')] : null,
          ['Parça', r.part_id],
          ['Yazıcı', printerLabel(r)],
          ['Kaydeden', r.user_name || '—'],
          ['Bu parçadaki hata sayısı', String(r.part_errors)],
          ['Parçanın şu anki durumu', stateBadge(r)],
        ].filter(Boolean).map(([k, v]) => [h('dt', null, k), h('dd', null, v)]))),
      actions: [
        canOpen ? { label: 'Siparişe Git', onClick: () => { location.hash = `#/production/${r.order_id}`; } } : null,
        { label: 'Kapat', class: 'primary' },
      ].filter(Boolean),
    });
  }

  csvBtn.addEventListener('click', () => {
    const cols = [['Zaman', r => fmtDateTime(r.at)], ['Sipariş', r => r.order_code], ['Firma', r => r.company_name || ''],
      ['Parça', r => r.part_id], ['Yazıcı', printerLabel], ['Hata kodu', r => r.error_code || ''], ['Açıklama', r => r.note || ''],
      ['Kaydeden', r => r.user_name || ''], ['Resim', r => (r.photo ? 'var' : 'yok')], ['Parça şimdi', r => r.part_state_text || '']];
    const cell = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = '﻿' + [cols.map(c => cell(c[0])).join(';'), ...list.map(r => cols.map(c => cell(c[1](r))).join(';'))].join('\r\n');
    const a = h('a', { href: URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' })),
      download: `uretim-hatalari-${new Date().toISOString().slice(0, 10)}.csv` });
    document.body.append(a);
    a.click();
    a.remove();
  });

  for (const el of [q, printer, part, order, person, code, photoOnly]) {
    el.addEventListener(el === q ? 'input' : 'change', draw);
  }
  const reset = h('button', { class: 'btn ghost', type: 'button', onclick: () => {
    for (const el of [q, printer, part, order, person, code]) el.value = '';
    photoOnly.checked = false;
    draw();
  } }, 'Temizle');
  draw();
  clear(view,
    pageHead('Üretim Hataları', { back: '#/tools', sub: 'Hata kodu, açıklama ve resim' }),
    moduleToolbar(modeSeg),
    stats,
    h('div', { class: 'filters' }, q, period.el, printer, part, order, person, code,
      h('label', { class: 'check' }, photoOnly, 'Yalnızca resimli'), reset, h('span', { class: 'spacer' }), csvBtn),
    tops,
    body);
}
