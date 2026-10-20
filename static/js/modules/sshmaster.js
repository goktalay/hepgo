// Merkez › Mastertool: tek hesapla SSH Master + FTP Masters kullanıcıları (durum, uygulama lisansı, oturumlar, indirmeler, senkron) ve
// uygulama sürümleri (exe yükleme). Sunucu: Mastertool hesap servisi (central/sshmaster_server) — Merkez /api/central/sshm/* vekil
// uçlarıyla iç anahtarla çağırır. Kullanıcıların şifreleri ve kütüphaneleri burada görünmez (uçtan uca şifreli; sunucu da okuyamaz).
// Kullanıcıların destek talepleri Destek Merkezi'nde "Mastertool · <uygulama>" adıyla görünür.
import { api, upload } from '../api.js';
import { setListExport } from '../listexport.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, pageHead, segmented, statStrip, toast, toastError } from '../ui.js';

const SUBS = [['users', 'Kullanıcılar'], ['releases', 'Sürümler'], ['masterworld', 'MASTERWORLD']];
const APPS = [['sm', 'SSH Master'], ['fm', 'FTP Masters'], ['sq', 'SQL Master'], ['np', 'Notepad Master'], ['cv', 'Convert Master']];
// Oyunlar (hesap servisi GAMES): aynı Mastertool hesabı; kullanım özeti sv_profiles / vf_profiles'tan gelir (SIMUMAV sunucusu uçuş bitiminde ve
// giriş/çıkışta yazar; VOLFAI tarayıcıdan; MASTERWORLD web uygulaması: yalnız ayar kaydı). Tabloda araçlarla birlikte 9 sütun 1920 px'e sığmaz
// → sütun grupları sekmeli ("Araçlar | Oyunlar").
const GAMES = [['sv', 'SIMUMAV'], ['vf', 'VOLFAI'], ['mw', 'MASTERWORLD']];
const GROUPS = [['tools', 'Araçlar'], ['games', 'Oyunlar']];
const APPN = Object.fromEntries([...APPS, ...GAMES]);
const GAMEN = Object.fromEntries(GAMES);
const ST = { AKTIF: ['green', 'Aktif'], BEKLIYOR: ['yellow', 'E-posta bekliyor'], ASKIDA: ['red', 'Askıda'] };
const size = n => (n == null ? '—' : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`);
const badge = s => { const [c, l] = ST[s] || ['', s]; return h('span', { class: `badge ${c}` }, l); };
const used = a => a && (a.app_sessions || a.downloads || a.lib_version);
const played = g => g && g.has_profile;
const hours = v => (v >= 10 ? Math.round(v) : (Math.round((v || 0) * 10) / 10)).toLocaleString('tr-TR');
// Oyun hücresi / Excel metni: sv "N uçuş · H sa · P pilot", vf "Skor S · P parkur"
const gameText = (k, g) => (k === 'sv' ? `${g.flights || 0} uçuş · ${hours(g.hours)} sa · ${g.pilots || 0} pilot`
  : k === 'mw' ? 'Ayarlar kayıtlı' : `Skor ${(g.hi_score || 0).toLocaleString('tr-TR')} · ${g.parkurs || 0} parkur`);
const gameLast = (k, g) => (k === 'sv' && g.last_flight_at) || g.last_at;

export async function render(view, params) {
  const sub = SUBS.some(s => s[0] === params[0]) ? params[0] : 'users';
  const nav = segmented(SUBS, sub, v => { location.hash = `#/sshmaster/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Mastertool', { back: '#/', sub: 'SSH Master, FTP Masters, SQL Master, Notepad Master, Convert Master, SIMUMAV, VOLFAI ve MASTERWORLD — tek hesap, uygulama lisansları, oyun kullanımı, sürümler ve canlı veri kaynakları', tabs: nav }), body);
  return sub === 'releases' ? releasesView(body) : sub === 'masterworld' ? mwView(body) : usersView(body);
}

function appCell(a) {
  if (!a) return h('td', null, '—');
  if (a.license !== 'AKTIF') return h('td', null, h('span', { class: 'badge red' }, 'Kapalı'));
  return h('td', { class: 'small' }, used(a)
    ? [`${a.app_sessions || 0} oturum · ${a.downloads || 0} indirme`, h('div', { class: 'muted' }, a.sync_enabled ? (a.lib_version ? `Senkron ${size(a.lib_size)}` : 'Senkron açık') : 'Senkron kapalı')]
    : h('span', { class: 'muted' }, 'Kullanmadı'));
}

function gameCell(k, g) {
  if (!g) return h('td', null, '—');
  if (!played(g)) return h('td', { class: 'small' }, h('span', { class: 'muted' }, 'Kullanmadı'));
  const last = gameLast(k, g);
  return h('td', { class: 'small' }, gameText(k, g),
    h('div', { class: 'muted' }, last ? `Son ${k === 'sv' ? 'uçuş' : k === 'mw' ? 'güncelleme' : 'kayıt'} ${fmtDateTime(last)}` : '—', k === 'sv' && g.last_version ? ` · v${g.last_version}` : ''));
}

async function usersView(view) {
  const stats = statStrip();
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ad ya da e-posta ara…', style: { width: '260px' } });
  const st = h('select', { class: 'input' }, h('option', { value: '' }, 'Tüm durumlar'), Object.entries(ST).map(([k, [, l]]) => h('option', { value: k }, l)));
  const ap = h('select', { class: 'input' }, h('option', { value: '' }, 'Tüm uygulamalar'),
    h('optgroup', { label: 'Araçlar' }, APPS.map(([k, l]) => h('option', { value: k }, `${l} kullananlar`))),
    h('optgroup', { label: 'Oyunlar' }, GAMES.map(([k, l]) => h('option', { value: k }, `${l} ${k === 'mw' ? 'kullananlar' : 'oynayanlar'}`))));
  let grp = sessionStorage.getItem('mt-col-grp') === 'games' ? 'games' : 'tools';
  const list = h('div');
  let rows = [];
  const matches = u => (!st.value || u.status === st.value) && (!ap.value || (GAMEN[ap.value] ? played(u.games?.[ap.value]) : used(u.apps?.[ap.value])))
    && (!q.value.trim() || `${u.name} ${u.email}`.toLocaleLowerCase('tr').includes(q.value.trim().toLocaleLowerCase('tr')));
  const draw = () => {
    const shown = rows.filter(matches);
    const cols = grp === 'games' ? GAMES : APPS;
    clear(list, shown.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Kullanıcı', 'Durum', 'Kayıt', 'Son giriş', ...cols.map(a => a[1])].map(c => h('th', null, c)))),
      h('tbody', null, shown.map(u => h('tr', { class: 'click', onclick: () => userModal(u.id, load) },
        h('td', null, h('b', null, u.name), h('div', { class: 'small muted' }, u.email), u.note ? h('div', { class: 'small muted' }, `Not: ${u.note}`) : null),
        h('td', null, badge(u.status)),
        h('td', { class: 'small' }, fmtDateTime(u.created_at)),
        h('td', { class: 'small' }, u.last_login ? fmtDateTime(u.last_login) : '—'),
        grp === 'games' ? GAMES.map(([k]) => gameCell(k, u.games?.[k])) : APPS.map(([k]) => appCell(u.apps?.[k])))))))
      : h('div', { class: 'card empty' }, rows.length ? 'Filtreye uyan kullanıcı yok' : 'Henüz kayıtlı kullanıcı yok'));
  };
  const seg = segmented(GROUPS, grp, v => { grp = v; sessionStorage.setItem('mt-col-grp', v); draw(); });
  const setGrp = v => { if (grp !== v) { grp = v; sessionStorage.setItem('mt-col-grp', v); seg.querySelectorAll('button').forEach((b, i) => b.classList.toggle('on', GROUPS[i][0] === v)); } };
  const load = async () => {
    const d = await api.get('/api/central/sshm/users');
    rows = d.users;
    const s = d.stats;
    const per = s.apps || {};
    const g = s.games || {};
    stats.set([
      { icon: 'users', label: 'Kullanıcı', value: s.users, sub: `${s.active} aktif · ${s.pending} bekliyor` },
      { icon: 'warning', label: 'Askıda', value: s.suspended, tone: s.suspended ? 'alert' : '' },
      ...APPS.map(([k, l]) => ({ icon: 'tools', label: l, value: per[k]?.release ? per[k].release.version : '—',
        sub: `${per[k]?.users || 0} kullanıcı · ${per[k]?.downloads || 0} indirme` })),
      { icon: 'drone', label: 'SIMUMAV', key: 'sv', value: g.sv?.release ? g.sv.release.version : '—', onClick: () => { setGrp('games'); draw(); },
        sub: `${g.sv?.users || 0} kullanıcı · ${g.sv?.flights || 0} uçuş` },
      // 10 kart tek satıra sığar: MASTERWORLD (ayar kaydı olan kullanıcı) VOLFAI kartının alt satırında; ayrıntı "Oyunlar" sütununda ve MASTERWORLD sekmesinde
      { icon: 'apps', label: 'VOLFAI', key: 'vf', value: g.vf?.users || 0, onClick: () => { setGrp('games'); draw(); },
        sub: `kullanıcı · MASTERWORLD ${g.mw?.users || 0}` },
    ]);
    draw();
  };
  // Başlıktaki genel Excel düğmesi (listexport): görünen sekme değil, araç VE oyun sütunlarının tümü; filtredeki satırlar
  const appText = a => (!a ? '' : a.license !== 'AKTIF' ? 'Kapalı' : used(a) ? `${a.app_sessions || 0} oturum · ${a.downloads || 0} indirme · senkron ${a.sync_enabled ? 'açık' : 'kapalı'}` : 'Kullanmadı');
  const gText = (k, g) => (!g ? '' : !played(g) ? 'Kullanmadı' : `${gameText(k, g)}${gameLast(k, g) ? ` · son ${fmtDateTime(gameLast(k, g))}` : ''}`);
  setListExport(() => ({ columns: ['Ad', 'E-posta', 'Durum', 'Kayıt', 'Son giriş', ...APPS.map(a => a[1]), ...GAMES.map(a => a[1]), 'Not'],
    rows: rows.filter(matches).map(u => [u.name, u.email, ST[u.status]?.[1] || u.status, fmtDateTime(u.created_at), u.last_login ? fmtDateTime(u.last_login) : '',
      ...APPS.map(([k]) => appText(u.apps?.[k])), ...GAMES.map(([k]) => gText(k, u.games?.[k])), u.note || '']) }));
  q.addEventListener('input', draw);
  st.addEventListener('change', draw);
  ap.addEventListener('change', () => { if (ap.value) setGrp(GAMEN[ap.value] ? 'games' : 'tools'); draw(); });
  clear(view, stats, h('div', { class: 'filters' }, q, st, ap, seg, h('span', { class: 'spacer' }),
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
      h('h3', null, 'Oyunlar ve web uygulamaları'),
      GAMES.map(([k, l]) => {
        const g = d.games?.[k];
        const last = g && gameLast(k, g);
        return h('div', { class: 'card card-pad', style: { marginBottom: '10px' } },
          h('div', { class: 'row', style: { alignItems: 'center' } }, h('b', null, l),
            h('span', { class: `badge ${played(g) ? 'green' : ''}` }, played(g) ? 'Kullanıyor' : 'Kullanmadı'),
            k === 'sv' && g?.last_version ? h('span', { class: 'small muted' }, `v${g.last_version}`) : null),
          played(g) ? h('div', { class: 'small muted' }, gameText(k, g)
            + (k === 'sv' ? ` · ${g.drones || 0} dron${g.pilot ? ` · pilot ${g.pilot}` : ''}` : k === 'mw' ? '' : ` · ${g.levels || 0} bölüm`)
            + (last ? ` · son ${k === 'sv' ? 'uçuş' : 'kayıt'} ${fmtDateTime(last)}` : '')) : null);
      }),
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
      + `/api/${app}/releases/<sürüm>/setup|portable (parçalı), ${{ sm: 'SSHM', fm: 'FTPM', sq: 'SQLM', np: 'NOTEPADM', cv: 'CONVERTM' }[app]}_RELEASE_KEY ile.`;
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

// ======================= MASTERWORLD canlı veri kaynakları (docs/masterworld.md §3.2) =======================
// Hesap servisindeki mw_sources / mw_points kaydı: masterworld.app sunucusu bu kaydı 60 sn'de bir çeker. API anahtarı YALNIZ YAZILIR
// (listede yalnız has_key döner). Haritada çizilen = etkin + adaptör + (anahtar gerekmez ya da anahtar var).
const MW = '/api/central/sshm/mw';
const MW_ST = [['', 'Tüm durumlar'], ['on', 'Etkin'], ['off', 'Kapalı'], ['live', 'Haritada (canlı)'], ['catalog', 'Katalog (adaptörsüz)'], ['keymiss', 'Anahtar eksik']];
const MW_FL = [['', 'Tüm bayraklar'], ['nc', 'Ticari kısıtlı'], ['att', 'Atıf zorunlu'], ['key', 'Anahtar gerekli']];
const MW_MEDIA = [['', '—'], ['image', 'Görüntü (JPEG/PNG)'], ['mjpeg', 'MJPEG akışı'], ['audio', 'Ses akışı'], ['link', 'Bağlantı']];
const MW_BADGES = { display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '4px', alignItems: 'flex-start' };
const num = v => (v === '' || v == null ? null : Number(v));

function mwBadges(s) {
  return [s.noncommercial ? h('span', { class: 'badge orange' }, 'Ticari kısıtlı') : null,
    s.attribution_required ? h('span', { class: 'badge blue' }, 'Atıf') : null,
    s.key_required ? h('span', { class: `badge ${s.has_key ? 'green' : 'yellow'}` }, s.has_key ? 'Anahtar var' : 'Anahtar gerekli') : null].filter(Boolean);
}

async function mwView(view) {
  const stats = statStrip();
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ad, slug, adaptör ya da lisans ara…', style: { width: '260px' } });
  const cat = h('select', { class: 'input' }, h('option', { value: '' }, 'Tüm kategoriler'));
  const st = h('select', { class: 'input' }, MW_ST.map(([k, l]) => h('option', { value: k }, l)));
  const fl = h('select', { class: 'input' }, MW_FL.map(([k, l]) => h('option', { value: k }, l)));
  const list = h('div');
  let D = { sources: [], category_labels: {} };
  const catName = k => D.category_labels?.[k] || k;
  const matches = s => {
    const t = q.value.trim().toLocaleLowerCase('tr');
    if (t && !`${s.name} ${s.slug} ${s.adapter || ''} ${s.license || ''} ${s.kind}`.toLocaleLowerCase('tr').includes(t)) return false;
    if (cat.value && s.category !== cat.value) return false;
    const v = st.value;
    if ((v === 'on' && !s.enabled) || (v === 'off' && s.enabled) || (v === 'live' && !s.live) || (v === 'catalog' && s.adapter) || (v === 'keymiss' && !s.key_missing)) return false;
    return !fl.value || (fl.value === 'nc' ? s.noncommercial : fl.value === 'att' ? s.attribution_required : s.key_required);
  };
  const setStats = () => {
    const S = D.stats || {};
    const pick = v => { st.value = v; draw(); };
    stats.set([
      { icon: 'network', label: 'Kaynak', key: 'mw-total', value: S.total ?? 0, sub: `${D.sources.filter(s => !s.adapter).length} katalog · ${D.sources.filter(s => s.adapter).length} adaptörlü`, onClick: () => pick('') },
      { icon: 'radar', label: 'Etkin', key: 'mw-enabled', value: S.enabled ?? 0, sub: `${(S.total || 0) - (S.enabled || 0)} kapalı`, onClick: () => pick('on') },
      { icon: 'radar', label: 'Haritada (canlı)', key: 'mw-live', value: S.live ?? 0, sub: `${D.sources.filter(s => s.live && s.default_on).length} varsayılan görünür`, onClick: () => pick('live') },
      { icon: 'warning', label: 'Anahtar eksik', key: 'mw-keymiss', value: S.key_missing ?? 0, tone: S.key_missing ? 'alert' : '', sub: 'adaptörlü, anahtar girilmemiş', onClick: () => pick('keymiss') },
    ]);
  };
  const toggle = async (s, b) => {
    b.disabled = true;
    try {
      const r = await api.put(`${MW}/sources/${s.id}`, { enabled: !s.enabled });
      Object.assign(s, r);
      D.stats.enabled = D.sources.filter(x => x.enabled).length; D.stats.live = D.sources.filter(x => x.live).length;
      toast(`${s.name} ${s.enabled ? 'etkinleştirildi' : 'kapatıldı'}`); setStats(); draw();
    } catch (e) { toastError(e); b.disabled = false; }
  };
  const draw = () => {
    const shown = D.sources.filter(matches);
    clear(list, shown.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Kaynak', 'Kategori / tür', 'Adaptör', 'Lisans', 'Oran / TTL', 'Etkin', 'Varsayılan'].map(c => h('th', null, c)))),
      h('tbody', null, shown.map(s => h('tr', { class: 'click', 'data-slug': s.slug, onclick: () => mwSourceModal(s, D, load) },
        h('td', null, h('b', null, s.name), h('div', { class: 'small muted' }, s.slug, s.origin === 'builtin' ? ' · yerleşik' : s.origin === 'manual' ? ' · elle' : '')),
        h('td', { class: 'small' }, catName(s.category), h('div', { class: 'muted' }, s.kind)),
        h('td', { class: 'small' }, s.adapter ? h('code', null, s.adapter) : h('span', { class: 'badge gray' }, 'Katalog'),
          s.adapter === 'points' ? h('div', { class: 'muted' }, `${s.points || 0} nokta`) : null),
        h('td', { class: 'small', style: { maxWidth: '320px' } }, h('div', null, s.license || '—'), h('div', { style: MW_BADGES }, mwBadges(s))),
        h('td', { class: 'small' }, s.rate_per_min != null ? `${s.rate_per_min}/dk` : 'vars.', h('div', { class: 'muted' }, s.ttl_s != null ? `TTL ${s.ttl_s} sn` : 'TTL vars.')),
        h('td', null, (() => {
          const b = h('button', { class: `btn sm ${s.enabled ? '' : 'ghost'}`, type: 'button', title: s.enabled ? 'Kapatmak için tıklayın' : 'Etkinleştirmek için tıklayın',
            onclick: e => { e.stopPropagation(); toggle(s, b); } }, h('span', { class: `badge ${s.enabled ? 'green' : 'gray'}` }, s.enabled ? 'Etkin' : 'Kapalı'));
          return [b, s.enabled && !s.live ? h('div', { class: 'small muted' }, s.adapter ? 'anahtar bekliyor' : 'yalnız listede') : null];
        })()),
        h('td', { class: 'small' }, s.default_on ? h('span', { class: 'badge blue' }, 'Görünür') : h('span', { class: 'muted' }, '—')))))))
      : h('div', { class: 'card empty' }, D.sources.length ? 'Filtreye uyan kaynak yok' : "Henüz kaynak yok — \"Excel'den içe aktar\" ile başlayın"));
  };
  const load = async () => {
    D = await api.get(`${MW}/sources`);
    if (cat.options.length === 1) Object.keys(D.categories || {}).forEach(k => cat.append(h('option', { value: k }, catName(k))));
    setStats(); draw();
  };
  const file = h('input', { type: 'file', accept: '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', style: { display: 'none' } });
  const impBtn = h('button', { class: 'btn', type: 'button', onclick: () => file.click() }, "Excel'den içe aktar");
  file.addEventListener('change', async () => {
    const f = file.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    impBtn.disabled = true;
    try {
      const r = await upload(`${MW}/import`, fd);
      toast(`İçe aktarıldı: ${r.added} yeni · ${r.updated} güncellendi · ${r.unchanged} aynı${r.skipped?.length ? ` · ${r.skipped.length} atlandı` : ''}`);
      modal({ title: "Excel'den içe aktarma sonucu", body: h('div', null,
        h('dl', { class: 'kv' }, h('dt', null, 'Dosya'), h('dd', null, f.name), h('dt', null, 'Satır'), h('dd', null, String(r.rows ?? '—')),
          h('dt', null, 'Yeni eklenen'), h('dd', null, String(r.added)), h('dt', null, 'Güncellenen'), h('dd', null, String(r.updated)),
          h('dt', null, 'Değişmeyen'), h('dd', null, String(r.unchanged)), h('dt', null, 'Atlanan'), h('dd', null, String(r.skipped?.length || 0))),
        r.skipped?.length ? h('table', null, h('thead', null, h('tr', null, h('th', null, 'Satır'), h('th', null, 'Neden'))),
          h('tbody', null, r.skipped.map(x => h('tr', null, h('td', null, String(x.row)), h('td', null, x.reason))))) : null,
        h('p', { class: 'small muted' }, 'Var olan kaynaklarda etkinlik, API anahtarı, sıra, varsayılan görünürlük, parametreler ve elle değiştirilmiş atıf korunur; Excel\'de olmayan kaynak silinmez.')),
      actions: [{ label: 'Tamam', class: 'primary' }] });
      await load();
    } catch (e) { toastError(e); }
    impBtn.disabled = false; file.value = '';
  });
  setListExport(() => ({ columns: ['Ad', 'Slug', 'Kategori', 'Tür', 'Adaptör', 'Lisans', 'Ticari kısıtlı', 'Atıf zorunlu', 'Anahtar gerekli', 'Anahtar var', 'Etkin', 'Canlı', 'Varsayılan', 'Oran/dk', 'TTL sn', 'Atıf'],
    rows: D.sources.filter(matches).map(s => [s.name, s.slug, catName(s.category), s.kind, s.adapter || 'Katalog', s.license || '', s.noncommercial ? 'Evet' : '', s.attribution_required ? 'Evet' : '',
      s.key_required ? 'Evet' : '', s.has_key ? 'Evet' : '', s.enabled ? 'Evet' : 'Hayır', s.live ? 'Evet' : '', s.default_on ? 'Evet' : '', s.rate_per_min ?? '', s.ttl_s ?? '', s.attribution || '']) }));
  [q].forEach(x => x.addEventListener('input', draw));
  [cat, st, fl].forEach(x => x.addEventListener('change', draw));
  clear(view, stats, h('div', { class: 'filters' }, q, cat, st, fl, h('span', { class: 'spacer' }), file, impBtn,
    h('button', { class: 'btn primary', type: 'button', onclick: () => mwSourceModal(null, D, load) }, 'Yeni kaynak'),
    h('a', { class: 'btn', href: 'https://masterworld.app', target: '_blank', rel: 'noopener' }, 'masterworld.app')), list);
  try { await load(); } catch (e) { clear(list, h('div', { class: 'card empty' }, e.message)); }
}

function mwSourceModal(s, D, reload) {
  const isNew = !s;
  s = s || { category: 'camera', kind: 'camera', params: {}, enabled: 0, default_on: 0, key_required: 0, noncommercial: 0, attribution_required: 0, sort: 100 };
  const inp = (k, attrs = {}) => h('input', { class: 'input', value: s[k] ?? '', ...attrs });
  const area = (k, rows = 2) => h('textarea', { class: 'input', rows }, s[k] ?? '');
  const chk = (k, label) => { const c = h('input', { type: 'checkbox', checked: !!s[k] }); c.dataset.k = k; return [c, h('label', { class: 'check' }, c, label)]; };
  const cats = D.categories || {};
  const F = {
    name: inp('name'), slug: inp('slug', { placeholder: 'ör. adsb-lol', pattern: '[a-z0-9-]{2,40}' }),
    category: h('select', { class: 'input' }, Object.keys(cats).map(k => h('option', { value: k, selected: k === s.category }, D.category_labels?.[k] || k))),
    kind: h('select', { class: 'input' }),
    adapter: inp('adapter', { list: 'mw-adapters', placeholder: 'boş = yalnız katalog' }),
    params: h('textarea', { class: 'input', rows: 3, style: { fontFamily: 'monospace' } }, JSON.stringify(s.params || {}, null, 1)),
    api_key: h('input', { class: 'input', type: 'password', autocomplete: 'new-password', placeholder: s.has_key ? 'Kayıtlı — değiştirmek için yazın' : 'Anahtar yok' }),
    attribution: inp('attribution'), attribution_url: inp('attribution_url', { placeholder: 'https://' }),
    rate_per_min: inp('rate_per_min', { type: 'number', min: 0.1, max: 600, step: 'any', placeholder: 'adaptör varsayılanı' }),
    ttl_s: inp('ttl_s', { type: 'number', min: 5, max: 86400, step: 1, placeholder: 'adaptör varsayılanı' }),
    sort: inp('sort', { type: 'number', step: 1 }),
    license: inp('license'), data_desc: inp('data_desc'), endpoint: inp('endpoint'), protocol: inp('protocol'), auth: inp('auth'),
    push_pull: inp('push_pull'), scale: inp('scale'), note: area('note'),
  };
  const fillKinds = () => {
    const own = cats[F.category.value] || [];
    const rest = (D.kinds || []).filter(k => !own.includes(k));
    clear(F.kind, h('optgroup', { label: D.category_labels?.[F.category.value] || F.category.value }, own.map(k => h('option', { value: k }, k))),
      rest.length ? h('optgroup', { label: 'Diğer türler' }, rest.map(k => h('option', { value: k }, k))) : null);
    F.kind.value = own.includes(s.kind) || rest.includes(s.kind) ? s.kind : own[0];
  };
  F.category.addEventListener('change', () => { s.kind = (cats[F.category.value] || [])[0]; fillKinds(); });
  fillKinds();
  let delKey = false;
  const delKeyBtn = s.has_key ? h('button', { class: 'btn sm ghost', type: 'button', onclick: () => {
    delKey = !delKey; delKeyBtn.textContent = delKey ? 'Silinecek (geri al)' : 'Anahtarı sil'; F.api_key.disabled = delKey; F.api_key.value = '';
  } }, 'Anahtarı sil') : null;
  const flags = { enabled: chk('enabled', 'Etkin'), default_on: chk('default_on', 'İlk açılışta görünür'),
    key_required: chk('key_required', 'Anahtar gerekli'), noncommercial: chk('noncommercial', 'Ticari kısıtlı'), attribution_required: chk('attribution_required', 'Atıf zorunlu') };
  const ptsBox = h('div');
  const row = (...xs) => h('div', { class: 'row' }, ...xs);
  const m = modal({
    title: isNew ? 'Yeni MASTERWORLD kaynağı' : `${s.name} — ${s.slug}`, wide: true,
    body: h('div', null,
      h('datalist', { id: 'mw-adapters' }, (D.adapters || []).map(a => h('option', { value: a }))),
      !isNew ? h('div', { style: { ...MW_BADGES, alignItems: 'center', marginBottom: '12px' } },
        h('span', { class: `badge ${s.live ? 'green' : 'gray'}` }, s.live ? 'Haritada (canlı)' : 'Haritada değil'), mwBadges(s),
        h('span', { class: 'small muted' }, `Kaynak: ${s.origin === 'excel' ? 'Excel' : s.origin === 'builtin' ? 'yerleşik' : 'elle'} · güncelleme ${fmtDateTime(s.updated_at)}`)) : null,
      row(field('Ad', F.name), field('Slug', F.slug, '[a-z0-9-], 2–40; içe aktarma anahtarı')),
      row(field('Kategori', F.category), field('Tür (katman)', F.kind), field('Adaptör', F.adapter, 'masterworld sunucusundaki adaptör; boşsa haritada çizilmez')),
      row(field('API anahtarı', h('div', { class: 'row', style: { gap: '6px', alignItems: 'center' } }, F.api_key, delKeyBtn), 'Yalnız yazılır; değer burada ve Merkez kayıtlarında görünmez'),
        field('Adaptör parametreleri (JSON)', F.params, 'JSON nesnesi, ≤ 4 KB')),
      h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: '10px 18px', margin: '6px 0 14px' } }, Object.values(flags).map(x => x[1])),
      row(field('Atıf metni', F.attribution), field('Atıf adresi', F.attribution_url)),
      row(field('Oran (istek/dk)', F.rate_per_min, '0.1–600'), field('Önbellek (TTL sn)', F.ttl_s, '5–86400'), field('Sıra', F.sort)),
      h('h3', null, 'Kaynak bilgisi (Excel)'),
      row(field('Lisans / ticari kullanım', F.license), field('Veri', F.data_desc)),
      row(field('Erişim / endpoint', F.endpoint), field('Protokol', F.protocol), field('Kimlik doğrulama', F.auth)),
      row(field('Push / pull', F.push_pull), field('Ölçek / güncelleme', F.scale)),
      field('Not', F.note),
      ptsBox),
    actions: [
      ...(!isNew ? [{ label: 'Sil', class: 'danger', onClick: async () => {
        if (!await confirmDialog('Kaynağı sil', `${s.name} (${s.slug})${s.points ? ` ve ${s.points} noktası` : ''} kalıcı olarak silinsin mi? Excel yeniden içe aktarılırsa satır yeniden eklenir.`, { okLabel: 'Sil', danger: true })) return true;
        await api.del(`${MW}/sources/${s.id}`); toast('Kaynak silindi'); await reload();
      } }, 'spacer'] : []),
      { label: 'Vazgeç' },
      { label: isNew ? 'Ekle' : 'Kaydet', class: 'primary', onClick: async () => {
        let params;
        try { params = JSON.parse(F.params.value.trim() || '{}'); if (!params || typeof params !== 'object' || Array.isArray(params)) throw new Error(); }
        catch { toast('Parametreler geçerli bir JSON nesnesi olmalı', 'err'); F.params.focus(); return true; }
        const b = { params, category: F.category.value, kind: F.kind.value, adapter: F.adapter.value.trim() || null,
          rate_per_min: num(F.rate_per_min.value), ttl_s: num(F.ttl_s.value), sort: num(F.sort.value) ?? 100 };
        for (const k of ['name', 'slug', 'attribution', 'attribution_url', 'license', 'data_desc', 'endpoint', 'protocol', 'auth', 'push_pull', 'scale', 'note']) b[k] = F[k].value.trim();
        for (const [k, [c]] of Object.entries(flags)) b[k] = c.checked;
        if (delKey) b.api_key = '';
        else if (F.api_key.value.trim()) b.api_key = F.api_key.value.trim();
        try {
          if (isNew) await api.post(`${MW}/sources`, b); else await api.put(`${MW}/sources/${s.id}`, b);
        } catch (e) { toastError(e); return true; }
        toast(isNew ? 'Kaynak eklendi' : 'Kaydedildi'); await reload();
      } },
    ],
  });
  if (!isNew && s.adapter === 'points') mwPoints(s, ptsBox, reload);
  return m;
}

async function mwPoints(s, box, reload) {
  const draw = pts => clear(box, h('h3', null, `Noktalar (${pts.length})`),
    h('p', { class: 'small muted' }, 'Elle eklenen tekil noktalar (kamera, radyo …). Görüntüler masterworld sunucusu vekilinden geçer; ses akışı tarayıcıda doğrudan çalınır. Adres https:// olmalı.'),
    pts.length ? h('table', null, h('thead', null, h('tr', null, ['Ad', 'Konum', 'Medya', 'Durum', ''].map(c => h('th', null, c)))),
      h('tbody', null, pts.map(p => h('tr', null, h('td', null, p.name), h('td', { class: 'small' }, `${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}`),
        h('td', { class: 'small' }, p.media_type ? `${(MW_MEDIA.find(x => x[0] === p.media_type) || [, p.media_type])[1]}` : '—', p.media_url ? h('div', { class: 'muted', style: { wordBreak: 'break-all' } }, p.media_url) : null),
        h('td', null, h('span', { class: `badge ${p.enabled ? 'green' : 'gray'}` }, p.enabled ? 'Etkin' : 'Kapalı')),
        h('td', { class: 'num' }, h('button', { class: 'btn sm ghost', type: 'button', onclick: () => pointModal(p) }, 'Düzenle'),
          h('button', { class: 'btn sm ghost', type: 'button', onclick: async () => {
            if (!await confirmDialog('Noktayı sil', `${p.name} silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
            try { await api.del(`${MW}/points/${p.id}`); toast('Nokta silindi'); await load(); } catch (e) { toastError(e); }
          } }, 'Sil'))))))
      : h('div', { class: 'small muted' }, 'Henüz nokta yok'),
    h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'btn sm', type: 'button', onclick: () => pointModal(null) }, 'Nokta ekle')));
  const load = async () => { draw((await api.get(`${MW}/sources/${s.id}/points`)).points); };
  const pointModal = p => {
    p = p || { enabled: 1 };
    const F = { name: h('input', { class: 'input', value: p.name || '' }), lat: h('input', { class: 'input', type: 'number', step: 'any', min: -90, max: 90, value: p.lat ?? '' }),
      lon: h('input', { class: 'input', type: 'number', step: 'any', min: -180, max: 180, value: p.lon ?? '' }),
      media_type: h('select', { class: 'input' }, MW_MEDIA.map(([k, l]) => h('option', { value: k, selected: (p.media_type || '') === k }, l))),
      media_url: h('input', { class: 'input', value: p.media_url || '', placeholder: 'https://' }), enabled: h('input', { type: 'checkbox', checked: !!p.enabled }) };
    modal({ title: p.id ? `Nokta: ${p.name}` : `${s.name} — yeni nokta`,
      body: h('div', null, field('Ad', F.name), h('div', { class: 'row' }, field('Enlem', F.lat, '−90…90'), field('Boylam', F.lon, '−180…180')),
        h('div', { class: 'row' }, field('Medya türü', F.media_type), field('Medya adresi', F.media_url)), h('label', { class: 'check' }, F.enabled, 'Etkin')),
      actions: [{ label: 'Vazgeç' }, { label: p.id ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const b = { name: F.name.value.trim(), lat: num(F.lat.value), lon: num(F.lon.value), media_type: F.media_type.value || null, media_url: F.media_url.value.trim() || null, enabled: F.enabled.checked };
        try { if (p.id) await api.put(`${MW}/points/${p.id}`, b); else await api.post(`${MW}/sources/${s.id}/points`, b); } catch (e) { toastError(e); return true; }
        toast(p.id ? 'Nokta kaydedildi' : 'Nokta eklendi'); await load(); reload().catch(() => {});
      } }] });
  };
  try { await load(); } catch (e) { clear(box, h('div', { class: 'small muted' }, e.message)); }
}
