#!/usr/bin/env bash
# Fabrika Yönetim Sistemi sunucusu. Ağdaki cihazlardan http://<bu-makinenin-ip>:8000 ile girilir.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
exec .venv/bin/uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
