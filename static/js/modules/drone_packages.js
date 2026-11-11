// Dron Yönetimi › Veri Paketleri (#/drone/packages; RBAC 'drone.packages': okuma = liste / tüketim, yazma = ekle / düzenle / sil).
// Uydu / ücretli hat veri paketleri (ör. Certus 100 Aviation). Uçuş bağlantısı (Görev › Uçuş › Bağlantı) pakete bağlanır; köprü ↔ sunucu
// ya da dron ↔ köprü hattında ölçülen tüketim paketin GEÇERLİ döneminden düşer (app/data_packages.py). Otomatik yenilemede dönem döner.
import { api } from '../api.js';
import { clear, confirmDialog, every, field, fmtDate, h, modal, moduleToolbar, statStrip, toast, t as tr } from '../ui.js';

const PERIODS = [['AYLIK', 'Aylık'], ['3_AYLIK', '3 aylık'], ['6_AYLIK', '6 aylık'], ['YILLIK', 'Yıllık']];
const STATUS = { aktif: ['green', 'Aktif'], bitti: ['red', 'Kota bitti'], sure_doldu: ['gray', 'Süresi doldu'], baslamadi: ['blue', 'Başlamadı'], pasif: ['gray', 'Pasif'] };
// Certus 100 Aviation (Ağustos 2025) hazır paketleri: [dönem, dahil MB, paket fiyatı $, aşım $/MB]
const CERTUS = [
  ...[[100, 518, 5.18], [200, 991, 4.96], [400, 1900, 4.75], [600, 2758, 4.60], [800, 3563, 4.45], [1000, 4318, 4.32], [1250, 5239, 4.19], [1500, 6107, 4.07], [2500, 9896, 3.96]].map(x => ['AYLIK', ...x]),
  ...[[250, 1328, 5.31], [500, 2540, 5.08], [1250, 6086, 4.87], [1875, 8834, 4.71], [2500, 11411, 4.56], [3000, 13278, 4.43], [3750, 16110, 4.30], [5000, 20866, 4.17], [7500, 30430, 4.06]].map(x => ['3_AYLIK', ...x]),
  ...[[500, 2720, 5.44], [1000, 5204, 5.20], [2500, 12469, 4.99], [3750, 18100, 4.83], [5000, 23379, 4.68], [6000, 27205, 4.53], [7500, 33006, 4.40], [10000, 42750, 4.28], [15000, 62344, 4.16]].map(x => ['6_AYLIK', ...x]),
  ...[[1000, 5700, 5.70], [2000, 10904, 5.45], [5000, 26125, 5.23], [7500, 37923, 5.06], [10000, 48984, 4.90], [12000, 57000, 4.75], [15000, 69154, 4.61], [20000, 89571, 4.48], [30000, 130625, 4.35]].map(x => ['YILLIK', ...x]),
];
const PERIOD_TEXT = Object.fromEntries(PERIODS);
// Turkcell ve Türk Telekom hazır paketleri (operatör sitelerinden, Kasım 2026; ₺, KDV + ÖİV dahil). Kota GB → MB (× 1024).
// Satır: [dahil veri, fiyat ₺, not şablonunun değişkenleri]. Taahhütlü tarifelerde fiyat taahhütlü aylık bedeldir; taahhütsüzü nota yazılır.
const GB = 1024;
const N_COMMIT = '12 ay taahhütlü fiyat; taahhütsüz {a} ₺/ay.';
const N_COMMIT_ONLY = '12 ay taahhütlü fiyat.';
const N_PREPAID = 'Faturasız paket; 30 gün geçerlidir.';
const N_STOP = 'Aşım ücreti yok; kota bitince internet durur.';
const N_TC_M2M = '24 ay kampanyalı fiyat; liste fiyatı {a} ₺/ay. Aşım kademeli ücretlenir (MB başına değil).';
const N_TT_M2M = '12 ay taahhütlü fiyat; taahhütsüz {a} ₺, 24 ay taahhütlü {b} ₺. M2M tarife ücretine ektir.';
const N_TC_YEAR = 'Yıllık paket; 365 gün geçerlidir, {a} ₺ × 12 taksit. Ses hattı paketidir.';
const N_TT_YEAR = 'Yıllık paket; 360 gün geçerlidir. Faturasız ses hattı paketidir (20.000 dk + 20.000 SMS dahil).';
// notes: not şablonları; {a} / {b} satırın 3. ve 4. değeridir (taahhütsüz / liste fiyatı vb.).
const rows = (per, title, list, notes, over = null) => list.map(([q, price, a, b]) => ({ per, mb: q, price, cur: 'TRY', over, name: title, note: notes.map(n => [n, { a, b }]) }));
const OPERATORS = [
  { provider: 'Turkcell', groups: [
    ['Mobil Wifi · faturalı (aylık kota, 12 ay taahhüt)', [
      ...rows('AYLIK', 'Turkcell Mobil Wifi', [[20 * GB, 415, 715], [100 * GB, 635, 935], [200 * GB, 815, 1115]], [N_COMMIT]),
      ...rows('AYLIK', 'Turkcell Mobil Wifi', [[50 * GB, 535], [400 * GB, 1400], [600 * GB, 1800]], [N_COMMIT_ONLY]),
    ].sort((x, y) => x.mb - y.mb)],
    ['Mobil Wifi · faturasız (30 gün)', rows('AYLIK', 'Turkcell Faturasız Mobil Wifi', [[50 * GB, 550], [200 * GB, 850], [400 * GB, 1200]], [N_PREPAID])],
    ['M2M-IoT · kurumsal (aylık kota, 24 ay kampanya)', rows('AYLIK', 'Turkcell M2M', [[100, 84, 99], [1 * GB, 169, 219], [2 * GB, 179, 229], [5 * GB, 259, 329], [8 * GB, 379, 499],
      [15 * GB, 529, 799], [25 * GB, 649, 999], [50 * GB, 999, 1599], [150 * GB, 2299, 3599], [250 * GB, 2899, 4599], [500 * GB, 4999, 8199]], [N_TC_M2M])],
    ['Yıllık Dev Paketler (365 gün)', [['Dev Star', 120, 600], ['Dev Star', 240, 800], ['Dev Platinum Star', 480, 1100]].flatMap(([t, q, m]) =>
      rows('YILLIK', `Turkcell Yıllık ${t}`, [[q * GB, m * 12, m]], [N_TC_YEAR]))],
  ] },
  { provider: 'Türk Telekom', groups: [
    ['Cep Magnet · faturalı (aylık kota, 12 ay taahhüt)', [
      ...rows('AYLIK', 'Türk Telekom Cep Magnet', [[50 * GB, 460, 780], [100 * GB, 625, 1050]], [N_COMMIT, N_STOP]),
      ...rows('AYLIK', 'Türk Telekom Cep Magnet', [[200 * GB, 810], [300 * GB, 1110]], [N_COMMIT_ONLY, N_STOP]),
    ]],
    ['Mobil Wi-Fi · faturasız (30 gün)', rows('AYLIK', 'Türk Telekom Faturasız Mobil Wi-Fi', [[20 * GB, 300], [100 * GB, 560], [200 * GB, 720], [300 * GB, 975]], [N_PREPAID])],
    ['M2M Data · kurumsal (aylık kota, 12 ay taahhüt)', rows('AYLIK', 'Türk Telekom M2M', [[500, 12.42, 15.53, 9.32], [1 * GB, 14.50, 25.89, 11.39], [2 * GB, 19.67, 31.07, 15.53],
      [5 * GB, 30.03, 41.43, 25.89], [10 * GB, 40.39, 51.79, 36.25], [20 * GB, 61.11, 72.51, 56.97], [30 * GB, 81.82, 93.22, 77.68], [50 * GB, 102.55, 113.94, 98.40],
      [100 * GB, 206.13, 227.88, 191.63]], [N_TT_M2M], 0.051)],
    ['Yıllık (360 gün)', rows('YILLIK', 'Türk Telekom Geniş 12 Ay', [[100 * GB, 3300]], [N_TT_YEAR])],
  ] },
];
const SYMBOL = { USD: '$', TRY: '₺', EUR: '€' };
const size = q => (q >= GB && q % GB === 0 ? `${(q / GB).toLocaleString('tr')} GB` : `${q.toLocaleString('tr')} MB`);
const mb = v => (v == null ? '—' : v >= 100 ? Math.round(v).toLocaleString('tr') : Number(v).toLocaleString('tr', { maximumFractionDigits: 2 }));
const money = (v, cur = 'USD', digits = 2) => (v == null ? '—' : `${Number(v).toLocaleString('tr', { minimumFractionDigits: Number.isInteger(Number(v)) ? 0 : 2, maximumFractionDigits: digits })} ${SYMBOL[cur] || cur || '$'}`);
// Aşım maliyeti para birimine göre ayrı toplanır (dolar tarifesi ile ₺ tarifesi aynı toplamda birleşmez).
const overTotal = live => {
  const by = {};
  for (const p of live) if (p.over_cost) by[p.currency || 'USD'] = (by[p.currency || 'USD'] || 0) + p.over_cost;
  const curs = [...new Set(live.map(p => p.currency || 'USD'))];
  return Object.keys(by).length ? Object.entries(by).map(([c, v]) => money(v, c)).join(' + ') : curs.length === 1 ? money(0, curs[0]) : '0';
};
const inp = (value, attrs = {}) => h('input', { class: 'input', value: value ?? '', ...attrs });
const numOrNull = v => (v === '' || v == null || Number.isNaN(Number(v)) ? null : Number(v));
const bar = (pct, over) => h('div', { style: { height: '10px', borderRadius: '6px', background: 'var(--surface-2, #eef1f6)', overflow: 'hidden', margin: '8px 0 4px' } },
  h('div', { style: { width: `${Math.min(100, pct || 0)}%`, height: '100%', background: over || pct >= 100 ? 'var(--danger, #dc2626)' : pct >= 80 ? 'var(--warning, #d97706)' : 'var(--ok, #16a34a)' } }));
export const statusBadge = p => { const [c, l] = STATUS[p.status] || ['gray', p.status]; return h('span', { class: `badge ${c}` }, tr(l)); };

export async function render(view, ctx, m, head) {
  const stats = statStrip();
  const body = h('div');
  let data = { items: [], can_write: false };
  const draw = () => {
    const items = data.items;
    const live = items.filter(p => p.status === 'aktif' || p.status === 'bitti');
    stats.set([
      { icon: 'documents', label: 'Etkin paket', value: live.length },
      { icon: 'calendar', label: 'Bu dönem harcanan', value: `${mb(live.reduce((s, p) => s + p.used_mb, 0))} MB` },
      { icon: 'note', label: 'Kalan', value: `${mb(live.reduce((s, p) => s + p.remaining_mb, 0))} MB`, tone: 'ok' },
      { icon: 'warning', label: 'Aşım maliyeti', value: overTotal(live), tone: live.some(p => p.over_mb > 0) ? 'alert' : 'muted' },
    ]);
    clear(body, items.length ? h('div', { class: 'grid-cards', style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '14px' } },
      items.map(p => h('div', { class: 'card', style: { padding: '16px', opacity: p.active ? 1 : 0.6 } },
        h('div', { style: { display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'start' } },
          h('div', null, h('b', null, p.name), h('div', { class: 'small muted' }, [p.provider, tr(p.period_text), p.sim_count ? tr('{n} SIM', { n: p.sim_count }) : null].filter(Boolean).join(' · '))),
          statusBadge(p)),
        bar(p.pct, p.over_mb > 0),
        h('div', { style: { display: 'flex', justifyContent: 'space-between' } },
          h('span', null, h('b', null, `${mb(p.remaining_mb)} MB`), h('span', { class: 'muted' }, ` ${tr('kaldı')}`)),
          h('span', { class: 'small muted' }, tr('{u} / {q} MB · %{p}', { u: mb(p.used_mb), q: mb(p.quota_mb), p: p.pct ?? 0 }))),
        p.over_mb > 0 ? h('div', { class: 'small', style: { color: 'var(--danger, #dc2626)', marginTop: '4px' } },
          tr('Aşım {o} MB · ~{c}', { o: mb(p.over_mb), c: money(p.over_cost, p.currency) })) : null,
        h('div', { class: 'small muted', style: { marginTop: '6px' } },
          tr('Dönem {a} – {b} · {d} gün kaldı', { a: fmtDate(p.period_start), b: fmtDate(p.period_end), d: p.days_left }),
          p.auto_renew ? ` · ${tr('otomatik yenilenir')}` : ''),
        p.price != null ? h('div', { class: 'small muted' }, tr('Paket {p} · aşım {o}/MB', { p: money(p.price, p.currency), o: p.overage_per_mb != null ? money(p.overage_per_mb, p.currency, 4) : '—' })) : null,
        h('div', { class: 'pill-group', style: { marginTop: '10px' } },
          h('button', { class: 'btn sm primary', onclick: () => detailModal(p.id) }, 'Tüketim'),
          data.can_write ? h('button', { class: 'btn sm', onclick: () => packageForm(p, load) }, 'Düzenle') : null,
          data.can_write ? h('button', { class: 'btn sm danger', onclick: async () => {
            if (!await confirmDialog('Paketi sil', tr('{name} silinsin mi? Tüketim kaydı olan paket silinemez; pasife alabilirsiniz.', { name: p.name }), { okLabel: 'Sil', danger: true })) return;
            await api.del(`/api/drone/packages/${p.id}`); toast('Paket silindi'); load();
          } }, 'Sil') : null))))
      : h('div', { class: 'card empty' }, 'Henüz veri paketi yok. Uydu modeminin tarifesini (ör. Certus aylık 100 MB) ekleyin; ardından Görev › Uçuş › Bağlantı\'da uçuşu bu pakete bağlayın.'));
  };
  const load = async () => { data = await api.get('/api/drone/packages'); draw(); };
  data = await api.get('/api/drone/packages');
  clear(view, head('Veri Paketleri · uydu hattı veri paketleri ve kalan kota'), stats,
    moduleToolbar(data.can_write ? h('button', { class: 'btn primary', onclick: () => packageForm(null, load) }, '＋ Yeni Paket') : null), body);
  draw();
  every(30000, () => load().catch(() => {}));
}

export function packageForm(p, done) {
  // Hazır paket: önce tarife (Certus / Turkcell / Türk Telekom), sonra o tarifenin paketi. Seçenek değeri TARIFFS[t].items dizinidir.
  const TARIFFS = [
    { provider: 'Certus 100 Aviation', groups: PERIODS.map(([k, l]) => [l, CERTUS.filter(x => x[0] === k).map(([per, q, price, over]) => ({ per, mb: q, price, cur: 'USD', over,
      label: tr('{q} MB · {p} $ · aşım {o} $/MB', { q: q.toLocaleString('tr'), p: price.toLocaleString('tr'), o: over }) }))]) },
    ...OPERATORS,
  ].map(x => ({ ...x, items: x.groups.flatMap(g => g[1]) }));
  const tariff = h('select', { class: 'input', style: { maxWidth: '220px' } }, TARIFFS.map((x, i) => h('option', { value: i }, x.provider)));
  const preset = h('select', { class: 'input', style: { width: '100%' } });
  const optionText = it => it.label || (it.over != null ? tr('{q} · {p} · aşım {o}/MB', { q: size(it.mb), p: money(it.price, it.cur), o: money(it.over, it.cur, 4) }) : `${size(it.mb)} · ${money(it.price, it.cur)}`);
  const fillPresets = () => {
    const tf = TARIFFS[tariff.value];
    clear(preset, h('option', { value: '' }, '— Paket seçin —'),
      tf.groups.map(([l, list]) => h('optgroup', { label: tr(l) }, list.map(it => h('option', { value: tf.items.indexOf(it) }, optionText(it))))));
  };
  fillPresets();
  tariff.addEventListener('change', fillPresets);
  const name = inp(p?.name);
  const provider = inp(p?.provider ?? 'Certus 100 Aviation');
  const period = h('select', { class: 'input' }, PERIODS.map(([k, l]) => h('option', { value: k, selected: k === (p?.period || 'AYLIK') }, l)));
  const quota = inp(p?.quota_mb, { type: 'number', min: '1', step: 'any' });
  const price = inp(p?.price, { type: 'number', min: '0', step: 'any' });
  const currency = inp(p?.currency ?? 'USD', { maxlength: '3', style: { maxWidth: '90px' } });
  const over = inp(p?.overage_per_mb, { type: 'number', min: '0', step: 'any' });
  const start = inp(p?.start_date ?? new Date().toISOString().slice(0, 10), { type: 'date' });
  const sims = inp(p?.sim_count, { type: 'number', min: '0' });
  const note = h('textarea', { class: 'input', rows: 2 }, p?.note ?? '');
  const renew = h('input', { type: 'checkbox', checked: p ? !!p.auto_renew : true });
  const active = h('input', { type: 'checkbox', checked: p ? !!p.active : true });
  let auto = { name: '', note: '' };   // hazır paketten dolan ad / not: kullanıcı değiştirmediyse yeni seçimde yenilenir
  preset.addEventListener('change', () => {
    if (preset.value === '') return;
    const tf = TARIFFS[tariff.value], it = tf.items[preset.value];
    period.value = it.per; quota.value = it.mb; price.value = it.price; over.value = it.over ?? ''; currency.value = it.cur; provider.value = tf.provider;
    const fresh = {
      name: it.name ? `${it.name} ${size(it.mb)}` : tr('Certus {per} {q} MB', { per: tr(PERIOD_TEXT[it.per]), q: it.mb.toLocaleString('tr') }),
      note: (it.note || []).map(([n, v]) => tr(n, v && Object.fromEntries(Object.entries(v).filter(e => e[1] != null).map(([k, x]) => [k, x.toLocaleString('tr')])))).join(' '),
    };
    for (const [el, k] of [[name, 'name'], [note, 'note']]) if (!el.value.trim() || el.value === auto[k]) el.value = fresh[k];
    auto = fresh;
  });
  modal({
    title: p ? tr('{name} · veri paketi', { name: p.name }) : 'Yeni Veri Paketi',
    wide: true,
    body: h('div', null,
      p ? null : field('Hazır paket', h('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap' } }, tariff, h('div', { style: { flex: '1 1 260px' } }, preset)),
        'Tarifeyi ve paketi seçin; alanlar dolar, isterseniz düzenleyin. Turkcell ve Türk Telekom fiyatları Kasım 2026 tarihlidir (KDV + ÖİV dahil); güncelini operatörden doğrulayın.'),
      h('div', { class: 'row' }, field('Paket adı', name), field('Sağlayıcı', provider)),
      h('div', { class: 'row' }, field('Dönem', period), field('Dahil veri (MB)', quota, 'SIM\'ler arasında ortak kullanılır.')),
      h('div', { class: 'row' }, field('Paket fiyatı', price), field('Para birimi', currency), field('Aşım ücreti (MB başına)', over)),
      h('div', { class: 'row' }, field('Başlangıç tarihi', start, 'Dönem bu tarihten itibaren hesaplanır.'), field('SIM sayısı', sims)),
      field('Not', note),
      h('label', { class: 'check' }, renew, 'Otomatik yenilenir (dönem bitince yeni dönem başlar, kota sıfırlanır)'),
      h('label', { class: 'check' }, active, 'Etkin (uçuşlar bu pakete bağlanabilir)')),
    actions: [{ label: 'Vazgeç' }, {
      label: p ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const body = { name: name.value.trim(), provider: provider.value.trim() || null, period: period.value, quota_mb: numOrNull(quota.value),
          price: numOrNull(price.value), currency: currency.value.trim() || 'USD', overage_per_mb: numOrNull(over.value), start_date: start.value,
          auto_renew: renew.checked, sim_count: numOrNull(sims.value), note: note.value.trim() || null, active: active.checked };
        if (!body.name) throw new Error(tr('Paket adı gerekli'));
        if (!body.quota_mb) throw new Error(tr('Dahil veri (MB) gerekli'));
        if (p) { await api.put(`/api/drone/packages/${p.id}`, body); toast('Paket güncellendi'); } else { await api.post('/api/drone/packages', body); toast('Paket eklendi'); }
        done?.();
      },
    }],
  });
}

async function detailModal(id) {
  const p = await api.get(`/api/drone/packages/${id}`);
  const u = p.usage;
  const max = Math.max(0.001, ...u.days.map(d => d.mb));
  modal({
    title: tr('{name} · tüketim', { name: p.name }),
    wide: true,
    body: h('div', null,
      h('div', { class: 'small muted' }, tr('Dönem {a} – {b} · {u} / {q} MB · {r} MB kaldı', { a: fmtDate(u.period_start), b: fmtDate(u.period_end), u: mb(p.used_mb), q: mb(p.quota_mb), r: mb(p.remaining_mb) })),
      bar(p.pct, p.over_mb > 0),
      h('h3', { style: { margin: '14px 0 6px' } }, 'Günlük tüketim'),
      u.days.length ? h('div', null, u.days.map(d => h('div', { style: { display: 'grid', gridTemplateColumns: '90px 1fr 90px', gap: '8px', alignItems: 'center', fontSize: '13px', margin: '3px 0' } },
        h('span', { class: 'muted' }, fmtDate(d.day)),
        h('div', { style: { height: '8px', borderRadius: '4px', background: 'var(--accent, #1f6feb)', width: `${Math.max(2, 100 * d.mb / max)}%` } }),
        h('span', { class: 'num' }, `${mb(d.mb)} MB`)))) : h('div', { class: 'empty small' }, 'Bu dönemde tüketim yok'),
      h('h3', { style: { margin: '14px 0 6px' } }, 'Uçuşlar'),
      u.flights.length ? h('div', { class: 'table-wrap' }, h('table', null,
        h('thead', null, h('tr', null, ['Görev', 'Uçuş', 'Uydu hattı', 'Tüketim', 'Tarih'].map(c => h('th', null, c)))),
        h('tbody', null, u.flights.map(f => h('tr', null, h('td', null, f.task_code || '—'), h('td', null, f.label), h('td', { class: 'small' }, tr(f.line_text)),
          h('td', { class: 'num' }, `${mb(f.mb)} MB`), h('td', { class: 'small muted' }, f.first === f.last ? fmtDate(f.first) : `${fmtDate(f.first)} – ${fmtDate(f.last)}`))))))
        : h('div', { class: 'empty small' }, 'Bu döneme bağlı uçuş tüketimi yok'),
      h('p', { class: 'small muted', style: { marginTop: '12px' } }, 'Ölçüm yaklaşıktır: çerçeve başına TCP/IP ve TLS başlığı tahmini eklenir. Kesin fatura sağlayıcının portalındadır.')),
    actions: [{ label: 'Kapat' }],
  });
}
