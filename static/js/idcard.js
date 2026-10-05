// Personel kimlik kartı (yaka kartı) şablonu: mavi çerçeve, sol fotoğraf, üstte barkod (sicil / PDKS kart no),
// Kişi Güvenlik Kodu, e-posta, telefon, altta ad-görev ve kurum logoları. Hem personel detayında hem kart/yazdırma ekranında kullanılır.
import { fileUrl } from './api.js';
import { h } from './ui.js';
import { getLang } from './i18n.js';

// ---- Code128-B barkod → SVG (harici kütüphane yok). Değer boşsa null döner.
const C128 = [
  '11011001100', '11001101100', '11001100110', '10010011000', '10010001100', '10001001100', '10011001000', '10011000100',
  '10001100100', '11001001000', '11001000100', '11000100100', '10110011100', '10011011100', '10011001110', '10111001100',
  '10011101100', '10011100110', '11001110010', '11001011100', '11001001110', '11011100100', '11001110100', '11101101110',
  '11101001100', '11100101100', '11100100110', '11101100100', '11100110100', '11100110010', '11011011000', '11011000110',
  '11000110110', '10100011000', '10001011000', '10001000110', '10110001000', '10001101000', '10001100010', '11010001000',
  '11000101000', '11000100010', '10110111000', '10110001110', '10001101110', '10111011000', '10111000110', '10001110110',
  '11101110110', '11010001110', '11000101110', '11011101000', '11011100010', '11011101110', '11101011000', '11101000110',
  '11100010110', '11101101000', '11101100010', '11100011010', '11101111010', '11001000010', '11110001010', '10100110000',
  '10100001100', '10010110000', '10010000110', '10000101100', '10000100110', '10110010000', '10110000100', '10011010000',
  '10011000010', '10000110100', '10000110010', '11000010010', '11001010000', '11110111010', '11000010100', '10001111010',
  '10100111100', '10010111100', '10010011110', '10111100100', '10011110100', '10011110010', '11110100100', '11110010100',
  '11110010010', '11011011110', '11011110110', '11110110110', '10101111000', '10100011110', '10001011110', '10111101000',
  '10111100010', '11110101000', '11110100010', '10111011110', '10111101110', '11101011110', '11110101110', '11010000100',
  '11010010000', '11010011100', '11000111010',
];

function barcodeSvg(text, { h: height = 54, unit = 1.7 } = {}) {
  const s = String(text).replace(/[^\x20-\x7e]/g, '');   // Code128-B: basılabilir ASCII
  if (!s) return null;
  const codes = [104];   // Start B
  let sum = 104;
  for (let i = 0; i < s.length; i++) { const v = s.charCodeAt(i) - 32; codes.push(v); sum += v * (i + 1); }
  codes.push(sum % 103);   // kontrol
  codes.push(106);         // Stop
  const bits = codes.map(c => C128[c]).join('') + '11';   // bitiş çubuğu
  const w = bits.length * unit;
  let x = 0, rects = '';
  for (let i = 0; i < bits.length;) {
    let j = i; while (j < bits.length && bits[j] === bits[i]) j++;
    const run = j - i;
    if (bits[i] === '1') rects += `<rect x="${(x).toFixed(2)}" y="0" width="${(run * unit).toFixed(2)}" height="${height}" fill="#111"/>`;
    x += run * unit; i = j;
  }
  return `<svg viewBox="0 0 ${w.toFixed(1)} ${height}" preserveAspectRatio="none" class="idc-barcode" role="img" aria-label="barkod ${s}">${rects}</svg>`;
}

const svgWrap = markup => { const t = document.createElement('template'); t.innerHTML = markup; return t.content.firstElementChild; };

// Resmî "MKE İŞTİRAKİDİR" logosu: sunucuya yüklenen görsel. Arayüz Türkçe ise mke_tr, diğer dillerde mke_en.
function mkeLogo() {
  const file = getLang() === 'tr' ? 'mke_tr' : 'mke_en';
  return h('img', { class: 'idc-mke-img', src: `/static/img/${file}.png`, alt: 'MKE İŞTİRAKİDİR' });
}

/** idCard(e, {company, action}) → kimlik kartı DOM'u. action verilirse kartın içinde, alt çizginin hemen üstünde ortada gösterilir (yazdırmada verilmez). */
export function idCard(e, { company, action } = {}) {
  const name = `${e.first_name || ''} ${e.last_name || ''}`.trim().toLocaleUpperCase('tr');
  const title = (e.title || e.emp_title || '').toLocaleUpperCase('tr');
  const email = e.email || (e.username && /@/.test(e.username) ? e.username : '') || '';
  const phone = e.phone || '';
  const code = e.security_code || null;
  const barValue = e.card_no || e.tc_no || (e.id ? `P${e.id}` : '');
  const photo = e.photo_file ? fileUrl(e.photo_file, 400) : e.user_photo ? fileUrl(e.user_photo, 400) : null;
  const bar = barcodeSvg(barValue);
  const row = (label, value, cls) => h('div', { class: 'idc-row' }, h('span', { class: 'idc-label' }, label),
    h('div', { class: `idc-value ${cls || ''}` }, value || h('span', { class: 'idc-empty' }, '—')));
  return h('div', { class: 'idc' },
    h('div', { class: 'idc-head' }, (company || 'GÖKKUBBE TEKNOLOJİ ANONİM ŞİRKETİ').toLocaleUpperCase('tr')),
    h('div', { class: 'idc-body' },
      h('div', { class: 'idc-left' },
        h('div', { class: 'idc-photo' }, photo ? h('img', { src: photo, alt: '' }) : h('span', { class: 'idc-noimg' }, name.slice(0, 1) || '?')),
        h('div', { class: 'idc-name' }, name || '—'),
        title ? h('div', { class: 'idc-title' }, title) : null),
      h('div', { class: 'idc-right' },
        bar ? h('div', { class: 'idc-bar' }, svgWrap(bar), h('span', { class: 'idc-barnum' }, barValue)) : h('div', { class: 'idc-bar idc-bar-empty' }, 'Kart / sicil no yok'),
        row('Kişi Güvenlik Kodu', code, code ? 'mono' : 'idc-dashed'),
        row('E-Mail', email, 'idc-link'),
        row('Telefon Numarası', phone))),
    action ? h('div', { class: 'idc-action' }, action) : null,
    h('div', { class: 'idc-foot' },
      h('div', { class: 'idc-mke' }, mkeLogo()),
      h('img', { class: 'idc-logo', src: '/static/img/logo.png', alt: 'Gökkubbe' })));
}

export { barcodeSvg };
