// Sunucu API sarmalayıcısı. Hata mesajları sunucudan Türkçe gelir.
export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function request(method, url, body) {
  const opts = { method, headers: {}, credentials: 'same-origin' };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = 'Eksik veya hatalı bilgi girildi';
    const err = new ApiError(res.status, msg || `İstek başarısız (${res.status})`);
    if (res.status === 401 && !url.endsWith('/auth/login')) window.dispatchEvent(new Event('caymaz:unauthorized'));
    throw err;
  }
  return data;
}

export const api = {
  get: url => request('GET', url),
  post: (url, body) => request('POST', url, body ?? {}),
  put: (url, body) => request('PUT', url, body),
  del: url => request('DELETE', url),
};

// Büyük dosyalar için ilerleme bildiren yükleme (fetch yükleme ilerlemesi vermez).
export function upload(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress?.(Math.round(e.loaded * 100 / e.total)); };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* boş yanıt */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
      if (xhr.status === 401) window.dispatchEvent(new Event('caymaz:unauthorized'));
      reject(new ApiError(xhr.status, (data && typeof data.detail === 'string' && data.detail) || `Yükleme başarısız (${xhr.status})`));
    };
    xhr.onerror = () => reject(new ApiError(0, 'Bağlantı hatası, yükleme tamamlanamadı'));
    xhr.send(formData);
  });
}

// w verilirse sunucu resmi o genişliğe küçültüp gönderir (liste, kart, avatar); aslı için w verilmez
export const fileUrl = (path, w) => (path ? `/api/files/${path}${w ? `?w=${w}` : ''}` : null);

// Hareket kaydı (sayfa girişi/çıkışı, yazdırma vb.). beacon: sekme kapanırken de gönderilir.
export function logActivity(events, { beacon = false } = {}) {
  const body = JSON.stringify([].concat(events));
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon('/api/activity', new Blob([body], { type: 'text/plain' }));
    return;
  }
  return fetch('/api/activity', { method: 'POST', credentials: 'same-origin', keepalive: true,
    headers: { 'Content-Type': 'application/json' }, body }).catch(() => {});
}

// Dosyayı parçalar halinde sırayla gönderir (bağlantı koparsa parça yeniden denenir). signal ile iptal edilebilir.
async function sendChunks(file, chunkUrl, size, onProgress, signal) {
  let offset = 0;
  while (offset < file.size) {
    const blob = file.slice(offset, offset + size);
    let tries = 0;
    for (;;) {
      if (signal?.aborted) throw new DOMException('İptal', 'AbortError');
      try {
        const res = await fetch(`${chunkUrl}?offset=${offset}`, {
          method: 'PUT', credentials: 'same-origin', body: blob, signal, headers: { 'Content-Type': 'application/octet-stream' } });
        if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail || `Yükleme hatası (${res.status})`);
        break;
      } catch (err) {
        if (err.name === 'AbortError') throw err;
        if (++tries >= 3 || (err instanceof ApiError && err.status < 500 && err.status !== 0)) throw err;
        await new Promise(r => setTimeout(r, 1500 * tries));   // bağlantı kopmasına karşı yeniden dene
      }
    }
    offset += blob.size;
    onProgress?.(Math.round(offset * 100 / file.size));
  }
}

// İptal edilen yüklemenin yarım dosyası sunucudan silinir; çağırana "iptal edildi" hatası döner
export class UploadCanceled extends Error {
  constructor() { super('Yükleme iptal edildi'); this.canceled = true; }
}
async function withCancel(cleanupUrl, fn) {
  try {
    return await fn();
  } catch (err) {
    if (err.name !== 'AbortError') throw err;
    fetch(cleanupUrl, { method: 'DELETE', credentials: 'same-origin' }).catch(() => {});
    throw new UploadCanceled();
  }
}

// Uçuş videoları: saha modülünün kendi parça parça yükleme uçları
export async function uploadChunked(file, initUrl, onProgress, signal) {
  const { upload_id: id, chunk_size: size } = await request('POST', initUrl, { file_name: file.name, size: file.size });
  await withCancel(`/api/field/uploads/${id}`, () => sendChunks(file, `/api/field/uploads/${id}`, size, onProgress, signal));
  return request('POST', `/api/field/uploads/${id}/complete`);
}

// Büyük dosya (ör. uçuş logu): /api/uploads ile parça parça yüklenir; dönen jeton dosyayı kullanan uca verilir
export async function uploadLarge(file, kind, onProgress, signal) {
  const { upload_id: id, chunk_size: size } = await request('POST', '/api/uploads', { kind, file_name: file.name, size: file.size });
  await withCancel(`/api/uploads/${id}`, () => sendChunks(file, `/api/uploads/${id}`, size, onProgress, signal));
  return id;
}
