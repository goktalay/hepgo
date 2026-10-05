#!/usr/bin/env bash
# HEPGO fabrika ajanı — Linux kurulum paketi üretici.
#
# Kullanım:   tools/build-agent-linux.sh <mikro|pdks|printer|camera|face>
#
# Üretir:     agent-dist/<integ>/hepgo-<integ>-setup-linux.sh
#   Kendinden çıkartmalı (self-extracting) bir kabuk betiği + sonuna eklenmiş tar.gz yük.
#   İçinde: taşınabilir CPython 3.12 (python-build-standalone, pinli, sha256 doğrulanır),
#   TABAN + o entegrasyonun pip bağımlılıkları kurulu, app/ + agent/ kodu.
#   Kurulumda: /opt/hepgo-<integ> altına açar, systemd birimi hepgo-<integ>.service yazar ve etkinleştirir.
#   İlk açılışta yapılandırma yoksa yerel ayar arayüzünü (127.0.0.1:8765) başlatır ve URL'yi loglar.
#
# Gerçek systemctl/kurulum adımları yalnız kök (root) + --dry-run DEĞİL iken çalışır; böylece burada
# (--dry-run ile) servislere dokunmadan paket üretip açılışı test edebilirsiniz.
set -euo pipefail

# ---- pinli taşınabilir CPython (python-build-standalone) ----
PBS_DATE="20241016"
PBS_PYVER="3.12.7"
PBS_TRIPLE="x86_64-unknown-linux-gnu"
PBS_FILE="cpython-${PBS_PYVER}+${PBS_DATE}-${PBS_TRIPLE}-install_only.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_DATE}/${PBS_FILE}"
PBS_SHA256="43576f7db1033dd57b900307f09c2e86f371152ac8a2607133afa51cbfc36064"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="${ROOT}/tools/.cache"
INTEG="${1:-}"

die() { echo "HATA: $*" >&2; exit 1; }

[ -n "${INTEG}" ] || die "entegrasyon adı gerekli: mikro|pdks|printer|camera|face"
VALID=$(cd "${ROOT}" && python3 -c "import agent.profiles as p; print(' '.join(p.names()))")
case " ${VALID} " in *" ${INTEG} "*) : ;; *) die "bilinmeyen entegrasyon '${INTEG}' (geçerli: ${VALID})";; esac

NAME=$(cd "${ROOT}" && python3 -c "import agent.profiles as p; print(p.get('${INTEG}')['name'])")
DEPS=$(cd "${ROOT}" && python3 -c "import agent.profiles as p; print(' '.join(p.pip_requirements('${INTEG}')))")

OUTDIR="${ROOT}/agent-dist/${INTEG}"
INSTALLER="${OUTDIR}/hepgo-${INTEG}-setup-linux.sh"
BUILD="$(mktemp -d)"
trap 'rm -rf "${BUILD}"' EXIT

echo ">> [${INTEG}] ${NAME}"
echo ">> bağımlılıklar: ${DEPS}"
mkdir -p "${OUTDIR}" "${CACHE}"

# ---- 1) taşınabilir CPython indir + sha256 doğrula (önbellekli) ----
TARBALL="${CACHE}/${PBS_FILE}"
if [ ! -f "${TARBALL}" ]; then
  echo ">> CPython indiriliyor: ${PBS_URL}"
  curl -fSL --retry 3 -o "${TARBALL}.part" "${PBS_URL}"
  mv "${TARBALL}.part" "${TARBALL}"
fi
echo ">> sha256 doğrulanıyor"
echo "${PBS_SHA256}  ${TARBALL}" | sha256sum -c - >/dev/null || die "CPython sha256 uyuşmadı"

STAGE="${BUILD}/hepgo-${INTEG}"
mkdir -p "${STAGE}/code"
echo ">> CPython açılıyor"
tar -xzf "${TARBALL}" -C "${STAGE}"     # → ${STAGE}/python/
PY="${STAGE}/python/bin/python3"
[ -x "${PY}" ] || die "taşınabilir python bulunamadı: ${PY}"

# ---- 2) pip bağımlılıkları (taban + entegrasyon) ----
echo ">> pip yükseltiliyor"
"${PY}" -m pip install --quiet --no-warn-script-location --upgrade pip
echo ">> bağımlılıklar kuruluyor"
# shellcheck disable=SC2086
"${PY}" -m pip install --quiet --no-warn-script-location ${DEPS}

# ---- 3) kod (app/ + agent/, __pycache__ hariç) ----
echo ">> kod kopyalanıyor (app/, agent/)"
tar -C "${ROOT}" --exclude='__pycache__' --exclude='*.pyc' -cf - app agent | tar -C "${STAGE}/code" -xf -
cat > "${STAGE}/VERSION" <<EOF
integ=${INTEG}
name=${NAME}
python=${PBS_PYVER}+${PBS_DATE} ${PBS_TRIPLE}
built=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

# ---- 4) yük tar.gz ----
PAYLOAD="${BUILD}/payload.tar.gz"
echo ">> yük paketleniyor"
tar -C "${BUILD}" -czf "${PAYLOAD}" "hepgo-${INTEG}"

# ---- 5) kendinden çıkartmalı kurulum betiği (baş + yük) ----
HEAD="${BUILD}/head.sh"
cat > "${HEAD}" <<HEADEOF
#!/usr/bin/env bash
# HEPGO ${NAME} (${INTEG}) — Linux kurulumu. Kendinden çıkartmalı paket.
#   sudo bash \$0                 → /opt/hepgo-${INTEG} altına kurar + systemd servisini etkinleştirir
#   bash \$0 --dry-run [--extract-to DIR]  → yalnız açar (systemd'ye DOKUNMAZ) — test için
#   bash \$0 --no-start           → kurar ama servisi başlatmaz
#   bash \$0 --prefix DIR         → kurulum dizini (varsayılan /opt/hepgo-${INTEG})
set -euo pipefail
INTEG="${INTEG}"
NAME="${NAME}"
PREFIX="/opt/hepgo-${INTEG}"
DRYRUN=0 ; NOSTART=0 ; EXTRACT_TO=""
while [ \$# -gt 0 ]; do
  case "\$1" in
    --dry-run) DRYRUN=1 ;;
    --no-start) NOSTART=1 ;;
    --prefix) PREFIX="\$2"; shift ;;
    --extract-to) EXTRACT_TO="\$2"; shift ;;
    -h|--help) grep '^#' "\$0" | sed 's/^# \\?//'; exit 0 ;;
    *) echo "bilinmeyen seçenek: \$1" >&2; exit 2 ;;
  esac
  shift
done

SELF="\$0"
ARCHIVE_LINE=\$(awk '/^__PAYLOAD_BELOW__\$/ {print NR + 1; exit}' "\$SELF")
[ -n "\${ARCHIVE_LINE}" ] || { echo "HATA: yük bulunamadı" >&2; exit 1; }

if [ "\${DRYRUN}" = "1" ]; then
  DEST="\${EXTRACT_TO:-\$(mktemp -d)}"
  mkdir -p "\${DEST}"
  echo ">> [DRY-RUN] yük açılıyor: \${DEST}"
  tail -n +"\${ARCHIVE_LINE}" "\$SELF" | tar -xzf - -C "\${DEST}"
  echo ">> [DRY-RUN] açıldı. İçerik: \${DEST}/hepgo-${INTEG}"
  echo ">> [DRY-RUN] systemd / /opt kurulumu YAPILMADI."
  exit 0
fi

[ "\$(id -u)" = "0" ] || { echo "HATA: kurulum için kök (sudo) gerekir. Test için --dry-run kullanın." >&2; exit 1; }

echo ">> kuruluyor: \${PREFIX}"
TMP=\$(mktemp -d)
tail -n +"\${ARCHIVE_LINE}" "\$SELF" | tar -xzf - -C "\${TMP}"
mkdir -p "\${PREFIX}"
# agent-config.env korunur (yeniden kurulumda yapılandırma silinmez)
if [ -f "\${PREFIX}/agent-config.env" ]; then cp -a "\${PREFIX}/agent-config.env" "\${TMP}/hepgo-${INTEG}/agent-config.env"; fi
rm -rf "\${PREFIX}/python" "\${PREFIX}/code" "\${PREFIX}/VERSION"
cp -a "\${TMP}/hepgo-${INTEG}/." "\${PREFIX}/"
rm -rf "\${TMP}"

UNIT="/etc/systemd/system/hepgo-${INTEG}.service"
cat > "\${UNIT}" <<UNITEOF
[Unit]
Description=HEPGO Fabrika Ajanı — \${NAME} (${INTEG})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=\${PREFIX}/code
Environment=HEPGO_INTEG=${INTEG}
Environment=HEPGO_AGENT_CONFIG=\${PREFIX}/agent-config.env
Environment=HEPGO_LOCALCONFIG_PORT=8765
ExecStart=\${PREFIX}/python/bin/python3 -m agent.service
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNITEOF

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl enable hepgo-${INTEG}.service
  if [ "\${NOSTART}" != "1" ]; then
    systemctl restart hepgo-${INTEG}.service
    echo ">> servis başlatıldı: hepgo-${INTEG}.service"
    echo ">> İlk kurulumsa yapılandırma için:  journalctl -u hepgo-${INTEG} -n 20"
    echo ">>   (http://127.0.0.1:8765 adresindeki ayar sayfasını açın)"
  fi
else
  echo ">> UYARI: systemctl yok; birim yazıldı (\${UNIT}) ama etkinleştirilemedi."
fi
echo ">> kurulum tamam."
exit 0
__PAYLOAD_BELOW__
HEADEOF

cat "${HEAD}" "${PAYLOAD}" > "${INSTALLER}"
chmod +x "${INSTALLER}"
SIZE=$(du -h "${INSTALLER}" | cut -f1)
echo ">> ÜRETİLDİ: ${INSTALLER} (${SIZE})"
