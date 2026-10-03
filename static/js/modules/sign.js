// İmza talepleri: bana gelenler / gönderdiklerim ve talep ekranı (evrakı gör → İmzala / Reddet / Vazgeç).
// Modül değildir; her kullanıcı yalnızca kendisine gelen ve kendi gönderdiği talepleri görür.
import { api, fileUrl } from '../api.js';
import { clear, fmtDateTime, h, modal, pageHead, segmented, statStrip, t, toast, toastError } from '../ui.js';
import { thumbOf } from './documents.js';

export const SIGN_STATES = {
  BEKLIYOR: ['İmza bekliyor', 'yellow'], IMZALANDI: ['İmzalandı', 'green'], REDDEDILDI: ['Reddedildi', 'red'], IPTAL: ['Geri çekildi', 'gray'],
};
export const signBadge = st => { const [label, color] = SIGN_STATES[st] || [st, 'gray']; return h('span', { class: `badge ${color}` }, label); };
const code = sig => (sig ? sig.slice(0, 32).toUpperCase().match(/.{1,4}/g).join(' ') : '');

export async function render(view, params, ctx) {
  if (params[0]) return renderRequest(view, Number(params[0]), ctx);
  let box = 'inbox';
  const stats = statStrip();
  const body = h('div');
  const load = async () => {
    const [inbox, sent] = await Promise.all([api.get('/api/signatures?box=inbox'), api.get('/api/signatures?box=sent')]);
    const rows = box === 'inbox' ? inbox : sent;
    stats.set([
      { label: 'İmzamı bekleyen', value: inbox.filter(s => s.status === 'BEKLIYOR').length, tone: inbox.some(s => s.status === 'BEKLIYOR') ? 'alert' : '' },
      { label: 'İmzaladığım', value: inbox.filter(s => s.status === 'IMZALANDI').length, tone: 'ok' },
      { label: 'Reddettiğim', value: inbox.filter(s => s.status === 'REDDEDILDI').length },
      { label: 'Gönderdiğim, bekleyen', value: sent.filter(s => s.status === 'BEKLIYOR').length },
      { label: 'Gönderdiğim, reddedilen', value: sent.filter(s => s.status === 'REDDEDILDI').length, tone: sent.some(s => s.status === 'REDDEDILDI') ? 'alert' : '' },
    ]);
    clear(body, rows.length ? h('div', { class: 'doc-list' }, rows.map(s => h('a', { class: 'card doc-row', href: `#/sign/${s.id}` },
      thumbOf(s),
      h('div', { class: 'grow' },
        h('div', { class: 'doc-title' }, h('b', null, s.document_title), ' ', signBadge(s.status)),
        h('div', { class: 'small muted' }, box === 'inbox' ? t('Gönderen: {name} · {date}', { name: s.requested_by_name || '—', date: fmtDateTime(s.requested_at) })
          : t('İmzalayacak: {name} · {date}', { name: s.signer_name || '—', date: fmtDateTime(s.requested_at) })),
        s.message ? h('div', { class: 'doc-snippet' }, s.message) : null,
        s.status === 'REDDEDILDI' && s.reason ? h('div', { class: 'small', style: { color: 'var(--danger)', marginTop: '4px' } }, t('Red gerekçesi: {reason}', { reason: s.reason })) : null),
      h('div', { class: 'doc-side' }, s.decided_at ? fmtDateTime(s.decided_at) : ''))))
      : h('div', { class: 'card empty' }, box === 'inbox' ? 'Size gelen imza talebi yok' : 'Gönderdiğiniz imza talebi yok'));
  };
  clear(view,
    pageHead('İmza Talepleri', { back: '#/', sub: 'Dijital evrak imzalama',
      tabs: segmented([['inbox', 'Bana gelenler'], ['sent', 'Gönderdiklerim']], box, v => { box = v; load().catch(toastError); }) }),
    stats,
    body);
  await load();
}

export function signatureBlock(s) {
  // İmzalanmış talebin dijital imza bilgisi + doğrulama
  const result = h('span');
  const check = async () => {
    try {
      const v = await api.get(`/api/signatures/${s.id}/verify`);
      clear(result, v.valid ? h('span', { class: 'badge green' }, '✓ İmza geçerli, evrak değişmemiş')
        : h('span', { class: 'badge red' }, v.file_unchanged ? '✗ İmza kaydı geçersiz' : '✗ Evrak imzadan sonra değişmiş'));
    } catch (err) { toastError(err); }
  };
  return h('div', { class: 'sign-block' },
    h('div', null, h('b', null, t('Dijital olarak imzalandı: {name}', { name: s.signer_name })), ` · ${fmtDateTime(s.decided_at)}`),
    h('div', { class: 'small mono' }, t('İmza kodu: {code}', { code: code(s.signature) })),
    h('div', { class: 'small mono muted' }, t('Evrak özeti (SHA-256): {hash}', { hash: s.file_sha256 })),
    h('div', { style: { marginTop: '6px', display: 'flex', gap: '8px', alignItems: 'center' } },
      h('button', { class: 'btn sm', type: 'button', onclick: check }, 'İmzayı doğrula'), result));
}

async function renderRequest(view, sid, ctx) {
  const s = await api.get(`/api/signatures/${sid}`);
  const url = fileUrl(s.file);
  const ext = s.file_name.split('.').pop().toLowerCase();
  const preview = s.kind === 'VIDEO' ? h('video', { src: url, controls: true, playsinline: true, class: 'doc-preview' })
    : s.kind === 'RESIM' && !['heic', 'heif'].includes(ext) ? h('img', { src: fileUrl(s.file, 1600), class: 'doc-preview', alt: s.document_title })
      : ext === 'pdf' ? h('iframe', { src: url, class: 'doc-preview pdf', title: s.document_title })
        : h('div', { class: 'doc-preview none' }, thumbOf(s, 'doc-thumb big'), h('a', { class: 'btn primary', href: url, download: s.file_name }, 'Dosyayı İndir'));
  const back = () => { if (history.length > 1) history.back(); else location.hash = '#/sign'; };
  const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));
  const sign = async () => {
    try { await api.post(`/api/signatures/${sid}/sign`); toast('Evrak dijital olarak imzalandı'); reload(); } catch (err) { toastError(err); }
  };
  const reject = () => {
    const reason = h('textarea', { class: 'input', rows: 3, placeholder: 'Neden reddettiğinizi yazın' });
    modal({
      title: 'İmza talebini reddet',
      body: h('div', null, h('p', { style: { marginTop: 0 } }, t('{title} evrakını imzalamayı reddediyorsunuz.', { title: s.document_title })), reason),
      actions: [{ label: 'Vazgeç' }, {
        label: 'Reddet', class: 'danger', onClick: async () => {
          if (!reason.value.trim()) throw new Error('Red açıklaması zorunlu');
          await api.post(`/api/signatures/${sid}/reject`, { reason: reason.value.trim() });
          toast('İmza talebi reddedildi');
          reload();
        },
      }],
    });
  };
  const cancel = async () => {
    try { await api.post(`/api/signatures/${sid}/cancel`); toast('İmza talebi geri çekildi'); reload(); } catch (err) { toastError(err); }
  };
  const kv = (k, v) => [h('dt', null, k), h('dd', null, v)];
  clear(view,
    pageHead(s.document_title, { back: '#/sign', sub: t('İmza talebi · {file}', { file: s.file_name }) }),
    h('div', { class: 'doc-layout' },
      h('div', { class: 'card doc-stage' }, preview),
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: '16px' } },
        h('div', { class: 'card card-pad' },
          h('div', { style: { marginBottom: '10px' } }, signBadge(s.status)),
          h('dl', { class: 'kv' },
            kv('Gönderen', `${s.requested_by_name || '—'} · ${fmtDateTime(s.requested_at)}`),
            kv('İmzalayacak', s.signer_name || '—'),
            s.message ? kv('Mesaj', s.message) : null,
            s.status === 'REDDEDILDI' ? kv('Red gerekçesi', h('span', { style: { color: 'var(--danger)' } }, s.reason || '—')) : null,
            s.decided_at && s.status !== 'IMZALANDI' ? kv('Sonuç zamanı', fmtDateTime(s.decided_at)) : null),
          s.status === 'IMZALANDI' ? signatureBlock(s) : null,
          s.can_decide ? h('div', { class: 'sign-actions' },
            h('button', { class: 'btn success lg', onclick: sign }, '✍ İmzala'),
            h('button', { class: 'btn danger lg', onclick: reject }, 'Reddet'),
            h('button', { class: 'btn lg', onclick: back }, 'Vazgeç')) : null,
          s.can_cancel ? h('div', { class: 'sign-actions' }, h('button', { class: 'btn', onclick: cancel }, 'Talebi geri çek')) : null),
        s.others.length ? h('div', { class: 'card card-pad' },
          h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Bu evraktaki diğer imzalar'),
          h('ul', { class: 'stat-list' }, s.others.map(o => h('li', null, h('span', null, o.signer_name), signBadge(o.status))))) : null)));
}
