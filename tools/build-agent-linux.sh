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
#   sudo bash \$0                 → /opt/hepgo-${INTEG} altına kurar + systemd servisini etkinleştirir (sistem/root)
#   bash \$0 --user               → sudo YOK; \$HOME altına kurar + systemctl --user servisi (önerilen; gx10 ile aynı düzen)
#   bash \$0 --dry-run [--extract-to DIR]  → yalnız açar (systemd'ye DOKUNMAZ) — test için
#   bash \$0 --no-start           → kurar ama servisi başlatmaz (sistem veya kullanıcı modu)
#   bash \$0 --prefix DIR         → kurulum dizini (sistem modu; varsayılan /opt/hepgo-${INTEG})
set -euo pipefail
INTEG="${INTEG}"
NAME="${NAME}"
PREFIX="/opt/hepgo-${INTEG}"
DRYRUN=0 ; NOSTART=0 ; EXTRACT_TO="" ; USERMODE=0
while [ \$# -gt 0 ]; do
  case "\$1" in
    --user) USERMODE=1 ;;
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
  echo ">> [DRY-RUN] systemd / /opt / \$HOME kurulumu YAPILMADI."
  exit 0
fi

if [ "\${USERMODE}" = "1" ]; then
  # ========== SUDOSUZ KULLANICI KURULUMU (systemd --user) ==========
  # Tamamen kullanıcının ev dizinine kurar; root / /opt / sudo KULLANMAZ.
  INSTALLDIR="\${HOME}/.local/share/hepgo-agent-${INTEG}"
  CFG="\${INSTALLDIR}/agent-config.env"
  UNITDIR="\${HOME}/.config/systemd/user"
  UNIT="\${UNITDIR}/hepgo-${INTEG}.service"

  echo ">> [kullanıcı] kuruluyor: \${INSTALLDIR}  (sudo YOK)"
  TMP=\$(mktemp -d)
  tail -n +"\${ARCHIVE_LINE}" "\$SELF" | tar -xzf - -C "\${TMP}"
  mkdir -p "\${INSTALLDIR}"
  # Mevcut yapılandırmayı koru (yeniden kurulumda agent-config.env silinmez).
  SAVED=""
  if [ -f "\${CFG}" ]; then SAVED=\$(mktemp); cp -a "\${CFG}" "\${SAVED}"; fi
  rm -rf "\${INSTALLDIR}/python" "\${INSTALLDIR}/app" "\${INSTALLDIR}/agent" "\${INSTALLDIR}/VERSION"
  # python/ + (code/ içeriği olan) app/ + agent/ doğrudan INSTALLDIR köküne yerleştirilir.
  cp -a "\${TMP}/hepgo-${INTEG}/python" "\${INSTALLDIR}/"
  cp -a "\${TMP}/hepgo-${INTEG}/code/." "\${INSTALLDIR}/"
  [ -f "\${TMP}/hepgo-${INTEG}/VERSION" ] && cp -a "\${TMP}/hepgo-${INTEG}/VERSION" "\${INSTALLDIR}/" || true
  rm -rf "\${TMP}"
  if [ -n "\${SAVED}" ]; then cp -a "\${SAVED}" "\${CFG}"; chmod 600 "\${CFG}" 2>/dev/null || true; rm -f "\${SAVED}"; fi

  # python-build-standalone bin/python sağlar; yoksa python3'e düş.
  PYBIN="\${INSTALLDIR}/python/bin/python"
  [ -x "\${PYBIN}" ] || PYBIN="\${INSTALLDIR}/python/bin/python3"

  mkdir -p "\${UNITDIR}"
  cat > "\${UNIT}" <<UNITEOF
[Unit]
Description=HEPGO ${NAME} ajanı (${INTEG}) — kullanıcı servisi
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=\${INSTALLDIR}
Environment=HEPGO_INTEG=${INTEG}
Environment=HEPGO_AGENT_CONFIG=\${CFG}
Environment=HEPGO_LOCALCONFIG_PORT=8765
ExecStart=\${PYBIN} -m agent.service
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNITEOF

  if command -v systemctl >/dev/null 2>&1; then
    if systemctl --user daemon-reload 2>/dev/null; then
      if [ "\${NOSTART}" != "1" ]; then
        if systemctl --user enable --now hepgo-${INTEG}.service 2>/dev/null; then
          echo ">> kullanıcı servisi etkinleştirildi ve başlatıldı: hepgo-${INTEG}.service"
        else
          echo ">> UYARI: 'systemctl --user enable --now' başarısız oldu."
          echo ">>   Etkin bir kullanıcı oturumu / XDG_RUNTIME_DIR gerekir. Elle:"
          echo ">>   systemctl --user enable --now hepgo-${INTEG}.service"
        fi
      else
        systemctl --user enable hepgo-${INTEG}.service 2>/dev/null || true
        echo ">> kullanıcı servisi etkinleştirildi (başlatılmadı): hepgo-${INTEG}.service"
      fi
    else
      echo ">> UYARI: 'systemctl --user' kullanılamadı; birim yazıldı (\${UNIT}) ama etkinleştirilemedi."
    fi
  else
    echo ">> UYARI: systemctl yok; birim yazıldı (\${UNIT}) ama etkinleştirilemedi."
  fi

  echo ""
  echo ">> KULLANICI KURULUMU TAMAM (sudo yok)."
  echo ">>   Kurulum dizini : \${INSTALLDIR}"
  echo ">>   Servis birimi  : \${UNIT}"
  echo ">>   Yapılandırma   : \${CFG}"
  echo ">>   Ayar arayüzü   : http://127.0.0.1:8765  (yapılandırma yoksa ilk açılışta açılır)"
  echo ">>   Günlük         : journalctl --user -u hepgo-${INTEG} -n 30"
  echo ""
  echo ">> BAŞSIZ (headless) NOT: Servisin oturum açmadan da çalışması için 'linger' AÇIK olmalı."
  echo ">>   Durum:  loginctl show-user \"\$USER\" -p Linger"
  echo ">>   Açmak (sudo ister; gx10'da zaten açık):  sudo loginctl enable-linger \"\$USER\""
  echo ""
  echo ">> BAŞSIZ ÖN-TOHUMLAMA (web arayüzü olmadan): şu dosyayı oluşturun →  \${CFG}"
  echo ">>   CAYMAZ_AGENT_CENTRAL_URL=wss://<alanadi>/ws/agent"
  echo ">>   CAYMAZ_AGENT_KEY=<ajan-anahtari>"
  echo ">>   HEPGO_INTEG=${INTEG}"
  echo ">>   # + bu entegrasyonun CAYMAZ_* cihaz değişkenleri"
  echo ">>   (dosya izni 600 önerilir: chmod 600 \"\${CFG}\")"
  exit 0
fi

# ========== SİSTEM (root) KURULUMU — varsayılan ==========
[ "\$(id -u)" = "0" ] || { echo "HATA: sistem kurulumu için kök (sudo) gerekir. Sudosuz için --user, test için --dry-run kullanın." >&2; exit 1; }

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
