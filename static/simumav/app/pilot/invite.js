// E-posta davet bağlantısı (#/match/invite/<belirteç>): ön izleme (GET /api/invites/t/{tok}) → Kabul et (şifresiz salona) / Reddet / Engelle.
// Oturum yoksa kabuk zaten girişe yönlendirir ve bu adrese döner (app.js loadSession).
import * as api from '../core/api.js';
import { h, clear } from '../core/dom.js';
import { t } from '../i18n/i18n.js';
import { screen, btn, toast, toastErr } from '../ui/components.js';

export const tokenOf = param => { const m = String(param || '').match(/^invite\/([A-Za-z0-9_-]{30,40})$/); return m ? m[1] : null; };

export async function mount(root, ctx) {
  const tok = tokenOf(ctx.param);
  const sc = screen({ title: t('rm.invite_title'), sub: '' });
  const card = h('div', { class: 'rm-xp-card', style: 'max-width:560px;margin:0 auto' });
  sc.append(card);
  clear(root, sc);
  ctx.setBack(t('common.menu'));
  if (!tok) { clear(card, h('p', null, t('rm.invite_bad'))); return; }
  let r;
  try { r = await api.get(`/api/invites/t/${tok}`); } catch (e) { clear(card, h('p', null, e.status === 404 ? t('rm.invite_bad') : e.message)); return; }
  const state = r.state;
  clear(card, h('h2', { class: 'title md' }, t('rm.invite_from', { n: r.inviter })),
    h('p', null, [r.mode ? t(`rm.mode_${r.mode === 'fpv' ? 'rings' : r.mode}`) : null, r.track, t('rm.max_players_n', { n: r.max_players })].filter(Boolean).join(' · ')),
    h('p', { class: 'rm-note' }, t('rm.invite_for', { e: r.email_hint }), ' · ', t('rm.expires', { d: String(r.expires_at || '').slice(0, 16).replace('T', ' ') })),
    state !== 'pending' ? h('p', { class: 'err-box' }, t(`rm.invite_state_${state}`)) : h('div', { class: 'btn-row' },
      btn(t('rm.accept'), async () => { try { const m = await api.post(`/api/invites/t/${tok}/accept`); toast(t('rm.joined'), 'ok'); ctx.go(`#/fly/match/${m.id}`); } catch (e) { toastErr(e); } }, 'primary lg'),
      btn(t('rm.decline'), async () => { try { await api.post(`/api/invites/t/${tok}/decline`, { block: false }); toast(t('rm.declined'), 'ok'); ctx.go('menu'); } catch (e) { toastErr(e); } }, 'ghost'),
      btn(t('rm.block'), async () => { try { await api.post(`/api/invites/t/${tok}/decline`, { block: true }); toast(t('rm.declined'), 'ok'); ctx.go('menu'); } catch (e) { toastErr(e); } }, 'ghost')));
}
