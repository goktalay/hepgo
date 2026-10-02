// Tanıtım sayfası: oturum açıksa üstte kullanıcı rozeti (resim, ad, e-posta) ve menüden uygulamaya giriş;
// değilse "Giriş Yap" (/app). Cihaz sekmeleri, cihaz içi slaytlar, kaydırınca beliren bölümler.
(function () {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const svg = d => `<svg viewBox="0 0 24 24">${d}</svg>`;

  // ---- Modül kartları ----
  const FEATURES = [
    ['Üretim ve iş emirleri', 'Sipariş → üretim → depo → montaj → kalibrasyon akışı; parça bazında takip, hata kayıtları.', '#2f6fed', '#eaf1ff', '<path d="M3 21h18M5 21V9l5 3V9l5 3V5l4 2v14"/>'],
    ['Yazıcı odası', 'Creality K2 Plus yazıcıların canlı durumu, 3B oda görünümü ve doğrudan G-code gönderimi.', '#7c5cf5', '#f1ecff', '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 17v4h10v-4"/>'],
    ['Malzeme ihtiyaç planlaması', 'Çoklu depo, stok hareketleri, kritik stok uyarıları, fatura ve irsaliye ile giriş-çıkış.', '#0ea5a4', '#e3f7f6', '<path d="M3 7l9-4 9 4-9 4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/>'],
    ['Satın alma ve satış', 'Talep, teklif (revizyonlu), tedarikçi ve satış faturaları; stoğa otomatik yansır.', '#f59e0b', '#fff4e0', '<path d="M3 4h2l2.4 11.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.5L21 8H6"/><circle cx="10" cy="20" r="1.4"/><circle cx="17" cy="20" r="1.4"/>'],
    ['Mikro ERP entegrasyonu', 'Cari, stok, alış ve satış faturaları tek tıkla aktarılır; senkronize kayıtlar ayrı izlenir.', '#16a34a', '#e6f7ec', '<path d="M4 7h11l-3-3M20 17H9l3 3"/>'],
    ['Mesajlaşma ve toplantı', 'Sohbet, sesli arama, kayıt ve deşifre; davet koduyla görüntülü toplantı ve ekran paylaşımı.', '#ec4899', '#fdebf4', '<path d="M20.5 12a8.5 8.5 0 0 1-12.4 7.5L3.5 20.5l1.1-4.4A8.5 8.5 0 1 1 20.5 12z"/>'],
    ['Saha ve uçuş', 'Saha görevleri, araç ve yol kayıtları, uçuş logları ve telemetri analizi.', '#0284c7', '#e2f2fb', '<path d="M2 16l20-7-7 13-3-6z"/>'],
    ['İnsan kaynakları ve sekreterya', 'Personel ve özlük dosyaları, izinler; misafir, kargo ve telefon kayıtları.', '#9333ea', '#f4e8fd', '<circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><circle cx="17.5" cy="9" r="2.4"/><path d="M16 14.2A5 5 0 0 1 21.5 20"/>'],
    ['Güvenlik, rapor ve pano', 'Kamera izleme ve giriş-çıkış, hazır raporlar ve kişiye özel düzenlenebilir pano.', '#dc2626', '#fdecec', '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>'],
  ];
  $('#features').innerHTML = FEATURES.map(([t, d, c, s, p], i) =>
    `<div class="feat reveal" style="--c:${c};--c-soft:${s};--d:${(i % 3) * 0.06}s"><div class="feat-ic">${svg(p)}</div><b>${t}</b><p>${d}</p></div>`).join('');

  // ---- Şirket adı / yıl ----
  $('#year').textContent = new Date().getFullYear();
  fetch('/api/meta').then(r => r.ok ? r.json() : null).then(m => {
    if (m?.company) { $('#companyName').textContent = m.company; document.title = `Fabrika Yönetim Sistemi · ${m.company}`; }
  }).catch(() => {});

  // ---- Oturum: kullanıcı rozeti ----
  const initials = n => (n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(s => s[0].toLocaleUpperCase('tr')).join('');
  const av = u => u.photo ? `<span class="uc-av"><img src="/api/files/${encodeURI(u.photo)}?w=128" alt=""></span>` : `<span class="uc-av">${esc(initials(u.full_name))}</span>`;
  fetch('/api/auth/me', { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).then(u => {
    if (!u || !u.id) return;
    $$('[data-app-link]').forEach(a => { a.textContent = 'Uygulamaya Git'; });
    const box = $('#auth');
    box.innerHTML = `
      <button class="user-chip" type="button" aria-haspopup="menu" aria-expanded="false">
        ${av(u)}<span class="uc-txt"><b>${esc(u.full_name)}</b><small>${esc(u.username)}</small></span>
        <svg class="uc-chev" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>
      </button>
      <div class="user-menu" role="menu">
        <div class="um-head">${av(u)}<div><b>${esc(u.full_name)}</b><small>${esc(u.username)}</small></div></div>
        <a class="um-go" href="/app">${svg('<path d="M5 12h14M13 6l6 6-6 6"/>')}Uygulamaya Git</a>
        <a href="/app#/messages">${svg('<path d="M20.5 12a8.5 8.5 0 0 1-12.4 7.5L3.5 20.5l1.1-4.4A8.5 8.5 0 1 1 20.5 12z"/>')}Mesajlar</a>
        <a href="/app#/meet">${svg('<rect x="2.5" y="6" width="13.5" height="12" rx="3"/><path d="M16 10.5l5.5-3.2v9.4L16 13.5z"/>')}Görüntülü Toplantı</a>
        <a href="/app#/settings">${svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>')}Ayarlar</a>
        <button class="um-out" type="button">${svg('<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l-5-5 5-5M5 12h11"/>')}Çıkış Yap</button>
      </div>`;
    const chip = $('.user-chip', box), menu = $('.user-menu', box);
    const set = open => { menu.classList.toggle('open', open); chip.setAttribute('aria-expanded', String(open)); };
    chip.addEventListener('click', e => { e.stopPropagation(); set(!menu.classList.contains('open')); });
    document.addEventListener('click', e => { if (!box.contains(e.target)) set(false); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
    $('.um-out', box).addEventListener('click', async () => {
      try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }); } catch { /* */ }
      location.reload();
    });
  }).catch(() => {});

  // ---- Menü gölgesi ----
  const nav = $('#nav');
  const onScroll = () => nav.classList.toggle('scrolled', scrollY > 8);
  addEventListener('scroll', onScroll, { passive: true }); onScroll();

  // ---- Kaydırınca beliren ----
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
  }), { threshold: 0.12, rootMargin: '0px 0px -40px 0px' }) : null;
  $$('.reveal').forEach(el => io ? io.observe(el) : el.classList.add('in'));

  // ---- Cihaz içi slaytlar (açıklamalar eşlik eder) ----
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const slideshows = $$('.dev-pane').map(pane => {
    const imgs = $$('[data-slides] img', pane), caps = $$('[data-captions] span', pane);
    if (!imgs.length) return null;
    let i = 0;
    const show = n => { i = n; imgs.forEach((im, k) => im.classList.toggle('on', k === i)); caps.forEach((c, k) => c.classList.toggle('on', k === i)); };
    show(0);
    return { pane, next: () => imgs.length > 1 && show((i + 1) % imgs.length), show };
  }).filter(Boolean);
  if (!reduce) setInterval(() => slideshows.forEach(s => { if (s.pane.classList.contains('on') && !document.hidden) s.next(); }), 4200);

  // ---- Cihaz sekmeleri ----
  $$('.dev-tabs button').forEach(b => b.addEventListener('click', () => {
    $$('.dev-tabs button').forEach(x => x.classList.toggle('on', x === b));
    $$('.dev-pane').forEach(p => p.classList.toggle('on', p.dataset.pane === b.dataset.dev));
    slideshows.find(s => s.pane.dataset.pane === b.dataset.dev)?.show(0);
  }));
})();
