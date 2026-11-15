"""İş Güvenliği — görüntü çıkarımı (nesne / KKD / vücut duruşu).

Tek arka uç: OpenCV DNN. OpenCV CUDA ile derlenmişse (fabrika makinesi) modeller GPU'da yarı duyarlıkla (FP16)
koşar; değilse ya da GPU'da ilk çıkarım hata verirse CPU'ya düşer. Görüntü makineden dışarı çıkmaz.

MODELLER (çekirdek depoya dahil değildir; `tools/worksafety_models.py` indirir → vendor/models/):
  yolox_s.onnx      nesne (COCO 80 sınıf: kişi, araç, çanta, telefon …)      Apache-2.0
  ppe.onnx/.labels  KKD (YOLOv8; baret, yelek, eldiven, gözlük, maske, düşme, merdiven)   CC-BY-4.0
  rtmpose_s.onnx    vücut duruşu (17 eklem; REBA / RULA, düşme, tırmanma)   Apache-2.0
  ws_*.onnx/.labels EK modeller (YOLOv8 biçimi) — forklift ya da eksik KKD sınıfları için genişleme noktası.
Bir model yoksa ona bağlı kurallar "model gerekli" olarak pasif kalır; sonuç uydurulmaz."""
import logging
import threading

import cv2
import numpy as np

from . import config

log = logging.getLogger('worksafety')
MODEL_DIR = config.BASE_DIR / 'vendor' / 'models'

# İndirilebilir modeller (tools/worksafety_models.py bu tabloyu kullanır; sha256 doğrulanır)
MODELS = {
    'yolox_s.onnx': {
        'url': 'https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx',
        'sha256': 'c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063', 'license': 'Apache-2.0', 'role': 'objects'},
    'yolox_tiny.onnx': {
        'url': 'https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx',
        'sha256': '427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7', 'license': 'Apache-2.0', 'role': 'objects (yedek, küçük)'},
    'ppe.onnx': {
        'url': 'https://huggingface.co/Hexmon/vyra-yolo-ppe-detection/resolve/main/best.onnx',
        'sha256': 'b99fed37bae1d111ddb622a0ef9077d42918a4daebd4a0bffbd8faaba273f246', 'license': 'CC-BY-4.0', 'role': 'ppe'},
    'rtmpose_s.onnx': {
        'url': 'https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-s_simcc-body7_pt-body7_420e-256x192-acd4a1ef_20230504.zip',
        'member': 'end2end.onnx', 'license': 'Apache-2.0', 'role': 'pose'},
}
PPE_LABELS = ['Fall-Detected', 'Gloves', 'Goggles', 'Hardhat', 'Ladder', 'Mask', 'NO-Gloves', 'NO-Goggles', 'NO-Hardhat',
              'NO-Mask', 'NO-Safety Vest', 'Person', 'Safety Cone', 'Safety Vest']

COCO = ['person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light', 'fire hydrant',
        'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe',
        'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee', 'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat',
        'baseball glove', 'skateboard', 'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl',
        'banana', 'apple', 'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
        'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard', 'cell phone', 'microwave',
        'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier', 'toothbrush']
VEHICLES = ('forklift', 'car', 'truck', 'bus', 'motorcycle', 'bicycle', 'vehicle')

# Model etiketi (küçük harf, boşluk → '-') → KKD anahtarı
PPE_ALIAS = {
    'hardhat': 'hardhat', 'hard-hat': 'hardhat', 'helmet': 'hardhat', 'safety-helmet': 'hardhat', 'baret': 'hardhat', 'kask': 'hardhat',
    'vest': 'vest', 'safety-vest': 'vest', 'hi-vis': 'vest', 'hi-vis-vest': 'vest', 'reflective-vest': 'vest', 'yelek': 'vest',
    'gloves': 'gloves', 'glove': 'gloves', 'safety-gloves': 'gloves', 'eldiven': 'gloves',
    'goggles': 'goggles', 'glasses': 'goggles', 'safety-glasses': 'goggles', 'gozluk': 'goggles',
    'shoes': 'shoes', 'boots': 'shoes', 'safety-shoes': 'shoes', 'safety-boots': 'shoes', 'ayakkabi': 'shoes',
    'apron': 'apron', 'onluk': 'apron',
    'mask': 'mask', 'face-mask': 'mask', 'maske': 'mask',
    'faceshield': 'faceshield', 'face-shield': 'faceshield', 'shield': 'faceshield', 'siper': 'faceshield',
    'earmuff': 'earmuff', 'earmuffs': 'earmuff', 'ear-muffs': 'earmuff', 'ear-protection': 'earmuff', 'kulaklik': 'earmuff',
    'harness': 'harness', 'safety-harness': 'harness', 'safety-belt': 'harness', 'emniyet-kemeri': 'harness',
    'coverall': 'coverall', 'coveralls': 'coverall', 'protective-suit': 'coverall', 'safety-suit': 'coverall', 'suit': 'coverall', 'tulum': 'coverall',
    'sleeves': 'sleeves', 'sleeve': 'sleeves', 'arm-sleeves': 'sleeves', 'kolluk': 'sleeves',
}
# Model etiketi → nesne sınıfı (KKD dışı)
OBJ_ALIAS = {
    'person': 'person', 'forklift': 'forklift', 'fork-lift': 'forklift', 'pallet-jack': 'forklift', 'transpalet': 'forklift',
    'vehicle': 'vehicle', 'car': 'car', 'truck': 'truck', 'bus': 'bus',
    'ladder': 'ladder', 'merdiven': 'ladder', 'safety-cone': 'cone', 'cone': 'cone',
    'fall-detected': 'fall', 'fall': 'fall', 'fallen': 'fall', 'fallen-person': 'fall',
}
NEG_PREFIX = ('no-', 'no_', 'no ', 'without-', 'without ')


def map_label(label):
    """Model etiketi → {'key': KKD anahtarı | None, 'neg': eksik mi, 'cls': nesne sınıfı | None}."""
    n = (label or '').strip().lower()
    neg = False
    for p in NEG_PREFIX:
        if n.startswith(p):
            neg, n = True, n[len(p):].lstrip('-_ ')
            break
    n = n.replace(' ', '-').replace('_', '-')
    key = PPE_ALIAS.get(n)
    return {'key': key, 'neg': neg and bool(key), 'cls': None if key else OBJ_ALIAS.get(n)}


def _letterbox(img, size, center):
    """Kareyi oranı koruyarak size×size'a sığdırır (114 dolgu). center=False: sol-üst (YOLOX); True: ortalı (YOLOv8)."""
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nw, nh = max(1, int(round(w * r))), max(1, int(round(h * r)))
    out = np.full((size, size, 3), 114, np.uint8)
    dx, dy = ((size - nw) // 2, (size - nh) // 2) if center else (0, 0)
    out[dy:dy + nh, dx:dx + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return out, r, dx, dy


def _nms(boxes, scores, classes, conf, iou):
    if not len(boxes):
        return []
    try:
        keep = cv2.dnn.NMSBoxesBatched(boxes, scores, classes, conf, iou)
    except AttributeError:   # eski OpenCV: sınıf ayrımı kutuları kaydırarak yapılır
        off = [[b[0] + c * 4096, b[1], b[2], b[3]] for b, c in zip(boxes, classes)]
        keep = cv2.dnn.NMSBoxes(off, scores, conf, iou)
    return [int(i) for i in np.array(keep).reshape(-1)]


class _Net:
    """Tek bir ONNX modeli: GPU (FP16) → CPU geri dönüşlü yükleme."""

    def __init__(self, path, probe_shape, want_gpu=True):
        self.path, self.backend = path, 'cpu'
        self.net = cv2.dnn.readNetFromONNX(str(path))
        self.outs = list(self.net.getUnconnectedOutLayersNames())
        probe = np.zeros(probe_shape, np.float32)
        gpu = False
        if want_gpu:
            try:
                gpu = cv2.cuda.getCudaEnabledDeviceCount() > 0
            except Exception:   # noqa: BLE001 — CUDA'sız OpenCV
                gpu = False
        if gpu:
            try:
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA_FP16)
                self.run(probe)
                self.backend = 'cuda_fp16'
                return
            except Exception as e:   # noqa: BLE001 — GPU'da çalışmayan katman: CPU'ya düş
                log.warning('%s GPU\'da çalışmadı (%s) → CPU', path.name, str(e)[:120])
                self.net = cv2.dnn.readNetFromONNX(str(path))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.run(probe)

    def run(self, blob):
        self.net.setInput(blob)
        out = self.net.forward(self.outs)
        return [np.asarray(o) for o in out]


class Engine:
    """Modelleri tembel yükler; çıkarım çağrıları tek iş parçacığından (işleyici) gelir, yine de kilitlidir."""

    def __init__(self, want_gpu=True, model_dir=None):
        self.dir = model_dir or MODEL_DIR
        self.want_gpu = want_gpu
        self.lock = threading.Lock()
        self.nets = {}      # ad → _Net | None (None: yok / yüklenemedi)
        self.errors = {}    # ad → hata metni
        self.meta = {}      # ad → {'size', 'labels', 'mapped'}

    # ---- yükleme
    def _load(self, name, file, probe_shape):
        if name in self.nets:
            return self.nets[name]
        path = self.dir / file
        net = None
        if path.is_file():
            try:
                net = _Net(path, probe_shape, self.want_gpu)
                log.info('İSG modeli yüklendi: %s (%s)', file, net.backend)
            except Exception as e:   # noqa: BLE001
                self.errors[name] = str(e)[:200]
                log.exception('İSG modeli yüklenemedi: %s', file)
        self.nets[name] = net
        return net

    def _objects_net(self):
        for file, size in (('yolox_s.onnx', 640), ('yolox_tiny.onnx', 416)):
            if (self.dir / file).is_file():
                net = self._load('objects', file, (1, 3, size, size))
                if net:
                    self.meta.setdefault('objects', {'size': size, 'file': file})
                return net
        self.nets.setdefault('objects', None)
        return None

    def _labels(self, path):
        try:
            return [ln.strip() for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip()]
        except OSError:
            return None

    def _yolo_nets(self):
        """KKD modeli + ek (ws_*.onnx) modeller: [(ad, _Net, etiketler, eşlenmiş)]."""
        out = []
        files = [('ppe', self.dir / 'ppe.onnx')] + sorted((p.stem, p) for p in self.dir.glob('ws_*.onnx'))
        for name, path in files:
            if not path.is_file():
                self.nets.setdefault(name, None)
                continue
            if name not in self.meta:
                labels = self._labels(path.with_suffix('.labels')) or (PPE_LABELS if name == 'ppe' else None)
                if not labels:
                    self.nets[name] = None
                    self.errors[name] = 'Etiket dosyası (.labels) yok'
                    continue
                self.meta[name] = {'size': 640, 'labels': labels, 'mapped': [map_label(x) for x in labels], 'file': path.name}
            net = self._load(name, path.name, (1, 3, 640, 640))
            if net:
                out.append((name, net, self.meta[name]['labels'], self.meta[name]['mapped']))
        return out

    def _pose_net(self):
        return self._load('pose', 'rtmpose_s.onnx', (1, 3, 256, 192))

    def caps(self):
        """Yüklü modellerin sağladığı yetenekler (kural motoru "model gerekli" kararını buna göre verir)."""
        with self.lock:
            obj = self._objects_net()
            yolo = self._yolo_nets()
            pose = self._pose_net()
        ppe, classes = set(), set(COCO) if obj else set()
        for _n, _net, _labels, mapped in yolo:
            for m in mapped:
                if m['key']:
                    ppe.add(m['key'] + (':neg' if m['neg'] else ''))
                elif m['cls']:
                    classes.add(m['cls'])
        models = {}
        for name, net in self.nets.items():
            models[name] = {'file': (self.meta.get(name) or {}).get('file'), 'backend': net.backend if net else None,
                            'error': self.errors.get(name)}
        backends = {n.backend for n in self.nets.values() if n}
        return {'objects': bool(obj), 'pose': bool(pose), 'ppe': sorted(ppe), 'classes': sorted(classes),
                'backend': 'cuda_fp16' if 'cuda_fp16' in backends else ('cpu' if backends else None), 'models': models}

    # ---- nesne (YOLOX)
    def objects(self, frame, conf=0.35, iou=0.45):
        """→ [{'cls', 'box': [x, y, w, h] piksel, 'score'}] (COCO sınıfları)."""
        with self.lock:
            net = self._objects_net()
            if not net:
                return []
            size = self.meta['objects']['size']
            img, r, _dx, _dy = _letterbox(frame, size, center=False)
            blob = np.ascontiguousarray(img.transpose(2, 0, 1)[None].astype(np.float32))
            out = net.run(blob)[0]
        out = out.reshape(-1, out.shape[-1])
        grid = self.meta['objects'].get('grid')
        if grid is None or len(grid[0]) != len(out):
            gs, ss = [], []
            for s in (8, 16, 32):
                n = size // s
                xv, yv = np.meshgrid(np.arange(n), np.arange(n))
                gs.append(np.stack((xv, yv), 2).reshape(-1, 2))
                ss.append(np.full((n * n, 1), s))
            grid = (np.concatenate(gs).astype(np.float32), np.concatenate(ss).astype(np.float32))
            self.meta['objects']['grid'] = grid
        if len(grid[0]) != len(out):
            return []
        xy = (out[:, :2] + grid[0]) * grid[1]
        wh = np.exp(np.clip(out[:, 2:4], -10, 10)) * grid[1]
        scores = out[:, 4:5] * out[:, 5:]
        cls = scores.argmax(1)
        sc = scores[np.arange(len(cls)), cls]
        m = sc >= conf
        if not m.any():
            return []
        xy, wh, cls, sc = xy[m], wh[m], cls[m], sc[m]
        boxes = np.concatenate((xy - wh / 2, wh), 1) / r
        keep = _nms(boxes.tolist(), sc.tolist(), cls.tolist(), conf, iou)
        h, w = frame.shape[:2]
        res = []
        for i in keep:
            x, y, bw, bh = boxes[i]
            x, y = max(0.0, float(x)), max(0.0, float(y))
            bw, bh = min(float(bw), w - x), min(float(bh), h - y)
            if bw > 2 and bh > 2:
                res.append({'cls': COCO[int(cls[i])], 'box': [x, y, bw, bh], 'score': round(float(sc[i]), 3)})
        return res

    # ---- KKD + ek modeller (YOLOv8)
    def ppe(self, frame, conf=0.35, iou=0.45):
        """→ [{'label', 'key', 'neg', 'cls', 'box', 'score', 'model'}] — key: KKD anahtarı; cls: nesne sınıfı."""
        res = []
        with self.lock:
            nets = self._yolo_nets()
            if not nets:
                return res
            img, r, dx, dy = _letterbox(frame, 640, center=True)
            blob = np.ascontiguousarray(img[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
            raws = [(name, net.run(blob)[0], labels, mapped) for name, net, labels, mapped in nets]
        h, w = frame.shape[:2]
        for name, out, labels, mapped in raws:
            out = out[0] if out.ndim == 3 else out
            if out.shape[0] == 4 + len(labels):
                out = out.T
            if out.shape[1] != 4 + len(labels):
                self.errors[name] = f'Çıkış biçimi etiket sayısıyla uyuşmuyor ({out.shape} / {len(labels)} sınıf)'
                continue
            scores = out[:, 4:]
            cls = scores.argmax(1)
            sc = scores[np.arange(len(cls)), cls]
            m = sc >= conf
            if not m.any():
                continue
            b, cls, sc = out[m, :4], cls[m], sc[m]
            boxes = np.stack(((b[:, 0] - b[:, 2] / 2 - dx) / r, (b[:, 1] - b[:, 3] / 2 - dy) / r, b[:, 2] / r, b[:, 3] / r), 1)
            for i in _nms(boxes.tolist(), sc.tolist(), cls.tolist(), conf, iou):
                x, y, bw, bh = boxes[i]
                x, y = max(0.0, float(x)), max(0.0, float(y))
                bw, bh = min(float(bw), w - x), min(float(bh), h - y)
                if bw <= 2 or bh <= 2:
                    continue
                mp = mapped[int(cls[i])]
                res.append({'label': labels[int(cls[i])], 'key': mp['key'], 'neg': mp['neg'], 'cls': mp['cls'],
                            'box': [x, y, bw, bh], 'score': round(float(sc[i]), 3), 'model': name})
        return res

    # ---- vücut duruşu (RTMPose, SimCC)
    def pose(self, frame, boxes, limit=8):
        """Kişi kutuları (piksel [x,y,w,h]) → her biri için 17 eklem [[x, y, güven]] (piksel); model yoksa None'lar."""
        out = [None] * len(boxes)
        with self.lock:
            net = self._pose_net()
            if not net:
                return out
            order = sorted(range(len(boxes)), key=lambda i: -boxes[i][2] * boxes[i][3])[:limit]
            mean = np.array([123.675, 116.28, 103.53], np.float32)
            std = np.array([58.395, 57.12, 57.375], np.float32)
            for i in order:
                x, y, bw, bh = boxes[i]
                cx, cy = x + bw / 2, y + bh / 2
                bw, bh = bw * 1.25, bh * 1.25
                if bw > bh * 0.75:      # 192:256 oranına tamamla
                    bh = bw / 0.75
                else:
                    bw = bh * 0.75
                src = np.float32([[cx - bw / 2, cy - bh / 2], [cx + bw / 2, cy - bh / 2], [cx - bw / 2, cy + bh / 2]])
                dst = np.float32([[0, 0], [192, 0], [0, 256]])
                crop = cv2.warpAffine(frame, cv2.getAffineTransform(src, dst), (192, 256), flags=cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
                blob = ((crop[:, :, ::-1].astype(np.float32) - mean) / std).transpose(2, 0, 1)[None]
                try:
                    res = net.run(np.ascontiguousarray(blob))
                except Exception:   # noqa: BLE001
                    log.exception('duruş çıkarımı hatası')
                    continue
                sx = next((o for o in res if o.shape[-1] == 384), None)
                sy = next((o for o in res if o.shape[-1] == 512), None)
                if sx is None or sy is None:
                    continue
                sx, sy = sx.reshape(17, 384), sy.reshape(17, 512)
                px, py = sx.argmax(1) / 2.0, sy.argmax(1) / 2.0
                conf = np.minimum(sx.max(1), sy.max(1))
                out[i] = [[float(cx - bw / 2 + px[k] / 192 * bw), float(cy - bh / 2 + py[k] / 256 * bh), round(float(conf[k]), 3)]
                          for k in range(17)]
        return out
