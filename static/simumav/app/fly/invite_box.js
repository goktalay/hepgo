// Bekleme salonunda kurucunun E-POSTA DAVETİ kutusu (yol haritası): e-posta adresleri (sınırsız; istek başına 25) + arkadaşlardan seç →
// POST /api/match/{id}/invites; gönderilen davetler (maskeli adres, durum, e-posta kapalıysa kopyalanacak bağlantı) GET /api/match/{id}/invites.
// Salon her güncellemede yeniden çizildiği için kutu TEK düğüm olarak tutulur (yazılan metin kaybolmaz).
import { h, clear, toast, toastError, t as tr } from './simui.js';
import { net } from './net.js';
import { parseEmails } from './flow.js';

const LT = (k, p, fb) => { const r = tr(k, p); return r && r !== k ? r : (fb ?? k); };

export function createInviteMailBox(mid) {
  const ta = h('textarea', { class: 'input', placeholder: LT('rm.emails_ph'), 'aria-label': LT('rm.invite_email') });
  const fbox = h('div', { class: 'rm-friend-pick' });
  const list = h('ul', { class: 'rm-inv-list' });
  const note = h('small', { class: 'rm-note' });
  const picked = new Set();
  const send = async e => {
    const emails = parseEmails(ta.value), fids = [...picked];
    if (!emails.length && !fids.length) { toast(LT('rm.invite_need'), 'err'); return; }
    e.currentTarget.disabled = true;
    try {
      const r = await net.post(`/api/match/${mid}/invites`, { emails, friend_ids: fids });
      ta.value = ''; picked.clear(); for (const c of fbox.querySelectorAll('input')) c.checked = false;
      toast(LT(r.mail_enabled ? 'rm.invites_sent' : 'rm.invites_links', { n: r.invites.length }));
      if (r.skipped?.length) toast(LT('rm.invites_skipped', { n: r.skipped.length }));
      links = Object.assign(links, Object.fromEntries(r.invites.filter(i => i.link).map(i => [i.id, i.link])));
      await load();
    } catch (err) { toastError(err); }
    e.currentTarget.disabled = false;
  };
  let links = {};
  const load = async () => {
    try {
      const r = await net.get(`/api/match/${mid}/invites`);
      clear(note, r.mail_enabled ? LT('rm.mail_on') : LT('rm.mail_off'));
      clear(list, r.invites.map(i => h('li', null, h('span', { class: 'mono' }, i.email), h('span', null, LT(`rm.inv_${i.state}`),
        !r.mail_enabled && links[i.id] && i.state === 'pending' ? h('button', { class: 'btn sm', type: 'button', onclick: () => navigator.clipboard?.writeText(links[i.id]).then(() => toast(LT('match.link_copied'))) }, LT('match.copy')) : null))));
    } catch { /* kurucu değil */ }
  };
  net.get('/api/friends').then(r => clear(fbox, (r.friends || []).map(f => h('label', null, h('input', { type: 'checkbox', onchange: e => { if (e.target.checked) picked.add(f.user_id); else picked.delete(f.user_id); } }), f.name)))).catch(() => {});
  load();
  return h('div', { class: 'sm-mt-card rm-inv-box', dataset: { inviteMail: '1' } }, h('h3', null, '✉ ', LT('rm.invite_email')), ta, h('b', { class: 'small' }, LT('rm.invite_friends')), fbox,
    h('button', { class: 'btn primary', type: 'button', onclick: send }, LT('rm.invite_send')), note, list);
}
