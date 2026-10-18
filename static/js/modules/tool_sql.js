// Araçlar › SQL Master (web): SQLite (yükle ya da DATA_DIR yolu) + MySQL/PostgreSQL (sürücü kuruluysa).
// Sol: tablo listesi; sağ: sorgu editörü (Ctrl+Enter) + sayfalı sonuç tablosu + Excel dışa aktarım (SheetJS, tarayıcıda).
import { api } from '../api.js';
import { clear, confirmDialog, h, onLeave, pageHead, toast, toastError } from '../ui.js';
import { btn, downloadText, inp, lab, loadScript, progress, sel, setStatus, shell, status, uploadRaw } from './tool_mt.js';

const PAGE = 100;

export async function render(view, params, ctx) {
  const st = status('Bağlı değil');
  let sid = null, drivers = { sqlite: true }, files = [], lastSql = '', page = 1, total = 0, readonly = false;

  // --- Bağlan formu ---
  const driver = sel([['sqlite', 'SQLite'], ['mysql', 'MySQL'], ['postgres', 'PostgreSQL']], 'sqlite');
  const fileSel = sel([['', '— Yüklenen dosya —']], '');
  const path = inp({ cls: 'w-l', placeholder: 'ya da DATA_DIR altında yol (ör. caymaz.db)' });
  const upIn = h('input', { type: 'file', accept: '.db,.sqlite,.sqlite3,.db3', style: { display: 'none' }, onchange: () => upIn.files[0] && uploadDb(upIn.files[0]) });
  const prog = progress();
  const host = inp({ cls: 'w-m', placeholder: 'sunucu' });
  const port = inp({ cls: 'w-s', type: 'number', placeholder: '3306' });
  const user = inp({ cls: 'w-m', placeholder: 'kullanıcı', autocomplete: 'off' });
  const pass = inp({ cls: 'w-m', type: 'password', placeholder: 'parola', autocomplete: 'new-password' });
  const dbname = inp({ cls: 'w-m', placeholder: 'veritabanı' });
  const sqliteBox = h('span', { class: 'mt-bar' }, lab('Dosya', fileSel), lab('Yol', path), btn('Yükle…', { onclick: () => upIn.click() }), btn('Dosyayı sil', { cls: 'sm', onclick: () => delDb() }), upIn);
  const netBox = h('span', { class: 'mt-bar', style: { display: 'none' } }, lab('Sunucu', host), lab('Port', port), lab('Kullanıcı', user), lab('Parola', pass), lab('Veritabanı', dbname));
  driver.addEventListener('change', () => {
    const sq = driver.value === 'sqlite';
    sqliteBox.style.display = sq ? '' : 'none'; netBox.style.display = sq ? 'none' : '';
    port.placeholder = driver.value === 'mysql' ? '3306' : '5432';
    if (!sq && !drivers[driver.value]) toastError(new Error(`${driver.value} sürücüsü sunucuda kurulu değil`));
  });
  const connBtn = btn('Bağlan', { cls: 'primary', onclick: () => connect() });
  const discBtn = btn('Kes', { cls: 'danger', onclick: () => disconnect(), disabled: true });
  const form = h('div', { class: 'mt-form' }, lab('Sürücü', driver), sqliteBox, netBox, connBtn, discBtn, prog);

  // --- Sol: tablolar ---
  const tblList = h('div', { class: 'mt-list' });
  const left = h('div', { class: 'mt-panel' }, h('div', { class: 'mt-bar', style: { marginBottom: '6px' } }, h('b', null, 'Tablolar'), h('span', { class: 'mt-bar right' }, btn('Yenile', { cls: 'sm', onclick: () => loadTables() }))), tblList);

  // --- Sağ: editör + sonuç ---
  const editor = h('textarea', { class: 'mt-area', placeholder: 'SELECT * FROM tablo LIMIT 100;   (Ctrl+Enter çalıştırır)', spellcheck: false, style: { minHeight: '110px' } });
  editor.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(editor.value); } });
  const info = h('span', { class: 'mt-status' });
  const pager = h('span', { class: 'mt-bar right' });
  const result = h('div', { class: 'mt-table-wrap' });
  const right = h('div', { class: 'mt-panel', style: { display: 'flex', flexDirection: 'column', gap: '8px', minWidth: 0 } },
    editor,
    h('div', { class: 'mt-bar' }, btn('Çalıştır', { cls: 'primary', onclick: () => run(editor.value) }), btn('Temizle', { cls: 'sm', onclick: () => { editor.value = ''; } }),
      btn('Excel', { onclick: () => exportExcel() }), btn('CSV', { cls: 'sm', onclick: () => exportCsv() }), info, pager),
    result);
  const body = h('div', { class: 'mt-split', style: { display: 'none' } }, left, right);

  async function loadFiles() {
    try { files = await api.get('/api/tools/sql/files'); clear(fileSel, h('option', { value: '' }, '— Yüklenen dosya —'), files.map(f => h('option', { value: f.name }, `${f.name}`))); } catch (e) { toastError(e); }
  }
  async function uploadDb(f) {
    const fd = new FormData(); fd.append('file', f, f.name);
    try { const r = await uploadRaw('/api/tools/sql/upload', fd, pct => prog.set(pct)); toast(`Yüklendi: ${r.name}`); await loadFiles(); fileSel.value = r.name; } catch (e) { toastError(e); } finally { prog.done(); upIn.value = ''; }
  }
  async function delDb() {
    if (!fileSel.value) return toastError(new Error('Yüklenen dosya seçin'));
    if (!await confirmDialog('Dosyayı sil', `${fileSel.value} sunucudan silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/tools/sql/files/${encodeURIComponent(fileSel.value)}`); loadFiles(); } catch (e) { toastError(e); }
  }
  async function connect() {
    connBtn.disabled = true; setStatus(st, 'Bağlanıyor…');
    const bodyIn = driver.value === 'sqlite' ? { driver: 'sqlite', path: fileSel.value || path.value.trim() }
      : { driver: driver.value, host: host.value.trim(), port: port.value ? Number(port.value) : null, username: user.value.trim(), password: pass.value, database: dbname.value.trim() };
    try {
      const r = await api.post('/api/tools/sql/connect', bodyIn);
      sid = r.sid; readonly = r.readonly; pass.value = '';
      setStatus(st, `Bağlı: ${r.label}`, 'ok'); discBtn.disabled = false; body.style.display = '';
      await loadTables();
    } catch (e) { setStatus(st, e.message, 'err'); toastError(e); } finally { connBtn.disabled = false; }
  }
  async function disconnect() {
    if (sid) { try { await api.post(`/api/tools/sql/disconnect?sid=${encodeURIComponent(sid)}`); } catch { /* */ } }
    sid = null; body.style.display = 'none'; discBtn.disabled = true; setStatus(st, 'Bağlı değil');
  }
  const q = n => (driver.value === 'mysql' ? `\`${n}\`` : `"${n.replace(/"/g, '""')}"`);
  async function loadTables() {
    try {
      const ts = await api.get(`/api/tools/sql/tables?sid=${encodeURIComponent(sid)}`);
      clear(tblList, ts.length ? ts.map(tb => h('div', { class: 'it', title: tb.columns.join(', '), onclick: () => { editor.value = `SELECT * FROM ${q(tb.name)} LIMIT 100`; run(editor.value); } },
        tb.type === 'view' ? '👁' : '▦', tb.name, h('small', null, tb.columns.length ? `${tb.columns.length} sütun` : tb.type))) : h('div', { class: 'muted', style: { padding: '8px' } }, 'Tablo yok'));
    } catch (e) { toastError(e); if (e.status === 404) disconnect(); }
  }
  async function run(sql, p = 1) {
    if (!sql.trim()) return;
    lastSql = sql; page = p;
    try {
      const r = await api.post(`/api/tools/sql/query?sid=${encodeURIComponent(sid)}`, { sql, page: p, page_size: PAGE });
      drawResult(r);
    } catch (e) { clear(result, h('div', { class: 'mt-status err', style: { padding: '10px' } }, e.message)); clear(pager); info.textContent = ''; if (e.status === 404) disconnect(); }
  }
  function drawResult(r) {
    total = r.total || 0;
    if (!r.columns.length) {
      clear(result, h('div', { class: 'mt-status ok', style: { padding: '10px' } }, `Tamam · ${r.rowcount >= 0 ? r.rowcount : 0} satır etkilendi · ${r.ms} ms${readonly ? ' (salt okunur)' : ''}`));
      clear(pager); info.textContent = ''; loadTables(); return;
    }
    clear(result, h('table', { class: 'mt-table' },
      h('thead', null, h('tr', null, h('th', null, '#'), r.columns.map(c => h('th', null, c)))),
      h('tbody', null, r.rows.map((row, i) => h('tr', null, h('td', { class: 'null' }, (r.page - 1) * r.page_size + i + 1),
        row.map(v => h('td', { class: v === null ? 'null' : '', title: v === null ? '' : String(v) }, v === null ? 'NULL' : String(v))))))));
    info.textContent = `${total} satır${r.truncated ? ' (ilk 5000)' : ''} · ${r.ms} ms`;
    const pages = Math.max(1, Math.ceil(total / r.page_size));
    clear(pager, pages > 1 ? [btn('‹', { cls: 'sm', disabled: page <= 1, onclick: () => run(lastSql, page - 1) }), h('span', { class: 'mt-status' }, `${page} / ${pages}`), btn('›', { cls: 'sm', disabled: page >= pages, onclick: () => run(lastSql, page + 1) })] : null);
  }
  async function fetchAll() {
    const rows = []; let cols = [], p = 1;
    for (;;) {
      const r = await api.post(`/api/tools/sql/query?sid=${encodeURIComponent(sid)}`, { sql: lastSql, page: p, page_size: 1000 });
      cols = r.columns; rows.push(...r.rows);
      if (rows.length >= r.total || !r.rows.length) break;
      p++;
    }
    return [cols, rows];
  }
  async function exportExcel() {
    if (!lastSql) return toastError(new Error('Önce bir sorgu çalıştırın'));
    try {
      await loadScript('/static/vendor/xlsx/xlsx.full.min.js');
      const [cols, rows] = await fetchAll();
      const ws = window.XLSX.utils.aoa_to_sheet([cols, ...rows]);
      const wb = window.XLSX.utils.book_new(); window.XLSX.utils.book_append_sheet(wb, ws, 'Sorgu');
      window.XLSX.writeFile(wb, `sorgu-${new Date().toISOString().slice(0, 10)}.xlsx`);
    } catch (e) { toastError(e); }
  }
  async function exportCsv() {
    if (!lastSql) return toastError(new Error('Önce bir sorgu çalıştırın'));
    try {
      const [cols, rows] = await fetchAll();
      const esc = v => { const s = v === null ? '' : String(v); return /[";\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
      downloadText('﻿' + [cols, ...rows].map(r => r.map(esc).join(';')).join('\r\n'), `sorgu-${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv');
    } catch (e) { toastError(e); }
  }

  onLeave(() => { if (sid) api.post(`/api/tools/sql/disconnect?sid=${encodeURIComponent(sid)}`).catch(() => {}); });
  clear(view,
    pageHead('SQL Master', { back: '#/tools', sub: 'SQLite · MySQL · PostgreSQL — sorgu editörü, sayfalı sonuç, Excel', right: st }),
    shell(form, body, h('div', { class: 'small muted' }, 'Uygulamanın kendi veritabanı yalnız salt okunur açılır. Parola yalnız bu oturumda sunucu belleğinde tutulur.')));
  try {
    drivers = await api.get('/api/tools/sql/drivers');
    for (const k of ['mysql', 'postgres']) if (!drivers[k]) driver.querySelector(`option[value=${k}]`).textContent += ' (sürücü yok)';
    await loadFiles();
  } catch (e) { toastError(e); }
}
