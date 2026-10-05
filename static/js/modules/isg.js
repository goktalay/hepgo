// İSG / KKD denetimi görünümü (Görüntü İşleme entegrasyonunun 2. özelliği): kamera tabanlı zorunlu KKD
// (kask/eldiven…) alarmları. Kask/eldiven tespiti fabrika makinesindeki KKD modeli ile çalışır; model yoksa
// yalnız Yüz Tanıma aktiftir. Kişi başına zorunlu KKD İK › personel › İSG sekmesinden ayarlanır.
import { api } from '../api.js';
import { clear, h, fmtDateTime, toast, toastError } from '../ui.js';

const PPE_LABEL = {
  kask: '⛑️ Kask', eldiven: '🧤 Eldiven', gozluk: '🥽 Gözlük', yelek: '🦺 Yelek',
  maske: '😷 Maske', kulaklik: '🎧 Kulaklık', ayakkabi: '🥾 Ayakkabı', tulum: '🧥 Tulum',
};
const nameOf = a => a.user_name || a.person_name || a.family_name || a.visitor_name || 'Tanımsız kişi';

export async function renderIsg(body, _ctx) {
  const note = h('div', { class: 'card card-pad', style: { marginBottom: '12px' } },
    h('b', null, 'İSG · KKD Kamera Denetimi'),
    h('p', { class: 'small muted', style: { margin: '6px 0 0' } },
      'Görüntü İşleme entegrasyonu, tanıdığı personelin zorunlu koruyucu donanımı (kask/eldiven…) takıp takmadığını kamerada denetler; eksikse burada alarm oluşur. '
      + 'Kişi başına zorunlu KKD: İnsan Kaynakları › personel detayı › İSG › KKD. '
      + 'Kask/eldiven tespiti fabrikadaki KKD modeliyle çalışır; model kurulmadıysa yalnız Yüz Tanıma etkindir.'));
  const list = h('div');
  body.append(note, list);

  const load = async () => {
    clear(list, h('div', { class: 'loading' }, 'Yükleniyor…'));
    let rows;
    try { rows = await api.get('/api/faces/isg-alarms?limit=300'); }
    catch (err) { return clear(list, h('div', { class: 'card empty' }, err.message || 'Alarmlar okunamadı')); }
    if (!rows.length) return clear(list, h('div', { class: 'card empty' }, 'Henüz İSG alarmı yok. Kamera denetimi, KKD modeli kurulu ve zorunlu KKD tanımlı personel kadraja girince alarm üretir.'));
    clear(list, h('div', { class: 'table-wrap card' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Zaman', 'Kişi', 'Kamera', 'Eksik KKD', 'Durum', ''].map(c => h('th', null, c)))),
      h('tbody', null, rows.map(a => {
        const missing = (a.missing || []).map(k => PPE_LABEL[k] || k).join(', ') || '—';
        const acked = !!a.acknowledged_at;
        const ackBtn = h('button', { class: 'btn xs' }, 'Görüldü');
        ackBtn.addEventListener('click', async () => {
          ackBtn.disabled = true;
          try { await api.post(`/api/faces/isg-alarms/${a.id}/ack`); toast('Görüldü olarak işaretlendi'); await load(); }
          catch (err) { toastError(err); ackBtn.disabled = false; }
        });
        return h('tr', { class: acked ? '' : 'isg-missing' },
          h('td', { class: 'nowrap small' }, a.at ? fmtDateTime(a.at) : '—'),
          h('td', null, h('b', null, nameOf(a))),
          h('td', { class: 'small' }, a.camera_name || (a.camera_id ? `Kamera #${a.camera_id}` : '—')),
          h('td', { class: 'wrap' }, missing),
          h('td', { class: 'small muted' }, acked ? 'Görüldü' : 'Yeni'),
          h('td', { class: 'nowrap' }, acked ? '—' : ackBtn));
      })))));
  };
  await load();
}
