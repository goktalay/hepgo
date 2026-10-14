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
  let Cesium, log, data, fuel;
  try {
    [Cesium, log, data, fuel] = await Promise.all([loadCesium(), api.get(`/api/flight-logs/${id}`), api.get(`/api/flight-logs/${id}/replay`), api.get(`/api/flight-logs/${id}/fuel`).catch(() => null)]);
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
  const find = t => {   // t'ye en yakın önceki örnek (ikili arama)
    let lo = 0, hi = S.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (S[mid][0] <= t) lo = mid; else hi = mid - 1; }
    return S[lo];
  };

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

  // Uçuş izi (seyreltilmiş): havadayken sarı, yerdeyken (kalkış öncesi bekleme, iniş sonrası, rampa/araç üstü) gri; irtifa perdesi yalnız havada
  const stepN = Math.max(1, Math.ceil(S.length / 4000));
  const inAir = t => flying.some(([x, y]) => t >= x && t <= y);
  const yellow = Cesium.Color.fromCssColorString('#ffcc33'), grey = Cesium.Color.fromCssColorString('#9aa3ad').withAlpha(0.85);
  const segs = [];   // { air, pts }
  for (let i = 0; i < S.length; i += stepN) {
    const air = inAir(S[i][0]);
    let seg = segs[segs.length - 1];
    if (!seg || seg.air !== air) { seg = { air, pts: seg ? [seg.pts[seg.pts.length - 1]] : [] }; segs.push(seg); }   // önceki uçla birleşsin
    seg.pts.push(pts[i]);
  }
  let track = null;
  for (const seg of segs) {
    if (seg.pts.length < 2) continue;
    const ent = viewer.entities.add({ polyline: { positions: seg.pts, width: seg.air ? 1.5 : 1.2, material: seg.air ? yellow : grey } });
    if (seg.air) {
      viewer.entities.add({ wall: { positions: seg.pts, material: Cesium.Color.fromCssColorString('#3aa0ff').withAlpha(0.07), outline: false } });
      if (!track) track = ent;
    }
  }
  track = track || viewer.entities.values[0];
  // Kalkış noktası (ilk havalanma; uçuş aralığı yoksa kayıt başı)
  const tk = flying.length ? find(flying[0][0]) : S[0];
  viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(tk[2], tk[1], 0.5),
    point: { pixelSize: 10, color: Cesium.Color.LIME, outlineColor: Cesium.Color.BLACK, outlineWidth: 2 },
    label: { text: 'Kalkış', font: '13px sans-serif', pixelOffset: new Cesium.Cartesian2(0, -18), fillColor: Cesium.Color.WHITE,
      outlineColor: Cesium.Color.BLACK, outlineWidth: 3, style: Cesium.LabelStyle.FILL_AND_OUTLINE },
  });
  const plane = viewer.entities.add({
    viewFrom: new Cesium.Cartesian3(-60, -60, 70),   // takip kamerası: uçağın arkasından ve yukarıdan
    availability: new Cesium.TimeIntervalCollection([new Cesium.TimeInterval({ start: at(0), stop: at(duration) })]),
    position, orientation,
    model: { uri: '/static/models/caymaz.gltf', minimumPixelSize: 72, maximumScale: 400, scale: 1.8 },
    path: { leadTime: 0, trailTime: 90, width: 2, material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.25, color: Cesium.Color.ORANGE }) },
  });
  const planePosAt = t => position.getValue(t);
  // Burun ucu etiketi: yer hızı (km/sa) — uçağın burnunun 5 m önünde, yönelimle birlikte döner
  const noseOf = (p, yawDeg, out) => {
    const enu = Cesium.Transforms.eastNorthUpToFixedFrame(p);
    const r = Cesium.Math.toRadians(yawDeg || 0), d = 5;
    return Cesium.Matrix4.multiplyByPoint(enu, new Cesium.Cartesian3(Math.sin(r) * d, Math.cos(r) * d, 0.6), out);
  };
  viewer.entities.add({
    position: new Cesium.CallbackProperty(t => { const p = planePosAt(t); if (!p) return undefined; const s = find(Cesium.JulianDate.secondsDifference(t, start)); return noseOf(p, s[6], new Cesium.Cartesian3()); }, false),
    label: {
      text: new Cesium.CallbackProperty(t => { const s = find(Cesium.JulianDate.secondsDifference(t, start)); return `${Math.round((s[7] || 0) * 3.6)} km/sa`; }, false),
      font: 'bold 12px sans-serif', fillColor: Cesium.Color.fromCssColorString('#ffe08a'), outlineColor: Cesium.Color.BLACK, outlineWidth: 3, style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      pixelOffset: new Cesium.Cartesian2(0, -10), showBackground: true, backgroundColor: Cesium.Color.fromCssColorString('#0f172a').withAlpha(0.55), backgroundPadding: new Cesium.Cartesian2(5, 3),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });
  // İrtifa çizgisi: uçaktan yere (0 m) dikey çizgi, tam ortasında anlık irtifa etiketi — uçakla birlikte gezer
  const carto = new Cesium.Cartographic();
  const groundOf = (p, out) => { Cesium.Cartographic.fromCartesian(p, Cesium.Ellipsoid.WGS84, carto); return Cesium.Cartesian3.fromRadians(carto.longitude, carto.latitude, 0, Cesium.Ellipsoid.WGS84, out); };
  viewer.entities.add({
    polyline: {
      positions: new Cesium.CallbackProperty(t => { const p = planePosAt(t); return p ? [p, groundOf(p, new Cesium.Cartesian3())] : []; }, false),
      width: 1.2, material: Cesium.Color.fromCssColorString('#ffffff').withAlpha(0.7),
    },
  });
  viewer.entities.add({
    position: new Cesium.CallbackProperty(t => { const p = planePosAt(t); if (!p) return undefined; const g = groundOf(p, new Cesium.Cartesian3()); return Cesium.Cartesian3.midpoint(p, g, new Cesium.Cartesian3()); }, false),
    label: {
      text: new Cesium.CallbackProperty(t => { const sec = Cesium.JulianDate.secondsDifference(t, start); const s = find(sec); return `${Math.max(0, s[3]).toFixed(1)} m`; }, false),
      font: '12px sans-serif', fillColor: Cesium.Color.WHITE, outlineColor: Cesium.Color.BLACK, outlineWidth: 3, style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      showBackground: true, backgroundColor: Cesium.Color.fromCssColorString('#0f172a').withAlpha(0.55), backgroundPadding: new Cesium.Cartesian2(5, 3),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
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
  const modeAt = t => { let m = null; for (const x of modes) { if (x.t <= t) m = x.name; else break; } return m; };
  // Yakıt serisi (Yakıt Hesapla sonrası): [t, L/sa, yakılan L, itki kg, gaz %] — zamana göre ikili arama
  const FS = fuel && fuel.samples && fuel.samples.length ? fuel.samples : null;
  const fuelAt = FS ? (t => { let lo = 0, hi = FS.length - 1; while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (FS[mid][0] <= t) lo = mid; else hi = mid - 1; } return FS[lo]; }) : null;
  const row = (k, v) => h('div', null, h('span', null, k), h('b', null, v));
  let last = -1;
  const drawHud = () => {
    if (destroyed) return;
    const t = Cesium.JulianDate.secondsDifference(clockModel.currentTime, start);
    if (Math.abs(t - last) < 0.1) return;
    last = t;
    const s = find(t);
    const air = inAir(t);
    clear(hud,
      h('div', { class: 'r3d-hud-head' }, h('b', null, clock(t)), h('span', { class: `badge ${air ? 'green' : 'gray'}` }, air ? 'Havada' : 'Yerde'),
        modeAt(t) ? h('span', { class: 'badge blue' }, modeAt(t)) : null),
      row('İrtifa (eve göre)', `${f1(s[3])} m`),
      row('Yer hızı', `${f1(s[7])} m/s`),
      row('Hava hızı', `${f1(s[8])} m/s`),
      row('Gaz', s[9] == null ? '—' : `%${Math.round(s[9])}`),
      row('Batarya', s[10] == null ? '—' : `${Number(s[10]).toFixed(2)} V`),
      row('Roll / Pitch', `${f1(s[4])}° / ${f1(s[5])}°`),
      row('Yön (yaw)', `${f1(s[6])}°`),
      ...(fuelAt ? (() => { const fr = fuelAt(t); return [
        row('Anlık tüketim', `${f1(fr[1])} L/sa`),
        row('Yakılan yakıt', `${Number(fr[2]).toFixed(2)} / ${fuel.summary.total_l} L`),
        row('İtki', `${f1(fr[3])} kg (%${fr[4]})`)]; })() : []));
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
