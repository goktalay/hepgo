#!/usr/bin/env bash
# static/vendor/three/3DTilesRenderer.js üretimi: NASA-AMMOS 3d-tiles-renderer (MIT) tek ES modülü olarak paketlenir.
# three bağımlılıkları dışarıda bırakılır ve yerel vendor yollarına çevrilir (import haritası gerekmez).
# Kullanım: tools/build-3dtiles.sh [sürüm]   (varsayılan 0.5.3; three 0.170 ile uyumlu, vendor three.module.min.js r170)
set -euo pipefail
VER="${1:-0.5.3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/static/vendor/three"
TMP="$(mktemp -d /tmp/g3d-build.XXXXXX)"
cd "$TMP"
echo '{"name":"g3d-build","private":true}' > package.json
npm i --no-audit --no-fund --silent "3d-tiles-renderer@$VER" three@0.170.0 esbuild@0.28.2
cat > entry.js <<'EOF'
// HEPGO Uçuş Simülatörü — Google Photorealistic 3D Tiles için gereken parçalar
export { TilesRenderer, WGS84_ELLIPSOID, Ellipsoid } from '3d-tiles-renderer';
export { GoogleCloudAuthPlugin } from '3d-tiles-renderer/core/plugins';
export { GLTFExtensionsPlugin, TilesFadePlugin, TileCompressionPlugin } from '3d-tiles-renderer/plugins';
EOF
npx esbuild entry.js --bundle --format=esm --minify --target=es2022 \
  --external:three --external:three/addons/loaders/GLTFLoader.js --external:three/addons/utils/BufferGeometryUtils.js \
  --outfile=bundle.js
{
  echo "// 3d-tiles-renderer v$VER (NASA-AMMOS, MIT — LICENSE-3d-tiles-renderer) — HEPGO için tek ES modülü; tools/build-3dtiles.sh ile üretildi."
  echo "// Dışa: TilesRenderer, WGS84_ELLIPSOID, Ellipsoid, GoogleCloudAuthPlugin, GLTFExtensionsPlugin, TilesFadePlugin, TileCompressionPlugin."
  sed -e 's#from"three"#from"./three.module.min.js"#g' \
      -e 's#from"three/addons/loaders/GLTFLoader.js"#from"./GLTFLoader.js"#g' \
      -e 's#from"three/addons/utils/BufferGeometryUtils.js"#from"./BufferGeometryUtils.js"#g' \
      -e 's#from"three/addons/postprocessing/Pass.js"#from"./Pass.js"#g' bundle.js
} > "$OUT/3DTilesRenderer.js"
cp node_modules/3d-tiles-renderer/LICENSE "$OUT/LICENSE-3d-tiles-renderer"
# three eklentileri (vendor'da yoksa): Pass.js (TilesFadePlugin), DRACOLoader.js + draco/ çözücü (Google karoları Draco sıkıştırmalı)
sed "s#from 'three';#from './three.module.min.js';#" node_modules/three/examples/jsm/postprocessing/Pass.js > "$OUT/Pass.js"
sed "s#from 'three';#from './three.module.min.js';#" node_modules/three/examples/jsm/loaders/DRACOLoader.js > "$OUT/DRACOLoader.js"
mkdir -p "$OUT/draco"
cp node_modules/three/examples/jsm/libs/draco/gltf/{draco_decoder.js,draco_decoder.wasm,draco_wasm_wrapper.js} "$OUT/draco/"
cd /; rm -rf "$TMP"
echo "yazıldı: $OUT/3DTilesRenderer.js ($(stat -c %s "$OUT/3DTilesRenderer.js") bayt)"
grep -o 'from"[^"]*"' "$OUT/3DTilesRenderer.js" | sort | uniq -c
