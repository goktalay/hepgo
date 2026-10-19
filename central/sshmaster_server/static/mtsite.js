// Mastertool siteleri (ürün siteleri + mastertool.download ana sayfası): başlıkta oturum durumu.
// Çerez HttpOnly olduğundan durum GET /api/<site>/session ile sorulur (oturum yoksa da 200, {user:null}).
// Oturum yoksa sunucudan gelen "Giriş" + "Kayıt ol" bağlantıları olduğu gibi kalır (betik yüklenmezse de çalışır);
// oturum varsa kullanıcı adı (Hesabım) + "Web'de aç" (yalnız ürün sitesi: /web/<uygulama>/) + "Çıkış".
// Metinler Türkçe kaynaktır; kit.js eklenen öğeleri sitenin sözlüğüyle çevirir (ad data-noi18n).
(() => {
  'use strict';
  const slot = document.querySelector('[data-mt-auth]');
  if (!slot) return;
  const site = /^[a-z]{2}$/.test(slot.dataset.mtAuth || '') ? slot.dataset.mtAuth : 'mt';
  const web = /^\/web\/[a-z]+\/$/.test(slot.dataset.web || '') ? slot.dataset.web : '';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ICON_OUT = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l-5-5 5-5M5 12h11"/></svg>';
  fetch(`/api/${site}/session`, { credentials: 'same-origin', cache: 'no-store' })
    .then(r => (r.ok ? r.json() : null))
    .then(d => {
      if (!d || !d.user) return;
      const name = (d.user.name || d.user.email || '').trim();
      slot.classList.add('in');
      slot.innerHTML = `<a class="mt-user" href="/hesabim" title="${esc(d.user.email)}"><span class="mt-av" data-noi18n>${esc(name.slice(0, 1).toLocaleUpperCase())}</span><span class="mt-un" data-noi18n>${esc(name)}</span></a>`
        + (web ? `<a class="mt-webbtn" href="${web}">Web'de aç</a>` : '')   // portalda başlıkta zaten "Uygulamalar" bağlantısı var
        + `<button type="button" class="mt-out" title="Çıkış" aria-label="Çıkış">${ICON_OUT}</button>`;
      slot.querySelector('.mt-out').addEventListener('click', async () => {
        await fetch(`/api/${site}/auth/logout`, { method: 'POST', credentials: 'same-origin', headers: { 'X-SSHM': '1' } }).catch(() => {});
        location.reload();
      });
    })
    .catch(() => {});
})();
