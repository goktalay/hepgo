// VOLFAI - dokunmatik "yüzen joystick" + klavye
// Parmağı ekranın herhangi bir yerine koy, sürükle: baskın eksen yönü belirler.
// Çapa parmağı takip eder (floating stick) → yön değişimi anında hissedilir.
export const DIR = { NONE: 0, UP: 1, DOWN: 2, LEFT: 3, RIGHT: 4 };
export const DIR_VEC = { 1: [0, -1], 2: [0, 1], 3: [-1, 0], 4: [1, 0] };

export class Input {
  constructor(surface, fireBtn) {
    this.surface = surface;
    this.primary = DIR.NONE;     // baskın yön
    this.secondary = DIR.NONE;   // ikinci eksen (köşe dönüş yardımı)
    this.fire = false;
    this.keyFire = false;
    this.touchId = null;
    this.anchor = null;          // {x,y}
    this.pos = null;
    this.deadzone = 10;
    this.followRadius = 28;
    this.keys = new Set();
    this.onAny = null;           // ilk etkileşim (ses başlatma) için
    this.visible = false;

    const opt = { passive: false };
    surface.addEventListener('touchstart', e => this.onTouchStart(e), opt);
    surface.addEventListener('touchmove', e => this.onTouchMove(e), opt);
    surface.addEventListener('touchend', e => this.onTouchEnd(e), opt);
    surface.addEventListener('touchcancel', e => this.onTouchEnd(e), opt);
    // fare ile test
    surface.addEventListener('mousedown', e => { this.anchor = { x: e.clientX, y: e.clientY }; this.pos = { ...this.anchor }; this.visible = true; this.touchId = 'mouse'; this.fireAny(); });
    window.addEventListener('mousemove', e => { if (this.touchId === 'mouse') this.updateFrom(e.clientX, e.clientY); });
    window.addEventListener('mouseup', () => { if (this.touchId === 'mouse') this.release(); });

    window.addEventListener('keydown', e => {
      if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' '].includes(e.key)) e.preventDefault();
      this.keys.add(e.key); this.fireAny(); this.updateKeys();
    });
    window.addEventListener('keyup', e => { this.keys.delete(e.key); this.updateKeys(); });

    if (fireBtn) {
      fireBtn.addEventListener('touchstart', e => { e.preventDefault(); e.stopPropagation(); this.fire = true; this.fireAny(); }, opt);
      fireBtn.addEventListener('touchend', e => { e.preventDefault(); e.stopPropagation(); this.fire = false; }, opt);
      fireBtn.addEventListener('touchcancel', e => { e.preventDefault(); this.fire = false; }, opt);
      fireBtn.addEventListener('mousedown', e => { e.stopPropagation(); this.fire = true; });
      fireBtn.addEventListener('mouseup', e => { e.stopPropagation(); this.fire = false; });
    }
  }

  fireAny() { if (this.onAny) { const f = this.onAny; this.onAny = null; f(); } }

  onTouchStart(e) {
    // düğmelere dokunuş joystick başlatmasın
    if (e.target.closest && e.target.closest('button, a, input, label, select')) return;
    e.preventDefault();
    this.fireAny();
    if (this.touchId !== null && this.touchId !== 'mouse') return;
    const t = e.changedTouches[0];
    this.touchId = t.identifier;
    this.anchor = { x: t.clientX, y: t.clientY };
    this.pos = { ...this.anchor };
    this.visible = true;
  }
  onTouchMove(e) {
    for (const t of e.changedTouches) if (t.identifier === this.touchId) { e.preventDefault(); this.updateFrom(t.clientX, t.clientY); }
  }
  onTouchEnd(e) {
    for (const t of e.changedTouches) if (t.identifier === this.touchId) { e.preventDefault(); this.release(); }
  }
  release() {
    this.touchId = null; this.anchor = null; this.pos = null; this.visible = false;
    this.primary = DIR.NONE; this.secondary = DIR.NONE;
    this.updateKeys();
  }

  updateFrom(x, y) {
    if (!this.anchor) return;
    this.pos = { x, y };
    let dx = x - this.anchor.x, dy = y - this.anchor.y;
    const d = Math.hypot(dx, dy);
    if (d < this.deadzone) { this.primary = DIR.NONE; this.secondary = DIR.NONE; return; }
    const ax = Math.abs(dx), ay = Math.abs(dy);
    const hx = dx > 0 ? DIR.RIGHT : DIR.LEFT, vy = dy > 0 ? DIR.DOWN : DIR.UP;
    if (ax >= ay) { this.primary = hx; this.secondary = ay > d * 0.38 ? vy : DIR.NONE; }
    else { this.primary = vy; this.secondary = ax > d * 0.38 ? hx : DIR.NONE; }
    // çapa parmağı takip etsin
    if (d > this.followRadius) {
      const k = (d - this.followRadius) / d;
      this.anchor.x += dx * k; this.anchor.y += dy * k;
    }
  }

  updateKeys() {
    if (this.touchId !== null) return;
    const k = this.keys;
    const v = (k.has('ArrowUp') || k.has('w') || k.has('W')) ? DIR.UP : (k.has('ArrowDown') || k.has('s') || k.has('S')) ? DIR.DOWN : DIR.NONE;
    const h = (k.has('ArrowLeft') || k.has('a') || k.has('A')) ? DIR.LEFT : (k.has('ArrowRight') || k.has('d') || k.has('D')) ? DIR.RIGHT : DIR.NONE;
    // son basılan öncelikli: basitçe dikeyi birincil al, yatayı ikincil (ikisi de denenir)
    if (v && h) { this.primary = this.lastAxis === 'h' ? h : v; this.secondary = this.lastAxis === 'h' ? v : h; }
    else { this.primary = v || h; this.secondary = DIR.NONE; }
    if (v && !h) this.lastAxis = 'v'; else if (h && !v) this.lastAxis = 'h';
    this.keyFire = k.has(' ') || k.has('Shift');
  }
}
