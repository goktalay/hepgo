# HEPGO Fabrika Ajanı — kurulum paketi üretimi (tools/)

Her entegrasyon (mikro, pdks, printer, camera, face) **ayrı** indirilir, **ayrı anahtarla** çalışır.
Paketler entegrasyon başına üretilir ve merkez indirme uçlarının beklediği yola yazılır:

    agent-dist/<integ>/hepgo-<integ>-setup-linux.sh      (Linux, kendinden çıkartmalı)
    agent-dist/<integ>/hepgo-<integ>-setup-windows.exe   (Windows, Inno Setup)

`<integ>` ∈ { mikro, pdks, printer, camera, face }. Tanımların tek kaynağı: `agent/profiles.py`.

## Linux (burada üretilebilir ve test edilebilir)
```sh
tools/build-agent-linux.sh <integ>     # tek entegrasyon
tools/build-agent-all.sh               # beşini sırayla
```
Üretilen `.sh` kendinden çıkartmalıdır (kabuk başı + sonuna eklenmiş `tar.gz` yük). İçinde:
- taşınabilir **CPython 3.12.7** (python-build-standalone, pinli `x86_64-unknown-linux-gnu`, sha256
  doğrulanır),
- **taban** (`websockets`, `httpx`) + o entegrasyonun ek pip bağımlılıkları o Python'a kurulu,
- `app/` + `agent/` kodu.

Kurulum / test:
```sh
sudo bash hepgo-<integ>-setup-linux.sh                 # /opt/hepgo-<integ> + systemd (hepgo-<integ>.service)
bash hepgo-<integ>-setup-linux.sh --dry-run            # yalnız açar; systemd'ye DOKUNMAZ (test)
bash hepgo-<integ>-setup-linux.sh --dry-run --extract-to DIR
sudo bash hepgo-<integ>-setup-linux.sh --no-start      # kur ama başlatma
sudo bash hepgo-<integ>-setup-linux.sh --prefix DIR    # farklı kurulum dizini
```
İlk açılışta yapılandırma yoksa servis yerel ayar sayfasını (`http://127.0.0.1:8765`) başlatır ve
URL'yi loglar (`journalctl -u hepgo-<integ>`).

## Windows (yalnız tooling — .exe bir Windows makinesinde üretilir)
- `tools/build-agent-windows.ps1 <integ>` — pinli msvc CPython + taban/entegrasyon pip + kod + NSSM
  hazırlar ve Inno Setup (`ISCC.exe`) ile `.exe` derler.
- `tools/hepgo-agent.iss` — Inno şablonu, `/DInteg`, `/DIntegName`, `/DStageDir`, `/DOutDir` ile
  parametrelenir. Windows servisi (NSSM), başlat menüsü/masaüstü kısayolu (ayar sayfası) kurar.
- Ayrıntılı adımlar: `agent-dist/README-windows-build.md`.

## Çalışma zamanı modeli
Servis `python -m agent.service` çalıştırır (ortam: `HEPGO_INTEG=<integ>`,
`HEPGO_AGENT_CONFIG=<yol>`). Ajan merkeze `wss://<domain>/ws/agent` ile bağlanır ve ilk mesajı:
`{"t":"auth","key":"<anahtar>","host":"<makine>","integ":"<integ>"}` gönderir. Merkez anahtarı o
entegrasyonun slotuna kaydeder ve yalnız o entegrasyonun op'larını bu ajana yönlendirir.

Önbellek: indirilen CPython/NSSM `tools/.cache/` altında tutulur (sürüm kontrolüne girmemeli).
