// Şirketten Haberler: pano akışı (Facebook tarzı) — sistem olayları + kullanıcı paylaşımları (resim/video/ses + konum).
// İki görünüm: Akış ve Harita. Sistem olaylarında şirket logosu, kullanıcı paylaşımında kişinin fotoğrafı.
import { api, fileUrl, upload } from '../api.js';
import { loadMaps } from '../maps.js';
import { avatar, clear, confirmDialog, fmtDateTime, h, modal, segmented, t, toast, toastError } from '../ui.js';

const KIND_BADGE = {
  HIRE: ['green', 'İşe alım'], TERMINATION: ['', 'Ayrılış'], FLIGHT: ['blue', 'Uçuş'],
  ORDER: ['blue', 'Sipariş'], MEETING: ['yellow', 'Toplantı'], ANNOUNCE: ['red', 'Duyuru'], USER: ['', ''],
};
const LOGO = '/static/img/logo-mark.png';

export function renderFeed(container, ctx) {
  let view = 'feed', posts = [];
  const body = h('div', { class: 'feed-body' });
  const seg = segmented([['feed', 'Akış'], ['map', 'Harita']], view, v => { view = v; draw(); }, { tabs: true });
  const shareBtn = h('button', { class: 'btn sm primary', type: 'button', onclick: () => compose(load) }, '＋ Paylaş');
  clear(container, h('div', { class: 'feed-bar' }, seg, h('span', { class: 'spacer' }), shareBtn), body);

  const mediaEl = m => {
    if (m.type === 'video') return h('video', { class: 'feed-media', src: fileUrl(m.path), controls: true, preload: 'metadata', playsinline: true });
    if (m.type === 'audio') return h('audio', { class: 'feed-audio', src: fileUrl(m.path), controls: true, preload: 'none' });
    return h('img', { class: 'feed-media', src: fileUrl(m.path, 1000), alt: '', loading: 'lazy', onclick: () => modal({ title: '', wide: true, body: h('img', { class: 'feed-media-full', src: fileUrl(m.path) }), actions: [{ label: 'Kapat' }] }) });
  };
  const postCard = p => {
    const badge = KIND_BADGE[p.kind] || KIND_BADGE.USER;
    const canDel = p.author_id === ctx.user.id || ctx.user.master || ctx.user.modules.includes('admin');
    return h('div', { class: 'feed-post' },
      h('div', { class: 'feed-ph' },
        p.system ? h('img', { class: 'feed-ava', src: LOGO, alt: '' }) : avatar({ full_name: p.author_name, photo: p.author_photo }, 40),
        h('div', { class: 'grow' }, h('b', null, p.system ? (ctx.meta?.company || 'Şirket') : (p.author_name || 'Kullanıcı')),
          h('small', { class: 'muted' }, fmtDateTime(p.created_at), p.lat ? ' · 📍' : '')),
        badge[1] ? h('span', { class: `badge ${badge[0]}` }, badge[1]) : null,
        canDel ? h('button', { class: 'feed-x', type: 'button', title: 'Sil', onclick: () => del(p) }, '×') : null),
      p.text ? h('div', { class: 'feed-text' }, p.ref_link ? h('a', { href: p.ref_link }, p.text) : p.text) : null,
      p.media?.length ? h('div', { class: `feed-medias n${Math.min(p.media.length, 4)}` }, p.media.map(mediaEl)) : null);
  };

  let drawMap;
  function draw() {
    seg.querySelectorAll('button').forEach((b, i) => b.classList.toggle('on', ['feed', 'map'][i] === view));
    if (view === 'map') return drawMap();
    clear(body, posts.length ? h('div', { class: 'feed-list' }, posts.map(postCard))
      : h('div', { class: 'card empty' }, 'Henüz paylaşım yok. İlk paylaşımı sen ekle!'));
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
    try { posts = (await api.get('/api/feed')).posts; draw(); }
    catch (err) { clear(body, h('div', { class: 'card empty' }, err.message)); }
  }
  load();
  return { reload: load };
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
