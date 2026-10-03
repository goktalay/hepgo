"""Üyelik sözleşmeleri (Merkez): sürümlü sözleşme şablonları, firmaya özel doldurma ve elektronik onay kanıtı.

Akış (SaaS sektöründe yaygın "clickwrap" yöntemi):
  · Merkez şablonu taslak olarak hazırlar; yayınlayınca aynı türdeki önceki sürüm arşivlenir ve tüm firmalardan
    yeni sürüm için onay beklenir (zorunlu belgelerde firma yöneticisine bildirim gider).
  · Firma metni kendi bilgileriyle doldurulmuş hâliyle okur; yetkili kişi adı/ünvanıyla "okudum, kabul ediyorum" der.
  · Kanıt: belge + sürüm, firmaya özel metnin SHA-256 parmak izi, imzalayan adı/ünvanı/e-postası, zaman, IP ve tarayıcı.
    Onaylanan metin bire bir saklanır (sonradan şablon değişse de o günkü metin gösterilebilir).
Metin biçimi: '# başlık', '## alt başlık', '- madde', boş satır = paragraf, **kalın**. Alanlar: {{firma}} gibi.
"""
import hashlib
import json
from datetime import date

KINDS = {
    'abonelik': 'Abonelik ve Hizmet Sözleşmesi',
    'kvkk': 'KVKK Veri İşleme Sözleşmesi',
    'sla': 'Hizmet Seviyesi Taahhüdü (SLA)',
    'aup': 'Kabul Edilebilir Kullanım Politikası',
    'diger': 'Diğer',
}

FIELDS = [   # (alan, açıklama) — şablon düzenleyicide yardım olarak gösterilir
    ('firma', 'Müşteri firmanın unvanı'), ('firma_kodu', 'Firma kısa kodu'), ('adres', 'Firmaya ait sistem adresi'),
    ('paket', 'Abone olunan paket'), ('aylik_ucret', 'Aylık ücret (KDV hariç)'), ('baslangic', 'Üyelik başlangıç tarihi'),
    ('yonetici', 'Firma yönetici hesabı'), ('bugun', 'Bugünün tarihi'),
    ('saglayici', 'Hizmet sağlayıcı unvanı'), ('saglayici_adres', 'Sağlayıcı adresi'), ('saglayici_vergi', 'Sağlayıcı vergi dairesi / no'),
    ('saglayici_mersis', 'Sağlayıcı MERSİS no'), ('saglayici_eposta', 'Sağlayıcı e-posta'), ('saglayici_kep', 'Sağlayıcı KEP adresi'),
    ('mahkeme', 'Yetkili mahkeme ve icra daireleri'),
]

PROVIDER_KEY = 'contracts.provider'
PROVIDER_DEFAULT = {'saglayici': 'Veilox Yazılım', 'saglayici_adres': '', 'saglayici_vergi': '', 'saglayici_mersis': '',
                    'saglayici_eposta': '', 'saglayici_kep': '', 'mahkeme': 'İstanbul (Merkez) Mahkemeleri ve İcra Daireleri'}


def provider(conn):
    r = conn.execute('SELECT v FROM app_kv WHERE k = ?', (PROVIDER_KEY,)).fetchone()
    try:
        saved = json.loads(r[0]) if r else {}
    except ValueError:
        saved = {}
    return {**PROVIDER_DEFAULT, **{k: v for k, v in saved.items() if k in PROVIDER_DEFAULT}}


def _d(s):
    s = (s or '')[:10]
    return f'{s[8:10]}.{s[5:7]}.{s[:4]}' if len(s) == 10 else (s or '—')


def values(conn, company=None, package=None, fee=None):
    c = company or {}
    v = dict(provider(conn))
    v.update({
        'firma': c.get('name') or '[Firma unvanı]', 'firma_kodu': c.get('slug') or '—', 'adres': c.get('url') or '—',
        'paket': (package or {}).get('name') or '—',
        'aylik_ucret': (f'{fee:,.2f} TL'.replace(',', 'X').replace('.', ',').replace('X', '.') if fee else 'Ücretsiz / özel fiyatlandırma'),
        'baslangic': _d(c.get('provisioned_at') or c.get('created_at')), 'yonetici': c.get('master_username') or '—',
        'bugun': _d(date.today().isoformat()),
    })
    for k in list(v):
        v[k] = str(v[k] or '—')
    return v


def render(body, vals):
    out = body or ''
    for k, val in vals.items():
        out = out.replace('{{' + k + '}}', val)
    return out


def fingerprint(title, version, text):
    return hashlib.sha256(f'{title}\n{version}\n{text}'.encode('utf-8')).hexdigest()


# ---------------- Varsayılan şablonlar (TASLAK — yayınlamadan önce hukuk danışmanınca gözden geçirilmelidir) ----------------
DEFAULTS = [
    ('abonelik', 'Abonelik ve Hizmet Sözleşmesi', 'Bulut tabanlı kurumsal yazılım hizmetinin kapsamı, ücretler, sorumluluklar ve fesih koşulları.', """# Abonelik ve Hizmet Sözleşmesi

## 1. Taraflar
İşbu Abonelik ve Hizmet Sözleşmesi ("Sözleşme"), bir tarafta **{{saglayici}}** ({{saglayici_adres}}, {{saglayici_vergi}}, MERSİS: {{saglayici_mersis}}) ("Sağlayıcı") ile diğer tarafta **{{firma}}** ("Müşteri") arasında, Müşteri'nin elektronik ortamda onay verdiği tarihte yürürlüğe girmek üzere akdedilmiştir.

## 2. Tanımlar
- **Hizmet:** Sağlayıcı tarafından {{adres}} adresi üzerinden sunulan, Müşteri'nin abone olduğu pakete ({{paket}}) dahil modüllerden oluşan bulut tabanlı kurumsal yazılım hizmeti.
- **Kullanıcı:** Müşteri tarafından Hizmet'e erişim yetkisi verilen çalışan ve temsilciler.
- **Müşteri Verisi:** Müşteri ve Kullanıcılar tarafından Hizmet'e girilen, yüklenen veya Hizmet aracılığıyla oluşturulan her türlü veri.

## 3. Sözleşmenin Konusu ve Hizmetin Kapsamı
Sağlayıcı, abonelik süresince Hizmet'i Müşteri'nin kullanımına sunar; güncellemeler, güvenlik yamaları ve teknik destek abonelik kapsamındadır. Hizmet'in erişilebilirlik ve destek taahhütleri, Hizmet Seviyesi Taahhüdü'nde (SLA) düzenlenmiştir.

## 4. Abonelik Süresi ve Yenileme
Abonelik {{baslangic}} tarihinde başlamış olup aylık dönemler hâlinde, taraflardan biri dönem sonundan en az 30 (otuz) gün önce yazılı olarak (e-posta, KEP veya Hizmet içindeki destek kanalı) fesih bildiriminde bulunmadıkça kendiliğinden yenilenir.

## 5. Ücretler ve Ödeme
- Aylık abonelik ücreti **{{aylik_ucret}}** olup ücretlere KDV dahil değildir.
- Ücretler her ayın ilk 10 (on) günü içinde peşin olarak ödenir. Süresinde ödenmeyen tutarlar için, yazılı ihtar tarihinden itibaren 15 (on beş) gün içinde ödeme yapılmaması hâlinde Sağlayıcı Hizmet'i geçici olarak askıya alabilir; askı süresince Müşteri Verisi korunur.
- Sağlayıcı, ücretlerde yapacağı değişiklikleri en az 30 (otuz) gün önceden bildirir; Müşteri yeni ücreti kabul etmezse yürürlük tarihinden önce cezasız fesih hakkına sahiptir.

## 6. Müşteri'nin Yükümlülükleri
- Kullanıcı hesaplarının ve şifrelerin gizliliğini korumak, yetkisiz erişimi derhâl bildirmek.
- Hizmet'i yürürlükteki mevzuata ve Kabul Edilebilir Kullanım Politikası'na uygun kullanmak.
- Hizmet'e girdiği verilerin hukuka uygunluğundan ve gerekli aydınlatma/rıza süreçlerinden (veri sorumlusu sıfatıyla) sorumlu olmak.

## 7. Sağlayıcı'nın Yükümlülükleri
- Hizmet'i makul ticari özen ve sektör standartlarına uygun güvenlik önlemleriyle sunmak.
- Müşteri Verisi'ni yalnızca Hizmet'in sunulması amacıyla, KVKK Veri İşleme Sözleşmesi'ne uygun olarak işlemek.
- Planlı bakımları önceden duyurmak; güvenlik ihlallerini öğrenmesinden itibaren gecikmeksizin ve en geç 72 saat içinde Müşteri'ye bildirmek.

## 8. Verinin Mülkiyeti ve Taşınabilirlik
Müşteri Verisi'nin tüm hakları Müşteri'ye aittir. Müşteri, abonelik süresince ve sona ermesinden itibaren 30 (otuz) gün boyunca verilerinin yaygın kullanılan formatlarda (ör. Excel/CSV, belgeler için özgün dosya biçimi) dışa aktarılmasını talep edebilir. Bu sürenin sonunda veriler, yasal saklama yükümlülükleri saklı kalmak kaydıyla, geri döndürülemez biçimde silinir.

## 9. Fikri Mülkiyet
Hizmet'e ait yazılım, arayüz, marka ve dokümantasyon üzerindeki tüm fikri mülkiyet hakları Sağlayıcı'ya aittir. Müşteri'ye abonelik süresince devredilemez, münhasır olmayan bir kullanım hakkı tanınır.

## 10. Gizlilik
Taraflar, Sözleşme kapsamında öğrendikleri ticari sır ve gizli bilgileri, Sözleşme sona erdikten sonra da süresiz olarak gizli tutar ve yalnızca Sözleşme'nin ifası amacıyla kullanır.

## 11. Sorumluluğun Sınırlandırılması
Taraflardan hiçbiri, kâr kaybı, itibar kaybı gibi dolaylı zararlardan sorumlu değildir. Sağlayıcı'nın Sözleşme'den doğan toplam sorumluluğu, zarara yol açan olaydan önceki son 12 (on iki) ayda Müşteri'nin ödediği abonelik ücretleri toplamı ile sınırlıdır. Kast ve ağır kusur hâlleri ile kişisel verilere ilişkin kanuni sorumluluklar saklıdır.

## 12. Askıya Alma ve Fesih
- Taraflardan biri Sözleşme'yi esaslı şekilde ihlal eder ve yazılı ihtara rağmen 15 (on beş) gün içinde ihlali gidermezse, diğer taraf Sözleşme'yi derhâl feshedebilir.
- Fesih hâlinde Müşteri, Madde 8 uyarınca verilerini dışa aktarma hakkını korur.

## 13. Mücbir Sebep
Doğal afet, salgın, savaş, genel internet kesintisi, kamu otoritesi kararları gibi tarafların kontrolü dışındaki hâllerde, mücbir sebep süresince yükümlülükler askıya alınır.

## 14. Bildirimler
Taraflar arasındaki bildirimler e-posta ({{saglayici_eposta}}), KEP ({{saglayici_kep}}) veya Hizmet içindeki destek kanalı üzerinden yapılır. Hizmet içinden yapılan bildirimler, kayıt altına alındığı anda tebliğ edilmiş sayılır.

## 15. Uygulanacak Hukuk ve Yetki
Sözleşme Türkiye Cumhuriyeti hukukuna tabidir. Uyuşmazlıklarda {{mahkeme}} yetkilidir. Sağlayıcı'nın elektronik kayıtları, 6100 sayılı HMK md. 193 uyarınca kesin delil niteliğindedir.

## 16. Yürürlük
Sözleşme, Müşteri adına yetkili kişinin elektronik ortamda "Okudum, kabul ediyorum" onayı verdiği tarihte yürürlüğe girer. Onay kaydı; tarih-saat, IP adresi ve onaylanan metnin özet değerini (SHA-256) içerir.
"""),
    ('kvkk', 'KVKK Veri İşleme Sözleşmesi', '6698 sayılı KVKK md. 12 ve GDPR md. 28 ile uyumlu veri sorumlusu – veri işleyen sözleşmesi.', """# KVKK Veri İşleme Sözleşmesi

## 1. Taraflar ve Roller
İşbu Veri İşleme Sözleşmesi, **{{firma}}** ("Veri Sorumlusu") ile **{{saglayici}}** ("Veri İşleyen") arasında, Abonelik ve Hizmet Sözleşmesi'nin ayrılmaz eki olarak akdedilmiştir. Hizmet'e girilen kişisel verilerin veri sorumlusu Müşteri'dir; Sağlayıcı bu verileri yalnızca Müşteri adına ve talimatları doğrultusunda işler (6698 sayılı Kişisel Verilerin Korunması Kanunu md. 12; AB GDPR md. 28 ile uyumlu).

## 2. İşlemenin Konusu, Niteliği ve Süresi
- **Amaç:** Hizmet'in sunulması, barındırılması, yedeklenmesi, güvenliğinin sağlanması ve teknik destek.
- **Veri kategorileri:** Çalışan kimlik ve iletişim bilgileri, özlük ve devam kayıtları, müşteri/tedarikçi yetkili bilgileri, kullanıcı işlem kayıtları; Müşteri'nin kullandığı modüllere göre görüntü ve ses kayıtları.
- **İlgili kişi grupları:** Müşteri çalışanları, stajyerleri, ziyaretçileri, müşteri ve tedarikçi temsilcileri.
- **Süre:** Abonelik süresi ve sona ermesinden sonraki 30 günlük veri iade süresi.

## 3. Veri İşleyen'in Yükümlülükleri
- Kişisel verileri yalnızca Veri Sorumlusu'nun belgelenmiş talimatlarıyla işlemek; talimatın mevzuata aykırı olduğunu düşünürse derhâl bildirmek.
- Verilere erişen personelin gizlilik yükümlülüğü altında olmasını sağlamak.
- Kanun md. 12 kapsamında uygun teknik ve idari tedbirleri almak (aşağıda Madde 4).
- İlgili kişi başvurularının (Kanun md. 11) yanıtlanmasında Veri Sorumlusu'na makul destek vermek.
- Veri ihlalini öğrenmesinden itibaren gecikmeksizin ve en geç 72 saat içinde, bilinen ayrıntılarla Veri Sorumlusu'na bildirmek.
- Sözleşme sona erdiğinde verileri Veri Sorumlusu'nun tercihine göre iade etmek veya silmek ve bunu yazılı olarak teyit etmek.

## 4. Teknik ve İdari Tedbirler
- Aktarımda TLS şifreleme, gizli bilgiler (şifre, bağlantı anahtarları) için saklamada şifreleme.
- Rol tabanlı erişim kontrolü, güçlü şifre politikası, işlem (log) kayıtları.
- Düzenli yedekleme ve yedeklerden geri dönüş testleri.
- Destek amacıyla müşteri hesabına erişim yalnızca Müşteri'nin süreli onayı ile ve iz kaydı tutularak yapılır.

## 5. Alt Veri İşleyenler
Veri İşleyen, Hizmet'in sunulması için aşağıdaki alt işleyenlerden yararlanabilir: barındırma (sunucu) sağlayıcısı, içerik dağıtım ve güvenlik hizmeti (Cloudflare), Müşteri'nin etkinleştirmesi hâlinde yapay zekâ hizmet sağlayıcısı. Yeni bir alt işleyen eklenmesi en az 30 gün önce bildirilir; Veri Sorumlusu haklı gerekçeyle itiraz edebilir.

## 6. Yurt Dışına Aktarım
İçerik dağıtım ve güvenlik hizmetleri kapsamında verilerin yurt dışındaki sunucular üzerinden geçmesi söz konusu olabilir. Bu aktarımlar Kanun md. 9 ve ilgili ikincil düzenlemelerde öngörülen güvencelere (standart sözleşme vb.) uygun olarak gerçekleştirilir.

## 7. Denetim
Veri Sorumlusu, makul önceden bildirimle ve yılda bir defayı aşmamak üzere, Veri İşleyen'in bu Sözleşme'ye uyumunu belge talebi veya denetim yoluyla doğrulayabilir.

## 8. Yürürlük
Bu Sözleşme, Veri Sorumlusu adına yetkili kişinin elektronik onayıyla yürürlüğe girer ve Abonelik ve Hizmet Sözleşmesi süresince geçerlidir.
"""),
    ('sla', 'Hizmet Seviyesi Taahhüdü (SLA)', 'Erişilebilirlik hedefi, planlı bakım, destek yanıt süreleri ve hizmet kredileri.', """# Hizmet Seviyesi Taahhüdü (SLA)

## 1. Kapsam
Bu taahhüt, **{{saglayici}}** tarafından **{{firma}}** firmasına {{adres}} adresinden sunulan bulut Hizmet'i için geçerlidir. Müşteri'nin kendi sunucusunda (yerinde) çalışan kurulumlar erişilebilirlik taahhüdü kapsamı dışındadır.

## 2. Erişilebilirlik Hedefi
Sağlayıcı, her takvim ayı için **%99,5** erişilebilirlik hedefler. Erişilebilirlik; ay içindeki toplam dakikadan, planlı bakım ve hariç tutulan durumlar düşüldükten sonra Hizmet'in erişilebilir olduğu dakika oranıdır.

## 3. Planlı Bakım
Planlı bakımlar mümkün olduğunca mesai saatleri dışında yapılır ve en az 48 saat önceden Hizmet içinde duyurulur. Kritik güvenlik güncellemeleri önceden duyuru yapılmaksızın uygulanabilir.

## 4. Destek Kanalları ve Yanıt Süreleri
Destek talepleri Hizmet içindeki "Üyeliğim & Destek" bölümünden açılır. İlk yanıt hedefleri (iş günleri 09:00–18:00):
- **Kritik** (Hizmet'e hiç erişilemiyor): 4 saat
- **Yüksek** (temel bir modül çalışmıyor): 1 iş günü
- **Normal** (kısmi sorun, soru): 2 iş günü
- **Düşük** (öneri, geliştirme talebi): 5 iş günü
Gerektiğinde Müşteri'nin onayıyla uzaktan ekran paylaşımı üzerinden destek verilir.

## 5. Hizmet Kredisi
Aylık erişilebilirlik hedefin altında kalırsa, Müşteri'nin yazılı talebi üzerine izleyen ayın faturasına:
- %99,5 – %99,0 arası: aylık ücretin %5'i,
- %99,0 – %95,0 arası: %10'u,
- %95,0'ın altı: %25'i
oranında hizmet kredisi yansıtılır. Hizmet kredisi, erişilebilirlik ihlali için Müşteri'nin tek telafi yoludur.

## 6. Hariç Tutulan Durumlar
Müşteri'nin kendi altyapısı, internet bağlantısı veya cihazlarından kaynaklanan sorunlar; mücbir sebepler; Müşteri talimatıyla yapılan değişiklikler; planlı bakım süreleri erişilebilirlik hesabına dahil edilmez.
"""),
    ('aup', 'Kabul Edilebilir Kullanım Politikası', 'Hizmetin hangi amaçlarla kullanılamayacağına ilişkin kurallar.', """# Kabul Edilebilir Kullanım Politikası

**{{firma}}** ve Kullanıcıları, Hizmet'i kullanırken aşağıdaki kurallara uymayı kabul eder.

## 1. Yasak Kullanımlar
- Yürürlükteki mevzuata, üçüncü kişilerin haklarına veya kişisel verilerin korunması mevzuatına aykırı içerik yüklemek ya da işlemek.
- Hizmet'in güvenliğini test etmek, zafiyet taramak, tersine mühendislik yapmak veya erişim kısıtlamalarını aşmaya çalışmak (yazılı izin olmaksızın).
- Hizmet'i zararlı yazılım yaymak, istenmeyen toplu ileti (spam) göndermek veya hizmet dışı bırakma amaçlı aşırı yük oluşturmak için kullanmak.
- Kullanıcı hesaplarını başkalarıyla paylaşmak, yetkisiz kişilere erişim sağlamak.
- Kamera, ses kaydı ve konum özelliklerini ilgili kişilerin aydınlatılması ve gerekli hukuki dayanak olmaksızın kullanmak.

## 2. İçerik Sorumluluğu
Hizmet'e yüklenen tüm içerikten Müşteri sorumludur. Sağlayıcı, açıkça hukuka aykırı içerikleri yetkili makam kararı veya ciddi bir hukuki risk hâlinde kaldırabilir; bu durumda Müşteri'yi bilgilendirir.

## 3. İhlal
Bu Politika'nın ihlali, Abonelik ve Hizmet Sözleşmesi'nin esaslı ihlali sayılır. Sağlayıcı, ihlalin sürmesi hâlinde ilgili kullanıcı hesabını veya Hizmet'i geçici olarak askıya alabilir.
"""),
]


def seed(conn, user_id=None):
    """Hiç şablon yoksa varsayılanları TASLAK olarak ekler (yayınlanmaz)."""
    if conn.execute('SELECT COUNT(*) FROM contract_docs').fetchone()[0]:
        return 0
    from . import db
    now = db.now()
    for kind, title, summary, body in DEFAULTS:
        conn.execute('''INSERT INTO contract_docs (kind, title, version, summary, body, required, status, created_by, created_at, updated_at)
                        VALUES (?,?,?,?,?,1,'draft',?,?,?)''', (kind, title, '1.0', summary, body.strip(), user_id, now, now))
    conn.commit()
    return len(DEFAULTS)
