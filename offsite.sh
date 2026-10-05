#!/bin/bash
# Sunucu dışı yedek: gece yedeğini (backup.sh) ŞİFRELİ olarak Google Drive'a gönderir (rclone).
# OFFSITE_REMOTE (varsayılan hepgo-yedek:) bir rclone "crypt" hedefidir: dosya içerikleri ve adları sunucuda şifrelenir,
# Drive yalnız okunamaz veri görür (kişisel veri + imza/kamera anahtarları içerir). Şifre kaybolursa yedek açılamaz.
# Her firma için uzakta:
#   <firma>/db/caymaz-GGAAYYYY.db (+ *.key)  günlük veritabanı, KEEP_DAYS gün saklanır
#   <firma>/uploads/                          yüklenen dosyaların güncel aynası (tek kopya: hard link'li günlük
#                                             görüntüler Drive'da her gün yeniden yer kaplamasın)
#   <firma>/uploads-eski/GGAAYYYY/            o gün değişen/silinen dosyaların önceki hali, KEEP_DAYS gün saklanır
# Argümansız: GÖKKUBBE (data/ → caymaz) + tenants/<firma>/data. backup.sh'den SONRA, servis kullanıcısıyla çalışır.
set -uo pipefail
umask 077
cd "$(dirname "$0")"
REMOTE=${OFFSITE_REMOTE:-hepgo-yedek:}
KEEP_DAYS=${KEEP_DAYS:-30}
RCLONE=${RCLONE:-rclone}
DAY=$(date +%Y%m%d)
CUTOFF=$(date -d "-$KEEP_DAYS days" +%Y%m%d)
RC=(--retries 3 --low-level-retries 10 --stats 0)

push() {   # $1 veri klasörü, $2 uzak klasör adı
  local data=$1 name=$2 src=$1/backups/nightly
  if [ ! -f "$src/caymaz-$DAY.db" ]; then
    echo "HATA: $name: bugünün gece yedeği yok ($src/caymaz-$DAY.db) — backup.sh çalıştı mı?"; return 1
  fi
  $RCLONE copy "${RC[@]}" "$src" "$REMOTE$name/db" --include "caymaz-$DAY.db" --include "*.key" || return 1
  if [ -d "$src/uploads-$DAY" ]; then
    $RCLONE sync "${RC[@]}" "$src/uploads-$DAY/" "$REMOTE$name/uploads" --backup-dir "$REMOTE$name/uploads-eski/$DAY" || return 1
  fi
  # Saklama: tarih ADINA göre (dosya zamanına değil — eski dosyalar taşınınca zamanı eski kalır)
  local f
  for f in $($RCLONE lsf "$REMOTE$name/db" --include 'caymaz-*.db' 2>/dev/null); do
    [[ "$f" =~ ^caymaz-([0-9]{8})\.db$ ]] && [ "${BASH_REMATCH[1]}" -lt "$CUTOFF" ] && $RCLONE deletefile "$REMOTE$name/db/$f"
  done
  for f in $($RCLONE lsf --dirs-only "$REMOTE$name/uploads-eski" 2>/dev/null); do
    f=${f%/}
    [[ "$f" =~ ^[0-9]{8}$ ]] && [ "$f" -lt "$CUTOFF" ] && $RCLONE purge "$REMOTE$name/uploads-eski/$f"
  done
  echo "$(date '+%F %T') Sunucu dışı yedek tamam: $name"
}

fail=0
if [ -n "${1:-}" ]; then
  push "$1" "${2:-$(basename "$(dirname "$(readlink -f "$1")")")}" || fail=1
else
  push data caymaz || fail=1
  for t in tenants/*/data; do
    [ -f "$t/caymaz.db" ] || continue
    push "$t" "$(basename "$(dirname "$t")")" || fail=1
  done
fi
# Veilox paneli: <uzak>/veilox/db/central-GGAAYYYY.db (KEEP_DAYS gün) + veilox.env, tenants.json, cf-backups/ (güncel)
VD=${VEILOX_DIR:-/opt/hepgo/veilox}/data/backups/nightly
if [ -z "${1:-}" ] && [ -d "$VD" ]; then
  if [ ! -f "$VD/central-$DAY.db" ]; then
    echo "HATA: veilox: bugünün gece yedeği yok ($VD/central-$DAY.db)"; fail=1
  elif $RCLONE copy "${RC[@]}" "$VD" "${REMOTE}veilox/db" --include "central-$DAY.db" --include veilox.env --include tenants.json --include "cf-backups/**"; then
    for f in $($RCLONE lsf "${REMOTE}veilox/db" --include 'central-*.db' 2>/dev/null); do
      [[ "$f" =~ ^central-([0-9]{8})\.db$ ]] && [ "${BASH_REMATCH[1]}" -lt "$CUTOFF" ] && $RCLONE deletefile "${REMOTE}veilox/db/$f"
    done
    echo "$(date '+%F %T') Sunucu dışı yedek tamam: veilox"
  else
    fail=1
  fi
fi
[ $fail -eq 0 ] || { echo "$(date '+%F %T') UYARI: en az bir firmanın sunucu dışı yedeği alınamadı"; exit 1; }
