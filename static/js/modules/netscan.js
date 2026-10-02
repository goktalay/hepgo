// Araçlar › Ağ Tarayıcı: sunucunun yerel ağındaki cihazlar (IP, bilgisayar adı, MAC, üretici, açık portlar, tür).
// Tarama sunucuda arka planda çalışır; sayfa ilerlemeyi saniyede bir okur. Yalnızca Sistem Yöneticisi.
import { api } from '../api.js';
import { clear, every, field, fmtDateTime, h, matches, modal, pageHead, pref, selectInput, setPref, statStrip, toast, toastError } from '../ui.js';

const ipKey = ip => (ip || '').split('.').map(n => n.padStart(3, '0')).join('.');
const WEB = { 80: 'http', 8080: 'http', 443: 'https', 7125: 'http' };

export async function renderNetscan(view) {
  let data = await api.get('/api/tools/network');
  const stats = statStrip();
  const info = h('div', { class: 'small muted ns-info' });
  const progress = h('div', { class: 'ns-progress', hidden: true }, h('div', { class: 'ns-phase' }), h('div', { class: 'progress' }, h('i')));
  const q = h('input', { class: 'input', type: 'search', placeholder: 'IP, ad, MAC, üretici ara…', style: { width: '240px' } });
  const kind = selectInput([], { all: 'Tüm cihaz türleri' });
  const offline = h('input', { type: 'checkbox', checked: pref('netscan.offline', '0') === '1' });
  const body = h('div');
  const scanBtn = h('button', { class: 'btn primary' }, '⟳ Ağı Tara');
  const csvBtn = h('button', { class: 'btn' }, 'CSV İndir');

  const shown = () => data.devices.filter(d => (offline.checked || d.online) && (!kind.value || d.kind === kind.value)
    && matches(q.value, d.ip, d.label, d.hostname, d.netbios, d.mdns, d.dns, d.mac, d.vendor, d.kind, d.known, d.note))
    .sort((a, b) => b.online - a.online || ipKey(a.ip).localeCompare(ipKey(b.ip)));

  const draw = () => {
    const on = data.devices.filter(d => d.online);
    const n = k => on.filter(d => d.kind === k).length;
    stats.set([
      { label: 'Çevrimiçi cihaz', value: on.length, tone: 'ok' },
      { label: 'Bilgisayar', value: n('Windows bilgisayar') + n('Bilgisayar') + n('Mac') + n('Linux / sunucu') },
      { label: 'Telefon / tablet', value: n('Telefon / tablet') },
      { label: '3B yazıcı', value: n('3B yazıcı') },
      { label: 'Kamera', value: n('Kamera') },
      { label: 'Adı bulunan', value: on.filter(d => d.label || d.hostname).length },
      { label: 'Çevrimdışı (bilinen)', value: data.devices.length - on.length, tone: 'muted' },
    ]);
    const kinds = [...new Set(data.devices.map(d => d.kind).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'tr'));
    const cur = kind.value;
    clear(kind, h('option', { value: '' }, 'Tüm cihaz türleri'), kinds.map(k => h('option', { value: k, selected: k === cur }, k)));
    const l = data.last;
    info.textContent = l ? `Son tarama ${fmtDateTime(l.at)} · ${l.networks.map(x => `${x.cidr} (${x.iface})`).join(', ')}${l.gateway ? ` · ağ geçidi ${l.gateway}` : ''} · ${l.count} IP`
      : `Henüz tarama yapılmadı · ${data.networks.map(x => x.cidr).join(', ') || 'yerel ağ bulunamadı'}`;
    const rows = shown();
    clear(body, rows.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table ns-table' },
      h('thead', null, h('tr', null, h('th', null, ''), h('th', null, 'IP'), h('th', null, 'Bilgisayar adı'), h('th', null, 'Tür'),
        h('th', null, 'MAC / Üretici'), h('th', null, 'Açık portlar'), h('th', null, 'Görülme'), h('th', null, ''))),
      h('tbody', null, rows.map(d => h('tr', { class: d.online ? '' : 'off' },
        h('td', null, h('span', { class: `ns-dot ${d.online ? 'on' : ''}`, title: d.online ? 'Çevrimiçi' : 'Son taramada yoktu' })),
        h('td', { class: 'mono' }, h('b', null, d.ip), d.is_server ? h('div', { class: 'small muted' }, 'bu sunucu') : d.is_gateway ? h('div', { class: 'small muted' }, 'ağ geçidi') : null),
        h('td', null, d.label ? h('b', null, d.label) : null, d.hostname ? h('div', { class: d.label ? 'small muted' : '' }, d.hostname) : (d.label ? null : h('span', { class: 'muted' }, '—')),
          d.known ? h('div', { class: 'small ns-known' }, d.known) : null,
          d.workgroup ? h('div', { class: 'small muted' }, `Çalışma grubu: ${d.workgroup}`) : null,
          d.note ? h('div', { class: 'small muted' }, d.note) : null),
        h('td', null, h('span', { class: 'badge gray' }, d.kind || '—')),
        h('td', null, h('div', { class: 'mono small' }, d.mac || '—'), h('div', { class: 'small muted' }, d.vendor || '')),
        h('td', null, h('div', { class: 'ns-ports' }, d.ports.map(p => WEB[p.port] && d.online
          ? h('a', { class: 'chip', href: `${WEB[p.port]}://${d.ip}${[80, 443].includes(p.port) ? '' : `:${p.port}`}/`, target: '_blank', rel: 'noopener', title: `${p.name} arayüzünü aç` }, p.name)
          : h('span', { class: 'chip', title: `Port ${p.port}` }, p.name)))),
        h('td', { class: 'small muted' }, `Son: ${fmtDateTime(d.last_seen)}`, h('div', null, `İlk: ${fmtDateTime(d.first_seen)}`)),
        h('td', { class: 'actions' },
          h('button', { class: 'btn sm', onclick: () => labelModal(d) }, 'Ad Ver'),
          d.online ? null : h('button', { class: 'btn sm ghost', onclick: () => forget(d) }, 'Sil')))))))
      : h('div', { class: 'card empty' }, data.devices.length ? 'Filtreye uyan cihaz yok' : 'Henüz tarama yapılmadı. “Ağı Tara” ile başlatın.'));
  };

  const reload = async () => { data = await api.get('/api/tools/network'); draw(); };
  const showState = st => {
    progress.hidden = !st.running;
    scanBtn.disabled = st.running;
    scanBtn.textContent = st.running ? 'Taranıyor…' : '⟳ Ağı Tara';
    if (st.running) {
      progress.querySelector('.ns-phase').textContent = `${st.phase || ''}${st.total ? ` · ${st.done}/${st.total}` : ''}`;
      progress.querySelector('i').style.width = `${st.total ? Math.round(st.done * 100 / st.total) : 8}%`;
    }
  };
  let wasRunning = data.state.running;
  every(1000, async () => {
    if (!wasRunning) return;
    try {
      const st = await api.get('/api/tools/network/state');
      showState(st);
      if (!st.running) {
        wasRunning = false;
        await reload();
        if (st.error) toastError(new Error(st.error)); else toast(`Tarama tamamlandı: ${data.devices.filter(d => d.online).length} cihaz`);
      }
    } catch { /* sayfa değişti */ }
  });
  scanBtn.addEventListener('click', async () => {
    try { showState(await api.post('/api/tools/network/scan')); wasRunning = true; } catch (err) { toastError(err); }
  });
  csvBtn.addEventListener('click', () => {
    const cols = [['ip', 'IP'], ['label', 'Verilen ad'], ['hostname', 'Bilgisayar adı'], ['kind', 'Tür'], ['mac', 'MAC'], ['vendor', 'Üretici'],
      ['ports', 'Açık portlar'], ['known', 'Sistemdeki kayıt'], ['online', 'Çevrimiçi'], ['last_seen', 'Son görülme']];
    const cell = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const lines = [cols.map(c => cell(c[1])).join(';'), ...shown().map(d => cols.map(([k]) =>
      cell(k === 'ports' ? d.ports.map(p => p.name).join(' ') : k === 'online' ? (d.online ? 'Evet' : 'Hayır') : d[k])).join(';'))];
    const a = h('a', { href: URL.createObjectURL(new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv' })), download: `ag-taramasi-${new Date().toLocaleDateString('sv')}.csv` });
    a.click();
  });

  function labelModal(d) {
    const label = h('input', { class: 'input', value: d.label || '', placeholder: 'ör. Muhasebe PC, Toplantı odası TV' });
    const note = h('input', { class: 'input', value: d.note || '' });
    modal({
      title: `${d.ip} · Ad Ver`,
      body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, `${d.hostname || 'Adı bulunamadı'} · ${d.mac || 'MAC yok'} · ${d.vendor || ''}`),
        field('Ad', label, 'Cihaz MAC adresiyle izlenir; IP değişse de ad korunur'), field('Not', note)),
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        await api.put(`/api/tools/network/${d.id}`, { label: label.value, note: note.value }); await reload();
      } }],
    });
  }
  async function forget(d) {
    try { await api.del(`/api/tools/network/${d.id}`); await reload(); } catch (err) { toastError(err); }
  }

  q.addEventListener('input', draw);
  kind.addEventListener('change', draw);
  offline.addEventListener('change', () => { setPref('netscan.offline', offline.checked ? '1' : '0'); draw(); });
  clear(view,
    pageHead('Ağ Tarayıcı', { back: '#/tools', sub: 'Sunucunun bulunduğu ağdaki bilgisayarlar ve cihazlar', right: h('div', { class: 'head-right' }, csvBtn, scanBtn) }),
    stats, info, progress,
    h('div', { class: 'filters' }, q, kind, h('label', { class: 'check' }, offline, 'Çevrimdışı olanları da göster')),
    body);
  showState(data.state);
  draw();
  if (!data.devices.length && !data.state.running) scanBtn.click();   // ilk açılışta tarama kendiliğinden başlar
}
