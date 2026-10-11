(function(){
  'use strict';
  var RM = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (RM) document.documentElement.classList.add('rm');

  /* ---------- Brand / data config ---------- */
  var GTABLES = [
    { title:'Satış Analitiği', rows:[
      ['/static/exp2/assets/avatars/a1.png','Selin Aydın','2025-10-01','₺130,000','pending'],
      ['/static/exp2/assets/avatars/a2.png','Zeynep Kaya','2025-11-02','₺400,000','approved'],
      ['/static/exp2/assets/avatars/a3.png','Mert Demir','2025-10-08','₺220,000','approved'],
      ['/static/exp2/assets/avatars/a4.png','Ayşe Yıldız','2025-09-06','₺360,000','pending'],
      ['/static/exp2/assets/avatars/a2.png','Can Öz','2025-03-07','₺890,000','approved']
    ]},
    { title:'Saha Performansı', rows:[
      ['/static/exp2/assets/avatars/a3.png','Mert Demir','2025-10-11','₺96,000','approved'],
      ['/static/exp2/assets/avatars/a1.png','Selin Aydın','2025-10-14','₺210,000','pending'],
      ['/static/exp2/assets/avatars/a4.png','Ayşe Yıldız','2025-11-01','₺175,000','approved'],
      ['/static/exp2/assets/avatars/a2.png','Zeynep Kaya','2025-11-09','₺302,000','approved'],
      ['/static/exp2/assets/avatars/a3.png','Ece Ak','2025-11-12','₺88,000','pending']
    ]},
    { title:'Müşteri Kartları', rows:[
      ['/static/exp2/assets/avatars/a4.png','Ayşe Yıldız','2025-10-19','₺54,000','approved'],
      ['/static/exp2/assets/avatars/a2.png','Can Öz','2025-10-22','₺132,000','approved'],
      ['/static/exp2/assets/avatars/a1.png','Selin Aydın','2025-10-29','₺77,500','pending'],
      ['/static/exp2/assets/avatars/a3.png','Mert Demir','2025-11-04','₺148,000','approved'],
      ['/static/exp2/assets/avatars/a4.png','Burak Şen','2025-11-15','₺61,200','pending']
    ]}
  ];

  function renderGTable(i){
    var t = GTABLES[i];
    document.getElementById('gtTitle').textContent = t.title;
    document.getElementById('gtBody').innerHTML = t.rows.map(function(r){
      return '<tr><td class="who"><img class="avatar" src="'+r[0]+'" alt="'+r[1]+'">'+r[1]+'</td><td>'+r[2]+'</td><td class="amt">'+r[3]+'</td><td><span class="status '+r[4]+'">'+(r[4]==='approved'?'Onaylı':'Bekliyor')+'</span></td></tr>';
    }).join('');
  }
  renderGTable(0);

  var gtabs = document.querySelectorAll('.gtab');
  gtabs.forEach(function(btn,i){
    btn.addEventListener('click', function(){
      gtabs.forEach(function(b){ b.classList.remove('on'); b.setAttribute('aria-selected','false'); });
      btn.classList.add('on'); btn.setAttribute('aria-selected','true');
      renderGTable(i);
    });
  });

  /* ---------- Pricing toggle ---------- */
  var sw = document.getElementById('billSwitch');
  sw.addEventListener('click', function(){
    var yearly = sw.classList.toggle('yearly');
    sw.setAttribute('aria-checked', yearly ? 'true' : 'false');
    document.querySelectorAll('[data-price]').forEach(function(el){
      el.textContent = yearly ? el.getAttribute('data-y') : el.getAttribute('data-m');
    });
    document.querySelectorAll('[data-billed]').forEach(function(el){
      el.textContent = 'beta döneminde ücretsiz';
    });
  });

  /* ---------- FAQ accordion ---------- */
  document.querySelectorAll('.acc').forEach(function(acc){
    var head = acc.querySelector('.acc-head'), body = acc.querySelector('.acc-body');
    function setHeight(){ body.style.maxHeight = acc.classList.contains('open') ? body.scrollHeight + 'px' : '0px'; }
    head.addEventListener('click', function(){
      var open = acc.classList.toggle('open');
      head.setAttribute('aria-expanded', open ? 'true' : 'false');
      setHeight();
    });
    setHeight();
    window.addEventListener('resize', setHeight);
  });

  /* ---------- Key Tools panels ---------- */
  var ktTabs = document.querySelectorAll('.kt-tab');
  var ktPanels = document.querySelectorAll('.kt-panel');
  function ktSet(i){
    ktTabs.forEach(function(t,j){ t.classList.toggle('on', i===j); t.setAttribute('aria-selected', i===j?'true':'false'); });
    ktPanels.forEach(function(p,j){ p.classList.toggle('on', i===j); });
  }
  ktTabs.forEach(function(t,i){ t.addEventListener('click', function(){ ktSet(i); }); });

  /* ---------- Motion ---------- */
  if (window.gsap && window.ScrollTrigger && !RM){
    gsap.registerPlugin(ScrollTrigger);

    /* Hero load: staggered entrance with line-level blur reveal */
    gsap.set('[data-hero]', {opacity:0, y:26});
    gsap.set('[data-hero-line]', {yPercent:112, filter:'blur(10px)'});
    gsap.set('[data-hero-dash]', {opacity:0, y:80});
    var tl = gsap.timeline({defaults:{ease:'power3.out'}});
    tl.to('[data-hero]', {opacity:1, y:0, duration:.9, stagger:.12}, .15)
      .to('[data-hero-line]', {yPercent:0, filter:'blur(0px)', duration:1.05, stagger:.14, ease:'power4.out'}, .3)
      .to('[data-hero-dash]', {opacity:1, y:0, duration:1.15, ease:'power3.out'}, .75);

    /* Generic scroll reveals — reversible: play on enter, reverse on leave, both directions */
    gsap.utils.toArray('[data-reveal]').forEach(function(el){
      if (el.matches('.bcard,.dcard,.pcard,.acc,.tstat,.tquote')) return; /* grouped/directional choreo below */
      gsap.to(el, {
        opacity:1, y:0, duration:.9, ease:'power3.out',
        scrollTrigger:{trigger:el, start:'top 86%', toggleActions:'play reverse play reverse'}
      });
    });

    /* Section headings: word-level blur reveal, reversible */
    document.querySelectorAll('h2.sec').forEach(function(h){
      var parts = h.innerHTML.split(/<br\s*\/?>/i);
      h.setAttribute('aria-label', parts.map(function(t){ return t.replace(/<[^>]*>/g,'').trim(); }).filter(Boolean).join(' '));
      h.innerHTML = parts.map(function(line){
        return line.trim().split(/\s+/).filter(Boolean).map(function(w){
          return '<span class="w" aria-hidden="true">'+w+'</span>';
        }).join(' ');
      }).join('<br>');
      gsap.fromTo(h.querySelectorAll('.w'),
        {opacity:0, y:16, filter:'blur(8px)'},
        {opacity:1, y:0, filter:'blur(0px)', duration:.7, ease:'power3.out', stagger:.045,
         scrollTrigger:{trigger:h, start:'top 88%', toggleActions:'play reverse play reverse', pinnedContainer:(h.closest('#ktPin')||undefined)}});
    });

    /* Card grids: staggered rise, reversible */
    [['.bento','.bcard'],['.dgrid','.dcard'],['.pcards','.pcard'],['.faq','.acc']].forEach(function(pair){
      var grid = document.querySelector(pair[0]);
      if (!grid) return;
      var cards = grid.querySelectorAll(pair[1]);
      if (!cards.length) return;
      gsap.fromTo(cards, {opacity:0, y:34},
        {opacity:1, y:0, duration:.8, ease:'power3.out', stagger:.09,
         scrollTrigger:{trigger:grid, start:'top 84%', toggleActions:'play reverse play reverse'}});
    });

    /* Testimonials: directional slides (stats from left, quotes from right), reversible */
    gsap.utils.toArray('.tstat').forEach(function(el){
      gsap.fromTo(el, {opacity:0, x:-48, y:0},
        {opacity:1, x:0, y:0, duration:.85, ease:'power3.out',
         scrollTrigger:{trigger:el, start:'top 88%', toggleActions:'play reverse play reverse'}});
    });
    gsap.utils.toArray('.tquote').forEach(function(el){
      gsap.fromTo(el, {opacity:0, x:48, y:0},
        {opacity:1, x:0, y:0, duration:.85, ease:'power3.out',
         scrollTrigger:{trigger:el, start:'top 88%', toggleActions:'play reverse play reverse'}});
    });

    /* Hero parallax drift (scrub) */
    gsap.to('[data-hero-dash]', {yPercent:-9, ease:'none',
      scrollTrigger:{trigger:'.hero', start:'top top', end:'bottom top', scrub:.6}});
    gsap.to('.hero-chart-bg', {yPercent:18, ease:'none',
      scrollTrigger:{trigger:'.hero', start:'top top', end:'bottom top', scrub:.6}});

    /* Showcase dashboard drift (scrub) */
    var scDash = document.querySelector('.showcase .dash');
    if (scDash) gsap.fromTo(scDash, {y:56}, {y:-56, ease:'none',
      scrollTrigger:{trigger:'.showcase', start:'top bottom', end:'bottom top', scrub:.8}});

    /* Key Tools: scroll-driven tab swap with pinned right panel */
    ScrollTrigger.create({
      trigger:'#keytools', start:'top 15%', end:'+=1400', pin:'#ktPin', scrub:true, refreshPriority:1,
      onUpdate:function(self){
        var i = Math.min(2, Math.floor(self.progress * 3));
        ktSet(i);
      }
    });

    /* Dark panel entrance */
    gsap.from('.dark', {
      yPercent:6, borderRadius:'56px', ease:'none',
      scrollTrigger:{trigger:'.dark', start:'top 95%', end:'top 45%', scrub:true}
    });
  } else {
    /* Reduced motion / no GSAP: everything visible, key tools clickable only */
    document.querySelectorAll('[data-reveal]').forEach(function(el){ el.style.opacity=1; el.style.transform='none'; });
  }
})();
