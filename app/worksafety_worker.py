"""İş Güvenliği işleyicisi — kamera servisinin içinde çalışan tek iş parçacığı.

Çalışan kameraların son karelerini sırayla dolaşır (round-robin): nesne / KKD / duruş çıkarımı → kural motoru → onay
katmanı → olay (kare + klip), ısı haritası ve denetim istatistikleri. Yüz tanıma iş parçacıklarına dokunmaz; yalnız
`throttle` sözlüğü üzerinden (işlem gücü yetmediğinde) yüz tanımayı seyreltir ya da durdurur.
Görüntü dışarı gönderilmez; her şey bu makinede işlenir ve yerel veritabanına / diske yazılır.
"""
import json
import logging
import os
import queue
import threading
import time
import uuid

import cv2
import numpy as np

from . import db
from . import worksafety as W
from . import worksafety_detect as D
from . import worksafety_rules as R

log = logging.getLogger('worksafety')
FACE_STEPS = (1, 3, 8, None)       # yüz tanıma aralığı çarpanı; None: durdur
SLOW_CYCLE, FAST_CYCLE = 4.0, 2.5  # sn: tur bu kadar uzarsa "kötü", bunun altındaysa "iyi"
STALE = 5.0                        # sn: bundan eski kare işlenmez (akış kopuk)
PHOTO_WIDTH = 1280
CLIP_AFTER = 3.0                   # sn: klip, olaydan sonraki bu kadar süreyi de kapsar
CLIP_FPS = 5


def _cell(x, y):
    return min(W.GRID_H - 1, max(0, int(y * W.GRID_H))) * W.GRID_W + min(W.GRID_W - 1, max(0, int(x * W.GRID_W)))


def _pixelate(img, x1, y1, x2, y2):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return
    small = cv2.resize(img[y1:y2, x1:x2], (5, 5), interpolation=cv2.INTER_AREA)
    img[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)


def _hide_heads(img, persons):
    """Kişilerin baş bölgesini geri döndürülemez biçimde pikselleştirir. persons: [{'box' (0-1), 'kpts'?}]."""
    h, w = img.shape[:2]
    for p in persons:
        x, y, bw, bh = p['box']
        face = [k for k in (p.get('kpts') or [])[:5] if k[2] >= 0.3]
        if len(face) >= 2:      # duruş modeli: burun / göz / kulak noktalarının çevresi (baret görünür kalır)
            cx, cy = sum(k[0] for k in face) / len(face), sum(k[1] for k in face) / len(face)
            r = max(max(abs(k[0] - cx) for k in face) * 1.6, bw * 0.16)
            _pixelate(img, (cx - r) * w, (cy - r * w / h * 1.1) * h, (cx + r) * w, (cy + r * w / h * 1.3) * h)
        else:                   # tahmin: kutunun üst bölümü
            _pixelate(img, (x + bw * 0.2) * w, (y + bh * 0.03) * h, (x + bw * 0.8) * w, (y + bh * 0.21) * h)


def _write_mp4(frames, path, fps=CLIP_FPS):
    """Tarayıcıda oynayan H.264 MP4. PyAV yoksa OpenCV (avc1 → mp4v) ile yazılır."""
    if not frames:
        return False
    h, w = frames[0].shape[:2]
    w, h = w - w % 2, h - h % 2
    try:
        import av
        with av.open(str(path), 'w', options={'movflags': 'faststart'}) as out:
            st = out.add_stream('libx264', rate=fps)
            st.width, st.height, st.pix_fmt = w, h, 'yuv420p'
            st.options = {'preset': 'veryfast', 'crf': '28'}
            for fr in frames:
                fr = fr if fr.shape[:2] == (h, w) else cv2.resize(fr, (w, h))
                for pkt in st.encode(av.VideoFrame.from_ndarray(np.ascontiguousarray(fr), format='bgr24')):
                    out.mux(pkt)
            for pkt in st.encode():
                out.mux(pkt)
        return True
    except Exception:   # noqa: BLE001 — PyAV / libx264 yok
        pass
    for cc in ('avc1', 'mp4v'):
        wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*cc), fps, (w, h))
        if not wr.isOpened():
            continue
        try:
            for fr in frames:
                wr.write(fr if fr.shape[:2] == (h, w) else cv2.resize(fr, (w, h)))
        finally:
            wr.release()
        return True
    return False


class Worker:
    def __init__(self, running, throttle):
        self.running, self.throttle = running, throttle     # kamera servisinin {id: (imza, Camera)} sözlüğü, yüz kısma bayrağı
        self.engine = D.Engine()
        self.caps = {}
        self.cfg = W.default_config()
        self.rules = R.effective(self.cfg)
        self.tracker = R.Tracker()
        self.mem, self.scenes, self.seen = {}, {}, {}
        self.stats, self.heat = {}, {}
        self.media = queue.Queue(maxsize=24)
        self.level, self.bad, self.good = 0, 0, 0
        self.n_cycle = 0
        self.errors = []
        self.last = {'cfg': 0.0, 'flush': 0.0, 'status': 0.0, 'purge': 0.0}
        self.cycle_s = self.cams_active = 0

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name='worksafety').start()
        threading.Thread(target=self._media_loop, daemon=True, name='worksafety-media').start()

    # ---- kamera servisi sorar: bu kamera İSG için çalıştırılsın mı?
    def wants(self, cid):
        return bool(self.cfg.get('enabled') and self.caps.get('objects') and W.camera_config(self.cfg, cid))

    # ---- ana döngü
    def _loop(self):
        try:
            W.LIVE_DIR.mkdir(parents=True, exist_ok=True)
            self.caps = self.engine.caps()
            log.info('iş güvenliği işleyicisi: %s, nesne=%s, duruş=%s, KKD=%s', self.caps.get('backend'), self.caps.get('objects'),
                     self.caps.get('pose'), ','.join(self.caps.get('ppe') or []) or '-')
        except Exception:   # noqa: BLE001
            log.exception('modeller yüklenemedi')
            self._err('Modeller yüklenemedi')
        while True:
            t0 = time.time()
            try:
                self._housekeeping(t0)
                n = self._cycle() if self.cfg.get('enabled') else 0
                self.cams_active = n
            except Exception:   # noqa: BLE001
                log.exception('iş güvenliği turu hatası')
                self._err('Tur hatası (günlüğe bakın)')
                n = 0
            dur = time.time() - t0
            if n:
                self.cycle_s = round(dur, 2)
            self._throttle(dur, n)
            time.sleep(max(0.3, float(self.cfg.get('interval') or 2.0) - dur) if n else 2.0)

    def _err(self, msg):
        self.errors = (self.errors + [f'{time.strftime("%H:%M:%S")} {msg}'])[-5:]

    def _housekeeping(self, now):
        if now - self.last['cfg'] >= 10:
            self.last['cfg'] = now
            with db.connect() as conn:
                self.cfg = W.get_config(conn)
            self.rules = R.effective(self.cfg)
        if now - self.last['flush'] >= 60:
            self.last['flush'] = now
            self._flush()
        if now - self.last['status'] >= 10:
            self.last['status'] = now
            self._write_status(now)
        if now - self.last['purge'] >= 6 * 3600:
            self.last['purge'] = now
            with db.connect() as conn:
                n = W.purge(conn, self.cfg.get('retention_days') or 90)
            if n:
                log.info('saklama süresi dolan %s uyarı silindi', n)

    def _cycle(self):
        try:
            cams = [(cid, v[1]) for cid, v in list(self.running.items())]
        except RuntimeError:    # sözlük o anda değişti; sonraki turda
            return 0
        self.n_cycle += 1
        n = 0
        for cid, cam in cams:
            ccfg = W.camera_config(self.cfg, cid)
            if not ccfg:
                continue
            need = R.needs(ccfg, self.rules, self.caps)
            if not need['active']:
                continue
            latest = cam.latest
            if not latest or time.time() - latest[0] > STALE or self.seen.get(cid) == latest[0]:
                continue
            self.seen[cid] = latest[0]
            n += 1
            try:
                self._process(cid, cam, ccfg, need, latest[0], latest[1])
            except Exception:   # noqa: BLE001 — bir kameradaki hata diğerlerini durdurmaz
                log.exception('iş güvenliği işleme hatası (kamera %s)', cid)
                self._err(f'Kamera {cid}: işleme hatası')
        return n

    # ---- gözlem
    def _norm(self, dets, w, h):
        return [{**d, 'box': [d['box'][0] / w, d['box'][1] / h, d['box'][2] / w, d['box'][3] / h]} for d in dets]

    def _observe(self, cid, cam, ccfg, need, t, frame):
        h, w = frame.shape[:2]
        aspect = w / h
        dets = self._norm(self.engine.objects(frame), w, h)
        persons = [{'box': d['box'], 'cls': 'person', 'score': d['score']} for d in dets if d['cls'] == 'person' and d['score'] >= 0.4]
        vehicles = [{'box': d['box'], 'cls': d['cls']} for d in dets if d['cls'] in R.VEHICLES]
        objects = [{'box': d['box'], 'cls': d['cls']} for d in dets if d['cls'] != 'person' and d['cls'] not in R.VEHICLES]
        ladders, falls = [], []
        if need['ppe'] and (persons or self.n_cycle % 3 == 0):
            pd = self._norm(self.engine.ppe(frame), w, h)
            for d in pd:
                if d['cls'] == 'ladder':
                    ladders.append(d['box'])
                elif d['cls'] == 'fall':
                    falls.append(d['box'])
                elif d['cls'] in R.VEHICLES and not any(R.iou(d['box'], v['box']) > 0.5 for v in vehicles):
                    vehicles.append({'box': d['box'], 'cls': d['cls']})
            ppe = set(self.caps.get('ppe') or [])
            R.assign_ppe(persons, pd, inferred=[k for k in R.KKD if k in ppe and k + ':neg' not in ppe])
        if need['pose'] and persons:
            px = [[p['box'][0] * w, p['box'][1] * h, p['box'][2] * w, p['box'][3] * h] for p in persons]
            for p, k in zip(persons, self.engine.pose(frame, px, limit=8)):
                p['kpts'] = [[q[0] / w, q[1] / h, q[2]] for q in k] if k is not None else None
        if need['motion'] and (persons or vehicles):
            prev = None
            for bt, img in reversed(list(cam.clipbuf)):
                if 0.6 <= t - bt <= 2.0:
                    prev = (bt, img)
                    if t - bt >= 0.9:
                        break
                elif t - bt > 2.0:
                    break
            if prev:
                ph, pw = prev[1].shape[:2]
                pdets = [d for d in self._norm(self.engine.objects(prev[1]), pw, ph) if d['cls'] == 'person' or d['cls'] in R.VEHICLES]
                R.match_motion(persons + vehicles, pdets, t - prev[0], aspect)
        if need['color']:
            mz = [z for z in ccfg['zones'] if z['type'] == 'machine']
            for p in persons:
                if any(R.in_poly(R.foot(p['box']), z['points']) for z in mz):
                    x, y, bw, bh = p['box']
                    crop = frame[int((y + bh * 0.2) * h):int((y + bh * 0.55) * h), int((x + bw * 0.2) * w):int((x + bw * 0.8) * w)]
                    p['color'] = R.dominant_color(crop)
        static = None
        if need['static']:
            sc = self.scenes.setdefault(cid, R.StaticScene())
            sc.update(frame, t, [o['box'] for o in persons + vehicles])
            if sc.ready():
                static = {z['id']: sc.ratio(z['points']) for z in ccfg['zones'] if z['type'] in ('vehicle_lane', 'crossing')}
        lt = time.localtime(t)
        return {'t': t, 'aspect': aspect, 'clock': lt.tm_hour * 60 + lt.tm_min, 'persons': persons, 'vehicles': vehicles,
                'objects': objects, 'ladders': ladders, 'falls': falls, 'static': static}

    def _process(self, cid, cam, ccfg, need, t, frame):
        obs = self._observe(cid, cam, ccfg, need, t, frame)
        results = R.evaluate(obs, ccfg, self.rules, self.caps, self.mem.setdefault(cid, {}))
        events = self.tracker.step(cid, results, t, self.rules)
        day, hour = W.local_day_hour(t)
        st = self.stats.setdefault((day, hour), {})
        viol = {}
        for r in results:
            x = st.setdefault((cid, r['rule']), [0, 0])
            x[0] += r['checks']
            x[1] += min(r['viol'], r['checks'])
            if r['viol'] > 0:
                v = viol.setdefault(r['rule'], {'rule': r['rule'], 'name': self.rules[r['rule']]['name'],
                                                'level': self.rules[r['rule']]['level'], 'boxes': []})
                v['boxes'] += [[round(c, 4) for c in b] for b in r['boxes']]
        hp = self.heat.setdefault((cid, day, 'person'), {})
        for p in obs['persons']:
            c = _cell(*R.foot(p['box']))
            hp[c] = hp.get(c, 0) + 1
        hv = self.heat.setdefault((cid, day, 'vehicle'), {})
        for v in obs['vehicles']:
            c = _cell(*R.center(v['box']))
            hv[c] = hv.get(c, 0) + 1
        for e in events:
            he = self.heat.setdefault((cid, day, 'event'), {})
            for b in e['boxes'] or [[0.45, 0.45, 0.1, 0.1]]:
                c = _cell(*R.center(b))
                he[c] = he.get(c, 0) + e['risk']
            self._emit(cid, cam, ccfg, e, obs, frame)
        bad = [b for v in viol.values() for b in v['boxes']]
        self._write_live(cid, {
            't': round(t, 2), 'persons': [{'box': [round(c, 4) for c in p['box']], 'bad': any(R.iou(p['box'], b) > 0.5 for b in bad)}
                                         for p in obs['persons']],
            'vehicles': [[round(c, 4) for c in v['box']] for v in obs['vehicles']], 'viol': list(viol.values())})

    def _write_live(self, cid, data):
        try:
            p = W.LIVE_DIR / f'{cid}.ws.json'
            tmp = p.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, separators=(',', ':')))
            os.replace(tmp, p)
        except OSError:
            pass

    # ---- olay
    def _emit(self, cid, cam, ccfg, e, obs, frame):
        try:
            name = cam.row['name']
        except Exception:   # noqa: BLE001
            name = None
        with db.connect() as conn:
            eid = W.add_event(conn, cid, name, e)
        log.info('uyarı #%s kamera %s: %s (%s)%s', eid, cid, e['name'], e['level'], f' — {e["detail"]}' if e.get('detail') else '')
        zone = next((z for z in ccfg['zones'] if z['id'] == e.get('zone')), None)
        job = {'id': eid, 'cam': cam, 'frame': frame, 'boxes': e['boxes'], 'zone': zone['points'] if zone else None,
               'persons': [{'box': p['box'], 'kpts': p.get('kpts')} for p in obs['persons']], 'at': time.time(),
               'blur': bool(self.cfg.get('blur_faces')), 'clip': bool(self.cfg.get('clip'))}
        try:
            self.media.put_nowait(job)
        except queue.Full:
            log.warning('medya kuyruğu dolu; uyarı #%s görselsiz kaydedildi', eid)

    def _media_loop(self):
        W.EVENT_DIR.mkdir(parents=True, exist_ok=True)
        while True:
            job = self.media.get()
            try:
                self._photo(job)
                if job['clip']:
                    wait = job['at'] + CLIP_AFTER - time.time()
                    if wait > 0:
                        time.sleep(wait)
                    self._clip(job)
            except Exception:   # noqa: BLE001 — görsel yazılamasa da uyarı kaydı durur
                log.exception('uyarı görseli yazılamadı (#%s)', job.get('id'))

    def _photo(self, job):
        img = job['frame']
        h, w = img.shape[:2]
        if w > PHOTO_WIDTH:
            img = cv2.resize(img, (PHOTO_WIDTH, int(h * PHOTO_WIDTH / w)), interpolation=cv2.INTER_AREA)
        else:
            img = img.copy()
        h, w = img.shape[:2]
        if job['blur']:
            _hide_heads(img, job['persons'])
        if job['zone']:
            cv2.polylines(img, [np.int32([[p[0] * w, p[1] * h] for p in job['zone']])], True, (0, 200, 255), 2, cv2.LINE_AA)
        for b in job['boxes']:
            cv2.rectangle(img, (int(b[0] * w), int(b[1] * h)), (int((b[0] + b[2]) * w), int((b[1] + b[3]) * h)), (40, 40, 235), 3, cv2.LINE_AA)
        name = f'{uuid.uuid4().hex}.jpg'
        ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if ok:
            (W.EVENT_DIR / name).write_bytes(buf.tobytes())
            with db.connect() as conn:
                conn.execute('UPDATE ws_events SET photo = ? WHERE id = ?', (f'wsevents/{name}', job['id']))

    def _clip(self, job):
        frames = [f.copy() if job['blur'] else f for _t, f in list(job['cam'].clipbuf)]
        if len(frames) < CLIP_FPS:
            return
        if job['blur']:
            for fr in frames:
                h, w = fr.shape[:2]
                ps = [{'box': [d['box'][0] / w, d['box'][1] / h, d['box'][2] / w, d['box'][3] / h]}
                      for d in self.engine.objects(fr, conf=0.3) if d['cls'] == 'person']
                _hide_heads(fr, ps)
        name = f'{uuid.uuid4().hex}.mp4'
        if _write_mp4(frames, W.EVENT_DIR / name):
            with db.connect() as conn:
                conn.execute('UPDATE ws_events SET clip = ? WHERE id = ?', (f'wsevents/{name}', job['id']))

    # ---- kayıt
    def _flush(self):
        stats, self.stats = self.stats, {}
        heat, self.heat = self.heat, {}
        if not stats and not heat:
            return
        try:
            with db.connect() as conn:
                for (day, hour), items in stats.items():
                    W.stats_add(conn, day, hour, items)
                for (cid, day, kind), cells in heat.items():
                    W.heat_add(conn, cid, day, kind, cells)
        except Exception:   # noqa: BLE001
            log.exception('istatistik / ısı haritası yazılamadı')

    def _write_status(self, now):
        try:
            total = len(self.running)
        except Exception:   # noqa: BLE001
            total = 0
        try:
            load = round(os.getloadavg()[0], 1)
        except OSError:
            load = None
        mult = FACE_STEPS[self.level]
        st = {'ts': now, 'at': db.now(), 'backend': self.caps.get('backend'), 'objects': bool(self.caps.get('objects')),
              'pose': bool(self.caps.get('pose')), 'ppe': self.caps.get('ppe') or [], 'classes_extra': [c for c in (self.caps.get('classes') or []) if c not in D.COCO],
              'models': self.caps.get('models') or {}, 'cycle_s': self.cycle_s, 'cams_total': total, 'cams_active': self.cams_active,
              'faces_level': self.level, 'faces_mult': mult, 'faces_off': mult is None, 'load': load, 'cores': os.cpu_count(),
              'queue': self.media.qsize(), 'errors': self.errors}
        try:
            with db.connect() as conn:
                W.set_status(conn, st)
        except Exception:   # noqa: BLE001
            log.exception('durum yazılamadı')

    # ---- yüz tanıma kısma ("gerekiyorsa yüz tanımayı durdur")
    def _throttle(self, dur, n):
        mode = self.cfg.get('faces_mode') if self.cfg.get('enabled') else 'on'
        if mode == 'on':
            lvl = 0
        elif mode == 'off':
            lvl = len(FACE_STEPS) - 1
        else:
            lvl = self.level
            try:
                load, cores = os.getloadavg()[0], os.cpu_count() or 1
            except OSError:
                load, cores = 0, 1
            if n and (dur > SLOW_CYCLE or load > cores * 1.1):
                self.bad, self.good = self.bad + 1, 0
            elif dur < FAST_CYCLE and load < cores * 0.9:
                self.good, self.bad = self.good + 1, 0
            if self.bad >= 3 and lvl < len(FACE_STEPS) - 1:
                lvl, self.bad = lvl + 1, 0
            elif self.good >= 10 and lvl > 0:
                lvl, self.good = lvl - 1, 0
        if lvl != self.level:
            log.info('yüz tanıma kısma düzeyi %s → %s (tur %.1f sn)', self.level, lvl, dur)
            self.level = lvl
        mult = FACE_STEPS[lvl]
        self.throttle['off'], self.throttle['mult'] = mult is None, mult or 1
