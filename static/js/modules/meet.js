// Görüntülü online toplantı: davet kodu, bekleme odası, şirket içi/dışı katılımcı, WebRTC mesh.
// #/meet (ana ekran: sıradaki toplantı kartı + program listesi), #/meet/{id} (oda). Dış katılımcı: /m/{code} → guestEntry.
// Arayüz: açık/ferah tema, yumuşak mavi kartlar, avatar yığınları, videonun üstünde yüzen hap kontrol çubuğu.
import { api } from '../api.js';
import { avatar, clear, confirmDialog, h, modal, t, toast, toastError } from '../ui.js';

const ICE = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }, { urls: 'stun:stun1.l.google.com:19302' }] };
const wsBase = () => (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host;

// ---- Çizgi ikonlar ----
const P = {
  mic: '<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"/><path d="M19 11a7 7 0 0 1-14 0M12 18v3"/>',
  micOff: '<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"/><path d="M19 11a7 7 0 0 1-14 0M12 18v3M3 3l18 18"/>',
  cam: '<rect x="2.5" y="6" width="13.5" height="12" rx="3"/><path d="M16 10.5l5.5-3.2v9.4L16 13.5z"/>',
  camOff: '<rect x="2.5" y="6" width="13.5" height="12" rx="3"/><path d="M16 10.5l5.5-3.2v9.4L16 13.5zM3 3l18 18"/>',
  screen: '<rect x="3" y="4" width="18" height="12" rx="2.5"/><path d="M8 20h8M12 16v4M9.5 10l2.5-2.5 2.5 2.5M12 7.5V13"/>',
  hand: '<path d="M8 13V6a1.5 1.5 0 0 1 3 0v5M11 10.5V4.5a1.5 1.5 0 0 1 3 0V11M14 10.5V6a1.5 1.5 0 0 1 3 0v8a6.5 6.5 0 0 1-6.5 6.5H10a6 6 0 0 1-5-2.8L3.4 15a1.6 1.6 0 0 1 2.7-1.7L8 15.5"/>',
  chat: '<path d="M20.5 12a8.5 8.5 0 0 1-12.4 7.5L3.5 20.5l1.1-4.4A8.5 8.5 0 1 1 20.5 12z"/>',
  people: '<circle cx="9" cy="8" r="3.2"/><path d="M3 19.5a6 6 0 0 1 12 0"/><circle cx="17.2" cy="9.2" r="2.5"/><path d="M15.8 14.3A5 5 0 0 1 21 19.5"/>',
  more: '<circle cx="5" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/><circle cx="19" cy="12" r="1.6" fill="currentColor"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  key: '<path d="M5 9h14M5 15h14M10 4L8 20M16 4l-2 16"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  video: '<rect x="2.5" y="6" width="13.5" height="12" rx="3"/><path d="M16 10.5l5.5-3.2v9.4L16 13.5z"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  send: '<path d="M4 12l16-8-6 16-2.5-6.5z"/>',
  files: '<path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/>',
  download: '<path d="M12 4v10M8 11l4 4 4-4M5 19h14"/>',
  pin: '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/><path d="M12 14v7"/>',
  end: '<path d="M2.8 14.6c5.2-4.8 13.2-4.8 18.4 0 .5.5.5 1.2 0 1.7l-1.7 1.7c-.4.4-1.1.5-1.6.1l-2.3-1.7c-.3-.2-.5-.6-.5-1v-2a10.4 10.4 0 0 0-6.2 0v2c0 .4-.2.8-.5 1l-2.3 1.7c-.5.4-1.2.3-1.6-.1l-1.7-1.7c-.5-.5-.5-1.2 0-1.7z" fill="currentColor" stroke="none"/>',
};
const ic = (name, cls = '') => {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', `vm-ic ${cls}`);
  s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '1.8');
  s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
  s.innerHTML = P[name] || ''; return s;
};

const MON = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
const pad = n => String(n).padStart(2, '0');
const dateParts = iso => { const d = new Date(iso); return isNaN(d) ? null : { day: `${pad(d.getDate())} ${MON[d.getMonth()]}`, time: `${pad(d.getHours())}:${pad(d.getMinutes())}` }; };

// Avatar yığını (+N)
function stack(people = [], total = 0) {
  const shown = people.slice(0, 4);
  const more = Math.max(0, (total || people.length) - shown.length);
  return h('div', { class: 'vm-stack' }, ...shown.map(p => avatar({ full_name: p.name, photo: p.photo }, 'sm')),
    more ? h('span', { class: 'vm-stack-more' }, `+${more}`) : null);
}

// ============================ ANA EKRAN ============================
export async function render(view, params, ctx) {
  if (params[0]) { openRoom(view, { mid: Number(params[0]), user: ctx.user }); return; }
  renderHome(view, ctx);
}

let histOpen = false;
const durText = m => {
  if (!m.started_at || !m.ended_at) return m.started_at ? '' : 'Başlamadan bitti';
  const min = Math.max(1, Math.round((new Date(m.ended_at) - new Date(m.started_at)) / 60000));
  return min >= 60 ? t('{h} sa {m} dk', { h: Math.floor(min / 60), m: min % 60 }) : t('{m} dk', { m: min });
};

// Bitmiş toplantı özeti: süre, katılımcılar, varsa kayıt / transkript
async function pastModal(m) {
  const body = h('div', { class: 'vm-past-body' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  modal({ title: m.title, wide: true, body });
  let d, info;
  try { [d, info] = await Promise.all([api.get(`/api/meet/${m.id}/detail`), api.get(`/api/meet/${m.id}`)]); }
  catch (err) { clear(body, h('div', { class: 'empty' }, err.message)); return; }
  const fmt = iso => { const p = dateParts(iso); return p ? `${p.day} ${p.time}` : '—'; };
  const joined = (info.participants || []).filter(p => p.state !== 'DAVETLI' || p.joined_at);
  clear(body,
    h('div', { class: 'vm-past-kv' },
      h('span', null, h('small', null, 'Başladı'), h('b', null, fmt(m.started_at))),
      h('span', null, h('small', null, 'Bitti'), h('b', null, fmt(m.ended_at))),
      h('span', null, h('small', null, 'Süre'), h('b', null, durText(m) || '—')),
      h('span', null, h('small', null, 'Sahibi'), h('b', null, m.host_name || '—'))),
    h('div', { class: 'vm-sec' }, t('Katılımcılar ({n})', { n: joined.length })),
    h('div', { class: 'vm-past-people' }, joined.map(p => h('span', { class: 'vm-past-p' }, avatar({ full_name: p.name, photo: p.photo }, 'sm'),
      h('span', null, p.name), p.is_external ? h('small', null, 'misafir') : null))),
    d.has_audio ? h('audio', { class: 'vm-past-audio', controls: true, preload: 'none', src: `/api/meet/${m.id}/audio` }) : null,
    d.segments?.length ? h('div', { class: 'vm-sec' }, 'Transkript') : null,
    d.segments?.length ? h('div', { class: 'vm-past-tr' }, d.segments.map(s => h('p', null,
      h('b', null, `${s.speaker_label || 'Konuşmacı'}: `), s.text))) : (m.record ? h('p', { class: 'small muted' }, 'Kayıt metne çevriliyor ya da konuşma algılanmadı.') : null));
}

async function renderHome(view, ctx) {
  const u = ctx.user;
  const histSec = h('div', { class: 'vm-sec', hidden: true }, 'Geçmiş toplantılar');
  const hist = h('div', { class: 'vm-list' });
  const hero = h('div', { class: 'vm-hero' }, h('div', { class: 'vm-skel' }));
  const list = h('div', { class: 'vm-list' });
  const page = h('div', { class: 'vm-home' },
    h('div', { class: 'vm-topbar' },
      h('a', { class: 'vm-round', href: '#/', title: 'Geri' }, ic('back')),
      h('span', { class: 'vm-topbar-title' }, 'Toplantılar'),
      h('span', { class: 'vm-round ghost' })),
    h('div', { class: 'vm-profile' }, avatar(u, 'lg'), h('b', null, u.full_name), h('small', null, u.username)),
    hero,
    h('div', { class: 'vm-quick' },
      h('button', { class: 'vm-qbtn primary', type: 'button', onclick: () => newMeetingModal(ctx, () => renderHome(view, ctx)) },
        h('span', { class: 'vm-qic' }, ic('plus')), h('span', null, h('b', null, 'Yeni toplantı'), h('small', null, 'Hemen ya da planlı'))),
      h('button', { class: 'vm-qbtn', type: 'button', onclick: () => joinByCodeModal() },
        h('span', { class: 'vm-qic' }, ic('key')), h('span', null, h('b', null, 'Kod ile katıl'), h('small', null, 'Davet koduyla gir')))),
    h('div', { class: 'vm-sec' }, 'Program'),
    list,
    histSec, hist);
  clear(view, page);
  // Geçmiş toplantılar: bitenler (sahibi ya da katılımcısı olunan)
  api.get('/api/meet/history').then(old => {
    if (!old?.length) return;
    histSec.hidden = false;
    clear(hist, old.slice(0, histOpen ? 60 : 8).map(m => {
      const dp = dateParts(m.ended_at || m.started_at || m.created_at);
      return h('button', { class: 'vm-item vm-past', type: 'button', onclick: () => pastModal(m) },
        h('div', { class: 'grow' }, h('b', null, m.title),
          h('div', { class: 'vm-past-meta' }, stack(m.people, m.joined_count),
            h('small', null, [durText(m), m.segment_count ? 'Transkript var' : m.record ? 'Kayıtlı' : null].filter(Boolean).join(' · ')))),
        h('div', { class: 'vm-item-when' }, dp ? [h('b', null, dp.day), h('small', null, dp.time)] : null));
    }), old.length > 8 && !histOpen ? h('button', { class: 'vm-more', type: 'button', onclick: () => { histOpen = true; renderHome(view, ctx); } }, t('Tümünü göster ({n})', { n: old.length })) : null);
  }).catch(() => {});

  let rows = [];
  try { rows = await api.get('/api/meet'); } catch (err) { clear(list, h('div', { class: 'vm-empty' }, err.message)); }
  // Kahraman kart: devam eden ya da en yakın planlı toplantı
  const live = rows.find(m => m.status === 'DEVAM');
  const upcoming = rows.filter(m => m.status !== 'DEVAM' && m.scheduled_at).sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at))[0];
  const top = live || upcoming || rows[0];
  if (top) {
    const dp = dateParts(top.scheduled_at || top.started_at || top.created_at);
    clear(hero,
      h('div', { class: 'vm-hero-h' }, h('b', null, top.title),
        live ? h('span', { class: 'vm-live' }, h('i'), 'Canlı') : dp ? h('small', null, `${dp.day} ${dp.time}`) : null),
      h('div', { class: 'vm-hero-mid' }, stack(top.people, top.participant_count),
        h('button', { class: 'vm-chip', type: 'button', title: 'Davet linkini kopyala', onclick: () => copyLink(top) }, ic('link'), top.code)),
      h('button', { class: 'vm-join', type: 'button', onclick: () => { location.hash = `#/meet/${top.id}`; } },
        live ? 'Toplantıya Katıl' : top.is_host ? 'Toplantıyı Başlat' : 'Toplantıya Katıl'));
  } else {
    clear(hero, h('div', { class: 'vm-hero-h' }, h('b', null, 'Planlı toplantı yok')),
      h('p', { class: 'vm-hero-p' }, 'Yeni bir toplantı başlatın ya da davet koduyla katılın.'),
      h('button', { class: 'vm-join', type: 'button', onclick: () => newMeetingModal(ctx, () => renderHome(view, ctx)) }, 'Yeni Toplantı Başlat'));
  }
  const rest = rows.filter(m => m !== top);
  clear(list, rest.length ? rest.map(m => {
    const dp = dateParts(m.scheduled_at || m.created_at);
    return h('button', { class: 'vm-item', type: 'button', onclick: () => { location.hash = `#/meet/${m.id}`; } },
      h('div', { class: 'grow' }, h('b', null, m.title), stack(m.people, m.participant_count)),
      h('div', { class: 'vm-item-when' },
        m.status === 'DEVAM' ? h('span', { class: 'vm-live' }, h('i'), 'Canlı') : dp ? [h('b', null, dp.day), h('small', null, dp.time)] : null));
  }) : [h('div', { class: 'vm-empty' }, rows.length ? 'Başka toplantı yok.' : 'Henüz toplantı yok.')]);
}

// Davet metni (Google Meet biçimi): başlık, tarih-saat, saat dilimi, katılma bilgileri, bağlantı, kod
function copyLink(m) {
  const text = m.invite_text || m.link;
  navigator.clipboard?.writeText(text).then(() => toast('Davet bilgileri kopyalandı'), () => toast(text));
}
async function sendInviteMail(mid) {
  try {
    const r = await api.post(`/api/meet/${mid}/email`, {});
    toast(t('{n} / {t} katılımcıya davet e-postası gönderildi', { n: r.sent, t: r.total }) + (r.errors?.length ? ` · hata: ${r.errors[0]}` : ''), r.errors?.length ? 'err' : 'success');
  } catch (err) { toastError(err); }
}

function newMeetingModal(ctx, done) {
  const title = h('input', { class: 'input', placeholder: 'Örn: Haftalık üretim toplantısı' });
  const when = h('input', { class: 'input', type: 'datetime-local' });
  const dur = h('select', { class: 'input' }, ...[15, 30, 45, 60, 90, 120, 180].map(v => h('option', { value: v, selected: v === 60 }, v >= 60 ? t('{h} saat{m}', { h: Math.floor(v / 60), m: v % 60 ? ` ${v % 60} dk` : '' }) : t('{m} dk', { m: v }))));
  const mailCb = h('input', { type: 'checkbox', checked: true });
  const wr = h('input', { type: 'checkbox', checked: true });
  const rec = h('input', { type: 'checkbox' });
  const userSel = h('div', { class: 'vm-usersel' }, h('div', { class: 'small muted' }, 'Yükleniyor…'));
  const picked = new Set();
  const exts = h('div', { class: 'vm-exts' });
  const addExt = () => exts.append(h('div', { class: 'vm-ext-row' },
    h('input', { class: 'input', placeholder: 'Ad Soyad' }), h('input', { class: 'input', placeholder: 'E-posta (ops.)', type: 'email' })));
  addExt();
  api.get('/api/meet/invitees').then(us => {
    clear(userSel, (us || []).filter(x => x.id !== ctx.user.id).map(x => {
      const cb = h('input', { type: 'checkbox', onchange: e => e.target.checked ? picked.add(x.id) : picked.delete(x.id) });
      return h('label', { class: 'vm-user' }, cb, avatar(x, 'sm'), h('span', null, x.full_name));
    }));
  }).catch(() => clear(userSel, h('div', { class: 'small muted' }, 'Kullanıcılar yüklenemedi')));
  modal({
    title: 'Yeni toplantı', wide: true,
    body: h('div', { class: 'vm-form' },
      h('label', { class: 'field' }, h('span', null, 'Başlık'), title),
      h('label', { class: 'field' }, h('span', null, 'Zaman (opsiyonel)'), when,
        h('small', { class: 'hint' }, 'Boş bırakırsanız hemen başlatabilirsiniz; zaman girerseniz programda ve davet metninde görünür.')),
      h('label', { class: 'field' }, h('span', null, 'Süre'), dur),
      h('label', { class: 'set-toggle' }, mailCb, h('span', null, h('b', null, 'Katılımcılara davet e-postası gönder'), h('small', null, 'Şirket logolu davet; bağlı posta hesabınızdan gönderilir'))),
      h('label', { class: 'set-toggle' }, wr, h('span', null, h('b', null, 'Bekleme odası'), h('small', null, 'Katılımcılar önce bekler, siz kabul edersiniz'))),
      h('label', { class: 'set-toggle' }, rec, h('span', null, h('b', null, 'Toplantıyı kaydet'), h('small', null, 'Konuşmalar kaydedilir ve metne çevrilir'))),
      h('h4', { class: 'set-sub' }, 'Şirket içi davetliler'), userSel,
      h('h4', { class: 'set-sub' }, 'Dış katılımcılar'), exts,
      h('button', { class: 'btn xs', type: 'button', onclick: addExt }, '＋ Dış katılımcı ekle')),
    actions: ['spacer', { label: 'İptal', onClick: () => {} }, {
      label: 'Oluştur', class: 'primary',
      onClick: async () => {
        if (!title.value.trim()) throw new Error('Başlık girin');
        const externals = [...exts.querySelectorAll('.vm-ext-row')].map(r => {
          const [n, e] = r.querySelectorAll('input'); return { name: n.value.trim(), email: e.value.trim() };
        }).filter(x => x.name);
        const d = await api.post('/api/meet', { title: title.value.trim(), scheduled_at: when.value || null, duration_min: Number(dur.value) || 60,
          send_email: mailCb.checked, waiting_room: wr.checked, record: rec.checked, user_ids: [...picked], externals });
        toast(t('Toplantı oluşturuldu · Kod: {code}', { code: d.code }), 'success');
        if (d.email) toast(d.email.error ? `E-posta gönderilemedi: ${d.email.error}` : t('{n} / {t} katılımcıya davet e-postası gönderildi', { n: d.email.sent, t: d.email.total }), d.email.error ? 'err' : 'success');
        done?.();
        createdModal(d);
      },
    }],
  });
}

function createdModal(d) {
  const row = (label, value) => h('div', { class: 'vm-linkrow' }, h('small', null, label),
    h('div', { class: 'vm-linkbox' }, h('span', null, value),
      h('button', { class: 'vm-round sm', type: 'button', title: 'Kopyala', onclick: () => { navigator.clipboard?.writeText(value); toast('Kopyalandı'); } }, ic('link'))));
  modal({
    title: 'Toplantı hazır',
    body: h('div', { class: 'vm-created' },
      h('div', { class: 'vm-created-ic' }, ic('video')),
      d.invite_text ? h('div', { class: 'vm-linkrow' }, h('small', null, 'Davet bilgileri'),
        h('pre', { class: 'vm-invite' }, d.invite_text),
        h('div', { class: 'stp-bar' },
          h('button', { class: 'btn sm primary', type: 'button', onclick: () => { navigator.clipboard?.writeText(d.invite_text); toast('Davet bilgileri kopyalandı'); } }, '⧉ Davet bilgilerini kopyala'),
          h('button', { class: 'btn sm', type: 'button', onclick: () => sendInviteMail(d.id) }, '📧 Davet e-postası gönder'))) : null,
      row('Davet kodu', d.code), row('Toplantı linki', d.link),
      ...(d.externals || []).map(e => row(t('{name} için özel link', { name: e.name }), e.link))),
    actions: ['spacer', { label: 'Tamam', class: 'primary', onClick: () => {} }],
  });
}

function joinByCodeModal() {
  const code = h('input', { class: 'input vm-codein', placeholder: 'A123-456', autocapitalize: 'characters' });
  modal({
    title: 'Kod ile katıl',
    body: h('label', { class: 'field' }, h('span', null, 'Davet kodu'), code),
    actions: ['spacer', { label: 'İptal', onClick: () => {} }, {
      label: 'Katıl', class: 'primary',
      onClick: async () => {
        const c = code.value.trim().toUpperCase();
        if (!c) throw new Error('Kod girin');
        const d = await api.post(`/api/meet/join/${encodeURIComponent(c)}`, {});
        location.hash = `#/meet/${d.meeting_id}`;
      },
    }],
  });
}

// ============================ ODA (WebRTC) ============================
// opts: { mid, user } (içerik)  |  { mid, guest:{token,name,pid}, title } (dış)
export async function openRoom(view, opts) {
  const { mid, guest } = opts;
  const myName = guest ? guest.name : (opts.user?.full_name || 'Ben');
  const myPhoto = guest ? null : opts.user?.photo;
  const root = h('div', { class: 'vm-room' });
  const host = view || document.getElementById('app') || document.body;
  clear(host, root);

  const stage = h('div', { class: 'vm-stage' });
  const self = tile({ name: myName, photo: myPhoto, self: true });
  self.el.classList.add('vm-self');
  const peers = new Map();   // cid -> { pc, info, t }
  let ws = null, localStream = null, selfCid = null, isHost = false, screenTrack = null, recorder = null, recBlobs = [];
  let myPid = guest ? guest.pid : null, camOn = true, micOn = true, hand = false, recording = false;
  let timerId = null, unreadChat = 0, selfHandSeq = 0;
  const pinned = new Set();        // sabitlenen kişiler (cid)
  const dmThreads = new Map();     // cid -> [{mine,text,time}]  · kişiye özel sohbet
  const dmUnread = new Map();      // cid -> okunmamış özel mesaj sayısı
  let dmPeer = null;               // açık özel sohbetin karşı tarafı (cid)

  // Üst bilgi
  const titleEl = h('b', null, opts.title || 'Toplantı');
  const countEl = h('span', { class: 'vm-count' }, ic('people'), h('span', null, '1'));
  const btnPeople = topBtn('people', 'Katılımcılar', () => togglePanel('people'));
  const btnChat = topBtn('chat', 'Sohbet', () => togglePanel('chat'));
  const btnFiles = topBtn('files', 'Dosya kutusu', () => togglePanel('files'));
  const top = h('div', { class: 'vm-top' }, h('div', { class: 'vm-top-l' }, titleEl, countEl), h('div', { class: 'vm-top-r' }, btnChat, btnFiles, btnPeople));

  // Yüzen hap kontrol çubuğu
  const btnMic = pillBtn('mic', 'Mikrofon', () => toggleMic());
  const btnCam = pillBtn('cam', 'Kamera', () => toggleCam());
  const btnScreen = pillBtn('screen', 'Ekran paylaş', () => toggleScreen(), 'wide-only');
  const btnHand = pillBtn('hand', 'El kaldır', () => toggleHand(), 'wide-only');
  const btnMore = pillBtn('more', 'Diğer', () => moreMenu(), 'narrow-only');
  const timer = h('span', { class: 'vm-timer' }, h('i'), h('span', null, '00:00'));
  const btnEnd = h('button', { class: 'vm-end', type: 'button', title: 'Ayrıl', onclick: () => leave(true) }, ic('end'));
  const pill = h('div', { class: 'vm-pill' }, btnMic, btnCam, btnScreen, btnHand, timer, btnMore, btnEnd);

  // Paneller (masaüstü: sağ kart, mobil: alt sayfa)
  const chatList = h('div', { class: 'vm-chat-list' });
  const chatInput = h('input', { class: 'input', placeholder: 'Mesaj yazın…' });
  chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });
  const chatPanel = panel('Sohbet', chatList, h('div', { class: 'vm-chat-bar' }, chatInput,
    h('button', { class: 'vm-send', type: 'button', title: 'Gönder', onclick: sendChat }, ic('send'))));
  const waitBox = h('div', { class: 'vm-waitbox' });
  const peopleList = h('div', { class: 'vm-people' });
  const peoplePanel = panel('Katılımcılar', waitBox, peopleList);
  // Dosya kutusu paneli
  const filesList = h('div', { class: 'vm-files' });
  const fileInput = h('input', { type: 'file', hidden: true, onchange: () => uploadFiles(fileInput.files) });
  const filesPanel = panel('Dosya kutusu', filesList, h('div', { class: 'vm-files-bar' }, fileInput,
    h('button', { class: 'btn primary', type: 'button', onclick: () => fileInput.click() }, ic('plus'), 'Dosya yükle')));
  // Kişiye özel sohbet (DM) paneli
  const dmList = h('div', { class: 'vm-chat-list' });
  const dmInput = h('input', { class: 'input', placeholder: 'Özel mesaj…' });
  dmInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendDm(); });
  const dmTitle = h('b', null, 'Özel sohbet');
  const dmPanel = panel('Özel sohbet', dmList, h('div', { class: 'vm-chat-bar' }, dmInput,
    h('button', { class: 'vm-send', type: 'button', title: 'Gönder', onclick: sendDm }, ic('send'))));
  dmPanel.el.querySelector('.vm-panel-h b').replaceWith(dmTitle);
  const pinBubbles = h('div', { class: 'vm-pins' });   // solda sabitlenen kişiler
  const waitScreen = h('div', { class: 'vm-waiting', hidden: true });
  const recBanner = h('div', { class: 'vm-recbar', hidden: true }, h('span', { class: 'vm-recdot' }), 'Bu toplantı kaydediliyor');

  clear(root, h('div', { class: 'vm-main' }, stage, self.el, top, pill, chatPanel.el, peoplePanel.el, filesPanel.el, dmPanel.el, pinBubbles, recBanner), waitScreen);
  layout();

  function topBtn(icon, label, onclick) { return h('button', { class: 'vm-round glass', type: 'button', title: label, onclick }, ic(icon)); }
  function pillBtn(icon, label, onclick, cls = '') {
    const b = h('button', { class: `vm-pbtn ${cls}`, type: 'button', title: label, onclick }, ic(icon));
    b._icon = icon; return b;
  }
  function setIcon(btn, name) { clear(btn, ic(name)); }
  function panel(titleText, ...kids) {
    const el = h('div', { class: 'vm-panel', hidden: true },
      h('div', { class: 'vm-panel-h' }, h('b', null, titleText),
        h('button', { class: 'vm-round sm', type: 'button', title: 'Kapat', onclick: () => { el.hidden = true; } }, ic('close'))),
      ...kids);
    return { el };
  }
  function tile(info) {
    const video = h('video', { autoplay: true, playsinline: true, muted: !!info.self });
    const av = h('div', { class: 'vm-tile-av' }, avatar({ full_name: info.name, photo: info.photo }, 'lg'));
    const name = h('span', null, info.self ? 'Siz' : (info.name || '…'));
    const mute = h('span', { class: 'vm-tile-mute', hidden: true }, ic('micOff'));
    const handEl = h('span', { class: 'vm-tile-hand', hidden: true }, ic('hand'));
    const meter = h('div', { class: 'vm-tile-meter' }, h('i'), h('i'), h('i'));   // sağ altta canlı ses grafiği
    const el = h('div', { class: `vm-tile camoff ${info.self ? 'self' : ''}` }, video, av, meter, h('div', { class: 'vm-tile-name' }, handEl, mute, name));
    return {
      el, video, av, name,
      setCam(on) { el.classList.toggle('camoff', !on); },
      setMuted(m) { mute.hidden = !m; },
      setHand(x) { handEl.hidden = !x; el.classList.toggle('hand', !!x); },
      setLevel(v) { const on = v > 0.07; el.classList.toggle('speaking', on); meter.style.setProperty('--lvl', Math.min(1, v * 2.5).toFixed(2)); },
      setInfo(p) { name.textContent = p.name || '…'; clear(av, avatar({ full_name: p.name, photo: p.photo }, 'lg')); },
    };
  }

  // --------- Canlı ses grafiği (konuşan kişi) ---------
  let audioCtx = null, rafMeter = null;
  function attachMeter(tileObj, stream) {
    try {
      if (!stream.getAudioTracks().length) return;
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const an = audioCtx.createAnalyser(); an.fftSize = 256; an.smoothingTimeConstant = 0.6;
      audioCtx.createMediaStreamSource(stream).connect(an);
      tileObj.analyser = an; tileObj.audioData = new Uint8Array(an.frequencyBinCount);
    } catch { /* */ }
  }
  function meterLoop() {
    const tiles = [self, ...[...peers.values()].map(e => e.t)];
    for (const t of tiles) {
      if (!t.analyser) { t.setLevel?.(0); continue; }
      t.analyser.getByteFrequencyData(t.audioData);
      let sum = 0; for (let i = 0; i < t.audioData.length; i++) sum += t.audioData[i] * t.audioData[i];
      t.setLevel?.(Math.sqrt(sum / t.audioData.length) / 255);
    }
    rafMeter = requestAnimationFrame(meterLoop);
  }

  async function start() {
    try { localStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: true }); }
    catch {
      try { localStream = await navigator.mediaDevices.getUserMedia({ audio: true }); camOn = false; }
      catch { toast('Kamera ve mikrofona erişilemedi', 'err'); localStream = new MediaStream(); micOn = false; camOn = false; }
    }
    self.video.srcObject = localStream;
    self.setCam(camOn && localStream.getVideoTracks().length > 0);
    attachMeter(self, localStream);
    if (!rafMeter) meterLoop();
    refreshBtns();
    connect();
  }

  function connect() {
    const q = `mid=${mid}` + (guest ? `&token=${encodeURIComponent(guest.token)}` : '');
    ws = new WebSocket(`${wsBase()}/ws/meet?${q}`);
    ws.onmessage = ev => { let m; try { m = JSON.parse(ev.data); } catch { return; } onWs(m); };
    ws._ping = setInterval(() => send({ t: 'ping' }), 25000);
  }
  const send = m => { try { ws.send(JSON.stringify(m)); } catch { /* */ } };

  function onWs(m) {
    if (m.t === 'waiting') showWaiting(m.reason);
    else if (m.t === 'joined') enterRoom(m);
    else if (m.t === 'peer_join') { if (m.peer) addPeer(m.peer, true); }
    else if (m.t === 'peer_left') removePeer(m.cid);
    else if (m.t === 'signal') onSignal(m.from, m.data);
    else if (m.t === 'peer_state') peerState(m);
    else if (m.t === 'chat') addChat(m.name, m.text, m.from === selfCid);
    else if (m.t === 'chat_sys') addChat(null, m.text, false, true);
    else if (m.t === 'file') addFileRow(m.file, true);
    else if (m.t === 'dm') onDm(m);
    else if (m.t === 'wait_list') renderWaitList(m.list);
    else if (m.t === 'denied') { toast('Katılım isteğiniz kabul edilmedi', 'err'); leave(false); }
    else if (m.t === 'kicked') { toast('Toplantıdan çıkarıldınız', 'err'); leave(false); }
    else if (m.t === 'force_mute') { if (micOn) toggleMic(); toast('Toplantı sahibi sizi sessize aldı'); }
    else if (m.t === 'ended') { toast('Toplantı sona erdi'); leave(false); }
    else if (m.t === 'error') toast(m.error || 'Bağlantı hatası', 'err');
  }

  function showWaiting(reason) {
    waitScreen.hidden = false;
    clear(waitScreen, h('div', { class: 'vm-wait-card' },
      h('div', { class: 'vm-wait-ring' }, avatar({ full_name: myName, photo: myPhoto }, 'lg')),
      h('b', { class: 'vm-wait-title' }, opts.title || 'Toplantı'),
      h('p', null, reason === 'admit' ? 'Toplantı sahibinin sizi içeri almasını bekliyorsunuz…' : 'Toplantı henüz başlamadı. Başladığında otomatik olarak katılacaksınız.'),
      h('div', { class: 'vm-dots' }, h('i'), h('i'), h('i')),
      h('button', { class: 'vm-ghostbtn', type: 'button', onclick: () => leave(false) }, 'Vazgeç')));
  }

  function enterRoom(m) {
    waitScreen.hidden = true;
    selfCid = m.self; isHost = m.is_host; if (m.pid) myPid = m.pid;
    if (m.meeting?.code) opts.code = m.meeting.code;
    if (m.meeting?.invite_text) opts.invite_text = m.meeting.invite_text;
    titleEl.textContent = m.meeting?.title || opts.title || 'Toplantı';
    root.classList.toggle('is-host', isHost);
    for (const p of m.peers || []) addPeer(p, false);
    startTimer(m.meeting);
    if (m.meeting?.record) startRecording();
    send({ t: 'state', muted: !micOn, cam: camOn });
  }

  function startTimer(meet) {
    const t0 = Date.now();
    const base = meet?.started_at && meet?.now ? Math.max(0, (new Date(meet.now) - new Date(meet.started_at)) / 1000) : 0;
    const out = timer.querySelector('span');
    clearInterval(timerId);
    const tick = () => {
      const s = Math.floor(base + (Date.now() - t0) / 1000);
      const hh = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = s % 60;
      out.textContent = hh ? `${hh}:${pad(mm)}:${pad(ss)}` : `${pad(mm)}:${pad(ss)}`;
    };
    tick(); timerId = setInterval(tick, 1000);
  }

  // --------- WebRTC mesh (mevcut akranlar yeni gelene offer başlatır) ---------
  function ensurePc(cid, initiator) {
    let e = peers.get(cid);
    if (e) return e;
    const pc = new RTCPeerConnection(ICE);
    const t = tile({ name: '…' });
    stage.append(t.el);
    e = { pc, t, info: {}, vsender: null };
    peers.set(cid, e);
    layout();
    for (const track of localStream.getTracks()) { const s = pc.addTrack(track, localStream); if (track.kind === 'video') e.vsender = s; }
    // Kamerası olmayan katılımcı için bile bir video hattı (transceiver) ayrılır ki ekran paylaşımı herkese ulaşsın (bug fix)
    if (!e.vsender) e.vsender = pc.addTransceiver('video', { direction: 'sendrecv' }).sender;
    if (screenTrack) e.vsender.replaceTrack(screenTrack);
    pc.onicecandidate = ev => { if (ev.candidate) send({ t: 'signal', to: cid, data: { ice: ev.candidate } }); };
    pc.ontrack = ev => { t.video.srcObject = ev.streams[0]; if (e.info.cam !== false || e.info.sharing) t.setCam(true); attachMeter(t, ev.streams[0]); };
    if (initiator) pc.onnegotiationneeded = async () => {
      try { await pc.setLocalDescription(await pc.createOffer()); send({ t: 'signal', to: cid, data: { sdp: pc.localDescription } }); } catch { /* */ }
    };
    return e;
  }
  function addPeer(p, initiator) {
    const e = ensurePc(p.cid, initiator);
    e.info = { ...e.info, ...p };
    e.t.setInfo(p); e.t.setMuted(p.muted); e.t.setHand(p.hand);
    if (p.cam === false) e.t.setCam(false);
    renderPeople();
  }
  function removePeer(cid) {
    const e = peers.get(cid); if (!e) return;
    try { e.pc.close(); } catch { /* */ }
    e.t.el.remove(); peers.delete(cid); layout(); renderPeople();
    if (pinned.has(cid)) { if (dmPeer === cid) { dmPanel.el.hidden = true; dmPeer = null; } renderPins(); }
  }
  async function onSignal(from, data) {
    const e = ensurePc(from, false);
    try {
      if (data.sdp) {
        await e.pc.setRemoteDescription(data.sdp);
        if (data.sdp.type === 'offer') { await e.pc.setLocalDescription(await e.pc.createAnswer()); send({ t: 'signal', to: from, data: { sdp: e.pc.localDescription } }); }
      } else if (data.ice) await e.pc.addIceCandidate(data.ice);
    } catch { /* */ }
  }
  function peerState(m) {
    if (m.cid === selfCid) { selfHandSeq = m.hand_seq || 0; renderPeople(); return; }   // kendi sıra numaramı yakala
    const e = peers.get(m.cid); if (!e) return;
    const wasHand = e.info.hand;
    e.info = { ...e.info, ...m };
    e.t.setMuted(m.muted); e.t.setHand(m.hand);
    e.t.setCam(m.cam || m.sharing);
    e.t.el.classList.toggle('sharing', !!m.sharing);
    if (m.hand && !wasHand) toast(t('{name} el kaldırdı ✋', { name: e.info.name || 'Bir katılımcı' }));
    layout(); renderPeople();
  }
  function layout() {
    const n = peers.size;
    stage.dataset.n = n === 0 ? '0' : n === 1 ? '1' : n === 2 ? '2' : n <= 4 ? '4' : n <= 6 ? '6' : 'many';
    self.el.classList.toggle('alone', n === 0);
    countEl.querySelector('span').textContent = String(n + 1);
    // ekran paylaşan kişi öne alınır
    for (const e of peers.values()) e.t.el.classList.toggle('spot', e.t.el.classList.contains('sharing'));
  }

  // --------- Kontroller ---------
  function refreshBtns() {
    setIcon(btnMic, micOn ? 'mic' : 'micOff'); btnMic.classList.toggle('off', !micOn);
    setIcon(btnCam, camOn ? 'cam' : 'camOff'); btnCam.classList.toggle('off', !camOn);
    btnHand.classList.toggle('on', hand); btnScreen.classList.toggle('on', !!screenTrack);
    self.setMuted(!micOn); self.setHand(hand);
  }
  function toggleMic() { micOn = !micOn; localStream.getAudioTracks().forEach(t => { t.enabled = micOn; }); refreshBtns(); send({ t: 'state', muted: !micOn }); }
  function toggleCam() {
    if (!localStream.getVideoTracks().length) { toast('Kamera bulunamadı', 'err'); return; }
    camOn = !camOn; localStream.getVideoTracks().forEach(t => { t.enabled = camOn; });
    self.setCam(camOn || !!screenTrack); refreshBtns(); send({ t: 'state', cam: camOn });
  }
  function toggleHand() { hand = !hand; refreshBtns(); send({ t: 'state', hand }); }
  async function toggleScreen() {
    if (screenTrack) { stopScreen(); return; }
    if (!navigator.mediaDevices?.getDisplayMedia) { toast('Bu cihaz ekran paylaşımını desteklemiyor', 'err'); return; }
    try {
      const ds = await navigator.mediaDevices.getDisplayMedia({ video: true });
      screenTrack = ds.getVideoTracks()[0];
      for (const e of peers.values()) { try { await e.vsender?.replaceTrack(screenTrack); } catch { /* */ } }
      self.video.srcObject = new MediaStream([screenTrack]); self.setCam(true);
      screenTrack.onended = stopScreen;
      refreshBtns(); send({ t: 'state', sharing: true, cam: true });
    } catch { /* kullanıcı vazgeçti */ }
  }
  function stopScreen() {
    if (!screenTrack) return;
    try { screenTrack.stop(); } catch { /* */ }
    screenTrack = null;
    const cam = localStream.getVideoTracks()[0] || null;
    for (const e of peers.values()) { try { e.vsender?.replaceTrack(cam); } catch { /* */ } }
    self.video.srcObject = localStream; self.setCam(camOn);
    refreshBtns(); send({ t: 'state', sharing: false, cam: camOn });
  }
  function moreMenu() {
    const close = () => sheet.remove();
    const item = (icon, label, fn, on) => h('button', { class: `vm-sheet-item ${on ? 'on' : ''}`, type: 'button', onclick: () => { close(); fn(); } },
      h('span', { class: 'vm-sheet-ic' }, ic(icon)), h('span', null, label));
    const sheet = h('div', { class: 'vm-sheet-back', onclick: e => { if (e.target === sheet) close(); } },
      h('div', { class: 'vm-sheet' }, h('div', { class: 'vm-grab' }),
        item('screen', screenTrack ? 'Paylaşımı durdur' : 'Ekran paylaş', toggleScreen, !!screenTrack),
        item('hand', hand ? 'Eli indir' : 'El kaldır', toggleHand, hand),
        item('chat', 'Sohbet', () => togglePanel('chat')),
        item('people', 'Katılımcılar', () => togglePanel('people')),
        item('link', 'Davet bilgilerini kopyala', () => { const l = opts.invite_text || `${location.origin}/m/${encodeURIComponent(opts.code || '')}`; navigator.clipboard?.writeText(l); toast('Davet bilgileri kopyalandı'); })));
    root.append(sheet);
  }

  // --------- Sohbet / katılımcılar ---------
  function sendChat() { const t = chatInput.value.trim(); if (!t) return; chatInput.value = ''; send({ t: 'chat', text: t }); }
  function addChat(name, text, mine, sys) {
    if (sys) { chatList.append(h('div', { class: 'vm-chat-sys' }, text)); }
    else {
      const time = new Date().toLocaleTimeString('tr', { hour: '2-digit', minute: '2-digit' });
      chatList.append(h('div', { class: `vm-msg ${mine ? 'mine' : ''}` },
        !mine && name ? h('b', null, name) : null,
        h('span', { class: 'vm-msg-t' }, text),
        h('span', { class: 'vm-msg-time' }, time)));
    }
    chatList.scrollTop = chatList.scrollHeight;
    if (chatPanel.el.hidden && !sys) { unreadChat++; btnChat.dataset.badge = String(unreadChat); }
  }
  function renderPeople() {
    // El kaldırma sırası (hand_seq'e göre)
    const queue = [];
    if (hand) queue.push({ name: t('{name} (siz)', { name: myName }), seq: selfHandSeq || 1e9, me: true });
    for (const [, e] of peers) if (e.info.hand) queue.push({ name: e.info.name, seq: e.info.hand_seq || 1e9 });
    queue.sort((a, b) => a.seq - b.seq);
    const queueBox = queue.length ? h('div', { class: 'vm-handq' },
      h('div', { class: 'vm-handq-h' }, ic('hand'), t('Söz sırası · {n}', { n: queue.length })),
      ...queue.map((q, i) => h('div', { class: `vm-handq-row ${q.me ? 'me' : ''}` },
        h('span', { class: 'vm-handq-n' }, String(i + 1)), h('span', { class: 'grow' }, q.name)))) : null;
    const addBtn = isHost ? h('button', { class: 'btn sm primary vm-addppl', type: 'button', onclick: addStaffModal }, ic('plus'), 'Personel ekle') : null;
    const rows = [h('div', { class: 'vm-person' }, avatar({ full_name: myName, photo: myPhoto }, 'sm'),
      h('span', { class: 'grow' }, t('{name} (siz)', { name: myName })), isHost ? h('span', { class: 'vm-tag' }, 'Sahip') : null)];
    for (const [cid, e] of peers) {
      const p = e.info;
      rows.push(h('div', { class: 'vm-person' }, avatar({ full_name: p.name, photo: p.photo }, 'sm'),
        h('span', { class: 'grow' }, p.name || '…'),
        p.hand ? h('span', { class: 'vm-person-ic hand' }, ic('hand')) : null,
        p.muted ? h('span', { class: 'vm-person-ic' }, ic('micOff')) : null,
        h('button', { class: `vm-round sm ${pinned.has(cid) ? 'on' : ''}`, type: 'button', title: pinned.has(cid) ? 'Sabitlemeyi kaldır' : 'Sabitle · özel sohbet', onclick: () => togglePin(cid) }, ic('pin')),
        isHost ? h('button', { class: 'vm-round sm', type: 'button', title: 'Sessize al', onclick: () => send({ t: 'mute_peer', cid }) }, ic('micOff')) : null,
        isHost ? h('button', { class: 'vm-round sm danger', type: 'button', title: 'Toplantıdan çıkar', onclick: async () => {
          if (await confirmDialog('Katılımcıyı çıkar', t('{name} toplantıdan çıkarılsın mı?', { name: p.name }), { okLabel: 'Çıkar', danger: true })) send({ t: 'kick', cid });
        } }, ic('close')) : null));
    }
    clear(peopleList, addBtn, queueBox, rows);
  }
  function renderWaitList(list) {
    if (!isHost || !list?.length) { clear(waitBox); delete btnPeople.dataset.badge; return; }
    clear(waitBox, h('div', { class: 'vm-wait-h' }, t('Bekleme odası · {n}', { n: list.length })),
      ...list.map(w => h('div', { class: 'vm-wait-row' }, avatar({ full_name: w.name }, 'sm'),
        h('span', { class: 'grow' }, w.name, w.is_external ? h('small', null, ' · misafir') : null),
        h('button', { class: 'vm-mini primary', type: 'button', onclick: () => send({ t: 'admit', cid: w.cid }) }, 'Kabul et'),
        h('button', { class: 'vm-mini', type: 'button', onclick: () => send({ t: 'deny', cid: w.cid }) }, 'Reddet'))));
    btnPeople.dataset.badge = String(list.length);
    toast(t('{name} toplantıya katılmak istiyor', { name: list[list.length - 1].name }));
  }
  const PANELS = () => ({ chat: chatPanel.el, people: peoplePanel.el, files: filesPanel.el, dm: dmPanel.el });
  function togglePanel(which) {
    const panels = PANELS(); const target = panels[which];
    for (const k in panels) if (panels[k] !== target) panels[k].hidden = true;
    target.hidden = !target.hidden;
    if (target.hidden) return;
    if (which === 'chat') { unreadChat = 0; delete btnChat.dataset.badge; setTimeout(() => chatInput.focus(), 50); }
    if (which === 'people') renderPeople();
    if (which === 'files') loadFiles();
  }

  // --------- Toplantıya personel ekle (sahibi) ---------
  async function addStaffModal() {
    let users;
    try { users = await api.get('/api/meet/invitees'); } catch (err) { return toastError(err); }
    const here = new Set([...peers.values()].map(e => e.info.user_id).filter(Boolean));
    if (opts.user?.id) here.add(opts.user.id);
    users = users.filter(u => !here.has(u.id));
    if (!users.length) { toast('Eklenecek başka kişi yok', 'err'); return; }
    const picked = new Set();
    const list = h('div', { class: 'vm-invite-list' });
    const draw = () => clear(list, users.map(u => h('label', { class: `vm-user ${picked.has(u.id) ? 'on' : ''}` },
      h('input', { type: 'checkbox', checked: picked.has(u.id), onchange: e => { e.target.checked ? picked.add(u.id) : picked.delete(u.id); draw(); } }),
      avatar(u, 'sm'), h('span', null, u.full_name))));
    draw();
    modal({ title: 'Toplantıya personel ekle', body: h('div', null,
      h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Seçtiğiniz kişilere toplantı daveti bildirimi gider.'), list),
      actions: [{ label: 'Vazgeç' }, { label: 'Davet et', class: 'primary', onClick: async () => {
        if (!picked.size) throw new Error('En az bir kişi seçin');
        const r = await api.post(`/api/meet/${mid}/invite`, { user_ids: [...picked] });
        toast(t('{n} kişi davet edildi', { n: r.added }), 'success');
      } }] });
  }

  // --------- Dosya kutusu ---------
  async function loadFiles() {
    if (guest) return;   // dış katılımcı listeyi çekemez; yüklenenleri canlı görür
    try { const list = await api.get(`/api/meet/${mid}/files`); clear(filesList); list.forEach(f => addFileRow(f, false)); }
    catch { /* */ }
  }
  function fileDownUrl(f) { return `/api/meet/${mid}/file?fid=${f.id}` + (guest ? `&token=${encodeURIComponent(guest.token)}` : ''); }
  function addFileRow(f, live) {
    if (filesList.querySelector(`[data-fid="${f.id}"]`)) return;
    filesList.append(h('a', { class: 'vm-file', 'data-fid': f.id, href: fileDownUrl(f), target: '_blank', rel: 'noopener', download: f.name },
      h('span', { class: 'vm-file-ic' }, ic('download')),
      h('span', { class: 'grow' }, h('b', null, f.name), h('small', null, `${f.by || ''}`))));
    if (live && filesPanel.el.hidden) { btnFiles.dataset.badge = String((+btnFiles.dataset.badge || 0) + 1); }
  }
  async function uploadFiles(fileListObj) {
    const files = [...(fileListObj || [])]; fileInput.value = '';
    for (const file of files) {
      const fd = new FormData();
      fd.append('file', file); fd.append('pid', String(myPid || 0));
      if (guest) fd.append('token', guest.token);
      try { await fetch(`/api/meet/${mid}/files`, { method: 'POST', body: fd, credentials: 'same-origin' }); }
      catch { toast('Dosya yüklenemedi', 'err'); }
    }
  }

  // --------- Kişi sabitleme + özel sohbet (DM) ---------
  function togglePin(cid) {
    if (pinned.has(cid)) pinned.delete(cid); else pinned.add(cid);
    renderPins(); renderPeople();
  }
  function renderPins() {
    clear(pinBubbles, [...pinned].map(cid => {
      const e = peers.get(cid); if (!e) { pinned.delete(cid); return null; }
      const n = dmUnread.get(cid) || 0;
      const b = h('button', { class: 'vm-pin', type: 'button', title: t('{name} · özel sohbet', { name: e.info.name }), onclick: () => openDm(cid) },
        avatar({ full_name: e.info.name, photo: e.info.photo }, 'sm'),
        n ? h('span', { class: 'vm-pin-badge' }, String(n)) : null,
        h('button', { class: 'vm-pin-x', type: 'button', title: 'Kaldır', onclick: ev => { ev.stopPropagation(); togglePin(cid); } }, ic('close')));
      return b;
    }).filter(Boolean));
  }
  function openDm(cid) {
    const e = peers.get(cid); if (!e) return;
    dmPeer = cid; dmUnread.set(cid, 0); renderPins();
    dmTitle.textContent = t('{name} · özel', { name: e.info.name });
    const msgs = dmThreads.get(cid) || [];
    clear(dmList, msgs.map(x => dmBubble(x)));
    for (const k in PANELS()) PANELS()[k].hidden = PANELS()[k] !== dmPanel.el;
    dmPanel.el.hidden = false;
    dmList.scrollTop = dmList.scrollHeight;
    setTimeout(() => dmInput.focus(), 50);
  }
  function dmBubble(x) {
    return h('div', { class: `vm-msg ${x.mine ? 'mine' : ''}` }, h('span', { class: 'vm-msg-t' }, x.text), h('span', { class: 'vm-msg-time' }, x.time));
  }
  function pushDm(cid, x) { const arr = dmThreads.get(cid) || []; arr.push(x); dmThreads.set(cid, arr); }
  function sendDm() {
    const text = dmInput.value.trim(); if (!text || !dmPeer) return;
    dmInput.value = '';
    const x = { mine: true, text, time: new Date().toLocaleTimeString('tr', { hour: '2-digit', minute: '2-digit' }) };
    pushDm(dmPeer, x); dmList.append(dmBubble(x)); dmList.scrollTop = dmList.scrollHeight;
    send({ t: 'dm', to: dmPeer, text });
  }
  function onDm(m) {
    const x = { mine: false, text: m.text, time: new Date().toLocaleTimeString('tr', { hour: '2-digit', minute: '2-digit' }) };
    pushDm(m.from, x);
    if (!pinned.has(m.from)) { pinned.add(m.from); }   // yazan kişi otomatik sabitlenir
    if (dmPeer === m.from && !dmPanel.el.hidden) { dmList.append(dmBubble(x)); dmList.scrollTop = dmList.scrollHeight; }
    else { dmUnread.set(m.from, (dmUnread.get(m.from) || 0) + 1); toast(t('{name}: özel mesaj', { name: m.name })); }
    renderPins();
  }

  // --------- Kayıt (kendi mikrofonu) ---------
  async function startRecording() {
    if (recorder) return;
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t));
      recorder = new MediaRecorder(mic, mime ? { mimeType: mime } : undefined);
      recorder._mic = mic;
      recorder.ondataavailable = e => { if (e.data && e.data.size) recBlobs.push(e.data); };
      recorder.start(2000);
      recording = true; timer.classList.add('rec'); timer.title = 'Kayıt yapılıyor'; recBanner.hidden = false;
    } catch { /* kayıt alınamadı */ }
  }
  async function uploadRecording() {
    if (!recorder) return;
    const r = recorder; recorder = null;
    await new Promise(res => { r.onstop = res; try { r.stop(); } catch { res(); } setTimeout(res, 1500); });
    try { r._mic.getTracks().forEach(t => t.stop()); } catch { /* */ }
    if (!recBlobs.length) return;
    const blob = new Blob(recBlobs, { type: recBlobs[0].type || 'audio/webm' });
    recBlobs = [];
    const fd = new FormData();
    fd.append('file', new File([blob], `meet-${mid}.${blob.type.includes('mp4') ? 'm4a' : 'webm'}`, { type: blob.type }));
    fd.append('pid', String(myPid || 0));
    if (guest) fd.append('token', guest.token);
    try { await fetch(`/api/meet/${mid}/recording`, { method: 'POST', body: fd, credentials: 'same-origin' }); } catch { /* */ }
  }

  let left = false;
  async function leave(confirmIt) {
    if (left) return;
    if (confirmIt) {
      const ok = await confirmDialog(isHost ? 'Toplantıyı bitir' : 'Toplantıdan ayrıl',
        isHost ? 'Toplantı herkes için sona erecek.' : 'Toplantıdan ayrılmak istiyor musunuz?',
        { okLabel: isHost ? 'Toplantıyı Bitir' : 'Ayrıl', danger: true });
      if (!ok) return;
      if (isHost) send({ t: 'end' });
    }
    left = true;
    await uploadRecording();
    cleanup();
    if (guest) {
      clear(host, h('div', { class: 'vm-guest' }, h('div', { class: 'vm-guest-card' },
        h('div', { class: 'vm-created-ic' }, ic('video')), h('b', { class: 'vm-guest-title' }, 'Toplantıdan ayrıldınız'),
        h('p', { class: 'muted' }, 'Katıldığınız için teşekkürler. Bu pencereyi kapatabilirsiniz.'))));
    } else location.hash = '#/meet';
  }
  function cleanup() {
    clearInterval(timerId);
    if (rafMeter) { cancelAnimationFrame(rafMeter); rafMeter = null; }
    try { audioCtx?.close(); } catch { /* */ }
    try { clearInterval(ws?._ping); ws?.close(); } catch { /* */ }
    for (const e of peers.values()) { try { e.pc.close(); } catch { /* */ } }
    peers.clear();
    try { localStream?.getTracks().forEach(t => t.stop()); } catch { /* */ }
    try { screenTrack?.stop(); } catch { /* */ }
  }

  stop = () => { if (!left) { left = true; uploadRecording(); cleanup(); } };   // SPA'da başka sayfaya geçilirse
  start();
}

let stop = () => {};
export function destroy() { try { stop(); } catch { /* */ } stop = () => {}; }

// ============================ DIŞ KATILIMCI (/m/{code}) ============================
export async function guestEntry(code) {
  const root = document.getElementById('app') || document.body;
  let info;
  try { info = await api.get(`/api/meet/public/${encodeURIComponent(code)}`); }
  catch {
    clear(root, h('div', { class: 'vm-guest' }, h('div', { class: 'vm-guest-card' },
      h('div', { class: 'vm-created-ic' }, ic('video')), h('b', { class: 'vm-guest-title' }, 'Toplantı bulunamadı'),
      h('p', { class: 'muted' }, 'Link geçersiz ya da toplantı sona ermiş.'))));
    return;
  }
  const preview = h('video', { autoplay: true, playsinline: true, muted: true });
  const prevWrap = h('div', { class: 'vm-preview camoff' }, preview, h('div', { class: 'vm-preview-off' }, ic('camOff'), h('span', null, 'Kamera kapalı')));
  let pstream = null;
  navigator.mediaDevices?.getUserMedia({ video: { facingMode: 'user' }, audio: false })
    .then(s => { pstream = s; preview.srcObject = s; prevWrap.classList.remove('camoff'); }).catch(() => {});
  const name = h('input', { class: 'input', placeholder: 'Adınız Soyadınız', autocomplete: 'name' });
  const go = h('button', { class: 'vm-join', type: 'button' }, 'Toplantıya Katıl');
  const brand = h('div', { class: 'vm-guest-brand' }, info.logo_url ? h('img', { src: info.logo_url, alt: info.company || '' }) : null, h('span', null, info.company || ''));
  clear(root, h('div', { class: 'vm-guest' }, h('div', { class: 'vm-guest-card' },
    brand,
    prevWrap,
    h('div', { class: 'vm-guest-meta' }, h('b', { class: 'vm-guest-title' }, info.title),
      (info.when || []).length ? h('small', { class: 'muted' }, info.when[0]) : null,
      info.status === 'DEVAM' ? h('span', { class: 'vm-live' }, h('i'), 'Şu an devam ediyor') : h('small', { class: 'muted' }, 'Henüz başlamadı — katılınca beklersiniz')),
    h('label', { class: 'field' }, h('span', null, 'Görünecek adınız'), name),
    go)));
  name.addEventListener('keydown', e => { if (e.key === 'Enter') go.click(); });
  go.addEventListener('click', async () => {
    const nm = name.value.trim();
    if (!nm) { toast('Lütfen adınızı girin', 'err'); name.focus(); return; }
    go.disabled = true;
    try {
      const g = await api.post(`/api/meet/guest/${encodeURIComponent(code)}`, { name: nm });
      try { pstream?.getTracks().forEach(t => t.stop()); } catch { /* */ }
      openRoom(null, { mid: g.meeting_id, guest: { token: g.token, name: g.name, pid: g.pid }, title: info.title, code });
    } catch (err) { toastError(err); go.disabled = false; }
  });
}
