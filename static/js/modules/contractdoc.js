// Sözleşme metni görüntüleyici + yazdırma (Merkez ve firma ortak). Metin biçimi: '# başlık', '## alt başlık', '- madde',
// boş satır = paragraf, **kalın**. Metin HTML olarak yorumlanmaz (yalnızca metin düğümleri) ve çeviriye sokulmaz.
import { fmtDateTime } from '../ui.js';

function inline(doc, tag, s) {
  const el = doc.createElement(tag);
  for (const part of String(s).split(/(\*\*[^*]+\*\*)/)) {
    if (/^\*\*[^*]+\*\*$/.test(part)) { const b = doc.createElement('b'); b.textContent = part.slice(2, -2); el.append(b); }
    else if (part) el.append(doc.createTextNode(part));
  }
  return el;
}

export function docView(text, doc = document) {
  const root = doc.createElement('div');
  root.className = 'ct-doc';
  let ul = null, para = [];
  const flush = () => { if (para.length) { root.append(inline(doc, 'p', para.join(' '))); para = []; } };
  for (const raw of String(text || '').split('\n')) {
    const line = raw.trimEnd();
    if (/^#\s/.test(line)) { flush(); ul = null; root.append(inline(doc, 'h2', line.slice(2))); }
    else if (/^##\s/.test(line)) { flush(); ul = null; root.append(inline(doc, 'h3', line.slice(3))); }
    else if (/^-\s/.test(line)) { flush(); if (!ul) { ul = doc.createElement('ul'); root.append(ul); } ul.append(inline(doc, 'li', line.slice(2))); }
    else if (!line.trim()) { flush(); ul = null; }
    else { ul = null; para.push(line.trim()); }
  }
  flush();
  return root;
}

// Elektronik onay kaydı kutusu (kanıt)
export function proofRows(a) {
  return [['İmzalayan', [a.signer_name, a.signer_title].filter(Boolean).join(' · ')], ['E-posta', a.signer_email],
    ['Onay zamanı', a.accepted_at ? fmtDateTime(a.accepted_at) : ''], ['IP adresi', a.ip], ['Tarayıcı', a.user_agent],
    ['Metin parmak izi (SHA-256)', a.doc_hash || a.hash]].filter(r => r[1]);
}

// Yazdır / PDF: yalnız belge ve (varsa) onay kaydıyla ayrı pencere
export function printDoc({ title, sub, text, proof, company }) {
  const w = window.open('', '_blank');
  if (!w) return;
  const d = w.document;
  d.title = title;
  const style = d.createElement('style');
  style.textContent = `body{font:11pt/1.55 Georgia,'Times New Roman',serif;color:#111;margin:18mm 20mm;}
    .meta{font:9pt/1.4 -apple-system,Segoe UI,Arial,sans-serif;color:#555;margin-bottom:14pt;border-bottom:1px solid #ccc;padding-bottom:8pt}
    h2{font-size:16pt;margin:0 0 10pt} h3{font-size:11.5pt;margin:14pt 0 4pt} p,li{text-align:justify} ul{padding-left:18pt}
    .proof{margin-top:22pt;border:1px solid #999;padding:10pt 12pt;font:9pt/1.5 -apple-system,Segoe UI,Arial,sans-serif;page-break-inside:avoid}
    .proof b{display:block;font-size:10pt;margin-bottom:6pt} .proof table{border-collapse:collapse;width:100%}
    .proof td{padding:2pt 6pt 2pt 0;vertical-align:top} .proof td:first-child{color:#555;white-space:nowrap;width:1%}
    .mono{font-family:Menlo,Consolas,monospace;word-break:break-all}`;
  d.head.append(style);
  const meta = d.createElement('div');
  meta.className = 'meta';
  meta.textContent = [company, sub].filter(Boolean).join(' · ');
  d.body.append(meta, docView(text, d));
  if (proof) {
    const box = d.createElement('div');
    box.className = 'proof';
    const b = d.createElement('b'); b.textContent = 'Elektronik Onay Kaydı';
    const tbl = d.createElement('table');
    for (const [k, v] of proofRows(proof)) {
      const tr = d.createElement('tr');
      const a = d.createElement('td'); a.textContent = k;
      const c = d.createElement('td'); c.textContent = v; if (/SHA-256/.test(k)) c.className = 'mono';
      tr.append(a, c); tbl.append(tr);
    }
    box.append(b, tbl);
    d.body.append(box);
  }
  setTimeout(() => w.print(), 300);
}
