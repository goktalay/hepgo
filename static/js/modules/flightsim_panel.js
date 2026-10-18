// Uçuş Simülatörü — YERLİ harekât paneli (docs/ucus-simulatoru.md §14). iframe YOK: panel, simülatör sayfasının kendi HTML/JS'idir (ui.js `h()`,
// mevcut HUD stilleri). Kullanıcı kararı: "sistem HTML değil mi? neden komple bir objeye ihtiyaç duyuyorsun; gerekiyorsa aynı görünümde mevcut
// altyapı üzerine bir panel yarat". Önceki şeffaf iframe canlıda (HEPGO koyu teması) bembeyaz çiziliyordu: üst belgede html[data-theme=dark]
// { color-scheme: dark } iframe öğesine miras kalır, GÖKTUNGU iç belgesi color-scheme bildirmez (normal) → Chromium, iframe öğesi ile iç belgenin
// kullanılan renk şeması uyuşmazsa iframe'i OPAK zeminle çizer. Burada iframe olmadığı için kartlar her temada koyu yarı saydamdır.
//
// Görünüm — 3B'nin üstünde yüzen yarı saydam kartlar (.fs-pn-card: rgba(11,14,17,.72), 10 px köşe, ince kenarlık, blur), ayrı zemin yok:
//   sağ üstte sütun (.fs-pn-col, 440 px; <1100 px 360 px): BAŞLIK (ad, mod, ARM, oturum durumu, GPS, MP, hub) · UÇUŞ GÖSTERGESİ (PFD canvas:
//   mavi/kahverengi suni ufuk, pitch merdiveni, roll yayı, sol hız / sağ irtifa bandı, alt yön şeridi, köşe etiketleri) · TELEMETRİ karoları 4×2
//   (İrtifa, Hız, Batarya, GPS / Durum[ARM], Mod[liste], Tip, Komut[Kalkış|Fırlat|Aracı sür / İniş]) · İŞLEMLER (katlanabilir: Kalkış, RTL, İniş,
//   İrtifa, Hedefe git, Ev, Rota seç→Yükle→Başlat/Duraklat/Sürdür/İptal, Sıfırla, Yerleşimi sıfırla); KONSOL kartı alt ortada küçük, katlanabilir.
// Veri/komut yolu — telemetri (PFD/karolar) simülatörün /ws/drone/sim tele'sinden (update(t)); hub durumu, konsol satırları ve KOMUTLAR için
//   bu modül kendi /ws/drone/live soketini açar ({t:'watch', sim_id} → hello/status/console/res; flightsim_hub.SimBridge) ve komutları hub
//   {t:'cmd', rid, bridge_id: -(9000+N), sysid: 1, name, params} ile gönderir (GÖKTUNGU kalkış/rota akışları sunucuda yürür). Simülatöre ÖZGÜ iki
//   komut sim WS yolundan gider (cmdSim): Sıfırla (reset) ve sabit kanat kalkış düzeneği (rampa/araç/tekerlek: takeoff{alt}, §13).
// Davranış — Panel düğmesi / P → kartlar gizli (sade görünüm: eski .fs-hud + alt çubuk komutları); FPV'de kartlar gizli (askeri HUD kalır);
//   yazma izni / hub komut yetkisi yoksa düğmeler pasif; kayıt (replay) ve sahte (mock) kiplerinde hub yoktur → komut kartları gizli, PFD/telemetri
//   çalışır. Sütun ve konsol başlığından sürüklenir (localStorage fs.panel.col / fs.panel.con), katlama fs.panel.fold, açık/kapalı fs.ops.on.
// Dışa: createOpsPanel(stage, opts) → { el, enabled, toggle(v), setFpv(v), update(tele), setState(st), setRoute(points), setGcs(on), log(text, sev, tag), dispose() }
import { api } from '../api.js';
import { confirmDialog, field, h, modal, toast, toastError, t as tr } from '../ui.js';

const KEY_ON = 'fs.ops.on', KEY_COL = 'fs.panel.col', KEY_CON = 'fs.panel.con', KEY_FOLD = 'fs.panel.fold';
const DEG = Math.PI / 180;
const num = (v, d = null) => (v == null || Number.isNaN(Number(v)) ? d : Number(v));
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const wrap180 = a => ((a + 180) % 360 + 360) % 360 - 180;
const pad3 = v => String(Math.round(((v % 360) + 360) % 360)).padStart(3, '0');
const f0 = v => (v == null || Number.isNaN(Number(v)) ? '—' : String(Math.round(Number(v))));
const f1 = v => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(1));
const CARD = { 0: 'N', 90: 'E', 180: 'S', 270: 'W' };
const TYPE_NAME = { multirotor: 'Multikopter', hexarotor: 'Hexakopter', helikopter: 'Helikopter', sabit_kanat: 'Sabit Kanat', vtol: 'VTOL' };
const LAUNCH_BTN = { ramp: 'Fırlat', vehicle: 'Aracı sür', wheels: 'Kalkış' };
const SEV_CLASS = { hata: 'err', uyari: 'warn', basari: 'ok', bilgi: '' };
// GÖKTUNGU kalkış kontrol listesi (kalkis_kontrol.js) — simülatörde zorunlu maddeler; sunucu drone_takeoff_checks'e kaydeder (hub takeoff{kontrol})
const CHECKLIST = [
  ['pervane', 'Pervaneler sağlam, güvenlik alanı boş'], ['batarya', 'Batarya dolu ve sabitlenmiş'], ['gps', 'GPS fix ve yeterli uydu'],
  ['ev', 'Ev konumu doğru'], ['hava', 'Hava koşulları uygun'], ['mod', 'Uçuş modu ve failsafe ayarları kontrol edildi'],
];
const gpsText = fix => (fix >= 6 ? 'RTK' : fix === 5 ? 'RTK FLT' : fix === 4 ? 'DGPS' : fix === 3 ? '3D' : fix === 2 ? '2D' : '—');
const lsGet = (k, d = null) => { try { const v = JSON.parse(localStorage.getItem(k) || 'null'); return v == null ? d : v; } catch { return d; } };
const lsSet = (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch { /* */ } };
const editable = el => el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);

export function createOpsPanel(stage, opts = {}) {
  const { sid, session = {}, type = 'multirotor', modes = [], launch = null, canWrite = false, hub = true, cmdSim = null, onToggle = null, onReset = null } = opts;
  const getSim = opts.getSim || (() => null);
  const bridgeId = session.hub?.bridge_id ?? null;
  let on = (localStorage.getItem(KEY_ON) ?? '1') !== '0';
  let tele = null, hubState = {}, hubOnline = false, hubCan = null, gcs = !!session.gcs?.connected, state = session.state || 'HAZIR', routePts = session.route || [];
  let disposed = false, hubWs = null, hubTimer = 0, hubPing = 0, hubRetry = 0, hubClosed = false, ridSeq = 0;
  const pending = new Map();   // rid → {resolve, timer, name}
  const fold = lsGet(KEY_FOLD, {});
  const isPlane = type === 'sabit_kanat' || type === 'vtol';
  const launchBtnText = () => (tele?.armed && (num(tele.alt_rel, 0) > 2 || (launch && launch.phase && launch.phase !== 'armed')) ? 'İniş' : (LAUNCH_BTN[launch?.method] || 'Kalkış'));
  const canCmd = () => canWrite && hub && hubOnline && hubCan !== false && state === 'HAZIR';

  // ---------- kart iskeleti ----------
  const card = (key, title, body, { extra = null, foldable = true, cls = '' } = {}) => {
    const foldBtn = foldable ? h('button', { class: 'fs-pn-fold', type: 'button', title: tr('Katla / aç'), onclick: e => { e.stopPropagation(); setFold(key, !el.classList.contains('folded')); } }, '▾') : null;
    const head = h('div', { class: 'fs-pn-h' }, h('span', { class: 'fs-pn-title' }, title), extra, h('span', { class: 'spacer' }), foldBtn);
    const el = h('div', { class: `fs-pn-card ${cls}`, 'data-card': key }, head, body);
    if (fold[key]) el.classList.add('folded');
    el._head = head;
    return el;
  };
  const setFold = (key, v) => { const el = root.querySelector(`[data-card="${key}"]`); el?.classList.toggle('folded', v); fold[key] = v; lsSet(KEY_FOLD, fold); if (key === 'pfd' && !v) pfdDirty = true; };

  // --- BAŞLIK kartı: ad · mod · ARM · oturum durumu · GPS · MP · hub ---
  const B = { name: h('b', { class: 'fs-pn-name' }, session.hub?.name || (session.drone ? `${session.drone.code || ''} ${session.drone.name || ''}`.trim() : null) || tr('Simülatör #{n}', { n: sid })),
    mode: h('span', { class: 'badge blue' }, '—'), arm: h('span', { class: 'badge gray' }, 'DISARMED'), st: h('span', { class: 'badge green' }, 'Hazır'),
    gps: h('span', { class: 'badge gray', title: 'GPS' }, 'GPS —'), mp: h('span', { class: 'badge gray', title: tr('Mission Planner (UDP) bağlantısı') }, 'MP'),
    hub: h('span', { class: 'badge gray', title: tr('Harekât hub bağlantısı (/ws/drone/live)') }, 'HUB') };
  const headCard = card('head', '', h('div', { class: 'fs-pn-body fs-pn-badges' }, B.name, B.mode, B.arm, B.st, B.gps, B.mp, hub ? B.hub : null), { foldable: false, cls: 'fs-pn-head' });   // tip TİP karosunda

  // --- PFD kartı ---
  const canvas = h('canvas', { class: 'fs-pn-pfd' });
  const g = canvas.getContext('2d');
  const pfdCard = card('pfd', 'UÇUŞ GÖSTERGESİ', h('div', { class: 'fs-pn-body fs-pn-pfd-wrap' }, canvas));

  // --- TELEMETRİ karoları 4×2 ---
  const tile = (key, label, { click = null, title = null } = {}) => {
    const v = h('b', null, '—'), sub = h('i', null, '');
    const el = h('div', { class: `fs-pn-tile ${click ? 'act' : ''}`, 'data-tile': key, role: click ? 'button' : null, tabindex: click ? 0 : null, title }, h('small', null, label), v, sub);
    if (click) { el.addEventListener('click', e => { e.stopPropagation(); if (el.classList.contains('off')) return; click(el); }); el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.click(); } }); }
    return Object.assign(el, { v, sub });
  };
  const T = {
    alt: tile('alt', 'İRTİFA'), spd: tile('spd', 'HIZ'), bat: tile('bat', 'BATARYA'), gps: tile('gps', 'GPS'),
    arm: tile('arm', 'DURUM', { click: () => armToggle(), title: tr('ARM / DISARM (onaylı)') }),
    mode: tile('mode', 'MOD', { click: el => modeMenu(el), title: tr('Uçuş modu seç') }),
    type: tile('type', 'TİP'),
    cmd: tile('cmd', 'KOMUT', { click: () => (launchBtnText() === 'İniş' ? land() : takeoffDialog()), title: tr('Kalkış / iniş') }),
  };
  T.type.v.textContent = tr(TYPE_NAME[type] || type); T.type.sub.textContent = session.sitl || session.mode === 'replay' ? (session.mode === 'replay' ? tr('Kayıt') : 'SITL') : '';
  const tilesCard = card('tiles', 'TELEMETRİ', h('div', { class: 'fs-pn-tiles' }, T.alt, T.spd, T.bat, T.gps, T.arm, T.mode, T.type, T.cmd));

  // --- İŞLEMLER kartı ---
  const btn = (label, fn, cls = '') => h('button', { class: `btn sm ${cls}`, type: 'button', onclick: fn }, label);
  const routeSel = h('select', { class: 'input sm fs-pn-route' }, h('option', { value: '' }, 'Rota seçin…'));
  const routeInfo = h('span', { class: 'small muted fs-pn-route-info' }, '');
  const altInp = h('input', { class: 'input sm fs-pn-num', type: 'number', min: 1, max: 500, value: isPlane ? 80 : 30, title: tr('Hedef irtifa (m, AGL)') });
  const gotoBtn = btn('Hedefe git', () => gotoDialog());
  const lbl = s => h('span', { class: 'fs-pn-lbl' }, s);
  const opsBody = h('div', { class: 'fs-pn-body fs-pn-ops-body' },
    h('div', { class: 'fs-pn-row' }, lbl('Uçuş'), btn(launchBtnText(), () => takeoffDialog(), 'primary fs-pn-takeoff'), btn('İniş', () => land()), btn('RTL', () => hubCmd('rtl')), btn('Ev konumu', () => setHome())),
    h('div', { class: 'fs-pn-row' }, lbl('Hedef'), h('span', { class: 'fs-pn-grp' }, altInp, btn('İrtifa', () => hubCmd('altitude_change', { alt_rel_m: Number(altInp.value) || 30 }))), gotoBtn),
    h('div', { class: 'fs-pn-row fs-pn-route-row' }, lbl('Rota'), routeSel, btn('Yükle', () => routeUpload(), 'fs-pn-route-up'), btn('Başlat', () => hubCmd('mission_start', { rota: routeName() }), 'fs-pn-route-start')),
    h('div', { class: 'fs-pn-row' }, lbl(''), btn('Duraklat', () => hubCmd('mission_pause', { davranis: 'bekle' })), btn('Sürdür', () => hubCmd('mission_resume', {})), btn('İptal', () => hubCmd('mission_cancel', { rota: routeName() }), 'danger'), routeInfo),
    h('div', { class: 'fs-pn-row' }, lbl('Sim'), btn('↺ Sıfırla', () => { onReset ? onReset() : cmdSim?.('reset'); }, 'fs-pn-free'), btn('Yerleşimi sıfırla', () => resetLayout(), 'fs-pn-free'), h('span', { class: 'spacer' }), h('span', { class: 'small muted fs-pn-perm' }, '')));
  const opsCard = card('ops', 'İŞLEMLER', opsBody);

  // --- KONSOL kartı (alt orta) ---
  const conBody = h('div', { class: 'fs-pn-con-body mono' });
  const conCard = card('con', 'KONSOL', conBody, { cls: 'fs-pn-con', extra: h('button', { class: 'fs-pn-clear', type: 'button', title: tr('Konsolu temizle'), onclick: e => { e.stopPropagation(); conBody.replaceChildren(); } }, '⌫') });

  const col = h('div', { class: 'fs-pn-col' }, headCard, pfdCard, tilesCard, hub ? opsCard : null);
  const root = h('div', { class: 'fs-pn' }, col, conCard);
  root.id = 'fs-pn';
  stage.append(root);
  stage.classList.add('fs-ops-host');
  if (!hub) { stage.classList.add('fs-pn-nohub'); for (const k of ['arm', 'mode', 'cmd']) T[k].classList.add('off'); }

  // ---------- konsol satırları ----------
  const log = (text, sev = 'bilgi', tag = 'SİM', ts = null) => {
    if (disposed || !text) return;
    const d = ts ? new Date(ts * 1000) : new Date();
    const stamp = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
    const cls = SEV_CLASS[sev] ?? (/err|crit|alert|emerg/.test(String(sev)) || (typeof sev === 'number' && sev <= 3) ? 'err' : /warn/.test(String(sev)) || sev === 4 ? 'warn' : '');
    const atBottom = conBody.scrollTop + conBody.clientHeight >= conBody.scrollHeight - 6;
    conBody.append(h('div', { class: `fs-pn-line ${cls}` }, h('span', { class: 't' }, stamp), h('span', { class: 'tag' }, tag), h('span', { class: 'x' }, text)));
    while (conBody.children.length > 200) conBody.firstChild.remove();
    if (atBottom) conBody.scrollTop = conBody.scrollHeight;
  };

  // ---------- hub soketi (/ws/drone/live, watch sim_id) ----------
  const hubSend = obj => { if (hubWs && hubWs.readyState === 1) hubWs.send(JSON.stringify(obj)); };
  const setHubBadge = (tone, text, title) => { B.hub.className = `badge ${tone}`; B.hub.textContent = text; if (title) B.hub.title = title; };
  const openHub = () => {
    if (hubClosed || disposed) return;
    const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/drone/live`;
    try { hubWs = new WebSocket(url); } catch (err) { setHubBadge('red', 'HUB', err.message); return; }
    setHubBadge('yellow', 'HUB…', tr('Harekât hub bağlantısı kuruluyor'));
    hubWs.onopen = () => { hubRetry = 0; hubSend({ t: 'watch', sim_id: Number(sid) }); hubPing = setInterval(() => hubSend({ t: 'ping' }), 10000); };
    hubWs.onmessage = e => { let m; try { m = JSON.parse(e.data); } catch { return; } onHub(m); };
    hubWs.onclose = ev => {
      clearInterval(hubPing); hubOnline = false; applyPerm();
      for (const [rid, p] of pending) { clearTimeout(p.timer); p.resolve({ ok: false, error: tr('Hub bağlantısı kapandı') }); pending.delete(rid); }
      if (hubClosed || disposed) return;
      setHubBadge(ev.code === 4403 ? 'red' : 'yellow', 'HUB', ev.code === 4403 ? tr('Harekât hub yetkisi yok') : tr('Hub bağlantısı koptu; yeniden deneniyor'));
      if (ev.code === 4403) return;
      hubTimer = setTimeout(openHub, Math.min(10000, 500 * 2 ** Math.min(hubRetry++, 5)));
    };
    hubWs.onerror = () => { /* onclose yeniden bağlanır */ };
  };
  const onHub = m => {
    if (m.t === 'hello') {
      const b = (m.bridges || []).find(x => x.bridge_id === bridgeId || x.sim_id === Number(sid));
      hubOnline = !!b;
      hubCan = m.me ? m.me.can_command !== false : null;
      if (b?.drones) { const d0 = b.drones['1'] || Object.values(b.drones)[0]; if (d0) hubState = { ...hubState, ...d0 }; }
      setHubBadge(hubOnline ? 'green' : 'yellow', 'HUB', hubOnline ? tr('Harekât hub bağlı · köprü {id}', { id: b.bridge_id }) : tr('Oturum köprüsü hub\'da yok'));
      applyPerm(); return;
    }
    if (m.t === 'status') { if (m.bridge_id === bridgeId) { hubState = m.state || hubState; drawTiles(); } return; }
    if (m.t === 'console') { if (m.bridge_id !== bridgeId || m.tag === 'STATUS') return; log(m.repeat > 1 ? `${m.text} ×${m.repeat}` : m.text, m.sev, m.tag, m.ts); return; }   // STATUSTEXT satırları sim WS 'event' olarak zaten gelir (tekrar yok)
    if (m.t === 'bridge') { if (m.bridge_id === bridgeId) { hubOnline = !!m.online; setHubBadge(hubOnline ? 'green' : 'red', 'HUB', hubOnline ? tr('Harekât hub bağlı') : tr('Oturum köprüsü çevrimdışı')); applyPerm(); } return; }
    if (m.t === 'res') { const p = pending.get(m.rid); if (p) { clearTimeout(p.timer); pending.delete(m.rid); p.resolve(m); } return; }
    if (m.t === 'error') { log(m.error || 'hata', 'hata', 'HUB'); }
  };
  // Komut: hub cmd{rid, bridge_id, sysid, name, params} → res; zaman aşımı hepgo_ws.js ile aynı (bileşik komutlar uzun)
  const hubCmd = (name, params = {}, { quiet = false } = {}) => new Promise(resolve => {
    if (!canCmd()) { toast(canWrite ? tr('Komut için hub bağlantısı ve yetki gerekir') : tr('Komut için Uçuş Simülatörü yazma izni gerekir'), 'err'); return resolve({ ok: false, error: 'yetki' }); }
    const rid = `p${++ridSeq}-${Date.now().toString(36)}`;
    const sn = /^(mission_upload|mission_download|mission_start)$/.test(name) ? 65 : /^mission_(pause|resume|cancel|resume_at)$|^altitude_change$/.test(name) ? 35 : 12;
    const timer = setTimeout(() => { pending.delete(rid); resolve({ ok: false, error: tr('yanıt alınamadı ({n} sn zaman aşımı)', { n: sn }) }); }, sn * 1000);
    pending.set(rid, { resolve, timer, name });
    hubSend({ t: 'cmd', rid, bridge_id: bridgeId, sysid: 1, name, params });
  }).then(r => {
    if (!r.ok && r.error !== 'yetki') { log(`${name}: ${r.error}`, 'hata', 'KOMUT'); if (!quiet) toast(`${name}: ${r.error}`, 'err'); }
    return r;
  });

  // ---------- komut diyalogları ----------
  const armToggle = async () => {
    if (!canCmd()) return hubCmd('arm');
    if (tele?.armed) { if (await confirmDialog('DISARM', tr('Motorlar durdurulsun mu? Havadaysa dron düşer.'), { okLabel: 'DISARM', danger: true })) hubCmd('disarm'); return; }
    const force = h('input', { type: 'checkbox' });
    modal({ title: 'ARM', body: h('div', null, h('p', null, tr('Motorlar ARM edilsin mi? Pervanelerin çevresi boş olmalı.')), h('label', { class: 'check' }, force, ' ', tr('Zorla (pre-arm denetimlerini atla)'))),
      actions: [{ label: 'Vazgeç' }, { label: 'ARM', class: 'danger', onClick: () => { hubCmd('arm', force.checked ? { force: true } : {}); } }] });
  };
  let menuEl = null;
  // Mod menüsü panel KÖKÜNE eklenir (karonun içine değil): sütun overflow:auto olduğundan karo içindeki absolute menü sütunun kaydırma
  // yüksekliğini büyütür, kapanınca içerik kayar (mousedown/mouseup farklı öğelere düşer); tıklama karoya kabarmasın (yeniden açılır)
  const closeMenu = () => { menuEl?.remove(); menuEl = null; document.removeEventListener('pointerdown', onDocDown, true); };
  const onDocDown = e => { if (menuEl && !menuEl.contains(e.target)) closeMenu(); };
  const modeMenu = anchor => {
    if (menuEl) return closeMenu();
    const r = anchor.getBoundingClientRect(), s = stage.getBoundingClientRect();
    menuEl = h('div', { class: 'fs-pn-menu', style: { left: `${Math.round(r.left - s.left)}px`, top: `${Math.round(r.bottom - s.top + 4)}px`, minWidth: `${Math.round(r.width)}px` }, onclick: e => e.stopPropagation() },
      modes.map(m => h('button', { type: 'button', class: `fs-pn-menu-it ${tele?.mode === m ? 'on' : ''}`, onclick: e => { e.stopPropagation(); closeMenu(); hubCmd('set_mode', { mode: m }); } }, m)));
    root.append(menuEl);
    document.addEventListener('pointerdown', onDocDown, true);
  };
  const takeoffDialog = () => {
    if (!canCmd()) { hubCmd('takeoff'); return; }
    const alt = h('input', { class: 'input', type: 'number', min: 1, max: 500, value: Number(altInp.value) || (isPlane ? 80 : 30) });
    const boxes = CHECKLIST.map(([k, q]) => ({ k, q, cb: h('input', { type: 'checkbox' }) }));
    const label = LAUNCH_BTN[launch?.method] || 'Kalkış';
    const hint = launch?.method === 'ramp' ? tr('Uçak TAKEOFF moduna alınır ve ARM edilir; 1 sn sonra pnömatik rampa kızağı {a}° açıyla fırlatır (SITL mancınık tetiği).', { a: Math.round(launch.angle_deg) })
      : launch?.method === 'vehicle' ? tr('Uçak TAKEOFF moduna alınır ve ARM edilir; pickup pist boyunca hızlanır, {k} km/h yer hızında uçak bırakılır.', { k: Math.round(launch.release_kmh) })
      : isPlane ? tr('ArduPlane yöntemi: TKOFF_ALT = hedef, TAKEOFF modu, ARM; uçak pist boyunca hızlanır.') : tr('GÖKTUNGU akışı: GUIDED → ARM → NAV_TAKEOFF; dron hedef irtifaya yükselir.');
    const all = h('button', { class: 'btn sm', type: 'button', onclick: () => boxes.forEach(b => { b.cb.checked = true; }) }, 'Hepsini onayla');
    modal({ title: label, body: h('div', null, field('Hedef irtifa (m, AGL)', alt, hint),
      h('div', { class: 'fs-pn-check' }, h('div', { class: 'small muted' }, tr('Kalkış kontrol listesi (zorunlu maddeler; sunucuda kayıt altına alınır)')), boxes.map(b => h('label', { class: 'check' }, b.cb, ' ', b.q)), all)),
      actions: [{ label: 'Vazgeç' }, { label, class: 'primary', onClick: () => {
        const eksik = boxes.filter(b => !b.cb.checked).length;
        if (eksik) { toast(tr('{n} zorunlu madde onaylanmadı', { n: eksik }), 'err'); return true; }
        const a = clamp(Number(alt.value) || 30, 1, 500); altInp.value = a;
        const kontrol = boxes.map((b, i) => ({ sira: i, anahtar: b.k, soru: b.q, grup: 'sim', cevap: true, zorunlu: true, kaynak: 'flightsim_panel' }));
        if (launch && cmdSim) { log(tr('Kalkış kontrol listesi onaylandı ({n} madde) · {l} {a} m', { n: kontrol.length, l: label, a }), 'bilgi', 'KOMUT'); cmdSim('takeoff', { alt: a }); }   // §13 fırlatma düzeneği sim yolundan
        else hubCmd('takeoff', { alt_rel_m: a, kontrol });
      } }] });
  };
  const land = () => hubCmd('land');
  const setHome = async () => { if (await confirmDialog('Ev konumu', tr('Ev (HOME) konumu dronun şu anki konumuna ayarlansın mı?'), { okLabel: 'Ayarla' })) hubCmd('set_home', {}); };
  const gotoDialog = () => {
    if (!canCmd()) { hubCmd('goto'); return; }
    const lat = h('input', { class: 'input mono', value: tele?.lat != null ? Number(tele.lat).toFixed(6) : '' }), lon = h('input', { class: 'input mono', value: tele?.lon != null ? Number(tele.lon).toFixed(6) : '' });
    const alt = h('input', { class: 'input', type: 'number', min: 1, max: 500, value: Math.max(5, Math.round(num(tele?.alt_rel, 0)) || Number(altInp.value) || 30) });
    modal({ title: 'Hedefe git', body: h('div', null, field('Enlem', lat), field('Boylam', lon), field('İrtifa (m, AGL)', alt, tr('GUIDED modda belirtilen konuma gider (sabit kanatta GUIDED hedef noktası).'))),
      actions: [{ label: 'Vazgeç' }, { label: 'Git', class: 'primary', onClick: () => { const la = Number(lat.value), lo = Number(lon.value); if (!Number.isFinite(la) || !Number.isFinite(lo)) { toast(tr('Geçersiz koordinat'), 'err'); return true; } hubCmd('goto', { lat: la, lon: lo, alt_rel_m: Number(alt.value) || 30 }); } }] });
  };

  // ---------- rotalar (Dron Yönetimi › Rotalar) ----------
  let routes = [];
  const routeName = () => routes.find(r => String(r.id) === routeSel.value)?.name || '';
  const loadRoutes = async () => {
    if (!hub) return;
    try { routes = await api.get('/api/drone/routes'); } catch { routes = []; }
    const cid = session.center?.id;
    routes = routes.filter(r => r.active !== 0 && r.active !== false).sort((a, b) => (a.center_id === cid ? -1 : 0) - (b.center_id === cid ? -1 : 0));
    routeSel.replaceChildren(h('option', { value: '' }, routes.length ? tr('Rota seçin…') : tr('Kayıtlı rota yok')), ...routes.map(r => h('option', { value: r.id }, `${r.name}${r.wp_count != null ? ` · ${r.wp_count} ${tr('nokta')}` : ''}${r.center_name && r.center_id !== cid ? ` (${r.center_name})` : ''}`)));
    if (!routeSel.value && routes.length && routes[0].center_id === cid) routeSel.value = String(routes[0].id);
  };
  const routeUpload = async () => {
    const rid = routeSel.value;
    if (!rid) { toast(tr('Önce bir rota seçin'), 'err'); return; }
    if (!canCmd()) { hubCmd('mission_upload'); return; }
    let ms;
    try { ms = await api.get(`/api/drone/routes/${encodeURIComponent(rid)}/mission`); } catch (err) { toastError(err); return; }
    log(tr('Rota yükleniyor: {r} ({n} öğe)', { r: ms.name || routeName(), n: (ms.items || []).length }), 'bilgi', 'ROTA');
    const r = await hubCmd('mission_upload', { items: ms.items || [], cruise_speed: ms.cruise_speed });
    if (r.ok) toast(tr('Rota yüklendi: {r}', { r: ms.name || routeName() }));
  };
  const drawRoute = () => { routeInfo.textContent = routePts.length ? tr('SITL\'de {n} rota noktası', { n: routePts.length }) + (hubState.mission_seq != null && tele?.mode === 'AUTO' ? ` · WP ${hubState.mission_seq}` : '') : tr('SITL\'de görev yok'); };

  // ---------- yetki / görünürlük ----------
  const applyPerm = () => {
    const ok = canCmd();
    root.querySelectorAll('.fs-pn-ops-body button:not(.fs-pn-free), .fs-pn-ops-body select, .fs-pn-ops-body input').forEach(b => { b.disabled = !ok; });
    root.querySelectorAll('.fs-pn-ops-body .fs-pn-free').forEach(b => { b.disabled = !canWrite; });
    for (const k of ['arm', 'mode', 'cmd']) T[k].classList.toggle('off', !ok);
    const perm = root.querySelector('.fs-pn-perm');
    if (perm) perm.textContent = ok ? '' : !canWrite ? tr('Komutlar için yazma izni gerekir') : !hubOnline ? tr('Hub bağlantısı bekleniyor') : hubCan === false ? tr('Hub komut yetkisi yok') : state !== 'HAZIR' ? tr('Oturum hazır değil') : '';
  };

  // ---------- veri güncelleme ----------
  let pfdDirty = false, raf = 0, tilesAt = 0, lastMode = null;
  const update = t => {
    if (disposed || !t) return;
    tele = t; pfdDirty = true;
    if (!raf && on && !stage.classList.contains('fs-fpv')) raf = requestAnimationFrame(frame);
    const now = performance.now();
    if (now - tilesAt > 100) { tilesAt = now; drawTiles(); }
  };
  const drawTiles = () => {
    const t = tele || {};
    B.mode.textContent = t.mode || hubState.mode || '—';
    const armed = !!t.armed;
    B.arm.textContent = armed ? 'ARMED' : 'DISARMED'; B.arm.className = `badge ${armed ? 'red' : 'gray'}`;
    B.gps.textContent = `GPS ${gpsText(t.gps_fix)} · ${f0(t.sats)}`; B.gps.className = `badge ${t.gps_fix >= 3 ? 'green' : 'gray'}`;
    B.mp.className = `badge ${gcs ? 'green' : 'gray'}`; B.mp.title = gcs ? tr('Mission Planner bağlı') : tr('Mission Planner bekleniyor');
    T.alt.v.textContent = f1(t.alt_rel); T.alt.sub.textContent = `MSL ${f0(t.alt_msl)} m`;
    T.spd.v.textContent = f1(t.groundspeed); T.spd.sub.textContent = tr('hava {v} m/s', { v: f1(t.airspeed) });
    const bv = num(t.batt_v), bp = num(t.batt_pct);
    T.bat.v.textContent = bp != null ? `%${f0(bp)}` : '—'; T.bat.sub.textContent = bv != null && bv > 0 ? `${bv.toFixed(2)} V` : '—'; T.bat.classList.toggle('warn', bp != null && bp < 25);
    T.gps.v.textContent = gpsText(t.gps_fix); T.gps.sub.textContent = tr('{n} uydu', { n: f0(t.sats) });
    T.arm.v.textContent = armed ? 'ARM' : 'DISARM'; T.arm.classList.toggle('armed', armed); T.arm.sub.textContent = hubState.prearm?.length && !armed ? tr('PreArm uyarısı') : armed ? tr('uçuşta') : tr('hazır');
    T.mode.v.textContent = t.mode || '—'; T.mode.sub.textContent = tr('değiştir');
    const cmdTxt = launchBtnText();
    T.cmd.v.textContent = tr(cmdTxt); T.cmd.sub.textContent = cmdTxt === 'İniş' ? 'LAND' : (launch ? tr('düzenek') : 'TAKEOFF');
    const tk = root.querySelector('.fs-pn-takeoff'); if (tk && tk.textContent !== tr(cmdTxt)) tk.textContent = tr(cmdTxt);
    if (t.mode !== lastMode) { lastMode = t.mode; drawRoute(); }
  };
  const frame = () => {
    raf = 0;
    if (disposed || !on) return;
    if (pfdDirty && !pfdCard.classList.contains('folded')) { pfdDirty = false; drawPfd(); }
  };

  // ---------- PFD çizimi (GÖKTUNGU benzeri: mavi gök / kahverengi yer) ----------
  let W = 0, H = 0, dpr = 1;
  const resizePfd = () => {   // kartlar gizliyken (P / FPV / katlı) tuval ölçüsüzdür → çizme (negatif yarıçap hatası)
    const w = canvas.clientWidth || 0, hh = Math.round(w * 0.47);
    if (w < 40 || hh < 20) return false;
    dpr = Math.min(devicePixelRatio || 1, 2);
    if (w === W && hh === H && canvas.width === Math.round(w * dpr)) return true;
    W = w; H = hh; canvas.style.height = `${H}px`; canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); pfdDirty = true;
    return true;
  };
  const txt = (s, x, y, { px = 11, align = 'left', base = 'middle', color = '#f1f5f9', bold = false } = {}) => {
    g.font = `${bold ? '700 ' : ''}${px}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`; g.textAlign = align; g.textBaseline = base;
    g.lineWidth = 3; g.strokeStyle = 'rgba(0,0,0,.6)'; g.lineJoin = 'round'; g.strokeText(s, x, y); g.fillStyle = color; g.fillText(s, x, y);
  };
  const line = (x1, y1, x2, y2, color = '#f1f5f9', w = 1.2) => { g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.lineWidth = w; g.strokeStyle = color; g.stroke(); };
  function drawPfd() {
    if (!resizePfd()) { pfdDirty = true; return; }
    const t = tele || {};
    const pose = getSim()?.getPose?.() || null;
    const roll = num(pose?.roll, num(t.roll, 0)), pitch = num(pose?.pitch, num(t.pitch, 0)), pitchDeg = pitch / DEG;
    const yawRad = num(pose?.yaw, num(t.yaw, null));
    const hdg = num(t.heading, yawRad != null ? ((yawRad / DEG) + 360) % 360 : 0);
    const gs = num(t.groundspeed, 0), air = num(t.airspeed, gs), agl = num(t.alt_rel, 0), msl = num(t.alt_msl, null), climb = num(t.climb, t.vd != null ? -t.vd : 0);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    const bandW = Math.round(W * 0.14), hsH = 22, cx = W / 2, cy = (H - hsH) / 2, ppd = (H - hsH) / 50;   // ±25° görünür
    const ax = bandW, aw = W - 2 * bandW, ah = H - hsH;   // ufuk alanı
    // --- suni ufuk ---
    g.save(); g.beginPath(); g.rect(ax, 0, aw, ah); g.clip();
    g.translate(cx, cy); g.rotate(roll);   // ArduPilot roll sağa pozitif → ufuk ekranda sola yükselir (flightsim_hud ile aynı yön)
    const hy = pitchDeg * ppd, R = Math.hypot(W, H);
    const sky = g.createLinearGradient(0, hy - R, 0, hy); sky.addColorStop(0, '#1d4ed8'); sky.addColorStop(1, '#60a5fa');
    g.fillStyle = sky; g.fillRect(-R, hy - R, 2 * R, R);
    const gnd = g.createLinearGradient(0, hy, 0, hy + R); gnd.addColorStop(0, '#9a6b3a'); gnd.addColorStop(1, '#4a2f14');
    g.fillStyle = gnd; g.fillRect(-R, hy, 2 * R, R);
    line(-R, hy, R, hy, '#ffffff', 1.6);
    for (let L = -90; L <= 90; L += 5) {
      if (L === 0) continue;
      const y = (pitchDeg - L) * ppd;
      if (Math.abs(y) > ah / 2 + 10) continue;
      const major = L % 10 === 0, half = major ? 34 : 16;
      line(-half, y, half, y, 'rgba(255,255,255,.9)', major ? 1.4 : 1);
      if (major) { txt(String(Math.abs(L)), -half - 6, y, { align: 'right', px: 10 }); txt(String(Math.abs(L)), half + 6, y, { align: 'left', px: 10 }); }
    }
    g.restore();
    // roll yayı + işaretçi
    const rr = ah * 0.42;
    g.save(); g.translate(cx, cy);
    g.beginPath(); g.arc(0, 0, rr, -Math.PI / 2 - 60 * DEG, -Math.PI / 2 + 60 * DEG); g.lineWidth = 1.2; g.strokeStyle = 'rgba(255,255,255,.85)'; g.stroke();
    for (const a of [-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60]) { const ang = -Math.PI / 2 + a * DEG, len = a === 0 ? 10 : a % 30 === 0 ? 8 : 5; line(Math.cos(ang) * rr, Math.sin(ang) * rr, Math.cos(ang) * (rr + len), Math.sin(ang) * (rr + len), 'rgba(255,255,255,.85)', a === 0 ? 2 : 1); }
    const ra = -Math.PI / 2 - clamp(roll / DEG, -60, 60) * DEG;
    g.beginPath(); g.moveTo(Math.cos(ra) * (rr - 2), Math.sin(ra) * (rr - 2)); g.lineTo(Math.cos(ra - 4 * DEG) * (rr - 12), Math.sin(ra - 4 * DEG) * (rr - 12)); g.lineTo(Math.cos(ra + 4 * DEG) * (rr - 12), Math.sin(ra + 4 * DEG) * (rr - 12)); g.closePath(); g.fillStyle = '#facc15'; g.fill();
    // uçak sembolü (sabit, sarı)
    g.strokeStyle = '#facc15'; g.lineWidth = 2.5; g.beginPath(); g.moveTo(-46, 0); g.lineTo(-16, 0); g.lineTo(-16, 8); g.moveTo(46, 0); g.lineTo(16, 0); g.lineTo(16, 8); g.stroke();
    g.fillStyle = '#facc15'; g.fillRect(-2, -2, 4, 4);
    g.restore();
    // --- sol: hız bandı (yer hızı) ---
    const bTop = 8, bBot = ah - 8, bh = bBot - bTop, pps = bh / 30;   // ±15 m/s
    g.fillStyle = 'rgba(0,0,0,.35)'; g.fillRect(0, 0, bandW, ah);
    g.save(); g.beginPath(); g.rect(0, bTop, bandW, bh); g.clip();
    for (let v = Math.max(0, Math.floor((gs - 16) / 2) * 2); v <= gs + 16; v += 2) { const y = cy - (v - gs) * pps, maj = v % 10 === 0; line(bandW, y, bandW - (maj ? 10 : 5), y, 'rgba(255,255,255,.8)', 1); if (maj) txt(String(v), bandW - 13, y, { align: 'right', px: 10 }); }
    g.restore();
    g.fillStyle = 'rgba(0,0,0,.8)'; g.fillRect(2, cy - 12, bandW - 6, 24); g.strokeStyle = '#f1f5f9'; g.lineWidth = 1; g.strokeRect(2.5, cy - 11.5, bandW - 6, 23);
    txt(gs.toFixed(gs < 10 ? 1 : 0), bandW - 8, cy, { align: 'right', px: 15, bold: true });
    txt('GS m/s', 4, 9, { px: 9, color: '#cbd5e1' });
    txt(`IAS ${air.toFixed(air < 10 ? 1 : 0)}`, 4, ah - 9, { px: 9.5, color: '#cbd5e1' });
    // --- sağ: irtifa bandı (AGL) + dikey hız ---
    const rx = W - bandW, ppm = bh / 60;   // ±30 m
    g.fillStyle = 'rgba(0,0,0,.35)'; g.fillRect(rx, 0, bandW, ah);
    g.save(); g.beginPath(); g.rect(rx, bTop, bandW, bh); g.clip();
    for (let v = Math.floor((agl - 32) / 5) * 5; v <= agl + 32; v += 5) { const y = cy - (v - agl) * ppm, maj = v % 10 === 0; line(rx, y, rx + (maj ? 10 : 5), y, 'rgba(255,255,255,.8)', 1); if (maj) txt(String(v), rx + 13, y, { align: 'left', px: 10 }); }
    g.restore();
    g.fillStyle = 'rgba(0,0,0,.8)'; g.fillRect(rx + 4, cy - 12, bandW - 6, 24); g.strokeStyle = '#f1f5f9'; g.strokeRect(rx + 3.5, cy - 11.5, bandW - 6, 23);
    txt(agl.toFixed(agl < 10 ? 1 : 0), rx + 8, cy, { align: 'left', px: 15, bold: true });
    txt('AGL m', W - 4, 9, { align: 'right', px: 9, color: '#cbd5e1' });
    txt(msl != null ? `MSL ${msl.toFixed(0)}` : '', W - 4, ah - 9, { align: 'right', px: 9.5, color: '#cbd5e1' });
    txt(`${climb > 0.05 ? '+' : ''}${climb.toFixed(1)}`, W - 4, cy + 22, { align: 'right', px: 10, color: climb < -3 ? '#fbbf24' : '#cbd5e1' });
    // --- alt: yön şeridi ---
    const hsY = ah, hpd = aw / 90;   // ±45°
    g.fillStyle = 'rgba(0,0,0,.6)'; g.fillRect(0, hsY, W, hsH);
    g.save(); g.beginPath(); g.rect(ax, hsY, aw, hsH); g.clip();
    for (let d = Math.floor((hdg - 50) / 5) * 5; d <= hdg + 50; d += 5) {
      const x = cx + wrap180(d - hdg) * hpd, maj = d % 10 === 0;
      line(x, hsY, x, hsY + (maj ? 7 : 4), 'rgba(255,255,255,.85)', 1);
      if (d % 30 === 0) { const n = ((d % 360) + 360) % 360; txt(CARD[n] || String(n / 10).padStart(2, '0'), x, hsY + 15, { align: 'center', px: 10, bold: !!CARD[n] }); }
    }
    // ev yönü
    if (t.home && t.home.lat != null && t.lat != null) {
      const dLat = (t.home.lat - t.lat) * 110574, dLon = (t.home.lon - t.lon) * 111320 * Math.cos(t.lat * DEG);
      const brg = (Math.atan2(dLon, dLat) / DEG + 360) % 360, rel = wrap180(brg - hdg), hx = cx + clamp(rel, -44, 44) * hpd;
      g.beginPath(); g.moveTo(hx, hsY + 3); g.lineTo(hx - 5, hsY + hsH - 3); g.lineTo(hx + 5, hsY + hsH - 3); g.closePath(); g.fillStyle = Math.abs(rel) > 44 ? 'rgba(74,222,128,.35)' : '#4ade80'; g.fill();
    }
    g.restore();
    g.beginPath(); g.moveTo(cx, hsY); g.lineTo(cx - 5, hsY + 8); g.lineTo(cx + 5, hsY + 8); g.closePath(); g.fillStyle = '#facc15'; g.fill();
    g.fillStyle = 'rgba(0,0,0,.85)'; g.fillRect(cx - 20, hsY + 2, 40, hsH - 4); txt(pad3(hdg), cx, hsY + hsH / 2, { align: 'center', px: 11, bold: true });
    // --- köşe etiketleri: mod / ARM / GPS / batarya ---
    txt(t.mode || '—', ax + 6, 10, { px: 11, bold: true, color: '#e2e8f0' });
    txt(t.armed ? 'ARMED' : 'DISARMED', rx - 6, 10, { align: 'right', px: 11, bold: true, color: t.armed ? '#f87171' : '#cbd5e1' });
    txt(`GPS ${gpsText(t.gps_fix)} ${t.sats != null ? t.sats + ' SAT' : ''}`, ax + 6, ah - 10, { px: 9.5, color: '#e2e8f0' });
    const bp = num(t.batt_pct);
    txt(`BAT ${t.batt_v != null && Number(t.batt_v) > 0 ? Number(t.batt_v).toFixed(1) + 'V ' : ''}${bp != null ? bp.toFixed(0) + '%' : '—'}`, rx - 6, ah - 10, { align: 'right', px: 9.5, color: bp != null && bp < 25 ? '#f87171' : '#e2e8f0' });
    if (t.mode === 'AUTO' && hubState.mission_count) txt(`WP ${hubState.mission_seq ?? '—'}/${hubState.mission_count}${hubState.wp_dist != null ? ` · ${Math.round(hubState.wp_dist)} m` : ''}`, cx, 10, { align: 'center', px: 10, color: '#fde68a' });
  }

  // ---------- sürükleme (sütun ve konsol başlığından) + yerleşim ----------
  const dragSetup = (el, head, key, place) => {
    let d = null;
    head.addEventListener('pointerdown', e => {
      if (e.button !== 0 || e.target.closest('button, input, select')) return;
      const r = el.getBoundingClientRect(), s = stage.getBoundingClientRect();
      d = { id: e.pointerId, dx: e.clientX - r.left, dy: e.clientY - r.top, s, w: r.width, h: r.height };
      head.setPointerCapture(e.pointerId); el.classList.add('dragging'); e.preventDefault();
    });
    head.addEventListener('pointermove', e => {
      if (!d || e.pointerId !== d.id) return;
      const x = clamp(e.clientX - d.dx - d.s.left, 0, Math.max(0, d.s.width - d.w)), y = clamp(e.clientY - d.dy - d.s.top, 0, Math.max(0, d.s.height - 40));
      place(x, y, d.s);
    });
    const up = e => { if (!d || e.pointerId !== d.id) return; d = null; el.classList.remove('dragging'); const r = el.getBoundingClientRect(), s = stage.getBoundingClientRect(); lsSet(key, { x: Math.round(r.left - s.left), y: Math.round(r.top - s.top), r: Math.round(s.right - r.right), w: Math.round(s.width) }); };
    head.addEventListener('pointerup', up); head.addEventListener('pointercancel', up);
  };
  const placeCol = (x, y) => { col.classList.add('free'); col.style.left = `${x}px`; col.style.top = `${y}px`; col.style.right = 'auto'; };
  const placeCon = (x, y) => { conCard.classList.add('free'); conCard.style.left = `${x}px`; conCard.style.top = `${y}px`; conCard.style.bottom = 'auto'; conCard.style.transform = 'none'; };
  dragSetup(col, headCard, KEY_COL, placeCol);   // başlık kartının tamamı sütunun tutamacıdır (rozetler tıklanabilir değil)
  dragSetup(conCard, conCard._head, KEY_CON, placeCon);
  const applyLayout = () => {
    const s = stage.getBoundingClientRect();
    const c = lsGet(KEY_COL); if (c && typeof c.r === 'number') { const w = col.offsetWidth || 440; placeCol(clamp(s.width - c.r - w, 0, Math.max(0, s.width - w)), clamp(c.y, 0, Math.max(0, s.height - 60))); }
    const k = lsGet(KEY_CON); if (k && typeof k.x === 'number') { const w = conCard.offsetWidth || 560; placeCon(clamp(k.x, 0, Math.max(0, s.width - w)), clamp(k.y, 0, Math.max(0, s.height - 60))); }
  };
  const resetLayout = () => {
    lsSet(KEY_COL, null); lsSet(KEY_CON, null); lsSet(KEY_FOLD, null);
    col.classList.remove('free'); col.style.cssText = ''; conCard.classList.remove('free'); conCard.style.cssText = '';
    for (const k of Object.keys(fold)) delete fold[k];
    root.querySelectorAll('.fs-pn-card.folded').forEach(e => e.classList.remove('folded'));
    pfdDirty = true; if (!raf) raf = requestAnimationFrame(frame);
    toast(tr('Yerleşim sıfırlandı'));
  };
  // alt çubuk sarınca yükselir: kapsayıcının alt sınırı (--fs-bar-h) çubuğun üstünde kalır
  const bar = stage.querySelector('.fs-bar');
  const onResize = () => { if (bar) stage.style.setProperty('--fs-bar-h', `${bar.offsetHeight || 54}px`); if (col.classList.contains('free') || conCard.classList.contains('free')) applyLayout(); resizePfd(); pfdDirty = true; if (!raf && on) raf = requestAnimationFrame(frame); };
  const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(onResize) : null;
  ro?.observe(stage); if (bar) ro?.observe(bar);

  // ---------- göster/gizle (Panel düğmesi, P) ----------
  const apply = () => { stage.classList.toggle('fs-ops', on); if (on) { pfdDirty = true; if (!raf) raf = requestAnimationFrame(frame); } else closeMenu(); };
  const onKey = e => {
    if (e.ctrlKey || e.metaKey || e.altKey || editable(document.activeElement)) return;
    if (e.key === 'p' || e.key === 'P') { apiObj.toggle(); e.preventDefault(); }
  };
  window.addEventListener('keydown', onKey);
  apply();
  applyLayout();
  applyPerm();
  drawTiles(); drawRoute();
  requestAnimationFrame(() => { resizePfd(); pfdDirty = true; if (on) frame(); });
  if (hub) { openHub(); loadRoutes(); } else { B.st.textContent = tr(session.mode === 'replay' ? 'Kayıt' : 'Sahte veri'); B.st.className = 'badge purple'; }

  const apiObj = {
    el: root,
    get enabled() { return on; },
    toggle(v) { on = v == null ? !on : !!v; try { localStorage.setItem(KEY_ON, on ? '1' : '0'); } catch { /* */ } apply(); onToggle?.(on); return on; },
    setFpv(v) { stage.classList.toggle('fs-fpv', !!v); if (v) closeMenu(); else { pfdDirty = true; if (on && !raf) raf = requestAnimationFrame(frame); } },
    update,
    setState(st) { state = st; if (hub) { const tone = { BASLIYOR: 'yellow', HAZIR: 'green', HATA: 'red', KAPANDI: 'gray' }[st] || 'gray'; B.st.className = `badge ${tone}`; B.st.textContent = tr({ BASLIYOR: 'Başlıyor', HAZIR: 'Hazır', HATA: 'Hata', KAPANDI: 'Kapandı' }[st] || st); } applyPerm(); },
    setRoute(points) { routePts = points || []; drawRoute(); },
    setGcs(v) { gcs = !!v; },
    setLaunchPhase(ph) { if (launch) { launch.phase = ph; drawTiles(); } },
    log,
    hubCmd,
    dispose() {
      disposed = true; hubClosed = true;
      clearTimeout(hubTimer); clearInterval(hubPing); try { hubWs?.close(); } catch { /* */ }
      for (const p of pending.values()) clearTimeout(p.timer); pending.clear();
      if (raf) cancelAnimationFrame(raf);
      ro?.disconnect(); closeMenu();
      window.removeEventListener('keydown', onKey);
      root.remove(); stage.classList.remove('fs-ops', 'fs-ops-host', 'fs-fpv', 'fs-pn-nohub');
    },
  };
  return apiObj;
}
