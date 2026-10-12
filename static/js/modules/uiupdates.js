// Yönetim › Sürüm Takibi: solda sürümler, ortada seçili sürümün etkilediği ekranlar, sağda seçili ekranda
// kullanıcılar (güncelledi / güncellemedi — güncel kodla açık ama ekrana girmedi · eski kodla açık · hiç açmadı).
import { api } from '../api.js';
import { avatar, clear, fmtDateTime, h, toast, toastError } from '../ui.js';

const KIND = { refresh: 'Yenile düğmesi', visit: 'güncel kodla girdi' };
const STATE = { fresh: ['Kodu güncel, ekrana girmedi', 'blue'], stale: ['Eski kodla açık', 'yellow'], never: ['Henüz açmadı', 'gray'] };

export async function render(view, body) {
  let rel = null, scr = null, data = null;
  const left = h('div', { class: 'uu-col uu-rel' }), mid = h('div', { class: 'uu-col uu-scr' }), right = h('div', { class: 'uu-col uu-usr' });
  clear(body, h('div', { class: 'uu-split' }, left, mid, right));

  async function loadReleases() {
    try { data = await api.get('/api/ui/releases'); } catch (e) { return clear(left, h('div', { class: 'card empty' }, e.message)); }
    const items = data.items || [];
    clear(left, h('div', { class: 'uu-h' }, h('span', null, 'Sürümler'), h('button', { class: 'btn sm', type: 'button', title: 'Dosyaları yeniden tara', onclick: async () => { try { await api.post('/api/ui/rescan'); toast('Tarandı'); loadReleases(); } catch (e) { toastError(e); } } }, '⟳')),
      items.length ? items.map(r => h('button', { class: `uu-item ${rel === r.id ? 'on' : ''} ${r.id === data.current ? 'cur' : ''}`, type: 'button', onclick: () => { rel = r.id; scr = null; loadReleases(); loadScreens(); clear(right); } },
        h('b', null, `#${r.id}`, r.id === data.current ? h('span', { class: 'badge green', style: { marginLeft: '6px' } }, 'güncel') : null),
        h('span', { class: 'small' }, fmtDateTime(r.created_at)),
        h('span', { class: 'small muted' }, r.all ? 'Tüm ekranlar (ortak dosya)' : `${r.screen_count} ekran · ${r.files.length} dosya`)))
        : h('div', { class: 'small muted', style: { padding: '8px' } }, 'Henüz sürüm kaydı yok'));
    if (rel == null && items.length) { rel = items[0].id; loadScreens(); }
  }
  async function loadScreens() {
    if (rel == null) return;
    let d;
    try { d = await api.get(`/api/ui/releases/${rel}/screens`); } catch (e) { return clear(mid, h('div', { class: 'card empty' }, e.message)); }
    const r = d.release;
    clear(mid, h('div', { class: 'uu-h' }, h('span', null, `#${r.id} · etkilenen ekranlar`), h('span', { class: 'badge gray' }, d.screens.length)),
      r.files.length ? h('details', { class: 'uu-files' }, h('summary', null, `${r.files.length} dosya değişti`), h('ul', null, r.files.map(f => h('li', { class: 'mono small' }, f)))) : null,
      d.screens.length ? d.screens.map(s => {
        const pct = s.total ? Math.round(s.updated * 100 / s.total) : 0;
        return h('button', { class: `uu-item ${scr === s.key ? 'on' : ''}`, type: 'button', onclick: () => { scr = s.key; loadScreens(); loadUsers(); } },
          h('b', null, s.title, s.personal ? h('span', { class: 'small muted' }, ' · Kişisel') : null),
          h('span', { class: 'small' }, `${s.updated} / ${s.total} kullanıcı güncelledi`),
          h('div', { class: 'todo-prog' }, h('i', { style: { width: pct + '%' } })));
      }) : h('div', { class: 'small muted', style: { padding: '8px' } }, 'Bu sürüm arayüz ekranı etkilemiyor (temel kayıt)'));
  }
  async function loadUsers() {
    if (rel == null || !scr) return;
    let d;
    try { d = await api.get(`/api/ui/releases/${rel}/screens/${encodeURIComponent(scr)}/users`); } catch (e) { return clear(right, h('div', { class: 'card empty' }, e.message)); }
    const row = (u, sub, cls) => h('div', { class: `uu-user ${cls || ''}` }, avatar(u, 'sm'), h('div', { class: 'grow', style: { minWidth: 0 } }, h('b', null, u.full_name || u.username), h('div', { class: 'small muted' }, sub)));
    const grp = (title, n, tone) => h('div', { class: `uu-grp ${tone}` }, h('span', null, title), h('b', null, n));
    const pend = d.pending || [];
    const byState = k => pend.filter(u => u.state === k);
    clear(right, h('div', { class: 'uu-h' }, h('span', null, d.title), h('span', { class: 'badge gray' }, `${d.updated.length} / ${d.updated.length + pend.length}`)),
      grp('Güncelledi', d.updated.length, 'ok'),
      d.updated.length ? d.updated.map(u => row(u, `${fmtDateTime(u.at)} · ${KIND[u.kind] || u.kind}`, 'ok')) : h('div', { class: 'small muted uu-none' }, '—'),
      grp('Güncellemedi', pend.length, 'no'),
      ...['stale', 'fresh', 'never'].map(k => { const l = byState(k); return l.length ? [h('div', { class: 'uu-sub' }, h('span', { class: `badge ${STATE[k][1]}` }, STATE[k][0]), h('b', null, l.length)),
        l.map(u => row(u, u.last_seen ? `son görülme ${fmtDateTime(u.last_seen)}` : 'hiç giriş yapmadı', k))] : null; }));
  }
  await loadReleases();
}
