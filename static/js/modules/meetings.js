// Kişisel → Toplantılar: şirket içi toplantı daveti. Düzenleyen konu, zaman, yer, talep notu ve hatırlatma süresiyle
// toplantı oluşturup kullanıcıları davet eder; davet bildirim olarak düşer, davetli notuyla Katılıyorum / Belki / Katılmıyorum
// der. Toplantıdan seçilen süre önce sesli hatırlatma gelir (bildirim: meeting-soon). Toplantılar kişisel takvimde de görünür.
import { api } from '../api.js';
import { renderRoom, renderSummary } from './meeting_room.js';
import { icons } from '../icons.js';
import { avatar, clear, confirmDialog, dateTimeInput, every, field, h, matches, modal, moduleToolbar, pageHead, peoplePicker, pref, setPref, svgIcon, t, toast, toastError } from '../ui.js';

export const STATUS = {
  BEKLIYOR: ['gray', 'Yanıt bekleniyor', '⏳'], KATILIYOR: ['green', 'Katılıyor', '✓'], BELKI: ['yellow', 'Belki', '?'],
  KATILMIYOR: ['red', 'Katılmıyor', '✗'], DUZENLEYEN: ['blue', 'Düzenleyen', '★'],
};
const REMIND = [[0, 'Hatırlatma yok'], [5, '5 dakika önce'], [10, '10 dakika önce'], [15, '15 dakika önce'], [30, '30 dakika önce'],
  [60, '1 saat önce'], [120, '2 saat önce'], [1440, '1 gün önce']];
const MONTHS = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
const DAYS = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];
const hm = iso => (iso ? iso.slice(11, 16) : '');
const badge = s => h('span', { class: `badge ${(STATUS[s] || STATUS.BEKLIYOR)[0]}` }, (STATUS[s] || STATUS.BEKLIYOR)[1]);
const when = m => {
  const d = new Date(m.starts_at);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()} ${DAYS[d.getDay()]} · ${hm(m.starts_at)}${m.ends_at ? `–${hm(m.ends_at)}` : ''}`;
};
const relative = iso => {
  const min = Math.round((new Date(iso) - Date.now()) / 60000);
  if (min < -5) return null;
  if (min <= 0) return t('başlıyor');
  if (min < 60) return t('{min} dk sonra', { min });
  if (min < 1440) return t('{h} sa {m}sonra', { h: Math.floor(min / 60), m: min % 60 ? t('{m} dk ', { m: min % 60 }) : '' });
  return t('{n} gün sonra', { n: Math.round(min / 1440) });
};

export async function renderMeetings(view, params = []) {
  if (params[1] === 'room') return renderRoom(view, Number(params[0]));
  if (params[1] === 'summary') return renderSummary(view, Number(params[0]));
  let scope = pref('meetings.scope', 'upcoming');
  const scopeSel = h('select', { class: 'input', title: 'Zaman' }, [['upcoming', 'Yaklaşan'], ['past', 'Geçmiş'], ['all', 'Tümü']].map(([v, l]) =>
    h('option', { value: v, selected: v === scope }, l)));
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Konu, kişi, yer ara…', style: { width: '200px' } });
  const out = h('div');
  let rows = [];
  clear(view, pageHead('Toplantılar', { back: '#/', sub: 'Toplantılar ve davetler' }),
    h('div', { class: 'filters' }, q, scopeSel),
    moduleToolbar(h('button', { class: 'btn primary', type: 'button', onclick: () => meetingForm(null, load) }, svgIcon(icons.plus), 'Yeni Toplantı')), out);

  const card = m => {
    const d = new Date(m.starts_at);
    const rel = !m.cancelled_at && relative(m.starts_at);
    const pending = m.my_status === 'BEKLIYOR' && !m.cancelled_at && new Date(m.starts_at) > new Date();
    return h('div', { class: `card mt-card ${m.cancelled_at ? 'cancelled' : ''} ${pending ? 'pending' : ''}`, onclick: () => openMeeting(m.id, load) },
      h('div', { class: 'mt-date' }, h('b', null, d.getDate()), h('span', null, MONTHS[d.getMonth()]), h('small', null, hm(m.starts_at))),
      h('div', { class: 'mt-body' },
        h('div', { class: 'mt-top' }, h('b', { class: 'mt-title' }, m.title), m.cancelled_at ? h('span', { class: 'badge red' }, 'İptal edildi') : badge(m.my_status)),
        h('div', { class: 'small muted' }, when(m), m.location ? ` · 📍 ${m.location}` : '', rel ? h('span', { class: 'mt-rel' }, ` · ${rel}`) : null),
        h('div', { class: 'small muted' }, t('Düzenleyen: {org}', { org: m.organizer })),
        h('div', { class: 'mt-people' }, m.invites.slice(0, 8).map(i => h('span', { class: `mt-av st-${i.status}`, title: `${i.full_name} · ${STATUS[i.status][1]}` }, avatar(i, 'sm'))),
          m.invites.length > 8 ? h('span', { class: 'small muted' }, `+${m.invites.length - 8}`) : null,
          h('span', { class: 'mt-counts small' }, ['KATILIYOR', 'BELKI', 'KATILMIYOR', 'BEKLIYOR'].map(s => m.counts[s] ? h('span', { class: `mt-c ${s}` }, `${STATUS[s][2]} ${m.counts[s]}`) : null))),
        pending ? h('div', { class: 'mt-quick', onclick: e => e.stopPropagation() },
          ['KATILIYOR', 'BELKI', 'KATILMIYOR'].map(s => h('button', { class: `btn sm mt-r ${s}`, type: 'button', onclick: () => respondModal(m, s, load) },
            { KATILIYOR: 'Katılıyorum', BELKI: 'Belki', KATILMIYOR: 'Katılmıyorum' }[s]))) : null));
  };
  const draw = () => {
    const list = rows.filter(m => matches(q.value, m.title, m.location, m.organizer, m.note, ...m.invites.map(i => i.full_name)));
    const pend = list.filter(m => m.my_status === 'BEKLIYOR' && !m.cancelled_at && new Date(m.starts_at) > new Date());
    const rest = list.filter(m => !pend.includes(m));
    clear(out,
      pend.length ? [h('h3', { class: 'mt-h' }, t('Yanıt bekleyen davetler ({n})', { n: pend.length })), h('div', { class: 'mt-grid' }, pend.map(card))] : null,
      rest.length ? [pend.length ? h('h3', { class: 'mt-h' }, scope === 'past' ? 'Geçmiş toplantılar' : 'Toplantılar') : null, h('div', { class: 'mt-grid' }, rest.map(card))] : null,
      !list.length ? h('div', { class: 'card empty' }, scope === 'past' ? 'Geçmiş toplantı yok' : 'Yaklaşan toplantınız yok. "Yeni Toplantı" ile oluşturup kişileri davet edin.') : null);
  };
  async function load() { rows = await api.get(`/api/meetings?scope=${scope}`); draw(); }
  scopeSel.addEventListener('change', () => { scope = scopeSel.value; setPref('meetings.scope', scope); load().catch(toastError); });
  q.addEventListener('input', draw);
  await load();
  every(30000, () => { if (!document.querySelector('.modal-back')) load().catch(() => {}); });
  if (params[0] && /^\d+$/.test(params[0])) openMeeting(Number(params[0]), load);   // bildirimden gelen toplantı
}

// ---------- Ayrıntı: bilgiler, talep notu, katılımcılar ve yanıtları; yanıt ver / düzenle / iptal
export async function openMeeting(id, done) {
  let m;
  try { m = await api.get(`/api/meetings/${id}`); } catch (err) { toastError(err); return; }
  const invitee = m.my_status && m.my_status !== 'DUZENLEYEN';
  const future = new Date(m.starts_at) > new Date(Date.now() - 3600e3);
  const note = h('textarea', { class: 'input', rows: 2, placeholder: 'Yanıtınıza not ekleyin (ör. 10 dk gecikebilirim)' }, m.my_response || '');
  const box = modal({
    title: m.title, wide: true, onClose: () => done?.(),
    body: h('div', { class: 'mt-detail' },
      m.cancelled_at ? h('div', { class: 'alert warn' }, 'Bu toplantı iptal edildi.') : null,
      h('dl', { class: 'sys-kv' },
        h('dt', null, 'Zaman'), h('dd', null, when(m), relative(m.starts_at) && !m.cancelled_at ? h('b', { class: 'mt-rel' }, ` · ${relative(m.starts_at)}`) : null),
        m.location ? [h('dt', null, 'Yer'), h('dd', null, /^https?:\/\//.test(m.location) ? h('a', { href: m.location, target: '_blank', rel: 'noopener' }, m.location) : m.location)] : null,
        h('dt', null, 'Düzenleyen'), h('dd', null, m.organizer),
        h('dt', null, 'Hatırlatma'), h('dd', null, (REMIND.find(r => r[0] === m.remind_min) || [0, '—'])[1])),
      m.note ? h('div', { class: 'call-msg' }, h('small', null, 'Talep notu'), m.note) : null,
      h('h4', null, t('Katılımcılar ({n})', { n: m.invites.length })),
      h('ul', { class: 'mt-list' }, m.invites.map(i => h('li', null, avatar(i, 'sm'),
        h('div', { class: 'grow' }, h('b', null, i.full_name), i.response ? h('div', { class: 'small muted' }, `“${i.response}”`) : null),
        badge(i.status)))),
      invitee && !m.cancelled_at && future ? h('div', { class: 'mt-answer' },
        h('h4', null, 'Yanıtınız'), note,
        h('div', { class: 'mt-quick' }, ['KATILIYOR', 'BELKI', 'KATILMIYOR'].map(s => h('button', {
          class: `btn mt-r ${s} ${m.my_status === s ? 'on' : ''}`, type: 'button', onclick: async () => {
            try { await api.post(`/api/meetings/${id}/respond`, { status: s, response: note.value }); toast('Yanıtınız iletildi'); box.close(); }
            catch (err) { toastError(err); }
          } }, { KATILIYOR: '✓ Katılıyorum', BELKI: '? Belki', KATILMIYOR: '✗ Katılmıyorum' }[s])))) : null),
    actions: [
      m.can_edit && !m.cancelled_at && !m.started_at ? { label: 'İptal Et', class: 'danger', onClick: async () => {
        if (!await confirmDialog('Toplantıyı iptal et', t('"{title}" iptal edilsin mi? Davetliler listesinde iptal olarak görür.', { title: m.title }), { okLabel: 'İptal Et', danger: true })) return true;
        await api.post(`/api/meetings/${id}/cancel`); toast('Toplantı iptal edildi');
      } } : null,
      m.can_edit && !m.cancelled_at && !m.started_at ? { label: 'Düzenle', onClick: () => { box.close(); meetingForm(m, done); return true; } } : null,
      'spacer',
      m.ended_at ? { label: 'Toplantı Özeti', class: 'primary', onClick: () => { location.hash = `#/meetings/${id}/summary`; } }
        : !m.cancelled_at && (m.started_at || m.can_edit || new Date(m.starts_at) - Date.now() < 3600e3)
          ? { label: m.started_at ? '● Toplantıya Katıl' : 'Toplantı Ekranı', class: 'primary', onClick: () => { location.hash = `#/meetings/${id}/room`; } } : null,
      { label: 'Kapat' },
    ].filter(Boolean),
  });
}

function respondModal(m, status, done) {
  const note = h('textarea', { class: 'input', rows: 3, placeholder: 'İsteğe bağlı not (ör. sunumu getireceğim)' });
  modal({
    title: { KATILIYOR: 'Katılıyorum', BELKI: 'Belki katılırım', KATILMIYOR: 'Katılmıyorum' }[status],
    body: h('div', null, h('p', { class: 'small muted' }, `${m.title} · ${when(m)}`), field('Not', note)),
    actions: [{ label: 'Vazgeç' }, { label: 'Yanıtı Gönder', class: 'primary', onClick: async () => {
      await api.post(`/api/meetings/${m.id}/respond`, { status, response: note.value }); toast('Yanıtınız iletildi'); done?.();
    } }],
  });
  note.focus();
}

// ---------- Yeni / düzenle
async function meetingForm(m, done) {
  const users = await api.get('/api/people');
  const me = (await api.get('/api/auth/me')).id;
  const title = h('input', { class: 'input', value: m?.title || '', placeholder: 'Ör. Haftalık üretim toplantısı' });
  const start = dateTimeInput({ value: m?.starts_at || nextSlot() });
  const end = dateTimeInput({ value: m?.ends_at || new Date(new Date(m?.starts_at || nextSlot()).getTime() + 3600e3).toISOString() });
  const loc = h('input', { class: 'input', value: m?.location || '', placeholder: 'Toplantı odası ya da çevrim içi bağlantı' });
  const note = h('textarea', { class: 'input', rows: 3, placeholder: 'Talep notu: gündem, hazırlanması gerekenler…' }, m?.note || '');
  const remind = h('select', { class: 'input' }, REMIND.map(([v, l]) => h('option', { value: v, selected: (m?.remind_min ?? 15) === v }, l)));
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi ara…' });
  const others = users.filter(u => u.id !== me);
  const chosen = new Set(m ? m.invites.map(i => i.user_id) : []);
  const pickBox = h('div');
  const drawPick = () => {
    const list = others.filter(u => matches(q.value, u.full_name, u.username));
    const p = peoplePicker(list, { selected: [...chosen], sub: u => u.username });
    p.addEventListener('click', () => { list.forEach(u => chosen.delete(u.id)); p.getIds().forEach(id => chosen.add(id)); count.textContent = t('{n} kişi seçildi', { n: chosen.size }); });
    clear(pickBox, p);
  };
  const count = h('span', { class: 'small muted' }, t('{n} kişi seçildi', { n: chosen.size }));
  q.addEventListener('input', drawPick);
  drawPick();
  modal({
    title: m ? 'Toplantıyı Düzenle' : 'Yeni Toplantı', wide: true,
    body: h('div', { class: 'mt-form' },
      h('div', null, field('Konu', title), h('div', { class: 'row' }, field('Başlangıç', start), field('Bitiş', end)),
        field('Yer / bağlantı', loc), field('Talep notu', note), field('Hatırlatma', remind),
        m ? h('p', { class: 'small muted' }, 'Zamanı değiştirirseniz davetlilerin yeniden yanıt vermesi istenir.') : null),
      h('div', null, field('Davet edilecek kişiler', h('div', { class: 'mt-who' }, q, count)), h('div', { class: 'mt-pick' }, pickBox))),
    actions: [{ label: 'Vazgeç' }, { label: m ? 'Kaydet' : 'Oluştur ve Davet Et', class: 'primary', onClick: async () => {
      const body = { title: title.value, starts_at: start.getValue(), ends_at: end.getValue(), location: loc.value, note: note.value,
        remind_min: Number(remind.value), user_ids: [...chosen] };
      if (m) await api.put(`/api/meetings/${m.id}`, body); else await api.post('/api/meetings', body);
      toast(m ? 'Toplantı güncellendi' : t('Toplantı oluşturuldu, {n} kişiye davet gitti', { n: chosen.size }));
      done?.();
    } }],
  });
  title.focus();
}

function nextSlot() {   // bir sonraki tam saat
  const d = new Date(Date.now() + 3600e3);
  d.setMinutes(0, 0, 0);
  return d.toISOString();
}
