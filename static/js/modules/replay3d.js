// Uçuş logunun Cesium ile 3 boyutlu oynatılması (Araçlar → Uçuş Logu Analizi ve saha uçuş raporları).
// Veri: /api/flight-logs/<id>/replay (.bin dosyasından üretilen 5 Hz konum + yönelim serisi).
// Cesium CDN'den yalnızca bu sayfa açılınca yüklenir; arazi modeli yok, irtifa eve (kalkış noktasına) göredir.
import { api } from '../api.js';
import { clear, h, onLeave, pageHead, toastError } from '../ui.js';

const CESIUM = 'https://cdn.jsdelivr.net/npm/cesium@1.145.0/Build/Cesium/';
let cesiumLoading = null;
function loadCesium() {
  if (window.Cesium) return Promise.resolve(window.Cesium);
  cesiumLoading ??= new Promise((resolve, reject) => {
    window.CESIUM_BASE_URL = CESIUM;
    document.head.append(h('link', { rel: 'stylesheet', href: `${CESIUM}Widgets/widgets.css` }));
    const s = h('script', { src: `${CESIUM}Cesium.js` });
    s.onload = () => resolve(window.Cesium);
    s.onerror = () => { cesiumLoading = null; reject(new Error('3B harita kütüphanesi (Cesium) yüklenemedi; internet bağlantısını kontrol edin')); };
    document.head.append(s);
  });
  return cesiumLoading;
}

const f1 = v => (v == null ? '—' : Number(v).toFixed(1));
const clock = sec => {
  sec = Math.max(0, Math.floor(sec));
  const hh = Math.floor(sec / 3600), mm = Math.floor(sec % 3600 / 60), ss = sec % 60;
  return `${hh ? `${hh}:` : ''}${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
};

// embed: sayfa başlığı olmadan verilen kutuya çizilir (ör. uçuş detayındaki "3B Uçuş İzleme" sekmesi)
export async function render3D(view, id, back, { embed = false } = {}) {
  const box = h('div', { class: `r3d-stage ${embed ? 'embed' : ''}` }, h('div', { class: 'r3d-loading' }, '3B oynatma hazırlanıyor…'));
  if (embed) clear(view, box); else clear(view, pageHead('3B Uçuş Oynatma', { back, sub: 'Yükleniyor…' }), box);
  let Cesium, log, data;
  try {
    [Cesium, log, data] = await Promise.all([loadCesium(), api.get(`/api/flight-logs/${id}`), api.get(`/api/flight-logs/${id}/replay`)]);
  } catch (err) {
    clear(box, h('div', { class: 'card card-pad' }, h('div', { class: 'alert err', style: { margin: 0 } }, err.message)));
    return;
  }
  const a = log.analysis || {};
  const S = data.samples;   // [t, lat, lng, alt, roll, pitch, yaw, gs, as, thr, volt]
  const modes = a.modes || [];
  const flying = a.flying || [];
  const start = Cesium.JulianDate.fromIso8601(a.summary?.start_utc || '2000-01-01T00:00:00Z');
  const at = t => Cesium.JulianDate.addSeconds(start, t, new Cesium.JulianDate());
  const duration = S[S.length - 1][0];

  if (!embed) clear(view, pageHead('3B Uçuş Oynatma', { back, sub: `${log.file_name}${log.aircraft ? ` · ${log.aircraft}` : ''}` }), box);
  clear(box);
  const holder = h('div', { class: 'r3d-map' });
  const hud = h('div', { class: 'r3d-hud' });
  const tools = h('div', { class: 'r3d-tools' });
  box.append(holder, hud, tools);

  Cesium.Ion.defaultAccessToken = '';
  const satellite = Cesium.ImageryLayer.fromProviderAsync(
    Cesium.ArcGisMapServerImageryProvider.fromUrl('https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer'));
  const viewer = new Cesium.Viewer(holder, {
    baseLayer: satellite, terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false, navigationHelpButton: false,
    infoBox: false, selectionIndicator: false, fullscreenButton: true, timeline: true, animation: true,
    shouldAnimate: false,
  });
  viewer.scene.globe.enableLighting = false;
  viewer.scene.skyAtmosphere.show = true;
  let destroyed = false;
  onLeave(() => { destroyed = true; if (!viewer.isDestroyed()) viewer.destroy(); });
  // sekme değişip kutu sayfadan kalkınca oynatıcı kapanır (arka planda çizmeye devam etmesin)
  const gone = setInterval(() => {
    if (!box.isConnected) { clearInterval(gone); destroyed = true; if (!viewer.isDestroyed()) viewer.destroy(); }
  }, 1000);
  onLeave(() => clearInterval(gone));

  // Konum ve yönelim örnekleri. Model burnu Cesium +X'te (heading 0 = doğu): heading = yaw - 90°;
  // pitch burun yukarı +, roll sağ kanat aşağı + (ArduPilot ile aynı)
  const position = new Cesium.SampledPositionProperty();
  const orientation = new Cesium.SampledProperty(Cesium.Quaternion);
  const toRad = Cesium.Math.toRadians;
  const pts = [];
  for (const s of S) {
    const p = Cesium.Cartesian3.fromDegrees(s[2], s[1], Math.max(s[3], 0) + 1);
    const time = at(s[0]);
    position.addSample(time, p);
    orientation.addSample(time, Cesium.Transforms.headingPitchRollQuaternion(p,
      new Cesium.HeadingPitchRoll(toRad(s[6] - 90), toRad(s[5]), toRad(s[4]))));
    pts.push(p);
  }
  position.setInterpolationOptions({ interpolationDegree: 1, interpolationAlgorithm: Cesium.LinearApproximation });

  // Uçuş izi (seyreltilmiş) ve irtifa perdesi
  const stepN = Math.max(1, Math.ceil(S.length / 4000));
  const pathPts = pts.filter((_, i) => i % stepN === 0);
  viewer.entities.add({ polyline: { positions: pathPts, width: 2.5, material: Cesium.Color.fromCssColorString('#ffcc33') } });
  viewer.entities.add({
    wall: { positions: pathPts, material: Cesium.Color.fromCssColorString('#3aa0ff').withAlpha(0.07), outline: false },
  });
  // Kalkış (ev) noktası
  viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(S[0][2], S[0][1], 0.5),
    point: { pixelSize: 10, color: Cesium.Color.LIME, outlineColor: Cesium.Color.BLACK, outlineWidth: 2 },
    label: { text: 'Kalkış', font: '13px sans-serif', pixelOffset: new Cesium.Cartesian2(0, -18), fillColor: Cesium.Color.WHITE,
      outlineColor: Cesium.Color.BLACK, outlineWidth: 3, style: Cesium.LabelStyle.FILL_AND_OUTLINE },
  });
  const track = viewer.entities.values[0];
  const plane = viewer.entities.add({
    viewFrom: new Cesium.Cartesian3(-60, -60, 70),   // takip kamerası: uçağın arkasından ve yukarıdan
    availability: new Cesium.TimeIntervalCollection([new Cesium.TimeInterval({ start: at(0), stop: at(duration) })]),
    position, orientation,
    model: { uri: '/static/models/caymaz.gltf', minimumPixelSize: 72, maximumScale: 400, scale: 1.8 },
    path: { leadTime: 0, trailTime: 90, width: 4, material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.25, color: Cesium.Color.ORANGE }) },
  });

  const clockModel = viewer.clock;
  clockModel.startTime = at(0);
  clockModel.stopTime = at(duration);
  const firstFlight = flying.length ? flying[0][0] : 0;
  clockModel.currentTime = at(Math.max(0, firstFlight - 5));
  clockModel.clockRange = Cesium.ClockRange.CLAMPED;
  clockModel.multiplier = 1;
  viewer.timeline.zoomTo(at(0), at(duration));

  // Anlık değerler (HUD)
  const find = t => {   // t'ye en yakın önceki örnek (ikili arama)
    let lo = 0, hi = S.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (S[mid][0] <= t) lo = mid; else hi = mid - 1; }
    return S[lo];
  };
  const modeAt = t => { let m = null; for (const x of modes) { if (x.t <= t) m = x.name; else break; } return m; };
  const row = (k, v) => h('div', null, h('span', null, k), h('b', null, v));
  let last = -1;
  const drawHud = () => {
    if (destroyed) return;
    const t = Cesium.JulianDate.secondsDifference(clockModel.currentTime, start);
    if (Math.abs(t - last) < 0.1) return;
    last = t;
    const s = find(t);
    const air = flying.some(([x, y]) => t >= x && t <= y);
    clear(hud,
      h('div', { class: 'r3d-hud-head' }, h('b', null, clock(t)), h('span', { class: `badge ${air ? 'green' : 'gray'}` }, air ? 'Havada' : 'Yerde'),
        modeAt(t) ? h('span', { class: 'badge blue' }, modeAt(t)) : null),
      row('İrtifa (eve göre)', `${f1(s[3])} m`),
      row('Yer hızı', `${f1(s[7])} m/s`),
      row('Hava hızı', `${f1(s[8])} m/s`),
      row('Gaz', s[9] == null ? '—' : `%${Math.round(s[9])}`),
      row('Batarya', s[10] == null ? '—' : `${Number(s[10]).toFixed(2)} V`),
      row('Roll / Pitch', `${f1(s[4])}° / ${f1(s[5])}°`),
      row('Yön (yaw)', `${f1(s[6])}°`));
  };
  clockModel.onTick.addEventListener(drawHud);
  box.viewer = viewer;   // test ve hata ayıklama için
  drawHud();

  // Kamera ve oynatma düğmeleri
  const btn = (label, fn, cls = '') => h('button', { class: `btn sm ${cls}`, type: 'button', onclick: fn }, label);
  const follow = () => { viewer.trackedEntity = plane; };
  const whole = () => { viewer.trackedEntity = undefined; viewer.zoomTo(track); };
  const speeds = [1, 2, 5, 10, 30];
  const speedBtns = speeds.map(x => btn(`${x}×`, () => {
    clockModel.multiplier = x;
    speedBtns.forEach((b, i) => b.classList.toggle('primary', speeds[i] === x));
  }, x === 1 ? 'primary' : ''));
  const play = btn('▶ Oynat', () => {
    clockModel.shouldAnimate = !clockModel.shouldAnimate;
    play.textContent = clockModel.shouldAnimate ? '❚❚ Duraklat' : '▶ Oynat';
  }, 'primary');
  clear(tools, play, ...speedBtns,
    btn('Uçağı takip et', follow), btn('Tüm iz', whole),
    flying.length ? btn('Kalkışa git', () => { clockModel.currentTime = at(Math.max(0, flying[0][0] - 5)); follow(); }) : null);
  viewer.clock.onTick.addEventListener(() => {
    const running = clockModel.shouldAnimate;
    if ((play.textContent.startsWith('▶')) === running) play.textContent = running ? '❚❚ Duraklat' : '▶ Oynat';
  });
  try {
    await viewer.zoomTo(track);
    follow();
  } catch (err) {
    if (!destroyed) toastError(err);
  }
}
