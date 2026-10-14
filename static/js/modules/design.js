// Endüstriyel Tasarım: projeler → montaj / çizim kartları (3B önizleme + ad) → montaj detayı:
// üstte genel bilgiler (kalkış ağırlığı, faydalı yük, mamul…), altta "3B Görünüm" (STEP parça ağacı, patlatma, ürün eşleştirme,
// G-code karşılaştırma) ve "CFD Analizi" (2B kesit, kafes-Boltzmann) alt modülleri. Her yeni dosya yüklemesi yeni sürümdür.
import { api, upload } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, moduleTabs, moduleToolbar, onLeave, pageHead, segmented, t, toast, toastError } from '../ui.js';
import { isStep, parseStep, viewStep } from '../step3d.js';
import { viewer as gcodeViewer } from '../gcode3d.js';
import { createCfdView } from '../cfd2d.js';
import { createCfdViz } from '../cfdviz.js';

const KIND = { assembly: 'Montaj Çizimi', drawing: 'Çizim', part: 'Parça' };
const KIND_BADGE = { assembly: 'blue', drawing: 'gray', part: 'green' };
const KIND_COLOR = { assembly: '#1d4e89', drawing: '#5d6879', part: '#16a34a' };
const isImg = n => /\.(png|jpe?g|webp|gif|bmp)$/i.test(n || '');
const fmtNum = (v, unit = '', digits = 0) => (v == null || v === '' || Number.isNaN(Number(v))) ? '—' : `${Number(v).toLocaleString('tr-TR', { maximumFractionDigits: digits })}${unit ? ' ' + unit : ''}`;
const fmtSize = b => b == null ? '' : b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`;

export async function render(view, params, ctx) {
  if (params[0] && params[1]) return renderDetail(view, Number(params[0]), Number(params[1]), params[2] === 'v' && params[3] ? Number(params[3]) : null, ctx);
  if (params[0]) return renderProject(view, Number(params[0]), ctx);
  return renderProjects(view, ctx);
}

// Tasarım dosyası bağlantıları: önizleme herkese; indirme yalnızca Master
function dzFileLinks(qkey, id, name, isMaster) {
  const base = `/api/design/file?${qkey}=${id}`;
  const out = [h('a', { class: 'dz-file', href: base, target: '_blank', rel: 'noopener' }, '📄 ', name, h('span', { class: 'small muted' }, ' · önizle'))];
  if (isMaster) out.push(h('a', { class: 'btn sm', href: `${base}&dl=1`, download: name }, '⬇ İndir'));
  return out;
}

// Görsel yüklenmemiş projeler için sade tasarım ikonu (pergel + gönye)
function designIcon() {
  const tpl = document.createElement('template');
  tpl.innerHTML = `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M24 7v6"/><circle cx="24" cy="15" r="2.4" fill="currentColor" stroke="none"/>
    <path d="M24 17.2 14 39"/><path d="M24 17.2 34 39"/><path d="M18.8 28.4h10.4"/>
    <path d="M8 41h32"/></svg>`;
  return tpl.content.firstElementChild;
}
function kindGlyphMarkup(kind) {
  if (kind === 'assembly') return '<path d="M24 5 40 14v20L24 43 8 34V14z"/><path d="M8 14 24 23l16-9M24 23v20"/>';
  if (kind === 'part') return '<circle cx="24" cy="24" r="6"/><path d="M24 6v6M24 36v6M6 24h6M36 24h6M11 11l4.2 4.2M32.8 32.8 37 37M37 11l-4.2 4.2M15.2 32.8 11 37"/>';
  return '<path d="M14 6h13l9 9v27H14z"/><path d="M27 6v9h9M19 25h11M19 31h11M19 19h6"/>';
}
function kindGlyph(kind) {
  const tpl = document.createElement('template');
  tpl.innerHTML = `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${kindGlyphMarkup(kind)}</svg>`;
  return tpl.content.firstElementChild;
}

function projCard(p) {
  const thumb = p.thumb_vid
    ? h('img', { src: `/api/design/file?v=${p.thumb_vid}`, alt: p.name, loading: 'lazy' })
    : h('span', { class: 'dz-proj-ico' }, designIcon());
  return h('a', { class: 'card dz-proj', href: `#/design/${p.id}` },
    h('div', { class: `dz-proj-thumb ${p.thumb_vid ? 'has-img' : ''}` }, thumb),
    h('div', { class: 'dz-proj-body' },
      h('b', { class: 'dz-proj-name' }, p.name),
      p.description ? h('div', { class: 'small muted dz-proj-desc' }, p.description) : null,
      h('div', { class: 'small muted dz-proj-meta' }, t('{n} çizim · {by} · {d}', { n: p.drawing_count, by: p.created_by_name || '', d: fmtDateTime(p.created_at) }))));
}

async function renderProjects(view, ctx) {
  const body = h('div');
  const load = async () => {
    let list;
    try { list = await api.get('/api/design/projects'); } catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    clear(body, list.length ? h('div', { class: 'dz-proj-grid' }, list.map(projCard))
      : h('div', { class: 'card empty' }, 'Henüz proje yok. “Yeni Proje” ile başlayın.'));
  };
  const newProject = () => {
    const name = h('input', { class: 'input', placeholder: 'Proje adı' });
    const desc = h('textarea', { class: 'input', rows: 3, placeholder: 'Açıklama (isteğe bağlı)' });
    modal({
      title: 'Yeni Tasarım Projesi', body: h('div', null, field('Proje adı', name), field('Açıklama', desc)),
      actions: [{ label: 'Vazgeç' }, { label: 'Oluştur', class: 'primary', onClick: async () => {
        if (!name.value.trim()) throw new Error('Proje adı girin');
        const r = await api.post('/api/design/projects', { name: name.value, description: desc.value });
        location.hash = `#/design/${r.id}`;
      } }],
    });
  };
  clear(view, pageHead('Endüstriyel Tasarım', { back: '#/', sub: 'Tasarım projeleri, çizimler ve sürümler' }),
    moduleToolbar(
      ctx.user.master ? h('button', { class: 'btn', onclick: deleteRequests }, '🗑 Silme Talepleri') : null,
      h('button', { class: 'btn primary', onclick: newProject }, '+ Yeni Proje')),
    body);
  load();
}

// Master: silme talepleri listesi (onayla / reddet)
async function deleteRequests() {
  let reqs;
  try { reqs = await api.get('/api/design/delete-requests'); } catch (err) { return toastError(err); }
  const list = h('div', { class: 'dz-notes' });
  const draw = async () => {
    try { reqs = await api.get('/api/design/delete-requests'); } catch { /* */ }
    clear(list, reqs.length ? reqs.map(r => h('div', { class: 'dz-note-row' },
      h('div', { class: 'grow' }, h('b', null, `${r.kind === 'part' ? 'Üretim parçası' : 'Çizim'}: ${r.label || ''}`),
        h('div', { class: 'small muted' }, `${r.project_name || ''} · ${r.requested_by_name || ''} · ${fmtDateTime(r.created_at)}`)),
      h('button', { class: 'btn sm danger', type: 'button', onclick: async () => { await api.post(`/api/design/delete-requests/${r.id}/approve`, {}); toast('Silindi'); draw(); } }, 'Onayla (Sil)'),
      h('button', { class: 'btn sm', type: 'button', onclick: async () => { await api.post(`/api/design/delete-requests/${r.id}/reject`, {}); draw(); } }, 'Reddet')))
      : h('div', { class: 'muted' }, 'Bekleyen silme talebi yok.'));
  };
  draw();
  modal({ title: 'Silme Talepleri', wide: true, body: list, actions: [{ label: 'Kapat' }] });
}

// ---------- STEP dosyası indirme (ilerlemeli) ve 3B önizleme resmi üretimi (arka planda, sırayla) ----------
async function fetchStep(vid, onProgress) {
  const resp = await fetch(`/api/design/file?v=${vid}`, { credentials: 'same-origin' });
  if (!resp.ok) throw new Error('Dosya alınamadı');
  const total = +resp.headers.get('content-length') || 0;
  if (!resp.body || !resp.body.getReader) return resp.arrayBuffer();
  const reader = resp.body.getReader(), parts = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value); got += value.length;
    onProgress?.(total ? got / total : null, got, total);
  }
  const out = new Uint8Array(got); let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out.buffer;
}
const thumbJobs = new Map();   // vid → Promise<url>
function makeThumb(vid) {
  if (thumbJobs.has(vid)) return thumbJobs.get(vid);
  const job = (async () => {
    const buf = await fetchStep(vid);
    const host = h('div', { style: { position: 'fixed', left: '-2000px', top: '0', width: '480px', height: '360px' } });
    document.body.append(host);
    let v = null;
    try {
      v = await viewStep(host, buf);
      const dataUrl = v.snapshot(480, 360);
      const blob = await (await fetch(dataUrl)).blob();
      const fd = new FormData(); fd.append('file', blob, `step-${vid}.png`);
      const r = await upload(`/api/design/versions/${vid}/thumb`, fd);
      return r.thumb;
    } finally { v?.dispose(); host.remove(); }
  })();
  thumbJobs.set(vid, job);
  job.catch(() => {}).finally(() => thumbJobs.delete(vid));
  return job;
}

// ---------- Proje: montaj / çizim kartları (yalnız 3B önizleme + ad) ----------
function montajCard(d, pid) {
  const cur = d.current;
  const thumb = h('div', { class: 'dz-mcard-thumb' });
  const spin = h('div', { class: 'dz-mcard-spin small muted' }, '3B önizleme hazırlanıyor…');
  const draw = url => {
    if (url) clear(thumb, h('img', { src: url, alt: d.name, loading: 'lazy' }));
    else if (cur && isImg(cur.file_name)) clear(thumb, h('img', { src: `/api/design/file?v=${cur.id}`, alt: d.name, loading: 'lazy' }));
    else clear(thumb, h('span', { class: 'dz-mcard-ico', style: { color: KIND_COLOR[d.kind] || '#5d6879' } }, kindGlyph(d.kind)));
  };
  draw(cur && cur.thumb_path ? `/api/design/file?t=${cur.id}` : null);
  if (cur && isStep(cur.file_name) && !cur.thumb_path) {   // STEP var, önizleme yok → arka planda üret
    thumb.append(spin);
    makeThumb(cur.id).then(url => draw(`${url}&r=${Date.now()}`)).catch(() => { spin.textContent = 'Önizleme alınamadı'; });
  }
  return h('a', { class: 'card dz-mcard', href: `#/design/${pid}/${d.id}`, title: 'Montaj detayı: 3B görünüm, eşleştirme, CFD' },
    thumb,
    h('div', { class: 'dz-mcard-body' },
      h('b', { class: 'dz-mcard-name' }, d.name),
      h('div', { class: 'small muted' }, h('span', { class: `badge ${KIND_BADGE[d.kind] || 'gray'}` }, KIND[d.kind] || 'Çizim'), cur ? ` v${cur.version}` : ' sürüm yok',
        d.product_code ? h('span', { class: 'dz-mcard-prod' }, ` · ↔ ${d.product_code}`) : null)));
}

async function renderProject(view, pid, ctx) {
  const body = h('div');
  const load = async () => {
    let p;
    try { p = await api.get(`/api/design/projects/${pid}`); } catch (err) { return clear(view, pageHead('Endüstriyel Tasarım', { back: '#/design' }), h('div', { class: 'card empty' }, err.message)); }
    const acts = designActions(pid, load, ctx.user.master);
    clear(view,
      pageHead(p.name, { back: '#/design', sub: p.description || 'Tasarım projesi' }),
      moduleToolbar(h('button', { class: 'btn primary', onclick: () => acts.addDrawing() }, '+ Montaj / Çizim Ekle')),
      body);
    const flat = []; const walk = ns => ns.forEach(n => { flat.push(n); walk(n.children || []); }); walk(p.tree || []);
    clear(body, flat.length ? h('div', { class: 'dz-grid' }, flat.map(d => montajCard(d, pid)))
      : h('div', { class: 'card empty' }, 'Bu projede çizim yok. “+ Montaj / Çizim Ekle” ile ekleyin.'));
  };
  load();
}

// ---------- Ortak işlemler (proje kartları + detay sayfası) ----------
function designActions(pid, reload, isMaster) {
  function addDrawing() {
    const name = h('input', { class: 'input', placeholder: 'Montaj / çizim adı' });
    const kind = h('select', { class: 'input' }, h('option', { value: 'assembly' }, 'Montaj Çizimi'), h('option', { value: 'drawing' }, 'Çizim'), h('option', { value: 'part' }, 'Parça'));
    modal({
      title: 'Montaj / Çizim Ekle', body: h('div', null, field('Ad', name), field('Tür', kind)),
      actions: [{ label: 'Vazgeç' }, { label: 'Ekle', class: 'primary', onClick: async () => {
        if (!name.value.trim()) throw new Error('Ad girin');
        const r = await api.post(`/api/design/projects/${pid}/drawings`, { name: name.value, kind: kind.value, parent_id: null });
        toast('Eklendi'); if (r && r.id) location.hash = `#/design/${pid}/${r.id}`; else reload();
      } }],
    });
  }

  // Yeni sürüm: yükleme ilerlemesi + STEP ise arka planda 3B önizleme
  function newVersion(d) {
    const fileIn = h('input', { type: 'file', class: 'input', accept: '.pdf,.dwg,.dxf,.step,.stp,.stl,.igs,.iges,.png,.jpg,.jpeg,.webp,.zip,.doc,.docx,.xls,.xlsx' });
    const note = h('textarea', { class: 'input', rows: 3, placeholder: 'Bu sürümde ne değişti? (açıklama)' });
    const bar = h('i'), pct = h('b', null, '%0'), prog = h('div', { class: 'progress-line', hidden: true }, h('div', { class: 'progress grow' }, bar), pct);
    const status = h('div', { class: 'small muted', hidden: true });
    modal({
      title: `${d.name} · ${d.version_count ? 'Yeni Sürüm' : 'Dosya Yükle'}`,
      body: h('div', null,
        d.version_count ? h('p', { class: 'small muted', style: { marginTop: 0 } }, t('Mevcut sürüm v{a} geçmişte saklanır; bu yükleme v{b} olur.', { a: d.current ? d.current.version : d.version_count, b: (d.current ? d.current.version : d.version_count) + 1 })) : null,
        field('Çizim dosyası', fileIn), field('Açıklama', note), prog, status),
      actions: [{ label: 'Vazgeç' }, { label: 'Yükle', class: 'primary', onClick: async ({ button }) => {
        const f = fileIn.files[0];
        if (!f) throw new Error('Dosya seçin');
        const fd = new FormData(); fd.append('file', f); fd.append('note', note.value);
        prog.hidden = false; status.hidden = false; status.textContent = t('Yükleniyor… ({s})', { s: fmtSize(f.size) }); button.textContent = 'Yükleniyor…';
        const r = await upload(`/api/design/drawings/${d.id}/version`, fd, p => { bar.style.width = `${p}%`; pct.textContent = `%${p}`; });
        toast('Sürüm yüklendi', 'success');
        if (isStep(f.name) && r && r.id) {
          status.textContent = '3B önizleme hazırlanıyor (CAD çekirdeği çözümlüyor, büyük dosyalarda 1 dk sürebilir)…'; bar.style.width = '100%'; pct.textContent = '3B';
          try { await makeThumb(r.id); } catch { /* önizleme olmadan da devam */ }
        }
        reload();
      } }],
    });
  }

  async function del(d) {
    const msg = isMaster ? t('“{name}” tüm sürümleri, eşleştirmeleri ve notlarıyla silinsin mi?', { name: d.name }) : t('“{name}” için silme talebi Master onayına gönderilsin mi?', { name: d.name });
    if (!await confirmDialog(isMaster ? 'Montajı sil' : 'Silme talebi', msg, { okLabel: isMaster ? 'Sil' : 'Talep Gönder', danger: true })) return;
    try { const r = await api.del(`/api/design/drawings/${d.id}`); toast(r.requested ? 'Silme talebi Master onayına gönderildi' : 'Silindi'); if (!r.requested) location.hash = `#/design/${pid}`; else reload(); } catch (err) { toastError(err); }
  }

  function notesPanel(d) {
    const list = h('div', { class: 'dz-notes' });
    const ta = h('textarea', { class: 'input', rows: 2, placeholder: 'Not ekle…' });
    const draw = async () => {
      let ns; try { ns = await api.get(`/api/design/drawings/${d.id}/notes`); } catch { return; }
      clear(list, ns.length ? ns.map(n => h('div', { class: 'dz-note-row' },
        h('div', { class: 'grow' }, h('div', null, n.note), h('div', { class: 'small muted' }, `${fmtDateTime(n.created_at)} · ${n.by_name || ''}`)),
        h('button', { class: 'btn xs ghost danger-text', type: 'button', title: 'Sil', onclick: async () => { await api.del(`/api/design/notes/${n.id}`); draw(); } }, '×')))
        : h('div', { class: 'muted' }, 'Henüz not yok.'));
    };
    const add = async () => { if (!ta.value.trim()) return; try { await api.post(`/api/design/drawings/${d.id}/notes`, { note: ta.value }); ta.value = ''; draw(); } catch (err) { toastError(err); } };
    draw();
    return h('div', { class: 'dz-notes-panel card' }, h('div', { class: 'cl-set-add' }, ta, h('button', { class: 'btn primary', type: 'button', onclick: add }, 'Ekle')), list);
  }
  function notesModal(d) { modal({ title: t('{name} · Notlar', { name: d.name }), wide: true, body: notesPanel(d), actions: [{ label: 'Kapat' }] }); }

  // Montaj genel bilgileri (kalkış ağırlığı, faydalı yük…)
  function specsModal(d, onSaved) {
    const sp = d.specs || {};
    const num = (k, ph) => h('input', { class: 'input', type: 'number', step: 'any', min: '0', value: sp[k] ?? '', placeholder: ph });
    const F = { mtow_g: num('mtow_g', 'g'), payload_g: num('payload_g', 'g'), empty_g: num('empty_g', 'g (boşsa basılan parçalardan)'), wingspan_mm: num('wingspan_mm', 'mm'), length_mm: num('length_mm', 'mm'),
      cruise_kmh: num('cruise_kmh', 'km/sa'), endurance_min: num('endurance_min', 'dk'), battery: h('input', { class: 'input', value: sp.battery || '', placeholder: 'ör. 6S 5000 mAh' }), notes: h('textarea', { class: 'input', rows: 2 }, sp.notes || '') };
    modal({ title: t('{name} · Montaj Bilgileri', { name: d.name }), wide: true,
      body: h('div', { class: 'dz-spec-form' },
        field('Toplam kalkış ağırlığı (MTOW)', F.mtow_g), field('Faydalı yük (payload)', F.payload_g), field('Boş ağırlık', F.empty_g),
        field('Kanat açıklığı', F.wingspan_mm), field('Uzunluk', F.length_mm), field('Seyir hızı', F.cruise_kmh), field('Uçuş süresi', F.endurance_min), field('Batarya', F.battery), field('Notlar', F.notes)),
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        const specs = Object.fromEntries(Object.entries(F).map(([k, el]) => [k, el.value]));
        const r = await api.put(`/api/design/drawings/${d.id}/specs`, { specs }); toast('Kaydedildi', 'success'); onSaved?.(r.specs);
      } }] });
  }

  return { addDrawing, newVersion, del, notesModal, notesPanel, specsModal };
}

// ---------- Montaj detayı: genel bilgiler + 3B Görünüm / CFD Analizi ----------
async function renderDetail(view, pid, did, vid, ctx) {
  const isMaster = ctx.user.master;
  let d;
  try { d = await api.get(`/api/design/drawings/${did}`); } catch (err) { return clear(view, pageHead('Endüstriyel Tasarım', { back: `#/design/${pid}` }), h('div', { class: 'card empty' }, err.message)); }
  const cur = vid && d.current && d.current.id !== vid ? await api.get(`/api/design/drawings/${did}/versions`).then(vs => vs.find(v => v.id === vid) || d.current).catch(() => d.current) : d.current;
  const reloadInfo = async () => { try { d = await api.get(`/api/design/drawings/${did}`); drawInfo(); } catch { /* */ } };
  const acts = designActions(pid, reloadInfo, isMaster);
  const infoEl = h('div', { class: 'dz-info card' });
  const stage = h('div', { class: 'stp-stage-in' });
  let tab = 'view', studio = null;

  const tile = (label, value, sub) => h('div', { class: 'dz-tile' }, h('div', { class: 'dz-tile-l' }, label), h('div', { class: 'dz-tile-v' }, value), sub ? h('div', { class: 'small muted' }, sub) : null);
  const dd = () => ({ id: did, name: d.name, current: d.current, version_count: d.version_count, specs: d.specs });
  const subEl = h('div', { class: 'sub' });
  const drawInfo = () => {
    const sp = d.specs || {}, st = d.stats || {};
    subEl.textContent = d.product ? `${d.product.code} — ${d.product.name}` : 'Mamul eşleştirilmedi';
    const mamulSel = h('select', { class: 'input sm', 'aria-label': 'Mamul' }, h('option', { value: '' }, '— mamul seçin —'), (d.mamuls || []).map(m => h('option', { value: m.id, selected: d.product && d.product.id === m.id }, `${m.code} — ${m.name}`)));
    mamulSel.addEventListener('change', async () => {
      try { await api.put(`/api/design/drawings/${did}/product`, { product_id: mamulSel.value ? Number(mamulSel.value) : null }); toast(mamulSel.value ? 'Montaj mamul ile eşleştirildi' : 'Mamul eşleşmesi kaldırıldı', 'success'); await reloadInfo(); studio?.reloadLinks(); } catch (err) { toastError(err); }
    });
    const empty = sp.empty_g ?? (st.printed_weight_g || null);
    const upBtn = h('button', { class: 'btn xs ghost', type: 'button', onclick: () => acts.newVersion(dd()) }, cur ? '⬆ STEP değiştir' : '⬆ STEP yükle');
    clear(infoEl,
      h('div', { class: 'dz-info-head small muted' }, cur ? `v${cur.version} · ${cur.file_name}${cur.size ? ` · ${fmtSize(cur.size)}` : ''} · ${fmtDateTime(cur.created_at)}` : 'Henüz dosya yüklenmedi', upBtn),
      h('div', { class: 'dz-tiles' },
        tile('Eşleştirilen mamul', mamulSel),
        tile('Toplam kalkış ağırlığı', fmtNum(sp.mtow_g, 'g'), 'MTOW'),
        tile('Faydalı yük', fmtNum(sp.payload_g, 'g'), 'payload'),
        tile('Boş ağırlık', fmtNum(empty, 'g', 1), sp.empty_g != null ? null : (st.printed_weight_g ? t('{n} eşleşen parçanın G-code ağırlığı', { n: st.weighed }) : null)),
        tile('Uçuş süresi', fmtNum(sp.endurance_min, 'dk'), sp.cruise_kmh ? t('seyir {v} km/sa', { v: fmtNum(sp.cruise_kmh) }) : null),
        tile('Eşleşen parça', fmtNum(st.linked), st.print_minutes ? t('toplam baskı ≈ {h} sa', { h: (st.print_minutes / 60).toFixed(1) }) : null)));
  };
  drawInfo();

  const fsBtn = h('button', { class: 'btn sm ghost', type: 'button', title: 'Tam ekran' }, '⛶ Tam ekran');
  fsBtn.addEventListener('click', () => {
    if (!document.fullscreenElement) (stage.requestFullscreen || stage.webkitRequestFullscreen)?.call(stage);
    else (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
  });
  const onFs = () => { fsBtn.textContent = document.fullscreenElement ? '⛶ Tam ekrandan çık' : '⛶ Tam ekran'; setTimeout(() => studio?.resize(), 60); };
  document.addEventListener('fullscreenchange', onFs);
  onLeave(() => { document.removeEventListener('fullscreenchange', onFs); studio?.dispose(); });

  const notesEl = h('div', { hidden: true }, acts.notesPanel(dd()));
  const showTab = k => { tab = k; notesEl.hidden = k !== 'notes'; fsBtn.hidden = k === 'notes'; studio?.showTab(k); };
  const tabsEl = moduleTabs([['view', '🧊 3B Görünüm'], ['cfd', '🌬 CFD Analizi'], ['notes', `📝 Notlar${d.note_count ? ` (${d.note_count})` : ''}`]], tab, showTab);
  const head = pageHead(d.name, { back: `#/design/${pid}`, right: h('div', { class: 'pill-group' },
    h('button', { class: 'btn sm', type: 'button', onclick: () => acts.specsModal(d, () => reloadInfo()) }, '✎ Bilgileri düzenle'),
    h('button', { class: 'btn sm ghost danger-text', type: 'button', onclick: () => acts.del(dd()) }, '🗑 Sil')) });
  head.querySelector('.page-head-t').append(subEl);
  const stageWrap = h('div', { class: 'stp-stage' });
  clear(view, head, infoEl, h('div', { class: 'stp-tabs-row' }, tabsEl, h('span', { class: 'spacer' }), fsBtn), stageWrap);
  stageWrap.append(stage, notesEl);

  if (!cur) clear(stage, h('div', { class: 'card empty' }, h('p', null, 'Bu montaj için henüz dosya yok.'), h('button', { class: 'btn primary', type: 'button', onclick: () => acts.newVersion(dd()) }, '⬆ STEP yükle')));
  else if (!isStep(cur.file_name)) {
    clear(stage, h('div', { class: 'card empty' }, isImg(cur.file_name) ? h('img', { src: `/api/design/file?v=${cur.id}`, alt: d.name, style: { maxWidth: '100%', borderRadius: '10px' } }) : null,
      h('p', null, '3B görünüm ve CFD için STEP (.step/.stp) sürümü gerekir.'), ...dzFileLinks('v', cur.id, cur.file_name, isMaster)));
  } else studio = stepStudio(stage, { did, vid: cur.id, name: d.name, reload: reloadInfo, specs: d.specs });
  showTab(tab);
}

// ---------- 3B stüdyo (sayfa içi): parça ağacı (düzenlenebilir), model, patlatma, karşılaştırma, ürün eşleştirme + CFD sekmesi ----------
const PTYPE = { MAMUL: 'Mamul', YARI_MAMUL: 'Yarı mamul', YEDEK_PARCA: 'Yedek parça', SARF: 'Sarf' };
// Ad/kod sadeleştirme: "L4 - V3" ↔ "L4-V3"; "O1 - V3" ↔ "01-V3" (STEP'te O harfi / üründe sıfır); boşluk, Türkçe İ, satır sonu
const normCode = s => (s || '').replace(/[\r\n]/g, '').toLocaleUpperCase('tr').replace(/İ/g, 'I').replace(/[\s_]+/g, '').replace(/-+/g, '-');
const codeVariants = s => { const n = normCode(s); const z = n.replace(/O(?=\d)/g, '0'), o = n.replace(/\b0(?=\d)/g, 'O'); return [...new Set([n, z, o])]; };

function stepStudio(host, { did, vid, name, reload, specs }) {
  // ---- yükleme ilerlemesi
  const bar = h('i'), pct = h('b', null, '%0'), phase = h('div', { class: 'small muted' }, 'Dosya indiriliyor…');
  const loader = h('div', { class: 'stp-loader' }, h('div', { class: 'progress-line' }, h('div', { class: 'progress grow' }, bar), pct), phase);
  const canvas = h('div', { class: 'stp-canvas' }, loader);
  const treeEl = h('div', { class: 'stp-tree' }, h('div', { class: 'small muted', style: { padding: '8px' } }, 'Parçalar okunuyor…'));
  const selName = h('b', { class: 'stp-sel-name' }, 'Parça seçilmedi');
  const selLink = h('span', { class: 'small muted' }, '');
  const candFilter = h('input', { class: 'input', placeholder: 'Ürün ara (kod / ad)…', 'aria-label': 'Ürün ara' });
  const candSel = h('select', { class: 'input', 'aria-label': 'Eşleşecek ürün' });
  const saveBtn = h('button', { class: 'btn sm primary', type: 'button', disabled: true }, 'Eşleştir');
  const unlinkBtn = h('button', { class: 'btn sm ghost danger-text', type: 'button', disabled: true }, 'Kaldır');
  const autoBtn = h('button', { class: 'btn sm', type: 'button', title: 'STEP parça adlarını ürün kodlarıyla karşılaştırıp eşleşenleri bağlar' }, '✨ Ada göre otomatik eşle');
  const range = h('input', { type: 'range', min: '0', max: '100', value: '0', class: 'stp-range', 'aria-label': 'Patlatma' });
  const rangeVal = h('span', { class: 'small muted stp-range-val' }, '%0');
  const fitBtn = h('button', { class: 'btn sm ghost', type: 'button', title: 'Kadrajı sıfırla' }, '⌖ Kadraj');
  const countChip = h('span', { class: 'small muted' }, '');
  // karşılaştırma penceresi (sol üst): solda ürünün G-code 3B'si, sağda seçili STEP parçası — ikisi de döner
  const cmpG = h('div', { class: 'stp-cmp-box' }), cmpS = h('div', { class: 'stp-cmp-box' });
  const cmpGl = h('div', { class: 'stp-cmp-l' }, 'Ürün (G-code)'), cmpSl = h('div', { class: 'stp-cmp-l' }, 'STEP parçası');
  const cmp = h('div', { class: 'stp-cmp', hidden: true }, h('div', { class: 'stp-cmp-col' }, cmpGl, cmpG), h('div', { class: 'stp-cmp-col' }, cmpSl, cmpS));
  let cmpGv = null, cmpSv = null, cmpKey = null;

  let viewer = null, links = {}, cands = [], mamul = null, selected = null, rows = {};
  const linkOf = p => links[p.key] || null;
  const collapsed = new Set();

  // ---- Ağaç düzenleme (yerel; "Kaydet" ile sunucuya): alt kırılım ekle, taşı (sürükle-bırak / Taşı), ad değiştir
  let overlay = { groups: [], parents: {}, names: {}, hidden: [] }, dirty = false;
  const checked = new Set();   // işaretli parça/kırılım anahtarları (toplu taşıma)
  const checkChip = h('button', { class: 'btn xs ghost', type: 'button', hidden: true, title: 'İşaretleri kaldır' }, '');
  const refreshCheck = () => { checkChip.hidden = !checked.size; checkChip.textContent = `☑ ${checked.size} işaretli ✕`; moveBtn.textContent = checked.size ? `⤵ Taşı (${checked.size})` : '⤵ Taşı'; moveBtn.disabled = !checked.size && !selected; };
  checkChip.addEventListener('click', () => { checked.clear(); drawTree(); refreshCheck(); });
  const treeSaveBtn = h('button', { class: 'btn xs primary', type: 'button', disabled: true, title: 'Ağaç düzenlemelerini kaydet' }, '💾 Kaydet');
  const addGrpBtn = h('button', { class: 'btn xs', type: 'button', title: 'Seçili kırılımın (ya da kökün) altına yeni alt kırılım ekle' }, '＋ Alt kırılım');
  const renameBtn = h('button', { class: 'btn xs', type: 'button', title: 'Seçili parça / kırılımın adını değiştir', disabled: true }, '✎ Ad');
  const moveBtn = h('button', { class: 'btn xs', type: 'button', title: 'Seçili parça / kırılımı başka bir kırılımın altına taşı', disabled: true }, '⤵ Taşı');
  const delGrpBtn = h('button', { class: 'btn xs ghost danger-text', type: 'button', title: 'Seçili parçayı / alt montajı ağaçtan ve modelden kaldır (gizlenenlerden geri getirilebilir); kendi eklediğiniz kırılımı kaldırır', disabled: true }, '🗑');
  const hiddenBtn = h('button', { class: 'btn xs ghost', type: 'button', hidden: true, title: 'Kaldırılan parçalar — geri getir' }, '');
  const markDirty = () => { dirty = true; treeSaveBtn.disabled = false; };
  const beforeUnload = e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
  window.addEventListener('beforeunload', beforeUnload);
  const askName = (title, value = '', hint = null) => new Promise(resolve => {
    const inp = h('input', { class: 'input', value, placeholder: 'Ad', maxlength: '200' });
    let done = false;
    modal({ title, body: field('Ad', inp, hint), onClose: () => { if (!done) resolve(null); },
      actions: [{ label: 'Vazgeç' }, { label: 'Tamam', class: 'primary', onClick: () => { if (!inp.value.trim()) throw new Error('Ad girin'); done = true; resolve(inp.value.trim()); } }] });
    inp.addEventListener('keydown', e => { if (e.key === 'Enter' && inp.value.trim()) inp.closest('.modal-back')?.querySelector('.modal-foot .primary')?.click(); });
  });
  const applyTree = () => { if (!viewer) return; viewer.rebuild(overlay); drawTree(); onSelect(viewer.selected); };
  const isDesc = (node, anc) => { for (let a = node; a; a = a.parent) if (a === anc) return true; return false; };
  const moveSet = node => (checked.size ? viewer.nodes.filter(n => checked.has(n.key)) : (node ? [node] : []));   // işaretliler varsa onlar, yoksa verilen düğüm
  const moveTo = (node, targetKey) => {
    if (!viewer) return;
    const target = targetKey === 'root' ? viewer.root : viewer.nodes.find(n => n.key === targetKey);
    if (!target || target.kind !== 'group') return;
    let moved = 0;
    for (const n of moveSet(node)) {
      if (n === target || isDesc(target, n) || target === n.parent) continue;
      const g = overlay.groups.find(x => x.key === n.key);
      if (g) g.parent = target === viewer.root ? null : target.key; else overlay.parents[n.key] = target === viewer.root ? null : target.key;
      moved++;
    }
    if (!moved) return;
    checked.clear(); collapsed.delete(target.key); markDirty(); applyTree(); refreshCheck();
    toast(t('{n} öğe “{g}” altına taşındı', { n: moved, g: target.name }));
  };
  addGrpBtn.addEventListener('click', async () => {
    if (!viewer) return;
    const parent = selected ? (selected.kind === 'group' ? selected : selected.parent) : viewer.root;
    const nm = await askName(t('Yeni alt kırılım — “{p}” altına', { p: parent.name }), '', checked.size ? t('İşaretli {n} parça bu kırılımın içine alınır.', { n: checked.size }) : null); if (!nm) return;
    const key = `c:${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    overlay.groups.push({ key, name: nm, parent: parent && parent !== viewer.root ? parent.key : null });
    for (const k of checked) { const n = viewer.nodes.find(x => x.key === k); if (!n || n.key === key) continue; const g = overlay.groups.find(x => x.key === k); if (g) g.parent = key; else overlay.parents[k] = key; }
    checked.clear(); if (parent) collapsed.delete(parent.key);
    markDirty(); applyTree(); refreshCheck();
    const n = viewer.nodes.find(x => x.key === key); if (n) viewer.select(n);
    toast(t('“{g}” eklendi — parçaları sürükleyip ya da işaretleyip “Taşı” ile içine alın; sonra “Kaydet”.', { g: nm }));
  });
  renameBtn.addEventListener('click', async () => {
    if (!selected) return;
    const nm = await askName('Adı değiştir', selected.name); if (!nm || nm === selected.name) return;
    const g = overlay.groups.find(x => x.key === selected.key);
    if (g) g.name = nm; else overlay.names[selected.key] = nm;
    markDirty(); applyTree();
  });
  moveBtn.addEventListener('click', () => {
    if (!viewer) return;
    const set = moveSet(selected); if (!set.length) return;
    const opts = [h('option', { value: 'root' }, `⌂ ${viewer.root.name || 'Tüm montaj'}`)];
    const walk = (nodes, depth) => nodes.forEach(n => { if (n.kind !== 'group' || set.some(x => isDesc(n, x))) return; opts.push(h('option', { value: n.key }, `${'— '.repeat(depth)}${n.name}`)); walk(n.children, depth + 1); });
    walk(viewer.root.children, 0);
    const sel = h('select', { class: 'input' }, opts);
    modal({ title: set.length === 1 ? t('“{name}” → taşı', { name: set[0].name }) : t('{n} öğeyi taşı', { n: set.length }), body: field('Hedef kırılım', sel, 'Parçaları ağaçta sürükleyip bir kırılımın üstüne bırakarak da taşıyabilirsiniz; birden çok parça için satırlardaki kutuları işaretleyin.'),
      actions: [{ label: 'Vazgeç' }, { label: 'Taşı', class: 'primary', onClick: () => moveTo(selected, sel.value) }] });
  });
  delGrpBtn.addEventListener('click', async () => {
    if (!selected) return;
    const set = checked.size ? viewer.nodes.filter(n => checked.has(n.key)) : [selected];
    if (set.length === 1 && set[0].custom) {   // kendi kırılımı: içindekiler bir üste çıkar
      if (!await confirmDialog('Alt kırılımı kaldır', t('“{name}” kaldırılsın mı? İçindeki parçalar bir üst kırılıma çıkar.', { name: selected.name }), { okLabel: 'Kaldır', danger: true })) return;
      const g = overlay.groups.find(x => x.key === selected.key), up = g ? g.parent : null;
      for (const c of selected.children) { const cg = overlay.groups.find(x => x.key === c.key); if (cg) cg.parent = up; else overlay.parents[c.key] = up; }
      overlay.groups = overlay.groups.filter(x => x.key !== selected.key);
      delete overlay.parents[selected.key]; delete overlay.names[selected.key];
    } else {   // STEP'ten gelen parça / alt montaj: ağaçtan ve modelden gizlenir (dosya değişmez; geri getirilebilir)
      const names = set.map(n => n.name).slice(0, 8).join(', ') + (set.length > 8 ? '…' : '');
      if (!await confirmDialog(set.length === 1 ? 'Parçayı kaldır' : t('{n} öğeyi kaldır', { n: set.length }), t('{names}\n\nAğaçtan ve 3B modelden kaldırılsın mı? STEP dosyası değişmez; “Kaldırılanlar” listesinden geri getirebilirsiniz.', { names }), { okLabel: 'Kaldır', danger: true })) return;
      for (const n of set) { if (!overlay.hidden.includes(n.key)) overlay.hidden.push(n.key); }
      checked.clear();
    }
    markDirty(); viewer.select(null); applyTree(); refreshCheck();
  });
  hiddenBtn.addEventListener('click', () => {
    if (!viewer) return;
    const list = h('div', { class: 'dz-notes' });
    const draw = () => clear(list, viewer.hidden.length ? viewer.hidden.map(n => h('div', { class: 'dz-note-row' },
      h('div', { class: 'grow' }, h('b', null, n.name), n.kind === 'group' ? h('span', { class: 'small muted' }, t(' · alt montaj, {n} parça', { n: n.allMeshes.length })) : null),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { overlay.hidden = overlay.hidden.filter(k => k !== n.key); markDirty(); applyTree(); draw(); } }, '↩ Geri getir')))
      : h('div', { class: 'muted' }, 'Kaldırılan parça yok.'));
    draw();
    modal({ title: 'Kaldırılan parçalar', body: list, actions: [{ label: 'Kapat' }] });
  });
  treeSaveBtn.addEventListener('click', async () => {
    try {
      const r = await api.put(`/api/design/drawings/${did}/step-tree`, { tree: overlay });
      overlay = r.tree ? { hidden: [], ...r.tree } : { groups: [], parents: {}, names: {}, hidden: [] }; dirty = false; treeSaveBtn.disabled = true;
      toast('Parça ağacı kaydedildi', 'success'); applyTree();
    } catch (err) { toastError(err); }
  });
  const dnd = (row, node) => {
    row.draggable = true;
    row.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', node.key); e.dataTransfer.effectAllowed = 'move'; row.classList.add('dragging'); });
    row.addEventListener('dragend', () => row.classList.remove('dragging'));
  };
  const dropTarget = (row, targetKey) => {
    row.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; row.classList.add('drop'); });
    row.addEventListener('dragleave', () => row.classList.remove('drop'));
    row.addEventListener('drop', e => { e.preventDefault(); row.classList.remove('drop'); const k = e.dataTransfer.getData('text/plain'); const n = viewer?.nodes.find(x => x.key === k); if (n) moveTo(n, targetKey); });
  };

  // ---- Ağaç çizimi
  const drawTree = () => {
    if (!viewer) return;
    rows = {};
    const items = [];
    const walk = nodes => nodes.forEach(p => {
      const ln = linkOf(p), isG = p.kind === 'group', closed = isG && collapsed.has(p.key);
      const caret = isG ? h('span', { class: `stp-caret ${closed ? 'closed' : ''}`, title: closed ? 'Aç' : 'Kapat',
        onclick: ev => { ev.stopPropagation(); if (closed) collapsed.delete(p.key); else collapsed.add(p.key); drawTree(); } }, '▾') : h('span', { class: 'stp-dot' });
      const cb = h('input', { type: 'checkbox', class: 'stp-cb', checked: checked.has(p.key), title: 'İşaretle (toplu taşıma)', onclick: ev => { ev.stopPropagation(); if (cb.checked) checked.add(p.key); else checked.delete(p.key); row.classList.toggle('checked', cb.checked); refreshCheck(); } });
      const row = h('button', { class: `stp-row ${isG ? 'group' : ''} ${p.custom ? 'custom' : ''} ${selected && selected.key === p.key ? 'on' : ''} ${ln ? 'linked' : ''} ${checked.has(p.key) ? 'checked' : ''}`, type: 'button',
        style: { paddingLeft: `${8 + Math.max(0, p.depth - 1) * 14}px` }, title: ln ? `${p.name} ↔ ${ln.product_code} ${ln.product_name || ''}` : (isG ? t('{name} · alt montaj, {n} parça', { name: p.name, n: p.allMeshes.length }) : p.name),
        onclick: () => viewer.select(p) },
        cb, caret, h('span', { class: 'stp-row-name' }, p.custom ? [h('span', { class: 'stp-folder' }, '📁'), ' '] : null, p.name, p.dupIndex ? h('span', { class: 'muted' }, ` #${p.dupIndex}`) : null, isG ? h('span', { class: 'muted small' }, ` (${p.children.length})`) : null),
        ln ? h('span', { class: 'stp-row-code' }, ln.product_code) : null);
      dnd(row, p); if (isG) dropTarget(row, p.key);
      rows[p.key] = row; items.push(row);
      if (isG && !closed) walk(p.children);
    });
    walk(viewer.root.children);
    const n = Object.keys(links).length, g = viewer.nodes.filter(x => x.kind === 'group').length;
    countChip.textContent = t('{n} parça{g} · {m} eşleşmiş', { n: viewer.parts.length, g: g ? t(' · {g} alt montaj', { g }) : '', m: n });
    const hid = (viewer.hidden || []).length; hiddenBtn.hidden = !hid; hiddenBtn.textContent = t('🚫 Kaldırılan ({n})', { n: hid });
    const rootRow = h('button', { class: `stp-row root ${!selected ? 'on' : ''}`, type: 'button', onclick: () => viewer.select(null) }, h('span', { class: 'stp-dot' }), h('b', null, viewer.root.name || 'Tüm montaj'));
    dropTarget(rootRow, 'root');
    clear(treeEl, rootRow, items);
  };

  // Aday listesi: başka bir parçayla eşleşmiş ürünler gizlenir (seçili parçanın kendi eşleşmesi kalır); arama kutusu süzer
  const fillCands = () => {
    const q = normCode(candFilter.value), keep = selected ? linkOf(selected)?.product_id : null;
    const used = new Set(Object.values(links).map(l => l.product_id).filter(id => id !== keep));
    const list = cands.filter(c => !used.has(c.id));
    const prev = candSel.value;
    clear(candSel, h('option', { value: '' }, list.length ? '— ürün seçin —' : (mamul ? 'Bu mamulün ağacında eşleşmemiş yarı mamul kalmadı' : '— ürün seçin —')),
      list.map(c => h('option', { value: c.id, hidden: !!q && !normCode(`${c.code} ${c.name}`).includes(q) }, `${c.code} — ${c.name}${c.type && c.type !== 'YARI_MAMUL' ? ` (${PTYPE[c.type] || c.type})` : ''}`)));
    if (prev && list.some(c => String(c.id) === prev)) candSel.value = prev;
  };
  candFilter.addEventListener('input', fillCands);

  // ---- Karşılaştırma penceresi: seçili parça + (eşleşen ürün ya da listede seçilen aday)
  const updateCompare = () => {
    const p = selected;
    const prodId = candSel.value ? Number(candSel.value) : (p ? linkOf(p)?.product_id : null);
    const prod = prodId ? (cands.find(c => c.id === prodId) || Object.values(links).find(l => l.product_id === prodId)) : null;
    const key = `${p ? p.key : ''}|${prodId || ''}`;
    if (!p) { cmp.hidden = true; cmpGv?.destroy(); cmpSv?.dispose(); cmpGv = cmpSv = null; cmpKey = null; return; }
    cmp.hidden = false;
    if (key === cmpKey) return;
    cmpKey = key;
    cmpSv?.dispose(); cmpSv = viewer ? viewer.miniView(cmpS, p) : null; cmpSl.textContent = `STEP: ${p.name}`;
    cmpGv?.destroy(); cmpGv = null; clear(cmpG);
    if (prod && (prod.gcode_preview)) {
      cmpGl.textContent = `Ürün: ${prod.product_code || prod.code}`;
      gcodeViewer(cmpG, prod.gcode_preview, { autoRotate: true, interactive: false }).then(v => { if (cmpKey === key) cmpGv = v; else v.destroy(); }).catch(() => clear(cmpG, h('div', { class: 'small muted' }, 'G-code önizleme yok')));
    } else { cmpGl.textContent = prod ? `Ürün: ${prod.product_code || prod.code}` : 'Ürün seçilmedi'; clear(cmpG, h('div', { class: 'small muted stp-cmp-empty' }, prod ? 'Bu ürüne G-code yüklenmemiş' : 'Listeden ürün seçin')); }
  };
  candSel.addEventListener('change', updateCompare);

  const onSelect = p => {
    selected = p;
    let opened = false;
    for (let a = p && p.parent; a && a.parent; a = a.parent) if (collapsed.has(a.key)) { collapsed.delete(a.key); opened = true; }
    if (opened) drawTree();
    Object.values(rows).forEach(r => r.classList.remove('on'));
    if (p && rows[p.key]) { rows[p.key].classList.add('on'); rows[p.key].scrollIntoView({ block: 'nearest' }); }
    treeEl.querySelector('.stp-row.root')?.classList.toggle('on', !p);
    const ln = p ? linkOf(p) : null;
    selName.textContent = p ? `${p.name}${p.kind === 'group' ? t(' (alt montaj · {n} parça)', { n: p.allMeshes.length }) : ''}` : 'Parça seçilmedi';
    selLink.textContent = p ? (ln ? `↔ ${ln.product_code} — ${ln.product_name || ''}` : 'Henüz ürünle eşleştirilmedi') : 'Soldaki listeden ya da modelden bir parçaya dokunun.';
    saveBtn.disabled = !p; unlinkBtn.disabled = !(p && ln);
    renameBtn.disabled = !p; moveBtn.disabled = !p && !checked.size; delGrpBtn.disabled = !p;
    fillCands();
    candSel.value = ln ? String(ln.product_id) : '';
    if (p && !ln) { const guess = guessFor(p); if (guess) candSel.value = String(guess.id); }
    updateCompare();
  };
  const guessFor = p => {
    const vs = codeVariants(p.name), used = new Set(Object.values(links).map(l => l.product_id));
    return cands.find(c => !used.has(c.id) && codeVariants(c.code).some(v => vs.includes(v))) || null;
  };

  const loadLinks = async () => {
    const r = await api.get(`/api/design/drawings/${did}/step-links`);
    links = Object.fromEntries((r.links || []).map(l => [l.mesh_key, l]));
    cands = r.candidates || []; mamul = r.product || null;
    if (!dirty) overlay = r.tree && typeof r.tree === 'object' ? { groups: r.tree.groups || [], parents: r.tree.parents || {}, names: r.tree.names || {}, hidden: r.tree.hidden || [] } : { groups: [], parents: {}, names: {}, hidden: [] };
    fillCands(); drawTree(); if (selected) onSelect(selected);
  };
  saveBtn.addEventListener('click', async () => {
    if (!selected || !candSel.value) { toast('Önce listeden ürün seçin', 'err'); return; }
    try {
      await api.put(`/api/design/drawings/${did}/step-links`, { mesh_key: selected.key, mesh_name: selected.name, product_id: Number(candSel.value) });
      toast('Eşleştirildi', 'success'); await loadLinks(); reload?.();
    } catch (err) { toastError(err); }
  });
  unlinkBtn.addEventListener('click', async () => {
    if (!selected) return;
    try { await api.put(`/api/design/drawings/${did}/step-links`, { mesh_key: selected.key, mesh_name: selected.name, product_id: null }); toast('Eşleşme kaldırıldı'); await loadLinks(); reload?.(); } catch (err) { toastError(err); }
  });
  autoBtn.addEventListener('click', async () => {
    if (!viewer) return;
    const todo = viewer.nodes.filter(p => !linkOf(p)).map(p => [p, guessFor(p)]).filter(([, g]) => g);
    if (!todo.length) { toast('Ada göre eşleşen yeni parça bulunamadı'); return; }
    if (!await confirmDialog('Otomatik eşleştirme', t('{n} parça adı ürün koduyla eşleşiyor:\n{list}\n\nBağlansın mı?', { n: todo.length, list: todo.slice(0, 12).map(([p, g]) => `${p.name} → ${g.code}`).join('\n') + (todo.length > 12 ? '\n…' : '') }), { okLabel: 'Eşleştir' })) return;
    let ok = 0;
    for (const [p, g] of todo) { try { await api.put(`/api/design/drawings/${did}/step-links`, { mesh_key: p.key, mesh_name: p.name, product_id: g.id }); ok++; } catch { /* sıradakine */ } }
    toast(t('{n} parça eşleştirildi', { n: ok }), 'success'); await loadLinks(); reload?.();
  });
  range.addEventListener('input', () => { rangeVal.textContent = `%${range.value}`; viewer?.explode(Number(range.value) / 100); });
  fitBtn.addEventListener('click', () => viewer?.fit());

  // ---- CFD sekmesi (2B kesit, kafes-Boltzmann)
  const cfdHost = h('div', { class: 'cfd-canvas-wrap' }, h('div', { class: 'small muted', style: { padding: '24px' } }, '3B model yüklenince kesit alınır.'));
  const cfdAxis = h('select', { class: 'input sm' }, h('option', { value: 'z' }, 'Üstten (X–Y düzlemi)'), h('option', { value: 'x', selected: true }, 'Yandan (Y–Z düzlemi)'), h('option', { value: 'y' }, 'Önden (X–Z düzlemi)'));
  const cfdObj = h('select', { class: 'input sm' }, h('option', { value: 'all' }, 'Tüm montaj'), h('option', { value: 'sel' }, '3B sekmesinde seçili parça'));
  const cfdFlip = h('select', { class: 'input sm' }, h('option', { value: '0' }, 'Akış → (soldan sağa)'), h('option', { value: '1' }, 'Akış ← (ters)'));
  const cfdSpeed = h('input', { type: 'range', min: '3', max: '12', value: '8', class: 'stp-range' }), cfdSpeedV = h('span', { class: 'small muted' }, '0.08');
  const cfdVisc = h('input', { type: 'range', min: '1', max: '40', value: '8', class: 'stp-range' }), cfdViscV = h('span', { class: 'small muted' }, '0.020');
  const cfdMode = h('select', { class: 'input sm' }, h('option', { value: 'speed' }, 'Hız büyüklüğü'), h('option', { value: 'curl' }, 'Girdap (curl)'), h('option', { value: 'pressure' }, 'Basınç'));
  const cfdPart = h('input', { type: 'checkbox', checked: true });
  const cfdRun = h('button', { class: 'btn sm primary', type: 'button' }, '▶ Başlat');
  const cfdReset = h('button', { class: 'btn sm', type: 'button' }, '↺ Sıfırla');
  const cfdCut = h('button', { class: 'btn sm', type: 'button', title: 'Seçili kesit/nesneyle engel maskesini yeniden al' }, '✂ Kesiti al');
  const cfdStats = h('div', { class: 'cfd-stats small muted' }, '—');
  const cfdInfo = h('div', { class: 'small muted' }, '');
  let cfd = null, cfdReady = false;
  const cfdNu = () => Number(cfdVisc.value) / 400, cfdU = () => Number(cfdSpeed.value) / 100;
  const takeCut = () => {
    if (!viewer) return;
    const node = cfdObj.value === 'sel' && selected ? selected : null;
    const sil = viewer.silhouette(node, cfdAxis.value, 220, 110, { flip: cfdFlip.value === '1' });
    if (!cfd) { clear(cfdHost); cfd = createCfdView(cfdHost, { cols: 220, rows: 110, stepsPerFrame: 6 }); cfd.opt.onStats = s => {
      cfdStats.textContent = t('adım {s} · Re ≈ {re} · u_max {um} · C_d ≈ {cd} · C_l ≈ {cl}{st}', { s: s.step, re: Math.round(s.re), um: s.vmax.toFixed(3), cd: s.cd.toFixed(2), cl: s.cl.toFixed(2), st: s.stable ? '' : ' · ⚠ kararsız: hızı düşürün ya da viskoziteyi artırın' });
    }; }
    cfd.setSpeed(cfdU()); cfd.setViscosity(cfdNu()); cfd.setObstacle(sil.mask); cfd.opt.mode = cfdMode.value; cfd.opt.particles = cfdPart.checked;
    cfdInfo.textContent = sil.bbox ? t('Kesit: {n} · {w}×{h} mm · hücre ≈ {c} mm · dolu hücre {f}', { n: node ? node.name : 'tüm montaj', w: sil.bbox.width.toFixed(0), h: sil.bbox.height.toFixed(0), c: sil.cell.toFixed(1), f: sil.fill }) : 'Kesit boş';
    cfdReady = true;
  };
  cfdRun.addEventListener('click', () => { if (!cfd) takeCut(); if (!cfd) return; cfd.opt.running = !cfd.opt.running; cfdRun.textContent = cfd.opt.running ? '⏸ Duraklat' : '▶ Başlat'; });
  cfdReset.addEventListener('click', () => { cfd?.reset(); });
  cfdCut.addEventListener('click', takeCut);
  cfdSpeed.addEventListener('input', () => { cfdSpeedV.textContent = cfdU().toFixed(2); cfd?.setSpeed(cfdU()); });
  cfdVisc.addEventListener('input', () => { cfdViscV.textContent = cfdNu().toFixed(3); cfd?.setViscosity(cfdNu()); });
  cfdMode.addEventListener('change', () => { if (cfd) cfd.opt.mode = cfdMode.value; });
  cfdPart.addEventListener('change', () => { if (cfd) cfd.opt.particles = cfdPart.checked; });
  const cfd2dPanel = h('div', { class: 'cfd-panel' },
    h('div', { class: 'cfd-ctl' },
      field('Kesit düzlemi', cfdAxis), field('Nesne', cfdObj), field('Akış yönü', cfdFlip),
      field('Giriş hızı (kafes)', h('div', { class: 'progress-line' }, cfdSpeed, cfdSpeedV)),
      field('Viskozite (kafes)', h('div', { class: 'progress-line' }, cfdVisc, cfdViscV)),
      field('Görünüm', cfdMode), h('label', { class: 'small', style: { display: 'flex', gap: '6px', alignItems: 'center' } }, cfdPart, 'Akım izleyici parçacıklar'),
      h('div', { class: 'stp-bar' }, cfdCut, cfdRun, cfdReset),
      h('p', { class: 'small muted', style: { marginTop: '10px' } }, '2B kesit, kafes-Boltzmann (D2Q9) yaklaşık çözüm — anlık ön izleme içindir; katsayılar boyutsuz kafes birimindedir.')),
    h('div', { class: 'cfd-view' }, cfdHost, cfdInfo, cfdStats));

  // ---- 3B CFD (OpenFOAM, sunucuda): STL dışa aktar → analiz kuyruğu → ilerleme/yakınsama → sonuçlar (katsayılar, yüzey Cp, kesitler, akım çizgileri)
  const sp = specs || {};
  const ofStatus = h('div', { class: 'small muted' }, 'Çözücü durumu alınıyor…');
  const inU = h('input', { class: 'input', type: 'number', step: 'any', min: '0.5', max: '200', value: sp.cruise_kmh ? (Number(sp.cruise_kmh) / 3.6).toFixed(1) : '20' });
  const inAoa = h('input', { class: 'input', type: 'number', step: 'any', min: '-30', max: '30', value: '0' });
  const axisOpts = sel => [['+x', '+X'], ['-x', '−X'], ['+y', '+Y'], ['-y', '−Y'], ['+z', '+Z'], ['-z', '−Z']].map(([v, l]) => h('option', { value: v, selected: v === sel }, l));
  const inNose = h('select', { class: 'input' }, axisOpts('+x'));
  const inUp = h('select', { class: 'input' }, axisOpts('+z'));
  const inScope = h('select', { class: 'input' }, h('option', { value: 'all' }, 'Tüm montaj (gizlenenler hariç)'), h('option', { value: 'sel' }, '3B sekmesinde seçili parça / kırılım'));
  const inRes = h('select', { class: 'input' }, h('option', { value: 'coarse', selected: true }, 'Kaba — hızlı (≈ 0,3–1 M hücre)'), h('option', { value: 'medium' }, 'Orta (≈ 1–3 M hücre)'), h('option', { value: 'fine' }, 'İnce — uzun (≈ 3–8 M hücre)'));
  const inRho = h('input', { class: 'input', type: 'number', step: 'any', value: '1.225' }), inNu = h('input', { class: 'input', type: 'number', step: 'any', value: '0.000015' }), inTi = h('input', { class: 'input', type: 'number', step: 'any', value: '1' });
  const inIters = h('input', { class: 'input', type: 'number', step: '1', min: '20', max: '3000', placeholder: 'otomatik' });
  const startBtn = h('button', { class: 'btn primary', type: 'button' }, '▶ 3B analizi başlat');
  const upBar = h('i'), upPct = h('b', null, ''), upLine = h('div', { class: 'progress-line', hidden: true }, h('div', { class: 'progress grow' }, upBar), upPct);
  const runSel = h('select', { class: 'input', 'aria-label': 'Analiz' });
  const runRefresh = h('button', { class: 'btn xs ghost', type: 'button', title: 'Yenile' }, '↻');
  const runCancel = h('button', { class: 'btn xs ghost danger-text', type: 'button', hidden: true }, '⏹ Durdur');
  const runDel = h('button', { class: 'btn xs ghost danger-text', type: 'button', hidden: true, title: 'Analizi ve dosyalarını sil' }, '🗑');
  const stBadge = h('span', { class: 'badge gray' }, '—'), stPhase = h('span', { class: 'small muted' }, ''), stBar = h('i'), stPct = h('b', null, ''), stLine = h('div', { class: 'progress-line' }, h('div', { class: 'progress grow' }, stBar), stPct);
  const stInfo = h('div', { class: 'small muted' }, '');
  const resTable = h('div', { class: 'cfd-res' });
  const plotResid = h('canvas', { class: 'cfd-plot', width: 560, height: 170 }), plotCoef = h('canvas', { class: 'cfd-plot', width: 560, height: 150 });
  const vizHost = h('div', { class: 'cfd3d-view' }, h('div', { class: 'small muted', style: { padding: '24px' } }, 'Sonuç yok. Analiz bitince gövde, kesitler ve akım çizgileri burada görünür.'));
  const legend = h('canvas', { class: 'cfd-legend', width: 260, height: 44 });
  const vizField = h('select', { class: 'input sm' }, h('option', { value: 'Cp' }, 'Gövde: Cp (basınç katsayısı)'), h('option', { value: 'wallShearStress' }, 'Gövde: kayma gerilmesi'), h('option', { value: 'yPlus' }, 'Gövde: y+'));
  const vizSlice = h('select', { class: 'input sm' }, h('option', { value: 'Umag' }, 'Kesitler: |U| / U∞'), h('option', { value: 'Cp' }, 'Kesitler: Cp'));
  const tog = (name, label, on = true) => { const cb = h('input', { type: 'checkbox', class: 'stp-cb', checked: on }); cb.addEventListener('change', () => viz?.show(name, cb.checked)); return h('label', { class: 'small cfd-tog' }, cb, label); };
  const togBody = tog('body', 'Gövde'), togSide = tog('slice_side', 'Yan kesit'), togTop = tog('slice_top', 'Üst kesit', false), togLines = tog('lines', 'Akım çizgileri');
  const vizFit = h('button', { class: 'btn xs ghost', type: 'button' }, '⌖ Gövde'), vizFitAll = h('button', { class: 'btn xs ghost', type: 'button' }, '⌖ Tümü');
  const logPre = h('pre', { class: 'cfd-log' }, '');
  let runs = [], curRun = null, viz = null, pollT = null, vizLoadedFor = null;

  const fmtN = (v, d = 3) => (v == null || Number.isNaN(v)) ? '—' : Number(v).toLocaleString('tr-TR', { maximumFractionDigits: d });
  const plot = (cv, series, { log = false, xlabel = '' } = {}) => {
    const g = cv.getContext('2d'), W = cv.width, H = cv.height, L = 44, B = 22, T = 8, R = 8;
    g.clearRect(0, 0, W, H); g.fillStyle = '#fff'; g.fillRect(0, 0, W, H);
    const all = series.filter(s => s.y && s.y.length);
    if (!all.length) { g.fillStyle = '#94a3b8'; g.font = '12px system-ui'; g.fillText('veri yok', L, H / 2); return; }
    const xs = all.flatMap(s => s.x), ys = all.flatMap(s => s.y.filter(v => v != null && (!log || v > 0)));
    const x0 = Math.min(...xs), x1 = Math.max(...xs) || 1; let y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (log) { y0 = Math.log10(Math.max(y0, 1e-12)); y1 = Math.log10(Math.max(y1, 1e-12)); }
    if (y1 - y0 < 1e-9) { y0 -= 0.5; y1 += 0.5; }
    const X = x => L + (x - x0) / (x1 - x0 || 1) * (W - L - R), Y = y => T + (1 - ((log ? Math.log10(Math.max(y, 1e-12)) : y) - y0) / (y1 - y0)) * (H - T - B);
    g.strokeStyle = '#e2e8f0'; g.lineWidth = 1;
    for (let i = 0; i <= 4; i++) { const yy = T + i * (H - T - B) / 4; g.beginPath(); g.moveTo(L, yy); g.lineTo(W - R, yy); g.stroke(); }
    g.fillStyle = '#64748b'; g.font = '10px system-ui'; g.textAlign = 'right';
    for (let i = 0; i <= 4; i++) { const v = y1 - i * (y1 - y0) / 4; g.fillText(log ? `1e${v.toFixed(1)}` : v.toPrecision(3), L - 4, T + i * (H - T - B) / 4 + 3); }
    g.textAlign = 'center'; g.fillText(`${Math.round(x0)}`, L, H - 6); g.fillText(`${Math.round(x1)}${xlabel ? ' ' + xlabel : ''}`, W - R - 10, H - 6);
    all.forEach((s, i) => {
      g.strokeStyle = s.color || ['#1d4ed8', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2'][i % 6]; g.lineWidth = 1.5; g.beginPath(); let started = false;
      s.x.forEach((x, k) => { const v = s.y[k]; if (v == null || (log && v <= 0)) return; const px = X(x), py = Y(v); if (!started) { g.moveTo(px, py); started = true; } else g.lineTo(px, py); });
      g.stroke(); g.fillStyle = g.strokeStyle; g.textAlign = 'left'; g.fillText(s.name, L + 6 + i * 70, T + 10);
    });
  };
  const drawRun = r => {
    curRun = r;
    const st = r.status, prm = r.params || {}, res = r.result || {};
    const total = prm.iters || 0, done = r.iters || 0;
    stBadge.textContent = { queued: 'Kuyrukta', preparing: 'Hazırlanıyor', running: 'Çalışıyor', cancelling: 'Durduruluyor', cancelled: 'Durduruldu', done: 'Tamamlandı', failed: 'Hata' }[st] || st;
    stBadge.className = `badge ${{ done: 'green', failed: 'red', running: 'blue', cancelled: 'gray' }[st] || 'gray'}`;
    const ph = { features: 'yüzey özellikleri', blockMesh: 'arka plan ağı', snappyHexMesh: 'gövde çevresi ağ (snappyHexMesh)', checkMesh: 'ağ kontrolü', simpleFoam: 'çözüm (simpleFoam, k-ω SST)', post: 'sonuçlar yazılıyor', results: 'sonuçlar işleniyor', done: 'bitti' }[r.phase] || (r.phase || '');
    stPhase.textContent = ph ? `Aşama: ${ph}` : '';
    const pct = st === 'done' ? 100 : (r.phase === 'simpleFoam' && total ? Math.min(99, 15 + Math.round(done / total * 80)) : { features: 3, blockMesh: 6, snappyHexMesh: 10, checkMesh: 14, post: 96, results: 98 }[r.phase] || 0);
    stBar.style.width = `${pct}%`; stPct.textContent = `%${pct}`;
    stInfo.textContent = [r.cells ? t('{n} hücre', { n: fmtN(r.cells, 0) }) : null, done ? t('{a} / {b} yineleme', { a: done, b: total }) : null, prm.cores ? t('{n} çekirdek', { n: prm.cores }) : null,
      r.started_at ? t('başladı {d}', { d: fmtDateTime(r.started_at) }) : null, r.finished_at ? t('bitti {d}', { d: fmtDateTime(r.finished_at) }) : null].filter(Boolean).join(' · ');
    runCancel.hidden = !['queued', 'running'].includes(st); runDel.hidden = ['running', 'cancelling'].includes(st);
    const c = res.coeffs || r.coeffs_live || null, f = res.forces || null, geo = r.geometry || {};
    const row = (k, v, sub) => h('div', { class: 'dz-tile' }, h('div', { class: 'dz-tile-l' }, k), h('div', { class: 'dz-tile-v' }, v), sub ? h('div', { class: 'small muted' }, sub) : null);
    clear(resTable, c ? h('div', { class: 'dz-tiles' },
      row('C_d', fmtN(c.Cd, 4), 'sürükleme katsayısı'), row('C_l', fmtN(c.Cl, 4), 'kaldırma katsayısı'), row('L / D', f && f.LD != null ? fmtN(f.LD, 2) : '—'),
      row('Sürükleme', f ? `${fmtN(f.drag_N, 2)} N` : '—', f ? t('{u} m/s, ρ {r}', { u: prm.U, r: prm.rho }) : null), row('Kaldırma', f ? `${fmtN(f.lift_N, 2)} N` : '—'),
      row('C_m (yunuslama)', fmtN(c.CmPitch, 4)), row('Referans alan', geo.frontal_area != null ? `${fmtN(geo.frontal_area * 1e4, 1)} cm²` : '—', 'ön izdüşüm'),
      row('Hücum açısı', `${fmtN(prm.aoa, 1)}°`), row('Ağ', r.cells ? fmtN(r.cells, 0) : '—', 'hücre'), row('Yineleme', `${done}${total ? ' / ' + total : ''}`, st === 'done' && total && done < total ? 'yakınsadı (erken durdu)' : null))
      : (st === 'failed' ? h('div', { class: 'card empty danger-text' }, h('b', null, 'Analiz başarısız: '), r.error || '') : h('div', { class: 'small muted' }, st === 'done' ? 'Katsayı verisi yok' : 'Katsayılar çözüm sırasında burada güncellenir.')));
    const rs = r.residuals;
    plot(plotResid, rs ? ['Ux', 'Uy', 'Uz', 'p', 'k', 'omega'].filter(k => rs[k]).map(k => ({ name: k, x: rs.iters, y: rs[k] })) : [], { log: true, xlabel: 'yineleme' });
    const hist = c && c.history;
    plot(plotCoef, hist ? [{ name: 'Cd', x: hist.map(x => x[0]), y: hist.map(x => x[1]) }, { name: 'Cl', x: hist.map(x => x[0]), y: hist.map(x => x[2]) }] : [], { xlabel: 'yineleme' });
    logPre.textContent = r.log || '';
    if (st === 'done' && res.files && vizLoadedFor !== r.id) loadViz(r);
    if (st !== 'done') { vizLoadedFor = null; }
  };
  const loadViz = async r => {
    vizLoadedFor = r.id;
    try {
      if (!viz) { clear(vizHost); viz = await createCfdViz(vizHost, { legend }); }
      const have = await viz.load(`/api/design/cfd/${r.id}/file?x=1`, r.result);
      viz.show('slice_top', false);
      [togBody, togSide, togTop, togLines].forEach(l => { l.hidden = !have.includes(l.querySelector('input') && { Gövde: 'body', 'Yan kesit': 'slice_side', 'Üst kesit': 'slice_top', 'Akım çizgileri': 'lines' }[l.textContent.trim()]); });
    } catch (err) { clear(vizHost, h('div', { class: 'small muted', style: { padding: '24px' } }, 'Görselleştirme yüklenemedi: ' + (err.message || err))); }
  };
  vizField.addEventListener('change', () => viz?.setField('body', vizField.value));
  vizSlice.addEventListener('change', () => viz?.setField('slice', vizSlice.value));
  vizFit.addEventListener('click', () => viz?.fitBody()); vizFitAll.addEventListener('click', () => viz?.fit());
  const loadRuns = async (selectId = null) => {
    try { runs = await api.get(`/api/design/drawings/${did}/cfd`); } catch (err) { toastError(err); return; }
    const want = selectId || (curRun && curRun.id) || (runs[0] && runs[0].id);
    clear(runSel, runs.length ? runs.map(r => h('option', { value: r.id, selected: r.id === want }, `#${r.id} · ${r.name || ''} · ${{ queued: 'kuyrukta', preparing: 'hazırlanıyor', running: 'çalışıyor', cancelling: 'durduruluyor', cancelled: 'durduruldu', done: 'tamamlandı', failed: 'hata' }[r.status] || r.status}`)) : h('option', { value: '' }, 'Henüz analiz yok'));
    if (want) await pollRun(want); else { curRun = null; clear(resTable); }
  };
  const pollRun = async id => {
    let r; try { r = await api.get(`/api/design/cfd/${id}`); } catch { return; }
    drawRun(r);
    const opt = [...runSel.options].find(o => Number(o.value) === r.id); if (opt) opt.textContent = `#${r.id} · ${r.name || ''} · ${{ queued: 'kuyrukta', preparing: 'hazırlanıyor', running: 'çalışıyor', cancelling: 'durduruluyor', cancelled: 'durduruldu', done: 'tamamlandı', failed: 'hata' }[r.status] || r.status}`;
    clearTimeout(pollT);
    if (['queued', 'preparing', 'running', 'cancelling'].includes(r.status)) pollT = setTimeout(() => pollRun(id), 4000);
  };
  runSel.addEventListener('change', () => { if (runSel.value) pollRun(Number(runSel.value)); });
  runRefresh.addEventListener('click', () => loadRuns());
  runCancel.addEventListener('click', async () => { if (!curRun) return; try { await api.post(`/api/design/cfd/${curRun.id}/cancel`, {}); toast('Durduruluyor'); pollRun(curRun.id); } catch (err) { toastError(err); } });
  runDel.addEventListener('click', async () => { if (!curRun || !await confirmDialog('Analizi sil', t('#{id} analizi ve dosyaları silinsin mi?', { id: curRun.id }), { okLabel: 'Sil', danger: true })) return; try { await api.del(`/api/design/cfd/${curRun.id}`); curRun = null; loadRuns(); } catch (err) { toastError(err); } });
  startBtn.addEventListener('click', async () => {
    if (!viewer) { toast('Önce 3B model yüklensin', 'err'); return; }
    const node = inScope.value === 'sel' ? selected : null;
    if (inScope.value === 'sel' && !node) { toast('3B sekmesinde bir parça / kırılım seçin', 'err'); return; }
    const U = Number(inU.value); if (!(U >= 0.5 && U <= 200)) { toast('Akış hızı 0,5–200 m/s olmalı', 'err'); return; }
    startBtn.disabled = true; upLine.hidden = false; upBar.style.width = '0%'; upPct.textContent = 'STL';
    try {
      const stl = viewer.exportStl(node, { nose: inNose.value, up: inUp.value, aoa: Number(inAoa.value) || 0, scale: 0.001 });
      if (!stl.triangles) throw new Error('Dışa aktarılacak gövde yok');
      const fd = new FormData(); fd.append('file', new Blob([stl.buffer], { type: 'application/octet-stream' }), 'body.stl');
      fd.append('params', JSON.stringify({ U, rho: Number(inRho.value) || 1.225, nu: Number(inNu.value) || 1.5e-5, turb_intensity: (Number(inTi.value) || 1) / 100, res: inRes.value, aoa: Number(inAoa.value) || 0,
        nose: inNose.value, up: inUp.value, scope: inScope.value, scope_name: node ? node.name : '', iters: inIters.value ? Number(inIters.value) : null, version_id: vid,
        name: `${node ? node.name : name} · ${U} m/s · ${Number(inAoa.value) || 0}° · ${inRes.selectedOptions[0].textContent.split(' ')[0]}` }));
      const r = await upload(`/api/design/drawings/${did}/cfd`, fd, p => { upBar.style.width = `${p}%`; upPct.textContent = `%${p}`; });
      toast(t('Analiz #{id} kuyruğa alındı ({n} üçgen, gövde {l} m)', { id: r.id, n: stl.triangles.toLocaleString('tr-TR'), l: (r.geometry.size[0]).toFixed(2) }), 'success');
      await loadRuns(r.id);
    } catch (err) { toastError(err); } finally { startBtn.disabled = false; upLine.hidden = true; }
  });
  api.get('/api/design/cfd/status').then(s => {
    ofStatus.textContent = s.available ? t('OpenFOAM v2406 hazır · {n} çekirdek', { n: s.cores }) : 'OpenFOAM bu sunucuda kurulu değil — analiz başlatılamaz';
    ofStatus.classList.toggle('danger-text', !s.available); startBtn.disabled = !s.available;
  }).catch(() => { ofStatus.textContent = 'Çözücü durumu alınamadı'; });

  const cfd3dPanel = h('div', { class: 'cfd-panel' },
    h('div', { class: 'cfd-ctl' },
      ofStatus,
      field('Uçuş / akış hızı (m/s)', inU), field('Hücum açısı (°)', inAoa, 'burun yukarı +'),
      h('div', { class: 'dz-part-fields' }, field('Burun yönü (model ekseni)', inNose), field('Yukarı (model ekseni)', inUp)),
      field('Nesne', inScope), field('Ağ çözünürlüğü', inRes),
      h('details', null, h('summary', { class: 'small' }, 'Gelişmiş'), h('div', { class: 'dz-part-fields' }, field('Hava yoğunluğu (kg/m³)', inRho), field('Kinematik viskozite (m²/s)', inNu)), h('div', { class: 'dz-part-fields' }, field('Türbülans yoğunluğu (%)', inTi), field('En çok yineleme', inIters))),
      startBtn, upLine,
      h('p', { class: 'small muted', style: { marginTop: '10px' } }, 'Sunucuda OpenFOAM: snappyHexMesh ile gövde çevresinde hex ağ, simpleFoam ile kararlı RANS çözümü (k-ω SST), sınır tabaka duvar fonksiyonlu. Kaba ağda dakikalar, ince ağda saatler sürebilir.')),
    h('div', { class: 'cfd-view' },
      h('div', { class: 'stp-bar' }, runSel, runRefresh, runCancel, runDel),
      h('div', { class: 'cfd-status card' }, h('div', { class: 'stp-bar' }, stBadge, stPhase), stLine, stInfo),
      resTable,
      h('div', { class: 'cfd-plots' }, h('div', null, h('div', { class: 'small muted' }, 'Yakınsama (artık, log)'), plotResid), h('div', null, h('div', { class: 'small muted' }, 'C_d / C_l tarihçesi'), plotCoef)),
      h('div', { class: 'stp-bar' }, vizField, vizSlice, togBody, togSide, togTop, togLines, h('span', { class: 'spacer' }), vizFit, vizFitAll),
      vizHost, legend,
      h('details', null, h('summary', { class: 'small' }, 'Çözücü günlüğü'), logPre)));

  const cfdModeSel = segmented([['cfd3d', '🧮 3B Analiz (OpenFOAM)'], ['cfd2d', '⚡ Hızlı 2B ön izleme']], 'cfd3d', k => { cfd3dPanel.hidden = k !== 'cfd3d'; cfd2dPanel.hidden = k !== 'cfd2d'; if (k === 'cfd2d' && viewer && !cfdReady) takeCut(); if (k === 'cfd3d') setTimeout(() => viz?.resize(), 30); });
  cfd2dPanel.hidden = true;
  const cfdPanel = h('div', { hidden: true }, h('div', { class: 'cfd-mode' }, cfdModeSel), cfd3dPanel, cfd2dPanel);

  // ---- Yerleşim
  const viewPanel = h('div', { class: 'stp-studio' },
    h('div', { class: 'stp-main' },
      h('div', { class: 'stp-side' },
        h('div', { class: 'stp-side-head' }, h('b', null, 'Parçalar'), treeSaveBtn),
        h('div', { class: 'stp-tools' }, addGrpBtn, renameBtn, moveBtn, delGrpBtn, checkChip, hiddenBtn),
        treeEl),
      h('div', { class: 'stp-view' }, canvas, cmp,
        h('div', { class: 'stp-bar' }, h('span', { class: 'stp-lbl' }, '💥 Patlat'), range, rangeVal, fitBtn, h('span', { class: 'spacer' }), countChip))),
    h('div', { class: 'stp-sel' },
      h('div', { class: 'stp-sel-info' }, selName, selLink),
      h('div', { class: 'stp-sel-ctl' }, candFilter, candSel, saveBtn, unlinkBtn, h('span', { class: 'spacer' }), autoBtn)));
  clear(host, viewPanel, cfdPanel);

  // ---- Model yükleme (ilerleme: indirme yüzdesi → CAD çözümleme)
  (async () => {
    try {
      const [buf] = await Promise.all([
        fetchStep(vid, (r, got, total) => { if (r != null) { bar.style.width = `${Math.round(r * 100)}%`; pct.textContent = `%${Math.round(r * 100)}`; } phase.textContent = t('Dosya indiriliyor… {a}{b}', { a: fmtSize(got), b: total ? ` / ${fmtSize(total)}` : '' }); }),
        loadLinks().catch(err => toastError(err))]);
      bar.style.width = '100%'; pct.textContent = '⚙';
      const parsed = await parseStep(buf, { onPhase: s => { phase.textContent = s; } });
      phase.textContent = 'Sahne kuruluyor…';
      clear(canvas);
      viewer = await viewStep(canvas, parsed, { onSelect, overlay });
      viewer.nodes.forEach(n => { if (n.kind === 'group' && n.depth >= 2 && !n.custom) collapsed.add(n.key); });
      drawTree(); onSelect(null);
      if (!cfdPanel.hidden && !cfd2dPanel.hidden) takeCut();
    } catch (err) { clear(canvas, h('div', { class: 'card empty' }, 'Model yüklenemedi: ' + (err.message || err))); clear(treeEl); }
  })();

  return {
    showTab(k) {
      viewPanel.hidden = k !== 'view'; cfdPanel.hidden = k !== 'cfd'; host.hidden = k === 'notes';
      if (k === 'view') setTimeout(() => viewer?.resize(), 30);
      if (k === 'cfd') { if (!runs.length && !curRun) loadRuns(); if (!cfd2dPanel.hidden && viewer && !cfdReady) takeCut(); setTimeout(() => viz?.resize(), 30); }
    },
    resize() { viewer?.resize(); },
    reloadLinks() { loadLinks().catch(() => {}); },
    get dirty() { return dirty; },
    dispose() { window.removeEventListener('beforeunload', beforeUnload); clearTimeout(pollT); cmpGv?.destroy(); cmpSv?.dispose(); cfd?.destroy(); viz?.dispose(); viewer?.dispose(); },
  };
}
