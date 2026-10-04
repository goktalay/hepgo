#!/usr/bin/env bash
# Canlıya aktarım: depo → canlı klasör (rsync). Servisleri yeniden başlatmaz.
# Kullanım: ./deploy.sh app|veilox [--apply]   (varsayılan: yalnız ön izleme)
#   app    → /opt/hepgo/caymazbuild (hepgo-caymaz, hepgo-turkbey, hepgo-merkez)
#   veilox → /opt/hepgo/veilox      (hepgo-veilox)
# Canlı veriler (data/, tenants/, .env*, .venv, vendor/models|ocr|whisper) hiç ellenmez;
# değişen/silinen dosyalar /opt/hepgo/deploy-backups/<hedef>-<zaman> altına yedeklenir.
set -euo pipefail
cd "$(dirname "$0")"
TARGET=${1:?app|veilox}; APPLY=${2:-}
case $TARGET in
  app)    SRC=./;                     DST=/opt/hepgo/caymazbuild/; SVCS="caymaz turkbey merkez" ;;
  veilox) SRC=central/veilox_server/; DST=/opt/hepgo/veilox/;      SVCS="veilox" ;;
  *) echo "hedef: app|veilox"; exit 1 ;;
esac
[ -w "$DST" ] || { echo "HATA: $DST yazılamıyor (izin)"; exit 1; }

# Yalnızca main'e gönderilmiş, temiz bir ağaç aktarılır
[ -z "$(git status --porcelain)" ] || { echo "HATA: commit edilmemiş değişiklik var"; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "HATA: HEAD origin/main ile aynı değil"; exit 1; }

EXCL=(--exclude=/.git/ --exclude=/.venv/ --exclude=/data/ --exclude=/tenants/
      --exclude='.env*' --exclude=__pycache__/ --exclude='*.pyc' --exclude=/.deployed-rev
      --exclude=/vendor/models --exclude=/vendor/ocr --exclude=/vendor/whisper --exclude=/.claude)
# (sondaki / yok: klasör olsun ya da kısayol (symlink), canlıdaki gerçek klasörün yerine hiçbir şey geçmesin)
[ "$TARGET" = app ] && EXCL+=(--exclude=/central/)
# veilox: canlıdaki yapılandırma (tenants.json) korunur; depoda olmayan eski dosyalar silinmez (yalnız güncelleme/ekleme)
DELETE=(--delete)
if [ "$TARGET" = veilox ]; then EXCL+=(--exclude=/tenants.json); DELETE=(); fi

# Yalnız içerik karşılaştırılır (--checksum); sahiplik/izin/zaman taşınmaz, çünkü hepgo'ya ait
# dosyalarda chmod/utime yapılamaz. Değişen dosya yeniden yazılır (sahibi gelistirici olur, okunabilir kalır);
# yeni dosyalar kaynak iznini umask ile alır (run.sh çalıştırılabilir kalır).
STAMP=$(date +%Y%m%d-%H%M%S)
OPTS=(-rl --checksum "${DELETE[@]}" --itemize-changes
      --backup --backup-dir=/opt/hepgo/deploy-backups/$TARGET-$STAMP "${EXCL[@]}")

if [ "$APPLY" != --apply ]; then
  rsync "${OPTS[@]}" --dry-run "$SRC" "$DST"; echo "(ön izleme — uygulamak için --apply)"; exit 0
fi
PREV=$(cat "$DST/.deployed-rev" 2>/dev/null || true)
if [ "$TARGET" = app ] && [ -n "$PREV" ] && ! git diff --quiet "$PREV" HEAD -- requirements.txt 2>/dev/null; then
  echo "UYARI: requirements.txt değişti — .venv'e pip install gerekir (hepgo yetkisi)"
fi
rsync "${OPTS[@]}" "$SRC" "$DST"
git rev-parse HEAD > "$DST/.deployed-rev"
echo "Aktarıldı ($(git log -1 --format='%h %s')). Yedek: /opt/hepgo/deploy-backups/$TARGET-$STAMP"
echo "Yeniden başlatmak için: for s in $SVCS; do sudo systemctl restart hepgo-\$s.service; done"
