// Dron Yönetimi (Saha Yönetimi alt modülleri — Faz 0): Dron Envanteri, Canlı Uçuş, Rotalar, Dron Köprüleri.
// Adresler: #/field/drones[/id] · #/field/live · #/field/routes[/id] · #/field/bridges
// Canlı telemetri: /ws/drone/live (oturum çerezi) — sunucu köprülerden gelen MAVLink'i çözümleyip JSON durum paketi yayınlar.
import { api } from '../api.js';
import {
  clear, confirmDialog, every, field, fmtDateTime, h, matches, modal, moduleTabs, moduleToolbar, onLeave, pageHead, statStrip, toast,
  toastError, t as tr,
} from '../ui.js';
import { PLANE_MODEL, createViewer, loadCesium, planeOrientation } from './replay3d.js';

const TABS = [['drones', 'Dron Envanteri'], ['live', 'Canlı Uçuş'], ['routes', 'Rotalar'], ['bridges', 'Dron Köprüleri']];
const DRONE_BADGE = { AKTIF: 'green', BAKIMDA: 'yellow', ARIZALI: 'red', PASIF: 'gray' };
const SESSION_BADGE = { ACIK: 'green', KAPANDI: 'gray', KOPTU: 'red', KESILDI: 'yellow' };
const FIX = { 0: 'GPS yok', 1: 'Fix yok', 2: '2B', 3: '3B', 4: 'DGPS', 5: 'RTK float', 6: 'RTK fixed' };
const MODES = ['MANUAL', 'STABILIZE', 'FBWA', 'FBWB', 'CRUISE', 'LOITER', 'AUTO', 'GUIDED', 'RTL', 'TAKEOFF', 'QLOITER', 'QHOVER', 'QLAND',
  'ALT_HOLD', 'LAND', 'POSHOLD', 'CIRCLE'];
const f1 = v => (v == null ? '—' : Number(v).toFixed(1));
const num = (v, d = 0) => (v == null || v === '' || Number.isNaN(Number(v)) ? null : Number(Number(v).toFixed(d)));
const ago = iso => { if (!iso) return '—'; const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000); return s < 60 ? `${Math.round(s)} sn önce` : s < 3600 ? `${Math.round(s / 60)} dk önce` : fmtDateTime(iso); };
const copy = async (txt, what = 'Kopyalandı') => { try { await navigator.clipboard.writeText(txt); toast(what); } catch { toast('Kopyalanamadı; metni elle seçin', 'err'); } };
const bridgeWsUrl = () => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/drone/bridge`;

export async function render(view, params, ctx) {
  const m = await api.get('/api/drone/meta');
  const tabs = TABS.filter(([k]) => m.can[k]);
  if (!tabs.length) {
    clear(view, pageHead('Dron Yönetimi', { back: '#/field' }),
      h('div', { class: 'card empty' }, 'Dron Yönetimi için yetkiniz yok. Rol Yönetimi › Saha & Operasyon altındaki Dron düğümleri rolünüze açılmalı.'));
    return;
  }
  const want = TABS.some(([k]) => k === params[0]) ? params[0] : tabs[0][0];
  const cur = m.can[want] ? want : tabs[0][0];
  const head = sub => pageHead('Dron Yönetimi', { back: '#/field', sub, tabs: moduleTabs(tabs, cur, k => { location.hash = `#/field/${k}`; }) });
  if (cur === 'drones') return params[1] ? renderDroneDetail(view, Number(params[1]), ctx, m) : renderDrones(view, ctx, m, head);
  if (cur === 'live') return renderLive(view, ctx, m, head);
  if (cur === 'routes') return params[1] ? renderRouteEditor(view, Number(params[1]), ctx, m) : renderRoutes(view, ctx, m, head);
  return renderBridges(view, ctx, m, head);
}

// ---------- yardımcılar ----------
const people = role => api.get(`/api/people?role=${encodeURIComponent(role)}`).catch(() => []);
const bridgesList = () => api.get('/api/drone/bridges').catch(() => []);
const sel = (options, value, { empty } = {}) => h('select', { class: 'input' },
  empty != null ? h('option', { value: '' }, empty) : null,
  options.map(([k, label]) => h('option', { value: k, selected: String(k) === String(value ?? '') }, label)));
const inp = (value, attrs = {}) => h('input', { class: 'input', value: value ?? '', ...attrs });
const check = (label, on) => { const cb = h('input', { type: 'checkbox', checked: !!on }); return [h('label', { class: 'check' }, cb, label), cb]; };
const onlineBadge = on => h('span', { class: `badge ${on ? 'green' : 'gray'}` }, on ? 'Çevrimiçi' : 'Çevrimdışı');
const liveLine = st => (st ? [st.mode ? h('span', { class: 'badge blue' }, st.mode) : null, h('span', { class: `badge ${st.armed ? 'red' : 'gray'}` }, st.armed ? 'ARMED' : 'Disarmed'),
  st.alt_rel != null ? h('span', { class: 'small muted' }, ` ${f1(st.alt_rel)} m · ${f1(st.groundspeed)} m/s`) : null] : null);

// ======================================================================
// Dron Envanteri
// ======================================================================
async function renderDrones(view, ctx, m, head) {
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kod, ad, model, seri, köprü, pilot ara…', style: { width: '260px' } });
  const status = sel([['', 'Tüm durumlar'], ...Object.entries(m.drone_status)], '');
  const stats = statStrip();
  const body = h('div');
  let rows = [];
  const draw = () => {
    const list = rows.filter(d => (!status.value || d.status === status.value) && matches(q.value, d.code, d.name, d.model, d.serial, d.bridge_name, d.pilot_name));
    stats.set([
      { icon: 'fleet', label: 'Kayıtlı dron', value: rows.filter(d => d.active).length },
      { icon: 'documents', label: 'Köprüsü çevrimiçi', value: rows.filter(d => d.online).length, tone: 'ok' },
      { icon: 'note', label: 'Açık görevde', value: rows.filter(d => d.open_task_code).length },
      { icon: 'warning', label: 'Bakım / arıza', value: rows.filter(d => ['BAKIMDA', 'ARIZALI'].includes(d.status)).length },
    ]);
    clear(body, list.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Kod', 'Dron', 'MAVLink', 'Köprü', 'Pilot', 'Durum', 'Görev', 'Son log'].map(c => h('th', null, c)))),
      h('tbody', null, list.map(d => h('tr', { class: 'click', onclick: () => { location.hash = `#/field/drones/${d.id}`; } },
        h('td', null, h('b', { class: 'mono' }, d.code), d.active ? null : h('div', null, h('span', { class: 'badge gray' }, 'Pasif'))),
        h('td', null, h('b', null, d.name), h('div', { class: 'small muted' }, [d.model, d.serial ? `SN ${d.serial}` : null].filter(Boolean).join(' · '))),
        h('td', { class: 'small' }, d.sysid != null ? `sysid ${d.sysid}` : '—', h('div', { class: 'small muted' },
          d.conn_type ? `${d.conn_type}${d.conn_type === 'serial' ? ` ${d.conn_serial || ''} ${d.conn_baud || ''}` : ` ${d.conn_host || ''}:${d.conn_port || ''}`}` : '')),
        h('td', null, d.bridge_name ? [d.bridge_name, h('div', null, onlineBadge(d.online))] : h('span', { class: 'muted' }, '—'),
          d.live ? h('div', { class: 'small' }, liveLine(d.live)) : null),
        h('td', null, d.pilot_name || h('span', { class: 'muted' }, '—')),
        h('td', null, h('span', { class: `badge ${DRONE_BADGE[d.status] || 'gray'}` }, d.status_text)),
        h('td', null, d.open_task_code ? h('span', { class: 'badge blue' }, d.open_task_code) : h('span', { class: 'small muted' }, tr('{n} görev', { n: d.task_count }))),
        h('td', { class: 'small muted' }, d.last_log_at ? fmtDateTime(d.last_log_at) : '—'))))))
      : h('div', { class: 'card empty' }, rows.length ? 'Filtreye uyan dron yok' : 'Henüz dron eklenmedi. "Yeni Dron" ile envantere ekleyin; köprü ve MAVLink sistem kimliğini bağlayın.'));
  };
  const load = async () => { rows = await api.get('/api/drone/drones'); draw(); };
  q.addEventListener('input', draw);
  status.addEventListener('change', draw);
  clear(view, head('Dron Envanteri · kayıtlı dronlar, köprü bağları ve canlı durum'),
    stats,
    moduleToolbar(h('button', { class: 'btn primary', onclick: () => droneForm(null, m, load) }, '＋ Yeni Dron'), q, status),
    body);
  await load();
  every(15000, () => load().catch(() => {}));
}

async function droneForm(d, m, done) {
  const [pilots, bridges] = await Promise.all([people('Pilot'), bridgesList()]);
  const name = inp(d?.name, { placeholder: 'Örn. Göktungu-1', maxlength: 120 });
  const model = inp(d?.model, { placeholder: 'Örn. GT-1 VTOL', maxlength: 80 });
  const serial = inp(d?.serial, { placeholder: 'Seri no', maxlength: 80 });
  const sysid = inp(d?.sysid, { type: 'number', min: 1, max: 255, placeholder: '1' });
  const connType = sel([['', 'Seçilmedi'], ...m.conn_types.map(c => [c, c.toUpperCase()])], d?.conn_type);
  const connHost = inp(d?.conn_host, { placeholder: '192.168.4.1 ya da 0.0.0.0' });
  const connPort = inp(d?.conn_port, { type: 'number', min: 1, max: 65535, placeholder: '14550' });
  const connSerial = inp(d?.conn_serial, { placeholder: '/dev/ttyUSB0 · COM3' });
  const connBaud = inp(d?.conn_baud, { type: 'number', placeholder: '57600' });
  const bridge = sel(bridges.map(b => [b.id, `${b.name}${b.online ? ' · çevrimiçi' : ''}`]), d?.bridge_id, { empty: bridges.length ? 'Köprü seçilmedi' : 'Kayıtlı köprü yok' });
  const pilot = sel(pilots.map(p => [p.id, p.full_name]), d?.pilot_id, { empty: 'Pilot seçilmedi' });
  const status = sel(Object.entries(m.drone_status), d?.status || 'AKTIF');
  const note = h('textarea', { class: 'input', rows: 2 }, d?.note || '');
  const [activeEl, active] = check('Aktif (görevlere seçilebilir)', d ? d.active : true);
  const connRow = h('div', { class: 'row' });
  const drawConn = () => clear(connRow, connType.value === 'serial' ? [field('Seri port', connSerial), field('Baud', connBaud)]
    : connType.value ? [field('Adres', connHost), field('Port', connPort)] : null);
  connType.addEventListener('change', drawConn);
  drawConn();
  modal({
    title: d ? tr('{code} · Dron bilgileri', { code: d.code }) : 'Yeni Dron',
    wide: true,
    body: h('div', null,
      h('div', { class: 'row' }, field('Dron adı', name), field('Model', model)),
      h('div', { class: 'row' }, field('Seri no', serial), field('MAVLink sistem kimliği (sysid)', sysid, 'Köprü birden çok dron taşıyorsa ayrım için')),
      h('div', { class: 'row' }, field('Köprü (pilot cihazı)', bridge, 'Dronun telemetrisini sunucuya taşıyan köprü yazılımı'), field('Sorumlu pilot', pilot)),
      h('div', { class: 'row' }, field('Köprünün drona bağlantısı', connType), h('div', null)),
      connRow,
      h('div', { class: 'row' }, field('Durum', status), field('Not', note)),
      activeEl),
    actions: [{ label: 'Vazgeç' }, {
      label: d ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const body = {
          name: name.value.trim(), model: model.value.trim() || null, serial: serial.value.trim() || null, sysid: num(sysid.value),
          conn_type: connType.value || null, conn_host: connHost.value.trim() || null, conn_port: num(connPort.value),
          conn_serial: connSerial.value.trim() || null, conn_baud: num(connBaud.value), bridge_id: num(bridge.value), pilot_id: num(pilot.value),
          status: status.value, note: note.value.trim() || null, active: active.checked,
        };
        if (!body.name) throw new Error('Dron adı gerekli');
        if (d) { await api.put(`/api/drone/drones/${d.id}`, body); toast('Dron güncellendi'); } else { const r = await api.post('/api/drone/drones', body); toast(tr('{code} eklendi', { code: r.code })); }
        done?.();
      },
    }],
  });
}

async function renderDroneDetail(view, id, ctx, m) {
  const box = h('div');
  const load = async () => {
    const d = await api.get(`/api/drone/drones/${id}`);
    const kv = (k, v) => [h('dt', null, k), h('dd', null, v == null || v === '' ? h('span', { class: 'muted' }, '—') : v)];
    const conn = d.conn_type ? (d.conn_type === 'serial' ? `serial ${d.conn_serial || ''} @ ${d.conn_baud || '?'}` : `${d.conn_type} ${d.conn_host || ''}:${d.conn_port || ''}`) : null;
    const st = d.live;
    clear(view,
      pageHead(`${d.code} · ${d.name}`, {
        back: '#/field/drones', sub: [d.model, d.serial ? `SN ${d.serial}` : null, d.status_text].filter(Boolean).join(' · '),
        right: h('div', { class: 'pill-group' },
          m.can.live && d.online ? h('a', { class: 'btn sm', href: '#/field/live' }, 'Canlı Uçuş') : null,
          h('button', { class: 'btn sm primary', onclick: () => droneForm(d, m, load) }, 'Bilgileri düzenle'),
          h('button', { class: 'btn sm danger', onclick: async () => {
            if (!await confirmDialog('Dronu sil', tr('{code} silinsin mi? Uçuş geçmişi varsa silinmez, pasife alınır.', { code: d.code }), { okLabel: 'Sil', danger: true })) return;
            const r = await api.del(`/api/drone/drones/${d.id}`);
            toast(r.deactivated ? 'Dron pasife alındı (uçuş geçmişi var)' : 'Dron silindi');
            location.hash = '#/field/drones';
          } }, 'Sil')),
      }),
      h('div', { class: 'grid-2', style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', alignItems: 'start' } },
        h('div', { class: 'card card-pad' }, h('h3', null, 'Genel bilgiler'),
          h('dl', { class: 'kv' },
            ...kv('Durum', h('span', { class: `badge ${DRONE_BADGE[d.status] || 'gray'}` }, d.status_text)),
            ...kv('Protokol', `${d.protocol}${d.sysid != null ? ` · sysid ${d.sysid}` : ''}`),
            ...kv('Köprü', d.bridge_name ? [d.bridge_name, ' ', onlineBadge(d.online), d.bridge_last_seen ? h('span', { class: 'small muted' }, ` · ${ago(d.bridge_last_seen)}`) : null] : null),
            ...kv('Drona bağlantı', conn),
            ...kv('Sorumlu pilot', d.pilot_name),
            ...kv('Üretim bağı', d.order_code ? `${d.queue_no || ''} ${d.order_code}`.trim() : null),
            ...kv('Açık görev', d.open_task_code ? h('span', { class: 'badge blue' }, d.open_task_code) : null),
            ...kv('Not', d.note),
            ...kv('Kayıt', d.created_at ? fmtDateTime(d.created_at) : null))),
        h('div', { class: 'card card-pad' }, h('h3', null, 'Canlı durum'),
          st ? h('div', { class: 'dr-kv' },
            h('span', null, 'Mod'), h('b', null, st.mode || '—'), h('span', null, 'Arm'), h('b', null, st.armed ? 'ARMED' : 'Disarmed'),
            h('span', null, 'İrtifa (göreli)'), h('b', null, `${f1(st.alt_rel)} m`), h('span', null, 'Yer hızı'), h('b', null, `${f1(st.groundspeed)} m/s`),
            h('span', null, 'Hava hızı'), h('b', null, `${f1(st.airspeed)} m/s`), h('span', null, 'Gaz'), h('b', null, st.throttle == null ? '—' : `%${st.throttle}`),
            h('span', null, 'Batarya'), h('b', null, st.volt == null ? '—' : `${Number(st.volt).toFixed(2)} V${st.batt_pct != null ? ` · %${st.batt_pct}` : ''}`),
            h('span', null, 'GPS'), h('b', null, `${FIX[st.fix] || '—'}${st.sats != null ? ` · ${st.sats} uydu` : ''}`),
            h('span', null, 'Konum'), h('b', null, st.lat != null ? `${st.lat.toFixed(6)}, ${st.lon.toFixed(6)}` : '—'),
            h('span', null, 'Paket'), h('b', null, String(st.msgs || 0)))
            : h('div', { class: 'small muted' }, d.online ? 'Köprü bağlı; drondan henüz telemetri gelmedi.' : 'Köprü çevrimdışı. Canlı veri, pilotun cihazındaki köprü yazılımı bağlanınca görünür.'))),
      h('div', { class: 'card card-pad', style: { marginTop: '14px' } }, h('h3', null, tr('Uçuşlar ({n})', { n: d.flights.length })),
        d.flights.length ? h('div', { class: 'table-wrap' }, h('table', null,
          h('thead', null, h('tr', null, ['Saha görevi', 'Durum', 'Görev yeri', 'Başladı', 'Uçuş logu', 'Havada', ''].map(c => h('th', null, c)))),
          h('tbody', null, d.flights.map(f => h('tr', { class: 'click', onclick: () => { location.hash = `#/field/flight/${f.id}`; } },
            h('td', null, h('b', null, f.task_code)), h('td', null, f.task_status), h('td', null, f.location_name || '—'),
            h('td', { class: 'small muted' }, f.started_at ? fmtDateTime(f.started_at) : '—'),
            h('td', null, f.log_status ? h('span', { class: `badge ${f.log_status === 'TAMAM' ? 'green' : f.log_status === 'HATA' ? 'red' : 'yellow'}` }, f.log_status) : h('span', { class: 'muted' }, 'Yok'),
              f.log_source === 'BRIDGE' ? h('span', { class: 'small muted' }, ' köprüden') : null),
            h('td', null, f.flight_s != null ? `${Math.floor(f.flight_s / 60)} dk ${Math.round(f.flight_s % 60)} sn` : '—'),
            h('td', { class: 'num' }, f.log_status === 'TAMAM' ? h('a', { class: 'btn sm', href: `#/field/report/${f.log_id}`, onclick: e => e.stopPropagation() }, 'Uçuş Raporu') : null))))))
          : h('div', { class: 'small muted' }, 'Bu dron henüz bir saha görevine eklenmedi. Yeni Saha Görevi penceresinde "Götürülecek dronlar" listesinden seçilir.')),
      h('div', { class: 'card card-pad', style: { marginTop: '14px' } }, h('h3', null, 'Köprü oturumları'),
        d.sessions.length ? sessionsTable(d.sessions) : h('div', { class: 'small muted' }, 'Bu drona bağlı köprü oturumu yok.')));
  };
  clear(view, box);
  await load();
  every(10000, () => load().catch(() => {}));
}

const sessionsTable = rows => h('div', { class: 'table-wrap' }, h('table', null,
  h('thead', null, h('tr', null, ['Köprü', 'Başladı', 'Bitti', 'Durum', 'Paket', 'Dron', 'Hata'].map(c => h('th', null, c)))),
  h('tbody', null, rows.map(s => h('tr', null,
    h('td', null, s.bridge_name || '—'), h('td', { class: 'small' }, fmtDateTime(s.started_at)), h('td', { class: 'small' }, s.ended_at ? fmtDateTime(s.ended_at) : h('span', { class: 'badge green' }, 'Açık')),
    h('td', null, h('span', { class: `badge ${SESSION_BADGE[s.status] || 'gray'}` }, s.status_text || s.status)),
    h('td', { class: 'num' }, s.packets), h('td', null, s.drone_code || '—'), h('td', { class: 'small muted' }, s.error || ''))))));

// ======================================================================
// Dron Köprüleri
// ======================================================================
async function renderBridges(view, ctx, m, head) {
  const body = h('div');
  const stats = statStrip();
  let rows = [];
  const draw = () => {
    stats.set([
      { icon: 'fleet', label: 'Köprü', value: rows.filter(b => b.active).length },
      { icon: 'documents', label: 'Çevrimiçi', value: rows.filter(b => b.online).length, tone: 'ok' },
      { icon: 'warning', label: 'Eşleştirilmemiş', value: rows.filter(b => !b.has_key).length },
    ]);
    clear(body, rows.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Köprü', 'Platform', 'Sahibi', 'Bağlantı', 'Cihaz', 'Dron', ''].map(c => h('th', null, c)))),
      h('tbody', null, rows.map(b => h('tr', null,
        h('td', null, h('b', null, b.name), b.active ? null : h('span', { class: 'badge gray', style: { marginLeft: '6px' } }, 'Pasif'),
          h('div', { class: 'small muted' }, b.note || '')),
        h('td', null, b.platform || '—'),
        h('td', null, b.owner_name || h('span', { class: 'muted' }, '—')),
        h('td', null, onlineBadge(b.online), h('div', { class: 'small muted' }, b.online ? tr('{n} paket · oturum #{s}', { n: b.live?.packets || 0, s: b.live?.session_id || '' })
          : b.last_seen ? `Son görülme ${ago(b.last_seen)}` : 'Hiç bağlanmadı'),
          b.has_key ? null : h('span', { class: 'badge yellow' }, 'Eşleştirilmedi')),
        h('td', { class: 'small' }, b.host || '—', h('div', { class: 'muted' }, b.bridge_ver ? `sürüm ${b.bridge_ver}` : '')),
        h('td', null, tr('{n} dron', { n: b.drone_count }), b.online && b.live?.drones ? h('div', { class: 'small' }, Object.values(b.live.drones).map(st => h('div', null, `sysid ${st.sysid}: `, liveLine(st)))) : null),
        h('td', { class: 'num' }, h('div', { class: 'pill-group' },
          h('button', { class: 'btn sm primary', title: 'Köprü yazılımına girilecek tek kullanımlık kod (10 dk)', onclick: () => pairModal(b) }, 'Eşleştir'),
          h('button', { class: 'btn sm', onclick: () => sessionsModal(b) }, 'Oturumlar'),
          b.online ? h('button', { class: 'btn sm', onclick: async () => {
            if (!await confirmDialog('Bağlantıyı kes', tr('{name} köprüsünün bağlantısı kesilsin mi? Köprü yeniden bağlanabilir.', { name: b.name }), { okLabel: 'Kes', danger: true })) return;
            await api.post(`/api/drone/bridges/${b.id}/disconnect`); toast('Bağlantı kesildi'); load();
          } }, 'Bağlantıyı kes') : null,
          h('button', { class: 'btn sm', onclick: () => bridgeForm(b, m, load) }, 'Düzenle'),
          h('button', { class: 'btn sm ghost', onclick: () => rekey(b) }, 'Anahtarı yenile'),
          h('button', { class: 'btn sm danger', onclick: async () => {
            if (!await confirmDialog('Köprüyü sil', tr('{name} silinsin mi? Oturum geçmişi silinir, dronların köprü bağı kalkar.', { name: b.name }), { okLabel: 'Sil', danger: true })) return;
            await api.del(`/api/drone/bridges/${b.id}`); toast('Köprü silindi'); load();
          } }, 'Sil'))))))))
      : h('div', { class: 'card empty' }, 'Henüz köprü yok. Köprü, pilotun telefonundaki / bilgisayarındaki yazılımdır: drona yerel bağlanır, telemetriyi sunucuya taşır. "Yeni Köprü" ekleyip "Eşleştir" ile koda bağlayın.'));
  };
  const load = async () => { rows = await api.get('/api/drone/bridges'); draw(); };
  const rekey = async b => {
    if (!await confirmDialog('Anahtarı yenile', tr('{name} için yeni anahtar üretilsin mi? Eski anahtar hemen geçersiz olur; bağlı köprü düşer ve yeni anahtarla yeniden bağlanmalıdır.', { name: b.name }), { okLabel: 'Yenile', danger: true })) return;
    const r = await api.post(`/api/drone/bridges/${b.id}/rekey`);
    modal({
      title: tr('{name} · yeni anahtar', { name: b.name }),
      body: h('div', null, h('p', { class: 'small muted' }, 'Bu anahtar yalnız şimdi gösterilir; köprü yazılımının ayarlarına yapıştırın. Sunucuda şifreli saklanır, bir daha okunamaz.'),
        h('div', { class: 'dr-key' }, r.key), h('p', { class: 'small muted', style: { marginTop: '8px' } }, 'Sunucu adresi: ', h('code', null, bridgeWsUrl()))),
      actions: [{ label: 'Kapat' }, { label: 'Anahtarı kopyala', class: 'primary', onClick: async () => { await copy(r.key, 'Anahtar kopyalandı'); return true; } }],
    });
    load();
  };
  const pairModal = async b => {
    const r = await api.post(`/api/drone/bridges/${b.id}/pair`);
    const codeEl = h('div', { class: 'dr-pair-code' }, r.code);
    const left = h('b', null, '');
    const until = Date.now() + r.expires_in * 1000;
    const tick = () => { const s = Math.max(0, Math.round((until - Date.now()) / 1000)); left.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; if (!s) { clearInterval(iv); codeEl.textContent = 'Süresi doldu'; } };
    const iv = setInterval(tick, 1000); tick();
    modal({
      title: tr('{name} · eşleştirme kodu', { name: b.name }),
      onClose: () => clearInterval(iv),
      body: h('div', null, codeEl,
        h('p', { class: 'small muted', style: { marginTop: '10px' } }, 'Köprü yazılımında "Eşleştir"e basıp bu kodu girin. Kod ', left, ' içinde ve yalnız bir kez kullanılabilir; köprü kalıcı anahtarını alır ve bir daha kod gerekmez.'),
        h('p', { class: 'small muted' }, 'Sunucu adresi: ', h('code', null, bridgeWsUrl()))),
      actions: [{ label: 'Kapat' }, { label: 'Adresi kopyala', onClick: async () => { await copy(bridgeWsUrl(), 'Adres kopyalandı'); return true; } },
        { label: 'Kodu kopyala', class: 'primary', onClick: async () => { await copy(r.code, 'Kod kopyalandı'); return true; } }],
    });
  };
  const sessionsModal = async b => {
    const rows = await api.get(`/api/drone/bridges/${b.id}/sessions`);
    modal({ title: tr('{name} · oturumlar', { name: b.name }), wide: true, body: rows.length ? sessionsTable(rows) : h('div', { class: 'small muted' }, 'Henüz oturum yok'), actions: [{ label: 'Kapat' }] });
  };
  clear(view, head('Dron Köprüleri · pilot cihazındaki köprü yazılımları, eşleştirme ve oturumlar'),
    stats,
    moduleToolbar(h('button', { class: 'btn primary', onclick: () => bridgeForm(null, m, load) }, '＋ Yeni Köprü'),
      h('span', { class: 'small muted' }, 'Köprü adresi: ', h('code', null, bridgeWsUrl()))),
    body);
  await load();
  every(10000, () => load().catch(() => {}));
}

async function bridgeForm(b, m, done) {
  const pilots = await people('Pilot');
  const name = inp(b?.name, { placeholder: 'Örn. Pilot tableti (Ahmet)', maxlength: 80 });
  const platform = sel(m.platforms.map(p => [p, p]), b?.platform, { empty: 'Seçilmedi' });
  const owner = sel(pilots.map(p => [p.id, p.full_name]), b?.owner_id, { empty: 'Sahibi seçilmedi' });
  const note = h('textarea', { class: 'input', rows: 2 }, b?.note || '');
  const [activeEl, active] = check('Aktif (bağlanabilir)', b ? b.active : true);
  modal({
    title: b ? 'Köprü bilgileri' : 'Yeni Köprü',
    body: h('div', null, field('Köprü adı', name), h('div', { class: 'row' }, field('Platform', platform), field('Sahibi (pilot)', owner)), field('Not', note), activeEl,
      b ? null : h('p', { class: 'small muted' }, 'Eklendikten sonra "Eşleştir" ile 6 haneli kod üretilir; köprü yazılımı bu kodla bağlanıp kalıcı anahtarını alır.')),
    actions: [{ label: 'Vazgeç' }, {
      label: b ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const body = { name: name.value.trim(), platform: platform.value || null, owner_id: num(owner.value), note: note.value.trim() || null, active: active.checked };
        if (!body.name) throw new Error('Köprü adı gerekli');
        if (b) await api.put(`/api/drone/bridges/${b.id}`, body); else await api.post('/api/drone/bridges', body);
        toast(b ? 'Köprü güncellendi' : 'Köprü eklendi'); done?.();
      },
    }],
  });
}

// ======================================================================
// Rotalar
// ======================================================================
async function renderRoutes(view, ctx, m, head) {
  const body = h('div');
  const load = async () => {
    const [centers, routes] = await Promise.all([api.get('/api/drone/centers'), api.get('/api/drone/routes')]);
    clear(body,
      h('div', { class: 'card card-pad' }, h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px' } }, h('h3', { style: { margin: 0, flex: 1 } }, tr('Rota merkezleri ({n})', { n: centers.length })),
        h('button', { class: 'btn sm primary', onclick: () => centerForm(null, load) }, '＋ Yeni Merkez')),
        centers.length ? h('div', { class: 'table-wrap', style: { marginTop: '10px' } }, h('table', null,
          h('thead', null, h('tr', null, ['Merkez', 'Konum', 'İrtifa', 'Görev yeri', 'Rota', ''].map(c => h('th', null, c)))),
          h('tbody', null, centers.map(c => h('tr', null,
            h('td', null, h('b', null, c.name), c.active ? null : h('span', { class: 'badge gray', style: { marginLeft: '6px' } }, 'Pasif'), h('div', { class: 'small muted' }, c.note || '')),
            h('td', { class: 'mono small' }, `${c.lat.toFixed(6)}, ${c.lon.toFixed(6)}`),
            h('td', null, c.alt != null ? `${c.alt} m` : '—'), h('td', null, c.location_name || '—'), h('td', null, c.route_count),
            h('td', { class: 'num' }, h('div', { class: 'pill-group' },
              h('a', { class: 'btn sm', href: `https://www.google.com/maps?q=${c.lat},${c.lon}`, target: '_blank', rel: 'noopener' }, 'Haritada'),
              h('button', { class: 'btn sm', onclick: () => centerForm(c, load) }, 'Düzenle'),
              h('button', { class: 'btn sm danger', onclick: async () => {
                if (!await confirmDialog('Merkezi sil', tr('{name} silinsin mi? Rotalar kalır, merkez bağı kalkar.', { name: c.name }), { okLabel: 'Sil', danger: true })) return;
                await api.del(`/api/drone/centers/${c.id}`); toast('Merkez silindi'); load();
              } }, 'Sil'))))))))
          : h('div', { class: 'small muted', style: { marginTop: '8px' } }, 'Merkez: rotaların referans noktası (pist / kalkış alanı). Önce bir merkez ekleyin.')),
      h('div', { class: 'card card-pad', style: { marginTop: '14px' } }, h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px' } }, h('h3', { style: { margin: 0, flex: 1 } }, tr('Rotalar ({n})', { n: routes.length })),
        h('button', { class: 'btn sm primary', onclick: () => routeNew(centers) }, '＋ Yeni Rota')),
        routes.length ? h('div', { class: 'table-wrap', style: { marginTop: '10px' } }, h('table', null,
          h('thead', null, h('tr', null, ['Rota', 'Merkez', 'Tür', 'Seyir irtifası', 'Seyir hızı', 'Nokta', 'Güncellendi'].map(c => h('th', null, c)))),
          h('tbody', null, routes.map(r => h('tr', { class: 'click', onclick: () => { location.hash = `#/field/routes/${r.id}`; } },
            h('td', null, h('b', null, r.name), r.active ? null : h('span', { class: 'badge gray', style: { marginLeft: '6px' } }, 'Pasif')),
            h('td', null, r.center_name || '—'), h('td', null, h('span', { class: 'badge blue' }, r.kind_text)),
            h('td', null, r.cruise_alt != null ? `${r.cruise_alt} m` : '—'), h('td', null, r.cruise_speed != null ? `${r.cruise_speed} m/s` : '—'),
            h('td', null, r.wp_count), h('td', { class: 'small muted' }, fmtDateTime(r.updated_at || r.created_at)))))))
          : h('div', { class: 'small muted', style: { marginTop: '8px' } }, 'Henüz rota yok. Rota: sıralı ara noktalar (enlem, boylam, irtifa, eylem); köprüye MAVLink görevi olarak yüklenir.')));
  };
  const routeNew = centers => {
    const name = inp('', { placeholder: 'Örn. Devriye 1' });
    const center = sel(centers.filter(c => c.active).map(c => [c.id, c.name]), '', { empty: 'Merkez seçilmedi' });
    const kind = sel(Object.entries(m.route_kinds), 'line');
    modal({
      title: 'Yeni Rota', body: h('div', null, field('Rota adı', name), h('div', { class: 'row' }, field('Merkez', center), field('Tür', kind))),
      actions: [{ label: 'Vazgeç' }, { label: 'Oluştur ve düzenle', class: 'primary', onClick: async () => {
        if (!name.value.trim()) throw new Error('Rota adı gerekli');
        const c = centers.find(x => x.id === num(center.value));
        const r = await api.post('/api/drone/routes', { name: name.value.trim(), center_id: num(center.value), kind: kind.value,
          waypoints: c ? [{ lat: c.lat, lon: c.lon, alt: null, action: 'takeoff' }] : [] });
        location.hash = `#/field/routes/${r.id}`;
      } }],
    });
  };
  clear(view, head('Rotalar · rota merkezleri, ara noktalar ve MAVLink görev dışa aktarımı'), body);
  await load();
}

async function centerForm(c, done) {
  const locations = await api.get('/api/field/locations').catch(() => []);
  const name = inp(c?.name, { placeholder: 'Örn. Ankara pist' });
  const lat = inp(c?.lat, { type: 'number', step: 'any', placeholder: '39.9' });
  const lon = inp(c?.lon, { type: 'number', step: 'any', placeholder: '32.8' });
  const alt = inp(c?.alt, { type: 'number', step: 'any', placeholder: 'm (deniz seviyesi)' });
  const loc = sel(locations.map(l => [l.id, l.name]), c?.location_id, { empty: 'Görev yeri bağlanmadı' });
  const note = h('textarea', { class: 'input', rows: 2 }, c?.note || '');
  const [activeEl, active] = check('Aktif', c ? c.active : true);
  const locBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => {
    if (!navigator.geolocation) return toast('Bu cihazda konum servisi yok', 'err');
    navigator.geolocation.getCurrentPosition(p => { lat.value = p.coords.latitude.toFixed(6); lon.value = p.coords.longitude.toFixed(6); if (p.coords.altitude != null) alt.value = Math.round(p.coords.altitude); toast('Konum alındı'); },
      () => toast('Konum alınamadı', 'err'), { enableHighAccuracy: true, timeout: 10000 });
  } }, 'Bulunduğum konumu kullan');
  modal({
    title: c ? 'Merkez bilgileri' : 'Yeni Rota Merkezi',
    body: h('div', null, field('Merkez adı', name), h('div', { class: 'row' }, field('Enlem', lat), field('Boylam', lon)),
      h('div', { class: 'row' }, field('İrtifa (m)', alt), field('Görev yeri', loc)), locBtn, field('Not', note), activeEl),
    actions: [{ label: 'Vazgeç' }, { label: c ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
      const body = { name: name.value.trim(), lat: num(lat.value, 7), lon: num(lon.value, 7), alt: num(alt.value, 1), location_id: num(loc.value), note: note.value.trim() || null, active: active.checked };
      if (!body.name) throw new Error('Merkez adı gerekli');
      if (body.lat == null || body.lon == null) throw new Error('Enlem ve boylam gerekli');
      if (c) await api.put(`/api/drone/centers/${c.id}`, body); else await api.post('/api/drone/centers', body);
      toast(c ? 'Merkez güncellendi' : 'Merkez eklendi'); done?.();
    } }],
  });
}

async function renderRouteEditor(view, id, ctx, m) {
  const [r, centers] = await Promise.all([api.get(`/api/drone/routes/${id}`), api.get('/api/drone/centers')]);
  const wps = r.waypoints.map(w => ({ lat: w.lat, lon: w.lon, alt: w.alt, action: w.action, hold_s: w.hold_s, note: w.note }));
  const name = inp(r.name, { maxlength: 120 });
  const center = sel(centers.map(c => [c.id, c.name]), r.center_id, { empty: 'Merkez seçilmedi' });
  const kind = sel(Object.entries(m.route_kinds), r.kind);
  const cAlt = inp(r.cruise_alt, { type: 'number', step: 'any', placeholder: 'm (göreli)' });
  const cSpd = inp(r.cruise_speed, { type: 'number', step: 'any', placeholder: 'm/s' });
  const note = h('textarea', { class: 'input', rows: 2 }, r.note || '');
  const [activeEl, active] = check('Aktif', r.active);
  const tbl = h('div');
  const prev = h('div', { class: 'dr-route-svg' });
  const info = h('div', { class: 'small muted' });
  const R = 6371000;
  const dist = (a, b) => { const p1 = a.lat * Math.PI / 180, p2 = b.lat * Math.PI / 180, dp = p2 - p1, dl = (b.lon - a.lon) * Math.PI / 180; const x = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(x)); };
  const drawPrev = () => {
    const pts = wps.filter(w => w.lat != null && w.lon != null);
    if (pts.length < 1) { prev.innerHTML = '<svg viewBox="0 0 300 300"><text x="150" y="150" text-anchor="middle" fill="#9aa4b6" font-size="13">Ara nokta yok</text></svg>'; info.textContent = ''; return; }
    const lat0 = pts.reduce((a, w) => a + w.lat, 0) / pts.length;
    const k = Math.cos(lat0 * Math.PI / 180);
    const xs = pts.map(w => w.lon * k), ys = pts.map(w => w.lat);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const span = Math.max(maxX - minX, maxY - minY, 1e-5), pad = 24, sz = 300 - pad * 2;
    const X = v => pad + ((v - minX) / span) * sz + (sz - ((maxX - minX) / span) * sz) / 2;
    const Y = v => 300 - pad - ((v - minY) / span) * sz - (sz - ((maxY - minY) / span) * sz) / 2;
    const P = pts.map((w, i) => [X(xs[i]), Y(ys[i])]);
    const path = P.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ') + (kind.value === 'loop' && P.length > 2 ? ' Z' : '');
    const colors = { takeoff: '#22c55e', land: '#ef4444', rtl: '#f59e0b', loiter: '#8b5cf6', waypoint: '#2563eb' };
    prev.innerHTML = `<svg viewBox="0 0 300 300"><path d="${path}" fill="none" stroke="#ffcc33" stroke-width="2" stroke-dasharray="${kind.value === 'survey' ? '6 4' : '0'}"/>`
      + P.map(([x, y], i) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="7" fill="${colors[pts[i].action] || '#2563eb'}" stroke="#fff" stroke-width="1.5"/><text x="${x.toFixed(1)}" y="${(y + 3.5).toFixed(1)}" text-anchor="middle" font-size="9" fill="#fff" font-weight="700">${i + 1}</text>`).join('')
      + '</svg>';
    let total = 0;
    for (let i = 1; i < pts.length; i++) total += dist(pts[i - 1], pts[i]);
    if (kind.value === 'loop' && pts.length > 2) total += dist(pts[pts.length - 1], pts[0]);
    const spd = num(cSpd.value);
    info.textContent = `${pts.length} nokta · ${(total / 1000).toFixed(2)} km${spd ? ` · ~${Math.round(total / spd / 60)} dk @ ${spd} m/s` : ''}`;
  };
  const drawTbl = () => {
    clear(tbl, h('div', { class: 'table-wrap' }, h('table', { class: 'dr-wp' },
      h('thead', null, h('tr', null, ['#', 'Enlem', 'Boylam', 'İrtifa (m)', 'Eylem', 'Bekleme (sn)', 'Not', ''].map(c => h('th', null, c)))),
      h('tbody', null, wps.map((w, i) => {
        const lat = inp(w.lat, { type: 'number', step: 'any' }), lon = inp(w.lon, { type: 'number', step: 'any' }), alt = inp(w.alt, { type: 'number', step: 'any', placeholder: 'seyir' });
        const act = sel(Object.entries(m.wp_actions), w.action), hold = inp(w.hold_s, { type: 'number', step: 'any' }), nt = inp(w.note, { maxlength: 200 });
        const upd = () => { w.lat = num(lat.value, 7); w.lon = num(lon.value, 7); w.alt = num(alt.value, 1); w.action = act.value; w.hold_s = num(hold.value, 1); w.note = nt.value.trim() || null; drawPrev(); };
        [lat, lon, alt, act, hold, nt].forEach(el => el.addEventListener('change', upd));
        return h('tr', null, h('td', { class: 'num' }, i + 1), h('td', null, lat), h('td', null, lon), h('td', null, alt), h('td', null, act), h('td', null, hold), h('td', null, nt),
          h('td', { class: 'num' }, h('div', { class: 'pill-group' },
            h('button', { class: 'btn sm', type: 'button', disabled: i === 0, title: 'Yukarı', onclick: () => { [wps[i - 1], wps[i]] = [wps[i], wps[i - 1]]; drawTbl(); } }, '↑'),
            h('button', { class: 'btn sm', type: 'button', disabled: i === wps.length - 1, title: 'Aşağı', onclick: () => { [wps[i + 1], wps[i]] = [wps[i], wps[i + 1]]; drawTbl(); } }, '↓'),
            h('button', { class: 'btn sm', type: 'button', title: 'Kopyala (altına)', onclick: () => { wps.splice(i + 1, 0, { ...w, action: 'waypoint' }); drawTbl(); } }, '⧉'),
            h('button', { class: 'btn sm danger', type: 'button', title: 'Sil', onclick: () => { wps.splice(i, 1); drawTbl(); } }, '✕'))));
      })))),
    h('div', { class: 'pill-group', style: { marginTop: '8px' } },
      h('button', { class: 'btn sm', type: 'button', onclick: () => { const l = wps[wps.length - 1]; wps.push({ lat: l ? l.lat : null, lon: l ? l.lon : null, alt: null, action: 'waypoint', hold_s: null, note: null }); drawTbl(); } }, '＋ Nokta ekle'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { const c = centers.find(x => x.id === num(center.value)); if (!c) return toast('Önce merkez seçin', 'err'); wps.push({ lat: c.lat, lon: c.lon, alt: null, action: 'waypoint', hold_s: null, note: 'Merkez' }); drawTbl(); } }, '＋ Merkezi ekle'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { const c = centers.find(x => x.id === num(center.value)); wps.push({ lat: c ? c.lat : (wps[0]?.lat ?? null), lon: c ? c.lon : (wps[0]?.lon ?? null), alt: null, action: 'rtl', hold_s: null, note: null }); drawTbl(); } }, '＋ Eve dön (RTL)')));
    drawPrev();
  };
  const save = async () => {
    const body = { name: name.value.trim(), center_id: num(center.value), kind: kind.value, cruise_alt: num(cAlt.value, 1), cruise_speed: num(cSpd.value, 1), note: note.value.trim() || null, active: active.checked,
      waypoints: wps.map(w => ({ lat: w.lat, lon: w.lon, alt: w.alt, action: w.action, hold_s: w.hold_s, note: w.note })) };
    if (!body.name) throw new Error('Rota adı gerekli');
    if (body.waypoints.some(w => w.lat == null || w.lon == null)) throw new Error('Her ara noktanın enlem ve boylamı dolu olmalı');
    await api.put(`/api/drone/routes/${id}`, body);
    toast('Rota kaydedildi');
  };
  const missionModal = async () => {
    await save();
    const ms = await api.get(`/api/drone/routes/${id}/mission`);
    const txt = JSON.stringify(ms.items, null, 1);
    modal({ title: 'MAVLink görevi (MISSION_ITEM_INT)', wide: true,
      body: h('div', null, h('p', { class: 'small muted' }, tr('{n} öğe · çerçeve GLOBAL_RELATIVE_ALT_INT · köprüye mission_upload komutuyla gönderilir.', { n: ms.items.length })),
        h('pre', { style: { maxHeight: '50vh', overflow: 'auto', fontSize: '12px' } }, txt)),
      actions: [{ label: 'Kapat' }, { label: 'JSON kopyala', class: 'primary', onClick: async () => { await copy(txt, 'Görev JSON kopyalandı'); return true; } }] });
  };
  const uploadModal = async () => {
    await save();
    const bridges = (await bridgesList()).filter(b => b.online);
    if (!bridges.length) throw new Error('Çevrimiçi köprü yok; görev yüklemek için pilot cihazındaki köprü bağlı olmalı');
    const bsel = sel(bridges.map(b => [b.id, b.name]), bridges[0].id);
    const sysid = inp(1, { type: 'number', min: 1, max: 255 });
    modal({ title: 'Görevi drona yükle',
      body: h('div', null, h('div', { class: 'row' }, field('Köprü', bsel), field('MAVLink sysid', sysid)),
        h('p', { class: 'small muted' }, 'Rota, köprü üzerinden drona MAVLink görevi olarak yüklenir (uçuş başlamaz; mod AUTO yapılınca izlenir). İşlem Pilot rolü ve Canlı Uçuş yazma yetkisi ister; kayda geçer.')),
      actions: [{ label: 'Vazgeç' }, { label: 'Yükle', class: 'primary', onClick: async () => {
        const ms = await api.get(`/api/drone/routes/${id}/mission`);
        const res = await api.post('/api/drone/live/cmd', { bridge_id: num(bsel.value), sysid: num(sysid.value) || 1, name: 'mission_upload', params: { items: ms.items, cruise_speed: ms.cruise_speed } });
        if (!res.ok) throw new Error(res.error || 'Köprü görevi kabul etmedi');
        toast('Görev drona yüklendi');
      } }] });
  };
  [kind, cSpd].forEach(el => el.addEventListener('change', drawPrev));
  clear(view,
    pageHead(r.name, { back: '#/field/routes', sub: `Rota · ${r.center_name || 'merkez yok'} · ${r.kind_text}`,
      right: h('div', { class: 'pill-group' },
        h('button', { class: 'btn sm', onclick: () => missionModal().catch(toastError) }, 'MAVLink görevi'),
        m.can.command ? h('button', { class: 'btn sm', onclick: () => uploadModal().catch(toastError) }, 'Drona yükle') : null,
        h('button', { class: 'btn sm primary', onclick: () => save().catch(toastError) }, 'Kaydet'),
        h('button', { class: 'btn sm danger', onclick: async () => {
          if (!await confirmDialog('Rotayı sil', tr('{name} silinsin mi?', { name: r.name }), { okLabel: 'Sil', danger: true })) return;
          await api.del(`/api/drone/routes/${id}`); toast('Rota silindi'); location.hash = '#/field/routes';
        } }, 'Sil')) }),
    h('div', { class: 'dr-route' },
      h('div', null,
        h('div', { class: 'card card-pad' },
          h('div', { class: 'row' }, field('Rota adı', name), field('Merkez', center)),
          h('div', { class: 'row' }, field('Tür', kind), field('Seyir irtifası (m, göreli)', cAlt, 'İrtifası boş noktalar bu değeri alır'), field('Seyir hızı (m/s)', cSpd)),
          h('div', { class: 'row' }, field('Not', note)), activeEl),
        h('div', { class: 'card card-pad', style: { marginTop: '14px' } }, h('h3', null, 'Ara noktalar'), tbl)),
      h('div', { class: 'card card-pad' }, h('h3', null, 'Önizleme'), prev, info,
        h('p', { class: 'small muted', style: { marginTop: '8px' } }, 'Yeşil: kalkış · Mavi: ara nokta · Mor: bekleme · Turuncu: eve dön · Kırmızı: iniş. Döngü rotada son nokta ilk noktaya bağlanır (DO_JUMP).'))));
  drawTbl();
}

// ======================================================================
// Canlı Uçuş
// ======================================================================
async function renderLive(view, ctx, m, head) {
  const side = h('div', { class: 'dr-side' });
  const mapBox = h('div', { class: 'dr-map' });
  const mapHolder = h('div', { class: 'r3d-map' });
  const mapMsg = h('div', { class: 'dr-map-msg' }, '3B harita yükleniyor…');
  const hud = h('div', { class: 'r3d-hud', hidden: true });
  const tools = h('div', { class: 'r3d-tools' });
  mapBox.append(mapHolder, mapMsg, hud, tools);
  const events = h('div', { class: 'dr-events' });
  const connBadge = h('span', { class: 'badge gray' }, 'Bağlanıyor…');
  const listEl = h('div');
  const cmdEl = h('div');
  side.append(h('div', { class: 'card' }, h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' } }, h('b', null, 'Köprüler ve dronlar'), h('span', { class: 'spacer' }), connBadge), listEl),
    h('div', { class: 'card' }, h('b', null, 'Komutlar'), cmdEl));
  clear(view, head('Canlı Uçuş · köprülerden gelen MAVLink telemetrisi (anlık)'),
    h('div', { class: 'dr-live' }, side, h('div', null, mapBox, h('div', { style: { marginTop: '10px' } }, h('div', { class: 'small muted', style: { marginBottom: '4px' } }, 'Olaylar (STATUSTEXT ve köprü bildirimleri)'), events))));

  // Durum deposu: key = `${bridge_id}:${sysid}` → state; bridges: id → info
  const bridges = new Map();     // bridge_id → { name, online, info }
  const states = new Map();      // key → state
  const inventory = new Map();   // `${bridge_id}:${sysid}` ya da `${bridge_id}:*` → envanter dronu
  let selected = null;           // seçili key
  let canCommand = false;
  try {
    const inv = await api.get('/api/drone/live');
    for (const d of inv.drones || []) if (d.bridge_id) inventory.set(`${d.bridge_id}:${d.sysid ?? '*'}`, d);
    canCommand = inv.can_command;
    for (const b of (await bridgesList())) bridges.set(b.id, { name: b.name, online: b.online, info: b.live });
  } catch { /* envanter yetkisi yoksa yalnız canlı veriler */ }
  const labelOf = key => { const [bid, sid] = key.split(':'); const d = inventory.get(key) || inventory.get(`${bid}:*`); return d ? `${d.code} · ${d.name}` : `sysid ${sid}`; };

  // ---- Cesium ----
  let Cesium = null, viewer = null;
  const ents = new Map();   // key → { entity, pos, ori, trail(PolylineCollection item), pts[] }
  let destroyed = false;
  let follow = true;
  loadCesium().then(C => {
    if (destroyed) return;
    Cesium = C;
    viewer = createViewer(Cesium, mapHolder, { timeline: false, animation: false });
    mapMsg.remove();
    hud.hidden = false;
    for (const key of states.keys()) placeOnMap(key);
    const btn = (label, fn, cls = '') => h('button', { class: `btn sm ${cls}`, type: 'button', onclick: fn }, label);
    const followBtn = btn('Takip et', () => { follow = !follow; followBtn.classList.toggle('primary', follow); if (follow && selected && ents.get(selected)) viewer.trackedEntity = ents.get(selected).entity; else viewer.trackedEntity = undefined; }, 'primary');
    clear(tools, followBtn, btn('Tümünü göster', () => { follow = false; followBtn.classList.remove('primary'); viewer.trackedEntity = undefined; viewer.zoomTo(viewer.entities).catch(() => {}); }));
  }).catch(err => {
    console.error('Canlı Uçuş haritası:', err);
    if (!mapMsg.isConnected) mapBox.append(mapMsg);
    clear(mapMsg, h('div', null, h('div', { class: 'alert err', style: { margin: 0 } }, err.message), h('div', { class: 'small', style: { marginTop: '8px', color: '#cbd5e1' } }, 'Harita olmadan da köprü/dron listesi ve anlık değerler çalışır.')));
  });
  const trailMat = () => Cesium.Material.fromType('Color', { color: Cesium.Color.fromCssColorString('#ffcc33').withAlpha(0.6) });
  let trails = null;
  const placeOnMap = key => {
    const st = states.get(key);
    if (!viewer || !st || st.lat == null || st.lon == null) return;
    const p = Cesium.Cartesian3.fromDegrees(st.lon, st.lat, Math.max(0, st.alt_rel ?? 0) + 1);
    let e = ents.get(key);
    if (!e) {
      const pos = new Cesium.ConstantPositionProperty(p);
      const ori = new Cesium.ConstantProperty(planeOrientation(Cesium, p, st.yaw ?? st.hdg, st.pitch, st.roll));
      const entity = viewer.entities.add({
        viewFrom: new Cesium.Cartesian3(-60, -60, 70), position: pos, orientation: ori, model: PLANE_MODEL,
        label: { text: labelOf(key), font: '13px sans-serif', pixelOffset: new Cesium.Cartesian2(0, -36), fillColor: Cesium.Color.WHITE, outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE, showBackground: true, backgroundColor: Cesium.Color.fromCssColorString('#0f172a').withAlpha(0.55), disableDepthTestDistance: Number.POSITIVE_INFINITY },
      });
      trails ??= viewer.scene.primitives.add(new Cesium.PolylineCollection());
      e = { entity, pos, ori, pts: [], line: null };
      ents.set(key, e);
      if (ents.size === 1) { viewer.zoomTo(entity).catch(() => {}); if (follow) viewer.trackedEntity = entity; }
    } else {
      e.pos.setValue(p);
      e.ori.setValue(planeOrientation(Cesium, p, st.yaw ?? st.hdg, st.pitch, st.roll));
    }
    const last = e.pts[e.pts.length - 1];
    if (!last || Cesium.Cartesian3.distance(last, p) > 1.5) {
      e.pts.push(p);
      if (e.pts.length > 1200) e.pts.shift();
      if (e.pts.length > 1) {
        if (e.line) trails.remove(e.line);
        e.line = trails.add({ positions: e.pts.slice(), width: 2, material: trailMat() });
      }
    }
    if (follow && selected === key) viewer.trackedEntity = e.entity;
  };

  // ---- Liste ve HUD ----
  const row = (k, v) => h('div', null, h('span', null, k), h('b', null, v));
  const drawList = () => {
    const items = [];
    const seen = new Set();
    for (const [bid, b] of bridges) {
      items.push(h('div', { class: 'dr-bridge' }, h('span', { class: `dr-dot ${b.online ? 'on' : ''}` }), h('b', null, b.name), b.online && b.info ? h('span', { class: 'small muted' }, ` · ${b.info.packets || 0} paket`) : h('span', { class: 'small muted' }, ' · çevrimdışı')));
      for (const [key, st] of states) {
        if (Number(key.split(':')[0]) !== bid) continue;
        seen.add(key);
        items.push(droneItem(key, st));
      }
    }
    for (const [key, st] of states) if (!seen.has(key)) items.push(droneItem(key, st));
    clear(listEl, items.length ? items : h('div', { class: 'small muted' }, 'Bağlı köprü yok. Pilot cihazındaki köprü yazılımı bağlanınca dronlar burada görünür.'));
  };
  const droneItem = (key, st) => h('div', { class: `dr-item ${selected === key ? 'on' : ''}`, onclick: () => { selected = key; drawList(); drawHud(); if (viewer && follow && ents.get(key)) viewer.trackedEntity = ents.get(key).entity; } },
    h('span', { class: `dr-dot ${st.last_hb && Date.now() / 1000 - st.last_hb < 5 ? 'on' : ''}` }),
    h('div', { class: 'grow' }, h('b', null, labelOf(key)), h('div', { class: 'small' }, liveLine(st))));
  const drawHud = () => {
    const st = selected ? states.get(selected) : null;
    if (!st) { clear(hud, h('div', { class: 'r3d-hud-head' }, h('b', null, '—'), h('span', { class: 'small muted' }, 'Dron seçin'))); drawCmd(); return; }
    const hbAge = st.last_hb ? Date.now() / 1000 - st.last_hb : null;
    clear(hud,
      h('div', { class: 'r3d-hud-head' }, h('b', { style: { fontSize: '14px' } }, labelOf(selected)),
        h('span', { class: `badge ${st.armed ? 'red' : 'gray'}` }, st.armed ? 'ARMED' : 'Disarmed'), st.mode ? h('span', { class: 'badge blue' }, st.mode) : null,
        hbAge != null && hbAge > 5 ? h('span', { class: 'badge yellow' }, `Kalp atışı ${Math.round(hbAge)} sn önce`) : null),
      row('İrtifa (göreli)', `${f1(st.alt_rel)} m`), row('İrtifa (MSL)', `${f1(st.alt)} m`),
      row('Yer hızı', `${f1(st.groundspeed)} m/s · ${Math.round((st.groundspeed || 0) * 3.6)} km/sa`), row('Hava hızı', `${f1(st.airspeed)} m/s`),
      row('Tırmanma', `${f1(st.climb)} m/s`), row('Gaz', st.throttle == null ? '—' : `%${st.throttle}`),
      row('Yön', `${f1(st.hdg)}°`), row('Roll / Pitch', `${f1(st.roll)}° / ${f1(st.pitch)}°`),
      row('Batarya', st.volt == null ? '—' : `${Number(st.volt).toFixed(2)} V${st.curr != null ? ` · ${f1(st.curr)} A` : ''}${st.batt_pct != null ? ` · %${st.batt_pct}` : ''}`),
      row('GPS', `${FIX[st.fix] || '—'}${st.sats != null ? ` · ${st.sats} uydu` : ''}${st.hdop != null ? ` · HDOP ${st.hdop}` : ''}`),
      st.rpm != null ? row('Motor', `${Math.round(st.rpm)} rpm`) : null,
      row('Konum', st.lat != null ? `${st.lat.toFixed(6)}, ${st.lon.toFixed(6)}` : '—'),
      row('Paket', String(st.msgs || 0)));
    drawCmd();
  };
  // ---- Komutlar ----
  const pending = new Map();   // rid → {resolve, reject, timer}
  const sendCmd = (name, params = {}) => new Promise((resolve, reject) => {
    if (!selected) return reject(new Error('Önce dron seçin'));
    if (!ws || ws.readyState !== 1) return reject(new Error('Sunucu bağlantısı yok'));
    const [bridge_id, sysid] = selected.split(':').map(Number);
    const rid = Math.random().toString(36).slice(2, 10);
    const timer = setTimeout(() => { pending.delete(rid); reject(new Error('Köprü yanıt vermedi (zaman aşımı)')); }, 15000);
    pending.set(rid, { resolve, reject, timer });
    ws.send(JSON.stringify({ t: 'cmd', rid, bridge_id, sysid, name, params }));
  });
  const run = async (label, name, params, confirmText) => {
    if (confirmText && !await confirmDialog(label, confirmText, { okLabel: label, danger: true })) return;
    try {
      const r = await sendCmd(name, params);
      if (r.ok) toast(tr('{label}: kabul edildi', { label })); else toast(tr('{label}: {err}', { label, err: r.error || 'reddedildi' }), 'err');
    } catch (err) { toastError(err); }
  };
  const drawCmd = () => {
    if (!canCommand) { clear(cmdEl, h('div', { class: 'small muted' }, 'Komut göndermek için Canlı Uçuş yazma yetkisi ve Pilot rolü gerekir.')); return; }
    const st = selected ? states.get(selected) : null;
    if (!st) { clear(cmdEl, h('div', { class: 'small muted' }, 'Komut için listeden dron seçin.')); return; }
    const mode = h('input', { class: 'input', list: 'dr-modes', placeholder: 'Mod (AUTO, RTL…)', style: { width: '140px' } });
    const dl = h('datalist', { id: 'dr-modes' }, MODES.map(x => h('option', { value: x })));
    const alt = h('input', { class: 'input', type: 'number', value: 50, min: 5, max: 1000, style: { width: '90px' }, title: 'Kalkış irtifası (m)' });
    clear(cmdEl,
      h('div', { class: 'pill-group', style: { flexWrap: 'wrap', marginTop: '6px' } },
        st.armed ? h('button', { class: 'btn sm danger', onclick: () => run('Disarm', 'disarm', {}, 'Motorlar durdurulsun mu (DISARM)? Havadaysa dron düşer.') }, 'Disarm')
          : h('button', { class: 'btn sm danger', onclick: () => run('Arm', 'arm', {}, 'Motorlar kurulsun mu (ARM)? Pervane dönebilir; çevrenin güvenli olduğundan emin olun.') }, 'Arm'),
        h('button', { class: 'btn sm', onclick: () => run('RTL', 'rtl', {}, 'Dron eve dönsün mü (RTL)?') }, 'Eve dön'),
        h('button', { class: 'btn sm', onclick: () => run('İniş', 'land', {}, 'Dron bulunduğu yere insin mi (LAND)?') }, 'İniş'),
        h('button', { class: 'btn sm', onclick: () => run('Kalkış', 'takeoff', { alt_rel_m: Number(alt.value) || 50 }, tr('{alt} m irtifaya kalkış verilsin mi?', { alt: alt.value })) }, 'Kalkış'), alt),
      h('div', { style: { display: 'flex', gap: '6px', marginTop: '6px' } }, mode, dl,
        h('button', { class: 'btn sm', onclick: () => { const v = mode.value.trim().toUpperCase(); if (!v) return toast('Mod girin', 'err'); run('Mod değiştir', 'set_mode', { mode: v }, tr('Uçuş modu {mode} yapılsın mı?', { mode: v })); } }, 'Modu ayarla')),
      h('div', { class: 'small muted', style: { marginTop: '6px' } }, 'Her komut kayda geçer (kim, ne zaman, hangi dron).'));
  };
  const addEvent = (bid, sysid, text, severity) => {
    const sev = severity == null ? '' : Number(severity) <= 3 ? 'sev-err' : Number(severity) === 4 ? 'sev-warn' : '';
    events.prepend(h('div', { class: sev }, h('span', { class: 'muted' }, new Date().toLocaleTimeString('tr-TR')), h('span', { class: 'muted' }, `${bridges.get(bid)?.name || `köprü ${bid}`}${sysid != null ? `/${sysid}` : ''}`), h('span', null, text)));
    while (events.children.length > 200) events.lastChild.remove();
  };

  // ---- WebSocket ----
  let ws = null, retry = null, pingIv = null;
  const handle = msg => {
    if (msg.t === 'hello') {
      canCommand = !!msg.me?.can_command;
      for (const b of msg.bridges || []) {
        const cur = bridges.get(b.bridge_id) || { name: b.name };
        bridges.set(b.bridge_id, { ...cur, name: b.name || cur.name, online: true, info: b });
        for (const [sid, st] of Object.entries(b.drones || {})) { const key = `${b.bridge_id}:${sid}`; states.set(key, st); placeOnMap(key); }
      }
      if (!selected && states.size) selected = states.keys().next().value;
      drawList(); drawHud();
    } else if (msg.t === 'status') {
      const key = `${msg.bridge_id}:${msg.sysid}`;
      const first = !states.has(key);
      states.set(key, msg.state);
      const b = bridges.get(msg.bridge_id); if (b && b.info) b.info.packets = (b.info.packets || 0) + 1;
      placeOnMap(key);
      if (!selected) selected = key;
      if (first) drawList(); else if (selected === key) { const it = listEl.querySelector('.dr-item.on .small'); if (it) clear(it, liveLine(msg.state)); }
      if (selected === key) drawHud();
    } else if (msg.t === 'bridge') {
      const cur = bridges.get(msg.bridge_id) || { name: msg.info?.name || `Köprü ${msg.bridge_id}` };
      bridges.set(msg.bridge_id, { ...cur, name: msg.info?.name || cur.name, online: !!msg.online, info: msg.info || cur.info });
      addEvent(msg.bridge_id, null, msg.online ? 'Köprü bağlandı' : `Köprü ayrıldı (${msg.status || ''})`, msg.online ? 6 : 4);
      if (!msg.online) for (const key of [...states.keys()]) if (Number(key.split(':')[0]) === msg.bridge_id) { const e = ents.get(key); if (e && viewer) { viewer.entities.remove(e.entity); if (e.line) trails.remove(e.line); } ents.delete(key); states.delete(key); if (selected === key) selected = null; }
      drawList(); drawHud();
    } else if (msg.t === 'event') addEvent(msg.bridge_id, msg.sysid, msg.text, msg.severity);
    else if (msg.t === 'res') { const p = pending.get(msg.rid); if (p) { clearTimeout(p.timer); pending.delete(msg.rid); p.resolve(msg); } }
    else if (msg.t === 'log') { addEvent(msg.bridge_id, null, `Uçuş logu alındı: ${msg.name} (#${msg.flight_log_id})`, 6); toast(tr('Köprüden uçuş logu alındı: {name}', { name: msg.name })); }
  };
  const connect = () => {
    if (destroyed) return;
    connBadge.textContent = 'Bağlanıyor…'; connBadge.className = 'badge gray';
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/drone/live`);
    ws.onopen = () => { connBadge.textContent = 'Bağlı'; connBadge.className = 'badge green'; };
    ws.onmessage = e => { try { handle(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    ws.onclose = ev => {
      if (destroyed) return;
      connBadge.textContent = ev.code === 4403 ? 'Yetki yok' : 'Bağlantı koptu'; connBadge.className = 'badge red';
      for (const [, p] of pending) { clearTimeout(p.timer); p.reject(new Error('Bağlantı koptu')); }
      pending.clear();
      if (ev.code !== 4403) retry = setTimeout(connect, 3000);
    };
  };
  connect();
  pingIv = setInterval(() => { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ t: 'ping' })); drawList(); }, 20000);
  onLeave(() => {
    destroyed = true;
    clearTimeout(retry); clearInterval(pingIv);
    try { ws?.close(); } catch { /* yok */ }
    if (viewer && !viewer.isDestroyed()) viewer.destroy();
  });
  drawList(); drawHud();
}
