// İnsan Kaynakları: personel (her kullanıcı aynı zamanda personeldir), iş başvuruları, özlük dosyaları, sözleşmeler ve izinler.
// Personel Ekle → iş başvurusu (TC, kaynak, CV); kabul edilince personel olur (görev, maaş, resmi işe başlama).
// Zorunlu özlük dosyası ya da sözleşmesi eksik olan personel kırmızı çerçeveyle gösterilir.
import { setListExport } from '../listexport.js';
import { idCard } from '../idcard.js';
import { api, fileUrl, upload } from '../api.js';
import { personPane } from './finmoves.js';
import { emailsInput,
  clear, confirmDialog, field, fmtDate, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, pref, segmented, selectInput, setPref, statStrip, t, toast, toastError, periodFilter
} from '../ui.js';

const LEAVE_STATUS = { BEKLIYOR: ['Onay bekliyor', 'yellow'], ONAYLANDI: ['Onaylandı', 'green'], REDDEDILDI: ['Reddedildi', 'red'], IPTAL: ['Geri çekildi', 'gray'] };
const EMP_STATUS = { BASVURU: ['İş başvurusu', 'blue'], REDDEDILDI: ['Reddedildi', 'red'], AKTIF: ['Aktif', 'green'], AYRILDI: ['Ayrıldı', 'gray'] };
const LEAVE_KINDS = { UCRETLI: 'Ücretli izin', UCRETSIZ: 'Ücretsiz izin' };
const badge = (map, k) => h('span', { class: `badge ${(map[k] || [])[1] || 'gray'}` }, (map[k] || [k])[0]);
const money = v => (v || v === 0 ? Number(v).toLocaleString('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 2 }) : '—');
const today = () => new Date().toLocaleDateString('sv');
const dateIn = (value = '', attrs = {}) => h('input', { class: 'input', type: 'date', value: value || '', ...attrs });
const days = (a, b) => (a && b ? Math.round((new Date(b) - new Date(a)) / 86400000) + 1 : null);
const range = (a, b) => (a ? t('{a} – {b} ({n} gün)', { a: fmtDate(a), b: fmtDate(b), n: days(a, b) }) : '—');
let META = null;

// treeSpider (organizasyon şeması) tembel yüklenir: ~1 MB bundle yalnızca şema sekmesi açılınca indirilir.
let _TreeSpider = null;
async function loadTreeSpider() {
  if (_TreeSpider) return _TreeSpider;
  if (!document.querySelector('link[data-treespider]')) {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = '/static/vendor/treespider/treeSpider.css'; l.dataset.treespider = '1';
    document.head.append(l);
  }
  const mod = await import('/static/vendor/treespider/treeSpider.bundle.min.js');
  _TreeSpider = mod.default;
  return _TreeSpider;
}

// Fotoğrafı olmayan düğümler için baş harf (ya da yer tutucu için +) içeren yuvarlak avatar — data URI.
function initialsAvatar(name, placeholder) {
  const letter = placeholder ? '+' : ((name || '').trim()[0] || '?').toLocaleUpperCase('tr');
  const bg = placeholder ? '#eef2f7' : '#12385c';
  const fg = placeholder ? '#64748b' : '#ffffff';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120"><rect width="120" height="120" rx="60" fill="${bg}"/><text x="60" y="66" text-anchor="middle" dominant-baseline="central" font-family="Arial,sans-serif" font-size="58" font-weight="700" fill="${fg}">${letter}</text></svg>`;
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
}
let COMPANY = '';
let COMPANY_LEGAL = '';   // kimlik kartında tam/yasal ünvan (yoksa kısa ada düşer)
let COMPANY_LOGO = '';    // kimlik kartında firma logosu (yoksa varsayılan)
const meta = async () => (META ??= await api.get('/api/hr/meta'));

function photoOf(e, size = 'lg') {
  const src = e.photo_file ? fileUrl(e.photo_file, 256) : e.user_photo ? fileUrl(e.user_photo, 256) : null;
  const initials = `${e.first_name?.[0] || ''}${e.last_name?.[0] || ''}`.toLocaleUpperCase('tr');
  return h('span', { class: `avatar ${size}` }, src ? h('img', { src, alt: '', loading: 'lazy' }) : initials);
}

export async function render(view, params, ctx) {
  COMPANY = ctx.meta?.company || '';
  COMPANY_LEGAL = ctx.meta?.company_legal || ctx.meta?.company || '';
  COMPANY_LOGO = ctx.meta?.logo_url || '';
  if (/^\d+$/.test(params[0] || '')) return renderDetail(view, Number(params[0]), ctx);
  const tab = ['applications', 'leaves', 'matrix', 'attendance', 'org'].includes(params[0]) ? params[0] : 'personnel';
  // "Takip" üst sekmesi: İzinler ve Giriş-Çıkış onun altında ikincil seçici olarak toplanır
  const TAKIP = ['leaves', 'attendance'];
  const navKey = TAKIP.includes(tab) ? 'takip' : tab;
  const nav = segmented([['personnel', 'Personel'], ['applications', 'İş Başvuruları'], ['takip', 'Takip'], ['org', 'Organizasyon'], ['matrix', 'Görev Matrisi']], navKey,
    v => { location.hash = v === 'personnel' ? '#/hr' : v === 'takip' ? '#/hr/leaves' : `#/hr/${v}`; }, { tabs: true });
  const takipNav = () => segmented([['leaves', 'İzinler'], ['attendance', 'Giriş-Çıkış']], tab, v => { location.hash = `#/hr/${v}`; });
  const head = (sub, extra) => h('div', null, pageHead('İnsan Kaynakları', { back: '#/', sub, tabs: nav }),
    moduleToolbar(TAKIP.includes(tab) ? takipNav() : null, extra || null));
  if (tab === 'leaves') return renderLeaves(view, head);
  if (tab === 'matrix') return renderMatrix(view, head);
  if (tab === 'attendance') return renderAttendance(view, head, ctx);
  if (tab === 'org') return renderOrg(view, head);
  const [list, m] = await Promise.all([api.get('/api/hr/employees'), meta()]);
  if (tab === 'applications') return renderApplications(view, head, list, m);
  return renderPersonnel(view, head, list, m);
}

// ---------- Personel
function renderPersonnel(view, head, list, m) {
  const staff = list.filter(e => e.status === 'AKTIF' || e.status === 'AYRILDI');
  const active = staff.filter(e => e.status === 'AKTIF');
  const stats = statStrip();
  stats.set([
    { icon: 'hr', label: 'Aktif personel', value: active.length },
    { icon: 'warning', label: 'Evrakı eksik', value: active.filter(e => e.missing.length || e.unsigned_leaves).length, tone: active.some(e => e.missing.length || e.unsigned_leaves) ? 'alert' : 'ok' },
    { icon: 'calendar', label: 'Bugün izinde / raporlu', value: active.filter(e => e.on_leave || e.on_report).length },
    { icon: 'person', label: 'Bekleyen başvuru', value: list.filter(e => e.status === 'BASVURU').length },
  ]);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ad, TC, görev ara…', style: { width: '220px' } });
  const st = selectInput([['AKTIF', 'Aktif personel'], ['AYRILDI', 'Ayrılan personel'], ['MISSING', 'Evrakı eksik olanlar']], { all: 'Tüm personel', value: pref('hr.filter', 'AKTIF') });
  const grid = h('div', { class: 'hr-grid' });
  const draw = () => {
    setPref('hr.filter', st.value);
    const shown = staff.filter(e => (!st.value || (st.value === 'MISSING' ? e.status === 'AKTIF' && (e.missing.length || e.unsigned_leaves) : e.status === st.value))
      && matches(q.value, e.first_name, e.last_name, e.name, e.tc_no, e.title, e.department, e.username));
    clear(grid, shown.length ? shown.map(card) : h('div', { class: 'card empty' }, 'Filtreye uyan personel yok'));
    setListExport(() => ({ columns: ['Ad Soyad', 'TC Kimlik No', 'Görev', 'Departman', 'Durum', 'İşe başlama', 'Telefon', 'E-posta', 'Kullanıcı', 'Eksik evrak'],
      rows: shown.map(e => [e.name || `${e.first_name} ${e.last_name}`, e.tc_no || '', e.title || '', e.department || '', ({ AKTIF: 'Aktif', AYRILDI: 'Ayrıldı', BASVURU: 'Başvuru', REDDEDILDI: 'Reddedildi' })[e.status] || e.status, e.start_date || '',
        e.phone || '', e.email || '', e.username || '', (e.missing || []).length]) }));
  };
  q.addEventListener('input', draw);
  st.addEventListener('change', draw);
  const add = h('button', { class: 'btn primary', onclick: () => applicationForm(m) }, '＋ Personel Ekle');
  clear(view, head('Personel kayıtları, özlük dosyaları ve sözleşmeler', [q, st, add]), stats, grid);
  draw();
}

function card(e) {
  const tags = [
    !e.tc_no ? h('span', { class: 'badge yellow' }, 'TC girilmemiş') : null,
    e.on_report ? h('span', { class: 'badge yellow' }, 'Raporlu') : e.on_leave ? h('span', { class: 'badge blue' }, 'İzinde') : null,
    e.status === 'AYRILDI' ? h('span', { class: 'badge gray' }, 'Ayrıldı') : null,
    e.user_id ? null : h('span', { class: 'badge gray' }, 'Kullanıcısı yok'),
  ];
  return h('a', { class: `card hr-card ${e.missing.length || e.unsigned_leaves ? 'missing' : ''} ${e.status === 'AYRILDI' ? 'left' : ''}`, href: `#/hr/${e.id}` },
    photoOf(e),
    h('div', { class: 'hr-card-body' },
      h('b', null, e.name),
      h('div', { class: 'small muted' }, [e.title, e.department].filter(Boolean).join(' · ') || 'Görev girilmemiş'),
      h('div', { class: 'small muted' }, e.start_date ? t('İşe başlama {d}', { d: fmtDate(e.start_date) }) : ''),
      h('div', { class: 'hr-tags' }, tags),
      e.missing.length ? h('div', { class: 'hr-missing' }, t('{n} evrak eksik', { n: e.missing.length }),
        h('span', null, [e.missing_personnel ? t('{n} özlük', { n: e.missing_personnel }) : null, e.missing_contracts ? t('{n} sözleşme', { n: e.missing_contracts }) : null].filter(Boolean).join(' · '))) : null,
      e.unsigned_leaves ? h('div', { class: 'hr-missing' }, t('{n} izin formu imzasız', { n: e.unsigned_leaves })) : null));
}

// Personel Ekle: iş başvurusu formu (TC, kişisel bilgiler, başvuru kaynağı, CV)
function applicationForm(m) {
  const f = {
    tc: h('input', { class: 'input mono', inputmode: 'numeric', maxlength: 11, placeholder: '11 haneli TC Kimlik No' }),
    first: h('input', { class: 'input' }), last: h('input', { class: 'input' }),
    gender: h('select', { class: 'input' }, h('option', { value: '' }, 'Seçin'), h('option', { value: 'E' }, 'Erkek'), h('option', { value: 'K' }, 'Kadın')),
    birth: dateIn(), phone: h('input', { class: 'input', type: 'tel' }), email: emailsInput([]),
    position: h('input', { class: 'input', placeholder: 'ör. Montaj Teknisyeni' }),
    source: h('select', { class: 'input' }, h('option', { value: '' }, 'Seçin'), m.sources.map(s => h('option', { value: s }, s))),
    sourceNote: h('input', { class: 'input' }),
    applied: dateIn(today()),
    cv: h('input', { class: 'input', type: 'file', accept: '.pdf,.doc,.docx,.odt,.jpg,.jpeg,.png' }),
    note: h('textarea', { class: 'input', rows: 2 }),
  };
  const noteField = field('Açıklama', f.sourceNote);
  const syncSource = () => {
    noteField.querySelector('label').textContent = f.source.value === 'Referans' ? 'Referans veren kişi' : 'Kaynak açıklaması';
    f.sourceNote.placeholder = f.source.value === 'Referans' ? 'Ad soyad, yakınlık' : 'ör. ilan numarası';
  };
  f.source.addEventListener('change', syncSource);
  syncSource();
  modal({
    title: 'Personel Ekle · İş Başvurusu', wide: true,
    body: h('div', null,
      h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Kayıt iş başvurusu olarak açılır; kabul edilene kadar personel ve kullanıcı listelerinde görünmez.'),
      h('div', { class: 'form-grid' },
        field('TC Kimlik Numarası *', f.tc), field('Ad *', f.first), field('Soyad *', f.last),
        field('Cinsiyet', f.gender, 'Askerlik belgesi yalnızca erkek personelden istenir'), field('Doğum tarihi', f.birth), field('Telefon', f.phone),
        field('E-posta', f.email), field('Başvurduğu pozisyon', f.position), field('Başvuru tarihi', f.applied),
        field('Başvuru kaynağı *', f.source), noteField, field('CV', f.cv)),
      field('Not', f.note)),
    actions: [{ label: 'Vazgeç' }, {
      label: 'Başvuruyu Kaydet', class: 'primary', onClick: async () => {
        const { id } = await api.post('/api/hr/applications', {
          tc_no: f.tc.value, first_name: f.first.value, last_name: f.last.value, gender: f.gender.value || null, birth_date: f.birth.value || null,
          phone: f.phone.value, email: f.email.value, emails: f.email.values, position: f.position.value, source: f.source.value || null, source_note: f.sourceNote.value,
          applied_at: f.applied.value || null, note: f.note.value,
        });
        if (f.cv.files[0]) {
          const fd = new FormData();
          fd.append('file', f.cv.files[0]);
          await upload(`/api/hr/employees/${id}/cv`, fd).catch(err => toast(t('Başvuru kaydedildi ama CV yüklenemedi: {msg}', { msg: err.message }), 'err'));
        }
        toast('İş başvurusu kaydedildi');
        location.hash = `#/hr/${id}`;
      },
    }],
  });
  f.tc.focus();
}

// ---------- İş başvuruları
function renderApplications(view, head, list, m) {
  let show = pref('hr.apps', 'BASVURU');
  const apps = list.filter(e => e.status === 'BASVURU' || e.status === 'REDDEDILDI')
    .sort((a, b) => (b.applied_at || b.created_at).localeCompare(a.applied_at || a.created_at));
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ad, TC, pozisyon ara…', style: { width: '220px' } });
  const src = selectInput(m.sources.map(s => [s, s]), { all: 'Tüm kaynaklar' });
  const body = h('div');
  const draw = () => {
    const rows = apps.filter(e => e.status === show && (!src.value || e.source === src.value) && matches(q.value, e.name, e.tc_no, e.position, e.source_note));
    clear(body, rows.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, h('th', null, 'Aday'), h('th', null, 'TC'), h('th', null, 'Pozisyon'), h('th', null, 'Kaynak'),
        h('th', null, 'Başvuru'), h('th', null, 'CV'), h('th', null, show === 'BASVURU' ? '' : 'Ret sebebi'), h('th', null, ''))),
      h('tbody', null, rows.map(e => h('tr', null,
        h('td', null, h('a', { href: `#/hr/${e.id}` }, h('b', null, e.name)), h('div', { class: 'small muted' }, e.phone || e.email || '')),
        h('td', { class: 'mono' }, e.tc_no || '—'), h('td', null, e.position || '—'),
        h('td', null, e.source || '—', e.source_note ? h('div', { class: 'small muted' }, e.source_note) : null),
        h('td', null, fmtDate(e.applied_at)),
        h('td', null, e.cv_file ? h('a', { href: fileUrl(e.cv_file), target: '_blank', rel: 'noopener' }, 'CV') : h('span', { class: 'muted' }, '—')),
        h('td', { class: 'small' }, e.status === 'REDDEDILDI' ? e.reject_reason : null),
        h('td', { class: 'actions' }, e.status === 'BASVURU'
          ? [h('button', { class: 'btn sm primary', onclick: () => acceptModal(e) }, 'Kabul Et'), h('button', { class: 'btn sm', onclick: () => rejectModal(e) }, 'Reddet')]
          : h('button', { class: 'btn sm', onclick: () => reopen(e) }, 'Yeniden Değerlendir')))))))
      : h('div', { class: 'card empty' }, show === 'BASVURU' ? 'Bekleyen iş başvurusu yok' : 'Reddedilen başvuru yok'));
  };
  const seg = segmented([['BASVURU', t('Bekleyenler ({n})', { n: apps.filter(e => e.status === 'BASVURU').length })], ['REDDEDILDI', 'Reddedilenler']], show,
    v => { show = v; setPref('hr.apps', v); draw(); });
  q.addEventListener('input', draw);
  src.addEventListener('change', draw);
  const add = h('button', { class: 'btn primary', onclick: () => applicationForm(m) }, '＋ Personel Ekle');
  clear(view, head('İş başvuruları: kabul edilince personel olur', [add]),
    h('div', { class: 'filters' }, seg, h('span', { class: 'spacer' }), q, src), body);
  draw();
}

const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));

function acceptModal(e) {
  const title = h('input', { class: 'input', value: e.position || '' });
  const dept = h('input', { class: 'input' });
  const salary = h('input', { class: 'input', type: 'number', min: 0, step: '0.01', placeholder: 'Brüt / net, ₺' });
  const start = dateIn();
  modal({
    title: t('{name} · Kabul Et', { name: e.name }),
    body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Aday personel olur; özlük dosyaları ve sözleşmeler ardından girilir.'),
      field('Görevi *', title), field('Departman', dept), field('Maaşı (₺)', salary), field('Resmi işe başlama tarihi *', start)),
    actions: [{ label: 'Vazgeç' }, {
      label: 'Kabul Et', class: 'primary', onClick: async () => {
        await api.post(`/api/hr/employees/${e.id}/accept`, { title: title.value, department: dept.value, salary: salary.value === '' ? null : Number(salary.value), start_date: start.value });
        toast(t('{name} personel olarak kaydedildi', { name: e.name }));
        location.hash = `#/hr/${e.id}`;
        reload();
      },
    }],
  });
}

function rejectModal(e) {
  const reason = h('textarea', { class: 'input', rows: 3, placeholder: 'ör. Deneyim yetersiz, maaş beklentisi uyuşmadı…' });
  modal({
    title: t('{name} · Reddet', { name: e.name }),
    body: field('Reddetme sebebi *', reason),
    actions: [{ label: 'Vazgeç' }, { label: 'Reddet', class: 'danger', onClick: async () => {
      await api.post(`/api/hr/employees/${e.id}/reject`, { reason: reason.value });
      toast('Başvuru reddedildi');
      reload();
    } }],
  });
}

async function reopen(e) {
  try { await api.post(`/api/hr/employees/${e.id}/reopen`); toast('Başvuru yeniden değerlendirmeye alındı'); reload(); } catch (err) { toastError(err); }
}

// ---------- İzinler (İK): bekleyen talepler ve geçmiş; istenen ve verilen tarihler yan yana
async function renderLeaves(view, head) {
  const period = periodFilter('hrLeaves', () => renderLeaves(view, head), { title: 'Tüm Geçmiş: izin tarihi seçilen dönemle çakışanlar' });
  const all = await api.get(`/api/hr/leaves?${period.qs()}`);
  let show = pref('hr.leaves', 'BEKLIYOR');
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Personel ara…', style: { width: '200px' } });
  const kind = selectInput(Object.entries(LEAVE_KINDS), { all: 'Tüm izin türleri' });
  const body = h('div');
  const draw = () => {
    const rows = all.filter(l => (show === 'ALL' ? l.status !== 'IPTAL' : show === 'FUTURE' ? l.status === 'ONAYLANDI' && l.end_date >= today()
      : show === 'UNSIGNED' ? l.unsigned : l.status === show)
      && (!kind.value || l.kind === kind.value) && matches(q.value, l.employee_name, l.reason, l.location));
    period.el.hidden = show !== 'ALL';   // dönem yalnızca geçmiş izinlerde anlamlı
    if (!rows.length) return clear(body, h('div', { class: 'card empty' }, 'Kayıt yok'));
    const v = leaveViews(rows, { hr: true, showEmployee: true });
    clear(body, h('div', { class: 'leave-view-bar' }, v.seg), v.box);
  };
  const unsignedN = all.filter(l => l.unsigned).length;
  const seg = segmented([['BEKLIYOR', t('Onay Bekleyenler ({n})', { n: all.filter(l => l.status === 'BEKLIYOR').length })],
    ['UNSIGNED', t('İmzalı Form Bekleyen ({n})', { n: unsignedN })], ['FUTURE', 'Yaklaşan ve Süren'], ['ALL', 'Tüm Geçmiş']], show,
  v => { show = v; setPref('hr.leaves', v); draw(); });
  q.addEventListener('input', draw);
  kind.addEventListener('change', draw);
  clear(view, head('İzin talepleri: istenen ve verilen tarihler'), h('div', { class: 'filters' }, seg, h('span', { class: 'spacer' }), period.el, q, kind), body);
  draw();
}

// Islak imzalı izin formu: onaylanan izin için İK yükler; yüklenene kadar izin (kart / satır) kırmızı çerçevelidir
function signedCell(l, hr) {
  if (l.status !== 'ONAYLANDI') return h('span', { class: 'muted' }, '—');
  if (l.signed_file) {
    return h('div', { class: 'signed-ok' }, h('a', { href: fileUrl(l.signed_file), target: '_blank', rel: 'noopener' }, '✓ İmzalı form'),
      hr ? h('div', { class: 'small muted' }, `${fmtDate(l.signed_at)} · ${l.signed_by_name || ''}`) : null,
      hr ? h('button', { class: 'link-btn small', onclick: () => removeSigned(l) }, 'Kaldır') : null);
  }
  if (!hr) return h('span', { class: 'muted small' }, 'İK imzalı formu bekliyor');
  return h('div', { class: 'signed-miss' }, h('b', null, 'Islak imzalı form yok'),
    h('div', { class: 'row-inline' },
      h('button', { class: 'btn sm primary', onclick: () => uploadSigned(l) }, 'Yükle'),
      h('button', { class: 'btn sm', onclick: () => printLeaveForm(l) }, 'Formu Yazdır')));
}

function uploadSigned(l) {
  const input = h('input', { type: 'file', accept: '.pdf,.jpg,.jpeg,.png,.webp,.heic,.heif', hidden: true });
  input.addEventListener('change', async () => {
    if (!input.files[0]) return;
    const fd = new FormData();
    fd.append('file', input.files[0]);
    try { await upload(`/api/hr/leaves/${l.id}/signed`, fd); toast('Islak imzalı izin formu yüklendi'); reload(); } catch (err) { toastError(err); }
  });
  document.body.append(input);
  input.click();
  setTimeout(() => input.remove(), 60000);
}

async function removeSigned(l) {
  if (!await confirmDialog('İmzalı formu kaldır', 'Islak imzalı izin formu kaldırılsın mı? İzin yeniden kırmızı görünür.', { okLabel: 'Kaldır', danger: true })) return;
  try { await api.del(`/api/hr/leaves/${l.id}/signed`); reload(); } catch (err) { toastError(err); }
}

// Islak imza için yazdırılabilir izin formu
function printLeaveForm(l) {
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const row = (k, v) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`;
  const w = window.open('', '_blank');
  if (!w) { toast('Açılır pencere engellendi; tarayıcıda izin verin', 'err'); return; }
  w.document.write(`<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>İzin Formu · ${esc(l.employee_name)}</title>
<style>body{font-family:system-ui,sans-serif;margin:40px;color:#111}h1{font-size:20px;text-align:center;margin:0 0 4px}
.co{text-align:center;color:#555;margin-bottom:28px}table{width:100%;border-collapse:collapse;margin-bottom:28px}
th,td{border:1px solid #999;padding:9px 12px;text-align:left;font-size:14px}th{width:34%;background:#f3f3f3}
.sig{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin-top:40px}.sig div{border-top:1px solid #333;padding-top:6px;text-align:center;font-size:13px;min-height:70px}
.note{font-size:12px;color:#555}@media print{body{margin:18mm}}</style></head><body>
<h1>PERSONEL İZİN FORMU</h1><div class="co">${esc(COMPANY || '')}</div>
<table>${row('Adı Soyadı', l.employee_name)}${row('TC Kimlik No', l.employee_tc || '')}${row('Görevi', [l.employee_title, l.employee_department].filter(Boolean).join(' · '))}
${row('İzin türü', LEAVE_KINDS[l.kind] || l.kind)}${row('İzin başlangıcı', fmtDate(l.start_date))}${row('İzin bitişi', fmtDate(l.end_date))}
${row('Süre', `${l.days} gün`)}${row('İzin sebebi', l.reason)}${row('İzinde bulunacağı yer', l.location)}
${l.changed ? row('Talep edilen', `${fmtDate(l.req_start)} – ${fmtDate(l.req_end)} (${l.req_days} gün)`) : ''}
${row('Onaylayan', `${l.decided_by_name || ''} · ${fmtDate(l.decided_at)}`)}${l.decision_note ? row('Not', l.decision_note) : ''}</table>
<p class="note">Yukarıdaki tarihler arasında izin kullanacağımı beyan ederim.</p>
<div class="sig"><div>Personel<br>İmza</div><div>Birim Amiri<br>İmza</div><div>İnsan Kaynakları<br>İmza</div></div>
<script>window.onload=()=>window.print()<\/script></body></html>`);
  w.document.close();
}

function leaveCard(l, { hr = false, showEmployee = false, mine = false } = {}) {
  return h('div', { class: `card leave-card ${l.unsigned && !mine ? 'unsigned' : ''} st-${l.status.toLowerCase()}` },
    h('div', { class: 'leave-card-head' },
      h('b', null, showEmployee ? l.employee_name : LEAVE_KINDS[l.kind] || l.kind), badge(LEAVE_STATUS, l.status)),
    showEmployee ? h('div', { class: 'small muted' }, LEAVE_KINDS[l.kind]) : null,
    h('dl', { class: 'leave-kv' },
      h('dt', null, 'İstenen'), h('dd', null, range(l.req_start, l.req_end)),
      h('dt', null, 'Verilen'), h('dd', { class: l.changed ? 'leave-changed' : '' }, l.start_date ? range(l.start_date, l.end_date) : '—'),
      h('dt', null, 'Sebep'), h('dd', null, l.reason || '—'),
      h('dt', null, 'Nerede'), h('dd', null, l.location || '—'),
      l.decision_note ? [h('dt', null, 'İK notu'), h('dd', null, l.decision_note)] : null,
      l.decided_by_name && l.status !== 'IPTAL' ? [h('dt', null, 'Karar'), h('dd', null, `${l.decided_by_name} · ${fmtDate(l.decided_at)}`)] : null),
    l.status === 'ONAYLANDI' ? h('div', { class: 'leave-sign' }, signedCell(l, hr)) : null,
    h('div', { class: 'leave-actions' },
      hr && l.status === 'BEKLIYOR' ? [h('button', { class: 'btn sm primary', onclick: () => approveModal(l) }, 'Onayla'),
        h('button', { class: 'btn sm', onclick: () => rejectLeave(l) }, 'Reddet')] : null,
      hr && l.status === 'ONAYLANDI' && l.signed_file ? h('button', { class: 'btn sm', onclick: () => printLeaveForm(l) }, 'Formu Yazdır') : null,
      mine && l.status === 'BEKLIYOR' ? h('button', { class: 'btn sm', onclick: () => cancelLeave(l) }, 'Geri Çek') : null));
}

function leaveTable(rows, { hr = false, showEmployee = false, mine = false } = {}) {
  return h('div', { class: 'card table-wrap' }, h('table', { class: 'table leave-table' },
    h('thead', null, h('tr', null, showEmployee ? h('th', null, 'Personel') : null, h('th', null, 'Tür'), h('th', null, 'İstenen'),
      h('th', null, 'Verilen'), h('th', null, 'Sebep / Nerede'), h('th', null, 'Durum'), mine ? null : h('th', null, 'Islak imza'), h('th', null, ''))),
    h('tbody', null, rows.map(l => h('tr', { class: `${l.status === 'BEKLIYOR' ? 'pending' : ''} ${l.unsigned && !mine ? 'unsigned' : ''}` },
      showEmployee ? h('td', null, h('a', { href: `#/hr/${l.employee_id}` }, h('b', null, l.employee_name)), h('div', { class: 'small muted' }, l.employee_title || '')) : null,
      h('td', null, LEAVE_KINDS[l.kind] || l.kind),
      h('td', null, range(l.req_start, l.req_end), h('div', { class: 'small muted' }, t('Talep: {d}', { d: fmtDateTime(l.created_at) }) + (l.requested_by_name && showEmployee ? ` · ${l.requested_by_name}` : ''))),
      h('td', { class: l.changed ? 'leave-changed' : '' }, l.start_date ? range(l.start_date, l.end_date) : '—',
        l.changed ? h('div', { class: 'small' }, 'İK tarafından değiştirildi') : null),
      h('td', { class: 'small' }, l.reason, h('div', { class: 'muted' }, `📍 ${l.location || '—'}`)),
      h('td', null, badge(LEAVE_STATUS, l.status), l.decision_note ? h('div', { class: 'small muted' }, l.decision_note) : null,
        l.decided_by_name && l.status !== 'IPTAL' ? h('div', { class: 'small muted' }, `${l.decided_by_name} · ${fmtDate(l.decided_at)}`) : null),
      mine ? null : h('td', null, signedCell(l, hr)),
      h('td', { class: 'actions' },
        hr && l.status === 'BEKLIYOR' ? [h('button', { class: 'btn sm primary', onclick: () => approveModal(l) }, 'Onayla'),
          h('button', { class: 'btn sm', onclick: () => rejectLeave(l) }, 'Reddet')] : null,
        mine && l.status === 'BEKLIYOR' ? h('button', { class: 'btn sm', onclick: () => cancelLeave(l) }, 'Geri Çek') : null))))));
}

// İzinler: kart ya da liste görünümü (tercih saklanır)
function leaveViews(rows, opts) {
  let view = pref('hr.leaveView', 'card');
  const box = h('div');
  const draw = () => clear(box, view === 'card'
    ? h('div', { class: 'leave-grid' }, rows.map(l => leaveCard(l, opts)))
    : leaveTable(rows, opts));
  const seg = segmented([['card', 'Kart'], ['list', 'Liste']], view, v => { view = v; setPref('hr.leaveView', v); draw(); });
  draw();
  return { seg, box };
}

function approveModal(l) {
  const start = dateIn(l.req_start), end = dateIn(l.req_end);
  const note = h('input', { class: 'input', placeholder: 'Tarih değiştiyse sebebi (isteğe bağlı)' });
  const info = h('div', { class: 'small muted' });
  const sync = () => { info.textContent = t('Verilecek: {a} gün · İstenen: {b} gün ({c} – {d})', { a: days(start.value, end.value) || '—', b: l.req_days, c: fmtDate(l.req_start), d: fmtDate(l.req_end) }); };
  start.addEventListener('input', sync); end.addEventListener('input', sync); sync();
  modal({
    title: t('{name} · İzni Onayla', { name: l.employee_name }),
    body: h('div', null, h('p', { style: { marginTop: 0 } }, `${LEAVE_KINDS[l.kind]} · ${l.reason} · 📍 ${l.location}`),
      h('div', { class: 'row' }, field('Başlangıç', start), field('Bitiş', end)), info, field('Not', note)),
    actions: [{ label: 'Vazgeç' }, { label: 'Onayla', class: 'primary', onClick: async () => {
      await api.post(`/api/hr/leaves/${l.id}/approve`, { start: start.value, end: end.value, note: note.value });
      toast('İzin onaylandı · ıslak imzalı formu yükleyin'); reload();
    } }],
  });
}

function rejectLeave(l) {
  const note = h('textarea', { class: 'input', rows: 3 });
  modal({
    title: t('{name} · İzni Reddet', { name: l.employee_name }), body: field('Reddetme sebebi *', note),
    actions: [{ label: 'Vazgeç' }, { label: 'Reddet', class: 'danger', onClick: async () => {
      await api.post(`/api/hr/leaves/${l.id}/reject`, { note: note.value }); toast('İzin talebi reddedildi'); reload();
    } }],
  });
}

async function cancelLeave(l) {
  if (!await confirmDialog('Talebi geri çek', t('{range} tarihli {kind} talebiniz geri çekilsin mi?', { range: range(l.req_start, l.req_end), kind: LEAVE_KINDS[l.kind].toLocaleLowerCase('tr') }),
    { okLabel: 'Geri Çek', danger: true })) return;
  try { await api.del(`/api/me/leaves/${l.id}`); toast('Talep geri çekildi'); reload(); } catch (err) { toastError(err); }
}

// İzin talebi formu (personel: Kişisel › İzinlerim; İK: personel adına)
function leaveForm({ title, url, hint }) {
  const kind = h('select', { class: 'input' }, Object.entries(LEAVE_KINDS).map(([k, v]) => h('option', { value: k }, v)));
  const start = dateIn('', { min: url.startsWith('/api/me') ? today() : undefined });
  const end = dateIn('', { min: url.startsWith('/api/me') ? today() : undefined });
  start.addEventListener('change', () => { if (!end.value || end.value < start.value) end.value = start.value; sync(); });
  end.addEventListener('change', () => sync());
  const count = h('div', { class: 'small muted' });
  const sync = () => { count.textContent = start.value && end.value ? t('{n} gün', { n: days(start.value, end.value) }) : ''; };
  const reason = h('textarea', { class: 'input', rows: 2, placeholder: 'ör. Yıllık izin, aile ziyareti, sağlık…' });
  const location = h('input', { class: 'input', placeholder: 'ör. Ankara, Kızılay · telefonla ulaşılabilir' });
  modal({
    title,
    body: h('div', null, hint ? h('p', { class: 'small muted', style: { marginTop: 0 } }, hint) : null,
      field('İzin türü', kind), h('div', { class: 'row' }, field('Başlangıç tarihi', start), field('Bitiş tarihi', end)), count,
      field('İzin sebebi *', reason), field('İzinde nerede olacaksınız? *', location)),
    actions: [{ label: 'Vazgeç' }, { label: 'Gönder', class: 'primary', onClick: async () => {
      await api.post(url, { kind: kind.value, start: start.value, end: end.value, reason: reason.value, location: location.value });
      toast(url.startsWith('/api/me') ? 'İzin talebiniz İnsan Kaynakları onayına gönderildi' : 'İzin kaydedildi');
      reload();
    } }],
  });
}

// ---------- Personel ayrıntısı
async function renderDetail(view, id, ctx) {
  const [e, m] = await Promise.all([api.get(`/api/hr/employees/${id}`), meta()]);
  const staff = e.status === 'AKTIF' || e.status === 'AYRILDI';
  // Ana sekmeler sade: Genel · İSG · Özlük · İzin ve Sağlık · Geçmiş. Gruplu sekmelerde solda alt modül seçici, sağda detay.
  const missingCount = kinds => e.required.filter(k => k in kinds && !e.files[k]).length;
  const cnt = (n, extra = '') => (n ? ` (${n}${extra})` : '');
  const GROUPS = staff ? {
    general: { label: 'Genel' },
    isg: { label: 'İSG', subs: [
      ['duties', 'Görev Tanımı', 'Pozisyon, amir, vekil, acil durum görevi ve maddeler', cnt(e.duties?.length)],
      ['ppe', 'KKD', 'Kişisel koruyucu donanımlar', cnt(e.isg?.ppe?.length)],
      ['trainings', 'Eğitimler', 'Zorunlu eğitim ve yeterlilikler', cnt(e.isg?.trainings?.length)],
      ['hazards', 'Riskler', 'Tehlikeler ve kontrol tedbirleri', cnt(e.isg?.hazards?.length)]] },
    personnel: { label: 'Özlük', subs: [
      ['files', 'Özlük Dosyaları', 'Zorunlu belgeler', cnt(e.status === 'AKTIF' && missingCount(m.personnel_files), ' eksik')],
      ['contracts', 'Sözleşmeler', 'İş, gizlilik, araç sözleşmeleri', cnt(e.status === 'AKTIF' && missingCount(m.contracts), ' eksik')],
      ['application', 'Başvuru Bilgileri', 'İş başvuru formundaki bilgiler', cnt(Object.values(e.application_info || {}).filter(Boolean).length)],
      ['addresses', 'Adresler', 'Ev, tebligat, acil durum', cnt(e.addresses.length)],
      ['family', 'Ailesi', 'Aile üyeleri ve yakınlık', cnt(e.family?.length)]] },
    absence: { label: 'İzin ve Sağlık', subs: [
      ['leaves', 'İzinler', 'İzin talepleri ve imzalı formlar', cnt(e.unsigned_leaves, ' imzasız')],
      ['health', 'Sağlık Raporları', 'Rapor süresince raporlu; sisteme giremez', cnt(e.health_reports?.length)]] },
    attendance: { label: 'Giriş-Çıkış' },
    finance: { label: 'Hesap Hareketleri' },   // maaş ödemeleri vb. (isimle eşleşen + bağlanan cari / hesap hareketleri)
    history: { label: 'Geçmiş' },
  } : { general: { label: 'Genel' }, personnel: { label: 'Adresler', subs: [['addresses', 'Adresler', '', cnt(e.addresses.length)]] }, history: { label: 'Geçmiş' } };
  const OLD = { duties: 'isg', ppe: 'isg', trainings: 'isg', hazards: 'isg', files: 'personnel', contracts: 'personnel', addresses: 'personnel', leaves: 'absence' };
  let tab = pref('hr.tab', 'general');
  let sub = pref('hr.sub', '');
  if (OLD[tab]) { sub = tab; tab = OLD[tab]; }   // eski tercih (ör. Görev Matrisi'nden gelen 'duties') yeni gruba çevrilir
  if (!GROUPS[tab]) tab = 'general';
  const stage = h('div');
  const panel = key => {
    if (key === 'addresses') return addressesTab(e, m);
    if (key === 'family') return familyTab(e, m, ctx);
    if (key === 'duties') return dutiesTab(e, m);
    if (key === 'ppe' || key === 'trainings' || key === 'hazards') return isgListTab(e, key);
    if (key === 'files') return filesTab(e, m.personnel_files, 'Özlük Dosyaları');
    if (key === 'contracts') return filesTab(e, m.contracts, 'Sözleşmeler');
    if (key === 'application') return applicationTab(e);
    if (key === 'leaves') return leavesTab(e);
    if (key === 'health') return healthTab(e);
    return h('div');
  };
  const show = () => {
    const g = GROUPS[tab];
    if (tab === 'general') return clear(stage, generalTab(e, m, ctx));
    if (tab === 'history') return clear(stage, historyTab(e, { ...m.personnel_files, ...m.contracts }));
    if (tab === 'attendance') return clear(stage, attendanceDetailTab(e));
    if (tab === 'finance') { const box = h('div', { class: 'hr-sub-detail' }); clear(stage, box); return personPane(box, e.id); }
    if (!g.subs.some(s => s[0] === sub)) sub = g.subs[0][0];
    const detail = h('div', { class: 'hr-sub-detail' }, panel(sub));
    clear(stage, g.subs.length === 1 ? detail : h('div', { class: 'set-layout hr-sub' },
      h('nav', { class: 'card set-nav' }, g.subs.map(([k, l, d, c]) => h('a', { href: 'javascript:void 0', class: k === sub ? 'on' : '',
        onclick: () => { sub = k; setPref('hr.sub', k); show(); } }, h('span', null, h('b', null, l + (c || '')), d ? h('small', null, d) : null)))),
      detail));
  };
  const seg = segmented(Object.entries(GROUPS).map(([k, g]) => [k, g.label]), tab, v => { tab = v; setPref('hr.tab', v); show(); });
  seg.classList.add('hr-tabs', 'seg-tabs');
  const actions = e.status === 'BASVURU' ? [h('button', { class: 'btn primary', onclick: () => acceptModal(e) }, 'Kabul Et'), h('button', { class: 'btn', onclick: () => rejectModal(e) }, 'Reddet')]
    : e.status === 'REDDEDILDI' ? [h('button', { class: 'btn', onclick: () => reopen(e) }, 'Yeniden Değerlendir')]
      : e.status === 'AKTIF' ? [h('button', { class: 'btn sm primary', onclick: () => leaveForm({ title: t('{name} · İzin Gir', { name: e.name }), url: `/api/hr/employees/${e.id}/leaves`, hint: 'İK tarafından girilen izin onaylı kaydedilir.' }) }, 'İzin Gir'),
        h('button', { class: 'btn sm danger-text', onclick: () => leaveJobModal(e) }, 'İşten Ayrılış')]
        : [h('button', { class: 'btn', onclick: async () => { try { await api.post(`/api/hr/employees/${e.id}/rehire`); reload(); } catch (err) { toastError(err); } } }, 'Yeniden İşe Al')];
  const printCard = h('button', { class: 'btn sm', type: 'button', onclick: () => printIdCard(e) }, '🪪 Kartı Yazdır');
  const card = idCard(e, { company: COMPANY_LEGAL, action: printCard, logoUrl: COMPANY_LOGO });
  const top = h('div', { class: `hr-detail-top ${e.missing.length || e.unsigned_leaves ? 'missing' : ''}` },
    h('div', { class: 'idc-wrap' }, card),
    h('div', { class: 'card card-pad hr-top-side' },
      h('div', { class: 'hr-top-name' }, badge(EMP_STATUS, e.status),
        e.absence ? h('span', { class: `badge ${e.absence.kind === 'RAPOR' ? 'yellow' : 'blue'}`, title: 'Bu sürede sisteme giriş yapamaz' },
          t('{label} · {d} tarihine kadar', { label: e.absence.label, d: e.absence.until.split('-').reverse().join('.') })) : null,
        e.status === 'BASVURU' ? h('span', { class: 'muted' }, t('Başvurduğu pozisyon: {p}', { p: e.position || '—' })) : null,
        h('span', { class: 'spacer', style: { flex: 1 } }), h('div', { class: 'hr-side-actions' }, actions)),
      h('dl', { class: 'hr-kv' },
        h('dt', null, e.is_foreign ? 'Yabancı Kimlik No' : 'TC Kimlik No'), h('dd', { class: 'mono' }, e.tc_no || h('span', { class: 'badge yellow' }, 'Girilmemiş')),
        e.is_foreign ? [h('dt', null, 'Uyruğu'), h('dd', null, h('span', { class: 'badge blue' }, 'Yabancı uyruklu'), e.nationality ? ` ${e.nationality}` : '')] : null,
        staff ? [h('dt', null, 'İşe başlama'), h('dd', null, fmtDate(e.start_date) || '—')] : [h('dt', null, 'Başvuru'), h('dd', null, `${fmtDate(e.applied_at)} · ${e.source || '—'}`)],
        staff ? [h('dt', null, 'Maaş'), h('dd', null, money(e.salary))] : null,
        e.status === 'AYRILDI' ? [h('dt', null, 'Ayrılış'), h('dd', null, `${fmtDate(e.end_date)}${e.end_reason ? ` · ${e.end_reason}` : ''}`)] : null,
        e.addresses[0] ? [h('dt', null, 'Adres'), h('dd', null, addressLine(e.addresses[0]))] : null,
        h('dt', null, 'Kişi Güvenlik Kodu'), h('dd', { class: 'mono' }, e.security_code || h('span', { class: 'badge yellow' }, 'Girilmemiş')),
        h('dt', null, 'Kullanıcı'), h('dd', null, e.user_id ? `${e.username}${e.user_active ? '' : ' (pasif)'}` : 'Sistem kullanıcısı değil')),
      e.status === 'REDDEDILDI' ? h('div', { class: 'hr-alert' }, h('b', null, 'Ret sebebi: '), e.reject_reason, h('div', { class: 'small' }, `${e.decided_by_name || ''} · ${fmtDateTime(e.decided_at)}`)) : null,
      e.missing.length ? h('div', { class: 'hr-alert' }, h('b', null, t('Eksik evrak ({n}): ', { n: e.missing.length })), e.missing.join(', ')) : null,
      e.unsigned_leaves ? h('div', { class: 'hr-alert' }, h('b', null, t('{n} onaylı iznin ıslak imzalı formu yüklenmemiş', { n: e.unsigned_leaves })), ' · İzinler sekmesinden yükleyin') : null,
      e.pending_files ? h('div', { class: 'hr-alert' }, h('b', null, t('{n} evrak onay bekliyor', { n: e.pending_files })), ' · Özlük Dosyaları / Sözleşmeler sekmesinden açıp onaylayın') : null,
      e.org_path && e.org_path.length ? h('div', { class: 'org-path' }, e.org_path.map((n, i) => [
        i ? h('span', { class: 'org-path-sep' }, '›') : null,
        h('span', { class: `org-path-item ${n.self ? 'self' : ''}` }, h('b', null, n.name), n.title ? h('small', null, n.title) : null),
      ]).flat().filter(Boolean)) : null));
  clear(view,
    pageHead(e.name, { back: staff ? '#/hr' : '#/hr/applications', sub: t('İnsan Kaynakları · {s}', { s: EMP_STATUS[e.status][0] }) }),
    top, h('div', { class: 'module-tabs' }, seg), stage);
  show();
}

// ---------- Adresler: birden fazla adres, biri birincil
const addressLine = a => [a.address, [a.district, a.city].filter(Boolean).join(' / '), a.postal_code].filter(Boolean).join(', ');

// Görev tanımı (İSG görev tanımı belgesi yapısında): üst bilgiler (uçuş ekibi pozisyonu, amir, vekil, acil durum görevi,
// doküman no / revizyon), bölümlere ayrılmış maddeler (amaç, pozisyon görevleri, rol görevleri: rol › aşama, yetki ve sınırlar).
// Her maddenin gizlilik derecesi seçilir: Genel / Kurum İçi maddeler başka belgelerde (saha görev raporu) kullanılır.
const DUTY_TONE = { GENEL: 'green', KURUM_ICI: 'blue', GIZLI: 'yellow', COK_GIZLI: 'red' };
const SECTION_ORDER = ['AMAC', 'POZISYON', 'ROL', 'YETKI', 'DIGER'];
function dutiesTab(e, m) {
  const levels = m.duty_levels || { GENEL: 'Genel', KURUM_ICI: 'Kurum İçi', GIZLI: 'Gizli', COK_GIZLI: 'Çok Gizli' };
  const sections = m.duty_sections || { AMAC: 'Görevin Amacı', POZISYON: 'Uçuş Ekibi Pozisyonuna Özgü Görevler', ROL: 'Rollere Göre Görev ve Sorumluluklar', YETKI: 'Yetki ve Sınırlar', DIGER: 'Diğer' };
  const box = h('div', { class: 'duty-wrap' });
  const levelSel = (cur = 'KURUM_ICI') => h('select', { class: 'input duty-level' }, Object.entries(levels).map(([k, l]) => h('option', { value: k, selected: k === cur }, l)));
  const sectionSel = (cur = 'POZISYON') => h('select', { class: 'input duty-level' }, SECTION_ORDER.map(k => h('option', { value: k, selected: k === cur }, sections[k])));
  const save = async (url, method, body) => { try { e.duties = await api[method](url, body); draw(); } catch (err) { toastError(err); } };

  // Üst bilgiler kartı
  const infoCard = () => {
    const i = e.isg || {};
    const f = {
      flight_position: h('input', { class: 'input', value: i.flight_position || '', placeholder: 'ör. Pilot / Uçuş Komutanı' }),
      supervisor: h('input', { class: 'input', value: i.supervisor || '', placeholder: 'ör. Uçuş Test Koordinatörü (Saha Amiri)' }),
      deputy_id: h('select', { class: 'input' }, h('option', { value: '' }, 'Vekil seçin')),
      deputy_note: h('input', { class: 'input', value: i.deputy_note || '', placeholder: 'Vekil yoksa açıklama' }),
      emergency_duty: h('textarea', { class: 'input', rows: 2, placeholder: 'Acil durumda üstlendiği görev' }, i.emergency_duty || ''),
      duty_doc_no: h('input', { class: 'input', value: i.duty_doc_no || '', placeholder: 'ör. GKT-İSG-GT-CAYMAZ-01-07' }),
      duty_rev: h('input', { class: 'input', value: i.duty_rev || '', placeholder: 'ör. Rev. 00 — 01.10.2026' }),
    };
    api.get('/api/hr/employees').then(list => {
      list.filter(x => x.status === 'AKTIF' && x.id !== e.id).forEach(x => f.deputy_id.append(h('option', { value: x.id, selected: x.id === i.deputy_id }, x.name || `${x.first_name} ${x.last_name}`)));
    }).catch(() => {});
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Bilgileri Kaydet');
    saveBtn.addEventListener('click', async () => {
      const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, k === 'deputy_id' ? (el.value ? Number(el.value) : null) : el.value]));
      try { e.isg = { ...e.isg, ...(await api.put(`/api/hr/employees/${e.id}/isg`, body)) }; toast('Görev tanımı bilgileri kaydedildi'); }
      catch (err) { toastError(err); }
    });
    const fld = (label, el, cls = '') => h('label', { class: `field ${cls}` }, h('span', null, label), el);
    return h('div', { class: 'card card-pad duty-info' },
      h('div', { class: 'tv-bar' }, h('b', null, 'Görev Bilgileri'), h('span', { class: 'spacer' }),
        h('button', { class: 'btn', type: 'button', onclick: () => printDutyDoc(e, m) }, '🖨 Görev Tanımını Yazdır')),
      h('div', { class: 'duty-info-grid' },
        fld('Uçuş ekibi pozisyonu', f.flight_position), fld('Bağlı olduğu amir', f.supervisor),
        fld('Vekili', f.deputy_id), fld('Vekil notu', f.deputy_note),
        fld('Acil durum görevi', f.emergency_duty, 'wide'),
        fld('Doküman no', f.duty_doc_no), fld('Revizyon / tarih', f.duty_rev)),
      h('div', { class: 'duty-sign' },
        i.duty_signed_file
          ? [h('span', { class: 'badge green' }, t('İmzalı (tebellüğ) · {d}', { d: fmtDate(i.duty_signed_at) })),
            h('a', { class: 'btn sm', href: fileUrl(i.duty_signed_file), target: '_blank', rel: 'noopener' }, 'Taramayı Aç'),
            h('button', { class: 'btn sm ghost danger-text', type: 'button', onclick: async () => {
              if (!await confirmDialog('İmzalı belgeyi kaldır', 'İmzalı görev tanımı taraması kaldırılsın mı?', { okLabel: 'Kaldır', danger: true })) return;
              try { e.isg = await api.del(`/api/hr/employees/${e.id}/duty-signed`); draw(); } catch (err) { toastError(err); }
            } }, 'Kaldır')]
          : [h('span', { class: 'badge yellow' }, 'İmzalı tebellüğ yok'),
            uploadBtn('İmzalı Taramayı Yükle', async file => { const fd = new FormData(); fd.append('file', file); e.isg = await api.post(`/api/hr/employees/${e.id}/duty-signed`, fd); draw(); toast('İmzalı görev tanımı yüklendi'); })],
        h('span', { class: 'spacer' }), saveBtn));
  };
  const uploadBtn = (label, fn) => {
    const inp = h('input', { type: 'file', accept: '.pdf,.jpg,.jpeg,.png,.webp,.heic', hidden: true });
    inp.addEventListener('change', async () => { const fl = inp.files[0]; inp.value = ''; if (fl) { try { await fn(fl); } catch (err) { toastError(err); } } });
    return h('span', null, inp, h('button', { class: 'btn sm', type: 'button', onclick: () => inp.click() }, label));
  };

  const item = (d, list) => {
    const i = list.indexOf(d);
    const move = async dir => {
      const all = e.duties.map(x => x.id); const a = all.indexOf(d.id), b = all.indexOf(list[i + dir]?.id);
      if (b < 0) return; [all[a], all[b]] = [all[b], all[a]];
      save(`/api/hr/employees/${e.id}/duties-order`, 'put', { ids: all });
    };
    return h('li', { class: `duty-item lv-${d.level}` },
      h('div', { class: 'duty-text' }, d.text),
      h('div', { class: 'duty-side' },
        h('span', { class: `badge ${DUTY_TONE[d.level] || 'gray'}` }, levels[d.level] || d.level),
        h('button', { class: 'btn xs', title: 'Yukarı', disabled: i === 0, onclick: () => move(-1) }, '↑'),
        h('button', { class: 'btn xs', title: 'Aşağı', disabled: i === list.length - 1, onclick: () => move(1) }, '↓'),
        h('button', { class: 'btn xs', onclick: () => edit(d) }, 'Düzenle'),
        h('button', { class: 'btn xs ghost danger-text', onclick: () => remove(d) }, 'Sil')));
  };
  const edit = d => {
    const ta = h('textarea', { class: 'input', rows: 4 }, d.text);
    const ls = levelSel(d.level), ss = sectionSel(d.section || 'DIGER');
    const role = h('input', { class: 'input', value: d.role || '', placeholder: 'Rol (ör. Pilot)' });
    const phase = h('input', { class: 'input', value: d.phase || '', placeholder: 'Aşama (ör. Uçuş öncesi)' });
    modal({ title: 'Görev tanımı maddesi', body: h('div', null, ta, h('div', { class: 'row' },
      h('label', { class: 'field' }, h('span', null, 'Bölüm'), ss), h('label', { class: 'field' }, h('span', null, 'Gizlilik derecesi'), ls)),
      h('div', { class: 'row' }, h('label', { class: 'field' }, h('span', null, 'Rol'), role), h('label', { class: 'field' }, h('span', null, 'Aşama'), phase))),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        e.duties = await api.put(`/api/hr/employees/${e.id}/duties/${d.id}`, { text: ta.value, level: ls.value, section: ss.value, role: role.value, phase: phase.value });
        draw(); toast('Madde güncellendi');
      } }] });
  };
  const remove = async d => {
    if (!await confirmDialog('Maddeyi sil', t('“{text}” silinsin mi?', { text: d.text.slice(0, 80) }), { okLabel: 'Sil', danger: true })) return;
    save(`/api/hr/employees/${e.id}/duties/${d.id}`, 'del');
  };

  const draw = () => {
    const all = e.duties || [];
    const blocks = [];
    for (const sec of SECTION_ORDER) {
      const list = all.filter(d => (d.section || 'DIGER') === sec);
      if (!list.length) continue;
      const body = [];
      if (sec === 'ROL') {
        const groups = new Map();
        for (const d of list) { const k = `${d.role || 'Rol'}|${d.phase || ''}`; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(d); }
        let lastRole = null;
        for (const [k, g] of groups) {
          const [role, phase] = k.split('|');
          if (role !== lastRole) { body.push(h('div', { class: 'duty-role' }, role)); lastRole = role; }
          if (phase) body.push(h('div', { class: 'duty-phase' }, phase));
          body.push(h('ol', { class: 'duty-list' }, g.map(d => item(d, list))));
        }
      } else body.push(h('ol', { class: 'duty-list' }, list.map(d => item(d, list))));
      blocks.push(h('section', { class: 'duty-sec' }, h('h4', null, sections[sec], h('small', null, ` (${list.length})`)), ...body));
    }
    const text = h('textarea', { class: 'input', rows: 2, placeholder: 'Yeni madde yazın…' });
    const ss = sectionSel('POZISYON'), lvl = levelSel();
    const role = h('input', { class: 'input', placeholder: 'Rol (ör. Pilot)', hidden: true });
    const phase = h('input', { class: 'input', placeholder: 'Aşama (ör. Uçuş öncesi)', hidden: true });
    ss.addEventListener('change', () => { role.hidden = phase.hidden = ss.value !== 'ROL'; });
    const add = () => {
      if (!text.value.trim()) { toast('Maddeyi yazın', 'err'); return; }
      save(`/api/hr/employees/${e.id}/duties`, 'post', { text: text.value, level: lvl.value, section: ss.value, role: role.value, phase: phase.value });
    };
    text.addEventListener('keydown', ev => { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) add(); });
    clear(box, infoCard(),
      h('div', { class: 'card card-pad duty-card' },
        h('div', { class: 'tv-bar' }, h('b', null, t('Görev Tanımı Maddeleri ({n})', { n: all.length })),
          h('span', { class: 'small muted' }, 'Genel ve Kurum İçi maddeler saha görev raporunda kullanılır; Gizli / Çok Gizli maddeler yalnızca burada görünür.')),
        blocks.length ? blocks : h('div', { class: 'empty small' }, 'Henüz görev tanımı yok. Aşağıdan madde ekleyin.'),
        h('div', { class: 'duty-add' }, text, h('div', { class: 'duty-add-row' }, ss, role, phase, lvl,
          h('span', { class: 'spacer' }), h('button', { class: 'btn primary', onclick: add }, '＋ Madde Ekle')))));
  };
  draw();
  return box;
}

// Sağlık raporları: dosya + başlama / bitiş tarihi; rapor süresince personel raporlu görünür ve sisteme giriş yapamaz
function healthTab(e) {
  const box = h('div', { class: 'card card-pad' });
  const today = new Date().toISOString().slice(0, 10);
  const add = () => {
    const s = h('input', { class: 'input', type: 'date', value: today });
    const t = h('input', { class: 'input', type: 'date', value: today });
    const note = h('input', { class: 'input', placeholder: 'Not (ops.): ör. hastane, tanı kodu yazmayın' });
    const file = h('input', { class: 'input', type: 'file', accept: '.pdf,.jpg,.jpeg,.png,.webp,.heic' });
    modal({ title: 'Sağlık raporu ekle', body: h('div', null,
      h('div', { class: 'row' }, h('label', { class: 'field' }, h('span', null, 'Başlama'), s), h('label', { class: 'field' }, h('span', null, 'Bitiş'), t)),
      h('label', { class: 'field' }, h('span', null, 'Rapor dosyası'), file), h('label', { class: 'field' }, h('span', null, 'Not'), note),
      h('p', { class: 'small muted' }, 'Bu tarihler arasında personel sistemde “Raporlu” görünür ve sisteme giriş yapamaz; açık oturumu kapanır.')),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        const fd = new FormData(); fd.append('start_date', s.value); fd.append('end_date', t.value); fd.append('note', note.value);
        if (file.files[0]) fd.append('file', file.files[0]);
        e.health_reports = await api.post(`/api/hr/employees/${e.id}/health-reports`, fd); draw(); toast('Sağlık raporu kaydedildi');
      } }] });
  };
  const draw = () => {
    const rows = e.health_reports || [];
    clear(box,
      h('div', { class: 'tv-bar' }, h('b', null, t('Sağlık Raporları ({n})', { n: rows.length })),
        h('span', { class: 'small muted' }, 'Rapor süresince personel raporlu görünür ve sisteme giremez.'),
        h('span', { class: 'spacer' }), h('button', { class: 'btn sm primary', onclick: add }, '＋ Rapor Ekle')),
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, ['Başlama', 'Bitiş', 'Gün', 'Durum', 'Dosya', 'Not', 'Ekleyen', ''].map(c => h('th', null, c)))),
        h('tbody', null, rows.map(r => {
          const days = Math.round((new Date(r.end_date) - new Date(r.start_date)) / 864e5) + 1;
          const st = r.start_date <= today && r.end_date >= today ? ['Şu an raporlu', 'yellow'] : r.start_date > today ? ['İleri tarihli', 'blue'] : ['Bitti', 'gray'];
          return h('tr', null, h('td', null, fmtDate(r.start_date)), h('td', null, fmtDate(r.end_date)), h('td', { class: 'num' }, days),
            h('td', null, h('span', { class: `badge ${st[1]}` }, st[0])),
            h('td', null, r.file ? h('a', { href: fileUrl(r.file), target: '_blank', rel: 'noopener' }, r.file_name || 'Aç') : '—'),
            h('td', { class: 'wrap small' }, r.note || ''), h('td', { class: 'small muted' }, r.created_by_name || ''),
            h('td', null, h('button', { class: 'btn xs ghost danger-text', onclick: async () => {
              if (!await confirmDialog('Raporu sil', t('{a} – {b} raporu silinsin mi?', { a: fmtDate(r.start_date), b: fmtDate(r.end_date) }), { okLabel: 'Sil', danger: true })) return;
              try { e.health_reports = await api.del(`/api/hr/employees/${e.id}/health-reports/${r.id}`); draw(); } catch (err) { toastError(err); }
            } }, 'Sil')));
        }))))
        : h('div', { class: 'empty small' }, 'Sağlık raporu yok.'));
  };
  draw();
  return box;
}

// KKD / Eğitimler / Riskler: kişiye özel İSG listeleri
const ISG_TABS = {
  ppe: { title: 'Kişisel Koruyucu Donanımlar (KKD)', hint: 'Kişinin kullanması gereken KKD, standardı ve kullanım yeri; teslim tarihi zimmet takibi içindir.',
    cols: [['name', 'KKD (standart)'], ['usage', 'Kullanım yeri / zamanı'], ['issued_at', 'Teslim tarihi', 'date'], ['note', 'Not']] },
  trainings: { title: 'Zorunlu Eğitim ve Yeterlilikler', hint: 'Alındığı tarih ve geçerlilik bitişi girilir; süresi geçen ya da 30 gün içinde dolacak eğitimler renkle uyarılır.',
    cols: [['name', 'Eğitim / yeterlilik'], ['done_at', 'Alındığı tarih', 'date'], ['valid_until', 'Geçerlilik bitişi', 'date'], ['note', 'Not']] },
  hazards: { title: 'Göreve Özgü Tehlikeler ve Kontrol Tedbirleri', hint: 'Kişinin görevinde karşılaşabileceği tehlikeler ve uygulanacak kontrol tedbirleri.',
    cols: [['hazard', 'Tehlike'], ['control', 'Uygulanacak kontrol tedbiri', 'long']] },
};
function isgListTab(e, kind) {
  const cfg = ISG_TABS[kind];
  const box = h('div', { class: 'card card-pad' });
  const today = new Date().toISOString().slice(0, 10);
  const soon = new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10);
  const form = (it = {}) => {
    const els = Object.fromEntries(cfg.cols.map(([k, , t]) => [k, t === 'long' ? h('textarea', { class: 'input', rows: 3 }, it[k] || '')
      : h('input', { class: 'input', type: t === 'date' ? 'date' : 'text', value: it[k] || '' })]));
    modal({ title: it.id ? 'Kaydı düzenle' : 'Yeni kayıt', body: h('div', null, cfg.cols.map(([k, l]) => h('label', { class: 'field' }, h('span', null, l), els[k]))),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        const body = Object.fromEntries(Object.entries(els).map(([k, el]) => [k, el.value]));
        e.isg = it.id ? await api.put(`/api/hr/employees/${e.id}/isg/${kind}/${it.id}`, body) : await api.post(`/api/hr/employees/${e.id}/isg/${kind}`, body);
        draw();
      } }] });
  };
  const draw = () => {
    const rows = e.isg?.[kind] || [];
    clear(box,
      h('div', { class: 'tv-bar' }, h('b', null, `${cfg.title} (${rows.length})`), h('span', { class: 'small muted' }, cfg.hint),
        h('span', { class: 'spacer' }), h('button', { class: 'btn sm primary', onclick: () => form() }, '＋ Ekle')),
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table isg-table' },
        h('thead', null, h('tr', null, h('th', null, '#'), cfg.cols.map(([, l]) => h('th', null, l)), h('th', null, ''))),
        h('tbody', null, rows.map((r, i) => {
          const tone = kind === 'trainings' ? (!r.done_at ? 'isg-missing' : r.valid_until && r.valid_until < today ? 'isg-expired' : r.valid_until && r.valid_until <= soon ? 'isg-soon' : '') : '';
          return h('tr', { class: tone },
            h('td', { class: 'num muted' }, i + 1),
            cfg.cols.map(([k, , t]) => h('td', { class: t === 'long' ? 'wrap' : '' }, t === 'date' ? (r[k] ? fmtDate(r[k]) : '—') : (r[k] || '—'))),
            h('td', { class: 'nowrap' }, h('button', { class: 'btn xs', onclick: () => form(r) }, 'Düzenle'),
              h('button', { class: 'btn xs ghost danger-text', onclick: async () => {
                if (!await confirmDialog('Kaydı sil', t('“{text}” silinsin mi?', { text: (r[cfg.cols[0][0]] || '').slice(0, 60) }), { okLabel: 'Sil', danger: true })) return;
                try { e.isg = await api.del(`/api/hr/employees/${e.id}/isg/${kind}/${r.id}`); draw(); } catch (err) { toastError(err); }
              } }, 'Sil')));
        }))))
        : h('div', { class: 'empty small' }, 'Kayıt yok.'));
  };
  draw();
  return box;
}

// Görev Matrisi: personel – rol – uçuş ekibi pozisyonu – vekil – acil durum görevi (yazdırılabilir; Excel düğmesi otomatik)
async function renderMatrix(view, head) {
  const rows = await api.get('/api/hr/matrix');
  const filled = rows.filter(r => r.flight_position || r.emergency_duty || r.duty_count);
  const all = h('input', { type: 'checkbox' });
  const body = h('div');
  const draw = () => {
    const list = all.checked ? rows : filled;
    clear(body, list.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table matrix-table' },
      h('thead', null, h('tr', null, ['#', 'Personel', 'Sistem rolleri', 'Uçuş ekibi pozisyonu', 'Vekili', 'Acil durum görevi', 'Tebellüğ'].map(c => h('th', null, c)))),
      h('tbody', null, list.map((r, i) => h('tr', { class: 'click', onclick: () => { setPref('hr.tab', 'isg'); setPref('hr.sub', 'duties'); location.hash = `#/hr/${r.id}`; } },
        h('td', { class: 'num muted' }, i + 1), h('td', null, h('b', null, r.name), r.title ? h('div', { class: 'small muted' }, r.title) : null),
        h('td', { class: 'wrap small' }, r.roles.join(', ') || '—'), h('td', { class: 'wrap' }, r.flight_position || '—'),
        h('td', { class: 'wrap small' }, r.deputy_name || r.deputy_note || '—'), h('td', { class: 'wrap small' }, r.emergency_duty || '—'),
        h('td', null, r.duty_signed_at ? h('span', { class: 'badge green' }, fmtDate(r.duty_signed_at)) : h('span', { class: 'badge gray' }, 'Yok')))))))
      : h('div', { class: 'card empty' }, 'Henüz görev tanımı girilmiş personel yok. Personel › Görev Tanımı sekmesinden girin.'));
  };
  all.addEventListener('change', draw);
  clear(view, head('Personel – rol – uçuş ekibi görev matrisi ve acil durum görev dağılımı',
    [h('label', { class: 'check' }, all, 'Tüm aktif personel')]), body);
  draw();
}

// Görev tanımı belgesi (İSG): A–J bölümleri ve tebliğ-tebellüğ imza alanı; ortak bölümler İSG genel hükümlerinden
async function printDutyDoc(e, m) {
  let g = {};
  try { g = await api.get('/api/hr/isg-general'); } catch { /* */ }
  const { printPage, head, foot } = await import('../print.js');
  const i = e.isg || {};
  const sections = m.duty_sections || {};
  const name = e.name || `${e.first_name} ${e.last_name}`;
  const ul = items => h('ul', { class: 'dd-list' }, items.map(t => h('li', null, t)));
  const by = s => (e.duties || []).filter(d => (d.section || 'DIGER') === s);
  const roleBlock = () => {
    const out = []; let lastRole = null, lastPhase = null; let cur = null;
    for (const d of by('ROL')) {
      if (d.role !== lastRole) { out.push(h('h4', { class: 'dd-role' }, d.role || 'Rol')); lastRole = d.role; lastPhase = null; }
      if (d.phase !== lastPhase) { if (d.phase) out.push(h('div', { class: 'dd-phase' }, d.phase)); lastPhase = d.phase; cur = h('ul', { class: 'dd-list' }); out.push(cur); }
      if (!cur) { cur = h('ul', { class: 'dd-list' }); out.push(cur); }
      cur.append(h('li', null, d.text));
    }
    return out;
  };
  const kv = rows => h('table', { class: 'pf-table' }, h('tbody', null, rows.filter(Boolean).map(([k, v]) => h('tr', null, h('th', null, k), h('td', null, v || '—')))));
  const tbl = (cols, rows) => h('table', { class: 'pf-table pf-list' }, h('thead', null, h('tr', null, cols.map(c => h('th', null, c)))),
    h('tbody', null, rows.map(r => h('tr', null, r.map(c => h('td', null, c || ''))))));
  const signs = ['Tebellüğ Eden (Personel)', 'Tebliğ Eden (Birim Amiri)', 'İSG Uzmanı', 'İşveren / İşveren Vekili'];
  printPage(h('div', { class: 'pf-page pf-flow dd-doc' },
    head(COMPANY, 'GÖREV TANIMI', [['Personel', name], ['Doküman', i.duty_doc_no || g.doc_no || '—'], ['Revizyon', i.duty_rev || g.rev || '—']]),
    kv([['Ad Soyad', name], ['Görevi / unvanı', e.title], ['Uçuş ekibi pozisyonu', i.flight_position], ['Bağlı olduğu amir', i.supervisor],
      ['Vekili', i.deputy_name || i.deputy_note], g.place ? ['Çalışma yeri', g.place] : null]),
    by('AMAC').length ? [h('h2', { class: 'pf-h2' }, `A. ${sections.AMAC || 'Görevin Amacı'}`), h('p', null, by('AMAC').map(d => d.text).join(' '))] : null,
    by('POZISYON').length ? [h('h2', { class: 'pf-h2' }, `B. ${sections.POZISYON}`), ul(by('POZISYON').map(d => d.text))] : null,
    by('ROL').length ? [h('h2', { class: 'pf-h2' }, `C. ${sections.ROL}`), ...roleBlock()] : null,
    g.common?.length ? [h('h2', { class: 'pf-h2' }, 'D. İSG Yükümlülükleri (Tüm Personel)'), ul(g.common)] : null,
    i.hazards?.length ? [h('h2', { class: 'pf-h2' }, 'E. Göreve Özgü Tehlikeler ve Kontrol Tedbirleri'), tbl(['Tehlike', 'Uygulanacak kontrol tedbiri'], i.hazards.map(x => [x.hazard, x.control]))] : null,
    i.ppe?.length ? [h('h2', { class: 'pf-h2' }, 'F. Kişisel Koruyucu Donanımlar (KKD)'), tbl(['KKD (standart)', 'Kullanım yeri / zamanı'], i.ppe.map(x => [x.name, x.usage]))] : null,
    by('YETKI').length ? [h('h2', { class: 'pf-h2' }, `G. ${sections.YETKI}`), ul(by('YETKI').map(d => d.text))] : null,
    i.trainings?.length ? [h('h2', { class: 'pf-h2' }, 'H. Zorunlu Eğitim ve Yeterlilikler'), ul(i.trainings.map(x => x.name + (x.done_at ? ` — alındı: ${fmtDate(x.done_at)}` : '')))] : null,
    i.emergency_duty ? [h('h2', { class: 'pf-h2' }, 'I. Acil Durum Görevi'), h('p', null, i.emergency_duty),
      h('p', { class: 'small' }, 'Acil durumda Saha Amirinin talimatlarına uyar, toplanma noktasına gider ve sayıma katılır; yaralanma halinde 112 aranır.')] : null,
    h('h2', { class: 'pf-h2' }, 'J. Tebliğ ve Tebellüğ'),
    h('p', null, 'Bu görev tanımını okudum, anladım; görevimle ilgili İSG eğitimlerini aldım ve belirtilen kurallara uyacağımı taahhüt ederim. Bir nüshası tarafıma teslim edilmiştir.'),
    h('div', { class: 'dd-signs' }, signs.map((t, k) => h('div', { class: 'pf-sign' }, h('div', { class: 'pf-sign-title' }, t),
      h('div', { class: 'pf-sign-line' }, h('span', null, 'Ad Soyad:'), h('b', null, k === 0 ? name : '')),
      h('div', { class: 'pf-sign-line' }, h('span', null, 'Tarih:')), h('div', { class: 'pf-sign-box' }, 'İmza')))),
    foot(COMPANY, `${i.duty_doc_no || ''} · ${name}`)), `Görev tanımı ${name}`);
}

function addressesTab(e, m) {
  const setPrimary = async a => {
    try { await api.put(`/api/hr/employees/${e.id}/addresses/${a.id}`, { ...a, is_primary: true }); toast('Birincil adres değişti'); reload(); } catch (err) { toastError(err); }
  };
  const remove = async a => {
    if (!await confirmDialog('Adresi sil', t('{label} adresi silinsin mi?', { label: a.label }), { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/hr/employees/${e.id}/addresses/${a.id}`); toast('Adres silindi'); reload(); } catch (err) { toastError(err); }
  };
  return h('div', { class: 'card card-pad' },
    h('div', { class: 'tv-bar' }, h('b', null, 'Adresler'), h('span', { class: 'small muted' }, 'Birincil adres personel kartında görünür'),
      h('span', { class: 'spacer' }), h('button', { class: 'btn sm primary', onclick: () => addressForm(e, m) }, '＋ Adres Ekle')),
    e.addresses.length ? h('div', { class: 'addr-grid' }, e.addresses.map(a => h('div', { class: `addr-card ${a.is_primary ? 'primary' : ''}` },
      h('div', { class: 'addr-head' }, h('b', null, a.label), a.is_primary ? h('span', { class: 'badge blue' }, 'Birincil') : null),
      h('div', { class: 'addr-text' }, a.address),
      a.district || a.city || a.postal_code ? h('div', { class: 'small' }, [[a.district, a.city].filter(Boolean).join(' / '), a.postal_code].filter(Boolean).join(' · ')) : null,
      a.note ? h('div', { class: 'small muted' }, a.note) : null,
      h('div', { class: 'addr-actions' },
        h('button', { class: 'btn sm', onclick: () => addressForm(e, m, a) }, 'Düzenle'),
        a.is_primary ? null : h('button', { class: 'btn sm', onclick: () => setPrimary(a) }, 'Birincil Yap'),
        h('button', { class: 'btn sm ghost danger-text', onclick: () => remove(a) }, 'Sil')))))
      : h('div', { class: 'empty small' }, 'Adres girilmemiş. “Adres Ekle” ile ekleyin.'));
}

function addressForm(e, m, a = null) {
  const labels = [...new Set([...(m.address_labels || []), ...(a ? [a.label] : [])])];
  const label = h('select', { class: 'input' }, labels.map(l => h('option', { value: l, selected: (a?.label || (e.addresses.length ? 'Diğer' : 'Ev')) === l }, l)));
  const address = h('textarea', { class: 'input', rows: 3, placeholder: 'Mahalle, cadde / sokak, bina no, daire' }, a?.address || '');
  const district = h('input', { class: 'input', value: a?.district || '' });
  const city = h('input', { class: 'input', value: a?.city || '' });
  const postal = h('input', { class: 'input', value: a?.postal_code || '', inputmode: 'numeric', maxlength: 5 });
  const note = h('input', { class: 'input', value: a?.note || '', placeholder: 'ör. Acil durumda annesinin adresi' });
  const primary = h('input', { type: 'checkbox', checked: a ? !!a.is_primary : !e.addresses.length });
  modal({
    title: a ? 'Adresi Düzenle' : 'Adres Ekle',
    body: h('div', null, field('Adres türü', label), field('Adres *', address),
      h('div', { class: 'form-grid' }, field('İlçe', district), field('İl', city), field('Posta kodu', postal)),
      field('Not', note), h('label', { class: 'check' }, primary, 'Birincil adres')),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const body = { label: label.value, address: address.value, district: district.value, city: city.value, postal_code: postal.value, note: note.value, is_primary: primary.checked };
      if (a) await api.put(`/api/hr/employees/${e.id}/addresses/${a.id}`, body);
      else await api.post(`/api/hr/employees/${e.id}/addresses`, body);
      toast('Adres kaydedildi');
      reload();
    } }],
  });
  address.focus();
}

// ---------- Ailesi: aile üyeleri + yakınlık; yüz tanımada eğitilebilir
const RELATIONS = ['Eş', 'Çocuk', 'Anne', 'Baba', 'Kardeş', 'Nişanlı', 'Diğer'];
function familyTab(e) {
  const wrap = h('div', { class: 'card card-pad' });
  let recognized = {};   // family_id → kamera görülme kırpıkları
  const remove = async f => {
    if (!await confirmDialog('Aile üyesini sil', t('{n} silinsin mi? Yüz tanıma eğitim verisi de silinir.', { n: f.full_name }), { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/hr/employees/${e.id}/family/${f.id}`); toast('Aile üyesi silindi'); reload(); } catch (err) { toastError(err); }
  };
  const draw = () => clear(wrap,
    h('div', { class: 'tv-bar' }, h('b', null, 'Ailesi'), h('span', { class: 'small muted' }, 'Aile üyeleri ve yakınlık derecesi; yüz tanımada eğitilebilir'),
      h('span', { class: 'spacer' }), h('button', { class: 'btn sm primary', onclick: () => familyForm(e) }, '＋ Aile Üyesi Ekle')),
    e.family?.length ? h('div', { class: 'addr-grid' }, e.family.map(f => {
      const shots = recognized[f.id] || [];
      return h('div', { class: 'addr-card' },
        h('div', { class: 'addr-head' }, h('b', null, f.full_name), f.relation ? h('span', { class: 'badge blue' }, f.relation) : null,
          f.face_count ? h('span', { class: 'badge green' }, t('{n} eğitim', { n: f.face_count })) : null,
          shots.length ? h('span', { class: 'badge' }, t('{n} tanınma', { n: shots.length })) : null),
        f.birth_date ? h('div', { class: 'small' }, t('Doğum: {d}', { d: fmtDate(f.birth_date) })) : null,
        f.phone ? h('div', { class: 'small' }, f.phone) : null,
        f.note ? h('div', { class: 'small muted' }, f.note) : null,
        shots.length ? h('div', { class: 'fg-recognized' }, shots.slice(0, 5).map(s => h('img', { src: fileUrl(s.crop, 160), alt: '', loading: 'lazy', title: s.camera_name || '' }))) : null,
        h('div', { class: 'addr-actions' },
          h('button', { class: 'btn sm', onclick: () => familyForm(e, f) }, 'Düzelt'),
          h('button', { class: 'btn sm', onclick: () => familyFaceModal(e, f, recognized[f.id] || []) }, 'Yüz Tanıma Eğit'),
          h('button', { class: 'btn sm ghost danger-text', onclick: () => remove(f) }, 'Sil')));
    }))
      : h('div', { class: 'empty small' }, 'Aile üyesi eklenmemiş. “Aile Üyesi Ekle” ile ekleyin.'));
  draw();
  if (e.family?.length) api.get(`/api/hr/employees/${e.id}/family-recognized`).then(r => { recognized = r.shots || {}; draw(); }).catch(() => {});
  return wrap;
}

function familyForm(e, f = null) {
  const name = h('input', { class: 'input', value: f?.full_name || '', placeholder: 'Ad Soyad' });
  const relation = h('select', { class: 'input' }, RELATIONS.map(r => h('option', { value: r, selected: f?.relation === r }, r)));
  const birth = h('input', { type: 'date', class: 'input', value: f?.birth_date || '' });
  const phone = h('input', { class: 'input', value: f?.phone || '', placeholder: 'Telefon (ops.)' });
  const note = h('input', { class: 'input', value: f?.note || '', placeholder: 'Not (ops.)' });
  modal({
    title: f ? 'Aile Üyesini Düzenle' : 'Aile Üyesi Ekle',
    body: h('div', null, field('Ad Soyad *', name), field('Yakınlık', relation),
      h('div', { class: 'form-grid' }, field('Doğum tarihi', birth), field('Telefon', phone)), field('Not', note)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const body = { full_name: name.value, relation: relation.value, birth_date: birth.value, phone: phone.value, note: note.value };
      if (f) await api.put(`/api/hr/employees/${e.id}/family/${f.id}`, body);
      else await api.post(`/api/hr/employees/${e.id}/family`, body);
      toast('Aile üyesi kaydedildi'); reload();
    } }],
  });
  name.focus();
}

function familyFaceModal(e, f, recognized = []) {
  const grid = h('div', { class: 'fr-crops' });
  const status = h('span', { class: 'small muted' });
  const fileInp = h('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true });
  const base = `/api/hr/employees/${e.id}/family/${f.id}/faces`;
  const draw = async () => {
    let faces = [];
    try { faces = (await api.get(base)).faces; } catch { /* */ }
    clear(grid, faces.length ? faces.map(x => h('div', { class: 'fr-crop' },
      h('img', { src: fileUrl(x.crop, 160), alt: '', loading: 'lazy' }),
      h('button', { class: 'fr-crop-x', type: 'button', title: 'Sil', onclick: async () => {
        try { await api.del(`${base}/${x.id}`); draw(); } catch (err) { toastError(err); }
      } }, '×')))
      : h('div', { class: 'muted', style: { padding: '8px 0' } }, 'Henüz eğitim fotoğrafı yok.'));
  };
  fileInp.addEventListener('change', async () => {
    const files = [...fileInp.files]; fileInp.value = '';
    for (const file of files) {
      status.textContent = t('{name} işleniyor…', { name: file.name });
      const fd = new FormData(); fd.append('file', file);
      try { await api.post(base, fd); } catch (err) { toast(err.message || 'Yüz bulunamadı', 'err'); }
    }
    status.textContent = ''; draw();
  });
  modal({ title: t('{n} · Yüz Tanıma Eğitimi', { n: f.full_name }), wide: true,
    body: h('div', null,
      h('p', { class: 'small muted' }, 'Kişinin net, önden çekilmiş fotoğraflarını yükleyin. Kameralarda tanındığında adıyla görünür. Veri fabrikada (lokal) tutulur.'),
      h('div', { class: 'tv-bar' }, h('button', { class: 'btn sm primary', type: 'button', onclick: () => fileInp.click() }, '＋ Fotoğraf yükle'), fileInp, status),
      grid,
      recognized.length ? h('div', { style: { marginTop: '14px' } },
        h('b', null, t('Kameradan tanınan yüzler ({n})', { n: recognized.length })),
        h('p', { class: 'small muted' }, 'Tanımlanmayan kişilerden bu kişiye atanan kamera görülmeleri.'),
        h('div', { class: 'fg-recognized' }, recognized.map(s => h('img', { src: fileUrl(s.crop, 160), alt: '', loading: 'lazy', title: `${s.camera_name || ''} ${s.at ? fmtDateTime(s.at) : ''}` })))) : null),
    actions: [{ label: 'Kapat' }], onClose: reload });
  draw();
}

function leaveJobModal(e) {
  const end = dateIn(today());
  const reason = h('input', { class: 'input', placeholder: 'ör. İstifa, sözleşme bitişi' });
  modal({
    title: t('{name} · İşten Ayrılış', { name: e.name }), body: h('div', null, field('Ayrılış tarihi', end), field('Sebep', reason)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'danger', onClick: async () => {
      await api.post(`/api/hr/employees/${e.id}/leave-job`, { end_date: end.value, reason: reason.value }); reload();
    } }],
  });
}

function generalTab(e, m, ctx) {
  const staff = e.status === 'AKTIF' || e.status === 'AYRILDI';
  const f = {
    tc: h('input', { class: 'input mono', value: e.tc_no || '', inputmode: 'numeric', maxlength: 11 }),
    first: h('input', { class: 'input', value: e.first_name }), last: h('input', { class: 'input', value: e.last_name }),
    gender: h('select', { class: 'input' }, [['', 'Seçin'], ['E', 'Erkek'], ['K', 'Kadın']].map(([v, l]) => h('option', { value: v, selected: (e.gender || '') === v }, l))),
    birth: dateIn(e.birth_date), phone: h('input', { class: 'input', value: e.phone || '' }), email: emailsInput(e.emails || (e.email ? [e.email] : [])),
    position: h('input', { class: 'input', value: e.position || '' }),
    source: h('select', { class: 'input' }, h('option', { value: '' }, '—'), m.sources.map(s => h('option', { value: s, selected: s === e.source }, s))),
    sourceNote: h('input', { class: 'input', value: e.source_note || '' }), applied: dateIn(e.applied_at),
    title: h('input', { class: 'input', value: e.title || '' }), dept: h('input', { class: 'input', value: e.department || '' }),
    salary: h('input', { class: 'input', type: 'number', min: 0, step: '0.01', value: e.salary ?? '' }), start: dateIn(e.start_date),
    note: h('textarea', { class: 'input', rows: 2 }, e.note || ''),
    foreign: h('input', { type: 'checkbox', checked: !!e.is_foreign }),
    nationality: h('input', { class: 'input', value: e.nationality || '', placeholder: 'ör. İran' }),
    security: h('input', { class: 'input mono', value: e.security_code || '', placeholder: 'MSB Tesis Güvenlik Belgesi kapsamında' }),
  };
  const natField = field('Uyruğu', f.nationality);
  const syncForeign = () => { natField.hidden = !f.foreign.checked; };
  f.foreign.addEventListener('change', syncForeign);
  syncForeign();
  const save = h('button', { class: 'btn primary' }, 'Kaydet');
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      await api.put(`/api/hr/employees/${e.id}`, {
        tc_no: f.tc.value, first_name: f.first.value, last_name: f.last.value, gender: f.gender.value || null, birth_date: f.birth.value || null,
        is_foreign: f.foreign.checked, nationality: f.nationality.value, security_code: f.security.value,
        phone: f.phone.value, email: f.email.value, emails: f.email.values, position: f.position.value, source: f.source.value || null,
        source_note: f.sourceNote.value, applied_at: f.applied.value || null, note: f.note.value,
        title: f.title.value, department: f.dept.value, salary: f.salary.value === '' ? null : Number(f.salary.value), start_date: f.start.value || null,
      });
      toast('Personel bilgileri kaydedildi'); reload();
    } catch (err) { toastError(err); } finally { save.disabled = false; }
  });
  // CV
  const cvIn = h('input', { type: 'file', hidden: true, accept: '.pdf,.doc,.docx,.odt,.jpg,.jpeg,.png' });
  cvIn.addEventListener('change', async () => {
    const fd = new FormData(); fd.append('file', cvIn.files[0]);
    try { await upload(`/api/hr/employees/${e.id}/cv`, fd); toast('CV yüklendi'); reload(); } catch (err) { toastError(err); }
  });
  // Kullanıcı eşleştirme
  const userSel = h('select', { class: 'input' }, h('option', { value: '' }, 'Sistem kullanıcısı değil'));
  api.get('/api/hr/users').then(list => list.forEach(u => userSel.append(h('option', { value: u.id, selected: u.id === e.user_id },
    `${u.full_name} (${u.username})${u.employee_id && u.employee_id !== e.id ? (u.tc_no ? ' · başka personele bağlı' : ' · bilgisi girilmemiş kaydı birleştirilir') : ''}`)))).catch(() => {});
  userSel.addEventListener('change', async () => {
    try {
      await api.put(`/api/hr/employees/${e.id}/user`, { user_id: userSel.value ? Number(userSel.value) : null });
      toast('Kullanıcı bağlantısı güncellendi'); reload();
    } catch (err) { toastError(err); reload(); }
  });
  return h('div', { class: 'hr-general' },
    h('div', { class: 'card card-pad' }, h('h3', null, 'Kişisel bilgiler'),
      h('div', { class: 'form-grid' }, field(e.is_foreign ? 'Yabancı Kimlik Numarası' : 'TC Kimlik Numarası', f.tc), field('Ad', f.first), field('Soyad', f.last), field('Cinsiyet', f.gender),
        h('label', { class: 'field set-toggle', style: { alignSelf: 'end' } }, f.foreign, h('span', null, h('b', null, 'Yabancı uyruklu'), h('small', null, 'Pasaport ve çalışma izni zorunlu olur'))), natField,
        field('Kişi Güvenlik Kodu', f.security, 'MSB Tesis Güvenlik Belgesi olan firmamızca personel adına başvurularak alınır'),
        field('Doğum tarihi', f.birth), field('Telefon', f.phone), field('E-posta', f.email))),
    staff ? h('div', { class: 'card card-pad' }, h('h3', null, 'Görev ve ücret'),
      h('div', { class: 'form-grid' }, field('Görevi', f.title), field('Departman', f.dept), field('Maaşı (₺)', f.salary), field('Resmi işe başlama tarihi', f.start)),
      h('div', { class: 'small muted' }, 'Görev, maaş ve işe başlama tarihi değişiklikleri Geçmiş sekmesine yazılır.')) : null,
    h('div', { class: 'card card-pad' }, h('h3', null, 'İş başvurusu'),
      h('div', { class: 'form-grid' }, field('Başvurduğu pozisyon', f.position), field('Başvuru kaynağı', f.source), field(f.source.value === 'Referans' ? 'Referans veren' : 'Kaynak açıklaması', f.sourceNote), field('Başvuru tarihi', f.applied)),
      h('div', { class: 'hr-cv' }, h('b', null, 'CV: '), e.cv_file ? h('a', { href: fileUrl(e.cv_file), target: '_blank', rel: 'noopener' }, e.cv_name || 'CV') : h('span', { class: 'muted' }, 'Yüklenmemiş'),
        h('button', { class: 'btn sm', onclick: () => cvIn.click() }, e.cv_file ? 'Değiştir' : 'CV Yükle'), cvIn)),
    h('div', { class: 'card card-pad' }, h('h3', null, 'Sistem kullanıcısı'),
      field('Eşleşen kullanıcı', userSel, 'Her kullanıcı aynı zamanda personeldir. Yeni kullanıcı hesabı Kullanıcı Yönetimi’nden açılır; adı aynıysa bu kayda otomatik bağlanır.'),
      field('Not', f.note)),
    h('div', { class: 'hr-save' }, save));
}

function filesTab(e, kinds, title) {
  const rows = Object.entries(kinds).map(([k, label]) => {
    const f = e.files[k];
    const needed = e.required.includes(k);
    const input = h('input', { type: 'file', hidden: true, accept: k === 'VESIKALIK' ? 'image/*' : '.pdf,.jpg,.jpeg,.png,.webp,.heic,.doc,.docx,.odt,.zip' });
    input.addEventListener('change', async () => {
      const fd = new FormData(); fd.append('file', input.files[0]);
      try { await upload(`/api/hr/employees/${e.id}/files/${k}`, fd); toast(t('{label} yüklendi', { label })); reload(); } catch (err) { toastError(err); }
    });
    const remove = async () => {
      if (!confirm(t('{label} {act} mı?', { label, act: f && !f.approved ? 'reddedilsin' : 'kaldırılsın' }))) return;
      try { await api.del(`/api/hr/employees/${e.id}/files/${f.id}`); reload(); } catch (err) { toastError(err); }
    };
    const approve = async () => {
      try { await api.post(`/api/hr/employees/${e.id}/files/${f.id}/approve`); toast(t('{label} onaylandı', { label })); reload(); } catch (err) { toastError(err); }
    };
    const pending = f && !f.approved;   // personelin yüklediği, İK onayı bekleyen evrak
    return h('div', { class: `hr-doc ${pending ? 'pending' : f ? 'ok' : needed ? 'miss' : 'na'}` },
      k === 'VESIKALIK' && f ? h('img', { class: 'hr-doc-photo', src: fileUrl(f.path, 128), alt: '' }) : h('span', { class: 'hr-doc-ico' }, pending ? '⏳' : f ? '✓' : needed ? '!' : '–'),
      h('div', { class: 'grow' }, h('b', null, label), pending ? h('span', { class: 'badge yellow', style: { marginLeft: '6px' } }, 'Onay bekliyor') : null,
        h('div', { class: 'small muted' }, f ? `${f.file_name} · ${fmtDateTime(f.created_at)} · ${f.uploaded_by_name || ''}${pending ? ' · personel yükledi' : ''}`
          : needed ? 'Eksik — yüklenmesi zorunlu' : 'Gerekli değil (kadın personel)')),
      f ? h('a', { class: 'btn sm', href: fileUrl(f.path), target: '_blank', rel: 'noopener' }, 'Aç / Görüntüle') : null,
      pending ? h('button', { class: 'btn sm primary', onclick: approve }, 'Onayla') : null,
      h('button', { class: `btn sm ${f ? '' : 'primary'}`, onclick: () => input.click() }, f ? 'Değiştir' : 'Yükle'),
      f ? h('button', { class: 'btn sm ghost', onclick: remove }, pending ? 'Reddet' : 'Kaldır') : null, input);
  });
  const missing = Object.keys(kinds).filter(k => e.required.includes(k) && !e.files[k]).length;
  const pendingN = Object.keys(kinds).filter(k => e.files[k] && !e.files[k].approved).length;
  return h('div', { class: 'card card-pad' },
    h('div', { class: 'tv-bar' }, h('b', null, title),
      pendingN ? h('span', { class: 'badge yellow' }, t('{n} onay bekliyor', { n: pendingN })) : null,
      missing ? h('span', { class: 'badge red' }, t('{n} eksik', { n: missing })) : h('span', { class: 'badge green' }, 'Tamam')),
    rows);
}

function leavesTab(e) {
  const year = String(new Date().getFullYear());
  const used = k => e.leaves.filter(l => l.status === 'ONAYLANDI' && l.kind === k && (l.start_date || '').startsWith(year)).reduce((a, l) => a + (l.days || 0), 0);
  return h('div', null,
    h('div', { class: 'stat-strip' },
      h('div', { class: 'stat' }, h('span', { class: 'v' }, used('UCRETLI')), h('span', { class: 'l' }, t('{year} ücretli izin (gün)', { year }))),
      h('div', { class: 'stat' }, h('span', { class: 'v' }, used('UCRETSIZ')), h('span', { class: 'l' }, t('{year} ücretsiz izin (gün)', { year }))),
      h('div', { class: 'stat' }, h('span', { class: 'v' }, e.leaves.filter(l => l.status === 'BEKLIYOR').length), h('span', { class: 'l' }, 'Onay bekleyen')),
      h('div', { class: `stat ${e.unsigned_leaves ? 'alert' : ''}` }, h('span', { class: 'v' }, e.unsigned_leaves), h('span', { class: 'l' }, 'İmzalı formu eksik'))),
    e.leaves.length ? (() => { const v = leaveViews(e.leaves, { hr: true }); return h('div', null, h('div', { class: 'leave-view-bar' }, v.seg), v.box); })()
      : h('div', { class: 'card empty' }, 'İzin kaydı yok'));
}

function historyTab(e, kinds) {
  return h('div', { class: 'hr-general' },
    h('div', { class: 'card card-pad' }, h('h3', null, 'Geçmiş'),
      e.events.length ? h('ul', { class: 'hr-timeline' }, e.events.map(ev => h('li', null,
        h('b', null, ev.action), ev.detail ? h('div', null, ev.detail) : null,
        h('div', { class: 'small muted' }, `${fmtDateTime(ev.created_at)} · ${ev.user_name || 'Sistem'}`)))) : h('div', { class: 'muted' }, 'Kayıt yok')),
    e.file_history.length ? h('div', { class: 'card card-pad' }, h('h3', null, 'Yüklenen dosyalar'),
      h('ul', { class: 'stat-list' }, e.file_history.map(f => h('li', null,
        h('span', null, h('b', null, kinds[f.kind] || f.kind), ' · ', h('a', { href: fileUrl(f.path), target: '_blank', rel: 'noopener' }, f.file_name)),
        h('span', { class: 'small muted' }, `${fmtDateTime(f.created_at)} · ${f.uploaded_by_name || ''}`))))) : null);
}

// ---------- Kişisel › İzinlerim (her kullanıcı)
export async function renderMyLeaves(view) {
  const data = await api.get('/api/me/leaves');
  const add = h('button', { class: 'btn primary', onclick: () => leaveForm({ title: 'İzin Talebi', url: '/api/me/leaves', hint: 'Talebiniz İnsan Kaynakları onayına gider; İK tarihleri değiştirebilir.' }) }, '＋ İzin Talebi');
  const pending = data.items.filter(l => l.status === 'BEKLIYOR').length;
  clear(view,
    pageHead('İzinlerim', { back: '#/', sub: 'İzin talepleri ve İK kararları' }),
    moduleToolbar(add),
    h('div', { class: 'stat-strip' },
      h('div', { class: 'stat' }, h('span', { class: 'v' }, data.used_paid_this_year), h('span', { class: 'l' }, t('{year} kullanılan ücretli izin (gün)', { year: new Date().getFullYear() }))),
      h('div', { class: 'stat' }, h('span', { class: 'v' }, pending), h('span', { class: 'l' }, 'Onay bekleyen talep'))),
    data.items.length ? leaveTable(data.items, { mine: true }) : h('div', { class: 'card empty' }, 'Henüz izin talebiniz yok. “İzin Talebi” ile oluşturun.'));
}

// ---------- Evraklarım (Kişisel): personel kendi özlük evrakını yükler; eksik zorunlu evrak için son gün geri sayımı
export async function renderMyDocuments(view) {
  const data = await api.get('/api/me/documents');
  if (!data.employee) {
    clear(view, pageHead('Evraklarım', { back: '#/', sub: 'Özlük evrakı' }),
      h('div', { class: 'card empty' }, 'Hesabınız bir personel kaydına bağlı değil; yüklenecek özlük evrakınız yok.'));
    return;
  }
  const pick = (kind, label) => {
    const inp = h('input', { type: 'file', hidden: true, accept: '.pdf,.jpg,.jpeg,.png,.doc,.docx,.heic' });
    inp.addEventListener('change', async () => {
      if (!inp.files[0]) return;
      const fd = new FormData(); fd.append('file', inp.files[0]);
      try {
        await upload(`/api/me/documents/${kind}`, fd);
        toast(t('{label} yüklendi', { label }), 'success');
        window.dispatchEvent(new Event('caymaz:docs'));   // başlıktaki geri sayım ve bildirim tazelensin
        renderMyDocuments(view);
      } catch (err) { toastError(err); }
    });
    document.body.append(inp);
    inp.click();
    setTimeout(() => inp.remove(), 60000);
  };
  const left = data.deadline ? new Date(data.deadline) - new Date() : 0;
  const cd = left > 0 ? (() => { const m = Math.floor(left / 60000); return t('{d} gün {h} saat {m} dakika', { d: Math.floor(m / 1440), h: Math.floor((m % 1440) / 60), m: m % 60 }); })() : null;
  const extra = h('select', { class: 'input', style: { maxWidth: '260px' } }, h('option', { value: '' }, 'Diğer evrak türü seçin…'),
    Object.entries(data.optional || {}).map(([k, l]) => h('option', { value: k }, l)));
  clear(view,
    pageHead('Evraklarım', { back: '#/', sub: t('{name} · özlük dosyası', { name: data.employee.name }) }),
    data.missing ? h('div', { class: 'alert err docs-alert' },
      h('b', null, t('{n} adet zorunlu evrakınız eksik.', { n: data.missing })),
      cd ? h('span', null, t(' Tamamlamak için kalan süre: {cd} (son gün {d}).', { cd, d: fmtDateTime(data.deadline) })) : h('span', null, ' Süre doldu; lütfen hemen yükleyin.'),
      h('div', { class: 'small' }, 'Her satırdaki “Yükle” ile telefonunuzdan fotoğraf ya da PDF seçebilirsiniz. Yüklenen evrak İnsan Kaynakları’na iletilir.'))
      : h('div', { class: 'alert ok' }, 'Zorunlu evraklarınız tamam. Teşekkürler.'),
    h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Evrak', 'Durum', ''].map(t => h('th', null, t)))),
      h('tbody', null, data.kinds.map(k => h('tr', { class: !k.file && k.required ? 'docs-miss' : '' },
        h('td', null, h('b', null, k.label), k.required ? null : h('span', { class: 'small muted' }, ' (isteğe bağlı)')),
        h('td', null, k.file
          ? h('span', null, h('span', { class: `badge ${k.file.approved ? 'green' : 'yellow'}` }, k.file.approved ? 'Onaylandı' : 'Onay bekliyor'), ' ', h('a', { href: fileUrl(k.file.path), target: '_blank', rel: 'noopener' }, k.file.name),
            h('span', { class: 'small muted' }, ` · ${fmtDateTime(k.file.at)}`))
          : h('span', { class: 'badge red' }, 'Eksik')),
        h('td', { class: 'num' }, h('button', { class: `btn sm ${k.file ? '' : 'primary'}`, type: 'button', onclick: () => pick(k.kind, k.label) }, k.file ? 'Yenisini yükle' : 'Yükle')))))))),
    h('div', { class: 'card card-pad docs-extra' }, h('b', null, 'Başka bir evrak eklemek için'), extra,
      h('button', { class: 'btn', type: 'button', onclick: () => { if (extra.value) pick(extra.value, extra.selectedOptions[0].textContent); else toast('Önce evrak türünü seçin', 'err'); } }, 'Yükle')));
}

// ---------- PDKS giriş-çıkış (Firebird, salt okuma): gün bazında ilk giriş / son çıkış; eşleşmeyen kartlar elle bağlanır
async function renderAttendance(view, head, ctx) {
  clear(view, head('Personel giriş-çıkış kayıtları (PDKS cihazından)'), h('div', { class: 'card card-pad loading' }, 'PDKS verileri okunuyor…'));
  const today = new Date();
  const d0 = new Date(today); d0.setDate(d0.getDate() - 6);
  const iso = x => x.toISOString().slice(0, 10);
  let from = pref('hr.att.from', iso(d0)), to = pref('hr.att.to', iso(today));
  const body = h('div');
  const dFrom = h('input', { class: 'input', type: 'date', value: from });
  const dTo = h('input', { class: 'input', type: 'date', value: to });
  const load = async () => {
    from = dFrom.value; to = dTo.value; setPref('hr.att.from', from); setPref('hr.att.to', to);
    clear(body, h('div', { class: 'card card-pad loading' }, 'Okunuyor…'));
    let d;
    try { d = await api.get(`/api/hr/pdks/attendance?date_from=${from}&date_to=${to}`); }
    catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    if (!d.enabled) return clear(body, h('div', { class: 'card empty' }, d.message || 'PDKS bağlantısı tanımlı değil.'));
    if (d.error) return clear(body, h('div', { class: 'alert err', style: { margin: '12px 0' } }, 'PDKS’e bağlanılamadı: ' + d.error));
    const fmtd = s => s.slice(8, 10) + '.' + s.slice(5, 7);
    const dow = ['Pz', 'Pt', 'Sa', 'Ça', 'Pe', 'Cu', 'Ct'];
    const rows = d.rows.map(r => h('tr', { class: r.matched ? '' : 'att-unmatched' },
      h('td', null, h('b', null, r.name), r.title ? h('div', { class: 'small muted' }, r.title) : null,
        r.matched ? null : h('div', { class: 'small warn-text' }, 'Eşleşmedi · ', linkSel(r, load))),
      ...d.days.map(day => {
        const v = r.days[day];
        if (!v) return h('td', { class: 'att-cell att-absent' }, '—');
        const dur = v.dakika != null ? `${Math.floor(v.dakika / 60)}s ${String(v.dakika % 60).padStart(2, '0')}d` : '';
        return h('td', { class: 'att-cell' }, h('b', null, v.giris), v.cikis ? h('span', null, '→ ' + v.cikis) : h('span', { class: 'muted' }, 'çıkış yok'),
          dur ? h('div', { class: 'small muted' }, dur) : null);
      })));
    clear(body,
      d.unmatched.length ? h('div', { class: 'alert warn', style: { margin: '0 0 12px' } },
        t('PDKS’te eşleşmeyen {n} personel: {list}. Her satırdaki “Eşleşmedi” yanından personel seçerek bağlayın.', { n: d.unmatched.length, list: d.unmatched.join(', ') })) : null,
      h('div', { class: 'table-wrap' }, h('table', { class: 'att-table' },
        h('thead', null, h('tr', null, h('th', null, 'Personel'),
          ...d.days.map(day => h('th', null, fmtd(day), h('div', { class: 'small muted' }, dow[(new Date(day + 'T12:00')).getDay()]))))),
        h('tbody', null, rows))),
      h('p', { class: 'small muted', style: { marginTop: '8px' } }, 'Cihaz giriş/çıkış yönü tutmadığından günün ilk okuması giriş, son okuması çıkış kabul edilir. Veri PDKS’ten yalnızca okunur.'));
  };
  let empList = null;
  const linkSel = (r, reload) => {
    const sel = h('select', { class: 'input att-link' }, h('option', { value: '' }, 'Personel seç…'));
    (async () => {
      empList ??= (await api.get('/api/hr/employees')).filter(e => e.status === 'AKTIF' || e.status === 'AYRILDI');
      for (const e of empList) sel.append(h('option', { value: e.id }, `${e.first_name} ${e.last_name}${e.status === 'AYRILDI' ? ' (ayrıldı)' : ''}`));
    })();
    sel.addEventListener('change', async () => {
      if (!sel.value) return;
      try { await api.put('/api/hr/pdks/link', { kart_id: r.kart_id, employee_id: Number(sel.value) }); toast('Eşleştirildi'); reload(); }
      catch (err) { toastError(err); }
    });
    return sel;
  };
  // Görünüm: Tablo (PDKS giriş-çıkış) | İstihdam Gantt (işe başlama → ayrılış/bugün)
  let vmode = pref('hr.attView', 'table');
  const viewSeg = segmented([['table', 'Giriş-Çıkış'], ['gantt', 'İstihdam (Gantt)']], vmode, v => { vmode = v; setPref('hr.attView', v); paint(); });
  const paint = () => {
    const range = h('span', { class: 'att-range' }, field('Başlangıç', dFrom), field('Bitiş', dTo), h('button', { class: 'btn', type: 'button', onclick: load }, 'Göster'));
    clear(view, head(vmode === 'gantt' ? 'Personel istihdam süreleri (işe başlama → ayrılış / bugün)' : 'Personel giriş-çıkış kayıtları (PDKS cihazından)',
      [vmode === 'table' ? range : null, viewSeg]), body);
    if (vmode === 'gantt') return gantt();
    load();
  };
  const gantt = async () => {
    clear(body, h('div', { class: 'card card-pad loading' }, 'Yükleniyor…'));
    let list;
    try { list = (await api.get('/api/hr/employees')).filter(e => (e.status === 'AKTIF' || e.status === 'AYRILDI') && e.start_date); }
    catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    if (!list.length) return clear(body, h('div', { class: 'card empty' }, 'İşe başlama tarihi girili personel yok.'));
    const today = new Date(); const d = s => new Date(s + 'T12:00');
    const starts = list.map(e => d(e.start_date));
    let min = new Date(Math.min(...starts)); min = new Date(min.getFullYear(), min.getMonth(), 1);
    const max = new Date(today.getFullYear(), today.getMonth() + 1, 1);
    const span = max - min;
    const months = []; for (let m = new Date(min); m < max; m = new Date(m.getFullYear(), m.getMonth() + 1, 1)) months.push(new Date(m));
    const pct = dt => ((dt - min) / span) * 100;
    const MON = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
    list.sort((a, b) => d(a.start_date) - d(b.start_date));
    const rows = list.map(e => {
      const st = d(e.start_date); const en = e.status === 'AYRILDI' && e.end_date ? d(e.end_date) : today;
      const left = pct(st), width = Math.max(0.6, pct(en) - left);
      const mdays = Math.round((en - st) / 86400000); const yrs = Math.floor(mdays / 365); const mos = Math.floor((mdays % 365) / 30);
      const dur = (yrs ? yrs + ' yıl ' : '') + (mos ? mos + ' ay' : (yrs ? '' : mdays + ' gün'));
      return h('div', { class: 'gantt-row' },
        h('a', { class: 'gantt-name', href: `#/hr/${e.id}` }, h('b', null, `${e.first_name} ${e.last_name}`), h('span', null, e.title || '—')),
        h('div', { class: 'gantt-track' }, months.map((m, i) => h('div', { class: 'gantt-gl', style: { left: pct(m) + '%' } })),
          h('div', { class: `gantt-bar ${e.status === 'AYRILDI' ? 'left' : ''}`, style: { left: left + '%', width: width + '%' },
            title: `${fmtDate(e.start_date)} → ${e.status === 'AYRILDI' ? fmtDate(e.end_date) : 'bugün'} · ${dur}` },
            h('span', null, dur))));
    });
    clear(body, h('div', { class: 'card card-pad' },
      h('div', { class: 'gantt' },
        h('div', { class: 'gantt-head' }, h('div', { class: 'gantt-name' }), h('div', { class: 'gantt-track' }, months.map(m => h('div', { class: 'gantt-mon', style: { left: pct(m) + '%' } }, (m.getMonth() === 0 || m === months[0]) ? `${MON[m.getMonth()]} ${String(m.getFullYear()).slice(2)}` : MON[m.getMonth()])))),
        rows),
      h('p', { class: 'small muted', style: { marginTop: '10px' } }, 'Her çubuk personelin işe başlama tarihinden ayrılışına (ayrılmadıysa bugüne) kadar olan istihdam süresidir. Mor = ayrılmış.')));
  };
  paint();
}

// Personel detayı › Giriş-Çıkış: o kişinin son 14 günlük PDKS giriş-çıkışı
function attendanceDetailTab(e) {
  // Bireysel giriş-çıkış takvimi: gün / hafta görünümü; giriş→çıkış bloğu zaman ızgarasında gösterilir
  const box = h('div', { class: 'hr-sub-detail' });
  let mode = pref('hr.attCal', 'week'), anchor = new Date();
  let days = null, loFrom = '', loTo = '', state = { enabled: true };
  const iso = d => { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 10); };
  const addD = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
  const monday = d => { const x = new Date(d); const w = (x.getDay() + 6) % 7; return addD(x, -w); };
  const H0 = 6, H1 = 22, SPAN = (H1 - H0) * 60, PXH = 34;   // 06:00–22:00
  const toMin = t => (t ? parseInt(t.slice(0, 2)) * 60 + parseInt(t.slice(3, 5)) : null);
  const DOW = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
  async function ensure(from, to) {
    if (days && from >= loFrom && to <= loTo) return;
    const f = iso(addD(from, -7)), t = iso(addD(to, 7));
    const d = await api.get(`/api/hr/pdks/attendance?date_from=${f}&date_to=${t}`);
    loFrom = f; loTo = t; state = d;
    const row = (d.rows || []).find(r => r.employee_id === e.id);
    days = row ? row.days : (d.enabled ? {} : null);
  }
  const block = (day) => {
    const v = days[day]; if (!v) return null;
    const g = toMin(v.giris), c = toMin(v.cikis) ?? g;
    const top = Math.max(0, (g - H0 * 60) / SPAN) * (SPAN / 60 * PXH);
    const hgt = Math.max(16, ((c - g) / SPAN) * (SPAN / 60 * PXH));
    const dur = v.dakika != null ? `${Math.floor(v.dakika / 60)}s ${String(v.dakika % 60).padStart(2, '0')}d` : '';
    return h('div', { class: 'cal-ev', style: { top: top + 'px', height: hgt + 'px' }, title: t('{giris} – {cikis} · {n} okuma', { giris: v.giris, cikis: v.cikis || 'çıkış yok', n: v.okuma }) },
      h('b', null, v.giris), v.cikis ? h('span', null, ' – ' + v.cikis) : h('span', { class: 'cal-nx' }, ' çıkış yok'), dur ? h('small', null, dur) : null);
  };
  const hoursCol = () => h('div', { class: 'cal-hours' }, Array.from({ length: H1 - H0 + 1 }, (_, i) => h('div', { class: 'cal-h', style: { height: PXH + 'px' } }, `${String(H0 + i).padStart(2, '0')}:00`)));
  const dayCol = (day, withName) => {
    const dd = new Date(day + 'T12:00'); const today = iso(new Date()) === day;
    return h('div', { class: `cal-col ${today ? 'today' : ''}` },
      withName ? h('div', { class: 'cal-chead' }, h('b', null, `${dd.getDate()}`), h('span', null, DOW[(dd.getDay() + 6) % 7])) : null,
      h('div', { class: 'cal-grid', style: { height: (H1 - H0) * PXH + 'px' } },
        Array.from({ length: H1 - H0 }, (_, i) => h('div', { class: 'cal-slot', style: { height: PXH + 'px' } })), block(day)));
  };
  const draw = () => {
    if (!state.enabled) return clear(box, h('div', { class: 'card empty' }, state.message || 'PDKS entegrasyonu tanımlı değil.'));
    if (state.error) return clear(box, h('div', { class: 'alert err' }, 'PDKS’e bağlanılamadı: ' + state.error));
    let label, grid;
    if (mode === 'day') {
      const day = iso(anchor);
      label = `${anchor.getDate()}.${String(anchor.getMonth() + 1).padStart(2, '0')}.${anchor.getFullYear()} ${['Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi'][anchor.getDay()]}`;
      grid = h('div', { class: 'cal cal-day' }, hoursCol(), dayCol(day, false));
    } else {
      const m = monday(anchor); const list = Array.from({ length: 7 }, (_, i) => iso(addD(m, i)));
      label = `${m.getDate()}.${String(m.getMonth() + 1).padStart(2, '0')} – ${addD(m, 6).getDate()}.${String(addD(m, 6).getMonth() + 1).padStart(2, '0')}.${addD(m, 6).getFullYear()}`;
      grid = h('div', { class: 'cal cal-week' }, hoursCol(), ...list.map(d => dayCol(d, true)));
    }
    const nav = (n) => { anchor = addD(anchor, mode === 'day' ? n : n * 7); refresh(); };
    const modeBtn = (k, t) => h('button', { class: `btn sm ${mode === k ? 'primary' : ''}`, type: 'button', onclick: () => { mode = k; setPref('hr.attCal', k); draw(); } }, t);
    clear(box, h('div', { class: 'card card-pad' },
      h('div', { class: 'cal-bar' },
        h('button', { class: 'btn sm', type: 'button', onclick: () => nav(-1) }, '‹'),
        h('button', { class: 'btn sm', type: 'button', onclick: () => { anchor = new Date(); refresh(); } }, 'Bugün'),
        h('button', { class: 'btn sm', type: 'button', onclick: () => nav(1) }, '›'),
        h('b', { class: 'cal-label' }, label), h('span', { class: 'spacer', style: { flex: 1 } }),
        modeBtn('day', 'Gün'), modeBtn('week', 'Hafta')),
      grid,
      h('p', { class: 'small muted', style: { marginTop: '8px' } }, 'PDKS cihazından yalnızca okunur. Günün ilk okuması giriş, son okuması çıkış kabul edilir.')));
  };
  const refresh = async () => {
    const from = mode === 'day' ? anchor : monday(anchor);
    const to = mode === 'day' ? anchor : addD(monday(anchor), 6);
    clear(box, h('div', { class: 'card card-pad loading' }, 'PDKS okunuyor…'));
    try { await ensure(from, to); draw(); } catch (err) { clear(box, h('div', { class: 'card empty' }, err.message)); }
  };
  refresh();
  return box;
}

// Personel detayı › Başvuru Bilgileri: iş başvuru formundan (AI ile) okunan bilgiler; İK düzenler ve kaydeder
function applicationTab(e) {
  const box = h('div', { class: 'hr-sub-detail' });
  const LABELS = {
    dogum_yeri: 'Doğum yeri', dogum_tarihi: 'Doğum tarihi', medeni_durum: 'Medeni durumu', kan_grubu: 'Kan grubu',
    adres: 'Ev adresi', telefon: 'Cep telefonu', email: 'E-posta', acil_kisi: 'Acil durumda haber verilecek kişi',
    es_ad: 'Eşinin adı soyadı', es_meslek: 'Eşinin mesleği', es_telefon: 'Eşinin telefonu', cocuk: 'Çocuk sayısı / yaşı',
    egitim_lise: 'Lise', egitim_lisans: 'Lisans', egitim_yuksek: 'Yüksek lisans', egitim_devam: 'Devam eden eğitim',
    tecrube: 'İş tecrübeleri',
  };
  const draw = (info, note) => {
    const inputs = {};
    const rows = Object.entries(LABELS).map(([k, label]) => {
      const el = k === 'tecrube' || k === 'adres' ? h('textarea', { class: 'input', rows: 2 }, info[k] || '') : h('input', { class: 'input', value: info[k] || '' });
      inputs[k] = el;
      return field(label, el);
    });
    const save = h('button', { class: 'btn primary' }, 'Kaydet');
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        const payload = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value.trim()]));
        await api.put(`/api/hr/employees/${e.id}/application`, { info: payload });
        toast('Başvuru bilgileri kaydedildi'); e.application_info = payload;
      } catch (err) { toastError(err); } finally { save.disabled = false; }
    });
    const readBtn = e.has_application_form ? h('button', { class: 'btn', type: 'button' }, '🪄 Başvuru formundan oku (AI)') : null;
    if (readBtn) readBtn.addEventListener('click', async () => {
      readBtn.disabled = true; readBtn.textContent = 'Form okunuyor…';
      try {
        const r = await api.post(`/api/hr/employees/${e.id}/application/parse`, {});
        draw({ ...info, ...Object.fromEntries(Object.entries(r.fields).filter(([, v]) => v)) }, 'Form okundu — bilgileri kontrol edip Kaydet’e basın. (AI okuması; hataları düzeltin.)');
      } catch (err) { toastError(err); readBtn.disabled = false; readBtn.textContent = '🪄 Başvuru formundan oku (AI)'; }
    });
    clear(box, h('div', { class: 'card card-pad' },
      h('div', { class: 'co-section-head' }, h('h3', { style: { margin: 0 } }, 'Başvuru Bilgileri'), readBtn),
      note ? h('div', { class: 'alert warn', style: { margin: '0 0 12px' } }, note) : null,
      e.has_application_form ? null : h('p', { class: 'small muted' }, 'Bu personelde yüklü İş Başvuru Formu yok; bilgileri elle girebilirsiniz.'),
      h('div', { class: 'form-grid' }, ...rows),
      h('div', { class: 'set-actions left', style: { marginTop: '12px' } }, save)));
  };
  draw(e.application_info || {});
  return box;
}

// ---------- Organizasyon şeması: üstten alta bağlı kartlar; personel ata, görev gir, alta kart ekle, sil
async function renderOrg(view, head) {
  const body = h('div');
  let empList = null;
  const employees = async () => (empList ??= (await api.get('/api/hr/employees')).filter(e => e.status === 'AKTIF' || e.status === 'AYRILDI'));
  const assignModal = (node, parentId) => {
    const sel = h('select', { class: 'input' }, h('option', { value: '' }, 'Personel seçin…'));
    const title = h('input', { class: 'input', value: node?.title || '', placeholder: 'Görev / ünvan (ör. Genel Müdür)' });
    employees().then(list => { for (const e of list) sel.append(h('option', { value: e.id, selected: node && e.id === node.employee_id }, `${e.first_name} ${e.last_name}${e.status === 'AYRILDI' ? ' (ayrıldı)' : ''}`)); });
    modal({
      title: node ? 'Kartı düzenle' : 'Personel ata',
      body: h('div', null, field('Personel', sel), field('Görev / ünvan', title)),
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        const payload = { employee_id: sel.value ? Number(sel.value) : null, title: title.value.trim() };
        if (node) await api.put(`/api/hr/org/${node.id}`, payload);
        else await api.post('/api/hr/org', { ...payload, parent_id: parentId ?? null });
        toast('Kaydedildi'); load();
      } }],
    });
  };
  const del = async node => {
    const n = (function count(x) { return 1 + x.children.reduce((a, c) => a + count(c), 0); })(node) - 1;
    if (!await confirmDialog('Kartı sil', t('{name} kartı{extra} silinsin mi?', { name: node.name, extra: n ? t(' ve altındaki {n} kart', { n }) : '' }), { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/hr/org/${node.id}`); toast('Silindi'); load(); } catch (err) { toastError(err); }
  };
  // Tıklanan kişiye göre işlem menüsü (treeSpider düğümü tıklama olayı sunmadığından kendi menümüzü açarız)
  let menuEl = null;
  const closeMenu = () => { if (menuEl) { menuEl.remove(); menuEl = null; document.removeEventListener('click', closeMenu); } };
  const openMenu = (ev, node) => {
    closeMenu();
    const items = !node
      ? [['Personel ata', () => assignModal(null, null), false]]
      : [['Alta bağlı kart ekle', () => assignModal(null, node.id), false],
         ['Düzenle', () => assignModal(node), false],
         ['Sil', () => del(node), true]];
    menuEl = h('div', { class: 'org-menu' }, items.map(([label, fn, danger]) =>
      h('button', { class: `org-menu-item ${danger ? 'danger' : ''}`, onclick: () => { closeMenu(); fn(); } }, label)));
    document.body.append(menuEl);
    const w = menuEl.offsetWidth || 190, hh = menuEl.offsetHeight || 150;
    menuEl.style.left = Math.min(ev.clientX, window.innerWidth - w - 8) + 'px';
    menuEl.style.top = Math.min(ev.clientY, window.innerHeight - hh - 8) + 'px';
    setTimeout(() => document.addEventListener('click', closeMenu), 0);
  };

  const stage = h('div', { class: 'org-ts' });
  const renderChart = async (tree_data, byId) => {
    const TreeSpider = await loadTreeSpider();
    clear(stage);
    const cid = 'ts-' + Date.now().toString(36);
    const cont = h('div', { style: { width: '100%', height: '100%' } });
    cont.id = cid;
    stage.append(cont);
    const chart = new TreeSpider({
      targetContainer: '#' + cid,
      autoInitialize: false,
      tree_data,
      tree_type: 'default',
      chart_head_type: 'default',
      head_image_shape: 'symbolCircle',
      show_chart_head_border: true,
      backgroundPattern: 'none',
      chart_head_bg: '#ffffff',
      color_range: ['#12385c', '#1d4e89', '#2b6cb0', '#3f7cb8'],
      width: '100%', height: '100%',
      font_link: '', font_name: "system-ui, 'Segoe UI', Arial, sans-serif",
    });
    chart.on('chart_head.create', e => {
      const svgEl = e && e.detail && e.detail.headNode; if (!svgEl) return;
      const clip = svgEl.querySelector('[id^="default-head-clip-"]');
      const id = clip ? clip.id.replace('default-head-clip-', '') : null;
      if (id == null) return;
      svgEl.style.cursor = 'pointer';
      // Kısa dokunuş → ağacı aç/kapa; uzun basış → işlem menüsü (treeSpider tıklama olayı sunmaz).
      let timer = null, longPressed = false, sx = 0, sy = 0;
      const cancel = () => { if (timer) { clearTimeout(timer); timer = null; } };
      svgEl.addEventListener('pointerdown', ev => {
        longPressed = false; sx = ev.clientX; sy = ev.clientY;
        timer = setTimeout(() => { longPressed = true; openMenu({ clientX: sx, clientY: sy }, byId[id] || null); }, 480);
      });
      svgEl.addEventListener('pointermove', ev => { if (Math.abs(ev.clientX - sx) > 8 || Math.abs(ev.clientY - sy) > 8) cancel(); });
      svgEl.addEventListener('pointercancel', cancel);
      svgEl.addEventListener('pointerleave', cancel);
      svgEl.addEventListener('pointerup', ev => {
        cancel();
        if (longPressed) { ev.preventDefault(); ev.stopPropagation(); return; }
        if (ev.target.closest && ev.target.closest('.ts-linker')) return;   // thumb'a basıldıysa bileşen kendi açar
        const thumb = svgEl.querySelector('.ts-linker[style*="pointer"]');  // çocukları varsa aç/kapa thumb'ı
        if (thumb) { ev.stopPropagation(); thumb.dispatchEvent(new MouseEvent('click', { bubbles: true })); }
      });
    });
    chart.initialize();
  };

  const load = async () => {
    let d;
    try { d = await api.get('/api/hr/org'); } catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    clear(body, stage);
    const byId = {};
    const flat = [];
    const walk = (nodes, parentId) => { for (const n of (nodes || [])) { byId[String(n.id)] = n; flat.push({ n, parentId }); walk(n.children, String(n.id)); } };
    walk(d.tree, undefined);
    if (!flat.length) {
      // Boş şema: atanmamış en-üst kart; tıklayıp personel atayarak ilk kaydı oluşturursunuz
      return renderChart([{ id: '__new__', name: 'En üst kart', role: 'Personel atamak için tıklayın', image: initialsAvatar('', true) }], {});
    }
    const tree_data = flat.map(({ n, parentId }) => ({
      id: String(n.id),
      parentId,
      name: n.name || '—',
      role: n.title || n.emp_title || '',
      image: n.photo ? fileUrl(n.photo, 160) : initialsAvatar(n.name, !n.employee_id),
    }));
    renderChart(tree_data, byId);
  };
  clear(view, head('Organizasyon şeması'), body);
  load();
}

// Kimlik kartını yazdır: kartı tek başına yazdırma alanında aç
function printIdCard(e) {
  const card = idCard(e, { company: COMPANY_LEGAL, logoUrl: COMPANY_LOGO });
  const area = h('div', { class: 'idc-print' }, card);
  document.body.append(area);
  const done = () => { area.remove(); window.removeEventListener('afterprint', done); };
  window.addEventListener('afterprint', done);
  setTimeout(() => window.print(), 100);
}
