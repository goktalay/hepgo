// Toplantı ekranı ve toplantı özeti (Kişisel → Toplantılar).
// Ekran: düzenleyen "Toplantıyı Başlat" der; başlayınca herkes kendi notunu alır (otomatik kaydedilir), düzenleyen ses
// kaydını açıp kapatır (kayıt sürerken parça parça sunucuya yüklenir) ve "Toplantıyı Bitir" der. Katılımcılar canlı görünür.
// Özet: kayıt metne çevrilip konuşmacılara ayrılınca; tanımsız kişiler kişiye atanır (ses profili öğrenilir), kararlar /
// yapılacaklar / sorular, notlar ve konuşmacı adlı tam döküm; yazdırılabilir.
import { api } from '../api.js';
import { foot, head as printHead, printPage } from '../print.js';
import { avatar, clear, confirmDialog, field, fmtDateTime, h, modal, moduleToolbar, onLeave, pageHead, t, toast, toastError } from '../ui.js';

const STATUS_TEXT = { DUZENLEYEN: 'Düzenleyen', KATILIYOR: 'Katılıyor', BELKI: 'Belki', KATILMIYOR: 'Katılmıyor', BEKLIYOR: 'Yanıt bekleniyor' };
const clock = s => { s = Math.max(0, Math.floor(s)); const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return `${hh ? `${hh}:` : ''}${String(mm).padStart(hh ? 2 : 1, '0')}:${String(ss).padStart(2, '0')}`; };
const since = iso => (Date.now() - new Date(iso).getTime()) / 1000;

// ---------- Toplantı ekranı
export async function renderRoom(view, id) {
  let r = await api.get(`/api/meetings/${id}/room`);
  const org = r.can_edit;
  const timer = h('b', { class: 'mr-timer' });
  const stateChip = h('span', { class: 'mr-state' });
  const right = h('div', { class: 'module-toolbar' });   // düzenleyenin eylem düğmeleri (Başlat / Bitir / Özet); draw() doldurur
  const people = h('ul', { class: 'mr-people' });
  const note = h('textarea', { class: 'input mr-note', placeholder: 'Toplantı notlarınız… (otomatik kaydedilir)' }, r.my_note || '');
  const saved = h('span', { class: 'small muted' });
  const recBox = h('div', { class: 'mr-rec' });
  const info = h('div', { class: 'card card-pad mr-info' });
  clear(view, pageHead(r.title, { back: '#/meetings', sub: h('span', null, stateChip, ' ', timer) }), right,
    h('div', { class: 'mr-grid' },
      h('section', { class: 'card card-pad' }, h('h3', null, 'Katılımcılar'), people),
      h('section', { class: 'card card-pad mr-notes' }, h('div', { class: 'mr-notes-head' }, h('h3', null, 'Notlarım'), saved), note,
        h('p', { class: 'small muted' }, 'Notlarınız toplantı bitince özete eklenir ve katılımcılar görür. Madde madde yazdığınız kararlar ve yapılacaklar özette ayrıca listelenir.')),
      h('div', { class: 'mr-side' }, recBox, info)));

  // --- ses kaydı (yalnızca düzenleyen)
  const rec = { mr: null, stream: null, aid: null, seq: 0, queue: Promise.resolve(), started: 0, analyser: null, raf: 0 };
  const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
  async function startRec() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { toast('Bu tarayıcı ses kaydını desteklemiyor', 'err'); return; }
    try {
      rec.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: true } });
    } catch { toast('Mikrofon izni verilmedi', 'err'); return; }
    const type = types.find(t => MediaRecorder.isTypeSupported?.(t)) || '';
    const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
    try { rec.aid = (await api.post(`/api/meetings/${id}/audio/start?ext=${ext}`)).id; } catch (err) { toastError(err); rec.stream.getTracks().forEach(t => t.stop()); return; }
    rec.seq = 0;
    rec.mr = new MediaRecorder(rec.stream, type ? { mimeType: type } : undefined);
    rec.mr.ondataavailable = ev => {
      if (!ev.data.size) return;
      const seq = rec.seq++, aid = rec.aid;
      rec.queue = rec.queue.then(() => sendChunk(aid, seq, ev.data));   // sırayla; bağlantı koparsa yeniden dener
    };
    rec.mr.start(5000);
    rec.started = Date.now();
    // ses düzeyi göstergesi
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    rec.analyser = ctx.createAnalyser();
    rec.analyser.fftSize = 512;
    ctx.createMediaStreamSource(rec.stream).connect(rec.analyser);
    rec.ctx = ctx;
    drawRec();
  }
  async function sendChunk(aid, seq, blob, tries = 0) {
    try {
      const res = await fetch(`/api/meetings/${id}/audio/${aid}/chunk?seq=${seq}`, { method: 'POST', body: blob, credentials: 'same-origin' });
      if (!res.ok) throw new Error(await res.text());
    } catch (err) {
      if (tries < 5) { await new Promise(res => setTimeout(res, 2000 * (tries + 1))); return sendChunk(aid, seq, blob, tries + 1); }
      toast('Ses kaydının bir parçası gönderilemedi', 'err');
    }
  }
  async function stopRec() {
    if (!rec.mr) return;
    const aid = rec.aid;
    await new Promise(res => { rec.mr.onstop = res; rec.mr.stop(); });
    rec.stream.getTracks().forEach(t => t.stop());
    rec.ctx?.close();
    cancelAnimationFrame(rec.raf);
    rec.mr = null;
    await rec.queue;
    await api.post(`/api/meetings/${id}/audio/${aid}/stop`).catch(() => {});
    drawRec();
  }
  function drawRec() {
    const on = !!rec.mr;
    const level = h('div', { class: 'mr-level' }, h('i'));
    clear(recBox, h('div', { class: 'card card-pad' },
      h('h3', null, 'Ses kaydı'),
      on ? h('div', { class: 'mr-recon' }, h('span', { class: 'chat-rec-dot' }), h('b', { class: 'mr-rectime' }, '0:00'), ' kaydediliyor', level)
        : r.recording ? h('div', { class: 'mr-recon' }, h('span', { class: 'chat-rec-dot' }), ' Kayıt yapılıyor (düzenleyenin cihazından)')
          : h('div', { class: 'small muted' }, r.recordings ? t('{n} kayıt alındı', { n: r.recordings }) : 'Kayıt alınmadı'),
      org && r.state === 'DEVAM' ? h('button', { class: `btn ${on ? 'danger' : 'primary'}`, type: 'button', style: { marginTop: '10px' },
        onclick: async e => { e.target.disabled = true; try { on ? await stopRec() : await startRec(); } finally { e.target.disabled = false; } refresh(); } },
      on ? '⏹ Kaydı Durdur' : '⏺ Kaydı Başlat') : null,
      org && r.state === 'DEVAM' && !r.audio_available ? h('p', { class: 'small muted' }, 'Konuşma tanıma bu sunucuda kurulu değil; kayıt saklanır ama metne çevrilmez.') : null,
      org && r.state === 'DEVAM' ? h('p', { class: 'small muted' }, 'Kayıt bu cihazın mikrofonundan alınır; sayfa açık kalmalıdır. Toplantı bitince konuşmacılara göre ayrılıp metne çevrilir.') : null));
    if (on && rec.analyser) {
      const data = new Uint8Array(rec.analyser.fftSize);
      const bar = level.querySelector('i'), tm = recBox.querySelector('.mr-rectime');
      const loop = () => {
        rec.analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
        bar.style.width = `${Math.min(100, peak / 128 * 180)}%`;
        tm.textContent = clock((Date.now() - rec.started) / 1000);
        rec.raf = requestAnimationFrame(loop);
      };
      loop();
    }
  }
  onLeave(() => { if (rec.mr) stopRec(); });
  window.addEventListener('beforeunload', ev => { if (rec.mr) { ev.preventDefault(); ev.returnValue = ''; } }, { once: true });

  // --- notlar: yazdıkça 1,5 sn sonra kaydet
  let noteTimer;
  note.addEventListener('input', () => {
    saved.textContent = 'yazılıyor…';
    clearTimeout(noteTimer);
    noteTimer = setTimeout(async () => {
      try { await api.put(`/api/meetings/${id}/notes`, { body: note.value }); saved.textContent = t('kaydedildi {time}', { time: new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }) }); }
      catch (err) { saved.textContent = err.message; }
    }, 1500);
  });

  function draw() {
    const st = r.state;
    stateChip.className = `mr-state ${st}`;
    stateChip.textContent = { BASLAMADI: 'Başlamadı', DEVAM: '● Devam ediyor', BITTI: 'Bitti' }[st];
    note.disabled = st !== 'DEVAM';
    if (st === 'BASLAMADI') note.placeholder = 'Toplantı başlayınca not alabilirsiniz';
    clear(people, r.people.map(p => h('li', null, h('span', { class: `mr-dot ${p.online ? 'on' : ''}` }), avatar(p, 'sm'),
      h('div', { class: 'grow' }, h('b', null, p.full_name), h('small', null, STATUS_TEXT[p.status] || p.status)),
      p.online ? h('small', { class: 'mr-in' }, 'ekranda') : null)));
    clear(info, h('h3', null, 'Toplantı'),
      h('dl', { class: 'sys-kv' }, h('dt', null, 'Planlanan'), h('dd', null, fmtDateTime(r.starts_at)),
        r.location ? [h('dt', null, 'Yer'), h('dd', null, r.location)] : null, h('dt', null, 'Düzenleyen'), h('dd', null, r.organizer)),
      r.note ? h('div', { class: 'call-msg' }, h('small', null, 'Talep notu'), r.note) : null);
    clear(right,
      org && st === 'BASLAMADI' ? h('button', { class: 'btn primary', type: 'button', onclick: async () => {
        try { r = await api.post(`/api/meetings/${id}/start`); toast('Toplantı başladı'); draw(); } catch (err) { toastError(err); }
      } }, '▶ Toplantıyı Başlat') : null,
      org && st === 'DEVAM' ? h('button', { class: 'btn danger', type: 'button', onclick: async () => {
        if (!await confirmDialog('Toplantıyı bitir', 'Toplantı bitirilsin mi? Notlar kilitlenir; ses kaydı varsa metne çevrilip konuşmacılara ayrılır.', { okLabel: 'Toplantıyı Bitir', danger: true })) return;
        if (rec.mr) await stopRec();
        clearTimeout(noteTimer);
        if (!note.disabled) await api.put(`/api/meetings/${id}/notes`, { body: note.value }).catch(() => {});
        try { await api.post(`/api/meetings/${id}/end`); toast('Toplantı bitti'); location.hash = `#/meetings/${id}/summary`; } catch (err) { toastError(err); }
      } }, '■ Toplantıyı Bitir') : null,
      st === 'BITTI' ? h('a', { class: 'btn primary', href: `#/meetings/${id}/summary` }, 'Toplantı Özeti') : null);
    if (!rec.mr) drawRec();
  }
  const tick = () => {
    if (r.state === 'DEVAM') timer.textContent = clock(since(r.started_at));
    else if (r.state === 'BITTI') timer.textContent = '';
    else timer.textContent = t('· planlanan {d}', { d: fmtDateTime(r.starts_at) });
  };
  async function refresh() {
    try {
      const prev = r.state;
      r = await api.get(`/api/meetings/${id}/room`);
      if (prev !== r.state && r.state === 'DEVAM' && !org) toast('Toplantı başladı; not alabilirsiniz');
      if (prev !== r.state && r.state === 'BITTI' && !org) toast('Toplantı bitti');
      draw();
    } catch { /* bir sonraki turda */ }
  }
  draw();
  tick();
  const t1 = setInterval(tick, 1000), t2 = setInterval(refresh, 5000);
  onLeave(() => { clearInterval(t1); clearInterval(t2); });
}

// ---------- Toplantı özeti
export async function renderSummary(view, id) {
  let s;
  const load = async () => { s = await api.get(`/api/meetings/${id}/summary`); };
  await load();
  let users = null;
  let timer = null;
  onLeave(() => clearInterval(timer));
  const audio = new Audio();
  const play = url => { audio.src = url; audio.play().catch(() => {}); };
  const colors = ['#2563eb', '#16a34a', '#d97706', '#9333ea', '#dc2626', '#0891b2', '#db2777', '#65a30d'];

  async function draw() {
    const org = s.can_edit;
    const colorOf = new Map(s.speakers.map((sp, i) => [sp.id, colors[i % colors.length]]));
    const nameOf = sp => sp.full_name || sp.label;
    const dur = s.started_at && s.ended_at ? (new Date(s.ended_at) - new Date(s.started_at)) / 1000 : 0;
    const known = s.speakers.filter(x => x.user_id), unknown = s.speakers.filter(x => !x.user_id);
    if (org && unknown.length && !users) users = await api.get('/api/people').catch(() => []);
    const assignSel = sp => {
      const sel = h('select', { class: 'input' }, h('option', { value: '' }, sp.user_id ? '— Atamayı kaldır —' : 'Kişiye ata…'),
        (users || []).map(u => h('option', { value: u.id, selected: u.id === sp.user_id }, u.full_name)));
      sel.addEventListener('change', async () => {
        try { s = await api.put(`/api/meetings/${id}/speakers/${sp.id}`, { user_id: sel.value ? Number(sel.value) : null }); toast(sel.value ? 'Konuşmacı atandı; ses profili öğrenildi' : 'Atama kaldırıldı'); draw(); }
        catch (err) { toastError(err); }
      });
      return sel;
    };
    const spRow = sp => h('div', { class: 'ms-sp' },
      h('i', { class: 'ms-sw', style: { background: colorOf.get(sp.id) } }),
      h('div', { class: 'grow' }, h('b', null, nameOf(sp)), h('small', null, t('{d} konuşma · %{share}{auto}', { d: clock(sp.seconds), share: sp.share, auto: sp.auto ? t(' · sesinden tanındı') : '' }))),
      h('button', { class: 'btn sm', type: 'button', title: 'Sesinden örnek dinle', onclick: () => play(`/api/meetings/${id}/speakers/${sp.id}/sample`) }, '▶ Dinle'),
      org ? (users ? assignSel(sp) : h('button', { class: 'btn sm', type: 'button', onclick: async () => { users = await api.get('/api/people'); draw(); } }, 'Kişiye ata')) : null);
    const pointList = (title, items, empty) => h('section', { class: 'card card-pad ms-points' }, h('h3', null, title),
      items.length ? h('ul', null, items.map(p => h('li', null, h('span', null, p.text), h('small', null, ` — ${p.speaker}${p.when ? ' · ⏰' : ''}`))))
        : h('div', { class: 'small muted' }, empty));
    const processing = s.process_status === 'ISLENIYOR';
    clear(view,
      pageHead(t('Toplantı özeti · {title}', { title: s.title }), { back: '#/meetings', sub: t('{start} – {end} · {dur} · düzenleyen {org}', { start: fmtDateTime(s.started_at), end: s.ended_at ? s.ended_at.slice(11, 16) : '', dur: clock(dur), org: s.organizer }) }),
      moduleToolbar(h('button', { class: 'btn', type: 'button', onclick: () => printSummary(s, dur).catch(toastError) }, '🖨 Yazdır')),
      processing ? h('div', { class: 'alert info ms-proc' }, h('span', { class: 'chat-rec-dot' }), ' Ses kaydı metne çevriliyor ve konuşmacılara ayrılıyor… Bu sayfa kendiliğinden yenilenir.') : null,
      s.process_status === 'HATA' ? h('div', { class: 'alert warn' }, t('Ses işlenemedi: {err} ', { err: s.process_error || '' }),
        org ? h('button', { class: 'btn sm', type: 'button', onclick: async () => { await api.post(`/api/meetings/${id}/reprocess`); await load(); draw(); watch(); } }, 'Yeniden dene') : null) : null,
      h('div', { class: 'db-kpis ms-kpis' },
        [['Süre', clock(dur)], ['Katılımcı', s.people.length], ['Konuşmacı', s.speakers.length], ['Kayıt', clock(s.recorded_seconds)],
          ['Not alan', s.notes.length]].map(([l, v]) => h('div', { class: 'db-kpi' }, h('b', null, v), h('span', null, l)))),
      h('div', { class: 'ms-grid' },
        h('section', { class: 'card card-pad' }, h('h3', null, 'Konuşmacılar'),
          s.speakers.length ? [
            known.length ? h('div', { class: 'ms-bar' }, s.speakers.map(sp => h('i', { title: `${nameOf(sp)} %${sp.share}`, style: { width: `${sp.share}%`, background: colorOf.get(sp.id) } }))) : null,
            known.map(spRow),
            unknown.length ? h('div', { class: 'ms-unknown' }, h('h4', null, t('Tanımsız kişiler ({n})', { n: unknown.length })),
              h('p', { class: 'small muted' }, org ? 'Sesini dinleyip kişiye atayın; kişinin ses profili öğrenilir ve sonraki toplantılarda otomatik tanınır. Aynı kişiyi iki gruba atarsanız birleşir.'
                : 'Düzenleyen bu sesleri kişilere atayabilir.'), unknown.map(spRow)) : null]
            : h('div', { class: 'small muted' }, processing ? 'Hazırlanıyor…' : 'Ses kaydı yok')),
        h('section', { class: 'card card-pad' }, h('h3', null, 'Katılımcılar'),
          h('ul', { class: 'mr-people' }, s.people.map(p => h('li', null, avatar(p, 'sm'), h('div', { class: 'grow' }, h('b', null, p.full_name),
            h('small', null, `${STATUS_TEXT[p.status] || p.status}${s.joined.includes(p.id) || p.status === 'DUZENLEYEN' ? ' · ekrana katıldı' : ''}`))))))),
      h('div', { class: 'ms-grid three' },
        pointList('Kararlar', s.points.decisions, 'Kararlaştırılan bir şey yakalanmadı'),
        pointList('Yapılacaklar', s.points.actions, 'Yapılacak iş yakalanmadı'),
        pointList('Sorular', s.points.questions, 'Soru yok')),
      h('section', { class: 'card card-pad' }, h('div', { class: 'ms-notes-head' }, h('h3', null, 'Katılımcı notları'),
        !s.notes.some(n => n.user_id === s.me) ? h('button', { class: 'btn sm', type: 'button', onclick: () => editNote(null) }, '＋ Notumu Ekle') : null),
        s.notes.length ? h('div', { class: 'ms-notes' }, s.notes.map(n => h('div', { class: 'ms-note' },
          h('div', { class: 'ms-note-top' }, h('b', null, n.full_name),
            n.user_id === s.me || org ? h('button', { class: 'link-btn small', type: 'button', onclick: () => editNote(n) }, 'Düzenle') : null),
          h('div', { class: 'ms-note-body' }, n.body),
          n.edited_by_name ? h('div', { class: 'small muted' }, t('Toplantıdan sonra {name} düzenledi · {d}', { name: n.edited_by_name, d: fmtDateTime(n.updated_at) })) : null)))
          : h('div', { class: 'small muted' }, 'Not alınmadı')),
      h('section', { class: 'card card-pad' }, h('h3', null, t('Konuşma dökümü ({n})', { n: s.segments.length })),
        s.segments.length ? h('div', { class: 'ms-transcript' }, s.segments.map(g => h('div', { class: 'ms-line' },
          h('button', { class: 'ms-play', type: 'button', title: 'Dinle', onclick: () => play(`/api/meetings/${id}/segments/${g.id}/audio`) }, '▶'),
          h('span', { class: 'ms-time' }, (g.at || '').slice(11, 16)),
          h('b', { class: 'ms-who', style: { color: colorOf.get(g.speaker_id) || 'var(--muted)' } }, g.speaker),
          h('span', null, g.text))))
          : h('div', { class: 'small muted' }, processing ? 'Hazırlanıyor…' : 'Döküm yok')),
      h('p', { class: 'small muted' }, 'Kararlar, yapılacaklar ve sorular döküm ve notlardan anahtar ifadelerle seçilir; konuşmacı adları atamaya göre güncellenir.'));
  }
  // Toplantı bittikten sonra not düzenleme: herkes kendi notunu, düzenleyen katılımcıların notlarını
  function editNote(n) {
    const body = h('textarea', { class: 'input', rows: 12 }, n?.body || '');
    modal({
      title: n ? t('{name} · Notu Düzenle', { name: n.full_name }) : 'Notumu Ekle', wide: true,
      body: h('div', null, field('Not', body, 'Madde satırları (- ile başlayan) kararlar ve yapılacaklar arasına da alınır')),
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        await api.put(`/api/meetings/${id}/notes`, { body: body.value, user_id: n && n.user_id !== s.me ? n.user_id : null });
        toast('Not kaydedildi');
        await load();
        draw();
      } }],
    });
    body.focus();
  }
  function watch() {
    clearInterval(timer);
    if (s.process_status === 'ISLENIYOR') timer = setInterval(async () => { await load().catch(() => {}); draw(); if (s.process_status !== 'ISLENIYOR') clearInterval(timer); }, 5000);
  }
  await draw();
  watch();
}

// Yazdırılabilir toplantı özeti (A4): başlık, katılımcılar, konuşmacılar, kararlar, yapılacaklar, sorular, notlar, döküm
async function printSummary(s, dur) {
  const meta = await api.get('/api/meta').catch(() => ({}));
  const company = meta.company || '';
  const clockTxt = sec => { const m = Math.round((sec || 0) / 60); return m >= 60 ? t('{h} sa {m} dk', { h: Math.floor(m / 60), m: m % 60 }) : t('{m} dk', { m }); };
  const list = (title, items, empty) => h('section', { class: 'mp-sec' }, h('h2', null, title),
    items.length ? h('ul', null, items.map(p => h('li', null, p.text, h('small', null, ` — ${p.speaker}`)))) : h('p', { class: 'mp-empty' }, empty));
  const page = h('div', { class: 'mp-doc' },
    printHead(company, 'TOPLANTI ÖZETİ', [['Toplantı', s.title], ['Tarih', `${fmtDateTime(s.started_at)} – ${s.ended_at ? s.ended_at.slice(11, 16) : ''}`],
      ['Süre', clockTxt(dur)], ['Düzenleyen', s.organizer], ...(s.location ? [['Yer', s.location]] : [])]),
    h('section', { class: 'mp-sec' }, h('h2', null, 'Katılımcılar'), h('p', null, s.people.map(p => p.full_name).join(', ') || '—')),
    s.speakers.length ? h('section', { class: 'mp-sec' }, h('h2', null, 'Konuşmacılar'),
      h('table', { class: 'mp-table' }, h('tbody', null, s.speakers.map(sp => h('tr', null, h('td', null, sp.full_name || sp.label),
        h('td', null, `${clockTxt(sp.seconds)} · %${sp.share}`)))))) : null,
    list('Kararlar', s.points.decisions, 'Kararlaştırılan bir şey yakalanmadı'),
    list('Yapılacaklar', s.points.actions, 'Yapılacak iş yakalanmadı'),
    list('Sorular', s.points.questions, 'Soru yok'),
    h('section', { class: 'mp-sec' }, h('h2', null, 'Katılımcı notları'),
      s.notes.length ? s.notes.map(n => h('div', { class: 'mp-note' }, h('b', null, n.full_name), h('div', { class: 'mp-pre' }, n.body))) : h('p', { class: 'mp-empty' }, 'Not alınmadı')),
    s.segments.length ? h('section', { class: 'mp-sec' }, h('h2', null, 'Konuşma dökümü'),
      s.segments.map(g => h('div', { class: 'mp-line' }, h('span', { class: 'mp-time' }, (g.at || '').slice(11, 16)), h('b', null, `${g.speaker}: `), g.text))) : null,
    foot(company, t('Toplantı özeti · Yazdırma: {d}', { d: fmtDateTime(new Date().toISOString()) })));
  printPage(page, `Toplantı özeti ${s.title}`);
}
