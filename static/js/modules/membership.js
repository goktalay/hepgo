// Firma paneli › Üyeliğim & Destek: HEPGO ile ilişkiniz tek ekranda — üyelik ve paket, destek ekibine canlı destek (ekran
// paylaşımıyla), destek talepleri (dosya ekli, değerlendirme), ödeme takibi ve ödeme bildirimi, üyelik sözleşmeleri.
// Veriler merkezdedir; burası güvenli federasyon bağlantısıyla okur / yazar. Aktif canlı sohbet başka sayfadayken de köşede görünür.
import { api } from '../api.js';
import { moduleName } from '../modulenames.js';
import { clear, every, field, fmtDate, fmtDateTime, h, modal, pageHead, segmented, statStrip, t, toast, toastError } from '../ui.js';
import { CATEGORY, PRIORITY, STATUS_FIRM, badge, chatMessage, composer, fmtM, formData, ratingBox, starsOf, threadView } from './supportkit.js';
import { docView, printDoc, proofRows } from './contractdoc.js';

const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 0 }).format(n || 0);
const money2 = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' }).format(n || 0);
// AÇIK BETA: üyelik ekranında ücret tutarları gizlenir (fiyatlandırma politikası belirlenince false yapılır).
const HIDE_PRICES = true;
const showFee = f => !HIDE_PRICES && f;
const SUBS = [['overview', 'Genel Bakış'], ['live', 'Canlı Destek'], ['tickets', 'Destek Taleplerim'], ['payments', 'Ödemelerim'], ['contracts', 'Sözleşmelerim']];
const PAY = { odendi: ['green', 'Ödendi'], kismi: ['yellow', 'Kısmi ödendi'], bekliyor: ['', 'Ödeme bekleniyor'], gecikti: ['red', 'Gecikmiş'], ucretsiz: ['', 'Ücretsiz'] };
const NOTICE = { bekliyor: ['yellow', 'Onay bekliyor'], onaylandi: ['green', 'Onaylandı'], reddedildi: ['red', 'Reddedildi'] };
const DAYN = ['', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
const fileUrl = tok => `/api/membership/files/${tok}`;
const hoursText = hs => {
  const d = [...(hs?.days || [])].sort();
  const span = d.length && d.every((x, i) => !i || x === d[i - 1] + 1) ? `${DAYN[d[0]]}–${DAYN[d[d.length - 1]]}` : d.map(x => DAYN[x]).join(', ');
  return `${span} ${hs?.start || ''}–${hs?.end || ''}`;
};

export async function render(view, params, ctx) {
  const p0 = (params[0] || '').split('?')[0];
  const subs = SUBS;
  const sub = subs.some(s => s[0] === p0) ? p0 : 'overview';
  const nav = segmented(subs, sub, v => { location.hash = `#/uyelik/${v}`; }, { tabs: true });
  const body = h('div', { class: 'mb2' });
  clear(view, pageHead('Üyeliğim & Destek', { back: '#/', sub: 'Paketiniz, destek ekibimiz, ödemeleriniz ve sözleşmeleriniz', tabs: nav }), body);
  if (sub === 'tickets' && /^\d+$/.test(params[1] || '')) return ticketDetail(body, Number(params[1]));
  if (sub === 'contracts' && /^\d+$/.test(params[1] || '')) return contractPage(body, Number(params[1]), ctx);
  if (sub === 'live') return liveView(body, ctx, Number(params[1]) || null);
  if (sub === 'tickets') return ticketsView(body);
  if (sub === 'payments') return paymentsView(body);
  if (sub === 'contracts') return contractsList(body);
  return overview(body, ctx);
}

const loading = view => clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));

function supportCard(st, ctx, compact) {
  if (!st) return null;
  const on = st.online > 0;
  return h('section', { class: `card mb2-support ${on ? 'on' : 'off'} ${compact ? 'compact' : ''}` },
    h('div', { class: 'mb2-sup-h' }, h('span', { class: 'mb2-pulse' }), h('div', { class: 'grow' },
      h('b', null, on ? 'Destek ekibimiz çevrimiçi' : 'Destek ekibimiz şu an çevrimdışı'),
      h('small', null, on ? (st.avg_first_response_min !== null ? t('Ortalama ilk yanıt süremiz {m}', { m: fmtM(st.avg_first_response_min) }) : 'Size hemen yardımcı olalım')
        : t('Çalışma saatleri: {h} · mesajınızı bırakın, talep olarak kaydedelim', { h: hoursText(st.hours) })))),
    h('div', { class: 'mb2-sup-acts' },
      h('a', { class: 'btn primary', href: '#/uyelik/live' }, on ? '💬 Canlı destek' : '✉️ Mesaj bırak'),
      h('button', { class: 'btn', type: 'button', onclick: () => newTicket(st, () => { location.hash = '#/uyelik/tickets'; }) }, '🎫 Destek talebi aç'),
      h('button', { class: 'btn', type: 'button', onclick: () => import('./screenshare.js').then(m => m.startScreenShare(ctx)) }, '🖥️ Ekranımı paylaş')),
    st.contact?.email || st.contact?.phone ? h('div', { class: 'mb2-contact small' },
      st.contact.phone ? h('a', { href: `tel:${st.contact.phone.replace(/\s/g, '')}` }, `📞 ${st.contact.phone}`) : null,
      st.contact.email ? h('a', { href: `mailto:${st.contact.email}` }, `✉️ ${st.contact.email}`) : null) : null);
}

async function overview(view, ctx) {
  loading(view);
  let d, tickets = [], ct = null;
  try { [d, tickets, ct] = await Promise.all([api.get('/api/membership'), api.get('/api/membership/tickets').catch(() => []), api.get('/api/membership/contracts').catch(() => null)]); }
  catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const c = d.company || {};
  const [, pl] = PAY[d.pay_status] || ['', d.pay_status];
  const strip = statStrip();
  strip.set([{ icon: 'uyelik', label: 'Paket', value: d.package?.name || '—' },
    { icon: 'finance', label: t('Bu ay ({p})', { p: d.period }), value: pl, tone: d.pay_status === 'gecikti' ? 'alert' : d.pay_status === 'odendi' ? 'ok' : '' },
    { icon: 'tickets', label: 'Açık destek talebi', value: d.open_tickets ?? 0, sub: d.unread_tickets ? t('{n} yeni yanıt', { n: d.unread_tickets }) : null, tone: d.unread_tickets ? 'alert' : '' },
    { icon: 'documents', label: 'Onay bekleyen sözleşme', value: ct?.pending ?? 0, tone: ct?.pending ? 'alert' : 'ok' }]);
  const recent = tickets.slice(0, 5);
  const mods = d.package?.modules || c.modules || [];
  clear(view,
    d.suspended ? h('div', { class: 'card card-pad mb-alert' }, h('b', null, 'Hesabınız pasif durumda. '), d.suspend_reason || '', ' Kullanıcılarınız giriş yapamıyor; ödeme ve destek için bizimle iletişime geçin.') : null,
    h('section', { class: 'card mb2-hero' },
      h('div', { class: 'mb2-hero-l' },
        h('div', { class: 'mb2-hero-badges' }, h('span', { class: `mb2-state ${d.suspended ? 'off' : 'on'}` }, d.suspended ? 'Pasif' : '● Aktif üyelik'),
          d.package ? h('span', { class: 'mb2-pkg' }, d.package.name) : null),
        h('h2', null, c.name || ctx.meta?.company || '—'),
        h('div', { class: 'mb2-hero-meta' },
          c.url ? h('a', { href: c.url, target: '_blank', rel: 'noopener' }, c.url.replace(/^https?:\/\//, '')) : null,
          h('span', null, c.mode === 'offline' ? 'Kendi sunucunuzda' : 'HEPGO Bulut'),
          c.provisioned_at || c.created_at ? h('span', null, t('Üyelik: {d}', { d: fmtDate(c.provisioned_at || c.created_at) })) : null),
        d.package?.description ? h('p', { class: 'small muted' }, d.package.description) : null),
      supportCard(d.support, ctx, true)),
    strip,
    h('div', { class: 'mb2-grid' },
      h('section', { class: 'card card-pad' }, h('div', { class: 'mb-sec-h' }, h('h3', null, 'Son destek taleplerim'), h('a', { class: 'small', href: '#/uyelik/tickets' }, 'Tümü →')),
        recent.length ? h('div', { class: 'mb2-tlist' }, recent.map(x => h('a', { class: `mb2-trow ${x.company_unread ? 'unread' : ''}`, href: `#/uyelik/tickets/${x.id}` },
          h('span', { class: 'mono small muted' }, x.code), x.company_unread ? h('span', { class: 'tk-dot' }) : null, h('span', { class: 'grow' }, x.subject),
          badge(STATUS_FIRM, x.status)))) : h('p', { class: 'small muted' }, 'Henüz destek talebiniz yok. Sorunuz olduğunda canlı destekten ya da talep açarak bize ulaşın.')),
      h('section', { class: 'card card-pad' }, h('div', { class: 'mb-sec-h' }, h('h3', null, 'Ödeme takvimi'), h('a', { class: 'small', href: '#/uyelik/payments' }, 'Ödemelerim →')),
        showFee(d.fee) ? h('div', { class: 'mb2-months' }, [...(d.months || [])].reverse().map(m => h('div', { class: `mb2-m ${m.status}`, title: `${m.period} · ${(PAY[m.status] || [])[1] || m.status}${m.paid ? ` · ${money2(m.paid)}` : ''}` },
          h('b', null, m.period.slice(5)), h('small', null, m.period.slice(0, 4))))) : h('p', { class: 'small muted' }, HIDE_PRICES ? 'Açık beta döneminde ücretsiz.' : 'Paketiniz ücretsiz.'),
        showFee(d.fee) ? h('div', { class: 'mb2-legend small muted' }, ...['odendi', 'kismi', 'bekliyor', 'gecikti'].map(k => h('span', { class: `mb2-lg ${k}` }, PAY[k][1]))) : null),
      mods.length ? h('section', { class: 'card card-pad mb2-mods' }, h('h3', null, t('Paketinizdeki modüller ({n})', { n: mods.length })),
        h('div', { class: 'mb2-chips' }, mods.map(m => h('span', { class: 'sk-tagchip', title: m }, t(moduleName(m)))))) : null));
}

// ---------------- Destek talepleri ----------------
function newTicket(st, done) {
  const subj = h('input', { class: 'input', maxlength: 200, placeholder: 'Kısaca konu (ör. Aylık rapor açılmıyor)' });
  const cat = h('select', { class: 'input' }, Object.entries(CATEGORY).map(([k, v]) => h('option', { value: k }, v)));
  const pr = h('select', { class: 'input' }, Object.entries(PRIORITY).map(([k, v]) => h('option', { value: k, selected: k === 'normal' }, v[1])));
  const sla = h('small', { class: 'hint' });
  const drawSla = () => { const hrs = st?.sla_first?.[pr.value]; sla.textContent = hrs ? t('Bu öncelikte ilk yanıt hedefimiz: {m}', { m: fmtM(hrs * 60) }) : ''; };
  pr.addEventListener('change', drawSla); drawSla();
  const comp = composer(async () => {}, { rows: 6, noSend: true, placeholder: 'Sorunu ya da isteğinizi ayrıntılı yazın: hangi ekran, ne yaptınız, ne oldu? Ekran görüntüsünü buraya yapıştırabilirsiniz.' });
  modal({ title: 'Yeni destek talebi', wide: true,
    body: h('div', null, field('Konu', subj), h('div', { class: 'row' }, field('Kategori', cat), h('div', { class: 'field' }, h('span', null, 'Öncelik'), pr, sla)),
      h('div', { class: 'field' }, h('span', null, 'Açıklama ve ekler'), comp)),
    actions: [{ label: 'Vazgeç' }, 'spacer', { label: 'Talebi gönder', class: 'primary', onClick: async () => {
      if (!subj.value.trim() || !comp.getText().trim()) throw new Error('Konu ve açıklama gerekli');
      const r = await api.post('/api/membership/tickets', formData({ subject: subj.value, body: comp.getText(), category: cat.value, priority: pr.value }, comp.getFiles()));
      toast(t('Talebiniz alındı ({c})', { c: r.code }), 'success'); done?.();
    } }] });
  subj.focus();
}

async function ticketsView(view) {
  let filter = 'open', rows = [], st = null;
  const out = h('div');
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Taleplerimde ara…' });
  const draw = () => {
    const term = q.value.trim().toLocaleLowerCase('tr');
    const list = rows.filter(x => (filter === 'all' || (filter === 'open' ? !['cozuldu', 'kapali'].includes(x.status) : ['cozuldu', 'kapali'].includes(x.status)))
      && (!term || `${x.code} ${x.subject}`.toLocaleLowerCase('tr').includes(term)));
    clear(out, list.length ? h('div', { class: 'tk-list' }, list.map(x => h('a', { class: `card tk-row ${x.company_unread ? 'unread' : ''}`, href: `#/uyelik/tickets/${x.id}` },
      h('div', { class: 'tk-row-main' }, h('div', { class: 'tk-row-top' }, h('span', { class: 'mono small muted' }, x.code),
        x.company_unread ? h('span', { class: 'tk-dot', title: 'Yeni yanıt' }) : null, x.channel === 'chat' ? h('span', { class: 'sk-tagchip' }, '💬') : null, h('b', null, x.subject)),
        h('div', { class: 'small muted' }, `${CATEGORY[x.category] || x.category || ''} · ${t('{n} mesaj', { n: x.msg_count })} · ${t('açıldı {d}', { d: fmtDate(x.created_at) })}`)),
      h('div', { class: 'tk-row-side' }, badge(STATUS_FIRM, x.status), x.rating ? starsOf(x.rating) : null, h('small', { class: 'muted' }, fmtDateTime(x.updated_at))))))
      : h('div', { class: 'card empty' }, filter === 'open' ? 'Açık talebiniz yok.' : 'Talep bulunamadı.'));
  };
  const load = async () => {
    try { rows = await api.get('/api/membership/tickets'); } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    draw();
  };
  try { st = await api.get('/api/membership/support-status'); } catch { /* */ }
  q.addEventListener('input', draw);
  clear(view, h('div', { class: 'filters' }, segmented([['open', 'Açık'], ['done', 'Çözülen'], ['all', 'Tümü']], filter, v => { filter = v; draw(); }), q,
    h('span', { class: 'spacer' }), h('button', { class: 'btn primary', type: 'button', onclick: () => newTicket(st, load) }, '＋ Yeni destek talebi')), out);
  await load();
  every(30000, load);
}

async function ticketDetail(view, id) {
  const box = h('div');
  clear(view, h('a', { class: 'small dm-back', href: '#/uyelik/tickets' }, '← Destek Taleplerim'), box);
  let last = -1, lastStatus = '', comp = null;
  const draw = tk => {
    comp = comp || composer(async ({ body, files }) => {
      draw(await api.post(`/api/membership/tickets/${id}/messages`, formData({ body }, files))); last = -1;
    }, { placeholder: 'Yanıtınızı yazın… (dosya ekleyebilir, ekran görüntüsü yapıştırabilirsiniz)' });
    const done = ['cozuldu', 'kapali'].includes(tk.status);
    clear(box, h('section', { class: 'card card-pad tk-main' },
      h('div', { class: 'tk-head' }, h('div', { class: 'dm-head-row' }, h('span', { class: 'mono muted' }, tk.code), badge(STATUS_FIRM, tk.status), badge(PRIORITY, tk.priority)),
        h('h2', null, tk.subject),
        h('div', { class: 'small muted' }, t('Açıldı {d}', { d: fmtDateTime(tk.created_at) }), tk.assignee_name ? ` · ${t('İlgilenen: {n}', { n: tk.assignee_name })}${tk.assignee_title ? ` (${tk.assignee_title})` : ''}` : '',
          !tk.first_response_at && tk.due_at && !done ? ` · ${t('İlk yanıt hedefi: {d}', { d: fmtDateTime(tk.due_at) })}` : '')),
      threadView(tk.messages, 'company', fileUrl),
      done && !tk.rating ? ratingBox('Destek deneyiminizi değerlendirin', async (rating, note) => { draw(await api.post(`/api/membership/tickets/${id}/rate`, { rating, note })); toast('Teşekkürler!', 'success'); }) : null,
      tk.rating ? h('div', { class: 'dm-rated' }, 'Değerlendirmeniz: ', starsOf(tk.rating), tk.rating_note ? ` — “${tk.rating_note}”` : '') : null,
      tk.status === 'kapali' ? h('div', { class: 'card empty' }, 'Bu talep kapatıldı. Yeni bir konu için yeni talep açın.') : [
        done ? h('p', { class: 'small muted' }, 'Sorun devam ediyorsa yazmanız yeterli; talep yeniden açılır.') : null, comp,
        !done ? h('div', { class: 'mb2-solved' }, h('button', { class: 'btn success', type: 'button', onclick: async () => {
          try { draw(await api.post(`/api/membership/tickets/${id}/close`, {})); toast('Talep çözüldü olarak kapatıldı'); } catch (e) { toastError(e); }
        } }, '✓ Sorunum çözüldü')) : null]));
  };
  const load = async force => {
    let tk;
    try { tk = await api.get(`/api/membership/tickets/${id}`); } catch (e) { return clear(box, h('div', { class: 'card empty' }, e.message)); }
    if (!force && tk.messages.length === last && tk.status === lastStatus) return;
    last = tk.messages.length; lastStatus = tk.status; draw(tk);
  };
  await load(true);
  every(15000, () => load(false));
}

// ---------------- Canlı destek ----------------
async function liveView(view, ctx, openId) {
  loading(view);
  let st = null, chats = [];
  try { [st, chats] = await Promise.all([api.get('/api/membership/support-status'), api.get('/api/membership/chats')]); }
  catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const active = chats.find(c => ['waiting', 'active'].includes(c.status));
  const cid = openId || active?.id;
  if (cid) return chatView(view, ctx, cid, st);
  const topic = h('input', { class: 'input', placeholder: 'Konu (ör. Yazıcılar görünmüyor)', maxlength: 160 });
  const cat = h('select', { class: 'input' }, Object.entries(CATEGORY).map(([k, v]) => h('option', { value: k }, v)));
  const msg = h('textarea', { class: 'input', rows: 4, placeholder: 'Nasıl yardımcı olabiliriz?' });
  const on = st.online > 0;
  const start = h('button', { class: 'btn primary lg', type: 'button' }, on ? '💬 Sohbeti başlat' : '✉️ Mesajı bırak');
  start.addEventListener('click', async () => {
    if (!msg.value.trim()) { toast('Mesajınızı yazın', 'err'); msg.focus(); return; }
    start.disabled = true;
    try {
      const r = await api.post('/api/membership/chats', { topic: topic.value, category: cat.value, message: msg.value });
      if (r.offline) { toast(t('Mesajınız {c} numaralı talep olarak kaydedildi', { c: r.ticket.code }), 'success'); location.hash = `#/uyelik/tickets/${r.ticket.id}`; }
      else { location.hash = `#/uyelik/live/${r.id}`; }
    } catch (e) { toastError(e); start.disabled = false; }
  });
  clear(view, h('div', { class: 'mb2-live-start' },
    h('section', { class: 'card card-pad mb2-live-form' },
      h('div', { class: `mb2-live-hero ${on ? 'on' : 'off'}` }, h('span', { class: 'mb2-pulse' }),
        h('div', null, h('h3', null, on ? 'Destek ekibimiz çevrimiçi' : 'Şu an çevrimdışıyız'),
          h('p', { class: 'small muted' }, on ? (st.waiting_chats ? t('Sırada {n} firma var; kısa süre içinde bağlanacaksınız.', { n: st.waiting_chats }) : 'Mesajınızı yazın, bir destek uzmanı hemen bağlansın.')
            : st.offline_msg))),
      h('div', { class: 'row' }, field('Konu', topic), field('Kategori', cat)), field('Mesajınız', msg),
      h('div', { class: 'mb2-live-acts' }, start, h('span', { class: 'small muted' }, t('Çalışma saatleri: {h}', { h: hoursText(st.hours) })))),
    h('aside', { class: 'card card-pad mb2-live-side' }, h('h3', null, 'Önceki sohbetler'),
      chats.length ? h('div', { class: 'mb2-chats' }, chats.slice(0, 12).map(c => h('a', { class: 'mb2-chat', href: `#/uyelik/live/${c.id}` },
        h('div', { class: 'grow' }, h('b', null, c.topic || c.code), h('small', { class: 'muted' }, `${fmtDateTime(c.created_at)} · ${c.assignee_name || (c.status === 'missed' ? 'talebe dönüştü' : '—')}`)),
        c.rating ? starsOf(c.rating) : null))) : h('p', { class: 'small muted' }, 'Henüz canlı destek görüşmeniz yok.'),
      h('p', { class: 'small muted' }, 'İpucu: Sohbette “Ekranımı paylaş” ile ekranınızı destek uzmanına güvenli bir bağlantıyla gösterebilirsiniz.'))));
}

async function chatView(view, ctx, cid, st) {
  const msgs = h('div', { class: 'lc-msgs' });
  const typing = h('div', { class: 'lc-typing', hidden: true }, h('span'), h('span'), h('span'), ' destek yazıyor');
  const head = h('div', { class: 'lc-head' });
  const foot = h('div');
  let lastId = 0, chat = null, lastTyping = 0, ended = false;
  clear(view, h('section', { class: 'card lc-pane mb2-chat-pane' }, head, msgs, typing, foot));
  const append = list => {
    const atBottom = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 80;
    list.forEach(m => { msgs.append(chatMessage(m, 'company', fileUrl)); lastId = Math.max(lastId, m.id); });
    if (atBottom || list.length) msgs.scrollTop = msgs.scrollHeight;
  };
  const drawHead = c => {
    const who = c.status === 'waiting' ? h('div', { class: 'grow' }, h('b', null, 'Destek uzmanı bekleniyor…'),
      h('div', { class: 'small muted' }, c.queue_position > 1 ? t('Sıranız: {n}', { n: c.queue_position }) : 'Sıradaki sizsiniz', st?.avg_first_response_min ? ` · ${t('ortalama yanıt {m}', { m: fmtM(st.avg_first_response_min) })}` : ''))
      : h('div', { class: 'grow' }, h('b', null, c.assignee_name || 'Destek'), h('div', { class: 'small muted' }, c.assignee_title || 'HEPGO Destek', ' · ', c.code));
    clear(head, h('span', { class: `lc-agent ${c.status}` }, (c.assignee_name || '?').split(' ').map(x => x[0]).slice(0, 2).join('')), who,
      h('div', { class: 'lc-acts' },
        c.ticket_id ? h('a', { class: 'btn sm', href: `#/uyelik/tickets/${c.ticket_id}` }, `🎫 ${c.ticket_code || 'Talep'}`) : null,
        ['waiting', 'active'].includes(c.status) ? h('button', { class: 'btn sm', type: 'button', onclick: share }, '🖥️ Ekranımı paylaş') : null,
        ['waiting', 'active'].includes(c.status) ? h('button', { class: 'btn sm', type: 'button', onclick: end }, 'Sohbeti bitir') : h('a', { class: 'btn sm primary', href: '#/uyelik/live' }, 'Yeni sohbet')));
  };
  const drawFoot = c => {
    if (['waiting', 'active'].includes(c.status)) {
      if (!foot.firstChild || ended) {
        ended = false;
        clear(foot, composer(async ({ body, files }) => {
          await api.post(`/api/membership/chats/${cid}/messages`, formData({ body }, files)); poll();
        }, { enterSends: true, rows: 2, placeholder: 'Mesajınızı yazın…', onTyping: () => {
          if (Date.now() - lastTyping > 3000) { lastTyping = Date.now(); api.post(`/api/membership/chats/${cid}/typing`, {}).catch(() => {}); }
        } }));
        foot.firstChild.focus?.();
      }
    } else if (!ended) {
      ended = true;
      clear(foot, h('div', { class: 'lc-closed' }, c.rating ? h('div', null, 'Değerlendirmeniz: ', starsOf(c.rating), ' — teşekkürler!')
        : ratingBox('Görüşmeyi değerlendirin', async (rating, note) => { await api.post(`/api/membership/chats/${cid}/rate`, { rating, note }); toast('Teşekkürler!', 'success'); clear(foot, h('div', { class: 'lc-closed' }, 'Değerlendirmeniz için teşekkürler.', ' ', h('a', { href: '#/uyelik/live' }, 'Yeni sohbet başlat'))); })));
    }
  };
  async function share() {
    const m = await import('./screenshare.js');
    m.startScreenShare(ctx, { onStarted: async sess => {
      await api.post(`/api/membership/chats/${cid}/messages`, formData({ body: sess.link, kind: 'screen' }));
      toast('Ekran paylaşım bağlantınız destek uzmanına iletildi'); poll();
    } });
  }
  async function end() {
    try { await api.post(`/api/membership/chats/${cid}/end`, {}); poll(true); } catch (e) { toastError(e); }
  }
  const poll = async full => {
    let c;
    try { c = await api.get(`/api/membership/chats/${cid}?after=${full ? 0 : lastId}`); } catch { return; }
    if (full) { clear(msgs); lastId = 0; }
    const changed = !chat || chat.status !== c.status || chat.assignee_name !== c.assignee_name || chat.ticket_id !== c.ticket_id || chat.queue_position !== c.queue_position;
    chat = c;
    if (changed) { drawHead(c); drawFoot(c); }
    append(c.messages);
    typing.hidden = !c.typing;
    try { sessionStorage.setItem('hepgo.chat', ['waiting', 'active'].includes(c.status) ? String(cid) : ''); } catch { /* */ }
  };
  await poll(true);
  every(2500, () => poll(false));
}

// ---------------- Ödemeler ----------------
async function paymentsView(view) {
  loading(view);
  let d;
  try { d = await api.get('/api/membership'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const pi = d.support?.payment_info || {};
  const copy = (txt, label) => h('button', { class: 'btn xs', type: 'button', onclick: async () => { try { await navigator.clipboard.writeText(txt); toast(t('{l} kopyalandı', { l: label })); } catch { toast(txt); } } }, 'Kopyala');
  const notify = () => {
    const now = new Date();
    const per = i => { const x = new Date(now.getFullYear(), now.getMonth() - i, 1); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}`; };
    const period = h('select', { class: 'input' }, [-1, 0, 1, 2, 3, 4, 5].map(i => h('option', { value: per(i), selected: i === 0 }, per(i))));
    const amount = h('input', { class: 'input', type: 'number', min: 1, step: '0.01', value: d.fee || '' });
    const date = h('input', { class: 'input', type: 'date', value: now.toISOString().slice(0, 10) });
    const method = h('select', { class: 'input' }, [['havale', 'Havale'], ['eft', 'EFT / FAST'], ['kart', 'Kredi kartı'], ['nakit', 'Nakit'], ['diger', 'Diğer']].map(([k, l]) => h('option', { value: k }, l)));
    const ref = h('input', { class: 'input', placeholder: 'Dekont / işlem numarası' });
    const note = h('input', { class: 'input', placeholder: 'Açıklama (isteğe bağlı)' });
    modal({ title: 'Ödeme bildir', body: h('div', null, h('p', { class: 'small muted' }, 'Yaptığınız ödemeyi bize bildirin; muhasebe ekibimiz kontrol edip ödemelerinize işler.'),
      h('div', { class: 'row' }, field('Dönem', period), field('Tutar (₺)', amount)), h('div', { class: 'row' }, field('Ödeme tarihi', date), field('Yöntem', method)),
      field('Dekont / referans no', ref), field('Not', note)),
    actions: [{ label: 'Vazgeç' }, { label: 'Bildir', class: 'primary', onClick: async () => {
      if (!(Number(amount.value) > 0)) throw new Error('Tutarı girin');
      await api.post('/api/membership/payment-notices', { period: period.value, amount: Number(amount.value), paid_at: date.value, method: method.value, reference: ref.value, note: note.value });
      toast('Ödeme bildiriminiz alındı', 'success'); paymentsView(view);
    } }] });
  };
  const [, pl] = PAY[d.pay_status] || ['', d.pay_status];
  clear(view,
    h('div', { class: 'mb2-pay-top' },
      h('section', { class: 'card card-pad mb2-pay-sum' }, h('small', { class: 'muted' }, 'Aylık üyelik ücreti'), h('div', { class: 'mb2-big' }, showFee(d.fee) ? money2(d.fee) : (HIDE_PRICES ? 'Açık beta — ücretsiz' : 'Ücretsiz')),
        showFee(d.fee) ? h('div', null, t('Bu ay ({p}): ', { p: d.period }), badge(PAY, d.pay_status), d.paid_this_month ? h('span', { class: 'small muted' }, ` · ${money2(d.paid_this_month)} ödendi`) : null) : h('div', { class: 'small muted' }, 'Açık beta döneminde tüm modüller ücretsiz açıktır.'),
        showFee(d.fee) ? h('button', { class: 'btn primary', type: 'button', onclick: notify }, '＋ Ödeme bildir') : null),
      pi.iban ? h('section', { class: 'card card-pad mb2-bank' }, h('h3', null, 'Ödeme bilgileri'),
        h('dl', { class: 'dm-kv' }, pi.bank_name ? [h('dt', null, 'Banka'), h('dd', null, pi.bank_name)] : null,
          pi.account_name ? [h('dt', null, 'Hesap sahibi'), h('dd', null, pi.account_name, ' ', copy(pi.account_name, 'Hesap sahibi'))] : null,
          h('dt', null, 'IBAN'), h('dd', { class: 'mono' }, pi.iban, ' ', copy(pi.iban.replace(/\s/g, ''), 'IBAN'))),
        pi.note ? h('p', { class: 'small muted' }, pi.note) : null,
        h('p', { class: 'small muted' }, t('Açıklamaya firma adınızı ve dönemi yazmanız işlemi hızlandırır ({p}).', { p: pl }))) : null),
    showFee(d.fee) && d.months?.length ? h('section', { class: 'card card-pad' }, h('h3', null, 'Son 12 ay'),
      h('div', { class: 'mb2-months wide' }, [...d.months].reverse().map(m => h('div', { class: `mb2-m ${m.status}`, title: (PAY[m.status] || [])[1] || m.status },
        h('b', null, m.period.slice(5)), h('small', null, m.period.slice(0, 4)), m.paid ? h('i', null, money(m.paid)) : null)))) : null,
    d.notices?.length ? h('section', { class: 'card table-wrap' }, h('div', { class: 'mk-fin-h' }, h('b', null, 'Ödeme bildirimlerim')), h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Bildirim', 'Dönem', 'Tutar', 'Yöntem / ref.', 'Durum'].map(x => h('th', null, x)))),
      h('tbody', null, d.notices.map(n => h('tr', null, h('td', null, fmtDate(n.created_at)), h('td', null, n.period || '—'), h('td', { class: 'num' }, money2(n.amount)),
        h('td', null, [n.method, n.reference].filter(Boolean).join(' · ') || '—'), h('td', null, badge(NOTICE, n.status), n.decision_note ? h('div', { class: 'small muted' }, n.decision_note) : null)))))) : null,
    d.payments.length ? h('section', { class: 'card table-wrap' }, h('div', { class: 'mk-fin-h' }, h('b', null, 'Ödeme geçmişi')), h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Dönem', 'Ödeme tarihi', 'Tutar', 'Yöntem', 'Not'].map(x => h('th', null, x)))),
      h('tbody', null, d.payments.map(p => h('tr', null, h('td', null, p.period), h('td', null, fmtDate(p.paid_at)),
        h('td', { class: 'num' }, money2(p.amount)), h('td', null, p.method || '—'), h('td', { class: 'muted' }, p.note || '—'))))))
      : h('div', { class: 'card empty' }, 'Kayıtlı ödeme yok.'));
}

// ---------------- köşedeki canlı destek göstergesi (başka sayfadayken aktif sohbet) ----------------
let dockTimer = null;
export function initSupportDock(ctx) {
  if (dockTimer || !ctx.user?.modules?.includes('uyelik')) return;
  const dock = h('a', { class: 'lc-dock', hidden: true, href: '#/uyelik/live' });
  document.body.append(dock);
  const check = async () => {
    let id = '';
    try { id = sessionStorage.getItem('hepgo.chat') || ''; } catch { /* */ }
    if (!id || location.hash.startsWith('#/uyelik/live')) { dock.hidden = true; return; }
    let c;
    try { c = (await api.get('/api/membership/chats')).find(x => String(x.id) === id); } catch { return; }
    if (!c || !['waiting', 'active'].includes(c.status)) { try { sessionStorage.removeItem('hepgo.chat'); } catch { /* */ } dock.hidden = true; return; }
    dock.href = `#/uyelik/live/${id}`;
    clear(dock, h('span', { class: 'lc-dock-i' }, '💬'), h('span', null, h('b', null, c.status === 'waiting' ? 'Canlı destek: sıradasınız' : (c.assignee_name || 'Canlı destek')),
      h('small', null, c.company_unread ? t('{n} yeni mesaj', { n: c.company_unread }) : 'Sohbete dön')));
    dock.classList.toggle('hot', !!c.company_unread);
    dock.hidden = false;
  };
  window.addEventListener('hashchange', () => setTimeout(check, 300));
  dockTimer = setInterval(check, 10000);
  check();
}

// ---------------- Sözleşmelerim ----------------
async function contractsList(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get('/api/membership/contracts'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const card = x => {
    const a = x.acceptance;
    return h('a', { class: `card ct-card ct-link ${!a && x.required ? 'pending' : ''}`, href: `#/uyelik/contracts/${x.id}` },
      h('div', { class: 'ct-card-h' }, h('div', { class: 'grow' }, h('b', { class: 'ct-title' }, x.title),
        h('div', { class: 'small muted' }, `Sürüm ${x.version}`, x.published_at ? ` · ${fmtDate(x.published_at)}` : '', x.required ? ' · zorunlu' : ' · isteğe bağlı')),
        a ? h('span', { class: 'badge green' }, 'Onaylandı') : h('span', { class: `badge ${x.required ? 'yellow' : ''}` }, x.required ? 'Onayınızı bekliyor' : 'Onaylanmadı')),
      x.summary ? h('p', { class: 'small ct-sum' }, x.summary) : null,
      a ? h('div', { class: 'small muted' }, `${fmtDateTime(a.accepted_at)} · ${[a.signer_name, a.signer_title].filter(Boolean).join(' · ')}`)
        : x.previous ? h('div', { class: 'small muted' }, `Önceki sürüm (v${x.previous.version}) ${fmtDate(x.previous.accepted_at)} tarihinde onaylanmıştı; bu sürüm için yeniden onay gerekiyor.`) : null,
      h('span', { class: 'ct-go' }, a ? 'Görüntüle →' : 'Oku ve onayla →'));
  };
  clear(view,
    d.pending ? h('div', { class: 'card card-pad ct-note warn' }, h('b', null, `Onayınızı bekleyen ${d.pending} zorunlu sözleşme var. `),
      'Hizmetin kesintisiz sürmesi için firmanız adına yetkili kişinin okuyup onaylaması gerekir.') : null,
    d.docs.length ? h('div', { class: 'ct-grid' }, d.docs.map(card)) : h('div', { class: 'card empty' }, 'Henüz yayınlanmış bir sözleşme yok.'),
    d.history?.length ? h('section', { class: 'card table-wrap', style: { marginTop: '14px' } }, h('div', { class: 'mk-fin-h' }, h('b', null, 'Onay geçmişi')),
      h('table', { class: 'table' }, h('thead', null, h('tr', null, ['Sözleşme', 'Sürüm', 'İmzalayan', 'Tarih'].map(x => h('th', null, x)))),
        h('tbody', null, d.history.map(r => h('tr', null, h('td', null, h('a', { href: `#/uyelik/contracts/${r.doc_id}` }, r.title)), h('td', null, `v${r.version}`),
          h('td', null, [r.signer_name, r.signer_title].filter(Boolean).join(' · ')), h('td', null, fmtDateTime(r.accepted_at))))))) : null);
}

async function contractPage(view, id, ctx) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get(`/api/membership/contracts/${id}`); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const company = ctx.meta?.company || '';
  const a = d.acceptance;
  const printBtn = h('button', { class: 'btn', type: 'button', onclick: () => printDoc({ title: d.title, sub: `Sürüm ${d.version}`, text: d.body, proof: a ? { ...a, hash: d.hash } : null, company }) }, 'Yazdır / PDF');
  let foot;
  if (a) {
    foot = h('div', { class: 'ct-proof ok' }, h('b', null, '✓ Elektronik onay kaydı'),
      h('table', null, proofRows({ ...a, doc_hash: a.doc_hash || d.hash }).map(([k, v]) => h('tr', null, h('td', null, k), h('td', { class: /SHA/.test(k) ? 'mono' : '' }, v)))));
  } else if (d.status === 'published') {
    const name = h('input', { class: 'input', value: ctx.user.full_name || '', placeholder: 'Adı soyadı' });
    const title = h('input', { class: 'input', placeholder: 'Ünvanı (ör. Genel Müdür)' });
    const agree = h('input', { type: 'checkbox' });
    const btn = h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Sözleşmeyi onayla');
    agree.addEventListener('change', () => { btn.disabled = !agree.checked; });
    btn.addEventListener('click', async () => {
      if (name.value.trim().length < 3) { toast('İmzalayan yetkilinin adı soyadını yazın', 'err'); name.focus(); return; }
      btn.disabled = true; btn.textContent = 'Onaylanıyor…';
      try {
        await api.post(`/api/membership/contracts/${id}/accept`, { hash: d.hash, signer_name: name.value, signer_title: title.value, agree: agree.checked });
        toast('Sözleşme onaylandı', 'success');
        contractPage(view, id, ctx);
      } catch (e) { toast(e.message, 'err'); btn.disabled = false; btn.textContent = 'Sözleşmeyi onayla'; }
    });
    foot = h('div', { class: 'ct-accept card card-pad' }, h('b', null, 'Elektronik onay'),
      h('p', { class: 'small muted' }, 'Onayınız; adınız, ünvanınız, tarih-saat, IP adresi ve yukarıdaki metnin SHA-256 parmak izi ile kayıt altına alınır. Onaylanan metnin bire bir kopyası saklanır.'),
      h('div', { class: 'ct-edit-row' }, field('İmzalayan yetkili', name), field('Ünvan', title)),
      h('label', { class: 'ct-agree' }, agree, h('span', null, `Sözleşmeyi okudum ve anladım; ${company || 'firmam'} adına onaylamaya yetkili olduğumu beyan ederek kabul ediyorum.`)),
      h('div', { class: 'ct-acts' }, btn));
  }
  clear(view,
    h('div', { class: 'ct-head card card-pad' }, h('a', { class: 'small', href: '#/uyelik/contracts' }, '← Sözleşmelerim'),
      h('h3', null, d.title), h('div', { class: 'small muted' }, `Sürüm ${d.version}`, d.published_at ? ` · yayın ${fmtDate(d.published_at)}` : '',
        a ? ' · onaylandı' : d.required ? ' · onayınızı bekliyor' : ''), h('div', { class: 'ct-acts' }, printBtn)),
    h('div', { class: 'ct-paper' }, docView(d.body)),
    h('div', { class: 'small muted mono ct-hash' }, `Metin parmak izi (SHA-256): ${d.hash}`),
    foot || null);
}
