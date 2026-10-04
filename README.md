# Fabrika Yönetim Sistemi

GÖKKUBBE'nin CAYMAZ insansız uçağının 3D yazıcılarla parça parça üretimini takip eden web uygulaması.
Python (FastAPI) arka uç, SQLite veritabanı ve derleme gerektirmeyen bir web arayüzünden oluşur.

## Çalıştırma

```bash
./run.sh
```

İlk çalıştırmada `.venv` sanal ortamı kurulur. Sunucu varsayılan olarak `0.0.0.0:8000` adresinde açılır. Port değiştirmek için: `PORT=8080 ./run.sh`

### İlk giriş

Sistem yöneticisi, ilk açılışta `.env` dosyasındaki bilgilerle oluşturulur (`CAYMAZ_ADMIN_USERNAME`,
`CAYMAZ_ADMIN_PASSWORD`, `CAYMAZ_ADMIN_FULL_NAME`). Şifre veritabanına özetlenerek (PBKDF2) yazılır. İlk girişten
sonra şifreyi sağ üstteki menüden **Şifremi Değiştir** ile değiştirin. `.env` yalnızca ilk kurulumda okunur.

Diğer ayarlar (`.env` veya ortam değişkeni):

| Ayar | Varsayılan | Açıklama |
|---|---|---|
| `CAYMAZ_COMPANY_NAME` | GÖKKUBBE Teknoloji | Alt bilgide görünen firma adı |
| `CAYMAZ_DATA_DIR` | `data/` | Veritabanı ve yüklenen dosyalar |
| `CAYMAZ_SESSION_HOURS` | 12 | Oturum süresi |
| `CAYMAZ_PRINTER_POLL_SECONDS` | 30 | Yazıcı durum okuma aralığı |

## Çok firmalı kullanım

Her firma aynı kodla **ayrı bir süreç** olarak çalışır; veritabanı, yüklenen dosyalar, imza anahtarı ve
kullanıcılar tamamen ayrıdır (bir firmanın verisi diğerinde görünmez).

| Firma | Adres | Yerel ağ | Servis | Veri |
|---|---|---|---|---|
| GÖKKUBBE Teknoloji | caymaz.app | :8080 | `caymaz` | `data/` + `.env` |
| Türkbey Teknoloji A.Ş. | turkbey.app | :8081 | `caymaz-turkbey` | `tenants/turkbey/{.env,data,brand}` |

Firma ayarları servis ortamından gelir: `CAYMAZ_ENV_FILE` (firma .env: ilk yönetici, firma adı, `CAYMAZ_LOCAL_URL`),
`CAYMAZ_DATA_DIR`, `CAYMAZ_BRAND_DIR` (`img/logo.png` başlık, `img/logo-login.png` giriş, `img/logo-mark.png`,
`icons/*` uygulama simgeleri; olmayan dosya için varsayılan kullanılır). Yeni firmada yedek parça başlangıç
stoğu `CAYMAZ_SEED_SPARE_STOCK=0` ile sıfırdan başlar. Alan adı `~/.cloudflared/config.yml` ingress'ine
eklenir ve Cloudflare DNS'te tünele CNAME verilir. Gece yedeği (`backup.sh`) tüm `tenants/*/data` klasörlerini de yedekler.
Kod güncellemesinden sonra iki servis de yeniden başlatılır:
`systemctl --user restart caymaz caymaz-turkbey`.

## Sürekli çalışan sunucu

Bu makinede uygulama, kullanıcı systemd servisi olarak **8080** portunda sürekli çalışır (8000 portunu başka bir
uygulama kullanıyor). Makine yeniden başlasa da kendiliğinden açılır.

```bash
systemctl --user status caymaz      # durum
systemctl --user restart caymaz     # kod değişikliğinden sonra yeniden başlat
journalctl --user -u caymaz -f      # canlı log
```

Yerel ağdan adres: `http://192.168.1.189:8080`

### İnternetten erişim: https://caymaz.app

Alan adı (`caymaz.app`, `www.caymaz.app`) Cloudflare'de kayıtlıdır. `caymaz-tunnel-app` Docker konteyneri
Cloudflare'in adlandırılmış tüneli `caymaz`'ı çalıştırır (`--restart unless-stopped`, makine açılınca kendiliğinden
başlar); modemde port açılmaz, HTTPS sertifikasını Cloudflare verir. Tünel ayarları ve kimlik dosyaları
`~/.cloudflared/` altındadır (`config.yml`, `<tünel-id>.json`, `cert.pem`; gizli tutulmalıdır).

```bash
docker logs --tail 20 caymaz-tunnel-app   # bağlantı durumu ("Registered tunnel connection")
docker restart caymaz-tunnel-app
```

## Modüller ve yetkiler

Yetki matrisi (2026-09-25). Her rol yalnızca işaretli modüllere girer; Sistem Yöneticisi tüm modüllere girer.
Birden fazla rolü olan kullanıcı, rollerinin gördüğü modüllerin birleşimini görür.

| Modül | R1 Sis. Yön. | R2 Depo Yön. | R3 Üretim Yön. | R4 Üretim Sor. | R5 Yazıcı Bakım | R6 Saha Sor. | R7 Saha Pers. | R8 Şoför | R9 Pilot | R10 Montaj Pers. | R11 Elektronik Pers. | R12 İdari Pers. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 Yönetim | ✓ | | | | | | | | | | | |
| M2 Üretim Yönetimi | ✓ | | ✓ | ✓ | | | | | | ✓ | ✓ | |
| M3 Sipariş Yönetimi | ✓ | | ✓ | | | | | | | | | |
| M4 Depo Yönetimi | ✓ | ✓ | | | | | | | | | | |
| M5 Stok Yönetimi | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | | ✓ | | | |
| M6 Saha Yönetimi | ✓ | | | | | ✓ | ✓ | ✓ | ✓ | | | |
| M7 Yazıcı Yönetimi | ✓ | | ✓ | ✓ | ✓ | | | | | | | |
| M8 Ürün Yönetimi | ✓ | | | | | | | | | | | |
| M9 Araçlar | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| M10 Kullanıcı Yönetimi | ✓ | | | | | | | | | | | |
| M11 Firma Yönetimi | ✓ | | | | | | | | | | | ✓ |
| M12 Evrak Yönetimi | ✓ | | | | | | | | | | | ✓ |

Saha Yönetimi'nde görev açma/yönetme Saha Sorumlusu ve Sistem Yöneticisi'ndedir; diğer saha rolleri görüntüler.

Kullanıcı silme (Kullanıcı Yönetimi → kullanıcı → Kullanıcıyı Sil): iş kaydı olmayan kullanıcı tamamen silinir;
üretim/depo/saha kayıtlarında adı geçen kullanıcı arşivlenir (`users.deleted_at`, giriş kapanır, rolleri silinir,
kullanıcı adı `...#silindi-<id>` olur ve yeniden kullanılabilir; geçmiş kayıtlarda adı görünür). Kendi hesabınız
ve son sistem yöneticisi silinemez.
Yetkiler `app/auth.py` içindeki `MODULE_ROLES`'dadır ve `tests/test_permissions.py` ile doğrulanır.
Ana sayfaya yeni modül düğmesi eklemek için `static/js/app.js` içindeki `MODULES` listesine satır eklenir.

## Üretim akışı

1. **Sipariş** açılır; her sipariş bir CAYMAZ uçağıdır ve katalogdaki 60 parçanın tamamını içerir.
2. **Üretim** ekranında siparişin uçak haritasında parçaya tıklanır:
   - Üretilmemiş / hatalı parça (beyaz / açık kırmızı) → yazıcı seçilir, parça açık maviye döner.
   - Üretimdeki parça → geçen süre görünür; **Üretim Tamamlandı** (teslim alan depocu seçilir) veya
     **Hata Verdi** (hata kodu, açıklama, kamera ile fotoğraf).
   - Depodaki / montajdaki parça → işlem geçmişi görünür.
3. **Depo** teslim edilen parçaları onaylar; parça açık sarı olur.
4. Tüm parçalar onaylanınca hepsi otomatik olarak **montaja** (açık yeşil) alınır.
5. **Montaj** üç bölümde yapılır: sol kanat, sağ kanat, orta gövde (bölümler parçaların tarafına göre:
   `app/plane.py` → `ASSEMBLY_SECTIONS`). Montajdaki uçakta parçalar tıklanmaz; bölümler bütün olarak sarı
   çerçeveyle çizilir. Bölüme tıklanınca montajda çalışan en az 2 **Montaj Personeli** ve zaman seçilir,
   bölüm yeşil çerçeveye döner.
   **Elektronik parçalar**: elektronik kat (`EK`, çizimin sağ üstünde; şekli şimdilik kare) ve K04 kapağı
   (`app/plane.py` → `ELECTRONICS_PARTS`). Diğer parçalar gibi üretilip depoya girerler; depoya alınmadan sipariş
   Depo/Montaj olmaz. Montaja alınırken depoda kalırlar; her birine tıklanınca "Elektronik komponentler monte
   edildi mi?" sorulur, en az 1 **Elektronik Personeli** seçilir (adım: `ELEKTRONIK_<kod>`). İkisinin de
   elektronik montajı bitmeden uçak kalibrasyona geçmez.
   **Bölüm bölüm montaj**: bir bölümün tüm parçaları depoya girip onaylanınca, siparişin diğer parçaları henüz
   basılırken de o bölüm monte edilebilir (örn. gövde basılırken kanat). Sipariş ekranında uçak üç bölüm ayrık
   çizilir; montaja hazır bölüm sarı, montajı biten yeşil çerçeveli ve parçaları siliktir; bölüme tıklanınca
   montaj penceresi açılır. Montajı biten bölümün parçaları "Montajda" olur. (`production.section_parts`)
   **Kapaklar** (`catalogs.cover_parts`: kapak grubu, K04 hariç) bölümlere sayılmaz; en son takılır.
   **Birleştirme montajı**: bölümler ve elektronik montajlar bitince kanatlar ve elektronik parçalar gövdeye
   takılır (2 maddelik kontrol listesi, en az 2 montaj personeli; adım `BIRLESTIRME`). Kapaklar basılırken de
   yapılabilir.
   **Kapak montajı**: birleştirmeden sonra, tüm kapaklar depoda iken (en az 1 montaj personeli; adım `KAPAK`).
6. Kapak montajı bitince uçak tek parça görünür ve **Kalibrasyon**'a geçer: kontrol listesi (elektronik kat, kumpas
   kalibrasyonu, CG, motor testi, uçuşa hazır) tamamen işaretlenmeli, en az 2 montaj personeli seçilmeli.
   **Sahada Montaj**: montaj aşamasındaki uçak saha görevine götürülebilir; görev başlayınca sipariş
   `SAHADA_MONTAJ` olur ve montaj adımları sahada (Üretim ekranından) sürdürülür. Görev biterken montajı
   tamamlanmamışsa `MONTAJ`'a döner.
7. Kalibrasyondan sonra uçak **saha deposu onayı** için depocuya düşer (Depo → Saha Deposu Onayı). Depocu
   onaylayınca sipariş **saha deposuna** girer. **Kuyruk numarası** (`CYZ-0001`, V2 için `CYZ2-0001`: ürün öneki +
   4 hane) montaj bitip uçak kalibrasyona geçerken atanır (`production.assign_queue_no`); ekranda büyük gösterilir,
   uçağın metal etiketine yazılır ve bir daha değişmez. Numarası olmayan montajı bitmiş uçaklara açılışta atanır.
   Adımlar `assembly_steps` / `assembly_staff` tablolarında tutulur.
8. **Saha görevi** yalnızca saha deposundaki bir veya birden fazla uçakla açılır (saha sorumlusu, şoför, personel, görev yeri):
   Başlangıç → Görevde → Görev Tamamlandı / Başarısız → Rapor Tamamlandı. Görev detayında üç alt modül vardır:
   - **Uçuş Yönetimi:** her uçak bir uçuştur; fırlatma sistemi (Araç Üstü / Fırlatma Rampası), uçuş logu ve
     sınırsız sayıda/boyutta uçuş videosu (parça parça yüklenir, tarayıcıda izlenir). Görev bitmiş ve tüm uçuşların
     raporu hazırsa görev Rapor Tamamlandı olur.
   - **Masraf Yönetimi:** tarih, kategori, tutar, açıklama, fiş.
   - **Yol Yönetimi:** görev yeri ve göreve giden araçlar (`field_task_vehicles`; birden fazla araç, her birinin
     şoförü ve başlangıç/bitiş km'si). Araçları saha yöneticisi ekler; her şoför kendi aracının km'sini girer.
     Yeni görevde şoför seçilmez, şoförler araçlarla birlikte eklenir. Görev yerleri ve araç listesi ayrı sayfada yönetilir.
   Görev formu (imzalı) yazdırılabilir.

## Arayüz dosyalarının önbelleği

`/` sayfası JS/CSS'i `/sv/<sürüm>/...` adresinden yükler (`app/main.py`); sürüm dosyaların değişiklik
zamanlarından her istekte hesaplanır. Arayüz dosyası değişince adres değişir, tarayıcı ve Cloudflare eski
sürümü gösteremez; statik değişiklik için sunucuyu yeniden başlatmak gerekmez. `/static/...` yanıtları `no-cache`'dir.

## Saat dilimi

Makinenin saat dilimi UTC-3'tür; uygulama servisi `TZ=Europe/Istanbul` ile çalışır (systemd birimi), kayıtlar Türkiye
saatindedir. Gece yedeği de 03:00 Türkiye saatinde alınır. Tarih-saat seçici değeri saat dilimiyle gönderir.

## GÖVDE / KAPAK / ELEKTRONİK görünümü

Parça haritalarında (Üretim, Stok, Ürün) üç katman düğmesi vardır. GÖVDE'de kapaklar ve elektronik parçalar hiç
görünmez; KAPAK'ta kapaklar, ELEKTRONİK'te elektronik kat ve K04 etkindir, diğerleri silik ve tıklanamaz
(`layerToggle` → `renderPlane().setLayer`; parçanın katmanı `plane.py` → `layer_of`). Seçim kullanıcı tercihinde saklanır.

## İşlem zamanı

Kullanıcı işlemlerinde zaman otomatik yazılmaz; pencerede tarih-saat seçici (flatpickr, `static/vendor/flatpickr`,
Türkçe) vardır, varsayılan "şimdi"dir ve tarih serbestçe seçilir: parçayı üretime alma, depoya teslim, hata, depo onayı, montaj bölümü,
kalibrasyon, saha deposu onayı, saha görevini başlatma/bitirme. Sunucu yalnızca bir önceki işlemden önceki zamanı
reddeder (`db.pick_time`).

## Firma ve Evrak Yönetimi

- **Firma Yönetimi** (`app/routers/companies.py`): firma, logo, firma kişileri (sistem kullanıcısı değil) ve
  birden fazla adres (`company_addresses`: ad, açık adres, il/ilçe, not) ve toplantılar (adres seçimi + serbest yer,
  karşı taraftan firma kişileri, bizden kullanıcılar, diğer katılımcılar, tutanak). Firma detayında
  firmaya ya da kişilerine bağlı evraklar (görünürlük kurallarıyla) listelenir.
- **Evrak Yönetimi** (`app/routers/documents.py`): evrak/resim/video/ofis dosyaları parça parça yüklenir (`/api/uploads`,
  tür `documents`; video yalnızca yerel ağdan). Birden çok taranmış resim tek PDF'te birleştirilebilir.
  OCR (`app/document_ocr.py`) arka planda: PDF metin katmanı varsa `pdftotext`, yoksa 300 dpi sayfa resmi + Tesseract
  (`tur+eng`); resimler Tesseract; .txt/.docx doğrudan. Arama SQLite FTS5 (`documents_fts`) üzerinde, Türkçe harfler
  sadeleştirilerek (`fold`: İ/ı/i, ş/s, ğ/g, ü/u, ö/o, ç/c); önce cümle, bulunmazsa kelimelerin hepsi aranır.
- **Görünürlük:** yükleyen seçer: Herkes (modüle girebilen herkes) / Seçili roller / Yalnızca ben. Sistem yöneticisi
  rolü seçilmedikçe kısıtlı evrakı göremez; kural liste, arama, firma detayı ve dosya indirmede (`FILE_GUARDS`) uygulanır.
- **İmza talepleri** (`app/routers/signatures.py`, `#/sign`): evrağı görebilen kişi herhangi bir kullanıcıya imza
  talebi gönderir; talep bildirimler panelinde bekler. İmzalayan (evrak kısıtlı ya da modülü olmasa bile) yalnızca o
  evrağı görür; İmzala → dosyanın SHA-256 özeti + talep/evrak/imzalayan/zaman sunucu anahtarıyla HMAC-SHA256
  (`data/signing.key`, gece yedeğine dahil); Reddet → açıklama zorunlu; Vazgeç → işlem yok. "İmzayı doğrula" dosyayı
  yeniden özetler: dosya değiştiyse ya da kayıt oynandıysa geçersiz der.
- **Tesseract + Poppler:** sistem paketi değil; Ubuntu paketleri `vendor/ocr/root` altına açıldı (yönetici yetkisi gerekmez):
  `apt-get download tesseract-ocr libtesseract5 liblept5 tesseract-ocr-tur tesseract-ocr-eng tesseract-ocr-osd
  poppler-utils libpoppler134 libgif7 libwebpmux3 libopenjp2-7 liblcms2-2` ve her paket için
  `dpkg -x <paket>.deb vendor/ocr/root`. Paketler sunucunun mimarisine göre indirilmeli (x86_64 sunucuya arm64 paketi
  çalışmaz); kütüphane klasörü (`usr/lib/<mimari>-linux-gnu`) otomatik seçilir. `pdftoppm`/`pdftotext`/`pdfinfo`
  önce `vendor/ocr/root/usr/bin`'de, yoksa sistemde aranır. Eksik kütüphane kontrolü:
  `LD_LIBRARY_PATH=vendor/ocr/root/usr/lib/x86_64-linux-gnu ldd vendor/ocr/root/usr/bin/{tesseract,pdftoppm}`.
- **Mikro / PDKS / NVR / yüz tanıma** merkez sunucuda değil, fabrikadaki ajanda çalışır (`agent/README.md`);
  sürücüleri `agent/requirements.txt` ile yalnız orada kurulur.

## Ses ve video evrakları: konuşma metni ve yüz tanıma

Evrak Yönetimi'ne ses kayıtları da yüklenir (mp3, wav, m4a, aac, ogg, opus, flac, wma, amr…; tür **Ses**).
Tümü bu sunucuda işlenir, hiçbir veri dışarı gönderilmez (`app/document_media.py`):

- **Konuşma → metin:** ses dosyası ve videonun sesi PyAV ile 16 kHz WAV'a çevrilir, whisper.cpp (GB10 ekran kartı,
  `vendor/whisper/whisper-cli`, model `vendor/models/ggml-large-v3-turbo-q8_0.bin`, dil otomatik) ile metne dökülür.
  Metin `[dd:ss] cümle` satırlarıyla `ocr_text`'e yazılır ve evrak aramasında bulunur; evrak sayfasında zamana
  tıklayınca kayıt o ana gider.
- **Videodaki kişiler:** saniyede bir kare (uzun videoda en çok 900 kare) alınır, OpenCV YuNet ile yüzler bulunur,
  SFace ile yüz izi çıkarılır; aynı kişinin yüzleri gruplanır (kosinüs ≥ 0,363) ve her grubun en net yüzü
  `document_faces`'e kaydedilir ("Tanımsız kişi"). Yüze tıklayınca firma kişisi ya da personel seçilir; firma kişisi
  evrağın kişilerine eklenir, personelin Rehber sayfasında evrak görünür. Elle tanımlanan yüzler sonraki videolarda
  benzerlikle (≥ 0,42) **otomatik önerilir**; yanlışsa değiştirilir / "Kişi değil" ile kaldırılır. Yüz görüntüleri
  evrağın görünürlüğüyle korunur, evrak silinince silinir.
- **Resimdeki kişiler:** yüklenen resimlerde de (metin okumayla birlikte) yüzler bulunur; her yüz ayrı kişi olarak
  "Resimdeki kişiler"de gösterilir, tanımlama ve otomatik öneri videodakiyle aynıdır.
- **Sesle yazdırma:** uygulamadaki her çok satırlı metin kutusunda (toplantı notu, not, açıklama…) mikrofon düğmesi
  vardır (`static/js/dictation.js`). Basınca kayıt başlar, yeniden basınca durur; kayıt `POST /api/system/dictate`
  ile aynı Whisper'da Türkçe düz metne çevrilip imlecin yerine yazılır (ses saklanmaz). Tarayıcılar mikrofona
  yalnızca güvenli bağlantıda izin verir: https://caymaz.app ya da https://turkbey.app (yerel http://192.168.1.189
  adresinde mikrofon çalışmaz). Bir kutuda istenmiyorsa `data-no-mic`.
- Kurulum: `pip install av opencv-python-headless numpy`; whisper.cpp `cmake -DGGML_CUDA=ON
  -DCMAKE_CUDA_ARCHITECTURES=121a-real` ile derlenip `vendor/whisper/`'a kopyalanır; modeller: opencv_zoo
  (YuNet 2023mar, SFace 2021dec) ve ggerganov/whisper.cpp (large-v3-turbo-q8_0).
- Kişisel veri: yüz izleri biyometrik veridir (KVKK özel nitelikli kişisel veri); aydınlatma ve açık rıza
  süreçleri kurum tarafından yürütülmelidir.

## Rehber, Notlar ve Takvim (Firma Yönetimi)

- **Rehber** (`#/companies/rehber`): firma kişileri ve sistem kullanıcıları; "Tüm kişiler / Firma kişileri /
  Kullanıcılar" ve firma filtresi, kart ya da liste görünümü, harf dizini, .vcf. Karta tıklayınca detay açılır.
- **Kişi / kullanıcı detayı** (`#/companies/rehber/person|user/<id>[/<sekme>]`): Evrak Yönetimi, Notlar,
  Toplantı Yönetimi, Takvim sekmeleri.
- **Firma detayı** (`#/companies/<id>[/<sekme>]`): üstte firma bilgileri; altta Kişiler, Adresler, Evrak Yönetimi,
  Notlar, Toplantı Yönetimi, Takvim sekmeleri. Firma notları ve takvimi kişilerden bağımsızdır.
- **Notlar** (`crm_notes`): konu (firma / kişi / kullanıcı) hakkında birden çok not; yalnızca yazan ya da Sistem
  Yöneticisi düzenler / siler.
- **Takvim** (`crm_events`, `crm_event_users`): aylık görünüm; **randevu** (başlangıç–bitiş, yer) ve **hatırlatma**
  (tek an, "tamamlandı" işaretlenir). Toplantılar takvimde salt okunur görünür. Bildirim zilinde "Takvim: bugün ve
  zamanı gelen": bugünkü randevular ve zamanı gelmiş, tamamlanmamış hatırlatmalar (oluşturana ve seçilen kişilere).
- Firma / kişi silinince notları ve takvim kayıtları da silinir; not ya da takvim kaydı olan kullanıcı arşivlenir.

## Uyarılar ve bildirimler

Üst çubukta iki simge vardır:

- **Uyarılar** (üçgen, `app/alerts.py`): herkese açık sistem uyarıları (yazıcı hatası, yazıcı–sistem uyumsuzlukları).
  Rozet uyarı türü sayısını gösterir.
- **Bildirimler** (zil, `app/notifications.py`): yalnızca kullanıcıyı ilgilendirenler; rozet bekleyen kayıt sayısıdır.
  Her tür `NOTIFICATIONS` listesinde bir kayıttır (`roles` kimin göreceğini, `fn(conn, user)` kayıtları verir).
  Türler (bildirimler yalnızca okur, veri değiştirmez):

  | Tür | Kim görür |
  |---|---|
  | Depo onayı bekleyen parça | Depo Yöneticisi |
  | Hata veren parça | Üretim Yöneticisi, Üretim Sorumlusu |
  | Saha deposu onayı bekleyen uçak | Depo Yöneticisi |
  | Montajı bekleyen uçak (eksik bölümlerle) | Üretim Yöneticisi, Üretim Sorumlusu, Montaj Personeli |
  | Kalibrasyonu bekleyen uçak | Üretim Yöneticisi, Üretim Sorumlusu, Montaj Personeli |
  | Bitiş tarihi geçmiş sipariş | Üretim Yöneticisi |
  | Bakım gerektiren yazıcı (hata / çevrimdışı) | Yazıcı Bakım Sorumlusu |
  | Raporu eksik uçuş (bitmiş görevde) | Görevin saha sorumlusu; görevli pilot |
  | Yol bilgisi girilmemiş görev | Görevin şoförü |
  | Size atanan saha görevi (başlamamış) | Görevdeki herkes (görevi açan hariç) |

İkisi de 5 saniyede bir güncellenir.

## Güvenlik ve yedek

- Giriş koruması: aynı kullanıcı adına 5, aynı IP'den 20 hatalı denemeden sonra giriş 15 dakika kilitlenir.
- Web terminal (Araçlar › Terminal): sunucuda gerçek bir kabuk açtığı için varsayılan **kapalı**; yalnız fabrikadaki
  yerel kurulumda `.env` içinde `CAYMAZ_CONSOLE=1` ile açılır ve yalnız MASTER kullanabilir. Çok firmalı sunucuda açılmaz
  (kabuk diğer firmaların `.env`/veritabanına erişebilir); Veilox kurulumu `CAYMAZ_CONSOLE=0` yazar.
- Gece yedeği: `backup.sh`, systemd zamanlayıcısı `caymaz-backup.timer` ile her gece 03:00'te çalışır;
  `data/backups/nightly/` altına veritabanı ve yüklenen dosyaların anlık görüntüsü alınır, 30 gün saklanır.

## Saha Yönetimi görünümleri, kullanım durumu ve HURDA

- Saha Yönetimi'nde iki görünüm: **Saha Görevi** (görev listesi) ve **Uçuş Yönetimi** (`#/field/flights`): saha
  görevlerine eklenmiş uçaklar; varsayılan "Uçuşa hazır" (montajı bitmiş, saha deposunda, görev başlangıç / görevde),
  ayrıca "Uçmuş" ve "Tümü". Tıklayınca uçuş detayı açılır.
- Mamul **kullanım durumu** (`products.usage_type`): `TEK` tek kullanımlık (CAYMAZ, CAYMAZ V2) | `COKLU` çoklu kullanım;
  Ürün Yönetimi'nden seçilir.
- **HURDA** (sipariş durumu): tek kullanımlık uçağın uçuş logu havada kalma gösterince otomatik; log yoksa uçuş
  detayından saha sorumlusu "Uçtu — Hurdaya Ayır" (yanlışsa "Hurdadan Geri Al"). HURDA kapanmış sipariş sayılır.
- Sahada montajı biten uçak (Sahada Montaj → birleştirme → kapak montajı → Kalibrasyon): bulunduğu saha görevi hâlâ
  "Başlangıç"taysa göreve başlanmış sayılır; görev kendiliğinden "Görevde" olur (başlama = son montaj adımının zamanı)
  ve log / video / resim yükleme açılır (`production.start_field_task_for`).
- Saha görevine uçak seçimi: açık görevdeki uçak gelmez; tek kullanımlık uçak bir kez sahaya gittiyse yeniden
  seçilemez; çoklu kullanım uçağı görev bitince yeniden seçilebilir.

## Kritik uyarı: kayıtsız baskı yarıda kesildi

Yazıcı yoklaması (`printer_driver.detect_unrecorded_abort`), sistemde parça atanmamış bir yazıcı yazdırırken /
duraklatılmışken baskı bitmeden boşa geçerse (iptal) ya da hata verirse `printer_incidents`'e olay yazar. Uyarılar'da
en üstte, yanıp sönen **KRİTİK** uyarıdır (dosya, hangi parçanın dosyası, kesildiği ilerleme, başlama / kesilme);
yazıcı, üretim ya da yönetim yetkisi olan biri "Gördüm" diyene kadar kalır. Bağlantı kopması sayılmaz.

## Uçuş detayı (Saha Yönetimi → görev → uçak)

Görevdeki uçağa tıklanınca: uçak montajı bitmemişse (Montaj / Sahada montaj) Üretim Yönetimi'ndeki uçak detayına,
bitmişse **uçuş detayına** (`#/field/flight/<id>[/<sekme>]`, `static/js/modules/flight.js`) gidilir. Üstte uçak
(kuyruk no, sipariş, ürün, durum, fırlatma sistemi, havada kalma) ve saha görevi (görev, yer, sorumlu, pilot, personel,
araçlar, zamanlar) bilgileri; altında uçuş logu (.bin / .log, yalnızca yerel ağdan) yükleme; altta sekmeler:
**Uçuş Raporu** (yazdırılabilir), **3B Uçuş İzleme** (Cesium, sayfa içinde), **Uçuş Notları** (`flight_notes`; tür:
Görüş, İyileştirme talebi, Arıza / sorun, Gözlem, Diğer; Saha Yönetimi'ne giren herkes ekler, yazan ya da saha
sorumlusu düzenler / siler) ve **Video ve Resimler** (`flight_videos.kind` VIDEO | RESIM; birden çok dosya; videolar
yalnızca yerel ağdan, resimler her yerden). Yükleme saha sorumlusu ve pilot içindir, görev başladıktan sonra.

## Üretim Planlayıcı (Araçlar)

`#/tools/planner` (`app/planner.py`, `static/js/modules/planner.js`): mamul ve adet seçilir; yazıcıların anlık durumuna
göre (boştakiler hemen; baskıdakiler kalan süreden — dosyanın parça baskı süresi × kalan ilerleme — sonra;
çevrimdışı / hatalı yazıcılar hariç) her parçanın hangi yazıcıda, ne zaman basılacağı hesaplanır ve **Gantt şeması**
ile gösterilir. Baskılar arası hazırlık süresi girilir (varsayılan 15 dk). Öncelik: "uçak uçak" (ilk uçak en erken
biter) ya da "toplam süre en kısa". Çıktı: Gantt, "Şimdi yükleyin" listesi (yazıcı → dosya), uçakların tahmini
bitişi ve yazıcı yazıcı sıralı yükleme listesi (işaretlenebilir kutucuklu). "Yazıcı durumu: Hepsi boş" seçilirse
anlık durum yok sayılır, sistemdeki tüm yazıcılar boşmuş gibi (varsayımsal) planlanır. "Yazdır / PDF" A4 çıktı verir:
özet, Gantt, yazıcı başına kutucuklu dosya sırası (ekranda işaretlenenler işaretli basılır) ve imza alanları.
Salt okunurdur: sipariş açmaz, yazıcıya iş göndermez.

## Raporlar

`#/reports` (`app/reports.py`, `app/routers/reports.py`, `static/js/modules/reports.js`; grafikler Chart.js —
`static/vendor/chartjs`, MIT). Her rapor bir modüle bağlıdır; kullanıcı yalnızca girebildiği modüllerin raporlarını
görür (Güvenlik rolü Raporlar'ı görmez). Liste: düğmeler (üstte rapor adı, altta modül), kart / liste görünümü, modül
filtresi. Rapor: dönem (7 / 30 gün, bu ay, geçen ay, 90 gün, bu yıl, özel; en fazla 1 yıl); **Grafik** (göstergeler,
otomatik çıkarımlar, grafikler, gün × saat ısı haritası) ve **Baskı** (göstergeler, tablolar) görünümü; ikisi de antetli
yazdırılır (logo, rapor adı, dönem, rapor tarihi, hazırlayan; grafikler açık temada resim olarak). Görüntülenen rapor
işlem kaydına yazılır. Yeni rapor: `@report(anahtar, modül, başlık, açıklama)` ile bir fonksiyon eklemek yeterli.

Raporlar: Üretim Performansı, Üretim Hataları Analizi (Pareto), Baskı Süresi Sapması, Yazıcıda Bekleme, Montaj
Performansı, Üretim Kapasite ve Teslim Tahmini · Sipariş Durum, Sipariş Çevrim Süreleri · Depo Onay Performansı ·
Yedek Parça Stok ve Kapasite · Yazıcı Kullanım ve Verimlilik · Uçuş Performansı, Saha Görevleri ve Masraflar · Firma
İlişki Karnesi · Evrak ve İmza · Misafir, Kargo · Araç Giriş / Çıkış Analizi, Kamera Yüz Tanıma ve Yoklama ·
Kullanıcı Aktivitesi, Personel Performans Karnesi · Ürün Parça ve Baskı Listesi.

## Sipariş detayı (Sipariş Yönetimi)

`#/orders/<id>` (`production.order_timeline`, `GET /api/orders/<id>/timeline`): solda sipariş bilgileri, sağda
birbirine bağlı aşama kartları (tamamlandı / sürüyor / bekliyor; birden çok aşama aynı anda sürebilir):
Sipariş → Üretim → Depo onayı → Montaj (bölümler, elektronik, birleştirme, kapak; kişilerle) → Kalibrasyon → Saha
deposu (kuyruk no) → Saha görevi → Uçuş (uçuş süresi, mesafe, irtifa, not ve video sayısı; "Uçuş detayı") → Hurda.
Yedek parça siparişi: Sipariş → Üretim → Depo onayı → Stoğa girdi. Her sipariş tek üretimdir (tek uçak / tek baskı);
API birden fazla adeti reddeder.

## Güvenlik ve Sekreterya

Roller: **Güvenlik** (yalnızca Güvenlik modülü; Araçlar dahil başka modül ve üretim uyarıları görünmez, ana sayfa
doğrudan Güvenlik'e gider) ve **Sekreter** (Sekreterya + Araçlar). Sistem Yöneticisi ikisini de görür.

- **Güvenlik** (`app/routers/security.py`, `static/js/modules/security.js`): gelen aracın plakası kaydedilir (plaka
  `34 ABC 123` biçimine getirilir; içerideki araç ikinci kez girilemez). Parktaki araçlar plaka kartı olarak görünür,
  karta tıklanınca "Çıkış yaptı". Giriş / çıkış kayıtları tarih ve plakaya göre süzülür, CSV indirilir.
- **Kameralar** (`app/cameras.py`, `app/routers/cameras.py`, `static/js/modules/cameras.js`): ONVIF kameralar ağda
  bulunur (WS-Discovery) ya da IP / akış adresiyle eklenir; akış adresi ONVIF GetStreamUri ile alınır. Kamera şifresi
  `data/camera.key` ile şifreli saklanır, API'den dönmez. Akış adresi yalnızca rtsp:// / http(s):// olabilir.
  İzleme duvarı 1 / 4 / 6 / 9 / 12 / 16'lı; düzen ve karelerdeki kameralar kullanıcıya göre sunucuda (`user_prefs`).
- **Kamera servisi** (`app/camera_service.py`; systemd `caymaz-cameras`, Türkbey için `caymaz-turkbey-cameras`):
  her kamerayı sürekli okur, izleme karesini `data/cameras/live/<id>.jpg` olarak yazar ve saniyede 2 kez yüz tanır
  (YuNet + SFace). Benzer yüzler bir grupta toplanır (`face_groups`); bir grup için aynı kamerada en fazla 20 sn'de bir
  görülme (`face_sightings`: yüz kırpığı ve yüzün görüldüğü anın tam karesi, `uploads/camfaces/`) saklanır.
- **Tanımlanamayan Kişiler** (`static/js/modules/faces.js`): kişiye atanmamış gruplar; gruba tıklanınca görülmeler ve
  tam kareler. "Kişiye Ata" ile gruptaki tüm yüzler bir kullanıcıya ya da firma personeline atanır (kişinin başka grubu
  varsa birleşir); sonraki görülmelerde o kişi tanınır. Aynı kişinin grupları birleştirilebilir, yanlış tespit silinir.
- **Sekreterya** (`app/routers/secretariat.py`, `static/js/modules/secretariat.js`): misafir kaydı (bir grup = bir kayıt,
  `MS-0001`). Detayda **Gelen Kişiler** (Rehber'de ara; bulunamazsa bir firmaya yeni kişi — Rehber'e de eklenir — ya
  da serbest giriş), **Gelen Araçlar** (güvenliğin kaydettiği parktaki araçlardan, birden fazla) ve **Görüşülecek
  Kişiler** (firma kullanıcıları; bildirim "Misafiriniz geldi"). **Kargolar**: kargo kaydı (ilgili kişi, kargo firması,
  takip no, kamerayla resim); ilgili kişiye bildirim "Kargonuz var".
- Kullanıcı menüsü: **Kargolarım** (bekleyen kargolar kart halinde, "Teslim Aldım") ve **Misafirlerim**.

## Kişisel pano (ana sayfa)
Ana sayfa herkesin kendine göre düzenlediği panodur (`app/dashboard.py`, `static/js/modules/dashboard.js`). "Panoyu Düzenle" ile kutucuk
eklenir / çıkarılır / taşınır, genişliği (⅓, ⅔, tam) değiştirilir; düzen kullanıcıya özel sunucuda saklanır (`user_prefs: dashboard`).
Kutucuklar: saat (dijital / analog), hava durumu (konum izni ya da şehir; Open-Meteo), duyurular, bildirimler, uyarılar, takvim,
kargolarım, misafirlerim, aramalarım ve yetkiye göre modül özetleri (üretim, yazıcı, depo, stok, saha, güvenlik, sekreterya, evrak, sistem),
14 günlük üretim grafiği, teslim tahmini, son siparişler. Kullanıcı yalnızca girebildiği modüllerin kutucuklarını görür.

## Duyurular
Yalnızca Sistem Yöneticisi yazar; herkes görür. Açılan duyuru okundu sayılır ve "Okunmamış" listesinden, bildirimden ve panodan düşer.
Yönetici her duyuruda okuyanları (zamanıyla) ve okumayanları görür. Önem (Bilgi / Önemli / Kritik), sabitleme ve son geçerlilik tarihi vardır.

## Yönetim → Sistem Durumu
`/api/admin/system`: sunucu (CPU, bellek, disk, GPU, açık kalma), servisler (systemd + Cloudflare tüneli), yedekleme, entegrasyonlar,
kullanıcı / oturum / rol özeti, şüpheli giriş denemeleri (24 saatte 5+), sunucu hata günlüğü, veritabanı ve dosya depolama, 14 günlük
kullanım ve veri büyümesi grafikleri, gün × saat yoğunluğu ve son işlemler. Canlı yazıcı / uçak paneli "Canlı Üretim" sekmesindedir.

Alt durum çubuğundaki bilgiler (aktif kullanıcı, disk, CPU/GPU, RAM) bilgisayarda üzerine gelince, tablette dokununca yukarı açılan
kapatılabilir ayrıntı kutucuğu açar (`/api/system/details`; sayfa ve dosya dökümü yalnızca yöneticiye).

## Sekreterya → Aramalar
Şirkete dışarıdan gelen telefonlar not edilir (arayan, telefon, firma, konu, mesaj), ilgili kullanıcıya bağlanır ve sonuç seçilir
(Bağlandı / Ulaşılamadı / Mesaj bırakıldı; "geri aranmak istiyor"). Arayan yazılırken firmalarda kayıtlı kişiler ve daha önce arayanlar
önerilir. İlgili kullanıcıya bildirim düşer; kullanıcı menüsündeki **Aramalarım**'da (kart / liste) görür, not ekler, geri dönünce
"Tamamlandı" der. Bağlanan ve geri dönüş istemeyen arama kendiliğinden tamamlanır. Tablolar: `phone_calls`, `phone_call_notes`.

## Ayarlar ve sesler
Kullanıcı menüsü → **Kişisel**: Takvim, İmza Talepleri, Kargolarım, Misafirlerim, Aramalarım tek modülde; alt modül başlığın en
sağındaki açılır listeden seçilir (bekleyen sayılarıyla), son açılan hatırlanır.

Kullanıcı menüsü → **Ayarlar** (`#/settings/<grup>`; solda gruplar, sağda ayrıntı; `static/js/modules/settings.js`,
`static/js/prefs.js`; `users.prefs.settings`, her cihazda aynı):
- **Arayüz:** tema (açık / koyu / sisteme göre; başlıktaki tema düğmesi buraya taşındı), yazı ve öğe boyutu, sıkı görünüm,
  hareketleri azalt, açılış sayfası.
- **Bildirimler:** sağ üst bildirim kutusu ve süresi, masaüstü bildirimi (sekme arka plandayken).
- **Sesler** (`static/js/sounds.js`): uyarı, kritik uyarı, bildirim, mesaj, kargo, arama, misafir, duyuru, imza, takvim için ayrı ses;
  30'dan fazla ses tarayıcıda Web Audio ile üretilir (dosya / lisans yok). Açık / kapalı, ses düzeyi, sessiz saatler.
- **Gizlilik:** çevrimiçi durumu gizle (yönetici hariç), okundu bilgisi gönderme (karşılıklı), mesaj almayı kapat.
- **Pano** varsayılana döndürme, **Hesap** (şifre değiştirme).

## Resimler: küçük kopya ve önbellek
`/api/files/<tür>/<ad>?w=<genişlik>` resmi sunucuda bir kez küçültür (64–1600 px, WebP) ve `data/cache/thumbs` altında saklar;
arayüz her yerde gerektiği boyutu ister (avatar 128/512, liste 256, kart 512, ayrıntı 1600), "aslını aç" bağlantıları orijinali verir.
Yüklenen dosyaların adı değişmediği için tarayıcı 30 gün önbelleğe alır. `data/cache` silinirse kopyalar yeniden üretilir.

## Bekleme ekranı, PIN ve bu cihazdaki hesaplar
- **Bekleme ekranı** (Ayarlar → Bekleme ekranı; `static/js/screensaver.js`): seçilen süre dokunulmazsa tam ekran animasyon
  (Dünya, Soft Matrix, Soft Ses Dalgası, Kuzey Işıkları, Parçacık Ağı, Yıldız Yolculuğu, Radar, Lav Lambası, Rastgele), saat ve tarih.
  "Çıkarken şifre sor" açıksa dokununca animasyonlu kilit kartı şifreyi (`/api/auth/unlock`) sorar; sayfa yenilense de kilit kalır;
  hatalı deneme sınırı aşılınca oturum kapanır.
- **Bu cihazdaki hesaplar** (`static/js/accounts.js`, tablo `trusted_devices`): şifreyle giriş yapılan cihaza jeton verilir; giriş
  ekranı bu cihazda giriş yapmış hesapları fotoğraf ve adıyla gösterir, kullanıcı adı yazılmaz. 90 gün kullanılmayan jeton silinir.
- **PIN** (Ayarlar → Hesap; `users.pin_hash`): 4 haneli PIN şifreyle açılır / değiştirilir / kapatılır; kolay PIN'ler kabul edilmez.
  PIN yalnızca daha önce şifreyle giriş yapılmış cihazda çalışır; hatalı PIN giriş denemesi sayılır, sınır aşılınca o cihazda şifre istenir.

## Stajer ve ilk girişte şifre değişikliği
- **Stajer** rolü (`auth.INTERN`) hiçbir modüle yetkili değildir; pano, Kişisel, mesajlaşma, duyurular gibi genel yapıyı kullanır.
  Yardımcı personel seçimlerinde (Montaj, Elektronik, Saha Personeli; `auth.HELPER_ROLES`) listenin sonunda "Stajer" etiketiyle
  çıkar ve seçilebilir; montaj / elektronik adımında yanında en az bir asıl personel olmalıdır. Diğer kullanıcılar gibi pasifleştirilir.
- **İlk girişte şifre değişikliği** (`users.must_change_password`): yöneticinin oluşturduğu ya da şifresini sıfırladığı kullanıcı ve
  şifresini hiç değiştirmemiş mevcut kullanıcılar, girişten sonra şifresini değiştirmeden sistemi kullanamaz (sunucu diğer istekleri
  428 ile reddeder). `CAYMAZ_FORCE_PASSWORD_CHANGE=0` ile kapatılır (testler kapalı çalışır).

## Kişisel → Toplantılar (şirket içi)
`app/routers/meetings.py`, `static/js/modules/meetings.js`; tablolar `team_meetings`, `team_meeting_invites`. Düzenleyen konu,
başlangıç / bitiş, yer ya da bağlantı, **talep notu** ve **hatırlatma süresi** (5 dk – 1 gün önce) ile toplantı oluşturup kullanıcıları
davet eder. Davet bildirime ("Toplantı daveti" sesiyle) ve Kişisel sayısına düşer; davetli **notuyla** Katılıyorum / Belki / Katılmıyorum
der. Toplantıdan seçilen süre önce düzenleyene ve katılmayacağını söylemeyenlere hatırlatma bildirimi ("Toplantı hatırlatması" sesi,
masaüstü bildirimi) çıkar. Zaman değişince yanıtlar sıfırlanır; iptal edilen toplantı listede iptal olarak görünür. Toplantılar kişisel
takvimde de görünür (katılmayacağım dediklerim hariç).

### Toplantı ekranı ve toplantı özeti
`app/routers/meeting_room.py`, `app/meeting_audio.py`, `static/js/modules/meeting_room.js`. Toplantı ekranını (`#/meetings/<id>/room`)
düzenleyen **Toplantıyı Başlat** ile açar; başlayınca herkes kendi notunu alır (otomatik kaydedilir), katılımcılar canlı görünür.
Düzenleyen **Kaydı Başlat / Durdur** ile kendi cihazının mikrofonundan kayıt alır; kayıt 5 sn'lik parçalarla sırayla sunucuya
eklenir (`uploads/meetings/<id>/`). **Toplantıyı Bitir** denince notlar kilitlenir, kayıt arka planda işlenir: WAV → Whisper
(zaman damgalı) → her parçanın ses kimliği (WeSpeaker ResNet34 ONNX, `vendor/models/wespeaker_resnet34_LM.onnx`, onnxruntime)
→ konuşmacılara kümeleme → kayıtlı ses profilleriyle (`voice_profiles`) eşleşenler otomatik tanınır, kalanlar "Tanımsız kişi N".
Özet (`#/meetings/<id>/summary`): konuşma süreleri, tanımsız kişiler (sesini dinle, kişiye ata → ses profili öğrenilir, aynı kişiye
atanan gruplar birleşir), kararlar / yapılacaklar / sorular (döküm ve notlardan anahtar ifadelerle), katılımcı notları ve konuşmacı
adlı tam döküm (satırı dinle); yazdırılabilir. Sessiz ya da Whisper'ın uydurduğu bilinen kalıplar dökümden elenir.

## Takvim görünümleri
Kişisel → Takvim ve firma / kişi takvimleri aynı bileşeni kullanır (`calendarPanel`, `static/js/modules/crm.js`): **Gün** ve
**Hafta** (saat ızgarası, çakışan kayıtlar yan yana, şu anki saat çizgisi, boş saate tıklayınca o saatte yeni kayıt), **Ay**,
**Yıl** (kaydı olan günler işaretli; güne tıklayınca gün görünümü) ve **Ajanda** (60 günlük liste). Seçilen görünüm hatırlanır.

## Kişisel → Mail (Gmail)
Her kullanıcı kendi Gmail / Google Workspace hesabını bağlar (`app/mail.py`, `app/routers/mail.py`, `static/js/modules/mail.js`):
- **Google ile bağlan (OAuth, kurumsal hesaplar):** Google Cloud'da "Internal" OAuth istemcisi (Web uygulaması), Gmail API açık,
  yetki `https://mail.google.com/`, dönüş adresi `<CAYMAZ_PUBLIC_URL>/api/mail/oauth/callback`. `.env`: `CAYMAZ_GOOGLE_CLIENT_ID`,
  `CAYMAZ_GOOGLE_CLIENT_SECRET`, `CAYMAZ_PUBLIC_URL`. Yenileme jetonu şifrelenmiş saklanır; IMAP/SMTP'ye XOAUTH2 ile girilir;
  hesap ayrılınca izin Google'da geri alınır.
- **Uygulama şifresi (kişisel Gmail):** 16 haneli uygulama şifresi (2 adımlı doğrulama gerekli; Workspace'te genelde kapalı).
Şifre şifrelenmiş saklanır, hiçbir yanıtta dönmez; postalar sunucuda saklanmaz, Gmail'den anlık okunur (IMAP), SMTP ile gönderilir.
Klasörler (Gelen, Yıldızlı, Önemli, Gönderilen, Taslak, Tüm Postalar, Spam, Çöp), Gmail sözdizimiyle arama, okundu / yıldız /
arşiv / sil / spam, yanıtla / tümünü yanıtla / ilet (orijinal eklerle), ek gönderme, imza. İçerik betiksiz güvenli kutuda gösterilir,
uzak resimler istenince yüklenir. Okunmamış sayısı bildirime, Kişisel sayısına ve sese ("E-posta") yansır.
**Ekler → Evrak Yönetimi** (`app/mail_import.py`): Evrak modülü olan kullanıcıda gelen kutusuna yeni düşen e-postaların ekleri
2 dakikada bir "Yalnızca ben" görünürlüğünde evrak olarak kaydedilir ve OCR'dan geçer (yönetici dahil başkası göremez; aynı ek iki
kez aktarılmaz). Hesap bağlanmadan önceki postalar için okuma ekranında "Ekleri Evraklara Kaydet" düğmesi. Mail ayarlarından kapatılabilir.

## Mesajlaşma
Kullanıcılar arası birebir canlı mesajlaşma (`app/routers/chat.py`, `static/js/chat.js`, tablo `chat_messages`). Alttaki "Aktif kullanıcı"
kutucuğundaki kişiye ya da başlıktaki mesaj düğmesinden bir kişiye tıklanınca sağ altta sohbet penceresi açılır; açıkken 2 sn'de bir
yenilenir. Metin, dosya / resim (ataç, sürükle-bırak, yapıştır; en çok 25 MB) ve bas-konuş sesli mesaj (mikrofona basılı tut, bırakınca
gider, yukarı kaydırınca iptal) gönderilir. Okundu bilgisi çift tik ile görünür. **Gruplar:** kullanıcı "+ Yeni grup" ile grup kurar
(kuran grup yöneticisidir; ad / üye değiştirir), üyeler grupça yazışır, gruptan ayrılabilir. **Tüm Şirket** kanalı (şirket logolu):
herkes üyedir, yalnızca Sistem Yöneticisi yazar; yazılan mesaj herkese düşer. Tablolar `chat_groups`, `chat_group_members`,
`chat_group_messages`, `chat_group_reads`. Mesaj kutusunda emoji paneli (son kullanılanlar üstte). Başlıktaki düğmenin sayısı okunmamış mesajı olan kişi
sayısıdır; liste kişiye göre gruplanır. Dosyaları yalnızca iki taraf açabilir.

## Yazıcı odası (Yazıcı Yönetimi → 3B Görünüm)

`static/js/modules/printers3d.js` (Three.js yerel kopya: `static/vendor/three/`, MIT), `app/printer_layout.py`.
Oda ortasında koridor; solda ve sağda iki katlı raflar. Her yazıcının yeri `printers.rack_side` (L / R),
`rack_level` (1 alt / 2 üst), `rack_slot` (1 = girişe en yakın). Yeri olmayan yazıcı (yeni eklenen) ilk boş yere
konur: ad numarasına göre sol alt → sol üst → sağ alt → sağ üst, katta en az 15 yer. Yazıcılar K2 Plus benzeri
modelle çizilir (cam kapak, tabla, kafa, üstte CFS); ön üstteki ışık şeridi durumu gösterir, basan yazıcıda kafa
hareket eder ve parça ilerlemeye göre yükselir; gövde durum rengine doğru kısık boyanır. Yazıcının adı, üstündeki
raf kirişinde (rafın önünde ve arkasında) isim plakasında yazar; plakanın solunda durum şeridi var. Tıklanan yazıcının
ayrıntısı yan panelde; "Yerini Değiştir" ile başka rafa taşınır (dolu rafta iki yazıcı yer değiştirir;
`PUT /api/printers/layout`, Yazıcı modülü gerekir). Görünümler: Giriş, Sol raf, Sağ raf, Genel.

## Üretim Hataları (Araçlar)

`#/tools/production-errors` (`app/routers/production_errors.py`, `static/js/modules/prod_errors.js`): üretimdeki
parça "Hata verdi" ile kapatılırken girilen hata kodu, açıklama ve resim (`part_events`, `event = 'HATA'`) sonradan
incelenir. Kart görünümünde hata resmi (yoksa "Resim yok"), liste görünümü, filtreler (tarih, yazıcı, parça, sipariş,
kaydeden, hata kodu, yalnızca resimli), en çok hata veren yazıcı / parça / hata kodu (tıklanınca filtreler), detay
penceresi ve CSV çıktısı. Serbest girilen hata kodları büyük / küçük harf farkı yok sayılarak gruplanır. Salt okunur;
Üretim, Yazıcı ya da Sipariş modülü olanlar görür.

## Uçuş logu analizi

Video ve uçuş logu yalnızca yerel ağdan (`CAYMAZ_LOCAL_URL`, varsayılan http://192.168.1.189:8080) yüklenir;
Cloudflare üzerinden gelen istek (`cf-ray` başlığı) reddedilir ve arayüz yerel adrese bağlantı gösterir.
Yükleme ekranında "Yüklemeyi İptal Et" yarım dosyayı sunucudan siler.

**3B oynatma (Cesium):** uçuş raporundaki "3B Oynat" (`#/tools/flight-log/<id>/3d`, `#/field/report/<id>/3d`).
Veri `/api/flight-logs/<id>/replay`: .bin'den 5 Hz konum/irtifa/roll-pitch-yaw/hız/gaz/batarya serisi
(`flightlog.replay`), ilk istekte üretilip log dosyasının yanına `.replay.json` olarak kaydedilir. CesiumJS
jsdelivr'den yalnızca bu sayfada yüklenir; uydu görüntüsü Esri World Imagery, arazi yok (irtifa eve göre).
Uçak modeli `static/models/caymaz.gltf` (burun glTF +Z; heading = yaw − 90°).

ArduPilot DataFlash logları (`.bin`) ve metin logları (`.log`) `app/flightlog.py` ile (pymavlink) çözümlenir.
Log hem Saha Yönetimi'nden (göreve bağlı) hem de **Araçlar → Uçuş Logu Analizi**'nden (bağımsız) yüklenebilir;
dosya en fazla 2 GB olabilir, analiz arka planda çalışır (`app/flight_analysis.py`).

Rapor logolu ve yazdırılabilirdir: özet göstergeler, uçuş bilgileri, uçuş izi haritası, otomatik değerlendirme
(titreşim, GPS, batarya, kontrol takibi, ERR hataları, uyarı mesajları), irtifa/hız/batarya/yönelim/titreşim/GPS/
rüzgâr/gaz grafikleri, uçuş modları, olaylar ve sistem mesajları. Değerlendirme eşikleri `_findings()` içindedir.

Sipariş durumu parçalardan türetilir: herhangi bir parçada hata varsa **Hata**, tüm parçalar depoda ama onay
bekleyen varsa **Depo**, hepsi onaylıysa **Montaj**, üretim başlamışsa **Üretim**, hiç başlamamışsa **Sipariş**.

## Ürünler

Her sipariş bir ürüne (ör. CAYMAZ, seri no CYZ-S1) bağlıdır; parça listesi, uçak haritası, stok ve kuyruk numarası
öneki ürünün şemasından gelir. Ürün kayıtları `products` tablosundadır; parça şemaları `app/catalogs.py`'de kayıtlıdır.
Yeni ürün tipi = yeni şema modülü + `SCHEMAS` kaydı + ürün kaydı (yazılım tarafında birlikte eklenir).
Ürün Yönetimi ekranından ad, seri no, açıklama ve aktiflik düzenlenir; siparişi olan ürünün kodu/öneki kilitlidir.

### CAYMAZ V2 (GÖKKUBBE, `app/plane_v2.py`, şema `caymaz-v2`, ürün kodu CYZ2, seri CYZ-S2)

V1'den farkı: K02, K03, KAPAK7 yok; 05/04/03 üzerine gelen büyük kapaklar K08 ve K09 eklendi; L18, R18, L15A, L15B,
R15A, R15B, L4, R4, 01, 03, 04, 05, 06, 07, 08 yeniden çizildi ve ayrı parça oldu (`-V2` kodlu parça yedekleri;
yeni çizimleri gelene kadar V1 şekliyle gösterilir, baskı dosyaları boş). 63 parça. Diğer parçalar V1 ile ortak
(aynı parça yedeği ve stok). Ürün ağacı `semis.create_v2` ile kurulur: CAYMAZ V2 → Sol Kanat V2 (SLK2), Sağ Kanat V2
(SGK2), Gövde V2 (GVD2), Elektronik V2 (ELK2) → parçalar; montaj sarfı kullanımı V1 ile aynı (KMH 1, BBK 68, KBK 6).
Yarı mamulün parçaları ağaçta şemadan (üyelik) bulunur; ortak parçanın sayfasında kullanıldığı yarı mamuller listelenir.

### Yarı mamul (ürün tipi `YARI_MAMUL`)

CAYMAZ'ın montajda birleştirilen dört ana yapısı, içindeki parçalarla birlikte (`app/semis.py`):
Sol Kanat (SLK, 22 parça), Sağ Kanat (SGK, 22), Gövde (GVD, 19) ve Elektronik (ELK: elektronik kat + K04).
Dördü birlikte CAYMAZ'ın 65 parçasını tam olarak böler. Ayrı sipariş verilmez; CAYMAZ siparişinin montaj
adımlarıyla üretilir. Montaj görünümünde uçak bu dört yapı olarak çizilir: Elektronik, uçağın yanında
çerçeveli ayrı bir blok olarak durur (elektronik kat ve altında K04; her birine ayrı elektronik montajı).

### Ürün ağacı ve sipariş ayarı

Ürünler `parent_id` ile ağaç oluşturur: **MAMUL** (CAYMAZ) → **YARI MAMUL** (4 yapı) → **YEDEK PARÇA**.
CAYMAZ'ın 65 parçasının her biri, ait olduğu yarı mamulün altında bir yedek parça ürünüdür (şema `part-<kod>`,
kodu parça kodu ve kilitli, başlangıç stoğu 0). Tek parça siparişi verilip basılabilir; depo onayında stoğa 1 girer.
Parça yedekleri CAYMAZ montajında stoktan düşmez (parçalar CAYMAZ siparişinde basılır). Montaj sarfı
yedek parçaların kullanımı yarı mamul başına tutulur (`product_spares`): KMH Gövde 1; BBK Sol Kanat 27,
Sağ Kanat 27, Gövde 14; KBK Sol Kanat 3, Sağ Kanat 3. CAYMAZ montajı bitince toplamları (1 / 68 / 6) düşer.
Adetler yedek parçanın detayından yarı mamul başına düzenlenir.
CAYMAZ detayında görünüm seçilir: Mamul (tek parça uçak), Yarı mamul (4 yapı; tıklayınca yapıya gider),
Yedek parça (tüm parçalar; tıklayınca parça yedeğine gider). Sağda ürün ağacı ve stoklar görünür.
Her üründe **Sipariş verilebilir** ayarı vardır (`products.orderable`); kapalı ürüne sipariş açılamaz.
Yarı mamullerde bu ayar her zaman kapalıdır.

### Baskı dosyası, süre ve yazıcı takibi

Her parça yedeğinde yazıcıya verilen baskı dosyası (`print_file`, gcode adı) ve baskı süresi (`print_minutes`)
tutulur; ilk değerler `app/print_files.py`'den gelir (Parca_Dosya_Eslestirme.xlsx) ve Ürün Yönetimi'nden
düzenlenir. Süreler parça ipuçlarında, yazıcı seçiminde ("yazıcıya verilecek dosya") ve ürün ağacındaki parçalarda
görünür. Parça sürelerinin toplamı (mamul / yarı mamul / sipariş için "toplam / kalan baskı süresi") gösterilmez:
yazıcılar paralel çalıştığından gerçekte yaşanmayan bir süredir; gerçekçi süre için Üretim Planlayıcı kullanılır.
Parçanın **net baskı süresi** (`order_parts.print_seconds`) yazıcının bildirdiği değerden (Moonraker `print_duration`,
duraklamalar hariç) kaydedilir; üretimdeki parça penceresinde büyük saat ve ince ilerleme çubuğu bunu gösterir.
Parça yedekleri (64) mamul siparişiyle üretildiği için "sipariş verilemez"; ayrı sipariş yalnızca KMH, BBK, KBK.

Yazıcı yoklaması (`printer_driver.track_jobs`) üretimdeki parça için yazıcının kendi bildirimini kaydeder:
`printer_started_at` (dosyası basılırken ilk görüldüğü an) ve `printer_done_at` (ardından "tamamlandı" dediği an).
**Yazıcıda bekleme** = `printer_done_at` → "Üretim Tamamlandı" (`finished_at`). Dosya adı parçanın dosyasıyla
uyuşmazsa kaydedilmez. Uyarılar dosya adını karşılaştırır (uzantı, klasör, büyük/küçük harf ve boşluk yok sayılır):
**Yazıcıda yanlış dosya basılıyor** (atanan parçanın dosyasından farklı) ve **Sistemde boş ama yazıcıda baskı**
(dosya adından hangi parça olduğu ya da "Tanımsız dosya" gösterilir).

### Yedek parça (ürün tipi `YEDEK_PARCA`)

Ürünler iki tiptedir: **MAMUL** (CAYMAZ) ve **YEDEK PARÇA** (çoklu basılan küçük parçalar, `app/spares.py`):

| Kod | Ad | Bir baskıda | CAYMAZ başına | Başlangıç stoğu |
|---|---|---|---|---|
| KMH | Kamera Holder | 1 | 1 | 1 |
| BBK | Büyük Bağlantı Klipsi | 12 | 68 | 183 |
| KBK | Küçük Bağlantı Klipsi | 12 | 6 | 38 |

- Yedek parça siparişi tek parçalı bir baskıdır; parça depo onayından geçince sipariş **TAMAMLANDI** olur ve
  "bir baskıda" adedi kadar stoğa girer (montaj aşaması yoktur).
- CAYMAZ montajı (kapak montajı dahil) tamamlanıp kalibrasyona geçince "CAYMAZ başına" adetler stoktan düşer.
- Stok = `spare_moves` hareketlerinin toplamı (başlangıç, üretim +, montaj −, sayım düzeltmesi ±).
  Sayım düzeltmesini Depo Yöneticisi / Ürün Yönetimi yapabilir.
- Stok bir uçağa yetmezse Üretim ve Depo Yöneticisine "Stoğu yetmeyen yedek parça" bildirimi gider.
- Yedek parça siparişleri sahaya götürülebilecek uçak listesinde görünmez.

### Parça G-code'ları ve 3B görünüm
`app/gcode.py`: parçaların G-code dosyaları ürüne bağlanır (`products.gcode_file`, adı `print_file` ile eşleşir; aynı diskteyse
sabit bağlantı). Dilimleyici bilgileri (süre, filament g/m, maliyet, katman, malzeme, sıcaklıklar, yazıcı) ve gömülü önizleme
`gcode_meta` / `gcode_thumb`'a; dış duvar takım yolu 3B dosyasına (`*.3d.bin`) ve ışıklı kart resmine (`*.3d.png`) çıkarılır.
Toplu içe aktarma: `.venv/bin/python -m app.gcode <klasör> …`. Arayüz (`static/js/gcode3d.js`, Three.js): Ürün Yönetimi parça
kartlarında 3B resim, parça detayında döndürülebilir 3B görünüm ve G-code kartı (indirme), Üretim'de parçanın üzerine gelince dönen
3B parça, Yazıcı Odası'nda basılan parça gerçek ölçüde tablada (yüzdesi kadarı dolu, üstü şeffaf), yazıcı penceresinde tek yazıcı ve
içindeki parça. G-code dosyaları Ürün, Üretim, Yazıcı, Stok ve Depo modüllerine açıktır.

## Parça kataloğu

Uçağın tüm parçaları ve koordinatları tek bir yerde, `app/plane.py` içindedir. Hem harita hem sipariş parçaları
buradan üretilir:

- `PART_CODES`: her ızgara hücresinin/çizim parçasının parça kodu (ör. sol kanat `L1`–`L20`, gövde `01`–`07`, burun `08`–`09`,
  elevonlar `FL1`/`FL2`/`FR1`/`FR2`).
- `SPANS`: birleşik kanat hücreleri (ör. `L9-10`).
- `SPLITS`: iki ayrı yazıcıda basılan, A/B'ye bölünen parçalar (ör. `L15A` / `L15B`).
- `COVERS`: kapaklar. Aynı `id`'yi taşıyan kapaklar tek baskıdır ve tek parça sayılır (ör. dört flap kapağı `FLAP-KAPAK`); gövde kapakları `K` + gövde parçası kodudur (`K01`, `K03`, `K05`, `K06`).

Katalog değişirse yeni açılan siparişler yeni parça listesiyle oluşur; mevcut siparişler olduğu gibi kalır.

## Yazıcılar

Creality K2 Plus yazıcıların durumu Moonraker API'den (`http://IP:7125`) okunur. Moonraker yoksa Creality'nin
yerel WebSocket'i (`ws://IP:9999`) denenir. **Otomatik Ekle**, makinenin bağlı olduğu yerel /24 ağında bu portları
tarar ve yazıcı olarak doğrulanan cihazları, ağdaki adlarıyla kalıcı olarak ekler.

## Veri ve yedekleme

Tüm veri `data/` klasöründedir: `caymaz.db` (SQLite) ve `uploads/` (kullanıcı resimleri, hata fotoğrafları, görev
raporları). Yedek için bu klasörü kopyalamak yeterlidir.

## Web uygulaması (PWA)

Uygulama Chrome, Edge ve Android'de "Uygulamayı yükle" ile, iPhone'da Safari → Paylaş → "Ana Ekrana Ekle" ile
kurulabilir (`static/manifest.webmanifest`, `static/sw.js`, ikonlar `static/icons/`). Tarayıcılar kurulumu yalnızca
HTTPS'te sunar: https://caymaz.app adresinden yüklenir; yerel ağdaki http://192.168.1.189:8080 adresinde
kurulum seçeneği çıkmaz.

## Harici bileşenler (depoda yok)
Boyutları nedeniyle `vendor/` altındaki şu klasörler depoya konmaz; sunucuda elle kurulur:
- `vendor/models/`: `face_detection_yunet_2023mar.onnx`, `face_recognition_sface_2021dec.onnx` (OpenCV Zoo, yüz tanıma),
  `ggml-large-v3-turbo-q8_0.bin` (whisper.cpp modeli, konuşma → metin)
- `vendor/whisper/whisper-cli` (whisper.cpp derlemesi)
- `vendor/ocr/` (Tesseract OCR, Türkçe dil verisiyle)
Bunlar yoksa sistem çalışır; yalnızca ilgili özellik (yüz tanıma, konuşma metni, OCR) kapalı görünür.
Canlı veriler (`data/`, `tenants/`) ve gizli ayarlar (`.env`) da depoda değildir.

## Test

```bash
.venv/bin/python -m tests.test_flow          # uçtan uca akış
.venv/bin/python -m tests.test_permissions   # yetki matrisi
.venv/bin/python -m tests.test_documents     # firma ve evrak
.venv/bin/python -m tests.test_spares        # yedek parça stoğu
.venv/bin/python -m tests.test_print_tracking   # baskı dosyası, uyarılar, yazıcıda bekleme
.venv/bin/python -m tests.test_crm           # rehber, notlar, takvim
.venv/bin/python -m tests.test_media         # ses → metin, videodaki kişiler
.venv/bin/python -m tests.test_v2            # CAYMAZ V2 şeması, ürün ağacı, sipariş
.venv/bin/python -m tests.test_flight_detail # uçuş detayı: notlar, video ve resimler
.venv/bin/python -m tests.test_planner       # üretim planlayıcı
.venv/bin/python -m tests.test_early_assembly   # bölüm bölüm montaj, kapak montajı
.venv/bin/python -m tests.test_order_company    # siparişin firması ve logosu
.venv/bin/python -m tests.test_production_errors  # üretim hataları aracı
.venv/bin/python -m tests.test_printer_layout     # yazıcı odası yerleşimi (3B görünüm)
.venv/bin/python -m tests.test_secretariat        # güvenlik (araç giriş/çıkış), sekreterya (misafir, kargo)
.venv/bin/python -m tests.test_cameras            # kameralar, yüz grupları, kişiye atama
.venv/bin/python -m tests.test_order_detail       # sipariş detayı (aşamalar), tek üretim
.venv/bin/python -m tests.test_reports            # raporlar (yapı, yetki, tarih)
.venv/bin/python -m tests.test_announcements      # duyurular (okundu, okuyanlar)
.venv/bin/python -m tests.test_calls              # aramalar, kişisel pano, sistem durumu
.venv/bin/python -m tests.test_chat               # mesajlaşma (dosya, ses, okundu, gruplama)
.venv/bin/python -m tests.test_chat_groups        # mesaj grupları, Tüm Şirket kanalı
.venv/bin/python -m tests.test_thumbs             # küçük resim ve önbellek
.venv/bin/python -m tests.test_unlock             # bekleme ekranı kilidi
.venv/bin/python -m tests.test_pin                # PIN ile giriş, bu cihazdaki hesaplar
.venv/bin/python -m tests.test_mail               # Gmail (sahte IMAP/SMTP), ekler → evrak
.venv/bin/python -m tests.test_meetings           # toplantı daveti, yanıt, hatırlatma
.venv/bin/python -m tests.test_meeting_room       # toplantı ekranı, ses kaydı, konuşmacı ayırma, özet
.venv/bin/python -m tests.test_intern             # stajer rolü
.venv/bin/python -m tests.test_force_password     # ilk girişte şifre değişikliği
.venv/bin/python -m tests.check_js           # arayüz JavaScript sözdizimi
```

Siparişten saha raporuna kadar tüm akışı, yetki kontrollerini ve logları geçici bir veritabanında sınar.
