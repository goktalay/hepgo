// Güvenlik → Kameralar: izleme duvarı (1 / 4 / 6 / 9 / 12 / 16'lı; düzen ve hangi karede hangi kamera kullanıcıya göre
// sunucuda saklanır) ve kamera listesi (ONVIF ile ağda bulma, elle ekleme). Görüntü, kamera servisinin yazdığı son kare
// (/api/cameras/<id>/frame) kısa aralıklarla çekilerek gösterilir; değişmeyen kare için sunucu 304 döner.
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, onLeave, segmented, t, toast, toastError } from '../ui.js';

const LAYOUTS = [1, 4, 6, 9, 12, 16];
const STATUS = { CANLI: ['green', 'Canlı'], HATA: ['red', 'Bağlanamıyor'], KOPTU: ['yellow', 'Koptu'], KAPALI: ['gray', 'Kapalı'] };
const statusBadge = c => {
  const [cls, label] = STATUS[c.active ? c.status : 'KAPALI'] || ['gray', 'Bekliyor'];
  return h('span', { class: `badge ${cls}`, title: c.error || '' }, label);
};

export async function renderCameras(body, ctx, params) {
  const sub = params[0] === 'list' ? 'list' : 'watch';
  const nav = segmented([['watch', 'İzleme'], ['list', 'Kamera Listesi']], sub,
    v => { location.hash = v === 'list' ? '#/cameras/list' : '#/cameras'; }, { tabs: true });
  const box = h('div');
  clear(body, h('div', { class: 'filters' }, nav), box);
  return sub === 'list' ? renderList(box) : renderWall(box);
}

// ---------- İzleme duvarı
async function renderWall(box) {
  const [cams, saved] = await Promise.all([api.get('/api/cameras'), api.get('/api/me/prefs/camera.wall').catch(() => ({}))]);
  let cfg = { layout: 4, slots: [] };
  try { cfg = { ...cfg, ...JSON.parse(saved.value || '{}') }; } catch { /* varsayılan */ }
  const active = cams.filter(c => c.active);
  if (!cfg.slots.length) cfg.slots = active.map(c => c.id);   // ilk açılış: kameralar sırayla
  let saveTimer;
  const save = () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => api.put('/api/me/prefs/camera.wall', { value: JSON.stringify(cfg) }).catch(() => {}), 600);
  };
  const grid = h('div', { class: 'cw-grid' });
  const wall = h('div', { class: 'cw' });
  let tiles = [];
  let overlays = {};   // cam_id → [{x,y,w,h,known,label}]
  let alive = true;
  onLeave(() => { alive = false; tiles.forEach(t => t.stop()); if (wall.classList.contains('cw-full')) setFull(false); });
  // Yüz çerçevelerini toplu çek (görünen kameralar için) ve her kareye çizdir
  async function overlayLoop() {
    if (!alive) return;
    const ids = [...new Set(tiles.map(t => t.camId()).filter(Boolean))];
    if (ids.length) {
      try { overlays = (await api.get(`/api/cameras/overlays?ids=${ids.join(',')}`)).overlays || {}; tiles.forEach(t => t.drawBoxes()); } catch { /* */ }
    }
    if (alive) setTimeout(overlayLoop, 500);
  }
  const onResize = () => tiles.forEach(t => t.drawBoxes());
  window.addEventListener('resize', onResize);
  onLeave(() => window.removeEventListener('resize', onResize));

  function tile(i) {
    const img = h('img', { alt: '' });
    const canvas = h('canvas', { class: 'cw-canvas' });
    const over = h('div', { class: 'cw-over' });
    const sel = h('select', { class: 'cw-sel', title: 'Bu karede gösterilecek kamera' },
      h('option', { value: '' }, '— Boş —'), cams.map(c => h('option', { value: c.id, selected: c.id === cfg.slots[i] }, c.name)));
    const el = h('div', { class: 'cw-tile' }, img, canvas, over, h('div', { class: 'cw-head' }, sel));
    let etag = null, url = null, stopped = false;
    const camId = () => Number(sel.value) || null;
    // Yüz çerçeveleri: bilinen=yeşil + ad, bilinmeyen=kırmızı. Normalize kutular görüntünün (contain) konumuna ölçeklenir.
    const drawBoxes = () => {
      const boxes = overlays[camId()] || [];
      const W = el.clientWidth, H = el.clientHeight;
      canvas.width = W; canvas.height = H;
      const cx = canvas.getContext('2d');
      cx.clearRect(0, 0, W, H);
      if (!boxes.length || !img.naturalWidth) return;
      const scale = Math.min(W / img.naturalWidth, H / img.naturalHeight);
      const dw = img.naturalWidth * scale, dh = img.naturalHeight * scale;
      const ox = (W - dw) / 2, oy = (H - dh) / 2;
      cx.lineWidth = Math.max(2, Math.round(W / 320)); cx.font = `${Math.max(12, Math.round(W / 36))}px sans-serif`;
      for (const b of boxes) {
        const x = ox + b.x * dw, y = oy + b.y * dh, w = b.w * dw, hgt = b.h * dh;
        const col = b.known ? '#16a34a' : '#dc2626';
        cx.strokeStyle = col; cx.strokeRect(x, y, w, hgt);
        const label = b.known ? (b.label || 'Tanınan') : null;
        if (label) {
          const tw = cx.measureText(label).width + 10, th = Math.max(16, Math.round(W / 28));
          cx.fillStyle = col; cx.fillRect(x, y + hgt, Math.max(w, tw), th);
          cx.fillStyle = '#fff'; cx.textBaseline = 'middle'; cx.fillText(label, x + 5, y + hgt + th / 2);
        }
      }
    };
    sel.addEventListener('change', () => { cfg.slots[i] = camId(); save(); etag = null; img.removeAttribute('src'); loop(); });
    el.addEventListener('dblclick', e => { if (e.target !== sel) el.classList.toggle('max'); });
    const period = () => (cfg.layout <= 4 ? 250 : cfg.layout <= 9 ? 400 : 600);
    let timer;
    async function loop() {
      clearTimeout(timer);
      if (stopped || !alive) return;
      const id = camId();
      if (!id) { over.textContent = 'Kamera seçin'; over.hidden = false; return; }
      try {
        const r = await fetch(`/api/cameras/${id}/frame`, { headers: etag ? { 'If-None-Match': etag } : {}, credentials: 'same-origin' });
        if (r.status === 200) {
          etag = r.headers.get('ETag');
          const next = URL.createObjectURL(await r.blob());
          img.src = next;
          if (url) URL.revokeObjectURL(url);
          url = next;
        }
        const age = Number(r.headers.get('X-Frame-Age') || 0);
        over.hidden = r.ok || r.status === 304 ? age < 15 : false;
        over.textContent = r.status === 404 ? 'Görüntü yok' : age >= 15 ? 'Görüntü güncel değil' : '';
      } catch { over.hidden = false; over.textContent = 'Bağlantı yok'; }
      if (camId() === id) timer = setTimeout(loop, period());
    }
    img.addEventListener('load', drawBoxes);
    loop();
    return { el, camId, drawBoxes, stop: () => { stopped = true; clearTimeout(timer); if (url) URL.revokeObjectURL(url); } };
  }

  function draw() {
    tiles.forEach(t => t.stop());
    tiles = Array.from({ length: cfg.layout }, (_, i) => tile(i));
    grid.className = `cw-grid l${cfg.layout}`;
    clear(grid, tiles.map(t => t.el));
  }
  const layoutSeg = segmented(LAYOUTS.map(n => [String(n), `${n}'lı`]), String(cfg.layout), v => { cfg.layout = Number(v); save(); draw(); });
  const fullBtn = h('button', { class: 'btn', type: 'button', onclick: () => setFull(!wall.classList.contains('cw-full')) }, 'Tam ekran');
  function setFull(on) {
    wall.classList.toggle('cw-full', on);
    fullBtn.textContent = on ? 'Tam ekrandan çık' : 'Tam ekran';
    if (on && !document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
    if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }
  const onFs = () => { if (!document.fullscreenElement && wall.classList.contains('cw-full')) setFull(false); };
  document.addEventListener('fullscreenchange', onFs);
  onLeave(() => document.removeEventListener('fullscreenchange', onFs));
  const autoBtn = h('button', { class: 'btn', type: 'button', onclick: () => { cfg.slots = active.map(c => c.id); save(); draw(); } }, 'Sırayla yerleştir');
  wall.append(h('div', { class: 'cw-bar' }, h('span', { class: 'small muted' }, 'Düzen'), layoutSeg, autoBtn, h('span', { class: 'spacer' }),
    h('span', { class: 'small muted' }, 'Kareye çift tıklayınca büyür'), fullBtn), grid);
  clear(box, cams.length ? wall : h('div', { class: 'card empty' }, 'Kayıtlı kamera yok. NVR entegrasyonunda kanallarda yüz tanımayı açın.'));
  draw();
  overlayLoop();
}

// ---------- Kamera listesi
async function renderList(box) {
  const out = h('div');
  const load = async () => {
    const cams = await api.get('/api/cameras');
    clear(out, cams.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Kamera', 'Yer', 'IP', 'Model', 'Durum', 'Son kare', 'Yüz tanıma', ''].map(t => h('th', null, t)))),
      h('tbody', null, cams.map(c => h('tr', null,
        h('td', null, h('b', null, c.name), h('div', { class: 'small muted mono' }, c.stream_url || '—')),
        h('td', null, c.location || '—'), h('td', { class: 'mono' }, c.ip || '—'),
        h('td', null, [c.manufacturer, c.model].filter(Boolean).join(' ') || '—'),
        h('td', null, statusBadge(c), c.error && c.status !== 'CANLI' ? h('div', { class: 'small muted' }, c.error) : null),
        h('td', { class: 'muted' }, c.live_age != null ? (c.live_age < 15 ? 'şimdi' : fmtDateTime(c.last_frame_at)) : '—'),
        h('td', null, c.faces ? 'Açık' : 'Kapalı'),
        h('td', { class: 'num' },
          h('button', { class: 'btn sm ghost', onclick: () => renameCamera(c, load) }, 'Yeniden Adlandır'),
          h('button', { class: 'btn sm ghost', onclick: () => cameraForm(c, load) }, 'Düzenle'),
          h('button', { class: 'btn sm ghost', onclick: async () => {
            if (!await confirmDialog('Kamerayı sil', t('{name} silinsin mi? Yüz kayıtları silinmez.', { name: c.name }), { okLabel: 'Sil', danger: true })) return;
            try { await api.del(`/api/cameras/${c.id}`); toast('Kamera silindi'); load(); } catch (err) { toastError(err); }
          } }, 'Sil'))))))))
      : h('div', { class: 'card empty' }, 'Kayıtlı kamera yok'));
  };
  clear(box, h('div', { class: 'filters' },
    h('span', { class: 'small muted' }, 'Kameralar arka plandaki kamera servisi tarafından sürekli izlenir; yüz tanıma kamera başına açılıp kapatılır.'),
    h('span', { class: 'spacer' }),
    h('button', { class: 'btn', type: 'button', onclick: () => discover(load) }, 'Ağda Bul (ONVIF)'),
    h('button', { class: 'btn primary', type: 'button', onclick: () => cameraForm(null, load) }, '+ Kamera Ekle')), out);
  await load();
}

// Kamerayı yeniden adlandır (NVR kanalı için ad kalıcı olur ve canlı görünümde görünür)
function renameCamera(c, done) {
  const inp = h('input', { class: 'input', value: c.name || '', placeholder: 'Ör. Giriş kapısı, Üretim hattı, Depo' });
  modal({
    title: 'Kamerayı yeniden adlandır',
    body: field('Kamera adı', inp),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const name = inp.value.trim();
      if (!name) throw new Error('Ad boş olamaz');
      await api.put(`/api/cameras/${c.id}/name`, { name });
      toast('Kamera adı güncellendi'); done?.();
    } }],
  });
  setTimeout(() => inp.focus(), 50);
}

function cameraForm(c, done) {
  const inp = (v, attrs = {}) => h('input', { class: 'input', value: v ?? '', ...attrs });
  const f = {
    name: inp(c?.name, { placeholder: 'Ör. Giriş kapısı' }), location: inp(c?.location, { placeholder: 'Ör. Ana giriş, otopark' }),
    ip: inp(c?.ip, { placeholder: '192.168.1.64', inputmode: 'decimal' }), port: inp(c?.port, { type: 'number', placeholder: '80' }),
    username: inp(c?.username, { placeholder: 'admin', autocomplete: 'off' }),
    password: inp('', { type: 'password', placeholder: c ? 'Değiştirmek için yazın' : 'Kamera şifresi', autocomplete: 'new-password' }),
    stream: inp(c?.stream_url, { placeholder: 'Boş bırakırsanız ONVIF ile alınır (rtsp://…)' }),
    faces: h('input', { type: 'checkbox', checked: c ? !!c.faces : true }),
    active: h('input', { type: 'checkbox', checked: c ? !!c.active : true }),
  };
  modal({
    title: c ? t('{name} — Düzenle', { name: c.name }) : 'Kamera Ekle', wide: true,
    body: h('div', null,
      h('div', { class: 'row' }, field('Kamera adı', f.name), field('Yeri', f.location)),
      h('div', { class: 'row' }, field('IP adresi', f.ip), field('ONVIF portu (isteğe bağlı)', f.port)),
      h('div', { class: 'row' }, field('Kullanıcı adı', f.username), field('Şifre', f.password)),
      field('Akış adresi', f.stream),
      h('label', { class: 'check' }, f.faces, 'Yüz tanıma'), h('label', { class: 'check' }, f.active, 'Etkin (izle)'),
      h('p', { class: 'small muted' }, 'Şifre şifrelenerek saklanır ve bir daha gösterilmez.')),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const body = { name: f.name.value, location: f.location.value, ip: f.ip.value, port: Number(f.port.value) || null,
        username: f.username.value, password: f.password.value, stream_url: f.stream.value, faces: f.faces.checked, active: f.active.checked };
      if (c) await api.put(`/api/cameras/${c.id}`, body); else await api.post('/api/cameras', body);
      toast('Kamera kaydedildi');
      done();
    } }],
  });
}

async function discover(done) {
  const list = h('div', { class: 'pick-list multi' }, h('div', { class: 'empty' }, 'Ağ taranıyor…'));
  const user = h('input', { class: 'input', placeholder: 'admin', autocomplete: 'off' });
  const pass = h('input', { class: 'input', type: 'password', autocomplete: 'new-password' });
  const chosen = new Map();
  const m = modal({
    title: 'Ağda Kamera Bul (ONVIF)', wide: true,
    body: h('div', null, list, h('div', { class: 'row', style: { marginTop: '12px' } }, field('Kullanıcı adı (seçilenler için)', user), field('Şifre', pass))),
    actions: [{ label: 'Kapat' }, { label: 'Seçilenleri Ekle', class: 'primary', onClick: async () => {
      if (!chosen.size) throw new Error('Kamera seçin');
      const res = await api.post('/api/cameras/add-discovered', { items: [...chosen.values()], username: user.value, password: pass.value });
      const ok = res.filter(r => r.ok).length;
      const bad = res.filter(r => !r.ok);
      toast(t('{ok} kamera eklendi{rest}', { ok, rest: bad.length ? t('; {n} eklenemedi: {list}', { n: bad.length, list: bad.map(b => `${b.ip} (${b.error})`).join(', ') }) : '' }), bad.length ? 'err' : '');
      done();
      return bad.length ? true : undefined;   // hata varsa pencere açık kalır
    } }],
  });
  try {
    const found = await api.post('/api/cameras/discover');
    clear(list, found.length ? found.map(d => {
      const cb = h('input', { type: 'checkbox', disabled: d.added });
      const row = h('div', { class: `pick ${d.added ? 'muted' : ''}` }, cb,
        h('div', { class: 'grow' }, h('b', null, d.name || d.hardware || 'ONVIF kamera'), h('span', { class: 'small muted mono' }, ` ${d.ip}`),
          d.added ? h('span', { class: 'badge gray', style: { marginLeft: '8px' } }, 'Kayıtlı') : null));
      row.addEventListener('click', e => {
        if (d.added) return;
        if (e.target !== cb) cb.checked = !cb.checked;
        cb.checked ? chosen.set(d.ip, d) : chosen.delete(d.ip);
        row.classList.toggle('on', cb.checked);
      });
      return row;
    }) : h('div', { class: 'empty' }, 'Ağda ONVIF kamera bulunamadı. Kameranın ONVIF özelliğinin açık ve aynı ağda olduğundan emin olun; ya da "Kamera Ekle" ile IP adresiyle ekleyin.'));
  } catch (err) { clear(list, h('div', { class: 'alert err' }, err.message)); void m; }
}
