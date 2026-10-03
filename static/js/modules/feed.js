// Şirketten Haberler: pano akışı (Facebook tarzı) — sistem olayları + kullanıcı paylaşımları (resim/video/ses + konum).
// İki görünüm: Akış ve Harita. Sistem olaylarında şirket logosu, kullanıcı paylaşımında kişinin fotoğrafı.
import { api, fileUrl, upload, videoUrl } from '../api.js';
import { loadMaps } from '../maps.js';
import { avatar, clear, confirmDialog, fmtDateTime, h, modal, onLeave, segmented, toast, toastError } from '../ui.js';

const KIND_BADGE = {
  HIRE: ['green', 'İşe alım'], TERMINATION: ['', 'Ayrılış'], FLIGHT: ['blue', 'Uçuş'],
  ORDER: ['blue', 'Sipariş'], MEETING: ['yellow', 'Toplantı'], ANNOUNCE: ['red', 'Duyuru'], USER: ['', ''],
};
const LOGO = '/static/img/logo-mark.png';
// Tepki simgesi → etiket + renk (beğen düğmesi ve etiketi için)
const REACTION_META = {
  '👍': { label: 'Beğen', color: '#2563eb' }, '❤️': { label: 'Sevdim', color: '#e0245e' },
  '😂': { label: 'Güldüm', color: '#f7b125' }, '😮': { label: 'Şaşırdım', color: '#f7b125' },
  '😢': { label: 'Üzüldüm', color: '#f7b125' }, '👏': { label: 'Alkış', color: '#f7b125' },
  '🎉': { label: 'Kutlama', color: '#f7b125' },
};
const THUMB_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v10H4V10z"/><path d="M7 10l4.2-7a1.8 1.8 0 0 1 3.3 1.1V9h4.4a2 2 0 0 1 2 2.4l-1.3 6.2A2 2 0 0 1 17.6 20H7"/></svg>';
const CHAT_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a7.5 7.5 0 0 1-10.9 6.7L4 20l1.8-5.1A7.5 7.5 0 1 1 21 11.5z"/></svg>';
const SEND_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M3.4 20.4l17.4-7.5c.8-.3.8-1.5 0-1.8L3.4 3.6c-.7-.3-1.4.3-1.3 1l.9 5.3c.1.4.4.7.8.8l7.7 1.3-7.7 1.3c-.4.1-.7.4-.8.8l-.9 5.3c-.1.7.6 1.3 1.3 1z"/></svg>';
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
  const mediaEl = (m, p) => {
    if (m.type === 'audio') return h('audio', { class: 'feed-audio', src: fileUrl(m.path), controls: true, preload: 'none' });
    if (m.type === 'video') return h('button', { class: 'feed-media feed-vid', type: 'button', title: 'Tam ekran aç', onclick: () => openAt(m, p) },
      h('video', { src: videoUrl(m.path), preload: 'metadata', muted: true, playsinline: true, tabindex: -1 }), h('span', { class: 'feed-play' }, '▶'));
    return h('button', { class: 'feed-media', type: 'button', title: 'Tam ekran aç', onclick: () => openAt(m, p) },
      h('img', { src: fileUrl(m.path, 1000), alt: '', loading: 'lazy' }));
  };
  const isAdmin = () => ctx.user.master || ctx.user.modules.includes('admin');
  const postCard = p => {
    const badge = KIND_BADGE[p.kind] || KIND_BADGE.USER;
    // Başkasının paylaşımını kimse silemez (yönetici / sistem sahibi dahil); sistem olaylarını yönetici kaldırabilir
    const canDel = p.system ? isAdmin() : p.author_id === ctx.user.id;
    const card = h('div', { class: 'feed-post' },
      h('div', { class: 'feed-ph' },
        p.system ? h('img', { class: 'feed-ava', src: LOGO, alt: '' }) : avatar({ full_name: p.author_name, photo: p.author_photo }, 40),
        h('div', { class: 'grow' }, h('b', null, p.system ? (ctx.meta?.company || 'Şirket') : (p.author_name || 'Kullanıcı')),
          h('small', { class: 'muted' }, fmtDateTime(p.created_at), p.lat ? ' · 📍' : '')),
        badge[1] ? h('span', { class: `badge ${badge[0]}` }, badge[1]) : null,
        canDel ? h('button', { class: 'feed-x', type: 'button', title: 'Sil', onclick: () => del(p) }, '×') : null),
      p.text ? h('div', { class: 'feed-text' }, p.ref_link ? h('a', { href: p.ref_link }, p.text) : p.text) : null,
      p.media?.length ? h('div', { class: `feed-medias n${Math.min(p.media.length, 4)}` }, p.media.map(m => mediaEl(m, p))) : null,
      footer(p, c => reCard(p, c)));
    p._card = card;
    return card;
  };

  // Tepki (beğeni/kalp) + yorum ayağı; değişince kart yerinde yeniden çizilir (yorum açıklığı korunur)
  function reCard(p, oldCard) {
    const fresh = postCard(p);
    oldCard.replaceWith(fresh);
  }
  function footer(p, rerender) {
    const counts = p.reactions || {};
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const topEmojis = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 3).map(e => e[0]);
    const stat = h('div', { class: 'feed-stat' },
      total ? h(canSeeReactors(p) ? 'button' : 'span', { class: `feed-rsum ${canSeeReactors(p) ? 'clickable' : ''}`, type: 'button',
        title: canSeeReactors(p) ? 'Kimler tepki verdi' : null, onclick: canSeeReactors(p) ? () => showReactors(p) : null },
        h('span', { class: 'feed-rbubbles' }, topEmojis.map(em => h('span', { class: 'feed-rb' }, em))),
        h('span', { class: 'feed-rcount' }, String(total))) : h('span'),
      p.comment_count ? h('button', { class: 'feed-stat-c', type: 'button', onclick: () => toggleComments(p, rerender) }, `${p.comment_count} yorum`) : h('span'));

    const picker = h('div', { class: 'feed-picker' }, reactionList.map(em =>
      h('button', { class: 'feed-pick', type: 'button', title: (REACTION_META[em]?.label || em),
        onclick: () => { hidePicker(); doReact(p, em, rerender); } }, em)));
    const meta = p.my_reaction ? REACTION_META[p.my_reaction] : null;
    const likeBtn = h('button', { class: `feed-act feed-like ${p.my_reaction ? 'on' : ''}`, type: 'button',
      style: meta ? { color: meta.color } : null,
      onclick: () => doReact(p, p.my_reaction || '👍', rerender) },
      p.my_reaction ? h('span', { class: 'feed-like-em' }, p.my_reaction) : svgSpan(THUMB_SVG),
      h('span', null, meta ? meta.label : 'Beğen'));
    let hideT, lpT;
    const showPicker = () => { clearTimeout(hideT); likeWrap.classList.add('show-picker'); };
    const hidePicker = () => likeWrap.classList.remove('show-picker');
    const likeWrap = h('div', { class: 'feed-like-wrap',
      onmouseenter: showPicker, onmouseleave: () => { hideT = setTimeout(hidePicker, 220); } }, picker, likeBtn);
    likeBtn.addEventListener('touchstart', () => { lpT = setTimeout(showPicker, 350); }, { passive: true });
    likeBtn.addEventListener('touchend', () => clearTimeout(lpT));

    const cmtBtn = h('button', { class: 'feed-act', type: 'button', onclick: () => toggleComments(p, rerender, true) },
      svgSpan(CHAT_SVG), h('span', null, 'Yorum'));
    const bar = h('div', { class: 'feed-actions' }, likeWrap, cmtBtn);

    const box = h('div', { class: 'feed-comments' });
    const wrap = h('div', { class: 'feed-foot' }, (total || p.comment_count) ? stat : null, bar, box);
    if (p._open) renderComments(p, box, rerender);
    return wrap;
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

  async function renderComments(p, box, rerender) {
    clear(box, h('div', { class: 'small muted' }, 'Yükleniyor…'));
    let list = p._comments;
    if (!list) {
      try { list = p._comments = (await api.get(`/api/feed/${p.id}/comments`)).comments; }
      catch (err) { return clear(box, h('div', { class: 'small muted' }, err.message)); }
    }
    const input = h('input', { class: 'feed-cinput', type: 'text', placeholder: 'Yorum yaz…', maxlength: 1000 });
    const send = async () => {
      const text = input.value.trim(); if (!text) return;
      input.value = '';
      try {
        const r = await api.post(`/api/feed/${p.id}/comments`, { text });
        p._comments = [...(p._comments || []), { id: r.id, user_id: ctx.user.id, text, created_at: new Date().toISOString(),
          author_name: ctx.user.full_name, author_photo: ctx.user.photo }];
        p.comment_count = (p.comment_count || 0) + 1;
        rerender(p._card);
      } catch (err) { toastError(err); }
    };
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); send(); } });
    clear(box,
      h('div', { class: 'feed-clist' }, list.map(c => h('div', { class: 'feed-cmt' },
        avatar({ full_name: c.author_name, photo: c.author_photo }, 32),
        h('div', { class: 'feed-cmain' },
          h('div', { class: 'feed-cbody' },
            h('div', { class: 'feed-cname' }, c.author_name || 'Kullanıcı'),
            h('div', { class: 'feed-ctext' }, c.text)),
          h('div', { class: 'feed-cmeta' }, h('span', { class: 'muted' }, fmtDateTime(c.created_at)),
            c.user_id === ctx.user.id ? h('button', { class: 'feed-cdel', type: 'button', onclick: async () => {
              try { await api.del(`/api/feed/comments/${c.id}`); p._comments = p._comments.filter(x => x.id !== c.id); p.comment_count = Math.max(0, (p.comment_count || 1) - 1); rerender(p._card); }
              catch (err) { toastError(err); }
            } }, 'Sil') : null))))),
      h('div', { class: 'feed-cadd' }, avatar(ctx.user, 32),
        h('div', { class: 'feed-cinput-wrap' }, input,
          h('button', { class: 'feed-csend', type: 'button', title: 'Gönder', onclick: send }, svgSpan(SEND_SVG)))));
  }

  const composer = () => h('button', { class: 'feed-composer', type: 'button', onclick: () => compose(load) },
    avatar(ctx.user, 36),
    h('span', { class: 'feed-composer-pill' }, 'Bir şeyler paylaş…'),
    h('span', { class: 'feed-composer-ic', title: 'Foto / Video / Ses' }, '📷'));
  let drawMap;
  function draw() {
    if (view === 'map') return drawMap();
    const list = posts.length ? h('div', { class: 'feed-list' }, posts.map(postCard))
      : h('div', { class: 'feed-empty muted' }, 'Henüz paylaşım yok. İlk paylaşımı sen ekle!');
    clear(body, composer(), list);
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
    try { await api.del(`/api/feed/${p.id}`); load(); } catch (err) { toastError(err); }
  }
  async function load() {
    try {
      const d = await api.get('/api/feed');
      posts = d.posts; if (Array.isArray(d.reactions) && d.reactions.length) reactionList = d.reactions;
      draw();
      markSeen();
    } catch (err) { clear(body, h('div', { class: 'card empty' }, err.message)); }
  }
  // Yeni paylaşım anında: mevcut kartlara (açık yorum, yazılan metin) dokunmadan yenileri en üste ekle
  async function addNew() {
    if (view === 'map') return load();
    let d;
    try { d = await api.get('/api/feed'); } catch { return; }
    const top = posts.reduce((m, p) => Math.max(m, p.id || 0), 0);
    const fresh = (d.posts || []).filter(p => p.id > top);
    if (!fresh.length) return;
    const list = body.querySelector('.feed-list');
    if (!list) {   // akış boştu: tam çiz, gelenleri yine vurgula
      posts = d.posts; draw(); markSeen();
      const ids = new Set(fresh.map(p => p.id));
      posts.forEach(p => { if (ids.has(p.id)) p._card?.classList.add('feed-fresh'); });
      return;
    }
    posts = [...fresh, ...posts];
    for (const p of fresh.slice().reverse()) {   // en yeni en üstte kalsın
      const card = postCard(p);
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
  onLeave(() => { window.removeEventListener('caymaz:feed', onFeed); document.removeEventListener('visibilitychange', onVisible); });
  // Tam ekran görüntüleyicinin sağ şeridi akıştaki aynı işlemleri kullanır; değişiklik akıştaki karta da yansır
  const refreshCard = p => { if (p._card?.isConnected) reCard(p, p._card); };
  const viewerActs = {
    company: () => ctx.meta?.company || 'Şirket',
    reactions: () => reactionList,
    react: (p, em) => doReact(p, em, () => refreshCard(p)),
    comments: (p, box, after) => renderComments(p, box, () => { refreshCard(p); after(); }),
    canSeeReactors: p => canSeeReactors(p),
    showReactors: p => showReactors(p),
  };
  // Pano dakikalık yenilemesi: kullanıcı yorum yazıyor / açık yorum varsa yalnız yenileri ekle, yoksa tam yenile
  const busy = () => posts.some(p => p._open) || body.contains(document.activeElement);
  load();
  return { reload: () => (busy() ? addNew() : load()) };
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
    const redraw = () => { head.firstChild.textContent = `Yorumlar (${p.comment_count || 0})`; drawRail(); act.comments(p, body, redraw); };
    act.comments(p, body, redraw);
  }
  function closeSheet() { sheet.classList.remove('open'); setTimeout(() => { sheet.hidden = true; clear(sheet); }, 220); }

  // ---- paylaş: cihazın paylaşma menüsü (WhatsApp, Mesajlar, Posta…) — dosyanın kendisi gönderilir ----
  async function share(btn) {
    const p = post(), m = items[i];
    const text = [p?.system ? act.company() : p?.author_name, p?.text].filter(Boolean).join(': ').slice(0, 400);
    if (navigator.share) {
      let f = shareFiles.get(m.path);
      try {
        if (!f) { btn.classList.add('busy'); f = await shareFile(m).catch(() => null); btn.classList.remove('busy'); }
        if (f && navigator.canShare?.({ files: [f] })) await navigator.share({ files: [f], text });
        else await navigator.share({ text });
        return;
      } catch (e) {
        btn.classList.remove('busy');
        if (e?.name === 'AbortError') return;   // kullanıcı vazgeçti
        if (e?.name === 'NotAllowedError' && shareFiles.has(m.path)) return toast('Paylaşım hazır — Paylaş’a tekrar dokunun');
      }
    }
    dlLink?.click();   // paylaşma menüsü olmayan cihaz (masaüstü tarayıcı): indir
    toast('Bu cihazda paylaşma menüsü yok; dosya indirildi');
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

// Paylaşım oluştur: metin + medya (resim/video/ses, kamera) + konum
function compose(onDone) {
  const text = h('textarea', { class: 'input', rows: 3, placeholder: 'Bir şeyler paylaş…' });
  const fileInp = h('input', { type: 'file', accept: 'image/*,video/*,audio/*', multiple: true, hidden: true });
  const camInp = h('input', { type: 'file', accept: 'image/*,video/*', capture: 'environment', hidden: true });
  const picked = h('div', { class: 'feed-picked' });
  let locOn = false, coords = null;
  const files = [];
  const addFiles = list => { for (const f of list) files.push(f); drawPicked(); };
  fileInp.addEventListener('change', () => { addFiles(fileInp.files); fileInp.value = ''; });
  camInp.addEventListener('change', () => { addFiles(camInp.files); camInp.value = ''; });
  const drawPicked = () => clear(picked, files.map((f, i) => h('span', { class: 'feed-chip' },
    f.type.startsWith('video') ? '🎬' : f.type.startsWith('audio') ? '🎤' : '🖼', ` ${f.name.slice(0, 18)}`,
    h('button', { type: 'button', class: 'feed-chip-x', onclick: () => { files.splice(i, 1); drawPicked(); } }, '×'))));
  const locBtn = h('button', { class: 'btn sm', type: 'button' }, '📍 Konum ekle');
  locBtn.addEventListener('click', () => {
    if (!navigator.geolocation) return toast('Konum desteklenmiyor', 'err');
    locBtn.textContent = 'Konum alınıyor…';
    navigator.geolocation.getCurrentPosition(
      pos => { coords = { lat: pos.coords.latitude, lng: pos.coords.longitude }; locOn = true; locBtn.textContent = '📍 Konum eklendi ✓'; locBtn.classList.add('on'); },
      () => { locBtn.textContent = '📍 Konum alınamadı'; }, { enableHighAccuracy: true, timeout: 8000 });
  });
  modal({
    title: 'Şirketten Haberler · Paylaş', wide: true,
    body: h('div', { class: 'feed-compose' }, text, picked,
      h('div', { class: 'feed-compose-bar' },
        h('button', { class: 'btn sm', type: 'button', onclick: () => fileInp.click() }, '🖼 Medya'),
        h('button', { class: 'btn sm', type: 'button', onclick: () => camInp.click() }, '📷 Kamera'),
        locBtn, fileInp, camInp)),
    actions: [{ label: 'Vazgeç' }, { label: 'Paylaş', class: 'primary', onClick: async () => {
      if (!text.value.trim() && !files.length) { toast('Metin ya da medya ekleyin', 'err'); return true; }
      const fd = new FormData();
      fd.append('text', text.value);
      if (locOn && coords) { fd.append('lat', coords.lat); fd.append('lng', coords.lng); }
      files.forEach(f => fd.append('files', f));
      try { await upload('/api/feed', fd); toast('Paylaşıldı', 'success'); onDone?.(); window.dispatchEvent(new Event('feed:changed')); }
      catch (err) { toastError(err); return true; }
    } }],
  });
  text.focus();
}
