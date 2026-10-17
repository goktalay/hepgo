// Uçuş Simülatörü — Dron Yönetimi › Uçuş Simülatörü sekmesi (#/drone/sim[/<oturum>]). Sözleşme: docs/ucus-simulatoru.md.
// drone.js `sim` sayfasında dinamik yükler: import('./flightsim.js').then(mod => mod.render(view, params, ctx, { m, head, mock }))
// • Sihirbaz (§6): dron tipi kartları → merkez seçimi (/api/drone/sim/meta centers) → dünya kaydırıcıları + "Rastgele tohum" + küçük 3B
//   önizleme → Başlat (POST /api/drone/sim/sessions). Açık oturum varsa üstte liste: devam et / bitir.
// • Oturum ekranı: tam alan 3B tuval (flightsim3d.js) + HUD (sağ), Mission Planner bağlantı kutusu (sol alt), alt araç çubuğu
//   (kamera 1–4, Sıfırla, Bitir, ARM/DISARM/mod — yazma izni varsa), olay şeridi (STATUSTEXT), ÇARPIŞMA bandı.
// • WS istemcisi /ws/drone/sim/{id}: hello/tele/event/state/end; ping 10 sn; üstel geri çekilmeli yeniden bağlanma; 4403/4404 kalıcı.
// • `?mock=1`: arka uç yokken yerel kinematik üretici (WS yerine) — sihirbaz, 3B dünya ve HUD arka uçsuz denenir. Mock oturumlar yalnız
//   bu sekmede (bellekte) yaşar; komutlar (arm/disarm/mode/takeoff/rtl/reset/crash) üreticiye uygulanır.
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, onLeave, segmented, toast, toastError, t as tr } from '../ui.js';
import { ATTRIBUTION, CAMERA_MODES, WORLD_DEFAULTS, createFlightSim3D } from './flightsim3d.js';

const API = '/api/drone/sim';
// Dron tipleri (SITL TIP_ESLEME anahtarları); meta.types gelirse adlar oradan, açıklama/simge buradan
const TYPES = [
  ['multirotor', 'Multikopter', 'Dört rotor; dikey kalkış, hassas konum tutma. ArduCopter.', 'quad'],
  ['hexarotor', 'Hexakopter', 'Altı rotor; daha yüksek taşıma ve yedeklilik. ArduCopter hexa.', 'hexa'],
  ['helikopter', 'Helikopter', 'Ana rotor + kuyruk rotoru. ArduCopter heli.', 'heli'],
  ['sabit_kanat', 'Sabit Kanat', 'Caymaz uçak; pistten kalkış, uzun menzil. ArduPlane.', 'plane'],
  ['vtol', 'VTOL', 'Uçak + dört dikey rotor (quadplane). ArduPlane.', 'vtol'],
];
const TYPE_NAME = Object.fromEntries(TYPES.map(([k, n]) => [k, n]));
const STATE_BADGE = { BASLIYOR: 'yellow', HAZIR: 'green', HATA: 'red', KAPANDI: 'gray' };
const STATE_TEXT = { BASLIYOR: 'Başlıyor', HAZIR: 'Hazır', HATA: 'Hata', KAPANDI: 'Kapandı' };
const COPTER_MODES = ['STABILIZE', 'ALT_HOLD', 'LOITER', 'POSHOLD', 'GUIDED', 'AUTO', 'RTL', 'LAND'];
const PLANE_MODES = ['MANUAL', 'FBWA', 'FBWB', 'CRUISE', 'TAKEOFF', 'AUTO', 'LOITER', 'RTL'];
const VTOL_MODES = [...PLANE_MODES, 'QSTABILIZE', 'QHOVER', 'QLOITER', 'QLAND'];
const isPlane = type => type === 'sabit_kanat' || type === 'vtol';
const modesFor = type => (type === 'vtol' ? VTOL_MODES : isPlane(type) ? PLANE_MODES : COPTER_MODES);
const f1 = v => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(1));
const f0 = v => (v == null || Number.isNaN(Number(v)) ? '—' : String(Math.round(Number(v))));
const copy = async (txt, what = 'Kopyalandı') => { try { await navigator.clipboard.writeText(txt); toast(what); } catch { toast('Kopyalanamadı; metni elle seçin', 'err'); } };
const svgIco = body => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const TYPE_ICON = {
  quad: svgIco('<rect x="9.5" y="9.5" width="5" height="5" rx="1.2"/><path d="M9.5 9.5 6.6 6.6M14.5 9.5l2.9-2.9M9.5 14.5l-2.9 2.9M14.5 14.5l2.9 2.9"/><circle cx="5.2" cy="5.2" r="2.6"/><circle cx="18.8" cy="5.2" r="2.6"/><circle cx="5.2" cy="18.8" r="2.6"/><circle cx="18.8" cy="18.8" r="2.6"/>'),
  hexa: svgIco('<circle cx="12" cy="12" r="2.4"/><path d="M12 9.6V5.5M12 14.4v4.1M9.9 10.8 6.3 8.7M14.1 10.8l3.6-2.1M9.9 13.2l-3.6 2.1M14.1 13.2l3.6 2.1"/><circle cx="12" cy="4" r="1.6"/><circle cx="12" cy="20" r="1.6"/><circle cx="5" cy="8" r="1.6"/><circle cx="19" cy="8" r="1.6"/><circle cx="5" cy="16" r="1.6"/><circle cx="19" cy="16" r="1.6"/>'),
  heli: svgIco('<path d="M3 7h18M12 7v3"/><ellipse cx="11" cy="13" rx="4.5" ry="3"/><path d="M15.5 13h5l-2 2.5M20.5 13v-3M7 18h8"/>'),
  plane: svgIco('<path d="M12 3v18M4 13l8-3 8 3M8 20l4-2 4 2M12 3c1.5 0 2 2 2 4v3M12 3c-1.5 0-2 2-2 4v3"/>'),
  vtol: svgIco('<path d="M12 4v16M5 12l7-2 7 2M9 20l3-1.5 3 1.5"/><circle cx="6" cy="7" r="2"/><circle cx="18" cy="7" r="2"/><circle cx="6" cy="17" r="2"/><circle cx="18" cy="17" r="2"/>'),
};

// ======================================================================
// Giriş: #/drone/sim[?mock=1] → sihirbaz + açık oturumlar · #/drone/sim/<id>[?mock=1] → oturum ekranı
// ======================================================================
export async function render(view, params, ctx, extra = {}) {
  const joined = (params || []).join('/');
  const [path, qs] = joined.split('?');
  const sp = new URLSearchParams(qs || '');
  const mock = extra.mock || sp.get('mock') === '1';
  const parts = path.split('/').filter(Boolean);   // ['sim', '<id>']
  const sid = parts[1] || null;
  const canWrite = !!(ctx.user?.master || extra.m?.can?.command || (ctx.user?.write_modules || []).includes('drone'));
  const backend = mock ? mockBackend(ctx) : restBackend();
  const head = extra.head || (sub => h('div', { class: 'page-head' }, h('div', { class: 'page-head-t' }, h('h1', null, 'Uçuş Simülatörü'), sub ? h('div', { class: 'sub' }, sub) : null)));
  if (sid) return renderSession(view, ctx, backend, sid, { mock, canWrite });
  return renderWizard(view, ctx, backend, head, { mock, canWrite });
}

// ======================================================================
// Arka uç erişimi: REST ya da mock. Ortak yüz: meta(), sessions(), session(id), create(body), end(id), cmd(id, name, params), socket(id, handlers)
// ======================================================================
function restBackend() {
  return {
    mock: false,
    meta: () => api.get(`${API}/meta`),
    sessions: () => api.get(`${API}/sessions`),
    session: id => api.get(`${API}/sessions/${encodeURIComponent(id)}`),
    create: body => api.post(`${API}/sessions`, body),
    end: id => api.del(`${API}/sessions/${encodeURIComponent(id)}`),
    cmd: (id, name, params = {}) => api.post(`${API}/sessions/${encodeURIComponent(id)}/cmd`, { name, params }),
    socket: (id, handlers) => wsClient(id, handlers),
    href: id => `#/drone/sim${id ? `/${id}` : ''}`,
  };
}

// WS istemcisi: hello/tele/event/state/end; 10 sn ping; kopunca üstel geri çekilme (0.5 → 10 sn); 4403/4404 kalıcı hata.
function wsClient(id, handlers) {
  let ws = null, closed = false, retry = 0, pingIv = 0, timer = 0;
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/drone/sim/${encodeURIComponent(id)}`;
  const open = () => {
    if (closed) return;
    handlers.status?.(retry ? 'reconnect' : 'connecting');
    try { ws = new WebSocket(url); } catch (err) { handlers.fatal?.(err.message); return; }
    ws.onopen = () => { retry = 0; handlers.status?.('open'); pingIv = setInterval(() => send({ t: 'ping' }), 10000); };
    ws.onmessage = e => { let msg; try { msg = JSON.parse(e.data); } catch { return; } handlers.message?.(msg); };
    ws.onerror = () => { /* onclose yeniden bağlanır */ };
    ws.onclose = ev => {
      clearInterval(pingIv);
      if (closed) return;
      if (ev.code === 4403) return handlers.fatal?.('auth');
      if (ev.code === 4404) return handlers.fatal?.('notfound');
      handlers.status?.('closed');
      timer = setTimeout(open, Math.min(10000, 500 * 2 ** Math.min(retry++, 5)));
    };
  };
  const send = obj => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); };
  open();
  return { send, close: () => { closed = true; clearTimeout(timer); clearInterval(pingIv); try { ws?.close(); } catch { /* */ } } };
}

// ======================================================================
// Sihirbaz + açık oturum listesi
// ======================================================================
async function renderWizard(view, ctx, be, head, { mock, canWrite }) {
  let meta;
  try { meta = await be.meta(); } catch (err) {
    clear(view, head('Uçuş Simülatörü'), h('div', { class: 'card empty' }, h('p', null, h('b', null, 'Simülatör servisi yanıt vermedi.')), h('p', { class: 'small muted' }, err.message),
      h('p', { class: 'small muted' }, 'Arka uç hazır değilse arayüzü sahte veriyle denemek için adrese ?mock=1 ekleyin: ', h('a', { href: '#/drone/sim?mock=1' }, '#/drone/sim?mock=1'))));
    return;
  }
  const types = (meta.types?.length ? meta.types : TYPES.map(([key, name]) => ({ key, name }))).map(t => {
    const d = TYPES.find(x => x[0] === t.key) || [t.key, t.name, '', 'quad'];
    return { key: t.key, name: t.name || d[1], desc: d[2], icon: d[3], binary: t.binary };
  });
  const centers = meta.centers || [];
  const defaults = { ...WORLD_DEFAULTS, ...(meta.world_defaults || {}) };
  const S = { type: types[0]?.key || 'multirotor', center: centers[0]?.id ?? null, world: { ...defaults, seed: randomSeed() } };

  // ---------- açık oturumlar ----------
  const openBox = h('div');
  const drawOpen = async () => {
    let rows = [];
    try { rows = await be.sessions(); } catch { rows = []; }
    if (!rows.length) { clear(openBox); return; }
    clear(openBox, h('div', { class: 'card card-pad fs-open no-collapse' }, h('h3', null, tr('Açık oturumlar ({n})', { n: rows.length })),
      h('div', { class: 'fs-open-list' }, rows.map(s => h('div', { class: 'fs-open-row' },
        h('div', { class: 'fs-open-main' }, h('b', null, TYPE_NAME[s.type] || s.type), h('span', { class: `badge ${STATE_BADGE[s.state] || 'gray'}` }, STATE_TEXT[s.state] || s.state),
          h('div', { class: 'small muted' }, [s.center?.name, s.owner?.name, s.created_at ? fmtDateTime(s.created_at) : null, s.udp_port ? `UDP ${s.udp_port}` : null].filter(Boolean).join(' · '))),
        h('div', { class: 'pill-group' },
          h('a', { class: 'btn sm primary', href: be.href(s.id) }, 'Devam et'),
          canWrite ? h('button', { class: 'btn sm danger', onclick: async () => {
            if (!await confirmDialog('Oturumu bitir', 'Simülatör oturumu kapatılsın mı? SITL süreci ve UDP portu kapanır.', { okLabel: 'Bitir', danger: true })) return;
            await be.end(s.id); toast('Oturum kapatıldı'); drawOpen();
          } }, 'Bitir') : null))))));
  };

  // ---------- 1. dron tipi ----------
  const typeCards = h('div', { class: 'fs-types' });
  const drawTypes = () => clear(typeCards, types.map(t => h('button', { type: 'button', class: `fs-type ${S.type === t.key ? 'on' : ''}`, onclick: () => { S.type = t.key; drawTypes(); preview?.setType(t.key); } },
    h('span', { class: 'fs-type-ico', html: TYPE_ICON[t.icon] || TYPE_ICON.quad }),
    h('b', null, t.name), h('span', { class: 'small muted' }, t.desc || ''))));
  drawTypes();

  // ---------- 2. merkez ----------
  const centerList = h('div', { class: 'fs-centers' });
  const centerOf = () => centers.find(c => c.id === S.center) || null;
  const drawCenters = () => clear(centerList, centers.length ? centers.map(c => h('button', { type: 'button', class: `fs-center ${S.center === c.id ? 'on' : ''}`, onclick: () => { S.center = c.id; drawCenters(); if (preview) { progInfo(null); preview.setOrigin(c.lat, c.lon, S.world); } } },
    h('b', null, c.name), h('span', { class: 'small muted' }, [c.location_name, `${Number(c.lat).toFixed(5)}, ${Number(c.lon).toFixed(5)}`, c.alt != null ? `${f0(c.alt)} m` : null].filter(Boolean).join(' · '))))
    : h('div', { class: 'small muted fs-nocenter' }, 'Kayıtlı merkez yok. Önce ', h('a', { href: '#/drone/routes' }, 'Rotalar › Merkezler'), ' bölümünden bir merkez ekleyin.'));
  drawCenters();

  // ---------- 3. dünya ----------
  let preview = null, rebuildT = 0;
  const progBar = h('div', { class: 'fs-preview-prog', hidden: true });
  const previewBox = h('div', { class: 'fs-preview' }, h('div', { class: 'fs-preview-msg' }, '3B önizleme hazırlanıyor…'), progBar);
  const previewInfo = h('div', { class: 'small muted fs-preview-info' });
  // Gerçek kip yükleme ilerlemesi / özet (önizleme kutusu üstünde şerit + altında bilgi satırı)
  const progInfo = p => {
    if (!p) { progBar.hidden = false; progBar.textContent = tr('Arazi planı alınıyor…'); return; }
    if (p.stage === 'done') {
      progBar.hidden = true;
      if (p.real) {
        const c = p.counts || {};
        previewInfo.textContent = `${tr('Gerçek arazi · yükseklik {a}…{b} m · ev {h} m MSL', { a: f0(p.hmin), b: f0(p.hmax), h: f0(p.homeElev) })} · ${tr('{b} bina · {f} orman · {w} su · {r} pist', { b: c.buildings ?? 0, f: c.forests ?? 0, w: c.water ?? 0, r: c.runways ?? 0 })}`;
        const info = preview?.terrainInfo;
        if (info?.osmError) previewInfo.textContent += ` · ${tr('OSM verisi alınamadı: binalar/orman/su gösterilmiyor ({e})', { e: info.osmError })}`;
      } else previewInfo.textContent = S.world.mode === 'real' ? '' : tr('Prosedürel dünya: tohumlu rastgele arazi, binalar ve ağaçlar.');
      return;
    }
    progBar.hidden = false;
    progBar.textContent = p.stage === 'elev' ? tr('Yükseklik karoları {d}/{n}', { d: p.done, n: p.total }) : p.stage === 'img' ? tr('Uydu karoları {d}/{n}', { d: p.done, n: p.total })
      : p.stage === 'osm' ? tr('Harita verileri (OSM) alınıyor…') : tr('Arazi planı alınıyor…');
  };
  const onFallback = e => { previewInfo.textContent = tr('Gerçek veri alınamadı, prosedürele düşüldü: {e}', { e }); toast(previewInfo.textContent, 'err'); };
  const schedule = () => { clearTimeout(rebuildT); rebuildT = setTimeout(() => { if (S.world.mode === 'real') progInfo(null); preview?.setWorld(S.world); }, 300); };
  const sliders = {};
  const slider = (key, label, min, max, step, fmt = v => v) => {
    const out = h('b', { class: 'fs-val' }, fmt(S.world[key]));
    const lbl = h('span', null, label);
    const inp = h('input', { type: 'range', min, max, step, value: S.world[key], oninput: () => { S.world[key] = Number(inp.value); out.textContent = fmt(S.world[key]); schedule(); } });
    const el = h('label', { class: 'fs-slider' }, h('span', null, lbl, out), inp);
    sliders[key] = { el, lbl, inp, out, fmt, label };
    return el;
  };
  const seedInp = h('input', { class: 'input mono', value: S.world.seed, inputmode: 'numeric', style: { width: '120px' }, onchange: () => { S.world.seed = Number(seedInp.value) || 1; seedInp.value = S.world.seed; schedule(); } });
  const runwayCb = h('input', { type: 'checkbox', checked: S.world.runway !== false, onchange: () => { S.world.runway = runwayCb.checked; schedule(); } });
  const timeSeg = segmented([['day', 'Gündüz'], ['dusk', 'Akşam'], ['night', 'Gece']], S.world.time, v => { S.world.time = v; schedule(); });
  const seedBox = h('div', { class: 'fs-seed' }, h('span', { class: 'small muted' }, 'Tohum'), seedInp,
    h('button', { class: 'btn sm', type: 'button', onclick: () => { S.world.seed = randomSeed(); seedInp.value = S.world.seed; schedule(); } }, '🎲 Rastgele tohum'));
  // Dünya kipi: gerçek arazi (yükseklik + uydu + OSM; prosedürel ayarlar özelleştirme) / prosedürel
  const modeHint = h('p', { class: 'small muted fs-mode-hint' });
  const applyMode = () => {
    const real = S.world.mode === 'real';
    for (const k of ['mountain_height', 'mountain_count', 'water']) sliders[k].el.hidden = real;
    seedBox.hidden = real;
    sliders.tree_density.lbl.textContent = tr(real ? 'Ağaç sıklığı (orman alanlarına ölçek)' : 'Ağaç sıklığı');
    sliders.building_count.lbl.textContent = tr(real ? 'Ek bina sayısı (0 = yalnız gerçek binalar)' : 'Bina sayısı');
    modeHint.textContent = real
      ? `${tr('Gerçek kipte seçili merkezin çevresi gerçek yükseklik, uydu görüntüsü ve OpenStreetMap binalarıyla kurulur; veriler ilk kullanımda indirilip sunucuda önbelleklenir.')} ${ATTRIBUTION}`
      : tr('Prosedürel dünya: tohumlu rastgele arazi, binalar ve ağaçlar.');
  };
  let bcTouched = false;
  const modeSeg = segmented([['real', 'Gerçek arazi'], ['procedural', 'Prosedürel']], S.world.mode, v => {
    S.world.mode = v;
    if (!bcTouched) { S.world.building_count = v === 'real' ? 0 : defaults.building_count; sliders.building_count.inp.value = S.world.building_count; sliders.building_count.out.textContent = S.world.building_count; }
    applyMode(); schedule();
  });
  const worldForm = h('div', { class: 'fs-world' },
    h('div', { class: 'fs-mode-row' }, h('span', { class: 'small muted' }, 'Dünya kipi'), modeSeg),
    modeHint,
    h('div', { class: 'fs-world-grid' },
      slider('size_m', 'Dünya boyutu', 1000, 10000, 500, v => `${v} m`),
      slider('tree_density', 'Ağaç sıklığı', 0, 1, 0.05, v => `%${Math.round(v * 100)}`),
      slider('mountain_height', 'Dağ yüksekliği', 0, 1500, 25, v => `${v} m`),
      slider('mountain_count', 'Dağ sayısı', 1, 10, 1),
      slider('building_count', 'Bina sayısı', 0, 200, 5),
      slider('water', 'Su oranı', 0, 0.6, 0.05, v => `%${Math.round(v * 100)}`),
      slider('fog', 'Sis', 0, 1, 0.05, v => `%${Math.round(v * 100)}`),
      slider('wind_ms', 'Rüzgâr hızı', 0, 20, 0.5, v => `${v} m/s`),
      slider('wind_dir', 'Rüzgâr yönü', 0, 359, 1, v => `${v}°`),
      slider('runway_heading', 'Pist yönü', 0, 359, 1, v => `${v}°`)),
    h('div', { class: 'fs-world-row' },
      h('label', { class: 'check' }, runwayCb, 'Pist'),
      h('div', { class: 'fs-time' }, h('span', { class: 'small muted' }, 'Saat'), timeSeg),
      seedBox));
  sliders.building_count.inp.addEventListener('input', () => { bcTouched = true; });
  applyMode();

  // ---------- 4. başlat ----------
  const startBtn = h('button', { class: 'btn primary fs-start', disabled: !canWrite || !centers.length, onclick: async () => {
    if (S.center == null) { toast('Önce bir merkez seçin', 'err'); return; }
    startBtn.disabled = true;
    try {
      const s = await be.create({ type: S.type, center_id: S.center, world: { ...S.world } });
      toast('Simülatör oturumu açıldı');
      location.hash = be.href(s.id);
    } catch (err) {
      const msg = { 400: 'Geçersiz ayar; dünya değerlerini ve merkezi kontrol edin', 409: 'Oturum sınırı doldu; açık bir oturumu bitirin', 503: 'SITL hazır değil (ikili ya da boş port yok)' }[err?.status];
      toast(msg || err.message, 'err');
      startBtn.disabled = false;
    }
  } }, '▶ Başlat');
  const limits = meta.limits || {};
  clear(view, head(mock ? 'Uçuş Simülatörü · sahte veri kipi (arka uç yok)' : 'Uçuş Simülatörü · SITL + Mission Planner köprüsü, 3B dünya'),
    mock ? h('div', { class: 'alert warn fs-mock-note' }, 'Sahte veri kipi: oturum sunucuda açılmaz; telemetri tarayıcıda üretilir. Gerçek kullanım için adresten ?mock=1 kaldırın.') : null,
    openBox,
    h('div', { class: 'card card-pad fs-step no-collapse' }, h('h3', null, h('span', { class: 'fs-no' }, '1'), 'Dron tipi'), typeCards),
    h('div', { class: 'card card-pad fs-step no-collapse' }, h('h3', null, h('span', { class: 'fs-no' }, '2'), 'Merkez'), h('p', { class: 'small muted' }, 'Sanal dünyanın merkezi ve kalkış noktası. Mission Planner haritası bu koordinatı gösterir.'), centerList),
    h('div', { class: 'card card-pad fs-step no-collapse' }, h('h3', null, h('span', { class: 'fs-no' }, '3'), 'Dünya'),
      h('div', { class: 'fs-world-wrap' }, worldForm, h('div', null, previewBox, previewInfo))),
    h('div', { class: 'fs-start-row' },
      h('div', { class: 'small muted' }, canWrite
        ? tr('En çok {n} eşzamanlı oturum · oturum süresi {m} dk', { n: limits.max_sessions ?? '—', m: limits.max_minutes ?? '—' })
        : 'Oturum açmak için Dron Yönetimi yazma izni gerekir; açık oturumları izleyebilirsiniz.'),
      startBtn));
  drawOpen();

  // 3B önizleme (küçük, kendi etrafında dönen kamera); sayfa değişince serbest bırakılır
  try {
    if (S.world.mode === 'real') progInfo(null);
    const c0 = centerOf();
    preview = await createFlightSim3D(previewBox, S.world, { preview: true, type: S.type, origin: c0 ? { lat: c0.lat, lon: c0.lon } : undefined, onProgress: progInfo, onFallback });
    previewBox.querySelector('.fs-preview-msg')?.remove();
    if (preview.terrainInfo) progInfo({ stage: 'done', real: preview.real, ...preview.terrainInfo });
  } catch (err) {
    clear(previewBox, h('div', { class: 'fs-preview-msg' }, tr('3B önizleme açılamadı: {e}', { e: err.message })));
  }
  onLeave(() => { clearTimeout(rebuildT); preview?.dispose(); preview = null; });
}

const randomSeed = () => Math.floor(Math.random() * 2147483646) + 1;

// ======================================================================
// Oturum ekranı: tam alan 3B + HUD + Mission Planner kutusu + araç çubuğu + olaylar + çarpışma bandı
// ======================================================================
async function renderSession(view, ctx, be, sid, { mock, canWrite }) {
  let session;
  try { session = await be.session(sid); } catch (err) {
    clear(view, h('div', { class: 'card empty' }, h('p', null, h('b', null, 'Oturum bulunamadı.')), h('p', { class: 'small muted' }, err.message),
      h('a', { class: 'btn', href: be.href() }, 'Simülatör ana sayfası')));
    return;
  }
  const type = session.type, modes = modesFor(type);
  const world = { ...WORLD_DEFAULTS, ...(session.world || {}) };

  // ---------- iskelet ----------
  const stage = h('div', { class: 'fs-stage', 'data-immersive': '1' });
  const mount = h('div', { class: 'fs-canvas' });
  const msg = h('div', { class: 'fs-msg' }, '3B dünya hazırlanıyor…');
  const crash = h('div', { class: 'fs-crash', hidden: true }, h('b', null, 'ÇARPIŞMA'), h('span', { class: 'fs-crash-sub' }));
  const events = h('div', { class: 'fs-events' });
  const stateBadge = h('span', { class: `badge ${STATE_BADGE[session.state] || 'gray'}` }, STATE_TEXT[session.state] || session.state);
  const wsBadge = h('span', { class: 'badge gray', title: 'Telemetri bağlantısı (WebSocket)' }, 'Bağlanıyor…');
  const nav = h('div', { class: 'fs-nav' },
    h('a', { class: 'fs-nav-back', href: be.href(), title: 'Simülatör listesine dön' }, '←'),
    h('b', null, 'Uçuş Simülatörü'), h('span', { class: 'fs-nav-sub' }, `${TYPE_NAME[type] || type} · ${session.center?.name || '—'}`), stateBadge, wsBadge,
    mock ? h('span', { class: 'badge purple' }, 'Sahte veri') : null,
    h('button', { class: 'fs-nav-btn', type: 'button', title: 'Tam ekran', onclick: () => { if (document.fullscreenElement) document.exitFullscreen?.(); else stage.requestFullscreen?.(); } }, '⛶'));

  // HUD (sağ): sabit satırlar, değerler textContent ile güncellenir (DOM yeniden kurulmaz)
  const val = cls => h('b', { class: `fs-v ${cls || ''}` }, '—');
  const V = { mode: h('span', { class: 'badge blue fs-mode' }, '—'), arm: h('span', { class: 'badge gray fs-arm' }, 'DISARMED'),
    agl: val(), msl: val(), air: val(), gnd: val(), climb: val(), hdg: val(), gps: val(), batt: val(), thr: val(), wind: val() };
  const row = (label, el, unit) => h('div', { class: 'fs-row' }, h('span', null, label), h('span', { class: 'fs-rv' }, el, unit ? h('i', null, unit) : null));
  const rcBars = Array.from({ length: 8 }, (_, i) => h('div', { class: 'fs-rc', title: tr('Kanal {n}', { n: i + 1 }) }, h('i'), h('small', null, String(i + 1))));
  const thrBar = h('div', { class: 'fs-thr' }, h('i'));
  const windArrow = h('span', { class: 'fs-wind-arrow' }, '➤');
  const hud = h('div', { class: 'fs-hud mono' },
    h('div', { class: 'fs-hud-head' }, V.mode, V.arm),
    row('AGL', V.agl, 'm'), row('MSL', V.msl, 'm'),
    row('Hava hızı', V.air, 'm/s'), row('Yer hızı', V.gnd, 'm/s'), row('Dikey hız', V.climb, 'm/s'),
    row('Yön', V.hdg, '°'), row('GPS', V.gps), row('Batarya', V.batt),
    h('div', { class: 'fs-row' }, h('span', null, 'Gaz'), h('span', { class: 'fs-rv' }, V.thr, h('i', null, '%'))), thrBar,
    h('div', { class: 'fs-row fs-row-rc' }, h('span', null, 'RC'), h('div', { class: 'fs-rcs' }, rcBars)),
    h('div', { class: 'fs-row' }, h('span', null, 'Rüzgâr'), h('span', { class: 'fs-rv' }, windArrow, V.wind, h('i', null, 'm/s'))));
  V.wind.textContent = `${f1(world.wind_ms)} @ ${f0(world.wind_dir)}°`;
  windArrow.style.transform = `rotate(${(Number(world.wind_dir) || 0) + 90}deg)`;   // ➤ sağa bakar; rüzgâr "nereden" → ok akış yönünü gösterir

  // Mission Planner bağlantı kutusu (sol alt)
  const addr = `${session.host || location.hostname}:${session.udp_port || '—'}`;
  const gcsBadge = h('span', { class: 'badge gray' }, 'Bekleniyor');
  const mp = h('div', { class: 'fs-mp' },
    h('div', { class: 'fs-mp-head' }, h('b', null, 'Mission Planner bağlantısı'), gcsBadge),
    h('div', { class: 'fs-mp-addr' }, h('code', { class: 'mono' }, `UDP ${addr}`), h('button', { class: 'btn sm', type: 'button', onclick: () => copy(addr, 'Adres kopyalandı') }, 'Kopyala')),
    h('div', { class: 'small fs-mp-hint' }, 'Mission Planner › sağ üst bağlantı türü UDP › CONNECT › port ', h('b', null, String(session.udp_port || '—')), '. USB kumanda: Mission Planner › Joystick.'));

  // Alt araç çubuğu: kamera 1–4 · Sıfırla · Bitir · ARM/DISARM · mod · Kalkış · RTL (yazma izni)
  const camBtns = CAMERA_MODES.map(([k, label], i) => h('button', { class: 'btn sm', type: 'button', 'data-cam': k, title: tr('{label} (tuş {n})', { label, n: i + 1 }), onclick: () => sim?.setCamera(k) }, `${i + 1} `, label));   // etiket ayrı çocuk: çeviri kataloğundan karşılığı bulunur
  const gimbalLbl = h('span', { class: 'small fs-gimbal', hidden: true }, '');
  const armBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => cmd(last?.armed ? 'disarm' : 'arm') }, 'ARM');
  const modeSel = h('select', { class: 'input sm fs-modesel', onchange: () => { if (modeSel.value) cmd('mode', { mode: modeSel.value }); } },
    h('option', { value: '' }, 'Mod…'), modes.map(mm => h('option', { value: mm }, mm)));
  const bar = h('div', { class: 'fs-bar' },
    h('div', { class: 'pill-group' }, camBtns),
    gimbalLbl,
    h('span', { class: 'spacer' }),
    canWrite ? h('div', { class: 'pill-group' },
      armBtn, modeSel,
      h('button', { class: 'btn sm', type: 'button', onclick: () => takeoffDialog() }, 'Kalkış'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => cmd('rtl') }, 'RTL')) : null,
    h('div', { class: 'pill-group' },
      h('button', { class: 'btn sm', type: 'button', title: 'SITL aynı ayarlarla yeniden başlar; çarpışma kaldırılır', onclick: () => reset() }, '↺ Sıfırla'),
      h('button', { class: 'btn sm danger', type: 'button', onclick: () => endSession() }, 'Bitir')));
  const ended = h('div', { class: 'fs-ended', hidden: true });
  const attrib = world.mode === 'real' ? h('div', { class: 'fs-attrib' }, ATTRIBUTION) : null;
  stage.append(mount, msg, crash, hud, mp, events, bar, nav, ended);
  if (attrib) stage.append(attrib);

  // Tam alan yerleşimi (Canlı Uçuş iframe kalıbı): main#view mutlak konumlu, scroller kaydırmaz
  view.classList.add('ops-view');
  const scroller = view.closest('.scroller');
  scroller?.classList.add('ops-scroll');
  clear(view, stage);

  // Olay şeridi (3B kurulumundan önce tanımlı: gerçek arazi yükleme özeti de buraya yazılır)
  const addEvent = (text, severity = 'info') => {
    const sev = String(severity || 'info').toLowerCase();
    const cls = /err|crit|alert|emerg/.test(sev) ? 'err' : /warn/.test(sev) ? 'warn' : 'info';
    const now = new Date();
    events.prepend(h('div', { class: `fs-ev ${cls}` }, h('span', { class: 'fs-ev-t' }, `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`), h('span', null, text)));
    while (events.children.length > 8) events.lastChild.remove();
  };

  // ---------- 3B ----------
  let sim = null, last = null, socket = null, destroyed = false, worldReady = false;
  const progMsg = p => {   // gerçek arazi yükleme ilerlemesi (3B tuval üstünde)
    if (destroyed) return;
    if (p.stage === 'done') {
      worldReady = true;
      if (session.state === 'HAZIR' || mock) msg.hidden = true;
      if (p.real) addEvent(`${tr('Gerçek arazi · yükseklik {a}…{b} m · ev {h} m MSL', { a: f0(p.hmin), b: f0(p.hmax), h: f0(p.homeElev) })} · ${tr('{b} bina · {f} orman · {w} su · {r} pist', { b: p.counts?.buildings ?? 0, f: p.counts?.forests ?? 0, w: p.counts?.water ?? 0, r: p.counts?.runways ?? 0 })}`);
      const info = sim?.terrainInfo;
      if (p.real && info?.osmError) addEvent(tr('OSM verisi alınamadı: binalar/orman/su gösterilmiyor ({e})', { e: info.osmError }), 'warning');
      return;
    }
    msg.hidden = false;
    msg.textContent = p.stage === 'elev' ? tr('Yükseklik karoları {d}/{n}', { d: p.done, n: p.total }) : p.stage === 'img' ? tr('Uydu karoları {d}/{n}', { d: p.done, n: p.total })
      : p.stage === 'osm' ? tr('Harita verileri (OSM) alınıyor…') : tr('Arazi planı alınıyor…');
  };
  try {
    if (world.mode === 'real') { msg.textContent = tr('Arazi planı alınıyor…'); }
    sim = await createFlightSim3D(mount, world, {
      type, origin: { lat: session.center?.lat, lon: session.center?.lon },
      onCameraChange: mode => { camBtns.forEach(b => b.classList.toggle('primary', b.dataset.cam === mode)); gimbalLbl.hidden = mode !== 'fpv'; gimbalLbl.textContent = tr('Gimbal {d}° (↑↓ / tekerlek)', { d: sim?.getGimbal() ?? 0 }); },
      onCollision: info => onCrash(info),
      onProgress: progMsg,
      onFallback: e => { const t = tr('Gerçek veri alınamadı, prosedürele düşüldü: {e}', { e }); addEvent(t, 'warning'); toast(t, 'err'); if (attrib) attrib.hidden = true; },
    });
    if (sim.terrainInfo && !worldReady) progMsg({ stage: 'done', real: sim.real, ...sim.terrainInfo });
    msg.hidden = true;
  } catch (err) {
    msg.textContent = tr('3B dünya açılamadı: {e}', { e: err.message });
    msg.classList.add('err');
  }
  camBtns[0].classList.add('primary');
  const gimbalTick = setInterval(() => { if (!gimbalLbl.hidden && sim) gimbalLbl.textContent = tr('Gimbal {d}° (↑↓ / tekerlek)', { d: sim.getGimbal() }); }, 300);

  // ---------- olaylar / durum ----------
  const setState = st => {
    session.state = st;
    stateBadge.className = `badge ${STATE_BADGE[st] || 'gray'}`;
    stateBadge.textContent = tr(STATE_TEXT[st] || st);
    if (st === 'BASLIYOR') { msg.hidden = false; msg.textContent = tr('SITL başlıyor…'); }
    else if (st === 'HATA') { msg.hidden = false; msg.classList.add('err'); msg.textContent = tr('SITL hatası: {e}', { e: session.sitl?.error || '—' }); }
    else if (st === 'HAZIR' && sim) { msg.hidden = true; msg.classList.remove('err'); }
  };
  const setWs = st => {
    const map = { connecting: ['yellow', 'Bağlanıyor…'], reconnect: ['yellow', 'Yeniden bağlanıyor…'], open: ['green', 'Canlı'], closed: ['red', 'Bağlantı koptu'] };
    const [tone, text] = map[st] || ['gray', st];
    wsBadge.className = `badge ${tone}`; wsBadge.textContent = tr(text);
  };
  const setGcs = (connected, a) => { gcsBadge.className = `badge ${connected ? 'green' : 'gray'}`; gcsBadge.textContent = connected ? tr('Bağlı ({ip})', { ip: a || '' }) : tr('Bekleniyor'); };
  setGcs(!!session.gcs?.connected, session.gcs?.addr);
  if (session.state !== 'HAZIR') setState(session.state);

  // ---------- HUD güncelle (en çok ~12 Hz) ----------
  let hudAt = 0;
  const updateHud = t => {
    last = t;
    sim?.setTelemetry(t);
    const now = performance.now();
    if (now - hudAt < 80) return;
    hudAt = now;
    V.mode.textContent = t.mode || '—';
    V.arm.textContent = t.armed ? 'ARMED' : 'DISARMED';
    V.arm.className = `badge ${t.armed ? 'red' : 'gray'} fs-arm`;
    V.agl.textContent = f1(t.alt_rel); V.msl.textContent = f1(t.alt_msl);
    V.air.textContent = f1(t.airspeed); V.gnd.textContent = f1(t.groundspeed);
    const climb = t.climb != null ? t.climb : (t.vd != null ? -t.vd : null);
    V.climb.textContent = (climb != null && climb > 0.05 ? '+' : '') + f1(climb);
    V.hdg.textContent = f0(t.heading != null ? t.heading : (t.yaw != null ? ((t.yaw * 180 / Math.PI) + 360) % 360 : null)).padStart(3, '0');
    V.gps.textContent = `${t.gps_fix >= 3 ? '3D' : t.gps_fix === 2 ? '2D' : tr('Yok')} · ${f0(t.sats)} ${tr('uydu')}`;
    V.batt.textContent = `${t.batt_v != null ? Number(t.batt_v).toFixed(2) : '—'} V · %${f0(t.batt_pct)}`;
    V.batt.classList.toggle('warn', t.batt_pct != null && t.batt_pct < 25);
    V.thr.textContent = f0(t.throttle);
    thrBar.firstChild.style.width = `${Math.max(0, Math.min(100, Number(t.throttle) || 0))}%`;
    (t.rc || []).slice(0, 8).forEach((v, i) => { const pct = Math.max(0, Math.min(100, ((Number(v) || 1500) - 1000) / 10)); rcBars[i].firstChild.style.height = `${pct}%`; });
    if (canWrite) { armBtn.textContent = t.armed ? 'DISARM' : 'ARM'; armBtn.classList.toggle('danger', !!t.armed); if (t.mode && modeSel.value !== t.mode && document.activeElement !== modeSel) modeSel.value = modes.includes(t.mode) ? t.mode : ''; }
    if (t.gcs_connected != null) setGcs(!!t.gcs_connected, t.gcs_addr);
  };

  // ---------- komutlar ----------
  const cmd = async (name, params = {}) => {
    try { await be.cmd(sid, name, params); addEvent(tr('Komut: {c}', { c: name + (params.mode ? ` ${params.mode}` : params.alt != null ? ` ${params.alt} m` : '') })); } catch (err) { toastError(err); }
  };
  const takeoffDialog = () => {
    const alt = h('input', { class: 'input', type: 'number', min: 1, max: 500, value: isPlane(type) ? 80 : 30 });
    modal({ title: 'Kalkış', body: field('Hedef irtifa (m, AGL)', alt, isPlane(type) ? 'Uçak TAKEOFF moduna alınır; pist boyunca hızlanır.' : 'Dron GUIDED modda belirtilen irtifaya yükselir.'),
      actions: [{ label: 'Vazgeç' }, { label: 'Kalkış', class: 'primary', onClick: () => cmd('takeoff', { alt: Number(alt.value) || 30 }) }] });
  };
  const onCrash = info => {
    const kind = { terrain: 'Arazi ile temas', water: 'Suya düşüş', building: 'Binaya çarpma' }[info.kind] || 'Çarpışma';
    crash.hidden = false;
    crash.querySelector('.fs-crash-sub').textContent = tr('{k} · {v} m/s · "Sıfırla" ile yeniden başlayın', { k: tr(kind), v: f1(info.speed) });
    addEvent(tr('ÇARPIŞMA: {k} ({v} m/s)', { k: tr(kind), v: f1(info.speed) }), 'error');
    if (canWrite) be.cmd(sid, 'crash', { kind: info.kind, speed: info.speed }).catch(() => {});
  };
  const reset = async () => {
    crash.hidden = true;
    sim?.clearCollision();
    sim?.resetCamera();
    if (canWrite) await cmd('reset'); else toast('Sıfırlamak için yazma izni gerekir', 'err');
  };
  const endSession = async () => {
    if (!canWrite) { location.hash = be.href(); return; }
    if (!await confirmDialog('Oturumu bitir', 'Simülatör oturumu kapatılsın mı? SITL süreci ve UDP portu kapanır; Mission Planner bağlantısı düşer.', { okLabel: 'Bitir', danger: true })) return;
    try { await be.end(sid); toast('Oturum kapatıldı'); location.hash = be.href(); } catch (err) { toastError(err); }
  };
  const showEnded = reason => {
    clear(ended, h('div', { class: 'fs-ended-box' }, h('b', null, 'Oturum sona erdi'), h('div', { class: 'small muted' }, reason || ''),
      h('a', { class: 'btn primary', href: be.href() }, 'Simülatör ana sayfası')));
    ended.hidden = false;
  };

  // ---------- telemetri bağlantısı (WS ya da mock) ----------
  socket = be.socket(sid, {
    status: setWs,
    fatal: why => { setWs('closed'); showEnded(why === 'auth' ? tr('Bu oturumu izleme yetkiniz yok.') : why === 'notfound' ? tr('Oturum sunucuda yok (kapanmış olabilir).') : why); },
    message: m => {
      if (destroyed) return;
      if (m.t === 'tele') return updateHud(m);
      if (m.t === 'hello') { if (m.session) { Object.assign(session, m.session); setState(session.state); setGcs(!!session.gcs?.connected, session.gcs?.addr); } return; }
      if (m.t === 'event') return addEvent(m.text, m.severity);
      if (m.t === 'state') return setState(m.state);
      if (m.t === 'end') { setState('KAPANDI'); showEnded(m.reason); socket?.close(); }
    },
  });

  onLeave(() => {
    destroyed = true;
    clearInterval(gimbalTick);
    socket?.close();
    sim?.dispose();
    view.classList.remove('ops-view');
    scroller?.classList.remove('ops-scroll');
    document.body.classList.remove('immersive');
  });
}

// ======================================================================
// MOCK: arka uç yokken yerel kinematik üretici (WS yerine). Oturumlar bellekte (sekme ömrü). Komutlar üreticiye uygulanır.
// ======================================================================
const MOCK = { sessions: new Map(), seq: 0 };
const SAMPLE_CENTERS = [
  { id: 1, name: 'Örnek Merkez · Akyurt', lat: 40.1305, lon: 33.0876, alt: 1050, location_name: 'Ankara' },
  { id: 2, name: 'Örnek Merkez · Kıyı', lat: 36.8841, lon: 30.7056, alt: 30, location_name: 'Antalya' },
];
function mockBackend(ctx) {
  let centersP = null;
  const centers = () => (centersP ??= api.get('/api/drone/centers').then(r => (Array.isArray(r) && r.length ? r.map(c => ({ id: c.id, name: c.name, lat: c.lat, lon: c.lon, alt: c.alt ?? 0, location_name: c.location_name })) : SAMPLE_CENTERS)).catch(() => SAMPLE_CENTERS));
  const mk = async (type, centerId, world) => {
    const cs = await centers();
    const center = cs.find(c => String(c.id) === String(centerId)) || cs[0];
    const id = `mock-${++MOCK.seq}`;
    const s = { id, type, center, world: { ...WORLD_DEFAULTS, ...(world || {}) }, state: 'HAZIR', udp_port: 14550 + MOCK.seq - 1, host: location.hostname,
      created_at: new Date().toISOString(), owner: { id: ctx.user?.id, name: ctx.user?.full_name || ctx.user?.username || '—' }, gcs: { connected: false, addr: null, since: null }, sitl: { pid: 0, port: 0, error: null } };
    s.flight = new MockFlight(s);
    MOCK.sessions.set(id, s);
    return s;
  };
  const pub = s => { const { flight, ...rest } = s; return rest; };
  return {
    mock: true,
    meta: async () => ({ types: TYPES.map(([key, name]) => ({ key, name, binary: isPlane(key) ? 'arduplane' : 'arducopter' })), centers: await centers(), world_defaults: WORLD_DEFAULTS, limits: { max_sessions: 2, max_minutes: 120 }, host: location.hostname }),
    sessions: async () => [...MOCK.sessions.values()].filter(s => s.state !== 'KAPANDI').map(pub),
    session: async id => {
      if (!MOCK.sessions.has(id)) {   // sayfa yenilendi: aynı kimlikle varsayılan bir sahte oturum kur
        const n = Number(String(id).replace('mock-', '')) || 1; MOCK.seq = Math.max(MOCK.seq, n);
        const s = await mk('multirotor', null, {}); MOCK.sessions.delete(s.id); s.id = id; MOCK.sessions.set(id, s);
      }
      return pub(MOCK.sessions.get(id));
    },
    create: async body => { if ([...MOCK.sessions.values()].filter(s => s.state !== 'KAPANDI').length >= 2) throw Object.assign(new Error('Oturum sınırı'), { status: 409 }); return pub(await mk(body.type, body.center_id, body.world)); },
    end: async id => { const s = MOCK.sessions.get(id); if (s) { s.state = 'KAPANDI'; s.flight.end('Kullanıcı bitirdi'); MOCK.sessions.delete(id); } return { ok: true }; },
    cmd: async (id, name, params) => { const s = MOCK.sessions.get(id); if (!s) throw Object.assign(new Error('Oturum yok'), { status: 404 }); s.flight.cmd(name, params || {}); return { ok: true }; },
    socket: (id, handlers) => { const s = MOCK.sessions.get(id); if (!s) { handlers.fatal?.('notfound'); return { send() {}, close() {} }; } return s.flight.attach(handlers, pub(s)); },
    href: id => `#/drone/sim${id ? `/${id}` : ''}?mock=1`,
  };
}

// Basit kinematik uçuş: yerde bekle → arm → kalkış → merkez etrafında daire (uçak: pistten hızlanıp tırmanır; kopter dikey kalkar).
// 20 Hz `tele` paketi sözleşme §3 alanlarıyla; STATUSTEXT benzeri olaylar; komutlar: arm/disarm/mode/takeoff/rtl/reset/crash/set_home/rc.
class MockFlight {
  constructor(session) {
    this.s = session; this.plane = isPlane(session.type); this.handlers = new Set(); this.timer = 0; this.reset();
  }
  reset() {
    const w = this.s.world;
    this.st = { t: 0, phase: 'ground', x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0, yaw: (Number(w.runway_heading) || 0) * Math.PI / 180, roll: 0, pitch: 0,
      mode: this.plane ? 'MANUAL' : 'STABILIZE', armed: false, thr: 0, batt_v: 16.8, batt_pct: 100, ang: 0, targetAlt: this.plane ? 150 : 30, auto: true, gcsAt: 10 };
  }
  attach(handlers, pubSession) {
    this.handlers.add(handlers);
    handlers.status?.('open');
    handlers.message?.({ t: 'hello', session: pubSession });
    // Gerçek zamana göre adım: yavaş çizimde (yazılım WebGL) zamanlayıcı seyrekleşse de uçuş gerçek hızda ilerler (en çok 0.25 sn/adım)
    if (!this.timer) { this.lastTick = performance.now(); this.timer = setInterval(() => { const now = performance.now(); const dt = Math.min(0.25, (now - this.lastTick) / 1000); this.lastTick = now; this.step(dt); }, 50); }
    return { send: obj => { if (obj?.t === 'cmd') this.cmd(obj.name, obj.params || {}); if (obj?.t === 'rc') this.rc = obj.ch; }, close: () => { this.handlers.delete(handlers); if (!this.handlers.size) { clearInterval(this.timer); this.timer = 0; } } };
  }
  emit(m) { this.handlers.forEach(hh => hh.message?.(m)); }
  event(text, severity = 'info') { this.emit({ t: 'event', text, severity }); }
  end(reason) { this.emit({ t: 'end', reason }); clearInterval(this.timer); this.timer = 0; }
  cmd(name, p) {
    const S = this.st;
    if (name === 'arm') { S.armed = true; S.auto = false; this.event('Arming motors'); }
    else if (name === 'disarm') { S.armed = false; S.auto = false; S.phase = 'ground'; this.event('Disarming motors'); }
    else if (name === 'mode') { S.mode = p.mode || S.mode; S.auto = false; this.event(`Mode ${S.mode}`); if (S.mode === 'RTL') S.phase = 'rtl'; if (S.mode === 'LAND' || S.mode === 'QLAND') S.phase = 'land'; if ((S.mode === 'AUTO' || S.mode === 'LOITER') && S.armed && S.z > 2) S.phase = 'cruise'; }
    else if (name === 'takeoff') { S.targetAlt = Number(p.alt) || S.targetAlt; S.auto = false; if (!S.armed) { S.armed = true; this.event('Arming motors'); } S.mode = this.plane ? 'TAKEOFF' : 'GUIDED'; S.phase = 'takeoff'; this.event(`Takeoff to ${S.targetAlt} m`); }
    else if (name === 'rtl') { S.mode = 'RTL'; S.phase = 'rtl'; S.auto = false; this.event('Mode RTL'); }
    else if (name === 'reset') { this.reset(); this.emit({ t: 'state', state: 'BASLIYOR' }); this.event('SITL yeniden başlatıldı', 'warning'); setTimeout(() => this.emit({ t: 'state', state: 'HAZIR' }), 800); }
    else if (name === 'crash') { S.armed = false; S.phase = 'crashed'; S.auto = false; S.thr = 0; S.vx = S.vy = S.vz = 0; this.event('Crash: Disarming', 'critical'); }
    else if (name === 'set_home') this.event('Home set');
  }
  step(dt) {
    const S = this.st, w = this.s.world, g = 9.81;
    S.t += dt;
    if (S.t > S.gcsAt && !this.s.gcs.connected) { this.s.gcs.connected = true; this.s.gcs.addr = '192.0.2.10:14550'; this.event('GCS bağlandı (192.0.2.10)'); }
    // Otomatik senaryo (komut gelmediyse): 4 sn sonra arm + kalkış
    if (S.auto && S.phase === 'ground' && S.t > 4) { S.armed = true; S.phase = 'takeoff'; S.mode = this.plane ? 'TAKEOFF' : 'GUIDED'; this.event('Arming motors'); this.event(`Takeoff to ${S.targetAlt} m`); }
    const V = this.plane ? 22 : 8, R = this.plane ? 450 : 150;
    const hdg = S.yaw;   // yaw: kuzeyden saat yönü
    if (S.phase === 'takeoff' && S.armed) {
      if (this.plane) {
        const sp = Math.hypot(S.vx, S.vy);
        const ns = Math.min(V, sp + 4 * dt);
        S.vx = Math.sin(hdg) * ns; S.vy = Math.cos(hdg) * ns;
        S.vz = sp > 15 ? 7 : 0; S.pitch = sp > 15 ? 16 * Math.PI / 180 : 0; S.thr = sp > 15 ? 85 : 100;   // dik tırmanış: merkez çevresindeki düzlük (300 m) bitmeden irtifa alsın
      } else { S.vx = S.vy = 0; S.vz = 2.5; S.thr = 65; S.pitch = 0; }
      if (S.z >= S.targetAlt) { S.phase = 'cruise'; S.mode = this.plane ? 'AUTO' : 'LOITER'; S.vz = 0; S.ang = Math.atan2(S.y, S.x); this.event(`Mode ${S.mode}`); this.event('Reached target altitude'); }
    } else if (S.phase === 'cruise' && S.armed) {
      // Merkez etrafında daire: konumu açıyla sür, yaw = hız yönü, roll = koordineli dönüş
      const r0 = Math.hypot(S.x, S.y);
      const r = r0 + (R - r0) * Math.min(1, dt * 0.4);
      S.ang += (V / r) * dt;
      const nx = Math.cos(S.ang) * r, ny = Math.sin(S.ang) * r;
      S.vx = (nx - S.x) / dt; S.vy = (ny - S.y) / dt; S.x = nx; S.y = ny;
      const za = S.targetAlt + (this.plane ? 10 : 3) * Math.sin(S.t * 0.25);
      S.vz = (za - S.z) * 0.5;
      S.yaw = Math.atan2(S.vx, S.vy);
      S.roll = this.plane ? Math.atan((V * V) / (r * g)) : 0.08 * Math.sin(S.t * 0.7);
      S.pitch = (this.plane ? 2 : 0) * Math.PI / 180 + S.vz * 0.02;
      S.thr = this.plane ? 55 : 48;
      S.x -= S.vx * dt; S.y -= S.vy * dt;   // aşağıda ortak entegrasyon ekler
    } else if ((S.phase === 'rtl' || S.phase === 'land') && S.armed) {
      const d = Math.hypot(S.x, S.y);
      if (S.phase === 'rtl' && d > 3) { const sp = Math.min(V, d); S.vx = -S.x / d * sp; S.vy = -S.y / d * sp; S.vz = 0; S.yaw = Math.atan2(S.vx, S.vy); S.roll = 0; S.pitch = 0; S.thr = 50; }
      else { S.vx = S.vy = 0; S.vz = -Math.min(1.5, Math.max(0.3, S.z * 0.3)); S.roll = S.pitch = 0; S.thr = 30; if (S.phase === 'rtl') { S.phase = 'land'; S.mode = this.plane ? 'QLAND' : 'LAND'; this.event('Landing'); } }
      if (S.z <= 0.05 && S.phase === 'land') { S.z = 0; S.vz = 0; S.armed = false; S.phase = 'ground'; S.thr = 0; S.mode = this.plane ? 'MANUAL' : 'STABILIZE'; this.event('Disarming motors'); }
    } else if (!S.armed) { S.vx = S.vy = S.vz = 0; S.thr = 0; S.roll = 0; if (S.phase !== 'crashed') S.pitch = 0; }
    S.x += S.vx * dt; S.y += S.vy * dt; S.z = Math.max(0, S.z + S.vz * dt);
    if (S.armed) { S.batt_pct = Math.max(0, S.batt_pct - dt * 0.02 * (1 + S.thr / 100)); S.batt_v = 14.2 + 2.6 * S.batt_pct / 100; }
    const c = this.s.center, lat = c.lat + S.y / 110574, lon = c.lon + S.x / (111320 * Math.cos(c.lat * Math.PI / 180));
    const gs = Math.hypot(S.vx, S.vy), windDir = (Number(w.wind_dir) || 0) * Math.PI / 180, wind = Number(w.wind_ms) || 0;
    const air = Math.max(0, gs + wind * Math.cos(S.yaw - windDir));   // rüzgâr "nereden": burun rüzgâra dönükse hava hızı artar
    const rc = this.rc || [1500 + 500 * Math.sin(S.roll * 2), 1500 - 500 * Math.sin(S.pitch * 2), 1000 + S.thr * 10, 1500, 1800, 1000, 1000, 1500].map(v => Math.round(Math.max(1000, Math.min(2000, v))));
    this.emit({ t: 'tele', ts: Date.now(), lat, lon, alt_msl: (Number(c.alt) || 0) + S.z, alt_rel: S.z, roll: S.roll, pitch: S.pitch, yaw: S.yaw, vn: S.vy, ve: S.vx, vd: -S.vz,
      airspeed: air, groundspeed: gs, heading: ((S.yaw * 180 / Math.PI) + 360) % 360, climb: S.vz, mode: S.mode, armed: S.armed, gps_fix: 3, sats: 14,
      batt_v: S.batt_v, batt_pct: S.batt_pct, throttle: S.thr, rc, home: { lat: c.lat, lon: c.lon, alt: c.alt }, gcs_connected: this.s.gcs.connected, gcs_addr: this.s.gcs.addr });
  }
}
