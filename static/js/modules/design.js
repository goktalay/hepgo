// Endüstriyel Tasarım: projeler → çizim / montaj çizimi ağacı → alt çizimler (parçalar) → her çizimin sürüm geçmişi.
// Her yeni dosya yüklemesi yeni sürümdür; eski sürümler (dosya + açıklama) geçmişte kalır ve açılıp görülebilir.
import { api, upload } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, moduleToolbar, pageHead, toast, toastError } from '../ui.js';
import { isStep, viewStep } from '../step3d.js';

const KIND = { assembly: 'Montaj Çizimi', drawing: 'Çizim', part: 'Parça' };
const KIND_BADGE = { assembly: 'blue', drawing: 'gray', part: 'green' };
const KIND_COLOR = { assembly: '#1d4e89', drawing: '#5d6879', part: '#16a34a' };
const isImg = n => /\.(png|jpe?g|webp|gif|bmp)$/i.test(n || '');

export async function render(view, params, ctx) {
  if (params[0] && params[1]) return renderAssembly(view, Number(params[0]), Number(params[1]), ctx);
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
  const t = document.createElement('template');
  t.innerHTML = `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M24 7v6"/><circle cx="24" cy="15" r="2.4" fill="currentColor" stroke="none"/>
    <path d="M24 17.2 14 39"/><path d="M24 17.2 34 39"/><path d="M18.8 28.4h10.4"/>
    <path d="M8 41h32"/></svg>`;
  return t.content.firstElementChild;
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
      h('div', { class: 'small muted dz-proj-meta' }, `${p.drawing_count} çizim · ${p.created_by_name || ''} · ${fmtDateTime(p.created_at)}`)));
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

// Üst seviye montaj/çizim kartı — gövdeye tıklayınca o montajın ağaç görünümü açılır; altta hızlı işlem düğmeleri
function montajCard(d, pid, acts) {
  const cur = d.current;
  const img = cur && isImg(cur.file_name);
  const kids = (d.children || []).length;
  const thumb = img
    ? h('img', { src: `/api/design/file?v=${cur.id}`, alt: d.name, loading: 'lazy' })
    : h('span', { class: 'dz-mcard-ico', style: { color: KIND_COLOR[d.kind] || '#5d6879' } }, kindGlyph(d.kind));
  return h('div', { class: 'card dz-mcard' },
    h('a', { class: 'dz-mcard-head', href: `#/design/${pid}/${d.id}`, title: 'Ağaç görünümünü aç' },
      h('div', { class: `dz-mcard-thumb ${img ? 'has-img' : ''}` }, thumb),
      h('div', { class: 'dz-mcard-info' },
        h('span', { class: `badge ${KIND_BADGE[d.kind] || 'gray'}` }, KIND[d.kind] || 'Çizim'),
        h('b', { class: 'dz-mcard-name' }, d.name),
        cur ? h('span', { class: 'dz-ver' }, `v${cur.version}`) : h('span', { class: 'small muted' }, 'sürüm yok'),
        h('div', { class: 'small muted' }, `${kids} alt çizim${d.prod_count ? ` · ${d.prod_count} parça` : ''}`),
        h('span', { class: 'dz-mcard-open' }, 'Ağacı aç →'))),
    h('div', { class: 'dz-acts' },
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => acts.newVersion(d) }, cur ? 'Yeni Sürüm' : 'Dosya Yükle'),
      d.version_count ? h('button', { class: 'btn sm', type: 'button', onclick: () => acts.history(d) }, `Geçmiş (${d.version_count})`) : null,
      h('button', { class: 'btn sm', type: 'button', title: 'Notlar', onclick: () => acts.notesModal(d) }, `📝${d.note_count ? ` ${d.note_count}` : ''}`),
      h('button', { class: 'btn sm', type: 'button', title: 'Üretim Parçaları', onclick: () => acts.partsModal(d) }, `🔩${d.prod_count ? ` ${d.prod_count}` : ''}`),
      h('button', { class: 'btn sm', type: 'button', onclick: () => acts.addDrawing(d) }, '+ Alt'),
      h('button', { class: 'btn sm ghost', type: 'button', title: 'Kopyala', onclick: () => acts.copyModal(d) }, '⧉'),
      h('button', { class: 'btn sm ghost', type: 'button', title: 'Yeniden adlandır', onclick: () => acts.rename(d) }, '✎'),
      h('button', { class: 'btn sm ghost danger-text', type: 'button', title: 'Sil', onclick: () => acts.del(d) }, '🗑')));
}

async function renderProject(view, pid, ctx) {
  const body = h('div');
  const isMaster = ctx.user.master;
  const load = async () => {
    let p;
    try { p = await api.get(`/api/design/projects/${pid}`); } catch (err) { return clear(view, pageHead('Endüstriyel Tasarım', { back: '#/design' }), h('div', { class: 'card empty' }, err.message)); }
    const acts = designActions(pid, load, isMaster);
    clear(view,
      pageHead(p.name, { back: '#/design', sub: p.description || 'Tasarım projesi' }),
      moduleToolbar(h('button', { class: 'btn primary', onclick: () => acts.addDrawing(null) }, '+ Montaj / Çizim Ekle')),
      body);
    clear(body, p.tree.length ? h('div', { class: 'dz-grid' }, p.tree.map(d => montajCard(d, pid, acts)))
      : h('div', { class: 'card empty' }, 'Bu projede çizim yok. “+ Montaj / Çizim Ekle” ile ekleyin.'));
  };
  load();
}

// Ortak düğüm işlemleri (hem üst-seviye kartlar hem ağaç görünümü kullanır). reload: liste/ağacı yeniden çizer.
function designActions(pid, reload, isMaster) {
  function addDrawing(parent) {
    const name = h('input', { class: 'input', placeholder: parent ? 'Alt çizim / parça adı' : 'Çizim / montaj adı' });
    const kind = h('select', { class: 'input' },
      h('option', { value: 'assembly' }, 'Montaj Çizimi'),
      h('option', { value: 'drawing', selected: !!parent }, 'Çizim'),
      h('option', { value: 'part' }, 'Parça'));
    modal({
      title: parent ? `${parent.name} · Alt Çizim Ekle` : 'Montaj / Çizim Ekle',
      body: h('div', null, field('Ad', name), field('Tür', kind)),
      actions: [{ label: 'Vazgeç' }, { label: 'Ekle', class: 'primary', onClick: async () => {
        if (!name.value.trim()) throw new Error('Ad girin');
        await api.post(`/api/design/projects/${pid}/drawings`, { name: name.value, kind: kind.value, parent_id: parent ? parent.id : null });
        toast('Eklendi'); reload();
      } }],
    });
  }

  function newVersion(d) {
    const fileIn = h('input', { type: 'file', class: 'input', accept: '.pdf,.dwg,.dxf,.step,.stp,.stl,.igs,.iges,.png,.jpg,.jpeg,.webp,.zip,.doc,.docx,.xls,.xlsx' });
    const note = h('textarea', { class: 'input', rows: 3, placeholder: 'Bu sürümde ne değişti? (açıklama)' });
    modal({
      title: `${d.name} · ${d.version_count ? 'Yeni Sürüm' : 'Dosya Yükle'}`,
      body: h('div', null,
        d.version_count ? h('p', { class: 'small muted', style: { marginTop: 0 } }, `Mevcut sürüm v${d.current ? d.current.version : d.version_count} geçmişte saklanır; bu yükleme v${(d.current ? d.current.version : d.version_count) + 1} olur.`) : null,
        field('Çizim dosyası', fileIn), field('Açıklama', note)),
      actions: [{ label: 'Vazgeç' }, { label: 'Yükle', class: 'primary', onClick: async () => {
        if (!fileIn.files[0]) throw new Error('Dosya seçin');
        const fd = new FormData(); fd.append('file', fileIn.files[0]); fd.append('note', note.value);
        await upload(`/api/design/drawings/${d.id}/version`, fd);
        toast('Sürüm yüklendi'); reload();
      } }],
    });
  }

  async function history(d) {
    let vs;
    try { vs = await api.get(`/api/design/drawings/${d.id}/versions`); } catch (err) { return toastError(err); }
    modal({
      title: `${d.name} · Sürüm Geçmişi`, wide: true,
      body: h('div', { class: 'dz-history' }, vs.map(v => h('div', { class: 'dz-hrow' },
        h('span', { class: 'dz-hver' }, `v${v.version}`),
        h('div', { class: 'grow' },
          h('div', { class: 'dz-file-row' }, [...dzFileLinks('v', v.id, v.file_name, isMaster),
            isStep(v.file_name) ? h('button', { class: 'btn sm', type: 'button', onclick: () => stepModal(v.id, v.file_name) }, '🧊 3B') : null]),
          v.note ? h('div', { class: 'small dz-note' }, v.note) : null,
          h('div', { class: 'small muted' }, `${fmtDateTime(v.created_at)} · ${v.uploaded_by_name || ''}`))))),
      actions: [{ label: 'Kapat' }],
    });
  }

  function rename(d) {
    const name = h('input', { class: 'input', value: d.name });
    modal({ title: 'Çizimi Yeniden Adlandır', body: field('Ad', name),
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        if (!name.value.trim()) throw new Error('Ad girin');
        await api.put(`/api/design/drawings/${d.id}`, { name: name.value }); reload();
      } }] });
  }
  async function del(d) {
    const msg = isMaster ? `“${d.name}” ve altındaki tüm alt çizimler ile sürümleri silinsin mi?` : `“${d.name}” için silme talebi Master onayına gönderilsin mi?`;
    if (!await confirmDialog(isMaster ? 'Çizimi sil' : 'Silme talebi', msg, { okLabel: isMaster ? 'Sil' : 'Talep Gönder', danger: true })) return;
    try { const r = await api.del(`/api/design/drawings/${d.id}`); toast(r.requested ? 'Silme talebi Master onayına gönderildi' : 'Silindi'); reload(); } catch (err) { toastError(err); }
  }

  // Çizime/montaja farklı zamanlarda not
  async function notesModal(d) {
    const list = h('div', { class: 'dz-notes' });
    const ta = h('textarea', { class: 'input', rows: 2, placeholder: 'Not ekle…' });
    const draw = async () => {
      let ns; try { ns = await api.get(`/api/design/drawings/${d.id}/notes`); } catch (err) { return; }
      clear(list, ns.length ? ns.map(n => h('div', { class: 'dz-note-row' },
        h('div', { class: 'grow' }, h('div', null, n.note), h('div', { class: 'small muted' }, `${fmtDateTime(n.created_at)} · ${n.by_name || ''}`)),
        h('button', { class: 'btn xs ghost danger-text', type: 'button', title: 'Sil', onclick: async () => { await api.del(`/api/design/notes/${n.id}`); draw(); reload(); } }, '×')))
        : h('div', { class: 'muted' }, 'Henüz not yok.'));
    };
    const add = async () => { if (!ta.value.trim()) return; try { await api.post(`/api/design/drawings/${d.id}/notes`, { note: ta.value }); ta.value = ''; draw(); reload(); } catch (err) { toastError(err); } };
    draw();
    modal({ title: `${d.name} · Notlar`, wide: true, body: h('div', null, list, h('div', { class: 'cl-set-add', style: { marginTop: '10px' } }, ta, h('button', { class: 'btn primary', type: 'button', onclick: add }, 'Ekle'))), actions: [{ label: 'Kapat' }] });
  }

  // Montaj üretim parçaları (G-code dosyaları)
  async function partsModal(d) {
    const list = h('div', { class: 'dz-parts' });
    const draw = async () => {
      let ps; try { ps = await api.get(`/api/design/drawings/${d.id}/parts`); } catch (err) { return; }
      clear(list, ps.length ? ps.map(pp => h('div', { class: 'dz-part-row' },
        h('div', { class: 'grow' }, h('b', null, pp.name), pp.qty != null ? h('span', { class: 'small muted' }, ` · ${pp.qty} adet`) : null,
          pp.note ? h('div', { class: 'small dz-note' }, pp.note) : null,
          h('div', { class: 'small muted' }, `${fmtDateTime(pp.created_at)} · ${pp.by_name || ''}`)),
        pp.file_path ? h('div', { class: 'dz-file-row' }, dzFileLinks('p', pp.id, pp.file_name || pp.name, isMaster)) : null,
        h('button', { class: 'btn xs ghost danger-text', type: 'button', title: isMaster ? 'Sil' : 'Silme talebi', onclick: async () => { if (await confirmDialog(isMaster ? 'Parçayı sil' : 'Silme talebi', isMaster ? `“${pp.name}” silinsin mi?` : `“${pp.name}” için silme talebi Master onayına gönderilsin mi?`, { okLabel: isMaster ? 'Sil' : 'Talep Gönder', danger: true })) { const r = await api.del(`/api/design/parts/${pp.id}`); toast(r.requested ? 'Silme talebi gönderildi' : 'Silindi'); draw(); reload(); } } }, '×')))
        : h('div', { class: 'muted' }, 'Henüz üretim parçası yok.'));
    };
    const fileIn = h('input', { type: 'file', class: 'input', accept: '.gcode,.nc,.tap,.ngc,.cnc,.txt' });
    const nm = h('input', { class: 'input', placeholder: 'Parça adı (boşsa dosya adı)' });
    const qty = h('input', { class: 'input', type: 'number', min: '0', step: '1', placeholder: 'Adet', style: { maxWidth: '110px' } });
    const note = h('input', { class: 'input', placeholder: 'Açıklama (isteğe bağlı)' });
    const add = async () => {
      if (!fileIn.files[0]) { toast('G-code dosyası seçin', 'err'); return; }
      const fd = new FormData(); fd.append('file', fileIn.files[0]); fd.append('name', nm.value); fd.append('qty', qty.value); fd.append('note', note.value);
      try { await upload(`/api/design/drawings/${d.id}/parts`, fd); fileIn.value = ''; nm.value = ''; qty.value = ''; note.value = ''; draw(); reload(); } catch (err) { toastError(err); }
    };
    draw();
    modal({ title: `${d.name} · Üretim Parçaları (G-code)`, wide: true,
      body: h('div', null, list,
        h('div', { class: 'dz-part-add' }, h('b', null, 'Yeni G-code parçası'),
          field('G-code dosyası', fileIn), h('div', { class: 'dz-part-fields' }, field('Parça adı', nm), field('Adet', qty)), field('Açıklama', note),
          h('button', { class: 'btn primary', type: 'button', onclick: add }, 'Ekle'))),
      actions: [{ label: 'Kapat' }] });
  }

  // Çizimi/montajı alt parçaları ve sürüm geçmişiyle kopyala
  async function copyModal(d) {
    let projects; try { projects = await api.get('/api/design/projects'); } catch (err) { return toastError(err); }
    const projSel = h('select', { class: 'input' }, projects.map(pr => h('option', { value: pr.id, selected: pr.id === pid }, pr.name)));
    const parentSel = h('select', { class: 'input' });
    const loadParents = async () => {
      let det; try { det = await api.get(`/api/design/projects/${Number(projSel.value)}`); } catch { det = { tree: [] }; }
      const opts = [h('option', { value: '' }, 'En üst (proje kökü)')];
      const walk = (nodes, depth) => nodes.forEach(n => { opts.push(h('option', { value: n.id }, `${'— '.repeat(depth)}${n.name}`)); walk(n.children || [], depth + 1); });
      walk(det.tree || [], 0);
      clear(parentSel, opts);
    };
    projSel.addEventListener('change', loadParents);
    await loadParents();
    modal({ title: `${d.name} · Kopyala`,
      body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Çizim; alt parçaları ve tüm sürüm geçmişiyle birlikte kopyalanır.'),
        field('Hedef proje', projSel), field('Hedef montaj / konum', parentSel)),
      actions: [{ label: 'Vazgeç' }, { label: 'Kopyala', class: 'primary', onClick: async () => {
        const tproj = Number(projSel.value);
        await api.post(`/api/design/drawings/${d.id}/copy`, { target_project_id: tproj, target_parent_id: parentSel.value ? Number(parentSel.value) : null });
        toast('Kopyalandı', 'success');
        if (tproj === pid) reload();
      } }] });
  }

  return { addDrawing, newVersion, history, rename, del, notesModal, partsModal, copyModal };
}

// STEP dosyasının 3B önizlemesi (bağımsız)
async function stepModal(vid, name) {
  const wrap = h('div', { class: 'step3d-wrap' }, h('div', { class: 'loading', style: { padding: '24px' } }, '3B model yükleniyor… (ilk açılışta CAD çekirdeği iner)'));
  let viewer = null;
  modal({ title: `${name} · 3B Önizleme`, wide: true, body: wrap, actions: [{ label: 'Kapat' }], onClose: () => viewer?.dispose() });
  try {
    const resp = await fetch(`/api/design/file?v=${vid}`, { credentials: 'same-origin' });
    if (!resp.ok) throw new Error('Dosya alınamadı');
    const buf = await resp.arrayBuffer();
    clear(wrap);
    viewer = await viewStep(wrap, buf);
  } catch (err) { clear(wrap, h('div', { class: 'card empty' }, 'Önizleme yüklenemedi: ' + (err.message || err))); }
}

// ---------- Montaj ağacı: gerçek ağaç (organizasyon şemasında kullanılan treeSpider bileşeni) ----------
let _TreeSpider = null;
async function loadTreeSpider() {
  if (_TreeSpider) return _TreeSpider;
  if (!document.querySelector('link[data-treespider]')) {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = '/static/vendor/treespider/treeSpider.css'; l.dataset.treespider = '1';
    document.head.append(l);
  }
  const mod = await import('/static/vendor/treespider/treeSpider.bundle.min.js');
  _TreeSpider = mod.default;
  return _TreeSpider;
}

function findNode(nodes, id) {
  for (const n of (nodes || [])) { if (String(n.id) === String(id)) return n; const f = findNode(n.children, id); if (f) return f; }
  return null;
}

function kindGlyphMarkup(kind) {
  if (kind === 'assembly') return '<path d="M24 5 40 14v20L24 43 8 34V14z"/><path d="M8 14 24 23l16-9M24 23v20"/>';
  if (kind === 'part') return '<circle cx="24" cy="24" r="6"/><path d="M24 6v6M24 36v6M6 24h6M36 24h6M11 11l4.2 4.2M32.8 32.8 37 37M37 11l-4.2 4.2M15.2 32.8 11 37"/>';
  return '<path d="M14 6h13l9 9v27H14z"/><path d="M27 6v9h9M19 25h11M19 31h11M19 19h6"/>';
}
function kindGlyph(kind) {
  const t = document.createElement('template');
  t.innerHTML = `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${kindGlyphMarkup(kind)}</svg>`;
  return t.content.firstElementChild;
}
function kindAvatar(kind) {
  const c = KIND_COLOR[kind] || '#5d6879';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120"><rect width="120" height="120" rx="20" fill="${c}"/><svg x="30" y="30" width="60" height="60" viewBox="0 0 48 48" fill="none" stroke="#ffffff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">${kindGlyphMarkup(kind)}</svg></svg>`;
  return 'data:image/svg+xml,' + encodeURIComponent(svg);
}

async function renderChart(stage, tree_data, byId, openMenu) {
  const TreeSpider = await loadTreeSpider();
  clear(stage);
  const cid = 'dzts-' + Date.now().toString(36);
  const cont = h('div', { style: { width: '100%', height: '100%' } });
  cont.id = cid;
  stage.append(cont);
  const chart = new TreeSpider({
    targetContainer: '#' + cid, autoInitialize: false,
    tree_data, tree_type: 'default', chart_head_type: 'default',
    head_image_shape: 'symbolCircle', show_chart_head_border: true,
    backgroundPattern: 'none', chart_head_bg: '#ffffff',
    color_range: ['#12385c', '#1d4e89', '#2b6cb0', '#3f7cb8'],
    width: '100%', height: '100%', font_link: '', font_name: "system-ui, 'Segoe UI', Arial, sans-serif",
  });
  chart.on('chart_head.create', e => {
    const svgEl = e && e.detail && e.detail.headNode; if (!svgEl) return;
    const clip = svgEl.querySelector('[id^="default-head-clip-"]');
    const id = clip ? clip.id.replace('default-head-clip-', '') : null;
    if (id == null) return;
    svgEl.style.cursor = 'pointer';
    // Kısa dokunuş → işlem menüsü; alt dalları açıp kapatmak için düğümdeki ok (.ts-linker) kendi çalışır.
    let timer = null, longPressed = false, sx = 0, sy = 0;
    const cancel = () => { if (timer) { clearTimeout(timer); timer = null; } };
    svgEl.addEventListener('pointerdown', ev => {
      longPressed = false; sx = ev.clientX; sy = ev.clientY;
      timer = setTimeout(() => { longPressed = true; openMenu({ clientX: sx, clientY: sy }, byId[id] || null); }, 420);
    });
    svgEl.addEventListener('pointermove', ev => { if (Math.abs(ev.clientX - sx) > 8 || Math.abs(ev.clientY - sy) > 8) cancel(); });
    svgEl.addEventListener('pointercancel', cancel);
    svgEl.addEventListener('pointerleave', cancel);
    svgEl.addEventListener('pointerup', ev => {
      cancel();
      if (longPressed) { ev.preventDefault(); ev.stopPropagation(); return; }
      if (ev.target.closest && ev.target.closest('.ts-linker')) return;   // oka basıldıysa bileşen açar/kapar
      openMenu({ clientX: ev.clientX, clientY: ev.clientY }, byId[id] || null);
    });
  });
  chart.initialize();
}

async function renderAssembly(view, pid, nodeId, ctx) {
  const isMaster = ctx.user.master;
  const body = h('div');
  const stage = h('div', { class: 'org-ts dz-ts' });
  let acts = null;

  let menuEl = null;
  const closeMenu = () => { if (menuEl) { menuEl.remove(); menuEl = null; document.removeEventListener('click', closeMenu); } };
  const openMenu = (ev, node) => {
    closeMenu();
    if (!node || !acts) return;
    const cur = node.current;
    const items = [
      [cur ? 'Yeni Sürüm' : 'Dosya Yükle', () => acts.newVersion(node), false],
      node.version_count ? [`Sürüm Geçmişi (${node.version_count})`, () => acts.history(node), false] : null,
      cur ? ['Dosyayı Önizle', () => window.open(`/api/design/file?v=${cur.id}`, '_blank', 'noopener'), false] : null,
      (cur && isStep(cur.file_name)) ? ['🧊 3B Önizle', () => stepModal(cur.id, cur.file_name), false] : null,
      [`📝 Notlar${node.note_count ? ` (${node.note_count})` : ''}`, () => acts.notesModal(node), false],
      [`🔩 Üretim Parçaları${node.prod_count ? ` (${node.prod_count})` : ''}`, () => acts.partsModal(node), false],
      ['+ Alt Çizim', () => acts.addDrawing(node), false],
      ['⧉ Kopyala', () => acts.copyModal(node), false],
      ['✎ Yeniden Adlandır', () => acts.rename(node), false],
      ['🗑 Sil', () => acts.del(node), true],
    ].filter(Boolean);
    menuEl = h('div', { class: 'org-menu' }, items.map(([label, fn, danger]) =>
      h('button', { class: `org-menu-item ${danger ? 'danger' : ''}`, onclick: () => { closeMenu(); fn(); } }, label)));
    document.body.append(menuEl);
    const w = menuEl.offsetWidth || 210, hh = menuEl.offsetHeight || 320;
    menuEl.style.left = Math.min(ev.clientX, window.innerWidth - w - 8) + 'px';
    menuEl.style.top = Math.min(ev.clientY, window.innerHeight - hh - 8) + 'px';
    setTimeout(() => document.addEventListener('click', closeMenu), 0);
  };

  const load = async () => {
    let p;
    try { p = await api.get(`/api/design/projects/${pid}`); } catch (err) { return clear(view, pageHead('Endüstriyel Tasarım', { back: `#/design/${pid}` }), h('div', { class: 'card empty' }, err.message)); }
    const root = findNode(p.tree, nodeId);
    if (!root) { location.hash = `#/design/${pid}`; return; }
    acts = designActions(pid, load, isMaster);
    clear(view,
      pageHead(root.name, { back: `#/design/${pid}`, sub: `${p.name} · ${KIND[root.kind] || 'Çizim'}` }),
      moduleToolbar(
        h('button', { class: 'btn', type: 'button', onclick: () => acts.newVersion(root) }, root.current ? 'Yeni Sürüm' : 'Dosya Yükle'),
        h('button', { class: 'btn primary', type: 'button', onclick: () => acts.addDrawing(root) }, '+ Alt Çizim')),
      body);
    clear(body,
      h('p', { class: 'small muted dz-ts-hint' }, 'Bir düğüme dokunun → işlemler menüsü (yeni sürüm, alt çizim, notlar, üretim parçaları…). Alt dalları açıp kapatmak için düğümdeki oka dokunun.'),
      stage);
    const byId = {}; const flat = [];
    const walk = (node, parentId) => { byId[String(node.id)] = node; flat.push({ node, parentId }); (node.children || []).forEach(c => walk(c, String(node.id))); };
    walk(root, undefined);
    const tree_data = flat.map(({ node, parentId }) => ({
      id: String(node.id), parentId,
      name: node.name || '—',
      role: `${KIND[node.kind] || ''}${node.current ? ` · v${node.current.version}` : ' · sürüm yok'}`,
      image: (node.current && isImg(node.current.file_name)) ? `/api/design/file?v=${node.current.id}` : kindAvatar(node.kind),
    }));
    renderChart(stage, tree_data, byId, openMenu);
  };
  load();
}
