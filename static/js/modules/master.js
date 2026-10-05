// MASTER (sistem sahibi) modülü — "Veri & Yedek".
// KVKK: kişisel veri gösterilmez. Sistem sahibi şirketin tüm verisini tek ZIP'te indirir ve yedekleri görür/indirir.
import { api } from '../api.js';
import { clear, fmtDateTime, h, pageHead, t, toastError } from '../ui.js';

const bytes = b => (b == null ? '—' : b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : b >= 1e3 ? `${Math.round(b / 1e3)} KB` : `${b} B`);

export async function render(view, params, ctx) {
  if (!ctx.user.master) { clear(view, h('div', { class: 'card empty' }, 'Bu modül yalnızca sistem sahibine açıktır.')); return; }
  if (params[0] === 'ssh') { const m = await import('./ssh.js'); return m.render(view, params.slice(1), ctx); }
  let ov, backups;
  try {
    [ov, backups] = await Promise.all([api.get('/api/master/overview'), api.get('/api/master/backups')]);
  } catch (e) { toastError(e); return; }

  const stat = (label, value, tone = '') => h('div', { class: `stat ${tone}` }, h('b', null, value), h('span', null, label));

  // Tüm veriyi indir
  const exportCard = h('section', { class: 'card card-pad' },
    h('h3', null, 'Tüm veriyi indir'),
    h('p', { class: 'small muted' }, t('{company} şirketinin tüm verisi tek pakette (veritabanı + yüklenen dosyalar + anahtarlar).', { company: ov.company })),
    h('div', { class: 'stats mv-stats' },
      stat('Veritabanı', bytes(ov.db_bytes)),
      stat('Dosyalar', bytes(ov.uploads_bytes)),
      stat('Toplam', bytes(ov.total_bytes))),
    h('a', { class: 'btn primary', href: '/api/master/export', download: '' }, '⬇ Tüm veriyi ZIP indir'),
    h('p', { class: 'small muted' }, 'İndirme hazırlanırken birkaç saniye sürebilir. Paket yalnızca size özeldir.'));

  // Yedekler
  const ageTxt = ov.last_backup_age_h == null ? 'Henüz otomatik yedek yok'
    : t('Son yedek: {d} · {h} saat önce', { d: fmtDateTime(ov.last_backup.at), h: ov.last_backup_age_h });
  const backupCard = h('section', { class: 'card card-pad' },
    h('h3', null, 'Yedekler'),
    h('div', { class: `mv-backup-status ${ov.backup_ok ? 'ok' : 'warn'}` },
      h('b', null, ov.backup_ok ? '✓ Yedekleme güncel' : '⚠ Yedek kontrolü'),
      h('span', { class: 'small muted' }, ageTxt)),
    backups.length
      ? h('div', { class: 'mv-backups' }, backups.map(b => h('div', { class: 'mv-bk' },
          h('div', { class: 'grow' }, h('b', null, b.name),
            h('span', { class: 'small muted' }, `${b.scope === 'nightly' ? 'Otomatik' : 'Manuel'} · ${fmtDateTime(b.at)} · ${bytes(b.size)}`)),
          h('a', { class: 'btn sm', href: `/api/master/backups/download?name=${encodeURIComponent(b.name)}&scope=${b.scope}`, download: '' }, 'İndir'))))
      : h('div', { class: 'empty small muted' }, 'Yedek bulunamadı'));

  // SSH Erişim: kayıtlı uzak sunuculara (ör. fabrikadaki GX10) tarayıcıdan bağlan
  const sshCard = h('section', { class: 'card card-pad' },
    h('h3', null, 'SSH Erişim'),
    h('p', { class: 'small muted' }, t('Kayıtlı uzak sunuculara (ör. fabrikadaki makineler) tarayıcıdan bağlanıp komut çalıştırın. Parola / anahtar şifreli saklanır; her bağlantı denetim kaydına yazılır.')),
    h('a', { class: 'btn primary', href: '#/master/ssh' }, 'Sunucuları yönet'));

  clear(view, pageHead('Veri & Yedek', { back: '#/', sub: 'Sistem sahibi · veri ve yedekler' }),
    h('div', { class: 'mv-grid' }, exportCard, backupCard, sshCard));
}
