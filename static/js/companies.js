// Çok-şirketli giriş: bir kullanıcı birden fazla firmada (ayrı alan adları, ayrı süreçler) çalışabilir. Her firma ayrı
// bir alan adıdır (ör. gokkubbe.hepgo.com) ve merkezî bir "kullanıcı→firmalar" eşlemesi yoktur; bu yüzden girilen
// firmalar BU CİHAZDA hatırlanır: logo + firma adı + son kullanılan kullanıcı adı. Giriş ekranının altındaki
// "Şirket değiştir" ile hatırlanan firmalara tek dokunuşla geçilir ya da adres/kod yazılarak yeni firmaya gidilir.
import { clear, field, h } from './ui.js';

const KEY = 'hepgo.companies';
const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; } };
const write = list => { try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, 8))); } catch { /* gizli pencere */ } };
export const forgetCompany = url => write(read().filter(c => c.url !== url));

// Logoyu küçük bir data URL kopyasına çevir (başka alan adında/çevrimdışıyken de görünsün)
async function logoDataUrl(src) {
  if (!src) return null;
  try {
    const abs = new URL(src, location.origin).href;
    const blob = await (await fetch(abs)).blob();
    if (blob.size > 400 * 1024) return abs;   // çok büyükse yalnız adresi sakla
    return await new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => res(abs); r.readAsDataURL(blob); });
  } catch { return null; }
}

// Başarılı girişten sonra: bu firmayı cihaza kaydet (logo + firma adı + kullanıcı adı)
export async function rememberCompany(meta, username) {
  const url = location.origin;
  const company = meta?.company || location.hostname;
  const entry = { url, company, username: username || '', logo: null, ts: Date.now() };
  const list = read().filter(c => c.url !== url);
  const prev = read().find(c => c.url === url);
  list.unshift(entry);
  write(list);
  // logo: meta'da varsa indir; yoksa önceki kayıttaki logoyu koru
  const logo = await logoDataUrl(meta?.logo_url) || prev?.logo || null;
  if (logo) write(read().map(c => (c.url === url ? { ...c, logo } : c)));
}

export const hasCompanies = () => read().length > 0;

// Yalnız GÜVENİLEN firma alan adlarına yönlendirilir (phishing/açık-yönlendirme engeli): capacitor allowNavigation
// listesiyle aynı köken kümesi. Rastgele bir host (ör. evil.com) girilirse reddedilir — kullanıcı sahte giriş
// sayfasına yönlendirilip kimlik bilgisi çalınamasın.
const TRUSTED_SUFFIXES = ['.hepgo.com', '.caymaz.app', '.veilox.app', '.firma.app'];
const TRUSTED_EXACT = ['hepgo.com', 'caymaz.app', 'veilox.app', 'firma.app'];
const isTrustedHost = host => TRUSTED_EXACT.includes(host) || TRUSTED_SUFFIXES.some(sfx => host.endsWith(sfx));

// Girilen adresi/kodu firma adresine çevir: "gokkubbe" → gokkubbe.hepgo.com ; tam adres yalnız güvenilir alan adıysa
function resolveAddress(raw) {
  let s = (raw || '').trim().toLowerCase();
  if (!s) return null;
  s = s.replace(/^https?:\/\//, '').replace(/[/?#].*$/, '').replace(/\s+/g, '').replace(/:\d+$/, '');
  if (!s) return null;
  if (!s.includes('.')) s = `${s}.hepgo.com`;   // yalnız kod/slug girildiyse hepgo.com altına
  if (!/^[a-z0-9.-]+$/.test(s) || s.includes('..')) return null;   // geçersiz karakter
  if (!isTrustedHost(s)) return null;           // güvenilmeyen alan adı: reddet
  return s;
}

const goto = host => { location.href = `https://${host}/app`; };

const avatarOf = c => h('span', { class: 'acc-av co-av' }, c.logo ? h('img', { src: c.logo, alt: '' })
  : (c.company || '?').split(/\s+/).slice(0, 2).map(x => x[0]).join('').toLocaleUpperCase('tr'));

// "Şirket değiştir" ekranı: HEPGO markalı; hatırlanan firmalar + "Başka şirketle gir" (adres/kod gir)
// box: içeriğin basılacağı kapsayıcı. onBack: geri (normal girişe dön). Çağıran, üstteki logo/başlığı HEPGO'ya çevirir.
export function companySwitcher(box, { onBack }) {
  const list = read();

  const showAddress = () => {
    const addr = h('input', { class: 'input', type: 'text', autocomplete: 'off', autocapitalize: 'off', spellcheck: false, placeholder: 'firma.hepgo.com veya firma kodu' });
    const err = h('div', { class: 'pin-err' });
    const submit = h('button', { class: 'btn primary lg', type: 'submit' }, 'Devam');
    const form = h('form', { class: 'acc-form co-addr' },
      list.length ? h('button', { type: 'button', class: 'acc-back', onclick: showList, title: 'Geri' }, '←') : null,
      h('div', { class: 'co-hint' }, 'Gireceğiniz firmanın adresini veya kodunu yazın. Firmanın giriş ekranına yönlendirileceksiniz.'),
      field('Firma adresi / kodu', addr), err, submit,
      h('button', { type: 'button', class: 'btn ghost acc-other', onclick: onBack }, '← Girişe dön'));
    form.addEventListener('submit', e => {
      e.preventDefault();
      const host = resolveAddress(addr.value);
      if (!host) { err.textContent = 'Geçerli bir firma adresi veya kodu girin'; addr.focus(); return; }
      submit.disabled = true;
      goto(host);
    });
    clear(box, form);
    addr.focus();
  };

  const showList = () => {
    if (!list.length) { showAddress(); return; }
    clear(box,
      h('div', { class: 'acc-title' }, 'Kayıtlı firmalarınız'),
      h('div', { class: 'acc-list co-list' }, list.map(c => h('div', { class: 'acc-item' },
        h('button', { type: 'button', class: 'acc-btn', onclick: () => { let hst; try { hst = new URL(c.url).host; } catch { return; } if (isTrustedHost(hst)) goto(hst); } },
          avatarOf(c), h('b', null, c.company), h('small', null, c.username || c.url.replace(/^https?:\/\//, ''))),
        h('button', { type: 'button', class: 'acc-x', title: 'Bu cihazdan kaldır', onclick: () => {
          forgetCompany(c.url); list.splice(list.indexOf(c), 1); showList();
        } }, '×')))),
      h('button', { type: 'button', class: 'btn primary co-other', onclick: showAddress }, 'Başka şirketle gir'),
      h('button', { type: 'button', class: 'btn ghost acc-other', onclick: onBack }, '← Girişe dön'));
  };

  showList();
}
