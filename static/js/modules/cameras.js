// Güvenlik → Kameralar: izleme duvarı (1 / 4 / 6 / 9 / 12 / 16'lı; düzen ve hangi karede hangi kamera kullanıcıya göre
// sunucuda saklanır) ve kamera listesi (ONVIF ile ağda bulma, elle ekleme). Görüntü, kamera servisinin yazdığı son kare
// (/api/cameras/<id>/frame) kısa aralıklarla çekilerek gösterilir; değişmeyen kare için sunucu 304 döner.
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, onLeave, segmented, toast, toastError } from '../ui.js';

const LAYOUTS = [1, 4, 6, 9, 12, 16];
const STATUS = { CANLI: ['green', 'Canlı'], HATA: ['red', 'Bağlanamıyor'], KOPTU: ['yellow', 'Koptu'], KAPALI: ['gray', 'Kapalı'] };
const statusBadge = c => {
  const [cls, label] = STATUS[c.active ? c.status : 'KAPALI'] || ['gray', 'Bekliyor'];
  return h('span', { class: `badge ${cls}`, title: c.error || '' }, label);
};

export async function renderCameras(body, ctx, params) {
  const sub = params[0] === 'list' ? 'list' : 'watch';
  const nav = segmented([['watch', 'İzleme'], ['list', 'Kamera Listesi']], sub,
    v => { location.hash = v === 'list' ? '#/security/cameras/list' : '#/security/cameras'; });
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
  let alive = true;
  onLeave(() => { alive = false; tiles.forEach(t => t.stop()); if (wall.classList.contains('cw-full')) setFull(false); });

  function tile(i) {
    const img = h('img', { alt: '' });
    const over = h('div', { class: 'cw-over' });
    const sel = h('select', { class: 'cw-sel', title: 'Bu karede gösterilecek kamera' },
      h('option', { value: '' }, '— Boş —'), cams.map(c => h('option', { value: c.id, selected: c.id === cfg.slots[i] }, c.name)));
    const el = h('div', { class: 'cw-tile' }, img, over, h('div', { class: 'cw-head' }, sel));
    let etag = null, url = null, stopped = false;
    const camId = () => Number(sel.value) || null;
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
    loop();
    return { el, stop: () => { stopped = true; clearTimeout(timer); if (url) URL.revokeObjectURL(url); } };
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
  clear(box, cams.length ? wall : h('div', { class: 'card empty' }, 'Kayıtlı kamera yok. "Kamera Listesi"nden ekleyin ya da ağda bulun.'));
  draw();
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
          h('button', { class: 'btn sm ghost', onclick: () => cameraForm(c, load) }, 'Düzenle'),
          h('button', { class: 'btn sm ghost', onclick: async () => {
            if (!await confirmDialog('Kamerayı sil', `${c.name} silinsin mi? Yüz kayıtları silinmez.`, { okLabel: 'Sil', danger: true })) return;
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
    title: c ? `${c.name} — Düzenle` : 'Kamera Ekle', wide: true,
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
      toast(`${ok} kamera eklendi${bad.length ? `; ${bad.length} eklenemedi: ${bad.map(b => `${b.ip} (${b.error})`).join(', ')}` : ''}`, bad.length ? 'err' : '');
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
