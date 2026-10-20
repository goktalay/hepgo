// Araçlar: yazılımdaki yardımcı araçlar. İlk araç: Uçuş Logu Analizi (saha görevinden bağımsız).
import { api, uploadLarge } from '../api.js';
import { render3D } from './replay3d.js';
import { logOrigin, originBadge } from './flightlog_origin.js';
import { renderPlanner } from './planner.js';
import { renderProductionErrors } from './prod_errors.js';
import { renderNetscan } from './netscan.js';
import { buildFlightReport, printFlightReport } from '../flightreport.js';
import { icons } from '../icons.js';
import {
  clear, confirmDialog, every, field, fmtDateTime, h, localUploadNotice, matches, moduleToolbar, pageHead, pref, progressBar, selectInput, setPref, statStrip,
  svgIcon, t, toast, uploadPanel,
  toastError,
} from '../ui.js';
import { clock } from '../chart.js';

// Araç listesi; yeni araç eklemek için bir satır yeterli.
const TOOLS = [
  { key: 'flight-log', title: 'Uçuş Logu Analizi', icon: 'flightlog', desc: 'ArduPilot .bin / .log dosyasından uçuş raporu' },
  { key: 'planner', title: 'Üretim Planlayıcı', icon: 'planner', desc: 'Mamul ve adet seçin; yazıcılara yükleme sırası (Gantt)' },
  { key: 'production-errors', title: 'Üretim Hataları', icon: 'warning', desc: 'Parçalara girilen hata kayıtları: hata kodu, açıklama, resim',
    modules: ['production', 'printers', 'orders'] },
  { key: 'network', title: 'Ağ Tarayıcı', icon: 'network', desc: 'Sunucunun ağındaki bilgisayarlar: IP, bilgisayar adı, MAC, üretici', modules: ['admin'] },
  { key: 'terminal', title: 'Terminal', icon: 'terminal', desc: 'Sistem sahibi için yerel kabuk (SSH benzeri) — sahada olmadan komut çalıştırın', master: true },
  // Master Tool ailesi — web sürümleri (tool_<ad>.js; arka uç app/routers/tools_<ad>.py). Yetki: Araçlar modülü.
  { key: 'ssh', title: 'SSH Master', icon: 'terminal', desc: 'Masaüstü SSH Master\'ın web sürümü: bağlantı kartları, bölünebilir konsollar, SFTP paneli, kısayollar', mt: 'tool_sshmaster' },
  { key: 'ftp', title: 'FTP Masters', icon: 'folderOpen', desc: 'Masaüstü FTP Masters\'ın web sürümü: FTP / FTPS / SFTP siteleri, iki panel, aktarım kuyruğu, hız sınırı', mt: 'tool_ftpmaster' },
  // SQL / Notepad / Convert Master: masaüstü uygulamaların orijinal arayüzleri (static/mt/<uygulama>) aynı kökenli iframe'de; tool_mtframe.js
  { key: 'sql', title: 'SQL Master', icon: 'reports', desc: 'Bağlantı kütüphanesi, nesne ağacı, SQL editörü, görsel sorgu oluşturucu (SQLite · MySQL · PostgreSQL)', mt: 'tool_mtframe' },
  { key: 'notepad', title: 'Notepad Master', icon: 'note', desc: 'SSH/SFTP, FTP ve sunucudaki klasörlerde dosya düzenleyen kod editörü (Monaco)', mt: 'tool_mtframe' },
  { key: 'convert', title: 'Convert Master', icon: 'refresh', desc: 'Resim, video ve ses dönüştürme projeleri; önizleme, kuyruk ve ilerleme', mt: 'tool_mtframe' },
  { key: 'volfai', title: 'VOLFAI', icon: 'apps', desc: 'Volfied’in dokunmatik yeniden yapımı — HEPGO içinde, ilerleme hesabınızda', mt: 'tool_volfai' },
];
// Kullanıcının görebileceği araçlar (modül koşulu olanlar o modüllerden birine sahip olana; master koşulu yalnız sistem sahibine)
export const visibleTools = ctx => TOOLS.filter(t => (t.master ? (t.key === 'terminal' ? ctx.user.console : ctx.user.master) : (!t.modules || t.modules.some(m => ctx.user.modules.includes(m)))));

export async function render(view, params, ctx) {
  if (params[0] === 'planner') return renderPlanner(view, ctx);
  if (params[0] === 'production-errors') return renderProductionErrors(view, ctx);
  if (params[0] === 'network') return ctx.user.modules.includes('admin') ? renderNetscan(view) : clear(view, h('div', { class: 'card empty' }, 'Bu araç yalnızca Sistem Yöneticisine açıktır.'));
  if (params[0] === 'terminal') { const con = await import('./console.js'); return con.render(view, params.slice(1), ctx); }
  const mt = TOOLS.find(t => t.key === params[0] && t.mt);   // Master Tool web sürümleri: tembel yüklenen ayrı ES modülleri
  if (mt) { const m = await import(`./${mt.mt}.js`); return m.render(view, params.slice(1), ctx); }
  if (params[0] === 'flight-log') {
    if (params[2] === '3d') return render3D(view, Number(params[1]), `#/tools/flight-log/${params[1]}`);
    return params[1] ? renderReportView(view, Number(params[1]), '#/tools/flight-log', ctx) : renderFlightLogs(view, ctx);
  }
  // Araçlar ana sayfası: yalnızca araç kartları (bilgilendirme ve arama yok)
  const grid = h('div', { class: 'modules', style: { justifyContent: 'start' } }, visibleTools(ctx).map(t =>
    h('a', { class: 'module-btn', href: `#/tools/${t.key}` },
      h('span', { class: 'ico' }, svgIcon(icons[t.icon])),
      h('span', null, t.title),
      h('small', { class: 'muted', style: { textAlign: 'center' } }, t.desc))));
  clear(view, pageHead('Araçlar', { back: '#/' }), grid);
}

function logStats(logs, toolCount) {
  const done = logs.filter(l => l.status === 'TAMAM');
  const month = new Date().toISOString().slice(0, 7);
  const air = done.reduce((a, l) => a + (l.flight_s || 0), 0);
  return [
    { icon: 'flightlog', label: 'Analiz edilen log', value: logs.length },
    { icon: 'reports', label: 'Rapor hazır', value: done.length, tone: 'ok' },
    { icon: 'warning', label: 'Hatalı log', value: logs.filter(l => l.status === 'HATA').length, tone: logs.some(l => l.status === 'HATA') ? 'alert' : '' },
    { icon: 'calendar', label: 'Toplam uçuş süresi', value: clock(air), sub: 'hazır raporlarda' },
  ];
}

const LOG_STATES = {
  ISLENIYOR: ['blue', 'Analiz ediliyor'],
  TAMAM: ['green', 'Hazır'],
  HATA: ['red', 'Hata'],
};
export function logBadge(status) {
  const [color, label] = LOG_STATES[status] || ['gray', status || '—'];
  return h('span', { class: `badge ${color}` }, label);
}

// ---------- Uçuş Logu Analizi: yükleme + geçmiş ----------
async function renderFlightLogs(view, ctx) {
  const file = h('input', { class: 'input', type: 'file', accept: '.bin,.BIN,.log,.LOG', style: { height: 'auto', padding: '6px' } });
  const aircraft = h('input', { class: 'input', placeholder: 'Ör. CYZ-0001' });
  const pilot = h('input', { class: 'input', placeholder: 'Pilot adı' });
  const place = h('input', { class: 'input', placeholder: 'Ör. Test sahası' });
  const note = h('input', { class: 'input', placeholder: 'İsteğe bağlı' });
  const progress = uploadPanel();
  const go = h('button', { class: 'btn primary' }, svgIcon(icons.upload), 'Yükle ve Analiz Et');
  const list = h('div');
  const stats = statStrip();
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Dosya, uçak, pilot, yer ara…', style: { width: '240px' } });
  const st = selectInput(Object.entries(LOG_STATES).map(([k, v]) => [k, v[1]]), { all: 'Tüm durumlar' });
  const src = selectInput([['tools', 'Araçlar'], ['field', 'Saha görevi']], { all: 'Tüm bağlamlar' });
  // Kaynak: gerçek uçuş / simülasyon (SITL) — süzgeç + sütun başlığına tıklayarak sıralama (tercih saklanır)
  const org = selectInput([['REAL', 'Gerçek uçuş'], ['SIM', 'Simülasyon']], { all: 'Tüm kaynaklar (gerçek + simülasyon)', value: pref('flightlogs.origin', '') });
  let sort = pref('flightlogs.sort', '-uploaded');
  let logs = [];

  go.addEventListener('click', async () => {
    const f = file.files[0];
    if (!f) return toastError(new Error('Log dosyası seçin (.bin veya .log)'));
    const meta = Object.fromEntries([['aircraft', aircraft], ['pilot', pilot], ['location', place], ['note', note]]
      .map(([k, i]) => [k, i.value.trim() || null]));
    go.disabled = true;
    const signal = progress.start();
    try {
      // Büyük loglar parça parça gönderilir; "Yüklemeyi İptal Et" ile durdurulabilir
      const uploadId = await uploadLarge(f, 'flightlogs', pct => progress.set(t('{name} yükleniyor…', { name: f.name }), pct), signal);
      const { id } = await api.post('/api/tools/flight-logs/chunked', { upload_id: uploadId, ...meta });
      toast('Log yüklendi, analiz ediliyor');
      location.hash = `#/tools/flight-log/${id}`;
    } catch (err) {
      if (err.canceled) toast('Yükleme iptal edildi'); else toastError(err);
    } finally {
      go.disabled = false;
      progress.done();
    }
  });

  const SORT_KEY = {
    file: l => String(l.file_name || '').toLocaleLowerCase('tr'), origin: l => (logOrigin(l) === 'REAL' ? 0 : 1),
    flight: l => Date.parse(l.takeoff_utc || l.start_utc || '') || 0, air: l => Number(l.flight_s) || 0, uploaded: l => Date.parse(l.uploaded_at || '') || l.id,
  };
  const th = (label, key) => {
    if (!key) return h('th', null, label);
    const on = sort.replace('-', '') === key, desc = sort.startsWith('-');
    return h('th', { class: `sortable ${on ? 'on' : ''}`, title: t('Sıralamak için tıklayın'), onclick: () => { sort = on && !desc ? `-${key}` : key; setPref('flightlogs.sort', sort); draw(); } },
      t(label), on ? (desc ? ' ▼' : ' ▲') : '');
  };
  const draw = () => {
    stats.set(logStats(logs, 0));
    const rows = logs.filter(l => (!st.value || l.status === st.value) &&
      (!src.value || (src.value === 'field') === !!l.task_id) && (!org.value || logOrigin(l) === org.value) &&
      matches(q.value, l.file_name, l.aircraft, l.pilot, l.location, l.note, l.task_code, l.vehicle, l.uploaded_by_name));
    const kf = SORT_KEY[sort.replace('-', '')], dir = sort.startsWith('-') ? -1 : 1;
    if (kf) rows.sort((a, b) => { const x = kf(a), y = kf(b); return (x < y ? -1 : x > y ? 1 : b.id - a.id) * dir; });
    clear(list, rows.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, th('Log dosyası', 'file'), th('Kaynak', 'origin'), th('Uçak'), th('Pilot'), th('Uçuş tarihi', 'flight'), th('Havada', 'air'), th('Bağlam'), th('Durum'), th('Yükleyen', 'uploaded'), th(''))),
      h('tbody', null, rows.map(l => h('tr', { class: l.status === 'TAMAM' ? 'click' : '', onclick: e => {
        if (l.status === 'TAMAM' && !e.target.closest('button')) location.hash = `#/tools/flight-log/${l.id}`;
      } },
        h('td', null, h('b', null, l.file_name), h('div', { class: 'small muted' }, l.vehicle || '')),
        h('td', null, originBadge(l)),
        h('td', null, l.aircraft || '—'),
        h('td', { style: { whiteSpace: 'normal' } }, l.pilot || '—'),
        h('td', null, fmtDateTime(l.takeoff_utc || l.start_utc)),
        h('td', null, l.flight_s != null ? clock(l.flight_s) : '—'),
        h('td', null, l.task_code ? t('Saha görevi {code}', { code: l.task_code }) : 'Araçlar'),
        h('td', null, logBadge(l.status), l.error ? h('div', { class: 'small', style: { color: 'var(--danger)', whiteSpace: 'normal', maxWidth: '260px' } }, l.error) : null),
        h('td', { class: 'muted' }, l.uploaded_by_name || '—', h('div', { class: 'small' }, fmtDateTime(l.uploaded_at))),
        h('td', { class: 'num' },
          l.status === 'TAMAM' ? h('a', { class: 'btn sm', href: `#/tools/flight-log/${l.id}` }, 'Raporu Aç') : null,
          !l.task_id && l.status !== 'ISLENIYOR' ? h('button', { class: 'btn sm ghost', onclick: () => remove(l, load) }, 'Sil') : null))))))
      : h('div', { class: 'card empty' }, logs.length ? 'Filtreye uyan log yok' : 'Henüz analiz edilmiş uçuş logu yok'));
  };
  const load = async () => { logs = await api.get('/api/tools/flight-logs'); draw(); };
  q.addEventListener('input', draw);
  st.addEventListener('change', draw);
  src.addEventListener('change', draw);
  org.addEventListener('change', () => { setPref('flightlogs.origin', org.value); draw(); });

  clear(view,
    pageHead('Uçuş Logu Analizi', { back: '#/tools', sub: 'Uçuş logu (.bin/.log) → rapor' }),
    stats,
    h('div', { class: 'card upload-card' }, ctx.meta.remote ? localUploadNotice(ctx.meta, 'Uçuş logu') : [
      h('div', { class: 'row' }, field('Log dosyası', file, 'En fazla 2 GB'), field('Uçak', aircraft), field('Pilot', pilot)),
      h('div', { class: 'row' }, field('Uçuş yeri', place), field('Not', note),
        h('div', { class: 'field', style: { flex: '0 0 auto' } }, go)),
      progress]),
    h('h2', { style: { fontSize: '16px', margin: '4px 0 10px' } }, 'Analiz geçmişi'),
    h('div', { class: 'filters' }, q, org, st, src),
    list);
  await load();
  every(5000, () => load().catch(() => {}));
}

async function remove(l, reload) {
  if (!await confirmDialog('Uçuş logunu sil', t('{name} ve raporu silinsin mi?', { name: l.file_name }), { okLabel: 'Sil', danger: true })) return;
  try {
    await api.del(`/api/tools/flight-logs/${l.id}`);
    toast('Silindi');
    reload();
  } catch (err) { toastError(err); }
}

// ---------- Rapor görünümü (Araçlar ve Saha Yönetimi ortak) ----------
export async function renderReportView(view, id, back, ctx) {
  const log = await api.get(`/api/flight-logs/${id}`);
  const title = t('Uçuş Raporu — {name}', { name: log.file_name });
  if (log.status === 'ISLENIYOR') {
    clear(view, pageHead(title, { back }),
      h('div', { class: 'card empty' }, h('b', null, 'Log analiz ediliyor…'),
        h('div', { class: 'small', style: { marginTop: '6px' } }, 'Büyük dosyalarda birkaç dakika sürebilir. Sayfa hazır olunca kendiliğinden açılır.')));
    every(3000, async () => {
      const l = await api.get(`/api/flight-logs/${id}`).catch(() => null);
      if (l && l.status !== 'ISLENIYOR') window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    return;
  }
  if (log.status === 'HATA') {
    clear(view, pageHead(title, { back }), h('div', { class: 'card card-pad' },
      h('div', { class: 'alert err', style: { margin: 0 } }, h('b', null, 'Log analiz edilemedi. '), log.error || '')));
    return;
  }
  clear(view,
    pageHead('Uçuş Raporu', { back, sub: log.file_name }),
    moduleToolbar(
      h('a', { class: 'btn', href: `${location.hash.replace(/\/3d$/, '')}/3d` }, '3B Oynat'),
      h('button', { class: 'btn primary', onclick: () => printFlightReport(log, ctx.meta.company) }, 'Yazdır / PDF')),
    h('div', { class: 'fr-doc' }, buildFlightReport(log, ctx.meta.company)));
}
