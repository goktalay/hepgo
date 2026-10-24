// Dron Yönetimi › Kameralar (#/drone/cameras; yetki RBAC 'drone.cameras': görüntüleme okuma, ekle/düzenle/sil yazma izni).
// Kamera bir DRON KÖPRÜSÜNE bağlanır (görüntü yeteneği olan köprüler önde ve etiketli); köprü (ör. Jetson görüntü köprüsü) RTSP/RTP kaynağını
// kendi ağında açar ve parçalı MP4 olarak sunucuya iter. Ayarlar SİTEDEN köprüye gider (video_cfg) — köprüdeki yerel conf yalnız yedektir.
// FPS "Kaynak FPS" ise (ya da kaynağın FPS'iyle aynıysa) yeniden kodlanmaz; farklı FPS / çözünürlük köprüde yeniden kodlama gerektirir.
// Parola şifreli saklanır, arayüze geri gönderilmez ("değiştirmek için yazın"). Canlı önizleme: MSE oynatıcı (drone_camera.js).
// Canlı Uçuş'ta kamera seçimi, köprü/dron bağlama ve yüzen pencereler: drone.js renderLive + drone_camera.createCameraWindows.
import { api } from '../api.js';
import { clear, confirmDialog, every, field, h, matches, modal, moduleToolbar, onLeave, segmented, statStrip, toast, t as tr } from '../ui.js';
import { createPlayer, openPopout } from './drone_camera.js';
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
const PV_CSS = `
.dpv-back{position:fixed;inset:0;z-index:1000;background:rgba(3,7,12,.78);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;padding:18px;animation:dpvIn .16s ease-out}
@keyframes dpvIn{from{opacity:0}to{opacity:1}}
.dpv{width:min(1180px,100%);max-height:100%;display:flex;flex-direction:column;background:linear-gradient(180deg,#0d1621,#091018);border:1px solid rgba(120,170,220,.18);border-radius:16px;box-shadow:0 24px 70px rgba(0,0,0,.6);color:#dbe7f2;overflow:hidden;font:13px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
.dpv-hd{display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid rgba(120,170,220,.12)}
.dpv-hd .ic{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;background:rgba(56,189,248,.12);color:#7dd3fc;flex:none}
.dpv-hd b{font-size:15px;display:block}.dpv-hd small{color:#8aa0b6}
.dpv-pill{margin-left:auto;display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;font:600 12px system-ui;background:rgba(148,163,184,.12);color:#cbd5e1;white-space:nowrap}
.dpv-pill i{width:8px;height:8px;border-radius:50%;background:#64748b}
.dpv-pill.live{background:rgba(34,197,94,.14);color:#86efac}.dpv-pill.live i{background:#22c55e;box-shadow:0 0 0 0 rgba(34,197,94,.7);animation:dpvPulse 1.6s infinite}
.dpv-pill.warn{background:rgba(245,158,11,.14);color:#fcd34d}.dpv-pill.warn i{background:#f59e0b}
.dpv-pill.err{background:rgba(239,68,68,.14);color:#fca5a5}.dpv-pill.err i{background:#ef4444}
@keyframes dpvPulse{0%{box-shadow:0 0 0 0 rgba(34,197,94,.6)}70%{box-shadow:0 0 0 8px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
.dpv-x{background:none;border:0;color:#8aa0b6;font-size:22px;line-height:1;cursor:pointer;padding:4px 6px;border-radius:8px}.dpv-x:hover{color:#fff;background:rgba(255,255,255,.08)}
.dpv-stage{position:relative;aspect-ratio:16/9;background:#000;max-height:calc(100vh - 240px);min-height:200px}
.dpv-stage .drc-player{position:absolute;inset:0}
.dpv-stage .drc-tools{display:none}
.dpv-stage .drc-st{display:none}
.dpv-bar{position:absolute;left:0;right:0;bottom:0;display:flex;align-items:center;gap:8px;padding:28px 12px 10px;background:linear-gradient(transparent,rgba(0,0,0,.75));opacity:0;transition:opacity .18s;z-index:6}
.dpv-stage:hover .dpv-bar,.dpv-bar:focus-within,.dpv-stage.paused .dpv-bar{opacity:1}
.dpv-btn{display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 12px;border-radius:9px;border:1px solid rgba(255,255,255,.16);background:rgba(15,23,32,.72);color:#e2e8f0;font:600 12.5px system-ui;cursor:pointer}
.dpv-btn:hover{background:rgba(30,41,59,.9);border-color:rgba(255,255,255,.3)}
.dpv-btn.main{width:42px;padding:0;justify-content:center;font-size:15px;border-color:rgba(34,197,94,.55);color:#bbf7d0}
.dpv-btn.on{border-color:rgba(56,189,248,.7);color:#7dd3fc}
.dpv-sp{flex:1}
.dpv-ov{position:absolute;left:12px;top:12px;z-index:5;display:flex;gap:6px;pointer-events:none}
.dpv-ov span{font:600 11.5px ui-monospace,SFMono-Regular,Menlo,monospace;color:#e2e8f0;background:rgba(0,0,0,.55);border:1px solid rgba(255,255,255,.12);padding:3px 8px;border-radius:7px}
.dpv-ov span.g{color:#86efac}.dpv-ov span.y{color:#fcd34d}.dpv-ov span.r{color:#fca5a5}
.dpv-stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:1px;background:rgba(120,170,220,.1);border-top:1px solid rgba(120,170,220,.12)}
.dpv-stat{background:#0b131c;padding:10px 14px}
.dpv-stat small{display:block;color:#7f93a8;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.dpv-stat b{display:block;font:600 16px ui-monospace,SFMono-Regular,Menlo,monospace;color:#f1f5f9;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dpv-stat em{font-style:normal;color:#7f93a8;font-size:11px}
.dpv-ft{display:flex;gap:10px;align-items:center;padding:9px 16px;color:#7f93a8;font-size:12px}
@media (max-width:760px){.dpv-stats{grid-template-columns:repeat(3,minmax(0,1fr))}.dpv-back{padding:0}.dpv{border-radius:0;height:100%}}
`;
const fmtMs = v => (v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);
const SVG = d => { const e = h('span'); e.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`; return e.firstChild; };

export function previewModal(c) {
  if (!document.getElementById('dpv-css')) document.head.append(h('style', { id: 'dpv-css' }, PV_CSS));
  const p = createPlayer({ cameraId: c.id, autostart: true });
  const pill = h('span', { class: 'dpv-pill' }, h('i'), h('span', null, tr('Bağlanıyor…')));
  const ovFps = h('span'), ovLat = h('span');
  const ov = h('div', { class: 'dpv-ov' }, ovFps, ovLat);
  const playBtn = h('button', { class: 'dpv-btn main', type: 'button', title: tr('Başlat / Durdur (Boşluk)'), onclick: e => { e.stopPropagation(); toggle(); } }, '■');
  const jpegBtn = h('button', { class: 'dpv-btn', type: 'button', title: tr('Düşük bant: 2 sn\'de bir JPEG'), onclick: e => { e.stopPropagation(); p.setLow(!p.low); jpegBtn.classList.toggle('on', p.low); } }, 'JPEG');
  const photoBtn = h('button', { class: 'dpv-btn', type: 'button', title: tr('Gösterilen kareyi PNG olarak indir'), onclick: async e => {
    e.stopPropagation(); const b = await p.snapshotBlob(); if (!b) { toast(tr('Kare alınamadı'), 'error'); return; }
    const a = h('a', { href: URL.createObjectURL(b), download: `${c.name}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png` }); a.click();
  } }, SVG('<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>'), tr('Fotoğraf'));
  const popBtn = h('button', { class: 'dpv-btn', type: 'button', title: tr('Ayrı pencerede aç'), onclick: e => { e.stopPropagation(); openPopout(c.id, { droneId: c.drone_id }); } },
    SVG('<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/>'));
  const fsBtn = h('button', { class: 'dpv-btn', type: 'button', title: tr('Tam ekran'), onclick: e => { e.stopPropagation(); if (document.fullscreenElement) document.exitFullscreen(); else stage.requestFullscreen?.(); } },
    SVG('<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>'));
  const bar = h('div', { class: 'dpv-bar' }, playBtn, h('span', { class: 'dpv-sp' }), jpegBtn, photoBtn, popBtn, fsBtn);
  const stage = h('div', { class: 'dpv-stage' }, p.el, ov, bar);
  stage.addEventListener('click', e => { if (!e.target.closest('button,select')) toggle(); });
  const tile = (label) => { const b = h('b', null, '—'), em = h('em'); return { el: h('div', { class: 'dpv-stat' }, h('small', null, tr(label)), b, em), b, em }; };
  const T = { fps: tile('FPS'), lat: tile('Gecikme'), rate: tile('Bit hızı'), res: tile('Çözünürlük'), codec: tile('Kodek'), src: tile('Kaynak') };
  const sub = [c.drone_code ? `${c.drone_code} · ${c.drone_name || ''}` : null, c.bridge_name ? tr('köprü {b}', { b: c.bridge_name }) : null,
    c.kind === 'rtsp' ? 'RTSP' : `RTP · UDP ${c.rtp_port}`].filter(Boolean).join(' · ');
  const back = h('div', { class: 'dpv-back' }, h('div', { class: 'dpv', role: 'dialog', 'aria-label': c.name },
    h('div', { class: 'dpv-hd' }, h('span', { class: 'ic' }, SVG('<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/>')),
      h('div', { style: { minWidth: 0 } }, h('b', null, c.name), h('small', null, sub)), pill,
      h('button', { class: 'dpv-x', type: 'button', title: tr('Kapat (Esc)'), onclick: () => close() }, '×')),
    stage,
    h('div', { class: 'dpv-stats' }, Object.values(T).map(x => x.el)),
    h('div', { class: 'dpv-ft' }, tr('Gecikme: karenin köprüye girişinden bu ekranda gösterilmesine kadar geçen süre (saatler eşitlenir). Kamera içi kodlama gecikmesi dahil değildir. Kapatınca ya da ■ ile köprü yayını hemen durdurur.'))));
  const STATE_TONE = { canli: 'live', kare_yok: 'warn', h265: 'warn', kopru_cevrimdisi: 'warn', hata: 'err', yetki: 'err' };
  const update = S => {
    const running = p.running;
    playBtn.textContent = running ? '■' : '▶'; stage.classList.toggle('paused', !running);
    pill.className = `dpv-pill ${STATE_TONE[S.state] || ''}`;
    pill.lastChild.textContent = !running ? tr('Durduruldu') : S.state === 'canli' ? tr('Canlı') : tr(({ baglaniyor: 'Bağlanıyor…', basliyor: 'Kaynak açılıyor…', kare_yok: 'Görüntü yok', hata: 'Kaynak hatası', h265: 'H.265 kaynak', kopru_cevrimdisi: 'Köprü çevrim dışı' })[S.state] || S.state);
    pill.title = S.detail || '';
    const st = S.stat || {};
    const fps = S.fps, srcFps = st.src_fps || st.fps;
    T.fps.b.textContent = fps != null ? fps.toFixed(1) : '—'; T.fps.em.textContent = srcFps ? tr('kaynak {f}', { f: Number(srcFps).toFixed(0) }) : '';
    T.lat.b.textContent = fmtMs(S.latency); T.lat.em.textContent = S.latency == null ? (running && S.state === 'canli' ? tr('ölçülüyor…') : '') : S.latSrc === 'kopru' ? tr('köprü → ekran') : tr('sunucu → ekran (köprü ≥ 1.1.4 gerekir)');
    T.rate.b.textContent = S.kbps ? (S.kbps >= 1000 ? `${(S.kbps / 1000).toFixed(1)} Mbit/s` : `${S.kbps} kbit/s`) : '—'; T.rate.em.textContent = '';
    const v = p.video; T.res.b.textContent = v.videoWidth ? `${v.videoWidth}×${v.videoHeight}` : '—';
    const codec = /hvc1|hev1/.test(S.mime || '') ? 'H.265' : /avc1/.test(S.mime || '') ? 'H.264' : (st.codec || '').toUpperCase() || '—';
    T.codec.b.textContent = codec; T.codec.em.textContent = st.copy === true ? tr('yeniden kodlamasız') : st.copy === false ? tr('köprüde yeniden kodlanıyor') : '';
    T.src.b.textContent = c.kind === 'rtsp' ? 'RTSP' : 'RTP'; T.src.em.textContent = FPS_TEXT(c.fps) === 'Kaynak FPS' ? tr('Kaynak FPS') : FPS_TEXT(c.fps);
    ovFps.textContent = fps != null ? `${fps.toFixed(0)} FPS` : ''; ovFps.hidden = fps == null;
    ovLat.textContent = S.latency != null ? fmtMs(S.latency) : ''; ovLat.hidden = S.latency == null;
    ovLat.className = S.latency == null ? '' : S.latency < 400 ? 'g' : S.latency < 1000 ? 'y' : 'r';
  };
  const offState = p.onState(update);
  function toggle() { if (p.running) p.pause(); else p.start(); update(p.state); }
  const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); close(); } else if (e.key === ' ' && !e.target.closest('input,textarea,select')) { e.preventDefault(); toggle(); } };
  function close() { offState(); p.stop(); document.removeEventListener('keydown', onKey, true); if (document.fullscreenElement) document.exitFullscreen?.(); back.remove(); }
  back.addEventListener('click', e => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.append(back);
  update(p.state);
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
