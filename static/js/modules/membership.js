// Firma paneli › Üyeliğim & Destek: merkezle (Veilox) ilişkiniz — paket ve modüller, aylık ücret ve ödeme geçmişi,
// destek talepleri (aç, yazış, takip et). Veriler merkezdedir; burası güvenli federasyon bağlantısıyla okur/yazar.
import { api } from '../api.js';
import { clear, every, field, fmtDate, fmtDateTime, h, modal, pageHead, segmented, statStrip, toast } from '../ui.js';
import { CATEGORY, PRIORITY, STATUS, badge, composer, threadView } from './tickets.js';

const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 0 }).format(n || 0);
const SUBS = [['overview', 'Üyeliğim'], ['tickets', 'Destek Taleplerim'], ['payments', 'Ödemelerim']];
const PAY = { odendi: ['green', 'Ödendi'], kismi: ['yellow', 'Kısmi ödendi'], bekliyor: ['', 'Ödeme bekleniyor'], gecikti: ['red', 'Gecikmiş'], ucretsiz: ['', 'Ücretsiz'] };

export async function render(view, params, ctx) {
  if (params[0] === 'tickets' && /^\d+$/.test(params[1] || '')) return ticketDetail(view, Number(params[1]));
  const sub = SUBS.some(s => s[0] === params[0]) ? params[0] : 'overview';
  const nav = segmented(SUBS, sub, v => { location.hash = `#/uyelik/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Üyeliğim & Destek', { back: '#/', sub: 'Paketiniz, ödemeleriniz ve bizimle destek kayıtlarınız', tabs: nav }), body);
  if (sub === 'tickets') return ticketsView(body, ctx);
  if (sub === 'payments') return paymentsView(body);
  return overview(body);
}

async function overview(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get('/api/membership'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const [pc, pl] = PAY[d.pay_status] || ['', d.pay_status];
  const strip = statStrip();
  strip.set([{ label: 'Paket', value: d.package?.name || '—' }, { label: 'Aylık ücret', value: d.fee ? money(d.fee) : 'Ücretsiz' },
    { label: `Bu ay (${d.period})`, value: pl, tone: d.pay_status === 'gecikti' ? 'alert' : d.pay_status === 'odendi' ? 'ok' : '' },
    { label: 'Hesap', value: d.suspended ? 'Pasif' : 'Aktif', tone: d.suspended ? 'alert' : 'ok' }]);
  const c = d.company || {};
  clear(view,
    d.suspended ? h('div', { class: 'card card-pad mb-alert' }, h('b', null, 'Hesabınız pasif durumda. '), d.suspend_reason || '', ' Kullanıcılarınız giriş yapamıyor; ödeme ve destek için bizimle iletişime geçin.') : null,
    strip,
    h('section', { class: 'card card-pad' }, h('h3', null, c.name || '—'),
      h('dl', { class: 'sys-kv' }, h('dt', null, 'Adres'), h('dd', null, c.url ? h('a', { href: c.url, target: '_blank', rel: 'noopener' }, c.url) : '—'),
        h('dt', null, 'Kurulum'), h('dd', null, c.mode === 'offline' ? 'Kendi sunucunuz' : 'Bulut (Veilox)'),
        h('dt', null, 'Firma yöneticisi'), h('dd', null, c.master_username || '—'),
        h('dt', null, 'Üyelik başlangıcı'), h('dd', null, c.provisioned_at ? fmtDate(c.provisioned_at) : (c.created_at ? fmtDate(c.created_at) : '—')),
        h('dt', null, 'Bu ay ödeme'), h('dd', null, h('span', { class: `badge ${pc}` }, pl))),
      d.package?.description ? h('p', { class: 'small muted' }, d.package.description) : null),
    h('section', { class: 'card card-pad' }, h('div', { class: 'mb-sec-h' }, h('h3', null, 'Yardıma mı ihtiyacınız var?'),
      h('a', { class: 'btn primary', href: '#/uyelik/tickets' }, 'Destek talebi aç')),
      h('p', { class: 'small muted' }, 'Talepleriniz doğrudan Veilox destek ekibine iletilir; yanıtlar burada ve bildirimlerinizde görünür. Ekranınızda birlikte bakmamız gerekirse kullanıcı menüsünden “Ekranı Paylaş” ile link oluşturup talebe ekleyebilirsiniz.')));
}

async function ticketsView(view, ctx) {
  const out = h('div');
  const load = async () => {
    let rows;
    try { rows = await api.get('/api/membership/tickets'); } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    clear(out, rows.length ? h('div', { class: 'tk-list' }, rows.map(t => h('a', { class: `card tk-row ${t.company_unread ? 'unread' : ''}`, href: `#/uyelik/tickets/${t.id}` },
      h('div', { class: 'tk-row-main' }, h('div', { class: 'tk-row-top' }, h('span', { class: 'mono small muted' }, t.code),
        t.company_unread ? h('span', { class: 'tk-dot', title: 'Yeni yanıt' }) : null, h('b', null, t.subject)),
        h('div', { class: 'small muted' }, `${CATEGORY[t.category] || t.category || ''} · ${t.msg_count} mesaj`)),
      h('div', { class: 'tk-row-side' }, badge(STATUS, t.status), h('small', { class: 'muted' }, fmtDateTime(t.updated_at)))))) :
      h('div', { class: 'card empty' }, 'Henüz destek talebiniz yok.'));
  };
  const newBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => newTicket(load) }, '＋ Yeni Destek Talebi');
  clear(view, h('div', { class: 'filters' }, h('span', { class: 'spacer' }), newBtn), out);
  await load();
  every(30000, load);
}

function newTicket(done) {
  const subj = h('input', { class: 'input', maxlength: 200, placeholder: 'Kısaca konu' });
  const cat = h('select', { class: 'input' }, Object.entries(CATEGORY).map(([k, v]) => h('option', { value: k }, v)));
  const pr = h('select', { class: 'input' }, Object.entries(PRIORITY).map(([k, v]) => h('option', { value: k, selected: k === 'normal' }, v[1])));
  const body = h('textarea', { class: 'input', rows: 6, placeholder: 'Sorunu ya da isteğinizi ayrıntılı yazın (hangi ekran, ne yaptınız, ne oldu)…' });
  modal({ title: 'Yeni destek talebi', wide: true,
    body: h('div', null, field('Konu', subj), h('div', { class: 'row' }, field('Kategori', cat), field('Öncelik', pr)), field('Açıklama', body)),
    actions: [{ label: 'Vazgeç' }, { label: 'Gönder', class: 'primary', onClick: async () => {
      if (!subj.value.trim() || !body.value.trim()) throw new Error('Konu ve açıklama gerekli');
      const r = await api.post('/api/membership/tickets', { subject: subj.value, body: body.value, category: cat.value, priority: pr.value });
      toast(`Talebiniz alındı (${r.code})`); done?.();
    } }] });
}

async function ticketDetail(view, id) {
  const box = h('div');
  clear(view, pageHead('Destek Talebi', { back: '#/uyelik/tickets' }), box);
  let last = -1, comp = null;
  const draw = t => {
    comp = comp || composer(async v => { draw(await api.post(`/api/membership/tickets/${id}/messages`, { body: v })); last = -1; });
    clear(box, h('section', { class: 'card card-pad tk-main' },
      h('div', { class: 'tk-head' }, h('span', { class: 'mono muted' }, t.code), h('h2', null, t.subject),
        h('div', null, badge(STATUS, t.status), ' ', badge(PRIORITY, t.priority))),
      threadView(t.messages, 'company'),
      t.status === 'kapali' ? h('div', { class: 'card empty' }, 'Bu talep kapatıldı. Yeni bir konu için yeni talep açın.') : comp));
  };
  const load = async (force) => {
    let t;
    try { t = await api.get(`/api/membership/tickets/${id}`); } catch (e) { return clear(box, h('div', { class: 'card empty' }, e.message)); }
    if (!force && t.messages.length === last) return;
    last = t.messages.length; draw(t);
  };
  await load(true);
  every(15000, () => load(false));
}

async function paymentsView(view) {
  let d;
  try { d = await api.get('/api/membership'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  clear(view, h('section', { class: 'card card-pad' }, h('h3', null, 'Aylık ücret: ', d.fee ? money(d.fee) : 'Ücretsiz')),
    d.payments.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Dönem', 'Ödeme tarihi', 'Tutar', 'Yöntem', 'Not'].map(x => h('th', null, x)))),
      h('tbody', null, d.payments.map(p => h('tr', null, h('td', null, p.period), h('td', null, fmtDate(p.paid_at)),
        h('td', { class: 'num' }, money(p.amount)), h('td', null, p.method || '—'), h('td', { class: 'muted' }, p.note || '—'))))))) :
      h('div', { class: 'card empty' }, 'Kayıtlı ödeme yok.'));
}
