// İş Güvenliği: kamera tabanlı kural denetimi (KKD, bölge / erişim, davranış, araç, nesne, ergonomi).
// Sekmeler: Uyarılar (kare + klip, kapatma) · Canlı İzleme (kutular + ihlaller) · Kurallar (aç/kapat, risk, parametre) ·
// KKD Grupları (senaryo grubu: donanım + donanım başına ayar, kameraya atama) · Bölgeler (kamera görüntüsü üzerinde poligon çizimi) · Isı Haritası · Raporlar (güvenlik puanı, kırılımlar, Excel) · Ayarlar.
// Tespit fabrikadaki kamera servisinde yapılır (app/worksafety_worker.py); bu ekran yapılandırır ve sonuçları gösterir.
// API: /api/worksafety/* (app/routers/worksafety.py). Stil: static/css/worksafety.css (modülle aynı sürümlü yoldan yüklenir).
import { api, fileUrl, videoUrl } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, moduleTabs, moduleToolbar, multiSelect, onLeave, pageHead, periodFilter,
  pref, segmented, selectInput, setPref, statStrip, toast, toastError } from '../ui.js';
import { setListExport } from '../listexport.js';

const TABS = [['', 'Uyarılar'], ['live', 'Canlı İzleme'], ['rules', 'Kurallar'], ['groups', 'KKD Grupları'], ['zones', 'Bölgeler'],
  ['heat', 'Isı Haritası'], ['report', 'Raporlar'], ['settings', 'Ayarlar']];
const LEVELS = [[20, 'KRİTİK', 'krit'], [15, 'CİDDİ RİSK', 'ciddi'], [10, 'YÜKSEK', 'yuksek'], [5, 'ORTA', 'orta'], [0, 'DÜŞÜK', 'dusuk']];
const levelOf = risk => LEVELS.find(l => risk >= l[0]) || LEVELS[4];
const levelCls = name => (LEVELS.find(l => l[1] === name) || LEVELS[4])[2];
const levelBadge = name => h('span', { class: `ws-lv ${levelCls(name)}` }, name || '—');
const PARAM_LABEL = {
  objects: 'Yasak nesneler', from: 'Başlangıç saati', to: 'Bitiş saati', pose: 'Duruşla (iskelet) doğrula', speed: 'Hız eşiği (boy / sn)',
  dist: 'Mesafe eşiği (kişi boyunun katı)', gap: 'Araçlar arası boşluk (araç genişliğinin katı)', ratio: 'Engel alanı (bölgenin oranı)',
  seconds: 'Süre (sn)', min: 'En düşük puan',
};
const ZONE_PARAM_LABEL = { min: 'En az kişi', max: 'En çok kişi', from: 'Yasak başlangıç saati', to: 'Yasak bitiş saati',
  dir: 'Akış yönü (derece: 0 = sağa, 90 = aşağı)', auth_colors: 'Yetkili kıyafet renkleri', items: 'Zorunlu donanım', group: 'KKD senaryo grubu' };
const OBJ_TR = {
  bicycle: 'Bisiklet', car: 'Otomobil', motorcycle: 'Motosiklet', bus: 'Otobüs', truck: 'Kamyon', backpack: 'Sırt çantası', umbrella: 'Şemsiye',
  handbag: 'El çantası', suitcase: 'Valiz', bottle: 'Şişe', 'wine glass': 'Kadeh', cup: 'Bardak', fork: 'Çatal', knife: 'Bıçak', spoon: 'Kaşık',
  bowl: 'Kâse', chair: 'Sandalye', couch: 'Kanepe', bed: 'Yatak', 'dining table': 'Masa', tv: 'Ekran', laptop: 'Dizüstü bilgisayar',
  'cell phone': 'Cep telefonu', book: 'Kitap', scissors: 'Makas', 'sports ball': 'Top', skateboard: 'Kaykay', dog: 'Köpek', cat: 'Kedi',
  bird: 'Kuş', 'potted plant': 'Saksı', clock: 'Saat', vase: 'Vazo', sandwich: 'Sandviç', pizza: 'Pizza', cake: 'Pasta', banana: 'Muz',
  apple: 'Elma', orange: 'Portakal', 'hot dog': 'Sosisli', donut: 'Donut', microwave: 'Mikrodalga', oven: 'Fırın', toaster: 'Tost makinesi',
  refrigerator: 'Buzdolabı', sink: 'Lavabo', 'fire hydrant': 'Yangın musluğu', 'stop sign': 'Dur levhası', bench: 'Bank', kite: 'Uçurtma',
  'baseball bat': 'Sopa', 'tennis racket': 'Raket', tie: 'Kravat', 'teddy bear': 'Oyuncak ayı', 'hair drier': 'Saç kurutma makinesi',
  toothbrush: 'Diş fırçası', remote: 'Kumanda', keyboard: 'Klavye', mouse: 'Fare', 'traffic light': 'Trafik ışığı', train: 'Tren', boat: 'Tekne',
  airplane: 'Uçak', horse: 'At', sheep: 'Koyun', cow: 'İnek',
};
const objName = k => OBJ_TR[k] || k;
const num = v => (v == null ? '—' : Number(v).toLocaleString('tr-TR'));
const esc1 = v => (v == null || v === '' ? '—' : v);

function ensureCss() {
  if (document.getElementById('ws-css')) return;
  let href = '/static/css/worksafety.css';
  try { href = new URL('../../css/worksafety.css', import.meta.url).href; } catch { /* test ortamı: sabit yol */ }
  document.head.append(h('link', { id: 'ws-css', rel: 'stylesheet', href }));
}

// Kameranın son karesini <img>'e yükler (ETag ile; değişmediyse 304). ms verilirse yineler. → durdurma işlevi
function frameLoop(img, cid, { w = 0, ms = 0, onLoad } = {}) {
  let etag = null, url = null, stopped = false, timer;
  const tick = async () => {
    clearTimeout(timer);
    if (stopped || !img.isConnected) return;
    try {
      const r = await fetch(`/api/worksafety/cameras/${cid}/frame${w ? `?w=${w}` : ''}`, { headers: etag ? { 'If-None-Match': etag } : {}, credentials: 'same-origin' });
      if (r.status === 200) {
        etag = r.headers.get('ETag');
        const blob = await r.blob();
        const old = url;
        url = URL.createObjectURL(blob);
        img.src = url;
        img.dataset.ok = '1';
        if (old) setTimeout(() => URL.revokeObjectURL(old), 1500);
        onLoad?.(true);
      } else if (r.status !== 304) { onLoad?.(false); }
    } catch { onLoad?.(false); }
    if (ms && !stopped) timer = setTimeout(tick, ms);
  };
  setTimeout(tick, 0);
  const stop = () => { stopped = true; clearTimeout(timer); if (url) URL.revokeObjectURL(url); };
  onLeave(stop);
  return { stop, refresh: () => { etag = null; tick(); } };
}

export async function render(view, params, ctx) {
  ensureCss();
  const tab = TABS.some(x => x[0] === (params[0] || '').split('?')[0]) ? (params[0] || '').split('?')[0] : '';
  const u = ctx.user;
  const canWrite = !!u.master || !u.write_modules || u.write_modules.includes('worksafety');
  const strip = statStrip();
  const banner = h('div');
  const body = h('div', { class: 'ws-body' });
  const go = (t, extra = '') => { location.hash = `#/worksafety${t ? `/${t}` : ''}${extra}`; };
  clear(view, pageHead('İş Güvenliği', { back: '#/', sub: 'Kameralarla kural denetimi: donanım, bölge, araç, davranış ve ergonomi' }),
    moduleTabs(TABS, tab, go), strip, banner, body);
  clear(body, h('div', { class: 'loading' }, 'Yükleniyor…'));

  const S = { canWrite, go, tab, params: params.slice(1), ctx };
  try {
    [S.cat, S.cfg, S.cams] = await Promise.all([
      api.get('/api/worksafety/catalog'), api.get('/api/worksafety/config'),
      api.get('/api/worksafety/cameras').catch(err => { S.camErr = err.message; return []; })]);
  } catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message || 'İş Güvenliği verisi okunamadı')); }
  S.rule = Object.fromEntries(S.cat.rules.map(r => [r.key, r]));
  S.zoneType = Object.fromEntries(S.cat.zone_types.map(z => [z.key, z]));
  S.camName = id => S.cams.find(c => c.id === id)?.name || `Kamera #${id}`;
  // Yapılandırmayı kaydeder; fabrikaya aktarılamadıysa uyarır. → kaydedilen (normalize) belge
  S.save = async (cfg, okMsg = 'Kaydedildi') => {
    const r = await api.put('/api/worksafety/config', cfg);
    S.cfg = r.config;
    toast(r.warning || okMsg, r.warning ? 'err' : '');
    return r.config;
  };

  const st = S.cat.status || {};
  const drawStrip = () => {
    const run = st.running, on = S.cfg.enabled;
    strip.set([
      { key: 'state', label: 'Denetim', value: !on ? 'Kapalı' : run ? 'Çalışıyor' : 'Bekliyor', tone: !on ? '' : run ? 'ws-ok' : 'ws-warn',
        sub: !on ? 'Ayarlar sekmesinden açılır' : run ? `${num(st.cams_active)} kamera · tur ${st.cycle_s ?? '—'} sn` : (st.reachable === false ? 'fabrikaya ulaşılamıyor' : 'işleyici yanıt vermiyor'),
        onClick: () => go('settings') },
      { key: 'open', label: 'Açık uyarı', value: num(st.open_events), tone: st.open_events ? 'alert' : '', onClick: () => go('') },
      { key: 'today', label: 'Bugünkü uyarı', value: num(st.events_today), onClick: () => go('') },
      { key: 'rules', label: 'Etkin kural', value: `${S.cat.rules.filter(r => ruleActive(S, r)).length} / ${S.cat.rules.length}`, onClick: () => go('rules') },
      { key: 'faces', label: 'Yüz tanıma', value: !run ? '—' : st.faces_off ? 'Durduruldu' : (st.faces_mult > 1 ? `1/${st.faces_mult} hız` : 'Tam hız'),
        tone: run && st.faces_off ? 'ws-warn' : '', sub: { auto: 'işlem gücüne göre otomatik', on: 'her zaman açık', off: 'denetim sürerken kapalı' }[S.cfg.faces_mode],
        onClick: () => go('settings') },
    ]);
  };
  S.drawStrip = drawStrip;
  drawStrip();
  if (st.reachable === false) {
    banner.append(h('div', { class: `alert ${st.outdated ? 'warn' : 'err'}`, style: { marginBottom: '12px' } },
      st.outdated ? 'Fabrika bilgisayarındaki yazılım İş Güvenliği modülünü henüz içermiyor. Güncellendiğinde denetim kendiliğinden başlar; kurallar ve bölgeler şimdiden hazırlanabilir.'
        : `Fabrikaya ulaşılamıyor: ${st.problem || 'bağlantı yok'}. Kayıtlı ayarlar gösteriliyor; uyarılar ve canlı görüntü fabrika bağlanınca gelir.`));
  } else if (S.cfg.enabled && !st.running) {
    banner.append(h('div', { class: 'alert warn', style: { marginBottom: '12px' } }, 'Denetim açık ancak kamera servisindeki işleyici yanıt vermiyor (son 90 sn içinde durum bildirimi yok).'));
  }
  if (S.camErr && st.reachable !== false) banner.append(h('div', { class: 'alert warn', style: { marginBottom: '12px' } }, `Kamera listesi okunamadı: ${S.camErr}`));

  clear(body);
  const pages = { '': tabEvents, live: tabLive, rules: tabRules, groups: tabGroups, zones: tabZones, heat: tabHeat, report: tabReport, settings: tabSettings };
  try { await pages[tab](body, S); } catch (err) { clear(body, h('div', { class: 'card empty' }, err.message || 'Sayfa yüklenemedi')); }
}

const ruleOn = (S, r) => S.cfg.rules[r.key]?.enabled ?? r.on;
const ruleRisk = (S, r) => (S.cfg.rules[r.key]?.sev ?? r.sev) * (S.cfg.rules[r.key]?.lik ?? r.lik);
const camCfg = (S, cid) => S.cfg.cameras[String(cid)] || (S.cfg.all_cameras ? { enabled: true, ppe: false, ppe_group: null, rules: null, zones: [] } : null);
const scopeCams = S => S.cams.filter(c => { const cc = camCfg(S, c.id); return cc && cc.enabled; });

// KKD senaryo grupları: cfg.ppe_groups = [{ id, name, items: { <donanım>: { sev?, lik?, hold?, cooldown? } } }]
const groupOf = (S, id) => (id && (S.cfg.ppe_groups || []).find(g => g.id === id)) || null;
// Kameranın KKD kapsamı: '' denetim yok · '*' grupsuz (etkin tüm KKD kuralları) · grup kimliği
const ppeMode = (S, cc) => (groupOf(S, cc?.ppe_group) ? cc.ppe_group : cc?.ppe ? '*' : '');
const ppeFields = v => ({ ppe: v === '*', ppe_group: v && v !== '*' ? v : null });
function ppeSelect(S, value, onChange, { disabled = false, label = 'KKD senaryo grubu' } = {}) {
  const opts = [['', '— KKD denetimi yok —'], ['*', 'Etkin tüm KKD kuralları (grupsuz)'], ...(S.cfg.ppe_groups || []).map(g => [g.id, g.name])];
  const sel = h('select', { class: 'input', disabled, 'aria-label': label }, opts.map(([v, l]) => h('option', { value: v, selected: v === value }, l)));
  sel.addEventListener('change', () => onChange(sel.value));
  return sel;
}
// Bu donanımı, kapsamdaki bir kamerada ya da KKD alanında denetleyen grupların adları
function kkdGroups(S, r) {
  const ids = new Set();
  for (const c of scopeCams(S)) {
    const cc = camCfg(S, c.id);
    for (const id of [cc.ppe_group, ...(cc.zones || []).filter(z => z.type === 'ppe_zone').map(z => z.params?.group)]) if (groupOf(S, id)?.items?.[r.ppe]) ids.add(id);
  }
  return [...ids].map(id => groupOf(S, id).name);
}
// Kural bir yerde denetleniyor mu: genel anahtarı açık ya da (KKD) bir senaryo grubunda kullanılıyor
const ruleActive = (S, r) => ruleOn(S, r) || (r.cat === 'kkd' && kkdGroups(S, r).length > 0);

// Kuralın çalışmasına engel olan eksik: [metin, sekme] ya da null
function ruleBlock(S, r) {
  if (r.model_ok === false) return [`Model gerekli${r.model_missing ? `: ${r.model_missing}` : ''}`, null];
  const zones = scopeCams(S).flatMap(c => camCfg(S, c.id).zones || []);
  const types = S.cat.zone_types.filter(z => z.rules.includes(r.key)).map(z => z.key);
  if (r.cat === 'kkd') {
    if (kkdGroups(S, r).length) return null;
    const plain = z => !groupOf(S, z.params?.group) && (!(z.params?.items || []).length || z.params.items.includes(r.ppe));   // grupsuz alan: genel kural
    const anyCam = scopeCams(S).some(c => { const cc = camCfg(S, c.id); return cc.ppe && !groupOf(S, cc.ppe_group); });
    return anyCam || zones.some(z => z.type === 'ppe_zone' && plain(z)) ? null : ['KKD grubu atanmış kamera ya da alan yok', 'groups'];
  }
  if (r.zone_req && !zones.some(z => types.includes(z.type))) return [`Bölge çizilmedi: ${types.map(t => S.zoneType[t].name).join(' / ')}`, 'zones'];
  if (r.key === 'forbidden_object' && !((S.cfg.rules[r.key]?.params?.objects ?? r.params.objects) || []).length) return ['Yasak nesne listesi boş', null];
  return null;
}

// ============================================================ Uyarılar
async function tabEvents(body, S) {
  const list = h('div');
  const F = { ack: pref('ws.ev.ack', 'open'), cat: '', rule: '', level: '', camera: '' };
  let rows = [], total = 0;
  const period = periodFilter('ws.events', () => load(), { initial: '30d' });
  const catSel = selectInput(S.cat.cats.map(c => [c.key, c.name]), { all: 'Tüm kategoriler' });
  const ruleSel = selectInput(S.cat.rules.map(r => [r.key, `${r.no}. ${r.name}`]), { all: 'Tüm kurallar' });
  const lvlSel = selectInput(LEVELS.map(l => [l[1], l[1]]), { all: 'Tüm düzeyler' });
  const camSel = selectInput(S.cams.map(c => [c.id, c.name]), { all: 'Tüm kameralar' });
  const ackSeg = segmented([['open', 'Açık'], ['done', 'Kapatılan'], ['', 'Tümü']], F.ack, v => { F.ack = v; setPref('ws.ev.ack', v); load(); });
  for (const [sel, k] of [[catSel, 'cat'], [ruleSel, 'rule'], [lvlSel, 'level'], [camSel, 'camera']]) sel.addEventListener('change', () => { F[k] = sel.value; load(); });
  const picked = new Set();
  const closeBtn = h('button', { class: 'btn', hidden: !S.canWrite, disabled: true }, 'Seçilenleri kapat');
  const syncPick = () => { closeBtn.disabled = !picked.size; closeBtn.textContent = picked.size ? `Seçilenleri kapat (${picked.size})` : 'Seçilenleri kapat'; };

  const ackEvents = async (ids, undo = false, note = null) => {
    try {
      const r = await api.post('/api/worksafety/events/ack', { ids, undo, note });
      toast(undo ? 'Uyarı yeniden açıldı' : `${r.n} uyarı kapatıldı`);
      picked.clear(); syncPick();
      await load();
    } catch (err) { toastError(err); }
  };
  closeBtn.addEventListener('click', async () => {
    if (await confirmDialog('Uyarıları kapat', `${picked.size} uyarı "görüldü" olarak kapatılsın mı?`, { okLabel: 'Kapat' })) ackEvents([...picked]);
  });
  setListExport(() => ({   // ortak Excel düğmesi (listexport.js) süzülmüş uyarıların tümünü aktarır
    columns: ['Zaman', 'Kural', 'Kategori', 'Düzey', 'Risk', 'Kamera', 'Bölge', 'Ayrıntı', 'Durum', 'Kapatan', 'Kapatma zamanı', 'Not'],
    rows: rows.map(e => [e.at, e.rule_name, S.cat.cats.find(c => c.key === e.cat)?.name || e.cat, e.level, e.risk, e.camera_name, e.zone_name || '', e.detail || '',
      e.ack_at ? 'Kapatıldı' : 'Açık', e.ack_name || '', e.ack_at || '', e.ack_note || '']) }));

  const openEvent = e => {
    const note = h('textarea', { class: 'input', rows: 2, placeholder: 'Not (isteğe bağlı): alınan önlem, kişi, açıklama…' });
    const media = h('div', { class: 'ws-ev-media' },
      e.clip ? h('video', { class: 'fr-clip', src: videoUrl(e.clip), controls: true, loop: true, muted: true, playsinline: true, preload: 'metadata', poster: e.photo ? fileUrl(e.photo) : null })
        : e.photo ? h('img', { class: 'ws-ev-photo', src: fileUrl(e.photo), alt: e.rule_name })
          : h('div', { class: 'card empty' }, 'Görüntü hazırlanıyor ya da kaydedilemedi'));
    const kv = (k, v) => h('div', { class: 'ws-kv' }, h('span', null, k), h('b', null, v));
    const info = h('div', { class: 'ws-ev-info' },
      kv('Kural', `${S.rule[e.rule]?.no ?? ''}. ${e.rule_name}`), kv('Düzey', levelBadge(e.level)), kv('Risk', `${e.severity} × ${e.likelihood} = ${e.risk}`),
      kv('Kamera', e.camera_name || `#${e.camera_id}`), kv('Bölge', esc1(e.zone_name)), kv('Zaman', fmtDateTime(e.at)), kv('Ayrıntı', esc1(e.detail)),
      e.meta?.group ? kv('KKD grubu', e.meta.group) : null,
      e.meta?.duration ? kv('Süre', `${Math.round(e.meta.duration)} sn`) : null,
      e.ack_at ? kv('Kapatan', `${e.ack_name || '—'} · ${fmtDateTime(e.ack_at)}`) : null, e.ack_note ? kv('Not', e.ack_note) : null,
      S.rule[e.rule] ? h('p', { class: 'small muted', style: { margin: '8px 0 0' } }, S.rule[e.rule].desc) : null,
      e.photo && e.clip ? h('a', { class: 'small', href: fileUrl(e.photo), target: '_blank', rel: 'noopener' }, 'Kareyi aç') : null);
    modal({ title: `Uyarı #${e.id} — ${e.rule_name}`, wide: true,
      body: h('div', { class: 'ws-ev' }, media, h('div', null, info, !e.ack_at && S.canWrite ? field('Kapatma notu', note) : null)),
      actions: [
        { label: 'Kapat' },
        !S.canWrite ? null : e.ack_at ? { label: 'Yeniden aç', onClick: () => ackEvents([e.id], true) }
          : { label: 'Uyarıyı kapat', class: 'primary', onClick: () => ackEvents([e.id], false, note.value) },
      ].filter(Boolean) });
  };

  const draw = () => {
    if (!rows.length) return clear(list, h('div', { class: 'card empty' }, S.cfg.enabled ? 'Bu ölçütlere uyan uyarı yok.' : 'Denetim kapalı. Ayarlar sekmesinden açıldığında kural ihlalleri burada listelenir.'));
    const all = h('input', { type: 'checkbox', title: 'Tümünü seç' });
    all.addEventListener('change', () => { rows.filter(e => !e.ack_at).forEach(e => (all.checked ? picked.add(e.id) : picked.delete(e.id))); syncPick(); draw(); });
    clear(list,
      total > rows.length ? h('div', { class: 'small muted', style: { margin: '0 0 8px' } }, `${num(total)} uyarıdan son ${num(rows.length)} tanesi gösteriliyor; aralığı daraltın.`) : null,
      h('div', { class: 'table-wrap card' }, h('table', { class: 'table ws-ev-table' },
        h('thead', null, h('tr', null, S.canWrite ? h('th', { 'data-dt': 'off', class: 'ws-ck' }, all) : null,
          h('th', { 'data-dt': 'off' }, ''), ['Zaman', 'Kural', 'Düzey', 'Kamera', 'Bölge', 'Ayrıntı', 'Durum'].map(c => h('th', null, c)))),
        h('tbody', null, rows.map(e => {
          const ck = h('input', { type: 'checkbox', checked: picked.has(e.id), disabled: !!e.ack_at });
          ck.addEventListener('click', ev => ev.stopPropagation());
          ck.addEventListener('change', () => { ck.checked ? picked.add(e.id) : picked.delete(e.id); syncPick(); });
          return h('tr', { class: `ws-ev-row${e.ack_at ? ' done' : ''}`, onclick: () => openEvent(e) },
            S.canWrite ? h('td', { class: 'ws-ck', onclick: ev => ev.stopPropagation() }, ck) : null,
            h('td', { class: 'ws-thumb' }, e.photo ? h('img', { src: fileUrl(e.photo, 240), loading: 'lazy', alt: '' }) : h('span', { class: 'muted small' }, '—'),
              e.clip ? h('span', { class: 'ws-play', title: 'Klip var' }, '▶') : null),
            h('td', { class: 'nowrap small', 'data-sort': e.at }, fmtDateTime(e.at)),
            h('td', null, h('b', null, e.rule_name)),
            h('td', { 'data-sort': String(e.risk).padStart(3, '0') }, levelBadge(e.level)),
            h('td', { class: 'small' }, e.camera_name || `#${e.camera_id}`),
            h('td', { class: 'small' }, esc1(e.zone_name)),
            h('td', { class: 'small wrap' }, esc1(e.detail)),
            h('td', { class: 'small nowrap' }, e.ack_at ? h('span', { class: 'badge gray', title: `${e.ack_name || ''} · ${fmtDateTime(e.ack_at)}` }, 'Kapatıldı') : h('span', { class: 'badge red' }, 'Açık')));
        })))));
  };

  async function load() {
    const r = period.range();
    const q = new URLSearchParams({ limit: '500' });
    if (r.date_from) q.set('since', r.date_from);
    if (r.date_to) q.set('until', r.date_to);
    for (const k of ['ack', 'cat', 'rule', 'level', 'camera']) if (F[k]) q.set(k, F[k]);
    if (!list.firstChild) clear(list, h('div', { class: 'loading' }, 'Yükleniyor…'));
    try { ({ rows, total } = await api.get(`/api/worksafety/events?${q}`)); }
    catch (err) { return clear(list, h('div', { class: 'card empty' }, err.message || 'Uyarılar okunamadı')); }
    for (const id of [...picked]) if (!rows.some(e => e.id === id && !e.ack_at)) picked.delete(id);
    syncPick();
    draw();
  }
  body.append(moduleToolbar(period.el, catSel, ruleSel, lvlSel, camSel, ackSeg, closeBtn), list);
  await load();
  const want = Number(S.params[0]);   // doğrudan bağlantı: #/worksafety/e/<uyarı no>
  if (want) { try { openEvent(await api.get(`/api/worksafety/events/${want}`)); } catch { /* silinmiş olabilir */ } }
  const timer = setInterval(() => { if (!document.querySelector('.modal-back') && !picked.size) load(); }, 30000);
  onLeave(() => clearInterval(timer));
}

// ============================================================ Canlı İzleme
// Normalize kutu / poligonları, object-fit: contain ile gösterilen görüntünün ekrandaki konumuna ölçekler
function fitRect(img, W, H) {
  const nw = img.naturalWidth || 16, nh = img.naturalHeight || 9;
  const s = Math.min(W / nw, H / nh), dw = nw * s, dh = nh * s;
  return { x: (W - dw) / 2, y: (H - dh) / 2, w: dw, h: dh };
}
function drawZones(cx, r, zones, S, { alpha = 0.16, labels = false } = {}) {
  for (const z of zones || []) {
    const col = S.zoneType[z.type]?.color || '#eab308';
    cx.beginPath();
    z.points.forEach(([px, py], i) => (i ? cx.lineTo(r.x + px * r.w, r.y + py * r.h) : cx.moveTo(r.x + px * r.w, r.y + py * r.h)));
    cx.closePath();
    cx.globalAlpha = alpha; cx.fillStyle = col; cx.fill();
    cx.globalAlpha = 1; cx.strokeStyle = col; cx.stroke();
    if (labels) { cx.fillStyle = col; cx.fillText(z.name, r.x + z.points[0][0] * r.w + 3, r.y + z.points[0][1] * r.h + 12); }
  }
}

async function tabLive(body, S) {
  const cams = scopeCams(S).filter(c => c.active !== 0);
  if (!cams.length) return clear(body, h('div', { class: 'card empty' }, 'Denetim kapsamında kamera yok. Ayarlar sekmesinden kamera seçin.'));
  let layout = Number(pref('ws.live.layout', '9')), page = 0, zonesOn = pref('ws.live.zones', '1') === '1';
  const grid = h('div');
  const pager = h('span', { class: 'small muted' });
  const prev = h('button', { class: 'btn sm' }, '‹ Önceki'), next = h('button', { class: 'btn sm' }, 'Sonraki ›');
  const zoneSeg = segmented([['1', 'Bölgeler açık'], ['0', 'Bölgeler kapalı']], zonesOn ? '1' : '0', v => { zonesOn = v === '1'; setPref('ws.live.zones', v); tiles.forEach(t => t.draw()); });
  const laySeg = segmented([['1', '1'], ['4', '4'], ['9', '9'], ['16', '16'], ['32', '32']], String(layout), v => { layout = Number(v); setPref('ws.live.layout', v); page = 0; build(); });
  let tiles = [], live = {}, alive = true, liveTimer;
  onLeave(() => { alive = false; clearTimeout(liveTimer); tiles.forEach(t => t.stop()); });

  const tile = c => {
    const img = h('img', { alt: c.name });
    const canvas = h('canvas', { class: 'cw-canvas' });
    const tags = h('div', { class: 'ws-tags' });
    const el = h('div', { class: 'cw-tile ws-tile' }, img, canvas, h('div', { class: 'ws-tile-name' }, c.name), tags);
    const zones = camCfg(S, c.id)?.zones || [];
    const draw = () => {
      const W = el.clientWidth, H = el.clientHeight;
      canvas.width = W; canvas.height = H;
      const cx = canvas.getContext('2d');
      cx.clearRect(0, 0, W, H);
      if (!img.naturalWidth) return;
      const r = fitRect(img, W, H), d = live[c.id];
      cx.lineWidth = Math.max(1, Math.round(W / 360)); cx.font = `${Math.max(9, Math.round(W / 46))}px sans-serif`;
      if (zonesOn) drawZones(cx, r, zones, S, { labels: W > 420 });
      const box = (b, col) => { cx.strokeStyle = col; cx.strokeRect(r.x + b[0] * r.w, r.y + b[1] * r.h, b[2] * r.w, b[3] * r.h); };
      for (const v of d?.vehicles || []) box(v, '#3b82f6');
      for (const p of d?.persons || []) box(p.box, p.bad ? '#ef4444' : '#22c55e');
      cx.lineWidth *= 2;
      for (const v of d?.viol || []) for (const b of v.boxes || []) box(b, '#ef4444');
      const viol = d?.viol || [];
      el.classList.toggle('alarm', viol.length > 0);
      clear(tags, viol.slice(0, 4).map(v => h('span', { class: `ws-lv ${levelCls(v.level)}` }, v.name)), viol.length > 4 ? h('span', { class: 'ws-lv dusuk' }, `+${viol.length - 4}`) : null);
    };
    img.addEventListener('load', draw);
    el.addEventListener('dblclick', () => { el.classList.toggle('max'); draw(); fl.refresh(); });
    const fl = frameLoop(img, c.id, { w: layout <= 1 ? 0 : layout <= 4 ? 640 : layout <= 9 ? 480 : 320, ms: layout <= 4 ? 700 : layout <= 9 ? 1200 : layout <= 16 ? 2000 : 3500 });
    return { el, id: c.id, draw, stop: fl.stop };
  };

  const build = () => {
    tiles.forEach(t => t.stop());
    const pages = Math.max(1, Math.ceil(cams.length / layout));
    page = Math.min(page, pages - 1);
    const shown = cams.slice(page * layout, page * layout + layout);
    tiles = shown.map(tile);
    clear(grid, h('div', { class: `cw-grid l${layout === 32 ? 32 : layout} ws-grid` }, tiles.map(t => t.el)));
    pager.textContent = pages > 1 ? `Sayfa ${page + 1} / ${pages}` : `${cams.length} kamera`;
    prev.hidden = next.hidden = pages <= 1;
    prev.disabled = page === 0; next.disabled = page >= pages - 1;
    poll();
  };
  prev.addEventListener('click', () => { page--; build(); });
  next.addEventListener('click', () => { page++; build(); });
  async function poll() {
    clearTimeout(liveTimer);
    if (!alive) return;
    try { live = await api.get(`/api/worksafety/live?ids=${tiles.map(t => t.id).join(',')}`); tiles.forEach(t => t.draw()); } catch { /* geçici */ }
    liveTimer = setTimeout(poll, 2000);
  }
  const onResize = () => tiles.forEach(t => t.draw());
  window.addEventListener('resize', onResize);
  onLeave(() => window.removeEventListener('resize', onResize));
  body.append(moduleToolbar(pager, prev, next, zoneSeg, laySeg),
    h('div', { class: 'small muted', style: { margin: '0 0 8px' } }, 'Yeşil: kişi · Kırmızı: ihlal · Mavi: araç. Kareyi büyütmek için çift tıklayın.'), grid);
  build();
}

// ============================================================ Kurallar
async function tabRules(body, S) {
  const wrap = h('div');
  let saving = Promise.resolve();
  const patch = (key, fn) => {   // kural ayarını değiştirip kaydeder (art arda değişiklikler sıraya girer)
    const cfg = structuredClone(S.cfg);
    cfg.rules[key] = cfg.rules[key] || {};
    fn(cfg.rules[key]);
    S.cfg = cfg;
    saving = saving.then(() => S.save(cfg, 'Kural kaydedildi')).catch(toastError).then(() => { S.drawStrip(); draw(); });
  };

  const editRule = r => {
    const cur = S.cfg.rules[r.key] || {};
    const sev = h('input', { class: 'input', type: 'number', min: 1, max: 5, value: cur.sev ?? r.sev });
    const lik = h('input', { class: 'input', type: 'number', min: 1, max: 5, value: cur.lik ?? r.lik });
    const out = h('div', { class: 'small', style: { margin: '6px 0 12px' } });
    const calc = () => { const k = (Number(sev.value) || 1) * (Number(lik.value) || 1); clear(out, 'Risk puanı: ', h('b', null, String(k)), ' → ', levelBadge(levelOf(k)[1])); };
    sev.addEventListener('input', calc); lik.addEventListener('input', calc); calc();
    const inputs = {};
    const fields = Object.entries(r.params || {}).map(([k, d]) => {
      const v = cur.params?.[k] ?? d;
      if (typeof d === 'boolean') { const cb = h('input', { type: 'checkbox', checked: !!v }); inputs[k] = () => cb.checked; return h('label', { class: 'ws-check' }, cb, PARAM_LABEL[k] || k); }
      if (Array.isArray(d)) {
        const set = new Set(v || []);
        const box = h('div', { class: 'ws-pick' }, S.cat.objects.map(o => {
          const cb = h('input', { type: 'checkbox', checked: set.has(o) });
          cb.addEventListener('change', () => (cb.checked ? set.add(o) : set.delete(o)));
          return h('label', { class: 'ws-check' }, cb, objName(o));
        }));
        inputs[k] = () => [...set];
        return field(PARAM_LABEL[k] || k, box, 'İşaretlenen nesneler kamerada görülürse uyarı üretilir.');
      }
      const inp = h('input', { class: 'input', type: typeof d === 'string' ? 'time' : 'number', step: Number.isInteger(d) ? 1 : 'any', min: typeof d === 'string' ? null : 0, value: v });
      inputs[k] = () => (typeof d === 'string' ? inp.value : Number(inp.value));
      return field(PARAM_LABEL[k] || k, inp);
    });
    modal({ title: `${r.no}. ${r.name}`,
      body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, r.desc),
        h('div', { class: 'ws-two' }, field('Şiddet (1–5)', sev), field('Olasılık (1–5)', lik)), out, fields,
        r.hold ? h('p', { class: 'small muted' }, `Bu kural, durum en az ${r.hold} sn sürdüğünde uyarı üretir.`) : null,
        r.cat === 'kkd' ? h('p', { class: 'small muted' }, 'Bu ayar grupsuz denetimde ve grupta ayrı değer verilmeyen yerlerde geçerlidir. Donanım başına şiddet, olasılık, süre ve yeniden uyarı süresi "KKD Grupları" sekmesinde gruba göre tanımlanır.') : null),
      actions: [{ label: 'Vazgeç' },
        { label: 'Varsayılana dön', onClick: () => patch(r.key, e => { delete e.sev; delete e.lik; delete e.params; }) },
        { label: 'Kaydet', class: 'primary', onClick: () => {
          patch(r.key, e => { e.sev = Number(sev.value) || r.sev; e.lik = Number(lik.value) || r.lik; if (Object.keys(inputs).length) e.params = Object.fromEntries(Object.entries(inputs).map(([k, f]) => [k, f()])); });
        } }] });
  };

  function draw() {
    clear(wrap, S.cat.cats.map(c => {
      const rules = S.cat.rules.filter(r => r.cat === c.key);
      return h('div', { class: 'ws-rule-group' },
        h('h3', { class: 'ws-h3' }, c.name, h('span', { class: 'muted small' }, ` · ${rules.filter(r => ruleActive(S, r)).length} / ${rules.length} etkin`)),
        h('div', { class: 'table-wrap card' }, h('table', { class: 'table ws-rule-table', 'data-dt': 'off' },
          h('thead', null, h('tr', null, ['No', 'Kural', 'Risk', 'Durum', 'Etkin', ''].map(x => h('th', null, x)))),
          h('tbody', null, rules.map(r => {
            const on = ruleOn(S, r), risk = ruleRisk(S, r), block = ruleBlock(S, r);
            const grp = r.cat === 'kkd' ? kkdGroups(S, r) : [], active = on || grp.length > 0;
            const sw = h('input', { type: 'checkbox', checked: on, disabled: !S.canWrite, 'aria-label': `${r.name} etkin` });
            sw.addEventListener('change', () => patch(r.key, e => { e.enabled = sw.checked; }));
            const state = !active ? h('span', { class: 'badge gray' }, 'Kapalı')
              : block ? h(block[1] ? 'a' : 'span', { class: 'badge yellow', href: block[1] ? `#/worksafety/${block[1]}` : null, title: block[0] }, block[0])
                : h('span', { class: 'badge green' }, S.cat.status?.running ? 'Çalışıyor' : 'Hazır');
            return h('tr', { class: active ? '' : 'ws-off' },
              h('td', { class: 'muted' }, String(r.no)),
              h('td', null, h('b', null, r.name), h('div', { class: 'small muted' }, r.desc)),
              h('td', { class: 'nowrap' }, levelBadge(levelOf(risk)[1]), h('span', { class: 'small muted' }, ` ${risk}`)),
              h('td', null, h('div', { class: 'ws-rule-st' }, state, grp.length ? h('a', { class: 'badge blue', href: '#/worksafety/groups', title: `${grp.join(', ')} — ${on ? 'bu donanımı denetleyen KKD senaryo grupları' : 'genel kural kapalı; bu donanım yalnız grubun atandığı kamera ve alanlarda denetlenir'}` }, grp.length > 1 ? `${grp.length} grup` : `Grup: ${grp[0]}`) : null)),
              h('td', null, h('label', { class: 'ws-switch' }, sw, h('span', null))),
              h('td', { class: 'nowrap' }, S.canWrite ? h('button', { class: 'btn xs', onclick: () => editRule(r) }, 'Ayar') : null));
          })))));
    }));
  }
  body.append(h('div', { class: 'alert info', style: { marginBottom: '12px' } },
    'Risk = şiddet × olasılık. 20 ve üzeri KRİTİK, 15+ CİDDİ RİSK, 10+ YÜKSEK, 5+ ORTA. Donanım (KKD) kuralları, "KKD Grupları" sekmesinde senaryo grubu atanan kameralarda ve çizilen donanım alanlarında çalışır; gruba eklenen donanım, buradaki anahtarı kapalı olsa da o kamerada denetlenir. Bölge kuralları ilgili bölge çizilince devreye girer.'), wrap);
  draw();
}

// ============================================================ KKD Grupları
async function tabGroups(body, S) {
  const dis = !S.canWrite, wrap = h('div');
  const groups = () => S.cfg.ppe_groups || [];
  let saving = Promise.resolve();
  const commit = (fn, msg) => {   // yapılandırmayı değiştirip kaydeder (art arda değişiklikler sıraya girer)
    const cfg = structuredClone(S.cfg);
    fn(cfg);
    S.cfg = cfg;
    saving = saving.then(() => S.save(cfg, msg))
      .catch(async err => { toastError(err); try { S.cfg = await api.get('/api/worksafety/config'); } catch { /* yerel durum kalır */ } })
      .then(() => { S.drawStrip(); draw(); });
  };
  const noModel = o => S.rule[o.rule]?.model_ok === false;
  const base = o => { const r = S.rule[o.rule], c = S.cfg.rules[o.rule] || {}; return { sev: c.sev ?? r.sev, lik: c.lik ?? r.lik, hold: r.hold || 0, cooldown: S.cfg.cooldown }; };
  const eff = (o, it) => { const e = { ...base(o), ...Object.fromEntries(Object.entries(it || {}).filter(([, v]) => v != null)) }; return { ...e, risk: e.sev * e.lik }; };
  const usage = id => {
    let cams = 0, zones = 0;
    for (const cc of Object.values(S.cfg.cameras)) { if (cc.ppe_group === id) cams++; zones += (cc.zones || []).filter(z => z.type === 'ppe_zone' && z.params?.group === id).length; }
    return { cams, zones };
  };
  const setCam = (cfg, cid, patch) => { cfg.cameras[String(cid)] = { ...(cfg.cameras[String(cid)] || { enabled: !!cfg.all_cameras, ppe: false, ppe_group: null, rules: null, zones: [] }), ...patch }; };

  const editGroup = (g, from = null) => {
    const src = g || from;
    const name = h('input', { class: 'input', maxlength: 60, value: g ? g.name : from ? `${from.name} (kopya)` : '', placeholder: 'Örn. Seviye 1' });
    const rows = S.cat.kkd.map(o => {
      const cur = src?.items?.[o.key], b = base(o);
      const on = h('input', { type: 'checkbox', checked: !!cur, 'aria-label': `${o.name} gruba dahil` });
      const n = (f, lbl, attrs) => h('input', { class: 'input ws-grp-num', type: 'number', value: cur?.[f] ?? '', placeholder: String(b[f]), 'aria-label': `${o.name} — ${lbl}`, ...attrs });
      const inp = { sev: n('sev', 'şiddet', { min: 1, max: 5 }), lik: n('lik', 'olasılık', { min: 1, max: 5 }), hold: n('hold', 'süre (sn)', { min: 0, max: 3600 }),
        cooldown: n('cooldown', 'yeniden uyarı (sn)', { min: 30, max: 86400, step: 10 }) };
      const lim = { sev: [1, 5], lik: [1, 5], hold: [0, 3600], cooldown: [30, 86400] };
      const val = f => (inp[f].value.trim() === '' || !Number.isFinite(Number(inp[f].value)) ? null : Math.min(lim[f][1], Math.max(lim[f][0], Math.round(Number(inp[f].value)))));
      const risk = h('td', { class: 'nowrap' });
      const tr = h('tr', null,
        h('td', null, h('label', { class: 'ws-check' }, on, h('span', null, h('b', null, o.name),
          noModel(o) ? h('div', { class: 'small muted', title: 'Bu donanımı tanıyan model yüklenene dek denetlenmez' }, 'Model yok') : null))),
        h('td', null, inp.sev), h('td', null, inp.lik), risk, h('td', null, inp.hold), h('td', null, inp.cooldown));
      const sync = () => {
        for (const i of Object.values(inp)) i.disabled = !on.checked;
        tr.classList.toggle('ws-off', !on.checked);
        const k = (val('sev') ?? b.sev) * (val('lik') ?? b.lik);
        clear(risk, on.checked ? [levelBadge(levelOf(k)[1]), h('span', { class: 'small muted' }, ` ${k}`)] : h('span', { class: 'muted' }, '—'));
      };
      on.addEventListener('change', sync); inp.sev.addEventListener('input', sync); inp.lik.addEventListener('input', sync); sync();
      return { o, on, tr, sync, read: () => Object.fromEntries(Object.keys(inp).map(f => [f, val(f)]).filter(([, v]) => v != null)) };
    });
    const pick = (label, fn) => h('button', { class: 'btn xs', type: 'button', onclick: () => rows.forEach(r => { r.on.checked = fn(r.o); r.sync(); }) }, label);
    modal({ title: g ? `Grup: ${g.name}` : 'Yeni KKD senaryo grubu', wide: true,
      body: h('div', null, field('Grup adı', name),
        h('div', { class: 'ws-row', style: { margin: '4px 0 8px' } }, h('b', null, 'Alarm verecek donanımlar'),
          h('span', { class: 'ws-h3-act' }, pick('Tümünü seç', () => true), pick('Modeli olanlar', o => !noModel(o)), pick('Temizle', () => false))),
        h('div', { class: 'table-wrap' }, h('table', { class: 'table ws-grp-table', 'data-dt': 'off' },
          h('thead', null, h('tr', null, [['Donanım'], ['Şiddet', '1–5'], ['Olasılık', '1–5'], ['Risk'], ['Süre', 'sn — kesintisiz ihlal'], ['Yeniden uyarı', 'sn']].map(([x, t]) => h('th', { title: t || null }, x, t ? h('span', { class: 'small muted' }, ` ${t.split(' ')[0]}`) : null)))),
          h('tbody', null, rows.map(r => r.tr)))),
        h('p', { class: 'small muted' }, 'İşaretlenen donanım takılı değilse grubun atandığı kamerada uyarı üretilir. Boş bırakılan ayar genel kuraldan gelir (gri değer). ',
          'Süre: eksiklik en az bu kadar saniye sürerse uyarı açılır (0 = hemen). Yeniden uyarı: aynı kamerada aynı donanım için yeni uyarı açılmadan önce beklenen süre.')),
      actions: [{ label: 'Vazgeç' }, { label: g ? 'Kaydet' : 'Grubu ekle', class: 'primary', onClick: () => {
        const nm = name.value.trim(), items = Object.fromEntries(rows.filter(r => r.on.checked).map(r => [r.o.key, r.read()]));
        if (!nm) { toast('Grup adı yazın', 'err'); name.focus(); return true; }
        if (groups().some(x => x.id !== g?.id && x.name.toLocaleLowerCase('tr') === nm.toLocaleLowerCase('tr'))) { toast('Bu adda bir grup var', 'err'); name.focus(); return true; }
        if (!Object.keys(items).length) { toast('En az bir donanım işaretleyin', 'err'); return true; }
        if (!g && groups().length >= 40) { toast('En çok 40 grup tanımlanabilir', 'err'); return true; }
        commit(cfg => {
          cfg.ppe_groups = cfg.ppe_groups || [];
          const i = g ? cfg.ppe_groups.findIndex(x => x.id === g.id) : -1;
          if (i >= 0) cfg.ppe_groups[i] = { id: g.id, name: nm, items };
          else cfg.ppe_groups.push({ id: `g${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, name: nm, items });
        }, g ? 'Grup kaydedildi' : 'Grup eklendi');
      } }] });
  };
  const removeGroup = async g => {
    const u = usage(g.id);
    const used = [u.cams ? `${u.cams} kamerada` : '', u.zones ? `${u.zones} alanda` : ''].filter(Boolean).join(' ve ');
    if (!await confirmDialog('Grubu sil', `"${g.name}" silinsin mi?${used ? ` Grup ${used} kullanılıyor; buralarda KKD denetimi başka bir grup seçilene dek kapanır.` : ''}`, { okLabel: 'Sil', danger: true })) return;
    commit(cfg => {
      cfg.ppe_groups = (cfg.ppe_groups || []).filter(x => x.id !== g.id);
      for (const cc of Object.values(cfg.cameras)) {
        if (cc.ppe_group === g.id) cc.ppe_group = null;
        for (const z of cc.zones || []) if (z.params?.group === g.id) delete z.params.group;
      }
    }, 'Grup silindi');
  };

  const card = g => {
    const u = usage(g.id), items = S.cat.kkd.filter(o => g.items[o.key]);
    return h('div', { class: 'card card-pad ws-grp' },
      h('div', { class: 'ws-grp-head' }, h('b', null, g.name),
        h('span', { class: 'small muted' }, `${items.length} donanım · ${u.cams} kamera${u.zones ? ` · ${u.zones} alan` : ''}`)),
      h('div', { class: 'ws-grp-items' }, items.map(o => {
        const e = eff(o, g.items[o.key]), nm = noModel(o);
        return h('span', { class: `ws-grp-item${nm ? ' nomodel' : ''}`, title: nm ? 'Bu donanımı tanıyan model yüklü değil; yüklenene dek denetlenmez' : `Risk ${e.sev} × ${e.lik} = ${e.risk} · yeniden uyarı ${e.cooldown} sn` },
          h('b', null, o.name), nm ? h('span', { class: 'badge yellow' }, 'Model yok') : levelBadge(levelOf(e.risk)[1]),
          e.hold ? h('span', { class: 'small muted' }, `${e.hold} sn sonra`) : null);
      })),
      dis ? null : h('div', { class: 'ws-row' }, h('button', { class: 'btn sm', onclick: () => editGroup(g) }, 'Düzenle'),
        h('button', { class: 'btn sm', onclick: () => editGroup(null, g) }, 'Kopyala'), h('button', { class: 'btn sm danger', onclick: () => removeGroup(g) }, 'Sil')));
  };
  // Kameranın tamamında denetlenen donanımlar (alanlar ayrıca sayılır)
  const camItems = cc => {
    const g = groupOf(S, cc?.ppe_group);
    const list = g ? S.cat.kkd.filter(o => g.items[o.key]) : cc?.ppe ? S.cat.kkd.filter(o => ruleOn(S, S.rule[o.rule])) : [];
    const zn = (cc?.zones || []).filter(z => z.type === 'ppe_zone').length;
    if (!list.length && !zn) return h('span', { class: 'muted' }, '—');
    return h('span', { class: 'small' }, list.map((o, i) => [i ? ', ' : '', noModel(o) ? h('s', { class: 'muted', title: 'Model yok — denetlenmez' }, o.name) : o.name]),
      zn ? h('span', { class: 'muted' }, `${list.length ? ' · ' : ''}${zn} KKD alanı`) : null);
  };

  function draw() {
    const gs = groups();
    const bulk = ppeSelect(S, '', () => {}, { disabled: dis, label: 'Tüm kameralara atanacak grup' });
    const bulkBtn = h('button', { class: 'btn sm', hidden: dis, onclick: async () => {
      const v = bulk.value, label = bulk.selectedOptions[0].textContent;
      if (!await confirmDialog('Tüm kameralara uygula', `${S.cams.length} kameranın KKD senaryo grubu "${label}" olarak ayarlansın mı?`, { okLabel: 'Uygula' })) return;
      commit(cfg => S.cams.forEach(c => setCam(cfg, c.id, ppeFields(v))), 'Kameralar güncellendi');
    } }, 'Tümüne uygula');
    clear(wrap,
      h('h3', { class: 'ws-h3' }, 'Senaryo grupları', h('span', { class: 'muted small' }, ` · ${gs.length}`),
        dis ? null : h('span', { class: 'ws-h3-act' }, h('button', { class: 'btn sm primary', onclick: () => editGroup(null) }, 'Yeni grup'))),
      gs.length ? h('div', { class: 'ws-grp-grid' }, gs.map(card))
        : h('div', { class: 'card empty' }, 'Henüz grup yok. "Yeni grup" ile bir grup ekleyin (örn. Seviye 1), alarm verecek donanımları işaretleyin, sonra aşağıdan kameralara atayın.'),
      h('h3', { class: 'ws-h3' }, 'Kameralar', h('span', { class: 'muted small' }, ` · ${S.cams.filter(c => ppeMode(S, S.cfg.cameras[String(c.id)])).length} / ${S.cams.length} kamerada KKD denetimi`),
        dis || !S.cams.length ? null : h('span', { class: 'ws-h3-act ws-grp-bulk' }, bulk, bulkBtn)),
      S.cams.length ? h('div', { class: 'table-wrap card' }, h('table', { class: 'table ws-grp-cams', 'data-dt': 'off' },
        h('thead', null, h('tr', null, ['Kamera', 'Konum', 'Denetim', 'KKD senaryo grubu', 'Denetlenen donanımlar', ''].map(x => h('th', null, x)))),
        h('tbody', null, S.cams.map(c => {
          const cc = S.cfg.cameras[String(c.id)], on = cc ? !!cc.enabled : !!S.cfg.all_cameras, m = ppeMode(S, cc);
          const en = h('input', { type: 'checkbox', checked: on, disabled: dis, 'aria-label': `${c.name} denetlensin` });
          en.addEventListener('change', () => commit(cfg => setCam(cfg, c.id, { enabled: en.checked }), 'Kamera kaydedildi'));
          return h('tr', { class: on ? '' : 'ws-off' }, h('td', null, h('b', null, c.name)), h('td', { class: 'small' }, esc1(c.location)),
            h('td', null, en),
            h('td', null, ppeSelect(S, m, v => commit(cfg => setCam(cfg, c.id, ppeFields(v)), 'Kamera kaydedildi'), { disabled: dis, label: `${c.name} — KKD senaryo grubu` })),
            h('td', null, camItems(cc), m && !on ? h('div', { class: 'small muted' }, 'Kamera denetim dışı; grup, "Denetim" işaretlenince uygulanır.') : null),
            h('td', null, h('a', { class: 'btn xs', href: `#/worksafety/zones/${c.id}` }, 'Bölgeler')));
        })))) : h('div', { class: 'card empty' }, S.camErr || 'Kamera bulunamadı.'));
  }
  body.append(h('div', { class: 'alert info', style: { marginBottom: '12px' } },
    'Senaryo grubu, bir kamerada hangi koruyucu donanımların eksikliğinde uyarı verileceğini belirler. Grup oluşturun, donanımları ve donanım başına şiddet / olasılık / süre ayarını seçin, sonra her kamera için grubu seçin. ',
    'Kameranın yalnız bir bölümü için "Bölgeler" sekmesinde "KKD zorunlu alan" çizilip alana ayrı grup verilebilir.'), wrap);
  draw();
}

// ============================================================ Bölgeler
async function tabZones(body, S) {
  const cams = S.cams;
  if (!cams.length) return clear(body, h('div', { class: 'card empty' }, 'Kamera bulunamadı.'));
  let cid = Number(S.params[0]) || Number(pref('ws.zone.cam', '')) || cams[0].id;
  if (!cams.some(c => c.id === cid)) cid = cams[0].id;
  const camSel = selectInput(cams.map(c => [c.id, `${c.name}${(camCfg(S, c.id)?.zones || []).length ? ` (${camCfg(S, c.id).zones.length} bölge)` : ''}`]), { all: null, value: cid });
  const stage = h('div');
  camSel.addEventListener('change', () => { setPref('ws.zone.cam', camSel.value); S.go('zones', `/${camSel.value}`); });
  body.append(moduleToolbar(camSel), stage);

  const base = camCfg(S, cid) || { enabled: false, ppe: false, ppe_group: null, rules: null, zones: [] };
  const W = { enabled: !!S.cfg.cameras[String(cid)]?.enabled || (!S.cfg.cameras[String(cid)] && S.cfg.all_cameras), mode: ppeMode(S, base),
    rules: base.rules ? [...base.rules] : null, zones: structuredClone(base.zones || []) };
  let sel = -1, drawing = null, dirty = false, drag = null;
  const img = h('img', { class: 'ws-ze-img', alt: 'Kamera görüntüsü', draggable: false });
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'ws-ze-svg'); svg.setAttribute('viewBox', '0 0 1000 1000'); svg.setAttribute('preserveAspectRatio', 'none');
  const noImg = h('div', { class: 'ws-ze-empty' }, 'Kamera görüntüsü bekleniyor…');
  const labels = h('div', { class: 'ws-ze-labels' });   // bölge adları: SVG gerildiği için HTML katmanında
  const board = h('div', { class: 'ws-ze-board' }, img, svg, labels, noImg);
  const side = h('div', { class: 'ws-ze-side' });
  const saveBtn = h('button', { class: 'btn primary', disabled: true, hidden: !S.canWrite }, 'Kaydet');
  const fl = frameLoop(img, cid, { onLoad: ok => { noImg.hidden = ok || !!img.dataset.ok; if (!ok && !img.dataset.ok) noImg.textContent = 'Kamera görüntüsü alınamadı. Bölgeler boş zemin üzerinde çizilebilir.'; } });
  img.addEventListener('load', () => { if (img.naturalWidth) board.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`; });   // bölge koordinatları kareye oranlıdır
  const touch = () => { dirty = true; saveBtn.disabled = false; };
  const svgEl = (tag, attrs) => { const e = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
  const pos = ev => { const r = svg.getBoundingClientRect(); return [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))]; };
  const P = ([x, y]) => `${(x * 1000).toFixed(1)},${(y * 1000).toFixed(1)}`;

  const paint = () => {
    svg.replaceChildren(); labels.replaceChildren();
    W.zones.forEach((z, i) => {
      const col = S.zoneType[z.type]?.color || '#eab308';
      const pg = svgEl('polygon', { points: z.points.map(P).join(' '), fill: col, 'fill-opacity': i === sel ? 0.32 : 0.16, stroke: col, 'stroke-width': i === sel ? 3 : 2, 'vector-effect': 'non-scaling-stroke', class: 'ws-ze-poly' });
      pg.addEventListener('pointerdown', ev => { if (drawing) return; ev.stopPropagation(); sel = i; paint(); drawSide(); });
      svg.append(pg);
      const cxm = z.points.reduce((a, p) => a + p[0], 0) / z.points.length, cym = z.points.reduce((a, p) => a + p[1], 0) / z.points.length;
      if (z.type === 'vehicle_lane' && z.params?.dir != null) {
        const a = z.params.dir * Math.PI / 180, L = 60;
        svg.append(svgEl('line', { x1: cxm * 1000 - Math.cos(a) * L, y1: cym * 1000 - Math.sin(a) * L * 1.78, x2: cxm * 1000 + Math.cos(a) * L, y2: cym * 1000 + Math.sin(a) * L * 1.78, stroke: '#fff', 'stroke-width': 3, 'vector-effect': 'non-scaling-stroke', 'marker-end': 'url(#ws-arrow)' }));
      }
      labels.append(h('span', { class: 'ws-ze-label', style: { left: `${cxm * 100}%`, top: `${cym * 100}%` } }, z.name));
    });
    const defs = svgEl('defs', {});
    defs.innerHTML = '<marker id="ws-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#fff"/></marker>';
    svg.append(defs);
    if (sel >= 0 && W.zones[sel] && !drawing && S.canWrite) {
      W.zones[sel].points.forEach((p, j) => {
        const c = svgEl('ellipse', { cx: p[0] * 1000, cy: p[1] * 1000, rx: 9, ry: 16, class: 'ws-ze-pt' });
        c.addEventListener('pointerdown', ev => { ev.stopPropagation(); ev.preventDefault(); drag = { j }; svg.setPointerCapture(ev.pointerId); });
        c.addEventListener('contextmenu', ev => { ev.preventDefault(); if (W.zones[sel].points.length > 3) { W.zones[sel].points.splice(j, 1); touch(); paint(); } });
        c.addEventListener('dblclick', ev => { ev.stopPropagation(); const pts = W.zones[sel].points, n = pts[(j + 1) % pts.length]; pts.splice(j + 1, 0, [(p[0] + n[0]) / 2, (p[1] + n[1]) / 2]); touch(); paint(); });
        svg.append(c);
      });
    }
    if (drawing) {
      if (drawing.pts.length) svg.append(svgEl('polyline', { points: [...drawing.pts, drawing.cur || drawing.pts[drawing.pts.length - 1]].map(P).join(' '), fill: 'none', stroke: '#fff', 'stroke-width': 2, 'stroke-dasharray': '6 4', 'vector-effect': 'non-scaling-stroke' }));
      drawing.pts.forEach((p, j) => svg.append(svgEl('ellipse', { cx: p[0] * 1000, cy: p[1] * 1000, rx: j ? 6 : 10, ry: j ? 11 : 18, class: j ? 'ws-ze-pt' : 'ws-ze-pt first' })));
    }
    board.classList.toggle('drawing', !!drawing);
  };
  const finish = () => {
    if (!drawing) return;
    if (drawing.pts.length >= 3) { W.zones.push({ id: '', name: S.zoneType[drawing.type].name, type: drawing.type, points: drawing.pts.map(p => [+p[0].toFixed(4), +p[1].toFixed(4)]), params: {} }); sel = W.zones.length - 1; touch(); } else toast('Bölge için en az 3 nokta gerekir', 'err');
    drawing = null; paint(); drawSide();
  };
  svg.addEventListener('pointerdown', ev => {
    if (!drawing) { if (sel !== -1) { sel = -1; paint(); drawSide(); } return; }
    const p = pos(ev), f = drawing.pts[0];
    if (f && drawing.pts.length >= 3 && Math.hypot(p[0] - f[0], (p[1] - f[1]) * 0.56) < 0.02) return finish();
    drawing.pts.push(p); paint(); drawSide();
  });
  svg.addEventListener('pointermove', ev => {
    if (drag && sel >= 0) { W.zones[sel].points[drag.j] = pos(ev).map(v => +v.toFixed(4)); touch(); paint(); } else if (drawing) { drawing.cur = pos(ev); paint(); }
  });
  svg.addEventListener('pointerup', () => { drag = null; });
  svg.addEventListener('dblclick', () => { if (drawing) { drawing.pts.pop(); finish(); } });
  const onKey = ev => { if (ev.key === 'Escape' && drawing) { drawing = null; paint(); drawSide(); } else if (ev.key === 'Enter' && drawing) finish(); };
  document.addEventListener('keydown', onKey);
  onLeave(() => document.removeEventListener('keydown', onKey));

  const zoneParams = z => {
    const t = S.zoneType[z.type];
    z.params = z.params || {};
    return (t.params || []).map(k => {
      if (k === 'group') {
        const gs = S.cfg.ppe_groups || [];
        const gSel = h('select', { class: 'input', disabled: !S.canWrite }, [['', 'Grupsuz — aşağıda işaretlenen donanımlar'], ...gs.map(g => [g.id, g.name])]
          .map(([v, l]) => h('option', { value: v, selected: v === (groupOf(S, z.params.group)?.id || '') }, l)));
        gSel.addEventListener('change', () => { if (gSel.value) z.params.group = gSel.value; else delete z.params.group; touch(); drawSide(); });
        return field(ZONE_PARAM_LABEL[k], gSel, gs.length ? 'Grup seçilirse bu alandaki kişilerde yalnız grubun donanımları, grubun ayarlarıyla denetlenir; kameranın grubunun önüne geçer.' : 'Henüz grup yok; "KKD Grupları" sekmesinden eklenir.');
      }
      if (k === 'items' && groupOf(S, z.params.group)) return null;   // grup seçiliyken donanımları grup belirler
      if (k === 'auth_colors' || k === 'items') {
        const opts = k === 'items' ? S.cat.kkd : S.cat.colors, set = new Set(z.params[k] || []);
        return field(ZONE_PARAM_LABEL[k], h('div', { class: 'ws-pick' }, opts.map(o => {
          const cb = h('input', { type: 'checkbox', checked: set.has(o.key), disabled: !S.canWrite });
          cb.addEventListener('change', () => { cb.checked ? set.add(o.key) : set.delete(o.key); z.params[k] = [...set]; touch(); });
          return h('label', { class: 'ws-check' }, cb, o.name);
        })), k === 'items' ? 'Hiçbiri işaretlenmezse etkin tüm donanım kuralları bu alanda geçerli olur.' : 'Bu renkte kıyafeti olanlar yetkili sayılır; boşsa bölgeye giren herkes uyarı üretir.');
      }
      const inp = h('input', { class: 'input', type: k === 'from' || k === 'to' ? 'time' : 'number', min: 0, value: z.params[k] ?? '', disabled: !S.canWrite });
      inp.addEventListener('input', () => { if (inp.value === '') delete z.params[k]; else z.params[k] = inp.type === 'time' ? inp.value : Number(inp.value); touch(); if (k === 'dir') paint(); });
      return field(ZONE_PARAM_LABEL[k] || k, inp, k === 'from' ? 'Boş bırakılırsa kuraldaki saatler kullanılır.' : k === 'dir' ? 'Boş bırakılırsa yön denetlenmez.' : null);
    });
  };

  function drawSide() {
    const typeSel = h('select', { class: 'input' }, S.cat.zone_types.map(z => h('option', { value: z.key }, z.name)));
    const addBtn = h('button', { class: 'btn primary sm', onclick: () => { sel = -1; drawing = { type: typeSel.value, pts: [], cur: null }; paint(); drawSide(); } }, 'Çiz');
    const enabledCb = h('input', { type: 'checkbox', checked: W.enabled, disabled: !S.canWrite });
    enabledCb.addEventListener('change', () => { W.enabled = enabledCb.checked; touch(); });
    const ppeSel = ppeSelect(S, W.mode, v => { W.mode = v; touch(); }, { disabled: !S.canWrite });
    const allKeys = S.cat.rules.map(r => r.key);
    const ruleMs = multiSelect('Kurallar', S.cat.rules.map(r => [r.key, `${r.no}. ${r.name}`]), W.rules || allKeys,
      v => { W.rules = v.length === allKeys.length ? null : v; touch(); });
    const z = W.zones[sel];
    let edit = null;
    if (drawing) {
      edit = h('div', { class: 'card card-pad ws-ze-card' }, h('b', null, `Çizim: ${S.zoneType[drawing.type].name}`),
        h('p', { class: 'small muted' }, 'Görüntü üzerinde köşeleri sırayla tıklayın. Bitirmek için ilk noktaya tıklayın, çift tıklayın ya da Enter\'a basın. Esc: vazgeç.'),
        h('div', { class: 'ws-row' }, h('button', { class: 'btn sm primary', disabled: drawing.pts.length < 3, onclick: finish }, `Bitir (${drawing.pts.length} nokta)`),
          h('button', { class: 'btn sm', onclick: () => { drawing = null; paint(); drawSide(); } }, 'Vazgeç')));
    } else if (z) {
      const name = h('input', { class: 'input', value: z.name, maxlength: 60, disabled: !S.canWrite });
      name.addEventListener('input', () => { z.name = name.value; touch(); paint(); });
      const tSel = h('select', { class: 'input', disabled: !S.canWrite }, S.cat.zone_types.map(t => h('option', { value: t.key, selected: t.key === z.type }, t.name)));
      tSel.addEventListener('change', () => { z.type = tSel.value; z.params = {}; touch(); paint(); drawSide(); });
      const zg = z.type === 'ppe_zone' ? groupOf(S, z.params?.group) : null;
      const rules = S.zoneType[z.type].rules.map(k => S.rule[k]).filter(r => r && (!zg || zg.items[r.ppe]));
      edit = h('div', { class: 'card card-pad ws-ze-card' }, field('Bölge adı', name), field('Tür', tSel), zoneParams(z),
        h('p', { class: 'small muted' }, 'Bu bölgede çalışan kurallar: ', rules.map(r => `${r.no}. ${r.name}${zg || ruleOn(S, r) ? '' : ' (kapalı)'}`).join(' · ')),
        h('p', { class: 'small muted' }, 'Köşeyi sürükleyin · çift tık: araya nokta ekle · sağ tık: noktayı sil.'),
        S.canWrite ? h('button', { class: 'btn sm danger', onclick: () => { W.zones.splice(sel, 1); sel = -1; touch(); paint(); drawSide(); } }, 'Bölgeyi sil') : null);
    }
    clear(side,
      h('div', { class: 'card card-pad ws-ze-card' },
        h('label', { class: 'ws-check' }, enabledCb, h('span', null, h('b', null, 'Bu kamerada denetim yapılsın'))),
        field('KKD senaryo grubu', ppeSel, 'Görüntünün tamamında seçilen grubun donanımları (baret, yelek…) denetlenir. Gruplar "KKD Grupları" sekmesinde tanımlanır.'),
        S.canWrite ? h('div', { style: { marginTop: '8px' } }, ruleMs) : null),
      S.canWrite ? h('div', { class: 'card card-pad ws-ze-card' }, h('b', null, 'Yeni bölge'), h('div', { class: 'ws-row', style: { marginTop: '6px' } }, typeSel, addBtn)) : null,
      edit,
      h('div', { class: 'card card-pad ws-ze-card' }, h('b', null, `Bölgeler (${W.zones.length})`),
        W.zones.length ? h('div', { class: 'ws-ze-list' }, W.zones.map((zz, i) => h('button', { class: `ws-ze-item${i === sel ? ' on' : ''}`, type: 'button', onclick: () => { sel = i; drawing = null; paint(); drawSide(); } },
          h('i', { style: { background: S.zoneType[zz.type]?.color } }), h('span', { class: 'grow' }, zz.name), h('span', { class: 'small muted' }, S.zoneType[zz.type]?.name))))
          : h('p', { class: 'small muted', style: { margin: '6px 0 0' } }, 'Henüz bölge yok. Tür seçip "Çiz" ile görüntü üzerinde işaretleyin.')),
      h('div', { class: 'ws-row' }, saveBtn, h('button', { class: 'btn', onclick: () => fl.refresh() }, 'Görüntüyü yenile')));
  }
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    const cfg = structuredClone(S.cfg);
    cfg.cameras[String(cid)] = { enabled: W.enabled, ...ppeFields(W.mode), rules: W.rules, zones: W.zones };
    try {
      const saved = await S.save(cfg, 'Bölgeler kaydedildi');
      W.zones = structuredClone(saved.cameras[String(cid)]?.zones || []);
      dirty = false; sel = Math.min(sel, W.zones.length - 1); paint(); drawSide(); S.drawStrip();
    } catch (err) { toastError(err); saveBtn.disabled = false; }
  });
  const guard = ev => { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } };
  window.addEventListener('beforeunload', guard);
  onLeave(() => window.removeEventListener('beforeunload', guard));
  clear(stage, h('div', { class: 'ws-ze' }, board, side));
  paint(); drawSide();
}

// ============================================================ Isı Haritası
function heatPaint(canvas, grid, gw, gh, max) {
  const small = document.createElement('canvas');
  small.width = gw; small.height = gh;
  const sx = small.getContext('2d'), im = sx.createImageData(gw, gh);
  for (let i = 0; i < grid.length; i++) {
    const v = max > 0 ? Math.sqrt(grid[i] / max) : 0;   // karekök: az kullanılan hücreler de görünsün
    const hue = 240 - 240 * v;                          // mavi → kırmızı
    const [r, g, b] = hsl(hue, 1, 0.5);
    im.data[i * 4] = r; im.data[i * 4 + 1] = g; im.data[i * 4 + 2] = b; im.data[i * 4 + 3] = v <= 0 ? 0 : Math.round(60 + 170 * v);
  }
  sx.putImageData(im, 0, 0);
  const cx = canvas.getContext('2d');
  cx.clearRect(0, 0, canvas.width, canvas.height);
  cx.imageSmoothingEnabled = true; cx.imageSmoothingQuality = 'high';
  cx.drawImage(small, 0, 0, canvas.width, canvas.height);
}
function hsl(hh, s, l) {
  const a = s * Math.min(l, 1 - l), f = n => { const k = (n + hh / 30) % 12; return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))); };
  return [f(0), f(8), f(4)];
}

async function tabHeat(body, S) {
  let kind = pref('ws.heat.kind', 'person');
  const grid = h('div');
  const period = periodFilter('ws.heat', () => load(), { initial: 'week' });
  const kindSeg = segmented([['person', 'Kişi yoğunluğu'], ['vehicle', 'Araç yoğunluğu'], ['event', 'İhlal yoğunluğu']], kind, v => { kind = v; setPref('ws.heat.kind', v); load(); });
  body.append(moduleToolbar(period.el, kindSeg), grid);
  async function load() {
    const r = period.range(), q = new URLSearchParams({ kind });
    if (r.date_from) q.set('from', r.date_from); else q.set('from', '2000-01-01');
    q.set('to', r.date_to || new Date().toISOString().slice(0, 10));
    clear(grid, h('div', { class: 'loading' }, 'Yükleniyor…'));
    let d;
    try { d = await api.get(`/api/worksafety/heatmap?${q}`); } catch (err) { return clear(grid, h('div', { class: 'card empty' }, err.message || 'Isı haritası okunamadı')); }
    const list = d.cameras.filter(c => c.max > 0).sort((a, b) => b.sum - a.sum);
    if (!list.length) return clear(grid, h('div', { class: 'card empty' }, 'Bu dönemde kayıtlı yoğunluk verisi yok.'));
    clear(grid, h('div', { class: 'ws-heat-grid' }, list.map(c => {
      const img = h('img', { alt: '' });
      const cv = h('canvas', { width: 640, height: 360 });
      frameLoop(img, c.camera_id, { w: 640 });
      img.addEventListener('load', () => { if (img.naturalWidth) img.parentNode.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`; });
      heatPaint(cv, c.grid, d.w, d.h, c.max);
      return h('div', { class: 'card ws-heat' }, h('div', { class: 'ws-heat-pic' }, img, cv),
        h('div', { class: 'ws-heat-cap' }, h('b', null, S.camName(c.camera_id)),
          h('span', { class: 'small muted' }, kind === 'event' ? `risk toplamı ${num(Math.round(c.sum))}` : `${num(Math.round(c.sum))} gözlem`)));
    })), h('div', { class: 'ws-heat-legend small muted' }, 'Az', h('i', null), 'Çok'));
  }
  await load();
}

// ============================================================ Raporlar
const scoreTone = s => (s == null ? '' : s >= 90 ? 'green' : s >= 75 ? 'yellow' : 'red');
// Puanlar çoğunlukla 80–100 arasında kalır: farklar seçilsin diye taban en düşük puanın altındaki onluğa çekilir
const scoreFloor = days => { const v = days.map(x => x.score).filter(x => x != null); return v.length ? Math.max(0, Math.floor((Math.min(...v) - 10) / 10) * 10) : 0; };
function bars(items, { max = 100, min = 0, fmt = v => v, tone = scoreTone } = {}) {   // items: [{label, value, title}]; min: çubuk tabanı
  return h('div', { class: 'ws-bars' }, items.map(i => h('div', { class: 'ws-bar', title: i.title || '' },
    h('div', { class: 'ws-bar-col' }, i.value == null ? null : h('i', { class: tone(i.value), style: { height: `${Math.max(2, Math.min(100, 100 * (i.value - min) / ((max - min) || 1)))}%` } })),
    h('span', { class: 'ws-bar-v' }, i.value == null ? '·' : fmt(i.value)), h('span', { class: 'ws-bar-l' }, i.label))));
}

async function tabReport(body, S) {
  const out = h('div');
  let d = null;
  const period = periodFilter('ws.report', () => load(), { initial: 'week' });
  setListExport(() => {   // ortak Excel düğmesi: bütün kırılımlar tek sayfada
    if (!d) return { columns: [], rows: [] };
    const rows = [['Genel', `${d.from} – ${d.to}`, d.score, d.checks, d.violations, d.checks ? +(100 * d.violations / d.checks).toFixed(2) : '', d.events]];
    d.by_day.forEach(x => rows.push(['Gün', x.day, x.score ?? '', x.checks, x.violations, x.checks ? +(100 * x.violations / x.checks).toFixed(2) : '', x.events]));
    d.by_rule.forEach(x => rows.push(['Kural', `${x.no}. ${x.name}`, '', x.checks, x.violations, x.rate ?? '', x.events]));
    d.by_camera.forEach(x => rows.push(['Kamera', x.camera, x.score ?? '', x.checks, x.violations, x.checks ? +(100 * x.violations / x.checks).toFixed(2) : '', x.events]));
    d.by_shift.forEach(x => rows.push(['Vardiya', x.name, x.score ?? '', x.checks, x.violations, x.checks ? +(100 * x.violations / x.checks).toFixed(2) : '', '']));
    d.by_zone.forEach(x => rows.push(['Bölge', `${x.camera} › ${x.zone}`, '', '', '', '', x.events]));
    return { columns: ['Bölüm', 'Ad', 'Güvenlik puanı', 'Denetim', 'İhlal', 'İhlal oranı %', 'Uyarı'], rows };
  });
  body.append(moduleToolbar(period.el), out);
  const table = (cols, rows) => h('div', { class: 'table-wrap card' }, h('table', { class: 'table' }, h('thead', null, h('tr', null, cols.map(c => h('th', null, c)))), h('tbody', null, rows)));
  async function load() {
    const r = period.range(), q = new URLSearchParams();
    if (r.date_from) q.set('from', r.date_from);
    if (r.date_to) q.set('to', r.date_to > new Date().toISOString().slice(0, 10) ? new Date().toISOString().slice(0, 10) : r.date_to);
    if (!r.date_from && !r.date_to) q.set('from', new Date(Date.now() - 89 * 864e5).toISOString().slice(0, 10));
    clear(out, h('div', { class: 'loading' }, 'Yükleniyor…'));
    try { d = await api.get(`/api/worksafety/report?${q}`); } catch (err) { return clear(out, h('div', { class: 'card empty' }, err.message || 'Rapor okunamadı')); }
    if (!d.checks && !d.events) return clear(out, h('div', { class: 'card empty' }, `${d.from} – ${d.to} döneminde denetim kaydı yok.`));
    const diff = d.score != null && d.prev_score != null ? +(d.score - d.prev_score).toFixed(1) : null;
    const days = d.by_day.length > 45 ? d.by_day.filter((_, i) => i % Math.ceil(d.by_day.length / 45) === 0) : d.by_day;
    clear(out,
      h('div', { class: 'ws-rep-top' },
        h('div', { class: `card card-pad ws-score ${scoreTone(d.score)}` }, h('div', { class: 'ws-score-v' }, d.score == null ? '—' : d.score.toLocaleString('tr-TR')),
          h('div', { class: 'ws-score-l' }, 'Güvenlik puanı (100 üzerinden)'),
          diff == null ? null : h('div', { class: `small ${diff >= 0 ? 'ws-up' : 'ws-down'}` }, `Önceki ${d.days} güne göre ${diff >= 0 ? '+' : ''}${diff.toLocaleString('tr-TR')} puan`)),
        h('div', { class: 'card card-pad ws-rep-nums' },
          [['Denetim', num(d.checks)], ['İhlal', num(d.violations)], ['İhlal oranı', d.checks ? `%${(100 * d.violations / d.checks).toFixed(2).replace('.', ',')}` : '—'],
            ['Uyarı', num(d.events)], ['Açık uyarı', num(d.open_events)]].map(([k, v]) => h('div', null, h('b', null, v), h('span', null, k))),
          h('div', { class: 'ws-rep-levels' }, d.levels.filter(l => l.events).map(l => h('span', null, levelBadge(l.level), ` ${num(l.events)}`))))),
      h('h3', { class: 'ws-h3' }, 'Günlük güvenlik puanı'),
      h('div', { class: 'card card-pad' }, bars(days.map(x => ({ label: x.day.slice(8) + '.' + x.day.slice(5, 7), value: x.score, title: `${x.day}: ${num(x.checks)} denetim, ${num(x.violations)} ihlal, ${num(x.events)} uyarı` })), { fmt: v => Math.round(v), min: scoreFloor(days) })),
      h('div', { class: 'ws-rep-two' },
        h('div', null, h('h3', { class: 'ws-h3' }, 'Vardiyalar'),
          table(['Vardiya', 'Puan', 'Denetim', 'İhlal'], d.by_shift.map(x => h('tr', null, h('td', null, x.name), h('td', null, h('b', { class: `ws-t-${scoreTone(x.score)}` }, x.score ?? '—')), h('td', null, num(x.checks)), h('td', null, num(x.violations)))))),
        h('div', null, h('h3', { class: 'ws-h3' }, 'Saatlere göre ihlal'),
          h('div', { class: 'card card-pad' }, bars(d.by_hour.map(x => ({ label: String(x.hour).padStart(2, '0'), value: x.checks ? x.violations : null, title: `${x.hour}:00 — ${num(x.violations)} ihlal / ${num(x.checks)} denetim` })),
            { max: Math.max(1, ...d.by_hour.map(x => x.violations)), fmt: v => (v >= 1000 ? `${Math.round(v / 1000)}b` : v), tone: () => 'red' })))),
      h('h3', { class: 'ws-h3' }, 'Kurallara göre'),
      table(['No', 'Kural', 'Kategori', 'Denetim', 'İhlal', 'İhlal oranı', 'Uyarı'], d.by_rule.map(x => h('tr', null, h('td', { class: 'muted' }, String(x.no)), h('td', null, h('b', null, x.name)),
        h('td', { class: 'small' }, S.cat.cats.find(c => c.key === x.cat)?.name || x.cat), h('td', null, num(x.checks)), h('td', null, num(x.violations)),
        h('td', null, x.rate == null ? '—' : `%${String(x.rate).replace('.', ',')}`), h('td', null, num(x.events))))),
      h('h3', { class: 'ws-h3' }, 'Kameralara göre'),
      table(['Kamera', 'Puan', 'Denetim', 'İhlal', 'Uyarı'], d.by_camera.map(x => h('tr', null, h('td', null, h('b', null, x.camera)), h('td', null, h('b', { class: `ws-t-${scoreTone(x.score)}` }, x.score ?? '—')),
        h('td', null, num(x.checks)), h('td', null, num(x.violations)), h('td', null, num(x.events))))),
      d.by_zone.length ? [h('h3', { class: 'ws-h3' }, 'Bölgelere göre uyarı'),
        table(['Kamera', 'Bölge', 'Uyarı'], d.by_zone.map(x => h('tr', null, h('td', null, x.camera), h('td', null, h('b', null, x.zone)), h('td', null, num(x.events)))))] : null,
      h('p', { class: 'small muted' }, 'Güvenlik puanı: kural şiddetiyle ağırlıklandırılmış uyum oranı (ihlalsiz denetimlerin payı). Denetim = bir kuralın bir kamerada bir kez değerlendirilmesi.'));
  }
  await load();
}

// ============================================================ Ayarlar
async function tabSettings(body, S) {
  const st = S.cat.status || {}, C = structuredClone(S.cfg);
  const dis = !S.canWrite;
  const cb = (k, label, hint) => { const i = h('input', { type: 'checkbox', checked: !!C[k], disabled: dis }); i.addEventListener('change', () => { C[k] = i.checked; }); return h('label', { class: 'ws-check' }, i, h('span', null, h('b', null, label), hint ? h('div', { class: 'small muted' }, hint) : null)); };
  const nm = (k, label, hint, attrs = {}) => { const i = h('input', { class: 'input', type: 'number', value: C[k], disabled: dis, ...attrs }); i.addEventListener('input', () => { C[k] = Number(i.value); }); return field(label, i, hint); };
  const faces = h('select', { class: 'input', disabled: dis }, [['auto', 'Otomatik — işlem gücü yetmezse yüz tanımayı yavaşlat, gerekirse durdur'], ['on', 'Yüz tanıma her zaman tam hızda'], ['off', 'Denetim sürerken yüz tanımayı durdur']]
    .map(([v, l]) => h('option', { value: v, selected: C.faces_mode === v }, l)));
  faces.addEventListener('change', () => { C.faces_mode = faces.value; });
  const camState = new Map(S.cams.map(c => { const cc = S.cfg.cameras[String(c.id)]; return [c.id, { enabled: cc ? !!cc.enabled : !!S.cfg.all_cameras }]; }));
  const save = h('button', { class: 'btn primary', hidden: dis }, 'Kaydet');
  save.addEventListener('click', async () => {
    save.disabled = true;
    for (const c of S.cams) {
      const s = camState.get(c.id), cur = C.cameras[String(c.id)];
      if (cur) cur.enabled = s.enabled; else if (s.enabled !== !!C.all_cameras) C.cameras[String(c.id)] = { enabled: s.enabled, ppe: false, ppe_group: null, rules: null, zones: [] };
    }
    try { await S.save(C, 'Ayarlar kaydedildi'); window.dispatchEvent(new HashChangeEvent('hashchange')); }   // sayfayı yeni durumla yeniden çiz
    catch (err) { toastError(err); save.disabled = false; }
  });
  const kv = (k, v) => h('div', { class: 'ws-kv' }, h('span', null, k), h('b', null, v));
  const MODEL_TR = { objects: 'nesne', pose: 'duruş', ppe: 'donanım' };
  const models = Object.entries(st.models || {}).map(([k, v]) => `${MODEL_TR[k] || k}: ${v && v.backend ? (v.file || 'yüklü') : (v && v.error) || 'yok'}`).join(' · ');
  const statusCard = h('div', { class: 'card card-pad' }, h('b', null, 'İşleyici durumu'),
    st.reachable === false ? h('p', { class: 'small muted' }, st.problem || 'Fabrikaya ulaşılamıyor')
      : !st.ts ? h('p', { class: 'small muted' }, 'Kamera servisi henüz durum bildirmedi.')
        : h('div', { class: 'ws-kvs' },
          kv('Durum', st.running ? 'Çalışıyor' : `Yanıt yok (${Math.round(st.age)} sn)`), kv('Hızlandırma', String(st.backend || '').startsWith('cuda') ? 'Ekran kartı (CUDA)' : st.backend === 'cpu' ? 'İşlemci' : '—'),
          kv('Tur süresi', st.cycle_s != null ? `${st.cycle_s} sn` : '—'), kv('Denetlenen kamera', `${num(st.cams_active)} / ${num(st.cams_total)}`),
          kv('İşlemci yükü', st.load != null ? `${st.load} / ${st.cores} çekirdek` : '—'),
          kv('Yüz tanıma', st.faces_off ? 'Durduruldu (işlem gücü yetersiz ya da ayar)' : st.faces_mult > 1 ? `Yavaşlatıldı (1/${st.faces_mult})` : 'Tam hızda'),
          kv('Nesne / kişi modeli', st.objects ? 'Var' : 'Yok'), kv('Duruş (iskelet) modeli', st.pose ? 'Var' : 'Yok'),
          kv('Donanım sınıfları', (st.ppe || []).filter(k => !k.includes(':')).map(k => S.cat.kkd.find(x => x.key === k)?.name || k).join(', ') || 'Yok'),
          kv('Görüntü kuyruğu', num(st.queue)), models ? kv('Modeller', models) : null,
          (st.errors || []).length ? kv('Son hatalar', st.errors.join(' · ')) : null));
  const camTable = h('div', { class: 'table-wrap card' }, h('table', { class: 'table', 'data-dt': 'off' },
    h('thead', null, h('tr', null, ['Kamera', 'Konum', 'Görüntü', 'Denetim', 'KKD senaryo grubu', 'Bölge', ''].map(x => h('th', null, x)))),
    h('tbody', null, S.cams.map(c => {
      const s = camState.get(c.id);
      const e = h('input', { type: 'checkbox', checked: s.enabled, disabled: dis }); e.addEventListener('change', () => { s.enabled = e.checked; });
      const m = ppeMode(S, S.cfg.cameras[String(c.id)]);
      const p = m ? h('a', { class: `badge ${m === '*' ? 'gray' : 'blue'}`, href: '#/worksafety/groups' }, m === '*' ? 'Etkin tüm KKD kuralları' : groupOf(S, m).name) : h('span', { class: 'muted' }, '—');
      return h('tr', null, h('td', null, h('b', null, c.name)), h('td', { class: 'small' }, esc1(c.location)),
        h('td', { class: 'small' }, c.live_age != null && c.live_age < 30 ? h('span', { class: 'badge green' }, 'Canlı') : h('span', { class: 'badge gray' }, c.active === 0 ? 'Pasif' : 'Görüntü yok')),
        h('td', null, e), h('td', null, p), h('td', null, String(c.zones || 0)), h('td', null, h('a', { class: 'btn xs', href: `#/worksafety/zones/${c.id}` }, 'Bölgeler')));
    }))));
  const allBtn = (label, fn) => h('button', { class: 'btn xs', hidden: dis, onclick: () => { camState.forEach(fn); S.cams.forEach((c, i) => { camTable.querySelectorAll('tbody tr')[i].querySelector('input').checked = camState.get(c.id).enabled; }); } }, label);
  body.append(
    h('div', { class: 'ws-set' },
      h('div', { class: 'card card-pad' }, h('b', null, 'Genel'),
        cb('enabled', 'Denetim açık', 'Kapalıyken kamera servisi kural denetimi yapmaz; kayıtlı uyarılar ve raporlar görünmeye devam eder.'),
        cb('all_cameras', 'Yeni / ayarlanmamış kameralar kapsamda olsun', 'Kapalıysa yalnız aşağıda "Denetim" işaretli kameralar denetlenir.'),
        field('Yüz tanıma ile birlikte çalışma', faces, 'İkisi aynı bilgisayarda çalışır. Otomatik kipte tur süresi ve işlemci yükü ölçülür; yük düşünce yüz tanıma kendiliğinden geri açılır.'),
        cb('blur_faces', 'Uyarı görüntülerinde yüzleri gizle', 'Kare ve kliplerde baş bölgesi bulanıklaştırılır.'),
        cb('clip', 'Uyarıya kısa video klip ekle'),
        h('div', { class: 'ws-two' }, nm('interval', 'Denetim aralığı (sn)', 'Her kamera en sık bu aralıkla değerlendirilir.', { min: 0.5, max: 60, step: 0.5 }),
          nm('cooldown', 'Aynı uyarının yinelenme süresi (sn)', 'Aynı kamera ve kural için bu süre dolmadan yeni uyarı açılmaz.', { min: 30, step: 10 })),
        nm('retention_days', 'Kayıt saklama süresi (gün)', 'Daha eski uyarılar, kareler ve klipler silinir.', { min: 1, max: 3650 }),
        h('div', { class: 'ws-row', style: { marginTop: '10px' } }, save)),
      statusCard),
    h('h3', { class: 'ws-h3' }, 'Kamera kapsamı', h('span', { class: 'ws-h3-act' }, allBtn('Tümünü denetle', s => { s.enabled = true; }), allBtn('Hiçbirini denetleme', s => { s.enabled = false; }))),
    camTable,
    h('p', { class: 'small muted' }, 'Kamera kapsamındaki değişiklikler de yukarıdaki "Kaydet" ile saklanır. Kameranın KKD senaryo grubu "KKD Grupları" sekmesinden seçilir. Görüntüler fabrikadaki bilgisayarda işlenir; dışarıya gönderilmez.'));
}
