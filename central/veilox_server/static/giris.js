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
    verifyH: 'E-postanızı doğrulayın', verifyP: e => `${e} adresine 6 haneli bir kod gönderdik. Aşağıya girin.`, verifyBtn: 'Doğrula',
    expiresIn: 'Kodun süresi', codeExpired: 'Kodun süresi doldu. Yeniden gönderin.', verifying: 'Doğrulanıyor…',
    emailVerified: 'E-posta doğrulandı', changeMail: 'E-postayı değiştir', closeM: 'Kapat', verifyFirst: 'Devam etmek için e-postanızı doğrulayın.',
    loginNow: 'Giriş yap', readyH: 'Firmanız hazır!', readyP: 'Hesabınız oluşturuldu ve firmanız kuruldu. Hemen giriş yapabilirsiniz.',
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
    verifyH: 'Verify your email', verifyP: e => `We sent a 6-digit code to ${e}. Enter it below.`, verifyBtn: 'Verify',
    expiresIn: 'Code expires in', codeExpired: 'Code expired. Resend it.', verifying: 'Verifying…',
    emailVerified: 'Email verified', changeMail: 'Change email', closeM: 'Close', verifyFirst: 'Verify your email to continue.',
    loginNow: 'Sign in', readyH: 'Your company is ready!', readyP: 'Your account was created and your company is set up. You can sign in now.',
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
const state = { tab: location.hash === '#kayit' ? 'reg' : 'login', step: 0, pkg: qs.get('paket') || '', pkgs: [], form: {}, result: null, emailVerify: false, codeSentOnce: false, openBeta: false, emailVerified: false };
// Açık betada "Paket" adımı yok → ilk adım doğrudan Firma (adım 1). Adım numaraları sabit kalır (1=Firma,2=Yönetici,3=Tamam).
const firstStep = () => state.openBeta ? 1 : 0;
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
  // Açık betada Paket adımı gizli → logical adım no'ları korunur (1=Firma…), yalnız görünümden çıkarılır.
  const items = L.steps.map((s, i) => [i, s]).filter(([i]) => !(state.openBeta && i === 0));
  return `<ol class="gx-steps">${items.map(([i, s], k) => `<li class="${i < state.step ? 'done' : i === state.step ? 'on' : ''}"><span>${i < state.step ? '✓' : k + 1}</span>${esc(s)}</li>`).join('')}</ol>`;
}

// Ülkeler (bayrak emoji 2-harf koddan). Türkiye ilk; sonra yaygın ülkeler.
const COUNTRIES = [['TR', 'Türkiye'], ['DE', 'Almanya'], ['US', 'ABD'], ['GB', 'Birleşik Krallık'], ['FR', 'Fransa'], ['NL', 'Hollanda'], ['IT', 'İtalya'], ['ES', 'İspanya'], ['AZ', 'Azerbaycan'], ['SA', 'Suudi Arabistan'], ['AE', 'BAE'], ['QA', 'Katar'], ['RU', 'Rusya'], ['UA', 'Ukrayna'], ['CN', 'Çin'], ['IN', 'Hindistan'], ['JP', 'Japonya'], ['KR', 'Güney Kore'], ['BR', 'Brezilya'], ['CA', 'Kanada'], ['AU', 'Avustralya'], ['EG', 'Mısır'], ['GR', 'Yunanistan'], ['BG', 'Bulgaristan'], ['RO', 'Romanya'], ['PL', 'Polonya'], ['SE', 'İsveç'], ['CH', 'İsviçre'], ['BE', 'Belçika'], ['AT', 'Avusturya']];
const cflag = cc => (cc && cc.length === 2) ? String.fromCodePoint(...[...cc.toUpperCase()].map(c => 127397 + c.charCodeAt(0))) : '';

function regView() {
  const L = t();
  const body = $('#gxBody');
  if (state.openBeta && state.step === 0) state.step = 1;   // Paket adımı betada yok
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
          <div class="gx-drop${f.logo ? ' has' : ''}" id="logoDrop" tabindex="0" role="button">
            <input type="file" id="logoInput" accept="image/png,image/jpeg,image/webp,image/gif" hidden>
            <div class="gx-drop-prev" id="logoPrev">${f.logo ? `<img src="${f.logo}" alt="">` : ''}</div>
            <div class="gx-drop-cta">
              <span class="gx-drop-ic">${svg('<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>')}</span>
              <b id="logoTitle">${f.logo ? esc(L.logoChange) : esc(L.logoPick)}</b>
              <span class="small muted">${esc(L.logoHint)}</span>
            </div>
            <button type="button" class="gx-drop-x" id="logoDel"${f.logo ? '' : ' hidden'} aria-label="${esc(L.logoRemove)}">×</button>
          </div>
        </div>
        <div class="vx-err" id="f1err"></div>
        <div class="gx-acts">${state.openBeta ? '<span></span>' : `<button type="button" class="btn btn-ghost" id="prev">← ${esc(L.prev)}</button>`}<button class="btn btn-primary btn-lg" type="submit">${esc(L.next)} →</button></div>
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
    // Logo (kurallı, şık dropzone — tıkla ya da sürükle-bırak)
    const drop = $('#logoDrop'), logoInput = $('#logoInput');
    const paintLogo = () => {
      $('#logoPrev').innerHTML = state.form.logo ? `<img src="${state.form.logo}" alt="">` : '';
      $('#logoTitle').textContent = state.form.logo ? L.logoChange : L.logoPick;
      $('#logoDel').hidden = !state.form.logo;
      drop.classList.toggle('has', !!state.form.logo);
    };
    const takeFile = (file) => {
      if (!file) return;
      err.textContent = '';
      if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) { err.textContent = L.logoBadType; return; }
      if (file.size > 2 * 1024 * 1024) { err.textContent = L.logoTooBig; return; }
      const rd = new FileReader();
      rd.onload = () => { state.form.logo = rd.result; paintLogo(); };
      rd.readAsDataURL(file);
    };
    drop.addEventListener('click', e => { if (e.target.id !== 'logoDel') logoInput.click(); });
    drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); logoInput.click(); } });
    $('#logoDel').addEventListener('click', e => { e.stopPropagation(); state.form.logo = ''; logoInput.value = ''; paintLogo(); });
    logoInput.addEventListener('change', () => { takeFile(logoInput.files[0]); logoInput.value = ''; });
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('drag'); }));
    ['dragleave', 'dragend', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('drag'); }));
    drop.addEventListener('drop', e => { if (e.dataTransfer && e.dataTransfer.files[0]) takeFile(e.dataTransfer.files[0]); });
    if ($('#prev')) $('#prev').addEventListener('click', () => { state.step = 0; regView(); });
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
    // E-posta doğrulaması gerekli mi, edildi mi? Doğrulanana kadar ŞİFRE alanı görünmez (kullanıcı isteği #3).
    const needV = state.emailVerify && !state.emailVerified;
    body.innerHTML = `<div class="gx-pane">${stepsBar()}<h2>${esc(L.adminH)}</h2><p class="gx-sub">${esc(L.adminP)}</p>
      <form id="f2" class="gx-form">
        <label class="vx-field"><span>${esc(L.full)}</span><input class="vx-input" name="full" value="${esc(f.full || '')}" autocomplete="name" required autofocus></label>
        <label class="vx-field"><span>${esc(L.mail)}</span>
          <div class="gx-inint">
            <input class="vx-input" type="email" name="email" value="${esc(f.email || '')}" autocomplete="email" required${state.emailVerified ? ' disabled' : ''}>
            ${state.emailVerify ? (state.emailVerified
              ? `<span class="gx-inint-ok">${svg('<path d="M5 12l4 4 10-10"/>')}${esc(L.emailVerified)}</span>`
              : `<button type="button" class="gx-inint-btn" id="sendCode">${esc(L.sendCode)}</button>`) : ''}
          </div>
          ${state.emailVerify && state.emailVerified ? `<small class="gx-slug-msg"><button type="button" class="gx-link" id="changeMail">${esc(L.changeMail)}</button></small>` : ''}
        </label>
        <div id="pwSection"${needV ? ' hidden' : ''}>
          <div class="gx-row"><label class="vx-field"><span>${esc(L.pw)}</span><input class="vx-input" type="password" name="pw" minlength="10" autocomplete="new-password"${needV ? '' : ' required'}></label>
            <label class="vx-field"><span>${esc(L.pw2)}</span><input class="vx-input" type="password" name="pw2" minlength="10" autocomplete="new-password"${needV ? '' : ' required'}></label></div>
          <div class="gx-meter"><i id="pwBar"></i><small id="pwTxt"></small></div>
          <label class="gx-check"><input type="checkbox" name="accept"${needV ? '' : ' required'}><span>${esc(L.accept)}</span></label>
        </div>
        <div class="vx-err" id="regErr"></div>
        ${needV ? `<p class="gx-sub gx-verifyhint">${esc(L.verifyFirst)}</p>` : ''}
        <div class="gx-acts"><button type="button" class="btn btn-ghost" id="prev">← ${esc(L.prev)}</button>
          ${needV ? '' : `<button class="btn btn-primary btn-lg" type="submit">${esc(L.submit)}</button>`}</div>
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
    if (form.pw) form.pw.addEventListener('input', meter);
    $('#prev').addEventListener('click', () => { state.form.full = form.full.value; if (form.email && !form.email.disabled) state.form.email = form.email.value; state.step = 1; regView(); });
    // E-postayı değiştir → doğrulamayı sıfırla, tekrar kod iste
    if ($('#changeMail')) $('#changeMail').addEventListener('click', () => { state.emailVerified = false; state.codeSentOnce = false; state.form.full = form.full.value; regView(); });
    // "Doğrulama kodu gönder" (input içinde) → email'i kilitle + modal aç
    if ($('#sendCode')) {
      $('#sendCode').addEventListener('click', async () => {
        const email = form.email.value.trim().toLowerCase();
        if (!/.+@.+\..+/.test(email)) { err.textContent = L.badEmail; form.email.focus(); return; }
        err.textContent = ''; state.form.full = form.full.value; state.form.email = email;
        const btn = $('#sendCode'); btn.disabled = true; btn.textContent = L.codeSending; form.email.disabled = true;
        try {
          const r = await post('/api/register/send-code', { email });
          state.codeSentOnce = true;
          openVerifyModal(email, r.sent_to || email);
        } catch (ex) { err.textContent = ex.message; form.email.disabled = false; }
        btn.disabled = false; btn.textContent = L.sendCode;
      });
    }
    form.addEventListener('submit', async e => {
      e.preventDefault();
      err.textContent = '';
      if (needV) { err.textContent = L.verifyFirst; return; }
      if (form.pw.value !== form.pw2.value) { err.textContent = L.mismatch; return; }
      const btn = form.querySelector('button[type=submit]'); if (btn) btn.disabled = true;
      Object.assign(state.form, { full: form.full.value.trim() });
      if (form.email && !form.email.disabled) state.form.email = form.email.value.trim();
      try {
        state.result = await post('/api/register', { company_name: state.form.company, master_username: state.form.email, master_name: state.form.full, password: form.pw.value,
          package_slug: state.pkg, phone: state.form.phone, tax_no: state.form.tax, city: state.form.city, accept: form.accept.checked, email_code: '',
          slug: state.form.slug || '', country: state.form.country || '', logo: state.form.logo || '' });
        state.step = 3; regView();
      } catch (ex) { err.textContent = ex.message; if (btn) btn.disabled = false; }
    });
    return;
  }
  // ---- Adım 3: Sonuç ----
  const r = state.result || {};
  if (r.status === 'active' && r.url) {
    // Açık beta otomatik kurulum: firma hazır → doğrudan giriş düğmesi (onay/başvuru akışı yok)
    body.innerHTML = `<div class="gx-pane gx-done">${stepsBar()}
      <div class="gx-ok">${svg('<path d="M5 12l4 4 10-10"/>')}</div>
      <h2>${esc(L.readyH)}</h2><p class="gx-sub">${esc(L.readyP)}</p>
      <dl class="gx-sum"><dt>${esc(L.yourAddr)}</dt><dd>${esc(r.domain || '—')}</dd><dt>${esc(L.mail)}</dt><dd>${esc(state.form.email || '')}</dd></dl>
      <a class="btn btn-primary btn-lg gx-full" href="${esc(r.url)}">${esc(L.loginNow)} →</a></div>`;
    return;
  }
  body.innerHTML = `<div class="gx-pane gx-done">${stepsBar()}
    <div class="gx-ok">${svg('<path d="M5 12l4 4 10-10"/>')}</div>
    <h2>${esc(L.okH)}</h2><p class="gx-sub">${esc(L.okP)}</p>
    <dl class="gx-sum"><dt>${esc(L.appNo)}</dt><dd>${esc(r.application_no || '—')}</dd><dt>${esc(L.yourAddr)}</dt><dd>${esc(r.domain || '—')}</dd>
      ${r.package ? `<dt>${esc(L.steps[0])}</dt><dd>${esc(r.package)}</dd>` : ''}<dt>${esc(L.mail)}</dt><dd>${esc(state.form.email || '')}</dd></dl>
    <ol class="gx-timeline">${L.timeline.map((x, i) => `<li class="${i === 0 ? 'done' : i === 1 ? 'on' : ''}">${esc(x)}</li>`).join('')}</ol>
    <a class="btn btn-ghost gx-full" href="/">← ${esc(L.back)}</a></div>`;
}

// E-posta doğrulama modalı (ping/çağrı ekranı tarzı, geri sayımlı). Doğru pin → /api/register/verify-code → şifre adımı açılır.
function openVerifyModal(email, masked) {
  const L = t();
  document.querySelectorAll('.gx-modal-wrap').forEach(n => n.remove());
  const wrap = document.createElement('div');
  wrap.className = 'gx-modal-wrap';
  wrap.innerHTML = `<div class="gx-modal" role="dialog" aria-modal="true">
    <button type="button" class="gx-modal-x" id="mX" aria-label="${esc(L.closeM)}">×</button>
    <div class="gx-ping"><span class="gx-ping-ring"></span><span class="gx-ping-ring d2"></span>
      <span class="gx-ping-core">${svg('<path d="M4 4h16v16H4z" fill="none"/><path d="M22 6l-10 7L2 6"/><rect x="2" y="4" width="20" height="16" rx="2" fill="none"/>')}</span></div>
    <h3>${esc(L.verifyH)}</h3><p class="gx-sub">${esc(L.verifyP(masked))}</p>
    <input class="vx-input gx-pin" id="mPin" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="______" aria-label="${esc(L.codeL)}">
    <div class="gx-count" id="mCount"></div>
    <div class="vx-err" id="mErr"></div>
    <button class="btn btn-primary btn-lg gx-full" id="mVerify">${esc(L.verifyBtn)}</button>
    <button type="button" class="gx-link gx-resend" id="mResend" disabled>${esc(L.resend)}</button>
  </div>`;
  document.body.appendChild(wrap);
  const pin = $('#mPin', wrap), errEl = $('#mErr', wrap), countEl = $('#mCount', wrap);
  const verifyBtn = $('#mVerify', wrap), resendBtn = $('#mResend', wrap);
  pin.focus();
  let left = 600, resendAt = 60, timer = null;           // kod 10 dk geçerli; 60 sn sonra tekrar gönder
  const fmt = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  const render = () => {
    countEl.textContent = left > 0 ? `${L.expiresIn} ${fmt(left)}` : L.codeExpired;
    countEl.className = left > 0 ? 'gx-count' : 'gx-count exp';
    resendBtn.disabled = resendAt > 0;
    resendBtn.textContent = resendAt > 0 ? `${L.resend} (${resendAt})` : L.resend;
  };
  render();
  timer = setInterval(() => { if (left > 0) left--; if (resendAt > 0) resendAt--; render(); if (left <= 0) { clearInterval(timer); } }, 1000);
  const close = () => { if (timer) clearInterval(timer); wrap.remove(); const e = document.querySelector('#f2 input[name=email]'); if (e) e.disabled = false; };
  $('#mX', wrap).addEventListener('click', close);
  wrap.addEventListener('click', e => { if (e.target === wrap) close(); });
  document.addEventListener('keydown', function esc0(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc0); } });
  pin.addEventListener('input', () => { pin.value = pin.value.replace(/\D/g, '').slice(0, 6); if (pin.value.length === 6) verifyBtn.click(); });
  const doVerify = async () => {
    const code = pin.value.trim();
    if (code.length !== 6) { errEl.textContent = L.codeNeed; return; }
    errEl.textContent = ''; verifyBtn.disabled = true; verifyBtn.textContent = L.verifying; pin.disabled = true;
    try {
      await post('/api/register/verify-code', { email, code });
      if (timer) clearInterval(timer);
      state.emailVerified = true; state.form.email = email;
      wrap.remove();
      regView();   // şifre adımı artık görünür
    } catch (ex) { errEl.textContent = ex.message; verifyBtn.disabled = false; verifyBtn.textContent = L.verifyBtn; pin.disabled = false; pin.focus(); pin.select(); }
  };
  verifyBtn.addEventListener('click', doVerify);
  resendBtn.addEventListener('click', async () => {
    errEl.textContent = ''; resendBtn.disabled = true;
    try { const r = await post('/api/register/send-code', { email }); left = 600; resendAt = 60; render(); countEl.textContent = L.codeSent(r.sent_to || masked); }
    catch (ex) { errEl.textContent = ex.message; resendAt = 0; render(); }
  });
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
  try { const s = await (await fetch('/api/public/site')).json(); base = s.firm_base || base; state.emailVerify = !!s.email_verify; state.openBeta = !!s.open_beta; } catch { /* */ }
  if (state.openBeta && state.step === 0) state.step = firstStep();   // Paket adımı betada yok
  draw();
  if (!state.openBeta) {
    try { state.pkgs = await (await fetch('/api/public/packages')).json(); } catch { state.pkgs = []; }
    if (state.tab === 'reg' && state.step === 0) regView();
  }
})();
