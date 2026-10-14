// 2B CFD (kafes-Boltzmann, D2Q9, BGK): STEP parçasının / montajın kesit silueti etrafında akış.
// Ön değerlendirme amaçlı, boyutsuz kafes birimleriyle çalışır: giriş hızı u0 (kafes), viskozite ν → τ = 3ν + 0.5.
// Reynolds ≈ u0 · L / ν (L: cisim yüksekliği, hücre). Engel: geri sekme (bounce-back); üst/alt: serbest kayma; giriş sabit hız; çıkış açık.
// Görselleştirme: hız büyüklüğü / girdap (curl) / basınç (yoğunluk) renk haritası + izleyici parçacıklar (akım çizgileri).
// Sürükleme kuvveti: momentum alışverişi (engel sınırlarındaki geri sekmelerden) — bağıl karşılaştırma için.

const W9 = [4 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 36, 1 / 36, 1 / 36, 1 / 36];
const CX = [0, 1, 0, -1, 0, 1, -1, -1, 1], CY = [0, 0, 1, 0, -1, 1, 1, -1, -1], OPP = [0, 3, 4, 1, 2, 7, 8, 5, 6];
const REFY = [0, 1, 4, 3, 2, 8, 7, 6, 5];   // düşey aynalama (serbest kayma: üst/alt duvar)

export function createLBM(cols, rows) {
  const N = cols * rows;
  let f = new Float32Array(N * 9), f2 = new Float32Array(N * 9);
  const rho = new Float32Array(N), ux = new Float32Array(N), uy = new Float32Array(N), solid = new Uint8Array(N);
  const st = { u0: 0.08, tau: 0.56, step: 0, fx: 0, fy: 0, cols, rows };

  const eq = (k, r, vx, vy) => { const cu = 3 * (CX[k] * vx + CY[k] * vy), u2 = 1.5 * (vx * vx + vy * vy); return W9[k] * r * (1 + cu + 0.5 * cu * cu - u2); };
  const reset = () => {
    for (let i = 0; i < N; i++) { rho[i] = 1; ux[i] = solid[i] ? 0 : st.u0; uy[i] = 0; for (let k = 0; k < 9; k++) f[i * 9 + k] = eq(k, 1, ux[i], uy[i]); }
    st.step = 0; st.fx = 0; st.fy = 0;
  };
  const setObstacle = mask => { solid.set(mask); reset(); };
  const setViscosity = nu => { st.tau = 3 * nu + 0.5; };

  const stepOnce = () => {
    const omega = 1 / st.tau, u0 = st.u0;
    // çarpışma
    for (let i = 0; i < N; i++) {
      if (solid[i]) continue;
      let r = 0, vx = 0, vy = 0;
      for (let k = 0; k < 9; k++) { const v = f[i * 9 + k]; r += v; vx += v * CX[k]; vy += v * CY[k]; }
      vx /= r; vy /= r; rho[i] = r; ux[i] = vx; uy[i] = vy;
      for (let k = 0; k < 9; k++) f[i * 9 + k] += omega * (eq(k, r, vx, vy) - f[i * 9 + k]);
    }
    // yayılım + geri sekme (momentum alışverişi ile kuvvet)
    let fx = 0, fy = 0;
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
      const i = y * cols + x;
      if (solid[i]) continue;
      for (let k = 0; k < 9; k++) {
        let nx = x + CX[k], ny = y + CY[k];
        if (ny < 0 || ny >= rows) { f2[i * 9 + REFY[k]] = f[i * 9 + k]; continue; }   // üst/alt: serbest kayma (aynalı yansıma)
        if (nx < 0 || nx >= cols) continue;   // giriş/çıkış ayrıca
        const j = ny * cols + nx;
        if (solid[j]) { f2[i * 9 + OPP[k]] = f[i * 9 + k]; fx += 2 * f[i * 9 + k] * CX[k]; fy += 2 * f[i * 9 + k] * CY[k]; }
        else f2[j * 9 + k] = f[i * 9 + k];
      }
    }
    // giriş (x=0): sabit hız denge dağılımı; çıkış (x=cols-1): bir önceki sütunu kopyala
    for (let y = 0; y < rows; y++) {
      const i = y * cols, o = y * cols + cols - 1;
      for (let k = 0; k < 9; k++) { f2[i * 9 + k] = eq(k, 1, u0, 0); f2[o * 9 + k] = f2[(o - 1) * 9 + k]; }
    }
    [f, f2] = [f2, f];
    st.step++; st.fx = st.fx * 0.98 + fx * 0.02; st.fy = st.fy * 0.98 + fy * 0.02;   // kuvvet: üstel ortalama
  };
  const run = n => { for (let i = 0; i < n; i++) stepOnce(); };

  // Girdap (curl) alanı
  const curl = out => {
    for (let y = 1; y < rows - 1; y++) for (let x = 1; x < cols - 1; x++) {
      const i = y * cols + x;
      out[i] = solid[i] ? 0 : (uy[i + 1] - uy[i - 1] - (ux[i + cols] - ux[i - cols])) * 0.5;
    }
    return out;
  };
  reset();
  return { st, rho, ux, uy, solid, reset, setObstacle, setViscosity, step: run, curl, get N() { return N; } };
}

// Renk haritası (mavi → cyan → yeşil → sarı → kırmızı), t ∈ [0,1]
export function heat(t) {
  t = Math.max(0, Math.min(1, t));
  const s = [[20, 30, 120], [0, 150, 220], [40, 200, 90], [240, 220, 40], [220, 40, 30]];
  const p = t * (s.length - 1), i = Math.min(s.length - 2, Math.floor(p)), k = p - i;
  return [s[i][0] + (s[i + 1][0] - s[i][0]) * k, s[i][1] + (s[i + 1][1] - s[i][1]) * k, s[i][2] + (s[i + 1][2] - s[i][2]) * k];
}
export function diverging(t) {   // −1..1: mavi – beyaz – kırmızı (girdap)
  t = Math.max(-1, Math.min(1, t));
  const a = Math.abs(t);
  return t < 0 ? [255 - 220 * a, 255 - 180 * a, 255 - 40 * a] : [255 - 20 * a, 255 - 200 * a, 255 - 220 * a];
}

// Simülasyon + çizim: host içine canvas; opts: { cols, rows, stepsPerFrame, mode:'speed'|'curl'|'pressure', particles:true, onStats(st) }
export function createCfdView(host, { cols = 240, rows = 120, stepsPerFrame = 8 } = {}) {
  const sim = createLBM(cols, rows);
  const canvas = document.createElement('canvas'); canvas.width = cols; canvas.height = rows; canvas.className = 'cfd-canvas';
  host.appendChild(canvas);
  const ctx = canvas.getContext('2d'), img = ctx.createImageData(cols, rows), px = img.data;
  const curlBuf = new Float32Array(cols * rows);
  const particles = []; const P = 400;
  for (let i = 0; i < P; i++) particles.push([Math.random() * cols, Math.random() * rows]);
  const opt = { mode: 'speed', particles: true, running: false, stepsPerFrame, onStats: null };
  let raf = null, alive = true, frames = 0;

  const draw = () => {
    const { rho, ux, uy, solid } = sim;
    const u0 = sim.st.u0, N = cols * rows;
    if (opt.mode === 'curl') sim.curl(curlBuf);
    for (let i = 0; i < N; i++) {
      let c;
      if (solid[i]) c = [40, 44, 52];
      else if (opt.mode === 'speed') c = heat(Math.sqrt(ux[i] * ux[i] + uy[i] * uy[i]) / (u0 * 1.6));
      else if (opt.mode === 'curl') c = diverging(curlBuf[i] / (u0 * 0.25));
      else c = diverging((rho[i] - 1) / (u0 * u0 * 3));
      px[i * 4] = c[0]; px[i * 4 + 1] = c[1]; px[i * 4 + 2] = c[2]; px[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    if (opt.particles) {
      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      for (const p of particles) {
        const xi = Math.floor(p[0]), yi = Math.floor(p[1]);
        if (xi >= 0 && xi < cols && yi >= 0 && yi < rows && !solid[yi * cols + xi]) { ctx.fillRect(p[0], p[1], 1.2, 1.2); p[0] += ux[yi * cols + xi] * 14; p[1] += uy[yi * cols + xi] * 14; }
        if (xi < 0 || xi >= cols - 1 || yi < 0 || yi >= rows || (xi >= 0 && xi < cols && yi >= 0 && yi < rows && solid[yi * cols + xi]) || Math.random() < 0.004) { p[0] = Math.random() * 3; p[1] = Math.random() * rows; }
      }
    }
  };
  const loop = () => {
    if (!alive) return;
    if (opt.running) { sim.step(opt.stepsPerFrame); frames++; }
    draw();
    if (opt.onStats && (frames % 4 === 0)) opt.onStats(stats());
    raf = requestAnimationFrame(loop);
  };
  const stats = () => {
    const { ux, uy, solid, st } = sim;
    let vmax = 0, hmin = rows, hmax = 0;
    for (let i = 0; i < ux.length; i++) {
      if (solid[i]) { const y = Math.floor(i / cols); if (y < hmin) hmin = y; if (y > hmax) hmax = y; continue; }
      const v = ux[i] * ux[i] + uy[i] * uy[i]; if (v > vmax) vmax = v;
    }
    const L = Math.max(1, hmax - hmin + 1), nu = (st.tau - 0.5) / 3;
    const q = 0.5 * st.u0 * st.u0 * L;   // dinamik basınç × karakteristik uzunluk (kafes)
    return { step: st.step, vmax: Math.sqrt(vmax), u0: st.u0, nu, re: st.u0 * L / nu, L, fx: st.fx, fy: st.fy, cd: q ? st.fx / q : 0, cl: q ? -st.fy / q : 0, stable: Number.isFinite(vmax) && vmax < 0.5 };
  };
  loop();
  return {
    sim, opt, canvas,
    setObstacle: mask => { sim.setObstacle(mask); frames = 0; },
    setSpeed: u => { sim.st.u0 = u; sim.reset(); },
    setViscosity: nu => { sim.setViscosity(nu); },
    reset: () => sim.reset(),
    stats,
    destroy() { alive = false; if (raf) cancelAnimationFrame(raf); canvas.remove(); },
  };
}
