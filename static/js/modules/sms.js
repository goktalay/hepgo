// Merkez › Toplu SMS: üye firmalara (iletişim telefonu kayıtlı) ya da elle girilen numaralara toplu SMS.
// Sağlayıcı: Netgsm (kullanıcı kodu, şifre, onaylı başlık). Sağlayıcı tanımlı değilse gönderim yapılmaz, deneme kaydı tutulur.
import { api } from '../api.js';
import { clear, field, fmtDateTime, h, pageHead, segmented, toast, toastError } from '../ui.js';

const SUBS = [['send', 'Gönder'], ['log', 'Gönderim Kaydı'], ['settings', 'Sağlayıcı Ayarı']];
const ST = { sent: ['green', 'Gönderildi'], failed: ['red', 'Başarısız'], dry: ['', 'Deneme (gönderilmedi)'] };

export async function render(view, params) {
  const sub = SUBS.some(s => s[0] === params[0]) ? params[0] : 'send';
  const nav = segmented(SUBS, sub, v => { location.hash = `#/sms/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Toplu SMS', { back: '#/', sub: 'Üye firmalara duyuru ve bilgilendirme', tabs: nav }), body);
  if (sub === 'log') return logView(body);
  if (sub === 'settings') return settingsView(body);
  return sendView(body);
}

async function sendView(view) {
  let rec = [], cfg = {};
  try { [rec, cfg] = await Promise.all([api.get('/api/central/sms/recipients'), api.get('/api/central/sms/config')]); }
  catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const picked = new Set();
  const list = h('div', { class: 'sms-rec' }, rec.length ? rec.map(r => {
    const cb = h('input', { type: 'checkbox', disabled: !r.phone, onchange: e => { e.target.checked ? picked.add(r.phone) : picked.delete(r.phone); count(); } });
    return h('label', { class: `sms-rec-row ${r.phone ? '' : 'dim'}` }, cb, h('span', { class: 'grow' }, h('b', null, r.name), h('small', { class: 'muted' }, r.phone || ' — telefon yok (Üyelik › Düzenle)')));
  }) : h('div', { class: 'muted small' }, 'Üye firma yok.'));
  const allBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => {
    list.querySelectorAll('input:not(:disabled)').forEach(cb => { cb.checked = true; cb.dispatchEvent(new Event('change')); });
  } }, 'Telefonu olanların hepsi');
  const extra = h('textarea', { class: 'input', rows: 2, placeholder: 'Ek numaralar (virgül ya da satırla ayırın): 05xx xxx xx xx' });
  const msg = h('textarea', { class: 'input', rows: 5, maxlength: 900, placeholder: 'Mesajınız…' });
  const info = h('small', { class: 'muted' });
  const count = () => {
    const extras = extra.value.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);
    const len = msg.value.length, parts = len <= 160 ? 1 : Math.ceil(len / 153);
    info.textContent = `${picked.size + extras.length} alıcı · ${len} karakter · ${len ? parts : 0} SMS`;
  };
  [extra, msg].forEach(el => el.addEventListener('input', count)); count();
  const send = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    const numbers = [...picked, ...extra.value.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean)];
    if (!numbers.length || !msg.value.trim()) return toast('Alıcı ve mesaj gerekli', 'err');
    send.disabled = true;
    try {
      const r = await api.post('/api/central/sms/send', { numbers, message: msg.value });
      toast(r.status === 'sent' ? `${r.count} numaraya gönderildi` : r.status === 'dry' ? 'Sağlayıcı tanımlı değil — deneme kaydı alındı' : `Gönderilemedi: ${r.response}`, r.status === 'failed' ? 'err' : undefined);
      if (r.status !== 'failed') { msg.value = ''; count(); }
    } catch (e) { toastError(e); } finally { send.disabled = false; }
  } }, 'Gönder');
  clear(view,
    cfg.usercode && cfg.has_password && cfg.header ? null : h('div', { class: 'card card-pad sms-warn' }, '⚠ SMS sağlayıcısı tanımlı değil. Gönderimler yalnızca deneme olarak kaydedilir. ', h('a', { href: '#/sms/settings' }, 'Sağlayıcı ayarı')),
    h('div', { class: 'sms-grid' },
      h('section', { class: 'card card-pad' }, h('div', { class: 'sms-head' }, h('h3', null, 'Alıcılar'), allBtn), list, field('Ek numaralar', extra)),
      h('section', { class: 'card card-pad' }, h('h3', null, 'Mesaj'), msg, h('div', { class: 'sms-bar' }, info, send))));
}

async function logView(view) {
  let rows = [];
  try { rows = await api.get('/api/central/sms/log'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  clear(view, rows.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
    h('thead', null, h('tr', null, ['Tarih', 'Gönderen', 'Alıcı', 'Mesaj', 'Durum'].map(x => h('th', null, x)))),
    h('tbody', null, rows.map(r => h('tr', null, h('td', null, fmtDateTime(r.created_at)), h('td', null, r.sender || '—'),
      h('td', { class: 'num' }, String(r.numbers.length)), h('td', { class: 'sms-msg' }, r.message),
      h('td', null, h('span', { class: `badge ${(ST[r.status] || [''])[0]}`, title: r.response || '' }, (ST[r.status] || ['', r.status])[1])))))))) : h('div', { class: 'card empty' }, 'Henüz gönderim yok.'));
}

async function settingsView(view) {
  let c = {};
  try { c = await api.get('/api/central/sms/config'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const uc = h('input', { class: 'input', value: c.usercode || '', placeholder: '850xxxxxxx' });
  const pw = h('input', { class: 'input', type: 'password', placeholder: c.has_password ? '•••••• (değiştirmek için yazın)' : 'API şifresi' });
  const hd = h('input', { class: 'input', value: c.header || '', placeholder: 'Onaylı SMS başlığı (ör. VEILOX)' });
  clear(view, h('section', { class: 'card card-pad set-card' }, h('h3', null, 'Netgsm'),
    h('p', { class: 'small muted' }, 'Netgsm hesabınızdaki API kullanıcı kodu, şifre ve onaylı mesaj başlığını girin. Şifre şifrelenmiş saklanır.'),
    field('Kullanıcı kodu', uc), field('Şifre', pw), field('Mesaj başlığı', hd),
    h('div', { class: 'set-actions left' }, h('button', { class: 'btn primary', type: 'button', onclick: async () => {
      try { await api.put('/api/central/sms/config', { provider: 'netgsm', usercode: uc.value, password: pw.value, header: hd.value }); toast('Kaydedildi'); pw.value = ''; }
      catch (e) { toastError(e); }
    } }, 'Kaydet'))));
}
