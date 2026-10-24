// Sağ üst PİLOT MENÜSÜ (yol haritası "Pilot"): kabuk çipi (avatar + ad + seviye) → açılır menü: Özelleştir · Önceki uçuşlarım · Arkadaşlarım ·
// Davetler (bekleyen sayı rozeti; GET /api/invites) · TOP 10 · Görevler · Ayarlar. Çipteki seviye varsayılan pilotun (GET /api/crew).
import * as api from '../core/api.js';
import { h, clear } from '../core/dom.js';
import { t } from '../i18n/i18n.js';
import * as sfx from './sfx.js';

let pop = null, invites = 0, pilot = null, pollT = 0;

/** Menü öğeleri (saf; test edilir): [{key, href|action}] */
export const PILOT_ITEMS = [
  { key: 'customize', href: '#/crew/edit' },
  { key: 'flights', href: '#/pilot/flights' },
  { key: 'friends', href: '#/pilot/friends' },
  { key: 'invites', href: '#/pilot/invites' },
  { key: 'top10', action: 'top10' },
  { key: 'missions', href: '#/missions' },
  { key: 'settings', href: '#/settings' },
];

export function levelBadge(p) {
  if (!p) return null;
  const pct = Math.round(Math.max(0, Math.min(1, Number(p.progress) || 0)) * 100);
  return h('span', { class: 'rm-lvl', title: t('rm.level_title', { l: p.level, x: p.xp }) }, h('b', null, t('rm.lv', { l: p.level || 1 })),
    h('i', { class: 'rm-lvl-bar' }, h('i', { style: `width:${pct}%` })));
}

export async function refreshPilot(chip) {
  try {
    const r = await api.get('/api/crew');
    pilot = (r.pilots || []).find(p => p.is_default) || (r.pilots || [])[0] || null;
  } catch { pilot = null; }
  try { invites = (await api.get('/api/invites')).count || 0; } catch { invites = 0; }
  paintChip(chip);
  return pilot;
}

function paintChip(chip) {
  if (!chip) return;
  const sub = chip.querySelector('#chip-sub');
  if (sub && pilot) clear(sub, levelBadge(pilot), pilot.name ? ` ${pilot.name}` : '');
  let dot = chip.querySelector('.rm-inv-dot');
  if (invites > 0) {
    if (!dot) { dot = h('span', { class: 'rm-inv-dot' }); chip.append(dot); }
    dot.textContent = String(invites > 9 ? '9+' : invites);
    dot.title = t('rm.invites_n', { n: invites });
  } else dot?.remove();
}

export function closePilotMenu() { pop?.remove(); pop = null; document.removeEventListener('pointerdown', outside, true); document.removeEventListener('keydown', esc); }
const outside = e => { if (pop && !pop.contains(e.target) && !e.target.closest?.('#chip')) closePilotMenu(); };
const esc = e => { if (e.key === 'Escape') closePilotMenu(); };

export function togglePilotMenu(chip, ctx) {
  if (pop) { closePilotMenu(); return; }
  sfx.select();
  const item = it => h('button', { type: 'button', class: `rm-pm-item k-${it.key}`, role: 'menuitem', dataset: { key: it.key }, onclick: async () => {
    closePilotMenu(); sfx.tick();
    if (it.action === 'top10') { (await import('../menu/top10.js')).openTop10(); return; }
    location.hash = it.href;
  } }, h('span', { class: 'rm-pm-ico', 'aria-hidden': 'true' }, ICONS[it.key] || '•'), h('span', null, t(`rm.pm_${it.key}`)),
    it.key === 'invites' && invites > 0 ? h('b', { class: 'rm-pm-badge' }, String(invites)) : null);
  pop = h('div', { class: 'rm-pilot-menu', role: 'menu', 'aria-label': t('rm.pilot_menu') },
    pilot ? h('div', { class: 'rm-pm-head' }, h('b', null, pilot.name), levelBadge(pilot),
      h('small', { class: 'muted' }, pilot.next_level_xp ? t('rm.xp_to_next', { x: pilot.xp, n: pilot.next_level_xp }) : t('rm.max_level')),
      (pilot.medals || []).length ? h('span', { class: 'rm-medals-mini' }, (pilot.medals || []).map(m => h('i', { class: `rm-medal m-${m}`, title: t(`rm.medal_${m}`) }))) : null) : null,
    PILOT_ITEMS.map(item));
  document.body.append(pop);
  setTimeout(() => { document.addEventListener('pointerdown', outside, true); document.addEventListener('keydown', esc); pop?.querySelector('button')?.focus(); }, 0);
  ctx?.track?.('pilot_menu');
}

const ICONS = { customize: '✎', flights: '⟲', friends: '☺', invites: '✉', top10: '🏆', missions: '⌖', settings: '⚙' };

export function startInvitePoll(chip) {
  clearInterval(pollT);
  pollT = setInterval(async () => { try { invites = (await api.get('/api/invites')).count || 0; paintChip(chip); } catch { /* çevrimdışı */ } }, 45000);
}
