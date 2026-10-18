// Araçlar › FTP Master (web): FTP/FTPS (stdlib) + SFTP (sunucuda paramiko varsa). Sol: uzak dizin; sağ: yükle/indir/ad değiştir/sil.
// Bağlantı bilgileri yalnız oturum belleğinde; profil kaydı parolasız (localStorage).
import { api } from '../api.js';
import { clear, confirmDialog, h, onLeave, pageHead, toast, toastError } from '../ui.js';
import { btn, dropZone, fmtBytes, inp, lab, profiles, progress, sel, setStatus, shell, status, uploadRaw, download } from './tool_mt.js';

const PROF = profiles('mt.ftp.profiles');
const ic = { dir: '📁', file: '📄', up: '↩' };

export async function render(view, params, ctx) {
  const st = status('Bağlı değil');
  let sid = null, cwd = '/', items = [], selected = null, caps = null;

  const proto = sel([['ftp', 'FTP'], ['ftps', 'FTPS (TLS)'], ['sftp', 'SFTP']], 'ftp');
  const host = inp({ cls: 'w-m', placeholder: 'ftp.example.com', autocomplete: 'off' });
  const port = inp({ cls: 'w-s', type: 'number', placeholder: '21' });
  const user = inp({ cls: 'w-m', placeholder: 'anonymous', autocomplete: 'off' });
  const pass = inp({ cls: 'w-m', type: 'password', placeholder: 'parola', autocomplete: 'new-password' });
  const passive = sel([['1', 'Pasif'], ['0', 'Aktif']], '1');
  const profSel = sel([['', '— Profil —']], '');
  const refreshProfiles = () => clear(profSel, h('option', { value: '' }, '— Profil —'), PROF.list().map(p => h('option', { value: p.name }, p.name)));
  refreshProfiles();
  profSel.addEventListener('change', () => {
    const p = PROF.list().find(x => x.name === profSel.value);
    if (p) { proto.value = p.protocol; host.value = p.host; port.value = p.port || ''; user.value = p.username; passive.value = p.passive ? '1' : '0'; pass.focus(); }
  });
  proto.addEventListener('change', () => { port.placeholder = proto.value === 'sftp' ? '22' : '21'; if (proto.value === 'sftp' && caps && !caps.sftp) toastError(new Error(caps.sftp_note)); });

  const connBtn = btn('Bağlan', { cls: 'primary', onclick: () => connect() });
  const discBtn = btn('Kes', { cls: 'danger', onclick: () => disconnect(), disabled: true });
  const form = h('div', { class: 'mt-form' },
    lab('Profil', profSel), lab('Protokol', proto), lab('Sunucu', host), lab('Port', port), lab('Kullanıcı', user), lab('Parola', pass), lab('Mod', passive),
    connBtn, discBtn,
    btn('Profili kaydet', { onclick: () => {
      if (!host.value.trim()) return toastError(new Error('Sunucu girin'));
      PROF.save({ name: `${proto.value}://${user.value.trim() || 'anonymous'}@${host.value.trim()}`, protocol: proto.value, host: host.value.trim(), port: port.value ? Number(port.value) : null, username: user.value.trim() || 'anonymous', passive: passive.value === '1' });
      refreshProfiles(); toast('Profil kaydedildi (parolasız)');
    }, title: 'Parola kaydedilmez' }));
  [host, pass].forEach(e => e.addEventListener('keydown', ev => ev.key === 'Enter' && connect()));

  // Sol panel: dizin listesi
  const crumb = h('div', { class: 'mt-crumb' });
  const list = h('div', { class: 'mt-list' });
  const left = h('div', { class: 'mt-panel' }, h('div', { class: 'mt-bar', style: { marginBottom: '6px' } }, crumb, h('span', { class: 'mt-bar right' }, btn('Yenile', { cls: 'sm', onclick: () => load(cwd) }))), list);

  // Sağ panel: işlemler
  const selInfo = h('div', { class: 'mt-kv muted' }, 'Dosya seçilmedi');
  const prog = progress();
  const progTxt = h('div', { class: 'small muted' });
  const right = h('div', { class: 'mt-panel' },
    h('div', { class: 'mt-bar' },
      btn('İndir', { onclick: () => { if (!selected || selected.dir) return toastError(new Error('Bir dosya seçin')); download(`/api/tools/ftp/download?sid=${encodeURIComponent(sid)}&path=${encodeURIComponent(join(cwd, selected.name))}`, selected.name); } }),
      btn('Yeniden adlandır', { onclick: () => rename() }),
      btn('Sil', { cls: 'danger', onclick: () => remove() }),
      btn('Yeni klasör', { onclick: () => mkdir() })),
    h('div', { style: { margin: '10px 0' } }, selInfo),
    dropZone('Dosyaları buraya sürükleyin ya da tıklayıp seçin — geçerli dizine yüklenir', files => uploadFiles(files)),
    h('div', { style: { marginTop: '8px' } }, prog, progTxt));

  const body = h('div', { class: 'mt-split half', style: { display: 'none' } }, left, right);
  const join = (d, n) => (d.endsWith('/') ? d : d + '/') + n;

  async function connect() {
    if (!host.value.trim()) return toastError(new Error('Sunucu girin'));
    connBtn.disabled = true; setStatus(st, 'Bağlanıyor…');
    try {
      const r = await api.post('/api/tools/ftp/connect', { host: host.value.trim(), port: port.value ? Number(port.value) : null, username: user.value.trim() || 'anonymous',
        password: pass.value, protocol: proto.value, passive: passive.value === '1' });
      sid = r.sid; pass.value = '';
      setStatus(st, `Bağlı: ${r.label}`, 'ok'); discBtn.disabled = false; body.style.display = '';
      await load('/');
    } catch (e) { setStatus(st, e.message, 'err'); toastError(e); } finally { connBtn.disabled = false; }
  }
  async function disconnect() {
    if (sid) { try { await api.post(`/api/tools/ftp/disconnect?sid=${encodeURIComponent(sid)}`); } catch { /* */ } }
    sid = null; body.style.display = 'none'; discBtn.disabled = true; setStatus(st, 'Bağlı değil');
  }
  async function load(path) {
    try {
      const r = await api.get(`/api/tools/ftp/list?sid=${encodeURIComponent(sid)}&path=${encodeURIComponent(path)}`);
      cwd = r.path; items = r.items; selected = null; draw();
    } catch (e) { toastError(e); if (e.status === 404) disconnect(); }
  }
  function draw() {
    const parts = cwd.split('/').filter(Boolean);
    clear(crumb, h('a', { onclick: () => load('/') }, '/'), parts.map((p, i) => [h('a', { onclick: () => load('/' + parts.slice(0, i + 1).join('/')) }, p), h('span', null, '/')]));
    clear(list,
      cwd !== '/' ? h('div', { class: 'it', ondblclick: () => load(cwd.replace(/\/[^/]+\/?$/, '') || '/'), onclick: () => load(cwd.replace(/\/[^/]+\/?$/, '') || '/') }, ic.up, '..') : null,
      items.length ? items.map(it => h('div', { class: `it ${selected === it ? 'on' : ''}`,
        onclick: () => { selected = it; draw(); },
        ondblclick: () => { if (it.dir) load(join(cwd, it.name)); } },
      it.dir ? ic.dir : ic.file, it.name, h('small', null, it.dir ? (it.mtime || '') : `${fmtBytes(it.size)} ${it.mtime || ''}`)))
        : h('div', { class: 'muted', style: { padding: '8px' } }, 'Dizin boş'));
    clear(selInfo, selected ? [h('b', null, 'Ad'), h('span', null, selected.name), h('b', null, 'Tür'), h('span', null, selected.dir ? 'Klasör' : 'Dosya'),
      h('b', null, 'Boyut'), h('span', null, fmtBytes(selected.size)), h('b', null, 'Tarih'), h('span', null, selected.mtime || '—')] : 'Dosya seçilmedi');
  }
  async function uploadFiles(files) {
    let i = 0;
    for (const f of files) {
      i++;
      progTxt.textContent = `${f.name} yükleniyor (${i}/${files.length})…`;
      const fd = new FormData(); fd.append('file', f, f.name);
      try { await uploadRaw(`/api/tools/ftp/upload?sid=${encodeURIComponent(sid)}&path=${encodeURIComponent(cwd)}`, fd, pct => prog.set(pct)); }
      catch (e) { toastError(e); break; }
    }
    prog.done(); progTxt.textContent = ''; toast('Yükleme tamamlandı'); load(cwd);
  }
  async function rename() {
    if (!selected) return toastError(new Error('Bir öğe seçin'));
    const name = prompt('Yeni ad', selected.name);
    if (!name || name === selected.name) return;
    try { await api.post(`/api/tools/ftp/rename?sid=${encodeURIComponent(sid)}`, { path: join(cwd, selected.name), new_path: join(cwd, name) }); toast('Yeniden adlandırıldı'); load(cwd); } catch (e) { toastError(e); }
  }
  async function remove() {
    if (!selected) return toastError(new Error('Bir öğe seçin'));
    if (!await confirmDialog('Sil', `${selected.name} silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
    try { await api.post(`/api/tools/ftp/delete?sid=${encodeURIComponent(sid)}`, { path: join(cwd, selected.name), is_dir: selected.dir }); toast('Silindi'); load(cwd); } catch (e) { toastError(e); }
  }
  async function mkdir() {
    const name = prompt('Klasör adı');
    if (!name) return;
    try { await api.post(`/api/tools/ftp/mkdir?sid=${encodeURIComponent(sid)}`, { path: join(cwd, name) }); load(cwd); } catch (e) { toastError(e); }
  }

  onLeave(() => { if (sid) api.post(`/api/tools/ftp/disconnect?sid=${encodeURIComponent(sid)}`).catch(() => {}); });
  clear(view,
    pageHead('FTP Master', { back: '#/tools', sub: 'FTP / FTPS / SFTP — iki panel: uzak dizin · yükle/indir', right: st }),
    shell(form, body, h('div', { class: 'small muted' }, 'Parola yalnız bu oturum için sunucu belleğinde tutulur; 30 dk boşta kalan bağlantı kapanır.')));
  try { caps = await api.get('/api/tools/ftp/caps'); if (!caps.sftp) proto.querySelector('option[value=sftp]').textContent = 'SFTP (sürücü yok)'; } catch (e) { toastError(e); }
}
