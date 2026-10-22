#!/usr/bin/env python3
"""SIMUMAV dışa aktarma — HEPGO deposundan SIMUMAV çalışır ağacını üretir (docs/simumav.md §2, §6).

SIMUMAV kodu HEPGO deposunda geliştirilir (app/simumav, static/simumav + flightsim çekirdeği); bu betik yalnız SIMUMAV'ın
ihtiyaç duyduğu dosyaları seçip goktalay/simumav yayın deposunun klonuna kopyalar. Oradan `v*` etiketi ile GitHub Actions
paketi mastertool.download'a yükler ve sunucu otomatik yayımlar (deploy/simumav/).

Kullanım:
    .venv/bin/python tools/simumav_export.py [--src <hepgo kökü>] [--dest ~/mt-work/simumav] [--version 0.1.0]
                                             [--dry-run] [--include-hepgo] [--force] [--json]

Çözüm mantığı:
  * MANIFEST'teki glob'lar kopyalanır; karşılığı olmayan glob UYARI verir, hata vermez (henüz yazılmamış dosyalar).
  * Python: PY_CEKIRDEK + app/simumav/** AST ile taranır; `from . import x` / `from .x import y` / `from .x.y import z`
    zinciri kapanana dek izlenir. Çözülen modül HEPGO_OZGU kümesindeyse (app/main.py, app/db.py, ...) UYARI verilir ve
    kopyalanMAZ (--include-hepgo ile zorlanabilir) — çekirdek bunları app/simumav/bridge.py ile almalıdır (§1, §7).
  * JS: JS_CEKIRDEK + static/simumav/** taranır; `import ... from './x.js'`, `import('./x.js')`, `export ... from './x.js'`
    göreli zinciri izlenir. HEPGO `static/js/api.js` kopyalanmaz (simumav `simapi.js` sağlar, §2). `/vendor/<ad>/` ya da
    `../vendor/<ad>/` başvuruları o vendor klasörünü tamamen ekler.
  * requirements.txt: Python dosyalarındaki üçüncü parti üst düzey importlar → PIP_ADI eşlemesi → HEPGO requirements.txt
    satırındaki sürüm kısıtı ile. uvicorn[standard] her zaman (run-simumav.sh), python-multipart Form/File/UploadFile
    kullanılıyorsa eklenir. Eşlenemeyen üçüncü parti modül UYARI.
  * Hedef temizlenir; KORUNAN girdiler (.git, .github, scripts, CHANGELOG.md) dokunulmaz; README.md ve .gitignore şablondan
    yeniden yazılır; VERSION yazılır.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import sys
from pathlib import Path

# --------------------------------------------------------------------------- manifest
PY_CEKIRDEK = ['app/__init__.py', 'app/flightsim.py', 'app/flightsim_hub.py', 'app/flightsim_mission.py', 'app/flightsim_rec.py',
               'app/flightsim_bin.py', 'app/flightsim_replay.py', 'app/flightsim_runs.py', 'app/flightsim_models.py',
               'app/sim_terrain.py', 'app/drone_sitl.py', 'app/drone_params.py', 'app/flightsim_power.py', 'app/flightsim_icept.py', 'app/flightsim_targets.py', 'app/flightsim_gcs.py', 'app/flightsim_launcher.py',
               'app/flightsim_servotrig.py', 'app/flightsim_match_core.py', 'app/flightsim_match_bot.py', 'app/flightsim_gpws.py', 'app/tlog.py']   # §23 güç · §25 INTERCEPTOR · §24 hedefler · §26 yer kontrol sahası · §27 fırlatıcılar · §33/SIMUMAV §18 karşılaşma çekirdeği · §44 yapay zekâ pilot · §8.6 tlog araç seçimi (replay) · §42 uçuş uyarıları
JS_CEKIRDEK = ['static/js/modules/flightsim*.js', 'static/js/modules/fs_inputs.js', 'static/js/modules/flightlog_origin.js', 'static/js/modules/replay3d.js', 'static/js/modules/flightsim_g3d.js']
MANIFEST = ['app/simumav/**', *PY_CEKIRDEK, 'static/simumav/**', *JS_CEKIRDEK, 'static/vendor/three/**', 'static/vendor/xterm/**',
            # HEPGO modüllerinin kök seviye bağımlılıkları (simumav main.py `/<ad>.js` beyaz listesi) ve sabit yollu varlıklar (§2 yönlendirmeler)
            'static/js/ui.js', 'static/js/i18n.js', 'static/js/icons.js', 'static/js/segicons.js', 'static/js/fa-icons.js', 'static/js/step3d.js',
            'static/js/engine3d.js', 'static/js/gcode3d.js', 'static/js/imgopt.js', 'static/img/google-logo.png', 'static/models/caymaz-sim.glb',
            'run-simumav.sh', 'deploy/simumav/**', 'docs/simumav.md', 'tests/test_simumav*', 'tests/simumav_*.py', 'tests/__init__.py',
            'tests/match_bot.py']   # §18 karşılaşma testinin rota pilotu (yalnız test aracı)

# HEPGO'ya özgü app/ modülleri: SIMUMAV ağacına girmemeli (ERP veritabanı/kullanıcı/yetki/akış). Zincirde çıkarsa UYARI.
HEPGO_OZGU = {'main', 'db', 'config', 'auth', 'feed', 'users', 'rbac', 'permissions', 'tenants', 'mail', 'chat', 'notify',
              'push', 'drone_hub', 'flightlog', 'flight_analysis', 'documents', 'crm', 'hr', 'planner', 'console'}
# Göreli JS importu kopyalanmaz: YALNIZ HEPGO static/js/api.js (simumav kendi api köprüsünü sağlar: static/simumav/app/simapi.js, /sim/api.js
# yönlendirmesi). static/simumav/app/core/api.js gerçek bir SIMUMAV dosyasıdır ve kopyalanır.
# §45 uçuş yığını seçici (ucus_yigini.js) YALNIZ HEPGO: flightsim.js sihirbazı onu meta.stacks varsa dinamik yükler; SIMUMAV'a kopyalanmaz
# (Python tarafı app/flightsim_px4.py zaten zincirde yok: flightsim.py importlib ile yalnız stack verilince yükler).
JS_DISLANAN = {'static/js/api.js', 'static/js/modules/ucus_yigini.js'}

# Hedefte asla silinmeyen girdiler (yayın deposunun kendi dosyaları)
KORUNAN = {'.git', '.github', 'scripts', 'CHANGELOG.md', 'README.md', '.gitignore', 'VERSION'}

# import adı → pip paketi (HEPGO requirements.txt'teki ad)
PIP_ADI = {'fastapi': 'fastapi', 'starlette': 'fastapi', 'pydantic': 'fastapi', 'uvicorn': 'uvicorn', 'httpx': 'httpx',
           'pymavlink': 'pymavlink', 'av': 'av', 'cv2': 'opencv-python-headless', 'numpy': 'numpy', 'PIL': 'Pillow',
           'multipart': 'python-multipart', 'websockets': 'websockets', 'onnxruntime': 'onnxruntime', 'anthropic': 'anthropic',
           'pywebpush': 'pywebpush', 'firebird': 'firebird-driver', 'yaml': 'PyYAML', 'aiofiles': 'aiofiles',
           'jinja2': 'Jinja2', 'markdown': 'Markdown'}
HER_ZAMAN_PIP = ['uvicorn']          # run-simumav.sh uvicorn ile başlatır; kodda import edilmez
STDLIB = set(getattr(sys, 'stdlib_module_names', ())) | {'__future__', 'typing_extensions'}

GITIGNORE = """# SIMUMAV yayın deposu — tools/simumav_export.py üretir; elle düzenleme HEPGO deposunda yapılır.
.venv/
__pycache__/
*.pyc
.env
.env.*
*.db
*.db-wal
*.db-shm
/data/
/dist/
*.tar.gz
"""

README_SABLON = """# SIMUMAV — bağımsız dron simülasyon oyunu

Sürüm: **{version}** · Site: https://simumav.com · Hesap: https://mastertool.download (uygulama kodu `sv`)

HEPGO Uçuş Simülatörü çekirdeğinin (ArduPilot SITL + Google 3B / gerçek arazi + dron paneli + görev / çarpışma / .bin /
replay) HEPGO'dan **bağımsız**, mastertool.download hesap yapısıyla çalışan, oyun görünümünde sürümü.
Sözleşme: `docs/simumav.md` (mimari, veri modeli, REST yüzeyi, güvenlik, yayın).

> Bu depo **üretilmiş** bir ağaçtır. Kaynak geliştirme HEPGO deposunda (`fabrika-yonetim`) yapılır; buradaki dosyalar
> `tools/simumav_export.py` ile dışa aktarılır. Buraya doğrudan commit atılan kod değişiklikleri bir sonraki dışa aktarmada
> silinir — yalnız `.github/`, `scripts/`, `CHANGELOG.md` korunur.

## Mimari özet

- `app/simumav/` — ayrı ASGI uygulaması (`app.simumav.main:app`): oturum (hesap servisi belirteci → kendi HttpOnly çerezi),
  hangar / mürettebat / parkur / görev / uçuş / operasyon REST'i, `bridge.py` ile flightsim çekirdeğine adaptör.
- `app/flightsim*.py`, `sim_terrain.py`, `drone_sitl.py`, `drone_params.py` — HEPGO ile **aynı** simülasyon çekirdeği.
- `static/simumav/site` tanıtım sitesi, `static/simumav/app` oyun arayüzü; `static/js/modules/flightsim*.js`, `replay3d.js`
  simülatör ön yüzü (`/sim` olarak mount edilir); `static/vendor/three`, `static/vendor/xterm` CDN'siz bağımlılıklar.
- Veri: `SIMUMAV_DATA_DIR` altında sqlite (`simumav.db`) + `files/`. HEPGO veritabanına erişim yoktur.

## Çalıştırma (geliştirme)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env 2>/dev/null || true     # GOOGLE_MAPS_API_KEY, SIMUMAV_SECRET, SIMUMAV_MT_URL, SIMUMAV_DATA_DIR
SIMUMAV_DEV_LOGIN=1 PORT=8600 ./run-simumav.sh    # http://127.0.0.1:8600
python -m tests.test_simumav                      # SITL gerekmez
python -m tests.test_simumav_power                # güç ve yakıt (§10); SITL gerekmez
python -m tests.test_simumav_match                # çok oyunculu karşılaşma (§18); SITL gerekmez
node tests/test_simumav_power.mjs && node tests/test_simumav_fly.mjs && node tests/test_simumav_match.mjs
```

SITL (ArduPilot) kurulu değilse uçuş sahte kinematikle çalışır (`HEPGO_SITL=0`).

## Geliştirme akışı

1. HEPGO deposunda değişikliği yap, testleri çalıştır.
2. `./.venv/bin/python tools/simumav_export.py --dest ~/mt-work/simumav --version X.Y.Z` → bu ağacı yeniler
   (`--dry-run` ile önce ne olacağını gör).
3. Bu depoda `git add -A && git commit` → `git push`.

## Yayın

```bash
git tag vX.Y.Z && git push origin vX.Y.Z
```

`.github/workflows/release.yml`: testler → `simumav-X.Y.Z.tar.gz` + `.sha256` → GitHub Release → `scripts/upload-mastertool.sh`
ile `https://mastertool.download/api/sv/web-releases` (anahtar: depo secret `SIMUMAV_RELEASE_KEY`). Sunucuda
`hepgo-simumav-deploy.path` yeni sürümü görür, `deploy/simumav/deploy.sh` doğrular, kurar, sağlık denetimi başarısızsa önceki
sürüme döner. Ayrıntı: `deploy/simumav/README.md`.

## Sunucu kurulumu

`deploy/simumav/README.md` — `hepgo-simumav.service` (uygulama), `hepgo-simumav-deploy.path/.service` (otomatik yayın),
cloudflared ingress parçası, `.env` alanları.
"""


# --------------------------------------------------------------------------- yardımcılar
class Rapor:
    def __init__(self):
        self.uyarilar: list[str] = []
        self.notlar: list[str] = []
        self.shim: list[str] = []      # HEPGO'ya özgü modül → SIMUMAV shim eşlemesi (tasarım gereği; not/uyarı değil)
        self.py_zincir: dict[str, str] = {}    # modül → kimden geldi
        self.js_zincir: dict[str, str] = {}
        self.vendor: set[str] = set()
        self.requirements: list[str] = []
        self.dosyalar: list[str] = []
        self.silinen: list[str] = []
        self.eksik_glob: list[str] = []

    def uyar(self, m):
        self.uyarilar.append(m)

    def not_(self, m):
        self.notlar.append(m)


def glob_coz(src: Path, desen: str) -> list[Path]:
    """`a/b/**` → a/b altındaki tüm dosyalar; aksi halde Path.glob. Yalnız dosyalar, .pyc/__pycache__ hariç."""
    if desen.endswith('/**'):
        kok = src / desen[:-3]
        yollar = [p for p in kok.rglob('*') if p.is_file()] if kok.is_dir() else []
    else:
        yollar = [p for p in src.glob(desen) if p.is_file()]
    return sorted(p for p in yollar if '__pycache__' not in p.parts and not p.name.endswith(('.pyc', '.pyo')))


def py_ic_importlar(dosya: Path) -> tuple[list[str], set[str], bool]:
    """(göreli import hedefleri [(level, ad)…], üçüncü parti üst düzey adlar, multipart gerekiyor mu). `from . import x` dosyanın kendi paketine
    göre çözülür (app/simumav/routers/x.py içindeki `..` = app/simumav). Söz dizimi hatasında boş + uyarı yok."""
    try:
        agac = ast.parse(dosya.read_text(encoding='utf-8'), filename=str(dosya))
    except (SyntaxError, UnicodeDecodeError):
        return [], set(), False
    goreli: list[tuple[int, str]] = []
    ucuncu: set[str] = set()
    multipart = False
    for n in ast.walk(agac):
        if isinstance(n, ast.ImportFrom):
            if n.level:                                   # from . import x  |  from .x import y  |  from .x.y import z
                if n.module:
                    goreli.append((n.level, n.module.split('.')[0]))
                else:
                    goreli.extend((n.level, a.name) for a in n.names)
            else:
                ust = (n.module or '').split('.')[0]
                if ust and ust not in STDLIB:
                    ucuncu.add(ust)
                if ust == 'fastapi' and any(a.name in ('Form', 'File', 'UploadFile') for a in n.names):
                    multipart = True
        elif isinstance(n, ast.Import):
            for a in n.names:
                ust = a.name.split('.')[0]
                if ust not in STDLIB:
                    ucuncu.add(ust)
    return goreli, ucuncu, multipart


def py_modul_yolu(src: Path, ad: str, kaynak: Path | None = None, level: int = 1) -> Path | None:
    """Göreli import hedefi: `kaynak` dosyasının paketinden `level` kadar yukarı (1 = kendi paketi) → <paket>/<ad>.py ya da <paket>/<ad>/__init__.py.
    kaynak verilmezse app/ kökü varsayılır."""
    paket = (kaynak.parent if kaynak is not None else src / 'app')
    for _ in range(max(0, level - 1)):
        paket = paket.parent
    for aday in (paket / f'{ad}.py', paket / ad / '__init__.py'):
        if aday.is_file():
            return aday
    return None


def shim_modulu(src: Path, ad: str) -> Path | None:
    """HEPGO'ya özgü modülün SIMUMAV karşılığı (app/simumav/shim/<ad>.py): varsa zincir uyarısı yerine not düşülür (sys.modules ile sağlanır)."""
    aday = src / 'app' / 'simumav' / 'shim' / f'{ad}.py'
    return aday if aday.is_file() else None


JS_IMPORT_RE = re.compile(r"""(?:import|export)\s*(?:[\w*{}\s,$]*?\s*from\s*)?['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)""")


JS_YORUM_RE = re.compile(r'/\*.*?\*/|^[ \t]*//[^\n]*', re.S | re.M)


def js_importlar(dosya: Path) -> list[str]:
    try:
        metin = dosya.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return []
    return [a or b for a, b in JS_IMPORT_RE.findall(JS_YORUM_RE.sub('', metin))]


# --------------------------------------------------------------------------- çözümleyici
def coz(src: Path, rapor: Rapor, include_hepgo: bool) -> set[Path]:
    secilen: set[Path] = set()

    # 1) manifest
    for desen in MANIFEST:
        bulunan = glob_coz(src, desen)
        if not bulunan:
            rapor.eksik_glob.append(desen)
            rapor.uyar(f'manifest karşılığı yok (henüz yazılmamış olabilir): {desen}')
        secilen.update(bulunan)

    # 2) Python import zinciri (çekirdek + app/simumav)
    kuyruk = [p for p in secilen if p.suffix == '.py' and p.parts[len(src.parts)] == 'app']
    gorulen = set(kuyruk)
    ucuncu: set[str] = set()
    multipart = False
    while kuyruk:
        d = kuyruk.pop()
        goreli, u, mp = py_ic_importlar(d)
        ucuncu |= u
        multipart |= mp
        kaynak = d.relative_to(src).as_posix()
        for level, ad in goreli:
            yol = py_modul_yolu(src, ad, d, level)
            if yol is None:
                if ad not in ('simumav',):       # app/simumav alt paketi zaten manifestte
                    rapor.not_(f'{kaynak}: göreli import çözülemedi: {"." * level}{ad}')
                continue
            if yol in gorulen or yol in secilen:
                continue
            app_kok = yol.parent == src / 'app' and yol.name == f'{ad}.py'   # yalnız app/<ad>.py HEPGO'ya özgü olabilir (app/simumav/auth.py değil)
            if app_kok and ad in HEPGO_OZGU and not include_hepgo:
                if shim_modulu(src, ad) is not None:
                    rapor.shim.append(f'app/{ad} ← {kaynak} → app/simumav/shim/{ad}.py')
                else:
                    rapor.uyar(f"HEPGO'ya özgü modül zincirde: app/{ad} ← {kaynak} (kopyalanmadı; shim ile sağlanmalı: app/simumav/shim/{ad}.py)")
                gorulen.add(yol)
                continue
            rapor.py_zincir[yol.relative_to(src).as_posix()] = kaynak
            secilen.add(yol)
            gorulen.add(yol)
            kuyruk.append(yol)

    # 3) requirements
    req_satir: dict[str, str] = {}
    req_dosya = src / 'requirements.txt'
    if req_dosya.is_file():
        for satir in req_dosya.read_text(encoding='utf-8').splitlines():
            s = satir.split('#')[0].strip()
            if not s:
                continue
            ad = re.split(r'[\[<>=!~ ]', s, 1)[0].lower()
            req_satir[ad] = s
    paketler: dict[str, str] = {}
    for mod in sorted(ucuncu):
        pip = PIP_ADI.get(mod)
        if pip is None:
            if py_modul_yolu(src, mod) is None and not (src / 'app' / mod).exists():
                rapor.uyar(f'üçüncü parti import pip adına eşlenemedi: {mod} (PIP_ADI tablosuna ekleyin)')
            continue
        paketler[pip] = req_satir.get(pip.lower(), pip)
    for pip in HER_ZAMAN_PIP:
        paketler.setdefault(pip, req_satir.get(pip, pip))
    if multipart:
        paketler.setdefault('python-multipart', req_satir.get('python-multipart', 'python-multipart'))
    rapor.requirements = sorted(paketler.values(), key=str.lower)

    # 4) JS göreli zinciri + vendor
    js_kuyruk = [p for p in secilen if p.suffix in ('.js', '.mjs') and 'static' in p.parts]
    js_gorulen = set(js_kuyruk)
    while js_kuyruk:
        d = js_kuyruk.pop()
        kaynak = d.relative_to(src).as_posix()
        for ref in js_importlar(d):
            ref_yol = ref.split('?')[0]
            m = re.search(r'(?:^|/)vendor/([^/]+)/', ref_yol)
            if m:
                vendor_kok = src / 'static' / 'vendor' / m.group(1)
                if vendor_kok.is_dir() and m.group(1) not in rapor.vendor:
                    rapor.vendor.add(m.group(1))
                    secilen.update(glob_coz(src, f'static/vendor/{m.group(1)}/**'))
                continue
            if not ref_yol.startswith('.'):
                continue                                  # çıplak belirteç ya da mutlak URL: dokunma
            hedef = (d.parent / ref_yol).resolve()
            try:
                hg = hedef.relative_to(src).as_posix()
            except ValueError:
                hg = str(hedef)
            if hg in JS_DISLANAN:
                continue                                  # HEPGO api.js: simumav main.py /api.js + /sim/api.js → simapi.js (§2); not gerekmez
            if not hedef.is_file():
                rapor.uyar(f'{kaynak}: göreli JS importu bulunamadı: {ref_yol}')
                continue
            if hedef in js_gorulen or hedef in secilen:
                js_gorulen.add(hedef)
                continue
            try:
                hedef.relative_to(src / 'static')
            except ValueError:
                rapor.uyar(f'{kaynak}: static dışına import: {ref_yol}')
                continue
            rapor.js_zincir[hedef.relative_to(src).as_posix()] = kaynak
            secilen.add(hedef)
            js_gorulen.add(hedef)
            js_kuyruk.append(hedef)
    return secilen


# --------------------------------------------------------------------------- yazım
def surum_bul(src: Path, dest: Path, istenen: str | None) -> str:
    if istenen:
        return istenen.lstrip('vV')
    v = dest / 'VERSION'
    if v.is_file() and v.read_text().strip():
        return v.read_text().strip()
    return '0.1.0'       # HEPGO'nun kendi etiketleri (v2.x) SIMUMAV sürümü değildir; git describe kullanılmaz


def temizle(dest: Path, rapor: Rapor, dry: bool):
    for giris in sorted(dest.iterdir()):
        if giris.name in KORUNAN:
            continue
        rapor.silinen.append(giris.name)
        if not dry:
            if giris.is_dir() and not giris.is_symlink():
                shutil.rmtree(giris)
            else:
                giris.unlink()


def yaz(src: Path, dest: Path, secilen: set[Path], version: str, rapor: Rapor, dry: bool):
    for p in sorted(secilen):
        gorel = p.relative_to(src)
        rapor.dosyalar.append(gorel.as_posix())
        if dry:
            continue
        hedef = dest / gorel
        hedef.parent.mkdir(parents=True, exist_ok=True)
        if p.is_symlink():
            rapor.uyar(f'sembolik bağ kopyalanmadı: {gorel}')
            continue
        shutil.copy2(p, hedef)
    uretilen = {'requirements.txt': '\n'.join(rapor.requirements) + '\n', 'VERSION': version + '\n',
                'README.md': README_SABLON.format(version=version), '.gitignore': GITIGNORE}
    for ad, icerik in uretilen.items():
        rapor.dosyalar.append(f'{ad} (üretildi)')
        if not dry:
            (dest / ad).write_text(icerik, encoding='utf-8')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='HEPGO → SIMUMAV dışa aktarma')
    ap.add_argument('--src', default=str(Path(__file__).resolve().parents[1]), help='HEPGO depo kökü')
    ap.add_argument('--dest', default=str(Path.home() / 'mt-work' / 'simumav'), help='SIMUMAV yayın deposu klonu')
    ap.add_argument('--version', help='VERSION içeriği (varsayılan: hedefteki VERSION, yoksa 0.1.0)')
    ap.add_argument('--dry-run', action='store_true', help='hiçbir şey yazma/silme; planı göster')
    ap.add_argument('--include-hepgo', action='store_true', help="HEPGO'ya özgü modülleri de kopyala (önerilmez)")
    ap.add_argument('--force', action='store_true', help='hedefte .git yoksa ve boş değilse de temizle')
    ap.add_argument('--json', action='store_true', help='raporu JSON olarak yaz')
    a = ap.parse_args(argv)

    src, dest = Path(a.src).resolve(), Path(a.dest).expanduser().resolve()
    if not (src / 'app').is_dir() or not (src / 'static').is_dir():
        print(f'HATA: {src} bir HEPGO depo kökü değil (app/ ve static/ yok)', file=sys.stderr)
        return 2
    rapor = Rapor()
    secilen = coz(src, rapor, a.include_hepgo)
    version = surum_bul(src, dest, a.version)

    if dest.exists():
        if not dest.is_dir():
            print(f'HATA: {dest} bir dizin değil', file=sys.stderr)
            return 2
        if not (dest / '.git').exists() and any(dest.iterdir()) and not a.force:
            print(f'HATA: {dest} boş değil ve .git içermiyor; yanlış hedef olabilir (--force ile zorla)', file=sys.stderr)
            return 2
        temizle(dest, rapor, a.dry_run)
    elif not a.dry_run:
        dest.mkdir(parents=True)
    yaz(src, dest, secilen, version, rapor, a.dry_run)

    if a.json:
        print(json.dumps({'version': version, 'dry_run': a.dry_run, 'dosyalar': rapor.dosyalar, 'silinen': rapor.silinen,
                          'py_zincir': rapor.py_zincir, 'js_zincir': rapor.js_zincir, 'vendor': sorted(rapor.vendor),
                          'requirements': rapor.requirements, 'eksik_glob': rapor.eksik_glob, 'uyarilar': rapor.uyarilar,
                          'notlar': rapor.notlar, 'shim': rapor.shim}, ensure_ascii=False, indent=1))
        return 0
    on = '[KURU] ' if a.dry_run else ''
    print(f'{on}SIMUMAV {version}: {src} → {dest}')
    print(f'{on}{len(rapor.dosyalar)} dosya' + (f', hedefte temizlenen: {", ".join(rapor.silinen)}' if rapor.silinen else ''))
    if rapor.py_zincir:
        print('Python import zinciriyle eklenen:')
        for m, k in sorted(rapor.py_zincir.items()):
            print(f'  {m}  ← {k}')
    if rapor.js_zincir:
        print('JS import zinciriyle eklenen:')
        for m, k in sorted(rapor.js_zincir.items()):
            print(f'  {m}  ← {k}')
    if rapor.vendor:
        print('Vendor: ' + ', '.join(sorted(rapor.vendor)))
    print('requirements.txt: ' + ' | '.join(rapor.requirements))
    if rapor.shim:
        print('Shim ile sağlanan HEPGO modülleri: ' + ', '.join(rapor.shim))
    for n in rapor.notlar:
        print(f'  not: {n}')
    for u in rapor.uyarilar:
        print(f'UYARI: {u}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
