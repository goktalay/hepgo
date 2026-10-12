// Yapılacaklar (TODO): Sistem Yöneticisi personele görev verir; personel görevi BAŞLATIR (süre işler), yaptığı işleri
// madde madde ekler, TAMAMLANDI der (sonuç notu). Yönetici "Verdiğim görevler"de durum / maddeler / geçen süreyi takip eder.
// Üst çubuktaki TODO ikonu (app.js todoButton) /api/todos/pending ile aynı veriyi gösterir. Günlük Görevler'den bağımsız.
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
const ST = { pending: ['Bekliyor', 'gray'], started: ['Devam ediyor', 'blue'], done: ['Tamamlandı', 'green'], cancelled: ['İptal', 'gray'] };
const badge = (map, k) => { const [l, c] = map[k] || [k, 'gray']; return h('span', { class: `badge ${c}` }, l); };
const overdue = t => t.open && t.due_at && new Date(t.due_at.length === 16 ? t.due_at + ':00' : t.due_at) < new Date();

export async function render(view, params, ctx) {
  const admin = isAdmin(ctx);
  let tab = params[0] === 'given' && admin ? 'given' : 'mine';
  let showDone = false, list = [], users = null;
  const focusId = params[0] && /^\d+$/.test(params[0]) ? +params[0] : null;   // #/my-todos/<id> → o görev vurgulu
  const body = h('div', { class: 'todo-list' });

  // ---- veri
  const load = async () => {
    try { list = await api.get(`/api/todos?scope=${tab}&status=${showDone ? 'all' : 'open'}`); }
    catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    draw();
  };
  const act = async (fn, msg) => { try { await fn(); if (msg) toast(msg); await load(); changed(); } catch (err) { toastError(err); } };
  const loadUsers = async () => { if (users) return users; users = (await api.get('/api/users')).filter(u => u.active); return users; };

  // ---- görev verme / düzenleme (yönetici)
  async function editDialog(t) {
    let us = [];
    try { us = await loadUsers(); } catch (err) { return toastError(err); }
    const title = h('input', { class: 'input', value: t?.title || '', placeholder: 'Görev başlığı', maxlength: 300 });
    const note = h('textarea', { class: 'input', rows: 3, placeholder: 'Açıklama / beklenen sonuç (isteğe bağlı)' }, t?.note || '');
    const who = h('select', { class: 'input' }, us.map(u => h('option', { value: u.id, selected: t && u.id === t.assignee_id }, u.full_name || u.username)));
    const due = h('input', { class: 'input', type: 'datetime-local', value: t?.due_at || '' });
    const pr = h('select', { class: 'input' }, Object.entries(PR).map(([k, [l]]) => h('option', { value: k, selected: (t?.priority || 'normal') === k }, l)));
    const m = modal({
      title: t ? 'Görevi düzenle' : 'Yeni görev ver',
      body: h('div', null, field('Başlık', title), field('Kime', who), h('div', { class: 'row' }, field('Son tarih', due), field('Öncelik', pr)), field('Açıklama', note)),
      actions: [{ label: 'Vazgeç' }, { label: t ? 'Kaydet' : 'Görevi ver', class: 'primary', onClick: async () => {
        const payload = { title: title.value.trim(), note: note.value.trim(), assignee_id: +who.value, due_at: due.value || null, priority: pr.value };
        if (!payload.title) { toast('Başlık gerekli', 'err'); return false; }
        try { if (t) await api.put(`/api/todos/${t.id}`, payload); else await api.post('/api/todos', payload); toast(t ? 'Kaydedildi' : 'Görev verildi'); await load(); changed(); }
        catch (err) { toastError(err); return false; }
      } }],
    });
    setTimeout(() => title.focus(), 50);
    return m;
  }

  // ---- tamamlama (sonuç notu)
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

  // ---- kart
  const mine = t => t.assignee_id === ctx.user.id;
  function card(t) {
    const canWork = mine(t) || admin;
    const timer = h('span', { class: `todo-timer ${t.status}`, 'data-id': t.id }, '⏱ ', h('span', { class: 'v' }, fmtDur(liveElapsed(t))));
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
    const actions = [];
    if (canWork && t.status === 'pending') actions.push(h('button', { class: 'btn primary', type: 'button', onclick: () => act(() => api.post(`/api/todos/${t.id}/start`), 'Görev başlatıldı · süre işliyor') }, '▶ Başla'));
    if (canWork && t.status === 'started') actions.push(h('button', { class: 'btn primary', type: 'button', onclick: () => completeDialog(t) }, '✓ Tamamlandı'));
    if (tab === 'given' || admin) {
      if (t.status === 'done' && !t.seen_at) actions.push(h('button', { class: 'btn', type: 'button', onclick: () => act(() => api.post(`/api/todos/${t.id}/seen`), 'Sonuç görüldü olarak işaretlendi') }, '👁 Sonucu gördüm'));
      if (t.status === 'done') actions.push(h('button', { class: 'btn', type: 'button', onclick: async () => { if (await confirmDialog('Yeniden aç', 'Görev yeniden açılsın mı? Süre kaldığı yerden devam eder.')) act(() => api.post(`/api/todos/${t.id}/reopen`), 'Görev yeniden açıldı'); } }, '↻ Yeniden aç'));
      if (t.open) actions.push(h('button', { class: 'btn', type: 'button', onclick: () => editDialog(t) }, 'Düzenle'));
      actions.push(h('button', { class: 'btn danger', type: 'button', onclick: async () => { if (await confirmDialog('Görevi sil', `“${t.title}” silinsin mi?`, { okLabel: 'Sil', danger: true })) act(() => api.del(`/api/todos/${t.id}`), 'Silindi'); } }, 'Sil'));
    }
    const pct = t.item_count ? Math.round(t.item_done * 100 / t.item_count) : 0;
    return h('div', { class: `todo-card ${t.status} ${focusId === t.id ? 'focus' : ''} ${overdue(t) ? 'late' : ''}`, id: `todo-${t.id}` },
      h('div', { class: 'todo-head' }, badge(PR, t.priority), h('b', { class: 't' }, t.title), badge(ST, t.status), timer),
      h('div', { class: 'todo-meta' },
        h('span', null, tab === 'mine' ? `Veren: ${t.creator_name || '—'}` : `Kime: ${t.assignee_name || t.assignee_username}`),
        t.due_at ? h('span', { class: overdue(t) ? 'late' : '' }, `Son: ${fmtDT(t.due_at)}`) : null,
        t.started_at ? h('span', null, `Başladı: ${fmtDT(t.started_at)}`) : null,
        t.done_at ? h('span', null, `Bitti: ${fmtDT(t.done_at)}`) : null,
        t.item_count ? h('span', null, `${t.item_done}/${t.item_count} madde`) : null),
      t.note ? h('div', { class: 'todo-note' }, t.note) : null,
      t.item_count ? h('div', { class: 'todo-prog' }, h('i', { style: { width: pct + '%' } })) : null,
      t.items.length ? items : (t.status === 'started' ? h('div', { class: 'small muted', style: { marginTop: '8px' } }, 'Henüz madde yok — yaptıklarınızı aşağıdan ekleyin.') : null),
      add,
      t.result ? h('div', { class: 'todo-result' }, h('b', null, 'Sonuç: '), t.result) : null,
      actions.length ? h('div', { class: 'todo-actions' }, actions) : null);
  }

  function draw() {
    clear(body, list.length ? list.map(card)
      : h('div', { class: 'card empty' }, tab === 'mine' ? (showDone ? 'Göreviniz yok.' : 'Bekleyen göreviniz yok 🎉') : 'Verdiğiniz görev yok.'));
    if (focusId) document.getElementById(`todo-${focusId}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  // ---- başlık + sekmeler
  const tabs = admin ? segmented([['mine', 'Bana atanan'], ['given', 'Verdiğim görevler']], tab, v => { tab = v; location.replace(`#/my-todos${v === 'given' ? '/given' : ''}`); load(); }) : null;
  const doneTog = h('label', { class: 'small', style: { display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' } },
    h('input', { type: 'checkbox', onchange: e => { showDone = e.target.checked; load(); } }), 'Tamamlananları da göster');
  const newBtn = admin ? h('button', { class: 'btn primary', type: 'button', onclick: () => editDialog(null) }, '＋ Görev ver') : null;
  clear(view,
    h('div', { class: 'page-head' }, h('h1', null, 'Yapılacaklar'), h('div', { class: 'spacer' }), newBtn),
    h('div', { class: 'todo-tabs' }, tabs, doneTog, h('span', { class: 'spacer' })),
    body);
  await load();
  // saniyede bir: devam eden görevlerin süresi
  every(1000, () => list.forEach(t => { if (t.status !== 'started') return; const el = body.querySelector(`.todo-timer[data-id="${t.id}"] .v`); if (el) el.textContent = fmtDur(liveElapsed(t)); }));
  const onChg = () => load();
  window.addEventListener('hepgo:todos-changed', onChg);
}
