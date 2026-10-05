"""İSG / KKD görüntü-işleme — kamera karesinde kask/eldiven gibi kişisel koruyucu donanım (KKD) tespiti.

Görüntü İşleme entegrasyonunun 2. özelliği (İSG). Yüz tanımayla aynı kareyi kullanır: camera_service, tanıdığı
personelin zorunlu KKD'sini (İK'da tanımlı) bu modülle kamerada denetler; eksikse isg_alarms üretir.

MODEL FABRİKAYA AYRICA YÜKLENİR (çekirdek depoya dahil değildir):
  vendor/models/ppe.onnx     → YOLOv8 export (tek çıkış: [1, 4+nc, N] ya da [1, N, 4+nc])
  vendor/models/ppe.labels   → her satır bir sınıf adı (model çıkış sırasıyla)
Etiketler İngilizce olabilir; _ALIAS tablosu PPE anahtarlarına eşler (hardhat→kask, vest→yelek, gloves→eldiven…).
'no-...' (ör. no-helmet) sınıfları EKSİK (neg) işaretidir. Model ya da etiket yoksa available()=False → özellik
tamamen pasiftir ve yüz tanımayı hiçbir şekilde etkilemez (çağıran taraf erken döner)."""
import threading

from . import config

# camera denetimi yapılabilen KKD anahtarları (hr.PPE_ITEMS + employees.ppe_required ile birebir).
PPE_CLASSES = ('kask', 'eldiven', 'gozluk', 'yelek', 'maske', 'kulaklik', 'ayakkabi', 'tulum')

# Yaygın (çoğunlukla İngilizce) model etiketlerinden PPE anahtarına eşleme. Küçük harfe indirilip ' '→'-' ile aranır.
_ALIAS = {
    'hardhat': 'kask', 'hard-hat': 'kask', 'helmet': 'kask', 'kask': 'kask', 'baret': 'kask',
    'gloves': 'eldiven', 'glove': 'eldiven', 'eldiven': 'eldiven',
    'goggles': 'gozluk', 'glasses': 'gozluk', 'safety-glasses': 'gozluk', 'gozluk': 'gozluk',
    'vest': 'yelek', 'safety-vest': 'yelek', 'hi-vis': 'yelek', 'hi-vis-vest': 'yelek', 'yelek': 'yelek',
    'mask': 'maske', 'face-mask': 'maske', 'maske': 'maske',
    'earmuffs': 'kulaklik', 'ear-protection': 'kulaklik', 'kulaklik': 'kulaklik',
    'boots': 'ayakkabi', 'safety-boots': 'ayakkabi', 'shoes': 'ayakkabi', 'ayakkabi': 'ayakkabi',
    'coverall': 'tulum', 'suit': 'tulum', 'tulum': 'tulum',
}

_lock = threading.Lock()
_state = {'tried': False, 'sess': None, 'labels': None, 'mapped': None, 'input': 640}


def _paths():
    d = config.BASE_DIR / 'vendor' / 'models'
    onnx = next((d / n for n in ('ppe.onnx', 'ppe_yolo.onnx', 'kkd.onnx') if (d / n).exists()), None)
    labels = next((d / n for n in ('ppe.labels', 'ppe.names', 'kkd.labels') if (d / n).exists()), None)
    return onnx, labels


def available():
    """Model + etiket dosyası mevcut mu? Değilse İSG tespiti tamamen pasiftir."""
    onnx, labels = _paths()
    return bool(onnx and labels)


def _key_for(name):
    n = (name or '').strip().lower()
    base = n
    neg = n.startswith('no-') or n.startswith('no_') or n.startswith('no ') or n == 'none'
    if neg:
        base = n[3:].lstrip('-_ ')
    return _ALIAS.get(n.replace(' ', '-')) or _ALIAS.get(base.replace(' ', '-')) or _ALIAS.get(base), neg


def _ensure():
    if _state['tried']:
        return _state['sess'] is not None
    with _lock:
        if _state['tried']:
            return _state['sess'] is not None
        _state['tried'] = True
        onnx, labels = _paths()
        if not (onnx and labels):
            return False
        try:
            import onnxruntime as ort
            names = [ln.strip() for ln in labels.read_text(encoding='utf-8').splitlines() if ln.strip()]
            _state['labels'] = names
            _state['mapped'] = [_key_for(n) for n in names]   # (key, neg) çiftleri
            so = ort.SessionOptions(); so.intra_op_num_threads = 2
            _state['sess'] = ort.InferenceSession(str(onnx), so, providers=['CPUExecutionProvider'])
            inp = _state['sess'].get_inputs()[0]
            if inp.shape and len(inp.shape) == 4 and isinstance(inp.shape[3], int):
                _state['input'] = int(inp.shape[3])
        except Exception:   # noqa: BLE001 — model okunamazsa özellik pasif kalır
            _state['sess'] = None
        return _state['sess'] is not None


def detect(frame_bgr, conf=0.35, iou=0.45):
    """YOLOv8-ONNX ile KKD tespiti. Dönüş: [{'key','neg','box':[x,y,w,h],'score'}] (orijinal kare pikselinde).
    'neg'=True → model KKD'nin YOK halini tespit etti (ör. 'no-helmet'). Model yoksa []."""
    if not _ensure():
        return []
    try:
        import numpy as np
        import cv2
        sess = _state['sess']; S = _state['input']
        h0, w0 = frame_bgr.shape[:2]
        r = min(S / w0, S / h0)
        nw, nh = int(round(w0 * r)), int(round(h0 * r))
        dx, dy = (S - nw) // 2, (S - nh) // 2
        canvas = np.full((S, S, 3), 114, np.uint8)
        canvas[dy:dy + nh, dx:dx + nw] = cv2.resize(frame_bgr, (nw, nh))
        blob = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        out = sess.run(None, {sess.get_inputs()[0].name: blob})[0]
        o = out[0]
        if o.shape[0] < o.shape[1]:   # [4+nc, N] → [N, 4+nc]
            o = o.T
        mapped = _state['mapped'] or []
        boxes, scores, keys, negs = [], [], [], []
        for row in o:
            cls = row[4:]
            ci = int(np.argmax(cls)); sc = float(cls[ci])
            if sc < conf or ci >= len(mapped):
                continue
            key, neg = mapped[ci]
            if key is None:
                continue
            cx, cy, bw, bh = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            x = (cx - bw / 2 - dx) / r; y = (cy - bh / 2 - dy) / r
            boxes.append([x, y, bw / r, bh / r]); scores.append(sc); keys.append(key); negs.append(neg)
        if not boxes:
            return []
        idx = cv2.dnn.NMSBoxes([[int(b[0]), int(b[1]), int(b[2]), int(b[3])] for b in boxes], scores, conf, iou)
        out_list = []
        for i in (idx if idx is not None else []):
            j = int(i[0]) if hasattr(i, '__len__') else int(i)
            out_list.append({'key': keys[j], 'neg': negs[j], 'box': [round(v, 1) for v in boxes[j]], 'score': round(scores[j], 3)})
        return out_list
    except Exception:   # noqa: BLE001 — tespit hatası yüz tanımayı etkilememeli
        return []


def _overlap(a, b):
    """İki kutunun (x,y,w,h) kesişim alanının b'ye oranı (b ne kadarı a içinde)."""
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    area = bw * bh
    return inter / area if area > 0 else 0.0


def body_region(face_box, w, h):
    """Yüz kutusundan (x,y,w,h) kabaca gövde bölgesi (baş + torso + bacak) — KKD tespitini kişiye bağlamak için."""
    fx, fy, fw, fh = face_box
    bx = max(0.0, fx - fw * 1.0)
    by = max(0.0, fy - fh * 0.6)
    bw = min(w - bx, fw * 3.0)
    bh = min(h - by, fh * 7.0)
    return [bx, by, bw, bh]


def missing_for(required, dets, face_box, w, h):
    """Bu kişi için eksik KKD listesi. required: ['kask',...]. dets: detect() çıktısı. Kişinin gövde bölgesiyle
    örtüşen tespitlere bakar: pozitif tespit varsa 'var', yoksa (ya da 'no-...' tespiti varsa) 'eksik'."""
    if not required:
        return []
    region = body_region(face_box, w, h)
    present, negative = set(), set()
    for d in dets:
        if _overlap(region, d['box']) < 0.12:
            continue
        if d['neg']:
            negative.add(d['key'])
        else:
            present.add(d['key'])
    miss = []
    for k in required:
        if k in present:
            continue
        # pozitif tespit yoksa: 'no-...' sınıfı gördüysek kesin eksik; hiç görmediysek de (takmıyor say) eksik
        miss.append(k)
    return miss
