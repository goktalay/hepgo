// Merkez › Destek Talepleri: firmalardan gelen talepler (ticket). Liste + canlı yazışma (15 sn'de bir yenilenir),
// durum / öncelik / atanan. Yazışma görünümü (threadView) firma tarafındaki Üyeliğim & Destek modülünde de kullanılır.
import { api } from '../api.js';
import { clear, every, fmtDateTime, h, matches, pageHead, selectInput, statStrip, toast, toastError } from '../ui.js';

export const STATUS = { acik: ['blue', 'Açık'], yanit_bekliyor: ['yellow', 'Yanıt bekliyor'], cozuldu: ['green', 'Çözüldü'], kapali: ['', 'Kapalı'] };
export const PRIORITY = { dusuk: ['', 'Düşük'], normal: ['blue', 'Normal'], yuksek: ['yellow', 'Yüksek'], acil: ['red', 'Acil'] };
export const CATEGORY = { teknik: 'Teknik', fatura: 'Fatura / ödeme', oneri: 'Öneri', egitim: 'Eğitim', diger: 'Diğer' };
export const badge = (map, k) => { const [c, l] = map[k] || ['', k]; return h('span', { class: `badge ${c}` }, l); };

// Yazışma: "mine" tarafı sağda (merkezde support, firmada company)
export function threadView(messages, mine) {
  return h('div', { class: 'tk-thread' }, messages.map(m => m.author_kind === 'system'
    ? h('div', { class: 'tk-sys' }, `${m.body} · ${fmtDateTime(m.created_at)}`)
    : h('div', { class: `tk-msg ${m.author_kind === mine ? 'mine' : ''}` },
      h('div', { class: 'tk-bubble' },
        h('div', { class: 'tk-who' }, m.author_name || (m.author_kind === 'support' ? 'Destek' : 'Firma'),
          m.author_kind === 'support' ? h('span', { class: 'tk-tag' }, 'Destek') : null),
        h('div', { class: 'tk-body' }, m.body)),
      h('small', { class: 'muted' }, fmtDateTime(m.created_at)))));
}

export function composer(onSend, placeholder = 'Yanıtınızı yazın…') {
  const ta = h('textarea', { class: 'input tk-input', rows: 3, placeholder });
  const btn = h('button', { class: 'btn primary', type: 'button' }, 'Gönder');
  const send = async () => {
    const v = ta.value.trim(); if (!v) return;
    btn.disabled = true;
    try { await onSend(v); ta.value = ''; } catch (e) { toastError(e); } finally { btn.disabled = false; }
  };
  btn.addEventListener('click', send);
  ta.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } });
  return h('div', { class: 'tk-compose' }, ta, h('div', { class: 'tk-compose-bar' }, h('small', { class: 'muted' }, 'Ctrl+Enter ile gönder'), btn));
}

export async function render(view, params) {
  if (params[0] && /^\d+$/.test(params[0])) return detail(view, Number(params[0]));
  return list(view);
}

async function list(view) {
  clear(view, pageHead('Destek Talepleri', { back: '#/', sub: 'Firmalardan gelen talepler · canlı yazışma' }),
    h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  const strip = statStrip();
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Talep, firma, kod ara…', style: { maxWidth: '240px' } });
  const st = selectInput(Object.entries(STATUS).map(([k, v]) => [k, v[1]]), { all: 'Tüm durumlar' });
  const openOnly = h('select', { class: 'input' }, h('option', { value: 'open' }, 'Açık olanlar'), h('option', { value: '' }, 'Hepsi'));
  const out = h('div');
  let data = { tickets: [], stats: {} };
  const load = async () => {
    try {
      const s = st.value || openOnly.value;
      data = await api.get(`/api/central/tickets${s ? `?status=${s}` : ''}`);
    } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    draw();
  };
  const draw = () => {
    const S = data.stats || {};
    strip.set([{ label: 'Açık', value: S.acik || 0, tone: S.acik ? 'alert' : '' }, { label: 'Yanıt bekliyor (firma)', value: S.yanit_bekliyor || 0 },
      { label: 'Çözüldü', value: S.cozuldu || 0, tone: 'ok' }, { label: 'Kapalı', value: S.kapali || 0, tone: 'muted' }]);
    const rows = data.tickets.filter(t => matches(q.value, t.subject, t.company_name, t.code, t.opened_by_name));
    clear(out, rows.length ? h('div', { class: 'tk-list' }, rows.map(t => h('a', { class: `card tk-row ${t.support_unread ? 'unread' : ''}`, href: `#/tickets/${t.id}` },
      h('div', { class: 'tk-row-main' },
        h('div', { class: 'tk-row-top' }, h('span', { class: 'mono small muted' }, t.code), t.support_unread ? h('span', { class: 'tk-dot', title: 'Yeni mesaj' }) : null,
          h('b', null, t.subject)),
        h('div', { class: 'small muted' }, `${t.company_name || t.slug} · ${t.opened_by_name || ''} · ${t.msg_count} mesaj`)),
      h('div', { class: 'tk-row-side' }, badge(PRIORITY, t.priority), badge(STATUS, t.status),
        h('small', { class: 'muted' }, fmtDateTime(t.updated_at)), t.assignee_name ? h('small', { class: 'muted' }, `→ ${t.assignee_name}`) : null))))
      : h('div', { class: 'card empty' }, 'Talep yok.'));
  };
  q.addEventListener('input', draw);
  [st, openOnly].forEach(el => el.addEventListener('change', load));
  clear(view, pageHead('Destek Talepleri', { back: '#/', sub: 'Firmalardan gelen talepler · canlı yazışma' }),
    strip, h('div', { class: 'filters' }, q, openOnly, st), out);
  await load();
  every(20000, load);
}

async function detail(view, id) {
  let staff = [];
  try { staff = await api.get('/api/central/staff'); } catch { /* */ }
  const box = h('div');
  clear(view, pageHead('Destek Talebi', { back: '#/tickets' }), box);
  let lastCount = -1;
  const load = async (force) => {
    let t;
    try { t = await api.get(`/api/central/tickets/${id}`); } catch (e) { return clear(box, h('div', { class: 'card empty' }, e.message)); }
    if (!force && t.messages.length === lastCount) return;   // değişiklik yoksa yeniden çizme (yazılan yanıt kaybolmasın)
    lastCount = t.messages.length;
    draw(t);
  };
  const upd = async (patch) => { try { draw(await api.put(`/api/central/tickets/${id}`, patch)); toast('Güncellendi'); } catch (e) { toastError(e); } };
  let comp = null;
  const draw = t => {
    const stSel = h('select', { class: 'input' }, Object.entries(STATUS).map(([k, v]) => h('option', { value: k, selected: t.status === k }, v[1])));
    const prSel = h('select', { class: 'input' }, Object.entries(PRIORITY).map(([k, v]) => h('option', { value: k, selected: t.priority === k }, v[1])));
    const asSel = h('select', { class: 'input' }, h('option', { value: '0' }, '— Atanmadı —'),
      staff.map(s => h('option', { value: s.id, selected: t.assignee_id === s.id }, s.full_name)));
    stSel.addEventListener('change', () => upd({ status: stSel.value }));
    prSel.addEventListener('change', () => upd({ priority: prSel.value }));
    asSel.addEventListener('change', () => upd({ assignee_id: Number(asSel.value) }));
    comp = comp || composer(async v => { draw(await api.post(`/api/central/tickets/${id}/messages`, { body: v })); lastCount = -1; });
    clear(box, h('div', { class: 'tk-detail' },
      h('section', { class: 'card card-pad tk-main' },
        h('div', { class: 'tk-head' }, h('span', { class: 'mono muted' }, t.code), h('h2', null, t.subject),
          h('div', { class: 'small muted' }, `${t.company_name} · ${t.opened_by_name || ''} ${t.opened_by_email ? `<${t.opened_by_email}>` : ''} · ${fmtDateTime(t.created_at)}`)),
        threadView(t.messages, 'support'),
        t.status === 'kapali' ? h('div', { class: 'card empty' }, 'Talep kapalı. Yeniden açmak için durumu değiştirin.') : comp),
      h('aside', { class: 'card card-pad tk-side' },
        h('label', { class: 'field' }, h('span', null, 'Durum'), stSel),
        h('label', { class: 'field' }, h('span', null, 'Öncelik'), prSel),
        h('label', { class: 'field' }, h('span', null, 'Atanan'), asSel),
        h('div', { class: 'small muted', style: { marginTop: '8px' } }, 'Kategori: ', CATEGORY[t.category] || t.category || '—'),
        t.status !== 'cozuldu' ? h('button', { class: 'btn', type: 'button', style: { marginTop: '12px', width: '100%' }, onclick: () => upd({ status: 'cozuldu' }) }, '✓ Çözüldü olarak işaretle') : null,
        h('p', { class: 'small muted', style: { marginTop: '12px' } }, 'Uzaktan destek gerekiyorsa firmadan “Ekranı Paylaş” linki isteyin; görüntülü görüşme ve müdahale aynı linkte.'))));
  };
  await load(true);
  every(15000, () => load(false));
}
