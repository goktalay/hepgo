// Yönetim (yalnızca Sistem Yöneticisi): "Sistem Durumu" (sunucu, servisler, veritabanı, yedek, güvenlik, aktivite) ve
// "Canlı Üretim" (yazıcı ve uçak durumu, 5 sn'de bir yenilenir).
import { api } from '../api.js';
import { chartConfig, heatEl, loadChart, theme } from './reports.js';
import { loadPlane, renderPlane } from '../plane.js';
import { PRINTER_STATES } from '../status.js';
import { avatar, clear, every, fmtDateTime, fmtDuration, h, matches, onLeave, pageHead, segmented, selectInput } from '../ui.js';

const REFRESH_MS = 5000;

// Seçilebilir özet rakamlar: [anahtar, başlık, alt bilgi, düzey(s) → 'alert' | 'danger' | '']
const TILES = [
  ['online_users', 'Çevrimiçi personel'],
  ['printers_printing', 'Yazdıran yazıcı', s => `${s.printers_total} yazıcıdan`],
  ['printers_really_idle', 'Gerçekten boştaki yazıcı', () => 'yazdırmıyor, sistemde işi yok'],
  ['printers_stale', 'Boşta ama sistemde üretimde',
    s => (s.printers_stale ? s.stale_printers.slice(0, 3).map(p => p.name).join(', ') + (s.printers_stale > 3 ? '…' : '')
      : 'yazıcı durumu ile sistem uyumlu'),
    s => (s.printers_stale > 0 ? 'danger' : '')],
  ['printers_total', 'Toplam yazıcı'],
  ['printers_offline', 'Çevrimdışı yazıcı'],
  ['printers_problem', 'Sorunlu yazıcı', () => 'hata / duraklatıldı', s => (s.printers_problem > 0 ? 'alert' : '')],
  ['printing_outside', 'Sistemde boş ama yazıcıda baskı var',
    s => (s.printing_outside ? s.outside_printers.slice(0, 3).map(p => p.name).join(', ') + (s.printing_outside > 3 ? '…' : '')
      : 'yazıcı durumu ile sistem uyumlu'),
    s => (s.printing_outside > 0 ? 'alert' : '')],
  ['parts_printing', 'Yazıcıdaki parça'],
  ['parts_error', 'Hatalı parça', null, s => (s.parts_error > 0 ? 'alert' : '')],
  ['parts_pending_approval', 'Depo onayı bekleyen'],
  ['orders_open', 'Açık sipariş'],
  ['today_done', 'Bugün biten baskı'],
  ['today_errors', 'Bugün hata', null, s => (s.today_errors > 0 ? 'alert' : '')],
  ['aircraft_ready', 'Depodaki uçak', () => 'sahaya çıkmamış'],
  ['field_active', 'Sahada görevdeki uçak'],
];
const DEFAULT_TILES = ['online_users', 'printers_printing', 'printers_really_idle', 'printers_stale', 'printing_outside', 'parts_printing',
  'orders_open', 'today_done', 'parts_error', 'parts_pending_approval', 'printers_offline'];
const PREF = 'adminTiles';

const nav = cur => segmented([['', 'Sistem Durumu'], ['live', 'Canlı Üretim']], cur, k => { location.hash = k ? `#/admin/${k}` : '#/admin'; }, { tabs: true });

export async function render(view, params, ctx) {
  if (params[0] === 'live') return renderLive(view, params, ctx);
  return renderSystem(view);
}

async function renderLive(view, params, ctx) {
  const stamp = h('span', { class: 'small muted' });
  const valid = new Set(TILES.map(t => t[0]));
  let chosen = (ctx.user.prefs?.[PREF] || DEFAULT_TILES).filter(k => valid.has(k));
  let last = null;
  const picker = tilePicker(() => chosen, async next => {
    chosen = next;
    if (last) drawTiles(tiles, last.summary, chosen);
    ctx.user.prefs = { ...ctx.user.prefs, [PREF]: chosen };
    try { await api.put(`/api/auth/prefs/${PREF}`, chosen); } catch { /* sonraki seçimde tekrar denenir */ }
  });
  const tiles = h('div', { class: 'tiles admin-tiles' });
  const planesBox = h('div', { class: 'admin-planes' });
  const onlineBox = h('div', { class: 'card card-pad' });
  const printersBox = h('div', { class: 'card card-pad' });
  const planes = new Map();   // ürün id → { pl, data }
  // Filtre çubuğu: yazıcı listesi ve çevrimiçi personel
  const pq = h('input', { class: 'input', type: 'search', placeholder: 'Yazıcı adı, IP, dosya ara…', style: { width: '220px' } });
  const pstate = selectInput([['YAZDIRIYOR', 'Yazdıran'], ['IDLE', 'Boşta (hazır / baskı bitti)'], ['MISMATCH', 'Durumu uyumsuz'],
    ['PROBLEM', 'Hata / duraklatıldı'], ['CEVRIMDISI', 'Çevrimdışı']], { all: 'Tüm yazıcılar' });
  const uq = h('input', { class: 'input', type: 'search', placeholder: 'Çevrimiçi personel ara…', style: { width: '200px' } });
  const redrawSide = () => { if (last) { drawOnline(onlineBox, last.online.filter(u => matches(uq.value, u.full_name, ...u.roles))); drawPrinters(printersBox, filterPrinters(last.printers)); } };
  const filterPrinters = list => list.filter(p => {
    const st = p.live_state;
    const ok = !pstate.value || (pstate.value === 'IDLE' ? st === 'HAZIR' || st === 'TAMAMLANDI'
      : pstate.value === 'MISMATCH' ? p.stale || p.outside
        : pstate.value === 'PROBLEM' ? st === 'HATA' || st === 'DURAKLADI'
          : pstate.value === 'CEVRIMDISI' ? !st || st === 'CEVRIMDISI' : st === pstate.value);
    return ok && matches(pq.value, p.name, p.ip, p.live_file, p.current_part, p.current_order);
  });
  pq.addEventListener('input', redrawSide);
  uq.addEventListener('input', redrawSide);
  pstate.addEventListener('change', redrawSide);

  clear(view,
    pageHead('Yönetim', {
      back: '#/',
      sub: h('span', null, h('span', { class: 'live-dot' }), ' Canlı · 5 saniyede bir yenilenir · ', stamp),
      right: h('div', { class: 'head-right' }, picker, nav('live')),
    }),
    tiles,
    h('div', { class: 'filters' }, h('span', { class: 'lbl' }, 'Yazıcılar'), pq, pstate, h('span', { class: 'lbl' }, 'Personel'), uq),
    h('div', { class: 'admin-layout' }, planesBox, h('div', { class: 'admin-side' }, onlineBox, printersBox)));

  async function refresh() {
    const d = await api.get('/api/admin/dashboard');
    last = d;
    stamp.textContent = `Son güncelleme ${d.at.slice(11)}`;
    drawTiles(tiles, d.summary, chosen);
    await drawPlanes(planesBox, planes, d.products);
    redrawSide();
  }
  await refresh();
  every(REFRESH_MS, () => refresh().catch(() => {}));
}

function drawTiles(box, s, chosen) {
  const set = new Set(chosen);
  const list = TILES.filter(t => set.has(t[0]));
  if (!list.length) return clear(box, h('div', { class: 'card empty', style: { gridColumn: '1 / -1' } }, 'Gösterilecek rakam seçilmedi'));
  clear(box, list.map(([key, label, sub, level]) =>
    h('div', { class: `card tile ${level?.(s) || ''}` },
      h('div', { class: 'label' }, label),
      h('div', { class: 'value' }, s[key]),
      sub ? h('div', { class: 'small muted' }, sub(s)) : null)));
}

// Özet rakam seçici (açılır kutu, çoklu seçim)
function tilePicker(get, set) {
  const label = h('span');
  const btn = h('button', { class: 'btn', 'aria-haspopup': 'true' }, label, h('span', { 'aria-hidden': 'true' }, '▾'));
  const panel = h('div', { class: 'dropdown tile-picker', hidden: true });
  const sync = () => { label.textContent = `Gösterilen rakamlar (${get().length}/${TILES.length})`; };
  const fill = () => {
    const cur = new Set(get());
    clear(panel,
      TILES.map(([key, title]) => {
        const cb = h('input', { type: 'checkbox', checked: cur.has(key) });
        cb.addEventListener('change', () => {
          const next = TILES.map(t => t[0]).filter(k => (k === key ? cb.checked : cur.has(k)));
          cur.clear(); next.forEach(k => cur.add(k));
          set(next); sync();
        });
        return h('label', { class: 'check' }, cb, title);
      }),
      h('div', { class: 'picker-foot' },
        h('button', { class: 'btn sm ghost', onclick: () => { set([...DEFAULT_TILES]); sync(); fill(); } }, 'Varsayılana dön'),
        h('button', { class: 'btn sm ghost', onclick: () => { set(TILES.map(t => t[0])); sync(); fill(); } }, 'Tümünü seç')));
  };
  btn.addEventListener('click', e => { e.stopPropagation(); fill(); panel.hidden = !panel.hidden; });
  panel.addEventListener('click', e => e.stopPropagation());
  const close = () => { panel.hidden = true; };
  document.addEventListener('click', close);
  onLeave(() => document.removeEventListener('click', close));
  sync();
  return h('div', { class: 'menu-anchor' }, btn, panel);
}

// Her ürün tipi için bir uçak; yazıcıdaki parçalar mavi, içinde yazıcı adı ve kalan yüzde
async function drawPlanes(box, planes, products) {
  const ids = new Set(products.map(p => p.id));
  for (const [id, entry] of planes) {
    if (!ids.has(id)) { entry.card.remove(); planes.delete(id); }
  }
  for (const p of products) {
    let entry = planes.get(p.id);
    if (!entry) {
      const plane = await loadPlane(p.id);
      entry = { data: p, byPart: new Map() };
      entry.pl = renderPlane(plane, {
        fill: part => (entry.byPart.has(part.id) ? 'var(--st-uretimde)' : 'var(--part-fill)'),
        labelClass: part => (entry.byPart.has(part.id) ? 'printing' : 'idle'),
        label: part => {
          const jobs = entry.byPart.get(part.id);
          if (!jobs) return part.group === 'cover' || part.group === 'strake' || part.area < 6000 ? null : part.id;
          const lines = [];
          for (const j of jobs.slice(0, 2)) {
            lines.push({ text: j.printer || '?', class: 'pn' });
            lines.push({ text: j.remaining === null ? 'kalan: —' : `%${j.remaining} kaldı`, class: 'pr' });
          }
          if (jobs.length > 2) lines.push({ text: `+${jobs.length - 2} yazıcı`, class: 'pr' });
          return lines;
        },
        tooltip: part => {
          const jobs = entry.byPart.get(part.id);
          if (!jobs) return ['Yazıcıda değil'];
          return jobs.flatMap(j => [
            h('span', null, h('b', null, j.printer || '?'), ` · ${j.order_code}`),
            `Kalan: ${j.remaining === null ? 'bilinmiyor (yazıcıdan canlı veri yok)' : `%${j.remaining}`}`,
            `Süre: ${fmtDuration(j.elapsed_seconds)}`,
          ]);
        },
      });
      entry.title = h('div', { class: 'admin-plane-head' });
      entry.card = h('div', { class: 'card plane-stage admin-plane' }, entry.title, entry.pl.svg);
      box.append(entry.card);
      planes.set(p.id, entry);
    }
    entry.data = p;
    entry.byPart = new Map();
    for (const j of p.printing) {
      if (!entry.byPart.has(j.part_id)) entry.byPart.set(j.part_id, []);
      entry.byPart.get(j.part_id).push(j);
    }
    clear(entry.title,
      h('b', null, `${p.name} `), h('span', { class: 'mono small muted' }, p.serial),
      h('span', { class: 'spacer' }),
      h('span', { class: 'badge blue' }, `${p.printing.length} parça yazıcıda`),
      h('span', { class: 'badge gray' }, `${p.open_orders} açık sipariş`));
    entry.pl.update();
  }
  box.classList.toggle('two', planes.size > 1);
}

function drawOnline(box, users) {
  clear(box,
    h('h2', { class: 'side-title' }, `Çevrimiçi personel (${users.length})`),
    users.length ? h('ul', { class: 'online-list' }, users.map(u => h('li', null,
      h('span', { class: 'avatar-wrap' }, avatar(u), h('i', { class: 'online-dot' })),
      h('div', { class: 'grow' }, h('b', null, u.full_name), h('div', { class: 'small muted' }, u.roles.join(', ') || '—')),
      h('span', { class: 'small muted' }, u.seconds_ago < 30 ? 'şimdi' : `${Math.round(u.seconds_ago / 60) || 1} dk önce`))))
      : h('div', { class: 'muted small' }, 'Şu an çevrimiçi kimse yok'));
}

function drawPrinters(box, printers) {
  const order = { YAZDIRIYOR: 1, DURAKLADI: 2, HATA: 3, HAZIR: 4, TAMAMLANDI: 5, CEVRIMDISI: 6 };
  const rank = p => (p.stale ? 0 : p.outside ? 0.5 : order[p.live_state] ?? 7);   // uyumsuz olanlar en başta
  const list = [...printers].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name, 'tr'));
  clear(box,
    h('h2', { class: 'side-title' }, `Yazıcılar (${printers.length})`),
    printers.length ? null : h('div', { class: 'muted small' }, 'Filtreye uyan yazıcı yok'),
    h('div', { class: 'printer-grid' }, list.map(p => {
      const st = PRINTER_STATES[p.live_state] || { label: 'Bilinmiyor', badge: 'gray' };
      const pct = p.live_state === 'YAZDIRIYOR' && p.live_progress != null ? Math.round(p.live_progress) : null;
      return h('div', { class: `pcell ${st.badge} ${p.stale ? 'stale' : ''} ${p.outside ? 'outside' : ''}`, title: [p.name, p.ip, st.label, p.current_part ? `Sistemde: ${p.current_order} / ${p.current_part}` : p.live_file].filter(Boolean).join('\n') },
        h('b', null, p.name),
        h('span', null, pct !== null ? `%${100 - pct} kaldı` : st.label),
        p.stale ? h('em', null, `Sistemde üretimde: ${p.current_part}`) : null,
        p.outside ? h('em', { class: 'out' }, 'Sistemde kaydı yok') : null,
        pct !== null ? h('i', { class: 'pbar' }, h('i', { style: { width: `${pct}%` } })) : null);
    })));
}

// ---------- Sistem Durumu: sistem yöneticisinin bir bakışta görmek isteyeceği her şey (30 sn'de bir yenilenir)
const GB = 1024 ** 3;
const fmtBytes = b => (b == null ? '—' : b >= GB ? `${(b / GB).toFixed(b >= 100 * GB ? 0 : 1)} GB` : b >= 1024 ** 2 ? `${(b / 1024 ** 2).toFixed(1)} MB`
  : `${Math.round(b / 1024)} KB`);
const fmtUp = s => { if (s == null) return '—'; const d = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} gün ${hh} sa` : hh ? `${hh} sa ${m} dk` : `${m} dk`; };
const KIND_NAMES = { camfaces: 'Kamera yüz kayıtları', cargo: 'Kargo fotoğrafları', documents: 'Evraklar', errors: 'Üretim hata fotoğrafları',
  flightlogs: 'Uçuş logları', logos: 'Firma logoları', videos: 'Uçuş videoları', avatars: 'Profil fotoğrafları', media: 'Medya' };
const TABLE_NAMES = { users: 'Kullanıcı', orders: 'Sipariş', order_parts: 'Sipariş parçası', part_events: 'Parça olayı', printers: 'Yazıcı',
  products: 'Ürün', companies: 'Firma', company_people: 'Firma personeli', documents: 'Evrak', field_tasks: 'Saha görevi', flight_logs: 'Uçuş logu',
  guest_visits: 'Misafir kaydı', vehicle_visits: 'Araç kaydı', cargo: 'Kargo', cameras: 'Kamera', face_groups: 'Yüz grubu', face_sightings: 'Yüz görülme',
  audit_logs: 'İşlem logu', login_logs: 'Giriş logu' };

async function renderSystem(view) {
  const stamp = h('span', { class: 'small muted' });
  const body = h('div', { class: 'sys' });
  const charts = [];
  onLeave(() => charts.forEach(c => c.destroy()));
  clear(view, pageHead('Yönetim', { back: '#/', sub: h('span', null, 'Sistem durumu · 30 saniyede bir yenilenir · ', stamp),
    right: h('div', { class: 'head-right' }, nav('')) }), body);

  const gauge = (label, pct, sub, warn = 80, crit = 92) => {
    const tone = pct >= crit ? 'crit' : pct >= warn ? 'warn' : 'ok';
    const ring = h('div', { class: 'sys-ring' }, h('b', null, `%${Math.round(pct || 0)}`));
    ring.style.setProperty('--p', Math.min(100, pct || 0));
    return h('div', { class: `sys-gauge ${tone}` }, ring,
      h('div', null, h('span', null, label), h('small', null, sub)));
  };
  const card = (title, ...kids) => h('section', { class: 'card card-pad sys-card' }, h('h3', null, title), ...kids);
  const kv = rows => h('dl', { class: 'sys-kv' }, rows.filter(Boolean).map(([k, v]) => [h('dt', null, k), h('dd', null, v)]).flat());
  const names = (list, empty) => (list.length ? h('div', { class: 'sys-names' }, list.map(n => h('span', null, n))) : h('div', { class: 'small muted' }, empty));

  async function load() {
    const d = await api.get('/api/admin/system');
    stamp.textContent = `Son güncelleme ${d.at.slice(11)}`;
    charts.splice(0).forEach(c => c.destroy());
    const s = d.server, sec = d.security, b = d.backups;
    const down = d.services.filter(x => x.state !== 'active');
    const problems = [
      down.length ? `${down.length} servis çalışmıyor: ${down.map(x => x.label).join(', ')}` : null,
      !b.ok ? (b.nightly_age_h == null ? 'Gece yedeği bulunamadı' : `Son gece yedeği ${b.nightly_age_h} saat önce alınmış`) : null,
      sec.suspicious.length ? `Şüpheli giriş denemesi: ${sec.suspicious.map(x => `${x.key} (${x.n})`).join(', ')}` : null,
      d.errors.count ? `Son 24 saatte ${d.errors.count} sunucu hatası kaydı` : null,
      s.disk_total && s.disk_used / s.disk_total > 0.9 ? 'Disk %90 üzerinde dolu' : null,
      ...d.integrations.filter(i => !i.ok).map(i => `${i.name}: ${i.detail}`),
    ].filter(Boolean);

    const actCanvas = h('canvas'), growCanvas = h('canvas');
    clear(body,
      h('div', { class: `sys-banner ${problems.length ? 'bad' : 'good'}` },
        h('b', null, problems.length ? `${problems.length} konu dikkat istiyor` : 'Her şey yolunda'),
        problems.length ? h('ul', null, problems.map(p => h('li', null, p))) : h('span', null, ' · servisler çalışıyor, yedek güncel, şüpheli giriş yok')),

      h('div', { class: 'sys-gauges card card-pad' },
        gauge('İşlemci', s.cpu, `${s.cpus} çekirdek · yük ${s.load.map(x => x.toFixed(2)).join(' / ')}`),
        gauge('Bellek', s.ram_total ? 100 * s.ram_used / s.ram_total : 0, `${fmtBytes(s.ram_used)} / ${fmtBytes(s.ram_total)}`),
        gauge('Disk', s.disk_total ? 100 * s.disk_used / s.disk_total : 0, `${fmtBytes(s.disk_free)} boş / ${fmtBytes(s.disk_total)}`),
        s.gpu_name ? gauge('Ekran kartı', s.gpu, `${s.gpu_name}${s.gpu_temp != null ? ` · ${s.gpu_temp}°C` : ''}`) : null,
        h('div', { class: 'sys-up' }, h('span', null, 'Sunucu açık'), h('b', null, fmtUp(s.uptime_s)), h('span', null, 'Uygulama'), h('b', null, fmtUp(s.app_uptime_s)),
          h('small', null, d.host))),

      h('div', { class: 'sys-grid' },
        card('Servisler', h('ul', { class: 'sys-svc' }, d.services.map(x => h('li', { class: x.state === 'active' ? 'ok' : 'bad' },
          h('i'), h('div', null, h('b', null, x.label), h('small', null, `${x.unit} · ${x.state === 'active' ? 'çalışıyor' : x.state}${x.since ? ` · ${x.since}` : ''}`)))))),
        card('Yedekleme', kv([
          ['Durum', h('span', { class: `badge ${b.ok ? 'green' : 'red'}` }, b.ok ? 'Güncel' : 'Eski / yok')],
          ['Son gece yedeği', b.nightly_last ? `${b.nightly_last} (${b.nightly_age_h} sa önce)` : '—'],
          ['Yedek boyutu', fmtBytes(b.nightly_size)],
          ['Saklanan gece yedeği', b.nightly_count],
          ['Dosya anlık görüntüsü', b.uploads_snapshots],
          ['Elle alınan yedek', `${b.manual_count}${b.manual_last ? ` · son: ${b.manual_last}` : ''}`],
          ['Kamera anahtarı yedekte', b.camera_key_backed ? 'Evet' : h('b', { class: 'text-danger' }, 'Hayır')],
          ['Yedek klasörü', fmtBytes(d.storage.backups_size)],
        ])),
        card('Entegrasyonlar', h('ul', { class: 'sys-svc' }, d.integrations.map(i => h('li', { class: i.ok ? 'ok' : 'bad' },
          h('i'), h('div', null, h('b', null, i.name), h('small', null, i.detail)))))),

        card('Kullanıcılar ve oturumlar',
          h('div', { class: 'db-kpis' },
            [['Aktif kullanıcı', `${sec.users_active} / ${sec.users_total}`], ['Çevrimiçi', sec.online], ['Açık oturum', sec.sessions],
              ['Bugün giriş', sec.logins_today], ['Başarısız giriş (24 sa)', sec.fails_24h, sec.fails_24h >= 5 ? 'alert' : '']]
              .map(([l, v, t]) => h('div', { class: `db-kpi ${t || ''}` }, h('b', null, v), h('span', null, l)))),
          h('h4', null, 'Rollere göre'), h('div', { class: 'sys-names' }, sec.roles.map(([r, n]) => h('span', null, `${r} `, h('b', null, n)))),
          h('h4', null, `Rolü olmayan (${sec.no_role.length})`), names(sec.no_role, 'Yok'),
          h('h4', null, `Hiç giriş yapmamış (${sec.never_logged.length})`), names(sec.never_logged, 'Yok'),
          h('h4', null, `30 gündür girmeyen (${sec.inactive_30d.length})`), names(sec.inactive_30d, 'Yok')),
        card('Güvenlik',
          sec.suspicious.length ? h('div', { class: 'sys-alert' }, h('b', null, 'Şüpheli deneme (24 saatte 5+ başarısız)'),
            h('ul', null, sec.suspicious.map(x => h('li', null, `${x.what}: ${x.key} — ${x.n} deneme`)))) : h('div', { class: 'sys-okline' }, '✓ Şüpheli giriş denemesi yok'),
          h('h4', null, 'Son başarısız girişler'),
          sec.recent_fails.length ? h('table', { class: 'table compact' }, h('tbody', null, sec.recent_fails.map(f => h('tr', null,
            h('td', null, fmtDateTime(f.at)), h('td', null, f.username), h('td', { class: 'muted' }, f.ip || '—'))))) : h('div', { class: 'small muted' }, 'Yok'),
          h('h4', null, `Sunucu hataları (24 sa): ${d.errors.count}`),
          d.errors.last.length ? h('pre', { class: 'sys-log' }, d.errors.last.join('\n')) : h('div', { class: 'sys-okline' }, '✓ Hata kaydı yok')),

        card('Veritabanı', kv([['Boyut', fmtBytes(d.database.size)], ['WAL günlüğü', fmtBytes(d.database.wal)]]),
          h('table', { class: 'table compact' }, h('tbody', null, Object.entries(d.database.counts).sort((a, c) => c[1] - a[1]).map(([t, n]) =>
            h('tr', null, h('td', null, TABLE_NAMES[t] || t), h('td', { class: 'num' }, n.toLocaleString('tr-TR'))))))),
        card('Dosya depolama', kv([['Yüklenen dosyalar', fmtBytes(d.storage.uploads_total)]]),
          h('div', { class: 'sys-bars' }, d.storage.uploads.sort((a, c) => c.size - a.size).map(k => h('div', null,
            h('span', null, KIND_NAMES[k.kind] || k.kind, h('small', null, ` · ${k.files} dosya`)), h('b', null, fmtBytes(k.size)),
            h('i', { style: { width: `${d.storage.uploads_total ? Math.max(1, 100 * k.size / d.storage.uploads_total) : 0}%` } }))))),

        h('section', { class: 'card card-pad sys-card s2' }, h('h3', null, 'Kullanım · son 14 gün (işlem ve giriş)'), h('div', { class: 'sys-chart' }, actCanvas)),
        card('En aktif kullanıcılar (7 gün)', h('div', { class: 'sys-bars' }, d.activity.top.map(t => h('div', null, h('span', null, t.name), h('b', null, t.n),
          h('i', { style: { width: `${100 * t.n / (d.activity.top[0]?.n || 1)}%` } }))))),
        h('section', { class: 'card card-pad sys-card s2' }, h('h3', null, 'Veri büyümesi · son 14 gün yeni kayıt'), h('div', { class: 'sys-chart' }, growCanvas)),
        h('section', { class: 'card card-pad sys-card s3' }, h('h3', null, 'Gün × saat yoğunluğu (7 gün, işlem sayısı)'), heatEl(d.activity.heat)),
        h('section', { class: 'card card-pad sys-card s3' }, h('h3', null, 'Son işlemler'),
          h('table', { class: 'table compact' }, h('tbody', null, d.activity.recent.map(r => h('tr', null,
            h('td', { class: 'nowrap' }, fmtDateTime(r.at)), h('td', null, r.who || 'Sistem'), h('td', null, h('b', null, r.action)), h('td', { class: 'muted' }, r.detail || ''))))))));

    const labels = d.activity.days.map(x => `${x.slice(8, 10)}.${x.slice(5, 7)}`);
    loadChart().then(Chart => {
      charts.push(new Chart(actCanvas, chartConfig({ labels, datasets: [{ label: 'İşlem', data: d.activity.actions }, { label: 'Giriş', data: d.activity.logins, line: true, axis: 'n' }] }, theme(), false)));
      charts.push(new Chart(growCanvas, chartConfig({ labels, stacked: true, datasets: d.growth.series.filter(x => x.data.some(Boolean)) }, theme(), false)));
    }).catch(() => {});
  }
  await load();
  every(30000, () => { if (!document.querySelector('.modal-back')) load().catch(() => {}); });
}
