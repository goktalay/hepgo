// Evrak Yönetimi: taranmış evrak, resim, ses, video ve diğer dosyalar; OCR / konuşma metninde arama; videodaki kişiler
// (yüz tanıma, kişiye bağlama); firma/kişi ilişkilendirme;
// görünürlük (herkes / seçili roller / yalnızca yükleyen).
import { crmNav } from './crmhub.js';
import { api, fileUrl, uploadLarge, videoUrl } from '../api.js';
import { icons } from '../icons.js';
import {
  clear, confirmDialog, every, field, fmtDate, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, peoplePicker, segmented, selectInput,
  statStrip, svgIcon, t, toast, toastError, uploadPanel, companyName, shortCompany, periodFilter
} from '../ui.js';
import { signBadge, signatureBlock } from './sign.js';

const KINDS = { EVRAK: ['Evrak', 'blue'], RESIM: ['Resim', 'purple'], VIDEO: ['Video', 'yellow'], SES: ['Ses', 'green'], DIGER: ['Diğer', 'gray'] };
const MEDIA = ['SES', 'VIDEO'];   // konuşma metne çevrilir
const OCR = {
  BEKLIYOR: ['Sırada', 'gray'], ISLENIYOR: ['Metin okunuyor', 'blue'], TAMAM: ['Metin hazır', 'green'],
  HATA: ['Okunamadı', 'red'], YOK: ['Metin yok', 'gray'],
};
const VIS = { ALL: 'Herkes', ROLES: 'Seçili roller', PRIVATE: 'Yalnızca ben' };
const VIDEO_EXT = /\.(mp4|mov|m4v|webm|mkv|avi|3gp|ts)$/i;
const IMAGE_EXT = /\.(jpe?g|png|tiff?|bmp|webp|gif)$/i;
const badgeOf = (map, key) => { const [label, color] = map[key] || [key, 'gray']; return h('span', { class: `badge ${color}` }, label); };
const size = b => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

export async function render(view, params, ctx) {
  if (params[0] === 'belge') { const belge = await import('./belge.js'); return belge.render(view, params.slice(1), ctx); }
  if (params[0]) return renderDetail(view, Number(params[0]), ctx);
  return renderList(view, ctx);
}

// Evrak ↔ Belge Yönetim alt sekmeleri
function docSubTabs(active) {
  return segmented([['evrak', 'Evraklar'], ['belge', 'Belge Yönetim']], active,
    v => { location.hash = v === 'belge' ? '#/documents/belge' : '#/documents'; }, { tabs: true });
}

// ---------- Küçük resim / tür simgesi
export function thumbOf(d, cls = 'doc-thumb') {
  if (d.thumb) return h('img', { class: cls, src: fileUrl(d.thumb, 512), alt: '', loading: 'lazy' });
  return h('span', { class: `${cls} doc-thumb-icon ${d.kind.toLowerCase()}` },
    svgIcon(d.kind === 'VIDEO' ? icons.camera : d.kind === 'SES' ? icons.mic : icons.documents));
}

// Aranan ifadenin geçtiği metin parçası (vurgulu)
const snippetEl = s => (s ? h('div', { class: 'doc-snippet' }, s.before, h('mark', null, s.match), s.after) : null);

// ---------- Liste ve arama
async function renderList(view, ctx) {
  const [companies, people] = await Promise.all([api.get('/api/companies'), api.get('/api/companies/people')]);
  const q = h('input', { class: 'input doc-search', type: 'search', placeholder: 'Evrak metninde ara…', title: 'Evrak metninde kelime ya da cümle, başlık, firma, kişi' });
  const company = selectInput(companies.map(c => [c.id, c.name]), { all: 'Tüm firmalar' });
  const kind = selectInput(Object.entries(KINDS).map(([k, v]) => [k, v[0]]), { all: 'Tüm türler' });
  const status = selectInput(Object.entries(OCR).map(([k, v]) => [k, v[0]]), { all: 'Tüm metin durumları' });
  const period = periodFilter('documents', () => load().catch(toastError), { title: 'Evrak tarihi (yoksa yükleme tarihi)' });
  const body = h('div');
  let docs = [];
  let ocrAvailable = true;

  const draw = () => {
    const searching = q.value.trim().length > 0;
    clear(body,
      ocrAvailable ? null : h('div', { class: 'alert warn' }, 'OCR motoru bulunamadı; evraklar kaydedilir ama metinleri okunamaz.'),
      docs.length ? h('div', { class: 'doc-list' }, docs.map(d => h('a', { class: 'card doc-row', href: `#/documents/${d.id}` },
        thumbOf(d),
        h('div', { class: 'grow' },
          h('div', { class: 'doc-title' }, h('b', null, d.title), ' ', badgeOf(KINDS, d.kind),
            d.visibility !== 'ALL' ? h('span', { class: 'badge gray', title: 'Görünürlük kısıtlı' }, `🔒 ${VIS[d.visibility]}`) : null),
          h('div', { class: 'small muted' }, [d.file_name, size(d.size), d.pages ? t('{n} sayfa', { n: d.pages }) : null].filter(Boolean).join(' · ')),
          snippetEl(d.snippet),
          d.companies.length || d.people.length ? h('div', { class: 'chips doc-chips' },
            d.companies.map(c => h('span', { class: 'chip', title: c.name }, shortCompany(c.name))),
            d.people.map(p => h('span', { class: 'chip light', title: `${p.full_name} · ${p.company_name}` }, `${p.full_name} · ${shortCompany(p.company_name)}`))) : null),
        h('div', { class: 'doc-side' },
          h('div', null, fmtDate(d.doc_date || d.uploaded_at)),
          badgeOf(OCR, d.ocr_status),
          h('div', { class: 'small muted' }, d.uploaded_by_name || '')))))
        : h('div', { class: 'card empty' }, searching ? 'Aramaya uyan evrak yok' : 'Henüz evrak yüklenmedi'));
  };
  let seq = 0;
  const load = async () => {
    const my = ++seq;
    const qs = new URLSearchParams(Object.entries({ q: q.value.trim(), company_id: company.value, kind: kind.value,
      status: status.value, ...period.range() }).filter(([, v]) => v));
    const r = await api.get(`/api/documents?${qs}`);
    if (my !== seq) return;   // daha yeni arama geldi
    docs = r.documents;
    ocrAvailable = r.ocr_available;
    draw();
  };
  let timer;
  q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => load().catch(toastError), 300); });
  [company, kind, status].forEach(el => el.addEventListener('change', () => load().catch(toastError)));

  clear(view,
    pageHead('Evrak Yönetimi', { back: '#/', tabs: crmNav('documents', ctx) }),
    // Alt sekme seçici kendi satırında; filtreler + Evrak Yükle hemen altındaki toolbar'da (başlıkta değil), düğme sağda
    moduleToolbar(docSubTabs('evrak')),
    h('div', { class: 'filters' },
      h('div', { class: 'doc-search-wrap' }, svgIcon(icons.search), q), company, kind, status, period.el,
      h('div', { class: 'spacer' }),
      h('button', { class: 'btn primary', onclick: () => openUpload(ctx, {}, load) }, svgIcon(icons.upload), 'Evrak Yükle')),
    body);
  await load();
  every(5000, () => { if (docs.some(d => ['BEKLIYOR', 'ISLENIYOR'].includes(d.ocr_status))) load().catch(() => {}); });
}

// ---------- Çoklu seçim (firma / kişi): açılır listeden ekle, çip olarak göster
function chipPicker(items, selected, { placeholder, empty, onChange } = {}) {
  const chosen = new Set(selected);
  const sel = h('select', { class: 'input' });
  const chips = h('div', { class: 'chips', style: { justifyContent: 'flex-start', marginTop: '6px' } });
  let list = items;
  const draw = () => {
    clear(sel, h('option', { value: '' }, list.length ? placeholder : empty),
      list.filter(i => !chosen.has(i.id)).map(i => h('option', { value: i.id }, i.label)));
    clear(chips, [...chosen].map(id => {
      const it = items.find(i => i.id === id);
      return it ? h('span', { class: 'chip' }, it.label, h('button', { type: 'button', class: 'chip-x', onclick: () => {
        chosen.delete(id); draw(); onChange?.();
      } }, '×')) : null;
    }));
  };
  sel.addEventListener('change', () => { if (sel.value) { chosen.add(Number(sel.value)); draw(); onChange?.(); } });
  draw();
  const el = h('div', null, sel, chips);
  el.getIds = () => [...chosen];
  el.setItems = next => { list = next; draw(); };
  return el;
}

// Görünürlük seçimi: herkes / seçili roller / yalnızca ben
function visibilityPicker(ctx, value = 'ALL', roles = []) {
  let vis = value;
  const chosen = new Set(roles);
  const roleBox = h('div', { class: 'role-checks' }, ctx.meta.roles.map(r => {
    const cb = h('input', { type: 'checkbox', checked: chosen.has(r) });
    cb.addEventListener('change', () => (cb.checked ? chosen.add(r) : chosen.delete(r)));
    return h('label', { class: 'check' }, cb, r);
  }));
  const hint = h('div', { class: 'small muted', style: { marginTop: '6px' } });
  const sync = () => {
    roleBox.hidden = vis !== 'ROLES';
    hint.textContent = { ALL: 'Evrak Yönetimi\'ne girebilen herkes görür.',
      ROLES: 'Yalnızca seçtiğiniz rollerdeki kişiler görür. Sistem yöneticisi de ancak rolü seçilirse görür.',
      PRIVATE: 'Yalnızca siz görürsünüz; sistem yöneticisi dahil kimse göremez.' }[vis];
  };
  const el = h('div', null, segmented(Object.entries(VIS), vis, v => { vis = v; sync(); }), roleBox, hint);
  sync();
  el.value = () => ({ visibility: vis, roles: vis === 'ROLES' ? [...chosen] : [] });
  return el;
}

async function linkPickers(preset) {
  const [companies, people] = await Promise.all([api.get('/api/companies'), api.get('/api/companies/people')]);
  const personItems = cids => people.filter(p => !cids.length || cids.includes(p.company_id))
    .map(p => ({ id: p.id, label: `${p.full_name}${p.title ? ` (${p.title})` : ''} · ${p.company_name}`, company_id: p.company_id }));
  const personPick = chipPicker(personItems([]), preset.person_ids || [], { placeholder: 'Kişi ekle…', empty: 'Firmaya kişi eklenmemiş' });
  const companyPick = chipPicker(companies.filter(c => c.active || (preset.company_ids || []).includes(c.id)).map(c => ({ id: c.id, label: c.name })),
    preset.company_ids || [], { placeholder: 'Firma ekle…', empty: 'Firma yok (Firma Yönetimi\'nden ekleyin)',
      onChange: () => personPick.setItems(personItems(companyPick.getIds())) });
  personPick.setItems(personItems(companyPick.getIds()));
  return { companyPick, personPick };
}

// ---------- Yükleme penceresi (Firma detayından da açılır: preset.company_ids)
export async function openUpload(ctx, preset = {}, done) {
  const files = [];
  const pick = h('input', { type: 'file', multiple: true, hidden: true });
  const camera = h('input', { type: 'file', accept: 'image/*', capture: 'environment', multiple: true, hidden: true });
  const list = h('div', { class: 'upload-files' });
  const merge = h('input', { type: 'checkbox' });
  const mergeRow = h('label', { class: 'check', hidden: true }, merge, 'Seçilen resimleri tek evrak (PDF) olarak birleştir — çok sayfalı tarama');
  const title = h('input', { class: 'input', placeholder: 'Boş bırakılırsa dosya adı kullanılır' });
  const date = h('input', { class: 'input', type: 'date' });
  const note = h('textarea', { class: 'input', rows: 2, placeholder: 'İsteğe bağlı açıklama (aramada da bulunur)' });
  const { companyPick, personPick } = await linkPickers(preset);
  const visibility = visibilityPicker(ctx);
  const progress = uploadPanel();
  const drawFiles = () => {
    const images = files.filter(f => IMAGE_EXT.test(f.name));
    mergeRow.hidden = images.length < 2 || images.length !== files.length;
    if (mergeRow.hidden) merge.checked = false;
    clear(list, files.length ? files.map((f, i) => h('div', { class: 'upload-file' },
      h('span', { class: 'small muted' }, `${i + 1}.`), h('b', { class: 'grow' }, f.name), h('span', { class: 'small muted' }, size(f.size)),
      ctx.meta.remote && VIDEO_EXT.test(f.name) ? h('span', { class: 'badge red' }, 'Yalnızca yerel ağdan') : null,
      h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { files.splice(i, 1); drawFiles(); } }, 'Çıkar')))
      : h('div', { class: 'small muted' }, 'Henüz dosya seçilmedi'));
  };
  const add = input => { files.push(...input.files); input.value = ''; drawFiles(); };
  pick.addEventListener('change', () => add(pick));
  camera.addEventListener('change', () => add(camera));
  drawFiles();
  modal({
    title: 'Evrak Yükle',
    wide: true,
    onClose: () => progress.abort(),
    body: h('div', null,
      field('Dosyalar', h('div', null,
        h('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap' } },
          h('button', { class: 'btn', type: 'button', onclick: () => pick.click() }, svgIcon(icons.upload), 'Dosya Seç'),
          h('button', { class: 'btn', type: 'button', onclick: () => camera.click() }, svgIcon(icons.camera), 'Kamerayla Tara'),
          pick, camera),
        list, mergeRow), 'Evrak (PDF, taranmış resim), resim, ses kaydı, video, Word/Excel ve diğer dosyalar. Metin otomatik okunur; ses ve videodaki konuşma metne çevrilir, videodaki kişiler bulunur.'),
      h('div', { class: 'row' }, field('Evrak adı', title), field('Evrak tarihi', date)),
      h('div', { class: 'row' }, field('Firmalar', companyPick), field('Firma kişileri', personPick)),
      field('Açıklama', note),
      field('Kimler görebilir?', visibility),
      progress),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Yükle', class: 'primary', onClick: async () => {
          if (!files.length) throw new Error('Dosya seçin');
          if (ctx.meta.remote && files.some(f => VIDEO_EXT.test(f.name))) {
            throw new Error(t('Videolar yalnızca yerel ağdan yüklenebilir: {url}', { url: ctx.meta.local_url }));
          }
          const vis = visibility.value();
          if (vis.visibility === 'ROLES' && !vis.roles.length) throw new Error('Görebilecek en az bir rol seçin');
          const signal = progress.start();
          try {
            const ids = [];
            for (const [i, f] of files.entries()) {
              ids.push(await uploadLarge(f, 'documents', pct => progress.set(t('{name} ({i}/{total}) yükleniyor…', { name: f.name, i: i + 1, total: files.length }), pct), signal));
            }
            progress.done();
            const r = await api.post('/api/documents', {
              upload_ids: ids, merge_images: merge.checked, title: title.value.trim() || null, doc_date: date.value || null,
              note: note.value.trim() || null, company_ids: companyPick.getIds(), person_ids: personPick.getIds(), ...vis,
            });
            toast(t('{n} evrak yüklendi; metin okunuyor', { n: r.ids.length }));
            done?.(r.ids);
          } catch (err) {
            progress.done();
            if (!err.canceled) throw err;
            toast('Yükleme iptal edildi');
            return true;
          }
        },
      },
    ],
  });
}

// ---------- Evrak detayı
async function renderDetail(view, id, ctx) {
  const d = await api.get(`/api/documents/${id}`);
  const url = fileUrl(d.file);
  const ext = d.file_name.split('.').pop().toLowerCase();
  const preview = d.kind === 'VIDEO' ? h('video', { src: url + '#t=0.1', controls: true, playsinline: true, preload: 'metadata', class: 'doc-preview' })
    : d.kind === 'SES' ? h('div', { class: 'doc-preview audio' }, thumbOf(d, 'doc-thumb big'),
      h('audio', { src: url, controls: true, preload: 'metadata' }))
    : d.kind === 'RESIM' && ext !== 'heic' && ext !== 'heif' ? h('img', { src: fileUrl(d.file, 1600), class: 'doc-preview', alt: d.title })
      : ext === 'pdf' ? h('iframe', { src: url, class: 'doc-preview pdf', title: d.title })
        : h('div', { class: 'doc-preview none' }, thumbOf(d, 'doc-thumb big'), h('p', null, 'Bu dosya türü tarayıcıda önizlenemiyor.'),
          h('a', { class: 'btn primary', href: url, download: d.file_name }, 'Dosyayı İndir'));

  // OCR metni ve metin içinde arama (vurgulu)
  const find = h('input', { class: 'input', type: 'search', placeholder: 'Metinde ara…' });
  const textBox = h('pre', { class: 'ocr-text' });
  const media = () => preview.matches?.('video, audio') ? preview : preview.querySelector?.('audio');
  const seek = sec => { const m = media(); if (m) { m.currentTime = sec; m.play?.().catch(() => {}); m.scrollIntoView({ block: 'nearest' }); } };
  const drawText = () => {
    const text = d.ocr_text || '';
    const term = find.value.trim();
    if (!term && MEDIA.includes(d.kind)) {   // konuşma metni: zamana tıklayınca kayıt o ana gider
      return clear(textBox, text.split('\n').map(line => {
        const m = line.match(/^\[(?:(\d+):)?(\d+):(\d+)\] (.*)$/);
        if (!m) return h('div', null, line);
        const sec = (Number(m[1] || 0) * 3600) + Number(m[2]) * 60 + Number(m[3]);
        return h('div', { class: 'tr-line' }, h('button', { class: 'tr-time', type: 'button', onclick: () => seek(sec) },
          line.slice(1, line.indexOf(']'))), m[4]);
      }));
    }
    if (!term) return clear(textBox, text || '—');
    const esc = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const parts = text.split(new RegExp(`(${esc})`, 'gi'));
    clear(textBox, parts.map((p, i) => (i % 2 ? h('mark', null, p) : p)));
    textBox.querySelector('mark')?.scrollIntoView({ block: 'center' });
  };
  find.addEventListener('input', drawText);
  drawText();

  const edit = () => editDocument(ctx, d);
  const remove = async () => {
    if (!await confirmDialog('Evrakı sil', t('{title} kalıcı olarak silinsin mi?', { title: d.title }), { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/documents/${id}`); toast('Evrak silindi'); location.hash = '#/documents'; } catch (err) { toastError(err); }
  };
  const rerun = async () => {
    try { await api.post(`/api/documents/${id}/ocr`); toast('Metin yeniden okunuyor'); window.dispatchEvent(new HashChangeEvent('hashchange')); }
    catch (err) { toastError(err); }
  };
  const kv = (k, v) => [h('dt', null, k), h('dd', null, v)];
  clear(view,
    pageHead(d.title, { back: '#/documents', sub: d.file_name }),
    moduleToolbar(
      h('a', { class: 'btn', href: url, download: d.file_name }, 'İndir'),
      d.can_edit ? h('button', { class: 'btn', onclick: edit }, 'Düzenle') : null,
      d.can_edit ? h('button', { class: 'btn danger', onclick: remove }, 'Sil') : null),
    h('div', { class: 'doc-layout' },
      h('div', { class: 'card doc-stage' }, preview),
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: '16px' } },
        h('div', { class: 'card card-pad' },
          h('dl', { class: 'kv' },
            kv('Tür', badgeOf(KINDS, d.kind)),
            kv('Evrak tarihi', fmtDate(d.doc_date)),
            kv('Boyut', `${size(d.size)}${d.pages ? t(' · {n} sayfa', { n: d.pages }) : ''}${d.duration ? ` · ${fmtClock(d.duration)}` : ''}`),
            kv('Yükleyen', `${d.uploaded_by_name || '—'} · ${fmtDateTime(d.uploaded_at)}`),
            kv('Görünürlük', d.visibility === 'ROLES' ? t('Seçili roller: {roles}', { roles: d.roles.join(', ') }) : VIS[d.visibility]),
            kv('Firmalar', d.companies.length ? h('div', { class: 'chips', style: { justifyContent: 'flex-start' } },
              d.companies.map(c => h('a', { class: 'chip', href: `#/companies/${c.id}`, title: c.name }, shortCompany(c.name)))) : '—'),
            kv('Kişiler', d.people.length ? h('span', null, d.people.map((p, i) => [i ? ', ' : '', p.full_name, ' (',
              companyName(p.company_name), ')'])) : '—'),
            d.note ? kv('Açıklama', d.note) : null)),
        h('div', { class: 'card card-pad' },
          h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' } },
            h('h2', { style: { fontSize: '15px', margin: 0 } }, MEDIA.includes(d.kind) ? 'Konuşma metni (otomatik)' : 'Okunan metin (OCR)'),
            badgeOf(OCR, d.ocr_status),
            h('span', { style: { flex: 1 } }),
            d.can_edit && (['TAMAM', 'HATA'].includes(d.ocr_status) || (MEDIA.includes(d.kind) && d.ocr_status === 'YOK'))
              ? h('button', { class: 'btn sm', onclick: rerun }, MEDIA.includes(d.kind) ? 'Yeniden işle' : 'Yeniden oku') : null),
          d.ocr_status === 'HATA' ? h('div', { class: 'alert err' }, d.ocr_error || 'Metin okunamadı') : null,
          d.ocr_status === 'YOK' ? h('div', { class: 'small muted' }, MEDIA.includes(d.kind) ? 'Kayıtta konuşma bulunamadı.' : 'Bu dosya türünden metin okunmaz.') : null,
          ['BEKLIYOR', 'ISLENIYOR'].includes(d.ocr_status) ? h('div', { class: 'small muted' }, d.kind === 'VIDEO'
            ? 'Konuşma metne çevriliyor, videodaki kişiler aranıyor; hazır olunca sayfa yenilenir.'
            : d.kind === 'SES' ? 'Ses metne çevriliyor; hazır olunca sayfa yenilenir.'
              : d.kind === 'RESIM' ? 'Metin okunuyor, resimdeki kişiler aranıyor; hazır olunca sayfa yenilenir.'
                : 'Metin okunuyor; hazır olunca sayfa yenilenir.') : null,
          d.ocr_status === 'TAMAM' ? [find, textBox] : null),
        ['VIDEO', 'RESIM'].includes(d.kind) && !['BEKLIYOR', 'ISLENIYOR'].includes(d.ocr_status) ? facesCard(d, seek) : null,
        signaturesCard(d, ctx))));
  if (['BEKLIYOR', 'ISLENIYOR'].includes(d.ocr_status)) {
    every(3000, async () => {
      const x = await api.get(`/api/documents/${id}`).catch(() => null);
      if (x && !['BEKLIYOR', 'ISLENIYOR'].includes(x.ocr_status)) window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
  }
}

const fmtClock = sec => { sec = Math.round(sec); const hh = Math.floor(sec / 3600), mm = Math.floor(sec % 3600 / 60), ss = sec % 60;
  return hh ? `${hh}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}` : `${mm}:${String(ss).padStart(2, '0')}`; };

// ---------- Videodaki / resimdeki kişiler: bulunan yüzler; tıklayınca firma kişisi ya da personel seçilir
function facesCard(d, seek) {
  const box = h('div', { class: 'faces' });
  const where = d.kind === 'VIDEO' ? 'Videodaki' : 'Resimdeki';
  const draw = faces => {
    const unknown = faces.filter(f => !f.person_id && !f.user_id).length;
    clear(box,
      h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' } },
        h('h2', { style: { fontSize: '15px', margin: 0 } }, t('{where} kişiler ({n})', { where, n: faces.length })),
        unknown ? h('span', { class: 'badge yellow' }, t('{n} tanımsız', { n: unknown })) : null),
      faces.length ? h('div', { class: 'face-grid' }, faces.map(f => {
        const known = f.person_id || f.user_id;
        return h('button', { type: 'button', class: `face ${known ? 'known' : 'unknown'} ${f.auto ? 'auto' : ''}`,
          title: 'Kim olduğunu seçmek için tıklayın', onclick: () => assignFace(d, f, draw, seek) },
          h('img', { src: fileUrl(f.crop, 256), alt: '', loading: 'lazy' }),
          h('b', null, f.person_name || f.user_name || 'Tanımsız kişi'),
          h('span', { class: 'small muted', title: f.person_id ? f.company_name : '' }, f.person_id ? shortCompany(f.company_name) : f.user_id ? 'Personel'
            : d.kind === 'VIDEO' ? t('{n} karede görüldü', { n: f.samples }) : 'Kim olduğunu seçin'),
          f.auto ? h('span', { class: 'face-auto' }, 'Otomatik öneri') : null);
      })) : h('div', { class: 'empty small' }, d.kind === 'VIDEO' ? 'Videoda yüz bulunamadı' : 'Resimde yüz bulunamadı'),
      faces.length ? h('div', { class: 'small muted', style: { marginTop: '8px' } },
        'Yüze tıklayıp hangi firmadaki hangi kişi ya da hangi personel olduğunu seçin. Tanımlanan kişiler sonraki video ve resimlerde otomatik önerilir.') : null);
  };
  draw(d.faces || []);
  return h('div', { class: 'card card-pad' }, box);
}

async function assignFace(d, f, draw, seek) {
  const [people, users] = await Promise.all([api.get('/api/companies/people'), api.get('/api/people')]);
  let pick = f.person_id ? `p${f.person_id}` : f.user_id ? `u${f.user_id}` : null;
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi, firma ya da personel ara…' });
  const list = h('div', { class: 'pick-list face-pick' });
  const items = [
    ...people.map(p => ({ key: `p${p.id}`, name: p.full_name, sub: [shortCompany(p.company_name), p.title].filter(Boolean).join(' · '), group: 'Firma kişileri' })),
    ...users.map(u => ({ key: `u${u.id}`, name: u.full_name, sub: 'Personel', group: 'Personel' })),
  ];
  const drawList = () => {
    const shown = items.filter(i => matches(q.value, i.name, i.sub));
    clear(list, shown.length ? ['Firma kişileri', 'Personel'].map(g => {
      const rows = shown.filter(i => i.group === g);
      return rows.length ? [h('div', { class: 'pick-group' }, g), rows.map(i => {
        const el = h('div', { class: `pick ${pick === i.key ? 'on' : ''}` },
          h('input', { type: 'radio', name: 'face', checked: pick === i.key }),
          h('div', { class: 'grow' }, h('b', null, i.name), h('span', { class: 'small muted' }, i.sub)));
        el.addEventListener('click', () => { pick = i.key; drawList(); });
        return el;
      })] : null;
    }) : h('div', { class: 'empty small' }, 'Eşleşen kişi yok. Firma kişisi Firma Yönetimi\'nden eklenir.'));
  };
  q.addEventListener('input', drawList);
  drawList();
  // bağlama evrağın kişilerini de değiştirir: sayfa yeniden çizilir
  const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));
  const save = async body => { await api.put(`/api/documents/${d.id}/faces/${f.id}`, body); reload(); };
  modal({
    title: 'Bu kişi kim?',
    wide: true,
    body: h('div', { class: 'face-assign' },
      h('div', { class: 'face-assign-img' }, h('img', { src: fileUrl(f.crop, 256), alt: '' }),
        f.first_at != null ? h('button', { class: 'btn sm', type: 'button', onclick: () => seek(f.first_at) }, t('Videoda göster ({t})', { t: fmtClock(f.first_at) })) : null,
        f.auto ? h('div', { class: 'small muted' }, 'Bu kişi daha önce tanımlanan bir yüze benzediği için otomatik önerildi; doğru değilse değiştirin.') : null),
      h('div', { class: 'grow' }, q, list)),
    actions: [
      { label: 'Kişi değil (kaldır)', class: 'ghost', onClick: async () => {
        await api.del(`/api/documents/${d.id}/faces/${f.id}`); toast('Yüz kaldırıldı'); reload();
      } },
      (f.person_id || f.user_id) ? { label: 'Tanımsız yap', onClick: async () => { await save({}); toast('Kişi tanımsız yapıldı'); } } : null,
      'spacer',
      { label: 'Vazgeç' },
      { label: 'Kaydet', class: 'primary', onClick: async () => {
        if (!pick) throw new Error('Listeden bir kişi seçin');
        await save(pick[0] === 'p' ? { person_id: Number(pick.slice(1)) } : { user_id: Number(pick.slice(1)) });
        toast('Kişi tanımlandı');
      } },
    ].filter(Boolean),
  });
}

// ---------- İmzalar: talep gönder, durumları gör, imzayı doğrula
function signaturesCard(d, ctx) {
  const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));
  const request = async () => {
    const users = await api.get('/api/people');
    const picker = peoplePicker(users, { selected: [] });
    const message = h('textarea', { class: 'input', rows: 2, placeholder: 'İmzalayacak kişiye not (isteğe bağlı)' });
    modal({
      title: t('{title} — İmzaya gönder', { title: d.title }),
      body: h('div', null, field('İmzalayacak kişiler', picker, 'Her kişiye ayrı talep açılır; bildirimler panelinde görünür.'),
        field('Mesaj', message)),
      actions: [{ label: 'Vazgeç' }, {
        label: 'İmzaya Gönder', class: 'primary', onClick: async () => {
          const ids = picker.getIds();
          if (!ids.length) throw new Error('İmzalayacak en az bir kişi seçin');
          const r = await api.post(`/api/documents/${d.id}/signatures`, { user_ids: ids, message: message.value.trim() || null });
          toast(t('{n} kişiye imza talebi gönderildi{extra}', { n: r.created.length, extra: r.skipped.length ? t(' ({list}: zaten bekliyor)', { list: r.skipped.join(', ') }) : '' }));
          reload();
        },
      }],
    });
  };
  const sigs = d.signatures || [];
  return h('div', { class: 'card card-pad' },
    h('div', { class: 'co-section-head' }, h('h2', null, t('İmzalar ({n})', { n: sigs.length })),
      h('button', { class: 'btn sm primary', onclick: request }, '✍ İmzaya Gönder')),
    sigs.length ? h('div', { class: 'meet-list' }, sigs.map(s => h('div', { class: 'meet-item' },
      h('div', { class: 'meet-head' }, h('div', { class: 'grow' }, h('b', null, s.signer_name || '—'),
        h('span', { class: 'small muted' }, t(' · gönderen {name}, {d}', { name: s.requested_by_name || '—', d: fmtDateTime(s.requested_at) }))),
        signBadge(s.status), h('a', { class: 'btn sm', href: `#/sign/${s.id}` }, 'Aç')),
      s.status === 'IMZALANDI' ? signatureBlock(s) : null,
      s.status === 'REDDEDILDI' ? h('div', { class: 'meet-sub', style: { color: 'var(--danger)' } }, t('Red gerekçesi: {r}', { r: s.reason || '—' })) : null)))
      : h('div', { class: 'empty small' }, 'Bu evrak için imza talebi yok'));
}

async function editDocument(ctx, d) {
  const title = h('input', { class: 'input', value: d.title });
  const date = h('input', { class: 'input', type: 'date', value: d.doc_date || '' });
  const note = h('textarea', { class: 'input', rows: 2 }, d.note || '');
  const { companyPick, personPick } = await linkPickers({ company_ids: d.companies.map(c => c.id), person_ids: d.people.map(p => p.id) });
  const mine = d.uploaded_by === ctx.user.id;
  const visibility = visibilityPicker(ctx, d.visibility, d.roles);
  modal({
    title: 'Evrakı düzenle',
    wide: true,
    body: h('div', null,
      h('div', { class: 'row' }, field('Evrak adı', title), field('Evrak tarihi', date)),
      h('div', { class: 'row' }, field('Firmalar', companyPick), field('Firma kişileri', personPick)),
      field('Açıklama', note),
      mine ? field('Kimler görebilir?', visibility) : h('div', { class: 'small muted' }, 'Görünürlüğü yalnızca evrakı yükleyen kişi değiştirebilir.')),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          const vis = mine ? visibility.value() : { visibility: d.visibility, roles: d.roles };
          await api.put(`/api/documents/${d.id}`, { title: title.value.trim(), doc_date: date.value || null, note: note.value.trim() || null,
            company_ids: companyPick.getIds(), person_ids: personPick.getIds(), ...vis });
          toast('Evrak kaydedildi');
          window.dispatchEvent(new HashChangeEvent('hashchange'));
        },
      },
    ],
  });
}

export { KINDS, OCR, badgeOf, size, snippetEl, matches };
