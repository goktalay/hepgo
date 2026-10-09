// Durum adları ve renkleri tek yerde.
import { h } from './ui.js';

export const PART_STATES = {
  BEKLIYOR: { label: 'Üretilmedi', color: 'var(--st-bekliyor)', badge: 'gray' },
  URETIMDE: { label: 'Üretimde', color: 'var(--st-uretimde)', badge: 'blue' },
  DEPO: { label: 'Depoda', color: 'var(--st-depo)', badge: 'yellow' },
  MONTAJ: { label: 'Montajda', color: 'var(--st-montaj)', badge: 'green' },
  HATA: { label: 'Hata', color: 'var(--st-hata)', badge: 'red' },
};

export const ORDER_STATES = {
  SIPARIS: { label: 'Sipariş', badge: 'gray' },
  URETIM: { label: 'Üretim', badge: 'blue' },
  HATA: { label: 'Hata', badge: 'red' },
  DEPO: { label: 'Depo', badge: 'yellow' },
  MONTAJ: { label: 'Montaj', badge: 'green' },
  SAHADA_MONTAJ: { label: 'Sahada Montaj', badge: 'blue' },
  KALIBRASYON: { label: 'Kalibrasyon', badge: 'yellow' },
  SAHA_ONAY: { label: 'Saha deposu onayı', badge: 'yellow' },
  TAMAMLANDI: { label: 'Saha Deposunda', badge: 'purple' },
  HURDA: { label: 'Hurda (uçtu)', badge: 'gray' },
};
// Mamul kullanım durumu: tek kullanımlık uçak uçunca HURDA olur
export const USAGE_TYPES = { TEK: { label: 'Tek kullanımlık', badge: 'yellow' }, COKLU: { label: 'Çoklu kullanım', badge: 'green' } };

export const TASK_STATES = {
  BASLANGIC: { label: 'Başlangıç', badge: 'gray' },
  GOREVDE: { label: 'Görevde', badge: 'blue' },
  GOREV_TAMAMLANDI: { label: 'Görev Tamamlandı', badge: 'green' },
  BASARISIZ: { label: 'Başarısız', badge: 'red' },
  RAPOR_TAMAMLANDI: { label: 'Rapor Tamamlandı', badge: 'purple' },
  IPTAL: { label: 'İptal', badge: 'gray' },
};

export const PRINTER_STATES = {
  HAZIR: { label: 'Hazır', badge: 'green' },
  YAZDIRIYOR: { label: 'Yazdırıyor', badge: 'blue' },
  DURAKLADI: { label: 'Duraklatıldı', badge: 'yellow' },
  TAMAMLANDI: { label: 'Baskı bitti', badge: 'purple' },
  HATA: { label: 'Hata', badge: 'red' },
  CEVRIMDISI: { label: 'Çevrimdışı', badge: 'gray' },
  BAKIM: { label: 'Bakımda', badge: 'orange' },
  ARGE: { label: 'Ar-Ge', badge: 'teal' },
};

// Sipariş durumu: tamamlanan parça baskısı siparişi saha deposuna değil stoğa girer
export function orderBadge(o) {
  if (o.product_stocked && o.status === 'TAMAMLANDI') return h('span', { class: 'badge purple' }, 'Stoğa girdi');
  return badge(ORDER_STATES, o.status);
}

export function badge(map, key) {
  const s = map[key] || { label: key || '—', badge: 'gray' };
  return h('span', { class: `badge ${s.badge}` }, s.label);
}

// Kuyruk numarası: uçağa takılan 4 vidalı metal etiket görünümü (lazerle kazınmış yazı). size: sm (tablo) | md | lg
export function queuePlate(q, size = 'sm') {
  return q ? h('span', { class: `qplate ${size}`, title: 'Kuyruk numarası (metal etiket)' }, h('span', null, q)) : null;
}
