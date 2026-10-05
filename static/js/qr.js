// QR üretimi: vendor/qrcode klasik script olarak tembel yüklenir (offline).
// qrSvg() SVG metni döndürür; qrSvgEl() çağıran senkron ekleyebilsin diye sonradan dolan <span> verir.
let _qrLib = null;
export function ensureQrLib() {
  return _qrLib ??= new Promise((resolve, reject) => {
    if (window.qrcode) return resolve(window.qrcode);
    const s = document.createElement('script');
    s.src = '/static/vendor/qrcode/qrcode.js';
    s.onload = () => (window.qrcode ? resolve(window.qrcode) : reject(new Error('QR bileşeni yüklenemedi')));
    s.onerror = () => { _qrLib = null; reject(new Error('QR bileşeni yüklenemedi')); };
    document.head.append(s);
  });
}

// Verilen metin için SVG string (yazdırma şablonuna gömmek / senkron kullanmak için).
export async function qrSvg(text, { cell = 4, margin = 2 } = {}) {
  const qrcode = await ensureQrLib();
  const qr = qrcode(0, 'M');   // typeNumber 0 = otomatik boyut, 'M' = orta hata düzeltme
  qr.addData(String(text ?? ''));
  qr.make();
  return qr.createSvgTag({ cellSize: cell, margin });
}

// Ekranda göstermek için: çağıran hemen ekler, QR sonradan (asenkron) içine dolar.
export function qrSvgEl(text, opts) {
  const span = document.createElement('span');
  span.className = 'qr-svg';
  qrSvg(text, opts)
    .then(svg => { span.innerHTML = svg; })
    .catch(() => { span.textContent = 'QR oluşturulamadı'; });
  return span;
}
