// Endüstriyel Tasarım: projeler → çizim / montaj çizimi ağacı → alt çizimler (parçalar) → her çizimin sürüm geçmişi.
// Her yeni dosya yüklemesi yeni sürümdür; eski sürümler (dosya + açıklama) geçmişte kalır ve açılıp görülebilir.
import { api, upload } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, moduleToolbar, pageHead, t, toast, toastError } from '../ui.js';
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
        h('div', { class: 'small muted' }, t('{n} alt çizim{parts}', { n: kids, parts: d.prod_count ? t(' · {p} parça', { p: d.prod_count }) : '' })),
        d.product_code ? h('div', { class: 'small dz-mcard-prod', title: d.product_name || '' }, `↔ ${d.product_code}${d.link_count ? t(' · {n} parça eşleşti', { n: d.link_count }) : ''}`) : null,
        h('span', { class: 'dz-mcard-open' }, 'Ağacı aç →'))),
    h('div', { class: 'dz-acts' },
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => acts.newVersion(d) }, cur ? 'Yeni Sürüm' : 'Dosya Yükle'),
      (cur && isStep(cur.file_name)) ? h('button', { class: 'btn sm', type: 'button', title: '3B montaj görünümü ve ürün eşleştirme', onclick: () => acts.step(d) }, '🧊 3B') : null,
      d.version_count ? h('button', { class: 'btn sm', type: 'button', onclick: () => acts.history(d) }, t('Geçmiş ({n})', { n: d.version_count })) : null,
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
      title: parent ? t('{name} · Alt Çizim Ekle', { name: parent.name }) : 'Montaj / Çizim Ekle',
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
        d.version_count ? h('p', { class: 'small muted', style: { marginTop: 0 } }, t('Mevcut sürüm v{a} geçmişte saklanır; bu yükleme v{b} olur.', { a: d.current ? d.current.version : d.version_count, b: (d.current ? d.current.version : d.version_count) + 1 })) : null,
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
      title: t('{name} · Sürüm Geçmişi', { name: d.name }), wide: true,
      body: h('div', { class: 'dz-history' }, vs.map(v => h('div', { class: 'dz-hrow' },
        h('span', { class: 'dz-hver' }, `v${v.version}`),
        h('div', { class: 'grow' },
          h('div', { class: 'dz-file-row' }, [...dzFileLinks('v', v.id, v.file_name, isMaster),
            isStep(v.file_name) ? h('button', { class: 'btn sm', type: 'button', onclick: () => stepStudio({ did: d.id, vid: v.id, name: `${d.name} v${v.version}`, reload }) }, '🧊 3B') : null]),
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
    const msg = isMaster ? t('“{name}” ve altındaki tüm alt çizimler ile sürümleri silinsin mi?', { name: d.name }) : t('“{name}” için silme talebi Master onayına gönderilsin mi?', { name: d.name });
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
    modal({ title: t('{name} · Notlar', { name: d.name }), wide: true, body: h('div', null, list, h('div', { class: 'cl-set-add', style: { marginTop: '10px' } }, ta, h('button', { class: 'btn primary', type: 'button', onclick: add }, 'Ekle'))), actions: [{ label: 'Kapat' }] });
  }

  // Montaj üretim parçaları (G-code dosyaları)
  async function partsModal(d) {
    const list = h('div', { class: 'dz-parts' });
    const draw = async () => {
      let ps; try { ps = await api.get(`/api/design/drawings/${d.id}/parts`); } catch (err) { return; }
      clear(list, ps.length ? ps.map(pp => h('div', { class: 'dz-part-row' },
        h('div', { class: 'grow' }, h('b', null, pp.name), pp.qty != null ? h('span', { class: 'small muted' }, t(' · {q} adet', { q: pp.qty })) : null,
          pp.note ? h('div', { class: 'small dz-note' }, pp.note) : null,
          h('div', { class: 'small muted' }, `${fmtDateTime(pp.created_at)} · ${pp.by_name || ''}`)),
        pp.file_path ? h('div', { class: 'dz-file-row' }, dzFileLinks('p', pp.id, pp.file_name || pp.name, isMaster)) : null,
        h('button', { class: 'btn xs ghost danger-text', type: 'button', title: isMaster ? 'Sil' : 'Silme talebi', onclick: async () => { if (await confirmDialog(isMaster ? 'Parçayı sil' : 'Silme talebi', isMaster ? t('“{name}” silinsin mi?', { name: pp.name }) : t('“{name}” için silme talebi Master onayına gönderilsin mi?', { name: pp.name }), { okLabel: isMaster ? 'Sil' : 'Talep Gönder', danger: true })) { const r = await api.del(`/api/design/parts/${pp.id}`); toast(r.requested ? 'Silme talebi gönderildi' : 'Silindi'); draw(); reload(); } } }, '×')))
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
    modal({ title: t('{name} · Üretim Parçaları (G-code)', { name: d.name }), wide: true,
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
    modal({ title: t('{name} · Kopyala', { name: d.name }),
      body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Çizim; alt parçaları ve tüm sürüm geçmişiyle birlikte kopyalanır.'),
        field('Hedef proje', projSel), field('Hedef montaj / konum', parentSel)),
      actions: [{ label: 'Vazgeç' }, { label: 'Kopyala', class: 'primary', onClick: async () => {
        const tproj = Number(projSel.value);
        await api.post(`/api/design/drawings/${d.id}/copy`, { target_project_id: tproj, target_parent_id: parentSel.value ? Number(parentSel.value) : null });
        toast('Kopyalandı', 'success');
        if (tproj === pid) reload();
      } }] });
  }

  const step = d => stepStudio({ did: d.id, vid: d.current.id, name: d.name, reload });
  return { addDrawing, newVersion, history, rename, del, notesModal, partsModal, copyModal, step };
}

// ---------- STEP 3B stüdyosu: solda parça ağacı, ortada model (tıkla/seç → turuncu vurgu), altta patlatma kaydırıcısı,
// montaj ↔ Ürün Yönetimi mamulü ve seçili parça ↔ yarı mamul / yedek parça eşleştirme (design_step_links). ----------
const PTYPE = { MAMUL: 'Mamul', YARI_MAMUL: 'Yarı mamul', YEDEK_PARCA: 'Yedek parça', SARF: 'Sarf' };
// Ad/kod sadeleştirme: "L4 - V3" ↔ "L4-V3"; "O1 - V3" ↔ "01-V3" (STEP'te O harfi / üründe sıfır); boşluk, Türkçe İ, satır sonu
const normCode = s => (s || '').replace(/[\r\n]/g, '').toLocaleUpperCase('tr').replace(/İ/g, 'I').replace(/[\s_]+/g, '').replace(/-+/g, '-');
const codeVariants = s => { const n = normCode(s); const z = n.replace(/O(?=\d)/g, '0'), o = n.replace(/\b0(?=\d)/g, 'O'); return [...new Set([n, z, o])]; };

async function stepStudio({ did, vid, name, reload }) {
  const canvas = h('div', { class: 'stp-canvas' }, h('div', { class: 'loading', style: { padding: '24px' } }, '3B model yükleniyor… (ilk açılışta CAD çekirdeği iner, büyük dosyalarda bir dakikaya kadar sürebilir)'));
  const treeEl = h('div', { class: 'stp-tree' }, h('div', { class: 'small muted', style: { padding: '8px' } }, 'Parçalar okunuyor…'));
  const selName = h('b', { class: 'stp-sel-name' }, 'Parça seçilmedi');
  const selLink = h('span', { class: 'small muted' }, '');
  const candFilter = h('input', { class: 'input', placeholder: 'Ürün ara (kod / ad)…', 'aria-label': 'Ürün ara' });
  const candSel = h('select', { class: 'input', 'aria-label': 'Eşleşecek ürün' });
  const saveBtn = h('button', { class: 'btn sm primary', type: 'button', disabled: true }, 'Eşleştir');
  const unlinkBtn = h('button', { class: 'btn sm ghost danger-text', type: 'button', disabled: true }, 'Kaldır');
  const autoBtn = h('button', { class: 'btn sm', type: 'button', title: 'STEP parça adlarını ürün kodlarıyla karşılaştırıp eşleşenleri bağlar' }, '✨ Ada göre otomatik eşle');
  const mamulSel = h('select', { class: 'input', 'aria-label': 'Mamul' });
  const mamulBtn = h('button', { class: 'btn sm', type: 'button' }, 'Kaydet');
  const mamulInfo = h('span', { class: 'small muted' }, '');
  const range = h('input', { type: 'range', min: '0', max: '100', value: '0', class: 'stp-range', 'aria-label': 'Patlatma' });
  const rangeVal = h('span', { class: 'small muted stp-range-val' }, '%0');
  const fitBtn = h('button', { class: 'btn sm ghost', type: 'button', title: 'Kadrajı sıfırla' }, '⌖ Kadraj');
  const countChip = h('span', { class: 'small muted' }, '');

  let viewer = null, links = {}, cands = [], mamul = null, selected = null, rows = {};
  const linkOf = p => links[p.key] || null;
  const collapsed = new Set();   // kapalı alt montaj anahtarları (varsayılan: 2. seviyeden derin gruplar kapalı)

  // Ağaç: alt montajlar (STEP içindeki STEP'ler / çok gövdeli düğümler) ▸ ile açılıp kapanır; grup satırı seçilince tüm alt parçalar vurgulanır
  const drawTree = () => {
    if (!viewer) return;
    rows = {};
    const items = [];
    const walk = nodes => nodes.forEach(p => {
      const ln = linkOf(p), isG = p.kind === 'group', closed = isG && collapsed.has(p.key);
      const caret = isG ? h('span', { class: `stp-caret ${closed ? 'closed' : ''}`, title: closed ? 'Aç' : 'Kapat',
        onclick: ev => { ev.stopPropagation(); if (closed) collapsed.delete(p.key); else collapsed.add(p.key); drawTree(); } }, '▾') : h('span', { class: 'stp-dot' });
      const row = h('button', { class: `stp-row ${isG ? 'group' : ''} ${selected && selected.key === p.key ? 'on' : ''} ${ln ? 'linked' : ''}`, type: 'button',
        style: { paddingLeft: `${8 + Math.max(0, p.depth - 1) * 14}px` }, title: ln ? `${p.name} ↔ ${ln.product_code} ${ln.product_name || ''}` : (isG ? t('{name} · alt montaj, {n} parça', { name: p.name, n: p.allMeshes.length }) : p.name),
        onclick: () => viewer.select(p) },
        caret, h('span', { class: 'stp-row-name' }, p.name, p.dupIndex ? h('span', { class: 'muted' }, ` #${p.dupIndex}`) : null, isG ? h('span', { class: 'muted small' }, ` (${p.children.length})`) : null),
        ln ? h('span', { class: 'stp-row-code' }, ln.product_code) : null);
      rows[p.key] = row; items.push(row);
      if (isG && !closed) walk(p.children);
    });
    walk(viewer.root.children);
    const n = Object.keys(links).length, g = viewer.nodes.filter(x => x.kind === 'group').length;
    countChip.textContent = t('{n} parça{g} · {m} eşleşmiş', { n: viewer.parts.length, g: g ? t(' · {g} alt montaj', { g }) : '', m: n });
    clear(treeEl, h('button', { class: `stp-row root ${!selected ? 'on' : ''}`, type: 'button', onclick: () => viewer.select(null) }, h('span', { class: 'stp-dot' }), h('b', null, viewer.root.name || 'Tüm montaj')), items);
  };

  const fillCands = () => {
    const q = normCode(candFilter.value);
    clear(candSel, h('option', { value: '' }, '— ürün seçin —'), cands.map(c => h('option', { value: c.id, hidden: !!q && !normCode(`${c.code} ${c.name}`).includes(q) }, `${c.code} — ${c.name}${c.type && c.type !== 'YARI_MAMUL' ? ` (${PTYPE[c.type] || c.type})` : ''}`)));
  };
  candFilter.addEventListener('input', fillCands);

  const onSelect = p => {
    selected = p;
    // Modelden seçilen parça kapalı bir alt montajın içindeyse üst grupları aç
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
    candSel.value = ln ? String(ln.product_id) : '';
    // Eşleşme yoksa ada göre öneri
    if (p && !ln) { const guess = guessFor(p); if (guess) candSel.value = String(guess.id); }
  };
  const guessFor = p => {
    const vs = codeVariants(p.name);
    return cands.find(c => codeVariants(c.code).some(v => vs.includes(v))) || null;
  };

  const loadLinks = async () => {
    const r = await api.get(`/api/design/drawings/${did}/step-links`);
    links = Object.fromEntries((r.links || []).map(l => [l.mesh_key, l]));
    cands = r.candidates || []; mamul = r.product || null;
    clear(mamulSel, h('option', { value: '' }, '— mamul seçin —'), (r.mamuls || []).map(m => h('option', { value: m.id, selected: mamul && mamul.id === m.id }, `${m.code} — ${m.name}`)));
    mamulInfo.textContent = mamul ? t('Parça adayları: {code} ürün ağacındaki yarı mamuller', { code: mamul.code }) : 'Mamul seçilmedi; adaylar tüm yarı mamuller / yedek parçalar';
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
  mamulBtn.addEventListener('click', async () => {
    try {
      await api.put(`/api/design/drawings/${did}/product`, { product_id: mamulSel.value ? Number(mamulSel.value) : null });
      toast(mamulSel.value ? 'Montaj mamul ile eşleştirildi' : 'Mamul eşleşmesi kaldırıldı', 'success'); await loadLinks(); reload?.();
    } catch (err) { toastError(err); }
  });
  range.addEventListener('input', () => { rangeVal.textContent = `%${range.value}`; viewer?.explode(Number(range.value) / 100); });
  fitBtn.addEventListener('click', () => viewer?.fit());

  const body = h('div', { class: 'stp-studio' },
    h('div', { class: 'stp-top' }, h('span', { class: 'stp-lbl' }, '🏷 Montaj ↔ Mamul'), mamulSel, mamulBtn, mamulInfo, h('span', { class: 'spacer' }), countChip),
    h('div', { class: 'stp-main' },
      h('div', { class: 'stp-side' }, h('div', { class: 'stp-side-head' }, h('b', null, 'Parçalar'), autoBtn), treeEl),
      h('div', { class: 'stp-view' }, canvas,
        h('div', { class: 'stp-bar' }, h('span', { class: 'stp-lbl' }, '💥 Patlat'), range, rangeVal, fitBtn))),
    h('div', { class: 'stp-sel' },
      h('div', { class: 'stp-sel-info' }, selName, selLink),
      h('div', { class: 'stp-sel-ctl' }, candFilter, candSel, saveBtn, unlinkBtn)));
  modal({ title: t('{name} · 3B Montaj', { name }), wide: true, body, actions: [{ label: 'Kapat' }], onClose: () => viewer?.dispose() });

  try {
    const [resp] = await Promise.all([fetch(`/api/design/file?v=${vid}`, { credentials: 'same-origin' }), loadLinks().catch(err => toastError(err))]);
    if (!resp.ok) throw new Error('Dosya alınamadı');
    const buf = await resp.arrayBuffer();
    clear(canvas);
    viewer = await viewStep(canvas, buf, { onSelect });
    viewer.nodes.forEach(n => { if (n.kind === 'group' && n.depth >= 2) collapsed.add(n.key); });   // derin alt montajlar kapalı başlar
    drawTree(); onSelect(null);
  } catch (err) { clear(canvas, h('div', { class: 'card empty' }, 'Önizleme yüklenemedi: ' + (err.message || err))); clear(treeEl); }
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

async function renderChart(stage, tree_data, byId, openMenu, onStep) {
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
      const node = byId[id] || null;
      if (node && node.current && isStep(node.current.file_name) && onStep) { onStep(node); return; }   // STEP'li düğüm: dokun → 3B montaj
      openMenu({ clientX: ev.clientX, clientY: ev.clientY }, node);
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
      node.version_count ? [t('Sürüm Geçmişi ({n})', { n: node.version_count }), () => acts.history(node), false] : null,
      cur ? ['Dosyayı Önizle', () => window.open(`/api/design/file?v=${cur.id}`, '_blank', 'noopener'), false] : null,
      (cur && isStep(cur.file_name)) ? ['🧊 3B Montaj / Eşleştir', () => stepStudio({ did: node.id, vid: cur.id, name: node.name, reload: load }), false] : null,
      [t('📝 Notlar{c}', { c: node.note_count ? ` (${node.note_count})` : '' }), () => acts.notesModal(node), false],
      [t('🔩 Üretim Parçaları{c}', { c: node.prod_count ? ` (${node.prod_count})` : '' }), () => acts.partsModal(node), false],
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
      h('p', { class: 'small muted dz-ts-hint' }, 'Bir düğüme dokunun → işlemler menüsü (yeni sürüm, alt çizim, notlar, üretim parçaları…); STEP dosyalı düğümde dokunuş 3B montajı açar, menü için basılı tutun. Alt dalları açıp kapatmak için düğümdeki oka dokunun.'),
      stage);
    const byId = {}; const flat = [];
    const walk = (node, parentId) => { byId[String(node.id)] = node; flat.push({ node, parentId }); (node.children || []).forEach(c => walk(c, String(node.id))); };
    walk(root, undefined);
    const tree_data = flat.map(({ node, parentId }) => ({
      id: String(node.id), parentId,
      name: node.name || '—',
      role: `${KIND[node.kind] || ''}${node.current ? ` · v${node.current.version}` : ' · sürüm yok'}${node.product_code ? ` · ↔ ${node.product_code}` : ''}`,
      image: (node.current && isImg(node.current.file_name)) ? `/api/design/file?v=${node.current.id}` : kindAvatar(node.kind),
    }));
    renderChart(stage, tree_data, byId, openMenu, node => stepStudio({ did: node.id, vid: node.current.id, name: node.name, reload: load }));
  };
  load();
}
