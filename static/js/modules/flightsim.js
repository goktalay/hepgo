// Uçuş Simülatörü — Dron Yönetimi › Uçuş Simülatörü sekmesi (#/drone/sim[/<oturum>]). Sözleşme: docs/ucus-simulatoru.md.
// drone.js `sim` sayfasında dinamik yükler: import('./flightsim.js').then(mod => mod.render(view, params, ctx, { m, head, mock }))
// • Sihirbaz (§6): dron tipi kartları → merkez seçimi (/api/drone/sim/meta centers) → dünya kaydırıcıları + "Rastgele tohum" + küçük 3B
//   önizleme → Başlat (POST /api/drone/sim/sessions). Açık oturum varsa üstte liste: devam et / bitir.
// • Oturum ekranı: tam alan 3B tuval (flightsim3d.js) + YERLİ harekât paneli (§14, flightsim_panel.js: GÖKTUNGU dron kartı görünümünde TEK kart
//   sağ üstte — başlık şeridi / PFD / telemetri karoları / İŞLEMLER / Haberleşme konsolu; hub soketi ve komutlar panelde; Panel düğmesi / P
//   gizleyince sade görünüm: eski HUD (sağ) + alt çubuk ARM/mod/Kalkış/RTL + olay şeridi), Mission Planner bağlantı kutusu (sol alt), alt araç
//   çubuğu, ÇARPIŞMA bandı. Tam ekran (⛶) BELGEYE uygulanır (document.documentElement): body'ye eklenen pencereler/bildirimler tam ekranda görünür.
// • WS istemcisi /ws/drone/sim/{id}: hello/tele/event/state/end; ping 10 sn; üstel geri çekilmeli yeniden bağlanma; 4403/4404 kalıcı.
// • Sanal kumanda (yazma izni; alt çubuk 🎮): iki sanal çubuk + klavye → 20 Hz {t:'rc', ch[8]} (RC_CHANNELS_OVERRIDE); kapatınca 8×0.
//   Açıkken 3B klavye kilidi (WASD/ok tuşları kumandaya gider). HUD altında ağ göstergesi: 'net: 48 Hz · jitter 3 ms' (sim.netStats()).
// • `?mock=1`: arka uç yokken yerel kinematik üretici (WS yerine) — sihirbaz, 3B dünya ve HUD arka uçsuz denenir. Mock oturumlar yalnız
//   bu sekmede (bellekte) yaşar; komutlar (arm/disarm/mode/takeoff/rtl/reset/crash) üreticiye uygulanır.
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, fmtDuration, h, modal, onLeave, segmented, toast, toastError, t as tr } from '../ui.js';
import { ATTRIBUTION, CAMERA_MODES, WORLD_DEFAULTS, createFlightSim3D } from './flightsim3d.js';
import { createMilHud } from './flightsim_hud.js';   // askeri tarz FPV HUD (Dron kamerası kipi; H aç/kapa)
import { G3D_LOGO } from './flightsim_g3d.js';   // Google 3B kipi (§11): logo yolu; kütüphane yalnız kip seçilince dinamik yüklenir
import { modelPicker } from './flightsim_models.js';   // görsel model kütüphanesi (§12): kart ızgarası, yükleme, tarayıcıda STEP→GLB, yönelim paneli
import { clientsCard } from './flightsim_clients.js';   // CAYSIM masaüstü istemcileri kartı (docs/caysim-api.md §9): kod bir kez gösterilir, rekey, sil
import { LAUNCH_DEFAULTS, LAUNCH_METHODS, launchLabel, rampExitSpeed } from './flightsim_launch.js';   // sabit kanat kalkış yöntemi (§13)
import { createEngineAudio } from './flightsim_audio.js';   // §16: tipe göre sentezlenmiş motor sesi (Web Audio); 🔊 düğmesi + M tuşu alt çubukta
import { createOpsPanel } from './flightsim_panel.js';   // §14: YERLİ harekât paneli (iframe yok) — kartlar 3B'nin üstünde yüzer; hub soketi + komutlar panelde

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
// Görsel model (§12): oturuma {id, orient} gönderilir (dahili için yalnız id); sahte kipte tam nesne (blob GLB adresi aynı sekmede geçerli)
const modelBody = (m, mock) => (m ? (mock ? { ...m } : { id: m.id, orient: String(m.id).startsWith('builtin:') ? undefined : m.orient }) : undefined);
const modesFor = type => (type === 'vtol' ? VTOL_MODES : isPlane(type) ? PLANE_MODES : COPTER_MODES);
const f1 = v => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(1));
const f0 = v => (v == null || Number.isNaN(Number(v)) ? '—' : String(Math.round(Number(v))));
const clock = sec => { sec = Math.max(0, Math.floor(Number(sec) || 0)); const hh = Math.floor(sec / 3600), mm = Math.floor(sec % 3600 / 60), ss = sec % 60; return `${hh ? `${hh}:` : ''}${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`; };
const copy = async (txt, what = 'Kopyalandı') => { try { await navigator.clipboard.writeText(txt); toast(what); } catch { toast('Kopyalanamadı; metni elle seçin', 'err'); } };
const svgIco = body => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const TYPE_ICON = {
  quad: svgIco('<rect x="9.5" y="9.5" width="5" height="5" rx="1.2"/><path d="M9.5 9.5 6.6 6.6M14.5 9.5l2.9-2.9M9.5 14.5l-2.9 2.9M14.5 14.5l2.9 2.9"/><circle cx="5.2" cy="5.2" r="2.6"/><circle cx="18.8" cy="5.2" r="2.6"/><circle cx="5.2" cy="18.8" r="2.6"/><circle cx="18.8" cy="18.8" r="2.6"/>'),
  hexa: svgIco('<circle cx="12" cy="12" r="2.4"/><path d="M12 9.6V5.5M12 14.4v4.1M9.9 10.8 6.3 8.7M14.1 10.8l3.6-2.1M9.9 13.2l-3.6 2.1M14.1 13.2l3.6 2.1"/><circle cx="12" cy="4" r="1.6"/><circle cx="12" cy="20" r="1.6"/><circle cx="5" cy="8" r="1.6"/><circle cx="19" cy="8" r="1.6"/><circle cx="5" cy="16" r="1.6"/><circle cx="19" cy="16" r="1.6"/>'),
  heli: svgIco('<path d="M3 7h18M12 7v3"/><ellipse cx="11" cy="13" rx="4.5" ry="3"/><path d="M15.5 13h5l-2 2.5M20.5 13v-3M7 18h8"/>'),
  plane: svgIco('<path d="M12 3v18M4 13l8-3 8 3M8 20l4-2 4 2M12 3c1.5 0 2 2 2 4v3M12 3c-1.5 0-2 2-2 4v3"/>'),
  vtol: svgIco('<path d="M12 4v16M5 12l7-2 7 2M9 20l3-1.5 3 1.5"/><circle cx="6" cy="7" r="2"/><circle cx="18" cy="7" r="2"/><circle cx="6" cy="17" r="2"/><circle cx="18" cy="17" r="2"/>'),
};
// Kalkış yöntemi simgeleri (§13): tekerlekli (uçak + tekerlekler), rampa (eğik ray + kızak), araç üstü (pickup + uçak)
const LAUNCH_ICON = {
  wheels: svgIco('<path d="M3 11h18l-3-3H8l-5 3Z"/><path d="M12 8V5h4"/><path d="M7 11v4M16 11v4"/><circle cx="7" cy="17" r="2"/><circle cx="16" cy="17" r="2"/><path d="M3 21h18"/>'),
  ramp: svgIco('<path d="M3 19 19 7"/><path d="M5 19h14"/><path d="M8 19v-3.5M13 19v-7"/><rect x="12" y="7" width="5" height="3" rx=".6" transform="rotate(-37 14.5 8.5)"/><circle cx="6" cy="21" r="1.4"/><circle cx="17" cy="21" r="1.4"/>'),
  vehicle: svgIco('<path d="M2 16h20v-4h-6l-2-3H9v3H2Z"/><circle cx="6.5" cy="18.5" r="2"/><circle cx="17.5" cy="18.5" r="2"/><path d="M8 9h11l-3-2.2H11L8 9Z"/><path d="M13.5 6.8V5"/>'),
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
  if (sid) return renderSession(view, ctx, backend, sid, { mock, canWrite, netsim: parseNetsim(sp.get('netsim')) });
  return renderWizard(view, ctx, backend, head, { mock, canWrite });
}

// Ağ bozulması test kipi (§5 titreme teşhisi): #/drone/sim/<id>?netsim=jitter30,loss5,delay40 — gelen her `tele` karesi delay + U(0, 2·jitter) ms
// gecikmeyle (sıra bozulabilir) iletilir, %loss'u düşürülür. Yalnız bu parametreyle açılır; ayrıca window.__fsSim (3B nesnesi: netStats/motionStats) verilir.
function parseNetsim(s) {
  if (!s) return null;
  const o = { jitter: 0, loss: 0, delay: 0 };
  for (const part of String(s).split(',')) { const m = /^(jitter|loss|delay)(\d+(?:\.\d+)?)$/.exec(part.trim()); if (m) o[m[1]] = Number(m[2]); }
  return o;
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
    logs: q => api.get(`${API}/logs${q ? `?q=${encodeURIComponent(q)}` : ''}`),
    replay: id => api.get(`${API}/sessions/${encodeURIComponent(id)}/replay`),
    end: id => api.del(`${API}/sessions/${encodeURIComponent(id)}`),
    cmd: (id, name, params = {}) => api.post(`${API}/sessions/${encodeURIComponent(id)}/cmd`, { name, params }),
    g3dKey: () => api.get(`${API}/g3d-key`).then(r => r.key),   // Google Map Tiles anahtarı (no-store; yalnız dünya kurulurken)
    drones: () => api.get(`${API}/drones`),   // §14: sihirbaz "Dron kaydı (isteğe bağlı)" — Dron Envanteri
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
  const logsAllowed = meta.replay ? meta.replay.logs_allowed !== false : true;
  const S = { mode: 'sitl', type: types[0]?.key || 'multirotor', center: centers[0]?.id ?? null, log: null, logs: null, q: '', drone: null,
    world: { ...defaults, seed: randomSeed(), launch: { ...LAUNCH_DEFAULTS, ...(defaults.launch || {}) } } };
  // Etkin dron tipi: canlı kipte seçilen kart, kayıt kipinde seçili logun araç tipi (model kütüphanesi bu tipe göre listelenir)
  const activeType = () => (S.mode === 'replay' ? ((S.logs || []).find(x => x.id === S.log)?.type || 'multirotor') : S.type);

  // ---------- açık oturumlar ----------
  const openBox = h('div');
  const drawOpen = async () => {
    let rows = [];
    try { rows = await be.sessions(); } catch { rows = []; }
    if (!rows.length) { clear(openBox); return; }
    clear(openBox, h('div', { class: 'card card-pad fs-open no-collapse' }, h('h3', null, tr('Açık oturumlar ({n})', { n: rows.length })),
      h('div', { class: 'fs-open-list' }, rows.map(s => h('div', { class: 'fs-open-row' },
        h('div', { class: 'fs-open-main' }, h('b', null, TYPE_NAME[s.type] || s.type), s.mode === 'replay' ? h('span', { class: 'badge purple' }, 'Kayıt') : null,
          s.client ? h('span', { class: 'badge blue', title: tr('CAYSIM istemcisi açtı: {name}', { name: s.client.name }) }, 'CAYSIM') : null,
          h('span', { class: `badge ${STATE_BADGE[s.state] || 'gray'}` }, STATE_TEXT[s.state] || s.state),
          h('div', { class: 'small muted' }, [s.mode === 'replay' ? s.replay?.file_name : s.center?.name, s.owner?.name, s.created_at ? fmtDateTime(s.created_at) : null, s.udp_port ? `UDP ${s.udp_port}` : null].filter(Boolean).join(' · '))),
        h('div', { class: 'pill-group' },
          h('a', { class: 'btn sm primary', href: be.href(s.id) }, 'Devam et'),
          canWrite ? h('button', { class: 'btn sm danger', onclick: async () => {
            if (!await confirmDialog('Oturumu bitir', s.mode === 'replay' ? 'Kayıttan oynatma oturumu kapatılsın mı?' : 'Simülatör oturumu kapatılsın mı? SITL süreci ve UDP portu kapanır.', { okLabel: 'Bitir', danger: true })) return;
            await be.end(s.id); toast('Oturum kapatıldı'); drawOpen();
          } }, 'Bitir') : null))))));
  };

  // ---------- 1. dron tipi ----------
  const typeCards = h('div', { class: 'fs-types' });
  // Görsel model kütüphanesi (§12): tip kartının altında kart ızgarası (dahili + tasarım + yüklenen), seçim önizlemeye uygulanır
  const picker = modelPicker({ getType: activeType, canWrite, mock, getSim: () => preview, onSelect: m => preview?.setType(activeType(), m) });
  const modelBox = h('div', { class: 'fs-model-step' }, h('p', { class: 'small muted' }, 'Dron tipi için görsel gövde: dahili modeller her zaman vardır; sistemdeki STEP/GLB/OBJ dosyaları ya da yüklediğiniz model seçilince tarayıcıda GLB\'ye dönüştürülür.'), picker.el);
  const refreshModels = () => picker.refresh(activeType()).then(m => { if (m) preview?.setType(activeType(), m); });
  const drawTypes = () => clear(typeCards, types.map(t => h('button', { type: 'button', class: `fs-type ${S.type === t.key ? 'on' : ''}`, onclick: () => { S.type = t.key; drawTypes(); drawLaunch(); refreshModels(); } },
    h('span', { class: 'fs-type-ico', html: TYPE_ICON[t.icon] || TYPE_ICON.quad }),
    h('b', null, t.name), h('span', { class: 'small muted' }, t.desc || ''))));
  drawTypes();

  // ---------- 1L. kalkış yöntemi (§13; yalnız Sabit Kanat): tekerlekli · fırlatma rampası (açı) · araç üstü (bırakma hızı) ----------
  const L = S.world.launch;
  const launchCards = h('div', { class: 'fs-launches' });
  const launchInfo = h('div', { class: 'small muted fs-launch-info' });
  const applyLaunch = () => { preview?.setLaunch({ ...L }); };
  const angleOut = h('b', { class: 'fs-val' }, `${Math.round(L.angle_deg)}°`);
  const angleInp = h('input', { type: 'range', min: 10, max: 30, step: 1, value: L.angle_deg, oninput: () => { L.angle_deg = Number(angleInp.value); angleOut.textContent = `${L.angle_deg}°`; drawLaunchInfo(); applyLaunch(); } });
  const relOut = h('b', { class: 'fs-val' }, `${Math.round(L.release_kmh)} km/h`);
  const relInp = h('input', { type: 'range', min: 40, max: 110, step: 5, value: L.release_kmh, oninput: () => { L.release_kmh = Number(relInp.value); relOut.textContent = `${L.release_kmh} km/h`; drawLaunchInfo(); applyLaunch(); } });
  const angleRow = h('label', { class: 'fs-slider fs-launch-param' }, h('span', null, h('span', null, 'Fırlatma açısı'), angleOut), angleInp);
  const relRow = h('label', { class: 'fs-slider fs-launch-param' }, h('span', null, h('span', null, 'Bırakma hızı'), relOut), relInp);
  const vehicleRow = h('div', { class: 'small muted fs-launch-param' }, tr('Araç tipi: pickup (kasa kızağı). Araç pist boyunca hızlanır; bırakma hızına ulaşınca uçak serbest kalır ve tırmanır.'));
  const drawLaunchInfo = () => {
    const v = rampExitSpeed();
    launchInfo.textContent = L.method === 'ramp' ? tr('Pnömatik rampa: 6 m ray, 0,5 sn kızak → çıkış hızı ≈ {v} m/s ({k} km/h); açı {a}°. SITL: plane-catapult modeli, servo 7 tetiği; TKOFF_THR_MINACC 8 m/s².', { v: v.toFixed(0), k: Math.round(v * 3.6), a: Math.round(L.angle_deg) })
      : L.method === 'vehicle' ? tr('Araç üstü: uçak {k} km/h ({v} m/s) yer hızında bırakılır (TKOFF_ROTATE_SPD = bırakma hızı); araç frenleyip durur.', { k: Math.round(L.release_kmh), v: (L.release_kmh / 3.6).toFixed(1) })
      : tr('Tekerlekli: iniş takımı eklenir; uçak pist boyunca hızlanır, 12 m/s döndürme hızında burun kalkar (ArduPlane TAKEOFF).');
  };
  const drawLaunch = () => {
    launchBox.hidden = !(S.mode === 'sitl' && S.type === 'sabit_kanat');
    clear(launchCards, LAUNCH_METHODS.map(([key, name, desc]) => h('button', { type: 'button', class: `fs-type fs-launch ${L.method === key ? 'on' : ''}`, 'data-launch': key, onclick: () => { L.method = key; drawLaunch(); applyLaunch(); } },
      h('span', { class: 'fs-type-ico', html: LAUNCH_ICON[key] }), h('b', null, name), h('span', { class: 'small muted' }, desc))));
    angleRow.hidden = L.method !== 'ramp'; relRow.hidden = L.method !== 'vehicle'; vehicleRow.hidden = L.method !== 'vehicle';
    drawLaunchInfo();
  };
  const launchBox = h('div', { class: 'fs-launch-step' }, h('h4', null, 'Kalkış yöntemi'),
    h('p', { class: 'small muted' }, 'Sabit kanat uçağın nasıl havalanacağı: tekerlekli pist koşusu, pnömatik fırlatma rampası ya da pickup üstünden bırakma. Seçim 3B sahnede ve SITL kalkış parametrelerinde uygulanır.'),
    launchCards, h('div', { class: 'fs-launch-params' }, angleRow, relRow, vehicleRow), launchInfo);
  drawLaunch();

  // ---------- 2. merkez ----------
  const centerList = h('div', { class: 'fs-centers' });
  const centerOf = () => centers.find(c => c.id === S.center) || null;
  const drawCenters = () => clear(centerList, centers.length ? centers.map(c => h('button', { type: 'button', class: `fs-center ${S.center === c.id ? 'on' : ''}`, onclick: () => { S.center = c.id; drawCenters(); if (preview) { progInfo(null); preview.setOrigin(c.lat, c.lon, S.world, c.alt); } } },
    h('b', null, c.name), h('span', { class: 'small muted' }, [c.location_name, `${Number(c.lat).toFixed(5)}, ${Number(c.lon).toFixed(5)}`, c.alt != null ? `${f0(c.alt)} m` : null].filter(Boolean).join(' · '))))
    : h('div', { class: 'small muted fs-nocenter' }, 'Kayıtlı merkez yok. Önce ', h('a', { href: '#/drone/routes' }, 'Rotalar › Merkezler'), ' bölümünden bir merkez ekleyin.'));
  drawCenters();
  // ---------- 2b. dron kaydı (isteğe bağlı; §14): harekât panelinde telemetri bu dronun koduyla/adıyla akar; yoksa "Simülatör #N" ----------
  const droneSel = h('select', { class: 'input fs-drone-sel', onchange: () => { S.drone = droneSel.value ? Number(droneSel.value) : null; } }, h('option', { value: '' }, 'Yok — "Simülatör #N" sanal dronu'));
  const droneBox = h('div', { class: 'fs-drone-step' },
    h('p', { class: 'small muted' }, 'Dron Envanteri\'nden bir kayıt seçilirse harekât panelinde dron o adla görünür; seçilmezse oturuma özel "Simülatör #N" sanal dronu kullanılır. Simülatör her durumda SITL\'dir; kayıt yalnız kimliktir.'),
    h('label', { class: 'fs-drone-row' }, h('span', { class: 'small muted' }, 'Dron kaydı'), droneSel));
  (be.drones ? be.drones() : Promise.resolve([])).then(rows => { (rows || []).forEach(d => droneSel.append(h('option', { value: d.id }, `${d.code || ''} · ${d.name || ''}${d.model ? ` (${d.model})` : ''}`))); }).catch(() => {});

  // ---------- 1R. kayıttan oynat: uçuş logu listesi (ad, tarih, dron, süre, boyut; arama) ----------
  const logList = h('div', { class: 'fs-logs' });
  const logInfo = h('div', { class: 'small muted fs-log-info' });
  const fmtSize = b => (b == null ? '—' : b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
  const drawLogs = () => {
    if (S.logs === null) { clear(logList, h('div', { class: 'small muted' }, 'Uçuş logları yükleniyor…')); return; }
    const q = S.q.trim().toLocaleLowerCase('tr');
    const rows = S.logs.filter(l => !q || [l.file_name, l.aircraft, l.pilot, l.location, l.task_code, l.note, l.vehicle].some(v => String(v || '').toLocaleLowerCase('tr').includes(q)));
    if (!rows.length) {
      clear(logList, h('div', { class: 'small muted fs-nocenter' }, S.logs.length ? tr('Aramaya uyan log yok.') : logsAllowed
        ? ['Oynatılabilir uçuş logu yok. Önce ', h('a', { href: '#/tools/flight-logs' }, 'Araçlar › Uçuş Logu Analizi'), ' bölümünden bir .bin / .tlog yükleyin (analizi tamamlanmış loglar listelenir).']
        : 'Uçuş loglarına erişim için Araçlar ya da Saha Yönetimi yetkisi gerekir.'));
      return;
    }
    clear(logList, rows.map(l => h('button', { type: 'button', class: `fs-log ${S.log === l.id ? 'on' : ''}`, onclick: () => { S.log = l.id; drawLogs(); refreshModels(); } },
      h('span', { class: 'fs-log-ico', html: TYPE_ICON[(TYPES.find(x => x[0] === l.type) || [])[3] || 'quad'] }),
      h('span', { class: 'fs-log-main' },
        h('b', null, l.file_name, l.ext ? h('span', { class: 'badge gray fs-log-ext' }, l.ext.toUpperCase()) : null, l.cached ? h('span', { class: 'badge green', title: tr('Kareler önbellekte; hemen açılır') }, '⚡') : null),
        h('span', { class: 'small muted' }, [l.takeoff_utc || l.start_utc ? fmtDateTime(l.takeoff_utc || l.start_utc) : fmtDateTime(l.uploaded_at), l.aircraft, l.pilot, l.location, l.task_code ? tr('Görev {c}', { c: l.task_code }) : null, l.vehicle].filter(Boolean).join(' · '))),
      h('span', { class: 'fs-log-meta small' }, h('b', null, l.flight_s != null ? fmtDuration(l.flight_s) : (l.duration_s != null ? fmtDuration(l.duration_s) : '—')), h('span', { class: 'muted' }, fmtSize(l.size))))));
  };
  const searchInp = h('input', { class: 'input', placeholder: 'Ara: dosya adı, dron, pilot, konum, görev kodu…', value: S.q, oninput: () => { S.q = searchInp.value; drawLogs(); } });
  const loadLogs = async () => {
    if (!logsAllowed) { S.logs = []; drawLogs(); return; }
    try { S.logs = await be.logs(); } catch (err) { S.logs = []; toastError(err); }
    if (S.log == null && S.logs.length) S.log = S.logs[0].id;
    drawLogs();
  };
  drawLogs();
  const stepLog = h('div', { class: 'card card-pad fs-step no-collapse', hidden: true }, h('h3', null, h('span', { class: 'fs-no' }, '1'), 'Uçuş logu'),
    h('p', { class: 'small muted' }, 'Sisteme yüklenmiş ArduPilot .bin / .log ya da MAVLink .tlog kayıtlarından biri 3B dünyada aynen oynatılır; kontrol sizde değildir. Dünyanın merkezi kaydın kalkış (ilk ARM) noktasıdır.'),
    h('div', { class: 'fs-log-search' }, searchInp, h('button', { class: 'btn sm', type: 'button', onclick: loadLogs }, '↻ Yenile')), logList, logInfo);

  // ---------- 3. dünya ----------
  let preview = null, rebuildT = 0;
  const progBar = h('div', { class: 'fs-preview-prog', hidden: true });
  const g3dLogo = h('img', { class: 'fs-g3d-logo', src: G3D_LOGO, alt: 'Google', hidden: true });   // Google 3B önizlemesinde ToS logosu (sol alt)
  const previewBox = h('div', { class: 'fs-preview' }, h('div', { class: 'fs-preview-msg' }, '3B önizleme hazırlanıyor…'), progBar, g3dLogo);
  const previewInfo = h('div', { class: 'small muted fs-preview-info' });
  // Gerçek kip yükleme ilerlemesi / özet (önizleme kutusu üstünde şerit + altında bilgi satırı)
  const progInfo = p => {
    if (!p) { progBar.hidden = false; progBar.textContent = tr('Arazi planı alınıyor…'); return; }
    if (p.stage === 'done') {
      progBar.hidden = true;
      g3dLogo.hidden = !p.google;
      if (p.real) {
        const c = p.counts || {};
        previewInfo.textContent = `${tr('Gerçek arazi · yükseklik {a}…{b} m · ev {h} m MSL', { a: f0(p.hmin), b: f0(p.hmax), h: f0(p.homeElev) })} · ${tr('{b} bina · {f} orman · {w} su · {r} pist', { b: c.buildings ?? 0, f: c.forests ?? 0, w: c.water ?? 0, r: c.runways ?? 0 })}`;
        const info = preview?.terrainInfo;
        if (info?.osmError) previewInfo.textContent += ` · ${tr('OSM verisi alınamadı: binalar/orman/su gösterilmiyor ({e})', { e: info.osmError })}`;
      } else if (p.google) previewInfo.textContent = `${tr('Google 3B (fotogerçekçi) · ev {h} m MSL', { h: f0(p.homeElev) })} · ${preview?.g3dAttribution?.()?.text || 'Google'}`;
      else if (S.world.mode === 'procedural') previewInfo.textContent = tr('Prosedürel dünya: tohumlu rastgele arazi, binalar ve ağaçlar.');
      // real/google3d seçiliyken prosedürele düşüldüyse onFallback'in yazdığı uyarı kalır
      return;
    }
    if (p.stage === 'g3d') {   // Google karoları: kök tileset + görünür karolar (%); dolunca şerit gizlenir
      progBar.hidden = p.pct >= 100; progBar.textContent = tr('Google 3B karoları yükleniyor… %{p}', { p: p.pct ?? 0 });
      return;
    }
    progBar.hidden = false;
    progBar.textContent = p.stage === 'elev' ? tr('Yükseklik karoları {d}/{n}', { d: p.done, n: p.total }) : p.stage === 'img' ? tr('Uydu karoları {d}/{n}', { d: p.done, n: p.total })
      : p.stage === 'osm' ? tr('Harita verileri (OSM) alınıyor…') : tr('Arazi planı alınıyor…');
  };
  const fallbackText = (mode, e) => (mode === 'google3d' ? tr('Google 3B verisi alınamadı: {e} → prosedürele düşüldü', { e }) : tr('Gerçek veri alınamadı, prosedürele düşüldü: {e}', { e }));
  const onFallback = e => { previewInfo.textContent = fallbackText(S.world.mode, e); toast(previewInfo.textContent, 'err'); };
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
    const real = S.world.mode === 'real', g3 = S.world.mode === 'google3d';
    for (const k of ['mountain_height', 'mountain_count', 'water']) sliders[k].el.hidden = real || g3;
    for (const k of ['tree_density', 'building_count']) sliders[k].el.hidden = g3;   // Google 3B: nesneler karoların içinde; yalnız saat/sis/rüzgâr/pist
    seedBox.hidden = real || g3;
    sliders.tree_density.lbl.textContent = tr(real ? 'Ağaç sıklığı (orman alanlarına ölçek)' : 'Ağaç sıklığı');
    sliders.building_count.lbl.textContent = tr(real ? 'Ek bina sayısı (0 = yalnız gerçek binalar)' : 'Bina sayısı');
    modeHint.textContent = real
      ? `${tr('Gerçek kipte seçili merkezin çevresi gerçek yükseklik, uydu görüntüsü ve OpenStreetMap binalarıyla kurulur; veriler ilk kullanımda indirilip sunucuda önbelleklenir.')} ${ATTRIBUTION}`
      : g3 ? tr('Google 3B kipinde çevre Google Photorealistic 3D Tiles ile fotogerçekçi kurulur (binalar ve ağaçlar karoların içinde); karolar tarayıcıya doğrudan Google’dan gelir, sunucuda önbelleklenmez; atıf zorunludur. Ev irtifası açık yükseklik verisinden alınır.')
      : tr('Prosedürel dünya: tohumlu rastgele arazi, binalar ve ağaçlar.');
  };
  let bcTouched = false, rwTouched = false;
  const g3dOn = !!meta.google3d?.enabled;   // yalnız sunucuda GOOGLE_MAPS_API_KEY tanımlıysa üçüncü seçenek
  if (!g3dOn && S.world.mode === 'google3d') S.world.mode = 'procedural';
  const worldModeSeg = segmented([['real', 'Gerçek arazi'], ...(g3dOn ? [['google3d', 'Google 3B (fotogerçekçi)']] : []), ['procedural', 'Prosedürel']], S.world.mode, v => {
    S.world.mode = v;
    if (!bcTouched) { S.world.building_count = v === 'real' ? 0 : defaults.building_count; sliders.building_count.inp.value = S.world.building_count; sliders.building_count.out.textContent = S.world.building_count; }
    if (!rwTouched) { S.world.runway = v !== 'google3d'; runwayCb.checked = S.world.runway; }   // Google 3B: pist varsayılan kapalı (gerçek yüzeyle çakışmasın)
    applyMode(); schedule();
  });
  runwayCb.addEventListener('change', () => { rwTouched = true; });
  const worldForm = h('div', { class: 'fs-world' },
    h('div', { class: 'fs-mode-row' }, h('span', { class: 'small muted' }, 'Dünya kipi'), worldModeSeg),
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
    if (S.mode === 'replay' && S.log == null) { toast('Önce bir uçuş logu seçin', 'err'); return; }
    if (S.mode === 'sitl' && S.center == null) { toast('Önce bir merkez seçin', 'err'); return; }
    startBtn.disabled = true;
    try {
      const model = modelBody(picker.selectionFor(activeType()), mock);
      const s = S.mode === 'replay'
        ? await be.create({ mode: 'replay', log_id: S.log, world: { ...S.world }, model })
        : await be.create({ mode: 'sitl', type: S.type, center_id: S.center, world: { ...S.world }, model, drone_id: S.drone ?? undefined });
      toast(S.mode === 'replay' ? 'Kayıttan oynatma oturumu açıldı' : 'Simülatör oturumu açıldı');
      location.hash = be.href(s.id);
    } catch (err) {
      const msg = { 400: S.mode === 'replay' ? 'Log açılamadı; analizi tamamlanmış bir .bin/.tlog seçin' : 'Geçersiz ayar; dünya değerlerini ve merkezi kontrol edin', 409: 'Oturum sınırı doldu; açık bir oturumu bitirin', 503: 'SITL hazır değil (ikili ya da boş port yok)' }[err?.status];
      toast(msg || err.message, 'err');
      startBtn.disabled = false;
    }
  } }, '▶ Başlat');
  const limits = meta.limits || {};
  // Kip seçimi: canlı simülasyon (SITL + Mission Planner; kontrol kullanıcıda) · kayıttan oynat (yüklü uçuş logu; kontrol yok)
  const stepType = h('div', { class: 'card card-pad fs-step no-collapse' }, h('h3', null, h('span', { class: 'fs-no' }, '1'), 'Dron tipi'), typeCards, launchBox, modelBox);
  const stepCenter = h('div', { class: 'card card-pad fs-step no-collapse' }, h('h3', null, h('span', { class: 'fs-no' }, '2'), 'Merkez'), h('p', { class: 'small muted' }, 'Sanal dünyanın merkezi ve kalkış noktası. Mission Planner haritası bu koordinatı gösterir.'), centerList,
    h('h4', { class: 'fs-sub-h' }, 'Dron kaydı (isteğe bağlı)'), droneBox);
  const worldNo = h('span', { class: 'fs-no' }, '3');
  const worldHint = h('p', { class: 'small muted', hidden: true }, 'Dünya kaydın kalkış noktası etrafında kurulur (pist seviyesi = kalkış irtifası); çarpışma denetimi kapalıdır. Prosedürel kipte arazi gerçek araziyle örtüşmez; gerçek kipte kalkış noktasının çevresi gerçek yükseklik ve uydu görüntüsüyle kurulur.');
  const stepWorld = h('div', { class: 'card card-pad fs-step no-collapse' }, h('h3', null, worldNo, 'Dünya'), worldHint, h('div', { class: 'fs-world-wrap' }, worldForm, h('div', null, previewBox, previewInfo)));
  const startNote = h('div', { class: 'small muted' });
  const drawMode = () => {
    const rp = S.mode === 'replay';
    stepType.hidden = rp; stepCenter.hidden = rp; stepLog.hidden = !rp; worldHint.hidden = !rp;
    worldNo.textContent = rp ? '2' : '3';
    startBtn.disabled = !canWrite || (rp ? !logsAllowed : !centers.length);
    startBtn.textContent = tr(rp ? '▶ Oynat' : '▶ Başlat');
    clear(startNote, canWrite
      ? (rp ? tr('Kayıt sunucuda bir kez ayrıştırılır ve önbelleğe alınır; SITL ve Mission Planner köprüsü açılmaz.') : tr('En çok {n} eşzamanlı oturum · oturum süresi {m} dk', { n: limits.max_sessions ?? '—', m: limits.max_minutes ?? '—' }))
      : 'Oturum açmak için Dron Yönetimi yazma izni gerekir; açık oturumları izleyebilirsiniz.');
    (rp ? stepLog : stepType).append(modelBox);   // model bölümü: canlı kipte tip kartlarının, kayıt kipinde log listesinin altında
    drawLaunch();
    if (rp && S.logs === null) loadLogs().then(refreshModels); else refreshModels();
  };
  const modeSeg = segmented([['sitl', 'Canlı simülasyon (SITL + Mission Planner)'], ['replay', 'Kayıttan oynat']], S.mode, v => { S.mode = v; drawMode(); });
  clear(view, head(mock ? 'Uçuş Simülatörü · sahte veri kipi (arka uç yok)' : 'Uçuş Simülatörü · SITL + Mission Planner köprüsü, 3B dünya'),
    mock ? h('div', { class: 'alert warn fs-mock-note' }, 'Sahte veri kipi: oturum sunucuda açılmaz; telemetri tarayıcıda üretilir. Gerçek kullanım için adresten ?mock=1 kaldırın.') : null,
    openBox,
    mock ? null : clientsCard({ canWrite }).el,   // CAYSIM istemcileri (docs/caysim-api.md)
    h('div', { class: 'fs-mode-row' }, h('span', { class: 'small muted' }, 'Kip'), modeSeg),
    stepType, stepCenter, stepLog, stepWorld,
    h('div', { class: 'fs-start-row' }, startNote, startBtn));
  drawMode();
  drawOpen();

  // 3B önizleme (küçük, kendi etrafında dönen kamera); sayfa değişince serbest bırakılır
  try {
    if (S.world.mode === 'real') progInfo(null);
    const c0 = centerOf();
    preview = await createFlightSim3D(previewBox, S.world, { preview: true, type: activeType(), model: picker.selectionFor(activeType()) || undefined, origin: c0 ? { lat: c0.lat, lon: c0.lon, alt: c0.alt } : undefined, onProgress: progInfo, onFallback, g3dKey: be.g3dKey, launch: { ...L } });
    previewBox.querySelector('.fs-preview-msg')?.remove();
    const sel = picker.selectionFor(activeType()); if (sel) { preview.setType(activeType(), sel).then(() => picker.drawInfo()); picker.redraw(); }
    picker.ensureThumbs();   // 3B sahne hazır: eksik küçük resimler artık üretilebilir (snapshotModel)
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
async function renderSession(view, ctx, be, sid, { mock, canWrite, netsim = null }) {
  let session;
  try { session = await be.session(sid); } catch (err) {
    clear(view, h('div', { class: 'card empty' }, h('p', null, h('b', null, 'Oturum bulunamadı.')), h('p', { class: 'small muted' }, err.message),
      h('a', { class: 'btn', href: be.href() }, 'Simülatör ana sayfası')));
    return;
  }
  const replay = session.mode === 'replay';   // kayıttan oynatma: SITL/UDP/komut yok; kareler sunucudan bir kez çekilir, tarayıcıda oynatılır
  const type = session.type, modes = modesFor(type);
  const world = { ...WORLD_DEFAULTS, ...(session.world || {}) };
  // Sabit kanat kalkış yöntemi (§13): session.launch {method, angle_deg, release_kmh, phase}; yalnız canlı sabit kanatta
  const launch = !replay && type === 'sabit_kanat' ? { ...LAUNCH_DEFAULTS, ...(session.launch || world.launch || {}) } : null;
  const LAUNCH_BTN = { ramp: 'Fırlat', vehicle: 'Aracı sür', wheels: 'Kalkış' };
  const LAUNCH_PHASE_TEXT = { armed: { ramp: 'Uçak rampada, motor hazır', vehicle: 'Uçak araçta, motor hazır', wheels: 'Pist koşusu başlıyor' },
    launch: { ramp: 'FIRLATMA', vehicle: 'Araç hızlanıyor', wheels: 'Pist koşusu' }, released: { ramp: 'Uçak rampadan ayrıldı', vehicle: 'BIRAKILDI', wheels: 'Uçak havalandı' } };

  // ---------- iskelet ----------
  const stage = h('div', { class: `fs-stage ${replay ? 'fs-replay' : ''}`, 'data-immersive': '1' });
  const mount = h('div', { class: 'fs-canvas' });
  const msg = h('div', { class: 'fs-msg' }, '3B dünya hazırlanıyor…');
  const crash = h('div', { class: 'fs-crash', hidden: true }, h('b', null, 'ÇARPIŞMA'), h('span', { class: 'fs-crash-sub' }));
  const events = h('div', { class: 'fs-events' });
  const stateBadge = h('span', { class: `badge ${STATE_BADGE[session.state] || 'gray'}` }, STATE_TEXT[session.state] || session.state);
  const wsBadge = h('span', { class: 'badge gray', title: 'Telemetri bağlantısı (WebSocket)' }, 'Bağlanıyor…');
  const nav = h('div', { class: 'fs-nav' },
    h('a', { class: 'fs-nav-back', href: be.href(), title: 'Simülatör listesine dön' }, '←'),
    h('b', null, 'Uçuş Simülatörü'), h('span', { class: 'fs-nav-sub' }, `${TYPE_NAME[type] || type} · ${(replay ? session.replay?.file_name : session.center?.name) || '—'}`), stateBadge, wsBadge,
    replay ? h('span', { class: 'badge purple', title: 'Kayıttan oynatma: yüklü uçuş logu aynen oynatılır; kontrol yok' }, 'Kayıt') : null,
    launch ? h('span', { class: 'badge blue fs-launch-badge', title: tr('Kalkış yöntemi') }, launchLabel(launch, tr)) : null,
    mock ? h('span', { class: 'badge purple' }, 'Sahte veri') : null,
    h('button', { class: 'fs-nav-btn fs-full-btn', type: 'button', title: 'Tam ekran', onclick: () => { (document.fullscreenElement ? document.exitFullscreen?.() : document.documentElement.requestFullscreen?.())?.then(() => onFullChange()).catch(() => {}); } }, '⛶'));
  // Tam ekran BELGEYE (document.documentElement) uygulanır, sahneye değil: ui.js modal()/toast() ve açılır menüler body'ye eklenir; sahne
  // (.fs-stage) tam ekran öğesi olsaydı bunlar tam ekran öğesinin dışında kalır ve GÖRÜNMEZDİ (kullanıcı: "tam ekrandayken mesaj pencereleri
  // arkada kalıyor, takeoff yüksekliği görünmüyor"). Belge tam ekranda: app.js `immersive` (data-immersive) üst başlığı/alt barı gizler,
  // body.fs-full + .fs-stage.fs-full sahneyi tüm ekrana yayar; çıkınca (Escape / ⛶) düzen eski hâline döner.
  const onFullChange = () => { const full = !!document.fullscreenElement; stage.classList.toggle('fs-full', full); document.body.classList.toggle('fs-full', full); const b = nav.querySelector('.fs-full-btn'); if (b) b.title = tr(full ? 'Tam ekrandan çık' : 'Tam ekran'); };
  document.addEventListener('fullscreenchange', onFullChange);
  onFullChange();

  // HUD (sağ): sabit satırlar, değerler textContent ile güncellenir (DOM yeniden kurulmaz)
  const val = cls => h('b', { class: `fs-v ${cls || ''}` }, '—');
  const V = { mode: h('span', { class: 'badge blue fs-mode' }, '—'), arm: h('span', { class: 'badge gray fs-arm' }, 'DISARMED'),
    agl: val(), msl: val(), air: val(), gnd: val(), climb: val(), hdg: val(), gps: val(), batt: val(), thr: val(), wind: val() };
  const row = (label, el, unit) => h('div', { class: 'fs-row' }, h('span', null, label), h('span', { class: 'fs-rv' }, el, unit ? h('i', null, unit) : null));
  const rcBars = Array.from({ length: 8 }, (_, i) => h('div', { class: 'fs-rc', title: tr('Kanal {n}', { n: i + 1 }) }, h('i'), h('small', null, String(i + 1))));
  const thrBar = h('div', { class: 'fs-thr' }, h('i'));
  const windArrow = h('span', { class: 'fs-wind-arrow' }, '➤');
  const netLbl = h('div', { class: 'fs-net', title: 'Telemetri alım hızı, jitter (alım aralığı − kaynak aralığı) ve uyarlanır gecikme tamponu; DR = ölü hesap' }, '');
  const hud = h('div', { class: 'fs-hud mono' },
    h('div', { class: 'fs-hud-head' }, V.mode, V.arm),
    row('AGL', V.agl, 'm'), row('MSL', V.msl, 'm'),
    row('Hava hızı', V.air, 'm/s'), row('Yer hızı', V.gnd, 'm/s'), row('Dikey hız', V.climb, 'm/s'),
    row('Yön', V.hdg, '°'), row('GPS', V.gps), row('Batarya', V.batt),
    h('div', { class: 'fs-row' }, h('span', null, 'Gaz'), h('span', { class: 'fs-rv' }, V.thr, h('i', null, '%'))), thrBar,
    h('div', { class: 'fs-row fs-row-rc' }, h('span', null, 'RC'), h('div', { class: 'fs-rcs' }, rcBars)),
    h('div', { class: 'fs-row' }, h('span', null, 'Rüzgâr'), h('span', { class: 'fs-rv' }, windArrow, V.wind, h('i', null, 'm/s'))),
    launch ? h('div', { class: 'fs-row' }, h('span', null, 'Kalkış'), h('span', { class: 'fs-rv' }, h('b', { class: 'fs-v fs-launch-v' }, launchLabel(launch, tr)))) : null,
    netLbl);
  V.wind.textContent = `${f1(world.wind_ms)} @ ${f0(world.wind_dir)}°`;
  windArrow.style.transform = `rotate(${(Number(world.wind_dir) || 0) + 90}deg)`;   // ➤ sağa bakar; rüzgâr "nereden" → ok akış yönünü gösterir

  // Mission Planner bağlantı kutusu (sol alt) — kayıt kipinde yerine kayıt bilgisi kutusu
  const addr = `${session.host || location.hostname}:${session.udp_port || '—'}`;
  const gcsBadge = h('span', { class: 'badge gray' }, 'Bekleniyor');
  const mp = replay ? h('div', { class: 'fs-mp fs-rec' },
    h('div', { class: 'fs-mp-head' }, h('b', null, 'Kayıttan oynatma'), h('span', { class: 'badge purple' }, (session.replay?.vehicle || '').split(' ')[0] || 'Log')),
    h('div', { class: 'small fs-mp-hint fs-rec-info' }, '—')) : h('div', { class: 'fs-mp' },
    h('div', { class: 'fs-mp-head' }, h('b', null, 'Mission Planner bağlantısı'), gcsBadge),
    h('div', { class: 'fs-mp-addr' }, h('code', { class: 'mono' }, `UDP ${addr}`), h('button', { class: 'btn sm', type: 'button', onclick: () => copy(addr, 'Adres kopyalandı') }, 'Kopyala')),
    h('div', { class: 'small fs-mp-hint' }, 'Mission Planner › sağ üst bağlantı türü UDP › CONNECT › port ', h('b', null, String(session.udp_port || '—')), '. USB kumanda: Mission Planner › Joystick.'));

  // Alt araç çubuğu: kamera 1–4 · Sıfırla · Bitir · ARM/DISARM · mod · Kalkış · RTL (yazma izni)
  const camBtns = CAMERA_MODES.map(([k, label], i) => h('button', { class: 'btn sm', type: 'button', 'data-cam': k, title: tr('{label} (tuş {n})', { label, n: i + 1 }), onclick: () => sim?.setCamera(k) }, `${i + 1} `, label));   // etiket ayrı çocuk: çeviri kataloğundan karşılığı bulunur
  const gimbalLbl = h('span', { class: 'small fs-gimbal', hidden: true }, '');
  const mhudBtn = h('button', { class: 'btn sm fs-mhud-btn', type: 'button', hidden: true, title: tr('Askeri HUD aç/kapa (H) · Shift+H renk'), onclick: () => { milHud?.toggle(); mhudBtn.classList.toggle('primary', !!milHud?.enabled); } }, 'HUD');
  // §14 harekât paneli (flightsim_panel.js; iframe YOK): GÖKTUNGU dron kartı görünümünde TEK kart (başlık şeridi + PFD + telemetri karoları + İŞLEMLER +
  // Haberleşme konsolu) 3B'nin ÜSTÜNDE; "Panel" düğmesi / P tuşu gösterip gizler; gizliyken sade görünüm (eski HUD + alt çubuk komutları). Kayıt/sahte kipte hub yok: PFD/telemetri çalışır, İŞLEMLER yok
  let ops = null;
  const opsBtn = h('button', { class: 'btn sm fs-ops-btn', type: 'button', title: tr('Harekât panelini göster/gizle (P): dron kartı (başlık, uçuş göstergesi, telemetri karoları, işlemler ve haberleşme konsolu) 3B dünyanın üstünde; gizliyken sade görünüm (eski HUD ve alt çubuk komutları)'), onclick: () => { if (!ops) return; ops.toggle(); } }, 'Panel');
  const armBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => cmd(last?.armed ? 'disarm' : 'arm') }, 'ARM');
  const rcBtn = h('button', { class: 'btn sm', type: 'button', title: 'Sanal kumanda: iki sanal çubuk + klavye (W/S gaz, A/D yaw, ok tuşları pitch/roll, Q/E mod kanalı, Boşluk gaz orta). RC_CHANNELS_OVERRIDE 20 Hz.', onclick: () => rcToggle() }, '🎮 ', 'Sanal kumanda');
  const modeSel = h('select', { class: 'input sm fs-modesel', onchange: () => { if (modeSel.value) cmd('mode', { mode: modeSel.value }); } },
    h('option', { value: '' }, 'Mod…'), modes.map(mm => h('option', { value: mm }, mm)));
  // Kayıt kipi: oynatma çubuğu (Oynat/Duraklat · hız 0.5×–8× · zaman kaydırıcısı · süre · Baştan); komut düğmeleri yok
  const SPEEDS = [0.5, 1, 2, 4, 8];
  const playBtn = h('button', { class: 'btn sm primary fs-play-btn', type: 'button', title: tr('Oynat / Duraklat (boşluk)'), onclick: () => player?.toggle() }, '▶');
  const speedBtns = SPEEDS.map(x => h('button', { class: `btn sm ${x === 1 ? 'primary' : ''}`, type: 'button', 'data-speed': x, onclick: () => player?.setSpeed(x) }, `${x}×`));
  const seek = h('input', { class: 'fs-seek', type: 'range', min: 0, max: 1000, step: 1, value: 0, 'aria-label': 'Zaman', oninput: () => player?.seekFrac(Number(seek.value) / 1000) });
  const timeLbl = h('span', { class: 'fs-time-lbl mono' }, '00:00 / 00:00');
  const clockLbl = h('span', { class: 'fs-clock-lbl small' }, '');
  const playBar = replay ? h('div', { class: 'fs-playbar' },
    playBtn,
    h('button', { class: 'btn sm', type: 'button', title: 'Baştan', onclick: () => player?.restart() }, '↺ ', 'Baştan'),
    h('div', { class: 'pill-group fs-speeds' }, speedBtns),
    h('div', { class: 'fs-seek-wrap' }, seek, h('i', { class: 'fs-seek-marks' })),
    timeLbl, clockLbl) : null;
  const bar = h('div', { class: 'fs-bar' },
    h('div', { class: 'pill-group' }, camBtns),
    gimbalLbl, mhudBtn, opsBtn,
    replay ? playBar : h('span', { class: 'spacer' }),
    canWrite && !replay ? h('div', { class: 'pill-group fs-cmds' },   // .fs-cmds: harekât paneli açıkken gizli (komutlar panelden)
      armBtn, modeSel,
      h('button', { class: 'btn sm fs-takeoff-btn', type: 'button', onclick: () => takeoffDialog() }, LAUNCH_BTN[launch?.method] || 'Kalkış'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => cmd('rtl') }, 'RTL')) : null,
    canWrite && !replay ? h('div', { class: 'pill-group' }, rcBtn) : null,
    h('div', { class: 'pill-group' },
      replay ? null : h('button', { class: 'btn sm', type: 'button', title: 'SITL aynı ayarlarla yeniden başlar; çarpışma kaldırılır', onclick: () => reset() }, '↺ Sıfırla'),
      h('button', { class: 'btn sm danger', type: 'button', onclick: () => endSession() }, 'Bitir')));
  const ended = h('div', { class: 'fs-ended', hidden: true });
  // Sanal kumanda katmanı: sol çubuk gaz/yaw, sağ çubuk pitch/roll (Mode 2); klavye ipucu; Mission Planner joystick uyarısı
  const stickL = h('div', { class: 'fs-stick', 'data-side': 'l' }, h('i', { class: 'fs-stick-knob' }), h('small', null, 'Gaz / Yaw'));
  const stickR = h('div', { class: 'fs-stick', 'data-side': 'r' }, h('i', { class: 'fs-stick-knob' }), h('small', null, 'Pitch / Roll'));
  const rcWarn = h('div', { class: 'fs-rc-warn', hidden: true }, 'Mission Planner joystick de açıksa son gelen RC komutu geçerli olur');
  const rcHint = h('div', { class: 'fs-rc-hint' }, h('span', null, 'W/S gaz · A/D yaw · ↑↓ pitch · ←→ roll · Q/E mod kanalı · Boşluk gaz orta'), rcWarn);
  const sticks = h('div', { class: 'fs-sticks', hidden: true }, stickL, stickR, rcHint);
  // Kaynak atfı: gerçek arazi sağ altta metin; Google 3B'de ToS gereği Google logosu + canlı veri sağlayıcı metni (sol alt, MP kutusu üstü)
  const g3dMode = world.mode === 'google3d';
  const attribTxt = h('span', null, g3dMode ? 'Google' : ATTRIBUTION);
  const attrib = world.mode === 'real' || g3dMode ? h('div', { class: `fs-attrib ${g3dMode ? 'fs-attrib-g3d' : ''}` }, g3dMode ? h('img', { class: 'fs-g3d-logo', src: G3D_LOGO, alt: 'Google' }) : null, attribTxt) : null;
  stage.append(mount, msg, crash, hud, mp, events, sticks, bar, nav, ended);
  if (attrib) stage.append(attrib);
  ops = createOpsPanel(stage, { sid, session, type, modes, launch, canWrite, hub: !replay && !mock, getSim: () => sim, cmdSim: (name, params) => cmd(name, params), onReset: () => reset(), onToggle: on => opsBtn.classList.toggle('primary', on) });
  opsBtn.classList.toggle('primary', ops.enabled);
  const audio = createEngineAudio(stage, { type, launch, replay, tr, getSim: () => sim, getCrashed: () => !crash.hidden, getSpeed: () => player?.speed() ?? 1 });   // §16: düğmeyi alt çubuğa kendisi ekler; kamera/kalkış aşaması/çarpışma getter'lardan

  // Tam alan yerleşimi (Canlı Uçuş iframe kalıbı): main#view mutlak konumlu, scroller kaydırmaz
  view.classList.add('ops-view');
  const scroller = view.closest('.scroller');
  scroller?.classList.add('ops-scroll');
  clear(view, stage);

  // Olay şeridi (3B kurulumundan önce tanımlı: gerçek arazi yükleme özeti de buraya yazılır).
  // Canlıda saat (şimdi); kayıtta log zamanı (mm:ss) ve MAVLink/DataFlash önem düzeyi (sayı: 0–3 hata, 4 uyarı)
  const sevClass = severity => {
    if (typeof severity === 'number') return severity <= 3 ? 'err' : severity === 4 ? 'warn' : 'info';
    const sev = String(severity || 'info').toLowerCase();
    return /err|crit|alert|emerg/.test(sev) ? 'err' : /warn/.test(sev) ? 'warn' : 'info';
  };
  // tag: panel konsolu etiketi ('SİM' yerel olaylar, 'STATUS' dronun STATUSTEXT'i — hub'ın aynı satırı panelde atlanır, tekrar olmaz)
  const addEvent = (text, severity = 'info', at = null, tag = 'SİM') => {
    const now = new Date();
    const stamp = at != null ? clock(at) : `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
    events.prepend(h('div', { class: `fs-ev ${sevClass(severity)}` }, h('span', { class: 'fs-ev-t' }, stamp), h('span', null, text)));
    while (events.children.length > 8) events.lastChild.remove();
    ops?.log(text, { err: 'hata', warn: 'uyari', info: 'bilgi' }[sevClass(severity)], tag);
  };

  // ---------- 3B ----------
  let sim = null, last = null, socket = null, destroyed = false, rc = null, worldReady = false, milHud = null;   // rc: sanal kumanda (virtualRC) ya da null
  // Askeri FPV HUD bağlamı: getter'lar her karede okunur (3B'nin render ettiği yönelim, gimbal, çarpışma)
  const hudCtx = { world, session, replay, launch, fov: 78, t0: Date.parse(session.created_at) || Date.now(),
    get pose() { return sim?.getPose?.() || null; }, get gimbalDeg() { return sim?.getGimbal() ?? 0; }, get camMode() { return sim?.getCamera(); }, get collision() { return !crash.hidden; } };
  milHud = createMilHud(stage, hudCtx, { tr });
  mhudBtn.classList.toggle('primary', milHud.enabled);
  const progMsg = p => {   // gerçek arazi yükleme ilerlemesi (3B tuval üstünde)
    if (destroyed) return;
    if (p.stage === 'done') {
      worldReady = true;
      if (session.state === 'HAZIR' || mock) msg.hidden = true;
      if (p.real) addEvent(`${tr('Gerçek arazi · yükseklik {a}…{b} m · ev {h} m MSL', { a: f0(p.hmin), b: f0(p.hmax), h: f0(p.homeElev) })} · ${tr('{b} bina · {f} orman · {w} su · {r} pist', { b: p.counts?.buildings ?? 0, f: p.counts?.forests ?? 0, w: p.counts?.water ?? 0, r: p.counts?.runways ?? 0 })}`);
      if (p.google) addEvent(tr('Google 3B (fotogerçekçi) · ev {h} m MSL', { h: f0(p.homeElev) }));
      const info = sim?.terrainInfo;
      if (p.real && info?.osmError) addEvent(tr('OSM verisi alınamadı: binalar/orman/su gösterilmiyor ({e})', { e: info.osmError }), 'warning');
      return;
    }
    if (p.stage === 'g3d-ground') { addEvent(tr('Google 3B yer ofseti {o} m (karo yüzeyi ↔ ev irtifası)', { o: f1(p.offset) })); return; }
    if (p.stage === 'g3d') {   // Google karoları: yalnız ilk dolum perdede; sonrası atıf satırında "yükleniyor %"
      if (worldReady) return;
      if (p.pct >= 100) { if (session.state === 'HAZIR' || mock) msg.hidden = true; return; }
      msg.hidden = false; msg.textContent = tr('Google 3B karoları yükleniyor… %{p}', { p: p.pct ?? 0 });
      return;
    }
    msg.hidden = false;
    msg.textContent = p.stage === 'elev' ? tr('Yükseklik karoları {d}/{n}', { d: p.done, n: p.total }) : p.stage === 'img' ? tr('Uydu karoları {d}/{n}', { d: p.done, n: p.total })
      : p.stage === 'osm' ? tr('Harita verileri (OSM) alınıyor…') : tr('Arazi planı alınıyor…');
  };
  try {
    if (world.mode === 'real') { msg.textContent = tr('Arazi planı alınıyor…'); }
    if (g3dMode) { msg.textContent = tr('Google 3B karoları yükleniyor… %{p}', { p: 0 }); }
    sim = await createFlightSim3D(mount, world, {
      type, model: session.model || session.airframe, launch, origin: { lat: session.center?.lat ?? session.replay?.home?.lat, lon: session.center?.lon ?? session.replay?.home?.lon, alt: session.center?.alt ?? session.replay?.home?.alt },
      onCameraChange: mode => { camBtns.forEach(b => b.classList.toggle('primary', b.dataset.cam === mode)); gimbalLbl.hidden = mode !== 'fpv'; mhudBtn.hidden = mode !== 'fpv'; milHud?.setCamMode(mode); ops?.setFpv(mode === 'fpv'); gimbalLbl.textContent = tr('Gimbal {d}° (↑↓ / tekerlek)', { d: sim?.getGimbal() ?? 0 }); },   // FPV: harekât kartları gizli, askeri HUD kalır (§14)
      onCollision: replay ? null : info => onCrash(info),   // kayıt: gerçek uçuş → çarpışma denetimi yok
      onProgress: progMsg,
      g3dKey: be.g3dKey,
      onFallback: e => { const t = g3dMode ? tr('Google 3B verisi alınamadı: {e} → prosedürele düşüldü', { e }) : tr('Gerçek veri alınamadı, prosedürele düşüldü: {e}', { e }); addEvent(t, 'warning'); toast(t, 'err'); if (attrib) attrib.hidden = true; },
    });
    if (netsim) window.__fsSim = sim;   // teşhis: Playwright/konsol sim.netStats() · sim.motionStats(true)
    if (sim.terrainInfo && !worldReady) progMsg({ stage: 'done', real: sim.real, ...sim.terrainInfo });
    if (launch && session.launch?.phase) sim.setLaunchPhase(session.launch.phase);   // oturuma geç katılan izleyici: aşama sunucudan
    msg.hidden = true;
  } catch (err) {
    msg.textContent = tr('3B dünya açılamadı: {e}', { e: err.message });
    msg.classList.add('err');
  }
  camBtns[0].classList.add('primary');
  const gimbalTick = setInterval(() => {
    if (!gimbalLbl.hidden && sim) gimbalLbl.textContent = tr('Gimbal {d}° (↑↓ / tekerlek)', { d: sim.getGimbal() });
    if (g3dMode && sim?.google) {   // Google atfı canlı (görünür karoların veri sağlayıcıları) + yükleme yüzdesi
      const a = sim.g3dAttribution();
      if (a) { const t = a.loading < 100 ? `${a.text} · ${tr('yükleniyor %{p}', { p: a.loading })}` : a.text; if (attribTxt.textContent !== t) attribTxt.textContent = t; }
    }
  }, 300);

  // ---------- olaylar / durum ----------
  const setState = st => {
    session.state = st;
    stateBadge.className = `badge ${STATE_BADGE[st] || 'gray'}`;
    stateBadge.textContent = tr(STATE_TEXT[st] || st);
    if (st === 'BASLIYOR') { msg.hidden = false; msg.textContent = replay ? tr('Kayıt hazırlanıyor… %{p}', { p: session.replay?.progress ?? 0 }) : tr('SITL başlıyor…'); }
    else if (st === 'HATA') { msg.hidden = false; msg.classList.add('err'); msg.textContent = replay ? tr('Kayıt açılamadı: {e}', { e: session.sitl?.error || '—' }) : tr('SITL hatası: {e}', { e: session.sitl?.error || '—' }); }
    else if (st === 'HAZIR' && sim) { msg.hidden = true; msg.classList.remove('err'); if (replay) loadReplay(); }
    ops?.setState(st);
  };
  const setWs = st => {
    const map = { connecting: ['yellow', 'Bağlanıyor…'], reconnect: ['yellow', 'Yeniden bağlanıyor…'], open: ['green', 'Canlı'], closed: ['red', 'Bağlantı koptu'] };
    const [tone, text] = map[st] || ['gray', st];
    wsBadge.className = `badge ${tone}`; wsBadge.textContent = tr(text);
  };
  const setGcs = (connected, a) => { gcsBadge.className = `badge ${connected ? 'green' : 'gray'}`; gcsBadge.textContent = connected ? tr('Bağlı ({ip})', { ip: a || '' }) : tr('Bekleniyor'); ops?.setGcs(connected); };
  setGcs(!!session.gcs?.connected, session.gcs?.addr);
  if (session.state !== 'HAZIR') setState(session.state);

  // ---------- HUD güncelle (en çok ~12 Hz) ----------
  let hudAt = 0;
  // RC çubukları: sanal kumanda açıkken 1–5 yerel kanal değerleri (anlık), diğerleri telemetriden
  const drawRcBars = teleRc => {
    const loc = rc?.channels();
    for (let i = 0; i < 8; i++) {
      const v = loc && i < 5 ? loc[i] : Number((teleRc || [])[i]);
      const pct = Math.max(0, Math.min(100, ((v || 1500) - 1000) / 10));
      rcBars[i].firstChild.style.height = `${pct}%`;
      rcBars[i].classList.toggle('vr', !!loc && i < 5);
    }
  };
  const updateHud = t => {
    last = t;
    sim?.setTelemetry(t);
    milHud?.update(t); audio.update(t); ops?.update(t);
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
    V.gps.textContent = `${t.gps_fix >= 6 ? 'RTK' : t.gps_fix === 5 ? 'RTK FLT' : t.gps_fix === 4 ? 'DGPS' : t.gps_fix === 3 ? '3D' : t.gps_fix === 2 ? '2D' : tr('Yok')} · ${f0(t.sats)} ${tr('uydu')}`;
    V.batt.textContent = `${t.batt_v != null && Number(t.batt_v) > 0 ? Number(t.batt_v).toFixed(2) : '—'} V · %${f0(t.batt_pct)}`;   // SITL'de batarya izleme kapalıysa 0 V gelir
    V.batt.classList.toggle('warn', t.batt_pct != null && t.batt_pct < 25);
    V.thr.textContent = f0(t.throttle);
    thrBar.firstChild.style.width = `${Math.max(0, Math.min(100, Number(t.throttle) || 0))}%`;
    drawRcBars(t.rc);
    if (rc) rcWarn.hidden = !t.gcs_connected;
    if (canWrite && !replay) { armBtn.textContent = t.armed ? 'DISARM' : 'ARM'; armBtn.classList.toggle('danger', !!t.armed); if (t.mode && modeSel.value !== t.mode && document.activeElement !== modeSel) modeSel.value = modes.includes(t.mode) ? t.mode : ''; }
    if (t.gcs_connected != null) setGcs(!!t.gcs_connected, t.gcs_addr);
  };

  // ---------- kayıttan oynatma: kareleri çek, enterpolasyonla oynat ----------
  let player = null, replayLoaded = false;
  const loadReplay = async () => {
    if (!replay || replayLoaded) return;
    replayLoaded = true;
    msg.hidden = false; msg.classList.remove('err'); msg.textContent = tr('Kareler indiriliyor…');
    let data;
    try { data = await be.replay(sid); } catch (err) { replayLoaded = false; msg.classList.add('err'); msg.textContent = tr('Kayıt açılamadı: {e}', { e: err.message }); return; }
    if (destroyed) return;
    msg.hidden = true;
    // Dünya uçuşu kapsasın: evden en uzak kare mesafesinin 2,4 katı (en az seçilen boyut, en çok 20 km) — uçak arazi dışına çıkmasın
    if (sim && data.home && Array.isArray(data.frames) && data.frames.length) {
      const FI = Object.fromEntries((data.fields || []).map((k, i) => [k, i]));
      let maxD = 0;
      const step = Math.max(1, Math.floor(data.frames.length / 4000));
      for (let i = 0; i < data.frames.length; i += step) { const f = data.frames[i]; if (f[FI.lat] == null) continue; const p = sim.toLocal(f[FI.lat], f[FI.lon]); maxD = Math.max(maxD, Math.hypot(p.x, p.y)); }
      const need = Math.min(20000, Math.ceil(maxD * 2.4 / 500) * 500);
      if (need > (Number(world.size_m) || 0)) { world.size_m = need; sim.setWorld(world); addEvent(tr('Dünya boyutu uçuşa göre {n} m yapıldı', { n: need }), 6); }
    }
    player = createReplayPlayer(data, {
      onFrame: t => updateHud(t),
      onEvent: (e, t) => addEvent(e.text, e.sev, t),
      onClear: () => clear(events),
      onSeek: () => sim?.snapCamera(),   // atlama: takip kamerası dronun yanına ışınlanır (yayla yüzlerce metre kovalamaz)
      onTime: (t, dur, playing) => {
        seek.value = String(Math.round(1000 * (dur ? t / dur : 0)));
        timeLbl.textContent = `${clock(t)} / ${clock(dur)}`;
        if (data.start_utc) { const d = new Date(new Date(data.start_utc).getTime() + t * 1000); clockLbl.textContent = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`; }
        playBtn.textContent = playing ? '❚❚' : '▶';
      },
      onSpeed: sp => speedBtns.forEach(b => b.classList.toggle('primary', Number(b.dataset.speed) === sp)),
    });
    // Kayıt bilgisi kutusu + kaydırıcıda olay/kalkış işaretleri
    const info = mp.querySelector('.fs-rec-info');
    if (info) clear(info, h('div', null, h('b', null, session.replay?.file_name || '—')),
      h('div', null, [data.vehicle, data.n != null ? tr('{n} kare', { n: data.n }) : null, data.hz ? `${data.hz} Hz` : null, fmtDuration(data.duration_s)].filter(Boolean).join(' · ')),
      data.start_utc ? h('div', null, tr('Kayıt başı: {t}', { t: fmtDateTime(data.start_utc) })) : null,
      data.home ? h('div', null, tr('Kalkış: {lat}, {lon} · {alt} m MSL', { lat: Number(data.home.lat).toFixed(5), lon: Number(data.home.lon).toFixed(5), alt: f0(data.home.alt) })) : null);
    const marks = playBar?.querySelector('.fs-seek-marks');
    if (marks && data.duration_s) {
      const dur = data.duration_s;
      clear(marks, (data.events || []).filter(e => e.sev <= 4).slice(0, 60).map(e => h('b', { class: e.sev <= 3 ? 'err' : 'warn', style: { left: `${(e.t / dur * 100).toFixed(2)}%` }, title: `${clock(e.t)} ${e.text}` })),
        data.takeoff_t != null ? h('b', { class: 'to', style: { left: `${(data.takeoff_t / dur * 100).toFixed(2)}%` }, title: tr('İlk ARM {t}', { t: clock(data.takeoff_t) }) }) : null);
    }
    // İlk ARM'den 5 sn önce başla; otomatik oynat
    player.seek(Math.max(0, (data.takeoff_t ?? 0) - 5));
    sim?.resetCamera();
    player.play();
    addEvent(tr('Kayıt yüklendi: {n} kare · {d}', { n: data.n, d: fmtDuration(data.duration_s) }), 6, player.time());
  };
  const onKeyReplay = e => {
    if (!player || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')) return;
    if (e.key === ' ') { player.toggle(); e.preventDefault(); }
    else if (e.key === 'ArrowLeft') { player.seek(player.time() - (e.shiftKey ? 30 : 5)); e.preventDefault(); }
    else if (e.key === 'ArrowRight') { player.seek(player.time() + (e.shiftKey ? 30 : 5)); e.preventDefault(); }
  };
  if (replay) window.addEventListener('keydown', onKeyReplay);

  // ---------- komutlar ----------
  const cmd = async (name, params = {}) => {
    try { await be.cmd(sid, name, params); addEvent(tr('Komut: {c}', { c: name + (params.mode ? ` ${params.mode}` : params.alt != null ? ` ${params.alt} m` : '') })); } catch (err) { toastError(err); }
  };
  const takeoffDialog = () => {
    const alt = h('input', { class: 'input', type: 'number', min: 1, max: 500, value: isPlane(type) ? 80 : 30 });
    const m = launch?.method;
    const hint = m === 'ramp' ? tr('Uçak TAKEOFF moduna alınır ve ARM edilir; 1 sn sonra pnömatik rampa kızağı {a}° açıyla fırlatır (SITL mancınık tetiği). Fırlatma ivmesi algılanınca gaz açılır.', { a: Math.round(launch.angle_deg) })
      : m === 'vehicle' ? tr('Uçak TAKEOFF moduna alınır ve ARM edilir; pickup pist boyunca hızlanır, {k} km/h yer hızında uçak bırakılır ve tırmanır.', { k: Math.round(launch.release_kmh) })
      : isPlane(type) ? 'Uçak TAKEOFF moduna alınır; pist boyunca hızlanır.' : 'Dron GUIDED modda belirtilen irtifaya yükselir.';
    const label = LAUNCH_BTN[m] || 'Kalkış';
    modal({ title: label, body: field('Hedef irtifa (m, AGL)', alt, hint),
      actions: [{ label: 'Vazgeç' }, { label, class: 'primary', onClick: () => cmd('takeoff', { alt: Number(alt.value) || 30 }) }] });
  };
  // Kalkış aşaması (WS `launch`): 3B düzenek + olay şeridi
  const onLaunch = m => {
    if (!launch) return;
    sim?.setLaunchPhase(m.phase); ops?.setLaunchPhase(m.phase);
    const txt = (LAUNCH_PHASE_TEXT[m.phase] || {})[launch.method] || m.phase;
    addEvent(m.phase === 'released' && m.speed_kmh != null ? `${tr(txt)} · ${f0(m.speed_kmh)} km/h` : tr(txt), m.phase === 'released' || m.phase === 'launch' ? 'warning' : 'info');
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
    sim?.setLaunchPhase(null);   // uçak yeniden rampaya / araca oturur
    sim?.resetCamera();
    if (canWrite) await cmd('reset'); else toast('Sıfırlamak için yazma izni gerekir', 'err');
  };
  const endSession = async () => {
    if (!canWrite) { location.hash = be.href(); return; }
    if (!await confirmDialog('Oturumu bitir', replay ? 'Kayıttan oynatma oturumu kapatılsın mı?' : 'Simülatör oturumu kapatılsın mı? SITL süreci ve UDP portu kapanır; Mission Planner bağlantısı düşer.', { okLabel: 'Bitir', danger: true })) return;
    try { await be.end(sid); toast('Oturum kapatıldı'); location.hash = be.href(); } catch (err) { toastError(err); }
  };
  const END_REASON = { kapatildi: 'Oturum kapatıldı', bosta: 'İzleyici ve GCS olmadığından kapatıldı', sure: 'Oturum süresi doldu', sunucu_kapaniyor: 'Sunucu kapanıyor' };
  const showEnded = reason => {
    clear(ended, h('div', { class: 'fs-ended-box' }, h('b', null, 'Oturum sona erdi'), h('div', { class: 'small muted' }, tr(END_REASON[reason] || reason || '')),
      h('a', { class: 'btn primary', href: be.href() }, 'Simülatör ana sayfası')));
    ended.hidden = false;
  };

  // ---------- telemetri bağlantısı (WS ya da mock) ----------
  socket = be.socket(sid, {
    status: setWs,
    fatal: why => { setWs('closed'); showEnded(why === 'auth' ? tr('Bu oturumu izleme yetkiniz yok.') : why === 'notfound' ? tr('Oturum sunucuda yok (kapanmış olabilir).') : why); },
    message: m => {
      if (destroyed) return;
      if (m.t === 'tele') { if (replay) return; if (!netsim) return updateHud(m); if (Math.random() * 100 < netsim.loss) return; return void setTimeout(() => { if (!destroyed) updateHud(m); }, netsim.delay + Math.random() * 2 * netsim.jitter); }
      if (m.t === 'hello') { if (m.session) { Object.assign(session, m.session); setState(session.state); setGcs(!!session.gcs?.connected, session.gcs?.addr); if (Array.isArray(session.route)) { sim?.setRoute(session.route); ops?.setRoute(session.route); } } return; }
      if (m.t === 'route') { sim?.setRoute(m.points || []); ops?.setRoute(m.points || []); if (m.points?.length) addEvent(tr('Rota yüklendi: {n} nokta', { n: m.points.length })); return; }   // §14: SITL'deki görev → 3B çizgi/işaretler + panel rota durumu
      if (m.t === 'event') return addEvent(m.text, m.severity, replay ? (player?.time() ?? null) : null, 'STATUS');
      if (m.t === 'launch') return onLaunch(m);
      if (m.t === 'state') { if (m.replay) session.replay = { ...(session.replay || {}), ...m.replay }; return setState(m.state); }
      if (m.t === 'replay' && m.action === 'reset') return player?.restart();
      if (m.t === 'end') { setState('KAPANDI'); showEnded(m.reason); socket?.close(); }
    },
  });

  // ---------- sanal kumanda (yazma izni): 20 Hz {t:'rc', ch} yalnız açıkken; kapatınca tek sefer 8×0 (override serbest) ----------
  const rcToggle = () => {
    if (!canWrite) { toast('Sanal kumanda için yazma izni gerekir', 'err'); return; }
    if (rc) {
      rc.dispose();                      // zamanlayıcı durur, dinleyiciler kalkar, 8×0 gönderilir
      rc = null;
      sticks.hidden = true; stage.classList.remove('rc-on'); rcBtn.classList.remove('primary');
      sim?.setKeyboardLock(false);
      drawRcBars(last?.rc);
      addEvent(tr('Sanal kumanda kapatıldı (RC override serbest)'));
      return;
    }
    rc = virtualRC({ plane: isPlane(type), stickL, stickR, send: ch => socket?.send({ t: 'rc', ch }), onChange: () => drawRcBars(last?.rc) });
    sticks.hidden = false; stage.classList.add('rc-on'); rcBtn.classList.add('primary');
    rcWarn.hidden = !last?.gcs_connected;
    sim?.setKeyboardLock(true);
    addEvent(tr('Sanal kumanda açık (RC override)'));
  };
  const netTick = setInterval(() => {
    if (!sim || replay) { netLbl.hidden = true; return; }   // kayıt kipinde ağ akışı yok
    const n = sim.netStats();
    netLbl.textContent = tr('net: {hz} Hz · jitter {j} ms · tampon {d} ms', { hz: n.hz, j: n.jitter, d: n.delay }) + (n.deadReckoning ? ' · DR' : '');
    netLbl.classList.toggle('warn', n.hz > 0 && (n.hz < 15 || n.jitter > 40));
  }, 500);

  onLeave(() => {
    destroyed = true;
    clearInterval(gimbalTick); clearInterval(netTick);
    if (rc) { rc.dispose(); rc = null; }   // override serbest bırakılır (soket kapanmadan önce)
    if (replay) window.removeEventListener('keydown', onKeyReplay);
    player?.dispose();
    socket?.close();
    milHud?.dispose();
    audio.dispose(); ops?.dispose();
    sim?.dispose();
    if (window.__fsSim === sim) delete window.__fsSim;
    view.classList.remove('ops-view');
    scroller?.classList.remove('ops-scroll');
    document.removeEventListener('fullscreenchange', onFullChange);
    document.body.classList.remove('immersive', 'fs-full');
  });
}

// ======================================================================
// Sanal kumanda: iki sanal çubuk (Mode 2: sol gaz/yaw, sağ pitch/roll; dokunmatik + fare, pointer events) + klavye.
// ArduPilot RC: ch1 roll, ch2 pitch (ileri = burun aşağı = düşük PWM), ch3 gaz, ch4 yaw, ch5 mod anahtarı; 1000–2000, merkez 1500.
// Eksenler −1…1: tuş basılıyken KEY_RATE ile uca gider, bırakılınca yaylı (üstel) merkeze döner. Kopterde gaz çubuğu merkeze yaylıdır
// (1500 ≈ askı); uçakta gaz tutmalıdır (W/S kaydırır, çubuk bırakıldığı yerde kalır). Boşluk = gaz 1500. Q/E = ch5 1000/1500/2000.
// 20 Hz: tick (klavye entegrasyonu + çizim) → send(channels()). dispose(): zamanlayıcı/dinleyiciler kalkar, 8×0 (override serbest) gönderilir.
// ======================================================================
const RC_KEYS = new Set(['w', 'a', 's', 'd', 'q', 'e', ' ', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright']);
function virtualRC({ plane, stickL, stickR, send, onChange }) {
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const ax = { roll: 0, pitch: 0, thr: plane ? -1 : 0, yaw: 0 };   // thr: −1 = 1000 (uçak boşta), 0 = 1500 (kopter askı)
  let ch5 = 1500, lastT = performance.now(), disposed = false;
  const keys = new Set();
  const drag = { l: null, r: null };          // sürüklenen çubuk: {id, x0, y0, r}
  const KEY_RATE = 3.5, SPRING = 9, THR_RATE = 0.7;
  const editable = el => el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
  const pwm = v => Math.round(clamp(1500 + v * 500, 1000, 2000));
  const channels = () => [pwm(ax.roll), pwm(-ax.pitch), pwm(ax.thr), pwm(ax.yaw), ch5, 0, 0, 0];   // 6–8: 0 = o kanala dokunma

  // --- klavye ---
  const onKeyDown = e => {
    if (disposed || editable(document.activeElement) || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (!RC_KEYS.has(k)) return;
    e.preventDefault();
    if (e.repeat) return;
    if (k === ' ') { ax.thr = 0; return; }
    if (k === 'q' || k === 'e') { ch5 = clamp(ch5 + (k === 'e' ? 500 : -500), 1000, 2000); return; }
    keys.add(k);
  };
  const onKeyUp = e => keys.delete(e.key.toLowerCase());
  const onBlur = () => keys.clear();

  // --- çubuklar (pointer events; touch-action: none) ---
  const bind = (el, side) => {
    const knob = el.querySelector('.fs-stick-knob');
    const down = e => {
      if (disposed) return;
      const b = el.getBoundingClientRect();
      drag[side] = { id: e.pointerId, cx: b.left + b.width / 2, cy: b.top + b.height / 2, r: b.width / 2 - 16 };
      el.setPointerCapture(e.pointerId); el.classList.add('on');
      move(e); e.preventDefault();
    };
    const move = e => {
      const d = drag[side];
      if (!d || e.pointerId !== d.id) return;
      const x = clamp((e.clientX - d.cx) / d.r, -1, 1), y = clamp(-(e.clientY - d.cy) / d.r, -1, 1);
      if (side === 'l') { ax.yaw = x; ax.thr = y; } else { ax.roll = x; ax.pitch = y; }
    };
    const up = e => { if (drag[side] && e.pointerId === drag[side].id) { drag[side] = null; el.classList.remove('on'); } };
    el.addEventListener('pointerdown', down); el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    return { knob, off: () => { el.removeEventListener('pointerdown', down); el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); el.classList.remove('on'); } };
  };
  const L = bind(stickL, 'l'), R = bind(stickR, 'r');
  const draw = () => {
    const place = (knob, x, y) => { knob.style.transform = `translate(${(x * 40).toFixed(1)}px, ${(-y * 40).toFixed(1)}px)`; };
    place(L.knob, ax.yaw, ax.thr); place(R.knob, ax.roll, ax.pitch);
  };

  // --- 20 Hz: klavye entegrasyonu + yay, çizim, gönderim ---
  const tick = () => {
    const now = performance.now(), dt = Math.min(0.2, (now - lastT) / 1000); lastT = now;
    const kax = (neg, pos) => (keys.has(pos) ? 1 : 0) - (keys.has(neg) ? 1 : 0);
    const decay = Math.exp(-SPRING * dt);
    const spring = (key, dir) => { if (dir) ax[key] = clamp(ax[key] + dir * KEY_RATE * dt, -1, 1); else { ax[key] *= decay; if (Math.abs(ax[key]) < 0.004) ax[key] = 0; } };
    if (!drag.r) { spring('roll', kax('arrowleft', 'arrowright')); spring('pitch', kax('arrowdown', 'arrowup')); }
    if (!drag.l) {
      spring('yaw', kax('a', 'd'));
      const t = kax('s', 'w');
      if (plane) { if (t) ax.thr = clamp(ax.thr + t * THR_RATE * dt, -1, 1); }   // tutmalı gaz
      else spring('thr', t);                                                     // askıya yaylı
    }
    draw();
    const ch = channels();
    send(ch);
    onChange?.(ch);
  };
  window.addEventListener('keydown', onKeyDown); window.addEventListener('keyup', onKeyUp); window.addEventListener('blur', onBlur);
  const timer = setInterval(tick, 50);
  draw();
  return {
    channels,
    dispose() {
      if (disposed) return;
      disposed = true;
      clearInterval(timer);
      window.removeEventListener('keydown', onKeyDown); window.removeEventListener('keyup', onKeyUp); window.removeEventListener('blur', onBlur);
      L.off(); R.off();
      L.knob.style.transform = R.knob.style.transform = '';
      send([0, 0, 0, 0, 0, 0, 0, 0]);   // override serbest
    },
  };
}

// ======================================================================
// Kayıt oynatıcı: sunucudan gelen kare dizisi (fields sırası: flightsim_replay.FIELDS) → zaman t için enterpolasyonlu `tele` nesnesi.
// requestAnimationFrame ile ilerler (hız 0.5×–8×); kaydırıcı/klavye ile atlama; olaylar zaman geldikçe şeride düşer (atlamada şerit
// yeniden kurulur: t'den önceki son 8 olay). Sonda durur.
// ======================================================================
function createReplayPlayer(data, cb) {
  const F = data.frames || [], FI = Object.fromEntries((data.fields || []).map((k, i) => [k, i]));
  const modes = data.modes || [];
  const EV = (data.events || []).slice().sort((a, b) => a.t - b.t);
  const dur = Math.max(0.001, Number(data.duration_s) || (F.length ? F[F.length - 1][0] : 0));
  const col = (fr, k) => (FI[k] == null ? null : fr[FI[k]]);
  let t = 0, speed = 1, playing = false, raf = 0, last = 0, evIdx = 0, disposed = false;
  const find = x => { let lo = 0, hi = F.length - 1; while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (F[mid][0] <= x) lo = mid; else hi = mid - 1; } return lo; };
  const lerp = (a, b, u) => (a == null ? b : b == null ? a : a + (b - a) * u);
  const lerpAng = (a, b, u) => { if (a == null || b == null) return a ?? b; let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return a + d * u; };
  const frameAt = x => {
    if (!F.length) return null;
    const i = find(x), a = F[i], b = F[Math.min(i + 1, F.length - 1)];
    const span = b[0] - a[0], u = span > 0 && span < 5 ? Math.max(0, Math.min(1, (x - a[0]) / span)) : 0;   // 5 sn'den uzun boşlukta tutma (log kesintisi)
    const g = k => lerp(col(a, k), col(b, k), u);
    const yaw = lerpAng(col(a, 'yaw'), col(b, 'yaw'), u);
    const vn = g('vn'), ve = g('ve'), vd = g('vd');
    const gs = g('gs'), hdg = col(a, 'hdg') != null ? ((lerpAng(col(a, 'hdg') * Math.PI / 180, col(b, 'hdg') * Math.PI / 180, u) * 180 / Math.PI) + 360) % 360 : null;
    const mi = col(a, 'mode');
    return { ts: Date.now(), t: x, lat: g('lat'), lon: g('lon'), alt_msl: g('alt_msl'), alt_rel: g('alt_rel'), roll: lerpAng(col(a, 'roll'), col(b, 'roll'), u), pitch: lerpAng(col(a, 'pitch'), col(b, 'pitch'), u), yaw,
      vn, ve, vd, airspeed: g('as'), groundspeed: gs != null ? gs : (vn != null ? Math.hypot(vn, ve || 0) : null), heading: hdg, climb: vd != null ? -vd : null,
      mode: mi != null ? modes[mi] : null, armed: !!col(a, 'armed'), gps_fix: col(a, 'fix'), sats: col(a, 'sats'), batt_v: g('batt_v'), batt_pct: col(a, 'batt_pct'),
      throttle: g('thr'), rc: col(a, 'rc') || [], home: data.home || null, gcs_connected: null };
  };
  const emitFrame = () => { const fr = frameAt(t); if (fr) cb.onFrame?.(fr); cb.onTime?.(t, dur, playing); };
  const syncEvents = () => {   // atlama: t'den önceki son 8 olayı şeride koy
    cb.onClear?.();
    evIdx = 0;
    while (evIdx < EV.length && EV[evIdx].t <= t) evIdx++;
    for (const e of EV.slice(Math.max(0, evIdx - 8), evIdx)) cb.onEvent?.(e, e.t);
  };
  const pumpEvents = () => { while (evIdx < EV.length && EV[evIdx].t <= t) { cb.onEvent?.(EV[evIdx], EV[evIdx].t); evIdx++; } };
  const tick = now => {
    if (disposed) return;
    raf = requestAnimationFrame(tick);
    const dt = Math.min(0.25, (now - last) / 1000); last = now;
    if (!playing) return;
    t += dt * speed;
    if (t >= dur) { t = dur; playing = false; }
    pumpEvents();
    emitFrame();
  };
  const seek = x => { t = Math.max(0, Math.min(dur, Number(x) || 0)); syncEvents(); emitFrame(); cb.onSeek?.(t); };
  const play = () => { if (t >= dur) t = 0; playing = true; last = performance.now(); cb.onTime?.(t, dur, playing); };
  const pause = () => { playing = false; cb.onTime?.(t, dur, playing); };
  raf = requestAnimationFrame(now => { last = now; tick(now); });
  seek(0);
  cb.onSpeed?.(speed);
  return {
    play, pause, toggle: () => (playing ? pause() : play()), seek, seekFrac: f => seek(f * dur), restart: () => { seek(0); play(); },
    setSpeed: s => { speed = Number(s) || 1; cb.onSpeed?.(speed); }, time: () => t, duration: () => dur, frameAt, playing: () => playing, speed: () => speed,
    dispose: () => { disposed = true; cancelAnimationFrame(raf); },
  };
}

// ======================================================================
// MOCK: arka uç yokken yerel kinematik üretici (WS yerine). Oturumlar bellekte (sekme ömrü). Komutlar üreticiye uygulanır.
// Kayıt kipi (mode 'replay'): sahte log listesi + 2 dakikalık sahte kare dizisi (kalkış, daire, iniş; MSG olayları).
// ======================================================================
const MOCK = { sessions: new Map(), seq: 0 };
const SAMPLE_CENTERS = [
  { id: 1, name: 'Örnek Merkez · Akyurt', lat: 40.1305, lon: 33.0876, alt: 1050, location_name: 'Ankara' },
  { id: 2, name: 'Örnek Merkez · Kıyı', lat: 36.8841, lon: 30.7056, alt: 30, location_name: 'Antalya' },
];
function mockBackend(ctx) {
  let centersP = null;
  const centers = () => (centersP ??= api.get('/api/drone/centers').then(r => (Array.isArray(r) && r.length ? r.map(c => ({ id: c.id, name: c.name, lat: c.lat, lon: c.lon, alt: c.alt ?? 0, location_name: c.location_name })) : SAMPLE_CENTERS)).catch(() => SAMPLE_CENTERS));
  const mockModel = (type, model) => (model && typeof model === 'object' ? model : { id: model || ({ multirotor: 'builtin:quad', hexarotor: 'builtin:hexa', helikopter: 'builtin:heli' }[type] || 'builtin:caymaz'), source: 'builtin', type, ready: true });
  const mk = async (type, centerId, world, model) => {
    const cs = await centers();
    const center = cs.find(c => String(c.id) === String(centerId)) || cs[0];
    const id = `mock-${++MOCK.seq}`;
    const mdl = mockModel(type, model);
    const s = { id, type, model: mdl, airframe: isPlane(type) ? ({ 'builtin:caymaz': 'caymaz', 'builtin:delta': 'delta' }[mdl.id] || null) : null, center, world: { ...WORLD_DEFAULTS, ...(world || {}) }, state: 'HAZIR', udp_port: 14550 + MOCK.seq - 1, host: location.hostname,
      launch: { ...LAUNCH_DEFAULTS, ...((world || {}).launch || {}), method: type === 'sabit_kanat' ? ((world || {}).launch?.method || 'wheels') : 'wheels', phase: null },
      created_at: new Date().toISOString(), owner: { id: ctx.user?.id, name: ctx.user?.full_name || ctx.user?.username || '—' }, gcs: { connected: false, addr: null, since: null }, sitl: { pid: 0, port: 0, error: null } };
    s.flight = new MockFlight(s);
    MOCK.sessions.set(id, s);
    return s;
  };
  // Kayıt kipi sahte oturumu: SITL/UDP yok; `replay` metası + kareler (mockReplayData) hazır → HAZIR
  const mkReplay = async (logId, world, model) => {
    const log = MOCK_LOGS.find(l => l.id === Number(logId)) || MOCK_LOGS[0];
    const cs = await centers();
    const c = cs[0];
    const data = mockReplayData(log, c);
    const id = `mock-${++MOCK.seq}`;
    const s = { id, mode: 'replay', type: log.type, model: mockModel(log.type, model), center: { id: null, name: log.file_name, lat: data.home.lat, lon: data.home.lon, alt: data.home.alt }, world: { ...WORLD_DEFAULTS, ...(world || {}) },
      state: 'HAZIR', udp_port: null, host: location.hostname, created_at: new Date().toISOString(), owner: { id: ctx.user?.id, name: ctx.user?.full_name || ctx.user?.username || '—' },
      gcs: { connected: false, addr: null, since: null }, sitl: { pid: null, port: null, error: null },
      replay: { log_id: log.id, file_name: log.file_name, size: log.size, progress: 100, frames: data.n, duration_s: data.duration_s, home: data.home, hz: data.hz, takeoff_t: data.takeoff_t, start_utc: data.start_utc, vehicle: data.vehicle, modes: data.modes } };
    s.data = data;
    MOCK.sessions.set(id, s);
    return s;
  };
  const pub = s => { const { flight, data, ...rest } = s; return rest; };
  return {
    mock: true,
    meta: async () => ({ types: TYPES.map(([key, name]) => ({ key, name, binary: isPlane(key) ? 'arduplane' : 'arducopter' })), centers: await centers(), world_defaults: WORLD_DEFAULTS, limits: { max_sessions: 2, max_minutes: 120 }, host: location.hostname,
      replay: { logs_allowed: true, hz: 25, formats: ['.bin', '.log', '.tlog'] }, google3d: { enabled: true } }),
    g3dKey: async () => 'MOCK-GECERSIZ-ANAHTAR',   // sahte kip: Google 400/403 döner → hata yolu ("… prosedürele düşüldü") denenir
    logs: async () => MOCK_LOGS.map(l => ({ ...l })),
    replay: async id => { const s = MOCK.sessions.get(id); if (!s?.data) throw Object.assign(new Error('Kayıt oturumu değil'), { status: 400 }); return s.data; },
    sessions: async () => [...MOCK.sessions.values()].filter(s => s.state !== 'KAPANDI').map(pub),
    session: async id => {
      if (!MOCK.sessions.has(id)) {   // sayfa yenilendi: aynı kimlikle varsayılan bir sahte oturum kur (…r → kayıt kipi)
        const n = Number(String(id).replace('mock-', '').replace(/r$/, '')) || 1; MOCK.seq = Math.max(MOCK.seq, n);
        const s = /r$/.test(String(id)) ? await mkReplay(1, {}) : await mk('multirotor', null, {}); MOCK.sessions.delete(s.id); s.id = id; MOCK.sessions.set(id, s);
      }
      return pub(MOCK.sessions.get(id));
    },
    create: async body => {
      if ([...MOCK.sessions.values()].filter(s => s.state !== 'KAPANDI').length >= 2) throw Object.assign(new Error('Oturum sınırı'), { status: 409 });
      if (body.mode === 'replay') { const s = await mkReplay(body.log_id, body.world, body.model); MOCK.sessions.delete(s.id); s.id = `${s.id}r`; MOCK.sessions.set(s.id, s); return pub(s); }
      return pub(await mk(body.type, body.center_id, body.world, body.model || body.airframe));
    },
    end: async id => { const s = MOCK.sessions.get(id); if (s) { s.state = 'KAPANDI'; s.flight?.end('Kullanıcı bitirdi'); MOCK.sessions.delete(id); } return { ok: true }; },
    cmd: async (id, name, params) => { const s = MOCK.sessions.get(id); if (!s) throw Object.assign(new Error('Oturum yok'), { status: 404 }); if (s.mode === 'replay') { if (name !== 'reset') throw Object.assign(new Error('Kayıtta komut yok'), { status: 400 }); return { ok: true }; } s.flight.cmd(name, params || {}); return { ok: true }; },
    socket: (id, handlers) => {
      const s = MOCK.sessions.get(id);
      if (!s) { handlers.fatal?.('notfound'); return { send() {}, close() {} }; }
      if (s.mode === 'replay') { handlers.status?.('open'); setTimeout(() => { handlers.message?.({ t: 'hello', session: pub(s) }); handlers.message?.({ t: 'event', text: `Kayıt hazır: ${s.replay.frames} kare · ${s.replay.duration_s} sn`, severity: 6 }); }, 0); return { send() {}, close() {} }; }
      return s.flight.attach(handlers, pub(s));
    },
    href: id => `#/drone/sim${id ? `/${id}` : ''}?mock=1`,
  };
}

// Sahte uçuş logu listesi (kayıt kipi) ve 2 dakikalık sahte kare üretici: uçak pistten kalkar, 400 m yarıçapta daire çizer, iner.
const MOCK_LOGS = [
  { id: 1, file_name: '00000012.BIN', ext: 'bin', size: 253034496, uploaded_at: '2026-09-26T09:40:00', takeoff_utc: '2026-09-21T13:24:00Z', start_utc: '2026-09-21T13:01:41Z', aircraft: 'CZ-07', pilot: 'A. Yılmaz', location: 'Akyurt', task_code: 'SG-2026-014', vehicle: 'ArduPlane V4.7.1', type: 'sabit_kanat', flight_s: 120, duration_s: 150, cached: true, status: 'TAMAM' },
  { id: 2, file_name: '20261016T093821-1-4e2a6023.tlog', ext: 'tlog', size: 233827, uploaded_at: '2026-10-16T09:40:00', start_utc: '2026-10-16T06:38:21Z', aircraft: 'Sanal dron', pilot: null, location: null, task_code: null, vehicle: 'ArduCopter', type: 'multirotor', flight_s: 95, duration_s: 120, cached: false, status: 'TAMAM' },
  { id: 3, file_name: '00000009.BIN', ext: 'bin', size: 491417600, uploaded_at: '2026-09-26T10:19:00', takeoff_utc: '2026-09-20T08:12:00Z', aircraft: 'CZ-05', pilot: 'M. Kaya', location: 'Akyurt', task_code: null, vehicle: 'ArduPlane V4.6.0', type: 'sabit_kanat', flight_s: 1860, duration_s: 2400, cached: false, status: 'TAMAM' },
];
function mockReplayData(log, c) {
  const plane = isPlane(log.type), hz = 25, dur = 120, home = { lat: c.lat, lon: c.lon, alt: Number(c.alt) || 0 };
  const fields = ['t', 'lat', 'lon', 'alt_msl', 'alt_rel', 'roll', 'pitch', 'yaw', 'vn', 've', 'vd', 'gs', 'as', 'hdg', 'thr', 'mode', 'armed', 'batt_v', 'batt_pct', 'sats', 'fix', 'rc'];
  const modes = plane ? ['MANUAL', 'TAKEOFF', 'AUTO', 'RTL'] : ['STABILIZE', 'GUIDED', 'LOITER', 'LAND'];
  const frames = [], events = [{ t: 0, text: `${log.vehicle || 'ArduPlane'} (sahte kayıt)`, sev: 6 }, { t: 3, text: 'GPS 1: detected as u-blox at 115200 baud', sev: 6 }, { t: 8, text: 'EKF3 IMU0 is using GPS', sev: 6 }];
  const V = plane ? 22 : 8, R = plane ? 400 : 120, cosLat = Math.cos(home.lat * Math.PI / 180);
  let x = 0, y = 0, z = 0, yaw = 0, roll = 0, pitch = 0, vx = 0, vy = 0, vz = 0, mode = 0, armed = 0, thr = 0, ang = 0, batt = 100;
  let phase = 'ground';
  for (let i = 0; i <= dur * hz; i++) {
    const t = i / hz, dt = 1 / hz;
    if (phase === 'ground' && t >= 10) { phase = 'takeoff'; armed = 1; mode = 1; events.push({ t, text: 'Throttle armed', sev: 6 }, { t, text: `Mode ${modes[1]}`, sev: 6 }); }
    if (phase === 'takeoff') {
      if (plane) { const sp = Math.min(V, Math.hypot(vx, vy) + 4 * dt); vx = Math.sin(yaw) * sp; vy = Math.cos(yaw) * sp; vz = sp > 15 ? 6 : 0; pitch = sp > 15 ? 0.25 : 0; thr = 95; }
      else { vz = 2.5; thr = 65; }
      if (z >= (plane ? 120 : 30)) { phase = 'cruise'; mode = 2; vz = 0; ang = Math.atan2(y, x); events.push({ t, text: `Mode ${modes[2]}`, sev: 6 }, { t, text: 'Reached target altitude', sev: 6 }); }
    } else if (phase === 'cruise') {
      const r0 = Math.hypot(x, y), r = r0 + (R - r0) * Math.min(1, dt * 0.4);
      ang += (V / r) * dt;
      const nx = Math.cos(ang) * r, ny = Math.sin(ang) * r;
      vx = (nx - x) / dt; vy = (ny - y) / dt; x = nx - vx * dt; y = ny - vy * dt;
      vz = ((plane ? 120 : 30) + (plane ? 8 : 2) * Math.sin(t * 0.3) - z) * 0.5;
      yaw = Math.atan2(vx, vy); roll = plane ? Math.atan((V * V) / (r * 9.81)) : 0.06 * Math.sin(t * 0.8); pitch = (plane ? 0.04 : 0) + vz * 0.02; thr = plane ? 55 : 48;
      if (t >= 85) { phase = 'rtl'; mode = 3; events.push({ t, text: `Mode ${modes[3]}`, sev: 6 }); if (plane) events.push({ t: t + 0.2, text: 'Low battery warning (sahte)', sev: 4 }); }
    } else if (phase === 'rtl') {
      const d = Math.hypot(x, y);
      if (d > 3) { const sp = Math.min(V, d); vx = -x / d * sp; vy = -y / d * sp; vz = -Math.min(3, z / Math.max(1, d / V)); yaw = Math.atan2(vx, vy); roll = 0; pitch = -0.05; thr = 40; }
      else { vx = vy = 0; vz = -Math.min(1.5, Math.max(0.3, z * 0.3)); roll = pitch = 0; thr = 25; }
      if (z <= 0.05 && d <= 3) { z = 0; vz = 0; if (armed) { armed = 0; thr = 0; mode = 0; phase = 'ground'; events.push({ t, text: 'Disarming motors', sev: 6 }); } }
    }
    x += vx * dt; y += vy * dt; z = Math.max(0, z + vz * dt);
    if (armed) batt = Math.max(0, batt - dt * 0.03);
    const lat = home.lat + y / 110574, lon = home.lon + x / (111320 * cosLat), gs = Math.hypot(vx, vy);
    const rc = [1500 + Math.round(400 * Math.sin(roll * 2)), 1500 - Math.round(400 * Math.sin(pitch * 2)), 1000 + Math.round(thr * 10), 1500, 1800, 1000, 1000, 1500];
    frames.push([Number(t.toFixed(3)), Number(lat.toFixed(7)), Number(lon.toFixed(7)), Number((home.alt + z).toFixed(2)), Number(z.toFixed(2)), Number(roll.toFixed(4)), Number(pitch.toFixed(4)), Number(yaw.toFixed(4)),
      Number(vy.toFixed(2)), Number(vx.toFixed(2)), Number((-vz).toFixed(2)), Number(gs.toFixed(2)), Number((gs + 2).toFixed(2)), Number((((yaw * 180 / Math.PI) + 360) % 360).toFixed(1)), thr, mode, armed,
      Number((14.2 + 2.6 * batt / 100).toFixed(2)), Math.round(batt), 14, 3, rc]);
  }
  return { v: 1, hz, fields, frames, modes, events, duration_s: dur, home, takeoff_t: 10, start_utc: log.start_utc || null, vehicle: log.vehicle || 'ArduPlane', type: log.type, n: frames.length, source: log.ext === 'tlog' ? 'tlog' : 'bin' };
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
    return { send: obj => { if (obj?.t === 'cmd') this.cmd(obj.name, obj.params || {}); if (obj?.t === 'rc') this.rc = Array.isArray(obj.ch) && obj.ch.some(Boolean) ? obj.ch : null; }, close: () => { this.handlers.delete(handlers); if (!this.handlers.size) { clearInterval(this.timer); this.timer = 0; } } };
  }
  emit(m) { this.handlers.forEach(hh => hh.message?.(m)); }
  event(text, severity = 'info') { this.emit({ t: 'event', text, severity }); }
  launch(phase, extra = {}) { if (this.s.launch) this.s.launch.phase = phase; this.emit({ t: 'launch', method: this.s.launch?.method || 'wheels', phase, ts: Date.now() / 1000, ...extra }); }
  end(reason) { this.emit({ t: 'end', reason }); clearInterval(this.timer); this.timer = 0; }
  cmd(name, p) {
    const S = this.st;
    if (name === 'arm') { S.armed = true; S.auto = false; this.event('Arming motors'); }
    else if (name === 'disarm') { S.armed = false; S.auto = false; S.phase = 'ground'; this.event('Disarming motors'); }
    else if (name === 'mode') { S.mode = p.mode || S.mode; S.auto = false; this.event(`Mode ${S.mode}`); if (S.mode === 'RTL') S.phase = 'rtl'; if (S.mode === 'LAND' || S.mode === 'QLAND') S.phase = 'land'; if ((S.mode === 'AUTO' || S.mode === 'LOITER') && S.armed && S.z > 2) S.phase = 'cruise'; }
    else if (name === 'takeoff') {
      S.targetAlt = Number(p.alt) || S.targetAlt; S.auto = false; if (!S.armed) { S.armed = true; this.event('Arming motors'); } S.mode = this.plane ? 'TAKEOFF' : 'GUIDED'; S.phase = 'takeoff'; this.event(`Takeoff to ${S.targetAlt} m`);
      if (this.s.type === 'sabit_kanat' && S.z < 1) {   // kalkış yöntemi dizisi (§13): armed → launch → released
        S.lt = 0; S.lphase = 'armed'; this.launch('armed');
        const m = this.s.launch?.method;
        if (m !== 'ramp') { S.lphase = 'launch'; this.launch('launch'); }
      }
    }
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
    if (S.auto && S.phase === 'ground' && S.t > 4) { this.cmd('takeoff', { alt: S.targetAlt }); S.auto = false; }
    const V = this.plane ? 22 : 8, R = this.plane ? 450 : 150;
    const hdg = S.yaw;   // yaw: kuzeyden saat yönü
    if (S.phase === 'takeoff' && S.armed) {
      if (this.plane) {
        const sp = Math.hypot(S.vx, S.vy);
        const m = this.s.type === 'sabit_kanat' ? this.s.launch?.method : 'wheels';
        let ns, acc = 4, rot = 15;
        if (S.lphase) S.lt = (S.lt || 0) + dt;
        if (m === 'ramp' && S.lphase) {
          if (S.lphase === 'armed') { if (S.lt >= 1.2) { S.lphase = 'launch'; this.launch('launch', { angle_deg: this.s.launch.angle_deg }); } ns = 0; S.thr = 0; }
          else { acc = 44; rot = 20; ns = Math.min(V, sp + acc * dt); S.thr = 100; if (S.lphase === 'launch' && sp >= 8) { S.lphase = 'released'; this.launch('released', { speed_kmh: Math.round(sp * 36) / 10 }); } }
        } else if (m === 'vehicle' && S.lphase) {
          const rel = (Number(this.s.launch.release_kmh) || 70) / 3.6;
          acc = 2.5; rot = rel; ns = Math.min(V, sp + acc * dt); S.thr = S.lphase === 'released' ? 100 : 0;
          if (S.lphase === 'launch' && sp >= rel * 0.95) { S.lphase = 'released'; this.launch('released', { speed_kmh: Math.round(sp * 36) / 10 }); }
        } else {
          ns = Math.min(V, sp + acc * dt); S.thr = 100;
          if (S.lphase === 'launch' && S.z >= 1) { S.lphase = 'released'; this.launch('released', { speed_kmh: Math.round(sp * 36) / 10 }); }
        }
        S.vx = Math.sin(hdg) * ns; S.vy = Math.cos(hdg) * ns;
        const air = sp > rot;
        S.vz = air ? 7 : 0; S.pitch = air ? 16 * Math.PI / 180 : 0; if (air) S.thr = 85;   // dik tırmanış: merkez çevresindeki düzlük (300 m) bitmeden irtifa alsın
      } else { S.vx = S.vy = 0; S.vz = 2.5; S.thr = 65; S.pitch = 0; }
      if (S.z >= S.targetAlt) { S.phase = 'cruise'; S.lphase = null; S.mode = this.plane ? 'AUTO' : 'LOITER'; S.vz = 0; S.ang = Math.atan2(S.y, S.x); this.event(`Mode ${S.mode}`); this.event('Reached target altitude'); }
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
    } else if (S.armed && this.rc && S.phase === 'ground') {
      // Sanal kumanda (mock): gaz → dikey hız (kopter: 1500 askı), yaw → dönüş, pitch/roll → eğim ve yatay hız
      const n = i => ((Number(this.rc[i]) || 1500) - 1500) / 500;
      S.thr = Math.max(0, Math.min(100, ((Number(this.rc[2]) || 1000) - 1000) / 10));
      S.vz = this.plane ? (S.thr - 50) / 50 * 4 : n(2) * 4;
      S.yaw += n(3) * 1.6 * dt;
      S.roll = n(0) * 0.6; S.pitch = -n(1) * 0.5;
      const sp = this.plane ? 18 : 9, fwd = -S.pitch / 0.5 * sp, side = S.roll / 0.6 * sp;
      S.vx = Math.sin(S.yaw) * fwd + Math.cos(S.yaw) * side; S.vy = Math.cos(S.yaw) * fwd - Math.sin(S.yaw) * side;
      if (S.z <= 0 && S.vz < 0) S.vz = 0;
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
