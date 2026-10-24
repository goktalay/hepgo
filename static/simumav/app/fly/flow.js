// UÇUŞ AKIŞI (yol haritası "Uçuş"): 1 dron (hangar) → 2 parkur (Karşılaşma Parkurları · Özel Parkurlar · Gerçek Dünyalar; yalnız kayıtlı olan
// türler sekme olarak çıkar, hiçbiri yoksa doğrudan karşılaşma parkurları) → 3 oyun türü (serbest, halka toplama, yük bırakma, tarla ilaçlama,
// it dalaşı, kritik tesis savunma, gemi savunma; araca/parkura uymayanlar gerekçesiyle pasif) → 4 tek oyunculu (gerekli yapay zekâ otomatik) /
// çok oyunculu (e-posta ile sınırsız davet + arkadaşlardan seç + istenen sayıda yapay zekâ) → UÇ.
// Başlatma: karşılaşma türleri /api/match[/ai|/solo] + davet (/api/match/{id}/invites) + bot; uçuş türleri ayrıntı sihirbazına (kalkış, güç, görev,
// saha, pilot) `preset` ile devredilir (POST /api/fly/start {…, mode}).
import { clear, h, toast, toastError, t as tr } from './simui.js';
import { net } from './net.js';
import { createMatch } from './match.js';
import { lobbyHref } from './match_core.js';

export const FLOW_STEPS = ['drone', 'track', 'mode', 'players'];
export const MODE_ORDER = ['free', 'rings', 'cargo_drop', 'spraying', 'dogfight', 'facility_defense', 'ship_defense'];
const MODE_ICON = {
  free: '<svg viewBox="0 0 48 48"><path d="M6 30c10-14 26-14 36 0"/><path d="M24 8v8M14 12l4 6M34 12l-4 6"/><circle cx="24" cy="30" r="4"/></svg>',
  rings: '<svg viewBox="0 0 48 48"><ellipse cx="14" cy="24" rx="6" ry="11"/><ellipse cx="34" cy="24" rx="6" ry="11"/><path d="M4 24h40"/></svg>',
  cargo_drop: '<svg viewBox="0 0 48 48"><path d="M10 10h28M24 10v8"/><rect x="16" y="26" width="16" height="12" rx="1"/><path d="M24 18v8M19 22l5 4 5-4"/></svg>',
  spraying: '<svg viewBox="0 0 48 48"><path d="M8 14h32M24 14v6"/><path d="M14 26l-4 14M24 26v14M34 26l4 14"/><circle cx="24" cy="22" r="3"/></svg>',
  dogfight: '<svg viewBox="0 0 48 48"><path d="M10 34l10-8-6-4zM38 14l-10 8 6 4z"/><circle cx="24" cy="24" r="16" stroke-dasharray="3 4"/></svg>',
  facility_defense: '<svg viewBox="0 0 48 48"><path d="M24 6l14 6v10c0 9-6 16-14 20-8-4-14-11-14-20V12z"/><path d="M18 24h12M24 18v12"/></svg>',
  ship_defense: '<svg viewBox="0 0 48 48"><path d="M6 30h36l-5 9H11z"/><path d="M14 30v-8h14v8M20 22v-8h6"/><path d="M6 43c4 2 8 2 12 0s8-2 12 0 8 2 12 0"/></svg>',
};
const LT = (k, p, fb) => { const r = tr(k, p); return r && r !== k ? r : (fb ?? k); };

/** Tür uygunluğu (saf; test edilir): {ok, reason?} — araç tipi, parkur türü (hazır parkurda yalnız halka toplama), gerekli eklenti. */
export function modeAvailability(mode, drone, trackKind) {
  if (!mode || !drone) return { ok: false, reason: 'no_drone' };
  if (Array.isArray(mode.types) && !mode.types.includes(drone.type)) return { ok: false, reason: 'type' };
  if (trackKind === 'match' && mode.id !== 'rings') return { ok: false, reason: 'course' };
  if (trackKind === 'match' && !['multirotor', 'fpv', 'heli'].includes(drone.type)) return { ok: false, reason: 'type' };
  const need = mode.requires?.addon;
  if (need && !(drone.equipment?.addons || {})[need]) return { ok: false, reason: 'addon', addon: need };
  return { ok: true };
}
/** Parkur sekmeleri (saf): yalnız kaydı olan türler; ikisi de yoksa yalnız 'match'. */
export function trackTabs(tracks) {
  const c = (tracks || []).filter(x => x.world_mode === 'procedural').length, r = (tracks || []).filter(x => x.world_mode !== 'procedural').length;
  return ['match', ...(c ? ['custom'] : []), ...(r ? ['real'] : [])];
}
export const parseEmails = txt => [...new Set(String(txt || '').split(/[\s,;]+/).map(s => s.trim().toLowerCase()).filter(s => /^[^@\s]+@[^@\s]+\.[a-z]{2,}$/.test(s)))];
const genPw = () => Array.from(crypto.getRandomValues(new Uint8Array(6)), b => 'abcdefghjkmnpqrstuvwxyz23456789'[b % 31]).join('');

let pending = null;   // ayrıntı sihirbazına devredilen ön ayar (renderWizard tüketir)
export const takeFlowPreset = () => { const p = pending; pending = null; return p; };

export async function renderFlow(view, ctx) {
  const go = ctx.go;
  clear(view, h('div', { class: 'sm-fly sm-loading' }, LT('common.loading')));
  let drones = [], tracks = [], modes = [], courses = [], friends = [], meta = {};
  try {
    const [hg, tk, md, fc, fr, mm] = await Promise.all([net.get('/api/hangar'), net.get('/api/tracks'), net.get(`/api/modes?lang=${document.documentElement.lang || 'tr'}`),
      net.get('/api/fpv/courses').catch(() => ({ courses: [] })), net.get('/api/friends').catch(() => ({ friends: [] })), net.get('/api/match/meta').catch(() => ({}))]);
    drones = hg.drones || []; tracks = tk.tracks || []; modes = md.modes || []; courses = fc.courses || []; friends = fr.friends || []; meta = mm || {};
  } catch (e) { toastError(e); return; }
  if (meta.current) { go(lobbyHref(meta.current.id)); return; }
  if (!drones.length) { clear(view, h('div', { class: 'sm-fly sm-loading' }, h('p', null, LT('rm.no_drone')), h('button', { class: 'btn primary', type: 'button', onclick: () => go('#/hangar/new') }, LT('rm.to_hangar')))); return; }
  const S = { step: 0, drone: drones.find(d => d.is_default) || drones[0], tab: null, track: null, course: null, mode: null, players: 'single', ai: 1, maxp: 4, emails: '', friendIds: new Set(), level: 'normal' };
  const tabs = trackTabs(tracks);
  S.tab = tabs.includes('real') ? 'real' : tabs[tabs.length - 1];
  const modeById = id => modes.find(m => m.id === id);
  const trackKind = () => (S.course ? 'match' : S.track ? (S.track.world_mode === 'procedural' ? 'custom' : 'real') : null);
  const root = h('div', { class: 'rm-flow' });
  const steps = h('div', { class: 'rm-steps' });
  const body = h('div');
  const foot = h('div', { class: 'rm-flow-foot' });
  root.append(h('div', { class: 'rm-flow-head' }, h('div', null, h('h1', null, LT('rm.fly_title')), h('p', { class: 'muted' }, LT('rm.fly_sub'))), steps), body, foot,
    h('p', { class: 'rm-note', style: 'text-align:center' }, h('a', { href: '#/fly/classic' }, LT('rm.fly_classic'))));
  clear(view, root);
  ctx.setBack?.(LT('common.menu'), 'menu');
  const views = [];
  const drop = () => views.splice(0).forEach(v => { try { v.dispose(); } catch { /* */ } });
  const paintSteps = () => clear(steps, FLOW_STEPS.map((k, i) => h('i', { class: i === S.step ? 'on' : i < S.step ? 'done' : '' }, `${i + 1}. ${LT(`rm.fs_${k}`)}`)));
  const can = () => [!!S.drone, !!(S.track || S.course), !!S.mode && modeAvailability(modeById(S.mode), S.drone, trackKind()).ok, true][S.step];
  const navFoot = () => clear(foot,
    S.step > 0 ? h('button', { class: 'btn', type: 'button', onclick: () => { S.step--; draw(); } }, '‹ ', LT('common.back')) : null,
    S.step < FLOW_STEPS.length - 1 ? h('button', { class: 'btn primary', type: 'button', disabled: can() ? null : true, onclick: () => { if (can()) { S.step++; draw(); } } }, LT('common.next'), ' ›')
      : h('button', { class: 'btn primary rm-fly-btn', type: 'button', onclick: e => launch(e.currentTarget) }, LT('rm.fly_go')));
  const opt = ({ key, title, desc, icon, sel, off, chip, accent, onClick, bg }) => h('button', { type: 'button', class: `rm-opt small ${sel ? 'sel' : ''} ${off ? 'off' : ''}`, cssVars: { ac: accent || '#38bdf8' }, dataset: { key },
    'aria-disabled': off ? 'true' : null, title: off || null, onclick: () => { if (!off) onClick(); else toast(off, 'err'); } },
    bg || null, icon ? h('i', { class: 'rm-opt-ico', html: icon }) : null, chip ? h('span', { class: 'rm-chip' }, chip) : null, h('b', null, title), desc ? h('span', null, desc) : null);

  async function draw() {
    drop(); paintSteps();
    const k = FLOW_STEPS[S.step];
    if (k === 'drone') {
      const { miniDroneView } = await import('../hangar/index.js');
      const cards = drones.map(d => { const bg = h('div', { class: 'rm-opt-bg' }); const c = opt({ key: `d${d.id}`, title: d.name, desc: `${LT(`types.${d.type}`)} · ${d.model_label || d.model_key}`, sel: S.drone?.id === d.id, accent: d.color, bg,
        onClick: () => { S.drone = d; S.mode = null; draw(); } }); miniDroneView(bg, d).then(v => views.push(v)).catch(() => {}); return c; });
      clear(body, h('div', { class: 'rm-mode-grid' }, cards));
    } else if (k === 'track') {
      const tabBar = h('div', { class: 'rm-tabs' }, h('div', { class: 'seg' }, tabs.map(tb => h('button', { type: 'button', class: S.tab === tb ? 'on' : '', onclick: () => { S.tab = tb; draw(); } }, LT(`rm.tr_${tb}`)))));
      let cards;
      if (S.tab === 'match') cards = courses.map(c => opt({ key: `c${c.id}`, title: LT(`fpv.c_${c.id}`, null, c.name), desc: [LT(`fpv.v_${c.id}`, null, c.venue_name), `${Math.round(c.length_m)} m`].join(' · '), chip: '★'.repeat(c.difficulty || 1), accent: '#f97316',
        sel: S.course === c.id, onClick: () => { S.course = c.id; S.track = null; S.mode = 'rings'; draw(); } }));
      else cards = tracks.filter(x => (S.tab === 'custom') === (x.world_mode === 'procedural')).map(x => opt({ key: `t${x.id}`, title: x.name, desc: [LT(`rm.w_${x.weather}`), S.tab === 'custom' ? LT(`rm.biome_${x.world?.biome || 'forest'}`) : `${(x.radius_m * 2 / 1000).toFixed(1)} km`].join(' · '),
        accent: S.tab === 'custom' ? '#34d399' : '#38bdf8', sel: S.track?.id === x.id, bg: h('img', { class: 'rm-opt-bg', src: x.preview_png, alt: '', loading: 'lazy', style: 'object-fit:cover' }),
        onClick: () => { S.track = x; S.course = null; if (S.mode && !modeAvailability(modeById(S.mode), S.drone, trackKind()).ok) S.mode = null; draw(); } }));
      clear(body, tabs.length > 1 ? tabBar : null, h('div', { class: 'rm-mode-grid' }, cards));
    } else if (k === 'mode') {
      clear(body, h('div', { class: 'rm-mode-grid' }, MODE_ORDER.map(id => modeById(id)).filter(Boolean).map(m => {
        const av = modeAvailability(m, S.drone, trackKind());
        return opt({ key: m.id, title: LT(`rm.mode_${m.id}`, null, m.label), desc: LT(`rm.mode_${m.id}_desc`), icon: MODE_ICON[m.id], sel: S.mode === m.id, accent: m.defend ? '#ef4444' : m.engine === 'match' ? '#fbbf24' : '#38bdf8',
          chip: m.multiplayer ? LT('rm.multi_ok') : null, off: av.ok ? null : LT(`rm.na_${av.reason}`, { a: LT(`rm.addon_${av.addon || ''}`) }), onClick: () => { S.mode = m.id; draw(); } });
      })), S.mode && modeById(S.mode)?.engagement ? h('p', { class: 'rm-note' }, LT('rm.engagement_rule')) : null);
    } else {
      const m = modeById(S.mode);
      let sugg = { count: 0 };
      try { sugg = await net.get(`/api/modes/${S.mode}/ai`); } catch { /* */ }
      const maxV = meta.limits?.players?.[1] || 8;
      if (!m.multiplayer) S.players = 'single';
      const single = opt({ key: 'single', title: LT('match.mode_solo'), desc: sugg.count ? LT(sugg.kind === 'target_drone' ? 'rm.ai_targets' : 'rm.ai_auto', { n: sugg.count }) : LT('rm.ai_none'), sel: S.players === 'single', accent: '#38bdf8', onClick: () => { S.players = 'single'; draw(); } });
      const multi = opt({ key: 'multi', title: LT('match.mode_multi'), desc: LT('rm.multi_desc'), sel: S.players === 'multi', accent: '#fbbf24', off: m.multiplayer ? null : LT('rm.na_multi'), onClick: () => { S.players = 'multi'; draw(); } });
      const extra = [];
      if (S.players === 'multi') {
        const df = S.mode === 'dogfight';
        const em = h('textarea', { class: 'input', placeholder: LT('rm.emails_ph'), oninput: e => { S.emails = e.target.value; cnt.textContent = LT('rm.emails_n', { n: parseEmails(S.emails).length }); } }, S.emails);
        const cnt = h('small', { class: 'rm-note' }, LT('rm.emails_n', { n: parseEmails(S.emails).length }));
        extra.push(h('div', { class: 'rm-xp-card rm-inv-box' }, h('b', null, '✉ ', LT('rm.invite_email')), em, cnt,
          friends.length ? [h('b', null, '☺ ', LT('rm.invite_friends')), h('div', { class: 'rm-friend-pick' }, friends.map(f => h('label', null, h('input', { type: 'checkbox', checked: S.friendIds.has(f.user_id) ? true : null, onchange: e => { if (e.target.checked) S.friendIds.add(f.user_id); else S.friendIds.delete(f.user_id); } }), f.name)))] : h('small', { class: 'rm-note' }, LT('rm.no_friends_short')),
          df ? h('p', { class: 'rm-note' }, LT('rm.df_two')) : [h('div', { class: 'rm-row' }, h('label', null, LT('rm.max_humans')), numSel(2, maxV, S.maxp, v => { S.maxp = v; })),
            h('div', { class: 'rm-row' }, h('label', null, LT('rm.ai_count')), numSel(0, maxV - 1, S.ai, v => { S.ai = v; }))],
          h('p', { class: 'rm-note' }, LT('rm.invite_note'))));
      }
      if ((S.players === 'single' && sugg.count && sugg.kind === 'pilot') || (S.players === 'multi' && S.ai > 0)) {
        extra.push(h('div', { class: 'rm-row' }, h('label', null, LT('ai.level')), h('div', { class: 'seg' }, ['easy', 'normal', 'hard'].map(l => h('button', { type: 'button', class: S.level === l ? 'on' : '', onclick: () => { S.level = l; draw(); } }, LT(`ai.level_${l}`))))));
      }
      clear(body, h('div', { class: 'rm-mode-grid' }, single, multi), ...extra,
        h('p', { class: 'rm-note' }, [S.drone.name, S.course ? LT(`fpv.c_${S.course}`) : S.track?.name, LT(`rm.mode_${S.mode}`)].join(' · ')));
    }
    navFoot();
  }
  const numSel = (lo, hi, v, on) => h('select', { class: 'input', onchange: e => on(Number(e.target.value)) }, Array.from({ length: hi - lo + 1 }, (_, i) => h('option', { value: lo + i, selected: lo + i === v ? true : null }, String(lo + i))));

  async function launch(btnEl) {
    const m = modeById(S.mode);
    btnEl.disabled = true;
    try {
      if (m.engine === 'fly') {   // ayrıntı sihirbazı: kalkış · güç · görev · saha · pilot (dron/parkur/tür hazır)
        pending = { drone_id: S.drone.id, track_id: S.track.id, mode: S.mode, skip_to: 'launch', ...(m.defend ? { site: { station: true }, defend: {} } : {}) };
        drop(); go('#/fly/solo'); return;
      }
      const base = { drone_id: S.drone.id, mode: S.mode, launch: { method: 'wheels' } };
      const where = S.course ? { kind: 'fpv', fpv: { course_id: S.course } } : { track_id: S.track.id, kind: S.mode === 'dogfight' ? 'dogfight' : 'rings' };
      let r;
      if (S.players === 'single') {
        if (S.mode === 'dogfight') r = await net.post('/api/match/ai', { ...base, ...where, level: S.level });
        else r = await net.post('/api/match/solo', { ...base, ...where });
      } else {
        r = await createMatch({ ...base, ...where, password: genPw(), max_players: S.mode === 'dogfight' ? 2 : S.maxp });
        const emails = parseEmails(S.emails), fids = [...S.friendIds];
        if (emails.length || fids.length) {
          try {
            const inv = await net.post(`/api/match/${r.id}/invites`, { emails, friend_ids: fids });
            toast(LT(inv.mail_enabled ? 'rm.invites_sent' : 'rm.invites_links', { n: inv.invites.length }));
          } catch (e) { toastError(e); }
        }
        for (let i = 0; i < (S.mode === 'dogfight' ? 0 : S.ai); i++) { try { await net.post(`/api/match/${r.id}/bot`, { level: S.level }); } catch (e) { toastError(e); break; } }
      }
      drop(); go(lobbyHref(r.id));
    } catch (e) { toastError(e); btnEl.disabled = false; }
  }
  draw();
  return () => drop();
}
