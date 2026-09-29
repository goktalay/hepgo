// Firma Yönetimi ortak parçaları: sekme çubuğu, notlar, takvim (randevu / hatırlatma + toplantılar) ve evrak listesi.
// Konu (subject): company | person | user — firma detayı ve Rehber kişi / kullanıcı detayı aynı parçaları kullanır.
import { segIcon } from '../segicons.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import {
  clear, companyName, confirmDialog, dateTimeInput, field, fmtDate, fmtDateTime, h, modal, peoplePicker, segmented, shortCompany, svgIcon,
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
          n.updated_at ? h('span', { class: 'muted' }, ` · düzenlendi ${fmtDateTime(n.updated_at)}`) : null,
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
export const EVENT_KINDS = { RANDEVU: ['Randevu', 'blue'], HATIRLATMA: ['Hatırlatma', 'yellow'], TOPLANTI: ['Toplantı', 'purple'] };
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
        if (!await confirmDialog('Kaydı sil', `${e.title} silinsin mi?`, { okLabel: 'Sil', danger: true })) return false;
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
export function calendarPanel(subject, subjectId, ctx, { mine = false } = {}) {
  const today = new Date();
  let year = today.getFullYear(), month = today.getMonth();
  const title = h('b', { class: 'cal-title' });
  const grid = h('div', { class: 'cal-grid' });
  const upcoming = h('div', { class: 'cal-upcoming' });
  const newEvent = preset => eventForm(subject, subjectId, preset, load);
  const chip = e => {
    // kişisel takvimde (Firmalar modülü dışı) firma kısa adıyla; tam adı üzerine gelince
    const label = e.subject_name ? `${e.title} · ${e.subject_name}` : e.kind === 'TOPLANTI' && mine ? `${e.title} · ${shortCompany(e.company_name)}` : e.title;
    const full = e.kind === 'TOPLANTI' && mine && !e.subject_name ? `${e.title} · ${e.company_name}` : label;
    const el = h('button', { type: 'button', class: `cal-chip ${e.kind.toLowerCase()} ${e.done_at ? 'done' : ''}`, title: full },
      e.kind !== 'HATIRLATMA' || hm(e.starts_at) !== '00:00' ? h('span', { class: 'cal-time' }, hm(e.starts_at)) : null, label);
    el.addEventListener('click', ev => { ev.stopPropagation(); eventInfo(subject, subjectId, e, ctx, load); });
    return el;
  };
  async function load() {
    const first = new Date(year, month, 1);
    const gridStart = new Date(year, month, 1 - ((first.getDay() + 6) % 7));
    const gridEnd = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + 42);
    title.textContent = `${MONTHS[month]} ${year}`;
    const [events, next] = await Promise.all(mine
      ? [api.get(`/api/crm/my/events?start=${ymd(gridStart)}&end=${ymd(gridEnd)}`), api.get('/api/crm/my/upcoming')]
      : [api.get(`/api/crm/events?subject=${subject}&subject_id=${subjectId}&start=${ymd(gridStart)}&end=${ymd(gridEnd)}`),
        api.get(`/api/crm/events/upcoming?subject=${subject}&subject_id=${subjectId}`)]);
    const byDay = new Map();
    for (const e of events) {
      const k = e.starts_at.slice(0, 10);
      if (!byDay.has(k)) byDay.set(k, []);
      byDay.get(k).push(e);
    }
    const cells = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i);
      const key = ymd(d);
      const list = (byDay.get(key) || []).sort((a, b) => a.starts_at.localeCompare(b.starts_at));
      const cell = h('div', { class: `cal-cell ${d.getMonth() !== month ? 'out' : ''} ${key === ymd(today) ? 'today' : ''}`,
        title: 'Bu güne kayıt eklemek için tıklayın' },
        h('span', { class: 'cal-day' }, d.getDate()),
        list.slice(0, 3).map(chip),
        list.length > 3 ? h('button', { type: 'button', class: 'cal-more', onclick: ev => {
          ev.stopPropagation();   // günün tüm kayıtları
          const box = modal({ title: fmtDate(key), body: h('div', { class: 'cal-day-list' }, list.map(e => {
            const c = chip(e);
            c.addEventListener('click', () => box.close());
            return c;
          })), actions: [{ label: 'Kapat', class: 'primary' }] });
        } }, `+${list.length - 3} kayıt daha`) : null);
      cell.addEventListener('click', () => newEvent({ starts_at: `${key}T09:00:00` }));
      cells.push(cell);
    }
    clear(grid, DAYS.map(d => h('div', { class: 'cal-head' }, d)), cells);
    clear(upcoming, h('h3', null, 'Yaklaşan ve bekleyen'),
      next.length ? next.map(e => h('button', { type: 'button', class: `cal-up ${e.done_at ? 'done' : ''}`, onclick: () => eventInfo(subject, subjectId, e, ctx, load) },
        h('span', { class: 'cal-up-when' }, fmtDateTime(e.starts_at)), kindBadge(e.kind), h('b', null, e.title),
        e.subject_name ? h('span', { class: 'small muted' }, e.subject_name) : null,
        e.users.length ? h('span', { class: 'small muted' }, e.users.map(u => u.full_name).join(', ')) : null))
        : h('div', { class: 'empty small' }, 'Yaklaşan randevu ya da bekleyen hatırlatma yok'));
  }
  const nav = (dm) => { month += dm; if (month < 0) { month = 11; year--; } if (month > 11) { month = 0; year++; } load().catch(toastError); };
  load().catch(toastError);
  return h('div', { class: 'cal' },
    h('div', { class: 'cal-bar' },
      h('button', { class: 'btn sm', type: 'button', onclick: () => nav(-1), 'aria-label': 'Önceki ay' }, '‹'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { year = today.getFullYear(); month = today.getMonth(); load().catch(toastError); } }, 'Bugün'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => nav(1), 'aria-label': 'Sonraki ay' }, '›'),
      title,
      h('span', { class: 'grow' }),
      h('span', { class: 'cal-legend' }, Object.entries(EVENT_KINDS).map(([k, [label]]) => h('span', { class: `cal-dot ${k.toLowerCase()}` }, label))),
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => newEvent({}) }, svgIcon(icons.plus), 'Randevu / Hatırlatma')),
    grid,
    upcoming);
}
