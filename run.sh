#!/usr/bin/env bash
# Fabrika Yönetim Sistemi sunucusu.
# CAYMAZ_UDS tanımlıysa Unix domain socket üzerinde çalışır (port açılmaz; yalnız tünel erişir);
# yoksa ağdaki cihazlardan http://<bu-makinenin-ip>:${PORT} ile girilir.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
if [ -n "${CAYMAZ_UDS:-}" ]; then
  mkdir -p "$(dirname "$CAYMAZ_UDS")"
  rm -f "$CAYMAZ_UDS"   # eski soket dosyasını temizle (EADDRINUSE olmasın)
  exec .venv/bin/uvicorn app.main:app --uds "$CAYMAZ_UDS" --timeout-graceful-shutdown 3
fi
exec .venv/bin/uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" --timeout-graceful-shutdown 3
