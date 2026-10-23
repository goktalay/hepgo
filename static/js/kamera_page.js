// Dron kamerası AYRI PENCERE sayfası (/static/kamera.html?camera=<id>&task=<görev>&drone=<dron>): yalnız oynatıcı + yeşil HUD.
// Görev verilmişse HUD telemetrisi /ws/drone/live (watch task_id) ile gelir; HUD'daki seçiciyle kamera görevdeki başka drona bağlanabilir
// (PUT /api/drone/tasks/{görev}/cameras/{kamera}; field.live yazma izni). Pencere kapanınca akış kapanır.
import { initLang, t } from './i18n.js';
import './i18n.en.js';
import './i18n.en.extra.js';
import './i18n.en.extra2.js';
import './i18n.de.js';
import './i18n.fr.js';
import './i18n.es.js';
import './i18n.ar.js';
import './i18n.ru.js';
import { createPlayer, createTelemetryFeed } from './modules/drone_camera.js';

initLang();
const q = new URLSearchParams(location.search);
const camId = Number(q.get('camera')) || 0;
const taskId = Number(q.get('task')) || 0;
let droneId = Number(q.get('drone')) || null;
const root = document.getElementById('kp-root');
const titleEl = document.getElementById('kp-title');
const getJson = async url => { const r = await fetch(url, { credentials: 'same-origin' }); if (!r.ok) throw new Error(`${r.status}`); return r.json(); };

async function main() {
  if (!camId) { root.innerHTML = `<div class="kp-err">${t('Kamera seçilmedi')}</div>`; return; }
  let name = `#${camId}`, drones = [], canEdit = false, feed = null;
  try {
    if (taskId) {
      const tc = await getJson(`/api/drone/tasks/${taskId}/cameras`);
      drones = tc.drones || [];
      canEdit = !!tc.can_edit;
      const a = (tc.assigned || []).find(c => c.id === camId) || (tc.available || []).find(c => c.id === camId);
      if (a) { name = a.name; if (droneId == null) droneId = a.hud_drone_id ?? null; }
      feed = createTelemetryFeed(taskId);
    } else {
      const l = await getJson(`/api/drone/camera-list`);
      const c = l.find(x => x.id === camId);
      if (c) name = c.name;
    }
  } catch (e) {
    if (String(e.message) === '401' || String(e.message) === '403') { root.innerHTML = `<div class="kp-err">${t('Oturum yok ya da yetkiniz yok; HEPGO\'ya giriş yapın.')}</div>`; return; }
  }
  document.title = `${name} · ${t('Kamera')} · HEPGO`;
  titleEl.textContent = name;
  const hudOf = () => { const d = drones.find(x => x.drone_id === droneId); return d && feed ? feed.get(d.bridge_id, d.sysid) : null; };
  let sel = null;
  if (drones.length) {
    sel = document.createElement('select');
    sel.title = t('HUD: bağlı dron');
    sel.append(new Option(t('— dron —'), ''), ...drones.map(d => new Option(d.label, String(d.drone_id), false, d.drone_id === droneId)));
    sel.addEventListener('change', async () => {
      droneId = sel.value ? Number(sel.value) : null;
      if (canEdit && taskId) {
        try { await fetch(`/api/drone/tasks/${taskId}/cameras/${camId}`, { method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ drone_id: droneId }) }); } catch { /* yalnız yerel */ }
      }
    });
  }
  const p = createPlayer({ cameraId: camId, hud: true, getTelemetry: hudOf, droneSelect: sel });
  root.append(p.el);
  window.addEventListener('pagehide', () => { p.stop(); feed?.close(); });
}
main();
