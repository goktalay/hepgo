// Beta geri bildirim: footer'daki ortadaki "Beta" düğmesi. Kullanıcı hata/tavsiye/diğer bildirir
// (opsiyonel ekran görüntüsüyle), geçmiş bildirimlerini ve merkez cevaplarını görür.
import { api } from '../api.js';
import { clear, h, modal, toast, toastError } from '../ui.js';

const CATS = [['hata', '🐞 Hata'], ['tavsiye', '💡 Tavsiye'], ['diger', '💬 Diğer']];
const CAT_LBL = Object.fromEntries(CATS.map(c => c));
const ST = { NEW: 'Gönderildi', SENT: 'İletildi', ANSWERED: 'Cevaplandı' };

// Footer'ın ortasına konan düğme
export function betaButton(ctx) {
  return h('button', { class: 'beta-fab', type: 'button', title: 'Beta geri bildirim', onclick: () => openBeta(ctx) },
    h('span', { class: 'beta-dot' }), 'Beta');
}

export function openBeta(ctx) {
  let tab = 'new';
  const bodyWrap = h('div', { class: 'beta-modal' });
  const m = modal({ title: 'Beta Geri Bildirim', wide: true, body: bodyWrap });
  const tabs = h('div', { class: 'beta-tabs' },
    h('button', { class: 'beta-tab on', type: 'button', 'data-t': 'new' }, 'Yeni bildirim'),
    h('button', { class: 'beta-tab', type: 'button', 'data-t': 'mine' }, 'Bildirimlerim'));
  tabs.querySelectorAll('.beta-tab').forEach(b => b.addEventListener('click', () => {
    tab = b.dataset.t; tabs.querySelectorAll('.beta-tab').forEach(x => x.classList.toggle('on', x === b));
    draw();
  }));
  const pane = h('div', { class: 'beta-pane' });
  bodyWrap.append(
    h('p', { class: 'beta-intro' }, 'HEPGO beta aşamasındadır. Karşılaştığınız hataları veya önerilerinizi bize iletin; merkez ekibi yanıtlar. ',
      h('a', { href: '/beta-sozlesmesi', target: '_blank', rel: 'noopener' }, 'Beta Programı Sözleşmesi')),
    tabs, pane);
  draw();

  function draw() { tab === 'new' ? drawNew() : drawMine(); }

  function drawNew() {
    let cat = 'hata', shot = '';
    const catRow = h('div', { class: 'beta-cats' }, CATS.map(([k, lbl]) =>
      h('button', { type: 'button', class: 'beta-cat' + (k === cat ? ' on' : ''), 'data-c': k,
        onclick: e => { cat = k; catRow.querySelectorAll('.beta-cat').forEach(x => x.classList.toggle('on', x === e.currentTarget)); } }, lbl)));
    const msg = h('textarea', { class: 'input beta-msg', rows: '5', placeholder: 'Ne oldu? Ne öneriyorsunuz? Mümkünse adım adım yazın.' });
    const shotInfo = h('span', { class: 'muted small' }, 'Ekran görüntüsü yok');
    const shotInput = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', hidden: true });
    shotInput.addEventListener('change', () => {
      const f = shotInput.files[0]; if (!f) return;
      if (f.size > 4 * 1024 * 1024) { toastError('Görüntü 4MB’tan küçük olmalı'); shotInput.value = ''; return; }
      const r = new FileReader(); r.onload = () => { shot = r.result; shotInfo.textContent = '✓ ' + f.name; }; r.readAsDataURL(f);
    });
    const send = h('button', { class: 'btn primary', type: 'button' }, 'Gönder');
    send.onclick = async () => {
      if (!msg.value.trim()) { toastError('Lütfen bir mesaj yazın'); return; }
      send.disabled = true; send.textContent = 'Gönderiliyor…';
      try {
        await api.post('/api/beta/feedback', { category: cat, message: msg.value.trim(), screenshot: shot, page: location.hash || '' });
        toast('Teşekkürler! Bildiriminiz iletildi.');
        tab = 'mine'; tabs.querySelectorAll('.beta-tab').forEach(x => x.classList.toggle('on', x.dataset.t === 'mine')); draw();
      } catch (e) { toastError(e); send.disabled = false; send.textContent = 'Gönder'; }
    };
    clear(pane,
      h('div', { class: 'beta-field' }, h('label', null, 'Konu'), catRow),
      h('div', { class: 'beta-field' }, h('label', null, 'Mesaj'), msg),
      h('div', { class: 'beta-field beta-shot' },
        h('button', { class: 'btn sm', type: 'button', onclick: () => shotInput.click() }, '📷 Ekran görüntüsü ekle'), shotInfo, shotInput),
      h('div', { class: 'beta-foot' }, send));
  }

  async function drawMine() {
    clear(pane, h('div', { class: 'loading' }, 'Yükleniyor…'));
    let list;
    try { list = await api.get('/api/beta/feedback'); } catch (e) { clear(pane, h('div', { class: 'empty' }, e.message)); return; }
    clear(pane);
    if (!list.length) { pane.append(h('div', { class: 'empty' }, 'Henüz bildiriminiz yok.')); return; }
    list.forEach(f => pane.append(h('div', { class: 'beta-item' },
      h('div', { class: 'beta-item-h' },
        h('span', { class: 'chip' }, CAT_LBL[f.category] || f.category),
        f.user_name ? h('span', { class: 'muted small' }, f.user_name) : null,
        h('span', { class: 'spacer' }),
        h('span', { class: 'chip ' + (f.status === 'ANSWERED' ? 'ok' : 'light') }, ST[f.status] || f.status)),
      h('div', { class: 'beta-item-msg' }, f.message),
      f.reply ? h('div', { class: 'beta-reply' }, h('b', null, 'Merkez cevabı: '), f.reply) : null)));
  }
}
