// VOLFAI - ızgara ve alan ele geçirme mantığı (saf, DOM bağımsız)
import { GRID_W, GRID_H, CELL } from './config.js';

export class Grid {
  constructor(w = GRID_W, h = GRID_H) {
    this.w = w;
    this.h = h;
    this.cells = new Uint8Array(w * h);
    this.blocks = [];           // {x,y,size,captured}
    this.interiorTotal = 0;     // yüzde hesabı için toplam iç hücre
    this.claimedInterior = 0;
    this.reset();
  }

  idx(x, y) { return y * this.w + x; }
  inBounds(x, y) { return x >= 0 && y >= 0 && x < this.w && y < this.h; }
  get(x, y) { return this.inBounds(x, y) ? this.cells[this.idx(x, y)] : CELL.CLAIMED; }
  set(x, y, v) { if (this.inBounds(x, y)) this.cells[this.idx(x, y)] = v; }

  reset() {
    this.cells.fill(CELL.EMPTY);
    for (let x = 0; x < this.w; x++) { this.set(x, 0, CELL.CLAIMED); this.set(x, this.h - 1, CELL.CLAIMED); }
    for (let y = 0; y < this.h; y++) { this.set(0, y, CELL.CLAIMED); this.set(this.w - 1, y, CELL.CLAIMED); }
    this.blocks = [];
    this.interiorTotal = (this.w - 2) * (this.h - 2);
    this.claimedInterior = 0;
  }

  addBlock(x, y, size) {
    for (let j = 0; j < size; j++) for (let i = 0; i < size; i++) this.set(x + i, y + j, CELL.BLOCK);
    this.blocks.push({ x, y, size, captured: false });
    this.interiorTotal -= size * size;
  }

  percent() {
    return this.interiorTotal > 0 ? (100 * this.claimedInterior) / this.interiorTotal : 100;
  }

  isEmpty(x, y) { return this.get(x, y) === CELL.EMPTY; }
  isClaimed(x, y) { return this.get(x, y) === CELL.CLAIMED; }
  isTrail(x, y) { return this.get(x, y) === CELL.TRAIL; }
  isBlock(x, y) { return this.get(x, y) === CELL.BLOCK; }

  // Oyuncunun yürüyebileceği "kenar" hücre: ele geçirilmiş + 8 komşusundan biri boş
  hasEmptyNeighbour8(x, y) {
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      if (!dx && !dy) continue;
      const v = this.get(x + dx, y + dy);
      if (v === CELL.EMPTY || v === CELL.TRAIL) return true;
    }
    return false;
  }
  isWalkableEdge(x, y) { return this.isClaimed(x, y) && this.hasEmptyNeighbour8(x, y); }

  // Çizim sırasında x,y boş hücresine girilebilir mi? (önceki hücre hariç hatta 4-komşu olmamalı)
  canExtendTrail(x, y, px, py) {
    if (!this.isEmpty(x, y)) return false;
    const n = [[1, 0], [-1, 0], [0, 1], [0, -1]];
    for (const [dx, dy] of n) {
      const nx = x + dx, ny = y + dy;
      if (nx === px && ny === py) continue;
      if (this.isTrail(nx, ny)) return false;
    }
    return true;
  }

  clearTrail(trail) {
    for (const [x, y] of trail) if (this.isTrail(x, y)) this.set(x, y, CELL.EMPTY);
  }

  /**
   * Hattı kapat: hat hücreleri ele geçirilir, boss'ların ulaşamadığı tüm boş bölgeler doldurulur.
   * @param {Array<[number,number]>} trail
   * @param {Array<{x:number,y:number}>} seeds - boss hücre konumları (dış taraf)
   * @returns {{claimedCells:number, filledRegion:Uint8Array, newlyCaptured:Array}}
   */
  closeTrail(trail, seeds) {
    for (const [x, y] of trail) this.set(x, y, CELL.CLAIMED);
    const reach = new Uint8Array(this.w * this.h);
    const stack = [];
    for (const s of seeds) {
      const sx = Math.max(1, Math.min(this.w - 2, Math.round(s.x)));
      const sy = Math.max(1, Math.min(this.h - 2, Math.round(s.y)));
      // boss bir hat/kutu üstüne denk gelirse en yakın boş hücreyi ara
      const p = this.nearestEmpty(sx, sy);
      if (p) stack.push(p);
    }
    while (stack.length) {
      const [x, y] = stack.pop();
      const i = this.idx(x, y);
      if (reach[i] || this.cells[i] !== CELL.EMPTY) continue;
      reach[i] = 1;
      if (x > 0) stack.push([x - 1, y]);
      if (x < this.w - 1) stack.push([x + 1, y]);
      if (y > 0) stack.push([x, y - 1]);
      if (y < this.h - 1) stack.push([x, y + 1]);
    }
    const filled = new Uint8Array(this.w * this.h);
    let claimed = trail.length;
    for (let i = 0; i < this.cells.length; i++) {
      if (this.cells[i] === CELL.EMPTY && !reach[i]) {
        this.cells[i] = CELL.CLAIMED;
        filled[i] = 1;
        claimed++;
      }
    }
    for (const [x, y] of trail) filled[this.idx(x, y)] = 1;
    this.claimedInterior += claimed;

    const newlyCaptured = [];
    for (const b of this.blocks) {
      if (b.captured) continue;
      if (this.isBlockSurrounded(b)) { b.captured = true; newlyCaptured.push(b); }
    }
    return { claimedCells: claimed, filledRegion: filled, newlyCaptured };
  }

  isBlockSurrounded(b) {
    for (let j = -1; j <= b.size; j++) for (let i = -1; i <= b.size; i++) {
      const onRing = (i === -1 || j === -1 || i === b.size || j === b.size);
      if (!onRing) continue;
      if (this.isEmpty(b.x + i, b.y + j)) return false;
    }
    return true;
  }

  nearestEmpty(sx, sy, maxR = 12) {
    if (this.isEmpty(sx, sy)) return [sx, sy];
    for (let r = 1; r <= maxR; r++) {
      for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
        const x = sx + dx, y = sy + dy;
        if (this.isEmpty(x, y)) return [x, y];
      }
    }
    return null;
  }

  // Boş bölgede rastgele hücre
  randomEmptyCell(rng, margin = 3) {
    for (let t = 0; t < 500; t++) {
      const x = margin + Math.floor(rng() * (this.w - 2 * margin));
      const y = margin + Math.floor(rng() * (this.h - 2 * margin));
      if (this.isEmpty(x, y)) return { x, y };
    }
    return { x: this.w >> 1, y: this.h >> 1 };
  }
}
