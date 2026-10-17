// Dron Yönetimi (Saha Yönetimi alt modülleri — Faz 1): Dron Envanteri, Canlı Uçuş, Rotalar, Dron Köprüleri.
// Adresler: #/drone/drones[/id] · #/field/live?task=<görev id> · #/drone/routes (routes.js) · #/drone/bridges
// Bağlantı bilgileri (köprü, seri/tcp/udp, sysid) DRON KAYDINDA TUTULMAZ; saha görevindeki uçuş (field_flights) düzeyinde seçilir.
// Canlı telemetri: /ws/drone/live (oturum çerezi) — harekât ekranı (static/ops) yalnız bir saha görevi bağlamında açılır.
import { api } from '../api.js';
import {
  clear, confirmDialog, every, field, fmtDateTime, h, matches, modal, moduleTabs, moduleToolbar, onLeave, pageHead, segmented, statStrip,
  toast, t as tr,
} from '../ui.js';

// Canlı Uçuş sekmesi yok: harekât ekranı yalnız saha görevinden açılır (#/field/live?task=<id>; renderLive aşağıda)
// Uçuş Simülatörü (#/drone/sim[/<oturum>]): flightsim.js dinamik yüklenir; yetki m.can.sim (RBAC 'drone.sim'). `?mock=1` arka uçsuz deneme.
const TABS = [['drones', 'Dron Envanteri'], ['routes', 'Rotalar'], ['bridges', 'Dron Köprüleri'], ['sim', 'Uçuş Simülatörü']];
const DRONE_BADGE = { AKTIF: 'green', BAKIMDA: 'yellow', ARIZALI: 'red', PASIF: 'gray' };
const SESSION_BADGE = { ACIK: 'green', KAPANDI: 'gray', KOPTU: 'red', KESILDI: 'yellow' };
// Dron türü (protocol): ürettiğimiz tüm Caymaz dronları MAVLink; sanal dron sunucu içi simülatör (köprü gerekmez); DJI ileride.
const PROTOCOLS = [['mavlink', 'MAVLink'], ['sanal', 'Sanal Dron'], ['dji', 'DJI']];
const PROTO_TEXT = Object.fromEntries(PROTOCOLS);
const PROTO_BADGE = { mavlink: 'blue', sanal: 'purple', dji: 'teal' };
const f1 = v => (v == null ? '—' : Number(v).toFixed(1));
const num = (v, d = 0) => (v == null || v === '' || Number.isNaN(Number(v)) ? null : Number(Number(v).toFixed(d)));
const ago = iso => { if (!iso) return '—'; const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000); return s < 60 ? `${Math.round(s)} sn önce` : s < 3600 ? `${Math.round(s / 60)} dk önce` : fmtDateTime(iso); };
const copy = async (txt, what = 'Kopyalandı') => { try { await navigator.clipboard.writeText(txt); toast(what); } catch { toast('Kopyalanamadı; metni elle seçin', 'err'); } };
const bridgeWsUrl = () => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/drone/bridge`;

export async function render(view, params, ctx) {
  const m = await api.get('/api/drone/meta');
  // Sahte veri kipi (?mock=1): simülatör arayüzü arka uç/yetki olmadan denenir (sorgu dizesi params'ın herhangi bir parçasında olabilir)
  const simMock = String(params[0] || '').split('?')[0] === 'sim' && new URLSearchParams(String(params.join('/')).split('?')[1] || '').get('mock') === '1';
  const tabs = TABS.filter(([k]) => m.can[k] || (k === 'sim' && simMock));
  // Görevden açılan Canlı Uçuş (#/field/live?task=<id>): yetki görev üyeliğiyle sunucuda denetlenir (/api/field/tasks/{id}/live);
  // Dron Yönetimi sekme yetkisi olmayan görev pilotu da açabilmeli.
  {
    const [pg, q] = String(params[0] || '').split('?');
    if (pg === 'live') {
      const head = sub => pageHead('Canlı Uçuş', { back: '#/field', sub });
      return renderLive(view, ctx, m, head, new URLSearchParams(q || ''));
    }
  }
  if (!tabs.length) {
    clear(view, pageHead('Dron Yönetimi', { back: '#/' }),
      h('div', { class: 'card empty' }, 'Dron Yönetimi için yetkiniz yok. Rol Yönetimi › Saha & Operasyon › Dron Yönetimi rolünüze açılmalı.'));
    return;
  }
  // params[0] 'live?task=5' biçiminde gelebilir (yönlendirici hash'i '/' ile böler, sorgu dizesi ilk parçada kalır)
  const [page, qs] = String(params[0] || '').split('?');
  const want = TABS.some(([k]) => k === page) ? page : tabs[0][0];
  const cur = (m.can[want] || (want === 'sim' && simMock)) ? want : tabs[0][0];
  const head = sub => pageHead('Dron Yönetimi', { back: '#/', sub, tabs: moduleTabs(tabs, cur, k => { location.hash = `#/drone/${k}`; }) });
  if (cur === 'sim') {
    // Uçuş Simülatörü ayrı modülde (flightsim.js: sihirbaz + tam alan 3B oturum ekranı); yalnız gerekince yüklenir.
    const fs = await import('./flightsim.js');
    return fs.render(view, params, ctx, { m, head, mock: simMock });
  }
  if (cur === 'drones') return params[1] ? renderDroneDetail(view, Number(params[1]), ctx, m) : renderDrones(view, ctx, m, head);
  if (cur === 'routes') {
    // Rotalar sekmesi ayrı modülde (routes.js: sol dar sütun + Cesium harita); yalnız gerekince yüklenir.
    const routes = await import('./routes.js');
    return routes.render(view, ctx, m, head, params);
  }
  return renderBridges(view, ctx, m, head);
}

// ---------- yardımcılar ----------
const people = role => api.get(`/api/people?role=${encodeURIComponent(role)}`).catch(() => []);
const sel = (options, value, { empty } = {}) => h('select', { class: 'input' },
  empty != null ? h('option', { value: '' }, empty) : null,
  options.map(([k, label]) => h('option', { value: k, selected: String(k) === String(value ?? '') }, label)));
const inp = (value, attrs = {}) => h('input', { class: 'input', value: value ?? '', ...attrs });
const check = (label, on) => { const cb = h('input', { type: 'checkbox', checked: !!on }); return [h('label', { class: 'check' }, cb, label), cb]; };
const onlineBadge = on => h('span', { class: `badge ${on ? 'green' : 'gray'}` }, on ? 'Çevrimiçi' : 'Çevrimdışı');
const protoText = d => d.protocol_text || PROTO_TEXT[d.protocol] || d.protocol || '—';
const protoBadge = d => h('span', { class: `badge ${PROTO_BADGE[d.protocol] || 'gray'}` }, protoText(d));
const liveLine = st => (st ? [st.mode ? h('span', { class: 'badge blue' }, st.mode) : null, h('span', { class: `badge ${st.armed ? 'red' : 'gray'}` }, st.armed ? 'ARMED' : 'Disarmed'),
  st.alt_rel != null ? h('span', { class: 'small muted' }, ` ${f1(st.alt_rel)} m · ${f1(st.groundspeed)} m/s`) : null] : null);
const liveHref = taskId => `#/field/live?task=${taskId}`;

// ======================================================================
// Dron Envanteri
// ======================================================================
async function renderDrones(view, ctx, m, head) {
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kod, ad, model, seri, pilot ara…', style: { width: '260px' } });
  const status = sel([['', 'Tüm durumlar'], ...Object.entries(m.drone_status)], '');
  const proto = sel([['', 'Tüm türler'], ...PROTOCOLS], '');
  const stats = statStrip();
  const body = h('div');
  let rows = [];
  const draw = () => {
    const list = rows.filter(d => (!status.value || d.status === status.value) && (!proto.value || d.protocol === proto.value)
      && matches(q.value, d.code, d.name, d.model, d.serial, d.pilot_name, protoText(d)));
    stats.set([
      { icon: 'fleet', label: 'Kayıtlı dron', value: rows.filter(d => d.active).length },
      { icon: 'documents', label: 'Sanal dron', value: rows.filter(d => d.protocol === 'sanal').length, tone: 'muted' },
      { icon: 'note', label: 'Açık görevde', value: rows.filter(d => d.open_task_code).length },
      { icon: 'warning', label: 'Bakım / arıza', value: rows.filter(d => ['BAKIMDA', 'ARIZALI'].includes(d.status)).length },
    ]);
    clear(body, list.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Kod', 'Dron', 'Tür', 'Pilot', 'Durum', 'Görev', 'Son log'].map(c => h('th', null, c)))),
      h('tbody', null, list.map(d => h('tr', { class: 'click', onclick: () => { location.hash = `#/drone/drones/${d.id}`; } },
        h('td', null, h('b', { class: 'mono' }, d.code), d.active ? null : h('div', null, h('span', { class: 'badge gray' }, 'Pasif'))),
        h('td', null, h('b', null, d.name), h('div', { class: 'small muted' }, [d.model, d.serial ? `SN ${d.serial}` : null].filter(Boolean).join(' · '))),
        h('td', null, protoBadge(d)),
        h('td', null, d.pilot_name || h('span', { class: 'muted' }, '—')),
        h('td', null, h('span', { class: `badge ${DRONE_BADGE[d.status] || 'gray'}` }, d.status_text)),
        h('td', null, d.open_task_code ? h('span', { class: 'badge blue' }, d.open_task_code) : h('span', { class: 'small muted' }, tr('{n} görev', { n: d.task_count }))),
        h('td', { class: 'small muted' }, d.last_log_at ? fmtDateTime(d.last_log_at) : '—'))))))
      : h('div', { class: 'card empty' }, rows.length ? 'Filtreye uyan dron yok'
        : 'Henüz dron eklenmedi. "Yeni Dron" ile envantere ekleyin. Üretimden gelen kuyruk numaralı Caymaz uçakları zaten MAVLink dronudur; burada ayrıca eklenmez. Bağlantı (köprü, seri/tcp/udp, sysid) saha görevindeki uçuşta seçilir.'));
  };
  const load = async () => { rows = await api.get('/api/drone/drones'); draw(); };
  q.addEventListener('input', draw);
  status.addEventListener('change', draw);
  proto.addEventListener('change', draw);
  clear(view, head('Dron Envanteri · kayıtlı dronlar, türleri ve görev geçmişi'),
    stats,
    moduleToolbar(h('button', { class: 'btn primary', onclick: () => droneForm(null, m, load) }, '＋ Yeni Dron'), q, proto, status),
    body);
  await load();
  every(15000, () => load().catch(() => {}));
}

// Dron formu: tür (MAVLink / Sanal Dron / DJI), kimlik ve sorumlu pilot. Bağlantı bilgisi burada yok (uçuş düzeyinde).
async function droneForm(d, m, done) {
  const pilots = await people('Pilot');
  const name = inp(d?.name, { placeholder: 'Örn. Göktungu-1', maxlength: 120 });
  const model = inp(d?.model, { placeholder: 'Örn. GT-1 VTOL', maxlength: 80 });
  const serial = inp(d?.serial, { placeholder: 'Seri no', maxlength: 80 });
  let protocol = PROTO_TEXT[d?.protocol] ? d.protocol : 'mavlink';
  const protoHint = h('div', { class: 'hint' });
  const hints = {
    mavlink: 'ArduPilot / PX4 uçuş kontrolcüsü. Bağlantı (köprü, seri/tcp/udp, sysid) saha görevindeki uçuşta seçilir.',
    sanal: 'Sunucu içi simülatör: köprü gerekmez; Canlı Uçuş\'ta gerçek dron gibi uçar (eğitim ve deneme için).',
    dji: 'DJI SDK köprüsü ile telemetri; MAVLink komutları sınırlıdır.',
  };
  const setHint = () => { protoHint.textContent = hints[protocol] || ''; };
  const protoSeg = segmented(PROTOCOLS, protocol, k => { protocol = k; setHint(); });
  setHint();
  const pilot = sel(pilots.map(p => [p.id, p.full_name]), d?.pilot_id, { empty: 'Pilot seçilmedi' });
  const status = sel(Object.entries(m.drone_status), d?.status || 'AKTIF');
  const note = h('textarea', { class: 'input', rows: 2 }, d?.note || '');
  const [activeEl, active] = check('Aktif (görevlere seçilebilir)', d ? d.active : true);
  modal({
    title: d ? tr('{code} · Dron bilgileri', { code: d.code }) : 'Yeni Dron',
    wide: true,
    body: h('div', null,
      h('div', { class: 'field' }, h('label', null, 'Tür'), protoSeg, protoHint),
      h('div', { class: 'row' }, field('Dron adı', name), field('Model', model)),
      h('div', { class: 'row' }, field('Seri no', serial), field('Sorumlu pilot', pilot)),
      h('div', { class: 'row' }, field('Durum', status), field('Not', note)),
      activeEl),
    actions: [{ label: 'Vazgeç' }, {
      label: d ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const body = {
          name: name.value.trim(), model: model.value.trim() || null, serial: serial.value.trim() || null, protocol,
          pilot_id: num(pilot.value), status: status.value, note: note.value.trim() || null, active: active.checked,
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
    const flights = d.flights || [];
    const sessions = Array.isArray(d.sessions) ? d.sessions : [];
    const kv = (k, v) => [h('dt', null, k), h('dd', null, v == null || v === '' ? h('span', { class: 'muted' }, '—') : v)];
    // Canlı Uçuş yalnız açık saha görevi bağlamında: dronun açık görevdeki uçuşu varsa oraya bağlan
    const openFlight = flights.find(f => ['BASLANGIC', 'GOREVDE'].includes(f.task_status) && f.task_id);
    clear(view,
      pageHead(`${d.code} · ${d.name}`, {
        back: '#/drone/drones', sub: [protoText(d), d.model, d.serial ? `SN ${d.serial}` : null, d.status_text].filter(Boolean).join(' · '),
        right: h('div', { class: 'pill-group' },
          m.can.live && openFlight ? h('a', { class: 'btn sm', href: liveHref(openFlight.task_id) }, 'Canlı Uçuş') : null,
          h('button', { class: 'btn sm primary', onclick: () => droneForm(d, m, load) }, 'Bilgileri düzenle'),
          h('button', { class: 'btn sm danger', onclick: async () => {
            if (!await confirmDialog('Dronu sil', tr('{code} silinsin mi? Uçuş geçmişi varsa silinmez, pasife alınır.', { code: d.code }), { okLabel: 'Sil', danger: true })) return;
            const r = await api.del(`/api/drone/drones/${d.id}`);
            toast(r.deactivated ? 'Dron pasife alındı (uçuş geçmişi var)' : 'Dron silindi');
            location.hash = '#/drone/drones';
          } }, 'Sil')),
      }),
      h('div', { class: 'grid-2', style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', alignItems: 'start' } },
        h('div', { class: 'card card-pad' }, h('h3', null, 'Genel bilgiler'),
          h('dl', { class: 'kv' },
            ...kv('Durum', h('span', { class: `badge ${DRONE_BADGE[d.status] || 'gray'}` }, d.status_text)),
            ...kv('Tür', protoBadge(d)),
            ...kv('Sorumlu pilot', d.pilot_name),
            ...kv('Üretim bağı', d.order_code ? `${d.queue_no || ''} ${d.order_code}`.trim() : null),
            ...kv('Açık görev', d.open_task_code ? h('span', { class: 'badge blue' }, d.open_task_code) : null),
            ...kv('Not', d.note),
            ...kv('Kayıt', d.created_at ? fmtDateTime(d.created_at) : null))),
        h('div', { class: 'card card-pad' }, h('h3', null, 'Bağlantı'),
          d.protocol === 'sanal'
            ? h('div', { class: 'small muted' }, h('span', { class: 'badge purple' }, 'Sanal Dron'), ' Sunucu içi simülatör: köprü ve bağlantı ayarı gerekmez; görevin Canlı Uçuş ekranında otomatik bağlı görünür.')
            : h('div', { class: 'small muted' }, 'Bağlantı bilgileri (köprü, seri/tcp/udp, MAVLink sysid) dron kaydında tutulmaz; saha görevi › Uçuş Yönetimi › Düzenle penceresinin "Bağlantı" panelinde uçuş başına seçilir.'))),
      h('div', { class: 'card card-pad', style: { marginTop: '14px' } }, h('h3', null, tr('Uçuşlar ({n})', { n: flights.length })),
        flights.length ? h('div', { class: 'table-wrap' }, h('table', null,
          h('thead', null, h('tr', null, ['Saha görevi', 'Durum', 'Görev yeri', 'Başladı', 'Uçuş logu', 'Havada', ''].map(c => h('th', null, c)))),
          h('tbody', null, flights.map(f => h('tr', { class: 'click', onclick: () => { location.hash = `#/field/flight/${f.id}`; } },
            h('td', null, h('b', null, f.task_code)), h('td', null, f.task_status), h('td', null, f.location_name || '—'),
            h('td', { class: 'small muted' }, f.started_at ? fmtDateTime(f.started_at) : '—'),
            h('td', null, f.log_status ? h('span', { class: `badge ${f.log_status === 'TAMAM' ? 'green' : f.log_status === 'HATA' ? 'red' : 'yellow'}` }, f.log_status) : h('span', { class: 'muted' }, 'Yok'),
              f.log_source === 'BRIDGE' ? h('span', { class: 'small muted' }, ' köprüden') : null),
            h('td', null, f.flight_s != null ? `${Math.floor(f.flight_s / 60)} dk ${Math.round(f.flight_s % 60)} sn` : '—'),
            h('td', { class: 'num' }, h('div', { class: 'pill-group' },
              m.can.live && ['BASLANGIC', 'GOREVDE'].includes(f.task_status) && f.task_id ? h('a', { class: 'btn sm', href: liveHref(f.task_id), onclick: e => e.stopPropagation() }, 'Canlı Uçuş') : null,
              f.log_status === 'TAMAM' ? h('a', { class: 'btn sm', href: `#/field/report/${f.log_id}`, onclick: e => e.stopPropagation() }, 'Uçuş Raporu') : null)))))))
          : h('div', { class: 'small muted' }, 'Bu dron henüz bir saha görevine eklenmedi. Görev detayı › Uçuş Yönetimi › "Dron Ekle" ile ya da Yeni Saha Görevi penceresinden eklenir.')),
      sessions.length ? h('div', { class: 'card card-pad', style: { marginTop: '14px' } }, h('h3', null, 'Köprü oturumları'), sessionsTable(sessions)) : null);
  };
  clear(view, box);
  await load();
}

const sessionsTable = rows => h('div', { class: 'table-wrap' }, h('table', null,
  h('thead', null, h('tr', null, ['Köprü', 'Başladı', 'Bitti', 'Durum', 'Paket', 'Dron', 'Hata'].map(c => h('th', null, c)))),
  h('tbody', null, rows.map(s => h('tr', null,
    h('td', null, s.bridge_name || '—'), h('td', { class: 'small' }, fmtDateTime(s.started_at)), h('td', { class: 'small' }, s.ended_at ? fmtDateTime(s.ended_at) : h('span', { class: 'badge green' }, 'Açık')),
    h('td', null, h('span', { class: `badge ${SESSION_BADGE[s.status] || 'gray'}` }, s.status_text || s.status)),
    h('td', { class: 'num' }, s.packets), h('td', null, s.drone_code || '—'), h('td', { class: 'small muted' }, s.error || ''))))));

// ======================================================================
// Dron Köprüleri — köprü kodu: köprü eklenince <domain>/<key> verilir (bir kez); köprü yazılımına girilince köprü bu şirkete ve
// kullanıcıya bağlanır (Entegrasyonlar'daki ajan API anahtarı kalıbı). 6 haneli eşleştirme kodu ikincil yol olarak kalır.
// ======================================================================
function codeModal(name, code, { renewed = false } = {}) {
  modal({
    title: tr(renewed ? '{name} · yeni köprü kodu' : '{name} · köprü kodu', { name }),
    body: h('div', null,
      h('div', { class: 'dr-key dr-code' }, code),
      h('p', { class: 'small', style: { marginTop: '10px' } }, h('b', null, 'Köprü yazılımına bu kodu girin.'),
        ' Köprü, kodla bu şirkete ve size bağlanır; sunucu adresini koddaki alan adından bulur. Kod bir daha gösterilmez; kaybolursa "Kodu yenile" ile yenisi üretilir.'),
      renewed ? h('p', { class: 'small muted' }, 'Eski kod hemen geçersiz oldu; bağlı köprü düştüyse yeni kodla yeniden bağlanmalıdır.') : null),
    actions: [{ label: 'Kapat' }, { label: 'Kopyala', class: 'primary', onClick: async () => { await copy(code, 'Köprü kodu kopyalandı'); return true; } }],
  });
}

async function renderBridges(view, ctx, m, head) {
  const body = h('div');
  const stats = statStrip();
  let rows = [];
  const draw = () => {
    stats.set([
      { icon: 'fleet', label: 'Köprü', value: rows.filter(b => b.active).length },
      { icon: 'documents', label: 'Çevrimiçi', value: rows.filter(b => b.online).length, tone: 'ok' },
      { icon: 'warning', label: 'Hiç bağlanmamış', value: rows.filter(b => !b.online && !b.last_seen).length },
    ]);
    clear(body, rows.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Köprü', 'Platform', 'Sahibi', 'Bağlantı', 'Cihaz', 'Canlı dron', ''].map(c => h('th', null, c)))),
      h('tbody', null, rows.map(b => h('tr', null,
        h('td', null, h('b', null, b.name), b.active ? null : h('span', { class: 'badge gray', style: { marginLeft: '6px' } }, 'Pasif'),
          h('div', { class: 'small muted' }, b.note || '')),
        h('td', null, b.platform || '—'),
        h('td', null, b.owner_name || h('span', { class: 'muted' }, '—')),
        h('td', null, onlineBadge(b.online), h('div', { class: 'small muted' }, b.online ? tr('{n} paket · oturum #{s}', { n: b.live?.packets || 0, s: b.live?.session_id || '' })
          : b.last_seen ? `Son görülme ${ago(b.last_seen)}` : 'Hiç bağlanmadı'),
          b.has_key ? null : h('span', { class: 'badge yellow' }, 'Kodu yok')),
        h('td', { class: 'small' }, b.host || '—', h('div', { class: 'muted' }, b.bridge_ver ? `sürüm ${b.bridge_ver}` : '')),
        h('td', null, b.online && b.live?.drones && Object.keys(b.live.drones).length
          ? h('div', { class: 'small' }, Object.values(b.live.drones).map(st => h('div', null, `sysid ${st.sysid}: `, liveLine(st))))
          : h('span', { class: 'muted' }, '—')),
        h('td', { class: 'num' }, h('div', { class: 'pill-group' },
          h('button', { class: 'btn sm primary', title: 'Köprü yazılımına girilecek köprü kodunu yeniden üretir; eski kod geçersiz olur', onclick: () => rekey(b) }, 'Kodu yenile'),
          h('button', { class: 'btn sm', title: 'Tek kullanımlık 6 haneli eşleştirme kodu (10 dk) — ikincil yol', onclick: () => pairModal(b) }, 'Eşleştir'),
          h('button', { class: 'btn sm', onclick: () => sessionsModal(b) }, 'Oturumlar'),
          b.online ? h('button', { class: 'btn sm', onclick: async () => {
            if (!await confirmDialog('Bağlantıyı kes', tr('{name} köprüsünün bağlantısı kesilsin mi? Köprü yeniden bağlanabilir.', { name: b.name }), { okLabel: 'Kes', danger: true })) return;
            await api.post(`/api/drone/bridges/${b.id}/disconnect`); toast('Bağlantı kesildi'); load();
          } }, 'Bağlantıyı kes') : null,
          h('button', { class: 'btn sm', onclick: () => bridgeForm(b, m, load) }, 'Düzenle'),
          h('button', { class: 'btn sm danger', onclick: async () => {
            if (!await confirmDialog('Köprüyü sil', tr('{name} silinsin mi? Oturum geçmişi silinir; uçuşlardaki köprü seçimi boşa düşer.', { name: b.name }), { okLabel: 'Sil', danger: true })) return;
            await api.del(`/api/drone/bridges/${b.id}`); toast('Köprü silindi'); load();
          } }, 'Sil'))))))))
      : h('div', { class: 'card empty' }, 'Henüz köprü yok. Köprü, pilotun telefonundaki / bilgisayarındaki yazılımdır: drona yerel bağlanır, telemetriyi sunucuya taşır. "Yeni Köprü" ekleyin; verilen köprü kodunu köprü yazılımına girince köprü bu şirkete ve size bağlanır.'));
  };
  const load = async () => { rows = await api.get('/api/drone/bridges'); draw(); };
  const rekey = async b => {
    if (!await confirmDialog('Kodu yenile', tr('{name} için yeni köprü kodu üretilsin mi? Eski kod hemen geçersiz olur; bağlı köprü düşer ve yeni kodla yeniden bağlanmalıdır.', { name: b.name }), { okLabel: 'Yenile', danger: true })) return;
    const r = await api.post(`/api/drone/bridges/${b.id}/rekey`);
    codeModal(b.name, r.code || r.key, { renewed: true });
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
  clear(view, head('Dron Köprüleri · pilot cihazındaki köprü yazılımları, köprü kodu ve oturumlar'),
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
  const platform = sel((m.platforms || []).map(p => [p, p]), b?.platform, { empty: 'Seçilmedi' });
  const owner = sel(pilots.map(p => [p.id, p.full_name]), b?.owner_id, { empty: 'Sahibi seçilmedi' });
  const note = h('textarea', { class: 'input', rows: 2 }, b?.note || '');
  const [activeEl, active] = check('Aktif (bağlanabilir)', b ? b.active : true);
  modal({
    title: b ? 'Köprü bilgileri' : 'Yeni Köprü',
    body: h('div', null, field('Köprü adı', name), h('div', { class: 'row' }, field('Platform', platform), field('Sahibi (pilot)', owner)), field('Not', note), activeEl,
      b ? null : h('p', { class: 'small muted' }, 'Eklenince bir köprü kodu verilir (bir kez gösterilir). Köprüyü kuran kişi bu kodu köprü yazılımına girer; köprü otomatik bu şirkete ve size bağlanır.')),
    actions: [{ label: 'Vazgeç' }, {
      label: b ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const body = { name: name.value.trim(), platform: platform.value || null, owner_id: num(owner.value), note: note.value.trim() || null, active: active.checked };
        if (!body.name) throw new Error('Köprü adı gerekli');
        if (b) { await api.put(`/api/drone/bridges/${b.id}`, body); toast('Köprü güncellendi'); done?.(); return; }
        const r = await api.post('/api/drone/bridges', body);
        toast('Köprü eklendi');
        done?.();
        if (r?.code) codeModal(body.name, r.code);
      },
    }],
  });
}

// ======================================================================
// Canlı Uçuş — GÖKTUNGU harekât arayüzü (/static/ops/index.html) bir iframe içinde, YALNIZ saha görevi bağlamında (?task=<id>):
// ekran o göreve bağlı uçakları/dronları gösterir; serbest uçuş yok. Sayfa data-immersive taşır: HEPGO'nun kendi tam ekran
// düğmesi üst başlığı ve alt barı gizler (app.js body.immersive). iframe → parent gezinme: {t:'ops-nav', hash:'#/field/…'}.
// Aynı köken: oturum çerezi ve /ws/drone/live paylaşılır.
// ======================================================================
async function renderLive(view, ctx, m, head, sp) {
  const task = Number(sp?.get('task')) || 0;
  if (!task) {
    clear(view, head('Canlı Uçuş · harekât ekranı yalnız saha görevinden açılır'),
      h('div', { class: 'card empty dr-live-info' },
        h('p', null, h('b', null, 'Canlı Uçuş yalnız bir saha görevi üzerinden açılır.')),
        h('p', { class: 'small muted' }, 'Serbest uçuş yok: harekât ekranı, görevin Uçuş Yönetimi\'ne eklenen uçak ve dronları gösterir; bağlantı (köprü, seri/tcp/udp, sysid) uçuş başına orada seçilir. Görev detayındaki "Canlı Uçuş" düğmesini kullanın.'),
        h('div', { class: 'pill-group', style: { justifyContent: 'center' } },
          h('a', { class: 'btn primary', href: '#/field' }, 'Saha görevleri'))));
    return;
  }
  const ver = (document.querySelector('script[src*="app.js"]')?.src.match(/[?&]v=([^&]+)/) || [])[1] || '';
  const frame = h('iframe', { class: 'ops-frame', src: `/static/ops/index.html?task=${encodeURIComponent(task)}${ver ? `&v=${encodeURIComponent(ver)}` : ''}`,
    allow: 'geolocation', title: tr('Canlı Uçuş — görev {id} harekât ekranı', { id: task }) });
  view.classList.add('ops-view');
  view.dataset.immersive = '1';   // HEPGO tam ekran → başlık/alt bar gizlenir
  const scroller = view.closest('.scroller');
  scroller?.classList.add('ops-scroll');
  const onMsg = e => {
    if (e.origin !== location.origin || e.source !== frame.contentWindow || !e.data || typeof e.data !== 'object') return;
    if (e.data.t === 'ops-nav' && typeof e.data.hash === 'string' && e.data.hash.startsWith('#/')) location.hash = e.data.hash;
  };
  window.addEventListener('message', onMsg);
  onLeave(() => {
    window.removeEventListener('message', onMsg);
    delete view.dataset.immersive;
    document.body.classList.remove('immersive');
    view.classList.remove('ops-view');
    scroller?.classList.remove('ops-scroll');
  });
  clear(view, frame);
}
