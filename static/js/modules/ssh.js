// SSH Erişim — yalnızca MASTER (sistem sahibi). Kayıtlı uzak sunuculara (ör. fabrikadaki GX10) tarayıcıdan bağlanıp
// komut çalıştırır. Parola / özel anahtar sunucuda şifreli saklanır, hiç geri dönmez. Her bağlantı denetim kaydına yazılır.
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, pageHead, selectInput, t, toast, toastError } from '../ui.js';
import { openTerminal } from './console.js';

export async function render(view, params, ctx) {
  if (!ctx.user.master) { clear(view, h('div', { class: 'card empty' }, 'SSH Erişim yalnızca sistem sahibine açıktır.')); return; }
  if (params[0] === 'c' && /^\d+$/.test(params[1] || '')) {
    const id = Number(params[1]);
    let hosts = [];
    try { hosts = await api.get('/api/ssh/hosts'); } catch { /* */ }
    const hh = hosts.find(x => x.id === id);
    return openTerminal(view, { title: hh ? hh.label : 'SSH', back: '#/master/ssh',
      sub: hh ? `${hh.username}@${hh.host}:${hh.port}` : 'Sistem sahibi · uzak sunucu', wsUrl: `/ws/ssh/${id}` });
  }
  draw(view);
}

async function draw(view) {
  let hosts;
  try { hosts = await api.get('/api/ssh/hosts'); } catch (e) { toastError(e); return; }
  const addBtn = h('button', { class: 'btn primary', onclick: () => form(null, () => draw(view)) }, '+ Sunucu ekle');
  const rows = hosts.map(hh => h('div', { class: 'ssh-row card' },
    h('div', { class: 'ssh-main' },
      h('b', null, hh.label),
      h('span', { class: 'small muted' }, `${hh.username}@${hh.host}:${hh.port} · ${hh.auth_type === 'key' ? 'anahtar' : 'parola'}`),
      hh.note ? h('span', { class: 'small muted' }, hh.note) : null,
      hh.last_used ? h('span', { class: 'small muted' }, `Son bağlantı: ${fmtDateTime(hh.last_used)}`) : null),
    h('div', { class: 'ssh-acts' },
      h('a', { class: 'btn sm primary', href: `#/master/ssh/c/${hh.id}` }, 'Bağlan'),
      h('button', { class: 'btn sm', onclick: () => form(hh, () => draw(view)) }, 'Düzenle'),
      h('button', { class: 'btn sm danger', onclick: () => remove(hh, () => draw(view)) }, 'Sil'))));
  clear(view,
    pageHead('SSH Erişim', { back: '#/master', sub: 'Sistem sahibi · kayıtlı uzak sunucular' }),
    h('div', { class: 'filters' }, h('div', { class: 'spacer' }), addBtn),
    h('p', { class: 'small muted ssh-note' }, 'Buradaki bağlantılar sunucudan dışa doğru kurulur (uzak makinede komut çalıştırır); merkez sunucuda kabuk açmaz. Parola ve anahtarlar şifreli saklanır, ekranda bir daha gösterilmez. Her bağlantı denetim kaydına yazılır.'),
    hosts.length ? h('div', { class: 'ssh-list' }, rows) : h('div', { class: 'card empty' }, 'Henüz sunucu eklenmedi.'));
}

function form(hh, done) {
  const label = h('input', { class: 'input', value: hh?.label || '', placeholder: 'Örn. Fabrika GX10' });
  const host = h('input', { class: 'input', value: hh?.host || '', placeholder: 'IP ya da alan adı' });
  const port = h('input', { class: 'input', type: 'number', value: String(hh?.port || 22), style: { width: '110px' } });
  const username = h('input', { class: 'input', value: hh?.username || '', placeholder: 'kullanıcı adı', autocapitalize: 'none' });
  const authSel = selectInput([['password', 'Parola'], ['key', 'Özel anahtar']], { all: '', value: hh?.auth_type || 'password' });
  const pass = h('input', { class: 'input', type: 'password', autocomplete: 'new-password',
    placeholder: hh?.has_secret ? '(değiştirmek için yeni parola)' : 'parola' });
  const key = h('textarea', { class: 'input', rows: 5, spellcheck: 'false',
    placeholder: hh?.has_secret ? '(değiştirmek için yeni özel anahtarı yapıştırın)' : '-----BEGIN OPENSSH PRIVATE KEY-----', style: { fontFamily: 'monospace', fontSize: '12px' } });
  const note = h('input', { class: 'input', value: hh?.note || '', placeholder: 'not (isteğe bağlı)' });
  const secRow = field('Parola', pass), keyRow = field('Özel anahtar', key);
  const sync = () => { const k = authSel.value === 'key'; secRow.style.display = k ? 'none' : ''; keyRow.style.display = k ? '' : 'none'; };
  authSel.addEventListener('change', sync); sync();

  modal({
    title: hh ? 'SSH sunucusunu düzenle' : 'SSH sunucusu ekle', wide: true,
    body: h('div', null,
      field('Ad', label), field('Sunucu', host), field('Port', port), field('Kullanıcı', username),
      field('Kimlik', authSel), secRow, keyRow, field('Not', note)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async ({ close }) => {
      const body = { label: label.value, host: host.value, port: Number(port.value) || 22, username: username.value,
        auth_type: authSel.value, secret: (authSel.value === 'key' ? key.value : pass.value) || null, note: note.value };
      try {
        if (hh) await api.put(`/api/ssh/hosts/${hh.id}`, body); else await api.post('/api/ssh/hosts', body);
        toast('Kaydedildi'); close(); done();
      } catch (e) { toastError(e); return true; }
    } }],
  });
}

async function remove(hh, done) {
  if (!await confirmDialog('Sunucuyu sil', `“${hh.label}” (${hh.username}@${hh.host}) silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
  try { await api.del(`/api/ssh/hosts/${hh.id}`); toast('Silindi'); done(); } catch (e) { toastError(e); }
}
