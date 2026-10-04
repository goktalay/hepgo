#!/bin/bash
# Gece yedeği: veritabanı (tutarlı SQLite kopyası) + yüklenen dosyaların anlık görüntüsü.
# Dosya görüntüleri bir önceki güne sabit bağlantıyla (hard link) kurulur; değişmeyen dosyalar
# (ör. uçuş videoları) tekrar yer kaplamaz. KEEP_DAYS günden eski yedekler silinir.
# Servis kullanıcısı dışında (ör. hepgo grubundaki bir kullanıcı, cron ile) de çalışır: veritabanı
# salt-okunur açılır, yedekler veri klasörünün grubuna okunur kalır (uygulamanın yedek paneli görür).
set -euo pipefail
umask 027
cd "$(dirname "$0")"
KEEP_DAYS=${KEEP_DAYS:-30}
# Veri klasörü: argümansız GÖKKUBBE (data/); diğer firmalar tenants/<firma>/data (en sonda sırayla yedeklenir)
DATA=$(readlink -f "${1:-data}")
DEST=$DATA/backups/nightly
DAY=$(date +%Y%m%d)
GRP=$(stat -c %G "$DATA")
# setgid + grup yazma: içeride oluşan her dosya veri klasörünün grubunu alır; servis kullanıcısı ve gruptaki
# kullanıcılar (cron) aynı yedek klasörüne yazabilir. Var olan klasörün iznine dokunulmaz (sahibi başkası olabilir).
for d in "$DATA/backups" "$DEST"; do [ -d "$d" ] || install -d -m 2770 -g "$GRP" "$d"; done

sqlite3 "file:$DATA/caymaz.db?mode=ro" ".backup '$DEST/caymaz-$DAY.db.tmp'"
[ "$(sqlite3 "$DEST/caymaz-$DAY.db.tmp" 'PRAGMA quick_check;')" = ok ] || { echo "HATA: yedek bozuk ($DEST/caymaz-$DAY.db.tmp)"; exit 1; }
mv "$DEST/caymaz-$DAY.db.tmp" "$DEST/caymaz-$DAY.db"

# Evrak imza anahtarı: kaybolursa eski imzalar doğrulanamaz (değişmez; yalnızca sahibi okuyabilir)
# Kamera şifre anahtarı: kaybolursa kayıtlı kamera şifreleri çözülemez (yeniden girilmesi gerekir)
for k in signing.key camera.key; do
  [ -f "$DATA/$k" ] || continue
  if [ -r "$DATA/$k" ]; then cp -p "$DATA/$k" "$DEST/$k"
  elif [ ! -f "$DEST/$k" ]; then echo "UYARI: $DATA/$k okunamıyor; anahtarı servis kullanıcısıyla bir kez $DEST/ içine kopyalayın"
  fi
done

PREV=$(ls -d "$DEST"/uploads-* 2>/dev/null | grep -v "uploads-$DAY$" | sort | tail -1 || true)
rsync -a --chmod=o-rwx,Fg-w,Dg+w --delete ${PREV:+--link-dest="$PREV"} "$DATA/uploads/" "$DEST/uploads-$DAY/"

find "$DEST" -maxdepth 1 -name 'caymaz-*.db' -mtime +"$KEEP_DAYS" -delete
find "$DEST" -maxdepth 1 -name 'uploads-*' -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +
echo "$(date '+%F %T') Yedek tamam: $DEST (caymaz-$DAY.db, uploads-$DAY)"

# Diğer firmalar (çok firmalı kurulum): her birinin veri klasörü ayrı yedeklenir
if [ -z "${1:-}" ]; then
  if [ -d tenants ] && [ ! -x tenants ]; then
    echo "UYARI: tenants/ okunamıyor; firma verileri bu kullanıcıyla yedeklenemedi"
  fi
  for t in tenants/*/data; do
    if [ -f "$t/caymaz.db" ]; then "$0" "$t" || echo "HATA: $t yedeklenemedi"; fi
  done
fi
