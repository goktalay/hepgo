# Yüz ile giriş (Face ID tarzı) — sözleşme v1

Amaç: Kullanıcı, Kişisel Ayarlar › Hesap'ta (PIN ayarının hemen altında) yüzünü iPhone Face ID tarzı bir akışla tanıtır;
giriş ekranında, daha önce şifreyle giriş yaptığı **güvenilir cihazda** adına dokunup kameraya bakarak oturum açar.
Sistem yöneticisi Sistem Ayarları › Güvenlik'ten özelliği açıp kapatır, eşleşme eşiğini ve canlılık adımını belirler.

## 1. Teknik seçim (araştırma ve karar)

Adaylar: (a) MediaPipe FaceLandmarker (wasm + .task, ~6 MB) + ayrı gömme modeli (MobileFaceNet/ArcFace tfjs ya da
onnxruntime-web ~ 10 MB wasm + model); (b) face-api.js (tfjs, 128-d; eski, ~6 MB); (c) **sunucuda mevcut OpenCV Zoo
modelleri: YuNet 2023mar (tespit + 5 nokta, 233 KB) + SFace 2021dec (128-d gömme, 38,7 MB)** — kamera modülü
(`app/document_media.py`, `app/facecore.py`) zaten bunları kullanıyor; `vendor/models/` altında, Apache-2.0.

**Karar: (c) — gömme sunucuda.** Gerekçe:
- SFace 38,7 MB → tarayıcıya "≤ 10 MB toplam" sınırında taşınamaz; (a)/(b) ikinci bir model uzayı demek olurdu.
- İstemciden **gömme hiç kabul edilmez**: tarayıcı yalnızca ~480 px JPEG kare (≈ 30 KB) gönderir, sunucu tespit + gömme +
  baş pozunu hesaplar. "İstemci güvenilmez → sahte gömme enjeksiyonu" sınırı böylece ortadan kalkar; biyometrik şablon
  istemciye hiç dönmez.
- Tarayıcıya model indirme, wasm/`wasm-unsafe-eval`, worker-src, iOS Safari wasm bellek sorunu yok; CSP değişmedi.
  Yalnız `Permissions-Policy` başlığına `camera=(self), microphone=(self)` eklendi (`app/main.py`).
- Kamera erişimi `getUserMedia` (HTTPS zorunlu; yerel http geliştirmede `localhost` güvenli bağlam sayılır).
- Maliyet: kare başına sunucuda ~30–60 ms CPU (modeller önbellekte, tek kilit); istemci 380 ms'de bir kare → ~2,6 kare/sn.
- Dağıtık kurulum (`CAYMAZ_AGENT_MODE=remote`): kare fabrika yüz ajanında (`facebridge.rpc('embed_frame')`) işlenir.
  Model yoksa uçlar 503 "Yüz tanıma motoru bu sunucuda kurulu değil" döner; arayüz bölümü bunu açıkça yazar.

## 2. Güvenlik modeli

- **Saklama**: `user_face` (kullanıcı başına tek satır): `data` = `cameras.encrypt(JSON {embeddings:[[128 float]…], slots})`
  (nonce + HMAC-SHA256 etiket + SHA-256 akış şifresi; anahtar `DATA_DIR/cameras.key`, 0600), `model_ver`, `mode`
  (`face` | `face_pin`), `enabled`, `count`, `created_at`, `updated_at`. Ham kare/kırpık saklanmaz. Kullanıcı silinince CASCADE.
- **Eğitim** yalnız oturumlu kullanıcı, kendi hesabı için ve **mevcut şifreyle** (PIN ayarı kuralı). Eğitim oturumu bellekte
  10 dk; ilk kare kabaca önden olmalı (referans yüz + referans poz); başka bir kişinin yüzü (referansa kosinüs < 0,30)
  eklenmez (`other_face`). En az 5 yuva (merkez zorunlu), tam daire 9; ikinci tarama ile en çok 18 gömme.
- **Giriş** yalnız **güvenilir cihaz** jetonuyla (`trusted_devices`; PIN ile aynı kural). Akış: `challenge` (tek kullanımlık
  nonce, 60 sn, en çok 60 kare) → `verify` kareleri: (1) eşleme aşaması — kosinüs ≥ eşik (`face_threshold`/100, varsayılan
  0,45; SFace'te 0,363 "aynı kişi") ve kabaca önden bakış → referans poz; (2) **canlılık** — rastgele yöne (sol/sağ/yukarı)
  baş çevirme, referansa göre ≥ 0,18, eşleşme sürer (eşik −0,08); (3) kipe göre oturum çerezi ya da **PIN adımı**
  (`/pin`, `face_pin` kipi). Eşleşmeyen 10 kare → meydan okuma kapanır, `login_logs`'a başarısız giriş yazılır →
  kaba kuvvet kilidi PIN/şifreyle ortak (`policy.lockout_*`). Hız sınırı: kullanıcı ve IP başına dakikada 5 meydan okuma.
  Benzerlik skoru istemciye dönmez. Pasif kullanıcı / politika kapalı / yüz tanıtılmamış → 401/403.
- **Denetim** (`audit_logs`): "Yüz tanıtma kaydı oluşturdu", "…ikinci tarama ekledi", "Yüz ile giriş kipini değiştirdi",
  "Yüz verisini sildi", "Sisteme yüz ile giriş yaptı", "Sisteme yüz + PIN ile giriş yaptı", "Yüz ile giriş başarısız".
- **Sınırlar (dürüstçe)**: canlılık yalnızca baş çevirmedir — basılı/ekrandaki **fotoğrafı yener**, yüksek çözünürlüklü
  **video replay'ini yenmez**; IR/3B/ışık yanıtı gibi derin canlılık yoktur. Bu yüzden yüz girişi güvenilir cihaza bağlıdır
  ve isteğe bağlı "yüz + PIN" kipi vardır; güvenlik-hassas kurulumda yönetici `face_liveness` açık + kullanıcı `face_pin`
  önerilir. Kare TLS içinde taşınır (HTTPS). Sunucu gömmesi kamera modülüyle aynı uzaydadır ama `user_face` kayıtları
  kamera tanıma havuzuna (face_enroll) **yazılmaz** (amaç sınırlaması, KVKK).

## 3. Kişisel Ayarlar › Hesap › Yüz ile giriş (`static/js/modules/facesetup.js`)

- Bölüm (`faceSection`): durum (tanıtılmamış / "Yüz tanıtıldı · N açı · tarih"), **Giriş kipi** (Yalnız yüz / Yüz + PIN —
  PIN yoksa uyarır), düğmeler: *Yüzünüzü tanıtın* / *İkinci tarama* / *Yeniden tanıt* / *Yüz verisini sil* (şifre ile).
  Politika kapalı ya da motor yoksa bilgi notu.
- **Eğitim ekranı** (`openFaceSetup`): tam ekran koyu "sheet" (`.fe-sheet/.fe-card`; mobilde alttan kart, safe-area):
  1. Giriş kartı: Face ID simgesi, 3 adım, mevcut şifre, *Başla*.
  2. Tarama: ortada yuvarlak kamera (aynalı), çevresinde 360° halka — 8 yön × 9 ince çubuk (`facering.js`, SVG); dolan
     segment yeşile döner ve parlar; sıradaki segment mavi nefes alır; canlı baş pozu mavi nokta; yönlendirme metni
     ("Yüzünüzü dairenin içine alın" → "Başınızı yavaşça daire çizerek çevirin" → "Başınızı sağ üste doğru çevirin"…);
     alt ipucu (yaklaşın/uzaklaşın/ortalayın, yüz bulunamadı, farklı yüz); sayaç "N / 9 açı". Tam daire → kendiliğinden
     biter; ≥ 5 yuva ve 15 sn geçtiyse *Tamamla* düğmesi.
  3. Başarı: tik çizimi animasyonu, "Yüzünüz tanıtıldı · N açıdan kaydedildi", *İkinci taramayı yap (önerilir)* / *Bitti*.
- Erişilebilirlik: `role=dialog`, metin `aria-live`, Escape kapatır, `prefers-reduced-motion` ile animasyonlar kapanır.

## 4. Giriş ekranı (`static/js/accounts.js` + `static/js/face.js`)

- `/api/auth/devices` artık `has_face`, `face_mode` döner (politika açık + motor var + kayıt var). Hesap kartı etiketi
  "Yüz ile giriş" / "Yüz + PIN ile giriş"; dokununca kamera yoksa PIN/şifreye düşer.
- Yüz akışı: başlık + halka + "Kamera başlatılıyor…" → "Yüzünüzü dairenin içine alın" → eşleşince "Hafifçe sola/sağa/yukarı
  bakın" (segment vurgulu) → tik + "Hoş geldiniz" → oturum. `face_pin` kipinde "Yüz doğrulandı · PIN kodunuzu girin" →
  PIN klavyesi (`/api/auth/face/pin`). Başarısızlık/izin reddi/kamera yok/politika kapalı → açıklayıcı metin + 2,6 sn sonra
  PIN ya da şifre ekranına otomatik düşüş; *Yeniden dene*; PIN ve şifre ekranlarında "Yüz ile giriş yap" bağlantısı.
- Süre dolarsa (410) sessizce en çok 2 yeni meydan okuma alınır.
- Yüz akışı sürerken arka plandaki küre animasyonu durur (`window` olayı `hepgo:globe {pause}` → `globe.js`): kamera
  çözme + kare kodlama ana iş parçacığını paylaşır; yazılım GPU'lu/zayıf cihazlarda küre akışı tıkıyordu (Playwright
  SwiftShader'da gözlendi). Akış bitince küre sürer.
- Başarı/hata animasyonu, kamera kapatılmadan önce canvas'a dondurulan son kare üstünde oynar (siyah daire yerine yüz).

## 5. Sunucu

- `app/facelogin.py`: model önbelleği + kilit, `embed()` (`EMBED` testte değiştirilebilir), `segment_of` (aynalı; merkez
  < 0,14, yön ≥ 0,20), `pose_matches` (≥ 0,18), **referans poz kalibrasyonu** (`_head_pose` nötr sabitleri kişiye/kameraya
  göre ±0,15 kayar; eğitimde ve girişte ilk önden kare (|poz| < 0,35) referans alınır, sonraki pozlar referansa göre
  ölçülür — iPhone'un başlangıç duruşunu merkez sayması gibi), eğitim oturumları, meydan okumalar, hız sınırı,
  `save/record/status/delete/set_mode`, `threshold(policy)`.
- `app/routers/faceauth.py` (`/api/auth/face`): `GET status`; `POST enroll/start {password, append}` → `{enroll_id, slots,
  min_slots, ttl}`; `POST enroll/frame {enroll_id, jpg}` → `{found, small, box, w, h, yaw, pitch, slot, slots[], added,
  enough, complete, need_center, other_face}`; `POST enroll/finish {enroll_id, mode?}`; `POST enroll/cancel`;
  `PUT mode {mode}`; `POST delete {password}`; oturumsuz: `POST challenge {token}` → `{challenge, pose, mode, expires_in,
  max_frames}`; `POST verify {challenge, jpg}` → `{found, matched, stage, pose, done, ok, need_pin, frames_left, yaw, pitch,
  box, small}` (başarıda oturum çerezi); `POST pin {challenge, pin}`.
- Politika (`app/policy.py`): `face_enabled` (True), `face_threshold` (45; 30–80), `face_liveness` (True). Sistem Ayarları ›
  Güvenlik › "Yüz ile giriş" kartı (`sysconfig.js`).
- Ortam değişkenleri (yalnız test/özel durum): `CAYMAZ_FACE_POSES` (canlılık yönleri; varsayılan `left,right,up`),
  `CAYMAZ_FACE_MIN_SLOTS` (varsayılan 5, alt sınır 3).
- Tablo: `user_face` (`db.py` SCHEMA, `CREATE TABLE IF NOT EXISTS`).

## 6. Testler ve doğrulama

- `tests/test_face.py` (sahte gömme, model çalışmaz): eğitim yuvaları / need_center / other_face / yetersiz yuva / ikinci
  tarama / şifreli saklama, cihaz listesi, tek kullanımlık meydan okuma, eşleşmeme → 401 + login_logs, canlılık yanlış yön,
  başarılı oturum, audit, hız sınırı 5/dk, yüz + PIN, canlılık kapalı, politika kapalı → 403, pasif kullanıcı, silme, saf
  fonksiyonlar. `tests/test_face.mjs`: `facemath.js` (segment eşlemesi sunucuyla aynı değerler, canlılık, kosinüs, ilerleme,
  sıradaki segment, çerçeveleme ipuçları).
- Tarayıcı (Playwright, `--use-fake-device-for-media-stream --use-file-for-fake-video-capture=<y4m>`): Pillow ile çizilmiş
  **sentetik yüz** (YuNet 0,85 skorla algılar; yaw çalışır, pitch sentetikte üretilemez → test ortamında
  `CAYMAZ_FACE_POSES=left,right`, `CAYMAZ_FACE_MIN_SLOTS=3`). Masaüstü 1400×840 ve mobil 390×844: eğitim (halka, segment,
  tik), ikinci tarama, ayar bölümü, hesap listesi, yüz ile giriş (canlılık "Hafifçe sola bakın") → oturum; koyu tema; boş
  video → "Yüz bulunamadı — kameraya bakın"; kamera izni reddi → şifre ekranına düşüş. Betikler `/tmp/flsim/face/`.
