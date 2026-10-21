// Yazıcı listesi Excel dışa aktarımı: MAC birincil kimlik sütunu, MAC kaynağı, son görülen IP; MAC'siz yazıcı uyarısı.
// Çalıştırma: node tests/test_printers_export.mjs
import assert from 'node:assert/strict';
import { EXPORT_COLUMNS, macSourceLabel, printersExportSpec } from '../static/js/modules/printers_export.js';

const printers = [
  { name: '31', mac: 'FC:EE:28:0F:36:97', mac_source: 'arp', hw_id: 'K2Plus-3697', ip: '192.168.1.187', last_seen: '2026-10-21T11:12:55',
    mac_checked_at: '2026-10-21T11:00:00', live_state: 'HAZIR', model: 'Creality K2 Plus', rack_side: 'L', rack_level: 1, rack_slot: 3 },
  { name: '58', mac: null, hw_id: 'K2Plus-2CAA', ip: null, live_state: 'CEVRIMDISI' },
];
const spec = printersExportSpec(printers);
assert.deepEqual(spec.columns, EXPORT_COLUMNS);
const ci = name => spec.columns.indexOf(name);
assert.ok(ci('MAC adresi') === 1, 'MAC ikinci sütun (addan hemen sonra)');
assert.equal(spec.rows[0][ci('MAC adresi')], 'FC:EE:28:0F:36:97');
assert.equal(spec.rows[0][ci('MAC kaynağı')], 'Ağ taraması (ARP)');
assert.equal(spec.rows[0][ci('Son görülen IP')], '192.168.1.187');
assert.ok(spec.rows[0][ci('IP son görülme')] instanceof Date);
assert.equal(spec.rows[1][ci('MAC adresi')], 'MAC YOK');
assert.equal(spec.rows[1][ci('Son görülen IP')], 'bilinmiyor');
// MAC'siz yazıcı için sonda boş satır + uyarı satırı; satır genişliği sütun sayısı kadar
assert.equal(spec.rows.length, 4);
assert.ok(spec.rows.every(r => r.length === spec.columns.length));
assert.match(spec.rows[3][0], /^⚠ 1 yazıcının MAC adresi yok.*: 58$/);
// Hepsinin MAC'i varsa uyarı yok
assert.equal(printersExportSpec([printers[0]]).rows.length, 1);
assert.equal(macSourceLabel('elle'), 'Elle girildi');
assert.equal(macSourceLabel(null), '');
console.log('Yazıcı Excel dışa aktarımı (MAC sütunu) testleri geçti.');
