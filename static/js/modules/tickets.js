// Merkez › Destek Merkezi: firmalardan gelen destek talepleri (SLA, atama, iç not, dosya, toplu işlem), canlı destek sohbetleri
// (kuyruk, kabul, aktarma, talebe dönüştürme, ekran paylaşımı), destek ekibi ve çevrimiçi durum, hazır yanıtlar ve ayarlar.
// Ekran açıkken birkaç saniyede bir yoklanır: kişi çevrimiçi görünür, sırada bekleyen firma olunca sesli uyarı verilir.
import { api } from '../api.js';
import { playSound } from '../sounds.js';
import { avatar, clear, confirmDialog, every, field, fmtDate, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, segmented, statStrip, t, toast, toastError } from '../ui.js';
import { CATEGORY, PRESENCE, PRIORITY, STATUS, badge, chatMessage, composer, fmtM, formData, presenceDot, slaChip, starsOf, threadView, waitFor } from './supportkit.js';

export { CATEGORY, PRIORITY, STATUS, badge, composer, threadView };   // eski içe aktarmalar için

const SUBS = [['', 'Pano'], ['list', 'Talepler'], ['live', 'Canlı Destek'], ['team', 'Ekip'], ['canned', 'Hazır Yanıtlar'], ['settings', 'Ayarlar']];
const fileUrl = tok => `/api/central/support/files/${tok}`;
let lastWaiting = 0;

export async function render(view, params, ctx) {
  const [p0, p1] = [(params[0] || '').split('?')[0], params[1]];
  if (/^\d+$/.test(p0)) { location.replace(`#/tickets/t/${p0}`); return; }   // eski bağlantılar
  const sub = p0 === 't' ? 'list' : SUBS.some(s => s[0] === p0) ? p0 : '';
  const nav = segmented(SUBS, sub, v => { location.hash = v ? `#/tickets/${v}` : '#/tickets'; }, { tabs: true });
  const presence = h('select', { class: 'input dm-select', title: 'Durumunuz' }, Object.entries(PRESENCE).map(([k, [, l]]) => h('option', { value: k }, l)));
  presence.addEventListener('change', async () => { try { await api.put('/api/central/support/me/status', { status: presence.value }); toast(t('Durumunuz: {s}', { s: PRESENCE[presence.value][1] })); } catch (e) { toastError(e); } });
  const bar = h('div', { class: 'dm-livebar', hidden: true });
  const body = h('div', { class: 'dm-body' });
  clear(view, pageHead('Destek Merkezi', { back: '#/', sub: 'Firmalardan gelen talepler · canlı destek · destek ekibi', tabs: nav }),
    moduleToolbar(h('span', { class: 'dm-me' }, h('span', { class: 'small muted' }, 'Durumum'), presence)), bar, body);
  const pulse = async () => {
    let p;
    try { p = await api.get('/api/central/support/pulse'); } catch { return; }
    if (document.activeElement !== presence) presence.value = p.status;
    presence.className = `input dm-select ${p.status}`;
    const parts = [];
    if (p.waiting_chats) parts.push(h('span', null, '🟢 ', h('b', null, t('{n} firma', { n: p.waiting_chats })), ' canlı destekte sırada bekliyor'));
    if (p.my_chats_unread) parts.push(h('span', null, '💬 ', h('b', null, t('{n} yeni mesaj', { n: p.my_chats_unread })), ' sohbetlerinizde'));
    clear(bar, parts.length ? [...parts, sub !== 'live' ? h('a', { class: 'btn sm primary', href: '#/tickets/live' }, 'Canlı Destek’e git') : null] : null);
    bar.hidden = !parts.length;
    if (p.waiting_chats > lastWaiting) playSound('Kapı Zili', 0.6);
    lastWaiting = p.waiting_chats;
  };
  pulse();
  every(5000, pulse);
  if (p0 === 't' && /^\d+$/.test(p1 || '')) return ticketDetail(body, Number(p1), ctx);
  if (sub === 'list') return ticketList(body, params[0]);
  if (sub === 'live') return liveDesk(body, ctx, Number(p1) || null);
  if (sub === 'team') return team(body, ctx);
  if (sub === 'canned') return cannedView(body);
  if (sub === 'settings') return settingsView(body);
  return dashboard(body);
}

// ---------------- Pano ----------------
async function dashboard(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get('/api/central/support/overview'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const strip = statStrip();
  strip.set([
    { icon: 'chat', label: 'Canlı destekte bekleyen', value: d.waiting_chats, tone: d.waiting_chats ? 'alert' : '' },
    { icon: 'tickets', label: 'Açık talep', value: d.open, sub: t('{a} destek · {b} firma bekliyor', { a: d.awaiting_support, b: d.awaiting_company }) },
    { icon: 'warning', label: 'SLA aşan', value: d.overdue, tone: d.overdue ? 'alert' : 'ok' },
    { icon: 'person', label: 'Atanmamış', value: d.unassigned, tone: d.unassigned ? 'warn' : '' }]);
  const kpi = (label, value, sub, cls = '') => h('div', { class: `card dm-kpi ${cls}` }, h('small', null, label), h('b', null, value), sub ? h('span', { class: 'small muted' }, sub) : null);
  const chartBox = h('canvas', { height: 220 });
  const link = (href, ...kids) => h('a', { class: 'dm-link', href }, ...kids);
  clear(view, strip,
    h('div', { class: 'dm-kpis' },
      kpi('Ortalama ilk yanıt', d.avg_first_response_min === null ? '—' : fmtM(d.avg_first_response_min), 'son 30 gün'),
      kpi('Ortalama çözüm', d.avg_resolve_hours === null ? '—' : t('{n} saat', { n: d.avg_resolve_hours }), 'son 30 gün'),
      kpi('Memnuniyet', d.csat ? h('span', null, `${d.csat} `, h('span', { class: 'sk-star1' }, '★')) : '—', t('{n} değerlendirme', { n: d.csat_count })),
      kpi('SLA uyumu', d.sla_rate === null ? '—' : `%${d.sla_rate}`, 'ilk yanıt hedefinde', d.sla_rate !== null && d.sla_rate < 80 ? 'warn' : '')),
    h('div', { class: 'dm-grid' },
      h('section', { class: 'card card-pad dm-chart' }, h('h3', null, 'Son 14 gün'), chartBox),
      h('section', { class: 'card card-pad' }, h('div', { class: 'dm-sec-h' }, h('h3', null, 'Destek ekibi'), link('#/tickets/team', 'Ekibi yönet →')),
        d.staff.length ? h('div', { class: 'dm-team-mini' }, d.staff.map(s => h('div', { class: 'dm-tm' },
          h('span', { class: 'dm-av' }, avatar(s, 34), presenceDot(s.presence)),
          h('div', { class: 'grow' }, h('b', null, s.full_name), h('small', { class: 'muted' }, s.title || PRESENCE[s.presence][1])),
          h('span', { class: 'small muted', title: 'Aktif sohbet / kapasite · açık talep' }, `💬 ${s.active_chats}/${s.max_chats} · 🎫 ${s.open_tickets}`))))
          : h('p', { class: 'small muted' }, 'Henüz destek personeli yok. Ekip sekmesinden ekleyin.')),
      h('section', { class: 'card card-pad' }, h('div', { class: 'dm-sec-h' }, h('h3', null, 'En çok açık talebi olan firmalar'), link('#/tickets/list?view=open', 'Tüm açıklar →')),
        d.top_companies.length ? h('div', { class: 'dm-rank' }, d.top_companies.map(c => link(`#/tickets/list?view=open&slug=${encodeURIComponent(c.slug)}`,
          h('span', { class: 'grow' }, c.company_name || c.slug), h('b', null, c.n)))) : h('p', { class: 'small muted' }, 'Açık talep yok 🎉')),
      h('section', { class: 'card card-pad' }, h('h3', null, 'Kategoriler (30 gün)'),
        d.categories.length ? h('div', { class: 'dm-bars' }, d.categories.map(c => {
          const max = Math.max(...d.categories.map(x => x.n));
          return h('div', { class: 'dm-bar' }, h('span', null, CATEGORY[c.category] || c.category || '—'),
            h('i', { style: `--w:${Math.round(c.n / max * 100)}%` }), h('b', null, c.n));
        })) : h('p', { class: 'small muted' }, 'Kayıt yok'))));
  const { loadChart, theme } = await import('./reports.js');
  const Chart = await loadChart().catch(() => null);
  if (!Chart || !chartBox.isConnected) return;
  const th = theme();
  new Chart(chartBox, {
    type: 'bar',
    data: { labels: d.trend.map(x => x.day.slice(8, 10) + '.' + x.day.slice(5, 7)),
      datasets: [{ label: 'Yeni talep', data: d.trend.map(x => x.created), backgroundColor: '#3b82f6', borderRadius: 4 },
        { label: 'Çözülen', data: d.trend.map(x => x.resolved), backgroundColor: '#22c55e', borderRadius: 4 },
        { label: 'Canlı sohbet', data: d.trend.map(x => x.chats), type: 'line', borderColor: '#f59e0b', backgroundColor: '#f59e0b', tension: 0.3 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: th.text } } },
      scales: { x: { ticks: { color: th.muted }, grid: { display: false } }, y: { beginAtZero: true, ticks: { color: th.muted, precision: 0 }, grid: { color: th.grid } } } },
  });
}

// ---------------- Talepler ----------------
const VIEWS = [['mine', 'Bana atanan'], ['unassigned', 'Atanmamış'], ['awaiting', 'Destek yanıtı bekleyen'], ['company', 'Firma yanıtı bekleyen'],
  ['overdue', 'SLA aşan'], ['open', 'Tüm açık'], ['resolved', 'Çözülen / kapalı'], ['all', 'Tümü']];

async function ticketList(view, raw) {
  const qs = new URLSearchParams((raw || '').split('?')[1] || '');
  let cur = qs.get('view') || 'open';
  const slug = qs.get('slug') || '';
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Konu, firma, kod, kişi ara…' });
  const cat = h('select', { class: 'input' }, h('option', { value: '' }, 'Tüm kategoriler'), Object.entries(CATEGORY).map(([k, v]) => h('option', { value: k }, v)));
  const pri = h('select', { class: 'input' }, h('option', { value: '' }, 'Tüm öncelikler'), Object.entries(PRIORITY).map(([k, v]) => h('option', { value: k }, v[1])));
  // Kaynak: firmalar (federasyon) / Mastertool araçları (Hesabım › Destek) / SIMUMAV oyunu (simumav.com "Sorun bildir"; etiket SIMUMAV)
  const src = h('select', { class: 'input', 'aria-label': 'Kaynak' }, [['', 'Tüm kaynaklar'], ['company', 'Firmalar'], ['mastertool', 'Mastertool'], ['simumav', 'SIMUMAV']].map(([k, v]) => h('option', { value: k }, v)));
  src.value = qs.get('source') || '';
  const side = h('nav', { class: 'card dm-views' });
  const out = h('div', { class: 'dm-tlist' });
  const bulkBar = h('div', { class: 'dm-bulk', hidden: true });
  const sel = new Set();
  let data = { tickets: [], counts: {} }, staff = [];
  try { staff = (await api.get('/api/central/support/staff')).staff; } catch { /* */ }
  const load = async () => {
    try {
      data = await api.get(`/api/central/support/tickets?view=${cur}&category=${cat.value}&priority=${pri.value}&slug=${encodeURIComponent(slug)}&source=${src.value}`);
    } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    draw();
  };
  const drawBulk = () => {
    bulkBar.hidden = !sel.size;
    if (!sel.size) return;
    const asg = h('select', { class: 'input' }, h('option', { value: '' }, 'Ata…'), h('option', { value: '0' }, '— Atamayı kaldır —'), staff.map(s => h('option', { value: s.id }, s.full_name)));
    const st = h('select', { class: 'input' }, h('option', { value: '' }, 'Durum…'), Object.entries(STATUS).map(([k, v]) => h('option', { value: k }, v[1])));
    const pr = h('select', { class: 'input' }, h('option', { value: '' }, 'Öncelik…'), Object.entries(PRIORITY).map(([k, v]) => h('option', { value: k }, v[1])));
    const apply = async () => {
      const body = { ids: [...sel] };
      if (asg.value !== '') body.assignee_id = Number(asg.value);
      if (st.value) body.status = st.value;
      if (pr.value) body.priority = pr.value;
      try { await api.post('/api/central/support/tickets/bulk', body); toast(t('{n} talep güncellendi', { n: sel.size })); sel.clear(); load(); } catch (e) { toastError(e); }
    };
    clear(bulkBar, h('b', null, t('{n} seçili', { n: sel.size })), asg, st, pr, h('button', { class: 'btn sm primary', type: 'button', onclick: apply }, 'Uygula'),
      h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { sel.clear(); draw(); } }, 'Seçimi kaldır'));
  };
  const draw = () => {
    clear(side, VIEWS.map(([k, l]) => h('button', { type: 'button', class: `dm-view ${k === cur ? 'on' : ''} ${k === 'overdue' && data.counts.overdue ? 'alert' : ''}`,
      onclick: () => { cur = k; sel.clear(); history.replaceState(null, '', `#/tickets/list?view=${k}`); load(); } },
      h('span', { class: 'grow' }, l), h('b', null, data.counts[k] ?? ''))));
    const rows = data.tickets.filter(x => matches(q.value, x.subject, x.company_name, x.code, x.opened_by_name));
    clear(out, slug ? h('div', { class: 'dm-filter-note' }, t('Firma: {s}', { s: rows[0]?.company_name || slug }), ' ', h('a', { href: `#/tickets/list?view=${cur}` }, '× filtreyi kaldır')) : null,
      rows.length ? rows.map(x => {
        const cb = h('input', { type: 'checkbox', checked: sel.has(x.id), onclick: e => e.stopPropagation(),
          onchange: e => { e.target.checked ? sel.add(x.id) : sel.delete(x.id); drawBulk(); } });
        return h('a', { class: `card dm-trow ${x.support_unread ? 'unread' : ''} pr-${x.priority}`, href: `#/tickets/t/${x.id}` },
          h('span', { class: 'dm-cb', onclick: e => e.stopPropagation() }, cb),
          h('div', { class: 'dm-trow-main' },
            h('div', { class: 'dm-trow-top' }, h('span', { class: 'mono small muted' }, x.code), x.support_unread ? h('span', { class: 'tk-dot', title: 'Yeni firma mesajı' }) : null,
              x.channel === 'chat' ? h('span', { class: 'sk-tagchip', title: 'Canlı destekten' }, '💬') : null,
              x.channel === 'mastertool' ? h('span', { class: 'sk-tagchip', title: x.tags === 'SIMUMAV' ? 'SIMUMAV oyuncusu (simumav.com › Sorun bildir)' : 'Mastertool kullanıcısı (Hesabım › Destek)' }, x.tags || 'Mastertool') : null, h('b', null, x.subject)),
            h('div', { class: 'small muted' }, `${x.company_name || x.slug} · ${x.opened_by_name || '—'} · ${CATEGORY[x.category] || x.category || ''} · ${t('{n} mesaj', { n: x.msg_count })}`)),
          h('div', { class: 'dm-trow-side' },
            h('div', { class: 'dm-badges' }, badge(PRIORITY, x.priority), badge(STATUS, x.status)),
            slaChip(x),
            h('small', { class: 'muted' }, x.assignee_name ? `→ ${x.assignee_name}` : 'Atanmadı', ' · ', fmtDateTime(x.updated_at))));
      }) : h('div', { class: 'card empty' }, 'Bu görünümde talep yok.'));
    drawBulk();
  };
  q.addEventListener('input', draw);
  [cat, pri, src].forEach(el => el.addEventListener('change', load));
  clear(view, h('div', { class: 'dm-tickets' }, side, h('div', { class: 'dm-tmain' }, h('div', { class: 'filters' }, q, cat, pri, src), bulkBar, out)));
  await load();
  every(20000, load);
}

async function ticketDetail(view, id) {
  let staff = [], canned = [];
  try { [staff, canned] = await Promise.all([api.get('/api/central/support/staff').then(r => r.staff), api.get('/api/central/support/canned')]); } catch { /* */ }
  const box = h('div');
  clear(view, h('a', { class: 'small dm-back', href: '#/tickets/list' }, '← Talepler'), box);
  let lastCount = -1, comp = null, cur = null;
  const load = async force => {
    let tk;
    try { tk = await api.get(`/api/central/support/tickets/${id}`); } catch (e) { return clear(box, h('div', { class: 'card empty' }, e.message)); }
    if (!force && tk.messages.length === lastCount && tk.status === cur?.status) return;   // değişiklik yoksa yeniden çizme (yazılan yanıt kaybolmasın)
    lastCount = tk.messages.length;
    draw(tk);
  };
  const upd = async patch => { try { draw(await api.put(`/api/central/support/tickets/${id}`, patch)); toast('Güncellendi'); } catch (e) { toastError(e); } };
  const draw = tk => {
    cur = tk;
    const sel = (opts, value, onChange, empty) => {
      const s = h('select', { class: 'input' }, empty ? h('option', { value: '0' }, empty) : null, opts.map(([k, l]) => h('option', { value: k, selected: String(value) === String(k) }, l)));
      s.addEventListener('change', () => onChange(s.value));
      return s;
    };
    comp = comp || composer(async ({ body, files, internal, extra }) => {
      const fd = formData({ body, internal: internal ? '1' : '', status: extra === 'solve' ? 'cozuldu' : '' }, files);
      draw(await api.post(`/api/central/support/tickets/${id}/messages`, fd)); lastCount = -1;
      toast(internal ? 'İç not eklendi' : extra === 'solve' ? 'Yanıt gönderildi, talep çözüldü' : 'Yanıt gönderildi');
    }, { note: true, canned, extra: { key: 'solve', label: 'Gönder ve çözüldü yap' }, rows: 4 });
    const m = tk.member || {};
    const PAYL = { odendi: ['green', 'Ödendi'], kismi: ['yellow', 'Kısmi'], bekliyor: ['', 'Bekliyor'], gecikti: ['red', 'Gecikmiş'], ucretsiz: ['', 'Ücretsiz'] };
    const tl = (label, at, cls = '') => h('div', { class: `dm-tl ${cls}` }, h('span', null, label), h('b', null, at ? fmtDateTime(at) : '—'));
    clear(box, h('div', { class: 'tk-detail dm-detail' },
      h('section', { class: 'card card-pad tk-main' },
        h('div', { class: 'tk-head' }, h('div', { class: 'dm-head-row' }, h('span', { class: 'mono muted' }, tk.code), badge(STATUS, tk.status), badge(PRIORITY, tk.priority), slaChip(tk),
          tk.chat_code ? h('span', { class: 'sk-tagchip' }, `💬 ${tk.chat_code}`) : null),
          h('h2', null, tk.subject),
          h('div', { class: 'small muted' }, `${tk.company_name} · ${tk.opened_by_name || ''}${tk.opened_by_email ? ` <${tk.opened_by_email}>` : ''} · ${fmtDateTime(tk.created_at)}`)),
        threadView(tk.messages, 'support', fileUrl),
        tk.rating ? h('div', { class: 'dm-rated' }, 'Firma değerlendirmesi: ', starsOf(tk.rating), tk.rating_note ? ` — “${tk.rating_note}”` : '') : null,
        tk.status === 'kapali' ? h('div', { class: 'card empty' }, 'Talep kapalı. Yeniden açmak için durumu değiştirin.') : comp),
      h('aside', { class: 'tk-side dm-side' },
        h('section', { class: 'card card-pad' },
          field('Durum', sel(Object.entries(STATUS).map(([k, v]) => [k, v[1]]), tk.status, v => upd({ status: v }))),
          field('Öncelik', sel(Object.entries(PRIORITY).map(([k, v]) => [k, v[1]]), tk.priority, v => upd({ priority: v }))),
          field('Kategori', sel(Object.entries(CATEGORY), tk.category, v => upd({ category: v }))),
          field('Atanan', sel(staff.map(s => [s.id, s.full_name]), tk.assignee_id || 0, v => upd({ assignee_id: Number(v) }), '— Atanmadı —')),
          (() => { const tg = h('input', { class: 'input', value: tk.tags || '', placeholder: 'ör. rapor, yazıcı' }); tg.addEventListener('change', () => upd({ tags: tg.value })); return field('Etiketler', tg); })(),
          tk.status !== 'cozuldu' ? h('button', { class: 'btn success', type: 'button', style: 'width:100%;margin-top:8px', onclick: () => upd({ status: 'cozuldu' }) }, '✓ Çözüldü olarak işaretle') : null),
        h('section', { class: 'card card-pad' }, h('h4', { class: 'dm-h4' }, 'SLA'),
          tl('Oluşturuldu', tk.created_at), tl('İlk yanıt hedefi', tk.due_at, tk.sla?.first === 'late' ? 'late' : ''),
          tl('İlk yanıt', tk.first_response_at, tk.sla?.first === 'late_met' ? 'late' : tk.first_response_at ? 'ok' : ''),
          tl('Çözüm hedefi', tk.resolve_due_at, tk.sla?.resolve === 'late' ? 'late' : ''), tl('Çözüldü', tk.resolved_at, tk.resolved_at ? 'ok' : '')),
        h('section', { class: 'card card-pad dm-firm' }, h('h4', { class: 'dm-h4' }, 'Firma'),
          h('b', null, m.name || tk.company_name), m.url ? h('div', null, h('a', { class: 'small', href: m.url, target: '_blank', rel: 'noopener' }, m.url.replace(/^https?:\/\//, ''))) : null,
          h('dl', { class: 'dm-kv' }, h('dt', null, 'Paket'), h('dd', null, m.package || '—'), h('dt', null, 'Bu ay ödeme'), h('dd', null, m.pay_status ? badge(PAYL, m.pay_status) : '—'),
            h('dt', null, 'Yönetici'), h('dd', null, m.master || '—'), h('dt', null, 'Telefon'), h('dd', null, m.phone ? h('a', { href: `tel:${m.phone}` }, m.phone) : '—'),
            h('dt', null, 'Açık talep'), h('dd', null, m.open_tickets ?? '—')),
          m.suspended ? h('div', { class: 'dm-warn' }, 'Firma hesabı pasif') : null,
          m.recent?.length > 1 ? h('div', { class: 'dm-recent' }, h('small', { class: 'muted' }, 'Son talepler'), m.recent.filter(r => r.id !== tk.id).map(r =>
            h('a', { href: `#/tickets/t/${r.id}` }, h('span', { class: 'mono' }, r.code), ' ', r.subject, ' ', badge(STATUS, r.status)))) : null))));
  };
  await load(true);
  every(15000, () => load(false));
}

// ---------------- Canlı Destek ----------------
async function liveDesk(view, ctx, openId) {
  let staff = [], canned = [];
  try { [staff, canned] = await Promise.all([api.get('/api/central/support/staff').then(r => r.staff), api.get('/api/central/support/canned')]); } catch { /* */ }
  const queue = h('aside', { class: 'card lc-queue' });
  const pane = h('section', { class: 'card lc-pane' });
  const info = h('aside', { class: 'card card-pad lc-info' });
  clear(view, h('div', { class: 'lc-desk' }, queue, pane, info));
  let curId = openId, live = { waiting: [], mine: [], others: [], recent: [] };
  const item = (c, kind) => h('a', { class: `lc-item ${c.id === curId ? 'on' : ''} ${kind}`, href: `#/tickets/live/${c.id}`, onclick: e => { e.preventDefault(); open(c.id); } },
    h('div', { class: 'lc-item-top' }, h('b', { class: 'grow' }, c.company_name), c.support_unread && kind === 'mine' ? h('span', { class: 'lc-unread' }, c.support_unread) : null,
      h('small', { class: 'muted' }, kind === 'waiting' ? `⏳ ${waitFor(c.created_at)}` : (c.last_msg_at || '').slice(11, 16))),
    h('div', { class: 'small muted lc-item-sub' }, c.typing ? h('i', null, 'yazıyor…') : (c.topic || c.last_body || '')),
    kind === 'waiting' ? h('button', { class: 'btn sm primary', type: 'button', onclick: async e => { e.preventDefault(); e.stopPropagation(); await accept(c.id); } }, 'Sohbeti al') : null,
    kind === 'others' ? h('small', { class: 'muted' }, `→ ${c.assignee_name}`) : null);
  const drawQueue = () => clear(queue,
    h('div', { class: 'lc-qh' }, h('b', null, 'Bekleyenler'), h('span', { class: `lc-count ${live.waiting.length ? 'hot' : ''}` }, live.waiting.length)),
    live.waiting.length ? live.waiting.map(c => item(c, 'waiting')) : h('div', { class: 'lc-none' }, 'Sırada bekleyen yok'),
    h('div', { class: 'lc-qh' }, h('b', null, 'Sohbetlerim'), h('span', { class: 'lc-count' }, live.mine.length)),
    live.mine.length ? live.mine.map(c => item(c, 'mine')) : h('div', { class: 'lc-none' }, 'Aktif sohbetiniz yok'),
    live.others.length ? [h('div', { class: 'lc-qh' }, h('b', null, 'Diğer aktif sohbetler'), h('span', { class: 'lc-count' }, live.others.length)), live.others.map(c => item(c, 'others'))] : null,
    live.recent.length ? [h('div', { class: 'lc-qh' }, h('b', null, 'Son biten'))].concat(live.recent.slice(0, 8).map(c => h('a', { class: `lc-item ended ${c.id === curId ? 'on' : ''}`, href: `#/tickets/live/${c.id}`,
      onclick: e => { e.preventDefault(); open(c.id); } }, h('div', { class: 'lc-item-top' }, h('b', { class: 'grow' }, c.company_name), c.rating ? starsOf(c.rating) : null),
      h('div', { class: 'small muted lc-item-sub' }, `${c.status === 'missed' ? 'Kaçırıldı → talep' : c.assignee_name || ''} · ${fmtDateTime(c.ended_at)}`)))) : null);
  const loadLive = async () => {
    try { live = await api.get('/api/central/support/live'); } catch { return; }
    drawQueue();
  };
  const accept = async cid => {
    try { await api.post(`/api/central/support/chats/${cid}/accept`, {}); toast('Sohbeti aldınız'); await loadLive(); open(cid); } catch (e) { toastError(e); loadLive(); }
  };

  // ---- açık sohbet
  let chat = null, lastId = 0, msgsEl = null, typingEl = null, comp = null, lastTyping = 0;
  async function open(cid) {
    curId = cid; lastId = 0; chat = null;
    history.replaceState(null, '', `#/tickets/live/${cid}`);
    drawQueue();
    clear(pane, h('div', { class: 'loading' }, 'Açılıyor…'));
    let c;
    try { c = await api.get(`/api/central/support/chats/${cid}`); } catch (e) { return clear(pane, h('div', { class: 'card empty' }, e.message)); }
    chat = c;
    msgsEl = h('div', { class: 'lc-msgs' });
    typingEl = h('div', { class: 'lc-typing', hidden: true }, h('span'), h('span'), h('span'), ' yazıyor');
    const mine = c.assignee_id === ctx.user.id;
    comp = c.status === 'active' && mine ? composer(async ({ body, files }) => {
      await api.post(`/api/central/support/chats/${cid}/messages`, formData({ body }, files)); poll();
    }, { canned, enterSends: true, rows: 2, placeholder: 'Mesajınızı yazın…', onTyping: () => {
      if (Date.now() - lastTyping > 3000) { lastTyping = Date.now(); api.post(`/api/central/support/chats/${cid}/typing`, {}).catch(() => {}); }
    } }) : null;
    const acts = [];
    if (c.status === 'waiting') acts.push(h('button', { class: 'btn primary', type: 'button', onclick: () => accept(cid) }, 'Sohbeti al'));
    if (c.status === 'active' && mine) {
      const tr = h('select', { class: 'input', title: 'Aktar' }, h('option', { value: '' }, 'Aktar…'), staff.filter(s => s.id !== ctx.user.id).map(s => h('option', { value: s.id }, `${s.full_name} · ${PRESENCE[s.presence][1]}`)));
      tr.addEventListener('change', async () => {
        if (!tr.value) return;
        try { await api.post(`/api/central/support/chats/${cid}/transfer`, { to: Number(tr.value) }); toast('Sohbet aktarıldı'); loadLive(); open(cid); } catch (e) { toastError(e); }
      });
      acts.push(tr, h('button', { class: 'btn', type: 'button', onclick: () => end(cid) }, 'Sohbeti bitir'));
    }
    if (!c.ticket_id) acts.push(h('button', { class: 'btn', type: 'button', onclick: () => toTicket(cid) }, '🎫 Talebe dönüştür'));
    else acts.push(h('a', { class: 'btn', href: `#/tickets/t/${c.ticket_id}` }, `🎫 ${c.ticket_code || 'Talep'}`));
    clear(pane,
      h('div', { class: 'lc-head' }, h('div', { class: 'grow' }, h('b', null, c.company_name), h('div', { class: 'small muted' },
        `${c.code} · ${c.user_name || ''} · ${c.topic || CATEGORY[c.category] || ''}`)),
        h('span', { class: `badge ${{ waiting: 'yellow', active: 'green', ended: '', missed: 'red' }[c.status]}` }, { waiting: 'Bekliyor', active: 'Aktif', ended: 'Bitti', missed: 'Kaçırıldı' }[c.status]),
        h('div', { class: 'lc-acts' }, acts)),
      msgsEl, typingEl,
      comp || h('div', { class: 'lc-closed small muted' }, c.status === 'active' ? t('Bu sohbet {n} kişisinde.', { n: c.assignee_name || '—' }) : c.status === 'waiting' ? 'Yazmak için sohbeti alın.' : 'Sohbet sona erdi.'));
    append(c.messages);
    drawInfo(c);
    comp?.focus();
  }
  const append = msgs => {
    if (!msgsEl) return;
    const atBottom = msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 80;
    msgs.forEach(m => { msgsEl.append(chatMessage(m, 'support', fileUrl)); lastId = Math.max(lastId, m.id); });
    if (atBottom || msgs.length) msgsEl.scrollTop = msgsEl.scrollHeight;
  };
  const drawInfo = c => {
    const m = c.member || {};
    clear(info, h('h4', { class: 'dm-h4' }, 'Görüşülen'), h('b', null, c.user_name || '—'), c.user_email ? h('div', null, h('a', { class: 'small', href: `mailto:${c.user_email}` }, c.user_email)) : null,
      h('dl', { class: 'dm-kv' }, h('dt', null, 'Başladı'), h('dd', null, fmtDateTime(c.created_at)), h('dt', null, 'Bekleme'),
        h('dd', null, c.accepted_at ? fmtM((new Date(c.accepted_at) - new Date(c.created_at)) / 60000) : c.status === 'waiting' ? waitFor(c.created_at) : '—'),
        h('dt', null, 'Kategori'), h('dd', null, CATEGORY[c.category] || '—'), c.rating ? [h('dt', null, 'Puan'), h('dd', null, starsOf(c.rating))] : null),
      m.name ? [h('h4', { class: 'dm-h4' }, 'Firma'), h('b', null, m.name), h('dl', { class: 'dm-kv' }, h('dt', null, 'Paket'), h('dd', null, m.package || '—'),
        h('dt', null, 'Telefon'), h('dd', null, m.phone || '—'), h('dt', null, 'Açık talep'), h('dd', null, m.open_tickets ?? '—')),
      m.recent?.length ? h('div', { class: 'dm-recent' }, h('small', { class: 'muted' }, 'Son talepler'), m.recent.map(r => h('a', { href: `#/tickets/t/${r.id}` },
        h('span', { class: 'mono' }, r.code), ' ', r.subject))) : null] : null);
  };
  const poll = async () => {
    if (!curId || !chat) return;
    let c;
    try { c = await api.get(`/api/central/support/chats/${curId}?after=${lastId}`); } catch { return; }
    if (c.status !== chat.status || c.assignee_id !== chat.assignee_id) { open(curId); return; }
    append(c.messages);
    if (typingEl) typingEl.hidden = !c.typing;
  };
  const end = async cid => {
    if (!await confirmDialog('Sohbeti bitir', 'Sohbet sonlandırılsın mı? Firma sohbeti değerlendirebilir.', { okLabel: 'Bitir' })) return;
    try { await api.post(`/api/central/support/chats/${cid}/end`, {}); loadLive(); open(cid); } catch (e) { toastError(e); }
  };
  const toTicket = cid => {
    const subj = h('input', { class: 'input', value: chat?.topic || '' });
    const pr = h('select', { class: 'input' }, Object.entries(PRIORITY).map(([k, v]) => h('option', { value: k, selected: k === 'normal' }, v[1])));
    modal({ title: 'Talebe dönüştür', body: h('div', null, h('p', { class: 'small muted' }, 'Sohbetin tüm yazışması talebe aktarılır; firma takibini Destek Taleplerim’den yapar.'),
      field('Konu', subj), field('Öncelik', pr)),
    actions: [{ label: 'Vazgeç' }, { label: 'Talep oluştur', class: 'primary', onClick: async () => {
      const r = await api.post(`/api/central/support/chats/${cid}/ticket`, { subject: subj.value, priority: pr.value });
      toast('Talep oluşturuldu'); open(cid); return r;
    } }] });
  };
  await loadLive();
  if (curId) open(curId);
  else clear(pane, h('div', { class: 'lc-empty' }, h('div', null, '💬'), h('b', null, 'Canlı destek'), h('p', { class: 'small muted' },
    'Soldan bir sohbet seçin. Sırada bekleyen firma olduğunda sesli uyarı alırsınız; durumunuz “Müsait” iken yeni sohbetler size otomatik de atanabilir.')),
  clear(info, h('p', { class: 'small muted' }, 'Sohbet seçildiğinde firma bilgileri burada görünür.')));
  every(4000, loadLive);
  every(2000, poll);
}

// ---------------- Ekip ----------------
async function team(view, ctx) {
  let d;
  try { d = await api.get('/api/central/support/staff'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const card = s => h('div', { class: 'card dm-staff' },
    h('div', { class: 'dm-staff-h' }, h('span', { class: 'dm-av' }, avatar(s, 48), presenceDot(s.presence)),
      h('div', { class: 'grow' }, h('b', null, s.full_name), h('div', { class: 'small muted' }, s.title || 'Destek personeli'), h('div', { class: 'small' }, PRESENCE[s.presence][1],
        s.presence === 'offline' && s.status && s.status !== 'offline' ? h('span', { class: 'muted' }, ' (ekran kapalı)') : null))),
    h('div', { class: 'dm-skills' }, (s.skills.length ? s.skills : ['tümü']).map(k => h('span', { class: 'sk-tagchip' }, CATEGORY[k] || 'Tüm kategoriler'))),
    h('div', { class: 'dm-staff-stats' },
      h('div', null, h('b', null, `${s.active_chats}/${s.max_chats}`), h('small', null, 'aktif sohbet')),
      h('div', null, h('b', null, s.open_tickets), h('small', null, 'açık talep')),
      h('div', null, h('b', null, s.resolved_month), h('small', null, 'bu ay çözülen')),
      h('div', null, h('b', null, s.chats_month), h('small', null, 'bu ay sohbet')),
      h('div', null, h('b', null, s.csat ? `${s.csat} ★` : '—'), h('small', null, t('{n} puan', { n: s.csat_count })))),
    d.manager ? h('div', { class: 'dm-staff-acts' }, h('button', { class: 'btn sm', type: 'button', onclick: () => edit(s) }, 'Düzenle'),
      h('button', { class: 'btn sm danger', type: 'button', onclick: async () => {
        if (!await confirmDialog('Ekipten çıkar', t('{n} destek ekibinden çıkarılsın mı? Kullanıcı hesabı ve geçmiş kayıtlar silinmez; aktif sohbetleri sıraya döner.', { n: s.full_name }), { okLabel: 'Çıkar', danger: true })) return;
        try { await api.del(`/api/central/support/staff/${s.id}`); toast('Ekipten çıkarıldı'); team(view, ctx); } catch (e) { toastError(e); }
      } }, 'Ekipten çıkar')) : null);
  const skillPick = sel => {
    const set = new Set(sel);
    return { el: h('div', { class: 'dm-skillpick' }, Object.entries(CATEGORY).map(([k, v]) => {
      const cb = h('input', { type: 'checkbox', checked: set.has(k), onchange: e => { e.target.checked ? set.add(k) : set.delete(k); } });
      return h('label', null, cb, v);
    })), get: () => [...set] };
  };
  const edit = s => {
    const title = h('input', { class: 'input', value: s.title || '' });
    const max = h('input', { class: 'input', type: 'number', min: 1, max: 10, value: s.max_chats });
    const sk = skillPick(s.skills);
    modal({ title: s.full_name, body: h('div', null, field('Ünvan', title), field('Aynı anda en çok canlı sohbet', max),
      h('div', { class: 'field' }, h('span', null, 'Uzmanlık (otomatik atamada öncelik; boşsa tüm kategoriler)'), sk.el)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      await api.put(`/api/central/support/staff/${s.id}`, { title: title.value, max_chats: Number(max.value) || 3, skills: sk.get() });
      toast('Kaydedildi'); team(view, ctx);
    } }] });
  };
  const add = () => {
    let mode = 'new';
    const name = h('input', { class: 'input', placeholder: 'Ad Soyad' });
    const user = h('input', { class: 'input', type: 'email', placeholder: 'destek@firma.com' });
    const pw = h('input', { class: 'input', type: 'text', placeholder: 'İlk girişte değiştirilecek' });
    const title = h('input', { class: 'input', placeholder: 'ör. Teknik Destek Uzmanı' });
    const existing = h('select', { class: 'input' }, d.candidates.map(c => h('option', { value: c.id }, `${c.full_name} · ${c.username}`)));
    const sk = skillPick([]);
    const newBox = h('div', null, h('div', { class: 'row' }, field('Ad soyad', name), field('Kullanıcı adı (e-posta)', user)), field('Geçici şifre', pw));
    const exBox = h('div', { hidden: true }, field('Kullanıcı', existing));
    modal({ title: 'Destek personeli ekle', wide: true, body: h('div', null,
      segmented([['new', 'Yeni hesap'], ['existing', 'Mevcut kullanıcı']], 'new', v => { mode = v; newBox.hidden = v !== 'new'; exBox.hidden = v === 'new'; }),
      h('div', { style: 'height:10px' }), newBox, exBox, field('Ünvan', title),
      h('div', { class: 'field' }, h('span', null, 'Uzmanlık'), sk.el),
      h('p', { class: 'small muted' }, 'Personele “Merkez Destek” rolü verilir: Destek Merkezi’ni kullanır; Üyelik, ödeme ve SMS ekranlarını görmez.')),
    actions: [{ label: 'Vazgeç' }, { label: 'Ekle', class: 'primary', onClick: async () => {
      const body = mode === 'new' ? { full_name: name.value, username: user.value, password: pw.value } : { user_id: Number(existing.value) };
      await api.post('/api/central/support/staff', { ...body, title: title.value, skills: sk.get() });
      toast('Destek ekibine eklendi', 'success'); team(view, ctx);
    } }] });
  };
  clear(view, d.manager ? h('div', { class: 'filters' }, h('span', { class: 'spacer' }), h('button', { class: 'btn primary', type: 'button', onclick: add }, '＋ Destek personeli ekle')) : null,
    d.staff.length ? h('div', { class: 'dm-staff-grid' }, d.staff.map(card))
      : h('div', { class: 'card empty' }, 'Henüz destek ekibi yok. “Destek personeli ekle” ile yeni hesap açın ya da mevcut bir kullanıcıyı ekibe alın.'),
    h('p', { class: 'small muted' }, 'Durum (Müsait / Meşgul / Molada / Çevrimdışı) her kişinin kendi seçimidir; Destek Merkezi ekranı kapalı olan çevrimdışı görünür. Otomatik atama yalnızca müsait ve kapasitesi dolmamış kişilere yapılır.'));
}

// ---------------- Hazır yanıtlar ----------------
async function cannedView(view) {
  let rows;
  try { rows = await api.get('/api/central/support/canned'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const edit = c => {
    const title = h('input', { class: 'input', value: c?.title || '' });
    const sc = h('input', { class: 'input', value: c?.shortcut || '', placeholder: 'ör. selam' });
    const body = h('textarea', { class: 'input', rows: 7 }, c?.body || '');
    modal({ title: c ? 'Hazır yanıtı düzenle' : 'Yeni hazır yanıt', wide: true,
      body: h('div', null, h('div', { class: 'row' }, field('Başlık', title), field('Kısayol (/kısayol + boşluk)', sc)), field('Metin', body)),
      actions: [c ? { label: 'Sil', class: 'danger', onClick: async () => { await api.del(`/api/central/support/canned/${c.id}`); toast('Silindi'); cannedView(view); } } : null,
        'spacer', { label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
          const b = { title: title.value, shortcut: sc.value, body: body.value };
          if (c) await api.put(`/api/central/support/canned/${c.id}`, b); else await api.post('/api/central/support/canned', b);
          toast('Kaydedildi'); cannedView(view);
        } }].filter(Boolean) });
  };
  clear(view, h('div', { class: 'filters' }, h('span', { class: 'small muted' }, 'Yanıt kutusunda “⚡ Hazır yanıt” listesinden ya da /kısayol yazıp boşlukla eklenir.'), h('span', { class: 'spacer' }),
    h('button', { class: 'btn primary', type: 'button', onclick: () => edit(null) }, '＋ Hazır yanıt')),
  rows.length ? h('div', { class: 'dm-canned' }, rows.map(c => h('button', { class: 'card dm-cn', type: 'button', onclick: () => edit(c) },
    h('div', { class: 'dm-cn-h' }, h('b', null, c.title), c.shortcut ? h('span', { class: 'mono small muted' }, `/${c.shortcut}`) : null),
    h('p', { class: 'small muted' }, c.body.length > 180 ? `${c.body.slice(0, 180)}…` : c.body))))
    : h('div', { class: 'card empty' }, 'Henüz hazır yanıt yok.'));
}

// ---------------- Ayarlar ----------------
async function settingsView(view) {
  let d;
  try { d = await api.get('/api/central/support/settings'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const s = d.settings, ro = !d.manager;
  const num = (v, step = 0.25) => h('input', { class: 'input', type: 'number', min: step, step, value: v, disabled: ro });
  const first = {}, resolve = {};
  const slaRows = Object.entries(PRIORITY).map(([k, [, l]]) => { first[k] = num(s.sla_first[k]); resolve[k] = num(s.sla_resolve[k]); return h('tr', null, h('td', null, badge(PRIORITY, k)), h('td', null, first[k]), h('td', null, resolve[k])); });
  const DAYS = [[1, 'Pzt'], [2, 'Sal'], [3, 'Çar'], [4, 'Per'], [5, 'Cum'], [6, 'Cmt'], [7, 'Paz']];
  const days = new Set(s.hours.days);
  const dayBox = h('div', { class: 'dm-days' }, DAYS.map(([n, l]) => h('label', null, h('input', { type: 'checkbox', checked: days.has(n), disabled: ro, onchange: e => { e.target.checked ? days.add(n) : days.delete(n); } }), l)));
  const start = h('input', { class: 'input', type: 'time', value: s.hours.start, disabled: ro });
  const endT = h('input', { class: 'input', type: 'time', value: s.hours.end, disabled: ro });
  const auto = h('input', { type: 'checkbox', checked: s.auto_assign, disabled: ro });
  const wait = h('input', { class: 'input', type: 'number', min: 1, max: 240, value: s.chat_wait_minutes, disabled: ro });
  const ta = (v, rows = 3) => h('textarea', { class: 'input', rows, disabled: ro }, v || '');
  const inp = (v, ph = '') => h('input', { class: 'input', value: v || '', placeholder: ph, disabled: ro });
  const f = { welcome: ta(s.welcome), offline_msg: ta(s.offline_msg), contact_email: inp(s.contact_email, 'destek@hepgo.com'), contact_phone: inp(s.contact_phone, '0850 …'),
    bank_name: inp(s.bank_name), iban: inp(s.iban, 'TR..'), account_name: inp(s.account_name), payment_note: ta(s.payment_note, 2) };
  const save = h('button', { class: 'btn primary', type: 'button', hidden: ro, onclick: async () => {
    const body = { sla_first: Object.fromEntries(Object.entries(first).map(([k, el]) => [k, Number(el.value)])),
      sla_resolve: Object.fromEntries(Object.entries(resolve).map(([k, el]) => [k, Number(el.value)])),
      hours: { days: [...days].sort(), start: start.value, end: endT.value }, auto_assign: auto.checked, chat_wait_minutes: Number(wait.value) || 10,
      ...Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value])) };
    try { await api.put('/api/central/support/settings', body); toast('Destek ayarları kaydedildi', 'success'); } catch (e) { toastError(e); }
  } }, 'Kaydet');
  clear(view, ro ? h('div', { class: 'card card-pad small muted' }, 'Ayarları yalnızca destek yöneticisi (Sistem Yöneticisi) değiştirebilir.') : null,
    h('div', { class: 'dm-settings' },
      h('section', { class: 'card card-pad' }, h('h3', null, 'SLA hedefleri (saat)'), h('p', { class: 'small muted' }, 'Önceliğe göre ilk yanıt ve çözüm hedefi. Firma, talebini açarken ilk yanıt hedefini görür.'),
        h('table', { class: 'table dm-sla' }, h('thead', null, h('tr', null, h('th', null, 'Öncelik'), h('th', null, 'İlk yanıt'), h('th', null, 'Çözüm'))), h('tbody', null, slaRows))),
      h('section', { class: 'card card-pad' }, h('h3', null, 'Canlı destek'),
        h('div', { class: 'field' }, h('span', null, 'Çalışma günleri'), dayBox), h('div', { class: 'row' }, field('Başlangıç', start), field('Bitiş', endT)),
        h('label', { class: 'set-toggle' }, auto, h('span', null, h('b', null, 'Otomatik atama'), h('small', null, 'Yeni talep ve sohbetler müsait, uzmanlığı uygun ve en az yüklü kişiye atanır'))),
        field('Sohbet en çok kaç dakika beklesin? (sonra talebe dönüşür)', wait),
        field('Karşılama mesajı', f.welcome), field('Çevrimdışı mesajı', f.offline_msg)),
      h('section', { class: 'card card-pad' }, h('h3', null, 'Firmalara görünen iletişim'), h('div', { class: 'row' }, field('Destek e-postası', f.contact_email), field('Destek telefonu', f.contact_phone))),
      h('section', { class: 'card card-pad' }, h('h3', null, 'Ödeme bilgileri'), h('p', { class: 'small muted' }, 'Firmalar Üyeliğim › Ödemelerim ekranında görür ve ödeme bildirimi yapar.'),
        h('div', { class: 'row' }, field('Banka', f.bank_name), field('Hesap sahibi', f.account_name)), field('IBAN', f.iban), field('Ödeme notu', f.payment_note))),
    h('div', { class: 'set-actions' }, save));
}
