# Hepgo Dron Köprüsü — Linux / NVIDIA Jetson kurulum rehberi

Jetson (Nano, Xavier NX, Orin) dronun üstünde ya da yer istasyonunda çalışan **başsız** köprüdür: uçuş kontrolcüsünün MAVLink telemetrisini
(UART / USB / UDP / TCP) ve gimbal kameranın görüntüsünü (RTSP / RTP) HEPGO'ya taşır. Sunucuya yalnız **dışa doğru** WebSocket açar
(`wss://<alan>/ws/drone/bridge` telemetri, `wss://<alan>/ws/drone/video` görüntü); 4G modem / NAT arkasında port yönlendirme gerekmez.
Protokol: `docs/dron-kopru-protokolu.md` (v1 telemetri, v1.3 görüntü). Kaynak: `bridge/dron_koprusu_linux/` + paylaşılan çekirdek
`bridge/dron_koprusu/kopru_core.py`, `goruntu_core.py`. Paket: `tools/kopru_linux_paket.py` → `HepgoDronKoprusu-Linux-Jetson-<sürüm>.tar.gz`.

## 1. Desteklenen sistemler

| Jetson | JetPack | Ubuntu | Python | Not |
|---|---|---|---|---|
| Nano (4 GB / 2 GB) | 4.6.x (L4T R32.7) | 18.04 aarch64 | varsayılan 3.6 → **install.sh python3.8 kurar** | J41 UART `/dev/ttyTHS1`, `nvgetty` kapatılmalı olabilir |
| Xavier NX / AGX | 5.1.x (L4T R35) | 20.04 | 3.8 | J12 UART `/dev/ttyTHS0` (NX: pin 8/10) |
| Orin Nano / NX / AGX | 6.x (L4T R36) | 22.04 | 3.10 | 40 pinli başlık UART `/dev/ttyTHS1` (Orin Nano dev kit: `/dev/ttyTHS0` olabilir — `ls /dev/ttyTHS*`) |
| Herhangi bir Ubuntu / Debian | — | 18.04+ | 3.8+ | x86_64 ya da aarch64; USB `/dev/ttyACM0` |

Bağımlılıklar Python 3.8'i destekleyen son sürümlere sabittir (`requirements.txt`: websockets 13.1, pymavlink 2.4.49, pyserial 3.5); aarch64 için
hazır tekerlek vardır, derleme gerekmez. Görüntü için `ffmpeg` (apt) gerekir; Jetson'da yeniden kodlama donanımla (GStreamer `nvv4l2h264enc`) yapılır.

## 2. Kurulum

1. HEPGO › Dron Yönetimi › **Dron Köprüleri** › "＋ Yeni Köprü" (platform: linux) → **köprü kodu** bir kez gösterilir (`<alan>/<anahtar>`).
   Aynı sayfanın üstündeki "Linux / Jetson (arm64)" kartından paketi indirin.
2. Jetson'a kopyalayıp kurun:
   ```bash
   scp HepgoDronKoprusu-Linux-Jetson-1.1.0.tar.gz jetson@<ip>:
   tar xzf HepgoDronKoprusu-Linux-Jetson-1.1.0.tar.gz && cd HepgoDronKoprusu-Linux-Jetson-1.1.0
   sudo ./install.sh                 # Nano + ttyTHS1 için: sudo ./install.sh --nvgetty-kapat
   sudo hepgo-kopru eslestir caymaz.app/AbC…   # köprü kodu (sunucuya bağlanıp doğrular, servisi yeniden başlatır)
   hepgo-kopru durum
   ```
   6 haneli eşleştirme koduyla: `sudo hepgo-kopru eslestir --alan caymaz.app 7KX2QD`. Çevrim dışı kurulum: `--dogrulama-yok`.
3. install.sh şunları yapar: apt ile `python3.8 python3.8-venv` (yalnız 18.04), `ffmpeg`, GStreamer araçları (`--gst-yok` ile atlanır);
   `hepgo-kopru` sistem kullanıcısı (`dialout`, `video` grupları); `/opt/hepgo-kopru/{app,venv}`; `/usr/local/bin/hepgo-kopru`;
   `/etc/hepgo-kopru/kopru.conf` (varsa korunur; 0640 root:hepgo-kopru — köprü anahtarını içerir); systemd `hepgo-kopru.service` (etkin).
4. Kaldırma: `sudo /opt/hepgo-kopru/uninstall.sh` (yapılandırma korunur) · `--hepsi` (yapılandırma ve kullanıcı da silinir).

Servis: `Restart=on-failure` (5 sn); köprü kodu yok/geçersiz → çıkış 3 ve **durur** (`RestartPreventExitStatus=3`), `eslestir` yeniden başlatır.
Günlük journald'da: `hepgo-kopru log -f` (= `journalctl -u hepgo-kopru -f`). Anlık durum: `/run/hepgo-kopru/durum.json` (`hepgo-kopru durum --json`).

## 3. Uçuş kontrolcüsü bağlantısı (UART)

Pixhawk / Cube **TELEM2** ↔ Jetson 40 pinli başlık (Nano'da J41):

| Pixhawk TELEM2 | Jetson J41 | Not |
|---|---|---|
| TX (pin 2) | **pin 10** (UART1_RXD → `/dev/ttyTHS1`) | çapraz |
| RX (pin 3) | **pin 8** (UART1_TXD) | çapraz |
| GND (pin 6) | **pin 6** (GND) | ortak toprak ŞART |
| 5V (pin 1) | — | **bağlamayın** (Jetson'u ayrı besleyin) |

Seviyeler 3,3 V'tur (Pixhawk TELEM ve Jetson UART uyumlu); CTS/RTS gerekmez (`BRD_SER2_RTSCTS = 0`).
ArduPilot parametreleri (Mission Planner › Full Parameter List):

| Parametre | Değer | Anlamı |
|---|---|---|
| `SERIAL2_PROTOCOL` | **2** | MAVLink 2 |
| `SERIAL2_BAUD` | **921** | 921600 bps (sorun olursa 115 → 115200; conf `baud`'u da değiştirin) |
| `BRD_SER2_RTSCTS` | 0 | akış denetimi yok |
| `SR2_*` | boş bırakılabilir | köprü ilk HEARTBEAT'te veri akışlarını kendisi ister (4 Hz) |

`/etc/hepgo-kopru/kopru.conf`:
```ini
[baglanti]
tur = serial
cihaz = /dev/ttyTHS1      ; USB ile: /dev/ttyACM0 · Mission Planner/mavproxy'den: tur = udp, port = 14550
baud = 921600
```
Değişiklikten sonra `sudo systemctl restart hepgo-kopru`. Seri port çıkarılır / dron kapanırsa köprü 5 sn'de bir yeniden açmayı dener; sunucu bağlantısı
koparsa 2→30 sn artan beklemeyle yeniden bağlanır. `tur = yok` ise bağlantı HEPGO Canlı Uçuş › Bağlantı Yöneticisi'nden (uçuşun link ayarı) açılır.

## 4. Kamera (görüntü köprüsü)

Kameralar **siteden** tanımlanır: HEPGO › Dron Yönetimi › **Kameralar** › "＋ Yeni Kamera" → köprü olarak bu Jetson'u seçin (görüntü yeteneği olan
köprüler listede önde ve "görüntü" etiketli). Kayıt kaydedilince köprüye `video_cfg` gider; Jetson'da ayar gerekmez (conf `[kamera.N]` yalnız yedek).
Köprü yalnız izleyen varken yayınlar (4G bant tasarrufu); izleyen kalmayınca 20 sn sonra durur.

| Kaynak | Kayıt | Not |
|---|---|---|
| Siyi A8 / ZR10 / ZR30 | RTSP `rtsp://192.168.144.25:8554/main.264`, TCP | gimbal IP'si varsayılan 192.168.144.25; Jetson aynı alt ağda olmalı (ör. 192.168.144.20) |
| Siyi (alt akış) | `rtsp://192.168.144.25:8554/video2` | düşük çözünürlük, 4G için uygun |
| Herelink / IP kamera | RTSP adresi + kullanıcı/parola | parola şifreli saklanır, arayüze dönmez |
| Gimbal RTP yayını (ör. QGC tarzı UDP 5600) | RTP, port 5600, H.264, yük türü 96 | köprü UDP 5600'ü dinler; SDP gerekmez (üretilir) |
| Jetson CSI / USB kamera | şimdilik `kamera-dene --adres test` ile deneme; yayın için kamerayı RTSP sunucusu ile (ör. `gst-rtsp-server`) RTSP'ye çevirin | sitede bağlantı türü RTSP/RTP ile sınırlı |

**FPS**: "Kaynak FPS" (varsayılan) → yeniden kodlama yok (`ffmpeg -c copy`; Nano'da bile ~%2 CPU). 5/10/15… seçilirse ya da çözünürlük girilirse köprü
yeniden kodlar: Jetson'da `nvv4l2decoder → nvvidconv → videorate → nvv4l2h264enc` (donanım), diğer sistemlerde `libx264 ultrafast`. Bit hızı yalnız
yeniden kodlamada uygulanır (4G için 800–1500 kbit/sn, 10–15 FPS, 1280×720 önerilir).

**H.265**: çoğu tarayıcı (Chrome/Firefox masaüstü) MSE'de H.265 oynatamaz. Kamerada H.264 seçin; seçilemiyorsa conf'ta `h265 = yeniden_kodla`
(Jetson donanım kod çözücü/kodlayıcı ile H.264'e çevrilir). Desteklemeyen tarayıcı otomatik olarak 2 sn'de bir JPEG gösterir.

Deneme (sunucuya göndermeden): `hepgo-kopru kamera-dene --adres rtsp://192.168.144.25:8554/main.264 --sure 10 --cikti /tmp/deneme.mp4`
(conf'taki `[kamera.N]` için `--kamera N`; ffmpeg test görüntüsü: `--adres test`). Çıktı: init / anahtar parça / ara parça sayısı, kbit/sn, FPS.

İzleme: Kameralar sayfasında "Önizle" (MSE, gecikme sol altta), "Anlık görüntü" (tek JPEG — yayın gerekmez), dron detayında kamera kartı; saha
görevinin **Canlı Uçuş** ekranında sağ üstteki "Kameralar" paneli: görevde kullanılacak kamerayı seçin, gerekirse bu görev için başka köprü ve HUD dronunu
bağlayın; kamera yüzen pencerede açılır (başlıktan sürükle, köşe/kenardan oran korunarak boyutlandır, yerleşim kalıcı), **çift tık** ayrı tarayıcı
penceresi. Yeşil HUD yalnız göstergedir (yön, irtifa, hızlar, batarya, GPS, mod/ARM, konum, uçuş süresi, ufuk, gecikme).

## 5. Sorun giderme

| Belirti | Neden / çözüm |
|---|---|
| `hepgo-kopru durum` → servis `inactive`, günlükte "Köprü kodu yok/geçersiz" | `sudo hepgo-kopru eslestir <kod>`; kod yenilendiyse yenisini girin |
| sunucu `retry … 4409` | aynı köprü kodu başka cihazda açık (Windows uygulaması da açıksa kapatın) |
| `link error … could not open port /dev/ttyTHS1` | Nano'da `nvgetty` portu tutuyor: `sudo systemctl disable --now nvgetty` (ya da `install.sh --nvgetty-kapat`); izin: kullanıcı `dialout` grubunda mı (`id hepgo-kopru`) |
| port açık ama telemetri yok (`rx 0`) | TX/RX çapraz mı, GND bağlı mı, `SERIAL2_PROTOCOL=2`, baud her iki tarafta aynı mı (`SERIAL2_BAUD=921` ↔ `baud = 921600`) |
| Kameralar'da "Görüntü yeteneği yok" | köprü Windows uygulaması ya da conf `[goruntu] etkin = hayir`; Linux köprüsünde `etkin = evet` + servis yeniden başlatma |
| "Görüntü yok" / `kare_yok` | Jetson'dan kameraya erişim: `ping 192.168.144.25`, `ffprobe -rtsp_transport tcp rtsp://…`; UDP taşıma 4G/NAT'ta paket kaybeder → TCP |
| `Araç bulunamadı: ffmpeg` | `sudo apt install ffmpeg` (JetPack 4.6'da universe deposu açık olmalı) |
| yüksek gecikme | FPS "Kaynak" ve TCP; 4G'de alt akış ya da 10–15 FPS + 1000 kbit/sn; tarayıcıdaki gecikme göstergesi > 2,5 sn'de uca atlar |
| H.265 uyarısı | kamerada H.264 seçin ya da `h265 = yeniden_kodla` |
| Orin/JetPack 6'da `nvv4l2h264enc` yok (Orin Nano'da donanım kodlayıcı yoktur) | otomatik `libx264`'e düşer; ya da kaynağı kopyalanacak biçimde (Kaynak FPS, H.264) ayarlayın |
| journald'da parola | görünmez: RTSP adresleri `rtsp://kullanıcı:***@` olarak gizlenir |

Güvenlik: conf yalnız root ve servis kullanıcısınca okunur (köprü anahtarı); servis `NoNewPrivileges`, `ProtectSystem=full`, `ProtectHome` ile çalışır.
Köprü kodu sızarsa HEPGO › Dron Köprüleri › "Kodu yenile" (eski kod ve açık bağlantılar — telemetri ve görüntü — anında düşer).
