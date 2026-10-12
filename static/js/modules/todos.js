// Yapılacaklar (TODO): Sistem Yöneticisi personele görev verir; personel görevi BAŞLATIR (süre işler), yaptığı işleri
// madde madde ekler, TAMAMLANDI der (sonuç notu) ya da nedeniyle REDDEDER. Yönetici "Verdiğim görevler"de solda personel
// listesi (Tüm Personel varsayılan), sağda Liste / Kart / TODO panosu (Başlamamışlar · Başlamışlar · Tamamlanmışlar ·
// Reddedilmişler) ve tarih filtresi (Tüm tarihler / Bu hafta / Bu ay / Bu yıl). Üst çubuktaki TODO ikonu (app.js
// todoButton) /api/todos/pending ile aynı veriyi gösterir. Günlük Görevler'den bağımsız.
import { api } from '../api.js';
import { clear, confirmDialog, every, field, h, modal, segmented, toast, toastError } from '../ui.js';

const ADMIN = 'Sistem Yöneticisi';
export const isAdmin = ctx => !!ctx?.user?.master || (ctx?.user?.roles || []).includes(ADMIN);
export const changed = () => window.dispatchEvent(new Event('hepgo:todos-changed'));
// süre: "1:05:09" ya da "05:09"
export const fmtDur = s => { s = Math.max(0, Math.floor(s || 0)); const hh = Math.floor(s / 3600), mm = Math.floor(s % 3600 / 60), ss = s % 60; return (hh ? hh + ':' : '') + String(mm).padStart(2, '0') + ':' + String(ss).padStart(2, '0'); };
// devam eden görevde süre tarayıcıda akar (sunucu started_at + yerel saat)
export const liveElapsed = t => t.status === 'started' && t.started_at ? Math.max(0, Math.floor((Date.now() - new Date(t.started_at).getTime()) / 1000)) : (t.elapsed_s || 0);
const fmtDT = iso => iso ? new Date(iso.length === 16 ? iso + ':00' : iso).toLocaleString('tr', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
const PR = { low: ['Düşük', 'gray'], normal: ['Normal', 'blue'], high: ['Yüksek', 'red'] };
const ST = { pending: ['Bekliyor', 'gray'], started: ['Devam ediyor', 'blue'], done: ['Tamamlandı', 'green'], rejected: ['Reddedildi', 'red'], cancelled: ['İptal', 'gray'] };
const COLS = [['pending', 'Başlamamışlar'], ['started', 'Başlamışlar'], ['done', 'Tamamlanmışlar'], ['rejected', 'Reddedilmişler']];
const badge = (map, k) => { const [l, c] = map[k] || [k, 'gray']; return h('span', { class: `badge ${c}` }, l); };
const overdue = t => t.open && t.due_at && new Date(t.due_at.length === 16 ? t.due_at + ':00' : t.due_at) < new Date();
const pref = (k, d) => { try { return localStorage.getItem('hepgo.todos.' + k) || d; } catch { return d; } };
const setPref = (k, v) => { try { localStorage.setItem('hepgo.todos.' + k, v); } catch { /* gizli pencere */ } };

export async function render(view, params, ctx) {
  const admin = isAdmin(ctx);
  let tab = params[0] === 'given' && admin ? 'given' : 'mine';
  let showDone = false, list = [], users = null;
  let person = 0, viewMode = pref('view', 'todo'), period = pref('period', 'all');   // yönetici görünümü
  const focusId = params[0] && /^\d+$/.test(params[0]) ? +params[0] : null;   // #/my-todos/<id> → o görev vurgulu
  const body = h('div', { class: 'todo-body' });

  // ---- veri
  const load = async () => {
    const qs = tab === 'given' ? `scope=all&status=all&assignee=${person}&period=${period}` : `scope=mine&status=${showDone ? 'all' : 'open'}`;
    try { list = await api.get(`/api/todos?${qs}`); }
    catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    draw();
  };
  const act = async (fn, msg) => { try { await fn(); if (msg) toast(msg); await load(); changed(); return true; } catch (err) { toastError(err); return false; } };
  const loadUsers = async () => { if (users) return users; users = (await api.get('/api/users')).filter(u => u.active); return users; };

  // ---- görev verme / düzenleme (yönetici)
  async function editDialog(t) {
    let us = [];
    try { us = await loadUsers(); } catch (err) { return toastError(err); }
    const title = h('input', { class: 'input', value: t?.title || '', placeholder: 'Görev başlığı', maxlength: 300 });
    const note = h('textarea', { class: 'input', rows: 3, placeholder: 'Açıklama / beklenen sonuç (isteğe bağlı)' }, t?.note || '');
    const who = h('select', { class: 'input' }, us.map(u => h('option', { value: u.id, selected: t ? u.id === t.assignee_id : u.id === person }, u.full_name || u.username)));
    const due = h('input', { class: 'input', type: 'datetime-local', value: t?.due_at || '' });
    const pr = h('select', { class: 'input' }, Object.entries(PR).map(([k, [l]]) => h('option', { value: k, selected: (t?.priority || 'normal') === k }, l)));
    modal({
      title: t ? 'Görevi düzenle' : 'Yeni görev ver',
      body: h('div', null, field('Başlık', title), field('Kime', who), h('div', { class: 'row' }, field('Son tarih', due), field('Öncelik', pr)), field('Açıklama', note)),
      actions: [{ label: 'Vazgeç' }, { label: t ? 'Kaydet' : 'Görevi ver', class: 'primary', onClick: async () => {
        const payload = { title: title.value.trim(), note: note.value.trim(), assignee_id: +who.value, due_at: due.value || null, priority: pr.value };
        if (!payload.title) { toast('Başlık gerekli', 'err'); return false; }
        return act(() => (t ? api.put(`/api/todos/${t.id}`, payload) : api.post('/api/todos', payload)), t ? 'Kaydedildi' : 'Görev verildi');
      } }],
    });
    setTimeout(() => title.focus(), 50);
  }

  // ---- tamamlama (sonuç notu) / reddetme (neden)
  function completeDialog(t) {
    const res = h('textarea', { class: 'input', rows: 4, placeholder: 'Sonuç / kısa özet (isteğe bağlı)' });
    modal({
      title: 'Görevi tamamla',
      body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, `${t.title} · geçen süre ${fmtDur(liveElapsed(t))}`),
        t.items.some(i => !i.done) ? h('p', { class: 'small', style: { color: 'var(--warning, #b45309)' } }, 'Açık kalan maddeler tamamlandı sayılacak.') : null, field('Sonuç', res)),
      actions: [{ label: 'Vazgeç' }, { label: 'Tamamlandı', class: 'primary', onClick: () => act(() => api.post(`/api/todos/${t.id}/complete`, { result: res.value.trim() }), 'Görev tamamlandı') }],
    });
    setTimeout(() => res.focus(), 50);
  }
  function rejectDialog(t) {
    const res = h('textarea', { class: 'input', rows: 3, placeholder: 'Neden reddediyorsunuz? (zorunlu)' });
    modal({
      title: 'Görevi reddet',
      body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, t.title), field('Neden', res)),
      actions: [{ label: 'Vazgeç' }, { label: 'Reddet', class: 'danger', onClick: () => { const r = res.value.trim(); if (!r) { toast('Neden gerekli', 'err'); return false; } return act(() => api.post(`/api/todos/${t.id}/reject`, { reason: r }), 'Görev reddedildi'); } }],
    });
    setTimeout(() => res.focus(), 50);
  }

  // ---- tam kart (her iki sekmede; TODO panosunda tıklayınca pencerede)
  const mine = t => t.assignee_id === ctx.user.id;
  const timerEl = t => h('span', { class: `todo-timer ${t.status}`, 'data-id': t.id }, '⏱ ', h('span', { class: 'v' }, fmtDur(liveElapsed(t))));
  function actionsOf(t) {
    const canWork = mine(t) || admin, out = [];
    if (canWork && t.status === 'pending') out.push(h('button', { class: 'btn primary', type: 'button', onclick: () => act(() => api.post(`/api/todos/${t.id}/start`), 'Görev başlatıldı · süre işliyor') }, '▶ Başla'));
    if (canWork && t.status === 'started') out.push(h('button', { class: 'btn primary', type: 'button', onclick: () => completeDialog(t) }, '✓ Tamamlandı'));
    if (mine(t) && t.open) out.push(h('button', { class: 'btn', type: 'button', onclick: () => rejectDialog(t) }, '✕ Reddet'));
    if (admin) {
      if ((t.status === 'done' || t.status === 'rejected') && !t.seen_at) out.push(h('button', { class: 'btn', type: 'button', onclick: () => act(() => api.post(`/api/todos/${t.id}/seen`), 'Sonuç görüldü olarak işaretlendi') }, '👁 Sonucu gördüm'));
      if (t.status === 'done' || t.status === 'rejected') out.push(h('button', { class: 'btn', type: 'button', onclick: async () => { if (await confirmDialog('Yeniden aç', 'Görev yeniden açılsın mı? Süre kaldığı yerden devam eder.')) act(() => api.post(`/api/todos/${t.id}/reopen`), 'Görev yeniden açıldı'); } }, '↻ Yeniden aç'));
      if (t.open) out.push(h('button', { class: 'btn', type: 'button', onclick: () => editDialog(t) }, 'Düzenle'));
      out.push(h('button', { class: 'btn danger', type: 'button', onclick: async () => { if (await confirmDialog('Görevi sil', `“${t.title}” silinsin mi?`, { okLabel: 'Sil', danger: true })) act(() => api.del(`/api/todos/${t.id}`), 'Silindi'); } }, 'Sil'));
    }
    return out;
  }
  function card(t) {
    const canWork = mine(t) || admin;
    const items = h('div', { class: 'todo-items' }, t.items.map(it => h('div', { class: `todo-item ${it.done ? 'done' : ''}` },
      h('button', { class: 'chk', type: 'button', title: it.done ? 'Geri al' : 'Yapıldı', disabled: !canWork || !t.open,
        onclick: () => act(() => api.put(`/api/todos/${t.id}/items/${it.id}`, { done: !it.done })) }, it.done ? '✓' : ''),
      h('span', null, it.text),
      it.done_at ? h('small', { class: 'muted' }, fmtDT(it.done_at)) : null,
      canWork && t.open ? h('button', { class: 'x', type: 'button', title: 'Sil', onclick: () => act(() => api.del(`/api/todos/${t.id}/items/${it.id}`)) }, '×') : null)));
    let add = null;
    if (canWork && t.status === 'started') {
      const inp = h('input', { class: 'input', placeholder: 'Yaptığınız işi yazın, Enter', maxlength: 1000 });
      const send = () => { const v = inp.value.trim(); if (!v) return; inp.value = ''; act(() => api.post(`/api/todos/${t.id}/items`, { text: v })); };
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); send(); } });
      add = h('div', { class: 'todo-add' }, inp, h('button', { class: 'btn', type: 'button', onclick: send }, '＋ Madde'));
    }
    const actions = actionsOf(t), pct = t.item_count ? Math.round(t.item_done * 100 / t.item_count) : 0;
    return h('div', { class: `todo-card ${t.status} ${focusId === t.id ? 'focus' : ''} ${overdue(t) ? 'late' : ''}`, id: `todo-${t.id}` },
      h('div', { class: 'todo-head' }, badge(PR, t.priority), h('b', { class: 't' }, t.title), badge(ST, t.status), timerEl(t)),
      h('div', { class: 'todo-meta' },
        h('span', null, tab === 'mine' ? `Veren: ${t.creator_name || '—'}` : `Kime: ${t.assignee_name || t.assignee_username}`),
        h('span', null, `Verildi: ${fmtDT(t.created_at)}`),
        t.due_at ? h('span', { class: overdue(t) ? 'late' : '' }, `Son: ${fmtDT(t.due_at)}`) : null,
        t.started_at ? h('span', null, `Başladı: ${fmtDT(t.started_at)}`) : null,
        t.done_at ? h('span', null, `${t.status === 'rejected' ? 'Reddedildi' : 'Bitti'}: ${fmtDT(t.done_at)}`) : null,
        t.item_count ? h('span', null, `${t.item_done}/${t.item_count} madde`) : null),
      t.note ? h('div', { class: 'todo-note' }, t.note) : null,
      t.item_count ? h('div', { class: 'todo-prog' }, h('i', { style: { width: pct + '%' } })) : null,
      t.items.length ? items : (t.status === 'started' ? h('div', { class: 'small muted', style: { marginTop: '8px' } }, 'Henüz madde yok — yaptıklarınızı aşağıdan ekleyin.') : null),
      add,
      t.result ? h('div', { class: 'todo-result' }, h('b', null, 'Sonuç: '), t.result) : null,
      t.reason ? h('div', { class: 'todo-result rej' }, h('b', null, 'Red nedeni: '), t.reason) : null,
      actions.length ? h('div', { class: 'todo-actions' }, actions) : null);
  }
  // TODO panosu mini kartı → tıklayınca tam kart pencerede
  function miniCard(t) {
    return h('div', { class: `todo-mini ${t.status} ${overdue(t) ? 'late' : ''}`, onclick: () => openCard(t) },
      h('div', { class: 'todo-mini-h' }, badge(PR, t.priority), h('b', null, t.title)),
      h('div', { class: 'todo-mini-m' }, h('span', null, t.assignee_name || t.assignee_username),
        t.status !== 'pending' ? timerEl(t) : (t.due_at ? h('span', { class: overdue(t) ? 'late' : '' }, '⏳ ' + fmtDT(t.due_at)) : null)),
      t.item_count ? h('div', { class: 'todo-prog' }, h('i', { style: { width: Math.round(t.item_done * 100 / t.item_count) + '%' } })) : null,
      t.reason ? h('div', { class: 'small muted todo-mini-r' }, t.reason) : null);
  }
  let openM = null;
  function openCard(t) {
    openM?.close?.();
    const box = h('div', { class: 'todo-list' }, card(t));
    openM = modal({ title: t.title, wide: true, body: box, actions: [{ label: 'Kapat', class: 'primary' }], onClose: () => { openM = null; } });
    // işlem sonrası (load → draw) açık pencere de yenilensin
    openM.refresh = () => { const nt = list.find(x => x.id === t.id); if (nt) clear(box, card(nt)); else openM?.close?.(); };
  }
  // liste satırı (yönetici)
  function row(t) {
    return h('tr', { class: `${t.status} ${overdue(t) ? 'late' : ''}`, onclick: () => openCard(t) },
      h('td', null, h('b', null, t.title), t.note ? h('div', { class: 'small muted', style: { maxWidth: '380px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, t.note) : null),
      h('td', null, t.assignee_name || t.assignee_username),
      h('td', null, badge(ST, t.status)),
      h('td', null, badge(PR, t.priority)),
      h('td', { class: 'small' }, fmtDT(t.created_at)),
      h('td', { class: `small ${overdue(t) ? 'late' : ''}` }, t.due_at ? fmtDT(t.due_at) : '—'),
      h('td', null, t.status === 'pending' ? h('span', { class: 'muted' }, '—') : timerEl(t)),
      h('td', { class: 'small' }, t.item_count ? `${t.item_done}/${t.item_count}` : '—'));
  }

  // ---- yönetici: sol personel listesi
  const peopleEl = h('div', { class: 'todo-people' });
  async function drawPeople() {
    let us = [];
    try { us = await loadUsers(); } catch (err) { return clear(peopleEl, h('div', { class: 'small muted' }, err.message)); }
    // sayılar: seçili dönemdeki tüm görevler (kişi filtresi uygulanmadan) — ayrı istek
    let all = [];
    try { all = await api.get(`/api/todos?scope=all&status=all&period=${period}`); } catch { /* sayılar boş kalır */ }
    const cnt = id => all.filter(t => (!id || t.assignee_id === id)), openN = l => l.filter(t => t.open).length;
    const btn = (id, name, l) => h('button', { class: `todo-person ${person === id ? 'on' : ''}`, type: 'button', onclick: () => { person = id; drawPeople(); load(); } },
      h('span', { class: 'nm' }, name), openN(l) ? h('span', { class: 'n open' }, openN(l)) : null, h('span', { class: 'n' }, l.length));
    const withTasks = us.filter(u => cnt(u.id).length), without = us.filter(u => !cnt(u.id).length);
    clear(peopleEl,
      btn(0, 'Tüm Personel', all),
      withTasks.map(u => btn(u.id, u.full_name || u.username, cnt(u.id))),
      without.length ? h('div', { class: 'todo-people-sep' }, 'Görevi olmayanlar') : null,
      without.map(u => btn(u.id, u.full_name || u.username, [])));
  }

  function draw() {
    if (tab === 'mine') {
      clear(body, h('div', { class: 'todo-list' }, list.length ? list.map(card) : h('div', { class: 'card empty' }, showDone ? 'Göreviniz yok.' : 'Bekleyen göreviniz yok 🎉')));
    } else if (viewMode === 'list') {
      clear(body, list.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table todo-table' },
        h('thead', null, h('tr', null, ['Görev', 'Kime', 'Durum', 'Öncelik', 'Verildi', 'Son tarih', 'Süre', 'Madde'].map(x => h('th', null, x)))),
        h('tbody', null, list.map(row)))) : h('div', { class: 'card empty' }, 'Bu seçimde görev yok.'));
    } else if (viewMode === 'card') {
      clear(body, h('div', { class: 'todo-list' }, list.length ? list.map(card) : h('div', { class: 'card empty' }, 'Bu seçimde görev yok.')));
    } else {
      clear(body, h('div', { class: 'todo-board' }, COLS.map(([st, title]) => {
        const l = list.filter(t => t.status === st);
        return h('div', { class: `todo-col ${st}` }, h('div', { class: 'todo-col-h' }, h('span', null, title), h('b', null, l.length)),
          h('div', { class: 'todo-col-b' }, l.length ? l.map(miniCard) : h('div', { class: 'small muted', style: { padding: '8px' } }, '—')));
      })));
    }
    openM?.refresh?.();
    if (focusId) document.getElementById(`todo-${focusId}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  // ---- başlık + araç çubuğu
  const tabs = admin ? segmented([['mine', 'Bana atanan'], ['given', 'Verdiğim görevler']], tab, v => { tab = v; location.replace(`#/my-todos${v === 'given' ? '/given' : ''}`); layout(); }) : null;
  const doneTog = h('label', { class: 'small', style: { display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' } },
    h('input', { type: 'checkbox', onchange: e => { showDone = e.target.checked; load(); } }), 'Tamamlananları da göster');
  const viewSeg = segmented([['list', 'Liste'], ['card', 'Kart'], ['todo', 'TODO']], viewMode, v => { viewMode = v; setPref('view', v); draw(); });
  const periodSel = h('select', { class: 'input', title: 'Tarih', onchange: e => { period = e.target.value; setPref('period', period); drawPeople(); load(); } },
    [['all', 'Tüm tarihler'], ['week', 'Bu hafta'], ['month', 'Bu ay'], ['year', 'Bu yıl']].map(([v, l]) => h('option', { value: v, selected: v === period }, l)));
  const newBtn = admin ? h('button', { class: 'btn primary', type: 'button', onclick: () => editDialog(null) }, '＋ Görev ver') : null;
  const toolbar = h('div', { class: 'todo-tabs' });
  const main = h('div', { class: 'todo-main' }, toolbar, body);
  const split = h('div', { class: 'todo-split' }, peopleEl, main);
  const page = h('div');
  function layout() {
    clear(toolbar, tabs, tab === 'mine' ? doneTog : [viewSeg, periodSel], h('span', { class: 'spacer' }));
    clear(page, tab === 'given' ? split : main);
    if (tab === 'given') drawPeople();
    load();
  }
  clear(view, h('div', { class: 'page-head' }, h('h1', null, 'Yapılacaklar'), h('div', { class: 'spacer' }), newBtn), page);
  layout();
  // saniyede bir: devam eden görevlerin süresi (kart, liste, pano ve açık pencere)
  every(1000, () => list.forEach(t => { if (t.status !== 'started') return; document.querySelectorAll(`.todo-timer[data-id="${t.id}"] .v`).forEach(el => { el.textContent = fmtDur(liveElapsed(t)); }); }));
  window.addEventListener('hepgo:todos-changed', () => load());
}
