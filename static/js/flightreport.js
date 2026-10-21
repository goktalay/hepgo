// Logolu, çok sayfalı uçuş raporu (ekranda A4 sayfalar, yazdırmada sayfa sonlu).
import { clock, lineChart, trackMap } from './chart.js';
import { printPage } from './print.js';
import { TASK_STATES } from './status.js';
import { fmtDateTime, h } from './ui.js';

const LEVEL = { ok: 'Uygun', warn: 'Dikkat', bad: 'Kritik' };
const C = { blue: '#1d4f91', sky: '#2b8fd6', green: '#1e7b3a', red: '#b42318', orange: '#c26a00', purple: '#6b3fc2', gray: '#8a94a6' };

const n = (v, d = 1, unit = '') => (v === null || v === undefined ? '—' : `${Number(v).toLocaleString('tr-TR', { maximumFractionDigits: d })}${unit}`);
const dur = s => (s === null || s === undefined ? '—' : clock(s));
const kmh = v => (v === null || v === undefined ? '—' : `${n(v, 1)} m/s (${n(v * 3.6, 0)} km/sa)`);
const bytes = b => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const localTime = iso => (iso ? fmtDateTime(iso) : '—');

function head(company, lines) {
  return h('header', { class: 'pf-head' },
    h('img', { class: 'pf-logo', src: '/static/img/logo.png', alt: company }),
    h('div', { class: 'pf-title' }, h('h1', null, 'UÇUŞ RAPORU'),
      lines.filter(Boolean).map(([k, v]) => h('div', null, `${k}: `, h('b', null, v)))));
}

function page(company, meta, title, ...content) {
  return h('section', { class: 'fr-page' },
    head(company, meta),
    h('div', { class: 'fr-body' }, content),
    h('footer', { class: 'pf-foot' }, h('span', null, company),
      h('span', null, `${title} · Oluşturma: ${fmtDateTime(new Date().toISOString())}`)));
}

const section = (title, ...c) => h('div', { class: 'fr-section' }, h('h2', null, title), c);
const kv = rows => h('table', { class: 'pf-table fr-kv' }, h('tbody', null,
  rows.filter(Boolean).map(([k, v]) => h('tr', null, h('th', null, k), h('td', null, v)))));

// MAVLink telemetri kaydında (.tlog) karşılığı olmayan bölümler (summary.missing; app/tlog.py SERI_ADI ile aynı anahtarlar)
const TLOG_MISSING = { alt: 'irtifa', gs: 'yer hızı', as: 'hava hızı (sensör yok)', volt: 'batarya voltajı', curr: 'batarya akımı', vx: 'titreşim (VIBRATION)',
  roll: 'tutum (ATTITUDE)', droll: 'istenen tutum (NAV_CONTROLLER_OUTPUT)', sats: 'GPS uydu sayısı', hdop: 'GPS HDop', wind: 'rüzgâr (WIND)', thr: 'gaz',
  errors: 'hata (ERR) ve olay (EV) kayıtları', energy: 'tüketilen enerji (BATTERY_STATUS)', track: 'konum', messages: 'sistem mesajları (STATUSTEXT)',
  modes: 'uçuş modları' };

export function buildFlightReport(log, company) {
  const a = log.analysis, s = a.summary, S = a.series, task = log.task;
  const tlog = s.source === 'tlog';
  const NONE = tlog ? 'Telemetri kaydında (.tlog) bu veri yok' : undefined;
  const flightDate = s.takeoff_utc || s.start_utc;
  const meta = [
    ['Uçuş tarihi', flightDate ? fmtDateTime(flightDate).slice(0, 10) : '—'],
    ['Rapor no', `UR-${String(log.id).padStart(4, '0')}`],
    task ? ['Saha görevi', task.code] : null,
  ];
  const bands = a.flying;

  const kpi = (label, value, sub) => h('div', { class: 'fr-kpi' }, h('span', null, label), h('b', null, value), sub ? h('small', null, sub) : null);
  const findings = h('ul', { class: 'fr-findings' }, a.findings.map(f =>
    h('li', { class: f.level }, h('span', { class: 'lvl' }, LEVEL[f.level]), h('div', null, h('b', null, f.title), h('div', null, f.detail)))));

  const info = kv([
    ['Uçak', log.aircraft || '—'],
    task ? ['Saha sorumlusu', task.lead_name || '—'] : null,
    task ? ['Pilot', task.pilot_name || log.pilot || '—'] : ['Pilot / ekip', log.pilot || '—'],
    log.flight ? ['Fırlatma sistemi', log.flight.launch_text || '—'] : null,
    task?.vehicle_plate ? ['Araç plakası', task.vehicle_plate] : null,
    ['Uçuş yeri', log.location || (s.home ? `${s.home.lat.toFixed(5)}, ${s.home.lng.toFixed(5)}` : '—')],
    ['Otopilot yazılımı', s.firmware || (tlog ? s.vehicle : '—')],
    tlog ? ['Log biçimi', `MAVLink telemetri kaydı (.tlog) · sistem ${s.sysid}${s.other_systems?.length ? ` (kayıttaki diğer sistemler: ${s.other_systems.join(', ')})` : ''}`] : null,
    ['Uçuş kartı', s.board || '—'],
    ['Kalkış / iniş', `${localTime(s.takeoff_utc)} – ${localTime(s.landing_utc)}`],
    task ? ['Görev sonucu', `${TASK_STATES[task.status]?.label || task.status}${task.result ? ` (${task.result === 'BASARILI' ? 'Başarılı' : 'Başarısız'})` : ''}`] : null,
    ['Log dosyası', `${log.file_name} · ${bytes(log.size)}`],
    log.note ? ['Not', log.note] : null,
  ]);

  const p1 = [
    h('div', { class: 'fr-kpis' },
      kpi('Uçuş süresi', dur(s.flight_s), `Kurulu: ${dur(s.armed_s)}`),
      kpi('Toplam mesafe', s.distance_m >= 1000 ? `${n(s.distance_m / 1000, 2)} km` : `${n(s.distance_m, 0)} m`, `Evden en uzak: ${n(s.max_home_m, 0)} m`),
      kpi('Maks. irtifa', n(s.alt_max, 0, ' m'), `Ortalama: ${n(s.alt_avg, 0, ' m')}`),
      kpi('Maks. yer hızı', n(s.gs_max, 1, ' m/s'), `${n((s.gs_max || 0) * 3.6, 0)} km/sa`),
      kpi('Maks. hava hızı', n(s.as_max, 1, ' m/s'), s.as_avg ? `Ortalama: ${n(s.as_avg, 1)} m/s` : 'Hava hızı sensörü yok'),
      kpi('Tüketilen enerji', n(s.bat_used_mah, 0, ' mAh'), s.bat_used_wh ? `${n(s.bat_used_wh, 1)} Wh` : null)),
    ...(log.fuel ? [
      h('div', { class: 'fr-kpis fr-kpis-fuel' },
        kpi('Toplam yakılan yakıt', n(log.fuel.total_l, 2, ' L'), `${n(log.fuel.start_l, 1)} → ${n(log.fuel.end_l, 1)} L`),
        kpi('Ortalama tüketim', n(log.fuel.avg_lph, 2, ' L/sa'), 'motor çalışırken'),
        kpi('Maks. tüketim', n(log.fuel.peak_lph, 2, ' L/sa')),
        kpi('Min. tüketim', n(log.fuel.min_lph, 2, ' L/sa'), 'motor çalışırken'),
        kpi('Uçuş saatine göre', n(log.fuel.lph_flight, 2, ' L/sa')),
        kpi('Km başına', n(log.fuel.l_per_km, 3, ' L/km'), log.fuel.peak_thrust_kg ? `Maks. itki ${n(log.fuel.peak_thrust_kg, 1)} kg` : null)),
      log.fuel.series?.length ? h('div', { class: 'fr-charts fr-charts-fuel' },
        lineChart({ title: 'Yakıt tüketimi', unit: 'L/sa', bands, series: [{ label: 'Anlık tüketim', color: C.green, data: log.fuel.series.map(r => [r[0], r[1]]) }] }),
        lineChart({ title: 'Yakılan yakıt (birikimli) ve itki', unit: 'L · kg', bands, series: [
          { label: 'Yakılan (L)', color: C.blue, data: log.fuel.series.map(r => [r[0], r[2]]) },
          { label: 'İtki (kg)', color: C.orange, dash: '4 3', data: log.fuel.series.map(r => [r[0], r[3]]) }] })) : null,
    ] : []),
    tlog ? h('p', { class: 'fr-note fr-tlog-note' }, 'Kaynak MAVLink telemetri kaydı (.tlog): otopilotun yer istasyonuna gönderdiği seyreltilmiş akış (genelde 1–10 Hz); DataFlash (.bin) loguna göre daha az ayrıntı içerir.',
      s.missing?.length ? ` Bu kayıtta bulunmayan: ${s.missing.map(k => TLOG_MISSING[k] || k).join(', ')}.` : '') : null,
    h('div', { class: 'fr-two' }, section('Uçuş bilgileri', info), trackMap(a.track, s.home, { height: 330, empty: tlog ? 'Telemetri kaydında (.tlog) GPS konumu yok' : undefined })),
    section('Değerlendirme', findings),
  ];

  const charts = [
    lineChart({ empty: NONE, title: 'İrtifa (eve göre)', unit: 'm', bands, series: [{ label: 'İrtifa', color: C.blue, data: S.alt }] }),
    lineChart({ empty: NONE, title: 'Hız', unit: 'm/s', bands, series: [
      { label: 'Yer hızı', color: C.blue, data: S.gs }, { label: 'Hava hızı', color: C.orange, data: S.as }] }),
    lineChart({ empty: NONE, title: 'Batarya voltajı', unit: 'V', bands, zero: false, series: [{ label: 'Voltaj', color: C.green, data: S.volt }] }),
    lineChart({ empty: NONE, title: 'Batarya akımı', unit: 'A', bands, series: [{ label: 'Akım', color: C.red, data: S.curr }] }),
    lineChart({ empty: NONE, title: 'Yatış (roll)', unit: '°', bands, zero: false, series: [
      { label: 'Gerçekleşen', color: C.blue, data: S.roll }, { label: 'İstenen', color: C.orange, data: S.droll, dash: '4 3' }] }),
    lineChart({ empty: NONE, title: 'Yunuslama (pitch)', unit: '°', bands, zero: false, series: [
      { label: 'Gerçekleşen', color: C.blue, data: S.pitch }, { label: 'İstenen', color: C.orange, data: S.dpitch, dash: '4 3' }] }),
    lineChart({ empty: NONE, title: 'Titreşim', unit: 'm/s²', bands, series: [
      { label: 'X', color: C.blue, data: S.vx }, { label: 'Y', color: C.green, data: S.vy }, { label: 'Z', color: C.purple, data: S.vz }],
      thresholds: [{ value: 30, color: C.orange, label: 'Dikkat 30' }, { value: 60, color: C.red, label: 'Kritik 60' }] }),
    lineChart({ empty: NONE, title: 'GPS', unit: 'uydu / HDop', bands, series: [
      { label: 'Uydu sayısı', color: C.blue, data: S.sats }, { label: 'HDop', color: C.red, data: S.hdop }] }),
    lineChart({ empty: NONE, title: 'Tahmini rüzgâr hızı', unit: 'm/s', bands, series: [{ label: 'Rüzgâr', color: C.sky, data: S.wind }] }),
    lineChart({ empty: NONE, title: 'Gaz (throttle)', unit: '%', bands, series: [{ label: 'Gaz', color: C.gray, data: S.thr }] }),
  ];
  const p2 = [h('p', { class: 'fr-note' }, 'Gri arka planlı bölgeler havada geçen süreyi gösterir. Zaman ekseni log başlangıcına göredir (dk:sn).'),
    h('div', { class: 'fr-charts' }, charts)];

  const details = h('div', { class: 'fr-two' },
    section('Uçuş ve performans', kv([
      ['Log süresi', dur(s.duration_s)], ['Kurulu (ARM) süre', dur(s.armed_s)], ['Havada geçen süre', dur(s.flight_s)],
      ['Uçuş sayısı', s.flights], ['Kalkış / iniş (log zamanı)', `${dur(s.takeoff_t)} / ${dur(s.landing_t)}`],
      ['Maks. tırmanma / alçalma', `${n(s.climb_max, 1)} / ${n(s.sink_max, 1)} m/s`],
      ['Yer hızı maks. / ort.', `${kmh(s.gs_max)} / ${n(s.gs_avg, 1)} m/s`],
      ['Maks. yatış / yunuslama', `${n(s.roll_max, 0)}° / ${n(s.pitch_max, 0)}°`],
      ['Yatış / yunuslama takip hatası (RMS)', `${n(s.roll_err_rms, 1)}° / ${n(s.pitch_err_rms, 1)}°`],
      ['Ortalama gaz', n(s.thr_avg, 0, ' %')],
    ])),
    section('Batarya, GPS ve ortam', kv([
      ['Voltaj başlangıç / bitiş', `${n(s.bat_start_v, 2)} V / ${n(s.bat_end_v, 2)} V`],
      ['En düşük voltaj', n(s.bat_min_v, 2, ' V')],
      ['Akım maks. / ort.', `${n(s.bat_max_a, 1)} A / ${n(s.bat_avg_a, 1)} A`],
      ['Kalan kapasite', s.bat_end_pct === null || s.bat_end_pct === undefined ? '—' : `%${s.bat_end_pct}`],
      ['Uydu en az / ort.', `${n(s.sats_min, 0)} / ${n(s.sats_avg, 1)}`], ['En yüksek HDop', n(s.hdop_max, 2)],
      ['Titreşim maks. X / Y / Z', s.vibe_max.map(v => n(v, 1)).join(' / ') + ' m/s²'], ['İvmeölçer doygunluğu', n(s.clips, 0)],
      ['Rüzgâr ort. / maks.', `${n(s.wind_avg, 1)} / ${n(s.wind_max, 1)} m/s${s.wind_dir !== null && s.wind_dir !== undefined ? ` · ${s.wind_dir}° yönünden` : ''}`],
      ['Parametre sayısı', n(s.params, 0)],
    ])));

  const table = (cols, rows, empty) => rows.length
    ? h('table', { class: 'pf-table fr-list' }, h('thead', null, h('tr', null, cols.map(c => h('th', null, c)))),
      h('tbody', null, rows))
    : h('div', { class: 'fr-empty' }, empty);

  const p3 = [
    details,
    section('Uçuş modları', table(['Başlangıç', 'Mod', 'Süre'],
      a.modes.map(m => h('tr', null, h('td', null, clock(m.t)), h('td', null, h('b', null, m.name)), h('td', null, clock(m.dur)))),
      tlog ? 'Telemetri kaydında HEARTBEAT modu yok' : 'Mod değişikliği kaydı yok')),
    section('Hatalar ve olaylar', table(['Zaman', 'Tür', 'Açıklama'], [
      ...a.errors.map(e => ({ t: e.t, row: h('tr', { class: e.resolved ? '' : 'bad' }, h('td', null, clock(e.t)), h('td', null, 'Hata'),
        h('td', null, `${e.text} — kod ${e.code}${e.resolved ? ' (giderildi)' : ''}`)) })),
      ...a.events.map(e => ({ t: e.t, row: h('tr', null, h('td', null, clock(e.t)), h('td', null, 'Olay'), h('td', null, e.text)) })),
    ].sort((x, y) => x.t - y.t).map(r => r.row), tlog ? 'Telemetri kaydında (.tlog) ERR/EV kaydı yok; ARM/DISARM geçişi de görülmedi' : 'Kayıtlı hata veya olay yok')),
    section('Sistem mesajları', table(['Zaman', 'Mesaj'],
      a.messages.map(m => h('tr', { class: m.warn ? 'warn' : '' }, h('td', null, clock(m.t)), h('td', null, m.text))),
      'Sistem mesajı yok')),
  ];

  return [
    page(company, meta, 'Özet', p1),
    page(company, meta, 'Uçuş verileri', p2),
    page(company, meta, 'Ayrıntılar', p3),
  ];
}

export function printFlightReport(log, company) {
  printPage(h('div', { class: 'fr-doc' }, buildFlightReport(log, company)), `Uçuş raporu ${log.file_name}`);
}
