// PARKUR (yol haritası): üç seçenek — Karşılaşma Parkurları (hazır parkurlar, yalnız gösterim; içinden canlı 3B görüntü) · Özel Parkurlar
// (Yeni → Orman / Şehir / Dağlık + yoğunluk kaydırıcıları, hava, ad, deniz seviyesi yüksekliği; prosedürel dünya) · Gerçek Dünya (uydu haritası:
// adres ara (Esri), işareti sürükle, harita boyutu, hava, ad). Rotalar: #/tracks · #/tracks/match · #/tracks/custom[/new] · #/tracks/real[/new]
// (ayrıntılı eski editör #/tracks/mine; hazır FPV ayrıntısı #/tracks/fpv/<id>).
import * as api from '../core/api.js';
import { h, clear } from '../core/dom.js';
import { t } from '../i18n/i18n.js';
import { screen, btn, segment, range, toast, toastErr, confirmDlg } from '../ui/components.js';
import { stagger } from '../ui/transition.js';
import * as sfx from '../ui/sfx.js';

export const SECTIONS = ['match', 'custom', 'real'];
export const BIOMES = {
  forest: { sliders: [['tree_density', 0, 1, 0.01, 0.6], ['water', 0, 1, 0.01, 0.15]], world: { mountain_count: 2, mountain_height: 120, building_count: 0 } },
  city: { sliders: [['building_count', 0, 500, 1, 220], ['vehicle_count', 0, 500, 1, 80], ['people_count', 0, 1000, 1, 150]], world: { tree_density: 0.08, mountain_count: 0, water: 0.05 } },
  mountain: { sliders: [['mountain_count', 0, 50, 1, 14], ['water', 0, 1, 0.01, 0.2], ['tree_density', 0, 1, 0.01, 0.35]], world: { mountain_height: 900, building_count: 0 } },
};
const WEATHER = ['clear', 'cloudy', 'fog', 'rain', 'snow'];
const TIMES = ['day', 'dusk', 'night'];
export const isCustom = tr => tr.world_mode === 'procedural';
/** Özel parkur gövdesi (saf; test edilir). */
export function customBody(d) {
  const b = BIOMES[d.biome] || BIOMES.forest;
  const world = { ...b.world, biome: d.biome, seed: d.seed ?? Math.floor(Math.random() * 1e6), size_m: 4000, runway: false };
  for (const [k] of b.sliders) if (d[k] != null) world[k] = Number(d[k]);
  if (d.elevation_m != null && d.elevation_m !== '') world.elevation_m = Number(d.elevation_m);
  return { name: (d.name || '').trim(), lat: d.lat ?? 40.099, lon: d.lon ?? 33.4101, radius_m: 1500, world_mode: 'procedural', world, weather: d.weather || 'clear', time_of_day: d.time || 'day',
    wind: { speed_ms: d.wind ?? 3, dir_deg: 270, gust: 1 } };
}
export function realBody(d, google3d = false) {
  return { name: (d.name || '').trim(), lat: Number(d.lat), lon: Number(d.lon), radius_m: Math.round(Number(d.radius_m) || 1500), world_mode: google3d ? 'google3d' : 'real',
    weather: d.weather || 'clear', time_of_day: d.time || 'day', wind: { speed_ms: d.wind ?? 3, dir_deg: 270, gust: 1 } };
}

export async function mountSection(root, ctx, sec, sub, register) {
  if (sec === 'match') return matchCourses(root, ctx, register);
  if (sec === 'custom') return sub === 'new' ? customWizard(root, ctx) : list(root, ctx, 'custom');
  if (sec === 'real') return sub === 'new' ? realWizard(root, ctx, register) : list(root, ctx, 'real');
  return landing(root, ctx, register);
}

// ---------------------------------------------------------------- giriş: üç animasyonlu seçenek
async function landing(root, ctx, register) {
  const sc = screen({ title: t('tracks.title'), sub: t('rm.tr_sub') });
  const views = [];
  register(() => views.splice(0).forEach(v => v.dispose?.()));
  const opt = (key, accent, bg) => h('button', { type: 'button', class: 'rm-opt', cssVars: { ac: accent }, dataset: { sec: key }, onclick: () => { sfx.select(); ctx.go('tracks', key); } },
    bg, h('span', { class: 'rm-chip' }, t(`rm.tr_${key}_chip`)), h('b', null, t(`rm.tr_${key}`)), h('span', null, t(`rm.tr_${key}_desc`)), h('em', null, `${t('match.choose')} ›`));
  const b1 = h('div', { class: 'rm-opt-bg' }), b2 = h('div', { class: 'rm-opt-bg' });
  const b3 = h('div', { class: 'rm-opt-bg rm-sat-bg' });
  const cards = [opt('match', '#f97316', b1), opt('custom', '#34d399', b2), opt('real', '#38bdf8', b3)];
  sc.append(h('div', { class: 'rm-options' }, cards), h('p', { class: 'rm-note', style: 'text-align:center;margin-top:14px' },
    h('a', { href: '#/tracks/mine' }, t('rm.tr_all')), ' · ', h('a', { href: '#/missions' }, t('menu.missions'))));
  clear(root, sc);
  ctx.setBack(t('common.menu'));
  stagger(cards, 90, { rise: true });
  // canlı arka planlar: hazır parkurun içinden süzülen kamera · dönen prosedürel arazi · kayan uydu görüntüsü (CSS)
  try {
    const c = await api.get('/api/fpv/courses/forest');
    const { courseFlythrough } = await import('./flythrough.js');
    if (b1.isConnected) views.push(await courseFlythrough(b1, c.course, { speed: 7 }));
  } catch (e) { console.warn(e); }
  try {
    const { terrainViewer } = await import('./terrain3d.js');
    const tv = await terrainViewer(b2, { spin: 0.35, tilt: 0.95 });
    tv.setTrack?.({ lat: 40, lon: 33, radius_m: 1500, world_mode: 'procedural', world: { runway: false }, gates: [] });
    if (b2.isConnected) views.push(tv); else tv.dispose();
  } catch (e) { console.warn(e); }
  const z = 15, x0 = 19500, y0 = 12500;   // Kapadokya çevresi uydu karoları (Esri; img-src https:)
  for (let i = 0; i < 12; i++) b3.append(h('img', { src: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y0 + Math.floor(i / 4)}/${x0 + (i % 4)}`, alt: '', loading: 'lazy' }));
  b3.append(h('i', { class: 'rm-scan' }));
}

// ---------------------------------------------------------------- karşılaşma parkurları (yalnız gösterim)
async function matchCourses(root, ctx, register) {
  const sc = screen({ title: t('rm.tr_match'), sub: t('rm.tr_match_sub'), cls: 'scroll' });
  const grid = h('div', { class: 'rm-gallery' });
  sc.append(grid);
  clear(root, sc);
  ctx.setBack(t('tracks.title'), '#/tracks');
  const views = [];
  let dead = false;
  register(() => { dead = true; views.splice(0).forEach(v => v.dispose?.()); });
  let list = [];
  try { list = (await api.get('/api/fpv/courses')).courses || []; } catch (e) { toastErr(e); }
  const { FT } = await import('../fly/fpv.js');
  const { courseFlythrough } = await import('./flythrough.js');
  const cards = list.map(c => {
    const host = h('div', { style: 'position:absolute;inset:0' });
    return [h('div', { class: 'rm-gal-card', dataset: { course: c.id }, 'aria-label': FT(`fpv.c_${c.id}`) }, host,
      h('div', { class: 'cap' }, h('b', null, FT(`fpv.c_${c.id}`)), h('small', null, [FT(`fpv.v_${c.id}`), `${Math.round(c.length_m)} m`, FT('fpv.gates_n', { n: c.gate_count }), '★'.repeat(c.difficulty || 1)].join(' · ')))), host, c];
  });
  clear(grid, cards.map(x => x[0]));
  stagger(cards.map(x => x[0]), 50);
  for (const [, host, c] of cards) {   // sırayla: her kart parkurun içinden canlı görüntü
    if (dead) break;
    try { const d = await api.get(`/api/fpv/courses/${c.id}`); if (dead) break; views.push(await courseFlythrough(host, d.course, { speed: 8 })); } catch (e) { console.warn(e); }
  }
}

// ---------------------------------------------------------------- liste (özel / gerçek)
async function list(root, ctx, kind) {
  const sc = screen({ title: t(`rm.tr_${kind}`), sub: t(`rm.tr_${kind}_desc`), cls: 'scroll' });
  const box = h('div', { class: 'rm-list' });
  sc.append(h('div', { class: 'btn-row', style: 'justify-content:center;margin-bottom:14px' }, btn(`+ ${t('rm.new')}`, () => ctx.go('tracks', `${kind}/new`), 'primary lg')), box);
  clear(root, sc);
  ctx.setBack(t('tracks.title'), '#/tracks');
  const load = async () => {
    let all = [];
    try { all = (await api.get('/api/tracks')).tracks || []; } catch (e) { toastErr(e); }
    const rows = all.filter(x => (kind === 'custom') === isCustom(x));
    if (!rows.length) { clear(box, h('p', { class: 'rm-empty' }, t('rm.tr_none'))); return; }
    clear(box, rows.map(tr => h('div', { class: 'rm-li', dataset: { tid: String(tr.id) } }, h('div', { class: 'av' }, h('img', { src: tr.preview_png, alt: '', loading: 'lazy' })),
      h('div', { class: 'tx' }, h('b', null, `${tr.is_default ? '★ ' : ''}${tr.name}`), h('small', null, [kind === 'custom' ? t(`rm.biome_${tr.world?.biome || 'forest'}`) : `${Number(tr.lat).toFixed(4)}, ${Number(tr.lon).toFixed(4)}`,
        t(`rm.w_${tr.weather}`), kind === 'real' ? `${(tr.radius_m * 2 / 1000).toFixed(1)} km` : tr.world?.elevation_m != null ? `${tr.world.elevation_m} m` : null].filter(Boolean).join(' · '))),
      h('div', { class: 'ac' }, btn(t('common.edit'), () => ctx.go('tracks', `mine/${tr.id}`), 'sm'),
        btn(t('common.delete'), async () => { if (!await confirmDlg(t('tracks.delete_q', { name: tr.name }), { danger: true })) return; try { await api.del(`/api/tracks/${tr.id}`); load(); } catch (e) { toastErr(e); } }, 'sm ghost')))));
  };
  load();
}

// ---------------------------------------------------------------- özel parkur sihirbazı
async function customWizard(root, ctx) {
  const d = { biome: 'forest', weather: 'clear', time: 'day', name: '', elevation_m: 850 };
  const sc = screen({ title: t('rm.tr_custom_new'), sub: t('rm.tr_custom_new_sub'), cls: 'scroll' });
  const body = h('div', { class: 'rm-form' });
  sc.append(body);
  clear(root, sc);
  ctx.setBack(t('rm.tr_custom'), '#/tracks/custom');
  const biomeCard = (k, ac) => h('button', { type: 'button', class: `rm-opt small ${d.biome === k ? 'sel' : ''}`, cssVars: { ac }, dataset: { biome: k }, onclick: () => { d.biome = k; for (const [s] of BIOMES[k].sliders) delete d[s]; draw(); } },
    h('div', { class: `rm-opt-bg rm-biome-${k}` }), h('b', null, t(`rm.biome_${k}`)), h('span', null, t(`rm.biome_${k}_desc`)));
  function draw() {
    const b = BIOMES[d.biome];
    for (const [k, , , , df] of b.sliders) if (d[k] == null) d[k] = df;
    const name = h('input', { class: 'input big', maxlength: 40, placeholder: t('rm.tr_name_ph'), value: d.name, oninput: e => { d.name = e.target.value; } });
    clear(body, h('div', { class: 'rm-options' }, biomeCard('forest', '#22c55e'), biomeCard('city', '#f59e0b'), biomeCard('mountain', '#a78bfa')),
      ...b.sliders.map(([k, lo, hi, st]) => h('div', { class: 'rm-row' }, h('label', null, t(`rm.sl_${k}`)), range({ min: lo, max: hi, step: st, value: d[k], onInput: v => { d[k] = v; }, format: v => (hi <= 1 ? `${Math.round(v * 100)}%` : String(Math.round(v))) }))),
      h('div', { class: 'rm-row' }, h('label', null, t('rm.weather')), segment(WEATHER.map(w => ({ value: w, label: t(`rm.w_${w}`) })), d.weather, v => { d.weather = v; })),
      h('div', { class: 'rm-row' }, h('label', null, t('rm.time')), segment(TIMES.map(w => ({ value: w, label: t(`rm.t_${w}`) })), d.time, v => { d.time = v; })),
      h('div', { class: 'rm-row' }, h('label', null, t('rm.elevation')), range({ min: -100, max: 5000, step: 10, value: d.elevation_m, onInput: v => { d.elevation_m = v; }, format: v => `${v} m` })),
      h('div', { class: 'rm-row' }, h('label', null, t('rm.tr_name')), name),
      h('div', { class: 'btn-row', style: 'justify-content:center' }, btn(t('common.save'), save, 'primary lg')));
  }
  async function save() {
    const body = customBody({ ...d, name: d.name || t(`rm.biome_${d.biome}`) });
    try { await api.post('/api/tracks', body); toast(t('common.saved'), 'ok'); ctx.go('tracks', 'custom'); } catch (e) { toastErr(e); }
  }
  draw();
}

// ---------------------------------------------------------------- gerçek dünya sihirbazı (uydu haritası + adres arama)
export async function geocode(q) {
  const ll = String(q || '').trim().match(/^(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)$/);
  if (ll) return [{ name: q, lat: Number(ll[1]), lon: Number(ll[2]) }];
  const u = `https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&maxLocations=6&outFields=Match_addr&SingleLine=${encodeURIComponent(q)}`;
  const r = await fetch(u, { credentials: 'omit' });
  if (!r.ok) throw new Error(`geocode ${r.status}`);
  const j = await r.json();
  return (j.candidates || []).map(c => ({ name: c.address, lat: c.location.y, lon: c.location.x }));
}

async function realWizard(root, ctx, register) {
  const d = { lat: 40.099, lon: 33.4101, radius_m: 1500, weather: 'clear', time: 'day', name: '' };
  const sc = screen({ title: t('rm.tr_real_new'), sub: t('rm.tr_real_new_sub'), cls: 'scroll' });
  const mapBox = h('div', { class: 'rm-mapbox', style: 'height:min(54vh,520px);border-radius:16px;overflow:hidden;position:relative' });
  const q = h('input', { class: 'input', placeholder: t('rm.addr_ph'), 'aria-label': t('rm.addr_ph') });
  const hits = h('div', { class: 'rm-inv-list' });
  const coord = h('span', { class: 'rm-note mono' });
  const body = h('div', { class: 'rm-form', style: 'width:min(1100px,100%)' });
  sc.append(body);
  clear(root, sc);
  ctx.setBack(t('rm.tr_real'), '#/tracks/real');
  const { satPickerMap } = await import('./satmap.js');
  const paintCoord = () => { coord.textContent = `${d.lat.toFixed(5)}, ${d.lon.toFixed(5)} · ${(d.radius_m * 2 / 1000).toFixed(1)} km`; };
  const map = satPickerMap(mapBox, { lat: d.lat, lon: d.lon, radius_m: d.radius_m, onPick: p => { d.lat = p.lat; d.lon = p.lon; map.setCenter(p.lat, p.lon); paintCoord(); }, note: t('rm.map_note') });
  register(() => map.dispose());
  const search = async e => {
    e?.preventDefault?.();
    clear(hits, h('small', { class: 'rm-note' }, t('common.loading')));
    try {
      const rs = await geocode(q.value);
      clear(hits, rs.length ? rs.map(r => h('button', { type: 'button', class: 'rm-pm-item', onclick: () => { d.lat = r.lat; d.lon = r.lon; if (!d.name) { d.name = String(r.name).split(',')[0].slice(0, 40); nameInp.value = d.name; } map.setCenter(r.lat, r.lon, d.radius_m); paintCoord(); clear(hits); } }, '⌖ ', r.name)) : h('small', { class: 'rm-note' }, t('rm.addr_none')));
    } catch { clear(hits, h('small', { class: 'rm-note' }, t('rm.addr_err'))); }
  };
  const nameInp = h('input', { class: 'input big', maxlength: 40, placeholder: t('rm.tr_name_ph'), oninput: e => { d.name = e.target.value; } });
  clear(body, h('form', { class: 'rm-row', onsubmit: search }, q, h('button', { class: 'btn primary', type: 'submit' }, t('rm.search'))), hits, mapBox, coord,
    h('div', { class: 'rm-row' }, h('label', null, t('rm.map_size')), range({ min: 200, max: 5000, step: 50, value: d.radius_m, onInput: v => { d.radius_m = v; map.setRadius(v); paintCoord(); }, format: v => `${(v * 2 / 1000).toFixed(1)} km` })),
    h('div', { class: 'rm-row' }, h('label', null, t('rm.weather')), segment(WEATHER.map(w => ({ value: w, label: t(`rm.w_${w}`) })), d.weather, v => { d.weather = v; })),
    h('div', { class: 'rm-row' }, h('label', null, t('rm.time')), segment(TIMES.map(w => ({ value: w, label: t(`rm.t_${w}`) })), d.time, v => { d.time = v; })),
    h('div', { class: 'rm-row' }, h('label', null, t('rm.tr_name')), nameInp),
    h('div', { class: 'btn-row', style: 'justify-content:center' }, btn(t('common.save'), async () => {
      try { await api.post('/api/tracks', realBody({ ...d, name: d.name || t('rm.tr_real') }, !!ctx.state?.meta?.google3d)); toast(t('common.saved'), 'ok'); ctx.go('tracks', 'real'); } catch (e) { toastErr(e); }
    }, 'primary lg')));
  paintCoord();
}
