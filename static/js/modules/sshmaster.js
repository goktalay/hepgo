// Merkez › Mastertool: tek hesapla SSH Master + FTP Masters kullanıcıları (durum, uygulama lisansı, oturumlar, indirmeler, senkron) ve
// uygulama sürümleri (exe yükleme). Sunucu: Mastertool hesap servisi (central/sshmaster_server) — Merkez /api/central/sshm/* vekil
// uçlarıyla iç anahtarla çağırır. Kullanıcıların şifreleri ve kütüphaneleri burada görünmez (uçtan uca şifreli; sunucu da okuyamaz).
// Kullanıcıların destek talepleri Destek Merkezi'nde "Mastertool · <uygulama>" adıyla görünür.
import { api, upload } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, pageHead, segmented, statStrip, toast, toastError } from '../ui.js';

const SUBS = [['users', 'Kullanıcılar'], ['releases', 'Sürümler']];
const APPS = [['sm', 'SSH Master'], ['fm', 'FTP Masters'], ['sq', 'SQL Master'], ['np', 'Notepad Master']];
const APPN = Object.fromEntries(APPS);
const ST = { AKTIF: ['green', 'Aktif'], BEKLIYOR: ['yellow', 'E-posta bekliyor'], ASKIDA: ['red', 'Askıda'] };
const size = n => (n == null ? '—' : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`);
const badge = s => { const [c, l] = ST[s] || ['', s]; return h('span', { class: `badge ${c}` }, l); };
const used = a => a && (a.app_sessions || a.downloads || a.lib_version);

export async function render(view, params) {
  const sub = SUBS.some(s => s[0] === params[0]) ? params[0] : 'users';
  const nav = segmented(SUBS, sub, v => { location.hash = `#/sshmaster/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Mastertool', { back: '#/', sub: 'SSH Master, FTP Masters, SQL Master ve Notepad Master — tek hesap, uygulama lisansları ve sürümler', tabs: nav }), body);
  return sub === 'releases' ? releasesView(body) : usersView(body);
}

function appCell(a) {
  if (!a) return h('td', null, '—');
  if (a.license !== 'AKTIF') return h('td', null, h('span', { class: 'badge red' }, 'Kapalı'));
  return h('td', { class: 'small' }, used(a)
    ? [`${a.app_sessions || 0} oturum · ${a.downloads || 0} indirme`, h('div', { class: 'muted' }, a.sync_enabled ? (a.lib_version ? `Senkron ${size(a.lib_size)}` : 'Senkron açık') : 'Senkron kapalı')]
    : h('span', { class: 'muted' }, 'Kullanmadı'));
}

async function usersView(view) {
  const stats = statStrip();
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ad ya da e-posta ara…', style: { width: '260px' } });
  const st = h('select', { class: 'input' }, h('option', { value: '' }, 'Tüm durumlar'), Object.entries(ST).map(([k, [, l]]) => h('option', { value: k }, l)));
  const ap = h('select', { class: 'input' }, h('option', { value: '' }, 'Tüm uygulamalar'), APPS.map(([k, l]) => h('option', { value: k }, `${l} kullananlar`)));
  const list = h('div');
  let rows = [];
  const draw = () => {
    const t = q.value.trim().toLocaleLowerCase('tr');
    const shown = rows.filter(u => (!st.value || u.status === st.value) && (!ap.value || used(u.apps?.[ap.value]))
      && (!t || `${u.name} ${u.email}`.toLocaleLowerCase('tr').includes(t)));
    clear(list, shown.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Kullanıcı', 'Durum', 'Kayıt', 'Son giriş', ...APPS.map(a => a[1])].map(c => h('th', null, c)))),
      h('tbody', null, shown.map(u => h('tr', { class: 'click', onclick: () => userModal(u.id, load) },
        h('td', null, h('b', null, u.name), h('div', { class: 'small muted' }, u.email), u.note ? h('div', { class: 'small muted' }, `Not: ${u.note}`) : null),
        h('td', null, badge(u.status)),
        h('td', { class: 'small' }, fmtDateTime(u.created_at)),
        h('td', { class: 'small' }, u.last_login ? fmtDateTime(u.last_login) : '—'),
        APPS.map(([k]) => appCell(u.apps?.[k])))))))
      : h('div', { class: 'card empty' }, rows.length ? 'Filtreye uyan kullanıcı yok' : 'Henüz kayıtlı kullanıcı yok'));
  };
  const load = async () => {
    const d = await api.get('/api/central/sshm/users');
    rows = d.users;
    const s = d.stats;
    const per = s.apps || {};
    stats.set([
      { icon: 'users', label: 'Kullanıcı', value: s.users, sub: `${s.active} aktif · ${s.pending} bekliyor` },
      { icon: 'warning', label: 'Askıda', value: s.suspended, tone: s.suspended ? 'alert' : '' },
      ...APPS.map(([k, l]) => ({ icon: 'tools', label: l, value: per[k]?.release ? per[k].release.version : '—',
        sub: `${per[k]?.users || 0} kullanıcı · ${per[k]?.downloads || 0} indirme` })),
    ]);
    draw();
  };
  q.addEventListener('input', draw);
  [st, ap].forEach(el => el.addEventListener('change', draw));
  clear(view, stats, h('div', { class: 'filters' }, q, st, ap, h('span', { class: 'spacer' }),
    h('a', { class: 'btn', href: 'https://mastertool.download', target: '_blank', rel: 'noopener' }, 'mastertool.download')), list);
  try { await load(); } catch (e) { clear(list, h('div', { class: 'card empty' }, e.message)); }
}

async function userModal(uid, reload) {
  let d;
  try { d = await api.get(`/api/central/sshm/users/${uid}`); } catch (e) { toastError(e); return; }
  const u = d.user;
  const note = h('textarea', { class: 'input', rows: 2, placeholder: 'Yalnız yöneticiler görür' }, u.note || '');
  const act = async (fn, ok) => { try { await fn(); if (ok) toast(ok); m.close?.(); await reload(); } catch (e) { toastError(e); } };
  const appBlock = ([k, l]) => {
    const a = d.apps?.[k] || {};
    const on = a.license === 'AKTIF';
    return h('div', { class: 'card card-pad', style: { marginBottom: '10px' } },
      h('div', { class: 'row', style: { alignItems: 'center' } }, h('b', null, l), h('span', { class: `badge ${on ? 'green' : 'red'}` }, on ? 'Lisans açık' : 'Lisans kapalı'),
        h('span', { class: 'spacer' }),
        h('button', { class: `btn sm ${on ? 'ghost' : ''}`, type: 'button', onclick: async () => {
          if (on && !await confirmDialog(`${l} lisansını kapat`, `${u.email} ${l}'a giriş yapamaz ve indiremez; açık ${l} oturumları kapanır. Diğer uygulama etkilenmez.`,
            { okLabel: 'Kapat', danger: true })) return;
          await act(() => api.put(`/api/central/sshm/users/${uid}`, { apps: { [k]: on ? 'KAPALI' : 'AKTIF' } }), on ? `${l} kapatıldı` : `${l} açıldı`);
        } }, on ? 'Lisansı kapat' : 'Lisansı aç')),
      h('div', { class: 'small muted' }, `${a.app_sessions || 0} uygulama oturumu · ${a.downloads || 0} indirme · senkron ${a.sync_enabled ? 'açık' : 'kapalı (kullanıcı kapattı)'}`
        + (a.lib_version ? ` · web kopyası ${size(a.lib_size)}, ${fmtDateTime(a.lib_updated)}` : '')));
  };
  const m = modal({
    title: `${u.name} — ${u.email}`, wide: true,
    body: h('div', null,
      h('dl', { class: 'kv' },
        h('dt', null, 'Hesap durumu'), h('dd', null, badge(u.status)),
        h('dt', null, 'Kayıt'), h('dd', null, fmtDateTime(u.created_at)),
        h('dt', null, 'E-posta doğrulama'), h('dd', null, u.verified_at ? fmtDateTime(u.verified_at) : 'Doğrulanmadı'),
        h('dt', null, 'Son giriş'), h('dd', null, u.last_login ? fmtDateTime(u.last_login) : '—')),
      h('h3', null, 'Uygulamalar'),
      APPS.map(appBlock),
      h('p', { class: 'small muted' }, 'Kütüphaneler uçtan uca şifrelidir; içeriği sunucuda ve burada görüntülenemez.'),
      h('h3', null, 'Oturumlar'),
      d.sessions.length ? h('table', null, h('thead', null, h('tr', null, ['Cihaz', 'Tür', 'Sürüm', 'IP', 'Son görülme'].map(c => h('th', null, c)))),
        h('tbody', null, d.sessions.map(s => h('tr', null, h('td', null, s.device || '—'), h('td', null, s.kind === 'web' ? 'Web' : (APPN[s.app || 'sm'] || 'Uygulama')),
          h('td', null, s.app_version || '—'), h('td', { class: 'small' }, s.ip || '—'), h('td', { class: 'small' }, fmtDateTime(s.last_seen))))))
        : h('div', { class: 'small muted' }, 'Açık oturum yok'),
      h('h3', null, 'İndirmeler'),
      d.downloads.length ? h('table', null, h('thead', null, h('tr', null, ['Tarih', 'Uygulama', 'Sürüm', 'Tür', 'IP'].map(c => h('th', null, c)))),
        h('tbody', null, d.downloads.map(x => h('tr', null, h('td', { class: 'small' }, fmtDateTime(x.at)), h('td', null, APPN[x.app || 'sm'] || x.app),
          h('td', null, x.version || '—'), h('td', null, x.kind === 'portable' ? 'Taşınabilir' : 'Kurulum'), h('td', { class: 'small' }, x.ip || '—')))))
        : h('div', { class: 'small muted' }, 'Henüz indirme yok'),
      field('Yönetici notu', note)),
    actions: [
      { label: 'Sil', class: 'danger', onClick: async () => {
        if (!await confirmDialog('Kullanıcıyı sil', `${u.email} hesabı ve web'deki tüm şifreli kopyaları (tüm uygulamalar) kalıcı olarak silinsin mi?`, { okLabel: 'Sil', danger: true })) return true;
        await act(() => api.del(`/api/central/sshm/users/${uid}`), 'Kullanıcı silindi');
      } },
      { label: u.status === 'BEKLIYOR' ? 'Doğrulama e-postasını yeniden gönder' : 'Şifre sıfırlama e-postası gönder', onClick: async () => {
        await act(() => api.post(`/api/central/sshm/users/${uid}/reset-mail`), 'E-posta gönderildi');
      } },
      u.status === 'ASKIDA'
        ? { label: 'Etkinleştir', onClick: async () => { await act(() => api.put(`/api/central/sshm/users/${uid}`, { status: 'AKTIF' }), 'Hesap etkinleştirildi'); } }
        : { label: u.status === 'BEKLIYOR' ? 'E-postasız etkinleştir' : 'Hesabı askıya al', onClick: async () => {
          const target = u.status === 'BEKLIYOR' ? 'AKTIF' : 'ASKIDA';
          if (target === 'ASKIDA' && !await confirmDialog('Askıya al', 'Kullanıcının tüm oturumları kapanır; hiçbir uygulamaya giriş ve indirme yapamaz.', { okLabel: 'Askıya al', danger: true })) return true;
          await act(() => api.put(`/api/central/sshm/users/${uid}`, { status: target }), target === 'AKTIF' ? 'Hesap etkinleştirildi' : 'Hesap askıya alındı');
        } },
      { label: 'Notu kaydet', class: 'primary', onClick: async () => { await act(() => api.put(`/api/central/sshm/users/${uid}`, { note: note.value }), 'Kaydedildi'); } },
    ],
  });
}

async function releasesView(view) {
  let app = sessionStorage.getItem('mt-rel-app') || 'sm';
  const list = h('div');
  const load = async () => {
    const rows = await api.get(`/api/central/sshm/releases?app=${app}`);
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
          if (!await confirmDialog('Sürümü sil', `${APPN[app]} ${r.version} sürümü ve dosyaları silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
          try { await api.del(`/api/central/sshm/releases/${r.id}`); toast('Sürüm silindi'); await load(); } catch (e) { toastError(e); }
        } }, 'Sil')))))))
      : h('div', { class: 'card empty' }, `Henüz ${APPN[app]} sürümü yüklenmedi. Kullanıcılar Hesabım sayfasında en son yüklenen sürümü indirir.`));
  };
  const ver = h('input', { class: 'input', placeholder: 'ör. 1.2.0' });
  const setup = h('input', { class: 'input', type: 'file', accept: '.exe' });
  const portable = h('input', { class: 'input', type: 'file', accept: '.exe' });
  const notes = h('textarea', { class: 'input', rows: 3, placeholder: 'Bu sürümde neler var? (Hesabım sayfasında görünür)' });
  const prog = h('div', { class: 'small muted' });
  const title = h('h2', { class: 'side-title' });
  const hint = h('p', { class: 'small muted' });
  const btn = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    if (!ver.value.trim() || !setup.files[0]) { toast('Sürüm numarası ve kurulum dosyası gerekli', 'err'); return; }
    const fd = new FormData();
    fd.append('app', app); fd.append('version', ver.value.trim()); fd.append('notes', notes.value); fd.append('setup', setup.files[0]);
    if (portable.files[0]) fd.append('portable', portable.files[0]);
    btn.disabled = true;
    try {
      const r = await upload('/api/central/sshm/releases', fd, p => { prog.textContent = `Yükleniyor… %${p || 0}`; });
      prog.textContent = '';
      toast(`${APPN[app]} ${r.version} yüklendi`);
      ver.value = ''; setup.value = ''; portable.value = ''; notes.value = '';
      await load();
    } catch (e) { prog.textContent = ''; toastError(e); }
    btn.disabled = false;
  } }, 'Sürümü yükle');
  const setApp = v => {
    app = v; sessionStorage.setItem('mt-rel-app', v);
    title.textContent = `Yeni ${APPN[app]} sürümü yükle`;
    hint.textContent = `GitHub Actions aynı uca otomatik yükler: POST /api/${app}/releases (tek istekte ≤ 100 MB) ya da `
      + `/api/${app}/releases/<sürüm>/setup|portable (parçalı), ${{ sm: 'SSHM', fm: 'FTPM', sq: 'SQLM', np: 'NOTEPADM' }[app]}_RELEASE_KEY ile.`;
    load().catch(e => clear(list, h('div', { class: 'card empty' }, e.message)));
  };
  clear(view, segmented(APPS, app, setApp),
    h('div', { class: 'card card-pad', style: { margin: '12px 0 16px' } },
      title,
      h('div', { class: 'row' }, field('Sürüm', ver), field('Kurulum dosyası (Setup .exe)', setup), field('Taşınabilir (isteğe bağlı)', portable)),
      field('Sürüm notları', notes),
      h('div', { class: 'row', style: { alignItems: 'center' } }, btn, prog),
      hint),
    list);
  setApp(app);
}
