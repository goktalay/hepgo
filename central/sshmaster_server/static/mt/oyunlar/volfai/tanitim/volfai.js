// VOLFAI tanıtım sayfası (CSP: satır içi betik yok): alt bilgi yılı ve HEMEN OYNA bağlantılarına site kitinin dil / tema tercihinin
// aktarılması (oyun ?lang= ve ?theme= parametrelerini okur; kit.js kendi tercihlerini mt-lang / mt-theme'de tutar).
(() => {
  'use strict';
  const yil = document.getElementById('yil');
  if (yil) yil.textContent = new Date().getFullYear();
  const apply = () => {
    const kit = window.mtKit;
    if (!kit) return;
    document.querySelectorAll('a.store.play').forEach(a => {
      const u = new URL(a.getAttribute('href'), location.href);
      u.searchParams.set('lang', kit.lang);
      u.searchParams.set('theme', kit.theme);
      a.href = u.pathname + u.search;
    });
  };
  addEventListener('mt-lang', apply);
  addEventListener('mt-theme', apply);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply); else apply();
})();
