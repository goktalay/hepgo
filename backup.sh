#!/bin/bash
# Gece yedeği: veritabanı (tutarlı SQLite kopyası) + yüklenen dosyaların anlık görüntüsü.
# Dosya görüntüleri bir önceki güne sabit bağlantıyla (hard link) kurulur; değişmeyen dosyalar
# (ör. uçuş videoları) tekrar yer kaplamaz. KEEP_DAYS günden eski yedekler silinir.
set -euo pipefail
umask 077
cd "$(dirname "$0")"
KEEP_DAYS=${KEEP_DAYS:-30}
# Veri klasörü: argümansız GÖKKUBBE (data/); diğer firmalar tenants/<firma>/data (en sonda sırayla yedeklenir)
DATA=${1:-data}
DEST=$DATA/backups/nightly
DAY=$(date +%Y%m%d)
mkdir -p "$DEST"

sqlite3 "$DATA/caymaz.db" ".backup '$DEST/caymaz-$DAY.db.tmp'"
mv "$DEST/caymaz-$DAY.db.tmp" "$DEST/caymaz-$DAY.db"

# Evrak imza anahtarı: kaybolursa eski imzalar doğrulanamaz (değişmez; yalnızca sahibi okuyabilir)
[ -f "$DATA/signing.key" ] && cp -p "$DATA/signing.key" "$DEST/signing.key"
# Kamera şifre anahtarı: kaybolursa kayıtlı kamera şifreleri çözülemez (yeniden girilmesi gerekir)
[ -f "$DATA/camera.key" ] && cp -p "$DATA/camera.key" "$DEST/camera.key"

PREV=$(ls -d "$DEST"/uploads-* 2>/dev/null | grep -v "uploads-$DAY$" | sort | tail -1 || true)
rsync -a --chmod=go-rwx --delete ${PREV:+--link-dest="$PWD/$PREV"} "$DATA/uploads/" "$DEST/uploads-$DAY/"

find "$DEST" -maxdepth 1 -name 'caymaz-*.db' -mtime +"$KEEP_DAYS" -delete
find "$DEST" -maxdepth 1 -name 'uploads-*' -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +
echo "Yedek tamam: $DEST (caymaz-$DAY.db, uploads-$DAY)"

# Diğer firmalar (çok firmalı kurulum): her birinin veri klasörü ayrı yedeklenir
if [ -z "${1:-}" ]; then
  for t in tenants/*/data; do
    [ -f "$t/caymaz.db" ] && "$0" "$t"
  done
fi
