// SIMUMAV oyun kabuğu — yer tutucu (ön yüz ajanı ezer). Oturum yoksa simapi 401'de tanıtıma yönlendirir.
import { api } from '/sim/api.js';
api.get('/api/session').then(s => { document.querySelector('#app .muted').textContent = `Hoş geldin, ${s.user.display_name}. Oyun arayüzü hazırlanıyor…`; }).catch(() => {});
