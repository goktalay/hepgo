#!/bin/bash
# Hepgo Dron Köprüsü — Linux / NVIDIA Jetson kurulumu (telemetri + görüntü köprüsü).
#   tar xzf HepgoDronKoprusu-Linux-Jetson-<sürüm>.tar.gz && cd HepgoDronKoprusu-Linux-Jetson-<sürüm> && sudo ./install.sh
#   sudo hepgo-kopru eslestir <köprü kodu>
# Seçenekler: --gst-yok (GStreamer paketlerini kurma) · --nvgetty-kapat (Jetson Nano: ttyTHS1'i tutan seri konsolu kapat) · --apt-yok
# Destek: Jetson Nano (JetPack 4.6 / Ubuntu 18.04 → python3.8 apt ile kurulur), Orin / Xavier (JetPack 5 / 6 → Ubuntu 20.04 / 22.04),
#         ayrıca herhangi bir Ubuntu/Debian (x86_64 / aarch64).
set -euo pipefail

APP=/opt/hepgo-kopru
ETC=/etc/hepgo-kopru
USR=hepgo-kopru
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GST=1; NVGETTY_OFF=0; APT=1
for a in "$@"; do
  case "$a" in
    --gst-yok) GST=0 ;;
    --nvgetty-kapat) NVGETTY_OFF=1 ;;
    --apt-yok) APT=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Bilinmeyen seçenek: $a" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Kök yetkisi gerekir: sudo ./install.sh" >&2; exit 1; }
say() { echo -e "\e[1;32m»\e[0m $*"; }
warn() { echo -e "\e[1;33m!\e[0m $*"; }

. /etc/os-release 2>/dev/null || true
ARCH="$(uname -m)"
JETSON=""
[ -f /etc/nv_tegra_release ] && JETSON="$(head -1 /etc/nv_tegra_release | sed 's/^# //')"
say "Sistem: ${PRETTY_NAME:-?} · $ARCH${JETSON:+ · Jetson ($JETSON)}"

# ---- Python 3.8+ ----
pyok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; }
PY=""
for c in python3 python3.12 python3.11 python3.10 python3.9 python3.8; do
  if command -v "$c" >/dev/null && pyok "$(command -v "$c")"; then PY="$(command -v "$c")"; break; fi
done
if [ "$APT" = 1 ]; then
  export DEBIAN_FRONTEND=noninteractive
  say "apt paketleri güncelleniyor"
  apt-get update -qq || warn "apt-get update başarısız (ağ?) — kuruluma devam"
  PKGS="ffmpeg ca-certificates"
  if [ -z "$PY" ] || [ "$PY" = "$(command -v python3.8 2>/dev/null)" ]; then
    PKGS="$PKGS python3.8 python3.8-venv python3.8-dev"   # Ubuntu 18.04 (JetPack 4.6): varsayılan python3.6
  else
    V="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    PKGS="$PKGS python${V}-venv"
  fi
  [ "$GST" = 1 ] && PKGS="$PKGS gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav"
  # tek tek: biri yoksa (ör. python3.X-venv adı farklı) diğerleri kurulsun
  for p in $PKGS; do apt-get install -y -qq "$p" >/dev/null 2>&1 || warn "$p kurulamadı"; done
  if [ -z "$PY" ] && command -v python3.8 >/dev/null; then PY="$(command -v python3.8)"; fi
fi
[ -n "$PY" ] || { echo "Python 3.8+ bulunamadı (Ubuntu 18.04: sudo apt install python3.8 python3.8-venv)" >&2; exit 1; }
say "Python: $PY ($("$PY" -V 2>&1))"

# ---- kullanıcı + dosyalar ----
id "$USR" >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin "$USR"
for g in dialout video tty; do getent group "$g" >/dev/null && usermod -aG "$g" "$USR" || true; done
install -d -m 0755 "$APP" "$APP/app"
install -m 0644 "$HERE"/kopru_core.py "$HERE"/goruntu_core.py "$HERE"/hepgo_kopru.py "$HERE"/requirements.txt "$HERE"/kopru.conf.ornek "$APP/app/"
[ -f "$HERE/SURUM" ] && install -m 0644 "$HERE/SURUM" "$APP/app/"
install -m 0755 "$HERE"/uninstall.sh "$APP/uninstall.sh"

# ---- sanal ortam ----
if [ ! -x "$APP/venv/bin/python" ] || ! pyok "$APP/venv/bin/python"; then
  rm -rf "$APP/venv"
  say "Sanal ortam: $APP/venv"
  "$PY" -m venv "$APP/venv"
fi
"$APP/venv/bin/python" -m pip install -q --upgrade "pip<25" "setuptools<76" wheel || warn "pip güncellenemedi"
say "Python paketleri kuruluyor (websockets, pymavlink, pyserial)"
"$APP/venv/bin/python" -m pip install -q --prefer-binary -r "$APP/app/requirements.txt"
"$APP/venv/bin/python" -c 'import websockets, pymavlink, serial; print("  websockets", websockets.__version__)'

# ---- komut ----
cat > /usr/local/bin/hepgo-kopru <<EOF
#!/bin/sh
exec "$APP/venv/bin/python" "$APP/app/hepgo_kopru.py" "\$@"
EOF
chmod 0755 /usr/local/bin/hepgo-kopru

# ---- yapılandırma (varsa korunur) ----
install -d -m 0750 -o root -g "$USR" "$ETC"
if [ ! -f "$ETC/kopru.conf" ]; then
  install -m 0640 -o root -g "$USR" "$HERE/kopru.conf.ornek" "$ETC/kopru.conf"
  if [ -z "$JETSON" ] && [ -e /dev/ttyACM0 ]; then sed -i 's#^cihaz = /dev/ttyTHS1#cihaz = /dev/ttyACM0#; s#^baud = 921600#baud = 115200#' "$ETC/kopru.conf"; fi
  say "Yapılandırma: $ETC/kopru.conf"
else
  chgrp "$USR" "$ETC/kopru.conf"; chmod 0640 "$ETC/kopru.conf"
  say "Mevcut yapılandırma korundu: $ETC/kopru.conf"
fi

# ---- Jetson Nano: J41 UART (ttyTHS1) seri konsol tarafından tutuluyor olabilir ----
if systemctl list-unit-files 2>/dev/null | grep -q '^nvgetty'; then
  if [ "$NVGETTY_OFF" = 1 ]; then
    systemctl stop nvgetty || true; systemctl disable nvgetty || true
    say "nvgetty kapatıldı (/dev/ttyTHS1 serbest)"
  elif systemctl is-enabled nvgetty >/dev/null 2>&1; then
    warn "nvgetty etkin: /dev/ttyTHS1 kullanılacaksa  sudo ./install.sh --nvgetty-kapat  (ya da systemctl disable --now nvgetty)"
  fi
fi

# ---- systemd ----
install -m 0644 "$HERE/hepgo-kopru.service" /etc/systemd/system/hepgo-kopru.service
systemctl daemon-reload
systemctl enable hepgo-kopru >/dev/null
if grep -Eq '^kod *= *[^ ]+/[^ ]+' "$ETC/kopru.conf"; then
  systemctl restart hepgo-kopru
  say "Servis (yeniden) başlatıldı — hepgo-kopru durum"
else
  say "Kurulum tamam. Şimdi köprü kodunu girin:  sudo hepgo-kopru eslestir <köprü kodu>"
  echo "   (HEPGO › Dron Yönetimi › Dron Köprüleri › Yeni Köprü / Kodu yenile)"
fi
command -v ffmpeg >/dev/null || warn "ffmpeg yok: görüntü köprüsü çalışmaz (sudo apt install ffmpeg)"
