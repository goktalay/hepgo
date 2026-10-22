// Uçuş Simülatörü §45 — UÇUŞ YIĞINI (otopilot) seçimi. YALNIZ HEPGO: sihirbaz (flightsim.js wizardModal) bu modülü meta.stacks varsa
// dinamik yükler; SIMUMAV dışa aktarımına girmez (tools/simumav_export.py JS_DISLANAN) ve SIMUMAV meta'sında `stacks` yoktur.
// Saf katman (node testi tests/test_ucus_yigini.mjs): stackStatus, stackTypeError, airframesFor, stackBody, stackLabel, readParamsText.
// DOM: createStackPicker({ h, tr, stacks, getType, initial, onChange }) → { el, value, isPx4(), error(), body(), label(), refresh() }.
// Kartlar: ArduPilot (varsayılan) · PX4 (SIH) etkin; INAV / Paparazzi "Yakında", Betaflight / Rotorflight "Uygun değil" — gri, gerekçe ipucu ve
// alt satırda. PX4 seçilince: airframe (SYS_AUTOSTART), simülasyon hızı (PX4_SIM_SPEED_FACTOR; yalnız açılışta), çalışan / çalışmayan özellikler.
// Her etkin yığında parametre dosyası (.params PX4 QGC / .parm ArduPilot) — metin olarak gövdeye (stack_cfg.params_text; sunucu ayrıştırır).

export const STACK_BADGE = { active: '', planned: 'Yakında', unsuitable: 'Uygun değil', missing: 'Kurulu değil' };
export const PARAM_MAX_BYTES = 512 * 1024;
export const PX4_SPEEDS = [0.5, 1, 2, 4];
const TYPE_NAMES = { multirotor: 'Multikopter', hexarotor: 'Hexakopter', helikopter: 'Helikopter', sabit_kanat: 'Sabit Kanat', vtol: 'VTOL', interceptor: 'INTERCEPTOR', rover: 'Kara Aracı' };

/** Kart durumu: 'active' (seçilebilir) | 'planned' | 'unsuitable' | 'missing'. */
export const stackStatus = s => (s?.status === 'active' && s.available !== false ? 'active' : s?.status === 'active' ? 'missing' : s?.status || 'planned');
/** Seçili yığın bu dron tipini uçurabilir mi; değilse açıklama (sihirbaz Araç adımı doğrulaması). */
export function stackTypeError(stack, type, stacks) {
  const s = (stacks || []).find(x => x.key === stack);
  if (!s || stack === 'ardupilot') return null;
  if (stackStatus(s) !== 'active') return `${s.name}: ${s.reason || 'kullanılamıyor'}`;
  if (!(s.types || []).includes(type)) return `${s.name} (SIH) bu dron tipini desteklemiyor: ${TYPE_NAMES[type] || type}. Desteklenen: ${(s.types || []).map(t => TYPE_NAMES[t] || t).join(', ')}.`;
  return null;
}
export const airframesFor = (stacks, type) => ((stacks || []).find(x => x.key === 'px4')?.airframes || {})[type] || [];
/** Sunucu gövdesi: ArduPilot + dosyasız → {} (eski gövdeyle birebir); aksi { stack, stack_cfg }. */
export function stackBody(st) {
  const cfg = {};
  if (st.params?.text) { cfg.params_text = st.params.text; cfg.params_name = st.params.name || null; }
  if (st.stack === 'px4') { if (st.airframe != null) cfg.airframe = st.airframe; if (st.speed != null && st.speed !== 1) cfg.speed = st.speed; }
  if (st.stack === 'ardupilot' && !cfg.params_text) return {};
  return { stack: st.stack, stack_cfg: cfg };
}
export function stackLabel(st, stacks, type) {
  const s = (stacks || []).find(x => x.key === st.stack);
  const parts = [s?.name || st.stack];
  if (st.stack === 'px4') {
    const af = airframesFor(stacks, type).find(a => a.id === st.airframe);
    if (af) parts.push(`${af.name} (${af.id})`);
    if (st.speed && st.speed !== 1) parts.push(`${st.speed}×`);
  }
  if (st.params?.text) parts.push(`parametre dosyası ${st.params.name || ''} (${st.params.count} satır)`.replace('  ', ' '));
  return parts.join(' · ');
}
/** Dosya metni ön denetimi (istemci): boyut + yorum/boş olmayan satır sayısı. Ayrıştırma sunucuda (flightsim_px4.param_dosyasi_coz). */
export function readParamsText(text) {
  if (typeof text !== 'string') return { error: 'Dosya okunamadı' };
  if (text.length > PARAM_MAX_BYTES) return { error: 'Parametre dosyası çok büyük (en çok 512 KB)' };
  const count = text.split(/\r?\n/).map(s => s.split('#')[0].trim()).filter(Boolean).length;
  if (!count) return { error: 'Dosyada parametre satırı yok' };
  return { count };
}

const CSS = `
.yy-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.yy-card { display: flex; flex-direction: column; gap: 3px; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--text); text-align: left; cursor: pointer; position: relative; }
.yy-card:hover:not([disabled]) { border-color: var(--primary); }
.yy-card.on { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-soft); background: var(--primary-soft); }
.yy-card[disabled] { cursor: not-allowed; opacity: .55; filter: grayscale(.6); }
.yy-card b { font-size: 14px; }
.yy-badge { position: absolute; top: 8px; right: 8px; font-size: 10px; padding: 1px 6px; border-radius: 9px; background: var(--border); color: var(--text-muted, #667); }
.yy-badge.def { background: var(--primary-soft); color: var(--primary); }
.yy-card .yy-meta { font-size: 11px; color: var(--text-muted, #667); }
.yy-card .yy-why { font-size: 11px; color: var(--text-muted, #667); line-height: 1.3; }
.yy-cfg { margin-top: 10px; display: grid; gap: 8px; }
.yy-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.yy-row > span:first-child { min-width: 120px; }
.yy-feat { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 14px; font-size: 12px; margin: 4px 0 0; padding: 0; list-style: none; }
.yy-feat li { display: flex; gap: 6px; }
.yy-feat li.no { color: var(--text-muted, #889); }
.yy-feat li i { font-style: normal; width: 14px; flex: none; }
.yy-warn { color: var(--danger, #c33); font-size: 12px; }
@media (max-width: 640px) { .yy-feat { grid-template-columns: 1fr; } }
`;
const FEAT_NAMES = { telemetry: '3B + HUD telemetrisi', gcs: 'GCS köprüsü (UDP)', arm: 'ARM / DISARM', takeoff: 'Kalkış', rtl: 'RTL', modes: 'Uçuş kipleri', rc: 'Sanal kumanda',
  mission: 'Görev (harekât paneli)', params_file: 'Parametre dosyası', power: 'Yakıt / batarya', targets: 'Hedefler', gpws: 'Uçuş uyarıları', speed: 'Uçuşta simülasyon hızı',
  wind: 'Rüzgâr fiziği', motor_cut: 'Motor kesme', servo_trigger: 'Servo tetik', launch: 'Rampa / araç / fırlatıcı', terrain: 'Arazi sunumu', bin_log: '.bin → Uçuş Logları',
  saved_params: 'Dron kaydı parametreleri', layout: 'Kontrol düzeni', defend: 'Yer kontrolünü koru' };

function ensureCss() {
  if (typeof document === 'undefined' || document.getElementById('yy-css')) return;
  const st = document.createElement('style'); st.id = 'yy-css'; st.textContent = CSS; document.head.append(st);
}

export function createStackPicker({ h, tr = s => s, stacks = [], getType = () => 'multirotor', initial = null, onChange = () => {} }) {
  ensureCss();
  const ok = k => stackStatus(stacks.find(s => s.key === k)) === 'active';
  const st = { stack: initial?.stack && ok(initial.stack) ? initial.stack : 'ardupilot', airframe: initial?.stack_cfg?.airframe ?? null, speed: Number(initial?.stack_cfg?.speed) || 1, params: null };
  const cards = h('div', { class: 'yy-cards' });
  const cfg = h('div', { class: 'yy-cfg' });
  const warn = h('div', { class: 'yy-warn', hidden: true });
  const fileInp = h('input', { type: 'file', accept: '.params,.parm,.param,.txt', hidden: true, onchange: () => readFile(fileInp.files?.[0]) });
  const fileInfo = h('span', { class: 'small muted' });
  const fileClear = h('button', { class: 'btn sm', type: 'button', hidden: true, onclick: () => { st.params = null; fileInp.value = ''; draw(); onChange(st); } }, tr('Kaldır'));
  const fileBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => fileInp.click() }, tr('Dosya seç…'));
  const afSel = h('select', { class: 'input sm', onchange: () => { st.airframe = Number(afSel.value); draw(); onChange(st); } });
  const spSel = h('select', { class: 'input sm', onchange: () => { st.speed = Number(spSel.value); onChange(st); } }, PX4_SPEEDS.map(x => h('option', { value: x }, `${x}×`)));
  const feat = h('ul', { class: 'yy-feat' });
  const gcsNote = h('div', { class: 'small muted' });
  const px4Box = h('div', { class: 'yy-cfg', hidden: true },
    h('label', { class: 'yy-row' }, h('span', { class: 'small muted' }, tr('PX4 airframe')), afSel, h('span', { class: 'small muted' }, 'SYS_AUTOSTART')),
    h('label', { class: 'yy-row', title: tr('PX4 SIH simülasyon hızı yalnız açılışta okunur (PX4_SIM_SPEED_FACTOR); uçuş sırasında değiştirilemez.') },
      h('span', { class: 'small muted' }, tr('Simülasyon hızı')), spSel, h('span', { class: 'small muted' }, tr('yalnız açılışta'))),
    gcsNote, h('div', { class: 'small' }, h('b', null, tr('PX4\'te çalışan / çalışmayan özellikler'))), feat);
  const fileRow = h('div', { class: 'yy-row' }, h('span', { class: 'small muted' }, tr('Parametre dosyası')), fileBtn, fileClear, fileInfo, fileInp);
  cfg.append(warn, px4Box, fileRow);

  async function readFile(f) {
    if (!f) return;
    if (f.size > PARAM_MAX_BYTES) { fileInfo.textContent = tr('Parametre dosyası çok büyük (en çok 512 KB)'); return; }
    const text = await f.text();
    const r = readParamsText(text);
    if (r.error) { st.params = null; fileInfo.textContent = tr(r.error); } else st.params = { text, name: f.name, count: r.count };
    draw(); onChange(st);
  }
  function draw() {
    const type = getType();
    clear(cards, stacks.map(s => {
      const status = stackStatus(s), on = st.stack === s.key, dis = status !== 'active';
      const badge = s.key === 'ardupilot' ? h('span', { class: 'yy-badge def' }, tr('Varsayılan')) : STACK_BADGE[status] ? h('span', { class: 'yy-badge' }, tr(STACK_BADGE[status])) : null;
      return h('button', { type: 'button', class: `yy-card ${on ? 'on' : ''}`, 'data-stack': s.key, disabled: dis || undefined, title: dis ? `${s.name}: ${tr(s.reason || '')}` : tr(s.desc || ''),
        onclick: () => { if (dis) return; st.stack = s.key; draw(); onChange(st); } },
      h('b', null, s.name), badge, h('span', { class: 'yy-meta' }, [s.rtos, s.license, s.version].filter(Boolean).join(' · ')),
      dis ? h('span', { class: 'yy-why' }, tr(s.reason || '')) : h('span', { class: 'yy-why' }, tr(s.desc || '')));
    }));
    const px4 = st.stack === 'px4';
    px4Box.hidden = !px4;
    if (px4) {
      const afs = airframesFor(stacks, type);
      if (!afs.some(a => a.id === st.airframe)) st.airframe = afs[0]?.id ?? null;
      clear(afSel, afs.map(a => h('option', { value: a.id, selected: a.id === st.airframe || undefined }, `${a.id} · ${a.name}`)));
      afSel.disabled = !afs.length;
      spSel.value = String(st.speed);
      const p = stacks.find(s => s.key === 'px4');
      clear(feat, Object.entries(p?.features || {}).map(([k, v]) => h('li', { class: v.ok ? 'ok' : 'no', title: tr(v.note) }, h('i', null, v.ok ? '✓' : '✗'), h('span', null, tr(FEAT_NAMES[k] || k)))));
      gcsNote.textContent = tr('GCS: QGroundControl önerilir (UDP köprüsü aynı; Mission Planner da bağlanır). Kurulum: {b}', { b: p?.build || p?.version || 'PX4' });
    }
    const err = stackTypeError(st.stack, type, stacks);
    warn.hidden = !err; warn.textContent = err ? tr(err) : '';
    const ext = (stacks.find(s => s.key === st.stack) || {}).params_ext || '';
    fileBtn.title = tr('{s} parametre dosyası ({e}); açılışta yüklenir', { s: st.stack === 'px4' ? 'PX4 / QGroundControl' : 'ArduPilot / Mission Planner', e: ext });
    fileClear.hidden = !st.params;
    if (st.params) fileInfo.textContent = `${st.params.name} · ${tr('{n} satır', { n: st.params.count })}`;
    else if (!fileInfo.textContent || !/büyük|okunamadı|satırı yok/.test(fileInfo.textContent)) fileInfo.textContent = tr('İsteğe bağlı ({e})', { e: ext });
  }
  function clear(el, kids) { el.textContent = ''; (kids || []).forEach(k => k && el.append(k)); }
  const el = h('div', { class: 'yy-stack' }, h('p', { class: 'small muted' }, tr('Uçuş yazılımı (otopilot) yığını: dron SITL olarak bu yazılımla uçar. Varsayılan ArduPilot; PX4 SIH fiziğiyle Multikopter, Sabit Kanat ve VTOL için.')), cards, cfg);
  draw();
  return {
    el,
    get value() { return { ...st }; },
    isPx4: () => st.stack === 'px4',
    error: () => stackTypeError(st.stack, getType(), stacks),
    body: () => stackBody(st),
    label: () => stackLabel(st, stacks, getType()),
    refresh: draw,
  };
}
