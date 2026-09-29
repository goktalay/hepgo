// Uyarı ayrıntı sayfası (#/alerts/<tür>) — tüm kullanıcılara açık, 5 sn'de bir yenilenir.
import { api } from '../api.js';
import { PRINTER_STATES, badge } from '../status.js';
import { clear, every, fmtDateTime, fmtDuration, h, pageHead, toast, toastError } from '../ui.js';

export async function render(view, params, ctx) {
  const key = params[0];
  const body = h('div');
  const head = h('div');
  const canOpen = ctx.user.modules.includes('production');

  async function load() {
    const d = await api.get(`/api/alerts/${encodeURIComponent(key)}`);
    clear(head, pageHead(d.title, {
      back: '#/', sub: h('span', null, h('span', { class: 'live-dot' }), ' 5 saniyede bir yenilenir · ', `${d.items.length} kayıt`),
    }), h('div', { class: `alert ${d.level === 'danger' ? 'err' : 'warn'} ${d.critical ? 'critical' : ''}` }, d.hint));
    if (!d.items.length) return clear(body, h('div', { class: 'card empty' }, 'Bu uyarı şu an yok — yazıcı durumları ile sistem uyumlu.'));
    const filePart = r => (r.file_parts?.length ? h('b', null, r.file_parts.join(', '))
      : h('span', { class: 'badge red' }, 'Tanımsız dosya'));
    const orderCell = r => (r.order_code
      ? (canOpen ? h('a', { href: `#/production/${r.order_id}` }, `${r.order_code} / ${r.part_id}`) : `${r.order_code} / ${r.part_id}`)
      : '—');
    const cols = {
      'printer-stale': ['Yazıcı', 'IP', 'Yazıcı durumu', 'Sistemde üretimde', 'Üretime başlama', 'Geçen süre', 'Yazıcıda bekleme', 'Son okuma'],
      'printer-outside': ['Yazıcı', 'IP', 'Yazıcı durumu', 'Basılan dosya', 'Dosyaya göre parça', 'İlerleme', 'Son okuma'],
      'printer-wrong-file': ['Yazıcı', 'IP', 'Yazıcı durumu', 'Sistemde üretimde', 'Beklenen dosya', 'Basılan dosya', 'Son okuma'],
      'printer-unrecorded-abort': ['Yazıcı', 'IP', 'Şu anki durum', 'Kesilen dosya', 'Kesildiğinde', 'Başlama', 'Kesilme', 'Son okuma', ''],
      'printer-error': ['Yazıcı', 'IP', 'Yazıcı durumu', 'Dosya', 'Sistemdeki parça', 'Son okuma'],
    }[d.key] || ['Yazıcı', 'IP', 'Durum'];
    const row = r => ({
      'printer-stale': [r.started_at ? fmtDateTime(r.started_at) : '—', fmtDuration(r.elapsed_seconds),
        r.waiting_seconds != null ? h('b', { style: { color: 'var(--danger)' } }, fmtDuration(r.waiting_seconds)) : h('span', { class: 'muted' }, 'bilinmiyor')],
      'printer-outside': [r.live_file || '—', filePart(r),
        r.live_progress != null ? `%${Math.round(r.live_progress)} (kalan %${100 - Math.round(r.live_progress)})` : '—'],
      'printer-wrong-file': [h('span', { class: 'mono' }, r.expected_file),
        h('span', null, h('span', { class: 'mono' }, r.live_file), ' ', filePart(r))],
      'printer-error': [r.live_file || '—', orderCell(r)],
      'printer-unrecorded-abort': [h('span', null, h('span', { class: 'mono' }, r.live_file || '—'), ' ', filePart(r)),
        h('span', null, r.live_progress != null ? `%${Math.round(r.live_progress)} basılmıştı` : '—',
          h('div', { class: 'small muted' }, r.end_state === 'HATA' ? 'hata ile durdu' : 'iptal edildi')),
        r.started_at ? fmtDateTime(r.started_at) : '—', h('b', { style: { color: 'var(--danger)' } }, fmtDateTime(r.ended_at))],
    }[d.key] || []);
    clear(body, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, cols.map(c => h('th', null, c)))),
      h('tbody', null, d.items.map(r => h('tr', null,
        h('td', null, h('b', null, r.name)),
        h('td', { class: 'mono' }, r.ip),
        h('td', null, badge(PRINTER_STATES, r.live_state)),
        ['printer-stale', 'printer-wrong-file'].includes(d.key) ? h('td', null, orderCell(r)) : null,
        row(r).map(v => h('td', { style: { whiteSpace: 'normal' } }, v)),
        h('td', { class: 'muted' }, fmtDateTime(r.last_seen)),
        d.key === 'printer-unrecorded-abort' ? h('td', null, h('button', { class: 'btn sm', onclick: async () => {
          try { await api.post(`/api/alerts/incidents/${r.incident_id}/ack`); toast('Uyarı kapatıldı'); load(); } catch (err) { toastError(err); }
        } }, 'Gördüm')) : null))))));
  }
  clear(view, head, body);
  await load();
  every(5000, () => load().catch(() => {}));
}
