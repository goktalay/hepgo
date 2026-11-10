// Alt-modül toolbar'ındaki eylem düğmelerini (ör. "+ Yeni", "Excel", görünüm seçici) aşağıda bir filtre satırı
// (.filters) varsa o satıra taşır; böylece ayrı "boşuna" bir satır oluşmaz. Düğmeler filtre satırının sağına girer;
// görünüm seçicisi (Kart/Liste) filtrelerle birlikte solda kalır. listexport.js / headgroup.js ile aynı desen:
// body'yi izler, değişince yeniden düzenler. İşlem fikir birliğine varınca (kararlı) DOM'a dokunulmaz.

let queued = false;
function queue() { if (!queued) { queued = true; requestAnimationFrame(sweep); } }

// Araç satırı sırası her sayfada aynıdır: solda bakış denetimleri (arama, filtreler, görünüm seçici), boşluk, sağda eylemler.
// Boşluğun (.spacer) sağında kalmış seçiciler (.seg ve dar ekran karşılığı .seg-pick) boşluğun soluna alınır.
function order(view) {
  for (const f of view.querySelectorAll('.filters')) {
    const sp = f.querySelector(':scope > .spacer');
    if (!sp) continue;
    for (let el = sp.nextElementSibling; el;) {
      const nx = el.nextElementSibling;
      if ((el.classList.contains('seg') && !el.classList.contains('seg-tabs')) || el.classList.contains('seg-pick')) f.insertBefore(el, sp);
      el = nx;
    }
  }
}

function sweep() {
  queued = false;
  const view = document.getElementById('view');
  if (!view) return;
  order(view);
  const mt = view.querySelector('.module-toolbar');
  if (!mt) return;
  // Sayfa iskeleti sırası: başlık → (sekmeler) → özet şeridi → araç çubuğu → içerik. Araç çubuğu özet şeridinin üstünde
  // kalmışsa altına iner (sekme çubuğu yerinde kalır: sekme, özetin de üstündedir).
  const nx = mt.nextElementSibling;
  if (!mt.classList.contains('module-tabs') && nx && nx.classList.contains('stat-strip')) { nx.after(mt); return; }
  // Araç çubuğunun kendisi de filtre kutusu görünümündedir (.module-toolbar.filters); birleşilecek satır AYRI bir filtre satırıdır.
  const filters = view.querySelector('.filters:not(.module-toolbar)');
  if (!filters) return;                              // ayrı filtre satırı yoksa araç çubuğu kendi kutusunda kalır
  // Alt-gezinme sekmeleri (.seg-tabs) filtreye taşınmaz; kendi satırında kalır. Yalnızca eylem düğmeleri /
  // görünüm seçicileri (Kart/Liste = .seg) filtre satırına iner (boşuna satır olmasın).
  const children = [...mt.children].filter(c => c.nodeType === 1);
  const movers = children.filter(c => !(c.classList && c.classList.contains('seg-tabs')));
  if (!movers.length) return;                        // yalnızca sekme var → toolbar kendi satırı olarak kalsın
  if (!filters.querySelector(':scope > .spacer')) filters.append(Object.assign(document.createElement('span'), { className: 'spacer' }));
  filters.append(...movers);                         // eylemler satırın sağına; seçiciler order() ile boşluğun soluna geçer
  order(view);
  // Toolbar'da sekme (.seg-tabs) kaldıysa satır olarak kalsın; tamamen boşaldıysa kaldır.
  if (![...mt.children].some(c => c.nodeType === 1)) mt.remove();
}

export function enableToolbarMerge() {
  new MutationObserver(queue).observe(document.body, { childList: true, subtree: true });
  queue();
}
