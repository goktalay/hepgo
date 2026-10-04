// Kişisel Ayarlar › Mail Hesaplarım ve Sosyal Medya. Hesaplar yalnızca sahibine özeldir (yönetici dahil kimse göremez).
// Mail: Google / Microsoft ile bağlan (OAuth; anahtarlar Program Ayarları › Entegrasyonlar'da), ya da uygulama şifresiyle
// Gmail / Yandex / iCloud / Yahoo, özel IMAP / Exchange ve POP3. Sosyal: RSS, YouTube, Bluesky, Mastodon (anahtarsız);
// Instagram / Facebook / X / TikTok anahtar girilince açılır. Paylaşımlar Şirketten Haberler'de yalnızca sahibine görünür.
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, t, toast, toastError } from '../ui.js';

const GOOGLE_G = '<svg viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.7 13.3l7.9 6.1C12.5 13.6 17.8 9.5 24 9.5z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 2.9-2.2 5.4-4.7 7.1l7.6 5.9c4.4-4.1 6.9-10.1 6.9-17.5z"/><path fill="#FBBC05" d="M10.6 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.2.8-4.6l-7.9-6.1C1 16.6 0 20.2 0 24s1 7.4 2.7 10.7l7.9-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2.1 1.4-4.9 2.3-8.3 2.3-6.2 0-11.5-4.1-13.4-9.9l-7.9 6.1C6.6 42.6 14.6 48 24 48z"/></svg>';
const MS_LOGO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#F25022" d="M1 1h10.5v10.5H1z"/><path fill="#7FBA00" d="M12.5 1H23v10.5H12.5z"/><path fill="#00A4EF" d="M1 12.5h10.5V23H1z"/><path fill="#FFB900" d="M12.5 12.5H23V23H12.5z"/></svg>';
const svgEl = s => { const d = document.createElement('span'); d.className = 'prov-logo'; d.innerHTML = s; return d; };
const PROV_COLOR = { gmail: '#ea4335', outlook: '#0078d4', yandex: '#fc3f1d', icloud: '#3b82f6', yahoo: '#6001d2', imap: '#475569', pop3: '#64748b' };
const PROV_ICON = { gmail: 'G', outlook: 'O', yandex: 'Y', icloud: '', yahoo: 'Y!', imap: '@', pop3: 'P' };
const COLORS = ['#2563eb', '#db2777', '#059669', '#d97706', '#7c3aed', '#0891b2', '#dc2626', '#475569'];
const chk = (label, checked, hint) => {
  const cb = h('input', { type: 'checkbox', checked: !!checked });
  return { el: h('label', { class: 'set-toggle' }, cb, h('span', null, h('b', null, label), hint ? h('small', null, hint) : null)), get: () => cb.checked };
};

// ---------------- Mail Hesaplarım ----------------
export function mailboxesSection(query = '') {
  const wrap = h('div', null, h('section', { class: 'card card-pad set-card' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  const msg = new URLSearchParams(query).get('msg');
  if (msg) {
    if (msg === 'ok') toast('Mail hesabı bağlandı', 'success'); else toast(msg, 'err');
    history.replaceState(null, '', '#/settings/mailboxes');
  }
  let d, provs;
  const load = async () => {
    try { [d, provs] = await Promise.all([api.get('/api/mail/boxes'), provs ? provs : api.get('/api/mail/providers')]); } catch (e) { clear(wrap, h('div', { class: 'card empty' }, e.message)); return; }
    draw();
  };
  const draw = () => {
    const P = provs.providers;
    clear(wrap, h('section', { class: 'card card-pad set-card' },
      h('h3', null, 'Mail Hesaplarım'),
      h('p', { class: 'small muted' }, 'Bağladığınız hesaplar Kişisel › Mail ekranında Outlook gibi birlikte görünür: tüm gelen kutuları, klasörler, arama, yeni e-posta, yanıt / iletme, taslak. Davetler takviminize, yazıştığınız kişiler kişisel rehberinize eklenir. Hesaplarınızı ve postalarınızı yönetici dahil kimse göremez.'),
      h('div', { class: 'set-actions left' }, h('button', { class: 'btn primary', type: 'button', onclick: addWizard }, '＋ Mail hesabı ekle'),
        d.boxes.length ? h('a', { class: 'btn', href: '#/mail' }, 'Mail’e git') : null),
      d.boxes.length ? h('div', { class: 'mbx-list' }, d.boxes.map((b, i) => h('div', { class: 'mbx' },
        h('span', { class: 'mail-acc-dot', style: { background: b.color || PROV_COLOR[b.provider] || '#475569' } }, PROV_ICON[b.provider] || '@'),
        h('div', { class: 'grow' }, h('div', { class: 'mbx-e' }, b.email),
          h('div', { class: 'small muted' }, [P[b.provider]?.title || b.provider, b.auth_type === 'google' ? 'Google ile bağlı' : b.auth_type === 'microsoft' ? 'Microsoft ile bağlı' : 'şifreyle',
            b.name].filter(Boolean).join(' · ')),
          b.last_error ? h('div', { class: 'small fin-late' }, `⚠ ${b.last_error}`)
            : h('div', { class: 'small muted' }, b.last_ok ? t('Son erişim: {d}', { d: fmtDateTime(b.last_ok) }) : '',
              b.last_sync ? t(' · Takvim/kişi eşitleme: {d}', { d: fmtDateTime(b.last_sync) }) : ''),
          b.sync_error ? h('div', { class: 'small fin-late' }, `⚠ ${b.sync_error}`) : null),
        h('div', { class: 'mbx-acts' },
          i > 0 ? h('button', { class: 'btn xs ghost', type: 'button', title: 'Yukarı taşı', onclick: async () => {
            const ids = d.boxes.map(x => x.id); [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]];
            try { await api.put('/api/mail/boxes-order', { ids }); load(); } catch (e) { toastError(e); }
          } }, '↑') : null,
          b.auth_type !== 'password' ? h('button', { class: 'btn xs', type: 'button', title: 'Takvim ve kişileri şimdi eşitle', onclick: async e => {
            e.currentTarget.disabled = true;
            try {
              const r = await api.post(`/api/mail/${b.id}/sync`, {});
              if (r.errors?.length) toast(r.errors.join(' · '), 'err');
              else toast(t('{e} takvim öğesi, {c} kişi eşitlendi', { e: r.events, c: r.contacts }), 'success');
              load();
            } catch (err) { toastError(err); load(); }
          } }, '⟳ Eşitle') : null,
          h('button', { class: 'btn xs', type: 'button', onclick: () => editBox(b) }, 'Düzenle'),
          h('button', { class: 'btn xs danger', type: 'button', onclick: async () => {
            if (!await confirmDialog('Hesabı ayır', t('{e} hesabı ayrılsın mı? Postalarınız sunucuda kalır; yalnızca bu uygulamadaki bağlantı ve takvim öğeleri kaldırılır.', { e: b.email }), { okLabel: 'Ayır', danger: true })) return;
            try { await api.del(`/api/mail/boxes/${b.id}`); toast('Hesap ayrıldı'); load(); } catch (e) { toastError(e); }
          } }, 'Ayır'))))) : h('p', { class: 'small muted' }, 'Henüz bağlı hesap yok.')));
  };

  function addWizard() {
    const P = provs.providers, oa = provs.oauth;
    const oauthBtn = (prov, logo, label) => h('button', { class: 'prov', type: 'button', disabled: !oa[prov],
      title: oa[prov] ? '' : 'Bu sunucuda henüz ayarlanmadı: yönetici Program Ayarları › Entegrasyonlar’dan anahtarı girmeli',
      onclick: async () => { try { const r = await api.get(`/api/mail/oauth/${prov}/start`); location.href = r.url; } catch (e) { toastError(e); } } },
      svgEl(logo), h('b', null, label), h('small', null, oa[prov]
        ? (prov === 'google' ? 'Gmail + Google Takvim + Kişiler. Şifre gerekmez.' : 'Outlook, Hotmail, Microsoft 365 / Exchange Online + takvim + kişiler.')
        : 'Anahtar gerekli (yönetici: Program Ayarları › Entegrasyonlar)'));
    const pwBtn = key => h('button', { class: 'prov', type: 'button', onclick: () => { m.close(); passwordForm(key); } },
      h('span', { class: 'prov-ic', style: { background: PROV_COLOR[key] } }, PROV_ICON[key] || '@'), h('b', null, P[key].title), h('small', null, P[key].help));
    const m = modal({
      title: 'Mail hesabı ekle', wide: true,
      body: h('div', null,
        h('h4', { class: 'set-sub' }, 'Tek tıkla bağlan (önerilen)'),
        h('div', { class: 'prov-grid' }, oauthBtn('google', GOOGLE_G, 'Google ile bağlan'), oauthBtn('microsoft', MS_LOGO, 'Microsoft ile bağlan')),
        h('h4', { class: 'set-sub' }, 'Şifre / uygulama şifresi ile'),
        h('div', { class: 'prov-grid' }, ['gmail', 'yandex', 'icloud', 'yahoo', 'imap', 'pop3'].filter(k => P[k]).map(pwBtn))),
      actions: [{ label: 'Kapat' }],
    });
  }

  function passwordForm(key) {
    const p = provs.providers[key];
    const email = h('input', { class: 'input', type: 'email', autocomplete: 'off', placeholder: 'ad@firma.com' });
    const name = h('input', { class: 'input', placeholder: 'Gönderen adı (boşsa adınız)' });
    const pw = h('input', { class: 'input', type: 'password', autocomplete: 'new-password' });
    const login = h('input', { class: 'input', placeholder: 'Boşsa e-posta adresi' });
    const inHost = h('input', { class: 'input', placeholder: p.pop ? 'pop.firma.com' : 'imap.firma.com' });
    const inPort = h('input', { class: 'input', type: 'number', value: p.pop ? 995 : 993 });
    const outHost = h('input', { class: 'input', placeholder: 'smtp.firma.com' });
    const outPort = h('input', { class: 'input', type: 'number', value: 465 });
    const sec = h('select', { class: 'input' }, h('option', { value: 'ssl' }, 'SSL/TLS (465)'), h('option', { value: 'starttls' }, 'STARTTLS (587)'));
    sec.addEventListener('change', () => { outPort.value = sec.value === 'ssl' ? 465 : 587; });
    email.addEventListener('input', () => {   // alan adından sunucu tahmini
      const dom = (email.value.split('@')[1] || '').trim();
      if (!dom || !p.custom) return;
      if (!inHost.dataset.touched) inHost.value = `${p.pop ? 'pop' : 'imap'}.${dom}`;
      if (!outHost.dataset.touched) outHost.value = `smtp.${dom}`;
    });
    [inHost, outHost].forEach(i => i.addEventListener('input', () => { i.dataset.touched = '1'; }));
    modal({
      title: t('{p} hesabı ekle', { p: p.title }), wide: !!p.custom,
      body: h('div', null,
        h('p', { class: 'small muted' }, p.help),
        h('div', { class: 'row' }, field('E-posta adresi', email), field('Ad', name)),
        field(['gmail', 'yandex', 'icloud', 'yahoo'].includes(key) ? 'Uygulama şifresi' : 'Şifre', pw),
        p.custom ? [
          h('h4', { class: 'set-sub' }, p.pop ? 'Gelen sunucu (POP3)' : 'Gelen sunucu (IMAP)'),
          h('div', { class: 'row' }, field('Sunucu', inHost), field('Port (SSL)', inPort)),
          h('h4', { class: 'set-sub' }, 'Giden sunucu (SMTP)'),
          h('div', { class: 'row' }, field('Sunucu', outHost), field('Güvenlik', sec), field('Port', outPort)),
          field('Kullanıcı adı', login)] : null,
        h('p', { class: 'small muted' }, 'Şifre şifrelenmiş olarak saklanır ve hiçbir ekranda gösterilmez. Bağlanmadan önce sunucuya giriş denenir.')),
      actions: [{ label: 'Vazgeç' }, 'spacer', { label: 'Bağlan', class: 'primary', onClick: async () => {
        const body = { provider: key, email: email.value.trim(), password: pw.value, name: name.value.trim() || null, login: login.value.trim() || null };
        if (p.custom) {
          Object.assign(body, p.pop ? { pop_host: inHost.value.trim(), pop_port: Number(inPort.value) || 995 } : { imap_host: inHost.value.trim(), imap_port: Number(inPort.value) || 993 },
            { smtp_host: outHost.value.trim(), smtp_port: Number(outPort.value) || 465, smtp_security: sec.value });
        }
        await api.post('/api/mail/boxes', body);
        toast('Mail hesabı bağlandı', 'success');
        load();
      } }],
    });
    email.focus();
  }

  function editBox(b) {
    const name = h('input', { class: 'input', value: b.name || '' });
    let color = b.color || PROV_COLOR[b.provider];
    const sw = h('div', { class: 'sr-sw' });
    const drawSw = () => clear(sw, COLORS.map(c => { const x = h('button', { type: 'button', class: c === color ? 'on' : '', title: c, onclick: () => { color = c; drawSw(); } }); x.style.background = c; return x; }));
    drawSw();
    const sig = h('textarea', { class: 'input', rows: 4, placeholder: 'Ad Soyad\nUnvan · Firma\n+90 …' }, b.signature || '');
    const pop = b.provider === 'pop3', oauth = b.auth_type !== 'password';
    const saveSent = chk('Gönderilenleri sunucuya kaydet', b.save_sent, 'Gönderilen e-postanın kopyası hesabın “Gönderilenler” klasörüne yazılır (Gmail / Outlook / Yahoo bunu kendisi yapar)');
    const autoImp = chk('Gelen ekleri Evraklara aktar', b.auto_import, 'Yeni e-postaların ekleri “Yalnızca ben” görünürlüğünde Evrak Yönetimi’ne kaydedilir ve metni okunur');
    const cal = chk('Takvim eşitlemesi', b.sync_calendar, oauth ? 'Hesabın takvimi ve mail davetleri Kişisel Takvim’inizde görünür' : 'Mail davetleri (toplantı istekleri) Kişisel Takvim’inize eklenir');
    const con = chk('Kişileri rehbere al', b.sync_contacts, 'Hesabın kişileri Rehber › Kişilerim’e gelir (yalnızca siz görürsünüz)');
    const pw = h('input', { class: 'input', type: 'password', autocomplete: 'new-password', placeholder: 'Değiştirmek için yeni şifre' });
    modal({
      title: b.email,
      body: h('div', null,
        field('Gönderen adı', name), h('div', { class: 'field' }, h('span', null, 'Renk'), sw),
        field('İmza (gönderilen e-postaların altına eklenir)', sig),
        h('h4', { class: 'set-sub' }, 'Seçenekler'),
        pop ? null : saveSent.el, d.can_import && !pop ? autoImp.el : null, cal.el, oauth ? con.el : null,
        oauth ? null : [h('h4', { class: 'set-sub' }, 'Şifre'), pw]),
      actions: [{ label: 'Vazgeç' }, 'spacer', { label: 'Kaydet', class: 'primary', onClick: async () => {
        const body = { name: name.value, color, signature: sig.value, sync_calendar: cal.get() };
        if (!pop) body.save_sent = saveSent.get();
        if (d.can_import && !pop) body.auto_import = autoImp.get();
        if (oauth) body.sync_contacts = con.get();
        if (pw.value) body.password = pw.value;
        await api.put(`/api/mail/boxes/${b.id}`, body);
        toast('Kaydedildi', 'success');
        load();
      } }],
    });
  }

  load();
  return wrap;
}

// ---------------- Sosyal Medya ----------------
const SOC_COLOR = { rss: '#f97316', youtube: '#ff0000', bluesky: '#0085ff', mastodon: '#6364ff', instagram: '#e1306c', facebook: '#1877f2', x: '#111', tiktok: '#010101' };
const SOC_ICON = { rss: 'RSS', youtube: '▶', bluesky: '🦋', mastodon: 'M', instagram: 'IG', facebook: 'f', x: '𝕏', tiktok: '♪' };
export const socialBadge = p => h('span', { class: 'prov-ic soc-ic', style: { background: SOC_COLOR[p] || '#475569' } }, SOC_ICON[p] || '•');

export function socialSection(query = '') {
  const wrap = h('div', null, h('section', { class: 'card card-pad set-card' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  const msg = new URLSearchParams(query).get('msg');   // OAuth dönüşü (X ile bağlan)
  if (msg) {
    if (msg === 'ok') toast('Hesap bağlandı', 'success'); else toast(msg, 'err');
    history.replaceState(null, '', '#/settings/social');
  }
  let d;
  const load = async () => {
    try { d = await api.get('/api/social/accounts'); } catch (e) { clear(wrap, h('div', { class: 'card empty' }, e.message)); return; }
    draw();
  };
  const draw = () => {
    const feedCb = h('input', { type: 'checkbox', checked: d.feed_on });
    feedCb.addEventListener('change', async () => { try { await api.put('/api/social/feed-on', { on: feedCb.checked }); toast(feedCb.checked ? 'Paylaşımlar akışta gösterilecek' : 'Paylaşımlar akıştan gizlendi'); } catch (e) { toastError(e); } });
    clear(wrap, h('section', { class: 'card card-pad set-card' },
      h('h3', null, 'Sosyal Medya'),
      h('p', { class: 'small muted' }, 'Takip ettiğiniz ya da kendi hesaplarınızı bağlayın; yeni paylaşımlar Şirketten Haberler akışında tarihine göre araya karışır. Bu paylaşımları yalnızca siz görürsünüz, şirketteki başka kimse görmez.'),
      h('label', { class: 'set-toggle' }, feedCb, h('span', null, h('b', null, 'Şirketten Haberler’de göster'), h('small', null, 'Kapatırsanız hesaplar bağlı kalır ama akışta görünmez'))),
      h('div', { class: 'set-actions left' }, h('button', { class: 'btn primary', type: 'button', onclick: addAcc }, '＋ Hesap bağla')),
      d.accounts.length ? h('div', { class: 'mbx-list' }, d.accounts.map(a => {
        const cb = h('input', { type: 'checkbox', checked: !!a.show_in_feed, title: 'Akışta göster' });
        cb.addEventListener('change', async () => { try { await api.put(`/api/social/accounts/${a.id}`, { show_in_feed: cb.checked }); } catch (e) { toastError(e); } });
        return h('div', { class: 'mbx' },
          a.avatar ? h('img', { class: 'soc-av', src: a.avatar, alt: '', referrerpolicy: 'no-referrer', onerror: e => e.target.replaceWith(socialBadge(a.provider)) }) : socialBadge(a.provider),
          h('div', { class: 'grow' }, h('div', { class: 'mbx-e' }, a.display_name || a.handle),
            h('div', { class: 'small muted' }, [d.providers[a.provider]?.title, a.handle !== a.display_name ? a.handle : null, t('{n} paylaşım', { n: a.posts })].filter(Boolean).join(' · ')),
            a.last_error ? h('div', { class: 'small fin-late' }, `⚠ ${a.last_error}`) : a.last_sync ? h('div', { class: 'small muted' }, t('Son yenileme: {d}', { d: fmtDateTime(a.last_sync) })) : null),
          h('div', { class: 'mbx-acts' },
            h('label', { class: 'soc-feed' }, cb, 'Akışta'),
            h('button', { class: 'btn xs', type: 'button', onclick: async e => {
              e.currentTarget.disabled = true;
              try { const r = await api.post(`/api/social/accounts/${a.id}/refresh`, {}); toast(r.new ? t('{n} yeni paylaşım', { n: r.new }) : 'Yeni paylaşım yok'); } catch (err) { toastError(err); }
              load();
            } }, '⟳ Yenile'),
            h('button', { class: 'btn xs danger', type: 'button', onclick: async () => {
              if (!await confirmDialog('Hesabı kaldır', t('{n} bağlantısı ve indirilen paylaşımları kaldırılsın mı?', { n: a.display_name || a.handle }), { okLabel: 'Kaldır', danger: true })) return;
              try { await api.del(`/api/social/accounts/${a.id}`); toast('Kaldırıldı'); load(); } catch (e) { toastError(e); }
            } }, 'Kaldır')));
      })) : h('p', { class: 'small muted' }, 'Henüz bağlı hesap yok.'),
      h('p', { class: 'small muted' }, 'Paylaşımlar yaklaşık 30 dakikada bir yenilenir (X hesapları okuma kotası nedeniyle 6 saatte bir; “Yenile” ile hemen).')));
  };
  function addAcc() {
    let prov = 'youtube';
    const handle = h('input', { class: 'input' });
    const hint = h('small', { class: 'hint' });
    const grid = h('div', { class: 'prov-grid' });
    const drawGrid = () => {
      clear(grid, Object.entries(d.providers).map(([k, p]) => h('button', { class: `prov ${k === prov ? 'on' : ''}`, type: 'button', disabled: !d.available[k],
        title: d.available[k] ? '' : `Henüz kullanılamıyor: yönetici Program Ayarları › Entegrasyonlar › ${p.title}’ı ayarlamalı`,
        onclick: () => { prov = k; drawGrid(); handle.focus(); } },
        socialBadge(k), h('b', null, p.title), h('small', null, d.available[k] ? p.hint : 'Yakında · anahtar gerekli'))));
      const oauth = !!d.providers[prov].oauth;
      field.hidden = oauth;
      connect.hidden = !oauth;
      connect.textContent = t('{n} ile bağlan', { n: d.providers[prov].title });
      handle.placeholder = d.providers[prov].hint;
      hint.textContent = d.providers[prov].hint;
    };
    // OAuth sağlayıcı (X): kullanıcı adı girilmez; sağlayıcının izin ekranına gidilir, dönüşte hesap eklenir
    const connect = h('button', { class: 'btn primary', type: 'button', hidden: true, style: { marginTop: '12px' }, onclick: async e => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try { location.href = (await api.get(`/api/social/oauth/${prov}/start`)).url; } catch (err) { btn.disabled = false; toastError(err); }
    } });
    const field = h('div', { class: 'field', style: { marginTop: '12px' } }, h('span', null, 'Hesap / adres'), handle, hint);
    drawGrid();
    modal({
      title: 'Sosyal medya hesabı bağla', wide: true,
      body: h('div', null, grid, field, connect),
      actions: [{ label: 'Vazgeç' }, 'spacer', { label: 'Bağla', class: 'primary', onClick: async () => {
        if (d.providers[prov].oauth) { connect.click(); return true; }   // yönlendirilene dek açık kalsın
        const r = await api.post('/api/social/accounts', { provider: prov, handle: handle.value.trim() });
        toast(t('{n} bağlandı', { n: r.display_name || r.handle }), 'success');
        load();
      } }],
    });
  }
  load();
  return wrap;
}
