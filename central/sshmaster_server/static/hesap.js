// Mastertool web hesap sayfaları (SSH Master + FTP Masters tek hesap): /kayit /giris /sifremi-unuttum /sifre-sifirla/<token> /hesabim
// Site / marka sunucudan gelir (body data-site / data-brand). API öneki /api/mt (kimlik uçları /api/sm ile aynıdır).
// Düz şifre sunucuya HİÇ gitmez: master = PBKDF2-SHA256(şifre, tuz, iter, 32B), auth_hash = b64(PBKDF2-SHA256(master, şifre, 1, 32B))
// (uygulama ile aynı türetme; sözleşme docs/sshmaster-api.md v2). Tuz /api/mt/auth/prelogin'den gelir.
// Çok dil: görünen her metin t('Türkçe kaynak', {değişken}) ile yazılır; sözlük /i18n/hesap.<dil>.json (kit.js yükler).
// #view kitin otomatik çevirisinin dışındadır (data-noi18n); dil değişince geçerli sayfa yeniden çizilir.
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const view = $('#view');
view.setAttribute('data-noi18n', '');
const SITE = document.body.dataset.site || 'sm';
const BRAND = document.body.dataset.brand || SITE;
const NAMES = { sm: 'SSH Master', fm: 'FTP Masters', sq: 'SQL Master', np: 'Notepad Master', cv: 'Convert Master', mt: 'Mastertool' };
const SNAME = NAMES[SITE] || 'Mastertool';
const API = '/api/mt';
const AQ = BRAND !== SITE ? `?app=${BRAND}` : '';   // portalda ürün markası sayfalar arasında korunur
const enc = new TextEncoder();
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const t = (s, v) => (window.mtKit ? window.mtKit.t(s, v) : s.replace(/\{(\w+)\}/g, (m, k) => (v && k in v ? v[k] : m)));
const LOCALES = { tr: 'tr-TR', en: 'en-GB', fr: 'fr-FR', de: 'de-DE', es: 'es-ES', ar: 'ar', zh: 'zh-CN', ru: 'ru-RU' };
const locale = () => LOCALES[window.mtKit?.lang] || 'tr-TR';
const b64 = buf => btoa(String.fromCharCode(...new Uint8Array(buf)));
const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));

async function authHash(password, kdf) {
  const pw = enc.encode(password);
  const base = await crypto.subtle.importKey('raw', pw, 'PBKDF2', false, ['deriveBits']);
  const master = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: unb64(kdf.salt), iterations: kdf.iter }, base, 256);
  const mk = await crypto.subtle.importKey('raw', master, 'PBKDF2', false, ['deriveBits']);
  return b64(await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: pw, iterations: 1 }, mk, 256));
}
window.__sshmAuthHash = authHash;   // test vektörü doğrulaması için

async function api(path, opts = {}) {
  const r = await fetch(path, { method: opts.method || 'GET', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-SSHM': '1' }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  let d = null;
  try { d = await r.json(); } catch { /* boş */ }
  if (!r.ok) {   // sunucu iletileri Türkçe sabit metinlerdir; sözlükte varsa çevrilir
    const e = new Error(d && (d.message || d.detail) ? t(d.message || d.detail) : t('Hata ({n})', { n: r.status }));
    e.code = d && d.code; e.status = r.status; throw e;
  }
  return d;
}
async function prelogin(email) { return (await api(`${API}/auth/prelogin`, { method: 'POST', body: { email } })).kdf; }

function msg(el, text, kind = 'err') { el.innerHTML = text ? `<div class="msg ${kind}">${text}</div>` : ''; }
function busy(btn, on, label) { btn.disabled = on; if (label) btn.textContent = on ? t('Lütfen bekleyin…') : label; }
const qs = new URLSearchParams(location.search);
const nextUrl = () => { const n = qs.get('sonra') || ''; return /^\/(indir|hesabim)\b/.test(n) ? n : '/hesabim'; };

function pwRules(p) { return p.length >= 8; }

// ---------- sayfalar ----------
function pageRegister() {
  document.title = `${t('Hesap oluştur')} — ${SNAME}`;
  view.innerHTML = `<h1>${t('Hesap oluşturun')}</h1><p class="muted small">${t('Tek Mastertool hesabıyla tüm Mastertool uygulamalarını indirin, kayıtlarınızı cihazlar arasında şifreli eşitleyin.')}</p>
    <form id="f" autocomplete="on">
      <label for="n">${t('Ad soyad')}</label><input id="n" autocomplete="name" required>
      <label for="e">${t('E-posta')}</label><input id="e" type="email" autocomplete="email" required>
      <label for="p">${t('Şifre')}</label><input id="p" type="password" autocomplete="new-password" required minlength="8">
      <div class="hint">${t('En az 8 karakter. Şifreniz bu tarayıcıda şifrelenir; sunucuya düz hâliyle gitmez.')}</div>
      <label for="p2">${t('Şifre (tekrar)')}</label><input id="p2" type="password" autocomplete="new-password" required>
      <button class="btn primary block" id="b">${t('Hesap oluştur')}</button>
      <div id="m"></div>
    </form>
    <div class="links"><a href="/giris${AQ}">${t('Zaten hesabım var')}</a></div>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#m'), b = $('#b'), name = $('#n').value.trim(), email = $('#e').value.trim(), p = $('#p').value;
    if (!pwRules(p)) return msg(m, t('Şifre en az 8 karakter olmalı'));
    if (p !== $('#p2').value) return msg(m, t('Şifreler aynı değil'));
    busy(b, true, t('Hesap oluştur'));
    try {
      const kdf = await prelogin(email);
      await api(`${API}/auth/register`, { method: 'POST', body: { name, email, auth_hash: await authHash(p, kdf), brand: BRAND } });
      view.innerHTML = `<h1>${t('E-postanızı kontrol edin')}</h1><p class="muted">${t('{email} adresine bir doğrulama bağlantısı gönderdik. Bağlantıya tıklayınca hesabınız açılır ve indirme sayfanıza yönlenirsiniz. Bağlantı 24 saat geçerlidir.', { email: `<b>${esc(email)}</b>` })}</p>
        <p class="muted small">${t('E-posta gelmediyse gereksiz klasörüne bakın ya da <a href="#" id="rs">yeniden gönderin</a>.')}</p><div id="m"></div>`;
      $('#rs').onclick = async e => { e.preventDefault(); await api(`${API}/auth/resend-verify`, { method: 'POST', body: { email, brand: BRAND } }).catch(() => {}); msg($('#m'), t('Doğrulama e-postası yeniden gönderildi'), 'ok'); };
    } catch (e) { msg(m, esc(e.message)); busy(b, false, t('Hesap oluştur')); }
  };
}

function pageLogin() {
  document.title = `${t('Giriş')} — ${SNAME}`;
  const durum = { 'dogrulama-gecersiz': [t('Doğrulama bağlantısı geçersiz ya da süresi dolmuş. Giriş yapmayı deneyin ya da yeniden kayıt olun.'), 'err'],
    askida: [t('Hesabınız askıya alınmış.'), 'err'], sifirlandi: [t('Şifreniz değişti. Yeni şifrenizle giriş yapın.'), 'ok'],
    cikis: [t('Çıkış yaptınız.'), 'info'] }[qs.get('durum')];
  view.innerHTML = `<h1>${t('Giriş yapın')}</h1>
    <p class="muted small">${t('Mastertool hesabınız tüm Mastertool uygulamalarında aynıdır.')}</p>
    ${qs.get('sonra') ? `<div class="msg info">${t('İndirme bağlantınız kişiye özeldir; devam etmek için giriş yapın.')}</div>` : ''}
    ${durum ? `<div class="msg ${durum[1]}">${durum[0]}</div>` : ''}
    <form id="f" autocomplete="on">
      <label for="e">${t('E-posta')}</label><input id="e" type="email" autocomplete="username" required>
      <label for="p">${t('Şifre')}</label><input id="p" type="password" autocomplete="current-password" required>
      <button class="btn primary block" id="b">${t('Giriş yap')}</button>
      <div id="m"></div>
    </form>
    <div class="links"><a href="/sifremi-unuttum${AQ}">${t('Şifremi unuttum')}</a><a href="/kayit${AQ}">${t('Hesap oluştur')}</a></div>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#m'), b = $('#b'), email = $('#e').value.trim(), p = $('#p').value;
    busy(b, true, t('Giriş yap'));
    try {
      const kdf = await prelogin(email);
      await api(`${API}/auth/login`, { method: 'POST', body: { email, auth_hash: await authHash(p, kdf), client: 'web' } });
      location.href = nextUrl();
    } catch (e) {
      msg(m, esc(e.message) + (e.code === 'unverified' ? ` <a href="#" id="rs">${t('Doğrulama e-postasını yeniden gönder')}</a>` : ''));
      const rs = $('#rs');
      if (rs) rs.onclick = async x => { x.preventDefault(); await api(`${API}/auth/resend-verify`, { method: 'POST', body: { email, brand: BRAND } }).catch(() => {}); msg(m, t('Doğrulama e-postası yeniden gönderildi'), 'ok'); };
      busy(b, false, t('Giriş yap'));
    }
  };
}

function pageForgot() {
  document.title = `${t('Şifremi unuttum')} — ${SNAME}`;
  view.innerHTML = `<h1>${t('Şifremi unuttum')}</h1><p class="muted small">${t('Kayıtlı e-posta adresinize şifre sıfırlama bağlantısı gönderelim.')}</p>
    <form id="f"><label for="e">${t('E-posta')}</label><input id="e" type="email" autocomplete="email" required>
      <button class="btn primary block" id="b">${t('Bağlantı gönder')}</button><div id="m"></div></form>
    <div class="links"><a href="/giris${AQ}">${t('Girişe dön')}</a></div>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const b = $('#b');
    busy(b, true, t('Bağlantı gönder'));
    try {
      await api(`${API}/auth/forgot`, { method: 'POST', body: { email: $('#e').value.trim(), brand: BRAND } });
      msg($('#m'), t('Bu e-postayla kayıtlı bir hesap varsa sıfırlama bağlantısı gönderildi. Bağlantı 1 saat geçerlidir.'), 'ok');
    } catch (e) { msg($('#m'), esc(e.message)); }
    busy(b, false, t('Bağlantı gönder'));
  };
}

async function pageReset(tok) {
  document.title = `${t('Yeni şifre')} — ${SNAME}`;
  let info;
  try { info = await api(`${API}/auth/reset/${encodeURIComponent(tok)}`); } catch (e) {
    view.innerHTML = `<h1>${t('Bağlantı geçersiz')}</h1><p class="muted">${esc(e.message)}</p><div class="links"><a href="/sifremi-unuttum${AQ}">${t('Yeni bağlantı iste')}</a></div>`;
    return;
  }
  view.innerHTML = `<h1>${t('Yeni şifre belirleyin')}</h1><p class="muted small">${esc(info.email)}</p>
    <div class="msg info">${t('Yeni şifre tüm Mastertool uygulamaları için birlikte geçerli olur. Şifre değişince web\'de saklanan şifreli kütüphaneleriniz silinir; uygulamalarda yeni şifrenizle giriş yaptığınızda bilgisayarınızdaki kayıtlar yeniden yüklenir.')}</div>
    <form id="f"><label for="p">${t('Yeni şifre')}</label><input id="p" type="password" autocomplete="new-password" required minlength="8">
      <label for="p2">${t('Yeni şifre (tekrar)')}</label><input id="p2" type="password" autocomplete="new-password" required>
      <button class="btn primary block" id="b">${t('Şifreyi kaydet')}</button><div id="m"></div></form>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#m'), b = $('#b'), p = $('#p').value;
    if (!pwRules(p)) return msg(m, t('Şifre en az 8 karakter olmalı'));
    if (p !== $('#p2').value) return msg(m, t('Şifreler aynı değil'));
    busy(b, true, t('Şifreyi kaydet'));
    try {
      await api(`${API}/auth/reset/${encodeURIComponent(tok)}`, { method: 'POST', body: { new_auth_hash: await authHash(p, info.kdf) } });
      location.href = '/giris?durum=sifirlandi';
    } catch (e) { msg(m, esc(e.message)); busy(b, false, t('Şifreyi kaydet')); }
  };
}

const fmtSize = n => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n || 0} B`);
const fmtDate = s => (s ? new Date(s).toLocaleString(locale(), { dateStyle: 'medium', timeStyle: 'short' }) : '—');
const TABS = () => [['uygulamalar', t('Uygulamalar')], ['cihazlar', t('Cihazlar')], ['guvenlik', t('Şifre')], ['destek', t('Destek')]];
const TK_STATUS = () => ({ acik: [t('Açık'), 'warn'], yanit_bekliyor: [t('Yanıtlandı'), 'on'], cozuldu: [t('Çözüldü'), ''], kapali: [t('Kapalı'), ''] });
const TK_APPS = () => ({ sm: 'SSH Master', fm: 'FTP Masters', sq: 'SQL Master', np: 'Notepad Master', cv: 'Convert Master', mt: t('Hesap / genel') });
let ACC = null;
let curTab = null;

async function pageAccount() {
  document.title = `${t('Hesabım')} — ${SNAME}`;
  try { ACC = await api(`${API}/account`); } catch (e) {
    if (e.status === 401 || e.status === 403) { location.href = `/giris${AQ}`; return; }
    view.textContent = e.message; return;
  }
  $('#box').classList.add('wide');
  const tab = curTab || (location.hash || '').slice(1);
  const cur = TABS().some(x => x[0] === tab) ? tab : (qs.get('talep') ? 'destek' : 'uygulamalar');
  view.innerHTML = `<button class="btn sm top-right" id="out">${t('Çıkış')}</button>
    <h1>${t('Merhaba, {name}', { name: esc(ACC.user.name) })}</h1><p class="muted small">${esc(ACC.user.email)} · ${t('Mastertool hesabı')}</p>
    ${qs.get('durum') === 'dogrulandi' ? `<div class="msg ok">${t('E-postanız doğrulandı, hesabınız açıldı.')}</div>` : ''}
    <div class="tabs">${TABS().map(([k, l]) => `<button type="button" data-tab="${k}" class="${k === cur ? 'on' : ''}">${l}</button>`).join('')}</div>
    <div id="pane"></div>`;
  $('#out').onclick = async () => { await api(`${API}/auth/logout`, { method: 'POST' }).catch(() => {}); location.href = `/giris${AQ}${AQ ? '&' : '?'}durum=cikis`; };
  view.querySelectorAll('[data-tab]').forEach(b => { b.onclick = () => { history.replaceState(null, '', `${location.pathname}${location.search}#${b.dataset.tab}`); show(b.dataset.tab); }; });
  show(cur);
}

function show(tab) {
  curTab = tab;
  view.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  const pane = $('#pane');
  ({ uygulamalar: paneApps, cihazlar: paneDevices, guvenlik: panePassword, destek: paneSupport }[tab] || paneApps)(pane);
}

function paneApps(pane) {
  const order = [...ACC.apps].sort((a, b) => (b.app === BRAND) - (a.app === BRAND));
  const L = ACC.launcher, lr = L && L.release;
  const launcher = L ? `<div class="app-card launcher">
      <div class="head"><img src="/brand/mt.png" alt=""><div class="grow"><b>${esc(L.name)}</b>
        <div class="muted small">${lr ? t('Sürüm {v} · {size} · {date}', { v: esc(lr.version), size: fmtSize(lr.size), date: fmtDate(lr.date) }) : t('İndirilebilir sürüm yakında')}</div></div></div>
      <p class="hint">${t('Tüm Mastertool uygulamalarını tek pencereden kurun, açın ve güncelleyin; bir kez giriş yapın, hepsi açılsın.')}</p>
      ${lr ? `<div class="row"><a class="btn primary" href="${esc(L.download_url)}">${t('İndir (Windows)')}</a>
        ${lr.portable ? `<a class="btn" href="${esc(L.download_url)}?tur=portable">${t('Taşınabilir sürüm')}</a>` : ''}</div>
        <p class="hint">SHA-256: <code>${esc(lr.sha256)}</code></p>` : ''}
    </div>` : '';
  pane.innerHTML = `${launcher}<div class="apps">${order.map(x => {
    const r = x.release, off = x.license !== 'AKTIF';
    return `<div class="app-card ${off ? 'off' : ''}">
      <div class="head"><img src="/brand/${x.app}.png" alt=""><div class="grow"><b>${esc(x.name)}</b>
        <div class="muted small">${r ? t('Sürüm {v} · {size} · {date}', { v: esc(r.version), size: fmtSize(r.size), date: fmtDate(r.date) }) : t('İndirilebilir sürüm yakında')}</div></div>
        ${off ? `<span class="badge off">${t('Hesabınızda kapalı')}</span>` : ''}</div>
      ${off ? `<p class="hint">${t('Bu uygulamanın kullanımı hesabınız için kapatılmış. Bilgi için Destek sekmesinden talep açabilirsiniz.')}</p>` : `
      ${r ? `<div class="row"><a class="btn primary" href="${esc(x.download_url)}">${t('İndir (Windows)')}</a>
        ${r.portable ? `<a class="btn" href="${esc(x.download_url)}?tur=portable">${t('Taşınabilir sürüm')}</a>` : ''}</div>
        ${r.notes ? `<p class="muted small" style="white-space:pre-wrap">${esc(r.notes)}</p>` : ''}
        <p class="hint">SHA-256: <code>${esc(r.sha256)}</code> · ${t('Bu bağlantı size özeldir ve yalnız bu hesapla oturum açmışken çalışır.')}</p>` : ''}
      <div class="kv" style="margin-top:12px"><span>${t('Senkronizasyon')}</span><span>${x.sync_enabled ? `<span class="badge on">${t('Açık')}</span>` : `<span class="badge">${t('Kapalı (uygulama ayarlarından)')}</span>`}</span>
        <span>${t('Şifreli kopya')}</span><span>${x.library.version ? t('{size} · son eşitleme {date}', { size: fmtSize(x.library.size), date: fmtDate(x.library.updated_at) }) + (x.library.device ? ` · ${esc(x.library.device)}` : '') : t('Henüz eşitleme yok')}</span></div>`}
    </div>`;
  }).join('')}</div>
  <p class="hint">${t('Kayıtlarınız uçtan uca şifrelenir; anahtar yalnız sizin cihazlarınızda bulunur, sunucu içeriği okuyamaz.')}</p>`;
}

function paneDevices(pane) {
  const kind = s => (s.kind === 'web' ? 'Web' : s.kind === 'sso' ? t('Ortak oturum (Master Tool)') : (TK_APPS()[s.app || 'sm'] || t('Uygulama')));
  pane.innerHTML = `<table><tr><th>${t('Cihaz')}</th><th>${t('Uygulama')}</th><th>${t('Son görülme')}</th><th></th></tr>
    ${ACC.sessions.map(s => `<tr><td>${esc(s.device || (s.kind === 'web' ? t('Tarayıcı') : t('Uygulama')))}${s.app_version ? ` <span class="muted small">v${esc(s.app_version)}</span>` : ''}</td>
      <td>${kind(s)}</td><td>${fmtDate(s.last_seen)}</td>
      <td>${s.current ? `<span class="badge on">${t('Bu oturum')}</span>` : `<button class="btn sm danger" data-sid="${s.id}">${t('Kapat')}</button>`}</td></tr>`).join('')}</table>
    <p class="hint">${t('Tanımadığınız bir cihaz görürseniz oturumu kapatın ve şifrenizi değiştirin.')}</p>`;
  pane.querySelectorAll('[data-sid]').forEach(b => { b.onclick = async () => {
    await api(`${API}/sessions/${b.dataset.sid}`, { method: 'DELETE' });
    ACC = await api(`${API}/account`); paneDevices(pane);
  }; });
}

function panePassword(pane) {
  pane.innerHTML = `<form id="pf"><label for="op">${t('Mevcut şifre')}</label><input id="op" type="password" autocomplete="current-password" required>
      <label for="np">${t('Yeni şifre')}</label><input id="np" type="password" autocomplete="new-password" required minlength="8">
      <label for="np2">${t('Yeni şifre (tekrar)')}</label><input id="np2" type="password" autocomplete="new-password" required>
      <div class="hint">${t('Yeni şifre tüm Mastertool uygulamaları için birlikte geçerli olur. Şifre değişince web\'deki şifreli kopyalar silinir ve diğer cihazlardaki oturumlar kapanır; uygulamalarda yeni şifreyle giriş yaptığınızda bilgisayarınızdaki kayıtlar yeniden yüklenir.')}</div>
      <button class="btn block" id="pb">${t('Şifreyi değiştir')}</button><div id="pm"></div></form>`;
  $('#pf').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#pm'), b = $('#pb'), np = $('#np').value;
    if (!pwRules(np)) return msg(m, t('Yeni şifre en az 8 karakter olmalı'));
    if (np !== $('#np2').value) return msg(m, t('Yeni şifreler aynı değil'));
    busy(b, true, t('Şifreyi değiştir'));
    try {
      const me = await api(`${API}/me`);
      const fresh = (await api(`${API}/auth/new-salt`, { method: 'POST' })).kdf;
      await api(`${API}/auth/change-password`, { method: 'POST', body: {
        old_auth_hash: await authHash($('#op').value, me.kdf), new_auth_hash: await authHash(np, fresh), new_salt: fresh.salt } });
      $('#pf').reset();
      msg(m, t('Şifreniz değişti. Uygulamalarda yeni şifrenizle giriş yapın.'), 'ok');
    } catch (e) { msg(m, esc(e.message)); }
    busy(b, false, t('Şifreyi değiştir'));
  };
}

const tkBadge = st => { const [l, c] = TK_STATUS()[st] || [st, '']; return `<span class="badge ${c}">${esc(l)}</span>`; };
let openTicket = null;

async function paneSupport(pane, openId) {
  openId = openId ?? openTicket ?? (qs.get('talep') ? Number(qs.get('talep')) : null);
  if (openId) return ticketView(pane, openId);
  openTicket = null;
  pane.innerHTML = `<p class="muted">${t('Yükleniyor…')}</p>`;
  let rows;
  try { rows = await api(`${API}/tickets`); } catch (e) { pane.innerHTML = `<div class="msg err">${esc(e.message)}</div>`; return; }
  pane.innerHTML = `<div style="display:flex;align-items:center;gap:10px"><h2 style="margin:8px 0;flex:1">${t('Destek talepleri')}</h2>
      <button class="btn sm" id="nt">${t('Yeni talep')}</button></div>
    <div id="nf"></div>
    ${rows.length ? rows.map(x => `<div class="tk" data-id="${x.id}">${x.unread ? `<span class="dot" title="${t('Yeni yanıt')}"></span>` : ''}
        <div class="grow"><b>${esc(x.subject)}</b><div class="muted small">${esc(x.code)} · ${esc(TK_APPS()[x.app] || '')} · ${fmtDate(x.updated_at)}</div></div>
        ${tkBadge(x.status)}</div>`).join('') : `<p class="muted">${t('Henüz destek talebiniz yok.')}</p>`}`;
  pane.querySelectorAll('[data-id]').forEach(el => { el.onclick = () => ticketView(pane, Number(el.dataset.id)); });
  $('#nt').onclick = () => newTicket($('#nf'), pane);
  if (!rows.length) newTicket($('#nf'), pane);
}

function newTicket(box, pane) {
  const apps = TK_APPS(), def = BRAND in apps ? BRAND : 'mt';
  box.innerHTML = `<form id="tf" class="app-card" style="margin:10px 0">
      <label for="ta">${t('Uygulama')}</label><select id="ta">${Object.entries(apps).map(([k, l]) => `<option value="${k}" ${k === def ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <label for="tc">${t('Konu türü')}</label><select id="tc"><option value="teknik">${t('Teknik sorun')}</option><option value="oneri">${t('Öneri')}</option><option value="diger">${t('Diğer')}</option></select>
      <label for="ts">${t('Konu')}</label><input id="ts" maxlength="200" required>
      <label for="tb">${t('Açıklama')}</label><textarea id="tb" maxlength="8000" required placeholder="${t('Ne oldu? Hangi sürümü kullanıyorsunuz? Hata iletisi varsa ekleyin.')}"></textarea>
      <button class="btn primary block" id="tsb">${t('Talebi gönder')}</button><div id="tm"></div></form>`;
  $('#tf').onsubmit = async ev => {
    ev.preventDefault();
    const b = $('#tsb');
    busy(b, true, t('Talebi gönder'));
    try {
      const r = await api(`${API}/tickets`, { method: 'POST', body: { app: $('#ta').value, category: $('#tc').value, subject: $('#ts').value.trim(), body: $('#tb').value.trim() } });
      ticketView(pane, r.id);
    } catch (e) { msg($('#tm'), esc(e.message)); busy(b, false, t('Talebi gönder')); }
  };
}

async function ticketView(pane, id) {
  openTicket = id;
  const back = () => { const bk = $('#bk'); if (bk) bk.onclick = ev => { ev.preventDefault(); openTicket = null; history.replaceState(null, '', `${location.pathname}#destek`); paneSupport(pane, 0); }; };
  pane.innerHTML = `<p class="muted">${t('Yükleniyor…')}</p>`;
  let tk;
  try { tk = await api(`${API}/tickets/${id}`); } catch (e) {
    pane.innerHTML = `<div class="msg err">${esc(e.message)}</div><div class="links"><a href="#destek" id="bk">${t('← Taleplerim')}</a></div>`;
    back();
    return;
  }
  const closed = ['cozuldu', 'kapali'].includes(tk.status);
  pane.innerHTML = `<div class="links" style="margin-top:4px"><a href="#destek" id="bk">${t('← Taleplerim')}</a></div>
    <h2 style="margin-top:10px">${esc(tk.subject)}</h2>
    <div class="muted small">${esc(tk.code)} · ${esc(TK_APPS()[tk.app] || '')} · ${fmtDate(tk.created_at)} ${tkBadge(tk.status)}</div>
    <div class="thread">${tk.messages.map(m => m.author_kind === 'system'
      ? `<div class="bubble sys">${esc(t(m.body))} · ${fmtDate(m.created_at)}</div>`
      : `<div class="bubble ${m.author_kind === 'company' ? 'me' : ''}"><div class="who">${m.author_kind === 'company' ? t('Siz') : esc(m.author_name || t('Destek'))} · ${fmtDate(m.created_at)}</div>${esc(m.body)}</div>`).join('')}</div>
    <form id="rf"><label for="rb">${closed ? t('Yanıt yazarsanız talep yeniden açılır') : t('Yanıtınız')}</label><textarea id="rb" maxlength="8000" required></textarea>
      <div class="row" style="display:flex;gap:10px;margin-top:12px"><button class="btn primary" id="rsb">${t('Gönder')}</button>
      ${closed ? '' : `<button class="btn" type="button" id="cl">${t('Sorunum çözüldü, kapat')}</button>`}</div><div id="rm"></div></form>`;
  back();
  $('#rf').onsubmit = async ev => {
    ev.preventDefault();
    const b = $('#rsb');
    busy(b, true, t('Gönder'));
    try { await api(`${API}/tickets/${id}/messages`, { method: 'POST', body: { body: $('#rb').value.trim() } }); ticketView(pane, id); }
    catch (e) { msg($('#rm'), esc(e.message)); busy(b, false, t('Gönder')); }
  };
  const cl = $('#cl');
  if (cl) cl.onclick = async () => { try { await api(`${API}/tickets/${id}/close`, { method: 'POST' }); ticketView(pane, id); } catch (e) { msg($('#rm'), esc(e.message)); } };
}

function route() {
  const p = location.pathname.replace(/\/+$/, '');
  if (p === '/kayit') pageRegister();
  else if (p === '/giris') pageLogin();
  else if (p === '/sifremi-unuttum') pageForgot();
  else if (p.startsWith('/sifre-sifirla/')) pageReset(decodeURIComponent(p.slice('/sifre-sifirla/'.length)));
  else pageAccount();
}
// kit sözlüğü yükleyip 'mt-lang' yayınlayınca çiz; dil değişince yeniden çiz. Kit yüklenemezse Türkçe çizilir.
let started = false;
addEventListener('mt-lang', () => { started = true; route(); });
setTimeout(() => { if (!started) { started = true; route(); } }, 1500);
