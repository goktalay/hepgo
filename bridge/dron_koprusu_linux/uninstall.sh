#!/bin/bash
# Hepgo Dron Köprüsü — Linux / Jetson kaldırma. Yapılandırma (/etc/hepgo-kopru, köprü kodu) varsayılan olarak KORUNUR;
# --hepsi ile o da ve hepgo-kopru sistem kullanıcısı silinir. apt paketleri (ffmpeg, python3.8, GStreamer) kaldırılmaz.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Kök yetkisi gerekir: sudo $0" >&2; exit 1; }
ALL=0; [ "${1:-}" = "--hepsi" ] && ALL=1
systemctl disable --now hepgo-kopru 2>/dev/null || true
rm -f /etc/systemd/system/hepgo-kopru.service
systemctl daemon-reload || true
rm -f /usr/local/bin/hepgo-kopru
rm -rf /opt/hepgo-kopru
if [ "$ALL" = 1 ]; then
  rm -rf /etc/hepgo-kopru
  id hepgo-kopru >/dev/null 2>&1 && userdel hepgo-kopru || true
  echo "Hepgo Dron Köprüsü ve yapılandırması kaldırıldı."
else
  echo "Hepgo Dron Köprüsü kaldırıldı. Yapılandırma korundu: /etc/hepgo-kopru (silmek için: sudo $0 --hepsi)"
fi
