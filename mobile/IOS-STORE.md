# HEPGO — iOS App Store Yayın Rehberi (Mac'siz, GitHub Actions ile)

Mac'in olmadığı için iOS paketi **GitHub Actions (bulut macOS)** üzerinde derlenir ve **TestFlight**'a
yüklenir. İmzalama **fastlane match** (şifreli sertifika deposu) + **App Store Connect API Key** ile yapılır.
Uygulama paketi: **`com.turkbey.hepgo`** (Android ile aynı Bundle ID).

> Repoda hazır olanlar (bende): `mobile/ios/` iOS projesi, Info.plist izin açıklamaları + arka plan modları,
> 1024×1024 App Store ikonu (opak), `.github/workflows/ios.yml`, fastlane `Fastfile/Appfile/Matchfile`.
> Senin yapacakların: Apple tarafı kayıtlar + GitHub **Secrets**. Hepsi aşağıda.

---

## 0) Ön koşul
- Apple Developer Program **aktif** (99 $/yıl) — ✅ sende var.

---

## 1) App Store Connect'te uygulamayı oluştur
1. https://appstoreconnect.apple.com → **Uygulamalarım → +** → **Yeni Uygulama**.
2. Platform **iOS**, Ad **HEPGO**, Birincil dil **Türkçe**, **Bundle ID = `com.turkbey.hepgo`**
   (listede yoksa: Developer portalında **Identifiers → + → App IDs** ile `com.turkbey.hepgo` oluştur,
   **Push Notifications** capability'sini işaretle), SKU: `hepgo-ios`.

## 2) App Store Connect API Key üret (imzalama + yükleme için)
1. App Store Connect → **Kullanıcılar ve Erişim → Integrations (Tümleştirmeler) → App Store Connect API → Keys**.
2. **+** ile anahtar üret, rol **App Manager** (veya Admin). 
3. Şunları not et: **Key ID**, **Issuer ID** (sayfanın üstünde). **AuthKey_XXXX.p8** dosyasını **indir (yalnız bir kez indirilebilir!)**.

## 3) Sertifika deposu için boş bir PRIVATE repo aç
- GitHub'da yeni **private** repo: ör. `goktalay/hepgo-ios-certs` (boş; README bile gerekmez).
- fastlane match imzalama sertifikalarını buraya **şifreli** olarak koyacak.

## 4) GitHub Secrets (fabrika-yonetim reposuna)
Repo → **Settings → Secrets and variables → Actions → New repository secret** ile şunları ekle:

| Secret | Değer |
|---|---|
| `ASC_KEY_ID` | API Key ID (Adım 2) |
| `ASC_ISSUER_ID` | Issuer ID (Adım 2) |
| `ASC_KEY_P8` | `.p8` dosyasının **base64**'ü. Komut: `base64 -i AuthKey_XXXX.p8` (çıktının tamamı; Linux'ta `base64 -w0 AuthKey_XXXX.p8`) |
| `MATCH_GIT_URL` | Sertifika reposu HTTPS URL'si (Adım 3), ör. `https://github.com/goktalay/hepgo-ios-certs.git` |
| `MATCH_PASSWORD` | Sertifikaları şifrelemek için **senin belirlediğin** güçlü bir parola (not et, sakla) |
| `MATCH_GIT_BASIC_AUTHORIZATION` | CI'nın sertifika reposuna yazması için: `base64("KULLANICI:PAT")`. Bir GitHub **Personal Access Token** (repo yetkili) üret, sonra `echo -n "goktalay:ghp_XXXX" \| base64` çıktısını koy |

> `.p8`, `MATCH_PASSWORD` ve PAT **gizli**dir; sadece GitHub Secrets'ta durur, repoda değil.

## 5) Derlemeyi başlat (ilk yükleme)
1. GitHub → repo → **Actions → "iOS TestFlight" → Run workflow**.
2. İlk çalıştırmada fastlane match, API Key ile **Dağıtım sertifikası + provisioning profili** üretir ve
   şifreli olarak `hepgo-ios-certs`'e kaydeder; ardından derler ve **TestFlight**'a yükler (~15-25 dk).
3. Hata olursa Actions loguna bak; en sık neden eksik/yanlış secret'tır.

## 6) TestFlight'ta dene
- App Store Connect → **TestFlight** → build "işleniyor"dan çıkınca kendini testçi ekle, TestFlight uygulamasıyla kur-dene.

## 7) Mağaza kaydı (Store listing) + gönderim
- **Açıklama / anahtar kelimeler:** `mobile/store/listing-tr.md` (Android ile aynı metinler kullanılabilir).
- **Ekran görüntüleri (ZORUNLU):** iPhone **6.7"** (1290×2796) en az 1 set; mümkünse 6.5" de. Cihazdan çek.
- **App Privacy (Veri Gizliliği):** Topla: Konum (uygulama işlevi), Kişiler, İletişim bilgileri, Fotoğraf/Medya, Ses,
  Tanımlayıcılar (bildirim). "Üçüncü tarafla paylaşım YOK", "izleme (tracking) YOK". Gizlilik URL: `https://app.hepgo.com/gizlilik`.
- **Yaş sınırı:** 17+ değil; iş uygulaması → genellikle 4+.
- **App Review notu:** WebView tabanlı kurumsal ERP; test için demo hesap bilgisi ver (inceleme hızlanır).
  Arka plan konumu gerekçesi: saha/görev personeli iş güvenliği takibi, çalışanın açık rızasıyla (KVKK).
- Submit for Review → inceleme (genelde 1-3 gün; hassas izinler ek bilgi isteyebilir).

## 8) Güncellemeler
- Native değişiklik gerekmez çoğu arayüz güncellemesinde (uygulama canlı `app.hepgo.com`'u yükler).
- Yeni native özellik / sürüm artışı gerektiğinde: Actions → "iOS TestFlight" tekrar çalıştır (build numarası otomatik artar).

## Notlar / sınırlar
- **Gelen arama tam-ekran** (Android'deki native eklenti) iOS'ta YOK — iOS'ta CallKit + PushKit gerekir (ayrı iş).
  Temel sürümde: uygulama açıkken arama çalar; kapalıyken APNs push (APNs kurulumu ayrıca yapılır).
- **Push (APNs):** iOS bildirimleri için Firebase'e iOS uygulaması + **APNs Auth Key** eklenmeli (ayrı adım; TestFlight çalışır, push sonra).
