// Kişisel Ayarlar › Hesap › Yüz ile giriş — iPhone Face ID tarzı yüz tanıtma (eğitim) ekranı ve ayar bölümü.
// Tam ekran koyu kart: ortada yuvarlak kamera, çevresinde 360° segmentli halka (8 yön × 9 çubuk; dolan segment yeşile döner),
// yönlendirme metni, canlı poz noktası. Kareler sunucuya gider (POST /api/auth/face/enroll/frame); yuvaları SUNUCU hesaplar ve
// gömmeyi saklar — tarayıcıya biyometrik şablon dönmez. Tamamlanınca tik animasyonu + "Yüzünüz tanıtıldı"; ikinci tarama isteğe bağlı.
// Bkz. docs/yuz-tanima.md §3.
import { api } from '../api.js';
import { DIRECTION_TEXT, SLOTS, framing, framingHint, nextSegment } from '../facemath.js';
import { cameraErrorText, closeCamera, createFaceRing, ensureFaceStyle, faceIcon, frameLoop, openCamera } from '../facering.js';
import { clear, field, fmtDateTime, h, modal, segmented, t, toast, toastError } from '../ui.js';

const ENOUGH_AFTER = 15000;   // yeterli yuva varsa bu süreden sonra "Tamamla" düğmesi görünür (ms); tam daire = kendiliğinden biter

// Tam ekran eğitim. opts: {append, onDone(status)}
export function openFaceSetup(ctx, { append = false, onDone } = {}) {
  ensureFaceStyle();
  const sheet = h('div', { class: 'fe-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': t('Yüz tanıtma') });
  const card = h('div', { class: 'fe-card' });
  sheet.append(card);
  document.body.append(sheet);
  document.body.classList.add('fe-open');
  let ring = null, loop = null, enrollId = null, closed = false, startedAt = 0;

  function close(status) {
    if (closed) return;
    closed = true;
    if (loop) { loop.stop(); loop = null; }
    if (ring) closeCamera(ring.video);
    if (enrollId) api.post('/api/auth/face/enroll/cancel', { enroll_id: enrollId }).catch(() => {});
    sheet.classList.add('out');
    document.body.classList.remove('fe-open');
    document.removeEventListener('keydown', onKey);
    setTimeout(() => sheet.remove(), 260);
    onDone?.(status || null);
  }
  const onKey = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);

  // ---- 1) Giriş kartı: açıklama + şifre
  function intro() {
    const pw = h('input', { class: 'input', type: 'password', autocomplete: 'current-password', required: true, placeholder: t('Mevcut şifreniz') });
    const go = h('button', { class: 'btn primary lg fe-go', type: 'submit' }, append ? 'İkinci taramayı başlat' : 'Başla');
    const form = h('form', { class: 'fe-intro' },
      h('div', { class: 'fe-hero' }, faceIcon('fe-hero-ico')),
      h('h2', null, append ? 'İkinci tarama' : 'Yüz ile giriş'),
      h('p', { class: 'fe-lead' }, append
        ? 'Farklı ışık ve açılarda ikinci bir tarama tanımayı daha güvenilir yapar. Gözlük takıyorsanız bu kez çıkarabilirsiniz.'
        : 'Giriş ekranında şifre ya da PIN yerine yüzünüzle giriş yapın. Yüzünüz birkaç açıdan taranır; yalnızca matematiksel bir özet şifrelenerek saklanır, fotoğraf saklanmaz.'),
      h('ul', { class: 'fe-steps' },
        h('li', null, h('b', null, '1'), h('span', null, 'Yüzünüzü dairenin içine alın')),
        h('li', null, h('b', null, '2'), h('span', null, 'Başınızı yavaşça daire çizerek çevirin')),
        h('li', null, h('b', null, '3'), h('span', null, 'Halka tamamlanınca yüzünüz tanıtılır'))),
      field('Güvenlik için mevcut şifreniz', pw),
      h('div', { class: 'fe-actions' }, h('button', { class: 'btn ghost', type: 'button', onclick: () => close() }, 'Vazgeç'), go));
    form.addEventListener('submit', async e => {
      e.preventDefault(); go.disabled = true;
      try {
        const r = await api.post('/api/auth/face/enroll/start', { password: pw.value, append });
        enrollId = r.enroll_id;
        scan();
      } catch (err) { toastError(err); go.disabled = false; pw.select(); }
    });
    clear(card, form);
    pw.focus();
  }

  // ---- 2) Tarama
  async function scan() {
    ring = createFaceRing({ size: Math.min(300, Math.floor(Math.min(window.innerWidth * 0.74, window.innerHeight * 0.42))), label: 'Kamera başlatılıyor…' });
    const finishBtn = h('button', { class: 'btn primary', type: 'button', hidden: true, onclick: () => finish() }, 'Tamamla');
    const counter = h('div', { class: 'fe-counter' }, t('{n} / 9 açı', { n: 0 }));
    clear(card, h('div', { class: 'fe-scan' },
      h('button', { class: 'fe-x', type: 'button', 'aria-label': t('Kapat'), onclick: () => close() }, '×'),
      h('h2', null, append ? 'İkinci tarama' : 'Yüzünüzü tanıtın'),
      ring.el, counter,
      h('div', { class: 'fe-actions' }, h('button', { class: 'btn ghost', type: 'button', onclick: () => close() }, 'İptal'), finishBtn)));
    try { await openCamera(ring.video); } catch (err) {
      ring.fail(); ring.setText(cameraErrorText(err)); ring.setHint('');
      return;
    }
    if (closed) return;
    ring.setState('scan'); ring.setText(DIRECTION_TEXT.center);
    startedAt = Date.now();
    let slots = [], noFaceSince = 0, enough = false, finishing = false;
    const update = () => {
      ring.setSlots(slots);
      const nx = nextSegment(slots);
      ring.setNext(nx === 'center' ? null : nx);
      counter.textContent = t('{n} / 9 açı', { n: slots.length });
      if (nx) ring.setText(slots.length === 0 ? DIRECTION_TEXT.center : slots.length === 1 ? 'Başınızı yavaşça daire çizerek çevirin' : DIRECTION_TEXT[nx]);
    };
    update();
    loop = frameLoop(ring.video, async jpg => {
      if (closed || finishing) return;
      let r;
      try { r = await api.post('/api/auth/face/enroll/frame', { enroll_id: enrollId, jpg }); } catch (err) {
        if (closed || finishing) return;
        if (err.status === 410) { loop.stop(); ring.fail(); ring.setText('Süre doldu'); ring.setHint('Yeniden başlatın'); enrollId = null; return; }
        ring.setHint(err.message || 'Bağlantı hatası'); return;
      }
      if (closed || finishing) return;   // "Tamamla" basıldıysa uçuştaki kare sonucu ekranı geri yazmasın
      if (!r.found) {
        ring.setLive(null);
        noFaceSince = noFaceSince || Date.now();
        if (Date.now() - noFaceSince > 1000) { ring.noFace(true); ring.setHint(r.small ? 'Biraz yaklaşın' : 'Yüz bulunamadı — kameraya bakın'); }
        return;
      }
      noFaceSince = 0; ring.noFace(false);
      ring.setLive(r.yaw, r.pitch);
      if (r.other_face) { ring.setHint('Farklı bir yüz algılandı — yalnızca kendi yüzünüzü tanıtın'); return; }
      if (r.need_center) { ring.setHint('Önce doğrudan kameraya bakın'); return; }
      ring.setHint(slots.length === 0 ? (framingHint(framing(r.box, r.w || 480, r.h || 360)) || '') : '');
      if (r.added) ring.stage.classList.remove('fr-tick-pop'), void ring.stage.offsetWidth, ring.stage.classList.add('fr-tick-pop');
      slots = r.slots || slots;
      update();
      enough = !!r.enough;
      if (r.complete) { finishing = true; finish(); return; }
      if (enough && Date.now() - startedAt > ENOUGH_AFTER) finishBtn.hidden = false;
    });

    async function finish() {
      finishing = true;
      if (loop) { loop.stop(); loop = null; }
      ring.setText('Kaydediliyor…'); ring.setHint('');
      try {
        const r = await api.post('/api/auth/face/enroll/finish', { enroll_id: enrollId });
        enrollId = null;
        closeCamera(ring.video);
        done(r);
      } catch (err) { finishing = false; toastError(err); ring.setHint(err.message); finishBtn.hidden = false; }
    }
  }

  // ---- 3) Başarı
  function done(st) {
    ring.celebrate(); ring.setText(append ? 'İkinci tarama tamamlandı' : 'Yüzünüz tanıtıldı'); ring.setHint(t('{n} açıdan kaydedildi', { n: st.count }));
    const actions = h('div', { class: 'fe-actions fe-done-actions' });
    if (!append) actions.append(h('button', { class: 'btn', type: 'button', onclick: () => { closed = true; sheet.remove(); document.body.classList.remove('fe-open'); document.removeEventListener('keydown', onKey); openFaceSetup(ctx, { append: true, onDone }); } }, 'İkinci taramayı yap (önerilir)'));
    actions.append(h('button', { class: 'btn primary lg', type: 'button', onclick: () => close(st) }, 'Bitti'));
    const scanBox = card.querySelector('.fe-scan');
    if (scanBox) {
      scanBox.querySelector('.fe-counter')?.remove();
      scanBox.querySelector('.fe-actions')?.replaceWith(actions);
      scanBox.querySelector('h2').textContent = t('Hazır');
      scanBox.classList.add('done');
    }
    setTimeout(() => actions.querySelector('.primary')?.focus(), 900);
  }

  intro();
  return { close };
}

// ---- Kişisel Ayarlar › Hesap kartındaki bölüm (asenkron durum)
export function faceSection(ctx, { onChange } = {}) {
  ensureFaceStyle();
  const box = h('div', { class: 'fe-section' }, h('div', { class: 'small muted' }, 'Yükleniyor…'));
  const draw = async () => {
    let st;
    try { st = await api.get('/api/auth/face/status'); } catch (err) { return clear(box, h('p', { class: 'small muted' }, err.message)); }
    const rows = [h('h4', { class: 'set-sub' }, faceIcon(), ' ', 'Yüz ile giriş')];
    if (!st.policy_enabled) {
      rows.push(h('p', { class: 'small muted' }, 'Yüz ile giriş sistem yöneticisi tarafından kapatılmış.'));
      return clear(box, rows);
    }
    if (!st.engine) {
      rows.push(h('p', { class: 'small muted' }, 'Yüz tanıma motoru bu sunucuda kurulu değil; yöneticinize başvurun.'));
      return clear(box, rows);
    }
    rows.push(h('p', { class: 'small muted' }, 'Bu cihazda bir kez şifreyle giriş yaptıktan sonra giriş ekranında adınıza dokunup yüzünüzle girebilirsiniz. Yüzünüzün yalnızca şifrelenmiş matematiksel özeti saklanır; fotoğraf saklanmaz.'));
    const refresh = r => { draw(); onChange?.(r); };
    if (!st.enrolled) {
      rows.push(h('div', { class: 'fe-status off' }, h('span', { class: 'fe-dot' }), h('span', null, 'Yüz tanıtılmamış')),
        h('div', { class: 'set-actions left' }, h('button', { class: 'btn primary', type: 'button', onclick: () => openFaceSetup(ctx, { onDone: refresh }) }, faceIcon(), ' ', 'Yüzünüzü tanıtın')));
      return clear(box, rows);
    }
    rows.push(h('div', { class: 'fe-status on' }, h('span', { class: 'fe-dot' }),
      h('span', null, t('Yüz tanıtıldı · {n} açı', { n: st.count }), st.updated_at ? h('small', { class: 'muted' }, ' · ', fmtDateTime(st.updated_at)) : null)));
    // Kip: yalnız yüz / yüz + PIN
    const modeSeg = segmented([['face', 'Yalnız yüz'], ['face_pin', 'Yüz + PIN']], st.mode, async v => {
      if (v === 'face_pin' && !st.has_pin) { toast('Önce PIN ile girişi açın', 'err'); draw(); return; }
      try { await api.put('/api/auth/face/mode', { mode: v }); toast(v === 'face_pin' ? 'Yüz doğrulandıktan sonra PIN de istenecek' : 'Yalnız yüz ile giriş'); } catch (err) { toastError(err); }
      draw();
    });
    rows.push(h('div', { class: 'set-row' }, h('div', { class: 'grow' }, h('b', null, 'Giriş kipi'), h('small', null, st.mode === 'face_pin' ? 'Yüz doğrulanınca ek olarak PIN sorulur (daha güvenli)' : 'Yüz doğrulanınca doğrudan giriş')), modeSeg));
    rows.push(h('div', { class: 'set-actions left fe-btns' },
      h('button', { class: 'btn', type: 'button', onclick: () => openFaceSetup(ctx, { append: true, onDone: refresh }) }, 'İkinci tarama'),
      h('button', { class: 'btn', type: 'button', onclick: () => openFaceSetup(ctx, { onDone: refresh }) }, 'Yeniden tanıt'),
      h('button', { class: 'btn danger', type: 'button', onclick: () => deleteFace(refresh) }, 'Yüz verisini sil')));
    clear(box, rows);
  };
  function deleteFace(after) {
    const pw = h('input', { class: 'input', type: 'password', autocomplete: 'current-password' });
    modal({
      title: 'Yüz verisini sil',
      body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Kayıtlı yüz özeti kalıcı olarak silinir; giriş ekranında yüz ile giriş kapanır. İstediğiniz zaman yeniden tanıtabilirsiniz.'), field('Mevcut şifreniz', pw)),
      actions: [{ label: 'Vazgeç' }, { label: 'Sil', class: 'danger', onClick: async () => {
        await api.post('/api/auth/face/delete', { password: pw.value });
        toast('Yüz verisi silindi');
        after({ enrolled: false });
      } }],
    });
  }
  draw();
  return box;
}

export { SLOTS };
