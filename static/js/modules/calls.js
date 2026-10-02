// Sekreterya → Aramalar ve kullanıcı menüsündeki Aramalarım: şirkete dışarıdan gelen telefonlar.
// Sekreterya aramayı not eder ve ilgili kullanıcıya bağlar; kullanıcı notunu ekler, geri dönünce "Tamamlandı" der.
// İki sayfada da kart ve liste görünümü vardır (tercih tarayıcıda saklanır).
import { api } from '../api.js';
import {
  avatar, clear, companyName, confirmDialog, every, field, fmtDateTime, fmtDuration, h, matches, modal, moduleToolbar, pageHead, pref, secondsSince,
  segmented, setPref, toast, toastError,
} from '../ui.js';

export const RESULTS = { BAGLANDI: ['green', 'Bağlandı'], ULASILAMADI: ['red', 'Ulaşılamadı'], MESAJ: ['yellow', 'Mesaj bırakıldı'] };
const resultBadge = r => h('span', { class: `badge ${(RESULTS[r] || RESULTS.MESAJ)[0]}` }, (RESULTS[r] || RESULTS.MESAJ)[1]);
const state = k => (k.done_at ? h('span', { class: 'badge gray' }, 'Tamamlandı') : k.target_id ? h('span', { class: 'badge blue' }, 'Bekliyor') : null);
const tel = p => (p ? h('a', { href: `tel:${p.replace(/[^\d+]/g, '')}`, class: 'call-tel', onclick: e => e.stopPropagation() }, `📞 ${p}`) : null);
const company = k => (k.company_name ? companyName(k.company_name, { class: 'small muted' }) : k.caller_company ? h('span', { class: 'small muted' }, k.caller_company) : null);

// Kart / liste çizimi (iki sayfada ortak). mine: Aramalarım (ilgili kişi sütunu yok)
function drawCalls(out, list, mode, open, mine) {
  if (mode === 'list') {
    clear(out, h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', { class: 'call-table' },
      h('thead', null, h('tr', null, ['Zaman', 'Arayan', 'Telefon', 'Konu', mine ? null : 'İlgili kişi', 'Sonuç', 'Durum', 'Not'].filter(Boolean).map(t => h('th', null, t)))),
      h('tbody', null, list.map(k => h('tr', { class: `clickable ${k.done_at ? '' : 'call-open'}`, onclick: () => open(k.id) },
        h('td', { class: 'nowrap' }, fmtDateTime(k.created_at)),
        h('td', null, h('b', null, k.caller_name), h('div', null, company(k))),
        h('td', { class: 'nowrap' }, tel(k.caller_phone) || '—'),
        h('td', { class: 'wrap' }, k.subject || '—'),
        mine ? null : h('td', null, k.target_name || '—'),
        h('td', null, resultBadge(k.result), k.callback ? h('div', { class: 'small call-cb' }, 'Geri aranmak istiyor') : null),
        h('td', null, state(k)),
        h('td', { class: 'num' }, k.note_count || (k.note ? '✎' : '—')))))))));
    return;
  }
  clear(out, h('div', { class: 'call-grid' }, list.map(k => h('div', { class: `card call-card ${k.done_at ? 'done' : ''} r-${k.result}`, onclick: () => open(k.id) },
    h('div', { class: 'call-top' }, h('span', { class: 'call-ico' }, '☎'), h('div', { class: 'grow' }, h('b', null, k.caller_name), h('div', null, company(k))),
      resultBadge(k.result)),
    tel(k.caller_phone),
    k.subject ? h('div', { class: 'call-subject' }, k.subject) : null,
    k.note ? h('div', { class: 'call-note' }, k.note.length > 160 ? `${k.note.slice(0, 160)}…` : k.note) : null,
    h('div', { class: 'call-foot' },
      !mine && k.target_name ? h('span', { class: 'call-who' }, avatar({ full_name: k.target_name, photo: k.target_photo }, 'sm'), k.target_name) : null,
      k.callback && !k.done_at ? h('span', { class: 'badge red' }, 'Geri arayın') : null,
      state(k), k.note_count ? h('span', { class: 'small muted' }, `✎ ${k.note_count}`) : null,
      h('span', { class: 'grow' }),
      h('span', { class: 'small muted', title: fmtDateTime(k.created_at) }, `${fmtDateTime(k.created_at)}${k.done_at ? '' : ` · ${fmtDuration(secondsSince(k.created_at)).replace(/ \d+ sn$/, '')}`}`))))));
}

function viewToggle(key, onChange) {
  let mode = pref(key, 'card');
  const seg = segmented([['card', 'Kart'], ['list', 'Liste']], mode, v => { mode = v; setPref(key, v); onChange(); });
  return { seg, get: () => mode };
}

// ---------- Sekreterya → Aramalar
export async function renderCalls(body, addBtn, head) {
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Arayan, telefon, firma, konu, kişi ara…', style: { width: '260px' } });
  const scope = h('select', { class: 'input', title: 'Durum' }, [['open', 'Bekleyenler'], ['today', 'Bugün'], ['all', 'Tüm aramalar']].map(([v, l]) => h('option', { value: v }, l)));
  scope.value = pref('calls.scope', 'today');
  const info = h('span', { class: 'small muted' });
  const out = h('div');
  let rows = [];
  const vt = viewToggle('calls.view', () => draw());
  const draw = () => {
    const today = new Date().toISOString().slice(0, 10);
    const list = rows.filter(k => (scope.value === 'all' || (scope.value === 'open' ? !k.done_at && k.target_id : k.created_at.slice(0, 10) === today))
      && matches(q.value, k.caller_name, k.caller_phone, k.caller_company, k.company_name, k.subject, k.note, k.target_name));
    info.textContent = `${list.length} arama`;
    if (!list.length) { clear(out, h('div', { class: 'card empty' }, rows.length ? 'Bu filtrede arama yok' : 'Henüz arama kaydı yok. Gelen telefonu sağ üstteki "Yeni Arama" ile not edin.')); return; }
    drawCalls(out, list, vt.get(), id => openCall(id, load), false);
  };
  const load = async () => { rows = await api.get('/api/secretariat/calls'); draw(); };
  q.addEventListener('input', draw);
  scope.addEventListener('change', () => { setPref('calls.scope', scope.value); draw(); });
  addBtn.onclick = () => callForm(null, load);
  head.insertBefore(vt.seg, head.lastChild);   // kart / liste: toolbar'da, alt modül işleminin solunda
  clear(body, h('div', { class: 'filters' }, scope, q, info), out);
  await load();
  every(30000, () => { if (!document.querySelector('.modal-back')) load().catch(() => {}); });
}

// ---------- Yeni / düzenle
async function callForm(k, done) {
  const [users, people, callers] = await Promise.all([api.get('/api/people'), api.get('/api/secretariat/people').catch(() => []),
    api.get('/api/secretariat/calls/callers').catch(() => [])]);
  let personId = k?.person_id || null;
  const name = h('input', { class: 'input', value: k?.caller_name || '', placeholder: 'Arayan kişinin adı', autocomplete: 'off' });
  const phone = h('input', { class: 'input', type: 'tel', value: k?.caller_phone || '', placeholder: '05xx xxx xx xx', autocomplete: 'off' });
  const comp = h('input', { class: 'input', value: k?.caller_company || k?.company_name || '', placeholder: 'Firma (isteğe bağlı)' });
  const subject = h('input', { class: 'input', value: k?.subject || '', placeholder: 'Ne için aradı? (kısa)' });
  const note = h('textarea', { class: 'input', rows: 4, placeholder: 'Bırakılan mesaj, alınan not…' }, k?.note || '');
  const callback = h('input', { type: 'checkbox', checked: !!k?.callback });
  let result = k?.result || 'MESAJ';
  const resSeg = segmented(Object.entries(RESULTS).map(([v, [, l]]) => [v, l]), result, v => { result = v; });
  // Arayan önerileri: firmada kayıtlı kişiler ve daha önce arayanlar
  const sugg = h('div', { class: 'call-sugg', hidden: true });
  const pickCaller = (n, p, c, pid) => { name.value = n; phone.value = p || ''; comp.value = c || ''; personId = pid || null; sugg.hidden = true; subject.focus(); };
  const suggest = () => {
    const t = name.value.trim().length >= 2 ? name.value : phone.value.replace(/\D/g, '').length >= 4 ? phone.value : '';
    if (!t) { sugg.hidden = true; return; }
    const digits = t.replace(/\D/g, '');
    const hit = (n, p, c) => matches(t, n, c) || (digits.length >= 4 && (p || '').replace(/\D/g, '').includes(digits));
    const a = people.filter(p => hit(p.full_name, p.phone, p.company_name)).slice(0, 6)
      .map(p => h('button', { type: 'button', onclick: () => pickCaller(p.full_name, p.phone, p.company_name, p.id) },
        h('b', null, p.full_name), h('span', null, [p.title, p.company_name, p.phone].filter(Boolean).join(' · '))));
    const b = callers.filter(c => hit(c.caller_name, c.caller_phone, c.caller_company)).slice(0, 6)
      .map(c => h('button', { type: 'button', onclick: () => pickCaller(c.caller_name, c.caller_phone, c.caller_company, c.person_id) },
        h('b', null, c.caller_name), h('span', null, [c.caller_company, c.caller_phone, `${c.n} kez aradı`].filter(Boolean).join(' · '))));
    clear(sugg, a.length ? h('div', { class: 'call-sugg-h' }, 'Firmalarda kayıtlı') : null, a, b.length ? h('div', { class: 'call-sugg-h' }, 'Daha önce arayanlar') : null, b);
    sugg.hidden = !(a.length || b.length);
  };
  name.addEventListener('input', () => { personId = null; suggest(); });
  phone.addEventListener('input', suggest);
  // İlgili kişi
  const uq = h('input', { class: 'input', type: 'search', placeholder: 'İlgili kişiyi ara…' });
  const target = h('select', { class: 'input', size: 5 });
  const fillUsers = () => {
    const cur = target.value || (k?.target_id ? String(k.target_id) : '');
    clear(target, h('option', { value: '' }, '— Kimseye bağlanmadı (yalnızca not) —'),
      users.filter(u => matches(uq.value, u.full_name, u.username)).map(u => h('option', { value: u.id, selected: String(u.id) === cur }, u.full_name)));
  };
  uq.addEventListener('input', fillUsers);
  fillUsers();
  modal({
    title: k ? 'Aramayı Düzenle' : 'Yeni Arama', wide: true,
    body: h('div', { class: 'call-form' },
      h('div', null,
        h('div', { class: 'call-caller' }, field('Arayan', name), sugg),
        h('div', { class: 'row' }, field('Telefon', phone), field('Firma', comp)),
        field('Konu', subject), field('Not / mesaj', note)),
      h('div', null,
        field('Kime bağlandı / kiminle görüşmek istedi', h('div', null, uq, target)),
        field('Sonuç', resSeg),
        h('label', { class: 'check' }, callback, 'Geri aranmak istiyor'),
        h('p', { class: 'small muted' }, 'İlgili kişiye bildirim düşer ve arama "Aramalarım"da görünür. Bağlanan ve geri dönüş istemeyen aramalar tamamlanmış sayılır.'))),
    actions: [{ label: 'Vazgeç' }, { label: k ? 'Kaydet' : 'Kaydet ve Bildir', class: 'primary', onClick: async () => {
      const b = { caller_name: name.value, caller_phone: phone.value, caller_company: comp.value, person_id: personId, subject: subject.value,
        note: note.value, result, callback: callback.checked, target_id: target.value ? Number(target.value) : null };
      if (k) await api.put(`/api/secretariat/calls/${k.id}`, b); else await api.post('/api/secretariat/calls', b);
      toast(k ? 'Arama güncellendi' : b.target_id ? 'Arama kaydedildi, ilgili kişiye bildirildi' : 'Arama kaydedildi');
      done();
    } }],
  });
  name.focus();
}

// ---------- Ayrıntı: bilgiler, not akışı, tamamla / yeniden aç, düzenle / sil
export async function openCall(id, done) {
  let k = await api.get(`/api/calls/${id}`);
  const box = h('div');
  const text = h('textarea', { class: 'input', rows: 2, placeholder: 'Not ekleyin (ör. geri aradım, teklif istedi)…' });
  const draw = () => clear(box,
    h('div', { class: 'call-detail' },
      h('div', { class: 'call-top' }, h('span', { class: 'call-ico big' }, '☎'), h('div', { class: 'grow' }, h('b', { class: 'call-name' }, k.caller_name), h('div', null, company(k))),
        resultBadge(k.result), state(k)),
      h('dl', { class: 'sys-kv' },
        [['Telefon', tel(k.caller_phone) || '—'], ['Zaman', fmtDateTime(k.created_at)], ['Konu', k.subject || '—'],
          ['İlgili kişi', k.target_name || '— (yalnızca not)'], ['Geri arama', k.callback ? 'İstiyor' : 'Gerekmiyor'],
          ['Kaydeden', k.created_by_name || '—'], k.seen_at ? ['Görüldü', fmtDateTime(k.seen_at)] : null,
          k.done_at ? ['Tamamlandı', `${fmtDateTime(k.done_at)}${k.done_by_name ? ` · ${k.done_by_name}` : ''}`] : null]
          .filter(Boolean).map(([a, b]) => [h('dt', null, a), h('dd', null, b)]).flat()),
      k.note ? h('div', { class: 'call-msg' }, h('small', null, 'Sekreteryanın notu'), k.note) : null,
      h('h4', null, `Notlar (${k.notes.length})`),
      k.notes.length ? h('ul', { class: 'call-notes' }, k.notes.map(n => h('li', null, avatar(n, 'sm'),
        h('div', null, h('div', { class: 'small muted' }, `${n.full_name || '—'} · ${fmtDateTime(n.at)}`), h('div', { class: 'call-nbody' }, n.body)))))
        : h('div', { class: 'small muted' }, 'Henüz not yok'),
      h('div', { class: 'call-add' }, text, h('button', { class: 'btn', type: 'button', onclick: async () => {
        try { k = await api.post(`/api/calls/${id}/notes`, { body: text.value }); text.value = ''; draw(); done?.(); } catch (err) { toastError(err); }
      } }, 'Not Ekle'))));
  draw();
  const m = modal({
    title: 'Arama', wide: true, body: box, onClose: () => done?.(),
    actions: [
      k.can_edit ? { label: 'Sil', class: 'danger', onClick: async () => {
        if (!await confirmDialog('Aramayı sil', `${k.caller_name} araması silinsin mi?`, { okLabel: 'Sil', danger: true })) return true;
        await api.del(`/api/secretariat/calls/${id}`); toast('Arama silindi');
      } } : null,
      k.can_edit ? { label: 'Düzenle', onClick: () => { m.close(); callForm(k, () => done?.()); return true; } } : null,
      'spacer',
      { label: 'Kapat' },
      k.target_id ? { label: k.done_at ? 'Yeniden Aç' : 'Tamamlandı', class: k.done_at ? '' : 'primary', onClick: async () => {
        await api.post(`/api/calls/${id}/done`, { done: !k.done_at }); toast(k.done_at ? 'Arama yeniden açıldı' : 'Arama tamamlandı');
      } } : null,
    ].filter(Boolean),
  });
}

// ---------- Aramalarım (kullanıcı menüsü)
export async function renderMyCalls(view) {
  const scope = h('select', { class: 'input', title: 'Durum' }, [['open', 'Bekleyenler'], ['done', 'Tamamlananlar'], ['all', 'Tümü']].map(([v, l]) => h('option', { value: v }, l)));
  scope.value = pref('mycalls.scope', 'open');
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Arayan, telefon, firma, konu ara…', style: { width: '240px' } });
  const out = h('div');
  let rows = [];
  const vt = viewToggle('mycalls.view', () => draw());
  const draw = () => {
    const list = rows.filter(k => (scope.value === 'all' || (scope.value === 'open' ? !k.done_at : !!k.done_at))
      && matches(q.value, k.caller_name, k.caller_phone, k.caller_company, k.company_name, k.subject, k.note));
    if (!list.length) { clear(out, h('div', { class: 'card empty' }, scope.value === 'open' ? 'Bekleyen aramanız yok' : 'Arama yok')); return; }
    drawCalls(out, list, vt.get(), id => openCall(id, load), true);
  };
  const load = async () => { rows = await api.get('/api/me/calls'); draw(); };
  q.addEventListener('input', draw);
  scope.addEventListener('change', () => { setPref('mycalls.scope', scope.value); draw(); });
  clear(view, pageHead('Aramalarım', { back: '#/', sub: 'Sekreteryanın sizin için not ettiği telefonlar · geri dönünce "Tamamlandı" deyin' }),
    moduleToolbar(vt.seg),
    h('div', { class: 'filters' }, scope, q), out);
  await load();
  every(30000, () => { if (!document.querySelector('.modal-back')) load().catch(() => {}); });
}
