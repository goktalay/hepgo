// Modül anahtarı → görünen ad (Türkçe kaynak; t() / h() ile kullanıcının diline çevrilir). Paket / üyelik ekranlarında
// ham anahtar (admin, stock…) yerine gösterilir. Başlıklar modül ızgarası ve rol kataloğuyla (app/rbac.py) aynıdır.
export const MODULE_NAMES = {
  boss: 'Patron', admin: 'Yönetim', users: 'Kullanıcı Yönetimi', reports: 'Raporlar', announcements: 'Duyurular', tools: 'Araçlar',
  production: 'Üretim Yönetimi', orders: 'İş Emri Yönetimi', printers: 'Yazıcı Yönetimi', products: 'Ürün Yönetimi',
  design: 'Endüstriyel Tasarım', mrp: 'MRP', stock: 'Yarı Mamül / Stok', warehouse: 'Onay / Depo', purchasing: 'Satın Alma',
  companies: 'Firma Yönetimi', documents: 'Evrak Yönetimi', sales: 'Satış Yönetimi', crm: 'CRM', finance: 'Finans',
  hr: 'İnsan Kaynakları', projects: 'Proje Yönetimi', field: 'Saha Yönetimi', drone: 'Dron Yönetimi', fleet: 'Araç Yönetimi', certs: 'Sertifikasyon',
  cleaning: 'Temizlik', secretariat: 'Sekreterya', security: 'Güvenlik', cameras: 'Kameralar', rehber: 'Rehber', factory: 'Fabrika', konum: 'Canlı Konum',
  members: 'Üyelik Yönetimi', sshmaster: 'Mastertool', tickets: 'Destek Merkezi', sms: 'Toplu SMS', uyelik: 'Üyeliğim & Destek', mikro: 'Mikro ERP', master: 'Veri & Yedek', pos: 'Esnaf Kasa', sections: 'Bölümler', services: 'Hizmetler', reservations: 'Rezervasyon', waiter: 'Garson',
};
// Bilinmeyen (yeni) anahtar: ham anahtar yerine okunur biçim (ilk harf büyük)
export const moduleName = k => MODULE_NAMES[k] || String(k).replace(/[._-]+/g, ' ').replace(/^./, c => c.toLocaleUpperCase('tr'));

// Modülün tek cümlelik açıklaması (Üyelik › Paketinizdeki Modüller kutucukları). Türkçe kaynak; t() ile çevrilir.
export const MODULE_DESC = {
  boss: 'Üst yönetim özeti: üretim, satış, finans ve saha tek ekranda', admin: 'Program ayarları, roller, entegrasyonlar ve sistem durumu',
  users: 'Kullanıcılar, roller ve giriş ayarları', reports: 'Tüm modüllerin raporları; grafik, baskı, Excel', announcements: 'Duyurular ve Şirketten Haberler akışı',
  tools: 'Yardımcı araçlar: terminal, dönüştürücüler, ağ', production: 'İş emirleri, baskı takibi, montaj ve hata kayıtları', orders: 'Sipariş ve iş emri yaşam döngüsü',
  printers: '3B yazıcı filosu, baskı kuyruğu ve bakım', products: 'Mamul, parça ağacı ve baskı dosyaları', design: 'Proje / çizim sürümleri, STEP önizleme ve CFD analizi',
  mrp: 'Malzeme ihtiyaç planlaması, yarı mamul ve depo onayı', stock: 'Yarı mamul ve yedek parça stoğu', warehouse: 'Depo teslim ve onay akışı', purchasing: 'Satın alma talepleri, teklifler ve tedarikçiler',
  companies: 'Müşteri / tedarikçi firmalar, kişiler, logo ve konum', documents: 'Evrak arşivi, e-imza ve paylaşım', sales: 'Teklif, satış faturası ve sipariş takibi', crm: 'Firma, evrak ve satış tek çatı altında',
  finance: 'Kasa / banka, cariler, nakit akışı ve mali tablolar', hr: 'Personel özlük, izin, İSG ve organizasyon', projects: 'Projeler, görevler ve ilerleme', field: 'Saha görevleri, uçuşlar, masraflar ve canlı harekât',
  drone: 'Dron envanteri, rotalar, köprüler ve uçuş simülatörü', fleet: 'Araç filosu, yakıt, bakım ve belgeler', certs: 'Sertifikalar, denetimler ve süre takibi', cleaning: 'Temizlik planı ve kontrol listesi',
  secretariat: 'Misafir, kargo ve telefon notları', security: 'Araç giriş / çıkış, nöbet ve ziyaretçi', cameras: 'NVR kameraları, yüz tanıma ve İSG denetimi', rehber: 'Kurum rehberi: kişiler, telefonlar, adresler',
  factory: 'Fabrika dijital ikizi: kat planı, kamera ve hareket izi', members: 'Üye firmalar, paketler ve ödemeler (merkez)', sshmaster: 'Mastertool uzak yönetim ve lisans', tickets: 'Destek talepleri ve canlı destek (merkez)',
  sms: 'Toplu SMS gönderimi', uyelik: 'Paketiniz, ödemeleriniz, destek ve sözleşmeler', mikro: 'Mikro ERP bağlantısı ve eşleşmeler', master: 'Veri dışa aktarım ve yedek', konum: 'Personelin mobil canlı konumu haritada',
  pos: 'Dokunmatik yazarkasa ve günlük satış', sections: 'Salon, masa ve oda düzeni', services: 'Hizmet listesi ve personel payı', reservations: 'Randevu / masa takvimi', waiter: 'Garson adisyon ve masa takibi',
};
