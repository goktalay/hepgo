'use strict';

// Mastertool web (mtweb) ön yüz katmanı — yalnız mtweb servisinde yüklenir (HEPGO'da yok).
// window.MTWEB sunucudan (/web/config.js) gelir. Burada: site dili, ince üst şerit (uygulama, kullanıcı, masaüstü indir,
// tüm uygulamalar, çıkış), oturum düşünce girişe yönlendirme ve bilgi sayfası metinleri.
(function () {
  const W = window.MTWEB || {};
  const CODES = ['tr', 'en', 'fr', 'de', 'es', 'ar', 'zh', 'ru'];
  function pickLang() {
    try { const s = localStorage.getItem('mt-lang'); if (CODES.includes(s)) return s; } catch { /* özel kip */ }
    for (const l of navigator.languages || [navigator.language || '']) { const c = String(l || '').slice(0, 2).toLowerCase(); if (CODES.includes(c)) return c; }
    return 'en';
  }
  W.lang = pickLang();

  const STR = {
    tr: { download: 'Masaüstü sürümünü indir', allApps: 'Tüm uygulamalar', logout: 'Çıkış', soon: 'Web sürümü yakında — masaüstü sürümünü indirin.', disabled: 'Bu uygulama geçici olarak kapalı.', verify: 'Lütfen e-posta adresinizi doğrulayın.', notfound: 'Sayfa bulunamadı.', desktopOnly: 'Bu özellik masaüstü sürümünde', files: 'Dosyalarınız' },
    en: { download: 'Download the desktop version', allApps: 'All apps', logout: 'Sign out', soon: 'The web version is coming soon — download the desktop version.', disabled: 'This app is temporarily unavailable.', verify: 'Please verify your e-mail address.', notfound: 'Page not found.', desktopOnly: 'Available in the desktop version', files: 'Your files' },
    fr: { download: 'Télécharger la version de bureau', allApps: 'Toutes les applications', logout: 'Déconnexion', soon: 'La version web arrive bientôt — téléchargez la version de bureau.', disabled: 'Cette application est temporairement indisponible.', verify: 'Veuillez vérifier votre adresse e-mail.', notfound: 'Page introuvable.', desktopOnly: 'Disponible dans la version de bureau', files: 'Vos fichiers' },
    de: { download: 'Desktop-Version herunterladen', allApps: 'Alle Apps', logout: 'Abmelden', soon: 'Die Webversion kommt bald — laden Sie die Desktop-Version herunter.', disabled: 'Diese App ist vorübergehend nicht verfügbar.', verify: 'Bitte bestätigen Sie Ihre E-Mail-Adresse.', notfound: 'Seite nicht gefunden.', desktopOnly: 'In der Desktop-Version verfügbar', files: 'Ihre Dateien' },
    es: { download: 'Descargar la versión de escritorio', allApps: 'Todas las aplicaciones', logout: 'Cerrar sesión', soon: 'La versión web llegará pronto — descargue la versión de escritorio.', disabled: 'Esta aplicación no está disponible temporalmente.', verify: 'Verifique su dirección de correo.', notfound: 'Página no encontrada.', desktopOnly: 'Disponible en la versión de escritorio', files: 'Sus archivos' },
    ar: { download: 'تنزيل إصدار سطح المكتب', allApps: 'كل التطبيقات', logout: 'تسجيل الخروج', soon: 'إصدار الويب قريبًا — نزّل إصدار سطح المكتب.', disabled: 'هذا التطبيق غير متاح مؤقتًا.', verify: 'يرجى تأكيد بريدك الإلكتروني.', notfound: 'الصفحة غير موجودة.', desktopOnly: 'متاح في إصدار سطح المكتب', files: 'ملفاتك' },
    zh: { download: '下载桌面版', allApps: '所有应用', logout: '退出', soon: '网页版即将推出 — 请下载桌面版。', disabled: '此应用暂时不可用。', verify: '请验证您的电子邮件地址。', notfound: '页面未找到。', desktopOnly: '桌面版提供此功能', files: '您的文件' },
    ru: { download: 'Скачать настольную версию', allApps: 'Все приложения', logout: 'Выйти', soon: 'Веб-версия скоро — скачайте настольную версию.', disabled: 'Приложение временно недоступно.', verify: 'Подтвердите адрес электронной почты.', notfound: 'Страница не найдена.', desktopOnly: 'Доступно в настольной версии', files: 'Ваши файлы' },
  };
  W.t = (k) => (STR[W.lang] || STR.en)[k] || STR.en[k] || k;
  window.MTWEB = W;

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function inSameOriginFrame() {
    if (window.parent === window) return false;
    try { return window.parent.location.host === location.host; } catch { return false; }
  }

  async function logout() {
    try { await fetch(W.logoutUrl || '/api/mt/auth/logout', { method: 'POST', credentials: 'same-origin', headers: { 'x-sshm': '1' } }); } catch { /* ağ */ }
    location.href = '/';
  }
  W.logout = logout;

  function strip() {
    if (inSameOriginFrame() || !document.body || document.getElementById('mtweb-strip')) return;
    const u = W.user || {};
    const el = document.createElement('div');
    el.id = 'mtweb-strip';
    el.innerHTML = `<span class="mw-app">${W.app ? `<img src="/static/mt/${esc(W.app)}/icon.png" alt="">` : ''}<b>${esc(W.appName || 'Mastertool')}</b></span>
      <span class="mw-sp"></span>
      <a class="mw-link" href="${esc(W.downloadUrl || '/#indir')}">${esc(W.t('download'))}</a>
      <a class="mw-link" href="${esc(W.allAppsUrl || 'https://mastertool.download/uygulamalar')}">${esc(W.t('allApps'))}</a>
      ${u.name || u.email ? `<span class="mw-user" title="${esc(u.email || '')}">${esc(u.name || u.email)}</span>` : ''}
      <button type="button" class="mw-out">${esc(W.t('logout'))}</button>`;
    el.querySelector('.mw-out').addEventListener('click', logout);
    document.body.prepend(el);
    document.body.classList.add('mtweb-has-strip');
  }

  function infoPage() {
    document.documentElement.lang = W.lang;
    if (W.lang === 'ar') document.documentElement.dir = 'rtl';
    for (const n of document.querySelectorAll('[data-t]')) n.textContent = W.t(n.dataset.t);
  }

  // Oturum düştüyse (API 401) girişe
  window.addEventListener('caymaz:unauthorized', () => {
    const next = location.pathname + location.search;
    location.href = `${W.loginUrl || '/giris'}?next=${encodeURIComponent(next)}`;
  });

  const ready = () => { if (document.body.classList.contains('mtweb-info')) infoPage(); else strip(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
})();
