'use strict';

// Proje formu: "Yeni" (ana pencere) ve "Proje ayarları" (ana pencere ve proje penceresi).
// Akış: Proje İsmi → Tür (Video / Resim / Ses) → kaynak ve hedef uzantı → Dosya / Klasör → seçim
//       → aynı anda kaç dosya → (video/seste) konuşmayı metne çevir / (resimde) OCR — ikisi de isteğe bağlı → Kaydet.

const TYPE_ICONS = { video: 'video', image: 'image', audio: 'audio' };
// langName: settings.js

const optList = (list, v) => list.map(([k, l]) => `<option value="${esc(k)}" ${String(k) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('');

function targetOptions(type, v) {
  const T = FORMATS.TYPES[type];
  if (type !== 'video') return optList(T.target.map((x) => [x, x.toUpperCase()]), v);
  const vids = T.target.filter((x) => !T.audioOnlyTargets.includes(x) && x !== 'gif');
  const group = (label, list) => `<optgroup label="${esc(label)}">${optList(list.map((x) => [x, x.toUpperCase()]), v)}</optgroup>`;
  return group(t('pf.groupVideo'), vids) + group(t('pf.groupAnim'), ['gif']) + group(t('pf.groupAudioOnly'), T.audioOnlyTargets);
}

// folders: hiyerarşik klasör seçimi için; null ise klasör alanı gizlenir
async function editProject(project, { folderId = null, folders = null, settings = {} } = {}) {
  const isNew = !project;
  const p = JSON.parse(JSON.stringify(project || {
    name: '', type: 'video', sourceExts: [...FORMATS.TYPES.video.defaultSource], targetExt: FORMATS.TYPES.video.defaultTarget,
    sourceMode: 'folder', includeSubfolders: true, concurrency: settings.defaultConcurrency || 2,
    speech: { ...FORMATS.defaultSpeech(), model: settings.speechModel || 'base' },
    ocr: { ...FORMATS.defaultOcr(), languages: settings.ocrLanguages || FORMATS.defaultOcr().languages },
    options: FORMATS.defaultOptions(), folderId, sourcePath: '',
  }));
  p.options = { ...FORMATS.defaultOptions(), ...(p.options || {}) };
  for (const k of ['video', 'image', 'audio']) p.options[k] = { ...FORMATS.defaultOptions()[k], ...(p.options[k] || {}) };
  p.speech = { ...FORMATS.defaultSpeech(), ...(p.speech || {}) };
  p.ocr = { ...FORMATS.defaultOcr(), languages: settings.ocrLanguages || FORMATS.defaultOcr().languages, ...(p.ocr || {}) };
  let sourcePath = p.sourcePath || '';

  const folderSelect = () => {
    const out = [`<option value="">${esc(t('app.rootFolder'))}</option>`];
    const walk = (parentId, depth) => {
      for (const f of folders.filter((x) => (x.parentId || null) === parentId).sort((a, b) => a.name.localeCompare(b.name, LANG))) {
        out.push(`<option value="${f.id}" ${f.id === p.folderId ? 'selected' : ''}>${'&nbsp;&nbsp;&nbsp;'.repeat(depth)}${esc(f.name)}</option>`);
        walk(f.id, depth + 1);
      }
    };
    walk(null, 1);
    return out.join('');
  };

  const body = h(`<div class="pf">
    <div class="tabs">
      <button type="button" data-tab="general" class="on">${icon('layers')}${esc(t('pf.tabGeneral'))}</button>
      <button type="button" data-tab="output">${icon('gear')}${esc(t('pf.tabOutput'))}</button>
      <button type="button" data-tab="speech">${icon('mic')}${esc(t('pf.tabSpeech'))}</button>
      <button type="button" data-tab="ocr">${icon('text')}${esc(t('pf.tabOcr'))}</button>
    </div>

    <div class="tab-panel" data-panel="general">
      <div class="field"><label>${esc(t('pf.name'))}</label><input class="input" id="pf-name" maxlength="120" placeholder="${esc(t('pf.namePh'))}" value="${esc(p.name)}"></div>
      <div class="field"><label>${esc(t('pf.type'))}</label>
        <div class="types">${Object.keys(FORMATS.TYPES).map((k) => `
          <button type="button" class="type-card" data-type="${k}" style="--c:${FORMATS.TYPES[k].color}">
            <span class="ti">${icon(TYPE_ICONS[k])}</span><span><b>${esc(t(`type.${k}`))}</b><small>${esc(t(`type.${k}Hint`))}</small></span>
          </button>`).join('')}</div></div>
      <div class="ext-row">
        <div class="field"><div class="hint-line"><label>${esc(t('pf.sourceExt'))}</label><a id="pf-all"></a></div><div class="ext-chips" id="pf-src"></div></div>
        <div class="ext-arrow">${icon('arrowRight', '')}</div>
        <div class="field"><label>${esc(t('pf.targetExt'))}</label><select class="input" id="pf-target"></select>
          <small class="hint" id="pf-target-hint"></small></div>
      </div>
      <div class="field"><label>${esc(t('pf.source'))}</label>
        <div class="seg" id="pf-mode">
          <button type="button" data-v="file">${icon('file')}${esc(t('pf.modeFile'))}</button>
          <button type="button" data-v="folder">${icon('folder')}${esc(t('pf.modeFolder'))}</button>
        </div></div>
      <div class="field"><label id="pf-path-label"></label>
        <div class="src-pick"><input class="input" id="pf-path" readonly spellcheck="false"><button type="button" class="btn" id="pf-pick">${icon('folder')}${esc(t('common.choose'))}</button></div>
        <label class="check" id="pf-sub-wrap"><input type="checkbox" id="pf-sub" ${p.includeSubfolders !== false ? 'checked' : ''}><span>${esc(t('pf.subfolders'))}</span></label>
      </div>
      <div class="row c-1-1">
        <div class="field"><label>${esc(t('pf.concurrency'))}</label>
          <div class="inline"><input class="input" id="pf-conc" type="number" min="1" max="32" value="${esc(p.concurrency || 2)}"><div class="chips" id="pf-conc-chips"></div></div>
          <small class="hint">${esc(t('pf.concurrencyHint'))}</small></div>
        ${folders ? `<div class="field"><label>${esc(t('pf.folder'))}</label><select class="input" id="pf-folder">${folderSelect()}</select></div>` : '<div></div>'}
      </div>
      <label class="speech-ask check hidden" id="pf-ocr-ask"><input type="checkbox" id="pf-ocr" ${p.ocr.enabled ? 'checked' : ''}>
        <span>${icon('text', 'si')}</span><span><b>${esc(t('pf.ocrAsk'))}</b><small>${esc(t('pf.ocrAskHint'))}</small></span></label>
      <label class="speech-ask check" id="pf-speech-ask"><input type="checkbox" id="pf-speech" ${p.speech.enabled ? 'checked' : ''}>
        <span>${icon('mic', 'si')}</span><span><b>${esc(t('pf.speechAsk'))}</b><small>${esc(t('pf.speechAskHint'))}</small></span></label>
    </div>

    <div class="tab-panel hidden" data-panel="output"></div>

    <div class="tab-panel hidden" data-panel="ocr">
      <label class="check"><input type="checkbox" id="pf-ocr2"><span>${esc(t('pf.ocrAsk'))}<small>${esc(t('pf.ocrAskHint'))}</small></span></label>
      <div class="field"><div class="hint-line"><label>${esc(t('pf.ocrLangs'))}</label></div><div class="ext-chips" id="pf-ocr-langs"></div>
        <small class="hint">${esc(t('pf.ocrLangsHint'))}</small></div>
      <div class="section-title">${esc(t('pf.ocrData'))}</div>
      <div id="pf-ocr-models"></div>
      <small class="hint">${esc(t('pf.ocrNote'))}</small>
    </div>

    <div class="tab-panel hidden" data-panel="speech">
      <label class="check"><input type="checkbox" id="pf-speech2"><span>${esc(t('pf.speechAsk'))}<small>${esc(t('pf.speechAskHint'))}</small></span></label>
      <div class="row c-1-1">
        <div class="field"><label>${esc(t('pf.speechModel'))}</label>
          <select class="input" id="pf-model">${optList(Object.keys(FORMATS.SPEECH_MODELS).map((k) => [k, `${t(`speech.model.${k}`)} · ~${FORMATS.SPEECH_MODELS[k].mb} MB`]), p.speech.model)}</select></div>
        <div class="field"><label>${esc(t('pf.speechLang'))}</label>
          <select class="input" id="pf-lang">${optList(FORMATS.SPEECH_LANGS.map((c) => [c, langName(c)]), p.speech.language)}</select></div>
      </div>
      <label class="check"><input type="checkbox" id="pf-window" ${p.speech.perWindow ? 'checked' : ''}><span>${esc(t('pf.perWindow'))}<small>${esc(t('pf.perWindowHint'))}</small></span></label>
      <div class="section-title">${esc(t('pf.models'))}</div>
      <div id="pf-models"></div>
      <small class="hint">${esc(t('pf.speechNote'))}</small>
    </div>
  </div>`);
  const q = (s) => body.querySelector(s);
  q('#pf-models').replaceWith(speechModelsBox());
  q('#pf-ocr-models').replaceWith(ocrLangsBox(() => p.ocr.languages));

  // OCR dilleri (en çok 6; Tesseract birden çok dili aynı anda okuyabilir)
  const paintOcrLangs = () => {
    const el = q('#pf-ocr-langs');
    el.innerHTML = '';
    for (const l of FORMATS.OCR_LANGS) {
      const b = h(`<button type="button" class="ext-chip all ${p.ocr.languages.includes(l) ? 'on' : ''}">${esc(langName(FORMATS.OCR_ISO[l]))}</button>`);
      b.onclick = () => {
        if (p.ocr.languages.includes(l)) { if (p.ocr.languages.length > 1) p.ocr.languages = p.ocr.languages.filter((x) => x !== l); }
        else if (p.ocr.languages.length < 6) p.ocr.languages = [...p.ocr.languages, l];
        paintOcrLangs();
        document.dispatchEvent(new Event('ocr-langs-changed'));
      };
      el.appendChild(b);
    }
  };
  paintOcrLangs();

  // --- Sekmeler
  const showTab = (name) => {
    body.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
    body.querySelectorAll('.tab-panel').forEach((x) => x.classList.toggle('hidden', x.dataset.panel !== name));
  };
  body.querySelectorAll('.tabs button').forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));

  // --- Dönüştürme ayarları (türe göre)
  const readOutput = () => {
    const o = JSON.parse(JSON.stringify(p.options));
    const v = (id) => { const el = q(id); return el ? (el.type === 'checkbox' ? el.checked : el.value) : undefined; };
    if (p.type === 'video') {
      Object.assign(o.video, { quality: v('#o-q'), resolution: v('#o-res'), fps: v('#o-fps'), codec: v('#o-codec'), speed: v('#o-speed'), audioBitrate: v('#o-ab'), noAudio: v('#o-noa') });
    } else if (p.type === 'image') {
      Object.assign(o.image, { quality: Number(v('#o-iq')), maxWidth: Number(v('#o-w')) || 0, maxHeight: Number(v('#o-h')) || 0, keepMeta: v('#o-meta') });
    } else {
      Object.assign(o.audio, { bitrate: v('#o-br'), sampleRate: v('#o-sr'), channels: v('#o-ch') });
    }
    return o;
  };
  const paintOutput = () => {
    const el = q('[data-panel="output"]');
    const o = p.options;
    if (p.type === 'video') {
      const v = o.video;
      el.innerHTML = `
        <div class="row c-1-1">
          <div class="field"><label>${esc(t('out.quality'))}</label><select class="input" id="o-q">${optList(FORMATS.QUALITY.map((k) => [k, t(`out.q.${k}`)]), v.quality)}</select></div>
          <div class="field"><label>${esc(t('out.resolution'))}</label><select class="input" id="o-res">${optList(FORMATS.RESOLUTIONS.map((k) => [k, k === 'source' ? t('out.asSource') : `${k}p`]), v.resolution)}</select>
            <small class="hint">${esc(t('out.resolutionHint'))}</small></div>
        </div>
        <div class="row c-1-1">
          <div class="field"><label>${esc(t('out.fps'))}</label><select class="input" id="o-fps">${optList(FORMATS.FPS.map((k) => [k, k === 'source' ? t('out.asSource') : `${k} fps`]), v.fps)}</select></div>
          <div class="field"><label>${esc(t('out.codec'))}</label><select class="input" id="o-codec">${optList([['h264', t('out.h264')], ['h265', t('out.h265')]], v.codec)}</select>
            <small class="hint">${esc(t('out.codecHint'))}</small></div>
        </div>
        <div class="row c-1-1">
          <div class="field"><label>${esc(t('out.speed'))}</label><select class="input" id="o-speed">${optList(['veryfast', 'fast', 'medium', 'slow'].map((k) => [k, t(`out.speed.${k}`)]), v.speed)}</select></div>
          <div class="field"><label>${esc(t('out.audioBitrate'))}</label><select class="input" id="o-ab">${optList(FORMATS.AUDIO_BITRATES.map((k) => [k, `${k} kbps`]), v.audioBitrate)}</select></div>
        </div>
        <label class="check"><input type="checkbox" id="o-noa" ${v.noAudio ? 'checked' : ''}><span>${esc(t('out.noAudio'))}</span></label>`;
    } else if (p.type === 'image') {
      const v = o.image;
      el.innerHTML = `
        <div class="field"><label>${esc(t('out.imgQuality'))}: <b id="o-iqv">${v.quality}</b></label><input type="range" id="o-iq" min="1" max="100" value="${esc(v.quality)}">
          <small class="hint">${esc(t('out.imgQualityHint'))}</small></div>
        <div class="row c-1-1">
          <div class="field"><label>${esc(t('out.maxWidth'))}</label><div class="unit-wrap"><input class="input" id="o-w" type="number" min="0" max="20000" value="${esc(v.maxWidth || '')}" placeholder="${esc(t('out.noLimit'))}"><span>px</span></div></div>
          <div class="field"><label>${esc(t('out.maxHeight'))}</label><div class="unit-wrap"><input class="input" id="o-h" type="number" min="0" max="20000" value="${esc(v.maxHeight || '')}" placeholder="${esc(t('out.noLimit'))}"><span>px</span></div></div>
        </div>
        <small class="hint">${esc(t('out.resizeHint'))}</small>
        <label class="check"><input type="checkbox" id="o-meta" ${v.keepMeta ? 'checked' : ''}><span>${esc(t('out.keepMeta'))}<small>${esc(t('out.keepMetaHint'))}</small></span></label>`;
      q('#o-iq').oninput = (e) => (q('#o-iqv').textContent = e.target.value);
    } else {
      const v = o.audio;
      el.innerHTML = `
        <div class="row c-1-1">
          <div class="field"><label>${esc(t('out.bitrate'))}</label><select class="input" id="o-br">${optList(FORMATS.AUDIO_BITRATES.map((k) => [k, `${k} kbps`]), v.bitrate)}</select>
            <small class="hint">${esc(t('out.bitrateHint'))}</small></div>
          <div class="field"><label>${esc(t('out.sampleRate'))}</label><select class="input" id="o-sr">${optList(FORMATS.SAMPLE_RATES.map((k) => [k, k === 'source' ? t('out.asSource') : `${Number(k) / 1000} kHz`]), v.sampleRate)}</select></div>
        </div>
        <div class="field"><label>${esc(t('out.channels'))}</label><select class="input" id="o-ch">${optList([['source', t('out.asSource')], ['stereo', t('out.stereo')], ['mono', t('out.mono')]], v.channels)}</select></div>`;
    }
  };

  // --- Tür, uzantılar, kaynak
  const T = () => FORMATS.TYPES[p.type];
  const paintType = () => {
    body.querySelectorAll('.type-card').forEach((b) => b.classList.toggle('on', b.dataset.type === p.type));
    body.style.setProperty('--c', T().color);
    const src = q('#pf-src');
    src.innerHTML = '';
    for (const x of T().source) {
      const b = h(`<button type="button" class="ext-chip ${p.sourceExts.includes(x) ? 'on' : ''}">${esc(x)}</button>`);
      b.onclick = () => {
        p.sourceExts = p.sourceExts.includes(x) ? p.sourceExts.filter((y) => y !== x) : [...p.sourceExts, x];
        b.classList.toggle('on');
        paintAll();
      };
      src.appendChild(b);
    }
    q('#pf-target').innerHTML = targetOptions(p.type, p.targetExt);
    // Video/seste konuşmadan metne, resimde OCR seçeneği sunulur (ikisi de isteğe bağlı)
    const speechOk = p.type !== 'image';
    q('#pf-speech-ask').classList.toggle('hidden', !speechOk);
    q('#pf-ocr-ask').classList.toggle('hidden', speechOk);
    body.querySelector('[data-tab="speech"]').classList.toggle('hidden', !speechOk);
    body.querySelector('[data-tab="ocr"]').classList.toggle('hidden', speechOk);
    paintAll();
    paintOutput();
  };
  const paintAll = () => {
    const all = p.sourceExts.length === T().source.length;
    q('#pf-all').textContent = all ? t('pf.selectNone') : t('pf.selectAll');
    const ao = p.type === 'video' && T().audioOnlyTargets.includes(q('#pf-target').value);
    q('#pf-target-hint').textContent = ao ? t('pf.audioOnlyHint') : q('#pf-target').value === 'gif' ? t('pf.gifHint') : '';
  };
  q('#pf-all').onclick = () => {
    p.sourceExts = p.sourceExts.length === T().source.length ? [] : [...T().source];
    paintType();
  };
  body.querySelectorAll('.type-card').forEach((b) => (b.onclick = () => {
    if (p.type === b.dataset.type) return;
    p.type = b.dataset.type;
    p.sourceExts = [...T().defaultSource];
    p.targetExt = T().defaultTarget;
    if (p.sourceMode === 'file' && sourcePath && !T().source.includes(FORMATS.extOf(sourcePath))) { sourcePath = ''; paintMode(); }
    paintType();
  }));
  q('#pf-target').onchange = (e) => { p.targetExt = e.target.value; paintAll(); };

  const paintMode = () => {
    body.querySelectorAll('#pf-mode button').forEach((b) => b.classList.toggle('on', b.dataset.v === p.sourceMode));
    q('#pf-path-label').textContent = p.sourceMode === 'file' ? t('pf.pathFile') : t('pf.pathFolder');
    q('#pf-path').value = sourcePath;
    q('#pf-path').placeholder = isNew || !sourcePath ? t('pf.pathNone') : '';
    q('#pf-sub-wrap').classList.toggle('hidden', p.sourceMode !== 'folder');
  };
  body.querySelectorAll('#pf-mode button').forEach((b) => (b.onclick = () => {
    if (p.sourceMode === b.dataset.v) return;
    p.sourceMode = b.dataset.v;
    sourcePath = '';
    paintMode();
  }));
  q('#pf-pick').onclick = async () => {
    const picked = await window.api.pickSource({ mode: p.sourceMode, type: p.type, exts: p.sourceExts, defaultPath: sourcePath || undefined });
    if (!picked) return;
    sourcePath = picked;
    q('#pf-path').classList.remove('invalid');
    if (p.sourceMode === 'file') {
      const ext = FORMATS.extOf(picked);
      if (T().source.includes(ext) && !p.sourceExts.includes(ext)) { p.sourceExts.push(ext); paintType(); }
    }
    if (!q('#pf-name').value.trim()) q('#pf-name').value = picked.split(/[\\/]/).filter(Boolean).pop().replace(/\.[^.]+$/, '');
    paintMode();
  };

  for (const n of [1, 2, 4, 8]) {
    const b = h(`<button type="button" class="chip">${n}</button>`);
    b.onclick = () => (q('#pf-conc').value = n);
    q('#pf-conc-chips').appendChild(b);
  }

  // İki onay kutusu (Genel ve Konuşma sekmesi) aynı değeri gösterir
  const setSpeech = (on) => {
    p.speech.enabled = on;
    q('#pf-speech').checked = on;
    q('#pf-speech2').checked = on;
    q('#pf-speech-ask').classList.toggle('on', on);
  };
  q('#pf-speech').onchange = (e) => setSpeech(e.target.checked);
  q('#pf-speech2').onchange = (e) => setSpeech(e.target.checked);
  setSpeech(!!p.speech.enabled);
  const setOcr = (on) => {
    p.ocr.enabled = on;
    q('#pf-ocr').checked = on;
    q('#pf-ocr2').checked = on;
    q('#pf-ocr-ask').classList.toggle('on', on);
  };
  q('#pf-ocr').onchange = (e) => setOcr(e.target.checked);
  q('#pf-ocr2').onchange = (e) => setOcr(e.target.checked);
  setOcr(!!p.ocr.enabled);

  paintType();
  paintMode();

  const res = await openModal({
    title: isNew ? t('pf.titleNew') : t('pf.titleEdit', { name: p.name }), iconName: isNew ? 'plus' : 'gear', width: 720, body,
    buttons: [
      { label: t('common.cancel'), value: null },
      {
        label: isNew ? t('pf.create') : t('common.save'), cls: 'primary',
        onClick: async () => {
          const name = q('#pf-name').value.trim();
          let bad = false;
          if (!name) { q('#pf-name').classList.add('invalid'); bad = true; }
          if (!p.sourceExts.length && p.sourceMode === 'folder') { toast(t('pf.errExt'), { type: 'err' }); bad = true; }
          if (isNew && !sourcePath) { q('#pf-path').classList.add('invalid'); bad = true; }
          if (bad) { showTab('general'); return false; }
          const form = {
            id: project ? project.id : undefined, name, type: p.type, sourceExts: p.sourceExts, targetExt: q('#pf-target').value,
            sourceMode: p.sourceMode, includeSubfolders: q('#pf-sub').checked,
            concurrency: Number(q('#pf-conc').value) || 2, folderId: folders ? q('#pf-folder').value || null : p.folderId,
            ocr: { enabled: p.type === 'image' && q('#pf-ocr').checked, languages: p.ocr.languages },
            speech: { enabled: p.type !== 'image' && q('#pf-speech').checked, model: q('#pf-model').value, language: q('#pf-lang').value, perWindow: q('#pf-window').checked },
            options: readOutput(), color: p.color, notes: p.notes || '', sourcePath,
          };
          return window.api.saveProject(form);
        },
      },
    ],
  });
  return res || null;
}
