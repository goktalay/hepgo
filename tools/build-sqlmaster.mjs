// SQL Master renderer'ını HEPGO static/mt/sqlmaster altına derler (orijinal scripts/build.mjs'nin web kısmı; login penceresi hariç)
import * as esbuild from '/home/gelistirici/mt-work/sqlmaster/node_modules/esbuild/lib/main.js';
const root = '/home/gelistirici/mt-work/sqlmaster';
const out = process.argv[2] || new URL('../static/mt/sqlmaster/', import.meta.url).pathname;
await esbuild.build({
  absWorkingDir: root, bundle: true, platform: 'browser', format: 'iife', target: 'chrome120', sourcemap: false, logLevel: 'info', minify: false,
  entryPoints: { 'renderer/main/app': 'src/renderer/main/app.ts', 'renderer/conn/conn': 'src/renderer/conn/conn.ts' },
  outdir: out,
});
