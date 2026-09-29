// Araçlar → Üretim Planlayıcı: mamul + adet → yazıcılara hangi parça, hangi sırayla (Gantt şeması).
// Yazıcıların anlık durumu dikkate alınır (boştakiler hemen, baskıdakiler kalan süreden sonra; çevrimdışı / hatalı hariç).
import { api } from '../api.js';
import { foot, head, printPage, sign } from '../print.js';
import { fmtMinutes, h, clear, field, fmtDateTime, pageHead, segmented, statStrip, toastError } from '../ui.js';

const COLORS = ['#1f6feb', '#16a34a', '#d97706', '#9333ea', '#dc2626', '#0891b2', '#db2777', '#65a30d', '#7c3aed', '#ea580c'];
const colorOf = n => COLORS[(n - 1) % COLORS.length];
const ms = iso => new Date(iso).getTime();
// Plan anından son parçanın bitişine geçen takvim süresi
const span = r => (r.end ? fmtMinutes(Math.round((ms(r.end) - ms(r.now)) / 60000)) : '—');
const hhmm = iso => new Date(iso).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

export async function renderPlanner(view, ctx) {
  const products = await api.get('/api/planner/products');
  const product = h('select', { class: 'input' }, products.map(p => h('option', { value: p.id },
    `${p.name} (${p.serial}) · ${p.part_count} parça`)));
  const qty = h('input', { class: 'input', type: 'number', min: 1, max: 50, value: 1, style: { width: '110px' } });
  const change = h('input', { class: 'input', type: 'number', min: 0, max: 240, value: 15, style: { width: '110px' },
    title: 'İki baskı arasında tabla boşaltma ve temizlik için ayrılan süre' });
  let idle = false;   // true: yazıcıların anlık durumu yok sayılır, hepsi boşmuş gibi planlanır
  const idleSeg = segmented([['current', 'Mevcut durum'], ['idle', 'Hepsi boş']], 'current', v => { idle = v === 'idle'; });
  let mode = 'aircraft';
  const modeSeg = segmented([['aircraft', 'Uçak uçak'], ['fastest', 'En kısa toplam süre']], mode, v => { mode = v; });
  const run = h('button', { class: 'btn primary', type: 'button' }, 'Planı Hesapla');
  const printBtn = h('button', { class: 'btn', type: 'button', disabled: true, onclick: () => printPlan() }, 'Yazdır / PDF');
  const out = h('div');
  let zoomLevel = 18;   // saat başına piksel
  let last = null;
  let checked = new Set();   // yükleme listesinde işaretlenenler ("yazıcıId:sıra"); çıktıya da işlenir

  const calc = async () => {
    run.disabled = true;
    try {
      last = await api.post('/api/planner/plan', { product_id: Number(product.value), quantity: Number(qty.value) || 1, mode,
        change_minutes: Number(change.value) || 0, assume_idle: idle });
      checked = new Set();
      printBtn.disabled = false;
      draw();
    } catch (err) { toastError(err); } finally { run.disabled = false; }
  };
  run.addEventListener('click', calc);

  function draw() {
    const r = last;
    const stats = statStrip();
    stats.set([
      { label: 'Uçak', value: r.quantity },
      { label: 'Basılacak parça', value: r.jobs },
      { label: 'Kullanılabilir yazıcı', value: r.printers.length,
        sub: r.assume_idle ? 'hepsi boş varsayıldı' : `${r.printers.filter(p => !p.busy).length} boşta` },
      { label: 'Şimdi yüklenecek', value: r.first_loads.length, tone: 'ok' },
      { label: 'Tahmini bitiş', value: r.end ? hhmm(r.end) : '—', tone: 'alert' },
      { label: 'Tahmini toplam süre', value: span(r), sub: 'şimdiden son parçanın bitişine', tone: 'alert' },
    ]);
    clear(out,
      stats,
      r.unknown_parts.length ? h('div', { class: 'alert warn' }, `${r.unknown_parts.length} parçanın baskı süresi tanımlı değil (${r.unknown_parts.slice(0, 8).join(', ')}${r.unknown_parts.length > 8 ? '…' : ''}); `
        + `plan için ${fmtMinutes(r.fallback_minutes)} varsayıldı. Süreleri Ürün Yönetimi'nden girin.`) : null,
      r.assume_idle ? h('div', { class: 'alert info' }, 'Varsayımsal plan: yazıcıların anlık durumu yok sayıldı; '
        + 'sistemdeki tüm yazıcılar şu an boş kabul edildi.') : null,
      r.unusable.length ? h('div', { class: 'alert warn' }, `Plana alınmayan ${r.unusable.length} yazıcı (çevrimdışı / hata): `
        + r.unusable.map(p => p.name).join(', ')) : null,
      h('div', { class: 'card card-pad' },
        h('div', { class: 'pl-head' }, h('h2', null, 'Gantt şeması'), h('span', { class: 'grow' }),
          h('span', { class: 'pl-legend' },
            Array.from({ length: Math.min(r.quantity, COLORS.length) }, (_, i) => h('span', null, h('i', { style: { background: colorOf(i + 1) } }), `${i + 1}. uçak`)),
            h('span', null, h('i', { class: 'busy' }), 'Yazıcıdaki mevcut iş')),
          segmented([['8', 'Uzak'], ['18', 'Orta'], ['40', 'Yakın']], String(zoomLevel), v => { zoomLevel = Number(v); draw(); })),
        gantt(r)),
      h('div', { class: 'card card-pad', style: { marginTop: '16px' } },
        h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, `Şimdi yükleyin (${r.first_loads.length} yazıcı)`),
        r.first_loads.length ? h('div', { class: 'table-wrap' }, h('table', null,
          h('thead', null, h('tr', null, ['Yazıcı', 'Uçak', 'Parça', 'Yazıcıya verilecek dosya', 'Süre', 'Bitiş'].map(c => h('th', null, c)))),
          h('tbody', null, r.first_loads.map(j => h('tr', null,
            h('td', null, h('b', null, j.printer)),
            h('td', null, h('span', { class: 'pl-dot', style: { background: colorOf(j.aircraft) } }), `${j.aircraft}. uçak`),
            h('td', { class: 'mono' }, j.part),
            h('td', { class: 'mono' }, j.file || h('span', { class: 'muted' }, 'tanımsız')),
            h('td', null, fmtMinutes(j.minutes), j.estimated ? h('span', { class: 'muted' }, ' (varsayım)') : null),
            h('td', null, hhmm(j.end)))))))
          : h('div', { class: 'empty small' }, 'Şu an boşta yazıcı yok; ilk işler baskıdaki yazıcılar boşaldıkça başlar (şemaya bakın).')),
      h('div', { class: 'card card-pad', style: { marginTop: '16px' } },
        h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Uçakların tahmini bitişi'),
        h('ul', { class: 'stat-list' }, r.aircraft_done.map(a => h('li', null,
          h('span', null, h('span', { class: 'pl-dot', style: { background: colorOf(a.aircraft) } }), `${a.aircraft}. uçak — son parça`),
          h('b', null, hhmm(a.end))))),
      h('div', { class: 'card card-pad', style: { marginTop: '16px' } },
        h('div', { class: 'pl-head' }, h('h2', null, 'Yazıcı yazıcı yükleme sırası'), h('span', { class: 'grow' }),
          h('span', { class: 'small muted' }, 'Yüklediğiniz dosyayı işaretleyin; işaretler çıktıya da yansır')),
        h('div', { class: 'pl-lists' }, loadLists(r, false)))));
  }

  const printers = r => r.printers.filter(p => p.jobs.length);
  const busyText = b => `Önce mevcut iş: ${b.part || b.file || 'bilinmeyen iş'}${b.order ? ` (${b.order})` : ''} · tahmini boşalma ${hhmm(b.until)}`;

  // Her yazıcı için sıralı dosya listesi; ekranda tıklanabilir kutucuk, çıktıda boş / işaretli kare
  function loadLists(r, print) {
    return printers(r).map(p => h('section', { class: 'pl-list' },
      h('div', { class: 'pl-list-head' }, h('b', null, p.name),
        h('span', null, `${p.jobs.length} baskı · bitiş ${hhmm(p.jobs[p.jobs.length - 1].end)}`)),
      p.busy ? h('div', { class: 'pl-list-note' }, busyText(p.busy)) : null,
      p.note ? h('div', { class: 'pl-list-note warn' }, p.note) : null,
      h('table', { class: print ? 'pf-table pf-list pl-ptable' : 'pl-table' },
        h('thead', null, h('tr', null, ['✓', 'Sıra', 'Uçak', 'Parça', 'Yazıcıya verilecek dosya', 'Süre', 'Başlangıç', 'Bitiş']
          .map(c => h('th', null, c)))),
        h('tbody', null, p.jobs.map((j, i) => {
          const key = `${p.id}:${i}`;
          const box = print ? h('span', { class: `pl-cb ${checked.has(key) ? 'on' : ''}` }, checked.has(key) ? '✓' : '')
            : h('input', { type: 'checkbox', checked: checked.has(key),
              onchange: e => { e.target.checked ? checked.add(key) : checked.delete(key); e.target.closest('tr').classList.toggle('done', e.target.checked); } });
          return h('tr', { class: checked.has(key) && !print ? 'done' : '' },
            h('td', { class: 'pl-cbcell' }, box),
            h('td', null, `${i + 1}`),
            h('td', null, h('span', { class: 'pl-dot', style: { background: colorOf(j.aircraft) } }), `${j.aircraft}. uçak`),
            h('td', { class: 'mono' }, j.part),
            h('td', { class: 'mono' }, j.file || 'tanımsız'),
            h('td', null, fmtMinutes(j.minutes), j.estimated ? ' (varsayım)' : ''),
            h('td', null, hhmm(j.start)),
            h('td', null, hhmm(j.end)));
        })))));
  }

  function printPlan() {
    const r = last;
    const company = ctx?.meta?.company || '';
    const modeText = r.mode === 'fastest' ? 'Toplam süre en kısa' : 'Uçak uçak (ilk uçak en erken)';
    const kv = rows => h('table', { class: 'pf-table pl-pkv' }, h('tbody', null, rows.map(row => h('tr', null,
      row.flatMap(([k, v]) => [h('th', null, k), h('td', null, v)])))));
    printPage(h('div', { class: 'pf-page pf-flow pl-print' },
      head(company, 'ÜRETİM PLANI', [['Mamul', r.product.name], ['Adet', String(r.quantity)], ['Plan zamanı', hhmm(r.now)]]),
      kv([
        [['Öncelik', modeText], ['Hazırlık süresi', `${r.change_minutes} dk`]],
        [['Yazıcı durumu', r.assume_idle ? 'Hepsi boş varsayıldı (varsayımsal plan)' : 'Mevcut durum'],
          ['Kullanılabilir yazıcı', `${r.printers.length} (${r.printers.filter(p => !p.busy).length} boşta)`]],
        [['Basılacak parça', String(r.jobs)], ['Mamul', `${r.product.name} × ${r.quantity}`]],
        [['Tahmini bitiş', r.end ? hhmm(r.end) : '—'], ['Tahmini toplam süre', span(r)]],
        [['Uçak bitişleri', r.aircraft_done.map(a => `${a.aircraft}. uçak ${hhmm(a.end)}`).join(' · ')],
          ['Plana alınmayan', r.unusable.map(p => p.name).join(', ') || '—']],
      ]),
      r.unknown_parts.length ? h('p', { class: 'pf-empty' }, `Baskı süresi tanımsız ${r.unknown_parts.length} parça için ${fmtMinutes(r.fallback_minutes)} varsayıldı: `
        + r.unknown_parts.join(', ')) : null,
      h('h2', { class: 'pf-h2' }, 'Gantt şeması'),
      h('div', { class: 'pl-legend' },
        Array.from({ length: Math.min(r.quantity, COLORS.length) }, (_, i) => h('span', null, h('i', { style: { background: colorOf(i + 1) } }), `${i + 1}. uçak`)),
        h('span', null, h('i', { class: 'busy' }), 'Yazıcıdaki mevcut iş')),
      gantt(r, 600),
      h('h2', { class: 'pf-h2 pl-pbreak' }, 'Yazıcı yazıcı yükleme sırası'),
      h('p', { class: 'pf-empty' }, 'Her dosyayı yazıcıya yükledikten sonra kutucuğu işaretleyiniz. Sıra, planın varsaydığı sıradır; '
        + 'gerçek süreler değişirse planı yeniden hesaplayın.'),
      loadLists(r, true),
      h('div', { class: 'pf-signs' }, sign('Planı Hazırlayan', ctx?.user?.full_name || ''), sign('Kontrol Eden', ''), sign('Onaylayan', '')),
      foot(company, `Yazdırma: ${fmtDateTime(new Date().toISOString())}`)), `Üretim planı ${r.product.name} × ${r.quantity}`);
  }

  // fit: verilirse şema bu genişliğe sığdırılır (çıktı)
  function gantt(r, fit) {
    const t0 = ms(r.now);
    const ends = r.printers.flatMap(p => [...p.jobs.map(j => ms(j.end)), p.busy ? ms(p.busy.until) : t0]);
    const t1 = Math.max(t0 + 3600e3, ...ends);
    const hours = Math.ceil((t1 - t0) / 3600e3) + 1;
    const zoom = fit ? fit / hours : zoomLevel;
    const width = hours * zoom;
    const x = t => ((t - t0) / 3600e3) * zoom;
    const ticks = [];
    const step = zoom >= 30 ? 1 : zoom >= 14 ? 3 : zoom >= 6 ? 6 : zoom >= 3 ? 12 : 24;   // saat çizgisi aralığı
    const first = new Date(t0); first.setMinutes(0, 0, 0);
    const marks0 = [{ px: 0, w: 48 }];   // etiket çakışmasın: "Şimdi" ve gün etiketleri yer kaplar
    for (let t = first.getTime() + 3600e3; t <= t1; t += 3600e3) {
      if (new Date(t).getHours() === 0) marks0.push({ px: x(t), w: 76 });
    }
    const crowded = px => marks0.some(m => px > m.px - 36 && px < m.px + m.w);
    for (let t = first.getTime() + 3600e3; t <= t1; t += 3600e3) {
      const d = new Date(t);
      if (d.getHours() % step) continue;
      const day = d.getHours() === 0;
      const label = day ? d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', weekday: 'short' })
        : crowded(x(t)) ? '' : `${String(d.getHours()).padStart(2, '0')}:00`;
      ticks.push(h('div', { class: `pl-tick ${day ? 'day' : ''}`, style: { left: `${x(t)}px` } }, label ? h('span', null, label) : null));
    }
    const rows = r.printers.filter(p => p.jobs.length || p.busy).map(p => h('div', { class: 'pl-row' },
      h('div', { class: 'pl-name', title: p.note || '' }, h('b', null, p.name), p.note && !fit ? h('span', { class: 'pl-warn' }, '!') : null),
      h('div', { class: 'pl-track', style: { width: `${width}px` } },
        p.busy ? h('div', { class: 'pl-bar busy', style: { left: '0px', width: `${Math.max(3, x(ms(p.busy.until)))}px` },
          title: `Yazıcıda şu an: ${p.busy.part || p.busy.file || 'bilinmeyen iş'}${p.busy.order ? ` (${p.busy.order})` : ' — sistemde kayıtsız'}`
            + `\nTahmini boşalma: ${hhmm(p.busy.until)}${p.busy.estimated ? ' (süre bilinmiyor, 1 sa varsayıldı)' : ''}` },
          h('span', null, p.busy.part || 'meşgul')) : null,
        p.jobs.map(j => h('div', { class: `pl-bar ${j.estimated ? 'est' : ''}`,
          style: { left: `${x(ms(j.start))}px`, width: `${Math.max(3, x(ms(j.end)) - x(ms(j.start)))}px`, background: colorOf(j.aircraft) },
          title: `${j.aircraft}. uçak · ${j.part}\n${j.file || 'dosya tanımsız'}\n${hhmm(j.start)} → ${hhmm(j.end)} (${fmtMinutes(j.minutes)})` },
          h('span', null, j.part))))));
    const marks = r.aircraft_done.map(a => h('div', { class: 'pl-done', style: { left: `${x(ms(a.end))}px`, borderColor: colorOf(a.aircraft) },
      title: `${a.aircraft}. uçağın son parçası: ${hhmm(a.end)}` }, h('span', { style: { background: colorOf(a.aircraft) } }, `${a.aircraft}`)));
    return h('div', { class: 'pl-gantt' },
      h('div', { class: 'pl-inner', style: { width: `${width + 110}px` } },
        h('div', { class: 'pl-axis' }, h('div', { class: 'pl-name' }, 'Yazıcı'), h('div', { class: 'pl-track', style: { width: `${width}px` } },
          h('div', { class: 'pl-tick now', style: { left: '0px' } }, h('span', null, 'Şimdi')), ticks, marks)),
        rows.length ? rows : h('div', { class: 'empty small' }, 'Plana alınabilecek yazıcı yok')));
  }

  clear(view,
    pageHead('Üretim Planlayıcı', { back: '#/tools', sub: 'Mamul ve adet seçin; yazıcılara hangi parçaların hangi sırayla yükleneceği hesaplansın' }),
    h('div', { class: 'card card-pad pl-form' },
      field('Mamul', product),
      field('Adet', qty),
      field('Hazırlık (dk)', change),
      field('Yazıcı durumu', idleSeg),
      field('Öncelik', modeSeg),
      h('div', { class: 'pl-run' }, run, printBtn)),
    out);
  qty.addEventListener('keydown', e => { if (e.key === 'Enter') calc(); });
}
