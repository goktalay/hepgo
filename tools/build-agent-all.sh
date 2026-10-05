#!/usr/bin/env bash
# Tüm 5 entegrasyon için Linux kurulum paketlerini sırayla üretir.
# Kullanım: tools/build-agent-all.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTEGS=$(cd "${ROOT}" && python3 -c "import agent.profiles as p; print(' '.join(p.names()))")
echo ">> entegrasyonlar: ${INTEGS}"
for i in ${INTEGS}; do
  echo ""; echo "=================  ${i}  ================="
  bash "${ROOT}/tools/build-agent-linux.sh" "${i}"
done
echo ""; echo ">> hepsi bitti. Çıktılar: ${ROOT}/agent-dist/<integ>/"
