# Mastertool düğmesi (masaüstü uygulamalar ve ürün siteleri)

Kullanıcı isteği: SSH Master, FTP Masters ve SQL Master uygulamalarında ve ürün sitelerinde **en sağ üst köşede**, animasyonlu,
şık bir **Mastertool** düğmesi. Tıklanınca `https://mastertool.download/` **ayrı pencerede** açılır.

- Web siteleri: `central/sshmaster_server/static/kit.js` (`[data-mt-button]` yuvası) + `kit.css` — `target="_blank" rel="noopener"`.
- Electron uygulamaları: aşağıdaki işaretleme + stil birebir kullanılır; tıklama `shell.openExternal(url)` ile varsayılan tarayıcıda
  (ayrı pencere) açar. Adres: `https://mastertool.download/?lang=<uygulama dili: tr|en|fr|de|es|ar|zh|ru>&theme=<dark|light>` — site
  dili ve temayı bu parametrelerden alır. Özel başlık çubuğunda düğmeye `-webkit-app-region: no-drag` verin.
- Animasyon: çevrede dönen turkuaz→mor ışık halkası (4 sn), "M" simgesinin kendini yeniden çizmesi ve yazıda parıltı.
  `prefers-reduced-motion` açıkken animasyon durur. Dar alanda (≤ 560 px) yalnız simge görünür.
- Açık temada iç zemin beyaz, koyu temada koyu (`html[data-theme=light]` yerine uygulamanın kendi tema seçicisini kullanın).

## İşaretleme
```html
<a class="mtk-mt" href="https://mastertool.download/" title="Mastertool — SSH Master · FTP Masters · SQL Master">
  <span class="mtk-mt-in">
    <svg class="mtk-mt-ic" viewBox="0 0 32 32" aria-hidden="true">
      <defs><linearGradient id="mtkg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#6366f1"/></linearGradient></defs>
      <rect x="2" y="2" width="28" height="28" rx="8" fill="url(#mtkg)"/>
      <path d="M8.5 22.5V10l7.5 7.5 7.5-7.5v12.5" fill="none" stroke="#06101c" stroke-opacity=".28" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      <path class="mtk-mt-m" d="M8.5 22.5V10l7.5 7.5 7.5-7.5v12.5" fill="none" stroke="#06101c" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" pathLength="100"/>
    </svg>
    <span class="mtk-mt-tx">Mastertool</span>
    <svg class="mtk-mt-go" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
  </span>
</a>
```
Electron'da: `a.addEventListener('click', e => { e.preventDefault(); window.api.openExternal(url); })` (preload'da `shell.openExternal`).

## Stil
```css
@property --mtk-a { syntax: '<angle>'; inherits: false; initial-value: 0deg; }
.mtk-mt { --mtk-a: 0deg; position: relative; display: inline-flex; padding: 1.5px; border-radius: 999px; text-decoration: none; flex: 0 0 auto;
  background: conic-gradient(from var(--mtk-a), #22d3ee, #6366f1, #a855f7, #22d3ee 55%, rgba(34,211,238,.15) 70%, #22d3ee);
  animation: mtk-spin 4s linear infinite; box-shadow: 0 0 18px rgba(34,211,238,.25), 0 0 34px rgba(99,102,241,.18); transition: transform .2s, box-shadow .2s; }
.mtk-mt:hover { transform: translateY(-1px); box-shadow: 0 0 24px rgba(34,211,238,.45), 0 0 48px rgba(99,102,241,.3); }
.mtk-mt-in { display: inline-flex; align-items: center; gap: 8px; height: 33px; padding: 0 12px 0 5px; border-radius: 999px;
  background: rgba(11,15,23,.92); color: #fff; font: 700 13.5px/1 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; letter-spacing: .01em; }
html[data-theme=light] .mtk-mt-in { background: rgba(255,255,255,.95); color: #0f172a; }
.mtk-mt-ic { width: 24px; height: 24px; flex: 0 0 auto; }
.mtk-mt-m { stroke-dasharray: 100; animation: mtk-draw 4s ease-in-out infinite; }
.mtk-mt-tx { background: linear-gradient(90deg, currentColor 0%, currentColor 40%, #22d3ee 50%, currentColor 60%, currentColor 100%); background-size: 250% 100%;
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; animation: mtk-shine 4s ease-in-out infinite; }
.mtk-mt-go { width: 14px; height: 14px; opacity: .7; transition: transform .2s, opacity .2s; }
.mtk-mt:hover .mtk-mt-go { transform: translate(2px, -2px); opacity: 1; }
[dir=rtl] .mtk-mt-go { transform: scaleX(-1); }
@keyframes mtk-spin { to { --mtk-a: 360deg; } }
@keyframes mtk-draw { 0% { stroke-dashoffset: 100; } 35%, 80% { stroke-dashoffset: 0; } 100% { stroke-dashoffset: -100; } }
@keyframes mtk-shine { 0%, 30% { background-position: 100% 0; } 70%, 100% { background-position: 0 0; } }
@media (prefers-reduced-motion: reduce) { .mtk-mt, .mtk-mt-m, .mtk-mt-tx { animation: none; } .mtk-mt-m { stroke-dasharray: none; } }
@media (max-width: 560px) { .mtk-mt-tx, .mtk-mt-go { display: none; } .mtk-mt-in { padding: 0 4px; } }
```
