// Program Ayarları (yalnızca Sistem Yöneticisi / MASTER): sistem geneli ayarlar. Kişisel Ayarlar tarzında iki panel.
// Bölümler: Sunucu Durumu (CPU/GPU/RAM/disk grafikleri + servisler ve yeniden başlat), Entegrasyonlar (API anahtarları…).
import { api } from '../api.js';
import { stockPicker } from '../stockpick.js';
import { segIconByKey } from '../segicons.js';
import { rolesBody } from './roles.js';
import { avatar, clear, confirmDialog, every, field, fmtDateTime, h, modal, pageHead, t, toast, toastError } from '../ui.js';

// Mobilde (≤800px) Program Ayarları iOS tarzı ana liste + alt-sayfa olur; görünüm genişliği değişince yeniden çizilir.
const SC_MQ = matchMedia('(max-width: 800px)');
let _scRedraw = null;
SC_MQ.addEventListener('change', () => { if (_scRedraw && location.hash.startsWith('#/sysconfig')) _scRedraw(); });

const pct = v => (v == null ? '—' : `%${Math.round(v)}`);
const gb = b => (b >= 1e12 ? `${(b / 1e12).toFixed(2)} TB` : `${Math.round(b / 1e9)} GB`);

function spark(values, color) {
  const w = 260, hh = 54, n = Math.max(values.length, 2);
  const pts = values.map((v, i) => `${(i / (n - 1)) * w},${hh - 1 - (Math.max(0, Math.min(100, v || 0)) / 100) * (hh - 2)}`).join(' ');
  const area = values.length ? `M0,${hh} L${pts.replaceAll(' ', ' L')} L${w},${hh}Z` : '';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${hh}`); svg.setAttribute('class', 'sc-spark'); svg.setAttribute('preserveAspectRatio', 'none');
  svg.innerHTML = `<path d="${area}" fill="${color}" opacity="0.14"/><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
  return svg;
}

function metricCard(label, color) {
  const val = h('b', { class: 'sc-metric-val' }, '—');
  const sub = h('small', { class: 'muted' }, '');
  const chart = h('div', { class: 'sc-chart' });
  const card = h('div', { class: 'card card-pad sc-metric' }, h('div', { class: 'sc-metric-top' }, h('span', { class: 'sc-metric-label' }, label), val), sub, chart);
  return { card, set(v, subText, series) { val.textContent = pct(v); sub.textContent = subText || ''; clear(chart, spark(series, color)); } };
}

// Entegrasyon sunucusu kartı: bir sunucuda çalışan entegrasyonun (Mikro ERP, PDKS) çalıştığı makinenin anlık
// kaynak grafiklerini (CPU/GPU/RAM/disk) ve fabrika ajanı bağlantı durumunu gösterir. Veri /api/system/status'tan gelir;
// uzak modda bu uçnokta merkez sunucuyu DEĞİL, fabrikadaki entegrasyon makinesini yansıtır (ajan sysstat). Yalnız sistem yöneticisi.
function integServerCard(view) {
  const cpu = metricCard('CPU', '#2563eb'), gpu = metricCard('GPU', '#16a34a'), ram = metricCard('RAM', '#7c3aed');
  const diskVal = h('b', { class: 'sc-metric-val' }, '—');
  const diskBar = h('div', { class: 'sc-disk-bar' }, h('i'));
  const diskSub = h('small', { class: 'muted' }, '');
  const diskCard = h('div', { class: 'card card-pad sc-metric' }, h('div', { class: 'sc-metric-top' }, h('span', { class: 'sc-metric-label' }, 'Disk'), diskVal), diskSub, diskBar);
  const hist = { cpu: [], gpu: [], ram: [] };
  let sinceT = 0;

  const loadStatus = async () => {
    try {
      const s = await api.get(`/api/system/status?since=${sinceT}`);
      (s.history || []).forEach(p => { hist.cpu.push(p.cpu); hist.gpu.push(p.gpu); hist.ram.push(p.ram); sinceT = p.t; });
      for (const k of ['cpu', 'gpu', 'ram']) hist[k] = hist[k].slice(-120);
      cpu.set(s.cpu, '', hist.cpu);
      gpu.set(s.gpu, s.gpu != null ? '' : 'yok', hist.gpu);
      ram.set(s.ram_total ? 100 * s.ram_used / s.ram_total : null, s.ram_total ? `${gb(s.ram_used)} / ${gb(s.ram_total)}` : '', hist.ram);
      if (s.disk_total) {
        const u = 100 * s.disk_used / s.disk_total;
        diskVal.textContent = pct(u);
        diskBar.querySelector('i').style.width = `${u.toFixed(1)}%`;
        diskBar.querySelector('i').className = u >= 92 ? 'bad' : u >= 80 ? 'warn' : '';
        diskSub.textContent = t('{used} dolu · {free} boş', { used: gb(s.disk_used), free: gb(s.disk_free) });
      }
    } catch { /* */ }
  };

  const agentBody = h('div');
  const loadAgent = async () => {
    try {
      const a = await api.get('/api/system/agent');
      if (a.mode !== 'remote') { clear(agentBody, h('div', { class: 'sc-svc' }, h('span', { class: 'sc-svc-dot on' }), h('div', { class: 'grow' }, h('b', null, 'Yerel sunucu'), h('small', { class: 'muted' }, 'Bu entegrasyon uygulamayla aynı makinede çalışıyor · ayrı ajan gerekmez')))); return; }
      const on = a.online;
      clear(agentBody, h('div', { class: 'sc-svc' },
        h('span', { class: `sc-svc-dot ${on ? 'on' : 'off'}` }),
        h('div', { class: 'grow' }, h('b', null, on ? 'Fabrika ajanı bağlı' : 'Fabrika ajanı ÇEVRİMDIŞI'),
          h('small', { class: 'muted' }, on
            ? `${a.info?.host || ''} · ${a.ping?.ok ? 'yanıt ' + a.ping.ms + ' ms' : 'ping yok'}`
            : 'Bu entegrasyon şu an erişilemez — fabrikadaki ajanı kontrol edin'))));
    } catch { /* */ }
  };

  loadStatus(); loadAgent();
  every(2000, loadStatus); every(10000, loadAgent);
  return h('section', { class: 'card card-pad sc-integ-server' },
    h('h3', { style: { marginTop: 0 } }, 'Çalıştığı sunucu'),
    h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Bu entegrasyonun çalıştığı makinenin anlık kaynak kullanımı. Merkez bulutta çalışıyorsa buradaki değerler fabrikadaki entegrasyon makinesine aittir.'),
    h('div', { class: 'sc-metrics' }, cpu.card, gpu.card, ram.card, diskCard),
    agentBody);
}

// Tek kamera canlı izleme (talep üzerine): fabrikadan anlık kareleri kısa aralıkla yenileyerek akıcı görüntü
function watchChannel(ch, name) {
  const img = h('img', { class: 'nvr-live-img', alt: name });
  const note = h('div', { class: 'nvr-live-note muted small' }, 'Bağlanıyor…');
  let stop = false, timer = null;
  const tick = () => {
    if (stop) return;
    const next = new Image();
    next.onload = () => { if (stop) return; img.src = next.src; note.textContent = name + ' · canlı'; timer = setTimeout(tick, 120); };
    next.onerror = () => { if (stop) return; note.textContent = 'Kare alınamadı — kanal yayında olmayabilir. Yeniden deneniyor…'; timer = setTimeout(tick, 1500); };
    next.src = `/api/system/nvr/snapshot/${ch}?sub=1&t=${Date.now()}`;
  };
  tick();
  modal({ title: `${name} (Kanal ${ch})`, wide: true,
    body: h('div', { class: 'nvr-live' }, img, note),
    actions: [{ label: 'Kapat' }],
    onClose: () => { stop = true; if (timer) clearTimeout(timer); } });
}

// NVR paneli: GPU kapasitesi (kaç kameraya yüz tanıma) + kanal listesi (her kanal: yüz tanıma aç/kapa + zamanlama)
const SCHED_LABEL = { all: 'Tüm gün', day: 'Sadece gündüz', night: 'Sadece akşam', custom: 'Özel saat' };
function nvrPanel() {
  const wrap = h('section', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Kanallar yükleniyor…'));
  let data = null;

  const gpuCard = () => {
    const g = data.gpu || {};
    const eff = g.effective_max || 0;
    const active = data.channels.filter(c => c._face).length;
    const over = active > eff && eff > 0;
    const manual = h('input', { class: 'input', type: 'number', min: '0', style: { maxWidth: '110px' },
      value: g.manual_max != null ? String(g.manual_max) : '', placeholder: 'Oto' });
    const saveCap = h('button', { class: 'btn sm', type: 'button' }, 'Uygula');
    saveCap.addEventListener('click', async () => {
      saveCap.disabled = true;
      try { const r = await api.put('/api/system/nvr/capacity', { manual_max: Number(manual.value) || null }); data.gpu = r.gpu; draw(); toast('Kapasite ayarı kaydedildi', 'success'); }
      catch (err) { toastError(err); } finally { saveCap.disabled = false; }
    });
    return h('section', { class: 'card card-pad' },
      h('h3', { style: { marginTop: 0 } }, 'Yüz Tanıma Kapasitesi'),
      h('p', { class: 'small muted', style: { marginTop: '-4px' } },
        g.gpu_name ? `GPU: ${g.gpu_name}${g.vram_mb ? ' · ' + Math.round(g.vram_mb / 1024) + ' GB' : ''}` : 'GPU bulunamadı — yüz tanıma için NVIDIA GPU gerekir.'),
      h('div', { class: 'nvr-cap' },
        h('div', { class: 'nvr-cap-box' }, h('span', { class: 'muted' }, 'Sistem desteği'), h('b', null, g.est_max ? `${g.est_max} kamera` : '—')),
        h('div', { class: 'nvr-cap-box' }, h('span', { class: 'muted' }, 'Etkin sınır'), h('b', null, eff ? `${eff} kamera` : '—')),
        h('div', { class: `nvr-cap-box ${over ? 'over' : ''}` }, h('span', { class: 'muted' }, 'Şu an açık'), h('b', null, `${active} kamera`))),
      h('p', { class: 'small muted' }, g.basis ? `Tahmin: ${g.basis}.` : '', ' Sınırı elle değiştirebilirsiniz; boş = otomatik.'),
      h('label', { class: 'sc-field', style: { maxWidth: '260px' } }, h('span', { class: 'sc-f-label' }, 'Elle max kamera'),
        h('div', { style: { display: 'flex', gap: '8px' } }, manual, saveCap)),
      over ? h('div', { class: 'sc-integ-msg err', style: { marginTop: '8px' } },
        `Açık kamera sayısı sistem sınırını (${eff}) aşıyor — performans düşebilir.`) : null);
  };

  const channelRow = c => {
    const face = h('input', { type: 'checkbox', class: 'nvr-switch' });
    face.checked = !!c._face;
    const sched = h('select', { class: 'input', style: { maxWidth: '160px' } },
      ...Object.entries(SCHED_LABEL).map(([v, l]) => h('option', { value: v, selected: c._sched === v }, l)));
    const c0 = h('input', { type: 'time', class: 'input', style: { maxWidth: '120px' }, value: (c._custom?.[0]?.[0]) || '' });
    const c1 = h('input', { type: 'time', class: 'input', style: { maxWidth: '120px' }, value: (c._custom?.[0]?.[1]) || '' });
    const customWrap = h('span', { class: 'nvr-custom', hidden: c._sched !== 'custom' }, c0, h('span', { class: 'muted' }, '–'), c1);
    const syncState = () => { c._face = face.checked; c._sched = sched.value; c._custom = [[c0.value, c1.value]]; customWrap.hidden = sched.value !== 'custom'; };
    face.addEventListener('change', () => { syncState(); draw(); });
    sched.addEventListener('change', () => { syncState(); customWrap.hidden = sched.value !== 'custom'; refreshCap(); });
    [c0, c1].forEach(x => x.addEventListener('change', syncState));
    const nameInp = h('input', { class: 'input nvr-name', value: c.name || '', placeholder: `Kanal ${c.ch}`, title: 'Kamera adı (düzenlenebilir)' });
    nameInp.addEventListener('input', () => { c.name = nameInp.value; });
    const watch = h('button', { class: 'btn sm nvr-watch', type: 'button', title: 'Canlı izle', onclick: () => watchChannel(c.ch, c.name || `Kanal ${c.ch}`) }, segIconByKey('eye'), 'İzle');
    return h('div', { class: `nvr-ch ${c._face ? 'on' : ''}` },
      h('label', { class: 'nvr-ch-sw' }, face, h('span', { class: 'nvr-slider' })),
      h('div', { class: 'grow' }, nameInp, h('small', { class: 'muted' }, `Kanal ${c.ch}`)),
      h('div', { class: 'nvr-ch-sched' }, c._face ? sched : h('span', { class: 'muted small' }, 'Kapalı'), c._face ? customWrap : null),
      watch);
  };

  const frCard = facerecCard();   // bir kez; her çizimde yeniden eklenir (durum korunur)
  let draw, refreshCap;
  draw = () => {
    const rows = data.channels.map(channelRow);
    clear(wrap,
      gpuCard(),
      frCard,
      h('section', { class: 'card card-pad' },
        h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px' } },
          h('h3', { style: { margin: 0, flex: 1 } }, `Kanallar (${data.channels.length})`),
          h('button', { class: 'btn sm', type: 'button', onclick: () => { data.channels.forEach(c => c._face = false); draw(); } }, 'Tümünü kapat')),
        data.error ? h('p', { class: 'sc-integ-msg err' }, `NVR'a ulaşılamadı: ${data.error}. Önce bağlantıyı kurun.`) : null,
        data.channels.length ? h('div', { class: 'nvr-chs' }, ...rows) : h('div', { class: 'muted', style: { padding: '8px 0' } }, 'Kanal bulunamadı.'),
        h('div', { class: 'sc-integ-foot', style: { marginTop: '10px' } }, h('span', { class: 'spacer' }),
          h('button', { class: 'btn primary', type: 'button', onclick: saveChannels }, 'Kanal ayarlarını kaydet'))));
  };
  refreshCap = () => draw();   // kapasite kutusunu (açık kamera sayısı) güncelle

  async function saveChannels() {
    const payload = data.channels.map(c => ({ ch: c.ch, name: c.name, face: !!c._face, schedule: c._sched,
      custom: c._sched === 'custom' ? c._custom : [] }));
    try {
      const r = await api.put('/api/system/nvr/channels', { channels: payload });
      data.gpu = r.gpu; draw();
      toast(t('{n} kanal açık olarak kaydedildi', { n: r.active }), 'success');
    } catch (err) { toastError(err); }
  }

  (async () => {
    try {
      const d = await api.get('/api/system/nvr/channels');
      d.channels.forEach(c => { c._face = !!c.face; c._sched = c.schedule || 'all'; c._custom = c.custom?.length ? c.custom : [['', '']]; });
      data = d; draw();
    } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); }
  })();
  return wrap;
}

// Yüz tanıma hassasiyeti (NVR eklenti ayarları): algılama eşiği + en küçük yüz. Fabrika servisine anında aktarılır.
function facerecCard() {
  const wrap = h('section', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  const draw = cfg => {
    const score = h('input', { type: 'range', min: '0.3', max: '0.95', step: '0.05', value: String(cfg.score), style: { flex: 1 } });
    const scoreVal = h('b', { style: { minWidth: '38px', textAlign: 'right' } }, String(cfg.score));
    score.addEventListener('input', () => { scoreVal.textContent = score.value; });
    const minFace = h('input', { type: 'number', class: 'input', min: '16', max: '240', value: String(cfg.min_face), style: { maxWidth: '100px' } });
    const save = async () => {
      try { const r = await api.put('/api/system/nvr/facerec', { score: Number(score.value), min_face: Number(minFace.value) }); draw(r); toast('Hassasiyet kaydedildi · anında geçerli', 'success'); }
      catch (err) { toastError(err); }
    };
    clear(wrap,
      h('h3', { style: { marginTop: 0 } }, 'Yüz Tanıma Hassasiyeti'),
      h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Eşik düşükse daha çok yüz yakalanır (uzak / açılı / hareketli), ama yanlış tespit artabilir. Varsayılan 0.60. Giriş kameralarında kişi görünmüyorsa eşiği düşürün.'),
      h('label', { class: 'sc-field' }, h('span', { class: 'sc-f-label' }, 'Algılama eşiği'),
        h('div', { style: { display: 'flex', gap: '10px', alignItems: 'center' } }, score, scoreVal)),
      h('label', { class: 'sc-field', style: { maxWidth: '280px' } }, h('span', { class: 'sc-f-label' }, 'En küçük yüz (piksel)'), minFace),
      h('div', { class: 'sc-integ-foot' }, h('span', { class: 'spacer' }), h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Kaydet')));
  };
  (async () => { try { draw(await api.get('/api/system/nvr/facerec')); } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); } })();
  return wrap;
}

// Yüz Tanıma CANLI TEST kartı: tarayıcı kamerasını açıp o ana kadar EĞİTİLMİŞ yüzlerle gerçek-zamanlı eşleştirme
// yapar (yüzen panel; yüz çerçevesi + bulunan kişinin adı). Panel kapatılınca kamera kapanır. Yalnız 'face' bağlıyken.
function faceLiveTestCard() {
  const btn = h('button', { class: 'btn primary', type: 'button' }, '📷 Canlı Test Başlat');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try { const m = await import('../livepanels.js'); await m.openFaceTest(); }
    catch (err) { toastError(err); }
    finally { btn.disabled = false; }
  });
  return h('section', { class: 'card card-pad' },
    h('h3', { style: { marginTop: 0 } }, 'Canlı Test'),
    h('p', { class: 'small muted', style: { marginTop: '-4px' } },
      'Bilgisayarınızın kamerasını açar; eğitilmiş yüzlerle gerçek-zamanlı eşleştirme yapıp yüzün etrafına çerçeve çizer ve bulunan kişinin adını yazar. Küçük yüzen panel — kapatınca kamera kapanır.'),
    h('div', { class: 'sc-integ-foot' }, h('span', { class: 'spacer' }), btn));
}

// Konuşma Tanıma CANLI TEST kartı: (69) sesten yazıya + (70) konuşmacı tanıma yüzen panelleri. Yalnız 'speech' bağlıyken.
function speechLiveTestCard() {
  const mk = (label, fn) => {
    const b = h('button', { class: 'btn primary', type: 'button', style: { marginRight: '8px' } }, label);
    b.addEventListener('click', async () => {
      b.disabled = true;
      try { const m = await import('../livepanels.js'); await m[fn](); }
      catch (err) { toastError(err); }
      finally { b.disabled = false; }
    });
    return b;
  };
  return h('section', { class: 'card card-pad' },
    h('h3', { style: { marginTop: 0 } }, 'Canlı Test'),
    h('p', { class: 'small muted', style: { marginTop: '-4px' } },
      'Mikrofonu açar — küçük yüzen panelde ses dalgasını gösterir. “Sesten Yazıya” konuştuklarınızı canlı metne çevirir; “Konuşmacı Tanıma” eğitilmiş seslerle eşleştirip kişinin adını/fotoğrafını getirir (tanıyamazsa “Tanımsız Kişi”). Panel kapatılınca mikrofon kapanır.'),
    h('div', { class: 'sc-integ-foot' }, h('span', { class: 'spacer' }),
      mk('🎙️ Sesten Yazıya', 'openSpeechToText'), mk('🗣️ Konuşmacı Tanıma', 'openSpeakerId')));
}

// Fabrika vardiya ayarı (Genel ayarlar içinde): gündüz/gece mesai saatleri (24s). NVR "sadece gündüz/akşam" bunu kullanır.
function shiftCard() {
  const wrap = h('section', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  const mk = () => ({ s: h('input', { type: 'time', class: 'input', style: { maxWidth: '130px' } }), e: h('input', { type: 'time', class: 'input', style: { maxWidth: '130px' } }) });
  const day = mk(), night = mk();
  const draw = s => {
    day.s.value = s.day[0]; day.e.value = s.day[1]; night.s.value = s.night[0]; night.e.value = s.night[1];
    clear(wrap,
      h('h3', { style: { marginTop: 0 } }, 'Fabrika Vardiyası'),
      h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Gündüz ve gece mesai saatleri (24 saat). Kameralarda “sadece gündüz / sadece akşam” yüz tanıma bu saatlere göre çalışır.'),
      h('label', { class: 'sc-field' }, h('span', { class: 'sc-f-label' }, 'Gündüz mesaisi'),
        h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } }, day.s, h('span', { class: 'muted' }, '–'), day.e)),
      h('label', { class: 'sc-field' }, h('span', { class: 'sc-f-label' }, 'Gece mesaisi'),
        h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } }, night.s, h('span', { class: 'muted' }, '–'), night.e)),
      h('div', { class: 'sc-integ-foot' }, h('span', { class: 'spacer' }),
        h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Vardiyayı kaydet')));
  };
  async function save() {
    try { const r = await api.put('/api/system/shift', { day: [day.s.value, day.e.value], night: [night.s.value, night.e.value] }); draw(r.shift); toast('Vardiya kaydedildi', 'success'); }
    catch (err) { toastError(err); }
  }
  (async () => { try { draw((await api.get('/api/system/shift')).shift); } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); } })();
  return wrap;
}

// Sayı kutusu: sabit genişlikte tek parça kontrol (− değer birim +); birim yazısının uzunluğu kutuyu kaydırmaz
function numBox(inp, suffix) {
  const step = Number(inp.step) || 1;
  const nudge = dir => {
    const min = inp.min !== '' ? Number(inp.min) : -Infinity, max = inp.max !== '' ? Number(inp.max) : Infinity;
    const v = Math.min(max, Math.max(min, (Number(inp.value) || 0) + dir * step));
    inp.value = String(v); inp.dispatchEvent(new Event('input', { bubbles: true })); inp.dispatchEvent(new Event('change', { bubbles: true }));
  };
  inp.classList.add('numbox-in');
  return h('span', { class: 'sc-num-wrap numbox' },
    h('button', { class: 'numbox-btn', type: 'button', tabindex: -1, 'aria-label': 'Azalt', onclick: () => nudge(-1) }, '−'),
    inp, suffix ? h('span', { class: 'numbox-unit' }, suffix) : null,
    h('button', { class: 'numbox-btn', type: 'button', tabindex: -1, 'aria-label': 'Artır', onclick: () => nudge(1) }, '+'));
}

// ---- Entegrasyonlar: API anahtarları ve bağlantı bilgileri (Claude, Mikro ERP, Google, genel) ----------
// Gizli alanların değeri sunucudan hiç gelmez; yalnızca "tanımlı" bilgisi ve kaynağı (panel / .env) gelir.
const INTEG_ICON = { ai: 'bolt', mikro: 'server', pdks: 'clock', nvr: 'lock', google: 'mailDot', microsoft: 'mailDot', meta: 'globe', x: 'globe', tiktok: 'globe', spotify: 'globe', speech: 'mic', maps: 'globe', general: 'gear' };
// Bir sunucuda çalışan (bu makinede ya da uzak modda fabrikadaki ajan makinesinde) entegrasyonlar: detayında o sunucunun kaynak grafikleri gösterilir.
const SERVER_INTEGRATIONS = ['mikro', 'pdks', 'nvr'];
// Ajan-ürünü logosu: mikro/pdks kendi logosu; camera NVR logosu; printer/face için simge.
const agentLogo = integ => (INTEG_LOGO[integ === 'camera' ? 'nvr' : integ]?.())
  || segIconByKey(integ === 'printer' ? 'server' : integ === 'face' ? 'lock' : 'grid');

// İndirilebilir (ajan-tabanlı) bir entegrasyonun detayındaki kurulum paneli: lisans + "API key üret" + indirme + nasıl-yapılır.
// Anahtar yalnız üretilince bir kez gösterilir. Yalnız MASTER'a açıktır; değilse kısa bilgi notu döner.
function downloadPanel(it, agentData, cat) {
  const prod = it.agent_integ;
  if (!cat.master) {
    return h('section', { class: 'card card-pad integ-dl' },
      h('h3', { style: { marginTop: 0 } }, 'Kurulum ve API anahtarı'),
      h('p', { class: 'small muted' }, 'Bu entegrasyonun anahtar üretimi ve kurulum dosyaları yalnızca sistem sahibine (MASTER) açıktır.'));
  }
  const akit = agentData?.items.find(x => x.integ === prod) || null;
  const central = cat.central_url;
  const dlLinks = () => h('div', { class: 'fab-dl' },
    [['windows', '⬇ Windows'], ['linux', '⬇ Linux']].map(([p, label]) =>
      h('a', { class: 'btn xs', href: akit ? akit.downloads[p] : '#', download: '',
        title: akit && akit.has_installer[p] ? 'Kurulum dosyasını indir' : 'Kurulum dosyası henüz hazır değil' },
        label, akit && akit.has_installer[p] ? null : h('small', { class: 'muted' }, ' · yakında'))));
  const keyBox = h('div', { class: 'fab-keybox' });
  if (akit?.key_set) clear(keyBox, h('div', { class: 'fab-key set' },
    h('span', { class: 'sc-f-ok' }, 'API anahtarı üretildi (gizli; yalnız üretilince bir kez gösterilir)')));
  const genBtn = h('button', { class: 'btn', type: 'button' }, akit?.key_set ? '🔑 API anahtarını yeniden üret' : '🔑 API key üret');
  genBtn.addEventListener('click', async () => {
    if (akit?.key_set && !await confirmDialog('Anahtarı yeniden üret',
      'Yeni anahtar üretilince eski anahtar geçersiz olur; kurulu ajanın yeni anahtarla yeniden yapılandırılması gerekir. Devam edilsin mi?',
      { okLabel: 'Yeniden üret', danger: true })) return;
    genBtn.disabled = true;
    try {
      const r = await api.post(`/api/system/integrations/agent/${prod}/genkey`, {});
      const code = h('code', { class: 'fab-key-val' }, r.key);
      clear(keyBox, h('div', { class: 'fab-key new' },
        h('b', null, 'API Anahtarı (yalnızca bir kez gösterilir):'),
        h('div', { class: 'fab-key-row' }, code,
          h('button', { class: 'btn xs', type: 'button', onclick: () => { navigator.clipboard?.writeText(r.key); toast('Anahtar kopyalandı'); } }, 'Kopyala')),
        h('p', { class: 'small warn-text' }, 'Bu anahtarı güvenli bir yere kaydedin; sayfadan ayrıldığınızda bir daha gösterilmez. Kurulan ajana domain ve bu anahtar girilir.')));
      genBtn.textContent = '🔑 API anahtarını yeniden üret';
    } catch (err) { toastError(err); } finally { genBtn.disabled = false; }
  });
  const lic = h('input', { type: 'checkbox', checked: !!akit?.licensed });
  lic.addEventListener('change', async () => {
    lic.disabled = true;
    try { await api.post(`/api/system/integrations/agent/${prod}/license`, { enabled: lic.checked }); toast(lic.checked ? 'Lisans açıldı' : 'Lisans kapatıldı'); lic.disabled = false; }
    catch (err) { toastError(err); lic.checked = !lic.checked; lic.disabled = false; }
  });
  const howto = h('ol', { class: 'integ-howto small' },
    ['Aşağıdan “API key üret”e basın; üretilen anahtarı kopyalayın.',
     'Kurulum dosyasını (Windows / Linux) fabrikadaki ilgili makineye indirip çalıştırın.',
     'Kurulan yazılıma bu API anahtarını girin.',
     'Bağlan deyin; ajan merkeze bağlanınca entegrasyon yeşile döner ve ayarlar görünür.'].map(s => h('li', null, s)));
  return h('section', { class: 'card card-pad integ-dl' },
    h('h3', { style: { marginTop: 0 } }, 'Kurulum ve API anahtarı'),
    h('p', { class: 'small muted' }, 'Bu entegrasyon fabrikaya kurulan bir ajanla çalışır. İndirin, kurun, üretilen API anahtarını ajana girin.'),
    akit?.min_req ? h('p', { class: 'small warn-text' }, akit.min_req) : null,
    central ? h('p', { class: 'small muted' }, t('Ajan bağlantı adresi: {u}', { u: central }))
      : h('p', { class: 'small warn-text' }, 'Önce Ayarlar’dan ortak domaini girin (ajan bu adrese bağlanır).'),
    h('label', { class: 'set-toggle' }, lic, h('span', null, h('b', null, 'Lisans (satışta / etkin)'),
      h('small', null, 'Açıkken bu ürün kullanıcılarca kullanılabilir'))),
    howto,
    h('div', { class: 'integ-dl-acts' }, genBtn, dlLinks()),
    keyBox);
}
// Entegrasyon durumu: ayarlı mı + (denetleniyorsa) son denemesi başarılı mı. "Bağlı" yalnız gerçekten ulaşılabiliyorsa.
const integState = g => !g.configured ? ['', 'Ayarlanmadı']
  : g.checked && !g.health ? ['wait', 'Denetleniyor…']
  : g.checked && !g.health.ok ? ['err', 'Çevrimdışı'] : ['ok', 'Bağlı'];
const integBadge = g => { const [cls, text] = integState(g); return h('span', { class: `sc-integ-status ${cls}`, title: g.health?.message || '' }, text); };
// Katalog kartı durumu (birleşik connected): gri = Bağlı değil, yeşil = Bağlı.
const catBadge = it => h('span', { class: `sc-integ-status ${it.connected ? 'ok' : ''}` }, it.connected ? 'Bağlı' : 'Bağlı değil');
const INTERVALS = [[30, '30 sn'], [60, '1 dk'], [120, '2 dk'], [300, '5 dk'], [600, '10 dk'], [900, '15 dk'], [1800, '30 dk'], [3600, '1 saat']];
function integHealthCard(grp, reload) {
  if (!grp.checked) return null;
  const sel = h('select', { class: 'input', style: { maxWidth: '140px' } },
    (INTERVALS.some(([v]) => v === grp.interval) ? INTERVALS : [...INTERVALS, [grp.interval, `${grp.interval} sn`]])
      .map(([v, l]) => h('option', { value: v, selected: v === grp.interval }, l)));
  sel.addEventListener('change', async () => {
    try { await api.put(`/api/system/integrations/${grp.key}/interval`, { seconds: Number(sel.value) }); toast('Kontrol sıklığı kaydedildi'); reload(grp.key); }
    catch (err) { toastError(err); }
  });
  const hl = grp.health;
  return h('section', { class: 'card card-pad integ-health' },
    h('h3', { style: { marginTop: 0 } }, 'Bağlantı durumu'),
    !grp.configured ? h('p', { class: 'small muted' }, 'Ayarlar girilince bağlantı düzenli olarak denetlenir.')
      : hl ? h('p', null, integBadge(grp), ' ', h('span', { class: 'small' }, hl.message),
        h('div', { class: 'small muted' }, t('Son kontrol: {a} · bu durumda: {b} tarihinden beri', { a: fmtDateTime(hl.checked_at), b: fmtDateTime(hl.since) })))
        : h('p', { class: 'small muted' }, 'Henüz denetlenmedi; ilk kontrol birkaç saniye içinde yapılır.'),
    h('label', { class: 'field', style: { maxWidth: '360px' } }, h('span', null, 'Kontrol sıklığı'), sel,
      h('small', { class: 'hint' }, 'Bağlantı bu aralıkla denenir; ulaşılamazsa “Çevrimdışı” görünür ve sistem yöneticisine bildirim düşer.')));
}

// Firma Kimliği (yalnızca MASTER): ünvan (kısa + resmî) ve logo. Ünvanlar Entegrasyonlar'ın 'general' grubunda
// saklanır (COMPANY_NAME / COMPANY_LEGAL_NAME); logo tenant'a özel UPLOAD_DIR'e yüklenir (/api/system/brand/logo).
function identityBody(view, ctx) {
  const wrap = h('div', { class: 'sc-identity' }, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));

  const draw = (shortV, legalV) => {
    const shortInp = h('input', { class: 'input', type: 'text', spellcheck: 'false', value: shortV || '', placeholder: 'ör. GÖKKUBBE Teknoloji' });
    const legalInp = h('input', { class: 'input', type: 'text', spellcheck: 'false', value: legalV || '', placeholder: 'ör. GÖKKUBBE TEKNOLOJİ ANONİM ŞİRKETİ' });
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
    saveBtn.addEventListener('click', async () => {
      saveBtn.disabled = true;
      try {
        await api.put('/api/system/integrations/general', { values: { COMPANY_NAME: shortInp.value.trim(), COMPANY_LEGAL_NAME: legalInp.value.trim() } });
        toast('Firma ünvanı kaydedildi · anında geçerli', 'success');
      } catch (err) { toastError(err); } finally { saveBtn.disabled = false; }
    });

    const preview = h('img', { class: 'sc-logo-preview', alt: 'Logo', src: ctx.meta?.logo_url || '/static/img/logo.png' });
    const fileInp = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/svg+xml,image/gif', hidden: true });
    fileInp.addEventListener('change', async () => {
      const file = fileInp.files?.[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      try {
        const r = await api.post('/api/system/brand/logo', fd);
        if (r?.logo_url && ctx.meta) ctx.meta.logo_url = r.logo_url;
        preview.src = r?.logo_url || preview.src;
        toast('Logo yüklendi · anında geçerli (yeniden giriş sonrası her yerde görünür)', 'success');
      } catch (err) { toastError(err); } finally { fileInp.value = ''; }
    });
    const upBtn = h('button', { class: 'btn', type: 'button', onclick: () => fileInp.click() }, 'Logo Yükle');
    const rmBtn = h('button', { class: 'btn', type: 'button', onclick: async () => {
      try { await api.del('/api/system/brand/logo'); if (ctx.meta) ctx.meta.logo_url = null; preview.src = '/static/img/logo.png'; toast('Logo kaldırıldı · varsayılana dönüldü'); }
      catch (err) { toastError(err); }
    } }, 'Varsayılana Döndür');

    clear(wrap,
      h('section', { class: 'card card-pad set-card' },
        h('h3', null, 'Firma Ünvanı'),
        h('p', { class: 'small muted' }, 'Kısa ad başlıklarda ve asistanda; resmî ünvan personel kimlik kartlarında kullanılır. Değişiklik anında geçerli olur.'),
        h('label', { class: 'sc-field' }, h('span', { class: 'sc-f-label' }, 'Ünvan (başlıklarda)'), shortInp),
        h('label', { class: 'sc-field' }, h('span', { class: 'sc-f-label' }, 'Resmî ünvan (kartlarda)'), legalInp),
        h('div', { class: 'sc-integ-foot' }, h('span', { class: 'spacer' }), saveBtn)),
      h('section', { class: 'card card-pad set-card' },
        h('h3', null, 'Logo'),
        h('p', { class: 'small muted' }, 'Başlık, giriş ekranı ve kimlik kartında görünür. PNG, JPG, WEBP, SVG veya GIF.'),
        h('div', { class: 'sc-logo-row' }, preview, fileInp, upBtn, rmBtn)));
  };

  (async () => {
    try {
      const d = await api.get('/api/system/integrations');
      const g = d.groups.find(x => x.key === 'general');
      const val = k => (g && g.fields.find(f => f.key === k)?.value) || '';
      draw(val('COMPANY_NAME'), val('COMPANY_LEGAL_NAME'));
    } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); }
  })();

  return wrap;
}

function integrationsBody(view, ctx) {
  const wrap = h('div', { class: 'sc-integ-list' }, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  const card = grp => {
    const ctl = {};
    const clear = new Set();
    const rows = grp.fields.map(f => {
      if (f.kind === 'bool') {   // aç / kapa
        const cb = h('input', { type: 'checkbox', checked: !!f.value });
        ctl[f.key] = { get value() { return cb.checked ? '1' : '0'; } };
        return h('label', { class: 'set-toggle' }, cb, h('span', null, h('b', null, f.label), h('small', null, f.hint)));
      }
      const secret = f.kind === 'secret';
      const inp = h('input', {
        class: 'input', type: secret ? 'password' : f.kind === 'int' ? 'number' : 'text', autocomplete: secret ? 'new-password' : 'off',
        spellcheck: 'false', value: secret ? '' : (f.value ?? ''),
        placeholder: secret ? (f.set ? '••••••••  (kayıtlı)' : f.hint) : f.hint,
      });
      ctl[f.key] = inp;
      // Kutunun altında tek sade satır: durum (gizli alanlarda kayıtlı mı) ve gerekiyorsa "Temizle"
      const state = secret ? (f.set ? h('span', { class: 'sc-f-ok' }, 'Kayıtlı') : h('span', { class: 'sc-f-empty' }, 'Girilmedi'))
        : h('span');   // ipucu zaten kutunun içinde (placeholder); tekrar yazılmaz
      let clr = null;
      if (f.source === 'panel') {
        clr = h('button', { class: 'sc-f-clear', type: 'button', title: 'Bu değeri sil' }, 'Temizle');
        clr.addEventListener('click', () => { clear.add(f.key); inp.value = ''; inp.placeholder = 'Kaydedince silinecek'; clr.remove(); });
      }
      return h('label', { class: 'sc-field' }, h('span', { class: 'sc-f-label' }, f.label), inp,
        h('span', { class: 'sc-f-meta' }, state, clr));
    });
    const status = integBadge(grp);
    const msg = h('div', { class: 'sc-integ-msg', hidden: true });
    const say = (ok, text) => { msg.hidden = false; msg.className = `sc-integ-msg ${ok ? 'ok' : 'err'}`; msg.textContent = text; };
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
    const testBtn = h('button', { class: 'btn', type: 'button' }, grp.key === 'general' ? null : 'Bağlantıyı Test Et');
    saveBtn.addEventListener('click', async () => {
      const values = {};
      for (const f of grp.fields) values[f.key] = ctl[f.key].value;
      saveBtn.disabled = true;
      try {
        await api.put(`/api/system/integrations/${grp.key}`, { values, clear: [...clear] });
        toast(t('{title} kaydedildi', { title: grp.title }), 'success');
        if (grp.key !== 'general') { const r = await api.post(`/api/system/integrations/${grp.key}/test`, {}); say(r.ok, r.message); }
        await reload(grp.key);
      } catch (err) { toastError(err); } finally { saveBtn.disabled = false; }
    });
    testBtn.addEventListener('click', async () => {
      testBtn.disabled = true; say(true, 'Deneniyor…');
      try { const r = await api.post(`/api/system/integrations/${grp.key}/test`, {}); say(r.ok, r.message); }
      catch (err) { say(false, err.message); } finally { testBtn.disabled = false; }
    });
    const extra = grp.key === 'mikro' && ctx.user.master && grp.configured
      ? h('button', { class: 'btn', type: 'button', onclick: () => { location.hash = '#/mikro'; } }, 'Mikro ERP’yi Aç') : null;
    return h('section', { class: 'card card-pad sc-integ', 'data-g': grp.key },
      h('div', { class: 'sc-integ-h' },
        h('span', { class: 'sc-integ-ico' }, segIconByKey(INTEG_ICON[grp.key] || 'grid')),
        h('div', { class: 'grow' }, h('b', null, grp.title), h('small', null, grp.desc)),
        status),
      h('div', { class: 'sc-fields' }, ...rows),
      h('div', { class: 'sc-integ-foot' }, msg, h('span', { class: 'spacer' }), extra, grp.key === 'general' ? null : testBtn, saveBtn));
  };
  const tileLogo = it => INTEG_LOGO[it.key]?.() || agentLogo(it.agent_integ || it.key);

  // "Entegrasyon Ekle": konu-bazlı katalog; henüz eklenmemiş entegrasyonlar gruplar halinde seçilir.
  const openAddModal = (cat, availItems) => {
    const byTopic = cat.topics.map(tp => [tp, availItems.filter(it => it.topic === tp.key)]).filter(([, l]) => l.length);
    const body = byTopic.length
      ? h('div', { class: 'integ-add' }, byTopic.map(([tp, list]) => h('div', { class: 'integ-add-sec' },
          h('h4', null, tp.label),
          h('div', { class: 'integ-add-grid' }, list.map(it => {
            const b = h('button', { class: 'integ-add-tile', type: 'button' },
              h('span', { class: 'integ-logo' }, tileLogo(it)),
              h('div', { class: 'grow' }, h('b', null, INTEG_INFO[it.key]?.short || it.title),
                h('small', null, it.downloadable ? 'Fabrika ajanı ile kurulur' : (INTEG_INFO[it.key]?.tag || ''))));
            b.addEventListener('click', async () => {
              b.disabled = true;
              try { await api.post('/api/system/integrations/add', { integ: it.key }); toast(t('{t} eklendi', { t: it.title })); m.close(); open = it.key; reload(); }
              catch (err) { toastError(err); b.disabled = false; }
            });
            return b;
          })))))
      : h('div', { class: 'card empty' }, 'Eklenebilecek başka entegrasyon yok; hepsi zaten listenizde.');
    const m = modal({ title: 'Entegrasyon Ekle', body, wide: true, actions: [{ label: 'Kapat' }] });
  };

  // Üstteki dişli: ortak domain (ajan-tabanlı ürünler bu adrese bağlanır) + firma geneli (ad / adresler).
  const openSettingsModal = (cat, d) => {
    const gen = d.groups.find(g => g.key === 'general');
    const body = h('div', null);
    if (cat.master) {
      const domInp = h('input', { class: 'input', type: 'text', spellcheck: 'false', value: cat.domain || '', placeholder: 'ör. caymaz.app' });
      const urlNote = h('small', { class: 'hint' }, cat.central_url ? t('Ajan bağlantı adresi: {u}', { u: cat.central_url }) : 'Domain girilince ajan adresi (wss://…/ws/agent) oluşur.');
      const domSave = h('button', { class: 'btn sm primary', type: 'button' }, 'Kaydet');
      domSave.addEventListener('click', async () => {
        domSave.disabled = true;
        try {
          const r = await api.put('/api/system/integrations/agent/domain', { domain: domInp.value.trim() });
          cat.domain = r.domain; cat.central_url = r.central_url;
          urlNote.textContent = r.central_url ? t('Ajan bağlantı adresi: {u}', { u: r.central_url }) : 'Domain girilince ajan adresi (wss://…/ws/agent) oluşur.';
          toast('Domain kaydedildi');
        } catch (err) { toastError(err); } finally { domSave.disabled = false; }
      });
      body.append(h('section', { class: 'card card-pad' },
        h('h3', { style: { marginTop: 0 } }, 'Fabrika ajanı domaini'),
        h('p', { class: 'small muted' }, 'İndirilebilir (ajan-tabanlı) entegrasyonların fabrikadaki kurulumu bu ortak adrese bağlanır.'),
        h('label', { class: 'sc-field', style: { maxWidth: '460px' } }, h('span', { class: 'sc-f-label' }, 'Ortak domain'),
          domInp, h('span', { class: 'sc-f-meta' }, urlNote, domSave))));
    }
    if (gen) body.append(h('section', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, gen.title), card(gen)));
    modal({ title: 'Entegrasyon Ayarları', body, wide: true, actions: [{ label: 'Kapat' }] });
  };

  // Eklenmiş entegrasyonların listesi (gri = bağlı değil, yeşil = Bağlı) + Ekle / Ayarlar.
  const renderList = (cat, d) => {
    const added = cat.items.filter(x => x.added);
    const avail = cat.items.filter(x => !x.added);
    clear(wrap,
      h('div', { class: 'integ-top' },
        h('p', { class: 'small muted grow' }, 'Firmanızın entegrasyonları. Yeni bir servis bağlamak için “Entegrasyon Ekle”ye dokunun; eklenen entegrasyon bağlanana kadar gri görünür. Ayarlara girmek için bir karta dokunun.'),
        h('button', { class: 'btn', type: 'button', title: 'Entegrasyon ayarları', onclick: () => openSettingsModal(cat, d) }, segIconByKey('gear'), ' Ayarlar'),
        h('button', { class: 'btn primary', type: 'button', onclick: () => openAddModal(cat, avail) }, '＋ Entegrasyon Ekle')),
      added.length
        ? h('div', { class: 'integ-gallery' }, added.map(it => h('button', { class: `integ-tile ${it.connected ? 'on' : ''}`, type: 'button', 'data-g': it.key,
            onclick: () => { open = it.key; reload(); } },
            h('span', { class: 'integ-logo' }, tileLogo(it)),
            h('b', null, INTEG_INFO[it.key]?.short || it.title),
            h('small', null, INTEG_INFO[it.key]?.tag || (it.downloadable ? 'Fabrika ajanı ile' : '')),
            catBadge(it))))
        : h('div', { class: 'card empty' }, 'Henüz entegrasyon eklenmedi. “＋ Entegrasyon Ekle” ile bir servis bağlayın.'));
  };

  // Tek entegrasyonun detayı: durum + (indirilebilir) kurulum/anahtar/indirme + bağlıyken ayarlar; ya da kimlik/OAuth kodu girişi.
  const renderDetail = (cat, d, agentData) => {
    const it = cat.items.find(x => x.key === open);
    if (!it) { open = null; return renderList(cat, d); }
    const grp = d.groups.find(g => g.key === open) || null;   // kimlik/ayar alanları; printer/face için yok
    const info = INTEG_INFO[it.key] || {};
    const agentBased = it.downloadable && cat.mode === 'remote';   // yerel modda doğrudan bağlanır (ajan/indirme yok)
    const back = h('button', { class: 'btn sm integ-back', type: 'button', onclick: () => { open = null; reload(); } }, '← Tüm entegrasyonlar');
    const hero = h('section', { class: `card integ-hero ${it.connected ? 'on' : ''}`, 'data-g': it.key },
      h('span', { class: 'integ-logo lg' }, tileLogo(it)),
      h('div', { class: 'grow' }, h('h2', null, it.title), h('p', null, info.lead || it.desc), catBadge(it)));
    const infoSec = info.sections?.length ? h('section', { class: 'card card-pad integ-info' },
      info.sections.map(([ti, items]) => h('div', { class: 'integ-info-sec' }, h('h4', null, ti), h('ul', null, items.map(x => h('li', null, x)))))) : null;
    const removeBtn = h('button', { class: 'btn sm danger', type: 'button' }, 'Listeden kaldır');
    removeBtn.addEventListener('click', async () => {
      if (!await confirmDialog('Entegrasyonu kaldır',
        t('“{t}” firma listenizden kaldırılsın mı? Ayarlar ve anahtar silinmez; istediğinizde yeniden ekleyebilirsiniz.', { t: it.title }),
        { okLabel: 'Kaldır', danger: true })) return;
      try { await api.post('/api/system/integrations/remove', { integ: it.key }); toast(t('{t} kaldırıldı', { t: it.title })); open = null; reload(); }
      catch (err) { toastError(err); }
    });
    const removeSec = h('div', { class: 'integ-remove' }, removeBtn);

    if (agentBased) {
      const settings = it.connected
        ? (grp ? h('div', { class: 'integ-form' }, h('h3', null, 'Ayarlar'), card(grp),
            (['pdks', 'mikro'].includes(grp.key) ? syncBox(grp.key) : null),
            (grp.key === 'nvr' ? nvrPanel() : null),
            (grp.key === 'nvr' ? shiftCard() : null),
            (SERVER_INTEGRATIONS.includes(grp.key) ? integServerCard(view) : null))
          : h('section', { class: 'card card-pad' }, h('p', { class: 'small muted' }, 'Bu entegrasyon bağlı ve kullanıma hazır.')))
        : h('section', { class: 'card card-pad integ-gate' }, h('p', { class: 'small muted' }, 'Bağlanınca ayarlar burada görünecek.'));
      clear(wrap, back, hero, infoSec,
        downloadPanel(it, agentData, cat),
        it.connected && grp && grp.checked ? integHealthCard(grp, () => reload()) : null,
        settings,
        it.connected && it.key === 'face' ? faceLiveTestCard() : null,
        it.connected && it.key === 'speech' ? speechLiveTestCard() : null,
        removeSec);
      return;
    }
    // Kimlik / OAuth tabanlı (ya da yerel moddaki doğrudan ürün): "API kodu" doğrudan burada girilir.
    clear(wrap, back, hero, infoSec,
      grp && grp.checked ? integHealthCard(grp, () => reload()) : null,
      grp ? h('div', { class: 'integ-form' }, h('h3', null, 'API kodu / bağlantı bilgileri'), card(grp)) : null,
      grp && (['pdks', 'mikro'].includes(grp.key) ? syncBox(grp.key) : null),
      grp && grp.key === 'nvr' ? nvrPanel() : null,
      grp && grp.key === 'nvr' ? shiftCard() : null,
      grp && SERVER_INTEGRATIONS.includes(grp.key) ? integServerCard(view) : null,
      removeSec);
  };

  let open = null;
  const reload = async () => {
    let cat, d, agentData = null;
    try { cat = await api.get('/api/system/integrations/catalog'); } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); return; }
    try { d = await api.get('/api/system/integrations'); } catch { d = { groups: [] }; }
    if (cat.master) { try { agentData = await api.get('/api/system/integrations/agent'); } catch { agentData = null; } }
    if (open) renderDetail(cat, d, agentData); else renderList(cat, d);
  };
  reload();
  return wrap;
}

// Entegrasyon logoları (arayüzde tanıtım amaçlı; her biri kendi markasının uygulama ikonu)
const svgEl = markup => { const t = document.createElement('template'); t.innerHTML = markup.trim(); return t.content.firstElementChild; };
const INTEG_LOGO = {
  speech: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Konuşma Tanıma"><rect width="64" height="64" rx="16" fill="#76b900"/>
    <g fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"><rect x="25" y="13" width="14" height="25" rx="7" fill="#fff"/>
    <path d="M18 31a14 14 0 0 0 28 0M32 45v7M24 52h16"/></g></svg>`),
  x: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="X"><rect width="64" height="64" rx="16" fill="#000"/>
    <path transform="translate(14 14) scale(1.5)" fill="#fff" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>`),
  meta: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Meta"><rect width="64" height="64" rx="16" fill="#0866ff"/>
    <text x="32" y="44" text-anchor="middle" font-size="36" font-weight="700" fill="#fff" font-family="system-ui, sans-serif">∞</text></svg>`),
  tiktok: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="TikTok"><rect width="64" height="64" rx="16" fill="#010101"/>
    <text x="34" y="45" text-anchor="middle" font-size="34" fill="#25f4ee" font-family="system-ui, sans-serif">♪</text>
    <text x="31" y="43" text-anchor="middle" font-size="34" fill="#fe2c55" font-family="system-ui, sans-serif">♪</text>
    <text x="32.5" y="44" text-anchor="middle" font-size="34" fill="#fff" font-family="system-ui, sans-serif">♪</text></svg>`),
  spotify: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Spotify"><rect width="64" height="64" rx="16" fill="#1DB954"/>
    <g fill="none" stroke="#000" stroke-width="4" stroke-linecap="round"><path d="M18 26c10-3 21-1.5 29 3"/><path d="M20 35c8-2.3 17-1 23 2.8"/><path d="M22 43c6-1.6 12.5-.7 17.5 2.2"/></g></svg>`),
  ai: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Claude"><rect width="64" height="64" rx="16" fill="#D97757"/>
    <g fill="#fff" transform="translate(32 32)">${[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map((a, i) =>
      `<rect x="-2.6" y="-21" width="5.2" height="${i % 2 ? 15 : 19}" rx="2.6" transform="rotate(${a})"/>`).join('')}<circle r="4.2"/></g></svg>`),
  google: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Google"><rect width="64" height="64" rx="16" fill="#fff"/>
    <g transform="translate(12 12) scale(0.833)"><path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h12.4c-.5 2.9-2.2 5.3-4.6 6.9v5.7h7.4c4.4-4 6.9-9.9 6.9-16.6z"/>
    <path fill="#34A853" d="M24 47c6.2 0 11.4-2 15.2-5.5l-7.4-5.7c-2.1 1.4-4.7 2.2-7.8 2.2-6 0-11.1-4-12.9-9.5H3.4v5.9C7.2 42 15 47 24 47z"/>
    <path fill="#FBBC05" d="M11.1 28.5c-.5-1.4-.7-2.9-.7-4.5s.3-3.1.7-4.5v-5.9H3.4C1.9 16.6 1 20.2 1 24s.9 7.4 2.4 10.4l7.7-5.9z"/>
    <path fill="#EA4335" d="M24 10c3.4 0 6.4 1.2 8.8 3.4l6.6-6.6C35.4 3 30.2 1 24 1 15 1 7.2 6 3.4 13.6l7.7 5.9C12.9 14 18 10 24 10z"/></g></svg>`),
  mikro: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Mikro"><defs><linearGradient id="mk" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e30613"/><stop offset="1" stop-color="#a1000b"/></linearGradient></defs>
    <rect width="64" height="64" rx="16" fill="url(#mk)"/><text x="32" y="40" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="19" font-weight="800" fill="#fff" letter-spacing="-.5">mikro</text></svg>`),
  pdks: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="PDKS"><rect width="64" height="64" rx="16" fill="#0e7490"/>
    <circle cx="32" cy="32" r="16" fill="none" stroke="#fff" stroke-width="3.2"/><path d="M32 23v10l7 4" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`),
  nvr: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="NVR"><rect width="64" height="64" rx="16" fill="#1f2937"/>
    <rect x="14" y="20" width="36" height="24" rx="3" fill="none" stroke="#fff" stroke-width="3"/>
    <circle cx="32" cy="32" r="6.5" fill="none" stroke="#fff" stroke-width="3"/><circle cx="32" cy="32" r="1.8" fill="#fff"/>
    <circle cx="43" cy="25" r="1.6" fill="#22c55e"/></svg>`),
  maps: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Google Haritalar"><rect width="64" height="64" rx="16" fill="#fff"/>
    <path d="M32 14c-7 0-12 5.4-12 12 0 8.4 12 22 12 22s12-13.6 12-22c0-6.6-5-12-12-12z" fill="#34A853"/>
    <circle cx="32" cy="26" r="5" fill="#fff"/><path d="M20 26c0-6.6 5-12 12-12 3.4 0 6.4 1.3 8.6 3.6L24 34c-2.5-2.2-4-5-4-8z" fill="#4285F4"/></svg>`),
  microsoft: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Microsoft"><rect width="64" height="64" rx="16" fill="#fff"/>
    <rect x="15" y="15" width="15" height="15" fill="#F25022"/><rect x="34" y="15" width="15" height="15" fill="#7FBA00"/>
    <rect x="15" y="34" width="15" height="15" fill="#00A4EF"/><rect x="34" y="34" width="15" height="15" fill="#FFB900"/></svg>`),
  printer: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Yazıcılar"><rect width="64" height="64" rx="16" fill="#334155"/>
    <g fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
    <path d="M21 25V15h22v10"/><rect x="14" y="25" width="36" height="17" rx="2.5"/><path d="M21 42v7h22v-7"/><path d="M24 36h16"/></g>
    <circle cx="43" cy="30.5" r="2" fill="#22c55e"/></svg>`),
  face: () => svgEl(`<svg viewBox="0 0 64 64" aria-label="Görüntü İşleme"><rect width="64" height="64" rx="16" fill="#6d28d9"/>
    <g fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
    <path d="M18 25v-4a3 3 0 0 1 3-3h4M46 25v-4a3 3 0 0 0-3-3h-4M18 39v4a3 3 0 0 0 3 3h4M46 39v4a3 3 0 0 0-3 3h-4"/>
    <path d="M28 40c2.4 1.6 5.6 1.6 8 0M32 29v5"/></g>
    <circle cx="27" cy="30" r="1.8" fill="#fff"/><circle cx="37" cy="30" r="1.8" fill="#fff"/></svg>`),
  general: () => { const i = document.createElement('img'); i.src = '/static/img/logo-mark.png?v=3'; i.alt = 'Gökkubbe'; return i; },
};
const INTEG_INFO = {
  face: { short: 'Görüntü İşleme', tag: 'Yüz Tanıma + İSG/KKD',
    lead: 'Fabrika kamerası görüntülerine çoklu görüntü-işleme uygular. Şu an iki özellik: (1) Yüz Tanıma — kişileri tanıyıp görülme/hareket üretir; (2) İSG/KKD — kask, eldiven gibi zorunlu koruyucuları gerçekten takıyor mu denetler, eksikse alarm üretir. Fabrikadaki ekran kartıyla (GPU) çalışır.',
    sections: [
      ['Ne işe yarar?', ['Yüz Tanıma: kameradaki kişileri eğitilmiş yüzlerle eşleştirir (personel/kişi/aile/ziyaretçi).',
        'İSG/KKD: her personel için belirlenen zorunlu koruyucu donanımı (kask/eldiven…) kamera üzerinden denetler.',
        'Zorunlu KKD eksikse ilgili kişiye bağlı İSG alarmı üretilir ve yetkililere bildirilir.']],
      ['Kurulum', ['İndirip fabrika makinesine kurun; üretilen API anahtarıyla merkeze bağlanır.',
        'Yüz tanıma GPU ile çok daha hızlıdır (NVIDIA önerilir).',
        'İSG/KKD denetimi için fabrika makinesine KKD tespit modeli (ONNX) yüklenir; model yoksa yalnız Yüz Tanıma çalışır.']],
      ['Bilinmesi gerekenler', ['Kamera/NVR entegrasyonu ile birlikte kullanılır.', 'Kişi başına zorunlu KKD ayarı İnsan Kaynakları › personel detayı › İSG sekmesindedir.',
        'Biyometrik veri ve video fabrikada yerelde kalır (KVKK).']],
    ] },
  ai: { short: 'Claude', tag: 'Yapay zeka asistanı',
    lead: 'Anthropic’in Claude modeli, sistemdeki maskot asistan “Kubbe”yi çalıştırır: kullanıcıların sorularını yetkileri dahilindeki verilerle yanıtlar, kayıt değişikliklerini yönetici onayına gönderir.',
    sections: [
      ['Ne işe yarar?', ['Kullanıcı sistemle ilgili soruları asistana sorar; asistan yalnızca kullanıcının yetkili olduğu verileri okur.',
        'Kayıt değiştirme istekleri doğrudan uygulanmaz; Program Ayarları › YZ Onayları’na düşer.',
        'Kullanıcı başına aylık token kotası Program Ayarları › Yapay Zeka’dan yönetilir.']],
      ['Anahtar nasıl alınır?', ['console.anthropic.com adresinde oturum açın › API Keys › Create Key.',
        'Anahtar bir çalışma alanına (workspace) bağlıysa Workspace ID’yi de girin (wrkspc_ ile başlar).',
        'Model alanı boş bırakılırsa claude-haiku-4-5 kullanılır (hızlı ve ekonomik).']],
      ['Bilinmesi gerekenler', ['Anahtar şifreli saklanır ve bir daha gösterilmez.', 'Anahtar tanımlı değilse maskot ve yapay zeka bölümleri kimseye görünmez.',
        'Kullanım Anthropic hesabınızdan ücretlendirilir.']],
    ] },
  mikro: { short: 'Mikro ERP', tag: 'Muhasebe / ERP aktarımı',
    lead: 'Mikro ERP’nin SQL Server veritabanından cari, stok ve alış / satış faturaları tek yönlü olarak sisteme aktarılır.',
    sections: [
      ['Ne işe yarar?', ['Cari kartlar Firma Yönetimi’ne, stok kartları ürün / malzeme listelerine, faturalar Satış ve Satın Alma’ya aktarılır.',
        'Aktarım tek yönlüdür: sistem Mikro’ya hiçbir şey yazmaz.', 'Daha önce aktarılan kayıtlar listede gizlenir; istenirse gösterilir.']],
      ['Bağlantı bilgileri', ['Sunucu: Mikro SQL Server’ın yerel ağdaki IP adresi ya da adı; port genellikle 1433.',
        'Veritabanı: firmanın Mikro veritabanı (ör. MikroDB_V16_FIRMA ya da MikroDesktop_001).',
        'Kullanıcı: yalnızca okuma yetkisi olan bir SQL / Windows kullanıcısı önerilir.']],
      ['Bilinmesi gerekenler', ['Bu sunucu Mikro sunucusuna yerel ağdan erişebilmelidir.', 'Bilgiler eksikse Mikro ERP modülü görünmez.',
        'Aktarım ekranı yalnızca sistem sahibine (MASTER) açıktır.']],
    ] },
  pdks: { short: 'PDKS', tag: 'Personel giriş-çıkış',
    lead: 'Personel devam kontrol cihazlarının (ör. Fixap) Firebird veritabanından giriş-çıkış hareketleri yalnızca okunur; cihaza ya da veritabanına hiçbir şey yazılmaz.',
    sections: [
      ['Ne işe yarar?', ['Kart / yüz okuyucuların giriş-çıkış kayıtları personelle eşleştirilir.',
        'İnsan Kaynakları’nda günlük giriş-çıkış, geç kalma ve devamsızlık izin / raporlarla birlikte görünür.',
        'Bağlantı tek yönlüdür: sistem PDKS’ye hiçbir şey yazmaz.']],
      ['Bağlantı bilgileri', ['Sunucu: PDKS Firebird sunucusunun IP’si (ör. 192.168.1.100); port genellikle 3050.',
        'Veritabanı yolu: sunucudaki .GDB / .FDB dosyası (ör. \\\\192.168.1.100\\MPremium\\PDKS.GDB).',
        'Kullanıcı: Firebird kullanıcısı (genelde SYSDBA); yalnızca okuma yetkisi yeterlidir.']],
      ['Bilinmesi gerekenler', ['Bu sunucu PDKS sunucusuna yerel ağdan erişebilmelidir (3050 portu).',
        'Şifre şifreli saklanır ve bir daha gösterilmez.', 'Firebird istemci kütüphanesi sistemle birlikte gelir; ayrıca kurulum gerekmez.']],
    ] },
  google: { short: 'Google', tag: 'Gmail, Takvim ve Kişiler bağlantısı',
    lead: 'Kullanıcıların Kişisel Ayarlar › Mail Hesaplarım’dan “Google ile bağlan” diyerek Gmail hesabını şifresiz eklemesini; Google Takvim ve Kişiler’in kişisel takvime ve rehbere gelmesini sağlar.',
    sections: [
      ['Ne işe yarar?', ['Her kullanıcı kendi Gmail hesabını bağlar; şifresi sisteme girilmez (Google OAuth).',
        'Google Takvim etkinlikleri Kişisel Takvim’e, Google Kişiler Rehber › Kişilerim’e gelir (yalnız sahibi görür).']],
      ['Nasıl ayarlanır?', ['Google Cloud Console › API’ler ve Hizmetler › Kütüphane: Gmail API, Google Calendar API ve People API’yi etkinleştirin.',
        'Kimlik Bilgileri › OAuth istemci kimliği oluşturun (Web uygulaması).',
        `“Yetkilendirilmiş yönlendirme URI’leri”ne şu adresi BİREBİR ekleyin: ${location.origin}/api/mail/oauth/google/callback`,
        'Sisteme başka bir adresten de giriliyorsa (ör. hem caymaz.app hem gokkubbe.hepgo.com) her biri için aynı yolu ayrı ayrı ekleyin: https://<adres>/api/mail/oauth/google/callback',
        'OAuth izin ekranı “Test” modundaysa bağlanacak Gmail adreslerini “Test kullanıcıları”na ekleyin. Oluşan Client ID ve Client Secret’ı buraya girin.']],
      ['Bilinmesi gerekenler', ['“redirect_uri_mismatch” hatası, yukarıdaki adresin Google’da birebir kayıtlı olmadığı anlamına gelir (https, alan adı ve yol dahil). Google’daki değişikliğin etkinleşmesi birkaç dakika sürebilir.',
        'Bilgiler eksikse kullanıcılar “Google ile bağlan”ı kullanamaz; uygulama şifresiyle Gmail eklemek yine mümkündür.', 'Client Secret şifreli saklanır.']],
    ] },
  x: { short: 'X (Twitter)', tag: 'Kişisel X hesabı bağlama',
    lead: 'Kullanıcılar Kişisel Ayarlar › Sosyal Medya’dan “X (Twitter) ile bağlan” diyerek kendi X hesaplarını bağlar; paylaşımları Şirketten Haberler akışında yalnızca kendilerine görünür.',
    sections: [
      ['Nasıl ayarlanır?', ['developer.x.com › Developer Portal’da bir Proje ve içinde bir Uygulama (App) oluşturun.',
        'Uygulama › “User authentication settings” › Set up: App permissions “Read”, Type of App “Web App, Automated App or Bot”.',
        `“Callback URI / Redirect URL” alanına şu adresi BİREBİR ekleyin: ${location.origin}/api/social/oauth/x/callback`,
        'Sisteme başka adreslerden de giriliyorsa (ör. caymaz.app ve gokkubbe.hepgo.com) her biri için aynı yolu ayrıca ekleyin.',
        '“Website URL” alanına şirket sitenizi yazıp kaydedin.',
        'Keys and tokens › “OAuth 2.0 Client ID and Client Secret” bölümündeki Client ID ve Client Secret’ı buraya girin.']],
      ['Bilinmesi gerekenler', ['“API Key / API Secret” (OAuth 1.0a) ile “OAuth 2.0 Client ID / Secret” farklıdır; burada OAuth 2.0 bilgileri kullanılır.',
        'X’in ücretsiz paketinde okuma kotası çok düşüktür; paylaşımların düzenli gelmesi için ücretli paket (Basic ve üstü) gerekebilir.',
        'Kotayı korumak için X hesapları 6 saatte bir yenilenir (CAYMAZ_X_POLL_HOURS); kullanıcı “⟳ Yenile” ile hemen çekebilir. Yalnızca yeni paylaşımlar istenir.',
        '“Kaydet ve dene” istemci bilgilerinin geçerli olup olmadığını kota harcamadan kontrol eder. Client Secret şifreli saklanır.']],
    ] },
  spotify: { short: 'Spotify', tag: 'Çalan parça + oynatma kontrolü',
    lead: 'Kullanıcılar Kişisel Ayarlar › Sosyal Medya’dan “Spotify ile bağlan” diyerek kendi Spotify hesaplarını bağlar; '
      + 'üst barda ve panodaki Spotify kutucuğunda şu an çalan parça görünür ve oynatma (oynat / duraklat / önceki / sonraki, '
      + 'çalma listesi, arama) buradan kontrol edilir.',
    sections: [
      ['Nasıl ayarlanır?', ['developer.spotify.com › Dashboard › “Create app” ile bir uygulama oluşturun.',
        `Uygulama ayarlarında “Redirect URI” alanına şu adresi BİREBİR ekleyin: ${location.origin}/api/spotify/oauth/callback`,
        'Sisteme başka adreslerden de giriliyorsa her biri için aynı yolu ayrıca ekleyin: https://<adres>/api/spotify/oauth/callback',
        'API olarak “Web API” (ve dilerseniz “Web Playback SDK”) seçin. Oluşan Client ID ve Client Secret’ı buraya girin.']],
      ['Bilinmesi gerekenler', ['Oynatma kontrolü (oynat/duraklat/geç) için kullanıcının Spotify Premium hesabı gerekir; çalan parçayı görmek ücretsiz hesapta da çalışır.',
        'Oynatma komutları, kullanıcının o an açık bir Spotify cihazına (telefon / bilgisayar / web oynatıcı) uygulanır; etkin cihaz yoksa anlaşılır bir uyarı gösterilir.',
        'Client Secret şifreli saklanır. Anahtar tanımlı değilse “Spotify ile bağlan” kullanıcılara görünmez.']],
    ] },
  speech: { short: 'Konuşma Tanıma', tag: 'Ses → metin, konuşmacı ayırma',
    lead: 'Toplantı, görüşme ve evrak seslerini metne çevirir, konuşanları ayırır ve tanır; metin kutularında “sesle yazdır” mikrofonunu açar. Kapalıyken sesler yalnızca kaydedilir.',
    sections: [
      ['Kapalıyken', ['Toplantı / görüşme / evrak sesleri kaydedilir ve dinlenebilir; metin, konuşmacı ve ses kimliği çıkarılmaz.',
        'Metin kutularındaki mikrofon (sesle yazdırma) görünmez.']],
      ['Çalışma yeri', ['“Fabrikadaki GX10’da işle” açıkken sesler fabrika ajanı üzerinden GX10’un ekran kartıyla (NVIDIA GB10) saniyeler içinde metne çevrilir. Ajan sesi kısa ömürlü bir bağlantıyla indirir; yalnızca metin geri gelir, ses fabrikada saklanmaz.',
        'Kapalıyken bu sunucuda işlenir: ekran kartı olmadığından ses, süresinin yaklaşık 2 katı sürede çevrilir (1 saatlik toplantı ≈ 2 saat).',
        'Ajan bağlı değilse ya da GX10’daki kod güncel değilse entegrasyon “Çevrimdışı” görünür ve nedeni yazılır.']],
      ['Bilinmesi gerekenler', [
        'Açılmadan önce kaydedilen sesler, toplantı ekranındaki “Yeniden işle” ile sonradan metne çevrilebilir.']],
    ] },
  meta: { short: 'Meta', tag: 'Instagram / Facebook',
    lead: 'Instagram ve Facebook hesaplarının bağlanması için Meta uygulama bilgileri. Bilgiler kaydedilebilir; bu platformlar için hesap bağlama akışı henüz hazır değildir.',
    sections: [['Durum', ['Instagram Graph API ve Facebook Login için Meta uygulama incelemesi (App Review) gerekir; akış hazırlandığında bu bilgiler kullanılacak.']]] },
  tiktok: { short: 'TikTok', tag: 'TikTok hesabı',
    lead: 'TikTok hesaplarının bağlanması için TikTok geliştirici uygulama bilgileri. Bilgiler kaydedilebilir; hesap bağlama akışı henüz hazır değildir.',
    sections: [['Durum', ['TikTok Login Kit ve Display API için uygulama incelemesi gerekir; akış hazırlandığında bu bilgiler kullanılacak.']]] },
  maps: { short: 'Google Haritalar', tag: 'Harita görünümleri',
    lead: 'Harita gösterilen ekranlar (ör. Güvenlik › Bina Kontrol) Google Haritalar kullanır; anahtar yoksa açık kaynak haritaya (OpenStreetMap) düşülür.',
    sections: [
      ['Anahtar nasıl alınır?', ['Google Cloud Console › API’ler ve Hizmetler › "Maps JavaScript API"yi etkinleştirin.',
        'Kimlik Bilgileri › API anahtarı oluşturun (AIza… ile başlar).',
        'Güvenlik için anahtara HTTP yönlendiren (web sitesi) kısıtı ekleyin: alan adınız (ör. caymaz.app).']],
      ['Bilinmesi gerekenler', ['Bu anahtar istemci tarafında (tarayıcıda) kullanılır; yönlendiren kısıtı ile korunur.',
        'Anahtar tanımlı değilse haritalar OpenStreetMap ile gösterilir.']],
    ] },
  general: { short: 'Genel', tag: 'Firma adı ve adresler',
    lead: 'Sistemin kimliği: başlıklarda ve yazdırılan belgelerde görünen firma adı, davet ve e-posta bağlantılarında kullanılan adresler.',
    sections: [
      ['Alanlar', ['Firma adı: başlıklarda, belgelerde ve asistanda kullanılır.',
        'İnternet adresi: dışarıdan erişim adresi (ör. https://caymaz.app); toplantı davetleri ve e-posta bağlantıları bununla oluşur.',
        'Yerel ağ adresi: şirket içinden doğrudan erişim (büyük dosya / video yüklemeleri bu adresten yapılır).']],
    ] },
};

// ---- Modül Ayarları: her modülün kendi ayarları (ilk: Saha Yönetimi) -------------
const MODULE_SETTINGS = [
  { key: 'field', title: 'Saha Yönetimi', desc: 'Standart saha ekipman listesi ve görev tanımları', icon: 'route3d', body: fieldSettingsBody },
  { key: 'hr', title: 'İnsan Kaynakları · İSG', desc: 'Görev tanımı belgelerinin genel hükümleri', icon: 'person', body: isgGeneralBody },
  { key: 'cleaning', title: 'Temizlik', desc: 'Günlük temizlik çeklisti maddeleri', icon: 'grid', body: cleaningSettingsBody },
  { key: 'building', title: 'Güvenlik · Bina Kontrol', desc: 'Günlük bina kontrol (tur) saatleri', icon: 'lock', body: buildingSettingsBody },
  // Konuşma tanımanın geçtiği modüller: her birinde aç / kapa (entegrasyon çalışmıyorsa açılamaz)
  { key: 'speech-meetings', title: 'Toplantılar', desc: 'Toplantı kaydını metne çevirme, konuşmacı tanıma', icon: 'grid', body: () => speechSettingsBody('meetings') },
  { key: 'speech-meet', title: 'Online Toplantı', desc: 'Online toplantı kaydını metne çevirme', icon: 'grid', body: () => speechSettingsBody('meet') },
  { key: 'speech-calls', title: 'Sesli Görüşmeler', desc: 'Görüşme kaydını metne çevirme', icon: 'grid', body: () => speechSettingsBody('calls') },
  { key: 'speech-documents', title: 'Evrak Yönetimi', desc: 'Ses / video evrakının konuşmasını metne çevirme', icon: 'grid', body: () => speechSettingsBody('documents') },
  { key: 'speech-dictation', title: 'Sesle Yazdırma', desc: 'Metin kutularında mikrofon', icon: 'grid', body: () => speechSettingsBody('dictation') },
];

// Konuşma tanıma (modül bazında): entegrasyon açık ve çalışıyorsa açılabilir; kapalıyken sesler yalnız kaydedilir
function speechSettingsBody(key) {
  const wrap = h('div', null, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  const draw = d => {
    const f = d.features.find(x => x.key === key);
    const cb = h('input', { type: 'checkbox', checked: f.on && d.integration, disabled: !d.integration });
    cb.addEventListener('change', async () => {
      cb.disabled = true;
      try { draw(await api.put(`/api/system/speech/${key}`, { on: cb.checked })); toast(cb.checked ? 'Konuşma tanıma açıldı' : 'Konuşma tanıma kapatıldı'); }
      catch (err) { toastError(err); cb.checked = !cb.checked; cb.disabled = false; }
    });
    clear(wrap, h('section', { class: 'card card-pad' },
      h('h3', { style: { marginTop: 0 } }, `Konuşma Tanıma · ${f.title}`),
      h('p', { class: 'small muted' }, f.desc),
      h('label', { class: 'set-toggle' }, cb, h('span', null, h('b', null, 'Bu modülde konuşma tanımayı kullan'),
        h('small', null, d.integration ? (f.active ? 'Açık: sesler metne çevriliyor.' : 'Kapalı: sesler yalnız kaydediliyor.')
          : 'Açılamaz: Konuşma Tanıma entegrasyonu kapalı ya da çalışmıyor. Kapalıyken sesler yalnız kaydedilir.'))),
      d.integration ? null : h('p', { class: 'small' }, h('a', { href: '#/sysconfig/integrations' }, 'Program Ayarları › Entegrasyonlar › Konuşma Tanıma →'))));
  };
  (async () => { try { draw(await api.get('/api/system/speech')); } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); } })();
  return wrap;
}

// Bina kontrol saatleri: her gün güvenlik personelinin bina turu atacağı saatler
function buildingSettingsBody() {
  const wrap = h('div', null, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let times = [];
  const save = async () => { try { times = (await api.put('/api/security/building/config', { times })).times; draw(); toast('Saatler kaydedildi'); } catch (err) { toastError(err); } };
  const draw = () => {
    const add = h('input', { type: 'time', class: 'input', style: { maxWidth: '150px' } });
    clear(wrap, h('section', { class: 'card card-pad' },
      h('h3', { style: { marginTop: 0 } }, 'Günlük Bina Kontrol Saatleri'),
      h('p', { class: 'small muted' }, 'Güvenlik personelinin her gün bina turu atması gereken saatler. Her saat, o gün Güvenlik › Bina Kontrol ekranında bekleyen bir tur olarak görünür; saati gelince vurgulanır.'),
      times.length ? h('div', { class: 'bc-times' }, times.map(t => h('span', { class: 'bc-time-chip' }, t,
        h('button', { class: 'bc-time-x', type: 'button', title: 'Kaldır', onclick: () => { times = times.filter(x => x !== t); save(); } }, '×')))) : h('div', { class: 'muted', style: { margin: '8px 0' } }, 'Saat eklenmedi.'),
      h('div', { class: 'cl-set-add' }, add,
        h('button', { class: 'btn primary', type: 'button', onclick: () => { if (add.value && !times.includes(add.value)) { times = [...times, add.value].sort(); save(); } } }, 'Ekle'))));
  };
  (async () => { try { times = (await api.get('/api/security/building/config')).times || []; } catch { times = []; } draw(); })();
  return wrap;
}

// Temizlik çeklisti maddeleri: Sistem Yöneticisi günlük yapılacak işleri ekler / düzenler / sıralar
function cleaningSettingsBody() {
  const wrap = h('div', null, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  const load = async () => {
    let items;
    try { items = await api.get('/api/cleaning/items'); } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); return; }
    const active = items.filter(i => i.active);
    const add = h('input', { class: 'input', placeholder: 'Yeni iş (ör. Tuvaletlerin temizliği)' });
    const doAdd = async () => { const v = add.value.trim(); if (!v) return; try { await api.post('/api/cleaning/items', { label: v }); add.value = ''; load(); } catch (err) { toastError(err); } };
    add.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); doAdd(); } });
    const rowEl = (it, i) => {
      const label = h('input', { class: 'input', value: it.label });
      label.addEventListener('blur', async () => {
        const v = label.value.trim();
        if (v && v !== it.label) { try { await api.put(`/api/cleaning/items/${it.id}`, { label: v }); toast('Güncellendi'); } catch (err) { toastError(err); } }
      });
      const mv = async dir => { try { await api.post(`/api/cleaning/items/${it.id}/move?dir=${dir}`, {}); load(); } catch (err) { toastError(err); } };
      return h('div', { class: 'cl-set-row' }, label,
        h('button', { class: 'btn sm', type: 'button', title: 'Yukarı', disabled: i === 0, onclick: () => mv('up') }, '↑'),
        h('button', { class: 'btn sm', type: 'button', title: 'Aşağı', disabled: i === active.length - 1, onclick: () => mv('down') }, '↓'),
        h('button', { class: 'btn sm danger', type: 'button', title: 'Kaldır', onclick: async () => {
          if (await confirmDialog('İşi kaldır', t('“{label}” listeden kaldırılsın mı? (geçmiş kayıtlar korunur)', { label: it.label }), { okLabel: 'Kaldır', danger: true })) { try { await api.del(`/api/cleaning/items/${it.id}`); load(); } catch (err) { toastError(err); } }
        } }, '×'));
    };
    clear(wrap, h('section', { class: 'card card-pad' },
      h('h3', { style: { marginTop: 0 } }, 'Günlük Temizlik İşleri'),
      h('p', { class: 'small muted' }, 'Temizlik görevlisinin her gün yapması gereken işler. Buradaki sıra, Temizlik ekranında da aynıdır.'),
      active.length ? h('div', { class: 'cl-set-list' }, active.map(rowEl)) : h('div', { class: 'muted', style: { margin: '8px 0' } }, 'Henüz iş eklenmedi.'),
      h('div', { class: 'cl-set-add' }, add, h('button', { class: 'btn primary', type: 'button', onclick: doAdd }, 'Ekle'))));
  };
  load();
  return wrap;
}

// İSG genel hükümleri: görev tanımı belgelerinde ortak bölümler (her satır bir madde)
function isgGeneralBody() {
  const wrap = h('div', null, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  (async () => {
    let g;
    try { g = await api.get('/api/hr/isg-general'); } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); return; }
    const inp = (v, ph) => h('input', { class: 'input', value: v || '', placeholder: ph });
    const area = (v, rows = 4, ph = '') => h('textarea', { class: 'input', rows, placeholder: ph }, v || '');
    const f = {
      doc_no: inp(g.doc_no, 'ör. GKT-İSG-GT-CAYMAZ-01'), rev: inp(g.rev, 'ör. Rev. 00 — 01.10.2026'), place: inp(g.place, 'Faaliyet / çalışma yeri'),
      purpose: area(g.purpose, 4), scope: area(g.scope, 3),
      legal: area((g.legal || []).join('\n'), 6, 'Her satıra bir madde'),
      phases: area((g.phases || []).join('\n'), 6, 'Her satıra bir aşama (ör. Hazırlık (tesis): …)'),
      zones: area((g.zones || []).map(z => `${z.a} | ${z.b}`).join('\n'), 6, 'Bölge / komut | Kural'),
      common: area((g.common || []).join('\n'), 8, 'Tüm personelin İSG yükümlülükleri — her satıra bir madde'),
      emergency_note: area(g.emergency_note, 3),
    };
    const lines = el => el.value.split('\n').map(x => x.trim()).filter(Boolean);
    const fld = (label, el, hint) => h('label', { class: 'sc-field' }, h('span', { class: 'sc-f-label' }, label), el, hint ? h('span', { class: 'sc-f-meta' }, hint) : null);
    const save = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        await api.put('/api/hr/isg-general', { doc_no: f.doc_no.value, rev: f.rev.value, place: f.place.value, purpose: f.purpose.value, scope: f.scope.value,
          legal: lines(f.legal), phases: lines(f.phases), common: lines(f.common), emergency_note: f.emergency_note.value,
          zones: lines(f.zones).map(l => { const [a, ...b] = l.split('|'); return { a: a.trim(), b: b.join('|').trim() }; }) });
        toast('İSG genel hükümleri kaydedildi', 'success');
      } catch (err) { toastError(err); } finally { save.disabled = false; }
    });
    clear(wrap,
      h('section', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Belge Bilgileri'),
        h('div', { class: 'sc-fields' }, fld('Doküman no', f.doc_no), fld('Revizyon / tarih', f.rev), fld('Faaliyet / çalışma yeri', f.place))),
      h('section', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Genel Hükümler'),
        h('p', { class: 'small muted' }, 'Personel görev tanımı belgelerinde (İK › personel › Görev Tanımı › Yazdır) ortak bölümler buradan alınır. Liste alanlarında her satır bir maddedir.'),
        h('div', { class: 'sc-fields one' }, fld('Amaç', f.purpose), fld('Kapsam', f.scope), fld('Yasal dayanak', f.legal),
          fld('Faaliyet aşamaları', f.phases), fld('Saha emniyet bölgeleri ve komutlar', f.zones, 'Her satır: Bölge / Komut | Kural'),
          fld('İSG yükümlülükleri (tüm personel)', f.common, 'Görev tanımı belgesinin D bölümü'), fld('Acil durum notu', f.emergency_note))),
      h('div', { class: 'set-actions left' }, save));
  })();
  return wrap;
}
// Otomatik senkronizasyon kutusu (PDKS / Mikro): aç-kapa, aralık (dk), şimdi çalıştır, son durum
function syncBox(group) {
  const box = h('div', { class: 'card card-pad integ-sync' });
  const draw = async () => {
    let st;
    try { st = (await api.get('/api/system/sync')).sync[group]; } catch { clear(box, h('div', { class: 'small muted' }, 'Senkronizasyon durumu alınamadı')); return; }
    const toggle = h('input', { type: 'checkbox', checked: st.enabled });
    const interval = h('input', { class: 'input', type: 'number', min: '5', step: '5', value: st.interval, style: { width: '90px' } });
    const save = async () => {
      try { await api.put(`/api/system/sync/${group}`, { enabled: toggle.checked, interval: Number(interval.value) || 30 }); toast('Senkronizasyon ayarı kaydedildi'); draw(); }
      catch (err) { toastError(err); }
    };
    toggle.addEventListener('change', save);
    const runBtn = h('button', { class: 'btn sm', type: 'button' }, 'Şimdi senkronize et');
    runBtn.addEventListener('click', async () => {
      runBtn.disabled = true; runBtn.textContent = 'Çalışıyor…';
      try { const r = await api.post(`/api/system/sync/${group}/run`, {}); toast(r.ok ? ('Senkron tamam · ' + r.message) : ('Hata: ' + r.message), r.ok ? 'success' : 'err'); }
      catch (err) { toastError(err); } finally { runBtn.disabled = false; runBtn.textContent = 'Şimdi senkronize et'; draw(); }
    });
    const last = st.last_run ? `${fmtDateTime(st.last_run)} · ${st.last_ok ? '✓' : '✕'} ${st.last_msg || ''}` : 'Henüz çalışmadı';
    clear(box,
      h('h3', null, 'Otomatik senkronizasyon'),
      h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Açıkken bu entegrasyon belirtilen aralıkla kendiliğinden güncellenir (tek yönlü, yalnızca okuma). İstediğiniz an kapatabilirsiniz.'),
      h('label', { class: 'set-toggle' }, toggle, h('span', null, h('b', null, 'Otomatik senkronizasyon açık'))),
      h('div', { class: 'integ-sync-row' }, h('span', null, 'Her'), interval, h('span', null, 'dakikada bir'),
        h('button', { class: 'btn sm primary', type: 'button', onclick: save }, 'Kaydet'), runBtn),
      h('div', { class: `small ${st.last_ok === false ? 'warn-text' : 'muted'}` }, 'Son çalışma: ' + last));
  };
  draw();
  return box;
}

function modulesBody(view, ctx) {
  let cur = MODULE_SETTINGS[0].key;
  const pane = h('div');
  const tabs = h('div', { class: 'seg wrap ms-tabs' });
  const draw = () => {
    clear(tabs, MODULE_SETTINGS.map(m => h('button', { type: 'button', class: m.key === cur ? 'on' : '', onclick: () => { cur = m.key; draw(); } },
      segIconByKey(m.icon), m.title)));
    const m = MODULE_SETTINGS.find(x => x.key === cur);
    clear(pane, m.body(view, ctx));
  };
  draw();
  return h('div', null, h('p', { class: 'small muted' }, 'Modüllere özel ayarlar. Bir modül seçin.'), tabs, pane);
}

function fieldSettingsBody() {
  const wrap = h('div', null, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  (async () => {
    let d;
    try { d = await api.get('/api/field/settings'); } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); return; }
    let items = d.equipment.map(e => ({ ...e }));
    const tbody = h('tbody');
    const drawRows = () => clear(tbody, items.length ? items.map((e, i) => {
      // Ekipman: stoktaki ürünlerden aranarak seçilir (3 karakterden sonra liste)
      const pick = stockPicker({ value: e.name, linked: !!e.product_id, onPick: p => {
        if (p) { e.product_id = p.id; e.name = p.name; e.product_code = p.code; if (!e.unit || e.unit === 'adet') e.unit = p.unit || e.unit; unit.value = e.unit || ''; }
        else { e.product_id = null; }
      } });
      e._pick = pick;
      const name = h('div', null, pick.el, e.product_id ? h('div', { class: 'eq-code' }, e.product_code || '')
        : e.id ? h('div', { class: 'eq-code warn-text' }, 'Stokla eşleşmedi — listeden seçin') : null);
      const qty = h('input', { class: 'input eq-qty', type: 'number', min: '0', step: 'any', value: e.qty, oninput: ev => { e.qty = Number(ev.target.value) || 0; } });
      const unit = h('input', { class: 'input eq-unit', value: e.unit || '', placeholder: 'birim', oninput: ev => { e.unit = ev.target.value; } });
      const note = h('input', { class: 'input', value: e.note || '', placeholder: 'Not (ops.)', oninput: ev => { e.note = ev.target.value; } });
      const mv = (dir) => { const j = i + dir; if (j < 0 || j >= items.length) return; [items[i], items[j]] = [items[j], items[i]]; drawRows(); };
      return h('tr', null, h('td', { class: 'num muted' }, i + 1), h('td', null, name), h('td', null, qty), h('td', null, unit), h('td', null, note),
        h('td', { class: 'nowrap' },
          h('button', { class: 'btn xs', type: 'button', title: 'Yukarı', onclick: () => mv(-1), disabled: i === 0 }, '↑'),
          h('button', { class: 'btn xs', type: 'button', title: 'Aşağı', onclick: () => mv(1), disabled: i === items.length - 1 }, '↓'),
          h('button', { class: 'btn xs danger', type: 'button', title: 'Sil', onclick: () => { items.splice(i, 1); drawRows(); } }, '✕')));
    }) : [h('tr', null, h('td', { colspan: 6, class: 'muted small' }, 'Henüz ekipman yok. “Ekipman Ekle” ile başlayın.'))]);
    drawRows();
    const addBtn = h('button', { class: 'btn', type: 'button', onclick: () => { items.push({ name: '', qty: 1, unit: 'adet', note: '', product_id: null }); drawRows(); items[items.length - 1]._pick?.focus(); } }, '＋ Ekipman Ekle');
    const duties = {};
    const dutyRows = Object.entries(d.duty_titles).map(([k, title]) => {
      const ta = h('textarea', { class: 'input', rows: 2 }, d.duties[k]);
      duties[k] = ta;
      return h('label', { class: 'sc-field' }, h('span', { class: 'sc-field-l' }, h('b', null, title)), ta);
    });
    const save = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        const r = await api.put('/api/field/settings', {
          equipment: items.filter(e => e.product_id || (e.id && (e.name || '').trim())).map(e => ({ id: e.id || null, product_id: e.product_id || null, name: e.name, qty: e.qty, unit: e.unit, note: e.note })),
          duties: Object.fromEntries(Object.entries(duties).map(([k, ta]) => [k, ta.value])),
        });
        items = r.equipment.map(e => ({ ...e })); drawRows();
        toast('Saha Yönetimi ayarları kaydedildi', 'success');
      } catch (err) { toastError(err); } finally { save.disabled = false; }
    });
    clear(wrap,
      h('section', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Saha Ekipman Listesi'),
        h('p', { class: 'small muted' }, 'Her saha görevine götürülen standart ekipman. Yeni açılan her göreve otomatik eklenir; saha yöneticisi göreve özel çıkarabilir, ekleyebilir ve miktarı değiştirebilir. Buradaki değişiklik mevcut görevleri etkilemez.'),
        h('div', { class: 'table-wrap' }, h('table', { class: 'eq-table eq-std' },
          h('thead', null, h('tr', null, ['#', 'Ekipman', 'Miktar', 'Birim', 'Not', ''].map(c => h('th', null, c)))), tbody)),
        h('div', { class: 'set-actions left' }, addBtn)),
      h('section', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Saha Görev Tanımları'),
        h('p', { class: 'small muted' }, 'Saha görev raporunda, kişinin İnsan Kaynakları’nda görev tanımı yoksa rolüne göre bu açıklama yazılır.'),
        h('div', { class: 'sc-fields one' }, ...dutyRows)),
      h('div', { class: 'set-actions left' }, save));
  })();
  return wrap;
}

// ---- Güvenlik / Şifre kuralları -------------------------------------------------
function securityBody(view) {
  const wrap = h('div', null, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let pol = null;
  const P = {};   // alan → kontrol öğesi

  const num = (key, label, hint, { min = 0, max = 9999, suffix = '' } = {}) => {
    const inp = h('input', { class: 'input sc-num', type: 'number', min, max, step: 1 });
    P[key] = { get: () => Number(inp.value), set: v => { inp.value = v; } };
    return h('div', { class: 'set-row' }, h('div', { class: 'grow' }, h('b', null, label), hint ? h('small', null, hint) : null),
      numBox(inp, suffix));
  };
  const tog = (key, label, hint) => {
    const cb = h('input', { type: 'checkbox' });
    P[key] = { get: () => cb.checked, set: v => { cb.checked = !!v; } };
    return h('label', { class: 'set-toggle' }, cb, h('span', null, h('b', null, label), hint ? h('small', null, hint) : null));
  };
  const card = (title, sub, ...kids) => h('section', { class: 'card card-pad set-card' }, h('h3', null, title), sub ? h('p', { class: 'small muted' }, sub) : null, ...kids);

  const build = () => {
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Kuralları Kaydet');
    const resetBtn = h('button', { class: 'btn', type: 'button' }, 'Varsayılana Döndür');
    saveBtn.addEventListener('click', async () => {
      const data = {}; for (const k in P) data[k] = P[k].get();
      saveBtn.disabled = true;
      try { const r = await api.put('/api/system/security', data); apply(r.policy); toast('Güvenlik kuralları kaydedildi', 'success'); }
      catch (err) { toastError(err); } finally { saveBtn.disabled = false; }
    });
    resetBtn.addEventListener('click', async () => {
      if (!await confirmDialog('Varsayılana döndür', 'Tüm güvenlik / şifre kuralları varsayılan değerlere döndürülsün mü?', { okLabel: 'Döndür' })) return;
      apply(pol.defaults);
      toast('Varsayılanlar forma yüklendi — “Kuralları Kaydet” ile uygulayın');
    });
    clear(wrap,
      h('p', { class: 'small muted' }, 'Bu kurallar tüm kullanıcılara uygulanır: şifre değiştirme, giriş, oturum süresi, kaba kuvvet kilidi ve PIN.'),
      card('Şifre karmaşıklığı', 'Yeni / değiştirilen şifrelerin taşıması gereken kurallar.',
        num('min_length', 'En az uzunluk', 'Şifre bu kadar karakterden kısa olamaz', { min: 4, max: 64, suffix: 'karakter' }),
        tog('require_upper', 'Büyük harf zorunlu', 'En az bir A–Z / Ç,Ğ,İ… harfi'),
        tog('require_lower', 'Küçük harf zorunlu', 'En az bir a–z harfi'),
        tog('require_digit', 'Rakam zorunlu', 'En az bir 0–9 rakamı'),
        tog('require_symbol', 'Özel karakter zorunlu', 'En az bir !, ?, *, . gibi karakter'),
        tog('disallow_username', 'Kullanıcı adı içeremez', 'Şifre, kullanıcı adını barındıramaz'),
        tog('disallow_common', 'Yaygın şifreleri engelle', '“123456”, “password”, “parola” gibi bilinen şifreler reddedilir')),
      card('Şifre yaşam döngüsü', 'Şifre eskime ve yeniden kullanım.',
        num('expire_days', 'Şifre geçerlilik süresi', '0 = süresiz. Süre dolunca kullanıcı ilk girişte şifre değiştirir', { min: 0, max: 3650, suffix: 'gün' }),
        num('reuse_block', 'Yeniden kullanım engeli', '0 = kapalı. Son N şifre tekrar seçilemez', { min: 0, max: 24, suffix: 'şifre' }),
        tog('force_first_change', 'İlk girişte şifre değiştirmeyi zorunlu tut', 'Yöneticinin verdiği/sıfırladığı şifreyle giren kullanıcı devam etmeden önce şifresini değiştirir')),
      card('Giriş güvenliği', 'Kaba kuvvet koruması ve oturum.',
        num('lockout_fails', 'Kullanıcı deneme sınırı', 'Art arda bu kadar hatalı denemeden sonra hesap geçici kilitlenir', { min: 3, max: 100, suffix: 'deneme' }),
        num('ip_fails', 'IP deneme sınırı', 'Aynı ağ adresinden FARKLI hesaplara (hesap taraması) hatalı deneme sınırı. Tek işyeri tek internet (ortak IP) arkasındaysa 0 = kapalı önerilir.', { min: 0, max: 500, suffix: 'deneme' }),
        num('lockout_minutes', 'Kilit süresi', 'Sınır aşılınca bu süre boyunca giriş engellenir', { min: 1, max: 1440, suffix: 'dakika' }),
        num('session_hours', 'Oturum süresi', 'Giriş sonrası oturumun geçerli kalacağı süre', { min: 1, max: 720, suffix: 'saat' })),
      card('PIN ile giriş', 'Cihazda 4+ haneli PIN ile hızlı giriş.',
        tog('pin_enabled', 'PIN ile girişe izin ver', 'Kapatılırsa hiçbir kullanıcı PIN kullanamaz; herkes şifreyle girer'),
        num('pin_length', 'PIN hane sayısı', 'Yeni PIN’ler bu kadar haneli olur', { min: 4, max: 8, suffix: 'hane' })),
      h('div', { class: 'set-actions left' }, saveBtn, resetBtn));
  };
  const apply = data => { for (const k in P) if (k in data) P[k].set(data[k]); };

  (async () => {
    try { pol = await api.get('/api/system/security'); build(); apply(pol.policy); }
    catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); }
  })();
  return wrap;
}

// ---- Yapay Zeka: token kullanımı + kişiye özel aylık kota ----------------------
const kTok = n => (n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n || 0));
const trNum = n => Number(n || 0).toLocaleString('tr-TR');
const axTok = v => (v >= 1e6 ? `${+(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}K` : String(v));
const TR_MON = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
const pad2 = n => String(n).padStart(2, '0');
const isoDay = dt => `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())}`;

// Eksik günleri / ayları 0 ile doldurur → [{key, label, i, o, n}]
function fillSeries(rows, mode) {
  const by = Object.fromEntries(rows.map(r => [r.d, r]));
  const out = [];
  const now = new Date();
  if (mode === 'daily') {
    for (let k = 29; k >= 0; k--) {
      const dt = new Date(now.getFullYear(), now.getMonth(), now.getDate() - k);
      const key = isoDay(dt), r = by[key] || {};
      out.push({ key, label: `${dt.getDate()} ${TR_MON[dt.getMonth()]}`, i: r.i || 0, o: r.o || 0, n: r.n || 0 });
    }
  } else {
    for (let k = 11; k >= 0; k--) {
      const dt = new Date(now.getFullYear(), now.getMonth() - k, 1);
      const key = `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}`, r = by[key] || {};
      out.push({ key, label: `${TR_MON[dt.getMonth()]} ${String(dt.getFullYear()).slice(2)}`, i: r.i || 0, o: r.o || 0, n: r.n || 0 });
    }
  }
  return out;
}

// Zaman çizgi grafiği (girdi+çıktı toplamı ve çıktı ayrı çizgi); dokununca / üzerine gelince değer balonu.
function lineChart(series) {
  const W = 640, H = 260, L = 58, R = 12, T = 16, B = 36;
  const tot = series.map(p => p.i + p.o);
  const max = Math.max(1, ...tot);
  const step = (() => { const raw = max / 4, e = 10 ** Math.floor(Math.log10(raw)), f = raw / e; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * e; })();
  const top = step * Math.ceil(max / step);
  const n = series.length;
  const x = k => L + (n > 1 ? (k / (n - 1)) * (W - L - R) : (W - L - R) / 2);
  const y = v => T + (1 - v / top) * (H - T - B);
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; return e; };
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'sc-line' });
  for (let v = 0; v <= top + 1e-9; v += step) {
    svg.append(el('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'grid' }));
    svg.append(el('text', { x: L - 6, y: y(v) + 4, 'text-anchor': 'end', class: 'ax' }, axTok(v)));
  }
  const every = Math.max(1, Math.ceil(n / 5));
  series.forEach((p, k) => { if ((k % every === 0 && n - 1 - k >= every) || k === n - 1) svg.append(el('text', { x: x(k), y: H - 10, 'text-anchor': k === 0 ? 'start' : k === n - 1 ? 'end' : 'middle', class: 'ax' }, p.label)); });
  const pts = vals => vals.map((v, k) => `${x(k)},${y(v)}`).join(' ');
  svg.append(el('path', { d: `M${x(0)},${y(0)} L${pts(tot).replaceAll(' ', ' L')} L${x(n - 1)},${y(0)}Z`, class: 'area' }));
  svg.append(el('polyline', { points: pts(series.map(p => p.o)), class: 'ln out' }));
  svg.append(el('polyline', { points: pts(tot), class: 'ln tot' }));
  const guide = el('line', { y1: T, y2: H - B, class: 'guide', visibility: 'hidden' });
  const dot = el('circle', { r: 5, class: 'dot', visibility: 'hidden' });
  svg.append(guide, dot);
  const tip = h('div', { class: 'sc-line-tip', hidden: true });
  const box = h('div', { class: 'sc-line-wrap' }, svg, tip);
  const show = ev => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left) / r.width * W;
    const k = Math.max(0, Math.min(n - 1, Math.round((px - L) / ((W - L - R) / Math.max(1, n - 1)))));
    const p = series[k];
    guide.setAttribute('x1', x(k)); guide.setAttribute('x2', x(k)); guide.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', x(k)); dot.setAttribute('cy', y(tot[k])); dot.setAttribute('visibility', 'visible');
    clear(tip, h('b', null, p.label), h('div', null, `Toplam: ${trNum(tot[k])}`), h('div', { class: 'muted' }, `Girdi ${trNum(p.i)} · Çıktı ${trNum(p.o)}`), h('div', { class: 'muted' }, `${p.n} istek`));
    tip.hidden = false;
    const left = (x(k) / W) * 100;
    tip.style.left = `${Math.min(80, Math.max(20, left))}%`;
  };
  svg.addEventListener('pointermove', show);
  svg.addEventListener('pointerdown', show);
  svg.addEventListener('touchmove', show, { passive: true });
  svg.addEventListener('pointerleave', () => { tip.hidden = true; guide.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); });
  return box;
}

function usageModal(u) {
  const body = h('div', { class: 'sc-ai-detail' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  modal({ title: u.full_name, body, wide: true });
  (async () => {
    let d;
    try { d = await api.get(`/api/system/ai-usage/${u.id}`); } catch (err) { clear(body, h('div', { class: 'empty' }, err.message)); return; }
    const stat = (label, value, sub) => h('div', { class: 'sc-ai-stat' }, h('small', null, label), h('b', null, value), sub ? h('span', { class: 'small muted' }, sub) : null);
    const fmtDay = v => `${v.slice(8, 10)}.${v.slice(5, 7)}.${v.slice(0, 4)}`;
    const chartBox = h('div');
    let mode = 'daily';
    const seg = h('div', { class: 'seg' });
    const draw = () => {
      const s = fillSeries(mode === 'daily' ? d.daily : d.monthly, mode);
      clear(chartBox, s.some(p => p.i + p.o) ? lineChart(s) : h('div', { class: 'empty small' }, mode === 'daily' ? 'Son 30 günde kullanım yok.' : 'Son 12 ayda kullanım yok.'));
      for (const b of seg.children) b.classList.toggle('on', b.dataset.m === mode);
    };
    for (const [m, label] of [['daily', 'Son 30 gün'], ['monthly', 'Son 12 ay']]) {
      const b = h('button', { type: 'button', 'data-m': m }, label);
      b.addEventListener('click', () => { mode = m; draw(); });
      seg.append(b);
    }
    clear(body,
      h('div', { class: 'sc-ai-stats' },
        stat('Bu ay', kTok(d.month), d.quota ? t('kota {q} · %{pct}', { q: kTok(d.quota), pct: Math.round((d.month / d.quota) * 100) }) : 'kota sınırsız'),
        stat('Toplam', kTok(d.total), t('{n} istek', { n: trNum(d.calls) })),
        stat('Girdi', kTok(d.in_total), t('çıktı {n}', { n: kTok(d.out_total) })),
        stat('Son kullanım', d.last_at ? fmtDay(d.last_at) : '—', d.last_at ? `${d.last_at.slice(11, 16)}${d.first_at ? ` · ilk ${fmtDay(d.first_at)}` : ''}` : null)),
      h('div', { class: 'sc-ai-chart-h' }, h('b', null, 'Zamana göre kullanım'), seg),
      chartBox,
      h('div', { class: 'sc-ai-legend small muted' }, h('span', { class: 'k tot' }), 'Toplam (girdi+çıktı)', h('span', { class: 'k out' }), 'Çıktı'));
    draw();
  })();
}

function aiBody() {
  const wrap = h('div', null, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  (async () => {
    let d;
    try { d = await api.get('/api/system/ai-usage'); } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); return; }
    const defIn = h('input', { class: 'input sc-num', type: 'number', min: 0, step: 1000, value: d.default || 0 });
    const qInputs = {};
    const cards = d.users.map(u => {
      const inp = h('input', { class: 'input sc-num', type: 'number', min: 0, step: 1000, placeholder: 'varsayılan',
        value: u.custom ? u.quota : '', 'aria-label': t('{name} aylık kota', { name: u.full_name }) });
      qInputs[u.id] = inp;
      const over = u.quota && u.used_month >= u.quota;
      const ratio = u.quota ? Math.min(1, u.used_month / u.quota) : 0;
      const num = h('button', { class: `sc-ai-num ${over ? 'over' : ''}`, type: 'button', title: 'Kullanım ayrıntısı ve grafik' },
        h('b', null, kTok(u.used_month)), h('small', null, ` / ${u.quota ? kTok(u.quota) : '∞'}`));
      num.addEventListener('click', () => usageModal(u));
      return h('div', { class: `sc-ai-card ${over ? 'over' : ''}` },
        h('div', { class: 'sc-ai-who' }, avatar(u),
          h('div', { class: 'grow' }, h('b', null, u.full_name), h('small', null, u.username))),
        h('div', { class: 'sc-ai-use' },
          h('span', { class: 'small muted' }, 'Bu ay'), num),
        u.quota ? h('div', { class: 'sc-ai-bar' }, h('i', { style: { width: `${Math.round(ratio * 100)}%` } })) : null,
        h('label', { class: 'sc-ai-q' }, h('span', { class: 'small muted' }, 'Aylık kota'),
          numBox(inp, 'token')));
    });
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Kotaları Kaydet');
    saveBtn.addEventListener('click', async () => {
      const users = {}; for (const id in qInputs) { const v = Number(qInputs[id].value); if (v > 0) users[id] = v; }
      saveBtn.disabled = true;
      try { await api.put('/api/system/ai-quota', { default: Number(defIn.value) || 0, users }); toast('Kotalar kaydedildi', 'success'); }
      catch (err) { toastError(err); } finally { saveBtn.disabled = false; }
    });
    clear(wrap,
      h('section', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Yapay Zeka Asistanı'),
        h('p', { class: 'small muted' }, d.enabled ? t('Model: {model} · Kotalar aylık token (girdi+çıktı) toplamıdır; 0 = sınırsız. Ay: {month}', { model: d.model, month: d.month }) : 'Asistan anahtarı tanımlı değil (maskot gizli).'),
        h('div', { class: 'set-row' }, h('div', { class: 'grow' }, h('b', null, 'Varsayılan aylık kota'), h('small', null, 'Kişiye özel kota konmayan herkes için (0 = sınırsız)')),
          numBox(defIn, 'token'))),
      h('section', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Kullanıcılar (bu ay)'),
        h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Kişiye özel aylık kota girin; boş bırakılırsa varsayılan geçerli olur. Kotası dolan kullanıcıya kırıcı olmayan esprili bir mesaj gösterilir.'),
        h('div', { class: 'sc-ai-cards' }, ...cards),
        h('div', { class: 'set-actions left' }, saveBtn)));
  })();
  return wrap;
}

// ---- Yapay zekanın önerdiği kayıt değişiklikleri: onay/ret ----------------------
function aiChangesBody() {
  const wrap = h('div', null, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  const load = async () => {
    let d;
    try { d = await api.get('/api/system/ai-changes'); } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); return; }
    const STAT = { BEKLIYOR: ['Bekliyor', 'gray'], ONAYLANDI: ['Onaylandı', 'green'], RED: ['Reddedildi', 'red'], HATA: ['Hata', 'red'] };
    const card = r => {
      const badge = STAT[r.status] || [r.status, 'gray'];
      const pending = r.status === 'BEKLIYOR';
      const editable = pending || r.status === 'HATA';
      let pv = null; try { pv = r.preview ? JSON.parse(r.preview) : null; } catch { /* */ }
      const appr = h('button', { class: 'btn primary xs', type: 'button' }, 'Onayla ve Uygula');
      const rej = h('button', { class: 'btn xs', type: 'button' }, 'Reddet');
      const edit = h('button', { class: 'btn xs', type: 'button' }, r.status === 'HATA' ? 'SQL’i Düzelt ve Yeniden Dene' : 'SQL’i Düzenle');
      edit.addEventListener('click', () => {
        const ta = h('textarea', { class: 'input sc-sql-edit', rows: 10, spellcheck: 'false' }, r.sql);
        const msg = h('div', { class: 'small muted' }, 'Kaydetmeden önce SQL geri alınabilir şekilde denenir; hata verirse kaydedilmez.');
        modal({ title: t('Talep #{id} · SQL', { id: r.id }), wide: true, body: h('div', null, h('p', { class: 'small' }, r.summary), ta, msg), actions: ['spacer',
          { label: 'Vazgeç' },
          { label: 'Dene ve Kaydet', class: 'primary', onClick: async () => {
            try { const res = await api.put(`/api/system/ai-changes/${r.id}`, { sql: ta.value }); toast(t('Ön deneme başarılı · {n} satır. Talep onay bekliyor.', { n: res.affected }), 'success'); load(); return false; }
            catch (err) { msg.textContent = err.message; msg.className = 'sc-integ-msg err'; return true; }   // hata: pencere açık kalsın
          } }] });
      });
      appr.addEventListener('click', async () => {
        appr.disabled = true;
        let pre;
        try { pre = await api.post(`/api/system/ai-changes/${r.id}/preview`, {}); } catch (err) { pre = { ok: false, error: err.message }; }
        appr.disabled = false;
        if (!pre.ok) {
          toast(t('Bu SQL şu an uygulanamaz: {err}. “SQL’i Düzenle” ile düzeltebilirsiniz.', { err: pre.error }), 'err');
          return;
        }
        if (!await confirmDialog('Değişikliği onayla', t('Ön deneme: {n} satır etkilenecek{each}.\n\n{sql}\n\nUygulansın mı?', { n: pre.affected, each: pre.each.length > 1 ? ` (${pre.each.join(' + ')})` : '', sql: r.sql }), { okLabel: 'Onayla ve Uygula', danger: true })) return;
        appr.disabled = rej.disabled = true;
        try { const res = await api.post(`/api/system/ai-changes/${r.id}/approve`, {}); res.ok ? toast(t('Uygulandı ({n} satır)', { n: res.affected }), 'success') : toast(res.error || 'Uygulanamadı', 'err'); load(); }
        catch (err) { toastError(err); appr.disabled = rej.disabled = false; }
      });
      rej.addEventListener('click', async () => {
        if (!await confirmDialog('Talebi reddet', t('“{summary}” talebi reddedilsin mi?', { summary: r.summary }), { okLabel: 'Reddet' })) return;
        rej.disabled = appr.disabled = true;
        try { await api.post(`/api/system/ai-changes/${r.id}/reject`, { note: '' }); toast('Reddedildi'); load(); }
        catch (err) { toastError(err); rej.disabled = appr.disabled = false; }
      });
      return h('div', { class: `card card-pad sc-change ${pending ? 'pending' : ''}` },
        h('div', { class: 'sc-change-h' }, h('b', null, r.user_name), h('span', { class: `badge ${badge[1]}` }, badge[0]),
          h('span', { class: 'small muted', style: { marginLeft: 'auto' } }, (r.created_at || '').slice(0, 16).replace('T', ' '))),
        h('div', { class: 'sc-change-sum' }, r.summary),
        h('pre', { class: 'sc-change-sql' }, r.sql),
        pending && pv ? h('div', { class: 'small muted' }, t('Ön deneme: {n} satır etkilenecek', { n: pv.affected })) : null,
        r.note ? h('div', { class: 'small muted' }, t('Not: {note}{extra}', { note: r.note, extra: r.affected != null ? ` · ${r.affected} satır` : '' })) : null,
        r.status === 'ONAYLANDI' && r.affected != null ? h('div', { class: 'small muted' }, t('Uygulandı · {n} satır', { n: r.affected })) : null,
        editable ? h('div', { class: 'set-actions left' }, pending ? appr : null, edit, pending ? rej : null) : null);
    };
    const pend = d.items.filter(r => r.status === 'BEKLIYOR');
    const done = d.items.filter(r => r.status !== 'BEKLIYOR');
    clear(wrap,
      h('p', { class: 'small muted' }, 'Yapay zekanın kullanıcı adına önerdiği kayıt değişiklikleri. Onayladığınızda SQL, ilgili kullanıcının yetkisiyle çalıştırılır ve kullanıcıya bildirim gider.'),
      h('h3', null, t('Onay bekleyen ({n})', { n: pend.length })),
      pend.length ? h('div', { class: 'sc-change-list' }, ...pend.map(card)) : h('div', { class: 'empty small' }, 'Bekleyen talep yok.'),
      done.length ? h('h3', null, 'Son kararlar') : null,
      done.length ? h('div', { class: 'sc-change-list' }, ...done.map(card)) : null);
  };
  load();
  return wrap;
}

// Merkez (Veilox) destek girişleri: onay bekleyenler + aktif oturumlar (yalnız MASTER)
function supportBody(view, ctx) {
  const wrap = h('div');
  const sec = (title, sub, ...kids) => h('section', { class: 'card card-pad set-card' }, h('h3', null, title), sub ? h('p', { class: 'small muted' }, sub) : null, ...kids);
  const load = async () => {
    let d;
    try { d = await api.get('/api/auth/crosslogin/pending'); }
    catch (e) { return clear(wrap, sec('Merkez Destek', null, h('p', { class: 'muted' }, e.message))); }
    const pend = (d.pending || []).map(p => h('div', { class: 'set-row' },
      h('div', { class: 'grow' }, h('b', null, p.full_name || p.username), h('small', { class: 'muted' }, `${p.username} · IP ${p.ip}`)),
      h('button', { class: 'btn sm', type: 'button', onclick: async () => { try { await api.post(`/api/auth/crosslogin/${p.id}/decision`, { approve: false }); toast('Reddedildi'); load(); } catch (e2) { toastError(e2); } } }, 'Reddet'),
      h('button', { class: 'btn sm primary', type: 'button', onclick: async () => { try { await api.post(`/api/auth/crosslogin/${p.id}/decision`, { approve: true }); toast('Onaylandı'); load(); } catch (e2) { toastError(e2); } } }, 'Onayla')));
    const active = (d.active || []).map(a => h('div', { class: 'set-row' },
      h('div', { class: 'grow' }, h('b', null, a.full_name || a.username), h('small', { class: 'muted' }, t('{u} · bitiş: {d}', { u: a.username, d: fmtDateTime(a.support_until) }))),
      h('button', { class: 'btn sm danger', type: 'button', onclick: async () => {
        if (!await confirmDialog('Oturumu sonlandır', t('{name} destek oturumu sonlandırılsın mı?', { name: a.full_name || a.username }), { okLabel: 'Sonlandır', danger: true })) return;
        try { await api.post(`/api/auth/crosslogin/end/${a.user_id}`); toast('Oturum sonlandırıldı'); load(); } catch (e2) { toastError(e2); }
      } }, 'Sonlandır')));
    clear(wrap, sec('Merkez Destek Oturumları',
      'Veilox destek görevlilerinin firmanıza çapraz girişleri. Onaylarsanız süreli ve kayıt altında, master-benzeri yetkiyle girerler; dilediğinizde sonlandırabilirsiniz.',
      pend.length ? h('div', null, h('h4', { class: 'set-sub' }, 'Onay bekleyen'), ...pend) : null,
      active.length ? h('div', null, h('h4', { class: 'set-sub' }, 'Aktif oturumlar'), ...active) : null,
      (!pend.length && !active.length) ? h('p', { class: 'muted' }, 'Bekleyen talep ya da aktif destek oturumu yok.') : null));
  };
  load();
  return wrap;
}

function kvkkBody() {
  const wrap = h('div', null, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  const KIND = { export: 'Veri kopyası', delete: 'Silme / unutulma', object: 'İşlemeye itiraz' };
  const load = async () => {
    let s, bio, reqs;
    try {
      [s, bio, reqs] = await Promise.all([api.get('/api/kvkk/settings'), api.get('/api/kvkk/biometric-status'), api.get('/api/kvkk/requests')]);
    } catch (err) { clear(wrap, h('div', { class: 'card empty' }, err.message)); return; }
    const open = reqs.filter(r => r.status === 'open');

    // 1 - Veri sahibi başvuruları
    const reqCard = h('div', { class: 'card card-pad' },
      h('h3', null, 'Veri sahibi başvuruları (KVKK md. 11)'),
      reqs.length ? h('div', { class: 'ios-group' }, reqs.map(r => h('div', { class: 'ios-row', style: { display: 'block' } },
        h('div', null, h('b', null, r.user_name), ' — ', KIND[r.kind] || r.kind,
          h('span', { class: `pill ${r.status === 'open' ? 'warn' : 'ok'}`, style: { marginLeft: '8px' } }, r.status === 'open' ? 'Açık' : 'Kapatıldı')),
        r.note ? h('div', { class: 'small muted' }, r.note) : null,
        h('div', { class: 'small muted' }, new Date(r.created_at).toLocaleString('tr') + (r.handler_name ? ` · ${r.handler_name}` : '') + (r.resolution ? ` · ${r.resolution}` : '')),
        r.status === 'open' ? h('button', { class: 'btn xs primary', style: { marginTop: '6px' }, type: 'button', onclick: async () => {
          const note = prompt('Kapatma açıklaması (talebe ilişkin yapılan işlem):', '');
          if (note === null) return;
          try { await api.post(`/api/kvkk/requests/${r.id}/handle`, { resolution: note }); toast('Başvuru kapatıldı', 'success'); load(); } catch (err) { toastError(err); }
        } }, 'İncele ve Kapat') : null))) : h('p', { class: 'muted' }, 'Başvuru yok.'));

    // 2 - Biyometrik rıza durumu, denetim
    const bioCard = h('div', { class: 'card card-pad' },
      h('h3', null, 'Biyometrik (yüz) rıza durumu'),
      h('p', { class: 'small muted' }, `Yüz tanımaya atanmış ${bio.enrolled} kişi; açık rızası işaretlenmemiş ${bio.missing_consent} kişi.`),
      bio.missing_consent ? h('p', { class: 'small', style: { color: '#ff9500' } },
        'Denetim modunda tanıma çalışmaya devam eder. Açık rıza kişi bazında İnsan Kaynakları › personel › Özlük › ' +
        '“KVKK Rızası” sekmesinden işaretlenir; aydınlatma yapıp açık rıza topladıkça buradan kaydedin.') : null);

    // 3 - Ayarlar
    const enforce = h('input', { type: 'checkbox', ...(s.biometric_enforce ? { checked: true } : {}) });
    const rSight = h('input', { class: 'input', type: 'number', min: '1', value: s.retention_sightings_days });
    const rAudio = h('input', { class: 'input', type: 'number', min: '1', value: s.retention_audio_days });
    const rAudit = h('input', { class: 'input', type: 'number', min: '1', value: s.retention_audit_days });
    const save = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        await api.put('/api/kvkk/settings', {
          biometric_enforce: enforce.checked ? 1 : 0,
          retention_sightings_days: +rSight.value || 90, retention_audio_days: +rAudio.value || 90, retention_audit_days: +rAudit.value || 365,
        });
        toast('KVKK ayarları kaydedildi', 'success');
      } catch (err) { toastError(err); } finally { save.disabled = false; }
    });
    const setCard = h('div', { class: 'card card-pad' },
      h('h3', null, 'Saklama ve uygulama'),
      h('label', { class: 'sc-check' }, enforce, ' Rızasız kişilerde biyometriyi işleme (kapalı = denetim modu, tanıma çalışır)'),
      field('Kamera görülme kayıtlarını sakla (gün)', rSight),
      field('Görüşme ses kayıtlarını sakla (gün)', rAudio),
      field('Giriş/işlem (audit) kayıtlarını sakla (gün)', rAudit),
      h('p', { class: 'small muted' }, 'Süre dolan kayıtlar her gün otomatik silinir. Yasal saklama yükümlülükleri saklıdır.'),
      save);

    clear(wrap, open.length ? h('div', { class: 'card card-pad', style: { borderLeft: '3px solid #ff9500' } }, `${open.length} açık başvuru bekliyor.`) : null,
      reqCard, bioCard, setCard);
  };
  load();
  return wrap;
}

const GROUPS = [
  { key: 'security', title: 'Güvenlik', desc: 'Şifre kuralları, giriş ve PIN', icon: 'lock', body: securityBody },
  { key: 'support', title: 'Merkez Destek', desc: 'Veilox destek girişleri: onay ve aktif oturumlar', icon: 'lock', body: supportBody, master: true },
  { key: 'ai', title: 'Yapay Zeka', desc: 'Maskot asistanı: token kullanımı ve kotalar', icon: 'bolt', body: aiBody, needs: 'ai' },
  { key: 'ai-changes', title: 'YZ Onayları', desc: 'Yapay zekanın önerdiği kayıt değişiklikleri', icon: 'bolt', body: aiChangesBody, needs: 'ai' },
  { key: 'modules', title: 'Modül Ayarları', desc: 'Modüllere özel ayarlar (Saha Yönetimi…)', icon: 'layers', body: modulesBody },
  { key: 'integrations', title: 'Entegrasyonlar', desc: 'API anahtarları: Claude, Mikro ERP, Google', icon: 'grid', body: integrationsBody },
  { key: 'identity', title: 'Firma Kimliği', desc: 'Ünvan ve logo', icon: 'building', body: identityBody, master: true },
  { key: 'kvkk', title: 'KVKK / Veri Koruma', desc: 'Açık rıza durumu, veri başvuruları ve saklama süreleri', icon: 'lock', body: kvkkBody },
  // Modül olarak var; Program Ayarları altından açılır (link). Veri & Yedek yalnızca sistem sahibi (MASTER).
  { key: 'users', title: 'Kullanıcı Yönetimi', desc: 'Kullanıcılar ve rol atamaları', icon: 'users', link: '#/users' },
  { key: 'roles', title: 'Rol Yönetimi', desc: 'Roller, modül yetkileri (aç / oku / yaz), miras ve çakışmalar', icon: 'lock', body: rolesBody },
  { key: 'master', title: 'Veri & Yedek', desc: 'KVKK veri indirme ve yedekleme', icon: 'server', link: '#/master', master: true },
];

const SC_COLORS = { roles: '#ff2d55', security: '#ff3b30', support: '#34c759', ai: '#af52de', 'ai-changes': '#5856d6', modules: '#0a84ff', integrations: '#ff9500', identity: '#30b0c7', kvkk: '#30d158', users: '#ff3b30', master: '#af52de' };
const SC_SECTIONS = [['security', 'support', 'ai'], ['ai-changes'], ['modules', 'integrations', 'identity', 'kvkk'], ['users', 'roles', 'master']];

export async function render(view, params, ctx) {
  if (!(ctx.user.master || (ctx.user.roles || []).includes('Sistem Yöneticisi'))) {
    clear(view, pageHead('Program Ayarları', { back: '#/' }), h('div', { class: 'card empty' }, 'Bu bölüm yalnızca sistem yöneticisine açıktır.'));
    return;
  }
  // Claude API anahtarı girilmemişse yapay zeka bölümleri gizli (anahtar Entegrasyonlar'dan girilir)
  const groups = GROUPS.filter(x => (!x.needs || ctx.user[x.needs]) && (!x.master || ctx.user.master));
  const SUBTITLE = 'Sistem geneli ayarlar · yalnızca sistem yöneticisi';
  // Mobilde iOS Ayarlar gibi gruplanmış ana liste; masaüstünde iki sütun.
  const used = new Set(SC_SECTIONS.flat());
  const rest = groups.filter(gr => !used.has(gr.key)).map(gr => gr.key);
  const allSections = rest.length ? [...SC_SECTIONS, rest] : SC_SECTIONS;
  const masterList = () => h('div', { class: 'set-ios' }, allSections.map(keys => {
    const rows = keys.map(k => groups.find(gr => gr.key === k)).filter(Boolean);
    return rows.length ? h('div', { class: 'ios-group' }, rows.map(gr => h('a', { class: 'ios-row', href: gr.link || `#/sysconfig/${gr.key}` },
      h('span', { class: 'ios-ico', style: { background: SC_COLORS[gr.key] || '#8e8e93' } }, segIconByKey(gr.icon)),
      h('span', { class: 'ios-label' }, h('b', null, gr.title), h('small', null, gr.desc)),
      h('span', { class: 'ios-chev' })))) : null;
  }).filter(Boolean));

  const draw = () => {
    const g = groups.find(x => x.key === params[0]) || groups[0];
    if (g.link) { location.replace(g.link); return; }   // Kullanıcı Yönetimi / Veri & Yedek ayrı modül sayfasına gider
    if (SC_MQ.matches) {
      if (params[0]) clear(view, pageHead(g.title, { back: '#/sysconfig', sub: g.desc }), h('div', { class: 'set-detail set-detail-solo' }, g.body(view, ctx)));
      else clear(view, masterList());   // mobil ana liste: başlık / geri / açıklama gösterilmez (iOS tarzı)
    } else {
      clear(view, pageHead('Program Ayarları', { back: '#/', sub: SUBTITLE }),
        h('div', { class: 'set-layout' },
          h('nav', { class: 'card set-nav' }, groups.map(x => h('a', { href: x.link || `#/sysconfig/${x.key}`, class: x === g ? 'on' : '' },
            h('span', { class: 'set-ico' }, segIconByKey(x.icon)), h('span', null, h('b', null, x.title), h('small', null, x.desc))))),
          h('div', { class: 'set-detail' }, g.body(view, ctx))));
    }
  };
  _scRedraw = draw;
  draw();
}
