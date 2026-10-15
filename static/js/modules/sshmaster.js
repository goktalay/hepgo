// Merkez › SSH Master: sshmasters.com kullanıcıları (durum, oturumlar, indirmeler, senkron) ve uygulama sürümleri (exe yükleme).
// Sunucu: SSH Master hesap servisi (central/sshmaster_server) — Merkez /api/central/sshm/* vekil uçlarıyla iç anahtarla çağırır.
// Kullanıcıların şifreleri ve bağlantı kütüphaneleri burada görünmez (uçtan uca şifreli; sunucu da okuyamaz).
import { api, upload } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, pageHead, segmented, statStrip, toast, toastError } from '../ui.js';

const SUBS = [['users', 'Kullanıcılar'], ['releases', 'Sürümler']];
const ST = { AKTIF: ['green', 'Aktif'], BEKLIYOR: ['yellow', 'E-posta bekliyor'], ASKIDA: ['red', 'Askıda'] };
const size = n => (n == null ? '—' : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`);
const badge = s => { const [c, l] = ST[s] || ['', s]; return h('span', { class: `badge ${c}` }, l); };

export async function render(view, params) {
  const sub = SUBS.some(s => s[0] === params[0]) ? params[0] : 'users';
  const nav = segmented(SUBS, sub, v => { location.hash = `#/sshmaster/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('SSH Master', { back: '#/', sub: 'sshmasters.com kullanıcıları ve uygulama sürümleri', tabs: nav }), body);
  return sub === 'releases' ? releasesView(body) : usersView(body);
}

async function usersView(view) {
  const stats = statStrip();
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ad ya da e-posta ara…', style: { width: '260px' } });
  const st = h('select', { class: 'input' }, h('option', { value: '' }, 'Tüm durumlar'), Object.entries(ST).map(([k, [, l]]) => h('option', { value: k }, l)));
  const list = h('div');
  let rows = [];
  const draw = () => {
    const t = q.value.trim().toLocaleLowerCase('tr');
    const shown = rows.filter(u => (!st.value || u.status === st.value) && (!t || `${u.name} ${u.email}`.toLocaleLowerCase('tr').includes(t)));
    clear(list, shown.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Kullanıcı', 'Durum', 'Kayıt', 'Son giriş', 'Uygulama oturumu', 'Senkron', 'İndirme'].map(c => h('th', null, c)))),
      h('tbody', null, shown.map(u => h('tr', { class: 'click', onclick: () => userModal(u.id, load) },
        h('td', null, h('b', null, u.name), h('div', { class: 'small muted' }, u.email), u.note ? h('div', { class: 'small muted' }, `Not: ${u.note}`) : null),
        h('td', null, badge(u.status)),
        h('td', { class: 'small' }, fmtDateTime(u.created_at)),
        h('td', { class: 'small' }, u.last_login ? fmtDateTime(u.last_login) : '—'),
        h('td', null, String(u.app_sessions || 0)),
        h('td', { class: 'small' }, u.sync_enabled ? (u.lib_version ? `${size(u.lib_size)} · ${fmtDateTime(u.lib_updated)}` : 'Açık · henüz yok') : 'Kapalı'),
        h('td', null, String(u.downloads || 0)))))))
      : h('div', { class: 'card empty' }, rows.length ? 'Filtreye uyan kullanıcı yok' : 'Henüz kayıtlı kullanıcı yok'));
  };
  const load = async () => {
    const d = await api.get('/api/central/sshm/users');
    rows = d.users;
    const s = d.stats;
    stats.set([
      { icon: 'users', label: 'Kullanıcı', value: s.users, sub: `${s.active} aktif · ${s.pending} bekliyor` },
      { icon: 'warning', label: 'Askıda', value: s.suspended, tone: s.suspended ? 'alert' : '' },
      { icon: 'documents', label: 'İndirme', value: s.downloads },
      { icon: 'tools', label: 'Güncel sürüm', value: s.release ? s.release.version : '—', sub: s.release ? fmtDateTime(s.release.date) : 'Sürüm yüklenmedi' },
    ]);
    draw();
  };
  q.addEventListener('input', draw);
  st.addEventListener('change', draw);
  clear(view, stats, h('div', { class: 'filters' }, q, st, h('span', { class: 'spacer' }),
    h('a', { class: 'btn', href: 'https://sshmasters.com', target: '_blank', rel: 'noopener' }, 'sshmasters.com')), list);
  try { await load(); } catch (e) { clear(list, h('div', { class: 'card empty' }, e.message)); }
}

async function userModal(uid, reload) {
  let d;
  try { d = await api.get(`/api/central/sshm/users/${uid}`); } catch (e) { toastError(e); return; }
  const u = d.user;
  const note = h('textarea', { class: 'input', rows: 2, placeholder: 'Yalnız yöneticiler görür' }, u.note || '');
  const act = async (fn, ok) => { try { await fn(); if (ok) toast(ok); m.close?.(); await reload(); } catch (e) { toastError(e); } };
  const m = modal({
    title: `${u.name} — ${u.email}`, wide: true,
    body: h('div', null,
      h('dl', { class: 'kv' },
        h('dt', null, 'Durum'), h('dd', null, badge(u.status)),
        h('dt', null, 'Kayıt'), h('dd', null, fmtDateTime(u.created_at)),
        h('dt', null, 'E-posta doğrulama'), h('dd', null, u.verified_at ? fmtDateTime(u.verified_at) : 'Doğrulanmadı'),
        h('dt', null, 'Son giriş'), h('dd', null, u.last_login ? fmtDateTime(u.last_login) : '—'),
        h('dt', null, 'Senkronizasyon'), h('dd', null, u.sync_enabled ? 'Açık' : 'Kapalı (kullanıcı kapattı)'),
        h('dt', null, 'Web\'deki kütüphane'), h('dd', null, d.library.version ? `${size(d.library.size)} · sürüm ${d.library.version} · ${fmtDateTime(d.library.updated_at)}${d.library.device ? ` · ${d.library.device}` : ''}` : 'Yok')),
      h('p', { class: 'small muted' }, 'Bağlantı kütüphanesi uçtan uca şifrelidir; içeriği sunucuda ve burada görüntülenemez.'),
      h('h3', null, 'Oturumlar'),
      d.sessions.length ? h('table', null, h('thead', null, h('tr', null, ['Cihaz', 'Tür', 'Sürüm', 'IP', 'Son görülme'].map(c => h('th', null, c)))),
        h('tbody', null, d.sessions.map(s => h('tr', null, h('td', null, s.device || '—'), h('td', null, s.kind === 'web' ? 'Web' : 'Uygulama'),
          h('td', null, s.app_version || '—'), h('td', { class: 'small' }, s.ip || '—'), h('td', { class: 'small' }, fmtDateTime(s.last_seen))))))
        : h('div', { class: 'small muted' }, 'Açık oturum yok'),
      h('h3', null, 'İndirmeler'),
      d.downloads.length ? h('table', null, h('thead', null, h('tr', null, ['Tarih', 'Sürüm', 'Tür', 'IP'].map(c => h('th', null, c)))),
        h('tbody', null, d.downloads.map(x => h('tr', null, h('td', { class: 'small' }, fmtDateTime(x.at)), h('td', null, x.version || '—'),
          h('td', null, x.kind === 'portable' ? 'Taşınabilir' : 'Kurulum'), h('td', { class: 'small' }, x.ip || '—')))))
        : h('div', { class: 'small muted' }, 'Henüz indirme yok'),
      field('Yönetici notu', note)),
    actions: [
      { label: 'Sil', class: 'danger', onClick: async () => {
        if (!await confirmDialog('Kullanıcıyı sil', `${u.email} ve web'deki şifreli kütüphanesi kalıcı olarak silinsin mi?`, { okLabel: 'Sil', danger: true })) return true;
        await act(() => api.del(`/api/central/sshm/users/${uid}`), 'Kullanıcı silindi');
      } },
      { label: u.status === 'BEKLIYOR' ? 'Doğrulama e-postasını yeniden gönder' : 'Şifre sıfırlama e-postası gönder', onClick: async () => {
        await act(() => api.post(`/api/central/sshm/users/${uid}/reset-mail`), 'E-posta gönderildi');
      } },
      u.status === 'ASKIDA'
        ? { label: 'Etkinleştir', onClick: async () => { await act(() => api.put(`/api/central/sshm/users/${uid}`, { status: 'AKTIF' }), 'Hesap etkinleştirildi'); } }
        : { label: u.status === 'BEKLIYOR' ? 'E-postasız etkinleştir' : 'Askıya al', onClick: async () => {
          const target = u.status === 'BEKLIYOR' ? 'AKTIF' : 'ASKIDA';
          if (target === 'ASKIDA' && !await confirmDialog('Askıya al', 'Kullanıcının tüm oturumları kapanır; uygulamaya giriş ve indirme yapamaz.', { okLabel: 'Askıya al', danger: true })) return true;
          await act(() => api.put(`/api/central/sshm/users/${uid}`, { status: target }), target === 'AKTIF' ? 'Hesap etkinleştirildi' : 'Hesap askıya alındı');
        } },
      { label: 'Notu kaydet', class: 'primary', onClick: async () => { await act(() => api.put(`/api/central/sshm/users/${uid}`, { note: note.value }), 'Kaydedildi'); } },
    ],
  });
}

async function releasesView(view) {
  const list = h('div');
  const load = async () => {
    const rows = await api.get('/api/central/sshm/releases');
    clear(list, rows.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Sürüm', 'Kurulum dosyası', 'Taşınabilir', 'Yüklenme', 'İndirme', ''].map(c => h('th', null, c)))),
      h('tbody', null, rows.map((r, i) => h('tr', null,
        h('td', null, h('b', null, r.version), i === 0 ? h('span', { class: 'badge green', style: { marginLeft: '6px' } }, 'Güncel') : null,
          r.notes ? h('div', { class: 'small muted', style: { whiteSpace: 'pre-wrap' } }, r.notes) : null),
        h('td', { class: 'small' }, r.setup_file, h('div', { class: 'muted' }, `${size(r.setup_size)} · SHA-256 ${r.setup_sha256.slice(0, 16)}…`)),
        h('td', { class: 'small' }, r.portable_file ? `${r.portable_file} · ${size(r.portable_size)}` : '—'),
        h('td', { class: 'small' }, fmtDateTime(r.created_at)),
        h('td', null, String(r.downloads || 0)),
        h('td', { class: 'num' }, h('button', { class: 'btn sm ghost', onclick: async () => {
          if (!await confirmDialog('Sürümü sil', `${r.version} sürümü ve dosyaları silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
          try { await api.del(`/api/central/sshm/releases/${r.id}`); toast('Sürüm silindi'); await load(); } catch (e) { toastError(e); }
        } }, 'Sil')))))))
      : h('div', { class: 'card empty' }, 'Henüz sürüm yüklenmedi. Kullanıcılar Hesabım sayfasında en son yüklenen sürümü indirir.'));
  };
  const ver = h('input', { class: 'input', placeholder: 'ör. 1.2.0' });
  const setup = h('input', { class: 'input', type: 'file', accept: '.exe' });
  const portable = h('input', { class: 'input', type: 'file', accept: '.exe' });
  const notes = h('textarea', { class: 'input', rows: 3, placeholder: 'Bu sürümde neler var? (Hesabım sayfasında görünür)' });
  const prog = h('div', { class: 'small muted' });
  const btn = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    if (!ver.value.trim() || !setup.files[0]) { toast('Sürüm numarası ve kurulum dosyası gerekli', 'err'); return; }
    const fd = new FormData();
    fd.append('version', ver.value.trim()); fd.append('notes', notes.value); fd.append('setup', setup.files[0]);
    if (portable.files[0]) fd.append('portable', portable.files[0]);
    btn.disabled = true;
    try {
      const r = await upload('/api/central/sshm/releases', fd, p => { prog.textContent = `Yükleniyor… %${p || 0}`; });
      prog.textContent = '';
      toast(`${r.version} yüklendi`);
      ver.value = ''; setup.value = ''; portable.value = ''; notes.value = '';
      await load();
    } catch (e) { prog.textContent = ''; toastError(e); }
    btn.disabled = false;
  } }, 'Sürümü yükle');
  clear(view,
    h('div', { class: 'card card-pad', style: { marginBottom: '16px' } },
      h('h2', { class: 'side-title' }, 'Yeni sürüm yükle'),
      h('div', { class: 'row' }, field('Sürüm', ver), field('Kurulum dosyası (Setup .exe)', setup), field('Taşınabilir (isteğe bağlı)', portable)),
      field('Sürüm notları', notes),
      h('div', { class: 'row', style: { alignItems: 'center' } }, btn, prog),
      h('p', { class: 'small muted' }, 'GitHub Actions da aynı uca (POST https://sshmasters.com/api/sm/releases, X-Release-Key başlığı) otomatik yükleyebilir.')),
    list);
  try { await load(); } catch (e) { clear(list, h('div', { class: 'card empty' }, e.message)); }
}
