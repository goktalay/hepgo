// Bu cihazdaki hesaplar (telefonlardaki gibi): şifreyle giriş yapılan hesap cihazda hatırlanır; giriş ekranında fotoğraf
// ve adıyla listelenir. Tıklanınca PIN'i varsa 4 haneli PIN, yoksa yalnızca şifre sorulur (kullanıcı adı yazılmaz).
// Cihazda saklanan: sunucunun verdiği cihaz jetonu (tek başına giriş sağlamaz), ad, kullanıcı adı ve küçük fotoğraf.
import { api, fileUrl } from './api.js';
import { clear, field, h, toastError } from './ui.js';

const KEY = 'caymaz.accounts';
const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; } };
const write = list => { try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, 8))); } catch { /* gizli pencere */ } };
export const accountToken = username => read().find(a => a.username === username)?.token;

// Şifreyle girişten sonra: hesabı cihaza kaydet (fotoğraf küçük kopyası data URL olarak)
export async function rememberAccount(user, token) {
  if (!token) return;
  const list = read().filter(a => a.id !== user.id);
  const acc = { id: user.id, username: user.username, full_name: user.full_name, token, photo: null };
  list.unshift(acc);
  write(list);
  if (user.photo) {
    try {
      const blob = await (await fetch(fileUrl(user.photo, 128))).blob();
      acc.photo = await new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(blob); });
      write(read().map(a => (a.id === acc.id ? { ...a, photo: acc.photo } : a)));
    } catch { /* fotoğrafsız da olur */ }
  }
}
export const forgetAccount = id => write(read().filter(a => a.id !== id));

const avatarOf = a => h('span', { class: 'acc-av' }, a.photo ? h('img', { src: a.photo, alt: '' })
  : (a.full_name || '?').split(/\s+/).slice(0, 2).map(x => x[0]).join('').toLocaleUpperCase('tr'));

// Giriş kartının içeriği: hesap listesi → PIN / şifre. Hesap yoksa null döner (normal giriş formu gösterilir).
export async function accountChooser(box, { onLogin, onOther }) {
  let list = read();
  if (!list.length) return false;
  try {
    const valid = await api.post('/api/auth/devices', { tokens: list.map(a => a.token) });
    const by = new Map(valid.map(v => [v.token, v]));
    list = list.filter(a => by.has(a.token)).map(a => ({ ...a, ...by.get(a.token) }));
    write(list);
  } catch { /* sunucuya ulaşılamazsa kayıtlı liste gösterilir */ }
  if (!list.length) return false;

  const showList = () => clear(box,
    h('div', { class: 'acc-title' }, 'Hesap seçin'),
    h('div', { class: 'acc-list' }, list.map(a => h('div', { class: 'acc-item' },
      h('button', { type: 'button', class: 'acc-btn', onclick: () => (a.has_pin ? showPin(a) : showPassword(a)) },
        avatarOf(a), h('b', null, a.full_name), h('small', null, a.has_pin ? 'PIN ile giriş' : 'Şifre ile giriş')),
      h('button', { type: 'button', class: 'acc-x', title: 'Bu cihazdan kaldır', onclick: () => {
        forgetAccount(a.id); list = list.filter(x => x.id !== a.id); if (list.length) showList(); else onOther();
      } }, '×')))),
    h('button', { type: 'button', class: 'btn ghost acc-other', onclick: onOther }, 'Başka bir hesapla giriş yap'));

  const header = a => [h('button', { type: 'button', class: 'acc-back', onclick: showList, title: 'Hesaplar' }, '←'),
    h('div', { class: 'acc-me' }, avatarOf(a), h('b', null, a.full_name))];

  function showPassword(a) {
    const pw = h('input', { class: 'input', type: 'password', autocomplete: 'current-password', required: true });
    const submit = h('button', { class: 'btn primary lg', type: 'submit' }, 'Giriş Yap');
    const form = h('form', { class: 'acc-form' }, ...header(a), field('Şifre', pw), submit);
    form.addEventListener('submit', async e => {
      e.preventDefault();
      submit.disabled = true;
      try {
        const r = await api.post('/api/auth/login', { username: a.username, password: pw.value, device_token: a.token });
        await onLogin(r.device_token);
      } catch (err) { toastError(err); pw.select(); } finally { submit.disabled = false; }
    });
    clear(box, form);
    pw.focus();
  }

  function showPin(a) {
    let pin = '';
    const dots = h('div', { class: 'pin-dots' });
    const err = h('div', { class: 'pin-err' });
    const pad = h('div', { class: 'pin-pad' });
    const draw = () => clear(dots, [0, 1, 2, 3].map(i => h('i', { class: i < pin.length ? 'on' : '' })));
    const submit = async () => {
      try {
        await api.post('/api/auth/login-pin', { token: a.token, pin });
        await onLogin(null);
      } catch (ex) {
        pin = ''; draw();
        err.textContent = ex.message;
        dots.classList.remove('shake'); void dots.offsetWidth; dots.classList.add('shake');
        if (ex.status === 401) { a.has_pin = false; setTimeout(() => showPassword(a), 1200); }
      }
    };
    const press = k => {
      err.textContent = '';
      if (k === '⌫') pin = pin.slice(0, -1);
      else if (pin.length < 4) pin += k;
      draw();
      if (pin.length === 4) submit();
    };
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', '⌫'].forEach(k => pad.append(k ? h('button', { type: 'button', class: `pin-key ${k === '⌫' ? 'del' : ''}`, onclick: () => press(k) }, k) : h('span')));
    const onKey = e => {
      if (!box.isConnected || !box.contains(dots)) { removeEventListener('keydown', onKey); return; }
      if (/^\d$/.test(e.key)) press(e.key); else if (e.key === 'Backspace') press('⌫');
    };
    addEventListener('keydown', onKey);
    draw();
    clear(box, ...header(a), h('div', { class: 'pin-title' }, 'PIN kodunuzu girin'), dots, err, pad,
      h('button', { type: 'button', class: 'btn ghost acc-other', onclick: () => showPassword(a) }, 'Şifreyle giriş yap'));
  }

  showList();
  return true;
}
