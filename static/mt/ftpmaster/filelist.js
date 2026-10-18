'use strict';

// Yerel ve uzak panelin ortak dosya listesi: sütun başlıkları (tıklayınca sıralar), çoklu seçim
// (Ctrl / Shift / Ctrl+A), klavye, sağ tık ve paneller arası sürükle-bırak.

const DRAG_TYPE = 'application/x-ftpm-files';

class FileList {
  /**
   * @param {HTMLElement} el   .file-list
   * @param {object} o
   * @param {'local'|'remote'} o.kind
   * @param {Function} o.onOpen       (item) => void      çift tık / Enter
   * @param {Function} o.onUp         () => void          ".." / Backspace
   * @param {Function} o.onContext    (event, items) => void   items boşsa boş alana sağ tık
   * @param {Function} o.onDropItems  ({ from, items, paths }) => void
   * @param {Function} o.onKey        (event, items) => void   Delete, F2 vb.
   */
  constructor(el, o) {
    this.el = el;
    this.o = o;
    this.items = [];
    this.view = [];
    this.selected = new Set();
    this.anchor = null;
    this.sort = { key: 'name', dir: 1 };
    this.canUp = false;

    el.innerHTML = `<div class="fl-head">
        <button data-k="name">${esc(t('site.colName'))}</button>
        <button data-k="size">${esc(t('site.colSize'))}</button>
        <button data-k="mtime" class="c-date">${esc(t('site.colDate'))}</button>
      </div><div class="fl-body"></div>`;
    this.head = el.querySelector('.fl-head');
    this.body = el.querySelector('.fl-body');
    this.head.querySelectorAll('button').forEach((b) => (b.onclick = () => {
      const k = b.dataset.k;
      this.sort = { key: k, dir: this.sort.key === k ? -this.sort.dir : 1 };
      this.render();
    }));

    this.body.addEventListener('mousedown', (e) => {
      if (!e.target.closest('.row') && e.button === 0) { this.selected.clear(); this.paintSel(); }
    });
    this.body.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      const row = e.target.closest('.row');
      if (!row || row.dataset.up) { this.selected.clear(); this.paintSel(); return o.onContext(e, []); }
      const it = this.view[row.dataset.i];
      if (!this.selected.has(it.path)) { this.selected.clear(); this.selected.add(it.path); this.anchor = it.path; this.paintSel(); }
      o.onContext(e, this.selectedItems());
    });
    el.addEventListener('keydown', (e) => this.onKeyDown(e));

    // Sürükle-bırak hedefi: diğer panelden gelen öğeler veya Windows Gezgini'nden dosyalar
    let depth = 0;
    const accepts = (e) => e.dataTransfer.types.includes(DRAG_TYPE) ? this.dragFrom !== o.kind : (o.kind === 'remote' && e.dataTransfer.types.includes('Files'));
    el.addEventListener('dragenter', (e) => { if (!accepts(e)) return; depth++; el.classList.add('drop-here'); });
    el.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; el.classList.remove('drop-here'); } });
    el.addEventListener('dragover', (e) => { if (accepts(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
    el.addEventListener('drop', (e) => {
      depth = 0;
      el.classList.remove('drop-here');
      if (!accepts(e)) return;
      e.preventDefault();
      const raw = e.dataTransfer.getData(DRAG_TYPE);
      if (raw) {
        const d = JSON.parse(raw);
        if (d.from !== o.kind) o.onDropItems({ from: d.from, items: d.items });
      } else if (e.dataTransfer.files.length) {
        o.onDropItems({ from: 'explorer', paths: [...e.dataTransfer.files].map((f) => window.api.pathForFile(f)).filter(Boolean) });
      }
    });
  }

  setLoading() {
    this.body.innerHTML = `<div class="loading"><span class="spin"></span>${esc(t('site.loading'))}</div>`;
  }

  setError(msg) {
    this.items = [];
    this.view = [];
    this.body.innerHTML = '';
    if (this.canUp) this.body.appendChild(this.upRow());
    this.body.appendChild(h(`<div class="err-note">${icon('x')} ${esc(msg)}</div>`));
  }

  setItems(items, { canUp = false, keepSelection = false } = {}) {
    this.items = items;
    this.canUp = canUp;
    if (!keepSelection) { this.selected.clear(); this.anchor = null; }
    this.render();
  }

  selectedItems() {
    return this.view.filter((x) => this.selected.has(x.path));
  }

  selectByName(name) {
    const it = this.view.find((x) => x.name === name);
    if (!it) return;
    this.selected = new Set([it.path]);
    this.anchor = it.path;
    this.paintSel();
    this.body.querySelector(`.row[data-i="${this.view.indexOf(it)}"]`)?.scrollIntoView({ block: 'nearest' });
  }

  upRow() {
    const r = h(`<div class="row up" data-up="1"><span class="c-name">${icon('up', 'ico-up')}<span class="nm">..</span></span><span></span><span class="c-date"></span></div>`);
    r.addEventListener('dblclick', () => this.o.onUp());
    return r;
  }

  render() {
    const { key, dir } = this.sort;
    const cmp = (a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      let r = 0;
      if (key === 'size') r = (a.size || 0) - (b.size || 0);
      else if (key === 'mtime') r = (a.mtime || 0) - (b.mtime || 0);
      if (!r) r = a.name.localeCompare(b.name, LANG, { numeric: true, sensitivity: 'base' });
      return r * dir;
    };
    this.view = [...this.items].sort(cmp);
    this.head.querySelectorAll('button').forEach((b) => {
      b.classList.toggle('sorted', b.dataset.k === key);
      b.dataset.dir = dir > 0 ? 'asc' : 'desc';
    });

    const frag = document.createDocumentFragment();
    if (this.canUp) frag.appendChild(this.upRow());
    this.view.forEach((it, i) => {
      const ico = it.isDir ? icon(it.isLink ? 'link' : 'folder', 'ico-dir') : icon(it.isLink ? 'link' : 'file', it.isLink ? 'ico-link' : 'ico-file');
      const date = it.mtime ? formatDate(it.mtime) : (it.raw || '');
      const row = h(`<div class="row ${this.selected.has(it.path) ? 'sel' : ''} ${it.name.startsWith('.') ? 'dim' : ''}" data-i="${i}" draggable="true">
        <span class="c-name">${ico}<span class="nm">${esc(it.name)}</span></span>
        <span class="c-size">${it.isDir ? '' : esc(formatSize(it.size))}</span>
        <span class="c-date">${esc(date)}</span></div>`);
      row.title = it.name;
      frag.appendChild(row);
    });
    this.body.innerHTML = '';
    this.body.appendChild(frag);
    if (!this.view.length) this.body.appendChild(h(`<div class="empty-note">${esc(t('site.emptyDir'))}</div>`));

    this.body.querySelectorAll('.row[data-i]').forEach((row) => {
      const it = this.view[row.dataset.i];
      row.addEventListener('mousedown', (e) => { if (e.button === 0) this.click(it, e); });
      row.addEventListener('dblclick', () => this.o.onOpen(it));
      row.addEventListener('dragstart', (e) => {
        if (!this.selected.has(it.path)) { this.selected = new Set([it.path]); this.paintSel(); }
        FileList.prototype.dragFrom = this.o.kind;
        e.dataTransfer.effectAllowed = 'copy';
        e.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ from: this.o.kind, items: this.selectedItems() }));
      });
      row.addEventListener('dragend', () => { FileList.prototype.dragFrom = null; });
    });
  }

  click(it, e) {
    if (e.shiftKey && this.anchor) {
      const a = this.view.findIndex((x) => x.path === this.anchor);
      const b = this.view.indexOf(it);
      if (!e.ctrlKey) this.selected.clear();
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) this.selected.add(this.view[i].path);
    } else if (e.ctrlKey) {
      this.selected.has(it.path) ? this.selected.delete(it.path) : this.selected.add(it.path);
      this.anchor = it.path;
    } else if (!this.selected.has(it.path) || this.selected.size === 1) {
      // Çoklu seçim üzerinde sürüklemeye başlamak seçimi bozmasın
      this.selected = new Set([it.path]);
      this.anchor = it.path;
    }
    this.paintSel();
    this.el.focus({ preventScroll: true });
  }

  paintSel() {
    this.body.querySelectorAll('.row[data-i]').forEach((r) => r.classList.toggle('sel', this.selected.has(this.view[r.dataset.i].path)));
  }

  onKeyDown(e) {
    if (e.target.tagName === 'INPUT') return;
    const items = this.selectedItems();
    if (e.ctrlKey && e.key.toLowerCase() === 'a') {
      e.preventDefault();
      this.selected = new Set(this.view.map((x) => x.path));
      this.paintSel();
      return;
    }
    if (e.key === 'Enter' && items.length === 1) { e.preventDefault(); this.o.onOpen(items[0]); return; }
    if (e.key === 'Backspace') { e.preventDefault(); this.o.onUp(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const cur = this.view.findIndex((x) => x.path === this.anchor);
      const next = Math.max(0, Math.min(this.view.length - 1, cur + (e.key === 'ArrowDown' ? 1 : -1)));
      const it = this.view[next];
      if (!it) return;
      if (!e.shiftKey) this.selected.clear();
      this.selected.add(it.path);
      this.anchor = it.path;
      this.paintSel();
      this.body.querySelector(`.row[data-i="${next}"]`)?.scrollIntoView({ block: 'nearest' });
      return;
    }
    this.o.onKey(e, items);
  }
}
