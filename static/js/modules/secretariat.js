// Sekreterya: misafir kaydı (bir grup = bir kayıt; Gelen Kişiler, Gelen Araçlar, Görüşülecek Kişiler) ve kargolar.
// Görüşülecek kişiye ve kargonun ilgili kişisine bildirim düşer. Kargolarım / Misafirlerim sayfaları da burada.
import { api, fileUrl } from '../api.js';
import { renderCalls } from './calls.js';
import { tabView } from './crm.js';
import { plateEl } from './security.js';
import {
  avatar, clear, companyName, confirmDialog, every, field, fmtDateTime, fmtDuration, h, matches, modal, moduleToolbar, pageHead, peoplePicker,
  secondsBetween, secondsSince, segmented, t, toast, toastError, periodFilter
} from '../ui.js';

const TABS = [['', 'Misafirler'], ['cargo', 'Kargolar'], ['calls', 'Aramalar']];
const CARRIERS = ['Aras Kargo', 'Yurtiçi Kargo', 'MNG Kargo', 'PTT Kargo', 'Sürat Kargo', 'UPS', 'DHL', 'FedEx', 'Hepsijet',
  'Trendyol Express', 'Kolay Gelsin', 'Kurye'];

export async function render(view, params, ctx) {
  if (params[0] === 'visit') return renderVisit(view, Number(params[1]), ctx, params[2]);
  const tab = ['cargo', 'calls'].includes(params[0]) ? params[0] : '';
  const history = params[0] === 'history';               // eski misafir kayıtları
  const delivered = tab === 'cargo' && params[1] === 'delivered';   // teslim edilen kargolar
  const nav = segmented(TABS, tab, v => { location.hash = v ? `#/secretariat/${v}` : '#/secretariat'; }, { tabs: true });
  const body = h('div');
  // Sekmenin ana işlemi ile eski kayıtlar / teslim edilenler toolbar'da (alt modül seçimi sekme çubuğunda)
  const cargoAdd = h('button', { class: 'btn primary', type: 'button' }, '+ Kargo Kaydet');
  const callAdd = h('button', { class: 'btn primary', type: 'button' }, '+ Yeni Arama');
  const toolbar = tab === 'calls' ? moduleToolbar(callAdd) : moduleToolbar(
    tab === 'cargo' ? (delivered ? null : cargoAdd) : h('button', { class: 'btn primary', type: 'button', onclick: () => newVisit() }, '+ Yeni Misafir Girişi'),
    tab === 'cargo'
      ? (delivered ? h('a', { class: 'btn', href: '#/secretariat/cargo' }, 'Bekleyen Kargolar') : h('a', { class: 'btn', href: '#/secretariat/cargo/delivered' }, 'Teslim Edilenler'))
      : (history ? h('a', { class: 'btn', href: '#/secretariat' }, 'Aktif Misafirler') : h('a', { class: 'btn', href: '#/secretariat/history' }, 'Eski Kayıtlar')));
  const title = history ? 'Sekreterya · Eski Kayıtlar' : delivered ? 'Sekreterya · Teslim Edilen Kargolar' : 'Sekreterya';
  const sub = history ? 'Çıkış yapmış misafir kayıtları' : delivered ? 'Teslim alınan kargolar'
    : tab === 'calls' ? 'Şirkete dışarıdan gelen telefonlar · ilgili kişiye bağlanır ve bildirilir' : 'Misafir kayıtları ve gelen kargolar';
  clear(view, pageHead(title, { back: history ? '#/secretariat' : delivered ? '#/secretariat/cargo' : '#/', sub, tabs: nav }), toolbar, body);
  if (tab === 'calls') return renderCalls(body, callAdd, toolbar);
  if (tab === 'cargo') return delivered ? renderDelivered(body) : renderCargo(body, cargoAdd);
  return history ? renderHistory(body) : renderVisits(body);
}

// ---------- Misafirler: yalnızca içerideki (aktif) misafirler
const visitCard = r => h('a', { class: 'card visit-card', href: `#/secretariat/visit/${r.id}` },
  h('div', { class: 'visit-top' }, h('b', null, r.code), h('span', { class: 'badge green' }, 'İçeride')),
  r.purpose ? h('div', { class: 'visit-purpose' }, r.purpose) : null,
  h('div', { class: 'small' }, h('b', null, t('{n} kişi: ', { n: r.people_count })), r.people_names || 'kişi eklenmedi'),
  h('div', { class: 'small muted' }, t('Görüşülecek: {h}', { h: r.host_names || '—' })),
  r.plates ? h('div', { class: 'small muted' }, t('Araç: {p}', { p: r.plates })) : null,
  h('div', { class: 'small muted' }, `${fmtDateTime(r.arrived_at)} · ${fmtDuration(secondsSince(r.arrived_at))}`));

async function renderVisits(body) {
  const load = async () => {
    const inside = (await api.get('/api/secretariat/visits?scope=inside')).filter(r => !r.left_at);
    clear(body, inside.length ? h('div', { class: 'visit-grid' }, inside.map(visitCard))
      : h('div', { class: 'card empty' }, 'İçeride misafir yok. Yeni misafir için sağ üstteki "Yeni Misafir Girişi"ni kullanın.'));
  };
  await load();
  every(20000, () => load().catch(() => {}));
}

// ---------- Eski kayıtlar: çıkış yapmış misafirler (arama ile)
async function renderHistory(body) {
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kod, kişi, görüşülen, plaka, amaç ara…', style: { width: '280px' } });
  const out = h('div');
  const period = periodFilter('secHistory', () => renderHistory(body), { title: 'Geliş tarihi' });
  const rows = (await api.get(`/api/secretariat/visits?scope=history&${period.qs()}`)).filter(r => r.left_at);
  const draw = () => {
    const list = rows.filter(r => matches(q.value, r.code, r.purpose, r.people_names, r.host_names, r.plates, r.note));
    clear(out, list.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Kod', 'Geliş', 'Çıkış', 'Kişiler', 'Görüşülen', 'Araçlar', 'Amaç'].map(t => h('th', null, t)))),
      h('tbody', null, list.map(r => h('tr', { class: 'click', onclick: () => { location.hash = `#/secretariat/visit/${r.id}`; } },
        h('td', null, h('b', null, r.code)), h('td', null, fmtDateTime(r.arrived_at)), h('td', null, fmtDateTime(r.left_at)),
        h('td', { class: 'wrap' }, r.people_names || '—'), h('td', { class: 'wrap' }, r.host_names || '—'),
        h('td', null, r.plates || '—'), h('td', { class: 'wrap' }, r.purpose || '—')))))))
      : h('div', { class: 'card empty' }, rows.length ? 'Aramaya uyan kayıt yok' : 'Eski kayıt yok'));
  };
  q.addEventListener('input', draw);
  clear(body, h('div', { class: 'filters' }, q, period.el, h('span', { class: 'small muted' }, t('{n} kayıt', { n: rows.length }))), out);
  draw();
}

function newVisit() {
  const purpose = h('input', { class: 'input', placeholder: 'Ör. Proje toplantısı, teslimat, mülakat' });
  const note = h('textarea', { class: 'input', rows: 2, placeholder: 'İsteğe bağlı' });
  modal({
    title: 'Yeni Misafir Girişi',
    body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } },
      'Kaç kişi gelirse gelsin tek kayıt açılır; kişiler, araçlar ve görüşülecek kişiler kaydın içinden eklenir.'),
      field('Ziyaret amacı', purpose), field('Not', note)),
    actions: [{ label: 'Vazgeç' }, {
      label: 'Kaydı Aç', class: 'primary', onClick: async () => {
        const r = await api.post('/api/secretariat/visits', { purpose: purpose.value, note: note.value });
        toast(t('{code} açıldı', { code: r.code }));
        location.hash = `#/secretariat/visit/${r.id}`;
      },
    }],
  });
}

// ---------- Misafir kaydı detayı
async function renderVisit(view, id, ctx, sub) {
  let v = await api.get(`/api/secretariat/visits/${id}`);
  const headBox = h('div');
  const drawHead = () => clear(headBox,
    pageHead(`${v.code}${v.purpose ? ` — ${v.purpose}` : ''}`, {
      back: '#/secretariat',
      sub: h('span', null, v.left_at ? h('span', { class: 'badge gray' }, 'Çıkış yaptı') : h('span', { class: 'badge green' }, 'İçeride'),
        t('  Geliş {d}', { d: fmtDateTime(v.arrived_at) }), v.left_at ? t(' · Çıkış {d} · {dur}', { d: fmtDateTime(v.left_at), dur: fmtDuration(secondsBetween(v.arrived_at, v.left_at)) }) : '',
        t(' · Kaydeden: {name}', { name: v.created_by_name || '—' })),
    }),
    moduleToolbar(
      h('button', { class: 'btn', onclick: () => editVisit() }, 'Düzenle'),
      v.kvkk_signed_at
        ? h('button', { class: 'btn ghost', onclick: () => kvkkSign() }, '✓ KVKK imzalı')
        : h('button', { class: 'btn primary', onclick: () => kvkkSign() }, 'KVKK Sözleşmesi & İmza'),
      !v.left_at ? h('button', { class: 'btn success', onclick: () => leave() }, 'Misafir Çıkışı') : null),
    !v.kvkk_signed_at ? h('div', { class: 'alert warn' }, 'KVKK aydınlatma/açık rıza imzası alınmadı. Misafire ekranda sözleşmeyi gösterip parmakla imzalatın.') : null,
    v.note ? h('div', { class: 'alert info' }, v.note) : null);
  const set = nv => { v = nv; drawHead(); tabs = buildTabs(); clear(tabBox, tabs); };
  async function leave() {
    if (!await confirmDialog('Misafir çıkışı', t('{code} misafirleri çıkış yaptı mı?', { code: v.code }), { okLabel: 'Çıkış Yaptı' })) return;
    try { set(await api.post(`/api/secretariat/visits/${id}/leave`)); toast('Misafir çıkışı kaydedildi'); } catch (err) { toastError(err); }
  }
  function editVisit() {
    const purpose = h('input', { class: 'input', value: v.purpose || '' });
    const note = h('textarea', { class: 'input', rows: 2 }, v.note || '');
    modal({ title: t('{code} — Düzenle', { code: v.code }), body: h('div', null, field('Ziyaret amacı', purpose), field('Not', note)),
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        set(await api.put(`/api/secretariat/visits/${id}`, { purpose: purpose.value, note: note.value }));
      } }] });
  }
  // Misafir KVKK: ekranda aydınlatma/açık rıza + parmakla imza (şirkette CCTV/yüz tanıma olduğu için)
  function kvkkSign() {
    const textBox = h('div', { class: 'kvkk-text', style: { maxHeight: '34vh', overflow: 'auto', textAlign: 'left', border: '1px solid var(--line)', borderRadius: '10px', padding: '12px', fontSize: '14px', lineHeight: '1.5' } }, 'Yükleniyor…');
    const canvas = h('canvas', { width: 600, height: 220, style: { width: '100%', maxWidth: '600px', height: '220px', border: '1px dashed var(--line)', borderRadius: '10px', touchAction: 'none', background: '#fff', marginTop: '6px' } });
    const c2 = canvas.getContext('2d');
    c2.lineWidth = 2.5; c2.lineCap = 'round'; c2.lineJoin = 'round'; c2.strokeStyle = '#0b1b3a';
    let drawing = false, dirty = false, last = null;
    const pos = e => { const r = canvas.getBoundingClientRect(); return { x: (e.clientX - r.left) * (canvas.width / r.width), y: (e.clientY - r.top) * (canvas.height / r.height) }; };
    canvas.addEventListener('pointerdown', e => { drawing = true; last = pos(e); try { canvas.setPointerCapture(e.pointerId); } catch { /* */ } });
    canvas.addEventListener('pointermove', e => { if (!drawing) return; const p = pos(e); c2.beginPath(); c2.moveTo(last.x, last.y); c2.lineTo(p.x, p.y); c2.stroke(); last = p; dirty = true; });
    const end = () => { drawing = false; };
    canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end);
    const clearBtn = h('button', { class: 'btn ghost sm', type: 'button', onclick: () => { c2.clearRect(0, 0, canvas.width, canvas.height); dirty = false; } }, 'Temizle');
    const prev = v.kvkk_signed_at ? h('div', { class: 'small muted', style: { marginBottom: '6px' } },
      t('Daha önce imzalandı: {d}. Yeniden imzalarsanız öncekinin yerine geçer.', { d: fmtDateTime(v.kvkk_signed_at) })) : null;
    modal({
      title: 'KVKK Aydınlatma ve Açık Rıza — Misafir', wide: true,
      body: h('div', null, prev, textBox, h('p', { class: 'small muted', style: { margin: '10px 0 0' } }, 'Lütfen aşağıdaki alana parmağınızla imzalayın.'), canvas, h('div', { style: { marginTop: '6px' } }, clearBtn)),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'Onayla ve Kaydet', class: 'primary', onClick: async () => {
        if (!dirty) { toast('Lütfen imzalayın', 'err'); return true; }
        try { set(await api.post(`/api/secretariat/visits/${id}/kvkk`, { signature: canvas.toDataURL('image/png') })); toast('KVKK açık rıza imzası kaydedildi', 'success'); }
        catch (err) { toastError(err); return true; }
      } }],
    });
    api.get('/api/secretariat/kvkk-text').then(d => { textBox.innerHTML = d.html; }).catch(() => { textBox.textContent = 'Metin yüklenemedi.'; });
  }
  let current = sub || 'people';
  const buildTabs = () => tabView([
    { key: 'people', label: 'Gelen Kişiler', count: v.people.length, render: () => peopleTab() },
    { key: 'vehicles', label: 'Gelen Araçlar', count: v.vehicles.length, render: () => vehiclesTab() },
    { key: 'hosts', label: 'Görüşülecek Kişiler', count: v.hosts.length, render: () => hostsTab() },
  ], current, k => { current = k; });
  const tabBox = h('div');
  let tabs = buildTabs();
  drawHead();
  clear(view, headBox, tabBox);
  clear(tabBox, tabs);

  const del = async (url, msg) => { try { set(await api.del(url)); toast(msg); } catch (err) { toastError(err); } };

  function peopleTab() {
    return h('div', { class: 'tab-pad' },
      h('div', { class: 'row-actions', style: { marginBottom: '10px' } }, h('button', { class: 'btn primary', onclick: () => addGuest() }, '+ Kişi Ekle')),
      v.people.length ? h('div', { class: 'guest-list' }, v.people.map(p => h('div', { class: 'guest-row' },
        h('div', { class: 'grow' }, h('b', null, p.full_name), p.title ? h('span', { class: 'muted' }, ` · ${p.title}`) : null,
          h('div', { class: 'small muted' }, p.company_name ? companyName(p.company_name) : p.company_text || 'Firma belirtilmedi',
            p.person_id ? ' · Rehberde kayıtlı' : ' · Serbest giriş', p.phone ? ` · ${p.phone}` : '')),
        h('button', { class: 'btn sm ghost', onclick: () => del(`/api/secretariat/visits/${id}/people/${p.id}`, 'Kişi çıkarıldı') }, 'Çıkar'))))
        : h('div', { class: 'empty' }, 'Henüz kişi eklenmedi'));
  }

  // Gelen kişi: rehberde (firma kişileri) ara; bulunamazsa bir firmaya yeni kişi ya da serbest giriş
  async function addGuest() {
    const [people, companies] = await Promise.all([api.get('/api/secretariat/people'), api.get('/api/secretariat/companies')]);
    const q = h('input', { class: 'input', type: 'search', placeholder: 'Ad soyad ya da firma ara…' });
    const results = h('div', { class: 'pick-list' });
    const name = h('input', { class: 'input', placeholder: 'Ad soyad' });
    const title = h('input', { class: 'input', placeholder: 'Unvan (isteğe bağlı)' });
    const phone = h('input', { class: 'input', placeholder: 'Telefon (isteğe bağlı)', inputmode: 'tel' });
    const company = h('select', { class: 'input' }, h('option', { value: '' }, 'Serbest (firma adını yazın)'),
      companies.map(c => h('option', { value: c.id }, c.name)));
    const companyText = h('input', { class: 'input', placeholder: 'Firma adı (sistemde yoksa)', style: { width: '100%' } });
    company.addEventListener('change', () => { companyText.hidden = !!company.value; });
    let m;
    const drawResults = () => {
      const hits = people.filter(p => matches(q.value, p.full_name, p.company_name, p.title)).slice(0, 30);
      clear(results, q.value.trim().length < 2 ? h('div', { class: 'empty small' }, 'Aramak için en az 2 harf yazın')
        : hits.length ? hits.map(p => h('button', { class: 'pick', type: 'button', onclick: async () => {
          try { set(await api.post(`/api/secretariat/visits/${id}/people`, { person_id: p.id })); toast(t('{name} eklendi', { name: p.full_name })); m.close(); }
          catch (err) { toastError(err); }
        } }, h('div', { class: 'grow' }, h('b', null, p.full_name), h('span', { class: 'small muted' },
          [p.title, p.company_name].filter(Boolean).join(' · ')))))
          : h('div', { class: 'empty small' }, 'Rehberde bulunamadı; aşağıdan yeni kişi olarak ekleyin'));
      if (!name.value && hits.length === 0) name.value = q.value;
    };
    q.addEventListener('input', drawResults);
    drawResults();
    m = modal({
      title: 'Gelen Kişi Ekle', wide: true,
      body: h('div', null,
        field('Rehberde ara (firma kişileri)', q), results,
        h('h3', { class: 'sub-h' }, 'Bulamazsanız yeni kişi'),
        h('div', { class: 'row' }, field('Ad soyad', name), field('Unvan', title)),
        h('div', { class: 'row' }, field('Firma', company), field('Telefon', phone)), companyText,
        h('p', { class: 'small muted' }, 'Bir firma seçerseniz kişi o firmanın personeli olarak Rehber\'e de eklenir.')),
      actions: [{ label: 'Kapat' }, { label: 'Yeni Kişi Olarak Ekle', class: 'primary', onClick: async () => {
        set(await api.post(`/api/secretariat/visits/${id}/people`, {
          full_name: name.value, title: title.value, phone: phone.value,
          company_id: company.value ? Number(company.value) : null, company_text: company.value ? null : companyText.value,
        }));
        toast(t('{name} eklendi', { name: name.value }));
      } }],
    });
    q.focus();
  }

  function vehiclesTab() {
    return h('div', { class: 'tab-pad' },
      h('div', { class: 'row-actions', style: { marginBottom: '10px' } }, h('button', { class: 'btn primary', onclick: () => pickVehicles() }, '+ Araç Seç')),
      v.vehicles.length ? h('div', { class: 'guest-list' }, v.vehicles.map(x => h('div', { class: 'guest-row' },
        plateEl(x.plate, 'sm'),
        h('div', { class: 'grow small muted' }, t('Giriş {d}', { d: fmtDateTime(x.entered_at) }), x.exited_at ? t(' · Çıkış {d}', { d: fmtDateTime(x.exited_at) }) : ' · Parkta',
          x.note ? ` · ${x.note}` : ''),
        h('button', { class: 'btn sm ghost', onclick: () => del(`/api/secretariat/visits/${id}/vehicles/${x.id}`, 'Araç çıkarıldı') }, 'Çıkar'))))
        : h('div', { class: 'empty' }, 'Araç eklenmedi'));
  }

  async function pickVehicles() {
    const parked = (await api.get('/api/secretariat/parked')).filter(x => !v.vehicles.some(y => y.id === x.id));
    const chosen = new Set();
    const list = h('div', { class: 'pick-list multi' }, parked.length ? parked.map(x => {
      const cb = h('input', { type: 'checkbox' });
      const row = h('div', { class: 'pick' }, cb, plateEl(x.plate, 'sm'),
        h('span', { class: 'small muted grow' }, t('Giriş {d}{note}{code}', { d: fmtDateTime(x.entered_at), note: x.note ? ` · ${x.note}` : '', code: x.visit_code ? ` · ${x.visit_code}` : '' })));
      row.addEventListener('click', e => {
        if (e.target !== cb) cb.checked = !cb.checked;
        cb.checked ? chosen.add(x.id) : chosen.delete(x.id);
        row.classList.toggle('on', cb.checked);
      });
      return row;
    }) : h('div', { class: 'empty' }, 'Parkta (güvenliğin kaydettiği, çıkış yapmamış) araç yok'));
    modal({ title: 'Gelen Araçlar', body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } },
      'Güvenliğin kaydettiği, şu an parktaki araçlar. Birden fazla seçebilirsiniz.'), list),
    actions: [{ label: 'Vazgeç' }, { label: 'Ekle', class: 'primary', onClick: async () => {
      if (!chosen.size) throw new Error('Araç seçin');
      set(await api.post(`/api/secretariat/visits/${id}/vehicles`, { ids: [...chosen] }));
    } }] });
  }

  function hostsTab() {
    return h('div', { class: 'tab-pad' },
      h('div', { class: 'row-actions', style: { marginBottom: '10px' } }, h('button', { class: 'btn primary', onclick: () => pickHosts() }, '+ Kişi Seç')),
      h('p', { class: 'small muted' }, 'Seçilen firma kullanıcılarına "Misafiriniz geldi" bildirimi gider.'),
      v.hosts.length ? h('div', { class: 'guest-list' }, v.hosts.map(u => h('div', { class: 'guest-row' },
        avatar(u), h('div', { class: 'grow' }, h('b', null, u.full_name), h('div', { class: 'small muted' }, t('Bildirildi {d}', { d: fmtDateTime(u.added_at) }))),
        h('button', { class: 'btn sm ghost', onclick: () => del(`/api/secretariat/visits/${id}/hosts/${u.id}`, 'Kişi çıkarıldı') }, 'Çıkar'))))
        : h('div', { class: 'empty' }, 'Görüşülecek kişi seçilmedi'));
  }

  async function pickHosts() {
    const users = (await api.get('/api/people')).filter(u => !v.hosts.some(x => x.id === u.id));
    const q = h('input', { class: 'input', type: 'search', placeholder: 'Kullanıcı ara…' });
    let picker = peoplePicker(users, { empty: 'Seçilecek kullanıcı yok' });
    const box = h('div', null, picker);
    q.addEventListener('input', () => {
      const keep = picker.getIds();
      picker = peoplePicker(users.filter(u => matches(q.value, u.full_name, u.username)), { selected: keep });
      clear(box, picker);
    });
    modal({ title: 'Görüşülecek Kişiler', body: h('div', null, q, box),
      actions: [{ label: 'Vazgeç' }, { label: 'Ekle ve Bildir', class: 'primary', onClick: async () => {
        const ids = picker.getIds();
        if (!ids.length) throw new Error('Kişi seçin');
        set(await api.post(`/api/secretariat/visits/${id}/hosts`, { ids }));
        toast('Bildirim gönderildi');
      } }] });
  }
}

// ---------- Kargolar
const cargoPhoto = k => (k.photo ? h('a', { class: 'cargo-img', href: fileUrl(k.photo), target: '_blank', rel: 'noopener', onclick: e => e.stopPropagation() },
  h('img', { src: fileUrl(k.photo, 512), alt: 'Kargo resmi', loading: 'lazy' })) : h('div', { class: 'cargo-img none' }, 'Resim yok'));

// Kargolar: yalnızca bekleyenler (kart); teslim edilenler ayrı sayfada (#/secretariat/cargo/delivered)
async function renderCargo(body, addBtn) {
  const load = async () => {
    const waiting = (await api.get('/api/secretariat/cargo')).filter(k => !k.delivered_at);
    clear(body, waiting.length ? h('div', { class: 'cargo-grid' }, waiting.map(k => h('div', { class: 'card cargo-card' }, cargoPhoto(k),
      h('div', { class: 'cargo-body' },
        h('b', null, k.recipient_name), h('div', { class: 'small' }, [k.carrier, k.tracking_no].filter(Boolean).join(' · ') || 'Kargo'),
        k.description ? h('div', { class: 'small muted' }, k.description) : null,
        h('div', { class: 'small muted' }, t('{d} · {dur} bekliyor', { d: fmtDateTime(k.created_at), dur: fmtDuration(secondsSince(k.created_at)) })),
        h('button', { class: 'btn sm', onclick: () => deliver(k) }, 'Elden Teslim Edildi')))))
      : h('div', { class: 'card empty' }, 'Bekleyen kargo yok. Gelen kargo için sağ üstteki "Kargo Kaydet"i kullanın.'));
  };
  async function deliver(k) {
    if (!await confirmDialog('Kargo teslimi', t('{name} kargosunu elden teslim aldı mı?', { name: k.recipient_name }), { okLabel: 'Teslim Edildi' })) return;
    try { await api.post(`/api/secretariat/cargo/${k.id}/deliver`); toast('Teslim edildi'); await load(); } catch (err) { toastError(err); }
  }
  addBtn.onclick = () => newCargo(load);
  await load();
  every(30000, () => load().catch(() => {}));
}

async function renderDelivered(body) {
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi, kargo firması, takip no, açıklama ara…', style: { width: '280px' } });
  const out = h('div');
  const period = periodFilter('secDelivered', () => renderDelivered(body), { title: 'Teslim tarihi' });
  const rows = (await api.get(`/api/secretariat/cargo?${period.qs()}`)).filter(k => k.delivered_at);
  const draw = () => {
    const list = rows.filter(k => matches(q.value, k.recipient_name, k.carrier, k.tracking_no, k.description, k.delivered_by_name));
    clear(out, list.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Geliş', 'İlgili kişi', 'Kargo', 'Açıklama', 'Teslim', 'Teslim şekli', 'Resim'].map(t => h('th', null, t)))),
      h('tbody', null, list.map(k => h('tr', null,
        h('td', null, fmtDateTime(k.created_at)), h('td', null, k.recipient_name),
        h('td', null, [k.carrier, k.tracking_no].filter(Boolean).join(' · ') || '—'), h('td', { class: 'wrap' }, k.description || '—'),
        h('td', null, fmtDateTime(k.delivered_at)),
        h('td', { class: 'small' }, k.delivered_by === k.recipient_id ? 'Kendisi teslim aldı' : t('Elden teslim ({name})', { name: k.delivered_by_name || 'sekreterya' })),
        h('td', null, k.photo ? h('a', { href: fileUrl(k.photo), target: '_blank', rel: 'noopener' }, 'Aç') : '—')))))))
      : h('div', { class: 'card empty' }, rows.length ? 'Aramaya uyan kayıt yok' : 'Teslim edilmiş kargo yok'));
  };
  q.addEventListener('input', draw);
  clear(body, h('div', { class: 'filters' }, q, period.el, h('span', { class: 'small muted' }, t('{n} kayıt', { n: rows.length }))), out);
  draw();
}

async function newCargo(done) {
  const users = await api.get('/api/people');
  const q = h('input', { class: 'input', type: 'search', placeholder: 'İlgili kişiyi ara…' });
  const who = h('select', { class: 'input', size: 6 });
  const fill = () => clear(who, users.filter(u => matches(q.value, u.full_name, u.username)).map(u => h('option', { value: u.id }, u.full_name)));
  q.addEventListener('input', fill);
  fill();
  const carrier = h('input', { class: 'input', list: 'carrier-list', placeholder: 'Kargo firması' });
  const dl = h('datalist', { id: 'carrier-list' }, CARRIERS.map(c => h('option', { value: c })));
  const tracking = h('input', { class: 'input', placeholder: 'Takip no (isteğe bağlı)' });
  const desc = h('input', { class: 'input', placeholder: 'Açıklama (ör. 1 koli, zarf)' });
  const file = h('input', { type: 'file', accept: 'image/*', capture: 'environment', class: 'input' });
  const preview = h('div', { class: 'cargo-preview' }, 'Resim çekilmedi');
  file.addEventListener('change', () => {
    const f = file.files[0];
    clear(preview, f ? h('img', { src: URL.createObjectURL(f), alt: '' }) : 'Resim çekilmedi');
  });
  modal({
    title: 'Kargo Kaydet', wide: true,
    body: h('div', { class: 'cargo-form' },
      h('div', null, field('İlgili kişi', h('div', null, q, who)), h('div', { class: 'row' }, field('Kargo firması', carrier), field('Takip no', tracking)), dl,
        field('Açıklama', desc)),
      h('div', null, field('Kargonun resmi (kamerayla çekin)', file), preview)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet ve Bildir', class: 'primary', onClick: async () => {
      if (!who.value) throw new Error('İlgili kişiyi seçin');
      const fd = new FormData();
      fd.append('recipient_id', who.value);
      fd.append('carrier', carrier.value);
      fd.append('tracking_no', tracking.value);
      fd.append('description', desc.value);
      if (file.files[0]) fd.append('photo', file.files[0]);
      await api.post('/api/secretariat/cargo', fd);
      toast('Kargo kaydedildi, ilgili kişiye bildirildi');
      done();
    } }],
  });
}

// ---------- Kişiye özel sayfalar (kullanıcı menüsü)
export async function renderMyCargo(view, params = []) {
  const history = params[0] === 'history';
  const nav = segmented([['', 'Bekleyen Kargolar'], ['history', 'Kargo Geçmişi']], history ? 'history' : '',
    v => { location.hash = v ? '#/my-cargo/history' : '#/my-cargo'; }, { tabs: true });
  const out = h('div');
  const load = async () => {
    const rows = await api.get('/api/me/cargo');
    if (history) {   // teslim aldıklarım
      const done = rows.filter(k => k.delivered_at);
      const row = k => h('tr', null,
        h('td', null, k.photo ? h('a', { href: fileUrl(k.photo), target: '_blank', rel: 'noopener' },
          h('img', { class: 'pe-thumb', src: fileUrl(k.photo, 256), alt: 'Kargo resmi', loading: 'lazy' })) : h('span', { class: 'muted small' }, 'Resim yok')),
        h('td', null, h('b', null, k.carrier || 'Kargo'), k.tracking_no ? h('div', { class: 'small muted mono' }, k.tracking_no) : null),
        h('td', { class: 'wrap' }, k.description || '—'),
        h('td', null, fmtDateTime(k.created_at)),
        h('td', null, fmtDateTime(k.delivered_at)),
        h('td', { class: 'small' }, k.delivered_by === k.recipient_id ? 'Kendim teslim aldım' : t('Elden teslim ({name})', { name: k.delivered_by_name || 'sekreterya' })));
      const table = h('table', null,
        h('thead', null, h('tr', null, ['Resim', 'Kargo', 'Açıklama', 'Geldi', 'Teslim', 'Teslim şekli'].map(t => h('th', null, t)))),
        h('tbody', null, done.map(row)));
      clear(out, done.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, table))
        : h('div', { class: 'card empty' }, 'Teslim aldığınız kargo yok'));
      return;
    }
    const waiting = rows.filter(k => !k.delivered_at);
    clear(out, waiting.length ? h('div', { class: 'cargo-grid' }, waiting.map(k => h('div', { class: 'card cargo-card' }, cargoPhoto(k),
      h('div', { class: 'cargo-body' },
        h('b', null, [k.carrier, k.tracking_no].filter(Boolean).join(' · ') || 'Kargo'),
        k.description ? h('div', { class: 'small' }, k.description) : null,
        h('div', { class: 'small muted' }, t('{d} · kaydeden {name}', { d: fmtDateTime(k.created_at), name: k.created_by_name || '—' })),
        h('div', { class: 'small muted' }, t('{dur} bekliyor', { dur: fmtDuration(secondsSince(k.created_at)) })),
        h('button', { class: 'btn success', onclick: async () => {
          try { await api.post(`/api/me/cargo/${k.id}/receive`); toast('Teslim aldınız'); await load(); } catch (err) { toastError(err); }
        } }, 'Teslim Aldım')))))
      : h('div', { class: 'card empty' }, 'Bekleyen kargonuz yok'));
  };
  clear(view, pageHead('Kargolarım', { back: '#/', sub: history ? 'Teslim aldığınız kargolar' : 'Sizin için bekleyen kargolar', tabs: nav }), out);
  await load();
  if (!history) every(30000, () => load().catch(() => {}));
}

export async function renderMyGuests(view) {
  const rows = await api.get('/api/me/guests');
  clear(view, pageHead('Misafirlerim', { back: '#/', sub: 'Size bildirilen misafirler' }),
    rows.length ? h('div', { class: 'visit-grid' }, rows.map(r => h('div', { class: 'card visit-card' },
      h('div', { class: 'visit-top' }, h('b', null, r.code), r.left_at ? h('span', { class: 'badge gray' }, 'Çıkış yaptı') : h('span', { class: 'badge green' }, 'İçeride')),
      r.purpose ? h('div', { class: 'visit-purpose' }, r.purpose) : null,
      h('ul', { class: 'guest-mini' }, r.people.map(p => h('li', null, h('b', null, p.full_name),
        h('span', { class: 'small muted' }, ` ${[p.title, p.company_name ? null : p.company_text].filter(Boolean).join(' · ')} `),
        p.company_name ? companyName(p.company_name, { class: 'small muted' }) : null))),
      r.plates ? h('div', { class: 'small muted' }, t('Araç: {p}', { p: r.plates })) : null,
      h('div', { class: 'small muted' }, t('Geliş {a}{left}', { a: fmtDateTime(r.arrived_at), left: r.left_at ? t(' · Çıkış {d}', { d: fmtDateTime(r.left_at) }) : '' })))))
      : h('div', { class: 'card empty' }, 'Size bildirilmiş misafir yok'));
}
