// Araçlar › Master Tool web sürümleri — ortak arayüz parçaları (masaüstü Master Tool dili: koyu kabuk, kapsül düğmeler).
// SSH/FTP/SQL/Notepad/Convert/VOLFAI alt modülleri bu yardımcıları kullanır.
import { ApiError } from '../api.js';
import { h, t } from '../ui.js';

export { t };

// Kapsül düğme
export const btn = (label, { cls = '', onclick, disabled = false, title } = {}, ...kids) =>
  h('button', { class: `mt-btn ${cls}`.trim(), type: 'button', onclick, disabled, title }, ...kids, label);

// Kapsül giriş kutusu (placeholder otomatik çevrilir)
export const inp = ({ cls = '', ...attrs } = {}) => h('input', { class: `mt-input ${cls}`.trim(), ...attrs });

// Açılır liste: options = [[değer, etiket, devreDışı?]]
export const sel = (options, value, attrs = {}) => h('select', { class: 'mt-select', ...attrs },
  options.map(([k, l, dis]) => h('option', { value: k, selected: String(k) === String(value), disabled: !!dis }, l)));

export const lab = (label, control) => h('label', null, label, control);

// Koyu kabuk: pageHead'in altında tüm alt modül içeriği bu kabukta
export const shell = (...kids) => h('div', { class: 'mt' }, h('div', { class: 'mt-shell' }, ...kids));

export const status = (text = '', tone = '') => h('span', { class: `mt-status ${tone}`.trim() }, text);
export function setStatus(el, text, tone = '') { el.textContent = t(text); el.className = `mt-status ${tone}`.trim(); }

export function fmtBytes(n) {
  if (n == null || n === '') return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

// Ham yükleme (XHR, ilerleme ile). api.upload görselleri sıkıştırır; dönüştürme/FTP için dosya AYNEN gitmeli.
export function uploadRaw(url, fd, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress?.(Math.round(e.loaded * 100 / e.total)); };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* boş */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
      if (xhr.status === 401) window.dispatchEvent(new Event('caymaz:unauthorized'));
      reject(new ApiError(xhr.status, (data && typeof data.detail === 'string' && data.detail) || `Yükleme başarısız (${xhr.status})`));
    };
    xhr.onerror = () => reject(new ApiError(0, 'Bağlantı hatası, yükleme tamamlanamadı'));
    xhr.send(fd);
  });
}

// İndirme bağlantısını tetikle (aynı kökten; oturum çerezi tarayıcıda)
export function download(url, name) {
  const a = h('a', { href: url, download: name || '' });
  document.body.append(a); a.click(); a.remove();
}

export function downloadText(text, name, mime = 'text/plain') {
  const u = URL.createObjectURL(new Blob([text], { type: mime }));
  download(u, name);
  setTimeout(() => URL.revokeObjectURL(u), 5000);
}

// Dış betik (xterm, SheetJS) tek seferlik yükleyici
const scripts = {};
export function loadScript(src) {
  return scripts[src] ??= new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = src; s.onload = () => res(); s.onerror = () => { delete scripts[src]; rej(new Error('Bileşen yüklenemedi: ' + src)); };
    document.head.append(s);
  });
}
export function loadCss(href, mark) {
  if (document.querySelector(`link[data-${mark}]`)) return;
  const css = document.createElement('link');
  css.rel = 'stylesheet'; css.href = href; css.setAttribute(`data-${mark}`, '1');
  document.head.append(css);
}

// Sürükle-bırak alanı: onFiles(FileList)
export function dropZone(text, onFiles, { multiple = true, accept = '' } = {}) {
  const file = h('input', { type: 'file', multiple, accept, style: { display: 'none' }, onchange: () => { if (file.files.length) onFiles([...file.files]); file.value = ''; } });
  const z = h('div', { class: 'mt-drop', onclick: () => file.click(),
    ondragover: e => { e.preventDefault(); z.classList.add('over'); },
    ondragleave: () => z.classList.remove('over'),
    ondrop: e => { e.preventDefault(); z.classList.remove('over'); if (e.dataTransfer.files.length) onFiles([...e.dataTransfer.files]); } },
  text, file);
  return z;
}

export function progress() {
  const bar = h('i');
  const el = h('div', { class: 'mt-prog', style: { display: 'none' } }, bar);
  el.set = pct => { el.style.display = ''; bar.style.width = `${pct}%`; };
  el.done = () => { el.style.display = 'none'; bar.style.width = '0'; };
  return el;
}

// Bağlantı profilleri (yalnız tarayıcı localStorage; PAROLA SAKLANMAZ)
export function profiles(key) {
  const read = () => { try { return JSON.parse(localStorage.getItem(key) || '[]'); } catch { return []; } };
  const write = list => { try { localStorage.setItem(key, JSON.stringify(list.slice(0, 50))); } catch { /* */ } };
  return {
    list: read,
    save(p) { const { password, key: _k, ...safe } = p; const l = read().filter(x => x.name !== safe.name); l.unshift(safe); write(l); },   // eslint-disable-line no-unused-vars
    remove(name) { write(read().filter(x => x.name !== name)); },
  };
}
