// Modül anahtarı → görünen ad (Türkçe kaynak; t() / h() ile kullanıcının diline çevrilir). Paket / üyelik ekranlarında
// ham anahtar (admin, stock…) yerine gösterilir. Başlıklar modül ızgarası ve rol kataloğuyla (app/rbac.py) aynıdır.
export const MODULE_NAMES = {
  boss: 'Patron', admin: 'Yönetim', users: 'Kullanıcı Yönetimi', reports: 'Raporlar', announcements: 'Duyurular', tools: 'Araçlar',
  production: 'Üretim Yönetimi', orders: 'İş Emri Yönetimi', printers: 'Yazıcı Yönetimi', products: 'Ürün Yönetimi',
  design: 'Endüstriyel Tasarım', mrp: 'MRP', stock: 'Yarı Mamül / Stok', warehouse: 'Onay / Depo', purchasing: 'Satın Alma',
  companies: 'Firma Yönetimi', documents: 'Evrak Yönetimi', sales: 'Satış Yönetimi', crm: 'CRM', finance: 'Finans',
  hr: 'İnsan Kaynakları', projects: 'Proje Yönetimi', field: 'Saha Yönetimi', fleet: 'Araç Yönetimi', certs: 'Sertifikasyon',
  cleaning: 'Temizlik', secretariat: 'Sekreterya', security: 'Güvenlik', cameras: 'Kameralar', rehber: 'Rehber',
  members: 'Üyelik Yönetimi', tickets: 'Destek Merkezi', sms: 'Toplu SMS', uyelik: 'Üyeliğim & Destek', mikro: 'Mikro ERP', master: 'Veri & Yedek', pos: 'Esnaf Kasa',
};
// Bilinmeyen (yeni) anahtar: ham anahtar yerine okunur biçim (ilk harf büyük)
export const moduleName = k => MODULE_NAMES[k] || String(k).replace(/[._-]+/g, ' ').replace(/^./, c => c.toLocaleUpperCase('tr'));
