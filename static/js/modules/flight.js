// Uçuş detayı (#/field/flight/<id>[/<sekme>]): saha görevindeki uçağa tıklayınca açılır.
// Üstte uçak ve saha görevi bilgileri, uçuş logu (.bin) yükleme; altta sekmeler: Uçuş Raporu, 3B Uçuş İzleme,
// Uçuş Notları (türüyle birden çok not), Video ve Resimler (birden çok dosya).
import { api, fileUrl, uploadChunked, uploadLarge } from '../api.js';
import { buildFlightReport, printFlightReport } from '../flightreport.js';
import { icons } from '../icons.js';
import { ORDER_STATES, TASK_STATES, USAGE_TYPES, badge, queuePlate } from '../status.js';
import {
  clear, confirmDialog, every, field, fmtDateTime, h, localUploadNotice, modal, pageHead, svgIcon, t as tr, toast, toastError,
  uploadPanel,
} from '../ui.js';
import { tabView } from './crm.js';
import { aircraftReviewModal } from './mrp.js';
import { render3D } from './replay3d.js';
import { logBadge } from './tools.js';

const LAUNCH = { ARAC_USTU: 'Araç Üstü', RAMPA: 'Fırlatma Rampası' };
const NOTE_COLORS = { GORUS: 'blue', IYILESTIRME: 'purple', ARIZA: 'red', GOZLEM: 'green', DIGER: 'gray' };
const VIDEO_EXT = /\.(mp4|mov|m4v|webm|mkv|avi|3gp|ts)$/i;
const clock = s => { s = Math.round(s || 0); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };

export async function renderFlight(view, id, ctx, tab) {
  const d = await api.get(`/api/field/flights/${id}`);
  const { flight: f, order: o, task: t, log } = d;
  const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));
  const kv = (k, v) => (v || v === 0 ? [h('dt', null, k), h('dd', null, v)] : null);

  // ---- Uçuş logu yükleme (.bin / .log; yalnızca yerel ağdan)
  const logCard = () => {
    const input = h('input', { class: 'input', type: 'file', accept: '.bin,.BIN,.log,.LOG', style: { height: 'auto', padding: '6px' } });
    const progress = uploadPanel();
    const send = h('button', { class: 'btn primary', type: 'button' }, svgIcon(icons.upload), log ? 'Yeni Log Yükle' : 'Logu Yükle');
    send.addEventListener('click', async () => {
      const file = input.files?.[0];
      if (!file) { toastError(new Error('Önce .bin dosyasını seçin')); return; }
      send.disabled = true;
      try {
        const signal = progress.start();
        const uploadId = await uploadLarge(file, 'flightlogs', pct => progress.set(tr('{name} yükleniyor…', { name: file.name }), pct), signal);
        progress.done();
        await api.post(`/api/field/flights/${id}/flight-log/chunked`, { upload_id: uploadId });
        toast('Log yüklendi, analiz ediliyor');
        reload();
      } catch (err) {
        progress.done();
        if (err.canceled) toast('Yükleme iptal edildi'); else toastError(err);
      } finally { send.disabled = false; }
    });
    return h('div', { class: 'card card-pad fl-log' },
      h('div', { class: 'fl-log-head' },
        h('h2', null, 'Uçuş logu'),
        log ? logBadge(log.status) : h('span', { class: 'badge gray' }, 'Yüklenmedi'),
        log ? h('span', { class: 'small muted' }, `${log.file_name} · ${fmtDateTime(log.uploaded_at)}`) : null),
      log?.status === 'HATA' ? h('div', { class: 'alert err' }, log.error || 'Log analiz edilemedi') : null,
      log?.status === 'ISLENIYOR' ? h('div', { class: 'small muted' }, 'Log analiz ediliyor; hazır olunca sayfa yenilenir.') : null,
      d.can.upload ? (ctx.meta.remote ? localUploadNotice(ctx.meta, 'Uçuş logu')
        : h('div', { class: 'fl-log-up' }, input, send, progress,
          h('div', { class: 'small muted' }, log ? 'Yeni log yüklerseniz rapor ve 3B izleme yeniden oluşturulur. En fazla 2 GB.'
            : 'ArduPilot .bin (ya da .log) dosyasını seçin. Yüklenince uçuş raporu ve 3B izleme hazırlanır.')))
        : h('div', { class: 'small muted' }, t.status === 'BASLANGIC' ? 'Log, görev başladıktan sonra yüklenebilir.'
          : 'Log yükleme yetkisi saha sorumlusu ve pilottadır.'));
  };

  // ---- Hurda: tek kullanımlık uçak uçunca (log havada kalma gösterince otomatik; log yoksa saha sorumlusu işaretler)
  const scrapActions = () => {
    if (!d.can.manage || o.usage_type !== 'TEK') return null;
    if (o.status === 'TAMAMLANDI') {
      return h('div', { class: 'fl-scrap' }, h('button', { class: 'btn sm danger', onclick: async () => {
        if (!await confirmDialog('Uçtu — hurdaya ayır', tr('{id} tek kullanımlık; uçtuğu için hurdaya ayrılsın mı? Bir daha sahaya gidemez.', { id: o.queue_no || o.code }),
          { okLabel: 'Hurdaya Ayır', danger: true })) return;
        try {
          await api.post(`/api/field/flights/${id}/scrap`);
          toast('Uçak hurdaya ayrıldı');
          await aircraftReviewModal(o.id, reload);   // içindeki malzemeler: hurda mı, sağlam mı?
        } catch (err) { toastError(err); }
      } }, 'Uçtu — Hurdaya Ayır'), h('span', { class: 'small muted' }, 'Uçuş logu havada kalma gösterirse otomatik yapılır.'));
    }
    if (o.status === 'HURDA') {
      return h('div', { class: 'fl-scrap' }, o.material_pending ? h('button', { class: 'btn sm danger', onclick: () => aircraftReviewModal(o.id, reload).catch(toastError) },
        'Malzemeleri Değerlendir') : null, h('button', { class: 'btn sm', onclick: async () => {
        if (!await confirmDialog('Hurdadan geri al', tr('{id} yeniden saha deposuna alınsın mı?', { id: o.queue_no || o.code }), { okLabel: 'Geri Al' })) return;
        try { await api.post(`/api/field/flights/${id}/unscrap`); toast('Uçak saha deposuna geri alındı'); reload(); } catch (err) { toastError(err); }
      } }, 'Hurdadan Geri Al'));
    }
    return null;
  };

  // ---- Sekmeler
  const needLog = what => h('div', { class: 'empty' }, log?.status === 'ISLENIYOR' ? 'Log analiz ediliyor…'
    : log?.status === 'HATA' ? 'Log analiz edilemedi; yeni log yükleyin.' : tr('{what} için önce uçuş logunu (.bin) yükleyin.', { what }));
  const report = async () => {
    if (log?.status !== 'TAMAM') return needLog('Uçuş raporu');
    const full = await api.get(`/api/flight-logs/${log.id}`);
    return h('div', null,
      h('div', { class: 'fl-tab-bar' }, h('span', { class: 'grow' }),
        h('button', { class: 'btn primary', onclick: () => printFlightReport(full, ctx.meta.company) }, 'Yazdır / PDF')),
      h('div', { class: 'fr-doc' }, buildFlightReport(full, ctx.meta.company)));
  };
  const replay = () => {
    if (log?.status !== 'TAMAM') return needLog('3B uçuş izleme');
    const box = h('div', { class: 'fl-3d' });
    setTimeout(() => render3D(box, log.id, null, { embed: true }));   // kutu sayfaya eklendikten sonra
    return box;
  };

  const notes = () => {
    const wrap = h('div', { class: 'fl-notes' });
    let list = d.notes;
    const kindSel = h('select', { class: 'input fl-kind' }, Object.entries(d.note_kinds).map(([k, label]) => h('option', { value: k }, label)));
    const text = h('textarea', { class: 'input', rows: 3, placeholder: 'Uçuş hakkında görüş, iyileştirme talebi, gözlem…' });
    const add = h('button', { class: 'btn primary', type: 'button' }, svgIcon(icons.plus), 'Not Ekle');
    const listBox = h('div', { class: 'note-list' });
    const draw = () => clear(listBox, list.length ? list.map(n => {
      const mine = n.created_by === ctx.user.id || d.can.manage;
      const edit = () => {
        const k = h('select', { class: 'input' }, Object.entries(d.note_kinds).map(([key, label]) => h('option', { value: key, selected: key === n.kind }, label)));
        const b = h('textarea', { class: 'input', rows: 4 }, n.body);
        modal({ title: 'Uçuş notunu düzenle', body: h('div', null, field('Tür', k), field('Not', b)),
          actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
            list = (await api.put(`/api/field/flight-notes/${n.id}`, { kind: k.value, body: b.value })).notes; draw(); toast('Not güncellendi');
          } }] });
      };
      const del = async () => {
        if (!await confirmDialog('Notu sil', 'Bu uçuş notu silinsin mi?', { okLabel: 'Sil', danger: true })) return;
        try { list = (await api.del(`/api/field/flight-notes/${n.id}`)).notes; draw(); toast('Not silindi'); } catch (err) { toastError(err); }
      };
      return h('div', { class: `note-item fl-note ${n.kind.toLowerCase()}` },
        h('div', { class: 'note-meta' }, h('span', { class: `badge ${NOTE_COLORS[n.kind] || 'gray'}` }, d.note_kinds[n.kind] || n.kind),
          h('b', null, n.created_by_name || '—'), ` · ${fmtDateTime(n.created_at)}`,
          n.updated_at ? h('span', { class: 'muted' }, ' · düzenlendi') : null, h('span', { class: 'grow' }),
          mine ? h('button', { class: 'btn sm ghost', onclick: edit }, 'Düzenle') : null,
          mine ? h('button', { class: 'btn sm ghost', onclick: del }, 'Sil') : null),
        h('div', { class: 'note-body' }, n.body));
    }) : h('div', { class: 'empty small' }, 'Henüz uçuş notu yok'));
    add.addEventListener('click', async () => {
      if (!text.value.trim()) { toastError(new Error('Not boş olamaz')); return; }
      add.disabled = true;
      try {
        list = (await api.post(`/api/field/flights/${id}/notes`, { kind: kindSel.value, body: text.value })).notes;
        text.value = '';
        draw();
        toast('Uçuş notu eklendi');
      } catch (err) { toastError(err); } finally { add.disabled = false; }
    });
    draw();
    return clear(wrap, h('div', { class: 'note-add' }, field('Not türü', kindSel), text,
      h('div', { style: { display: 'flex', justifyContent: 'flex-end' } }, add)), listBox) || wrap;
  };

  const media = () => {
    const items = d.media;
    const input = h('input', { class: 'input', type: 'file', multiple: true, accept: 'video/*,image/*', style: { height: 'auto', padding: '6px' } });
    const progress = uploadPanel();
    const send = h('button', { class: 'btn primary', type: 'button' }, svgIcon(icons.upload), 'Yükle');
    send.addEventListener('click', async () => {
      const files = [...(input.files || [])];
      if (!files.length) { toastError(new Error('Video ya da resim seçin')); return; }
      if (ctx.meta.remote && files.some(fl => VIDEO_EXT.test(fl.name))) {
        toastError(new Error(tr('Videolar yalnızca yerel ağdan yüklenebilir: {url}', { url: ctx.meta.local_url })));
        return;
      }
      send.disabled = true;
      try {
        const signal = progress.start();
        for (const [i, fl] of files.entries()) {
          await uploadChunked(fl, `/api/field/flights/${id}/videos`, pct => progress.set(tr('{name} ({i}/{total}) yükleniyor…', { name: fl.name, i: i + 1, total: files.length }), pct), signal);
        }
        progress.done();
        toast(tr('{n} dosya yüklendi', { n: files.length }));
        reload();
      } catch (err) {
        progress.done();
        if (err.canceled) toast('Yükleme iptal edildi'); else toastError(err);
      } finally { send.disabled = false; }
    });
    const open = m => {
      const el = m.kind === 'RESIM' ? h('img', { src: fileUrl(m.file, 1600), class: 'fl-media-full', alt: m.file_name })
        : h('video', { src: fileUrl(m.file), controls: true, autoplay: true, playsinline: true, class: 'fl-media-full' });
      modal({ title: m.file_name, wide: true, body: h('div', null, el, h('div', { class: 'small muted', style: { marginTop: '6px' } },
        h('a', { href: fileUrl(m.file), download: m.file_name }, 'İndir'), ` · ${m.uploaded_by_name || ''} · ${fmtDateTime(m.uploaded_at)}`)),
        onClose: () => { if (el.pause) { el.pause(); el.removeAttribute('src'); el.load(); } } });
    };
    const del = async m => {
      if (!await confirmDialog('Dosyayı sil', tr('{name} silinsin mi?', { name: m.file_name }), { okLabel: 'Sil', danger: true })) return;
      try { await api.del(`/api/field/videos/${m.id}`); toast('Silindi'); reload(); } catch (err) { toastError(err); }
    };
    return h('div', null,
      d.can.upload ? h('div', { class: 'fl-media-up' }, input, send, progress,
        h('div', { class: 'small muted' }, 'Birden fazla video ve resim seçebilirsiniz. Videolar yalnızca yerel ağdan, resimler her yerden yüklenir.'))
        : h('div', { class: 'small muted', style: { marginBottom: '10px' } }, 'Video ve resimler görev başladıktan sonra saha sorumlusu ya da pilot tarafından yüklenir.'),
      items.length ? h('div', { class: 'fl-media' }, items.map(m => h('div', { class: 'fl-media-item' },
        h('button', { type: 'button', class: 'fl-thumb', onclick: () => open(m), title: m.file_name },
          m.kind === 'RESIM' ? h('img', { src: fileUrl(m.file, 512), alt: '', loading: 'lazy' })
            : h('span', { class: 'fl-play' }, svgIcon(icons.camera), h('b', null, '▶'))),
        h('div', { class: 'small fl-media-name', title: m.file_name }, m.file_name),
        h('div', { class: 'small muted' }, `${(m.size / 1048576).toFixed(1)} MB · ${m.uploaded_by_name || ''}`),
        (d.can.manage || m.uploaded_by === ctx.user.id) ? h('button', { class: 'btn sm ghost', onclick: () => del(m) }, 'Sil') : null)))
        : h('div', { class: 'empty small' }, 'Henüz video ya da resim yok'));
  };

  clear(view,
    pageHead(tr('Uçuş — {id}', { id: o.queue_no || o.code }), { back: `#/field/task/${t.id}`, sub: `${t.code} · ${o.product_name || ''}` }),
    h('div', { class: 'fl-top' },
      h('div', { class: 'card card-pad' },
        h('h2', { class: 'fl-h' }, 'Uçak'),
        h('dl', { class: 'kv' },
          kv('Kuyruk no', queuePlate(o.queue_no, 'md') || '—'),
          kv('Sipariş', ctx.user.modules.includes('production') ? h('a', { href: `#/production/${o.id}` }, o.code) : o.code),
          kv('Ürün', `${o.product_name || '—'}${o.product_serial ? ` (${o.product_serial})` : ''}`),
          kv('Durum', badge(ORDER_STATES, o.status)),
          kv('Kullanım', h('span', { class: `badge ${USAGE_TYPES[o.usage_type]?.badge || 'gray'}` }, USAGE_TYPES[o.usage_type]?.label || '—')),
          kv('Saha deposuna giriş', o.completed_at ? fmtDateTime(o.completed_at) : null),
          o.status === 'HURDA' ? kv('Hurda', `${fmtDateTime(o.scrapped_at)} · ${o.scrap_reason || ''}`) : null,
          kv('Fırlatma sistemi', f.launch ? LAUNCH[f.launch] : 'Seçilmedi'),
          kv('Uçuş süresi (havada)', log?.summary?.flight_s != null ? clock(log.summary.flight_s) : null),
          kv('Uçuş notu', f.note)),
        scrapActions()),
      h('div', { class: 'card card-pad' },
        h('h2', { class: 'fl-h' }, 'Saha görevi'),
        h('dl', { class: 'kv' },
          kv('Görev', h('a', { href: `#/field/task/${t.id}` }, t.code)),
          kv('Durum', badge(TASK_STATES, t.status)),
          kv('Görev yeri', t.location_name || '—'),
          kv('Saha sorumlusu', t.lead_name || '—'),
          kv('Pilot', t.pilot_name || '—'),
          kv('Personel', t.staff.join(', ') || null),
          kv('Araçlar', t.vehicles.join(', ') || null),
          kv('Başlama / bitiş', t.started_at ? `${fmtDateTime(t.started_at)} – ${t.finished_at ? fmtDateTime(t.finished_at) : 'devam ediyor'}` : 'Başlamadı')))),
    logCard(),
    tabView([
      { key: 'report', label: 'Uçuş Raporu', render: report },
      { key: '3d', label: '3B Uçuş İzleme', render: replay },
      { key: 'notes', label: 'Uçuş Notları', count: d.notes.length, render: notes },
      { key: 'media', label: 'Video ve Resimler', count: d.media.length || null, render: media },
    ], tab || (log?.status === 'TAMAM' ? 'report' : 'notes')));   // log hazırsa rapor, değilse notlar
  if (log?.status === 'ISLENIYOR') {
    every(3000, async () => {
      const x = await api.get(`/api/field/flights/${id}`).catch(() => null);
      if (x && x.log?.status !== 'ISLENIYOR') reload();
    });
  }
}
