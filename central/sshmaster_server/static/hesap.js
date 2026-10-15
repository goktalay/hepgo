// SSH Master web hesap sayfaları: /kayit /giris /sifremi-unuttum /sifre-sifirla/<token> /hesabim
// Düz şifre sunucuya HİÇ gitmez: master = PBKDF2-SHA256(şifre, tuz, iter, 32B), auth_hash = b64(PBKDF2-SHA256(master, şifre, 1, 32B))
// (uygulama ile aynı türetme; sözleşme docs/sshmaster-api.md v2). Tuz /api/sm/auth/prelogin'den gelir.
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const view = $('#view');
const enc = new TextEncoder();
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
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
  if (!r.ok) { const e = new Error((d && (d.message || d.detail)) || `Hata (${r.status})`); e.code = d && d.code; e.status = r.status; throw e; }
  return d;
}
async function prelogin(email) { return (await api('/api/sm/auth/prelogin', { method: 'POST', body: { email } })).kdf; }

function msg(el, text, kind = 'err') { el.innerHTML = text ? `<div class="msg ${kind}">${text}</div>` : ''; }
function busy(btn, on, label) { btn.disabled = on; if (label) btn.textContent = on ? 'Lütfen bekleyin…' : label; }
const qs = new URLSearchParams(location.search);
const nextUrl = () => { const n = qs.get('sonra') || ''; return /^\/(indir|hesabim)\b/.test(n) ? n : '/hesabim'; };

function pwRules(p) { return p.length >= 8; }

// ---------- sayfalar ----------
function pageRegister() {
  document.title = 'Hesap oluştur — SSH Master';
  view.innerHTML = `<h1>Hesap oluşturun</h1><p class="muted small">SSH Master'ı indirmek ve bağlantılarınızı cihazlar arasında eşitlemek için.</p>
    <form id="f" autocomplete="on">
      <label for="n">Ad soyad</label><input id="n" autocomplete="name" required>
      <label for="e">E-posta</label><input id="e" type="email" autocomplete="email" required>
      <label for="p">Şifre</label><input id="p" type="password" autocomplete="new-password" required minlength="8">
      <div class="hint">En az 8 karakter. Şifreniz bu tarayıcıda şifrelenir; sunucuya düz hâliyle gitmez.</div>
      <label for="p2">Şifre (tekrar)</label><input id="p2" type="password" autocomplete="new-password" required>
      <button class="btn primary block" id="b">Hesap oluştur</button>
      <div id="m"></div>
    </form>
    <div class="links"><a href="/giris">Zaten hesabım var</a></div>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#m'), b = $('#b'), name = $('#n').value.trim(), email = $('#e').value.trim(), p = $('#p').value;
    if (!pwRules(p)) return msg(m, 'Şifre en az 8 karakter olmalı');
    if (p !== $('#p2').value) return msg(m, 'Şifreler aynı değil');
    busy(b, true, 'Hesap oluştur');
    try {
      const kdf = await prelogin(email);
      await api('/api/sm/auth/register', { method: 'POST', body: { name, email, auth_hash: await authHash(p, kdf) } });
      view.innerHTML = `<h1>E-postanızı kontrol edin</h1><p class="muted"><b>${esc(email)}</b> adresine bir doğrulama bağlantısı gönderdik.
        Bağlantıya tıklayınca hesabınız açılır ve indirme sayfanıza yönlenirsiniz. Bağlantı 24 saat geçerlidir.</p>
        <p class="muted small">E-posta gelmediyse gereksiz klasörüne bakın ya da <a href="#" id="rs">yeniden gönderin</a>.</p><div id="m"></div>`;
      $('#rs').onclick = async e => { e.preventDefault(); await api('/api/sm/auth/resend-verify', { method: 'POST', body: { email } }).catch(() => {}); msg($('#m'), 'Doğrulama e-postası yeniden gönderildi', 'ok'); };
    } catch (e) { msg(m, esc(e.message)); busy(b, false, 'Hesap oluştur'); }
  };
}

function pageLogin() {
  document.title = 'Giriş — SSH Master';
  const durum = { 'dogrulama-gecersiz': ['Doğrulama bağlantısı geçersiz ya da süresi dolmuş. Giriş yapmayı deneyin ya da yeniden kayıt olun.', 'err'],
    askida: ['Hesabınız askıya alınmış.', 'err'], sifirlandi: ['Şifreniz değişti. Yeni şifrenizle giriş yapın.', 'ok'],
    cikis: ['Çıkış yaptınız.', 'info'] }[qs.get('durum')];
  view.innerHTML = `<h1>Giriş yapın</h1>
    ${qs.get('sonra') ? '<div class="msg info">İndirme bağlantınız kişiye özeldir; devam etmek için giriş yapın.</div>' : ''}
    ${durum ? `<div class="msg ${durum[1]}">${durum[0]}</div>` : ''}
    <form id="f" autocomplete="on">
      <label for="e">E-posta</label><input id="e" type="email" autocomplete="username" required>
      <label for="p">Şifre</label><input id="p" type="password" autocomplete="current-password" required>
      <button class="btn primary block" id="b">Giriş yap</button>
      <div id="m"></div>
    </form>
    <div class="links"><a href="/sifremi-unuttum">Şifremi unuttum</a><a href="/kayit">Hesap oluştur</a></div>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#m'), b = $('#b'), email = $('#e').value.trim(), p = $('#p').value;
    busy(b, true, 'Giriş yap');
    try {
      const kdf = await prelogin(email);
      await api('/api/sm/auth/login', { method: 'POST', body: { email, auth_hash: await authHash(p, kdf), client: 'web' } });
      location.href = nextUrl();
    } catch (e) {
      msg(m, esc(e.message) + (e.code === 'unverified' ? ' <a href="#" id="rs">Doğrulama e-postasını yeniden gönder</a>' : ''));
      const rs = $('#rs');
      if (rs) rs.onclick = async x => { x.preventDefault(); await api('/api/sm/auth/resend-verify', { method: 'POST', body: { email } }).catch(() => {}); msg(m, 'Doğrulama e-postası yeniden gönderildi', 'ok'); };
      busy(b, false, 'Giriş yap');
    }
  };
}

function pageForgot() {
  document.title = 'Şifremi unuttum — SSH Master';
  view.innerHTML = `<h1>Şifremi unuttum</h1><p class="muted small">Kayıtlı e-posta adresinize şifre sıfırlama bağlantısı gönderelim.</p>
    <form id="f"><label for="e">E-posta</label><input id="e" type="email" autocomplete="email" required>
      <button class="btn primary block" id="b">Bağlantı gönder</button><div id="m"></div></form>
    <div class="links"><a href="/giris">Girişe dön</a></div>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const b = $('#b');
    busy(b, true, 'Bağlantı gönder');
    try {
      await api('/api/sm/auth/forgot', { method: 'POST', body: { email: $('#e').value.trim() } });
      msg($('#m'), 'Bu e-postayla kayıtlı bir hesap varsa sıfırlama bağlantısı gönderildi. Bağlantı 1 saat geçerlidir.', 'ok');
    } catch (e) { msg($('#m'), esc(e.message)); }
    busy(b, false, 'Bağlantı gönder');
  };
}

async function pageReset(tok) {
  document.title = 'Yeni şifre — SSH Master';
  let info;
  try { info = await api(`/api/sm/auth/reset/${encodeURIComponent(tok)}`); } catch (e) {
    view.innerHTML = `<h1>Bağlantı geçersiz</h1><p class="muted">${esc(e.message)}</p><div class="links"><a href="/sifremi-unuttum">Yeni bağlantı iste</a></div>`;
    return;
  }
  view.innerHTML = `<h1>Yeni şifre belirleyin</h1><p class="muted small">${esc(info.email)}</p>
    <div class="msg info">Şifre değişince web'de saklanan şifreli bağlantı kütüphaneniz silinir. Uygulamada yeni şifrenizle giriş yaptığınızda
      bilgisayarınızdaki kütüphane yeniden yüklenir.</div>
    <form id="f"><label for="p">Yeni şifre</label><input id="p" type="password" autocomplete="new-password" required minlength="8">
      <label for="p2">Yeni şifre (tekrar)</label><input id="p2" type="password" autocomplete="new-password" required>
      <button class="btn primary block" id="b">Şifreyi kaydet</button><div id="m"></div></form>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#m'), b = $('#b'), p = $('#p').value;
    if (!pwRules(p)) return msg(m, 'Şifre en az 8 karakter olmalı');
    if (p !== $('#p2').value) return msg(m, 'Şifreler aynı değil');
    busy(b, true, 'Şifreyi kaydet');
    try {
      await api(`/api/sm/auth/reset/${encodeURIComponent(tok)}`, { method: 'POST', body: { new_auth_hash: await authHash(p, info.kdf) } });
      location.href = '/giris?durum=sifirlandi';
    } catch (e) { msg(m, esc(e.message)); busy(b, false, 'Şifreyi kaydet'); }
  };
}

const fmtSize = n => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n || 0} B`);
const fmtDate = s => (s ? new Date(s).toLocaleString('tr-TR', { dateStyle: 'medium', timeStyle: 'short' }) : '—');

async function pageAccount() {
  document.title = 'Hesabım — SSH Master';
  let a;
  try { a = await api('/api/sm/account'); } catch (e) {
    if (e.status === 401 || e.status === 403) { location.href = '/giris'; return; }
    view.textContent = e.message; return;
  }
  $('#box').classList.add('wide');
  const r = a.release;
  view.innerHTML = `<button class="btn sm top-right" id="out">Çıkış</button>
    <h1>Merhaba, ${esc(a.user.name)}</h1><p class="muted small">${esc(a.user.email)}</p>
    ${qs.get('durum') === 'dogrulandi' ? '<div class="msg ok">E-postanız doğrulandı, hesabınız açıldı.</div>' : ''}
    <h2>SSH Master'ı indirin</h2>
    ${r ? `<div class="dl"><div class="grow"><b>SSH Master ${esc(r.version)}</b><div class="muted small">Windows kurulum dosyası · ${fmtSize(r.size)} · ${fmtDate(r.date)}</div>
        <div class="hint">Bu bağlantı size özeldir ve yalnız bu hesapla oturum açmışken çalışır.</div></div>
        <a class="btn primary" href="${esc(a.download_url)}">İndir</a>
        ${r.portable ? `<a class="btn" href="${esc(a.download_url)}?tur=portable">Taşınabilir sürüm</a>` : ''}</div>
        ${r.notes ? `<p class="muted small" style="white-space:pre-wrap">${esc(r.notes)}</p>` : ''}
        <p class="hint">SHA-256: <code>${esc(r.sha256)}</code></p>`
      : '<div class="msg info">İndirilebilir sürüm yakında burada olacak.</div>'}
    <h2>Senkronizasyon</h2>
    <div class="kv"><span>Durum</span><span>${a.sync_enabled ? '<span class="badge on">Açık</span>' : '<span class="badge">Kapalı (uygulama ayarlarından)</span>'}</span>
      <span>Web'deki kütüphane</span><span>${a.library.version ? `${fmtSize(a.library.size)} · son eşitleme ${fmtDate(a.library.updated_at)}${a.library.device ? ` · ${esc(a.library.device)}` : ''}` : 'Henüz eşitleme yok'}</span></div>
    <p class="hint">Bağlantılarınız uçtan uca şifrelenir; anahtar yalnız sizin cihazlarınızda bulunur, sunucu içeriği okuyamaz.</p>
    <h2>Oturumlar</h2>
    <table><tr><th>Cihaz</th><th>Tür</th><th>Son görülme</th><th></th></tr>
      ${a.sessions.map(s => `<tr><td>${esc(s.device || (s.kind === 'web' ? 'Tarayıcı' : 'Uygulama'))}${s.app_version ? ` <span class="muted small">v${esc(s.app_version)}</span>` : ''}</td>
        <td>${s.kind === 'web' ? 'Web' : 'Uygulama'}</td><td>${fmtDate(s.last_seen)}</td>
        <td>${s.current ? '<span class="badge on">Bu oturum</span>' : `<button class="btn sm danger" data-sid="${s.id}">Kapat</button>`}</td></tr>`).join('')}</table>
    <h2>Şifre değiştir</h2>
    <form id="pf"><label for="op">Mevcut şifre</label><input id="op" type="password" autocomplete="current-password" required>
      <label for="np">Yeni şifre</label><input id="np" type="password" autocomplete="new-password" required minlength="8">
      <label for="np2">Yeni şifre (tekrar)</label><input id="np2" type="password" autocomplete="new-password" required>
      <div class="hint">Şifre değişince web'deki şifreli kütüphane silinir ve diğer cihazlardaki oturumlar kapanır; uygulamada yeni şifreyle
        giriş yaptığınızda bilgisayarınızdaki kütüphane yeniden yüklenir.</div>
      <button class="btn block" id="pb">Şifreyi değiştir</button><div id="pm"></div></form>`;
  $('#out').onclick = async () => { await api('/api/sm/auth/logout', { method: 'POST' }).catch(() => {}); location.href = '/giris?durum=cikis'; };
  view.querySelectorAll('[data-sid]').forEach(b => { b.onclick = async () => { await api(`/api/sm/sessions/${b.dataset.sid}`, { method: 'DELETE' }); pageAccount(); }; });
  $('#pf').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#pm'), b = $('#pb'), np = $('#np').value;
    if (!pwRules(np)) return msg(m, 'Yeni şifre en az 8 karakter olmalı');
    if (np !== $('#np2').value) return msg(m, 'Yeni şifreler aynı değil');
    busy(b, true, 'Şifreyi değiştir');
    try {
      const me = await api('/api/sm/me');
      const fresh = (await api('/api/sm/auth/new-salt', { method: 'POST' })).kdf;
      await api('/api/sm/auth/change-password', { method: 'POST', body: {
        old_auth_hash: await authHash($('#op').value, me.kdf), new_auth_hash: await authHash(np, fresh), new_salt: fresh.salt } });
      $('#pf').reset();
      msg(m, 'Şifreniz değişti. Uygulamada yeni şifrenizle giriş yapın.', 'ok');
    } catch (e) { msg(m, esc(e.message)); }
    busy(b, false, 'Şifreyi değiştir');
  };
}

const p = location.pathname.replace(/\/+$/, '');
if (p === '/kayit') pageRegister();
else if (p === '/giris') pageLogin();
else if (p === '/sifremi-unuttum') pageForgot();
else if (p.startsWith('/sifre-sifirla/')) pageReset(decodeURIComponent(p.slice('/sifre-sifirla/'.length)));
else pageAccount();
