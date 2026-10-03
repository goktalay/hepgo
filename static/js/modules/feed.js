// Şirketten Haberler: pano akışı (Facebook tarzı) — sistem olayları + kullanıcı paylaşımları (resim/video/ses + konum).
// İki görünüm: Akış ve Harita. Sistem olaylarında şirket logosu, kullanıcı paylaşımında kişinin fotoğrafı.
import { api, fileUrl, upload, videoUrl } from '../api.js';
import { loadMaps } from '../maps.js';
import { avatar, clear, confirmDialog, fmtDateTime, h, modal, toast, toastError } from '../ui.js';

const KIND_BADGE = {
  HIRE: ['green', 'İşe alım'], TERMINATION: ['', 'Ayrılış'], FLIGHT: ['blue', 'Uçuş'],
  ORDER: ['blue', 'Sipariş'], MEETING: ['yellow', 'Toplantı'], ANNOUNCE: ['red', 'Duyuru'], USER: ['', ''],
};
const LOGO = '/static/img/logo-mark.png';

export function renderFeed(container, ctx, opts = {}) {
  // Görünüm (Akış / Harita) Kişisel Ayarlar › Pano'dan seçilir; burada sabittir. Paylaşım gövdedeki kutudan yapılır.
  const view = opts.view === 'map' ? 'map' : 'feed';
  let posts = [];
  const body = h('div', { class: 'feed-body' });
  clear(container, body);

  let reactionList = ['👍', '❤️', '😂', '😮', '😢', '👏', '🎉'];   // sunucudan güncellenir
  let visual = [];   // akıştaki tüm resim + videolar (tam ekran kaydırmalı görüntüleyici için)
  const mediaEl = m => {
    if (m.type === 'audio') return h('audio', { class: 'feed-audio', src: fileUrl(m.path), controls: true, preload: 'none' });
    const idx = visual.length; visual.push(m);
    if (m.type === 'video') return h('button', { class: 'feed-media feed-vid', type: 'button', title: 'Tam ekran aç', onclick: () => openViewer(visual.slice(), idx) },
      h('video', { src: videoUrl(m.path), preload: 'metadata', muted: true, playsinline: true, tabindex: -1 }), h('span', { class: 'feed-play' }, '▶'));
    return h('button', { class: 'feed-media', type: 'button', title: 'Tam ekran aç', onclick: () => openViewer(visual.slice(), idx) },
      h('img', { src: fileUrl(m.path, 1000), alt: '', loading: 'lazy' }));
  };
  const isAdmin = () => ctx.user.master || ctx.user.modules.includes('admin');
  const postCard = p => {
    const badge = KIND_BADGE[p.kind] || KIND_BADGE.USER;
    const canDel = p.author_id === ctx.user.id || isAdmin();
    const card = h('div', { class: 'feed-post' },
      h('div', { class: 'feed-ph' },
        p.system ? h('img', { class: 'feed-ava', src: LOGO, alt: '' }) : avatar({ full_name: p.author_name, photo: p.author_photo }, 40),
        h('div', { class: 'grow' }, h('b', null, p.system ? (ctx.meta?.company || 'Şirket') : (p.author_name || 'Kullanıcı')),
          h('small', { class: 'muted' }, fmtDateTime(p.created_at), p.lat ? ' · 📍' : '')),
        badge[1] ? h('span', { class: `badge ${badge[0]}` }, badge[1]) : null,
        canDel ? h('button', { class: 'feed-x', type: 'button', title: 'Sil', onclick: () => del(p) }, '×') : null),
      p.text ? h('div', { class: 'feed-text' }, p.ref_link ? h('a', { href: p.ref_link }, p.text) : p.text) : null,
      p.media?.length ? h('div', { class: `feed-medias n${Math.min(p.media.length, 4)}` }, p.media.map(mediaEl)) : null,
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
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 3).map(e => e[0]).join('');
    const stat = h('div', { class: 'feed-stat' },
      total ? h('span', { class: 'feed-stat-r' }, top, ' ', String(total)) : h('span'),
      p.comment_count ? h('button', { class: 'feed-stat-c', type: 'button', onclick: () => toggleComments(p, rerender) }, `${p.comment_count} yorum`) : h('span'));

    const picker = h('div', { class: 'feed-picker', hidden: true }, (reactionList).map(em =>
      h('button', { class: 'feed-pick', type: 'button', title: em, onclick: () => { picker.hidden = true; doReact(p, em, rerender); } }, em)));
    const likeLabel = p.my_reaction ? `${p.my_reaction} Beğenildi` : '👍 Beğen';
    const likeBtn = h('button', { class: `feed-act ${p.my_reaction ? 'on' : ''}`, type: 'button',
      onclick: () => { if (p.my_reaction) doReact(p, p.my_reaction, rerender); else picker.hidden = !picker.hidden; } }, likeLabel);
    const likeWrap = h('div', { class: 'feed-like-wrap' }, picker, likeBtn);
    const cmtBtn = h('button', { class: 'feed-act', type: 'button', onclick: () => toggleComments(p, rerender, true) }, '💬 Yorum');
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
    const input = h('input', { class: 'input feed-cinput', type: 'text', placeholder: 'Yorum yaz…', maxlength: 1000 });
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
        avatar({ full_name: c.author_name, photo: c.author_photo }, 28),
        h('div', { class: 'feed-cbody' },
          h('div', null, h('b', null, c.author_name || 'Kullanıcı'), ' ', h('span', null, c.text)),
          h('small', { class: 'muted' }, fmtDateTime(c.created_at))),
        (c.user_id === ctx.user.id || isAdmin()) ? h('button', { class: 'feed-cx', type: 'button', title: 'Sil', onclick: async () => {
          try { await api.del(`/api/feed/comments/${c.id}`); p._comments = p._comments.filter(x => x.id !== c.id); p.comment_count = Math.max(0, (p.comment_count || 1) - 1); rerender(p._card); }
          catch (err) { toastError(err); }
        } }, '×') : null))),
      h('div', { class: 'feed-cadd' }, avatar(ctx.user, 28), input,
        h('button', { class: 'btn sm primary', type: 'button', onclick: send }, 'Gönder')));
  }

  const composer = () => h('button', { class: 'feed-composer', type: 'button', onclick: () => compose(load) },
    avatar(ctx.user, 36),
    h('span', { class: 'feed-composer-pill' }, 'Bir şeyler paylaş…'),
    h('span', { class: 'feed-composer-ic', title: 'Foto / Video / Ses' }, '📷'));
  let drawMap;
  function draw() {
    if (view === 'map') return drawMap();
    visual = [];
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
      const info = new maps.InfoWindow({ content: `<div style="max-width:200px">${thumb ? `<img src="${fileUrl(thumb.path, 200)}" style="width:100%;border-radius:6px">` : ''}<div>${(p.text || '').slice(0, 120)}</div></div>` });
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
    } catch (err) { clear(body, h('div', { class: 'card empty' }, err.message)); }
  }
  load();
  return { reload: load };
}

// Tam ekran medya görüntüleyici: resim/video arasında parmak ya da mouse ile yukarı/aşağı kaydırarak gezinilir.
function openViewer(items, start) {
  items = items.filter(m => m.type === 'image' || m.type === 'video');
  if (!items.length) return;
  let i = Math.max(0, Math.min(start, items.length - 1));
  const stage = h('div', { class: 'fv-stage' });
  const counter = h('div', { class: 'fv-count' });
  const upBtn = h('button', { class: 'fv-nav up', type: 'button', title: 'Önceki', onclick: () => go(i - 1) }, '▲');
  const downBtn = h('button', { class: 'fv-nav down', type: 'button', title: 'Sonraki', onclick: () => go(i + 1) }, '▼');
  const overlay = h('div', { class: 'fv-overlay' },
    h('button', { class: 'fv-x', type: 'button', title: 'Kapat', onclick: close }, '✕'),
    counter, upBtn, stage, downBtn,
    h('div', { class: 'fv-hint' }, 'Gezinmek için yukarı/aşağı kaydırın'));

  function render() {
    const m = items[i];
    counter.textContent = `${i + 1} / ${items.length}`;
    upBtn.disabled = i <= 0; downBtn.disabled = i >= items.length - 1;
    const el = m.type === 'video'
      ? h('video', { class: 'fv-media', src: fileUrl(m.path), controls: true, autoplay: true, playsinline: true })
      : h('img', { class: 'fv-media', src: fileUrl(m.path), alt: '' });
    clear(stage, el);
  }
  function go(n) { if (n < 0 || n >= items.length) return; i = n; render(); }
  function close() {
    document.removeEventListener('keydown', onKey);
    overlay.remove();
  }
  const onKey = e => {
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowDown' || e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); go(i + 1); }
    else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); go(i - 1); }
  };
  document.addEventListener('keydown', onKey);

  // Parmak / mouse ile dikey kaydırma
  let p0 = null;
  overlay.addEventListener('pointerdown', e => { p0 = { x: e.clientX, y: e.clientY }; });
  overlay.addEventListener('pointerup', e => {
    if (!p0) return;
    const dy = e.clientY - p0.y, dx = e.clientX - p0.x; p0 = null;
    if (Math.abs(dy) > 48 && Math.abs(dy) > Math.abs(dx)) { dy < 0 ? go(i + 1) : go(i - 1); }
    else if (Math.abs(dy) < 6 && Math.abs(dx) < 6 && (e.target === overlay || e.target === stage)) close();   // boşluğa dokunma = kapat
  });
  let wlock = 0;
  overlay.addEventListener('wheel', e => {
    e.preventDefault();
    const now = Date.now(); if (now - wlock < 350) return; wlock = now;
    go(i + (e.deltaY > 0 ? 1 : -1));
  }, { passive: false });

  document.body.append(overlay);
  render();
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
