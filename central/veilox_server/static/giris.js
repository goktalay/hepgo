// HEPGO › Firma girişi: firmanın kendi paneline girişi (firma adresiyle; adresini hatırlamayan yönetici kayıt e-postası ve
// şifresiyle bulur, başvuru durumunu görür) ve yeni firma kaydı (paket → firma → yönetici hesabı → başvuru özeti).
// Merkez (yönetim) girişi burada YOKTUR; yalnızca veilox.app alan adındadır. CSP: satır içi stil yok.
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const svg = d => `<svg viewBox="0 0 24 24">${d}</svg>`;
const nf = new Intl.NumberFormat('tr-TR');
let lang = (() => { try { return localStorage.getItem('veilox.lang') === 'en' ? 'en' : 'tr'; } catch { return 'tr'; } })();
let theme = (() => { try { return localStorage.getItem('veilox.theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); } catch { return 'light'; } })();
let base = 'hepgo.com';

const T = {
  tr: {
    back: 'Tanıtım sayfası', title: 'Firma girişi', tabLogin: 'Panelime gir', tabReg: 'Yeni firma kaydı',
    sideH: 'Firmanızın tamamı tek panelde', sideP: 'Üretimden sahaya, finanstan insan kaynaklarına; ekibiniz kendi rolüyle girer, siz her şeyi tek yerden yönetirsiniz.',
    sideList: ['Firmanıza özel adres ve kullanıcılar', 'Destek ekibimize canlı destek ve ekran paylaşımı', 'Üyelik, ödeme ve sözleşmeleriniz panelinizde', 'Verileriniz yalnızca sizin — merkez göremez'],
    loginH: 'Firmanızın paneline girin', loginP: 'Firma adresinizi yazın; sizi firmanızın giriş ekranına yönlendirelim.',
    addr: 'Firma adresi', addrPh: 'firmaniz', go: 'Devam', recent: 'Son kullandığınız', forgot: 'Firma adresimi hatırlamıyorum',
    findH: 'Firmanızı bulun', findP: 'Firmayı kaydederken kullandığınız yönetici e-postası ve şifresiyle firmanızı ve başvuru durumunuzu görün.',
    email: 'Yönetici e-postası', pass: 'Şifre', find: 'Firmamı bul', toPanel: 'Panele git', noAcc: 'Henüz firmanız yok mu?', regNow: 'Ücretsiz başvurun',
    steps: ['Paket', 'Firma', 'Yönetici', 'Tamam'], pickPkg: 'Paketinizi seçin', pickPkgP: 'Açık beta döneminde tüm paketler ücretsiz; firmanız tüm modüllere erişir. Daha sonra değiştirebilirsiniz.', noPkg: 'Paket seçmeden devam et',
    perMonth: '/ay', free: 'Ücretsiz', beta: 'Açık beta', mods: n => `${n} modül`, cloud: 'Bulut', onprem: 'Kendi sunucunuz', both: 'Bulut / kendi sunucunuz',
    firmH: 'Firma bilgileri', cname: 'Firma adı', cnamePh: 'ör. Örnek Makine A.Ş.', yourAddr: 'Firma adresiniz', city: 'Şehir', tax: 'Vergi no (isteğe bağlı)', phone: 'Telefon',
    addrHint: 'Giriş adresiniz bu olur. Değiştirebilirsiniz; yalnız küçük harf, rakam ve tire.', addrCheck: 'Kontrol ediliyor…', addrOk: 'Uygun ✓',
    countryL: 'Ülke', logoL: 'Logo (isteğe bağlı)', logoHint: 'PNG, JPG, WEBP veya GIF · en fazla 2 MB', logoPick: 'Logo seç', logoChange: 'Logoyu değiştir', logoRemove: 'Kaldır',
    logoTooBig: 'Logo en fazla 2 MB olmalı.', logoBadType: 'PNG, JPG, WEBP veya GIF seçin.', addrNeeded: 'Lütfen uygun bir firma adresi girin.',
    adminH: 'Yönetici hesabı', adminP: 'Bu hesap firmanızın sahibi (master) olur; kullanıcıları ve yetkileri o yönetir.',
    full: 'Ad soyad', mail: 'E-posta', pw: 'Şifre (en az 10 karakter)', pw2: 'Şifre tekrar',
    sendCode: 'Doğrulama kodu gönder', codeSending: 'Gönderiliyor…', codeL: 'E-posta doğrulama kodu', codeHint: 'E-postanıza gönderilen 6 haneli kodu girin.',
    codeSent: e => `${e} adresine kod gönderildi.`, resend: 'Tekrar gönder', codeNeed: 'Lütfen e-posta doğrulama kodunu girin.', badEmail: 'Geçerli bir e-posta girin.',
    accept: 'Başvurumun değerlendirilmesi ve benimle iletişime geçilmesi için bilgilerimin kaydedilmesini kabul ediyorum.',
    next: 'Devam', prev: 'Geri', submit: 'Başvuruyu tamamla',
    okH: 'Başvurunuz alındı', okP: 'Ekibimiz başvurunuzu inceleyip firmanızı kuracak. Kurulum tamamlanınca giriş adresiniz e-postanıza iletilecek.',
    appNo: 'Başvuru no', timeline: ['Başvuru alındı', 'İnceleme', 'Firma kurulumu', 'Giriş bilgileri e-postanıza'],
    pwWeak: 'Zayıf', pwOk: 'Orta', pwStrong: 'Güçlü', mismatch: 'Şifreler aynı değil', required: 'Bu alanı doldurun',
    pending: 'Başvuru inceleniyor', offline: 'Kendi sunucunuzda', unavailable: 'Kullanılamıyor', created: 'Başvuru',
  },
  en: {
    back: 'Home', title: 'Company sign-in', tabLogin: 'Sign in', tabReg: 'Register a company',
    sideH: 'Your whole company on one panel', sideP: 'From production to the field, finance to HR; your team signs in with their own role while you run everything from one place.',
    sideList: ['Your own address and users', 'Live support and screen sharing with our team', 'Membership, payments and contracts in your panel', 'Your data is yours — the console cannot see it'],
    loginH: 'Sign in to your company', loginP: 'Enter your company address and we will take you to its sign-in screen.',
    addr: 'Company address', addrPh: 'yourcompany', go: 'Continue', recent: 'Recently used', forgot: 'I don’t remember my company address',
    findH: 'Find your company', findP: 'Use the admin email and password you registered with to see your company and application status.',
    email: 'Admin email', pass: 'Password', find: 'Find my company', toPanel: 'Go to panel', noAcc: 'No company yet?', regNow: 'Apply for free',
    steps: ['Plan', 'Company', 'Admin', 'Done'], pickPkg: 'Choose your plan', pickPkgP: 'All plans are free during open beta; your company gets every module. You can change it later.', noPkg: 'Continue without a plan',
    perMonth: '/mo', free: 'Free', beta: 'Open beta', mods: n => `${n} modules`, cloud: 'Cloud', onprem: 'On-premise', both: 'Cloud / on-premise',
    firmH: 'Company details', cname: 'Company name', cnamePh: 'e.g. Acme Machinery Ltd.', yourAddr: 'Your company address', city: 'City', tax: 'Tax no (optional)', phone: 'Phone',
    addrHint: 'This becomes your sign-in address. You can change it; lowercase letters, digits and hyphens only.', addrCheck: 'Checking…', addrOk: 'Available ✓',
    countryL: 'Country', logoL: 'Logo (optional)', logoHint: 'PNG, JPG, WEBP or GIF · max 2 MB', logoPick: 'Choose logo', logoChange: 'Change logo', logoRemove: 'Remove',
    logoTooBig: 'Logo must be at most 2 MB.', logoBadType: 'Choose a PNG, JPG, WEBP or GIF.', addrNeeded: 'Please enter an available company address.',
    adminH: 'Admin account', adminP: 'This account becomes your company owner (master) and manages users and permissions.',
    full: 'Full name', mail: 'Email', pw: 'Password (min 10 characters)', pw2: 'Repeat password',
    sendCode: 'Send verification code', codeSending: 'Sending…', codeL: 'Email verification code', codeHint: 'Enter the 6-digit code sent to your email.',
    codeSent: e => `Code sent to ${e}.`, resend: 'Resend', codeNeed: 'Please enter the email verification code.', badEmail: 'Enter a valid email.',
    accept: 'I agree that my details are stored to evaluate my application and to contact me.',
    next: 'Continue', prev: 'Back', submit: 'Complete application',
    okH: 'Application received', okP: 'Our team will review your application and set up your company. Your sign-in address will be emailed when ready.',
    appNo: 'Application no', timeline: ['Application received', 'Review', 'Company setup', 'Credentials by email'],
    pwWeak: 'Weak', pwOk: 'Fair', pwStrong: 'Strong', mismatch: 'Passwords do not match', required: 'Please fill this in',
    pending: 'Under review', offline: 'On-premise', unavailable: 'Unavailable', created: 'Applied',
  },
};
const t = () => T[lang];
const qs = new URLSearchParams(location.search);
const state = { tab: location.hash === '#kayit' ? 'reg' : 'login', step: 0, pkg: qs.get('paket') || '', pkgs: [], form: {}, result: null, emailVerify: false, codeSentOnce: false };
const recent = () => { try { return JSON.parse(localStorage.getItem('hepgo.firms') || '[]'); } catch { return []; } };
const remember = (addr, url) => { try { localStorage.setItem('hepgo.firms', JSON.stringify([{ addr, url }, ...recent().filter(r => r.url !== url)].slice(0, 4))); } catch { /* */ } };
const post = async (url, body) => {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => null);
  if (!r.ok) throw new Error(d?.detail || 'Hata');
  return d;
};

function shell() {
  const L = t();
  const sun = svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/>');
  const moon = svg('<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>');
  return `<header class="nav scrolled"><div class="wrap nav-in">
      <a class="brand" href="/"><img src="/static/img/hepgo-mark.png" alt="" class="brand-logo"><span class="brand-txt"><b>HEPGO</b><span>ERP</span></span></a>
      <div class="nav-ctl gx-navctl"><a class="btn btn-ghost" href="/">← ${esc(L.back)}</a>
        <button class="icon-btn" id="langBtn" title="Dil / Language">${lang === 'tr' ? 'EN' : 'TR'}</button>
        <button class="icon-btn" id="themeBtn" title="Tema">${theme === 'dark' ? sun : moon}</button></div>
    </div></header>
    <main class="gx-main"><div class="wrap gx-grid">
      <aside class="gx-side"><div class="gx-side-in">
        <span class="pill"><i></i> HEPGO ERP</span>
        <h1>${esc(L.sideH)}</h1><p>${esc(L.sideP)}</p>
        <ul class="gx-ticks">${L.sideList.map(x => `<li>${svg('<path d="M5 12l4 4 10-10"/>')}<span>${esc(x)}</span></li>`).join('')}</ul>
        <div class="gx-shot"><img class="shot" src="/static/img/landing/shots/dashboard.webp" alt=""></div>
      </div></aside>
      <section class="gx-card">
        <div class="gx-tabs" role="tablist">
          <button type="button" data-tab="login" class="${state.tab === 'login' ? 'on' : ''}">${esc(L.tabLogin)}</button>
          <button type="button" data-tab="reg" class="${state.tab === 'reg' ? 'on' : ''}">${esc(L.tabReg)}</button>
        </div>
        <div id="gxBody"></div>
      </section>
    </div></main>
    <footer class="foot"><div class="wrap foot-in"><div class="foot-brand"><img src="/static/img/hepgo-mark.png" alt=""><span>HEPGO</span></div>
      <div class="foot-meta">© ${new Date().getFullYear()} · HEPGO ERP</div></div></footer>`;
}

// ---------------- Panelime gir ----------------
function loginView() {
  const L = t();
  const rec = recent();
  $('#gxBody').innerHTML = `<div class="gx-pane">
    <h2>${esc(L.loginH)}</h2><p class="gx-sub">${esc(L.loginP)}</p>
    <form id="lookForm" class="gx-form" autocomplete="on">
      <label class="vx-field"><span>${esc(L.addr)}</span>
        <div class="gx-addr"><input class="vx-input" name="addr" autocomplete="organization" placeholder="${esc(L.addrPh)}" required autofocus><b>.${esc(base)}</b></div></label>
      <div class="vx-err" id="lookErr"></div>
      <div class="gx-msg" id="lookMsg" hidden></div>
      <button class="btn btn-primary btn-lg gx-full" type="submit">${esc(L.go)} →</button>
    </form>
    ${rec.length ? `<div class="gx-recent"><small>${esc(L.recent)}</small>${rec.map((r, i) => `<a class="gx-rec" href="${esc(r.url)}" data-i="${i}">${svg('<path d="M4 20V5l8-2v17M12 8h8v12M3 20h18"/>')}<span>${esc(r.addr)}</span><i>→</i></a>`).join('')}</div>` : ''}
    <button type="button" class="gx-link" id="forgotBtn">${esc(L.forgot)}</button>
    <form id="findForm" class="gx-form gx-find" hidden>
      <h3>${esc(L.findH)}</h3><p class="gx-sub">${esc(L.findP)}</p>
      <label class="vx-field"><span>${esc(L.email)}</span><input class="vx-input" type="email" name="email" autocomplete="username" required></label>
      <label class="vx-field"><span>${esc(L.pass)}</span><input class="vx-input" type="password" name="pass" autocomplete="current-password" required></label>
      <div class="vx-err" id="findErr"></div>
      <button class="btn btn-ghost gx-full" type="submit">${esc(L.find)}</button>
      <div id="findOut"></div>
    </form>
    <p class="gx-alt">${esc(L.noAcc)} <button type="button" class="gx-link" data-tab="reg">${esc(L.regNow)} →</button></p>
  </div>`;
  const form = $('#lookForm'), err = $('#lookErr'), msg = $('#lookMsg');
  form.addEventListener('submit', async e => {
    e.preventDefault(); err.textContent = ''; msg.hidden = true;
    const btn = form.querySelector('button[type=submit]'); btn.disabled = true;
    const addr = form.addr.value.trim();
    try {
      const r = await post('/api/public/firm-lookup', { address: addr });
      if (r.status === 'active') { remember(addr.includes('.') ? addr : `${addr}.${base}`, r.url); location.href = r.url; return; }
      msg.textContent = r.message; msg.className = `gx-msg ${r.status}`; msg.hidden = false;
    } catch (ex) { err.textContent = ex.message; }
    btn.disabled = false;
  });
  $('#forgotBtn').addEventListener('click', () => { const f = $('#findForm'); f.hidden = !f.hidden; if (!f.hidden) f.email.focus(); });
  const find = $('#findForm');
  find.addEventListener('submit', async e => {
    e.preventDefault(); $('#findErr').textContent = '';
    const btn = find.querySelector('button[type=submit]'); btn.disabled = true;
    try {
      const r = await post('/api/public/firm-find', { email: find.email.value, password: find.pass.value });
      $('#findOut').innerHTML = `<div class="gx-firms">${r.firms.map(f => `<div class="gx-firm ${f.status}">
        <div><b>${esc(f.name)}</b><small>${esc({ active: f.url?.replace(/^https?:\/\//, '').replace(/\/app$/, ''), pending: L.pending, offline: L.offline, unavailable: L.unavailable }[f.status] || '')} · ${esc(L.created)} ${esc((f.created_at || '').slice(0, 10))}</small>
          ${f.message ? `<p>${esc(f.message)}</p>` : ''}</div>
        ${f.status === 'active' ? `<a class="btn btn-primary" href="${esc(f.url)}">${esc(L.toPanel)} →</a>` : `<span class="gx-badge ${f.status}">${esc(L[f.status] || f.status)}</span>`}</div>`).join('')}</div>`;
    } catch (ex) { $('#findErr').textContent = ex.message; }
    btn.disabled = false;
  });
}

// ---------------- Yeni firma kaydı ----------------
function stepsBar() {
  const L = t();
  return `<ol class="gx-steps">${L.steps.map((s, i) => `<li class="${i < state.step ? 'done' : i === state.step ? 'on' : ''}"><span>${i < state.step ? '✓' : i + 1}</span>${esc(s)}</li>`).join('')}</ol>`;
}

// Ülkeler (bayrak emoji 2-harf koddan). Türkiye ilk; sonra yaygın ülkeler.
const COUNTRIES = [['TR', 'Türkiye'], ['DE', 'Almanya'], ['US', 'ABD'], ['GB', 'Birleşik Krallık'], ['FR', 'Fransa'], ['NL', 'Hollanda'], ['IT', 'İtalya'], ['ES', 'İspanya'], ['AZ', 'Azerbaycan'], ['SA', 'Suudi Arabistan'], ['AE', 'BAE'], ['QA', 'Katar'], ['RU', 'Rusya'], ['UA', 'Ukrayna'], ['CN', 'Çin'], ['IN', 'Hindistan'], ['JP', 'Japonya'], ['KR', 'Güney Kore'], ['BR', 'Brezilya'], ['CA', 'Kanada'], ['AU', 'Avustralya'], ['EG', 'Mısır'], ['GR', 'Yunanistan'], ['BG', 'Bulgaristan'], ['RO', 'Romanya'], ['PL', 'Polonya'], ['SE', 'İsveç'], ['CH', 'İsviçre'], ['BE', 'Belçika'], ['AT', 'Avusturya']];
const cflag = cc => (cc && cc.length === 2) ? String.fromCodePoint(...[...cc.toUpperCase()].map(c => 127397 + c.charCodeAt(0))) : '';

function regView() {
  const L = t();
  const body = $('#gxBody');
  if (state.step === 0) {
    body.innerHTML = `<div class="gx-pane">${stepsBar()}<h2>${esc(L.pickPkg)}</h2><p class="gx-sub">${esc(L.pickPkgP)}</p>
      <div class="gx-pkgs">${state.pkgs.map(p => `<button type="button" class="gx-pkg ${p.slug === state.pkg ? 'on' : ''}" data-pkg="${esc(p.slug)}">
        <b>${esc(p.name)}</b><span class="gx-fee">${p.open_beta ? esc(L.beta) : (p.monthly_fee ? `${nf.format(p.monthly_fee)} ₺<small>${esc(L.perMonth)}</small>` : esc(L.free))}</span>
        <small>${esc({ online: L.cloud, offline: L.onprem, both: L.both }[p.mode] || '')} · ${esc(L.mods(p.modules.length))}</small>
        ${p.description ? `<p>${esc(p.description)}</p>` : ''}</button>`).join('') || '<p class="gx-sub">…</p>'}</div>
      <div class="gx-acts"><button type="button" class="gx-link" id="noPkg">${esc(L.noPkg)}</button><button type="button" class="btn btn-primary btn-lg" id="next0">${esc(L.next)} →</button></div></div>`;
    body.querySelectorAll('[data-pkg]').forEach(b => b.addEventListener('click', () => { state.pkg = b.dataset.pkg; regView(); }));
    $('#noPkg').addEventListener('click', () => { state.pkg = ''; state.step = 1; regView(); });
    $('#next0').addEventListener('click', () => { state.step = 1; regView(); });
    return;
  }
  if (state.step === 1) {
    const f = state.form;
    body.innerHTML = `<div class="gx-pane">${stepsBar()}<h2>${esc(L.firmH)}</h2>
      <form id="f1" class="gx-form">
        <label class="vx-field"><span>${esc(L.cname)}</span><input class="vx-input" name="company" value="${esc(f.company || '')}" placeholder="${esc(L.cnamePh)}" required autofocus></label>
        <label class="vx-field"><span>${esc(L.yourAddr)}</span>
          <div class="gx-slug"><input class="vx-input" name="slug" value="${esc(f.slug || '')}" autocapitalize="none" spellcheck="false" placeholder="firmaniz"><span class="gx-slug-suf">.${esc(base)}</span></div>
          <small class="gx-slug-msg muted" id="slugMsg">${esc(L.addrHint)}</small></label>
        <div class="gx-row">
          <label class="vx-field"><span>${esc(L.countryL)}</span>
            <select class="vx-input" name="country">${COUNTRIES.map(([cc, nm]) => `<option value="${cc}"${(f.country || 'TR') === cc ? ' selected' : ''}>${cflag(cc)} ${esc(nm)}</option>`).join('')}</select></label>
          <label class="vx-field"><span>${esc(L.city)}</span><input class="vx-input" name="city" value="${esc(f.city || '')}"></label>
        </div>
        <div class="gx-row">
          <label class="vx-field"><span>${esc(L.phone)}</span><input class="vx-input" type="tel" name="phone" value="${esc(f.phone || '')}" placeholder="05xx xxx xx xx" required></label>
          <label class="vx-field"><span>${esc(L.tax)}</span><input class="vx-input" name="tax" value="${esc(f.tax || '')}" inputmode="numeric"></label>
        </div>
        <div class="vx-field"><span>${esc(L.logoL)}</span>
          <div class="gx-logo">
            <div class="gx-logo-prev" id="logoPrev">${f.logo ? `<img src="${f.logo}" alt="">` : ''}</div>
            <div class="gx-logo-ctl">
              <input type="file" id="logoInput" accept="image/png,image/jpeg,image/webp,image/gif" hidden>
              <button type="button" class="btn btn-ghost" id="logoBtn">${f.logo ? esc(L.logoChange) : esc(L.logoPick)}</button>
              <button type="button" class="btn btn-ghost" id="logoDel"${f.logo ? '' : ' hidden'}>${esc(L.logoRemove)}</button>
              <div class="small muted">${esc(L.logoHint)}</div>
            </div>
          </div>
        </div>
        <div class="vx-err" id="f1err"></div>
        <div class="gx-acts"><button type="button" class="btn btn-ghost" id="prev">← ${esc(L.prev)}</button><button class="btn btn-primary btn-lg" type="submit">${esc(L.next)} →</button></div>
      </form></div>`;
    const form = $('#f1');
    const err = $('#f1err'), slugMsg = $('#slugMsg');
    let slugEdited = !!f.slug, tm;
    // Firma adresi (slug) canlı kontrol
    const checkSlug = () => { clearTimeout(tm); tm = setTimeout(async () => {
      const v = form.slug.value.trim();
      if (!v) { slugMsg.textContent = L.addrHint; slugMsg.className = 'gx-slug-msg muted'; state.form.slug = ''; state.form.slugOk = false; return; }
      slugMsg.textContent = L.addrCheck; slugMsg.className = 'gx-slug-msg muted';
      try {
        const r = await (await fetch(`/api/public/slug-check?slug=${encodeURIComponent(v)}`)).json();
        state.form.slug = r.slug || v; state.form.slugOk = !!r.ok;
        slugMsg.textContent = r.ok ? `${r.domain} · ${L.addrOk}` : (r.reason || '');
        slugMsg.className = r.ok ? 'gx-slug-msg ok' : 'gx-slug-msg err';
      } catch { slugMsg.textContent = ''; }
    }, 300); };
    // Firma adından slug öner (kullanıcı adresi elle değiştirmediyse)
    const fromName = () => { clearTimeout(tm); tm = setTimeout(async () => {
      if (slugEdited) return;
      const n = form.company.value.trim();
      if (!n) { form.slug.value = ''; slugMsg.textContent = L.addrHint; slugMsg.className = 'gx-slug-msg muted'; state.form.slugOk = false; return; }
      try { const r = await (await fetch(`/api/public/slug-preview?name=${encodeURIComponent(n)}`)).json(); form.slug.value = r.slug; checkSlug(); } catch { /* */ }
    }, 300); };
    form.company.addEventListener('input', fromName);
    form.slug.addEventListener('input', () => { slugEdited = true; checkSlug(); });
    if (form.slug.value.trim()) checkSlug(); else if (form.company.value.trim()) fromName();
    // Logo (kurallı)
    const paintLogo = () => {
      $('#logoPrev').innerHTML = state.form.logo ? `<img src="${state.form.logo}" alt="">` : '';
      $('#logoBtn').textContent = state.form.logo ? L.logoChange : L.logoPick;
      $('#logoDel').hidden = !state.form.logo;
    };
    const logoInput = $('#logoInput');
    $('#logoBtn').addEventListener('click', () => logoInput.click());
    $('#logoDel').addEventListener('click', () => { state.form.logo = ''; logoInput.value = ''; paintLogo(); });
    logoInput.addEventListener('change', () => {
      const file = logoInput.files[0]; if (!file) return;
      err.textContent = '';
      if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) { err.textContent = L.logoBadType; logoInput.value = ''; return; }
      if (file.size > 2 * 1024 * 1024) { err.textContent = L.logoTooBig; logoInput.value = ''; return; }
      const rd = new FileReader();
      rd.onload = () => { state.form.logo = rd.result; paintLogo(); };
      rd.readAsDataURL(file);
    });
    $('#prev').addEventListener('click', () => { state.step = 0; regView(); });
    form.addEventListener('submit', e => {
      e.preventDefault(); err.textContent = '';
      if (!state.form.slugOk) { err.textContent = L.addrNeeded; form.slug.focus(); return; }
      Object.assign(state.form, { company: form.company.value.trim(), city: form.city.value.trim(), phone: form.phone.value.trim(), tax: form.tax.value.trim(), country: form.country.value });
      state.step = 2; regView();
    });
    return;
  }
  if (state.step === 2) {
    const f = state.form;
    body.innerHTML = `<div class="gx-pane">${stepsBar()}<h2>${esc(L.adminH)}</h2><p class="gx-sub">${esc(L.adminP)}</p>
      <form id="f2" class="gx-form">
        <label class="vx-field"><span>${esc(L.full)}</span><input class="vx-input" name="full" value="${esc(f.full || '')}" autocomplete="name" required autofocus></label>
        <label class="vx-field"><span>${esc(L.mail)}</span><input class="vx-input" type="email" name="email" value="${esc(f.email || '')}" autocomplete="email" required></label>
        ${state.emailVerify ? `<div class="gx-verify">
          <button type="button" class="btn btn-ghost" id="sendCode">${esc(L.sendCode)}</button>
          <label class="vx-field gx-code" id="codeWrap" hidden><span>${esc(L.codeL)}</span>
            <input class="vx-input" name="code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="______">
            <small class="muted" id="codeMsg">${esc(L.codeHint)}</small></label>
        </div>` : ''}
        <div class="gx-row"><label class="vx-field"><span>${esc(L.pw)}</span><input class="vx-input" type="password" name="pw" minlength="10" autocomplete="new-password" required></label>
          <label class="vx-field"><span>${esc(L.pw2)}</span><input class="vx-input" type="password" name="pw2" minlength="10" autocomplete="new-password" required></label></div>
        <div class="gx-meter"><i id="pwBar"></i><small id="pwTxt"></small></div>
        <label class="gx-check"><input type="checkbox" name="accept" required><span>${esc(L.accept)}</span></label>
        <div class="vx-err" id="regErr"></div>
        <div class="gx-acts"><button type="button" class="btn btn-ghost" id="prev">← ${esc(L.prev)}</button><button class="btn btn-primary btn-lg" type="submit">${esc(L.submit)}</button></div>
      </form></div>`;
    const form = $('#f2');
    const err = $('#regErr');
    const meter = () => {
      const v = form.pw.value;
      const sc = [v.length >= 10, /[a-zçğıöşü]/.test(v) && /[A-ZÇĞİÖŞÜ]/.test(v), /\d/.test(v), /[^\wçğıöşüÇĞİÖŞÜ]/.test(v), v.length >= 14].filter(Boolean).length;
      const bar = $('#pwBar');
      bar.className = sc <= 2 ? 'weak' : sc <= 3 ? 'ok' : 'strong';
      bar.style.width = `${Math.min(100, sc * 20)}%`;   // CSSOM (CSP'de satır içi stil değil)
      $('#pwTxt').textContent = v ? (sc <= 2 ? L.pwWeak : sc <= 3 ? L.pwOk : L.pwStrong) : '';
    };
    form.pw.addEventListener('input', meter);
    $('#prev').addEventListener('click', () => { state.form.full = form.full.value; state.form.email = form.email.value; state.step = 1; regView(); });
    // E-posta doğrulama kodu gönderimi (SMTP yapılandırıldıysa)
    if (state.emailVerify) {
      const sendBtn = $('#sendCode'), codeWrap = $('#codeWrap'), codeMsg = $('#codeMsg');
      let cd = 0, timer = null;
      const tick = () => { if (cd > 0) { sendBtn.textContent = `${L.resend} (${cd})`; sendBtn.disabled = true; cd--; } else { sendBtn.textContent = state.codeSentOnce ? L.resend : L.sendCode; sendBtn.disabled = false; if (timer) { clearInterval(timer); timer = null; } } };
      sendBtn.addEventListener('click', async () => {
        const email = form.email.value.trim();
        if (!/.+@.+\..+/.test(email)) { err.textContent = L.badEmail; form.email.focus(); return; }
        err.textContent = ''; sendBtn.disabled = true; sendBtn.textContent = L.codeSending;
        try {
          const r = await post('/api/register/send-code', { email });
          state.codeSentOnce = true; codeWrap.hidden = false; codeMsg.textContent = L.codeSent(r.sent_to || email);
          form.code.focus(); cd = 60; if (timer) clearInterval(timer); tick(); timer = setInterval(tick, 1000);
        } catch (ex) { err.textContent = ex.message; sendBtn.disabled = false; sendBtn.textContent = state.codeSentOnce ? L.resend : L.sendCode; }
      });
    }
    form.addEventListener('submit', async e => {
      e.preventDefault();
      err.textContent = '';
      if (form.pw.value !== form.pw2.value) { err.textContent = L.mismatch; return; }
      const code = (state.emailVerify && form.code) ? form.code.value.trim() : '';
      if (state.emailVerify && !code) { err.textContent = L.codeNeed; if (form.code) form.code.focus(); return; }
      const btn = form.querySelector('button[type=submit]'); btn.disabled = true;
      Object.assign(state.form, { full: form.full.value.trim(), email: form.email.value.trim() });
      try {
        state.result = await post('/api/register', { company_name: state.form.company, master_username: state.form.email, master_name: state.form.full, password: form.pw.value,
          package_slug: state.pkg, phone: state.form.phone, tax_no: state.form.tax, city: state.form.city, accept: form.accept.checked, email_code: code,
          slug: state.form.slug || '', country: state.form.country || '', logo: state.form.logo || '' });
        state.step = 3; regView();
      } catch (ex) { err.textContent = ex.message; btn.disabled = false; }
    });
    return;
  }
  const r = state.result || {};
  body.innerHTML = `<div class="gx-pane gx-done">${stepsBar()}
    <div class="gx-ok">${svg('<path d="M5 12l4 4 10-10"/>')}</div>
    <h2>${esc(L.okH)}</h2><p class="gx-sub">${esc(L.okP)}</p>
    <dl class="gx-sum"><dt>${esc(L.appNo)}</dt><dd>${esc(r.application_no || '—')}</dd><dt>${esc(L.yourAddr)}</dt><dd>${esc(r.domain || '—')}</dd>
      ${r.package ? `<dt>${esc(L.steps[0])}</dt><dd>${esc(r.package)}</dd>` : ''}<dt>${esc(L.mail)}</dt><dd>${esc(state.form.email || '')}</dd></dl>
    <ol class="gx-timeline">${L.timeline.map((x, i) => `<li class="${i === 0 ? 'done' : i === 1 ? 'on' : ''}">${esc(x)}</li>`).join('')}</ol>
    <a class="btn btn-ghost gx-full" href="/">← ${esc(L.back)}</a></div>`;
}

function draw() {
  document.documentElement.lang = lang;
  document.documentElement.dataset.theme = theme;
  $('#app').innerHTML = shell();
  document.querySelectorAll('.gx-tabs [data-tab]').forEach(b => b.addEventListener('click', () => { state.tab = b.dataset.tab; history.replaceState(null, '', state.tab === 'reg' ? '#kayit' : '#'); draw(); }));
  $('#langBtn').addEventListener('click', () => { lang = lang === 'tr' ? 'en' : 'tr'; try { localStorage.setItem('veilox.lang', lang); } catch { /* */ } draw(); });
  $('#themeBtn').addEventListener('click', () => { theme = theme === 'dark' ? 'light' : 'dark'; try { localStorage.setItem('veilox.theme', theme); } catch { /* */ } draw(); });
  if (state.tab === 'reg') regView(); else loginView();
  document.querySelectorAll('#gxBody [data-tab]').forEach(b => b.addEventListener('click', () => { state.tab = b.dataset.tab; history.replaceState(null, '', '#kayit'); draw(); }));
}

(async () => {
  try { const s = await (await fetch('/api/public/site')).json(); base = s.firm_base || base; state.emailVerify = !!s.email_verify; } catch { /* */ }
  draw();
  try { state.pkgs = await (await fetch('/api/public/packages')).json(); } catch { state.pkgs = []; }
  if (state.tab === 'reg' && state.step === 0) regView();
})();
