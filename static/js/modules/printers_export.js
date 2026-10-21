// Yazıcı listesi Excel dışa aktarımı ve MAC kimlik etiketleri (saf; DOM yok — node ile test edilir).
// Yazıcının benzersiz kimliği MAC'tir; IP yalnız "son görülen IP"dir (DHCP ile değişir).
import { t } from '../i18n.js';

export const MAC_SOURCE_LABELS = {
  elle: 'Elle girildi',
  arp: 'Ağ taraması (ARP)',
  cihaz: 'Yazıcının kendi API’si',
  kayit: 'Önceki kayıt (kaynak bilinmiyor)',
};

export const macSourceLabel = src => (src ? t(MAC_SOURCE_LABELS[src] || src) : '');

const STATE_LABELS = {
  HAZIR: 'Hazır', YAZDIRIYOR: 'Yazdırıyor', DURAKLADI: 'Duraklatıldı', TAMAMLANDI: 'Baskı bitti', HATA: 'Hata',
  CEVRIMDISI: 'Çevrimdışı', BAKIM: 'Bakımda', ARGE: 'Ar-Ge',
};

const date = iso => (iso ? new Date(iso) : '');
const rack = p => (p.rack_side ? `${p.rack_side === 'L' ? t('Sol') : t('Sağ')} ${p.rack_level}/${p.rack_slot}` : '');

export const EXPORT_COLUMNS = ['Yazıcı', 'MAC adresi', 'MAC kaynağı', 'Ağ adı', 'Son görülen IP', 'IP son görülme',
  'MAC son doğrulama', 'Durum', 'Model', 'Raf', 'Son yüklenen iş'];

// Excel tablosu: her yazıcı bir satır (MAC birincil kimlik). MAC'i olmayan yazıcılar "MAC YOK" yazılır ve listenin
// sonuna uyarı satırı eklenir (bu yazıcılara dosya gönderilemez).
export function printersExportSpec(printers) {
  const columns = EXPORT_COLUMNS.map(c => t(c));
  const rows = printers.map(p => [
    p.name,
    p.mac || t('MAC YOK'),
    macSourceLabel(p.mac_source),
    p.hw_id || '',
    p.ip || t('bilinmiyor'),
    date(p.last_seen),
    date(p.mac_checked_at),
    t(STATE_LABELS[p.maint_since ? 'BAKIM' : (p.live_state || 'CEVRIMDISI')] || p.live_state || ''),
    p.model || '',
    rack(p),
    p.last_job || '',
  ]);
  const missing = printers.filter(p => !p.mac);
  if (missing.length) {
    const pad = r => [...r, ...Array(columns.length - r.length).fill('')];
    rows.push(pad([]));
    rows.push(pad([`⚠ ${t('{n} yazıcının MAC adresi yok — bu yazıcılara dosya gönderilemez. Yazıcı Yönetimi’nde “MAC’i Öğren” ile kaydedin: {names}',
      { n: missing.length, names: missing.map(p => p.name).join(', ') })}`]));
  }
  return { columns, rows };
}
