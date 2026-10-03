// Kişisel → Mail: kullanıcının kendi Gmail hesabı (IMAP/SMTP, uygulama şifresi). Solda klasörler, ortada liste, sağda
// okuma bölmesi. Arama Gmail sözdizimiyle (from:, has:attachment…). E-posta içeriği güvenli kutuda (betik çalışmaz) gösterilir;
// uzak resimler istenirse yüklenir. Yeni / Yanıtla / Tümünü yanıtla / İlet penceresi ekleriyle.
import { api } from '../api.js';
import { icons } from '../icons.js';
import { clear, confirmDialog, field, h, modal, moduleToolbar, pageHead, svgIcon, t, toast, toastError } from '../ui.js';

const FOLDER_ICONS = { inbox: '📥', starred: '⭐', important: '🏷️', sent: '📤', drafts: '📝', all: '🗂️', spam: '⚠️', trash: '🗑️' };
const size = b => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const when = iso => {
  if (!iso) return '';
  const d = new Date(iso), now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
  return d.toLocaleDateString('tr-TR');
};
const full = iso => (iso ? new Date(iso).toLocaleString('tr-TR', { dateStyle: 'long', timeStyle: 'short' }) : '');
const person = a => (a ? (a.name && a.name !== a.email ? `${a.name} <${a.email}>` : a.email) : '');
const initials = a => (a?.name || a?.email || '?').replace(/[^\p{L}\s]/gu, '').split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join('').toLocaleUpperCase('tr') || '@';

export async function renderMail(view, params = []) {
  if (params[0] === 'oauth') {   // Google'dan dönüş: sonuç bildirilir, adres temizlenir
    const msg = decodeURIComponent(params[1] || '');
    if (msg === 'ok') toast('Google hesabınız bağlandı'); else if (msg) toast(msg, 'err');
    history.replaceState(null, '', '#/mail');
    params = [];
  }
  const acc = await api.get('/api/mail/account');
  const newBtn = h('button', { class: 'btn primary', type: 'button' }, svgIcon(icons.plus), 'Yeni E-posta');
  const setBtn = h('button', { class: 'btn', type: 'button', title: 'Mail ayarları' }, svgIcon(icons.settings));
  clear(view, pageHead('Mail', { back: '#/', sub: acc.connected ? acc.email : 'Gmail hesabınızı bağlayın' }),
    moduleToolbar(acc.connected ? [newBtn, setBtn] : null));
  const again = () => window.dispatchEvent(new Event('hashchange'));   // Kişisel başlığıyla yeniden çiz
  if (!acc.connected) { view.append(connectCard(again, acc.oauth_available)); return; }

  let folder = params[0] || 'inbox', page = 0, q = '', current = null, list = { items: [], total: 0, pages: 1 };
  const selected = new Set();
  const nav = h('nav', { class: 'mail-nav' });
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Postalarda ara (ör. from:ali has:attachment)' });
  const bulk = h('div', { class: 'mail-bulk' });
  const listEl = h('div', { class: 'mail-list' });
  const pager = h('div', { class: 'mail-pager' });
  const reader = h('section', { class: 'mail-read card' });
  const shell = h('div', { class: 'mail' }, nav,
    h('div', { class: 'mail-mid card' }, h('div', { class: 'mail-tools' }, search, bulk), listEl, pager), reader);
  view.append(shell);
  let folders = [];

  const loadFolders = async () => {
    folders = await api.get('/api/mail/folders');
    clear(nav, folders.map(f => h('button', { type: 'button', class: `mail-f ${f.key === folder ? 'on' : ''}`, onclick: () => { folder = f.key; page = 0; q = ''; search.value = ''; openFolder(); } },
      h('span', { class: 'mail-fi' }, FOLDER_ICONS[f.key] || '📁'), h('span', { class: 'grow' }, f.title), f.unseen ? h('b', { class: 'mail-n' }, f.unseen) : null)));
  };
  const drawBulk = () => {
    const n = selected.size;
    const b = (label, act, title) => h('button', { type: 'button', class: 'btn sm', title, onclick: () => doAction([...selected], act) }, label);
    clear(bulk, n ? [h('span', { class: 'small muted' }, t('{n} seçili', { n })), b('Okundu', 'read'), b('Okunmadı', 'unread'),
      folder === 'inbox' ? b('Arşivle', 'archive') : null, ['spam', 'trash'].includes(folder) ? b('Gelen kutusuna', 'inbox') : null,
      b(folder === 'trash' ? 'Kalıcı sil' : 'Sil', 'trash')]
      : h('button', { type: 'button', class: 'btn sm ghost', title: 'Yenile', onclick: () => { loadList(); loadFolders(); } }, svgIcon(icons.refresh)));
  };
  const row = m => {
    const cb = h('input', { type: 'checkbox', checked: selected.has(m.uid), onclick: e => e.stopPropagation(),
      onchange: e => { e.target.checked ? selected.add(m.uid) : selected.delete(m.uid); drawBulk(); } });
    const star = h('button', { type: 'button', class: `mail-star ${m.starred ? 'on' : ''}`, title: 'Yıldız',
      onclick: e => { e.stopPropagation(); m.starred = !m.starred; star.classList.toggle('on', m.starred); doAction([m.uid], m.starred ? 'star' : 'unstar', true); } }, m.starred ? '★' : '☆');
    const who = folder === 'sent' || folder === 'drafts' ? t('Kime: {name}', { name: m.to?.name || m.to?.email || '' }) : (m.from?.name || m.from?.email);
    return h('div', { class: `mail-row ${m.seen ? '' : 'unread'} ${current?.uid === m.uid ? 'on' : ''}`, 'data-uid': m.uid, onclick: () => openMsg(m) },
      cb, star, h('div', { class: 'mail-who' }, who), h('div', { class: 'mail-subj' }, m.subject, m.attach ? h('span', { class: 'mail-clip', title: 'Ekli' }, '📎') : null),
      h('div', { class: 'mail-date', title: full(m.date) }, when(m.date)));
  };
  const drawList = () => {
    clear(listEl, list.items.length ? list.items.map(row) : h('div', { class: 'empty small' }, q ? 'Aramaya uyan e-posta yok' : 'Bu klasör boş'));
    clear(pager, list.total ? [h('span', { class: 'small muted' }, `${page * 50 + 1}–${Math.min((page + 1) * 50, list.total)} / ${list.total}`),
      h('button', { class: 'btn sm', type: 'button', disabled: page === 0, onclick: () => { page--; loadList(); } }, '‹'),
      h('button', { class: 'btn sm', type: 'button', disabled: page >= list.pages - 1, onclick: () => { page++; loadList(); } }, '›')] : null);
    drawBulk();
  };
  const loadList = async () => {
    clear(listEl, h('div', { class: 'loading small' }, 'Yükleniyor…'));
    try { list = await api.get(`/api/mail/list?folder=${folder}&page=${page}&q=${encodeURIComponent(q)}`); } catch (err) { toastError(err); list = { items: [], total: 0, pages: 1 }; }
    selected.clear();
    drawList();
  };
  const openFolder = () => {
    current = null;
    shell.classList.remove('reading');
    clear(reader, h('div', { class: 'mail-empty' }, h('div', null, '✉️'), 'Okumak için bir e-posta seçin'));
    nav.querySelectorAll('.mail-f').forEach((b, i) => b.classList.toggle('on', folders[i]?.key === folder));
    loadList();
  };
  async function doAction(uids, act, quiet) {
    try {
      await api.post('/api/mail/action', { folder, uids, action: act });
      if (!quiet) toast({ read: 'Okundu işaretlendi', unread: 'Okunmadı işaretlendi', archive: 'Arşivlendi', trash: folder === 'trash' ? 'Kalıcı silindi' : 'Çöp kutusuna taşındı', inbox: 'Gelen kutusuna taşındı', spam: 'Spam\'e taşındı' }[act] || 'Tamam');
      if (['archive', 'trash', 'inbox', 'spam'].includes(act) && uids.includes(current?.uid)) openFolder();
      else if (!quiet) loadList();
      loadFolders();
    } catch (err) { toastError(err); }
  }

  async function openMsg(m) {
    shell.classList.add('reading');
    listEl.querySelectorAll('.mail-row').forEach(r => r.classList.toggle('on', Number(r.dataset.uid) === m.uid));
    clear(reader, h('div', { class: 'loading' }, 'Açılıyor…'));
    let d;
    try { d = await api.get(`/api/mail/msg/${folder}/${m.uid}`); } catch (err) { toastError(err); return; }
    current = d;
    if (!m.seen) { m.seen = true; listEl.querySelector(`[data-uid="${m.uid}"]`)?.classList.remove('unread'); loadFolders(); }
    let remote = false;
    const frame = h('iframe', { class: 'mail-frame', sandbox: 'allow-popups allow-popups-to-escape-sandbox', title: d.subject });
    const setDoc = () => {
      const csp = `default-src 'none'; img-src data: ${remote ? 'https: http:' : ''}; style-src 'unsafe-inline' ${remote ? 'https:' : ''}; font-src data: ${remote ? 'https:' : ''}`;
      const body = d.html || `<pre style="white-space:pre-wrap;font:14px/1.5 -apple-system,Segoe UI,Arial,sans-serif;margin:0">${(d.text || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))}</pre>`;
      frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank">
        <style>body{font:14px/1.5 -apple-system,Segoe UI,Arial,sans-serif;color:#1f2937;margin:12px;word-wrap:break-word}img{max-width:100%;height:auto}</style></head><body>${body}</body></html>`;
    };
    frame.addEventListener('load', () => { try { frame.style.height = `${Math.max(300, frame.contentDocument?.documentElement?.scrollHeight || 600) + 20}px`; } catch { frame.style.height = '70vh'; } });
    setDoc();
    const hasRemote = /<img[^>]+src=["']?https?:/i.test(d.html || '');
    const remoteBar = hasRemote ? h('div', { class: 'mail-remote' }, 'Gizliliğiniz için uzak resimler gösterilmiyor. ',
      h('button', { class: 'btn sm', type: 'button', onclick: e => { remote = true; setDoc(); e.target.parentElement.remove(); } }, 'Resimleri göster')) : null;
    const act = (label, fn, title) => h('button', { class: 'btn sm', type: 'button', title, onclick: fn }, label);
    clear(reader,
      h('div', { class: 'mail-rhead' },
        h('button', { class: 'btn sm mail-back', type: 'button', onclick: () => shell.classList.remove('reading') }, '← Liste'),
        h('h2', null, d.subject),
        h('div', { class: 'mail-acts' },
          act('↩ Yanıtla', () => compose({ mode: 'reply', msg: d })), act('↩↩ Tümünü yanıtla', () => compose({ mode: 'all', msg: d })),
          act('↪ İlet', () => compose({ mode: 'forward', msg: d })),
          acc.can_import && d.attachments.length ? act('📄 Ekleri Evraklara Kaydet', async () => {
            try {
              const r = await api.post('/api/mail/import', { folder, uid: d.uid });
              toast(r.imported ? t('{n} ek evraklara kaydedildi (yalnızca siz görürsünüz, metni okunuyor)', { n: r.imported }) : 'Ekler zaten kayıtlı ya da desteklenmeyen türde');
            } catch (err) { toastError(err); }
          }, 'Ekleri Evrak Yönetimi\'ne yalnızca sizin görebileceğiniz şekilde kaydeder') : null,
          folder === 'inbox' ? act('Arşivle', () => doAction([d.uid], 'archive')) : null,
          act('Okunmadı', () => { doAction([d.uid], 'unread'); openFolder(); }),
          act(folder === 'trash' ? 'Kalıcı sil' : 'Sil', async () => {
            if (folder === 'trash' && !await confirmDialog('Kalıcı sil', 'E-posta kalıcı olarak silinsin mi?', { okLabel: 'Sil', danger: true })) return;
            doAction([d.uid], 'trash');
          }))),
      h('div', { class: 'mail-from' }, h('span', { class: 'mail-av' }, initials(d.from)),
        h('div', { class: 'grow' }, h('b', null, d.from.name), h('span', { class: 'small muted' }, ` <${d.from.email}>`),
          h('div', { class: 'small muted' }, t('Kime: {list}', { list: d.to.map(person).join(', ') || '—' }), d.cc.length ? t(' · Bilgi: {list}', { list: d.cc.map(person).join(', ') }) : '')),
        h('div', { class: 'small muted' }, full(d.date))),
      remoteBar,
      d.attachments.length ? h('div', { class: 'mail-atts' }, d.attachments.map(a => h('a', {
        class: 'mail-att', href: `/api/mail/att/${folder}/${d.uid}/${a.idx}${/^(image|audio|video)\/|pdf$/.test(a.type) ? '?inline=true' : ''}`, target: '_blank', rel: 'noopener' },
      svgIcon(icons.paperclip), h('span', null, h('b', null, a.name), h('small', null, size(a.size)))))) : null,
      frame);
  }

  function compose({ mode = 'new', msg = null } = {}) {
    const re = s => (/^(re|ynt|yanıt):/i.test(s) ? s : `Re: ${s}`), fw = s => (/^(fwd?|ilt):/i.test(s) ? s : `Fwd: ${s}`);
    const me = acc.email.toLowerCase();
    const replyTo = msg ? (msg.reply_to[0] || msg.from) : null;
    const others = msg ? [...msg.to, ...msg.cc].filter(a => a.email.toLowerCase() !== me && a.email !== replyTo.email) : [];
    const to = h('input', { class: 'input', value: mode === 'reply' || mode === 'all' ? replyTo.email : '', placeholder: 'ornek@firma.com, ...' });
    const cc = h('input', { class: 'input', value: mode === 'all' ? others.map(a => a.email).join(', ') : '' });
    const bcc = h('input', { class: 'input' });
    const subject = h('input', { class: 'input', value: msg ? (mode === 'forward' ? fw(msg.subject) : re(msg.subject)) : '' });
    const quote = msg ? `\n\n${full(msg.date)} tarihinde ${person(msg.from)} şunu yazdı:\n${(msg.text || (msg.html || '').replace(/<style[\s\S]*?<\/style>/gi, '').replace(/<[^>]+>/g, ' ').replace(/\s+\n/g, '\n')).split('\n').map(l => `> ${l}`).join('\n')}` : '';
    const fwdHead = msg && mode === 'forward' ? `\n\n---------- İletilen ileti ----------\nKimden: ${person(msg.from)}\nTarih: ${full(msg.date)}\nKonu: ${msg.subject}\nKime: ${msg.to.map(person).join(', ')}\n\n${msg.text || ''}` : '';
    const body = h('textarea', { class: 'input mail-body', rows: 12 }, mode === 'forward' ? fwdHead : quote);
    const files = h('input', { type: 'file', multiple: true, class: 'input' });
    const ccRow = h('div', { class: 'row', hidden: mode !== 'all' }, field('Bilgi (Cc)', cc), field('Gizli (Bcc)', bcc));
    modal({
      title: { new: 'Yeni E-posta', reply: 'Yanıtla', all: 'Tümünü Yanıtla', forward: 'İlet' }[mode], wide: true,
      body: h('div', { class: 'mail-compose' }, h('div', { class: 'small muted' }, t('Kimden: {from}', { from: acc.name ? `${acc.name} <${acc.email}>` : acc.email })),
        field('Kime', to), ccRow,
        mode !== 'all' ? h('button', { class: 'btn sm ghost', type: 'button', onclick: e => { ccRow.hidden = false; e.target.remove(); } }, '+ Bilgi / Gizli alıcı') : null,
        field('Konu', subject), body, field('Ekler (en çok 25 MB)', files),
        mode === 'forward' && msg.attachments.length ? h('div', { class: 'small muted' }, t('Orijinal {n} ek de iletilecek', { n: msg.attachments.length })) : null,
        acc.signature ? h('div', { class: 'small muted' }, 'İmzanız otomatik eklenir') : null),
      actions: [{ label: 'Vazgeç' }, { label: 'Gönder', class: 'primary', onClick: async () => {
        if (!to.value.trim()) throw new Error('Alıcı girin');
        const fd = new FormData();
        fd.append('to', to.value); fd.append('cc', cc.value); fd.append('bcc', bcc.value);
        fd.append('subject', subject.value); fd.append('body', body.value);
        if (msg && mode !== 'forward') { fd.append('reply_id', msg.message_id || ''); fd.append('references', msg.references || ''); }
        if (msg && mode === 'forward') { fd.append('fwd_folder', msg.folder); fd.append('fwd_uid', String(msg.uid)); }
        [...files.files].forEach(f => fd.append('files', f));
        await api.post('/api/mail/send', fd);
        toast('E-posta gönderildi');
        if (folder === 'sent') loadList();
      } }],
    });
    (mode === 'new' || mode === 'forward' ? to : body).focus();
    if (mode !== 'new' && mode !== 'forward') body.setSelectionRange(0, 0);
  }

  function settingsModal() {
    const name = h('input', { class: 'input', value: acc.name || '' });
    const sig = h('textarea', { class: 'input', rows: 4, placeholder: 'Ör. Ad Soyad · Unvan · Firma · Telefon' }, acc.signature || '');
    const auto = h('input', { type: 'checkbox', checked: acc.auto_import });
    modal({
      title: 'Mail Ayarları',
      body: h('div', null, h('p', { class: 'small muted' }, t('Bağlı hesap: {email} · {how}', { email: acc.email, how: acc.auth_type === 'oauth' ? t('Google ile bağlı') : t('uygulama şifresiyle') })), field('Gönderen adı', name), field('İmza', sig),
        acc.can_import ? h('label', { class: 'set-toggle' }, auto, h('span', null, h('b', null, 'Gelen eklerini Evrak Yönetimi\'ne kaydet'),
          h('small', null, 'Gelen kutusuna yeni düşen e-postaların ekleri yalnızca sizin görebileceğiniz evrak olarak kaydedilir ve metni okunur (OCR)'))) : null,
        acc.last_error ? h('div', { class: 'alert warn small' }, t('Son aktarım hatası: {err}', { err: acc.last_error })) : null),
      actions: [
        { label: 'Hesabı Ayır', class: 'danger', onClick: async () => {
          if (!await confirmDialog('Hesabı ayır', 'Gmail hesabınız sistemden ayrılsın mı? (Gmail\'deki postalarınız silinmez)', { okLabel: 'Ayır', danger: true })) return true;
          await api.del('/api/mail/account'); toast('Hesap ayrıldı'); again();
        } },
        'spacer', { label: 'Vazgeç' },
        { label: 'Kaydet', class: 'primary', onClick: async () => {
          Object.assign(acc, await api.put('/api/mail/account', { name: name.value, signature: sig.value, auto_import: auto.checked })); toast('Kaydedildi');
        } }],
    });
  }

  newBtn.addEventListener('click', () => compose());
  setBtn.addEventListener('click', settingsModal);
  let timer;
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { q = search.value.trim(); page = 0; loadList(); }, 400); });
  try { await loadFolders(); } catch (err) { clear(shell, h('div', { class: 'card empty' }, err.message, ' ', h('button', { class: 'btn', onclick: settingsModal }, 'Mail ayarları'))); return; }
  openFolder();
}

// İlk bağlama: kurumsal hesaplar için "Google ile bağlan" (OAuth); kişisel Gmail için uygulama şifresi
const GOOGLE_G = '<svg viewBox="0 0 48 48" width="20" height="20" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.6 13.3l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.1 5.5c4.2-3.9 7.2-9.6 7.2-16.9z"/><path fill="#FBBC05" d="M10.5 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.1.8-4.6l-7.9-6.1C.9 16.6 0 20.2 0 24s.9 7.4 2.6 10.7l7.9-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.1-5.5c-2 1.4-4.6 2.2-8.8 2.2-6.3 0-11.6-4.1-13.5-9.9l-7.9 6.1C6.6 42.6 14.6 48 24 48z"/></svg>';

function connectCard(done, oauth) {
  const google = h('button', { class: 'btn mail-google', type: 'button', disabled: !oauth, onclick: async () => {
    try { location.href = (await api.get('/api/mail/oauth/start')).url; } catch (err) { toastError(err); }
  } }, svgIcon(GOOGLE_G), 'Google ile bağlan');
  const addr = h('input', { class: 'input', type: 'email', placeholder: 'ad.soyad@gmail.com', autocomplete: 'email' });
  const pw = h('input', { class: 'input mono', type: 'password', placeholder: 'xxxx xxxx xxxx xxxx', autocomplete: 'off' });
  const btn = h('button', { class: 'btn', type: 'submit' }, 'Uygulama şifresiyle bağla');
  const form = h('form', { class: 'card card-pad mail-connect' },
    h('h3', null, 'Gmail hesabınızı bağlayın'),
    h('p', { class: 'muted' }, 'Şirket e-postalarınızı buradan okuyup gönderebilirsiniz. Bağlantı yalnızca size özeldir; yönetici dahil kimse postalarınızı göremez.'),
    h('div', { class: 'mail-google-box' }, google,
      h('div', { class: 'small muted' }, oauth
        ? 'Şirket (Google Workspace) hesapları için: Google\'ın kendi giriş ekranında hesabınızı seçip izin verin. Şifreniz bu sisteme girilmez; izni istediğiniz an geri alabilirsiniz.'
        : 'Google ile bağlanma henüz ayarlanmadı. Şirket hesapları için sistem yöneticisinin Google bağlantısını (OAuth) tanımlaması gerekir.')),
    h('details', { class: 'mail-pw', open: !oauth },
      h('summary', null, 'Kişisel Gmail: uygulama şifresiyle bağla'),
      h('ol', { class: 'steps' },
        h('li', null, 'Google hesabınızda ', h('b', null, '2 Adımlı Doğrulama'), ' açık olmalı.'),
        h('li', null, h('a', { href: 'https://myaccount.google.com/apppasswords', target: '_blank', rel: 'noopener' }, 'myaccount.google.com/apppasswords'),
          ' adresinde bir ad yazın (ör. "Fabrika") ve ', h('b', null, 'Oluştur'), '’a basın.'),
        h('li', null, 'Gösterilen ', h('b', null, '16 haneli uygulama şifresini'), ' aşağıya yapıştırın. (Normal Gmail şifreniz çalışmaz; şirket hesaplarında bu seçenek genelde kapalıdır.)')),
      h('div', { class: 'row' }, field('Gmail adresi', addr), field('Uygulama şifresi', pw)),
      h('div', { class: 'set-actions left' }, btn)));
  form.addEventListener('submit', async e => {
    e.preventDefault();
    btn.disabled = true; btn.textContent = 'Bağlanıyor…';
    try { await api.post('/api/mail/account', { email: addr.value, password: pw.value }); toast('Gmail hesabı bağlandı'); done(); }
    catch (err) { toastError(err); } finally { btn.disabled = false; btn.textContent = 'Uygulama şifresiyle bağla'; }
  });
  return form;
}
