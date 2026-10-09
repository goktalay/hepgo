// Şirketten Haberler: pano akışı (Facebook tarzı) — sistem olayları + kullanıcı paylaşımları (resim/video/ses + konum).
// İki görünüm: Akış ve Harita. Sistem olaylarında şirket logosu, kullanıcı paylaşımında kişinin fotoğrafı.
import { api, fileUrl, upload, videoUrl } from '../api.js';
import { loadMaps } from '../maps.js';
import { avatar, clear, confirmDialog, fmtDate, fmtDateTime, h, modal, onLeave, segmented, toast, toastError } from '../ui.js';
import { socialBadge } from './mysettings.js';

const KIND_BADGE = {
  HIRE: ['green', 'İşe alım'], TERMINATION: ['', 'Ayrılış'], FLIGHT: ['blue', 'Uçuş'],
  ORDER: ['blue', 'Sipariş'], MEETING: ['yellow', 'Toplantı'], ANNOUNCE: ['red', 'Duyuru'], USER: ['', ''], LIVE: ['red', '🔴 Canlı yayın'],
};
const LOGO = '/static/img/logo-mark.png?v=3';

// Paylaşılan metindeki URL'leri tıklanabilir bağlantıya çevirir (geri kalanı düz metin node'u).
function linkify(text) {
  const out = [];
  const re = /(https?:\/\/[^\s<>()]+|www\.[^\s<>()]+)/gi;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const raw = m[0];
    const href = raw.startsWith('http') ? raw : `https://${raw}`;
    out.push(h('a', { class: 'feed-link', href, target: '_blank', rel: 'noopener', onclick: e => e.stopPropagation() }, raw));
    last = m.index + raw.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
// Tepki simgesi → etiket + renk (beğen düğmesi ve etiketi için)
const REACTION_META = {
  '👍': { label: 'Beğen', color: '#2563eb' }, '❤️': { label: 'Sevdim', color: '#e0245e' },
  '😂': { label: 'Güldüm', color: '#f7b125' }, '😮': { label: 'Şaşırdım', color: '#f7b125' },
  '😢': { label: 'Üzüldüm', color: '#f7b125' }, '👏': { label: 'Alkış', color: '#f7b125' },
  '🎉': { label: 'Kutlama', color: '#f7b125' },
};
const HEART_SVG = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 20.3s-7.2-4.4-9.1-8.9C1.5 8.1 3.5 4.6 7 4.6c2 0 3.4 1.1 4.1 2.3h1.8c.7-1.2 2.1-2.3 4.1-2.3 3.5 0 5.5 3.5 4.1 6.8-1.9 4.5-9.1 8.9-9.1 8.9z"/></svg>';
const SEND_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M3.4 20.4l17.4-7.5c.8-.3.8-1.5 0-1.8L3.4 3.6c-.7-.3-1.4.3-1.3 1l.9 5.3c.1.4.4.7.8.8l7.7 1.3-7.7 1.3c-.4.1-.7.4-.8.8l-.9 5.3c-.1.7.6 1.3 1.3 1z"/></svg>';
// Instagram tarzı 24px çizgi ikonlar (akış kartı alt çubuğu, paylaşım menüsü)
const IG = {
  heart: '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M12 20.3s-7.2-4.4-9.1-8.9C1.5 8.1 3.5 4.6 7 4.6c2 0 3.4 1.1 4.1 2.3h1.8c.7-1.2 2.1-2.3 4.1-2.3 3.5 0 5.5 3.5 4.1 6.8-1.9 4.5-9.1 8.9-9.1 8.9z"/></svg>',
  chat: '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M20.7 16.4A9 9 0 1 0 17 20l3.9 1-1-3.9-.2-.7z"/></svg>',
  send: '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M21.5 3 9.6 10.4"/><path d="M21.5 3 15 21l-5.4-10.6L2.5 7.8z"/></svg>',
  save: '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M19 21l-7-5.2L5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1z"/></svg>',
  more: '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><circle cx="5" cy="12" r="1.9"/><circle cx="12" cy="12" r="1.9"/><circle cx="19" cy="12" r="1.9"/></svg>',
  dl: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M5 20h14"/></svg>',
  copy: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg>',
  pin: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/></svg>',
  trash: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/></svg>',
  image: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-9 9"/></svg>',
  camera: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13.5" r="3.5"/></svg>',
};
// "34 dakika önce" (kısa: "34 dk") — Instagram gibi göreli zaman; bir haftadan eskiyse tarih
function ago(iso, short) {
  const t = iso ? new Date(iso).getTime() : NaN;
  if (!Number.isFinite(t)) return '';
  const s = Math.max(0, (Date.now() - t) / 1000);
  const f = (n, long, sh) => (short ? `${n} ${sh}` : `${n} ${long} önce`);
  if (s < 60) return short ? 'şimdi' : 'az önce';
  if (s < 3600) return f(Math.floor(s / 60), 'dakika', 'dk');
  if (s < 86400) return f(Math.floor(s / 3600), 'saat', 'sa');
  if (s < 7 * 86400) return f(Math.floor(s / 86400), 'gün', 'g');
  if (short && s < 60 * 86400) return f(Math.floor(s / 604800), 'hafta', 'hf');
  return fmtDate(iso);
}
const svgSpan = markup => { const s = document.createElement('span'); s.className = 'feed-ic'; s.innerHTML = markup; return s; };

export function renderFeed(container, ctx, opts = {}) {
  // Görünüm (Akış / Harita) Kişisel Ayarlar › Pano'dan seçilir; burada sabittir. Paylaşım gövdedeki kutudan yapılır.
  const view = opts.view === 'map' ? 'map' : 'feed';
  let posts = [];
  const body = h('div', { class: 'feed-body' });
  clear(container, body);

  let reactionList = ['👍', '❤️', '😂', '😮', '😢', '👏', '🎉'];   // sunucudan güncellenir
  // Tam ekran: akıştaki tüm resim + videolar ekrandaki sırayla (paylaşımıyla birlikte → sağ şeritte kalp / yorum / paylaş)
  const viewerItems = () => posts.flatMap(q => (q.media || []).filter(x => x.type === 'image' || x.type === 'video').map(x => ({ ...x, post: q })));
  const openAt = (m, p) => {
    const items = viewerItems();
    openViewer(items, Math.max(0, items.findIndex(x => x.post === p && x.path === m.path)), viewerActs);
  };
  const mediaEl = (m, p, plus = 0) => {
    if (m.type === 'audio') return h('audio', { class: 'feed-audio', src: fileUrl(m.path), controls: true, preload: 'none' });
    if (m.type === 'video') return h('button', { class: 'feed-media feed-vid', type: 'button', title: 'Tam ekran aç', onclick: () => openAt(m, p) },
      h('video', { src: videoUrl(m.path), preload: 'metadata', muted: true, playsinline: true, tabindex: -1 }), h('span', { class: 'feed-play' }, '▶'),
      plus ? h('span', { class: 'feed-mplus' }, `+${plus}`) : null);
    return h('button', { class: 'feed-media', type: 'button', title: 'Tam ekran aç', onclick: () => openAt(m, p) },
      h('img', { src: fileUrl(m.path, 1000), alt: '', loading: 'lazy' }), plus ? h('span', { class: 'feed-mplus' }, `+${plus}`) : null);
  };
  const isAdmin = () => ctx.user.master || ctx.user.modules.includes('admin');
  // Başkasının paylaşımını kimse silemez (yönetici / sistem sahibi dahil); sistem olaylarını yönetici kaldırabilir
  const canDelete = p => (p.system ? isAdmin() : p.author_id === ctx.user.id);
  const authorName = p => (p.system ? (ctx.meta?.company || 'Şirket') : (p.author_name || 'Kullanıcı'));
  const visualOf = p => (p.media || []).filter(m => m.type === 'image' || m.type === 'video');
  const totalOf = p => Object.values(p.reactions || {}).reduce((a, b) => a + b, 0);
  // Uzun metin 3 satır / 150 karakterde kesilir, "devamı" ile açılır
  const textBody = (p, lead) => {
    const t = p.text || '';
    const lines = t.split('\n');
    const long = t.length > 160 || lines.length > 3;
    const shown = long ? `${lines.slice(0, 3).join('\n').slice(0, 150).trimEnd()}… ` : t;
    const span = h('span', { class: 'feed-tx' });
    // ref_link'li (sistem) postlarda metin zaten tek link; kullanıcı metninde içindeki URL'leri linkle
    const fill = s => span.replaceChildren(...(p.ref_link ? [s] : linkify(s)));
    fill(shown);
    const more = long ? h('button', { class: 'feed-moretx', type: 'button', onclick: () => { fill(t); more.remove(); } }, 'devamı') : null;
    return [lead || null, p.ref_link ? h('a', { href: p.ref_link }, span) : span, more];
  };
  const postCard = p => {
    const badge = KIND_BADGE[p.kind] || KIND_BADGE.USER;
    const vis = visualOf(p), aud = (p.media || []).filter(m => m.type === 'audio');
    const sub = vis.length ? [badge[1], p.lat ? '📍 Konum' : null] : [ago(p.created_at), badge[1], p.lat ? '📍' : null];
    const who = h('div', { class: `feed-who ${vis.length ? 'over' : ''}` },
      h('span', { class: `feed-ring ${p.system ? 'sys' : ''}` },
        p.system ? h('img', { class: 'feed-ava', src: LOGO, alt: '' }) : avatar({ full_name: p.author_name, photo: p.author_photo }, 36)),
      h('div', { class: 'grow' }, h('b', null, authorName(p)), sub.some(Boolean) ? h('small', null, sub.filter(Boolean).join(' · ')) : null),
      h('button', { class: 'feed-more', type: 'button', title: 'Seçenekler', 'aria-label': 'Paylaşım seçenekleri', onclick: () => postMenu(p) }, svgSpan(IG.more)));
    const card = h('div', { class: `feed-post ${vis.length ? 'has-media' : 'text-only'}` },
      vis.length ? h('div', { class: 'feed-mwrap' },
        h('div', { class: `feed-medias n${Math.min(vis.length, 4)}` }, vis.slice(0, 4).map((m, k) => mediaEl(m, p, k === 3 && vis.length > 4 ? vis.length - 4 : 0))),
        who) : who,
      !vis.length && p.text ? h('div', { class: 'feed-text' }, textBody(p)) : null,
      aud.length ? h('div', { class: 'feed-auds' }, aud.map(m => mediaEl(m, p))) : null,
      footer(p, c => reCard(p, c), vis.length > 0));
    p._card = card;
    return card;
  };

  // Tepki (beğeni/kalp) + yorum ayağı; değişince kart yerinde yeniden çizilir (yorum açıklığı korunur)
  function reCard(p, oldCard) {
    const fresh = postCard(p);
    oldCard.replaceWith(fresh);
  }
  // Alt çubuk (Instagram): solda kalp + sayı (uzun bas / üzerine gel: diğer tepkiler), yorum + sayı, paylaş; sağda kaydet.
  // Medyalı paylaşımda altında "Ad metin… devamı", "N yorumun tümünü gör" ve "34 dakika önce".
  function footer(p, rerender, media) {
    const total = totalOf(p);
    const mine = p.my_reaction;
    const picker = h('div', { class: 'feed-picker' }, reactionList.map(em =>
      h('button', { class: 'feed-pick', type: 'button', title: (REACTION_META[em]?.label || em),
        onclick: () => { hidePicker(); doReact(p, em, rerender); } }, em)));
    let hideT, lpT, longPressed = false;
    const heart = h('button', { class: `feed-ib feed-heart ${mine ? 'on' : ''}`, type: 'button', title: mine ? 'Tepkiyi kaldır' : 'Beğen',
      onclick: () => { if (longPressed) { longPressed = false; return; } doReact(p, mine || '❤️', rerender); } },
      mine && mine !== '❤️' ? h('span', { class: 'feed-like-em' }, mine) : svgSpan(IG.heart));
    const showPicker = () => { clearTimeout(hideT); likeWrap.classList.add('show-picker'); };
    const hidePicker = () => likeWrap.classList.remove('show-picker');
    const likeWrap = h('div', { class: 'feed-like-wrap',
      onmouseenter: showPicker, onmouseleave: () => { hideT = setTimeout(hidePicker, 260); } }, picker, heart);
    heart.addEventListener('touchstart', () => { lpT = setTimeout(() => { longPressed = true; showPicker(); }, 420); }, { passive: true });
    heart.addEventListener('touchend', () => clearTimeout(lpT));
    heart.addEventListener('contextmenu', e => { e.preventDefault(); showPicker(); });
    const seeWho = canSeeReactors(p) && total;
    const others = Object.entries(p.reactions || {}).filter(([em]) => em !== '❤️').sort((a, b) => b[1] - a[1]).slice(0, 2).map(e => e[0]);
    const likeN = total ? h(seeWho ? 'button' : 'span', { class: `feed-n ${seeWho ? 'link' : ''}`, type: seeWho ? 'button' : null,
      title: seeWho ? 'Kimler beğendi' : null, onclick: seeWho ? () => showReactors(p) : null },
      others.length ? h('span', { class: 'feed-rbubbles' }, others.map(em => h('span', { class: 'feed-rb' }, em))) : null, String(total)) : null;
    const cmt = h('button', { class: 'feed-ib', type: 'button', title: 'Yorum yap', onclick: () => toggleComments(p, rerender, true) }, svgSpan(IG.chat));
    const cmtN = p.comment_count ? h('button', { class: 'feed-n link', type: 'button', title: 'Yorumlar', onclick: () => toggleComments(p, rerender) }, String(p.comment_count)) : null;
    const share = h('button', { class: 'feed-ib', type: 'button', title: 'Paylaş', onpointerdown: () => prefetchShare(p), onclick: e => sharePost(p, e.currentTarget) }, svgSpan(IG.send));
    const save = h('button', { class: `feed-ib feed-save ${p.saved ? 'on' : ''}`, type: 'button', title: p.saved ? 'Kaydedilenlerden çıkar' : 'Favorilere kaydet',
      onclick: e => toggleSave(p, e.currentTarget) }, svgSpan(IG.save));
    const bar = h('div', { class: 'feed-bar' }, h('div', { class: 'feed-bar-l' }, likeWrap, likeN, cmt, cmtN, share), save);
    const cap = media && p.text ? h('div', { class: 'feed-cap' }, textBody(p, h('b', null, authorName(p), ' '))) : null;
    const allC = p.comment_count && !p._open ? h('button', { class: 'feed-cmore', type: 'button', onclick: () => toggleComments(p, rerender, true) },
      p.comment_count === 1 ? '1 yorumu gör' : `${p.comment_count} yorumun tümünü gör`) : null;
    const time = media ? h('div', { class: 'feed-time', title: fmtDateTime(p.created_at) }, ago(p.created_at)) : null;
    const box = h('div', { class: 'feed-comments' });
    if (p._open) renderComments(p, box, rerender);
    return h('div', { class: 'feed-foot' }, bar, cap, allC, time, box);
  }

  // ---- Kaydet (favoriler), paylaş, paylaşım menüsü ----
  const paintSave = (btn, p) => { if (!btn) return; btn.classList.toggle('on', !!p.saved); btn.title = p.saved ? 'Kaydedilenlerden çıkar' : 'Favorilere kaydet'; };
  async function toggleSave(p, btn) {
    btn ??= p._card?.querySelector('.feed-save');
    const was = !!p.saved; p.saved = !was; paintSave(btn, p);
    try {
      const r = await api.post(`/api/feed/${p.id}/save`);
      p.saved = r.saved; paintSave(btn, p);
      toast(r.saved ? 'Kaydedilenlere eklendi' : 'Kaydedilenlerden çıkarıldı');
    } catch (err) { p.saved = was; paintSave(btn, p); toastError(err); }
  }
  const shareText = p => [authorName(p), p.text].filter(Boolean).join(': ').slice(0, 500);
  const prefetchShare = p => { if (navigator.share) visualOf(p).slice(0, 4).filter(m => m.type === 'image').forEach(m => shareFile(m).catch(() => {})); };
  const sharePost = (p, btn) => deviceShare(visualOf(p).slice(0, 4), shareText(p), btn, () => {
    const v = visualOf(p);
    if (v.length) { downloadMedia(v[0]); toast('Bu cihazda paylaşma menüsü yok; dosya indirildi'); } else copyText(shareText(p));
  });
  function postMenu(p) {
    const vis = visualOf(p);
    actionSheet(authorName(p), [
      { ico: IG.save, label: p.saved ? 'Kaydedilenlerden çıkar' : 'Favorilere kaydet', run: () => toggleSave(p) },
      { ico: IG.send, label: 'Paylaş', run: () => sharePost(p) },
      vis.length ? { ico: IG.dl, label: vis.length > 1 ? `Tümünü indir (${vis.length})` : 'İndir', run: () => vis.forEach((m, k) => setTimeout(() => downloadMedia(m), k * 450)) } : null,
      p.text ? { ico: IG.copy, label: 'Metni kopyala', run: () => copyText(p.text) } : null,
      p.lat && p.lng ? { ico: IG.pin, label: 'Konumu haritada aç', run: () => window.open(`https://www.google.com/maps?q=${p.lat},${p.lng}`, '_blank', 'noopener') } : null,
      canSeeReactors(p) && totalOf(p) ? { ico: IG.heart, label: 'Kimler beğendi', run: () => showReactors(p) } : null,
      canDelete(p) ? { ico: IG.trash, label: 'Sil', danger: true, run: () => del(p) } : null,
    ].filter(Boolean));
  }

  async function doReact(p, emoji, rerender) {
    const prev = p.my_reaction;
    const c = { ...(p.reactions || {}) };
    if (prev) { c[prev] = (c[prev] || 1) - 1; if (!c[prev]) delete c[prev]; }
    const next = prev === emoji ? null : emoji;
    if (next) c[next] = (c[next] || 0) + 1;
    p.reactions = c; p.my_reaction = next;
    rerender(p._card);
    try { await api.post(`/api/feed/${p.id}/react`, { emoji }); }
    catch (err) { toastError(err); }
  }

  // Paylaşım sahibi (ve yönetici) kimlerin tepki verdiğini görür
  const canSeeReactors = p => !p.system && (p.author_id === ctx.user.id || isAdmin());
  async function showReactors(p) {
    let d;
    try { d = await api.get(`/api/feed/${p.id}/reactions`); } catch (e) { return toastError(e); }
    const list = d.reactions || [];
    const byEmoji = {};
    list.forEach(r => { byEmoji[r.emoji] = (byEmoji[r.emoji] || 0) + 1; });
    let cur = 'all';
    const box = h('div', { class: 'feed-rx-list' });
    const drawList = () => clear(box, list.filter(r => cur === 'all' || r.emoji === cur).map(r => h('div', { class: 'feed-rx-row' },
      h('span', { class: 'feed-rx-ava' }, avatar({ full_name: r.full_name, photo: r.photo }, 38), h('span', { class: 'feed-rx-em' }, r.emoji)),
      h('div', { class: 'grow' }, h('b', null, r.full_name), h('small', { class: 'muted' }, fmtDateTime(r.created_at))))));
    const tabs = segmented([['all', `Tümü ${list.length}`], ...Object.entries(byEmoji).sort((a, b) => b[1] - a[1]).map(([em, n]) => [em, `${em} ${n}`])],
      'all', v => { cur = v; drawList(); }, { tabs: true });
    drawList();
    modal({ title: 'Tepki verenler', body: h('div', { class: 'feed-rx' }, tabs, list.length ? box : h('div', { class: 'empty small' }, 'Henüz tepki yok.')),
      actions: [{ label: 'Kapat' }] });
  }

  function toggleComments(p, rerender, open) {
    p._open = open ? true : !p._open;
    rerender(p._card);
  }

  // Yorumlar (Instagram tarzı): her yorumda kalp + sayı, "Yanıtla"; yanıtlar ana yorumun altında girintili (tek seviye),
  // 2'den çok yanıt "— N yanıtı gör" ile katlanır. Kalp ve yanıt hedefi yerinde güncellenir (yazılan metin kaybolmaz).
  async function renderComments(p, box, rerender) {
    clear(box, h('div', { class: 'small muted' }, 'Yükleniyor…'));
    let list = p._comments;
    if (!list) {
      try { list = p._comments = (await api.get(`/api/feed/${p.id}/comments`)).comments; }
      catch (err) { return clear(box, h('div', { class: 'small muted' }, err.message)); }
      p.comment_count = list.filter(c => !c.deleted).length;
    }
    p._showReplies ??= new Set();
    const input = h('input', { class: 'feed-cinput', type: 'text', placeholder: 'Yorum yaz…', maxlength: 1000 });
    const replyChip = h('div', { class: 'feed-replying', hidden: true });
    const setReply = target => {   // target: { id: ana yorum, name, mention }
      p._reply = target || null;
      if (!target) { replyChip.hidden = true; input.placeholder = 'Yorum yaz…'; return; }
      clear(replyChip, h('span', null, '↳ Yanıtlanan: ', h('b', null, target.name || 'Kullanıcı')),
        h('button', { class: 'feed-replying-x', type: 'button', title: 'Yanıtı iptal et', onclick: () => setReply(null) }, '✕'));
      replyChip.hidden = false; input.placeholder = 'Yanıt yaz…';
      if (target.mention && !input.value.trim()) input.value = `@${target.mention} `;
      input.focus();
    };
    const send = async () => {
      const text = input.value.trim(); if (!text) return;
      const parent = p._reply?.id || null;
      input.value = '';
      try {
        const r = await api.post(`/api/feed/${p.id}/comments`, { text, parent_id: parent });
        p._comments = [...(p._comments || []), { id: r.id, user_id: ctx.user.id, parent_id: parent, text, created_at: new Date().toISOString(),
          author_name: ctx.user.full_name, author_photo: ctx.user.photo, like_count: 0, liked: false }];
        p.comment_count = (p.comment_count || 0) + 1;
        if (parent) p._showReplies.add(parent);
        p._reply = null;
        rerender(p._card);
      } catch (err) { input.value = text; toastError(err); }
    };
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); send(); }
      else if (e.key === 'Escape' && p._reply) { e.stopPropagation(); setReply(null); }
    });

    const names = [...new Set(list.map(c => c.author_name).filter(Boolean))].sort((x, y) => y.length - x.length);
    const textOf = t => {   // baştaki @Ad vurgulu
      const n = t.startsWith('@') ? names.find(x => t.startsWith(`@${x}`)) : null;
      return n ? [h('b', { class: 'feed-mention' }, `@${n}`), t.slice(n.length + 1)] : t;
    };
    const row = (c, isReply) => {
      if (c.deleted) {
        return h('div', { class: 'feed-cmt deleted' }, h('span', { class: 'feed-cava-ph' }),
          h('div', { class: 'feed-cmain' }, h('div', { class: 'feed-cbody' }, h('i', { class: 'muted' }, 'Bu yorum silindi'))));
      }
      const mine = c.user_id === ctx.user.id;
      const likeN = h('span', { class: 'feed-clike-n' });
      const likesLink = h('button', { class: 'feed-cact', type: 'button', hidden: true, onclick: () => showCommentLikers(c) });
      const heart = h('button', { class: 'feed-clike', type: 'button' }, svgSpan(HEART_SVG));
      const paint = () => {
        heart.classList.toggle('on', !!c.liked);
        heart.title = c.liked ? 'Beğeniyi kaldır' : 'Beğen';
        likeN.textContent = c.like_count ? String(c.like_count) : '';
        likesLink.textContent = `${c.like_count} beğeni`;
        likesLink.hidden = !(mine && c.like_count);   // yorum sahibi kimlerin beğendiğini görür
      };
      heart.addEventListener('click', async () => {
        const was = !!c.liked;
        c.liked = !was; c.like_count = Math.max(0, (c.like_count || 0) + (was ? -1 : 1)); paint();
        if (c.liked) { heart.classList.remove('pop'); void heart.offsetWidth; heart.classList.add('pop'); }
        try { const r = await api.post(`/api/feed/comments/${c.id}/like`); c.liked = r.liked; c.like_count = r.like_count; paint(); }
        catch (err) { c.liked = was; c.like_count = Math.max(0, (c.like_count || 0) + (was ? 1 : -1)); paint(); toastError(err); }
      });
      paint();
      return h('div', { class: `feed-cmt ${isReply ? 'reply' : ''}` },
        avatar({ full_name: c.author_name, photo: c.author_photo }, isReply ? 26 : 32),
        h('div', { class: 'feed-cmain' },
          h('div', { class: 'feed-cbody' },
            h('div', { class: 'feed-cname' }, c.author_name || 'Kullanıcı'),
            h('div', { class: 'feed-ctext' }, textOf(c.text || ''))),
          h('div', { class: 'feed-cmeta' }, h('span', { class: 'muted', title: fmtDateTime(c.created_at) }, ago(c.created_at, true)), likesLink,
            h('button', { class: 'feed-cact', type: 'button', onclick: () => setReply({ id: c.parent_id || c.id, name: c.author_name,
              mention: isReply && !mine ? c.author_name : null }) }, 'Yanıtla'),
            mine ? h('button', { class: 'feed-cdel', type: 'button', onclick: async () => {
              try {
                await api.del(`/api/feed/comments/${c.id}`);
                p.comment_count = Math.max(0, (p.comment_count || 1) - 1);
                p._comments = null;   // yanıtı olan yorum "silindi" yer tutucusuna döner → listeyi sunucudan tazele
                rerender(p._card);
              } catch (err) { toastError(err); }
            } }, 'Sil') : null)),
        h('div', { class: 'feed-cside' }, heart, likeN));
    };
    const ids = new Set(list.map(c => c.id));
    const kids = {};
    list.forEach(c => { if (c.parent_id && ids.has(c.parent_id)) (kids[c.parent_id] ??= []).push(c); });
    const thread = c => {
      const rs = kids[c.id] || [];
      const wrap = h('div', { class: 'feed-thread' }, row(c, false));
      if (!rs.length) return wrap;
      const repliesBox = h('div', { class: 'feed-replies' });
      const many = rs.length > 2;
      const toggle = h('button', { class: 'feed-more-replies', type: 'button' });
      const fill = () => {
        const open = !many || p._showReplies.has(c.id);
        clear(repliesBox, open ? rs.map(r => row(r, true)) : null);
        toggle.textContent = open ? 'Yanıtları gizle' : `${rs.length} yanıtı gör`;
      };
      toggle.addEventListener('click', () => { p._showReplies.has(c.id) ? p._showReplies.delete(c.id) : p._showReplies.add(c.id); fill(); });
      fill();
      wrap.append(...(many ? [toggle] : []), repliesBox);
      return wrap;
    };
    clear(box,
      h('div', { class: 'feed-clist' }, list.filter(c => !c.parent_id || !ids.has(c.parent_id)).map(thread)),
      replyChip,
      h('div', { class: 'feed-cadd' }, avatar(ctx.user, 32),
        h('div', { class: 'feed-cinput-wrap' }, input,
          h('button', { class: 'feed-csend', type: 'button', title: 'Gönder', onclick: send }, svgSpan(SEND_SVG)))));
    if (p._reply) setReply(p._reply);
  }

  async function showCommentLikers(c) {
    let d;
    try { d = await api.get(`/api/feed/comments/${c.id}/likes`); } catch (e) { return toastError(e); }
    const rows = (d.likes || []).map(r => h('div', { class: 'feed-rx-row' },
      h('span', { class: 'feed-rx-ava' }, avatar({ full_name: r.full_name, photo: r.photo }, 38), h('span', { class: 'feed-rx-em' }, '❤️')),
      h('div', { class: 'grow' }, h('b', null, r.full_name), h('small', { class: 'muted' }, fmtDateTime(r.created_at)))));
    modal({ title: 'Yorumu beğenenler', body: h('div', { class: 'feed-rx' }, rows.length ? h('div', { class: 'feed-rx-list' }, rows) : h('div', { class: 'empty small' }, 'Henüz beğeni yok.')),
      actions: [{ label: 'Kapat' }] });
  }

  let onlySaved = false;
  // Pano kutusu bağlamında (opts.headActions) Paylaş + Canlı + Kaydedilenler düğmeleri kutu BAŞLIĞINDA, tek kapsülde
  // durur ve gövdedeki büyük composer çubuğu gizlenir (yer kaplamaz). Başlıkta slot yoksa (bağımsız akış) eskisi gibi
  // composer gövdenin üstünde, Canlı/Kaydedilenler onun yanında kalır.
  const shareBtn = () => h('button', { class: 'feed-sharebtn', type: 'button', title: 'Bir şeyler paylaş',
    onclick: () => compose(ctx) }, svgSpan(IG.image), 'Paylaş');
  const liveBtn = () => h('button', { class: 'feed-livebtn', type: 'button', title: 'Canlı yayın başlat', 'aria-label': 'Canlı yayın başlat',
    onclick: () => import('./live.js').then(m => m.startBroadcast(ctx)) }, h('span', { class: 'feed-live-dot' }), 'Canlı');
  const savedBtn = () => h('button', { class: 'feed-savedbtn', type: 'button', title: 'Kaydedilenler', 'aria-label': 'Kaydedilenler',
    onclick: () => { onlySaved = true; load(); } }, svgSpan(IG.save));
  const topBar = () => {
    if (opts.headActions) {   // Paylaş + Canlı + Kaydedilenler kutu başlığına (tek kapsül); composer gövdede gösterilmez
      clear(opts.headActions, onlySaved ? null : h('div', { class: 'db-acts-pill' }, shareBtn(), liveBtn(), savedBtn()));
      return onlySaved
        ? h('div', { class: 'feed-top' }, h('div', { class: 'feed-saved-h' }, svgSpan(IG.save), h('b', null, 'Kaydedilenler'),
          h('button', { class: 'btn sm', type: 'button', onclick: () => { onlySaved = false; load(); } }, 'Tüm paylaşımlar')))
        : null;
    }
    return h('div', { class: 'feed-top' },
      onlySaved
        ? h('div', { class: 'feed-saved-h' }, svgSpan(IG.save), h('b', null, 'Kaydedilenler'),
          h('button', { class: 'btn sm', type: 'button', onclick: () => { onlySaved = false; load(); } }, 'Tüm paylaşımlar'))
        : h('button', { class: 'feed-composer', type: 'button', onclick: () => compose(ctx) },
          avatar(ctx.user, 36),
          h('span', { class: 'feed-composer-pill' }, 'Bir şeyler paylaş…'),
          h('span', { class: 'feed-composer-ic', title: 'Foto / Video / Ses' }, svgSpan(IG.image))),
      onlySaved ? null : liveBtn(),
      onlySaved ? null : savedBtn());
  };

  // Şu an canlı yayında olanlar: akışın en üstünde halkalı avatarlar (Instagram hikâye şeridi gibi); dokununca katıl
  const liveBox = h('div', { class: 'feed-lives', hidden: true });
  async function drawLives() {
    let list = [];
    try { list = await api.get('/api/live/active'); } catch { /* */ }
    list = list.filter(x => x.user_id !== ctx.user.id);
    liveBox.hidden = !list.length;
    clear(liveBox, list.map(x => h('a', { class: 'feed-live', href: `#/live/${x.id}`, title: x.title || `${x.name} canlı yayında` },
      h('span', { class: 'feed-live-ring' }, avatar({ full_name: x.name, photo: x.photo }, 52), h('span', { class: 'feed-live-tag' }, 'CANLI')),
      h('span', { class: 'feed-live-name' }, x.name.split(' ')[0]))));
  }
  const onLive = () => { if (container.isConnected) drawLives(); };
  window.addEventListener('caymaz:live', onLive);
  onLeave(() => window.removeEventListener('caymaz:live', onLive));

  // Arka planda süren paylaşım yüklemeleri: form hemen kapanır, akışın üstünde ilerleme çubuğu
  const upBox = h('div', { class: 'feed-uploads' });
  const upRows = new Map();
  function drawUploads() {
    for (const [u, r] of upRows) if (!uploads.has(u)) { r.el.remove(); upRows.delete(u); }
    for (const u of uploads) {
      let r = upRows.get(u);
      if (!r) {
        const th = u.thumb ? (u.thumbType === 'video' ? h('video', { class: 'feed-up-th', src: `${u.thumb}#t=0.1`, muted: true, playsinline: true, preload: 'metadata' })
          : h('img', { class: 'feed-up-th', src: u.thumb, alt: '' })) : h('span', { class: 'feed-up-th ico' }, u.audio ? '🎤' : '✎');
        r = { title: h('div', { class: 'feed-up-t' }), sub: h('small', { class: 'muted' }), fill: h('i'), acts: h('div', { class: 'feed-up-acts' }) };
        r.bar = h('div', { class: 'feed-up-bar' }, r.fill);
        r.el = h('div', { class: 'feed-up' }, th, h('div', { class: 'grow' }, r.title, r.bar, r.sub), r.acts);
        upRows.set(u, r); upBox.prepend(r.el);
      }
      r.el.className = `feed-up ${u.state} ${u.state === 'up' && !u.pct ? 'prep' : ''}`;
      r.title.textContent = u.state === 'err' ? 'Paylaşım yüklenemedi' : u.state === 'done' ? 'Paylaşıldı ✓'
        : u.pct >= 100 ? 'İşleniyor…' : u.pct > 0 ? `Gönderi yükleniyor… %${u.pct}` : 'Hazırlanıyor…';
      r.fill.style.width = `${u.state === 'done' ? 100 : Math.max(4, u.pct)}%`;
      r.bar.hidden = u.state === 'err';
      r.sub.textContent = u.state === 'err' ? (u.err || '') : (u.text || '');
      r.sub.hidden = !r.sub.textContent;
      clear(r.acts, u.state === 'err' ? [h('button', { class: 'btn sm primary', type: 'button', onclick: () => u.retry() }, 'Tekrar dene'),
        h('button', { class: 'btn sm', type: 'button', onclick: () => u.cancel() }, 'Vazgeç')] : null);
    }
  }
  const onUp = () => { if (!container.isConnected) { upListeners.delete(onUp); return; } drawUploads(); };
  upListeners.add(onUp);

  // Sonsuz kaydırma: 10'ar paylaşım; liste sonuna yaklaşınca sonraki sayfa
  const PAGE = 10;
  let hasMore = false, loadingMore = false, io = null;
  const sentinel = h('div', { class: 'feed-sentinel', hidden: true }, h('span', { class: 'feed-spin' }));
  const pageUrl = extra => `/api/feed?limit=${PAGE}${onlySaved ? '&saved=1' : ''}${extra || ''}`;
  function watchEnd() {
    io?.disconnect();
    if (!hasMore || !('IntersectionObserver' in window)) return;
    const root = /(auto|scroll)/.test(getComputedStyle(body).overflowY) ? body : null;   // pano kutucuğunda liste kendi içinde kayar
    io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) loadMore(); }, { root, rootMargin: '0px 0px 700px 0px' });
    io.observe(sentinel);
  }
  async function loadMore() {
    if (!hasMore || loadingMore || !posts.length) return;
    loadingMore = true;
    const last = posts[posts.length - 1];
    try {
      const d = await api.get(pageUrl(`&before_id=${last.id}&before_at=${encodeURIComponent(last.created_at)}`));
      const have = new Set(posts.map(x => x.id));
      const more = (d.posts || []).filter(x => !have.has(x.id));
      hasMore = (d.posts || []).length >= PAGE;
      posts = [...posts, ...more];
      await socialMore(hasMore ? posts[posts.length - 1].created_at : '');
      const list = body.querySelector('.feed-list');
      if (list) weave(list, more, !hasMore);
    } catch { /* bir sonraki kaydırmada yeniden denenir */ }
    loadingMore = false;
    sentinel.hidden = !hasMore;
    watchEnd();   // yeniden gözle: kısa sayfada sentinel hâlâ görünüyorsa hemen sonraki sayfa
  }

  let drawMap;
  // Kişisel sosyal medya paylaşımları (Kişisel Ayarlar › Sosyal Medya): yalnızca bu kullanıcının ekranında, tarihine göre
  // şirket paylaşımlarının arasına karışır. Şirket sırası bozulmaz; her şirket kartından önce ondan yeni olanlar yerleşir.
  let social = [], socialOn = true, socialFloor = '';
  async function socialMore(after) {   // (after, socialFloor] aralığını getirir; after boşsa kalan en eski 50
    if (!socialOn || onlySaved || view === 'map') return;
    try {
      const q = `${after ? `&after=${encodeURIComponent(after)}` : ''}${socialFloor ? `&before=${encodeURIComponent(socialFloor)}` : ''}`;
      const d = await api.get(`/api/social/feed?limit=50${q}`);
      socialOn = d.on !== false;
      const have = new Set(social.map(x => x.id));
      social.push(...(d.posts || []).filter(x => !have.has(x.id)));
      if (after) socialFloor = after;
      else socialOn = false;   // hepsi alındı
    } catch { /* sosyal akış isteğe bağlı; hata akışı bozmaz */ }
  }
  function weave(list, items, final) {
    const q = social.filter(x => !x._placed).sort((a, b) => (b.posted_at || '').localeCompare(a.posted_at || ''));
    let i = 0;
    const put = () => { list.append(socialCard(q[i])); q[i]._placed = true; i++; };
    for (const p of items) {
      while (i < q.length && (q[i].posted_at || '') > (p.created_at || '')) put();
      list.append(postCard(p));
    }
    if (final) while (i < q.length) put();
  }
  const SOC_NAME = { rss: 'RSS', youtube: 'YouTube', bluesky: 'Bluesky', mastodon: 'Mastodon', instagram: 'Instagram', facebook: 'Facebook', x: 'X', tiktok: 'TikTok' };
  function socialCard(sp) {
    const text = sp.text || '';
    const long = text.length > 220;
    const tx = h('span', { class: 'feed-tx' }, long ? `${text.slice(0, 200).trimEnd()}… ` : text);
    const more = long ? h('button', { class: 'feed-moretx', type: 'button', onclick: () => { tx.textContent = text; more.remove(); } }, 'devamı') : null;
    const open = sp.url ? { href: sp.url, target: '_blank', rel: 'noopener noreferrer' } : null;
    return h('div', { class: 'feed-post soc-post' },
      h('div', { class: 'feed-who' },
        sp.avatar ? h('img', { class: 'feed-ava soc-av', src: sp.avatar, alt: '', referrerpolicy: 'no-referrer', onerror: e => e.target.replaceWith(socialBadge(sp.provider)) }) : socialBadge(sp.provider),
        h('div', { class: 'grow' }, h('b', null, sp.display_name || sp.handle),
          h('small', null, [SOC_NAME[sp.provider] || sp.provider, ago(sp.posted_at)].filter(Boolean).join(' · '))),
        h('a', { class: 'soc-only', href: '#/settings/social', title: 'Bu paylaşımı yalnızca siz görüyorsunuz · Sosyal medya ayarları' }, '🔒 Yalnız siz')),
      sp.media ? h('a', { class: `soc-media ${sp.media_kind === 'video' ? 'vid' : ''}`, ...open },
        h('img', { src: sp.media, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer', onerror: e => e.target.parentElement.remove() }),
        sp.media_kind === 'video' ? h('span', { class: 'feed-play' }, '▶') : null) : null,
      text ? h('div', { class: 'feed-text' }, tx, more) : null,
      sp.url ? h('div', { class: 'soc-foot' }, h('a', { ...open }, 'Kaynağında aç ↗')) : null);
  }

  function draw() {
    if (view === 'map') return drawMap();
    social.forEach(x => { x._placed = false; });
    let list = null;
    if (posts.length || (social.length && !onlySaved)) {
      list = h('div', { class: 'feed-list' });
      if (onlySaved) posts.forEach(p => list.append(postCard(p))); else weave(list, posts, !hasMore);
    }
    list = list || h('div', { class: 'feed-empty muted' }, onlySaved ? 'Henüz kaydettiğin paylaşım yok. Paylaşımların altındaki kaydet simgesiyle favorilerine ekleyebilirsin.'
        : 'Henüz paylaşım yok. İlk paylaşımı sen ekle!');
    sentinel.hidden = !hasMore;
    clear(body, onlySaved ? null : liveBox, topBar(), onlySaved ? null : upBox, list, sentinel);
    if (!onlySaved) drawLives();
    drawUploads();
    requestAnimationFrame(watchEnd);
  }
  drawMap = async () => {
    clear(body, h('div', { class: 'feed-map' }));
    const el = body.querySelector('.feed-map');
    const maps = await loadMaps().catch(() => null);
    const located = posts.filter(p => p.lat && p.lng);
    if (!maps) return clear(body, h('div', { class: 'card empty' }, 'Harita için Google Haritalar anahtarı gerekli (Program Ayarları › Entegrasyonlar).'));
    if (!located.length) return clear(body, h('div', { class: 'card empty' }, 'Konumlu paylaşım yok.'));
    const map = new maps.Map(el, { mapTypeId: 'roadmap', mapTypeControl: true, streetViewControl: false });
    const bounds = new maps.LatLngBounds();
    for (const p of located) {
      const pos = { lat: p.lat, lng: p.lng }; bounds.extend(pos);
      const thumb = (p.media || []).find(m => m.type === 'image');
      const mk = new maps.Marker({ position: pos, map, title: p.text || '' });
      const info = new maps.InfoWindow({ content: h('div', { style: 'max-width:200px' },
        thumb ? h('img', { src: fileUrl(thumb.path, 200), style: 'width:100%;border-radius:6px', alt: '' }) : null,
        h('div', null, (p.text || '').slice(0, 120))) });
      mk.addListener('click', () => info.open(map, mk));
    }
    map.fitBounds(bounds, 48);
    if (located.length === 1) map.setZoom(15);
  };

  async function del(p) {
    if (!await confirmDialog('Paylaşımı sil', 'Bu paylaşım silinsin mi?', { okLabel: 'Sil', danger: true })) return;
    try {
      await api.del(`/api/feed/${p.id}`);
      posts = posts.filter(x => x !== p);
      p._card?.remove();
      if (!posts.length) draw();
      toast('Paylaşım silindi');
    } catch (err) { toastError(err); }
  }
  async function load() {
    try {
      const d = await api.get(view === 'map' ? '/api/feed?located=1&limit=300' : pageUrl());
      posts = d.posts; if (Array.isArray(d.reactions) && d.reactions.length) reactionList = d.reactions;
      hasMore = view !== 'map' && posts.length >= PAGE;
      social = []; socialOn = true; socialFloor = '';
      await socialMore(hasMore ? posts[posts.length - 1].created_at : '');
      draw();
      if (!onlySaved) markSeen();
    } catch (err) { clear(body, h('div', { class: 'card empty' }, err.message)); }
  }
  // Yeni paylaşım anında: mevcut kartlara (açık yorum, yazılan metin) dokunmadan yenileri en üste ekle
  async function addNew() {
    if (view === 'map') return load();
    if (onlySaved) return;
    const top = posts.reduce((m, x) => Math.max(m, x.id || 0), 0);
    if (!top) return load();
    let d;
    try { d = await api.get(`/api/feed?after=${top}&limit=60`); } catch { return; }
    const have = new Set(posts.map(x => x.id));   // aynı anda iki olay (kendi yüklemesi + canlı kanal) aynı paylaşımı iki kez eklemesin
    const fresh = (d.posts || []).filter(x => x.id > top && !have.has(x.id));
    if (!fresh.length) return;
    const list = body.querySelector('.feed-list');
    if (!list) return load();
    posts = [...fresh, ...posts];
    for (const x of fresh.slice().reverse()) {   // en yeni en üstte kalsın
      const card = postCard(x);
      card.classList.add('feed-fresh');
      list.prepend(card);
    }
    markSeen();
  }
  // Ana ekranda görüldü: yeni paylaşım bildirimi kalkar (sekme arka plandaysa görünür olunca)
  let pendingSeen = 0;
  function markSeen() {
    const top = posts.reduce((m, p) => Math.max(m, p.id || 0), 0);
    if (!top || !container.isConnected || view === 'map') return;
    if (document.visibilityState !== 'visible') { pendingSeen = top; return; }
    pendingSeen = 0;
    api.post('/api/feed/seen', { last_id: top }).then(() => window.dispatchEvent(new Event('caymaz:feed-seen'))).catch(() => {});
  }
  const onVisible = () => {
    if (document.visibilityState !== 'visible' || !container.isConnected) return;
    if (pendingSeen) markSeen();
    if (view === 'feed') addNew();
  };
  const onFeed = () => { if (container.isConnected) addNew(); };
  window.addEventListener('caymaz:feed', onFeed);
  document.addEventListener('visibilitychange', onVisible);
  onLeave(() => { window.removeEventListener('caymaz:feed', onFeed); document.removeEventListener('visibilitychange', onVisible); upListeners.delete(onUp); io?.disconnect(); });
  // Tam ekran görüntüleyicinin sağ şeridi akıştaki aynı işlemleri kullanır; değişiklik akıştaki karta da yansır
  const refreshCard = p => { if (p._card?.isConnected) reCard(p, p._card); };
  const viewerActs = {
    company: () => ctx.meta?.company || 'Şirket',
    reactions: () => reactionList,
    react: (p, em) => doReact(p, em, () => refreshCard(p)),
    comments: (p, box, after) => renderComments(p, box, () => { refreshCard(p); after(); }),
    canSeeReactors: p => canSeeReactors(p),
    showReactors: p => showReactors(p),
    save: p => toggleSave(p),
  };
  // Pano dakikalık yenilemesi: kullanıcı yorum yazıyor / açık yorum varsa yalnız yenileri ekle, yoksa tam yenile
  const busy = () => posts.some(p => p._open) || body.contains(document.activeElement);
  load();
  // ikinci sayfaya inilmişse tam yenileme kaydırmayı sıfırlamasın: yalnız yeniler eklenir
  return { reload: () => (busy() || posts.length > PAGE || onlySaved ? addNew() : load()) };
}

// Tam ekran medya görüntüleyici (TikTok / Reels tarzı):
//  · yukarı / aşağı kaydırınca parmağı izleyerek bir sonrakine KAYARAK geçer (tekerlek, ok tuşları, ▲▼ de aynı)
//  · iki parmakla (ya da Ctrl+tekerlek / izleme dörtgeni) yakınlaştırma, çift dokunuşla 2,5× ↔ 1×, büyükken sürükleyerek gezme
//  · sağ şerit: paylaşan, kalp + sayı (uzun bas: diğer tepkiler), yorumlar, cihazın paylaşma menüsü, indir
//  · alt sol: paylaşan adı + zaman + metin
const SVG = {
  heart: '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M12 21s-7.5-4.6-9.6-9.3C.9 8.3 3 4.5 6.7 4.5c2.1 0 3.6 1.2 4.3 2.4h2c.7-1.2 2.2-2.4 4.3-2.4 3.7 0 5.8 3.8 4.3 7.2C19.5 16.4 12 21 12 21z" fill="currentColor"/></svg>',
  chat: '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M12 3.5c5 0 9 3.4 9 7.7s-4 7.7-9 7.7c-1 0-2-.1-2.9-.4L4.4 20.4l1.3-3.7C4 15.3 3 13.4 3 11.2 3 6.9 7 3.5 12 3.5z" fill="currentColor"/><circle cx="8" cy="11.3" r="1.3" fill="#111"/><circle cx="12" cy="11.3" r="1.3" fill="#111"/><circle cx="16" cy="11.3" r="1.3" fill="#111"/></svg>',
  share: '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M13.5 4.3v4.1C6.6 9.2 3.6 13.6 3 19.6c2.3-3.2 5.6-4.8 10.5-4.8v4.1l7.6-7.3z" fill="currentColor"/></svg>',
  dl: '<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M5 20h14"/></svg>',
  save: '<svg viewBox="0 0 24 24" width="28" height="28"><path d="M6.2 3h11.6c.7 0 1.2.5 1.2 1.2V21l-7-5.2L5 21V4.2C5 3.5 5.5 3 6.2 3z" fill="currentColor"/></svg>',
};
const ico = markup => { const s = document.createElement('span'); s.className = 'fv-ic'; s.innerHTML = markup; return s; };
const shareFiles = new Map();   // dosya yolu → File (paylaşım menüsü kullanıcı dokunuşuyla hemen açılabilsin diye önceden indirilir)
async function shareFile(m) {
  if (shareFiles.has(m.path)) return shareFiles.get(m.path);
  const r = await fetch(fileUrl(m.path), { credentials: 'same-origin' });
  if (!r.ok) throw new Error('Dosya alınamadı');
  const b = await r.blob();
  const f = new File([b], m.path.split('/').pop() || 'paylasim', { type: b.type || (m.type === 'video' ? 'video/mp4' : 'image/jpeg') });
  shareFiles.set(m.path, f);
  if (shareFiles.size > 12) shareFiles.delete(shareFiles.keys().next().value);
  return f;
}

// Cihazın paylaşma menüsü (WhatsApp, Mesajlar, Posta…): medya dosyalarının kendisi + metin gönderilir
async function deviceShare(mediaList, text, btn, onNoShare) {
  if (navigator.share) {
    let files = mediaList.map(m => shareFiles.get(m.path));
    try {
      if (files.some(f => !f)) {
        btn?.classList.add('busy');
        files = await Promise.all(mediaList.map(m => shareFile(m).catch(() => null)));
        btn?.classList.remove('busy');
      }
      files = files.filter(Boolean);
      if (files.length && navigator.canShare?.({ files })) await navigator.share({ files, text });
      else await navigator.share({ text });
      return;
    } catch (e) {
      btn?.classList.remove('busy');
      if (e?.name === 'AbortError') return;   // kullanıcı vazgeçti
      if (e?.name === 'NotAllowedError' && mediaList.every(m => shareFiles.has(m.path))) { toast('Paylaşım hazır — Paylaş’a tekrar dokunun'); return; }
    }
  }
  onNoShare?.();
}
function downloadMedia(m) {
  const a = h('a', { href: `${fileUrl(m.path)}?dl=1`, download: m.path.split('/').pop() || '' });
  document.body.append(a); a.click(); a.remove();
}
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); toast('Kopyalandı'); } catch { toast('Kopyalanamadı', 'err'); }
}
// Alttan açılan seçenek paneli (Instagram "⋯" menüsü)
function actionSheet(title, items) {
  const close = () => { back.classList.remove('in'); document.removeEventListener('keydown', onKey); setTimeout(() => back.remove(), 220); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  const list = h('div', { class: 'sp-sheet-list' },
    items.map(it => h('button', { class: `sp-opt ${it.danger ? 'danger' : ''}`, type: 'button', onclick: () => { close(); it.run(); } },
      h('span', { class: 'sp-ico' }, svgSpan(it.ico)), h('span', { class: 'sp-txt' }, it.label))),
    h('button', { class: 'sp-opt sp-cancel', type: 'button', onclick: close }, h('span', { class: 'sp-txt' }, 'Vazgeç')));
  const back = h('div', { class: 'sp-back feed-sheet' }, h('div', { class: 'sp-sheet' }, h('div', { class: 'sp-grip' }),
    title ? h('div', { class: 'sp-title' }, title) : null, list));
  back.addEventListener('click', e => { if (e.target === back) close(); });
  document.body.append(back);
  document.addEventListener('keydown', onKey);
  window.addEventListener('hashchange', close, { once: true });
  requestAnimationFrame(() => back.classList.add('in'));
}

// Paylaşım yükleme kuyruğu (modül düzeyi: ana ekrandan çıkılsa da yükleme sürer; bitince akışa düşer)
const uploads = new Set();
const upListeners = new Set();
const upNotify = () => [...upListeners].forEach(f => f());
function startUpload(fd, preview) {
  const u = { pct: 0, state: 'up', ...preview };
  const drop = () => { uploads.delete(u); if (u.thumb) URL.revokeObjectURL(u.thumb); upNotify(); };
  const run = async () => {
    u.state = 'up'; u.pct = 0; u.err = ''; upNotify();
    try {
      await upload('/api/feed', fd, pct => { u.pct = pct; upNotify(); });
      u.state = 'done'; u.pct = 100; upNotify();
      window.dispatchEvent(new CustomEvent('caymaz:feed', { detail: { t: 'feed', own: true } }));   // açık akışlar yeni paylaşımı ekler
      if (!upListeners.size) toast('Paylaşımınız yayınlandı', 'success');
      setTimeout(drop, 1800);
    } catch (err) {
      u.state = 'err'; u.err = err?.message || 'Bağlantı hatası'; upNotify();
      if (!upListeners.size) toastError(err);
    }
  };
  u.retry = run; u.cancel = drop;
  uploads.add(u);
  run();
}

function openViewer(items, start, act) {
  items = items.filter(m => m.type === 'image' || m.type === 'video');
  if (!items.length) return;
  let i = Math.max(0, Math.min(start, items.length - 1));
  const track = h('div', { class: 'fv-track' });
  const stage = h('div', { class: 'fv-stage' }, track);
  const counter = h('div', { class: 'fv-count' });
  const upBtn = h('button', { class: 'fv-nav up', type: 'button', title: 'Önceki', onclick: () => slide(-1) }, '▲');
  const downBtn = h('button', { class: 'fv-nav down', type: 'button', title: 'Sonraki', onclick: () => slide(1) }, '▼');
  const rail = h('div', { class: 'fv-rail' });
  const cap = h('div', { class: 'fv-cap' });
  const sheet = h('div', { class: 'fv-sheet', hidden: true });
  const overlay = h('div', { class: 'fv-overlay' },
    stage, h('button', { class: 'fv-x', type: 'button', title: 'Kapat', onclick: close }, '✕'),
    counter, upBtn, downBtn, rail, cap, sheet);

  // ---- kayan şerit: önceki / şimdiki / sonraki slayt (geçişte öğeler yeniden yüklenmez) ----
  const make = k => {
    const m = items[k];
    if (!m) return null;
    const media = m.type === 'video'
      ? h('video', { class: 'fv-media', src: videoUrl(m.path), controls: true, playsinline: true, preload: 'metadata' })
      : h('img', { class: 'fv-media', src: fileUrl(m.path), alt: '', draggable: false });
    return { el: h('div', { class: 'fv-slide' }, media), media };
  };
  let sl = { prev: make(i - 1), cur: make(i), next: make(i + 1) };
  const place = () => [[-1, sl.prev], [0, sl.cur], [1, sl.next]].forEach(([k, x]) => {
    if (!x) return;
    x.el.style.transform = `translateY(${k * 100}%)`;
    if (!x.el.isConnected) track.append(x.el);
  });
  const setTrack = (y, anim) => {
    track.style.transition = anim ? 'transform .3s cubic-bezier(.2,.75,.25,1)' : 'none';
    track.style.transform = `translateY(${y})`;
  };
  let busy = false;
  function slide(d) {   // d: +1 sonraki, -1 önceki — kayarak geç
    if (busy || zoomed()) return;
    if (!(d > 0 ? sl.next : sl.prev)) return setTrack('0px', true);   // uçta: geri yaylan
    busy = true;
    setTrack(`${-d * 100}%`, true);
    setTimeout(() => {
      if (d > 0) { sl.prev?.el.remove(); sl = { prev: sl.cur, cur: sl.next, next: make(i + 2) }; }
      else { sl.next?.el.remove(); sl = { next: sl.cur, cur: sl.prev, prev: make(i - 2) }; }
      i += d;
      place(); setTrack('0px', false); activate();
      busy = false;
    }, 300);
  }

  // ---- yakınlaştırma ----
  let z = { s: 1, x: 0, y: 0 };
  const MAX = 5;
  const media = () => sl.cur?.media;
  const zoomed = () => z.s > 1.01;
  function clampPan() {
    const m = media(); if (!m) return;
    const mx = m.offsetWidth * (z.s - 1) / 2, my = m.offsetHeight * (z.s - 1) / 2;
    z.x = Math.max(-mx, Math.min(mx, z.x)); z.y = Math.max(-my, Math.min(my, z.y));
  }
  function apply(anim) {
    const m = media(); if (!m) return;
    m.style.transition = anim ? 'transform .18s ease' : 'none';
    m.style.transform = zoomed() ? `translate(${z.x}px, ${z.y}px) scale(${z.s})` : '';
    overlay.classList.toggle('zoomed', zoomed());
    if (m.tagName === 'VIDEO') m.controls = !zoomed();   // büyükken denetimler taşmasın
  }
  function zoomTo(ns, cx, cy, anim) {   // ekrandaki (cx, cy) noktası yerinde kalır
    ns = Math.max(1, Math.min(MAX, ns));
    const r = stage.getBoundingClientRect();
    const px = cx - (r.left + r.width / 2), py = cy - (r.top + r.height / 2);
    const qx = (px - z.x) / z.s, qy = (py - z.y) / z.s;
    z = ns <= 1.01 ? { s: 1, x: 0, y: 0 } : { s: ns, x: px - ns * qx, y: py - ns * qy };
    clampPan(); apply(anim);
  }
  const resetZoom = () => { z = { s: 1, x: 0, y: 0 }; apply(true); };

  // ---- sağ şerit + alt yazı ----
  const post = () => items[i].post;
  let dlLink;
  function drawRail() {
    const p = post(), m = items[i];
    if (!p) return clear(rail);
    const total = Object.values(p.reactions || {}).reduce((a, b) => a + b, 0);
    const mine = p.my_reaction;
    const heart = h('button', { class: `fv-rb fv-heart ${mine ? 'on' : ''}`, type: 'button', title: mine ? 'Tepkiyi kaldır' : 'Beğen',
      onclick: () => { act.react(p, mine || '❤️'); drawRail(); } },
      mine && mine !== '❤️' ? h('span', { class: 'fv-em' }, mine) : ico(SVG.heart));
    let lp;   // uzun bas / sağ tık: diğer tepkiler
    const pick = () => {
      const row = h('div', { class: 'fv-picker' }, act.reactions().map(em => h('button', { type: 'button',
        onclick: e => { e.stopPropagation(); act.react(p, em); drawRail(); } }, em)));
      rail.querySelector('.fv-picker')?.remove();
      heartWrap.append(row);
      setTimeout(() => document.addEventListener('pointerdown', ev => { if (!row.contains(ev.target)) row.remove(); }, { once: true }), 0);
    };
    heart.addEventListener('pointerdown', () => { lp = setTimeout(() => { lp = 'fired'; pick(); }, 450); });
    heart.addEventListener('pointerup', () => { if (lp !== 'fired') clearTimeout(lp); });
    heart.addEventListener('pointerleave', () => { if (lp !== 'fired') clearTimeout(lp); });
    heart.addEventListener('click', e => { if (lp === 'fired') { e.stopImmediatePropagation(); lp = null; } }, true);
    heart.addEventListener('contextmenu', e => { e.preventDefault(); pick(); });
    const who = act.canSeeReactors(p) && total;
    const heartWrap = h('div', { class: 'fv-ri' }, heart,
      h(who ? 'button' : 'span', { class: `fv-n ${who ? 'link' : ''}`, type: who ? 'button' : null, title: who ? 'Kimler beğendi' : null,
        onclick: who ? () => act.showReactors(p) : null }, String(total)));
    dlLink = h('a', { class: 'fv-rb', title: 'İndir', 'aria-label': 'İndir', href: `${fileUrl(m.path)}?dl=1`, download: m.path.split('/').pop() || '' }, ico(SVG.dl));
    clear(rail,
      h('div', { class: 'fv-ava' }, p.system ? h('img', { src: LOGO, alt: '' }) : avatar({ full_name: p.author_name, photo: p.author_photo }, 46)),
      heartWrap,
      h('div', { class: 'fv-ri' }, h('button', { class: 'fv-rb', type: 'button', title: 'Yorumlar', onclick: () => openSheet() }, ico(SVG.chat)),
        h('span', { class: 'fv-n' }, String(p.comment_count || 0))),
      h('div', { class: 'fv-ri' }, h('button', { class: `fv-rb fv-save ${p.saved ? 'on' : ''}`, type: 'button', title: p.saved ? 'Kaydedilenlerden çıkar' : 'Favorilere kaydet',
        onclick: () => { act.save(p).then(drawRail); drawRail(); } }, ico(SVG.save)),
        h('span', { class: 'fv-n' }, p.saved ? 'Kaydedildi' : 'Kaydet')),
      h('div', { class: 'fv-ri' }, h('button', { class: 'fv-rb fv-share', type: 'button', title: 'Paylaş', onclick: e => share(e.currentTarget) }, ico(SVG.share)),
        h('span', { class: 'fv-n' }, 'Paylaş')),
      h('div', { class: 'fv-ri' }, dlLink, h('span', { class: 'fv-n' }, 'İndir')));
  }
  function drawCap() {
    const p = post();
    if (!p) return clear(cap);
    const txt = h('div', { class: 'fv-ctext', onclick: () => txt.classList.toggle('open') }, p.text || '');
    clear(cap, h('div', { class: 'fv-cname' }, p.system ? act.company() : (p.author_name || 'Kullanıcı'),
      h('small', null, ` · ${fmtDateTime(p.created_at)}`)), p.text ? txt : null);
  }

  // ---- yorumlar: alttan açılan panel ----
  function openSheet() {
    const p = post(); if (!p) return;
    const body = h('div', { class: 'fv-sheet-b' });
    const head = h('div', { class: 'fv-sheet-h' }, h('b', null, `Yorumlar (${p.comment_count || 0})`),
      h('button', { class: 'fv-sheet-x', type: 'button', title: 'Kapat', onclick: closeSheet }, '✕'));
    clear(sheet, head, body);
    sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.add('open'));
    const sync = () => { head.firstChild.textContent = `Yorumlar (${p.comment_count || 0})`; drawRail(); };
    const redraw = () => { sync(); act.comments(p, body, redraw).then(sync); };
    act.comments(p, body, redraw).then(sync);
  }
  function closeSheet() { sheet.classList.remove('open'); setTimeout(() => { sheet.hidden = true; clear(sheet); }, 220); }

  // ---- paylaş: cihazın paylaşma menüsü (WhatsApp, Mesajlar, Posta…) — dosyanın kendisi gönderilir ----
  function share(btn) {
    const p = post(), m = items[i];
    const text = [p?.system ? act.company() : p?.author_name, p?.text].filter(Boolean).join(': ').slice(0, 400);
    deviceShare([m], text, btn, () => { dlLink?.click(); toast('Bu cihazda paylaşma menüsü yok; dosya indirildi'); });
  }

  function activate() {
    const m = items[i];
    counter.textContent = `${i + 1} / ${items.length}`;
    upBtn.disabled = i <= 0; downBtn.disabled = i >= items.length - 1;
    z = { s: 1, x: 0, y: 0 };
    overlay.classList.remove('zoomed');
    for (const x of [sl.prev, sl.next]) if (x?.media.tagName === 'VIDEO') { x.media.pause(); x.media.style.transform = ''; }
    if (sl.cur?.media.tagName === 'VIDEO') { sl.cur.media.controls = true; sl.cur.media.play().catch(() => {}); }
    if (sl.cur) sl.cur.media.style.transform = '';
    if (!sheet.hidden) closeSheet();
    drawRail(); drawCap();
    if (navigator.share && m.type === 'image') shareFile(m).catch(() => {});   // resim: paylaşım menüsü anında açılsın
  }

  const noGesture = e => e.preventDefault();   // iOS Safari: sayfanın kendisi yakınlaşmasın
  function close() {
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('gesturestart', noGesture);
    document.body.classList.remove('fv-open');
    overlay.querySelectorAll('video').forEach(v => v.pause());
    overlay.remove();
  }
  const typing = t => t?.closest?.('input, textarea, [contenteditable="true"]');
  const onKey = e => {
    if (e.key === 'Escape') { if (!sheet.hidden) closeSheet(); else if (zoomed()) resetZoom(); else close(); return; }
    if (typing(e.target) || !sheet.hidden) return;
    const r = stage.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    if (e.key === '+' || e.key === '=') return zoomTo(z.s * 1.5, cx, cy, true);
    if (e.key === '-') return zoomTo(z.s / 1.5, cx, cy, true);
    if (e.key === '0') return resetZoom();
    if (zoomed()) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); slide(1); }
    else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); slide(-1); }
  };
  document.addEventListener('keydown', onKey);
  document.addEventListener('gesturestart', noGesture);

  // ---- dokunma / mouse: tek parmak = kaydır (büyükken: sürükle), iki parmak = yakınlaştır ----
  const pts = new Map();
  let g = null, pinched = false, lastTap = null;
  const ignore = t => !!t.closest?.('button, a, .fv-rail, .fv-cap, .fv-sheet');
  const mid = () => { const [a, b] = [...pts.values()]; return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) || 1 }; };
  overlay.addEventListener('pointerdown', e => {
    if (ignore(e.target) || busy) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) {   // iki parmak: başlangıçtaki orta noktanın altındaki yer parmakları izler
      if (g?.drag) setTrack('0px', true);
      const m = mid(), r = stage.getBoundingClientRect();
      const px = m.x - (r.left + r.width / 2), py = m.y - (r.top + r.height / 2);
      g = { pinch: true, d0: m.d, s0: z.s, qx: (px - z.x) / z.s, qy: (py - z.y) / z.s };
      pinched = true;
    } else if (pts.size === 1) {
      g = { x: e.clientX, y: e.clientY, panX: z.x, panY: z.y, t: e.timeStamp, drag: false };
      pinched = false;
    }
  });
  overlay.addEventListener('pointermove', e => {
    if (!pts.has(e.pointerId) || !g) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (g.pinch && pts.size >= 2) {
      const m = mid(), r = stage.getBoundingClientRect();
      const ns = Math.max(1, Math.min(MAX, g.s0 * m.d / g.d0));
      const px = m.x - (r.left + r.width / 2), py = m.y - (r.top + r.height / 2);
      z = ns <= 1.01 ? { s: 1, x: 0, y: 0 } : { s: ns, x: px - ns * g.qx, y: py - ns * g.qy };
      clampPan(); apply(false);
    } else if (!g.pinch && zoomed()) {   // büyükken: resmi sürükle
      z.x = g.panX + (e.clientX - g.x); z.y = g.panY + (e.clientY - g.y);
      clampPan(); apply(false);
    } else if (!g.pinch) {   // kaydırma: şerit parmağı izler (uçta yaylanarak)
      const dy = e.clientY - g.y, dx = e.clientX - g.x;
      if (!g.drag && Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) g.drag = true;
      if (g.drag) {
        const edge = (dy < 0 && !sl.next) || (dy > 0 && !sl.prev);
        setTrack(`${edge ? dy * 0.25 : dy}px`, false);
      }
    }
  });
  const up = e => {
    if (!pts.has(e.pointerId)) return;
    pts.delete(e.pointerId);
    if (pts.size === 1 && g?.pinch) {   // bir parmak kaldı: oradan sürüklemeye devam
      const [q] = [...pts.values()];
      g = { x: q.x, y: q.y, panX: z.x, panY: z.y, t: e.timeStamp, after: true };
      return;
    }
    if (pts.size || !g) return;
    const s0 = g; g = null;
    if (pinched || s0.after || e.type === 'pointercancel') { pinched = false; if (!zoomed()) setTrack('0px', true); return; }
    const dy = e.clientY - s0.y, dx = e.clientX - s0.x;
    if (s0.drag) {   // bırakınca: yeterince çekildiyse (ya da hızlı fırlatıldıysa) kayarak geç, değilse yerine dön
      const v = dy / Math.max(1, e.timeStamp - s0.t);
      const h0 = stage.clientHeight || 600;
      if (dy < -h0 * 0.18 || (dy < -30 && v < -0.45)) return slide(1);
      if (dy > h0 * 0.18 || (dy > 30 && v > 0.45)) return slide(-1);
      return setTrack('0px', true);
    }
    const tap = Math.abs(dy) < 8 && Math.abs(dx) < 8;
    const m = media();
    if (tap && m && (e.target === m || m.contains(e.target))) {   // medyaya çift dokunuş: büyüt / küçült
      if (lastTap && e.timeStamp - lastTap.t < 320 && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 30) {
        lastTap = null;
        zoomed() ? resetZoom() : zoomTo(2.5, e.clientX, e.clientY, true);
      } else lastTap = { t: e.timeStamp, x: e.clientX, y: e.clientY };
      return;
    }
    if (tap && !zoomed() && e.target.closest?.('.fv-slide, .fv-track, .fv-stage') && sheet.hidden) close();   // boşluğa dokunma = kapat
    else if (tap && !sheet.hidden) closeSheet();
  };
  overlay.addEventListener('pointerup', up);
  overlay.addEventListener('pointercancel', up);
  overlay.addEventListener('dblclick', e => e.preventDefault());
  let wlock = 0;
  overlay.addEventListener('wheel', e => {
    if (e.target.closest?.('.fv-sheet')) return;   // yorum panelinde tekerlek listeyi kaydırır
    e.preventDefault();
    if (e.ctrlKey) return zoomTo(z.s * Math.exp(-e.deltaY / 120), e.clientX, e.clientY, false);   // izleme dörtgeni kıstırma / Ctrl+tekerlek
    if (zoomed()) { z.x -= e.deltaX; z.y -= e.deltaY; clampPan(); return apply(false); }
    if (Math.abs(e.deltaY) < 4) return;
    const now = Date.now(); if (now - wlock < 450) return; wlock = now;
    slide(e.deltaY > 0 ? 1 : -1);
  }, { passive: false });

  document.body.classList.add('fv-open');
  document.body.append(overlay);
  place(); activate();
}

// Paylaşım oluştur: metin + medya önizlemeleri (resim/video/ses küçük kareler) + konum. "Paylaş" formu hemen kapatır;
// yükleme arka planda sürer, akışın üstünde ilerleme çubuğu görünür, bitince paylaşım akışa düşer.
function compose(ctx) {
  const text = h('textarea', { class: 'feed-c-text', rows: 3, placeholder: 'Ne paylaşmak istersin?', maxlength: 2000 });
  const grow = () => { text.style.height = 'auto'; text.style.height = `${Math.min(text.scrollHeight, 320)}px`; };
  text.addEventListener('input', grow);
  const fileInp = h('input', { type: 'file', accept: 'image/*,video/*,audio/*', multiple: true, hidden: true });
  const camInp = h('input', { type: 'file', accept: 'image/*,video/*', capture: 'environment', hidden: true });
  const MAX = 8;
  const files = [];   // { file, url, kind }
  const kindOf = f => (f.type.startsWith('video') ? 'video' : f.type.startsWith('audio') ? 'audio' : 'image');
  const grid = h('div', { class: 'feed-c-grid', hidden: true });
  const addFiles = list => {
    for (const f of list) {
      if (files.length >= MAX) { toast(`En çok ${MAX} dosya eklenebilir`, 'err'); break; }
      files.push({ file: f, url: URL.createObjectURL(f), kind: kindOf(f) });
    }
    drawGrid();
  };
  fileInp.addEventListener('change', () => { addFiles(fileInp.files); fileInp.value = ''; });
  camInp.addEventListener('change', () => { addFiles(camInp.files); camInp.value = ''; });
  const tile = (x, i) => h('div', { class: `feed-c-tile ${x.kind}` },
    x.kind === 'image' ? h('img', { src: x.url, alt: '', onerror: e => e.target.replaceWith(h('span', { class: 'feed-c-ph' }, '🖼')) })
      : x.kind === 'video' ? [h('video', { src: `${x.url}#t=0.1`, muted: true, playsinline: true, preload: 'metadata' }), h('span', { class: 'feed-c-badge' }, '▶')]
        : h('span', { class: 'feed-c-ph' }, '🎤', h('small', null, 'Ses')),
    h('button', { class: 'feed-c-x', type: 'button', title: 'Kaldır', 'aria-label': 'Kaldır',
      onclick: () => { URL.revokeObjectURL(x.url); files.splice(i, 1); drawGrid(); } }, '✕'));
  const drawGrid = () => {
    clear(grid, files.map(tile), files.length && files.length < MAX
      ? h('button', { class: 'feed-c-add', type: 'button', title: 'Daha fazla ekle', onclick: () => fileInp.click() }, '+') : null);
    grid.hidden = !files.length;
  };
  let coords = null;
  const locBtn = h('button', { class: 'feed-c-tool', type: 'button' }, svgSpan(IG.pin), h('span', null, 'Konum'));
  locBtn.addEventListener('click', () => {
    if (coords) { coords = null; locBtn.classList.remove('on'); locBtn.lastChild.textContent = 'Konum'; return; }
    if (!navigator.geolocation) return toast('Konum desteklenmiyor', 'err');
    locBtn.lastChild.textContent = 'Konum alınıyor…';
    navigator.geolocation.getCurrentPosition(
      pos => { coords = { lat: pos.coords.latitude, lng: pos.coords.longitude }; locBtn.classList.add('on'); locBtn.lastChild.textContent = 'Konum eklendi ✕'; },
      () => { locBtn.lastChild.textContent = 'Konum alınamadı'; }, { enableHighAccuracy: true, timeout: 8000 });
  });
  let sent = false;
  modal({
    title: 'Yeni paylaşım', wide: true,
    onClose: () => { if (!sent) files.forEach(x => URL.revokeObjectURL(x.url)); },
    body: h('div', { class: 'feed-compose' },
      h('div', { class: 'feed-c-head' }, avatar(ctx.user, 40),
        h('div', null, h('b', null, ctx.user.full_name), h('small', { class: 'muted' }, 'Şirketten Haberler'))),
      text, grid,
      h('div', { class: 'feed-c-tools' },
        h('button', { class: 'feed-c-tool', type: 'button', onclick: () => fileInp.click() }, svgSpan(IG.image), h('span', null, 'Fotoğraf / Video')),
        h('button', { class: 'feed-c-tool', type: 'button', onclick: () => camInp.click() }, svgSpan(IG.camera), h('span', null, 'Kamera')),
        locBtn, fileInp, camInp)),
    actions: [{ label: 'Vazgeç' }, { label: 'Paylaş', class: 'primary', onClick: () => {
      if (!text.value.trim() && !files.length) { toast('Metin ya da medya ekleyin', 'err'); return true; }
      const fd = new FormData();
      fd.append('text', text.value);
      if (coords) { fd.append('lat', coords.lat); fd.append('lng', coords.lng); }
      files.forEach(x => fd.append('files', x.file));
      const first = files.find(x => x.kind !== 'audio');
      startUpload(fd, { thumb: first ? URL.createObjectURL(first.file) : null, thumbType: first?.kind,
        audio: files.some(x => x.kind === 'audio'), text: text.value.trim().slice(0, 80) });
      sent = true;
      files.forEach(x => URL.revokeObjectURL(x.url));
    } }],
  });
  text.focus();
}
