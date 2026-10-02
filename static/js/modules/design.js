// Endüstriyel Tasarım: projeler → çizim / montaj çizimi ağacı → alt çizimler (parçalar) → her çizimin sürüm geçmişi.
// Her yeni dosya yüklemesi yeni sürümdür; eski sürümler (dosya + açıklama) geçmişte kalır ve açılıp görülebilir.
import { api, upload } from '../api.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, pageHead, toast, toastError } from '../ui.js';
import { isStep, viewStep } from '../step3d.js';

const KIND = { assembly: 'Montaj Çizimi', drawing: 'Çizim', part: 'Parça' };
const KIND_BADGE = { assembly: 'blue', drawing: 'gray', part: 'green' };

export async function render(view, params, ctx) {
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

async function renderProjects(view, ctx) {
  const body = h('div');
  const load = async () => {
    let list;
    try { list = await api.get('/api/design/projects'); } catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    clear(body, list.length ? h('div', { class: 'grid-cards' }, list.map(p =>
      h('a', { class: 'card dz-proj', href: `#/design/${p.id}` },
        h('b', null, p.name),
        p.description ? h('div', { class: 'small muted dz-proj-desc' }, p.description) : null,
        h('div', { class: 'small muted' }, `${p.drawing_count} çizim · ${p.created_by_name || ''} · ${fmtDateTime(p.created_at)}`))))
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
  clear(view, pageHead('Endüstriyel Tasarım', { back: '#/', sub: 'Tasarım projeleri, çizimler ve sürümler',
    right: h('div', { class: 'head-right' },
      ctx.user.master ? h('button', { class: 'btn', onclick: deleteRequests }, '🗑 Silme Talepleri') : null,
      h('button', { class: 'btn primary', onclick: newProject }, '+ Yeni Proje')) }), body);
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

async function renderProject(view, pid, ctx) {
  const body = h('div');
  const isMaster = ctx.user.master;
  let p = null;
  const reload = () => load();
  const load = async () => {
    try { p = await api.get(`/api/design/projects/${pid}`); } catch (err) { return clear(view, pageHead('Endüstriyel Tasarım', { back: '#/design' }), h('div', { class: 'card empty' }, err.message)); }
    clear(view,
      pageHead(p.name, { back: '#/design', sub: p.description || 'Tasarım projesi',
        right: h('div', { class: 'head-right' }, h('button', { class: 'btn primary', onclick: () => addDrawing(null) }, '+ Montaj / Çizim Ekle')) }),
      body);
    clear(body, p.tree.length ? h('div', { class: 'dz-tree' }, p.tree.map(n => node(n, 0)))
      : h('div', { class: 'card empty' }, 'Bu projede çizim yok. “+ Montaj / Çizim Ekle” ile ekleyin.'));
  };

  function node(d, level) {
    const cur = d.current;
    const children = (d.children || []).map(c => node(c, level + 1));
    return h('div', { class: 'dz-node', style: { marginLeft: level ? '22px' : '0' } },
      h('div', { class: `dz-card ${cur ? '' : 'empty'}` },
        h('div', { class: 'dz-main' },
          h('span', { class: `badge ${KIND_BADGE[d.kind] || 'gray'}` }, KIND[d.kind] || 'Çizim'),
          h('b', { class: 'dz-name' }, d.name),
          cur ? h('span', { class: 'dz-ver' }, `v${cur.version}`) : h('span', { class: 'small muted' }, 'sürüm yok')),
        cur ? h('div', { class: 'dz-cur' },
          h('div', { class: 'dz-file-row' }, [...dzFileLinks('v', cur.id, cur.file_name, isMaster),
            isStep(cur.file_name) ? h('button', { class: 'btn sm primary', type: 'button', onclick: () => stepModal(cur.id, cur.file_name) }, '🧊 3B Önizle') : null]),
          cur.note ? h('div', { class: 'small dz-note' }, cur.note) : null,
          h('div', { class: 'small muted' }, `v${cur.version} · ${fmtDateTime(cur.created_at)} · ${cur.uploaded_by_name || ''}`)) : null,
        h('div', { class: 'dz-acts' },
          h('button', { class: 'btn sm primary', type: 'button', onclick: () => newVersion(d) }, cur ? 'Yeni Sürüm' : 'Dosya Yükle'),
          d.version_count ? h('button', { class: 'btn sm', type: 'button', onclick: () => history(d) }, `Geçmiş (${d.version_count})`) : null,
          h('button', { class: 'btn sm', type: 'button', onclick: () => notesModal(d) }, `📝 Notlar${d.note_count ? ` (${d.note_count})` : ''}`),
          h('button', { class: 'btn sm', type: 'button', onclick: () => partsModal(d) }, `🔩 Üretim Parçaları${d.prod_count ? ` (${d.prod_count})` : ''}`),
          h('button', { class: 'btn sm', type: 'button', onclick: () => addDrawing(d) }, '+ Alt Çizim'),
          h('button', { class: 'btn sm', type: 'button', onclick: () => copyModal(d) }, '⧉ Kopyala'),
          h('button', { class: 'btn sm ghost', type: 'button', onclick: () => rename(d) }, '✎'),
          h('button', { class: 'btn sm ghost danger-text', type: 'button', onclick: () => del(d) }, '🗑'))),
      children.length ? h('div', { class: 'dz-children' }, children) : null);
  }

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

  // STEP dosyasının 3B önizlemesi
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

  load();
}
