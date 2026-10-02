// Sayfa başlığındaki bağımsız eylem düğmelerini (ör. "+ Yeni X" ve global "Excel") tek bir kapsül (pill-group) içinde toplar.
// Mesajlardaki düğme stiliyle tutarlı; görünüm geçişleri (.seg) ve filtre kutuları (select) kapsül dışında kalır.
// segselect.js / listexport.js ile aynı desen: body'yi izler, değişince yeniden düzenler.

function el(tag, cls) { const e = document.createElement(tag); if (cls) e.className = cls; return e; }

// Kapsüle alınacak eylem düğmeleri: başlıktaki .btn'ler (geri oku ve .seg içindekiler hariç) + global Excel düğmesi.
function candidates(headEl) {
  return [...headEl.querySelectorAll('.btn')].filter(b =>
    !b.classList.contains('back') &&
    !b.closest('.seg') &&
    (b.closest('.head-right') || b.classList.contains('xl-btn') || b.closest('.head-actions')));
}

function rank(b) { return b.classList.contains('xl-btn') ? 2 : (b.classList.contains('primary') ? 0 : 1); }

let queued = false;
function queue() { if (!queued) { queued = true; requestAnimationFrame(sweep); } }

function sweep() {
  queued = false;
  const view = document.getElementById('view');
  const headEl = view && view.querySelector('.page-head');
  if (!headEl) return;
  let hr = headEl.querySelector(':scope > .head-right');
  let grp = headEl.querySelector('.pill-group.head-actions');
  const cand = candidates(headEl);
  if (cand.length < 2) {   // tek düğme kapsüle alınmaz; varsa dağıt
    if (grp) { if (!hr) { hr = el('div', 'head-right'); headEl.append(hr); } [...grp.children].forEach(b => hr.append(b)); grp.remove(); }
    return;
  }
  if (!hr) { hr = el('div', 'head-right'); headEl.append(hr); }
  if (!grp) grp = el('div', 'pill-group head-actions');
  cand.sort((a, b) => rank(a) - rank(b));   // önce primary, sonra diğerleri, en sona Excel
  // Zaten doğru sıradaysa DOM'a dokunma (gözlemci döngüsünü önler)
  const same = grp.parentElement === hr && hr.lastElementChild === grp &&
    grp.children.length === cand.length && cand.every((b, i) => grp.children[i] === b);
  if (same) return;
  for (const b of cand) grp.append(b);   // taşı (olay dinleyicileri korunur)
  hr.append(grp);
}

export function enableHeadGroup() {
  new MutationObserver(muts => {
    if (muts.every(m => m.target.closest && m.target.closest('.head-actions'))) return;   // kendi değişikliklerimiz
    queue();
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  queue();
}
