// Mobilde düğme grupları (sekmeler, görünüm / filtre seçimleri, alt modül sekmeleri) ekrana sığmayıp kayıyor.
// Bu yardımcı her `.seg` / `.tabbar` için yanına ikonlu bir seçici ekler: dokununca alttan açılan panelde
// seçenekler (kendi ikonlarıyla) listelenir. CSS ile telefonda düğmeler gizlenip seçici gösterilir, masaüstünde
// düğmeler kalır. Seçim yapılınca ilgili düğmeye tıklanır; düğmeler başka yoldan değişirse seçici kendini günceller.
const GROUPS = '.seg, .tabbar';
const SKIP = '.set-row, .no-select';   // ayar satırlarındaki kısa seçimler zaten tek satıra sığar

const label = b => [...b.childNodes].filter(n => !(n.nodeType === 1 && n.matches('svg, .seg-ico, .tab-n')))
  .map(n => n.textContent).join(' ').replace(/\s+/g, ' ').trim() || b.getAttribute('aria-label') || b.title || '•';
const iconOf = b => b.querySelector('svg')?.cloneNode(true) || null;
const countOf = b => b.querySelector('.tab-n')?.textContent || '';
const buttons = grp => [...grp.querySelectorAll(':scope > button, :scope > a')];
const isOn = b => b.classList.contains('on') || b.getAttribute('aria-selected') === 'true' || b.getAttribute('aria-pressed') === 'true';

function el(tag, cls, ...kids) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  e.append(...kids.filter(k => k != null && k !== ''));
  return e;
}

function sync(grp) {
  const pick = grp._segPick;
  if (!pick) return;
  const btns = buttons(grp);
  const cur = btns.find(isOn);
  const sig = `${btns.map(b => `${label(b)}:${countOf(b)}`).join('\u0001')}|${cur ? label(cur) : ''}`;
  if (pick._sig !== sig) {
    pick._sig = sig;
    pick.trigger.replaceChildren(...[
      el('span', 'sp-ico', (cur && iconOf(cur)) || el('span', 'sp-dot')),
      el('span', 'sp-txt', cur ? label(cur) : 'Seçin'),
      cur && countOf(cur) ? el('span', 'sp-n', countOf(cur)) : null,
      el('span', 'sp-chev')].filter(Boolean));
  }
  pick.hidden = grp.hidden || btns.length < 2;
  grp.classList.toggle('has-select', btns.length >= 2);
}

let openSheet = null;
function closeSheet() {
  if (!openSheet) return;
  const s = openSheet; openSheet = null;
  s.classList.remove('in');
  document.removeEventListener('keydown', onKey);
  setTimeout(() => s.remove(), 220);
}
function onKey(e) { if (e.key === 'Escape') closeSheet(); }

function openPicker(grp) {
  closeSheet();
  const btns = buttons(grp);
  const title = grp.closest('.prod-subnav, .tabbar') || grp.classList.contains('prod-subnav') ? 'Bölüm seçin' : 'Görünüm seçin';
  const list = el('div', 'sp-sheet-list');
  btns.forEach(b => {
    const on = isOn(b);
    const row = el('button', `sp-opt ${on ? 'on' : ''}`,
      el('span', 'sp-ico', iconOf(b) || el('span', 'sp-dot')),
      el('span', 'sp-txt', label(b)),
      countOf(b) ? el('span', 'sp-n', countOf(b)) : null,
      el('span', 'sp-check'));
    row.type = 'button';
    row.disabled = !!b.disabled;
    row.addEventListener('click', () => {
      closeSheet();
      if (!on) b.click();
      requestAnimationFrame(() => sync(grp));
    });
    list.append(row);
  });
  const sheet = el('div', 'sp-back', el('div', 'sp-sheet', el('div', 'sp-grip'), el('div', 'sp-title', title), list));
  sheet.addEventListener('click', e => { if (e.target === sheet) closeSheet(); });
  document.body.append(sheet);
  document.addEventListener('keydown', onKey);
  window.addEventListener('hashchange', closeSheet, { once: true });
  requestAnimationFrame(() => sheet.classList.add('in'));
  openSheet = sheet;
}

function attach(grp) {
  if (grp._segPick || grp.closest(SKIP)) return;
  const trigger = el('button', 'sp-trigger');
  trigger.type = 'button';
  trigger.setAttribute('aria-haspopup', 'listbox');
  trigger.addEventListener('click', () => openPicker(grp));
  const pick = el('div', `seg-pick ${grp.classList.contains('prod-subnav') ? 'sub' : ''} ${grp.classList.contains('tabbar') ? 'tabs' : ''}`, trigger);
  pick.trigger = trigger;
  pick._seg = grp;
  grp._segPick = pick;
  grp.after(pick);
  sync(grp);
}

let queued = false;
function sweep() {
  queued = false;
  document.querySelectorAll(GROUPS).forEach(g => (g._segPick ? sync(g) : attach(g)));
  document.querySelectorAll('.seg-pick').forEach(p => {
    if (!p._seg?.isConnected) p.remove();          // düğme grubu kaldırıldıysa seçici de gider
    else if (p.previousElementSibling !== p._seg) p._seg.after(p);   // grup yer değiştirdiyse peşinden git
  });
}

export function enableSegSelect() {
  new MutationObserver(muts => {
    if (muts.every(m => m.target.closest?.('.seg-pick, .sp-back'))) return;   // kendi değişikliklerimiz
    if (!queued) { queued = true; requestAnimationFrame(sweep); }
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'aria-selected', 'disabled'] });
  sweep();
}
