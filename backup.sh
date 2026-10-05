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

# Veilox paneli (hepgo.com / veilox.app: üyelikler, paketler, ödemeler): tek veritabanı + ayarlar (.env: Cloudflare /
# federasyon anahtarları — kaybolursa panel yeniden kurulamaz; yalnız sahibi okur) + tenants.json + Cloudflare DNS yedekleri
VEILOX=${VEILOX_DIR:-/opt/hepgo/veilox}
if [ -z "${1:-}" ] && [ -f "$VEILOX/data/central.db" ]; then
  if [ ! -r "$VEILOX/data/central.db" ]; then
    echo "UYARI: $VEILOX/data/central.db okunamıyor; Veilox servis kullanıcısıyla (hepgo) yedeklenmeli"
  else
    VD=$VEILOX/data/backups/nightly
    install -d -m 2770 "$VEILOX/data/backups" "$VD" 2>/dev/null || mkdir -p "$VD"
    sqlite3 "file:$VEILOX/data/central.db?mode=ro" ".backup '$VD/central-$DAY.db.tmp'"
    if [ "$(sqlite3 "$VD/central-$DAY.db.tmp" 'PRAGMA quick_check;')" = ok ]; then
      mv "$VD/central-$DAY.db.tmp" "$VD/central-$DAY.db"
      [ -r "$VEILOX/.env" ] && install -m 600 "$VEILOX/.env" "$VD/veilox.env"
      [ -f "$VEILOX/tenants.json" ] && cp -p "$VEILOX/tenants.json" "$VD/tenants.json"
      [ -d "$VEILOX/data/cf-backups" ] && rsync -a --delete "$VEILOX/data/cf-backups/" "$VD/cf-backups/"
      find "$VD" -maxdepth 1 -name 'central-*.db' -mtime +"$KEEP_DAYS" -delete
      echo "$(date '+%F %T') Yedek tamam: $VD (central-$DAY.db, ayarlar)"
    else
      echo "HATA: Veilox yedeği bozuk ($VD/central-$DAY.db.tmp)"; rm -f "$VD/central-$DAY.db.tmp"
    fi
  fi
fi
