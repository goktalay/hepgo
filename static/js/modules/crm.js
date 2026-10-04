// Firma Yönetimi ortak parçaları: sekme çubuğu, notlar, takvim (randevu / hatırlatma + toplantılar) ve evrak listesi.
// Konu (subject): company | person | user — firma detayı ve Rehber kişi / kullanıcı detayı aynı parçaları kullanır.
import { segIcon } from '../segicons.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import {
  clear, companyName, confirmDialog, dateTimeInput, field, fmtDate, fmtDateTime, h, modal, peoplePicker, pref, segmented, setPref, shortCompany, svgIcon, t,
  toast, toastError,
} from '../ui.js';
import { KINDS, OCR, badgeOf, size, thumbOf } from './documents.js';

// ---------- Sekmeler: tanım [{ key, label, count?, render: () => Promise<Element>|Element }]
export function tabView(defs, current, onChange) {
  let active = defs.some(d => d.key === current) ? current : defs[0].key;
  const bar = h('div', { class: 'tabbar', role: 'tablist' });
  const body = h('div', { class: 'tab-body' });
  const show = async key => {
    active = key;
    bar.replaceChildren(...defs.map(d => h('button', {
      class: `tab ${d.key === key ? 'on' : ''}`, role: 'tab', type: 'button', 'aria-selected': d.key === key ? 'true' : 'false',
      onclick: () => { if (d.key !== active) show(d.key); },
    }, segIcon(d.label), d.label, d.count != null ? h('span', { class: 'tab-n' }, d.count) : null)));
    onChange?.(key);
    clear(body, h('div', { class: 'muted small', style: { padding: '12px' } }, 'Yükleniyor…'));
    try {
      const el = await defs.find(d => d.key === key).render();
      if (active === key) clear(body, el);
    } catch (err) {
      clear(body, h('div', { class: 'empty' }, err.message));
    }
  };
  show(active);
  return h('div', { class: 'card tabs-card' }, bar, body);
}

// ---------- Evrak listesi
export function docList(docs, emptyText = 'Bağlı (görebildiğiniz) evrak yok') {
  if (!docs.length) return h('div', { class: 'empty small' }, emptyText);
  return h('div', { class: 'doc-list compact' }, docs.map(d => h('a', { class: 'doc-row', href: `#/documents/${d.id}` },
    thumbOf(d),
    h('div', { class: 'grow' },
      h('div', { class: 'doc-title' }, h('b', null, d.title), ' ', badgeOf(KINDS, d.kind)),
      h('div', { class: 'small muted' }, [fmtDate(d.doc_date || d.uploaded_at), size(d.size),
        (d.companies || []).map(c => c.name).join(', ')].filter(Boolean).join(' · '))),
    badgeOf(OCR, d.ocr_status))));
}

// ---------- Notlar: konu hakkında birden çok not; en yeni üstte. Yalnızca yazan (ya da yönetici) düzenler / siler.
export function notesPanel(subject, subjectId, ctx) {
  const list = h('div', { class: 'note-list' });
  const text = h('textarea', { class: 'input', rows: 3, placeholder: 'Yeni not yazın…' });
  const add = h('button', { class: 'btn primary', type: 'button' }, svgIcon(icons.plus), 'Not Ekle');
  const isAdmin = ctx.user.roles.includes('Sistem Yöneticisi');
  const load = async () => {
    const notes = await api.get(`/api/crm/notes?subject=${subject}&subject_id=${subjectId}`);
    clear(list, notes.length ? notes.map(n => {
      const mine = n.created_by === ctx.user.id || isAdmin;
      const body = h('div', { class: 'note-body' }, n.body);
      const edit = () => {
        const ta = h('textarea', { class: 'input', rows: 4 }, n.body);
        modal({
          title: 'Notu düzenle', body: ta,
          actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
            if (!ta.value.trim()) throw new Error('Not boş olamaz');
            await api.put(`/api/crm/notes/${n.id}`, { body: ta.value });
            toast('Not güncellendi');
            load();
          } }],
        });
      };
      const del = async () => {
        if (!await confirmDialog('Notu sil', 'Bu not silinsin mi?', { okLabel: 'Sil', danger: true })) return;
        try { await api.del(`/api/crm/notes/${n.id}`); toast('Not silindi'); load(); } catch (err) { toastError(err); }
      };
      return h('div', { class: 'note-item' },
        h('div', { class: 'note-meta' }, h('b', null, n.created_by_name || '—'), ` · ${fmtDateTime(n.created_at)}`,
          n.updated_at ? h('span', { class: 'muted' }, t(' · düzenlendi {d}', { d: fmtDateTime(n.updated_at) })) : null,
          h('span', { class: 'grow' }),
          mine ? h('button', { class: 'btn sm ghost', onclick: edit }, 'Düzenle') : null,
          mine ? h('button', { class: 'btn sm ghost', onclick: del }, 'Sil') : null),
        body);
    }) : h('div', { class: 'empty small' }, 'Henüz not yok'));
  };
  add.addEventListener('click', async () => {
    if (!text.value.trim()) { toastError(new Error('Not boş olamaz')); return; }
    add.disabled = true;
    try {
      await api.post('/api/crm/notes', { subject, subject_id: subjectId, body: text.value });
      text.value = '';
      toast('Not eklendi');
      await load();
    } catch (err) { toastError(err); } finally { add.disabled = false; }
  });
  load().catch(toastError);
  return h('div', { class: 'notes-panel' },
    h('div', { class: 'note-add' }, text, h('div', { style: { display: 'flex', justifyContent: 'flex-end' } }, add)),
    list);
}

// ---------- Takvim
const pad2 = n => String(n).padStart(2, '0');
const ymd = d => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
const DAYS = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
export const EVENT_KINDS = { RANDEVU: ['Randevu', 'blue'], HATIRLATMA: ['Hatırlatma', 'yellow'], TOPLANTI: ['Toplantı', 'purple'], KISISEL: ['Mail / Hesap takvimi', 'green'] };
const kindBadge = k => h('span', { class: `badge ${EVENT_KINDS[k][1]}` }, EVENT_KINDS[k][0]);
const hm = iso => (iso ? iso.slice(11, 16) : '');

async function eventForm(subject, subjectId, e = {}, done) {
  const users = await api.get('/api/people');
  let kind = e.kind || 'RANDEVU';
  const title = h('input', { class: 'input', value: e.title || '', placeholder: 'Ör. Teklif görüşmesi / Numuneyi gönder' });
  const start = dateTimeInput({ value: e.starts_at });
  const end = dateTimeInput({ value: e.ends_at || (e.starts_at ? new Date(new Date(e.starts_at).getTime() + 3600e3).toISOString() : null) });
  const endField = field('Bitiş', end);
  const location = h('input', { class: 'input', value: e.location || '', placeholder: 'Ör. firma ofisi, çevrim içi' });
  const locField = field('Yer', location);
  const note = h('textarea', { class: 'input', rows: 3, placeholder: 'Açıklama (isteğe bağlı)' }, e.note || '');
  const who = peoplePicker(users, { selected: (e.users || []).map(u => u.id) });
  const startField = field('Başlangıç', start);
  const sync = () => {
    endField.hidden = locField.hidden = kind !== 'RANDEVU';
    startField.querySelector('label, .label')?.replaceChildren(kind === 'RANDEVU' ? 'Başlangıç' : 'Hatırlatma zamanı');
  };
  const kindSeg = segmented([['RANDEVU', 'Randevu'], ['HATIRLATMA', 'Hatırlatma']], kind, v => { kind = v; sync(); });
  sync();
  modal({
    title: e.id ? 'Takvim kaydını düzenle' : 'Takvime ekle',
    wide: true,
    body: h('div', null,
      h('div', { style: { marginBottom: '12px' } }, kindSeg),
      field('Başlık', title),
      h('div', { class: 'row' }, startField, endField),
      locField,
      field('Açıklama', note),
      field('Bizden katılan / hatırlatılacak kişiler', who, 'Seçilenlere ve size, zamanı gelince bildirim gider')),
    actions: [
      { label: 'Vazgeç' },
      { label: 'Kaydet', class: 'primary', onClick: async () => {
        if (!title.value.trim()) throw new Error('Başlık zorunlu');
        const body = { subject, subject_id: subjectId, kind, title: title.value.trim(), starts_at: start.getValue(),
          ends_at: kind === 'RANDEVU' ? end.getValue() : null, location: kind === 'RANDEVU' ? location.value.trim() || null : null,
          note: note.value.trim() || null, user_ids: who.getIds() };
        if (e.id) await api.put(`/api/crm/events/${e.id}`, body); else await api.post('/api/crm/events', body);
        toast('Takvim kaydı kaydedildi');
        done?.();
      } },
    ],
  });
}

function eventInfo(subject, subjectId, e, ctx, reload) {
  const crm = ctx.user.modules.includes('companies');
  const personLink = p => (crm ? h('a', { href: `#/companies/rehber/person/${p.id}` }, p.full_name) : p.full_name);
  const joinEls = els => els.flatMap((el, i) => (i ? [', ', el] : [el]));
  if (e.kind === 'KISISEL') {   // mail daveti / Google Takvim / Outlook: yalnız sahibi görür, kaynağında düzenlenir
    return modal({
      title: e.title,
      body: h('dl', { class: 'kv event-kv' }, h('dt', null, 'Kaynak'), h('dd', null, kindBadge('KISISEL'), ' ', e.source || ''),
        h('dt', null, 'Zaman'), h('dd', null, e.all_day ? `${fmtDateTime(e.starts_at).slice(0, 10)} · tüm gün` : fmtDateTime(e.starts_at) + (e.ends_at ? ` – ${hm(e.ends_at)}` : '')),
        e.location ? [h('dt', null, 'Yer'), h('dd', null, e.location)] : null,
        e.note ? [h('dt', null, 'Açıklama'), h('dd', { class: 'event-note' }, e.note)] : null),
      actions: [{ label: 'Kapat', class: 'primary' }],
    });
  }
  if (e.readonly) {   // toplantı: Firma Yönetimi'nde düzenlenir
    return modal({
      title: e.title,
      wide: true,
      body: h('dl', { class: 'kv event-kv' }, h('dt', null, 'Tür'), h('dd', null, kindBadge('TOPLANTI')),
        h('dt', null, 'Zaman'), h('dd', null, fmtDateTime(e.starts_at)),
        h('dt', null, 'Firma'), h('dd', null, crm ? h('a', { href: `#/companies/${e.company_id}/meetings`, title: e.company_name }, subject === 'user' ? shortCompany(e.company_name) : e.company_name)
          : companyName(e.company_name)),
        e.address ? [h('dt', null, 'Adres'), h('dd', null, e.address)] : null,
        e.location ? [h('dt', null, 'Yer'), h('dd', null, e.location)] : null,
        h('dt', null, 'Görüşülen kişiler'), h('dd', null, e.people?.length
          ? joinEls(e.people.map(p => h('span', null, personLink(p), p.title ? h('span', { class: 'muted' }, ` (${p.title})`) : null))) : '—'),
        h('dt', null, 'Bizden katılanlar'), h('dd', null, e.users?.map(u => u.full_name).join(', ') || '—'),
        e.other_attendees ? [h('dt', null, 'Diğer katılımcılar'), h('dd', null, e.other_attendees)] : null,
        h('dt', null, 'Görüşme notu'), h('dd', { class: 'event-note' }, e.note || h('span', { class: 'muted' }, 'Not girilmemiş'))),
      actions: [{ label: 'Kapat', class: 'primary' }],
    });
  }
  const mine = e.created_by === ctx.user.id || ctx.user.roles.includes('Sistem Yöneticisi');
  const participant = mine || e.users.some(u => u.id === ctx.user.id);
  modal({
    title: e.title,
    body: h('dl', { class: 'kv' },
      h('dt', null, 'Tür'), h('dd', null, kindBadge(e.kind), e.done_at ? h('span', { class: 'badge green', style: { marginLeft: '6px' } }, 'Tamamlandı') : null),
      h('dt', null, e.kind === 'RANDEVU' ? 'Zaman' : 'Hatırlatma'), h('dd', null, fmtDateTime(e.starts_at) + (e.ends_at ? ` – ${hm(e.ends_at)}` : '')),
      e.location ? [h('dt', null, 'Yer'), h('dd', null, e.location)] : null,
      e.subject_name ? [h('dt', null, e.subject_type === 'person' || e.subject_type === 'user' ? 'Görüşülen kişi' : 'Firma'),
        h('dd', null, e.subject_href ? h('a', { href: e.subject_href }, e.subject_name) : e.subject_name)] : null,
      e.note ? [h('dt', null, e.kind === 'RANDEVU' ? 'Görüşme notu' : 'Açıklama'), h('dd', { class: 'event-note' }, e.note)] : null,
      h('dt', null, e.kind === 'RANDEVU' ? 'Bizden katılanlar' : 'Hatırlatılacaklar'), h('dd', null, e.users.map(u => u.full_name).join(', ') || '—'),
      h('dt', null, 'Ekleyen'), h('dd', null, `${e.created_by_name || '—'} · ${fmtDateTime(e.created_at)}`)),
    actions: [
      mine ? { label: 'Sil', class: 'danger', onClick: async () => {
        if (!await confirmDialog('Kaydı sil', t('{title} silinsin mi?', { title: e.title }), { okLabel: 'Sil', danger: true })) return false;
        await api.del(`/api/crm/events/${e.id}`); toast('Takvim kaydı silindi'); reload();
      } } : null,
      'spacer',
      participant && e.kind === 'HATIRLATMA' ? { label: e.done_at ? 'Tamamlanmadı yap' : 'Tamamlandı', class: e.done_at ? '' : 'success', onClick: async () => {
        await api.post(`/api/crm/events/${e.id}/done`); reload();
      } } : null,
      mine ? { label: 'Düzenle', onClick: () => { setTimeout(() => eventForm(subject, subjectId, e, reload)); } } : null,
      { label: 'Kapat', class: 'primary' },
    ].filter(Boolean),
  });
}

// mine: kişisel takvim (kullanıcı menüsü → Takvim): oluşturduğum / katıldığım tüm kayıtlar ve toplantılarım;
// yeni kayıt kişisel takvime (konu = kendim) eklenir.
// Takvim: Gün, Hafta (saat ızgarası), Ay, Yıl ve Ajanda (liste) görünümleri. Boş saate / güne tıklayınca yeni kayıt;
// kayda tıklayınca ayrıntı. Seçilen görünüm tarayıcıda hatırlanır.
const HOUR_PX = 48;
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const monday = d => addDays(d, -((d.getDay() + 6) % 7));
const LONG_DAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar'];

export function calendarPanel(subject, subjectId, ctx, { mine = false } = {}) {
  const today = new Date();
  let anchor = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  let mode = pref('cal.view', 'month');
  const title = h('b', { class: 'cal-title' });
  const body = h('div', { class: 'cal-body' });
  const upcoming = h('div', { class: 'cal-upcoming' });
  const newEvent = preset => eventForm(subject, subjectId, preset, load);
  const label = e => (e.subject_name ? `${e.title} · ${e.subject_name}` : e.kind === 'TOPLANTI' && mine ? `${e.title} · ${shortCompany(e.company_name)}` : e.title);
  const open = (e, ev) => {
    ev?.stopPropagation();
    if (e.birthday) return;   // doğum günü: salt bilgi, düzenlenmez
    if (e.link) { location.hash = e.link; return; }   // şirket içi toplantı: Kişisel → Toplantılar ayrıntısı
    eventInfo(subject, subjectId, e, ctx, load);
  };
  const chip = e => {
    const full = e.kind === 'TOPLANTI' && mine && !e.subject_name ? `${e.title} · ${e.company_name}` : label(e);
    const noTime = e.kind === 'HATIRLATMA' || e.kind === 'DOGUMGUNU';
    return h('button', { type: 'button', class: `cal-chip ${e.kind.toLowerCase()} ${e.done_at ? 'done' : ''}`, title: full, onclick: ev => open(e, ev) },
      !noTime || hm(e.starts_at) !== '00:00' ? h('span', { class: 'cal-time' }, hm(e.starts_at)) : null, label(e));
  };
  const range = () => {
    if (mode === 'day') return [anchor, addDays(anchor, 1)];
    if (mode === 'week') { const s0 = monday(anchor); return [s0, addDays(s0, 7)]; }
    if (mode === 'year') return [new Date(anchor.getFullYear(), 0, 1), new Date(anchor.getFullYear() + 1, 0, 1)];
    if (mode === 'agenda') return [anchor, addDays(anchor, 60)];
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const s0 = monday(first);
    return [s0, addDays(s0, 42)];
  };
  const titleText = () => {
    const d = anchor;
    if (mode === 'day') return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${LONG_DAYS[(d.getDay() + 6) % 7]}`;
    if (mode === 'week') {
      const s0 = monday(d), e0 = addDays(s0, 6);
      return s0.getMonth() === e0.getMonth() ? `${s0.getDate()}–${e0.getDate()} ${MONTHS[e0.getMonth()]} ${e0.getFullYear()}`
        : `${s0.getDate()} ${MONTHS[s0.getMonth()].slice(0, 3)} – ${e0.getDate()} ${MONTHS[e0.getMonth()].slice(0, 3)} ${e0.getFullYear()}`;
    }
    if (mode === 'year') return String(d.getFullYear());
    if (mode === 'agenda') return t('{d} itibarıyla 60 gün', { d: fmtDate(ymd(d)) });
    return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  };
  const byDayOf = events => {
    const m = new Map();
    for (const e of events) { const k = e.starts_at.slice(0, 10); if (!m.has(k)) m.set(k, []); m.get(k).push(e); }
    for (const l of m.values()) l.sort((x, y) => x.starts_at.localeCompare(y.starts_at));
    return m;
  };

  // ---------- Ay
  function drawMonth(byDay, start) {
    const cells = [];
    for (let i = 0; i < 42; i++) {
      const d = addDays(start, i), key = ymd(d), list = byDay.get(key) || [];
      const cell = h('div', { class: `cal-cell ${d.getMonth() !== anchor.getMonth() ? 'out' : ''} ${key === ymd(today) ? 'today' : ''}`, title: 'Bu güne kayıt eklemek için tıklayın' },
        h('button', { type: 'button', class: 'cal-day', title: 'Gün görünümü', onclick: ev => { ev.stopPropagation(); anchor = d; setMode('day'); } }, d.getDate()),
        list.slice(0, 3).map(chip),
        list.length > 3 ? h('button', { type: 'button', class: 'cal-more', onclick: ev => { ev.stopPropagation(); anchor = d; setMode('day'); } }, t('+{n} kayıt daha', { n: list.length - 3 })) : null);
      cell.addEventListener('click', () => newEvent({ starts_at: `${key}T09:00:00` }));
      cells.push(cell);
    }
    clear(body, h('div', { class: 'cal-grid' }, DAYS.map(d => h('div', { class: 'cal-head' }, d)), cells));
  }

  // ---------- Gün / Hafta: saat ızgarası
  function drawTime(byDay, start, days) {
    const cols = [];
    const allDay = [];
    for (let i = 0; i < days; i++) {
      const d = addDays(start, i), key = ymd(d), list = byDay.get(key) || [];
      const timed = list.filter(e => !(e.kind === 'HATIRLATMA' && hm(e.starts_at) === '00:00'));
      allDay.push(h('div', { class: 'cal-allday-cell' }, list.filter(e => !timed.includes(e)).map(chip)));
      // Çakışan kayıtlar yan yana şeritlere dağıtılır
      const lanes = [];
      const placed = timed.map(e => {
        const s0 = new Date(e.starts_at), en = e.ends_at ? new Date(e.ends_at) : new Date(s0.getTime() + 30 * 60e3);
        const top = (s0.getHours() * 60 + s0.getMinutes()) * HOUR_PX / 60;
        const endMin = en.toDateString() === s0.toDateString() ? en.getHours() * 60 + en.getMinutes() : 24 * 60;
        const height = Math.max(22, (endMin - (s0.getHours() * 60 + s0.getMinutes())) * HOUR_PX / 60);
        let lane = lanes.findIndex(endAt => endAt <= top);
        if (lane < 0) { lane = lanes.length; lanes.push(0); }
        lanes[lane] = top + height;
        return { e, top, height, lane };
      });
      const n = Math.max(1, lanes.length);
      const col = h('div', { class: `cal-tcol ${key === ymd(today) ? 'today' : ''}` },
        placed.map(({ e, top, height, lane }) => h('button', {
          type: 'button', class: `cal-tev ${e.kind.toLowerCase()} ${e.done_at ? 'done' : ''} ${height < 40 ? 'short' : ''}`, onclick: ev => open(e, ev),
          title: `${hm(e.starts_at)}${e.ends_at ? `–${hm(e.ends_at)}` : ''} · ${label(e)}`,
          style: { top: `${top}px`, height: `${height}px`, left: `calc(${(lane / n) * 100}% + 2px)`, width: `calc(${100 / n}% - 4px)` } },
        height < 40   // kısa kayıt: tek satır saat + başlık
          ? h('b', null, h('span', { class: 'cal-time' }, hm(e.starts_at)), label(e))
          : [h('b', null, label(e)), h('span', null, `${hm(e.starts_at)}${e.ends_at ? `–${hm(e.ends_at)}` : ''}${e.location ? ` · ${e.location}` : ''}`)])));
      col.addEventListener('click', ev => {   // boş saate tıkla: o saatte yeni kayıt (yarım saate yuvarlanır)
        if (ev.target !== col) return;
        const min = Math.floor((ev.offsetY / HOUR_PX) * 2) * 30;
        newEvent({ starts_at: `${key}T${pad2(Math.floor(min / 60))}:${pad2(min % 60)}:00` });
      });
      if (key === ymd(today)) {   // şu anki saat çizgisi
        const now = new Date();
        col.append(h('div', { class: 'cal-now', style: { top: `${(now.getHours() * 60 + now.getMinutes()) * HOUR_PX / 60}px` } }));
      }
      cols.push(col);
    }
    const heads = Array.from({ length: days }, (_, i) => {
      const d = addDays(start, i);
      return h('button', { type: 'button', class: `cal-thead ${ymd(d) === ymd(today) ? 'today' : ''}`, onclick: () => { anchor = d; setMode('day'); } },
        h('span', null, DAYS[(d.getDay() + 6) % 7]), h('b', null, d.getDate()));
    });
    const hours = h('div', { class: 'cal-hours' }, Array.from({ length: 24 }, (_, i) => h('div', null, i ? `${pad2(i)}:00` : '')));
    const scroller = h('div', { class: 'cal-tscroll' }, h('div', { class: 'cal-tgrid' }, hours, cols));
    const view = h('div', { class: `cal-time-view d${days}` },
      h('div', { class: 'cal-thead-row' }, h('span'), heads),
      h('div', { class: 'cal-allday' }, h('span', { class: 'small muted' }, 'Tüm gün'), allDay),
      scroller);
    view.style.setProperty('--days', days);   // sütun sayısı (CSS değişkeni stil nesnesiyle verilemiyor)
    clear(body, view);
    requestAnimationFrame(() => { scroller.scrollTop = 7.5 * HOUR_PX; });
  }

  // ---------- Yıl: 12 küçük ay; kaydı olan gün işaretli, tıklayınca gün görünümü
  function drawYear(byDay) {
    const y = anchor.getFullYear();
    clear(body, h('div', { class: 'cal-year' }, MONTHS.map((mn, mi) => {
      const first = new Date(y, mi, 1), s0 = monday(first);
      const cells = [];
      for (let i = 0; i < 42; i++) {
        const d = addDays(s0, i), key = ymd(d), n = d.getMonth() === mi ? (byDay.get(key) || []).length : 0;
        cells.push(h('button', { type: 'button', class: `cal-yd ${d.getMonth() !== mi ? 'out' : ''} ${key === ymd(today) ? 'today' : ''} ${n ? 'has' : ''}`,
          title: n ? t('{n} kayıt', { n }) : '', disabled: d.getMonth() !== mi, onclick: () => { anchor = d; setMode('day'); } }, d.getDate()));
      }
      return h('div', { class: 'cal-ym' }, h('button', { type: 'button', class: 'cal-ym-title', onclick: () => { anchor = first; setMode('month'); } }, mn),
        h('div', { class: 'cal-ygrid' }, DAYS.map(d => h('span', null, d[0])), cells));
    })));
  }

  // ---------- Ajanda: günlere göre liste
  function drawAgenda(byDay) {
    const keys = [...byDay.keys()].sort();
    clear(body, keys.length ? h('div', { class: 'cal-agenda' }, keys.map(k => {
      const d = new Date(`${k}T12:00`);
      return h('div', { class: `cal-ag-day ${k === ymd(today) ? 'today' : ''}` },
        h('div', { class: 'cal-ag-date' }, h('b', null, d.getDate()), h('span', null, `${MONTHS[d.getMonth()].slice(0, 3)} · ${DAYS[(d.getDay() + 6) % 7]}`)),
        h('div', { class: 'cal-ag-list' }, byDay.get(k).map(e => h('button', { type: 'button', class: `cal-ag-ev ${e.kind.toLowerCase()} ${e.done_at ? 'done' : ''}`, onclick: ev => open(e, ev) },
          h('span', { class: 'cal-ag-time' }, e.kind === 'HATIRLATMA' && hm(e.starts_at) === '00:00' ? 'Tüm gün' : `${hm(e.starts_at)}${e.ends_at ? `–${hm(e.ends_at)}` : ''}`),
          kindBadge(e.kind), h('b', null, label(e)), e.location ? h('span', { class: 'small muted' }, e.location) : null))));
    })) : h('div', { class: 'card empty' }, 'Bu aralıkta kayıt yok'));
  }

  async function load() {
    const [start, end] = range();
    title.textContent = titleText();
    const [events, next] = await Promise.all(mine
      ? [api.get(`/api/crm/my/events?start=${ymd(start)}&end=${ymd(end)}`), api.get('/api/crm/my/upcoming')]
      : [api.get(`/api/crm/events?subject=${subject}&subject_id=${subjectId}&start=${ymd(start)}&end=${ymd(end)}`),
        api.get(`/api/crm/events/upcoming?subject=${subject}&subject_id=${subjectId}`)]);
    let all = events;
    if (mine) {   // personel doğum günleri (yıllık tekrar) kişisel takvimde görünür
      try {
        const s = ymd(start), e = ymd(end);
        const bdays = ((await api.get('/api/hr/birthdays?days=400')).items || [])
          .filter(b => b.date >= s && b.date < e)
          .map(b => ({ id: null, birthday: true, kind: 'DOGUMGUNU', starts_at: `${b.date}T00:00:00`,
            title: `🎂 ${b.name}${b.age ? ` (${b.age})` : ''}`, done_at: null }));
        all = events.concat(bdays);
      } catch { /* doğum günü alınamazsa takvim yine çalışır */ }
    }
    const byDay = byDayOf(all);
    if (mode === 'day') drawTime(byDay, start, 1);
    else if (mode === 'week') drawTime(byDay, start, 7);
    else if (mode === 'year') drawYear(byDay);
    else if (mode === 'agenda') drawAgenda(byDay);
    else drawMonth(byDay, start);
    clear(upcoming, mode === 'agenda' ? null : [h('h3', null, 'Yaklaşan ve bekleyen'),
      next.length ? next.map(e => h('button', { type: 'button', class: `cal-up ${e.done_at ? 'done' : ''}`, onclick: () => eventInfo(subject, subjectId, e, ctx, load) },
        h('span', { class: 'cal-up-when' }, fmtDateTime(e.starts_at)), kindBadge(e.kind), h('b', null, e.title),
        e.subject_name ? h('span', { class: 'small muted' }, e.subject_name) : null,
        e.users.length ? h('span', { class: 'small muted' }, e.users.map(u => u.full_name).join(', ')) : null))
        : h('div', { class: 'empty small' }, 'Yaklaşan randevu ya da bekleyen hatırlatma yok')]);
  }
  const seg = segmented([['day', 'Gün'], ['week', 'Hafta'], ['month', 'Ay'], ['year', 'Yıl'], ['agenda', 'Ajanda']], mode, v => setMode(v, true));
  function setMode(v, fromSeg) {
    mode = v;
    setPref('cal.view', v);
    if (!fromSeg) seg.querySelectorAll('button').forEach((b, i) => b.classList.toggle('on', ['day', 'week', 'month', 'year', 'agenda'][i] === v));
    load().catch(toastError);
  }
  const step = dir => {
    const y = anchor.getFullYear(), m = anchor.getMonth(), d = anchor.getDate();
    anchor = mode === 'day' ? addDays(anchor, dir) : mode === 'week' ? addDays(anchor, 7 * dir) : mode === 'year' ? new Date(y + dir, m, 1)
      : mode === 'agenda' ? addDays(anchor, 30 * dir) : new Date(y, m + dir, 1);
    void d;
    load().catch(toastError);
  };
  load().catch(toastError);
  return h('div', { class: 'cal' },
    h('div', { class: 'cal-bar' },
      h('button', { class: 'btn sm', type: 'button', onclick: () => step(-1), 'aria-label': 'Önceki' }, '‹'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { anchor = new Date(today.getFullYear(), today.getMonth(), today.getDate()); load().catch(toastError); } }, 'Bugün'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => step(1), 'aria-label': 'Sonraki' }, '›'),
      title,
      h('span', { class: 'grow' }),
      seg,
      h('span', { class: 'cal-legend' }, Object.entries(EVENT_KINDS).filter(([k]) => mine || k !== 'KISISEL').map(([k, [lbl]]) => h('span', { class: `cal-dot ${k.toLowerCase()}` }, lbl))),
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => newEvent(mode === 'day' ? { starts_at: `${ymd(anchor)}T09:00:00` } : {}) }, svgIcon(icons.plus), 'Randevu / Hatırlatma')),
    body,
    upcoming);
}
