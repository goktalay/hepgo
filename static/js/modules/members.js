// Merkez › Üyelik Yönetimi: firmalar (onay, kurulum, kurulum linki, pasife al/aktif et, düzenle, sil), paketler, ödeme takibi.
// Kurulum kayıtları Veilox kurulum servisinde; Merkez onu iç anahtarla yönetir. "Pasife al" yumuşaktır: firma instance'ı
// ~5 dk içinde girişleri durdurur (master hariç), veri ve servis korunur; "Aktif et" ile anında geri döner.
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDate, h, matches, modal, moduleToolbar, pageHead, segmented, selectInput, statStrip, toast, toastError } from '../ui.js';
import { chartConfig, loadChart, theme } from './reports.js';

const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 0 }).format(n || 0);
const SUBS = [['firms', 'Firmalar'], ['packages', 'Paketler'], ['payments', 'Ödemeler']];
const VX_STATUS = { pending: ['yellow', 'Onay bekliyor'], approved: ['blue', 'Onaylandı'], provisioning: ['blue', 'Kuruluyor'],
  active: ['green', 'Yayında'], suspended: ['', 'Servis kaldırıldı'], offline: ['', 'Offline'], error: ['red', 'Hata'] };
const PAY = { odendi: ['green', 'Ödendi'], kismi: ['yellow', 'Kısmi'], bekliyor: ['', 'Bekliyor'], gecikti: ['red', 'Gecikti'], ucretsiz: ['', 'Ücretsiz'] };
const b = (map, k) => { const [c, l] = map[k] || ['', k]; return h('span', { class: `badge ${c}` }, l); };

export async function render(view, params) {
  const sub = SUBS.some(s => s[0] === params[0]) ? params[0] : 'firms';
  const nav = segmented(SUBS, sub, v => { location.hash = `#/members/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Üyelik Yönetimi', { back: '#/', sub: 'Firmalar, paketler ve ödeme takibi', tabs: nav }), body);
  if (sub === 'packages') return packagesView(body);
  if (sub === 'payments') return paymentsView(body);
  return firmsView(body);
}

// ---------------- Firmalar ----------------
async function firmsView(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  const strip = statStrip();
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Firma, e-posta ara…', style: { maxWidth: '240px' } });
  const st = h('select', { class: 'input' }, h('option', { value: '' }, 'Tüm firmalar'), h('option', { value: 'active' }, 'Yayında'),
    h('option', { value: 'passive' }, 'Pasif (askıda)'), h('option', { value: 'pending' }, 'Onay / kurulum bekleyen'), h('option', { value: 'late' }, 'Ödemesi geciken'));
  const out = h('div');
  const load = async () => {
    try { d = await api.get('/api/central/members'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
    draw();
  };
  const draw = () => {
    const M = d.members;
    strip.set([{ label: 'Firma', value: M.length }, { label: 'Yayında', value: M.filter(m => m.status === 'active' && !m.suspended).length, tone: 'ok' },
      { label: 'Pasif', value: M.filter(m => m.suspended).length, tone: M.some(m => m.suspended) ? 'alert' : '' },
      { label: 'Onay/kurulum bekleyen', value: M.filter(m => ['pending', 'approved'].includes(m.status)).length },
      { label: `Bu ay tahsilat (${d.period})`, value: money(M.reduce((s, m) => s + (m.paid_this_month || 0), 0)), sub: `beklenen ${money(M.reduce((s, m) => s + (m.fee || 0), 0))}` }]);
    const rows = M.filter(m => matches(q.value, m.name, m.master_username, m.slug, m.url))
      .filter(m => !st.value || (st.value === 'active' && m.status === 'active' && !m.suspended) || (st.value === 'passive' && m.suspended)
        || (st.value === 'pending' && ['pending', 'approved'].includes(m.status)) || (st.value === 'late' && m.pay_status === 'gecikti'));
    clear(out, rows.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Firma', 'Paket', 'Aylık', 'Bu ay', 'Talep', 'Durum', ''].map(x => h('th', null, x)))),
      h('tbody', null, rows.map(m => h('tr', { class: m.suspended ? 'mb-passive' : '' },
        h('td', null, h('b', null, m.name), h('div', { class: 'small muted' }, m.master_username),
          m.url ? h('a', { class: 'small', href: m.url, target: '_blank', rel: 'noopener' }, m.url.replace(/^https?:\/\//, '')) : null),
        h('td', null, m.package_name || '—', h('div', { class: 'small muted' }, m.mode === 'offline' ? 'Offline' : 'Online')),
        h('td', { class: 'num' }, m.fee ? money(m.fee) : '—'),
        h('td', null, b(PAY, m.pay_status)),
        h('td', { class: 'num' }, m.open_tickets ? h('a', { href: `#/tickets` }, String(m.open_tickets)) : '—'),
        h('td', null, b(VX_STATUS, m.status), m.suspended ? h('div', null, h('span', { class: 'badge red', title: m.suspend_reason }, 'Pasif')) : null),
        h('td', { class: 'num' }, h('div', { class: 'pill-group' }, ...actions(m, load))))))))) : h('div', { class: 'card empty' }, 'Firma yok.'));
  };
  q.addEventListener('input', () => d && draw()); st.addEventListener('change', () => d && draw());
  const newBtn = h('button', { class: 'btn primary', type: 'button', onclick: async () => editFirm(null, (await api.get('/api/central/packages')), load) }, '＋ Yeni Firma');
  clear(view, strip, moduleToolbar(newBtn), h('div', { class: 'filters' }, q, st), out);
  await load();
}

function actions(m, reload) {
  const act = async (action, label) => {
    try {
      const r = await api.post(`/api/central/members/${m.id}/${action}`, {});
      if (action === 'download-link') {
        const url = r.full_url || r.url;
        modal({ title: 'Kurulum linki (7 gün geçerli)', body: h('div', null, h('p', { class: 'small muted' }, 'Bu linki firma yöneticisine gönderin.'),
          h('input', { class: 'input', value: url, readonly: true, onclick: e => e.target.select() })),
          actions: [{ label: 'Kopyala', class: 'primary', onClick: () => { navigator.clipboard?.writeText(url); toast('Kopyalandı'); } }] });
      } else toast(label);
      reload();
    } catch (e) { toastError(e); }
  };
  const btns = [];
  if (m.status === 'pending') btns.push(h('button', { class: 'btn sm', type: 'button', onclick: () => act('approve', 'Onaylandı') }, 'Onayla'));
  if (m.status === 'approved' && m.mode !== 'offline') btns.push(h('button', { class: 'btn sm primary', type: 'button', onclick: async () => {
    if (await confirmDialog('Kurulum', `${m.name} için sunucu kurulumu başlatılsın mı? (birkaç dakika sürebilir)`, { okLabel: 'Kur' })) act('provision', 'Kurulum tamamlandı');
  } }, 'Kur'));
  btns.push(h('button', { class: 'btn sm', type: 'button', onclick: () => act('download-link') }, 'Kurulum linki'));
  btns.push(m.suspended
    ? h('button', { class: 'btn sm', type: 'button', onclick: () => setFlag(m, false, '', reload) }, 'Aktif et')
    : h('button', { class: 'btn sm', type: 'button', onclick: () => passiveModal(m, reload) }, 'Pasife al'));
  btns.push(h('button', { class: 'btn sm', type: 'button', onclick: async () => editFirm(m, (await api.get('/api/central/packages')), reload) }, 'Düzenle'));
  btns.push(h('button', { class: 'btn sm danger', type: 'button', onclick: () => deleteModal(m, reload) }, 'Sil'));
  return btns;
}

async function setFlag(m, suspended, reason, reload) {
  try { await api.put(`/api/central/members/flags/${m.slug}`, { suspended, reason }); toast(suspended ? 'Firma pasife alındı (≈5 dk içinde uygulanır)' : 'Firma aktif edildi'); reload(); }
  catch (e) { toastError(e); }
}

function passiveModal(m, reload) {
  const reason = h('input', { class: 'input', placeholder: 'Ör. Ödeme gecikmesi' });
  modal({ title: `${m.name} · Pasife al`, body: h('div', null,
    h('p', { class: 'small muted' }, 'Firma kullanıcılarının girişleri durdurulur (firma master’ı hariç; “Üyeliğim” ekranından ödeme yapabilsin diye). Veri ve sunucu korunur; “Aktif et” ile anında geri alınır.'),
    field('Gerekçe (kullanıcılara gösterilir)', reason)),
    actions: [{ label: 'Vazgeç' }, { label: 'Pasife al', class: 'danger', onClick: () => setFlag(m, true, reason.value.trim(), reload) }] });
}

function deleteModal(m, reload) {
  const inp = h('input', { class: 'input', placeholder: m.name });
  modal({ title: 'Firma kaydını sil', body: h('div', null,
    h('p', null, 'Bu işlem merkezdeki firma kaydını siler. Onay için firma adını aynen yazın:'), h('p', null, h('b', null, m.name)), inp),
    actions: [{ label: 'Vazgeç' }, { label: 'Kalıcı olarak sil', class: 'danger', onClick: async () => {
      await api.del(`/api/central/members/${m.id}?confirm=${encodeURIComponent(inp.value)}`); toast('Silindi'); reload();
    } }] });
}

function editFirm(m, pk, reload) {
  const name = h('input', { class: 'input', value: m?.name || '' });
  const mu = h('input', { class: 'input', type: 'email', value: m?.master_username || '', placeholder: 'master@firma.com' });
  const mn = h('input', { class: 'input', value: m?.master_name || '' });
  const url = h('input', { class: 'input', value: m?.url || '', placeholder: 'https://firma.app' });
  const phone = h('input', { class: 'input', value: m?.phone || '', placeholder: '05xx xxx xx xx (SMS için)' });
  const note = h('input', { class: 'input', value: m?.note || '' });
  const pkgSel = selectInput(pk.packages.map(p => [p.slug, `${p.name} · ${money(p.monthly_fee)}`]), { all: '— Paket seçin —' });
  const mode = h('select', { class: 'input' }, h('option', { value: 'online', selected: m?.mode !== 'offline' }, 'Online (bulut)'), h('option', { value: 'offline', selected: m?.mode === 'offline' }, 'Offline (kendi sunucusu)'));
  const sel = new Set(m?.modules || []);
  const mods = h('div', { class: 'mb-mods' }, pk.modules.map(x => {
    const cb = h('input', { type: 'checkbox', checked: sel.has(x.key), onchange: e => e.target.checked ? sel.add(x.key) : sel.delete(x.key) });
    return h('label', { class: 'mb-mod' }, cb, x.title);
  }));
  modal({ title: m ? `${m.name} · Düzenle` : 'Yeni firma', wide: true,
    body: h('div', null, h('div', { class: 'row' }, field('Firma adı', name), field('Web adresi', url)),
      h('div', { class: 'row' }, field('Master e-posta', mu), field('Master ad soyad', mn)),
      h('div', { class: 'row' }, m ? null : field('Paket', pkgSel), field('Kurulum', mode)),
      h('div', { class: 'row' }, field('İletişim telefonu', phone), field('Not', note)),
      h('div', { class: 'field' }, h('span', null, m ? 'Modüller' : 'Modüller (boşsa paketten)'), mods)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      if (!name.value.trim() || !mu.value.includes('@')) throw new Error('Firma adı ve geçerli master e-postası gerekli');
      const payload = { name: name.value.trim(), master_username: mu.value.trim(), master_name: mn.value.trim(), url: url.value.trim(),
        mode: mode.value, modules: [...sel], note: note.value, package_slug: m ? '' : pkgSel.value };
      const r = m ? await api.put(`/api/central/members/${m.id}`, payload) : await api.post('/api/central/members', payload);
      const slug = r.slug || m?.slug;
      if (slug && phone.value !== (m?.phone || '')) await api.put(`/api/central/members/flags/${slug}`, { phone: phone.value.trim() });
      toast('Kaydedildi'); reload();
    } }] });
}

// ---------------- Paketler ----------------
async function packagesView(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let pk;
  const load = async () => {
    try { pk = await api.get('/api/central/packages'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
    const title = Object.fromEntries(pk.modules.map(x => [x.key, x.title]));
    clear(view, moduleToolbar(h('button', { class: 'btn primary', type: 'button', onclick: () => editPkg(null, pk, load) }, '＋ Yeni Paket')),
      h('div', { class: 'mb-pkgs' }, pk.packages.map(p => h('div', { class: 'card mb-pkg' },
        h('div', { class: 'mb-pkg-top' }, h('h3', null, p.name), p.visible ? h('span', { class: 'badge green' }, 'Tanıtımda') : h('span', { class: 'badge' }, 'Gizli')),
        h('div', { class: 'mb-pkg-fee' }, money(p.monthly_fee), h('small', null, ' /ay')),
        h('div', { class: 'small muted' }, { online: 'Bulut', offline: 'Kendi sunucusu', both: 'Bulut / kendi sunucusu' }[p.mode] || p.mode, p.white_label ? ' · Beyaz etiket' : ''),
        p.description ? h('p', { class: 'small' }, p.description) : null,
        h('div', { class: 'mb-chips' }, (p.modules || []).map(k => h('span', { class: 'mb-chip' }, title[k] || k))),
        h('div', { class: 'pill-group', style: { marginTop: '10px' } },
          h('button', { class: 'btn sm', type: 'button', onclick: () => editPkg(p, pk, load) }, 'Düzenle'),
          h('button', { class: 'btn sm danger', type: 'button', onclick: async () => {
            if (!await confirmDialog('Paketi sil', `${p.name} silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
            try { await api.del(`/api/central/packages/${p.id}`); load(); } catch (e) { toastError(e); }
          } }, 'Sil'))))));
  };
  await load();
}

function editPkg(p, pk, reload) {
  const name = h('input', { class: 'input', value: p?.name || '' });
  const fee = h('input', { class: 'input', type: 'number', value: p?.monthly_fee ?? 0 });
  const desc = h('textarea', { class: 'input', rows: 2 }, p?.description || '');
  const mode = h('select', { class: 'input' }, [['online', 'Bulut'], ['offline', 'Kendi sunucusu'], ['both', 'İkisi de']].map(([v, l]) => h('option', { value: v, selected: (p?.mode || 'online') === v }, l)));
  const vis = h('input', { type: 'checkbox', checked: p ? !!p.visible : true });
  const wl = h('input', { type: 'checkbox', checked: !!p?.white_label });
  const sel = new Set(p?.modules || []);
  const mods = h('div', { class: 'mb-mods' }, pk.modules.map(x => h('label', { class: 'mb-mod' },
    h('input', { type: 'checkbox', checked: sel.has(x.key), onchange: e => e.target.checked ? sel.add(x.key) : sel.delete(x.key) }), x.title)));
  modal({ title: p ? `${p.name} · Düzenle` : 'Yeni paket', wide: true,
    body: h('div', null, h('div', { class: 'row' }, field('Paket adı', name), field('Aylık ücret (₺)', fee), field('Kurulum', mode)),
      field('Açıklama', desc),
      h('label', { class: 'set-toggle' }, vis, h('span', null, h('b', null, 'Tanıtım sayfasında göster'))),
      h('label', { class: 'set-toggle' }, wl, h('span', null, h('b', null, 'Beyaz etiket'), h('small', null, 'Firma kendi markasıyla kullanır'))),
      h('div', { class: 'field' }, h('span', null, 'Modüller'), mods)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      if (!name.value.trim()) throw new Error('Paket adı gerekli');
      const payload = { name: name.value.trim(), description: desc.value, monthly_fee: Number(fee.value) || 0, mode: mode.value,
        modules: [...sel], visible: vis.checked, white_label: wl.checked, sort: p?.sort || 0 };
      if (p) await api.put(`/api/central/packages/${p.id}`, payload); else await api.post('/api/central/packages', payload);
      toast('Kaydedildi'); reload();
    } }] });
}

// ---------------- Ödemeler ----------------
async function paymentsView(view) {
  const per = h('input', { class: 'input', type: 'month', value: new Date().toISOString().slice(0, 7), style: { maxWidth: '170px' } });
  const strip = statStrip();
  const out = h('div');
  const canvas = h('canvas');
  const chartCard = h('section', { class: 'card card-pad' }, h('h3', null, 'Son 12 ay tahsilat'), h('div', { class: 'db-chart', style: { height: '220px' } }, canvas));
  let chart = null;
  const load = async () => {
    let d;
    try { d = await api.get(`/api/central/payments?period=${per.value}`); } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    const late = d.rows.filter(r => r.pay_status === 'gecikti').length;
    strip.set([{ label: 'Beklenen', value: money(d.total_fee) }, { label: 'Tahsil edilen', value: money(d.total_paid), tone: 'ok' },
      { label: 'Kalan', value: money(Math.max(0, d.total_fee - d.total_paid)), tone: d.total_fee > d.total_paid ? 'alert' : '' },
      { label: 'Geciken firma', value: late, tone: late ? 'alert' : '' }]);
    clear(out, h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Firma', 'Aylık ücret', 'Ödenen', 'Durum', 'Ödemeler', ''].map(x => h('th', null, x)))),
      h('tbody', null, d.rows.map(r => h('tr', null,
        h('td', null, h('b', null, r.name)), h('td', { class: 'num' }, r.fee ? money(r.fee) : '—'), h('td', { class: 'num' }, money(r.paid)),
        h('td', null, b(PAY, r.pay_status)),
        h('td', null, r.payments.length ? r.payments.map(p => h('div', { class: 'small' }, `${fmtDate(p.paid_at)} · ${money(p.amount)} · ${p.method || ''} `,
          h('button', { class: 'btn xs ghost', type: 'button', title: 'Sil', onclick: async () => {
            if (!await confirmDialog('Ödemeyi sil', 'Bu ödeme kaydı silinsin mi?', { okLabel: 'Sil', danger: true })) return;
            await api.del(`/api/central/payments/${p.id}`); load();
          } }, '×'))) : h('span', { class: 'muted small' }, '—')),
        h('td', { class: 'num' }, r.fee ? h('button', { class: 'btn sm primary', type: 'button', onclick: () => payModal(r, per.value, load) }, 'Ödeme al') : null))))))));
    loadChart().then(Chart => {
      chart?.destroy();
      chart = new Chart(canvas, chartConfig({ type: 'bar', labels: d.history.map(x => x.period), datasets: [{ label: 'Tahsilat', data: d.history.map(x => x.total) }] }, theme(), true));
    }).catch(() => {});
  };
  per.addEventListener('change', load);
  clear(view, strip, h('div', { class: 'filters' }, h('label', { class: 'small muted' }, 'Dönem '), per), out, chartCard);
  await load();
}

function payModal(r, period, reload) {
  const amount = h('input', { class: 'input', type: 'number', step: '0.01', value: Math.max(0, r.fee - r.paid) || r.fee });
  const method = h('select', { class: 'input' }, [['havale', 'Havale / EFT'], ['kart', 'Kredi kartı'], ['nakit', 'Nakit']].map(([v, l]) => h('option', { value: v }, l)));
  const date = h('input', { class: 'input', type: 'date', value: new Date().toISOString().slice(0, 10) });
  const note = h('input', { class: 'input', placeholder: 'Dekont no / not' });
  modal({ title: `${r.name} · ${period} ödemesi`, body: h('div', null, field('Tutar (₺)', amount), field('Yöntem', method), field('Tarih', date), field('Not', note)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      await api.post('/api/central/payments', { slug: r.slug, period, amount: Number(amount.value), method: method.value, paid_at: date.value, note: note.value });
      toast('Ödeme kaydedildi'); reload();
    } }] });
}
