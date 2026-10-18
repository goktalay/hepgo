// Giriş ekranı — Yüz ile giriş (güvenilir cihazdaki hesap için). Akış: POST /api/auth/face/challenge (tek kullanımlık nonce +
// rastgele canlılık yönü) → kamera → kareler POST /verify: eşleme → "hafifçe sağa bakın" canlılık → oturum (ya da yüz+PIN kipinde
// PIN klavyesi). Başarısızlık / izin reddi / kamera yok → PIN ya da şifreye düşer. Bkz. docs/yuz-tanima.md §4.
import { api } from './api.js';
import { DIRECTION_TEXT, framing, framingHint } from './facemath.js';
import { cameraErrorText, closeCamera, createFaceRing, faceIcon, frameLoop, openCamera } from './facering.js';
import { clear, h, t } from './ui.js';

const POSE_TEXT = { left: 'Hafifçe sola bakın', right: 'Hafifçe sağa bakın', up: 'Hafifçe yukarı bakın', down: 'Hafifçe aşağı bakın' };
const RETRIES = 2;   // kare sınırı dolunca en çok bu kadar yeni meydan okuma

// box: giriş kartı gövdesi; a: hesap ({token, full_name, has_pin, face_mode}); header(a): üst satır düğümleri;
// onLogin(): oturum açıldı; onPin(a): PIN ekranına geç; onPassword(a): şifre ekranına geç; pinPad(a, submit): PIN klavyesi çizici
export function faceLogin(box, a, { header, onLogin, onPin, onPassword, pinPad }) {
  const ring = createFaceRing({ size: Math.min(260, Math.floor(window.innerWidth * 0.68)), label: 'Kamera başlatılıyor…' });
  const fallback = h('div', { class: 'fl-fallback' },
    a.has_pin ? h('button', { type: 'button', class: 'btn ghost', onclick: () => { stop(); onPin(a); } }, 'PIN ile giriş yap') : null,
    h('button', { type: 'button', class: 'btn ghost', onclick: () => { stop(); onPassword(a); } }, 'Şifreyle giriş yap'));
  const retry = h('button', { type: 'button', class: 'btn primary fl-retry', hidden: true, onclick: () => start() }, 'Yeniden dene');
  clear(box, ...header(a), h('div', { class: 'fl-title' }, faceIcon(), h('span', null, 'Yüz ile giriş')), ring.el, retry, fallback);

  let loop = null, stopped = false, challenge = null, pose = null, stage = 'match', retries = 0, fallTimer = null;
  const globe = pause => window.dispatchEvent(new CustomEvent('hepgo:globe', { detail: { pause } }));   // arka plan küresi kamera sürerken durur

  function stop() {
    stopped = true;
    if (loop) { loop.stop(); loop = null; }
    clearTimeout(fallTimer);
    closeCamera(ring.video);
    globe(false);
  }
  // kart DOM'dan kalkarsa (başka ekrana geçildi) kamera kapanır
  const watch = setInterval(() => { if (!box.isConnected || !box.contains(ring.el)) { clearInterval(watch); stop(); } }, 800);

  function failTo(msg, { auto = true } = {}) {
    if (loop) { loop.stop(); loop = null; }
    ring.fail(); ring.setLive(null); ring.setText(msg); ring.setHint(auto ? (a.has_pin ? 'PIN ekranına geçiliyor…' : 'Şifre ekranına geçiliyor…') : '');
    retry.hidden = false;
    if (auto) fallTimer = setTimeout(() => { if (!stopped) { stop(); (a.has_pin ? onPin : onPassword)(a); } }, 2600);
  }

  async function newChallenge() {
    const ch = await api.post('/api/auth/face/challenge', { token: a.token });
    challenge = ch.challenge; pose = ch.pose; stage = 'match';
    return ch;
  }

  async function start() {
    stopped = false; retries = 0; retry.hidden = true; clearTimeout(fallTimer);
    globe(true);
    ring.setState('idle'); ring.setSlots([]); ring.setNext(null); ring.setHint('');
    try { await newChallenge(); } catch (err) {
      // 403 politika kapalı, 401 yüz yok / cihaz yok, 429 hız sınırı / kilit, 503 motor yok
      return failTo(err.message || 'Yüz ile giriş kullanılamıyor', { auto: err.status !== 429 });
    }
    ring.setText('Kamera başlatılıyor…');
    try { await openCamera(ring.video); } catch (err) { return failTo(cameraErrorText(err)); }
    if (stopped) return;
    ring.setState('scan');
    ring.setText(DIRECTION_TEXT.center);
    let noFaceSince = 0;
    loop = frameLoop(ring.video, async jpg => {
      if (stopped || !challenge) return;
      let r;
      try { r = await api.post('/api/auth/face/verify', { challenge, jpg }); } catch (err) {
        if (stopped || stage === 'done' || stage === 'pin') return;
        if (err.status === 410 && retries < RETRIES) {   // süre doldu: sessizce yeni meydan okuma
          retries++;
          try { await newChallenge(); ring.setSlots([]); ring.setNext(null); ring.setText(DIRECTION_TEXT.center); return; } catch (e2) { return failTo(e2.message); }
        }
        return failTo(err.message || 'Yüz doğrulanamadı');
      }
      if (stopped || stage === 'done' || stage === 'pin') return;   // bitmiş akışa uçuştaki kare sonucu dokunmasın
      if (!r.found) {
        ring.setLive(null);
        noFaceSince = noFaceSince || Date.now();
        if (Date.now() - noFaceSince > 1200) { ring.noFace(true); ring.setHint(r.small ? 'Biraz yaklaşın' : 'Yüz bulunamadı — kameraya bakın'); }
      } else {
        noFaceSince = 0; ring.noFace(false);
        ring.setLive(r.yaw, r.pitch);
        const fh = stage === 'match' ? framingHint(framing(r.box, 480, 360)) : null;
        ring.setHint(fh || '');
      }
      if (r.matched && r.stage === 'pose') {
        stage = 'pose';
        ring.setSlots(['center']); ring.setNext(r.pose || pose);
        ring.setText(POSE_TEXT[r.pose || pose] || 'Başınızı hafifçe çevirin'); ring.setHint('');
      } else if (r.need_pin) {
        stage = 'pin';
        loop.stop(); loop = null; closeCamera(ring.video);
        ring.celebrate(); ring.setText('Yüz doğrulandı'); ring.setHint('Şimdi PIN kodunuzu girin');
        setTimeout(() => { if (!stopped) showPin(); }, 650);
      } else if (r.done && r.ok) {
        stage = 'done';
        loop.stop(); loop = null; closeCamera(ring.video);
        ring.celebrate(); ring.setText('Hoş geldiniz'); ring.setHint('');
        setTimeout(() => { if (!stopped) { stop(); onLogin(); } }, 750);
      } else if (!r.matched && r.frames_left === 0) {
        failTo('Yüz doğrulanamadı');
      }
    });
  }

  function showPin() {
    // yüz + PIN kipi: PIN klavyesi (accounts.js pinPad) — gönderim POST /api/auth/face/pin
    pinPad(a, async pin => { await api.post('/api/auth/face/pin', { challenge, pin }); stop(); await onLogin(); },
      { title: 'Yüz doğrulandı · PIN kodunuzu girin', onAlt: () => { stop(); onPassword(a); } });
  }

  start();
  return { stop };
}

export { faceIcon, t };
