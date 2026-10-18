'use strict';

// Uygulama ayarları penceresi, Gece/Gündüz düğmesi ve hesap durumu (ana pencere ve proje penceresi ortak)

// --- Mastertool hesabı ve senkron durumu -------------------------------------------
let acct = { loggedIn: false };
const acctListeners = [];

function syncText(st) {
  if (!st.syncEnabled || st.state === 'off') return t('sync.off');
  if (st.state === 'syncing') return t('sync.syncing');
  if (st.state === 'offline') return t('sync.offline');
  if (st.state === 'error') {
    if (st.error === 'decrypt_failed') return t('sync.errDecrypt');
    if (st.error === 'too_large') return t('sync.errTooLarge');
    return t('sync.error', { msg: st.errorMessage || st.error });
  }
  return st.lastSyncAt ? t('acct.lastSync', { time: formatDate(st.lastSyncAt) }) : t('acct.never');
}

function onAcct(fn) { acctListeners.push(fn); fn(acct); }
function setAcct(st) {
  acct = st;
  const live = document.querySelector('#acct-status');
  if (live) live.textContent = syncText(acct);
  acctListeners.forEach((fn) => fn(acct));
}
window.api.onAccountStatus(setAcct);
window.api.accountState().then(setAcct);

async function logout() {
  const ok = await confirmBox(t('acct.logout'), esc(t('acct.logoutMsg')), { okText: t('acct.logout') });
  if (ok) window.api.logout();
}

// Hızlı tema düğmesi: Gece ↔ Gündüz
function themeButton(btn, getSettings) {
  const paint = () => {
    const s = getSettings();
    const dark = (s.appTheme || 'system') !== 'light' && !(s.appTheme === 'system' && matchMedia('(prefers-color-scheme: light)').matches);
    btn.innerHTML = icon(dark ? 'sun' : 'moon');
    btn.title = dark ? t('set.toLight') : t('set.toDark');
  };
  btn.onclick = async () => {
    const dark = !matchMedia('(prefers-color-scheme: light)').matches;
    await window.api.setSettings({ appTheme: dark ? 'light' : 'dark' });
  };
  matchMedia('(prefers-color-scheme: light)').addEventListener('change', paint);
  paint();
  return paint;
}

const options = (list, v) => list.map(([k, l]) => `<option value="${k}" ${String(k) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('');
const modelLabel = (k) => `${t(`speech.model.${k}`)} · ~${FORMATS.SPEECH_MODELS[k].mb} MB`;

// Konuşma modelleri listesi (indir / sil / iptal); ayarlarda ve proje formunda kullanılır
function speechModelsBox() {
  const box = h('<div class="models"></div>');
  let st = null;
  let dl = null;
  const paint = () => {
    if (!st) return;
    box.innerHTML = '';
    if (!st.engine) {
      box.appendChild(h(`<div class="model-note">${icon('info')}<span>${esc(st.canDownloadEngine ? t('speech.engineAuto') : t('speech.engineMissing'))}</span></div>`));
    }
    for (const k of Object.keys(FORMATS.SPEECH_MODELS)) {
      const m = st.models[k] || {};
      const busy = st.downloading.includes(k) || (dl && dl.model === k);
      const row = h(`<div class="model-row">
        <span class="model-name">${esc(t(`speech.model.${k}`))}</span>
        <span class="model-sub">${m.installed ? esc(t('speech.installed', { size: formatSize(m.size) })) : esc(`~${FORMATS.SPEECH_MODELS[k].mb} MB`)}</span>
        <span class="model-act"></span></div>`);
      const act = row.querySelector('.model-act');
      if (busy) {
        const pct = dl && dl.model === k ? Math.round(dl.progress * 100) : 0;
        act.appendChild(h(`<div class="progress mini"><div style="width:${pct}%"></div></div>`));
        const c = h(`<button class="btn sm ghost" type="button">${esc(t('common.cancel'))}</button>`);
        c.onclick = () => window.api.speechCancelDownload(k);
        act.appendChild(c);
      } else if (m.installed) {
        const b = h(`<button class="btn sm ghost danger" type="button">${icon('trash')}${esc(t('common.delete'))}</button>`);
        b.onclick = async () => { await window.api.speechDeleteModel(k); refresh(); };
        act.appendChild(b);
      } else {
        const b = h(`<button class="btn sm" type="button">${icon('download')}${esc(t('speech.download'))}</button>`);
        b.onclick = async () => {
          st.downloading.push(k);
          paint();
          const r = await window.api.speechDownload(k);
          if (!r.ok) toast(t('speech.downloadFailed'), { type: 'err', sub: r.message, timeout: 8000 });
          refresh();
        };
        act.appendChild(b);
      }
      box.appendChild(row);
    }
  };
  const refresh = async () => { st = await window.api.speechStatus(); paint(); };
  const off = window.api.onSpeechDownload((x) => {
    if (!box.isConnected) return off();
    const prev = dl;
    dl = x && x.what === 'model' ? x : null;
    if (!x && prev) refresh(); else paint();
  });
  refresh();
  return box;
}

// Hakkında › açık kaynak bileşenleri
const OSS = [
  ['Convert Master', 'MIT'], ['Electron', 'MIT'], ['Chromium', 'BSD-3-Clause +'], ['Node.js', 'MIT'],
  ['FFmpeg (ffmpeg-static)', 'GPL-3.0'], ['sharp', 'Apache-2.0'], ['libvips', 'LGPL-3.0'],
  ['whisper.cpp', 'MIT'], ['Whisper models (OpenAI)', 'MIT'], ['tesseract.js / Tesseract OCR', 'Apache-2.0'], ['extract-zip', 'BSD-2-Clause'], ['@napi-rs/keyring', 'MIT'],
];

// Bölümlü ayarlar penceresi (Mastertool standardı): Genel · Hesap · Dönüştürme · Konuşma · Depolama · Hakkında
// OCR dil verileri (yüklü / indir / sil); getSelected verilirse önce seçili diller gösterilir
function ocrLangsBox(getSelected) {
  const box = h('<div class="models"></div>');
  let st = null;
  let dl = null;
  const paint = () => {
    if (!st) return;
    box.innerHTML = '';
    const sel = getSelected ? getSelected() : [];
    const list = getSelected ? sel : FORMATS.OCR_LANGS;
    for (const k of list) {
      const m = st.langs[k] || {};
      const busy = st.downloading.includes(k) || (dl && dl.lang === k);
      const row = h(`<div class="model-row"><span class="model-name">${esc(langName(FORMATS.OCR_ISO[k]))}</span>
        <span class="model-sub">${m.installed ? esc(t('speech.installed', { size: formatSize(m.size) })) : esc(t('ocr.notInstalled'))}</span><span class="model-act"></span></div>`);
      const act = row.querySelector('.model-act');
      if (busy) {
        const pct = dl && dl.lang === k ? Math.round(dl.progress * 100) : 0;
        act.appendChild(h(`<div class="progress mini"><div style="width:${pct}%"></div></div>`));
        const c = h(`<button class="btn sm ghost" type="button">${esc(t('common.cancel'))}</button>`);
        c.onclick = () => window.api.ocrCancelDownload(k);
        act.appendChild(c);
      } else if (m.installed) {
        const b = h(`<button class="btn sm ghost danger" type="button">${icon('trash')}${esc(t('common.delete'))}</button>`);
        b.onclick = async () => { await window.api.ocrDelete(k); refresh(); };
        act.appendChild(b);
      } else {
        const b = h(`<button class="btn sm" type="button">${icon('download')}${esc(t('speech.download'))}</button>`);
        b.onclick = async () => {
          st.downloading.push(k);
          paint();
          const r = await window.api.ocrDownload(k);
          if (!r.ok) toast(t('ocr.downloadFailed'), { type: 'err', sub: r.message, timeout: 8000 });
          refresh();
        };
        act.appendChild(b);
      }
      box.appendChild(row);
    }
  };
  const refresh = async () => { st = await window.api.ocrStatus(); paint(); };
  const off = window.api.onSpeechDownload((x) => {
    if (!box.isConnected) return off();
    const prev = dl;
    dl = x && x.what === 'ocr' ? x : null;
    if (!x && prev) refresh(); else paint();
  });
  document.addEventListener('ocr-langs-changed', () => box.isConnected && paint());
  refresh();
  return box;
}

const langName = (() => {
  let dn = null;
  try { dn = new Intl.DisplayNames([LANG], { type: 'language' }); } catch { /* eski motor */ }
  return (code) => {
    if (!code) return '';
    if (code === 'auto') return t('speech.langAuto');
    try { const n = dn && dn.of(code); return n ? n.charAt(0).toLocaleUpperCase(LANG) + n.slice(1) : code; } catch { return code; }
  };
})();

async function openSettings(s, startTab = 'general') {
  let appTheme = s.appTheme || 'system';
  const about = await window.api.about();
  const langOptions = Object.entries(I18N.LANGUAGES)
    .map(([code, l]) => `<option value="${code}" ${code === LANG ? 'selected' : ''}>${esc(l.name)}</option>`).join('');
  const tabs = [
    ['general', 'gear', t('set.general')],
    ['account', 'user', t('set.account')],
    ['conversion', 'layers', t('set.conversion')],
    ['speech', 'mic', t('set.speech')],
    ['ocr', 'text', t('set.ocr')],
    ['storage', 'hdd', t('set.storage')],
    ['about', 'bolt', t('set.about')],
  ];
  const email = (acct.user && acct.user.email) || acct.email || '';
  const body = h(`<div class="set-wrap">
    <nav class="set-nav">${tabs.map(([k, ic, label]) => `<button type="button" data-tab="${k}">${icon(ic)}<span>${esc(label)}</span></button>`).join('')}</nav>
    <div class="set-pages">
      <section data-page="general">
        <div class="field"><label>${esc(t('set.language'))}</label><select class="input" id="s-lang">${langOptions}</select>
          <small class="set-hint">${esc(t('set.languageHint'))}</small></div>
        <div class="field"><label>${esc(t('set.theme'))}</label>
          <div class="seg" id="s-theme">
            <button type="button" data-v="dark">${icon('moon')}${esc(t('set.themeDark'))}</button>
            <button type="button" data-v="light">${icon('sun')}${esc(t('set.themeLight'))}</button>
            <button type="button" data-v="system">${icon('monitor')}${esc(t('set.themeSystem'))}</button>
          </div></div>
        <div class="section-title">${esc(t('set.startup'))}</div>
        <label class="check"><input type="checkbox" id="s-login" ${about.openAtLogin ? 'checked' : ''}>
          <span>${esc(t('set.openAtLogin'))}<small>${esc(t('set.openAtLoginHint'))}</small></span></label>
        <label class="check"><input type="checkbox" id="s-min" ${s.minimizeToTray ? 'checked' : ''}>
          <span>${esc(t('set.minTray'))}<small>${esc(t('set.minTrayHint'))}</small></span></label>
        <label class="check"><input type="checkbox" id="s-close" ${s.closeToTray ? 'checked' : ''}>
          <span>${esc(t('set.closeTray'))}<small>${esc(t('set.closeTrayHint'))}</small></span></label>
      </section>

      <section data-page="account">
        <div class="acct-box">
          <div class="acct-who">${icon('user')}<span>${esc(t('acct.signedInAs', { email }))}</span></div>
          <label class="check"><input type="checkbox" id="s-sync" ${acct.syncEnabled ? 'checked' : ''}>
            <span>${esc(t('acct.syncToggle'))}<small>${esc(t('acct.syncHint'))}</small></span></label>
          <div class="acct-status">${icon('cloud')}<span id="acct-status">${esc(syncText(acct))}</span></div>
          <div class="acct-actions">
            <button class="btn sm" type="button" id="s-syncnow">${icon('refresh')}${esc(t('acct.syncNow'))}</button>
            <button class="btn sm" type="button" id="s-delremote">${icon('trash')}${esc(t('acct.deleteRemote'))}</button>
          </div>
          <div class="acct-actions">
            <button class="btn sm" type="button" id="s-web">${icon('open')}${esc(t('acct.myAccount'))}</button>
            <span style="flex:1"></span>
            <button class="btn sm danger" type="button" id="s-logout">${icon('logout')}${esc(t('acct.logout'))}</button>
          </div>
        </div>
      </section>

      <section data-page="conversion">
        <div class="field"><label>${esc(t('set.defaultConcurrency'))}</label><input class="input" id="s-conc" type="number" min="1" max="32" value="${esc(s.defaultConcurrency || 2)}" style="max-width:160px">
          <small class="set-hint">${esc(t('set.defaultConcurrencyHint'))}</small></div>
        <div class="field"><label>${esc(t('set.speechConcurrency'))}</label><input class="input" id="s-sconc" type="number" min="1" max="4" value="${esc(s.speechConcurrency || 1)}" style="max-width:160px">
          <small class="set-hint">${esc(t('set.speechConcurrencyHint'))}</small></div>
      </section>

      <section data-page="speech">
        <div class="field"><label>${esc(t('set.speechModel'))}</label>
          <select class="input" id="s-model">${options(Object.keys(FORMATS.SPEECH_MODELS).map((k) => [k, modelLabel(k)]), s.speechModel || 'base')}</select></div>
        <div class="section-title">${esc(t('pf.models'))}</div>
        <div id="s-models"></div>
        <small class="set-hint">${esc(t('pf.speechNote'))}</small>
      </section>

      <section data-page="ocr">
        <div class="field"><label>${esc(t('set.ocrLangs'))}</label><div class="ext-chips" id="s-ocr-langs"></div>
          <small class="set-hint">${esc(t('pf.ocrLangsHint'))}</small></div>
        <div class="section-title">${esc(t('pf.ocrData'))}</div>
        <div id="s-ocr-models"></div>
        <small class="set-hint">${esc(t('pf.ocrNote'))}</small>
      </section>

      <section data-page="storage">
        <div class="storage" id="s-storage"><div class="empty-note">…</div></div>
      </section>

      <section data-page="about">
        <div class="about-head">
          <img src="icon.png" alt="">
          <div><div class="about-name">Convert Master</div>
            <div class="about-ver">${esc(t('about.version', { version: about.version }))}</div></div>
        </div>
        <div class="set-hint">${esc(t('about.family'))}</div>
        <div class="acct-actions">
          <button class="btn sm" type="button" id="s-update">${icon('refresh')}${esc(t('about.checkUpdate'))}</button>
          <span class="about-update" id="s-update-result"></span>
        </div>
        <div class="section-title">${esc(t('about.licenses'))}</div>
        <div class="set-hint">${esc(t('about.licensesIntro'))}</div>
        <ul class="oss">${OSS.map(([n, l]) => `<li><span>${esc(n)}</span><span>${esc(l)}</span></li>`).join('')}</ul>
        <div class="acct-actions">
          <button class="btn sm" type="button" id="s-licenses">${icon('file')}${esc(t('about.chromium'))}</button>
          <span class="set-hint">Electron ${esc(about.electron)} · Chromium ${esc(about.chrome)}${about.ffmpeg ? ` · FFmpeg ${esc(about.ffmpeg)}` : ''}</span>
        </div>
      </section>
    </div>
  </div>`);

  const q = (sel) => body.querySelector(sel);
  const showTab = (k) => {
    body.querySelectorAll('.set-nav button').forEach((b) => b.classList.toggle('on', b.dataset.tab === k));
    body.querySelectorAll('.set-pages section').forEach((p) => p.classList.toggle('hidden', p.dataset.page !== k));
  };
  body.querySelectorAll('.set-nav button').forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  showTab(startTab);
  q('#s-models').replaceWith(speechModelsBox());
  q('#s-ocr-models').replaceWith(ocrLangsBox());
  let ocrLangs = [...(s.ocrLanguages || FORMATS.defaultOcr().languages)];
  const paintOcrLangs = () => {
    const el = q('#s-ocr-langs');
    el.innerHTML = '';
    for (const l of FORMATS.OCR_LANGS) {
      const b = h(`<button type="button" class="ext-chip all ${ocrLangs.includes(l) ? 'on' : ''}">${esc(langName(FORMATS.OCR_ISO[l]))}</button>`);
      b.onclick = () => {
        if (ocrLangs.includes(l)) { if (ocrLangs.length > 1) ocrLangs = ocrLangs.filter((x) => x !== l); }
        else if (ocrLangs.length < 6) ocrLangs = [...ocrLangs, l];
        paintOcrLangs();
      };
      el.appendChild(b);
    }
  };
  paintOcrLangs();

  // Depolama: boyutlar ve temizlik (anında uygulanır)
  const paintStorage = async () => {
    const info = await window.api.storageInfo();
    const el = q('#s-storage');
    el.innerHTML = `
      <div class="st-row">${icon('layers')}<span>${esc(t('set.converted'))}</span><b>${formatSize(info.converted)}</b>
        <button class="btn sm ghost" data-a="open-converted">${icon('folder')}${esc(t('common.open'))}</button>
        <button class="btn sm ghost danger" data-a="clear-converted" ${info.converted ? '' : 'disabled'}>${icon('trash')}${esc(t('set.clearConverted'))}</button></div>
      <div class="st-row">${icon('image')}<span>${esc(t('set.previewCache'))}</span><b>${formatSize(info.cache)}</b>
        <span></span><button class="btn sm ghost danger" data-a="clear-cache" ${info.cache ? '' : 'disabled'}>${icon('broom')}${esc(t('set.clearCache'))}</button></div>
      <div class="st-row">${icon('mic')}<span>${esc(t('set.models'))}</span><b>${formatSize(info.models)}</b>
        <button class="btn sm ghost" data-a="open-models">${icon('folder')}${esc(t('common.open'))}</button><span></span></div>
      <div class="set-hint">${esc(t('set.storageHint'))}</div>
      <div class="hint st-path">${esc(info.dir)}</div>`;
    el.querySelector('[data-a="open-converted"]').onclick = () => window.api.openStorage('converted');
    el.querySelector('[data-a="open-models"]').onclick = () => window.api.openStorage('models');
    el.querySelector('[data-a="clear-cache"]').onclick = async () => { await window.api.clearCache(); paintStorage(); };
    el.querySelector('[data-a="clear-converted"]').onclick = async () => {
      const r = await clearOutputsDialog(t('set.clearConverted'), t('set.clearConvertedMsg'));
      if (!r) return;
      await window.api.clearConverted(r.transcripts);
      toast(t('set.clearedConverted'), { type: 'ok' });
      paintStorage();
    };
  };
  paintStorage();

  // Tema seçimi anında uygulanır (önizleme); İptal edilirse eski temaya döner
  const originalTheme = appTheme;
  const setTheme = (v) => {
    appTheme = v;
    body.querySelectorAll('#s-theme button').forEach((b) => b.classList.toggle('on', b.dataset.v === v));
    window.api.setSettings({ appTheme: v });
  };
  body.querySelectorAll('#s-theme button').forEach((b) => (b.onclick = () => setTheme(b.dataset.v)));
  body.querySelectorAll('#s-theme button').forEach((b) => b.classList.toggle('on', b.dataset.v === appTheme));

  // Hesap bölümündeki işlemler anında uygulanır (Kaydet beklemez)
  q('#s-sync').onchange = async (e) => {
    const on = e.target.checked;
    const r = await window.api.setSyncEnabled(on);
    if (!r.ok) { e.target.checked = !on; toast(t('sync.error', { msg: r.code }), { type: 'err' }); }
  };
  q('#s-syncnow').onclick = () => window.api.syncNow();
  q('#s-delremote').onclick = async () => {
    const ok = await confirmBox(t('acct.deleteRemote'), esc(t('acct.deleteRemoteMsg')));
    if (!ok) return;
    const r = await window.api.deleteRemoteLibrary();
    if (r.ok) { q('#s-sync').checked = false; toast(t('acct.deleteRemoteDone'), { type: 'ok' }); }
    else toast(t('sync.error', { msg: r.code }), { type: 'err' });
  };
  q('#s-web').onclick = () => window.api.openWeb('account');
  q('#s-logout').onclick = logout;

  // Hakkında: yeni sürüm denetimi ve lisanslar
  q('#s-update').onclick = async () => {
    const out = q('#s-update-result');
    out.className = 'about-update';
    out.textContent = t('about.checking');
    const r = await window.api.checkUpdate();
    if (!r.ok) { out.classList.add('err'); out.textContent = t('about.checkFailed', { msg: r.message || r.code }); return; }
    if (r.newer) { out.classList.add('new'); out.textContent = `${t('update.available', { version: r.latest })} — ${t('update.hint')}`; }
    else { out.classList.add('ok'); out.textContent = t('about.upToDate'); }
  };
  q('#s-licenses').onclick = () => window.api.openLicenses();

  const clamp = (v, min, max, def) => { const n = Number(v); return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : def; };
  const res = await openModal({
    title: t('set.title'), iconName: 'gear', width: 760, body,
    buttons: [
      { label: t('common.cancel'), value: null },
      {
        label: t('common.save'), cls: 'primary',
        onClick: () => ({
          appTheme,
          language: q('#s-lang').value,
          openAtLogin: q('#s-login').checked,
          minimizeToTray: q('#s-min').checked,
          closeToTray: q('#s-close').checked,
          defaultConcurrency: clamp(q('#s-conc').value, 1, 32, 2),
          speechConcurrency: clamp(q('#s-sconc').value, 1, 4, 1),
          speechModel: q('#s-model').value,
          ocrLanguages: ocrLangs,
        }),
      },
    ],
  });
  if (!res) {
    if (appTheme !== originalTheme) window.api.setSettings({ appTheme: originalTheme });
    return null;
  }
  const langChanged = res.language !== LANG;
  if (!langChanged) delete res.language; // dil değişmediyse pencereyi yeniden yükleme
  await window.api.setSettings(res);
  if (!langChanged) toast(t('set.saved'), { type: 'ok' });
  return res;
}

// "Çevrilmiş dosyaları sil" onayı; metinler isteğe bağlı
async function clearOutputsDialog(title, message, { speech = true } = {}) {
  return openModal({
    title, iconName: 'trash',
    body: `<div style="color:var(--text-2);line-height:1.5">${message}</div>
      ${speech ? `<label class="check"><input type="checkbox" id="cd-tr"><span>${esc(t('set.alsoTranscripts'))}</span></label>` : ''}`,
    buttons: [
      { label: t('common.giveUp'), value: null },
      { label: t('common.delete'), cls: 'primary danger-primary', onClick: (m) => ({ transcripts: !!(m.querySelector('#cd-tr') || {}).checked }) },
    ],
  });
}
