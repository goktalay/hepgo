// Program Ayarları › Rol Yönetimi: rol ağacı (üst rolden miras), modül / alt modül bazında Aç · Veri oku · Veri yaz
// izin / yasak matrisi (kayıt yoksa miras), role kullanıcı ekleme / çıkarma, çakışma (izin + yasak → yasak geçerli) ve
// görev ayrılığı uyarıları. Rol adı "/" içerebildiği için API'ye ?name= ile gönderilir.
import { api } from '../api.js';
import { clear, confirmDialog, field, h, matches, modal, segmented, t, toast, toastError } from '../ui.js';

const q = n => encodeURIComponent(n);
let LIST = null;
let SEL = null;
let TAB = 'perms';

export function rolesBody() {
  const wrap = h('div', { class: 'rl' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  load(wrap);
  return wrap;
}

async function load(wrap, keep) {
  try { LIST = await api.get('/api/roles'); } catch (e) { return clear(wrap, h('div', { class: 'card empty' }, e.message)); }
  if (!keep || !LIST.roles.some(r => r.name === SEL)) SEL = SEL && LIST.roles.some(r => r.name === SEL) ? SEL : LIST.roles[0]?.name;
  draw(wrap);
}

function tree() {
  const names = new Set(LIST.roles.map(r => r.name));
  const kids = new Map();
  for (const r of LIST.roles) {
    const p = r.parent && names.has(r.parent) ? r.parent : '';
    if (!kids.has(p)) kids.set(p, []);
    kids.get(p).push(r);
  }
  const out = [], seen = new Set();
  const walk = (p, d) => (kids.get(p) || []).forEach(r => { if (seen.has(r.name)) return; seen.add(r.name); out.push([r, d]); walk(r.name, d + 1); });
  walk('', 0);
  LIST.roles.filter(r => !seen.has(r.name)).forEach(r => out.push([r, 0]));   // bozuk zincir olursa da listelensin
  return out;
}

function draw(wrap) {
  let filter = '';
  const listBox = h('div', { class: 'rl-tree' });
  const drawList = () => clear(listBox, tree().filter(([r]) => matches(filter, r.name, r.description)).map(([r, d]) => h('button', {
    class: `rl-node ${r.name === SEL ? 'on' : ''}`, type: 'button', style: { paddingLeft: `${10 + d * 18}px` },
    onclick: () => { SEL = r.name; draw(wrap); } },
  d ? h('span', { class: 'rl-branch' }, '└') : null,
  h('span', { class: 'rl-name' }, r.name), r.locked ? h('span', { class: 'rl-lock', title: 'Tüm yetkiler; düzenlenemez' }, '🔒') : null,
  r.system ? null : h('span', { class: 'rl-custom' }, 'özel'),
  h('span', { class: 'rl-count', title: 'Aktif kullanıcı' }, r.users))));
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Rol ara…' });
  search.addEventListener('input', () => { filter = search.value.trim(); drawList(); });
  const pane = h('div', { class: 'rl-pane' });
  clear(wrap, h('div', { class: 'rl-layout' },
    h('aside', { class: 'card rl-side' },
      h('div', { class: 'rl-side-h' }, h('b', null, t('Roller ({n})', { n: LIST.roles.length })),
        h('button', { class: 'btn sm primary', type: 'button', onclick: () => roleForm(null, wrap) }, '＋ Yeni rol')),
      search, listBox,
      h('p', { class: 'small muted rl-help' }, 'Alt rol, üst rolün tüm yetkilerini miras alır; kendi ayarı üst rolünkini geçersiz kılar. Bir kişide izin ve yasak birlikte varsa yasak geçerlidir.')),
    pane));
  drawList();
  if (SEL) detail(pane, wrap);
}

async function detail(pane, wrap) {
  clear(pane, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let r;
  try { r = await api.get(`/api/roles/one?name=${q(SEL)}`); } catch (e) { return clear(pane, h('div', { class: 'card empty' }, e.message)); }
  const body = h('div');
  const tabs = segmented([['perms', 'İzinler'], ['users', t('Kullanıcılar ({n})', { n: r.users.length })], ['settings', 'Ayarlar']], TAB,
    v => { TAB = v; show(); }, { tabs: true });
  const show = () => (TAB === 'users' ? usersTab(body, r, wrap) : TAB === 'settings' ? settingsTab(body, r, wrap) : permsTab(body, r, wrap));
  clear(pane, h('section', { class: 'card card-pad rl-head' },
    h('div', { class: 'rl-title' }, h('h2', null, r.name), r.locked ? h('span', { class: 'badge red' }, 'Tüm yetkiler') : r.system ? h('span', { class: 'badge blue' }, 'Sistem rolü') : h('span', { class: 'badge green' }, 'Özel rol')),
    r.description ? h('p', { class: 'muted', style: { margin: '2px 0 0' } }, r.description) : null,
    r.chain.length > 1 ? h('div', { class: 'rl-chain' }, h('small', { class: 'muted' }, 'Miras zinciri: '), r.chain.slice().reverse().map((x, i, a) => [
      h('button', { class: `rl-chip ${x === r.name ? 'on' : ''}`, type: 'button', onclick: () => { SEL = x; draw(wrap); } }, x), i < a.length - 1 ? h('span', { class: 'muted' }, ' › ') : null])) : null,
    r.children.length ? h('div', { class: 'rl-chain' }, h('small', { class: 'muted' }, 'Alt roller: '), r.children.map(x => h('button', { class: 'rl-chip', type: 'button', onclick: () => { SEL = x; draw(wrap); } }, x))) : null),
  h('div', { class: 'cf-tabs' }, tabs), body);
  show();
}

// ---- İzinler matrisi
const CAPS = ['open', 'read', 'write'];
function permsTab(root, r, wrap) {
  if (r.locked) return clear(root, h('div', { class: 'card card-pad' }, h('b', null, 'Sistem Yöneticisi tüm modüllerde tam yetkilidir.'),
    h('p', { class: 'muted' }, 'Bu rolün izinleri kısıtlanamaz (sistemden kilitlenip dışarıda kalınmasın). Yetkisi kısıtlı bir yönetim rolü için yeni bir rol oluşturun.')));
  const groups = [];
  for (const n of LIST.catalog) { let g = groups.find(x => x.name === n.group); if (!g) groups.push(g = { name: n.group, nodes: [] }); g.nodes.push(n); }
  const save = async changes => {
    try { await api.put(`/api/roles/perms?name=${q(r.name)}`, { changes }); const nr = await api.get(`/api/roles/one?name=${q(r.name)}`); Object.assign(r, nr); draw0(); } catch (e) { toastError(e); }
  };
  const cell = (n, cap) => {
    const ex = r.perms[n.key]?.[cap];
    const ef = r.effective[n.key]?.[cap];
    const own = ex !== undefined;
    const val = own ? ex : ef?.value;
    const cls = val === true ? 'allow' : val === false ? 'deny' : 'none';
    const tip = own ? (ex ? 'İzin (bu rolde)' : 'Yasak (bu rolde)')
      : ef ? `${ef.value ? 'İzin' : 'Yasak'} — miras: ${ef.role}${ef.node !== n.key ? ` › ${(LIST.catalog.find(c => c.key === ef.node) || {}).title || ef.node}` : ''}` : 'Ayar yok (yetki yok)';
    return h('button', { class: `rl-cell ${cls} ${own ? 'own' : 'inh'}`, type: 'button', title: `${t(tip)} · tıkla: değiştir`,
      onclick: () => save([{ node: n.key, cap, value: !own ? true : ex === true ? false : null }]) }, val === true ? '✓' : val === false ? '✕' : '·');
  };
  const preset = (nodes, kind) => save(nodes.flatMap(n => CAPS.map(cap => ({ node: n.key, cap,
    value: kind === 'clear' ? null : kind === 'full' ? true : kind === 'ro' ? cap !== 'write' : cap === 'open' ? false : null }))));
  const final = n => { const f = r.final[n.key]; return !f ? h('span', { class: 'rl-res none' }, 'Yok') : f.write ? h('span', { class: 'rl-res w' }, 'Yazar') : f.read ? h('span', { class: 'rl-res r' }, 'Okur') : h('span', { class: 'rl-res o' }, 'Açar'); };
  const presets = nodes => h('div', { class: 'rl-pre' },
    h('button', { type: 'button', title: 'Aç + oku + yaz izni', onclick: () => preset(nodes, 'full') }, 'Tam'),
    h('button', { type: 'button', title: 'Aç + oku izni, yazma yasak', onclick: () => preset(nodes, 'ro') }, 'Salt oku'),
    h('button', { type: 'button', title: 'Açma yasak', onclick: () => preset(nodes, 'none') }, 'Yasak'),
    h('button', { type: 'button', title: 'Bu roldeki ayarları sil (mirasa dön)', onclick: () => preset(nodes, 'clear') }, '↺'));
  const draw0 = () => clear(root,
    h('div', { class: 'rl-legend small muted' }, h('span', { class: 'rl-cell allow own' }, '✓'), ' izin · ', h('span', { class: 'rl-cell deny own' }, '✕'), ' yasak · ',
      h('span', { class: 'rl-cell allow inh' }, '✓'), ' soluk = üst rolden / üst modülden miras · ', h('span', { class: 'rl-cell none inh' }, '·'), ' ayar yok. Hücreye tıklayınca: izin → yasak → miras.'),
    h('div', { class: 'card rl-matrix' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, h('th', null, 'Modül'), h('th', { class: 'c' }, 'Aç'), h('th', { class: 'c' }, 'Veri oku'), h('th', { class: 'c' }, 'Veri yaz'), h('th', { class: 'c' }, 'Sonuç'), h('th', null, ''))),
      groups.map(g => h('tbody', null,
        h('tr', { class: 'rl-group' }, h('td', { colspan: 5 }, g.name), h('td', null, presets(g.nodes))),
        g.nodes.map(n => h('tr', { class: n.parent ? 'rl-sub' : '' }, h('td', null, n.parent ? '↳ ' : '', n.title),
          CAPS.map(cap => h('td', { class: 'c' }, cell(n, cap))), h('td', { class: 'c' }, final(n)), h('td', null, presets([n]))))))))
  );
  draw0();
}

// ---- Kullanıcılar
async function usersTab(root, r, wrap) {
  const add = h('button', { class: 'btn sm primary', type: 'button', onclick: () => pickUsers(r, wrap) }, '＋ Kullanıcı ekle');
  clear(root, h('div', { class: 'filters' }, h('span', { class: 'small muted' }, 'Bu role doğrudan atanmış kullanıcılar. Bir kullanıcı birden çok role atanabilir.'), h('span', { class: 'spacer' }), add),
    r.users.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Kullanıcı', 'Diğer rolleri', 'Durum', ''].map(x => h('th', null, x)))),
      h('tbody', null, r.users.map(u => h('tr', null,
        h('td', null, h('b', null, u.full_name), h('div', { class: 'small muted' }, u.username)),
        h('td', { class: 'small' }, u.roles.filter(x => x !== r.name).join(', ') || '—'),
        h('td', null, u.active ? null : h('span', { class: 'badge' }, 'Pasif'),
          u.conflicts ? h('button', { class: 'badge yellow rl-warnb', type: 'button', onclick: () => showConflicts(u.full_name, u.roles) }, t('⚠ {n} çakışma', { n: u.conflicts })) : null),
        h('td', null, h('button', { class: 'btn xs ghost', type: 'button', title: 'Rolden çıkar', onclick: async () => {
          if (!await confirmDialog('Rolden çıkar', t('{u} “{r}” rolünden çıkarılsın mı?', { u: u.full_name, r: r.name }), { okLabel: 'Çıkar', danger: true })) return;
          try { await api.del(`/api/roles/members?name=${q(r.name)}&uid=${u.id}`); toast('Çıkarıldı'); load(wrap, true); } catch (e) { toastError(e); }
        } }, '×'))))))) : h('div', { class: 'card empty' }, 'Bu role atanmış kullanıcı yok.'));
}

async function pickUsers(r, wrap) {
  let all;
  try { all = await api.get('/api/roles/users/all'); } catch (e) { return toastError(e); }
  const chosen = new Set();
  const list = h('div', { class: 'rl-pick' });
  const s = h('input', { class: 'input', type: 'search', placeholder: 'Ad, kullanıcı adı ara…' });
  const drawP = () => clear(list, all.filter(u => !u.roles.includes(r.name) && matches(s.value, u.full_name, u.username)).map(u => {
    const c = h('input', { type: 'checkbox', checked: chosen.has(u.id) });
    c.addEventListener('change', () => { if (c.checked) chosen.add(u.id); else chosen.delete(u.id); });
    return h('label', { class: 'rl-pick-row' }, c, h('span', null, h('b', null, u.full_name), h('small', { class: 'muted' }, ` ${u.username}${u.roles.length ? ` · ${u.roles.join(', ')}` : ''}`)), u.active ? null : h('span', { class: 'badge' }, 'Pasif'));
  }));
  s.addEventListener('input', drawP);
  drawP();
  modal({ title: t('“{r}” rolüne kullanıcı ekle', { r: r.name }), wide: true, body: h('div', null, field('Ara', s), list),
    actions: [{ label: 'Vazgeç' }, { label: 'Ekle', class: 'primary', onClick: async () => {
      if (!chosen.size) throw new Error(t('Kullanıcı seçin'));
      const res = await api.post(`/api/roles/members?name=${q(r.name)}`, { user_ids: [...chosen] });
      toast(t('{n} kullanıcı eklendi', { n: chosen.size }), 'success');
      load(wrap, true);
      if (res.warnings?.length) conflictModal(res.warnings);
    } }] });
}

export function conflictModal(warnings) {
  modal({ title: 'Rol çakışması uyarısı', wide: true, body: h('div', { class: 'rl-conf' },
    h('p', { class: 'muted' }, 'Aşağıdaki kullanıcılarda rollerin izinleri çakışıyor. İzin ile yasak birlikte olduğunda YASAK geçerlidir.'),
    warnings.map(w => h('div', { class: 'card card-pad' }, h('b', null, w.user), conflictList(w)))), actions: [{ label: 'Tamam', class: 'primary' }] });
}

function conflictList(c) {
  return h('ul', { class: 'rl-conf-l' },
    c.sod.map(([a, b]) => h('li', { class: 'sod' }, t('Görev ayrılığı: “{a}” ve “{b}” aynı kişide olmamalı', { a, b }))),
    c.perm.map(p => h('li', null, h('b', null, `${p.group} › ${p.title} · ${t(p.cap_label)}: `),
      t('{a} izin veriyor, {d} yasaklıyor → yasak geçerli', { a: p.allow.join(', '), d: p.deny.join(', ') }))));
}

async function showConflicts(name, roles) {
  try {
    const c = await api.get(`/api/roles/check?roles=${q(roles.join(','))}`);
    modal({ title: t('{n} · rol çakışmaları', { n: name }), wide: true, body: conflictList(c), actions: [{ label: 'Kapat', class: 'primary' }] });
  } catch (e) { toastError(e); }
}

// ---- Ayarlar
function settingsTab(root, r, wrap) {
  const desc = (cur, x) => { const ids = new Set(); const walk = n => LIST.roles.filter(y => y.parent === n).forEach(y => { ids.add(y.name); walk(y.name); }); walk(x); return ids; };
  const banned = desc(null, r.name);
  const name = h('input', { class: 'input', value: r.name, disabled: !!r.system });
  const d = h('textarea', { class: 'input', rows: 2 }); d.value = r.description || '';
  const parent = h('select', { class: 'input', disabled: !!r.locked }, h('option', { value: '' }, '— Üst rol yok (kök) —'),
    LIST.roles.filter(x => x.name !== r.name && !banned.has(x.name)).map(x => h('option', { value: x.name, selected: x.name === r.parent }, x.name)));
  const conf = new Set(r.conflicts_with);
  const confBox = h('div', { class: 'rl-conf-pick' }, LIST.roles.filter(x => x.name !== r.name).map(x => {
    const c = h('input', { type: 'checkbox', checked: conf.has(x.name) });
    c.addEventListener('change', () => { if (c.checked) conf.add(x.name); else conf.delete(x.name); });
    return h('label', null, c, ' ', x.name);
  }));
  clear(root, h('div', { class: 'card card-pad' },
    field('Rol adı', name, r.system ? 'Sistem rollerinin adı programda kullanıldığı için değiştirilemez.' : null),
    field('Açıklama', d),
    field('Üst rol (yetki mirası)', parent, 'Alt rol, üst rolün izin ve yasaklarını miras alır; kendi ayarları önceliklidir.'),
    field('Çakışan roller (görev ayrılığı)', confBox, 'Seçilen rollerle aynı kişiye atanırsa uyarı verilir (ör. talep eden ve onaylayan aynı kişi olmasın).'),
    h('div', { class: 'ct-acts' },
      h('button', { class: 'btn primary', type: 'button', onclick: async () => {
        try {
          const res = await api.put(`/api/roles/one?name=${q(r.name)}`, { name: name.value, description: d.value, parent: parent.value || null, conflicts_with: [...conf] });
          SEL = res.name; toast('Kaydedildi', 'success'); load(wrap, true);
        } catch (e) { toastError(e); }
      } }, 'Kaydet'),
      h('button', { class: 'btn', type: 'button', onclick: () => roleForm({ copy_from: r.name, parent: r.parent }, wrap) }, 'Kopyasını oluştur'),
      r.system ? null : h('button', { class: 'btn ghost danger-text', type: 'button', onclick: () => deleteRole(r, wrap) }, 'Rolü sil'))));
}

function roleForm(pre, wrap) {
  pre = pre || {};
  const name = h('input', { class: 'input', placeholder: 'ör. Muhasebe Sorumlusu' });
  const d = h('input', { class: 'input', placeholder: 'Kısa açıklama' });
  const parent = h('select', { class: 'input' }, h('option', { value: '' }, '— Üst rol yok (kök) —'), LIST.roles.map(x => h('option', { value: x.name, selected: x.name === pre.parent }, x.name)));
  const copy = h('select', { class: 'input' }, h('option', { value: '' }, '— Boş başla —'), LIST.roles.filter(x => !x.locked).map(x => h('option', { value: x.name, selected: x.name === pre.copy_from }, x.name)));
  modal({ title: 'Yeni rol', body: h('div', null, field('Rol adı', name), field('Açıklama', d),
    field('Üst rol', parent, 'Seçerseniz yeni rol onun yetkilerini miras alır.'),
    field('İzinleri kopyala', copy, 'Seçilen rolün kendi izin / yasak ayarları yeni role kopyalanır.')),
  actions: [{ label: 'Vazgeç' }, { label: 'Oluştur', class: 'primary', onClick: async () => {
    const res = await api.post('/api/roles', { name: name.value, description: d.value, parent: parent.value || null, copy_from: copy.value || null });
    SEL = res.name; TAB = 'perms'; toast('Rol oluşturuldu', 'success'); load(wrap, true);
  } }] });
}

function deleteRole(r, wrap) {
  const inp = h('input', { class: 'input', placeholder: r.name });
  modal({ title: 'Rolü sil', body: h('div', null, h('p', null, t('“{r}” silinecek; {n} kullanıcıdan bu rol kaldırılır, alt rolleri bir üst role bağlanır. Onaylamak için rol adını yazın:', { r: r.name, n: r.users.length })), inp),
    actions: [{ label: 'Vazgeç' }, { label: 'Sil', class: 'danger', onClick: async () => {
      await api.del(`/api/roles/one?name=${q(r.name)}&confirm=${q(inp.value)}`); SEL = null; toast('Rol silindi'); load(wrap);
    } }] });
}
