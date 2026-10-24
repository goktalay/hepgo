// HANGAR "+ Yeni" / Düzenle sihirbazı (yol haritası "Hangar"): 1 dron tipi (Çok motorlu · Sabit kanat · VTOL · Rover) → 2 model (alt gruplar:
// 4 / 6 pervaneli, helikopter · CAYMAZ V3 + uçaklar · VTOL + INTERCEPTOR · kara araçları; her kart dönen 3B model) → 3 performans (azami hız →
// tipe göre SITL parametresi, azami irtifa, tip/modele göre parametre tablosu; beyaz liste sunucuda) → 4 kamera (gündüz / gece görüşü / termal /
// multispektral) → 5 eklentiler (ilaçlama / paket bırakma / paraşüt; tipe uymayan pasif) → 6 görünüm (ad, renk, ikinci renk, desen, çağrı adı,
// logo / çıkartma yükleme) → kaydet (POST/PUT /api/hangar {…, equipment}; görseller POST /api/hangar/{id}/decals) → hangara iniş.
// Parametreler + script'ler kalıcıdır; Mission Planner'dan değiştirilenler uçuş sonunda kayda geçer (sunucu params_hasat).
import * as api from '../core/api.js';
import { h, clear } from '../core/dom.js';
import { t } from '../i18n/i18n.js';
import { btn, toast, toastErr, range, segment } from '../ui/components.js';
import { stagger } from '../ui/transition.js';
import * as sfx from '../ui/sfx.js';

export const CATEGORIES = [
  { key: 'multi', types: ['fpv', 'multirotor', 'heli'], accent: '#38bdf8' },
  { key: 'plane', types: ['plane'], accent: '#fbbf24' },
  { key: 'vtol', types: ['vtol', 'interceptor'], accent: '#a78bfa' },
  { key: 'rover', types: ['rover'], accent: '#34d399' },
];
export const categoryOf = type => (CATEGORIES.find(c => c.types.includes(type)) || CATEGORIES[0]).key;
// Model alt grubu (saf; test edilir): pervane sayısı / CAYMAZ / INTERCEPTOR
const HEXA = ['glb:typhoon_h480', 'builtin:hexa'];
const OCTA = ['builtin:octa', 'glb:octa', 'smv:octa', 'smv:cargo_x8'];
export function subgroupOf(type, key) {
  const k = String(key || '');
  if (type === 'heli') return 'heli';
  if (type === 'fpv' || type === 'multirotor') return OCTA.includes(k) ? 'rotor8' : HEXA.includes(k) ? 'rotor6' : 'rotor4';
  if (type === 'plane') return /caymaz/.test(k) ? 'caymaz' : 'planes';
  if (type === 'interceptor') return 'interceptor';
  if (type === 'vtol') return 'vtol';
  return 'rover';
}
export const SUBGROUP_ORDER = ['rotor4', 'rotor6', 'rotor8', 'heli', 'caymaz', 'planes', 'vtol', 'interceptor', 'rover'];
// Azami hız → SITL parametresi (ArduPilot adları; beyaz listede): kopter WPNAV_SPEED / LOIT_SPEED (cm/s), uçak AIRSPEED_MAX + AIRSPEED_CRUISE (m/s),
// VTOL Q_WP_SPEED (cm/s, dikey kip) + AIRSPEED_MAX, kara aracı CRUISE_SPEED (m/s)
export function speedParams(type, ms) {
  const v = Math.max(1, Number(ms) || 0);
  if (type === 'fpv' || type === 'multirotor' || type === 'heli') return { WPNAV_SPEED: Math.round(v * 100), LOIT_SPEED: Math.round(v * 100) };
  if (type === 'plane' || type === 'interceptor') return { AIRSPEED_MAX: Math.round(v), AIRSPEED_CRUISE: Math.round(v * 0.7) };
  if (type === 'vtol') return { AIRSPEED_MAX: Math.round(v), AIRSPEED_CRUISE: Math.round(v * 0.7), Q_WP_SPEED: Math.min(2000, Math.round(v * 40)) };
  return { CRUISE_SPEED: Math.round(v * 10) / 10 };
}
export const SPEED_RANGE = { fpv: [5, 45, 25], multirotor: [3, 25, 12], heli: [3, 30, 15], plane: [12, 60, 25], interceptor: [30, 170, 95], vtol: [12, 45, 22], rover: [1, 20, 5] };
// Tipe göre önerilen ayar parametreleri (tablo satırları; değer boşsa SITL varsayılanı)
export const TYPE_PARAMS = {
  fpv: ['ANGLE_MAX', 'ACRO_RP_RATE', 'ACRO_Y_RATE', 'PILOT_SPEED_UP', 'LAND_SPEED', 'ATC_RAT_RLL_P', 'ATC_RAT_PIT_P'],
  multirotor: ['ANGLE_MAX', 'PILOT_SPEED_UP', 'PILOT_SPEED_DN', 'LAND_SPEED', 'WPNAV_ACCEL', 'RTL_ALT', 'ATC_RAT_RLL_P'],
  heli: ['ANGLE_MAX', 'PILOT_SPEED_UP', 'LAND_SPEED', 'RTL_ALT'],
  plane: ['TRIM_THROTTLE', 'LIM_ROLL_CD', 'LIM_PITCH_MAX', 'LIM_PITCH_MIN', 'TECS_CLMB_MAX', 'TECS_SINK_MAX', 'RTL_RADIUS'],
  interceptor: ['TRIM_THROTTLE', 'LIM_ROLL_CD', 'TECS_CLMB_MAX', 'THR_MAX'],
  vtol: ['Q_ANGLE_MAX', 'Q_TRANSITION_MS', 'TRIM_THROTTLE', 'LIM_ROLL_CD', 'TECS_CLMB_MAX'],
  rover: ['CRUISE_THROTTLE', 'WP_RADIUS', 'WP_SPEED'],
};
const PATTERNS = ['solid', 'stripe', 'split', 'camo', 'checker'];
const COLORS = ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f87171', '#f472b6', '#f8fafc', '#64748b', '#0ea5e9', '#f97316', '#111827', '#65a30d'];
const STEPS = ['category', 'model', 'perf', 'camera', 'addons', 'look'];

/** Sihirbaz durumu (saf; test edilir): taslak → POST/PUT gövdesi. */
export function droneBody(d) {
  const eq = { camera: d.camera || 'day', addons: {}, livery: { pattern: d.pattern || 'solid', decals: d.decals || [] } };
  for (const [k, v] of Object.entries(d.addons || {})) if (v) eq.addons[k] = typeof v === 'object' ? { ...v } : {};
  if (d.color2) eq.livery.color2 = d.color2;
  if (d.callsign) eq.livery.callsign = String(d.callsign).toUpperCase();
  if (d.max_alt_m) eq.max_alt_m = Number(d.max_alt_m);
  const params = { ...(d.params || {}) };
  if (d.max_speed_ms) Object.assign(params, speedParams(d.type, d.max_speed_ms));
  for (const [k, v] of Object.entries(params)) if (v === '' || v == null || !Number.isFinite(Number(v))) delete params[k]; else params[k] = Number(v);
  return { name: (d.name || '').trim(), type: d.type, model_key: d.model_key, color: d.color, params, equipment: eq };
}

export async function openDroneWizard(root, ctx, { catalog, eqCat, existing = null, count = 0, miniView, bigView, onDone }) {
  const edit = !!existing;
  const ex = existing?.equipment || {};
  const draft = {
    type: existing?.type || 'fpv', model_key: existing?.model_key || null, color: existing?.color || COLORS[0], name: existing?.name || '',
    params: { ...(existing?.params || {}) }, camera: ex.camera || 'day', addons: { ...(ex.addons || {}) }, pattern: ex.livery?.pattern || 'solid',
    color2: ex.livery?.color2 || '', callsign: ex.livery?.callsign || '', decals: [...(ex.livery?.decals || [])], max_alt_m: ex.max_alt_m || '', max_speed_ms: null,
    files: [],   // yüklenecek görseller (data URL) — kayıttan sonra gönderilir
  };
  let step = edit ? 1 : 0, cat = categoryOf(draft.type);
  const views = [];
  const dropViews = () => views.splice(0).forEach(v => { try { v.dispose(); } catch { /* */ } });
  const wiz = h('div', { class: 'screen scroll rm-hangar-wiz' });
  const head = h('header', { class: 'screen-head' }, h('h1', { class: 'title lg' }, edit ? t('rm.hw_edit', { n: existing.name }) : t('hangar.new')));
  const steps = h('div', { class: 'rm-steps' });
  const body = h('div', { class: 'rm-form', style: 'width:min(1180px,100%)' });
  const foot = h('div', { class: 'btn-row', style: 'justify-content:center;margin:18px 0 40px' });
  wiz.append(head, steps, body, foot);
  clear(root, wiz);
  ctx.setBack(t('hangar.title'), () => { dropViews(); onDone?.(null); });
  const models = () => CATEGORIES.find(c => c.key === cat).types.flatMap(ty => ((catalog.types || []).find(x => x.key === ty)?.models || []).map(m => ({ ...m, type: ty })));
  const curModel = () => models().find(m => m.key === draft.model_key && m.type === draft.type) || null;
  const paintSteps = () => clear(steps, STEPS.map((k, i) => h('i', { class: i === step ? 'on' : i < step ? 'done' : '' }, `${i + 1}. ${t(`rm.hw_${k}`)}`)));
  const go = n => { step = Math.max(edit ? 1 : 0, Math.min(STEPS.length - 1, n)); dropViews(); draw(); };
  const nav = (last = false) => clear(foot,
    step > (edit ? 1 : 0) ? btn(`‹ ${t('common.back')}`, () => go(step - 1), 'ghost') : null,
    last ? btn(edit ? t('common.save') : t('rm.hw_add'), () => save(), 'primary lg') : btn(`${t('common.next')} ›`, () => { if (canNext()) go(step + 1); }, 'primary lg'));
  const canNext = () => (STEPS[step] === 'model' ? !!curModel() : true);

  function draw() {
    paintSteps();
    const k = STEPS[step];
    if (k === 'category') {
      const cards = CATEGORIES.map(c => {
        const rep = ((catalog.types || []).find(x => x.key === c.types[0])?.models || [])[0];
        const host = h('div', { class: 'rm-opt-bg' });
        const card = h('button', { type: 'button', class: `rm-opt ${cat === c.key ? 'sel' : ''}`, cssVars: { ac: c.accent }, dataset: { cat: c.key },
          onclick: () => { cat = c.key; draft.type = c.types[0]; draft.model_key = null; sfx.select(); go(1); } },
          host, h('b', null, t(`rm.cat_${c.key}`)), h('span', null, t(`rm.cat_${c.key}_desc`)), h('em', null, `${t('match.choose')} ›`));
        if (rep) miniView(host, { ...rep, type: c.types[0], model_key: rep.key, color: c.accent, id: views.length }).then(v => views.push(v)).catch(() => {});
        return card;
      });
      clear(body, h('div', { class: 'rm-options' }, cards)); stagger(cards, 60, { rise: true }); nav();
      return;
    }
    if (k === 'model') {
      const all = models();
      if (!draft.model_key || !curModel()) { draft.model_key = all[0]?.key || null; draft.type = all[0]?.type || draft.type; }
      const groups = SUBGROUP_ORDER.map(g => [g, all.filter(m => subgroupOf(m.type, m.key) === g)]).filter(([, l]) => l.length);
      let n = 0;
      const wrap = h('div', { class: 'rm-models' }, groups.map(([g, list]) => [h('h3', null, t(`rm.sub_${g}`)),
        h('div', { class: 'rm-mcards' }, list.map(m => {
          const thumb = h('div', { class: 'thumb' });
          const c = h('button', { type: 'button', class: `rm-mcard ${m.key === draft.model_key && m.type === draft.type ? 'sel' : ''}`, dataset: { key: m.key, ty: m.type },
            disabled: edit && m.type !== existing.type ? true : null,
            onclick: () => { draft.model_key = m.key; draft.type = m.type; for (const x of wrap.querySelectorAll('.rm-mcard')) x.classList.toggle('sel', x === c); sfx.tick(); } },
            thumb, h('b', null, m.label || m.key), h('small', null, [t(`types.${m.type}`), m.desc].filter(Boolean).join(' · ')));
          if (n++ < 14) miniView(thumb, { ...m, model_key: m.key, color: draft.color, id: n }).then(v => views.push(v)).catch(() => {});
          return c;
        }))]));
      clear(body, wrap, edit ? h('p', { class: 'rm-note' }, t('rm.hw_type_locked')) : null); nav();
      return;
    }
    if (k === 'perf') {
      const [lo, hi, df] = SPEED_RANGE[draft.type] || [3, 30, 12];
      if (draft.max_speed_ms == null) draft.max_speed_ms = guessSpeed(draft) || df;
      const pkeys = [...new Set([...(TYPE_PARAMS[draft.type] || []), ...Object.keys(curModel()?.defaults || {}).slice(0, 8), ...Object.keys(draft.params)])]
        .filter(p => !Object.keys(speedParams(draft.type, 1)).includes(p));
      const table = h('div', { class: 'rm-form' }, pkeys.map(p => paramRow(p)));
      function paramRow(p) {
        const inp = h('input', { class: 'input mono', type: 'number', step: 'any', value: draft.params[p] ?? curModel()?.defaults?.[p] ?? '', placeholder: t('rm.hw_param_default'), 'aria-label': p,
          oninput: e => { if (e.target.value === '') delete draft.params[p]; else draft.params[p] = Number(e.target.value); } });
        return h('div', { class: 'rm-row' }, h('label', { class: 'mono' }, p), inp);
      }
      const addP = h('input', { class: 'input mono', placeholder: 'SPRAY_PUMP_RATE', maxlength: 16, 'aria-label': t('rm.hw_param_add') });
      clear(body,
        h('div', { class: 'rm-row' }, h('label', null, t('rm.hw_max_speed')), range({ min: lo, max: hi, step: 1, value: draft.max_speed_ms, onInput: v => { draft.max_speed_ms = v; }, format: v => `${v} m/s · ${Math.round(v * 3.6)} km/h` })),
        draft.type !== 'rover' ? h('div', { class: 'rm-row' }, h('label', null, t('rm.hw_max_alt')), range({ min: 10, max: draft.type === 'plane' || draft.type === 'vtol' || draft.type === 'interceptor' ? 5000 : 1200, step: 10, value: Number(draft.max_alt_m) || 120,
          onInput: v => { draft.max_alt_m = v; }, format: v => `${v} m` })) : null,
        h('p', { class: 'rm-note' }, t('rm.hw_speed_note', { p: Object.keys(speedParams(draft.type, 1)).join(', ') })),
        h('h3', { class: 'title md' }, t('rm.hw_params')), table,
        h('div', { class: 'rm-row' }, addP, btn(`+ ${t('rm.hw_param_add')}`, () => { const p = addP.value.trim().toUpperCase(); if (!/^[A-Z][A-Z0-9_]{1,15}$/.test(p)) return; if (!(p in draft.params)) draft.params[p] = ''; table.append(paramRow(p)); addP.value = ''; }, 'sm')),
        h('p', { class: 'rm-note' }, t('rm.hw_mp_note')));
      if (!draft.max_alt_m) draft.max_alt_m = 120;
      nav();
      return;
    }
    if (k === 'camera') {
      const cams = (eqCat?.cameras || ['day', 'night', 'thermal', 'multispectral']).map(c => h('button', { type: 'button', class: `rm-pick ${draft.camera === c ? 'sel' : ''}`, dataset: { cam: c },
        onclick: e => { draft.camera = c; for (const x of body.querySelectorAll('[data-cam]')) x.classList.toggle('sel', x === e.currentTarget); sfx.tick(); } },
        h('i', { class: `rm-cam ${c}` }), h('b', null, t(`rm.cam_${c}`)), h('small', null, t(`rm.cam_${c}_desc`))));
      clear(body, h('div', { class: 'rm-cards' }, cams)); nav();
      return;
    }
    if (k === 'addons') {
      const addons = eqCat?.addons || {};
      const cards = Object.entries(addons).map(([key, a]) => {
        const ok = a.types.includes(draft.type);
        if (!ok) delete draft.addons[key];
        const opts = h('div', { class: 'rm-form', hidden: !draft.addons[key] });
        const paintOpts = () => clear(opts, Object.entries(a.options).map(([o, lim]) => h('div', { class: 'rm-row' }, h('label', null, t(`rm.addon_${key}_${o}`)),
          range({ min: lim.min, max: lim.max, step: lim.max > 20 ? 1 : 0.1, value: draft.addons[key]?.[o] ?? lim.default, onInput: v => { draft.addons[key] = { ...(draft.addons[key] || {}), [o]: v }; }, format: v => String(Math.round(v * 10) / 10) }))));
        paintOpts();
        return h('div', { class: `rm-pick ${draft.addons[key] ? 'sel' : ''} ${ok ? '' : 'off'}`, dataset: { addon: key } },
          h('label', { class: 'av-toggle' }, h('input', { type: 'checkbox', checked: draft.addons[key] ? true : null, disabled: ok ? null : true,
            onchange: e => { if (e.target.checked) draft.addons[key] = Object.fromEntries(Object.entries(a.options).map(([o, l]) => [o, l.default])); else delete draft.addons[key]; e.target.closest('.rm-pick').classList.toggle('sel', e.target.checked); opts.hidden = !e.target.checked; paintOpts(); } }),
            h('b', null, t(`rm.addon_${key}`))),
          h('small', null, ok ? t(`rm.addon_${key}_desc`) : t('rm.addon_na')), h('small', { class: 'mono' }, Object.entries(a.sitl_params).map(([p, v]) => `${p}=${v}`).join(' · ')), opts);
      });
      clear(body, h('div', { class: 'rm-cards', style: 'grid-template-columns:repeat(auto-fill,minmax(300px,1fr))' }, cards)); nav();
      return;
    }
    // görünüm
    const stage = h('div', { class: 'model-stage', style: 'height:300px' });
    let big = null;
    bigView(stage).then(v => { big = v; views.push(v); big.setModel({ ...(curModel() || {}), type: draft.type, model_key: draft.model_key, color: draft.color }); }).catch(() => {});
    const repaint = () => big?.setModel({ ...(curModel() || {}), type: draft.type, model_key: draft.model_key, color: draft.color });
    const sw = h('div', { class: 'swatches' }, COLORS.map(c => { const s = h('button', { type: 'button', class: `swatch ${draft.color === c ? 'on' : ''}`, 'aria-label': c, onclick: () => { draft.color = c; for (const x of sw.children) x.classList.toggle('on', x === s); repaint(); } }); s.style.background = c; return s; }));
    const nameInp = h('input', { class: 'input big', placeholder: t('hangar.name_ph'), maxlength: 40, value: draft.name, oninput: e => { draft.name = e.target.value; } });
    const c2 = h('input', { type: 'color', value: draft.color2 || '#111827', 'aria-label': t('rm.hw_color2'), oninput: e => { draft.color2 = e.target.value; } });
    const cs = h('input', { class: 'input mono', maxlength: 8, value: draft.callsign, placeholder: 'TR-01', oninput: e => { draft.callsign = e.target.value.toUpperCase().replace(/[^A-Z0-9-]/g, ''); e.target.value = draft.callsign; } });
    const decalBox = h('div', { class: 'rm-decals' });
    const paintDecals = () => clear(decalBox, [...(existing?._decals || []).map(d => decalTile(d.url, async () => { try { await api.del(`/api/hangar/${existing.id}/decals/${d.id}`); existing._decals = existing._decals.filter(x => x.id !== d.id); draft.decals = draft.decals.filter(x => x.id !== d.id); paintDecals(); } catch (e) { toastErr(e); } })),
      ...draft.files.map((f, i) => decalTile(f.data, () => { draft.files.splice(i, 1); paintDecals(); }))]);
    const decalTile = (src, onDel) => h('div', { class: 'rm-decal' }, h('img', { src, alt: '' }), h('button', { type: 'button', class: 'mini-btn danger', 'aria-label': t('common.delete'), onclick: onDel }, '✕'));
    const file = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', hidden: true, onchange: async e => {
      const f = e.target.files?.[0]; e.target.value = '';
      if (!f) return;
      if (f.size > (eqCat?.decals?.max_bytes || 1048576)) { toast(t('rm.hw_decal_big'), 'err'); return; }
      if ((existing?._decals?.length || 0) + draft.files.length >= (eqCat?.decals?.max || 6)) { toast(t('rm.hw_decal_max'), 'err'); return; }
      const data = await new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f); });
      draft.files.push({ data, kind: draft.files.length || existing?._decals?.length ? 'sticker' : 'logo' }); paintDecals();
    } });
    paintDecals();
    clear(body, stage,
      h('div', { class: 'rm-row' }, h('label', null, t('rm.hw_name')), nameInp),
      h('div', { class: 'rm-row' }, h('label', null, t('hangar.pick_color')), sw),
      h('div', { class: 'rm-row' }, h('label', null, t('rm.hw_pattern')), segment(PATTERNS.map(p => ({ value: p, label: t(`rm.pat_${p}`) })), draft.pattern, v => { draft.pattern = v; })),
      h('div', { class: 'rm-row' }, h('label', null, t('rm.hw_color2')), c2),
      h('div', { class: 'rm-row' }, h('label', null, t('rm.hw_callsign')), cs),
      h('div', { class: 'rm-row' }, h('label', null, t('rm.hw_decals')), h('div', null, decalBox, file, btn(`+ ${t('rm.hw_decal_add')}`, () => file.click(), 'sm'), h('p', { class: 'rm-note' }, t('rm.hw_decal_note')))));
    nav(true);
  }

  async function save() {
    const b = droneBody({ ...draft, name: draft.name || `${t(`types.${draft.type}`)}-${count + 1}` });
    try {
      let d;
      if (edit) d = await api.put(`/api/hangar/${existing.id}`, { name: b.name, model_key: b.model_key, color: b.color, params: b.params, equipment: b.equipment });
      else d = await api.post('/api/hangar', b);
      if (draft.files.length) {
        const added = [];
        for (const f of draft.files) { try { added.push(await api.post(`/api/hangar/${d.id}/decals`, { image: f.data, kind: f.kind })); } catch (e) { toastErr(e); } }
        const slots = ['top', 'left', 'right', 'front', 'tail', 'bottom'];
        const decals = [...b.equipment.livery.decals, ...added.map((x, i) => ({ id: x.id, slot: slots[(b.equipment.livery.decals.length + i) % slots.length], scale: 1 }))];
        d = await api.put(`/api/hangar/${d.id}`, { equipment: { ...b.equipment, livery: { ...b.equipment.livery, decals } } });
      }
      toast(t('common.saved'), 'ok'); sfx.land?.();
      dropViews(); onDone?.(d);
    } catch (e) { toastErr(e); }
  }
  draw();
  return () => dropViews();
}

function guessSpeed(d) {
  const p = d.params || {};
  if (p.WPNAV_SPEED) return Math.round(p.WPNAV_SPEED / 100);
  if (p.AIRSPEED_MAX) return Math.round(p.AIRSPEED_MAX);
  if (p.CRUISE_SPEED) return p.CRUISE_SPEED;
  return null;
}
