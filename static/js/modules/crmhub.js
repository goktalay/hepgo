// CRM: Firma Yönetimi, Evrak Yönetimi ve Satış Yönetimi'ni tek modülde toplayan grup.
// Ayrı yetkisi yoktur: kullanıcı bu üç modülden en az birine erişebiliyorsa CRM görünür; sekmeler yetkiye göre süzülür.
import { icons } from '../icons.js';
import { h, svgIcon } from '../ui.js';

export const CRM_KIDS = [
  ['companies', 'Firma Yönetimi'],
  ['documents', 'Evrak Yönetimi'],
  ['sales', 'Satış Yönetimi'],
];

export const hasCrm = user => CRM_KIDS.some(([k]) => user.modules.includes(k));

// Alt modül sekmeleri (Üretim Yönetimi'ndeki gibi)
export function crmNav(active, ctx) {
  const tabs = CRM_KIDS.filter(([k]) => ctx.user.modules.includes(k)).map(([k, label]) =>
    h('button', { class: k === active ? 'on' : '', type: 'button', onclick: () => { location.hash = `#/${k}`; } }, svgIcon(icons[k]), label));
  return tabs.length > 1 ? h('div', { class: 'seg seg-tabs' }, tabs) : null;
}

// #/crm → erişilebilen ilk alt modüle yönlendirir
export async function render(view, params, ctx) {
  const first = CRM_KIDS.find(([k]) => ctx.user.modules.includes(k));
  location.replace(`#/${first ? first[0] : ''}`);
}
