// Dron Yönetimi › Kameralar (#/drone/cameras; yetki RBAC 'drone.cameras': görüntüleme okuma, ekle/düzenle/sil yazma izni).
// Kamera bir DRON KÖPRÜSÜNE bağlanır (görüntü yeteneği olan köprüler önde ve etiketli); köprü (ör. Jetson görüntü köprüsü) RTSP/RTP kaynağını
// kendi ağında açar ve parçalı MP4 olarak sunucuya iter. Ayarlar SİTEDEN köprüye gider (video_cfg) — köprüdeki yerel conf yalnız yedektir.
// FPS "Kaynak FPS" ise (ya da kaynağın FPS'iyle aynıysa) yeniden kodlanmaz; farklı FPS / çözünürlük köprüde yeniden kodlama gerektirir.
// Parola şifreli saklanır, arayüze geri gönderilmez ("değiştirmek için yazın"). Canlı önizleme: MSE oynatıcı (drone_camera.js).
// Canlı Uçuş'ta kamera seçimi, köprü/dron bağlama ve yüzen pencereler: drone.js renderLive + drone_camera.createCameraWindows.
import { api } from '../api.js';
import { clear, confirmDialog, every, field, h, matches, modal, moduleToolbar, onLeave, segmented, statStrip, toast, t as tr } from '../ui.js';
import { createPlayer } from './drone_camera.js';
import { FPS_TEXT, STATUS_BADGE } from './drone_camera_core.js';

const inp = (value, attrs = {}) => h('input', { class: 'input', value: value ?? '', ...attrs });
const sel = (options, value, { empty } = {}) => h('select', { class: 'input' },
  empty != null ? h('option', { value: '' }, empty) : null,
  options.map(([k, label]) => h('option', { value: k, selected: String(k) === String(value ?? '') }, label)));
const numOrNull = v => (v === '' || v == null || Number.isNaN(Number(v)) ? null : Number(v));
export const statusBadge = c => h('span', { class: `badge ${STATUS_BADGE[c.status] || 'gray'}`, title: c.detail || '' }, tr(c.status_text || c.status || '—'));

export async function render(view, ctx, m, head) {
  const canWrite = !!m.write?.cameras;
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kamera, dron, köprü ara…', style: { width: '240px' } });
  const status = sel([['', 'Tüm durumlar'], ...Object.entries(m.camera_status || {})], '');
  const stats = statStrip();
  const body = h('div');
  let rows = [];
  const draw = () => {
    const list = rows.filter(c => (!status.value || c.status === status.value) && matches(q.value, c.name, c.drone_code, c.drone_name, c.bridge_name, c.url, c.kind_text));
    stats.set([
      { icon: 'fleet', label: 'Kamera', value: rows.filter(c => c.active).length },
      { icon: 'documents', label: 'Canlı', value: rows.filter(c => c.status === 'canli').length, tone: 'ok' },
      { icon: 'warning', label: 'Görüntü yok', value: rows.filter(c => c.status === 'goruntu_yok').length },
      { icon: 'note', label: 'Köprü çevrim dışı', value: rows.filter(c => c.status === 'kopru_cevrimdisi').length, tone: 'muted' },
    ]);
    clear(body, list.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Kamera', 'Bağlı dron', 'Köprü', 'Görüntü', 'Durum', ''].map(c => h('th', null, c)))),
      h('tbody', null, list.map(c => h('tr', null,
        h('td', null, h('b', null, c.name), c.active ? null : h('span', { class: 'badge gray', style: { marginLeft: '6px' } }, 'Pasif'),
          h('div', { class: 'small muted mono' }, c.kind === 'rtsp' ? `RTSP · ${c.url || ''}${c.has_password ? ` · ${tr('parolalı')}` : ''}` : `RTP · UDP ${c.rtp_port} · ${c.codec === 'h265' ? 'H.265' : 'H.264'}`)),
        h('td', null, c.drone_code ? `${c.drone_code} · ${c.drone_name || ''}` : h('span', { class: 'muted' }, '—')),
        h('td', null, c.bridge_name || h('span', { class: 'muted' }, 'Seçilmedi'),
          c.eff_bridge_id && c.eff_bridge_id !== c.bridge_id ? h('div', { class: 'small muted' }, tr('Açık görevde başka köprü (#{id})', { id: c.eff_bridge_id })) : null,
          c.bridge_id ? h('div', null, c.bridge_video ? h('span', { class: 'badge teal' }, 'Görüntü köprüsü') : h('span', { class: 'badge yellow', title: 'Bu köprü görüntü yeteneği bildirmedi (Linux/Jetson köprüsü gerekir)' }, 'Görüntü yeteneği yok')) : null),
        h('td', { class: 'small' }, tr(FPS_TEXT(c.fps)), c.width ? ` · ${c.width}×${c.height}` : '', c.bitrate_kbps ? ` · ${c.bitrate_kbps} kbit/sn` : ''),
        h('td', null, statusBadge(c), c.stat?.kbps ? h('div', { class: 'small muted' }, `${c.stat.kbps} kbit/sn · ${c.stat.fps ?? '—'} fps${c.stat.copy ? tr(' · yeniden kodlamasız') : ''}`) : null,
          c.detail && c.status !== 'canli' ? h('div', { class: 'small muted', style: { maxWidth: '260px' } }, tr(c.detail)) : null),
        h('td', { class: 'num' }, h('div', { class: 'pill-group' },
          c.active ? h('button', { class: 'btn sm primary', onclick: () => previewModal(c) }, 'Önizle') : null,
          c.active ? h('button', { class: 'btn sm', title: 'Tek kare JPEG (düşük bant; yayın açık olmasa da)', onclick: () => snapshotModal(c) }, 'Anlık görüntü') : null,
          canWrite ? h('button', { class: 'btn sm', onclick: () => cameraForm(c, m, load) }, 'Düzenle') : null,
          canWrite ? h('button', { class: 'btn sm', onclick: async () => { await api.post(`/api/drone/cameras/${c.id}/active`, { active: !c.active }); toast(c.active ? 'Kamera pasife alındı' : 'Kamera etkinleştirildi'); load(); } }, c.active ? 'Pasife al' : 'Etkinleştir') : null,
          canWrite ? h('button', { class: 'btn sm danger', onclick: async () => {
            if (!await confirmDialog('Kamerayı sil', tr('{name} silinsin mi? Köprü bu kamerayı yayınlamayı bırakır; görevlerdeki seçimi de kalkar.', { name: c.name }), { okLabel: 'Sil', danger: true })) return;
            await api.del(`/api/drone/cameras/${c.id}`); toast('Kamera silindi'); load();
          } }, 'Sil') : null)))))))
      : h('div', { class: 'card empty' }, rows.length ? 'Filtreye uyan kamera yok'
        : 'Henüz kamera yok. Dronun gimbal / EO kamerasını (RTSP ya da RTP) ekleyip görüntüyü taşıyacak köprüyü seçin; köprü (ör. Jetson üzerindeki Hepgo Dron Köprüsü) kaynağı kendi ağında açar ve görüntüyü buraya iter.'));
  };
  const load = async () => { rows = await api.get('/api/drone/cameras'); draw(); };
  q.addEventListener('input', draw);
  status.addEventListener('change', draw);
  clear(view, head('Kameralar · dron kameraları, görüntü köprüsü ve canlı önizleme'),
    stats,
    moduleToolbar(canWrite ? h('button', { class: 'btn primary', onclick: () => cameraForm(null, m, load) }, '＋ Yeni Kamera') : null, q, status),
    body);
  await load();
  every(5000, () => load().catch(() => {}));
}

// ---------- form ----------
export async function cameraForm(c, m, done) {
  const [bridges, drones] = await Promise.all([api.get('/api/drone/bridges').catch(() => []), api.get('/api/drone/drones').catch(() => [])]);
  // görüntü yeteneği olan köprüler önde ve etiketli
  const bOpts = [...bridges].sort((a, b) => (b.video - a.video) || a.name.localeCompare(b.name, 'tr'))
    .map(b => [b.id, `${b.name}${b.video ? tr(' · görüntü') : ''}${b.online || b.video_online ? tr(' · çevrimiçi') : ''}${b.active ? '' : tr(' · pasif')}`]);
  const name = inp(c?.name, { placeholder: 'Örn. Gimbal (Siyi A8)', maxlength: 80 });
  const drone = sel(drones.filter(d => d.active || d.id === c?.drone_id).map(d => [d.id, `${d.code} · ${d.name}`]), c?.drone_id, { empty: 'Dron seçilmedi' });
  const bridge = sel(bOpts, c?.bridge_id, { empty: 'Köprü seçilmedi' });
  const bridgeHint = h('div', { class: 'hint' });
  const setBridgeHint = () => {
    const b = bridges.find(x => String(x.id) === bridge.value);
    bridgeHint.textContent = !b ? tr('Görüntüyü taşıyacak köprü: dronun kamerasıyla aynı ağdaki köprü (ör. dron üzerindeki Jetson).')
      : b.video ? tr('Bu köprü görüntü yeteneği bildirdi; ayarlar kaydedilince köprüye gönderilir.')
        : tr('Bu köprü görüntü yeteneği bildirmedi (Windows köprüsü). Linux / Jetson köprüsünü kurun; Dron Köprüleri sayfasından indirilebilir.');
  };
  bridge.addEventListener('change', setBridgeHint); setBridgeHint();
  let kind = c?.kind === 'rtp' ? 'rtp' : 'rtsp';
  const url = inp(c?.url, { placeholder: 'rtsp://192.168.144.25:8554/main.264', maxlength: 500, class: 'input mono' });
  let transport = c?.transport === 'udp' ? 'udp' : 'tcp';
  const transSeg = segmented([['tcp', 'TCP'], ['udp', 'UDP']], transport, k => { transport = k; });
  const user = inp(c?.username, { placeholder: 'Kullanıcı adı (isteğe bağlı)', maxlength: 120, autocomplete: 'off' });
  const pass = inp('', { type: 'password', placeholder: c?.has_password ? 'Kayıtlı — değiştirmek için yazın' : 'Parola (isteğe bağlı)', autocomplete: 'new-password', maxlength: 200 });
  const clearPw = h('input', { type: 'checkbox' });
  const port = inp(c?.rtp_port ?? 5600, { type: 'number', min: 1024, max: 65535 });
  const codec = sel([['h264', 'H.264'], ['h265', 'H.265 (tarayıcı desteği sınırlı)']], c?.codec || 'h264');
  const codecWarn = h('div', { class: 'hint', style: { color: 'var(--warning, #b7791f)' } });
  const setCodecWarn = () => { codecWarn.textContent = codec.value === 'h265' ? tr('H.265 çoğu tarayıcıda oynatılamaz: kaynakta H.264 seçin ya da köprü ayarında h265 = yeniden_kodla (Jetson donanım kodlayıcıyla).') : ''; };
  codec.addEventListener('change', setCodecWarn); setCodecWarn();
  const pt = inp(c?.payload_type ?? 96, { type: 'number', min: 96, max: 127 });
  const sdp = h('textarea', { class: 'input mono', rows: 4, placeholder: 'İsteğe bağlı SDP metni (v=0 … m=video …). Boşsa köprü port, kodek ve yük türünden üretir.' }, c?.sdp || '');
  const fps = sel((m.camera_fps || [0, 5, 10, 15, 20, 25, 30]).map(v => [v, tr(FPS_TEXT(v))]), c?.fps ?? 0);
  const fpsHint = h('div', { class: 'hint' });
  const width = inp(c?.width, { type: 'number', min: 160, max: 3840, placeholder: 'Genişlik' });
  const height = inp(c?.height, { type: 'number', min: 120, max: 2160, placeholder: 'Yükseklik' });
  const bitrate = inp(c?.bitrate_kbps, { type: 'number', min: 100, max: 20000, placeholder: 'kbit/sn (ör. 2000)' });
  const setFpsHint = () => {
    const re = Number(fps.value) || width.value || height.value;
    fpsHint.textContent = re ? tr('Köprüde yeniden kodlanır (Jetson: donanım kodlayıcı nvv4l2h264enc; yoksa x264). FPS kaynakla aynıysa ve çözünürlük boşsa kopyalanır.')
      : tr('Kaynak FPS: görüntü yeniden kodlanmadan iletilir (en düşük gecikme ve işlemci yükü).');
  };
  [fps, width, height].forEach(x => x.addEventListener('input', setFpsHint)); setFpsHint();
  const note = h('textarea', { class: 'input', rows: 2 }, c?.note || '');
  const activeCb = h('input', { type: 'checkbox', checked: c ? !!c.active : true });
  const rtspBox = h('div', null,
    field('RTSP adresi', url, 'Kullanıcı adı ve parolayı adrese değil aşağıya yazın (parola şifreli saklanır).'),
    h('div', { class: 'row' }, field('Taşıma', transSeg), field('Kullanıcı adı', user)),
    field('Parola', pass), c?.has_password ? h('label', { class: 'check' }, clearPw, 'Kayıtlı parolayı sil') : null);
  const rtpBox = h('div', null,
    h('div', { class: 'row' }, field('Dinleme portu (köprüde UDP)', port), field('Yük türü', pt)),
    field('Kodek', codec), codecWarn, field('SDP (isteğe bağlı)', sdp));
  const setKind = () => { rtspBox.hidden = kind !== 'rtsp'; rtpBox.hidden = kind !== 'rtp'; };
  const kindSeg = segmented([['rtsp', 'RTSP'], ['rtp', 'RTP']], kind, k => { kind = k; setKind(); });
  setKind();
  modal({
    title: c ? tr('{name} · kamera', { name: c.name }) : 'Yeni Kamera',
    wide: true,
    body: h('div', null,
      h('div', { class: 'row' }, field('Kamera adı', name), field('Bağlı dron', drone, 'Dron paneli ve Canlı Uçuş penceresinde bu dronun telemetrisi HUD\'da gösterilir.')),
      field('Köprü', bridge), bridgeHint,
      h('div', { class: 'field' }, h('label', null, 'Bağlantı türü'), kindSeg),
      rtspBox, rtpBox,
      h('div', { class: 'row' }, field('FPS', fps), field('Bit hızı', bitrate)), fpsHint,
      h('div', { class: 'row' }, field('Çözünürlük (isteğe bağlı)', h('div', { style: { display: 'flex', gap: '6px' } }, width, height))),
      field('Not', note),
      h('label', { class: 'check' }, activeCb, 'Etkin (köprü izleyici olunca yayınlar)')),
    actions: [{ label: 'Vazgeç' }, {
      label: c ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const body = {
          name: name.value.trim(), drone_id: numOrNull(drone.value), bridge_id: numOrNull(bridge.value), kind, fps: Number(fps.value) || 0,
          width: numOrNull(width.value), height: numOrNull(height.value), bitrate_kbps: numOrNull(bitrate.value), note: note.value.trim() || null, active: activeCb.checked,
        };
        if (kind === 'rtsp') Object.assign(body, { url: url.value.trim(), transport, username: user.value.trim() || null, password: pass.value || null, password_clear: !!clearPw.checked });
        else Object.assign(body, { rtp_port: numOrNull(port.value), codec: codec.value, payload_type: numOrNull(pt.value), sdp: sdp.value.trim() || null });
        if (!body.name) throw new Error(tr('Kamera adı gerekli'));
        if (c) { await api.put(`/api/drone/cameras/${c.id}`, body); toast('Kamera güncellendi'); } else { await api.post('/api/drone/cameras', body); toast('Kamera eklendi'); }
        done?.();
      },
    }],
  });
}

// ---------- önizleme / anlık görüntü ----------
export function previewModal(c) {
  const p = createPlayer({ cameraId: c.id });
  modal({
    title: tr('{name} · canlı önizleme', { name: c.name }), wide: true,
    onClose: () => p.stop(),
    body: h('div', null, h('div', { style: { aspectRatio: '16 / 9', borderRadius: '10px', overflow: 'hidden' } }, p.el),
      h('p', { class: 'small muted', style: { marginTop: '8px' } }, 'Görüntü köprüden canlı gelir; ■ Durdur ya da pencereyi kapatınca köprü yayını hemen durdurur. Gecikme sol altta gösterilir; "JPEG" düşük bant kipine geçer.')),
    actions: [{ label: 'Kapat' }],
  });
}

export function snapshotModal(c) {
  const img = h('img', { alt: c.name, style: { width: '100%', borderRadius: '10px', background: '#000', minHeight: '120px' } });
  const info = h('div', { class: 'small muted', style: { marginTop: '6px' } }, 'Köprüden tek kare isteniyor…');
  const pull = () => {
    info.textContent = tr('Köprüden tek kare isteniyor…');
    fetch(`/api/drone/cameras/${c.id}/snapshot.jpg?t=${Date.now()}`, { credentials: 'same-origin' }).then(async r => {
      if (!r.ok) { let e = ''; try { e = (await r.json()).detail; } catch { /* */ } throw new Error(e || `HTTP ${r.status}`); }
      const b = await r.blob(); img.src = URL.createObjectURL(b); info.textContent = `${(b.size / 1024).toFixed(0)} KB · ${new Date().toLocaleTimeString()}`;
    }).catch(e => { info.textContent = tr(e.message); });
  };
  pull();
  modal({ title: tr('{name} · anlık görüntü', { name: c.name }), wide: true, body: h('div', null, img, info),
    actions: [{ label: 'Kapat' }, { label: 'Yenile', class: 'primary', onClick: () => { pull(); return true; } }] });
}

/** Dron detayı kartı: dronun kameraları + tıklayınca satır içi önizleme. */
export function droneCamerasCard(d) {
  const cams = d.cameras || [];
  if (!cams.length) return null;
  const box = h('div');
  let cur = null;
  onLeave(() => { cur?.stop(); cur = null; });   // sayfadan çıkınca akış kapanır
  const show = c => {
    cur?.stop();
    cur = createPlayer({ cameraId: c.id });
    clear(box, h('div', { style: { aspectRatio: '16 / 9', borderRadius: '10px', overflow: 'hidden', marginTop: '8px' } }, cur.el));
  };
  return h('div', { class: 'card card-pad', style: { marginTop: '14px' } }, h('h3', null, tr('Kameralar ({n})', { n: cams.length })),
    h('div', { class: 'pill-group' }, cams.map(c => h('button', { class: 'btn sm', onclick: () => show(c) }, statusBadge(c), ' ', c.name)),
      h('button', { class: 'btn sm', onclick: () => { cur?.stop(); cur = null; clear(box); } }, 'Kapat')),
    box);
}
