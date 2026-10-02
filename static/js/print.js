// Yazdırılabilir A4 belgeler: sipariş formu (iki kopya) ve yarı mamul raporu.
import { logActivity } from './api.js';
import { renderPlane } from './plane.js';
import { PART_STATES, queuePlate } from './status.js';
import { fmtDate, fmtDateTime, h } from './ui.js';

const now = () => fmtDateTime(new Date().toISOString());

export function head(company, title, lines) {
  return h('header', { class: 'pf-head' },
    h('img', { class: 'pf-logo', src: '/static/img/logo.png', alt: company }),
    h('div', { class: 'pf-title' },
      h('h1', null, title),
      lines.map(([k, v]) => h('div', null, `${k}: `, h('b', null, v)))));
}

export function foot(company, right) {
  return h('footer', { class: 'pf-foot' }, h('span', null, company), h('span', null, right));
}

// Sayfayı belgeye ekler, logolar yüklenince yazdırır, yazdırma bitince kaldırır.
export function printPage(page, title = 'Belge') {
  logActivity({ event: 'print', path: location.hash, title });
  document.querySelector('.print-area')?.remove();
  const area = h('div', { class: 'print-area' }, page);
  document.body.append(area);
  const cleanup = () => { area.remove(); window.removeEventListener('afterprint', cleanup); };
  window.addEventListener('afterprint', cleanup);
  const imgs = [...area.querySelectorAll('img')];
  Promise.all(imgs.map(i => (i.complete ? null : new Promise(r => { i.onload = i.onerror = r; }))))
    .then(() => window.print());
}

// ---------- Sipariş formu: tek sayfada iki kopya, ortada kesim çizgisi ----------
function copy(order, company, label) {
  return h('section', { class: 'pf-copy' },
    head(company, 'SİPARİŞ FORMU', [['Sipariş tarihi', fmtDate(order.created_at)], ['Sipariş no', order.code]]),
    h('table', { class: 'pf-table' }, h('tbody', null,
      row('Ürün', `${order.product_name} İnsansız Uçak`),
      row('Ürün seri numarası', order.product_serial),
      row('Adet', '1'),
      row('Parça sayısı', String(order.total_parts)),
      row('Üretim başlama tarihi', fmtDate(order.start_date)),
      row('Üretim bitiş tarihi', fmtDate(order.end_date)),
      row('Açıklama', order.note || '—'))),
    h('div', { class: 'pf-signs' },
      sign('Siparişi Oluşturan', order.created_by_name || ''),
      sign('Onaylayan', '')),
    foot(company, `${label} · Yazdırma: ${now()}`));
}

const row = (k, v) => h('tr', null, h('th', null, k), h('td', null, v));

export function sign(title, name) {
  return h('div', { class: 'pf-sign' },
    h('div', { class: 'pf-sign-title' }, title),
    h('div', { class: 'pf-sign-line' }, h('span', null, 'Ad Soyad:'), h('b', null, name)),
    h('div', { class: 'pf-sign-line' }, h('span', null, 'Tarih:')),
    h('div', { class: 'pf-sign-box' }, 'İmza'));
}

export function printOrderForm(order, company) {
  printPage(h('div', { class: 'pf-page' },
    copy(order, company, '1. Nüsha'),
    h('div', { class: 'pf-cut' }, h('span', null, '✂ Buradan kesiniz')),
    copy(order, company, '2. Nüsha')), `Sipariş formu ${order.code}`);
}

// ---------- Yarı mamul raporu: tamamlanan/kalan yüzde ve renkli uçak ----------
export function printWipReport(order, plane, company) {
  const byPart = new Map(order.parts.map(p => [p.part_id, p]));
  const done = order.progress;
  const counts = Object.fromEntries(Object.keys(PART_STATES).map(k => [k, 0]));
  order.parts.forEach(p => { counts[p.state]++; });
  const produced = counts.DEPO + counts.MONTAJ;

  const pl = renderPlane(plane, { fill: part => PART_STATES[byPart.get(part.id)?.state]?.color || 'var(--part-fill)' });

  printPage(h('div', { class: 'pf-page pf-report' },
    head(company, 'YARI MAMUL RAPORU', [
      ['Sipariş no', order.code],
      ['Rapor tarihi', fmtDate(new Date().toISOString())],
    ]),
    h('div', { class: 'wr-summary' },
      h('div', { class: 'wr-stat done' }, h('span', null, 'Tamamlanan'), h('b', null, `%${done}`),
        h('small', null, `${produced} / ${order.parts.length} parça`)),
      h('div', { class: 'wr-bar' }, h('i', { style: { width: `${done}%` } })),
      h('div', { class: 'wr-stat left' }, h('span', null, 'Kalan'), h('b', null, `%${100 - done}`),
        h('small', null, `${order.parts.length - produced} parça`))),
    h('div', { class: 'wr-plane' }, pl.svg),
    h('div', { class: 'wr-legend' }, Object.entries(PART_STATES).map(([k, s]) =>
      h('span', null, h('i', { style: { background: s.color } }), `${s.label}: `, h('b', null, counts[k])))),
    h('table', { class: 'pf-table wr-info' }, h('tbody', null,
      h('tr', null,
        h('th', null, 'Siparişi veren'), h('td', null, order.created_by_name || '—'),
        h('th', null, 'Başlama / Bitiş'), h('td', null, `${fmtDate(order.start_date)} – ${fmtDate(order.end_date)}`)))),
    foot(company, `Yazdırma: ${now()}`)), `Yarı mamul raporu ${order.code}`);
}

// ---------- Saha görev formu: görev, uçuşlar, yol ve masraflar; imzalı ----------
export function printTaskForm(t, company) {
  const launch = { ARAC_USTU: 'Araç Üstü', RAMPA: 'Fırlatma Rampası' };
  const drivers = [...new Set([t.driver_name, ...(t.vehicles || []).map(v => v.driver_name)].filter(Boolean))].join(', ');
  const money = v => `${Number(v || 0).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;
  const kv = rows => h('table', { class: 'pf-table' }, h('tbody', null,
    rows.filter(Boolean).map(([k, v]) => h('tr', null, h('th', null, k), h('td', null, v)))));
  const list = (cols, rows, empty) => (rows.length
    ? h('table', { class: 'pf-table pf-list' }, h('thead', null, h('tr', null, cols.map(c => h('th', null, c)))), h('tbody', null, rows))
    : h('p', { class: 'pf-empty' }, empty));
  const status = { BASLANGIC: 'Başlangıç', GOREVDE: 'Görevde', GOREV_TAMAMLANDI: 'Görev Tamamlandı', BASARISIZ: 'Başarısız',
    RAPOR_TAMAMLANDI: 'Rapor Tamamlandı', IPTAL: 'İptal' }[t.status] || t.status;
  printPage(h('div', { class: 'pf-page pf-flow' },
    head(company, 'SAHA GÖREV FORMU', [['Görev no', t.code], ['Tarih', fmtDate(t.started_at || t.created_at)]]),
    h('h2', { class: 'pf-h2' }, 'Görev bilgileri'),
    kv([
      ['Durum', `${status}${t.result ? ` (${t.result === 'BASARILI' ? 'Başarılı' : 'Başarısız'})` : ''}`],
      ['Saha sorumlusu', t.lead_name || '—'],
      ['Pilot', t.pilot_name || '—'],
      ['Şoför', drivers || '—'],
      ['Saha personeli', t.staff.map(s => s.full_name).join(', ') || '—'],
      ['Görev yeri', t.location_name || '—'],
      ['Başlama / bitiş', t.started_at ? `${fmtDateTime(t.started_at)} – ${t.finished_at ? fmtDateTime(t.finished_at) : 'devam ediyor'}` : '—'],
      t.note ? ['Not', t.note] : null,
    ]),
    h('h2', { class: 'pf-h2' }, `Uçuşlar (${t.flights.length})`),
    list(['Uçak', 'Ürün', 'Fırlatma sistemi', 'Uçuş raporu', 'Not'], t.flights.map(f => h('tr', null,
      h('td', null, queuePlate(f.queue_no) || f.order_code), h('td', null, `${f.product_name || ''} ${f.product_serial || ''}`),
      h('td', null, launch[f.launch] || '—'), h('td', null, f.log_status === 'TAMAM' ? 'Hazır' : f.log_status ? 'İşleniyor / hatalı' : 'Yok'),
      h('td', null, f.note || ''))), 'Uçuş yok'),
    h('h2', { class: 'pf-h2' }, 'Yol'),
    list(['Araç', 'Şoför', 'Başlangıç km', 'Bitiş km', 'Gidilen yol'], (t.vehicles || []).map(v => h('tr', null,
      h('td', null, v.plate), h('td', null, v.driver_name || ''), h('td', { class: 'num' }, v.start_km ?? '—'),
      h('td', { class: 'num' }, v.end_km ?? '—'), h('td', { class: 'num' }, v.distance_km != null ? `${v.distance_km} km` : '—'))),
    'Araç girilmedi'),
    kv([
      ['Toplam gidilen yol', t.distance_km != null ? `${t.distance_km} km` : '—'],
      t.road_note ? ['Not', t.road_note] : null,
    ]),
    h('h2', { class: 'pf-h2' }, `Masraflar (toplam ${money(t.expense_total)})`),
    list(['Tarih', 'Masrafı yapan', 'Kategori', 'Açıklama', 'Tutar'], (t.expenses || []).map(e => h('tr', null,
      h('td', null, fmtDate(e.spent_on)), h('td', null, e.spent_by_name || e.created_by_name || ''), h('td', null, e.category),
      h('td', null, e.description || ''),
      h('td', { class: 'num' }, money(e.amount)))), 'Masraf girilmedi'),
    h('div', { class: 'pf-signs' }, sign('Saha Sorumlusu', t.lead_name || ''), sign('Pilot', t.pilot_name || ''), sign('Şoför', drivers)),
    foot(company, `Yazdırma: ${now()}`)), `Saha görev formu ${t.code}`);
}

// ---------- Saha görev raporu: adım adım akış, görev tanımları, ekipman, masraf, imza ve uçuş raporları ----------
export function printTaskReport(r, company) {
  const t = r.task;
  const money = v => `${Number(v || 0).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;
  const num = (v, d = 1) => (v == null ? '—' : Number(v).toLocaleString('tr-TR', { maximumFractionDigits: d }));
  const dur = s => (s == null ? '—' : `${Math.floor(s / 3600) ? `${Math.floor(s / 3600)} sa ` : ''}${Math.floor((s % 3600) / 60)} dk ${Math.round(s % 60)} sn`);
  const qty = v => num(v, 2);
  const status = { BASLANGIC: 'Başlangıç', GOREVDE: 'Görevde', GOREV_TAMAMLANDI: 'Görev Tamamlandı', BASARISIZ: 'Başarısız',
    RAPOR_TAMAMLANDI: 'Rapor Tamamlandı', IPTAL: 'İptal' }[t.status] || t.status;
  const drivers = [...new Set([t.driver_name, ...(t.vehicles || []).map(v => v.driver_name)].filter(Boolean))].join(', ');
  const kv = rows => h('table', { class: 'pf-table' }, h('tbody', null, rows.filter(Boolean).map(([k, v]) => h('tr', null, h('th', null, k), h('td', null, v)))));
  const list = (cols, rows, empty, cls = '') => (rows.length
    ? h('table', { class: `pf-table pf-list ${cls}` }, h('thead', null, h('tr', null, cols.map(c => h('th', null, c)))), h('tbody', null, rows))
    : h('p', { class: 'pf-empty' }, empty));

  // 1) Adım adım akış (aşama başlıklarıyla)
  let phase = null, n = 0;
  const stepRows = [];
  for (const s of r.steps) {
    if (s.phase !== phase) { phase = s.phase; stepRows.push(h('tr', { class: 'tr-phase' }, h('td', { colspan: 4 }, { Hazırlık: 'HAZIRLIK', Saha: 'SAHADA — sahaya çıkıştan test tamamlanana kadar', Rapor: 'RAPOR' }[phase] || phase))); }
    stepRows.push(h('tr', null, h('td', { class: 'num' }, ++n), h('td', { class: 'nowrap' }, fmtDateTime(s.at)),
      h('td', null, h('b', null, s.text), s.detail ? h('div', { class: 'tr-detail' }, s.detail) : null), h('td', null, s.who || '—')));
  }

  const page1 = h('div', { class: 'pf-page pf-flow tr-report' },
    head(company, 'SAHA GÖREV RAPORU', [['Görev no', t.code], ['Tarih', fmtDate(t.started_at || t.created_at)], ['Durum', status]]),
    h('h2', { class: 'pf-h2' }, '1. Görev bilgileri'),
    kv([
      ['Sonuç', t.result ? (t.result === 'BASARILI' ? 'Başarılı' : 'Başarısız') : status],
      ['Görev yeri', t.location_name || '—'],
      ['Sahaya çıkış / bitiş', t.started_at ? `${fmtDateTime(t.started_at)} – ${t.finished_at ? fmtDateTime(t.finished_at) : 'devam ediyor'}` : 'Henüz başlamadı'],
      ['Uçaklar', t.flights.map(f => f.queue_no || f.order_code).join(', ') || '—'],
      ['Araç / yol', `${t.vehicle_plate || '—'}${t.distance_km != null ? ` · ${num(t.distance_km)} km` : ''}`],
      t.note ? ['Not', t.note] : null,
    ]),
    h('h2', { class: 'pf-h2' }, '2. Yapılan işlemler (adım adım)'),
    list(['#', 'Zaman', 'İşlem', 'Yapan'], stepRows, 'Kayıtlı işlem yok', 'tr-steps'),
    h('h2', { class: 'pf-h2' }, '3. Görev tanımları — sahada kim hangi görevi üstlendi'),
    list(['Ad Soyad', 'Görevi', 'Görev tanımı', 'İşlem'], r.people.map(p => h('tr', null,
      h('td', null, h('b', null, p.full_name)), h('td', null, p.roles.join(', ')),
      h('td', { class: 'tr-duty' }, p.duty_source === 'hr' ? h('ol', null, p.duties.map(d => h('li', null, d))) : p.duties.map(d => h('div', null, d))),
      h('td', { class: 'num' }, p.actions || '—'))), 'Görevli yok'),
    h('p', { class: 'tr-note' }, 'Görev tanımları İnsan Kaynakları’ndaki kişisel görev tanımından alınır (yalnızca Genel ve Kurum İçi maddeler); tanımı olmayan kişide rol açıklaması yazılır.'),
    h('h2', { class: 'pf-h2' }, '4. İş sağlığı ve güvenliği — KKD kontrolü'),
    h('p', { class: 'tr-note' }, 'Saha sorumlusu her kişinin KKD maddeleri için “Yaptı” ya da “Yapmadı” işaretler (sistemde işaretlenenler ☑ olarak basılır; boş kutular sahada elle doldurulur).'),
    ...(r.isg || []).map(p => h('div', { class: 'tr-isg' },
      h('div', { class: 'tr-isg-h' }, h('b', null, p.name), ` · ${p.roles.join(', ')}`, p.position ? ` · ${p.position}` : ''),
      p.emergency ? h('div', { class: 'tr-isg-em' }, h('b', null, 'Acil durum görevi: '), p.emergency) : null,
      p.trainings_expired?.length ? h('div', { class: 'tr-isg-em' }, h('b', null, 'Süresi dolan eğitim: '), p.trainings_expired.join(', ')) : null,
      p.ppe.length ? h('table', { class: 'pf-table pf-list tr-isg-t' },
        h('thead', null, h('tr', null, h('th', null, 'KKD'), h('th', null, 'Kullanım yeri / zamanı'), h('th', { class: 'tr-chk' }, 'Yaptı'), h('th', { class: 'tr-chk' }, 'Yapmadı'))),
        h('tbody', null, p.ppe.map(x => h('tr', null, h('td', null, x.name), h('td', null, x.usage || ''),
          h('td', { class: 'tr-chk' }, x.status === 'YAPTI' ? '☑' : '☐'), h('td', { class: 'tr-chk' }, x.status === 'YAPMADI' ? '☒' : '☐')))))
        : h('p', { class: 'pf-empty' }, 'KKD tanımlı değil.'))),
    h('h2', { class: 'pf-h2' }, `5. Ekipman listesi (${r.equipment.length} kalem)`),
    list(['#', 'Ekipman', 'Miktar', 'Not', 'Kontrol'], r.equipment.map((e, i) => h('tr', null,
      h('td', { class: 'num' }, i + 1), h('td', null, e.name), h('td', { class: 'num nowrap' }, `${qty(e.qty)} ${e.unit || ''}`),
      h('td', null, e.note || ''), h('td', { class: 'tr-check' }, '☐'))), 'Ekipman listesi boş'),
    h('h2', { class: 'pf-h2' }, `6. Masraflar (toplam ${money(t.expense_total)})`),
    list(['Tarih', 'Masrafı yapan', 'Kategori', 'Açıklama', 'Tutar'], (t.expenses || []).map(e => h('tr', null,
      h('td', null, fmtDate(e.spent_on)), h('td', null, e.spent_by_name || e.created_by_name || ''), h('td', null, e.category),
      h('td', null, e.description || ''), h('td', { class: 'num' }, money(e.amount)))), 'Masraf girilmedi'),
    h('div', { class: 'tr-approve' },
      h('p', null, `Yukarıda adım adım yazılan işlemlerin ${t.code} numaralı saha görevinde yapıldığını, görev tanımlarının ve ekipman listesinin doğru olduğunu onaylarım.`),
      h('div', { class: 'pf-signs tr-signs' }, sign('Saha Sorumlusu', t.lead_name || ''))),
    foot(company, `Pilot: ${t.pilot_name || '—'} · Şoför: ${drivers || '—'} · Yazdırma: ${now()}`));

  // 6) Uçuş raporları: her uçuş ayrı sayfada
  const flightPages = r.reports.map((fr, i) => {
    const s = fr.summary || {}, f = fr.flight;
    const has = fr.log && Object.keys(s).length;
    return h('div', { class: 'pf-page pf-flow tr-report tr-flight' },
      head(company, 'UÇUŞ RAPORU', [['Görev no', t.code], ['Uçak', f.queue_no || f.order_code], ['Uçuş', `${i + 1} / ${r.reports.length}`]]),
      kv([
        ['Ürün', `${f.product_name || '—'} ${f.product_serial || ''}`],
        ['Fırlatma sistemi', f.launch_text || '—'],
        ['Pilot', t.pilot_name || '—'],
        ['Uçuş logu', fr.log ? `${fr.log.file_name} · yükleyen ${fr.log.uploaded_by_name || '—'}` : 'Yüklenmedi'],
        f.note ? ['Uçuş notu', f.note] : null,
      ]),
      has ? [
        h('h2', { class: 'pf-h2' }, 'Uçuş özeti'),
        h('table', { class: 'pf-table tr-metrics' }, h('tbody', null,
          [[['Havada kalma', dur(s.flight_s)], ['Toplam kayıt', dur(s.duration_s)], ['Uçuş sayısı', s.flights ?? '—']],
            [['Kalkış', s.takeoff_utc ? fmtDateTime(new Date(s.takeoff_utc).toISOString()) : '—'], ['İniş', s.landing_utc ? fmtDateTime(new Date(s.landing_utc).toISOString()) : '—'], ['Mesafe', s.distance_m != null ? `${num(s.distance_m / 1000)} km` : '—']],
            [['Azami irtifa', s.alt_max != null ? `${num(s.alt_max)} m` : '—'], ['Ort. irtifa', s.alt_avg != null ? `${num(s.alt_avg)} m` : '—'], ['Eve azami uzaklık', s.max_home_m != null ? `${num(s.max_home_m / 1000, 2)} km` : '—']],
            [['Azami / ort. yer hızı', s.gs_max != null ? `${num(s.gs_max)} / ${num(s.gs_avg)} m/s` : '—'], ['Azami / ort. hava hızı', s.as_max != null ? `${num(s.as_max)} / ${num(s.as_avg)} m/s` : '—'], ['Rüzgâr ort. / azami', s.wind_avg != null ? `${num(s.wind_avg)} / ${num(s.wind_max)} m/s` : '—']],
            [['Batarya başlangıç / bitiş', s.bat_start_v != null ? `${num(s.bat_start_v, 2)} V / ${num(s.bat_end_v, 2)} V` : '—'], ['Harcanan enerji', s.bat_used_mah != null ? `${num(s.bat_used_mah, 0)} mAh · ${num(s.bat_used_wh)} Wh` : '—'], ['Kalan batarya', s.bat_end_pct != null ? `%${s.bat_end_pct}` : '—']],
            [['GPS uydu (min / ort.)', s.sats_min != null ? `${s.sats_min} / ${num(s.sats_avg)}` : '—'], ['Titreşim (azami)', Array.isArray(s.vibe_max) ? s.vibe_max.map(v => num(v)).join(' / ') : '—'], ['Yazılım / kart', `${s.firmware || '—'} · ${s.board || ''}`]],
          ].map(row => h('tr', null, row.map(([k, v]) => [h('th', null, k), h('td', null, v)]))))),
        h('h2', { class: 'pf-h2' }, 'Bulgular'),
        fr.findings.length ? h('ul', { class: 'tr-findings' }, fr.findings.map(x => h('li', { class: x.level }, h('b', null, `${x.level === 'bad' ? '✖' : x.level === 'warn' ? '⚠' : '✓'} ${x.title}`), x.detail ? ` — ${x.detail}` : ''))) : h('p', { class: 'pf-empty' }, 'Olumsuz bulgu yok.'),
      ] : h('p', { class: 'pf-empty' }, 'Bu uçuş için analiz edilmiş uçuş logu yok.'),
      fr.notes.length ? [h('h2', { class: 'pf-h2' }, 'Uçuş notları'),
        list(['Tür', 'Not', 'Yazan', 'Zaman'], fr.notes.map(nt => h('tr', null, h('td', null, nt.kind), h('td', null, nt.body), h('td', null, nt.created_by_name || ''), h('td', { class: 'nowrap' }, fmtDateTime(nt.created_at)))), '')] : null,
      fr.videos ? h('p', { class: 'small' }, `Bu uçuşa ait ${fr.videos} video / fotoğraf sistemde kayıtlı.`) : null,
      foot(company, `${t.code} · Uçuş raporu ${i + 1}/${r.reports.length}`));
  });
  printPage(h('div', null, page1, ...flightPages), `Saha görev raporu ${t.code}`);
}
