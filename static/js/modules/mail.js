// Kişisel → Mail (v2, Outlook gibi): birden çok hesap (Gmail, Outlook / Microsoft 365, Yandex, iCloud, Yahoo, özel IMAP /
// Exchange, POP3). Solda "Tüm gelen kutuları" + hesap ağacı (klasörler), ortada liste, sağda okuma bölmesi. Yeni e-posta:
// gönderen hesap seçimi, alıcı otomatik tamamlama (kişisel rehber + şirket), zengin metin, sürükle-bırak ek, taslak.
// İçerik güvenli kutuda (betik çalışmaz); uzak resimler istenirse yüklenir. Davet (ICS) takvime eklenir.
import { api } from '../api.js';
import { icons } from '../icons.js';
import { clear, confirmDialog, field, h, modal, moduleToolbar, pageHead, svgIcon, t, toast, toastError } from '../ui.js';

const FOLDER_ICONS = { inbox: '📥', starred: '⭐', important: '🏷️', sent: '📤', drafts: '📝', archive: '🗄️', all: '🗂️', spam: '⚠️', trash: '🗑️' };
const PROV_ICON = { gmail: 'G', outlook: 'O', yandex: 'Y', icloud: '', yahoo: 'Y!', imap: '@', pop3: 'P' };
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
const esc = s => String(s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const boxColor = b => b?.color || ['#2563eb', '#db2777', '#059669', '#d97706', '#7c3aed', '#0891b2'][(b?.id || 0) % 6];

export async function renderMail(view, params = []) {
  let d;
  try { d = await api.get('/api/mail/boxes'); } catch (e) { clear(view, h('div', { class: 'card empty' }, e.message)); return; }
  const boxes = d.boxes;
  const newBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => compose() }, svgIcon(icons.plus), 'Yeni E-posta');
  const setBtn = h('a', { class: 'btn', href: '#/settings/mailboxes', title: 'Mail hesaplarım' }, svgIcon(icons.settings), 'Hesaplar');
  clear(view, pageHead('Mail', { back: '#/', sub: boxes.length ? t('{n} hesap', { n: boxes.length }) : 'Mail hesabınızı bağlayın' }),
    moduleToolbar(boxes.length ? [newBtn, setBtn] : null));
  if (!boxes.length) {
    view.append(h('div', { class: 'card card-pad mail-connect' }, h('h3', null, 'Henüz mail hesabı bağlı değil'),
      h('p', { class: 'muted' }, 'Gmail, Outlook / Microsoft 365, Yandex, iCloud, Yahoo, şirket (IMAP / Exchange) ya da POP3 hesaplarınızı ekleyin. Hesaplar yalnızca size özeldir; yönetici dahil kimse postalarınızı göremez.'),
      h('a', { class: 'btn primary', href: '#/settings/mailboxes' }, '＋ Mail hesabı ekle')));
    return;
  }
  // Durum: seçili hesap + klasör ("all" = tüm gelen kutuları)
  let cur = { box: params[0] === 'all' || !params[0] ? (boxes.length > 1 ? 'all' : boxes[0].id) : Number(params[0]), folder: 'inbox' };
  if (cur.box !== 'all' && !boxes.some(b => b.id === cur.box)) cur.box = boxes[0].id;
  let page = 0, q = '', current = null, list = { items: [], total: 0, pages: 1 };
  const folderCache = {};
  const expanded = new Set([cur.box === 'all' ? boxes[0].id : cur.box]);
  const selected = new Set();
  const nav = h('nav', { class: 'mail-nav mail2-nav' });
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Postalarda ara…' });
  const bulk = h('div', { class: 'mail-bulk' });
  const listEl = h('div', { class: 'mail-list' });
  const pager = h('div', { class: 'mail-pager' });
  const title = h('div', { class: 'mail-ltitle' });
  const reader = h('section', { class: 'mail-read card' });
  const shell = h('div', { class: 'mail mail2' }, nav, h('div', { class: 'mail-mid card' }, title, h('div', { class: 'mail-tools' }, search, bulk), listEl, pager), reader);
  view.append(shell);
  const boxOf = id => boxes.find(b => b.id === id);

  async function loadFolders(id, quiet) {
    try { folderCache[id] = await api.get(`/api/mail/${id}/folders`); boxOf(id).last_error = null; } catch (e) { boxOf(id).last_error = e.message; if (!quiet) toastError(e); }
    drawNav();
  }
  function drawNav() {
    const fRow = (b, f) => h('button', { type: 'button', class: `mail-f ${cur.box === b.id && cur.folder === f.key ? 'on' : ''}`, onclick: () => go(b.id, f.key) },
      h('span', { class: 'mail-fi' }, FOLDER_ICONS[f.key] || '📁'), h('span', { class: 'grow' }, f.title), f.unseen ? h('b', { class: 'mail-n' }, f.unseen) : null);
    const totalUnseen = boxes.reduce((a, b) => a + ((folderCache[b.id] || []).find(f => f.key === 'inbox')?.unseen || 0), 0);
    clear(nav,
      boxes.length > 1 ? h('button', { type: 'button', class: `mail-f mail-all ${cur.box === 'all' ? 'on' : ''}`, onclick: () => go('all', 'inbox') },
        h('span', { class: 'mail-fi' }, '📬'), h('span', { class: 'grow' }, 'Tüm gelen kutuları'), totalUnseen ? h('b', { class: 'mail-n' }, totalUnseen) : null) : null,
      boxes.map(b => {
        const open = expanded.has(b.id);
        const fs = folderCache[b.id] || [];
        const std = fs.filter(f => !f.custom), custom = fs.filter(f => f.custom);
        return h('div', { class: `mail-acc ${open ? 'open' : ''}` },
          h('button', { type: 'button', class: 'mail-acc-h', onclick: () => { if (open) expanded.delete(b.id); else { expanded.add(b.id); if (!folderCache[b.id]) loadFolders(b.id); } drawNav(); } },
            h('span', { class: 'mail-acc-dot', style: { background: boxColor(b) } }, PROV_ICON[b.provider] || '@'),
            h('span', { class: 'grow mail-acc-e', title: b.email }, b.email),
            b.last_error ? h('span', { class: 'mail-acc-err', title: b.last_error }, '!') : null,
            h('span', { class: 'mail-acc-car' }, open ? '▾' : '▸')),
          open ? h('div', { class: 'mail-acc-f' }, fs.length ? [std.map(f => fRow(b, f)), custom.length ? h('div', { class: 'mail-acc-sub' }, 'Klasörler') : null, custom.map(f => fRow(b, f))]
            : h('div', { class: 'small muted', style: { padding: '6px 10px' } }, b.last_error ? b.last_error : 'Yükleniyor…')) : null);
      }));
  }
  function go(box, folder) {
    cur = { box, folder }; page = 0; q = ''; search.value = ''; selected.clear();
    if (box !== 'all') expanded.add(box);
    drawNav(); openFolder();
  }
  const drawBulk = () => {
    const n = selected.size;
    const b = (label, act, ttl) => h('button', { type: 'button', class: 'btn sm', title: ttl, onclick: () => doAction(cur.box, [...selected], act) }, label);
    clear(bulk, n && cur.box !== 'all' ? [h('span', { class: 'small muted' }, t('{n} seçili', { n })), b('Okundu', 'read'), b('Okunmadı', 'unread'),
      cur.folder === 'inbox' ? b('Arşivle', 'archive') : null, ['spam', 'trash'].includes(cur.folder) ? b('Gelen kutusuna', 'inbox') : null,
      b(cur.folder === 'trash' ? 'Kalıcı sil' : 'Sil', 'trash')]
      : h('button', { type: 'button', class: 'btn sm ghost', title: 'Yenile', onclick: () => { loadList(); if (cur.box !== 'all') loadFolders(cur.box, true); } }, svgIcon(icons.refresh)));
  };
  const row = m => {
    const bid = m.box_id || cur.box;
    const cb = cur.box !== 'all' ? h('input', { type: 'checkbox', checked: selected.has(m.uid), onclick: e => e.stopPropagation(),
      onchange: e => { e.target.checked ? selected.add(m.uid) : selected.delete(m.uid); drawBulk(); } }) : h('span', { class: 'mail-acc-dot sm', style: { background: boxColor(boxOf(bid)) }, title: m.box_email });
    const star = boxOf(bid)?.provider === 'pop3' ? h('span', { class: 'mail-star' }) : h('button', { type: 'button', class: `mail-star ${m.starred ? 'on' : ''}`, title: 'Yıldız',
      onclick: e => {
        e.stopPropagation(); m.starred = !m.starred; star.classList.toggle('on', m.starred); star.textContent = m.starred ? '★' : '☆';
        doAction(bid, [m.uid], m.starred ? 'star' : 'unstar', true, cur.box === 'all' ? 'inbox' : cur.folder);
      } }, m.starred ? '★' : '☆');
    const who = cur.folder === 'sent' || cur.folder === 'drafts' ? t('Kime: {name}', { name: m.to?.name || m.to?.email || '' }) : (m.from?.name || m.from?.email);
    return h('div', { class: `mail-row ${m.seen ? '' : 'unread'} ${current?.uid === m.uid && current?.box === bid ? 'on' : ''}`, 'data-k': `${bid}:${m.uid}`, onclick: () => openMsg(m, bid) },
      cb, star, h('div', { class: 'mail-who' }, who), h('div', { class: 'mail-subj' }, m.subject, m.invite ? h('span', { class: 'mail-clip', title: 'Takvim daveti' }, '📅') : null,
        m.attach ? h('span', { class: 'mail-clip', title: 'Ekli' }, '📎') : null),
      h('div', { class: 'mail-date', title: full(m.date) }, when(m.date)));
  };
  const drawList = () => {
    const b = boxOf(cur.box);
    const fTitle = cur.box === 'all' ? 'Tüm gelen kutuları' : ((folderCache[cur.box] || []).find(f => f.key === cur.folder)?.title || 'Gelen Kutusu');
    clear(title, h('b', null, fTitle), b ? h('span', { class: 'small muted' }, ` · ${b.email}`) : null);
    clear(listEl, list.items.length ? list.items.map(row) : h('div', { class: 'empty small' }, q ? 'Aramaya uyan e-posta yok' : 'Bu klasör boş'));
    clear(pager, list.total && cur.box !== 'all' ? [h('span', { class: 'small muted' }, `${page * 50 + 1}–${Math.min((page + 1) * 50, list.total)} / ${list.total}`),
      h('button', { class: 'btn sm', type: 'button', disabled: page === 0, onclick: () => { page--; loadList(); } }, '‹'),
      h('button', { class: 'btn sm', type: 'button', disabled: page >= list.pages - 1, onclick: () => { page++; loadList(); } }, '›')] : null);
    drawBulk();
  };
  const loadList = async () => {
    clear(listEl, h('div', { class: 'loading small' }, 'Yükleniyor…'));
    try {
      if (cur.box === 'all') {
        const r = await api.get(`/api/mail/unified/inbox?q=${encodeURIComponent(q)}`);
        list = { items: r.items, total: r.items.length, pages: 1 };
        r.errors.forEach(e => { const b = boxOf(e.box_id); if (b) b.last_error = e.error; });
        if (r.errors.length) drawNav();
      } else {
        list = await api.get(`/api/mail/${cur.box}/list?folder=${encodeURIComponent(cur.folder)}&page=${page}&q=${encodeURIComponent(q)}`);
      }
    } catch (err) { toastError(err); list = { items: [], total: 0, pages: 1 }; }
    selected.clear();
    drawList();
  };
  const openFolder = () => {
    current = null;
    shell.classList.remove('reading');
    clear(reader, h('div', { class: 'mail-empty' }, h('div', null, '✉️'), 'Okumak için bir e-posta seçin'));
    loadList();
  };
  async function doAction(bid, uids, act, quiet, folder, target) {
    try {
      await api.post(`/api/mail/${bid}/action`, { folder: folder || cur.folder, uids, action: act, target });
      if (!quiet) toast({ read: 'Okundu işaretlendi', unread: 'Okunmadı işaretlendi', archive: 'Arşivlendi', trash: cur.folder === 'trash' ? 'Kalıcı silindi' : 'Çöp kutusuna taşındı',
        inbox: 'Gelen kutusuna taşındı', spam: 'Gereksiz klasörüne taşındı', move: 'Taşındı' }[act] || 'Tamam');
      if (['archive', 'trash', 'inbox', 'spam', 'move'].includes(act) && current && uids.includes(current.uid)) openFolder();
      else if (!quiet) loadList();
      loadFolders(bid, true);
    } catch (err) { toastError(err); }
  }

  async function openMsg(m, bid) {
    const folder = cur.box === 'all' ? 'inbox' : cur.folder;
    shell.classList.add('reading');
    listEl.querySelectorAll('.mail-row').forEach(r => r.classList.toggle('on', r.dataset.k === `${bid}:${m.uid}`));
    clear(reader, h('div', { class: 'loading' }, 'Açılıyor…'));
    let msg;
    try { msg = await api.get(`/api/mail/${bid}/msg?folder=${encodeURIComponent(folder)}&uid=${m.uid}`); } catch (err) { toastError(err); return; }
    current = { ...msg, box: bid };
    const box = boxOf(bid);
    if (!m.seen) { m.seen = true; listEl.querySelector(`[data-k="${bid}:${m.uid}"]`)?.classList.remove('unread'); loadFolders(bid, true); }
    let remote = false;
    const frame = h('iframe', { class: 'mail-frame', sandbox: 'allow-popups allow-popups-to-escape-sandbox', title: msg.subject });
    const setDoc = () => {
      const csp = `default-src 'none'; img-src data: ${remote ? 'https: http:' : ''}; style-src 'unsafe-inline' ${remote ? 'https:' : ''}; font-src data: ${remote ? 'https:' : ''}`;
      const body = msg.html || `<pre style="white-space:pre-wrap;font:14px/1.5 -apple-system,Segoe UI,Arial,sans-serif;margin:0">${esc(msg.text)}</pre>`;
      frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank">
        <style>body{font:14px/1.5 -apple-system,Segoe UI,Arial,sans-serif;color:#1f2937;margin:12px;word-wrap:break-word}img{max-width:100%;height:auto}</style></head><body>${body}</body></html>`;
    };
    frame.addEventListener('load', () => { try { frame.style.height = `${Math.max(300, frame.contentDocument?.documentElement?.scrollHeight || 600) + 20}px`; } catch { frame.style.height = '70vh'; } });
    setDoc();
    const hasRemote = /<img[^>]+src=["']?https?:/i.test(msg.html || '');
    const remoteBar = hasRemote ? h('div', { class: 'mail-remote' }, 'Gizliliğiniz için uzak resimler gösterilmiyor. ',
      h('button', { class: 'btn sm', type: 'button', onclick: e => { remote = true; setDoc(); e.target.parentElement.remove(); } }, 'Resimleri göster')) : null;
    const act = (label, fn, ttl) => h('button', { class: 'btn sm', type: 'button', title: ttl, onclick: fn }, label);
    const fs = (folderCache[bid] || []).filter(f => !['inbox', 'starred', 'important', 'all', 'drafts'].includes(f.key) && f.key !== folder);
    const moveSel = fs.length && box.provider !== 'pop3' ? h('select', { class: 'input mail-move', title: 'Klasöre taşı', onchange: e => { if (e.target.value) doAction(bid, [msg.uid], 'move', false, folder, e.target.value); } },
      h('option', { value: '' }, 'Taşı…'), fs.map(f => h('option', { value: f.key }, f.title))) : null;
    const inv = msg.invite;
    const inviteCard = inv ? h('div', { class: 'mail-invite' }, h('span', { class: 'mail-invite-i' }, '📅'),
      h('div', { class: 'grow' }, h('b', null, inv.title), h('div', { class: 'small muted' }, [full(inv.starts_at), inv.location, inv.organizer].filter(Boolean).join(' · ')),
        inv.status === 'cancelled' ? h('div', { class: 'small fin-late' }, 'Etkinlik iptal edildi') : null),
      inv.added ? h('span', { class: 'badge green' }, 'Takviminizde') : act('Takvime ekle', async () => {
        try { await api.post(`/api/mail/${bid}/invite`, { folder, uid: msg.uid }); toast('Kişisel takviminize eklendi', 'success'); } catch (e) { toastError(e); }
      })) : null;
    clear(reader,
      h('div', { class: 'mail-rhead' },
        h('button', { class: 'btn sm mail-back', type: 'button', onclick: () => shell.classList.remove('reading') }, '← Liste'),
        h('h2', null, msg.subject),
        h('div', { class: 'mail-acts' },
          folder === 'drafts' ? act('✎ Düzenle', () => compose({ mode: 'draft', msg: current, box: bid })) : [
            act('↩ Yanıtla', () => compose({ mode: 'reply', msg: current, box: bid })), act('↩↩ Tümünü yanıtla', () => compose({ mode: 'all', msg: current, box: bid })),
            act('↪ İlet', () => compose({ mode: 'forward', msg: current, box: bid }))],
          d.can_import && msg.attachments.length && box.provider !== 'pop3' ? act('📄 Evraklara', async () => {
            try {
              const r = await api.post(`/api/mail/${bid}/import`, { folder, uid: msg.uid });
              toast(r.imported ? t('{n} ek evraklara kaydedildi (yalnızca siz görürsünüz, metni okunuyor)', { n: r.imported }) : 'Ekler zaten kayıtlı ya da desteklenmeyen türde');
            } catch (err) { toastError(err); }
          }, 'Ekleri Evrak Yönetimi\'ne yalnızca sizin görebileceğiniz şekilde kaydeder') : null,
          folder === 'inbox' && box.provider !== 'pop3' ? act('Arşivle', () => doAction(bid, [msg.uid], 'archive', false, folder)) : null,
          folder !== 'spam' && box.provider !== 'pop3' ? act('Gereksiz', () => doAction(bid, [msg.uid], 'spam', false, folder), 'Gereksiz (spam) klasörüne taşı') : null,
          act('Okunmadı', () => { doAction(bid, [msg.uid], 'unread', true, folder); openFolder(); }),
          moveSel,
          act(folder === 'trash' || box.provider === 'pop3' ? 'Kalıcı sil' : 'Sil', async () => {
            if ((folder === 'trash' || box.provider === 'pop3') && !await confirmDialog('Kalıcı sil', 'E-posta sunucudan kalıcı olarak silinsin mi?', { okLabel: 'Sil', danger: true })) return;
            doAction(bid, [msg.uid], 'trash', false, folder);
          }))),
      h('div', { class: 'mail-from' }, h('span', { class: 'mail-av' }, initials(msg.from)),
        h('div', { class: 'grow' }, h('b', null, msg.from.name), h('span', { class: 'small muted' }, ` <${msg.from.email}>`),
          h('div', { class: 'small muted' }, t('Kime: {list}', { list: msg.to.map(person).join(', ') || '—' }), msg.cc.length ? t(' · Bilgi: {list}', { list: msg.cc.map(person).join(', ') }) : '')),
        h('div', { class: 'small muted', style: { textAlign: 'right' } }, full(msg.date), h('div', null, h('span', { class: 'mail-acc-dot sm', style: { background: boxColor(box) } }), ' ', box.email))),
      inviteCard, remoteBar,
      msg.attachments.length ? h('div', { class: 'mail-atts' }, msg.attachments.map(a => h('a', {
        class: 'mail-att', href: `/api/mail/${bid}/att?folder=${encodeURIComponent(folder)}&uid=${msg.uid}&idx=${a.idx}${/^(image|audio|video)\/|pdf$/.test(a.type) ? '&inline=true' : ''}`, target: '_blank', rel: 'noopener' },
      svgIcon(icons.paperclip), h('span', null, h('b', null, a.name), h('small', null, size(a.size)))))) : null,
      frame);
  }

  // ---------------- Yeni e-posta / yanıt / ilet / taslak ----------------
  function compose({ mode = 'new', msg = null, box = null } = {}) {
    const re = s => (/^(re|ynt|yanıt):/i.test(s) ? s : `Re: ${s}`), fw = s => (/^(fwd?|ilt):/i.test(s) ? s : `Fwd: ${s}`);
    const fromBox = box || (cur.box !== 'all' ? cur.box : boxes[0].id);
    const from = h('select', { class: 'input' }, boxes.map(b => h('option', { value: b.id, selected: b.id === fromBox }, b.name ? `${b.name} <${b.email}>` : b.email)));
    const me = new Set(boxes.map(b => b.email.toLowerCase()));
    const replyTo = msg && mode !== 'draft' ? (msg.reply_to[0] || msg.from) : null;
    const others = msg && mode === 'all' ? [...msg.to, ...msg.cc].filter(a => !me.has(a.email.toLowerCase()) && a.email !== replyTo.email) : [];
    const to = recipientInput(mode === 'draft' ? msg.to.map(person).join(', ') : (mode === 'reply' || mode === 'all') ? person(replyTo) : '');
    const cc = recipientInput(mode === 'draft' ? msg.cc.map(person).join(', ') : others.map(person).join(', '));
    const bcc = recipientInput('');
    const subject = h('input', { class: 'input', value: msg ? (mode === 'draft' ? msg.subject : mode === 'forward' ? fw(msg.subject) : re(msg.subject)) : '' });
    const quoted = msg && mode !== 'draft' ? (msg.html || `<pre>${esc(msg.text)}</pre>`) : '';
    const head = msg && mode === 'forward' ? `<p>---------- İletilen ileti ----------<br>Kimden: ${esc(person(msg.from))}<br>Tarih: ${esc(full(msg.date))}<br>Konu: ${esc(msg.subject)}<br>Kime: ${esc(msg.to.map(person).join(', '))}</p>`
      : msg && mode !== 'draft' ? `<p>${esc(full(msg.date))} tarihinde ${esc(person(msg.from))} şunu yazdı:</p>` : '';
    const editor = h('div', { class: 'mail-editor', contenteditable: 'true', spellcheck: 'true' });
    editor.innerHTML = mode === 'draft' ? (msg.html || esc(msg.text || '').replace(/\n/g, '<br>')) : (msg ? `<p><br></p><p><br></p>${head}<blockquote class="mail-quote">${sanitize(quoted)}</blockquote>` : '<p><br></p>');
    const cmd = (c, v) => () => { editor.focus(); document.execCommand(c, false, v); };
    const tb = (label, c, v, ttl) => h('button', { type: 'button', class: 'mail-tb', title: ttl, onmousedown: e => e.preventDefault(), onclick: cmd(c, v) }, label);
    const toolbar = h('div', { class: 'mail-toolbar' }, tb(h('b', null, 'K'), 'bold', null, 'Kalın'), tb(h('i', null, 'İ'), 'italic', null, 'İtalik'), tb(h('u', null, 'A'), 'underline', null, 'Altı çizili'),
      tb('• Liste', 'insertUnorderedList', null, 'Madde işaretli liste'), tb('1. Liste', 'insertOrderedList', null, 'Numaralı liste'),
      h('button', { type: 'button', class: 'mail-tb', title: 'Bağlantı', onmousedown: e => e.preventDefault(), onclick: () => { const u = prompt(t('Bağlantı adresi')); if (u) cmd('createLink', u)(); } }, '🔗'),
      tb('⌫ Biçim', 'removeFormat', null, 'Biçimi temizle'));
    const attached = [];
    const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
    const attBox = h('div', { class: 'mail-c-atts' });
    const drawAtts = () => clear(attBox, attached.map((f, i) => h('span', { class: 'mail-c-att' }, '📎 ', f.name, h('small', null, ` ${size(f.size)}`),
      h('button', { type: 'button', onclick: () => { attached.splice(i, 1); drawAtts(); } }, '×'))));
    const addFiles = fl => { [...fl].forEach(f => attached.push(f)); drawAtts(); };
    fileIn.addEventListener('change', () => { addFiles(fileIn.files); fileIn.value = ''; });
    const ccRow = h('div', { class: 'row', hidden: !(mode === 'all' || (mode === 'draft' && msg.cc.length)) }, field('Bilgi (Cc)', cc.el), field('Gizli (Bcc)', bcc.el));
    const form = () => {
      const fd = new FormData();
      fd.append('to', to.value()); fd.append('cc', cc.value()); fd.append('bcc', bcc.value());
      fd.append('subject', subject.value); fd.append('html', editor.innerHTML); fd.append('body', editor.innerText);
      if (msg && (mode === 'reply' || mode === 'all')) { fd.append('reply_id', msg.message_id || ''); fd.append('references', msg.references || ''); }
      if (msg && mode === 'forward') { fd.append('fwd_folder', msg.folder); fd.append('fwd_uid', String(msg.uid)); }
      attached.forEach(f => fd.append('files', f));
      return fd;
    };
    const sendNow = async () => {
      if (!to.value().trim() && !cc.value().trim() && !bcc.value().trim()) throw new Error(t('Alıcı girin'));
      const fd = form();
      if (mode === 'draft') fd.append('draft_uid', String(msg.uid));
      const r = await api.post(`/api/mail/${from.value}/send`, fd);
      toast(r.saved_to_sent ? 'E-posta gönderildi ve Gönderilenler’e kaydedildi' : 'E-posta gönderildi', 'success');
      if (cur.folder === 'sent' || mode === 'draft') loadList();
    };
    const m = modal({
      title: { new: 'Yeni E-posta', reply: 'Yanıtla', all: 'Tümünü Yanıtla', forward: 'İlet', draft: 'Taslak' }[mode], wide: true,
      body: h('div', { class: 'mail-compose mail2-compose' },
        boxes.length > 1 ? field('Kimden', from) : h('div', { class: 'small muted' }, t('Kimden: {f}', { f: from.selectedOptions[0]?.textContent || '' })),
        field('Kime', to.el), ccRow,
        ccRow.hidden ? h('button', { class: 'btn sm ghost', type: 'button', onclick: e => { ccRow.hidden = false; e.target.remove(); } }, '+ Bilgi / Gizli alıcı') : null,
        field('Konu', subject), toolbar, editor,
        h('div', { class: 'mail-c-foot' }, h('button', { class: 'btn sm', type: 'button', onclick: () => fileIn.click() }, '📎 Dosya ekle'), fileIn,
          h('span', { class: 'small muted' }, 'Dosyaları buraya da sürükleyebilirsiniz · en çok 25 MB'), attBox),
        mode === 'forward' && msg.attachments.length ? h('div', { class: 'small muted' }, t('Orijinal {n} ek de iletilecek', { n: msg.attachments.length })) : null),
      actions: [{ label: 'Vazgeç' },
        { label: 'Taslak kaydet', onClick: async () => {
          const fd = form();
          if (mode === 'draft') fd.append('replace_uid', String(msg.uid));
          await api.post(`/api/mail/${from.value}/draft`, fd); toast('Taslak kaydedildi');
          if (cur.folder === 'drafts') loadList();
        } }, 'spacer',
        { label: 'Gönder', class: 'primary', onClick: sendNow }],
    });
    m.el.addEventListener('dragover', e => { e.preventDefault(); m.el.classList.add('mail-drop'); });
    m.el.addEventListener('dragleave', e => { if (e.target === m.el) m.el.classList.remove('mail-drop'); });
    m.el.addEventListener('drop', e => { e.preventDefault(); m.el.classList.remove('mail-drop'); addFiles(e.dataTransfer.files); });
    m.el.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendNow().then(() => m.close()).catch(toastError); } });
    if (mode === 'new' || mode === 'forward') to.focus();
    else { editor.focus(); const r = document.createRange(); r.setStart(editor, 0); r.collapse(true); getSelection().removeAllRanges(); getSelection().addRange(r); }
  }

  let timer;
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { q = search.value.trim(); page = 0; loadList(); }, 400); });
  drawNav();
  boxes.forEach(b => loadFolders(b.id, true));   // klasör ve okunmamış sayıları (hesaplar paralel)
  openFolder();
}

// Alıcı alanı: virgülle çoklu adres; yazdıkça kişisel rehber + şirket kullanıcılarından öneri
function recipientInput(value) {
  const inp = h('input', { class: 'input', value, placeholder: 'ornek@firma.com, …', autocomplete: 'off' });
  const box = h('div', { class: 'mail-sug', hidden: true });
  let timer, items = [], active = -1;
  const lastToken = () => inp.value.split(',').pop().trim();
  const pick = it => {
    const parts = inp.value.split(',');
    parts[parts.length - 1] = ` ${it.name && it.name !== it.email ? `${it.name} <${it.email}>` : it.email}`;
    inp.value = `${parts.join(',').replace(/^\s+/, '')}, `;
    box.hidden = true; inp.focus();
  };
  const draw = () => {
    clear(box, items.map((it, i) => h('button', { type: 'button', class: `mail-sug-i ${i === active ? 'on' : ''}`, onmousedown: e => { e.preventDefault(); pick(it); } },
      h('b', null, it.name || it.email), h('small', null, ` ${it.email}${it.company ? ' · şirket' : ''}`))));
    box.hidden = !items.length;
  };
  inp.addEventListener('input', () => {
    clearTimeout(timer);
    const q = lastToken();
    if (q.length < 2) { box.hidden = true; return; }
    timer = setTimeout(async () => { try { items = await api.get(`/api/mail/contacts/suggest?q=${encodeURIComponent(q)}`); active = -1; draw(); } catch { /* */ } }, 200);
  });
  inp.addEventListener('keydown', e => {
    if (box.hidden) return;
    if (e.key === 'ArrowDown') { active = Math.min(items.length - 1, active + 1); draw(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { active = Math.max(0, active - 1); draw(); e.preventDefault(); }
    else if (e.key === 'Enter' && active >= 0) { pick(items[active]); e.preventDefault(); }
    else if (e.key === 'Escape') box.hidden = true;
  });
  inp.addEventListener('blur', () => setTimeout(() => { box.hidden = true; }, 150));
  return { el: h('div', { class: 'mail-rcpt' }, inp, box), value: () => inp.value.replace(/,\s*$/, '').trim(), focus: () => inp.focus() };
}

// Alıntılanan HTML: betik / olay öznitelikleri / dış kaynaklar ayıklanır (yazma alanında çalışmasın)
function sanitize(html) {
  const doc = new DOMParser().parseFromString(`<div>${html || ''}</div>`, 'text/html');
  doc.querySelectorAll('script,style,iframe,object,embed,link,meta,form').forEach(n => n.remove());
  doc.querySelectorAll('*').forEach(n => [...n.attributes].forEach(a => { if (/^on/i.test(a.name) || (/^(src|href)$/i.test(a.name) && /^\s*javascript:/i.test(a.value))) n.removeAttribute(a.name); }));
  doc.querySelectorAll('img[src^="http"]').forEach(n => n.removeAttribute('src'));
  return doc.body.firstChild.innerHTML;
}
