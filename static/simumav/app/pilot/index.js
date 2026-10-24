// Pilot menüsü sayfaları (#/pilot/<sekme>): ÖNCEKİ UÇUŞLARIM (pilot seçici + tür filtresi; GET /api/crew/{id}/flights; kart → Operasyon ayrıntısı/replay),
// ARKADAŞLARIM (GET /api/friends: birlikte uçulanlar otomatik + elle ekle/sil; e-posta maskeli), DAVETLER (GET /api/invites: kabul / ret / engelle).
import * as api from '../core/api.js';
import { h, clear } from '../core/dom.js';
import { t } from '../i18n/i18n.js';
import { screen, segment, btn, toast, toastErr, confirmDlg, promptDlg } from '../ui/components.js';
import { stagger } from '../ui/transition.js';
import { avatarImg, ensureAvatarCss } from '../crew/avatar3d.js';

export const TABS = ['flights', 'friends', 'invites'];
const MODES = ['', 'free', 'rings', 'cargo_drop', 'spraying', 'dogfight', 'facility_defense', 'ship_defense'];
export const fmtDur = s => { s = Math.max(0, Math.round(Number(s) || 0)); const m = Math.floor(s / 60); return m >= 60 ? `${Math.floor(m / 60)} sa ${m % 60} dk` : `${m}:${String(s % 60).padStart(2, '0')}`; };
const fmtDate = d => (d ? String(d).slice(0, 16).replace('T', ' ') : '');

export async function mount(root, ctx) {
  ensureAvatarCss();
  const tab = TABS.includes((ctx.param || '').split('/')[0]) ? ctx.param.split('/')[0] : 'flights';
  const sc = screen({ title: t(`rm.pm_${tab}`), sub: t(`rm.${tab}_sub`), cls: 'scroll' });
  sc.append(h('div', { class: 'rm-tabs' }, segment(TABS.map(v => ({ value: v, label: t(`rm.pm_${v}`) })), tab, v => ctx.go('pilot', v))));
  const body = h('div', { class: 'rm-list' });
  sc.append(body);
  clear(root, sc);
  ctx.setBack(t('common.menu'));
  if (tab === 'flights') await flights(body, ctx);
  else if (tab === 'friends') await friends(body, ctx);
  else await invites(body, ctx);
}

async function flights(body, ctx) {
  let pilots = [];
  try { pilots = (await api.get('/api/crew')).pilots || []; } catch (e) { toastErr(e); }
  if (!pilots.length) { clear(body, h('p', { class: 'rm-empty' }, t('rm.no_pilot'))); return; }
  let pid = (pilots.find(p => p.is_default) || pilots[0]).id, mode = '';
  const sel = h('select', { class: 'input', 'aria-label': t('rm.pilot'), onchange: e => { pid = Number(e.target.value); load(); } }, pilots.map(p => h('option', { value: p.id, selected: p.id === pid }, `${p.name} · ${t('rm.lv', { l: p.level || 1 })}`)));
  const msel = h('select', { class: 'input', 'aria-label': t('rm.mode'), onchange: e => { mode = e.target.value; load(); } }, MODES.map(m => h('option', { value: m }, m ? t(`rm.mode_${m}`) : t('rm.all_modes'))));
  const stats = h('div', { class: 'rm-note' });
  const list = h('div', { class: 'rm-list' });
  clear(body, h('div', { class: 'rm-switch' }, h('b', null, t('rm.pilot')), sel, msel, stats), list);
  async function load() {
    clear(list, h('p', { class: 'rm-empty' }, t('common.loading')));
    let r;
    try { r = await api.get(`/api/crew/${pid}/flights?limit=50${mode ? `&mode=${mode}` : ''}`); } catch (e) { toastErr(e); return; }
    clear(stats, t('rm.flight_stats', { n: r.stats.flights, d: fmtDur(r.stats.flight_s), c: r.stats.crashes }));
    if (!r.flights.length) { clear(list, h('p', { class: 'rm-empty' }, t('rm.no_flights'))); return; }
    const rows = r.flights.map(f => h('div', { class: 'rm-li', dataset: { fid: String(f.id) } },
      h('div', { class: 'av' }, f.track?.preview_png ? h('img', { src: f.track.preview_png, alt: '', loading: 'lazy' }) : null),
      h('div', { class: 'tx' }, h('b', null, `${f.drone?.name || '—'} · ${f.track?.name || '—'}`),
        h('small', null, [fmtDate(f.started_at), f.mode ? t(`rm.mode_${f.mode}`) : null, f.duration_s != null ? fmtDur(f.duration_s) : null, f.result ? t(`rm.result_${f.result}`) : t('rm.result_live')].filter(Boolean).join(' · '))),
      h('div', { class: 'ac' }, f.xp != null ? h('span', { class: 'rm-xp-pill' }, `+${f.xp} XP`) : null,
        btn(t('rm.details'), () => ctx.go('ops', String(f.id)), 'sm'))));
    clear(list, rows); stagger(rows, 30);
  }
  load();
}

async function friends(body, ctx) {
  const addBox = h('div', { class: 'rm-switch' },
    btn(`+ ${t('rm.friend_add_email')}`, async () => {
      const e = await promptDlg(t('rm.friend_add_email'), { placeholder: 'ornek@eposta.com', maxlength: 254 });
      if (!e) return;
      try { await api.post('/api/friends', { email: e }); toast(t('rm.friend_added'), 'ok'); load(); } catch (err) { toastErr(err); }
    }, 'primary'), h('span', { class: 'rm-note' }, t('rm.friends_note')));
  const list = h('div', { class: 'rm-list' });
  clear(body, addBox, list);
  async function load() {
    let fr = [];
    try { fr = (await api.get('/api/friends')).friends || []; } catch (e) { toastErr(e); }
    if (!fr.length) { clear(list, h('p', { class: 'rm-empty' }, t('rm.no_friends'))); return; }
    const rows = fr.map(f => h('div', { class: 'rm-li', dataset: { uid: String(f.user_id) } },
      h('div', { class: 'av' }, avatarImg(f.avatar, { size: 128, alt: '' })),
      h('div', { class: 'tx' }, h('b', null, f.name), h('small', null, [f.email, f.played_count ? t('rm.played_n', { n: f.played_count }) : null, f.last_played_at ? t('rm.last_played', { d: fmtDate(f.last_played_at) }) : null].filter(Boolean).join(' · ')),
        h('small', null, f.friend ? `★ ${t('rm.friend_manual')}` : t('rm.friend_auto'))),
      h('div', { class: 'ac' },
        !f.friend ? btn(`★ ${t('rm.friend_keep')}`, async () => { try { await api.post('/api/friends', { user_id: f.user_id }); load(); } catch (e) { toastErr(e); } }, 'sm') : null,
        btn(t('common.delete'), async () => { if (!await confirmDlg(t('rm.friend_del_q', { n: f.name }), { danger: true })) return; try { await api.del(`/api/friends/${f.user_id}`); load(); } catch (e) { toastErr(e); } }, 'sm ghost'))));
    clear(list, rows); stagger(rows, 30);
  }
  load();
}

async function invites(body, ctx) {
  const list = h('div', { class: 'rm-list' });
  clear(body, list);
  async function load() {
    let inv = [];
    try { inv = (await api.get('/api/invites')).invites || []; } catch (e) { toastErr(e); }
    if (!inv.length) { clear(list, h('p', { class: 'rm-empty' }, t('rm.no_invites'))); return; }
    clear(list, inv.map(i => h('div', { class: 'rm-li', dataset: { iid: String(i.id) } }, h('div', { class: 'av' }),
      h('div', { class: 'tx' }, h('b', null, t('rm.invite_from', { n: i.inviter?.name || '—' })),
        h('small', null, [i.mode ? t(`rm.mode_${i.mode === 'fpv' ? 'rings' : i.mode}`) : null, i.track, i.drone?.name, t('rm.expires', { d: fmtDate(i.expires_at) })].filter(Boolean).join(' · '))),
      h('div', { class: 'ac' },
        btn(t('rm.accept'), async () => { try { const m = await api.post(`/api/invites/${i.id}/accept`); ctx.refreshPilot?.(); ctx.go(`#/fly/match/${m.id}`); } catch (e) { toastErr(e); load(); } }, 'primary sm'),
        btn(t('rm.decline'), async () => { try { await api.post(`/api/invites/${i.id}/decline`, { block: false }); ctx.refreshPilot?.(); load(); } catch (e) { toastErr(e); } }, 'sm'),
        btn(t('rm.block'), async () => { if (!await confirmDlg(t('rm.block_q', { n: i.inviter?.name || '' }), { danger: true })) return; try { await api.post(`/api/invites/${i.id}/decline`, { block: true }); ctx.refreshPilot?.(); load(); } catch (e) { toastErr(e); } }, 'sm ghost')))));
  }
  load();
}
