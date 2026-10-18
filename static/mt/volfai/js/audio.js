// VOLFAI - WebAudio ile sentezlenmiş retro sesler (harici dosya yok)
export class Sfx {
  constructor() { this.ctx = null; this.muted = false; this.master = null; }
  init() {
    if (this.ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    this.ctx = new AC();
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.35;
    this.master.connect(this.ctx.destination);
  }
  resume() { if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume(); }
  setMuted(m) { this.muted = m; if (this.master) this.master.gain.value = m ? 0 : 0.35; }

  tone({ f = 440, f2 = null, type = 'square', dur = 0.1, vol = 0.5, delay = 0 }) {
    if (!this.ctx || this.muted) return;
    const t0 = this.ctx.currentTime + delay;
    const o = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(f, t0);
    if (f2 !== null) o.frequency.exponentialRampToValueAtTime(Math.max(20, f2), t0 + dur);
    g.gain.setValueAtTime(vol, t0);
    g.gain.exponentialRampToValueAtTime(0.001, t0 + dur);
    o.connect(g); g.connect(this.master);
    o.start(t0); o.stop(t0 + dur + 0.02);
  }
  noise(dur = 0.3, vol = 0.4) {
    if (!this.ctx || this.muted) return;
    const n = this.ctx.sampleRate * dur;
    const buf = this.ctx.createBuffer(1, n, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n);
    const s = this.ctx.createBufferSource(); s.buffer = buf;
    const g = this.ctx.createGain(); g.gain.value = vol;
    s.connect(g); g.connect(this.master); s.start();
  }

  step()     { this.tone({ f: 900, type: 'square', dur: 0.025, vol: 0.06 }); }
  claim(big) { this.tone({ f: 300, f2: 900, type: 'triangle', dur: 0.18, vol: 0.4 }); if (big) this.tone({ f: 600, f2: 1400, type: 'triangle', dur: 0.3, vol: 0.4, delay: 0.1 }); }
  power()    { [523, 659, 784, 1046].forEach((f, i) => this.tone({ f, type: 'square', dur: 0.09, vol: 0.3, delay: i * 0.07 })); }
  enemyDie() { this.tone({ f: 800, f2: 100, type: 'sawtooth', dur: 0.25, vol: 0.3 }); }
  laser()    { this.tone({ f: 1400, f2: 300, type: 'sawtooth', dur: 0.08, vol: 0.2 }); }
  bossHit()  { this.tone({ f: 200, f2: 120, type: 'square', dur: 0.08, vol: 0.3 }); }
  fuse()     { this.tone({ f: 2000, f2: 1500, type: 'square', dur: 0.05, vol: 0.12 }); }
  die()      { this.noise(0.5, 0.5); this.tone({ f: 400, f2: 40, type: 'sawtooth', dur: 0.7, vol: 0.5 }); }
  coin()     { this.tone({ f: 1500, type: 'square', dur: 0.06, vol: 0.2 }); this.tone({ f: 2200, type: 'square', dur: 0.1, vol: 0.2, delay: 0.06 }); }
  buy()      { [660, 880, 1320].forEach((f, i) => this.tone({ f, type: 'triangle', dur: 0.12, vol: 0.3, delay: i * 0.08 })); }
  tap()      { this.tone({ f: 700, type: 'triangle', dur: 0.04, vol: 0.15 }); }
  tick(last)  { this.tone({ f: last ? 1200 : 880, type: 'square', dur: last ? 0.25 : 0.07, vol: 0.35 }); }
  hit()      { this.noise(0.15, 0.35); this.tone({ f: 220, f2: 90, type: 'sawtooth', dur: 0.2, vol: 0.4 }); }
  deflect()  { this.tone({ f: 600, f2: 2400, type: 'sine', dur: 0.15, vol: 0.35 }); this.noise(0.12, 0.25); }
  missile()  { this.tone({ f: 300, f2: 500, type: 'sawtooth', dur: 0.3, vol: 0.15 }); }
  levelClear() { [392, 523, 659, 784, 1046, 1318].forEach((f, i) => this.tone({ f, type: 'triangle', dur: 0.2, vol: 0.4, delay: i * 0.1 })); }
  hurry()    { this.tone({ f: 660, type: 'square', dur: 0.1, vol: 0.3 }); this.tone({ f: 660, type: 'square', dur: 0.1, vol: 0.3, delay: 0.15 }); }
  gameOver() { [440, 415, 392, 349, 330, 262].forEach((f, i) => this.tone({ f, type: 'sawtooth', dur: 0.35, vol: 0.35, delay: i * 0.25 })); }
}
