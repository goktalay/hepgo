'use strict';

// Aktarım ağacı: her indirme/yükleme bir kök satırdır; klasörler iç içe açılır.
// Sütunlar: Ad (ağaç) | Boyut | İlerleme | Durum — başlıktaki tutamaçlarla genişletilip daraltılır.
// Binlerce dosyada akıcı kalması için yalnızca görünen satırlar çizilir (sanal kaydırma).

const ROW_H = 26;
const FINISHED = ['done', 'error', 'cancelled', 'skipped'];

class TransferTree {
  /**
   * @param {object} o
   * @param {HTMLElement} o.root      .tree
   * @param {number[]} o.cols         sütun genişlikleri (px)
   * @param {Function} o.onColsChange (cols) => void
   * @param {Function} o.onContext    (event, node) => void
   * @param {Function} o.onOpen       (node) => void   çift tık
   * @param {Function} o.onStats      () => void       özet değişti
   */
  constructor(o) {
    this.o = o;
    this.root = o.root;
    this.head = o.root.querySelector('.tree-head');
    this.body = o.root.querySelector('.tree-body');
    this.spacer = o.root.querySelector('.tree-spacer');
    this.rowsEl = o.root.querySelector('.tree-rows');
    this.nodes = new Map();
    this.children = new Map(); // parentId -> [id]
    this.roots = [];           // en yenisi en üstte
    this.collapsed = new Set();
    this.selectedId = null;
    this.flat = [];
    this.cols = (o.cols && o.cols.length === 4 ? o.cols : [200, 72, 150, 120]).slice();
    this.raf = 0;

    this.buildHead();
    this.applyCols();

    this.body.addEventListener('scroll', () => {
      this.head.scrollLeft = this.body.scrollLeft;
      this.paint();
    });
    new ResizeObserver(() => this.paint()).observe(this.body);

    this.rowsEl.addEventListener('mousedown', (e) => {
      const row = e.target.closest('.tr-row');
      if (!row) return;
      const id = row.dataset.id;
      if (e.target.closest('.caret')) { this.toggle(id); return; }
      this.selectedId = id;
      this.paint();
    });
    this.rowsEl.addEventListener('dblclick', (e) => {
      const row = e.target.closest('.tr-row');
      if (!row || e.target.closest('.caret')) return;
      const n = this.nodes.get(row.dataset.id);
      if (n.isDir) this.toggle(n.id); else o.onOpen(n);
    });
    this.body.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      const row = e.target.closest('.tr-row');
      const n = row && this.nodes.get(row.dataset.id);
      if (n) { this.selectedId = n.id; this.paint(); }
      o.onContext(e, n || null);
    });
    this.body.addEventListener('keydown', (e) => {
      const n = this.nodes.get(this.selectedId);
      if (!n) return;
      if (e.key === 'ArrowRight' && n.isDir) { this.collapsed.delete(n.id); this.update(); }
      if (e.key === 'ArrowLeft' && n.isDir) { this.collapsed.add(n.id); this.update(); }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const i = this.flat.findIndex((x) => x.node.id === n.id) + (e.key === 'ArrowDown' ? 1 : -1);
        if (this.flat[i]) { this.selectedId = this.flat[i].node.id; this.scrollTo(i); this.paint(); }
      }
      if (e.key === 'Delete') o.onKey && o.onKey(e, n);
    });
  }

  // --- Sütunlar ----------------------------------------------------------------
  buildHead() {
    const labels = [t('tr.colName'), t('tr.colSize'), t('tr.colProgress'), t('tr.colStatus')];
    this.head.innerHTML = `<div class="tree-head-inner">${labels.map((l, i) => `<div class="th" data-i="${i}"><span>${esc(l)}</span><span class="rz" data-i="${i}"></span></div>`).join('')}</div>`;
    this.head.querySelectorAll('.rz').forEach((rz) => rz.addEventListener('mousedown', (e) => {
      e.preventDefault();
      const i = Number(rz.dataset.i);
      const startX = e.clientX;
      const startW = this.cols[i];
      const rtl = document.documentElement.dir === 'rtl';
      rz.classList.add('active');
      document.body.classList.add('resizing-col');
      const move = (ev) => {
        const dx = (ev.clientX - startX) * (rtl ? -1 : 1);
        this.cols[i] = Math.max(i === 0 ? 120 : 56, Math.min(900, startW + dx));
        this.applyCols();
      };
      const up = () => {
        rz.classList.remove('active');
        document.body.classList.remove('resizing-col');
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
        this.o.onColsChange(this.cols.slice());
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
    }));
  }

  applyCols() {
    this.cols.forEach((w, i) => this.root.style.setProperty(`--c${i}`, w + 'px'));
    this.root.style.setProperty('--tree-w', this.cols.reduce((a, b) => a + b, 0) + 'px');
  }

  // --- Veri ----------------------------------------------------------------------
  apply({ added, changed }) {
    for (const n of added) {
      const node = { ...n, done: 0, files: n.isDir ? 0 : 1, finished: 0, speed: 0, error: null };
      this.nodes.set(n.id, node);
      if (n.parentId) {
        if (!this.children.has(n.parentId)) this.children.set(n.parentId, []);
        this.children.get(n.parentId).push(n.id);
      } else {
        this.roots.unshift(n.id);
        this.selectedId = this.selectedId || n.id;
      }
    }
    for (const c of changed) {
      const n = this.nodes.get(c.id);
      if (n) Object.assign(n, c);
    }
    this.update();
  }

  remove(ids) {
    const kill = (id) => {
      for (const ch of this.children.get(id) || []) kill(ch);
      this.children.delete(id);
      this.nodes.delete(id);
      this.collapsed.delete(id);
    };
    for (const id of ids) kill(id);
    this.roots = this.roots.filter((id) => this.nodes.has(id));
    if (!this.nodes.has(this.selectedId)) this.selectedId = null;
    this.update();
  }

  finishedRoots() {
    return this.roots.map((id) => this.nodes.get(id)).filter((n) => FINISHED.includes(n.status));
  }

  stats() {
    let active = 0;
    let down = 0;
    let up = 0;
    for (const id of this.roots) {
      const n = this.nodes.get(id);
      if (FINISHED.includes(n.status)) continue;
      active++;
      if (n.kind === 'download') down += n.speed || 0; else up += n.speed || 0;
    }
    return { active, down, up, total: this.roots.length };
  }

  toggle(id) {
    this.collapsed.has(id) ? this.collapsed.delete(id) : this.collapsed.add(id);
    this.update();
  }

  scrollTo(i) {
    const top = i * ROW_H;
    if (top < this.body.scrollTop) this.body.scrollTop = top;
    else if (top + ROW_H > this.body.scrollTop + this.body.clientHeight) this.body.scrollTop = top + ROW_H - this.body.clientHeight;
  }

  update() {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => {
      this.raf = 0;
      this.flatten();
      this.paint();
      this.o.onStats();
    });
  }

  flatten() {
    const out = [];
    const walk = (id, depth) => {
      const n = this.nodes.get(id);
      if (!n) return;
      out.push({ node: n, depth });
      if (n.isDir && !this.collapsed.has(id)) for (const ch of this.children.get(id) || []) walk(ch, depth + 1);
    };
    for (const id of this.roots) walk(id, 0);
    this.flat = out;
    this.spacer.style.height = out.length * ROW_H + 'px';
  }

  // --- Çizim ---------------------------------------------------------------------
  statusText(n) {
    const st = n.status;
    if (st === 'error') return t('tr.error');
    if (st === 'cancelled') return t('tr.cancelled');
    if (st === 'skipped') return t('tr.skipped');
    if (st === 'done') return n.isDir ? t('tr.doneFiles', { n: n.files }) : t('tr.done');
    if (st === 'scanning') return t('tr.scanning', { n: n.files });
    if (st === 'retry') return t('tr.retrying');
    if (st === 'queued') return t('tr.queued');
    // aktif
    if (!n.parentId && n.speed) {
      return `${formatSize(n.speed)}/s${n.isDir ? ` · ${n.finished}/${n.files}` : ''}`;
    }
    return n.isDir ? `${n.finished}/${n.files}` : t('tr.active');
  }

  paint() {
    const total = this.flat.length;
    const viewH = this.body.clientHeight || 400;
    const start = Math.max(0, Math.floor(this.body.scrollTop / ROW_H) - 6);
    const end = Math.min(total, start + Math.ceil(viewH / ROW_H) + 12);
    this.rowsEl.style.transform = `translateY(${start * ROW_H}px)`;
    let html = '';
    for (let i = start; i < end; i++) {
      const { node: n, depth } = this.flat[i];
      const pct = n.size > 0 ? Math.min(100, (n.done / n.size) * 100) : FINISHED.includes(n.status) && n.status !== 'error' ? 100 : 0;
      const pctText = n.status === 'skipped' ? '—' : `${pct >= 99.95 || pct === 0 ? Math.round(pct) : pct.toFixed(1)}%`;
      const caret = n.isDir
        ? `<span class="caret ${this.collapsed.has(n.id) ? 'closed' : ''}">${icon('chevronDown')}</span>`
        : '<span class="caret none"></span>';
      const ico = !n.parentId
        ? icon(n.kind === 'download' ? 'download' : 'upload', `kind ${n.kind}`)
        : n.isDir ? icon('folder', 'ico-dir') : icon('file', 'ico-file');
      const sub = !n.parentId && n.isDir ? icon('folder', 'ico-dir') : '';
      const title = esc(n.error ? `${n.name}\n${n.error}` : `${n.src || ''}\n→ ${n.dst || ''}`);
      html += `<div class="tr-row st-${n.status} ${n.id === this.selectedId ? 'sel' : ''} ${n.parentId ? '' : 'root'}" data-id="${n.id}" title="${title}">
        <div class="td c-name" style="padding-inline-start:${6 + depth * 16}px">${caret}${ico}${sub}<span class="nm">${esc(n.name)}</span></div>
        <div class="td c-size">${n.size || !n.isDir ? esc(formatSize(n.size)) : ''}</div>
        <div class="td c-prog"><div class="pbar"><div style="width:${pct}%"></div></div><span class="pct">${pctText}</span></div>
        <div class="td c-status">${n.status === 'error' ? icon('x') : ''}<span>${esc(this.statusText(n))}</span></div>
      </div>`;
    }
    this.rowsEl.innerHTML = html;
    this.root.classList.toggle('empty', !total);
  }
}
