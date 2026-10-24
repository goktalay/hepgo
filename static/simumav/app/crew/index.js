// Mürettebat: pilot kartları (3B avatar görüntüsü, isim, uçuş/saat), yeni pilot / düzenle → KARAKTER YARATMA (§25 + §28: canlı dönen TAM BOY 3B
// önizleme + Tam boy/Yüz yakınlaştırma; sekmeler Beden · Yüz · Saç · Kıyafet · Aksesuar; "Rastgele" (+ "Cinsiyeti koru"); eski 2B karakterler hazır başlangıç),
// varsayılan seç, sil. Avatar pilotla birlikte saklanır (POST/PUT /api/crew {avatar}).
import * as api from '../core/api.js';
import { h, clear, svg } from '../core/dom.js';
import { t } from '../i18n/i18n.js';
import { screen, plusButton, miniBtn, toast, toastErr, confirmDlg, modal, EDIT_SVG, TRASH_SVG, STAR_SVG } from '../ui/components.js';
import { stagger } from '../ui/transition.js';
import { ACCESSORIES, BEARDS, BODIES, BROWS, BROW_W, BUILDS, EYES, EYE_COLORS, FACES, GLASSES, HAIRS, HAIR_BY_BODY, HAIR_COLORS, HAIR_FANCY, HEADGEAR, HELMET_COLORS, LEGACY, MOUTHS, NOSES, OUTFITS, PATCHES, PATCH_COLORS, SKINS, SUIT_COLORS, VISOR_COLORS,
  avatarBody, legacy, normAvatar, randomAvatar, switchBody } from './avatar_core.js';
import { drawPatch } from './avatar_mesh.js';
import { avatarImg, ensureAvatarCss, mountAvatarStage } from './avatar3d.js';
import { levelBadge } from '../ui/pilotmenu.js';   // yol haritası: seviye rozeti (Pilot menüsüyle aynı)

/** Seviye / XP / madalya paneli (yol haritası: seviye 1–100; doğrulanmamış XP ayrı tarama deseniyle). */
export function xpPanel(p, levels = null) {
  const span = Math.max(1, (p.next_level_xp ?? p.xp) - (p.level_xp ?? 0));
  const pv = p.next_level_xp ? Math.max(0, Math.min(1, ((p.xp_verified ?? p.xp) - (p.level_xp ?? 0)) / span)) : 1;
  const pt = p.next_level_xp ? Math.max(0, Math.min(1, (p.xp - (p.level_xp ?? 0)) / span)) : 1;
  const medals = (levels?.medals || [5, 10, 25, 50, 75, 100].map((l, i) => ({ id: ['wings_bronze', 'wings_silver', 'wings_gold', 'wings_platinum', 'wings_diamond', 'wings_legend'][i], level: l })));
  return h('div', { class: 'rm-xp-card', dataset: { pid: String(p.id) } },
    h('div', { class: 'rm-switch' }, h('b', { class: 'title md' }, p.name), levelBadge(p),
      h('span', { class: 'rm-note' }, p.next_level_xp ? t('rm.xp_to_next', { x: p.xp, n: p.next_level_xp }) : t('rm.max_level'))),
    h('div', { class: 'rm-xp-bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(pt * 100)) },
      h('u', { style: `width:${(pt * 100).toFixed(1)}%` }), h('i', { style: `width:${(pv * 100).toFixed(1)}%` })),
    p.xp_unverified ? h('span', { class: 'rm-note' }, t('rm.xp_unverified', { x: p.xp_unverified })) : null,
    h('div', { class: 'rm-medal-row' }, medals.map(m => h('div', { class: 'rm-medal-cell', title: t(`rm.medal_${m.id}`) },
      h('i', { class: `rm-medal big m-${m.id} ${(p.medals || []).includes(m.id) ? '' : 'off'}` }), h('b', null, t(`rm.medal_${m.id}`)), h('small', null, t('rm.lv', { l: m.level }))))));
}

const CHARS = Object.keys(LEGACY);

export async function mount(root, ctx) {
  ensureAvatarCss();
  const sc = screen({ title: t('crew.title'), sub: t('crew.sub') });
  const grid = h('div', { class: 'grid crew-grid' });
  const top = h('div', { class: 'rm-crew-top', style: 'width:min(1180px,100%);margin:0 auto 16px;display:grid;gap:12px' });   // pilot değiştir + seviye paneli
  sc.classList.add('scroll'); sc.append(top, grid);
  let levels = null;
  api.get('/api/crew/levels').then(r => { levels = r; renderTop(); }).catch(() => {});
  clear(root, sc);
  ctx.setBack(t('common.menu'));
  let pilots = [];

  const fmtH = v => `${(Number(v) || 0).toFixed(1)} ${t('common.h')}`;
  const card = p => {
    const c = h('div', { class: `card lift pilot-card ${p.is_default ? 'sel' : ''}`, tabindex: '0', dataset: { pid: String(p.id) } },
      h('div', { class: 'row-actions' },
        miniBtn(svg('0 0 24 24', STAR_SVG), () => setDefault(p), '', t('common.default')),
        miniBtn(svg('0 0 24 24', EDIT_SVG), () => openEditor(p), '', t('avatar.edit')),
        miniBtn(svg('0 0 24 24', TRASH_SVG), () => remove(p), 'danger', t('common.delete'))),
      h('div', { class: 'face av3d' }, avatarImg(p.avatar, { size: 256, alt: '' })),
      h('b', {}, p.name), levelBadge(p),
      p.is_default ? h('span', { class: 'badge accent' }, t('crew.default_pilot')) : h('span', { class: 'badge' }, t('crew.pilot')),
      h('div', { class: 'meta' }, h('span', {}, h('b', {}, p.flights ?? 0), ` ${t('crew.flights')}`), h('span', {}, h('b', {}, fmtH(p.hours)))));
    c.addEventListener('dblclick', () => openEditor(p));
    c.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target === c) openEditor(p); });
    return c;
  };

  function renderTop() {
    const cur = pilots.find(p => p.is_default) || pilots[0];
    if (!cur) { clear(top); return; }
    const sel = h('select', { class: 'input', 'aria-label': t('rm.switch_pilot'), onchange: async e => { const p = pilots.find(x => x.id === Number(e.target.value)); if (p) await setDefault(p); } },
      pilots.map(p => h('option', { value: p.id, selected: p.id === cur.id }, `${p.name} · ${t('rm.lv', { l: p.level || 1 })}`)));
    clear(top, h('div', { class: 'rm-switch' }, h('b', null, t('rm.switch_pilot')), sel), xpPanel(cur, levels));
  }
  const render = () => {
    renderTop();
    const cards = pilots.map(card);
    clear(grid, cards, h('div', { class: 'pilot-card plus-holder' }, plusButton(t('crew.new'), () => openEditor(null), { small: true })));
    stagger([...grid.children], 50);
  };
  const load = async () => { try { pilots = (await api.get('/api/crew')).pilots || []; } catch (e) { toastErr(e); pilots = []; } render(); };
  const remove = async p => { if (!await confirmDlg(t('crew.delete_q', { name: p.name }), { danger: true })) return; try { await api.del(`/api/crew/${p.id}`); toast(t('common.deleted'), 'ok'); await load(); window.dispatchEvent(new Event('sm:session')); } catch (e) { toastErr(e); } };
  const setDefault = async p => { try { await api.put(`/api/crew/${p.id}`, { is_default: 1 }); await load(); } catch (e) { toastErr(e); } };

  async function openEditor(p) {
    const isNew = !p;
    let character = p?.character || CHARS[1];
    let A = normAvatar(p?.avatar, character);
    const name = h('input', { class: 'input big', placeholder: t('crew.name_ph'), maxlength: '40', value: p?.name || '', 'aria-label': t('avatar.name') });
    const view = h('div', { class: 'av-stage full', 'aria-label': t('avatar.preview'), role: 'img' }, h('span', { class: 'av-hint' }, t('avatar.drag')));
    let live = null;
    const upd = () => { live?.set(A, name.value.trim()); paint(); };
    const setA = patch => { A = normAvatar({ ...A, ...patch }); upd(); };
    const sw = (key, colors, extra = null) => {
      const row = h('div', { class: 'av-sw', role: 'radiogroup', 'aria-label': t(`avatar.${key}`) });
      const pick = h('input', { type: 'color', class: 'av-pick', value: A[key], title: t('avatar.custom'), 'aria-label': t('avatar.custom'), dataset: { pk: key },
        oninput: e => { A = { ...A, [key]: e.target.value.toLowerCase() }; upd(); } });
      for (const c of colors) {
        if (extra && c === extra.breakBefore) row.append(h('span', { class: 'av-sep', title: extra.label }, '✦'));
        row.append(h('button', { type: 'button', class: 'av-dot', cssVars: { c }, dataset: { k: key, v: c }, title: c, 'aria-label': c, onclick: () => { A = { ...A, [key]: c }; pick.value = c; upd(); } }));
      }
      row.append(pick);
      return row;
    };
    /** Metin seçenekleri (enum): data-k / data-v; etiket avatar.<key>_<v>. */
    const opts = (key, list, { cls = '' } = {}) => h('div', { class: `av-opts txt ${cls}`, role: 'radiogroup', 'aria-label': t(`avatar.${key}`) },
      list.map(v => h('button', { type: 'button', class: 'av-opt', dataset: { k: key, v }, onclick: () => setA(key === 'body' ? switchBody(A, v) : { [key]: v }) }, t(`avatar.${key}_${v}`))));
    const toggle = (key, label) => { const i = h('input', { type: 'checkbox', dataset: { tk: key }, onchange: e => setA({ [key]: e.target.checked }) }); i.checked = !!A[key]; return h('label', { class: 'av-toggle', dataset: { f: key } }, i, h('span', null, label)); };
    const skins = h('div', { class: 'av-sw', role: 'radiogroup', 'aria-label': t('avatar.skin') },
      Object.entries(SKINS).map(([k, c]) => h('button', { type: 'button', class: 'av-dot skin', cssVars: { c }, dataset: { k: 'skin', v: k }, 'aria-label': `${t('avatar.skin')} ${k.slice(1)}`, onclick: () => { A = { ...A, skin: k }; upd(); } })));
    const patchIcon = kind => { const c = h('canvas', { width: 44, height: 44 }); drawPatch(c.getContext('2d'), kind, A.patch_color, 22, 22, 19); return c; };
    const patches = h('div', { class: 'av-opts', role: 'radiogroup', 'aria-label': t('avatar.patch') });
    const drawPatches = () => clear(patches, PATCHES.map(k => h('button', { type: 'button', class: `av-opt ${A.patch === k ? 'on' : ''}`, dataset: { k: 'patch', v: k }, title: t(`avatar.patch_${k}`), 'aria-label': t(`avatar.patch_${k}`),
      onclick: () => { A = { ...A, patch: k }; upd(); } }, k === 'none' ? h('span', { class: 'av-none' }, '∅') : patchIcon(k))));
    const accs = h('div', { class: 'av-opts txt', role: 'radiogroup', 'aria-label': t('avatar.accessory') },
      ACCESSORIES.map(k => h('button', { type: 'button', class: 'av-opt', dataset: { k: 'accessory', v: k }, onclick: () => { A = { ...A, accessory: k }; upd(); } }, t(`avatar.acc_${k}`))));
    const mirrorIn = h('input', { type: 'checkbox', onchange: e => { A = { ...A, mirror: e.target.checked }; upd(); } });
    mirrorIn.checked = !!A.mirror;
    const mirror = h('label', { class: 'av-toggle' }, mirrorIn, h('span', null, t('avatar.mirror')));
    const presets = h('div', { class: 'av-presets', role: 'radiogroup', 'aria-label': t('avatar.presets') },
      CHARS.map(c => h('button', { type: 'button', class: 'av-preset', dataset: { c }, title: c, 'aria-label': `${t('avatar.presets')} ${c}`,
        onclick: () => { character = c; A = legacy(c); syncInputs(); upd(); } }, h('img', { src: `/app/img/pilots/${c}.svg`, alt: '' }))));
    const field = (f, label, ...kids) => h('div', { class: 'av-field', dataset: { f } }, h('span', { class: 'av-lbl' }, label), ...kids);
    // saç modelleri: seçili bedenin listesi önce (her iki beden her stili seçebilir)
    const hairBox = h('div', { class: 'av-opts txt', role: 'radiogroup', 'aria-label': t('avatar.hair') });
    const drawHair = () => { const first = HAIR_BY_BODY[A.body] || []; clear(hairBox, [...first, ...HAIRS.filter(x => !first.includes(x))].map(v => h('button', { type: 'button', class: `av-opt ${first.includes(v) ? '' : 'alt'}`, dataset: { k: 'hair', v }, onclick: () => setA({ hair: v }) }, t(`avatar.hair_${v}`)))); };
    // §28 sekmeler: Beden · Yüz · Saç · Kıyafet · Aksesuar
    const TABS = [
      ['body', [isNew ? null : field('name', t('avatar.name'), name), field('presets', t('avatar.presets'), presets), field('body', t('avatar.body'), opts('body', BODIES)),
        field('build', t('avatar.build'), opts('build', BUILDS)), field('skin', t('avatar.skin'), skins)]],
      ['face', [field('face', t('avatar.face'), opts('face', FACES)), field('eyes', t('avatar.eyes'), opts('eyes', EYES)), field('eye_color', t('avatar.eye_color'), sw('eye_color', EYE_COLORS)),
        field('brows', t('avatar.brows'), opts('brows', BROWS)), field('brow_w', t('avatar.brow_w'), opts('brow_w', BROW_W)), field('nose', t('avatar.nose'), opts('nose', NOSES)),
        field('mouth', t('avatar.mouth'), opts('mouth', MOUTHS)), field('beard', t('avatar.beard'), opts('beard', BEARDS)),
        field('marks', t('avatar.marks'), h('div', { class: 'av-sw' }, toggle('freckles', t('avatar.freckles')), toggle('mole', t('avatar.mole')))), field('glasses', t('avatar.glasses'), opts('glasses', GLASSES))]],
      ['hair', [field('hair', t('avatar.hair'), hairBox), field('hair_color', t('avatar.hair_color'), sw('hair_color', HAIR_COLORS, { breakBefore: HAIR_FANCY[0], label: t('avatar.hair_fancy') }))]],
      ['outfit', [field('outfit', t('avatar.outfit'), opts('outfit', OUTFITS)), field('suit', t('avatar.suit'), sw('suit', SUIT_COLORS)), field('patch', t('avatar.patch'), patches),
        field('patch_color', t('avatar.patch_color'), sw('patch_color', PATCH_COLORS))]],
      ['acc', [field('headgear', t('avatar.headgear'), opts('headgear', HEADGEAR)), field('helmet', t('avatar.helmet'), sw('helmet', HELMET_COLORS)),
        field('visor', t('avatar.visor'), sw('visor', VISOR_COLORS), h('div', { class: 'av-sw' }, mirror, toggle('visor_open', t('avatar.visor_open')))), field('accessory', t('avatar.accessory'), accs)]],
    ];
    if (isNew) TABS.push(['name', [field('name', t('avatar.name'), name), h('p', { class: 'rm-note' }, t('rm.pilot_starts'))]]);   // yol haritası sihirbazı: cinsiyet/vücut → yüz → saç → kıyafet → aksesuar → ad soyad
    let tab = 'body';
    const panes = TABS.map(([k, kids]) => h('div', { class: 'av-pane', dataset: { pane: k }, role: 'tabpanel' }, ...kids));
    const tabBtns = TABS.map(([k]) => h('button', { type: 'button', class: 'av-tab', role: 'tab', dataset: { tab: k }, onclick: () => { tab = k; paintTabs(); } }, t(`avatar.tab_${k}`)));
    const paintTabs = () => { for (const b of tabBtns) { const on = b.dataset.tab === tab; b.classList.toggle('on', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); } for (const pn of panes) pn.hidden = pn.dataset.pane !== tab; };
    const order = TABS.map(([k]) => k);
    const stepNav = isNew ? h('div', { class: 'btn-row rm-wiz-nav' },
      h('button', { type: 'button', class: 'btn ghost', onclick: () => { const i = order.indexOf(tab); if (i > 0) { tab = order[i - 1]; paintTabs(); } } }, '‹ ', t('common.back')),
      h('button', { type: 'button', class: 'btn primary', onclick: () => { const i = order.indexOf(tab); if (i < order.length - 1) { tab = order[i + 1]; paintTabs(); if (tab === 'name') name.focus(); } } }, t('common.next'), ' ›')) : null;
    const form = h('div', { class: 'av-form' }, h('div', { class: 'av-tabs', role: 'tablist' }, tabBtns), ...panes, stepNav);
    const keepIn = h('input', { type: 'checkbox', class: 'av-keep' });
    const dice = h('button', { type: 'button', class: 'btn ghost av-dice', onclick: () => { A = randomAvatar(Math.random, { body: keepIn.checked ? A.body : null }); syncInputs(); upd(); } }, '🎲 ', t('avatar.random'));
    let zoom = 'body';
    const zoomBtns = ['body', 'face'].map(v => h('button', { type: 'button', class: 'av-zoom-btn', dataset: { zoom: v }, onclick: () => { zoom = v; live?.setView(v); paintZoom(); } }, t(`avatar.view_${v}`)));
    const paintZoom = () => zoomBtns.forEach(b => b.classList.toggle('on', b.dataset.zoom === zoom));
    view.append(h('div', { class: 'av-zoom', role: 'group', 'aria-label': t('avatar.zoom') }, zoomBtns));
    const box = h('div', { class: 'av-editor' }, h('div', { class: 'av-left' }, view, h('div', { class: 'av-dice-row' }, dice, h('label', { class: 'av-toggle' }, keepIn, h('span', null, t('avatar.keep_body'))))), form);
    function syncInputs() {
      for (const i of box.querySelectorAll('.av-pick')) { const k = i.dataset.pk; if (k && A[k]) i.value = A[k]; }
      mirrorIn.checked = !!A.mirror;
      for (const i of box.querySelectorAll('input[data-tk]')) i.checked = !!A[i.dataset.tk];
    }
    function paint() {
      drawPatches(); drawHair();
      for (const b of box.querySelectorAll('[data-k]')) b.classList.toggle('on', String(A[b.dataset.k]) === b.dataset.v);
      const same = JSON.stringify(normAvatar(A)) === JSON.stringify(legacy(character));
      for (const b of presets.children) b.classList.toggle('on', same && b.dataset.c === character);
      // bağlama göre alanlar: sakal yalnız erkek bedende; vizör/aksesuar yalnız kaskta; kask rengi etiketi başlığa göre
      const helmet = A.headgear === 'helmet';
      box.querySelector('.av-field[data-f="beard"]').hidden = A.body === 'f';
      box.querySelector('.av-field[data-f="visor"]').hidden = !helmet;
      box.querySelector('.av-field[data-f="accessory"]').hidden = !helmet;
      box.querySelector('.av-field[data-f="helmet"]').hidden = A.headgear === 'none';
      box.querySelector('.av-field[data-f="helmet"] .av-lbl').textContent = t(helmet ? 'avatar.helmet' : 'avatar.gear_color');
      syncInputs();
    }
    name.addEventListener('input', () => live?.set(A, name.value.trim()));
    const m = modal({ title: isNew ? t('crew.new') : t('avatar.edit_title', { name: p.name }), wide: true, body: box, onClose: () => { live?.dispose(); live = null; },
      actions: [{ label: t('common.cancel'), cls: 'ghost' }, { label: t('common.save'), cls: 'primary', onClick: async () => {
        const n = name.value.trim(); if (!n) { tab = isNew ? 'name' : 'body'; paintTabs(); name.focus(); return false; }
        try {
          if (isNew) { await api.post('/api/crew', { name: n, character, avatar: avatarBody(A) }); toast(t('crew.welcome', { name: n }), 'ok'); }
          else { await api.put(`/api/crew/${p.id}`, { name: n, character, avatar: avatarBody(A) }); toast(t('common.saved'), 'ok'); }
          await load(); window.dispatchEvent(new Event('sm:session'));
        } catch (e) { toastErr(e); return false; }
      } }] });
    m.box.classList.add('av-modal');
    paintTabs(); paint(); paintZoom();
    try { live = await mountAvatarStage(view, A, { name: name.value.trim(), pose: 'full', view: zoom }); } catch { view.append(avatarImg(A, { size: 256 })); }
    window.__smAvatarEditor = { get avatar() { return A; }, set: v => { A = normAvatar(v); syncInputs(); upd(); }, tab: k => { tab = k; paintTabs(); }, zoom: v => { zoom = v; live?.setView(v); paintZoom(); }, get live() { return live; } };   // teşhis (Playwright)
  }
  await load();
  if (ctx.param === 'new') openEditor(null);
  if (ctx.param === 'edit') { const p = pilots.find(x => x.is_default) || pilots[0]; if (p) openEditor(p); }   // Pilot menüsü › Özelleştir
}
