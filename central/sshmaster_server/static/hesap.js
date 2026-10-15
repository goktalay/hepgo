// Mastertool web hesap sayfaları (SSH Master + FTP Masters tek hesap): /kayit /giris /sifremi-unuttum /sifre-sifirla/<token> /hesabim
// Site / marka sunucudan gelir (body data-site / data-brand). API öneki /api/mt (kimlik uçları /api/sm ile aynıdır).
// Düz şifre sunucuya HİÇ gitmez: master = PBKDF2-SHA256(şifre, tuz, iter, 32B), auth_hash = b64(PBKDF2-SHA256(master, şifre, 1, 32B))
// (uygulama ile aynı türetme; sözleşme docs/sshmaster-api.md v2). Tuz /api/mt/auth/prelogin'den gelir.
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const view = $('#view');
const SITE = document.body.dataset.site || 'sm';
const BRAND = document.body.dataset.brand || SITE;
const NAMES = { sm: 'SSH Master', fm: 'FTP Masters', mt: 'Mastertool' };
const SNAME = NAMES[SITE] || 'Mastertool';
const API = '/api/mt';
const AQ = BRAND !== SITE ? `?app=${BRAND}` : '';   // portalda ürün markası sayfalar arasında korunur
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
async function prelogin(email) { return (await api(`${API}/auth/prelogin`, { method: 'POST', body: { email } })).kdf; }

function msg(el, text, kind = 'err') { el.innerHTML = text ? `<div class="msg ${kind}">${text}</div>` : ''; }
function busy(btn, on, label) { btn.disabled = on; if (label) btn.textContent = on ? 'Lütfen bekleyin…' : label; }
const qs = new URLSearchParams(location.search);
const nextUrl = () => { const n = qs.get('sonra') || ''; return /^\/(indir|hesabim)\b/.test(n) ? n : '/hesabim'; };

function pwRules(p) { return p.length >= 8; }

// ---------- sayfalar ----------
function pageRegister() {
  document.title = `Hesap oluştur — ${SNAME}`;
  view.innerHTML = `<h1>Hesap oluşturun</h1><p class="muted small">Tek Mastertool hesabıyla SSH Master ve FTP Masters'ı indirin, kayıtlarınızı cihazlar arasında şifreli eşitleyin.</p>
    <form id="f" autocomplete="on">
      <label for="n">Ad soyad</label><input id="n" autocomplete="name" required>
      <label for="e">E-posta</label><input id="e" type="email" autocomplete="email" required>
      <label for="p">Şifre</label><input id="p" type="password" autocomplete="new-password" required minlength="8">
      <div class="hint">En az 8 karakter. Şifreniz bu tarayıcıda şifrelenir; sunucuya düz hâliyle gitmez.</div>
      <label for="p2">Şifre (tekrar)</label><input id="p2" type="password" autocomplete="new-password" required>
      <button class="btn primary block" id="b">Hesap oluştur</button>
      <div id="m"></div>
    </form>
    <div class="links"><a href="/giris${AQ}">Zaten hesabım var</a></div>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#m'), b = $('#b'), name = $('#n').value.trim(), email = $('#e').value.trim(), p = $('#p').value;
    if (!pwRules(p)) return msg(m, 'Şifre en az 8 karakter olmalı');
    if (p !== $('#p2').value) return msg(m, 'Şifreler aynı değil');
    busy(b, true, 'Hesap oluştur');
    try {
      const kdf = await prelogin(email);
      await api(`${API}/auth/register`, { method: 'POST', body: { name, email, auth_hash: await authHash(p, kdf), brand: BRAND } });
      view.innerHTML = `<h1>E-postanızı kontrol edin</h1><p class="muted"><b>${esc(email)}</b> adresine bir doğrulama bağlantısı gönderdik.
        Bağlantıya tıklayınca hesabınız açılır ve indirme sayfanıza yönlenirsiniz. Bağlantı 24 saat geçerlidir.</p>
        <p class="muted small">E-posta gelmediyse gereksiz klasörüne bakın ya da <a href="#" id="rs">yeniden gönderin</a>.</p><div id="m"></div>`;
      $('#rs').onclick = async e => { e.preventDefault(); await api(`${API}/auth/resend-verify`, { method: 'POST', body: { email, brand: BRAND } }).catch(() => {}); msg($('#m'), 'Doğrulama e-postası yeniden gönderildi', 'ok'); };
    } catch (e) { msg(m, esc(e.message)); busy(b, false, 'Hesap oluştur'); }
  };
}

function pageLogin() {
  document.title = `Giriş — ${SNAME}`;
  const durum = { 'dogrulama-gecersiz': ['Doğrulama bağlantısı geçersiz ya da süresi dolmuş. Giriş yapmayı deneyin ya da yeniden kayıt olun.', 'err'],
    askida: ['Hesabınız askıya alınmış.', 'err'], sifirlandi: ['Şifreniz değişti. Yeni şifrenizle giriş yapın.', 'ok'],
    cikis: ['Çıkış yaptınız.', 'info'] }[qs.get('durum')];
  view.innerHTML = `<h1>Giriş yapın</h1>
    <p class="muted small">Mastertool hesabınız SSH Master ve FTP Masters'ta aynıdır.</p>
    ${qs.get('sonra') ? '<div class="msg info">İndirme bağlantınız kişiye özeldir; devam etmek için giriş yapın.</div>' : ''}
    ${durum ? `<div class="msg ${durum[1]}">${durum[0]}</div>` : ''}
    <form id="f" autocomplete="on">
      <label for="e">E-posta</label><input id="e" type="email" autocomplete="username" required>
      <label for="p">Şifre</label><input id="p" type="password" autocomplete="current-password" required>
      <button class="btn primary block" id="b">Giriş yap</button>
      <div id="m"></div>
    </form>
    <div class="links"><a href="/sifremi-unuttum${AQ}">Şifremi unuttum</a><a href="/kayit${AQ}">Hesap oluştur</a></div>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#m'), b = $('#b'), email = $('#e').value.trim(), p = $('#p').value;
    busy(b, true, 'Giriş yap');
    try {
      const kdf = await prelogin(email);
      await api(`${API}/auth/login`, { method: 'POST', body: { email, auth_hash: await authHash(p, kdf), client: 'web' } });
      location.href = nextUrl();
    } catch (e) {
      msg(m, esc(e.message) + (e.code === 'unverified' ? ' <a href="#" id="rs">Doğrulama e-postasını yeniden gönder</a>' : ''));
      const rs = $('#rs');
      if (rs) rs.onclick = async x => { x.preventDefault(); await api(`${API}/auth/resend-verify`, { method: 'POST', body: { email, brand: BRAND } }).catch(() => {}); msg(m, 'Doğrulama e-postası yeniden gönderildi', 'ok'); };
      busy(b, false, 'Giriş yap');
    }
  };
}

function pageForgot() {
  document.title = `Şifremi unuttum — ${SNAME}`;
  view.innerHTML = `<h1>Şifremi unuttum</h1><p class="muted small">Kayıtlı e-posta adresinize şifre sıfırlama bağlantısı gönderelim.</p>
    <form id="f"><label for="e">E-posta</label><input id="e" type="email" autocomplete="email" required>
      <button class="btn primary block" id="b">Bağlantı gönder</button><div id="m"></div></form>
    <div class="links"><a href="/giris${AQ}">Girişe dön</a></div>`;
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const b = $('#b');
    busy(b, true, 'Bağlantı gönder');
    try {
      await api(`${API}/auth/forgot`, { method: 'POST', body: { email: $('#e').value.trim(), brand: BRAND } });
      msg($('#m'), 'Bu e-postayla kayıtlı bir hesap varsa sıfırlama bağlantısı gönderildi. Bağlantı 1 saat geçerlidir.', 'ok');
    } catch (e) { msg($('#m'), esc(e.message)); }
    busy(b, false, 'Bağlantı gönder');
  };
}

async function pageReset(tok) {
  document.title = `Yeni şifre — ${SNAME}`;
  let info;
  try { info = await api(`${API}/auth/reset/${encodeURIComponent(tok)}`); } catch (e) {
    view.innerHTML = `<h1>Bağlantı geçersiz</h1><p class="muted">${esc(e.message)}</p><div class="links"><a href="/sifremi-unuttum${AQ}">Yeni bağlantı iste</a></div>`;
    return;
  }
  view.innerHTML = `<h1>Yeni şifre belirleyin</h1><p class="muted small">${esc(info.email)}</p>
    <div class="msg info">Yeni şifre SSH Master ve FTP Masters için birlikte geçerli olur. Şifre değişince web'de saklanan şifreli
      kütüphaneleriniz silinir; uygulamalarda yeni şifrenizle giriş yaptığınızda bilgisayarınızdaki kayıtlar yeniden yüklenir.</div>
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
      await api(`${API}/auth/reset/${encodeURIComponent(tok)}`, { method: 'POST', body: { new_auth_hash: await authHash(p, info.kdf) } });
      location.href = '/giris?durum=sifirlandi';
    } catch (e) { msg(m, esc(e.message)); busy(b, false, 'Şifreyi kaydet'); }
  };
}

const fmtSize = n => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n || 0} B`);
const fmtDate = s => (s ? new Date(s).toLocaleString('tr-TR', { dateStyle: 'medium', timeStyle: 'short' }) : '—');
const TABS = [['uygulamalar', 'Uygulamalar'], ['cihazlar', 'Cihazlar'], ['guvenlik', 'Şifre'], ['destek', 'Destek']];
const TK_STATUS = { acik: ['Açık', 'warn'], yanit_bekliyor: ['Yanıtlandı', 'on'], cozuldu: ['Çözüldü', ''], kapali: ['Kapalı', ''] };
const TK_APPS = { sm: 'SSH Master', fm: 'FTP Masters', mt: 'Hesap / genel' };
let ACC = null;

async function pageAccount() {
  document.title = `Hesabım — ${SNAME}`;
  try { ACC = await api(`${API}/account`); } catch (e) {
    if (e.status === 401 || e.status === 403) { location.href = `/giris${AQ}`; return; }
    view.textContent = e.message; return;
  }
  $('#box').classList.add('wide');
  const tab = (location.hash || '').slice(1);
  const cur = TABS.some(t => t[0] === tab) ? tab : (qs.get('talep') ? 'destek' : 'uygulamalar');
  view.innerHTML = `<button class="btn sm top-right" id="out">Çıkış</button>
    <h1>Merhaba, ${esc(ACC.user.name)}</h1><p class="muted small">${esc(ACC.user.email)} · Mastertool hesabı</p>
    ${qs.get('durum') === 'dogrulandi' ? '<div class="msg ok">E-postanız doğrulandı, hesabınız açıldı.</div>' : ''}
    <div class="tabs">${TABS.map(([k, l]) => `<button type="button" data-tab="${k}" class="${k === cur ? 'on' : ''}">${l}</button>`).join('')}</div>
    <div id="pane"></div>`;
  $('#out').onclick = async () => { await api(`${API}/auth/logout`, { method: 'POST' }).catch(() => {}); location.href = `/giris${AQ}${AQ ? '&' : '?'}durum=cikis`; };
  view.querySelectorAll('[data-tab]').forEach(b => { b.onclick = () => { history.replaceState(null, '', `${location.pathname}${location.search}#${b.dataset.tab}`); show(b.dataset.tab); }; });
  show(cur);
}

function show(tab) {
  view.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  const pane = $('#pane');
  ({ uygulamalar: paneApps, cihazlar: paneDevices, guvenlik: panePassword, destek: paneSupport }[tab] || paneApps)(pane);
}

function paneApps(pane) {
  const order = [...ACC.apps].sort((a, b) => (b.app === BRAND) - (a.app === BRAND));
  pane.innerHTML = `<div class="apps">${order.map(x => {
    const r = x.release, off = x.license !== 'AKTIF';
    return `<div class="app-card ${off ? 'off' : ''}">
      <div class="head"><img src="/brand/${x.app}.png" alt=""><div class="grow"><b>${esc(x.name)}</b>
        <div class="muted small">${r ? `Sürüm ${esc(r.version)} · ${fmtSize(r.size)} · ${fmtDate(r.date)}` : 'İndirilebilir sürüm yakında'}</div></div>
        ${off ? '<span class="badge off">Hesabınızda kapalı</span>' : ''}</div>
      ${off ? '<p class="hint">Bu uygulamanın kullanımı hesabınız için kapatılmış. Bilgi için Destek sekmesinden talep açabilirsiniz.</p>' : `
      ${r ? `<div class="row"><a class="btn primary" href="${esc(x.download_url)}">İndir (Windows)</a>
        ${r.portable ? `<a class="btn" href="${esc(x.download_url)}?tur=portable">Taşınabilir sürüm</a>` : ''}</div>
        ${r.notes ? `<p class="muted small" style="white-space:pre-wrap">${esc(r.notes)}</p>` : ''}
        <p class="hint">SHA-256: <code>${esc(r.sha256)}</code> · Bu bağlantı size özeldir ve yalnız bu hesapla oturum açmışken çalışır.</p>` : ''}
      <div class="kv" style="margin-top:12px"><span>Senkronizasyon</span><span>${x.sync_enabled ? '<span class="badge on">Açık</span>' : '<span class="badge">Kapalı (uygulama ayarlarından)</span>'}</span>
        <span>Şifreli kopya</span><span>${x.library.version ? `${fmtSize(x.library.size)} · son eşitleme ${fmtDate(x.library.updated_at)}${x.library.device ? ` · ${esc(x.library.device)}` : ''}` : 'Henüz eşitleme yok'}</span></div>`}
    </div>`;
  }).join('')}</div>
  <p class="hint">Kayıtlarınız uçtan uca şifrelenir; anahtar yalnız sizin cihazlarınızda bulunur, sunucu içeriği okuyamaz.</p>`;
}

function paneDevices(pane) {
  const kind = s => (s.kind === 'web' ? 'Web' : (TK_APPS[s.app || 'sm'] || 'Uygulama'));
  pane.innerHTML = `<table><tr><th>Cihaz</th><th>Uygulama</th><th>Son görülme</th><th></th></tr>
    ${ACC.sessions.map(s => `<tr><td>${esc(s.device || (s.kind === 'web' ? 'Tarayıcı' : 'Uygulama'))}${s.app_version ? ` <span class="muted small">v${esc(s.app_version)}</span>` : ''}</td>
      <td>${kind(s)}</td><td>${fmtDate(s.last_seen)}</td>
      <td>${s.current ? '<span class="badge on">Bu oturum</span>' : `<button class="btn sm danger" data-sid="${s.id}">Kapat</button>`}</td></tr>`).join('')}</table>
    <p class="hint">Tanımadığınız bir cihaz görürseniz oturumu kapatın ve şifrenizi değiştirin.</p>`;
  pane.querySelectorAll('[data-sid]').forEach(b => { b.onclick = async () => {
    await api(`${API}/sessions/${b.dataset.sid}`, { method: 'DELETE' });
    ACC = await api(`${API}/account`); paneDevices(pane);
  }; });
}

function panePassword(pane) {
  pane.innerHTML = `<form id="pf"><label for="op">Mevcut şifre</label><input id="op" type="password" autocomplete="current-password" required>
      <label for="np">Yeni şifre</label><input id="np" type="password" autocomplete="new-password" required minlength="8">
      <label for="np2">Yeni şifre (tekrar)</label><input id="np2" type="password" autocomplete="new-password" required>
      <div class="hint">Yeni şifre SSH Master ve FTP Masters için birlikte geçerli olur. Şifre değişince web'deki şifreli kopyalar silinir ve diğer
        cihazlardaki oturumlar kapanır; uygulamalarda yeni şifreyle giriş yaptığınızda bilgisayarınızdaki kayıtlar yeniden yüklenir.</div>
      <button class="btn block" id="pb">Şifreyi değiştir</button><div id="pm"></div></form>`;
  $('#pf').onsubmit = async ev => {
    ev.preventDefault();
    const m = $('#pm'), b = $('#pb'), np = $('#np').value;
    if (!pwRules(np)) return msg(m, 'Yeni şifre en az 8 karakter olmalı');
    if (np !== $('#np2').value) return msg(m, 'Yeni şifreler aynı değil');
    busy(b, true, 'Şifreyi değiştir');
    try {
      const me = await api(`${API}/me`);
      const fresh = (await api(`${API}/auth/new-salt`, { method: 'POST' })).kdf;
      await api(`${API}/auth/change-password`, { method: 'POST', body: {
        old_auth_hash: await authHash($('#op').value, me.kdf), new_auth_hash: await authHash(np, fresh), new_salt: fresh.salt } });
      $('#pf').reset();
      msg(m, 'Şifreniz değişti. Uygulamalarda yeni şifrenizle giriş yapın.', 'ok');
    } catch (e) { msg(m, esc(e.message)); }
    busy(b, false, 'Şifreyi değiştir');
  };
}

const tkBadge = st => { const [l, c] = TK_STATUS[st] || [st, '']; return `<span class="badge ${c}">${esc(l)}</span>`; };

async function paneSupport(pane, openId) {
  openId = openId ?? (qs.get('talep') ? Number(qs.get('talep')) : null);
  if (openId) return ticketView(pane, openId);
  pane.innerHTML = '<p class="muted">Yükleniyor…</p>';
  let rows;
  try { rows = await api(`${API}/tickets`); } catch (e) { pane.innerHTML = `<div class="msg err">${esc(e.message)}</div>`; return; }
  pane.innerHTML = `<div style="display:flex;align-items:center;gap:10px"><h2 style="margin:8px 0;flex:1">Destek talepleri</h2>
      <button class="btn sm" id="nt">Yeni talep</button></div>
    <div id="nf"></div>
    ${rows.length ? rows.map(t => `<div class="tk" data-id="${t.id}">${t.unread ? '<span class="dot" title="Yeni yanıt"></span>' : ''}
        <div class="grow"><b>${esc(t.subject)}</b><div class="muted small">${esc(t.code)} · ${esc(TK_APPS[t.app] || '')} · ${fmtDate(t.updated_at)}</div></div>
        ${tkBadge(t.status)}</div>`).join('') : '<p class="muted">Henüz destek talebiniz yok.</p>'}`;
  pane.querySelectorAll('[data-id]').forEach(el => { el.onclick = () => ticketView(pane, Number(el.dataset.id)); });
  $('#nt').onclick = () => newTicket($('#nf'), pane);
  if (!rows.length) newTicket($('#nf'), pane);
}

function newTicket(box, pane) {
  const def = BRAND in TK_APPS ? BRAND : 'mt';
  box.innerHTML = `<form id="tf" class="app-card" style="margin:10px 0">
      <label for="ta">Uygulama</label><select id="ta">${Object.entries(TK_APPS).map(([k, l]) => `<option value="${k}" ${k === def ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <label for="tc">Konu türü</label><select id="tc"><option value="teknik">Teknik sorun</option><option value="oneri">Öneri</option><option value="diger">Diğer</option></select>
      <label for="ts">Konu</label><input id="ts" maxlength="200" required>
      <label for="tb">Açıklama</label><textarea id="tb" maxlength="8000" required placeholder="Ne oldu? Hangi sürümü kullanıyorsunuz? Hata iletisi varsa ekleyin."></textarea>
      <button class="btn primary block" id="tsb">Talebi gönder</button><div id="tm"></div></form>`;
  $('#tf').onsubmit = async ev => {
    ev.preventDefault();
    const b = $('#tsb');
    busy(b, true, 'Talebi gönder');
    try {
      const r = await api(`${API}/tickets`, { method: 'POST', body: { app: $('#ta').value, category: $('#tc').value, subject: $('#ts').value.trim(), body: $('#tb').value.trim() } });
      ticketView(pane, r.id);
    } catch (e) { msg($('#tm'), esc(e.message)); busy(b, false, 'Talebi gönder'); }
  };
}

async function ticketView(pane, id) {
  pane.innerHTML = '<p class="muted">Yükleniyor…</p>';
  let t;
  try { t = await api(`${API}/tickets/${id}`); } catch (e) {
    pane.innerHTML = `<div class="msg err">${esc(e.message)}</div><div class="links"><a href="#destek" id="bk">← Taleplerim</a></div>`;
    $('#bk').onclick = ev => { ev.preventDefault(); history.replaceState(null, '', `${location.pathname}#destek`); paneSupport(pane, 0); };
    return;
  }
  const closed = ['cozuldu', 'kapali'].includes(t.status);
  pane.innerHTML = `<div class="links" style="margin-top:4px"><a href="#destek" id="bk">← Taleplerim</a></div>
    <h2 style="margin-top:10px">${esc(t.subject)}</h2>
    <div class="muted small">${esc(t.code)} · ${esc(TK_APPS[t.app] || '')} · ${fmtDate(t.created_at)} ${tkBadge(t.status)}</div>
    <div class="thread">${t.messages.map(m => m.author_kind === 'system'
      ? `<div class="bubble sys">${esc(m.body)} · ${fmtDate(m.created_at)}</div>`
      : `<div class="bubble ${m.author_kind === 'company' ? 'me' : ''}"><div class="who">${m.author_kind === 'company' ? 'Siz' : esc(m.author_name || 'Destek')} · ${fmtDate(m.created_at)}</div>${esc(m.body)}</div>`).join('')}</div>
    <form id="rf"><label for="rb">${closed ? 'Yanıt yazarsanız talep yeniden açılır' : 'Yanıtınız'}</label><textarea id="rb" maxlength="8000" required></textarea>
      <div class="row" style="display:flex;gap:10px;margin-top:12px"><button class="btn primary" id="rsb">Gönder</button>
      ${closed ? '' : '<button class="btn" type="button" id="cl">Sorunum çözüldü, kapat</button>'}</div><div id="rm"></div></form>`;
  $('#bk').onclick = ev => { ev.preventDefault(); history.replaceState(null, '', `${location.pathname}#destek`); paneSupport(pane, 0); };
  $('#rf').onsubmit = async ev => {
    ev.preventDefault();
    const b = $('#rsb');
    busy(b, true, 'Gönder');
    try { await api(`${API}/tickets/${id}/messages`, { method: 'POST', body: { body: $('#rb').value.trim() } }); ticketView(pane, id); }
    catch (e) { msg($('#rm'), esc(e.message)); busy(b, false, 'Gönder'); }
  };
  const cl = $('#cl');
  if (cl) cl.onclick = async () => { try { await api(`${API}/tickets/${id}/close`, { method: 'POST' }); ticketView(pane, id); } catch (e) { msg($('#rm'), esc(e.message)); } };
}

const p = location.pathname.replace(/\/+$/, '');
if (p === '/kayit') pageRegister();
else if (p === '/giris') pageLogin();
else if (p === '/sifremi-unuttum') pageForgot();
else if (p.startsWith('/sifre-sifirla/')) pageReset(decodeURIComponent(p.slice('/sifre-sifirla/'.length)));
else pageAccount();
