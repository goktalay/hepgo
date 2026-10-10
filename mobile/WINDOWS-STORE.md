# HEPGO — Windows / Microsoft Store Yayınlama (PWABuilder → MSIX)

Uygulama zaten bir PWA (manifest + service worker + ikonlar hazır). Windows'a mağaza
uygulaması olarak koymanın en kısa yolu **PWABuilder** ile MSIX paketi üretip
**Microsoft Partner Center**'a yüklemektir. Yeni bir kod tabanı/derleme gerekmez;
güncellemeler web'den (app.hepgo.com) otomatik gelir.

PWABuilder'ın manifest'i okuyabilmesi için erişilebilir giriş noktası:

    https://app.hepgo.com/static/install.html

(Bu sayfa manifest linkini içerir; appgw restart'a gerek kalmadan 200 döner.)

---

## 1) Microsoft Partner Center hesabı (TEK SEFERLİK — senin yapman gerekir)

1. https://partner.microsoft.com/dashboard → **Windows & Xbox** programına kaydol.
2. Kayıt ücreti: bireysel ~**$19**, şirket ~**$99** (tek seferlik).
3. Onaylanınca "Apps and games" panosuna erişirsin.

## 2) Uygulama adını ayır (Partner Center)

1. **Apps and games → New product → MSIX or PWA app**.
2. Ad olarak **HEPGO ERP** (veya **HEPGO**) ayır. Ad müsaitse rezerve edilir.

## 3) Kimlik değerlerini al (PWABuilder bunları ister)

Partner Center → ürünün → **Product management → Product identity**. Şu 3 değeri kopyala:

- **Package/Identity/Name**  → PWABuilder'da "Package ID"
- **Package/Identity/Publisher** (CN=... ile başlar) → "Publisher ID"
- **Package/Properties/PublisherDisplayName** → "Publisher display name"

## 4) PWABuilder ile MSIX üret (tarayıcıda, herhangi bir OS)

1. https://www.pwabuilder.com → kutuya **https://app.hepgo.com/static/install.html** yaz → **Start**.
2. Skor kartını gör (manifest + service worker + güvenlik yeşil olmalı). Gerekirse "Edit".
3. **Package For Stores → Windows → Store package**.
4. Formu doldur:
   - **Publisher display name**, **Publisher ID (CN=...)**, **Package ID** → 3. adımdaki değerler.
   - **App name**: HEPGO ERP
   - **Version**: `1.0.1` (PWABuilder son haneyi 0 tutmanı söyler; ilk yüklemede `1.0.0.0`
     Store'a ayrılı olduğu için **1.0.1.0**'dan başla).
5. **Generate** → bir .zip iner. İçinde:
   - `*.msixbundle`  → **Store'a yüklenecek paket**
   - test paketi (yerelde denemek için, kendinden imzalı)
   - `next-steps.md` (PWABuilder'ın kendi notları)

## 5) (İsteğe bağlı) Windows'ta yerelde dene

Zip'teki **test** paketini Windows 10/11'de aç → sağ tık → Yükle (geliştirici modu gerekebilir).
Uygulama Edge WebView2 ile açılır, app.hepgo.com/app yüklenir, giriş yapıp kullanırsın.

## 6) Partner Center'a yükle ve gönder

1. Ürünün → **Packages** → `.msixbundle`'ı yükle.
2. **Store listings** (tr-TR):
   - Açıklama, kısa açıklama, özellikler.
   - **Ekran görüntüleri**: en az 1 adet, **1366×768** (veya 1920×1080) PNG/JPG.
     (Masaüstü ekran görüntüleri; istenirse ben üretebilirim — aşağıya bak.)
3. **Properties**: Kategori = **Business**. Gizlilik politikası URL'si (yasal sayfan).
4. **Age ratings** anketini doldur.
5. **Submit to the Store** → sertifikasyon ~24–48 saat → yayın.

---

## Notlar

- **Otomatik güncelleme**: Arayüz app.hepgo.com'dan geldiği için mağaza paketi nadiren
  güncellenir; sürüm/manifest/ikon değişince yeni paket üretip yüklersin.
- **Giriş ekranında tarayıcı "Yükle" istemi** (Edge/Chrome) için app.hepgo.com giriş
  sayfasına da manifest eklendi; bu, appgw servisinin yeniden başlatılmasıyla aktifleşir
  (DEV + PROD: `sudo systemctl restart hepgo-appgw.service`). Mağaza paketlemesi için
  ŞART DEĞİL — install.html zaten yeterli.
- **Ekran görüntüleri**: app.hepgo.com giriş gerektirdiğinden masaüstü ekran görüntülerini
  üretebilmem için ya giriş bilgisi ya da demo hesap gerekir; istersen hazırlarım.
