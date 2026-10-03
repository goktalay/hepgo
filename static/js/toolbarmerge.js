// Alt-modül toolbar'ındaki eylem düğmelerini (ör. "+ Yeni", "Excel", görünüm seçici) aşağıda bir filtre satırı
// (.filters) varsa o satıra taşır; böylece ayrı "boşuna" bir satır oluşmaz. Düğmeler filtre satırının sağına,
// varsa görünüm seçicisinin (Kart/Liste) hemen soluna girer. listexport.js / headgroup.js ile aynı desen:
// body'yi izler, değişince yeniden düzenler. İşlem fikir birliğine varınca (kararlı) DOM'a dokunulmaz.

let queued = false;
function queue() { if (!queued) { queued = true; requestAnimationFrame(sweep); } }

function sweep() {
  queued = false;
  const view = document.getElementById('view');
  if (!view) return;
  const mt = view.querySelector('.module-toolbar');
  const filters = view.querySelector('.filters');
  if (!mt || !filters) return;                       // ayrı toolbar yoksa ya da filtre satırı yoksa dokunma
  const movers = [...mt.children].filter(c => c.nodeType === 1);
  if (!movers.length) { mt.remove(); return; }
  // Filtre satırının sonunda bir görünüm seçicisi (Kart/Liste = .seg) varsa, taşınanlar onun SOLUNA girsin.
  const last = filters.lastElementChild;
  const ref = last && last.classList && last.classList.contains('seg') ? last : null;
  if (!ref && !filters.querySelector(':scope > .spacer')) {   // sona ekleniyorsa sağa yasla
    const sp = document.createElement('span'); sp.className = 'spacer'; filters.append(sp);
  }
  for (const m of movers) filters.insertBefore(m, ref);
  mt.remove();                                        // boşalan toolbar satırını kaldır
}

export function enableToolbarMerge() {
  new MutationObserver(queue).observe(document.body, { childList: true, subtree: true });
  queue();
}
